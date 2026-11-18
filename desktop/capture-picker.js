'use strict';
(function () {
  const api = window.producerCapturePicker, area = document.getElementById('sources'), share = document.getElementById('shareCapture'), cancel = document.getElementById('cancelCapture'), status = document.getElementById('captureStatus'), selection = document.getElementById('selectionStatus');
  let selected = null, busy = false, cancelling = false;
  async function stop() { if (cancelling) return; cancelling = true; busy = true; share.disabled = true; cancel.disabled = true; try { await api.cancel(); } catch (_) { window.close(); } }
  cancel.addEventListener('click', stop);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); stop(); } });
  share.addEventListener('click', async () => {
    if (busy || !selected) return;
    busy = true; share.disabled = true;
    for (const control of area.querySelectorAll('input')) control.disabled = true;
    status.textContent = 'Checking your selection…';
    try { const result = await api.choose(selected); if (!result?.accepted) status.textContent = 'That source is no longer available. Close this picker and try again.'; }
    catch (_) { status.textContent = 'Screen sharing was cancelled. Close this picker and try again.'; }
    // If native selection failed without closing the window, keep a way out.
    if (!cancelling) { busy = false; cancel.disabled = false; }
  });
  Promise.resolve().then(() => api.list()).then(value => {
    if (busy) return;
    const sources = Array.isArray(value?.sources) ? value.sources : [];
    if (value?.phase !== 'ready' || !sources.length) {
      status.textContent = value?.phase === 'empty' ? 'No screens or windows are available. Open the window you want to share, then try again.' : 'Screens and windows could not be listed. Cancel and try again.';
      return;
    }
    for (const source of sources) {
      const card = document.createElement('label'), radio = document.createElement('input'), preview = document.createElement('span'), title = document.createElement('strong'), kind = document.createElement('span');
      card.className = 'source'; radio.type = 'radio'; radio.name = 'captureSource'; radio.value = source.id;
      preview.className = 'source-preview';
      if (source.thumbnail) { const image = document.createElement('img'); image.src = source.thumbnail; image.alt = ''; preview.append(image); }
      else preview.textContent = 'Preview unavailable';
      title.textContent = source.name; kind.className = 'source-kind'; kind.textContent = source.kind === 'screen' ? 'Entire screen' : 'Window';
      radio.addEventListener('change', () => { if (!busy && radio.checked) { selected = source.id; share.disabled = false; selection.textContent = source.name + ' · video only'; } });
      card.append(radio, preview, title, kind); area.append(card);
    }
    status.textContent = 'Nothing is shared until you select Share video.';
    area.querySelector('input')?.focus();
  }).catch(() => { status.textContent = 'This sharing request expired. Cancel and start again from the studio.'; });
})();
