/* Clean Program composition. Receiver tracks are borrowed, never captured or stopped here. */
(function(host){
  'use strict';
  const SOURCE=/^(?:camera:([1-4])|guest:([a-f0-9]{32}):(camera|screen|audio))$/;
  const FRAME_TTL=2500,STATE_TTL=4500;
  function parseSource(value){
    const match=typeof value==='string'&&SOURCE.exec(value);
    return match?{id:value,kind:match[1]?'local':match[3],slot:match[1]?Number(match[1]):null,participantId:match[2]||null}:null;
  }
  function sourceList(state,bus){
    const key=bus+'_sources';
    const values=Object.prototype.hasOwnProperty.call(state,key)?state[key]:["camera:"+state[bus+'_slot']];
    if(!Array.isArray(values)||values.length>6||values.some(value=>!parseSource(value))||new Set(values).size!==values.length)return null;
    return values.slice();
  }
  function normalizeState(state,bus='program'){
    if(!state||typeof state!=='object'||!Number.isSafeInteger(state.generation)||state.generation<0)return null;
    const sources=sourceList(state,bus),preview=sourceList(state,'preview');
    if(!sources||!preview)return null;
    const layout=['auto','grid','spotlight'].includes(state[bus+'_layout'])?state[bus+'_layout']:'auto';
    const transition=['cut','fade','slide','zoom'].includes(state.transition)?state.transition:'cut';
    return {generation:state.generation,sources,preview,layout,transition,
      duration:transition==='cut'?0:Math.min(5000,Math.max(0,Number(state.duration_ms)||0))};
  }
  const liveTrack=track=>Boolean(track&&track.readyState==='live'&&track.enabled!==false&&track.muted!==true);
  function participantFor(room,id){return room?.participants?.find(p=>p.id===id&&p.state==='admitted'&&p.connected===true&&!p.expired)||null;}
  function permitted(source,room){
    if(source.kind==='local')return true;
    const participant=participantFor(room,source.participantId);
    return Boolean(participant&&participant.media?.[source.kind==='audio'?'microphone':source.kind]===true);
  }
  function audioPlan(sources,room,tracks){
    const result=new Map();
    for(const id of sources){
      const source=parseSource(id);
      if(!source||source.kind==='local'||!permitted(source,room))continue;
      const participant=participantFor(room,source.participantId),media=tracks(source.participantId)||{};
      if(participant.media.microphone===true&&liveTrack(media.microphone))result.set(source.participantId+':microphone',media.microphone);
      if(source.kind==='screen'&&participant.media.screen_audio===true&&liveTrack(media.screen_audio))result.set(source.participantId+':screen_audio',media.screen_audio);
    }
    return result;
  }
  class ProducerCompositionView{
    constructor({container,mediaReceiver=null,muted=false,bus='program',onStatus=()=>{},onRendered=()=>{},
      document=container?.ownerDocument||host.document,now=()=>host.performance?.now?.()??Date.now(),
      setTimeout:later=host.setTimeout.bind(host),clearTimeout:cancel=host.clearTimeout.bind(host),
      setInterval:repeat=host.setInterval.bind(host),clearInterval:cancelRepeat=host.clearInterval.bind(host),
      requestAnimationFrame:frame=host.requestAnimationFrame?.bind(host)||((fn)=>later(fn,0)),
      cancelAnimationFrame:cancelFrame=host.cancelAnimationFrame?.bind(host)||cancel,
      makeStream=tracks=>new host.MediaStream(tracks)}={}){
      if(!container||!document||!['program','preview'].includes(bus))throw Error('invalid_composition_view');
      Object.assign(this,{container,mediaReceiver,muted:muted||bus==='preview',bus,onStatus,onRendered,document,
        now,later,cancel,repeat,cancelRepeat,frame,cancelFrame,makeStream});
      this.current=null;this.outgoing=null;this.preloads=new Map();this.audio=new Map();this.room=null;this.roomRevision=-1;
      this.state=null;this.lastReceived=0;this.epoch=0;this.timer=null;this.frameTimer=null;this.lastStatus='';this.lastRendered=null;this.closed=false;
      container.classList.add('producer-composition');
      this.preloadHost=document.createElement('div');this.preloadHost.className='composition-preload';this.preloadHost.setAttribute('aria-hidden','true');container.append(this.preloadHost);
      this.audioHost=document.createElement('div');this.audioHost.className='composition-audio';this.audioHost.setAttribute('aria-hidden','true');container.append(this.audioHost);
      this.watchdog=repeat(()=>this.refresh(),200);
    }
    _emit(fn,value){try{fn(value);}catch(_){/* A control-panel callback cannot affect clean output. */}}
    _tracks(id){try{return this.mediaReceiver?.tracks(id)||{};}catch(_){return {};}}
    setRoom(room){
      if(!room||!Array.isArray(room.participants)){this.room=null;this.roomRevision=-1;this.refresh();return;}
      if(Number.isSafeInteger(room.revision)&&room.revision<this.roomRevision)return;
      this.room=room;this.roomRevision=Number.isSafeInteger(room.revision)?room.revision:this.roomRevision;this.refresh();
    }
    render(value,room){
      if(this.closed)return false;
      if(room!==undefined)this.setRoom(room);
      const next=normalizeState(value,this.bus);
      if(!next){this.clear();return false;}
      if(this.state&&next.generation<this.state.generation)return false;
      this.lastReceived=this.now();
      const changed=!this.state||next.generation!==this.state.generation||next.layout!==this.state.layout||JSON.stringify(next.sources)!==JSON.stringify(this.state.sources);
      this.state=next;
      if(changed)this._transition(next);
      this._preload();this.refresh();return true;
    }
    _transition(state){
      const epoch=++this.epoch;this.cancel(this.timer);this.cancelFrame(this.frameTimer);
      if(this.outgoing)this._disposeLayer(this.outgoing);
      this.outgoing=this.current;this.lastRendered=null;this._clearAudio();
      const node=this.document.createElement('div');node.className='composition-layer composition-incoming';
      node.dataset.layout=state.layout;node.dataset.count=String(state.sources.length);node.style.setProperty('--composition-duration',state.duration+'ms');
      node.style.setProperty('--composition-sides',String(Math.max(1,state.sources.length-1)));
      node.style.setProperty('--composition-portrait-rows',String(Math.max(1,Math.ceil((state.sources.length-1)/2))));
      const tiles=state.sources.map(id=>{
        let tile=this.preloads.get(id);if(tile)this.preloads.delete(id);else tile=this._tile(id);
        node.append(tile.node);return tile;
      });
      this.current={node,tiles,generation:state.generation,visible:false};this.container.append(node);
      this.container.dataset.transition=state.transition;
      if(this.outgoing){this.outgoing.node.style.setProperty('--composition-duration',state.duration+'ms');this.outgoing.node.classList.add('composition-outgoing');}
      const incoming=this.current;
      this.frameTimer=this.frame(()=>{
        if(this.closed||epoch!==this.epoch||this.current!==incoming)return;
        incoming.visible=true;incoming.node.classList.remove('composition-incoming');this.refresh();
      });
      const outgoing=this.outgoing;
      if(!state.duration){if(outgoing)this._disposeLayer(outgoing);this.outgoing=null;}
      else this.timer=this.later(()=>{
        if(this.closed||epoch!==this.epoch||this.outgoing!==outgoing)return;
        if(outgoing)this._disposeLayer(outgoing);this.outgoing=null;
      },state.duration);
    }
    _preload(){
      const desired=new Set(this.state.preview.filter(id=>parseSource(id)?.kind!=='local'&&!this.state.sources.includes(id)));
      for(const [id,tile] of this.preloads)if(!desired.has(id)){this._disposeTile(tile);this.preloads.delete(id);}
      for(const id of desired)if(!this.preloads.has(id)){const tile=this._tile(id);this.preloads.set(id,tile);this.preloadHost.append(tile.node);}
    }
    _listen(target,type,listener,cleanups){target.addEventListener?.(type,listener);cleanups.push(()=>target.removeEventListener?.(type,listener));}
    _tile(id){
      const source=parseSource(id),node=this.document.createElement('figure');node.className='composition-tile';node.dataset.source=id;node.dataset.kind=source.kind;node.dataset.ready='false';
      const tile={id,source,node,track:null,stream:null,frameSeen:false,lastFrame:0,mediaTime:-1,ready:false,version:0,frameRequest:null,cleanups:[],trackCleanups:[],disposed:false};
      if(source.kind==='local'){
        const iframe=this.document.createElement('iframe');iframe.title='Program camera '+source.slot;iframe.src='/output/camera/'+source.slot;iframe.tabIndex=-1;node.append(iframe);tile.iframe=iframe;
      }else if(source.kind==='audio'){
        const avatar=this.document.createElement('span');avatar.className='composition-avatar';avatar.textContent='●';
        const label=this.document.createElement('figcaption');label.className='composition-speaker';label.textContent='Guest';node.append(avatar,label);tile.label=label;
      }else{
        const video=this.document.createElement('video');video.autoplay=true;video.muted=true;video.playsInline=true;video.setAttribute('playsinline','');video.setAttribute('aria-label',source.kind==='screen'?'Guest screen':'Guest camera');node.append(video);tile.video=video;
        const observe=()=>{if(!tile.disposed&&video.readyState>=2&&video.videoWidth>0&&liveTrack(tile.track)){tile.frameSeen=true;tile.lastFrame=this.now();}};
        this._listen(video,'loadeddata',observe,tile.cleanups);this._listen(video,'timeupdate',observe,tile.cleanups);
        this._listen(video,'error',()=>{tile.frameSeen=false;tile.ready=false;node.dataset.ready='false';this.refresh();},tile.cleanups);
      }
      const cover=this.document.createElement('span');cover.className='composition-cover';cover.setAttribute('aria-hidden','true');node.append(cover);return tile;
    }
    _bindTrack(tile,track){
      if(tile.track===track)return;
      tile.version++;for(const remove of tile.trackCleanups.splice(0))remove();
      if(tile.frameRequest!==null)tile.video?.cancelVideoFrameCallback?.(tile.frameRequest);
      tile.frameRequest=null;tile.track=track;tile.frameSeen=false;tile.lastFrame=0;tile.mediaTime=-1;
      if(tile.video){tile.video.pause?.();tile.video.srcObject=null;tile.stream=null;}
      if(!track)return;
      for(const event of ['mute','unmute','ended'])this._listen(track,event,()=>this.refresh(),tile.trackCleanups);
      if(!tile.video)return;
      tile.stream=this.makeStream([track]);tile.video.srcObject=tile.stream;
      Promise.resolve(tile.video.play?.()).catch(()=>{if(!tile.disposed){tile.frameSeen=false;tile.ready=false;tile.node.dataset.ready='false';}});
      const version=tile.version;
      if(tile.video.requestVideoFrameCallback){
        const decoded=()=>{
          if(tile.disposed||version!==tile.version)return;
          if(liveTrack(tile.track)&&tile.video.videoWidth>0){tile.frameSeen=true;tile.lastFrame=this.now();}
          tile.frameRequest=tile.video.requestVideoFrameCallback(decoded);
        };
        tile.frameRequest=tile.video.requestVideoFrameCallback(decoded);
      }
    }
    _refreshTile(tile){
      if(tile.disposed)return false;
      const source=tile.source;
      if(source.kind==='local'){
        try{const image=tile.iframe.contentDocument?.querySelector('img.live');tile.ready=Boolean(image?.complete&&image.naturalWidth>0);}catch(_){tile.ready=false;}
      }else{
        const allowed=permitted(source,this.room),tracks=this._tracks(source.participantId);
        const track=allowed?tracks[source.kind==='audio'?'microphone':source.kind]:null;
        this._bindTrack(tile,liveTrack(track)?track:null);
        if(tile.label){const p=participantFor(this.room,source.participantId);tile.label.textContent=typeof p?.name==='string'?p.name.slice(0,60):'Guest';}
        if(tile.video&&!tile.video.requestVideoFrameCallback&&tile.video.readyState>=2&&tile.video.videoWidth>0&&tile.video.currentTime!==tile.mediaTime){
          tile.mediaTime=tile.video.currentTime;tile.frameSeen=true;tile.lastFrame=this.now();
        }
        tile.ready=allowed&&liveTrack(tile.track)&&(source.kind==='audio'||(tile.frameSeen&&this.now()-tile.lastFrame<FRAME_TTL));
      }
      tile.node.dataset.ready=String(tile.ready);return tile.ready;
    }
    _allTiles(){return [...(this.current?.tiles||[]),...(this.outgoing?.tiles||[]),...this.preloads.values()];}
    readySources(){
      const allowed=new Set([...(this.state?.sources||[]),...(this.state?.preview||[])]);
      return [...new Set(this._allTiles().filter(tile=>tile.source.kind!=='local'&&tile.ready&&allowed.has(tile.id)).map(tile=>tile.id))].sort();
    }
    _disposeAudio(entry){entry.node.pause?.();entry.node.srcObject=null;entry.node.remove();}
    _clearAudio(){for(const entry of this.audio.values())this._disposeAudio(entry);this.audio.clear();}
    _syncAudio(){
      const sources=this.current?.tiles.filter(tile=>tile.ready).map(tile=>tile.id)||[];
      const plan=this.muted?new Map():audioPlan(sources,this.room,id=>this._tracks(id));
      for(const [key,entry] of this.audio)if(plan.get(key)!==entry.track){this._disposeAudio(entry);this.audio.delete(key);}
      for(const [key,track] of plan)if(!this.audio.has(key)){
        const node=this.document.createElement('audio');node.autoplay=true;node.muted=false;node.srcObject=this.makeStream([track]);this.audioHost.append(node);
        const entry={node,track,playing:false,blocked:false};this.audio.set(key,entry);this._playAudio(key,entry);
      }
    }
    _playAudio(key,entry){
      entry.blocked=false;entry.playing=false;
      Promise.resolve().then(()=>entry.node.play()).then(()=>{
        if(this.audio.get(key)!==entry)return;entry.playing=true;this._status();
      },()=>{if(this.audio.get(key)!==entry)return;entry.blocked=true;this._status();});
    }
    resumeAudio(){for(const [key,entry] of this.audio)if(!entry.playing)this._playAudio(key,entry);}
    _status(){
      const audioBlocked=[...this.audio.values()].some(entry=>entry.blocked);
      const rendered=Boolean(this.current?.visible&&this.current.tiles.every(tile=>tile.ready)&&[...this.audio.values()].every(entry=>entry.playing));
      const status={generation:this.state?.generation??-1,rendered,audioBlocked,readySources:this.readySources(),muted:this.muted};
      this.container.dataset.audioBlocked=String(audioBlocked);this.container.dataset.rendered=String(rendered);
      const serialized=JSON.stringify(status);if(serialized!==this.lastStatus){this.lastStatus=serialized;this._emit(this.onStatus,status);}
      if(rendered&&this.state){const signature=this.state.generation+':'+JSON.stringify(this.state.sources);if(signature!==this.lastRendered){
        // The HTTP state poll can beat signaling. Retry when its authenticated
        // receiver has not yet accepted this generation, rather than losing the receipt.
        try{if(this.onRendered(this.state.generation)!==false)this.lastRendered=signature;}catch(_){/* Retry on the next refresh. */}
      }}
    }
    refresh(){
      if(this.closed)return;
      if(this.state&&this.now()-this.lastReceived>STATE_TTL){this.clear();return;}
      for(const tile of this._allTiles())this._refreshTile(tile);
      this._syncAudio();this._status();
    }
    _disposeTile(tile){
      if(tile.disposed)return;tile.disposed=true;tile.version++;
      for(const remove of [...tile.cleanups,...tile.trackCleanups])remove();
      if(tile.frameRequest!==null)tile.video?.cancelVideoFrameCallback?.(tile.frameRequest);
      if(tile.video){tile.video.pause?.();tile.video.srcObject=null;}
      if(tile.iframe)tile.iframe.removeAttribute('src');
      tile.node.remove();tile.track=null;tile.stream=null;
    }
    _disposeLayer(layer){for(const tile of layer.tiles)this._disposeTile(tile);layer.node.remove();}
    clear(){
      this.epoch++;this.cancel(this.timer);this.cancelFrame(this.frameTimer);this.timer=null;this.frameTimer=null;
      if(this.current)this._disposeLayer(this.current);if(this.outgoing)this._disposeLayer(this.outgoing);
      this.current=null;this.outgoing=null;
      for(const tile of this.preloads.values())this._disposeTile(tile);this.preloads.clear();this._clearAudio();
      this.state=null;this.room=null;this.roomRevision=-1;this.lastRendered=null;this._status();
    }
    close(){if(this.closed)return;this.clear();this.closed=true;this.cancelRepeat(this.watchdog);this.preloadHost.remove();this.audioHost.remove();}
  }
  function boot(){
    const container=host.document?.querySelector('[data-producer-program-output]');
    if(!container||container.dataset.compositionStarted==='true'||!host.RareIQOverlay||!host.ProducerGuestMedia)return;
    container.dataset.compositionStarted='true';let view,receiver,stopped=false;
    receiver=host.ProducerGuestMedia.createReceiver({role:'output',
      onState:message=>{if(!stopped&&message.room){view.setRoom(message.room);view.render(message.room.switcher);}},
      onTracks:()=>view?.refresh(),
      onConnection:event=>{if(!event.participant_id&&['disconnected','closed'].includes(event.state))view?.clear();},
      onError:()=>view?.refresh()});
    view=new ProducerCompositionView({container,mediaReceiver:receiver,onRendered:generation=>receiver.rendered(generation)});
    const stopPoll=host.RareIQOverlay.start({interval:300,load:signal=>host.RareIQOverlay.json('/api/production/switcher',signal),render:state=>view.render(state),clear:()=>view.clear()});
    const ready=host.setInterval(()=>receiver.sendReady(view.readySources()),1000);
    const resume=()=>view.resumeAudio();host.addEventListener('pointerdown',resume);host.addEventListener('keydown',resume);
    host.addEventListener('pagehide',()=>{stopped=true;host.clearInterval(ready);stopPoll();view.close();receiver.close();host.removeEventListener('pointerdown',resume);host.removeEventListener('keydown',resume);},{once:true});
    Promise.resolve(receiver.connect()).catch(()=>view.clear());return {view,receiver};
  }
  const exported={ProducerCompositionView,parseSource,sourceList,normalizeState,liveTrack,participantFor,permitted,audioPlan,boot};
  if(typeof module==='object'&&module.exports)module.exports=exported;
  host.ProducerCompositionView=ProducerCompositionView;host.ProducerComposition=exported;
  if(host.document){if(host.document.readyState==='loading')host.document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();}
})(typeof window!=='undefined'?window:globalThis);
