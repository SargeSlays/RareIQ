'use strict';
const {cleanMeterStatus}=require('./audio-meters.cjs');
const {LiveAudioSession}=require('./live-audio-session.cjs');
const {randomUUID}=require('node:crypto');
const FORMATS=Object.freeze({hd:{width:1280,height:720},fullhd:{width:1920,height:1080},portrait:{width:720,height:1280}});
const START_FIELDS=new Set(['destinationId','destinationIds','format','profileId']);
const PUBLIC_ENCODER_FAILURE_CODES=Object.freeze([
  'shared_mux_unavailable','shared_encoder_start_failed','shared_encoder_shutdown_unconfirmed',
  'encoder_backpressure','twitch_vod_unavailable','twitch_vod_audio_missing','twitch_vod_audio_late','vod_audio_timeline_discontinuity',
  'invalid_encoder_config','destination_required','invalid_destination','secure_destination_required','nonpublic_destination','destination_dns_failed',
  'tls_trust_unavailable','tls_verification_failed','tls_connection_failed','encoder_transport_ownership_unavailable','encoder_transport_interrupted',
  'video_encoder_unavailable','encoder_input_ended','invalid_encoder_packet','invalid_audio_samples','audio_timeline_discontinuity','encoder_dependency_missing',
  'encoder_failed','encoder_start_timeout','encoder_spawn_failed','encoder_input_failed','encoder_protocol_failed','encoder_start_failed','encoder_exited','encoder_stop_timeout','encoder_runtime_required',
]);
const ENCODER_FAILURES=new Set(PUBLIC_ENCODER_FAILURE_CODES);
const PUBLIC_FAILURE_CODES=Object.freeze([...PUBLIC_ENCODER_FAILURE_CODES,
  'rehearsal_active','rehearsal_status_unavailable',
  'account_authorization_required','streaming_not_available','secure_ingest_unavailable','broadcast_selection_changed','youtube_broadcast_unavailable','youtube_broadcast_not_owned','youtube_stream_unavailable','youtube_stream_not_owned','youtube_stream_shared','account_state_changed','provider_rate_limited','authorization_refresh_required',
  'audio_mix_not_ready','audio_mix_unconfirmed','prepare_output','output_not_ready','output_generation_changed','broadcast_cancelled','desktop_backend_required','desktop_mode_required','desktop_closing',
  'close_browser_review','studio_unavailable','another_broadcast_active','output_lost','encoder_backpressure','capture_stop_unconfirmed','encoder_stop_unconfirmed','studio_status_unconfirmed','broadcast_start_failed',
  'output_review_open','output_receiver_changed','output_receiver_unavailable','output_capture_size_mismatch','output_navigated','output_renderer_unavailable','output_closed','output_frame_failed',
  'output_audio_stalled','output_video_sink_failed','output_audio_unavailable','output_audio_protocol_invalid','output_audio_sink_failed',
  'output_not_identified','output_not_rendered','program_not_ready','program_changed','preflight_unavailable','composition_not_rendered',
  'invalid_production_sources','camera_slot_unavailable','guest_source_unavailable','guest_output_not_ready','producer_screen_source_unavailable','producer_screen_output_not_ready','unavailable','unassigned','disconnected','stale',
  ...['image','video','text','browser'].flatMap(kind=>[kind+'_source_unavailable',kind+'_output_not_ready']),
]);
const PUBLIC_FAILURES=new Set(PUBLIC_FAILURE_CODES);
const safeReason=(value,fallback='encoder_failed')=>PUBLIC_FAILURES.has(value)?value:fallback;
const safeStats=value=>({codec:['h264_nvenc','libx264'].includes(value?.codec)?value.codec:null,
  frames:Number.isSafeInteger(value?.frames??value?.videoFrames)&&(value.frames??value.videoFrames)>=0?(value.frames??value.videoFrames):0,
  audioSamples:Number.isSafeInteger(value?.audioSamples)&&value.audioSamples>=0?value.audioSamples:0,
  ...Object.fromEntries(['bytesMuxed','queuedBytes','packets','droppedVideoFrames','droppedAudioPackets','droppedVodAudioPackets']
    .filter(key=>Number.isSafeInteger(value?.[key])&&value[key]>=0).map(key=>[key,value[key]]))});
class NativeBroadcast{
  constructor({destinations,outputProfiles,createCapture,createEncoder,createEncoderGroup,request,identity,ownerPid,confirm=async()=>false,canPublish=async()=>true,onState=()=>{},onAudioAudit=()=>{},clock=()=>Date.now()}={}){
    Object.assign(this,{destinations,outputProfiles,createCapture,createEncoder,createEncoderGroup,request,identity,ownerPid,confirm,canPublish,onState,onAudioAudit,clock});
    this.rehearsing=false;
    this.audioSession=null;this.targets=[];this.outputProfile=null;this.profileSignature=null;this.capture=null;this.encoder=null;this.encoderGroup=null;this.format='hd';this.phase='idle';this.failure=null;this.selected=null;this.preflight=null;this.operation=0;this.starting=false;this.preparing=false;this.stopping=null;this.reserving=null;this.ownsEncoding=false;this.unreadySince=null;this.lastStats=safeStats();
  }
  active(){return this.rehearsing||this.encoderGroup?.status?.().running===true||this.starting||['starting','sending','stopping'].includes(this.phase)||this.targets.some(t=>t.encoder?.status?.().running===true);}
  audioMixReady(){const state=this.audioSession?.status();return typeof this.capture?.updateAudioRouting!=='function'||Boolean(state?.outputId&&!state.uncertain&&!state.applying);}
  status(){
    const encoder=this.encoderGroup?.status?.()||this.encoder?.status?.(),own=this.capture?.status?.(),blocker=this.preflight?.blockers?.[0];
    const prepared=Boolean(this.capture)&&own?.prepared!==false;
    return {phase:this.phase,active:this.active(),format:this.format,prepared,ownershipPending:this.ownsEncoding&&!encoder?.running,
      ready:prepared&&this.preflight?.ready===true&&!this.active()&&!this.preparing&&!this.ownsEncoding&&this.audioMixReady(),
      reason:this.failure||(!this.active()&&!this.audioMixReady()?'audio_mix_not_ready':null)||(blocker?safeReason(blocker?.reason||blocker,'output_not_ready'):null),destinationId:this.selected,destinationIds:this.targets.map(t=>t.destinationId),profileId:this.outputProfile?.id||null,outputProfile:this.outputProfile,
      audioMix:this.audioSession?.status()||null,audioSourcesAvailable:own?.audioSourcesAvailable||[],audioMeters:cleanMeterStatus(own?.audioMeters),targets:this.targets.map(t=>({destinationId:t.destinationId,phase:t.phase,reason:t.reason,...safeStats(t.encoder?.status?.()||t.lastStats)})),
      ...(encoder?safeStats(encoder):this.lastStats),platformLiveVerified:false,vodPlatformVerified:false};
  }
  notify(){try{this.onState(this.status());}catch(_){} }
  async resolveProfile(value={}){
    if(value.profileId!==undefined){
      if(typeof value.profileId!=='string'||!this.outputProfiles)throw Error('invalid_output_profile');
      return this.outputProfiles.getProfile(value.profileId);
    }
    const format=value.format||'hd';if(!Object.hasOwn(FORMATS,format))throw Error('invalid_output_format');
    return {id:null,name:'Current format',format,fps:30,videoBitrateKbps:format==='fullhd'?6000:4000,codec:'auto',keyframeSeconds:2,audioBitrateKbps:192,twitchVod:false,audioRouting:{}};
  }
  async prepare(value={}){
    if(!value||Object.keys(value).some(k=>!['format','profileId'].includes(k)))throw Error('invalid_output_profile');
    if(this.active()||this.preparing||this.ownsEncoding)throw Error('broadcast_busy');
    const operation=++this.operation;this.preparing=true;
    this.audioSession?.close();this.audioSession=null;
    try{
      const profile=await this.resolveProfile(value),format=profile.format;
      if(operation!==this.operation)throw Error('broadcast_cancelled');
      if(!Object.hasOwn(FORMATS,format))throw Error('invalid_output_format');
      if(this.capture&&(this.profileSignature!==JSON.stringify(profile)||this.capture.status().error||this.capture.status().prepared===false)){await this.capture.close();this.capture=null;}
      if(operation!==this.operation)throw Error('broadcast_cancelled');
      this.format=format;this.outputProfile=structuredClone(profile);this.profileSignature=JSON.stringify(profile);this.failure=null;
      if(!this.capture)this.capture=this.createCapture({...FORMATS[format],fps:profile.fps,audioRouting:profile.audioRouting,requireVod:profile.twitchVod===true});
      await this.capture.prepare();if(operation!==this.operation)throw Error('broadcast_cancelled');
      if(typeof this.capture.updateAudioRouting==='function'){
        const preparedCapture=this.capture;
        await preparedCapture.updateAudioRouting({audioRouting:profile.audioRouting,requestId:randomUUID()});
        if(operation!==this.operation||preparedCapture!==this.capture)throw Error('broadcast_cancelled');
        const session=new LiveAudioSession({apply:value=>preparedCapture.updateAudioRouting(value),audit:value=>this.onAudioAudit(value)});
        session.init({outputId:randomUUID(),profileId:profile.id||'current-output',audioRouting:profile.audioRouting});this.audioSession=session;
      }
      await this.capture.review();if(operation!==this.operation)throw Error('broadcast_cancelled');
      this.phase='prepared';await this.check();this.preparing=false;return this.status();
    }finally{this.preparing=false;this.notify();}
  }
  async setLiveAudio(value){
    if(this.preparing||this.starting||this.stopping||this.phase==='stopping')throw Object.assign(Error('audio_routing_busy'),{code:'audio_routing_busy'});
    if(!this.capture||this.capture.status().prepared===false||this.capture.status().audioReady===false||this.capture.status().error||!this.audioSession)throw Object.assign(Error('audio_routing_unavailable'),{code:'audio_routing_unavailable'});
    try{await this.audioSession.set(value);return this.status();}finally{this.notify();}
  }
  async check(){if(this.checking)return this.checking;this.checking=this._check().finally(()=>{this.checking=null;});return this.checking;}
  async _check(){
    if(!this.capture||!this.identity){this.preflight={ready:false,blockers:['prepare_output']};return this.status();}
    const capture=this.capture,own=capture.status();let durableFailure=own.error?safeReason(own.error,'output_lost'):own.browserReviewOpen?'output_review_open':null;
    if(!own.peerId||!own.rendered||own.prepared===false||own.browserReviewOpen||own.audioBlocked||own.audioReady===false||own.error){this.preflight={ready:false,blockers:[own.browserReviewOpen?'close_browser_review':'output_not_ready']};}
    else{
      try{
        const value=await this.request('/api/production/native-preflight?output_peer_id='+encodeURIComponent(own.peerId));this.preflight=value.preflight;
        const latest=this.capture?.status();
        if(value.native_encoding?.active&&value.native_encoding.owner_pid!==this.ownerPid)this.preflight={ready:false,blockers:['another_broadcast_active']};
        if(this.capture!==capture||!latest||latest.peerId!==own.peerId||latest.generation!==this.preflight?.generation||!latest.rendered||latest.prepared===false||latest.browserReviewOpen||latest.audioBlocked||latest.audioReady===false||latest.error||this.preflight?.generation!==own.generation||this.preflight?.composition_id!==undefined&&(!/^[a-f0-9]{64}$/.test(this.preflight.composition_id)||own.programCompositionId!==this.preflight.composition_id||latest.programCompositionId!==this.preflight.composition_id))this.preflight={ready:false,blockers:['output_generation_changed']};
        if(latest?.error)durableFailure=safeReason(latest.error,'output_lost');else if(latest?.browserReviewOpen)durableFailure='output_review_open';
      }catch(_){this.preflight={ready:false,blockers:['studio_unavailable']};}
    }
    if(this.phase==='sending'){
      if(durableFailure)await this.stop(durableFailure);
      else if(this.preflight?.ready===true)this.unreadySince=null;
      else if(this.unreadySince===null)this.unreadySince=this.clock();
      else if(this.clock()-this.unreadySince>=6500)await this.stop('output_lost');
    }
    this.notify();return this.status();
  }
  async reserve(active){
    if(!this.identity)throw Error('desktop_backend_required');
    if(active){
      this.ownsEncoding=true;
      const reservation=Promise.resolve().then(()=>this.request('/api/desktop/encoding-status',{...this.identity,active:true,owner_pid:this.ownerPid}));
      this.reserving=reservation;
      try{await reservation;}finally{if(this.reserving===reservation)this.reserving=null;}
    }else{
      await this.request('/api/desktop/encoding-status',{...this.identity,active:false,owner_pid:this.ownerPid});this.ownsEncoding=false;
    }
  }
  async start(value){
    if(!value||Object.keys(value).some(key=>!START_FIELDS.has(key))||(value.destinationId!==undefined&&value.destinationIds!==undefined))throw Error('invalid_broadcast_request');
    const ids=value.destinationIds??[value.destinationId];
    if(!Array.isArray(ids)||ids.length<1||ids.length>8||ids.some(id=>typeof id!=='string'||!id||id.length>128)||new Set(ids).size!==ids.length)throw Error('invalid_broadcast_request');
    const policyOperation=this.operation;await this.assertPublishing();if(policyOperation!==this.operation)throw Error('broadcast_cancelled');
    if(this.active()||this.preparing)throw Error('broadcast_busy');if(this.ownsEncoding)throw Error('studio_status_unconfirmed');if(!this.audioMixReady())throw Error('audio_mix_unconfirmed');
    this.starting=true;const operation=++this.operation;let runFailure=null;
    const current=()=>operation===this.operation;
    const assertCurrent=()=>{if(!current())throw Error('broadcast_cancelled');};
    try{
      const settings=await this.resolveProfile(value);assertCurrent();
      if(!this.capture||this.profileSignature!==JSON.stringify(settings))throw Error('prepare_output');
      await this.check();assertCurrent();if(!this.preflight?.ready)throw Error('output_not_ready');
      const generation=this.preflight.generation,profiles=[];
      for(const id of ids){await this.assertPublishing();assertCurrent();profiles.push(await this.destinations.getPrivateDestination(id));assertCurrent();}
      await this.assertPublishing();assertCurrent();
      const approved=await this.confirm(profiles.length===1?profiles[0]:profiles,structuredClone(settings),{destinationIds:[...ids]});assertCurrent();await this.assertPublishing();assertCurrent();if(!approved){this.starting=false;return this.status();}
      // YouTube can change its bound stream or auto-start behavior while the
      // operator reviews confirmation. Revalidate the exact saved selection.
      for(let index=0;index<profiles.length;index++){
        const reviewed=profiles[index];if(reviewed.platform!=='youtube'||!reviewed.accountRef)continue;
        const refreshed=await this.destinations.getPrivateDestination(ids[index]);assertCurrent();
        if(refreshed.platform!=='youtube'||refreshed.accountRef!==reviewed.accountRef||refreshed.id!==reviewed.id||!reviewed.youtubeSelection||!refreshed.youtubeSelection||['broadcastId','streamId','settingsFingerprint','autoStart','autoStop','privacyStatus'].some(key=>refreshed.youtubeSelection[key]!==reviewed.youtubeSelection[key]))throw Error('broadcast_selection_changed');
        profiles[index]=refreshed;
      }
      await this.check();assertCurrent();if(!this.preflight?.ready||this.preflight.generation!==generation)throw Error('output_generation_changed');
      await this.assertPublishing();assertCurrent();
      this.targets=[];this.encoder=null;this.encoderGroup=null;this.selected=ids[0];this.phase='starting';this.failure=null;this.lastStats=safeStats();this.unreadySince=null;this.notify();await this.reserve(true);assertCurrent();await this.assertPublishing();assertCurrent();
      if(this.createEncoderGroup){
        const group=this.createEncoderGroup(snapshot=>{
          if(!current()||this.encoderGroup!==group)return;
          if(snapshot.state==='failed'||snapshot.error){runFailure=ENCODER_FAILURES.has(snapshot.code)?snapshot.code:'encoder_failed';this.stop(runFailure).catch(()=>{});}
        });
        this.encoderGroup=group;
      }
      for(let index=0;index<ids.length;index++){
        const target={destinationId:ids[index],encoder:null,phase:'starting',reason:null,lastStats:safeStats(),vod:settings.twitchVod===true&&profiles[index].platform==='twitch'};
        this.targets.push(target);
        const observe=snapshot=>{
          if(!current()||!this.targets.includes(target)||target.encoder!==encoder||!['starting','sending'].includes(target.phase))return;
          if(snapshot.state==='failed'||snapshot.phase==='failed'||snapshot.error||snapshot.state==='stopped'||snapshot.running===false){
            const reason=ENCODER_FAILURES.has(snapshot.code)?snapshot.code:'encoder_failed';
            if(this.starting){runFailure=reason;this.stop(reason).catch(()=>{});}
            else this.stopTarget(target.destinationId,reason).catch(()=>{});
          }else if(safeStats(snapshot).frames>0){target.phase='sending';this.phase='sending';this.notify();}
        };
        const encoder=this.encoderGroup?this.encoderGroup.createTarget(target.destinationId,observe):this.createEncoder(observe);
        target.encoder=encoder;if(!this.encoder)this.encoder=encoder;
        if(!this.encoderGroup)await encoder.start({destination:this.encoderDestination(profiles[index]),...FORMATS[settings.format],fps:settings.fps,bitrate:settings.videoBitrateKbps*1000,codec:settings.codec,keyframeSeconds:settings.keyframeSeconds,audioBitrateKbps:settings.audioBitrateKbps,twitchVod:target.vod});assertCurrent();
      }
      if(this.encoderGroup){
        await this.encoderGroup.start({...FORMATS[settings.format],fps:settings.fps,bitrate:settings.videoBitrateKbps*1000,codec:settings.codec,keyframeSeconds:settings.keyframeSeconds,audioBitrateKbps:settings.audioBitrateKbps,
          twitchVod:this.targets.some(t=>t.vod),targets:this.targets.map((t,i)=>({id:t.destinationId,destination:this.encoderDestination(profiles[i]),twitchVod:t.vod}))});assertCurrent();
      }
      await this.check();assertCurrent();if(!this.preflight?.ready||this.preflight.generation!==generation)throw Error('output_generation_changed');
      const send=(method,buffer,pts,vod)=>{
        if(!current())return false;
        if(this.encoderGroup){
          let accepted=false;
          try{accepted=this.encoderGroup[method](buffer,pts)!==false;if(method==='sendAudio'&&this.targets.some(t=>t.vod))accepted=this.encoderGroup.sendVodAudio(vod,pts)!==false&&accepted;}catch(_){}
          if(!accepted){runFailure='encoder_backpressure';this.stop(runFailure).catch(()=>{});}return accepted;
        }
        for(const target of this.targets){
          if(!['starting','sending'].includes(target.phase))continue;
          let accepted=false;
          try{accepted=target.encoder[method](buffer,pts)!==false;if(method==='sendAudio'&&target.vod)accepted=target.encoder.sendVodAudio(vod,pts)!==false&&accepted;}catch(_){}
          if(!accepted){if(this.starting){runFailure='encoder_backpressure';this.stop(runFailure).catch(()=>{});}else this.stopTarget(target.destinationId,'encoder_backpressure').catch(()=>{});}
        }
        return true; // A destination fault is isolated; shared output faults stop all.
      };
      await this.capture.startCapture((buffer,pts)=>send('sendVideo',buffer,pts),(buffer,pts,vod)=>send('sendAudio',buffer,pts,vod));assertCurrent();
      return this.status();
    }catch(error){
      const cancelled=!current();
      const reason=runFailure||(cancelled?'broadcast_cancelled':ENCODER_FAILURES.has(error?.code)?error.code:safeReason(error?.message,'broadcast_start_failed'));
      if(!cancelled)await this.stop(reason);else if(this.stopping)await this.stopping;
      throw Error(reason);
    }finally{this.starting=false;this.notify();}
  }
  async assertPublishing(){
    let allowed;try{allowed=await this.canPublish();}catch(_){throw Error('rehearsal_status_unavailable');}
    if(allowed!==true||this.rehearsing)throw Error('rehearsal_active');
  }
  encoderDestination(value){return Object.fromEntries(['id','serverUrl','streamKey','platform','name','networkVerified','allowInsecureRtmp'].filter(key=>Object.hasOwn(value,key)).map(key=>[key,value[key]]));}
  async stopTarget(destinationId,reason=null){
    if(typeof destinationId!=='string')throw Error('invalid_broadcast_request');
    if(this.starting)throw Error('broadcast_busy');
    const target=this.targets.find(t=>t.destinationId===destinationId);if(!target)throw Error('invalid_broadcast_request');
    if(target.stopping)return target.stopping;
    target.phase='stopping';target.reason=reason===null?null:safeReason(reason);this.notify();
    target.stopping=(async()=>{
      try{await target.encoder?.stop();}catch(_){target.reason='encoder_stop_unconfirmed';}
      target.lastStats=safeStats(target.encoder?.status?.());
      if(target.encoder?.status?.().running===true){target.phase='failed';target.reason='encoder_stop_unconfirmed';this.failure='encoder_stop_unconfirmed';this.notify();return this.status();}
      target.phase=target.reason?'failed':'stopped';target.encoder=null;
      const live=this.targets.some(t=>['starting','sending','stopping'].includes(t.phase)||t.encoder?.status?.().running===true);
      if(!live){this.lastStats=target.lastStats;await this.stop(target.reason);}
      else{this.encoder=this.targets.find(t=>t.encoder)?.encoder||null;this.notify();}
      return this.status();
    })().finally(()=>{target.stopping=null;});return target.stopping;
  }
  async stop(reason=null){
    if(this.stopping)return this.stopping;
    reason=reason===null?null:safeReason(reason);++this.operation;this.phase='stopping';this.notify();
    this.stopping=(async()=>{
      try{await this.capture?.stopCapture();}catch(_){reason=reason||'capture_stop_unconfirmed';}
      if(this.encoderGroup){try{await this.encoderGroup.stop();}catch(_){reason=reason||'encoder_stop_unconfirmed';}}
      await Promise.all(this.targets.map(async target=>{
        target.phase='stopping';
        try{if(!this.encoderGroup)await target.encoder?.stop();}catch(_){reason=reason||'encoder_stop_unconfirmed';}
        if(target.encoder)target.lastStats=safeStats(target.encoder.status?.());
        target.reason=target.reason||reason;target.phase=target.reason?'failed':'stopped';
      }));
      const encoder=this.encoderGroup?.status?.()||this.encoder?.status?.();if(encoder)this.lastStats=safeStats(encoder);
      if(this.encoderGroup?.status?.().running===true||this.targets.some(t=>t.encoder?.status?.().running===true)){this.phase='failed';this.failure='encoder_stop_unconfirmed';this.notify();return this.status();}
      this.encoder=null;this.encoderGroup=null;for(const t of this.targets)t.encoder=null;
      // A cancellation must clear ownership after an in-flight reservation settles.
      if(this.reserving){try{await this.reserving;}catch(_){} }
      if(this.ownsEncoding){try{await this.reserve(false);}catch(_){reason='studio_status_unconfirmed';}}
      this.phase=reason?'failed':this.capture?'prepared':'idle';this.failure=reason;this.unreadySince=null;this.notify();
      return this.status();
    })().finally(()=>{this.stopping=null;});return this.stopping;
  }
  async close(){await this.stop();if(this.encoderGroup?.status?.().running===true||this.targets.some(t=>t.encoder?.status?.().running===true)||this.ownsEncoding)return false;this.audioSession?.close();this.audioSession=null;await this.capture?.close();this.capture=null;this.preflight=null;this.phase='idle';return true;}
}
module.exports={NativeBroadcast,FORMATS,PUBLIC_ENCODER_FAILURE_CODES,PUBLIC_FAILURE_CODES};
