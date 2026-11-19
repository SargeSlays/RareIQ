'use strict';
// A separate speaker renderer receives only selected public post-mix PCM.
const path=require('node:path'),http=require('node:http'),{randomUUID}=require('node:crypto');
const CHANNELS=Object.freeze({control:'producer:monitor:control',health:'producer:monitor:health',pcm:'producer:monitor:pcm',ack:'producer:monitor:ack'});
const DOCUMENT='<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src blob:; worker-src blob:"><title>Local public audio monitor</title>';
function createLocalMonitor({BrowserWindow,ipcMain,baseDir=__dirname,timeoutMs=1500,createServer=http.createServer}={}){
  let window=null,server=null,monitorUrl=null,nonce=null,ready=false,starting=null,pending=null,sequence=0,timer=null,finishStart=null;
  const code=()=>Object.assign(Error('rehearsal_monitor_unavailable'),{code:'rehearsal_monitor_unavailable'});
  const owned=event=>{try{return window&&!window.isDestroyed()&&event.sender===window.webContents&&event.senderFrame===window.webContents.mainFrame&&event.senderFrame.url===monitorUrl&&window.webContents.getURL()===monitorUrl;}catch(_){return false;}};
  function stop(){ready=false;clearTimeout(timer);finishStart?.(false);finishStart=null;const item=pending;pending=null;if(item){clearTimeout(item.timer);item.resolve(false);}const target=window,listener=server;window=null;server=null;monitorUrl=null;nonce=null;if(target&&!target.isDestroyed())target.destroy();if(listener){try{listener.closeAllConnections?.();listener.close();}catch(_){}}}
  function health(event,value){if(!owned(event)||value?.nonce!==nonce||typeof value.ready!=='boolean')return;ready=value.ready;if(!ready){finishStart?.(false);if(pending){const item=pending;pending=null;clearTimeout(item.timer);item.resolve(false);}}else finishStart?.(true);}
  function ack(event,value){if(!owned(event)||value?.nonce!==nonce||!pending||value.seq!==pending.seq)return;const item=pending;pending=null;clearTimeout(item.timer);item.resolve(true);}
  ipcMain.on(CHANNELS.health,health);ipcMain.on(CHANNELS.ack,ack);
  function prepare(){
    if(ready&&window&&!window.isDestroyed())return Promise.resolve();if(starting)return starting;
    const work=new Promise((resolve,reject)=>{
      nonce=randomUUID();sequence=0;finishStart=value=>{if(!finishStart)return;finishStart=null;clearTimeout(timer);value?resolve():reject(code());};timer=setTimeout(()=>{finishStart?.(false);stop();},timeoutMs);timer.unref?.();
      try{
        const owner=nonce,listener=server=createServer((request,response)=>{if(!monitorUrl||request.method!=='GET'||request.headers.host!==new URL(monitorUrl).host||request.url!==new URL(monitorUrl).pathname){response.writeHead(404);response.end();return;}response.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; script-src blob:; worker-src blob:",'X-Content-Type-Options':'nosniff'});response.end(DOCUMENT);});
        listener.once('error',()=>{if(server===listener)stop();});listener.listen(0,'127.0.0.1',()=>{try{
        if(server!==listener||nonce!==owner){try{listener.close();}catch(_){}return;}const address=listener.address();if(!address||!Number.isInteger(address.port)){stop();return;}monitorUrl='http://127.0.0.1:'+address.port+'/monitor/'+nonce;const origin=new URL(monitorUrl).origin;
        const target=window=new BrowserWindow({width:160,height:90,show:false,skipTaskbar:true,title:'Local public audio monitor',webPreferences:{preload:path.join(baseDir,'monitor-preload.cjs'),additionalArguments:['--producer-monitor-nonce='+nonce,'--producer-monitor-origin='+origin],partition:'producer-monitor-'+nonce,sandbox:true,contextIsolation:true,nodeIntegration:false,nodeIntegrationInSubFrames:false,webSecurity:true,allowRunningInsecureContent:false,webviewTag:false,backgroundThrottling:false,autoplayPolicy:'no-user-gesture-required'}});
        const contents=target.webContents;target.setMenu(null);contents.setWindowOpenHandler(()=>({action:'deny'}));contents.session.setPermissionCheckHandler(()=>false);contents.session.setPermissionRequestHandler((_c,_p,reply)=>reply(false));contents.session.setDisplayMediaRequestHandler((_request,reply)=>reply(null));
        contents.on('will-navigate',(event,url)=>{if(url!==monitorUrl)event.preventDefault();stop();});contents.on('will-redirect',event=>{event.preventDefault();stop();});contents.on('will-attach-webview',event=>event.preventDefault());contents.on('render-process-gone',stop);target.on('closed',()=>{if(window===target)stop();});
        Promise.resolve(contents.loadURL(monitorUrl)).catch(()=>{if(window===target)stop();});
        }catch(_){stop();}});
      }catch(_){stop();}
    });starting=work;return work.finally(()=>{if(starting===work)starting=null;});
  }
  function write(pcm){
    if(!ready||!window||window.isDestroyed()||pending||!Buffer.isBuffer(pcm)||pcm.length!==3840)return Promise.resolve(false);
    for(let offset=0;offset<pcm.length;offset+=4)if(!Number.isFinite(pcm.readFloatLE(offset))||Math.abs(pcm.readFloatLE(offset))>1)return Promise.resolve(false);
    const seq=sequence++;return new Promise(resolve=>{const item={seq,resolve,timer:null};pending=item;item.timer=setTimeout(()=>{if(pending!==item)return;pending=null;ready=false;resolve(false);},timeoutMs);item.timer.unref?.();try{window.webContents.send(CHANNELS.pcm,{nonce,seq,pcm:Uint8Array.from(pcm)});}catch(_){clearTimeout(item.timer);pending=null;ready=false;resolve(false);}});
  }
  return {prepare,write,stop,status:()=>({ready,running:Boolean(window&&!window.isDestroyed()),pending:Boolean(pending)}),close(){stop();ipcMain.removeListener(CHANNELS.health,health);ipcMain.removeListener(CHANNELS.ack,ack);}};
}
module.exports={createLocalMonitor,CHANNELS,DOCUMENT};
