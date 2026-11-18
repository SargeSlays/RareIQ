'use strict';
const FORMATS=Object.freeze({hd:{width:1280,height:720},fullhd:{width:1920,height:1080},portrait:{width:720,height:1280}});
const START_FIELDS=new Set(['destinationId','format']);
class NativeBroadcast{
  constructor({destinations,createCapture,createEncoder,request,identity,ownerPid,confirm=async()=>false,onState=()=>{},clock=()=>Date.now()}={}){
    Object.assign(this,{destinations,createCapture,createEncoder,request,identity,ownerPid,confirm,onState,clock});
    this.capture=null;this.encoder=null;this.format='hd';this.phase='idle';this.failure=null;this.selected=null;this.preflight=null;this.operation=0;this.starting=false;this.stopping=null;this.ownsEncoding=false;this.unreadySince=0;
  }
  active(){return this.starting||['starting','sending','stopping'].includes(this.phase)||this.encoder?.status?.().running===true;}
  status(){const encoder=this.encoder?.status?.()||{};return {phase:this.phase,active:this.active(),format:this.format,prepared:Boolean(this.capture),ready:this.preflight?.ready===true&&!this.active(),reason:this.failure||this.preflight?.blockers?.[0]?.reason||this.preflight?.blockers?.[0]||null,destinationId:this.selected,codec:encoder.codec||null,frames:encoder.frames||encoder.videoFrames||0,audioSamples:encoder.audioSamples||0,platformLiveVerified:false};}
  notify(){try{this.onState(this.status());}catch(_){}}
  async prepare({format='hd'}={}){
    if(this.active()||this.starting)throw Error('broadcast_busy');if(!FORMATS[format])throw Error('invalid_output_format');
    if(this.capture&&(this.format!==format||this.capture.status().error)){await this.capture.close();this.capture=null;}
    this.format=format;this.failure=null;
    if(!this.capture)this.capture=this.createCapture(FORMATS[format]);
    await this.capture.prepare();await this.capture.review();this.phase='prepared';await this.check();return this.status();
  }
  async check(){if(this.checking)return this.checking;this.checking=this._check().finally(()=>{this.checking=null;});return this.checking;}
  async _check(){
    if(!this.capture||!this.identity){this.preflight={ready:false,blockers:['prepare_output']};return this.status();}
    const own=this.capture.status();
    if(!own.peerId||!own.rendered||own.browserReviewOpen||own.audioBlocked||own.audioReady===false||own.error){this.preflight={ready:false,blockers:[own.browserReviewOpen?'close_browser_review':'output_not_ready']};}
    else{
      try{const value=await this.request('/api/production/native-preflight?output_peer_id='+encodeURIComponent(own.peerId));this.preflight=value.preflight;const latest=this.capture?.status();if(value.native_encoding?.active&&value.native_encoding.owner_pid!==this.ownerPid)this.preflight={ready:false,blockers:['another_broadcast_active']};if(!latest||latest.peerId!==own.peerId||latest.generation!==this.preflight?.generation||!latest.rendered||latest.browserReviewOpen||latest.audioBlocked||this.preflight?.generation!==own.generation)this.preflight={ready:false,blockers:['output_generation_changed']};}catch(_){this.preflight={ready:false,blockers:['studio_unavailable']};}
    }
    if(this.phase==='sending'){
      if(this.preflight?.ready===true)this.unreadySince=0;
      else if(!this.unreadySince)this.unreadySince=this.clock();
      else if(this.clock()-this.unreadySince>6500)await this.stop('output_lost');
    }
    this.notify();return this.status();
  }
  async reserve(active){
    if(!this.identity)throw Error('desktop_backend_required');
    if(active)this.ownsEncoding=true;
    await this.request('/api/desktop/encoding-status',{...this.identity,active,owner_pid:this.ownerPid});this.ownsEncoding=active;
  }
  async start(value){
    if(!value||Object.keys(value).some(key=>!START_FIELDS.has(key))||typeof value.destinationId!=='string'||!FORMATS[value.format||'hd'])throw Error('invalid_broadcast_request');
    if(this.active()||this.starting)throw Error('broadcast_busy');
    this.starting=true;const operation=++this.operation;
    try{
      if(!this.capture||this.format!==(value.format||'hd'))throw Error('prepare_output');
      await this.check();if(!this.preflight?.ready)throw Error('output_not_ready');
      const generation=this.preflight.generation,profile=await this.destinations.getPrivateDestination(value.destinationId);
      if(!await this.confirm(profile))return this.status();
      if(operation!==this.operation)throw Error('broadcast_cancelled');
      await this.check();if(!this.preflight?.ready||this.preflight.generation!==generation)throw Error('output_generation_changed');
      this.selected=value.destinationId;this.phase='starting';this.failure=null;this.notify();await this.reserve(true);
      if(operation!==this.operation)throw Error('broadcast_cancelled');
      this.encoder=this.createEncoder(snapshot=>{
        if(this.phase==='starting'||this.phase==='sending'){
          if(snapshot.state==='failed'||snapshot.phase==='failed'||snapshot.error||snapshot.state==='stopped'||snapshot.running===false)this.stop('encoder_failed').catch(()=>{});
          else if((snapshot.frames||snapshot.videoFrames||0)>0){this.phase='sending';this.notify();}
        }
      });
      await this.encoder.start({destination:profile,...FORMATS[this.format],fps:30,bitrate:this.format==='fullhd'?6000000:4000000,codec:'auto'});
      if(operation!==this.operation)throw Error('broadcast_cancelled');
      await this.check();if(!this.preflight?.ready||this.preflight.generation!==generation)throw Error('output_generation_changed');
      await this.capture.startCapture((buffer,pts)=>{const accepted=this.encoder?.sendVideo(buffer,pts);if(accepted===false)this.stop('encoder_backpressure').catch(()=>{});return accepted;},(buffer,pts)=>{const accepted=this.encoder?.sendAudio(buffer,pts);if(accepted===false)this.stop('encoder_backpressure').catch(()=>{});return accepted;});
      return this.status();
    }catch(error){
      const reason=['prepare_output','output_not_ready','output_generation_changed','broadcast_cancelled','desktop_backend_required'].includes(error.message)?error.message:'broadcast_start_failed';
      await this.stop(reason);throw Error(reason);
    }finally{this.starting=false;this.notify();}
  }
  async stop(reason=null){
    if(this.stopping)return this.stopping;
    ++this.operation;this.phase='stopping';this.notify();
    this.stopping=(async()=>{
      try{await this.capture?.stopCapture();}catch(_){reason=reason||'capture_stop_unconfirmed';}
      try{await this.encoder?.stop();}catch(_){reason=reason||'encoder_stop_unconfirmed';}
      if(this.encoder?.status?.().running===true){this.phase='failed';this.failure='encoder_stop_unconfirmed';this.notify();return this.status();}
      this.encoder=null;if(this.ownsEncoding){try{await this.reserve(false);}catch(_){reason=reason||'studio_status_unconfirmed';}}
      this.phase=reason?'failed':this.capture?'prepared':'idle';this.failure=reason;this.unreadySince=0;this.notify();
      return this.status();
    })().finally(()=>{this.stopping=null;});return this.stopping;
  }
  async close(){await this.stop();if(this.encoder?.status?.().running===true)return false;await this.capture?.close();this.capture=null;this.phase='idle';return true;}
}
module.exports={NativeBroadcast,FORMATS};
