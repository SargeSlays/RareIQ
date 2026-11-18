'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), { EventEmitter } = require('node:events');
const { createOutputCapture, cleanSnapshot, CHANNELS } = require('../output-capture.cjs');
const ORIGIN = 'http://127.0.0.1:54321';
const goodSnapshot = () => ({ peerId: 'fixture-peer', generation: 2, rendered: true, browserReviewOpen: false, audioBlocked: false, readySources: ['camera:1'] });
function fixture(options = {}) {
  const ipc = new EventEmitter(); ipc.handlers = new Map(); ipc.handle = (channel, fn) => ipc.handlers.set(channel, fn); ipc.removeHandler = channel => ipc.handlers.delete(channel);
  const errors = [], sent = []; let instance;
  class Window extends EventEmitter {
    constructor(config) {
      super(); instance = this; this.config = config; this.destroyed = false;
      const wc = this.webContents = new EventEmitter(); wc.mainFrame = { url: '' }; wc.url = ''; wc.muted = false;
      wc.getURL = () => wc.url; wc.setAudioMuted = value => { wc.muted = value; }; wc.isAudioMuted = () => wc.muted;
      wc.setWindowOpenHandler = fn => { wc.openHandler = fn; };
      wc.session = { setPermissionCheckHandler(fn) { this.check = fn; }, setPermissionRequestHandler(fn) { this.request = fn; }, setDisplayMediaRequestHandler(fn) { this.display = fn; } };
      wc.document = { documentElement: { dataset: {} } }; wc.frames = []; wc.events = [];
      wc.scripts = []; wc.executeJavaScript = async code => {
        wc.scripts.push(code);
        if (code.includes('nativeCapture')) {
          if (code.includes("nativeCapture='active'")) wc.events.push('hide-controls'); else wc.events.push('restore-controls');
          return vm.runInNewContext(code, { document: wc.document, setTimeout, clearTimeout, requestAnimationFrame: fn => options.paint ? options.paint(fn) : queueMicrotask(fn) });
        }
        if (code.includes('ProducerStudioOutput')) { options.onReview?.(); return null; } return options.snapshot || goodSnapshot();
      };
      wc.capturePage = async () => { const clean = wc.document.documentElement.dataset.nativeCapture === 'active'; wc.frames.push(clean); wc.events.push('capture'); return { isEmpty: () => false, getSize: () => ({ width: config.width, height: config.height }), toBitmap: () => Buffer.alloc(config.width * config.height * 4, clean ? 25 : 199) }; };
      wc.beginFrameSubscription = (dirty, callback) => { if (options.failSubscription) throw Error('subscription failed'); wc.events.push('subscribe'); wc.dirty = dirty; wc.frameCallback = callback; };
      wc.endFrameSubscription = () => { wc.events.push('unsubscribe'); wc.frameCallback = null; wc.ended = true; };
      wc.send = (channel, value) => { sent.push({ channel, value }); if (channel === CHANNELS.control && value.type === 'start') queueMicrotask(() => health({ captureId: value.captureId, started: true })); };
    }
    isDestroyed() { return this.destroyed; } show() {} focus() {} setMenu() {}
    async loadURL(url) { this.webContents.url = url; this.webContents.mainFrame.url = url; if (options.loadWait) await options.loadWait; health(); }
    destroy() { this.destroyed = true; this.emit('closed'); }
  }
  const event = () => ({ sender: instance.webContents, senderFrame: instance.webContents.mainFrame });
  const health = extra => ipc.emit(CHANNELS.health, event(), { ready: true, contextState: 'running', sourceCount: 1, unavailableCount: 0, ...extra });
  const capture = createOutputCapture({ BrowserWindow: Window, ipcMain: ipc, origin: ORIGIN, width: options.width || 1280, height: options.height || 720, onError: code => errors.push(code) });
  return { capture, ipc, errors, sent, event, health, get window() { return instance; },
    packet(extra = {}) { return { captureId: sent.filter(s => s.channel === CHANNELS.control && s.value.type === 'start').at(-1).value.captureId, seq: 0, ptsUs: 100, pcm: new Uint8Array(3840), ...extra }; },
    async pcm(value, from = event()) { await ipc.listeners(CHANNELS.pcm)[0](from, value); },
  };
}
test('snapshot validates identity and only returns bounded public source ids', () => {
  assert.equal(cleanSnapshot({ ...goodSnapshot(), peerId: 'https://private.invalid' }), null);
  assert.equal(cleanSnapshot({ ...goodSnapshot(), generation: NaN }), null);
  assert.equal(cleanSnapshot({ ...goodSnapshot(), rendered: 'yes' }), null);
  assert.deepEqual(cleanSnapshot({ ...goodSnapshot(), readySources: ['camera:1', 'secret:any', 'camera:2'] }).readySources, ['camera:1', 'camera:2']);
});
test('owned output is isolated, locally muted, permission denied and uses actual review document', async t => {
  const f = fixture(); t.after(() => f.capture.close()); await f.capture.prepare();
  const c = f.window.config, w = f.window.webContents;
  assert.equal(c.webPreferences.sandbox, true); assert.equal(c.webPreferences.contextIsolation, true);
  assert.equal(c.webPreferences.nodeIntegration, false); assert.equal(c.webPreferences.nodeIntegrationInSubFrames, false);
  assert.equal(c.webPreferences.backgroundThrottling, false); assert.match(w.getURL(), /\/output\/studio\?browser-review=1$/);
  assert.equal(w.isAudioMuted(), true); assert.equal(w.session.check(), false); assert.deepEqual(w.openHandler(), { action: 'deny' });
  let permission, display; w.session.request(null, null, value => { permission = value; }); w.session.display(null, value => { display = value; });
  assert.equal(permission, false); assert.equal(display, null); assert.equal(f.capture.status().peerId, 'fixture-peer');
  f.health({ ready: false }); assert.equal(f.capture.status().audioReady, false);
  f.ipc.emit(CHANNELS.health, { sender: w, senderFrame: { url: w.getURL() } }, { ready: true, contextState: 'running' });
  assert.equal(f.capture.status().audioReady, false, 'subframe cannot forge readiness');
});
test('review-open and unrendered output cannot capture', async t => {
  for (const patch of [{ browserReviewOpen: true }, { rendered: false }, { audioBlocked: true }]) {
    const f = fixture({ snapshot: { ...goodSnapshot(), ...patch } });
    try { await assert.rejects(f.capture.startCapture(() => {}, () => {}), /output_not_ready/); assert.equal(f.capture.status().capturing, false); }
    finally { f.capture.close(); }
  }
});
test('explicit review reopens through the owned output hook without replacing its window', async t => {
  const snapshot = goodSnapshot(); let calls = 0;
  const f = fixture({ snapshot, onReview: () => { calls++; snapshot.browserReviewOpen = true; } }); t.after(() => f.capture.close());
  await f.capture.prepare(); const original = f.window;
  const result = await f.capture.review();
  assert.equal(f.window, original); assert.equal(calls, 1); assert.equal(result.reviewOpen, true);
  assert.ok(f.window.webContents.scripts.includes('window.ProducerStudioOutput?.reviewBrowserSources()'));
});
test('constant video clock repeats latest full BGRA frame with microsecond PTS', async t => {
  const f = fixture(), video = []; t.after(() => f.capture.close());
  await f.capture.startCapture((buffer, ptsUs) => video.push({ buffer, ptsUs }), () => true);
  await new Promise(resolve => setTimeout(resolve, 80)); f.capture.stopCapture();
  assert.equal(f.window.webContents.dirty, false); assert.ok(video.length >= 3);
  assert.deepEqual(video.slice(0, 3).map(v => v.ptsUs), [0, 33333, 66667]);
  assert.ok(video.every(v => v.buffer.length === 1280 * 720 * 4 && v.buffer === video[0].buffer));
  const n = video.length; await new Promise(resolve => setTimeout(resolve, 40)); assert.equal(video.length, n);
  assert.equal(f.window.webContents.ended, true);
});
test('capture seeds only a newly painted clean picture and restores controls after unsubscribing', async t => {
  const f = fixture(), frames = []; t.after(() => f.capture.close()); await f.capture.prepare();
  const wc = f.window.webContents;
  assert.deepEqual(wc.frames, [], 'Prepare never caches a picture with preparation controls');
  await f.capture.startCapture(buffer => frames.push(buffer[0]), () => true);
  assert.equal(frames[0], 25); assert.deepEqual(wc.frames, [true]);
  assert.ok(wc.events.indexOf('hide-controls') < wc.events.indexOf('capture'));
  assert.ok(wc.events.indexOf('capture') < wc.events.indexOf('subscribe'));
  await f.capture.stopCapture();
  assert.equal(wc.document.documentElement.dataset.nativeCapture, undefined);
  assert.ok(wc.events.indexOf('unsubscribe') < wc.events.indexOf('restore-controls'));
  await f.capture.startCapture(buffer => frames.push(buffer[0]), () => true);
  assert.deepEqual(wc.frames, [true, true]); assert.ok(frames.every(value => value === 25));
  const staleClear = wc.scripts.find(code => code.includes('delete root.dataset.nativeCapture;'));
  vm.runInNewContext(staleClear, { document: wc.document });
  assert.equal(wc.document.documentElement.dataset.nativeCapture, 'active', 'late cleanup from the previous run cannot reveal controls');
});
test('cancel during the clean-paint wait restores controls and never captures a stale frame', async t => {
  const paints = [], f = fixture({ paint: fn => paints.push(fn) }); t.after(() => f.capture.close());
  const pending = f.capture.startCapture(() => assert.fail('cancelled capture emitted a frame'), () => true);
  const rejected = assert.rejects(pending, /output_capture_cancelled/);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.window.webContents.document.documentElement.dataset.nativeCapture, 'active');
  await f.capture.stopCapture(); while (paints.length) paints.shift()(); await rejected;
  assert.equal(f.window.webContents.document.documentElement.dataset.nativeCapture, undefined);
  assert.deepEqual(f.window.webContents.frames, []);
});
test('closing the output during clean-paint preparation cancels without publishing a frame', async () => {
  const paints = [], f = fixture({ paint: fn => paints.push(fn) });
  const pending = f.capture.startCapture(() => assert.fail('closed output emitted a frame'), () => true);
  const rejected = assert.rejects(pending, /output_capture_cancelled/);
  await new Promise(resolve => setImmediate(resolve)); const wc = f.window.webContents;
  f.capture.close(); while (paints.length) paints.shift()(); await rejected;
  assert.equal(f.capture.window, null); assert.deepEqual(wc.frames, []);
});
test('PCM is accepted only from owned top frame and acknowledges after consumer', async t => {
  const f = fixture(), audio = []; t.after(() => f.capture.close()); await f.capture.startCapture(() => true, (buffer, ptsUs) => audio.push({ buffer, ptsUs }));
  const packet = f.packet();
  await f.pcm(packet, { sender: f.window.webContents, senderFrame: { url: ORIGIN + '/program' } });
  await f.pcm(packet, { sender: {}, senderFrame: f.window.webContents.mainFrame });
  await f.pcm({ ...packet, captureId: 'stale-run' }); assert.equal(audio.length, 0);
  await f.pcm(packet); assert.equal(audio.length, 1); assert.equal(audio[0].ptsUs, 100); assert.equal(audio[0].buffer.length, 3840);
  assert.equal(f.sent.at(-1).channel, CHANNELS.ack);
  await f.pcm(packet); assert.equal(f.capture.status().capturing, false); assert.deepEqual(f.errors, ['output_audio_protocol_invalid']);
});
test('invalid PCM length, non-finite samples, future timestamp and replay fail closed', async () => {
  const invalid = [() => ({ pcm: new Uint8Array(8) }), () => { const pcm = Buffer.alloc(3840); pcm.writeFloatLE(NaN); return { pcm }; }, () => ({ ptsUs: 9000000000 }), () => ({ seq: -1 })];
  for (const patch of invalid) {
    const f = fixture(); let count = 0;
    try { await f.capture.startCapture(() => true, () => { count++; }); await f.pcm(f.packet(patch())); assert.equal(count, 0); assert.equal(f.capture.status().capturing, false); assert.deepEqual(f.errors, ['output_audio_protocol_invalid']); }
    finally { f.capture.close(); }
  }
});
test('main enforces one pending audio callback even if renderer sends another packet', async t => {
  const f = fixture(); t.after(() => f.capture.close()); let release, count = 0;
  await f.capture.startCapture(() => true, () => { count++; return new Promise(resolve => { release = resolve; }); });
  const pending = f.pcm(f.packet()); await f.pcm(f.packet({ seq: 1, ptsUs: 101 }));
  assert.equal(count, 1); assert.equal(f.capture.status().capturing, false); release(true); await pending;
});
test('concurrent start and cancelled preparation never leave capture running', async t => {
  let release; const f = fixture({ loadWait: new Promise(resolve => { release = resolve; }) }); t.after(() => f.capture.close());
  const first = f.capture.startCapture(() => true, () => true);
  await assert.rejects(f.capture.startCapture(() => true, () => true), /output_capture_start_invalid/);
  f.capture.stopCapture(); release(); await assert.rejects(first, /output_capture_cancelled/); assert.equal(f.capture.status().capturing, false);
});
test('subscription failure, navigation and unavailable audio stop capture', async () => {
  const failed = fixture({ failSubscription: true });
  try { await assert.rejects(failed.capture.startCapture(() => {}, () => {}), /subscription failed/); assert.equal(failed.capture.status().capturing, false); assert.equal(failed.window.webContents.document.documentElement.dataset.nativeCapture, undefined); }
  finally { failed.capture.close(); }
  for (const action of [f => f.health({ contextState: 'suspended' }), f => f.window.webContents.emit('did-start-navigation', {}, ORIGIN + '/output/studio', false, true)]) {
    const f = fixture(); try { await f.capture.startCapture(() => true, () => true); action(f); assert.equal(f.capture.status().capturing, false); } finally { f.capture.close(); }
  }
});
test('portrait format stays exact and close removes all privileged handlers', async () => {
  const f = fixture({ width: 720, height: 1280 }); let bytes = 0;
  await f.capture.startCapture(buffer => { bytes = buffer.length; }, () => true);
  assert.equal(bytes, 720 * 1280 * 4); assert.equal(f.capture.status().height, 1280);
  f.capture.close(); f.capture.close(); assert.equal(f.ipc.listenerCount(CHANNELS.pcm), 0); assert.equal(f.ipc.handlers.size, 0);
});
