'use strict';
const {studioOrigin}=require('./policy.cjs');
const plain=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const ACTIONS=new Set(['status','begin','begin_metadata','cancel','check','disconnect','authorize']);
const SAFE=new Set(['destination_change_pending','destination_broadcast_busy','local_operator_required','authorization_flow_unavailable','authorization_unavailable','authorization_open_failed','authorization_open_pending']);
function createProviderConnection({origin,trustedSender,mutate,authorize,fetchImpl=globalThis.fetch}={}){
  const base=studioOrigin(origin),pending=new Map();
  const trusted=e=>{try{return trustedSender(e)===true;}catch(_){return false;}};
  async function request(platform,action){
    const url=base+'/api/production/accounts'+(action==='status'?'':'/'+platform+'/'+(action==='begin_metadata'?'begin-metadata':action));
    const r=await fetchImpl(url,{method:action==='status'?'GET':'POST',redirect:'error',cache:'no-store',credentials:'omit',headers:{Accept:'application/json',Origin:base,...(action==='status'?{}:{'Content-Type':'application/json'})},...(action==='status'?{}:{body:'{}'}),signal:AbortSignal.timeout(20000)});
    if(!r||r.status!==200||r.redirected||r.url!==url||!r.body||r.headers?.get('content-type')?.split(';')[0].trim().toLowerCase()!=='application/json')throw Error('account_unavailable');
    const chunks=[];let size=0;
    for await(const part of r.body){const b=Buffer.from(part);size+=b.length;if(size>16384)throw Error('account_unavailable');chunks.push(b);}
    const v=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks))),raw=action==='status'?v.accounts?.find(a=>a.platform===platform):v.account;
    if(!plain(raw)||raw.platform!==platform||!['authorized','not_authorized','pending','unavailable'].includes(raw.state))throw Error('account_unavailable');
    const account={platform,state:raw.state,authorized:raw.authorized===true,metadata_authorized:raw.authorized===true&&raw.metadata_authorized===true,app_configured:raw.app_configured===true};
    if(typeof raw.reason==='string'&&/^[a-z_]{1,80}$/.test(raw.reason))account.reason=raw.reason;
    if(typeof raw.public_label==='string'&&raw.public_label.length<=80&&!/[\x00-\x1f\x7f]/.test(raw.public_label))account.public_label=raw.public_label;
    if(typeof raw.expires_at==='number'&&Number.isFinite(raw.expires_at))account.expires_at=raw.expires_at;
    if(raw.state==='pending'){
      if(typeof raw.flow_id!=='string'||!/^[a-f0-9]{32}$/.test(raw.flow_id))throw Error('account_unavailable');
      account.flow_id=raw.flow_id;
      account.authorization_kind=raw.authorization_kind==='metadata'?'metadata':'chat';
    }
    return {ok:true,account,...(v.activity_history_warning===true?{activity_history_warning:true}:{}),...(v.connection_stop_warning===true?{connection_stop_warning:true}:{})};
  }
  return async(e,v)=>{
    if(!trusted(e))return {ok:false,reason:'local_operator_required'};
    if(!plain(v)||!['youtube','kick'].includes(v.platform)||!ACTIONS.has(v.action)||Object.keys(v).some(k=>!['platform','action','flowId'].includes(k))||v.action==='authorize'&&!(typeof v.flowId==='string'&&/^[a-f0-9]{32}$/.test(v.flowId)))return {ok:false,reason:'invalid_account_request'};
    if(pending.has(v.platform)&&!['status','cancel'].includes(v.action))return {ok:false,reason:'destination_change_pending'};
    const token=Symbol(),frame=e.senderFrame,frameUrl=frame?.url;
    const run=async()=>{
      if(v.action==='authorize'){
        const opened=await authorize(e,{platform:v.platform,flowId:v.flowId});
        if(opened?.ok!==true)return {ok:false,reason:SAFE.has(opened?.reason)?opened.reason:'authorization_unavailable'};
        if(!trusted(e)||e.senderFrame!==frame||frame?.url!==frameUrl)return {ok:false,reason:'local_operator_required'};
        return {...await request(v.platform,'status'),authorization_opened:true};
      }
      return request(v.platform,v.action);
    };
    try{
      if(v.action==='status')return await run();
      pending.set(v.platform,token);
      return await (['cancel','check'].includes(v.action)?run():mutate(e,run));
    }catch(error){return {ok:false,reason:SAFE.has(error?.message)?error.message:'account_unavailable'};}
    finally{if(pending.get(v.platform)===token)pending.delete(v.platform);}
  };
}
module.exports={createProviderConnection};
