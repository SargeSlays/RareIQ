const test=require('node:test');
const assert=require('node:assert/strict');
const {createModel}=require('../../rareiq/web/static/studio_voice_rules.js');
const rule={phrase:'close up',action_id:'program.take',params:{preview_slot:2}};
test('custom settings load and save never arm voice or dispatch an action',async()=>{
  const calls=[];
  const model=createModel(async(path,options)=>{calls.push({path,options});return {ok:true,revision:options.method?1:0,rules:options.method?[rule]:[],editable:true};});
  await model.load();await model.save([rule]);
  assert.equal(calls.length,2);assert.ok(calls.every(call=>call.path==='/api/production/voice/rules'));
  assert.deepEqual(JSON.parse(calls[1].options.body),{expected_revision:0,rules:[rule]});
  const snapshot=model.state();snapshot.rules[0].phrase='changed outside';assert.equal(model.state().rules[0].phrase,'close up');
});
test('conflicting save keeps the original revision for explicit reload',async()=>{
  let requests=0;
  const model=createModel(async(path,options)=>{requests++;if(options.method){const error=Error('conflict');error.payload={reason:'voice_rules_revision_conflict'};throw error;}return {ok:true,revision:3,rules:[rule],editable:true};});
  await model.load();await assert.rejects(model.save([{...rule,phrase:'wide shot'}]));
  assert.equal(model.state().revision,3);assert.deepEqual(model.state().rules,[rule]);assert.equal(model.state().busy,false);
  assert.equal(requests,2);
});
test('disarmed state and pending saves guard repeated clicks',async()=>{
  const locked=createModel(async()=>({ok:true,revision:0,rules:[],editable:false}));
  await locked.load();await assert.rejects(locked.save([rule]),/not_editable/);
  let complete;
  const model=createModel(async(path,options)=>options.method?new Promise(resolve=>complete=resolve):{ok:true,revision:0,rules:[],editable:true});
  await model.load();const pending=model.save([rule]);await assert.rejects(model.save([rule]),/not_editable/);
  await assert.rejects(model.load(),/busy/);complete({ok:true,revision:1,rules:[rule]});await pending;
});
