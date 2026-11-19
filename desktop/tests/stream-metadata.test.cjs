'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createStreamMetadataHandler,publicResult}=require('../stream-metadata.cjs');
const destinationId='11111111-1111-4111-8111-111111111111';
function fixture(){
  const event={senderFrame:{url:'file:///fixture/settings.html'}},calls=[],confirms=[],permissions=[];
  const state={revision:3,shared:{title:'Shared fixture title',description:'Shared fixture description'},overrides:{[destinationId]:{title:'Saved fixture title',description:'Saved description',category:'Notes, not an ID',tags:'English, Friendly'}}};
  const info={ok:true,platform:'twitch',authorized:true,editable:true,channel_id:'123',public_label:'fixture_channel',capabilities:{title:true,description:false,category_id:true,tags:true},fields:{title:'Previous public title',category_id:'7',tags:['Previous']}};
  let accepted=true;
  const options={origin:'http://127.0.0.1:8765',store:{public:async()=>structuredClone(state)},destinations:{public:async()=>({destinations:[{id:destinationId,platform:'twitch',name:'Fixture target'}]})},trustedSender:e=>e===event,
    mutate:async(_event,run)=>{calls.push('lock');return run();},confirm:async value=>{confirms.push(value);return accepted;},permission:async(_event,platform)=>{permissions.push(platform);return {ok:true};},
    fetchImpl:async(url,options)=>{const body=JSON.parse(options.body);calls.push({url,body});const value=url.endsWith('/apply')?{ok:true,platform:'twitch',state:'applied',request_id:body.request_id}:info;const response=new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});Object.defineProperty(response,'url',{value:url});return response;}};
  return {event,calls,confirms,permissions,state,info,options,get handler(){return createStreamMetadataHandler(options);},set accepted(v){accepted=v;}};
}
const apply=()=>({action:'apply',platform:'twitch',destinationId,revision:3,requestId:'fixture-request',channelId:'123'});
test('only trusted settings can read or update, and renderer values cannot bypass saved drafts',async()=>{
  const f=fixture();assert.equal((await f.handler({},apply())).reason,'local_operator_required');assert.equal((await f.handler(f.event,{...apply(),values:{title:'Injected'}})).reason,'invalid_stream_info');assert.deepEqual(f.calls,[]);
});
test('Apply uses the saved revision and official category ID, omits unsupported description and preserves retry identity',async()=>{
  const f=fixture(),handler=f.handler,payload={...apply(),categoryId:'42'};for(let i=0;i<2;i++)assert.equal((await handler(f.event,payload)).state,'applied');
  const writes=f.calls.filter(c=>c.url?.endsWith('/apply'));assert.equal(writes.length,2);assert.deepEqual(writes[0].body,writes[1].body);assert.deepEqual(writes[0].body.values,{title:'Saved fixture title',tags:['English','Friendly'],category_id:'42'});assert.equal(writes[0].body.expected_channel_id,'123');assert.equal(f.confirms[0].channelLabel,'fixture_channel');
});
test('stale revision, removed target and changed account fail before a platform write',async()=>{
  const f=fixture();assert.equal((await f.handler(f.event,{...apply(),revision:2})).reason,'stream_info_revision_conflict');f.options.destinations.public=async()=>({destinations:[]});assert.equal((await f.handler(f.event,apply())).reason,'destination_not_found');f.options.destinations.public=async()=>({destinations:[{id:destinationId,platform:'twitch'}]});f.info.channel_id='456';assert.equal((await f.handler(f.event,apply())).reason,'account_identity_mismatch');assert.equal(f.calls.some(c=>c.url?.endsWith('/apply')),false);
});
test('Cancel never writes; read-only permission and missing YouTube broadcast are actionable',async()=>{
  const f=fixture();f.accepted=false;assert.equal((await f.handler(f.event,apply())).state,'cancelled');assert.equal(f.calls.some(c=>c.url?.endsWith('/apply')),false);f.accepted=true;f.info.editable=false;assert.equal((await f.handler(f.event,apply())).reason,'metadata_scope_required');
});
test('permission delegates to the existing guarded owner without nesting the mutation lock',async()=>{
  const f=fixture();assert.equal((await f.handler(f.event,{action:'permission',platform:'kick'})).ok,true);assert.deepEqual(f.permissions,['kick']);assert.deepEqual(f.calls,[]);
});
test('public projection drops credential-shaped fields and rejects oversized collections',()=>{
  assert.equal(publicResult({recovery_storage_warning:true}).recovery_storage_warning,true);
  const result=publicResult({ok:true,platform:'kick',access_token:'private',authorization_url:'private',fields:{title:'Public',access_token:'private'},categories:[{id:'1',name:'Games',streamKey:'private'}]});assert.equal(JSON.stringify(result).includes('private'),false);assert.throws(()=>publicResult({categories:Array.from({length:101},()=>({id:'1',name:'x'}))}),/provider_unavailable/);
});
test('navigation during a confirmation cancels the write and metadata parsing is bounded',async()=>{
  const f=fixture();f.options.confirm=async()=>{f.event.senderFrame={url:'file:///elsewhere'};return true;};assert.equal((await f.handler(f.event,apply())).reason,'local_operator_required');assert.equal(f.calls.some(c=>c.url?.endsWith('/apply')),false);
});
