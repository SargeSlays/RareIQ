(function(root){
  "use strict";
  const $=id=>document.getElementById(id), media={microphone:null,camera:null,screen:null,screen_audio:null};
  const STORE="producer.guest.session.v1";
  let invite=new URLSearchParams(location.hash.slice(1)).get("invite"),token="",publisher=null,joined=false,busy=false,leaving=false,mediaEpoch=0,microphone=null;
  let gateSettings={enabled:false,thresholdDb:-45};
  let voiceSettings={preset:"natural",soundVolume:.5},audioBusy=false,soundListStamp="",returnEpoch=0;
  const cueButtons={guestCueChime:"chime",guestCueSuccess:"success",guestCueBuzzer:"buzzer",guestCueDrumroll:"drumroll"};
  const peerWarnings=new Map();
  try{const saved=JSON.parse(localStorage.getItem("producer.guest.gate.v1")||"null");if(saved)gateSettings={enabled:saved.enabled===true,thresholdDb:Math.max(-70,Math.min(-10,Number.isFinite(saved.thresholdDb)?saved.thresholdDb:-45))};}catch{}
  history.replaceState(null,"",location.pathname);
  if(!invite){try{token=sessionStorage.getItem(STORE)||"";}catch{}}
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
  }
  const audioErrors={sound_file_too_large:"Choose an audio file smaller than 10 MB.",sound_duration_limit:"Choose a sound no longer than 30 seconds.",sound_slot_limit:"Remove a sound before adding another. There are 6 spaces.",sound_file_invalid:"This file could not be read as audio. Try WAV, MP3 or another supported audio file.",sound_decode_failed:"This browser could not read the audio. Try a different file.",sound_load_busy:"Wait for the current sound to finish loading.",audio_unavailable:"Audio processing could not start. Try turning the microphone off and on.",sound_unavailable:"That sound is no longer available. Add it again.",audio_closed:"Turn on your microphone to use sounds."};
  Object.assign(audioErrors,{sound_read_failed:"This file could not be read. Choose it again or try another audio file.",sound_cancelled:"Sound stopped.",unknown_sound:"That sound is no longer available. Add it again.",sound_playback_limit:"Four sounds are already playing. Wait or choose Stop sounds.",sound_import_busy:"Wait for the current sound to finish loading.",sound_file_type:"Choose a supported audio file, such as WAV or MP3.",sound_memory_limit:"There isn’t enough room for this sound. Remove a clip or choose a shorter mono or stereo file."});
  function audioState(value){
    const state=value||microphone?.snapshot?.(),available=Boolean(microphone)&&!leaving;
    for(const id of Object.keys(cueButtons)){$(id).disabled=!available||audioBusy||busy;$(id).title=available?"Send this sound with your microphone.":"Turn on your microphone first.";}
    $("guestSoundFile").disabled=!available||audioBusy||busy;$("guestSoundsStop").disabled=!available||(!state?.playing&&!audioBusy);
    const sounds=state?.sounds||[],stamp=JSON.stringify([available,audioBusy,sounds]);
    if(stamp!==soundListStamp){soundListStamp=stamp;const list=$("guestSoundList");list.replaceChildren();
      for(const sound of sounds){const row=document.createElement("div"),label=document.createElement("span"),play=document.createElement("button"),remove=document.createElement("button");row.className="guest-sound-row";label.textContent=sound.label;play.type=remove.type="button";play.textContent="Play";remove.textContent="Remove";play.setAttribute("aria-label","Play "+sound.label);remove.setAttribute("aria-label","Remove "+sound.label);play.disabled=remove.disabled=!available||audioBusy;play.addEventListener("click",()=>audioAction(owner=>owner.playSound(sound.id)));remove.addEventListener("click",()=>audioAction(owner=>owner.removeSound(sound.id)));row.append(label,play,remove);list.append(row);}
    }
    if(!available)$("guestAudioStatus").textContent="Turn on your microphone to use voice effects and sounds.";
    else if(state?.error)$("guestAudioStatus").textContent=audioErrors[state.error]||"Voice processing is unavailable. Your microphone is unfiltered.";
    else if(state?.loading)$("guestAudioStatus").textContent="Loading your sound on this device…";
    else if(state?.playing){$("guestAudioStatus").textContent=joined?"Playing into your microphone mix. The producer controls what reaches Program.":"Sound is active in your private mix. Join backstage to share it.";$("guestAudioStatus").setAttribute("data-playing","true");}
    else if($("guestAudioStatus").getAttribute("data-playing")==="true"){$("guestAudioStatus").setAttribute("data-playing","false");$("guestAudioStatus").textContent="Sound finished. Ready for the next cue.";}
  }
  async function audioAction(action,message="Ready. Sounds follow your microphone into the room."){
    const owner=microphone;if(!owner||audioBusy||leaving)return;audioBusy=true;audioState();
    try{await action(owner);if(microphone===owner&&!leaving){audioState();if(!owner.snapshot?.().playing)$("guestAudioStatus").textContent=message;}}
    catch(error){if(microphone===owner&&!leaving)$("guestAudioStatus").textContent=audioErrors[error?.message]||"This sound could not play. Try a supported audio file or restart your microphone.";}
    finally{if(microphone===owner&&!leaving){audioBusy=false;audioState();}}
  }
  function audioSettings(){return {...gateSettings,...voiceSettings};}
  function configureVoice(){
    const preset=$("guestVoicePreset").value;voiceSettings={preset:["natural","deep","radio","robot","megaphone"].includes(preset)?preset:"natural",soundVolume:Math.max(0,Math.min(1,Number($("guestSoundVolume").value)/100||0))};
    $("guestSoundVolumeValue").textContent=Math.round(voiceSettings.soundVolume*100)+"%";
    const owner=microphone,selected=voiceSettings.preset;
    if(owner)Promise.resolve(owner.configure(audioSettings())).then(()=>{if(microphone!==owner||leaving||voiceSettings.preset!==selected)return;const result=owner.snapshot?.();if(result?.error){audioState(result);return;}if(!result?.playing)$("guestAudioStatus").textContent=selected==="natural"?"Natural voice selected.":"Voice style applied to your microphone.";}).catch(()=>{if(microphone===owner&&!leaving)$("guestAudioStatus").textContent="Voice processing could not start. Try restarting your microphone.";});
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
    if(Object.prototype.hasOwnProperty.call(connectionReasons,reason)){lastConnectionReason=connectionReasons[reason];$("guestBadge").setAttribute("data-connection-reason",reason);}
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
  function setBusy(value){busy=value;$("guestJoin").disabled=value;for(const id of ["guestCamera","guestMicrophone"])$(id).disabled=value||!root.isSecureContext;$("guestScreen").disabled=value||!navigator.mediaDevices?.getDisplayMedia;audioState();}
  function synchronize(publish=true){
    if(publish)publisher?.setTracks({...media});
    const camera=Boolean(media.camera),mic=Boolean(media.microphone),screen=Boolean(media.screen);
    for(const [id,on,onText,offText] of [["guestCamera",camera,"Turn camera off","Turn camera on"],["guestMicrophone",mic,"Turn mic off","Turn mic on"],["guestScreen",screen,"Stop sharing","Share screen"]]){$(id).setAttribute("aria-pressed",String(on));$(id).textContent=on?onText:offText;}
    $("guestCameraEmpty").hidden=camera;if($("guestCameraPreview").srcObject?.getVideoTracks()[0]!==media.camera)$("guestCameraPreview").srcObject=camera?new MediaStream([media.camera]):null;
    $("guestScreenPreviewPanel").hidden=!screen;if($("guestScreenPreview").srcObject?.getVideoTracks()[0]!==media.screen)$("guestScreenPreview").srcObject=screen?new MediaStream([media.screen]):null;
    $("guestMediaHint").textContent=leaving?"Your camera, microphone and screen are off.":screen?(media.screen_audio?"Your selected screen and its audio are shared.":"Your screen is shared. This selection has no screen audio."):(joined?"Enabled sources are shared with the producer. Only selected sources reach Program.":"Your preview stays on this device until you join.");
  }
  function stop(kind){const track=media[kind];media[kind]=null;if(kind==="microphone"&&microphone){const owner=microphone;microphone=null;owner.close();audioBusy=false;$("guestGateStatus").textContent="Microphone off";audioState();}else if(track){track.onended=null;track.stop();}}
  function configureGate(){
    gateSettings={enabled:$("guestNoiseGate").getAttribute("aria-pressed")==="true",thresholdDb:Number($("guestGateThreshold").value)};
    $("guestGateValue").textContent=gateSettings.thresholdDb+" dB";
    try{localStorage.setItem("producer.guest.gate.v1",JSON.stringify(gateSettings));}catch{}
    const owner=microphone;if(owner)Promise.resolve(owner.configure(audioSettings())).catch(()=>{if(microphone===owner&&!leaving)$("guestGateStatus").textContent="Unavailable · audio unfiltered";});else $("guestGateStatus").textContent="Microphone off";
  }
  async function devices(){
    if(!navigator.mediaDevices?.enumerateDevices)return;
    const values=await navigator.mediaDevices.enumerateDevices();
    for(const [id,kind,label] of [["guestCameraDevice","videoinput","Camera"],["guestMicDevice","audioinput","Microphone"]]){
      const select=$(id),current=select.value;select.replaceChildren(new Option("Default "+label.toLowerCase(),""));
      values.filter(d=>d.kind===kind).forEach((d,i)=>select.add(new Option(d.label||`${label} ${i+1}`,d.deviceId)));select.value=current;
    }
  }
  async function capture(kind,reselect=false){
    if(busy||leaving)return;const epoch=mediaEpoch;setBusy(true);
    try{
      if(media[kind]&&!reselect){stop(kind);synchronize();return;}
      const device=$(kind==="camera"?"guestCameraDevice":"guestMicDevice").value;
      const options=kind==="camera"?{video:{width:{ideal:1280},height:{ideal:720},...(device?{deviceId:{exact:device}}:{})},audio:false}:{video:false,audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,...(device?{deviceId:{exact:device}}:{})}};
      const stream=await navigator.mediaDevices.getUserMedia(options);
      if(epoch!==mediaEpoch||leaving){stream.getTracks().forEach(track=>track.stop());return;}
      const track=stream.getTracks()[0];stop(kind);media[kind]=track;
      if(kind==="microphone"&&root.ProducerGuestMicrophone){
        const owner=root.ProducerGuestMicrophone.create(track,processed=>{if(microphone===owner&&!leaving){media.microphone=processed;synchronize();}},value=>{if(microphone===owner)$("guestGateStatus").textContent=value;},value=>{if(microphone===owner&&!leaving)audioState(value);});
        microphone=owner;track.onended=()=>{if(microphone===owner){stop("microphone");synchronize();}};
        await owner.configure(audioSettings());
        if(epoch!==mediaEpoch||leaving)return;
        $("guestAudioStatus").textContent="Your microphone is ready for voice effects and sounds.";audioState();
      }else track.onended=()=>{if(media[kind]===track){media[kind]=null;synchronize();}};
      synchronize();await devices();
    }catch(error){if(epoch===mediaEpoch&&!leaving)status("Check your device",error.name==="NotAllowedError"?"Permission was not granted. Allow this device in your browser, then try again.":"This device is unavailable. Choose another device or close the app using it.");}
    finally{if(epoch===mediaEpoch&&!leaving)setBusy(false);}
  }
  async function screen(){
    if(busy||leaving)return;const epoch=mediaEpoch;setBusy(true);
    try{
      if(media.screen){stop("screen");stop("screen_audio");synchronize();return;}
      const stream=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:{ideal:30,max:30}},audio:true});
      if(epoch!==mediaEpoch||leaving){stream.getTracks().forEach(track=>track.stop());return;}
      media.screen=stream.getVideoTracks()[0]||null;media.screen_audio=stream.getAudioTracks()[0]||null;
      if(media.screen)media.screen.onended=()=>{stop("screen");stop("screen_audio");synchronize();};synchronize();
    }catch(error){if(epoch===mediaEpoch&&!leaving)status("Screen sharing stopped",error.name==="NotAllowedError"?"No screen was shared. You can try again when ready.":"This browser could not share that screen. Try a different window or browser.");}
    finally{if(epoch===mediaEpoch&&!leaving)setBusy(false);}
  }
  function roomState(value){
    if(leaving)return;const participant=value.participant;if(!participant){programAudioNotice();return;}
    joined=true;$("guestName").value=participant.name;$("guestName").disabled=true;$("guestJoinForm").hidden=true;$("guestLeave").hidden=false;
    const onAir=(value.on_air_sources||[]).some(s=>s.startsWith(`guest:${participant.id}:`));
    $("guestBadge").textContent=onAir?"ON PROGRAM":participant.state==="admitted"?"BACKSTAGE":"WAITING FOR PRODUCER";$("guestBadge").classList.toggle("on-air",onAir);
    status(onAir?"You’re on Program":participant.state==="admitted"?"You’re backstage":"Waiting for the producer",onAir?"The producer selected your source for the production. You can still turn off your media.":participant.state==="admitted"?"You can talk with the room. Your sources stay off Program until the producer selects them.":"The producer can preview your enabled sources. You’re not on Program.");
    programAudioNotice(participant);
    synchronize(false);
  }
  function connect(){
    publisher?.close();peerWarnings.clear();peerNotice();publisher=root.ProducerGuestMedia.createPublisher({token,onState:roomState,
      onReturnAudio:stream=>{returnEpoch++;const audio=$("guestReturnAudio");audio.srcObject=leaving?null:stream;$("guestRoomAudio").hidden=true;if(stream&&!leaving)playReturn();else audio.pause();},
      onConnection:event=>{if(leaving)return;if(event.scope==="peer"){peerNotice(event);return;}if(event.state==="connected"){lastConnectionReason="";$("guestBadge").setAttribute("data-connection-reason","");}if(["disconnected","reconnecting","failed","closed"].includes(event.state)){peerWarnings.clear();peerNotice();programAudioNotice();status("Room connection paused",connectionMessage(event.reason));$("guestBadge").textContent="DISCONNECTED";$("guestBadge").classList.remove("on-air");}},
      onError:event=>{programAudioNotice();if(!leaving)status("Could not connect",connectionMessage(event?.reason));}});
    publisher.setTracks({...media});publisher.connect();
  }
  async function join(event){
    event.preventDefault();if(busy)return;const epoch=mediaEpoch;setBusy(true);leaving=false;status("Joining…","Your sources stay backstage until selected by the producer.");
    try{
      if(invite){token=token||secret();const response=await fetch("/guest/join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({invite_token:invite,name:$("guestName").value.trim(),session_token:token})});if(!response.ok)throw Error("join_failed");invite=null;}
      if(epoch!==mediaEpoch||leaving)return;
      if(!token)throw Error("missing_invite");try{sessionStorage.setItem(STORE,token);}catch{}connect();
    }catch{if(epoch===mediaEpoch&&!leaving)status("Unable to join","Check that you have a current invitation and a display name. Ask the producer for a new link if needed.");}
    finally{if(epoch===mediaEpoch&&!leaving)setBusy(false);}
  }
  async function leave(){
    leaving=true;mediaEpoch++;peerWarnings.clear();peerNotice();programAudioNotice();setBusy(true);publisher?.close();publisher=null;for(const key of Object.keys(media))stop(key);synchronize();$("guestReturnAudio").srcObject=null;$("guestReturnAudio").pause();
    const prior=token;token="";joined=false;try{sessionStorage.removeItem(STORE);}catch{}
    $("guestLeave").hidden=true;$("guestRoomAudio").hidden=true;$("guestBadge").textContent="LEFT THE ROOM";$("guestBadge").classList.remove("on-air");status("You’ve left the room","Your camera, microphone and screen are off.");
    if(prior){try{await fetch("/guest/leave",{method:"POST",headers:{Authorization:"Bearer "+prior}});}catch{}}
  }
  $("guestNoiseGate").setAttribute("aria-pressed",String(gateSettings.enabled));$("guestGateThreshold").value=String(gateSettings.thresholdDb);$("guestGateValue").textContent=gateSettings.thresholdDb+" dB";
  $("guestNoiseGate").addEventListener("click",()=>{$("guestNoiseGate").setAttribute("aria-pressed",String($("guestNoiseGate").getAttribute("aria-pressed")!=="true"));configureGate();});
  $("guestGateThreshold").addEventListener("input",configureGate);
  $("guestVoicePreset").value=voiceSettings.preset;$("guestSoundVolume").value=String(voiceSettings.soundVolume*100);
  $("guestVoicePreset").addEventListener("change",configureVoice);$("guestSoundVolume").addEventListener("input",configureVoice);
  for(const [id,cue] of Object.entries(cueButtons))$(id).addEventListener("click",()=>audioAction(owner=>owner.playCue(cue)));
  $("guestSoundsStop").addEventListener("click",()=>{microphone?.stopSounds();audioState();$("guestAudioStatus").textContent="Sounds stopped. Your voice is unchanged.";});
  $("guestSoundFile").addEventListener("change",()=>{const file=$("guestSoundFile").files?.[0];$("guestSoundFile").value="";if(file)audioAction(owner=>owner.addSound(file),"Sound added. Choose Play when you’re ready.");});
  $("guestJoinForm").addEventListener("submit",join);$("guestCamera").addEventListener("click",()=>capture("camera"));$("guestMicrophone").addEventListener("click",()=>capture("microphone"));$("guestScreen").addEventListener("click",screen);
  $("guestCameraDevice").addEventListener("change",()=>{if(media.camera)capture("camera",true);});$("guestMicDevice").addEventListener("change",()=>{if(media.microphone)capture("microphone",true);});
  $("guestLeave").addEventListener("click",leave);$("guestRoomAudio").addEventListener("click",()=>playReturn(true));
  root.addEventListener("pagehide",()=>{leaving=true;mediaEpoch++;programAudioNotice();publisher?.close();for(const key of Object.keys(media))stop(key);});
  if(!root.isSecureContext){status("A secure link is needed","Camera and microphone access need a secure HTTPS guest link. Ask the producer for one.");}
  else if(!invite&&!token){status("Invitation needed","Open the guest link provided by your producer to join this room.");$("guestJoin").disabled=true;}
  else if(token){$("guestJoin").textContent="Rejoin backstage";$("guestName").required=false;status("Resume your guest session","Choose your media, then rejoin the room.");}
  if(!navigator.mediaDevices?.getDisplayMedia){$("guestScreen").title="Screen sharing is not supported in this browser. Camera and mic can still be used.";$("guestMediaHint").textContent="This browser supports camera and mic; use a supported desktop browser to share your screen.";}
  setBusy(false);if(!invite&&!token)$("guestJoin").disabled=true;
})(window);
