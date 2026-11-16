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
function guestState(sources=['camera','screen','audio'],returnAudio=false,state='waiting'){
  return {type:'state',participant:person('guest-one',state),subscriptions:[{peer_id:'receiver',role:'producer',sources,return_audio:returnAudio}],on_air_sources:[]};
}
async function connect(f,engine,role){const ready=engine.connect();const ws=f.sockets.at(-1);ws.open();ws.message({type:'hello',peer_id:'self',role,ice_servers:[]});await ready;return ws;}
function offer(ws,from='publisher',id='guest-one'){ws.message({type:'signal',from,participant_id:id,role:'guest',kind:'offer',data:{type:'offer',sdp:'v=0\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n'}});}

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

test('offer arriving before state waits for source authorization; excessive early ICE closes transport',async()=>{
  const f=fixture(),receiver=f.api.createReceiver({role:'output'}),ws=await connect(f,receiver,'output');
  offer(ws);await settle();assert.equal(f.connections.length,0);
  ws.message(receiverState());await settle();assert.equal(f.connections.length,1);assert.ok(ws.sent.some(message=>message.kind==='answer'));
  receiver.close();
  const other=f.api.createReceiver({role:'output'}),second=await connect(f,other,'output');second.message(receiverState());
  for(let n=0;n<65;n++)second.message({type:'signal',from:'publisher',participant_id:'guest-one',role:'guest',kind:'ice',data:{candidate:'fixture-'+n}});
  await settle();assert.ok(second.closed);other.close();
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
