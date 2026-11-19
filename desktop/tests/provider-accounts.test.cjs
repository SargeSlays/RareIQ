'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {normalize,createController}=require('../settings-provider-accounts.js');
const NOW=1800000000;
const saved=platform=>({platform,state:'authorized',authorized:true,app_configured:true,reason:'account_authorized',public_label:'Fixture channel',expires_at:NOW+3600});
const pending=platform=>({...saved(platform),state:'pending',reason:'authorization_pending',flow_id:'a'.repeat(32),expires_at:NOW+600});
function fixture(platform='youtube'){
  const f={calls:[],imports:[],messages:[],timers:new Map(),result:{ok:true,account:saved(platform)},importResult:{ok:true,configured:true,platform},approved:true,changed:0,refreshError:false};let timer=0,requestSerial=0;
  f.controller=createController({platform,request:async value=>{f.calls.push(value);return typeof f.result==='function'?f.result():f.result;},importApp:async value=>{f.imports.push(value);return typeof f.importResult==='function'?f.importResult():f.importResult;},onDestinationsChanged:async()=>{f.changed++;if(f.refreshError)throw Error('private refresh error');},randomId:()=>`fixture-link-${++requestSerial}`,confirmDisconnect:async()=>f.approved,onChange:value=>f.messages.push(value),schedule:(fn,ms)=>{assert.equal(ms,2000);f.timers.set(++timer,fn);return timer;},unschedule:id=>f.timers.delete(id),now:()=>NOW});return f;
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
const notConfigured=platform=>({platform,state:'not_authorized',reason:'app_setup_required',authorized:false,app_configured:false});
test('app file setup passes only platform, reloads metadata and prepares sign-in without authorizing it',async()=>{
  for(const platform of ['youtube','kick']){
    const f=fixture(platform);f.result={ok:true,account:notConfigured(platform)};await f.controller.start();
    f.result={ok:true,account:{...notConfigured(platform),app_configured:true,reason:'authorization_required'}};assert.equal(await f.controller.run('setup'),true);
    assert.deepEqual(f.imports,[platform]);assert.deepEqual(f.calls,[{platform,action:'status'},{platform,action:'status'}]);const state=f.controller.snapshot();assert.equal(state.account.app_configured,true);assert.equal(state.account.authorized,false);assert.match(state.message,/Sign in with/);assert.equal(state.busy,'');
  }
});
test('file chooser cancellation keeps metadata, warnings and existing setup without a reload',async()=>{
  const f=fixture();f.result={ok:true,account:notConfigured('youtube'),activity_history_warning:true};await f.controller.start();const before=f.controller.snapshot().account;
  f.importResult={ok:true,cancelled:true,platform:'youtube'};assert.equal(await f.controller.run('setup'),true);assert.deepEqual(f.controller.snapshot().account,before);assert.equal(f.controller.snapshot().historyWarning,true);assert.equal(f.calls.length,1);assert.match(f.controller.snapshot().message,/previous setup is kept/);
});
test('app setup cannot overwrite authorized or pending accounts and respects the broadcast lock',async()=>{
  const f=fixture();await f.controller.start();assert.equal(await f.controller.run('setup'),false);f.result={ok:true,account:pending('youtube')};await f.controller.run('status');assert.equal(await f.controller.run('setup'),false);
  f.result={ok:true,account:notConfigured('youtube')};await f.controller.run('status');f.controller.setLocked(true);assert.equal(await f.controller.run('setup'),false);assert.equal(f.imports.length,0);
});
test('closing during file selection retires the result and never reloads or displays credentials',async()=>{
  const f=fixture('kick');f.result={ok:true,account:notConfigured('kick')};await f.controller.start();const picking=deferred();f.importResult=()=>picking.promise;const work=f.controller.run('setup');assert.equal(f.controller.snapshot().busy,'setup');f.controller.close();const count=f.messages.length;picking.resolve({ok:true,configured:true,platform:'kick',client_secret:'must-not-pass'});await work;assert.equal(f.calls.length,1);assert.equal(f.messages.length,count);assert.doesNotMatch(JSON.stringify(f.controller.snapshot()),/must-not-pass/);
});
test('saved configuration with failed metadata refresh is reported separately and history stays warned',async()=>{
  const f=fixture();f.result={ok:true,account:notConfigured('youtube')};await f.controller.start();f.importResult={ok:true,configured:true,platform:'youtube',activity_history_warning:true};f.result={ok:false,reason:'provider_unavailable'};assert.equal(await f.controller.run('setup'),false);assert.match(f.controller.snapshot().message,/App setup was saved/);assert.equal(f.controller.snapshot().historyWarning,true);assert.equal(f.controller.snapshot().stale,true);
  f.result={ok:true,account:{...notConfigured('youtube'),app_configured:true,reason:'authorization_required'}};await f.controller.run('check');assert.equal(f.controller.snapshot().account.app_configured,true);
});
test('app file errors use constant recovery messages and status check enables a safe retry',async()=>{
  const f=fixture('kick');f.result={ok:true,account:notConfigured('kick')};await f.controller.start();f.importResult={ok:false,reason:'invalid_app_configuration',path:'private-file.json'};assert.equal(await f.controller.run('setup'),false);assert.match(f.controller.snapshot().message,/not a valid provider app setup file/);assert.doesNotMatch(JSON.stringify(f.controller.snapshot()),/private-file/);assert.equal(await f.controller.run('setup'),false);await f.controller.run('status');f.importResult={ok:true,cancelled:true,platform:'kick'};assert.equal(await f.controller.run('setup'),true);
});

const kickStreaming=(extra={})=>({...saved('kick'),streaming_authorized:true,account_ref:'b'.repeat(64),...extra});
test('Kick destination requires fresh authorized streaming access and a strict opaque account reference',async()=>{
  for(const extra of [{streaming_authorized:false},{streaming_authorized:'true'},{account_ref:'private-ingest-url'},{account_ref:'B'.repeat(64)},{state:'pending',flow_id:'a'.repeat(32)},{expires_at:NOW-1},{authorized:false}]){
    const f=fixture('kick');f.result={ok:true,account:kickStreaming(extra)};await f.controller.start();assert.equal(await f.controller.run('link'),false);assert.equal(f.calls.length,1);
  }
  const f=fixture('youtube');f.result={ok:true,account:{...saved('youtube'),streaming_authorized:true,account_ref:'b'.repeat(64)}};await f.controller.start();assert.equal(await f.controller.run('link'),false);assert.equal(f.controller.snapshot().account.streaming_authorized,undefined);
});
test('Kick saves only platform and stable retry receipt after an ambiguous response and same-account read',async()=>{
  const f=fixture('kick');f.result={ok:true,account:kickStreaming()};await f.controller.start();f.result=()=>{throw Error('private key must not display');};await f.controller.run('link');const first=f.calls.at(-1);assert.deepEqual(first,{platform:'kick',action:'link',requestId:'fixture-link-1'});assert.equal(f.controller.snapshot().stale,true);assert.equal(f.controller.snapshot().linkRetry,true);assert.equal(await f.controller.run('link'),false);assert.doesNotMatch(f.controller.snapshot().message,/private key/);f.result={ok:true,account:kickStreaming()};await f.controller.run('status');await f.controller.run('link');assert.deepEqual(f.calls.at(-1),first);assert.equal(f.changed,1);assert.equal(f.controller.snapshot().linkRetry,false);assert.match(f.controller.snapshot().message,/Kick destination saved/);assert.match(f.controller.snapshot().message,/platform receipt remains unverified/);await f.controller.run('link');assert.notEqual(f.calls.at(-1).requestId,first.requestId);
});
test('Kick account change retires old retry and lock preserves read-only status without sending Link',async()=>{
  const f=fixture('kick');f.result={ok:true,account:kickStreaming()};await f.controller.start();f.result={ok:false,reason:'account_state_changed'};await f.controller.run('link');const first=f.calls.at(-1).requestId;f.result={ok:true,account:kickStreaming({account_ref:'c'.repeat(64)})};await f.controller.run('check');assert.equal(f.controller.snapshot().linkRetry,false);f.controller.setLocked(true);assert.equal(await f.controller.run('link'),false);const before=f.calls.length;assert.equal(await f.controller.run('status'),true);assert.equal(f.calls.length,before+1);f.controller.setLocked(false);await f.controller.run('link');assert.notEqual(f.calls.at(-1).requestId,first);
});
test('double Kick save is suppressed and late close response cannot refresh destination state',async()=>{
  const f=fixture('kick');f.result={ok:true,account:kickStreaming()};await f.controller.start();const link=deferred();f.result=()=>link.promise;const saving=f.controller.run('link');assert.equal(await f.controller.run('link'),false);assert.equal(f.calls.filter(call=>call.action==='link').length,1);f.controller.close();const before=f.messages.length;link.resolve({ok:true,account:kickStreaming()});await saving;assert.equal(f.changed,0);assert.equal(f.messages.length,before);
});
test('confirmed Kick save distinguishes list refresh/history warnings from an unconfirmed save',async()=>{
  const f=fixture('kick');f.result={ok:true,account:kickStreaming()};await f.controller.start();f.refreshError=true;f.result={ok:true,account:kickStreaming(),activity_history_warning:true};assert.equal(await f.controller.run('link'),true);const state=f.controller.snapshot();assert.equal(state.stale,false);assert.equal(state.linkRetry,false);assert.equal(state.historyWarning,true);assert.match(state.message,/destination saved/);assert.match(state.message,/destination list could not refresh/);assert.doesNotMatch(state.message,/private refresh error/);
});


test('definitive Kick destination conflict retires its receipt while ambiguous retries remain exact',async()=>{
 for(const reason of ['destination_request_conflict','destination_request_retired']){const f=fixture('kick');f.result={ok:true,account:kickStreaming()};await f.controller.start();f.result={ok:false,reason};await f.controller.run('link');const first=f.calls.at(-1).requestId;assert.equal(f.controller.snapshot().linkRetry,false);assert.equal(await f.controller.run('link'),false);f.result={ok:true,account:kickStreaming()};await f.controller.run('check');await f.controller.run('link');assert.notEqual(f.calls.at(-1).requestId,first);assert.equal(f.changed,1);f.controller.close();}
});
