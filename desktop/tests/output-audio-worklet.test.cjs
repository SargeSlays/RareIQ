'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
function fixture() {
  const source = fs.readFileSync(path.join(__dirname, '../output-preload.cjs'), 'utf8');
  const code = source.match(/const worklet = `([\s\S]*?)`;/)[1], packets = [];
  let Processor;
  const context = { currentFrame: 0, AudioWorkletProcessor: class { constructor() { this.port = { postMessage: data => packets.push(data) }; } }, registerProcessor: (_name, cls) => { Processor = cls; } };
  vm.runInNewContext(code, context); const processor = new Processor();
  return { processor, packets,
    message(value) { processor.port.onmessage({ data: value }); },
    tick(left = .5, right = -.25) { const output = [new Float32Array(128).fill(1), new Float32Array(128).fill(1)]; processor.process([[new Float32Array(128).fill(left), new Float32Array(128).fill(right)]], [output]); context.currentFrame += 128; return output; },
  };
}
test('worklet produces interleaved stereo samples, sample timestamps and a silent local sink', () => {
  const f = fixture(); f.message({ type: 'start', captureId: 'first' });
  for (let i = 0; i < 4; i++) assert.ok(f.tick().every(channel => channel.every(sample => sample === 0)));
  assert.equal(f.packets.length, 1); const p = f.packets[0], samples = new Float32Array(p.pcm);
  assert.equal(p.captureId, 'first'); assert.equal(p.frame, 0); assert.equal(samples.length, 960);
  assert.ok(samples.every((sample, i) => sample === (i % 2 ? -.25 : .5)));
});
test('worklet has one transport credit and at most four queued chunks during backpressure', () => {
  const f = fixture(); f.message({ type: 'start', captureId: 'first' });
  for (let i = 0; i < 100; i++) f.tick();
  assert.equal(f.packets.length, 1); assert.equal(f.processor.queue.length, 4); assert.ok(f.processor.dropped > 0);
  f.message({ type: 'credit', captureId: 'stale' }); assert.equal(f.packets.length, 1);
  f.message({ type: 'credit', captureId: 'first' }); assert.equal(f.packets.length, 2); assert.ok(f.packets[1].frame > 480);
});
test('stop clears queued samples; restart creates a fresh tagged epoch; non-finite audio is silent', () => {
  const f = fixture(); f.message({ type: 'start', captureId: 'first' }); for (let i = 0; i < 10; i++) f.tick();
  f.message({ type: 'stop' }); assert.equal(f.processor.queue.length, 0); const n = f.packets.length; for (let i = 0; i < 10; i++) f.tick(); assert.equal(f.packets.length, n);
  f.message({ type: 'start', captureId: 'second' }); for (let i = 0; i < 4; i++) f.tick(NaN, 2);
  const p = f.packets.at(-1), samples = new Float32Array(p.pcm); assert.equal(p.captureId, 'second'); assert.equal(p.dropped, 0);
  assert.ok(samples.every((sample, i) => sample === (i % 2 ? 1 : 0)));
});
