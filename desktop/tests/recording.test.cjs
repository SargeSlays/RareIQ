'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {NativeRecording}=require('../recording.cjs');
function fixture(){
  const f={calls:[],profile:{id:'saved-hd',format:'hd',fps:30,videoBitrateKbps:4000,codec:'auto',keyframeSeconds:2,audioBitrateKbps:192},own:{prepared:true,peerId:'output-one',generation:3,rendered:true,audioReady:true},ready:true,now:0,groupState:{running:false},finalized:true};
  f.capture={status:()=>({...f.own}),startCapture:async(video,audio)=>{f.calls.push('capture-start');f.video=video;f.audio=audio;},stopCapture:async()=>{f.calls.push('capture-stop');}};
  f.group={createTarget:(_id,observe)=>{f.targetObserve=observe;},status:()=>({...f.groupState}),start:async value=>{f.calls.push('encoder-start');f.config=value;f.groupState={running:true};},stop:async()=>{f.calls.push('encoder-stop');f.groupState={running:false,recordingFinalized:f.finalized,videoFrames:30,audioSamples:48000,recordingBytes:12345,codec:'libx264'};return f.groupState;},sendVideo:()=>true,sendAudio:()=>true};
  f.app=new NativeRecording({getCapture:async()=>f.capture,getProfile:async()=>f.profile,checkReady:async()=>({ready:f.ready,generation:f.own.generation}),request:async(_url,body)=>{f.calls.push(body.active?'claim':'release');},identity:{instance_id:'synthetic'},ownerPid:99,createEncoderGroup:(observe,options)=>{f.observe=observe;f.options=options;return f.group;},canPublish:async()=>true,chooseFile:async()=>{f.calls.push('choose');return path.resolve('F:/Temp/jonat/recording-tests/new.mkv');},confirm:async()=>{f.calls.push('confirm');return true;},inspectFile:async selected=>({path:selected,minimumFreeBytes:268435456}),clock:()=>f.now});return f;
}
const start=f=>f.app.start({requestId:'one'});
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
test('record-only prepares no destination and submits native file target, then independently finalizes',async()=>{
  const f=fixture();await start(f);assert.deepEqual(f.calls,['choose','confirm','claim','encoder-start','capture-start']);assert.equal(f.config.targets[0].recording,true);assert.equal(Object.hasOwn(f.config.targets[0],'destination'),false);assert.equal(f.config.twitchVod,false);assert.equal(f.options.recordingFile.path.endsWith('.mkv'),true);f.now=1500;const result=await f.app.stop();assert.equal(result.active,false);assert.equal(result.phase,'saved');assert.equal(result.finalized,true);assert.equal(result.frames,30);assert.equal(result.bytesWritten,12345);assert.equal(result.elapsedMs,1500);assert.ok(f.app.getSavedPath().endsWith('.mkv'));assert.equal(JSON.stringify(result).includes('F:'),false);assert.deepEqual(f.calls.slice(-3),['capture-stop','encoder-stop','release']);
});
test('renderer paths and unknown fields fail before chooser, repeated Start replays one operation',async()=>{
  const f=fixture();await assert.rejects(f.app.start({requestId:'bad',path:'private'}));assert.equal(f.calls.length,0);const one=start(f),same=start(f);assert.equal(one,same);await one;assert.equal(f.calls.filter(v=>v==='choose').length,1);await assert.rejects(f.app.start({requestId:'two'}),/recording_busy/);await f.app.stop();
});
test('chooser and confirmation cancellation create no file, claim or capture',async()=>{
  for(const cancel of ['chooseFile','confirm']){const f=fixture();f.app[cancel]=async()=>cancel==='chooseFile'?null:false;const result=await start(f);assert.equal(result.active,false);assert.equal(result.phase,'idle');assert.equal(f.calls.includes('claim'),false);assert.equal(f.calls.includes('encoder-start'),false);}
});
test('Stop retires a late chooser and stale trusted frame never claims output',async()=>{
  const f=fixture(),choice=deferred();f.app.chooseFile=()=>choice.promise;const pending=start(f);await new Promise(setImmediate);await f.app.stop();choice.resolve(path.resolve('F:/late.mkv'));await assert.rejects(pending,/recording_cancelled/);assert.equal(f.calls.includes('claim'),false);
  const other=fixture();let trusted=true;other.app.confirm=async()=>{trusted=false;return true;};await assert.rejects(other.app.start({requestId:'one'},{current:()=>trusted}),/recording_cancelled/);assert.equal(other.calls.includes('claim'),false);
});
test('readiness, profile changes and storage rejection block before owned media',async()=>{
  const noOutput=fixture();noOutput.ready=false;await assert.rejects(start(noOutput),/output_not_ready/);assert.equal(noOutput.calls.includes('choose'),false);
  const changed=fixture();changed.app.confirm=async()=>{changed.profile={...changed.profile,fps:60};return true;};await assert.rejects(start(changed),/output_generation_changed/);assert.equal(changed.calls.includes('claim'),false);
  const disk=fixture();disk.app.inspectFile=async()=>{throw Object.assign(Error('private-file'),{code:'insufficient_recording_space'});};await assert.rejects(start(disk),/insufficient_recording_space/);assert.equal(disk.calls.includes('claim'),false);assert.equal(JSON.stringify(disk.app.status()).includes('private'),false);
});
test('uncertain stop retains claim and retry Stop reconciles ownership without claiming saved',async()=>{
  const f=fixture();await start(f);const stop=f.group.stop;f.group.stop=async()=>({running:true});const result=await f.app.stop();assert.equal(result.active,true);assert.equal(result.finalized,false);assert.equal(result.reason,'recording_stop_unconfirmed');assert.equal(f.calls.includes('release'),false);await assert.rejects(f.app.start({requestId:'two'}),/recording_busy/);f.group.stop=stop;await f.app.stop();assert.equal(f.calls.includes('release'),true);assert.equal(f.app.active(),false);assert.equal(f.app.getSavedPath(),null);
});
test('partial reservation failure is reconciled and encoder failure stops only recording lease',async()=>{
  const f=fixture();f.app.request=async(_url,body)=>{f.calls.push(body.active?'claim':'release');if(body.active)throw Error('private response');};await assert.rejects(start(f),/recording_start_failed/);assert.equal(f.calls.includes('release'),true);
  const failed=fixture();await start(failed);failed.targetObserve({state:'failed',code:'recording_storage_unavailable'});await new Promise(setImmediate);assert.equal(failed.app.status().reason,'recording_storage_unavailable');assert.equal(failed.app.status().finalized,false);assert.equal(failed.calls.filter(v=>v==='capture-stop').length,1);
});
test('joining active owned output is allowed, Take remains valid, transient loss uses bounded grace',async()=>{
  const f=fixture();await start(f);f.own.generation=4;await f.app.check();assert.equal(f.app.active(),true);f.ready=false;await f.app.check();f.now=6499;await f.app.check();assert.equal(f.app.status().phase,'recording');f.now=6500;await f.app.check();assert.equal(f.app.status().reason,'recording_output_unavailable');assert.equal(f.app.status().finalized,false);
});
test('backpressure and unverified finalization never produce a saved file claim',async()=>{
  const f=fixture();await start(f);f.group.sendVideo=()=>false;assert.equal(f.video(Buffer.alloc(4),0),false);await new Promise(setImmediate);assert.equal(f.app.status().reason,'encoder_backpressure');assert.equal(f.app.getSavedPath(),null);
  const empty=fixture();empty.finalized=false;await start(empty);await empty.app.stop();assert.equal(empty.app.status().reason,'recording_finalize_failed');assert.equal(empty.app.status().finalized,false);
});

test('closing the initiating panel after committed Start keeps media and finalization alive',async()=>{
  const f=fixture();let current=true;await f.app.start({requestId:'one'},{current:()=>current});current=false;assert.equal(f.video(Buffer.alloc(4),1),true);assert.equal(f.audio(Buffer.alloc(8),1),true);f.targetObserve({state:'active',videoFrames:2});assert.equal(f.app.status().phase,'recording');assert.equal((await f.app.stop()).finalized,true);
});

test('repeated Stop and application shutdown preserve the saved receipt and Reveal path',async()=>{
  const f=fixture();await start(f);const saved=await f.app.stop(),file=f.app.getSavedPath();assert.equal(saved.phase,'saved');assert.equal(saved.finalized,true);assert.deepEqual(await f.app.stop(),saved);assert.deepEqual(await f.app.stop(),saved);assert.equal(f.app.getSavedPath(),file);assert.equal(f.calls.filter(value=>value==='encoder-stop').length,1);assert.equal(f.calls.filter(value=>value==='release').length,1);
});

test('a Program, receiver or profile change during worker startup releases ownership before capture',async()=>{
  for(const change of [f=>{f.own.generation++;},f=>{f.own.peerId='different-receiver';},f=>{f.profile={...f.profile,fps:60};},f=>{f.own.audioReady=false;}]){
    const f=fixture(),worker=deferred();f.group.start=async()=>{f.calls.push('encoder-start');f.groupState={running:true};await worker.promise;};const pending=start(f);await new Promise(setImmediate);assert.equal(f.calls.includes('claim'),true);change(f);worker.resolve();await assert.rejects(pending,/output_generation_changed/);assert.equal(f.calls.includes('capture-start'),false);assert.equal(f.calls.filter(value=>value==='encoder-stop').length,1);assert.equal(f.calls.filter(value=>value==='release').length,1);assert.equal(f.app.active(),false);
  }
});
