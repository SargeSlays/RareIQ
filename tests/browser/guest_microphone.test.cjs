const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/guest_microphone.js'),'utf8');
const dspSource=fs.readFileSync(require.resolve('../../rareiq/web/static/guest_audio_dsp.js'),'utf8');
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function fixture({deferred=false,unavailable=false,channels,decode}={}){
  let resolve;const raw={stops:0,getSettings:()=>({channelCount:channels}),stop(){this.stops++;}},processed={stops:0,stop(){this.stops++;}},states=[],tracks=[],contexts=[],settings=[],snapshots=[],nodes=[];
  const ready=deferred?new Promise(r=>resolve=r):Promise.resolve();
  function node(kind){const value={kind,connections:new Set(),starts:0,stops:0,connect(to){this.connections.add(to);},disconnect(to){if(to)this.connections.delete(to);else this.connections.clear();},start(){this.starts++;},stop(){this.stops++;}};for(const key of ['gain','frequency','Q','threshold','ratio','knee','attack','release'])value[key]={value:0};nodes.push(value);return value;}
  const makeBuffer=(channels=1,length=48000,rate=48000)=>({length,numberOfChannels:channels,duration:length/rate,getChannelData:()=>new Float32Array(length)});
  const host={MediaStream:class{constructor(tracks){this.tracks=tracks;}},StudioNoiseGate:{create(context,input,output,status,options){assert.match(options.workletUrl,/^\/guest\/assets\/studio_noise_gate.worklet.js/);input.connect(output);return {async configure(value){settings.push({...value});status(value.enabled?'Closed · quiet input muted':'Off');},close(){}};}}};
  if(!unavailable)host.AudioContext=class{constructor(){this.state='suspended';this.closed=0;this.sampleRate=48000;this.destination=node('speakers');contexts.push(this);}async resume(){await ready;this.state='running';}close(){this.closed++;this.state='closed';return Promise.resolve();}createMediaStreamSource(){return node('microphone');}createMediaStreamDestination(){this.output={...node('output'),channelCount:2,stream:{getTracks:()=>[processed],getAudioTracks:()=>[processed]}};return this.output;}createGain(){return node('gain');}createDynamicsCompressor(){return node('compressor');}createBiquadFilter(){return node('filter');}createWaveShaper(){return node('shaper');}createOscillator(){return node('oscillator');}createBufferSource(){return node('buffer');}createBuffer(...args){return makeBuffer(...args);}decodeAudioData(bytes){return decode?decode(bytes):Promise.resolve(makeBuffer());}};
  vm.runInNewContext(dspSource,{window:host});vm.runInNewContext(source,{window:host});return {raw,processed,states,tracks,contexts,settings,snapshots,nodes,resolve,makeBuffer,host,controller:host.ProducerGuestMicrophone.create(raw,t=>tracks.push(t),s=>states.push(s),s=>snapshots.push(s))};
}
test('guest gate is opt-in, publishes processed track, clamps threshold and closes owned resources',async()=>{
  const f=fixture();await f.controller.configure({enabled:false});assert.equal(f.contexts.length,0);assert.equal(f.tracks.length,0);
  await f.controller.configure({enabled:true,thresholdDb:-100});assert.equal(f.tracks.at(-1),f.processed);assert.equal(f.settings.at(-1).thresholdDb,-70);
  await f.controller.configure({enabled:false,thresholdDb:-25});assert.equal(f.states.at(-1),'Off');assert.equal(f.contexts.length,1);
  f.controller.close();f.controller.close();assert.equal(f.raw.stops,1);assert.equal(f.processed.stops,1);assert.equal(f.contexts[0].closed,1);
});
test('late audio initialization after leave cannot publish or reopen resources',async()=>{
  const f=fixture({deferred:true}),pending=f.controller.configure({enabled:true});f.controller.close();f.resolve();await pending;
  assert.equal(f.tracks.length,0);assert.equal(f.raw.stops,1);assert.equal(f.contexts[0].closed,1);
});
test('disabling while starting preserves bypass and unavailable processing explicitly publishes raw',async()=>{
  const f=fixture({deferred:true}),pending=f.controller.configure({enabled:true});await f.controller.configure({enabled:false});f.resolve();await pending;
  assert.equal(f.settings.at(-1).enabled,false);assert.equal(f.states.at(-1),'Off');f.controller.close();
  const missing=fixture({unavailable:true});await missing.controller.configure({enabled:true});assert.equal(missing.tracks.at(-1),missing.raw);assert.equal(missing.states.at(-1),'Unavailable · audio unfiltered');missing.controller.close();
});

for(const channels of [1,2,undefined,6])test(`processed microphone preserves supported input channel count (${channels})`,async()=>{
  const f=fixture({channels});await f.controller.configure({enabled:true});assert.equal(f.contexts[0].output.channelCount,channels===2?2:1);f.controller.close();
});

const file=(overrides={})=>({size:100,type:'audio/wav',name:'My cue.wav',arrayBuffer:async()=>new ArrayBuffer(100),...overrides});
test('preset changes share one outgoing track, latest settings win, and robot resources retire',async()=>{
  const f=fixture({deferred:true});assert.equal(f.snapshots.length,0,'create is callback-free');
  const starting=f.controller.configure({preset:'robot',enabled:true});
  await f.controller.configure({preset:'natural',enabled:false,soundVolume:.2});f.resolve();await starting;
  assert.equal(f.controller.snapshot().appliedPreset,'natural');assert.equal(f.settings.at(-1).enabled,false);
  for(const preset of ['deep','radio','robot','megaphone','natural'])await f.controller.configure({preset});
  assert.equal(f.contexts.length,1);assert.equal(f.tracks.length,1);assert.equal(f.tracks[0],f.processed);
  assert.equal(f.nodes.find(n=>n.kind==='oscillator').stops,1);assert.equal(f.raw.stops,0);
  assert.ok(f.nodes.every(n=>!n.connections.has(f.contexts[0].destination)),'no implicit speaker monitor');f.controller.close();
});

test('cues mix downstream of voice/gate and Stop All cancels concurrent or pending playback',async()=>{
  const f=fixture();await f.controller.configure({enabled:true,preset:'radio',soundVolume:.4});
  await Promise.all(['chime','success','buzzer','drumroll'].map(id=>f.controller.playCue(id)));
  assert.equal(f.controller.snapshot().playing,4);await assert.rejects(f.controller.playCue('chime'),/sound_playback_limit/);
  const players=f.nodes.filter(n=>n.kind==='buffer'),bus=[...players[0].connections][0];assert.equal(bus.gain.value,.4);
  assert.equal([...bus.connections][0].kind,'gain');assert.ok(players.every(p=>p.connections.has(bus)));
  await f.controller.configure({soundVolume:2});assert.equal(bus.gain.value,1);
  f.controller.stopSounds();assert.equal(f.controller.snapshot().playing,0);assert.ok(players.every(n=>n.stops===1&&n.connections.size===0));
  assert.equal(f.processed.stops,0,'stopping cues keeps microphone connected');f.controller.close();
  const pending=fixture({deferred:true}),play=pending.controller.playCue('chime');pending.controller.stopSounds();pending.resolve();await assert.rejects(play,/sound_cancelled/);assert.equal(pending.nodes.filter(n=>n.kind==='buffer').length,0);pending.controller.close();
});

test('cue end releases its node and reports idle without stopping microphone',async()=>{
  const f=fixture();await f.controller.playCue('buzzer');const player=f.nodes.find(n=>n.kind==='buffer');player.onended();
  assert.equal(f.controller.snapshot().playing,0);assert.equal(f.snapshots.at(-1).playing,0);assert.equal(player.connections.size,0);assert.equal(f.raw.stops,0);f.controller.close();
});

test('local files remain private buffers, use six slots, and removal stops only that sound',async()=>{
  const f=fixture();const first=await f.controller.addSound(file({name:'../<img src=x>.wav'}));assert.equal(first.label,'<img src=x>.wav');
  for(let i=1;i<6;i++)await f.controller.addSound(file());await assert.rejects(f.controller.addSound(file()),/sound_slot_limit/);
  await f.controller.playSound(first.id);await f.controller.playCue('chime');f.controller.removeSound(first.id);assert.equal(f.controller.snapshot().playing,1);assert.equal(f.controller.snapshot().sounds.length,5);
  await assert.rejects(f.controller.playSound(first.id),/unknown_sound/);f.controller.close();assert.equal(f.controller.snapshot().sounds.length,0);assert.equal(f.processed.stops,1);
});

test('malformed, oversized and unsupported local files are rejected before decoding',async()=>{
  let decodes=0;const f=fixture({decode:()=>{decodes++;throw Error('should not decode');}});
  for(const size of [0,-1,1.5,NaN,Infinity,10*1024*1024+1])await assert.rejects(f.controller.addSound(file({size})),/sound_file_too_large/);
  for(const type of ['text/html','image/png','', 'audio/wav; executable=true'])await assert.rejects(f.controller.addSound(file({type})),/sound_file_type/);
  await assert.rejects(f.controller.addSound(file({arrayBuffer:null})),/sound_file_type/);
  await assert.rejects(f.controller.addSound(file({arrayBuffer:async()=>new ArrayBuffer(10*1024*1024+1)})),/sound_file_too_large/);
  await assert.rejects(f.controller.addSound(file({arrayBuffer:async()=>({byteLength:100})})),/sound_file_too_large/);
  await assert.rejects(f.controller.addSound(file({arrayBuffer:async()=>{throw Error('private filesystem path');}})),/^Error: sound_read_failed$/);
  assert.equal(decodes,0);f.controller.close();
});

test('decoded duration, channel and memory limits are enforced, with recoverable decode errors',async()=>{
  for(const buffer of [{duration:30.01,length:1440480,numberOfChannels:1},{duration:NaN,length:2,numberOfChannels:1},{duration:1,length:48000,numberOfChannels:6},{duration:30,length:18000000,numberOfChannels:1}]){
    const f=fixture({decode:async()=>buffer});await assert.rejects(f.controller.addSound(file()),/sound_(duration|memory)_limit/);assert.equal(f.controller.snapshot().sounds.length,0);assert.equal(f.controller.snapshot().loading,false);f.controller.close();
  }
  const f=fixture({decode:async()=>{throw Error('private decoder details');}});await assert.rejects(f.controller.addSound(file()),/^Error: sound_decode_failed$/);f.controller.close();
});

test('only one local decode runs and close during decode cannot retain files or publish again',async()=>{
  let complete;const f=fixture({decode:()=>new Promise(r=>complete=r)}),loading=f.controller.addSound(file());await settle();
  assert.equal(f.controller.snapshot().loading,true);await assert.rejects(f.controller.addSound(file()),/sound_import_busy/);
  const trackCount=f.tracks.length;f.controller.close();complete(f.makeBuffer());await assert.rejects(loading,/audio_closed/);
  assert.equal(f.tracks.length,trackCount);assert.equal(f.controller.snapshot().sounds.length,0);assert.equal(f.processed.stops,1);assert.equal(f.raw.stops,1);
});

test('close while reading a file or resuming a cue cannot restart the owner',async()=>{
  let read;const f=fixture(),loading=f.controller.addSound(file({arrayBuffer:()=>new Promise(r=>read=r)}));await settle();f.controller.close();read(new ArrayBuffer(100));await assert.rejects(loading,/audio_closed/);
  const p=fixture({deferred:true}),play=p.controller.playCue('success');p.controller.close();p.resolve();await assert.rejects(play,/audio_closed/);assert.equal(p.tracks.length,0);assert.equal(p.nodes.filter(n=>n.kind==='buffer').length,0);
});

test('all original cue buffers are bounded, finite, non-silent and reject arbitrary names',()=>{
  const dsp=require('../../rareiq/web/static/guest_audio_dsp.js');
  const context={sampleRate:48000,createBuffer(channels,length,rate){const samples=new Float32Array(length);return {duration:length/rate,getChannelData:()=>samples};}};
  for(const {id} of dsp.cues){const buffer=dsp.cueBuffer(context,id),samples=buffer.getChannelData(0);assert.ok(buffer.duration<=1.3);assert.ok(samples.every(Number.isFinite));assert.ok(samples.some(v=>Math.abs(v)>.1));assert.ok(samples.every(v=>Math.abs(v)<.5));}
  assert.throws(()=>dsp.cueBuffer(context,'https://external.invalid/audio'),/unknown_sound/);
});

test('suspended processing resumes from the action and unavailable presets report truthful fallback',async()=>{
  const f=fixture();await f.controller.configure({preset:'radio'});const context=f.contexts[0];context.state='suspended';
  let inside=false,resumedInside=false;context.resume=()=>{resumedInside=inside;context.state='running';return Promise.resolve();};
  inside=true;const updating=f.controller.configure({preset:'deep'});inside=false;await updating;
  assert.equal(resumedInside,true);assert.equal(f.controller.snapshot().appliedPreset,'deep');
  context.state='suspended';context.resume=()=>{throw Error('private device details');};
  await assert.rejects(f.controller.playCue('chime'),/^Error: audio_unavailable$/);
  const fallback=await f.controller.configure({preset:'robot'});assert.equal(fallback.error,'audio_unavailable');assert.equal(fallback.available,false);assert.equal(fallback.appliedPreset,'natural');assert.equal(f.tracks.at(-1),f.raw);f.controller.close();
});

test('rapid established-graph settings retain the final preset, gate and sound volume',async()=>{
  const f=fixture();await f.controller.configure({preset:'deep'});
  await Promise.all([f.controller.configure({preset:'robot',enabled:true,soundVolume:.9}),f.controller.configure({preset:'radio',thresholdDb:-30}),f.controller.configure({preset:'natural',enabled:false,soundVolume:0})]);
  assert.equal(f.controller.snapshot().appliedPreset,'natural');assert.equal(f.controller.snapshot().soundVolume,0);assert.equal(f.settings.at(-1).enabled,false);assert.equal(f.settings.at(-1).thresholdDb,-30);assert.equal(f.tracks.length,1);f.controller.close();
});
