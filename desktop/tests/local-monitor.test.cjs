'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createLocalMonitor,CHANNELS}=require('../local-monitor.cjs');
function fixture(){
  const ipc=new EventEmitter(),sent=[];let window;
  class Window extends EventEmitter{constructor(options){super();window=this;this.options=options;this.destroyed=false;const wc=this.webContents=new EventEmitter();wc.mainFrame={url:''};wc.getURL=()=>wc.mainFrame.url;wc.session={setPermissionCheckHandler:fn=>wc.permission=fn,setPermissionRequestHandler:fn=>wc.requestPermission=fn,setDisplayMediaRequestHandler:fn=>wc.display=fn};wc.setWindowOpenHandler=fn=>wc.open=fn;wc.loadURL=async url=>{wc.mainFrame.url=url;};wc.send=(channel,value)=>sent.push({channel,value});}setMenu(){}isDestroyed(){return this.destroyed;}destroy(){this.destroyed=true;this.emit('closed');}}
  const monitor=createLocalMonitor({BrowserWindow:Window,ipcMain:ipc,timeoutMs:40,createServer:()=>{const server=new EventEmitter();server.listen=(_port,_host,fn)=>queueMicrotask(fn);server.address=()=>({port:19001});server.close=()=>{};return server;}});
  return {monitor,ipc,sent,get window(){return window;},event:()=>({sender:window.webContents,senderFrame:window.webContents.mainFrame}),nonce:()=>window.options.webPreferences.additionalArguments[0].split('=').at(-1),health(ready=true,event){ipc.emit(CHANNELS.health,event||this.event(),{nonce:this.nonce(),ready});}};
}

test('speaker window has fixed internal document and no capture permissions, page bridge or external navigation',async()=>{
  const f=fixture(),starting=f.monitor.prepare();await Promise.resolve();f.health();await starting;const wc=f.window.webContents;assert.equal(wc.getURL(),'http://127.0.0.1:19001/monitor/'+f.nonce());assert.equal(f.window.options.webPreferences.nodeIntegration,false);assert.equal(f.window.options.webPreferences.sandbox,true);assert.equal(f.window.options.webPreferences.contextIsolation,true);assert.equal(wc.permission(),false);assert.equal(wc.open().action,'deny');
  let grant;wc.requestPermission(null,null,value=>grant=value);assert.equal(grant,false);wc.display(null,value=>grant=value);assert.equal(grant,null);let prevented=false;wc.emit('will-navigate',{preventDefault(){prevented=true;}},'https://outside.invalid/');assert.equal(prevented,true);assert.equal(f.monitor.status().running,false);f.monitor.close();
});

test('only the owned speaker top frame can acknowledge playback, one packet is retained, and Off clears pending audio',async()=>{
  const f=fixture(),starting=f.monitor.prepare();await Promise.resolve();f.health();await starting;const delivery=f.monitor.write(Buffer.alloc(3840));assert.equal(f.monitor.status().pending,true);assert.equal(await f.monitor.write(Buffer.alloc(3840)),false);const packet=f.sent.at(-1).value;let settled=false;delivery.then(()=>settled=true);
  f.ipc.emit(CHANNELS.ack,{sender:f.window.webContents,senderFrame:{url:f.window.webContents.getURL()}},{nonce:packet.nonce,seq:packet.seq});f.ipc.emit(CHANNELS.ack,f.event(),{nonce:'wrong',seq:packet.seq});await Promise.resolve();assert.equal(settled,false);f.ipc.emit(CHANNELS.ack,f.event(),{nonce:packet.nonce,seq:packet.seq});assert.equal(await delivery,true);
  const pending=f.monitor.write(Buffer.alloc(3840));const old=f.event(),nonce=f.nonce();f.monitor.stop();assert.equal(await pending,false);assert.equal(f.window.isDestroyed(),true);f.ipc.emit(CHANNELS.ack,old,{nonce,seq:1});assert.equal(f.monitor.status().ready,false);f.monitor.close();assert.equal(f.ipc.listenerCount(CHANNELS.ack),0);
});

test('speaker playback worklet consumes only bounded IPC PCM, emits silence by default and ACKs after actual consumption',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../monitor-preload.cjs'),'utf8'),worklet=source.match(/const worklet=`([\s\S]*?)`;/)[1],acks=[];let Processor;
  vm.runInNewContext(worklet,{AudioWorkletProcessor:class{constructor(){this.port={postMessage:value=>acks.push(value)};}},registerProcessor:(_name,ctor)=>Processor=ctor,ArrayBuffer,Float32Array});
  const processor=new Processor(),tick=()=>{const channels=[new Float32Array(128).fill(99),new Float32Array(128).fill(99)];processor.process([], [channels]);return channels;};assert.ok(tick().every(channel=>channel.every(value=>value===0)));
  const samples=new Float32Array(960);for(let index=0;index<samples.length;index++)samples[index]=index%2?-.1:.2;processor.port.onmessage({data:{seq:3,pcm:samples.buffer}});
  for(let index=0;index<3;index++){const channels=tick();assert.ok(channels[0].every(value=>Math.abs(value-.2)<1e-7));assert.ok(channels[1].every(value=>Math.abs(value+.1)<1e-7));}assert.equal(acks.length,0);tick();assert.equal(acks[0].seq,3);assert.equal(processor.packet,null);assert.ok(tick().every(channel=>channel.every(value=>value===0)));
  processor.port.onmessage({data:{seq:4,pcm:new Float32Array(960).fill(.5).buffer}});processor.port.onmessage({data:{type:'stop'}});assert.ok(tick().every(channel=>channel.every(value=>value===0)));assert.equal(acks.length,1);
});
