'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {LiveAudioSession,MAX_RECEIPTS}=require('../live-audio-session.cjs');
const OUTPUT='12345678-1234-1234-1234-123456789abc',NEXT='22345678-1234-1234-1234-123456789abc';
const base={'voice:default':{live:true,vod:true}},boost={'voice:default':{live:true,vod:true,liveGainDb:6}};
const request=(extra={})=>({outputId:OUTPUT,expectedRevision:0,requestId:'first',audioRouting:JSON.parse(JSON.stringify(boost)),...extra});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(options={}){
  const applies=[],audits=[];
  const session=new LiveAudioSession({apply:async value=>{applies.push(value);return {ok:true,requestId:value.requestId,applied:true};},
    audit:metadata=>audits.push(metadata),...options});
  session.init({outputId:OUTPUT,profileId:'saved-profile',audioRouting:base});
  return {session,applies,audits};
}
const rejects=(promise,code)=>assert.rejects(promise,error=>error.code===code&&error.message===code);

test('confirmed ACK changes only effective routing/revision and audits metadata only',async()=>{
  const f=fixture(),input=request(),before=f.session.savedBase;
  const result=await f.session.set(input);input.audioRouting['voice:default'].liveGainDb=12;
  assert.equal(result.revision,1);assert.equal(result.applied,true);assert.equal(result.uncertain,false);
  assert.equal(result.applying,false);assert.equal(f.session.status().applying,false);
  assert.equal(result.routing['voice:default'].liveGainDb,6);assert.deepEqual(before,base);
  assert.equal(Object.isFrozen(before),true);assert.equal(Object.isFrozen(before['voice:default']),true);
  assert.deepEqual(f.audits,[{profileId:'saved-profile',requestId:'first',revision:1}]);
  assert.doesNotMatch(JSON.stringify(f.audits),/Gain|voice:|audioRouting/);
  result.routing['voice:default'].live=false;assert.equal(f.session.status().routing['voice:default'].live,true);
});

test('wrong output/revision and malformed requests fail before apply',async()=>{
  const f=fixture();
  await rejects(f.session.set(request({outputId:NEXT})),'audio_output_changed');
  await rejects(f.session.set(request({expectedRevision:1})),'audio_revision_conflict');
  for(const change of [{extra:'private'},{expectedRevision:-1},{expectedRevision:true},{requestId:'../private'},{outputId:'private'}])
    await rejects(f.session.set(request(change)),'invalid_audio_request');
  await rejects(f.session.set(request({audioRouting:{'https://private.example':{live:true,vod:true}}})),'invalid_audio_routing');
  assert.equal(f.applies.length,0);assert.equal(f.session.status().uncertain,false);
});

test('same in-flight ID shares one apply while different requests are rejected',async()=>{
  const wait=deferred(),calls=[];
  const f=fixture({apply:value=>{calls.push(value);return wait.promise;}});
  const first=f.session.set(request()),retry=f.session.set(request());
  assert.equal(f.session.status().applying,true);
  assert.equal(first,retry);await tick();assert.equal(calls.length,1);
  await rejects(f.session.set(request({requestId:'different'})),'audio_routing_busy');
  await rejects(f.session.set(request({audioRouting:base})),'audio_request_conflict');
  wait.resolve({requestId:'first',applied:true});await first;assert.equal(f.session.status().revision,1);assert.equal(f.session.status().applying,false);
});

test('successful retry returns current confirmed state without forwarding or bumping revision',async()=>{
  const f=fixture();await f.session.set(request());
  await f.session.set(request({requestId:'second',expectedRevision:1,audioRouting:base}));
  const result=await f.session.set(request());
  assert.equal(result.replayed,true);assert.equal(result.revision,2);assert.deepEqual(result.routing,base);
  assert.equal(f.applies.length,2);assert.equal(f.audits.length,2);
});

test('ambiguous timeout exposes exact recovery request and ignores late ACK until same-ID reconciliation',async()=>{
  const wait=deferred(),calls=[];
  const f=fixture({timeoutMs:10,apply:value=>{calls.push(value);return calls.length===1?wait.promise:Promise.resolve({requestId:value.requestId,applied:true});}});
  await rejects(f.session.set(request()),'audio_routing_timeout');
  const status=f.session.status();assert.equal(status.uncertain,true);assert.equal(status.applying,false);assert.equal(status.revision,0);assert.deepEqual(status.routing,base);
  assert.deepEqual(status.pending,{requestId:'first',expectedRevision:0,audioRouting:boost});
  status.pending.audioRouting['voice:default'].live=false;
  await rejects(f.session.set(request({requestId:'new'})),'audio_routing_uncertain');
  await rejects(f.session.set(request({audioRouting:base})),'audio_request_conflict');
  wait.resolve({requestId:'first',applied:true});await tick();assert.equal(f.session.status().revision,0);
  const reconciled=await f.session.set(request());assert.equal(reconciled.revision,1);assert.equal(reconciled.uncertain,false);
  assert.equal('pending'in reconciled,false);assert.equal(calls.length,2);
  assert.equal((await f.session.set(request())).replayed,true);assert.equal(calls.length,2);
});

test('capture cancellation or invalid ACK remains uncertain and never claims a DSP result',async()=>{
  for(const apply of [async()=>{throw Object.assign(Error('private path'),{code:'audio_routing_cancelled'});},
    async()=>({requestId:'wrong',applied:true}),async()=>({requestId:'first',applied:false}),async()=>{throw Error('private token');}]){
    const f=fixture({apply});const result=await f.session.set(request()).catch(error=>error);
    assert.match(result.code,/^audio_routing_(cancelled|unavailable)$/);assert.doesNotMatch(result.message,/private|token/);
    assert.equal(f.session.status().uncertain,true);assert.equal(f.session.status().revision,0);assert.deepEqual(f.session.status().routing,base);
  }
});

test('audit failure warns after ACK and never rolls DSP back or forwards routing to audit',async()=>{
  const applies=[],metadata=[];
  const f=fixture({apply:async value=>{applies.push(value);return {requestId:value.requestId,applied:true};},audit:value=>{metadata.push(value);throw Error('private audit');}});
  const result=await f.session.set(request());assert.equal(result.historyWarning,true);assert.equal(result.revision,1);assert.equal(result.uncertain,false);
  assert.equal(applies.length,1);assert.deepEqual(Object.keys(metadata[0]).sort(),['profileId','requestId','revision']);
  assert.equal((await f.session.set(request())).historyWarning,true);assert.equal(applies.length,1);
});

test('close or Prepare cancels awaiting apply promptly and stale ACK cannot mutate new session',async()=>{
  for(const replace of [false,true]){
    const wait=deferred();const f=fixture({timeoutMs:10000,apply:()=>wait.promise});
    const pending=f.session.set(request());await tick();
    if(replace)f.session.init({outputId:NEXT,profileId:'next-profile',audioRouting:{'video:default':{live:true,vod:false}}});
    else f.session.close();
    await rejects(pending,'audio_routing_cancelled');
    const before=f.session.status();wait.resolve({requestId:'first',applied:true});await tick();
    assert.deepEqual(f.session.status(),before);assert.equal(before.revision,0);assert.equal(before.uncertain,false);
    assert.equal(before.outputId,replace?NEXT:null);
  }
});

test('close before asynchronous forwarding prevents the obsolete DSP call',async()=>{
  const f=fixture();const pending=f.session.set(request());f.session.close();
  await rejects(pending,'audio_routing_cancelled');assert.equal(f.applies.length,0);
});

test('Prepare during audit cannot set warnings or routing on the replacement session',async()=>{
  const wait=deferred();const f=fixture({audit:()=>wait.promise});
  const pending=f.session.set(request());await tick();assert.equal(f.session.status().revision,1);
  f.session.init({outputId:NEXT,profileId:'next',audioRouting:base});
  await rejects(pending,'audio_routing_cancelled');wait.reject(Error('private late audit'));await tick();
  assert.deepEqual(f.session.status(),{outputId:NEXT,revision:0,routing:base,applying:false,uncertain:false,historyWarning:false});
});

test('receipt window retains exactly the latest64 confirmed mutations',async()=>{
  const f=fixture();
  for(let index=0;index<70;index++)await f.session.set(request({requestId:'request-'+index,expectedRevision:index,audioRouting:index%2?base:boost}));
  assert.equal(MAX_RECEIPTS,64);assert.equal(f.session.status().revision,70);
  assert.equal((await f.session.set(request({requestId:'request-6',expectedRevision:6}))).replayed,true);
  await rejects(f.session.set(request({requestId:'request-5',expectedRevision:5,audioRouting:base})),'audio_revision_conflict');
  assert.equal(f.applies.length,70);
});
