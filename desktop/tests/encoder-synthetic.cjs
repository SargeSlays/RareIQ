'use strict';
// Explicit synthetic-only rehearsal. Does not open devices or network outputs.
const {Encoder}=require('../encoder.cjs'),path=require('node:path'),fs=require('node:fs/promises'),{setTimeout:pause}=require('node:timers/promises');
async function main(){
  const artifactRoot=path.resolve(process.argv[2]||'F:/Temp/jonat/ProducerPlease-encoder-synthetic');await fs.mkdir(artifactRoot,{recursive:true});
  const testOutput=path.join(artifactRoot,'synthetic-'+Date.now()+'.flv');
  const testTransport=process.env.PRODUCER_ENCODER_TEST_PORT?{port:Number(process.env.PRODUCER_ENCODER_TEST_PORT),caFile:path.join(artifactRoot,'ca.pem'),serverName:process.env.PRODUCER_ENCODER_TEST_HOST||'localhost'}:undefined;
  const runtime=process.argv[3]?JSON.parse(await fs.readFile(path.resolve(process.argv[3]),'utf8')):{};
  const encoder=new Encoder({python:runtime.python||path.resolve(__dirname,'../../.venv/Scripts/python.exe'),workerPath:runtime.encoderWorker,pythonPackages:runtime.pythonPackages||'F:/Caches/ProducerPlease/python-packages',artifactRoot,testTransport});
  const events=[];encoder.on('state',state=>events.push(state));
  const ready=await encoder.start({width:320,height:180,fps:30,codec:process.env.PRODUCER_ENCODER_TEST_CODEC||'auto',...(testTransport?{}:{testOutput})});
  for(let index=0;index<90;index++){
    const video=Buffer.alloc(320*180*4);for(let pixel=0;pixel<320*180;pixel++){video[pixel*4]=index*2;video[pixel*4+1]=Math.floor(pixel/320)%256;video[pixel*4+2]=pixel%256;video[pixel*4+3]=255;}
    const audio=Buffer.alloc(1600*8);for(let sample=0;sample<1600;sample++){const value=Math.sin(2*Math.PI*440*(index*1600+sample)/48000)*.1;audio.writeFloatLE(value,sample*8);audio.writeFloatLE(value,sample*8+4);}
    const ptsUs=Math.round(index*1e6/30);
    const inputs=[[encoder.sendVideo.bind(encoder),video]];if(!(process.env.PRODUCER_ENCODER_TEST_AUDIO_GAP==='1'&&index===30))inputs.push([encoder.sendAudio.bind(encoder),audio]);
    for(const [send,buffer] of inputs)while(!send(buffer,ptsUs)){if(encoder.status().state==='failed')throw Error(encoder.status().code);await pause(2);}
    await pause(33);
  }
  const stopped=await encoder.stop();if(stopped.state!=='stopped'||stopped.running)throw Error('synthetic_encoder_did_not_stop');
  const outputPath=testTransport?undefined:testOutput;const result={testOutput:outputPath,ready,stopped,events};await fs.writeFile(path.join(artifactRoot,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({testOutput:outputPath,ready,stopped}));
}
main().catch(()=>{console.error('synthetic_encoder_rehearsal_failed');process.exitCode=1;});
