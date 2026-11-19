'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {normalize,createController}=require('../settings-provider-accounts.js');
const NOW=1800000000;
const saved=platform=>({platform,state:'authorized',authorized:true,app_configured:true,reason:'account_authorized',public_label:'Fixture channel',expires_at:NOW+3600});
const pending=platform=>({...saved(platform),state:'pending',reason:'authorization_pending',flow_id:'a'.repeat(32),expires_at:NOW+600});
function fixture(platform='youtube'){
  const f={calls:[],messages:[],timers:new Map(),result:{ok:true,account:saved(platform)},approved:true};let timer=0;
  f.controller=createController({platform,request:async value=>{f.calls.push(value);return typeof f.result==='function'?f.result():f.result;},confirmDisconnect:async()=>f.approved,onChange:value=>f.messages.push(value),schedule:(fn,ms)=>{assert.equal(ms,2000);f.timers.set(++timer,fn);return timer;},unschedule:id=>f.timers.delete(id),now:()=>NOW});return f;
}
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
test('saved identity reopens through public status without credentials or authorization URLs',async()=>{
  for(const platform of ['youtube','kick']){
    const f=fixture(platform);f.result={ok:true,account:{...saved(platform),access_token:'private-access',refresh_token:'private-refresh',authorization_url:'https://private.invalid/?code=secret'}};
    await f.controller.start();assert.equal(f.controller.snapshot().account.authorized,true);assert.equal(f.controller.snapshot().account.public_label,'Fixture channel');assert.deepEqual(f.calls,[{platform,action:'status'}]);assert.doesNotMatch(JSON.stringify(f.controller.snapshot()),/private-|authorization_url/);assert.equal(f.timers.size,0);
  }
});
test('missing provider app setup prevents beginning sign-in and never pretends connected',async()=>{
  const f=fixture('kick');f.result={ok:true,account:{platform:'kick',state:'not_authorized',reason:'app_setup_required',authorized:false,app_configured:false}};await f.controller.start();assert.equal(await f.controller.run('begin'),false);assert.equal(f.calls.length,1);assert.match(f.controller.snapshot().message,/One-time Kick app setup/);assert.equal(f.controller.snapshot().account.authorized,false);
});
test('pending sign-in passes only platform and opaque flow ID to Main; browser opens once',async()=>{
  for(const platform of ['youtube','kick']){
    const f=fixture(platform);await f.controller.start();f.result={ok:true,account:pending(platform)};await f.controller.run('begin');assert.equal(f.timers.size,1);await f.controller.run('authorize');assert.deepEqual(f.calls.at(-1),{platform,action:'authorize',flowId:'a'.repeat(32)});assert.equal(await f.controller.run('authorize'),false);assert.match(f.controller.snapshot().message,/opened browser/);f.controller.close();assert.equal(f.timers.size,0);
  }
});
test('Cancel supersedes delayed Begin and no late reply restores pending state',async()=>{
  const f=fixture();await f.controller.start();const begin=deferred();f.result=()=>begin.promise;const work=f.controller.run('begin');f.result={ok:true,account:{...saved('youtube'),reason:'authorization_cancelled'}};assert.equal(await f.controller.run('cancel'),true);begin.resolve({ok:true,account:pending('youtube')});await work;assert.equal(f.controller.snapshot().account.state,'authorized');assert.equal(f.controller.snapshot().busy,'');
});
test('close retires callbacks and timers, while reopen loads the saved connection again',async()=>{
  const f=fixture();await f.controller.start();const checking=deferred();f.result=()=>checking.promise;const work=f.controller.run('check');f.controller.close();const before=f.messages.length;checking.resolve({ok:true,account:pending('youtube')});await work;assert.equal(f.messages.length,before);assert.equal(f.timers.size,0);f.result={ok:true,account:saved('youtube')};await f.controller.start();assert.equal(f.controller.snapshot().account.state,'authorized');
});
test('broadcast lock blocks changes but leaves cancellation and status available',async()=>{
  const f=fixture('kick');f.result={ok:true,account:pending('kick')};await f.controller.start();f.controller.setLocked(true);for(const action of ['begin','authorize','check','disconnect'])assert.equal(await f.controller.run(action),false);assert.equal(await f.controller.run('cancel'),true);assert.equal(await f.controller.run('status'),true);
});
test('disconnect is confirmed locally and history/stop warnings remain distinct across polling',async()=>{
  const f=fixture('kick');await f.controller.start();f.approved=false;assert.equal(await f.controller.run('disconnect'),false);assert.equal(f.calls.length,1);f.approved=true;f.result={ok:true,account:{...saved('kick'),authorized:false,state:'not_authorized',reason:'account_disconnected'},activity_history_warning:true,connection_stop_warning:true};await f.controller.run('disconnect');assert.equal(f.calls.at(-1).action,'disconnect');f.result={ok:true,account:saved('kick')};await f.controller.run('status');assert.equal(f.controller.snapshot().historyWarning,true);assert.equal(f.controller.snapshot().stopWarning,true);assert.equal(await f.controller.run('begin'),false);
});
test('malformed or unavailable status preserves previous saved identity and hides provider error text',async()=>{
  const f=fixture();await f.controller.start();f.result={ok:false,reason:'secret provider payload'};await f.controller.run('status');assert.equal(f.controller.snapshot().stale,true);assert.equal(f.controller.snapshot().account.public_label,'Fixture channel');assert.doesNotMatch(f.controller.snapshot().message,/secret/);assert.equal(await f.controller.run('begin'),false);
});
test('expiry and strict public fields reject malformed pending IDs and unsafe identity labels',()=>{
  assert.throws(()=>normalize({...pending('youtube'),flow_id:'https://invalid/'},'youtube',NOW));assert.equal(normalize({...pending('kick'),expires_at:NOW-1},'kick',NOW).reason,'authorization_expired');const raw=normalize({...saved('kick'),authorized:'true',public_label:'bad\nlabel'},'kick',NOW);assert.equal(raw.authorized,false);assert.equal(raw.public_label,undefined);assert.equal(normalize({...saved('youtube'),state:'unavailable'},'youtube',NOW).authorized,false);
});
test('expired saved authorization becomes a reconnect state rather than a ready account',()=>{
  const raw=normalize({...saved('youtube'),expires_at:NOW-1},'youtube',NOW);assert.equal(raw.state,'not_authorized');assert.equal(raw.authorized,false);assert.equal(raw.reason,'authorization_refresh_required');assert.equal(raw.public_label,'Fixture channel');
});
