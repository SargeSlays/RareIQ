'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{pathToFileURL}=require('node:url');
const desktop=path.resolve(__dirname,'..'),main=fs.readFileSync(path.join(desktop,'main.cjs'),'utf8');
function fixture(){
  const calls=[],settingsUrl=pathToFileURL(path.join(desktop,'settings.html')).href,studioUrl='http://127.0.0.1:54321/control?workspace=settings';
  const settingsFrame={url:settingsUrl},studioFrame={url:studioUrl};
  const settings={isDestroyed:()=>false,webContents:{mainFrame:settingsFrame},hide:()=>calls.push('hide-settings'),destroy:()=>assert.fail('destination draft must not be destroyed')};
  const studio={isDestroyed:()=>false,isMinimized:()=>true,restore:()=>calls.push('restore-studio'),show:()=>calls.push('show-studio'),focus:()=>calls.push('focus-studio'),webContents:{mainFrame:studioFrame,getURL:()=>studioFrame.url,executeJavaScript:async(code,gesture)=>{calls.push({code,gesture});return true;}}};
  const context={settings,studio,broadcast:null,origin:'http://127.0.0.1:54321',choosingSources:null,path,pathToFileURL,URL,__dirname:desktop,policy:require('../policy.cjs')};
  vm.createContext(context);vm.runInContext(main.slice(main.indexOf('function settingsEvent('),main.indexOf('app.whenReady()')),context);
  return {context,settings,studio,calls,event:{sender:settings.webContents,senderFrame:settingsFrame},run(event){return context.openSources(event||this.event);}};
}
test('settings preload exposes a fixed no-payload Choose sources action',async()=>{
  let bridge,called;
  const electron={contextBridge:{exposeInMainWorld:(_name,value)=>{bridge=value;}},ipcRenderer:{invoke:(...args)=>{called=args;return Promise.resolve({ok:true});}}};
  vm.runInNewContext(fs.readFileSync(path.join(desktop,'settings-preload.cjs'),'utf8'),{require:()=>electron});
  await bridge.openSources({url:'https://ignored.invalid',script:'ignored'});assert.deepEqual(called,['producer:sources:open']);
  await bridge.viewOutput({url:'https://ignored.invalid',script:'ignored'});assert.deepEqual(called,['producer:output:view']);
});
test('View output uses only existing capture.show and accepts only the settings main frame',()=>{
  const f=fixture();let shown=0;f.context.broadcast={capture:{show:()=>{shown++;}},active:()=>true};
  assert.throws(()=>f.context.viewOutput({sender:f.event.sender,senderFrame:{url:f.event.senderFrame.url}}),/Untrusted request/);assert.equal(shown,0);
  assert.equal(f.context.viewOutput(f.event).ok,true);assert.equal(shown,1);assert.deepEqual(f.calls,[]);
  f.context.broadcast.capture=null;assert.throws(()=>f.context.viewOutput(f.event),/Prepare Studio Output/);
  f.context.broadcast.capture={show:()=>{throw Error('output_capture_closed');}};assert.throws(()=>f.context.viewOutput(f.event),/output_capture_closed/);
});
test('only exact settings main frame can request source navigation',async()=>{
  const f=fixture();for(const event of [{sender:{},senderFrame:f.event.senderFrame},{sender:f.event.sender,senderFrame:{url:f.event.senderFrame.url}},{sender:f.studio.webContents,senderFrame:f.studio.webContents.mainFrame}])await assert.rejects(f.run(event),/Untrusted request/);
  f.event.senderFrame.url='file:///untrusted.html';await assert.rejects(f.run(),/Untrusted request/);assert.deepEqual(f.calls,[]);
});
test('successful fixed navigation focuses Studio and hides the existing settings draft',async()=>{
  const f=fixture();const result=await f.run();assert.equal(result.ok,true);
  assert.deepEqual(f.calls,[{code:'window.ProducerDesktopNavigation?.openSources() === true',gesture:false},'restore-studio','show-studio','focus-studio','hide-settings']);
});
test('missing UI acknowledgment and an untrusted target leave settings visible',async()=>{
  const f=fixture();f.studio.webContents.executeJavaScript=async()=>false;await assert.rejects(f.run(),/not ready yet/);assert.deepEqual(f.calls,[]);
  f.studio.webContents.mainFrame.url='http://127.0.0.1:54321/program';await assert.rejects(f.run(),/unavailable/);assert.deepEqual(f.calls,[]);
});
test('duplicate requests share navigation and stale completion cannot hide a replacement settings window',async()=>{
  const f=fixture();let finish,count=0;f.studio.webContents.executeJavaScript=()=>{count++;return new Promise(resolve=>{finish=resolve;});};
  const first=f.run(),second=f.run();assert.equal(count,1);
  f.context.settings={...f.settings,hide:()=>assert.fail('a new settings window must remain visible')};finish(true);
  assert.equal((await first).ok,true);assert.equal((await second).ok,true);assert.equal(f.calls.includes('hide-settings'),false);
});
test('navigation during acknowledgment cannot hide settings or focus another page',async()=>{
  const f=fixture();let finish;f.studio.webContents.executeJavaScript=()=>new Promise(resolve=>{finish=resolve;});const pending=f.run();
  f.studio.webContents.mainFrame.url='https://example.invalid/';finish(true);await assert.rejects(pending,/not ready yet/);assert.deepEqual(f.calls,[]);
});
