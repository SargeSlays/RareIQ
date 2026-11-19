/* Local rehearsal controls. Main owns isolation, encoder ownership and exit confirmation. */
(() => {
  'use strict';
  const STATES=Object.freeze({not_tested:'Not tested',passed:'Passed',needs_attention:'Needs attention'});
  const bounded=(value,limit=160)=>typeof value==='string'?value.replace(/[\x00-\x1f\x7f]/g,' ').slice(0,limit):'';
  const count=value=>Number.isFinite(value)&&value>=0?Math.floor(value).toLocaleString():'—';
  function create({root,api,onBusy=()=>{},onChange=()=>{}}){
    if(!root)return null;
    const node=name=>root.querySelector('#rehearsal'+name),listeners=[],writes=new Set();
    let closed=false,started=false,locked=false,snapshot=null,timer=null,readPending=false,readSerial=0,writeSerial=0,failures=0,inFlight=0,stopBusy=false,pending=null,message='',uncertain=false,statusUnavailable=true,conflict=false,lastNotification='',checkStamp='';
    const active=()=>Boolean(snapshot?.room?.active)||['entering','rehearsal','recovery_required'].includes(snapshot?.room?.mode);
    const stoppingNeeded=()=>active()||uncertain||Boolean(snapshot?.local?.running||snapshot?.local?.ownershipPending)||['starting','running','stopping','failed'].includes(snapshot?.local?.state);
    function listen(element,event,handler){element.addEventListener(event,handler);listeners.push([element,event,handler]);}
    function notify(){const value={...snapshot,busy:inFlight>0,uncertain,statusUnavailable,pendingAction:pending?.action||null},stamp=JSON.stringify(value);if(stamp!==lastNotification){lastNotification=stamp;onChange(value);}}
    function actionBlocker(){if(locked)return 'Finish the current setup action first.';if(inFlight)return 'Wait for the current rehearsal action to finish.';if(conflict)return 'Check current status before trying again.';if(uncertain)return 'Retry the same action or confirm Stop before making another change.';return '';}
    function button(name,disabled,why=''){const element=node(name);element.disabled=disabled;element.title=disabled?why:'';}
    function renderChecks(){
      const checks=(Array.isArray(snapshot?.room?.checks)?snapshot.room.checks:[]).slice(0,40),stamp=JSON.stringify(checks);
      if(stamp!==checkStamp){
        checkStamp=stamp;node('Checks').replaceChildren();
        for(const item of checks){
          const id=bounded(item?.id,80);if(!id)continue;
          const row=root.ownerDocument.createElement('label');row.className='rehearsal-check';
          const label=root.ownerDocument.createElement('span');label.textContent=bounded(item.label,120)||id;
          const select=root.ownerDocument.createElement('select');select.dataset.checkId=id;select.setAttribute('aria-label',label.textContent+' result');
          for(const [value,text] of Object.entries(STATES)){const option=root.ownerDocument.createElement('option');option.value=value;option.textContent=text;select.append(option);}
          select.value=Object.hasOwn(STATES,item.status)?item.status:'not_tested';row.append(label,select);node('Checks').append(row);
        }
      }
      for(const element of node('Checks').querySelectorAll('select')){element.disabled=!active()||Boolean(actionBlocker());element.title=element.disabled?(actionBlocker()||'Enter rehearsal to mark your checks.'):'';}
      node('CheckEmpty').hidden=checks.length>0;
    }
    function render(){
      if(closed)return;
      const room=snapshot?.room,local=snapshot?.local,blocked=actionBlocker(),isActive=active(),ready=room?.mode==='rehearsal'&&room?.active===true&&snapshot?.outputPrepared===true;
      root.dataset.mode=uncertain?'uncertain':room?.mode||'unknown';
      node('Badge').textContent=isActive?'REHEARSAL — not broadcasting':uncertain?'Rehearsal status unconfirmed':snapshot?'Production setup':'Checking status…';
      node('Badge').dataset.active=String(isActive||uncertain);
      node('Enter').hidden=isActive;button('Enter',!snapshot||Boolean(blocked),blocked||'Check current rehearsal status first.');
      node('Exit').hidden=!isActive||room?.mode==='recovery_required';button('Exit',Boolean(blocked)||Boolean(local?.running||local?.ownershipPending)||['starting','stopping'].includes(local?.state),blocked||'Confirm Stop local encoding before leaving rehearsal.');
      node('Recover').hidden=room?.mode!=='recovery_required';button('Recover',Boolean(blocked)||Boolean(local?.running||local?.ownershipPending)||['starting','stopping','failed'].includes(local?.state),blocked||'Confirm Stop local encoding before restoring production setup.');
      node('Start').hidden=!isActive;button('Start',Boolean(blocked)||!ready||Boolean(local?.running||local?.ownershipPending)||['starting','stopping','failed'].includes(local?.state),blocked||(!snapshot?.outputPrepared?'Prepare output below before starting local encoding.':'Local encoding must be stopped before starting again.'));
      const confirmedStopping=stopBusy||(local?.state==='stopping'&&!uncertain);
      node('Stop').hidden=!stoppingNeeded();button('Stop',confirmedStopping,'Waiting for local encoding to stop.');node('Stop').textContent=confirmedStopping?'Stopping local encoding…':'Stop local encoding';
      node('Prepare').hidden=!isActive||snapshot?.outputPrepared===true;button('Prepare',Boolean(inFlight),'Wait for the current rehearsal action to finish.');
      node('Retry').hidden=!pending;button('Retry',Boolean(inFlight)||locked,locked?'Finish the current setup action first.':'Wait for the current rehearsal action to finish.');
      node('Retry').textContent=pending?'Retry same '+({start:'local start',stop:'local stop',enter:'entry',exit:'exit',recover:'recovery',mark:'check',monitor:'monitor change',export_report:'report export'}[pending.action]||'action'):'Retry same action';
      button('Refresh',readPending,'Checking rehearsal status…');button('Export',!isActive||Boolean(blocked),blocked||'Enter rehearsal to save a report.');
      node('Local').textContent=local?.running||local?.state==='running'||local?.state==='encoding'?'Local encoding is running. No platform delivery is being tested.':local?.state==='starting'?'Starting local encoding…':local?.state==='stopping'?'Stopping local encoding…':local?.state==='failed'?'Local encoding needs attention. Confirm Stop before starting again.':'Local encoding is stopped.';
      node('Counters').textContent=local?`${count(local.frames)} frames · ${count(local.audioSamples)} Live audio samples · ${count(local.vodAudioSamples)} VOD audio samples · ${count(local.bytesMuxed)} bytes muxed${bounded(local.codec,40)?' · '+bounded(local.codec,40):''}`:'Counters appear when local encoding starts.';
      const monitor=node('Monitor');monitor.value=['live','vod'].includes(snapshot?.monitor?.bus)?snapshot.monitor.bus:'off';
      monitor.querySelector('option[value="live"]').disabled=snapshot?.monitor?.available!==true;
      monitor.querySelector('option[value="vod"]').disabled=snapshot?.monitor?.available!==true||snapshot?.monitor?.vodAvailable===false;
      monitor.disabled=!isActive||Boolean(blocked)||(snapshot?.monitor?.available!==true&&monitor.value==='off');monitor.title=monitor.disabled?(blocked||'Prepare an output with local audio monitoring available.'):'';
      node('MonitorHint').textContent=snapshot?.monitor?.available===true?'Choose a mix to hear it locally. Off keeps your speakers quiet. Headphones help prevent feedback.':'Monitoring is unavailable until the prepared output supplies local audio. Your speakers stay quiet.';
      node('Status').textContent=message||(room?.mode==='recovery_required'?(room.reason==='rehearsal_storage_invalid'?'Rehearsal storage needs attention. Publishing remains blocked. Check the configured storage location before restoring production setup.':'Rehearsal recovery is required. Publishing remains blocked; confirm Stop and check status.'):isActive?'Publishing and recording are blocked in rehearsal. Prepare output, then start local encoding when ready.':'Enter rehearsal to practice locally with publishing and recording blocked.');
      node('Status').dataset.state=uncertain||conflict||room?.mode==='recovery_required'?'warning':'ready';
      renderChecks();notify();
    }
    function accept(value){
      if(!value||!value.room||!value.local)return false;
      if(!['production','entering','rehearsal','recovery_required'].includes(value.room.mode))return false;
      snapshot=value;statusUnavailable=value.ok===false&&/status_unavailable|storage_unavailable|idle_unavailable/.test(reason(value));failures=0;notify();return true;
    }
    function schedule(){clearTimeout(timer);if(started&&!closed)timer=setTimeout(()=>{timer=null;void refresh();},Math.min(1000*2**Math.min(failures,4),15000));}
    async function refresh(){
      if(closed||readPending||inFlight){schedule();return false;}
      readPending=true;const serial=++readSerial,write=writeSerial;render();
      try{
        const value=await api.rehearsal({action:'status'});if(closed||serial!==readSerial||write!==writeSerial)return false;
        if(value?.ok===false||!accept(value))throw Error('status_unavailable');
        if(conflict){conflict=false;message='Current rehearsal status loaded. Review it before trying again.';}
        else if(!uncertain&&message==='Rehearsal status is unavailable. Check again; publishing status has not been confirmed.')message='';
        return true;
      }catch(error){if(!closed&&serial===readSerial&&write===writeSerial){++failures;statusUnavailable=true;if(!uncertain)message='Rehearsal status is unavailable. Check again; publishing status has not been confirmed.';}return false;}
      finally{if(serial===readSerial)readPending=false;if(!closed){render();schedule();}}
    }
    function reason(value){return bounded(value?.reason||value?.code||(typeof value?.error==='string'?value.error:value?.error?.code)||value?.message,100);}
    async function mutate(action,extra={},retry=false){
      if(closed)return false;
      const isStop=action==='stop';
      if(isStop?(stopBusy||(snapshot?.local?.state==='stopping'&&!uncertain)):(Boolean(actionBlocker())&&!(retry&&uncertain&&!locked&&!inFlight&&!conflict)))return false;
      if(!isStop&&!retry&&['start','exit','mark','monitor','export_report'].includes(action)&&!active())return false;
      if(action==='start'&&!retry&&(!snapshot?.outputPrepared||snapshot?.room?.mode!=='rehearsal'||snapshot?.local?.running||snapshot?.local?.ownershipPending||['starting','stopping','failed'].includes(snapshot?.local?.state)))return false;
      if(action==='recover'&&(snapshot?.room?.mode!=='recovery_required'||snapshot?.local?.running||snapshot?.local?.ownershipPending||['starting','stopping','failed'].includes(snapshot?.local?.state)))return false;
      if(action==='monitor'&&extra.bus==='vod'&&snapshot?.monitor?.vodAvailable===false){render();return false;}
      const request=retry&&pending?{...pending}:{action,requestId:crypto.randomUUID(),revision:snapshot?.room?.revision,generation:snapshot?.room?.generation,...extra};
      const serial=++writeSerial,wasBusy=inFlight>0;clearTimeout(timer);if(isStop)writes.clear();writes.add(serial);inFlight=writes.size;if(!wasBusy)onBusy(true);if(isStop)stopBusy=true;
      pending=request;uncertain=false;message=({enter:'Entering rehearsal…',exit:'Requesting return to production setup…',recover:'Requesting recovery of production setup…',start:'Starting local encoding…',stop:'Confirming local encoding has stopped…',mark:'Saving your check…',monitor:'Changing local monitoring…',export_report:'Saving the metadata-only rehearsal report…'})[action];render();
      try{
        const value=await api.rehearsal({...request});if(closed||serial!==writeSerial)return false;
        const code=reason(value);
        if(value?.cancelled===true||value?.state==='cancelled'){pending=null;accept(value);message=action==='export_report'?'Report export cancelled. No report was saved.':'Action cancelled. Rehearsal status is unchanged.';return false;}
        if(value?.ok===false){
          if(/revision|generation|stale|conflict/.test(code)){pending=null;conflict=true;message='Rehearsal changed in another window. Checking current status before another action.';return false;}
          if(/cancel/.test(code)||value.state==='cancelled'){pending=null;message='Action cancelled. Rehearsal status is unchanged.';accept(value);return false;}
          if(accept(value)){pending=null;message=({output_not_prepared:'Prepare output below before starting local encoding.',monitor_unavailable:'This output does not have local audio monitoring available.',rehearsal_monitor_unavailable:'This output does not have local audio monitoring available.',rehearsal_required:'Enter rehearsal before starting local encoding.',ownership_pending:'Confirm Stop before starting again.',rehearsal_production_busy:'Stop any active session, recording or encoder. If OBS integration is enabled, open/connect OBS and confirm it is idle, then check status and retry.',rehearsal_idle_unavailable:'The production idle check could not be confirmed. Check the studio and any enabled OBS connection, confirm they are idle, then check status and retry.'})[code]||'This rehearsal action could not complete. Review the current status and try again.';return false;}
          throw Error('action_unconfirmed');
        }
        if(!accept(value))throw Error('action_unconfirmed');
        pending=null;uncertain=false;
        message=({enter:'REHEARSAL — not broadcasting. Publishing and recording are blocked.',exit:active()?'Rehearsal remains active.':'Returned to production setup. A separate broadcast confirmation is still required.',recover:active()?'Rehearsal recovery still needs attention.':'Production setup restored. A separate broadcast confirmation is still required.',start:'Local encoding started. Counters describe this local run; they do not verify a platform.',stop:'Local encoding stopped.',mark:'Your manual check was saved. This is an operator observation.',monitor:'Local monitoring changed. This does not verify sound quality.',export_report:'Rehearsal report saved. It contains metadata and manual checks; no recording.'})[action];
        if(action==='stop'&&(value.local.running||value.local.ownershipPending||['starting','stopping'].includes(value.local.state))){pending=request;uncertain=true;message='Stop is not yet confirmed. Check status or retry the same Stop before changing output.';}
        return !uncertain;
      }catch(error){if(!closed&&serial===writeSerial){pending=request;uncertain=true;message='Action not confirmed. Retry the same action to reconcile it, or confirm Stop local encoding. Publishing status has not been confirmed.';}return false;}
      finally{
        const tracked=writes.delete(serial);inFlight=writes.size;if(isStop)stopBusy=false;if(tracked&&!inFlight&&!closed)onBusy(false);
        if(!closed){render();if(conflict&&!inFlight)void refresh();else schedule();}
      }
    }
    for(const [name,action] of [['Enter','enter'],['Exit','exit'],['Recover','recover'],['Start','start'],['Stop','stop'],['Export','export_report']])listen(node(name),'click',()=>mutate(action));
    listen(node('Refresh'),'click',refresh);listen(node('Retry'),'click',()=>pending&&mutate(pending.action,{},true));
    listen(node('Prepare'),'click',()=>root.ownerDocument.querySelector('#prepareOutput')?.focus());
    listen(node('Monitor'),'change',()=>{const bus=node('Monitor').value;if(['off','live','vod'].includes(bus))void mutate('monitor',{bus});});
    listen(node('Checks'),'change',event=>{const target=event.target;if(target?.dataset?.checkId&&Object.hasOwn(STATES,target.value))void mutate('mark',{checkId:target.dataset.checkId,checkState:target.value});});
    function start(){if(closed||started)return;started=true;void refresh();}
    function setContext(value={}){if(closed)return;if(typeof value.locked==='boolean')locked=value.locked;render();}
    function close(){if(closed)return;closed=true;started=false;++readSerial;++writeSerial;clearTimeout(timer);for(const [element,event,handler] of listeners)element.removeEventListener(event,handler);if(inFlight)onBusy(false);}
    render();return {start,close,setContext};
  }
  window.ProducerRehearsalUI=Object.freeze({create});
})();
