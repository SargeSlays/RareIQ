'use strict';
// Explicit local synthetic media only: no real destination, camera or microphone.
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const {setTimeout:pause}=require('node:timers/promises');
const {NativeBroadcast}=require('../broadcast.cjs'),{Encoder}=require('../encoder.cjs');
async function main(){
  const root=process.argv[2]?path.resolve(process.argv[2]):null;
  if(!root||!path.isAbsolute(root)||path.parse(root).root.toLowerCase()!=='f:\\')throw Error('New F: evidence directory required');
  await fs.mkdir(root,{recursive:true});
  const profiles={id:'synthetic-dual',name:'Synthetic output',format:'hd',fps:30,videoBitrateKbps:4000,codec:'auto',keyframeSeconds:2,audioBitrateKbps:192,twitchVod:true,audioRouting:{}};
  const ownership=[],workers=[],outputs=[];let captureRun=null,captureCount=0;
  const capture={prepare:async()=>{},review:async()=>{},close:async()=>{},status:()=>({peerId:'synthetic-peer',generation:1,rendered:true,prepared:true,browserReviewOpen:false,audioBlocked:false,audioReady:true}),
    startCapture:async(video,audio)=>{captureCount++;captureRun={video,audio};},stopCapture:async()=>{captureRun=null;}};
  const app=new NativeBroadcast({destinations:{getPrivateDestination:async id=>({name:id,platform:id==='twitch'?'twitch':'youtube',serverUrl:'rtmps://synthetic.invalid/app',streamKey:'not-a-real-key'})},outputProfiles:{getProfile:async()=>structuredClone(profiles)},
    createCapture:()=>capture,identity:{pid:1,server_session_id:'synthetic-only'},ownerPid:2,confirm:async()=>true,
    request:async(url,body)=>{if(body)ownership.push(body.active);return {preflight:{ready:true,generation:1,blockers:[]}};},
    createEncoder:onState=>{
      const worker=new Encoder({python:path.resolve(__dirname,'../../.venv/Scripts/python.exe'),workerPath:path.resolve(__dirname,'../encoder_worker.py'),pythonPackages:'F:/Caches/ProducerPlease/python-packages',artifactRoot:root,onState});
      const target=path.join(root,'target-'+workers.length+'-'+Date.now()+'.flv'),start=worker.start.bind(worker);
      worker.start=value=>start({...value,testOutput:target});workers.push(worker);outputs.push(target);return worker;
    }});
  try{
    await app.prepare({profileId:profiles.id});await app.start({profileId:profiles.id,destinationIds:['twitch','youtube']});assert.equal(captureCount,1);
    const video=Buffer.alloc(1280*720*4);for(let i=3;i<video.length;i+=4)video[i]=255;
    let videoIndex=-1;
    for(let block=0;block<240;block++){
      assert.ok(captureRun,'Shared capture remains active');
      const pts=block*10000,live=Buffer.alloc(3840),vod=Buffer.alloc(3840);
      for(let n=0;n<480;n++){
        const sample=block*480+n,voice=.12*Math.sin(2*Math.PI*440*sample/48000),music=.12*Math.sin(2*Math.PI*880*sample/48000);
        for(const offset of [n*8,n*8+4]){live.writeFloatLE(voice+music,offset);vod.writeFloatLE(voice,offset);}
      }
      const frameIndex=Math.floor(block*30/100);if(frameIndex>videoIndex){videoIndex=frameIndex;video[0]=block;captureRun.video(video,Math.round(frameIndex*1e6/30));}
      captureRun.audio(live,pts,vod);await pause(10);
    }
    const before=app.status();assert.equal(before.targets.length,2);assert.ok(before.targets.every(t=>t.frames>0));
    await app.stop();assert.equal(app.active(),false);assert.deepEqual(ownership,[true,false]);assert.equal(workers.every(w=>!w.status().running),true);
    const result={complete:true,syntheticOnly:true,hardware:false,externalBroadcast:false,sharedCaptureCount:captureCount,outputs,targets:before.targets,stopped:workers.map(w=>w.status()),platformLiveVerified:false,vodPlatformVerified:false};
    await fs.writeFile(path.join(root,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({complete:true,outputs,captureCount}));
  }finally{await app.close();}
}
main().catch(error=>{console.error('synthetic_multistream_failed',/^[a-z_]{1,80}$/.test(error.message)?error.message:error.name);process.exitCode=1;});
