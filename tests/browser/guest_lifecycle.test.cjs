const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/guest.js'),'utf8');
const settle=async()=>{for(let index=0;index<20;index++)await Promise.resolve();};
function fixture(){
  const elements=new Map(),handlers=new Map(),publications=[];let resolveCapture;
  const element=id=>{if(!elements.has(id))elements.set(id,{value:id==='guestName'?'Fixture guest':'',hidden:false,disabled:false,srcObject:null,textContent:'',attributes:{},listeners:{},classList:{toggle(){},remove(){}},setAttribute(name,value){this.attributes[name]=value;},addEventListener(name,handler){this.listeners[name]=handler;},pause(){},play:async()=>{},replaceChildren(){},add(){}});return elements.get(id);};
  const capture=()=>new Promise(resolve=>{resolveCapture=resolve;});
  const context={document:{getElementById:element},location:{hash:'#invite='+'b'.repeat(64),pathname:'/guest'},history:{replaceState(){}},URLSearchParams,crypto:require('node:crypto').webcrypto,sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},isSecureContext:true,navigator:{mediaDevices:{getUserMedia:capture,getDisplayMedia:capture,enumerateDevices:async()=>[]}},fetch:async()=>({ok:true}),addEventListener:(name,callback)=>handlers.set(name,callback),ProducerGuestMedia:{createPublisher(options){return {setTracks:tracks=>publications.push(tracks),close(){},connect(){options.onState({participant:{id:'a'.repeat(32),name:'Fixture guest',state:'waiting'},on_air_sources:[]});}}}}};
  context.window=context;vm.runInNewContext(source,context);
  return {element,handlers,publications,resolve:tracks=>resolveCapture({getTracks:()=>tracks,getVideoTracks:()=>tracks.filter(track=>track.kind==='video'),getAudioTracks:()=>tracks.filter(track=>track.kind==='audio')})};
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
