'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {normalize,createController,VERIFY_URL}=require('../settings-accounts.js');
const saved={platform:'twitch',state:'authorized',reason:'account_authorized',authorized:true,streaming_authorized:false,app_configured:true,public_label:'fixture_channel',account_ref:'a'.repeat(64),expires_at:2000};
const pending={...saved,state:'pending',reason:'authorization_pending',user_code:'DEMO-1234',flow_id:'b'.repeat(32),expires_at:1500};
const streaming={...saved,streaming_authorized:true};
const deferred=()=>{let resolve;const promise=new Promise(a=>resolve=a);return {promise,resolve};};
function fixture(){
  let result={account:saved},now=1000,serial=0,changed=0,approved=true;const calls=[],timers=new Map(),messages=[],opens=[],copies=[];
  const controller=createController({request:async value=>{calls.push(value);if(result instanceof Error)throw result;return typeof result==='function'?result(value):result;},onChange:value=>messages.push(value),onDestinationsChanged:async()=>{changed++;},confirmDisconnect:async()=>approved,copy:async value=>copies.push(value),open:async value=>opens.push(value),now:()=>now,randomId:()=>'receipt-'+(++serial),schedule:(fn,delay)=>{timers.set(++serial,{fn,delay});return serial;},unschedule:id=>timers.delete(id)});
  return {controller,calls,timers,messages,opens,copies,set result(value){result=value;},set approved(value){approved=value;},set now(value){now=value;},get changed(){return changed;}};
}
test('account normalization admits only public metadata and fixed pending code contracts',()=>{
  const value=normalize({...saved,access_token:'secret',refresh_token:'secret',authorization_url:'https://bad'},1000);
  assert.equal(value.access_token,undefined);assert.equal(value.refresh_token,undefined);assert.equal(value.authorization_url,undefined);
  assert.equal(normalize({...saved,streaming_authorized:'true'},1000).streaming_authorized,false);
  assert.equal(normalize({...saved,reason:'https://private/token'},1000).reason,'account_unavailable');
  assert.throws(()=>normalize({...pending,user_code:'<script>'},1000));
  assert.throws(()=>normalize({...pending,flow_id:'unsafe'},1000));
  const expired=normalize(pending,1500);assert.equal(expired.state,'authorized');assert.equal(expired.reason,'authorization_expired');assert.equal(expired.user_code,undefined);assert.equal(expired.authorized,true);
});
test('saved chat connection is preserved during upgrade and pending polling uses two seconds',async()=>{
  const f=fixture();await f.controller.start();assert.equal(f.controller.snapshot().account.authorized,true);assert.equal(f.controller.snapshot().account.streaming_authorized,false);
  f.result={account:pending};await f.controller.run('begin');assert.equal(f.calls.at(-1).action,'begin');assert.equal(f.controller.snapshot().account.authorized,true);assert.equal([...f.timers.values()][0].delay,2000);
  assert.equal(await f.controller.run('link'),false);await f.controller.copyCode();assert.deepEqual(f.copies,['DEMO-1234']);await f.controller.openSignIn();assert.deepEqual(f.opens,[VERIFY_URL]);
  f.result={account:{...saved,reason:'authorization_cancelled'}};await f.controller.run('cancel');assert.equal(f.controller.snapshot().account.authorized,true);assert.equal(f.controller.snapshot().account.streaming_authorized,false);assert.equal([...f.timers.values()].filter(item=>item.delay===2000).length,0);
});
test('link retry keeps its request id after ambiguous failure and a status check',async()=>{
  const f=fixture();f.result={account:streaming};await f.controller.start();f.result=Error('secret exception');await f.controller.run('link');assert.equal(f.controller.snapshot().stale,true);assert.doesNotMatch(f.controller.snapshot().message,/secret/);const request=f.calls.at(-1);
  assert.equal(await f.controller.run('link'),false);f.result={account:streaming};await f.controller.run('check');await f.controller.run('link');assert.deepEqual(f.calls.at(-1),request);assert.equal(f.changed,1);
  await f.controller.run('link');assert.notEqual(f.calls.at(-1).requestId,request.requestId);
});
test('unavailable status leaves the previous saved identity visible and history warning persists polling',async()=>{
  const f=fixture();f.result={account:streaming,activity_history_warning:true};await f.controller.start();f.result={account:streaming};await f.controller.run('status');assert.equal(f.controller.snapshot().historyWarning,true);
  f.result={ok:false,reason:'provider_unavailable',token:'secret'};await f.controller.run('status');const state=f.controller.snapshot();assert.equal(state.stale,true);assert.equal(state.account.public_label,'fixture_channel');assert.equal(state.account.authorized,true);assert.equal(state.historyWarning,true);assert.doesNotMatch(JSON.stringify(state),/secret/);
});
test('cancel wins over a late begin and closing ignores stale callbacks',async()=>{
  const f=fixture();await f.controller.start();const begin=deferred();f.result=()=>begin.promise;const work=f.controller.run('begin');f.result={account:{...saved,reason:'authorization_cancelled'}};await f.controller.run('cancel');begin.resolve({account:pending});await work;assert.equal(f.controller.snapshot().account.state,'authorized');assert.equal(f.controller.snapshot().busy,'');
  const check=deferred();f.result=()=>check.promise;const checking=f.controller.run('check');const count=f.messages.length;f.controller.close();check.resolve({account:streaming});await checking;assert.equal(f.messages.length,count);assert.equal(f.timers.size,0);
});
test('broadcast lock prevents account changes while permitting cancellation and status',async()=>{
  const f=fixture();f.result={account:streaming};await f.controller.start();f.controller.setLocked(true);for(const action of ['begin','check','link','disconnect'])assert.equal(await f.controller.run(action),false);assert.equal(f.calls.length,1);await f.controller.run('status');assert.equal(f.calls.length,2);await f.controller.run('cancel');assert.equal(f.calls.length,3);
});
test('disconnect requires confirmation, clears only through the API and refreshes destinations',async()=>{
  const f=fixture();await f.controller.start();f.approved=false;assert.equal(await f.controller.run('disconnect'),false);assert.equal(f.calls.length,1);
  f.approved=true;f.result={account:{platform:'twitch',state:'not_authorized',reason:'authorization_required',authorized:false,app_configured:true}};await f.controller.run('disconnect');assert.equal(f.calls.at(-1).action,'disconnect');assert.equal(f.controller.snapshot().account.authorized,false);assert.equal(f.changed,1);
});
test('account change retires a failed link receipt and unsafe provider text is never shown',async()=>{
  const f=fixture();f.result={account:streaming};await f.controller.start();f.result={ok:false,reason:'secret raw token'};await f.controller.run('link');const first=f.calls.at(-1).requestId;assert.doesNotMatch(f.controller.snapshot().message,/secret/);
  f.result={account:{...streaming,account_ref:'c'.repeat(64)}};await f.controller.run('check');await f.controller.run('link');assert.notEqual(f.calls.at(-1).requestId,first);
});
test('unconfirmed chat shutdown remains warned across polling and blocks a new account link',async()=>{
  const f=fixture();f.result={account:streaming};await f.controller.start();f.result={account:{...streaming,authorized:false,streaming_authorized:false,state:'not_authorized',reason:'authorization_required'},connection_stop_warning:true};await f.controller.run('disconnect');assert.equal(f.controller.snapshot().stopWarning,true);
  f.result={account:streaming};await f.controller.run('status');assert.equal(f.controller.snapshot().stopWarning,true);assert.equal(await f.controller.run('begin'),false);assert.equal(await f.controller.run('link'),false);
});
