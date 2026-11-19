'use strict';
const {studioOrigin}=require('./policy.cjs');

const SCOPE='https://www.googleapis.com/auth/youtube.readonly';
const METADATA_SCOPE='https://www.googleapis.com/auth/youtube.force-ssl';
const exactScopes=(raw,base,extra)=>{const scopes=raw.split(' ');return scopes.length===new Set(scopes).size&&(scopes.length===base.length||scopes.length===base.length+1&&scopes.includes(extra))&&base.every(s=>scopes.includes(s));};
const MAX_RESPONSE_BYTES=16384;
const FIELDS=new Set(['client_id','redirect_uri','response_type','scope','access_type','prompt','state','code_challenge','code_challenge_method']);
const failure=reason=>({ok:false,reason});

function authorizationRequest(value){
  return Boolean(value&&Object.prototype.toString.call(value)==='[object Object]'
    &&Object.keys(value).length===2&&Object.hasOwn(value,'platform')&&Object.hasOwn(value,'flowId')
    &&['youtube','kick'].includes(value.platform)&&typeof value.flowId==='string'&&/^[a-f0-9]{32}$/.test(value.flowId));
}

function kickAuthorizationUrl(value){
  try{
    if(typeof value!=='string'||value.length>8192||/[^\x21-\x7e]/.test(value)||!value.startsWith('https://id.kick.com/oauth/authorize?'))return null;
    const u=new URL(value),pairs=[...u.searchParams],q=Object.fromEntries(pairs),fields=['client_id','redirect_uri','response_type','scope','state','code_challenge','code_challenge_method'];
    if(u.origin!=='https://id.kick.com'||u.port||u.username||u.password||u.hash||u.pathname!=='/oauth/authorize'||pairs.length!==fields.length||new Set(pairs.map(([k])=>k)).size!==fields.length||pairs.some(([k])=>!fields.includes(k)))return null;
    if(!/^[A-Za-z0-9_-]{1,220}$/.test(q.client_id)||q.redirect_uri!=='http://localhost:8770/callback'||q.response_type!=='code'||q.code_challenge_method!=='S256'||!/^[A-Za-z0-9_-]{43}$/.test(q.code_challenge)||!/^[A-Za-z0-9_-]{32,128}$/.test(q.state)||!exactScopes(q.scope,['user:read','channel:read','streamkey:read'],'channel:write'))return null;
    return value;
  }catch(_){return null;}
}

function googleAuthorizationUrl(value){
  try{
    if(typeof value!=='string'||value.length>8192||/[^\x21-\x7e]/.test(value)
      ||!value.startsWith('https://accounts.google.com/o/oauth2/v2/auth?'))return null;
    const url=new URL(value),pairs=[...url.searchParams.entries()],query=Object.fromEntries(pairs);
    if(url.protocol!=='https:'||url.hostname!=='accounts.google.com'||url.port||url.username||url.password
      ||url.pathname!=='/o/oauth2/v2/auth'||url.hash||pairs.length!==FIELDS.size
      ||new Set(pairs.map(([key])=>key)).size!==FIELDS.size||pairs.some(([key])=>!FIELDS.has(key)))return null;
    if(!/^[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com$/.test(query.client_id)
      ||query.response_type!=='code'||!exactScopes(query.scope,[SCOPE],METADATA_SCOPE)||query.access_type!=='offline'||query.prompt!=='consent'
      ||query.code_challenge_method!=='S256'||!/^[A-Za-z0-9_-]{43}$/.test(query.code_challenge)
      ||!/^[A-Za-z0-9_-]{32,128}$/.test(query.state))return null;
    const callback=/^http:\/\/127\.0\.0\.1:([1-9][0-9]{3,4})\/callback$/.exec(query.redirect_uri);
    if(!callback||Number(callback[1])<1024||Number(callback[1])>65535)return null;
    return value;
  }catch(_){return null;}
}

async function boundedJson(response,endpoint){
  if(!response||response.status!==200||response.ok!==true||response.redirected===true||response.url!==endpoint
    ||response.headers?.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'
    ||!response.body)throw Error('authorization_unavailable');
  const declared=response.headers.get('content-length');
  if(declared!==null&&(!/^[0-9]{1,8}$/.test(declared)||Number(declared)>MAX_RESPONSE_BYTES))throw Error('authorization_unavailable');
  const parts=[];let length=0;
  for await(const chunk of response.body){
    const bytes=Buffer.from(chunk);length+=bytes.length;
    if(length>MAX_RESPONSE_BYTES)throw Error('authorization_unavailable');
    parts.push(bytes);
  }
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(parts)));
}

function createAccountAuthorization({origin,trustedSender,openExternal,fetchImpl=globalThis.fetch}={}){
  const localOrigin=studioOrigin(origin);
  if(typeof trustedSender!=='function'||typeof openExternal!=='function'||typeof fetchImpl!=='function')throw Error('account_authorization_unavailable');
  let pending=null;
  const trusted=event=>{try{return trustedSender(event)===true;}catch(_){return false;}};
  return async function authorizeAccount(event,value){
    if(!trusted(event))return failure('local_operator_required');
    if(!authorizationRequest(value))return failure('invalid_authorization_request');
    if(pending)return pending.flowId===value.flowId&&pending.platform===value.platform?pending.promise:failure('authorization_open_pending');
    const frame=event.senderFrame,frameUrl=frame?.url;
    const endpoint=localOrigin+'/api/production/accounts/'+value.platform+'/authorization?flow_id='+value.flowId;
    const work=(async()=>{
      try{
        const response=await fetchImpl(endpoint,{method:'GET',redirect:'error',cache:'no-store',credentials:'omit',
          headers:{Accept:'application/json',Origin:localOrigin},signal:AbortSignal.timeout(8000)});
        if(response?.status===409)return failure('authorization_flow_unavailable');
        const payload=await boundedJson(response,endpoint);
        if(!payload||Object.prototype.toString.call(payload)!=='[object Object]'
          ||Object.keys(payload).length!==1||!Object.hasOwn(payload,'authorization_url'))return failure('authorization_unavailable');
        const url=(value.platform==='youtube'?googleAuthorizationUrl:kickAuthorizationUrl)(payload.authorization_url);
        if(!url||new URL(new URL(url).searchParams.get('redirect_uri')).port===new URL(localOrigin).port)return failure('authorization_unavailable');
        if(!trusted(event)||event.senderFrame!==frame||frame?.url!==frameUrl)return failure('local_operator_required');
        try{await openExternal(url);}catch(_){return failure('authorization_open_failed');}
        return {ok:true};
      }catch(_){return failure('authorization_unavailable');}
    })();
    pending={platform:value.platform,flowId:value.flowId,promise:work};
    try{return await work;}finally{if(pending?.promise===work)pending=null;}
  };
}

module.exports={authorizationRequest,googleAuthorizationUrl,kickAuthorizationUrl,createAccountAuthorization};
