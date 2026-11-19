/* Producer-only viewer text. Backstage chat and Program output have separate owners. */
(function(host){
  'use strict';
  const PLATFORMS=Object.freeze({twitch:'Twitch',youtube:'YouTube',kick:'Kick'}),LIMIT=300;
  const ACCOUNT_REQUIRED=new Set(['credentials_required','authorization_rejected','chat_scope_required']);
  const isId=value=>Number.isSafeInteger(value)&&value>=0;
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
    const heading=node('header',''),title=node('h3','Viewer chat',heading),summary=node('span','Stopped',heading,{class:'viewer-chat-summary'});title.id=prefix+'-title';
    node('p','Twitch, YouTube and Kick viewers. Backstage guest conversations stay in Guests.',root,{class:'viewer-chat-note'});
    const actions=node('div','',root,{class:'viewer-chat-actions'}),start=node('button','Start listening',actions,{type:'button','data-viewer-start':''}),stop=node('button','Stop listening · Clear',actions,{type:'button','data-viewer-stop':''});
    const details=node('details','',root,{class:'viewer-chat-connections'});node('summary','Platform connections',details);const connections=node('div','',details,{'data-viewer-sources':''});
    const manageAccounts=node('button','Manage accounts',details,{type:'button','data-viewer-accounts':''});
    const filters=node('div','',root,{class:'viewer-chat-filters',role:'group','aria-label':'Filter viewer messages'}),filterButtons=new Map();
    for(const [value,label]of Object.entries({all:'All',...PLATFORMS})){const b=node('button',label,filters,{type:'button','aria-pressed':String(value==='all'),'data-viewer-filter':value});filterButtons.set(value,b);}
    const feedback=node('p','Loading viewer chat…',root,{role:'status','aria-live':'polite','aria-atomic':'true',class:'viewer-chat-status','data-viewer-status':''});
    const transcript=node('ol','',root,{class:'viewer-chat-messages','data-viewer-messages':'',tabindex:'0','aria-label':'Viewer messages','aria-live':'off'}),empty=node('p','Loading viewer chat…',root,{class:'viewer-chat-empty','data-viewer-empty':''});
    const latest=node('button','Return to latest',root,{type:'button',class:'viewer-chat-latest','data-viewer-latest':''});latest.hidden=true;
    const retry=node('button','Retry updates',root,{type:'button','data-viewer-retry':''});retry.hidden=true;
    node('p','Read-only viewer chat · latest 300 messages, kept for up to 20 minutes. Stop listening clears this feed. Display names do not verify identity.',root,{class:'viewer-chat-note'});
    container.append(root);
    let previous=[],sourceStamp='',rendering=false,state=null,accountsDialog=null;
    const sourceRows=new Map(),local=['localhost','127.0.0.1','[::1]','::1'].includes(host.location?.hostname);
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
      const row=node('article','',connections,{'data-viewer-platform':platform}),copy=node('div','',row);node('strong',name,copy);const note=node('p','Checking connection…',copy),button=node('button','Connect '+name,row,{type:'button','data-viewer-connect':platform});
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
          const row=doc.createElement('li');row.dataset.viewerKey=key;const meta=node('div','',row,{class:'viewer-chat-meta'});node('span',PLATFORMS[message.platform],meta,{class:'viewer-chat-platform'});node('strong',message.display_name||'Viewer',meta);
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
    const teardown=()=>api.destroy(),api={element:root,controller,destroy(){controller.destroy();accountsDialog?.destroy();host.removeEventListener?.('pagehide',teardown);root.remove();delete container._viewerChat;}};
    container._viewerChat=api;host.addEventListener?.('pagehide',teardown,{once:true});controller.start();return api;
  }
  const exported={mount,createFeed,createController,connection,connected,LIMIT};
  if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerViewerChat=exported;
})(typeof window==='undefined'?globalThis:window);
