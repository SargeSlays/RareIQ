'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
function fixture() {
  const source = fs.readFileSync(path.join(__dirname, '../output-preload.cjs'), 'utf8');
  const code = source.match(/const worklet = `([\s\S]*?)`;/)[1], packets = [],meters=[];
  let Processor;
  const context = { currentFrame: 0, AudioWorkletProcessor: class { constructor() { this.port = { postMessage: data => (data.type==='meters'?meters:packets).push(data) }; } }, registerProcessor: (_name, cls) => { Processor = cls; } };
  vm.runInNewContext(code, context); const processor = new Processor();
  return { processor, packets,meters,
    message(value) { processor.port.onmessage({ data: value }); },
    tick(left = .5, right = -.25,vodLeft=0,vodRight=0) { const output = [new Float32Array(128).fill(1), new Float32Array(128).fill(1)]; processor.process([[new Float32Array(128).fill(left), new Float32Array(128).fill(right)],[new Float32Array(128).fill(vodLeft),new Float32Array(128).fill(vodRight)]], [output]); context.currentFrame += 128; return output; },
  };
}
test('worklet produces interleaved stereo samples, sample timestamps and a silent local sink', () => {
  const f = fixture(); f.message({ type: 'start', captureId: 'first' });
  for (let i = 0; i < 4; i++) assert.ok(f.tick().every(channel => channel.every(sample => sample === 0)));
  assert.equal(f.packets.length, 1); const p = f.packets[0], samples = new Float32Array(p.pcm);
  assert.equal(p.captureId, 'first'); assert.equal(p.frame, 0); assert.equal(samples.length, 960);
  assert.ok(samples.every((sample, i) => sample === (i % 2 ? -.25 : .5)));
  assert.equal(new Float32Array(p.vodPcm).every(sample=>sample===0),true);
});
test('prepared meter windows run without PCM capture or audible output and describe post-clamp levels',()=>{
  const f=fixture();
  for(let i=0;i<38;i++)assert.ok(f.tick(2,NaN,.25,-.5).every(channel=>channel.every(value=>value===0)));
  assert.equal(f.packets.length,0);assert.equal(f.processor.queue.length,0);assert.equal(f.meters.length,1);
  const {live,vod}=f.meters[0].meters;assert.equal(live.peak,1);assert.ok(Math.abs(live.rms-Math.SQRT1_2)<1e-8);assert.equal(live.clipCount,4800);
  assert.equal(vod.peak,.5);assert.ok(Math.abs(vod.rms-Math.sqrt(.15625))<1e-8);assert.equal(vod.clipCount,0);
  assert.equal(JSON.stringify(f.meters[0]).includes('pcm'),false);
  f.message({type:'start',captureId:'metered'});for(let i=0;i<38;i++)f.tick(.5,-.25,0,0);
  assert.equal(f.packets.length,1);assert.equal(f.processor.queue.length,4);assert.equal(f.meters.length,2);
});

test('paired live and VOD chunks share timestamps, credits and dropped-chunk boundaries',()=>{
  const f=fixture();f.message({type:'start',captureId:'paired'});
  for(let i=0;i<20;i++)f.tick(.5,-.25,.125,-.5);
  assert.equal(f.packets.length,1);const first=f.packets[0];assert.equal(first.pcm.byteLength,3840);assert.equal(first.vodPcm.byteLength,3840);
  assert.ok(new Float32Array(first.vodPcm).every((value,i)=>value===(i%2?-.5:.125)));
  for(let i=0;i<60;i++)f.tick(.5,-.25,.125,-.5);f.message({type:'credit',captureId:'paired'});
  const next=f.packets.at(-1);assert.ok(next.dropped>0);assert.equal(next.frame%480,0);assert.ok(new Float32Array(next.pcm).every((value,i)=>value===(i%2?-.25:.5)));assert.ok(new Float32Array(next.vodPcm).every((value,i)=>value===(i%2?-.5:.125)));
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
