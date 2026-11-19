/* Public provider metadata only. Main binds saved drafts and owns authorization. */
(() => {
  'use strict';
  const PLATFORMS=Object.freeze({twitch:'Twitch',youtube:'YouTube',kick:'Kick'});
  const bounded=(value,limit=160)=>typeof value==='string'?value.replace(/[\x00-\x1f\x7f]/g,' ').slice(0,limit):'';
  function create({root,api,onBusy=()=>{},onChange=()=>{},onPermission=()=>{}}){
    if(!root)return null;
    const node=name=>root.querySelector('#streamMetadata'+name);
    const account=node('Account'),status=node('Status'),check=node('Check'),permission=node('Permission'),apply=node('Apply'),broadcast=node('Broadcast'),category=node('Category'),query=node('Query'),search=node('Search');
    let destination=null,revision=null,locked=false,publishingBlocked=false,dirty=true,info=null,loading='',mutating=false,closed=false,generation=0,pending=null,outcome='',message='',lastNotification='';
    const supported=()=>Boolean(PLATFORMS[destination?.platform]);
    const busy=()=>Boolean(loading)||mutating;
    const editable=()=>info?.authorized===true&&info?.editable===true&&Boolean(bounded(info.channel_id,128));
    const needsBroadcast=()=>destination?.platform==='youtube';
    const boundBroadcast=()=>needsBroadcast()&&destination.linkedAccount===true?destination.youtubeBroadcastId:null;
    const hasCategory=()=>Boolean(info?.capabilities?.category_id||info?.capabilities?.category);
    const blocked=()=>closed||locked||busy()||!supported();
    function applyBlocker(){
      if(publishingBlocked)return 'Public channel updates are blocked in rehearsal or until production status is confirmed. Connection and category checks remain available.';
      if(locked)return 'Stop broadcasting or finish the current action before updating stream info.';
      if(busy())return 'Wait for the current stream info action to finish.';
      if(!supported())return 'Choose a Twitch, YouTube or Kick destination.';
      if(dirty||!Number.isSafeInteger(revision))return 'Save your local stream info draft before updating the channel.';
      if(!info)return 'Check the connected account before updating.';
      if(!editable())return 'Enable stream info editing and check the connection before updating.';
      if(boundBroadcast()&&broadcast.value!==boundBroadcast())return 'This destination can only update its saved YouTube broadcast. Check the connection again.';
      if(needsBroadcast()&&!broadcast.value)return 'Choose the YouTube broadcast to update.';
      if(needsBroadcast()&&info.broadcast_id!==broadcast.value)return 'Check connection to confirm the selected YouTube broadcast before updating.';
      return '';
    }
    function render(){
      if(closed)return;
      const disabled=blocked(),why=applyBlocker(),name=PLATFORMS[destination?.platform],channel=bounded(info?.public_label)||bounded(info?.channel_id,128);
      account.textContent=channel?`${name} · ${channel}`:supported()?`${name}: connected channel not confirmed.`:'Choose a Twitch, YouTube or Kick destination for direct updates.';
      node('BroadcastRow').hidden=!needsBroadcast();node('CategoryRow').hidden=!hasCategory();
      node('BroadcastHint').textContent=boundBroadcast()?'This destination uses the YouTube broadcast reviewed when it was saved. Choose another destination to update a different broadcast.':'Choose an existing broadcast explicitly. This does not create a broadcast or start streaming.';
      check.disabled=disabled;check.title=locked?'Finish the current action before checking.':!supported()?'Choose a supported destination.':'';
      permission.hidden=!supported()||editable();permission.disabled=disabled;permission.title=locked?'Finish the current action before requesting permission.':'Review the platform’s additional editing permission. Existing read-only access remains useful.';
      const hasBroadcasts=broadcast.children.length>1;
      broadcast.disabled=disabled||Boolean(boundBroadcast())||!hasBroadcasts;broadcast.title=boundBroadcast()?'This destination uses the broadcast reviewed when it was saved.':!hasBroadcasts?'No available existing broadcasts were returned. Check the connection again.':'';
      query.disabled=disabled||!editable();search.disabled=disabled||!editable();category.disabled=disabled||!editable();
      for(const control of [query,search,category])control.title=disabled?'Finish the current action before selecting a category.':!editable()?'Enable stream info editing first.':'';
      apply.disabled=Boolean(why);apply.title=why;apply.textContent=loading==='apply'?'Applying…':pending&&outcome==='unconfirmed'?'Retry same update':name?`Apply to ${name}`:'Apply stream info';
      const capabilities=info?.capabilities||{},fields=['title','description','tags'].filter(key=>capabilities[key]);
      node('Fields').textContent=info?`Applies your saved ${fields.length?fields.join(', '):'supported details'}${hasCategory()?' and the category selected here':''}. ${capabilities.description?'':'Description stays local. '}${capabilities.tags?'':'Tag notes stay local. '}This does not start a broadcast.`:'Save your local draft before applying its supported fields.';
      status.dataset.state=outcome||loading||'ready';
      const contextBlock=!busy()&&(publishingBlocked||locked||dirty||!Number.isSafeInteger(revision));
      status.textContent=contextBlock?`${outcome==='unconfirmed'?'The previous update remains unconfirmed. ':''}${why}`:message||(why||'Ready to update the connected channel from your saved draft.');
      root.dataset.busy=String(busy());const value={busy:mutating,state:outcome||loading||'ready'},signature=JSON.stringify(value);if(signature!==lastNotification){lastNotification=signature;onChange(value);}
    }
    function option(select,value,label){const existing=[...select.children].find(item=>item.value===value);if(existing){existing.textContent=bounded(label,200);return;}const item=root.ownerDocument.createElement('option');item.value=value;item.textContent=bounded(label,200);select.append(item);}
    function resetCategories(){category.replaceChildren();option(category,'','Leave current category unchanged');category.value='';query.value='';}
    function resetBroadcasts(){broadcast.replaceChildren();if(boundBroadcast()){option(broadcast,boundBroadcast(),'Saved YouTube broadcast');broadcast.value=boundBroadcast();}else{option(broadcast,'','Choose a broadcast…');broadcast.value='';}}
    function payload(action,extra={}){return {action,platform:destination.platform,...extra};}
    function inspectionMessage(result){
      if(['provider_unavailable','provider_rate_limited','invalid_provider_response'].includes(result?.reason))return 'The saved account could not be verified with the platform. Your saved sign-in is kept. Retry Check connection.';
      if(result?.reason==='account_storage_unavailable')return 'Protected account storage could not be opened. Your saved sign-in is kept. Check local storage, then retry Check connection.';
      if(result?.reason==='app_setup_required')return 'Complete the platform app setup in Connected accounts below, then enable stream info editing.';
      if(!result?.authorized)return 'Connect your account or finish the platform permission review, then check connection.';
      if(!result?.editable)return 'Your account is connected. Existing read-only access remains available; enable stream info editing to update public details.';
      if(needsBroadcast()&&!broadcast.value)return broadcast.children.length>1?'Choose the existing YouTube broadcast you intend to update.':'No available YouTube broadcasts were returned. Create or schedule one on YouTube, then check connection.';
      return 'Connection checked. Confirm the connected account, then update its supported details from your saved draft.';
    }
    function failure(value){
      const reason=typeof value==='string'?value:value?.reason||value?.code||value?.message||'';
      const messages={
        app_setup_required:'Complete the platform app setup in Connected accounts below, then try again.',
        authorization_required:'Connect or reconnect the platform account below, then check connection.',
        stream_info_scope_required:'Editing permission is required. Enable stream info editing, review the platform permission request, then check connection.',
        metadata_scope_required:'Editing permission is required. Enable stream info editing, review the platform permission request, then check connection.',
        broadcast_selection_required:'Choose an existing YouTube broadcast before updating.',
        broadcast_selection_changed:'This destination’s saved YouTube broadcast changed. Reload the destination and check the connection before updating.',
        account_identity_mismatch:'The connected channel changed. Check connection and confirm the intended account before updating.',
        category_not_found:'The selected category is no longer available. Find and select an official category again.',
        category_query_too_short:'Enter at least '+(destination?.platform==='kick'?'three':'two')+' characters to find a category.',
        stream_info_revision_conflict:'Saved stream info changed. Reload the local draft, then review the update again.',
        request_id_conflict:'This update request no longer matches the saved details. Check connection and review the update again.',
        unsupported_metadata_field:'This platform cannot apply one of the selected fields. Review its supported fields and try again.',
        invalid_metadata:'Check your saved title, description and tags against the platform’s requirements, then save and try again.',
        invalid_title:'Check the saved title against the platform’s requirements, then save and try again.',
        invalid_description:'Check the saved description against the platform’s requirements, then save and try again.',
        invalid_tags:'Check the saved tags against the platform’s requirements, then save and try again.',
        metadata_precondition_required:'YouTube did not return a safe current version. Check the connection and try again; no update was sent.',
        metadata_recovery_storage_invalid:'Update recovery tracking could not load. Your draft is kept; check local storage before retrying.',
        metadata_recovery_storage_unavailable:'Update recovery tracking could not be saved. Your draft is kept; check local storage and retry.',
        invalid_category_id:'Find and select an official platform category again.',
        invalid_channel_id:'Check connection to confirm the channel before updating.',
        invalid_request_id:'Check connection and review the update again.'
      };
      const key=Object.keys(messages).find(item=>reason===item||reason.endsWith('_'+item));
      return key?{key,message:messages[key]}:null;
    }
    async function inspect(){
      if(blocked())return false;
      const token=++generation;loading='inspect';message='Checking the connected account and editing permission…';render();
      try{
        const extra=broadcast.value?{broadcastId:broadcast.value}:{},result=await api.streamMetadata(payload('inspect',extra));
        if(closed||token!==generation)return false;
        if(!result||result.platform!==destination.platform){const known=failure(result);message=known?.message||'The connection could not be checked. Try again.';info=null;return false;}
        info=result;const chosen=broadcast.value;
        if(Array.isArray(result.broadcasts)){
          resetBroadcasts();
          for(const item of result.broadcasts.slice(0,100))if(bounded(item?.id,128)&&(!boundBroadcast()||item.id===boundBroadcast()))option(broadcast,bounded(item.id,128),`${bounded(item.title,160)||'Untitled broadcast'}${item.state?' · '+bounded(item.state,30):''}`);
          broadcast.value=[...broadcast.children].some(item=>item.value===chosen)?chosen:'';
        }else if(needsBroadcast()){
          if(result.authorized!==true||result.editable!==true)resetBroadcasts();
          else if(!chosen||result.broadcast_id!==chosen)broadcast.value='';
        }
        if(!outcome)message=(result.ok===false?failure(result)?.message:'')||inspectionMessage(result);
        else if(outcome==='unconfirmed')message='The previous update is still unconfirmed. Checking the connection does not confirm that write. Retry the same update to reconcile it.';
        return true;
      }catch(error){if(!closed&&token===generation){info=null;message=outcome==='unconfirmed'?'The update remains unconfirmed and the connection could not be checked. Check connection again, then retry the same update.':failure(error)?.message||'The connection could not be checked. Your local draft is kept. Retry Check connection.';}return false;}
      finally{if(token===generation){loading='';render();}}
    }
    async function categories(){
      if(blocked()||!editable()||!hasCategory())return false;
      const token=++generation,selected=category.value;loading='categories';message='Finding official platform categories…';render();
      try{
        const result=await api.streamMetadata(payload('categories',{query:bounded(query.value,100)}));if(closed||token!==generation)return false;
        if(result?.ok===false){message=failure(result)?.message||'Categories could not load. Try again; the selected category and local draft are kept.';return false;}
        const previous=[...category.children].find(item=>item.value===selected);category.replaceChildren();option(category,'','Leave current category unchanged');
        const values=(Array.isArray(result?.categories)?result.categories:[]).slice(0,100);for(const item of values)if(bounded(item?.id,128))option(category,bounded(item.id,128),bounded(item.name,160));
        if(selected&&!values.some(item=>item.id===selected)&&previous)option(category,selected,previous.textContent);
        category.value=selected;message=values.length?'Choose an official category, or leave the current category unchanged.':'No matching categories were returned. Try another search or leave the current category unchanged.';return true;
      }catch(error){if(token===generation)message=failure(error)?.message||'Categories could not load. Try again; the selected category and local draft are kept.';return false;}
      finally{if(token===generation){loading='';render();}}
    }
    async function mutate(action){
      if(blocked()||(action==='apply'&&applyBlocker()))return false;
      if(action==='apply'&&!pending){pending=payload('apply',{destinationId:destination.id,revision,channelId:bounded(info.channel_id,128),requestId:crypto.randomUUID()});if(broadcast.value)pending.broadcastId=broadcast.value;if(category.value)pending.categoryId=category.value;}
      const token=++generation,request=action==='apply'?{...pending}:payload('permission');loading=action;mutating=true;message=action==='apply'?'Updating the connected channel from your saved draft…':'Opening the account permission review…';render();onBusy(true);
      try{
        const result=await api.streamMetadata(request);if(closed||token!==generation)return false;
        if(action==='permission'){info=null;if(!result?.ok){message=failure(result)?.message||'Editing permission could not open. Check Connected accounts below and try again.';return false;}message='Review the editing permission in the platform account sign-in below. Return here and choose Check connection when finished.';onPermission(destination.platform);return true;}
        if(result?.state==='cancelled'){outcome='cancelled';message='Update cancelled. No platform change was requested.';pending=null;return false;}
        if(result?.state==='applied'&&result.request_id===pending.requestId){outcome='applied';message='Updated connected channel. The platform readback confirmed the supported details. This does not start a broadcast.'+(result.activity_history_warning?' Local activity history could not be written.':'')+(result.recovery_storage_warning?' Restart recovery tracking could not be saved; check the channel again after reopening.':'');pending=null;return true;}
        if(result?.state==='failed'||result?.ok===false){const known=failure(result);if(known){outcome='failed';message=known.message;pending=null;if(['stream_info_scope_required','metadata_scope_required','account_identity_mismatch','authorization_required'].includes(known.key))info=null;return false;}}
        outcome='unconfirmed';message='Update not confirmed. Your saved draft is kept. Retry the same update to check its result before sending another update.';return false;
      }catch(error){if(!closed&&token===generation){const known=failure(error);if(action==='apply'){outcome=known?'failed':'unconfirmed';message=known?.message||'Update could not be confirmed. Your saved draft is kept. Retry the same update to reconcile it.';if(known){pending=null;if(['stream_info_scope_required','metadata_scope_required','account_identity_mismatch','authorization_required'].includes(known.key))info=null;}}else message=known?.message||'Editing permission could not open. Check Connected accounts below and try again.';}return false;}
      finally{if(mutating){mutating=false;onBusy(false);}if(token===generation){loading='';render();}}
    }
    function changed(){pending=null;outcome='';message='';render();}
    category.addEventListener('change',()=>{if(blocked())return;changed();});
    broadcast.addEventListener('change',()=>{if(blocked())return;changed();info=null;resetCategories();inspect();});
    check.addEventListener('click',inspect);search.addEventListener('click',categories);permission.addEventListener('click',()=>mutate('permission'));apply.addEventListener('click',()=>mutate('apply'));
    query.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();categories();}});
    function setContext(value={}){
      if(closed)return;
      const next=Object.hasOwn(value,'destination')?value.destination:destination,nextRevision=Object.hasOwn(value,'revision')?value.revision:revision;
      const targetChanged=next?.id!==destination?.id||next?.platform!==destination?.platform||next?.youtubeBroadcastId!==destination?.youtubeBroadcastId,revisionChanged=nextRevision!==revision;
      destination=next&&typeof next.id==='string'?{id:next.id,name:bounded(next.name),platform:next.platform,...(next.platform==='youtube'&&next.linkedAccount===true&&typeof next.youtubeBroadcastId==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(next.youtubeBroadcastId)?{linkedAccount:true,youtubeBroadcastId:next.youtubeBroadcastId}:{})}:null;revision=nextRevision;
      if(typeof value.locked==='boolean')locked=value.locked;if(typeof value.publishingBlocked==='boolean')publishingBlocked=value.publishingBlocked;if(typeof value.dirty==='boolean')dirty=value.dirty;
      if(targetChanged){++generation;loading='';info=null;pending=null;outcome='';message='';resetBroadcasts();resetCategories();}
      else if(revisionChanged){pending=null;outcome='';message='';}
      render();if(targetChanged&&supported()&&!locked&&!mutating)inspect();
    }
    function close(){closed=true;++generation;loading='';if(mutating){mutating=false;onBusy(false);}}
    resetCategories();resetBroadcasts();render();return {setContext,close};
  }
  window.ProducerStreamMetadata=Object.freeze({create});
})();
