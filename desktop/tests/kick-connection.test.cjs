'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{EventEmitter}=require('node:events'),{PassThrough}=require('node:stream');
const {createKickResolver}=require('../kick-connection.cjs');
const ref='a'.repeat(64),valid={ok:true,platform:'kick',accountRef:ref,serverUrl:'rtmps://ingest.provider.com/app',streamKey:'synthetic-private-kick-key'};
function fixture(answer=valid,options={}){
  let invocation,input='',killed=0;
  const spawnImpl=(exe,args,settings)=>{if(options.spawnThrows)throw Error('private spawn details');const child=new EventEmitter();Object.assign(child,{stdin:new PassThrough(),stdout:new PassThrough(),stderr:new PassThrough(),kill:()=>{killed++;}});child.stdin.on('data',chunk=>{input+=chunk.toString('utf8');});invocation={exe,args,settings,child};if(!options.pending)setImmediate(()=>{if(options.errorEvent){child.emit('error',Error('private child details'));return;}const output=Buffer.isBuffer(answer)?answer:typeof answer==='string'?answer:JSON.stringify(answer);if(options.split){const middle=Math.floor(output.length/2);child.stdout.write(output.subarray?output.subarray(0,middle):output.slice(0,middle));child.stdout.write(output.subarray?output.subarray(middle):output.slice(middle));}else child.stdout.write(output);child.stderr.write('private-token-do-not-log');child.emit('close',options.exitCode??0);});return child;};
  const runtime={python:path.resolve('python.exe'),projectRoot:path.resolve('private-project'),buildKind:'local-development-runtime',...options.runtime};
  return {resolve:createKickResolver({runtime,spawnImpl}),invocation:()=>invocation,input:()=>input,killed:()=>killed};
}
test('Kick helper receives only the account reference on stdin and returns private validated transport settings',async()=>{
  const f=fixture(valid,{split:true}),value=await f.resolve(ref),invocation=f.invocation();assert.deepEqual(value,{platform:'kick',accountRef:ref,serverUrl:valid.serverUrl,streamKey:valid.streamKey});assert.deepEqual(JSON.parse(f.input()),{accountRef:ref});assert.equal(invocation.settings.windowsHide,true);assert.deepEqual(invocation.settings.stdio,['pipe','pipe','pipe']);assert.equal(path.basename(invocation.args[1]),'desktop_kick_account.py');
  for(const secret of [ref,valid.serverUrl,valid.streamKey])assert.equal(JSON.stringify(invocation.args).includes(secret),false);assert.equal(f.killed(),0);
});
test('bundled Kick helper is pinned to installed account storage and developer mode removes an inherited data root',async t=>{
  const before=process.env.PRODUCER_DESKTOP_DATA_ROOT;process.env.PRODUCER_DESKTOP_DATA_ROOT=path.resolve('wrong-inherited-data');t.after(()=>{if(before===undefined)delete process.env.PRODUCER_DESKTOP_DATA_ROOT;else process.env.PRODUCER_DESKTOP_DATA_ROOT=before;});
  const dataRoot=path.resolve('installed-data'),bundled=fixture(valid,{runtime:{buildKind:'bundled-runtime',dataRoot}});await bundled.resolve(ref);assert.equal(bundled.invocation().settings.cwd,dataRoot);assert.equal(bundled.invocation().settings.env.PRODUCER_DESKTOP,'1');assert.equal(bundled.invocation().settings.env.PRODUCER_DESKTOP_DATA_ROOT,dataRoot);
  const dev=fixture();await dev.resolve(ref);assert.equal(dev.invocation().settings.env.PRODUCER_DESKTOP_DATA_ROOT,undefined);assert.equal(dev.invocation().settings.cwd,path.resolve('private-project'));
});
test('invalid inputs and profile locations cannot start a helper',async()=>{
  for(const runtime of [{python:undefined},{projectRoot:undefined},{python:'relative.exe'},{projectRoot:'relative'},{buildKind:'bundled-runtime',dataRoot:'relative'}]){const f=fixture(valid,{runtime});await assert.rejects(f.resolve(ref),{message:'account_unavailable'});assert.equal(f.invocation(),undefined);}
  for(const accountRef of ['',null,42,{},'a'.repeat(63),'A'.repeat(64)]){const f=fixture();await assert.rejects(f.resolve(accountRef),{message:'account_unavailable'});assert.equal(f.invocation(),undefined);}
});
test('Kick success accepts only the pinned provider/reference and exact private response fields',async()=>{
  for(const change of [{platform:'twitch'},{platform:undefined},{accountRef:'b'.repeat(64)},{streamKey:''},{streamKey:'a\nb'},{streamKey:'a'.repeat(4097)},{access_token:'private-token'},{refresh_token:'private-refresh'},{publicLabel:'extra'}]){const f=fixture({...valid,...change});await assert.rejects(f.resolve(ref),{message:'account_authorization_required'});assert.equal(f.killed(),1);}
});
test('API RTMP endpoints, credentials, query strings and nonpublic hosts fail without guessing secure support',async()=>{
  for(const serverUrl of ['rtmp://ingest.provider.com/app','https://ingest.provider.com/app','rtmps://127.0.0.1/app','rtmps://machine.local/app','rtmps://name:key@ingest.provider.com/app','rtmps://ingest.provider.com/app?secret=1','rtmps://ingest.provider.com/app#secret']){const f=fixture({...valid,serverUrl});await assert.rejects(f.resolve(ref),{message:'streaming_not_available'});}
});
test('helper diagnostics and errors become fixed reasons and malformed, oversized or invalid UTF8 replies are bounded',async()=>{
  for(const [answer,options,reason] of [[{ok:false,reason:'provider_unavailable'}, {},'provider_unavailable'],[{ok:false,reason:'private-account-and-token'}, {},'account_authorization_required'],[valid,{exitCode:1},'account_authorization_required'],['{bad-json',{},'account_unavailable'],['x'.repeat(16385),{},'account_unavailable'],[Buffer.from([0xc3,0x28]),{},'account_unavailable'],[valid,{spawnThrows:true},'account_unavailable'],[valid,{errorEvent:true},'account_unavailable']]){const f=fixture(answer,options);await assert.rejects(f.resolve(ref),{message:reason});}
});
test('a stalled Kick helper is terminated after the bounded timeout and late secret output cannot settle it again',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});const f=fixture(valid,{pending:true}),pending=f.resolve(ref);t.mock.timers.tick(22001);await assert.rejects(pending,{message:'provider_unavailable'});assert.equal(f.killed(),1);f.invocation().child.stdout.write(JSON.stringify(valid));f.invocation().child.emit('close',0);assert.equal(f.killed(),1);
});
test('a pipe error terminates the owned helper and never forwards its diagnostic',async()=>{
  const f=fixture(valid,{pending:true}),pending=f.resolve(ref);f.invocation().child.stdin.emit('error',Error('private pipe data'));await assert.rejects(pending,{message:'account_unavailable'});assert.equal(f.killed(),1);
});


test('known missing secure ingest failure stays actionable and contains no private provider payload',async()=>{
  const f=fixture({ok:false,reason:'secure_ingest_unavailable',streamKey:'must-never-leave-helper'});await assert.rejects(f.resolve(ref),{message:'secure_ingest_unavailable'});
});
