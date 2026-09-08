const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studio_voice_control.js'),'utf8');
const workletSource=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studio_voice_capture.worklet.js'),'utf8');
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve()};
function fixture(handler){
  const nodes=new Map(),requests=[],worklets=[],connections=[],timers=new Map();let next=0;
  for(const id of ['studioVoiceStart','studioVoiceStop','studioVoicePractice','studioVoiceStatus','studioVoiceOutcome','studioVoiceControls'])nodes.set(id,{disabled:false,checked:false,dataset:{},textContent:'',addEventListener(){}});
  class Worklet {constructor(){this.port={postMessage:value=>this.commands.push(value),close:()=>{this.closed=true},onmessage:null};this.commands=[];worklets.push(this)}connect(target){connections.push([this,target])}disconnect(){this.disconnected=true}}
  const raw={connect:target=>connections.push([raw,target]),disconnect:target=>connections.push(['disconnect',target])};
  const sink={gain:{value:1},connect(){},disconnect(){this.disconnected=true}};
  const input={active:true,source:raw,inputStream:{getAudioTracks:()=>[{readyState:'live',stop(){throw Error('Must not stop microphone')}}]},context:{state:'running',currentTime:20,destination:{},audioWorklet:{addModule:async()=>{}},createGain:()=>sink}};
  const host={document:{getElementById:id=>nodes.get(id)},location:{hostname:'127.0.0.1'},AudioWorkletNode:Worklet,AbortController,setTimeout:fn=>{timers.set(++next,fn);return next},clearTimeout:id=>timers.delete(id),addEventListener(){}};
  const sandbox={window:host,ArrayBuffer,URLSearchParams,Date,WeakMap,Number,String};vm.runInNewContext(source,sandbox);
  const request=async(url,options={})=>{requests.push({url,options});if(handler)return handler(url,options);return url.endsWith('/start')?{ok:true,state:'armed',session_id:'session-1',practice:true}:{ok:true,state:'armed',last_result:{state:'validated',message:'Practice accepted; no action.'}}};
  const app=host.StudioVoiceControlFactory.create({borrow:()=>input,request});
  return {app,host,input,nodes,requests,worklets,connections,timers,sink};
}
test('requires active existing local input and defaults to Practice without auto-arming',async()=>{
  const f=fixture();assert.equal(f.nodes.get('studioVoicePractice').checked,true);assert.equal(f.requests.length,0);
  f.input.active=false;await f.app.start();assert.equal(f.requests.length,0);assert.equal(f.nodes.get('studioVoiceStart').disabled,true);
  f.input.active=true;f.host.location.hostname='192.168.1.2';await f.app.start();assert.equal(f.requests.length,0);
});
test('borrows raw source with silent sink and stops only owned connections',async()=>{
  const f=fixture();await f.app.start();assert.equal(f.worklets.length,1);assert.equal(f.sink.gain.value,0);assert.equal(f.connections[0][0],f.input.source);
  assert.equal(JSON.parse(f.requests[0].options.body).practice,true);await f.app.stop();assert.equal(f.input.active,true);assert.equal(f.input.context.state,'running');assert.equal(f.worklets[0].closed,true);assert.equal(f.connections.find(c=>c[0]==='disconnect')[1],f.worklets[0]);
});
test('cancelling asynchronous preparation cannot start a stale host session',async()=>{
  const f=fixture();let resolve;f.input.context.audioWorklet.addModule=()=>new Promise(r=>resolve=r);
  const first=f.app.start();await f.app.stop();resolve();await first;assert.equal(f.requests.length,0);assert.equal(f.worklets.length,0);
});
test('one utterance request, timestamp from audio clock, and stop ignores late results',async()=>{
  let resolve;
  const f=fixture((url)=>url.endsWith('/start')?{ok:true,state:'armed',session_id:'x',practice:true}:url.includes('/audio?')?new Promise(r=>resolve=r):{ok:true,state:'stopped'});
  await f.app.start();const port=f.worklets[0].port,handler=port.onmessage,utterance={data:{type:'utterance',wav:new ArrayBuffer(100),endedContextTime:18}};
  handler(utterance);handler(utterance);await settle();const sent=f.requests.filter(r=>r.url.includes('/audio?'));assert.equal(sent.length,1);
  const query=new URL(sent[0].url,'http://localhost').searchParams;assert.ok(Number(query.get('ended_at'))<Date.now()/1000-1.5);assert.equal(query.get('sequence'),'1');assert.equal(sent[0].options.headers['Content-Type'],'audio/wav');assert.equal(sent[0].options.retries,0);
  await f.app.stop();resolve({ok:true,state:'armed',last_result:{message:'Late result must stay hidden'}});await settle();assert.equal(f.nodes.get('studioVoiceOutcome').textContent,'');assert.equal(f.app.status().state,'stopped');
});
test('host stop via heartbeat disconnects borrowed branch without a new stop action',async()=>{
  const f=fixture(url=>url.endsWith('/start')?{ok:true,state:'armed',session_id:'owned',practice:true}:{ok:true,state:'stopped'});
  await f.app.start();f.worklets[0].port.onmessage({data:{type:'heartbeat'}});await settle();assert.equal(f.app.status().state,'stopped');assert.ok(f.requests.some(r=>r.url.includes('/status?session_id=owned')));assert.equal(f.requests.some(r=>r.url.endsWith('/stop')),false);
});
test('a still-recognizing response pauses capture until the owned status returns armed',async()=>{
  const f=fixture(url=>url.endsWith('/start')?{ok:true,state:'armed',session_id:'owned',practice:true}:url.includes('/audio?')?{ok:true,state:'recognizing'}:{ok:true,state:'armed',last_result:{state:'validated',message:'Practice only'}});
  await f.app.start();const worklet=f.worklets[0];worklet.port.onmessage({data:{type:'utterance',wav:new ArrayBuffer(100),endedContextTime:19}});await settle();assert.equal(f.app.status().busy,true);assert.equal(worklet.commands.filter(c=>c.value===true).length,1);
  worklet.port.onmessage({data:{type:'heartbeat'}});await settle();assert.equal(f.app.status().busy,false);assert.equal(worklet.commands.filter(c=>c.value===true).length,2);
});
function processor(rate=48000){
  let Class;const messages=[];const sandbox={sampleRate:rate,currentTime:0,AudioWorkletProcessor:class{constructor(){this.port={postMessage:data=>messages.push(data)}}},registerProcessor:(name,value)=>{Class=value},Float32Array,ArrayBuffer,DataView,Math};vm.runInNewContext(workletSource,sandbox);const node=new Class();node.port.onmessage({data:{type:'enabled',value:true}});
  function feed(seconds,amplitude=.1){for(let i=0;i<Math.ceil(seconds*rate/128);i++){const block=new Float32Array(128).fill(amplitude),output=new Float32Array(128).fill(.5);node.process([[block]],[[output]]);assert.equal(output.some(v=>v!==0),false);sandbox.currentTime+=128/rate;}}
  return {node,messages,feed};
}
test('worklet emits bounded 16k mono PCM16 WAV after speech and silence, never audio output',()=>{
  const f=processor(44100);f.feed(.3,0);f.feed(.7);f.feed(.6,0);const clips=f.messages.filter(m=>m.type==='utterance');assert.equal(clips.length,1);const view=new DataView(clips[0].wav);assert.equal(view.getUint32(24,true),16000);assert.equal(view.getUint16(22,true),1);assert.equal(view.getUint16(34,true),16);assert.ok(view.byteLength<=192044);assert.ok(clips[0].endedContextTime<1.1);f.feed(2);assert.equal(f.messages.filter(m=>m.type==='utterance').length,1);
});
test('worklet caps continuous utterances at six seconds and ignores silence',()=>{
  const silent=processor();silent.feed(7,0);assert.equal(silent.messages.some(m=>m.type==='utterance'),false);
  const f=processor();f.feed(7);const clips=f.messages.filter(m=>m.type==='utterance');assert.equal(clips.length,1);assert.equal(clips[0].wav.byteLength,192044);assert.ok(f.messages.some(m=>m.type==='heartbeat'));
});
