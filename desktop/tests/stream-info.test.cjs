'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const {StreamInfoStore,createStreamInfoActions}=require('../stream-info.cjs');
async function fixture(t){const directory=await fs.mkdtemp(path.join(process.env.TEMP||os.tmpdir(),'producer-stream-info-'));t.after(()=>fs.rm(directory,{recursive:true,force:true}));return {directory,store:new StreamInfoStore({directory})};}
const draft=(extra={})=>({requestId:'save-1',revision:0,shared:{title:'A fixture show',description:'First line\nSecond line'},overrides:{},...extra});
test('saved shared details and explicit empty destination overrides survive reopening',async t=>{
  const id='11111111-1111-4111-8111-111111111111', {directory,store}=await fixture(t),payload=draft({overrides:{[id]:{title:'',description:'',category:'Game notes',tags:'friendly, English'}}});
  const result=await store.save(payload);assert.equal(result.revision,1);assert.equal(result.overrides[id].title,'');assert.equal(result.shared.title,payload.shared.title);
  const reopened=await new StreamInfoStore({directory}).public();assert.deepEqual(reopened,{revision:result.revision,shared:result.shared,overrides:result.overrides});
  reopened.shared.title='Mutated externally';assert.equal((await store.public()).shared.title,payload.shared.title);
});
test('exact retries persist once; conflicting and stale requests preserve current details',async t=>{
  const {store}=await fixture(t),payload=draft();await store.save(payload);assert.equal((await store.save(payload)).replayed,true);
  await assert.rejects(store.save({...payload,shared:{...payload.shared,title:'Changed'}}),/request_conflict/);
  await assert.rejects(store.save(draft({requestId:'stale'})),/revision_conflict/);
  await store.save(draft({requestId:'save-2',revision:1,shared:{title:'New draft',description:''}}));await assert.rejects(store.save(payload),/revision_conflict/);assert.equal((await store.public()).shared.title,'New draft');
});
test('bounded fields, unknown keys, control characters and unsafe IDs are rejected',async t=>{
  const {store}=await fixture(t);
  for(const payload of [draft({unexpected:true}),draft({revision:NaN}),draft({shared:{title:'x'.repeat(101),description:''}}),draft({shared:{title:'bad\nline',description:''}}),draft({shared:{title:'title',description:'\x00'}}),draft({overrides:JSON.parse('{"__proto__":{"title":"","description":"","category":"","tags":""}}')}),draft({overrides:{id:{title:'t',description:'d',category:'c',tags:[]}}})])await assert.rejects(store.save(payload),/invalid_stream_info/);
  assert.equal((await store.public()).revision,0);
});
test('atomic write failure preserves prior disk state and supports explicit retry',async t=>{
  const {directory,store}=await fixture(t);await store.save(draft());let fail=true;
  const unstable=new StreamInfoStore({directory,fileSystem:{...fs,rename:async(...args)=>{if(fail)throw Error('fixture disk failure');return fs.rename(...args);}}}),payload=draft({requestId:'save-2',revision:1});
  await assert.rejects(unstable.save(payload),/storage_unavailable/);assert.equal((await new StreamInfoStore({directory}).public()).revision,1);fail=false;assert.equal((await unstable.save(payload)).revision,2);
});
test('concurrent same-revision saves cannot silently overwrite each other',async t=>{
  const {store}=await fixture(t),results=await Promise.allSettled([store.save(draft()),store.save(draft({requestId:'save-2'}))]);assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.equal((await store.public()).revision,1);
});

test('multi-byte draft size cannot produce a saved file that fails its own load bound',async t=>{
  const {store}=await fixture(t),overrides={};for(let i=0;i<50;i++)overrides[i.toString(16).padStart(8,'0')+'-1111-4111-8111-111111111111']={title:'',description:'\u754c'.repeat(5000),category:'',tags:''};await assert.rejects(store.save(draft({overrides})),/invalid_stream_info/);assert.equal((await store.public()).revision,0);
});
test('invalid saved storage fails closed without replacing it',async t=>{
  const {directory,store}=await fixture(t);await fs.writeFile(path.join(directory,'stream-info.json'),'{broken');await assert.rejects(store.public(),/storage_invalid/);await assert.rejects(store.save(draft()),/storage_invalid/);assert.equal(await fs.readFile(path.join(directory,'stream-info.json'),'utf8'),'{broken');
});
test('trusted actions use mutation guard and log only metadata; history failure is separate',async t=>{
  const {store}=await fixture(t),events=[],trusted={},actions=createStreamInfoActions({store,trustedSender:e=>e===trusted,mutate:async(e,fn)=>{events.push('guard');return fn();},append:entry=>{events.push(entry);throw Error('history unavailable');}});
  await assert.rejects(actions.list({}),/local_operator_required/);await assert.rejects(actions.save({},draft()),/local_operator_required/);assert.deepEqual(events,[]);
  const result=await actions.save(trusted,draft());assert.equal(result.activity_history_warning,true);assert.equal(events[0],'guard');assert.equal(JSON.stringify(events).includes('fixture show'),false);assert.equal(events[1].revision,1);assert.equal((await actions.list(trusted)).revision,1);
});
