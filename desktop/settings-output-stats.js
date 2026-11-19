(function (host) {
  'use strict';
  const COUNTERS = ['frames', 'audioSamples', 'bytesMuxed', 'queuedBytes', 'packets', 'droppedVideoFrames', 'droppedAudioPackets', 'droppedVodAudioPackets'];
  const TOTALS = COUNTERS.filter(key => key !== 'queuedBytes');
  const PHASES = new Set(['idle', 'prepared', 'starting', 'sending', 'stopping', 'failed', 'stopped']);
  const valid = value => Number.isSafeInteger(value) && value >= 0;
  const numeric = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  function normalize(value) {
    const result = {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) return result;
    for (const key of COUNTERS) {
      const candidate = key === 'frames' ? value.frames ?? value.videoFrames : value[key];
      if (valid(candidate)) result[key] = candidate;
    }
    if (['h264_nvenc', 'libx264'].includes(value.codec)) result.codec = value.codec;
    return result;
  }
  function createModel({now = () => performance.now(), staleMs = 3000} = {}) {
    if (typeof now !== 'function' || !Number.isInteger(staleMs) || staleMs < 500 || staleMs > 30000) throw Error('invalid_output_stats_configuration');
    let counters = {}, active = false, attempted = false, phase = 'idle', baseline = null, changedAt = null;
    let rates = {recentFps: null, encodedKbps: null}, state = 'idle';
    function snapshot() {
      const drops = ['droppedVideoFrames', 'droppedAudioPackets', 'droppedVodAudioPackets'].filter(key => valid(counters[key]));
      const sum = drops.reduce((total, key) => total + counters[key], 0);
      return {state, active, phase, counters: {...counters}, metrics: {
        encodedBytes: counters.bytesMuxed ?? null, queueBytes: counters.queuedBytes ?? null,
        inputDrops: drops.length && valid(sum) ? sum : null, ...rates,
      }};
    }
    return {
      observe(value, timestamp = now()) {
        if (!numeric(timestamp)) { rates = {recentFps: null, encodedKbps: null}; state = attempted ? 'unavailable' : 'idle'; return snapshot(); }
        const next = normalize(value), nextPhase = PHASES.has(value?.phase) ? value.phase : 'idle';
        const nextActive = value?.active === true || ['starting', 'sending', 'stopping'].includes(nextPhase);
        const newAttempt = nextActive && (!active || nextPhase === 'starting' && phase !== 'starting');
        const regression = nextActive && TOTALS.some(key => valid(counters[key]) && valid(next[key]) && next[key] < counters[key]);
        if (newAttempt || regression) { counters = {}; baseline = null; changedAt = null; rates = {recentFps: null, encodedKbps: null}; }
        const progressed = TOTALS.some(key => valid(next[key]) && next[key] !== counters[key]);
        if (nextActive) {
          attempted = true;
          counters = {...counters, ...next};
          if (progressed || changedAt === null) changedAt = timestamp;
          const elapsed = baseline ? timestamp - baseline.time : null;
          const fresh = changedAt !== null && timestamp - changedAt <= staleMs;
          rates = {recentFps: null, encodedKbps: null};
          if (baseline && elapsed >= 250 && elapsed <= staleMs && fresh) {
            if (valid(counters.frames) && valid(baseline.counters.frames)) rates.recentFps = (counters.frames - baseline.counters.frames) * 1000 / elapsed;
            if (valid(counters.bytesMuxed) && valid(baseline.counters.bytesMuxed)) rates.encodedKbps = (counters.bytesMuxed - baseline.counters.bytesMuxed) * 8 / elapsed;
          }
          if (!baseline || elapsed >= 250 || elapsed <= 0) baseline = {time: timestamp, counters: {...counters}};
          if (!fresh) baseline = null;
          state = fresh ? (regression ? 'reset' : 'active') : 'stale';
        } else {
          // Idle/prepared polls may omit or reset counters. Preserve the actual
          // last attempt until a subsequent active edge starts a new attempt.
          if (attempted) for (const [key, amount] of Object.entries(next)) {
            if (key === 'codec' || key === 'queuedBytes' || !valid(counters[key]) || amount >= counters[key]) counters[key] = amount;
          }
          rates = {recentFps: null, encodedKbps: null}; baseline = null;
          state = attempted ? 'last_attempt' : 'idle';
        }
        active = nextActive; phase = nextPhase;
        return snapshot();
      },
      snapshot,
    };
  }
  const MESSAGES = {
    idle: 'Statistics appear after native encoding starts.', active: 'Current local encoder counters.',
    stale: 'No recent encoder progress. Counters may be stale.', reset: 'Encoder counters restarted. Measuring rates again.',
    last_attempt: 'Last encoder attempt. Recent rates are unavailable after Stop.', unavailable: 'Recent encoder timing is unavailable.',
  };
  const bytes = value => {
    if (!valid(value)) return 'Unavailable';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let amount = value, unit = 0;
    while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit++; }
    return (unit ? amount.toFixed(1) : String(amount)) + ' ' + units[unit];
  };
  function render(root, snapshot) {
    const metrics = snapshot?.metrics || {};
    const values = {encodedBytes: bytes(metrics.encodedBytes), queueBytes: bytes(metrics.queueBytes),
      inputDrops: valid(metrics.inputDrops) ? metrics.inputDrops.toLocaleString('en-US') : 'Unavailable',
      recentFps: numeric(metrics.recentFps) ? metrics.recentFps.toFixed(1) + ' fps' : 'Unavailable',
      encodedKbps: numeric(metrics.encodedKbps) ? metrics.encodedKbps.toFixed(0) + ' kbps' : 'Unavailable'};
    for (const [key, value] of Object.entries(values)) {
      const output = root.querySelector('[data-output-stat="' + key + '"]');
      if (output) output.textContent = value;
    }
    const state = root.querySelector('[data-output-stats-state]');
    if (state) state.textContent = MESSAGES[snapshot?.state] || MESSAGES.unavailable;
    return values;
  }
  function mount({root, now, staleMs} = {}) {
    if (!root || typeof root.querySelector !== 'function') throw Error('output_stats_host_required');
    const model = createModel({...(now ? {now} : {}), ...(staleMs === undefined ? {} : {staleMs})});
    const cards = [['encodedBytes', 'Encoded bytes'], ['queueBytes', 'Encoder queue'], ['inputDrops', 'Input drops'], ['recentFps', 'Recent frame rate'], ['encodedKbps', 'Recent encoded bitrate']];
    root.innerHTML = '<div class="pp-output-stats"><h3>Native output statistics</h3><p data-output-stats-state role="status"></p><dl class="pp-output-stats-grid">' +
      cards.map(([key, label]) => '<div class="pp-output-stat"><dt>' + label + '</dt><dd><output data-output-stat="' + key + '">Unavailable</output></dd></div>').join('') +
      '</dl><p class="pp-output-stats-note">Local encoder counters only. Encoded bytes are not network delivery acknowledgments. CPU, GPU and platform receipt are not measured here.</p></div>';
    let destroyed = false;
    render(root, model.snapshot());
    return {update(value) { if (destroyed) return model.snapshot(); const snapshot = model.observe(value); render(root, snapshot); return snapshot; },
      destroy() { destroyed = true; }, model};
  }
  const api = Object.freeze({normalize, createModel, render, mount});
  if (typeof module === 'object' && module.exports) module.exports = api;
  else host.ProducerOutputStats = api;
})(typeof globalThis === 'object' ? globalThis : this);
