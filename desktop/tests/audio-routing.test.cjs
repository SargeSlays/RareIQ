'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {DEFAULT_AUDIO_ROUTING,validSourceId,categoryForSource,normalizeAudioRouting,normalizeSourceManifest,routeFor}=require('../audio-routing.cjs');
const mic='guest:'+'a'.repeat(32)+':microphone',screen='guest:'+'a'.repeat(32)+':screen_audio',video='video:12345678-1234-1234-1234-123456789abc';
test('defaults keep voices in both mixes while music-capable sources stay live only',()=>{
  for(const id of [mic,screen,video,'program:default','soundboard:clip_1','graphics:clip_1','audience:clip_1']){
    assert.equal(validSourceId(id),true);assert.deepEqual(routeFor(id),{live:true,vod:id===mic});
  }
  assert.equal(Object.keys(DEFAULT_AUDIO_ROUTING).length,7);
});
test('exact source overrides win over category defaults; sparse profiles are copied',()=>{
  const saved={...DEFAULT_AUDIO_ROUTING,'voice:default':{live:false,vod:false},[mic]:{live:true,vod:true},[video]:{live:false,vod:true}};
  assert.deepEqual(routeFor(mic,saved),{live:true,vod:true});assert.deepEqual(routeFor(video,saved),{live:false,vod:true});
  assert.deepEqual(routeFor(screen,{'program:default':{live:false,vod:true}}),{live:false,vod:true});
  const copy=normalizeAudioRouting(saved);copy[mic].vod=false;assert.equal(saved[mic].vod,true);
});
test('saved routes reject unknown fields, private URLs, invalid booleans and unbounded maps',()=>{
  for(const value of [null,[],{'https://private.invalid':{live:true,vod:true}}, {[mic]:{live:true,vod:1}}, {[mic]:{live:true,vod:false,token:'private'}},Object.fromEntries(Array.from({length:129},(_,i)=>['soundboard:clip'+i,{live:true,vod:false}]))])assert.throws(()=>normalizeAudioRouting(value),/invalid_audio_routing/);
  for(const id of ['__proto__','guest:person:microphone','camera-device-id','video:not-a-uuid','unknown:default'])assert.equal(validSourceId(id),false);
});
test('manifest reports fixed public labels and never accepts identities or arbitrary labels',()=>{
  const result=normalizeSourceManifest([{id:mic,category:'voice'},{id:mic,category:'voice'}]);
  assert.deepEqual(result,[{id:mic,category:'voice',label:'Guest microphone'}]);assert.equal(categoryForSource(screen),'screen');
  for(const value of [[{id:mic,category:'screen'}],[{id:mic,category:'voice',label:'Private name'}],[{id:mic,category:'voice',deviceId:'private'}],Array(65).fill({id:mic,category:'voice'})])assert.throws(()=>normalizeSourceManifest(value),/invalid_audio_routing/);
});
