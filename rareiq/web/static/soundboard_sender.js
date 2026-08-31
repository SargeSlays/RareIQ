/* A bounded snapshot transport preserves Queue/Layer semantics and Stop All. */
(() => {
  const owner = crypto.randomUUID(), players = new Map();
  const enabledControl = document.getElementById('soundboardObsOutput');
  const monitorControl = document.getElementById('soundboardLocalMonitor');
  const status = document.getElementById('soundboardOutputStatus');
  // Routing belongs to this RareIQ installation, not one browser profile.
  let enabled = false, monitor = false, settingsReady = false, revision = -1;
  let settingsBusy = false, settingsSaving = false;
  let sequence = 0, sending = false, dirty = false, closed = false;
  function controls() {
    if (enabledControl) { enabledControl.checked = enabled; enabledControl.disabled = !settingsReady || settingsSaving; }
    if (monitorControl) { monitorControl.checked = monitor; monitorControl.disabled = !settingsReady || settingsSaving; }
  }
  function applySettings(value) {
    if (!value || typeof value.enabled !== 'boolean' || typeof value.local_monitor !== 'boolean' || !Number.isInteger(value.revision) || value.revision < revision) return;
    const changed = !settingsReady || enabled !== value.enabled;
    enabled = value.enabled; monitor = value.local_monitor; revision = value.revision; settingsReady = true;
    for (const [audio, entry] of players) audio.volume = monitor ? entry.volume : 0;
    controls();
    if (changed) publish();
  }
  async function syncSettings() {
    if (settingsBusy || settingsSaving || closed) return;
    settingsBusy = true;
    try {
      const response = await fetch('/api/output/soundboard/settings', {cache:'no-store', signal:AbortSignal.timeout(2500)});
      if (!response.ok) throw new Error('Settings unavailable');
      if (!closed) applySettings(await response.json());
    } catch (_) { if (!closed && !settingsReady && status) status.textContent = 'Audio routing unavailable · retrying connection'; }
    finally { settingsBusy = false; }
  }
  async function saveSettings(change) {
    if (settingsSaving || closed) return;
    settingsSaving = true; controls();
    try {
      const response = await fetch('/api/output/soundboard/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(change), signal:AbortSignal.timeout(2500)});
      if (!response.ok) throw new Error('Settings could not be saved');
      if (!closed) applySettings(await response.json());
    } catch (_) { if (!closed && status) status.textContent = 'Audio routing was not saved · check the RareIQ server'; }
    finally { settingsSaving = false; controls(); }
  }
  function snapshot() {
    return {owner, sequence: ++sequence, voices: enabled ? [...players.entries()].filter(([audio]) => !audio.paused && !audio.ended).map(([audio, entry]) => ({id:entry.id, asset_id:entry.asset, position:audio.currentTime || 0, volume:entry.volume})) : []};
  }
  async function publish() {
    dirty = true;
    if (sending || closed || !settingsReady) return;
    sending = true; dirty = false;
    try {
      const response = await fetch('/api/output/soundboard', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(snapshot()), signal:AbortSignal.timeout(2500)});
      if (!response.ok) throw new Error('Output unavailable');
      const state = await response.json();
      if (!closed) applySettings(state.settings);
      if (status) status.textContent = enabled ? state.receivers ? `Digital output ready · ${state.receivers} audio source${state.receivers === 1 ? '' : 's'} connected` : 'Output enabled · open the Soundboard source in OBS' : 'OBS output off · local playback only';
    } catch (_) { if (status) status.textContent = 'Digital output disconnected · check RareIQ server'; }
    finally { sending = false; if (dirty && !closed) publish(); }
  }
  window.RareIQSoundboardOutput = {
    localVolume: volume => monitor ? volume : 0,
    add(audio, pad, volume) { audio.volume = monitor ? volume : 0; players.set(audio, {id:crypto.randomUUID(), asset:pad.asset_id || pad.asset?.id, volume}); publish(); },
    remove(audio) { players.delete(audio); publish(); },
    volume(volume) { for (const entry of players.values()) entry.volume = volume; if (enabled) publish(); },
  };
  if (enabledControl) enabledControl.onchange = () => saveSettings({enabled:enabledControl.checked});
  if (monitorControl) monitorControl.onchange = () => saveSettings({local_monitor:monitorControl.checked});
  const heartbeat = setInterval(() => { if (enabled) publish(); }, 750);
  const settingsTimer = setInterval(syncSettings, 3000);
  addEventListener('pagehide', () => { closed = true; clearInterval(heartbeat); clearInterval(settingsTimer); navigator.sendBeacon('/api/output/soundboard', new Blob([JSON.stringify({owner,sequence:++sequence,voices:[]})], {type:'application/json'})); });
  controls(); syncSettings();
})();
