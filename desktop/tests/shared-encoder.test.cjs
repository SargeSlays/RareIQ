'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs/promises'),{EventEmitter}=require('node:events'),{Writable,PassThrough}=require('node:stream'),{randomBytes,createCipheriv,createDecipheriv}=require('node:crypto');
const {SharedEncoderGroup}=require('../shared-encoder.cjs');
const root=path.resolve('F:/Temp/jonat/shared-encoder-tests');
const target=(id,extra={})=>({id,testOutput:path.join(root,id+'.flv'),...extra});
const config=extra=>({width:64,height:64,fps:30,bitrate:4000000,codec:'libx264',twitchVod:false,targets:[target('one'),target('two')],...extra});
function child({block=false,closeOnKill=true}={}){const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.writes=[];child.pending=[];child.kills=0;child.stdin=new Writable({write(chunk,_encoding,done){child.writes.push(Buffer.from(chunk));if(block)child.pending.push(done);else done();}});child.kill=()=>{child.kills++;if(closeOnKill)setImmediate(()=>child.emit('close',1));};return child;}
function fixture(options={}){const children=[],launches=[],observed=[];const group=new SharedEncoderGroup({python:path.resolve('synthetic-python.exe'),workerPath:path.resolve('shared_encoder_worker.py'),artifactRoot:root,startTimeoutMs:1000,stopTimeoutMs:40,killGraceMs:30,onState:state=>observed.push(state),...options,spawnProcess:(exe,args,settings)=>{const created=child(options);children.push(created);launches.push({exe,args,settings});return created;}});return {group,children,launches,observed,get child(){return children.at(-1);},message(value,index=children.length-1){children[index].stdout.write(JSON.stringify(value)+'\n');}};}
async function deadline(promise){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('test_deadline')),2000);})]);}finally{clearTimeout(timer);}}
async function ready(f,value=config()){const started=f.group.start(value);for(const entry of value.targets)f.message({event:'ready',targetId:entry.id});f.message({event:'ready',codec:'libx264',videoEncoderInstances:1,targetMuxerCount:value.targets.length});await started;}
async function close(f){const stopped=f.group.stop();f.message({event:'stopped'});f.child.emit('close',0);return stopped;}

test('one process owns multiple public target facades and keeps credentials off arguments and status',async()=>{
  const f=fixture(),one=f.group.createTarget('one'),two=f.group.createTarget('two');await ready(f,config({targets:[{id:'one',destination:{serverUrl:'rtmps://ingest.provider.com/live',streamKey:'synthetic-private-key',platform:'youtube',name:'private-display-name',networkVerified:false}},target('two')]}));assert.equal(f.launches.length,1);assert.equal(one.status().running,true);assert.equal(two.status().running,true);assert.equal(f.group.status().videoEncoderInstances,1);assert.equal(f.group.status().targetMuxerCount,2);assert.equal(f.group.status().targets.length,2);assert.ok(!JSON.stringify(f.launches).includes('synthetic-private-key'));assert.ok(!JSON.stringify(f.group.status()).includes('private'));assert.equal(JSON.parse(f.child.writes[0].toString()).targets[0].destination.streamKey,'synthetic-private-key');await close(f);assert.equal(f.group.status().running,false);assert.equal(one.status().running,false);
});

test('target stop sends one bounded T command, is idempotent, and awaits only that mux receipt',async()=>{
  const f=fixture(),one=f.group.createTarget('one'),two=f.group.createTarget('two');await ready(f);const stopping=one.stop();assert.equal(one.stop(),stopping);assert.equal(one.status().running,true);const control=f.child.writes.at(-1);assert.equal(control[0],84);assert.equal(Number(control.readBigUInt64LE(5)),0);assert.deepEqual(JSON.parse(control.subarray(13).toString()),{id:'one'});f.message({event:'stopped',targetId:'one',packets:7});assert.equal((await stopping).running,false);assert.equal(two.status().running,true);assert.equal(f.group.status().running,true);assert.equal(f.child.kills,0);await close(f);
});

test('target failure is redacted and remains running until its stopped receipt without killing peers',async()=>{
  const f=fixture(),states=[],one=f.group.createTarget('one',state=>states.push(state)),two=f.group.createTarget('two');await ready(f);f.message({event:'error',targetId:'one',code:'rtmps://private/secret',streamKey:'secret'});assert.equal(one.status().state,'failed');assert.equal(one.status().code,'encoder_failed');assert.equal(one.status().running,true);assert.equal(f.group.status().state,'starting');const stopped=one.stop();f.message({event:'stopped',targetId:'one',code:'encoder_failed'});assert.equal((await stopped).running,false);assert.equal(one.status().code,'encoder_failed');assert.equal(two.status().running,true);assert.ok(!JSON.stringify(states).includes('secret'));assert.equal(f.child.kills,0);await close(f);
});

test('target stop timeout retains truthful running ownership and never kills the shared child',async()=>{
  const f=fixture({stopTimeoutMs:15}),one=f.group.createTarget('one'),two=f.group.createTarget('two');await ready(f);const status=await deadline(one.stop());assert.equal(status.code,'encoder_stop_timeout');assert.equal(status.running,true);assert.equal(two.status().running,true);assert.equal(f.child.kills,0);f.message({event:'stopped',targetId:'one'});assert.equal(one.status().running,false);await close(f);
});

test('global Stop drains E and keeps process ownership until actual child close',async()=>{
  const f=fixture(),one=f.group.createTarget('one');await ready(f);let settled=false;const stopping=f.group.stop().then(value=>{settled=true;return value;});assert.equal(f.child.writes.at(-1)[0],69);f.message({event:'stopped'});await Promise.resolve();assert.equal(one.status().running,false);assert.equal(f.group.status().running,true);assert.equal(settled,false);f.child.emit('close',0);assert.equal((await stopping).running,false);
});

test('global Stop timeout only kills its owned process and keeps unconfirmed shutdown running',async()=>{
  const f=fixture({closeOnKill:false,stopTimeoutMs:15,killGraceMs:15});await ready(f);const stopped=await deadline(f.group.stop());assert.equal(f.child.kills,1);assert.equal(stopped.running,true);assert.equal(stopped.code,'encoder_stop_timeout');f.child.emit('close',1);assert.equal(f.group.status().running,false);
});

test('raw frames/audio are copied and sent once with bounded backpressure and independent VOD timestamps',async()=>{
  const f=fixture({block:true}),started=f.group.start(config({twitchVod:true,targets:[target('one',{twitchVod:true}),target('two')]}));f.child.pending.shift()();f.message({event:'ready'});await started;const frame=Buffer.alloc(64*64*4,7);assert.equal(f.group.sendVideo(frame,0),true);frame.fill(9);assert.equal(f.child.writes[1][13],7);assert.equal(f.group.sendVideo(frame,0),false);assert.equal(f.group.sendAudio(Buffer.alloc(7),0),false);assert.equal(f.group.sendAudio(Buffer.alloc(8),0),true);assert.equal(f.group.sendVodAudio(Buffer.alloc(8),0),true);assert.equal(f.group.sendVodAudio(Buffer.alloc(8),0),false);let accepted=0;for(let i=1;i<100;i++)accepted+=Number(f.group.sendVideo(frame,i));assert.ok(accepted>0&&accepted<100);assert.ok(f.group.status().droppedVideoFrames>0);assert.ok(f.group.status().queuedBytes<=2*(frame.length+13)+768000);f.child.emit('close',1);
});

test('shared settings, IDs, target bounds, unknown fields and test escapes are rejected before spawn',async()=>{
  const f=fixture();for(const value of [config({secret:'never-accept'}),config({targets:[]}),config({targets:Array.from({length:9},(_,i)=>target('t'+i))}),config({targets:[target('same'),target('same')]}),config({targets:[target('bad id')]}),config({targets:[target('one',{testTransport:{port:12345}})]}),config({targets:[target('one',{testOutput:path.resolve(root,'../outside.flv')})]}),config({fps:null}),config({twitchVod:true}),config({targets:[{id:'one',destination:{serverUrl:'rtmps://ingest.provider.com/app',streamKey:'synthetic',platform:'youtube'},twitchVod:true}],twitchVod:true})])await assert.rejects(f.group.start(value));assert.equal(f.children.length,0);assert.throws(()=>f.group.createTarget('bad id'));f.group.createTarget('one');assert.throws(()=>f.group.createTarget('one'));
});

test('TLS synthetic transports are constructor-only, bounded and cannot fall through to real destinations',async()=>{
  const seam={port:19000,caFile:path.join(root,'ca.pem'),serverName:'localhost'},f=fixture({testTransports:{one:seam}});await assert.rejects(f.group.start(config()),{message:'invalid_test_transport'});await assert.rejects(f.group.start(config({targets:[{id:'one',destination:{serverUrl:'rtmps://ingest.provider.com/app',streamKey:'synthetic'}}]})),{message:'invalid_test_transport'});const started=f.group.start(config({targets:[{id:'one'}]}));f.message({event:'ready'});await started;assert.deepEqual(JSON.parse(f.child.writes[0].toString()).targets[0].testTransport,seam);await close(f);assert.throws(()=>fixture({testTransports:{one:{...seam,serverName:'public.provider.com'}}}),{message:'invalid_test_transport'});
});

test('unknown target events and malformed stdout fail the group without exposing raw content',async()=>{
  for(const emit of [f=>f.message({event:'stats',targetId:'foreign',secret:'private'}),f=>f.child.stdout.write('private-invalid-json\n')]){const f=fixture();await ready(f);emit(f);assert.equal(f.group.status().state,'failed');assert.equal(f.group.status().code,'encoder_protocol_failed');assert.ok(!JSON.stringify(f.group.status()).includes('private'));await new Promise(resolve=>setImmediate(resolve));assert.equal(f.group.status().running,false);}
});

test('global safe failure codes notify the owner and keep all platform verification false',async()=>{
  const f=fixture(),one=f.group.createTarget('one');await ready(f);f.message({event:'stats',videoFrames:8,videoEncoderInstances:1,targetMuxerCount:2,platformVerified:true,platformLiveVerified:true,vodPlatformVerified:true,secret:'hidden'});f.message({event:'stats',targetId:'one',videoFrames:8,platformLiveVerified:true});assert.equal(f.group.status().platformLiveVerified,false);assert.equal(one.status().platformLiveVerified,false);f.message({event:'error',code:'shared_mux_unavailable'});assert.equal(f.observed.at(-1).code,'shared_mux_unavailable');await new Promise(resolve=>setImmediate(resolve));assert.equal(f.group.status().running,false);
});

test('late events from an old process cannot overwrite a new run or stop its child',async()=>{
  const f=fixture();await ready(f);await close(f);await ready(f);f.message({event:'error',code:'encoder_failed'},0);f.children[0].emit('close',1);assert.equal(f.group.status().running,true);assert.equal(f.child.kills,0);assert.equal(f.group.status().state,'starting');await close(f);
});

test('startup timeout is bounded and cancellation prevents late ready from changing terminal state',async()=>{
  const f=fixture({startTimeoutMs:15});await assert.rejects(deadline(f.group.start(config())),{message:'encoder_start_timeout'});await new Promise(resolve=>setImmediate(resolve));assert.equal(f.group.status().running,false);const other=fixture(),starting=other.group.start(config()),stopping=other.group.stop();other.message({event:'ready'});other.message({event:'stopped'});other.child.emit('close',0);await starting;assert.equal((await stopping).running,false);assert.equal(other.group.status().state,'stopped');
});

test('real DestinationStore private records bind their saved id and strip metadata before worker stdin',async t=>{
  await fs.mkdir(root,{recursive:true});const directory=await fs.mkdtemp(path.join(root,'destination-'));t.after(async()=>{assert.equal(path.dirname(path.resolve(directory)),root);await fs.rm(directory,{recursive:true,force:true});});const key=randomBytes(32),cipher={isAsyncEncryptionAvailable:async()=>true,encryptStringAsync:async value=>{const iv=randomBytes(12),encoder=createCipheriv('aes-256-gcm',key,iv);const bytes=Buffer.concat([encoder.update(value,'utf8'),encoder.final()]);return Buffer.concat([iv,encoder.getAuthTag(),bytes]);},decryptStringAsync:async value=>{const decoder=createDecipheriv('aes-256-gcm',key,value.subarray(0,12));decoder.setAuthTag(value.subarray(12,28));return {result:Buffer.concat([decoder.update(value.subarray(28)),decoder.final()]).toString('utf8'),shouldReEncrypt:false};}};
  const {DestinationStore}=require('../destinations.cjs'),store=new DestinationStore({directory,cipher,platform:'win32'}),saved=await store.save({name:'Synthetic channel',platform:'twitch',streamKey:'synthetic-store-key',requestId:'store-save'}),destination=await store.getPrivateDestination(saved.destination.id);assert.equal(destination.id,saved.destination.id);const f=fixture();await ready(f,config({targets:[{id:destination.id,destination}]}));const sent=JSON.parse(f.child.writes[0].toString()).targets[0].destination;assert.equal(sent.streamKey,'synthetic-store-key');for(const name of ['id','name','allowInsecureRtmp','networkVerified'])assert.equal(Object.hasOwn(sent,name),false);await close(f);
  const other=fixture();await assert.rejects(other.group.start(config({targets:[{id:'00000000-0000-0000-0000-000000000000',destination}]})),{message:'invalid_destination'});assert.equal(other.children.length,0);
});

const rehearsal=(extra={})=>config({rehearsal:true,targets:[{id:'rehearsal-local',rehearsal:true,twitchVod:false}],...extra});

test('rehearsal is an exclusive local target, normalized on stdin and truthful throughout Stop',async()=>{
  const f=fixture({artifactRoot:undefined}),target=f.group.createTarget('rehearsal-local');
  await ready(f,rehearsal({twitchVod:true,targets:[{id:'rehearsal-local',rehearsal:true,twitchVod:true}]}));
  const sent=JSON.parse(f.child.writes[0].toString());assert.equal(sent.rehearsal,true);assert.deepEqual(sent.targets,[{id:'rehearsal-local',twitchVod:true,rehearsal:true}]);assert.equal(Object.hasOwn(sent,'artifactRoot'),false);
  f.message({event:'stats',videoFrames:3,packets:9,bytesMuxed:100,bytesDiscarded:200,tlsVerified:true,networkVerified:true,twitchVodWireVerified:true,platformVerified:true});
  f.message({event:'stats',targetId:'rehearsal-local',bytesDiscarded:200,tlsVerified:true,twitchVodWireVerified:true});
  for(const status of [f.group.status(),target.status()]){assert.equal(status.rehearsal,true);assert.equal(status.localDiscard,true);assert.equal(status.bytesDiscarded,200);for(const key of ['networkVerified','tlsVerified','twitchVodWireVerified','platformVerified','platformLiveVerified','vodPlatformVerified'])assert.equal(status[key],false);}
  assert.equal(f.group.sendVideo(Buffer.alloc(64*64*4),0),true);assert.equal(f.group.sendAudio(Buffer.alloc(8),0),true);assert.equal(f.group.sendVodAudio(Buffer.alloc(8),0),true);
  const stopping=target.stop();assert.equal(target.stop(),stopping);f.message({event:'stopped',targetId:'rehearsal-local',bytesDiscarded:240});assert.equal((await stopping).running,false);assert.equal(f.group.status().running,true);assert.equal(f.child.kills,0);
  await close(f);assert.equal(f.group.status().running,false);
});

test('rehearsal rejects every publishing and artifact combination before spawn',async()=>{
  const f=fixture({artifactRoot:undefined}),local=rehearsal().targets[0];
  const mutations=[...['destination','testOutput','testTransport','serverUrl','streamKey','artifactRoot','transport','networkVerified'].map(key=>rehearsal({targets:[{...local,[key]:null}]})),...['destination','testOutput','testTransport','artifactRoot','serverUrl','streamKey'].map(key=>rehearsal({[key]:null})),rehearsal({targets:[local,target('other')]}),rehearsal({targets:[{...local,id:'other'}]}),rehearsal({targets:[{id:'rehearsal-local'}]}),rehearsal({twitchVod:true}),config({targets:[local]}),config({targets:[{...target('one'),rehearsal:false}]})];
  for(const flag of [false,null,1,0,'true',{},[]]){mutations.push(rehearsal({rehearsal:flag}),rehearsal({targets:[{...local,rehearsal:flag}]}));}
  for(const value of mutations)await assert.rejects(f.group.start(value),{message:'invalid_encoder_config'});
  assert.equal(f.children.length,0);
  for(const options of [{},{testTransports:{'rehearsal-local':{port:19000,caFile:path.join(root,'ca.pem'),serverName:'localhost'}}}]){const withArtifacts=fixture(options);await assert.rejects(withArtifacts.group.start(rehearsal()),{message:'invalid_encoder_config'});assert.equal(withArtifacts.children.length,0);}
});

test('rehearsal rejects unsafe counters and retains process ownership after failed shutdown',async()=>{
  const f=fixture({artifactRoot:undefined,closeOnKill:false,stopTimeoutMs:15,killGraceMs:15});await ready(f,rehearsal());
  for(const bytesDiscarded of [-1,Infinity,Number.MAX_SAFE_INTEGER+1,'8'])f.message({event:'stats',bytesDiscarded});
  assert.equal(f.group.status().bytesDiscarded,undefined);f.message({event:'stats',bytesDiscarded:8});assert.equal(f.group.status().bytesDiscarded,8);
  const stopped=await deadline(f.group.stop());assert.equal(stopped.running,true);assert.equal(stopped.code,'encoder_stop_timeout');assert.equal(stopped.localDiscard,true);f.child.emit('close',1);assert.equal(f.group.status().running,false);
});

test('recording path is constructor-only and exclusive from network, rehearsal and synthetic targets',async()=>{
  const recordingFile={path:path.join(root,'new.mkv'),minimumFreeBytes:268435456},f=fixture({artifactRoot:undefined,recordingFile});
  const value=config({targets:[{id:'recording-local',recording:true,twitchVod:false}]});await ready(f,value);const sent=JSON.parse(f.child.writes[0].toString());assert.deepEqual(sent.recordingFile,recordingFile);assert.deepEqual(sent.targets,value.targets);assert.equal(JSON.stringify(f.group.status()).includes('new.mkv'),false);
  f.message({event:'stats',recording:true,recordingBytes:12,recordingFinalized:false});assert.equal(f.group.status().recordingBytes,12);await close(f);
  for(const targets of [[target('one')],[{id:'recording-local',recording:true,destination:{}}],[{id:'recording-local',recording:true,twitchVod:true}],[{id:'foreign',recording:true}]])await assert.rejects(f.group.start(config({targets})),/invalid_encoder_config/);
  const ordinary=fixture();await assert.rejects(ordinary.group.start(value),/invalid_encoder_config/);await assert.rejects(ordinary.group.start(config({recordingFile})),/invalid_encoder_config/);assert.throws(()=>fixture({recordingFile}),/invalid_recording_file/);
});
