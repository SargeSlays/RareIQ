'use strict';
// Main-only: the renderer supplies a provider, never a filename or credentials.
const fs=require('node:fs/promises'),path=require('node:path');
const {studioOrigin}=require('./policy.cjs');
const MAX_BYTES=65536;
const plain=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const SAFE=new Set(['disconnect_before_app_setup','external_app_configuration_active','activity_history_unavailable','account_storage_unavailable','app_setup_unavailable','invalid_app_configuration','invalid_app_provider']);
function parseAppConfiguration(provider, raw){
  if(!['youtube','kick'].includes(provider)||typeof raw!=='string'||Buffer.byteLength(raw)>MAX_BYTES)throw Error('invalid_app_configuration');
  let parsed;try{parsed=JSON.parse(raw);}catch(_){throw Error('invalid_app_configuration');}
  if(!plain(parsed))throw Error('invalid_app_configuration');
  let value;
  if(provider==='youtube'){
    if(Object.keys(parsed).length!==1||!plain(parsed.installed))throw Error('invalid_app_configuration');
    value=parsed.installed;
    const allowed=new Set(['client_id','client_secret','project_id','auth_uri','token_uri','auth_provider_x509_cert_url','redirect_uris','universe_domain']);
    if(Object.keys(value).some(key=>!allowed.has(key))
      ||value.auth_uri!==undefined&&value.auth_uri!=='https://accounts.google.com/o/oauth2/auth'&&value.auth_uri!=='https://accounts.google.com/o/oauth2/v2/auth'
      ||value.token_uri!==undefined&&value.token_uri!=='https://oauth2.googleapis.com/token')throw Error('invalid_app_configuration');
  }else{
    if(Object.keys(parsed).some(key=>!['client_id','client_secret'].includes(key)))throw Error('invalid_app_configuration');
    value=parsed;
  }
  const id=provider==='youtube'?/^[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com$/:/^[A-Za-z0-9_-]{1,160}$/;
  if(typeof value.client_id!=='string'||!id.test(value.client_id)||typeof value.client_secret!=='string'||!value.client_secret||value.client_secret.length>4096||/[^\x21-\x7e]/.test(value.client_secret))throw Error('invalid_app_configuration');
  return {client_id:value.client_id,client_secret:value.client_secret};
}
function createAppSetupImporter({origin,trustedSender,chooseFile,fetchImpl=globalThis.fetch,fileSystem=fs}={}){
  const base=studioOrigin(origin);let pending=false;
  const trusted=e=>{try{return trustedSender(e)===true;}catch(_){return false;}};
  return async(e,platform)=>{
    if(!trusted(e))return {ok:false,reason:'local_operator_required'};
    if(typeof platform!=='string'||!['youtube','kick'].includes(platform))return {ok:false,reason:'invalid_app_provider'};
    if(pending)return {ok:false,reason:'app_setup_pending'};
    const frame=e.senderFrame,url=frame?.url,current=()=>trusted(e)&&e.senderFrame===frame&&frame?.url===url;
    let handle;pending=true;
    try{
      const selected=await chooseFile({platform:platform,defaultPath:'F:/Users/jonat/Downloads'});
      if(!current())return {ok:false,reason:'local_operator_required'};
      if(selected===null||selected===undefined)return {ok:true,cancelled:true,platform};
      if(typeof selected!=='string'||!path.isAbsolute(selected)||path.extname(selected).toLowerCase()!=='.json')return {ok:false,reason:'invalid_app_configuration'};
      handle=await fileSystem.open(selected,'r');const stat=await handle.stat();
      if(!stat.isFile()||stat.size>MAX_BYTES)throw Error('invalid_app_configuration');
      const bytes=Buffer.alloc(MAX_BYTES+1);let used=0;
      while(used<bytes.length){const read=await handle.read(bytes,used,bytes.length-used,null);if(!read.bytesRead)break;used+=read.bytesRead;}
      if(used>MAX_BYTES)throw Error('invalid_app_configuration');
      const config=parseAppConfiguration(platform,new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,used)));
      bytes.fill(0);await handle.close();handle=null;
      if(!current())return {ok:false,reason:'local_operator_required'};
      const endpoint=base+'/api/production/accounts/'+platform+'/configure-app';
      const r=await fetchImpl(endpoint,{method:'POST',redirect:'error',cache:'no-store',credentials:'omit',headers:{Origin:base,Accept:'application/json','Content-Type':'application/json'},body:JSON.stringify(config),signal:AbortSignal.timeout(10000)});
      if(!r||r.redirected||r.url!==endpoint||!r.body||r.headers?.get('content-type')?.split(';')[0].trim().toLowerCase()!=='application/json')throw Error('app_setup_unavailable');
      let size=0,parts=[];for await(const part of r.body){const bytes=Buffer.from(part);size+=bytes.length;if(size>4096)throw Error('app_setup_unavailable');parts.push(bytes);}
      const result=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(parts)));
      if(!plain(result)||r.status!==200||result.ok!==true)return {ok:false,reason:SAFE.has(result?.reason)?result.reason:'app_setup_unavailable'};
      if(!current())return {ok:false,reason:'local_operator_required'};
      return {ok:true,platform:platform,configured:result.configured===true,replayed:result.replayed===true,...(result.activity_history_warning===true?{activity_history_warning:true}:{})};
    }catch(error){return {ok:false,reason:SAFE.has(error?.message)?error.message:'app_setup_unavailable'};}
    finally{try{await handle?.close();}catch(_){}pending=false;}
  };
}
module.exports={createAppSetupImporter,parseAppConfiguration};
