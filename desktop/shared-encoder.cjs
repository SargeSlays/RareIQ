'use strict';
// Main-process owner of one encoder process and its independently stopped mux targets.
const {EventEmitter}=require('node:events'),{spawn}=require('node:child_process'),path=require('node:path');
const {validateSettings,packet,HEADER_BYTES}=require('./encoder.cjs'),{validateServerUrl}=require('./destinations.cjs');
const MAX_PTS=7*24*3600*1e6,MAX_CONFIG=65536,ID=/^[A-Za-z0-9_-]{1,80}$/;
const SETTINGS=['width','height','fps','bitrate','codec','audioBitrateKbps','keyframeSeconds','twitchVod'];
const CODES=new Set(['invalid_encoder_config','invalid_test_output','invalid_test_transport','destination_required','invalid_destination','secure_destination_required','nonpublic_destination','destination_dns_failed','tls_trust_unavailable','tls_verification_failed','tls_connection_failed','encoder_transport_ownership_unavailable','encoder_transport_interrupted','video_encoder_unavailable','encoder_input_ended','invalid_encoder_packet','invalid_audio_samples','audio_timeline_discontinuity','vod_audio_timeline_discontinuity','twitch_vod_unavailable','twitch_vod_audio_missing','twitch_vod_audio_late','encoder_dependency_missing','encoder_failed','encoder_backpressure','shared_mux_unavailable','shared_encoder_start_failed','shared_encoder_shutdown_unconfirmed','encoder_start_timeout','encoder_spawn_failed','encoder_input_failed','encoder_protocol_failed','encoder_start_failed','encoder_exited','encoder_stop_timeout']);
const error=code=>Object.assign(new Error(code),{code}),safeCode=value=>CODES.has(value)?value:'encoder_failed';
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&[Object.prototype,null].includes(Object.getPrototypeOf(value)),validId=value=>typeof value==='string'&&ID.test(value);
function transport(value){if(!plain(value)||Object.keys(value).some(key=>!['port','caFile','serverName'].includes(key))||!Number.isInteger(value.port)||value.port<1024||value.port>65535||typeof value.caFile!=='string'||!path.isAbsolute(value.caFile)||!['localhost','wrong-host.invalid'].includes(value.serverName))throw error('invalid_test_transport');return {...value};}
function safeStats(value,vod=false){const result={};for(const key of ['videoFrames','audioSamples','audioSilenceSamples','vodAudioSamples','vodAudioSilenceSamples','packets','bytesMuxed','droppedVideoFrames','droppedAudioPackets','droppedVodAudioPackets'])if(Number.isSafeInteger(value[key])&&value[key]>=0)result[key]=value[key];for(const key of ['videoEncoderInstances','targetMuxerCount'])if(Number.isSafeInteger(value[key])&&value[key]>=0&&value[key]<=8)result[key]=value[key];if(['h264_nvenc','libx264'].includes(value.codec))result.codec=value.codec;for(const key of ['hardwareVerified','synthetic','tlsVerified'])if(typeof value[key]==='boolean')result[key]=value[key];if(vod&&value.twitchVodWireVerified===true)result.twitchVodWireVerified=true;return result;}
const unverified={platformVerified:false,platformLiveVerified:false,vodPlatformVerified:false};
class SharedEncoderGroup extends EventEmitter{
  #python;#worker;#pythonPath;#artifactRoot;#transports;#singleTransport;#spawn;#startTimeout;#stopTimeout;#killGrace;#child=null;#settings=null;#generation=0;#queueBytes=0;#last={V:-1,A:-1,B:-1};#state={state:'idle',...unverified};#targets=new Map();#activeIds=new Set();#stopPromise=null;
  constructor({python,workerPath=path.join(__dirname,'shared_encoder_worker.py'),pythonPath,pythonPackages,artifactRoot,testTransports,testTransport,onState,spawnProcess=spawn,startTimeoutMs=30000,stopTimeoutMs=12000,killGraceMs=3000}={}){
    super();pythonPath=pythonPath??pythonPackages;if(typeof python!=='string'||!path.isAbsolute(python)||typeof workerPath!=='string'||!path.isAbsolute(workerPath)||pythonPath!==undefined&&(typeof pythonPath!=='string'||!path.isAbsolute(pythonPath)))throw error('encoder_runtime_required');if(artifactRoot!==undefined&&(typeof artifactRoot!=='string'||!path.isAbsolute(artifactRoot)))throw error('invalid_test_output');
    if(testTransports!==undefined){if(!artifactRoot||!plain(testTransports)||Object.keys(testTransports).length>8||Object.keys(testTransports).some(id=>!validId(id)))throw error('invalid_test_transport');this.#transports=Object.fromEntries(Object.entries(testTransports).map(([id,value])=>[id,transport(value)]));}else this.#transports={};if(testTransport!==undefined){if(!artifactRoot||testTransports!==undefined)throw error('invalid_test_transport');this.#singleTransport=transport(testTransport);}
    for(const value of [startTimeoutMs,stopTimeoutMs,killGraceMs])if(!Number.isFinite(value)||value<=0||value>120000)throw error('invalid_encoder_config');
    this.#python=python;this.#worker=workerPath;this.#pythonPath=pythonPath;this.#artifactRoot=artifactRoot;this.#spawn=spawnProcess;this.#startTimeout=startTimeoutMs;this.#stopTimeout=stopTimeoutMs;this.#killGrace=killGraceMs;if(typeof onState==='function')this.on('state',onState);
  }
  status(){return {...this.#state,running:Boolean(this.#child),queuedBytes:this.#queueBytes,targets:[...this.#activeIds].map(id=>this.#targetStatus(this.#targets.get(id)))};}
  #publish(value){this.#state={...this.#state,...value,...unverified};for(const name of ['status','state'])try{this.emit(name,this.status());}catch(_){} }
  #targetStatus(entry){return {...entry.state,targetId:entry.id,running:entry.running,...unverified};}
  #publishTarget(entry,value){entry.state={...entry.state,...value,...unverified};try{entry.onState?.(this.#targetStatus(entry));}catch(_){} }
  #entry(id,onState){const entry={id,onState,running:false,confirmed:false,failed:false,state:{state:'idle',...unverified},stopPromise:null,finishStop:null};entry.facade=Object.freeze({status:()=>this.#targetStatus(entry),stop:()=>this.#stopTarget(entry)});this.#targets.set(id,entry);return entry;}
  createTarget(id,onState){if(!validId(id)||this.#targets.has(id)||this.#targets.size>=8||this.#child||onState!==undefined&&typeof onState!=='function')throw error('invalid_encoder_config');return this.#entry(id,onState).facade;}
  #config(value){
    if(!plain(value)||Object.keys(value).some(key=>![...SETTINGS,'targets'].includes(key))||SETTINGS.some(key=>value[key]===null)||!Array.isArray(value.targets)||!value.targets.length||value.targets.length>8)throw error('invalid_encoder_config');const settings=validateSettings(value),ids=new Set();
    const targets=value.targets.map(raw=>{
      if(!plain(raw)||Object.keys(raw).some(key=>!['id','destination','testOutput','twitchVod'].includes(key))||!validId(raw.id)||ids.has(raw.id)||raw.twitchVod!==undefined&&typeof raw.twitchVod!=='boolean')throw error('invalid_encoder_config');ids.add(raw.id);const result={id:raw.id,twitchVod:raw.twitchVod===true},seam=this.#transports[raw.id]||this.#singleTransport;
      if(Object.keys(this.#transports).length&&!seam)throw error('invalid_test_transport');
      if(this.#singleTransport&&value.targets.length!==1)throw error('invalid_test_transport');
      if(seam){if(raw.destination!==undefined||raw.testOutput!==undefined)throw error('invalid_test_transport');result.testTransport=seam;}
      else if(raw.testOutput!==undefined){const output=raw.testOutput;if(!this.#artifactRoot||typeof output!=='string'||!path.isAbsolute(output)||output.length>2048)throw error('invalid_test_output');const relative=path.relative(path.resolve(this.#artifactRoot),path.resolve(output));if(!relative||relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative))throw error('invalid_test_output');result.testOutput=path.resolve(output);if(raw.destination!==undefined)throw error('invalid_test_output');}
      else{
        const destination=raw.destination;if(!plain(destination)||Object.keys(destination).some(key=>!['id','serverUrl','streamKey','platform','name','networkVerified','allowInsecureRtmp'].includes(key))||typeof destination.streamKey!=='string'||!destination.streamKey.length||destination.streamKey.length>4096||/[\s\x00-\x1f\x7f]/.test(destination.streamKey))throw error('destination_required');if(destination.id!==undefined&&(typeof destination.id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(destination.id)||destination.id!==raw.id))throw error('invalid_destination');if(typeof destination.serverUrl!=='string'||!destination.serverUrl.startsWith('rtmps://'))throw error('secure_destination_required');let serverUrl;try{serverUrl=validateServerUrl(destination.serverUrl,{platform:destination.platform||'custom'});}catch(_){throw error('invalid_destination');}if(result.twitchVod&&destination.platform!=='twitch')throw error('invalid_encoder_config');result.destination={serverUrl,streamKey:destination.streamKey,...(destination.platform?{platform:destination.platform}:{})};
      }
      return result;
    });
    if(settings.twitchVod!==targets.some(target=>target.twitchVod))throw error('invalid_encoder_config');return {settings,config:{...settings,targets,...(targets.some(target=>target.testOutput||target.testTransport)?{artifactRoot:this.#artifactRoot}:{})}};
  }
  start(value){
    if(this.#child||this.#state.state==='starting')return Promise.reject(error('encoder_already_running'));let settings,config,encoded;try{({settings,config}=this.#config(value));encoded=JSON.stringify(config)+'\n';if(Buffer.byteLength(encoded)>MAX_CONFIG)throw error('invalid_encoder_config');if(config.targets.some(target=>!this.#targets.has(target.id))&&this.#targets.size+config.targets.filter(target=>!this.#targets.has(target.id)).length>8)throw error('invalid_encoder_config');}catch(cause){return Promise.reject(error(CODES.has(cause.code)?cause.code:'invalid_encoder_config'));}
    this.#settings=settings;this.#last={V:-1,A:-1,B:-1};this.#queueBytes=0;this.#stopPromise=null;this.#activeIds=new Set(config.targets.map(target=>target.id));this.#state={state:'starting',videoFrames:0,audioSamples:0,vodAudioSamples:0,packets:0,bytesMuxed:0,droppedVideoFrames:0,droppedAudioPackets:0,droppedVodAudioPackets:0,twitchVod:settings.twitchVod,...unverified};
    for(const target of config.targets){const entry=this.#targets.get(target.id)||this.#entry(target.id);entry.running=true;entry.confirmed=false;entry.failed=false;entry.vod=target.twitchVod;entry.stopPromise=null;entry.finishStop=null;entry.state={state:'starting',videoFrames:0,audioSamples:0,vodAudioSamples:0,packets:0,bytesMuxed:0,twitchVod:target.twitchVod,...unverified};}
    const generation=++this.#generation;
    return new Promise((resolve,reject)=>{
      let child,ready=false,settled=false,output='',failed=false;
      const finishStart=code=>{if(settled)return;settled=true;clearTimeout(timer);code?reject(error(code)):resolve(this.status());};
      const fail=code=>{if(generation!==this.#generation||failed)return;failed=true;this.#publish({state:'failed',code});finishStart(code);try{child?.kill();}catch(_){};};
      const timer=setTimeout(()=>fail('encoder_start_timeout'),this.#startTimeout);timer.unref?.();
      try{const env={...process.env,PYTHONDONTWRITEBYTECODE:'1',PYTHONUNBUFFERED:'1'};if(this.#pythonPath)env.PYTHONPATH=this.#pythonPath;child=this.#spawn(this.#python,['-B',this.#worker],{windowsHide:true,stdio:['pipe','pipe','pipe'],env});this.#child=child;}
      catch(_){clearTimeout(timer);for(const entry of this.#targets.values())if(this.#activeIds.has(entry.id))entry.running=false;this.#publish({state:'failed',code:'encoder_spawn_failed'});finishStart('encoder_spawn_failed');return;}
      child.stderr.resume();child.on('error',()=>fail('encoder_spawn_failed'));child.stdin.on('error',()=>{if(this.#state.state!=='stopping')fail('encoder_input_failed');});
      child.stdout.on('data',chunk=>{
        if(generation!==this.#generation||failed)return;output+=chunk.toString();if(Buffer.byteLength(output)>MAX_CONFIG){fail('encoder_protocol_failed');return;}
        let end;while((end=output.indexOf('\n'))>=0){const line=output.slice(0,end);output=output.slice(end+1);let message;try{message=JSON.parse(line);}catch(_){fail('encoder_protocol_failed');return;}if(!plain(message)||!['ready','active','stats','error','stopped'].includes(message.event)){fail('encoder_protocol_failed');return;}
          if(Object.hasOwn(message,'targetId')){
            if(!this.#activeIds.has(message.targetId)){fail('encoder_protocol_failed');return;}const entry=this.#targets.get(message.targetId);if(entry.confirmed)continue;
            const stats=safeStats(message,entry.vod);if(message.event==='error'){entry.failed=true;this.#publishTarget(entry,{...stats,state:'failed',code:safeCode(message.code)});}
            else if(message.event==='stopped'){entry.running=false;entry.confirmed=true;this.#publishTarget(entry,{...stats,state:entry.failed?'failed':'stopped',...(entry.failed?{code:entry.state.code||safeCode(message.code)}:{})});entry.finishStop?.();}
            else if(!entry.failed)this.#publishTarget(entry,{...stats,state:entry.state.state==='stopping'?'stopping':message.event==='active'||stats.packets>0?'active':'starting'});
            continue;
          }
          if(message.event==='error'){fail(safeCode(message.code));return;}const stats=safeStats(message,settings.twitchVod);
          if(message.event==='ready'){ready=true;this.#publish({...stats,state:this.#state.state==='stopping'?'stopping':'starting'});finishStart();}
          else if(message.event==='stopped'){for(const id of this.#activeIds){const entry=this.#targets.get(id);if(!entry.confirmed){entry.running=false;entry.confirmed=true;this.#publishTarget(entry,{state:entry.failed?'failed':'stopped'});entry.finishStop?.();}}this.#publish({...stats,state:'stopped'});}
          else if(ready)this.#publish({...stats,state:this.#state.state==='stopping'?'stopping':message.event==='active'||stats.packets>0?'active':'starting'});
        }
      });
      child.on('close',code=>{
        if(generation!==this.#generation)return;clearTimeout(timer);this.#child=null;this.#queueBytes=0;if(!ready)finishStart(this.#state.code||'encoder_start_failed');if(!failed&&(code!==0||this.#state.state!=='stopped'))this.#publish({state:'failed',code:'encoder_exited'});else this.#publish({});
        for(const id of this.#activeIds){const entry=this.#targets.get(id);if(!entry.confirmed){entry.running=false;entry.confirmed=true;entry.failed=true;this.#publishTarget(entry,{state:'failed',code:entry.state.code||this.#state.code||'encoder_exited'});}entry.finishStop?.();}try{this.emit('closed',this.status());}catch(_){}
      });
      try{child.stdin.write(encoded,cause=>{if(cause)fail('encoder_input_failed');});}catch(_){fail('encoder_input_failed');}
    });
  }
  #send(kind,data,pts){
    if(kind==='B'&&!this.#settings?.twitchVod)return false;if(!this.#child||!['starting','active'].includes(this.#state.state)||!Buffer.isBuffer(data)||!Number.isSafeInteger(pts)||pts<0||pts>MAX_PTS||pts<=this.#last[kind])return false;
    const frame=this.#settings.width*this.#settings.height*4;if(kind==='V'?data.length!==frame:data.length<8||data.length>384000||data.length%8)return false;const limit=2*(frame+HEADER_BYTES)+384000*(this.#settings.twitchVod?2:1);if(this.#queueBytes+data.length+HEADER_BYTES>limit){const field=kind==='V'?'droppedVideoFrames':kind==='B'?'droppedVodAudioPackets':'droppedAudioPackets';this.#state[field]++;return false;}
    const bytes=packet(kind,data,pts),generation=this.#generation;this.#last[kind]=pts;this.#queueBytes+=bytes.length;try{this.#child.stdin.write(bytes,cause=>{if(generation!==this.#generation)return;this.#queueBytes=Math.max(0,this.#queueBytes-bytes.length);if(cause)this.#publish({state:'failed',code:'encoder_input_failed'});});return true;}catch(_){this.#queueBytes=Math.max(0,this.#queueBytes-bytes.length);this.#publish({state:'failed',code:'encoder_input_failed'});return false;}
  }
  sendVideo(value,pts){return this.#send('V',value,pts);}sendAudio(value,pts){return this.#send('A',value,pts);}sendVodAudio(value,pts){return this.#send('B',value,pts);}
  pushVideo(value,pts){return this.sendVideo(value,pts);}pushAudio(value,pts){return this.sendAudio(value,pts);}pushVodAudio(value,pts){return this.sendVodAudio(value,pts);}
  #stopTarget(entry){
    if(entry.stopPromise)return entry.stopPromise;if(!entry.running||!this.#child)return Promise.resolve(this.#targetStatus(entry));const generation=this.#generation,child=this.#child;if(!entry.failed)this.#publishTarget(entry,{state:'stopping'});
    entry.stopPromise=new Promise(resolve=>{let done=false;const finish=()=>{if(done)return;done=true;clearTimeout(timer);entry.finishStop=null;resolve(this.#targetStatus(entry));};entry.finishStop=finish;const timer=setTimeout(()=>{if(generation===this.#generation&&entry.running){entry.failed=true;this.#publishTarget(entry,{state:'failed',code:'encoder_stop_timeout'});}finish();},this.#stopTimeout);timer.unref?.();try{child.stdin.write(packet('T',Buffer.from(JSON.stringify({id:entry.id})),0));}catch(_){this.#publishTarget(entry,{state:'failed',code:'encoder_input_failed'});}}).finally(()=>{if(generation===this.#generation)entry.stopPromise=null;});return entry.stopPromise;
  }
  stop(){
    if(this.#stopPromise)return this.#stopPromise;if(!this.#child)return Promise.resolve(this.status());const child=this.#child,generation=this.#generation;this.#publish({state:'stopping'});
    this.#stopPromise=new Promise(resolve=>{let done=false,killTimer;const finish=()=>{if(done)return;done=true;clearTimeout(timer);clearTimeout(killTimer);this.removeListener('closed',finish);resolve(this.status());};this.on('closed',finish);const timer=setTimeout(()=>{if(generation!==this.#generation){finish();return;}this.#publish({state:'failed',code:'encoder_stop_timeout'});try{child.kill();}catch(_){}killTimer=setTimeout(finish,this.#killGrace);killTimer.unref?.();},this.#stopTimeout);timer.unref?.();try{child.stdin.end(packet('E',Buffer.alloc(0),0));}catch(_){try{child.kill();}catch(_){} }}).finally(()=>{if(generation===this.#generation)this.#stopPromise=null;});return this.#stopPromise;
  }
}
module.exports={SharedEncoderGroup};
