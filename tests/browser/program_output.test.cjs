const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const model=require('../../rareiq/web/static/program_composition.js');
const layerModel=require('../../rareiq/web/static/production_layer_editor.js');
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

test('custom geometry updates emitted tiles while hidden pictures retain decode and readiness requirements',async()=>{
  const f=fixture(),id='image:12345678-1234-1234-1234-123456789abc';
  const layers=layerModel.normalizeLayers(['camera:1',id],{[id]:{...layerModel.defaults(1),x:.2,y:.3,width:.4,height:.5,opacity:.6,hidden:true,crop:{top:0,right:.1,bottom:0,left:.2}}});
  f.view.render(state({program_sources:['camera:1',id],preview_sources:[],program_layout:'custom',program_layers:layers,program_composition_id:'a'.repeat(64)}));
  const tile=f.view.current.tiles.find(tile=>tile.id===id);
  assert.equal(tile.node.style['--layer-x'],'0.2');assert.equal(tile.node.style['--layer-width'],'0.4');assert.equal(tile.node.dataset.layerHidden,'true');
  await f.run(16);assert.equal(f.statuses.at(-1).rendered,false);
  tile.image.complete=true;tile.image.naturalWidth=640;tile.image.naturalHeight=360;f.view.refresh();
  assert.equal(f.statuses.at(-1).rendered,true);assert.equal(f.statuses.at(-1).compositionId,'a'.repeat(64));
  assert.ok(f.view.readySources().includes('camera:1'));assert.ok(f.view.readySources().includes(id));
  f.close();
});

test('a new staged composition ID cannot inherit old readiness before paint and source decode',async()=>{
  const f=fixture(),id='image:12345678-1234-1234-1234-123456789abc',layers=layerModel.normalizeLayers(['camera:1',id]);
  const first=state({preview_sources:['camera:1',id],preview_layout:'custom',preview_layers:layers,preview_composition_id:'b'.repeat(64)});
  f.view.render(first);await f.run(16);await f.run(16);await f.run(16);
  assert.equal(f.statuses.at(-1).previewCompositionId,null);
  const tile=f.view.preloads.get(id);tile.image.complete=true;tile.image.naturalWidth=640;tile.image.naturalHeight=360;f.view.refresh();
  assert.equal(f.statuses.at(-1).previewCompositionId,'b'.repeat(64));
  f.view.render({...first,preview_composition_id:'c'.repeat(64),preview_layers:{...layers,[id]:{...layers[id],x:.3}}});
  assert.equal(f.statuses.at(-1).previewCompositionId,null);assert.equal(f.view.current.generation,0);
  await f.run(16);assert.equal(f.statuses.at(-1).previewCompositionId,null);await f.run(16);
  assert.equal(f.statuses.at(-1).previewCompositionId,'c'.repeat(64));f.close();
});

test('rotation is emitted around the layer center and group metadata never changes source ownership',async()=>{
  const f=fixture(),layers=layerModel.normalizeLayers([CAM],{[CAM]:{...layerModel.defaults(),rotation:90,group:'Interview'}});
  const tracks=guestTracks(f);
  f.view.render(state({program_sources:[CAM],preview_sources:[],program_layout:'custom',program_layers:layers,program_composition_id:'d'.repeat(64)}),room());
  await f.run(16);paint(f);await settle();f.view.refresh();
  assert.equal(f.view.current.tiles[0].node.style['--layer-rotation'],'90');
  assert.equal(f.statuses.at(-1).rendered,true);assert.equal(f.statuses.at(-1).compositionId,'d'.repeat(64));
  assert.equal(f.view.audio.size,1);assert.equal(tracks.camera.stops,0);assert.equal(tracks.microphone.stops,0);
  f.view.render(state({generation:1,program_sources:[CAM],preview_sources:[],program_layout:'grid'}),room());
  await f.run(16);paint(f);assert.equal(f.view.current.tiles[0].node.style['--layer-rotation'],undefined);
  assert.equal(tracks.camera.stops,0);f.close();
});

test('late same-generation Preview polls cannot restore an earlier custom arrangement or receipt',()=>{
  const f=fixture(),layers=layerModel.normalizeLayers(['camera:1']);
  f.view.render(state({preview_revision:8,preview_sources:['camera:1'],preview_layout:'custom',preview_layers:layers,preview_composition_id:'a'.repeat(64)}));
  assert.equal(f.view.render(state({preview_revision:7,preview_sources:['camera:2'],preview_layout:'auto',preview_composition_id:'b'.repeat(64)})),false);
  assert.equal(f.view.state.previewCompositionId,'a'.repeat(64));f.close();
});
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
    play(){this.paused=false;this.plays=(this.plays||0)+1;return (this.tagName==='AUDIO'||this.tagName==='VIDEO'&&!this.srcObject)&&settings.rejectAudio?Promise.reject(Error('blocked')):Promise.resolve();}
    pause(){this.paused=true;}
    requestVideoFrameCallback(fn){this.frames.set(++next,fn);return next;}
    cancelVideoFrameCallback(id){this.frames.delete(id);}
    paint(){this.readyState=4;this.videoWidth=640;this.currentTime+=.04;const callbacks=[...this.frames.values()];this.frames.clear();for(const fn of callbacks)fn();}
  }
  const document={readyState:'complete',createElement:tag=>new Element(tag),querySelector:selector=>selector==='[data-output-audio-enable]'?soundButton:selector==='[data-producer-program-output]'&&settings.boot?container:null};
  const container=document.createElement('main');
  const soundButton=document.createElement('button');soundButton.hidden=true;
  const receiver={tracks:id=>tracks.get(id)||{},sendReady:(ids,playback)=>{receiver.lastReady=ids;receiver.lastPlayback=playback;},rendered:value=>acks.push(value),connect:()=>Promise.resolve(),close:()=>{receiver.closed=true;}};
  const config={container,document,mediaReceiver:receiver,muted:!!settings.muted,bus:settings.bus||'program',onStatus:s=>statuses.push(s),onRendered:g=>acks.push(g),now:()=>clock,setTimeout:later,clearTimeout:cancel,setInterval:repeat,clearInterval:id=>intervals.delete(id),requestAnimationFrame:fn=>later(fn,16),cancelAnimationFrame:cancel,makeStream:list=>({getTracks:()=>list}),fetch:settings.fetch};
  const output={container,soundButton,document,receiver,config,timers,intervals,nodes,statuses,acks,tracks,settings,events,advance:amount=>clock+=amount};
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

test('producer screen is video-only, needs decoded fresh frames and cannot fall back after withdrawal',async()=>{
  const source='producer:screen:'+'a'.repeat(32),f=fixture(),screen=track(),r={revision:1,participants:[],producer_sources:[{id:source,available:true}]};
  f.tracks.set(source,{screen,microphone:track('audio'),screen_audio:track('audio')});
  assert.equal(model.parseSource(source).kind,'producer_screen');assert.equal(model.audioPlan([source],r,id=>f.tracks.get(id)).size,0);
  f.view.render(state({program_sources:[],preview_sources:[source]}),r);await f.run(16);
  assert.deepEqual(f.view.readySources(),[]);for(const node of f.nodes)if(node.tagName==='VIDEO')node.paint();f.view.refresh();
  assert.deepEqual(f.view.readySources(),[source]);assert.equal(f.view.current.tiles.length,0);
  f.view.render(state({generation:1,program_sources:[source],preview_sources:[]}),r);await f.run(16);for(const node of f.nodes)if(node.tagName==='VIDEO')node.paint();f.view.refresh();
  assert.equal(f.statuses.at(-1).rendered,true);assert.equal(f.view.audio.size,0);
  f.view.setRoom({...r,producer_sources:[]});assert.equal(f.statuses.at(-1).rendered,false);assert.deepEqual(f.view.readySources(),[]);
  assert.equal(f.view.current.tiles[0].video.srcObject,null);assert.equal(screen.stops,0);
  f.view.render(state({generation:2,program_sources:[],preview_sources:[]}),{...r,producer_sources:[]});await f.run(16);
  assert.equal(f.view.current.tiles.length,0);assert.equal(f.view.current.tiles.some(tile=>tile.source.kind==='local'),false);f.close();
});
function paint(f){for(const node of f.nodes)if(node.tagName==='VIDEO'&&node.srcObject)node.paint();f.view?.refresh();}

test('source union preserves explicit blank and rejects arbitrary URLs, duplicates and malformed state',()=>{
  assert.deepEqual(model.normalizeState(state({program_sources:[]})).sources,[]);
  assert.deepEqual(model.normalizeState({generation:0,program_slot:3,preview_slot:2}).sources,['camera:3']);
  for(const values of [null,['https://outside.invalid'],['camera:1','camera:1'],['camera:9'],Array(7).fill(CAM)])assert.equal(model.normalizeState(state({program_sources:values})),null);
  assert.equal(model.parseSource(AUDIO).kind,'audio');assert.equal(model.normalizeState(state({generation:-1})),null);
});

test('imported images preload at their fixed local URL and require decoded dimensions before readiness',async()=>{
  const id='image:12345678-1234-1234-1234-123456789abc',f=fixture();
  assert.equal(model.parseSource(id).kind,'image');assert.equal(model.parseSource('image:../../secret'),null);
  assert.equal(model.audioPlan([id],room(),()=>{throw Error('Images never request guest tracks');}).size,0);
  f.view.render(state({preview_sources:[id]}),room());
  const tile=f.view.preloads.get(id),image=tile.image;
  assert.equal(image.src,'/api/creator/assets/12345678-1234-1234-1234-123456789abc');
  assert.deepEqual(f.view.readySources(),[]);
  image.complete=true;image.naturalWidth=1920;image.naturalHeight=1080;image.emit('load');
  assert.deepEqual(f.view.readySources(),[id]);
  f.view.render(state({generation:1,program_sources:[id],preview_sources:[],transition:'fade',duration_ms:500}),room());
  assert.equal(f.view.current.tiles[0],tile,'Take reuses the preloaded image');await f.run(16);
  assert.equal(f.statuses.at(-1).rendered,true);assert.equal(f.view.audio.size,0);
  image.emit('error');assert.deepEqual(f.view.readySources(),[]);assert.equal(f.statuses.at(-1).rendered,false);
  f.close();assert.equal(image.src,'');image.emit('load');assert.equal(f.view.current,null);
});

test('video preload is silent and paused; Take starts at zero and retires outgoing audio immediately',async()=>{
  const id='video:12345678-1234-1234-1234-123456789abc',f=fixture();
  assert.equal(model.parseSource(id).kind,'video');assert.equal(model.parseSource('video:https://example.test'),null);
  assert.equal(model.audioPlan([id],room(),()=>{throw Error('File video is not guest audio');}).size,0);
  f.view.render(state({preview_sources:[id]}),room());const tile=f.view.preloads.get(id),video=tile.video;
  assert.equal(video.src,'/api/creator/assets/12345678-1234-1234-1234-123456789abc');assert.equal(video.autoplay,false);assert.equal(video.muted,true);assert.equal(video.plays,undefined);assert.deepEqual(f.view.readySources(),[]);
  video.paint();video.emit('loadeddata');assert.deepEqual(f.view.readySources(),[id]);video.currentTime=9;
  f.view.render(state({generation:1,program_sources:[id],preview_sources:[]}));await f.run(16);
  assert.equal(f.view.current.tiles[0],tile);assert.equal(video.currentTime,0);assert.equal(video.muted,false);assert.equal(video.plays,1);assert.equal(f.statuses.at(-1).rendered,true);
  video.emit('waiting');assert.equal(f.statuses.at(-1).rendered,false);video.emit('playing');assert.equal(f.statuses.at(-1).rendered,true);
  f.view.render(state({generation:2,program_sources:[],preview_sources:[],transition:'fade',duration_ms:500}));assert.equal(video.paused,true);assert.equal(video.muted,true);await f.run(500);assert.equal(video.src,'');f.close();
});

test('file playback blockage uses output sound recovery and codec errors fail readiness closed',async()=>{
  const id='video:12345678-1234-1234-1234-123456789abc',f=fixture({rejectAudio:true});
  f.view.render(state({program_sources:[id],preview_sources:[]}));const tile=f.view.current.tiles[0];tile.video.paint();await f.run(16);
  assert.equal(f.statuses.at(-1).audioBlocked,true);assert.equal(f.statuses.at(-1).rendered,false);f.settings.rejectAudio=false;f.view.resumeAudio();await settle();assert.equal(f.statuses.at(-1).rendered,true);
  tile.video.emit('error');assert.deepEqual(f.view.readySources(),[]);assert.equal(f.statuses.at(-1).rendered,false);f.close();
  const preview=fixture({bus:'preview'});preview.view.render(state({preview_sources:[id]}));const silent=preview.view.current.tiles[0].video;silent.paint();await preview.run(16);assert.equal(silent.muted,true);assert.equal(silent.plays,undefined);assert.equal(preview.statuses.at(-1).rendered,true);preview.close();
});

test('text layers load literal definitions over the base grid and support text-only shots',async()=>{
  const id='text:12345678-1234-1234-1234-123456789abc',requests=[],f=fixture({fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({source:{id,text:'<img src=x onerror=alert(1)>\nWelcome',position:'lower-third'}})};}});
  f.view.render(state({program_sources:[id,'camera:1'],preview_sources:[]}));assert.deepEqual(f.view.readySources(),[]);await settle();await f.run(16);
  const tile=f.view.current.tiles[0];assert.equal(tile.text.textContent,'<img src=x onerror=alert(1)>\nWelcome');assert.equal(tile.node.dataset.position,'lower-third');assert.equal(f.view.current.node.dataset.count,'1');assert.equal(f.view.current.node.children[0].dataset.kind,'local');assert.deepEqual(f.view.readySources(),[id]);assert.equal(f.statuses.at(-1).rendered,true);
  assert.equal(requests[0].url,'/api/production/sources/text/12345678-1234-1234-1234-123456789abc');f.view.render(state({generation:1,program_sources:[id],preview_sources:[]}));await settle();await f.run(16);assert.equal(f.view.current.node.dataset.count,'0');assert.equal(f.statuses.at(-1).rendered,true);f.close();assert.equal(requests.at(-1).options.signal.aborted,true);
});

test('late or malformed text definitions cannot revive removed sources',async()=>{
  const id='text:12345678-1234-1234-1234-123456789abc';let resolve;const f=fixture({fetch:()=>new Promise(done=>resolve=done)});
  f.view.render(state({program_sources:[id],preview_sources:[]}));await settle();const tile=f.view.current.tiles[0];f.close();resolve({ok:true,json:async()=>({source:{id,text:'Late',position:'top'}})});await settle();assert.equal(tile.textLoaded,undefined);assert.equal(tile.text.textContent,undefined);
  const invalid=fixture({fetch:async()=>({ok:true,json:async()=>({source:{id,text:'Valid',position:'outside'}})})});invalid.view.render(state({program_sources:[id],preview_sources:[]}));await settle();await invalid.run(16);assert.deepEqual(invalid.view.readySources(),[]);assert.equal(invalid.statuses.at(-1).rendered,false);invalid.close();
  const multiline=fixture({fetch:async()=>({ok:true,json:async()=>({source:{id,text:Array(9).fill('Line').join('\r\n'),position:'top'}})})});multiline.view.render(state({program_sources:[id],preview_sources:[]}));await settle();await multiline.run(16);assert.deepEqual(multiline.view.readySources(),[]);assert.equal(multiline.statuses.at(-1).rendered,false);multiline.close();
});

test('microphone is deduplicated across camera/screen/audio and screen sound requires selected screen',()=>{
  const media={camera:track(),screen:track(),microphone:track('audio'),screen_audio:track('audio')};
  assert.deepEqual([...model.audioPlan([CAM,SCREEN,AUDIO],room(),()=>media).keys()],[G+':microphone',G+':screen_audio']);
  assert.deepEqual([...model.audioPlan([CAM],room(),()=>media).keys()],[G+':microphone']);
  const waiting=room();waiting.participants[0].state='waiting';assert.equal(model.audioPlan([CAM],waiting,()=>media).size,0);
});

test('Program mute flags separately suppress microphone and screen sound without changing source permission',()=>{
  const media={microphone:track('audio'),screen_audio:track('audio')},snapshot=room(),person=snapshot.participants[0];
  person.program_audio={microphone_muted:true,screen_muted:false};
  assert.deepEqual([...model.audioPlan([CAM,SCREEN,AUDIO],snapshot,()=>media).keys()],[G+':screen_audio']);
  assert.equal(model.permitted(model.parseSource(CAM),snapshot),true);
  assert.equal(model.permitted(model.parseSource(SCREEN),snapshot),true);
  person.program_audio={microphone_muted:false,screen_muted:true};
  assert.deepEqual([...model.audioPlan([CAM,SCREEN,AUDIO],snapshot,()=>media).keys()],[G+':microphone']);
  person.program_audio={microphone_muted:true,screen_muted:true};assert.equal(model.audioPlan([CAM,SCREEN,AUDIO],snapshot,()=>media).size,0);
  delete person.program_audio;assert.equal(model.audioPlan([CAM,SCREEN,AUDIO],snapshot,()=>media).size,2,'legacy room snapshots remain audible');
});

test('mid-shot Program mute releases consumers and unmute recreates them without changing video or borrowed tracks',async()=>{
  const f=fixture(),media=guestTracks(f),snapshot=room();f.view.render(state({program_sources:[CAM,SCREEN,AUDIO]}),snapshot);paint(f);await f.run(16);await settle();
  const video=f.view.current.tiles[0].video,screen=f.view.current.tiles[1].video,oldMic=f.view.audio.get(G+':microphone'),oldScreen=f.view.audio.get(G+':screen_audio');
  assert.equal(oldMic.node.dataset.audioSource,'guest:'+G+':microphone');assert.equal(oldMic.node.dataset.audioCategory,'voice');
  assert.equal(oldScreen.node.dataset.audioSource,'guest:'+G+':screen_audio');assert.equal(oldScreen.node.dataset.audioCategory,'screen');
  const muted=room();muted.revision=2;muted.participants[0].program_audio={microphone_muted:true,screen_muted:false};f.view.setRoom(muted);
  assert.equal(f.view.audio.size,1);assert.equal(oldMic.node.srcObject,null);assert.equal(oldMic.node.paused,true);assert.equal(oldMic.node.muted,true);
  assert.equal(f.view.audio.get(G+':screen_audio'),oldScreen);assert.equal(f.view.current.tiles[0].video,video);assert.equal(f.view.current.tiles[1].video,screen);
  muted.revision=3;muted.participants[0].program_audio.screen_muted=true;f.view.setRoom(muted);assert.equal(f.view.audio.size,0);assert.equal(oldScreen.node.srcObject,null);
  assert.deepEqual(f.view.readySources(),[AUDIO,CAM,SCREEN].sort());
  const resumed=room();resumed.revision=4;resumed.participants[0].program_audio={microphone_muted:false,screen_muted:false};f.view.setRoom(resumed);await settle();
  assert.equal(f.view.audio.size,2);assert.notEqual(f.view.audio.get(G+':microphone').node,oldMic.node);assert.notEqual(f.view.audio.get(G+':screen_audio').node,oldScreen.node);
  assert.ok(Object.values(media).every(t=>t.stops===0&&t.enabled===true));f.close();assert.ok(Object.values(media).every(t=>t.stops===0));
});

test('mute cancels queued or late audio playback and Preview remains silent through mute changes',async()=>{
  const f=fixture(),media=guestTracks(f);f.view.render(state({program_sources:[AUDIO]}),room());
  const original=f.view.audio.get(G+':microphone');let plays=0;original.node.play=()=>{plays++;return Promise.resolve();};
  const snapshot=room();snapshot.revision=2;snapshot.participants[0].program_audio={microphone_muted:true,screen_muted:true};f.view.setRoom(snapshot);await settle();assert.equal(plays,0);
  snapshot.revision=3;snapshot.participants[0].program_audio.microphone_muted=false;f.view.setRoom(snapshot);
  const pending=f.view.audio.get(G+':microphone');let resolve;pending.node.play=()=>new Promise(done=>{resolve=done;});await settle();
  snapshot.revision=4;snapshot.participants[0].program_audio.microphone_muted=true;f.view.setRoom(snapshot);resolve();await settle();assert.equal(pending.playing,false);assert.equal(f.view.audio.size,0);
  assert.equal(media.microphone.stops,0);f.close();
  const preview=fixture({bus:'preview'});guestTracks(preview);preview.view.render(state({preview_sources:[CAM,SCREEN,AUDIO]}),snapshot);paint(preview);await preview.run(16);
  snapshot.revision=5;snapshot.participants[0].program_audio={microphone_muted:false,screen_muted:false};preview.view.setRoom(snapshot);await settle();assert.equal(preview.nodes.filter(n=>n.tagName==='AUDIO').length,0);preview.close();
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

test('standalone output exposes sound recovery only while blocked and acknowledges after the explicit click',async()=>{
  const f=fixture({boot:true,rejectAudio:true});guestTracks(f);await settle();
  f.current.value=state({generation:1,program_sources:[AUDIO],preview_sources:[]});
  f.mediaOptions.onState({room:{...room(),switcher:f.current.value}});await f.run(16);await settle();
  assert.equal(f.soundButton.hidden,false);assert.equal(f.receiver.lastPlayback.audioBlocked,true);assert.equal(f.receiver.lastPlayback.rendered,false);assert.equal(f.acks.length,0);
  const audio=f.nodes.find(n=>n.tagName==='AUDIO');let duringClick=false,playedDuringClick=false;
  audio.play=()=>{playedDuringClick=duringClick;return Promise.resolve();};
  duringClick=true;f.soundButton.emit('click');duringClick=false;await settle();
  assert.equal(playedDuringClick,true,'audio.play stays inside the trusted gesture call stack');
  assert.equal(f.soundButton.hidden,true);assert.equal(f.receiver.lastPlayback.audioBlocked,false);assert.equal(f.receiver.lastPlayback.rendered,true);assert.deepEqual(f.acks,[1]);
  f.hide();assert.equal(f.soundButton.listeners.get('click').size,0);
});

test('an earlier receipt does not hide a new same-generation audio block',async()=>{
  const f=fixture();guestTracks(f);const snapshot=room();snapshot.participants[0].program_audio={microphone_muted:true,screen_muted:false};
  f.view.render(state({program_sources:[AUDIO]}),snapshot);await f.run(16);assert.deepEqual(f.acks,[0]);
  f.settings.rejectAudio=true;const unmuted=room();unmuted.revision=2;f.view.setRoom(unmuted);await settle();
  assert.equal(f.statuses.at(-1).audioBlocked,true);assert.equal(f.statuses.at(-1).rendered,false);assert.equal(f.statuses.at(-1).generation,0);
  f.settings.rejectAudio=false;f.view.resumeAudio();await settle();assert.equal(f.statuses.at(-1).rendered,true);f.close();
});

test('signaling catching up to an already-rendered HTTP state sends fresh health before the receipt',async()=>{
  const f=fixture({boot:true});let signalingReady=false;const messages=[];
  f.receiver.sendReady=(_sources,status)=>{if(signalingReady)messages.push({type:'health',generation:status?.generation,rendered:status?.rendered});};
  f.receiver.rendered=generation=>{if(!signalingReady)return false;messages.push({type:'receipt',generation});return true;};
  await settle();await f.run(16);assert.deepEqual(messages,[]);
  signalingReady=true;f.mediaOptions.onState({room:{...room(),switcher:state()}});
  assert.deepEqual(messages.slice(0,2),[{type:'health',generation:0,rendered:true},{type:'receipt',generation:0}]);f.hide();
});

test('PiP accepts two pictures while text and selected microphone stay out of the picture grid',()=>{
  const f=fixture();const image='image:12345678-1234-1234-1234-123456789abc';
  f.view.render(state({program_sources:['camera:1',image,AUDIO],program_layout:'pip'}),room());
  assert.equal(f.view.current.node.dataset.layout,'pip');assert.equal(f.view.current.node.dataset.count,'2');
  assert.equal(f.view.current.tiles.find(t=>t.id===AUDIO).node.hidden,true);assert.equal(f.view.current.tiles[1].node.style['--composition-inset-index'],'0');f.close();
});
