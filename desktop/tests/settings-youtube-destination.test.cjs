'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createController,selection}=require('../settings-youtube-destination.js');
const selected=(extra={})=>({account_ref:'a'.repeat(64),broadcast_id:'broadcast-one',stream_id:'stream-one',settings_fingerprint:'b'.repeat(64),privacy_status:'public',auto_start:true,auto_stop:false,title:'Synthetic broadcast',...extra});
const account=(extra={})=>({account:{state:'authorized',authorized:true,streaming_authorized:true,account_ref:'a'.repeat(64)},...extra});
function fixture(){const f={calls:[],states:[],busy:[],saved:0,result:null};let serial=0;f.controller=createController({request:async value=>{f.calls.push(value);return typeof f.result==='function'?f.result():f.result;},onChange:value=>f.states.push(value),onBusy:value=>f.busy.push(value),onSaved:async()=>{f.saved++;},randomId:()=>`synthetic-save-${++serial}`});f.controller.setAccount(account());return f;}
async function reviewed(f){f.result={ok:true,platform:'youtube',account_ref:'a'.repeat(64),broadcasts:[selected()]};assert.equal(await f.controller.run('list'),true);f.result={ok:true,selection:selected()};assert.equal(await f.controller.run('inspect'),true);}
const deferred=()=>{let resolve;return {promise:new Promise(r=>{resolve=r;}),resolve:value=>resolve(value)};};
test('selection exposes bounded public review fields only, with explicit auto-start settings',()=>{
 assert.deepEqual(selection({...selected(),streamKey:'secret',serverUrl:'private'}),selected());
 for(const extra of [{privacy_status:undefined},{privacy_status:'unknown'},{auto_start:undefined},{auto_stop:'false'},{settings_fingerprint:'bad'},{broadcast_id:'x/y'},{title:'unsafe\ntext'},{account_ref:'A'.repeat(64)}])assert.throws(()=>selection(selected(extra)));
});
test('read, review and save use exact IDs and fingerprint without a key or implicit Start',async()=>{
 const f=fixture();await reviewed(f);f.result={ok:true};assert.equal(await f.controller.run('link'),true);assert.deepEqual(f.calls,[{action:'list'},{action:'inspect',broadcastId:'broadcast-one'},{action:'link',broadcastId:'broadcast-one',expectedFingerprint:'b'.repeat(64),requestId:'synthetic-save-1'}]);assert.equal(f.saved,1);assert.match(f.controller.snapshot().message,/destination saved/);assert.doesNotMatch(JSON.stringify(f.controller.snapshot()),/streamKey|serverUrl/);
});
test('an ambiguous save keeps an exact retry and prevents choosing a different broadcast',async()=>{
 const f=fixture();await reviewed(f);f.result=()=>{throw Error('private upstream payload');};assert.equal(await f.controller.run('link'),false);const original=f.calls.at(-1);assert.equal(f.controller.choose('broadcast-one'),false);assert.equal(await f.controller.run('list'),false);f.controller.setAccount(account({stale:true}));assert.equal(f.controller.snapshot().retry,true);assert.equal(await f.controller.run('link'),false);f.controller.setAccount(account());f.result={ok:true};assert.equal(await f.controller.run('link'),true);assert.deepEqual(f.calls.at(-1),original);assert.equal(f.controller.snapshot().retry,false);assert.doesNotMatch(JSON.stringify(f.states),/private upstream/);
});
test('definitive binding or request changes require a new review and retire the old save receipt',async()=>{
 for(const reason of ['destination_request_conflict','destination_request_retired','selection_changed','youtube_selection_changed','account_state_changed','secure_ingest_unavailable','streaming_not_available','authorization_rejected','account_identity_mismatch','streaming_scope_required','broadcast_selection_limit']){const f=fixture();await reviewed(f);f.result={ok:false,reason};await f.controller.run('link');assert.equal(f.controller.snapshot().retry,false);assert.equal(f.controller.snapshot().review,null);assert.equal(await f.controller.run('link'),false);await reviewed(f);f.result={ok:true};await f.controller.run('link');assert.equal(f.calls.at(-1).requestId,'synthetic-save-2');}
});
test('account replacement and closing retire stale asynchronous list/review/save replies',async()=>{
 for(const close of [false,true]){const f=fixture();await reviewed(f);const pending=deferred();f.result=()=>pending.promise;const work=f.controller.run('link');assert.equal(await f.controller.run('link'),false);if(close)f.controller.close();else f.controller.setAccount({account:{...account().account,account_ref:'c'.repeat(64)}});const before=f.states.length;pending.resolve({ok:true});assert.equal(await work,false);assert.equal(f.saved,0);assert.equal(f.states.length,before);}
});
test('missing authorization, locks, mismatched accounts and malformed lists fail closed',async()=>{
 const f=fixture();f.controller.setAccount({account:{state:'not_authorized',authorized:false}});assert.equal(await f.controller.run('list'),false);f.controller.setAccount(account());f.controller.setLocked(true);assert.equal(await f.controller.run('list'),false);f.controller.setLocked(false);
 for(const value of [{ok:true,platform:'youtube',account_ref:'c'.repeat(64),broadcasts:[selected()]},{ok:true,platform:'youtube',account_ref:'a'.repeat(64),broadcasts:[selected(),selected()]},{ok:true,platform:'youtube',account_ref:'a'.repeat(64),broadcasts:[selected({auto_start:null})]}]){f.result=value;assert.equal(await f.controller.run('list'),false);assert.equal(f.controller.snapshot().review,null);}
});
test('empty broadcasts explain preparation outside the app without manufacturing a selection',async()=>{
 const f=fixture();f.result={ok:true,platform:'youtube',account_ref:'a'.repeat(64),broadcasts:[]};assert.equal(await f.controller.run('list'),true);assert.match(f.controller.snapshot().message,/No eligible broadcasts/);assert.equal(await f.controller.run('inspect'),false);assert.equal(await f.controller.run('link'),false);
});
test('a failed second review removes earlier permission to save that selection',async()=>{
 const f=fixture();await reviewed(f);f.result={ok:false,reason:'broadcast_selection_changed'};assert.equal(await f.controller.run('inspect'),false);assert.equal(f.controller.snapshot().review,null);assert.equal(await f.controller.run('link'),false);
});
