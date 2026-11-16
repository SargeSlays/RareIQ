(function (root) {
  'use strict';
  const labels = {open_palm:'Open palm', thumbs_up:'Thumbs up', victory:'Victory / V sign',
    look_camera_1:'Toward camera 1', look_camera_2:'Toward camera 2', look_camera_3:'Toward camera 3', look_camera_4:'Toward camera 4'};
  const messages = {
    vision_assets_unavailable:'Local vision models are unavailable. Ask the studio host to set up the experimental vision assets.',
    vision_local_operator_only:'Vision controls are available only in a browser on this production computer.',
    vision_model_unavailable:'The local vision model could not run in this browser. Detection has stopped.',
    vision_camera_unavailable:'The tracking camera is offline. Open its existing studio feed before starting practice.',
    vision_frame_unavailable:'No existing frame is available. Detection has stopped; check the tracking camera.',
    vision_tracking_lost:'Tracking was lost. Check the camera and start practice again.',
    vision_session_expired:'The session ended or another control took over. Start practice again.',
    vision_manual_override:'Manual controls took over. Start practice again when ready.',
    vision_hold_direction:'Hold your head still toward that camera for two seconds, then save again.',
    vision_directions_too_close:'Those directions are too similar. Move the camera positions farther apart and calibrate again.',
    vision_two_directions_required:'Assign at least two head directions before practicing.',
    vision_calibration_required:'Save a distinct head direction for every assigned camera first.',
    vision_fresh_tracking_required:'Wait for clear, current tracking before allowing Program changes.',
    vision_invalid_bindings:'Assign at least one gesture, or two head directions.',
    vision_return_to_practice:'Return to practice before changing calibration.',
    vision_waiting_for_new_frame:'Waiting for a fresh camera frame…',
    calibration_required:'Calibrate each assigned camera direction below.'
  };
  function binding(value, transition) {
    if (value.startsWith('camera:')) return {action_id:'program.take',params:{preview_slot:Number(value.slice(7)),transition,duration_ms:transition === 'cut' ? 0 : 500}};
    if (value.startsWith('scene:')) return {action_id:'scene.take',params:{scene_id:value.slice(6)}};
    return null;
  }
  function mount(parent) {
    if (!parent || document.getElementById('productionVision')) return null;
    const section = document.createElement('section'); section.id='productionVision'; section.className='pv-tools';
    section.innerHTML = `<div class="pv-heading"><div><h3>Gesture &amp; head direction</h3><p class="pv-muted">Hands-free camera and scene changes, with a practice space first.</p></div><span class="pv-badge">EXPERIMENTAL</span></div>
      <div class="pv-columns"><div><div class="pv-fields"><label>Control with<select data-field="mode"><option value="hands">Hand gestures</option><option value="head">Head direction</option></select></label><label>Fixed tracking camera<select data-field="camera">${[1,2,3,4].map(n=>`<option value="${n}">Camera ${n}</option>`).join('')}</select></label><label>Camera transition<select data-field="transition"><option value="fade">Fade · 500 ms</option><option value="cut">Cut</option></select></label></div><div class="pv-bindings"></div><div class="pv-calibration"></div><div class="pv-actions"><button class="pv-start" data-action="start" disabled>Start practice</button><button data-action="arm" disabled>Allow Program changes</button><button data-action="stop" disabled>Stop</button><button data-action="refresh">Refresh availability</button></div></div>
      <div class="pv-preview"><canvas width="640" height="360" aria-label="Tracking camera preview"></canvas><div class="pv-status" role="status" aria-live="polite">Checking local vision availability…</div></div></div><p class="pv-muted pv-note">Head direction is not eye tracking. Calibration lasts only for this session. Keep one person in view. Gestures need a short hold and release; manual controls always take over. Frames stay on this computer. Switching tabs stops detection.</p>`;
    parent.appendChild(section);
    const field = name => section.querySelector(`[data-field="${name}"]`);
    const button = name => section.querySelector(`[data-action="${name}"]`);
    const status = section.querySelector('.pv-status'), canvas=section.querySelector('canvas');
    let nonce='', worker=null, serial=0, epoch=0, pending=new Map(), active=false, live=false, busy=false, scenes=[], available=false;
    let selections={}, calibrations=[], lastObservation=null, cameraAvailability={};
    const say = text => {status.textContent=text;};
    const describe = reason => messages[reason] || 'Vision paused. Check the tracking camera and start practice again.';
    function controls() {
      button('start').disabled=active||busy||!available||cameraAvailability[field('camera').value]!==true;
      button('refresh').disabled=active||busy;
      button('arm').disabled=!active||busy;
      button('stop').disabled=!active&&!busy;
      button('arm').textContent=live?'Return to practice':'Allow Program changes';
      section.querySelectorAll('select').forEach(el=>{el.disabled=active||busy;});
      section.querySelectorAll('[data-calibrate]').forEach(el=>{el.disabled=!active||live||busy;});
    }
    async function request(path, data, token=nonce) {
      const response=await fetch('/api/production/vision'+path,{method:data===undefined?'GET':'POST',cache:'no-store',credentials:'same-origin',
        headers:{...(data===undefined?{}:{'Content-Type':'application/json'}),...(token?{'X-Studio-Vision-Session':token}:{})},
        body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(5000)});
      const payload=await response.json();
      if (!response.ok) throw new Error(payload.reason||'vision_unavailable');
      return payload;
    }
    function drawBindings() {
      const area=section.querySelector('.pv-bindings'); area.replaceChildren();
      const keys=Object.keys(labels).filter(key=>field('mode').value==='head'?key.startsWith('look_'):!key.startsWith('look_'));
      keys.forEach((key,index)=>{
        const row=document.createElement('label'); row.className='pv-binding';
        const name=document.createElement('span');name.textContent=labels[key];row.appendChild(name);
        const select=document.createElement('select');select.dataset.binding=key; select.setAttribute('aria-label',labels[key]+' action');
        const add=(value,text)=>{const option=document.createElement('option');option.value=value;option.textContent=text;select.appendChild(option);};
        add('','Unassigned');[1,2,3,4].forEach(n=>add('camera:'+n,'Switch to camera '+n));
        scenes.forEach(s=>{if(typeof s.id==='string'&&typeof s.name==='string') add('scene:'+s.id,'Scene · '+s.name.slice(0,60));});
        select.value=selections[key]===undefined?'camera:'+(index+1):selections[key];
        select.onchange=()=>{selections[key]=select.value;drawCalibration();};row.appendChild(select);area.appendChild(row);
      });drawCalibration();controls();
    }
    function drawCalibration() {
      const area=section.querySelector('.pv-calibration');area.replaceChildren();
      if(field('mode').value!=='head')return;
      section.querySelectorAll('[data-binding]').forEach(select=>{
        if(!select.value)return;
        const key=select.dataset.binding,n=Number(key.slice(-1)),b=document.createElement('button');
        b.dataset.calibrate=String(n);b.textContent=(calibrations.includes(key)?'✓ Saved · ':'Save direction · ')+'camera '+n;
        b.title='Look toward camera '+n+', hold still, then save.';
        b.onclick=async()=>{const version=epoch;try {const r=await request('/calibrate',{target_slot:n});if(version!==epoch)return;calibrations=r.calibrated;drawCalibration();say(r.ready?'All directions saved. Practice looking toward each camera before allowing Program changes.':'Direction saved. Continue with the other assigned cameras.');}catch(e){if(version===epoch)say(describe(e.message));}};
        area.appendChild(b);
      });controls();
    }
    function talk(type, payload={}, transfer=[]) {
      return new Promise((resolve,reject)=>{
        const id=++serial,timer=setTimeout(()=>{pending.delete(id);reject(new Error('vision_model_unavailable'));},type==='init'?45000:3000);
        pending.set(id,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});
        worker.postMessage({id,type,...payload},transfer);
      });
    }
    function stop(message='Detection stopped. Start practice when ready.') {
      const old=nonce;epoch++;active=false;busy=false;live=false;nonce='';calibrations=[];
      if(worker)worker.terminate();worker=null;
      pending.forEach(item=>item.reject(new Error('vision_stopped')));pending.clear();
      if(old)fetch('/api/production/vision/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Vision-Session':old},body:'{}',keepalive:true}).catch(()=>{});
      canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);drawCalibration();controls();say(message);
    }
    async function loop(version) {
      while(active&&version===epoch&&!document.hidden&&section.isConnected) {
        try {
          const response=await fetch('/api/production/vision/frame/'+field('camera').value,{cache:'no-store',headers:{'X-Studio-Vision-Session':nonce},signal:AbortSignal.timeout(3000)});
          if(!response.ok){const r=await response.json();if(r.reason==='vision_waiting_for_new_frame'){say(describe(r.reason));await new Promise(r=>setTimeout(r,180));continue;}throw new Error(r.reason);}
          const bitmap=await createImageBitmap(await response.blob(),{resizeWidth:640,resizeQuality:'low'});
          if(!active||version!==epoch){bitmap.close();break;}
          canvas.height=Math.round(640*bitmap.height/bitmap.width);canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
          const result=await talk('infer',{image:bitmap},[bitmap]);
          if(!active||version!==epoch)break;
          lastObservation=result.observation;
          const outcome=await request('/observe',{frame_id:response.headers.get('X-Vision-Frame'),...lastObservation});
          if(!active||version!==epoch)break;
          if(outcome.stopped)throw new Error(outcome.reason);
          if(outcome.state==='practice_match')say('Practice match: '+labels[outcome.label]+'. Program did not change.');
          else if(outcome.state==='action_result')say(outcome.outcome?.ok?'Assigned production action completed.':'The assigned production action was blocked or is still pending. Use manual controls to check.');
          else if(field('mode').value==='head'&&!calibrations.length)say(lastObservation.face_count===1?'Look toward a camera, hold still for two seconds, then save its direction.':'Keep one person clearly in view.');
          else if(outcome.reason==='tracking_not_confident')say(field('mode').value==='hands'&&lastObservation.hand_count===1&&labels[lastObservation.gesture]
            ?labels[lastObservation.gesture]+' · '+Math.round(lastObservation.gesture_score*100)+'% confidence. Hold clearly; 90% is needed for an action.'
            :'Unclear tracking or more than one person/hand. No action taken.');
          else if(outcome.state==='candidate')say((live?'Armed · ':'Practice · ')+labels[outcome.label]+' — hold briefly…');
          else if(outcome.state==='neutral')say(live?'Armed. Waiting for an assigned gesture or direction.':'Practice active. Program changes are off.');
        }catch(error){if(version===epoch)stop(describe(error.message));break;}
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      if(active&&version===epoch)stop('Detection stopped because the studio is hidden or disconnected.');
    }
    button('start').onclick=async()=>{
      busy=true;const version=++epoch;controls();say('Loading the local model. Your camera is not being opened by this tool.');
      try {
        worker=new Worker('/static/production_vision_worker.js');
        worker.onmessage=({data})=>{const p=pending.get(data.id);if(!p)return;pending.delete(data.id);data.ok?p.resolve(data):p.reject(new Error(data.reason));};
        worker.onerror=()=>stop(describe('vision_model_unavailable'));
        await talk('init',{mode:field('mode').value});if(version!==epoch)return;
        const bindings={};section.querySelectorAll('[data-binding]').forEach(el=>{const action=binding(el.value,field('transition').value);if(action)bindings[el.dataset.binding]=action;});
        const state=await request('/session',{mode:field('mode').value,tracking_camera:Number(field('camera').value),bindings});
        if(version!==epoch){await request('/stop',{},state.nonce);return;}
        nonce=state.nonce;active=true;busy=false;live=false;controls();say('Practice active. Program changes are off.');loop(version);
      }catch(e){if(version===epoch)stop(describe(e.message));}
    };
    button('arm').onclick=async()=>{const version=epoch;busy=true;controls();try{await request('/arm',{practice:live});if(version!==epoch)return;live=!live;say(live?'Armed. Assigned gestures can now change Program.':'Practice active. Program changes are off.');}catch(e){if(version===epoch)say(describe(e.message));}finally{if(version===epoch){busy=false;controls();}}};
    button('stop').onclick=()=>stop();field('mode').onchange=()=>drawBindings();
    const availabilityMessage=()=>say(!available?describe('vision_assets_unavailable'):cameraAvailability[field('camera').value]===true?'Ready for practice. No detection is running.':describe('vision_camera_unavailable'));
    field('camera').onchange=()=>{controls();availabilityMessage();};
    document.addEventListener('visibilitychange',()=>{if(document.hidden&&(active||busy))stop('Detection stopped when you switched tabs.');});
    window.addEventListener('pagehide',()=>stop());
    const refresh=()=>request('').then(state=>{if(active||busy)return;available=state.enabled&&state.assets_ready;cameraAvailability=state.camera_ready||{};Array.from(field('camera').options).forEach(option=>{option.textContent='Camera '+option.value+(cameraAvailability[option.value]?' · Ready':' · Offline');});availabilityMessage();controls();}).catch(e=>say(describe(e.message)));
    button('refresh').onclick=refresh;refresh();
    fetch('/api/production/scenes',{cache:'no-store'}).then(r=>r.ok?r.json():{}).then(data=>{if(!active&&!busy){scenes=Array.isArray(data.scenes)?data.scenes:[];drawBindings();}}).catch(()=>{});
    drawBindings();return {element:section,stop};
  }
  if(typeof module!=='undefined')module.exports={binding,labels};
  if(root)root.ProducerVisionControls={mount};
})(typeof window!=='undefined'?window:null);
