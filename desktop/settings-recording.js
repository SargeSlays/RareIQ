/* Native recording has a separate Stop and stores no paths in the renderer. */
(function(host){
  'use strict';
  const PHASES=new Set(['idle','choosing','confirming','starting','recording','stopping','saved','failed']);
  const REASONS={prepare_output:'Choose Program sources and prepare the output first.',output_not_ready:'Wait for a ready Program picture and audio before recording.',output_generation_changed:'Program changed during setup. Check the output and try again.',recording_busy:'Finish the current output action first.',recording_cancelled:'Recording cancelled. No new recording was started.',recording_file_exists:'That file already exists. Choose a new filename to keep it safe.',invalid_recording_file:'Choose a new .mkv file in an available folder.',recording_storage_unavailable:'The selected folder is unavailable. Choose another folder.',insufficient_recording_space:'There is not enough free space in that folder. Free space or choose another drive.',recording_start_failed:'Recording could not start. Check the output and folder, then retry.',recording_stop_unconfirmed:'Recording shutdown is unconfirmed. Keep the studio open and retry Stop recording.',recording_ownership_unconfirmed:'Recording ownership is unconfirmed. Keep the studio open and retry Stop recording.',recording_finalize_failed:'The file could not be finalized. Keep the retained file and check your disk before retrying.',recording_output_unavailable:'The Program output became unavailable. Check the retained file and restore the source.',rehearsal_active:'Leave rehearsal separately before recording. Local rehearsal does not save show media.',rehearsal_status_unavailable:'Check rehearsal status before recording.',encoder_backpressure:'Recording could not keep up. Check the retained file, choose HD, and retry.',encoder_failed:'The recording encoder stopped unexpectedly. Check the retained file and retry.'};
  const count=value=>Number.isSafeInteger(value)&&value>=0?value:0;
  function normalize(value){
    if(!value||typeof value!=='object'||!PHASES.has(value.phase)||typeof value.active!=='boolean'||typeof value.ownershipPending!=='boolean'||typeof value.canStart!=='boolean')throw Error('recording_status_unavailable');
    const fileName=typeof value.fileName==='string'&&value.fileName.length<=255&&!/[:\\/\x00-\x1f\x7f]/.test(value.fileName)?value.fileName:null;
    return {phase:value.phase,active:value.active,ownershipPending:value.ownershipPending,canStart:value.canStart,available:value.available===true,finalized:value.finalized===true,fileName,frames:count(value.frames??value.videoFrames),audioSamples:count(value.audioSamples),bytesWritten:count(value.bytesWritten??value.recordingBytes),elapsedMs:count(value.elapsedMs),reason:Object.hasOwn(REASONS,value.reason)?value.reason:null};
  }
  function createController({request,onChange=()=>{},onBusy=()=>{},onStatus=()=>{},randomId=()=>crypto.randomUUID()}={}){
    let state={recording:null,working:'',stale:true,locked:false,publishingBlocked:true,message:'Checking local recording…'},closed=false,epoch=0,pending=null;
    const snapshot=()=>({...state,recording:state.recording?{...state.recording}:null,retry:Boolean(pending)}),emit=()=>onChange(snapshot());
    function install(value){state.recording=normalize(value);state.stale=false;return state.recording;}
    function setContext({recording,locked,publishingBlocked}={}){
      if(closed)return;if(recording!==undefined)try{install(recording);}catch(_){state.stale=true;}if(typeof locked==='boolean')state.locked=locked;if(typeof publishingBlocked==='boolean')state.publishingBlocked=publishingBlocked;emit();
    }
    async function run(action){
      if(closed||!['status','start','stop','reveal','retry'].includes(action))return false;
      if(action==='retry'){if(!pending)return false;action=pending.action;}
      const stop=action==='stop',read=action==='status',record=state.recording;
      if(state.working&&!(stop&&state.working!=='stop'))return false;
      if(action==='start'&&(state.locked||state.publishingBlocked||state.stale||!record?.available||!record?.canStart||record.active||record.ownershipPending))return false;
      if(stop&&!record?.active&&!record?.ownershipPending&&state.working!=='start'&&!pending)return false;
      if(action==='reveal'&&(!record?.finalized||state.stale))return false;
      const payload=action==='start'?(pending||{action,requestId:randomId()}):{action};if(!read&&action==='start')pending=payload;
      const own=++epoch;state.working=action;if(!read)onBusy(true);state.message=({status:'Checking recording status…',start:'Choose a new file, then confirm recording.',stop:'Finalizing the recording…',reveal:'Opening the saved file’s folder…'})[action];emit();
      try{
        const result=await request({...payload});if(closed||own!==epoch)return false;
        if(result?.ok===true&&!result.recording)throw Error('recording_status_unavailable');
        if(result?.recording){const value=install(result.recording);onStatus(value);}
        if(!result||result.ok!==true){state.message=REASONS[result?.reason]||'Recording could not be confirmed. Check status and retry Stop if needed.';if(result?.recording)pending=null;else state.stale=true;return false;}
        if(!read)pending=null;const current=state.recording;
        state.message=action==='reveal'?'Saved recording shown in its folder.':current?.finalized?'Recording saved. Broadcasting has its own Stop control.':current?.active?'Program recording is running. Broadcasting has its own Start and Stop controls.':'Recording is stopped.';
        return true;
      }catch(_){if(!closed&&own===epoch){state.stale=true;state.message='Recording status is unconfirmed. Check status before starting again; Stop recording remains available.';}return false;}
      finally{if(!closed&&own===epoch){state.working='';if(!read)onBusy(false);emit();}}
    }
    return {run,setContext,snapshot,close(){closed=true;++epoch;if(state.working&&state.working!=='status')onBusy(false);state.working='';}};
  }
  function mount({root,api=host.producerSettings,onBusy=()=>{},onStatus=()=>{}}={}){
    if(!root||typeof api?.recordingActions!=='function')return null;
    const node=name=>root.querySelector('[data-recording-'+name+']');
    const controller=createController({request:value=>api.recordingActions(value),onBusy,onStatus,onChange(state){
      const r=state.recording,working=Boolean(state.working);root.setAttribute('aria-busy',String(working));
      node('badge').textContent=state.stale?'Check status':r?.phase==='saved'?'Saved':r?.phase==='recording'?'Recording':r?.phase==='failed'?'Needs attention':r?.active?'Working':'Stopped';
      node('start').disabled=working||state.stale||state.locked||state.publishingBlocked||!r?.available||!r?.canStart||r.active||r.ownershipPending;
      node('start').textContent=state.working==='start'?'Starting recording…':'Record Program';
      node('stop').disabled=state.working==='stop'||(!r?.active&&!r?.ownershipPending&&state.working!=='start'&&!state.retry);node('stop').textContent=state.working==='stop'?'Finalizing…':'Stop recording';
      node('check').disabled=working;node('reveal').disabled=working||state.stale||!r?.finalized;
      node('file').textContent=r?.fileName||'Choose a new Matroska (.mkv) file when you start.';
      const seconds=Math.floor((r?.elapsedMs||0)/1000);node('time').textContent=[Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(value=>String(value).padStart(2,'0')).join(':');
      node('frames').textContent=String(r?.frames||0);node('size').textContent=((r?.bytesWritten||0)/(1024*1024)).toFixed(1)+' MB';
      node('status').textContent=r?.reason&&REASONS[r.reason]||state.message;
      node('start').title=node('start').disabled?(state.publishingBlocked?'Leave rehearsal before recording.':state.locked?'Finish the current output action first.':state.stale?'Check recording status first.':r?.active||r?.ownershipPending?'Stop the current recording and confirm finalization first.':'Prepare a ready Program output first.'):'Choose a new file and review confirmation before recording.';
      node('stop').title=node('stop').disabled?'No recording needs stopping.':'Stop only the recording; a running broadcast continues.';node('reveal').title=node('reveal').disabled?'Finish and confirm recording before opening the file.':'Open the saved file in its folder.';
    }});
    for(const [name,action]of [['start','start'],['stop','stop'],['check','status'],['reveal','reveal']])node(name).addEventListener('click',()=>controller.run(action));
    return controller;
  }
  const api={normalize,createController,mount};if(typeof module==='object'&&module.exports)module.exports=api;else host.ProducerRecordingUI=api;
})(typeof window==='undefined'?globalThis:window);
