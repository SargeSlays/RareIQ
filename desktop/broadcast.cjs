'use strict';
const FORMATS=Object.freeze({hd:{width:1280,height:720},fullhd:{width:1920,height:1080},portrait:{width:720,height:1280}});
const START_FIELDS=new Set(['destinationId','format']);
const PUBLIC_ENCODER_FAILURE_CODES=Object.freeze([
  'invalid_encoder_config','destination_required','invalid_destination','secure_destination_required','nonpublic_destination','destination_dns_failed',
  'tls_trust_unavailable','tls_verification_failed','tls_connection_failed','encoder_transport_ownership_unavailable','encoder_transport_interrupted',
  'video_encoder_unavailable','encoder_input_ended','invalid_encoder_packet','invalid_audio_samples','audio_timeline_discontinuity','encoder_dependency_missing',
  'encoder_failed','encoder_start_timeout','encoder_spawn_failed','encoder_input_failed','encoder_protocol_failed','encoder_start_failed','encoder_exited','encoder_stop_timeout','encoder_runtime_required',
]);
const ENCODER_FAILURES=new Set(PUBLIC_ENCODER_FAILURE_CODES);
const PUBLIC_FAILURE_CODES=Object.freeze([...PUBLIC_ENCODER_FAILURE_CODES,
  'prepare_output','output_not_ready','output_generation_changed','broadcast_cancelled','desktop_backend_required','desktop_mode_required','desktop_closing',
  'close_browser_review','studio_unavailable','another_broadcast_active','output_lost','encoder_backpressure','capture_stop_unconfirmed','encoder_stop_unconfirmed','studio_status_unconfirmed','broadcast_start_failed',
  'output_review_open','output_receiver_changed','output_receiver_unavailable','output_capture_size_mismatch','output_navigated','output_renderer_unavailable','output_closed','output_frame_failed',
  'output_audio_stalled','output_video_sink_failed','output_audio_unavailable','output_audio_protocol_invalid','output_audio_sink_failed',
  'output_not_identified','output_not_rendered','program_not_ready','program_changed','preflight_unavailable','composition_not_rendered',
  'invalid_production_sources','camera_slot_unavailable','guest_source_unavailable','guest_output_not_ready','unavailable','unassigned','disconnected','stale',
  ...['image','video','text','browser'].flatMap(kind=>[kind+'_source_unavailable',kind+'_output_not_ready']),
]);
const PUBLIC_FAILURES=new Set(PUBLIC_FAILURE_CODES);
const safeReason=(value,fallback='encoder_failed')=>PUBLIC_FAILURES.has(value)?value:fallback;
const safeStats=value=>({codec:['h264_nvenc','libx264'].includes(value?.codec)?value.codec:null,
  frames:Number.isSafeInteger(value?.frames??value?.videoFrames)&&(value.frames??value.videoFrames)>=0?(value.frames??value.videoFrames):0,
  audioSamples:Number.isSafeInteger(value?.audioSamples)&&value.audioSamples>=0?value.audioSamples:0});
class NativeBroadcast{
  constructor({destinations,createCapture,createEncoder,request,identity,ownerPid,confirm=async()=>false,onState=()=>{},clock=()=>Date.now()}={}){
    Object.assign(this,{destinations,createCapture,createEncoder,request,identity,ownerPid,confirm,onState,clock});
    this.capture=null;this.encoder=null;this.format='hd';this.phase='idle';this.failure=null;this.selected=null;this.preflight=null;this.operation=0;this.starting=false;this.preparing=false;this.stopping=null;this.reserving=null;this.ownsEncoding=false;this.unreadySince=null;this.lastStats=safeStats();
  }
  active(){return this.starting||['starting','sending','stopping'].includes(this.phase)||this.encoder?.status?.().running===true;}
  status(){
    const encoder=this.encoder?.status?.(),own=this.capture?.status?.(),blocker=this.preflight?.blockers?.[0];
    const prepared=Boolean(this.capture)&&own?.prepared!==false;
    return {phase:this.phase,active:this.active(),format:this.format,prepared,ownershipPending:this.ownsEncoding&&!encoder?.running,
      ready:prepared&&this.preflight?.ready===true&&!this.active()&&!this.preparing&&!this.ownsEncoding,
      reason:this.failure||(blocker?safeReason(blocker?.reason||blocker,'output_not_ready'):null),destinationId:this.selected,
      ...(encoder?safeStats(encoder):this.lastStats),platformLiveVerified:false};
  }
  notify(){try{this.onState(this.status());}catch(_){} }
  async prepare({format='hd'}={}){
    if(this.active()||this.preparing||this.ownsEncoding)throw Error('broadcast_busy');if(!Object.hasOwn(FORMATS,format))throw Error('invalid_output_format');
    const operation=++this.operation;this.preparing=true;
    try{
      if(this.capture&&(this.format!==format||this.capture.status().error||this.capture.status().prepared===false)){await this.capture.close();this.capture=null;}
      if(operation!==this.operation)throw Error('broadcast_cancelled');
      this.format=format;this.failure=null;
      if(!this.capture)this.capture=this.createCapture(FORMATS[format]);
      await this.capture.prepare();if(operation!==this.operation)throw Error('broadcast_cancelled');
      await this.capture.review();if(operation!==this.operation)throw Error('broadcast_cancelled');
      this.phase='prepared';await this.check();this.preparing=false;return this.status();
    }finally{this.preparing=false;this.notify();}
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
        if(this.capture!==capture||!latest||latest.peerId!==own.peerId||latest.generation!==this.preflight?.generation||!latest.rendered||latest.prepared===false||latest.browserReviewOpen||latest.audioBlocked||latest.audioReady===false||latest.error||this.preflight?.generation!==own.generation)this.preflight={ready:false,blockers:['output_generation_changed']};
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
    if(!value||Object.keys(value).some(key=>!START_FIELDS.has(key))||typeof value.destinationId!=='string'||!Object.hasOwn(FORMATS,value.format||'hd'))throw Error('invalid_broadcast_request');
    if(this.active()||this.preparing)throw Error('broadcast_busy');if(this.ownsEncoding)throw Error('studio_status_unconfirmed');
    this.starting=true;const operation=++this.operation;let runFailure=null,encoder;
    const current=()=>operation===this.operation;
    const assertCurrent=()=>{if(!current())throw Error('broadcast_cancelled');};
    try{
      if(!this.capture||this.format!==(value.format||'hd'))throw Error('prepare_output');
      await this.check();assertCurrent();if(!this.preflight?.ready)throw Error('output_not_ready');
      const generation=this.preflight.generation,profile=await this.destinations.getPrivateDestination(value.destinationId);assertCurrent();
      const approved=await this.confirm(profile);assertCurrent();if(!approved){this.starting=false;return this.status();}
      await this.check();assertCurrent();if(!this.preflight?.ready||this.preflight.generation!==generation)throw Error('output_generation_changed');
      this.selected=value.destinationId;this.phase='starting';this.failure=null;this.lastStats=safeStats();this.unreadySince=null;this.notify();await this.reserve(true);assertCurrent();
      encoder=this.createEncoder(snapshot=>{
        if(!current()||this.encoder!==encoder)return;
        if(this.phase==='starting'||this.phase==='sending'){
          if(snapshot.state==='failed'||snapshot.phase==='failed'||snapshot.error||snapshot.state==='stopped'||snapshot.running===false){runFailure=ENCODER_FAILURES.has(snapshot.code)?snapshot.code:'encoder_failed';this.stop(runFailure).catch(()=>{});}
          else if(safeStats(snapshot).frames>0){this.phase='sending';this.notify();}
        }
      });
      this.encoder=encoder;
      await encoder.start({destination:profile,...FORMATS[this.format],fps:30,bitrate:this.format==='fullhd'?6000000:4000000,codec:'auto'});assertCurrent();
      await this.check();assertCurrent();if(!this.preflight?.ready||this.preflight.generation!==generation)throw Error('output_generation_changed');
      const send=(method,buffer,pts)=>{
        if(!current()||this.encoder!==encoder)return false;
        const accepted=encoder[method](buffer,pts);if(accepted===false)this.stop('encoder_backpressure').catch(()=>{});return accepted;
      };
      await this.capture.startCapture((buffer,pts)=>send('sendVideo',buffer,pts),(buffer,pts)=>send('sendAudio',buffer,pts));assertCurrent();
      return this.status();
    }catch(error){
      const cancelled=!current();
      const reason=runFailure||(cancelled?'broadcast_cancelled':ENCODER_FAILURES.has(error?.code)?error.code:safeReason(error?.message,'broadcast_start_failed'));
      if(!cancelled)await this.stop(reason);else if(this.stopping)await this.stopping;
      throw Error(reason);
    }finally{this.starting=false;this.notify();}
  }
  async stop(reason=null){
    if(this.stopping)return this.stopping;
    reason=reason===null?null:safeReason(reason);++this.operation;this.phase='stopping';this.notify();
    this.stopping=(async()=>{
      try{await this.capture?.stopCapture();}catch(_){reason=reason||'capture_stop_unconfirmed';}
      try{await this.encoder?.stop();}catch(_){reason=reason||'encoder_stop_unconfirmed';}
      const encoder=this.encoder?.status?.();if(encoder)this.lastStats=safeStats(encoder);
      if(encoder?.running===true){this.phase='failed';this.failure='encoder_stop_unconfirmed';this.notify();return this.status();}
      this.encoder=null;
      // A cancellation must clear ownership after an in-flight reservation settles.
      if(this.reserving){try{await this.reserving;}catch(_){} }
      if(this.ownsEncoding){try{await this.reserve(false);}catch(_){reason='studio_status_unconfirmed';}}
      this.phase=reason?'failed':this.capture?'prepared':'idle';this.failure=reason;this.unreadySince=null;this.notify();
      return this.status();
    })().finally(()=>{this.stopping=null;});return this.stopping;
  }
  async close(){await this.stop();if(this.encoder?.status?.().running===true||this.ownsEncoding)return false;await this.capture?.close();this.capture=null;this.preflight=null;this.phase='idle';return true;}
}
module.exports={NativeBroadcast,FORMATS,PUBLIC_ENCODER_FAILURE_CODES,PUBLIC_FAILURE_CODES};
