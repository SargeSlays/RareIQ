const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/guest.js'),'utf8');
const settle=async()=>{for(let index=0;index<20;index++)await Promise.resolve();};
function fixture(options={}){
  const elements=new Map(),handlers=new Map(),publications=[];let resolveCapture,rejectCapture,publisherOptions,captureCalls=0,doc;
  const node=(id='')=>({id,value:id==='guestName'?'Fixture guest':'',children:[],hidden:false,disabled:false,isConnected:true,srcObject:null,textContent:'',attributes:{},listeners:{},classList:{toggle(){},remove(){}},setAttribute(name,value){this.attributes[name]=value;},getAttribute(name){return this.attributes[name];},addEventListener(name,handler){this.listeners[name]=handler;},pause(){},play:async()=>{},append(...nodes){for(const item of nodes){item.parentNode=this;this.children.push(item);}},replaceChildren(...nodes){this.children=[];this.append(...nodes);},add(value){this.children.push(value);},contains(target){return this===target||this.children.some(child=>child.contains?.(target));},remove(){if(this.contains(doc.activeElement))doc.activeElement=doc.body;this.isConnected=false;if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(child=>child!==this);},focus(){doc.activeElement=this;}});
  const element=id=>{if(!elements.has(id))elements.set(id,node(id));return elements.get(id);};
  doc={getElementById:element,createElement:tag=>node(tag),activeElement:null,body:node('body')};
  const capture=()=>new Promise((resolve,reject)=>{captureCalls++;resolveCapture=resolve;rejectCapture=reject;});
  const context={document:doc,Option:class{constructor(label,value){this.textContent=label;this.value=value;}},location:{hash:'#invite='+'b'.repeat(64),pathname:'/guest'},history:{replaceState(){}},URLSearchParams,crypto:require('node:crypto').webcrypto,sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},isSecureContext:true,navigator:{mediaDevices:{getUserMedia:capture,getDisplayMedia:capture,enumerateDevices:async()=>[]}},fetch:async()=>({ok:true}),addEventListener:(name,callback)=>handlers.set(name,callback),ProducerGuestMedia:{createPublisher(options){publisherOptions=options;return {setTracks:tracks=>publications.push(tracks),close(){},connect(){options.onState({participant:{id:'a'.repeat(32),name:'Fixture guest',state:'waiting'},on_air_sources:[]});}}}}};
  Object.assign(context,options);context.window=context;vm.runInNewContext(source,context);
  return {element,handlers,publications,context,callbacks:()=>publisherOptions,captureCalls:()=>captureCalls,reject:error=>rejectCapture(error),resolve:tracks=>resolveCapture({getTracks:()=>tracks,getVideoTracks:()=>tracks.filter(track=>track.kind==='video'),getAudioTracks:()=>tracks.filter(track=>track.kind==='audio')})};
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
  assert.match(html,/guest\/assets\/guest\.js\?v=20261115-9/);
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
  for(const [reason,expected] of [['production_state_stalled','Updates from the production PC stopped'],['media_connection_failed','audio/video connection failed'],['media_negotiation_failed','could not agree'],['guest_access_ended','invitation is no longer active']]){
    const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
    f.callbacks().onError({reason});f.callbacks().onConnection({state:'disconnected',reason});assert.ok(f.element('guestConnectionStatus').textContent.includes(expected));
    assert.notEqual(f.element('guestStatus').textContent,f.element('guestConnectionStatus').textContent,'summary and recovery guidance are not duplicated');
    f.callbacks().onConnection({state:'closed'});assert.ok(f.element('guestConnectionStatus').textContent.includes(expected));
    f.callbacks().onConnection({state:'connected'});
  }
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();f.callbacks().onConnection({state:'disconnected',reason:'private-token-and-sdp'});assert.ok(!f.element('guestConnectionStatus').textContent.includes('private-token-and-sdp'));assert.ok(!f.element('guestConnectionStatus').textContent.includes('invitation is no longer active'));
});


test('every media-engine failure has a safe diagnostic without exposing signaling payloads',async()=>{
  const engine=fs.readFileSync(require.resolve('../../rareiq/web/static/greenroom_media.js'),'utf8');
  const reasons=new Set([...engine.matchAll(/fail\('([^']+)'/g)].map(match=>match[1]));
  for(const reason of ['guest_access_ended','signaling_disconnected'])reasons.add(reason);
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  for(const reason of reasons){f.callbacks().onConnection({state:'connected'});f.callbacks().onConnection({state:'disconnected',reason});assert.equal(f.element('guestBadge').attributes['data-connection-reason'],reason,reason);assert.ok(!f.element('guestConnectionStatus').textContent.includes(reason));}
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


test('capture transitions cannot enable joining without a secure invitation',async()=>{
  const f=fixture({location:{hash:'',pathname:'/guest'}});assert.equal(f.element('guestJoin').disabled,true);
  f.element('guestMicrophone').listeners.click();f.resolve([{kind:'audio',stop(){}}]);await settle();assert.equal(f.element('guestJoin').disabled,true);
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});assert.equal(f.callbacks(),undefined);
  const insecure=fixture({isSecureContext:false});assert.equal(insecure.element('guestJoin').disabled,true);await insecure.element('guestMicrophone').listeners.click();assert.equal(insecure.captureCalls(),0);assert.equal(insecure.element('guestJoin').disabled,true);
});

test('device feedback survives room updates and unsupported capture never starts',async()=>{
  const f=fixture();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});
  f.element('guestMicrophone').listeners.click();f.reject({name:'NotAllowedError'});await settle();assert.match(f.element('guestDeviceStatus').textContent,/permission was not granted/);
  f.callbacks().onState(roomState('admitted',{}));assert.match(f.element('guestDeviceStatus').textContent,/permission was not granted/);
  const unsupported=fixture({navigator:{mediaDevices:{}}});assert.equal(unsupported.element('guestMicrophone').disabled,true);assert.match(unsupported.element('guestDeviceStatus').textContent,/unavailable in this browser/);
  await unsupported.element('guestMicrophone').listeners.click();assert.equal(unsupported.captureCalls(),0);
});

for(const enumerationFails of [false,true])test(`successful capture retains the actual selected microphone (enumeration failure=${enumerationFails})`,async()=>{
  const f=fixture();f.context.navigator.mediaDevices.enumerateDevices=async()=>{if(enumerationFails)throw Error('fixture device list failed');return [{kind:'audioinput',deviceId:'actual-mic',label:'Fixture microphone'}];};
  f.element('guestMicrophone').listeners.click();const raw={kind:'audio',stop(){},getSettings:()=>({deviceId:'actual-mic'})};f.resolve([raw]);await settle();
  assert.equal(f.element('guestMicDevice').value,'actual-mic');assert.equal(f.element('guestMicrophone').attributes['aria-pressed'],'true');assert.match(f.element('guestDeviceStatus').textContent,/Microphone is on/);
  if(enumerationFails)assert.match(f.element('guestDeviceStatus').textContent,/current capture continues/);
  f.element('guestMicDevice').value='missing';f.element('guestMicDevice').listeners.change();f.reject({name:'OverconstrainedError'});await settle();assert.equal(f.element('guestMicDevice').value,'actual-mic');assert.equal(f.element('guestMicrophone').attributes['aria-pressed'],'true');
});

test('terminal network rejection is caught and explicit retry reuses its authenticated session',async()=>{
  const owners=[];let joins=0;
  const f=fixture({fetch:async path=>{if(path==='/guest/join')joins++;return {ok:true};},ProducerGuestMedia:{createPublisher(options){owners.push(options);return {setTracks(){},close(){},async connect(){if(owners.length===1)throw Error('signaling_unavailable');options.onState({participant:{id:'a'.repeat(32),name:'Current connection',state:'waiting'}});}};}}});
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});assert.equal(f.element('guestReconnect').hidden,false);assert.equal(f.element('guestReconnect').disabled,false);
  await f.element('guestReconnect').listeners.click();assert.equal(joins,1);assert.equal(owners.length,2);assert.equal(owners[0].token,owners[1].token);assert.equal(f.element('guestReconnect').hidden,true);
  owners[0].onState({participant:{id:'a'.repeat(32),name:'Obsolete callback',state:'waiting'}});assert.equal(f.element('guestName').value,'Current connection');
  owners[1].onConnection({state:'closed',reason:'guest_access_ended'});assert.equal(f.element('guestReconnect').hidden,true);assert.equal(f.element('guestJoin').disabled,true);
  await f.element('guestReconnect').listeners.click();await f.element('guestJoinForm').listeners.submit({preventDefault(){}});assert.equal(owners.length,2);assert.equal(joins,1);
});

test('late connection rejection after leave cannot restore retry controls or replace the leave message',async()=>{
  let reject;const f=fixture({ProducerGuestMedia:{createPublisher(){return {setTracks(){},close(){},connect:()=>new Promise((_,fail)=>reject=fail)};}}});
  const joining=f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();await f.element('guestLeave').listeners.click();reject(Error('signaling_unavailable'));await joining;
  assert.equal(f.element('guestBadge').textContent,'LEFT THE ROOM');assert.equal(f.element('guestReconnect').hidden,true);assert.equal(f.element('guestConnectionStatus').hidden,true);
});

test('late successful invitation response after leave is cleaned up without opening media',async()=>{
  let finish;const requests=[];const f=fixture({fetch:async(path,options)=>{requests.push(path);if(path==='/guest/join')return new Promise(resolve=>finish=resolve);return {ok:true};}});
  const joining=f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();await f.element('guestLeave').listeners.click();finish({ok:true});await joining;
  assert.equal(f.callbacks(),undefined);assert.equal(requests.at(-1),'/guest/leave');assert.equal(f.element('guestBadge').textContent,'LEFT THE ROOM');
});

test('sound rows keep keyboard focus and action errors remain visible while another sound plays',async()=>{
  let finish,stateCallback,state={sounds:[{id:'clip',label:'Fixture clip'}],playing:0};
  const f=fixture({ProducerGuestMicrophone:{create(raw,onTrack,onStatus,onState){stateCallback=onState;return {configure:async()=>{},snapshot:()=>state,playSound:()=>new Promise(resolve=>finish=()=>{state.playing=1;onState(state);resolve();}),playCue:async()=>{},addSound:async()=>{throw Error('sound_file_too_large');},removeSound(){state.sounds=[];onState(state);},close(){raw.stop();}};}}});
  f.element('guestMicrophone').listeners.click();f.resolve([{kind:'audio',stop(){}}]);await settle();const row=f.element('guestSoundList').children[0],play=row.children[1],remove=row.children[2];play.focus();
  const playing=play.listeners.click();assert.equal(f.element('guestSoundList').children[0],row);finish();await playing;assert.equal(f.element('guestSoundList').children[0],row);assert.equal(f.context.document.activeElement,play);
  f.element('guestSoundFile').files=[{}];f.element('guestSoundFile').listeners.change();await settle();assert.match(f.element('guestAudioError').textContent,/10 MB/);assert.equal(f.element('guestAudioError').hidden,false);
  stateCallback(state);assert.equal(f.element('guestAudioError').hidden,false);await f.element('guestCueChime').listeners.click();assert.equal(f.element('guestAudioError').hidden,true);
  remove.focus();await remove.listeners.click();assert.equal(f.element('guestSoundList').children.length,0);assert.equal(f.context.document.activeElement,f.element('guestSoundFile'));
});

test('guest gate and sound sliders expose their current units to assistive technology',()=>{
  const f=fixture();assert.equal(f.element('guestGateThreshold').attributes['aria-valuetext'],'-45 decibels');assert.equal(f.element('guestSoundVolume').attributes['aria-valuetext'],'50 percent');
  f.element('guestGateThreshold').value='-30';f.element('guestGateThreshold').listeners.input();assert.equal(f.element('guestGateThreshold').attributes['aria-valuetext'],'-30 decibels');
  f.element('guestSoundVolume').value='75';f.element('guestSoundVolume').listeners.input();assert.equal(f.element('guestSoundVolume').attributes['aria-valuetext'],'75 percent');
});


test('retry invalidates the former return-audio stream and its late playback result',async()=>{
  const owners=[];let rejectPlay;const f=fixture({ProducerGuestMedia:{createPublisher(options){owners.push(options);return {setTracks(){},close(){},connect:async()=>{}};}}});
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});f.element('guestReturnAudio').play=()=>new Promise((_,reject)=>rejectPlay=reject);owners[0].onReturnAudio({});
  owners[0].onConnection({state:'closed',reason:'signaling_disconnected'});await f.element('guestReconnect').listeners.click();assert.equal(f.element('guestReturnAudio').srcObject,null);
  rejectPlay(Error('old stream retired'));await settle();assert.equal(f.element('guestRoomAudio').hidden,true);owners[0].onReturnAudio({});assert.equal(f.element('guestReturnAudio').srcObject,null);
});

for(const phase of ['join','retry'])for(const kind of ['camera','microphone','screen'])test(`${kind} can stop while ${phase} signaling is pending without reopening after completion`,async()=>{
  const owners=[],published=[];let finish;
  const f=fixture({MediaStream:class{constructor(tracks){this.tracks=tracks;}getVideoTracks(){return this.tracks.filter(track=>track.kind==='video');}},ProducerGuestMedia:{createPublisher(options){owners.push(options);const index=owners.length;return {setTracks:tracks=>published.push(tracks),close(){},connect(){if(phase==='retry'&&index===1){options.onState(roomState('waiting',{}));return Promise.resolve();}return new Promise(resolve=>{finish=()=>{options.onState(roomState('waiting',{}));resolve();};});}};}}});
  const button=f.element(kind==='camera'?'guestCamera':kind==='microphone'?'guestMicrophone':'guestScreen');
  const tracks=(kind==='screen'?['video','audio']:[kind==='camera'?'video':'audio']).map(type=>({kind:type,stops:0,stop(){this.stops++;}}));
  button.listeners.click();f.resolve(tracks);await settle();
  let pending=f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  if(phase==='retry'){await pending;owners[0].onConnection({state:'closed',reason:'signaling_disconnected'});pending=f.element('guestReconnect').listeners.click();await settle();}
  assert.equal(button.disabled,false);assert.equal(f.element('guestLeave').hidden,false);assert.equal(f.element('guestJoin').disabled,true);
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});await f.element('guestReconnect').listeners.click();assert.equal(owners.length,phase==='retry'?2:1);
  await button.listeners.click();assert.ok(tracks.every(track=>track.stops===1));assert.equal(published.at(-1)[kind],null);
  if(kind==='screen')assert.equal(published.at(-1).screen_audio,null);
  const captures=f.captureCalls();finish();await pending;assert.equal(f.captureCalls(),captures);assert.equal(button.attributes['aria-pressed'],'false');assert.equal(published.at(-1)[kind],null);
  await f.element('guestLeave').listeners.click();
});

test('finishing signaling does not release a newer capture operation busy state',async()=>{
  let finish;const f=fixture({ProducerGuestMedia:{createPublisher(){return {setTracks(){},close(){},connect:()=>new Promise(resolve=>finish=resolve)};}}});
  const joining=f.element('guestJoinForm').listeners.submit({preventDefault(){}});await settle();
  f.element('guestMicrophone').listeners.click();assert.equal(f.element('guestMicrophone').disabled,true);
  finish();await joining;assert.equal(f.element('guestMicrophone').disabled,true);
  f.resolve([{kind:'audio',stop(){}}]);await settle();assert.equal(f.element('guestMicrophone').disabled,false);
  await f.element('guestLeave').listeners.click();
});

for(const failed of [false,true])test(`built-in cue restores keyboard focus after a disabled pending action (failed=${failed})`,async()=>{
  let finish;const f=fixture({ProducerGuestMicrophone:{create(raw){return {configure:async()=>{},snapshot:()=>({sounds:[],playing:0}),playCue:()=>new Promise((resolve,reject)=>finish=()=>failed?reject(Error('audio_unavailable')):resolve()),close(){raw.stop();}};}}});
  f.element('guestMicrophone').listeners.click();f.resolve([{kind:'audio',stop(){}}]);await settle();
  const cue=f.element('guestCueChime');cue.focus();const playing=cue.listeners.click();assert.equal(cue.disabled,true);
  // Browsers can blur a focused control when its disabled state changes.
  f.context.document.activeElement=f.context.document.body;finish();await playing;
  assert.equal(cue.disabled,false);assert.equal(f.context.document.activeElement,cue);
  await f.element('guestLeave').listeners.click();
});

const mediaStreamFixture=class{constructor(tracks){this.tracks=tracks;}getVideoTracks(){return this.tracks.filter(track=>track.kind==='video');}};
const mediaButton=kind=>kind==='camera'?'guestCamera':kind==='microphone'?'guestMicrophone':'guestScreen';
const mediaTracks=kind=>(kind==='screen'?['video','audio']:[kind==='camera'?'video':'audio']).map(type=>({kind:type,stops:0,stop(){this.stops++;}}));

for(const active of ['camera','microphone','screen'])test(`${active} OFF remains available while another device permission is pending`,async()=>{
  const f=fixture({MediaStream:mediaStreamFixture});await f.element('guestJoinForm').listeners.submit({preventDefault(){}});
  const button=f.element(mediaButton(active)),tracks=mediaTracks(active);button.listeners.click();f.resolve(tracks);await settle();
  const pendingKind=active==='camera'?'microphone':'camera',pending=f.element(mediaButton(pendingKind)).listeners.click();
  assert.equal(button.disabled,false);await button.listeners.click();assert.ok(tracks.every(track=>track.stops===1));assert.equal(f.publications.at(-1)[active],null);
  assert.equal(f.element(mediaButton(pendingKind)).disabled,true,'OFF must not release another request busy state');
  f.resolve(mediaTracks(pendingKind));await pending;assert.equal(button.attributes['aria-pressed'],'false');assert.equal(f.publications.at(-1)[active],null);
  await f.element('guestLeave').listeners.click();
});

for(const kind of ['camera','microphone'])for(const failed of [false,true])test(`${kind} OFF during enumeration ignores its late ${failed?'failure':'success'}`,async()=>{
  const f=fixture({MediaStream:mediaStreamFixture});let finish;
  f.context.navigator.mediaDevices.enumerateDevices=()=>new Promise((resolve,reject)=>finish=()=>failed?reject(Error('late enumeration')):resolve([]));
  const button=f.element(mediaButton(kind)),tracks=mediaTracks(kind),capture=button.listeners.click();f.resolve(tracks);await settle();
  assert.equal(button.disabled,false);await button.listeners.click();assert.ok(tracks.every(track=>track.stops===1));const notice=f.element('guestDeviceStatus').textContent;
  finish();await capture;assert.equal(button.attributes['aria-pressed'],'false');assert.equal(f.element('guestDeviceStatus').textContent,notice);assert.match(notice,/is off/);
});

for(const kind of ['camera','microphone'])test(`${kind} OFF cancels a pending replacement and stops the late stream`,async()=>{
  const f=fixture({MediaStream:mediaStreamFixture});await f.element('guestJoinForm').listeners.submit({preventDefault(){}});
  const button=f.element(mediaButton(kind)),original=mediaTracks(kind);button.listeners.click();f.resolve(original);await settle();const obsoleteEnded=original[0].onended;
  const select=f.element(kind==='camera'?'guestCameraDevice':'guestMicDevice');select.value='replacement';select.listeners.change();assert.equal(button.disabled,false);
  await button.listeners.click();const before=f.publications.length,late=mediaTracks(kind);f.resolve(late);await settle();
  assert.equal(original[0].stops,1);assert.equal(late[0].stops,1);assert.equal(button.attributes['aria-pressed'],'false');assert.equal(f.publications.length,before);
  const fresh=mediaTracks(kind);button.listeners.click();f.resolve(fresh);await settle();obsoleteEnded();assert.equal(fresh[0].stops,0);assert.equal(button.attributes['aria-pressed'],'true');
  await f.element('guestLeave').listeners.click();
});

test('microphone OFF cancels pending processing without publishing a late processed track',async()=>{
  let finish;const processed={kind:'audio',stop(){}},f=fixture({ProducerGuestMicrophone:{create(raw,onTrack){return {configure:()=>new Promise(resolve=>finish=()=>{onTrack(processed);resolve();}),close(){raw.stop();},snapshot:()=>({sounds:[],playing:0})};}}});
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});const button=f.element('guestMicrophone'),tracks=mediaTracks('microphone'),capture=button.listeners.click();f.resolve(tracks);await settle();
  assert.equal(button.disabled,false);await button.listeners.click();const before=f.publications.length;finish();await capture;
  assert.equal(tracks[0].stops,1);assert.equal(button.attributes['aria-pressed'],'false');assert.equal(f.publications.length,before);assert.equal(f.publications.at(-1).microphone,null);
});

for(const kind of ['camera','microphone','screen'])test(`unexpected ${kind} end reports capture loss and an obsolete callback cannot stop replacement`,async()=>{
  const f=fixture({MediaStream:mediaStreamFixture});const button=f.element(mediaButton(kind)),tracks=mediaTracks(kind);button.listeners.click();f.resolve(tracks);await settle();const ended=tracks[0].onended;
  ended();assert.equal(button.attributes['aria-pressed'],'false');assert.match(f.element('guestDeviceStatus').textContent,/disconnected or stopped|capture ended/);
  const fresh=mediaTracks(kind);button.listeners.click();f.resolve(fresh);await settle();ended();assert.equal(fresh[0].stops,0);assert.equal(button.attributes['aria-pressed'],'true');
  await button.listeners.click();
});

test('screen hint distinguishes private preview, sharing permission and paused connection; audio ending preserves video',async()=>{
  const f=fixture({MediaStream:mediaStreamFixture}),tracks=mediaTracks('screen');f.element('guestScreen').listeners.click();f.resolve(tracks);await settle();
  assert.match(f.element('guestMediaHint').textContent,/screen preview stays on this device until you join/);
  await f.element('guestJoinForm').listeners.submit({preventDefault(){}});assert.match(f.element('guestMediaHint').textContent,/screen and its audio are enabled for sharing/);
  tracks[1].onended();assert.equal(tracks[0].stops,0);assert.equal(f.element('guestScreen').attributes['aria-pressed'],'true');assert.match(f.element('guestDeviceStatus').textContent,/Screen audio stopped/);assert.match(f.element('guestMediaHint').textContent,/no screen audio/);
  f.callbacks().onConnection({state:'disconnected',reason:'signaling_disconnected'});assert.match(f.element('guestMediaHint').textContent,/paused or pending/);assert.match(f.element('guestMediaHint').textContent,/Delivery is not confirmed/);assert.match(f.element('guestMediaHint').textContent,/remain on until you turn them off/);
  f.callbacks().onState(roomState('admitted',{}));assert.match(f.element('guestMediaHint').textContent,/enabled for sharing/);
  f.callbacks().onConnection({scope:'peer',state:'peer_disconnected',peer_id:'fixture'});assert.match(f.element('guestMediaHint').textContent,/Some enabled sources may not reach/);
  await f.element('guestLeave').listeners.click();
});
