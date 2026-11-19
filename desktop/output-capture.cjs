'use strict';
const path = require('node:path');
const {loadInitialOutput}=require('./startup.cjs');
const {emptyMeters,cleanMeterHealth}=require('./audio-meters.cjs');
const { randomUUID } = require('node:crypto');
const {normalizeAudioRouting,normalizeSourceManifest}=require('./audio-routing.cjs');
const {createLocalMonitor}=require('./local-monitor.cjs');
const CHANNELS = Object.freeze({ health: 'producer:output:health', pcm: 'producer:output:pcm', sync: 'producer:output:sync', control: 'producer:output:control', ack: 'producer:output:ack',monitorPcm:'producer:output:monitor-pcm',monitorAck:'producer:output:monitor-ack' });
const SIZES = new Set(['1280x720', '1920x1080', '720x1280']);
const RATE = 48000, AUDIO_FRAMES = 480;
const SNAPSHOT = `(()=>{try{const f=document.querySelector('iframe.program');if(!f||f.contentWindow.location.origin!==location.origin||f.contentWindow.location.pathname!=='/program')return null;return f.contentWindow.ProducerProgramOutput?.snapshot()||null;}catch(_){return null;}})()`;
const rehearsalVisible=generation=>`(()=>{const root=document.documentElement,badge=document.querySelector('[data-rehearsal-badge].rehearsal-output-watermark');if(root.dataset.rehearsalMode!=='active'||root.dataset.rehearsalGeneration!==${JSON.stringify(generation)}||!badge||badge.hidden||badge.dataset.state!=='ready'||!badge.textContent.startsWith('REHEARSAL')||typeof badge.checkVisibility==='function'&&!badge.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}))return false;const style=getComputedStyle(badge),box=badge.getBoundingClientRect();return style.display!=='none'&&style.visibility==='visible'&&Number(style.opacity)>0&&box.width>0&&box.height>0&&box.bottom>0&&box.right>0&&box.top<innerHeight&&box.left<innerWidth;})()`;

function cleanSnapshot(value) {
  if (!value || typeof value !== 'object' || typeof value.peerId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.peerId)
      || !Number.isSafeInteger(value.generation) || value.generation < 0 || typeof value.rendered !== 'boolean'
      || typeof value.browserReviewOpen !== 'boolean' || typeof value.audioBlocked !== 'boolean') return null;
  const readySources = Array.isArray(value.readySources) ? value.readySources.filter(s => typeof s === 'string' && /^(camera:[1-4]|producer:screen:[a-f0-9]{32}|guest:[a-f0-9]{32}:(camera|screen|audio)|(image|video|text|browser):[a-f0-9-]{36})$/.test(s)).slice(0, 6) : [];
  const ids={};for(const key of ['programCompositionId','previewCompositionId']){
    if(value[key]!==undefined){if(typeof value[key]!=='string'||!/^[a-f0-9]{64}$/.test(value[key]))return null;ids[key]=value[key];}
  }
  return { peerId: value.peerId, generation: value.generation, rendered: value.rendered, browserReviewOpen: value.browserReviewOpen, reviewOpen: value.browserReviewOpen, audioBlocked: value.audioBlocked, readySources,...ids };
}
function createOutputCapture({ BrowserWindow, ipcMain, origin, baseDir = __dirname, width = 1280, height = 720, fps = 30, audioRouting = {}, requireVod = false, clockUs = () => Number(process.hrtime.bigint() / 1000n), routingTimeoutMs=1500,rehearsalTimeoutMs=6500,createMonitor=createLocalMonitor,partition = 'persist:producer-output', onError = () => {} } = {}) {
  if (!BrowserWindow || !ipcMain || !SIZES.has(width + 'x' + height) || ![30,60].includes(fps) || !path.isAbsolute(baseDir)||!Number.isInteger(routingTimeoutMs)||routingTimeoutMs<10||routingTimeoutMs>5000) throw Error('output_capture_configuration_invalid');
  audioRouting=normalizeAudioRouting(audioRouting);
  const trusted = new URL(origin); if (trusted.origin !== origin || !/^https?:$/.test(trusted.protocol)) throw Error('output_capture_origin_invalid');
  let window = null, windowClosing = false, preparing = null, closed = false, active = null, starting = false, captureVersion = 0, captureUi = null, latest = null, polling = null, snapshotPending = null;
  let snapshot = null, snapshotAt = 0, audioAt = 0, meterAt = 0, meters=emptyMeters(), audio = { ready: false, contextState: 'unavailable', sourceCount: 0, unavailableCount: 0 }, fault = null;
  let pendingRouting=null,routingGeneration=0,routingContext=randomUUID();const routingRecords=new Map();
  let pendingRehearsal=null,rehearsalReady=null;
  let localMonitor=null,monitorBus='off',monitorSupported=true,pendingMonitor=null,monitorVersion=0,monitorTail=null,monitorId=null,monitorSequence=-1,monitorBusy=false;
  const now = clockUs;
  const allowed = value => { try { const u = new URL(value); return u.origin === origin && u.pathname === '/output/studio' && !u.username && !u.password; } catch (_) { return false; } };
  function owned(event) { try { return window && !window.isDestroyed() && event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame && allowed(event.senderFrame.url) && allowed(window.webContents.getURL()); } catch (_) { return false; } }
  function report(code) { fault = code; try { onError(code); } catch (_) {} }
  const routingError=code=>Object.assign(Error(code),{code});
  function forceMonitorOff(){
    ++monitorVersion;monitorBus='off';monitorId=null;monitorSequence=-1;monitorBusy=false;localMonitor?.stop();const pending=pendingMonitor;pendingMonitor=null;if(pending){clearTimeout(pending.timer);pending.reject(routingError('rehearsal_monitor_cancelled'));}
    try{if(window&&!window.isDestroyed())window.webContents.send(CHANNELS.control,{type:'monitor',bus:'off',monitorNonce:randomUUID(),monitorContext:routingContext});}catch(_){}
  }
  function setMonitor(bus){
    if(!['off','live','vod'].includes(bus)||bus==='vod'&&!requireVod)return Promise.reject(routingError('rehearsal_monitor_unavailable'));
    if(bus==='off')forceMonitorOff();const version=monitorVersion,previous=monitorTail;
    const work=(async()=>{
      if(previous){try{await previous;}catch(_){} }
      if(bus==='off'&&(!window||window.isDestroyed()||closed||!audio.ready||audio.contextState!=='running'))return {ok:true,monitor:{bus:'off',available:false}};
      if(version!==monitorVersion||closed||windowClosing||!window||window.isDestroyed()||!allowed(window.webContents.getURL())||!audio.ready||audio.contextState!=='running')throw routingError('rehearsal_monitor_unavailable');
      const target=window,contents=target.webContents,frame=contents.mainFrame,context=routingContext,nonce=randomUUID();
      if(bus!=='off'){
        localMonitor=localMonitor||createMonitor({BrowserWindow,ipcMain,baseDir,timeoutMs:routingTimeoutMs});
        try{await localMonitor.prepare();}catch(_){monitorSupported=false;localMonitor.stop();throw routingError('rehearsal_monitor_unavailable');}
        if(version!==monitorVersion||target!==window||context!==routingContext){localMonitor.stop();throw routingError('rehearsal_monitor_cancelled');}
      }
      const result=await new Promise((resolve,reject)=>{const pending={target,contents,frame,context,nonce,bus,version,resolve,reject,timer:null};pendingMonitor=pending;pending.timer=setTimeout(()=>{if(pendingMonitor!==pending)return;pendingMonitor=null;monitorSupported=false;localMonitor?.stop();reject(routingError('rehearsal_monitor_unavailable'));},routingTimeoutMs);pending.timer.unref?.();try{contents.send(CHANNELS.control,{type:'monitor',bus,monitorNonce:nonce,monitorContext:context});}catch(_){clearTimeout(pending.timer);pendingMonitor=null;localMonitor?.stop();reject(routingError('rehearsal_monitor_unavailable'));}});
      if(version!==monitorVersion)throw routingError('rehearsal_monitor_cancelled');monitorBus=bus;monitorId=bus==='off'?null:nonce;monitorSequence=-1;if(bus!=='off')monitorSupported=true;return result;
    })();monitorTail=work;return work.finally(()=>{if(monitorTail===work)monitorTail=null;});
  }
  function cancelRehearsal(reason='output_rehearsal_cancelled'){const pending=pendingRehearsal;pendingRehearsal=null;rehearsalReady=null;if(pending){clearTimeout(pending.timer);pending.reject(routingError(reason));try{void pending.target.webContents.executeJavaScript(`(()=>{const root=document.documentElement;if(root.dataset.nativeRehearsalWait===${JSON.stringify(pending.owner)})delete root.dataset.nativeRehearsalWait;})()`,false).catch(()=>{});}catch(_){}}}
  function waitForRehearsal(generation){
    if(typeof generation!=='string'||!/^[a-f0-9]{32}$/.test(generation)||!Number.isInteger(rehearsalTimeoutMs)||rehearsalTimeoutMs<10||rehearsalTimeoutMs>10000)return Promise.reject(routingError('output_rehearsal_not_ready'));
    if(closed||windowClosing||!window||window.isDestroyed()||!allowed(window.webContents.getURL()))return Promise.reject(routingError('output_rehearsal_not_ready'));
    if(pendingRehearsal){if(pendingRehearsal.generation===generation)return pendingRehearsal.promise;cancelRehearsal();}
    const target=window,version=captureVersion,owner=randomUUID();let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const pending={target,generation,version,owner,promise,reject,timer:null};pendingRehearsal=pending;
    pending.timer=setTimeout(()=>{if(pendingRehearsal===pending)cancelRehearsal('output_rehearsal_not_ready');},rehearsalTimeoutMs);pending.timer.unref?.();
    const script=`(()=>{const root=document.documentElement;root.dataset.nativeRehearsalWait=${JSON.stringify(owner)};return new Promise(resolve=>{let timer,expiry,done=false;const finish=value=>{if(done)return;done=true;clearTimeout(timer);clearTimeout(expiry);if(root.dataset.nativeRehearsalWait===${JSON.stringify(owner)})delete root.dataset.nativeRehearsalWait;resolve(value);};const check=()=>{if(root.dataset.nativeRehearsalWait!==${JSON.stringify(owner)})return finish(false);if(${rehearsalVisible(generation)})return requestAnimationFrame(()=>requestAnimationFrame(()=>finish(${rehearsalVisible(generation)})));timer=setTimeout(check,25);};expiry=setTimeout(()=>finish(false),${rehearsalTimeoutMs});check();});})()`;
    Promise.resolve().then(()=>pendingRehearsal===pending?target.webContents.executeJavaScript(script,false):false).then(ready=>{if(pendingRehearsal!==pending)return;clearTimeout(pending.timer);pendingRehearsal=null;if(ready!==true||closed||version!==captureVersion||target!==window||target.isDestroyed())return reject(routingError('output_rehearsal_not_ready'));rehearsalReady={generation,target,version};resolve({ok:true,generation,visible:true});},()=>{if(pendingRehearsal===pending){clearTimeout(pending.timer);pendingRehearsal=null;reject(routingError('output_rehearsal_not_ready'));}});
    return promise;
  }
  function invalidateRouting(){
    routingGeneration++;routingRecords.clear();
    const pending=pendingRouting;pendingRouting=null;
    if(pending){clearTimeout(pending.timer);pending.reject(routingError('audio_routing_cancelled'));}
  }
  function updateAudioRouting(value){
    let normalized,signature;
    try{
      if(!value||typeof value!=='object'||Array.isArray(value)||!Object.hasOwn(value,'audioRouting')||Object.keys(value).some(key=>!['audioRouting','requestId'].includes(key))||typeof value.requestId!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId))throw routingError('invalid_audio_routing_request');
      normalized=normalizeAudioRouting(value.audioRouting);signature=JSON.stringify(normalized);
      if(closed||windowClosing||!window||window.isDestroyed()||!allowed(window.webContents.getURL())||!audio.ready||audio.contextState!=='running')throw routingError('audio_routing_unavailable');
      const known=routingRecords.get(value.requestId);
      if(known&&known.signature!==signature)throw routingError('audio_routing_conflict');
      if(pendingRouting){if(pendingRouting.id===value.requestId)return pendingRouting.promise;throw routingError('audio_routing_busy');}
      if(known?.result)return Promise.resolve({...known.result});
    }catch(error){return Promise.reject(error);}
    const id=value.requestId,target=window,contents=target.webContents,frame=contents.mainFrame,generation=routingGeneration,nonce=randomUUID();
    let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const pending={id,target,contents,frame,generation,nonce,routing:normalized,signature,promise,resolve,reject,timer:null};
    pendingRouting=pending;routingRecords.set(id,{signature});
    while(routingRecords.size>64)routingRecords.delete(routingRecords.keys().next().value);
    pending.timer=setTimeout(()=>{if(pendingRouting!==pending)return;pendingRouting=null;reject(routingError('audio_routing_timeout'));},routingTimeoutMs);pending.timer.unref?.();
    try{contents.send(CHANNELS.control,{type:'routing',audioRouting:normalized,requestId:id,routingNonce:nonce,routingContext});}
    catch(_){clearTimeout(pending.timer);if(pendingRouting===pending)pendingRouting=null;reject(routingError('audio_routing_unavailable'));}
    return promise;
  }
  function clearCaptureUi() {
    const ui = captureUi; captureUi = null;
    try {
      if (!ui || ui.target.isDestroyed() || !allowed(ui.target.webContents.getURL())) return Promise.resolve();
      // A late cleanup from an old run must not reveal controls in a newer run.
      const script = `(()=>{const root=document.documentElement;if(root.dataset.nativeCaptureOwner===${JSON.stringify(ui.owner)}){delete root.dataset.nativeCapture;delete root.dataset.nativeCaptureOwner;}})()`;
      return ui.target.webContents.executeJavaScript(script, false).catch(() => {});
    } catch (_) { return Promise.resolve(); }
  }
  function status() {
    const fresh = window && !window.isDestroyed() && snapshot && now() - snapshotAt < 2000000;
    return { prepared: Boolean(window && !window.isDestroyed() && audio.ready), capturing: Boolean(active), width, height, fps, pixelFormat: 'bgra', audioFormat: 'f32le', sampleRate: RATE, channels: 2,
      ...(fresh ? snapshot : { peerId: null, generation: null, rendered: false, browserReviewOpen: false, reviewOpen: false, audioBlocked: true, readySources: [] }),
      audioReady: audio.ready && now() - audioAt < 2000000 && audio.contextState === 'running' && audio.unavailableCount === 0, audioSources: audio.sourceCount,audioSourcesAvailable:audio.sources||[],audioMeters:window&&!window.isDestroyed()&&audio.ready&&audio.contextState==='running'&&!fault&&now()-meterAt<750000?meters:emptyMeters(),
      locallyMuted: Boolean(window && !window.isDestroyed() && window.webContents.isAudioMuted()), error: fault,
      monitor:{bus:monitorBus,available:monitorSupported&&Boolean(window&&!window.isDestroyed()&&audio.ready),vodAvailable:monitorSupported&&requireVod},
      capturedFrames: active?.frames || 0, droppedFrames: active?.droppedVideo || 0, audioPackets: active?.audioPackets || 0, droppedAudioPackets: (active?.droppedAudio || 0) + (active?.workletDropped || 0) };
  }
  function readSnapshot() {
    if (snapshotPending) return snapshotPending;
    if (!window || window.isDestroyed() || !allowed(window.webContents.getURL())) return Promise.resolve();
    const target = window;
    snapshotPending = (async () => { try {
      const value = await target.webContents.executeJavaScript(SNAPSHOT, false);
      if (target !== window || target.isDestroyed()) return;
      snapshot = cleanSnapshot(value); snapshotAt = now();
      if (active && snapshot?.browserReviewOpen) { stopCapture(); report('output_review_open'); }
      else if (active && (!snapshot || snapshot.peerId !== active.peerId)) { stopCapture(); report('output_receiver_changed'); }
    } catch (_) { snapshot = null; if (active) { stopCapture(); report('output_receiver_unavailable'); } }
    finally { snapshotPending = null; } })();
    return snapshotPending;
  }
  function storeFrame(image) {
    if (!image || image.isEmpty()) return;
    let frame = image; const size = image.getSize();
    if (size.width !== width || size.height !== height) {
      if (Math.abs(size.width / size.height - width / height) > 0.02) { latest = null; if (active) stopCapture(); report('output_capture_size_mismatch'); return; }
      frame = image.resize({ width, height, quality: 'good' });
    }
    const bytes = frame.toBitmap();
    if (bytes.length === width * height * 4) latest = bytes;
  }
  async function prepare() {
    if (closed) throw Error('output_capture_closed');
    if (preparing) return preparing;
    if (window && !window.isDestroyed()) { invalidateRouting();window.webContents.send(CHANNELS.control,{type:'routing',audioRouting,routingContext,monitorVodAllowed:requireVod});window.show(); return status(); }
    preparing = (async () => {
      invalidateRouting();routingContext=randomUUID();fault = null; audio.ready = false; windowClosing = false;
      window = new BrowserWindow({ width, height, useContentSize: true, resizable: false, maximizable: false, fullscreenable: false, show: true,
        title: 'Studio Output — Producer, Please', autoHideMenuBar: true, backgroundColor: '#000000',
        webPreferences: { preload: path.join(baseDir, 'output-preload.cjs'), additionalArguments: ['--producer-output-origin=' + origin], partition,
          sandbox: true, contextIsolation: true, nodeIntegration: false, nodeIntegrationInSubFrames: false, webSecurity: true,
          allowRunningInsecureContent: false, webviewTag: false, backgroundThrottling: false, autoplayPolicy: 'no-user-gesture-required' },
      });
      const target = window, contents = target.webContents;
      target.setMenu(null); contents.setAudioMuted(true);
      contents.setWindowOpenHandler(() => ({ action: 'deny' }));
      contents.session.setPermissionCheckHandler(() => false);
      contents.session.setPermissionRequestHandler((_c, _p, reply) => reply(false));
      contents.session.setDisplayMediaRequestHandler((_r, reply) => reply(null));
      contents.on('will-navigate', (event, url) => { if (!allowed(url)) event.preventDefault(); if (active) { stopCapture(); report('output_navigated'); } });
      contents.on('will-redirect', (event, url, _inPlace, main) => { if (main !== false && !allowed(url)) event.preventDefault(); });
      contents.on('will-attach-webview', event => event.preventDefault());
      contents.on('did-start-navigation', (_event, _url, _inPlace, main) => { if (main !== false) { forceMonitorOff();cancelRehearsal();invalidateRouting();routingContext=randomUUID();snapshot = null; audio.ready = false; if (active) { stopCapture(); report('output_navigated'); } } });
      contents.on('render-process-gone', () => { stopCapture(); audio.ready = false; report('output_renderer_unavailable'); });
      target.on('close', () => { if (window === target){windowClosing = true;forceMonitorOff();cancelRehearsal();invalidateRouting();} });
      target.on('closed', () => { const wasActive = Boolean(active); stopCapture(); if (window === target) window = null; audio.ready = false; latest = null; clearInterval(polling); polling = null; if (wasActive) report('output_closed'); });
      await loadInitialOutput(contents,origin + '/output/studio?browser-review=1',{timeoutMs:8000});
      const deadline = now() + 8000000;
      while (!audio.ready && !fault && now() < deadline && !target.isDestroyed()) await new Promise(resolve => setTimeout(resolve, 25));
      if (closed || target.isDestroyed() || target !== window) throw Error('output_capture_closed');
      if (!audio.ready) throw Error(fault || 'output_audio_not_prepared');
      contents.send(CHANNELS.control,{type:'routing',audioRouting,routingContext,monitorVodAllowed:requireVod});
      await readSnapshot();
      polling = setInterval(() => { void readSnapshot(); }, 250); polling.unref?.();
      return status();
    })().finally(() => { preparing = null; });
    return preparing;
  }
  async function startCapture(onVideo, onAudio) {
    if (closed || active || starting || typeof onVideo !== 'function' || typeof onAudio !== 'function') throw Error('output_capture_start_invalid');
    invalidateRouting();
    starting = true; const version = captureVersion;
    try {
    await prepare(); await readSnapshot();
    if (closed || version !== captureVersion || !window || window.isDestroyed()) throw Error('output_capture_cancelled');
    const before = status();
    if (!before.peerId || !before.rendered || before.reviewOpen || before.audioBlocked || !before.audioReady) throw Error('output_not_ready');
    const target = window, ui = captureUi = { target, owner: randomUUID() };
    // Hide preparation controls, not the real review panel. Wait for a painted
    // clean compositor before taking the first picture or subscribing to frames.
    const cleanUi = `(()=>{const root=document.documentElement;root.dataset.nativeCapture='active';root.dataset.nativeCaptureOwner=${JSON.stringify(ui.owner)};return new Promise(resolve=>{const timeout=setTimeout(()=>resolve(false),1500);requestAnimationFrame(()=>requestAnimationFrame(()=>{clearTimeout(timeout);resolve(root.dataset.nativeCaptureOwner===${JSON.stringify(ui.owner)});}));});})()`;
    const marked = await target.webContents.executeJavaScript(cleanUi, false);
    if (marked !== true || closed || version !== captureVersion || target !== window || target.isDestroyed()) throw Error('output_capture_cancelled');
    if(rehearsalReady&&(rehearsalReady.target!==target||rehearsalReady.version!==version||await target.webContents.executeJavaScript(rehearsalVisible(rehearsalReady.generation),false)!==true))throw routingError('output_rehearsal_not_ready');
    // Review can remain open for minutes; seed from the actual current compositor,
    // never from prepare()'s earlier picture, then recheck the reviewed receiver.
    storeFrame(await window.webContents.capturePage()); await readSnapshot();
    if (closed || version !== captureVersion || !window || window.isDestroyed()) throw Error('output_capture_cancelled');
    const current = status();
    if (!current.peerId || !current.rendered || current.reviewOpen || current.audioBlocked || !current.audioReady) throw Error('output_not_ready');
    if (!latest) throw Error('output_picture_unavailable');
    const run = active = { id: randomUUID(), peerId: current.peerId, epoch: now(), timer: null, onVideo, onAudio, frames: 0, index: 0, droppedVideo: 0, videoBusy: false, lastImageAt: 0, audioPackets: 0, droppedAudio: 0, audioSeq: -1, lastAudioPts: -1, audioStarted: false, audioBusy: false, lastAudioAt: now() };
    window.webContents.beginFrameSubscription(false, image => { if (active !== run || now() - run.lastImageAt < 750000 / fps) return; run.lastImageAt = now(); try { storeFrame(image); } catch (_) { stopCapture(); report('output_frame_failed'); } });
    window.webContents.send(CHANNELS.control, { type: 'start', captureId: run.id, audioRouting,routingContext });
    function tick() {
      if (active !== run) return;
      if (run.audioStarted && now() - run.lastAudioAt > 1000000) { stopCapture(); report('output_audio_stalled'); return; }
      const elapsed = now() - run.epoch, targetIndex = Math.floor(elapsed * fps / 1000000);
      if (targetIndex > run.index + 2) { run.droppedVideo += targetIndex - run.index; run.index = targetIndex; }
      const ptsUs = Math.round(run.index * 1000000 / fps); run.index++;
      if (run.videoBusy) run.droppedVideo++;
      else {
        try {
          const accepted = run.onVideo(latest, ptsUs); run.frames++;
          if (accepted && typeof accepted.then === 'function') { run.videoBusy = true; accepted.catch(() => { if (active === run) { stopCapture(); report('output_video_sink_failed'); } }).finally(() => { run.videoBusy = false; }); }
          else if (accepted === false) run.droppedVideo++;
        } catch (_) { stopCapture(); report('output_video_sink_failed'); return; }
      }
      const wait = Math.max(1, (run.index * 1000000 / fps - (now() - run.epoch)) / 1000);
      run.timer = setTimeout(tick, wait); run.timer.unref?.();
    }
    tick();
    const deadline = now() + 3000000;
    while (active === run && !run.audioStarted && now() < deadline) await new Promise(resolve => setTimeout(resolve, 15));
    if (active !== run || !run.audioStarted) { stopCapture(); throw Error('output_audio_capture_not_started'); }
    return status();
    } catch (error) { await stopCapture(); throw error; }
    finally { starting = false; }
  }
  function stopCapture() {
    forceMonitorOff();
    cancelRehearsal();
    invalidateRouting();
    captureVersion++;
    const run = active; active = null;
    if (run) {
      clearTimeout(run.timer);
      try { if (window && !window.isDestroyed()) { window.webContents.endFrameSubscription(); window.webContents.send(CHANNELS.control, { type: 'stop', captureId: run.id }); } } catch (_) {}
    }
    return clearCaptureUi();
  }
  const onHealth = (event, value) => {
    if (!owned(event) || !value || typeof value !== 'object') return;
    if (value.error) { forceMonitorOff();meters=emptyMeters();meterAt=0;audio.ready = false; if (active) stopCapture(); report('output_audio_unavailable'); return; }
    if (typeof value.ready !== 'boolean' || !['running', 'suspended', 'closed'].includes(value.contextState)) return;
    const monitorPending=pendingMonitor;
    if(monitorPending&&value.monitorNonce===monitorPending.nonce&&value.monitorContext===monitorPending.context&&monitorPending.context===routingContext&&monitorPending.target===window&&monitorPending.contents===event.sender&&monitorPending.frame===event.senderFrame&&monitorPending.version===monitorVersion){
      clearTimeout(monitorPending.timer);pendingMonitor=null;if(value.monitorApplied===true&&value.monitorAvailable===true&&value.monitorBus===monitorPending.bus&&(monitorPending.bus==='off'||value.ready&&value.contextState==='running')){monitorPending.resolve({ok:true,monitor:{bus:monitorPending.bus,available:true}});}else{monitorSupported=false;localMonitor?.stop();monitorPending.reject(routingError('rehearsal_monitor_unavailable'));}
    }
    const pending=pendingRouting;
    if(pending&&value.routingApplied===true&&value.routingRequestId===pending.id&&value.routingNonce===pending.nonce&&pending.target===window&&pending.contents===event.sender&&pending.frame===event.senderFrame&&pending.generation===routingGeneration&&value.ready&&value.contextState==='running'){
      clearTimeout(pending.timer);pendingRouting=null;audioRouting=pending.routing;
      const result={ok:true,requestId:pending.id,applied:true};routingRecords.set(pending.id,{signature:pending.signature,result});pending.resolve({...result});
    }
    audio = { ready: value.ready, contextState: value.contextState, sourceCount: Number.isInteger(value.sourceCount) ? Math.min(64, Math.max(0, value.sourceCount)) : 0,
      sources:Array.isArray(value.sources)?value.sources.slice(0,64).flatMap(item=>{try{return normalizeSourceManifest([item]);}catch(_){return [];}}):[],
      unavailableCount: Number.isInteger(value.unavailableCount) ? Math.min(64, Math.max(0, value.unavailableCount)) : 0 };
    meters=cleanMeterHealth(value.audioMeters);meterAt=meters.fresh?now():0;
    audioAt = now();
    if(monitorBus!=='off'&&!pendingMonitor&&value.monitorBus==='off')forceMonitorOff();
    if(monitorBus!=='off'&&(!audio.ready||audio.contextState!=='running'||audio.unavailableCount>0))forceMonitorOff();
    if (active && (!audio.ready || audio.contextState !== 'running' || audio.unavailableCount > 0)) { stopCapture(); report('output_audio_unavailable'); return; }
    if (active && value.captureId === active.id && value.started === true) active.audioStarted = true;
  };
  const onMonitorPcm=async(event,value)=>{
    if(!owned(event)||!monitorId||monitorBus==='off'||value?.monitorId!==monitorId)return;
    if(monitorBusy||!Number.isSafeInteger(value.seq)||value.seq<=monitorSequence||!(value.pcm instanceof Uint8Array)||value.pcm.byteLength!==3840){forceMonitorOff();monitorSupported=false;return;}
    const bytes=Buffer.from(value.pcm.buffer,value.pcm.byteOffset,value.pcm.byteLength),id=monitorId;monitorBusy=true;monitorSequence=value.seq;
    let accepted=false;try{accepted=await localMonitor?.write(bytes)===true;}catch(_){}
    if(id!==monitorId)return;monitorBusy=false;if(!accepted){forceMonitorOff();monitorSupported=false;return;}if(owned(event))event.sender.send(CHANNELS.monitorAck,{monitorId:id,seq:value.seq});
  };
  const onPcm = async (event, value) => {
    const run = active;
    if (!run || !owned(event) || value?.captureId !== run.id) return;
    if (run.audioBusy || !Number.isSafeInteger(value.seq) || value.seq <= run.audioSeq
        || !Number.isSafeInteger(value.ptsUs) || value.ptsUs < 0 || value.ptsUs <= run.lastAudioPts || value.ptsUs > now() - run.epoch + 1000000
        || !(value.pcm instanceof Uint8Array) || value.pcm.byteLength !== AUDIO_FRAMES * 2 * 4
        || (requireVod&&value.vodPcm===undefined)
        || (value.vodPcm!==undefined&&(!(value.vodPcm instanceof Uint8Array)||value.vodPcm.byteLength!==AUDIO_FRAMES*2*4))) { stopCapture(); report('output_audio_protocol_invalid'); return; }
    const bytes = Buffer.from(value.pcm.buffer, value.pcm.byteOffset, value.pcm.byteLength);
    const vod=value.vodPcm===undefined?Buffer.alloc(AUDIO_FRAMES*2*4):Buffer.from(value.vodPcm.buffer,value.vodPcm.byteOffset,value.vodPcm.byteLength);
    for (const pcm of [bytes,vod])for (let i = 0; i < pcm.length; i += 4) if (!Number.isFinite(pcm.readFloatLE(i)) || Math.abs(pcm.readFloatLE(i)) > 1.01) { stopCapture(); report('output_audio_protocol_invalid'); return; }
    run.audioBusy = true; run.audioSeq = value.seq; run.lastAudioPts = value.ptsUs; run.lastAudioAt = now();
    if (Number.isSafeInteger(value.dropped) && value.dropped >= (run.workletDropped || 0)) run.workletDropped = value.dropped;
    try { if (await run.onAudio(bytes, value.ptsUs, vod) === false) run.droppedAudio++; else run.audioPackets++; }
    catch (_) { if (active === run) { stopCapture(); report('output_audio_sink_failed'); } }
    finally { run.audioBusy = false; if (active === run && owned(event)) event.sender.send(CHANNELS.ack, { captureId: run.id, seq: value.seq }); }
  };
  ipcMain.on(CHANNELS.health, onHealth); ipcMain.on(CHANNELS.pcm, onPcm);ipcMain.on(CHANNELS.monitorPcm,onMonitorPcm);
  ipcMain.handle(CHANNELS.sync, event => { if (!active || !owned(event)) throw Error('output_capture_untrusted'); return { captureId: active.id, epochUs: now() - active.epoch }; });
  return { prepare, startCapture, stopCapture,updateAudioRouting,waitForRehearsal,setMonitor,status, get window() { return window; },
    show() {
      const target = window;
      const check = () => {
        if (closed || windowClosing || !target || target !== window || target.isDestroyed() || target.webContents.isDestroyed?.()) throw Error('output_capture_closed');
        if (!allowed(target.webContents.getURL())) throw Error('output_capture_untrusted');
      };
      check(); if (target.isMinimized()) target.restore();
      check(); target.show(); check(); target.focus(); check();
      return status();
    },
    async review() {
      await prepare(); if (active) throw Error('output_capture_active');
      if (!window || window.isDestroyed() || !allowed(window.webContents.getURL())) throw Error('output_capture_untrusted');
      window.show(); window.focus();
      await window.webContents.executeJavaScript('window.ProducerStudioOutput?.reviewBrowserSources()', false);
      await readSnapshot(); return status();
    },
    close() { if (closed) return; closed = true; stopCapture();localMonitor?.close();localMonitor=null; clearInterval(polling); polling = null; ipcMain.removeListener(CHANNELS.health, onHealth); ipcMain.removeListener(CHANNELS.pcm, onPcm);ipcMain.removeListener(CHANNELS.monitorPcm,onMonitorPcm); ipcMain.removeHandler(CHANNELS.sync); if (window && !window.isDestroyed()) window.destroy(); window = null; latest = null; },
  };
}
module.exports = { createOutputCapture, cleanSnapshot, CHANNELS };
