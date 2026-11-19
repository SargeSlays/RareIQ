/* Native settings account controller. Credentials never enter this renderer. */
(function(host){
  'use strict';
  const VERIFY_URL='https://www.twitch.tv/activate';
  const REASONS={account_authorization_required:'Twitch sign-in needs attention. Check or reconnect the saved account.',app_setup_required:'Twitch needs its one-time app setup on this computer.',authorization_required:'Sign in with Twitch to connect your channel.',authorization_refresh_required:'Your saved connection needs checking. Choose Check connection before signing in again.',authorization_pending:'Finish signing in on Twitch, then return here.',authorization_expired:'The sign-in code expired. Start a new sign-in when ready.',authorization_denied:'Twitch sign-in was declined. Your previous saved connection is kept.',authorization_rejected:'Twitch did not accept this sign-in. Check the connection or try again.',account_identity_mismatch:'The Twitch channel could not be confirmed. Reconnect the saved channel.',account_state_changed:'The saved account changed. Check the connection before trying again.',chat_scope_required:'Chat permission is missing. Sign in again to review access.',streaming_scope_required:'Streaming permission is missing. Choose Enable streaming and review access on Twitch.',stream_key_scope_required:'Streaming permission is missing. Choose Enable streaming and review access on Twitch.',account_storage_unavailable:'Protected account storage is unavailable. Your previous saved connection is kept.',provider_unavailable:'Twitch could not be reached. Check your connection and retry.',provider_rate_limited:'Twitch is limiting requests. Wait a moment, then check again.',account_service_closed:'The account service is unavailable. Reopen the studio and retry.',authorization_cancelled:'Sign-in cancelled. Your previous saved connection is kept.',account_disconnected:'Twitch sign-in was removed from this computer. Linked destinations need the same channel to reconnect.',disconnected:'Twitch sign-in was removed from this computer. Linked destinations need the same channel to reconnect.',destination_broadcast_busy:'Stop the broadcast before changing its account connection.',account_unavailable:'The saved account could not be checked. Retry when ready.'};
  const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  function normalize(raw,now=Date.now()/1000){
    if(!plain(raw)||raw.platform!=='twitch'||!['authorized','not_authorized','pending','unavailable'].includes(raw.state))throw Error('invalid_account_status');
    const value={platform:'twitch',state:raw.state,reason:Object.hasOwn(REASONS,raw.reason)||raw.reason==='account_authorized'?raw.reason:'account_unavailable',authorized:raw.authorized===true,streaming_authorized:raw.authorized===true&&raw.streaming_authorized===true,app_configured:raw.app_configured===true};
    if(typeof raw.public_label==='string'&&/^[a-z0-9_]{1,25}$/.test(raw.public_label))value.public_label=raw.public_label;
    if(typeof raw.account_ref==='string'&&/^[a-f0-9]{64}$/.test(raw.account_ref))value.account_ref=raw.account_ref;
    if(raw.authorization_kind==='metadata')value.authorization_kind='metadata';
    if(Number.isFinite(raw.expires_at)&&raw.expires_at>0)value.expires_at=raw.expires_at;
    if(raw.state==='pending'){
      if(typeof raw.user_code!=='string'||!/^[A-Za-z0-9-]{4,32}$/.test(raw.user_code)||typeof raw.flow_id!=='string'||!/^[a-f0-9]{32}$/.test(raw.flow_id)||!value.expires_at)throw Error('invalid_account_status');
      value.user_code=raw.user_code;value.flow_id=raw.flow_id;
      if(value.expires_at<=now){value.state=value.authorized?'authorized':'not_authorized';value.reason='authorization_expired';delete value.user_code;delete value.flow_id;}
    }
    return value;
  }
  function createController({request,onChange=()=>{},onDestinationsChanged=async()=>{},confirmDisconnect=async()=>false,copy=async()=>{},open=async()=>{},randomId=()=>crypto.randomUUID(),schedule=setTimeout,unschedule=clearTimeout,now=()=>Date.now()/1000}={}){
    let state={account:null,busy:'',stale:false,locked:false,message:'Checking your Twitch connection…',historyWarning:false,stopWarning:false},closed=false,epoch=0,timer=null,linkRequest=null,copyTimer=null;
    const snapshot=()=>({...state,account:state.account?{...state.account}:null});
    const emit=()=>onChange(snapshot());
    const stopTimer=()=>{if(timer!==null)unschedule(timer);timer=null;};
    function polling(){stopTimer();if(!closed&&state.account?.state==='pending')timer=schedule(()=>{timer=null;run('status');},2000);}
    function install(payload,action){
      const account=normalize(payload.account,now());
      if(state.account?.account_ref!==account.account_ref)linkRequest=null;
      state.account=account;state.stale=false;
      if(payload.activity_history_warning===true)state.historyWarning=true;
      if(payload.connection_stop_warning===true)state.stopWarning=true;
      state.message=action==='link'?'Twitch destination saved. Review Program and explicitly start when ready.':action==='disconnect'?'Twitch sign-in removed. Linked destinations require reconnecting the same channel.':action==='check'&&account.authorized?'Saved Twitch connection checked.':REASONS[account.reason]||(account.streaming_authorized?'Twitch streaming access is saved securely.':account.authorized?'Chat access is saved. Enable streaming to use this account as a broadcast destination.':'Check your saved Twitch connection.');
      if(account.state==='pending'&&account.authorization_kind==='metadata')state.message='Review Twitch permission to edit stream title, category and tags. Existing saved access stays available if you decline.';
    }
    async function run(action){
      if(closed||!['status','begin','cancel','check','link','disconnect'].includes(action))return false;
      if(state.busy&&!(action==='cancel'&&state.busy==='begin'))return false;
      if(state.locked&&!['status','cancel'].includes(action))return false;
      if(action==='link'&&(!state.account?.streaming_authorized||state.stale||state.stopWarning||state.account.state==='pending'))return false;
      if(action==='begin'&&(!state.account?.app_configured||state.stale||state.stopWarning))return false;
      if(action==='disconnect'){
        const account=state.account;
        if(!account?.authorized||!await confirmDisconnect()||closed||state.locked||state.busy||state.account!==account)return false;
      }
      const own=++epoch;stopTimer();state.busy=action;state.message=action==='status'?state.message:({begin:'Preparing Twitch sign-in…',cancel:'Cancelling sign-in…',check:'Checking the saved connection…',link:'Saving your Twitch destination…',disconnect:'Disconnecting Twitch…'})[action];
      if(action!=='status')state.historyWarning=false;
      const payload={action};if(action==='link')payload.requestId=linkRequest||(linkRequest=randomId());emit();
      try{
        const result=await request(payload);if(closed||own!==epoch)return false;
        if(!plain(result)||result.ok===false){state.stale=true;state.message=REASONS[result?.reason]||'The action could not be confirmed. Your saved connection is kept; check before trying again.';return false;}
        install(result,action);if(action==='link')linkRequest=null;
        if(action==='link'||action==='disconnect')try{await onDestinationsChanged();}catch(_){if(!closed&&own===epoch)state.message+=' The destination list could not refresh; reopen setup to check it.';}
        return true;
      }catch(_){if(!closed&&own===epoch){state.stale=true;state.message='The action could not be confirmed. Your saved connection is kept. Check connection and retry.';}return false;}
      finally{if(!closed&&own===epoch){state.busy='';emit();polling();}}
    }
    return {run,snapshot,setLocked(value){if(state.locked!==(value===true)){state.locked=value===true;emit();}},async copyCode(){const account=state.account;if(closed||account?.state!=='pending'||state.busy)return false;try{await copy(account.user_code);if(closed||state.account?.flow_id!==account.flow_id)return false;state.message='Sign-in code copied. Paste it only on twitch.tv.';emit();if(copyTimer!==null)unschedule(copyTimer);copyTimer=schedule(()=>{copyTimer=null;if(!closed&&state.account?.flow_id===account.flow_id){state.message=REASONS.authorization_pending;emit();}},3000);return true;}catch(_){if(closed)return false;state.message='Copy is unavailable. Enter the displayed code on twitch.tv.';emit();return false;}},async openSignIn(){if(closed||state.account?.state!=='pending')return false;try{await open(VERIFY_URL);return true;}catch(_){if(closed)return false;state.message='Twitch could not open. Visit twitch.tv/activate in your browser and enter the code.';emit();return false;}},close(){closed=true;++epoch;stopTimer();if(copyTimer!==null)unschedule(copyTimer);},start(){closed=false;return run('status');}};
  }
  function mount({document:doc=host.document,api=host.producerSettings,onDestinationsChanged,onBusyChange=()=>{}}={}){
    const root=doc?.querySelector('#twitchAccount');if(!root||typeof api?.twitchAccount!=='function')return null;
    const node=id=>doc.querySelector('#'+id),buttons={begin:node('twitchBegin'),check:node('twitchCheck'),cancel:node('twitchCancel'),link:node('twitchLink'),disconnect:node('twitchDisconnect')};
    let lastBusy=false;
    const controller=createController({request:value=>api.twitchAccount(value),onDestinationsChanged,confirmDisconnect:async()=>host.confirm('Disconnect Twitch on this computer? The saved Twitch sign-in will be removed. Linked destinations require reconnecting the same channel. Manual stream-key destinations are separate.'),copy:value=>host.navigator.clipboard.writeText(value),open:value=>api.openPlatform(value),onChange(state){
      const account=state.account,pending=account?.state==='pending',ready=account?.streaming_authorized,working=Boolean(state.busy),locked=state.locked;
      root.setAttribute('aria-busy',String(working));node('twitchIdentity').textContent=account?.authorized&&account.public_label?'@'+account.public_label:'Connect your channel';
      node('twitchBadge').textContent=state.stale?'Needs a check':pending?'Awaiting Twitch':ready?'Streaming access saved':account?.authorized?'Chat connected':'Not connected';
      node('twitchStatus').textContent=state.message+(state.stopWarning?' Saved sign-in removed, but chat shutdown could not be confirmed. Reopen the studio before reconnecting.':'')+(state.historyWarning?' Local activity history could not be written.':'');
      node('twitchPending').hidden=!pending;node('twitchCode').textContent=pending?account.user_code:'';
      buttons.begin.hidden=pending||ready;buttons.begin.textContent=account?.authorized?'Enable streaming':'Sign in with Twitch';buttons.begin.disabled=working||locked||state.stale||state.stopWarning||!account?.app_configured;
      buttons.link.hidden=!ready||pending;buttons.link.disabled=working||locked||state.stale||state.stopWarning;
      buttons.disconnect.hidden=!account?.authorized;buttons.disconnect.disabled=working||locked;
      buttons.cancel.hidden=!pending&&state.busy!=='begin';buttons.cancel.disabled=working&&state.busy!=='begin';
      buttons.check.disabled=working||locked;buttons.check.textContent=state.stale?'Retry connection check':'Check connection';
      for(const [action,button]of Object.entries(buttons))button.title=button.disabled?(locked&&action!=='cancel'?'Stop the broadcast or finish the current action before changing accounts.':working?'Wait for the account action to finish.':state.stopWarning?'Reopen the studio before reconnecting; chat shutdown was not confirmed.':state.stale?'Check the saved connection before continuing.':!account?.app_configured?'Twitch needs its one-time app setup.':''):(action==='link'?'Save this channel as a destination. Nothing starts broadcasting.':'');
      node('twitchCopy').disabled=working||!pending;node('twitchOpen').disabled=working||!pending;
      node('twitchLocked').hidden=!locked;
      const busy=Boolean(state.busy&&state.busy!=='status');if(lastBusy!==busy){lastBusy=busy;onBusyChange(busy);}
    }});
    for(const [action,button]of Object.entries(buttons))button.addEventListener('click',()=>controller.run(action));
    node('twitchCopy').addEventListener('click',()=>controller.copyCode());node('twitchOpen').addEventListener('click',()=>controller.openSignIn());
    return {controller,setLocked:value=>controller.setLocked(value),start:()=>controller.start(),close:()=>controller.close(),focus(){root.scrollIntoView({block:'start',behavior:'instant'});node('twitchCheck').focus();}};
  }
  const api={normalize,createController,mount,VERIFY_URL};if(typeof module==='object'&&module.exports)module.exports=api;else host.ProducerTwitchAccountUI=api;
})(typeof window==='undefined'?globalThis:window);
