'use strict';

const fail = code => Object.assign(Error(code), {code});
const PURPOSES = new Set(['broadcast', 'recording', 'rehearsal']);

// All leases observe the same physical Program capture. A slow or failed sink
// loses only its own lease; its promise is never returned to the raw PCM source.
function createSharedOutputCapture({capture, maxVideoFrames = 2, maxAudioPackets = 64, deliveryTimeoutMs = 2000} = {}) {
  if (!capture || !['startCapture', 'stopCapture', 'status', 'close'].every(key => typeof capture[key] === 'function') ||
      !Number.isInteger(maxVideoFrames) || maxVideoFrames < 1 || maxVideoFrames > 8 ||
      !Number.isInteger(maxAudioPackets) || maxAudioPackets < 1 || maxAudioPackets > 256 ||
      !Number.isInteger(deliveryTimeoutMs) || deliveryTimeoutMs < 10 || deliveryTimeoutMs > 10000)
    throw fail('invalid_shared_output_capture');
  const leases = new Map(), runs = new Set();
  let physical = false, epoch = 0, closed = false, rawClosed = false, closing = null, stopUnconfirmed = false, tail = Promise.resolve();
  const serialize = operation => {
    const work = tail.then(operation);
    tail = work.catch(() => {});
    return work;
  };
  const live = run => !run.cancelled && run.lease.run === run;
  function detach(run) {
    if (!run || run.cancelled) return;
    run.cancelled = true;
    run.queue.length = 0;
    clearTimeout(run.timer);
    run.cancelDelivery?.();
    runs.delete(run);
    if (run.lease.run === run) run.lease.run = null;
  }
  async function stopIfUnused() {
    if (runs.size || !physical) return;
    ++epoch;
    stopUnconfirmed = true;
    await capture.stopCapture();
    physical = false;
    stopUnconfirmed = false;
  }
  function closeManager() {
    if (rawClosed) return Promise.resolve(true);
    if (closing) return closing;
    // Closing retires the singleton IPC owner, including its inactive facades.
    // Admit no new leases while asynchronous physical cleanup is pending.
    closed = true;
    for (const lease of leases.values()) lease.closed = true;
    const work = serialize(async () => {
      await stopIfUnused();
      await capture.close();
      rawClosed = true;
      return true;
    });
    const result = work.finally(() => { if (closing === result) closing = null; });
    closing = result;
    return result;
  }
  function fault(run, code) {
    if (!live(run)) return;
    run.lease.fault = code;
    detach(run);
    void serialize(stopIfUnused).catch(() => {});
    try { Promise.resolve(run.lease.onFault(code)).catch(() => {}); } catch (_) {}
  }
  function schedule(run) {
    if (!live(run) || run.busy || run.scheduled || !run.queue.length) return;
    run.scheduled = true;
    setImmediate(() => { run.scheduled = false; deliver(run); });
  }
  function deliver(run) {
    if (!live(run) || run.busy || !run.queue.length) return;
    const item = run.queue.shift();
    run[item.kind === 'video' ? 'videos' : 'audios']--;
    run.busy = true;
    let result;
    try { result = item.kind === 'video' ? run.onVideo(item.bytes, item.pts) : run.onAudio(item.bytes, item.pts, item.vod); }
    catch (_) { run.busy = false; fault(run, 'output_' + item.kind + '_sink_failed'); return; }
    const timeout = new Promise((_, reject) => {
      run.timer = setTimeout(() => reject(fail('encoder_backpressure')), deliveryTimeoutMs);
      run.timer.unref?.();
    });
    const cancelled = new Promise(resolve => { run.cancelDelivery = resolve; });
    Promise.race([Promise.resolve(result), timeout, cancelled]).then(accepted => {
      if (!live(run)) return;
      if (accepted === false) fault(run, 'encoder_backpressure');
      else run[item.kind === 'video' ? 'capturedFrames' : 'audioPackets']++;
    }, error => {
      if (live(run)) fault(run, error?.code === 'encoder_backpressure' ? error.code : 'output_' + item.kind + '_sink_failed');
    }).finally(() => { clearTimeout(run.timer); run.cancelDelivery = null; run.busy = false; schedule(run); });
  }
  function enqueue(run, kind, bytes, pts, vod) {
    if (!live(run)) return;
    if (!Buffer.isBuffer(bytes) || !Number.isSafeInteger(pts) || pts < 0 || vod !== undefined && !Buffer.isBuffer(vod)) {
      fault(run, 'output_' + kind + '_sink_failed'); return;
    }
    if (kind === 'audio') {
      if (run.origin === null) run.origin = pts;
      if (pts <= run.lastAudio) { fault(run, 'output_audio_protocol_invalid'); return; }
      run.lastAudio = pts;
    } else if (run.origin === null || pts < run.origin || pts <= run.lastVideo) { run.droppedFrames++; return; }
    else run.lastVideo = pts;
    const field = kind === 'video' ? 'videos' : 'audios', limit = kind === 'video' ? maxVideoFrames : maxAudioPackets;
    if (run[field] >= limit) {
      if (kind === 'video') run.droppedFrames++;
      else fault(run, 'encoder_backpressure');
      return;
    }
    run[field]++;
    run.queue.push({kind, bytes: Buffer.from(bytes), pts: pts - run.origin, ...(vod === undefined ? {} : {vod: Buffer.from(vod)})});
    schedule(run);
  }
  function fanout(kind, bytes, pts, vod, generation) {
    if (!physical || generation !== epoch) return true;
    for (const run of [...runs]) enqueue(run, kind, bytes, pts, vod);
    return true;
  }
  function forConsumer(purpose, {onFault = () => {}} = {}) {
    if (!PURPOSES.has(purpose) || typeof onFault !== 'function' || closed) throw fail('invalid_shared_output_consumer');
    const existing = leases.get(purpose);
    if (existing && !existing.closed) { existing.onFault = onFault; return existing.facade; }
    const lease = {purpose, onFault, run: null, fault: null, closed: false, last: null};
    function status() {
      const raw = capture.status(), run = lease.run || lease.last;
      return {...raw, capturing: Boolean(lease.run), error: lease.fault || raw.error,
        capturedFrames: run?.capturedFrames || 0, droppedFrames: run?.droppedFrames || 0,
        audioPackets: run?.audioPackets || 0, droppedAudioPackets: 0};
    }
    const facade = lease.facade = {
      status,
      get window() { return capture.window; },
      startCapture(onVideo, onAudio) {
        if (closed || lease.closed || typeof onVideo !== 'function' || typeof onAudio !== 'function') return Promise.reject(fail('output_capture_closed'));
        if (lease.run) return Promise.reject(fail('output_capture_active'));
        const run = {lease, onVideo, onAudio, origin: null, lastAudio: -1, lastVideo: -1, queue: [], videos: 0, audios: 0,
          capturedFrames: 0, audioPackets: 0, droppedFrames: 0, cancelled: false, busy: false, scheduled: false, timer: null};
        lease.fault = null; lease.run = lease.last = run; runs.add(run);
        return serialize(async () => {
          if (!live(run)) throw fail('output_capture_cancelled');
          if (stopUnconfirmed) { detach(run); throw fail('capture_stop_unconfirmed'); }
          if (!physical) {
            const generation = ++epoch; physical = true;
            try { await capture.startCapture((bytes, pts) => fanout('video', bytes, pts, undefined, generation),
              (bytes, pts, vod) => fanout('audio', bytes, pts, vod, generation)); }
            catch (error) {
              // A failed physical start cannot leave a queued second consumer
              // attached to callbacks belonging to a capture that never started.
              for (const affected of [...runs]) {
                detach(affected);
                if (affected !== run) {
                  affected.lease.fault = 'output_receiver_unavailable';
                  try { Promise.resolve(affected.lease.onFault('output_receiver_unavailable')).catch(() => {}); } catch (_) {}
                }
              }
              try { await stopIfUnused(); } catch (_) { throw fail('capture_stop_unconfirmed'); }
              throw error;
            }
          }
          if (!live(run)) { await stopIfUnused(); throw fail('output_capture_cancelled'); }
          return status();
        });
      },
      stopCapture() { detach(lease.run); return serialize(stopIfUnused); },
      async close() {
        if ([...runs].some(run => run.lease !== lease)) throw fail('output_capture_in_use');
        detach(lease.run);
        return closeManager();
      },
    };
    for (const method of ['prepare', 'review', 'show', 'updateAudioRouting', 'waitForRehearsal', 'setMonitor'])
      if (typeof capture[method] === 'function') facade[method] = (...args) => {
        if (closed || lease.closed) throw fail('output_capture_closed');
        // Raw prepare refreshes its saved routing. Joining a running output must
        // preserve the actual runtime mix already heard by the other consumer.
        if (method === 'prepare' && physical) return Promise.resolve(status());
        return capture[method](...args);
      };
    leases.set(purpose, lease);
    return facade;
  }
  return {
    forConsumer,
    status: () => ({capturing: physical, ownershipPending: stopUnconfirmed, consumers: [...runs].map(run => run.lease.purpose)}),
    async close() {
      if (runs.size) return false;
      return closeManager();
    },
  };
}

module.exports = {createSharedOutputCapture};
