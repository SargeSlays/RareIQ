'use strict';
// Main only: Kick's temporary ingest address and key stay on an owned pipe.
const path=require('node:path'),{spawn}=require('node:child_process');
const {validateServerUrl}=require('./destinations.cjs');
const SAFE=new Set(['account_unavailable','account_authorization_required','account_identity_mismatch','streaming_scope_required','secure_ingest_unavailable','authorization_refresh_required','provider_unavailable','streaming_not_available','account_storage_unavailable']);
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
function createKickResolver({runtime,spawnImpl=spawn}={}){
  return accountRef=>new Promise((resolve,reject)=>{
    const fail=code=>reject(Error(SAFE.has(code)?code:'account_authorization_required'));
    if(typeof accountRef!=='string'||!/^[a-f0-9]{64}$/.test(accountRef)||!runtime||typeof runtime.python!=='string'||!path.isAbsolute(runtime.python)||typeof runtime.projectRoot!=='string'||!path.isAbsolute(runtime.projectRoot))return fail('account_unavailable');
    const env={...process.env,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8'};
    let cwd=runtime.projectRoot;
    if(runtime.buildKind==='bundled-runtime'){
      if(typeof runtime.dataRoot!=='string'||!path.isAbsolute(runtime.dataRoot))return fail('account_unavailable');
      cwd=runtime.dataRoot;env.PRODUCER_DESKTOP='1';env.PRODUCER_DESKTOP_DATA_ROOT=runtime.dataRoot;
    }else delete env.PRODUCER_DESKTOP_DATA_ROOT;
    let child;try{child=spawnImpl(runtime.python,['-B',path.join(runtime.projectRoot,'tools','desktop_kick_account.py')],{cwd,env,windowsHide:true,stdio:['pipe','pipe','pipe']});}catch(_){return fail('account_unavailable');}
    let chunks=[],size=0,settled=false,killed=false,timer;
    const terminate=()=>{if(killed)return;killed=true;try{child.kill();}catch(_){} };
    const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);chunks=[];size=0;if(error){terminate();fail(error);}else resolve(value);};
    timer=setTimeout(()=>finish('provider_unavailable'),22000);
    try{
      child.stdout.on('data',chunk=>{if(settled)return;const bytes=Buffer.from(chunk);size+=bytes.length;if(size>16384)return finish('account_unavailable');chunks.push(bytes);});
      child.stderr.resume(); // Drain diagnostics without logging provider data or secrets.
      child.stderr.on('error',()=>finish('account_unavailable'));
      child.on('error',()=>finish('account_unavailable'));
      child.stdin.on('error',()=>finish('account_unavailable'));
      child.stdout.on('error',()=>finish('account_unavailable'));
      child.on('close',code=>{
        if(settled)return;
        try{
          const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
          if(code!==0||!plain(value)||value.ok!==true)return finish(SAFE.has(value?.reason)?value.reason:'account_authorization_required');
          if(Object.keys(value).some(key=>!['ok','platform','accountRef','serverUrl','streamKey'].includes(key))||value.platform!=='kick'||value.accountRef!==accountRef||typeof value.streamKey!=='string'||!value.streamKey||value.streamKey.length>4096||/[\s\x00-\x1f\x7f]/.test(value.streamKey))return finish('account_authorization_required');
          let serverUrl;try{serverUrl=validateServerUrl(value.serverUrl,{platform:'kick'});}catch(_){return finish('streaming_not_available');}
          finish(null,{platform:'kick',accountRef,serverUrl,streamKey:value.streamKey});
        }catch(_){finish('account_unavailable');}
      });
      child.stdin.end(JSON.stringify({accountRef}));
    }catch(_){finish('account_unavailable');}
  });
}
module.exports={createKickResolver};
