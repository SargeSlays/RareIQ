'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createSharedOutputCapture} = require('../shared-output-capture.cjs');
const turn = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let n = 0; n < 12; n++) await turn(); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };

test('replay survives independent recording and broadcast stops on one physical Program capture',async()=>{
 const f=fixture(),replay=f.shared.forConsumer('replay'),received=[];
 await Promise.all([f.broadcast.startCapture(()=>true,()=>true),f.recording.startCapture(()=>true,()=>true),replay.startCapture((_b,p)=>{received.push(p);return true;},()=>true)]);
 f.audio(Buffer.alloc(1920),0);f.video(Buffer.from('generated'),10000);await settle();assert.equal(f.starts,1);assert.equal(received.length,1);
 await f.broadcast.stopCapture();await f.recording.stopCapture();assert.equal(f.stops,0);f.audio(Buffer.alloc(1920),20000);f.video(Buffer.from('generated2'),30000);await settle();assert.equal(received.length,2);
 await replay.stopCapture();assert.equal(f.stops,1);await f.shared.close();assert.equal(f.closes,1);
});
function fixture(options = {}) {
  const f = {starts: 0, stops: 0, closes: 0, prepares: 0, prepare: deferred()};
  f.raw = {status: () => ({prepared: true, capturing: f.starts > f.stops, error: null}), prepare: async () => { f.prepares++; },
    startCapture: async (video, audio) => { f.starts++; f.video = video; f.audio = audio; },
    stopCapture: async () => { f.stops++; }, close: () => { f.closes++; }, show: () => 'shown', review: async () => 'reviewed',
    updateAudioRouting: value => value, waitForRehearsal: value => value, setMonitor: value => value};
  f.shared = createSharedOutputCapture({capture: f.raw, ...options});
  f.broadcast = f.shared.forConsumer('broadcast'); f.recording = f.shared.forConsumer('recording');
  return f;
}

test('one physical capture survives stopping and closing either independent consumer', async () => {
  const f = fixture(), broadcast = [], recording = [];
  await f.broadcast.prepare(); assert.equal(f.prepares, 1);
  await f.broadcast.startCapture((...args) => broadcast.push(args), () => true);
  await f.recording.prepare(); assert.equal(f.prepares, 1);
  await f.recording.startCapture((...args) => recording.push(args), () => true);
  assert.equal(f.starts, 1); assert.equal(await f.shared.close(), false);
  f.audio(Buffer.from([1]), 5000000, Buffer.from([2])); f.video(Buffer.from([3]), 5010000); await settle();
  assert.equal(broadcast.length, 1); assert.equal(recording.length, 1);
  await assert.rejects(f.broadcast.close(), /output_capture_in_use/);
  assert.equal(f.broadcast.status().capturing, true); assert.equal(f.recording.status().capturing, true);
  await f.broadcast.stopCapture(); assert.equal(f.stops, 0); assert.equal(f.closes, 0);
  f.video(Buffer.from([4]), 5020000); await settle(); assert.equal(recording.length, 2);
  await f.recording.stopCapture(); assert.equal(f.stops, 1);
  await f.recording.close(); assert.equal(f.closes, 1);
});

test('joining a long-running output rebases from first paired audio without interval clamping', async () => {
  const f = fixture(), first = [], second = [], video = [];
  await f.broadcast.startCapture(() => true, (_bytes, pts) => { first.push(pts); return true; });
  f.video(Buffer.from([1]), 0); f.audio(Buffer.from([2]), 0, Buffer.from([3])); await settle();
  await f.recording.startCapture((_bytes, pts) => { video.push(pts); return true; }, (bytes, pts, vod) => { second.push({pts, live: bytes[0], vod: vod[0]}); return true; });
  f.video(Buffer.from([1]), 9000000); // No audio origin for this lease yet.
  f.audio(Buffer.from([4]), 9010000, Buffer.from([5]));
  f.video(Buffer.from([1]), 9005000); // Before its first audio timestamp.
  f.video(Buffer.from([1]), 9033333);
  f.audio(Buffer.from([6]), 9020000, Buffer.from([7])); await settle();
  assert.deepEqual(second, [{pts: 0, live: 4, vod: 5}, {pts: 10000, live: 6, vod: 7}]);
  assert.deepEqual(video, [23333]); assert.deepEqual(first, [0, 9010000, 9020000]);
  await f.broadcast.stopCapture(); await f.recording.stopCapture(); await f.shared.close();
});

test('slow recording backpressure cannot stall broadcast or retain unbounded media', async () => {
  const f = fixture({maxAudioPackets: 2}), blocked = deferred(), faults = [], broadcast = [];
  f.recording = f.shared.forConsumer('recording', {onFault: code => faults.push(code)});
  await f.broadcast.startCapture(() => true, (_bytes, pts) => { broadcast.push(pts); return true; });
  await f.recording.startCapture(() => true, () => blocked.promise);
  f.audio(Buffer.from([1]), 0); await settle();
  for (let n = 1; n <= 4; n++) { assert.equal(f.audio(Buffer.from([n]), n * 10000), true); await settle(); }
  assert.deepEqual(faults, ['encoder_backpressure']); assert.equal(f.recording.status().capturing, false);
  assert.deepEqual(broadcast, [0, 10000, 20000, 30000, 40000]); assert.equal(f.stops, 0);
  blocked.resolve(true); await settle(); await f.broadcast.stopCapture(); assert.equal(f.stops, 1);
  await f.shared.close();
});

test('sink throw, rejection and timeout fault only the affected lease', async () => {
  for (const sink of [() => { throw Error('private path'); }, () => Promise.reject(Error('private path')), () => new Promise(() => {})]) {
    const f = fixture({deliveryTimeoutMs: 15}), faults = [];
    f.recording = f.shared.forConsumer('recording', {onFault: code => faults.push(code)});
    await f.broadcast.startCapture(() => true, () => true); await f.recording.startCapture(() => true, sink);
    f.audio(Buffer.from([1]), 0); await settle(); await new Promise(resolve => setTimeout(resolve, 25)); await settle();
    assert.equal(faults.length, 1); assert.ok(['output_audio_sink_failed', 'encoder_backpressure'].includes(faults[0]));
    assert.equal(f.broadcast.status().capturing, true); assert.equal(f.stops, 0);
    assert.doesNotMatch(JSON.stringify(f.recording.status()), /private path/);
    await f.broadcast.stopCapture(); await f.shared.close();
  }
});

test('consumer buffers are isolated and stale callbacks cannot feed a later run', async () => {
  const f = fixture(), observed = [];
  await f.broadcast.startCapture(bytes => { bytes[0] = 99; return true; }, () => true);
  await f.recording.startCapture(bytes => { observed.push(bytes[0]); return true; }, () => true);
  const stale = {audio: f.audio, video: f.video};
  f.audio(Buffer.from([1]), 0); f.video(Buffer.from([5]), 10000); await settle(); assert.deepEqual(observed, [5]);
  await f.broadcast.stopCapture(); await f.recording.stopCapture();
  await f.recording.startCapture(bytes => { observed.push(bytes[0]); return true; }, () => true);
  stale.audio(Buffer.from([1]), 0); stale.video(Buffer.from([8]), 10000); await settle(); assert.deepEqual(observed, [5]);
  f.audio(Buffer.from([1]), 100000); f.video(Buffer.from([7]), 110000); await settle(); assert.deepEqual(observed, [5, 7]);
  await f.recording.stopCapture(); await f.shared.close();
});

test('stop during physical startup waits, cancels late start and retains uncertain stop ownership', async () => {
  const f = fixture(), start = deferred();
  f.raw.startCapture = async () => { f.starts++; await start.promise; };
  const starting = f.broadcast.startCapture(() => true, () => true); starting.catch(() => {});
  await turn(); const stopping = f.broadcast.stopCapture(); start.resolve();
  await stopping; await assert.rejects(starting, /output_capture_cancelled/); assert.equal(f.stops, 1);
  f.raw.startCapture = async () => { f.starts++; };
  await f.broadcast.startCapture(() => true, () => true);
  f.raw.stopCapture = async () => { throw Error('synthetic failure'); };
  await assert.rejects(f.broadcast.stopCapture());
  await assert.rejects(f.recording.startCapture(() => true, () => true), /capture_stop_unconfirmed/);
  f.raw.stopCapture = async () => { f.stops++; };
  await f.broadcast.stopCapture(); await f.shared.close();
});

test('physical startup failure cancels all queued consumers and permits clean retry', async () => {
  const f = fixture(), pending = deferred(), faults = [];
  f.recording = f.shared.forConsumer('recording', {onFault: code => faults.push(code)});
  f.raw.startCapture = async () => { f.starts++; await pending.promise; throw Error('synthetic physical failure'); };
  const broadcast = f.broadcast.startCapture(() => true, () => true), recording = f.recording.startCapture(() => true, () => true);
  broadcast.catch(() => {}); recording.catch(() => {}); await turn(); pending.resolve();
  await assert.rejects(broadcast); await assert.rejects(recording, /cancelled/);
  assert.equal(f.stops, 1); assert.deepEqual(faults, ['output_receiver_unavailable']);
  f.raw.startCapture = async () => { f.starts++; };
  await f.recording.startCapture(() => true, () => true); assert.equal(f.starts, 2);
  await f.recording.stopCapture(); await f.shared.close();
});

test('stopping a blocked consumer cancels its delivery deadline and never faults a later run', async () => {
  const f = fixture({deliveryTimeoutMs: 15}), faults = [], observed = [];
  f.recording = f.shared.forConsumer('recording', {onFault: code => faults.push(code)});
  await f.broadcast.startCapture(() => true, () => true);
  await f.recording.startCapture(() => true, () => new Promise(() => {}));
  f.audio(Buffer.from([1]), 0); await settle(); await f.recording.stopCapture();
  await f.recording.startCapture(() => true, (_bytes, pts) => { observed.push(pts); return true; });
  f.audio(Buffer.from([1]), 10000); await settle();
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.deepEqual(observed, [0]); assert.deepEqual(faults, []); assert.equal(f.recording.status().capturing, true);
  await f.recording.stopCapture(); await f.broadcast.stopCapture(); await f.shared.close();
});

test('stopped recording cannot retain the raw singleton when broadcast replaces its profile', async () => {
  const f = fixture();
  await f.broadcast.startCapture(() => true, () => true);
  await f.recording.startCapture(() => true, () => true);
  await f.recording.stopCapture();
  assert.equal(f.stops, 0); assert.equal(f.closes, 0);
  await f.broadcast.close();
  assert.equal(f.stops, 1); assert.equal(f.closes, 1);
  assert.throws(() => f.recording.prepare(), /output_capture_closed/);
  await assert.rejects(f.recording.startCapture(() => true, () => true), /output_capture_closed/);
  await f.recording.close(); assert.equal(f.closes, 1);
  const fresh = fixture(); await fresh.broadcast.prepare(); await fresh.broadcast.close();
  assert.equal(fresh.closes, 1);
});
