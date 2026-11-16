const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const model=require('../../rareiq/web/static/program_composition.js');
const ROOT=path.resolve(__dirname,'../../rareiq/web/static');
const moduleSource=fs.readFileSync(path.join(ROOT,'program_composition.js'),'utf8');
const runtimeSource=fs.readFileSync(path.join(ROOT,'overlay_runtime.js'),'utf8');
const settle=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const G='a'.repeat(32),CAM=`guest:${G}:camera`,SCREEN=`guest:${G}:screen`,AUDIO=`guest:${G}:audio`;
function track(kind='video'){
  const listeners=new Map();return {kind,readyState:'live',enabled:true,muted:false,stops:0,
    addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn);},
    removeEventListener(type,fn){listeners.get(type)?.delete(fn);},emit(type){for(const fn of [...listeners.get(type)||[]])fn();},
    stop(){this.stops++;this.readyState='ended';this.emit('ended');}};
}
const room=()=>({revision:1,participants:[{id:G,name:'Fixture guest',state:'admitted',connected:true,expired:false,media:{camera:true,microphone:true,screen:true,screen_audio:true}}]});
const state=(values={})=>({generation:0,program_slot:1,preview_slot:2,program_sources:['camera:1'],preview_sources:['camera:2'],program_layout:'auto',transition:'cut',duration_ms:0,...values});
function fixture(options={}){
  let clock=1000,next=0;const timers=new Map(),intervals=new Map(),nodes=[],statuses=[],acks=[],tracks=new Map(),events=new Map();
  const settings={rejectAudio:false,...options};
  const later=(fn,delay)=>{timers.set(++next,{fn,delay});return next;},cancel=id=>timers.delete(id);
  const repeat=(fn,delay)=>{intervals.set(++next,{fn,delay});return next;};
  class Element{
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.parentNode=null;this.dataset={};this.attrs={};this.className='';this.style={setProperty:(key,value)=>this.style[key]=value};this.listeners=new Map();this.src='';this.srcObject=null;this.readyState=0;this.videoWidth=0;this.currentTime=0;this.frames=new Map();this.ownerDocument=document;nodes.push(this);
      this.classList={add:(...values)=>this.className=[...new Set([...this.className.split(' ').filter(Boolean),...values])].join(' '),remove:(...values)=>this.className=this.className.split(' ').filter(v=>!values.includes(v)).join(' '),contains:value=>this.className.split(' ').includes(value)};
      if(tag==='iframe')this.contentDocument={querySelector:()=>this.cameraOffline?null:{complete:true,naturalWidth:1280}};
    }
    append(...children){for(const child of children){child.remove();child.parentNode=this;this.children.push(child);}}
    remove(){if(this.parentNode){this.parentNode.children=this.parentNode.children.filter(node=>node!==this);this.parentNode=null;}}
    setAttribute(key,value){this.attrs[key]=String(value);}
    removeAttribute(key){delete this.attrs[key];if(key==='src')this.src='';}
    addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(fn);}
    removeEventListener(type,fn){this.listeners.get(type)?.delete(fn);}
    emit(type){for(const fn of [...this.listeners.get(type)||[]])fn();}
    play(){this.paused=false;return this.tagName==='AUDIO'&&settings.rejectAudio?Promise.reject(Error('blocked')):Promise.resolve();}
    pause(){this.paused=true;}
    requestVideoFrameCallback(fn){this.frames.set(++next,fn);return next;}
    cancelVideoFrameCallback(id){this.frames.delete(id);}
    paint(){this.readyState=4;this.videoWidth=640;this.currentTime+=.04;const callbacks=[...this.frames.values()];this.frames.clear();for(const fn of callbacks)fn();}
  }
  const document={readyState:'complete',createElement:tag=>new Element(tag),querySelector:selector=>selector==='[data-producer-program-output]'&&settings.boot?container:null};
  const container=document.createElement('main');
  const receiver={tracks:id=>tracks.get(id)||{},sendReady:ids=>{receiver.lastReady=ids;},rendered:value=>acks.push(value),connect:()=>Promise.resolve(),close:()=>{receiver.closed=true;}};
  const config={container,document,mediaReceiver:receiver,muted:!!settings.muted,bus:settings.bus||'program',onStatus:s=>statuses.push(s),onRendered:g=>acks.push(g),now:()=>clock,setTimeout:later,clearTimeout:cancel,setInterval:repeat,clearInterval:id=>intervals.delete(id),requestAnimationFrame:fn=>later(fn,16),cancelAnimationFrame:cancel,makeStream:list=>({getTracks:()=>list})};
  const output={container,document,receiver,config,timers,intervals,nodes,statuses,acks,tracks,settings,events,advance:amount=>clock+=amount};
  output.run=async delay=>{const entry=[...timers].find(([,item])=>item.delay===delay);assert.ok(entry,`Expected ${delay}ms timer`);timers.delete(entry[0]);clock+=delay;await entry[1].fn();await settle();};
  output.close=()=>output.view?.close();
  if(settings.boot){
    output.current={value:state(),pending:null};output.requests=[];
    const sandbox={document,performance:{now:()=>clock},setTimeout:later,clearTimeout:cancel,setInterval:repeat,clearInterval:id=>intervals.delete(id),requestAnimationFrame:fn=>later(fn,16),cancelAnimationFrame:cancel,AbortController,
      MediaStream:class{constructor(list){this.list=list;}getTracks(){return this.list;}},
      fetch:async url=>{output.requests.push(url);return output.current.pending||{ok:true,json:async()=>output.current.value};},
      addEventListener:(name,fn)=>{if(!events.has(name))events.set(name,new Set());events.get(name).add(fn);},removeEventListener:(name,fn)=>events.get(name)?.delete(fn),
      ProducerGuestMedia:{createReceiver:opts=>{output.mediaOptions=opts;return receiver;}}};
    sandbox.window=sandbox;vm.createContext(sandbox);vm.runInContext(runtimeSource,sandbox);vm.runInContext(moduleSource,sandbox);
    output.hide=()=>{for(const fn of [...events.get('pagehide')||[]])fn();};
  }else output.view=new model.ProducerCompositionView(config);
  return output;
}
function guestTracks(f){const value={camera:track(),screen:track(),microphone:track('audio'),screen_audio:track('audio')};f.tracks.set(G,value);return value;}
function paint(f){for(const node of f.nodes)if(node.tagName==='VIDEO'&&node.srcObject)node.paint();f.view?.refresh();}

test('source union preserves explicit blank and rejects arbitrary URLs, duplicates and malformed state',()=>{
  assert.deepEqual(model.normalizeState(state({program_sources:[]})).sources,[]);
  assert.deepEqual(model.normalizeState({generation:0,program_slot:3,preview_slot:2}).sources,['camera:3']);
  for(const values of [null,['https://outside.invalid'],['camera:1','camera:1'],['camera:9'],Array(7).fill(CAM)])assert.equal(model.normalizeState(state({program_sources:values})),null);
  assert.equal(model.parseSource(AUDIO).kind,'audio');assert.equal(model.normalizeState(state({generation:-1})),null);
});

test('microphone is deduplicated across camera/screen/audio and screen sound requires selected screen',()=>{
  const media={camera:track(),screen:track(),microphone:track('audio'),screen_audio:track('audio')};
  assert.deepEqual([...model.audioPlan([CAM,SCREEN,AUDIO],room(),()=>media).keys()],[G+':microphone',G+':screen_audio']);
  assert.deepEqual([...model.audioPlan([CAM],room(),()=>media).keys()],[G+':microphone']);
  const waiting=room();waiting.participants[0].state='waiting';assert.equal(model.audioPlan([CAM],waiting,()=>media).size,0);
});

test('unchanged local Program retains clean camera subscription and waits for real image',async()=>{
  const f=fixture();f.view.render(state());const frame=f.view.current.tiles[0].iframe;frame.cameraOffline=true;await f.run(16);assert.equal(f.acks.length,0);
  frame.cameraOffline=false;f.view.refresh();assert.deepEqual(f.acks,[0]);f.view.render(state());assert.equal(f.view.current.tiles[0].iframe,frame);assert.equal(frame.src,'/output/camera/1');f.close();assert.equal(frame.src,'');
});

test('superseded transitions cannot retire the latest camera',async()=>{
  const f=fixture();f.view.render(state());await f.run(16);
  f.view.render(state({generation:1,program_sources:['camera:2'],transition:'fade',duration_ms:500}));const stale=[...f.timers.values()].find(t=>t.delay===500).fn;
  f.view.render(state({generation:2,program_sources:['camera:3'],transition:'zoom',duration_ms:500}));await f.run(16);stale();
  assert.equal(f.view.current.tiles[0].iframe.src,'/output/camera/3');await f.run(500);assert.equal(f.view.outgoing,null);assert.equal(f.view.current.tiles[0].iframe.src,'/output/camera/3');f.close();
});

test('empty Program clears former sources and never falls back to camera one',async()=>{
  const f=fixture();f.view.render(state());await f.run(16);f.view.render(state({generation:1,program_sources:[]}));await f.run(16);
  assert.equal(f.view.current.tiles.length,0);assert.ok(f.nodes.filter(n=>n.tagName==='IFRAME').every(n=>n.src===''));assert.deepEqual(f.acks,[0,1]);f.close();
});

test('Preview preloads video but never plays guest audio before Take',async()=>{
  const f=fixture();guestTracks(f);f.view.render(state({preview_sources:[CAM]}),room());await f.run(16);paint(f);assert.deepEqual(f.view.readySources(),[CAM]);assert.equal(f.view.audio.size,0);
  const previewVideo=f.view.preloads.get(CAM).video;
  f.view.render(state({generation:1,program_sources:[CAM],preview_sources:[]}));await f.run(16);await settle();
  assert.equal(f.view.current.tiles[0].video,previewVideo);assert.equal(f.view.audio.size,1);assert.deepEqual(f.acks,[0,1]);f.close();
});

test('muted producer monitors never construct playable audio',async()=>{
  const f=fixture({muted:true});guestTracks(f);f.view.render(state({program_sources:[CAM,SCREEN,AUDIO]}),room());paint(f);await f.run(16);await settle();
  assert.equal(f.view.audio.size,0);assert.equal(f.nodes.filter(n=>n.tagName==='AUDIO').length,0);f.close();
});

test('waiting/removed/disconnected guest tracks cannot become ready',async()=>{
  const f=fixture();guestTracks(f);const snapshot=room();snapshot.participants[0].state='waiting';f.view.render(state({program_sources:[CAM]}),snapshot);paint(f);await f.run(16);
  assert.deepEqual(f.view.readySources(),[]);assert.equal(f.view.current.tiles[0].video.srcObject,null);
  snapshot.revision=2;snapshot.participants[0].state='admitted';f.view.setRoom(snapshot);paint(f);assert.deepEqual(f.view.readySources(),[CAM]);
  snapshot.revision=3;snapshot.participants[0].connected=false;f.view.setRoom(snapshot);assert.equal(f.view.current.tiles[0].video.srcObject,null);assert.equal(f.view.audio.size,0);f.close();
});

test('stalled frames hide stale video and remove corresponding Program audio',async()=>{
  const f=fixture();guestTracks(f);f.view.render(state({program_sources:[CAM]}),room());paint(f);await f.run(16);await settle();assert.equal(f.view.audio.size,1);
  f.advance(2600);f.view.refresh();assert.equal(f.view.current.tiles[0].node.dataset.ready,'false');assert.deepEqual(f.view.readySources(),[]);assert.equal(f.view.audio.size,0);
  paint(f);await settle();assert.equal(f.view.current.tiles[0].node.dataset.ready,'true');f.close();
});

test('track mute/ended clears immediately without stopping shared receiver tracks',async()=>{
  const f=fixture();const media=guestTracks(f);f.view.render(state({program_sources:[CAM]}),room());paint(f);await f.run(16);await settle();
  media.camera.muted=true;media.camera.emit('mute');assert.equal(f.view.current.tiles[0].video.srcObject,null);assert.equal(f.view.audio.size,0);
  f.close();assert.ok(Object.values(media).every(t=>t.stops===0));
});

test('replaced tracks cannot inherit stale readiness or late callbacks',async()=>{
  const f=fixture();const media=guestTracks(f);f.view.render(state({program_sources:[CAM]}),room());paint(f);await f.run(16);
  const tile=f.view.current.tiles[0],oldFrame=[...tile.video.frames.values()][0];media.camera=track();f.view.refresh();oldFrame();assert.deepEqual(f.view.readySources(),[]);
  tile.video.paint();f.view.refresh();assert.deepEqual(f.view.readySources(),[CAM]);f.close();
});

test('audio-only Program requires live unmuted audio and reports blocked playback honestly',async()=>{
  const f=fixture({rejectAudio:true});const media=guestTracks(f);f.view.render(state({program_sources:[AUDIO]}),room());await f.run(16);await settle();
  assert.deepEqual(f.view.readySources(),[AUDIO]);assert.equal(f.container.dataset.audioBlocked,'true');assert.equal(f.acks.length,0);
  f.settings.rejectAudio=false;f.view.resumeAudio();await settle();assert.equal(f.container.dataset.audioBlocked,'false');assert.deepEqual(f.acks,[0]);
  media.microphone.muted=true;media.microphone.emit('mute');assert.equal(f.view.audio.size,0);assert.deepEqual(f.view.readySources(),[]);f.close();
});

test('stale metadata and stale generations cannot revive revoked participants or older compositions',async()=>{
  const f=fixture();guestTracks(f);f.view.render(state({generation:5,program_sources:[CAM]}),room());paint(f);await f.run(16);
  const removed=room();removed.revision=3;removed.participants[0].state='removed';f.view.setRoom(removed);f.view.setRoom(room());assert.equal(f.view.current.tiles[0].video.srcObject,null);
  assert.equal(f.view.render(state({generation:4})),false);assert.equal(f.view.state.generation,5);f.close();
});

test('lost state and close release nodes, audio and timers without recapturing devices',async()=>{
  const f=fixture();guestTracks(f);f.view.render(state({program_sources:[CAM]}),room());paint(f);await f.run(16);await settle();f.advance(4600);f.view.refresh();
  assert.equal(f.view.current,null);assert.equal(f.view.audio.size,0);assert.ok(f.nodes.filter(n=>n.tagName==='VIDEO').every(n=>n.srcObject===null));
  f.close();assert.equal(f.intervals.size,0);assert.equal(f.view.render(state()),false);
});

test('Program entry loads shared receiver before compositor and retains bounded overlay polling',async()=>{
  const html=fs.readFileSync(path.join(ROOT,'program_view.html'),'utf8');assert.ok(html.indexOf('greenroom_media.js')<html.indexOf('program_composition.js'));
  const f=fixture({boot:true});await settle();await f.run(16);assert.equal(f.nodes.find(n=>n.tagName==='IFRAME'&&n.src).src,'/output/camera/1');
  await f.run(300);assert.deepEqual(f.requests,['/api/production/switcher','/api/production/switcher']);f.hide();assert.equal(f.receiver.closed,true);assert.equal(f.intervals.size,0);assert.ok(f.nodes.filter(n=>n.tagName==='IFRAME').every(n=>n.src===''));
});

test('failed or stalled polling clears Program and late results cannot revive it',async()=>{
  const f=fixture({boot:true});await settle();await f.run(16);let resolve;
  f.current.pending=new Promise(done=>resolve=done);const polling=[...f.timers].find(([,t])=>t.delay===300);f.timers.delete(polling[0]);const pending=polling[1].fn();await settle();
  await f.run(4000);assert.ok(f.nodes.filter(n=>n.tagName==='IFRAME').every(n=>n.src===''));
  f.hide();resolve({ok:true,json:async()=>state({generation:9,program_sources:['camera:4']})});await pending;await settle();assert.ok(f.nodes.filter(n=>n.tagName==='IFRAME').every(n=>n.src===''));assert.equal(f.timers.size,0);
});

test('render receipt retries when HTTP state arrives before signaling generation',async()=>{
  const f=fixture();let attempts=0,accepted=false;
  f.view.onRendered=()=>{attempts++;return accepted;};
  f.view.render(state());await f.run(16);assert.ok(attempts>0);assert.equal(f.view.lastRendered,null);
  accepted=true;f.view.refresh();const acknowledged=attempts;
  assert.equal(f.view.lastRendered,'0:["camera:1"]');f.view.refresh();assert.equal(attempts,acknowledged);f.close();
});
