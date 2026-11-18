'use strict';
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { randomUUID } = require('node:crypto');

const CHANNELS = Object.freeze({ list: 'producer:capture:list', choose: 'producer:capture:choose', cancel: 'producer:capture:cancel' });
const genericError = () => new Error('capture_picker_untrusted');

function createCapturePicker({ BrowserWindow, ipcMain, desktopCapturer, studio, origin, baseDir = __dirname } = {}) {
  if (!BrowserWindow || !ipcMain || !desktopCapturer || !studio || !path.isAbsolute(baseDir)) throw Error('capture_picker_configuration_required');
  const trustedOrigin = new URL(origin).origin;
  if (trustedOrigin !== origin || !/^https?:$/.test(new URL(origin).protocol)) throw Error('capture_picker_origin_invalid');
  const pickerPath = path.join(baseDir, 'capture-picker.html'), pickerUrl = pathToFileURL(pickerPath).href;
  let active = null, closed = false;

  function trustedRequest(request) {
    try {
      const contents = studio.webContents, frame = request?.frame;
      return !closed && !studio.isDestroyed() && !contents.isDestroyed() && frame !== null && frame !== undefined
        && frame === contents.mainFrame && request.securityOrigin === trustedOrigin
        && new URL(frame.url).origin === trustedOrigin && new URL(contents.getURL()).origin === trustedOrigin
        && request.videoRequested === true && request.userGesture === true;
    } catch (_) { return false; }
  }
  function isCurrent(state) { return active === state && !state.done && trustedRequest(state.request); }
  function finish(state, grant = null) {
    if (!state || state.done) return;
    state.done = true;
    if (active === state) active = null;
    clearTimeout(state.timer);
    for (const dispose of state.cleanup) dispose();
    state.cleanup.length = 0;
    state.sources.clear(); state.items.length = 0;
    try { if (state.window && !state.window.isDestroyed()) state.window.destroy(); } catch (_) {}
    // A navigated/destroyed request may make Electron throw. Do not retry it.
    try { state.callback(grant); } catch (_) {}
  }
  function trustedPicker(event) {
    const state = active;
    try {
      if (!state || !isCurrent(state) || !state.window || state.window.isDestroyed()) throw genericError();
      const contents = state.window.webContents;
      if (event.sender !== contents || event.senderFrame !== contents.mainFrame || event.senderFrame.url !== pickerUrl
          || contents.getURL() !== pickerUrl) throw genericError();
      return state;
    } catch (_) { throw genericError(); }
  }
  function listen(state, target, name, fn) {
    target.on(name, fn);
    state.cleanup.push(() => target.removeListener(name, fn));
  }
  function publicSource(source) {
    if (typeof source?.id !== 'string' || !/^(screen|window):\d+:\d+$/.test(source.id) || typeof source.name !== 'string') return null;
    let thumbnail = '';
    try {
      const data = source.thumbnail?.toDataURL();
      if (typeof data === 'string' && data.length <= 2 * 1024 * 1024 && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(data)) thumbnail = data;
    } catch (_) {}
    return { id: randomUUID(), name: source.name.replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 160) || 'Untitled window',
      kind: source.id.startsWith('screen:') ? 'screen' : 'window', thumbnail };
  }
  async function enumerate(state) {
    try {
      const sources = await desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 320, height: 180 }, fetchWindowIcons: false });
      if (!isCurrent(state)) { finish(state); return; }
      if (!Array.isArray(sources)) throw Error('invalid_sources');
      const seen = new Set();
      for (const source of sources.slice(0, 256)) {
        const item = publicSource(source);
        if (!item || seen.has(source.id)) continue;
        seen.add(source.id);
        state.sources.set(item.id, { id: source.id, name: source.name });
        state.items.push(item);
      }
      state.phase = state.items.length ? 'ready' : 'empty';
    } catch (_) {
      if (isCurrent(state)) state.phase = 'unavailable';
      else finish(state);
    }
  }
  function handler(request, callback) {
    if (typeof callback !== 'function') return;
    const deny = () => { try { callback(null); } catch (_) {} };
    if (!trustedRequest(request)) { deny(); return; }
    // Repeated capture requests cannot race a previously displayed decision.
    if (active) { finish(active); deny(); return; }
    const state = { request, callback, done: false, window: null, sources: new Map(), items: [], cleanup: [], phase: 'loading', granting: false, timer: null };
    active = state;
    state.timer = setTimeout(() => finish(state), 120000); state.timer.unref?.();
    try {
      const contents = studio.webContents;
      listen(state, contents, 'did-start-navigation', (_event, _url, _inPlace, isMainFrame) => { if (isMainFrame !== false) finish(state); });
      listen(state, contents, 'destroyed', () => finish(state));
      listen(state, contents, 'render-process-gone', () => finish(state));
      listen(state, studio, 'closed', () => finish(state));
      state.ready = enumerate(state);
      const window = state.window = new BrowserWindow({
        width: 900, height: 740, minWidth: 480, minHeight: 440, parent: studio, modal: true, show: false,
        title: 'Choose a screen or window — Producer, Please', autoHideMenuBar: true,
        webPreferences: { preload: path.join(baseDir, 'capture-preload.cjs'), partition: 'producer-capture-' + randomUUID(),
          sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, allowRunningInsecureContent: false, webviewTag: false },
      });
      window.setMenu?.(null);
      window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      window.webContents.session?.setPermissionCheckHandler(() => false);
      window.webContents.session?.setPermissionRequestHandler((_contents, _permission, reply) => reply(false));
      window.webContents.session?.setDisplayMediaRequestHandler((_request, reply) => reply(null));
      window.webContents.session?.on('will-download', event => event.preventDefault());
      listen(state, window.webContents, 'will-navigate', event => { event.preventDefault(); finish(state); });
      listen(state, window.webContents, 'will-attach-webview', event => event.preventDefault());
      listen(state, window.webContents, 'render-process-gone', () => finish(state));
      listen(state, window.webContents, 'destroyed', () => finish(state));
      listen(state, window, 'closed', () => finish(state));
      listen(state, window, 'ready-to-show', () => { if (isCurrent(state)) { window.show(); window.focus(); } });
      Promise.resolve(window.loadFile(pickerPath)).catch(() => finish(state));
    } catch (_) { finish(state); }
  }
  ipcMain.handle(CHANNELS.list, async event => {
    const state = trustedPicker(event);
    await state.ready;
    if (trustedPicker(event) !== state) throw genericError();
    return { phase: state.phase, audioIncluded: false, sources: state.items.map(item => ({ ...item })) };
  });
  ipcMain.handle(CHANNELS.choose, async (event, choice) => {
    const state = trustedPicker(event);
    if (state.granting) return { accepted: false };
    const selected = typeof choice === 'string' ? state.sources.get(choice) : null;
    if (!selected || state.phase !== 'ready') { finish(state); return { accepted: false }; }
    state.granting = true;
    try {
      // Closed/replaced windows must not be granted using an old native handle.
      const current = await desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 0, height: 0 }, fetchWindowIcons: false });
      if (!isCurrent(state)) { finish(state); return { accepted: false }; }
      trustedPicker(event);
      const source = Array.isArray(current) && current.find(item => item.id === selected.id && item.name === selected.name);
      if (!source) { finish(state); return { accepted: false }; }
      finish(state, { video: { id: selected.id, name: selected.name } });
      return { accepted: true };
    } catch (_) { finish(state); return { accepted: false }; }
  });
  ipcMain.handle(CHANNELS.cancel, event => { const state = trustedPicker(event); finish(state); return { cancelled: true }; });
  return { handler, close() { if (closed) return; closed = true; finish(active); for (const channel of Object.values(CHANNELS)) ipcMain.removeHandler(channel); } };
}

module.exports = { createCapturePicker, CHANNELS };
