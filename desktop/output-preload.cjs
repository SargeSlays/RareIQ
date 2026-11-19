'use strict';
// No contextBridge: this privileged tap is never exposed to page scripts/iframes.
const { ipcRenderer } = require('electron');
if (process.isMainFrame) {
  const origin = process.argv.find(arg => arg.startsWith('--producer-output-origin='))?.slice('--producer-output-origin='.length);
  const CHANNELS = { health: 'producer:output:health', pcm: 'producer:output:pcm', sync: 'producer:output:sync', control: 'producer:output:control', ack: 'producer:output:ack' };
  const worklet = `class PublicOutputTap extends AudioWorkletProcessor {
    constructor() {
      super(); this.enabled = false; this.credit = 0; this.offset = 0;
      this.samples = new Float32Array(960); this.vodSamples = new Float32Array(960); this.queue = []; this.dropped = 0;
      this.port.onmessage = event => {
        const data = event.data;
        if (data.type === 'start') {
          this.captureId = data.captureId; this.enabled = true; this.credit = 1;
          this.offset = 0; this.queue = []; this.dropped = 0;
        } else if (data.type === 'stop') {
          this.enabled = false; this.offset = 0; this.queue = [];
        } else if (data.type === 'credit' && data.captureId === this.captureId) {
          this.credit = Math.min(1, this.credit + 1); this.flush();
        }
      };
    }
    flush() {
      if (!this.enabled || !this.credit || !this.queue.length) return;
      this.credit--; const packet = this.queue.shift();
      this.port.postMessage({ captureId: this.captureId, frame: packet.frame,
        dropped: this.dropped, pcm: packet.pcm, vodPcm: packet.vodPcm }, [packet.pcm, packet.vodPcm]);
    }
    process(inputs, outputs) {
      for (const output of outputs) for (const channel of output) channel.fill(0);
      if (!this.enabled) return true;
      const input = inputs[0] || [], vodInput = inputs[1] || [], count = outputs[0]?.[0]?.length || 128;
      for (let i = 0; i < count; i++) {
        if (this.offset === 0) this.first = currentFrame + i;
        for (let c = 0; c < 2; c++) {
          const value = input[c]?.[i] ?? input[0]?.[i] ?? 0;
          this.samples[this.offset * 2 + c] = Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : 0;
          const vodValue = vodInput[c]?.[i] ?? vodInput[0]?.[i] ?? 0;
          this.vodSamples[this.offset * 2 + c] = Number.isFinite(vodValue) ? Math.max(-1, Math.min(1, vodValue)) : 0;
        }
        if (++this.offset === 480) {
          // At most 40 ms queued behind one in-flight IPC packet.
          if (this.queue.length === 4) { this.queue.shift(); this.dropped++; }
          this.queue.push({ frame: this.first, pcm: this.samples.buffer, vodPcm: this.vodSamples.buffer });
          this.samples = new Float32Array(960); this.vodSamples = new Float32Array(960); this.offset = 0; this.flush();
        }
      }
      return true;
    }
  }
  registerProcessor('public-output-tap', PublicOutputTap);`;
  const frames = [['iframe.program', '/program','program'], ['iframe.audio', '/output/soundboard','soundboard'], ['iframe.graphics', '/overlay/graphics','graphics'], ['iframe.audience', '/overlay/audience','audience']];
  let context, node, mixer, vodMixer, stopped = false, capture = null, poll, healthTimer, token = 0, audioRouting={};
  const entries = new Map(), documents = new Map();
  // Sandbox preloads cannot require application modules. Main validates saved
  // profiles with audio-routing.cjs; this private boundary validates IPC again.
  const categoryLabels={voice:'Guest microphone',screen:'Guest screen audio',video:'Video audio',program:'Other Program audio',soundboard:'Soundboard audio',graphics:'Graphics audio',audience:'Audience alerts'};
  function validSourceId(id){return typeof id==='string'&&(/^guest:[a-f0-9]{32}:(microphone|screen_audio)$/.test(id)||/^video:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id)||/^(soundboard|graphics|audience):[A-Za-z0-9_-]{1,128}$/.test(id)||Object.hasOwn(categoryLabels,id.split(':')[0])&&id===id.split(':')[0]+':default');}
  function describeSource(element,group){
    if(group==='program'){
      const declared=element.dataset?.audioSource||element.closest?.('[data-source]')?.dataset?.source;
      if(validSourceId(declared)&&declared.startsWith('guest:')){const category=declared.endsWith(':microphone')?'voice':'screen';return {id:declared,category,label:categoryLabels[category]};}
      if(validSourceId(declared)&&declared.startsWith('video:'))return {id:declared,category:'video',label:categoryLabels.video};
    }else{
      try{const url=new URL(element.currentSrc||element.src,origin),asset=url.origin===origin&&!url.search&&!url.hash&&url.pathname.match(/^\/api\/creator\/assets\/([A-Za-z0-9_-]{1,128})$/);
        if(asset)return {id:group+':'+asset[1],category:group,label:categoryLabels[group]};}catch(_){}
    }
    return {id:group+':default',category:group,label:categoryLabels[group]};
  }
  function routingFor(source){
    const group=['voice','screen','video','program'].includes(source.category)?'program':source.category;
    return audioRouting[source.id]??audioRouting[source.category+':default']??audioRouting[group+':default']??{live:true,vod:source.category==='voice'};
  }
  function applyRouting(value){
    if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length>128)throw Error('invalid_audio_routing');
    const next={};
    for(const [id,route] of Object.entries(value)){
      if(!validSourceId(id)||!route||typeof route!=='object'||Array.isArray(route)||Object.keys(route).length!==2||typeof route.live!=='boolean'||typeof route.vod!=='boolean')throw Error('invalid_audio_routing');
      next[id]={live:route.live,vod:route.vod};
    }
    audioRouting=next;for(const entry of entries.values())refresh(entry);
  }
  const validTop = () => location.origin === origin && location.pathname === '/output/studio' && window.top === window;
  function sendHealth(error = false) {
    if (!validTop()) return;
    ipcRenderer.send(CHANNELS.health, { ready: Boolean(context && node && !stopped), contextState: context?.state || 'closed', sourceCount: [...entries.values()].filter(entry => entry.source).length,
      unavailableCount: [...entries.values()].filter(entry => entry.failed && !entry.element.paused && !entry.element.muted).length,
      sources:[...new Map([...entries.values()].map(entry=>[entry.descriptor.id,entry.descriptor])).values()].slice(0,64),
      ...(error ? { error: true } : {}), ...(capture ? { captureId: capture.id, started: true } : {}) });
  }
  function detach(entry) {
    for (const [name, fn] of entry.listeners) entry.element.removeEventListener(name, fn);
    entry.source?.disconnect(); entry.gain.disconnect();entry.vodGain.disconnect();
    // captureStream borrows media; never stop any source/captured/original track.
    entry.source = null; entry.stream = null; entries.delete(entry.element);
  }
  function refresh(entry) {
    const element = entry.element;
    entry.descriptor=describeSource(element,entry.group);
    const route=routingFor(entry.descriptor),volume=element.paused||element.ended||element.muted?0:Math.max(0,Math.min(1,Number.isFinite(element.volume)?element.volume:0));
    entry.gain.gain.setValueAtTime(route.live?volume:0,context.currentTime);entry.vodGain.gain.setValueAtTime(route.vod?volume:0,context.currentTime);
    try {
      const source = element.srcObject || element.currentSrc;
      if (source !== entry.mediaIdentity) { entry.source?.disconnect(); entry.source = null; entry.track = null; entry.stream = null; entry.mediaIdentity = source; }
      // Creating a file tap before decoded playback can leave Chromium's captured
      // track permanently silent. One tap per playing source also avoids replacing it.
      if (!entry.stream && (element.paused || element.readyState < 2)) return;
      // A public WebRTC element already owns a MediaStream. Borrow its tracks
      // directly to avoid a second Chromium capture buffer; never stop them.
      if (!entry.stream) entry.stream = element.srcObject && typeof element.srcObject.getAudioTracks === 'function' ? element.srcObject : element.captureStream();
      const track = entry.stream.getAudioTracks().find(item => item.readyState === 'live');
      if (track !== entry.track) {
        entry.source?.disconnect(); entry.source = null; entry.track = track;
        if (track) { entry.source = context.createMediaStreamSource(new MediaStream([track])); entry.source.connect(entry.gain);entry.source.connect(entry.vodGain); }
      }
      entry.failed = false;
    } catch (_) { entry.failed = true; entry.gain.gain.setValueAtTime(0, context.currentTime);entry.vodGain.gain.setValueAtTime(0,context.currentTime); }
  }
  function scan() {
    if (stopped || !context || !validTop()) return;
    const allowedDocs = new Set(), media = new Map();
    for (const [selector, pathname,group] of frames) {
      try {
        const frame = document.querySelector(selector), child = frame?.contentWindow;
        if (!child || child.location.origin !== origin || child.location.pathname !== pathname) continue;
        const doc = frame.contentDocument; if (!doc) continue; allowedDocs.add(doc);
        if (!documents.has(doc)) { const observer = new MutationObserver(scan); observer.observe(doc, { childList: true, subtree: true }); documents.set(doc, observer); }
        // Deliberately no traversal into any nested iframe (including browser sources).
        for (const element of doc.querySelectorAll('audio,video'))media.set(element,group);
      } catch (_) {}
    }
    for (const [doc, observer] of documents) if (!allowedDocs.has(doc)) { observer.disconnect(); documents.delete(doc); }
    for (const entry of entries.values()) if (!media.has(entry.element)) detach(entry);
    for (const [element,group] of [...media].slice(0, 64)) {
      let entry = entries.get(element);
      if (!entry) {
        const gain = context.createGain(),vodGain=context.createGain(); gain.gain.value = vodGain.gain.value=0; gain.connect(mixer);vodGain.connect(vodMixer);
        entry = { element, group,descriptor:describeSource(element,group),gain,vodGain,source: null, stream: null, track: null, failed: false, listeners: [] }; entries.set(element, entry);
        for (const name of ['play', 'playing', 'pause', 'volumechange', 'ended', 'emptied', 'loadedmetadata']) { const fn = () => refresh(entry); element.addEventListener(name, fn); entry.listeners.push([name, fn]); }
      }
      refresh(entry);
    }
  }
  async function start(value) {
    if (!validTop() || !context || !node || stopped || typeof value.captureId !== 'string') return;
    applyRouting(value.audioRouting??{});
    const version = ++token; capture = null; node.port.postMessage({ type: 'stop' });
    const before = performance.now(); const sync = await ipcRenderer.invoke(CHANNELS.sync); const after = performance.now();
    if (version !== token || sync.captureId !== value.captureId || stopped) return;
    await context.resume();
    capture = { id: value.captureId, seq: 0, outstanding: null, contextTime: context.currentTime, epochUs: sync.epochUs + (after - before) * 500 };
    node.port.postMessage({ type: 'start', captureId: capture.id }); sendHealth();
  }
  ipcRenderer.on(CHANNELS.control, (_event, value) => {
    if (value?.type === 'start') start(value).catch(() => sendHealth(true));
    else if(value?.type==='routing'){try{applyRouting(value.audioRouting);}catch(_){sendHealth(true);}}
    else if (value?.type === 'stop') { ++token; capture = null; node?.port.postMessage({ type: 'stop' }); }
  });
  ipcRenderer.on(CHANNELS.ack, (_event, value) => { if (capture && value?.captureId === capture.id && value.seq === capture.outstanding) { capture.outstanding = null; node.port.postMessage({ type: 'credit', captureId: capture.id }); } });
  async function prepare() {
    if (!validTop()) return;
    try {
      // Chromium's non-audible sink runs the graph without a speaker/audio-device route.
      context = new AudioContext({ sampleRate: 48000, sinkId: { type: 'none' } });
      if (context.sampleRate !== 48000) throw Error('sample_rate_unavailable');
      const url = URL.createObjectURL(new Blob([worklet], { type: 'text/javascript' }));
      try { await context.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
      if (stopped) return;
      mixer = context.createGain();vodMixer=context.createGain();node = new AudioWorkletNode(context, 'public-output-tap', { numberOfInputs: 2, numberOfOutputs: 1, outputChannelCount: [2], channelCount: 2, channelCountMode: 'explicit' });
      mixer.connect(node,0,0);vodMixer.connect(node,0,1);node.connect(context.destination);
      node.port.onmessage = event => {
        const current = capture, data = event.data;
        if (!current || data?.captureId !== current.id || current.outstanding !== null || !(data?.pcm instanceof ArrayBuffer) || data.pcm.byteLength !== 3840 || !(data.vodPcm instanceof ArrayBuffer)||data.vodPcm.byteLength!==3840|| !Number.isInteger(data.frame)) return;
        const ptsUs = Math.max(0, Math.round(current.epochUs + (data.frame / 48000 - current.contextTime) * 1000000)), seq = current.seq++;
        current.outstanding = seq;
        ipcRenderer.send(CHANNELS.pcm, { captureId: current.id, seq, ptsUs, dropped: data.dropped, pcm: new Uint8Array(data.pcm),vodPcm:new Uint8Array(data.vodPcm) });
      };
      await context.resume(); scan(); poll = setInterval(scan, 100); healthTimer = setInterval(sendHealth, 250); sendHealth();
    } catch (_) { sendHealth(true); }
  }
  if (document.readyState === 'loading') window.addEventListener('DOMContentLoaded', prepare, { once: true }); else void prepare();
  window.addEventListener('pagehide', () => { stopped = true; ++token; capture = null; clearInterval(poll); clearInterval(healthTimer); for (const entry of entries.values()) detach(entry); for (const observer of documents.values()) observer.disconnect(); documents.clear(); node?.disconnect(); mixer?.disconnect();vodMixer?.disconnect();void context?.close(); }, { once: true });
}
