'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{pathToFileURL}=require('node:url');
const desktop=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(desktop,'main.cjs'),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
function fixture(){
  const handlers=new Map(),calls=[],settingsFrame={url:pathToFileURL(path.join(desktop,'settings.html')).href};
  const settings={isDestroyed:()=>false,webContents:{mainFrame:settingsFrame}},event={sender:settings.webContents,senderFrame:settingsFrame};
  const broadcast={active:()=>false,status:()=>({ownershipPending:false}),start:async()=>{calls.push('start');}};
  const destinations={save:async value=>{calls.push(['save',value]);return {saved:true};},remove:async id=>{calls.push(['remove',id]);return {removed:true};}};
  const context={settings,broadcast,destinations,destinationMutation:false,path,pathToFileURL,__dirname:desktop,publicBroadcast:()=>({ready:true}),ipcMain:{handle:(name,handler)=>handlers.set(name,handler)}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function settingsEvent('),source.indexOf('app.whenReady()')),context);
  for(const line of source.split('\n'))if(/ipcMain.handle\('producer:(?:destinations:(?:save|remove)|broadcast:start)'/.test(line))vm.runInContext(line,context);
  return {calls,event,context,broadcast,destinations,run:(name,value,request=event)=>handlers.get('producer:'+name)(request,value)};
}

test('only the exact settings main frame can mutate saved destinations',async()=>{
  const f=fixture();for(const name of ['destinations:save','destinations:remove']){
    for(const event of [{sender:{},senderFrame:f.event.senderFrame},{sender:f.event.sender,senderFrame:{url:f.event.senderFrame.url}}])await assert.rejects(f.run(name,{},event),/Untrusted request/);
  }
  assert.deepEqual(f.calls,[]);
});

test('Start confirmation, sending, stopping and uncertain ownership block save and remove',async()=>{
  const f=fixture();
  for(const state of ['confirming','sending','stopping','ownershipPending']){
    f.broadcast.active=()=>state!=='ownershipPending';f.broadcast.status=()=>({ownershipPending:state==='ownershipPending'});
    await assert.rejects(f.run('destinations:save',{id:'other-profile'}),/destination_broadcast_busy/);
    await assert.rejects(f.run('destinations:remove','other-profile'),/destination_broadcast_busy/);
  }
  assert.deepEqual(f.calls,[]);
});

test('pending persistence blocks Start and repeated mutations until the save completes',async()=>{
  const f=fixture(),save=deferred();f.destinations.save=()=>{f.calls.push('save');return save.promise;};
  const pending=f.run('destinations:save',{});
  await assert.rejects(f.run('broadcast:start',{}),/destination_change_pending/);
  await assert.rejects(f.run('destinations:remove','any-profile'),/destination_change_pending/);
  await assert.rejects(f.run('destinations:save',{}),/destination_change_pending/);
  assert.deepEqual(f.calls,['save']);save.resolve({saved:true});assert.equal((await pending).saved,true);
  await f.run('broadcast:start',{});assert.deepEqual(f.calls,['save','start']);
});

test('failed save and completed remove release the mutation lock for explicit retry',async()=>{
  const f=fixture(),remove=deferred();f.destinations.save=async()=>{throw Error('synthetic_storage_failure');};
  await assert.rejects(f.run('destinations:save',{}),/synthetic_storage_failure/);assert.equal(f.context.destinationMutation,false);
  f.destinations.remove=()=>remove.promise;const pending=f.run('destinations:remove','profile');
  await assert.rejects(f.run('broadcast:start',{}),/destination_change_pending/);remove.resolve({removed:true});assert.equal((await pending).removed,true);
  await f.run('broadcast:start',{});assert.deepEqual(f.calls,['start']);
});
