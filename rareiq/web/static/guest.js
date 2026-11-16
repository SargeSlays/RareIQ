(function(root){
  "use strict";
  const $=id=>document.getElementById(id), media={microphone:null,camera:null,screen:null,screen_audio:null};
  const STORE="producer.guest.session.v1";
  let invite=new URLSearchParams(location.hash.slice(1)).get("invite"),token="",publisher=null,joined=false,busy=false,leaving=false,mediaEpoch=0,microphone=null;
  let gateSettings={enabled:false,thresholdDb:-45};
  let voiceSettings={preset:"natural",soundVolume:.5},audioBusy=false,returnEpoch=0;
  const cueButtons={guestCueChime:"chime",guestCueSuccess:"success",guestCueBuzzer:"buzzer",guestCueDrumroll:"drumroll"};
  const peerWarnings=new Map(),soundRows=new Map(),deviceSelection={camera:"",microphone:""},captureGeneration={camera:0,microphone:0,screen:0};
  let roomConnected=false,pendingCapture=null;
  let connectionEpoch=0,connecting=false,joining=false,retryAvailable=false,accessEnded=false,lastConnectionCode="",pendingSoundFocus=null;
  try{const saved=JSON.parse(localStorage.getItem("producer.guest.gate.v1")||"null");if(saved)gateSettings={enabled:saved.enabled===true,thresholdDb:Math.max(-70,Math.min(-10,Number.isFinite(saved.thresholdDb)?saved.thresholdDb:-45))};}catch{}
  history.replaceState(null,"",location.pathname);
  if(!invite){try{token=sessionStorage.getItem(STORE)||"";}catch{}}
  const validSession=()=>/^[a-f0-9]{64}$/.test(token);
  function feedback(id,message){$(id).textContent=message;$(id).hidden=!message;}
  const audioFeedback=message=>feedback("guestAudioError",message);
  function deviceError(error,kind){
    const name=kind==="camera"?"Camera":kind==="screen"?"Screen sharing":"Microphone";
    const messages={NotAllowedError:"permission was not granted. Allow access in your browser, then try again.",NotFoundError:"was not found. Connect a device or choose another input.",NotReadableError:"could not start. Close another app using the device, then try again.",OverconstrainedError:"selection is unavailable. Choose another device.",SecurityError:"access was blocked by this browser. Use a secure supported browser."};
    return name+" "+(messages[error?.name]||"is unavailable. Choose another device or try a supported browser.");
  }
  function status(title,message){$("guestStatusTitle").textContent=title;$("guestStatus").textContent=message;}
  function playReturn(manual=false){
    const audio=$("guestReturnAudio"),stream=audio.srcObject,epoch=returnEpoch;if(!stream||leaving)return;
    const current=()=>!leaving&&returnEpoch===epoch&&audio.srcObject===stream;
    Promise.resolve(audio.play()).then(()=>{if(current())$("guestRoomAudio").hidden=true;}).catch(()=>{if(current()){$("guestRoomAudio").hidden=false;if(manual)status("Audio is paused","Check the browser’s sound permissions and try again.");}});
  }
  function peerNotice(event){
    if(event?.scope==="peer"&&event.peer_id){
      if(["peer_reconnecting","peer_disconnected","peer_failed"].includes(event.state))peerWarnings.set(event.peer_id,event.state);
      else if(["connected","peer_removed"].includes(event.state))peerWarnings.delete(event.peer_id);
    }
    const notice=$("guestPeerNotice");notice.hidden=peerWarnings.size===0;
    notice.textContent=peerWarnings.size?(Array.from(peerWarnings.values()).includes("peer_failed")?"A studio audio/video connection could not recover. Other connections stay active. Ask the producer to reopen the affected studio view.":"A studio audio/video connection is reconnecting. Other connections stay active."):"";
    mediaHint();
  }
  const audioErrors={sound_file_too_large:"Choose an audio file smaller than 10 MB.",sound_duration_limit:"Choose a sound no longer than 30 seconds.",sound_slot_limit:"Remove a sound before adding another. There are 6 spaces.",sound_file_invalid:"This file could not be read as audio. Try WAV, MP3 or another supported audio file.",sound_decode_failed:"This browser could not read the audio. Try a different file.",sound_load_busy:"Wait for the current sound to finish loading.",audio_unavailable:"Audio processing could not start. Try turning the microphone off and on.",sound_unavailable:"That sound is no longer available. Add it again.",audio_closed:"Turn on your microphone to use sounds."};
  Object.assign(audioErrors,{sound_read_failed:"This file could not be read. Choose it again or try another audio file.",sound_cancelled:"Sound stopped.",unknown_sound:"That sound is no longer available. Add it again.",sound_playback_limit:"Four sounds are already playing. Wait or choose Stop sounds.",sound_import_busy:"Wait for the current sound to finish loading.",sound_file_type:"Choose a supported audio file, such as WAV or MP3.",sound_memory_limit:"There isn’t enough room for this sound. Remove a clip or choose a shorter mono or stereo file."});
  function audioState(value){
    const state=value||microphone?.snapshot?.(),available=Boolean(microphone)&&!leaving;
    for(const id of Object.keys(cueButtons)){$(id).disabled=!available||audioBusy||busy;$(id).title=available?"Send this sound with your microphone.":"Turn on your microphone first.";}
    $("guestSoundFile").disabled=!available||audioBusy||busy;$("guestSoundsStop").disabled=!available||(!state?.playing&&!audioBusy);
    const sounds=state?.sounds||[],wanted=new Set(sounds.map(sound=>sound.id)),list=$("guestSoundList");
    for(const [id,row] of soundRows)if(!wanted.has(id)){const focused=row.node.contains?.(document.activeElement);row.node.remove();soundRows.delete(id);if(focused)pendingSoundFocus=soundRows.values().next().value?.play||$("guestSoundFile");}
    for(const sound of sounds){
      let row=soundRows.get(sound.id);
      if(!row){const node=document.createElement("div"),label=document.createElement("span"),play=document.createElement("button"),remove=document.createElement("button");node.className="guest-sound-row";play.type=remove.type="button";play.textContent="Play";remove.textContent="Remove";play.addEventListener("click",()=>audioAction(owner=>owner.playSound(sound.id)));remove.addEventListener("click",()=>audioAction(owner=>owner.removeSound(sound.id)));node.append(label,play,remove);list.append(node);row={node,label,play,remove};soundRows.set(sound.id,row);}
      row.label.textContent=sound.label;row.play.setAttribute("aria-label","Play "+sound.label);row.remove.setAttribute("aria-label","Remove "+sound.label);row.play.disabled=row.remove.disabled=!available||audioBusy||busy;
    }
    if(pendingSoundFocus&&!audioBusy&&!busy&&!pendingSoundFocus.disabled){if(!document.activeElement||document.activeElement===document.body)pendingSoundFocus.focus?.();pendingSoundFocus=null;}
    if(!available)$("guestAudioStatus").textContent="Turn on your microphone to use voice effects and sounds.";
    else if(state?.error)$("guestAudioStatus").textContent=audioErrors[state.error]||"Voice processing is unavailable. Your microphone is unfiltered.";
    else if(state?.loading)$("guestAudioStatus").textContent="Loading your sound on this device…";
    else if(state?.playing){$("guestAudioStatus").textContent=joined?"Playing into your microphone mix. The producer controls what reaches Program.":"Sound is active in your private mix. Join backstage to share it.";$("guestAudioStatus").setAttribute("data-playing","true");}
    else if($("guestAudioStatus").getAttribute("data-playing")==="true"){$("guestAudioStatus").setAttribute("data-playing","false");$("guestAudioStatus").textContent="Sound finished. Ready for the next cue.";}
  }
  async function audioAction(action,message="Ready. Sounds follow your microphone into the room."){
    const owner=microphone;if(!owner||audioBusy||leaving)return;const focused=document.activeElement,restoreFocus=Object.keys(cueButtons).some(id=>$(id)===focused)||Array.from(soundRows.values()).some(row=>row.play===focused||row.remove===focused);audioBusy=true;audioState();
    try{await action(owner);if(microphone===owner&&!leaving){audioFeedback("");audioState();if(!owner.snapshot?.().playing)$("guestAudioStatus").textContent=message;}}
    catch(error){if(microphone===owner&&!leaving)audioFeedback(audioErrors[error?.message]||"This sound could not play. Try a supported audio file or restart your microphone.");}
    finally{if(microphone===owner&&!leaving){audioBusy=false;audioState();if(restoreFocus&&focused?.isConnected&&!focused.disabled&&document.activeElement===document.body)focused.focus();}}
  }
  function audioSettings(){return {...gateSettings,...voiceSettings};}
  function configureVoice(){
    const preset=$("guestVoicePreset").value;voiceSettings={preset:["natural","deep","radio","robot","megaphone"].includes(preset)?preset:"natural",soundVolume:Math.max(0,Math.min(1,Number($("guestSoundVolume").value)/100||0))};
    $("guestSoundVolumeValue").textContent=Math.round(voiceSettings.soundVolume*100)+"%";$("guestSoundVolume").setAttribute("aria-valuetext",Math.round(voiceSettings.soundVolume*100)+" percent");
    const owner=microphone,selected=voiceSettings.preset;
    if(owner)Promise.resolve(owner.configure(audioSettings())).then(()=>{if(microphone!==owner||leaving||voiceSettings.preset!==selected)return;const result=owner.snapshot?.();if(result?.error){audioState(result);return;}audioFeedback("");if(!result?.playing)$("guestAudioStatus").textContent=selected==="natural"?"Natural voice selected.":"Voice style applied to your microphone.";}).catch(()=>{if(microphone===owner&&!leaving)$("guestAudioStatus").textContent="Voice processing could not start. Try restarting your microphone.";});
  }
  const connectionReasons={
    invalid_signaling_response:"The studio sent a connection update this browser could not accept. Ask the producer to check the connection before rejoining.",
    media_queue_limit:"Too many audio/video changes were waiting to finish. Reconnecting; if this persists, ask the producer to check the connection.",
    media_candidate_limit:"Too many network connection options arrived before audio/video setup completed. Reconnecting; if this persists, ask the producer to check the connection.",
    unsupported_media_channel:"An unsupported connection channel was requested. Ask the producer to check the connection before rejoining.",
    production_state_stalled:"Updates from the production PC stopped. Reconnecting; if this persists, ask the producer to check the studio.",
    media_connection_failed:"The audio/video connection failed. Reconnecting; if this persists, check the connection to the production PC.",
    media_negotiation_failed:"The browser could not agree on the audio/video connection. Reconnecting; if this persists, ask the producer for a new invitation.",
    guest_access_ended:"Your invitation is no longer active. Ask the producer for a new invitation.",
    signaling_unavailable:"The production PC could not be reached. Reconnecting; check the studio connection.",
    signaling_disconnected:"The connection to the production PC closed. Reconnecting; check the studio connection.",
    browser_media_unavailable:"This browser cannot provide the required audio/video connection. Try a supported browser.",
    media_detach_failed:"The browser could not update the shared media. Reconnecting; if this persists, rejoin with a new invitation."
  };
  let lastConnectionReason="";
  function connectionMessage(reason){
    if(Object.prototype.hasOwnProperty.call(connectionReasons,reason)){lastConnectionReason=connectionReasons[reason];lastConnectionCode=reason;$("guestBadge").setAttribute("data-connection-reason",reason);}
    return lastConnectionReason||"Your media is not reaching the room. Reconnecting; if this persists, ask the producer for a new invitation.";
  }
  function programAudioNotice(participant){
    const notice=$("guestProgramAudioNotice"),flags=participant?.program_audio;
    const active=participant&&["waiting","admitted"].includes(participant.state),microphone=active&&flags?.microphone_muted===true,screen=active&&flags?.screen_muted===true;
    const sources=microphone&&screen?"microphone and shared-screen audio":microphone?"microphone":screen?"shared-screen audio":"";
    notice.textContent=sources?`The producer has muted your ${sources} for Program. Backstage audio is unaffected.`:"";
    notice.hidden=!sources;
  }
  function secret(){const bytes=new Uint8Array(32);crypto.getRandomValues(bytes);return Array.from(bytes,x=>x.toString(16).padStart(2,"0")).join("");}
  function setBusy(value){
    busy=value;const secure=root.isSecureContext===true,captureSupported=typeof navigator.mediaDevices?.getUserMedia==="function";
    $("guestJoin").disabled=busy||joining||connecting||leaving||!secure||accessEnded||!invite&&!validSession();
    $("guestJoin").textContent=joining?"Joining…":!invite&&validSession()?"Rejoin backstage":"Join backstage";$("guestJoin").setAttribute("aria-busy",String(joining&&!leaving));
    $("guestJoin").title=!secure?"Open a secure guest link.":accessEnded?"Ask the producer for a new invitation.":!invite&&!validSession()?"Open your private invitation first.":"";
    for(const [id,active] of [["guestCamera",media.camera],["guestMicrophone",media.microphone],["guestCameraDevice",null],["guestMicDevice",null]]){$(id).disabled=leaving||!active&&(busy||!secure||!captureSupported);$(id).title=!active&&!secure?"Camera and microphone need a secure link.":!active&&!captureSupported?"Camera and microphone capture are unavailable in this browser.":"";}
    $("guestScreen").disabled=leaving||!media.screen&&(busy||!secure||typeof navigator.mediaDevices?.getDisplayMedia!=="function");
    $("guestScreen").title=!media.screen&&typeof navigator.mediaDevices?.getDisplayMedia!=="function"?"Screen sharing is not supported in this browser. Camera and mic can still be used.":"";
    const retrying=connecting&&!joining&&!leaving;$("guestReconnect").hidden=(!retryAvailable&&!retrying)||accessEnded||!validSession()||leaving;$("guestReconnect").disabled=busy||joining||connecting||!secure||accessEnded||!validSession();$("guestReconnect").textContent=retrying?"Reconnecting…":"Retry connection";$("guestReconnect").setAttribute("aria-busy",String(retrying));
    for(const [kind,id,onText,offText,pendingText] of [["camera","guestCamera","Turn camera off","Turn camera on","Starting camera…"],["microphone","guestMicrophone","Turn mic off","Turn mic on","Starting mic…"],["screen","guestScreen","Stop sharing","Share screen","Choose a screen…"]]){
      const pending=!leaving&&pendingCapture?.kind===kind&&pendingCapture.generation===captureGeneration[kind];$(id).textContent=media[kind]?onText:pending?pendingText:offText;$(id).setAttribute("aria-busy",String(pending));
      if(!media[kind]&&busy&&secure&&captureSupported)$(id).title=pending?"Complete the browser request, or cancel it to try again.":"Wait for the current device request to finish.";
    }
    audioState();
  }
  function synchronize(publish=true){
    if(publish)publisher?.setTracks({...media});
    const camera=Boolean(media.camera),mic=Boolean(media.microphone),screen=Boolean(media.screen);
    for(const [id,on,onText,offText] of [["guestCamera",camera,"Turn camera off","Turn camera on"],["guestMicrophone",mic,"Turn mic off","Turn mic on"],["guestScreen",screen,"Stop sharing","Share screen"]]){$(id).setAttribute("aria-pressed",String(on));$(id).textContent=on?onText:offText;}
    $("guestCameraEmpty").hidden=camera;if($("guestCameraPreview").srcObject?.getVideoTracks()[0]!==media.camera)$("guestCameraPreview").srcObject=camera?new MediaStream([media.camera]):null;
    $("guestScreenPreviewPanel").hidden=!screen;if($("guestScreenPreview").srcObject?.getVideoTracks()[0]!==media.screen)$("guestScreenPreview").srcObject=screen?new MediaStream([media.screen]):null;
    mediaHint();setBusy(busy);
  }
  function mediaHint(){
    $("guestMediaHint").textContent=leaving?"Your camera, microphone and screen are off.":!roomConnected?
      (joined||connecting||joining||accessEnded||lastConnectionCode?"Room connection is paused or pending. Delivery is not confirmed; enabled sources remain on until you turn them off.":media.screen?"Your screen preview stays on this device until you join. Screen audio is not being shared.":"Your preview stays on this device until you join."):
      peerWarnings.size?"A studio media connection is paused. Some enabled sources may not reach the room; you can still turn them off.":
      media.screen?(media.screen_audio?"Your screen and its audio are enabled for sharing with the producer.":"Your screen is enabled for sharing with the producer. This selection has no screen audio."):"Enabled sources are available to the producer. Only selected sources reach Program.";
  }
  function stop(kind){const track=media[kind];media[kind]=null;if(kind==="microphone"&&microphone){const owner=microphone;microphone=null;owner.close();audioBusy=false;audioFeedback("");$("guestGateStatus").textContent="Microphone off";audioState();}else if(track){track.onended=null;track.stop();}}
  function stopSource(kind,message){captureGeneration[kind]++;stop(kind);if(kind==="screen")stop("screen_audio");synchronize();feedback("guestDeviceStatus",message);}
  function configureGate(){
    gateSettings={enabled:$("guestNoiseGate").getAttribute("aria-pressed")==="true",thresholdDb:Number($("guestGateThreshold").value)};
    $("guestGateValue").textContent=gateSettings.thresholdDb+" dB";$("guestGateThreshold").setAttribute("aria-valuetext",gateSettings.thresholdDb+" decibels");
    try{localStorage.setItem("producer.guest.gate.v1",JSON.stringify(gateSettings));}catch{}
    const owner=microphone;if(owner)Promise.resolve(owner.configure(audioSettings())).catch(()=>{if(microphone===owner&&!leaving)$("guestGateStatus").textContent="Unavailable · audio unfiltered";});else $("guestGateStatus").textContent="Microphone off";
  }
  async function devices(epoch,kind,generation){
    const current=()=>epoch===mediaEpoch&&!leaving&&captureGeneration[kind]===generation;
    try{
      const values=navigator.mediaDevices?.enumerateDevices?await navigator.mediaDevices.enumerateDevices():[];
      if(!current())return;
      for(const [id,type,label,key] of [["guestCameraDevice","videoinput","Camera","camera"],["guestMicDevice","audioinput","Microphone","microphone"]]){
        const select=$(id),current=deviceSelection[key]||select.value;select.replaceChildren(new Option("Default "+label.toLowerCase(),""));
        values.filter(d=>d.kind===type).forEach((d,i)=>select.add(new Option(d.label||`${label} ${i+1}`,d.deviceId)));
        if(current&&!values.some(d=>d.kind===type&&d.deviceId===current))select.add(new Option("Current "+label.toLowerCase(),current));select.value=current;
      }
    }catch(_){if(current()){const select=$(kind==="camera"?"guestCameraDevice":"guestMicDevice"),selected=deviceSelection[kind];if(selected){if(!Array.from(select.options||[]).some(option=>option.value===selected))select.add(new Option("Current "+(kind==="camera"?"camera":"microphone"),selected));select.value=selected;}feedback("guestDeviceStatus",(kind==="camera"?"Camera":"Microphone")+" is on. Device choices could not refresh; your current capture continues.");}}
  }
  async function capture(kind,reselect=false){
    if(leaving)return;
    if(media[kind]&&!reselect){stopSource(kind,(kind==="camera"?"Camera":"Microphone")+" is off.");return;}
    if(busy)return;if(!root.isSecureContext||typeof navigator.mediaDevices?.getUserMedia!=="function"){feedback("guestDeviceStatus","Camera and microphone capture need a secure link and a supported browser.");setBusy(false);return;}const epoch=mediaEpoch,generation=++captureGeneration[kind],current=()=>epoch===mediaEpoch&&!leaving&&captureGeneration[kind]===generation;pendingCapture={kind,generation};setBusy(true);feedback("guestDeviceStatus","Waiting for "+(kind==="camera"?"camera":"microphone")+" access… Allow access in your browser if asked.");
    try{
      const device=$(kind==="camera"?"guestCameraDevice":"guestMicDevice").value;
      const options=kind==="camera"?{video:{width:{ideal:1280},height:{ideal:720},...(device?{deviceId:{exact:device}}:{})},audio:false}:{video:false,audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,...(device?{deviceId:{exact:device}}:{})}};
      const stream=await navigator.mediaDevices.getUserMedia(options);
      if(!current()){stream.getTracks().forEach(track=>track.stop());return;}
      feedback("guestDeviceStatus","Setting up your "+(kind==="camera"?"camera":"microphone")+"…");
      const track=stream.getTracks()[0];if(!track)throw {name:"NotFoundError"};stop(kind);media[kind]=track;deviceSelection[kind]=track.getSettings?.().deviceId||device;
      if(kind==="microphone"&&root.ProducerGuestMicrophone){
        const owner=root.ProducerGuestMicrophone.create(track,processed=>{if(microphone===owner&&!leaving){media.microphone=processed;synchronize();}},value=>{if(microphone===owner)$("guestGateStatus").textContent=value;},value=>{if(microphone===owner&&!leaving)audioState(value);});
        microphone=owner;track.onended=()=>{if(microphone===owner)stopSource("microphone","Microphone disconnected or stopped. Turn it on again when the device is ready.");};synchronize(false);
        await owner.configure(audioSettings());
        if(!current())return;
        $("guestAudioStatus").textContent="Your microphone is ready for voice effects and sounds.";audioState();
      }else track.onended=()=>{if(media[kind]===track)stopSource(kind,(kind==="camera"?"Camera":"Microphone")+" disconnected or stopped. Turn it on again when the device is ready.");};
      synchronize();feedback("guestDeviceStatus",(kind==="camera"?"Camera":"Microphone")+" is on.");await devices(epoch,kind,generation);
    }catch(error){if(current()){feedback("guestDeviceStatus",deviceError(error,kind));$(kind==="camera"?"guestCameraDevice":"guestMicDevice").value=deviceSelection[kind];}}
    finally{if(epoch===mediaEpoch&&!leaving){if(pendingCapture?.kind===kind&&pendingCapture.generation===generation)pendingCapture=null;setBusy(false);}}
  }
  async function screen(){
    if(leaving)return;if(media.screen){stopSource("screen","Screen capture is off.");return;}
    if(busy)return;if(!root.isSecureContext||typeof navigator.mediaDevices?.getDisplayMedia!=="function"){feedback("guestDeviceStatus","Screen sharing is unavailable in this browser. Use a supported desktop browser.");return;}const epoch=mediaEpoch,generation=++captureGeneration.screen,current=()=>epoch===mediaEpoch&&!leaving&&captureGeneration.screen===generation;pendingCapture={kind:"screen",generation};setBusy(true);feedback("guestDeviceStatus","Choose a screen, window or tab in your browser to share.");
    try{
      const stream=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:{ideal:30,max:30}},audio:true});
      if(!current()){stream.getTracks().forEach(track=>track.stop());return;}
      media.screen=stream.getVideoTracks()[0]||null;media.screen_audio=stream.getAudioTracks()[0]||null;
      const video=media.screen,audio=media.screen_audio;
      if(video)video.onended=()=>{if(media.screen===video)stopSource("screen","Screen capture ended. Choose Share screen to select it again.");};
      if(audio)audio.onended=()=>{if(media.screen_audio===audio){stop("screen_audio");synchronize();feedback("guestDeviceStatus","Screen audio stopped. Screen video is still on.");}};synchronize();feedback("guestDeviceStatus",video?"Screen capture is on.":"No screen was shared. You can try again when ready.");
    }catch(error){if(current())feedback("guestDeviceStatus",error.name==="NotAllowedError"?"No screen was shared. You can try again when ready.":deviceError(error,"screen"));}
    finally{if(epoch===mediaEpoch&&!leaving){if(pendingCapture?.kind==="screen"&&pendingCapture.generation===generation)pendingCapture=null;setBusy(false);}}
  }
  function roomState(value){
    if(leaving)return;const participant=value.participant;roomConnected=Boolean(participant&&["waiting","admitted"].includes(participant.state)&&participant.connected!==false);if(!participant){programAudioNotice();mediaHint();return;}
    joined=true;$("guestName").value=participant.name;$("guestName").disabled=true;$("guestJoinForm").hidden=true;$("guestLeave").hidden=false;
    const onAir=(value.on_air_sources||[]).some(s=>s.startsWith(`guest:${participant.id}:`));
    $("guestBadge").textContent=onAir?"ON PROGRAM":participant.state==="admitted"?"BACKSTAGE":"WAITING FOR PRODUCER";$("guestBadge").classList.toggle("on-air",onAir);
    status(onAir?"You’re on Program":participant.state==="admitted"?"You’re backstage":"Waiting for the producer",onAir?"The producer selected your source for the production. You can still turn off your media.":participant.state==="admitted"?"You can talk with the room. Your sources stay off Program until the producer selects them.":"The producer can preview your enabled sources. You’re not on Program.");
    programAudioNotice(participant);
    synchronize(false);
  }
  function connectionFailure(reason,terminal=false){
    roomConnected=false;
    const recoverable=["production_state_stalled","signaling_unavailable","signaling_disconnected","media_connection_failed","media_negotiation_failed"].includes(reason);
    if(reason==="guest_access_ended")accessEnded=true;
    retryAvailable=terminal&&recoverable&&validSession()&&!accessEnded;
    let message=connectionMessage(reason);if(retryAvailable)message=message.split(".")[0]+". Choose Retry connection to try again.";
    feedback("guestConnectionStatus",message);status(accessEnded?"Invitation ended":"Room connection paused",accessEnded?"This session can no longer join the production.":"Your sources are not reaching the room.");mediaHint();setBusy(busy);
  }
  async function connect(){
    if(leaving||accessEnded||!root.isSecureContext||!validSession())return false;
    const epoch=++connectionEpoch,previous=publisher;publisher=null;roomConnected=false;previous?.close();returnEpoch++;$("guestReturnAudio").srcObject=null;$("guestReturnAudio").pause();$("guestRoomAudio").hidden=true;peerWarnings.clear();peerNotice();retryAvailable=false;connecting=true;lastConnectionCode="";lastConnectionReason="";feedback("guestConnectionStatus",joining?"Connecting to the production PC…":"Reconnecting to the production PC…");if(!joining)status("Reconnecting…","Your enabled sources remain on. You can still turn them off.");mediaHint();setBusy(busy);
    let owner=null,terminal=false;const owned=()=>!leaving&&connectionEpoch===epoch&&publisher===owner,current=()=>owned()&&!terminal;
    try{
      if(typeof root.ProducerGuestMedia?.createPublisher!=="function")throw Error("browser_media_unavailable");
      owner=root.ProducerGuestMedia.createPublisher({token,
        onState:message=>{if(current()){if(message.participant&&["waiting","admitted"].includes(message.participant.state))feedback("guestConnectionStatus","");roomState(message);}},
        onReturnAudio:stream=>{if(!current())return;returnEpoch++;const audio=$("guestReturnAudio");audio.srcObject=stream;$("guestRoomAudio").hidden=true;if(stream)playReturn();else audio.pause();},
        onConnection:event=>{if(!current())return;if(event.scope==="peer"){peerNotice(event);return;}if(event.state==="connected"){lastConnectionReason=lastConnectionCode="";retryAvailable=false;$("guestBadge").setAttribute("data-connection-reason","");feedback("guestConnectionStatus","");}if(["disconnected","reconnecting","failed","closed"].includes(event.state)){terminal=event.state==="closed";peerWarnings.clear();peerNotice();programAudioNotice();connectionFailure(event.reason||lastConnectionCode,terminal);$("guestBadge").textContent="DISCONNECTED";$("guestBadge").classList.remove("on-air");}},
        onError:event=>{if(current()){programAudioNotice();connectionFailure(event?.reason);}}
      });
      publisher=owner;owner.setTracks({...media});await owner.connect();return current();
    }catch(error){if(owned()){terminal=true;connectionFailure(error?.message||lastConnectionCode,true);}return false;}
    finally{if(owned()){connecting=false;setBusy(busy);}}
  }
  async function retryConnection(){
    if(busy||joining||connecting||leaving||!retryAvailable||accessEnded||!validSession())return;
    await connect();
  }
  async function join(event){
    event.preventDefault();if(busy||joining||connecting||leaving||accessEnded||!root.isSecureContext||!invite&&!validSession()){setBusy(busy);return;}
    const epoch=mediaEpoch;joining=true;setBusy(busy);mediaHint();status("Joining…","Your sources stay backstage until selected by the producer.");
    try{
      if(invite){
        token=validSession()?token:secret();const attemptToken=token;
        const response=await fetch("/guest/join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({invite_token:invite,name:$("guestName").value.trim(),session_token:token})});
        if(epoch!==mediaEpoch||leaving){if(response.ok)try{await fetch("/guest/leave",{method:"POST",headers:{Authorization:"Bearer "+attemptToken}});}catch{}return;}
        if(!response.ok){if([401,403,410].includes(response.status))accessEnded=true;throw Error("join_failed");}invite=null;
      }
      if(epoch!==mediaEpoch||leaving)return;
      if(!validSession())throw Error("missing_invite");try{sessionStorage.setItem(STORE,token);}catch{}$("guestLeave").hidden=false;await connect();
    }catch{if(epoch===mediaEpoch&&!leaving){feedback("guestConnectionStatus","Check your display name and invitation. Ask the producer for a new link if needed.");status("Unable to join","Your preview is still private on this device.");}}
    finally{if(epoch===mediaEpoch&&!leaving){joining=false;setBusy(busy);}}
  }
  async function leave(){
    leaving=true;mediaEpoch++;connectionEpoch++;connecting=joining=false;retryAvailable=false;feedback("guestConnectionStatus","");feedback("guestDeviceStatus","");peerWarnings.clear();peerNotice();programAudioNotice();setBusy(true);publisher?.close();publisher=null;for(const key of Object.keys(media))stop(key);synchronize();$("guestReturnAudio").srcObject=null;$("guestReturnAudio").pause();
    const prior=token;token="";joined=false;try{sessionStorage.removeItem(STORE);}catch{}
    $("guestLeave").hidden=true;$("guestRoomAudio").hidden=true;$("guestBadge").textContent="LEFT THE ROOM";$("guestBadge").classList.remove("on-air");status("You’ve left the room","Your camera, microphone and screen are off.");
    if(prior){try{await fetch("/guest/leave",{method:"POST",headers:{Authorization:"Bearer "+prior}});}catch{}}
  }
  $("guestNoiseGate").setAttribute("aria-pressed",String(gateSettings.enabled));$("guestGateThreshold").value=String(gateSettings.thresholdDb);$("guestGateValue").textContent=gateSettings.thresholdDb+" dB";$("guestGateThreshold").setAttribute("aria-valuetext",gateSettings.thresholdDb+" decibels");
  $("guestNoiseGate").addEventListener("click",()=>{$("guestNoiseGate").setAttribute("aria-pressed",String($("guestNoiseGate").getAttribute("aria-pressed")!=="true"));configureGate();});
  $("guestGateThreshold").addEventListener("input",configureGate);
  $("guestVoicePreset").value=voiceSettings.preset;$("guestSoundVolume").value=String(voiceSettings.soundVolume*100);$("guestSoundVolume").setAttribute("aria-valuetext",Math.round(voiceSettings.soundVolume*100)+" percent");
  $("guestVoicePreset").addEventListener("change",configureVoice);$("guestSoundVolume").addEventListener("input",configureVoice);
  for(const [id,cue] of Object.entries(cueButtons))$(id).addEventListener("click",()=>audioAction(owner=>owner.playCue(cue)));
  $("guestSoundsStop").addEventListener("click",()=>{microphone?.stopSounds();audioFeedback("");audioState();$("guestAudioStatus").textContent="Sounds stopped. Your voice is unchanged.";});
  $("guestSoundFile").addEventListener("change",()=>{const file=$("guestSoundFile").files?.[0];$("guestSoundFile").value="";if(file)audioAction(owner=>owner.addSound(file),"Sound added. Choose Play when you’re ready.");});
  $("guestReconnect").addEventListener("click",retryConnection);
  $("guestJoinForm").addEventListener("submit",join);$("guestCamera").addEventListener("click",()=>capture("camera"));$("guestMicrophone").addEventListener("click",()=>capture("microphone"));$("guestScreen").addEventListener("click",screen);
  $("guestCameraDevice").addEventListener("change",()=>{if(media.camera)capture("camera",true);});$("guestMicDevice").addEventListener("change",()=>{if(media.microphone)capture("microphone",true);});
  $("guestLeave").addEventListener("click",leave);$("guestRoomAudio").addEventListener("click",()=>playReturn(true));
  root.addEventListener("pagehide",()=>{leaving=true;mediaEpoch++;connectionEpoch++;programAudioNotice();publisher?.close();for(const key of Object.keys(media))stop(key);});
  if(!root.isSecureContext){status("A secure link is needed","Camera and microphone access need a secure HTTPS guest link. Ask the producer for one.");}
  else if(!invite&&!validSession()){status("Invitation needed","Open the guest link provided by your producer to join this room.");$("guestJoin").disabled=true;}
  else if(validSession()){$("guestJoin").textContent="Rejoin backstage";$("guestName").required=false;status("Resume your guest session","Choose your media, then rejoin the room.");}
  if(!navigator.mediaDevices?.getDisplayMedia){$("guestScreen").title="Screen sharing is not supported in this browser. Camera and mic can still be used.";$("guestMediaHint").textContent="This browser supports camera and mic; use a supported desktop browser to share your screen.";}
  if(typeof navigator.mediaDevices?.getUserMedia!=="function")feedback("guestDeviceStatus","Camera and microphone capture are unavailable in this browser. Use a supported browser with your secure guest link.");
  setBusy(false);
})(window);
