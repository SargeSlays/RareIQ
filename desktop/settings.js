'use strict';
const form=document.querySelector('#destinationForm'),status=document.querySelector('#status'),list=document.querySelector('#destinations');
const dashboards={twitch:'https://dashboard.twitch.tv/settings/stream',youtube:'https://studio.youtube.com/',kick:'https://dashboard.kick.com/'};
let locked=false,storageAvailable=false,pending=null,broadcastState=null,broadcastBusy=false,startPending=false,stopBusy=false,broadcastOperation=0,pollPending=false;
function busy(value){locked=value;renderBroadcast();}
function platform(){const twitch=form.elements.platform.value==='twitch';document.querySelector('#serverLabel').hidden=twitch;form.elements.serverUrl.required=!twitch;document.querySelector('#platformDashboard').hidden=!dashboards[form.elements.platform.value];}
async function refresh(){const operation=broadcastOperation,state=await producerSettings.status();if(operation===broadcastOperation)broadcastState=state.broadcast;storageAvailable=state.secureStorageAvailable===true;list.replaceChildren();for(const item of state.destinations||[]){const row=document.createElement('article');row.className='destination';const copy=document.createElement('div'),title=document.createElement('strong'),note=document.createElement('p'),remove=document.createElement('button');title.textContent=item.name;note.textContent=String(item.platform).toUpperCase()+' · '+(item.configured?'Configured · broadcast not verified':'Stream key required');copy.append(title,note);remove.textContent='Remove';remove.type='button';remove.dataset.removeDestinationId=item.id;remove.setAttribute('aria-label','Remove '+item.name);remove.addEventListener('click',async()=>{if(locked||broadcastBusy||startPending||stopBusy||(broadcastState?.active&&broadcastState.destinationId===item.id))return;busy(true);try{await producerSettings.remove(item.id);await refresh();status.textContent='Destination removed.';}catch(_){status.textContent='The destination could not be removed. Retry.';}finally{busy(false);}});const controls=document.createElement('div'),start=document.createElement('button');start.type='button';start.className='primary';start.textContent='Start broadcast';start.dataset.destinationId=item.id;start.dataset.configured=String(item.configured===true);start.disabled=!item.configured||!broadcastState?.ready||broadcastState?.active;start.addEventListener('click',()=>startBroadcast(item.id));controls.append(start,remove);row.append(copy,controls);list.append(row);}if(!state.destinations?.length){const empty=document.createElement('p');empty.textContent='No destination saved yet. Add one below.';list.append(empty);}renderBroadcast();platform();if(!storageAvailable)status.textContent='Windows protected storage is unavailable. Stream keys cannot be saved.';return state;}
form.elements.platform.addEventListener('change',platform);
form.addEventListener('submit',async event=>{event.preventDefault();if(locked||!storageAvailable||broadcastBusy||startPending||stopBusy)return;busy(true);status.textContent='Saving destination…';const payload={name:form.elements.name.value.trim(),platform:form.elements.platform.value,streamKey:form.elements.streamKey.value};if(payload.platform!=='twitch')payload.serverUrl=form.elements.serverUrl.value.trim();const signature=JSON.stringify(payload);if(!pending||pending.signature!==signature)pending={signature,id:crypto.randomUUID()};payload.requestId=pending.id;let saved=false;try{await producerSettings.save(payload);saved=true;pending=null;form.reset();await refresh();status.textContent='Destination saved securely. Encoder transmission and platform receipt have not been verified.';}catch(_){status.textContent=saved?'Destination saved securely, but the list could not refresh. Reopen setup.':'Save could not be confirmed. Your draft is kept; check the list, then retry the same details.';}finally{busy(false);}});
document.querySelector('#platformDashboard').addEventListener('click',()=>{const url=dashboards[form.elements.platform.value];if(url)producerSettings.openPlatform(url);});document.querySelector('#closeSettings').addEventListener('click',()=>window.close());
refresh().then(()=>{if(storageAvailable)status.textContent='Stream keys stay protected on this Windows account.';}).catch(()=>{status.textContent='Protected destination storage could not be loaded. Close setup and retry.';busy(true);});

const themeToggle=document.querySelector("#themeToggle");function setSkin(value){const skin=value==="daylight"?"daylight":"ignite";document.documentElement.dataset.operatorSkin=skin;themeToggle.textContent=skin==="daylight"?"Dark theme":"Light theme";try{localStorage.setItem("producer-settings-skin",skin);}catch(_){}}let savedSkin;try{savedSkin=localStorage.getItem("producer-settings-skin");}catch(_){}setSkin(savedSkin||"ignite");themeToggle.addEventListener("click",()=>setSkin(document.documentElement.dataset.operatorSkin==="daylight"?"ignite":"daylight"));

function renderBroadcast(){
  const value=broadcastState||{},summary=document.querySelector('#broadcastSummary'),prepare=document.querySelector('#prepareOutput'),stop=document.querySelector('#stopBroadcast'),format=document.querySelector('#outputFormat');
  const reasons={desktop_mode_required:'The running studio was started in browser mode. Close its sessions and restart it from the desktop app.',encoder_failed:'Transmission stopped because the encoder failed. Check the connection and output, then retry.',prepare_output:'Prepare the clean output, then check the Program picture.',close_browser_review:'Close browser review in the output window before starting.',output_not_ready:'Check the Program source and wait for the clean output to finish loading.',desktop_backend_required:'Restart the desktop app to initialize broadcasting.',studio_unavailable:'The studio is unavailable. Reopen the desktop app and retry.',output_generation_changed:'Program changed during setup. Check the output and try again.',broadcast_start_failed:'Broadcast could not start. Check the destination key and connection.',output_lost:'The output was lost and transmission stopped. Fix the source and retry.',encoder_backpressure:'The encoder could not keep up. Stop, choose HD, and retry.',studio_status_unconfirmed:'Transmission stopped; the studio status update is pending. Check the output before retrying.',another_broadcast_active:'Another desktop broadcast is active. Stop it before starting a second one.',encoder_stop_unconfirmed:'Encoder shutdown is unconfirmed. Keep the studio open and try Stop again.'};
  summary.textContent=value.phase==='failed'?(reasons[value.reason]||(value.active?'Transmission shutdown is not confirmed. Keep the studio open and try Stop again.':'Transmission stopped unexpectedly. Check the output and connection, then retry.')):value.phase==='sending'?'Sending picture and audio · platform receipt unverified':value.active?'Broadcast '+value.phase+'…':value.ready?'Ready to send. Choose Start broadcast for a destination.':reasons[value.reason]||'Choose a working Program source, then prepare and review the clean output.';
  if(value.available===false&&value.phase!=='failed')summary.textContent='Broadcasting needs the managed desktop runtime. Open this studio from the installed desktop app.';
  const working=broadcastBusy||startPending||stopBusy;
  for(const element of form.elements)element.disabled=locked||!storageAvailable||working;
  prepare.disabled=locked||working||value.active||value.available===false;format.disabled=locked||working||value.active;stop.hidden=!value.active&&!startPending&&!stopBusy;stop.disabled=broadcastBusy||stopBusy||value.phase==='stopping';stop.textContent=startPending?'Cancel start':'Stop broadcast';
  for(const button of document.querySelectorAll('[data-destination-id]')){button.disabled=locked||working||!storageAvailable||button.dataset.configured!=='true'||!value.ready||value.active||value.format!==format.value;button.title=button.disabled?'Prepare a ready output before starting.':'A confirmation appears before anything is sent.';}
  if(value.phase!=='failed'&&value.prepared&&!value.active&&value.format!==format.value)summary.textContent='Output format changed. Choose Prepare output to apply it.';
  for(const button of document.querySelectorAll('[data-remove-destination-id]'))button.disabled=locked||working||(value.active&&value.destinationId===button.dataset.removeDestinationId);
  document.querySelector('#broadcastDetails').textContent=(value.codec==='h264_nvenc'?'NVIDIA H.264':value.codec==='libx264'?'Software H.264':'Encoder selected when starting')+' · '+Number(value.frames||0)+' frames · '+Math.round(Number(value.audioSamples||0)/48000)+' seconds of audio. Platform-live verification: not confirmed.';
}
async function startBroadcast(destinationId){
  if(locked||broadcastBusy||startPending||stopBusy||broadcastState?.active||!broadcastState?.ready)return;
  const operation=++broadcastOperation;startPending=true;renderBroadcast();
  try{
    const value=await producerSettings.startBroadcast({destinationId,format:document.querySelector('#outputFormat').value});
    if(operation===broadcastOperation){broadcastState=value;status.textContent=value.active?'Broadcast request completed. Check the sending status and your platform dashboard.':'Broadcast was not started.';}
  }catch(_){if(operation===broadcastOperation)status.textContent='Broadcast could not start. Check Program, its output review, destination settings and connection, then retry.';}
  finally{if(operation===broadcastOperation)++broadcastOperation;startPending=false;renderBroadcast();}
}
document.querySelector('#prepareOutput').addEventListener('click',async()=>{
  if(locked||broadcastBusy||startPending||stopBusy||broadcastState?.active)return;
  const operation=++broadcastOperation;broadcastBusy=true;renderBroadcast();
  try{const value=await producerSettings.prepareOutput({format:document.querySelector('#outputFormat').value});if(operation===broadcastOperation){broadcastState=value;status.textContent='Output opened. Review its picture and browser sources, then return here.';}}
  catch(_){if(operation===broadcastOperation)status.textContent='Output could not be prepared. Check the studio, then retry.';}
  finally{if(operation===broadcastOperation)++broadcastOperation;broadcastBusy=false;renderBroadcast();}
});
document.querySelector('#stopBroadcast').addEventListener('click',async()=>{
  if(broadcastBusy||stopBusy)return;
  const operation=++broadcastOperation;stopBusy=true;renderBroadcast();
  try{const value=await producerSettings.stopBroadcast();if(operation===broadcastOperation){broadcastState=value;status.textContent=value.active?'Shutdown is not confirmed. Keep the studio open and retry.':'Transmission stopped.';}}
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
