(function(root) {
  'use strict';
  class SoundboardReceiver {
    constructor(AudioType, report = () => {}) { this.AudioType = AudioType; this.report = report; this.players = new Map(); this.completed = new Set(); this.blocked = new Set(); }
    stop(id) { const entry = this.players.get(id); if (!entry) return; entry.cancelled = true; entry.audio.pause(); entry.audio.removeAttribute('src'); entry.audio.load(); entry.audio.remove?.(); this.players.delete(id); }
    silence() { for (const id of [...this.players.keys()]) this.stop(id); }
    sync(voices) {
      const ids = new Set(voices.map(voice => voice.id));
      for (const id of [...this.players.keys()]) if (!ids.has(id)) this.stop(id);
      for (const voice of voices) {
        if (this.completed.has(voice.id) || this.blocked.has(voice.id)) continue;
        const existing = this.players.get(voice.id);
        if (existing) { existing.audio.volume = voice.volume; continue; }
        // Server supplies only registered local audio assets. Never load arbitrary URLs.
        if (!/^\/api\/creator\/assets\/[a-zA-Z0-9_-]+$/.test(voice.url)) continue;
        const audio = new this.AudioType(voice.url), entry = {audio, cancelled: false};
        this.players.set(voice.id, entry); audio.volume = voice.volume;
        if (typeof document !== 'undefined') { audio.hidden = true; audio.dataset.playbackId = voice.id; document.body.append(audio); }
        const finish = () => { this.completed.add(voice.id); while (this.completed.size > 256) this.completed.delete(this.completed.values().next().value); this.stop(voice.id); };
        audio.addEventListener('ended', finish, {once:true});
        audio.addEventListener('error', () => { finish(); this.report('Audio asset unavailable'); }, {once:true});
        audio.addEventListener('loadedmetadata', () => {
          if (entry.cancelled) return;
          if (Number.isFinite(audio.duration) && voice.position >= audio.duration) { finish(); return; }
          audio.currentTime = voice.position;
          audio.play().then(() => { if (!entry.cancelled) this.report(`Playing ${this.players.size} sound${this.players.size === 1 ? '' : 's'} · digital output active`); }).catch(error => { if (!entry.cancelled) { this.blocked.add(voice.id); while (this.blocked.size > 256) this.blocked.delete(this.blocked.values().next().value); this.stop(voice.id); this.report(`Audio blocked (${error.name}) — click Enable preview audio`); } });
        }, {once:true});
        audio.load();
      }
    }
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = {SoundboardReceiver}; return; }
  root.RareIQSoundboardReceiver = SoundboardReceiver;
  document.body.classList.toggle('preview', new URLSearchParams(location.search).has('preview'));
  const status = document.getElementById('status'), report = text => { status.textContent = text; };
  const receiver = new SoundboardReceiver(Audio, report);
  const events = new EventSource('/api/output/soundboard/events');
  let lastEvent = Date.now();
  events.onmessage = event => {
    try { const state = JSON.parse(event.data); lastEvent = Date.now(); receiver.sync(state.voices || []); if (!state.voices.length) report('Connected · waiting for soundboard playback'); }
    catch (_) { receiver.silence(); report('Audio state unavailable'); }
  };
  events.onerror = () => { receiver.silence(); report('RareIQ disconnected · audio stopped'); };
  const watchdog = setInterval(() => { if (Date.now() - lastEvent > 1500) receiver.silence(); }, 500);
  document.getElementById('enableAudio').onclick = () => { receiver.blocked.clear(); report('Preview enabled · play a pad in RareIQ'); };
  addEventListener('pagehide', () => { clearInterval(watchdog); events.close(); receiver.silence(); });
})(typeof window !== 'undefined' ? window : globalThis);
