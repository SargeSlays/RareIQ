/* Native capabilities are optional; ordinary browser behavior remains unchanged. */
(function(host){
  'use strict';
  function openSources(document=host.document,navigation=host){
    const workspace=document?.querySelector('.workspace[data-workspace="broadcast"]'),panel=workspace?.querySelector('.production-greenroom'),docks=workspace?._studioDocks;
    if(!panel||typeof docks?.showTool!=='function'||typeof navigation.switchWorkspace!=='function')return false;
    if(navigation.switchWorkspace('broadcast')!==true||docks.showTool('production-greenroom')!==true)return false;
    if(!workspace.classList.contains('active')||!panel.isConnected||panel.hidden||!panel.getClientRects().length)return false;
    panel.scrollIntoView({block:'start',behavior:'auto'});
    const addImage=panel.querySelector?.('[data-image-import]');
    if(addImage&&!addImage.disabled){addImage.scrollIntoView({block:'center',behavior:'auto'});addImage.focus({preventScroll:true});}
    return true;
  }
  function install(document=host.document,bridge=host.producerDesktop){
    if(!document||typeof bridge?.openBroadcastSettings!=='function')return false;
    host.ProducerDesktopNavigation=Object.freeze({openSources:()=>openSources(document)});
    const selector='[data-studio-open="broadcast"][data-studio-view="setup"]';
    const click=event=>{if(!event.target?.closest?.(selector))return;event.preventDefault();event.stopImmediatePropagation();Promise.resolve(bridge.openBroadcastSettings()).catch(()=>{const button=document.querySelector(selector);if(button)button.title='Broadcast setup could not open. Use the desktop app menu to retry.';});};
    document.addEventListener('click',click,true);
    const button=document.querySelector(selector);if(button){button.textContent='Broadcast setup';button.title='Set up a protected desktop broadcast destination.';}
    if(button?.parentNode&&typeof document.createElement==='function'&&typeof bridge.openRecordingSettings==='function'&&!document.querySelector('[data-desktop-recording]')){
      const record=document.createElement('button');record.type='button';record.className=button.className;record.dataset.desktopRecording='';record.textContent='Record Program';record.title='Open local recording controls. Choose a file and confirm before recording starts.';
      record.addEventListener('click',()=>Promise.resolve(bridge.openRecordingSettings()).catch(()=>{record.title='Recording controls could not open. Use the desktop app menu to retry.';}));button.parentNode.insertBefore(record,button.nextSibling);
    }
    if(typeof bridge.info==='function'&&typeof bridge.broadcastStatus==='function')Promise.resolve(bridge.info()).then(info=>{
      if(info.engine!=='standalone')return;document.body.dataset.desktopEngine='standalone';
      const parent=document.querySelector('#showPreflight');if(!parent)return;
      const native=document.createElement('div');native.className='native-broadcast-readiness';
      native.innerHTML='<h3>Broadcast readiness</h3><p data-native-summary>Prepare the clean output in Broadcast setup.</p><strong data-native-verdict>PREPARE OUTPUT</strong><p>Broadcast directly from Producer, Please. OBS is not required.</p><button type="button" class="riq-button">Broadcast setup</button><small>Platform receipt is confirmed separately on your platform dashboard.</small>';
      if(info.preview===true){const notice=document.createElement('aside');notice.className='native-preview-notice';notice.textContent='Standalone preview · This studio uses separate settings and media. Your existing studio stays unchanged.';native.prepend(notice);}
      native.querySelector('button').addEventListener('click',()=>bridge.openBroadcastSettings());parent.append(native);
      let stopped=false,pending=false;
      const refresh=async()=>{if(stopped||pending)return;pending=true;try{const state=await bridge.broadcastStatus();if(stopped)return;native.querySelector('[data-native-verdict]').textContent=state.phase==='sending'?'SENDING':state.active?'WORKING':state.ready?'READY TO SEND':'PREPARE OUTPUT';native.querySelector('[data-native-summary]').textContent=state.phase==='sending'?'Your Program picture and public audio are being sent. Check your platform for receipt.':state.ready?'Your clean output is ready. Choose a destination in Broadcast setup.':'Choose your Program sources, then prepare and review the clean output.';}catch(_){if(!stopped)native.querySelector('[data-native-summary]').textContent='Desktop broadcast status is unavailable. Open Broadcast setup to retry.';}finally{pending=false;}};
      const timer=host.setInterval(refresh,1000);refresh();host.addEventListener('pagehide',()=>{stopped=true;host.clearInterval(timer);},{once:true});
    }).catch(()=>{});
    return true;
  }
  if(typeof module==='object'&&module.exports)module.exports={install,openSources};
  if(host.document){if(host.document.readyState==='loading')host.document.addEventListener('DOMContentLoaded',()=>install(),{once:true});else install();}
})(typeof window==='undefined'?globalThis:window);
