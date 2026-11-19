'use strict';
// Bounded generated-media proof of the real JS owner -> Python discard mux path.
// Only a metadata report is written; no device, destination or media file opens.
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs/promises'),{setTimeout:pause}=require('node:timers/promises');
const {SharedEncoderGroup}=require('../shared-encoder.cjs');
const evidenceRoot=path.resolve('F:/Temp/jonat/ProducerPlease-rehearsal-20261119');

async function run(vod,{stopTarget=false}={}){
  const group=new SharedEncoderGroup({python:path.resolve(__dirname,'../../.venv/Scripts/python.exe'),pythonPackages:'F:/Caches/ProducerPlease/python-packages'});
  const target=group.createTarget('rehearsal-local'),events=[];group.on('state',state=>events.push(state));
  const value={width:64,height:64,fps:30,bitrate:500000,codec:'libx264',audioBitrateKbps:96,keyframeSeconds:1,twitchVod:vod,rehearsal:true,targets:[{id:'rehearsal-local',rehearsal:true,twitchVod:vod}]};
  const startedAt=Date.now(),ready=await group.start(value);let independentStop;
  try{
    for(let index=0;index<30;index++){
      const video=Buffer.alloc(64*64*4);for(let pixel=0;pixel<64*64;pixel++){video[pixel*4]=index*7;video[pixel*4+1]=pixel%256;video[pixel*4+3]=255;}
      const pcm=frequency=>{const data=Buffer.alloc(1600*8);for(let sample=0;sample<1600;sample++){const amplitude=.1*Math.sin(2*Math.PI*frequency*(index*1600+sample)/48000);data.writeFloatLE(amplitude,sample*8);data.writeFloatLE(amplitude,sample*8+4);}return data;};
      const pts=Math.round(index*1e6/30),inputs=[[group.sendVideo.bind(group),video],[group.sendAudio.bind(group),pcm(440)]];
      if(vod)inputs.push([group.sendVodAudio.bind(group),pcm(880)]);
      for(const [send,data] of inputs)while(!send(data,pts)){if(group.status().state==='failed'||Date.now()-startedAt>15000)throw Error(group.status().code||'rehearsal_feed_timeout');await pause(2);}
      await pause(5);
      if(stopTarget&&index===14){independentStop=await target.stop();assert.equal(independentStop.running,false);assert.equal(group.status().running,true);assert.equal(group.status().state==='failed',false);}
    }
    const stopped=await group.stop();assert.equal(stopped.running,false);assert.equal(stopped.state,'stopped');assert.equal(stopped.videoFrames,30);assert.equal(stopped.audioSamples,48000);assert.equal(stopped.vodAudioSamples,vod?48000:0);assert.equal(stopped.videoEncoderInstances,1);assert.equal(stopped.targetMuxerCount,1);assert.ok(stopped.packets>30&&stopped.bytesMuxed>0&&stopped.bytesDiscarded>0);assert.equal(target.status().running,false);
    for(const state of [...events,target.status()]){assert.equal(state.rehearsal,true);assert.equal(state.localDiscard,true);for(const key of ['networkVerified','tlsVerified','twitchVodWireVerified','platformVerified','platformLiveVerified','vodPlatformVerified'])assert.equal(state[key],false);}
    return {vod,stopTarget,ready,independentStop,stopped,target:target.status(),elapsedMs:Date.now()-startedAt};
  }finally{if(group.status().running)await group.stop();}
}

async function main(){
  const directory=path.join(evidenceRoot,'encoder-'+Date.now());assert.equal(path.dirname(directory),evidenceRoot);await fs.mkdir(evidenceRoot,{recursive:true});await fs.mkdir(directory);
  const results={scope:'Synthetic local discard encoding only; no platform, device, network or recording acceptance.',runs:[await run(false),await run(true),await run(false,{stopTarget:true})]};
  assert.deepEqual(await fs.readdir(directory),[]);const report=path.join(directory,'results.json');await fs.writeFile(report,JSON.stringify(results,null,2),{flag:'wx'});console.log(JSON.stringify({report,runs:results.runs.map(({vod,stopTarget,stopped,target})=>({vod,stopTarget,videoFrames:stopped.videoFrames,packets:stopped.packets,bytesDiscarded:stopped.bytesDiscarded,targetFrames:target.videoFrames,running:stopped.running}))}));
}
main().catch(error=>{console.error(error.code||error.message||'local_rehearsal_failed');process.exitCode=1;});
