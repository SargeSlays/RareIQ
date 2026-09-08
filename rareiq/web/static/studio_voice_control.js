/* Explicit local voice arming; borrows the existing pre-effects Voice Mod source. */
(function(host){
  'use strict';
  const modules=new WeakMap();
  function create({borrow,request}){
    let generation=0,session=null,branch=null,pollTimer=null,busy=false,starting=false,sequence=0,audioAbort=null,polling=false,lastPoll=0;
    let state='stopped',message='Start Voice Mod before listening.',outcome='';
    const node=id=>host.document.getElementById(id);
    const local=()=>['localhost','127.0.0.1','[::1]','::1'].includes(host.location.hostname);
    const ready=()=>{const input=borrow();return input?.active&&input.context?.state==='running'&&input.source&&input.inputStream?.getAudioTracks().some(track=>track.readyState==='live');};
    function refresh(){
      const available=local()&&ready(),start=node('studioVoiceStart'),stop=node('studioVoiceStop'),practice=node('studioVoicePractice');
      if(start){start.disabled=!available||starting||Boolean(session);start.title=!local()?'Use the local studio on this computer.':!available?'Start Voice Mod before listening.':'';}
      if(stop)stop.disabled=!starting&&!session;
      if(practice)practice.disabled=starting||Boolean(session);
      if(node('studioVoiceStatus'))node('studioVoiceStatus').textContent=!local()?'Voice commands are available only in the local studio.':!available&&!session&&!starting?'Start Voice Mod before listening.':message;
      if(node('studioVoiceOutcome'))node('studioVoiceOutcome').textContent=outcome;
      if(node('studioVoiceControls'))node('studioVoiceControls').dataset.state=state;
    }
    function detach(){
      host.clearTimeout(pollTimer);pollTimer=null;audioAbort?.abort();audioAbort=null;busy=false;
      if(branch){branch.worklet.port.onmessage=null;branch.worklet.port.postMessage({type:'enabled',value:false});try{branch.source.disconnect(branch.worklet);}catch(_){}try{branch.worklet.disconnect();branch.sink.disconnect();}catch(_){}branch.worklet.port.close();branch=null;}
    }
    function report(payload){
      if(payload.last_result)outcome=String(payload.last_result.message||({validated:'Practice command validated; no action taken.',succeeded:'Command completed.',failed:'Command failed.',rejected:'Command was not accepted.',executing:'Command is still executing.'}[payload.last_result.state]||'No action confirmed.'));
    }
    async function stop(detail='Listening stopped.',notify=true){
      const previous=session,stoppedGeneration=++generation;session=null;starting=false;detach();state='stopped';message=detail;refresh();
      if(previous&&notify){try{await request('/api/production/voice/stop',{method:'POST',retries:0,keepalive:true,body:JSON.stringify({session_id:previous})});}catch(_){if(generation===stoppedGeneration){message='Stopped locally; host stop could not be confirmed. Use the host emergency stop if needed.';refresh();}}}
    }
    function schedule(token){host.clearTimeout(pollTimer);pollTimer=host.setTimeout(()=>poll(token),1000);}
    async function poll(token){
      if(token!==generation||!session)return;
      if(polling||Date.now()-lastPoll<900){schedule(token);return;}polling=true;lastPoll=Date.now();
      try{
        const payload=await request('/api/production/voice/status?session_id='+encodeURIComponent(session),{retries:0,timeoutMs:5000});
        if(token!==generation)return;report(payload);
        if(['stopped','error'].includes(payload.state)){await stop(payload.state==='error'?'Voice recognition stopped after an error.':'Listening stopped by the host.',payload.state==='error');return;}
        if(!ready()||borrow().source!==branch?.source){await stop('Voice Mod changed or stopped.');return;}
        if(payload.state==='armed'&&busy&&!audioAbort){busy=false;state='armed';message=node('studioVoicePractice')?.checked?'Listening in Practice · no actions will run.':'Listening · accepted commands can control Program and save clips.';branch?.worklet.port.postMessage({type:'enabled',value:true});}
        refresh();schedule(token);
      }catch(_){if(token===generation)await stop('Voice status is unavailable; listening stopped.');}finally{polling=false;}
    }
    async function send(event,token,clockOffset){
      const data=event.data;
      if(data?.type==='heartbeat'){poll(token);return;}
      if(token!==generation||!session||busy||data?.type!=='utterance'||!(data.wav instanceof ArrayBuffer)||data.wav.byteLength>192044||data.wav.byteLength<=44||!Number.isFinite(data.endedContextTime))return;
      if(!ready()||borrow().source!==branch?.source){await stop('Voice Mod changed or stopped.');return;}
      busy=true;state='recognizing';message='Understanding command…';refresh();audioAbort=new host.AbortController();
      try{
        const query=new URLSearchParams({session_id:session,sequence:String(++sequence),ended_at:String(clockOffset+data.endedContextTime)});
        const payload=await request('/api/production/voice/audio?'+query,{method:'POST',headers:{'Content-Type':'audio/wav'},body:data.wav,retries:0,timeoutMs:30000,signal:audioAbort.signal});
        if(token!==generation)return;report(payload);
        if(['stopped','error'].includes(payload.state)){await stop('Voice recognition stopped.');return;}
        state=payload.state==='recognizing'?'recognizing':'armed';message=state==='recognizing'?'Command in progress…':node('studioVoicePractice')?.checked?'Listening in Practice · no actions will run.':'Listening · accepted commands can control Program and save clips.';refresh();
      }catch(_){if(token===generation)await stop('Command response unavailable; listening stopped. Check the outcome before retrying.');}
      finally{if(token===generation){audioAbort=null;if(state==='armed'){busy=false;branch?.worklet.port.postMessage({type:'enabled',value:true});}}}
    }
    async function start(){
      if(starting||session)return;outcome='';
      if(!local()||!ready()){refresh();return;}
      const input=borrow(),token=++generation;starting=true;state='starting';message='Preparing voice commands…';refresh();
      let created=null;
      try{
        if(!input.context.audioWorklet||!host.AudioWorkletNode)throw Error('AudioWorklet unavailable');
        if(!modules.has(input.context))modules.set(input.context,input.context.audioWorklet.addModule('/static/studio_voice_capture.worklet.js?v=20260908-1').catch(error=>{modules.delete(input.context);throw error;}));
        await modules.get(input.context);
        if(token!==generation||borrow().source!==input.source||!ready())return;
        const payload=await request('/api/production/voice/start',{method:'POST',retries:0,body:JSON.stringify({practice:node('studioVoicePractice')?.checked!==false})});
        created=payload.session_id;
        if(token!==generation||borrow().source!==input.source||!ready()){if(created)await request('/api/production/voice/stop',{method:'POST',retries:0,body:JSON.stringify({session_id:created})});return;}
        if(payload.ok!==true||!created||payload.state!=='armed')throw Error('Host did not arm voice commands');
        session=created;sequence=0;
        const worklet=new host.AudioWorkletNode(input.context,'studio-voice-capture',{numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1]}),sink=input.context.createGain();sink.gain.value=0;
        branch={source:input.source,worklet,sink};const clockOffset=Date.now()/1000-input.context.currentTime;
        worklet.port.onmessage=event=>send(event,token,clockOffset);worklet.onprocessorerror=()=>{if(token===generation)stop('Voice capture stopped after a processing error.');};
        input.source.connect(worklet);worklet.connect(sink);sink.connect(input.context.destination);
        worklet.port.postMessage({type:'enabled',value:true});state='armed';message=payload.practice?'Listening in Practice · no actions will run.':'Listening · accepted commands can control Program and save clips.';schedule(token);
      }catch(_){if(token===generation){if(created&&!session)session=created;await stop('Voice commands could not start. Check host availability, then try again.');}}
      finally{if(token===generation){starting=false;refresh();}}
    }
    node('studioVoicePractice').checked=true;
    node('studioVoiceStart').addEventListener('click',start);
    node('studioVoiceStop').addEventListener('click',()=>stop());
    host.addEventListener('pagehide',()=>stop('Listening stopped because the studio closed.'));
    refresh();return {start,stop,refresh,status:()=>({state,session_id:session,busy,starting})};
  }
  if(typeof module==='object'&&module.exports)module.exports={create};
  else host.StudioVoiceControlFactory={create};
})(typeof window==='undefined'?globalThis:window);
