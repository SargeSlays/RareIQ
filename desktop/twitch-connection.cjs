'use strict';
// Main only: credentials travel over an owned child-process pipe, never HTTP/IPC.
const path=require('node:path'),{spawn}=require('node:child_process');
const {studioOrigin}=require('./policy.cjs');
const ACTIONS=new Set(['status','begin','begin_metadata','cancel','check','link','disconnect']);
const SAFE=new Set(['account_unavailable','account_authorization_required','account_identity_mismatch','streaming_scope_required','authorization_refresh_required','provider_unavailable','streaming_not_available','destination_broadcast_busy','destination_change_pending','invalid_account_request','local_operator_required','account_storage_unavailable','secure_storage_unavailable','destination_library_full','destination_request_conflict','destination_request_retired','account_destination_managed']);
const reason=error=>SAFE.has(error?.message)?error.message:'account_unavailable';
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);

function createTwitchResolver({runtime,spawnImpl=spawn}={}){
  return accountRef=>new Promise((resolve,reject)=>{
    const fail=code=>reject(Error(SAFE.has(code)?code:'account_authorization_required'));
    if(!/^[a-f0-9]{64}$/.test(accountRef)||!runtime||!path.isAbsolute(runtime.python)||!path.isAbsolute(runtime.projectRoot))return fail('account_unavailable');
    const env={...process.env,PYTHONDONTWRITEBYTECODE:'1',PYTHONIOENCODING:'utf-8'};
    let cwd=runtime.projectRoot;
    if(runtime.buildKind==='bundled-runtime'){
      if(!path.isAbsolute(runtime.dataRoot))return fail('account_unavailable');
      cwd=runtime.dataRoot;env.PRODUCER_DESKTOP='1';env.PRODUCER_DESKTOP_DATA_ROOT=runtime.dataRoot;
    }else delete env.PRODUCER_DESKTOP_DATA_ROOT;
    let child;try{child=spawnImpl(runtime.python,['-B',path.join(runtime.projectRoot,'tools','desktop_twitch_account.py')],{cwd,env,windowsHide:true,stdio:['pipe','pipe','pipe']});}catch(_){return fail('account_unavailable');}
    let output='',settled=false;
    const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);output='';if(error)fail(error);else resolve(value);};
    const timer=setTimeout(()=>{child.kill();finish('provider_unavailable');},22000);
    child.stdout.on('data',chunk=>{output+=chunk.toString('utf8');if(Buffer.byteLength(output)>16384){child.kill();finish('account_unavailable');}});
    child.stderr.resume(); // Provider errors and secret material are never forwarded or logged.
    child.on('error',()=>finish('account_unavailable'));
    child.stdin.on('error',()=>finish('account_unavailable'));
    child.on('close',code=>{
      if(settled)return;
      try{
        const value=JSON.parse(output);
        if(code!==0||!plain(value)||value.ok!==true)return finish(SAFE.has(value?.reason)?value.reason:'account_authorization_required');
        if(Object.keys(value).some(key=>!['ok','streamKey','accountRef','publicLabel'].includes(key))||value.accountRef!==accountRef||typeof value.streamKey!=='string'||!value.streamKey||value.streamKey.length>4096||/[\s\x00-\x1f\x7f]/.test(value.streamKey))return finish('account_authorization_required');
        finish(null,{accountRef,streamKey:value.streamKey});
      }catch(_){finish('account_unavailable');}
    });
    child.stdin.end(JSON.stringify({accountRef}));
  });
}

function createTwitchConnection({origin,store,trustedSender,mutate,fetchImpl=globalThis.fetch,append=()=>{}}={}){
  const base=studioOrigin(origin);let pending=null,epoch=0;
  const trusted=event=>{try{return trustedSender(event)===true;}catch(_){return false;}};
  async function request(action){
    const endpoint=base+'/api/production/accounts'+(action==='status'?'':'/twitch/'+({begin:'begin-streaming',begin_metadata:'begin-metadata'}[action]||action));
    const response=await fetchImpl(endpoint,{method:action==='status'?'GET':'POST',redirect:'error',cache:'no-store',credentials:'omit',headers:{Accept:'application/json',Origin:base,...(action==='status'?{}:{'Content-Type':'application/json'})},...(action==='status'?{}:{body:'{}'}),signal:AbortSignal.timeout(20000)});
    if(!response||response.status!==200||response.redirected||response.url!==endpoint||!response.body||response.headers?.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json')throw Error('account_unavailable');
    const chunks=[];let size=0;
    for await(const chunk of response.body){const bytes=Buffer.from(chunk);size+=bytes.length;if(size>16384)throw Error('account_unavailable');chunks.push(bytes);}
    const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));
    const raw=action==='status'?value.accounts?.find(item=>item.platform==='twitch'):value.account;
    if(!plain(raw)||raw.platform!=='twitch'||!['authorized','not_authorized','pending','unavailable'].includes(raw.state))throw Error('account_unavailable');
    // Explicit allowlist: even a compromised/malformed response cannot carry tokens over IPC.
    const account={platform:'twitch',state:raw.state,authorized:raw.authorized===true,streaming_authorized:raw.streaming_authorized===true,metadata_authorized:raw.authorized===true&&raw.metadata_authorized===true,app_configured:raw.app_configured===true};
    if(typeof raw.reason==='string'&&/^[a-z_]{1,80}$/.test(raw.reason))account.reason=raw.reason;
    if(typeof raw.public_label==='string'&&/^[a-z0-9_]{1,25}$/.test(raw.public_label))account.public_label=raw.public_label;
    if(typeof raw.account_ref==='string'&&/^[a-f0-9]{64}$/.test(raw.account_ref))account.account_ref=raw.account_ref;
    if(typeof raw.expires_at==='number'&&Number.isFinite(raw.expires_at))account.expires_at=raw.expires_at;
    if(raw.state==='pending'){
      if(typeof raw.user_code!=='string'||!/^[A-Za-z0-9-]{4,32}$/.test(raw.user_code)||typeof raw.flow_id!=='string'||!/^[a-f0-9]{32}$/.test(raw.flow_id))throw Error('account_unavailable');
      Object.assign(account,{user_code:raw.user_code,flow_id:raw.flow_id,verification_url:'https://www.twitch.tv/activate'});
      account.authorization_kind=['streaming','metadata'].includes(raw.authorization_kind)?raw.authorization_kind:'chat';
    }
    return {ok:true,account,...(value.activity_history_warning===true?{activity_history_warning:true}:{}),...(value.connection_stop_warning===true?{connection_stop_warning:true}:{})};
  }
  const handle=async(event,value)=>{
    if(!trusted(event))return {ok:false,reason:'local_operator_required'};
    if(!plain(value)||!ACTIONS.has(value.action)||Object.keys(value).some(key=>!['action','requestId'].includes(key))||(value.action==='link'&&!(typeof value.requestId==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId))))return {ok:false,reason:'invalid_account_request'};
    if(pending&&!['status','cancel'].includes(value.action))return {ok:false,reason:'destination_change_pending'};
    const operation=value.action==='status'?epoch:++epoch,token=Symbol();
    const frame=event.senderFrame,frameUrl=frame?.url;
    const current=()=>operation===epoch&&trusted(event)&&event.senderFrame===frame&&frame?.url===frameUrl;
    const run=async()=>{
      if(value.action!=='link')return request(value.action);
      const result=await request('check'),account=result.account;
      if(!current())throw Error('local_operator_required');
      if(!account.authorized||!account.streaming_authorized||!account.account_ref||!account.public_label)throw Error('account_authorization_required');
      const saved=await store.saveAccount({platform:'twitch',name:'Twitch · '+account.public_label,accountRef:account.account_ref,requestId:value.requestId});
      let warning=result.activity_history_warning===true;
      try{await append({at:new Date().toISOString(),action:'account_destination.link',actor:'Desktop operator',identityVerified:false,destinationId:saved.destination.id,replayed:saved.replayed});}catch(_){warning=true;}
      return {ok:true,account,destination:saved.destination,...(warning?{activity_history_warning:true}:{})};
    };
    try{
      if(value.action==='status')return await run();
      pending=token;
      return await (['cancel','check'].includes(value.action)?run():mutate(event,run));
    }catch(error){return {ok:false,reason:reason(error)};}
    finally{if(pending===token)pending=null;}
  };
  // Startup/hourly validation does not open consent, connect chat or start media.
  handle.checkSaved=async()=>{
    const result=await request('status');
    if(!pending&&result.account.state!=='pending'&&(result.account.authorized||result.account.reason==='authorization_refresh_required'))return request('check');
    return result;
  };
  return handle;
}
module.exports={createTwitchResolver,createTwitchConnection};
