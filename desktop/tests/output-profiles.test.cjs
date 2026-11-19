'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {OutputProfileStore,normalizeProfile,MAX_PROFILES}=require('../output-profiles.cjs');
const {DEFAULT_AUDIO_ROUTING}=require('../audio-routing.cjs');
const root=path.resolve('F:/Temp/jonat/ProducerPlease-output-profile-tests');
async function fixture(t,options={}){await fs.mkdir(root,{recursive:true});const directory=await fs.mkdtemp(path.join(root,'profile-'));t.after(async()=>{assert.equal(path.dirname(path.resolve(directory)),root);await fs.rm(directory,{recursive:true,force:true});});return {directory,file:path.join(directory,'output-profiles.json'),store:new OutputProfileStore({directory,...options})};}
const payload=extra=>({requestId:'first',name:'My show',format:'hd',fps:30,videoBitrateKbps:4000,codec:'auto',keyframeSeconds:2,audioBitrateKbps:192,twitchVod:false,audioRouting:DEFAULT_AUDIO_ROUTING,...extra});
const rejects=(promise,code)=>assert.rejects(promise,error=>error.code===code&&error.message===code);

test('three default profiles preserve existing formats and separate voices in the optional VOD mix',async t=>{
  const {store}=await fixture(t),state=await store.public();assert.equal(state.profiles.length,3);assert.equal(state.selectedProfileId,'hd-balanced');assert.deepEqual(state.profiles.map(item=>item.format),['hd','fullhd','portrait']);const hd=await store.getProfile();assert.equal(hd.twitchVod,false);assert.equal(hd.fps,30);assert.equal(hd.audioRouting['voice:default'].vod,true);assert.equal(hd.audioRouting['video:default'].vod,false);assert.equal(hd.audioRouting['soundboard:default'].vod,false);
});

test('validation rejects unknown fields, secret-shaped payloads and out-of-bound encoding settings before persistence',async t=>{
  const {store,file}=await fixture(t);for(const extra of [{streamKey:'private'},{password:'private'},{clientSecret:'private'},{destinationIds:['one']},{requestId:undefined},{id:123}])await rejects(store.save(payload(extra)),'invalid_output_profile_fields');
  for(const extra of [{fps:24},{fps:120},{fps:null},{videoBitrateKbps:249},{videoBitrateKbps:40001},{codec:'arbitrary-codec'},{format:'4k'},{keyframeSeconds:0},{keyframeSeconds:11},{audioBitrateKbps:63},{audioBitrateKbps:321},{twitchVod:'yes'},{twitchVod:null}])await rejects(store.save(payload(extra)),'invalid_output_profile_settings');assert.equal(await fs.stat(file).then(()=>true,()=>false),false);
  assert.throws(()=>normalizeProfile({name:'Name',audioRouting:{'https://private.example':{live:true,vod:false}}}),error=>error.code==='invalid_output_profile_audio_routing');
});

test('save, selection and audio routing survive reload without mutating caller or returned snapshots',async t=>{
  const {store,directory}=await fixture(t),input=payload({fps:60,videoBitrateKbps:12000,codec:'libx264',keyframeSeconds:3,audioBitrateKbps:320,twitchVod:true,audioRouting:{'voice:default':{live:true,vod:true},'video:default':{live:true,vod:false}}}),saved=await store.save(input);assert.equal(saved.profiles.length,4);input.audioRouting['voice:default'].vod=false;saved.profiles.find(item=>item.id===saved.savedProfileId).name='Outside mutation';
  const reloaded=new OutputProfileStore({directory}),profile=await reloaded.getProfile(saved.savedProfileId);assert.equal(profile.name,'My show');assert.equal(profile.audioRouting['voice:default'].vod,true);assert.equal(profile.fps,60);assert.equal(profile.twitchVod,true);assert.equal((await reloaded.public()).selectedProfileId,saved.savedProfileId);await reloaded.select('portrait-hd');assert.equal((await new OutputProfileStore({directory}).public()).selectedProfileId,'portrait-hd');
});

test('retry receipts prevent duplicate profile creation and reject changed or retired requests',async t=>{
  const {store}=await fixture(t),first=await store.save(payload()),retry=await store.save(payload());assert.equal(retry.replayed,true);assert.equal(retry.savedProfileId,first.savedProfileId);assert.equal(retry.profiles.length,4);await rejects(store.save(payload({name:'Changed retry'})),'output_profile_request_conflict');await store.remove(first.savedProfileId);await rejects(store.save(payload()),'output_profile_request_retired');
});

test('concurrent save and selection are serialized and snapshots preserve independent profile IDs',async t=>{
  const {store}=await fixture(t),[first,second]=await Promise.all([store.save(payload({requestId:'one'})),store.save(payload({requestId:'two'}))]);assert.notEqual(first.savedProfileId,second.savedProfileId);assert.equal((await store.public()).profiles.length,5);await store.select(first.savedProfileId);assert.equal((await store.getProfile()).id,first.savedProfileId);
});

test('failed atomic replacement preserves the previous file and in-memory selection',async t=>{
  let failRename=false;const fileSystem={...fs,rename:async(...args)=>{if(failRename)throw Error('private filesystem detail');return fs.rename(...args);}},f=await fixture(t,{fileSystem});await f.store.save(payload());const before=await fs.readFile(f.file,'utf8'),selected=(await f.store.public()).selectedProfileId;failRename=true;await rejects(f.store.select('portrait-hd'),'output_profile_storage_unavailable');assert.equal(await fs.readFile(f.file,'utf8'),before);assert.equal((await f.store.public()).selectedProfileId,selected);assert.equal((await fs.readdir(f.directory)).some(name=>name.endsWith('.tmp')),false);
});

test('bounded library retains at least one profile and selects a safe replacement when removing the selected one',async t=>{
  const {store}=await fixture(t);for(let i=3;i<MAX_PROFILES;i++)await store.save(payload({requestId:'profile-'+i,name:'Profile '+i}));await rejects(store.save(payload({requestId:'overflow'})),'output_profile_library_full');let state=await store.public();while(state.profiles.length>1)state=await store.remove(state.selectedProfileId);assert.equal(state.profiles.length,1);assert.equal(state.selectedProfileId,state.profiles[0].id);await rejects(store.remove(state.selectedProfileId),'output_profile_required');
});

test('malformed persisted profile data is reported safely and never silently overwritten',async t=>{
  const {directory,file}=await fixture(t),raw=JSON.stringify({version:99,profiles:[],privateDetail:'never exposed'});await fs.writeFile(file,raw,'utf8');const store=new OutputProfileStore({directory});await rejects(store.public(),'output_profile_storage_invalid');await rejects(store.save(payload()),'output_profile_storage_invalid');assert.equal(await fs.readFile(file,'utf8'),raw);
});
