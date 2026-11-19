const test=require('node:test'),assert=require('node:assert/strict'),{NativeBroadcast}=require('../broadcast.cjs');
function fixture(){let captureState={peerId:'output-one',rendered:true,browserReviewOpen:false,audioBlocked:false,generation:3},preflight={ready:true,generation:3,blockers:[]},confirmed=true,starts=0,stops=0;const calls=[],capture={prepare:async()=>{},review(){},status:()=>captureState,startCapture:async()=>{},stopCapture:async()=>{},close:async()=>{}},encoder={start:async()=>starts++,stop:async()=>stops++,status:()=>({}),sendVideo:()=>true,sendAudio:()=>true};const app=new NativeBroadcast({destinations:{getPrivateDestination:async()=>({serverUrl:'rtmps://example.net/app',streamKey:'synthetic'})},createCapture:()=>capture,createEncoder:()=>encoder,identity:{pid:1,server_session_id:'test'},ownerPid:2,confirm:async()=>confirmed,request:async(url,body)=>{calls.push({url,body});return {preflight};}});return {app,capture,encoder,calls,get starts(){return starts;},get stops(){return stops;},set confirmed(v){confirmed=v;},set captureState(v){captureState=v;},set preflight(v){preflight=v;}};}
test('preparation is separate from transmission and requires the captured output identity',async()=>{const f=fixture();await f.app.prepare();assert.equal(f.starts,0);assert.equal(f.app.status().ready,true);assert.ok(f.calls[0].url.includes('output_peer_id=output-one'));f.captureState={rendered:true};await f.app.check();assert.equal(f.app.status().ready,false);});
test('cancelled confirmation never reserves encoding or starts a worker',async()=>{const f=fixture();await f.app.prepare();f.confirmed=false;await f.app.start({destinationId:'one'});assert.equal(f.starts,0);assert.equal(f.calls.some(c=>c.body?.active===true),false);});

test('expired or disconnected linked account blocks confirmation and media with reconnect guidance',async()=>{
  const f=fixture();let confirmations=0;f.app.confirm=async()=>{confirmations++;return true;};
  f.app.destinations.getPrivateDestination=async()=>{throw Error('account_authorization_required');};
  await f.app.prepare();await assert.rejects(f.app.start({destinationId:'linked'}),/account_authorization_required/);
  assert.equal(f.app.status().reason,'account_authorization_required');assert.equal(confirmations,0);assert.equal(f.starts,0);assert.equal(f.calls.some(call=>call.body?.active===true),false);
});
test('native start reserves ownership before transport and stop clears it after cleanup',async()=>{const f=fixture();await f.app.prepare();await f.app.start({destinationId:'one'});assert.equal(f.starts,1);assert.equal(f.calls.find(c=>c.body?.active).body.owner_pid,2);await f.app.stop();assert.equal(f.stops,1);assert.equal(f.calls.at(-1).body.active,false);});
test('unreviewed/stale output and renderer-supplied private options cannot start a broadcast',async()=>{const f=fixture();await f.app.prepare();f.captureState={peerId:'output-one',rendered:true,generation:99};await assert.rejects(f.app.start({destinationId:'one'}),/output_not_ready/);assert.equal(f.starts,0);await assert.rejects(f.app.start({destinationId:'one',testOutput:'anything'}),/invalid_broadcast_request/);});
test('worker start failure clears native ownership and reports only a generic safe reason',async()=>{const f=fixture();await f.app.prepare();f.encoder.start=async()=>{throw Error('rtmps://host/secret-key');};await assert.rejects(f.app.start({destinationId:'one'}),/broadcast_start_failed/);assert.equal(f.app.status().reason,'broadcast_start_failed');assert.equal(f.calls.at(-1).body.active,false);});

test('capture cleanup failure still stops the worker before clearing ownership',async()=>{const f=fixture();await f.app.prepare();await f.app.start({destinationId:'one'});f.capture.stopCapture=async()=>{throw Error('capture failed');};await f.app.stop();assert.equal(f.stops,1);assert.equal(f.calls.at(-1).body.active,false);});
test('ambiguous reservation response is cleared conservatively after a failed start',async()=>{const f=fixture();await f.app.prepare();const request=f.app.request;f.app.request=async(url,body)=>{if(body?.active===true){f.calls.push({url,body});throw Error('response lost');}return request(url,body);};await assert.rejects(f.app.start({destinationId:'one'}),/broadcast_start_failed/);assert.equal(f.calls.at(-1).body.active,false);});

test('late preflight cannot bless an output generation that changed during the check',async()=>{const f=fixture();await f.app.prepare();let resolve;f.app.request=()=>new Promise(r=>resolve=r);const pending=f.app.check();f.captureState={peerId:'output-one',rendered:true,browserReviewOpen:false,generation:4};resolve({preflight:{ready:true,generation:3}});await pending;assert.equal(f.app.status().ready,false);});

const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
const healthy=()=>({peerId:'output-one',rendered:true,browserReviewOpen:false,audioBlocked:false,audioReady:true,prepared:true,generation:3});
function runningFixture(){
  const f=fixture();f.runs=[];f.taps=[];f.confirmations=0;
  f.app.confirm=async()=>{f.confirmations++;return true;};
  f.app.createEncoder=notify=>{
    const run={state:{running:false,codec:'libx264',videoFrames:0,audioSamples:0},starts:0,stops:0,video:0,audio:0,
      status(){return {...this.state};},async start(){this.starts++;this.state.running=true;},async stop(){this.stops++;this.state.running=false;},
      sendVideo(){this.video++;return true;},sendAudio(){this.audio++;return true;},emit(value){Object.assign(this.state,value);notify({...this.state});}};
    f.runs.push(run);f.setupWorker?.(run);return run;
  };
  f.capture.startCapture=async(video,audio)=>{f.taps.push({video,audio});};
  return f;
}

test('old encoder events and capture callbacks cannot stop or feed a confirmed retry',async()=>{
  const f=runningFixture();await f.app.prepare();await f.app.start({destinationId:'one'});
  const previous=f.runs[0],tap=f.taps[0];await f.app.stop();await f.app.start({destinationId:'one'});
  const current=f.runs[1];current.emit({state:'active',videoFrames:2});
  previous.emit({state:'failed',code:'tls_connection_failed'});previous.emit({state:'active',videoFrames:900});
  assert.equal(tap.video(Buffer.alloc(1),0),false);assert.equal(tap.audio(Buffer.alloc(1),0),false);await settle();
  assert.equal(current.stops,0);assert.equal(current.video,0);assert.equal(current.audio,0);assert.equal(f.app.status().phase,'sending');assert.equal(f.app.status().frames,2);assert.equal(f.confirmations,2);
  await f.app.stop();
});

test('cancelling a pending encoder Start stops its worker and never starts capture afterward',async()=>{
  const f=runningFixture(),pending=deferred();f.setupWorker=run=>{run.start=async()=>{run.starts++;run.state.running=true;await pending.promise;};};
  await f.app.prepare();const starting=f.app.start({destinationId:'one'});await settle();assert.equal(f.runs.length,1);
  await f.app.stop();assert.equal(f.runs[0].stops,1);assert.equal(f.runs[0].state.running,false);
  pending.resolve();await assert.rejects(starting,/broadcast_cancelled/);assert.equal(f.taps.length,0);assert.equal(f.app.status().active,false);assert.equal(f.app.status().reason,null);
});

test('Stop waits for an unresolved reservation before clearing ownership',async()=>{
  const f=runningFixture(),reservation=deferred(),request=f.app.request;
  f.app.request=async(url,body)=>{if(body?.active===true){f.calls.push({url,body});await reservation.promise;return {};}return request(url,body);};
  await f.app.prepare();const starting=f.app.start({destinationId:'one'});await settle();const stopping=f.app.stop();await settle();
  assert.equal(f.calls.some(call=>call.body?.active===false),false);assert.equal(f.runs.length,0);
  reservation.resolve();await stopping;await assert.rejects(starting,/broadcast_cancelled/);
  assert.equal(f.calls.at(-1).body.active,false);assert.equal(f.app.ownsEncoding,false);assert.equal(f.runs.length,0);
});

test('safe encoder failures survive startup cancellation cleanup; raw worker failures are redacted',async()=>{
  for(const [code,expected] of [['tls_verification_failed','tls_verification_failed'],['encoder_transport_interrupted','encoder_transport_interrupted'],['rtmps://private/secret-key','encoder_failed']]){
    const f=runningFixture();f.setupWorker=run=>{run.start=async()=>{run.state.running=true;run.emit({state:'failed',code});throw Object.assign(Error('rtmps://private/secret-key'),{code});};};
    await f.app.prepare();await assert.rejects(f.app.start({destinationId:'one'}),{message:expected});
    assert.equal(f.app.status().reason,expected);assert.equal(f.app.status().active,false);assert.equal(f.runs[0].stops,1);assert.doesNotMatch(JSON.stringify(f.app.status()),/private|secret-key/);
    await f.app.check();assert.equal(f.runs.length,1);assert.equal(f.app.status().reason,expected);
  }
});

test('worker rejection with a safe public code is retained without exposing its message',async()=>{
  const f=runningFixture();f.setupWorker=run=>{run.start=async()=>{throw Object.assign(Error('private destination/key'),{code:'destination_dns_failed'});};};
  await f.app.prepare();await assert.rejects(f.app.start({destinationId:'one'}),{message:'destination_dns_failed'});
  assert.equal(f.app.status().reason,'destination_dns_failed');assert.doesNotMatch(JSON.stringify(f.app.status()),/private/);
});

test('uncertain ownership blocks retry and close until explicit Stop reconciles it',async()=>{
  const f=runningFixture(),request=f.app.request;let failClear=true,closed=0;
  f.capture.close=async()=>{closed++;};f.app.request=async(url,body)=>{if(body?.active===false&&failClear)throw Error('private response');return request(url,body);};
  await f.app.prepare();await f.app.start({destinationId:'one'});await f.app.stop();
  assert.equal(f.app.status().active,false);assert.equal(f.app.status().ownershipPending,true);assert.equal(f.app.status().ready,false);assert.equal(f.app.status().reason,'studio_status_unconfirmed');
  await assert.rejects(f.app.start({destinationId:'one'}),/studio_status_unconfirmed/);assert.equal(await f.app.close(),false);assert.equal(closed,0);assert.equal(f.runs.length,1);
  failClear=false;await f.app.stop();assert.equal(f.app.status().ownershipPending,false);assert.equal(f.app.status().ready,true);
  await f.app.start({destinationId:'one'});assert.equal(f.confirmations,2);await f.app.stop();
});

test('transient readiness gets a resettable grace period, including a zero-origin clock',async()=>{
  const f=runningFixture();let now=0;f.app.clock=()=>now;await f.app.prepare();await f.app.start({destinationId:'one'});f.runs[0].emit({state:'active',videoFrames:1});
  f.captureState={...healthy(),rendered:false};await f.app.check();now=6499;await f.app.check();assert.equal(f.runs[0].stops,0);
  f.captureState=healthy();await f.app.check();now=7000;f.captureState={...healthy(),rendered:false};await f.app.check();now=13499;await f.app.check();assert.equal(f.runs[0].stops,0);
  now=13500;await f.app.check();assert.equal(f.runs[0].stops,1);assert.equal(f.app.status().reason,'output_lost');
  f.captureState=healthy();await f.app.check();assert.equal(f.runs.length,1);assert.equal(f.app.status().reason,'output_lost');
});

test('durable output faults stop immediately and closed windows are not prepared',async()=>{
  const f=runningFixture();await f.app.prepare();await f.app.start({destinationId:'one'});f.runs[0].emit({state:'active',videoFrames:1});
  f.captureState={...healthy(),prepared:false,error:'output_closed'};await f.app.check();
  assert.equal(f.runs[0].stops,1);assert.equal(f.app.status().prepared,false);assert.equal(f.app.status().ready,false);assert.equal(f.app.status().reason,'output_closed');
});

test('final safe codec and counters survive confirmed stop and reset on a new attempt',async()=>{
  const f=runningFixture();await f.app.prepare();await f.app.start({destinationId:'one'});
  f.runs[0].emit({state:'active',videoFrames:90,audioSamples:144000,codec:'libx264',private:'secret-key'});f.runs[0].emit({state:'failed',code:'tls_connection_failed'});await settle();
  assert.equal(f.app.status().frames,90);assert.equal(f.app.status().audioSamples,144000);assert.equal(f.app.status().codec,'libx264');assert.equal(f.app.status().reason,'tls_connection_failed');assert.doesNotMatch(JSON.stringify(f.app.status()),/secret-key/);
  await f.app.start({destinationId:'one'});assert.equal(f.app.status().frames,0);assert.equal(f.app.status().audioSamples,0);
  f.runs[1].emit({state:'failed',code:'arbitrary secret',codec:'private-codec',videoFrames:Infinity,audioSamples:-1});await settle();
  assert.equal(f.app.status().frames,0);assert.equal(f.app.status().audioSamples,0);assert.equal(f.app.status().codec,null);assert.equal(f.app.status().reason,'encoder_failed');
});

test('unknown capture and backend reasons never enter public status or notifications',async()=>{
  const f=fixture(),events=[];f.app.onState=value=>events.push(value);await f.app.prepare();
  f.preflight={ready:false,generation:3,blockers:[{reason:'rtmps://private/secret-key'}]};await f.app.check();assert.equal(f.app.status().reason,'output_not_ready');
  await f.app.stop('rtmps://private/secret-key');assert.equal(f.app.status().reason,'encoder_failed');assert.doesNotMatch(JSON.stringify(events),/private|secret-key/);
});

test('unconfirmed worker shutdown retains ownership and prevents retry or close',async()=>{
  const f=runningFixture(),pending=deferred();await f.app.prepare();await f.app.start({destinationId:'one'});
  const run=f.runs[0];run.stop=async()=>{run.stops++;await pending.promise;};
  const first=f.app.stop(),second=f.app.stop();await settle();assert.equal(run.stops,1);pending.resolve();await Promise.all([first,second]);
  assert.equal(f.app.status().active,true);assert.equal(f.app.status().reason,'encoder_stop_unconfirmed');assert.equal(f.app.status().ready,false);
  assert.equal(f.calls.some(call=>call.body?.active===false),false);await assert.rejects(f.app.start({destinationId:'one'}),/broadcast_busy/);assert.equal(await f.app.close(),false);
  run.stop=async()=>{run.state.running=false;};await f.app.stop();assert.equal(f.app.status().active,false);assert.equal(f.app.ownsEncoding,false);
});

test('cancelled destination lookup cannot open a later confirmation or create a worker',async()=>{
  const f=runningFixture(),lookup=deferred();f.app.destinations.getPrivateDestination=()=>lookup.promise;await f.app.prepare();
  const starting=f.app.start({destinationId:'one'});await settle();await f.app.stop();lookup.resolve({serverUrl:'rtmps://example.net/app',streamKey:'synthetic'});
  await assert.rejects(starting,/broadcast_cancelled/);assert.equal(f.confirmations,0);assert.equal(f.runs.length,0);assert.equal(f.app.status().active,false);
});

test('selected destinations share one capture and keep transport failures isolated',async()=>{
  const f=runningFixture();let confirmed;f.app.confirm=async value=>{confirmed=value;return true;};
  await f.app.prepare();await f.app.start({destinationIds:['one','two','three']});
  assert.equal(confirmed.length,3);assert.equal(f.taps.length,1);assert.equal(f.runs.length,3);
  f.runs.forEach(run=>run.emit({state:'active',videoFrames:3}));
  f.runs[1].emit({state:'failed',code:'tls_connection_failed'});await settle();
  assert.equal(f.runs[1].stops,1);assert.equal(f.runs[0].stops,0);assert.equal(f.runs[2].stops,0);assert.equal(f.app.status().active,true);
  f.taps[0].video(Buffer.alloc(1),0);assert.equal(f.runs[0].video,1);assert.equal(f.runs[1].video,0);assert.equal(f.runs[2].video,1);
  const failed=f.app.status().targets[1];assert.equal(failed.phase,'failed');assert.equal(failed.reason,'tls_connection_failed');
  await f.app.stopTarget('one');assert.equal(f.runs[2].stops,0);await f.app.stopTarget('three');assert.equal(f.app.status().active,false);assert.equal(f.app.ownsEncoding,false);
});
test('a failed destination during startup rolls back the entire unstarted selection',async()=>{
  const f=runningFixture();f.setupWorker=run=>{if(f.runs.length===2)run.start=async()=>{run.state.running=true;throw Object.assign(Error('private'),{code:'destination_dns_failed'});};};
  await f.app.prepare();await assert.rejects(f.app.start({destinationIds:['one','two','three']}),/destination_dns_failed/);
  assert.equal(f.taps.length,0);assert.equal(f.runs.length,2);assert.equal(f.runs.every(r=>r.stops===1),true);assert.equal(f.app.ownsEncoding,false);
});
test('selection validation happens before destination access or confirmation',async()=>{
  const f=runningFixture();await f.app.prepare();
  for(const value of [{destinationIds:[]},{destinationIds:['one','one']},{destinationIds:Array.from({length:9},(_,i)=>String(i))},{destinationId:'one',destinationIds:['two']}])await assert.rejects(f.app.start(value),/invalid_broadcast_request/);
  assert.equal(f.confirmations,0);assert.equal(f.runs.length,0);
});
test('saved profile settings are immutable during confirmation and edits require preparation',async()=>{
  const f=runningFixture();const p={id:'hd-custom',name:'Custom',format:'hd',fps:60,videoBitrateKbps:8500,codec:'libx264',keyframeSeconds:3,audioBitrateKbps:256,twitchVod:true,audioRouting:{}};
  f.app.outputProfiles={getProfile:async()=>structuredClone(p)};const configs=[];f.setupWorker=run=>{run.start=async value=>{configs.push(value);run.state.running=true;};run.sendVodAudio=()=>true;};
  f.app.destinations.getPrivateDestination=async id=>({name:id,platform:id==='one'?'twitch':'youtube',serverUrl:'rtmps://example.net/app',streamKey:'synthetic'});
  await f.app.prepare({profileId:p.id});await f.app.start({profileId:p.id,destinationIds:['one','two']});
  assert.equal(configs[0].fps,60);assert.equal(configs[0].bitrate,8500000);assert.equal(configs[0].audioBitrateKbps,256);assert.equal(configs[0].keyframeSeconds,3);assert.equal(configs[0].twitchVod,true);assert.equal(configs[1].twitchVod,false);
  await f.app.stop();p.videoBitrateKbps=9000;await assert.rejects(f.app.start({profileId:p.id,destinationId:'one'}),/prepare_output/);assert.equal(configs.length,2);
});
test('shared output failure stops every selected destination and holds uncertain ownership',async()=>{
  const f=runningFixture();await f.app.prepare();await f.app.start({destinationIds:['one','two']});f.runs.forEach(r=>r.emit({state:'active',videoFrames:1}));
  f.captureState={...healthy(),error:'output_audio_stalled'};await f.app.check();assert.equal(f.runs.every(r=>r.stops===1),true);assert.equal(f.app.status().reason,'output_audio_stalled');assert.equal(f.app.ownsEncoding,false);
});

test('Stop cancels a delayed profile read before it can create or review output',async()=>{
  const f=runningFixture(),lookup=deferred();let created=0;f.app.outputProfiles={getProfile:()=>lookup.promise};f.app.createCapture=()=>{created++;return f.capture;};
  const preparing=f.app.prepare({profileId:'saved'});await settle();await assert.rejects(f.app.prepare(),/broadcast_busy/);await f.app.stop();lookup.resolve({id:'saved',format:'hd',fps:30,audioRouting:{}});
  await assert.rejects(preparing,/broadcast_cancelled/);assert.equal(created,0);assert.equal(f.app.status().phase,'idle');
});

test('cancelling the eighth encoder start cleans every owned worker once and never starts capture',async()=>{
  const f=runningFixture(),last=deferred(),ids=Array.from({length:8},(_,i)=>'target-'+i);
  f.setupWorker=run=>{if(f.runs.length===8)run.start=async()=>{run.starts++;run.state.running=true;await last.promise;};};
  await f.app.prepare();const starting=f.app.start({destinationIds:ids});
  for(let n=0;n<500&&f.runs.length<8;n++)await Promise.resolve();assert.equal(f.runs.length,8);
  await f.app.stop();last.resolve();await assert.rejects(starting,/broadcast_cancelled/);
  assert.equal(f.runs.every(run=>run.stops===1&&!run.state.running),true);assert.equal(f.taps.length,0);
  assert.equal(f.calls.filter(c=>c.body?.active===true).length,1);assert.equal(f.calls.filter(c=>c.body?.active===false).length,1);assert.equal(f.app.ownsEncoding,false);
});
test('one saturated destination stops alone while seven destinations keep receiving media',async()=>{
  const f=runningFixture(),ids=Array.from({length:8},(_,i)=>'target-'+i);await f.app.prepare();await f.app.start({destinationIds:ids});
  f.runs.forEach(run=>run.emit({state:'active',videoFrames:3}));f.runs[3].sendAudio=()=>false;
  assert.equal(f.taps[0].audio(Buffer.alloc(8),0,Buffer.alloc(8)),true);await settle();
  assert.equal(f.runs[3].stops,1);assert.equal(f.app.status().targets[3].reason,'encoder_backpressure');
  assert.equal(f.runs.filter((_,i)=>i!==3).every(run=>run.stops===0),true);assert.equal(f.app.ownsEncoding,true);
  f.taps[0].video(Buffer.alloc(4),1);assert.equal(f.runs.filter((_,i)=>i!==3).every(run=>run.video===1),true);assert.equal(f.runs[3].video,0);
  await f.app.stop();assert.equal(f.runs.every(run=>run.stops===1),true);assert.equal(f.calls.filter(c=>c.body?.active===false).length,1);assert.equal(f.app.active(),false);
});

function sharedFixture(){
  const f=runningFixture();f.groups=[];
  f.app.createEncoderGroup=notify=>{
    const group={running:false,targets:new Map(),video:0,audio:0,vod:0,stops:0,state:'idle',config:null,
      status(){return {running:this.running,state:this.state,videoFrames:this.video,audioSamples:this.audio*480,codec:'libx264'};},
      createTarget(id,observe){const target={running:false,stops:0,state:'starting',frames:0,status(){return {running:this.running,state:this.state,videoFrames:this.frames};},async stop(){this.stops++;this.running=false;this.state='stopped';return this.status();},emit(value){Object.assign(this,value);observe(this.status());}};this.targets.set(id,target);return target;},
      async start(value){this.config=value;this.running=true;this.state='starting';for(const target of this.targets.values())target.running=true;if(this.waitStart)await this.waitStart;},
      sendVideo(){this.video++;for(const target of this.targets.values())if(target.running)target.emit({state:'active',frames:this.video});return true;},sendAudio(){this.audio++;return true;},sendVodAudio(){this.vod++;return true;},
      async stop(){this.stops++;if(!this.holdRunning)this.running=false;for(const target of this.targets.values())target.running=false;this.state='stopped';return this.status();},fail(){this.state='failed';notify({state:'failed',code:'encoder_input_failed'});}};
    f.groups.push(group);return group;
  };
  f.app.destinations.getPrivateDestination=async id=>({platform:id==='one'?'twitch':'youtube',name:id,serverUrl:'rtmps://example.net/app',streamKey:'synthetic'});
  return f;
}
test('eight targets use one shared video and paired audio submission, with independent Stop',async()=>{
  const f=sharedFixture();f.app.outputProfiles={getProfile:async()=>({id:'saved',name:'Saved',format:'hd',fps:30,videoBitrateKbps:4000,codec:'auto',keyframeSeconds:2,audioBitrateKbps:192,twitchVod:true,audioRouting:{}})};
  await f.app.prepare({profileId:'saved'});await f.app.start({profileId:'saved',destinationIds:['one','two','three','four','five','six','seven','eight']});
  assert.equal(f.groups.length,1);assert.equal(f.runs.length,0);const group=f.groups[0];
  f.taps[0].video(Buffer.alloc(4),0);f.taps[0].audio(Buffer.alloc(8),0,Buffer.alloc(8));
  assert.equal(group.video,1);assert.equal(group.audio,1);assert.equal(group.vod,1);assert.equal(group.config.targets.filter(t=>t.twitchVod).length,1);
  await f.app.stopTarget('one');assert.equal(group.running,true);assert.equal(group.stops,0);assert.equal(f.app.ownsEncoding,true);assert.equal([...group.targets.values()].filter(t=>t.running).length,7);
  await f.app.stop();assert.equal(group.stops,1);assert.equal(f.app.ownsEncoding,false);assert.equal(f.calls.filter(c=>c.body?.active===false).length,1);
});
test('shared input failure stops every destination before releasing the session',async()=>{
  const f=sharedFixture();await f.app.prepare();await f.app.start({destinationIds:['one','two']});f.taps[0].video(Buffer.alloc(4),0);f.groups[0].fail();await settle();
  assert.equal(f.groups[0].stops,1);assert.equal(f.groups[0].running,false);assert.equal(f.app.status().reason,'encoder_input_failed');assert.equal(f.app.ownsEncoding,false);
});
test('Stop during shared worker startup rejects the late Start and never captures afterward',async()=>{
  const f=sharedFixture(),pending=deferred(),factory=f.app.createEncoderGroup;f.app.createEncoderGroup=notify=>{const g=factory(notify);g.waitStart=pending.promise;return g;};
  await f.app.prepare();const start=f.app.start({destinationIds:['one','two']});for(let i=0;i<200&&!f.groups[0]?.running;i++)await Promise.resolve();assert.equal(f.groups[0].running,true);
  await f.app.stop();pending.resolve();await assert.rejects(start,/broadcast_cancelled/);assert.equal(f.taps.length,0);assert.equal(f.groups[0].stops,1);assert.equal(f.app.ownsEncoding,false);
});
test('shared child ownership is retained even when every destination reports stopped',async()=>{
  const f=sharedFixture();await f.app.prepare();await f.app.start({destinationIds:['one','two']});const g=f.groups[0];g.holdRunning=true;
  await f.app.stop();assert.equal([...g.targets.values()].every(t=>!t.running),true);assert.equal(f.app.active(),true);assert.equal(f.app.status().reason,'encoder_stop_unconfirmed');assert.equal(f.app.ownsEncoding,true);assert.equal(f.calls.some(c=>c.body?.active===false),false);assert.equal(await f.app.close(),false);
  g.holdRunning=false;await f.app.stop();assert.equal(f.app.ownsEncoding,false);assert.equal(f.app.active(),false);
});

test('broadcast status exposes only fresh scalar Live/VOD diagnostics from the owned output',async()=>{
  const f=fixture();await f.app.prepare();f.captureState={...healthy(),audioMeters:{fresh:true,live:{peak:.7,rms:.3,clipCount:0},vod:{peak:.2,rms:.1,clipCount:0}}};assert.equal(f.app.status().audioMeters.live.peak,.7);
  f.captureState={...healthy(),audioMeters:{fresh:true,live:{peak:.7,rms:.3,clipCount:0},vod:{peak:.2,rms:.1,clipCount:0},privateBuffer:'never public'}};const status=f.app.status();assert.equal(status.audioMeters.fresh,false);assert.doesNotMatch(JSON.stringify(status),/privateBuffer|never public/);
});

test('live gain update while sending preserves encoder, capture and saved profile; retry does not apply twice',async()=>{
  const f=sharedFixture(),applies=[];f.capture.updateAudioRouting=async value=>{applies.push(value);return {ok:true,requestId:value.requestId,applied:true};};
  await f.app.prepare();await f.app.start({destinationIds:['one','two']});f.taps[0].video(Buffer.alloc(4),0);const group=f.groups[0],mix=f.app.status().audioMix;
  const value={outputId:mix.outputId,expectedRevision:mix.revision,requestId:'live-one',audioRouting:{'voice:default':{live:true,vod:true,liveGainDb:6,vodGainDb:-3}}};
  await f.app.setLiveAudio(value);await f.app.setLiveAudio(value);assert.equal(applies.length,2);assert.equal(f.app.encoderGroup,group);assert.equal(group.stops,0);assert.equal(f.taps.length,1);assert.equal(f.app.status().phase,'sending');assert.equal(f.app.status().audioMix.revision,1);assert.deepEqual(f.app.outputProfile.audioRouting,{});await f.app.stop();
});
test('pending live mix prevents a concurrent Start and old output requests cannot affect a new Prepare',async()=>{
  const f=sharedFixture(),pending=deferred();let wait=false;f.capture.updateAudioRouting=async value=>{if(wait)await pending.promise;return {requestId:value.requestId,applied:true};};await f.app.prepare();const old=f.app.status().audioMix;wait=true;
  const setting=f.app.setLiveAudio({outputId:old.outputId,expectedRevision:0,requestId:'pending',audioRouting:{'voice:default':{live:true,vod:true,liveGainDb:3}}});await settle();assert.equal(f.app.status().ready,false);await assert.rejects(f.app.start({destinationId:'one'}),/audio_mix_unconfirmed/);
  wait=false;await f.app.prepare();pending.resolve();await assert.rejects(setting,/audio_routing_cancelled/);assert.notEqual(f.app.status().audioMix.outputId,old.outputId);assert.equal(f.app.status().audioMix.revision,0);assert.equal(f.groups.length,0);
});
test('live audio audit failure does not undo a confirmed level change or stop transmission',async()=>{
  const f=sharedFixture();f.capture.updateAudioRouting=async value=>({requestId:value.requestId,applied:true});f.app.onAudioAudit=()=>{throw Error('private history path');};await f.app.prepare();await f.app.start({destinationIds:['one','two']});const mix=f.app.status().audioMix;
  await f.app.setLiveAudio({outputId:mix.outputId,expectedRevision:0,requestId:'history',audioRouting:{'voice:default':{live:true,vod:true,liveGainDb:-4}}});assert.equal(f.app.status().audioMix.historyWarning,true);assert.equal(f.groups[0].stops,0);assert.equal(f.app.status().active,true);assert.doesNotMatch(JSON.stringify(f.app.status()),/private history/);await f.app.stop();
});
