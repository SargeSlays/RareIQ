/* Producer-only guest decisions. Joining a room never takes a source to Program. */
(function(host){
  'use strict';
  let instance=null,pendingSwitcher=null;
  const emptyTracks=()=>({microphone:null,camera:null,screen:null,screen_audio:null});
  const cameraId=value=>typeof value==='string'&&/^camera:[1-4]$/.test(value)?Number(value.slice(7)):null;
  function sourceAvailable(source,switcher,room){
    if(typeof source==='string'&&/^(video|text):/.test(source))return Boolean(host.ProducerMediaLibrary?.sourceId(source)&&(switcher.production_sources||[]).some(asset=>asset.id===source));
    if(typeof source==='string'&&source.startsWith('image:'))return Boolean(host.ProducerImageLibrary?.imageId(source)&&(switcher.image_sources||[]).some(asset=>asset.id===source));
    const camera=cameraId(source);
    if(camera){const slot=(switcher.slots||[]).find(item=>Number(item.slot_id)===camera);return Boolean(slot?.source_id&&slot.connected&&slot.production_readiness?.ready===true);}
    const person=(room.participants||[]).find(item=>Object.values(item.sources||{}).includes(source));
    if(!person||person.state!=='admitted'||!person.connected)return false;
    const kind=Object.keys(person.sources).find(key=>person.sources[key]===source);
    return person.media?.[kind==='audio'?'microphone':kind]===true;
  }
  function previewSources(switcher){return Array.isArray(switcher.preview_sources)?switcher.preview_sources:[`camera:${Number(switcher.preview_slot)||2}`];}
  function programSources(switcher){return Array.isArray(switcher.program_sources)?switcher.program_sources:[`camera:${Number(switcher.program_slot)||1}`];}
  function togglePreview(source,switcher,room){
    const current=previewSources(switcher).filter(value=>sourceAvailable(value,switcher,room));
    if(current.includes(source))return current.filter(value=>value!==source);
    if(!sourceAvailable(source,switcher,room))throw Error('source_unavailable');
    if(current.length>=6)throw Error('preview_source_limit');
    return [...current,source];
  }
  function takeReadiness(switcher,room){
    const sources=previewSources(switcher),program=programSources(switcher),layout=switcher.preview_layout||'auto';
    if(!sources.length)return {ready:false,message:'Add a ready source to Preview first.'};
    if(sources.some(source=>!sourceAvailable(source,switcher,room)))return {ready:false,message:'A Preview source is unavailable. Remove it or reconnect the guest.'};
    const output=room.output||switcher.guest_output||{},guests=sources.filter(source=>/^(guest|image|video|text):/.test(source));
    const groups=Object.prototype.hasOwnProperty.call(output,'ready_groups')?output.ready_groups:[output.ready_sources||[]];
    if(guests.length&&(!output.connected||!Array.isArray(groups)||!groups.some(group=>Array.isArray(group)&&guests.every(source=>group.includes(source)))))return {ready:false,message:sources.some(source=>/^(image|video|text):/.test(source))?'Waiting for one Studio Output to load every Preview source. If media cannot load or its codec is unsupported, remove it and import another file.':'Waiting for one Studio Output to receive every Preview guest feed.'};
    if(JSON.stringify(sources)===JSON.stringify(program)&&layout===(switcher.program_layout||'auto'))return {ready:false,message:'This composition is already on Program.'};
    return {ready:true,message:'Preview is ready to take to Program.'};
  }
  function randomHex(bytes=20){const values=new Uint8Array(bytes);if(!host.crypto?.getRandomValues)throw Error('secure_random_unavailable');host.crypto.getRandomValues(values);return Array.from(values,value=>value.toString(16).padStart(2,'0')).join('');}
  function invitationLink(value){
    try{
      const url=new URL(value);
      if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.pathname!=='/guest'||url.search||!/^#invite=[a-f0-9]{64}$/.test(url.hash))return null;
      const local=['localhost','127.0.0.1','[::1]'].includes(url.hostname.toLowerCase());
      return {url:url.href,local,hint:local?'Local test link — opens on this computer only. Create a separate invitation for each guest.':'Private, single-use invitation. Send it only to this guest; create a separate invitation for each person.'};
    }catch(_){return null;}
  }
  function programAudioChange(person,kind){
    if(!['microphone','screen'].includes(kind))throw Error('invalid_audio_kind');
    const body={action:'program_audio',microphone_muted:person.program_audio?.microphone_muted===true,screen_muted:person.program_audio?.screen_muted===true};
    body[kind+'_muted']=!body[kind+'_muted'];return body;
  }
  function activityEntry(event,participants=[]){
    const actors={local_operator:'Local operator',paired_lan_operator:'Paired operator',producer_control:'Producer control',guest_session:'Guest invitation session',host_voice:'Voice',host_gesture:'Gesture',program_renderer:'Output renderer',server:'Studio service',verified_account:'Account operator'};
    const actions={'invite.created':'Invitation created','invite.revoked':'Invitation revoked','guest.joined':'Guest joined backstage','guest.admit':'Guest admitted','guest.remove':'Guest removed','guest.left':'Guest left','guest.connection':'Guest connection changed','guest.media':'Guest media changed','guest.program_audio':'Program audio setting changed','room.opened':'Room opened','room.closed':'Room closed','room.restarted':'Room restarted','program.preview':'Preview changed','program.take':'Program change','program.rendered':'Program rendered','host.microphone':'Host microphone changed'};
    actions['guest.wait']='Guest returned to waiting room';
    const outcomes={requested:'Requested',confirmed:'Renderer confirmed',succeeded:'Recorded',failed:'Failed',rejected:'Rejected',room_revision_conflict:'Rejected · room changed',room_request_conflict:'Rejected · request conflict'};
    const person=String(event.action||'').startsWith('guest.')?participants.find(item=>item.id===event.target):null;
    return {actor:actors[event.actor_kind]||'Unidentified source',action:actions[event.action]||'Production event',outcome:outcomes[event.outcome]||'Recorded event',verified:event.identity_verified===true,
      guest:typeof person?.name==='string'?person.name.slice(0,60):'',timestamp:Number.isFinite(event.timestamp)&&event.timestamp>0?event.timestamp:null};
  }
  function createRequests(fetcher,revision,random=()=>randomHex()){
    const pending=new Map();let busy=false;
    async function request(path,options={}){
      const controller=new host.AbortController(),timer=host.setTimeout(()=>controller.abort(),10000);
      let response;
      try{
        response=await fetcher(path,{credentials:'same-origin',cache:'no-store',...options,headers:{'Content-Type':'application/json',...(options.headers||{})},signal:controller.signal});
        const payload=await response.json();
        if(!response.ok||payload?.ok===false){const error=Error(/^[a-z0-9_]{1,80}$/.test(payload?.reason||'')?payload.reason:'request_rejected');error.status=response.status;error.uncertain=response.status>=500;throw error;}
        return payload;
      }catch(error){if(!error.status){const failure=Error('connection_unavailable');failure.uncertain=true;throw failure;}throw error;}
      finally{host.clearTimeout(timer);}
    }
    async function mutate(path,body){
      if(busy)throw Error('producer_request_busy');
      const key=JSON.stringify([path,body]);
      let entry=pending.get(key);
      if(!entry){const expected=revision();if(!Number.isInteger(expected))throw Error('room_not_loaded');if(pending.size>=32)throw Error('pending_request_limit');entry={...body,expected_revision:expected,request_id:random()};pending.set(key,entry);}
      busy=true;
      try{const result=await request(path,{method:'POST',body:JSON.stringify(entry)});pending.delete(key);return result;}
      catch(error){if(!error.uncertain)pending.delete(key);throw error;}
      finally{busy=false;}
    }
    return {request,mutate,busy:()=>busy};
  }
  function createPeerWarnings(){
    const warnings=new Map(),labels={
      peer_disconnected:'This guest’s connection to this studio is interrupted. Other connections may still be available.',
      peer_reconnecting:'Reconnecting this guest to this studio. Other guest connections are unchanged.',
      peer_failed:'This guest could not reconnect to this studio. Ask them to rejoin; check Studio Output before taking the shot.'
    };
    return {
      update(event){
        if(event?.scope!=='peer'||typeof event.peer_id!=='string')return;
        if(['connected','peer_removed'].includes(event.state)){warnings.delete(event.peer_id);return;}
        if(typeof event.participant_id==='string'&&Object.prototype.hasOwnProperty.call(labels,event.state))warnings.set(event.peer_id,{participant:event.participant_id,state:event.state});
      },
      prune(participants){const active=new Set(participants.filter(p=>p.state!=='removed'&&!p.expired).map(p=>p.id));for(const [id,warning] of warnings)if(!active.has(warning.participant))warnings.delete(id);},
      text(participant){const states=Array.from(warnings.values()).filter(w=>w.participant===participant).map(w=>w.state);return labels[['peer_failed','peer_reconnecting','peer_disconnected'].find(s=>states.includes(s))]||'';},
      clear(){warnings.clear();}
    };
  }
  function mount(workspace){
    if(!workspace||workspace._producerGreenroom)return workspace?._producerGreenroom;
    const doc=host.document,panel=doc.createElement('section');panel.className='production-greenroom';panel.dataset.broadcastPanel='live';
    panel.innerHTML='<header class="greenroom-heading"><div><span class="greenroom-eyebrow">TOGETHER, ON AIR</span><h3>Green room</h3><p>Invite guests. Prepare their feeds. Take the shot when you’re ready.</p></div><span class="greenroom-connection" role="status">Connecting…</span></header><div class="greenroom-body"><div class="greenroom-room-bar"><span data-room-count>Loading your room…</span><button type="button" class="riq-button" data-room-toggle disabled>Close room</button></div><form class="greenroom-invite"><label><span>Guest name or invitation label</span><input maxlength="60" autocomplete="off" placeholder="Guest, co-host or player" aria-label="Invitation label"></label><label><span>Link expires</span><select aria-label="Invitation expiry"><option value="60">In 1 hour</option><option value="240">In 4 hours</option><option value="1440">In 24 hours</option></select></label><button class="riq-button primary" type="submit" disabled>Create invitation</button></form><div class="greenroom-share" hidden><label><span>Your private invitation · shown only here</span><input type="text" readonly aria-label="Private invitation link"></label><a class="riq-button" data-open-invite target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Open guest tab</a><button class="riq-button" type="button" data-copy-invite>Copy link</button><button class="riq-button" type="button" data-dismiss-invite>Dismiss</button><p data-invite-hint></p></div><p class="greenroom-notice" role="status" aria-live="polite">Guests stay backstage until you admit them. Admission never changes Program.</p><div class="greenroom-host"><div><strong>Your conversation audio</strong><span>Listen to admitted guests or add your own microphone as a source.</span></div><div><button type="button" class="riq-button" data-room-listen>Listen to room</button><button type="button" class="riq-button" data-host-mic>Add my microphone</button></div></div><div class="greenroom-empty"><strong>Your next guest starts here</strong><p>Create an invitation and send the link. Guests can share a camera, microphone, screen or game window.</p></div><div class="greenroom-guests"></div><div class="greenroom-stage"><div class="greenroom-stage-heading"><strong>Build Preview</strong><span data-preview-count>No guest feeds selected</span></div><div class="greenroom-camera-sources" aria-label="Local camera sources"></div><div class="greenroom-stage-controls"><label><span>Layout</span><select data-room-layout><option value="auto">Automatic</option><option value="grid">Grid</option><option value="spotlight">Spotlight</option></select></label><label><span>Transition</span><select data-room-transition><option value="cut">Cut</option><option value="fade" selected>Fade</option><option value="slide">Slide</option><option value="zoom">Zoom</option></select></label><label><span>Duration</span><select data-room-duration><option value="250">250 ms</option><option value="500" selected>500 ms</option><option value="1000">1 second</option><option value="1500">1.5 seconds</option></select></label><button class="riq-button" type="button" data-preview-clear>Clear Preview</button><button class="riq-button primary" type="button" data-room-take disabled>Take Preview</button></div><p data-room-ready>Open Studio Output to prepare guest feeds.</p><div class="greenroom-output"><span data-output-state>No output connected</span><a class="riq-button" href="/output/studio" target="_blank" rel="noopener">Open Studio Output</a></div></div><details class="greenroom-invitations"><summary>Invitations <span data-invite-count>0</span></summary><div data-invites></div></details><p class="greenroom-access-note">Create a separate invitation for each guest. Local test links open on this computer; joining from another device needs a secure studio address. Guest names identify invitation sessions. Shared-account sign-in is a separate setup.</p></div>';
    workspace.append(panel);
    const chatContainer=doc.createElement('div');panel.querySelector('.greenroom-guests').after(chatContainer);
    const chat=host.ProducerGreenroomChat?.mount(chatContainer,{role:'producer'});
    const endedGuests=doc.createElement('details');endedGuests.className='greenroom-ended';endedGuests.hidden=true;
    endedGuests.innerHTML='<summary>Guests who left or were removed</summary><p>Ended invitations cannot be restored. Create a new invitation to bring someone back.</p><div data-ended-guests></div>';
    panel.querySelector('.greenroom-guests').after(endedGuests);
    const endedRows=new Map();
    const activity=doc.createElement('details');activity.className='greenroom-activity';
    activity.innerHTML='<summary>Recent activity</summary><p>Recorded actions and output receipts. Guest names are display names, not verified identities.</p><div class="greenroom-activity-toolbar"><span role="status" aria-live="polite" data-activity-status>Open to load recent activity.</span><button type="button" class="riq-button" data-activity-refresh>Refresh activity</button></div><ol aria-label="Recent production activity"></ol>';
    panel.querySelector('.greenroom-invitations').after(activity);
    let room={participants:[],invites:[],output:{}},switcher=pendingSwitcher||{},closed=false,busy=false,loaded=false,confirmClose=false,link='',pollTimer=null,refreshPromise=null,inviteStamp='',mediaConnected=false;
    let activityBusy=false,activityLoaded=false,activityRefreshAt=0,activityStamp='';
    let media=null,conference=null,audioContext=null,listening=false,hostStream=null,hostPublisher=null,hostToken=null,hostId=null,micBusy=false,micGeneration=0;
    const peerWarnings=createPeerWarnings();
    const tiles=new Map(),views=new Map(),cameraButtons=new Map(),api=createRequests((...args)=>host.fetch(...args),()=>room.revision);
    const one=selector=>panel.querySelector(selector),note=message=>{one('.greenroom-notice').textContent=message;};
    const imageLibrary=host.ProducerImageLibrary?.mount({after:one('.greenroom-camera-sources'),catalog:()=>switcher.image_sources||[],selected:()=>previewSources(switcher),busy:()=>busy,select:source=>toggle(source),refresh,fetch:(...args)=>host.fetch(...args),document:doc});
    const mediaLibrary=host.ProducerMediaLibrary?.mount({after:one('.production-image-library')||one('.greenroom-camera-sources'),catalog:()=>switcher.production_sources||[],selected:()=>previewSources(switcher),busy:()=>busy,select:source=>toggle(source),refresh,fetch:(...args)=>host.fetch(...args),document:doc});
    async function refreshActivity(force=false){
      if(closed||!activity.open||activityBusy||!force&&Date.now()-activityRefreshAt<15000)return;
      activityBusy=true;activityRefreshAt=Date.now();const status=activity.querySelector('[data-activity-status]'),button=activity.querySelector('button');button.disabled=true;
      status.textContent=activityLoaded?'Updating activity…':'Loading activity…';
      try{
        const response=await api.request('/api/production/greenroom/activity');
        if(!Array.isArray(response.events))throw Error('invalid_activity');if(closed)return;
        const entries=response.events.slice(0,20).map(event=>activityEntry(event,room.participants)),stamp=JSON.stringify(entries);
        if(stamp!==activityStamp){
          activityStamp=stamp;const list=activity.querySelector('ol');list.replaceChildren();
          for(const entry of entries){
            const row=doc.createElement('li'),time=doc.createElement('time'),content=doc.createElement('div'),action=doc.createElement('strong'),actor=doc.createElement('span'),outcome=doc.createElement('span');
            if(entry.timestamp){const date=new Date(entry.timestamp*1000);time.dateTime=date.toISOString();time.textContent=date.toLocaleString([],{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'});}else time.textContent='Time unavailable';
            action.textContent=entry.action+(entry.guest?' · '+entry.guest+' (display name)':'');actor.textContent=entry.actor+' · '+(entry.verified?'Identity verified':'Identity not verified');outcome.textContent=entry.outcome;outcome.className='greenroom-activity-outcome';content.append(action,actor);row.append(time,content,outcome);list.append(row);
          }
        }
        activityLoaded=true;status.textContent=entries.length?`Showing ${entries.length} most recent recorded events.`:'No recorded room activity yet.';button.textContent='Refresh activity';
      }catch(_){if(!closed){status.textContent=activityLoaded?'Activity could not refresh. The previous list is still shown.':'Activity could not load. Try again.';button.textContent='Retry activity';}}
      finally{activityBusy=false;button.disabled=false;}
    }
    const errorText=error=>({greenroom_revision_conflict:'The room changed in another tab. Your invitation draft is kept; review the current room and try again.',room_revision_conflict:'The room changed in another tab. Review the current room and try again.',source_unavailable:'That source is not ready. Ask the guest to enable it or reconnect.',preview_source_limit:'Preview can contain up to six sources. Remove one before adding another.',connection_unavailable:'The response could not be confirmed. Check the room, then retry the same action.',invitation_capacity_reached:'There are too many unused invitations. Revoke one or wait for it to expire.',guest_capacity_reached:'The room is full. Remove a guest before adding another.',room_closed:'Open the room before creating invitations.',guest_output_not_ready:'Studio Output is still receiving the guest feeds. Keep them in Preview until it is ready.',camera_slot_unavailable:'A selected camera is unavailable. Remove it from Preview or reconnect it.'}[error.message]||'That change could not be confirmed. Refresh the room and try again.');
    function setLink(value){
      const invitation=invitationLink(value);link=invitation?.url||'';
      one('.greenroom-share').hidden=!link;one('.greenroom-share input').value=link;
      const open=one('[data-open-invite]');if(link)open.href=link;else open.removeAttribute('href');
      one('[data-invite-hint]').textContent=invitation?.hint||'';return invitation;
    }
    function updateState(next){
      if(closed)return;
      if(!next||!Number.isInteger(next.revision))return;
      if(loaded&&next.room_id===room.room_id&&next.revision<room.revision)return;
      const changedRoom=room.room_id&&room.room_id!==next.room_id;
      room=next;loaded=true;if(changedRoom){setLink('');peerWarnings.clear();}peerWarnings.prune(room.participants);
      chat?.update({roomId:room.room_id,active:room.active===true,participants:room.participants||[]});
      if(room.switcher)forwardSwitcher({...switcher,...room.switcher});
      render();
    }
    function forwardSwitcher(next){
      if(closed)return;
      if(Number(next.generation||0)<Number(switcher.generation||0)||Number(next.updated_at||0)<Number(switcher.updated_at||0))return;
      switcher={...switcher,...next};
      if(typeof host.renderProductionSwitcher==='function')host.renderProductionSwitcher(switcher);
      else renderSwitcher(switcher);
    }
    async function refresh(afterMutation=false){
      if(closed)return;
      if(refreshPromise){await refreshPromise;if(!afterMutation||closed)return;}
      refreshPromise=(async()=>{
        try{const [status,cameras]=await Promise.all([api.request('/api/production/greenroom'),api.request('/api/production/switcher')]);if(closed)return;if(Number(cameras.generation||0)>=Number(switcher.generation||0))switcher={...switcher,...cameras};updateState(status);}
        catch(_){if(!loaded)note('The green room could not load. Check the studio connection and refresh this page.');}
      })();
      try{await refreshPromise;}finally{refreshPromise=null;}
    }
    async function decision(path,body,success){
      if(busy||micBusy||closed)return null;busy=true;confirmClose=false;render();
      try{const result=await api.mutate(path,body);await refresh(true);if(success)note(success);return result;}
      catch(error){note(errorText(error));await refresh(true);return null;}
      finally{busy=false;render();refreshActivity(true);}
    }
    function sourceName(source){
      if(/^(video|text):/.test(source))return (switcher.production_sources||[]).find(asset=>asset.id===source)?.name||'Source unavailable';
      if(source.startsWith('image:'))return (switcher.image_sources||[]).find(asset=>asset.id===source)?.name||'Image unavailable';
      const camera=cameraId(source);if(camera)return `Camera ${camera}`;
      const person=room.participants.find(item=>Object.values(item.sources||{}).includes(source));
      if(!person)return 'Guest unavailable';
      const kind=Object.keys(person.sources).find(key=>person.sources[key]===source);
      return `${person.name||'Guest'} · ${kind==='audio'?'microphone':kind}`;
    }
    function view(bus){
      if(!host.ProducerCompositionView)return null;
      if(views.has(bus))return views.get(bus);
      const image=doc.getElementById(bus==='program'?'productionProgramPreview':'productionPreviewPreview');
      const monitor=image?.closest('.production-monitor');if(!monitor)return null;
      const container=doc.createElement('div');container.className='greenroom-monitor-composition';container.hidden=true;monitor.append(container);
      const composition=new host.ProducerCompositionView({container,mediaReceiver:media,muted:true,bus});
      const result={container,composition,image,monitor};views.set(bus,result);return result;
    }
    function renderSwitcher(next={}){
      if(closed)return;
      if(Number(next.generation||0)<Number(switcher.generation||0)||Number(next.updated_at||0)<Number(switcher.updated_at||0))return;
      switcher={...switcher,...next};
      for(const bus of ['program','preview']){
        const sources=bus==='program'?programSources(switcher):previewSources(switcher),entry=view(bus);
        if(!entry)continue;
        const legacy=sources.length===1&&cameraId(sources[0])!==null;
        entry.image.hidden=!legacy;entry.image.classList.toggle('greenroom-legacy-hidden',!legacy);entry.container.hidden=legacy;
        if(legacy){entry.composition.clear();const path=`/api/camera-slots/${cameraId(sources[0])}/stream?g=${Number(switcher.generation)||0}`;if(entry.image.getAttribute('src')!==path)entry.image.setAttribute('src',path);}
        else{entry.image.removeAttribute('src');entry.monitor.dataset.sourceState='connected';entry.monitor.dataset.sourceMessage='';entry.composition.render(switcher,room);}
        const label=doc.getElementById(bus==='program'?'productionProgramLabel':'productionPreviewLabel');if(label){label.textContent=sources.length>1?`${sources.length} sources · ${switcher[bus+'_layout']||'auto'}`:sources.length?sourceName(sources[0]):'Empty composition';label.title=sources.map(sourceName).join(' + ');}
      }
      const ready=takeReadiness(switcher,room);
      for(const id of ['productionCut','productionAuto']){const button=doc.getElementById(id);if(button){button.disabled=!ready.ready||previewSources(switcher).some(source=>source.startsWith('guest:'))&&!mediaConnected;button.title=ready.message;}}
      renderStage();
    }
    async function setPreview(sources,layout=switcher.preview_layout||'auto'){
      if(busy||closed)return;busy=true;render();
      try{const next=await api.request('/api/production/switcher/preview',{method:'POST',body:JSON.stringify({preview_sources:sources,layout})});forwardSwitcher(next);note('Preview updated. Program is unchanged.');}
      catch(error){note(['image_source_unavailable','video_source_unavailable','text_source_unavailable'].includes(error.message)?'This source is unavailable. Add a replacement or clear Preview.':errorText(error));}
      finally{busy=false;render();refreshActivity(true);}
    }
    function toggle(source){try{setPreview(togglePreview(source,switcher,room));}catch(error){note(errorText(error));}}
    function attachVideo(video,track){
      if(video._track===track)return;video._track=track;
      video.muted=true;video.srcObject=track?new host.MediaStream([track]):null;video.hidden=!track;
      if(track)video.play().catch(()=>{});
    }
    function makeTile(person){
      const tile=doc.createElement('article');tile.className='greenroom-guest';tile.dataset.participantId=person.id;
      tile.innerHTML='<header><div><strong data-guest-name></strong><span data-guest-status></span></div><span class="greenroom-mic-state"></span></header><p class="greenroom-notice" data-guest-connection role="status" aria-live="polite" hidden></p><div class="greenroom-feeds"><figure><video muted playsinline autoplay></video><div data-empty-camera>Camera off</div><figcaption>Camera</figcaption></figure><figure><video muted playsinline autoplay></video><div data-empty-screen>Screen off</div><figcaption>Screen / game</figcaption></figure></div><div class="greenroom-guest-actions"><button type="button" class="riq-button primary" data-admit>Admit guest</button><button type="button" class="riq-button" data-remove>Remove</button></div><div class="greenroom-source-buttons"><button type="button" class="riq-button" data-source-kind="camera">Camera</button><button type="button" class="riq-button" data-source-kind="screen">Screen</button><button type="button" class="riq-button" data-source-kind="audio">Mic only</button></div><div class="greenroom-program-audio"><strong>Audio on Program</strong><div><button type="button" class="riq-button" data-program-audio="microphone" aria-pressed="false">Mute mic on Program</button><button type="button" class="riq-button" data-program-audio="screen" aria-pressed="false">Mute screen audio on Program</button></div><p>Set before or during a shot. Backstage conversation is unchanged.</p></div>';
      tile.querySelector('[data-admit]').addEventListener('click',()=>decision(`/api/production/greenroom/participants/${encodeURIComponent(person.id)}`,{action:'admit'},'Guest admitted to the room. Choose their sources for Preview when ready.'));
      const wait=doc.createElement('button');wait.type='button';wait.className='riq-button';wait.dataset.wait='';wait.textContent='Return to waiting room';
      wait.addEventListener('click',async()=>{const result=await decision(`/api/production/greenroom/participants/${encodeURIComponent(person.id)}`,{action:'wait'},'Guest returned to the waiting room and removed from Preview and Program. Admit them again when ready.');if(result)tile.querySelector('[data-admit]').focus();});
      tile.querySelector('[data-remove]').before(wait);
      const confirm=doc.createElement('div');confirm.className='greenroom-remove-confirm';confirm.hidden=true;
      confirm.innerHTML='<p>End this guest’s access? This removes their sources from Preview and Program. They will need a new invitation.</p><button type="button" class="riq-button" data-remove-confirm>End guest access</button><button type="button" class="riq-button" data-remove-cancel>Keep guest</button>';
      tile.querySelector('.greenroom-guest-actions').after(confirm);
      const remove=tile.querySelector('[data-remove]');remove.textContent='Remove & end access';remove.setAttribute('aria-expanded','false');
      remove.addEventListener('click',()=>{confirm.hidden=false;remove.setAttribute('aria-expanded','true');confirm.querySelector('[data-remove-cancel]').focus();});
      confirm.querySelector('[data-remove-cancel]').addEventListener('click',()=>{confirm.hidden=true;remove.setAttribute('aria-expanded','false');remove.focus();});
      confirm.querySelector('[data-remove-confirm]').addEventListener('click',async()=>{const result=await decision(`/api/production/greenroom/participants/${encodeURIComponent(person.id)}`,{action:'remove'},'Guest access ended. Use Invite again below to create a new invitation.');if(result){endedGuests.open=true;endedRows.get(person.id)?.querySelector('button').focus();}});
      for(const button of tile.querySelectorAll('[data-program-audio]'))button.addEventListener('click',()=>{
        const current=room.participants.find(item=>item.id===person.id);if(!current||busy||micBusy||!mediaConnected)return;
        decision(`/api/production/greenroom/participants/${encodeURIComponent(person.id)}`,programAudioChange(current,button.dataset.programAudio),'Program audio setting saved. Backstage conversation is unchanged.');
      });
      for(const button of tile.querySelectorAll('[data-source-kind]'))button.addEventListener('click',()=>{const current=room.participants.find(item=>item.id===person.id);if(current)toggle(current.sources[button.dataset.sourceKind]);});
      return tile;
    }
    function renderTiles(){
      const active=room.participants.filter(person=>person.state!=='removed'&&!person.expired),wanted=new Set(active.map(person=>person.id));
      for(const [id,tile] of tiles)if(!wanted.has(id)){for(const video of tile.querySelectorAll('video'))attachVideo(video,null);tile.remove();tiles.delete(id);}
      for(const person of active){
        let tile=tiles.get(person.id);if(!tile){tile=makeTile(person);tiles.set(person.id,tile);one('.greenroom-guests').append(tile);}
        tile.querySelector('[data-guest-name]').textContent=person.name||'Guest';
        const onAir=Object.values(person.sources).some(source=>programSources(switcher).includes(source));
        tile.dataset.state=onAir?'on-air':person.state;
        tile.querySelector('[data-guest-status]').textContent=!person.connected?'Disconnected':person.id===hostId?'This computer · admitted':person.state==='waiting'?'Waiting backstage':onAir?'Selected for Program':'Admitted · backstage';
        tile.querySelector('.greenroom-mic-state').textContent=person.media.microphone?'Mic on':'Mic off';
        const warning=tile.querySelector('[data-guest-connection]');warning.textContent=peerWarnings.text(person.id);warning.hidden=!warning.textContent;
        const current=media?.tracks(person.id)||emptyTracks(),videos=tile.querySelectorAll('video');
        attachVideo(videos[0],current.camera);attachVideo(videos[1],current.screen);
        tile.querySelector('[data-empty-camera]').hidden=Boolean(current.camera);tile.querySelector('[data-empty-screen]').hidden=Boolean(current.screen);
        tile.querySelector('[data-admit]').hidden=person.state!=='waiting';tile.querySelector('[data-admit]').disabled=busy||micBusy||!person.connected;
        tile.querySelector('[data-admit]').title=!person.connected?'The guest must reconnect before admission.':'Let this guest see and talk with the room. Program is unchanged.';
        tile.querySelector('[data-wait]').hidden=person.state!=='admitted';tile.querySelector('[data-wait]').disabled=busy||micBusy;
        tile.querySelector('[data-wait]').title='Remove their sources from Preview and Program, and pause room pictures and conversation. Their invitation stays active so you can admit them again.';
        tile.querySelector('[data-remove]').disabled=busy||micBusy;
        for(const button of tile.querySelectorAll('.greenroom-remove-confirm button'))button.disabled=busy||micBusy;
        for(const button of tile.querySelectorAll('[data-program-audio]')){
          const muted=person.program_audio?.[button.dataset.programAudio+'_muted']===true;
          button.textContent=`${muted?'Unmute':'Mute'} ${button.dataset.programAudio==='microphone'?'mic':'screen audio'} on Program`;
          button.setAttribute('aria-pressed',String(muted));button.disabled=busy||micBusy||!mediaConnected||!room.active;
          button.title=busy||micBusy?'Wait for the current change to finish.':!mediaConnected?'Reconnect to the room to change Program audio.':!room.active?'Open the room to change Program audio.':'Applies when this source is on Program. Guest capture and backstage conversation are unchanged.';
        }
        for(const button of tile.querySelectorAll('[data-source-kind]')){
          const source=person.sources[button.dataset.sourceKind],selected=previewSources(switcher).includes(source),available=sourceAvailable(source,switcher,room);
          button.disabled=busy||!available;button.setAttribute('aria-pressed',String(selected));
          button.title=person.state==='waiting'?'Admit this guest before adding a source to Preview.':!available?'Ask the guest to enable this feed.':selected?'Remove this source from Preview':'Add this source to Preview';
        }
      }
      one('.greenroom-empty').hidden=active.length>0;
      const ended=room.participants.filter(person=>person.state==='removed'||person.expired).slice(-12).reverse(),endedIds=new Set(ended.map(person=>person.id));
      endedGuests.hidden=!ended.length;
      for(const [id,row] of endedRows)if(!endedIds.has(id)){row.remove();endedRows.delete(id);}
      for(const person of ended){
        let row=endedRows.get(person.id);
        if(!row){row=doc.createElement('div');row.className='greenroom-ended-row';const label=doc.createElement('strong'),button=doc.createElement('button');button.type='button';button.className='riq-button';button.textContent='Invite again';button.dataset.reinvite=person.id;
          button.addEventListener('click',async()=>{const result=await decision('/api/production/greenroom/invites',{label:person.name||'Guest',ttl_minutes:60});if(result){setLink(result.join_url);note('New private invitation created. Share this new link with the guest.');one('.greenroom-share input').focus();}});
          row.append(label,button);endedRows.set(person.id,row);one('[data-ended-guests]').append(row);
        }
        row.querySelector('strong').textContent=person.name||'Guest';row.querySelector('button').disabled=busy||micBusy||!room.active;row.querySelector('button').title=room.active?'Create a new one-hour invitation. This does not restore or admit the ended session.':'Open the room before creating an invitation.';
      }
    }
    function renderInvites(){
      const stamp=JSON.stringify([room.invites,busy,micBusy]);if(stamp===inviteStamp)return;inviteStamp=stamp;
      const area=one('[data-invites]');area.replaceChildren();one('[data-invite-count]').textContent=String(room.invites.length);
      for(const invite of room.invites.slice().reverse().slice(0,24)){
        const row=doc.createElement('div');row.className='greenroom-invite-row';const label=doc.createElement('strong'),status=doc.createElement('span'),button=doc.createElement('button');
        label.textContent=invite.label||'Guest invitation';status.textContent=invite.status==='ready'?`Ready · expires ${new Date(invite.expires_at*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}`:invite.status==='used'?'Joined':invite.status==='expired'?'Expired':'Revoked';
        button.type='button';button.className='riq-button';button.textContent='Revoke';button.disabled=busy||micBusy||!['ready','used'].includes(invite.status);button.title=invite.status==='used'?'Revoke access and remove this guest.':'Disable this invitation.';
        button.addEventListener('click',()=>decision(`/api/production/greenroom/invites/${encodeURIComponent(invite.id)}/revoke`,{},'Invitation revoked.'));
        row.append(label,status,button);area.append(row);
      }
    }
    function renderStage(){
      imageLibrary?.render();
      mediaLibrary?.render();
      const selected=previewSources(switcher);one('[data-preview-count]').textContent=`${selected.length} / 6 sources in Preview`;
      one('[data-room-layout]').value=switcher.preview_layout||'auto';
      const cameras=one('.greenroom-camera-sources');
      for(let id=1;id<=4;id++){
        const source=`camera:${id}`;let button=cameraButtons.get(source);
        if(!button){button=doc.createElement('button');button.type='button';button.className='riq-button';button.textContent=`Camera ${id}`;button.addEventListener('click',()=>toggle(source));cameraButtons.set(source,button);cameras.append(button);}
        button.disabled=busy||!sourceAvailable(source,switcher,room);button.setAttribute('aria-pressed',String(selected.includes(source)));button.title=button.disabled?'This local camera is unavailable.':'Toggle this camera in Preview.';
      }
      const ready=takeReadiness(switcher,room);one('[data-room-ready]').textContent=ready.message;
      one('[data-room-take]').disabled=busy||!ready.ready||selected.some(source=>source.startsWith('guest:'))&&!mediaConnected;one('[data-room-take]').title=ready.message;
      one('[data-preview-clear]').disabled=busy||!selected.length;one('[data-room-layout]').disabled=busy;
      const output=room.output||switcher.guest_output||{},generation=Number(switcher.generation)||0;
      one('[data-output-state]').textContent=outputStatusLabel(output,generation);
    }
    function render(){
      one('[data-room-count]').textContent=!loaded?'Loading your room…':room.active?`${room.participants.filter(p=>p.state!=='removed'&&!p.expired).length} / ${room.max_guests} guest spaces`:'Room closed · guests cannot join';
      const roomButton=one('[data-room-toggle]');roomButton.disabled=busy||micBusy||!loaded;roomButton.textContent=!room.active?'Open room':confirmClose?'Confirm close room':'Close room';
      one('.greenroom-invite button').disabled=busy||micBusy||!loaded||!room.active;
      one('[data-host-mic]').disabled=micBusy||busy||!loaded||!room.active||!host.navigator?.mediaDevices?.getUserMedia;
      one('[data-host-mic]').textContent=micBusy?'Preparing microphone…':hostStream?'Stop my microphone':'Add my microphone';
      one('[data-host-mic]').title=!host.navigator?.mediaDevices?.getUserMedia?'Microphone capture needs a supported browser on HTTPS or this computer.':'Adds your microphone as a source; you choose when it enters Program.';
      one('[data-room-listen]').textContent=listening?'Stop listening':'Listen to room';
      renderTiles();renderInvites();renderStage();
    }
    function filteredRoomState(){const current=media?.state();return current?{...current,room:{...current.room,participants:(current.room.participants||[]).filter(person=>person.id!==hostId)}}:null;}
    async function ensureAudio(){
      if(!conference){
        const facade={state:filteredRoomState,tracks:id=>media.tracks(id),setReturnStream:(id,stream)=>media.setReturnStream(id,stream),subscribe:callback=>media.subscribe(event=>callback(event.type==='state'?{...event,state:filteredRoomState()}:event))};
        conference=host.ProducerGuestMedia.createConferenceAudio(facade);
      }
      if(!audioContext){const Audio=host.AudioContext||host.webkitAudioContext;if(!Audio)throw Error('audio_unavailable');audioContext=new Audio();}
      await conference.start(audioContext);conference.sync();
    }
    async function stopMic({leaving=true}={}){
      micGeneration++;const stream=hostStream,token=hostToken,publisher=hostPublisher;
      hostStream=hostToken=hostPublisher=hostId=null;conference?.setLocalStream(null);publisher?.close();for(const track of stream?.getTracks()||[])track.stop();
      if(token&&leaving)try{await api.request('/guest/leave',{method:'POST',headers:{Authorization:'Bearer '+token},body:'{}',keepalive:true});}catch(_){}
      micBusy=false;conference?.sync();render();await refresh();
    }
    async function startMic(){
      if(micBusy||busy||closed)return;if(hostStream){await stopMic();note('Your microphone stopped.');return;}
      micBusy=true;const generation=++micGeneration;let stream=null,token=null,joined=null,publisher=null,inviteId=null;render();
      const requireCurrent=()=>{if(closed||generation!==micGeneration)throw Error('microphone_cancelled');};
      try{
        await ensureAudio();requireCurrent();
        stream=await host.navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
        if(closed||generation!==micGeneration){for(const track of stream.getTracks())track.stop();return;}
        await refresh(true);requireCurrent();
        const invite=await api.mutate('/api/production/greenroom/invites',{label:'Producer microphone',ttl_minutes:1440});
        inviteId=invite.invite_id;
        requireCurrent();
        const invitation=new URL(invite.join_url,host.location.href),inviteToken=new URLSearchParams(invitation.hash.slice(1)).get('invite');
        if(!/^[a-f0-9]{64}$/.test(inviteToken||''))throw Error('invitation_link_unavailable');
        token=randomHex(32);joined=await api.request('/guest/join',{method:'POST',body:JSON.stringify({invite_token:inviteToken,name:'Producer microphone',session_token:token})});
        requireCurrent();await refresh(true);requireCurrent();await api.mutate(`/api/production/greenroom/participants/${encodeURIComponent(joined.id)}`,{action:'admit'});
        if(closed||generation!==micGeneration)throw Error('microphone_cancelled');
        hostId=joined.id;
        publisher=host.ProducerGuestMedia.createPublisher({token,onConnection:connection=>{if(connection.state==='closed'&&hostPublisher===publisher){stopMic({leaving:false});note('Your microphone connection stopped. Add it again when ready.');}},onError:()=>{}});
        publisher.setTracks({microphone:stream.getAudioTracks()[0],camera:null,screen:null,screen_audio:null});await publisher.connect();
        if(closed||generation!==micGeneration)throw Error('microphone_cancelled');
        hostPublisher=publisher;hostToken=token;hostStream=stream;conference.setLocalStream(stream);conference.sync();
        for(const track of stream.getAudioTracks())track.addEventListener('ended',()=>{if(hostStream===stream)stopMic();});
        note('Your microphone is in the room. Add its Mic only source to Preview, then Take when ready.');await refresh();
      }catch(_){
        publisher?.close();for(const track of stream?.getTracks()||[])track.stop();
        if(token&&joined)try{await api.request('/guest/leave',{method:'POST',headers:{Authorization:'Bearer '+token},body:'{}'});}catch(_){}
        else if(inviteId)try{await refresh();await api.mutate(`/api/production/greenroom/invites/${encodeURIComponent(inviteId)}/revoke`,{});}catch(_){}
        hostId=null;note('Your microphone could not be added. Check microphone permission and room capacity, then try again.');
      }finally{micBusy=false;render();}
    }
    one('.greenroom-invite').addEventListener('submit',async event=>{
      event.preventDefault();const label=one('.greenroom-invite input').value.trim()||'Guest',ttl=Number(one('.greenroom-invite select').value);
      const result=await decision('/api/production/greenroom/invites',{label,ttl_minutes:ttl});
      if(result?.join_url){const invitation=setLink(result.join_url);note(invitation?'Invitation created. '+invitation.hint:'The invitation link could not be opened safely. Revoke it and create a new invitation.');}
      else if(result)note('The invitation exists, but its private link is no longer available. Revoke it and create a new invitation.');
    });
    one('[data-copy-invite]').addEventListener('click',async()=>{if(!link)return;try{await host.navigator.clipboard.writeText(link);note('Private invitation copied.');}catch(_){one('.greenroom-share input').select();note('Select and copy the private invitation link.');}});
    one('[data-dismiss-invite]').addEventListener('click',()=>setLink(''));
    one('[data-room-toggle]').addEventListener('click',async()=>{if(room.active&&!confirmClose){confirmClose=true;note('Closing the room disconnects its guests and revokes its invitations. Click Confirm close room to continue.');render();return;}const result=await decision(`/api/production/greenroom/room/${room.active?'close':'open'}`,{},room.active?'Room closed.':'Room opened.');if(result&&!result.active){setLink('');await stopMic();}});
    one('[data-room-layout]').addEventListener('change',event=>setPreview(previewSources(switcher),event.target.value));
    one('[data-preview-clear]').addEventListener('click',()=>setPreview([]));
    one('[data-room-take]').addEventListener('click',async()=>{
      if(busy||!takeReadiness(switcher,room).ready)return;busy=true;render();
      try{const transition=one('[data-room-transition]').value,next=await api.request('/api/production/switcher/take',{method:'POST',body:JSON.stringify({preview_sources:previewSources(switcher),layout:switcher.preview_layout||'auto',transition,duration_ms:transition==='cut'?0:Number(one('[data-room-duration]').value),request_id:randomHex(),expires_at:Date.now()/1000+30})});forwardSwitcher(next);note('Program change requested. Studio Output confirmation is shown below.');}
      catch(error){note(errorText(error));}finally{busy=false;render();refreshActivity(true);}
    });
    activity.addEventListener('toggle',()=>{if(activity.open)refreshActivity(true);});
    activity.querySelector('button').addEventListener('click',()=>refreshActivity(true));
    one('[data-room-listen]').addEventListener('click',async()=>{try{await ensureAudio();listening=!listening;conference.setMonitor(listening);note(listening?'Listening to admitted guests. Use headphones to prevent feedback.':'Room monitoring stopped.');render();}catch(_){note('Room audio could not start. Try again from a supported browser.');}});
    one('[data-host-mic]').addEventListener('click',startMic);
    if(host.ProducerGuestMedia){
      media=host.ProducerGuestMedia.createReceiver({role:'producer',onState:message=>{mediaConnected=true;updateState(message.room);},onTracks:()=>{renderTiles();for(const entry of views.values())entry.composition.refresh();},onConnection:connection=>{if(connection.scope==='peer'){peerWarnings.update(connection);renderTiles();return;}if(!connection.participant_id){mediaConnected=connection.state==='connected';one('.greenroom-connection').textContent=mediaConnected?'Room connected':connection.state==='connecting'?'Connecting…':'Room connection interrupted';panel.dataset.connection=connection.state;if(!mediaConnected){peerWarnings.clear();room.output={...room.output,ready_sources:[]};render();}}},onError:()=>{}});
      media.connect().catch(()=>{one('.greenroom-connection').textContent='Room unavailable';});
    }else{one('.greenroom-connection').textContent='Guest media unavailable';}
    const result={panel,media,renderSwitcher,refresh,close(){if(closed)return;closed=true;chat?.destroy();imageLibrary?.close();mediaLibrary?.close();peerWarnings.clear();micGeneration++;host.clearInterval(pollTimer);setLink('');stopMic();media?.close();conference?.close();for(const entry of views.values())entry.composition.close();audioContext?.close();}};
    workspace._producerGreenroom=result;instance=result;
    host.addEventListener('pagehide',()=>result.close(),{once:true});
    refresh();pollTimer=host.setInterval(()=>{if(!doc.hidden){refresh();refreshActivity();}},4000);render();
    return result;
  }
  function outputStatusLabel(output,generation){
    return !output.connected?'No Studio Output connected':output.audio_blocked===true?'Output sound is blocked · open Studio Output and choose Enable output sound':output.rendered_generation===generation?'Studio Output reports this Program shot':'Program requested · waiting for output confirmation';
  }
  const exported={mount,receiver:()=>instance?.media||null,renderSwitcher:state=>{pendingSwitcher=state;instance?.renderSwitcher(state);},sourceAvailable,togglePreview,takeReadiness,createRequests,activityEntry,invitationLink,programAudioChange,outputStatusLabel,createPeerWarnings};
  if(typeof module==='object'&&module.exports)module.exports=exported;
  else host.ProducerGreenroomControls=exported;
})(typeof window==='undefined'?globalThis:window);
