const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/guest.js'),'utf8');
const settle=async()=>{for(let index=0;index<20;index++)await Promise.resolve();};
function fixture(options={}){
  const elements=new Map(),handlers=new Map(),publications=[];let resolveCapture,publisherOptions,captureCalls=0;
  const element=id=>{if(!elements.has(id))elements.set(id,{value:id==='guestName'?'Fixture guest':'',hidden:false,disabled:false,srcObject:null,textContent:'',attributes:{},listeners:{},classList:{toggle(){},remove(){}},setAttribute(name,value){this.attributes[name]=value;},getAttribute(name){return this.attributes[name];},addEventListener(name,handler){this.listeners[name]=handler;},pause(){},play:async()=>{},replaceChildren(){},add(){}});return elements.get(id);};
  const capture=()=>new Promise(resolve=>{captureCalls++;resolveCapture=resolve;});
  const context={document:{getElementById:element},location:{hash:'#invite='+'b'.repeat(64),pathname:'/guest'},history:{replaceState(){}},URLSearchParams,crypto:require('node:crypto').webcrypto,sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},isSecureContext:true,navigator:{mediaDevices:{getUserMedia:capture,getDisplayMedia:capture,enumerateDevices:async()=>[]}},fetch:async()=>({ok:true}),addEventListener:(name,callback)=>handlers.set(name,callback),ProducerGuestMedia:{createPublisher(options){publisherOptions=options;return {setTracks:tracks=>publications.push(tracks),close(){},connect(){options.onState({participant:{id:'a'.repeat(32),name:'Fixture guest',state:'waiting'},on_air_sources:[]});}}}}};
  Object.assign(context,options);context.window=context;vm.runInNewContext(source,context);
  return {element,handlers,publications,callbacks:()=>publisherOptions,captureCalls:()=>captureCalls,resolve:tracks=>resolveCapture({getTracks:()=>tracks,getVideoTracks:()=>tracks.filter(track=>track.kind==='video'),getAudioTracks:()=>tracks.filter(track=>track.kind==='audio')})};
}
for(const mode of ['camera','microphone','screen'])for(const ending of ['leave','pagehide'])test(`Late ${mode} permission result after ${ending} stops all new tracks and never republishes`,async()=>{
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  const button=mode==='camera'?'guestCamera':mode==='microphone'?'guestMicrophone':'guestScreen';f.element(button).listeners.click();await settle();
  if(ending==='leave')await f.element('guestLeave').listeners.click();else f.handlers.get('pagehide')();
  const before=f.publications.length,tracks=(mode==='screen'?['video','audio']:[mode==='camera'?'video':'audio']).map(kind=>({kind,stops:0,stop(){this.stops++;}}));
  f.resolve(tracks);await settle();assert.ok(tracks.every(track=>track.stops===1));assert.equal(f.publications.length,before);
  assert.equal(f.element('guestCameraPreview').srcObject,null);assert.equal(f.element('guestScreenPreview').srcObject,null);
  assert.equal(f.element('guestCamera').disabled,true);assert.equal(f.element('guestMicrophone').disabled,true);
});

const roomState=(state,program_audio)=>({participant:{id:'a'.repeat(32),name:'Private name <script>',state,program_audio},on_air_sources:[]});
for(const state of ['waiting','admitted'])test(`Program mute notice in ${state} is informational only and clears on unmute`,async()=>{
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  const before=f.publications.length,notice=f.element('guestProgramAudioNotice');
  for(const [microphone_muted,screen_muted,sources] of [[true,false,'microphone'],[false,true,'shared-screen audio'],[true,true,'microphone and shared-screen audio']]){
    f.callbacks().onState(roomState(state,{microphone_muted,screen_muted}));
    assert.equal(notice.hidden,false);
    assert.equal(notice.textContent,`The producer has muted your ${sources} for Program. Backstage audio is unaffected.`);
    assert.equal(f.publications.length,before);assert.equal(f.captureCalls(),0);
    assert.equal(f.element('guestMicrophone').attributes['aria-pressed'],'false');
    assert.equal(f.element('guestScreen').attributes['aria-pressed'],'false');
  }
  for(const flags of [{microphone_muted:false,screen_muted:false},undefined,{microphone_muted:'true',screen_muted:1}]){
    f.callbacks().onState(roomState(state,flags));assert.equal(notice.hidden,true);assert.equal(notice.textContent,'');
  }
});

for(const ending of ['leave','pagehide','disconnected','reconnecting','failed','closed','error','removed','missing'])test(`Program mute notice clears after ${ending}`,async()=>{
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  const update=roomState('admitted',{microphone_muted:true,screen_muted:true});
  f.callbacks().onState(update);assert.equal(f.element('guestProgramAudioNotice').hidden,false);
  if(ending==='leave')await f.element('guestLeave').listeners.click();
  else if(ending==='pagehide')f.handlers.get('pagehide')();
  else if(ending==='error')f.callbacks().onError();
  else if(ending==='removed')f.callbacks().onState(roomState('removed',update.participant.program_audio));
  else if(ending==='missing')f.callbacks().onState({});
  else f.callbacks().onConnection({state:ending});
  if(['leave','pagehide'].includes(ending))f.callbacks().onState(update); // Ignore an obsolete late push.
  assert.equal(f.element('guestProgramAudioNotice').hidden,true);
  assert.equal(f.element('guestProgramAudioNotice').textContent,'');assert.equal(f.captureCalls(),0);
});

test('Guest notice is an accessible hidden status and the changed script has a new cache key',()=>{
  const html=fs.readFileSync(require.resolve('../../rareiq/web/static/guest.html'),'utf8');
  assert.match(html,/<p[^>]*id="guestProgramAudioNotice"[^>]*role="status"[^>]*aria-live="polite"[^>]*hidden/);
  assert.match(html,/guest\/assets\/guest\.js\?v=20261115-5/);
});


test('guest publishes gated microphone, replaces devices and leaves without stale processing',async()=>{
  const owners=[],processed={kind:'audio',stop(){}};
  const f=fixture({ProducerGuestMicrophone:{create(raw,onTrack,onStatus){const owner={closed:0,configure(){onTrack(processed);onStatus('Open · voice passing');},close(){this.closed++;raw.stop();}};owners.push(owner);return owner;}}});
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  f.element('guestMicrophone').listeners.click();const raw={kind:'audio',stops:0,stop(){this.stops++;}};f.resolve([raw]);await settle();
  assert.equal(f.publications.at(-1).microphone,processed);assert.equal(f.element('guestGateStatus').textContent,'Open · voice passing');
  f.element('guestMicDevice').listeners.change();const replacement={kind:'audio',stops:0,stop(){this.stops++;}};f.resolve([replacement]);await settle();assert.equal(owners[0].closed,1);assert.equal(raw.stops,1);
  const before=f.publications.length;await f.element('guestLeave').listeners.click();assert.equal(owners[1].closed,1);assert.equal(replacement.stops,1);assert.equal(f.publications.length,before);assert.equal(f.element('guestMicrophone').attributes['aria-pressed'],'false');
});


test('enabling the microphone gate after camera capture publishes the processed microphone',async()=>{
  const raw={kind:'audio',stop(){}},camera={kind:'video',stop(){}},processed={kind:'audio',stop(){}};
  const f=fixture({MediaStream:class{constructor(tracks){this.tracks=tracks;}getVideoTracks(){return this.tracks.filter(t=>t.kind==='video');}},ProducerGuestMicrophone:{create(input,onTrack,onStatus){return {configure(settings){if(settings.enabled){onTrack(processed);onStatus('Open · voice passing');}},close(){input.stop();}};}}});
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  f.element('guestMicrophone').listeners.click();f.resolve([raw]);await settle();assert.equal(f.publications.at(-1).microphone,raw);
  f.element('guestCamera').listeners.click();f.resolve([camera]);await settle();assert.equal(f.publications.at(-1).camera,camera);
  f.element('guestNoiseGate').listeners.click();await settle();assert.equal(f.publications.at(-1).microphone,processed);assert.equal(f.publications.at(-1).camera,camera);
  assert.equal(f.element('guestGateStatus').textContent,'Open · voice passing');await f.element('guestLeave').listeners.click();
});


test('enabled guest gate finishes processing setup before the first microphone publication',async()=>{
  let complete;const processed={kind:'audio',stop(){}};
  const f=fixture({localStorage:{getItem:()=>JSON.stringify({enabled:true,thresholdDb:-45}),setItem(){}},ProducerGuestMicrophone:{create(raw,onTrack){return {configure(){return new Promise(resolve=>{complete=()=>{onTrack(processed);resolve();};});},close(){raw.stop();}};}}});
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();const before=f.publications.length;
  f.element('guestMicrophone').listeners.click();f.resolve([{kind:'audio',stop(){}}]);await settle();assert.equal(f.publications.length,before);
  complete();await settle();assert.ok(f.publications.length>before);assert.ok(f.publications.slice(before).every(tracks=>tracks.microphone===processed));await f.element('guestLeave').listeners.click();
});


test('guest connection failures expose only safe known reasons and preserve them through close',async()=>{
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  for(const [reason,expected] of [['production_state_stalled','Updates from the production PC stopped'],['media_connection_failed','audio/video connection failed'],['media_negotiation_failed','could not agree'],['guest_access_ended','invitation is no longer active']]){
    f.callbacks().onError({reason});f.callbacks().onConnection({state:'disconnected',reason});assert.ok(f.element('guestStatus').textContent.includes(expected));
    f.callbacks().onConnection({state:'closed'});assert.ok(f.element('guestStatus').textContent.includes(expected));
    f.callbacks().onConnection({state:'connected'});
  }
  f.callbacks().onConnection({state:'disconnected',reason:'private-token-and-sdp'});assert.ok(!f.element('guestStatus').textContent.includes('private-token-and-sdp'));assert.ok(!f.element('guestStatus').textContent.includes('invitation is no longer active'));
});


test('every media-engine failure has a safe diagnostic without exposing signaling payloads',async()=>{
  const engine=fs.readFileSync(require.resolve('../../rareiq/web/static/greenroom_media.js'),'utf8');
  const reasons=new Set([...engine.matchAll(/fail\('([^']+)'/g)].map(match=>match[1]));
  for(const reason of ['guest_access_ended','signaling_disconnected'])reasons.add(reason);
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  for(const reason of reasons){f.callbacks().onConnection({state:'connected'});f.callbacks().onConnection({state:'disconnected',reason});assert.equal(f.element('guestBadge').attributes['data-connection-reason'],reason,reason);assert.ok(!f.element('guestStatus').textContent.includes(reason));}
});

test('partial media failures persist through room refreshes without claiming whole-room disconnection',async()=>{
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});
  f.callbacks().onConnection({scope:'peer',peer_id:'one',state:'peer_reconnecting'});
  assert.equal(f.element('guestPeerNotice').hidden,false);assert.match(f.element('guestPeerNotice').textContent,/reconnecting/);
  f.callbacks().onState(roomState('admitted',{}));assert.equal(f.element('guestBadge').textContent,'BACKSTAGE');assert.equal(f.element('guestPeerNotice').hidden,false);
  f.callbacks().onConnection({scope:'peer',peer_id:'two',state:'connected'});assert.equal(f.element('guestPeerNotice').hidden,false);
  f.callbacks().onConnection({scope:'peer',peer_id:'one',state:'peer_failed'});assert.match(f.element('guestPeerNotice').textContent,/could not recover/);
  f.callbacks().onConnection({scope:'peer',peer_id:'one',state:'peer_removed'});assert.equal(f.element('guestPeerNotice').hidden,true);
  f.callbacks().onConnection({scope:'peer',peer_id:'two',state:'peer_failed'});await f.element('guestLeave').listeners.click();assert.equal(f.element('guestPeerNotice').hidden,true);
});

test('guest sound pads require an active microphone and are stopped with its owner',async()=>{
  let plays=0,stops=0,closes=0,stateCallback;
  const f=fixture({ProducerGuestMicrophone:{create(raw,onTrack,onStatus,onState){stateCallback=onState;return {configure:async()=>{},snapshot:()=>({sounds:[],playing:plays>stops}),playCue:async cue=>{assert.equal(cue,'chime');plays++;onState({sounds:[],playing:true});},stopSounds(){stops=plays;},close(){closes++;raw.stop();}};}}});
  assert.equal(f.element('guestCueChime').disabled,true);await f.element('guestCueChime').listeners.click();assert.equal(plays,0);
  f.element('guestMicrophone').listeners.click();f.resolve([{kind:'audio',stop(){}}]);await settle();assert.equal(f.element('guestCueChime').disabled,false);
  await f.element('guestCueChime').listeners.click();assert.equal(plays,1);assert.equal(f.element('guestSoundsStop').disabled,false);
  f.element('guestSoundsStop').listeners.click();assert.equal(stops,1);assert.equal(f.element('guestSoundsStop').disabled,true);
  await f.element('guestMicrophone').listeners.click();assert.equal(closes,1);assert.equal(f.element('guestCueChime').disabled,true);
  stateCallback({sounds:[],playing:true});assert.equal(f.element('guestSoundsStop').disabled,true,'late old-owner state cannot revive sounds');
});

test('rapid voice changes preserve newest settings without new capture or changing the gate',async()=>{
  const settings=[];const f=fixture({ProducerGuestMicrophone:{create(){return {configure(value){settings.push(value);return Promise.resolve();},snapshot:()=>({sounds:[],playing:false}),close(){}};}}});
  f.element('guestMicrophone').listeners.click();f.resolve([{kind:'audio',stop(){}}]);await settle();
  f.element('guestVoicePreset').value='robot';f.element('guestVoicePreset').listeners.change();f.element('guestVoicePreset').value='radio';f.element('guestVoicePreset').listeners.change();await settle();
  assert.equal(settings.at(-1).preset,'radio');assert.equal(settings.at(-1).enabled,false);assert.equal(f.captureCalls(),1);
});

test('processing fallback never claims the requested voice effect applied',async()=>{
  const f=fixture({ProducerGuestMicrophone:{create(){return {configure:async()=>{},snapshot:()=>({sounds:[],playing:false,error:'audio_unavailable',appliedPreset:'natural'}),close(){}};}}});
  f.element('guestMicrophone').listeners.click();f.resolve([{kind:'audio',stop(){}}]);await settle();f.element('guestVoicePreset').value='robot';f.element('guestVoicePreset').listeners.change();await settle();
  assert.match(f.element('guestAudioStatus').textContent,/could not start/);assert.doesNotMatch(f.element('guestAudioStatus').textContent,/applied/);
});

for(const ending of ['leave','replacement','pagehide'])test(`late room audio rejection cannot revive a retired ${ending} stream`,async()=>{
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});let reject;
  f.element('guestReturnAudio').play=()=>new Promise((_,no)=>{reject=no;});f.callbacks().onReturnAudio({});
  if(ending==='leave')await f.element('guestLeave').listeners.click();else if(ending==='replacement')f.callbacks().onReturnAudio(null);else f.handlers.get('pagehide')();
  reject(Error('blocked'));await settle();assert.equal(f.element('guestRoomAudio').hidden,true);
});
