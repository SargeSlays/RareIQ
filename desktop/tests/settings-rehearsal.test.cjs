'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../settings-rehearsal.js'),'utf8');
class Element{
  constructor(){this.listeners={};this.children=[];this.dataset={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';this.attributes={};}
  addEventListener(name,fn){this.listeners[name]=fn;}
  removeEventListener(name,fn){if(this.listeners[name]===fn)delete this.listeners[name];}
  fire(name='click',event={}){return this.listeners[name]?.({target:this,...event});}
  append(...items){this.children.push(...items);}
  replaceChildren(){this.children=[];}
  setAttribute(name,value){this.attributes[name]=value;}
  querySelector(){if(!this.option)this.option=new Element();return this.option;}
  querySelectorAll(name){return this.children.flatMap(row=>row.children.filter(value=>name==='select'&&value.dataset.checkId));}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const status=(mode='production',extra={})=>({ok:true,room:{mode,active:mode!=='production',publishing_allowed:mode==='production',revision:2,generation:4,checks:[{id:'picture',label:'Inspect the picture',status:'not_tested'}]},local:{state:'idle',running:false,frames:0,audioSamples:0,vodAudioSamples:0,bytesMuxed:0,codec:'h264',ownershipPending:false},monitor:{bus:'off',available:false,vodAvailable:false},outputPrepared:false,...extra});
function fixture(initial=status()){
  const nodes=new Map(),node=name=>{if(!nodes.has(name))nodes.set(name,new Element());return nodes.get(name);},root=new Element(),window={},requests=[],busy=[],changes=[],timers=new Map();let ids=0,current=initial;
  root.querySelector=selector=>node(selector.slice('#rehearsal'.length));root.ownerDocument={createElement:()=>new Element(),querySelector:()=>({focus(){node('PrepareTarget').focused=true;}})};
  const api={rehearsal:async request=>{requests.push({...request});if(request.action==='enter')current=status('rehearsal');if(['exit','recover'].includes(request.action))current=status();return structuredClone(current);}};
  vm.runInNewContext(source,{window,crypto:{randomUUID:()=>`fixture-${++ids}`},setTimeout:(fn,delay)=>{const id=++ids;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)});
  const editor=window.ProducerRehearsalUI.create({root,api,onBusy:value=>busy.push(value),onChange:value=>changes.push(value)});editor.start();
  return {editor,api,node,requests,busy,changes,timers,setCurrent:value=>{current=value;}};
}
test('entry is explicit, local start requires prepared output, reads never mark mutation busy',async()=>{
  const f=fixture();await tick();assert.deepEqual(f.requests,[{action:'status'}]);assert.deepEqual(f.busy,[]);assert.equal(f.node('Monitor').value,'off');assert.equal(f.node('Monitor').disabled,true);assert.equal(f.node('Start').hidden,true);
  await f.node('Enter').fire();assert.match(f.node('Badge').textContent,/REHEARSAL — not broadcasting/);assert.equal(f.node('Start').disabled,true);assert.match(f.node('Start').title,/Prepare output/);assert.equal(f.node('Stop').disabled,false);assert.deepEqual(f.busy,[true,false]);assert.equal(f.requests.at(-1).revision,2);assert.equal(f.requests.at(-1).generation,4);
  f.node('Prepare').fire();assert.equal(f.node('PrepareTarget').focused,true);f.editor.close();
});
test('an unconfirmed mutation retains its exact request through read-only status refresh',async()=>{
  const f=fixture(status('rehearsal',{outputPrepared:true}));await tick();let fail=true;
  f.api.rehearsal=async request=>{f.requests.push({...request});if(request.action==='status')return status('rehearsal',{outputPrepared:true});if(fail)throw Error('private detail must never be displayed');return status('rehearsal',{outputPrepared:true,local:{state:'running',running:true,frames:90}});};
  await f.node('Start').fire();const first=f.requests.at(-1);assert.equal(f.node('Retry').hidden,false);assert.equal(f.node('Stop').disabled,false);assert.match(f.node('Status').textContent,/not confirmed/);assert.doesNotMatch(f.node('Status').textContent,/private detail/);
  await f.node('Refresh').fire();assert.equal(f.node('Start').disabled,true);fail=false;await f.node('Retry').fire();assert.deepEqual(f.requests.at(-1),first);assert.equal(f.node('Retry').hidden,true);assert.match(f.node('Local').textContent,/Local encoding is running/);assert.doesNotMatch(f.node('Local').textContent,/On Air/i);f.editor.close();
});
test('Stop remains usable during Start, own busy lock and uncertainty; late Start cannot resurrect it',async()=>{
  const f=fixture(status('rehearsal',{outputPrepared:true}));await tick();let finish;
  f.api.rehearsal=async request=>{f.requests.push({...request});if(request.action==='start')return new Promise(resolve=>{finish=()=>resolve(status('rehearsal',{outputPrepared:true,local:{state:'running',running:true,frames:1}}));});return status('rehearsal',{outputPrepared:true});};
  const start=f.node('Start').fire();f.editor.setContext({locked:true});assert.equal(f.node('Stop').disabled,false);await f.node('Stop').fire();assert.match(f.node('Status').textContent,/stopped/);assert.deepEqual(f.busy,[true,false],'confirmed Stop releases busy even if the superseded Start reply is still pending');finish();await start;assert.match(f.node('Local').textContent,/stopped/);assert.deepEqual(f.busy,[true,false]);f.editor.close();
});
test('double Stop is guarded and uncertain Stop can retry the exact request',async()=>{
  const f=fixture(status('rehearsal',{local:{state:'running',running:true,frames:10}}));await tick();let finish;f.api.rehearsal=request=>{f.requests.push({...request});return new Promise(resolve=>{finish=()=>resolve(status('rehearsal',{local:{state:'running',running:true,ownershipPending:true}}));});};
  const stopping=f.node('Stop').fire();await f.node('Stop').fire();assert.equal(f.requests.filter(value=>value.action==='stop').length,1);assert.equal(f.node('Stop').disabled,true);finish();await stopping;assert.equal(f.node('Stop').disabled,false);const first=f.requests.at(-1);f.api.rehearsal=async request=>{f.requests.push({...request});return status('rehearsal');};await f.node('Retry').fire();assert.deepEqual(f.requests.at(-1),first);f.editor.close();
});
test('revision conflict reloads status and uses fresh generation for the next explicit action',async()=>{
  const f=fixture(status('rehearsal',{outputPrepared:true}));await tick();let conflict=true;
  f.api.rehearsal=async request=>{f.requests.push({...request});if(request.action==='status'){const next=status('rehearsal',{outputPrepared:true});next.room.revision=8;next.room.generation=9;return next;}if(conflict)return {ok:false,reason:'rehearsal_generation_conflict'};return status('rehearsal',{outputPrepared:true});};
  await f.node('Start').fire();await tick();assert.equal(f.node('Retry').hidden,true);assert.match(f.node('Status').textContent,/Current rehearsal status loaded/);conflict=false;await f.node('Start').fire();assert.equal(f.requests.at(-1).generation,9);assert.equal(f.requests.at(-1).revision,8);f.editor.close();
});
test('status polling does not overlap, backs off and keeps the active warning on failure',async()=>{
  const f=fixture(status('rehearsal'));await tick();let reject;f.api.rehearsal=request=>{f.requests.push({...request});return new Promise((resolve,fail)=>{reject=fail;});};
  const first=f.node('Refresh').fire();await f.node('Refresh').fire();assert.equal(f.requests.length,2);reject(Error('offline'));await first;assert.match(f.node('Badge').textContent,/REHEARSAL/);assert.match(f.node('Status').textContent,/unavailable/);assert.ok([...f.timers.values()].some(value=>value.delay===2000));assert.deepEqual(f.busy,[]);f.editor.close();assert.equal(f.timers.size,0);
});
test('monitoring remains opt in, respects absent VOD and manual marks are clearly observations',async()=>{
  const f=fixture(status('rehearsal',{monitor:{bus:'off',available:true,vodAvailable:false}}));await tick();assert.equal(f.requests.some(value=>value.action==='monitor'),false);assert.equal(f.node('Monitor').option.disabled,true);assert.equal(f.node('Monitor').disabled,false);
  f.node('Monitor').value='live';await f.node('Monitor').fire('change');await tick();assert.equal(f.requests.at(-1).bus,'live');const select=f.node('Checks').querySelectorAll('select')[0];assert.equal(select.value,'not_tested');select.value='needs_attention';await f.node('Checks').fire('change',{target:select});await tick();assert.equal(f.requests.at(-1).checkState,'needs_attention');assert.match(f.node('Status').textContent,/operator observation/);f.editor.close();
});
test('recovery is separate from exit and preserves report access, with Stop required first',async()=>{
  const f=fixture(status('recovery_required',{local:{state:'failed',running:false,ownershipPending:true}}));await tick();assert.equal(f.node('Recover').hidden,false);assert.equal(f.node('Recover').disabled,true);assert.equal(f.node('Exit').hidden,true);assert.equal(f.node('Export').disabled,false);assert.equal(f.node('Stop').disabled,false);
  f.setCurrent(status('recovery_required'));await f.node('Stop').fire();assert.equal(f.node('Recover').disabled,false);await f.node('Recover').fire();assert.equal(f.requests.at(-1).action,'recover');assert.match(f.node('Status').textContent,/separate broadcast confirmation/);f.editor.close();
});
test('closing ignores late callbacks, cancels polling and balances mutation busy once',async()=>{
  const f=fixture();await tick();let finish;f.api.rehearsal=()=>new Promise(resolve=>{finish=()=>resolve(status('rehearsal'));});const action=f.node('Enter').fire();f.editor.close();const prior=f.node('Status').textContent;finish();await action;assert.equal(f.node('Status').textContent,prior);assert.deepEqual(f.busy,[true,false]);assert.equal(f.timers.size,0);
});
test('native exit, recovery and report cancellation cannot produce success wording',async()=>{
  const f=fixture(status('rehearsal'));await tick();f.api.rehearsal=async request=>{f.requests.push({...request});return {...status('rehearsal'),cancelled:true};};await f.node('Exit').fire();assert.match(f.node('Status').textContent,/Action cancelled/);assert.match(f.node('Badge').textContent,/REHEARSAL/);await f.node('Export').fire();assert.equal(f.node('Status').textContent,'Report export cancelled. No report was saved.');assert.equal(f.node('Retry').hidden,true);f.editor.close();
});


test('failed monitor still permits choosing Off and invalid storage has an actionable status',async()=>{
  const value=status('recovery_required',{monitor:{bus:'live',available:false,vodAvailable:false}});value.room.reason='rehearsal_storage_invalid';
  const f=fixture(value);await tick();assert.equal(f.node('Monitor').disabled,false);assert.match(f.node('Status').textContent,/configured storage location/);f.editor.close();
});
