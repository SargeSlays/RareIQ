(function(root){
  "use strict";
  const $=id=>document.getElementById(id), media={microphone:null,camera:null,screen:null,screen_audio:null};
  const STORE="producer.guest.session.v1";
  let invite=new URLSearchParams(location.hash.slice(1)).get("invite"),token="",publisher=null,joined=false,busy=false,leaving=false,mediaEpoch=0;
  history.replaceState(null,"",location.pathname);
  if(!invite){try{token=sessionStorage.getItem(STORE)||"";}catch{}}
  function status(title,message){$("guestStatusTitle").textContent=title;$("guestStatus").textContent=message;}
  function secret(){const bytes=new Uint8Array(32);crypto.getRandomValues(bytes);return Array.from(bytes,x=>x.toString(16).padStart(2,"0")).join("");}
  function setBusy(value){busy=value;$("guestJoin").disabled=value;for(const id of ["guestCamera","guestMicrophone"])$(id).disabled=value||!root.isSecureContext;$("guestScreen").disabled=value||!navigator.mediaDevices?.getDisplayMedia;}
  function synchronize(publish=true){
    if(publish)publisher?.setTracks({...media});
    const camera=Boolean(media.camera),mic=Boolean(media.microphone),screen=Boolean(media.screen);
    for(const [id,on,onText,offText] of [["guestCamera",camera,"Turn camera off","Turn camera on"],["guestMicrophone",mic,"Turn mic off","Turn mic on"],["guestScreen",screen,"Stop sharing","Share screen"]]){$(id).setAttribute("aria-pressed",String(on));$(id).textContent=on?onText:offText;}
    $("guestCameraEmpty").hidden=camera;if($("guestCameraPreview").srcObject?.getVideoTracks()[0]!==media.camera)$("guestCameraPreview").srcObject=camera?new MediaStream([media.camera]):null;
    $("guestScreenPreviewPanel").hidden=!screen;if($("guestScreenPreview").srcObject?.getVideoTracks()[0]!==media.screen)$("guestScreenPreview").srcObject=screen?new MediaStream([media.screen]):null;
    $("guestMediaHint").textContent=screen?(media.screen_audio?"Your selected screen and its audio are shared.":"Your screen is shared. This selection has no screen audio."):(joined?"Enabled sources are shared with the producer. Only selected sources reach Program.":"Your preview stays on this device until you join.");
  }
  function stop(kind){const track=media[kind];media[kind]=null;if(track){track.onended=null;track.stop();}}
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
      track.onended=()=>{if(media[kind]===track){media[kind]=null;synchronize();}};
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
    const participant=value.participant;if(!participant)return;
    joined=true;$("guestName").value=participant.name;$("guestName").disabled=true;$("guestJoinForm").hidden=true;$("guestLeave").hidden=false;
    const onAir=(value.on_air_sources||[]).some(s=>s.startsWith(`guest:${participant.id}:`));
    $("guestBadge").textContent=onAir?"ON PROGRAM":participant.state==="admitted"?"BACKSTAGE":"WAITING FOR PRODUCER";$("guestBadge").classList.toggle("on-air",onAir);
    status(onAir?"You’re on Program":participant.state==="admitted"?"You’re backstage":"Waiting for the producer",onAir?"The producer selected your source for the production. You can still turn off your media.":participant.state==="admitted"?"You can talk with the room. Your sources stay off Program until the producer selects them.":"The producer can preview your enabled sources. You’re not on Program.");
    synchronize(false);
  }
  function connect(){
    publisher?.close();publisher=root.ProducerGuestMedia.createPublisher({token,onState:roomState,
      onReturnAudio:stream=>{const audio=$("guestReturnAudio");audio.srcObject=stream;if(stream)audio.play().then(()=>{$("guestRoomAudio").hidden=true;}).catch(()=>{$("guestRoomAudio").hidden=false;});else{$("guestRoomAudio").hidden=true;audio.pause();}},
      onConnection:event=>{if(leaving)return;if(["disconnected","reconnecting","failed","closed"].includes(event.state)){status("Room connection paused","Your media is not reaching the room. Reconnecting; if this persists, ask the producer for a new invitation.");$("guestBadge").textContent="DISCONNECTED";$("guestBadge").classList.remove("on-air");}},
      onError:()=>{if(!leaving)status("Could not connect","The invitation may have expired or been removed. Ask the producer for a new invitation.");}});
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
    leaving=true;mediaEpoch++;setBusy(true);publisher?.close();publisher=null;for(const key of Object.keys(media))stop(key);synchronize();$("guestReturnAudio").srcObject=null;$("guestReturnAudio").pause();
    const prior=token;token="";joined=false;try{sessionStorage.removeItem(STORE);}catch{}
    $("guestLeave").hidden=true;$("guestRoomAudio").hidden=true;$("guestBadge").textContent="LEFT THE ROOM";$("guestBadge").classList.remove("on-air");status("You’ve left the room","Your camera, microphone and screen are off.");
    if(prior){try{await fetch("/guest/leave",{method:"POST",headers:{Authorization:"Bearer "+prior}});}catch{}}
  }
  $("guestJoinForm").addEventListener("submit",join);$("guestCamera").addEventListener("click",()=>capture("camera"));$("guestMicrophone").addEventListener("click",()=>capture("microphone"));$("guestScreen").addEventListener("click",screen);
  $("guestCameraDevice").addEventListener("change",()=>{if(media.camera)capture("camera",true);});$("guestMicDevice").addEventListener("change",()=>{if(media.microphone)capture("microphone",true);});
  $("guestLeave").addEventListener("click",leave);$("guestRoomAudio").addEventListener("click",()=>$("guestReturnAudio").play().then(()=>{$("guestRoomAudio").hidden=true;}).catch(()=>status("Audio is paused","Check the browser’s sound permissions and try again.")));
  root.addEventListener("pagehide",()=>{leaving=true;mediaEpoch++;publisher?.close();for(const key of Object.keys(media))stop(key);});
  if(!root.isSecureContext){status("A secure link is needed","Camera and microphone access need a secure HTTPS guest link. Ask the producer for one.");}
  else if(!invite&&!token){status("Invitation needed","Open the guest link provided by your producer to join this room.");$("guestJoin").disabled=true;}
  else if(token){$("guestJoin").textContent="Rejoin backstage";$("guestName").required=false;status("Resume your guest session","Choose your media, then rejoin the room.");}
  if(!navigator.mediaDevices?.getDisplayMedia){$("guestScreen").title="Screen sharing is not supported in this browser. Camera and mic can still be used.";$("guestMediaHint").textContent="This browser supports camera and mic; use a supported desktop browser to share your screen.";}
  setBusy(false);if(!invite&&!token)$("guestJoin").disabled=true;
})(window);
