/* Backstage text only. No media capture, Program output or persistent credentials. */
(function(host){
  'use strict';
  let sequence=0;
  function mount(container,options={}){
    if(!container)return null;
    if(container._greenroomChat)return container._greenroomChat;
    const doc=container.ownerDocument||host.document,role=options.role==='guest'?'guest':'producer',prefix='greenroom-chat-'+(++sequence);
    const fetcher=options.fetch||((...args)=>host.fetch(...args));
    const root=doc.createElement('section');root.className='greenroom-chat';root.setAttribute('aria-label','Backstage chat');
    function node(tag,text,parent=root,attr={}){const el=doc.createElement(tag);if(text)el.textContent=text;for(const [key,value]of Object.entries(attr))el.setAttribute(key,value);parent.append(el);return el;}
    const heading=node('header',''),title=node('h3','Backstage chat',heading);title.id=prefix+'-title';
    node('span','Off Program',heading,{class:'greenroom-chat-tag'});
    const controls=node('div','',root,{class:'greenroom-chat-controls'}),channelLabel=node('label','Conversation',controls);
    const channel=node('select','',channelLabel,{'data-chat-channel':'','aria-label':'Chat conversation'});
    node('option','Shared backstage',channel,{value:'room'});node('option',role==='guest'?'Private · production team':'Private · guest + production team',channel,{value:'private'});
    const recipientLabel=node('label','Guest',controls),recipient=node('select','',recipientLabel,{'data-chat-recipient':'','aria-label':'Private chat guest'});recipientLabel.hidden=true;
    const audience=node('p','',root,{class:'greenroom-chat-audience',id:prefix+'-audience'});
    const transcript=node('ol','',root,{'data-chat-messages':'',class:'greenroom-chat-messages','aria-label':'Chat messages',tabindex:'0'});
    const empty=node('p','No messages in this conversation yet.',root,{class:'greenroom-chat-empty'});
    const newMessages=node('button','Show new messages',root,{type:'button',class:'riq-button greenroom-chat-new','data-chat-new':''});newMessages.hidden=true;
    const form=node('form','',root,{class:'greenroom-chat-compose'}),inputLabel=node('label','Message',form,{for:prefix+'-input'});
    const input=node('textarea','',form,{id:prefix+'-input','data-chat-input':'',maxlength:'1000',rows:'3','aria-describedby':prefix+'-audience '+prefix+'-status',placeholder:'Write a backstage message…'});
    const footer=node('div','',form,{class:'greenroom-chat-compose-footer'}),counter=node('span','0 / 1,000',footer,{'data-chat-count':''});
    const send=node('button','Send',footer,{type:'submit',class:'riq-button primary','data-chat-send':''});
    const status=node('p','',root,{id:prefix+'-status','data-chat-status':'',role:'status','aria-live':'polite',class:'greenroom-chat-status'});
    node('p','Guest names are display names, not verified identities. Chat stays backstage and is never sent to Program.',root,{class:'greenroom-chat-note'});
    const announcement=node('span','',root,{class:'greenroom-chat-announcement',role:'status','aria-live':'polite','aria-atomic':'true'});
    container.append(root);
    let state={roomId:'',token:'',participantId:'',participants:[],active:false},destroyed=false,session=0,scope=0,timer=null,readPending=false,readController=null,sendController=null,sending=false;
    let selected='room',target='',shown=new Set(),initial=true,notice='',drafts=new Map(),halted=false,sendNotice='';
    const key=()=>selected==='room'?'room':'private:'+target;
    const draft=()=>{const k=key();if(!drafts.has(k)){if(drafts.size>=16)drafts.delete(drafts.keys().next().value);drafts.set(k,{text:'',request:null});}return drafts.get(k);};
    const ready=()=>state.active&&!halted&&(role==='producer'||Boolean(state.token))&&(selected==='room'||role==='guest'||Boolean(target));
    const setStatus=text=>{if(status.textContent!==text)status.textContent=text;};
    function controlsState(){
      const d=draft(),available=ready(),canSend=available&&Boolean(state.roomId);
      audience.textContent=selected==='room'?'Shared with every guest in this room and the production team.':role==='guest'?'Private between you and the entire production team. Other guests cannot read this conversation.':target?'Private between '+(state.participants.find(p=>p.id===target)?.name||'this guest')+' and the entire production team. Other guests cannot read it.':'Choose a guest. Private messages are visible to that guest and the entire production team.';
      recipientLabel.hidden=role==='guest'||selected!=='private';
      input.disabled=!canSend;input.readOnly=Boolean(d.request)||sending;
      inputLabel.textContent=selected==='room'?'Message to shared backstage':role==='guest'?'Message to production team':'Message to selected guest + production team';
      counter.textContent=input.value.length+' / 1,000';send.disabled=!canSend||sending||!input.value.trim();
      send.textContent=sending?'Sending…':d.request?'Retry same message':'Send';send.setAttribute('aria-busy',String(sending));
      send.title=!available?notice||'Select an available conversation.':!state.roomId?'Loading the room before sending.':!input.value.trim()?'Write a message first.':d.request?'Retries the same message without creating a duplicate.':'';
      if(!available)setStatus(notice||(!state.active?(role==='guest'?'Join backstage to chat with the room or privately with the production team.':'Open the room to use backstage chat.'):'Choose a guest for a private conversation.'));
      else if(d.request&&!sending)setStatus(sendNotice||'Delivery could not be confirmed. Retry the same message; your draft is kept and duplicates are prevented.');
    }
    function clearTranscript(){shown=new Set();initial=true;transcript.replaceChildren();empty.hidden=false;newMessages.hidden=true;announcement.textContent='';}
    function schedule(delay=1500){host.clearTimeout(timer);if(!destroyed&&ready())timer=host.setTimeout(poll,delay);}
    function switchConversation(){scope++;readController?.abort();host.clearTimeout(timer);selected=channel.value==='private'?'private':'room';target=recipient.value||'';clearTranscript();input.value=draft().text;notice='';sendNotice='';setStatus(ready()?'Loading conversation…':'');controlsState();schedule(0);}
    const terminalErrors=new Set(['room_closed','chat_room_conflict','invalid_guest_session','guest_unavailable','access_revoked','guest_access_ended']);
    const errors={chat_rate_limited:'Too many messages. Wait a minute, then retry. Your draft is kept.',chat_rate_limit:'Too many messages. Wait a minute, then retry. Your draft is kept.',chat_text_invalid:'Use a message between 1 and 1,000 characters.',invalid_chat_text:'Use a message between 1 and 1,000 characters.',chat_request_conflict:'This message could not be accepted. Review your draft and try again.',room_closed:'The room is closed. Chat is unavailable.',invalid_guest_session:'Your invitation is no longer active. Ask the producer for a new invitation.',guest_unavailable:'This guest is no longer available for chat.',access_revoked:'Chat access ended. Reopen the studio with authorized access.',guest_access_ended:'Your invitation is no longer active. Ask the producer for a new invitation.'};
    errors.chat_room_conflict='The room changed. Previous chat and drafts have been cleared; wait for the current room or rejoin with a new invitation.';
    function fail(error){
      if(terminalErrors.has(error.message)){
        if(role==='producer'&&error.message==='guest_unavailable'){drafts.delete(key());target='';recipient.value='';scope++;clearTranscript();input.value='';notice=errors[error.message];}
        else{halted=true;drafts.clear();input.value='';scope++;clearTranscript();notice=errors[error.message];}
      }
      setStatus(errors[error.message]||'Chat could not refresh. Check the connection; your draft is kept.');controlsState();
    }
    async function request(url,init,controller){
      const timeout=host.setTimeout(()=>controller.abort(),10000);
      try{
        const response=await fetcher(url,{credentials:'same-origin',cache:'no-store',...init,signal:controller.signal,headers:{...(role==='guest'?{Authorization:'Bearer '+state.token}:{}),...(init.headers||{})}});
        const result=await response.json();
        if(!response.ok||result?.ok===false){const error=Error(/^[a-z0-9_]{1,80}$/.test(result?.reason||'')?result.reason:'chat_unavailable');error.uncertain=response.status>=500;throw error;}
        return result;
      }catch(error){if(error.uncertain===undefined)error.uncertain=true;throw error;}
      finally{host.clearTimeout(timeout);}
    }
    function renderMessages(messages){
      const atEnd=transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight<64,previous=shown;
      const valid=messages.slice(-100).filter(m=>Number.isInteger(m.id)&&m.channel===selected&&(selected==='room'?m.participant_id==null:m.participant_id===(role==='guest'?state.participantId:target))&&typeof m.text==='string');
      const ids=new Set(valid.map(m=>m.id)),added=valid.filter(m=>!previous.has(m.id));
      for(const row of Array.from(transcript.children))if(!ids.has(Number(row.dataset.messageId)))row.remove();
      for(const message of added){
        const row=node('li','',transcript,{'data-message-id':String(message.id)}),meta=node('div','',row,{class:'greenroom-chat-meta'});
        node('strong',String(message.author_name||'Guest').slice(0,60),meta);node('span',message.author_kind==='guest'?'Guest · display name':message.identity_verified===true?'Production · verified identity':'Production · identity not verified',meta);
        const time=node('time','',meta),date=new Date(Number(message.created_at)*1000);if(Number.isFinite(date.getTime())){time.dateTime=date.toISOString();time.textContent=date.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});}else time.textContent='Time unavailable';
        node('p',message.text,row);
      }
      shown=ids;empty.hidden=valid.length>0;
      if(initial||atEnd){transcript.scrollTop=transcript.scrollHeight;newMessages.hidden=true;}
      else if(added.length)newMessages.hidden=false;
      if(!initial&&added.length)announcement.textContent=added.length===1?'New backstage message.':added.length+' new backstage messages.';
      initial=false;
    }
    async function poll(){
      if(destroyed||!ready())return;if(readPending){schedule();return;}
      const version=scope,life=session,room=state.roomId,conversation=selected,person=role==='guest'?state.participantId:target;
      const controller=new host.AbortController();readController=controller;readPending=true;
      const query=new URLSearchParams({channel:conversation});if(room)query.set('room_id',room);if(role==='producer'&&conversation==='private')query.set('participant_id',person);
      try{
        const result=await request((role==='guest'?'/guest/chat':'/api/production/greenroom/chat')+'?'+query,{},controller);
        if(destroyed||version!==scope||life!==session)return;
        if(!result.room_id||room&&result.room_id!==room||result.channel!==conversation||conversation==='private'&&result.participant_id!==person||!Array.isArray(result.messages))throw Error('chat_response_invalid');
        state.roomId=result.room_id;renderMessages(result.messages);
        if(!sending&&!draft().request)setStatus(sendNotice||'Messages stay backstage. Enter adds a new line; Ctrl or ⌘ + Enter sends.');controlsState();
      }catch(error){if(!destroyed&&version===scope&&life===session)fail(error);}
      finally{readPending=false;if(readController===controller)readController=null;schedule();}
    }
    function requestId(){if(!host.crypto?.getRandomValues)throw Error('chat_random_unavailable');const bytes=new Uint8Array(20);host.crypto.getRandomValues(bytes);return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}
    async function submit(event){
      event?.preventDefault();if(!ready()||!state.roomId||sending||!input.value.trim())return;
      const d=draft(),version=scope,life=session,wasFocused=doc.activeElement,conversation=selected,person=target;
      d.text=input.value;try{if(!d.request)d.request={room_id:state.roomId,channel:conversation,text:d.text,request_id:requestId(),...(role==='producer'&&conversation==='private'?{participant_id:person}:{})};}catch(_){setStatus('Secure message creation is unavailable. Reopen this page in a supported browser.');return;}
      const controller=new host.AbortController();sendController=controller;sending=true;setStatus('Sending message…');controlsState();
      try{
        const result=await request(role==='guest'?'/guest/chat':'/api/production/greenroom/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d.request)},controller);
        if(destroyed||life!==session)return;
        if(result.room_id!==d.request.room_id||!Number.isInteger(result.message?.id)){const error=Error('chat_response_invalid');error.uncertain=true;throw error;}
        d.text='';d.request=null;
        if(version===scope){input.value='';sendNotice='Message sent.';setStatus(sendNotice);}
      }catch(error){if(!destroyed&&life===session){if(!error.uncertain)d.request=null;if(version===scope){if(terminalErrors.has(error.message))fail(error);else{sendNotice=error.uncertain?'Delivery could not be confirmed. Retry the same message; your draft is kept and duplicates are prevented.':errors[error.message]||'Message was not sent. Your draft is kept; try again.';setStatus(sendNotice);}}}}
      finally{
        if(sendController===controller)sendController=null;
        if(!destroyed&&life===session){sending=false;controlsState();if(version===scope&&wasFocused===send&&doc.activeElement===doc.body&&!input.disabled)input.focus();schedule(0);}
      }
    }
    channel.addEventListener('change',switchConversation);recipient.addEventListener('change',switchConversation);form.addEventListener('submit',submit);
    input.addEventListener('input',()=>{draft().text=input.value;sendNotice='';controlsState();});
    input.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();submit();}});
    newMessages.addEventListener('click',()=>{transcript.scrollTop=transcript.scrollHeight;newMessages.hidden=true;transcript.focus();});
    transcript.addEventListener('scroll',()=>{if(transcript.scrollHeight-transcript.scrollTop-transcript.clientHeight<64)newMessages.hidden=true;});
    function reset(message){session++;scope++;host.clearTimeout(timer);readController?.abort();sendController?.abort();drafts.clear();sending=false;target='';recipient.value='';selected='room';channel.value='room';input.value='';clearTranscript();notice=message||'';sendNotice='';}
    function update(next={}){
      if(destroyed)return;
      const upcoming={...state,...next},identityChanged=upcoming.token!==state.token||upcoming.participantId!==state.participantId||Boolean(state.roomId&&upcoming.roomId!==state.roomId);
      if(identityChanged||state.active&&!upcoming.active){reset();halted=false;}
      if(!state.active&&upcoming.active){halted=false;notice='';}
      state=upcoming;
      const people=(Array.isArray(state.participants)?state.participants:[]).filter(p=>['waiting','admitted'].includes(p.state)&&!p.expired).slice(0,16);
      if(role==='producer'){
        const stamp=JSON.stringify(people.map(p=>[p.id,p.name]));
        if(recipient.dataset.stamp!==stamp){recipient.dataset.stamp=stamp;recipient.replaceChildren();node('option','Choose a guest',recipient,{value:''});for(const person of people)node('option',String(person.name||'Guest').slice(0,60)+' · display name',recipient,{value:person.id});recipient.value=people.some(p=>p.id===target)?target:'';
          for(const k of drafts.keys())if(k.startsWith('private:')&&!people.some(p=>'private:'+p.id===k))drafts.delete(k);
          if(target&&!recipient.value){target='';scope++;readController?.abort();clearTranscript();input.value='';notice='That guest is no longer available. Choose another guest.';}
        }
      }
      controlsState();if(ready()&&!readPending)schedule(0);
    }
    const api={element:root,update,clear(message){reset(message);state={...state,active:false,token:'',roomId:'',participantId:''};halted=false;controlsState();},destroy(){if(destroyed)return;reset();destroyed=true;state={};root.remove();delete container._greenroomChat;}};
    container._greenroomChat=api;update(options);return api;
  }
  const exported={mount};if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerGreenroomChat=exported;
})(typeof window==='undefined'?globalThis:window);
