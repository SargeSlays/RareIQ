'use strict';
const form=document.querySelector('#destinationForm'),status=document.querySelector('#status'),list=document.querySelector('#destinations');
const dashboards={twitch:'https://dashboard.twitch.tv/settings/stream',youtube:'https://studio.youtube.com/',kick:'https://dashboard.kick.com/'};
let locked=false,storageAvailable=false,pending=null,broadcastState=null,broadcastBusy=false,startPending=false,stopBusy=false,broadcastOperation=0,pollPending=false,configuredDestinations=0,viewBusy=false,editing=null,addDraft=null;
function busy(value){locked=value;renderBroadcast();}
function destinationBusy(){return locked||broadcastBusy||startPending||stopBusy||broadcastState?.active||broadcastState?.ownershipPending;}
function platform(){const twitch=form.elements.platform.value==='twitch';document.querySelector('#serverLabel').hidden=twitch;form.elements.serverUrl.required=!twitch&&!editing;form.elements.streamKey.required=!editing||editing.keyConfigured!==true;document.querySelector('#platformDashboard').hidden=!dashboards[form.elements.platform.value];}
function draft(){return Object.fromEntries(['name','platform','serverUrl','streamKey'].map(key=>[key,form.elements[key].value]));}
function setDraft(value){for(const key of ['name','platform','serverUrl','streamKey'])form.elements[key].value=value?.[key]??(key==='platform'?'twitch':'');}
function renderEditor(){document.querySelector('#destinationFormTitle').textContent=editing?'Edit destination':'Add a destination';document.querySelector('#destinationFormHint').textContent=editing?'Update this destination without revealing its saved key or server address. To use another platform, add a separate destination.':'Your server address and stream key stay protected on this Windows account.';document.querySelector('#saveDestination').textContent=editing?'Save changes':'Save destination';document.querySelector('#cancelEdit').hidden=!editing;document.querySelector('#serverHint').textContent=editing?'Leave blank to keep the saved server. Changing it also requires a replacement stream key.':'Copy the secure RTMPS server address from your platform’s streaming dashboard.';document.querySelector('#keyHint').textContent=editing&&editing.keyConfigured?'Leave blank to keep the saved key. The app never displays it.':'Stored with Windows account encryption. The app never displays a saved key.';platform();renderBroadcast();}
function endEdit(){editing=null;pending=addDraft?.pending??null;setDraft(addDraft?.fields);addDraft=null;renderEditor();}
function beginEdit(item){if(destinationBusy()||editing)return;addDraft={fields:draft(),pending};editing={id:item.id,platform:item.platform,keyConfigured:item.keyConfigured===true};pending=null;setDraft({name:item.name,platform:item.platform});renderEditor();form.scrollIntoView({block:'start',behavior:'instant'});form.elements.name.focus();status.textContent='Editing '+item.name+'. Saving changes does not start a broadcast.';}
async function refresh(){
  const operation=broadcastOperation,state=await producerSettings.status();if(operation===broadcastOperation)broadcastState=state.broadcast;storageAvailable=state.secureStorageAvailable===true;configuredDestinations=(state.destinations||[]).filter(item=>item.configured===true).length;list.replaceChildren();
  for(const item of state.destinations||[]){
    const row=document.createElement('article');row.className='destination';const copy=document.createElement('div'),title=document.createElement('strong'),note=document.createElement('p'),remove=document.createElement('button');title.textContent=item.name;note.textContent=String(item.platform).toUpperCase()+' · '+(item.configured?'Configured · broadcast not verified':'Stream key required');copy.append(title,note);remove.textContent='Remove';remove.type='button';remove.dataset.removeDestinationId=item.id;remove.setAttribute('aria-label','Remove '+item.name);
    remove.addEventListener('click',async()=>{if(destinationBusy()||editing)return;busy(true);try{await producerSettings.remove(item.id);await refresh();status.textContent='Destination removed.';}catch(_){status.textContent='The destination could not be removed. Confirm Stop if needed, then retry.';}finally{busy(false);}});
    const controls=document.createElement('div'),start=document.createElement('button'),edit=document.createElement('button');controls.className='destination-actions';start.type='button';start.className='primary';start.textContent='Start broadcast';start.dataset.destinationId=item.id;start.dataset.configured=String(item.configured===true);start.addEventListener('click',()=>startBroadcast(item.id));edit.type='button';edit.textContent='Edit';edit.dataset.editDestinationId=item.id;edit.setAttribute('aria-label','Edit '+item.name);edit.addEventListener('click',()=>beginEdit(item));controls.append(start,edit,remove);row.append(copy,controls);list.append(row);
  }
  if(!state.destinations?.length){const empty=document.createElement('p');empty.textContent='No destination saved yet. Add one below.';list.append(empty);}renderBroadcast();platform();if(!storageAvailable)status.textContent='Windows protected storage is unavailable. Stream keys cannot be saved.';return state;
}
form.elements.platform.addEventListener('change',platform);
form.addEventListener('submit',async event=>{
  event.preventDefault();if(destinationBusy()||!storageAvailable)return;
  const payload={name:form.elements.name.value.trim(),platform:editing?.platform||form.elements.platform.value};
  const key=form.elements.streamKey.value,server=form.elements.serverUrl.value.trim();if(key)payload.streamKey=key;if(payload.platform!=='twitch'&&server)payload.serverUrl=server;if(editing)payload.id=editing.id;
  if(editing&&server&&!key){status.textContent='Enter a replacement stream key when changing the server address. Your draft is kept.';form.elements.streamKey.focus();return;}
  busy(true);status.textContent=editing?'Saving destination changes…':'Saving destination…';const signature=JSON.stringify(payload);if(!pending||pending.signature!==signature)pending={signature,id:crypto.randomUUID()};payload.requestId=pending.id;let saved=false;
  try{await producerSettings.save(payload);saved=true;pending=null;if(editing)endEdit();else{form.reset();setDraft();renderEditor();}await refresh();status.textContent='Destination saved securely. Encoder transmission and platform receipt have not been verified.';}
  catch(_){status.textContent=saved?'Destination saved securely, but the list could not refresh. Reopen setup.':'Save could not be confirmed. Your draft is kept; confirm Stop if needed, then retry the same details.';}
  finally{busy(false);}
});
document.querySelector('#cancelEdit').addEventListener('click',()=>{if(destinationBusy()||!editing)return;endEdit();status.textContent='Editing cancelled. Your Add destination draft is restored.';form.elements.name.focus();});
document.querySelector('#platformDashboard').addEventListener('click',()=>{const url=dashboards[form.elements.platform.value];if(url)producerSettings.openPlatform(url);});document.querySelector('#closeSettings').addEventListener('click',()=>window.close());
refresh().then(()=>{if(storageAvailable)status.textContent='Stream keys stay protected on this Windows account.';}).catch(()=>{status.textContent='Protected destination storage could not be loaded. Close setup and retry.';busy(true);});

const themeToggle=document.querySelector("#themeToggle");function setSkin(value){const skin=value==="daylight"?"daylight":"ignite";document.documentElement.dataset.operatorSkin=skin;themeToggle.textContent=skin==="daylight"?"Dark theme":"Light theme";try{localStorage.setItem("producer-settings-skin",skin);}catch(_){}}let savedSkin;try{savedSkin=localStorage.getItem("producer-settings-skin");}catch(_){}setSkin(savedSkin||"ignite");themeToggle.addEventListener("click",()=>setSkin(document.documentElement.dataset.operatorSkin==="daylight"?"ignite":"daylight"));

function renderBroadcast(){
  const value=broadcastState||{},summary=document.querySelector('#broadcastSummary'),prepare=document.querySelector('#prepareOutput'),stop=document.querySelector('#stopBroadcast'),format=document.querySelector('#outputFormat');
  const reasons={desktop_mode_required:'The running studio was started in browser mode. Close its sessions and restart it from the desktop app.',encoder_failed:'Transmission stopped because the encoder failed. Check the connection and output, then retry.',prepare_output:'Prepare the clean output, then check the Program picture.',close_browser_review:'Close browser review in the output window before starting.',output_not_ready:'Check the Program source and wait for the clean output to finish loading.',desktop_backend_required:'Restart the desktop app to initialize broadcasting.',studio_unavailable:'The studio is unavailable. Reopen the desktop app and retry.',output_generation_changed:'Program changed during setup. Check the output and try again.',broadcast_start_failed:'Broadcast could not start. Check the destination key and connection.',output_lost:'The output was lost and transmission stopped. Fix the source and retry.',encoder_backpressure:'The encoder could not keep up. Stop, choose HD, and retry.',studio_status_unconfirmed:'Transmission stopped; the studio status update is pending. Check the output before retrying.',another_broadcast_active:'Another desktop broadcast is active. Stop it before starting a second one.',encoder_stop_unconfirmed:'Encoder shutdown is unconfirmed. Keep the studio open and try Stop again.'};
  Object.assign(reasons,{destination_dns_failed:'The stream server address could not be found. Check the address and your connection.',tls_connection_failed:'The secure stream connection could not be opened. Check the connection and destination.',tls_verification_failed:'The secure stream connection could not be verified.',tls_trust_unavailable:'The secure connection trust settings are unavailable. Reopen the app and retry.',encoder_transport_interrupted:'The connection to the stream server was interrupted.',encoder_start_timeout:'The encoder did not become ready in time. Check the connection and output.',encoder_dependency_missing:'The encoder runtime is incomplete. Reopen or repair the desktop build.',video_encoder_unavailable:'The video encoder could not initialize. Reopen the app and retry.'});
  summary.textContent=value.phase==='failed'?(reasons[value.reason]||(value.active?'Transmission shutdown is not confirmed. Keep the studio open and try Stop again.':'Transmission stopped unexpectedly. Check the output and connection, then retry.')):value.phase==='sending'?(value.reason?'Waiting for output readiness. Transmission will stop if it cannot recover.':'Sending picture and audio · platform receipt unverified'):value.active?'Broadcast '+value.phase+'…':value.ready?'Ready to send. Choose Start broadcast for a destination.':reasons[value.reason]||'Choose a working Program source, then prepare and review the clean output.';
  if(value.available===false&&value.phase!=='failed')summary.textContent='Broadcasting needs the managed desktop runtime. Open this studio from the installed desktop app.';
  const working=broadcastBusy||startPending||stopBusy;
  const stopRequired=value.active||value.ownershipPending===true;
  const sending=value.phase==='sending',outputReady=(value.ready===true&&value.format===format.value)||sending;
  const programStep=document.querySelector('#programStep'),outputStep=document.querySelector('#outputStep'),destinationStep=document.querySelector('#destinationStep');
  programStep.textContent=outputReady?'Program checked':'Check Program';programStep.dataset.ready=String(outputReady);
  outputStep.textContent=sending?(value.reason?'Checking output':'Sending'):value.prepared&&value.format!==format.value?'Prepare new format':outputReady?'Ready':value.prepared?'Open · needs a check':'Not prepared';outputStep.dataset.ready=String(outputReady&&!value.reason);
  destinationStep.textContent=storageAvailable&&configuredDestinations>0?'Saved securely':'Not saved';destinationStep.dataset.ready=String(storageAvailable&&configuredDestinations>0);
  document.querySelector('#chooseSources').disabled=locked||working;document.querySelector('#addDestination').disabled=locked||working||stopRequired||Boolean(editing);
  for(const element of form.elements)element.disabled=locked||!storageAvailable||working||stopRequired;
  form.elements.platform.disabled=form.elements.platform.disabled||Boolean(editing);
  document.querySelector('#cancelEdit').disabled=destinationBusy();
  document.querySelector('#platformDashboard').disabled=locked||working;
  prepare.disabled=locked||working||stopRequired||value.available===false;format.disabled=locked||working||stopRequired;stop.hidden=!stopRequired&&!startPending&&!stopBusy;stop.disabled=broadcastBusy||stopBusy||value.phase==='stopping';stop.textContent=startPending?'Cancel start':'Stop broadcast';
  document.querySelector('#viewOutput').disabled=locked||broadcastBusy||stopBusy||viewBusy||!value.prepared;
  for(const button of document.querySelectorAll('[data-destination-id]')){button.disabled=locked||working||Boolean(editing)||!storageAvailable||button.dataset.configured!=='true'||!value.ready||stopRequired||value.format!==format.value;button.title=button.disabled?(editing?'Save or cancel editing before starting.':value.ownershipPending?'Confirm Stop before starting again.':'Prepare a ready output before starting.'):'A confirmation appears before anything is sent.';}
  if(value.phase!=='failed'&&value.prepared&&!value.active&&value.format!==format.value)summary.textContent='Output format changed. Choose Prepare output to apply it.';
  for(const selector of ['[data-remove-destination-id]','[data-edit-destination-id]'])for(const button of document.querySelectorAll(selector)){button.disabled=destinationBusy()||Boolean(editing)||!storageAvailable;button.title=!storageAvailable?'Windows protected storage is unavailable.':editing?'Save or cancel the current edit first.':locked||working?'Wait for the current action to finish.':stopRequired?'Confirm Stop before changing destinations.':'Edit or remove this saved destination.';}
  document.querySelector('#broadcastDetails').textContent=(!value.active&&value.frames>0?'Last attempt: ':'')+(value.codec==='h264_nvenc'?'NVIDIA H.264':value.codec==='libx264'?'Software H.264':'Encoder selected when starting')+' · '+Number(value.frames||0)+' frames · '+Math.round(Number(value.audioSamples||0)/48000)+' seconds of audio. Platform-live verification: not confirmed.';
  const recovery=document.querySelector('#recoveryPanel');recovery.hidden=value.phase!=='failed'&&!(value.ownershipPending&&!value.active);
  const network=['destination_dns_failed','tls_connection_failed','encoder_transport_interrupted','encoder_start_timeout'];
  document.querySelector('#recoveryInstructions').textContent=value.ownershipPending?'Stop confirmation is pending. Keep the studio open and choose Stop broadcast again before starting another attempt.':value.active?'Encoder shutdown is not confirmed. Keep the studio open and choose Stop broadcast again.':network.includes(value.reason)?'Check your internet connection and the destination details in your platform dashboard. View the clean output, then start again when it is ready.':['tls_verification_failed','tls_trust_unavailable'].includes(value.reason)?'The secure connection could not be verified. Check the secure server address, your computer’s date and time, and your connection before retrying.':value.reason==='encoder_backpressure'?'Choose HD landscape, prepare that output again, and check its picture and sound before retrying.':'Restore any unavailable sources, then choose Prepare output and check the picture and sound before starting again.';
}
async function startBroadcast(destinationId){
  if(locked||broadcastBusy||startPending||stopBusy||editing||broadcastState?.active||broadcastState?.ownershipPending||!broadcastState?.ready)return;
  const operation=++broadcastOperation;startPending=true;renderBroadcast();
  try{
    const value=await producerSettings.startBroadcast({destinationId,format:document.querySelector('#outputFormat').value});
    if(operation===broadcastOperation){broadcastState=value;status.textContent=value.active?'Broadcast request completed. Check the sending status and your platform dashboard.':'Broadcast was not started.';}
  }catch(_){if(operation===broadcastOperation)status.textContent='Broadcast could not start. Check Program, its output review, destination settings and connection, then retry.';}
  finally{if(operation===broadcastOperation)++broadcastOperation;startPending=false;renderBroadcast();}
}
document.querySelector('#prepareOutput').addEventListener('click',async()=>{
  if(locked||broadcastBusy||startPending||stopBusy||broadcastState?.active||broadcastState?.ownershipPending)return;
  const operation=++broadcastOperation;broadcastBusy=true;renderBroadcast();
  try{const value=await producerSettings.prepareOutput({format:document.querySelector('#outputFormat').value});if(operation===broadcastOperation){broadcastState=value;status.textContent='Output opened. Review its picture and browser sources, then return here.';}}
  catch(_){if(operation===broadcastOperation)status.textContent='Output could not be prepared. Check the studio, then retry.';}
  finally{if(operation===broadcastOperation)++broadcastOperation;broadcastBusy=false;renderBroadcast();}
});
document.querySelector('#stopBroadcast').addEventListener('click',async()=>{
  if(broadcastBusy||stopBusy)return;
  const operation=++broadcastOperation;stopBusy=true;renderBroadcast();
  try{const value=await producerSettings.stopBroadcast();if(operation===broadcastOperation){broadcastState=value;status.textContent=value.active||value.ownershipPending?'Shutdown is not confirmed. Keep the studio open and retry Stop.':'Transmission stopped.';}}
  catch(_){if(operation===broadcastOperation)status.textContent='Stop could not be confirmed. Keep the studio open and retry.';}
  finally{if(operation===broadcastOperation)++broadcastOperation;stopBusy=false;renderBroadcast();}
});
const broadcastTimer=setInterval(async()=>{
  if(broadcastBusy||stopBusy||pollPending)return;
  const operation=broadcastOperation;pollPending=true;
  try{const value=await producerSettings.broadcastStatus();if(operation===broadcastOperation){broadcastState=value;renderBroadcast();}}
  catch(_){}finally{pollPending=false;}
},1000);addEventListener('pagehide',()=>clearInterval(broadcastTimer),{once:true});

document.querySelector('#outputFormat').addEventListener('change',renderBroadcast);
document.querySelector('#viewOutput').addEventListener('click',async()=>{
  if(locked||broadcastBusy||stopBusy||viewBusy||!broadcastState?.prepared)return;viewBusy=true;renderBroadcast();
  try{await producerSettings.viewOutput();status.textContent='The existing clean output is open. Viewing it does not change Program or open browser review.';}
  catch(_){status.textContent='The output window is unavailable. Confirm Stop if needed, then choose Prepare output to open it again.';}
  finally{viewBusy=false;renderBroadcast();}
});
document.querySelector('#chooseSources').addEventListener('click',async()=>{
  if(locked||broadcastBusy||startPending||stopBusy)return;broadcastBusy=true;renderBroadcast();
  try{await producerSettings.openSources();status.textContent='Choose sources in the studio. Build Preview, then Take when you’re ready. Your destination draft is kept here.';}
  catch(_){status.textContent='The source library could not open. Keep the studio open and try Choose sources again.';}
  finally{broadcastBusy=false;renderBroadcast();}
});
document.querySelector('#addDestination').addEventListener('click',()=>{if(destinationBusy()||editing)return;form.scrollIntoView({block:'start',behavior:'instant'});form.elements.name.focus();});
