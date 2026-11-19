/* Replay controls retain exact uncertain requests; files stay behind the native chooser. */
(function(host){
  'use strict';
  const PHASES=new Set(['idle','starting','buffering','stopping','failed']);
  const REASONS={replay_busy:'Finish the current output action first.',replay_cancelled:'Replay action cancelled.',replay_not_running:'Start the replay buffer first.',replay_buffer_empty:'Wait for recent Program picture and audio to reach the buffer.',replay_save_busy:'A replay clip is already being saved.',replay_start_failed:'The replay buffer could not start. Check Program and try again.',replay_stop_unconfirmed:'Replay shutdown is unconfirmed. Keep the studio open and retry Stop buffer.',replay_ownership_unconfirmed:'Replay ownership is unconfirmed. Keep the studio open and retry Stop buffer.',replay_output_unavailable:'The Program output became unavailable. Restore the source before starting the buffer again.',replay_save_failed:'The clip could not be saved. Check the folder and try a new clip.',replay_not_saved:'No finalized replay clip is available.',prepare_output:'Prepare a ready Program output first.',output_not_ready:'Wait for the Program picture and audio before starting replay.',output_generation_changed:'Program changed during setup. Check the output and retry.',rehearsal_active:'Leave rehearsal before starting or saving replay.',rehearsal_status_unavailable:'Check rehearsal status before starting replay.',recording_file_exists:'That file exists. Choose a new filename to preserve it.',invalid_recording_file:'Choose a new .mkv file in an available folder.',recording_storage_unavailable:'The folder is unavailable. Choose another folder.',insufficient_recording_space:'There is not enough free disk space. Choose another drive or free space.',recording_finalize_failed:'The clip could not be finalized. Retain the file and check your disk.',encoder_backpressure:'Replay encoding could not keep up. Choose HD and retry.',encoder_failed:'The replay encoder stopped unexpectedly. Check Program and retry.'};
  const count=value=>Number.isSafeInteger(value)&&value>=0?value:0;
  function normalize(value){
    if(!value||typeof value!=='object'||!PHASES.has(value.phase)||['active','running','ownershipPending','canStart','canSave','saving'].some(key=>typeof value[key]!=='boolean'))throw Error('replay_status_unavailable');
    const file=typeof value.lastFileName==='string'&&value.lastFileName.length<=255&&!/[:\\/\x00-\x1f\x7f]/.test(value.lastFileName)?value.lastFileName:null;
    return {phase:value.phase,active:value.active,running:value.running,ownershipPending:value.ownershipPending,canStart:value.canStart,canSave:value.canSave,saving:value.saving,available:value.available===true,seconds:[15,30,60].includes(value.seconds)?value.seconds:30,bufferSeconds:typeof value.bufferSeconds==='number'&&Number.isFinite(value.bufferSeconds)&&value.bufferSeconds>=0?Math.min(60,value.bufferSeconds):0,bufferBytes:count(value.bufferBytes),maxBytes:count(value.maxBytes),frames:count(value.frames),elapsedMs:count(value.elapsedMs),lastFileName:file,finalized:value.finalized===true,savedBytes:count(value.savedBytes),reason:Object.hasOwn(REASONS,value.reason)?value.reason:null,saveReason:Object.hasOwn(REASONS,value.saveReason)?value.saveReason:null};
  }
  function createController({request,onChange=()=>{},onBusy=()=>{},onStatus=()=>{},randomId=()=>crypto.randomUUID()}={}){
    let state={replay:null,seconds:30,working:'',stale:true,locked:false,publishingBlocked:true,message:'Checking Program replay…'},closed=false,epoch=0,pending=null;
    const snapshot=()=>({...state,replay:state.replay?{...state.replay}:null,retry:Boolean(pending),pendingAction:pending?.action||null}),emit=()=>onChange(snapshot());
    const install=value=>{state.replay=normalize(value);state.stale=false;if(state.replay.active)state.seconds=state.replay.seconds;return state.replay;};
    function setContext({replay,locked,publishingBlocked}={}){if(closed)return;if(replay!==undefined)try{install(replay);}catch(_){state.stale=true;}if(typeof locked==='boolean')state.locked=locked;if(typeof publishingBlocked==='boolean')state.publishingBlocked=publishingBlocked;emit();}
    function setSeconds(value){if(closed||state.working||pending||state.replay?.active||![15,30,60].includes(value))return false;state.seconds=value;emit();return true;}
    async function run(action){
      if(closed||!['status','start','save','stop','reveal','retry'].includes(action))return false;
      if(action==='retry'){if(!pending)return false;action=pending.action;}
      const record=state.replay,read=action==='status',stop=action==='stop';
      if(state.working&&!(stop&&state.working!=='stop'))return false;
      if(action==='start'&&(state.locked||state.publishingBlocked||state.stale||!record?.available||!record.canStart||record.active||record.ownershipPending||pending&&pending.action!=='start'))return false;
      if(action==='save'&&(state.locked||state.publishingBlocked||state.stale||!record?.available||!record.canSave||!record.running||record.saving||pending&&pending.action!=='save'))return false;
      if(stop&&!record?.active&&!record?.ownershipPending&&!pending&&!['start','save'].includes(state.working))return false;
      if(action==='reveal'&&(state.stale||!record?.finalized))return false;
      const payload=['start','save'].includes(action)?pending||{action,requestId:randomId(),...(action==='start'?{seconds:state.seconds}:{})}:{action};
      if(['start','save'].includes(action))pending=payload;
      const own=++epoch;state.working=action;if(!read)onBusy(true);state.message=({status:'Checking replay status…',start:'Review confirmation before the buffer starts.',save:'Choose a new file and review your replay clip.',stop:'Stopping the replay buffer…',reveal:'Opening the last clip’s folder…'})[action];emit();
      try{
        const result=await request({...payload});if(closed||own!==epoch)return false;
        if(result?.ok===true&&!result.replay)throw Error('replay_status_unavailable');
        if(result?.replay){const value=install(result.replay);onStatus(value);}
        if(result?.ok!==true){state.message=REASONS[result?.reason]||'Replay status is unconfirmed. Check status and retry Stop buffer if needed.';if(result?.replay&&!read)pending=null;else if(!result?.replay)state.stale=true;return false;}
        if(!read)pending=null;
        state.message=action==='reveal'?'Last saved clip shown in its folder.':action==='save'&&state.replay?.finalized?'Replay clip saved. The buffer keeps running.':state.replay?.active?'Replay buffer is running. Save clip to keep recent Program picture and Live audio.':'Replay buffer is stopped. Saved clips remain available.';
        return true;
      }catch(_){if(!closed&&own===epoch){state.stale=true;state.message='Replay status is unconfirmed. Check status, retry the same action, or Stop buffer.';}return false;}
      finally{if(!closed&&own===epoch){state.working='';if(!read)onBusy(false);emit();}}
    }
    return {run,setContext,setSeconds,snapshot,close(){closed=true;++epoch;if(state.working&&state.working!=='status')onBusy(false);state.working='';}};
  }
  function mount({root,api=host.producerSettings,onBusy=()=>{},onStatus=()=>{}}={}){
    if(!root||typeof api?.replayActions!=='function')return null;
    const node=name=>root.querySelector('[data-replay-'+name+']');
    const controller=createController({request:value=>api.replayActions(value),onBusy,onStatus,onChange(state){
      const r=state.replay,busy=Boolean(state.working);root.setAttribute('aria-busy',String(busy));
      node('badge').textContent=state.stale?'Check status':r?.phase==='buffering'?'Buffering':r?.phase==='failed'?'Needs attention':r?.active?'Working':'Stopped';
      node('start').disabled=busy||state.stale||state.locked||state.publishingBlocked||!r?.available||!r.canStart||r.active||r.ownershipPending||state.retry&&state.pendingAction!=='start';
      node('save').disabled=busy||state.stale||state.locked||state.publishingBlocked||!r?.available||!r.canSave||r.saving||state.retry&&state.pendingAction!=='save';
      node('stop').disabled=state.working==='stop'||(!r?.active&&!r?.ownershipPending&&!state.retry&&!['start','save'].includes(state.working));
      const retryReady=state.pendingAction==='start'?r?.canStart&&!r?.active:r?.canSave&&!r?.saving;
      node('check').disabled=busy;node('reveal').disabled=busy||state.stale||!r?.finalized;node('retry').hidden=!state.retry||busy;node('retry').disabled=busy||state.stale||state.locked||state.publishingBlocked||!retryReady;node('retry').title=node('retry').disabled?'Check status; Stop buffer remains available for an unresolved action.':'Retry the exact previous request without making another clip.';
      node('seconds').disabled=busy||state.retry||r?.active===true;node('seconds').value=String(state.seconds);
      node('history').textContent=(r?.bufferSeconds||0).toFixed(1)+' s';node('memory').textContent=((r?.bufferBytes||0)/(1024*1024)).toFixed(1)+' MiB';node('frames').textContent=String(r?.frames||0);
      node('file').textContent=r?.lastFileName||'Choose a new MKV file when you save a clip.';node('status').textContent=r?.saveReason&&REASONS[r.saveReason]||r?.reason&&REASONS[r.reason]||state.message;
      node('start').title=node('start').disabled?(state.publishingBlocked?'Leave rehearsal before starting replay.':state.stale?'Check replay status first.':state.locked?'Finish the current output action first.':r?.active?'Stop the current buffer first.':'Prepare a ready Program output first.'):'Review the replay buffer confirmation before retaining media in memory.';
      node('save').title=node('save').disabled?(state.stale?'Check replay status first.':state.publishingBlocked?'Leave rehearsal before saving replay.':state.locked?'Finish the current output action first.':'Start replay and wait for picture and audio to reach the buffer.'):'Choose a new file for the available recent Program picture and Live audio.';
      node('stop').title=node('stop').disabled?'The replay buffer is stopped.':'Stop only replay and discard unsaved history; broadcasting and recording continue.';node('reveal').title=node('reveal').disabled?'Save and finalize a replay clip first.':'Open the last finalized clip in its folder.';
    }});
    for(const name of ['start','save','stop','check','reveal','retry'])node(name).addEventListener('click',()=>controller.run(name==='check'?'status':name));
    let seconds;try{seconds=Number(host.localStorage?.getItem('producer-replay-seconds'));}catch(_){}if([15,30,60].includes(seconds))controller.setSeconds(seconds);
    node('seconds').addEventListener('change',()=>{const value=Number(node('seconds').value);if(controller.setSeconds(value))try{host.localStorage?.setItem('producer-replay-seconds',String(value));}catch(_){} });
    return controller;
  }
  const api={normalize,createController,mount};if(typeof module==='object'&&module.exports)module.exports=api;else host.ProducerReplayUI=api;
})(typeof window==='undefined'?globalThis:window);
