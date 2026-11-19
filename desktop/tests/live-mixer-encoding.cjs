'use strict';
// Generated local media only. No real destinations, devices, listening or credentials.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict'),{_electron}=require('playwright');
async function main(){
  const root=process.argv[2]?path.resolve(process.argv[2]):null,executablePath=process.argv[3];
  if(!root||path.parse(root).root.toLowerCase()!=='f:\\'||!executablePath)throw Error('New F: evidence root and Electron executable required');
  await fs.mkdir(path.dirname(root),{recursive:true});await fs.mkdir(root);
  const app=await _electron.launch({executablePath,args:[path.join(__dirname,'output-capture-native-app.cjs')],env:{...process.env,PRODUCER_OUTPUT_QA_PROFILE:path.join(root,'profile')}});
  try{
    const page=await app.firstWindow();await page.waitForFunction(()=>Boolean(document.querySelector('iframe.program')));let ready=false;
    for(let n=0;n<100&&!ready;n++){ready=await app.evaluate(()=>globalThis.outputFixture?.ready===true);if(!ready)await new Promise(r=>setTimeout(r,50));}assert.ok(ready);
    await app.evaluate(async(_,cfg)=>{
      const require=process.getBuiltinModule('node:module').createRequire(cfg.broadcast);
      const {NativeBroadcast}=require(cfg.broadcast),{SharedEncoderGroup}=require(cfg.group),capture=outputFixture.capture;
      globalThis.liveEncodeProof={captureCreates:0,groupCreates:0,stops:0,pts:[],audits:[],outputs:[cfg.root+'/twitch.flv',cfg.root+'/other.flv']};const proof=liveEncodeProof;
      const start=capture.startCapture.bind(capture),stop=capture.stopCapture.bind(capture);
      capture.startCapture=(video,audio)=>start(video,(a,pts,b)=>{proof.pts.push(pts);return audio(a,pts,b);});capture.stopCapture=()=>{proof.stops++;return stop();};
      const profile={id:'live-test',name:'Synthetic live mix',format:'hd',fps:30,videoBitrateKbps:4000,codec:'auto',keyframeSeconds:2,audioBitrateKbps:192,twitchVod:true,audioRouting:{'voice:default':{live:true,vod:true}}};
      globalThis.liveBroker=new NativeBroadcast({outputProfiles:{getProfile:async()=>structuredClone(profile)},destinations:{getPrivateDestination:async id=>({platform:id==='twitch'?'twitch':'youtube',name:id,serverUrl:'rtmps://synthetic.invalid/app',streamKey:'not-real'})},
        createCapture:()=>{proof.captureCreates++;return capture;},createEncoderGroup:onState=>{proof.groupCreates++;const group=new SharedEncoderGroup({python:cfg.python,workerPath:cfg.worker,pythonPackages:cfg.packages,artifactRoot:cfg.root,onState}),original=group.start.bind(group);group.start=value=>original({...value,targets:value.targets.map((target,i)=>{const {destination,...safe}=target;return {...safe,testOutput:proof.outputs[i]};})});return group;},
        identity:{pid:1,server_session_id:'synthetic'},ownerPid:2,confirm:async()=>true,request:async()=>({preflight:{ready:true,generation:1,blockers:[]}}),onAudioAudit:entry=>proof.audits.push(entry)});
      await liveBroker.prepare({profileId:profile.id});await liveBroker.start({profileId:profile.id,destinationIds:['twitch','other']});
    },{root:root.replaceAll('\\','/'),broadcast:path.resolve(__dirname,'../broadcast.cjs'),group:path.resolve(__dirname,'../shared-encoder.cjs'),python:path.resolve(__dirname,'../../.venv/Scripts/python.exe'),worker:path.resolve(__dirname,'../shared_encoder_worker.py'),packages:'F:/Caches/ProducerPlease/python-packages'});
    await new Promise(r=>setTimeout(r,1600));
    const before=await app.evaluate(()=>({frames:liveBroker.status().frames,audio:liveBroker.status().audioSamples}));
    await app.evaluate(async()=>{const mix=liveBroker.status().audioMix;await liveBroker.setLiveAudio({outputId:mix.outputId,expectedRevision:mix.revision,requestId:'live-up',audioRouting:{'voice:default':{live:true,vod:true,liveGainDb:6.0206}}});});
    await new Promise(r=>setTimeout(r,1600));
    await app.evaluate(async()=>{const mix=liveBroker.status().audioMix;await liveBroker.setLiveAudio({outputId:mix.outputId,expectedRevision:mix.revision,requestId:'vod-down',audioRouting:{'voice:default':{live:true,vod:true,liveGainDb:6.0206,vodGainDb:-6.0206}}});});
    await new Promise(r=>setTimeout(r,1600));
    const result=await app.evaluate(async()=>{
      const during=liveBroker.status(),proof=liveEncodeProof;const unchanged=liveBroker.outputProfile.audioRouting['voice:default'].liveGainDb===undefined;
      if(proof.stops!==0)throw Error('capture restarted');const group=liveBroker.encoderGroup;await liveBroker.stop();
      return {...proof,beforeStop:during,encoderStopped:!group.status().running,group:group.status(),savedProfileUnchanged:unchanged,maxPcmGapUs:proof.pts.reduce((m,p,i,a)=>i?Math.max(m,p-a[i-1]):m,0),pcmPackets:proof.pts.length,errors:outputFixture.stats.errors};
    });
    delete result.pts;assert.equal(result.captureCreates,1);assert.equal(result.groupCreates,1);assert.equal(result.beforeStop.audioMix.revision,2);assert.ok(result.beforeStop.frames>before.frames);assert.ok(result.beforeStop.audioSamples>before.audio);assert.equal(result.encoderStopped,true);assert.equal(result.savedProfileUnchanged,true);assert.ok(result.maxPcmGapUs<=30000);assert.deepEqual(result.errors,[]);
    await fs.writeFile(path.join(root,'results.json'),JSON.stringify({complete:true,syntheticOnly:true,physicalCapture:false,externalBroadcast:false,...result},null,2));console.log(JSON.stringify({complete:true,captureCreates:result.captureCreates,groupCreates:result.groupCreates,maxPcmGapUs:result.maxPcmGapUs,frames:result.group.videoFrames}));
  }finally{try{await app.evaluate(async()=>{await globalThis.liveBroker?.close();outputFixture?.close();});}catch(_){}await app.close();}
}
main().catch(error=>{console.error('live_encoding_fixture_failed',String(error.message).split('\n')[0].slice(0,250));process.exitCode=1;});
