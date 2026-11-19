'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {normalize, createModel, mount} = require('../settings-output-stats.js');
const {NativeBroadcast, PUBLIC_FAILURE_CODES} = require('../broadcast.cjs');
const status = (frames, bytesMuxed, extra = {}) => ({phase: 'sending', active: true, frames, bytesMuxed, queuedBytes: 1024, droppedVideoFrames: 2, droppedAudioPackets: 3, ...extra});

test('native broadcast projects only present valid scalar encoder counters and retains them after Stop', async () => {
  const app = new NativeBroadcast(), raw = {videoFrames: 90, audioSamples: 144000, codec: 'libx264', bytesMuxed: 1234, queuedBytes: 55, packets: 99,
    droppedVideoFrames: 4, droppedAudioPackets: 5, droppedVodAudioPackets: 6, cpu: 99, privatePath: 'private-secret', networkAcknowledged: true};
  app.encoder = {status: () => raw, stop: async () => {}};
  const projected = app.status();
  for (const key of ['bytesMuxed', 'queuedBytes', 'packets', 'droppedVideoFrames', 'droppedAudioPackets', 'droppedVodAudioPackets']) assert.equal(projected[key], raw[key]);
  assert.doesNotMatch(JSON.stringify(projected), /private-secret|networkAcknowledged|"cpu"/);
  await app.stop(); assert.equal(app.status().bytesMuxed, 1234); assert.equal(app.status().droppedAudioPackets, 5);
  app.encoder = {status: () => ({videoFrames: 1, audioSamples: 2, bytesMuxed: NaN, queuedBytes: -1, packets: 1.5, droppedAudioPackets: Infinity})};
  assert.equal(app.status().frames, 1);
  for (const key of ['bytesMuxed', 'queuedBytes', 'packets', 'droppedAudioPackets']) assert.equal(Object.hasOwn(app.status(), key), false);
  assert.ok(PUBLIC_FAILURE_CODES.includes('producer_screen_source_unavailable'));
  assert.ok(PUBLIC_FAILURE_CODES.includes('producer_screen_output_not_ready'));
});

test('normalization omits absent/invalid counters and arbitrary worker fields', () => {
  assert.deepEqual(normalize({videoFrames: 12, queuedBytes: 0, bytesMuxed: -1, packets: Infinity, codec: 'private', private: 'secret'}), {frames: 12, queuedBytes: 0});
  assert.deepEqual(normalize(null), {});
});

test('monotonic counter deltas compute recent rates from a zero-origin clock', () => {
  const model = createModel();
  assert.equal(model.observe(status(0, 0), 0).metrics.recentFps, null);
  const value = model.observe(status(30, 100000), 1000);
  assert.equal(value.metrics.recentFps, 30); assert.equal(value.metrics.encodedKbps, 800);
  assert.equal(value.metrics.inputDrops, 5); assert.equal(value.metrics.queueBytes, 1024);
  assert.doesNotMatch(JSON.stringify(value), /cpu|gpu|elapsed|networkAcknowledged/i);
});

test('sub-interval polls accumulate while duplicate, reversed and stale timestamps never create bogus rates', () => {
  const model = createModel({staleMs: 1000});
  model.observe(status(0, 0), 0);
  assert.equal(model.observe(status(3, 1000), 100).metrics.recentFps, null);
  assert.equal(model.observe(status(15, 5000), 500).metrics.recentFps, 30);
  assert.equal(model.observe(status(16, 6000), 500).metrics.recentFps, null);
  assert.equal(model.observe(status(17, 7000), 400).metrics.recentFps, null);
  const stale = model.observe(status(17, 7000), 2500);
  assert.equal(stale.state, 'stale'); assert.equal(stale.metrics.encodedKbps, null);
  assert.equal(model.observe(status(18, 8000), 2600).metrics.recentFps, null);
});

test('counter regression resets the rate baseline and Stop preserves the last attempt until next Start', () => {
  const model = createModel();
  model.observe(status(0, 0), 0); model.observe(status(90, 12000), 1000);
  const reset = model.observe(status(1, 50), 1500);
  assert.equal(reset.state, 'reset'); assert.equal(reset.metrics.recentFps, null);
  assert.equal(model.observe(status(31, 3050), 2500).metrics.recentFps, 30);
  const stopped = model.observe({phase: 'prepared', active: false, frames: 0, bytesMuxed: 0}, 3000);
  assert.equal(stopped.state, 'last_attempt'); assert.equal(stopped.metrics.encodedBytes, 3050); assert.equal(stopped.metrics.recentFps, null);
  const next = model.observe({phase: 'starting', active: true, frames: 0}, 3500);
  assert.equal(next.metrics.encodedBytes, null); assert.equal(next.counters.frames, 0);
});

test('missing counters show unavailable; rendering uses text only and destroy stops updates', () => {
  const nodes = new Map(), root = {innerHTML: '', querySelector: selector => {
    if (!nodes.has(selector)) nodes.set(selector, {textContent: ''}); return nodes.get(selector);
  }};
  let clock = 0; const widget = mount({root, now: () => clock});
  assert.equal(nodes.get('[data-output-stat="encodedBytes"]').textContent, 'Unavailable');
  widget.update({phase: 'sending', active: true, frames: 0, reason: '<private-secret>'});
  clock = 1000; widget.update(status(30, 2048));
  assert.equal(nodes.get('[data-output-stat="encodedBytes"]').textContent, '2.0 KiB');
  assert.equal(nodes.get('[data-output-stat="recentFps"]').textContent, '30.0 fps');
  assert.doesNotMatch(JSON.stringify([...nodes]), /private-secret/);
  widget.destroy(); widget.update(status(60, 4096));
  assert.equal(nodes.get('[data-output-stat="encodedBytes"]').textContent, '2.0 KiB');
});
