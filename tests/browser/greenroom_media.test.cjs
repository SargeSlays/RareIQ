const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/greenroom_media.js'),'utf8');
const settle=async()=>{for(let n=0;n<60;n++)await Promise.resolve();};

function fixture(){
  let serial=0,time=0,timerId=0;const timers=new Map(),sockets=[],connections=[];
  class Track{
    constructor(kind,id){this.kind=kind;this.id=id||'track-'+(++serial);this.readyState='live';this.enabled=true;this.muted=false;this.stops=0;this.listeners=new Map();}
    stop(){this.stops++;this.readyState='ended';this.onended?.();for(const fn of this.listeners.get('ended')||[])fn();}
    addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(fn);}
    removeEventListener(name,fn){this.listeners.get(name)?.delete(fn);}
  }
  class Stream{
    constructor(tracks=[]){this.values=tracks;}
    getTracks(){return this.values;}
    getAudioTracks(){return this.values.filter(t=>t.kind==='audio');}
    getVideoTracks(){return this.values.filter(t=>t.kind==='video');}
  }
  class Socket{
    constructor(url){this.url=url;this.sent=[];this.readyState=0;this.bufferedAmount=0;sockets.push(this);}
    open(){this.readyState=1;this.onopen?.();}
    message(data){this.onmessage?.({data:JSON.stringify(data)});}
    send(raw){this.sent.push(JSON.parse(raw));}
    close(){this.readyState=3;this.closed=true;}
    dropped(code=1006){this.readyState=3;this.onclose?.({code});}
  }
  class PC{
    constructor(config){this.config=config;this.transceivers=[];this.signalingState='stable';this.connectionState='new';this.ice=[];connections.push(this);}
    addTransceiver(kind,options){const transceiver={direction:options.direction,mid:String(this.transceivers.length),receiver:{track:new Track(kind)},sender:{track:null,async replaceTrack(track){this.track=track;}}};this.transceivers.push(transceiver);return transceiver;}
    getTransceivers(){return this.transceivers;}
    async createOffer(){return {type:'offer',sdp:'v=0\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n'};}
    async createAnswer(){return {type:'answer',sdp:'v=0\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n'};}
    async setLocalDescription(value){this.localDescription=value;this.signalingState=value.type==='offer'?'have-local-offer':'stable';}
    async setRemoteDescription(value){if(this.delayRemote)await this.delayRemote;this.remoteDescription=value;if(value.type==='offer'&&!this.transceivers.length)for(const kind of ['audio','video','video','audio'])this.addTransceiver(kind,{direction:'recvonly'});this.signalingState=value.type==='offer'?'have-remote-offer':'stable';}
    async addIceCandidate(value){this.ice.push(value);}
    emitTrack(index,track=new Track(['audio','video','video','audio'][index])){this.transceivers[index].receiver.track=track;this.ontrack?.({track,transceiver:this.transceivers[index],streams:[]});return track;}
    close(){this.closed=true;this.connectionState='closed';}
  }
  class ClockDate extends Date{static now(){return time;}}
  const setTimer=(fn,ms,repeat)=>{const id=++timerId;timers.set(id,{fn,at:time+ms,ms,repeat});return id;};
  const host={WebSocket:Socket,RTCPeerConnection:PC,MediaStream:Stream,location:{protocol:'https:',host:'fixture.invalid'},
    setInterval:(fn,ms)=>setTimer(fn,ms,true),clearInterval:id=>timers.delete(id),setTimeout:(fn,ms)=>setTimer(fn,ms,false),clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(source,{window:host,Date:ClockDate,Promise,Map,Set,Error,JSON,Object,Array,Number,Boolean,String});
  const tick=async ms=>{const end=time+ms;while(true){const entry=Array.from(timers).filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!entry)break;time=entry[1].at;if(entry[1].repeat)entry[1].at+=entry[1].ms;else timers.delete(entry[0]);entry[1].fn();await settle();}time=end;await settle();};
  return {api:host.ProducerGuestMedia,host,sockets,connections,Track,Stream,timers,tick};
}
function person(id='guest-one',state='admitted'){
  return {id,state,connected:true,media:{microphone:true,camera:true,screen:true,screen_audio:true},sources:{camera:`guest:${id}:camera`,screen:`guest:${id}:screen`,audio:`guest:${id}:audio`}};
}
function receiverState(participants=[person()],sources=['guest:guest-one:camera'],owner=false){return {type:'state',room:{participants,switcher:{generation:3}},subscriptions:sources,return_audio_owner:owner};}
function viewState(participants=[person()],sources=['guest:guest-one:camera']){return {type:'state',room:{room_id:'room-one',active:true,participants},subscriptions:sources};}
function guestState(sources=['camera','screen','audio'],returnAudio=false,state='waiting'){
  return {type:'state',participant:person('guest-one',state),subscriptions:[{peer_id:'receiver',role:'producer',sources,return_audio:returnAudio}],on_air_sources:[]};
}
async function connect(f,engine,role){const ready=engine.connect();const ws=f.sockets.at(-1);ws.open();ws.message({type:'hello',peer_id:'self',role,ice_servers:[]});await ready;return ws;}
function offer(ws,from='publisher',id='guest-one'){ws.message({type:'signal',from,participant_id:id,role:'guest',kind:'offer',data:{type:'offer',sdp:'v=0\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n'}});}

test('local producer screen publishes one video transceiver without guest authentication or audio',async()=>{
  const f=fixture(),publisher=f.api.createProducerScreenPublisher(),screen=new f.Track('video');
  assert.throws(()=>publisher.setTracks({microphone:new f.Track('audio')}),/producer_screen_video_only/);
  publisher.setTracks({screen});assert.equal(f.sockets.length,0);
  const ws=await connect(f,publisher,'producer-screen');assert.match(ws.url,/producer-screen-socket$/);
  assert.equal(ws.sent.some(message=>message.type==='authenticate'),false);
  assert.deepEqual(ws.sent.find(message=>message.type==='media').media,{screen:true});
  ws.message({type:'state',source_id:'producer:screen:'+'a'.repeat(32),subscriptions:[{peer_id:'output',role:'output',sources:['screen'],return_audio:false}]});await settle();
  const pc=f.connections[0];assert.deepEqual(Array.from(pc.transceivers,t=>t.direction),['inactive','inactive','sendonly','inactive']);
  assert.deepEqual(Array.from(pc.transceivers,t=>t.sender.track),[null,null,screen,null]);
  for(const index of [0,1,2,3])assert.equal(pc.emitTrack(index).readyState,'ended');
  ws.dropped();await f.tick(10000);assert.equal(f.sockets.length,1);assert.equal(screen.stops,0);publisher.close();
});

test('producer screen receiver requires explicit subscription and refuses all audio and camera tracks',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output'),source='producer:screen:'+'a'.repeat(32);
  const message={type:'signal',from:'screen-publisher',source_id:source,role:'producer-screen',kind:'offer',data:{type:'offer',sdp:'v=0\nm=video 9 UDP/TLS/RTP/SAVPF 96\n'}};
  const snapshot={...receiverState([],[]),room:{participants:[],producer_sources:[{id:source,available:true}],switcher:{generation:3}}};
  ws.message(snapshot);ws.message(message);await settle();assert.equal(f.connections.length,0);
  ws.message({...snapshot,subscriptions:[source]});await settle();
  const pc=f.connections[0];assert.deepEqual(Array.from(pc.transceivers,t=>t.direction),['inactive','inactive','recvonly','inactive']);
  for(const index of [0,1,3])assert.equal(pc.emitTrack(index).readyState,'ended');
  const screen=pc.emitTrack(2);assert.equal(receiver.tracks(source).screen,screen);assert.equal(receiver.tracks(source).microphone,null);
  receiver.sendReady([source],{generation:3,audioBlocked:false,rendered:true});assert.deepEqual(ws.sent.at(-1).sources,[source]);
  ws.message({...snapshot,subscriptions:[source],room:{...snapshot.room,producer_sources:[]}});assert.ok(pc.closed);assert.equal(receiver.tracks(source).screen,null);
  receiver.close();
});

test('output playback health is typed and bound to the current signaling generation',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output');
  ws.message(receiverState());
  receiver.sendReady([], {generation:3,audioBlocked:true,rendered:false});
  assert.deepEqual(ws.sent.at(-1).playback,{generation:3,audio_blocked:true,rendered:false});
  for(const invalid of [{generation:2,audioBlocked:false,rendered:true},{generation:3,audioBlocked:'false',rendered:true},{generation:3,audioBlocked:false}]){
    receiver.sendReady([],invalid);assert.equal('playback' in ws.sent.at(-1),false);
  }
  receiver.close();
});

test('layer output receipts carry distinct staged Preview and rendered Program composition IDs',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output');ws.message(receiverState());
  receiver.sendReady([], {generation:3,audioBlocked:false,rendered:true,compositionId:'a'.repeat(64),previewCompositionId:'b'.repeat(64)});
  assert.equal(ws.sent.at(-1).playback.composition_id,'a'.repeat(64));assert.equal(ws.sent.at(-1).preview_composition_id,'b'.repeat(64));
  receiver.sendReady([], {generation:3,audioBlocked:false,rendered:true,compositionId:'invalid',previewCompositionId:'not-a-receipt'});
  assert.equal('composition_id' in ws.sent.at(-1).playback,false);assert.equal('preview_composition_id' in ws.sent.at(-1),false);receiver.close();
});

test('publisher requires explicit connection/caller tracks and fixed transceiver order',async()=>{
  const f=fixture(),publisher=f.api.createPublisher({token:'a'.repeat(64)});
  const mic=new f.Track('audio'),camera=new f.Track('video'),screen=new f.Track('video'),game=new f.Track('audio');
  publisher.setTracks({microphone:mic,camera,screen,screen_audio:game});assert.equal(f.sockets.length,0);
  const ws=await connect(f,publisher,'guest');assert.equal(ws.url,'wss://fixture.invalid/guest/ws');
  assert.deepEqual(ws.sent[0],{type:'authenticate',token:'a'.repeat(64)});
  ws.message(guestState(['camera']));await settle();
  const pc=f.connections[0];assert.deepEqual(Array.from(pc.transceivers,t=>t.direction),['sendrecv','sendonly','sendonly','sendonly']);
  assert.deepEqual(Array.from(pc.transceivers,t=>t.sender.track),[mic,camera,null,null]);
  assert.ok(ws.sent.some(message=>message.kind==='offer'));
  publisher.setTracks({camera:null,screen_audio:null});await settle();assert.equal(pc.transceivers[1].sender.track,null);
  publisher.close();assert.equal(mic.stops,0);assert.equal(camera.stops,0);assert.equal(screen.stops,0);assert.ok(pc.closed);
});

test('publisher permission changes detach senders and waiting guests receive no return audio',async()=>{
  const f=fixture(),returns=[],publisher=f.api.createPublisher({token:'a'.repeat(64),onReturnAudio:stream=>returns.push(stream)});
  publisher.setTracks({microphone:new f.Track('audio'),camera:new f.Track('video'),screen:new f.Track('video'),screen_audio:new f.Track('audio')});
  const ws=await connect(f,publisher,'guest');ws.message(guestState());await settle();
  const pc=f.connections[0],remote=pc.emitTrack(0);assert.equal(returns.filter(Boolean).length,0);
  ws.message(guestState(['camera','screen','audio'],true,'admitted'));await settle();assert.equal(returns.at(-1).getAudioTracks()[0],remote);
  ws.message(guestState(['camera'],false,'waiting'));assert.equal(returns.at(-1),null);await settle();
  assert.equal(pc.transceivers[2].sender.track,null);assert.equal(pc.transceivers[3].sender.track,null);
  publisher.close();
});

test('guest view authenticates separately and closing it preserves guest publication',async()=>{
  const f=fixture(),token='a'.repeat(64);
  assert.throws(()=>f.api.createReceiver({role:'guest-view'}),/invalid_guest_session/);
  const publisher=f.api.createPublisher({token}),camera=new f.Track('video');publisher.setTracks({camera});
  const publication=await connect(f,publisher,'guest');publication.message(guestState());await settle();
  const publisherPeer=f.connections[0],receiver=f.api.createReceiver({role:'guest-view',token});
  const ws=await connect(f,receiver,'guest-view');assert.equal(ws.url,'wss://fixture.invalid/guest/view/ws');
  assert.deepEqual(ws.sent[0],{type:'authenticate',token});assert.equal(ws.sent.some(message=>message.type==='media'),false);
  ws.message(viewState());offer(ws);await settle();const viewerPeer=f.connections.at(-1);viewerPeer.emitTrack(1);
  assert.equal(receiver.sendReady(['guest:guest-one:camera']),false);assert.equal(receiver.rendered(3),false);
  assert.equal(await receiver.setReturnStream('guest-one',new f.Stream([new f.Track('audio')])),false);
  receiver.close();assert.ok(ws.closed);assert.ok(viewerPeer.closed);assert.ok(!publication.closed);assert.ok(!publisherPeer.closed);
  assert.equal(publisherPeer.transceivers[1].sender.track,camera);assert.equal(camera.stops,0);publisher.close();assert.equal(f.timers.size,0);
});

test('guest view rejects audio and screen tracks while retaining admitted cameras only',async()=>{
  const f=fixture(),changes=[],receiver=f.api.createReceiver({role:'guest-view',token:'a'.repeat(64),onTracks:(id,tracks)=>changes.push({id,tracks})});
  const ws=await connect(f,receiver,'guest-view');ws.message(viewState());offer(ws);await settle();
  const pc=f.connections[0],mic=pc.emitTrack(0),camera=pc.emitTrack(1),screen=pc.emitTrack(2),game=pc.emitTrack(3);
  assert.deepEqual(Array.from(pc.transceivers,t=>t.direction),['inactive','recvonly','inactive','inactive']);
  assert.ok(pc.transceivers.every(t=>t.sender.track===null));assert.equal(receiver.tracks('guest-one').camera,camera);
  for(const track of [mic,screen,game])assert.equal(track.readyState,'ended');
  for(const key of ['microphone','screen','screen_audio'])assert.equal(changes.at(-1).tracks[key],null);
  ws.message(viewState([person('guest-one','waiting')]));assert.ok(pc.closed);assert.equal(camera.readyState,'ended');
  assert.ok(Object.values(changes.at(-1).tracks).every(track=>track===null));offer(ws);await settle();assert.equal(f.connections.length,1);
  ws.message(viewState([{...person(),expired:true}]));offer(ws);await settle();assert.equal(f.connections.length,1);
  ws.message(viewState());offer(ws);await settle();assert.equal(f.connections.length,2);
  ws.message(viewState([person()],[]));assert.ok(f.connections[1].closed);offer(ws);await settle();assert.equal(f.connections.length,2);
  receiver.close();
});

test('guest view closes on invitation expiry and rejects non-camera subscriptions',async()=>{
  for(const subscriptions of [['guest:guest-one:audio'],['guest:guest-one:screen']]){
    const f=fixture(),errors=[],receiver=f.api.createReceiver({role:'guest-view',token:'a'.repeat(64),onError:error=>errors.push(error)});
    const ws=await connect(f,receiver,'guest-view');ws.message(viewState([person()],subscriptions));
    assert.ok(ws.closed);assert.equal(errors.at(-1).reason,'invalid_signaling_response');receiver.close();
  }
  const f=fixture(),receiver=f.api.createReceiver({role:'guest-view',token:'a'.repeat(64)}),pending=receiver.connect();
  const rejected=assert.rejects(pending,/guest_access_ended/);f.sockets[0].open();f.sockets[0].dropped(1008);await rejected;
  await f.tick(60000);assert.equal(f.sockets.length,1);receiver.close();assert.equal(f.timers.size,0);
});

test('publishers send guest views only admitted cameras and preserve producer audio',async()=>{
  const f=fixture(),publisher=f.api.createPublisher({token:'a'.repeat(64)});
  const microphone=new f.Track('audio'),camera=new f.Track('video'),screen=new f.Track('video'),screen_audio=new f.Track('audio');
  publisher.setTracks({microphone,camera,screen,screen_audio});const ws=await connect(f,publisher,'guest');
  const state=guestState(['camera','screen','audio'],true,'admitted');state.subscriptions.push({peer_id:'viewer',role:'guest-view',sources:['camera']});
  ws.message(state);await settle();const producer=f.connections[0],viewer=f.connections[1];
  assert.deepEqual(Array.from(producer.transceivers,t=>t.sender.track),[microphone,camera,screen,screen_audio]);
  assert.deepEqual(Array.from(viewer.transceivers,t=>t.sender.track),[null,camera,null,null]);
  assert.deepEqual(Array.from(viewer.transceivers,t=>t.direction),['inactive','sendonly','inactive','inactive']);
  assert.equal(viewer.emitTrack(0).readyState,'ended');
  ws.message({...state,participant:person('guest-one','waiting')});await settle();assert.equal(viewer.transceivers[1].sender.track,null);
  ws.message({...state,subscriptions:[state.subscriptions[0]]});await settle();assert.ok(viewer.closed);assert.ok(!producer.closed);
  assert.equal(producer.transceivers[0].sender.track,microphone);publisher.close();
});

test('publisher subscriber limits allow twelve guest views plus five production receivers',async()=>{
  const f=fixture(),publisher=f.api.createPublisher({token:'a'.repeat(64)}),ws=await connect(f,publisher,'guest');
  const state=guestState(['camera'],false,'admitted');
  state.subscriptions=Array.from({length:17},(_,index)=>({peer_id:'recipient-'+index,role:index<12?'guest-view':'producer',sources:['camera']}));
  ws.message(state);await settle();assert.equal(f.connections.length,17);assert.ok(!ws.closed);
  ws.message({...state,subscriptions:state.subscriptions.map((sub,index)=>({...sub,role:index<13?'guest-view':'producer'}))});
  assert.ok(ws.closed);assert.ok(f.connections.every(pc=>pc.closed));publisher.close();
});

test('receiver filters unrequested tracks and never reports readiness automatically',async()=>{
  const f=fixture(),changes=[],receiver=f.api.createReceiver({role:'output',onTracks:(id,tracks)=>changes.push({id,tracks})});
  const ws=await connect(f,receiver,'output');ws.message(receiverState());offer(ws);await settle();
  const pc=f.connections[0];const mic=pc.emitTrack(0),camera=pc.emitTrack(1),screen=pc.emitTrack(2),game=pc.emitTrack(3);
  assert.equal(receiver.tracks('guest-one').microphone,mic);assert.equal(receiver.tracks('guest-one').camera,camera);
  assert.equal(receiver.tracks('guest-one').screen,null);assert.equal(receiver.tracks('guest-one').screen_audio,null);
  assert.equal(ws.sent.filter(message=>message.type==='ready').length,0);
  receiver.sendReady(['guest:guest-one:camera','guest:guest-one:screen']);assert.deepEqual(ws.sent.at(-1).sources,['guest:guest-one:camera']);
  assert.equal(receiver.rendered(2),false);assert.equal(receiver.rendered(3),true);
  assert.ok(pc.transceivers.every(transceiver=>transceiver.direction==='recvonly'));
  ws.message(receiverState([person()],['guest:guest-one:screen']));
  assert.equal(receiver.tracks('guest-one').camera,null);assert.equal(receiver.tracks('guest-one').screen,screen);assert.equal(receiver.tracks('guest-one').screen_audio,game);
  screen.muted=true;screen.onmute();assert.equal(changes.at(-1).tracks.screen,null);
  screen.muted=false;screen.onunmute();assert.equal(changes.at(-1).tracks.screen,screen);
  mic.stop();assert.equal(changes.at(-1).tracks.microphone,null);
  ws.message(receiverState([],[]));assert.ok(pc.closed);assert.ok(Object.values(changes.at(-1).tracks).every(track=>track===null));receiver.close();
});

test('ICE before remote description is queued and bounded; stale async work cannot answer after close',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output');
  ws.message(receiverState());
  ws.message({type:'signal',from:'publisher',participant_id:'guest-one',role:'guest',kind:'ice',data:{candidate:'fixture',sdpMid:'0',sdpMLineIndex:0}});
  await settle();const pc=f.connections[0];assert.equal(pc.ice.length,0);
  offer(ws);await settle();assert.equal(pc.ice.length,1);
  receiver.close();
  const second=f.api.createReceiver({role:'output'}),other=await connect(f,second,'output');other.message(receiverState());
  other.message({type:'signal',from:'publisher',participant_id:'guest-one',role:'guest',kind:'ice',data:{candidate:'fixture'}});await settle();
  const delayed=f.connections.at(-1);let resume;delayed.delayRemote=new Promise(resolve=>resume=resolve);
  offer(other);await settle();second.close();resume();await settle();assert.equal(other.sent.filter(message=>message.kind==='answer').length,0);
});

test('producer return audio requires admission and server return ownership',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'producer'}),ws=await connect(f,receiver,'producer');
  const stream=new f.Stream([new f.Track('audio')]);receiver.setReturnStream('guest-one',stream);
  ws.message(receiverState([person('guest-one','waiting')],['guest:guest-one:camera'],true));offer(ws);await settle();
  const pc=f.connections[0];assert.equal(pc.transceivers[0].sender.track,null);
  ws.message(receiverState([person()],['guest:guest-one:camera'],true));await settle();assert.equal(pc.transceivers[0].sender.track,stream.getAudioTracks()[0]);
  ws.message(receiverState([person()],['guest:guest-one:camera'],false));assert.equal(pc.transceivers[0].sender.track,null);
  receiver.close();assert.equal(stream.getAudioTracks()[0].stops,0);
});

test('offer arriving before state waits for source authorization; excessive early ICE closes only that peer',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output');
  offer(ws);await settle();assert.equal(f.connections.length,0);
  ws.message(receiverState());await settle();assert.equal(f.connections.length,1);assert.ok(ws.sent.some(message=>message.kind==='answer'));
  receiver.close();
  const other=f.api.createReceiver({role:'output'}),second=await connect(f,other,'output');second.message(receiverState());
  for(let n=0;n<65;n++)second.message({type:'signal',from:'publisher',participant_id:'guest-one',role:'guest',kind:'ice',data:{candidate:'fixture-'+n}});
  await settle();assert.ok(!second.closed);assert.ok(f.connections.at(-1).closed);other.close();
});

test('a rejected guest session is terminal and does not consume reconnect attempts',async()=>{
  const f=fixture(),publisher=f.api.createPublisher({token:'a'.repeat(64)}),pending=publisher.connect();
  const rejected=assert.rejects(pending,/guest_access_ended/);f.sockets[0].open();f.sockets[0].dropped(1008);await rejected;
  await f.tick(60000);assert.equal(f.sockets.length,1);publisher.close();
});

test('state stall closes media, reconnects a bounded number of times and ignores old socket messages',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output');ws.message(receiverState());offer(ws);await settle();
  const oldMessage=ws.onmessage,first=f.connections[0];
  await f.tick(8000);assert.ok(first.closed);assert.ok(ws.closed);
  await f.tick(1000);assert.equal(f.sockets.length,2);
  oldMessage({data:JSON.stringify(receiverState())});assert.equal(f.connections.length,1);
  for(let n=0;n<4;n++){const current=f.sockets.at(-1);current.open();current.dropped();await f.tick(5000);}
  assert.ok(f.sockets.length<=4);receiver.close();assert.equal(f.timers.size,0);
});

test('extra data channels are closed and never passed to application code',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output');ws.message(receiverState());offer(ws);await settle();
  let closed=false;f.connections[0].ondatachannel({channel:{close(){closed=true;}}});assert.ok(closed);assert.ok(ws.closed);receiver.close();
});

test('conference mix-minus excludes each guest and waiting guests; monitoring is opt-in',async()=>{
  const f=fixture(),returns=new Map(),nodes=[],observers=new Set();
  const consumers=[];f.host.document={body:{append(){}},createElement(name){assert.equal(name,'audio');const audio={srcObject:null,plays:0,paused:false,removed:false,setAttribute(){},play(){this.plays++;return Promise.resolve();},pause(){this.paused=true;},remove(){this.removed=true;}};consumers.push(audio);return audio;}};
  const a=person('a'),b=person('b'),waiting=person('w','waiting');
  let state=receiverState([a,b,waiting],[],true);
  const tracks={a:{microphone:new f.Track('audio','a-mic'),screen_audio:null},b:{microphone:new f.Track('audio','b-mic'),screen_audio:new f.Track('audio','b-game')},w:{microphone:new f.Track('audio','waiting-mic')}};
  const receiver={state:()=>state,tracks:id=>tracks[id],setReturnStream:(id,stream)=>returns.set(id,stream),subscribe:fn=>{observers.add(fn);return()=>observers.delete(fn);}};
  const node=(kind,stream)=>{const item={kind,stream,connections:[],connect(target){this.connections.push(target);},disconnect(){this.connections=[];}};nodes.push(item);return item;};
  const context={state:'running',destination:{id:'speaker'},createGain(){const value=node('gain');value.gain={value:0};return value;},createMediaStreamDestination(){return node('destination',new f.Stream([new f.Track('audio')]));},createMediaStreamSource(stream){return node('source',stream);}};
  const helper=f.api.createConferenceAudio(receiver),hostMic=new f.Track('audio','host-mic');helper.setLocalStream(new f.Stream([hostMic]));helper.sync(state.room.participants);
  assert.equal(nodes.length,0);assert.equal(consumers.length,0);await helper.start(context);
  assert.equal(consumers.length,3);assert.ok(consumers.every(audio=>audio.muted===true&&audio.hidden===true&&audio.plays===1));
  assert.ok(consumers.every(audio=>!['host-mic','waiting-mic'].includes(audio.srcObject.getTracks()[0].id)));
  const destinations=nodes.filter(item=>item.kind==='destination');assert.equal(destinations.length,2);assert.equal(returns.get('w'),undefined);
  const aSource=nodes.find(item=>item.kind==='source'&&item.stream.getTracks()[0].id==='a-mic');
  assert.equal(aSource.connections.length,1);assert.equal(aSource.connections[0].stream,returns.get('b'));
  assert.ok(!nodes.some(item=>item.kind==='source'&&item.stream.getTracks()[0].id==='waiting-mic'));
  assert.ok(nodes.every(item=>!item.connections.includes(context.destination)));
  helper.setMonitor(true);assert.ok(nodes.some(item=>item.kind==='gain'&&item.connections.includes(context.destination)));
  state=null;for(const callback of observers)callback({type:'state',state:null});assert.equal(returns.get('a'),null);assert.equal(returns.get('b'),null);
  assert.ok(consumers.every(audio=>audio.paused&&audio.removed&&audio.srcObject===null));
  helper.close();assert.equal(hostMic.stops,0);assert.equal(tracks.a.microphone.stops,0);
});


test('one failed recipient preserves healthy media and signaling with bounded per-peer retries',async()=>{
  const f=fixture(),events=[],errors=[],publisher=f.api.createPublisher({token:'a'.repeat(64),onConnection:e=>events.push(e),onError:e=>errors.push(e)});
  const mic=new f.Track('audio');publisher.setTracks({microphone:mic});const ws=await connect(f,publisher,'guest');
  const state=guestState(['audio'],false,'admitted');state.subscriptions=[{peer_id:'healthy',role:'output',sources:['audio']},{peer_id:'broken',role:'producer',sources:['audio']}];
  ws.message(state);await settle();const healthy=f.connections[0],broken=f.connections[1],stale=broken.onconnectionstatechange;
  healthy.connectionState='connected';healthy.onconnectionstatechange();
  for(const [index,delay] of [[1,1000],[2,2000],[3,4000]]){
    const pc=f.connections.at(-1);pc.connectionState='failed';pc.onconnectionstatechange();await settle();
    assert.equal(events.at(-1).state,'peer_reconnecting');assert.equal(events.at(-1).scope,'peer');assert.equal(events.at(-1).attempt,index);assert.equal(events.at(-1).retry_in_ms,delay);
    assert.ok(!healthy.closed);assert.ok(!ws.closed);assert.equal(healthy.transceivers[0].sender.track,mic);
    for(let n=0;n<delay;n+=500){ws.message(state);await f.tick(500);}
  }
  const final=f.connections.at(-1);final.connectionState='failed';final.onconnectionstatechange();assert.equal(events.at(-1).state,'peer_failed');assert.equal(events.at(-1).attempt,3);
  const count=f.connections.length,before=events.length;stale();assert.equal(events.length,before,'old peer callbacks cannot alter current recovery');
  for(let n=0;n<10;n++){ws.message(state);await f.tick(500);}assert.equal(f.connections.length,count);assert.ok(!ws.closed);assert.ok(!healthy.closed);assert.equal(errors.length,0);
  publisher.close();assert.equal(f.timers.size,0);assert.equal(mic.stops,0);
});

test('removing a recipient cancels its recovery and a later subscription may start afresh',async()=>{
  const f=fixture(),events=[],publisher=f.api.createPublisher({token:'a'.repeat(64),onConnection:e=>events.push(e)}),ws=await connect(f,publisher,'guest');
  const state=guestState();ws.message(state);await settle();f.connections[0].connectionState='failed';f.connections[0].onconnectionstatechange();
  ws.message({...state,subscriptions:[]});await f.tick(1000);assert.equal(f.connections.length,1);assert.ok(events.some(e=>e.state==='peer_removed'&&e.peer_id==='receiver'));
  ws.message(state);await settle();assert.equal(f.connections.length,2);publisher.close();assert.equal(f.timers.size,0);
});

test('receiver negotiation failure is isolated and a new authorized offer can recover that peer',async()=>{
  const f=fixture(),events=[],errors=[],receiver=f.api.createReceiver({role:'producer',onConnection:e=>events.push(e),onError:e=>errors.push(e)}),ws=await connect(f,receiver,'producer');
  const state=receiverState([person('healthy'),person('broken')],['guest:healthy:audio','guest:broken:audio']);ws.message(state);offer(ws,'healthy-publisher','healthy');await settle();
  const healthy=f.connections[0];healthy.emitTrack(0);offer(ws,'broken-publisher','broken');f.connections[1].createAnswer=async()=>{throw Error('fixture negotiation error');};await settle();
  assert.ok(!ws.closed);assert.ok(!healthy.closed);assert.equal(events.at(-1).state,'peer_reconnecting');assert.equal(events.at(-1).reason,'media_negotiation_failed');assert.equal(errors.length,0);
  offer(ws,'broken-publisher','broken');await settle();assert.equal(f.connections.length,3);assert.ok(ws.sent.some(m=>m.kind==='answer'&&m.to==='broken-publisher'));
  receiver.close();assert.equal(f.timers.size,0);
});


test('new ICE arriving before a replacement offer waits for matching remote credentials',async()=>{
  const f=fixture(),events=[],receiver=f.api.createReceiver({role:'producer',onConnection:e=>events.push(e)}),ws=await connect(f,receiver,'producer');ws.message(receiverState());
  const sendOffer=fragment=>ws.message({type:'signal',from:'publisher',participant_id:'guest-one',role:'guest',kind:'offer',data:{type:'offer',sdp:'v=0\na=ice-ufrag:'+fragment+'\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n'}});
  sendOffer('old');await settle();const pc=f.connections[0];pc.addIceCandidate=async value=>{if(!pc.remoteDescription.sdp.includes('ice-ufrag:'+value.usernameFragment))throw Error('credential mismatch');pc.ice.push(value);};
  ws.message({type:'signal',from:'publisher',participant_id:'guest-one',role:'guest',kind:'ice',data:{candidate:'fixture-new',usernameFragment:'new',sdpMLineIndex:0}});sendOffer('new');await settle();
  assert.ok(!pc.closed);assert.equal(pc.ice.length,1);assert.equal(pc.ice[0].usernameFragment,'new');assert.equal(ws.sent.filter(m=>m.kind==='answer').length,2);assert.ok(!events.some(e=>e.state==='peer_reconnecting'));receiver.close();
});

test('a rejoined publisher replaces its obsolete receiver record and old ICE is not applied to new credentials',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'producer'}),ws=await connect(f,receiver,'producer');ws.message(receiverState());offer(ws,'old-publisher');await settle();
  const old=f.connections[0],oldTrack=old.emitTrack(0);assert.equal(receiver.tracks('guest-one').microphone,oldTrack);
  ws.message({type:'signal',from:'new-publisher',participant_id:'guest-one',role:'guest',kind:'ice',data:{candidate:'stale-fixture',usernameFragment:'old'}});
  ws.message({type:'signal',from:'new-publisher',participant_id:'guest-one',role:'guest',kind:'offer',data:{type:'offer',sdp:'v=0\na=ice-ufrag:new\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n'}});await settle();
  const current=f.connections[1],newTrack=current.emitTrack(0);assert.ok(old.closed);assert.equal(oldTrack.readyState,'ended');assert.equal(receiver.tracks('guest-one').microphone,newTrack);assert.equal(current.ice.length,0);receiver.close();
});


test('normal unsubscribe clears a transient peer warning without needing a retry record',async()=>{
  for(const role of ['guest','producer']){
    const f=fixture(),events=[],engine=role==='guest'?f.api.createPublisher({token:'a'.repeat(64),onConnection:e=>events.push(e)}):f.api.createReceiver({role,onConnection:e=>events.push(e)}),ws=await connect(f,engine,role);
    const state=role==='guest'?guestState():receiverState();ws.message(state);if(role!=='guest')offer(ws);await settle();
    const pc=f.connections[0];pc.connectionState='disconnected';pc.onconnectionstatechange();ws.message({...state,subscriptions:[]});await settle();
    assert.ok(pc.closed);assert.deepEqual(events.filter(e=>e.scope==='peer').map(e=>e.state),['peer_disconnected','peer_removed']);assert.ok(!ws.closed);engine.close();
  }
});
