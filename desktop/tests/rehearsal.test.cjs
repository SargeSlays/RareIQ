'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {NativeBroadcast}=require('../broadcast.cjs'),{RehearsalCoordinator,sanitizeSourceCallbackCode}=require('../rehearsal.cjs');
const gen='a'.repeat(32),otherGen='b'.repeat(32),deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{for(let index=0;index<200;index++)await Promise.resolve();};
const room=(mode='production',extra={})=>({mode,active:mode!=='production',publishing_allowed:mode==='production',revision:mode==='production'?0:2,generation:gen,checks:[{id:'video',label:'Video and layouts',status:'not_tested'}],publishing_work_pending:false,...extra});
function fixture({vod=false,mode='rehearsal'}={}){
  const f={calls:[],groups:[],taps:[],monitorCalls:[],lookups:0,confirmations:0,now:0,room:room(mode),captureState:{peerId:'output-one',rendered:true,browserReviewOpen:false,audioBlocked:false,audioReady:true,prepared:true,generation:3},preflight:{ready:true,generation:3,blockers:[]}};
  f.profile={id:'saved',name:'Saved',format:'hd',fps:30,videoBitrateKbps:4000,codec:'libx264',keyframeSeconds:2,audioBitrateKbps:192,twitchVod:vod,audioRouting:{}};
  f.capture={status:()=>({...f.captureState}),prepare:async()=>{},review:async()=>{},close:async()=>{f.captureClosed=true;},waitForRehearsal:async value=>{f.waitedGeneration=value;},updateAudioRouting:async value=>({requestId:value.requestId,applied:true}),startCapture:async(video,audio)=>{f.taps.push({video,audio});},stopCapture:async()=>{f.captureStops=(f.captureStops||0)+1;},setMonitor:async bus=>{f.monitorCalls.push(bus);return {ok:true,monitor:{bus,available:true}};}};
  f.request=async(url,body)=>{
    f.calls.push({url,body});
    if(url==='/api/production/rehearsal')return {ok:true,room:structuredClone(f.room)};
    if(url.startsWith('/api/production/native-preflight'))return {preflight:structuredClone(f.preflight)};
    if(url==='/api/desktop/encoding-status'){if(body.active&&f.waitClaim)await f.waitClaim.promise;if(!body.active&&f.failClear)throw Error('private status path');return {ok:true};}
    if(url.startsWith('/api/production/rehearsal/')){const action=url.split('/').at(-1);if(f.waitMutation)await f.waitMutation.promise;f.room=room(action==='enter'?'rehearsal':action==='mark'?f.room.mode:'production',{revision:f.room.revision+1,generation:f.room.generation});return {ok:true,room:structuredClone(f.room)};}
    throw Error('unexpected_test_request');
  };
  f.createGroup=notify=>{
    const group={running:false,stops:0,video:0,audio:0,vod:0,counts:{},status(){return {running:this.running,...this.counts};},createTarget(id,observe){assert.equal(id,'rehearsal-local');this.observe=observe;return {status:()=>this.status()};},async start(value){this.config=value;this.running=true;if(f.waitWorker)await f.waitWorker.promise;},async stop(){this.stops++;if(!f.holdWorker)this.running=false;},sendVideo(){this.video++;return !f.backpressure;},sendAudio(){this.audio++;return true;},sendVodAudio(){this.vod++;return true;},emit(value){Object.assign(this.counts,value);if(value.running!==undefined)this.running=value.running;notify({...this.status(),...value});}};f.groups.push(group);return group;
  };
  f.broadcast=new NativeBroadcast({destinations:{getPrivateDestination:async()=>{f.lookups++;return {serverUrl:'rtmps://provider.net/live',streamKey:'synthetic'};}},outputProfiles:{getProfile:async()=>structuredClone(f.profile)},createCapture:()=>f.capture,createEncoder:()=>{throw Error('production_encoder_must_not_start');},request:(...args)=>f.request(...args),identity:{pid:1,server_session_id:'synthetic'},ownerPid:2,confirm:async()=>{f.confirmations++;return true;}});
  f.coordinator=new RehearsalCoordinator({broadcast:f.broadcast,createEncoderGroup:notify=>f.createGroup(notify),request:(...args)=>f.request(...args),identity:{pid:1,server_session_id:'synthetic'},ownerPid:2,clock:()=>f.now});
  f.broadcast.canPublish=()=>f.coordinator.canPublish();f.prepare=()=>f.broadcast.prepare({profileId:'saved'});f.start=(extra={})=>f.coordinator.start({requestId:'local-start',revision:f.room.revision,generation:f.room.generation,profileId:'saved',...extra});return f;
}

test('room status starts fail closed and a fresh confirmed policy blocks all destination lookup',async()=>{
  const f=fixture();assert.equal(f.coordinator.publishingAllowed(),false);await f.prepare();await f.coordinator.refresh();assert.equal(f.coordinator.status().room.mode,'rehearsal');
  await assert.rejects(f.broadcast.start({destinationId:'private'}),/rehearsal_active/);assert.equal(f.lookups,0);assert.equal(f.confirmations,0);assert.equal(f.groups.length,0);
  f.room=room();assert.equal(await f.coordinator.canPublish(),true);f.request=async()=>{throw Error('private backend details');};await assert.rejects(f.coordinator.canPublish(),/rehearsal_status_unavailable/);assert.equal(f.coordinator.publishingAllowed(),false);
});

test('enter, marks, exit and recovery only mutate the room with exact bounded backend payloads',async()=>{
  const f=fixture({mode:'production'});await f.coordinator.enter({requestId:'enter',revision:0});assert.equal(f.groups.length,0);assert.deepEqual(f.calls[0],{url:'/api/production/rehearsal/enter',body:{request_id:'enter',expected_revision:0}});
  await f.coordinator.mark({requestId:'mark',revision:1,generation:gen,checkId:'video',status:'passed'});assert.deepEqual(f.calls.at(-1).body,{request_id:'mark',expected_revision:1,generation:gen,check_id:'video',status:'passed'});
  await f.coordinator.exit({requestId:'exit',revision:2,generation:gen});assert.equal(f.coordinator.status().room.mode,'production');
  f.room=room('recovery_required');await f.coordinator.recover({requestId:'recover',revision:2,generation:gen});assert.equal(f.calls.at(-1).body.confirm_recovery,true);assert.equal(f.groups.length,0);assert.equal(f.lookups,0);
  for(const method of ['enter','exit','recover','mark'])await assert.rejects(f.coordinator[method]({requestId:'bad',revision:0,destination:{secret:'no'}}),/invalid_rehearsal_command/);
});

test('local Start uses the prepared live audio session and one fixed discard target without touching production ownership',async()=>{
  const f=fixture({vod:true});await f.prepare();const audio=f.broadcast.audioSession,profile=f.broadcast.outputProfile;const started=await f.start();assert.equal(started.local.running,true);assert.equal(f.broadcast.phase,'rehearsing');assert.equal(f.broadcast.active(),true);
  assert.equal(f.broadcast.encoderGroup,null);assert.equal(f.broadcast.ownsEncoding,false);assert.equal(f.broadcast.audioSession,audio);assert.equal(f.broadcast.outputProfile,profile);assert.equal(f.lookups,0);assert.equal(f.confirmations,0);
  const group=f.groups[0];assert.deepEqual(group.config,{width:1280,height:720,fps:30,bitrate:4000000,codec:'libx264',keyframeSeconds:2,audioBitrateKbps:192,twitchVod:true,rehearsal:true,targets:[{id:'rehearsal-local',rehearsal:true,twitchVod:true}]});
  const reservation=f.calls.find(call=>call.body?.active===true);assert.deepEqual(reservation.body,{pid:1,server_session_id:'synthetic',active:true,owner_pid:2,mode:'rehearsal',rehearsal_generation:gen});
  f.taps[0].video(Buffer.alloc(4),0);f.taps[0].audio(Buffer.alloc(8),0,Buffer.alloc(8));assert.equal(group.video,1);assert.equal(group.audio,1);assert.equal(group.vod,1);
  group.emit({state:'active',videoFrames:8,audioSamples:9,vodAudioSamples:7,bytesMuxed:20,codec:'libx264',privatePayload:'never'});assert.equal(f.coordinator.status().local.frames,8);assert.doesNotMatch(JSON.stringify(f.coordinator.status()),/privatePayload|never/);
  const mix=audio.status();await f.broadcast.setLiveAudio({outputId:mix.outputId,expectedRevision:0,requestId:'gain',audioRouting:{'voice:default':{live:true,vod:true,liveGainDb:3}}});assert.equal(audio.status().revision,1);assert.equal(group.stops,0);
  await f.coordinator.stop();assert.equal(f.coordinator.status().room.mode,'rehearsal');assert.equal(f.broadcast.audioSession,audio);assert.equal(f.broadcast.phase,'prepared');assert.equal(f.coordinator.active(),false);assert.deepEqual(f.calls.at(-1).body,{pid:1,server_session_id:'synthetic',active:false,owner_pid:2,mode:'rehearsal',rehearsal_generation:gen});
});

test('wrong room, stale revision/generation, unprepared profile and unknown options cannot create an encoder or claim',async()=>{
  for(const change of ['production','revision','generation','missing_prepare','profile','not_ready','mix','destination']){
    const f=fixture();if(change!=='missing_prepare')await f.prepare();let extra={};if(change==='production')f.room=room();if(change==='revision')extra.revision=1;if(change==='generation')extra.generation=otherGen;if(change==='profile')extra.profileId='other';if(change==='not_ready')f.preflight.ready=false;if(change==='mix')f.broadcast.audioMixReady=()=>false;if(change==='destination')extra.destinationId='never';
    await assert.rejects(f.start(extra));assert.equal(f.groups.length,0,change);assert.equal(f.calls.some(call=>call.body?.active===true),false,change);assert.equal(f.lookups,0);
  }
});

test('Start request retry is idempotent and conflicting reuse is rejected',async()=>{
  const f=fixture();await f.prepare();const first=f.start(),second=f.start();assert.equal(first,second);await first;await f.start();assert.equal(f.groups.length,1);await assert.rejects(f.start({profileId:'other'}),/rehearsal_request_conflict/);await f.coordinator.stop();
});

test('Stop waits for an in-flight claim, clears it, and prevents every late worker and capture',async()=>{
  const f=fixture();await f.prepare();f.waitClaim=deferred();const starting=f.start();starting.catch(()=>{});await settle();assert.equal(f.coordinator.status().local.ownershipPending,true);const stopping=f.coordinator.stop();assert.equal(f.coordinator.stop(),stopping);await settle();assert.equal(f.groups.length,0);assert.equal(f.calls.some(call=>call.body?.active===false),false);
  f.waitClaim.resolve();await stopping;await assert.rejects(starting,/rehearsal_cancelled/);assert.equal(f.groups.length,0);assert.equal(f.taps.length,0);assert.equal(f.coordinator.active(),false);assert.equal(f.coordinator.status().room.mode,'rehearsal');
});

test('Stop retains ownership until an in-flight worker Start settles and never captures afterward',async()=>{
  const f=fixture();await f.prepare();f.waitWorker=deferred();const starting=f.start();starting.catch(()=>{});await settle();assert.equal(f.groups[0].running,true);const stopping=f.coordinator.stop();await settle();assert.equal(f.calls.some(call=>call.body?.active===false),false);assert.equal(f.broadcast.rehearsing,true);f.waitWorker.resolve();await stopping;await assert.rejects(starting,/rehearsal_cancelled/);assert.equal(f.taps.length,0);assert.equal(f.coordinator.active(),false);
});

test('unconfirmed worker or ownership release blocks close and exit while keeping the durable latch',async()=>{
  const f=fixture();await f.prepare();await f.start();f.holdWorker=true;await f.coordinator.stop();assert.equal(f.coordinator.status().local.reason,'encoder_stop_unconfirmed');assert.equal(await f.coordinator.close(),false);assert.equal(f.coordinator.active(),true);await assert.rejects(f.coordinator.exit({requestId:'exit',revision:2,generation:gen}),/rehearsal_encoding_active/);assert.equal(f.calls.some(call=>call.url.endsWith('/exit')),false);
  f.holdWorker=false;f.failClear=true;await f.coordinator.stop();assert.equal(f.coordinator.status().local.ownershipPending,true);assert.equal(await f.coordinator.close(),false);f.failClear=false;assert.equal(await f.coordinator.close(),true);assert.equal(f.coordinator.status().room.mode,'rehearsal');assert.equal(f.captureClosed,undefined);
});

test('late encoder and capture callbacks cannot affect a later local retry',async()=>{
  const f=fixture();await f.prepare();await f.start();const old=f.groups[0],tap=f.taps[0];await f.coordinator.stop();await f.start({requestId:'retry'});old.emit({state:'failed',code:'encoder_input_failed'});assert.equal(tap.video(Buffer.alloc(4),0),false);await settle();assert.equal(f.groups[1].stops,0);assert.equal(f.groups[1].video,0);await f.coordinator.stop();
});

test('source backpressure and redacted failures stop local encoding without changing room mode',async()=>{
  const f=fixture();await f.prepare();await f.start();f.backpressure=true;assert.equal(f.taps[0].video(Buffer.alloc(4),0),false);await settle();assert.equal(f.coordinator.status().local.reason,'encoder_backpressure');assert.equal(f.coordinator.active(),false);assert.equal(f.coordinator.status().room.mode,'rehearsal');assert.equal(sanitizeSourceCallbackCode({code:'rtmps://private/key'}),'encoder_failed');
});

test('supervision permits temporary Take readiness changes but stops durable failure or changed room generation',async()=>{
  const f=fixture();await f.prepare();await f.start();f.preflight.ready=false;await f.coordinator.check();f.now=6000;await f.coordinator.check();assert.equal(f.groups[0].stops,0);f.preflight.ready=true;await f.coordinator.check();f.now=20000;f.preflight.ready=false;await f.coordinator.check();f.now=26500;await f.coordinator.check();assert.equal(f.coordinator.status().local.reason,'output_lost');
  f.preflight.ready=true;await f.start({requestId:'again'});f.captureState.error='output_audio_stalled';await f.coordinator.check();assert.equal(f.coordinator.status().local.reason,'output_audio_stalled');f.captureState.error=null;await f.start({requestId:'third'});f.room=room('rehearsal',{generation:otherGen});await f.coordinator.refresh();assert.equal(f.coordinator.active(),false);assert.equal(f.coordinator.status().local.reason,'rehearsal_generation_conflict');assert.equal(f.calls.at(-1).body.rehearsal_generation,gen);
});

test('monitor defaults off, requires room/Prepare/VOD support, and Stop serializes off after a pending selection',async()=>{
  const f=fixture({vod:true});assert.equal(f.coordinator.status().monitor.bus,'off');await assert.rejects(f.coordinator.monitor({bus:'live'}),/rehearsal_monitor_unavailable/);await f.prepare();await f.coordinator.refresh();assert.equal(f.coordinator.status().monitor.vodAvailable,true);await f.coordinator.monitor({bus:'vod'});assert.equal(f.coordinator.status().monitor.bus,'vod');
  const pending=deferred();f.capture.setMonitor=async bus=>{f.monitorCalls.push(bus);if(bus==='live')await pending.promise;return {ok:true};};const selecting=f.coordinator.monitor({bus:'live'});const stopping=f.coordinator.stop();await settle();assert.equal(f.monitorCalls.at(-1),'live');pending.resolve();await selecting;await stopping;assert.equal(f.coordinator.status().monitor.bus,'off');assert.equal(f.monitorCalls.at(-1),'off');
  f.broadcast.outputProfile.twitchVod=false;await assert.rejects(f.coordinator.monitor({bus:'vod'}),/rehearsal_monitor_unavailable/);
});

test('a late pre-command poll cannot replace the successful room mutation with stale Production',async()=>{
  const f=fixture({mode:'production'}),enter=deferred(),poll=deferred();let pollCount=0;f.request=async url=>url.endsWith('/enter')?enter.promise:++pollCount===1?poll.promise:{ok:true,room:room('rehearsal')};
  const entering=f.coordinator.enter({requestId:'enter',revision:0}),refreshing=f.coordinator.refresh();enter.resolve({ok:true,room:room('rehearsal')});await entering;poll.resolve({ok:true,room:room()});await refreshing;assert.equal(f.coordinator.status().room.mode,'rehearsal');assert.equal(f.coordinator.publishingAllowed(),false);
});

test('external room change also turns off prepared monitoring without requiring a running encoder',async()=>{
  const f=fixture();await f.prepare();await f.coordinator.refresh();await f.coordinator.monitor({bus:'live'});f.room=room();await f.coordinator.refresh();assert.equal(f.coordinator.status().monitor.bus,'off');assert.equal(f.monitorCalls.at(-1),'off');assert.equal(f.coordinator.publishingAllowed(),true);
});

test('capture Start cancellation and an uncertain capture Stop keep ownership until capture closes',async()=>{
  const f=fixture(),captureStart=deferred();await f.prepare();f.capture.startCapture=async()=>captureStart.promise;const starting=f.start();starting.catch(()=>{});await settle();assert.equal(f.groups.length,1);const stopping=f.coordinator.stop();await settle();assert.equal(f.calls.some(call=>call.body?.active===false),false);captureStart.resolve();await stopping;await assert.rejects(starting,/rehearsal_cancelled/);
  f.capture.startCapture=async()=>{};await f.start({requestId:'retry'});f.capture.stopCapture=async()=>{throw Error('private capture failure');};await f.coordinator.stop();assert.equal(f.coordinator.status().local.ownershipPending,true);assert.equal(f.coordinator.status().local.reason,'capture_stop_unconfirmed');assert.equal(await f.coordinator.close(),false);f.capture.stopCapture=async()=>{};assert.equal(await f.coordinator.close(),true);
});

test('local capture waits for the actual rehearsal watermark and Stop cancels that wait before the first frame',async()=>{
  const f=fixture(),badge=deferred();await f.prepare();f.capture.waitForRehearsal=async generation=>{assert.equal(generation,gen);await badge.promise;};const originalStop=f.capture.stopCapture;f.capture.stopCapture=async()=>{badge.reject(Object.assign(Error('output_rehearsal_cancelled'),{code:'output_rehearsal_cancelled'}));await originalStop();};
  const starting=f.start();starting.catch(()=>{});await settle();assert.equal(f.groups.length,1);assert.equal(f.taps.length,0);await f.coordinator.stop();await assert.rejects(starting,/rehearsal_cancelled/);assert.equal(f.taps.length,0);assert.equal(f.coordinator.active(),false);
});
