/* Local operator screen capture. Capture starts only inside the Share click. */
(function(host){
  'use strict';
  const sourceId=value=>typeof value==='string'&&/^producer:screen:[a-f0-9]{32}$/.test(value)?value:null;
  function mount({after,room=()=>({}),selected=()=>[],busy=()=>false,select=()=>{},refresh=async()=>{},
    fetch:request=(...args)=>host.fetch(...args),document=after?.ownerDocument||host.document,
    mediaDevices=host.navigator?.mediaDevices,createPublisher=options=>host.ProducerGuestMedia.createProducerScreenPublisher(options)}={}){
    if(!after||!document)return null;
    const section=document.createElement('section');section.className='producer-screen-source';section.setAttribute('aria-label','My screen or window');
    section.innerHTML='<div class="producer-screen-heading"><strong>My screen / window</strong><div><button type="button" class="riq-button" data-screen-share>Share screen / window</button><button type="button" class="riq-button" data-screen-stop disabled>Stop sharing</button></div></div><p class="producer-screen-feedback" role="status" aria-live="polite">Checking screen sharing…</p><p class="producer-screen-scope">Video only · no computer sound. Choose a screen or window, add it to Preview, then Take when Studio Output is ready.</p><button type="button" class="riq-button" data-screen-preview disabled aria-pressed="false">Add my screen to Preview</button>';
    after.after(section);
    const one=selector=>section.querySelector(selector),shareButton=one('[data-screen-share]'),stopButton=one('[data-screen-stop]'),previewButton=one('[data-screen-preview]'),feedback=one('[role="status"]');
    let allowed=false,checked=false,pending=false,closed=false,epoch=0,stream=null,publisher=null,id=null,removeEnded=null;
    const note=text=>{feedback.textContent=text;};
    function render(){
      if(closed)return;
      const available=!!id&&room().producer_sources?.some(source=>source.id===id&&source.available===true),chosen=selected().includes(id);
      shareButton.disabled=!checked||!allowed||pending||!!stream||busy()||typeof mediaDevices?.getDisplayMedia!=='function';
      shareButton.textContent=pending?'Choose a screen / window…':'Share screen / window';shareButton.setAttribute('aria-busy',String(pending));
      shareButton.title=!checked?'Checking local capture permission.':!allowed?'Screen sharing is available to the operator on this computer.':!mediaDevices?.getDisplayMedia?'Use the desktop app or a supported browser on this computer.':stream?'Stop the current share before choosing another.':busy()?'Wait for the current Preview change.':'Choose the picture to share. This does not change Program.';
      stopButton.disabled=!pending&&!stream;stopButton.textContent=pending?'Cancel sharing':'Stop sharing';stopButton.title=stopButton.disabled?'No screen is being shared.':'Stops capture and removes this screen from Preview and Program.';
      previewButton.disabled=!available||pending||busy();previewButton.setAttribute('aria-pressed',String(chosen));previewButton.textContent=chosen?'Remove my screen from Preview':'Add my screen to Preview';
      previewButton.title=!available?'Share a screen and wait for its connection.':busy()?'Wait for the current Preview change.':'Changes Preview only. Use Take to change Program.';
    }
    function stop(message='Screen sharing stopped. Preview and Program will remove this source.'){
      ++epoch;pending=false;const old=publisher;publisher=null;id=null;removeEnded?.();removeEnded=null;
      try{old?.setTracks({screen:null});}catch(_){}old?.close();
      const owned=stream;stream=null;for(const track of owned?.getTracks()||[])track.stop();
      if(!closed){note(message);render();Promise.resolve(refresh(true)).catch(()=>{});}
    }
    async function start(){
      if(closed||shareButton.disabled)return;
      const version=++epoch;pending=true;render();note('Choose a screen or window. Computer sound is not shared.');
      let captured=null,next=null;
      try{
        // Keep this call before the first await so native/browser user activation survives.
        const requestCapture=mediaDevices.getDisplayMedia({video:{frameRate:{ideal:30,max:30}},audio:false});
        captured=await requestCapture;
        if(closed||version!==epoch){for(const track of captured.getTracks())track.stop();return;}
        const videos=captured.getVideoTracks(),track=videos[0];
        for(const audio of captured.getAudioTracks())audio.stop();
        if(videos.length!==1||!track||track.readyState!=='live')throw Error('screen_unavailable');
        try{track.contentHint='detail';}catch(_){/* Older browsers retain their capture defaults. */}
        stream=captured;
        const ended=()=>{if(version===epoch)stop('Screen sharing ended. Share again when ready; the new picture is kept off Program.');};
        track.addEventListener('ended',ended);removeEnded=()=>track.removeEventListener('ended',ended);
        next=createPublisher({onState:state=>{if(version!==epoch||closed)return;id=sourceId(state.source_id);render();},
          onConnection:event=>{if(version===epoch&&!closed&&!event.scope&&['disconnected','closed'].includes(event.state))stop('Screen connection stopped. Share again when ready; Program is not restored automatically.');},onError:()=>{}});
        publisher=next;next.setTracks({screen:track});await next.connect();
        if(closed||version!==epoch){next.close();return;}
        pending=false;note('Sharing video only. Add my screen to Preview, then Take when Studio Output is ready.');render();await refresh(true);
      }catch(_){
        if(version===epoch&&!closed)stop('Screen sharing was cancelled or unavailable. Choose Share screen / window to try again.');
        else{next?.close();for(const track of captured?.getTracks()||[])track.stop();}
      }
    }
    shareButton.addEventListener('click',start);stopButton.addEventListener('click',()=>stop());
    previewButton.addEventListener('click',()=>{if(!previewButton.disabled&&id)select(id);});
    const pagehide=()=>api.close();host.addEventListener?.('pagehide',pagehide,{once:true});
    const api={render,start,stop,source:()=>id,close(){if(closed)return;closed=true;stop();host.removeEventListener?.('pagehide',pagehide);section.remove();}};
    render();Promise.resolve().then(()=>request('/api/production/greenroom/producer-screen',{credentials:'same-origin',cache:'no-store'})).then(async response=>{
      const state=await response.json();if(closed)return;checked=true;allowed=response.ok&&state.ok===true&&state.capture_allowed===true;
      note(allowed?'Ready to share video. Your screen stays off Program until you Take it.':'Share a screen from the operator app on this computer.');render();
    }).catch(()=>{if(!closed){checked=true;note('Screen sharing could not be checked. Reload the studio to retry.');render();}});
    return api;
  }
  const exported={mount,sourceId};if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerScreenSource=exported;
})(typeof window==='undefined'?globalThis:window);
