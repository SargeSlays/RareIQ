'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),fsp=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {createReplayPlayback,convertReplay,MAX_INPUT,MAX_ASSET}=require('../replay-playback.cjs');
const assetId='12345678-1234-1234-1234-123456789abc',source='video:'+assetId;
const switcher=()=>({ok:true,generation:5,preview_revision:9,program_composition_id:'a'.repeat(64)});
const staged=()=>({...switcher(),preview_revision:10,preview_sources:[source]});
const defer=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
function fixture(overrides={}){
  const calls=[],saved={path:path.resolve('synthetic-clip.mkv'),finalized:true,savedBytes:123,receipt:{}};
  const f={calls,saved,requests:[],uploads:[],conversions:[],confirmations:[],imported:[]};
  const playback=createReplayPlayback({getSaved:()=>f.saved,ffmpeg:path.resolve('synthetic-ffmpeg.exe'),cacheRoot:path.resolve('synthetic-cache'),
    request:async(endpoint,body)=>{calls.push(['request',endpoint]);f.requests.push({endpoint,body});return endpoint.endsWith('/preview')?staged():switcher();},
    upload:async(body,details)=>{calls.push(['upload']);f.uploads.push({body,details});return {ok:true,created:true,asset:{id:assetId,kind:'video'}};},
    convert:async(details)=>{calls.push(['convert']);f.conversions.push(details);return Buffer.from('generated MP4');},
    confirm:async(details)=>{calls.push(['confirm']);f.confirmations.push(details);return true;},onImported:id=>f.imported.push(id),...overrides});
  return {...f,playback};
}
test('stage imports only a finalized native receipt then CAS-stages Preview without taking Program',async()=>{
  const f=fixture();assert.equal(f.playback.status().canPreview,true);
  assert.deepEqual(await f.playback.stage({requestId:'review-1'}),{source});
  assert.deepEqual(f.requests,[{endpoint:'/api/production/switcher',body:undefined},{endpoint:'/api/production/switcher/preview',body:{preview_sources:[source],layout:'auto',expected_generation:5,expected_preview_revision:9}}]);
  assert.deepEqual(f.confirmations,[{fileName:'synthetic-clip.mkv'}]);
  assert.equal(f.uploads.length,1);assert.equal(f.conversions[0].source,f.saved.path);assert.equal(f.conversions[0].expectedBytes,123);
  assert.equal(f.playback.status().lastPreviewSource,source);assert.deepEqual(f.imported,[source]);
  assert.equal(JSON.stringify(f.playback.status()).includes(f.saved.path),false);
  assert.equal(f.requests.some(item=>/take|program/.test(item.endpoint)),false);
});
test('exact duplicate stage request shares one confirmation/import/CAS and concurrent new action is busy',async()=>{
  const pending=defer();const f=fixture({confirm:()=>pending.promise});
  const first=f.playback.stage({requestId:'same'}),again=f.playback.stage({requestId:'same'});assert.equal(first,again);
  await assert.rejects(f.playback.stage({requestId:'other'}),{code:'replay_busy'});pending.resolve(true);await first;
  assert.equal(f.uploads.length,1);assert.equal(f.requests.length,2);assert.equal(await f.playback.stage({requestId:'same'}),await first);
});
test('malformed renderer payloads cannot supply paths, sources, Take or control characters',async()=>{
  const f=fixture();for(const value of [null,{},[],{requestId:''},{requestId:'x'.repeat(81)},{requestId:'bad\n'},{requestId:'ok',path:f.saved.path},{requestId:'ok',source},{requestId:'ok',action:'take'}])await assert.rejects(f.playback.stage(value),{code:'invalid_replay_request'});
  assert.equal(f.requests.length,0);assert.equal(f.conversions.length,0);
});
test('current context must survive switcher read and confirmation before conversion/upload',async()=>{
  let current=true;const gate=defer(),f=fixture({confirm:()=>gate.promise});const pending=f.playback.stage({requestId:'closing'},{current:()=>current});
  await new Promise(resolve=>setImmediate(resolve));current=false;gate.resolve(true);await assert.rejects(pending,{code:'replay_cancelled'});
  assert.equal(f.conversions.length,0);assert.equal(f.uploads.length,0);assert.equal(f.requests.length,1);assert.equal(f.playback.status().importing,false);
  const late=fixture({request:async()=>{current=false;return switcher();}});current=true;
  await assert.rejects(late.playback.stage({requestId:'late'},{current:()=>current}),{code:'replay_cancelled'});assert.equal(late.confirmations.length,0);
});
test('cancelled confirmation never reads media or stages any output',async()=>{
  const f=fixture({confirm:async()=>false});assert.deepEqual(await f.playback.stage({requestId:'cancel'}),{cancelled:true});
  assert.equal(f.conversions.length,0);assert.equal(f.uploads.length,0);assert.equal(f.requests.length,1);assert.equal(f.playback.status().lastPreviewSource,null);
});
test('missing/unfinalized receipts and malformed revision state fail before importing',async()=>{
  for(const saved of [null,{path:path.resolve('clip.mkv'),finalized:false}]){const f=fixture({getSaved:()=>saved});await assert.rejects(f.playback.stage({requestId:'missing'}),{code:'replay_not_saved'});assert.equal(f.requests.length,0);}
  for(const state of [{generation:-1,preview_revision:0},{generation:0,preview_revision:-1},{generation:1.5,preview_revision:0},{generation:0,preview_revision:'1'},{}]){
    const f=fixture({request:async()=>({ok:true,...state})});await assert.rejects(f.playback.stage({requestId:'bad-state'}),{code:'replay_preview_unconfirmed'});assert.equal(f.conversions.length,0);
  }
});
test('CAS failure leaves Program and last Preview status unchanged without retrying the mutation',async()=>{
  const f=fixture({request:async(endpoint)=>endpoint.endsWith('/preview')?{ok:false,reason:'preview_revision_conflict'}:switcher()});
  await assert.rejects(f.playback.stage({requestId:'conflict'}),{code:'replay_preview_unconfirmed'});assert.equal(f.playback.status().lastPreviewSource,null);assert.equal(f.playback.status().importing,false);
  assert.equal(f.uploads.length,1);assert.equal(f.conversions.length,1);
});
test('unconfirmed Preview response cannot claim a different source, generation or Program composition',async()=>{
  for(const response of [null,{ok:true},{...staged(),generation:6},{...staged(),preview_revision:9},{...staged(),preview_sources:[]},{...staged(),program_composition_id:'b'.repeat(64)}]){
    const f=fixture({request:async endpoint=>endpoint.endsWith('/preview')?response:switcher()});
    await assert.rejects(f.playback.stage({requestId:'bad-preview'}),{code:'replay_preview_unconfirmed'});assert.equal(f.playback.status().lastPreviewSource,null);
  }
});
test('closing the initiating context during conversion or upload prevents Preview mutation',async()=>{
  for(const phase of ['convert','upload']){
    let current=true;const pending=defer();
    const f=fixture(phase==='convert'?{convert:()=>pending.promise}:{upload:()=>pending.promise});
    const operation=f.playback.stage({requestId:'close-'+phase},{current:()=>current});
    await new Promise(resolve=>setImmediate(resolve));current=false;
    pending.resolve(phase==='convert'?Buffer.from('generated MP4'):{ok:true,created:true,asset:{id:assetId,kind:'video'}});
    await assert.rejects(operation,{code:'replay_cancelled'});assert.equal(f.requests.length,1);assert.equal(f.playback.status().lastPreviewSource,null);
  }
});
test('malformed or mismatched upload receipts never stage Preview',async()=>{
  for(const receipt of [null,{ok:false},{ok:true,created:false,asset:{id:assetId,kind:'video'}},{ok:true,created:true,asset:{id:assetId,kind:'image'}},{ok:true,created:true,asset:{id:'https://outside.invalid/',kind:'video'}},{ok:true,created:true,asset:{id:'<script>',kind:'video'}}]){
    const f=fixture({upload:async()=>receipt});await assert.rejects(f.playback.stage({requestId:'bad-upload'}),{code:'replay_import_unconfirmed'});
    assert.equal(f.requests.length,1);assert.equal(f.playback.status().lastPreviewSource,null);
  }
});
test('same finalized clip reuses its durable import while a different receipt at the same path imports separately',async()=>{
  const f=fixture();await f.playback.stage({requestId:'first'});await f.playback.stage({requestId:'second'});assert.equal(f.uploads.length,1);
  f.saved.receipt={};await f.playback.stage({requestId:'third'});assert.equal(f.uploads.length,2);assert.equal(f.conversions.length,2);
  assert.notEqual(f.uploads[0].details.requestId,f.uploads[1].details.requestId);
});
let ffmpeg=null;try{ffmpeg=execFileSync(process.platform==='win32'?'where.exe':'which',['ffmpeg'],{encoding:'utf8',windowsHide:true}).split(/\r?\n/).find(value=>value&&path.isAbsolute(value))||null;}catch(_){}
test('actual generated H264/AAC MKV remux becomes a decodable MP4 and preserves the source',{skip:!ffmpeg},async()=>{
  const base=process.env.PRODUCER_REPLAY_ACCEPTANCE_ROOT||(process.platform==='win32'&&fs.existsSync('F:/')?'F:/Temp/jonat/ProducerPlease-replay-playback-20261119':path.join(os.tmpdir(),'ProducerPlease-replay-playback'));
  await fsp.mkdir(base,{recursive:true});const evidence=await fsp.mkdtemp(path.join(base,'native-')),input=path.join(evidence,'generated.mkv'),output=path.join(evidence,'decoded.mp4'),cacheRoot=path.join(evidence,'private-cache');
  execFileSync(ffmpeg,['-nostdin','-hide_banner','-loglevel','error','-n','-f','lavfi','-i','testsrc2=size=320x180:rate=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',input],{windowsHide:true,timeout:30000});
  const before=await fsp.readFile(input),expectedBytes=before.length;
  const body=await convertReplay({source:input,expectedBytes,cacheRoot,ffmpeg});assert.ok(body.length>12&&body.length<=MAX_ASSET);assert.equal(body.subarray(4,8).toString(),'ftyp');
  await fsp.writeFile(output,body,{flag:'wx'});
  execFileSync(ffmpeg,['-nostdin','-hide_banner','-loglevel','error','-i',output,'-map','0:v:0','-map','0:a:0','-f','null','-'],{windowsHide:true,timeout:30000});
  assert.deepEqual(await fsp.readFile(input),before);assert.deepEqual(await fsp.readdir(cacheRoot),[]);
  await assert.rejects(convertReplay({source:input,expectedBytes:expectedBytes+1,cacheRoot,ffmpeg}),{code:'replay_file_changed'});
  assert.equal(MAX_INPUT,128*1024*1024);assert.equal(MAX_ASSET,64*1024*1024);
  await fsp.writeFile(path.join(evidence,'results.json'),JSON.stringify({passed:true,generatedMediaOnly:true,hardware:false,broadcast:false,inputBytes:before.length,outputBytes:body.length,sourceSha256:crypto.createHash('sha256').update(before).digest('hex'),sourcePreserved:true,decodedH264AndAac:true,privateCacheEmpty:true},null,2));
});
