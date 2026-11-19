'use strict';
const {studioOrigin}=require('./policy.cjs');
const PLATFORM=new Set(['twitch','youtube','kick']),ID=/^[A-Za-z0-9_-]{1,128}$/,UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const plain=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const fail=reason=>{throw Error(reason);};
const text=(v,max=200)=>typeof v==='string'&&v.length<=max&&!/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(v);
function publicResult(raw){
  if(!plain(raw))fail('provider_unavailable');const result={};
  for(const key of ['ok','authorized','editable','activity_history_warning','recovery_storage_warning'])if(typeof raw[key]==='boolean')result[key]=raw[key];
  for(const key of ['platform','state','reason','channel_id','broadcast_id','request_id'])if(typeof raw[key]==='string'&&raw[key].length<=128&&/^[A-Za-z0-9_-]+$/.test(raw[key]))result[key]=raw[key];
  if(text(raw.public_label,100))result.public_label=raw.public_label;
  if(plain(raw.capabilities)){result.capabilities={};for(const key of ['title','description','category_id','category','tags','requires_broadcast_selection'])if(typeof raw.capabilities[key]==='boolean')result.capabilities[key]=raw.capabilities[key];}
  if(plain(raw.fields)){result.fields={};for(const key of ['title','description','category_id','category_name'])if(text(raw.fields[key],key==='description'?5000:500))result.fields[key]=raw.fields[key];if(Array.isArray(raw.fields.tags)&&raw.fields.tags.length<=30&&raw.fields.tags.every(v=>text(v,100)))result.fields.tags=[...raw.fields.tags];}
  for(const key of ['categories','broadcasts'])if(Array.isArray(raw[key])){
    if(raw[key].length>100)fail('provider_unavailable');result[key]=raw[key].map(item=>{if(!plain(item)||typeof item.id!=='string'||!ID.test(item.id))fail('provider_unavailable');const copy={id:item.id};for(const name of key==='categories'?['name']:['title','state','status'])if(text(item[name],500))copy[name]=item[name];return copy;});
  }
  return result;
}
function createStreamMetadataHandler({origin,store,destinations,trustedSender,mutate,confirm,permission,fetchImpl=globalThis.fetch}={}){
  const base=studioOrigin(origin),trusted=e=>{try{return trustedSender(e)===true;}catch(_){return false;}};
  async function request(platform,action,body){
    const endpoint=base+'/api/production/stream-metadata/'+platform+'/'+action;
    const response=await fetchImpl(endpoint,{method:'POST',redirect:'error',credentials:'omit',cache:'no-store',headers:{Origin:base,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(40000)});
    if(!response||response.redirected||response.url!==endpoint||response.headers?.get('content-type')?.split(';')[0].trim()!=='application/json'||!response.body)fail('provider_unavailable');
    const parts=[];let size=0;for await(const part of response.body){const bytes=Buffer.from(part);size+=bytes.length;if(size>131072)fail('provider_unavailable');parts.push(bytes);}
    const value=publicResult(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(parts))));if(value.ok===false)return {...value,platform};if(response.status!==200||value.platform!==platform)fail('provider_unavailable');return value;
  }
  return async(event,value)=>{
    if(!trusted(event))return {ok:false,reason:'local_operator_required'};
    try{
      if(!plain(value)||!PLATFORM.has(value.platform)||!['inspect','categories','apply','permission'].includes(value.action))fail('invalid_stream_info');
      const allowed={inspect:['broadcastId'],categories:['query'],permission:[],apply:['destinationId','revision','requestId','channelId','categoryId','broadcastId']}[value.action];
      if(Object.keys(value).some(k=>!['action','platform',...allowed].includes(k)))fail('invalid_stream_info');
      for(const key of ['broadcastId','channelId','categoryId'])if(value[key]!==undefined&&(typeof value[key]!=='string'||!ID.test(value[key])))fail('invalid_stream_info');
      if(value.query!==undefined&&(!text(value.query,100)||/[\r\n\t]/.test(value.query)))fail('invalid_stream_info');
      const frame=event.senderFrame,frameUrl=frame?.url,current=()=>trusted(event)&&event.senderFrame===frame&&frame?.url===frameUrl;
      if(value.action==='permission')return await permission(event,value.platform);
      const body=value.broadcastId?{broadcast_id:value.broadcastId}:{};
      if(value.action!=='apply'){const result=await request(value.platform,value.action,value.action==='categories'?{query:value.query||''}:body);if(!current())fail('local_operator_required');return result;}
      if(typeof value.destinationId!=='string'||!UUID.test(value.destinationId)||!Number.isSafeInteger(value.revision)||value.revision<0||typeof value.requestId!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId)||typeof value.channelId!=='string'||!ID.test(value.channelId))fail('invalid_stream_info');
      return await mutate(event,async()=>{
        const saved=await store.public(),targets=await destinations.public(),destination=targets.destinations.find(d=>d.id===value.destinationId&&d.platform===value.platform);if(!current())fail('local_operator_required');
        if(saved.revision!==value.revision)fail('stream_info_revision_conflict');if(!destination)fail('destination_not_found');
        const boundBroadcast=destination.platform==='youtube'&&destination.linkedAccount===true?destination.youtubeBroadcastId:null;
        if(destination.platform==='youtube'&&destination.linkedAccount===true&&(!ID.test(boundBroadcast)||value.broadcastId!==boundBroadcast))fail('broadcast_selection_changed');
        const checked=await request(value.platform,'inspect',body);if(!current())fail('local_operator_required');if(checked.ok===false)return checked;if(checked.channel_id!==value.channelId)fail('account_identity_mismatch');if(!checked.editable)fail('metadata_scope_required');
        if(value.platform==='youtube'&&!value.broadcastId)fail('broadcast_selection_required');
        const override=saved.overrides[value.destinationId],draft=override||saved.shared,values={title:draft.title};if(!draft.title.trim())fail('invalid_title');
        if(checked.capabilities?.description===true)values.description=draft.description;
        if(checked.capabilities?.tags===true&&override)values.tags=override.tags.split(',').map(v=>v.trim()).filter(Boolean);
        if(value.categoryId){if(checked.capabilities?.category_id!==true&&checked.capabilities?.category!==true)fail('unsupported_field');values.category_id=value.categoryId;}
        const accepted=await confirm({platform:value.platform,destinationName:destination.name,channelLabel:checked.public_label||checked.channel_id,broadcastId:value.broadcastId,values});if(!current())fail('local_operator_required');if(accepted!==true)return {ok:true,platform:value.platform,state:'cancelled'};
        if((await store.public()).revision!==value.revision)fail('stream_info_revision_conflict');
        if(boundBroadcast){const currentTargets=await destinations.public(),currentTarget=currentTargets.destinations.find(target=>target.id===value.destinationId&&target.platform==='youtube');if(!current()||currentTarget?.linkedAccount!==true||currentTarget.youtubeBroadcastId!==boundBroadcast)fail('broadcast_selection_changed');}
        const result=await request(value.platform,'apply',{...body,request_id:value.requestId,expected_channel_id:value.channelId,values});if(!current())fail('local_operator_required');return result;
      });
    }catch(error){const reason=typeof error?.message==='string'&&/^[a-z_]{1,80}$/.test(error.message)?error.message:'provider_unavailable';return {ok:false,reason};}
  };
}
module.exports={createStreamMetadataHandler,publicResult};
