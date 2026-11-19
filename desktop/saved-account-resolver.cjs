'use strict';
// Main only. The backend remains the sole refresh writer; helpers read private pipes.
const {studioOrigin}=require('./policy.cjs');
const SAFE=new Set(['account_authorization_required','streaming_not_available','streaming_scope_required','secure_ingest_unavailable','provider_unavailable','account_storage_unavailable','account_state_changed','authorization_refresh_required']);
function createSavedAccountResolver({origin,resolveTwitch,resolveKick,fetchImpl=globalThis.fetch}={}){
  const base=studioOrigin(origin);
  return async(accountRef,context={platform:'twitch'})=>{
    if(typeof accountRef!=='string'||!/^[a-f0-9]{64}$/.test(accountRef)||!context||Object.keys(context).some(key=>key!=='platform')||!['twitch','kick'].includes(context.platform))throw Error('account_authorization_required');
    const platform=context.platform,url=base+'/api/production/accounts/'+platform+'/check';
    try{
      const response=await fetchImpl(url,{method:'POST',redirect:'error',cache:'no-store',credentials:'omit',headers:{Accept:'application/json','Content-Type':'application/json',Origin:base},body:'{}',signal:AbortSignal.timeout(20000)});
      if(!response||response.status!==200||response.redirected||response.url!==url||response.headers?.get('content-type')?.split(';')[0].trim().toLowerCase()!=='application/json'||!response.body)throw Error('account_authorization_required');
      const chunks=[];let size=0;for await(const part of response.body){const data=Buffer.from(part);size+=data.length;if(size>16384)throw Error('account_authorization_required');chunks.push(data);}
      const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks))),account=value?.account;
      if(value.ok!==true||account?.platform!==platform||account.state!=='authorized'||account.authorized!==true||account.streaming_authorized!==true||account.account_ref!==accountRef)throw Error('account_authorization_required');
      const resolver=platform==='kick'?resolveKick:resolveTwitch;if(typeof resolver!=='function')throw Error('account_authorization_required');
      return await resolver(accountRef);
    }catch(error){throw Error(SAFE.has(error?.message)?error.message:'account_authorization_required');}
  };
}
module.exports={createSavedAccountResolver};
