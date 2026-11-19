'use strict';
const path=require('node:path'),{inspectRecordingPath}=require('./recording-file-store.cjs');
const FORMATS={hd:{width:1280,height:720},fullhd:{width:1920,height:1080},portrait:{width:720,height:1280}};
const CODES=new Set(['recording_cancelled','recording_busy','recording_file_exists','invalid_recording_file','recording_storage_unavailable','insufficient_recording_space','recording_finalize_failed','recording_output_unavailable','recording_start_failed','recording_stop_unconfirmed','recording_ownership_unconfirmed','prepare_output','output_not_ready','output_generation_changed','rehearsal_active','rehearsal_status_unavailable','encoder_backpressure','encoder_failed','encoder_start_timeout','encoder_spawn_failed','video_encoder_unavailable','encoder_dependency_missing','encoder_stop_timeout','shared_encoder_start_failed','shared_encoder_shutdown_unconfirmed']);
const fail=code=>Object.assign(Error(code),{code}),safe=(value,fallback='recording_start_failed')=>CODES.has(value?.code||value?.message)?value.code||value.message:fallback;
const counters=value=>Object.fromEntries(['videoFrames','audioSamples','bytesMuxed','recordingBytes','droppedVideoFrames','droppedAudioPackets'].filter(key=>Number.isSafeInteger(value?.[key])&&value[key]>=0).map(key=>[key,value[key]]));
class NativeRecording{
  constructor({getCapture,getProfile,checkReady,request,identity,ownerPid,createEncoderGroup,canPublish=async()=>false,chooseFile,confirm=async()=>false,inspectFile=inspectRecordingPath,onState=()=>{},clock=()=>Date.now()}={}){
    Object.assign(this,{getCapture,getProfile,checkReady,request,identity,ownerPid,createEncoderGroup,canPublish,chooseFile,confirm,inspectFile,onState,clock});this.phase='idle';this.reason=null;this.capture=null;this.group=null;this.ownsEncoding=false;this.operation=0;this.starting=false;this.stopping=null;this.reserving=null;this.pendingStart=null;this.receipts=new Map();this.fileName=null;this.savedPath=null;this.last={};this.finalized=false;this.startedAt=null;this.elapsedMs=0;this.unreadySince=null;
  }
  active(){return this.starting||Boolean(this.stopping)||this.ownsEncoding||this.group?.status?.().running===true||['starting','recording','stopping'].includes(this.phase);}
  status(){const current=this.group?.status?.(),stats={...this.last,...counters(current)};return {phase:this.phase,active:this.active(),running:current?.running===true,reason:this.reason,fileName:this.fileName,ownershipPending:this.ownsEncoding&&current?.running!==true,finalized:this.finalized,...stats,frames:stats.videoFrames||0,bytesWritten:stats.recordingBytes||stats.bytesMuxed||0,elapsedMs:this.startedAt===null?this.elapsedMs:Math.max(0,this.clock()-this.startedAt),codec:['h264_nvenc','libx264'].includes(current?.codec)?current.codec:this.last.codec||null,container:'mkv',audioTracks:1,platformLiveVerified:false};}
  getSavedPath(){return this.finalized?this.savedPath:null;}
  async check(){
    if(this.phase!=='recording'||this.starting||this.stopping)return this.status();const operation=this.operation,capture=this.capture;
    let ready=false;try{const checked=await this.checkReady(),own=capture?.status?.();ready=checked?.ready===true&&own?.prepared===true&&own?.rendered===true&&!own.error&&own.audioReady!==false&&!own.browserReviewOpen&&(checked.generation===undefined||checked.generation===own.generation);}catch(_){}
    if(operation!==this.operation||capture!==this.capture)return this.status();
    if(ready)this.unreadySince=null;else if(capture?.status?.().error)await this.stop('recording_output_unavailable');else if(this.unreadySince===null)this.unreadySince=this.clock();else if(this.clock()-this.unreadySince>=6500)await this.stop('recording_output_unavailable');return this.status();
  }
  notify(){try{this.onState(this.status());}catch(_){} }
  async allowed(){let permitted;try{permitted=await this.canPublish();}catch(_){throw fail('rehearsal_status_unavailable');}if(permitted!==true)throw fail('rehearsal_active');}
  async reserve(active){if(!this.identity||typeof this.request!=='function')throw fail('recording_ownership_unconfirmed');if(active){this.ownsEncoding=true;this.reserving=Promise.resolve().then(()=>this.request('/api/desktop/encoding-status',{...this.identity,active:true,owner_pid:this.ownerPid}));try{await this.reserving;}finally{this.reserving=null;}}else{await this.request('/api/desktop/encoding-status',{...this.identity,active:false,owner_pid:this.ownerPid});this.ownsEncoding=false;}}
  start(value,{current:requestCurrent=()=>true}={}){
    if(!value||Object.keys(value).some(key=>key!=='requestId')||typeof value.requestId!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId))return Promise.reject(fail('invalid_recording_file'));
    if(this.receipts.has(value.requestId))return this.receipts.get(value.requestId);
    if(this.active())return Promise.reject(fail('recording_busy'));
    const operation=++this.operation;this.starting=true;this.reason=null;this.finalized=false;this.fileName=null;this.savedPath=null;this.startedAt=null;this.elapsedMs=0;this.unreadySince=null;this.phase='choosing';this.notify();
    let committed=false;const ownsOperation=()=>operation===this.operation,current=()=>ownsOperation()&&(committed||requestCurrent()),assertCurrent=()=>{if(!current())throw fail('recording_cancelled');};
    const run=(async()=>{
      try{
        await this.allowed();assertCurrent();const profile=structuredClone(await this.getProfile());assertCurrent();
        if(!profile?.id||!FORMATS[profile.format])throw fail('prepare_output');
        const ready=await this.checkReady();assertCurrent();if(ready?.ready!==true)throw fail('output_not_ready');
        const capture=await this.getCapture();assertCurrent();const before=capture?.status?.();if(!capture||!before?.prepared||!before.peerId||!before.rendered||before.error||before.audioReady===false||before.browserReviewOpen||ready.generation!==undefined&&ready.generation!==before.generation)throw fail('output_not_ready');
        const selected=await this.chooseFile({profile});assertCurrent();if(!selected){this.phase='idle';return this.status();}
        const recordingFile=await this.inspectFile(selected);assertCurrent();this.phase='confirming';this.notify();
        if(!await this.confirm({fileName:path.basename(recordingFile.path),profile})){assertCurrent();this.phase='idle';return this.status();}assertCurrent();await this.allowed();assertCurrent();
        if(JSON.stringify(await this.getProfile())!==JSON.stringify(profile))throw fail('output_generation_changed');assertCurrent();
        const checked=await this.checkReady();assertCurrent();const after=capture.status();if(checked?.ready!==true||checked.generation!==undefined&&checked.generation!==after.generation||after.peerId!==before.peerId||after.generation!==before.generation||!after.prepared||!after.rendered||after.error||after.audioReady===false||after.browserReviewOpen)throw fail('output_generation_changed');
        this.capture=capture;this.fileName=path.basename(recordingFile.path);this.savedPath=recordingFile.path;this.last={};this.phase='starting';this.notify();await this.reserve(true);assertCurrent();await this.allowed();assertCurrent();
        let group;const observe=snapshot=>{if(!group||!current()||this.group!==group)return;if(snapshot.state==='failed'||snapshot.code)this.stop(safe({code:snapshot.code},'encoder_failed')).catch(()=>{});else if(snapshot.videoFrames>0){this.phase='recording';this.notify();}};
        group=this.createEncoderGroup(observe,{recordingFile});this.group=group;group.createTarget?.('recording-local',observe);
        await group.start({...FORMATS[profile.format],fps:profile.fps,bitrate:profile.videoBitrateKbps*1000,codec:profile.codec,keyframeSeconds:profile.keyframeSeconds,audioBitrateKbps:profile.audioBitrateKbps,twitchVod:false,targets:[{id:'recording-local',recording:true,twitchVod:false}]});assertCurrent();
        // Worker preparation can outlive the reviewed Program. Recheck the exact
        // receiver/profile before subscribing to any media, as broadcasting does.
        const startedReady=await this.checkReady();assertCurrent();const startedProfile=await this.getProfile();assertCurrent();const startedCapture=capture.status();
        if(startedReady?.ready!==true||JSON.stringify(startedProfile)!==JSON.stringify(profile)||startedCapture?.peerId!==before.peerId||startedCapture.generation!==before.generation||startedReady.generation!==undefined&&startedReady.generation!==startedCapture.generation||!startedCapture.prepared||!startedCapture.rendered||startedCapture.error||startedCapture.audioReady===false||startedCapture.browserReviewOpen)throw fail('output_generation_changed');
        const send=(method,buffer,pts)=>{if(!current())return false;let accepted=false;try{accepted=group[method](buffer,pts)!==false;}catch(_){}if(!accepted)this.stop('encoder_backpressure').catch(()=>{});return accepted;};
        await capture.startCapture((buffer,pts)=>send('sendVideo',buffer,pts),(buffer,pts)=>send('sendAudio',buffer,pts));assertCurrent();committed=true;this.startedAt=this.clock();this.phase='recording';return this.status();
      }catch(error){const code=current()?safe(error):this.reason||'recording_cancelled';if(ownsOperation())await this.stop(code);else if(this.stopping)await this.stopping;throw fail(code);}
      finally{this.starting=false;if(this.pendingStart===run)this.pendingStart=null;this.notify();}
    })();this.pendingStart=run;const completed=run.then(()=>this.status());this.receipts.set(value.requestId,completed);if(this.receipts.size>32)this.receipts.delete(this.receipts.keys().next().value);return completed;
  }
  stop(reason=null){
    if(this.stopping)return this.stopping;
    // Repeated Stop and idle application shutdown must preserve a saved receipt.
    // A chooser/start operation still needs cancellation even before it owns work.
    if(!this.starting&&!this.capture&&!this.group&&!this.ownsEncoding&&!this.reserving)return Promise.resolve(this.status());
    ++this.operation;this.phase='stopping';if(reason)this.reason=CODES.has(reason)?reason:'encoder_failed';this.notify();
    const work=(async()=>{
      let uncertain=false;try{await this.reserving;}catch(_){}
      try{await this.capture?.stopCapture();}catch(_){uncertain=true;this.reason='recording_stop_unconfirmed';}
      let result;try{result=await this.group?.stop();if(result?.running){uncertain=true;this.reason='recording_stop_unconfirmed';}}catch(_){uncertain=true;this.reason='recording_stop_unconfirmed';}
      this.last={...this.last,...counters(result)};if(['h264_nvenc','libx264'].includes(result?.codec))this.last.codec=result.codec;
      if(!uncertain){this.capture=null;if(this.ownsEncoding)try{await this.reserve(false);}catch(_){uncertain=true;this.reason='recording_ownership_unconfirmed';}}
      if(!uncertain){if(this.startedAt!==null)this.elapsedMs=Math.max(0,this.clock()-this.startedAt);this.startedAt=null;this.finalized=Boolean(result?.recordingFinalized&&!this.reason);if(this.fileName&&!this.finalized&&!this.reason)this.reason='recording_finalize_failed';this.phase=this.reason?'failed':this.finalized?'saved':'idle';this.group=null;}else this.phase='failed';
    })();const pending=work.finally(()=>{if(this.stopping===pending)this.stopping=null;this.notify();}).then(()=>this.status());this.stopping=pending;return pending;
  }
}
module.exports={NativeRecording};
