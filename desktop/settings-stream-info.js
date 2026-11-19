/* Local preparation only. No provider metadata mutation is exposed here. */
(() => {
  'use strict';
  const DASHBOARDS=Object.freeze({twitch:'https://dashboard.twitch.tv/',youtube:'https://studio.youtube.com/',kick:'https://dashboard.kick.com/'});
  const clone=value=>JSON.parse(JSON.stringify(value));
  const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  function normalize(value){
    if(!plain(value)||!Number.isSafeInteger(value.revision)||value.revision<0||!plain(value.shared)||!plain(value.overrides))throw Error('invalid_stream_info');
    const text=(input,limit)=>{if(typeof input!=='string'||input.length>limit||/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(input))throw Error('invalid_stream_info');return input;};
    const result={revision:value.revision,shared:{title:text(value.shared.title,100),description:text(value.shared.description,5000)},overrides:{}};
    for(const [id,item] of Object.entries(value.overrides)){
      if(!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id)||!plain(item))throw Error('invalid_stream_info');
      result.overrides[id]={title:text(item.title,100),description:text(item.description,5000),category:text(item.category,100),tags:text(item.tags,300)};
    }
    return result;
  }
  function create({root,api,onBusy=()=>{},onChange=()=>{},onContext=()=>{}}){
    if(!root)return null;
    const node=id=>root.querySelector('#streamInfo'+id),sharedTitle=node('SharedTitle'),sharedDescription=node('SharedDescription'),picker=node('Destination'),customize=node('Customize'),override=node('Override'),saveButton=node('Save'),reloadButton=node('Reload'),dashboardButton=node('Dashboard'),status=node('Status'),badge=node('Badge');
    const fields={title:node('Title'),description:node('Description'),category:node('Category'),tags:node('Tags')};
    let saved=null,draft=null,destinations=[],selected='',locked=false,busy=false,saving=false,closed=false,pending=null,conflict=false,uncertain=false,loadError=false,message='Loading local drafts…',operation=0,lastNotification='';
    const dirty=()=>Boolean(saved&&draft&&JSON.stringify(saved)!==JSON.stringify(draft));
    const ready=()=>Boolean(saved)&&!loadError&&!uncertain&&!conflict;
    const notify=()=>{const state={dirty:dirty(),busy,ready:ready(),loaded:Boolean(saved),conflict},signature=JSON.stringify(state);root.dataset.dirty=String(state.dirty);if(signature!==lastNotification){lastNotification=signature;onChange(state);}};
    const blocked=()=>closed||locked||busy||!draft;
    function render(){
      if(closed)return;
      const disabled=blocked(),item=destinations.find(value=>value.id===selected),custom=Boolean(draft?.overrides[selected]),url=DASHBOARDS[item?.platform];
      for(const input of [sharedTitle,sharedDescription,...Object.values(fields)]){input.disabled=disabled;input.title=locked?'Stop the broadcast or wait for the current action before editing.':busy?'Wait for the current stream info action to finish.':!draft?'Load saved details before editing.':'';}
      picker.disabled=disabled||!destinations.length;customize.disabled=disabled||!item;customize.checked=custom;override.hidden=!custom;
      saveButton.disabled=disabled||!dirty()||conflict;saveButton.textContent=pending?'Retry save':'Save stream info';saveButton.title=conflict?'Reload saved details to resolve the newer saved version.':disabled?'Wait until stream info editing is available.':!dirty()?'There are no unsaved stream info changes.':'';
      reloadButton.disabled=locked||busy;reloadButton.textContent=dirty()?'Discard draft and reload saved details':'Reload saved details';reloadButton.title=locked?'Stop the broadcast or wait for the current action before reloading.':'';
      dashboardButton.disabled=disabled||!url;dashboardButton.title=!url?'This destination has no supported dashboard shortcut. Open its platform dashboard yourself.':disabled?'Wait until the current action finishes.':'';
      node('DashboardHint').textContent=!item?'Save a destination to open its dashboard.':url?'Optional shortcut. Apply supported fields to the connected account above.':'Direct updates are available for Twitch, YouTube and Kick. Open this platform’s dashboard for its stream info.';
      node('DestinationHint').textContent=!item?'Save a destination to customize its details.':custom?'This destination uses its own saved copy of the details.':'This destination uses the shared title and description.';
      badge.textContent=busy?'Working…':uncertain||conflict?'Check saved details':dirty()?'Unsaved changes':saved?'Saved locally':'Local drafts';status.textContent=message;notify();
      onContext({destination:item||null,locked:disabled,dirty:!ready()||dirty(),revision:saved?.revision||0});
    }
    function showFields(){
      if(!draft)return;
      sharedTitle.value=draft.shared.title;sharedDescription.value=draft.shared.description;
      const values=draft.overrides[selected]||{...draft.shared,category:'',tags:''};
      for(const [name,input]of Object.entries(fields))input.value=values[name];
    }
    function changed(){pending=null;message=conflict?'A newer saved version is available. Your draft is kept. Copy any details you need, then choose Discard draft and reload saved details.':uncertain?'The previous save is unconfirmed. Reload saved details before starting, or save your updated draft.':'Unsaved changes. Save your draft before applying it to the connected account.';render();}
    for(const [name,input]of [['title',sharedTitle],['description',sharedDescription]])input.addEventListener('input',()=>{if(blocked())return;draft.shared[name]=input.value;changed();});
    for(const [name,input]of Object.entries(fields))input.addEventListener('input',()=>{if(blocked()||!draft.overrides[selected])return;draft.overrides[selected][name]=input.value;changed();});
    picker.addEventListener('change',()=>{if(blocked()){picker.value=selected;return;}selected=picker.value;showFields();render();});
    customize.addEventListener('change',()=>{if(blocked()||!destinations.some(item=>item.id===selected))return;if(customize.checked)draft.overrides[selected]={...draft.shared,category:'',tags:''};else delete draft.overrides[selected];showFields();changed();});
    async function load(){
      if(closed||locked||busy)return false;
      const generation=++operation;busy=true;message='Loading saved local details…';render();
      try{
        const result=normalize(await api.streamInfo());if(generation!==operation)return false;
        saved=result;draft=clone(result);pending=null;conflict=false;uncertain=false;loadError=false;showFields();message='Saved locally. Apply supported fields to the connected account below.';return true;
      }catch(_){loadError=true;message='Saved details could not load. Your current draft is kept. Retry loading when ready.';return false;}
      finally{busy=false;render();}
    }
    async function save(){
      if(blocked()||!dirty()||conflict)return false;
      try{normalize(draft);}catch(_){message='Check the text lengths and remove unsupported control characters before saving.';render();return false;}
      if(!pending)pending={requestId:crypto.randomUUID(),revision:saved.revision,shared:clone(draft.shared),overrides:clone(draft.overrides)};
      const generation=++operation;busy=true;saving=true;onBusy(true);message='Saving on this computer…';render();
      try{
        const response=await api.saveStreamInfo(clone(pending));if(closed||generation!==operation)return false;const result=normalize(response);saved=result;draft=clone(result);pending=null;conflict=false;uncertain=false;loadError=false;showFields();message=response.activity_history_warning?'Saved locally. Local activity history could not be written. Apply supported fields to the connected account below.':'Saved locally. Apply supported fields to the connected account below.';return true;
      }catch(error){
        const code=error?.code||error?.message||'';conflict=/revision_conflict|stale_revision/.test(code);uncertain=!conflict;
        message=conflict?'A newer saved version is available. Your draft is kept. Copy any details you need, then choose Discard draft and reload saved details.':'Save could not be confirmed. Your draft is kept. Retry save to confirm the same details.';return false;
      }finally{busy=false;if(saving){saving=false;onBusy(false);}render();}
    }
    saveButton.addEventListener('click',save);reloadButton.addEventListener('click',load);
    dashboardButton.addEventListener('click',async()=>{
      if(blocked())return;const url=DASHBOARDS[destinations.find(item=>item.id===selected)?.platform];if(!url)return;
      busy=true;render();try{await api.openPlatform(url);message='Dashboard opened. Update and confirm your details there; this app has not updated the platform.';}catch(_){message='The dashboard could not open. Open it yourself; your local draft is kept.';}finally{busy=false;render();}
    });
    function setContext(value={}){
      if(closed)return;
      if(Array.isArray(value.destinations)){
        const next=value.destinations.filter(item=>item&&typeof item.id==='string'&&typeof item.name==='string').map(({id,name,platform})=>({id,name,platform}));
        if(JSON.stringify(next)!==JSON.stringify(destinations)||!picker.children.length){
          destinations=next;if(!destinations.some(item=>item.id===selected))selected=destinations[0]?.id||'';
          const options=destinations.length?destinations:[{id:'',name:'No saved destinations'}];picker.replaceChildren();
          for(const item of options){const option=root.ownerDocument.createElement('option');option.value=item.id;option.textContent=item.name;picker.append(option);}picker.value=selected;showFields();
        }
      }
      if(typeof value.locked==='boolean')locked=value.locked;render();
    }
    render();
    function close(){closed=true;++operation;busy=false;if(saving){saving=false;onBusy(false);}}
    return {load,save,setContext,close,isDirty:dirty,get dirty(){return dirty();},get busy(){return busy;},get ready(){return ready();},get loaded(){return Boolean(saved);},get conflict(){return conflict;}};
  }
  window.ProducerStreamInfo=Object.freeze({create});
})();
