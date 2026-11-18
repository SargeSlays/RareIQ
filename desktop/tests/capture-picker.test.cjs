'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const path = require('node:path'), { pathToFileURL } = require('node:url');
const { createCapturePicker, CHANNELS } = require('../capture-picker.cjs');
const origin = 'http://127.0.0.1:8765';
const baseDir = path.resolve(__dirname, '..');
const choices = () => [
  { id: 'screen:0:0', name: 'Screen 1', thumbnail: { toDataURL: () => 'data:image/png;base64,AAAA' } },
  { id: 'window:123:0', name: '<private title>', thumbnail: { toDataURL: () => 'data:image/png;base64,AAAA' } },
];
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
class Contents extends EventEmitter {
  constructor(url = '') { super(); this.mainFrame = { url }; this.dead = false; this.session = new EventEmitter();
    for (const name of ['setPermissionCheckHandler', 'setPermissionRequestHandler', 'setDisplayMediaRequestHandler']) this.session[name] = fn => { this.session[name + 'Value'] = fn; };
  }
  isDestroyed() { return this.dead; }
  getURL() { return this.mainFrame.url; }
  setWindowOpenHandler(fn) { this.open = fn; }
}
function fixture(t, getSources = async () => choices()) {
  const windows = [], calls = [], handlers = new Map(), received = [];
  const studio = new EventEmitter(); studio.webContents = new Contents(origin + '/control?workspace=studio'); studio.isDestroyed = () => false;
  class Window extends EventEmitter {
    constructor(options) { super(); this.options = options; this.webContents = new Contents(); this.dead = false; this.shown = false; windows.push(this); }
    isDestroyed() { return this.dead; }
    setMenu(value) { this.menu = value; }
    async loadFile(file) { this.webContents.mainFrame.url = pathToFileURL(file).href; this.emit('ready-to-show'); }
    show() { this.shown = true; }
    focus() {}
    destroy() { if (this.dead) return; this.dead = true; this.webContents.dead = true; this.emit('closed'); this.webContents.emit('destroyed'); }
  }
  const ipcMain = { handle(name, handler) { assert.equal(handlers.has(name), false); handlers.set(name, handler); }, removeHandler(name) { handlers.delete(name); } };
  const picker = createCapturePicker({ BrowserWindow: Window, ipcMain, desktopCapturer: { getSources(options) { calls.push(options); return getSources(calls.length, options); } }, studio, origin, baseDir });
  t.after(() => picker.close());
  const request = overrides => ({ frame: studio.webContents.mainFrame, securityOrigin: origin, videoRequested: true, audioRequested: false, userGesture: true, ...overrides });
  const start = overrides => picker.handler(request(overrides), result => received.push(result));
  const event = () => { const window = windows.at(-1); return { sender: window.webContents, senderFrame: window.webContents.mainFrame }; };
  const invoke = (name, value, sender = event()) => handlers.get(CHANNELS[name])(sender, value);
  return { picker, studio, windows, calls, received, handlers, start, request, event, invoke };
}

test('only explicit video requests from the exact trusted Studio main frame enumerate sources', t => {
  const f = fixture(t);
  for (const override of [{ frame: null }, { frame: { url: origin + '/control' } }, { securityOrigin: 'https://untrusted.invalid' }, { securityOrigin: origin + '/' }, { userGesture: false }, { videoRequested: false, audioRequested: true }, { videoRequested: undefined }]) f.start(override);
  assert.equal(f.calls.length, 0); assert.equal(f.windows.length, 0);
  assert.deepEqual(f.received, Array(7).fill(null));
  f.studio.webContents.mainFrame.url = 'https://untrusted.invalid'; f.start();
  assert.equal(f.calls.length, 0); assert.equal(f.received.length, 8);
});

test('picker is sandboxed, uses local assets, and exposes opaque choices without native IDs', async t => {
  const f = fixture(t); f.start(); const window = f.windows[0];
  const list = await f.invoke('list');
  assert.equal(list.phase, 'ready'); assert.equal(list.audioIncluded, false);
  assert.equal(list.sources.length, 2); assert.equal(f.received.length, 0);
  assert.notEqual(list.sources[0].id, choices()[0].id);
  assert.equal(JSON.stringify(list).includes('window:123:0'), false);
  assert.equal(list.sources[1].name, '<private title>');
  assert.deepEqual(f.calls[0].types, ['screen', 'window']);
  assert.equal(window.options.parent, f.studio); assert.equal(window.options.modal, true);
  assert.equal(window.options.webPreferences.sandbox, true); assert.equal(window.options.webPreferences.contextIsolation, true);
  assert.equal(window.options.webPreferences.nodeIntegration, false); assert.equal(window.options.webPreferences.webSecurity, true);
  assert.equal(window.options.webPreferences.preload, path.join(baseDir, 'capture-preload.cjs'));
  assert.deepEqual(window.webContents.open({ url: 'https://untrusted.invalid' }), { action: 'deny' });
  assert.equal(window.webContents.session.setPermissionCheckHandlerValue(), false);
  assert.equal(window.shown, true);
});

test('selection rechecks current OS list and grants video only even when audio was requested', async t => {
  const f = fixture(t); f.start({ audioRequested: true });
  const list = await f.invoke('list');
  assert.deepEqual(await f.invoke('choose', list.sources[1].id), { accepted: true });
  assert.deepEqual(f.received, [{ video: { id: 'window:123:0', name: '<private title>' } }]);
  assert.deepEqual(f.calls[1].thumbnailSize, { width: 0, height: 0 });
  assert.equal(f.windows[0].dead, true);
  f.windows[0].emit('closed'); f.picker.close();
  assert.equal(f.received.length, 1);
});

test('IPC rejects studio, other windows, subframes and changed file URLs', async t => {
  const f = fixture(t); f.start();
  const event = f.event();
  const bad = [
    { sender: f.studio.webContents, senderFrame: f.studio.webContents.mainFrame },
    { sender: new Contents(event.senderFrame.url), senderFrame: event.senderFrame },
    { sender: event.sender, senderFrame: { url: event.senderFrame.url } },
  ];
  for (const sender of bad) await assert.rejects(f.invoke('list', undefined, sender), /capture_picker_untrusted/);
  const fileUrl = event.senderFrame.url; event.senderFrame.url += '#forged';
  await assert.rejects(f.invoke('list'), /capture_picker_untrusted/);
  event.senderFrame.url = fileUrl;
  assert.equal((await f.invoke('list')).sources.length, 2); assert.equal(f.received.length, 0);
});

test('arbitrary native IDs and malformed selections cancel without granting', async t => {
  const f = fixture(t); f.start(); await f.invoke('list');
  assert.deepEqual(await f.invoke('choose', 'screen:0:0'), { accepted: false });
  assert.deepEqual(f.received, [null]); assert.equal(f.calls.length, 1);
});

test('Cancel, native close and repeated close each resolve the callback exactly once', async t => {
  const f = fixture(t); f.start(); await f.invoke('list');
  assert.deepEqual(f.invoke('cancel'), { cancelled: true });
  f.windows[0].emit('closed'); assert.deepEqual(f.received, [null]);
  f.start(); await f.invoke('list'); f.windows[1].destroy(); f.windows[1].emit('closed');
  assert.deepEqual(f.received, [null, null]);
});

test('overlapping valid requests deny both without another enumeration', async t => {
  const pending = deferred(), f = fixture(t, () => pending.promise);
  f.start(); f.start(); assert.deepEqual(f.received, [null, null]); assert.equal(f.calls.length, 1);
  pending.resolve(choices()); await pending.promise; await Promise.resolve();
  assert.equal(f.windows.length, 1); assert.equal(f.windows[0].dead, true); assert.equal(f.received.length, 2);
});

test('invalid requests do not dismiss an existing explicit picker', async t => {
  const f = fixture(t); f.start(); f.start({ userGesture: false });
  assert.deepEqual(f.received, [null]); assert.equal(f.windows[0].dead, false);
  assert.equal((await f.invoke('list')).phase, 'ready');
});

test('main-frame navigation during enumeration discards late sources; subframe navigation does not', async t => {
  const pending = deferred(), f = fixture(t, () => pending.promise); f.start();
  f.studio.webContents.emit('did-start-navigation', {}, origin + '/subframe', false, false);
  assert.equal(f.received.length, 0);
  f.studio.webContents.emit('did-start-navigation', {}, origin + '/control', false, true);
  pending.resolve(choices()); await pending.promise; await Promise.resolve();
  assert.deepEqual(f.received, [null]); assert.equal(f.windows[0].dead, true);
});

test('renderer failure or Studio close cancels a pending request', async t => {
  const f = fixture(t); f.start(); await f.invoke('list');
  f.windows[0].webContents.emit('render-process-gone', {}, {}); assert.deepEqual(f.received, [null]);
  f.start(); await f.invoke('list'); f.studio.emit('closed'); assert.deepEqual(f.received, [null, null]);
});

test('disappeared or reassigned source IDs are denied after the user selects', async t => {
  const f = fixture(t, async count => count === 1 ? choices() : [{ ...choices()[0], name: 'Different application' }]);
  f.start(); const list = await f.invoke('list');
  assert.deepEqual(await f.invoke('choose', list.sources[0].id), { accepted: false });
  assert.deepEqual(f.received, [null]);
});

test('late selection cannot grant after cancellation or a second request', async t => {
  const pending = deferred(), f = fixture(t, async count => count === 1 ? choices() : pending.promise);
  f.start(); const list = await f.invoke('list');
  const selecting = f.invoke('choose', list.sources[0].id);
  assert.deepEqual(await f.invoke('choose', list.sources[1].id), { accepted: false });
  f.invoke('cancel'); pending.resolve(choices());
  assert.deepEqual(await selecting, { accepted: false }); assert.deepEqual(f.received, [null]);
});

test('empty and failed enumerations expose recoverable states without auto-selecting', async t => {
  const empty = fixture(t, async () => []); empty.start();
  assert.equal((await empty.invoke('list')).phase, 'empty'); assert.equal(empty.received.length, 0); empty.invoke('cancel');
  const broken = fixture(t, async () => { throw Error('private OS diagnostic'); }); broken.start();
  const status = await broken.invoke('list'); assert.equal(status.phase, 'unavailable');
  assert.equal(JSON.stringify(status).includes('private OS diagnostic'), false); broken.invoke('cancel');
});

test('module shutdown removes handlers, denies pending requests and never enumerates again', async t => {
  const f = fixture(t); f.start(); await f.invoke('list'); f.picker.close(); f.picker.close(); f.start();
  assert.equal(f.handlers.size, 0); assert.deepEqual(f.received, [null, null]); assert.equal(f.calls.length, 1);
});
