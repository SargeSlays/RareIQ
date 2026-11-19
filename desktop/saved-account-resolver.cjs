'use strict';
// Main only. The backend remains the sole refresh writer; helpers read private pipes.
const {studioOrigin}=require('./policy.cjs');
const {normalizeYouTubeSelection}=require('./destinations.cjs');
const SAFE=new Set(['account_authorization_required','streaming_not_available','streaming_scope_required','secure_ingest_unavailable','provider_unavailable','account_storage_unavailable','account_state_changed','authorization_refresh_required','broadcast_selection_changed','youtube_broadcast_unavailable','youtube_stream_shared','youtube_broadcast_not_owned','youtube_stream_unavailable','youtube_stream_not_owned','provider_rate_limited']);
function createSavedAccountResolver({origin,resolveTwitch,resolveKick,resolveYouTube,fetchImpl=globalThis.fetch}={}){
  const base=studioOrigin(origin);
  return async(accountRef,context={platform:'twitch'})=>{
    if(typeof accountRef!=='string'||!/^[a-f0-9]{64}$/.test(accountRef)||!context||Object.keys(context).some(key=>!['platform',...(context.platform==='youtube'?['youtubeSelection']:[])].includes(key))||!['twitch','kick','youtube'].includes(context.platform))throw Error('account_authorization_required');
    let selection;try{if(context.platform==='youtube')selection=normalizeYouTubeSelection(context.youtubeSelection);}catch(_){throw Error('account_authorization_required');}
    const platform=context.platform,url=base+'/api/production/accounts/'+platform+'/check';
    try{
      const response=await fetchImpl(url,{method:'POST',redirect:'error',cache:'no-store',credentials:'omit',headers:{Accept:'application/json','Content-Type':'application/json',Origin:base},body:'{}',signal:AbortSignal.timeout(platform==='youtube'?65000:20000)});
      if(!response||response.status!==200||response.redirected||response.url!==url||response.headers?.get('content-type')?.split(';')[0].trim().toLowerCase()!=='application/json'||!response.body)throw Error('account_authorization_required');
      const chunks=[];let size=0;for await(const part of response.body){const data=Buffer.from(part);size+=data.length;if(size>16384)throw Error('account_authorization_required');chunks.push(data);}
      const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks))),account=value?.account;
      if(value.ok!==true||account?.platform!==platform||account.state!=='authorized'||account.authorized!==true||account.streaming_authorized!==true||account.account_ref!==accountRef)throw Error('account_authorization_required');
      const resolver=platform==='youtube'?resolveYouTube:platform==='kick'?resolveKick:resolveTwitch;if(typeof resolver!=='function')throw Error('account_authorization_required');
      return await (platform==='youtube'?resolver(accountRef,selection):resolver(accountRef));
    }catch(error){throw Error(SAFE.has(error?.message)?error.message:'account_authorization_required');}
  };
}
module.exports={createSavedAccountResolver};
