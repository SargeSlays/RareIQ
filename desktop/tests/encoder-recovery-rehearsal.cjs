'use strict';
// Explicit generated-media rehearsal. No Studio API, platform or device is used.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto'),tls=require('node:tls'),net=require('node:net');
const {spawn,execFileSync}=require('node:child_process'),{pathToFileURL}=require('node:url');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const readJson=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const writeJson=(file,value)=>fs.writeFileSync(file,JSON.stringify(value,null,2));
async function until(test,timeout,reason){const end=Date.now()+timeout;while(!test()){if(Date.now()>end)throw Error(reason);await pause(20);}}
async function reservePort(){const server=net.createServer();await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});const port=server.address().port;await new Promise(resolve=>server.close(resolve));assert.ok(![8765,8767].includes(port));return port;}
function media(index){
  const video=Buffer.alloc(320*180*4),audio=Buffer.alloc(1600*8);
  for(let pixel=0;pixel<320*180;pixel++){video[pixel*4]=(index*3)%256;video[pixel*4+1]=Math.floor(pixel/320)%256;video[pixel*4+2]=pixel%256;video[pixel*4+3]=255;}
  for(let sample=0;sample<1600;sample++){const tone=Math.sin(2*Math.PI*440*(index*1600+sample)/48000)*.1;audio.writeFloatLE(tone,sample*8);audio.writeFloatLE(tone,sample*8+4);}
  return {video,audio,pts:Math.round(index*1e6/30)};
}
async function sendFrame(encoder,index){
  const {video,audio,pts}=media(index),end=Date.now()+1500;
  for(const [send,buffer] of [[encoder.sendVideo.bind(encoder),video],[encoder.sendAudio.bind(encoder),audio]]){
    while(!send(buffer,pts)){
      if(encoder.status().state==='failed')return false;
      if(Date.now()>end)throw Error('generated_input_backpressure_timeout');
      await pause(2);
    }
  }
  return true;
}

async function main(){
  const root=path.resolve(process.argv[2]||'F:/Temp/jonat/ProducerPlease-recovery-20261118/encoder');
  assert.equal(path.parse(root).root.toLowerCase(),'f:\\','Evidence must use a new F: directory');
  fs.mkdirSync(path.dirname(root),{recursive:true});fs.mkdirSync(root);
  const build=readJson(process.argv[3]||'F:/Apps/ProducerPlease/latest-bundled-build.json');
  const resources=path.join(path.dirname(build.executable),'resources'),runtime=readJson(path.join(resources,'runtime.json'));
  assert.equal(runtime.buildKind,'bundled-runtime');
  const inside=name=>{const file=fs.realpathSync(path.resolve(resources,name));assert.ok(!path.relative(fs.realpathSync(resources),file).startsWith('..'));return file;};
  const python=inside(runtime.python),worker=inside(runtime.encoderWorker),ffmpeg=inside(runtime.ffmpeg),ffprobe=inside('bin/ffprobe.exe');
  const asar=await import(pathToFileURL(process.env.PRODUCER_ASAR_MODULE||'F:/Caches/ProducerPlease/desktop-dependencies/node_modules/@electron/asar/lib/asar.js').href);
  const coordinator=asar.extractFile(path.join(resources,'app.asar'),'encoder.cjs');
  const coordinatorPath=path.join(root,'bundled-encoder.cjs');fs.writeFileSync(coordinatorPath,coordinator);
  assert.equal(hash(coordinator),hash(fs.readFileSync(path.join(__dirname,'../encoder.cjs'))),'Source coordinator differs from packaged module');
  const {Encoder}=require(coordinatorPath),owned=new Set(),children=[],encoders=[];
  const result={ok:false,syntheticMedia:true,localTlsOnly:true,physicalCapture:false,platformBroadcast:false,
    studioServersContacted:false,python,worker,coordinatorSha256:hash(coordinator),workerSha256:hash(fs.readFileSync(worker)),sourceMatchesPackagedCoordinator:true};
  let server,connections=[],receiver,plainPort,networkEncoder;
  const startOwned=(label,executable,args,options)=>{
    const child=spawn(executable,args,{...options,windowsHide:true});owned.add(child);
    const receipt={label,pid:child.pid,closed:false};children.push(receipt);
    child.on('close',(code,signal)=>{owned.delete(child);receipt.closed=true;receipt.code=code;receipt.signal=signal;});
    child.on('error',()=>{});
    const log=fs.createWriteStream(path.join(root,label+'.stderr.log'));
    child.stderr?.on('data',chunk=>log.write(chunk));child.on('close',()=>log.end());
    return child;
  };
  const createEncoder=(label,extra={})=>{
    const events=[],encoder=new Encoder({python,workerPath:worker,pythonPackages:inside(runtime.pythonPackages),
      artifactRoot:root,startTimeoutMs:12000,stopTimeoutMs:6000,
      spawnProcess:(...args)=>startOwned(label,...args),onState:value=>events.push({...value,observedAt:Date.now()}),...extra});
    encoders.push(encoder);return {encoder,events};
  };
  try{
    // Reuse only the existing fixture's certificate generator, not its encoder.
    const certHelper=path.join(__dirname,'encoder_tls_rehearsal.py');
    execFileSync(python,['-B','-c',"import runpy,sys; from pathlib import Path; runpy.run_path(sys.argv[1])['certificates'](Path(sys.argv[2]))",certHelper,root],{windowsHide:true,timeout:10000,stdio:'pipe'});
    plainPort=await reservePort();
    receiver=startOwned('tls-receiver',ffmpeg,['-hide_banner','-loglevel','error','-progress','pipe:1','-stats_period','0.1',
      '-listen','1','-timeout','12','-analyzeduration','500000','-probesize','100000','-i',`rtmp://127.0.0.1:${plainPort}/app/synthetic-fixture`,
      '-map','0','-c','copy','-f','flv','-n',path.join(root,'before-disconnect.flv')],{stdio:['ignore','pipe','pipe']});
    let progress='',receivedFrames=0,connectionsAccepted=0,tlsBytes=0,tlsProtocol=null;
    receiver.stdout.on('data',chunk=>{progress+=chunk.toString();let end;while((end=progress.indexOf('\n'))>=0){const line=progress.slice(0,end).trim();progress=progress.slice(end+1);if(line.startsWith('frame='))receivedFrames=Math.max(receivedFrames,Number(line.slice(6))||0);}});
    await pause(400);
    assert.equal(receiver.exitCode,null,'Local RTMP receiver failed before test');
    server=tls.createServer({cert:fs.readFileSync(path.join(root,'server.pem')),key:fs.readFileSync(path.join(root,'fixture-key.pem'))},secure=>{
      connectionsAccepted++;tlsProtocol=secure.getProtocol();connections.push(secure);
      const plain=net.createConnection({host:'127.0.0.1',port:plainPort});connections.push(plain);
      secure.on('data',chunk=>tlsBytes+=chunk.length);
      secure.on('error',()=>{});plain.on('error',()=>secure.destroy());
      secure.once('close',()=>plain.destroy());plain.once('close',()=>secure.destroy());
      secure.pipe(plain);plain.pipe(secure);
    });
    server.on('tlsClientError',()=>{});
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    const port=server.address().port;assert.ok(![8765,8767].includes(port));
    const network=createEncoder('network-encoder',{testTransport:{port,caFile:path.join(root,'ca.pem'),serverName:'localhost'}});
    result.networkEvents=network.events;
    networkEncoder=network.encoder;
    const caseStart=Date.now(),ready=await networkEncoder.start({width:320,height:180,fps:30,bitrate:1000000,codec:'libx264'});
    assert.equal(ready.tlsVerified,true);
    let disconnectedAt=null,index=0,framesAtDisconnect=0;
    while(Date.now()-caseStart<25000){
      if(!await sendFrame(networkEncoder,index++))break;
      if(disconnectedAt===null&&receivedFrames>=30){
        disconnectedAt=Date.now();framesAtDisconnect=receivedFrames;
        for(const socket of connections)socket.destroy();
        await new Promise(resolve=>server.close(resolve));
      }
      if(networkEncoder.status().state==='failed')break;
      await pause(33);
    }
    assert.ok(disconnectedAt,'Receiver never proved media before disconnect');
    await until(()=>networkEncoder.status().state==='failed'&&!networkEncoder.status().running,5000,'network_failure_did_not_close_child');
    const failed=networkEncoder.status();
    assert.ok(['encoder_failed','tls_connection_failed','encoder_transport_interrupted','encoder_input_failed','encoder_exited'].includes(failed.code),'Unexpected public failure code');
    assert.equal(failed.platformVerified,false);assert.equal(failed.queuedBytes,0);
    const failureObservedAt=Date.now();
    await pause(750);
    assert.equal(children.filter(child=>child.label==='network-encoder').length,1,'Unexpected automatic encoder retry');
    assert.equal(connectionsAccepted,1,'Unexpected transport reconnect');
    assert.equal(networkEncoder.status().running,false);
    result.disconnect={ready,failed,framesAtDisconnect,tlsBytes,tlsProtocol,connectionsAccepted,
      failureLatencyMs:failureObservedAt-disconnectedAt,elapsedMs:failureObservedAt-caseStart,noAutomaticRetry:true,events:network.events};
    assert.ok(result.disconnect.elapsedMs<30000,'Disconnect case exceeded bounded duration');
    // An operator's deliberate fresh start uses a new local-file encoder owner.
    const recovery=createEncoder('recovery-encoder'),recoveryStart=Date.now(),testOutput=path.join(root,'explicit-recovery.flv');
    await recovery.encoder.start({width:320,height:180,fps:30,bitrate:1000000,codec:'libx264',testOutput});
    for(let frame=0;frame<90;frame++){assert.equal(await sendFrame(recovery.encoder,frame),true);await pause(33);}
    const stopped=await recovery.encoder.stop();
    assert.equal(stopped.state,'stopped');assert.equal(stopped.running,false);assert.equal(stopped.videoFrames,90);
    assert.equal(stopped.droppedVideoFrames,0);assert.equal(stopped.droppedAudioPackets,0);
    const probe=JSON.parse(execFileSync(ffprobe,['-v','error','-count_frames','-show_entries','stream=codec_name,codec_type,width,height,sample_rate,channels,nb_read_frames','-of','json',testOutput],{windowsHide:true,timeout:10000,encoding:'utf8'}));
    const video=probe.streams.find(item=>item.codec_type==='video'),audio=probe.streams.find(item=>item.codec_type==='audio');
    assert.equal(video.codec_name,'h264');assert.equal(Number(video.nb_read_frames),90);
    assert.equal(audio.codec_name,'aac');assert.equal(audio.sample_rate,'48000');assert.equal(audio.channels,2);
    execFileSync(ffmpeg,['-v','error','-i',testOutput,'-f','null','-'],{windowsHide:true,timeout:10000,stdio:'pipe'});
    const pcm=execFileSync(ffmpeg,['-v','error','-i',testOutput,'-vn','-ac','1','-ar','48000','-f','f32le','-'],{windowsHide:true,timeout:10000,maxBuffer:4*1024*1024});
    let square=0,sine=0,cosine=0;const samples=pcm.length/4;
    for(let sample=0;sample<samples;sample++){const value=pcm.readFloatLE(sample*4),phase=2*Math.PI*440*sample/48000;square+=value*value;sine+=value*Math.sin(phase);cosine+=value*Math.cos(phase);}
    const rms=Math.sqrt(square/samples),toneAmplitude=2*Math.hypot(sine,cosine)/samples;
    assert.ok(rms>.01&&toneAmplitude>.05,'Generated tone missing from decoded recovery');
    result.recovery={stopped,elapsedMs:Date.now()-recoveryStart,probe,decoded:true,decodedAudioRms:rms,tone440Amplitude:toneAmplitude,events:recovery.events};
    assert.ok(result.recovery.elapsedMs<30000);writeJson(path.join(root,'recovery-ffprobe.json'),probe);
    result.ok=true;
  }catch(error){
    result.failure=String(error.code||error.message||'rehearsal_failed').replace(/[^a-zA-Z0-9_ .:-]/g,'').slice(0,180);
  }finally{
    for(const socket of connections)socket.destroy();
    if(server?.listening)await new Promise(resolve=>server.close(resolve));
    for(const encoder of encoders)if(encoder.status().running)await encoder.stop();
    if(receiver&&owned.has(receiver)){try{await until(()=>!owned.has(receiver),2000,'receiver_close_pending');}catch(_){receiver.kill();}}
    for(const child of [...owned])child.kill();
    await until(()=>owned.size===0,5000,'owned_children_did_not_close');
    result.children=children;result.allOwnedChildrenClosed=children.every(child=>child.closed);result.listenerClosed=!server?.listening;
    result.ok=result.ok&&result.allOwnedChildrenClosed&&result.listenerClosed;
    writeJson(path.join(root,'results.json'),result);
  }
  console.log(JSON.stringify({ok:result.ok,failure:result.failure,disconnect:result.disconnect&&{code:result.disconnect.failed.code,latencyMs:result.disconnect.failureLatencyMs,receivedFrames:result.disconnect.framesAtDisconnect,noAutomaticRetry:result.disconnect.noAutomaticRetry},recovery:result.recovery&&{frames:result.recovery.stopped.videoFrames,decoded:result.recovery.decoded},allOwnedChildrenClosed:result.allOwnedChildrenClosed,listenerClosed:result.listenerClosed}));
  if(!result.ok)process.exitCode=1;
}
main().catch(()=>{console.error('encoder_recovery_rehearsal_failed');process.exitCode=1;});
