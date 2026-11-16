/* Invitation media transport. Capture, production decisions and playback belong to the UI. */
(function(host){
  'use strict';
  const KEYS=['microphone','camera','screen','screen_audio'];
  const KINDS=['audio','video','video','audio'];
  const EMPTY=()=>Object.fromEntries(KEYS.map(key=>[key,null]));
  const live=track=>Boolean(track&&track.readyState==='live'&&track.enabled!==false);
  const call=(fn,...args)=>{try{fn?.(...args);}catch(_){/* UI failures must not expose signaling data. */}};
  const signalData=value=>typeof value?.toJSON==='function'?value.toJSON():value;
  function candidateMatchesDescription(candidate,description){
    if(!description)return false;
    const fragment=candidate.usernameFragment;
    if(typeof fragment!=='string'||!fragment)return true;
    const fragments=Array.from(String(description.sdp||'').matchAll(/^a=ice-ufrag:([^\r\n]+)/gm),match=>match[1]);
    return !fragments.length||fragments.includes(fragment);
  }
  function engine(role,options={}){
    if(!['guest','guest-view','producer','output'].includes(role))throw Error('invalid_media_role');
    const guestView=role==='guest-view',invitation=role==='guest'||guestView;
    if(invitation&&(typeof options.token!=='string'||! /^[a-f0-9]{64}$/.test(options.token)))throw Error('invalid_guest_session');
    let socket=null,generation=0,closed=true,peerId=null,iceServers=[],state=null;
    let heartbeat=null,watchdog=null,reconnectTimer=null,lastState=0,retries=0,hello=false,readyResolve=null,readyReject=null;
    let pending=[],localTracks=EMPTY(),mediaStamp='',localVersion=0,returnedTrack=null,connectPromise=null;
    const recoveries=new Map();
    const peers=new Map(),subscribers=new Set(),returnStreams=new Map(),endedHandlers=new Map();
    const publisher=role==='guest';
    const notify=event=>{for(const listener of subscribers)call(listener,event);};
    const current=(record,gen=record?.generation)=>!closed&&generation===gen&&(!record||peers.get(record.id)===record&&!record.closed);
    const connected=(value,detail={})=>{const data={state:value,role,...detail};call(options.onConnection,data);notify({type:'connection',...data});};
    const error=reason=>call(options.onError,{reason});
    const send=payload=>{
      if(!closed&&socket?.readyState===1){const encoded=JSON.stringify(payload);if(encoded.length<=65536&&socket.bufferedAmount<262144){socket.send(encoded);return true;}}
      return false;
    };
    function allowedPublisher(record,key){
      const sub=state?.subscriptions?.find(item=>item.peer_id===record.id);
      if(!sub)return false;
      if(sub.role==='guest-view')return key==='camera'&&sub.sources.includes('camera')&&state.participant?.state==='admitted'&&state.participant.expired!==true;
      return key==='microphone'?sub.sources.length>0:key==='camera'?sub.sources.includes('camera'):sub.sources.includes('screen');
    }
    function participant(id){return state?.room?.participants?.find(item=>item.id===id);}
    function receiverSubscribed(id){
      const person=participant(id);
      if(!person||!person.connected||person.state==='removed')return false;
      if(guestView)return state.room.active===true&&person.state==='admitted'&&person.expired!==true&&person.sources?.camera===`guest:${id}:camera`&&state.subscriptions.includes(person.sources.camera);
      return Object.values(person.sources||{}).some(source=>state.subscriptions.includes(source));
    }
    function receiverAllowed(id,key){
      const person=participant(id);
      if(!receiverSubscribed(id)||role==='output'&&person.state!=='admitted'||guestView&&key!=='camera')return false;
      const sources=new Set(state?.subscriptions||[]);
      const any=Object.values(person.sources||{}).some(source=>sources.has(source));
      if(!any)return false;
      if(key==='microphone')return person.media?.microphone===true;
      if(key==='camera')return sources.has(person.sources.camera)&&person.media?.camera===true;
      return sources.has(person.sources.screen)&&person.media?.screen===true&&(key!=='screen_audio'||person.media?.screen_audio===true);
    }
    function canReturn(record){
      if(publisher){const sub=state?.subscriptions?.find(item=>item.peer_id===record.id);return sub?.role==='producer'&&sub.return_audio===true&&state?.participant?.state==='admitted';}
      const person=participant(record.participantId);
      return role==='producer'&&state?.return_audio_owner===true&&person?.state==='admitted'&&person.connected===true;
    }
    function tracks(id){
      const record=Array.from(peers.values()).find(peer=>peer.participantId===id);
      const result=EMPTY();
      if(record)for(const key of KEYS){const track=record.remote[key];if(receiverAllowed(id,key)&&track?.readyState==='live'&&!track.muted)result[key]=track;}
      return result;
    }
    function emitTracks(record,force=false){
      if(publisher){
        const owner=Array.from(peers.values()).find(peer=>canReturn(peer)&&peer.remote.microphone?.readyState==='live'&&!peer.remote.microphone.muted);
        const active=owner?.remote.microphone||null;
        if(active!==returnedTrack||force){returnedTrack=active;call(options.onReturnAudio,active?new host.MediaStream([active]):null);notify({type:'return_audio',peer_id:owner?.id||null});}
        return;
      }
      const values=tracks(record.participantId);
      if(force||KEYS.some(key=>values[key]!==record.emitted[key])){
        record.emitted=values;call(options.onTracks,record.participantId,{...values});notify({type:'tracks',participant_id:record.participantId});
      }
    }
    function closePeer(record,removed=false){
      if(record.closed)return;
      record.closed=true;peers.delete(record.id);
      if(removed){clearRecovery(record.id);connected('peer_removed',{scope:'peer',peer_id:record.id,participant_id:record.participantId});}
      record.pc.onicecandidate=record.pc.ontrack=record.pc.onconnectionstatechange=record.pc.ondatachannel=null;
      record.pc.close();
      for(const track of Object.values(record.remote))if(track){track.onended=track.onmute=track.onunmute=null;track.stop();}
      if(publisher)emitTracks(record);
      else{call(options.onTracks,record.participantId,EMPTY());notify({type:'tracks',participant_id:record.participantId});}
    }
    function clearRecovery(id,notifyRemoved=false){
      const recovery=recoveries.get(id);if(!recovery)return;
      if(recovery.timer!==null)host.clearTimeout(recovery.timer);recoveries.delete(id);
      if(notifyRemoved)connected('peer_removed',{scope:'peer',peer_id:id,participant_id:recovery.participantId});
    }
    function authorizedRecovery(id,participantId){
      if(publisher)return state?.subscriptions?.some(sub=>sub.peer_id===id)===true;
      const person=participant(participantId);
      return receiverSubscribed(participantId)&&(role!=='output'||person.state==='admitted');
    }
    function recoverPeer(record,reason){
      if(!current(record))return;
      let recovery=recoveries.get(record.id);
      if(!recovery){recovery={attempts:0,timer:null,exhausted:false,participantId:record.participantId};recoveries.set(record.id,recovery);}
      if(record.connectedAt!==null&&Date.now()-record.connectedAt>=30000)recovery.attempts=0;
      closePeer(record);
      if(recovery.timer!==null)host.clearTimeout(recovery.timer);
      const detail={scope:'peer',peer_id:record.id,participant_id:record.participantId,reason};
      if(recovery.attempts>=3){recovery.timer=null;recovery.exhausted=true;connected('peer_failed',{...detail,attempt:recovery.attempts,retry_in_ms:0});return;}
      const delay=1000*2**recovery.attempts++,gen=generation;
      recovery.timer=host.setTimeout(()=>{
        if(closed||generation!==gen||recoveries.get(record.id)!==recovery)return;
        recovery.timer=null;
        if(!authorizedRecovery(record.id,record.participantId)){clearRecovery(record.id,true);return;}
        // Guests initiate SDP offers. Receivers wait for that guest's new offer.
        if(publisher){const next=createPeer(record.id);if(next)queue(next,()=>syncPublisher(next));}
      },delay);
      connected('peer_reconnecting',{...detail,attempt:recovery.attempts,retry_in_ms:delay});
    }
    function disposeSocket(){
      for(const id of Array.from(recoveries.keys()))clearRecovery(id);
      host.clearInterval(heartbeat);host.clearInterval(watchdog);heartbeat=watchdog=null;
      const old=socket;socket=null;
      if(old){old.onopen=old.onmessage=old.onerror=old.onclose=null;try{old.close();}catch(_){}}
      state=null;
      for(const record of Array.from(peers.values()))closePeer(record);
      pending=[];peerId=null;hello=false;state=null;mediaStamp='';
      call(options.onReturnAudio,null);notify({type:'state',state:null});
    }
    function fail(reason,{retry=true}={}){
      if(closed)return;
      generation++;disposeSocket();error(reason);connected('disconnected',{reason});
      if(retry&&retries<3){const delay=1000*2**retries++;reconnectTimer=host.setTimeout(()=>{reconnectTimer=null;if(!closed)openSocket();},delay);}
      else{closed=true;readyReject?.(Error(reason));readyResolve=readyReject=null;connected('closed',{reason});}
    }
    async function bounded(promise){
      let timer;
      try{return await Promise.race([promise,new Promise((_,reject)=>{timer=host.setTimeout(()=>reject(Error('media_operation_timeout')),5000);})]);}
      finally{host.clearTimeout(timer);}
    }
    function queue(record,operation){
      if(record.queued>=128){if(current(record))recoverPeer(record,'media_queue_limit');return Promise.resolve();}
      record.queued++;
      record.work=record.work.then(async()=>{try{if(current(record))await operation();}finally{record.queued--;}}).catch(()=>{if(current(record))recoverPeer(record,'media_negotiation_failed');});
      return record.work;
    }
    function createPeer(id,participantId=null){
      if(peers.has(id))return peers.get(id);
      const recovery=recoveries.get(id);if(recovery&&(recovery.timer!==null||recovery.exhausted))return null;
      if(peers.size>=(publisher?17:12))throw Error('media_peer_limit');
      const pc=new host.RTCPeerConnection({iceServers});
      const record={id,participantId,pc,generation,closed:false,remote:EMPTY(),emitted:EMPTY(),returnTrack:null,ice:[],work:Promise.resolve(),queued:0,offered:false,offer:null,answer:null,appliedVersion:-1,connectedAt:null};
      peers.set(id,record);
      pc.onicecandidate=event=>{
        if(current(record)&&event.candidate)send({type:'signal',to:id,kind:'ice',data:signalData(event.candidate)});
      };
      pc.onconnectionstatechange=()=>{
        if(!current(record))return;
        if(pc.connectionState==='failed'){recoverPeer(record,'media_connection_failed');return;}
        if(pc.connectionState==='connected'){retries=0;record.connectedAt=Date.now();}
        connected(pc.connectionState==='disconnected'?'peer_disconnected':pc.connectionState,{scope:'peer',peer_id:id,participant_id:record.participantId});
      };
      pc.ondatachannel=event=>{event.channel.close();if(current(record))fail('unsupported_media_channel',{retry:false});};
      pc.ontrack=event=>{
        if(!current(record))return;
        const index=pc.getTransceivers().indexOf(event.transceiver);
        if(index<0||index>3||event.track.kind!==KINDS[index]||publisher&&(index!==0||state?.subscriptions?.find(sub=>sub.peer_id===id)?.role==='guest-view')||guestView&&index!==1){event.track.stop();return;}
        const key=KEYS[index];
        if(record.remote[key]&&record.remote[key]!==event.track)record.remote[key].stop();
        record.remote[key]=event.track;
        event.track.onended=()=>{if(current(record)){record.remote[key]=null;emitTracks(record);}};
        event.track.onmute=event.track.onunmute=()=>{if(current(record))emitTracks(record);};
        emitTracks(record);
      };
      if(publisher){
        const cameraOnly=state?.subscriptions?.find(sub=>sub.peer_id===id)?.role==='guest-view';
        KINDS.forEach((kind,index)=>pc.addTransceiver(kind,{direction:cameraOnly?(index===1?'sendonly':'inactive'):index===0?'sendrecv':'sendonly'}));
      }
      return record;
    }
    async function syncPublisher(record){
      if(!current(record))return;
      for(let index=0;index<KEYS.length;index++){
        const key=KEYS[index],track=localTracks[key];
        const permitted=allowedPublisher(record,key)&&live(track)&&(key!=='screen_audio'||live(localTracks.screen));
        const next=permitted?track:null,sender=record.pc.getTransceivers()[index].sender;
        if(sender.track!==next)await bounded(sender.replaceTrack(next));
        if(!current(record))return;
      }
      record.appliedVersion=localVersion;
      if(!record.offered){
        const offer=await bounded(record.pc.createOffer());if(!current(record))return;
        await bounded(record.pc.setLocalDescription(offer));if(!current(record))return;
        record.offered=true;send({type:'signal',to:record.id,kind:'offer',data:signalData(record.pc.localDescription)});
      }
      emitTracks(record);
    }
    async function syncReturn(record){
      if(!current(record)||publisher||!record.pc.remoteDescription)return;
      const first=record.pc.getTransceivers()[0];if(!first)return;
      const track=canReturn(record)?returnStreams.get(record.participantId)?.getAudioTracks().find(live):null;
      if(first.sender.track!==(track||null))await bounded(first.sender.replaceTrack(track||null));
    }
    function announceMedia(){
      if(!publisher||!hello)return;
      const media=Object.fromEntries(KEYS.map(key=>[key,live(localTracks[key])]));
      media.screen_audio=media.screen&&media.screen_audio;
      const stamp=JSON.stringify(media);if(stamp!==mediaStamp&&send({type:'media',media}))mediaStamp=stamp;
    }
    function acceptState(message){
      if(publisher){
        if(!message.participant||!['waiting','admitted'].includes(message.participant.state)||message.participant.connected!==true||!Array.isArray(message.subscriptions)||message.subscriptions.length>17)throw Error('invalid_media_state');
        for(const sub of message.subscriptions)if(typeof sub.peer_id!=='string'||!['producer','output','guest-view'].includes(sub.role)||!Array.isArray(sub.sources)||sub.sources.some(source=>!['camera','screen','audio'].includes(source))||sub.role==='guest-view'&&(sub.sources.length!==1||sub.sources[0]!=='camera'||sub.return_audio===true))throw Error('invalid_media_state');
        if(message.subscriptions.filter(sub=>sub.role==='guest-view').length>12||message.subscriptions.filter(sub=>sub.role!=='guest-view').length>5)throw Error('invalid_media_state');
      }else if(!message.room||!Array.isArray(message.room.participants)||message.room.participants.length>128||!Array.isArray(message.subscriptions)||message.subscriptions.length>36)throw Error('invalid_media_state');
      if(guestView&&(message.subscriptions.length>12||message.subscriptions.some(source=>typeof source!=='string'||!/^guest:[^:]+:camera$/.test(source))))throw Error('invalid_media_state');
      state=message;lastState=Date.now();
      for(const [id,recovery] of recoveries)if(!authorizedRecovery(id,recovery.participantId)){const record=peers.get(id);if(record)closePeer(record,true);else clearRecovery(id,true);}
      if(publisher){
        const wanted=new Set(message.subscriptions.map(sub=>sub.peer_id));
        for(const record of Array.from(peers.values()))if(!wanted.has(record.id))closePeer(record,true);
        for(const sub of message.subscriptions){
          const record=createPeer(sub.peer_id);if(!record)continue;
          record.pc.getTransceivers().forEach((value,index)=>{if(value.sender.track&&!allowedPublisher(record,KEYS[index]))value.sender.replaceTrack(null).catch(()=>{if(current(record))recoverPeer(record,'media_detach_failed');});});
          queue(record,()=>syncPublisher(record));emitTracks(record);
        }
        announceMedia();
      }else{
        for(const record of Array.from(peers.values())){
          if(!receiverSubscribed(record.participantId))closePeer(record,true);
          else{
            const sender=record.pc.getTransceivers()[0]?.sender;
            if(sender?.track&&!canReturn(record))sender.replaceTrack(null).catch(()=>{if(current(record))recoverPeer(record,'media_detach_failed');});
            emitTracks(record);queue(record,()=>syncReturn(record));
          }
        }
      }
      call(options.onState,message);notify({type:'state',state:message});
      const held=pending;pending=[];for(const signal of held)if(Date.now()-signal.at<2000)acceptSignal(signal.message,false);
    }
    async function flushIce(record){
      const values=record.ice;record.ice=[];
      for(const value of values){if(!current(record))return;if(candidateMatchesDescription(value,record.pc.remoteDescription))await bounded(record.pc.addIceCandidate(value));}
    }
    function acceptSignal(message,mayHold=true){
      if(typeof message.from!=='string'||!['offer','answer','ice'].includes(message.kind)||!message.data||typeof message.data!=='object')throw Error('invalid_media_signal');
      if(message.kind!=='ice'&&(message.data.type!==message.kind||typeof message.data.sdp!=='string'||message.data.sdp.length>50000||/^m=application /m.test(message.data.sdp)))throw Error('invalid_media_description');
      if(message.kind==='ice'&&(typeof message.data.candidate!=='string'||message.data.candidate.length>2048||message.data.sdpMLineIndex!=null&&(!Number.isInteger(message.data.sdpMLineIndex)||message.data.sdpMLineIndex<0||message.data.sdpMLineIndex>3)))throw Error('invalid_media_candidate');
      if(publisher){
        if(!state?.subscriptions?.some(sub=>sub.peer_id===message.from)){
          if(mayHold&&pending.length<64)pending.push({message,at:Date.now()});return;
        }
        if(message.kind==='offer')return;
      }else{
        if(!receiverSubscribed(message.participant_id)){
          if(mayHold&&pending.length<64)pending.push({message,at:Date.now()});return;
        }
        if(message.role!=='guest'||message.kind==='answer')return;
      }
      if(!publisher&&message.kind==='offer'){
        // A rejoined guest receives a new signaling ID. Retire its former media
        // record so tracks() cannot keep selecting an obsolete first match.
        for(const old of Array.from(peers.values()))if(old.participantId===message.participant_id&&old.id!==message.from)closePeer(old,true);
        for(const [id,recovery] of recoveries)if(recovery.participantId===message.participant_id&&id!==message.from)clearRecovery(id,true);
      }
      const recovery=recoveries.get(message.from);
      if(recovery?.exhausted)return;
      if(recovery&&recovery.timer!==null){
        if(!publisher&&message.kind==='offer'){host.clearTimeout(recovery.timer);recovery.timer=null;}
        else{if(!publisher&&mayHold&&pending.length<64)pending.push({message,at:Date.now()});return;}
      }
      const record=createPeer(message.from,publisher?null:message.participant_id);if(!record)return;
      if(message.kind==='ice'&&!candidateMatchesDescription(message.data,record.pc.remoteDescription)){
        if(record.ice.length>=64){recoverPeer(record,'media_candidate_limit');return;}
        record.ice.push(message.data);return;
      }
      queue(record,async()=>{
        if(message.kind==='ice'){
          await bounded(record.pc.addIceCandidate(message.data));
          return;
        }
        if(message.kind==='answer'){
          if(record.pc.signalingState!=='have-local-offer')return;
          await bounded(record.pc.setRemoteDescription(message.data));if(!current(record))return;
          if(record.pc.getTransceivers().length!==4)throw Error('unsupported_media_layout');
          await flushIce(record);return;
        }
        if(record.offer===message.data.sdp&&record.answer){send({type:'signal',to:record.id,kind:'answer',data:record.answer});return;}
        await bounded(record.pc.setRemoteDescription(message.data));if(!current(record))return;
        const transceivers=record.pc.getTransceivers();
        if(transceivers.length!==4||transceivers.some((value,index)=>value.receiver.track.kind!==KINDS[index]))throw Error('unsupported_media_layout');
        transceivers.forEach((value,index)=>{value.direction=guestView?(index===1?'recvonly':'inactive'):role==='producer'&&index===0?'sendrecv':'recvonly';});
        await syncReturn(record);if(!current(record))return;
        const answer=await bounded(record.pc.createAnswer());if(!current(record))return;
        await bounded(record.pc.setLocalDescription(answer));if(!current(record))return;
        record.offer=message.data.sdp;record.answer=signalData(record.pc.localDescription);
        send({type:'signal',to:record.id,kind:'answer',data:record.answer});await flushIce(record);
      });
    }
    function openSocket(){
      if(closed)return;
      if(!host.WebSocket||!host.RTCPeerConnection||!host.MediaStream){fail('browser_media_unavailable',{retry:false});return;}
      const gen=++generation;lastState=Date.now();hello=false;
      const path=publisher?'/guest/ws':guestView?'/guest/view/ws':`/api/production/greenroom/${role}-socket`;
      const url=(host.location.protocol==='https:'?'wss://':'ws://')+host.location.host+path;
      try{socket=new host.WebSocket(url);}catch(_){fail('signaling_unavailable');return;}
      const ws=socket;connected('connecting');
      const valid=()=>!closed&&generation===gen&&socket===ws;
      ws.onopen=()=>{if(valid()&&invitation)send({type:'authenticate',token:options.token});};
      ws.onmessage=event=>{
        if(!valid())return;
        try{
          if(typeof event.data!=='string'||event.data.length>65536)throw Error('invalid_media_message');
          const message=JSON.parse(event.data);
          if(message.type==='hello'){
            if(hello||typeof message.peer_id!=='string'||message.role!==role||!Array.isArray(message.ice_servers))throw Error('invalid_media_hello');
            peerId=message.peer_id;iceServers=message.ice_servers;hello=true;lastState=Date.now();
            connected('connected',{scope:'signaling',peer_id:peerId});announceMedia();readyResolve?.({peer_id:peerId,role});readyResolve=readyReject=null;
          }else if(!hello)throw Error('media_hello_required');
          else if(message.type==='state')acceptState(message);
          else if(message.type==='signal')acceptSignal(message);
          else throw Error('invalid_media_message');
        }catch(_){fail('invalid_signaling_response',{retry:false});}
      };
      ws.onerror=()=>{if(valid())error('signaling_unavailable');};
      ws.onclose=event=>{if(valid())fail(event.code===1008?'guest_access_ended':'signaling_disconnected',{retry:![1000,1008].includes(event.code)});};
      heartbeat=host.setInterval(()=>{if(valid()&&hello){send({type:'heartbeat'});announceMedia();}},4000);
      watchdog=host.setInterval(()=>{if(valid()&&Date.now()-lastState>7000)fail('production_state_stalled');},1000);
    }
    const api={
      role,
      connect(){
        if(!closed)return connectPromise||Promise.resolve({peer_id:peerId,role});
        closed=false;retries=0;
        connectPromise=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject;openSocket();});
        return connectPromise;
      },
      close(){
        closed=true;generation++;host.clearTimeout(reconnectTimer);reconnectTimer=null;disposeSocket();
        readyReject?.(Error('media_closed'));readyResolve=readyReject=null;returnStreams.clear();
        for(const [track,handler] of endedHandlers)track.removeEventListener?.('ended',handler);endedHandlers.clear();
        localTracks=EMPTY();connectPromise=null;
        connected('closed');
      },
      state:()=>state,
      subscribe(listener){subscribers.add(listener);return()=>subscribers.delete(listener);},
      tracks,
      setTracks(values){
        if(!publisher||!values||typeof values!=='object')throw Error('invalid_guest_tracks');
        for(const key of Object.keys(values))if(!KEYS.includes(key))throw Error('invalid_guest_tracks');
        for(const [key,track] of Object.entries(values))if(track!==null&&(!track||track.kind!==KINDS[KEYS.indexOf(key)]||typeof track.readyState!=='string'))throw Error('invalid_guest_track');
        localTracks={...localTracks,...values};localVersion++;
        for(const [track,handler] of endedHandlers)if(!Object.values(localTracks).includes(track)){track.removeEventListener?.('ended',handler);endedHandlers.delete(track);}
        for(const track of Object.values(localTracks))if(track&&!endedHandlers.has(track)){const handler=()=>{localVersion++;announceMedia();for(const record of peers.values())queue(record,()=>syncPublisher(record));};track.addEventListener?.('ended',handler);endedHandlers.set(track,handler);}
        announceMedia();for(const record of peers.values())queue(record,()=>syncPublisher(record));
      },
      sendReady(sources,playback){
        if(role!=='output'||!Array.isArray(sources))return false;
        const message={type:'ready',sources:[...new Set(sources)].filter(source=>typeof source==='string'&&state?.subscriptions?.includes(source)).slice(0,12)};
        if(playback&&Number.isSafeInteger(playback.generation)&&playback.generation>=0&&playback.generation===state?.room?.switcher?.generation&&typeof playback.audioBlocked==='boolean'&&typeof playback.rendered==='boolean')message.playback={generation:playback.generation,audio_blocked:playback.audioBlocked,rendered:playback.rendered};
        return send(message);
      },
      rendered(value){return role==='output'&&Number.isInteger(value)&&value===state?.room?.switcher?.generation&&send({type:'rendered',generation:value});},
      setReturnStream(id,stream){
        if(role!=='producer')return Promise.resolve(false);
        if(stream!==null&&typeof stream?.getAudioTracks!=='function')throw Error('invalid_return_stream');
        if(stream)returnStreams.set(id,stream);else returnStreams.delete(id);
        return Promise.all(Array.from(peers.values()).filter(record=>record.participantId===id).map(record=>queue(record,()=>syncReturn(record))));
      }
    };
    return api;
  }
  function createConferenceAudio(receiver){
    let context=null,localStream=null,people=[],sources=[],monitor=null,monitoring=false,signature='';
    const destinations=new Map(),silentConsumers=new Map();
    const dropSources=()=>{for(const node of sources)try{node.disconnect();}catch(_){}sources=[];};
    function syncSilentConsumers(inputs=[]){
      const tracks=new Set(inputs.filter(input=>input.owner!==null).map(input=>input.track));
      for(const [track,audio] of silentConsumers)if(!tracks.has(track)){audio.pause();audio.srcObject=null;audio.remove?.();silentConsumers.delete(track);}
      for(const track of tracks)if(!silentConsumers.has(track)&&host.document?.createElement){
        // Chromium needs a media-element consumer to decode remote audio for the mix graph.
        // This sink is always muted; audible monitoring belongs only to setMonitor().
        const audio=host.document.createElement('audio');audio.muted=true;audio.autoplay=true;audio.hidden=true;audio.setAttribute('aria-hidden','true');
        audio.srcObject=new host.MediaStream([track]);host.document.body?.append(audio);silentConsumers.set(track,audio);
        Promise.resolve(audio.play()).catch(()=>{});
      }
    }
    function removeDestination(id){const item=destinations.get(id);if(!item)return;receiver.setReturnStream(id,null);try{item.disconnect();}catch(_){}for(const track of item.stream.getTracks())track.stop();destinations.delete(id);}
    function sync(participants=people){
      people=Array.isArray(participants)?participants:[];
      if(!context)return;
      const current=receiver.state?.();
      if(typeof receiver.state==='function')people=current?.room?.participants||[];
      const admitted=people.filter(person=>person.connected&&person.state==='admitted');
      const owned=typeof receiver.state==='function'?current?.return_audio_owner===true:true;
      const inputs=[];
      for(const track of localStream?.getAudioTracks?.()||[])if(live(track))inputs.push({owner:null,track});
      for(const person of admitted){const tracks=receiver.tracks(person.id);for(const key of ['microphone','screen_audio'])if(live(tracks[key]))inputs.push({owner:person.id,track:tracks[key]});}
      const next=JSON.stringify([owned,admitted.map(p=>p.id),inputs.map(item=>[item.owner,item.track.id]),monitoring]);
      if(next===signature)return;signature=next;dropSources();syncSilentConsumers(owned||monitoring?inputs:[]);
      const ids=new Set(owned?admitted.map(person=>person.id):[]);
      for(const id of destinations.keys())if(!ids.has(id))removeDestination(id);
      for(const id of ids)if(!destinations.has(id)){const destination=context.createMediaStreamDestination();destinations.set(id,destination);receiver.setReturnStream(id,destination.stream);}
      for(const input of inputs){
        const source=context.createMediaStreamSource(new host.MediaStream([input.track]));sources.push(source);
        for(const [id,destination] of destinations)if(id!==input.owner)source.connect(destination);
        if(monitoring&&input.owner!==null)source.connect(monitor);
      }
    }
    const unsubscribe=receiver.subscribe?.(event=>{
      if(event.type==='state'){if(!event.state){people=[];signature='';dropSources();syncSilentConsumers();for(const id of Array.from(destinations.keys()))removeDestination(id);return;}people=event.state.room?.participants||[];}
      if(event.type==='state'||event.type==='tracks')sync(people);
    });
    return {
      async start(audioContext){
        if(context&&context!==audioContext)throw Error('conference_context_already_started');
        if(!audioContext?.createMediaStreamDestination||!audioContext.createMediaStreamSource)throw Error('conference_audio_unavailable');
        context=audioContext;if(context.state==='suspended')await context.resume();
        if(context.state!=='running')throw Error('conference_audio_not_running');
        if(!monitor){monitor=context.createGain();monitor.gain.value=1;if(monitoring)monitor.connect(context.destination);}
        signature='';sync(people);
      },
      setLocalStream(stream){if(stream!==null&&typeof stream?.getAudioTracks!=='function')throw Error('invalid_host_audio');localStream=stream;signature='';sync(people);},
      sync,
      setMonitor(value){monitoring=value===true;if(monitor){monitor.disconnect();if(monitoring)monitor.connect(context.destination);}signature='';sync(people);},
      close(){unsubscribe?.();dropSources();syncSilentConsumers();for(const id of Array.from(destinations.keys()))removeDestination(id);monitor?.disconnect();monitor=null;context=null;localStream=null;people=[];signature='';monitoring=false;}
    };
  }
  const exported={createPublisher:options=>engine('guest',options),createReceiver:options=>engine(options?.role||'producer',options),createConferenceAudio};
  if(typeof module==='object'&&module.exports)module.exports=exported;
  else host.ProducerGuestMedia=exported;
})(typeof window==='undefined'?globalThis:window);
