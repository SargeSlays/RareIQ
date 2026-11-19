'use strict';
// Generated sources only. No Electron, devices, provider accounts or network.
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs/promises'),{setTimeout:pause}=require('node:timers/promises'),{spawn}=require('node:child_process');
const {NativeRecording}=require('../recording.cjs'),{SharedEncoderGroup}=require('../shared-encoder.cjs'),{createSharedOutputCapture}=require('../shared-output-capture.cjs'),{createEncodingReservations}=require('../encoding-reservations.cjs');
async function main(){
  const directory=path.resolve(process.argv[2]||'F:/Temp/jonat/ProducerPlease-recording-20261119/native-'+Date.now());if(process.platform==='win32'&&!/^f:/i.test(directory))throw Error('F_evidence_required');await fs.mkdir(directory,{recursive:true});
  const python=path.resolve(__dirname,'../../.venv/Scripts/python.exe'),pythonPackages='F:/Caches/ProducerPlease/python-packages',workerPath=path.resolve(__dirname,'../shared_encoder_worker.py');
  const profile={id:'synthetic-hd',name:'Generated HD',format:'hd',fps:30,videoBitrateKbps:4000,codec:'auto',keyframeSeconds:1,audioBitrateKbps:96,twitchVod:false};
  const identity={pid:process.pid,server_session_id:'synthetic-recording'},results=[];
  let activeGroup=null,activeRecorder=null,activeShared=null;
  const makeGroup=(onState,extra={})=>new SharedEncoderGroup({python,pythonPackages,workerPath,onState,...extra});
  async function scenario(name,{broadcastFirst=false,stopBroadcastFirst=false,lowSpace=false}={}){
    const destination=path.join(directory,name+'.mkv'),flv=path.join(directory,name+'.flv'),backend=[];let physicalStarts=0,physicalStops=0,video,audio,index=150,broadcast=null;
    const raw={status:()=>({prepared:true,peerId:'synthetic-output',rendered:true,audioReady:true,generation:7}),startCapture:async(v,a)=>{physicalStarts++;video=v;audio=a;},stopCapture:async()=>{physicalStops++;video=audio=null;},close:async()=>{},prepare:async()=>{}};
    const shared=activeShared=createSharedOutputCapture({capture:raw}),broker=createEncodingReservations({identity,ownerPid:process.pid,request:async(_url,body)=>{backend.push(body.active);return {ok:true,native_encoding:{active:body.active,owner_pid:body.active?process.pid:null,mode:body.active?body.mode:'broadcast',...(body.rehearsal_generation?{rehearsal_generation:body.rehearsal_generation}:{})}};}}),streamLease=shared.forConsumer('broadcast');
    const recorder=activeRecorder=new NativeRecording({getCapture:()=>shared.forConsumer('recording',{onFault:code=>recorder.stop(code)}),getProfile:()=>profile,checkReady:async()=>({ready:true,generation:7}),request:broker.requestFor('recording'),identity,ownerPid:process.pid,canPublish:async()=>true,chooseFile:async()=>destination,confirm:async()=>true,
      ...(lowSpace?{inspectFile:async selected=>({path:selected,minimumFreeBytes:Number.MAX_SAFE_INTEGER})}:{}),createEncoderGroup:(observe,options)=>makeGroup(observe,options)});
    async function beginBroadcast(){
      await broker.requestFor('broadcast')('/api/desktop/encoding-status',{...identity,owner_pid:process.pid,active:true});
      broadcast=activeGroup=makeGroup(()=>{},{artifactRoot:directory});await broadcast.start({width:1280,height:720,fps:30,bitrate:4000000,codec:'auto',audioBitrateKbps:96,keyframeSeconds:1,twitchVod:false,targets:[{id:'synthetic-stream',testOutput:flv,twitchVod:false}]});
      await streamLease.startCapture((bytes,pts)=>broadcast.sendVideo(bytes,pts),(bytes,pts)=>broadcast.sendAudio(bytes,pts));
    }
    async function endBroadcast(){await streamLease.stopCapture();const stopped=await broadcast.stop();assert.equal(stopped.running,false);await broker.requestFor('broadcast')('/api/desktop/encoding-status',{...identity,owner_pid:process.pid,active:false});activeGroup=null;return stopped;}
    async function frames(count){
      for(let j=0;j<count;j++,index++){
        const pts=Math.round(index*1e6/30),picture=Buffer.alloc(1280*720*4,0);for(let offset=0;offset<picture.length;offset+=4){picture[offset]=index%256;picture[offset+1]=Math.floor(offset/5120)%256;picture[offset+2]=80;picture[offset+3]=255;}
        const pcm=Buffer.alloc(1600*8);for(let sample=0;sample<1600;sample++){const value=.15*Math.sin(2*Math.PI*440*(index*1600+sample)/48000);pcm.writeFloatLE(value,sample*8);pcm.writeFloatLE(value,sample*8+4);}
        assert.equal(audio(pcm,pts,pcm),true);assert.equal(video(picture,pts),true);await pause(34);
      }
      await pause(80);
    }
    if(broadcastFirst){await beginBroadcast();await frames(4);}
    if(lowSpace){
      await assert.rejects(recorder.start({requestId:name}));assert.equal(recorder.status().finalized,false);assert.equal(broker.status().holds.length,1);assert.equal(shared.status().consumers.join(','),'broadcast');await frames(12);const stream=await endBroadcast();assert.ok(stream.videoFrames>=12);assert.equal(backend.filter(v=>v===false).length,1);results.push({name,diskFailureIsolated:true,recording:recorder.status(),stream,files:[flv]});activeRecorder=null;activeShared=null;return;
    }
    await recorder.start({requestId:name});await frames(16);
    if(!broadcastFirst&&stopBroadcastFirst){await beginBroadcast();await frames(12);}
    let stream;
    if(stopBroadcastFirst){stream=await endBroadcast();assert.equal(broker.status().holds[0].purpose,'recording');assert.equal(physicalStops,0);await frames(10);}
    const saved=await recorder.stop();assert.equal(saved.finalized,true);assert.equal(saved.phase,'saved');assert.equal(saved.active,false);assert.equal(recorder.getSavedPath(),destination);
    if(broadcastFirst&&!stopBroadcastFirst){assert.equal(physicalStops,0);assert.equal(broker.status().holds[0].purpose,'broadcast');await frames(10);stream=await endBroadcast();}
    assert.equal(physicalStarts,1);assert.equal(physicalStops,1);assert.equal(broker.status().active,false);assert.equal(backend.filter(v=>v===false).length,1);results.push({name,physicalStarts,physicalStops,recording:saved,...(stream?{stream}:{}),files:[destination,...(stream?[flv]:[])]});activeRecorder=null;activeShared=null;
  }
  try{
    await scenario('record-only');await scenario('stream-first-stop-recording',{broadcastFirst:true});await scenario('record-first-stop-stream',{stopBroadcastFirst:true});await scenario('disk-refusal-keeps-stream',{broadcastFirst:true,lowSpace:true});
    const decode=`import json,sys\nsys.path.insert(0,sys.argv[1])\nimport av,numpy as np\nresults=[]\nfor p in sys.argv[2:]:\n with av.open(p) as m:\n  video=list(m.decode(video=0)); name=m.format.name; codec=m.streams.video[0].codec_context.name\n with av.open(p) as m:\n  audio=list(m.decode(audio=0)); samples=np.concatenate([f.to_ndarray().reshape(-1) for f in audio]); rms=float(np.sqrt(np.mean(samples**2)))\n assert len(video)>=10 and rms>.05\n results.append(dict(file=p,format=name,codec=codec,frames=len(video),rms=rms,audioSamples=sum(f.samples for f in audio)))\nprint(json.dumps(results))`;
    const files=results.flatMap(result=>result.files||[]),decoded=await new Promise((resolve,reject)=>{const process=spawn(python,['-B','-c',decode,pythonPackages,...files],{windowsHide:true,stdio:['ignore','pipe','pipe']});let output='',error='';process.stdout.on('data',value=>output+=value);process.stderr.on('data',value=>error+=value);process.on('error',reject);process.on('close',code=>code===0?resolve(JSON.parse(output)):reject(Error('generated_decode_failed '+error)));});
    await fs.writeFile(path.join(directory,'results.json'),JSON.stringify({generatedOnly:true,results,decoded},null,2));console.log(JSON.stringify({directory,scenarios:results.length,decoded:decoded.length,passed:true}));
  }finally{await activeRecorder?.stop();await activeGroup?.stop();await activeShared?.close();}
}
main().catch(error=>{console.error(error.code||error.message);process.exitCode=1;});
