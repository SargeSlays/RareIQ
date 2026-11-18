'use strict';
const {app,BrowserWindow,Menu,dialog,ipcMain,shell,session,desktopCapturer}=require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{pathToFileURL}=require('node:url');
const policy=require('./policy.cjs'),{Backend}=require('./backend.cjs');
app.setName('Producer, Please');app.setAppUserModelId('com.producerplease.studio');
const profile=process.env.PRODUCER_DESKTOP_QA_PROFILE||process.env.PRODUCER_DESKTOP_DATA||path.join('F:/Users',os.userInfo().username,'AppData','ProducerPlease');
if(!path.isAbsolute(profile))throw Error('Desktop data must use an absolute directory');
for(const directory of [profile,path.join(profile,'browser'),path.join(profile,'logs'),path.join(profile,'crashes')])fs.mkdirSync(directory,{recursive:true});
app.setPath('userData',profile);app.setPath('sessionData',path.join(profile,'browser'));app.setPath('logs',path.join(profile,'logs'));app.setPath('crashDumps',path.join(profile,'crashes'));
let studio,settings,backend,origin,destinations,capturePicker,quit,runtime,broadcast,polling,choosingSources;
if(!app.requestSingleInstanceLock())app.exit(0);
app.on('second-instance',()=>{if(studio){if(studio.isMinimized())studio.restore();studio.show();studio.focus();}});
function windowOptions(extra={}){return {width:1600,height:1000,minWidth:800,minHeight:600,title:'Producer, Please',icon:path.join(__dirname,'assets','icon-512.png'),backgroundColor:'#101318',autoHideMenuBar:false,...extra,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true,allowRunningInsecureContent:false,webviewTag:false,backgroundThrottling:false,...extra.webPreferences}};}
function secureWindow(window,allowed){window.webContents.setWindowOpenHandler(({url})=>{if(policy.sameStudio(url,origin)&&!new URL(url).pathname.startsWith('/guest')){const child=new BrowserWindow(windowOptions({webPreferences:{partition:'persist:producer-studio'}}));secureWindow(child,origin);child.loadURL(url);}else if(policy.allowedExternal(url)||(policy.sameStudio(url,origin)&&new URL(url).pathname.startsWith('/guest')))shell.openExternal(url);return {action:'deny'};});window.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith(allowed+'/')&&url!==allowed)event.preventDefault();});window.webContents.on('will-redirect',(event,url,_inPlace,isMainFrame)=>{if(isMainFrame!==false&&!policy.sameStudio(url,origin))event.preventDefault();});window.webContents.on('will-attach-webview',event=>event.preventDefault());}
function settingsEvent(event){return settings&&!settings.isDestroyed()&&event.sender===settings.webContents&&event.senderFrame===settings.webContents.mainFrame&&event.senderFrame.url===pathToFileURL(path.join(__dirname,'settings.html')).href;}
async function openSettings(){if(settings&&!settings.isDestroyed()){settings.show();settings.focus();return;}
  settings=new BrowserWindow(windowOptions({width:860,height:790,parent:studio,webPreferences:{preload:path.join(__dirname,'settings-preload.cjs'),partition:'persist:producer-settings'}}));settings.webContents.setWindowOpenHandler(()=>({action:'deny'}));settings.webContents.on('will-navigate',event=>event.preventDefault());await settings.loadFile(path.join(__dirname,'settings.html'));
}
async function openSources(event){
  if(!settingsEvent(event))throw Error('Untrusted request');
  if(choosingSources)return choosingSources;
  const owner=settings,target=studio;
  choosingSources=(async()=>{
    const available=()=>target&&target===studio&&!target.isDestroyed()&&policy.sameStudio(target.webContents.getURL(),origin)&&new URL(target.webContents.getURL()).pathname==='/control'&&target.webContents.mainFrame.url===target.webContents.getURL();
    if(!available())throw Error('Studio sources are unavailable. Keep this window open and try again.');
    const frame=target.webContents.mainFrame;
    let opened=false;try{opened=await target.webContents.executeJavaScript('window.ProducerDesktopNavigation?.openSources() === true',false);}catch(_){}
    if(opened!==true||!available()||target.webContents.mainFrame!==frame)throw Error('Studio sources are not ready yet. Keep this window open and try again.');
    if(target.isMinimized())target.restore();target.show();target.focus();
    if(settings===owner&&!owner.isDestroyed())owner.hide();
    return {ok:true};
  })().finally(()=>{choosingSources=null;});
  return choosingSources;
}
app.whenReady().then(async()=>{
  const fixture=process.env.PRODUCER_DESKTOP_QA_ORIGIN;
  const runtimePath=process.env.PRODUCER_DESKTOP_RUNTIME||path.join(process.resourcesPath,'runtime.json');runtime=JSON.parse(fs.readFileSync(runtimePath,'utf8'));
  if(fixture){origin=policy.studioOrigin(fixture);}else{
    backend=new Backend(runtime,path.join(profile,'backend-owner.json'));const started=await backend.start();origin=policy.studioOrigin(started.origin||started.url);
  }
  const partition=session.fromPartition('persist:producer-studio');policy.applySessionPolicy(partition,origin);
  // Device grants always require an explicit native prompt from the trusted main studio.
  partition.setPermissionRequestHandler(async(contents,permission,callback,details)=>{
    if(!['media','display-capture'].includes(permission)||!policy.sameStudio(contents.getURL(),origin)||details.isMainFrame!==true||!policy.sameStudio(details.requestingUrl,origin))return callback(false);
    if(permission==='display-capture')return callback(true);
    const response=await dialog.showMessageBox(studio,{type:'question',buttons:['Allow this time','Cancel'],defaultId:1,cancelId:1,message:'Allow Producer, Please to use your camera or microphone?',detail:'Choose Allow only after selecting a capture control in the studio.'});callback(response.response===0);
  });
  const {DestinationStore}=require('./destinations.cjs');destinations=new DestinationStore({directory:profile,cipher:require('electron').safeStorage});
  studio=new BrowserWindow(windowOptions({webPreferences:{partition:'persist:producer-studio',preload:path.join(__dirname,'preload.cjs')}}));secureWindow(studio,origin);
  const {createCapturePicker}=require('./capture-picker.cjs');capturePicker=createCapturePicker({BrowserWindow,ipcMain,desktopCapturer,studio,origin});partition.setDisplayMediaRequestHandler(capturePicker.handler);
  studio.on('close',event=>{if(backend&&!quit?.finished){event.preventDefault();app.quit();}});
  const {NativeBroadcast}=require('./broadcast.cjs'),{Encoder}=require('./encoder.cjs'),{createOutputCapture}=require('./output-capture.cjs');
  const outputSession=session.fromPartition('persist:producer-output');policy.applySessionPolicy(outputSession,origin);
  const request=async(url,body)=>{const response=await fetch(origin+url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(8000)});const value=await response.json();const preflight=!body&&url.startsWith('/api/production/native-preflight?')&&value.preflight&&typeof value.preflight.ready==='boolean';if(!response.ok||(value.ok===false&&!preflight))throw Error('studio_unavailable');return value;};
  let lastPhase='';broadcast=new NativeBroadcast({destinations,identity:backend?.started?.identity,ownerPid:process.pid,request,
    createCapture:dimensions=>createOutputCapture({BrowserWindow,ipcMain,origin,...dimensions,onError:code=>{if(broadcast?.active())broadcast.stop(code).catch(()=>{});}}),
    createEncoder:onState=>new Encoder({python:runtime.python,workerPath:runtime.encoderWorker,pythonPackages:runtime.pythonPackages,onState}),
    confirm:async profile=>{const answer=await dialog.showMessageBox(settings&&!settings.isDestroyed()?settings:studio,{type:'warning',message:'Start a live broadcast?',detail:'Your current Program picture and public audio will be sent to '+profile.name+'. Check your platform dashboard to confirm viewers can receive it.',buttons:['Cancel','Start broadcast'],defaultId:0,cancelId:0});return answer.response===1;},
    onState:value=>{if(value.phase!==lastPhase){lastPhase=value.phase;try{fs.appendFileSync(path.join(profile,'activity.jsonl'),JSON.stringify({at:new Date().toISOString(),action:'broadcast.'+value.phase,actor:'Desktop operator',identityVerified:false,destinationId:value.destinationId||null,reason:value.reason||null})+'\n');}catch(_){}}}
  });
  polling=setInterval(()=>broadcast.check().catch(()=>{}),1000);polling.unref();
  const publicBroadcast=()=>({...broadcast.status(),available:Boolean(runtime.encoderWorker&&fs.existsSync(runtime.encoderWorker)&&backend?.started?.identity)});

  ipcMain.handle('producer:info',event=>{if(!policy.trustedMain(event,studio.webContents,origin))throw Error('Untrusted request');return {name:'Producer, Please',version:app.getVersion(),desktop:true,engine:'standalone'};});
  ipcMain.handle('producer:settings',event=>{if(!policy.trustedMain(event,studio.webContents,origin))throw Error('Untrusted request');return openSettings();});
  ipcMain.handle('producer:sources:open',openSources);
  ipcMain.handle('producer:destinations:status',event=>{if(!settingsEvent(event))throw Error('Untrusted request');return destinations.public().then(value=>({...value,broadcast:publicBroadcast()}));});
  ipcMain.handle('producer:destinations:save',async(event,value)=>{if(!settingsEvent(event))throw Error('Untrusted request');return destinations.save(value);});
  ipcMain.handle('producer:destinations:remove',async(event,id)=>{if(!settingsEvent(event))throw Error('Untrusted request');if(broadcast?.active()&&broadcast.selected===id)throw Error('Stop the broadcast before removing its destination');return destinations.remove(id);});
  ipcMain.handle('producer:broadcast:prepare',async(event,value)=>{if(!settingsEvent(event))throw Error('Untrusted request');await broadcast.prepare(value);return publicBroadcast();});
  ipcMain.handle('producer:broadcast:start',async(event,value)=>{if(!settingsEvent(event))throw Error('Untrusted request');await broadcast.start(value);return publicBroadcast();});
  ipcMain.handle('producer:broadcast:stop',async event=>{if(!settingsEvent(event))throw Error('Untrusted request');await broadcast.stop();return publicBroadcast();});
  ipcMain.handle('producer:broadcast:status',event=>{if(!policy.trustedMain(event,studio.webContents,origin)&&!settingsEvent(event))throw Error('Untrusted request');return publicBroadcast();});
  ipcMain.handle('producer:platform',(event,value)=>{if(!settingsEvent(event)||!policy.allowedExternal(value))throw Error('Untrusted address');return shell.openExternal(value);});
  Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'Producer, Please',submenu:[{label:'Broadcast setup…',accelerator:'CmdOrCtrl+,',click:openSettings},{type:'separator'},{label:'Quit',click:()=>app.quit()}]},{label:'View',submenu:[{role:'reload'},{role:'togglefullscreen'},{role:'resetzoom'},{role:'zoomin'},{role:'zoomout'}]},{role:'editMenu'},{label:'Help',submenu:[{label:'About Producer, Please',click:()=>dialog.showMessageBox(studio,{message:'Producer, Please',detail:'Standalone desktop production studio. Configuring a destination, sending media, and verified platform receipt are separate states. This local build uses the existing project runtime.'})}]}]));
  await studio.loadURL(origin+'/control?workspace=studio&desktop=1');
}).catch(async error=>{await dialog.showMessageBox({type:'error',message:'Producer, Please could not start',detail:typeof error.message==='string'?error.message:'The local runtime is unavailable.'});app.exit(1);});
const {createQuitCoordinator}=require('./quit.cjs');
quit=createQuitCoordinator({
  active:async()=>{
    const responses=await Promise.all(['/api/production/session','/api/production/obs'].map(url=>fetch(origin+url,{signal:AbortSignal.timeout(3000)})));
    const [value,encoder]=await Promise.all(responses.map(r=>r.json()));
    return broadcast?.active()||responses.some(r=>!r.ok)||value.session?.active!==false||value.session?.recording?.active!==false||encoder.obs?.streaming!==false||encoder.obs?.recording!==false;
  },
  confirm:async()=>{const options={type:'warning',message:'Close the desktop studio?',detail:'A production may still be active. Closing this window can disconnect your local microphone or guest controls. Background production will stay running when its safety cannot be confirmed.',buttons:['Keep studio open','Close window'],defaultId:0,cancelId:0};const answer=studio&&!studio.isDestroyed()?await dialog.showMessageBox(studio,options):await dialog.showMessageBox(options);return answer.response===1;},
  release:async()=>{
    if(await broadcast?.close()===false){await dialog.showMessageBox(studio,{type:'warning',message:'Broadcast shutdown is not confirmed',detail:'The studio will stay open. Try Stop broadcast again before quitting.'});return false;}clearInterval(polling);capturePicker?.close();for(const window of BrowserWindow.getAllWindows())window.destroy();
    let result;try{result=await backend.close();}catch(_){result={running:null,reason:'shutdown_unconfirmed'};}
    fs.writeFileSync(path.join(profile,'last-close.json'),JSON.stringify({backendRunning:result?.running??null,reason:result?.reason||null}));
  },
  exit:()=>app.quit(),
});
app.on('window-all-closed',()=>{if(!quit.draining)app.quit();});
app.on('before-quit',event=>{if(backend)quit.request(event);});
