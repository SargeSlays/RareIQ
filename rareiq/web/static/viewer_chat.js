/* Producer-only viewer text. Backstage chat and Program output have separate owners. */
(function(host){
  'use strict';
  const PLATFORMS=Object.freeze({twitch:'Twitch',youtube:'YouTube',kick:'Kick'}),LIMIT=300;
  const ACCOUNT_REQUIRED=new Set(['credentials_required','authorization_rejected','chat_scope_required']);
  const isId=value=>Number.isSafeInteger(value)&&value>=0;
  const REPLY_REASONS={ready:'Ready to reply',chat_send_permission_required:'Permission to send chat is missing. Update this account’s permissions.',chat_not_connected:'Connect chat before replying.',chat_account_required:'Connect an account on this computer.',chat_target_unavailable:'The destination is unavailable. Check it before retrying.',chat_target_changed:'The destination changed. Check the intended broadcast.',chat_provider_rejected:'The platform rejected this reply.',chat_provider_rate_limited:'The platform is limiting replies. Wait before retrying.',chat_send_uncertain:'Delivery is unknown. Check the platform; this reply will not be resent.',chat_sent:'Sent',chat_storage_unavailable:'Reply status could not be saved. Check each platform before starting a new reply.',chat_receipt_capacity:'Reply receipt capacity reached. Nothing new was sent.',chat_request_conflict:'This reply request changed. Review your draft.',invalid_chat_reply:'Use 1–200 characters and choose a destination.',unavailable:'Reply permission could not be checked.'};
  const replyReason=reason=>reason==='rehearsal_active'?'Public replies are unavailable during Rehearsal.':REPLY_REASONS[reason]||REPLY_REASONS.unavailable;
  const validReplyText=text=>typeof text==='string'&&Boolean(text.trim())&&[...text].length<=200&&[...text].every(char=>{const code=char.codePointAt(0);return code>=32&&!(code>=127&&code<=159)&&!(code>=0xD800&&code<=0xDFFF);});
  function createReplyController(options={}){
    const fetcher=options.fetch||((...args)=>host.fetch(...args)),notify=options.onChange||(()=>{}),setTimer=options.setTimeout||host.setTimeout.bind(host),clearTimer=options.clearTimeout||host.clearTimeout.bind(host);
    let targets=[],checking=false,sending=false,receipt=null,pending=null,error='',destroyed=false,reader=null,writer=null,serial=0;const timers=new Set();
    const snapshot=()=>({targets:targets.map(t=>({...t})),checking,sending,receipt:receipt?JSON.parse(JSON.stringify(receipt)):null,pendingSignature:pending?.signature||'',error});
    const emit=()=>{if(!destroyed)notify(snapshot());};
    async function request(url,body,controller){const timeout=setTimer(()=>controller.abort(),15000);timers.add(timeout);try{const response=await fetcher(url,{credentials:'same-origin',cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),signal:controller.signal});const value=await response.json();if(!response.ok||value?.ok!==true)throw Error(replyReason(value?.reason));return value;}finally{clearTimer(timeout);timers.delete(timeout);}}
    return {snapshot,
      async refresh(){if(destroyed||checking||sending)return;checking=true;error='';reader=new host.AbortController();emit();try{const value=await request('/api/production/viewer-chat/reply-status',null,reader);if(destroyed)return;if(value.max_length!==200||!Array.isArray(value.targets)||value.targets.length!==3||new Set(value.targets.map(t=>t.platform)).size!==3||value.targets.some(t=>!Object.hasOwn(PLATFORMS,t.platform)||typeof t.ready!=='boolean'))throw Error('invalid_reply_status');targets=value.targets.map(t=>({platform:t.platform,ready:t.ready,reason:typeof t.reason==='string'?t.reason:'unavailable'}));}catch(_){if(!destroyed){targets=[];error=REPLY_REASONS.unavailable;}}finally{reader=null;checking=false;emit();}},
      async send(text,chosen,{retryFailed=false}={}){
        if(destroyed||sending||!validReplyText(text)||!Array.isArray(chosen)||!chosen.length||new Set(chosen).size!==chosen.length||chosen.some(p=>!Object.hasOwn(PLATFORMS,p)))return false;
        const selection=Object.keys(PLATFORMS).filter(p=>chosen.includes(p)),signature=JSON.stringify([text,selection]);
        if(!retryFailed&&pending&&pending.signature===signature&&receipt)return false;
        if(!retryFailed&&selection.some(p=>!targets.some(t=>t.platform===p&&t.ready)))return false;
        if(retryFailed&&(!pending||pending.signature!==signature||!receipt?.results.some(r=>r.state==='failed'&&r.retryable)))return false;
        if(!pending||pending.signature!==signature)pending={signature,request_id:host.crypto?.randomUUID?.()||'viewer-'+Date.now()+'-'+(++serial),text,targets:selection};
        const body={request_id:pending.request_id,text,targets:selection,...(retryFailed?{retry_failed:true}:{})};sending=true;error='';writer=new host.AbortController();emit();
        try{const value=await request('/api/production/viewer-chat/reply',body,writer);if(destroyed)return false;if(value.request_id!==body.request_id||!Array.isArray(value.results)||value.results.length!==selection.length||new Set(value.results.map(r=>r.platform)).size!==selection.length||value.results.some(r=>!selection.includes(r.platform)||!['sent','failed','uncertain'].includes(r.state)||typeof r.retryable!=='boolean'))throw Error('invalid_reply_receipt');receipt={request_id:value.request_id,results:value.results.map(r=>({platform:r.platform,state:r.state,reason:typeof r.reason==='string'?r.reason:'unavailable',retryable:r.state==='failed'&&r.retryable}))};if(receipt.results.every(r=>r.state==='sent'))pending=null;return true;}
        catch(_){if(!destroyed){receipt={request_id:body.request_id,results:selection.map(platform=>({platform,state:'uncertain',reason:'chat_send_uncertain',retryable:false}))};error=REPLY_REASONS.chat_send_uncertain;}return false;}
        finally{writer=null;sending=false;emit();}
      },
      destroy(){destroyed=true;reader?.abort();writer?.abort();for(const timer of timers)clearTimer(timer);timers.clear();},
    };
  }
  function connected(source){return source?.connected===true&&source.authorized===true&&source.verified===true&&source.state==='connected';}
  function connection(source={}){
    const name=PLATFORMS[source.platform]||'Platform',blocked=source.platform==='kick'&&!source.dashboard_registration_approved;
    const active=['connected','connecting','reconnecting','ready'].includes(source.state);
    let text;
    if(connected(source))text='Connected · waiting for new viewer messages';
    else if(source.state==='connecting')text='Connecting · checking permission';
    else if(source.state==='reconnecting')text='Reconnecting · new messages may be delayed';
    else {
      const reasons={credentials_required:'Account setup is missing. Connect this account in host settings first.',chat_scope_required:'Permission to read chat is missing. Update account permission on this computer.',authorization_rejected:'Account permission was rejected. Renew permission before reconnecting.',token_channel_or_client_mismatch:'The saved account does not match this channel. Check host account settings.',token_expiring:'Account permission is expiring. Renew it before reconnecting.',subscription_revoked:'Chat permission was revoked. Renew it before reconnecting.',channel_identity_mismatch:'The saved YouTube account does not own this channel.',no_active_chat:'No active YouTube live chat. Start the intended broadcast yourself before connecting.',multiple_active_chats:'More than one active YouTube chat. Choose one broadcast on this channel first.',chat_disabled:'Chat is disabled on this YouTube broadcast.',chat_ended:'This YouTube live chat ended. Reconnect when the next broadcast is active.',chat_unavailable:'This YouTube chat is unavailable. Check the intended broadcast.',provider_quota_exhausted:'YouTube message access has reached its allowance. Reconnect after it renews.',provider_rate_limited:'The platform is limiting requests. Wait before reconnecting.',connection_retry_limited:'Wait a few seconds before connecting again.',provider_unavailable:name+' could not be reached. Check the connection and retry.',provider_key_unavailable:'Kick message verification is unavailable. Retry after the platform recovers.',authorization_refresh_required:'Account permission needs rechecking. Reconnect from this computer.',waiting_for_verified_chat:'Permission checked · waiting for a verified Kick message.',local_operator_required:'Connect from the production host computer.',same_origin_required:'Open the studio directly on the production host computer.',dashboard_registration_approval_required:'Kick needs approved message delivery and host account setup.',approved_https_callback_required:'Kick needs approved secure message delivery before it can connect.',unavailable:'Connection status is unavailable. Refresh to check again.'};
      text=reasons[source.reason]||(['disconnected','not_connected'].includes(source.state)||source.reason==='explicit_connection_required'?'Disconnected · choose Connect when ready.':source.implemented===false?'Message connection is unavailable':'Connection is not confirmed. Refresh to check again.');
    }
    if(blocked)text='Setup required · Kick needs approved message delivery and host account setup.';
    return {name,text,active,blocked,healthy:connected(source),available:source.implemented===true};
  }
  function createFeed({now=()=>Date.now()/1000}={}){
    let messages=[],session='',cursor=0,active=false,filter='all',paused=false,unread=0;
    const recent=message=>typeof message.received_at==='number'&&Number.isFinite(message.received_at)&&message.received_at>now()-1200;
    function prune(){messages=messages.filter(recent);unread=Math.min(unread,messages.filter(m=>filter==='all'||m.platform===filter).length);}
    function clear(){messages=[];session='';cursor=0;active=false;paused=false;unread=0;}
    function apply(payload){
      if(!payload||typeof payload.active!=='boolean'||typeof payload.session_id!=='string'||!/^[a-f0-9]{32}$/.test(payload.session_id)||!Number.isSafeInteger(payload.cursor)||payload.cursor<0||!Array.isArray(payload.messages)||!Array.isArray(payload.sources))throw Error('invalid_response');
      const reset=payload.reset===true||payload.session_id!==session;
      if(!reset&&payload.cursor<cursor)throw Error('invalid_response');
      const valid=payload.messages.slice(-LIMIT).filter(m=>m&&isId(m.id)&&Object.hasOwn(PLATFORMS,m.platform)&&typeof m.text==='string'&&typeof m.display_name==='string'&&recent(m)).map(m=>({id:m.id,platform:m.platform,display_name:m.display_name.slice(0,100),text:m.text.slice(0,4096),occurred_at:m.occurred_at,received_at:m.received_at}));
      if(reset){messages=[];unread=0;paused=false;}
      if(!payload.active){clear();session=payload.session_id;cursor=payload.cursor;return {added:0,reset:true};}
      prune();const known=new Set(messages.map(m=>m.platform+':'+m.id)),added=[];
      for(const message of valid){const key=message.platform+':'+message.id;if(!known.has(key)){known.add(key);added.push(message);}}
      messages=[...messages,...added].slice(-LIMIT);session=payload.session_id;cursor=payload.cursor;active=true;
      if(paused)unread=Math.min(LIMIT,unread+added.filter(m=>filter==='all'||m.platform===filter).length);
      return {added:added.length,reset};
    }
    return {apply,clear,setFilter(next){filter=Object.hasOwn(PLATFORMS,next)?next:'all';unread=0;},setPaused(value){paused=Boolean(value);if(!paused)unread=0;},snapshot(){prune();return {messages:messages.filter(m=>filter==='all'||m.platform===filter),count:messages.length,session_id:session,cursor,active,filter,paused,unread};}};
  }
  function createController(options={}){
    const feed=createFeed({now:options.now}),fetcher=options.fetch||((...args)=>host.fetch(...args)),setTimer=options.setTimeout||host.setTimeout.bind(host),clearTimer=options.clearTimeout||host.clearTimeout.bind(host),notify=options.onChange||(()=>{});
    let generation=0,destroyed=false,timer=null,read=null,command=null,sources=[],busy=false,stale=false,locallyStopped=false,stopConfirmed=false,activityHistoryWarning=false,status='Loading viewer chat…';const timeouts=new Set();
    const snapshot=()=>({...feed.snapshot(),sources,busy,stale,activityHistoryWarning,status:status+(activityHistoryWarning?' Action completed, but its activity history could not be saved.':'')});
    const emit=()=>{if(!destroyed)notify(snapshot());};
    function invalidate(){generation++;clearTimer(timer);timer=null;read?.abort();read=null;for(const timeout of timeouts)clearTimer(timeout);timeouts.clear();}
    async function request(url,init={},controller=new host.AbortController()){
      const timeout=setTimer(()=>controller.abort(),init.method==='POST'?30000:10000);
      timeouts.add(timeout);
      try{const response=await fetcher(url,{credentials:'same-origin',cache:'no-store',...init,signal:controller.signal});const data=await response.json();if(!response.ok){const error=Error('request_failed');error.reason=typeof data?.reason==='string'?data.reason:'';throw error;}return data;}finally{clearTimer(timeout);timeouts.delete(timeout);}
    }
    function schedule(){clearTimer(timer);if(!destroyed)timer=setTimer(()=>refresh(false),2000);}
    async function refresh(explicit=true){
      if(destroyed||read||busy)return;if(explicit)activityHistoryWarning=false;clearTimer(timer);timer=null;
      const life=generation,controller=new host.AbortController();read=controller;
      const before=feed.snapshot(),query=new URLSearchParams({after:String(before.cursor)});if(before.session_id)query.set('session_id',before.session_id);
      try{
        const data=await request('/api/production/viewer-chat?'+query,{},controller);
        if(destroyed||life!==generation)return;
        feed.apply(locallyStopped?{...data,active:false,messages:[]}:data);sources=data.sources.filter(s=>s&&Object.hasOwn(PLATFORMS,s.platform));stale=locallyStopped&&data.active;
        status=stale?(stopConfirmed?'Messages cleared here. Viewer chat is active again. Choose Stop listening to stop it.':'Messages cleared here. Stopping could not be confirmed. Retry Stop listening.'):feed.snapshot().active?(sources.some(connected)?'Listening for new viewer messages.':'Listening is enabled. Connect a platform to receive viewer messages.'):'Viewer chat is stopped. Start listening or connect a platform.';emit();
      }catch(_){if(!destroyed&&life===generation){stale=true;status='Updates interrupted. Previous messages are kept. Retry to check the connection.';emit();}}
      finally{if(read===controller)read=null;if(!destroyed&&life===generation)schedule();}
    }
    async function run(kind,platform){
      if(destroyed||busy||!['start','stop','connect','disconnect'].includes(kind)||['connect','disconnect'].includes(kind)&&!Object.hasOwn(PLATFORMS,platform))return false;
      if(kind==='connect'&&platform==='kick'&&connection(sources.find(s=>s.platform==='kick')||{platform:'kick'}).blocked)return false;
      invalidate();const life=generation,controller=new host.AbortController();command=controller;busy=true;activityHistoryWarning=false;
      if(kind==='stop'){locallyStopped=true;stopConfirmed=false;feed.clear();status='Stopping viewer chat and clearing messages…';}
      else{if(kind==='start'||kind==='connect')locallyStopped=false;status=kind==='start'?'Starting viewer chat…':(kind==='connect'?'Connecting ':'Disconnecting ')+PLATFORMS[platform]+'…';}emit();
      let success=false,failure='',accountRequired=false;
      const post=(url,body)=>request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},controller);
      try{
        if(kind==='start'||kind==='stop'||kind==='connect'&&!feed.snapshot().active){const result=await post('/api/production/viewer-chat/listening',{enabled:kind!=='stop'});if(destroyed||life!==generation)return false;activityHistoryWarning=activityHistoryWarning||result?.activity_history_warning===true;if(kind==='stop')stopConfirmed=true;}
        if(kind==='connect'||kind==='disconnect'){const result=await post('/api/production/audience/'+platform+'/'+kind,{});if(destroyed||life!==generation)return false;activityHistoryWarning=activityHistoryWarning||result?.activity_history_warning===true;accountRequired=kind==='connect'&&['twitch','youtube'].includes(platform)&&ACCOUNT_REQUIRED.has(result?.reason);}
        if(destroyed||life!==generation)return false;
        success=true;
      }catch(error){if(!destroyed&&life===generation){accountRequired=kind==='connect'&&['twitch','youtube'].includes(platform)&&ACCOUNT_REQUIRED.has(error.reason);stale=true;failure=kind==='stop'?'Messages cleared here. Stopping could not be confirmed. Retry Stop listening.':kind==='connect'||kind==='disconnect'?connection({platform,implemented:true,reason:error.reason}).text:'Listening could not be confirmed. Retry to check the connection.';}}
      finally{
        if(command===controller)command=null;
        if(!destroyed&&life===generation){busy=false;await refresh(false);if(failure){stale=true;status=failure;emit();}}
      }
      if(accountRequired&&!destroyed&&life===generation){options.onAccountRequired?.(platform);return false;}return success;
    }
    return {snapshot,refresh,run,setFilter(value){feed.setFilter(value);emit();},setPaused(value){feed.setPaused(value);emit();},destroy(){if(destroyed)return;invalidate();command?.abort();command=null;feed.clear();sources=[];destroyed=true;},start(){emit();return refresh();}};
  }
  let serial=0;
  function mount(container,options={}){
    if(!container)return null;if(container._viewerChat)return container._viewerChat;
    const doc=container.ownerDocument||host.document,prefix='viewer-chat-'+(++serial),root=doc.createElement('section');root.className='production-viewer-chat';root.dataset.broadcastPanel='live';root.setAttribute('aria-label','Viewer chat');
    function node(tag,text,parent=root,attrs={}){const el=doc.createElement(tag);if(text)el.textContent=text;for(const [key,value]of Object.entries(attrs))el.setAttribute(key,value);parent.append(el);return el;}
    function icon(parent,platform){return node('span','',parent,{class:'viewer-chat-icon','data-chat-icon':platform,'aria-hidden':'true'});}
    const heading=node('header',''),title=node('h3','Viewer chat',heading),summary=node('span','Stopped',heading,{class:'viewer-chat-summary'});title.id=prefix+'-title';
    node('p','Twitch, YouTube and Kick viewers. Backstage guest conversations stay in Guests.',root,{class:'viewer-chat-note'});
    const actions=node('div','',root,{class:'viewer-chat-actions'}),start=node('button','Start listening',actions,{type:'button','data-viewer-start':''}),stop=node('button','Stop listening · Clear',actions,{type:'button','data-viewer-stop':''});
    const details=node('details','',root,{class:'viewer-chat-connections'});node('summary','Platform connections',details);const connections=node('div','',details,{'data-viewer-sources':''});
    const manageAccounts=node('button','Manage accounts',details,{type:'button','data-viewer-accounts':''});
    details.append(actions);
    const filters=node('div','',root,{class:'viewer-chat-filters',role:'group','aria-label':'Filter viewer messages'}),filterButtons=new Map();
    for(const [value,label]of Object.entries({all:'All',...PLATFORMS})){const b=node('button',label,filters,{type:'button','aria-pressed':String(value==='all'),'data-viewer-filter':value});if(value!=='all')icon(b,value);filterButtons.set(value,b);}
    const feedback=node('p','Loading viewer chat…',root,{role:'status','aria-live':'polite','aria-atomic':'true',class:'viewer-chat-status','data-viewer-status':''});
    const transcript=node('ol','',root,{class:'viewer-chat-messages','data-viewer-messages':'',tabindex:'0','aria-label':'Viewer messages','aria-live':'off'}),empty=node('p','Loading viewer chat…',root,{class:'viewer-chat-empty','data-viewer-empty':''});
    const latest=node('button','Return to latest',root,{type:'button',class:'viewer-chat-latest','data-viewer-latest':''});latest.hidden=true;
    const retry=node('button','Retry updates',root,{type:'button','data-viewer-retry':''});retry.hidden=true;
    const composer=node('form','',root,{class:'viewer-chat-composer','data-viewer-composer':''}),destinationLabel=node('label','Reply to',composer),destination=node('select','',destinationLabel,{'data-viewer-reply-target':'','aria-label':'Reply destination'});
    for(const [value,label]of Object.entries({all:'All ready chats',...PLATFORMS}))node('option',label,destination,{value});
    const recipientList=node('div','',composer,{class:'viewer-chat-recipients','data-viewer-reply-recipients':'','aria-label':'Reply recipients'});
    destination.value='all';const draftLabel=node('label','Message',composer),draft=node('textarea','',draftLabel,{'data-viewer-reply-text':'',rows:'3',maxlength:'400',placeholder:'Write a reply to viewers…','aria-describedby':prefix+'-reply-help'});
    draft.value='';const composerActions=node('div','',composer,{class:'viewer-chat-compose-actions'}),counter=node('span','0 / 200',composerActions,{'data-viewer-reply-count':''}),send=node('button','Send to All',composerActions,{type:'submit','data-viewer-reply-send':''}),retryReply=node('button','Retry failed destinations',composerActions,{type:'button','data-viewer-reply-retry':''});retryReply.hidden=true;
    const replyHelp=node('p','Checking reply permissions…',composer,{id:prefix+'-reply-help',class:'viewer-chat-note','data-viewer-reply-help':''}),checkReply=node('button','Check reply permissions',composer,{type:'button','data-viewer-reply-check':''}),enableReplies=node('button','Enable replies…',composer,{type:'button','data-viewer-enable-replies':''}),replyReceipt=node('div','',composer,{class:'viewer-chat-receipt',role:'status','aria-live':'polite','data-viewer-reply-receipt':''});enableReplies.hidden=true;
    node('p','Latest 300 messages, kept for up to 20 minutes. Stop listening clears this feed. Display names do not verify identity.',root,{class:'viewer-chat-note'});
    container.append(root);
    let previous=[],sourceStamp='',rendering=false,state=null,accountsDialog=null;
    const sourceRows=new Map(),local=['localhost','127.0.0.1','[::1]','::1'].includes(host.location?.hostname);
    const selectedTargets=(next=replies.snapshot())=>destination.value==='all'?Object.keys(PLATFORMS).filter(p=>next.targets.some(t=>t.platform===p&&t.ready)):[destination.value];
    function paintReply(next){
      const chosen=selectedTargets(next),excluded=destination.value==='all'?Object.keys(PLATFORMS).filter(p=>!chosen.includes(p)):chosen.filter(p=>!next.targets.some(t=>t.platform===p&&t.ready)),length=[...draft.value].length,sameDraft=next.pendingSignature===JSON.stringify([draft.value,chosen]);counter.textContent=length+' / 200';send.textContent=next.sending?'Sending…':destination.value==='all'?'Send to All ready chats':'Send to '+PLATFORMS[destination.value];send.disabled=!local||next.sending||next.checking||!chosen.length||destination.value!=='all'&&excluded.length>0||!validReplyText(draft.value)||Boolean(sameDraft&&next.receipt);draft.disabled=next.sending;destination.disabled=next.sending;checkReply.disabled=next.checking||next.sending;
      recipientList.replaceChildren();for(const platform of chosen){const chip=node('span',PLATFORMS[platform],recipientList,{class:'viewer-chat-platform'});icon(chip,platform);}
      const warning=!local?'Reply from the production host computer.':next.checking?'Checking reply permissions…':length>200?'Use no more than 200 characters.':draft.value&&!validReplyText(draft.value)?'Use one line of plain text without control characters.':(chosen.length?'Public reply to '+chosen.map(p=>PLATFORMS[p]).join(', ')+'. ':'No chat is ready to receive a reply. ')+(excluded.length?'Excluded — '+excluded.map(p=>PLATFORMS[p]+': '+replyReason(next.targets.find(t=>t.platform===p)?.reason)).join(' '):'Sending requires an explicit click.');replyHelp.textContent=next.error||warning;send.title=send.disabled?replyHelp.textContent:'Post this reply to the shown destinations.';
      retryReply.hidden=!next.receipt?.results.some(r=>r.state==='failed'&&r.retryable);retryReply.disabled=next.sending||!sameDraft;replyReceipt.replaceChildren();for(const item of next.receipt?.results||[]){const line=node('p',PLATFORMS[item.platform]+': '+(item.state==='sent'?'Sent':replyReason(item.reason)),replyReceipt);line.dataset.state=item.state;}
      enableReplies.hidden=!next.targets.some(t=>!t.ready&&['chat_send_permission_required','chat_account_required'].includes(t.reason));enableReplies.disabled=!local||next.sending||next.checking;enableReplies.title='Open account setup, then choose Enable replies for a platform. No sign-in or message starts automatically.';
    }
    const replies=createReplyController({...options,onChange:paintReply});
    enableReplies.addEventListener('click',async()=>{if(enableReplies.disabled)return;const desktop=options.desktop||host.producerDesktop||host.ProducerDesktop;if(typeof desktop?.openBroadcastSettings==='function'){enableReplies.disabled=true;try{const result=await desktop.openBroadcastSettings();if(result===false||result?.ok===false)throw Error('open_failed');node('p','Broadcast setup opened. Choose Enable replies on the intended platform and review consent. No message is sent by sign-in.',replyReceipt);}catch(_){node('p','Broadcast setup could not open. Use Output setup in this desktop studio, then choose Enable replies.',replyReceipt);}finally{enableReplies.disabled=false;}}else openAccounts(enableReplies);});
    draft.addEventListener('input',()=>paintReply(replies.snapshot()));destination.addEventListener('change',()=>paintReply(replies.snapshot()));checkReply.addEventListener('click',()=>replies.refresh());
    async function sendReply(retryFailed=false){const text=draft.value,chosen=selectedTargets();await replies.send(text,chosen,{retryFailed});if(replies.snapshot().receipt?.results.every(r=>r.state==='sent'))draft.value='';paintReply(replies.snapshot());}
    composer.addEventListener('submit',event=>{event.preventDefault();if(!send.disabled)return sendReply();});retryReply.addEventListener('click',()=>sendReply(true));
    manageAccounts.disabled=!local;manageAccounts.title=local?'Manage account permission for viewer chat.':'Use the production host computer to manage accounts.';
    function openAccounts(trigger=manageAccounts){
      const accounts=options.platformAccounts||host.ProducerPlatformAccounts;
      if(!local)return false;
      if(!accounts){feedback.textContent='Account sign-in is unavailable. Reload the studio to try again.';return false;}
      if(!accountsDialog)accountsDialog=accounts.mount(doc.body||root,{onUse:async platform=>{if(!await controller.run('connect',platform))throw Error('chat_connection_unconfirmed');}});
      accountsDialog.open(trigger);return true;
    }
    manageAccounts.addEventListener('click',()=>openAccounts());
    if(!local)node('p','Use the production host computer to connect or disconnect platforms.',details,{class:'viewer-chat-note'});
    for(const [platform,name]of Object.entries(PLATFORMS)){
      const row=node('article','',connections,{'data-viewer-platform':platform}),copy=node('div','',row),platformName=node('strong',name,copy);icon(platformName,platform);const note=node('p','Checking connection…',copy),button=node('button','Connect '+name,row,{type:'button','data-viewer-connect':platform});
      button.addEventListener('click',()=>controller.run(connection(state?.sources.find(s=>s.platform===platform)||{platform}).active?'disconnect':'connect',platform));sourceRows.set(platform,{row,note,button});
    }
    const controller=createController({...options,onAccountRequired(platform){openAccounts();options.onAccountRequired?.(platform);},onChange(next){
      state=next;rendering=true;
      const visible=next.messages,keys=visible.map(m=>m.platform+':'+m.id),same=keys.length===previous.length&&keys.every((key,index)=>key===previous[index]);
      const atEnd=transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight<64;
      if(!same){
        const oldRows=new Map(Array.from(transcript.children).map(row=>[row.dataset.viewerKey,row]));
        const rows=visible.map(message=>{
          const key=message.platform+':'+message.id;if(oldRows.has(key))return oldRows.get(key);
          const row=doc.createElement('li');row.dataset.viewerKey=key;row.dataset.platform=message.platform;const meta=node('div','',row,{class:'viewer-chat-meta'}),badge=node('span',PLATFORMS[message.platform],meta,{class:'viewer-chat-platform'});icon(badge,message.platform);node('strong',message.display_name||'Viewer',meta);
          const time=node('time','',meta),raw=message.occurred_at??message.received_at,date=new Date(typeof raw==='number'?raw*1000:raw);if(Number.isFinite(date.getTime())){time.dateTime=date.toISOString();time.textContent=date.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});}else time.textContent='Time unavailable';
          node('p',message.text,row);return row;
        });
        transcript.replaceChildren(...rows);previous=keys;
        if(!next.paused&&atEnd)transcript.scrollTop=transcript.scrollHeight;
      }
      const stamp=JSON.stringify([next.sources,next.stale]);
      if(stamp!==sourceStamp||next.busy){for(const [platform,{row,note,button}]of sourceRows){const source=next.sources.find(s=>s.platform===platform)||{platform,implemented:false},info=connection(source);row.dataset.health=next.stale?'stale':info.healthy?'connected':'disconnected';note.textContent=(next.stale?'Last known: ':'')+info.text;button.textContent=info.blocked?'Kick setup required':(info.active?'Disconnect ':'Connect ')+info.name;button.disabled=next.busy||!local||info.blocked||!info.available;button.title=!local?'Use the production host computer to manage connections.':info.blocked?info.text:!info.available?'Message connection is unavailable.':info.active?'Stop observing this platform.':'Use the account permission already saved on this computer.';}sourceStamp=stamp;}
      // A completed command must restore source controls even if status is unchanged.
      if(!next.busy)for(const [platform,{button}]of sourceRows){const info=connection(next.sources.find(s=>s.platform===platform)||{platform,implemented:false});button.disabled=!local||info.blocked||!info.available;}
      root.setAttribute('aria-busy',String(next.busy));summary.textContent=next.stale?'Updates interrupted':next.active?'Listening · '+next.sources.filter(connected).length+' connected':'Stopped';summary.dataset.state=next.stale||next.activityHistoryWarning?'warning':next.active?'connected':'stopped';
      start.hidden=next.active;start.disabled=next.busy;stop.disabled=next.busy;stop.title=next.active?'Stop viewer chat and clear messages.':'Clear messages and confirm viewer chat is stopped.';
      for(const [value,button]of filterButtons)button.setAttribute('aria-pressed',String(value===next.filter));
      if(feedback.textContent!==next.status)feedback.textContent=next.status;retry.hidden=!next.stale;retry.disabled=next.busy;
      empty.hidden=visible.length>0;empty.textContent=!next.active?'Start listening or connect a platform to receive new messages.':next.filter!=='all'?'No '+PLATFORMS[next.filter]+' messages in this feed yet.':'Waiting for new viewer messages. Check platform connections above.';
      latest.hidden=!next.paused;latest.textContent=next.unread?next.unread+' new · Return to latest':'Return to latest';rendering=false;
      options.onChange?.(next);
    }});
    start.addEventListener('click',()=>controller.run('start'));stop.addEventListener('click',()=>controller.run('stop'));retry.addEventListener('click',()=>controller.refresh());
    for(const [value,button]of filterButtons)button.addEventListener('click',()=>{controller.setFilter(value);controller.setPaused(false);transcript.scrollTop=transcript.scrollHeight;});
    transcript.addEventListener('scroll',()=>{if(rendering)return;const paused=transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight>=64;if(paused!==state?.paused)controller.setPaused(paused);});
    latest.addEventListener('click',()=>{controller.setPaused(false);transcript.scrollTop=transcript.scrollHeight;transcript.focus();});
    const teardown=()=>api.destroy(),api={element:root,controller,replies,destroy(){controller.destroy();replies.destroy();accountsDialog?.destroy();host.removeEventListener?.('pagehide',teardown);root.remove();delete container._viewerChat;}};
    container._viewerChat=api;host.addEventListener?.('pagehide',teardown,{once:true});replies.refresh();controller.start();return api;
  }
  const exported={mount,createFeed,createController,createReplyController,connection,connected,replyReason,LIMIT};
  if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerViewerChat=exported;
})(typeof window==='undefined'?globalThis:window);
