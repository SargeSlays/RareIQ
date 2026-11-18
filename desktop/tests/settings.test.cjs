'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../settings.js'),'utf8');
const prepared={phase:'prepared',active:false,ready:true,prepared:true,format:'hd',available:true};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
class Element{
  constructor(){this.listeners=new Map();this.children=[];this.dataset={};this.value='';this.textContent='';this.hidden=false;this.disabled=false;}
  addEventListener(name,fn){this.listeners.set(name,fn);}
  fire(name='click'){return this.listeners.get(name)?.({preventDefault(){}});}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(){}
  focus(){this.focused=true;}
  scrollIntoView(){this.scrolled=true;}
}
async function fixture(){
  const nodes=new Map(),timers=[],calls={start:0,stop:0,poll:0,save:0,remove:0,sources:0,view:0};let state={...prepared};
  const node=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const form=node('#destinationForm');form.elements=[];
  for(const name of ['name','platform','serverUrl','streamKey']){const element=new Element();form.elements.push(element);form.elements[name]=element;}
  form.elements.name.value='Synthetic';form.elements.platform.value='twitch';form.elements.streamKey.value='synthetic-never-sent';form.reset=()=>{};
  node('#outputFormat').value='hd';
  const descendants=element=>element.children.flatMap(child=>[child,...descendants(child)]);
  const document={querySelector:node,createElement:()=>new Element(),documentElement:{dataset:{}},querySelectorAll:selector=>{
    const key=selector==='[data-destination-id]'?'destinationId':'removeDestinationId';return descendants(node('#destinations')).filter(element=>key in element.dataset);
  }};
  const api={status:async()=>({secureStorageAvailable:true,broadcast:state,destinations:[{id:'one',name:'Synthetic',platform:'twitch',configured:true}]}),
    startBroadcast:async()=>{calls.start++;return state;},stopBroadcast:async()=>{calls.stop++;return state={...prepared};},
    broadcastStatus:async()=>{calls.poll++;return state;},prepareOutput:async()=>state,
    save:async()=>{calls.save++;},remove:async()=>{calls.remove++;},openPlatform:()=>{},openSources:async()=>{calls.sources++;return {ok:true};},viewOutput:async()=>{calls.view++;return {ok:true};}};
  vm.runInNewContext(source,{document,producerSettings:api,window:{close(){}},localStorage:{getItem(){},setItem(){}},crypto:{randomUUID:()=> 'synthetic-request'},
    setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval(){},addEventListener(){}},{filename:'settings.js'});
  await settle();return {node,form,api,calls,poll:()=>timers[0](),set state(value){state=value;},get start(){return document.querySelectorAll('[data-destination-id]')[0];},get remove(){return document.querySelectorAll('[data-remove-destination-id]')[0];}};
}
test('stopped encoder failures override readiness and format hints without exposing unknown errors',async()=>{
  const f=await fixture();f.node('#outputFormat').value='portrait';
  for(const [reason,expected] of [['encoder_backpressure',/could not keep up/],['encoder_failed',/encoder failed/],['rtmps://private/secret-key',/stopped unexpectedly/]]){
    f.state={...prepared,phase:'failed',reason};await f.poll();const text=f.node('#broadcastSummary').textContent;
    assert.match(text,expected);assert.doesNotMatch(text,/Ready to send|secret-key|format changed/);
  }
});
test('pending Start keeps polling and Cancel available, prevents duplicate requests, and ignores late success',async()=>{
  const f=await fixture(),start=deferred(),stop=deferred();
  f.api.startBroadcast=()=>{f.calls.start++;return start.promise;};f.api.stopBroadcast=()=>{f.calls.stop++;return stop.promise;};
  const starting=f.start.fire();assert.equal(f.node('#stopBroadcast').hidden,false);assert.equal(f.node('#stopBroadcast').disabled,false);assert.equal(f.node('#stopBroadcast').textContent,'Cancel start');
  await f.start.fire();await f.form.fire('submit');await f.remove.fire();assert.equal(f.calls.start,1);assert.equal(f.calls.save,0);assert.equal(f.calls.remove,0);
  f.state={...prepared,phase:'starting',active:true,ready:false};await f.poll();assert.equal(f.calls.poll,1);assert.match(f.node('#broadcastSummary').textContent,/Broadcast starting/);
  const stopping=f.node('#stopBroadcast').fire();await f.node('#stopBroadcast').fire();assert.equal(f.calls.stop,1);assert.equal(f.node('#stopBroadcast').disabled,true);
  stop.resolve({...prepared});await stopping;start.resolve({...prepared,phase:'sending',active:true,ready:false});await starting;
  assert.equal(f.node('#stopBroadcast').hidden,true);assert.match(f.node('#status').textContent,/Transmission stopped/);assert.doesNotMatch(f.node('#broadcastSummary').textContent,/Sending/);
});
test('late Start rejection and pre-cancellation poll cannot overwrite a completed Stop',async()=>{
  const f=await fixture(),start=deferred(),poll=deferred();f.api.startBroadcast=()=>start.promise;const starting=f.start.fire();
  f.api.broadcastStatus=()=>poll.promise;const polling=f.poll();await f.node('#stopBroadcast').fire();
  poll.resolve({...prepared,phase:'sending',active:true});await polling;start.reject(Error('rtmps://private/secret-key'));await starting;
  assert.equal(f.node('#stopBroadcast').hidden,true);assert.equal(f.node('#status').textContent,'Transmission stopped.');assert.doesNotMatch(f.node('#broadcastSummary').textContent,/Sending|secret-key/);
});
test('status polling preserves destination save and remove locks until their requests finish',async()=>{
  const f=await fixture(),save=deferred(),remove=deferred();f.api.save=()=>{f.calls.save++;return save.promise;};
  const saving=f.form.fire('submit');await f.poll();await f.start.fire();await f.form.fire('submit');
  assert.equal(f.calls.start,0);assert.equal(f.calls.save,1);assert.equal(f.start.disabled,true);assert.ok(f.form.elements.every(element=>element.disabled));
  save.resolve();await saving;assert.equal(f.start.disabled,false);assert.ok(f.form.elements.every(element=>!element.disabled));
  f.api.remove=()=>{f.calls.remove++;return remove.promise;};const removing=f.remove.fire();await f.poll();await f.remove.fire();
  assert.equal(f.calls.remove,1);assert.equal(f.start.disabled,true);remove.resolve();await removing;assert.equal(f.start.disabled,false);
});
test('browser-mode backend explains the explicit restart without starting or stopping anything',async()=>{
  const f=await fixture();f.state={...prepared,ready:false,reason:'desktop_mode_required'};await f.poll();
  assert.match(f.node('#broadcastSummary').textContent,/started in browser mode\. Close its sessions and restart it from the desktop app/);
  assert.equal(f.start.disabled,true);assert.equal(f.calls.start,0);assert.equal(f.calls.stop,0);
});

test('broadcast guide distinguishes a checked output, changed format and secure destination',async()=>{
  const f=await fixture();assert.equal(f.node('#outputStep').textContent,'Ready');assert.equal(f.node('#destinationStep').textContent,'Saved securely');
  f.node('#outputFormat').value='portrait';f.node('#outputFormat').fire('change');assert.equal(f.node('#outputStep').textContent,'Prepare new format');assert.equal(f.start.disabled,true);
  f.api.status=async()=>({secureStorageAvailable:true,broadcast:{...prepared,ready:false,prepared:false},destinations:[]});await f.form.fire('submit');
  assert.equal(f.node('#outputStep').textContent,'Not prepared');assert.equal(f.node('#destinationStep').textContent,'Not saved');assert.equal(f.node('#programStep').textContent,'Check Program');
});

test('source navigation keeps destination drafts, blocks repeat clicks, and reports a recoverable failure',async()=>{
  const f=await fixture(),open=deferred();f.api.openSources=()=>{f.calls.sources++;return open.promise;};
  const name=f.form.elements.name.value,key=f.form.elements.streamKey.value,pending=f.node('#chooseSources').fire();await f.node('#chooseSources').fire();
  assert.equal(f.calls.sources,1);assert.equal(f.node('#chooseSources').disabled,true);assert.equal(f.calls.start,0);assert.equal(f.calls.save,0);
  open.reject(Error('private error'));await pending;assert.match(f.node('#status').textContent,/could not open/);assert.equal(f.node('#chooseSources').disabled,false);
  assert.equal(f.form.elements.name.value,name);assert.equal(f.form.elements.streamKey.value,key);assert.doesNotMatch(f.node('#status').textContent,/private error/);
  f.api.openSources=async()=>({ok:true});await f.node('#chooseSources').fire();assert.match(f.node('#status').textContent,/draft is kept/);
  f.node('#addDestination').fire();assert.equal(f.form.scrolled,true);assert.equal(f.form.elements.name.focused,true);
});

test('pending Stop acknowledgment keeps Stop available and blocks new transmission',async()=>{
  const f=await fixture();f.state={...prepared,phase:'failed',ownershipPending:true,reason:'studio_status_unconfirmed'};await f.poll();
  assert.equal(f.node('#stopBroadcast').hidden,false);assert.equal(f.node('#stopBroadcast').disabled,false);assert.equal(f.node('#prepareOutput').disabled,true);assert.equal(f.start.disabled,true);
  await f.start.fire();assert.equal(f.calls.start,0);assert.equal(f.node('#recoveryPanel').hidden,false);assert.match(f.node('#recoveryInstructions').textContent,/choose Stop broadcast again/);
  await f.node('#stopBroadcast').fire();assert.equal(f.calls.stop,1);assert.equal(f.node('#recoveryPanel').hidden,true);
});

test('View output stays usable during sending without starting or preparing another output',async()=>{
  const f=await fixture(),view=deferred();f.state={...prepared,phase:'sending',active:true,ready:false};await f.poll();f.api.viewOutput=()=>{f.calls.view++;return view.promise;};
  assert.equal(f.node('#viewOutput').disabled,false);const pending=f.node('#viewOutput').fire();await f.node('#viewOutput').fire();assert.equal(f.calls.view,1);assert.equal(f.node('#stopBroadcast').disabled,false);
  view.resolve({ok:true});await pending;assert.equal(f.calls.start,0);assert.match(f.node('#status').textContent,/does not change Program/);
  f.state={...prepared,prepared:false,ready:false};await f.poll();assert.equal(f.node('#viewOutput').disabled,true);
});

test('connection recovery remains explicit, preserves input drafts and hides unknown error text',async()=>{
  const f=await fixture();f.state={...prepared,phase:'failed',reason:'tls_verification_failed'};await f.poll();assert.match(f.node('#recoveryInstructions').textContent,/date and time/);assert.equal(f.calls.start,0);assert.equal(f.form.elements.streamKey.value,'synthetic-never-sent');
  f.state={...prepared,phase:'failed',reason:'rtmps://private/secret-key'};await f.poll();assert.doesNotMatch(f.node('#broadcastSummary').textContent+f.node('#recoveryInstructions').textContent,/secret-key|private/);
  f.state={...prepared,phase:'sending',active:true,ready:false,reason:'output_not_ready'};await f.poll();assert.match(f.node('#broadcastSummary').textContent,/Waiting for output readiness/);assert.equal(f.node('#outputStep').textContent,'Checking output');
});

test('normal startup reservation does not show an unconfirmed-stop recovery warning',async()=>{
  const f=await fixture();f.state={...prepared,phase:'starting',active:true,ready:false,ownershipPending:true};await f.poll();assert.equal(f.node('#recoveryPanel').hidden,true);assert.match(f.node('#broadcastSummary').textContent,/Broadcast starting/);
});
