/* Saved provider account controls. Native Main owns authorization URLs and credentials. */
(function(host){
  'use strict';
  const NAMES={youtube:'YouTube',kick:'Kick'},plain=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const REASONS={authorization_required:'Sign in to connect your account.',authorization_pending:'Open sign-in, review the permissions and return here.',validating_authorization:'Sign-in received. Checking your channel…',account_authorized:'Your account connection is saved securely on this Windows account.',authorization_refresh_required:'Your saved connection needs checking. Choose Check connection before signing in again.',authorization_expired:'This sign-in attempt expired. Start a new sign-in when ready.',authorization_denied:'Sign-in was declined. Your previous saved connection is kept.',authorization_rejected:'The provider did not accept this sign-in. Check or reconnect your account.',account_identity_mismatch:'The saved channel could not be confirmed. Check the connection before reconnecting.',account_state_changed:'The saved account changed. Check the connection and retry.',provider_unavailable:'The provider could not be reached. Check your connection and retry.',provider_rate_limited:'The provider is limiting requests. Wait a moment before checking again.',account_storage_unavailable:'Protected account storage is unavailable. Your previous connection is kept.',chat_scope_required:'The required read permission is missing. Sign in again to review access.',offline_access_required:'Permission to keep the connection saved is missing. Sign in again.',youtube_channel_required:'This Google account needs an eligible YouTube channel.',channel_selection_required:'Choose the intended YouTube channel when signing in.',callback_listener_unavailable:'The local sign-in return address is busy. Close another sign-in attempt and retry.',authorization_cancelled:'Sign-in cancelled. Your previous saved connection is kept.',account_disconnected:'Saved sign-in removed from this computer.',account_service_closed:'The account service is unavailable. Reopen the studio.',local_operator_required:'Open these controls in the desktop studio.',destination_broadcast_busy:'Stop broadcasting before changing the account connection.',authorization_open_failed:'The sign-in browser could not open. Check the connection and retry.',authorization_flow_unavailable:'This sign-in attempt is no longer available. Start again.',authorization_unavailable:'The sign-in details could not be verified. Check the connection and retry.'};
  Object.assign(REASONS,{streaming_scope_required:'Kick streaming permission is required. Reconnect and review the streaming permissions before saving a destination.',account_authorization_required:'Kick sign-in needs attention. Check or reconnect the saved account before saving a destination.',secure_ingest_unavailable:'Kick secure ingest could not be confirmed. Check the connection and retry; nothing was started.',invalid_request_id:'Check the connection and retry saving the Kick destination.',request_id_conflict:'The destination request changed. Check the saved connection before retrying.'});
  const SETUP={youtube:'YouTube needs a Google Desktop app registration, YouTube Data API and consent setup before sign-in is available.',kick:'Kick needs a private app registration with its local callback at http://localhost:8770/callback before sign-in is available.'};
  function normalize(raw,platform,now=Date.now()/1000){
    if(!Object.hasOwn(NAMES,platform)||!plain(raw)||raw.platform!==platform||!['authorized','not_authorized','pending','unavailable'].includes(raw.state))throw Error('invalid_account_status');
    const value={platform,state:raw.state,authorized:raw.state!=='unavailable'&&raw.authorized===true,app_configured:raw.app_configured===true,reason:typeof raw.reason==='string'&&Object.hasOwn(REASONS,raw.reason)?raw.reason:raw.reason==='app_setup_required'?'app_setup_required':'account_unavailable'};
    if(typeof raw.public_label==='string'&&raw.public_label.length>0&&raw.public_label.length<=80&&!/[\x00-\x1f\x7f]/.test(raw.public_label))value.public_label=raw.public_label;
    if(Number.isFinite(raw.expires_at)&&raw.expires_at>0)value.expires_at=raw.expires_at;
    if(value.state==='pending'){
      if(typeof raw.flow_id!=='string'||!/^[a-f0-9]{32}$/.test(raw.flow_id)||!value.expires_at)throw Error('invalid_account_status');value.flow_id=raw.flow_id;
      if(value.expires_at<=now){value.state=value.authorized?'authorized':'not_authorized';value.reason='authorization_expired';delete value.flow_id;}
    }
    if(raw.state==='authorized'&&(!value.authorized||!value.expires_at||value.expires_at<=now)){value.state='not_authorized';value.authorized=false;value.reason='authorization_refresh_required';}
    if(['kick','youtube'].includes(platform)){value.streaming_authorized=value.state==='authorized'&&value.authorized&&raw.streaming_authorized===true;if(typeof raw.account_ref==='string'&&/^[a-f0-9]{64}$/.test(raw.account_ref))value.account_ref=raw.account_ref;}
    return value;
  }
  const SETUP_ERRORS={disconnect_before_app_setup:'Disconnect or cancel sign-in before changing app setup.',external_app_configuration_active:'App setup is managed outside this dialog. Keep that setup or review it before importing a file.',activity_history_unavailable:'App setup was not changed because activity history is unavailable. Retry after history is available.',account_storage_unavailable:'Protected account storage is unavailable. Your saved setup is kept.',app_setup_unavailable:'App setup could not be loaded. Check connection, then retry.',invalid_app_configuration:'This file is not a valid provider app setup file. Check connection, then choose the correct file.',invalid_app_provider:'Choose YouTube or Kick app setup from its own card.',app_setup_pending:'An app setup action is already running. Finish it before retrying.',local_operator_required:'Load the setup file from the desktop studio.'};
  function createController({platform,request,importApp=null,onChange=()=>{},onDestinationsChanged=async()=>{},confirmDisconnect=async()=>false,randomId=()=>crypto.randomUUID(),schedule=setTimeout,unschedule=clearTimeout,now=()=>Date.now()/1000}={}){
    if(!Object.hasOwn(NAMES,platform)||typeof request!=='function')throw Error('invalid_provider');
    let state={platform,account:null,busy:'',stale:false,locked:false,message:'Checking '+NAMES[platform]+'…',historyWarning:false,stopWarning:false,openedFlow:null},closed=false,epoch=0,timer=null,linkRequest=null;
    const snapshot=()=>({...state,account:state.account?{...state.account}:null,linkRetry:Boolean(linkRequest)}),emit=()=>onChange(snapshot());
    const stopTimer=()=>{if(timer!==null)unschedule(timer);timer=null;};
    function poll(){stopTimer();if(!closed&&state.account?.state==='pending')timer=schedule(()=>{timer=null;run('status');},2000);}
    function install(result,action){
      const value=normalize(result.account,platform,now());if(value.account_ref!==state.account?.account_ref)linkRequest=null;if(value.flow_id!==state.account?.flow_id||value.state!=='pending')state.openedFlow=null;state.account=value;state.stale=false;
      if(result.activity_history_warning===true)state.historyWarning=true;if(result.connection_stop_warning===true)state.stopWarning=true;
      state.message=action==='link'?'Kick destination saved. Prepare output and explicitly start when ready. Start checks Kick’s current secure ingest; platform receipt remains unverified.':!value.app_configured?'One-time '+NAMES[platform]+' app setup is needed before signing in.':action==='disconnect'?'Saved '+NAMES[platform]+' sign-in removed from this computer.':action==='check'&&value.state==='authorized'&&value.reason==='account_authorized'?'Saved '+NAMES[platform]+' connection checked.':REASONS[value.reason]||'The account status is unavailable. Check the connection and retry.';
    }
    async function run(action){
      if(closed||!['status','begin','cancel','check','disconnect','authorize','setup','link'].includes(action))return false;
      if(state.busy&&!(action==='cancel'&&['begin','authorize'].includes(state.busy)))return false;
      if(state.locked&&!['status','cancel'].includes(action))return false;
      if(action==='link'&&(platform!=='kick'||state.account?.state!=='authorized'||!state.account.authorized||!state.account.streaming_authorized||!state.account.account_ref||state.stale||state.stopWarning))return false;
      if(action==='setup'&&(typeof importApp!=='function'||!state.account||state.account.authorized||state.account.state==='pending'||state.stale||state.stopWarning))return false;
      if(action==='begin'&&(!state.account?.app_configured||state.stale||state.stopWarning))return false;
      if(action==='authorize'&&(state.account?.state!=='pending'||state.stale||state.openedFlow===state.account.flow_id||state.account.reason==='validating_authorization'))return false;
      if(action==='disconnect'){
        const account=state.account;if(!account||!await confirmDisconnect(platform)||closed||state.locked||state.busy||state.account!==account)return false;
      }
      const own=++epoch,payload={platform,action};if(action==='authorize')payload.flowId=state.account.flow_id;if(action==='link')payload.requestId=linkRequest||(linkRequest=randomId());
      stopTimer();state.busy=action;if(action!=='status'){if(action!=='setup')state.historyWarning=false;state.message=({begin:'Preparing sign-in…',cancel:'Cancelling sign-in…',check:'Checking the saved connection…',disconnect:'Removing saved sign-in…',authorize:'Opening provider sign-in…',setup:'Choose the provider app setup file in the file picker…',link:'Saving your Kick destination…'})[action];}emit();
      let setupSaved=false;
      try{
        if(action==='setup'){
          const imported=await importApp(platform);if(closed||own!==epoch)return false;
          if(!plain(imported)||imported.ok!==true||imported.platform!==platform){state.stale=true;state.message=SETUP_ERRORS[imported?.reason]||'The app setup file could not be loaded. Your saved setup is kept. Check connection, then retry loading the file.';return false;}
          if(imported.activity_history_warning===true)state.historyWarning=true;
          if(imported.cancelled===true){state.message='No app setup file loaded. Your previous setup is kept.';return true;}
          if(imported.configured!==true){state.stale=true;state.message='App setup could not be confirmed. Your saved setup is kept. Check connection before retrying.';return false;}
          setupSaved=true;
          let refreshed;try{refreshed=await request({platform,action:'status'});}catch(_){}
          if(closed||own!==epoch)return false;
          if(!plain(refreshed)||refreshed.ok!==true){state.stale=true;state.message='App setup was saved, but account status could not refresh. Check connection or reopen setup.';return false;}
          install(refreshed,action);state.message=state.account.app_configured?'App setup loaded securely.'+(!state.account.authorized&&state.account.state!=='pending'?' Sign in with '+NAMES[platform]+' to connect your account.':''):'App setup was saved, but provider setup is still unavailable. Check connection before continuing.';return true;
        }
        const result=await request(payload);if(closed||own!==epoch)return false;
        if(!plain(result)||result.ok!==true){state.stale=true;if(action==='link'&&['destination_request_conflict','destination_request_retired'].includes(result?.reason)){linkRequest=null;state.message='This destination request has changed or expired. Check connection, then choose Save destination again.';return false;}state.message=REASONS[result?.reason]||'The action could not be confirmed. Your previous saved connection is kept; check and retry.';return false;}
        if(action==='authorize'){
          if(result.account)install(result,action);state.openedFlow=payload.flowId;state.message='Finish signing in on '+NAMES[platform]+' in the opened browser, then return here.';
        }else install(result,action);
        if(action==='link')linkRequest=null;
        if(platform==='kick'&&['link','disconnect'].includes(action))try{await onDestinationsChanged();}catch(_){if(!closed&&own===epoch)state.message+=' The destination list could not refresh; reopen setup to check it.';}
        return true;
      }catch(_){if(!closed&&own===epoch){state.stale=true;state.message=action==='setup'?(setupSaved?'App setup was saved, but account status could not refresh. Check connection or reopen setup.':'The app setup file could not be loaded. Your saved setup is kept. Check connection, then retry loading the file.'):'The action could not be confirmed. Your saved connection is kept. Check and retry.';}return false;}
      finally{if(!closed&&own===epoch){state.busy='';emit();poll();}}
    }
    return {run,snapshot,setLocked(value){if(state.locked!==(value===true)){state.locked=value===true;emit();}},start(){closed=false;return run('status');},close(){closed=true;++epoch;stopTimer();}};
  }
  function mount({document:doc=host.document,api=host.producerSettings,onBusyChange=()=>{},onDestinationsChanged=async()=>{},onAccountChange=()=>{}}={}){
    if(typeof api?.providerAccount!=='function')return [];
    return Object.keys(NAMES).map(platform=>{
      const root=doc.querySelector('#'+platform+'Account');if(!root)return null;
      const node=suffix=>doc.querySelector('#'+platform+suffix),buttons=Object.fromEntries(['begin','authorize','check','cancel','disconnect'].map(action=>[action,node(action[0].toUpperCase()+action.slice(1))]));buttons.setup=node('LoadSetup');if(platform==='kick'&&node('Link'))buttons.link=node('Link');let lastBusy=false,restoreSetupFocus=false;
      const controller=createController({platform,request:value=>api.providerAccount(value),onDestinationsChanged,importApp:typeof api.importProviderApp==='function'?value=>api.importProviderApp(value):null,confirmDisconnect:()=>host.confirm('Disconnect '+NAMES[platform]+' on this computer? This removes the saved sign-in. Manual streaming destinations remain separate. Provider-side app access can also be revoked on the provider website.'),onChange(state){
        onAccountChange(platform,state);
        const a=state.account,pending=a?.state==='pending',working=Boolean(state.busy),opened=pending&&a.flow_id===state.openedFlow;root.setAttribute('aria-busy',String(working));node('Identity').textContent=a?.authorized&&a.public_label?a.public_label:'Connect your channel';node('Badge').textContent=state.stale?'Needs a check':!a?.app_configured?'Setup required':pending?'Awaiting '+NAMES[platform]:a.authorized?'Account saved':'Not connected';
        node('Status').textContent=state.message+(state.stopWarning?' Saved sign-in removed, but chat shutdown could not be confirmed. Reopen the studio before reconnecting.':'')+(state.historyWarning?' Local activity history could not be written.':'');
        if(doc.activeElement===buttons.setup&&a?.app_configured)restoreSetupFocus=true;
        node('Setup').hidden=Boolean(a?.authorized||pending);node('Setup').querySelector('summary').textContent=a?.app_configured?'App setup':'One-time app setup needed';node('Pending').hidden=!pending;node('Locked').hidden=!state.locked;
        buttons.begin.hidden=pending||a?.authorized;buttons.begin.disabled=working||state.locked||state.stale||state.stopWarning||!a?.app_configured;
        buttons.authorize.hidden=!pending;buttons.authorize.disabled=working||state.locked||state.stale||opened||a?.reason==='validating_authorization';buttons.authorize.textContent=opened?'Sign-in browser opened':'Open '+NAMES[platform]+' sign-in';
        buttons.cancel.hidden=!pending&&state.busy!=='begin';buttons.cancel.disabled=working&&!['begin','authorize'].includes(state.busy);
        buttons.check.disabled=working||state.locked;buttons.check.textContent=state.stale?'Retry connection check':'Check connection';buttons.disconnect.hidden=!a?.authorized&&!['authorization_refresh_required','authorization_rejected','account_identity_mismatch'].includes(a?.reason);buttons.disconnect.disabled=working||state.locked;
        buttons.setup.textContent=state.busy==='setup'?'Loading setup file…':'Load app setup file';buttons.setup.disabled=working||state.locked||state.stale||state.stopWarning||!a||a.authorized||pending||typeof api.importProviderApp!=='function';
        if(buttons.link){buttons.link.hidden=!a?.authorized||a.state!=='authorized'||!a.streaming_authorized||!a.account_ref;buttons.link.disabled=working||state.locked||state.stale||state.stopWarning;buttons.link.textContent=state.busy==='link'?'Saving Kick destination…':state.linkRetry?'Retry Save Kick destination':'Save Kick destination';}
        for(const button of Object.values(buttons))button.title=button.disabled?(state.locked?'Stop broadcasting or finish the current account action first.':working?'Wait for the current action to finish.':opened?'Finish sign-in in the browser already opened.':!a?.app_configured?SETUP[platform]:state.stale?'Check the connection and retry.':'Reopen the studio before reconnecting.'):'';
        buttons.setup.title=buttons.setup.disabled?(working?'Finish choosing the current setup file first.':state.locked?'Stop broadcasting or finish the current account action first.':a?.authorized||pending?'Disconnect or cancel sign-in before changing app setup.':state.stale?'Check connection before loading another setup file.':typeof api.importProviderApp!=='function'?'App setup file loading requires the updated desktop app.':'Reopen the studio before changing app setup.'):'Choose the provider app setup file. No path or credentials are entered here.';
        if(buttons.link&&!buttons.link.disabled)buttons.link.title='Save this channel as a destination. Start checks current Kick secure ingest and requires a separate confirmation. Platform receipt is unverified.';
        if(restoreSetupFocus&&!working){restoreSetupFocus=false;if(!buttons.begin.hidden&&!buttons.begin.disabled)buttons.begin.focus();else buttons.check.focus();}
        const busy=Boolean(state.busy&&state.busy!=='status');if(lastBusy!==busy){lastBusy=busy;onBusyChange(platform,busy);}
      }});
      for(const [action,button]of Object.entries(buttons))button.addEventListener('click',()=>controller.run(action));
      return {platform,controller,start:()=>controller.start(),close:()=>controller.close(),setLocked:value=>controller.setLocked(value),focus(){root.scrollIntoView({block:'start',behavior:'instant'});buttons.check.focus();}};
    }).filter(Boolean);
  }
  const api={normalize,createController,mount,SETUP};if(typeof module==='object'&&module.exports)module.exports=api;else host.ProducerProviderAccounts=api;
})(typeof window==='undefined'?globalThis:window);
