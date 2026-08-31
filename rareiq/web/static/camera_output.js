/* OBS subscribes to RareIQ's capture owners, never to getUserMedia. */
(() => {
  const mode = location.pathname.split('/').pop();
  const stage = document.querySelector('main');
  const views = new Map();
  let stopped = false, timer, socket, lastMessage = Date.now();
  document.body.classList.toggle('preview', new URLSearchParams(location.search).has('preview'));
  stage.classList.toggle('quad', mode === 'all');
  function clear(view) { view.image.classList.remove('live'); view.image.removeAttribute('src'); for (const url of new Set([view.current,view.pending])) if (url) URL.revokeObjectURL(url); view.current = view.pending = ''; }
  function create(slot) {
    const figure = document.createElement('figure'), image = document.createElement('img'), label = document.createElement('figcaption');
    image.alt = `Camera ${slot}`; figure.append(image, label); stage.append(figure);
    const view = {figure, image, label, current:'', pending:''};
    image.onload = () => { if (view.current && view.current !== view.pending) URL.revokeObjectURL(view.current); view.current = view.pending; image.classList.add('live'); };
    image.onerror = () => { clear(view); label.textContent = `Camera ${slot} · reconnecting`; };
    return view;
  }
  function reconcile(state) {
      const slots = mode === 'all' ? [1,2,3,4] : [mode === 'scan' ? state.active_slot : Number(mode)];
      for (const [slot, view] of views) if (!slots.includes(slot)) { clear(view); view.figure.remove(); views.delete(slot); }
      for (const slot of slots) {
        const camera = state.slots.find(item => item.slot_id === slot);
        const view = views.get(slot) || create(slot); views.set(slot, view);
        view.label.textContent = `Camera ${slot} · ${camera?.source_id ? camera.connected ? camera.display_name || 'Live' : 'Waiting for camera' : 'Unassigned — choose a source in RareIQ'}`;
        if (!camera?.source_id) { clear(view); continue; }
        if (!camera.connected || camera.frame_age_seconds > 2) view.image.classList.remove('live');
      }
  }
  function disconnected() { for (const view of views.values()) { clear(view); view.label.textContent = 'RareIQ disconnected · reconnecting'; } }
  function connect() {
    if (stopped) return;
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/output/camera/${encodeURIComponent(mode)}`);
    socket.binaryType = 'arraybuffer';
    socket.onmessage = event => {
      lastMessage = Date.now();
      if (typeof event.data === 'string') { try { reconcile(JSON.parse(event.data)); } catch (_) { disconnected(); } return; }
      const data = new Uint8Array(event.data), view = views.get(data[0]);
      if (!view || data.length < 2) return;
      if (view.pending && view.pending !== view.current) URL.revokeObjectURL(view.pending);
      view.pending = URL.createObjectURL(new Blob([data.subarray(1)], {type:'image/jpeg'}));
      view.image.src = view.pending;
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => { disconnected(); if (!stopped) timer = setTimeout(connect, 1000); };
  }
  const watchdog = setInterval(() => { if (Date.now() - lastMessage > 3000) { disconnected(); socket?.close(); } }, 1000);
  addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); clearInterval(watchdog); socket?.close(); disconnected(); });
  connect();
})();
