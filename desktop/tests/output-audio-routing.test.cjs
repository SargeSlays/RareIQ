'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {normalizeSourceManifest,routeFor}=require('../audio-routing.cjs');
const origin='http://127.0.0.1:54321',mic='guest:'+'a'.repeat(32)+':microphone',screen='guest:'+'a'.repeat(32)+':screen_audio',video='video:12345678-1234-1234-1234-123456789abc';
function media(id,{volume=.5,sourceId='',src=''}={}){
  const listeners=new Map(),track={id,readyState:'live',stops:0,stop(){this.stops++;}};
  return {dataset:sourceId?{audioSource:sourceId}:{},src,currentSrc:src,srcObject:src?null:{getAudioTracks:()=>[track]},paused:false,ended:false,muted:false,volume,readyState:4,track,
    closest:()=>null,captureStream(){return {getAudioTracks:()=>[track]};},
    addEventListener(name,fn){listeners.set(name,fn);},removeEventListener(name){listeners.delete(name);},emit(name){listeners.get(name)?.();}};
}
async function fixture(groups){
  const controls=new Map(),events=new Map(),intervals=[],sent=[],sources=[],gains=[];let now=0,worklet;
  class Node{constructor(){this.connections=[];this.gain={value:0,setValueAtTime:value=>{this.gain.value=value;}};}connect(node,...ports){this.connections.push({node,ports});}disconnect(){this.connections=[];this.disconnected=true;}}
  class Context{constructor(){this.state='running';this.sampleRate=48000;this.currentTime=0;this.destination=new Node();this.audioWorklet={addModule:async()=>{}};}createGain(){const n=new Node();gains.push(n);return n;}createMediaStreamSource(stream){const n=new Node();n.track=stream.getAudioTracks()[0];sources.push(n);return n;}resume(){return Promise.resolve();}close(){this.state='closed';return Promise.resolve();}}
  const selectors={'program':['iframe.program','/program'],'soundboard':['iframe.audio','/output/soundboard'],'graphics':['iframe.graphics','/overlay/graphics'],'audience':['iframe.audience','/overlay/audience']},frames={};
  for(const [group,elements] of Object.entries(groups)){const [selector,pathname]=selectors[group];frames[selector]={contentWindow:{location:{origin,pathname}},contentDocument:{querySelectorAll:()=>elements}};}
  class Worklet extends Node{constructor(_c,_name,options){super();worklet=this;this.options=options;this.port={messages:[],postMessage:value=>this.port.messages.push(value)};}}
  const window={addEventListener:(name,fn)=>events.set(name,fn)};window.top=window;
  const context={require:name=>{assert.equal(name,'electron');return {ipcRenderer:{on:(name,fn)=>controls.set(name,fn),send:(channel,value)=>sent.push({channel,value}),invoke:async()=>({captureId:'run',epochUs:0})}};},
    process:{isMainFrame:true,argv:['--producer-output-origin='+origin]},window,location:{origin,pathname:'/output/studio'},document:{readyState:'loading',querySelector:selector=>frames[selector]},
    AudioContext:Context,AudioWorkletNode:Worklet,MediaStream:class{constructor(tracks){this.tracks=tracks;}getAudioTracks(){return this.tracks;}},MutationObserver:class{observe(){}disconnect(){}},
    URL:class extends URL{static createObjectURL(){return 'blob:synthetic';}static revokeObjectURL(){}},Blob:class{},setInterval:fn=>{intervals.push(fn);return intervals.length;},clearInterval(){},performance:{now:()=>now},console,ArrayBuffer,Uint8Array};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../output-preload.cjs'),'utf8'),context);await events.get('DOMContentLoaded')();
  return {sent,gains,sources,scan:intervals[0],health:intervals[1],controls,close:()=>events.get('pagehide')(),advance(ms){now+=ms;},meter(value){worklet.port.onmessage({data:{type:'meters',meters:value}});},route(value){controls.get('producer:output:control')(null,{type:'routing',audioRouting:value});},
    bus(element){const source=sources.findLast(s=>s.track===element.track&&!s.disconnected);return source.connections.map(c=>c.node.gain.value);}};
}
test('actual preload separates identified voice, screen, file and cue sources with saved overrides',async()=>{
  const voice=media('mic',{sourceId:mic,volume:.6}),share=media('screen',{sourceId:screen,volume:.4}),file=media('video',{sourceId:video,volume:.3}),cue=media('cue',{src:origin+'/api/creator/assets/clip_1',volume:.2});
  const f=await fixture({program:[voice,share,file],soundboard:[cue]});
  try{
    assert.deepEqual(f.bus(voice),[.6,.6]);assert.deepEqual(f.bus(share),[.4,0]);assert.deepEqual(f.bus(file),[.3,0]);assert.deepEqual(f.bus(cue),[.2,0]);
    f.health();const manifest=JSON.parse(JSON.stringify(f.sent.at(-1).value.sources));assert.equal(normalizeSourceManifest(manifest).length,4);
    const routes={[mic]:{live:false,vod:true},[video]:{live:false,vod:true},'soundboard:default':{live:false,vod:false}};
    f.route(routes);assert.deepEqual(f.bus(voice),[0,.6]);assert.deepEqual(f.bus(file),[0,.3]);assert.deepEqual(f.bus(cue),[0,0]);
    for(const item of manifest){const element=[voice,share,file,cue].find(e=>e.dataset.audioSource===item.id||item.id==='soundboard:clip_1'&&e===cue),route=routeFor(item,routes);assert.deepEqual(f.bus(element),[route.live?element.volume:0,route.vod?element.volume:0]);}
  }finally{f.close();}
  for(const element of [voice,share,file,cue])assert.equal(element.track.stops,0);
});
test('independent finite Live/VOD gains multiply volume while Program mute and source changes retain precedence',async()=>{
  const voice=media('mic',{sourceId:mic,volume:.2});const f=await fixture({program:[voice]});
  try{
    f.route({[mic]:{live:true,vod:true,liveGainDb:6.020599913279624,vodGainDb:-6.020599913279624}});
    const boosted=f.bus(voice);assert.ok(Math.abs(boosted[0]-.4)<1e-9);assert.ok(Math.abs(boosted[1]-.1)<1e-9);
    voice.muted=true;voice.emit('volumechange');assert.deepEqual(f.bus(voice),[0,0]);voice.muted=false;voice.emit('volumechange');
    voice.dataset.audioSource=screen;f.scan();assert.deepEqual(f.bus(voice),[.2,0]);
    f.route({[screen]:{live:true,vod:true,liveGainDb:12,vodGainDb:-60}});assert.ok(f.bus(voice)[0]>.79);assert.equal(f.bus(voice)[1],.0002);
    f.route({[screen]:{live:true,vod:true,liveGainDb:Infinity}});assert.equal(f.sent.at(-1).value.error,true);assert.ok(f.bus(voice)[0]>.79);
  }finally{f.close();}assert.equal(voice.track.stops,0);
});
test('meter health is scalar-only, available before capture, fresh for750ms and holds clipping2seconds',async()=>{
  const f=await fixture({program:[media('mic',{sourceId:mic})]});const level=(clipCount=0)=>({peak:1,rms:.5,clipCount});
  const report=()=>{f.health();return f.sent.at(-1).value.audioMeters;};
  try{
    assert.equal(report().available,false);
    f.meter({live:level(1),vod:level()});let meters=report();assert.equal(meters.available,true);assert.equal(meters.live.clipped,true);assert.equal(meters.vod.clipped,false);assert.equal(f.sent.at(-1).value.captureId,undefined);
    f.advance(1500);f.meter({live:level(),vod:level()});assert.equal(report().live.clipped,true);
    f.advance(501);f.meter({live:level(),vod:level()});assert.equal(report().live.clipped,false);
    f.advance(751);meters=report();assert.equal(meters.available,false);assert.equal(meters.live.peak,0);
    for(const invalid of [NaN,Infinity,-.1,1.1]){f.meter({live:{peak:invalid,rms:.1,clipCount:0},vod:level()});meters=report();assert.equal(meters.available,false);assert.equal(meters.live.rms,0);}
    f.meter({live:level(9601),vod:level()});assert.equal(report().available,false);
    f.meter({live:level(),vod:level()});assert.equal(report().available,true);assert.ok(!JSON.stringify(report()).includes('pcm'));
  }finally{f.close();}
});
test('Program mute and removal silence both mixes; replacement media uses its own default routing',async()=>{
  const voice=media('mic',{sourceId:mic}),cue=media('cue',{src:origin+'/api/creator/assets/one'}),elements=[voice];const f=await fixture({program:elements,soundboard:[cue]});
  try{
    f.route({[mic]:{live:true,vod:true}});voice.muted=true;voice.emit('volumechange');assert.deepEqual(f.bus(voice),[0,0]);
    voice.muted=false;voice.emit('volumechange');assert.deepEqual(f.bus(voice),[.5,.5]);
    voice.dataset.audioSource=screen;f.scan();assert.deepEqual(f.bus(voice),[.5,0]);
    elements.splice(0);f.scan();assert.equal(f.sources.find(s=>s.track===voice.track).disconnected,true);
    f.route({'soundboard:one':{live:false,vod:true}});assert.deepEqual(f.bus(cue),[0,.5]);cue.currentSrc=origin+'/api/creator/assets/two';f.scan();assert.deepEqual(f.bus(cue),[.5,0]);
    f.route({'soundboard:two':{live:true,vod:'yes'}});assert.equal(f.sent.at(-1).value.error,true);assert.deepEqual(f.bus(cue),[.5,0]);
  }finally{f.close();}assert.equal(voice.track.stops,0);assert.equal(cue.track.stops,0);
});
test('unidentified or forged voice metadata stays out of VOD and manifests contain no source URLs',async()=>{
  const unknown=media('unknown'),forged=media('forged',{sourceId:'https://private.invalid'});forged.dataset.audioCategory='voice';
  const f=await fixture({program:[unknown,forged],audience:[media('alert',{src:'https://outside.invalid/private'})]});
  try{assert.deepEqual(f.bus(unknown),[.5,0]);assert.deepEqual(f.bus(forged),[.5,0]);f.health();const manifest=JSON.parse(JSON.stringify(f.sent.at(-1).value.sources));assert.equal(normalizeSourceManifest(manifest).length,2);assert.ok(!JSON.stringify(manifest).includes('private'));}finally{f.close();}
});
