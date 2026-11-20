'use strict';
// Main owns the finalized path. The renderer can request a reviewed Preview, never a path or Take.
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
const runFile=promisify(execFile),MAX_INPUT=128*1024*1024,MAX_ASSET=64*1024*1024;
const fail=code=>Object.assign(Error(code),{code});
async function privateFile(value){
  if(typeof value!=='string'||!path.isAbsolute(value)||path.extname(value).toLowerCase()!=='.mkv')throw fail('replay_not_saved');
  let current=path.resolve(value);
  while(true){const info=await fs.lstat(current);if(info.isSymbolicLink()||path.resolve(await fs.realpath(current)).toLowerCase()!==current.toLowerCase())throw fail('replay_import_unavailable');const parent=path.dirname(current);if(parent===current)break;current=parent;}
  const info=await fs.stat(value);if(!info.isFile()||!info.size||info.size>MAX_INPUT)throw fail('replay_import_too_large');
  return info;
}
async function convertReplay({source,expectedBytes,cacheRoot,ffmpeg,run=runFile,current=()=>true}){
  if(typeof ffmpeg!=='string'||!path.isAbsolute(ffmpeg)||!path.isAbsolute(cacheRoot))throw fail('replay_conversion_unavailable');
  const before=await privateFile(source);if(before.size!==expectedBytes)throw fail('replay_file_changed');
  await fs.mkdir(cacheRoot,{recursive:true,mode:0o700});const realRoot=await fs.realpath(cacheRoot);
  if(path.resolve(realRoot).toLowerCase()!==path.resolve(cacheRoot).toLowerCase())throw fail('replay_import_unavailable');
  const space=await fs.statfs(realRoot);if(Number(space.bavail)*Number(space.bsize)<512*1024*1024)throw fail('insufficient_recording_space');
  const directory=await fs.mkdtemp(path.join(realRoot,'clip-')),input=path.join(directory,'input.mkv'),output=path.join(directory,'clip.mp4');
  let handle;
  try{
    if(!current())throw fail('replay_cancelled');
    handle=await fs.open(source,'r');const opened=await handle.stat();
    if(opened.ino!==before.ino||opened.dev!==before.dev||opened.size!==before.size||opened.mtimeMs!==before.mtimeMs)throw fail('replay_file_changed');
    // Read only the reviewed, bounded finalized file through its open handle.
    const bytes=Buffer.alloc(before.size);let offset=0;
    while(offset<bytes.length){const next=await handle.read(bytes,offset,Math.min(1024*1024,bytes.length-offset),offset);if(!next.bytesRead)throw fail('replay_file_changed');offset+=next.bytesRead;}
    const after=await handle.stat();
    if(after.size!==before.size||after.mtimeMs!==before.mtimeMs)throw fail('replay_file_changed');
    await privateFile(source);await fs.writeFile(input,bytes,{flag:'wx',mode:0o600});await handle.close();handle=null;
    if(!current())throw fail('replay_cancelled');
    await run(ffmpeg,['-nostdin','-hide_banner','-loglevel','error','-n','-protocol_whitelist','file,pipe','-i',input,'-map','0:v:0','-map','0:a:0?','-c','copy','-t','65','-fs',String(MAX_INPUT+MAX_ASSET),'-movflags','+faststart',output],{windowsHide:true,timeout:120000,maxBuffer:256*1024});
    if(!current())throw fail('replay_cancelled');
    const info=await fs.stat(output);if(!info.size||info.size>MAX_ASSET)throw fail('replay_import_too_large');
    const body=await fs.readFile(output);if(body.length!==info.size||body.length<12||body.subarray(4,8).toString()!=='ftyp')throw fail('replay_conversion_failed');
    return body;
  }catch(error){
    if(typeof error?.code==='string'&&(error.code.startsWith('replay_')||error.code==='insufficient_recording_space'))throw error;
    throw fail('replay_conversion_failed');
  }finally{
    await handle?.close().catch(()=>{});
    // Only files created in this exact private temporary directory are retired.
    for(const file of [input,output])await fs.unlink(file).catch(()=>{});
    await fs.rmdir(directory).catch(()=>{});
  }
}
function createReplayPlayback({getSaved,request,upload,confirm,cacheRoot,ffmpeg,convert=convertReplay,onImported=()=>{}}){
  const receipts=new Map(),imports=new Map(),savedKeys=new WeakMap();let active=false,lastSource=null;
  const status=()=>({importing:active,lastPreviewSource:lastSource,canPreview:!active&&Boolean(getSaved()?.path)&&getSaved()?.finalized===true&&typeof ffmpeg==='string'});
  function stage(value,{current=()=>true}={}){
    if(!value||Object.keys(value).some(key=>key!=='requestId')||typeof value.requestId!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId))return Promise.reject(fail('invalid_replay_request'));
    if(receipts.has(value.requestId))return receipts.get(value.requestId);
    if(active)return Promise.reject(fail('replay_busy'));
    const saved=getSaved();if(!saved?.path||!saved.finalized)return Promise.reject(fail('replay_not_saved'));
    const guard=()=>{if(!current())throw fail('replay_cancelled');};active=true;
    const result=(async()=>{
      const state=await request('/api/production/switcher');guard();
      if(state?.ok!==true||!Number.isSafeInteger(state.generation)||state.generation<0||!Number.isSafeInteger(state.preview_revision)||state.preview_revision<0)throw fail('replay_preview_unconfirmed');
      if(!await confirm({fileName:path.basename(saved.path)}))return {cancelled:true};guard();
      if(!saved.receipt||typeof saved.receipt!=='object')throw fail('replay_preview_unconfirmed');
      if(!savedKeys.has(saved.receipt))savedKeys.set(saved.receipt,crypto.randomUUID());
      const fingerprint=crypto.createHash('sha256').update(saved.path+'\0'+saved.savedBytes+'\0'+savedKeys.get(saved.receipt)).digest('hex');
      let source=imports.get(fingerprint);
      if(!source){
        const body=await convert({source:saved.path,expectedBytes:saved.savedBytes,cacheRoot,ffmpeg,current});guard();
        const name=path.basename(saved.path,path.extname(saved.path)).replace(/[^A-Za-z0-9._-]/g,'_').slice(0,80)||'Replay';
        const response=await upload(body,{requestId:'replay-'+fingerprint,fileName:name+'.mp4'});guard();
        if(response?.ok!==true||response.created!==true||typeof response.asset?.id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(response.asset.id)||response.asset.kind!=='video')throw fail('replay_import_unconfirmed');
        source='video:'+response.asset.id;imports.set(fingerprint,source);if(imports.size>32)imports.delete(imports.keys().next().value);onImported(source);
      }
      guard();
      const staged=await request('/api/production/switcher/preview',{preview_sources:[source],layout:'auto',expected_generation:state.generation,expected_preview_revision:state.preview_revision});
      if(staged?.ok!==true||staged.generation!==state.generation||staged.preview_revision!==state.preview_revision+1||JSON.stringify(staged.preview_sources)!==JSON.stringify([source])||staged.program_composition_id!==state.program_composition_id)throw fail('replay_preview_unconfirmed');
      guard();lastSource=source;return {source};
    })().finally(()=>{active=false;});
    receipts.set(value.requestId,result);if(receipts.size>32)receipts.delete(receipts.keys().next().value);return result;
  }
  return {stage,status};
}
module.exports={convertReplay,createReplayPlayback,MAX_INPUT,MAX_ASSET};
