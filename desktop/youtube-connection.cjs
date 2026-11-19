'use strict';
// Main only: YouTube's exact selected ingest address and key stay on an owned pipe.
const path=require('node:path'),{spawn}=require('node:child_process');
const {validateServerUrl,normalizeYouTubeSelection}=require('./destinations.cjs');
const SAFE=new Set(['account_unavailable','account_authorization_required','account_identity_mismatch','streaming_scope_required','secure_ingest_unavailable','authorization_refresh_required','provider_unavailable','streaming_not_available','account_storage_unavailable','account_state_changed','broadcast_selection_changed','youtube_broadcast_unavailable','youtube_stream_shared','youtube_broadcast_not_owned','youtube_stream_unavailable','youtube_stream_not_owned','broadcast_selection_limit','provider_rate_limited','authorization_required','authorization_rejected','app_setup_required']);
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
function createYouTubeResolver({runtime,spawnImpl=spawn}={}){
  return (accountRef,youtubeSelection)=>new Promise((resolve,reject)=>{
    const fail=code=>reject(Error(SAFE.has(code)?code:'account_authorization_required'));
    if(typeof accountRef!=='string'||!/^[a-f0-9]{64}$/.test(accountRef)||!runtime||typeof runtime.python!=='string'||!path.isAbsolute(runtime.python)||typeof runtime.projectRoot!=='string'||!path.isAbsolute(runtime.projectRoot))return fail('account_unavailable');
    let selection;try{selection=normalizeYouTubeSelection(youtubeSelection);}catch(_){return fail('account_authorization_required');}
    const env={...process.env,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8'};
    let cwd=runtime.projectRoot;
    if(runtime.buildKind==='bundled-runtime'){
      if(typeof runtime.dataRoot!=='string'||!path.isAbsolute(runtime.dataRoot))return fail('account_unavailable');
      cwd=runtime.dataRoot;env.PRODUCER_DESKTOP='1';env.PRODUCER_DESKTOP_DATA_ROOT=runtime.dataRoot;
    }else delete env.PRODUCER_DESKTOP_DATA_ROOT;
    let child;try{child=spawnImpl(runtime.python,['-B',path.join(runtime.projectRoot,'tools','desktop_youtube_account.py')],{cwd,env,windowsHide:true,stdio:['pipe','pipe','pipe']});}catch(_){return fail('account_unavailable');}
    let chunks=[],size=0,settled=false,killed=false,timer;
    const terminate=()=>{if(killed)return;killed=true;try{child.kill();}catch(_){} };
    const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);chunks=[];size=0;if(error){terminate();fail(error);}else resolve(value);};
    timer=setTimeout(()=>finish('provider_unavailable'),45000);
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
          if(Object.keys(value).some(key=>!['ok','platform','accountRef','broadcastId','streamId','settingsFingerprint','autoStart','autoStop','privacyStatus','serverUrl','streamKey'].includes(key))||value.platform!=='youtube'||value.accountRef!==accountRef||typeof value.streamKey!=='string'||!value.streamKey||value.streamKey.length>4096||/[\s\x00-\x1f\x7f]/.test(value.streamKey))return finish('account_authorization_required');
          if(value.broadcastId!==selection.broadcastId||value.streamId!==selection.streamId||value.settingsFingerprint!==selection.settingsFingerprint||value.autoStart!==selection.autoStart||value.autoStop!==selection.autoStop||value.privacyStatus!==selection.privacyStatus)return finish('broadcast_selection_changed');
          let serverUrl;try{serverUrl=validateServerUrl(value.serverUrl,{platform:'youtube'});}catch(_){return finish('streaming_not_available');}
          finish(null,{platform:'youtube',accountRef,...selection,serverUrl,streamKey:value.streamKey});
        }catch(_){finish('account_unavailable');}
      });
      child.stdin.end(JSON.stringify({accountRef,broadcastId:selection.broadcastId,streamId:selection.streamId,settingsFingerprint:selection.settingsFingerprint}));
    }catch(_){finish('account_unavailable');}
  });
}

function publicSelection(raw){
  if(!plain(raw)||raw.platform!=='youtube'||typeof raw.account_ref!=='string'||!/^[a-f0-9]{64}$/.test(raw.account_ref))throw Error('youtube_broadcast_unavailable');
  let selected;try{selected=normalizeYouTubeSelection({broadcastId:raw.broadcast_id,streamId:raw.stream_id,settingsFingerprint:raw.settings_fingerprint,autoStart:raw.auto_start,autoStop:raw.auto_stop,privacyStatus:raw.privacy_status});}catch(_){throw Error('youtube_broadcast_unavailable');}
  if(typeof raw.title!=='string'||raw.title.length>200||/[\x00-\x1f\x7f]/.test(raw.title)||!['lifecycle','stream_status'].every(key=>typeof raw[key]==='string'&&/^[A-Za-z_]{1,40}$/.test(raw[key])))throw Error('youtube_broadcast_unavailable');
  return {platform:'youtube',account_ref:raw.account_ref,broadcast_id:selected.broadcastId,stream_id:selected.streamId,settings_fingerprint:selected.settingsFingerprint,auto_start:selected.autoStart,auto_stop:selected.autoStop,privacy_status:selected.privacyStatus,title:raw.title,lifecycle:raw.lifecycle,stream_status:raw.stream_status};
}
function createYouTubeDestinationConnection({origin,store,trustedSender,mutate,fetchImpl=globalThis.fetch,append=()=>{}}={}){
  const base=require('./policy.cjs').studioOrigin(origin),safe=new Set([...SAFE,'destination_change_pending','destination_broadcast_busy','local_operator_required','invalid_account_request','selection_cancelled','destination_save_pending','secure_storage_unavailable','destination_library_full','destination_request_conflict','destination_request_retired','account_destination_managed']);let pending=null,epoch=0;
  const trusted=event=>{try{return trustedSender(event)===true;}catch(_){return false;}};
  async function request(action,broadcastId){
    const endpoint=base+'/api/production/accounts/youtube/'+(action==='list'?'broadcasts':'inspect-broadcast'),response=await fetchImpl(endpoint,{method:'POST',redirect:'error',cache:'no-store',credentials:'omit',headers:{Origin:base,'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify(broadcastId?{broadcast_id:broadcastId}:{}),signal:AbortSignal.timeout(65000)});
    if(!response||response.redirected||response.url!==endpoint||response.headers?.get('content-type')?.split(';')[0].trim().toLowerCase()!=='application/json'||!response.body)throw Error('youtube_broadcast_unavailable');
    const chunks=[];let size=0;for await(const chunk of response.body){const data=Buffer.from(chunk);size+=data.length;if(size>131072)throw Error('youtube_broadcast_unavailable');chunks.push(data);}const raw=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
    if(response.status!==200||raw?.ok!==true)throw Error(safe.has(raw?.reason)?raw.reason:'youtube_broadcast_unavailable');
    if(action==='list'){
      if(raw.platform!=='youtube'||typeof raw.account_ref!=='string'||!/^[a-f0-9]{64}$/.test(raw.account_ref)||!Array.isArray(raw.broadcasts)||raw.broadcasts.length>100)throw Error('youtube_broadcast_unavailable');
      const broadcasts=raw.broadcasts.map(publicSelection);if(broadcasts.some(item=>item.account_ref!==raw.account_ref)||new Set(broadcasts.map(item=>item.broadcast_id)).size!==broadcasts.length)throw Error('youtube_broadcast_unavailable');return {ok:true,platform:'youtube',account_ref:raw.account_ref,broadcasts};
    }
    const selection=publicSelection(raw.selection);if(selection.broadcast_id!==broadcastId)throw Error('broadcast_selection_changed');return {ok:true,selection};
  }
  return async(event,value)=>{
    if(!trusted(event))return {ok:false,reason:'local_operator_required'};
    if(!plain(value)||!['list','inspect','link','cancel'].includes(value.action)||Object.keys(value).some(key=>!({list:['action'],cancel:['action'],inspect:['action','broadcastId'],link:['action','broadcastId','expectedFingerprint','requestId']}[value.action]).includes(key))||['inspect','link'].includes(value.action)&&(typeof value.broadcastId!=='string'||!/^[A-Za-z0-9_-]{1,128}$/.test(value.broadcastId))||value.action==='link'&&(typeof value.requestId!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId)||typeof value.expectedFingerprint!=='string'||!/^[a-f0-9]{64}$/.test(value.expectedFingerprint)))return {ok:false,reason:'invalid_account_request'};
    if(value.action==='cancel'){if(pending?.saving)return {ok:false,reason:'destination_save_pending'};++epoch;pending=null;return {ok:true,cancelled:true};}
    if(pending)return {ok:false,reason:'destination_change_pending'};
    const token={epoch:++epoch,saving:false},frame=event.senderFrame,url=frame?.url,current=()=>trusted(event)&&event.senderFrame===frame&&frame?.url===url&&pending===token&&epoch===token.epoch;pending=token;
    const run=async()=>{
      const result=await request(value.action==='list'?'list':'inspect',value.broadcastId);if(!current())throw Error('selection_cancelled');if(value.action!=='link')return result;
      const selection=result.selection;if(selection.settings_fingerprint!==value.expectedFingerprint)throw Error('broadcast_selection_changed');
      token.saving=true;const youtubeSelection={broadcastId:selection.broadcast_id,streamId:selection.stream_id,settingsFingerprint:selection.settings_fingerprint,autoStart:selection.auto_start,autoStop:selection.auto_stop,privacyStatus:selection.privacy_status};
      const saved=await store.saveAccount({platform:'youtube',name:('YouTube · '+(selection.title||selection.broadcast_id)).slice(0,80),accountRef:selection.account_ref,youtubeSelection,requestId:value.requestId});let warning=false;
      try{await append({at:new Date().toISOString(),action:'account_destination.link',actor:'Desktop operator',identityVerified:false,destinationId:saved.destination.id,platform:'youtube',replayed:saved.replayed});}catch(_){warning=true;}
      return {ok:true,selection,destination:saved.destination,...(warning?{activity_history_warning:true}:{})};
    };
    try{return await (value.action==='link'?mutate(event,run):run());}catch(error){return {ok:false,reason:safe.has(error?.message)?error.message:'youtube_broadcast_unavailable'};}finally{if(pending===token)pending=null;}
  };
}
module.exports={createYouTubeResolver,createYouTubeDestinationConnection,publicSelection};
