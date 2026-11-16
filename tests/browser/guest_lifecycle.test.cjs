const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/guest.js'),'utf8');
const settle=async()=>{for(let index=0;index<20;index++)await Promise.resolve();};
function fixture(){
  const elements=new Map(),handlers=new Map(),publications=[];let resolveCapture,publisherOptions,captureCalls=0;
  const element=id=>{if(!elements.has(id))elements.set(id,{value:id==='guestName'?'Fixture guest':'',hidden:false,disabled:false,srcObject:null,textContent:'',attributes:{},listeners:{},classList:{toggle(){},remove(){}},setAttribute(name,value){this.attributes[name]=value;},addEventListener(name,handler){this.listeners[name]=handler;},pause(){},play:async()=>{},replaceChildren(){},add(){}});return elements.get(id);};
  const capture=()=>new Promise(resolve=>{captureCalls++;resolveCapture=resolve;});
  const context={document:{getElementById:element},location:{hash:'#invite='+'b'.repeat(64),pathname:'/guest'},history:{replaceState(){}},URLSearchParams,crypto:require('node:crypto').webcrypto,sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},isSecureContext:true,navigator:{mediaDevices:{getUserMedia:capture,getDisplayMedia:capture,enumerateDevices:async()=>[]}},fetch:async()=>({ok:true}),addEventListener:(name,callback)=>handlers.set(name,callback),ProducerGuestMedia:{createPublisher(options){publisherOptions=options;return {setTracks:tracks=>publications.push(tracks),close(){},connect(){options.onState({participant:{id:'a'.repeat(32),name:'Fixture guest',state:'waiting'},on_air_sources:[]});}}}}};
  context.window=context;vm.runInNewContext(source,context);
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
  assert.match(html,/guest\/assets\/guest\.js\?v=20261115-2/);
});
