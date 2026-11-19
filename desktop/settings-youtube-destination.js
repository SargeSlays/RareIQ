/* Existing YouTube broadcasts only. Native Main reviews and stores the binding. */
(function(host){
  'use strict';
  const hex=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
  const id=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value);
  const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  const ERRORS={
    account_authorization_required:'Check your saved YouTube connection before choosing a broadcast.',
    authorization_rejected:'YouTube did not accept this saved connection. Check or reconnect the account.',
    account_identity_mismatch:'Check the connected YouTube channel, then reload the broadcast list.',
    authorization_required:'Connect your YouTube channel first.',
    authorization_refresh_required:'Check your saved YouTube connection, then try again.',
    streaming_scope_required:'Your saved YouTube connection needs the streaming read permission.',
    account_state_changed:'The connected account changed. Check the connection and choose the broadcast again.',
    youtube_selection_changed:'This broadcast changed. Reload the list and review it again.',
    selection_changed:'This broadcast changed. Reload the list and review it again.',
    broadcast_selection_changed:'This broadcast changed. Reload the list and review it again.',
    secure_ingest_unavailable:'A secure YouTube streaming address is unavailable for this broadcast.',
    streaming_not_available:'YouTube streaming is unavailable for this broadcast. Reload and choose another.',
    provider_unavailable:'YouTube could not be reached. Check your connection and retry.',
    destination_request_conflict:'This save request changed. Review the broadcast again before saving.',
    destination_request_retired:'This save request expired. Review the broadcast again before saving.',
    destination_broadcast_busy:'Stop broadcasting or finish the current action before changing destinations.',
    youtube_broadcast_unavailable:'This broadcast cannot be used. Reload the list and choose another.',
    youtube_broadcast_not_owned:'This broadcast no longer belongs to the connected channel. Check the account and reload.',
    youtube_stream_unavailable:'The broadcast needs an available, dedicated YouTube stream. Reload and choose another.',
    youtube_stream_not_owned:'This stream does not belong to the connected channel. Reload and choose another.',
    broadcast_selection_limit:'There are too many broadcasts to check safely. Use a dedicated stream and try again.',
    youtube_stream_shared:'This stream is shared with another broadcast. Choose a dedicated broadcast.'
  };
  const DEFINITIVE_LINK_ERRORS=new Set(['destination_request_conflict','destination_request_retired','youtube_selection_changed','selection_changed','broadcast_selection_changed','account_state_changed','youtube_broadcast_unavailable','youtube_broadcast_not_owned','youtube_stream_unavailable','youtube_stream_not_owned','youtube_stream_shared','secure_ingest_unavailable','streaming_not_available','authorization_rejected','account_identity_mismatch','streaming_scope_required','broadcast_selection_limit']);
  function selection(raw){
    if(!plain(raw)||!hex(raw.account_ref)||!id(raw.broadcast_id)||!id(raw.stream_id)||!hex(raw.settings_fingerprint)||!['public','unlisted','private'].includes(raw.privacy_status)||typeof raw.auto_start!=='boolean'||typeof raw.auto_stop!=='boolean'||typeof raw.title!=='string'||!raw.title.trim()||raw.title.length>300||/[\x00-\x1f\x7f]/.test(raw.title))throw Error('invalid_selection');
    return {account_ref:raw.account_ref,broadcast_id:raw.broadcast_id,stream_id:raw.stream_id,settings_fingerprint:raw.settings_fingerprint,privacy_status:raw.privacy_status,auto_start:raw.auto_start,auto_stop:raw.auto_stop,title:raw.title};
  }
  function createController({request,onChange=()=>{},onSaved=async()=>{},onBusy=()=>{},randomId=()=>crypto.randomUUID()}={}){
    if(typeof request!=='function')throw Error('native_selection_unavailable');
    let state={authorized:false,accountRef:null,locked:false,busy:'',items:[],selectedId:'',review:null,open:false,uncertain:false,message:'Connect YouTube to choose an existing broadcast.'},closed=false,epoch=0,pending=null;
    const snapshot=()=>({...state,items:state.items.map(item=>({...item})),review:state.review?{...state.review}:null,retry:Boolean(pending)}),emit=()=>onChange(snapshot());
    const clear=()=>{state.items=[];state.selectedId='';state.review=null;state.open=false;state.uncertain=false;pending=null;};
    function setAccount(value){
      const a=value?.account,ref=a?.account_ref,ready=!value?.stale&&!value?.stopWarning&&a?.state==='authorized'&&a.authorized===true&&a.streaming_authorized===true&&hex(ref);
      const confirmedLoss=Boolean(a&&!value?.stale&&(a.state==='not_authorized'||a.authorized===false));
      if((hex(ref)&&state.accountRef!==ref)||confirmedLoss&&state.accountRef!==null){
        ++epoch;clear();state.busy='';onBusy(false);state.accountRef=hex(ref)&&!confirmedLoss?ref:null;
        state.message=ready?'Choose an existing broadcast already connected to its YouTube stream.':'Connect and check your YouTube channel to choose an existing broadcast.';
      }
      state.authorized=ready;emit();
    }
    function choose(value){if(closed||state.busy||state.locked||state.uncertain||!state.items.some(item=>item.broadcast_id===value))return false;state.selectedId=value;state.review=null;pending=null;state.message='Review this broadcast before saving it.';emit();return true;}
    async function run(action){
      if(closed||state.busy||state.locked||!state.authorized||!['list','inspect','link'].includes(action))return false;
      if(state.uncertain&&action!=='link')return false;
      if(action==='inspect'&&(!state.selectedId||state.uncertain))return false;
      if(action==='link'&&(!state.review||state.review.broadcast_id!==state.selectedId))return false;
      const own=++epoch,account=state.accountRef;
      const payload=action==='list'?{action}:action==='inspect'?{action,broadcastId:state.selectedId}:pending||(pending={action,broadcastId:state.review.broadcast_id,expectedFingerprint:state.review.settings_fingerprint,requestId:randomId()});
      if(action==='list'){clear();state.open=true;}
      if(action==='inspect'){state.review=null;pending=null;}
      state.busy=action;state.message=action==='list'?'Loading your existing broadcasts…':action==='inspect'?'Checking this broadcast and its streaming settings…':'Saving your YouTube destination…';onBusy(true);emit();
      try{
        const result=await request({...payload});if(closed||own!==epoch||state.accountRef!==account)return false;
        if(!plain(result)||result.ok!==true){
          if(action==='link'&&!DEFINITIVE_LINK_ERRORS.has(result?.reason)){state.uncertain=true;state.message='Save could not be confirmed. Retry the same save before choosing another broadcast.';}
          else{if(action==='link'){pending=null;state.review=null;}state.message=ERRORS[result?.reason]||'This broadcast could not be checked. Reload the list and try again.';}
          return false;
        }
        if(action==='list'){
          if(result.platform!=='youtube'||result.account_ref!==account||!Array.isArray(result.broadcasts)||result.broadcasts.length>100)throw Error('invalid_list');
          const items=result.broadcasts.map(selection);if(items.some(item=>item.account_ref!==account)||new Set(items.map(item=>item.broadcast_id)).size!==items.length)throw Error('invalid_list');
          state.items=items;state.selectedId=items[0]?.broadcast_id||'';state.message=items.length?'Choose a broadcast, then review its streaming settings.':'No eligible broadcasts were found. Create a broadcast with a dedicated bound stream in YouTube first, then reload. Nothing was created or started here.';
        }else if(action==='inspect'){
          const review=selection(result.selection);if(review.account_ref!==account||review.broadcast_id!==payload.broadcastId)throw Error('changed_selection');
          state.review=review;pending=null;state.uncertain=false;state.message='Review when this broadcast goes live, then save the destination. Saving sends no media.';
        }else{
          pending=null;state.uncertain=false;state.message='YouTube destination saved. Start will check the broadcast again and ask for confirmation before sending media.';
          if(result.activity_history_warning===true)state.message+=' Local activity history could not be written.';
          try{await onSaved();}catch(_){if(!closed&&own===epoch)state.message+=' Reopen setup to refresh the destination list.';}
        }
        return true;
      }catch(_){
        if(!closed&&own===epoch){state.uncertain=action==='link';if(action!=='link')state.review=null;state.message=action==='link'?'Save could not be confirmed. Retry the same save before choosing another broadcast.':'YouTube could not be checked. Reload the list and retry.';}return false;
      }finally{if(!closed&&own===epoch){state.busy='';onBusy(false);emit();}}
    }
    return {run,choose,setAccount,snapshot,setLocked(value){state.locked=value===true;emit();},close(){closed=true;++epoch;state.busy='';onBusy(false);},focus(){}};
  }
  function mount({root,api=host.producerSettings,onBusy=()=>{},onSaved=async()=>{}}={}){
    if(!root||typeof api?.youtubeDestinations!=='function')return null;
    const node=name=>root.querySelector('[data-youtube-'+name+']');
    const controller=createController({request:value=>api.youtubeDestinations(value),onSaved,onBusy,onChange(state){
      const working=Boolean(state.busy),blocked=!state.authorized||working||state.locked;root.setAttribute('aria-busy',String(working));node('status').textContent=state.message;node('panel').hidden=!state.open;
      node('load').disabled=blocked||state.uncertain;node('load').textContent=state.busy==='list'?'Loading broadcasts…':state.open?'Reload broadcasts':'Choose existing broadcast';
      const picker=node('select'),previous=picker.value;picker.replaceChildren();for(const item of state.items){const option=root.ownerDocument.createElement('option');option.value=item.broadcast_id;option.textContent=item.title;picker.append(option);}picker.value=state.selectedId||previous;
      picker.disabled=blocked||state.uncertain||!state.items.length;node('inspect').disabled=blocked||state.uncertain||!state.selectedId;node('inspect').textContent=state.busy==='inspect'?'Checking broadcast…':'Review broadcast';
      node('review').hidden=!state.review;if(state.review){node('title').textContent=state.review.title;node('privacy').textContent=({public:'Public — anyone can watch.',unlisted:'Unlisted — anyone with the link can watch.',private:'Private — only the YouTube viewers you allow can watch.'})[state.review.privacy_status];node('publish').textContent=state.review.auto_start?'YouTube publishes automatically when media arrives if this broadcast is not already live.':'YouTube requires a separate Go Live action if this broadcast is not already live. Confirm its status in YouTube Studio.';node('stop').textContent=state.review.auto_stop?'YouTube auto-stop is enabled. It may end this broadcast when media stops; confirm its final status in YouTube Studio.':'Stopping media does not automatically end the broadcast in YouTube Studio.';}
      node('save').disabled=blocked||!state.review;node('save').textContent=state.busy==='link'?'Saving destination…':state.uncertain?'Retry Save YouTube destination':'Save YouTube destination';
      for(const button of root.querySelectorAll('button'))button.title=button.disabled?state.locked?'Stop broadcasting or finish the current action first.':working?'Wait for this action to finish.':!state.authorized?'Connect and check your YouTube account first.':state.uncertain?'Retry the same save to confirm the result.':'Choose and review a broadcast first.':'';
    }});
    node('load').addEventListener('click',()=>controller.run('list'));node('select').addEventListener('change',event=>controller.choose(event.target.value));node('inspect').addEventListener('click',()=>controller.run('inspect'));node('save').addEventListener('click',()=>controller.run('link'));
    return controller;
  }
  const api={selection,createController,mount};if(typeof module==='object'&&module.exports)module.exports=api;else host.ProducerYouTubeDestination=api;
})(typeof window==='undefined'?globalThis:window);
