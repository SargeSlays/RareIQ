/* Owns one already-authorized microphone and its outgoing mix. No capture or network. */
(function(host){
  'use strict';
  const MAX_FILE=10*1024*1024,MAX_DECODED=64*1024*1024,MAX_SOUNDS=6,MAX_PLAYING=4;
  const presets=['natural','deep','radio','robot','megaphone'];
  function create(raw,onTrack,onStatus,onState=()=>{}){
    let context=null,input=null,output=null,gate=null,gateOutput=null,mix=null,soundGain=null,limiter=null,effect=null;
    let closed=false,pending=null,loading=false,sequence=0,playEpoch=0,appliedPreset='natural',error='';
    const sounds=new Map(),playing=new Map(),cueCache=new Map();
    let settings={enabled:false,thresholdDb:-45,preset:'natural',soundVolume:.5};
    const status=value=>{if(!closed)onStatus(value);};
    const snapshot=()=>({preset:settings.preset,appliedPreset,soundVolume:settings.soundVolume,
      sounds:[...sounds.values()].map(({id,label,buffer})=>({id,label,duration:buffer.duration})),
      playing:playing.size,loading,available:Boolean(!closed&&output&&context?.state==='running'),error});
    const emit=()=>{if(!closed)try{onState(snapshot());}catch(_){};};
    function finish(entry){if(entry.stopped)return;entry.stopped=true;entry.source.onended=null;try{entry.source.stop();}catch(_){}try{entry.source.disconnect();}catch(_){}playing.delete(entry.key);emit();}
    function stopSounds(){playEpoch++;for(const entry of [...playing.values()])finish(entry);}
    function disposeGraph(){
      stopSounds();effect?.close();effect=null;gate?.close();gate=null;
      for(const node of [input,gateOutput,mix,soundGain,limiter])try{node?.disconnect();}catch(_){}
      input=gateOutput=mix=soundGain=limiter=null;
      for(const track of output?.stream.getTracks()||[])track.stop();output=null;
      const old=context;context=null;cueCache.clear();appliedPreset='natural';if(old)Promise.resolve(old.close()).catch(()=>{});
    }
    function applyEffect(){
      if(!output)return;
      if(!effect||appliedPreset!==settings.preset){effect?.close();effect=host.ProducerGuestAudioDSP.connectPreset(context,gateOutput,mix,settings.preset);appliedPreset=settings.preset;}
      soundGain.gain.value=settings.soundVolume;
    }
    function unavailable(){if(closed)return;disposeGraph();error='audio_unavailable';onTrack(raw);status('Unavailable · audio unfiltered');emit();}
    function ensureGraph(){
      if(closed)return Promise.reject(Error('audio_closed'));
      if(pending)return pending;
      if(output){
        // Resume directly in the caller's click stack, before any promise continuation.
        let resumed;try{resumed=context.state==='running'?Promise.resolve():context.resume();}catch(_){resumed=Promise.reject(Error('audio_unavailable'));}
        return Promise.resolve(resumed).then(()=>{if(closed)throw Error('audio_closed');if(context?.state!=='running')throw Error('audio_unavailable');error='';emit();})
          .catch(()=>{if(!closed){error='audio_unavailable';emit();}throw Error(closed?'audio_closed':'audio_unavailable');});
      }
      try{
        const Context=host.AudioContext||host.webkitAudioContext;
        if(!Context||!host.StudioNoiseGate||!host.ProducerGuestAudioDSP)throw Error('audio_unavailable');
        context=new Context();const starting=context,ready=context.resume();
        pending=Promise.resolve(ready).then(async()=>{
          if(closed||context!==starting)throw Error('audio_closed');
          if(context.state!=='running')throw Error('audio_unavailable');
          input=context.createMediaStreamSource(new host.MediaStream([raw]));output=context.createMediaStreamDestination();
          // Keep replacement compatible with the negotiated physical microphone.
          output.channelCount=raw.getSettings?.().channelCount===2?2:1;
          gateOutput=context.createGain();mix=context.createGain();soundGain=context.createGain();limiter=context.createDynamicsCompressor();
          limiter.threshold.value=-6;limiter.knee.value=3;limiter.ratio.value=12;limiter.attack.value=.003;limiter.release.value=.1;
          soundGain.connect(mix);mix.connect(limiter);limiter.connect(output);
          gate=host.StudioNoiseGate.create(context,input,gateOutput,status,{workletUrl:'/guest/assets/studio_noise_gate.worklet.js?v=20260908-1'});
          await gate.configure(settings);
          if(closed||context!==starting)throw Error('audio_closed');
          applyEffect();error='';onTrack(output.stream.getAudioTracks()[0]);emit();
        }).catch(()=>{
          unavailable();
          throw Error(closed?'audio_closed':'audio_unavailable');
        }).finally(()=>{pending=null;});
        return pending;
      }catch(_){
        unavailable();return Promise.reject(Error('audio_unavailable'));
      }
    }
    async function configure(next={}){
      if(closed)return snapshot();
      const merged={...settings,...next};
      settings={enabled:merged.enabled===true,thresholdDb:Math.max(-70,Math.min(-10,Number.isFinite(merged.thresholdDb)?merged.thresholdDb:-45)),
        preset:presets.includes(merged.preset)?merged.preset:'natural',soundVolume:Math.max(0,Math.min(1,Number.isFinite(merged.soundVolume)?merged.soundVolume:.5))};
      if(gate){try{await Promise.all([ensureGraph(),gate.configure(settings)]);if(!closed){applyEffect();error='';emit();}}catch(_){unavailable();}return snapshot();}
      if(!settings.enabled&&settings.preset==='natural'){status('Off');emit();return snapshot();}
      status('Preparing…');try{await ensureGraph();}catch(_){}return snapshot();
    }
    async function playBuffer(id,makeBuffer){
      if(playing.size>=MAX_PLAYING)throw Error('sound_playback_limit');
      const epoch=playEpoch;await ensureGraph();
      if(closed||epoch!==playEpoch)throw Error('sound_cancelled');
      if(playing.size>=MAX_PLAYING)throw Error('sound_playback_limit');
      const buffer=makeBuffer();if(!buffer)throw Error('unknown_sound');
      const source=context.createBufferSource();source.buffer=buffer;source.connect(soundGain);
      const entry={key:++sequence,id,source,stopped:false};playing.set(entry.key,entry);source.onended=()=>finish(entry);
      try{source.start();}catch(_){finish(entry);throw Error('audio_unavailable');}emit();return snapshot();
    }
    async function playCue(id){
      if(!host.ProducerGuestAudioDSP?.cues.some(cue=>cue.id===id))throw Error('unknown_sound');
      return playBuffer(id,()=>{if(!cueCache.has(id))cueCache.set(id,host.ProducerGuestAudioDSP.cueBuffer(context,id));return cueCache.get(id);});
    }
    async function addSound(file){
      if(closed)throw Error('audio_closed');
      if(loading)throw Error('sound_import_busy');
      if(sounds.size>=MAX_SOUNDS)throw Error('sound_slot_limit');
      if(!file||!Number.isInteger(file.size)||file.size<=0||file.size>MAX_FILE)throw Error('sound_file_too_large');
      if(typeof file.arrayBuffer!=='function'||!/^(?:audio\/(?:mpeg|mp3|wav|x-wav|wave|ogg|webm|mp4|x-m4a|flac)|application\/ogg)$/.test(file.type||''))throw Error('sound_file_type');
      loading=true;emit();
      try{
        await ensureGraph();const owner=context;let bytes;
        try{bytes=await file.arrayBuffer();}catch(_){throw Error('sound_read_failed');}
        if(closed||context!==owner)throw Error('audio_closed');
        if(Object.prototype.toString.call(bytes)!=='[object ArrayBuffer]'||!Number.isInteger(bytes.byteLength)||bytes.byteLength<=0||bytes.byteLength>MAX_FILE)throw Error('sound_file_too_large');
        let buffer;try{buffer=await owner.decodeAudioData(bytes);}catch(_){throw Error('sound_decode_failed');}
        if(closed||context!==owner)throw Error('audio_closed');
        if(!Number.isFinite(buffer.duration)||buffer.duration<=0||buffer.duration>30)throw Error('sound_duration_limit');
        const memory=buffer.length*buffer.numberOfChannels*4,total=[...sounds.values()].reduce((n,s)=>n+s.buffer.length*s.buffer.numberOfChannels*4,0);
        if(![1,2].includes(buffer.numberOfChannels)||!Number.isFinite(memory)||memory+total>MAX_DECODED)throw Error('sound_memory_limit');
        const id='sound-'+(++sequence),label=String(file.name||'Local sound').split(/[\\/]/).pop().replace(/[\u0000-\u001f\u007f]/g,'').slice(0,50)||'Local sound';
        sounds.set(id,{id,label,buffer});return {id,label,duration:buffer.duration};
      }finally{loading=false;emit();}
    }
    function removeSound(id){for(const entry of [...playing.values()])if(entry.id===id)finish(entry);sounds.delete(id);emit();}
    function close(){if(closed)return;closed=true;raw.onended=null;raw.stop();disposeGraph();sounds.clear();}
    return {configure,snapshot,playCue,addSound,playSound:id=>playBuffer(id,()=>sounds.get(id)?.buffer),removeSound,stopSounds,close};
  }
  host.ProducerGuestMicrophone={create};
})(typeof window==='undefined'?globalThis:window);
