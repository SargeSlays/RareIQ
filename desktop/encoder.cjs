'use strict';
// Main process only. This coordinator owns only its encoder child, never OBS.
const {EventEmitter}=require('node:events'),{spawn}=require('node:child_process'),path=require('node:path');
const HEADER_BYTES=13,MAX_PTS=7*24*3600*1e6;
const FAILURE_CODES=new Set(['invalid_encoder_config','invalid_test_output','invalid_test_transport','destination_required','invalid_destination','secure_destination_required','nonpublic_destination','destination_dns_failed','tls_trust_unavailable','tls_verification_failed','tls_connection_failed','encoder_transport_ownership_unavailable','encoder_transport_interrupted','video_encoder_unavailable','encoder_input_ended','invalid_encoder_packet','invalid_audio_samples','audio_timeline_discontinuity','encoder_dependency_missing','encoder_failed']);
const publicError=code=>Object.assign(new Error(code),{code});
function packet(kind,buffer,ptsUs){const header=Buffer.alloc(HEADER_BYTES);header.writeUInt8(kind.charCodeAt(0));header.writeUInt32LE(buffer.length,1);header.writeBigUInt64LE(BigInt(ptsUs),5);return Buffer.concat([header,buffer]);}
function validateSettings(value){
  if(!value||!Number.isInteger(value.width)||value.width<16||value.width>3840||value.width%2||!Number.isInteger(value.height)||value.height<16||value.height>3840||value.height%2||value.width*value.height>3840*2160)throw publicError('invalid_encoder_config');
  const fps=value.fps??30,bitrate=value.bitrate??6000000,codec=value.codec??'auto';
  if(!Number.isInteger(fps)||fps<1||fps>60||!Number.isInteger(bitrate)||bitrate<250000||bitrate>40000000||!['auto','h264_nvenc','libx264'].includes(codec))throw publicError('invalid_encoder_config');
  return {width:value.width,height:value.height,fps,bitrate,codec};
}
class Encoder extends EventEmitter{
  #python;#worker;#pythonPath;#artifactRoot;#testTransport;#spawn;#child=null;#settings=null;#state={state:'idle',platformVerified:false};#queueBytes=0;#last={V:-1,A:-1};#stopPromise=null;#startTimeout;#stopTimeout;#generation=0;
  constructor({python,workerPath=path.join(__dirname,'encoder_worker.py'),pythonPath,pythonPackages,artifactRoot,testTransport,onState,spawnProcess=spawn,startTimeoutMs=30000,stopTimeoutMs=12000}={}){
    pythonPath=pythonPath??pythonPackages;
    super();if(typeof python!=='string'||!path.isAbsolute(python)||!path.isAbsolute(workerPath))throw publicError('encoder_runtime_required');
    if(pythonPath!==undefined&&(typeof pythonPath!=='string'||!path.isAbsolute(pythonPath)))throw publicError('encoder_runtime_required');
    if(artifactRoot!==undefined&&(typeof artifactRoot!=='string'||!path.isAbsolute(artifactRoot)))throw publicError('invalid_test_output');
    if(testTransport!==undefined){if(!artifactRoot||!testTransport||Object.keys(testTransport).some(key=>!['port','caFile','serverName'].includes(key))||!Number.isInteger(testTransport.port)||testTransport.port<1024||testTransport.port>65535||typeof testTransport.caFile!=='string'||!path.isAbsolute(testTransport.caFile)||!['localhost','wrong-host.invalid'].includes(testTransport.serverName))throw publicError('invalid_test_transport');this.#testTransport=Object.freeze({...testTransport});}
    this.#python=python;this.#worker=workerPath;this.#pythonPath=pythonPath;this.#artifactRoot=artifactRoot;this.#spawn=spawnProcess;this.#startTimeout=startTimeoutMs;this.#stopTimeout=stopTimeoutMs;
    if(typeof onState==='function')this.on('state',onState);
  }
  status(){return {...this.#state,running:Boolean(this.#child),queuedBytes:this.#queueBytes};}
  #publish(value){this.#state={...this.#state,...value,platformVerified:false};this.emit('status',this.status());this.emit('state',this.status());}
  start(value){
    if(this.#child||this.#state.state==='starting')return Promise.reject(publicError('encoder_already_running'));
    let settings,config;
    try{
      settings=validateSettings(value);config={...settings};
      if(value.testTransport!==undefined)throw publicError('invalid_test_transport');
      if(this.#testTransport){if(value.testOutput!==undefined||value.destination!==undefined)throw publicError('invalid_test_transport');config.testTransport=this.#testTransport;config.artifactRoot=this.#artifactRoot;}
      else if(value.testOutput!==undefined){if(!this.#artifactRoot||typeof value.testOutput!=='string'||!path.isAbsolute(value.testOutput))throw publicError('invalid_test_output');config.testOutput=value.testOutput;config.artifactRoot=this.#artifactRoot;}
      else{if(!value.destination||typeof value.destination.serverUrl!=='string'||typeof value.destination.streamKey!=='string')throw publicError('destination_required');config.destination={serverUrl:value.destination.serverUrl,streamKey:value.destination.streamKey};}
    }catch(error){return Promise.reject(publicError(FAILURE_CODES.has(error.code)?error.code:'invalid_encoder_config'));}
    const encoded=JSON.stringify(config)+'\n';if(Buffer.byteLength(encoded)>16384)return Promise.reject(publicError('invalid_encoder_config'));
    this.#settings=settings;this.#queueBytes=0;this.#last={V:-1,A:-1};this.#stopPromise=null;
    this.#state={state:'starting',videoFrames:0,audioSamples:0,packets:0,bytesMuxed:0,droppedVideoFrames:0,droppedAudioPackets:0,platformVerified:false};
    const generation=++this.#generation;
    return new Promise((resolve,reject)=>{
      let child,ready=false,settled=false,output='',failed=false;
      const finishStart=(error)=>{if(settled)return;settled=true;clearTimeout(timer);error?reject(publicError(error)):resolve(this.status());};
      const fail=(code)=>{if(generation!==this.#generation)return;failed=true;this.#publish({state:'failed',code});finishStart(code);try{child?.kill();}catch(_){};};
      const timer=setTimeout(()=>fail('encoder_start_timeout'),this.#startTimeout);timer.unref?.();
      try{
        const env={...process.env,PYTHONDONTWRITEBYTECODE:'1',PYTHONUNBUFFERED:'1'};
        if(this.#pythonPath)env.PYTHONPATH=this.#pythonPath;
        child=this.#spawn(this.#python,['-B',this.#worker],{windowsHide:true,stdio:['pipe','pipe','pipe'],env});this.#child=child;
      }catch(_){clearTimeout(timer);this.#publish({state:'failed',code:'encoder_spawn_failed'});reject(publicError('encoder_spawn_failed'));return;}
      child.stderr.resume();
      child.on('error',()=>fail('encoder_spawn_failed'));
      child.stdin.on('error',()=>{if(this.#state.state!=='stopping')fail('encoder_input_failed');});
      child.stdout.on('data',chunk=>{
        if(generation!==this.#generation)return;output+=chunk.toString();if(output.length>65536){fail('encoder_protocol_failed');return;}
        let end;while((end=output.indexOf('\n'))>=0){const line=output.slice(0,end);output=output.slice(end+1);let message;try{message=JSON.parse(line);}catch(_){fail('encoder_protocol_failed');return;}
          if(!message||!['ready','active','stats','stopped','error'].includes(message.event)){fail('encoder_protocol_failed');return;}
          if(message.event==='error'){fail(FAILURE_CODES.has(message.code)?message.code:'encoder_failed');return;}
          const safe={};for(const key of ['videoFrames','audioSamples','audioSilenceSamples','packets','bytesMuxed'])if(Number.isSafeInteger(message[key])&&message[key]>=0)safe[key]=message[key];
          if(['h264_nvenc','libx264'].includes(message.codec))safe.codec=message.codec;
          if(typeof message.hardwareVerified==='boolean')safe.hardwareVerified=message.hardwareVerified;
          if(typeof message.synthetic==='boolean')safe.synthetic=message.synthetic;
          if(typeof message.tlsVerified==='boolean')safe.tlsVerified=message.tlsVerified;
          if(message.event==='ready'){ready=true;safe.state=this.#state.state==='stopping'?'stopping':'starting';this.#publish(safe);finishStart();}
          else if(message.event==='stopped'){this.#publish({...safe,state:'stopped'});}
          else if(ready){this.#publish({...safe,state:this.#state.state==='stopping'?'stopping':message.event==='active'||safe.packets>0?'active':'starting'});}
        }
      });
      child.on('close',code=>{
        if(generation!==this.#generation)return;clearTimeout(timer);this.#child=null;this.#queueBytes=0;
        if(!ready)finishStart(this.#state.code||'encoder_start_failed');
        if(!failed&&(code!==0||this.#state.state!=='stopped'))this.#publish({state:'failed',code:'encoder_exited'});
        else this.#publish({});this.emit('closed',this.status());
      });
      child.stdin.write(encoded,error=>{if(error)fail('encoder_input_failed');});
    });
  }
  #send(kind,data,ptsUs){
    if(!this.#child||!['starting','active'].includes(this.#state.state)||!Buffer.isBuffer(data)||!Number.isSafeInteger(ptsUs)||ptsUs<0||ptsUs>MAX_PTS||ptsUs<=this.#last[kind])return false;
    const frameBytes=this.#settings.width*this.#settings.height*4;
    if(kind==='V'?data.length!==frameBytes:data.length<8||data.length>384000||data.length%8)return false;
    const limit=2*(frameBytes+HEADER_BYTES)+384000;
    if(this.#queueBytes+data.length+HEADER_BYTES>limit){const field=kind==='V'?'droppedVideoFrames':'droppedAudioPackets';this.#state[field]++;return false;}
    const bytes=packet(kind,data,ptsUs),generation=this.#generation;this.#last[kind]=ptsUs;this.#queueBytes+=bytes.length;
    try{this.#child.stdin.write(bytes,()=>{if(generation===this.#generation)this.#queueBytes=Math.max(0,this.#queueBytes-bytes.length);});return true;}catch(_){this.#queueBytes-=bytes.length;return false;}
  }
  sendVideo(buffer,ptsUs){return this.#send('V',buffer,ptsUs);}
  sendAudio(buffer,ptsUs){return this.#send('A',buffer,ptsUs);}
  pushVideo(buffer,ptsUs){return this.sendVideo(buffer,ptsUs);}
  pushAudio(buffer,ptsUs){return this.sendAudio(buffer,ptsUs);}
  stop(){
    if(this.#stopPromise)return this.#stopPromise;
    if(!this.#child)return Promise.resolve(this.status());
    const child=this.#child;this.#publish({state:'stopping'});
    this.#stopPromise=new Promise(resolve=>{
      let finished=false,killTimer;
      const finish=()=>{if(finished)return;finished=true;clearTimeout(timer);clearTimeout(killTimer);this.removeListener('closed',finish);resolve(this.status());};
      this.on('closed',finish);
      const timer=setTimeout(()=>{this.#publish({state:'failed',code:'encoder_stop_timeout'});try{child.kill();}catch(_){};killTimer=setTimeout(finish,3000);killTimer.unref?.();},this.#stopTimeout);timer.unref?.();
      try{child.stdin.end(packet('E',Buffer.alloc(0),0));}catch(_){try{child.kill();}catch(_){};}
    }).finally(()=>{this.#stopPromise=null;});
    return this.#stopPromise;
  }
}
module.exports={Encoder,NativeEncoder:Encoder,packet,validateSettings,HEADER_BYTES};
