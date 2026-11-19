'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events'),{PassThrough}=require('node:stream'),path=require('node:path');
const {createTwitchConnection,createTwitchResolver}=require('../twitch-connection.cjs');
const origin='http://127.0.0.1:8768',ref='a'.repeat(64);
const account={platform:'twitch',state:'authorized',reason:'account_authorized',authorized:true,streaming_authorized:true,app_configured:true,public_label:'synthetic_channel',account_ref:ref};
function fixture(options={}){
  const event={senderFrame:{url:'file:///trusted/settings.html'}}, calls=[], saved=[], entries=[];
  const fetchImpl=async(url,request)=>{calls.push({url,request});return new Response(JSON.stringify(url.endsWith('/accounts')?{accounts:[options.account||account]}:{account:options.account||account}),{status:200,headers:{'Content-Type':'application/json'}});};
  const fetchWithUrl=async(...args)=>{const response=await fetchImpl(...args);Object.defineProperty(response,'url',{value:args[0]});return response;};
  const run=createTwitchConnection({origin,trustedSender:value=>value===event,fetchImpl:fetchWithUrl,mutate:async(_e,fn)=>fn(),store:{saveAccount:async value=>{saved.push(value);return {destination:{id:'saved-id',linkedAccount:true},replayed:false};}},append:async value=>entries.push(value),...options});
  return {event,calls,saved,entries,run};
}
test('native Twitch link verifies streaming grant, stores reference and returns no provider secrets',async()=>{
  const f=fixture({account:{...account,access_token:'secret-access',refresh_token:'secret-refresh',stream_key:'secret-key'}});
  const result=await f.run(f.event,{action:'link',requestId:'request-one'});
  assert.equal(result.ok,true);assert.equal(f.calls[0].url,origin+'/api/production/accounts/twitch/check');assert.equal(f.calls[0].request.headers.Origin,origin);
  assert.deepEqual(f.saved,[{platform:'twitch',name:'Twitch · synthetic_channel',accountRef:ref,requestId:'request-one'}]);
  assert.equal(f.entries.length,1);assert.equal(JSON.stringify([result,f.entries]).includes('secret-'),false);
});
test('untrusted and malformed calls fail before any account or destination work',async()=>{
  const f=fixture();assert.equal((await f.run({}, {action:'begin'})).reason,'local_operator_required');
  for(const value of [null,{action:'unknown'},{action:'link'},{action:'begin',access_token:'no'}])assert.equal((await f.run(f.event,value)).reason,'invalid_account_request');
  assert.equal(f.calls.length,0);assert.equal(f.saved.length,0);
});
test('chat-only login cannot create a broadcast destination',async()=>{
  const f=fixture({account:{...account,streaming_authorized:false}});assert.equal((await f.run(f.event,{action:'link',requestId:'one'})).reason,'account_authorization_required');assert.equal(f.saved.length,0);
});
test('device-code sign-in uses fixed streaming route; IPC returns only a bounded public code',async()=>{
  const f=fixture({account:{...account,state:'pending',user_code:'DEMO-1234',flow_id:'b'.repeat(32),device_code:'secret-device',verification_url:'https://bad.invalid/'}});
  const result=await f.run(f.event,{action:'begin'});assert.equal(result.account.verification_url,'https://www.twitch.tv/activate');assert.equal(result.account.device_code,undefined);assert.equal(f.calls[0].url,origin+'/api/production/accounts/twitch/begin-streaming');
});

test('metadata upgrade has its own guarded route and public permission flag',async()=>{
  const f=fixture({account:{...account,metadata_authorized:true,state:'pending',authorization_kind:'metadata',user_code:'DEMO-1234',flow_id:'c'.repeat(32),access_token:'private'}});
  const result=await f.run(f.event,{action:'begin_metadata'});
  assert.equal(result.ok,true);assert.equal(result.account.metadata_authorized,true);assert.equal(result.account.authorization_kind,'metadata');
  assert.equal(f.calls[0].url,origin+'/api/production/accounts/twitch/begin-metadata');assert.equal(JSON.stringify(result).includes('private'),false);
  const blocked=fixture({mutate:async()=>{throw Error('destination_broadcast_busy');}});
  assert.equal((await blocked.run(blocked.event,{action:'begin_metadata'})).reason,'destination_broadcast_busy');assert.equal(blocked.calls.length,0);
});
test('stale settings navigation cannot finish a new destination link',async()=>{
  const f=fixture();const fetchImpl=async url=>{f.event.senderFrame.url='file:///changed';const r=new Response(JSON.stringify({account}),{headers:{'Content-Type':'application/json'}});Object.defineProperty(r,'url',{value:url});return r;};
  const g=fixture({fetchImpl,trustedSender:event=>event===f.event});assert.equal((await g.run(f.event,{action:'link',requestId:'one'})).reason,'local_operator_required');assert.equal(g.saved.length,0);
});
test('linked destination persists despite a separately reported audit failure',async()=>{
  const f=fixture({append:()=>{throw Error('private-path-secret');}}),result=await f.run(f.event,{action:'link',requestId:'one'});assert.equal(result.ok,true);assert.equal(result.activity_history_warning,true);assert.equal(JSON.stringify(result).includes('private-path'),false);
});
test('broadcast guard blocks changing connected accounts; check and cancel stay available',async()=>{
  const f=fixture({mutate:async()=>{throw Error('destination_broadcast_busy');}});
  for(const action of ['begin','link','disconnect'])assert.equal((await f.run(f.event,{action,requestId:'one'})).reason,'destination_broadcast_busy');
  for(const action of ['check','cancel'])assert.equal((await f.run(f.event,{action})).ok,true);
});
test('Cancel can supersede a delayed Begin without clearing newer pending work',async()=>{
  let release;const wait=new Promise(resolve=>{release=resolve;});const actions=[];
  const f=fixture({fetchImpl:async url=>{actions.push(url);if(url.endsWith('/begin-streaming'))await wait;const r=new Response(JSON.stringify({account}),{headers:{'Content-Type':'application/json'}});Object.defineProperty(r,'url',{value:url});return r;}});
  const beginning=f.run(f.event,{action:'begin'});
  assert.equal((await f.run(f.event,{action:'cancel'})).ok,true);
  release();await beginning;assert.equal(actions.length,2);assert.equal(actions[1].endsWith('/cancel'),true);
});
test('saved account validation explicitly checks existing authorization, but never opens consent or chat',async()=>{
  const f=fixture();assert.equal((await f.run.checkSaved()).ok,true);
  assert.deepEqual(f.calls.map(call=>call.url),[origin+'/api/production/accounts',origin+'/api/production/accounts/twitch/check']);assert.equal(f.saved.length,0);
  const empty=fixture({account:{...account,state:'not_authorized',authorized:false,streaming_authorized:false,reason:'authorization_required'}});await empty.run.checkSaved();assert.equal(empty.calls.length,1);
});
test('redirects, large bodies, wrong types and transport exceptions become constant failures',async()=>{
  for(const kind of ['redirect','large','type','throw']){
    const f=fixture({fetchImpl:async url=>{if(kind==='throw')throw Error('private token');const r=new Response(kind==='large'?' '.repeat(16385):JSON.stringify({account}),{headers:{'Content-Type':kind==='type'?'text/html':'application/json'}});Object.defineProperty(r,'url',{value:kind==='redirect'?'https://bad.invalid/':url});return r;}});
    assert.deepEqual(await f.run(f.event,{action:'check'}),{ok:false,reason:'account_unavailable'});
  }
});
function childFixture(answer,overrides={}){let invocation;
  const spawnImpl=(exe,args,options)=>{const child=new EventEmitter();Object.assign(child,{stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough(),kill:()=>{}});invocation={exe,args,options,child};setImmediate(()=>{child.stdout.write(answer);child.emit('close',0);});return child;};
  const runtime={python:path.resolve('python.exe'),projectRoot:path.resolve('project'),buildKind:'local-development-runtime',...overrides};
  return {resolve:createTwitchResolver({runtime,spawnImpl}),invocation:()=>invocation};
}
test('owned helper pipe returns a key privately, with no token or key in command arguments',async()=>{
  const f=childFixture(JSON.stringify({ok:true,accountRef:ref,streamKey:'synthetic-private-key',publicLabel:'channel'}));const value=await f.resolve(ref);assert.equal(value.streamKey,'synthetic-private-key');assert.equal(JSON.stringify(f.invocation().args).includes('synthetic-private-key'),false);assert.equal(f.invocation().options.windowsHide,true);
});
test('bundled helper uses the installed data profile instead of developer account configuration',async()=>{
  const dataRoot=path.resolve('installed-data'),f=childFixture(JSON.stringify({ok:true,accountRef:ref,streamKey:'synthetic-private-key'}),{buildKind:'bundled-runtime',dataRoot});
  await f.resolve(ref);const options=f.invocation().options;assert.equal(options.cwd,dataRoot);assert.equal(options.env.PRODUCER_DESKTOP,'1');assert.equal(options.env.PRODUCER_DESKTOP_DATA_ROOT,dataRoot);
  const dev=childFixture(JSON.stringify({ok:true,accountRef:ref,streamKey:'synthetic-private-key'}));await dev.resolve(ref);assert.equal(dev.invocation().options.env.PRODUCER_DESKTOP_DATA_ROOT,undefined);
});
test('helper errors, extra secret fields and wrong channel cannot cross the resolver contract',async()=>{
  for(const value of [{ok:false,reason:'provider_unavailable'},{ok:true,accountRef:'b'.repeat(64),streamKey:'wrong'},{ok:true,accountRef:ref,streamKey:'private',access_token:'must-not-pass'}]){
    const f=childFixture(JSON.stringify(value));await assert.rejects(f.resolve(ref),error=>['provider_unavailable','account_authorization_required'].includes(error.message));
  }
});
