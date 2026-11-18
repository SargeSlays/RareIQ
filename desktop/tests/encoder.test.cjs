'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{EventEmitter}=require('node:events'),{PassThrough,Writable}=require('node:stream');
const {Encoder,packet}=require('../encoder.cjs');
function fixture(options={}){
  let args,settings,writes=[],pending=[];const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.killed=false;
  child.stdin=new Writable({write(chunk,encoding,done){writes.push(Buffer.from(chunk));if(options.block)pending.push(done);else done();}});
  child.kill=()=>{child.killed=true;setImmediate(()=>child.emit('close',1));};
  const encoder=new Encoder({python:path.resolve('synthetic-python'),workerPath:path.resolve('encoder_worker.py'),artifactRoot:path.resolve('F:/Temp/encoder-test'),startTimeoutMs:1000,stopTimeoutMs:100,...options,spawnProcess:(exe,argv,config)=>{args=argv;settings=config;return child;}});
  return {encoder,child,writes,pending,get args(){return args;},get settings(){return settings;},message(value){child.stdout.write(JSON.stringify(value)+'\n');}};
}
const config={destination:{serverUrl:'rtmps://ingest.provider.com/app',streamKey:'synthetic-private-key'},width:64,height:64,fps:30};
async function withinTestDeadline(promise){
  // The fake child has no process handle to keep unref'ed encoder timers alive.
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('encoder_test_deadline_exceeded')),2000);})]);}
  finally{clearTimeout(timer);}
}
test('private configuration uses stdin only and public events are whitelisted',async()=>{
  const f=fixture();const started=f.encoder.start(config);f.message({event:'ready',codec:'libx264',url:'synthetic-private-key',hardwareVerified:false});await started;
  assert.equal(f.args.includes('synthetic-private-key'),false);assert.equal(JSON.stringify(f.settings).includes('synthetic-private-key'),false);
  assert.equal(JSON.parse(f.writes[0].toString()).destination.streamKey,'synthetic-private-key');assert.equal(JSON.stringify(f.encoder.status()).includes('synthetic-private-key'),false);
  f.message({event:'active',packets:1,videoFrames:1,streamKey:'synthetic-private-key'});assert.equal(f.encoder.status().state,'active');assert.equal(f.encoder.status().platformVerified,false);
  const stopping=f.encoder.stop();f.message({event:'stopped',packets:1});f.child.emit('close',0);assert.equal((await stopping).state,'stopped');
});
test('binary frames are copied, timestamped and bounded under backpressure',async()=>{
  const f=fixture({block:true}),started=f.encoder.start(config);f.pending.shift()();f.message({event:'ready',codec:'libx264'});await started;
  const frame=Buffer.alloc(64*64*4,5);assert.equal(f.encoder.sendVideo(frame,1000),true);frame.fill(9);assert.equal(f.writes[1][13],5);
  assert.equal(f.writes[1].readUInt32LE(1),frame.length);assert.equal(Number(f.writes[1].readBigUInt64LE(5)),1000);
  assert.equal(f.encoder.sendVideo(frame,1000),false);assert.equal(f.encoder.sendAudio(Buffer.alloc(7),2000),false);
  let accepted=0;for(let n=2;n<100;n++)accepted+=Number(f.encoder.sendVideo(frame,n*1000));assert.ok(accepted<30);assert.ok(f.encoder.status().droppedVideoFrames>0);
  assert.ok(f.encoder.status().queuedBytes<=2*(frame.length+13)+384000);f.child.emit('close',1);
});
test('untrusted worker errors cannot leak and only owned worker is killed',async()=>{
  const f=fixture();const result=f.encoder.start(config);f.message({event:'error',code:'rtmps://private/secret'});await assert.rejects(result,{message:'encoder_failed'});assert.equal(f.child.killed,true);assert.equal(JSON.stringify(f.encoder.status()).includes('private'),false);
});
test('rejects duplicate starts and stop is repeatable after close',async()=>{
  const f=fixture(),start=f.encoder.start(config);f.message({event:'ready',codec:'libx264'});await start;await assert.rejects(f.encoder.start(config),{message:'encoder_already_running'});
  const one=f.encoder.stop(),two=f.encoder.stop();assert.equal(one,two);assert.equal(f.encoder.sendVideo(Buffer.alloc(64*64*4),0),false);f.message({event:'stopped'});f.child.emit('close',0);await one;assert.equal((await f.encoder.stop()).running,false);
});
test('packet framing is deterministic',()=>{const p=packet('A',Buffer.from([1,2,3,4,5,6,7,8]),123);assert.equal(p.length,21);assert.equal(p[0],65);assert.equal(Number(p.readBigUInt64LE(5)),123);});
test('missing startup receipt and stalled stop are bounded',async()=>{
  const first=fixture({startTimeoutMs:20});await assert.rejects(withinTestDeadline(first.encoder.start(config)),{message:'encoder_start_timeout'});assert.equal(first.child.killed,true);
  const second=fixture({stopTimeoutMs:20}),starting=second.encoder.start(config);second.message({event:'ready',codec:'libx264'});await starting;const stopped=await withinTestDeadline(second.encoder.stop());assert.equal(second.child.killed,true);assert.equal(stopped.state,'failed');assert.equal(stopped.running,false);
});
test('test transport is constructor-only and refuses destination credentials',async()=>{
  const ordinary=fixture();await assert.rejects(ordinary.encoder.start({...config,testTransport:{port:443}}),{message:'invalid_test_transport'});
  const fixtureTransport=fixture({testTransport:{port:19000,caFile:path.resolve('F:/Temp/encoder-test/ca.pem'),serverName:'localhost'}});
  await assert.rejects(fixtureTransport.encoder.start(config),{message:'invalid_test_transport'});
  assert.throws(()=>fixture({testTransport:{port:19000,caFile:path.resolve('F:/Temp/encoder-test/ca.pem'),serverName:'public.provider.com'}}),{message:'invalid_test_transport'});
});
