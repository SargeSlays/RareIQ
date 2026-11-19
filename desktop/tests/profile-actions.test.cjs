'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{createProfileActions}=require('../profile-actions.cjs');
test('profile history records the local actor and version without source/credential content',async()=>{
  const rows=[],result={savedProfileId:'hd-balanced',replayed:false,profiles:[{id:'hd-balanced',updatedAt:123,name:'private title',audioRouting:{'private-source':{liveGainDb:12}}}]};
  const actions=createProfileActions({store:{save:async()=>result,select:async()=>result,remove:async()=>result},append:row=>rows.push(row),clock:()=> 'fixed'});
  assert.equal(await actions.save({streamKey:'never-log'}),result);await actions.select('hd-balanced');await actions.remove('hd-balanced');
  assert.equal(rows.length,3);assert.equal(rows[0].profileId,'hd-balanced');assert.equal(rows[0].updatedAt,123);assert.equal(rows[0].identityVerified,false);assert.doesNotMatch(JSON.stringify(rows),/private|never-log|streamKey|liveGainDb/);
});
test('history failure is a warning after a successful save, while store failure remains a failure',async()=>{
  const result={savedProfileId:'saved',profiles:[],replayed:true};let failStore=false;
  const actions=createProfileActions({store:{save:async()=>{if(failStore)throw Error('store unavailable');return result;}},append:()=>{throw Error('private disk detail');}});
  const receipt=await actions.save({});assert.equal(receipt.savedProfileId,'saved');assert.equal(receipt.replayed,true);assert.equal(receipt.activity_history_warning,true);assert.doesNotMatch(JSON.stringify(receipt),/disk detail/);
  failStore=true;await assert.rejects(actions.save({}),/store unavailable/);
});
