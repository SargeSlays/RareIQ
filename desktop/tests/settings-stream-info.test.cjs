'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../settings-stream-info.js'),'utf8');
const ONE='11111111-1111-4111-8111-111111111111',TWO='22222222-2222-4222-8222-222222222222';
const clone=value=>JSON.parse(JSON.stringify(value));
class Element{
  constructor(){this.listeners={};this.children=[];this.dataset={};this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.textContent='';}
  addEventListener(name,callback){this.listeners[name]=callback;}
  fire(name='click'){return this.listeners[name]?.({preventDefault(){}});}
  append(value){this.children.push(value);}
  replaceChildren(){this.children=[];}
}
function fixture(){
  const nodes=new Map(),get=name=>{if(!nodes.has(name))nodes.set(name,new Element());return nodes.get(name);},root=new Element(),window={},writes=[],opens=[],busy=[],changes=[];
  root.querySelector=selector=>get(selector.slice('#streamInfo'.length));root.ownerDocument={createElement:()=>new Element()};
  let state={revision:0,shared:{title:'Shared title',description:'Shared description'},overrides:{}},request=0;
  const api={streamInfo:async()=>clone(state),saveStreamInfo:async value=>{writes.push(clone(value));state={revision:state.revision+1,shared:clone(value.shared),overrides:clone(value.overrides)};return clone(state);},openPlatform:async url=>{opens.push(url);}};
  vm.runInNewContext(source,{window,crypto:{randomUUID:()=>`request-${++request}`}});
  const editor=window.ProducerStreamInfo.create({root,api,onBusy:value=>busy.push(value),onChange:value=>changes.push(value)});
  editor.setContext({destinations:[{id:ONE,name:'Twitch fixture',platform:'twitch'},{id:TWO,name:'Custom fixture',platform:'custom'}],locked:false});
  return {editor,root,node:get,api,writes,opens,busy,changes,get saved(){return state;},set saved(value){state=value;}};
}
function input(f,name,value){f.node(name).value=value;f.node(name).fire('input');}
test('local drafts preserve complete overrides and destination selection without provider writes',async()=>{
  const f=fixture();assert.equal(f.editor.ready,false);await f.editor.load();assert.equal(f.editor.ready,true);assert.equal(f.editor.dirty,false);
  f.node('Customize').checked=true;f.node('Customize').fire('change');assert.equal(f.node('Title').value,'Shared title');input(f,'Title','Twitch draft');input(f,'Category','Category notes');input(f,'Tags','tag notes');
  f.node('Destination').value=TWO;f.node('Destination').fire('change');assert.equal(f.node('Override').hidden,true);input(f,'SharedTitle','New shared title');
  f.node('Destination').value=ONE;f.node('Destination').fire('change');assert.equal(f.node('Title').value,'Twitch draft');assert.equal(f.node('Category').value,'Category notes');assert.equal(f.editor.dirty,true);assert.equal(f.writes.length,0);assert.equal(f.opens.length,0);
  await f.editor.save();assert.equal(f.saved.shared.title,'New shared title');assert.equal(f.saved.overrides[ONE].title,'Twitch draft');assert.equal(f.saved.overrides[ONE].tags,'tag notes');assert.equal(f.editor.dirty,false);assert.deepEqual(f.busy,[true,false]);assert.match(f.node('Status').textContent,/Saved locally/);assert.match(f.node('Status').textContent,/Apply supported fields/);
  f.node('Customize').checked=false;f.node('Customize').fire('change');await f.editor.save();assert.equal(Object.hasOwn(f.saved.overrides,ONE),false);
});
test('an ambiguous save retains its exact request until editing, and save locks controls',async()=>{
  const f=fixture();await f.editor.load();input(f,'SharedTitle','Local retry title');let reject,resolve;const attempts=[];
  f.api.saveStreamInfo=value=>{attempts.push(clone(value));return new Promise((a,b)=>{resolve=a;reject=b;});};
  const first=f.editor.save();assert.equal(f.node('SharedTitle').disabled,true);assert.equal(f.node('Save').disabled,true);assert.equal(f.editor.busy,true);reject(Error('acknowledgment lost'));await first;
  assert.equal(f.editor.dirty,true);assert.equal(f.node('SharedTitle').value,'Local retry title');assert.match(f.node('Save').textContent,/Retry/);
  const second=f.editor.save();assert.deepEqual(attempts[1],attempts[0]);resolve({revision:1,shared:attempts[1].shared,overrides:attempts[1].overrides});await second;assert.equal(f.editor.dirty,false);
});
test('revision conflicts keep the draft until explicit discard and reload, and failed loading blocks readiness',async()=>{
  const f=fixture();await f.editor.load();input(f,'SharedTitle','Keep this draft');f.api.saveStreamInfo=async()=>{throw Error('stream_info_revision_conflict');};await f.editor.save();
  assert.equal(f.editor.conflict,true);assert.equal(f.node('SharedTitle').value,'Keep this draft');assert.equal(f.node('Save').disabled,true);input(f,'SharedDescription','Still editing');assert.equal(f.node('Save').disabled,true);assert.match(f.node('Reload').textContent,/Discard draft/);
  f.saved={revision:2,shared:{title:'Newer saved title',description:''},overrides:{}};await f.node('Reload').fire();assert.equal(f.node('SharedTitle').value,'Newer saved title');assert.equal(f.editor.dirty,false);assert.equal(f.editor.conflict,false);
  f.api.streamInfo=async()=>{throw Error('unavailable');};await f.editor.load();assert.equal(f.editor.ready,false);assert.equal(f.node('SharedTitle').value,'Newer saved title');assert.match(f.node('Status').textContent,/could not load/);
});
test('undoing an unconfirmed save cannot bypass saved-state reconciliation',async()=>{
  const f=fixture();await f.editor.load();input(f,'SharedTitle','Potentially saved title');f.api.saveStreamInfo=async()=>{throw Error('acknowledgment lost');};await f.editor.save();input(f,'SharedTitle','Shared title');assert.equal(f.editor.dirty,false);assert.equal(f.editor.ready,false);await f.editor.load();assert.equal(f.editor.ready,true);
});
test('dashboard shortcuts use fixed URLs, locks preserve drafts, and context updates do not recurse',async()=>{
  const f=fixture();await f.editor.load();await f.node('Dashboard').fire();assert.deepEqual(f.opens,['https://dashboard.twitch.tv/']);
  input(f,'SharedTitle','Preserved draft');f.editor.setContext({locked:true});assert.equal(f.node('Save').disabled,true);assert.equal(f.node('Customize').disabled,true);assert.equal(f.node('Dashboard').disabled,true);await f.editor.save();assert.equal(f.writes.length,0);
  f.editor.setContext({locked:false});assert.equal(f.node('SharedTitle').value,'Preserved draft');f.node('Destination').value=TWO;f.node('Destination').fire('change');assert.equal(f.node('Dashboard').disabled,true);await f.node('Dashboard').fire();assert.equal(f.opens.length,1);
  const count=f.changes.length;for(let i=0;i<10;i++)f.editor.setContext({locked:false});assert.equal(f.changes.length,count);
});
