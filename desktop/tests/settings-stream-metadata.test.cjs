'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../settings-stream-metadata.js'),'utf8');
class Element{
  constructor(){this.listeners={};this.children=[];this.dataset={};this.value='';this.disabled=false;this.hidden=false;this.textContent='';}
  addEventListener(name,fn){this.listeners[name]=fn;}
  fire(name='click',event={}){return this.listeners[name]?.({preventDefault(){},...event});}
  append(value){this.children.push(value);}
  replaceChildren(){this.children=[];this.value='';}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const inspect=(platform='twitch',extra={})=>({platform,authorized:true,editable:true,channel_id:'fixture-channel',public_label:'Synthetic channel',fields:{title:'Current title'},capabilities:{title:true,description:platform==='youtube',category_id:true,tags:true},broadcasts:[],...extra});
function fixture(platform='twitch'){
  const nodes=new Map(),node=name=>{if(!nodes.has(name))nodes.set(name,new Element());return nodes.get(name);},root=new Element(),window={},requests=[],busy=[];let count=0;
  root.querySelector=selector=>node(selector.slice('#streamMetadata'.length));root.ownerDocument={createElement:()=>new Element()};
  const api={streamMetadata:async value=>{requests.push({...value});if(value.action==='inspect')return inspect(value.platform);if(value.action==='apply')return {state:'applied',request_id:value.requestId};if(value.action==='categories')return {categories:[{id:'123',name:'Official category'}]};return {ok:true};}};
  vm.runInNewContext(source,{window,crypto:{randomUUID:()=>`fixture-request-${++count}`}});
  const editor=window.ProducerStreamMetadata.create({root,api,onBusy:value=>busy.push(value)});editor.setContext({destination:{id:'fixture-destination',name:'Fixture destination',platform},revision:2,dirty:false,locked:false});
  return {editor,api,root,node,requests,busy};
}
test('explicit apply binds only a saved revision and confirmed channel, with no draft values',async()=>{
  const f=fixture();await tick();assert.equal(f.node('Apply').disabled,false);assert.equal(f.node('Apply').textContent,'Apply to Twitch');assert.match(f.node('Account').textContent,/Synthetic channel/);assert.match(f.node('Fields').textContent,/Description stays local/);
  await f.node('Apply').fire();const request=f.requests.find(value=>value.action==='apply');assert.deepEqual(request,{action:'apply',platform:'twitch',destinationId:'fixture-destination',revision:2,channelId:'fixture-channel',requestId:'fixture-request-1'});assert.deepEqual(f.busy,[true,false]);assert.match(f.node('Status').textContent,/platform readback confirmed/);
  f.editor.setContext({dirty:true});assert.equal(f.node('Apply').disabled,true);assert.match(f.node('Apply').title,/Save your local/);assert.match(f.node('Status').textContent,/Save your local/);f.editor.setContext({dirty:false,locked:true});assert.equal(f.node('Apply').disabled,true);assert.match(f.node('Status').textContent,/Stop broadcasting/);
});
test('YouTube requires an explicit broadcast and rechecks its selected binding',async()=>{
  const f=fixture('youtube');f.api.streamMetadata=async value=>{f.requests.push({...value});if(value.action==='apply')return {state:'applied',request_id:value.requestId};const result=inspect('youtube',{broadcasts:[{id:'broadcast-one',title:'Upcoming fixture'}]});if(value.broadcastId){delete result.broadcasts;result.broadcast_id=value.broadcastId;}return result;};
  await tick();await f.node('Check').fire();assert.equal(f.node('Broadcast').value,'');assert.equal(f.node('Apply').disabled,true);assert.match(f.node('Apply').title,/Choose the YouTube/);
  f.node('Broadcast').value='broadcast-one';await f.node('Broadcast').fire('change');await tick();assert.equal(f.node('Broadcast').value,'broadcast-one');assert.equal(f.node('Broadcast').children.length,2);assert.equal(f.node('Broadcast').disabled,false);assert.equal(f.node('Apply').disabled,false);await f.node('Apply').fire();assert.equal(f.requests.at(-1).broadcastId,'broadcast-one');assert.equal(f.requests.some(value=>/create|start/.test(value.action)),false);
});
test('a linked YouTube destination selects only its saved broadcast for stream info',async()=>{
 const f=fixture('youtube');await tick();f.api.streamMetadata=async value=>{f.requests.push({...value});if(value.action==='apply')return {state:'applied',request_id:value.requestId};return inspect('youtube',{broadcast_id:value.broadcastId,broadcasts:[{id:'bound-broadcast',title:'Bound broadcast'},{id:'other-broadcast',title:'Other broadcast'}]});};
 f.editor.setContext({destination:{id:'linked-destination',name:'Linked YouTube',platform:'youtube',linkedAccount:true,youtubeBroadcastId:'bound-broadcast'},revision:2,dirty:false,locked:false});await tick();
 assert.equal(f.requests.at(-1).broadcastId,'bound-broadcast');assert.equal(f.node('Broadcast').value,'bound-broadcast');assert.equal(f.node('Broadcast').children.length,1);assert.equal(f.node('Broadcast').children[0].textContent,'Bound broadcast');assert.equal(f.node('Broadcast').disabled,true);assert.match(f.node('BroadcastHint').textContent,/reviewed when it was saved/);assert.equal(f.node('Apply').disabled,false);
 await f.node('Apply').fire();assert.equal(f.requests.at(-1).broadcastId,'bound-broadcast');f.node('Broadcast').value='other-broadcast';await f.node('Broadcast').fire('change');await tick();assert.equal(f.node('Apply').disabled,true);assert.equal(f.requests.filter(request=>request.action==='apply').length,1);
});
test('unknown or revoked YouTube broadcast binding cannot enable Apply',async()=>{
  const f=fixture('youtube');await tick();let response=inspect('youtube',{broadcasts:[{id:'broadcast-one',title:'Upcoming fixture'}]});f.api.streamMetadata=async()=>response;await f.node('Check').fire();
  response=inspect('youtube',{broadcast_id:'different-broadcast'});delete response.broadcasts;f.node('Broadcast').value='broadcast-one';f.node('Broadcast').fire('change');await tick();assert.equal(f.node('Broadcast').value,'');assert.equal(f.node('Apply').disabled,true);
  response=inspect('youtube',{authorized:false,editable:false});delete response.broadcasts;f.node('Broadcast').value='broadcast-one';f.node('Broadcast').fire('change');await tick();assert.equal(f.node('Broadcast').value,'');assert.equal(f.node('Broadcast').children.length,1);assert.equal(f.node('Apply').disabled,true);
});
test('categories load lazily, preserve leave-current, and use official selected IDs',async()=>{
  const f=fixture('kick');await tick();assert.equal(f.requests.filter(value=>value.action==='categories').length,0);assert.equal(f.node('Category').value,'');f.node('Query').value='Just Chatting';await f.node('Search').fire();assert.equal(f.requests.at(-1).query,'Just Chatting');assert.equal(f.node('Category').children[1].value,'123');assert.match(f.node('Fields').textContent,/tags/);
  f.node('Category').value='123';f.node('Category').fire('change');await f.node('Apply').fire();assert.equal(f.requests.at(-1).categoryId,'123');
});
test('unconfirmed update retains its exact retry through connection checks and clears on saved revision change',async()=>{
  const f=fixture();await tick();let uncertain=true;f.api.streamMetadata=async value=>{f.requests.push({...value});if(value.action==='inspect')return inspect();return uncertain?{state:'unconfirmed'}:{state:'applied',request_id:value.requestId};};
  await f.node('Apply').fire();const first=f.requests.at(-1);assert.match(f.node('Apply').textContent,/Retry same/);await f.node('Check').fire();assert.match(f.node('Status').textContent,/still unconfirmed/);await f.node('Apply').fire();assert.deepEqual(f.requests.at(-1),first);uncertain=false;await f.node('Apply').fire();assert.match(f.node('Status').textContent,/Updated connected channel/);
  f.editor.setContext({revision:3});assert.doesNotMatch(f.node('Status').textContent,/Updated connected channel/);await f.node('Apply').fire();assert.notEqual(f.requests.at(-1).requestId,first.requestId);assert.equal(f.requests.at(-1).revision,3);
});
test('read-only connection stays clear; permission is separate and never silently grants access',async()=>{
  const f=fixture();await tick();f.api.streamMetadata=async value=>{f.requests.push({...value});return value.action==='inspect'?inspect('twitch',{editable:false}):{ok:true,state:'pending'};};await f.node('Check').fire();assert.equal(f.node('Permission').hidden,false);assert.equal(f.node('Apply').disabled,true);assert.match(f.node('Status').textContent,/read-only/);await f.node('Permission').fire();assert.deepEqual(f.busy,[true,false]);assert.match(f.node('Status').textContent,/permission/);assert.equal(f.node('Apply').disabled,true);
});
test('stale inspections cannot replace a newer destination and repeated polling does not query providers',async()=>{
  const f=fixture();await tick();let finish;f.api.streamMetadata=value=>new Promise(resolve=>{finish=()=>resolve(inspect(value.platform));});const old=f.node('Check').fire();f.editor.setContext({destination:{id:'other-destination',platform:'custom',name:'Custom'}});finish();await old;assert.match(f.node('Account').textContent,/Choose a Twitch/);assert.equal(f.node('Apply').disabled,true);const count=f.requests.length;for(let i=0;i<20;i++)f.editor.setContext({locked:false,dirty:false,revision:2});assert.equal(f.requests.length,count);f.editor.close();
});
test('double apply is ignored while active and a closed view ignores the final response',async()=>{
  const f=fixture();await tick();let finish;f.api.streamMetadata=value=>{f.requests.push({...value});return new Promise(resolve=>{finish=()=>resolve({state:'applied',request_id:value.requestId});});};const first=f.node('Apply').fire();await f.node('Apply').fire();assert.equal(f.requests.filter(value=>value.action==='apply').length,1);assert.equal(f.node('Apply').disabled,true);f.editor.close();finish();await first;assert.doesNotMatch(f.node('Status').textContent,/Updated connected channel/);assert.deepEqual(f.busy,[true,false]);
});
test('cancelled and known preflight failures are distinct from an unconfirmed provider write',async()=>{
  const f=fixture();await tick();let response={state:'cancelled'};f.api.streamMetadata=async value=>{f.requests.push({...value});return response;};await f.node('Apply').fire();assert.equal(f.node('Status').dataset.state,'cancelled');assert.match(f.node('Status').textContent,/No platform change was requested/);assert.doesNotMatch(f.node('Apply').textContent,/Retry/);
  response={ok:false,reason:'invalid_tags'};await f.node('Apply').fire();assert.equal(f.node('Status').dataset.state,'failed');assert.match(f.node('Status').textContent,/saved tags/);
  response={ok:false,reason:'provider_unavailable'};await f.node('Apply').fire();assert.equal(f.node('Status').dataset.state,'unconfirmed');assert.match(f.node('Apply').textContent,/Retry same/);
});
test('failed category lookup preserves official selection, and failed permission does not imply consent',async()=>{
  const f=fixture();await tick();await f.node('Search').fire();f.node('Category').value='123';f.node('Category').fire('change');f.api.streamMetadata=async()=>({ok:false,reason:'category_query_too_short'});await f.node('Search').fire();assert.equal(f.node('Category').value,'123');assert.equal(f.node('Category').children.length,2);assert.match(f.node('Status').textContent,/at least two/);
  f.api.streamMetadata=async()=>({ok:false,reason:'app_setup_required'});await f.node('Permission').fire();assert.match(f.node('Status').textContent,/Complete the platform app setup/);
});
test('applied response separates an activity-history warning from confirmed platform readback',async()=>{
  const f=fixture();await tick();f.api.streamMetadata=async value=>({state:'applied',request_id:value.requestId,activity_history_warning:true,recovery_storage_warning:true});await f.node('Apply').fire();assert.equal(f.node('Status').dataset.state,'applied');assert.match(f.node('Status').textContent,/readback confirmed/);assert.match(f.node('Status').textContent,/activity history could not/);assert.match(f.node('Status').textContent,/Restart recovery tracking could not/);
});

test('a temporary provider inspection failure requests a check rather than replacing saved sign-in',async()=>{
  const f=fixture();await tick();f.api.streamMetadata=async()=>({platform:'twitch',authorized:false,editable:false,reason:'provider_unavailable'});await f.node('Check').fire();assert.match(f.node('Status').textContent,/saved sign-in is kept/);assert.match(f.node('Status').textContent,/Retry Check connection/);assert.equal(f.requests.some(value=>value.action==='permission'),false);
});
test('publishing isolation blocks Apply while preserving read-only checks and incremental context',async()=>{
  const f=fixture();await tick();f.editor.setContext({publishingBlocked:true});assert.equal(f.node('Apply').disabled,true);assert.equal(f.node('Check').disabled,false);assert.equal(f.node('Search').disabled,false);assert.match(f.node('Status').textContent,/blocked in rehearsal/);await f.node('Apply').fire();assert.equal(f.requests.some(value=>value.action==='apply'),false);await f.node('Check').fire();await f.node('Search').fire();assert.equal(f.requests.at(-1).action,'categories');f.editor.setContext({locked:false});assert.equal(f.node('Apply').disabled,true);f.editor.setContext({publishingBlocked:false});assert.equal(f.node('Apply').disabled,false);await f.node('Apply').fire();assert.equal(f.requests.at(-1).destinationId,'fixture-destination');assert.equal(f.requests.at(-1).revision,2);
});
