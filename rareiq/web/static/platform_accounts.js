/* Local account consent UI. Opening it never begins sign-in or connects viewer chat. */
(function(host){
  'use strict';
  const VERIFY_URL='https://www.twitch.tv/activate',NAMES={twitch:'Twitch',youtube:'YouTube',kick:'Kick'};
  const GOOGLE_URL='https://accounts.google.com/o/oauth2/v2/auth',GOOGLE_SCOPE='https://www.googleapis.com/auth/youtube.readonly';
  function googleAuthorizationUrl(value){
    if(typeof value!=='string'||value.length>8192||/[\x00-\x20\x7f]/.test(value)||!value.startsWith(GOOGLE_URL+'?'))return null;
    try{
      const url=new URL(value),fields=['client_id','redirect_uri','response_type','scope','access_type','prompt','state','code_challenge','code_challenge_method'],pairs=Array.from(url.searchParams.entries());
      if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth'||url.username||url.password||url.port||url.hash||pairs.length!==fields.length||fields.some(key=>url.searchParams.getAll(key).length!==1)||pairs.some(([key])=>!fields.includes(key)))return null;
      const get=key=>url.searchParams.get(key),redirect=get('redirect_uri').match(/^http:\/\/127\.0\.0\.1:([1-9][0-9]{3,4})\/callback$/);
      if(!redirect||Number(redirect[1])<1024||Number(redirect[1])>65535||get('response_type')!=='code'||get('scope')!==GOOGLE_SCOPE||get('access_type')!=='offline'||get('prompt')!=='consent'||get('code_challenge_method')!=='S256'||!/^[A-Za-z0-9_-]{32,256}$/.test(get('state'))||!/^[A-Za-z0-9_-]{43}$/.test(get('code_challenge'))||!/^[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com$/.test(get('client_id')))return null;
      return value;
    }catch(_){return null;}
  }
  const REASONS={app_setup_required:'Twitch sign-in needs a one-time app setup. It is not ready on this computer yet.',authorization_required:'Sign in on Twitch to allow read-only access to your chat.',authorization_pending:'Enter this code on Twitch and approve read-only chat access.',authorization_expired:'This sign-in code expired. Start a new sign-in when you are ready.',authorization_denied:'Twitch sign-in was declined. You can start again when ready.',authorization_rejected:'Twitch did not accept this sign-in. Try again when ready.',chat_scope_required:'Chat-reading permission is missing. Sign in again and review the permission on Twitch.',authorization_refresh_required:'This account needs a fresh sign-in before it can be used.',account_identity_mismatch:'The Twitch account could not be confirmed. Sign in again.',account_storage_unavailable:'This computer could not securely save the account. Retry after account storage is available.',provider_unavailable:'Twitch could not be reached. Check the connection and retry.',provider_rate_limited:'Twitch is limiting requests. Wait before trying again.',invalid_provider_endpoint:'The sign-in address could not be verified. Start a new sign-in.',invalid_provider_response:'The sign-in details could not be verified. Retry to check the account.',youtube_sign_in_setup_required:'YouTube sign-in is not available in this dialog yet. Existing saved host authorization can still be used from Viewer chat.',kick_public_callback_required:'Kick needs separately approved message delivery before it can connect.'};
  const text=(value,max)=>typeof value==='string'?value.slice(0,max):'';
  function account(raw,now=Date.now()/1000){
    const platform=Object.hasOwn(NAMES,raw?.platform)?raw.platform:null;if(!platform)return null;
    const value={platform,state:['not_authorized','pending','authorized','unavailable'].includes(raw.state)?raw.state:'unavailable',reason:text(raw.reason,100),authorized:raw.authorized===true,app_configured:raw.app_configured===true};
    if(platform==='kick')return {...value,state:'unavailable',authorized:false,reason:'kick_public_callback_required'};
    if(typeof raw.public_label==='string')value.public_label=raw.public_label.slice(0,80);
    if(typeof raw.expires_at==='number'&&Number.isFinite(raw.expires_at))value.expires_at=raw.expires_at;
    if(value.state==='pending'){
      if(typeof raw.flow_id!=='string'||!/^[a-f0-9]{32}$/.test(raw.flow_id)||!value.expires_at)return {...value,state:'unavailable',authorized:false,reason:'invalid_provider_response'};
      if(value.expires_at<=now)return {...value,state:'not_authorized',authorized:false,reason:'authorization_expired'};
      if(platform==='youtube')return {...value,flow_id:raw.flow_id};
      if(raw.verification_url!==VERIFY_URL||typeof raw.user_code!=='string'||!/^[A-Za-z0-9-]{4,32}$/.test(raw.user_code))return {...value,state:'unavailable',authorized:false,reason:raw.verification_url!==VERIFY_URL?'invalid_provider_endpoint':'invalid_provider_response'};
      return {...value,flow_id:raw.flow_id,user_code:raw.user_code,verification_url:VERIFY_URL};
    }
    if(value.state==='authorized'&&(!value.authorized||!value.expires_at||value.expires_at<=now))return {...value,state:'not_authorized',authorized:false,reason:'authorization_refresh_required'};
    value.authorized=value.state==='authorized'&&value.authorized;return value;
  }
  function normalize(payload,now){
    if(!Array.isArray(payload?.accounts))throw Error('invalid_response');
    return Object.keys(NAMES).map(platform=>account(payload.accounts.find(item=>item?.platform===platform)||{platform,state:'unavailable',reason:'account_unavailable'},now));
  }
  function explanation(value){
    if(!value)return 'Account status is unavailable. Retry to check again.';if(value.state==='authorized'&&value.authorized)return 'Account ready. Choose Use account to connect viewer chat.';
    if(value.platform==='youtube'){
      if(value.reason==='youtube_sign_in_setup_required')return REASONS.youtube_sign_in_setup_required;
      if(!value.app_configured||value.reason==='app_setup_required')return 'YouTube sign-in needs a one-time app setup. It is not ready on this computer yet.';
      const reasons={authorization_required:'Sign in with Google to allow read-only access to your YouTube channel and chat.',authorization_pending:'Open Google sign-in, review the read-only permission, then return here.',authorization_expired:'This Google sign-in expired. Start a new sign-in when ready.',validating_authorization:'Google sign-in received. Checking your YouTube channel…',authorization_denied:'Google sign-in was declined. You can start again when ready.',authorization_rejected:'Google did not accept this sign-in. Try again when ready.',chat_scope_required:'YouTube read-only permission is missing. Sign in again and review consent on Google.',provider_unavailable:'Google could not be reached. Check the connection and retry.',provider_rate_limited:'Google is limiting requests. Wait before trying again.',account_identity_mismatch:'The YouTube account could not be confirmed. Sign in again.',offline_access_required:'Google did not grant continuing account access. Sign in again and review the permission.',youtube_channel_required:'This Google account needs a YouTube channel before it can be used.',channel_selection_required:'The YouTube channel could not be selected. Check the intended account before signing in again.',callback_listener_unavailable:'Google sign-in could not be prepared on this computer. Retry when it is available.',account_state_changed:'Account settings changed. Start a new sign-in when ready.'};
      return reasons[value.reason]||REASONS[value.reason]||'Account status could not be confirmed. Retry to check again.';
    }
    if(value.platform==='twitch'&&!value.app_configured)return REASONS.app_setup_required;return REASONS[value.reason]||'Account status could not be confirmed. Retry to check again.';
  }
  function createController(options={}){
    const fetcher=options.fetch||((...args)=>host.fetch(...args)),setTimer=options.setTimeout||host.setTimeout.bind(host),clearTimer=options.clearTimeout||host.clearTimeout.bind(host),now=options.now||(()=>Date.now()/1000),notify=options.onChange||(()=>{}),timeouts=new Set();
    let opened=false,destroyed=false,generation=0,accounts=[],status='',stale=false,busy='',busyPlatform='',read=null,command=null,timer=null,reservedWindow=null,googleOpenedFlow='',activityHistoryWarning=false;
    function snapshot(){accounts=accounts.map(value=>account(value,now()));return {open:opened,accounts:accounts.map(value=>({...value})),status:status+(activityHistoryWarning?' Action completed, but its activity history could not be saved.':''),activityHistoryWarning,stale,busy,busyPlatform,googleOpenedFlow};}
    const emit=()=>{if(!destroyed)notify(snapshot());};
    function invalidate(){generation++;clearTimer(timer);timer=null;read?.abort();command?.abort();read=command=null;try{reservedWindow?.close();}catch(_){}reservedWindow=null;for(const timeout of timeouts)clearTimer(timeout);timeouts.clear();}
    async function request(url,init={},controller=new host.AbortController()){
      const timeout=setTimer(()=>controller.abort(),10000);timeouts.add(timeout);
      try{const response=await fetcher(url,{credentials:'same-origin',cache:'no-store',...init,signal:controller.signal});const data=await response.json();if(!response.ok){const error=Error('request_failed');error.reason=typeof data?.reason==='string'?data.reason:'';throw error;}return data;}finally{clearTimer(timeout);timeouts.delete(timeout);}
    }
    function schedule(){clearTimer(timer);const expiry=Math.min(...accounts.filter(value=>value.state==='pending').map(value=>value.expires_at)),delay=Number.isFinite(expiry)?Math.min(5000,Math.max(1,(expiry-now())*1000)):5000;if(opened&&!destroyed)timer=setTimer(()=>refresh(false),delay);}
    async function refresh(explicit=true){
      if(!opened||destroyed||read||busy)return;if(explicit)activityHistoryWarning=false;clearTimer(timer);timer=null;emit();const life=generation,controller=new host.AbortController();read=controller;
      try{const result=await request('/api/production/accounts',{},controller);if(!opened||destroyed||life!==generation)return;accounts=normalize(result,now());stale=false;status='Account status updated. Signing in does not connect chat.';emit();}
      catch(_){if(opened&&!destroyed&&life===generation){stale=true;accounts=accounts.map(value=>({...value,state:'unavailable',authorized:false,user_code:undefined,flow_id:undefined,verification_url:undefined}));status='Account status could not be loaded. Retry to check again.';emit();}}
      finally{if(read===controller)read=null;if(opened&&!destroyed&&life===generation)schedule();}
    }
    async function run(kind,platform='twitch'){
      const value=snapshot().accounts.find(item=>item.platform===platform),cancel=kind==='cancel',ownBusy=busyPlatform===platform&&['begin','authorize'].includes(busy);
      if(!opened||destroyed||!['twitch','youtube'].includes(platform)||!['begin','cancel'].includes(kind)||busy&&!(cancel&&ownBusy)||cancel&&!ownBusy&&value?.state!=='pending'||!cancel&&(!value?.app_configured||value.state==='pending'))return false;
      invalidate();const life=generation,controller=new host.AbortController();command=controller;busy=kind;busyPlatform=platform;stale=false;activityHistoryWarning=false;if(platform==='youtube')googleOpenedFlow='';
      if(cancel)accounts=accounts.map(item=>item.platform===platform?{...item,state:'not_authorized',authorized:false,user_code:undefined,flow_id:undefined,verification_url:undefined}:item);
      status=cancel?'Cancelling this sign-in…':platform==='twitch'?'Requesting a Twitch sign-in code…':'Preparing Google sign-in…';emit();let success=false;
      try{const result=await request('/api/production/accounts/'+platform+'/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'},controller);if(!opened||destroyed||life!==generation)return false;const next=account(result.account,now());if(!next||next.platform!==platform)throw Error('invalid_response');activityHistoryWarning=result.activity_history_warning===true;accounts=Object.keys(NAMES).map(key=>key===platform?next:accounts.find(item=>item.platform===key)||account({platform:key}));status=cancel?'Sign-in cancelled. Any previously saved account is kept.':explanation(next);success=true;}
      catch(error){if(opened&&!destroyed&&life===generation){stale=true;status=cancel?'Cancellation could not be confirmed. Retry account status before continuing.':explanation({platform,state:'unavailable',app_configured:true,reason:error.reason});}}
      finally{if(command===controller)command=null;if(opened&&!destroyed&&life===generation){busy='';busyPlatform='';emit();schedule();}}
      return success;
    }
    async function openGoogle(){
      const value=snapshot().accounts.find(item=>item.platform==='youtube');if(!opened||destroyed||busy||stale||value?.state!=='pending'||value.reason==='validating_authorization'||value.flow_id===googleOpenedFlow)return false;
      invalidate();const life=generation,flow=value.flow_id,controller=new host.AbortController(),native=options.authorizeAccount||host.producerDesktop?.authorizeAccount?.bind(host.producerDesktop)||host.ProducerDesktop?.authorizeAccount?.bind(host.ProducerDesktop);let popup=null;command=controller;busy='authorize';busyPlatform='youtube';activityHistoryWarning=false;status='Opening Google sign-in…';emit();
      function current(){const matches=opened&&!destroyed&&life===generation&&snapshot().accounts.some(item=>item.platform==='youtube'&&item.state==='pending'&&item.flow_id===flow&&item.reason!=='validating_authorization');if(!matches&&opened&&!destroyed&&life===generation)status='This Google sign-in is no longer active. Start a new sign-in when ready.';return matches;}
      try{
        if(native){const result=await native({platform:'youtube',flowId:flow});if(!current())return false;if(result!==true&&result?.ok!==true)throw Error('open_failed');}
        else{
          const open=options.openWindow||host.open?.bind(host);popup=open?.('about:blank','_blank');if(!popup)throw Error('popup_blocked');reservedWindow=popup;popup.opener=null;
          const result=await request('/api/production/accounts/youtube/authorization?flow_id='+encodeURIComponent(flow),{},controller);if(!current())return false;const url=googleAuthorizationUrl(result?.authorization_url);if(!url)throw Error('invalid_authorization_url');popup.location.replace(url);reservedWindow=null;popup=null;
        }
        googleOpenedFlow=flow;status='Google sign-in opened. Finish sign-in in that browser window, then return here.';return true;
      }catch(error){if(opened&&!destroyed&&life===generation)status=error.message==='popup_blocked'?'Your browser blocked the sign-in window. Allow a window for this app, then choose Open Google sign-in again.':'Google sign-in could not be opened safely. Retry account status or cancel this attempt.';return false;}
      finally{try{popup?.close();}catch(_){}if(reservedWindow===popup)reservedWindow=null;if(command===controller)command=null;if(opened&&!destroyed&&life===generation){busy='';busyPlatform='';emit();schedule();}}
    }
    return {snapshot,refresh,run,openGoogle,open(){if(destroyed)return;if(!opened){invalidate();opened=true;busy='';busyPlatform='';accounts=[];status='Loading accounts…';stale=false;emit();}return refresh();},close(){if(!opened)return;invalidate();opened=false;busy='';busyPlatform='';accounts=[];status='';activityHistoryWarning=false;emit();},async copy(){const value=snapshot().accounts.find(item=>item.platform==='twitch'),life=generation;if(!opened||value?.state!=='pending'||!value.user_code)return false;try{const copy=options.copy||host.navigator?.clipboard?.writeText?.bind(host.navigator.clipboard);if(!copy)throw Error('copy_unavailable');await copy(value.user_code);if(opened&&!destroyed&&life===generation){status='Code copied. Paste it on Twitch and review the permission there.';emit();}return true;}catch(_){if(opened&&!destroyed&&life===generation){status='Copy is unavailable. Select the code and copy it yourself.';emit();}return false;}},async use(platform='twitch'){const value=snapshot().accounts.find(item=>item.platform===platform);if(!opened||destroyed||busy||!['twitch','youtube'].includes(platform)||value?.state!=='authorized'||!value.authorized||stale)return false;const life=generation;activityHistoryWarning=false;busy='use';busyPlatform=platform;status='Connecting viewer chat with this account…';emit();try{await options.onUse?.(platform);return true;}catch(_){if(opened&&!destroyed&&life===generation){status='Chat connection could not be confirmed. Check Viewer chat before retrying.';stale=true;}return false;}finally{if(opened&&!destroyed&&life===generation){busy='';busyPlatform='';emit();}}},destroy(){if(destroyed)return;invalidate();opened=false;accounts=[];busy='';busyPlatform='';destroyed=true;}};
  }
  let sequence=0;
  function mount(parent,options={}){
    if(!parent)return null;const doc=parent.ownerDocument||host.document,prefix='platform-accounts-'+(++sequence),dialog=doc.createElement('dialog');dialog.className='platform-accounts-dialog';dialog.setAttribute('aria-labelledby',prefix+'-title');
    function node(tag,text,parentNode=dialog,attrs={}){const el=doc.createElement(tag);if(text)el.textContent=text;for(const [key,value]of Object.entries(attrs))el.setAttribute(key,value);parentNode.append(el);return el;}
    const header=node('header',''),title=node('h2','Connect accounts',header,{id:prefix+'-title'}),close=node('button','Close',header,{type:'button','data-accounts-close':''});
    node('p','Authorize your account here, then choose Use account to connect viewer chat. Signing in never starts a broadcast or sends chat messages.',dialog,{class:'platform-accounts-intro'});
    const status=node('p','',dialog,{role:'status','aria-live':'polite','aria-atomic':'true','data-accounts-status':''}),rows=new Map();
    for(const [platform,name]of Object.entries(NAMES)){
      const section=node('section','',dialog,{'data-account-platform':platform});node('h3',name,section);const label=node('p','',section,{class:'platform-account-label'}),note=node('p','',section,{'data-account-note':platform});
      if(platform==='kick'){rows.set(platform,{section,label,note});continue;}
      const key=platform==='twitch'?'':platform;
      node('p',platform==='twitch'?'Read-only chat permission. Complete sign-in and review consent on Twitch. This account permission does not grant streaming or message-sending access.':'Read-only access to your YouTube channel and live chat. Review consent on Google. This account permission does not grant streaming or message-sending access.',section,{class:'platform-accounts-scope'});
      const pending=node('div','',section,{class:'platform-accounts-pending','data-accounts-pending':key});let code,copy,link,authorize,googleNote;
      if(platform==='twitch'){
        node('p','Your Twitch sign-in code',pending);code=node('output','',pending,{tabindex:'0','aria-label':'Twitch sign-in code','data-accounts-code':''});copy=node('button','Copy code',pending,{type:'button','data-accounts-copy':''});link=node('a','Open Twitch sign-in',pending,{href:VERIFY_URL,target:'_blank',rel:'noopener noreferrer',referrerpolicy:'no-referrer','data-accounts-link':''});
        node('p','Enter the code on twitch.tv. This code expires; closing this dialog keeps it available until it expires. Cancel sign-in stops this attempt.',pending);
      }else{
        googleNote=node('p','Continue in Google, then return here. This sign-in expires; Cancel sign-in stops the attempt.',pending);authorize=node('button','Open Google sign-in',pending,{type:'button','data-accounts-google-open':''});
      }
      const actions=node('div','',section,{class:'platform-accounts-actions'}),begin=node('button','Sign in with '+name,actions,{type:'button','data-accounts-begin':key}),cancel=node('button','Cancel sign-in',actions,{type:'button','data-accounts-cancel':key}),use=node('button','Use account',actions,{type:'button','data-accounts-use':key});rows.set(platform,{section,label,note,pending,code,copy,link,authorize,googleNote,begin,cancel,use});
    }
    const refresh=node('button','Retry account status',dialog,{type:'button','data-accounts-refresh':''});parent.append(dialog);let opener=null;
    const controller=createController({...options,onChange(state){
      if(status.textContent!==state.status)status.textContent=state.status;dialog.setAttribute('aria-busy',String(Boolean(state.busy)));refresh.hidden=!state.stale;refresh.disabled=Boolean(state.busy);
      for(const [platform,row]of rows){const value=state.accounts.find(item=>item.platform===platform);row.note.textContent=value?explanation(value):'Loading account status…';row.label.textContent=value?.state==='authorized'&&value.authorized?value.public_label?'Account ready · '+value.public_label:'Account ready':'';
        if(platform==='kick')continue;const pending=value?.state==='pending',ready=value?.state==='authorized'&&value.authorized,ownBusy=state.busyPlatform===platform&&['begin','authorize'].includes(state.busy);
        row.pending.hidden=!pending;
        if(platform==='twitch'){const code=pending?value.user_code:'';if(row.code.textContent!==code)row.code.textContent=code;row.copy.disabled=Boolean(state.busy)||!pending;row.link.hidden=!pending;}
        else{const launched=pending&&state.googleOpenedFlow===value.flow_id,validating=value?.reason==='validating_authorization';row.authorize.disabled=Boolean(state.busy)||state.stale||!pending||launched||validating;row.authorize.textContent=launched?'Google sign-in opened':'Open Google sign-in';row.authorize.title=launched?'Finish sign-in in the browser window already opened.':validating?'Google sign-in is being checked.':'';row.googleNote.textContent=validating?'Google sign-in received. Checking your channel…':launched?'Finish sign-in in the opened browser window, then return here. Cancel sign-in stops this attempt.':'Continue in Google, then return here. This sign-in expires; Cancel sign-in stops the attempt.';}
        row.begin.hidden=pending||ready;row.begin.disabled=Boolean(state.busy)||!value?.app_configured||state.stale;row.begin.title=!value?.app_configured?explanation({...value,platform,app_configured:false}):state.stale?'Retry account status before starting sign-in.':'';
        row.cancel.hidden=!pending&&!ownBusy;row.cancel.disabled=Boolean(state.busy)&&!ownBusy;row.use.hidden=!ready;row.use.disabled=Boolean(state.busy)||state.stale;
      }options.onChange?.(state);
    }});
    for(const platform of ['twitch','youtube']){const row=rows.get(platform);row.begin.addEventListener('click',()=>controller.run('begin',platform));row.cancel.addEventListener('click',()=>controller.run('cancel',platform));row.use.addEventListener('click',async()=>{if(await controller.use(platform))api.close();});}
    rows.get('twitch').copy.addEventListener('click',()=>controller.copy());rows.get('youtube').authorize.addEventListener('click',()=>controller.openGoogle());refresh.addEventListener('click',()=>controller.refresh());
    const api={element:dialog,controller,open(trigger){opener=trigger||doc.activeElement;if(!dialog.open)dialog.showModal();controller.open();},close(){controller.close();if(dialog.open)dialog.close();opener?.focus?.();},destroy(){controller.destroy();if(dialog.open)dialog.close();dialog.remove();}};
    close.addEventListener('click',()=>api.close());dialog.addEventListener('cancel',event=>{event.preventDefault();api.close();});dialog.addEventListener('close',()=>controller.close());return api;
  }
  const api={mount,createController,normalize,account,explanation,googleAuthorizationUrl,VERIFY_URL};if(typeof module==='object'&&module.exports)module.exports=api;else host.ProducerPlatformAccounts=api;
})(typeof window==='undefined'?globalThis:window);
