'use strict';
// Owns only local discard encoding. The durable backend latch owns room mode.
const {FORMATS,PUBLIC_FAILURE_CODES}=require('./broadcast.cjs');
const MODES=new Set(['production','entering','rehearsal','recovery_required']);
const CHECKS=new Set(['video','audio_live','audio_vod','guests','screens','transitions','recovery']);
const CHECK_STATUSES=new Set(['not_tested','passed','needs_attention']);
const REASONS=new Set([...PUBLIC_FAILURE_CODES,'rehearsal_cancelled','rehearsal_status_unavailable','rehearsal_not_ready','rehearsal_revision_conflict','rehearsal_generation_conflict','rehearsal_request_conflict','rehearsal_encoding_active','rehearsal_production_busy','rehearsal_already_active','rehearsal_not_active','rehearsal_recovery_not_required','rehearsal_interrupted','rehearsal_idle_unavailable','rehearsal_storage_invalid','rehearsal_storage_unavailable','rehearsal_storage_changed','rehearsal_recovery_interrupted','rehearsal_monitor_unavailable','rehearsal_monitor_unconfirmed','invalid_rehearsal_command','invalid_output_profile']);
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&[Object.prototype,null].includes(Object.getPrototypeOf(value));
const count=value=>Number.isSafeInteger(value)&&value>=0?value:0;
const id=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(value);
const generation=value=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value);
const revision=value=>Number.isSafeInteger(value)&&value>=0&&value<Number.MAX_SAFE_INTEGER-2;
const sanitizeSourceCallbackCode=(value,fallback='encoder_failed')=>REASONS.has(value?.code)?value.code:REASONS.has(value?.message)?value.message:REASONS.has(value)?value:fallback;
const failure=(reason)=>Object.assign(Error(reason),{code:reason});
for(const code of ['output_rehearsal_not_ready','output_rehearsal_cancelled'])REASONS.add(code);
const stats=value=>({frames:count(value?.videoFrames??value?.frames),audioSamples:count(value?.audioSamples),vodAudioSamples:count(value?.vodAudioSamples),bytesMuxed:count(value?.bytesMuxed),codec:['h264_nvenc','libx264'].includes(value?.codec)?value.codec:null});

function cleanRoom(value){
  if(!plain(value)||!MODES.has(value.mode)||!revision(value.revision)||!generation(value.generation)||typeof value.active!=='boolean'||value.active!==(value.mode!=='production')||typeof value.publishing_allowed!=='boolean'||value.publishing_allowed&&value.mode!=='production'||!Array.isArray(value.checks)||value.checks.length>CHECKS.size)throw failure('rehearsal_status_unavailable');
  const seen=new Set(),checks=value.checks.map(check=>{if(!plain(check)||!CHECKS.has(check.id)||seen.has(check.id)||!CHECK_STATUSES.has(check.status)||typeof check.label!=='string'||check.label.length>100)throw failure('rehearsal_status_unavailable');seen.add(check.id);return {id:check.id,label:check.label,status:check.status};});
  return {mode:value.mode,active:value.active,publishing_allowed:value.publishing_allowed,revision:value.revision,generation:value.generation,checks,publishing_work_pending:value.publishing_work_pending===true,...(value.reason?{reason:sanitizeSourceCallbackCode(value.reason,'rehearsal_status_unavailable')}:{})};
}

class RehearsalCoordinator{
  constructor({broadcast,createEncoderGroup,request,identity,ownerPid,onState=()=>{},clock=()=>Date.now()}={}){
    Object.assign(this,{broadcast,createEncoderGroup,request,identity,ownerPid,onState,clock});
    this.room=null;this.roomConfirmed=false;this.roomSerial=0;this.group=null;this.claim=false;this.claimGeneration=null;this.claiming=null;this.workerStarting=null;this.captureStarting=null;this.captureOwned=null;this.captureUnconfirmed=false;
    this.state='idle';this.reason=null;this.lastStats=stats();this.starting=false;this.stopping=null;this.operation=0;this.runGeneration=null;this.unreadySince=null;this.monitorBus='off';this.monitoring=null;this.mutating=null;this.entering=false;this.closed=false;this.starts=new Map();this.checking=null;
  }
  active(){return this.starting||Boolean(this.stopping)||this.claim||this.captureUnconfirmed||this.group?.status?.().running===true;}
  publishingAllowed(){return this.roomConfirmed&&this.room?.mode==='production'&&this.room.publishing_allowed===true&&!this.active()&&!this.entering&&!this.mutating&&!this.closed&&this.monitorBus==='off'&&!this.monitoring;}
  status(){
    const own=this.broadcast?.capture?.status?.(),prepared=Boolean(this.broadcast?.capture)&&own?.prepared!==false;
    const available=this.roomConfirmed&&this.room?.mode==='rehearsal'&&prepared&&own?.monitor?.available!==false&&typeof this.broadcast.capture.setMonitor==='function';
    return {room:this.room?structuredClone(this.room):null,local:{state:this.state,running:this.group?.status?.().running===true,...stats(this.group?.status?.()||this.lastStats),...(this.reason?{reason:this.reason}:{}),ownershipPending:this.claim&&!this.group?.status?.().running||Boolean(this.claiming)||this.captureUnconfirmed},monitor:{bus:this.monitorBus,available,vodAvailable:available&&this.broadcast?.outputProfile?.twitchVod===true},outputPrepared:prepared};
  }
  notify(){
    if(this.broadcast){this.broadcast.rehearsing=this.active();if(this.broadcast.rehearsing)this.broadcast.phase='rehearsing';else if(this.broadcast.phase==='rehearsing')this.broadcast.phase=this.broadcast.capture?'prepared':'idle';}
    try{this.onState(this.status());}catch(_){}try{this.broadcast?.notify?.();}catch(_){}
  }
  async refresh(){
    const token=++this.roomSerial;
    try{const value=await this.request('/api/production/rehearsal');if(value?.ok!==true)throw failure('rehearsal_status_unavailable');const room=cleanRoom(value.room);if(token===this.roomSerial){this.room=room;this.roomConfirmed=true;}}
    catch(_){if(token===this.roomSerial)this.roomConfirmed=false;this.notify();if(this.active()&&this.runGeneration)await this.stop('rehearsal_status_unavailable');else if(this.monitorBus!=='off'){try{await this.monitor({bus:'off'});}catch(_){this.reason='rehearsal_monitor_unconfirmed';}}throw failure('rehearsal_status_unavailable');}
    if(this.active()&&this.runGeneration&&(!this.roomConfirmed||this.room?.mode!=='rehearsal'||this.room.generation!==this.runGeneration))await this.stop('rehearsal_generation_conflict');
    else if(this.monitorBus!=='off'&&(!this.roomConfirmed||this.room?.mode!=='rehearsal')){try{await this.monitor({bus:'off'});}catch(_){this.reason='rehearsal_monitor_unconfirmed';}}
    this.notify();return this.status();
  }
  async canPublish(){await this.refresh();return this.publishingAllowed();}
  validateCommand(action,value){
    const fields=action==='enter'?['requestId','revision']:action==='mark'?['requestId','revision','generation','checkId','status']:['requestId','revision','generation'];
    if(!plain(value)||Object.keys(value).some(key=>!fields.includes(key))||!id(value.requestId)||!revision(value.revision)||action!=='enter'&&!generation(value.generation)||action==='mark'&&(!CHECKS.has(value.checkId)||!CHECK_STATUSES.has(value.status)))throw failure('invalid_rehearsal_command');
    return {request_id:value.requestId,expected_revision:value.revision,...(action!=='enter'?{generation:value.generation}:{}),...(action==='mark'?{check_id:value.checkId,status:value.status}:{}),...(action==='recover'?{confirm_recovery:true}:{})};
  }
  mutate(action,value){
    let body;try{body=this.validateCommand(action,value);if(this.closed)throw failure('desktop_closing');if(this.mutating)throw failure('rehearsal_production_busy');if(action==='enter'&&(this.active()||this.broadcast?.active?.()||this.broadcast?.preparing||this.broadcast?.ownsEncoding))throw failure('rehearsal_production_busy');}catch(error){return Promise.reject(error);}
    this.entering=action==='enter';
    const work=(async()=>{
      if(action==='exit'||action==='recover'){await this.stop();if(this.active()||this.monitorBus!=='off')throw failure('rehearsal_encoding_active');}
      ++this.roomSerial;
      try{const response=await this.request('/api/production/rehearsal/'+action,body);if(response?.ok!==true)throw failure(sanitizeSourceCallbackCode(response?.reason,'rehearsal_status_unavailable'));const room=cleanRoom(response.room);++this.roomSerial;this.room=room;this.roomConfirmed=true;this.reason=null;return this.status();}
      catch(error){++this.roomSerial;this.reason=sanitizeSourceCallbackCode(error,'rehearsal_status_unavailable');this.roomConfirmed=false;throw failure(this.reason);}
    })();
    this.mutating=work;this.notify();return work.finally(()=>{if(this.mutating===work)this.mutating=null;this.entering=false;this.notify();});
  }
  enter(value){return this.mutate('enter',value);}exit(value){return this.mutate('exit',value);}recover(value){return this.mutate('recover',value);}mark(value){return this.mutate('mark',value);}
  assertRoom(value,cas=true){
    if(!this.roomConfirmed||this.room?.mode!=='rehearsal')throw failure('rehearsal_not_ready');
    if(this.room.generation!==value.generation)throw failure('rehearsal_generation_conflict');
    if(cas&&this.room.revision!==value.revision)throw failure('rehearsal_revision_conflict');
  }
  assertPrepared(profile,capture){
    const own=capture?.status?.();
    if(!capture||capture!==this.broadcast.capture||!profile||!FORMATS[profile.format]||this.broadcast.outputProfile!==profile||own?.prepared===false)throw failure('prepare_output');
    if(!this.broadcast.audioMixReady())throw failure('audio_mix_unconfirmed');
    if(!own?.peerId||!own.rendered||own.browserReviewOpen||own.audioBlocked||own.audioReady===false||own.error||!this.broadcast.preflight?.ready)throw failure(sanitizeSourceCallbackCode(own?.error,'output_not_ready'));
  }
  start(value){
    try{
      if(!plain(value)||Object.keys(value).some(key=>!['requestId','revision','generation','profileId'].includes(key))||!id(value.requestId)||!revision(value.revision)||!generation(value.generation)||!id(value.profileId))throw failure('invalid_rehearsal_command');
      const fingerprint=JSON.stringify([value.revision,value.generation,value.profileId]),previous=this.starts.get(value.requestId);
      if(previous){if(previous.fingerprint!==fingerprint)throw failure('rehearsal_request_conflict');return previous.promise;}
      if(this.closed)throw failure('desktop_closing');if(this.active()||this.mutating||this.broadcast.active()||this.broadcast.preparing||this.broadcast.ownsEncoding)throw failure('rehearsal_production_busy');
      this.starting=true;this.state='starting';this.reason=null;const operation=++this.operation;this.notify();const promise=this.startLocal(value,operation).finally(()=>{if(operation===this.operation)this.starting=false;this.notify();});
      this.starts.set(value.requestId,{fingerprint,promise});if(this.starts.size>32)this.starts.delete(this.starts.keys().next().value);return promise;
    }catch(error){return Promise.reject(error);}
  }
  async reserve(active,generationValue){
    if(!this.identity)throw failure('desktop_backend_required');
    if(active){
      this.claim=true;this.claimGeneration=generationValue;const pending=Promise.resolve().then(()=>this.request('/api/desktop/encoding-status',{...this.identity,active:true,owner_pid:this.ownerPid,mode:'rehearsal',rehearsal_generation:generationValue}));this.claiming=pending;this.notify();
      try{const value=await pending;if(value?.ok===false)throw failure(sanitizeSourceCallbackCode(value.reason,'studio_status_unconfirmed'));}finally{if(this.claiming===pending)this.claiming=null;}
    }else{const value=await this.request('/api/desktop/encoding-status',{...this.identity,active:false,owner_pid:this.ownerPid,mode:'rehearsal',rehearsal_generation:this.claimGeneration});if(value?.ok===false)throw failure('studio_status_unconfirmed');this.claim=false;this.claimGeneration=null;}
  }
  async startLocal(value,operation){
    let runFailure=null;const current=()=>operation===this.operation&&!this.closed;const assertCurrent=()=>{if(!current())throw failure('rehearsal_cancelled');};
    try{
      await this.refresh();assertCurrent();this.assertRoom(value);
      const profile=this.broadcast.outputProfile,capture=this.broadcast.capture;
      if((profile?.id||'current-output')!==value.profileId)throw failure('prepare_output');
      await this.broadcast.check();assertCurrent();this.assertPrepared(profile,capture);
      await this.refresh();assertCurrent();this.assertRoom(value);this.runGeneration=value.generation;
      await this.reserve(true,value.generation);assertCurrent();
      let group;const observe=snapshot=>{if(!current()||this.group!==group)return;if(snapshot?.state==='failed'||snapshot?.error||snapshot?.state==='stopped'||snapshot?.running===false){runFailure=sanitizeSourceCallbackCode(snapshot?.code);void this.stop(runFailure).catch(()=>{});}else{this.lastStats=stats(snapshot);this.notify();}};
      group=this.createEncoderGroup(observe);this.group=group;group.createTarget('rehearsal-local',observe);
      const settings={...FORMATS[profile.format],fps:profile.fps,bitrate:profile.videoBitrateKbps*1000,codec:profile.codec,keyframeSeconds:profile.keyframeSeconds,audioBitrateKbps:profile.audioBitrateKbps,twitchVod:profile.twitchVod===true,rehearsal:true,targets:[{id:'rehearsal-local',rehearsal:true,twitchVod:profile.twitchVod===true}]};
      const pending=Promise.resolve(group.start(settings));this.workerStarting=pending;try{await pending;}finally{if(this.workerStarting===pending)this.workerStarting=null;}assertCurrent();
      await this.refresh();assertCurrent();this.assertRoom(value,false);await this.broadcast.check();assertCurrent();this.assertPrepared(profile,capture);
      this.captureOwned=capture;if(typeof capture.waitForRehearsal!=='function')throw failure('output_rehearsal_not_ready');await capture.waitForRehearsal(value.generation);assertCurrent();
      const send=(method,buffer,pts,vod)=>{if(!current()||this.group!==group)return false;let accepted=false;try{accepted=group[method](buffer,pts)!==false;if(accepted&&method==='sendAudio'&&profile.twitchVod===true)accepted=group.sendVodAudio(vod,pts)!==false;}catch(error){runFailure=sanitizeSourceCallbackCode(error);}if(!accepted){runFailure=runFailure||'encoder_backpressure';void this.stop(runFailure).catch(()=>{});}return accepted;};
      const capturing=Promise.resolve(capture.startCapture((buffer,pts)=>send('sendVideo',buffer,pts),(buffer,pts,vod)=>send('sendAudio',buffer,pts,vod)));this.captureStarting=capturing;
      try{await capturing;}finally{if(this.captureStarting===capturing)this.captureStarting=null;}assertCurrent();this.state='encoding';this.notify();return this.status();
    }catch(error){const cancelled=!current(),reason=runFailure||(cancelled?'rehearsal_cancelled':sanitizeSourceCallbackCode(error,'rehearsal_not_ready'));if(!cancelled)await this.stop(reason);else if(this.stopping)await this.stopping;throw failure(reason);}
  }
  stop(reason=null){
    if(this.stopping)return this.stopping;
    ++this.operation;this.starting=false;this.state='stopping';this.reason=reason===null?null:sanitizeSourceCallbackCode(reason);this.notify();
    const work=(async()=>{
      let stoppedCapture=true;try{await this.monitor({bus:'off'});}catch(_){this.reason='rehearsal_monitor_unconfirmed';}
      const capture=this.captureOwned,capturing=this.captureStarting;
      if(capture){try{await capture.stopCapture();}catch(_){stoppedCapture=false;}}
      if(capturing){try{await capturing;}catch(_){}try{await capture?.stopCapture();stoppedCapture=true;}catch(_){stoppedCapture=false;}}
      this.captureUnconfirmed=!stoppedCapture;if(stoppedCapture)this.captureOwned=null;else this.reason='capture_stop_unconfirmed';
      const group=this.group,starting=this.workerStarting;
      if(group){try{await group.stop();}catch(_){this.reason='encoder_stop_unconfirmed';}}
      if(starting){try{await starting;}catch(_){}if(group?.status?.().running===true){try{await group.stop();}catch(_){this.reason='encoder_stop_unconfirmed';}}}
      if(group)this.lastStats=stats(group.status?.());
      if(group?.status?.().running===true){this.reason='encoder_stop_unconfirmed';this.state='failed';return this.status();}
      this.group=null;if(this.claiming){try{await this.claiming;}catch(_){} }
      if(this.claim&&!this.captureUnconfirmed){try{await this.reserve(false);}catch(_){this.reason='studio_status_unconfirmed';}}
      this.state=this.reason?'failed':'idle';this.runGeneration=null;this.unreadySince=null;return this.status();
    })();
    const stopping=work.finally(()=>{if(this.stopping===stopping)this.stopping=null;this.notify();});this.stopping=stopping;this.notify();return stopping;
  }
  monitor(value){
    if(!plain(value)||Object.keys(value).some(key=>key!=='bus')||!['off','live','vod'].includes(value.bus))return Promise.reject(failure('invalid_rehearsal_command'));
    const bus=value.bus,operation=this.operation,previous=this.monitoring;
    const work=(async()=>{
      if(previous){try{await previous;}catch(_){} }
      const capture=this.broadcast?.capture,available=this.status().monitor;
      if(bus!=='off'&&(this.closed||this.stopping||operation!==this.operation||!available.available||bus==='vod'&&!available.vodAvailable))throw failure('rehearsal_monitor_unavailable');
      if(typeof capture?.setMonitor==='function'){const response=await capture.setMonitor(bus);if(response?.ok===false)throw failure('rehearsal_monitor_unconfirmed');}
      else if(bus!=='off')throw failure('rehearsal_monitor_unavailable');
      this.monitorBus=bus;this.notify();return this.status();
    })();this.monitoring=work;return work.finally(()=>{if(this.monitoring===work)this.monitoring=null;});
  }
  check(){if(this.checking)return this.checking;const work=this.checkLocal();this.checking=work;return work.finally(()=>{if(this.checking===work)this.checking=null;});}
  async checkLocal(){
    await this.refresh();if(!this.active()||!this.runGeneration||this.stopping)return this.status();const operation=this.operation,capture=this.captureOwned||this.broadcast.capture;
    await this.broadcast.check();if(operation!==this.operation||this.stopping)return this.status();const own=capture?.status?.();
    const durable=own?.error?sanitizeSourceCallbackCode(own.error,'output_lost'):own?.browserReviewOpen?'output_review_open':!this.broadcast.audioMixReady()?'audio_mix_unconfirmed':null;
    if(durable)await this.stop(durable);else if(this.broadcast.preflight?.ready===true)this.unreadySince=null;else if(this.unreadySince===null)this.unreadySince=this.clock();else if(this.clock()-this.unreadySince>=6500)await this.stop('output_lost');
    return this.status();
  }
  async close(){await this.stop();if(this.active()||this.monitorBus!=='off')return false;this.closed=true;this.notify();return true;}
}
module.exports={RehearsalCoordinator,sanitizeSourceCallbackCode};
