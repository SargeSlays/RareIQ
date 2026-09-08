const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.resolve(__dirname, '../../rareiq/web/static/studio_noise_gate.worklet.js'), 'utf8');
function gate(rate = 48000) {
  let Processor;
  const messages = [];
  const context = vm.createContext({sampleRate: rate, AudioWorkletProcessor: class {
    constructor() { this.port = {postMessage: value => messages.push({value, frame: instance.frames})}; }
  }, registerProcessor(name, constructor) { assert.equal(name, 'studio-noise-gate'); Processor = constructor; }});
  vm.runInContext(source, context);
  const instance = new Processor();
  const configure = config => instance.port.onmessage({data: {type: 'configure', ...config}});
  function process(channels) {
    const output = channels.map(channel => new Float32Array(channel.length));
    assert.equal(instance.process([channels], [output]), true);
    return output;
  }
  function run(value, seconds, channels = 1) {
    let output;
    for (let remaining = Math.round(seconds * rate); remaining > 0; remaining -= 128) {
      output = process(Array.from({length: channels}, () => new Float32Array(Math.min(128, remaining)).fill(value)));
    }
    return output;
  }
  return {instance, messages, configure, process, run, rate};
}

test('default bypass copies stereo channels exactly with no mixing', () => {
  const app = gate();
  const input = [Float32Array.from([0, .2, -.7, 1]), Float32Array.from([1, -.1, .3, 0])];
  const output = app.process(input);
  output.forEach((channel, i) => assert.deepEqual(channel, input[i]));
  assert.equal(app.instance.enabled, false);
  assert.equal(app.instance.thresholdDb, -45);
  assert.equal(app.messages[0].value.state, 'bypass');
});

test('quiet input stays closed and loud input opens smoothly without stereo cancellation', () => {
  const app = gate(); app.configure({enabled: true});
  const quiet = app.run(.001, .25);
  assert.ok(quiet[0].every(sample => sample === 0));
  const loud = app.process([new Float32Array(128).fill(.5), new Float32Array(128).fill(-.5)]);
  assert.equal(app.instance.open, true);
  assert.ok(loud[0][0] > 0 && loud[0][0] < loud[0][127] && loud[0][127] < .5);
  assert.ok(loud[0].every((sample, i) => sample === -loud[1][i]));
  assert.ok(app.run(.5, .1)[0].every(sample => sample > .499));
});

test('six-decibel hysteresis keeps an open gate open below the opening threshold', () => {
  const app = gate(); app.configure({enabled: true, thresholdDb: -20});
  app.run(.2, .1);
  app.run(.075, .4);
  assert.equal(app.instance.open, true);
  const fresh = gate(); fresh.configure({enabled: true, thresholdDb: -20});
  fresh.run(.075, .4);
  assert.equal(fresh.instance.open, false);
});

test('closing waits for hold, then releases smoothly and reaches silence', () => {
  const app = gate(); app.configure({enabled: true, thresholdDb: -20});
  app.run(.2, .15); app.run(0, .14);
  assert.equal(app.instance.open, true);
  app.run(0, .15);
  assert.equal(app.instance.open, false);
  const residual = app.instance.gain;
  assert.ok(residual > 0 && residual < 1);
  app.run(0, .1);
  assert.ok(Math.abs(app.instance.gain / residual - Math.exp(-1)) < .001);
  app.run(0, 2);
  assert.equal(app.instance.gain, 0);
});

test('disabling restores exact bypass immediately and re-enabling starts safely closed', () => {
  const app = gate(); app.configure({enabled: true}); app.run(.001, .2);
  app.configure({enabled: false});
  const input = [Float32Array.from([.0001, -.2, 0, .8])];
  assert.deepEqual(app.process(input)[0], input[0]);
  app.configure({enabled: true});
  assert.equal(app.instance.open, false);
  assert.equal(app.instance.gain, 0);
});

test('configuration clamps valid thresholds and ignores nonfinite or malformed values', () => {
  const app = gate();
  app.configure({thresholdDb: -100}); assert.equal(app.instance.thresholdDb, -70);
  app.configure({thresholdDb: 20}); assert.equal(app.instance.thresholdDb, -10);
  for (const value of [NaN, Infinity, -Infinity, 'loud', null]) app.configure({thresholdDb: value, enabled: 'true'});
  assert.equal(app.instance.thresholdDb, -10);
  assert.equal(app.instance.enabled, false);
});

test('enabled processing sanitizes nonfinite samples and missing inputs to finite silence', () => {
  const app = gate(); app.configure({enabled: true});
  const output = app.process([Float32Array.from([NaN, Infinity, -Infinity, .2])]);
  assert.ok(output[0].every(Number.isFinite));
  assert.ok(Number.isFinite(app.instance.energy));
  const disconnected = [new Float32Array(128).fill(1), new Float32Array(128).fill(1)];
  app.instance.process([[]], [disconnected]);
  assert.ok(disconnected.every(channel => channel.every(sample => sample === 0)));
});

test('status only reports changed states at most ten times per audio second without samples', () => {
  const app = gate(16000); app.run(.1, .2);
  assert.equal(app.messages.length, 1);
  for (let i = 0; i < 40; i++) {
    app.configure({enabled: i % 2 === 0}); app.run(.001, .025);
  }
  app.configure({enabled: true}); app.run(.001, .2);
  for (let i = 0; i < app.messages.length; i++) {
    assert.deepEqual(Object.keys(app.messages[i].value).sort(), ['state', 'type']);
    if (i) {
      assert.notEqual(app.messages[i].value.state, app.messages[i - 1].value.state);
      assert.ok(app.messages[i].frame - app.messages[i - 1].frame >= app.rate * .1);
    }
  }
  assert.equal(app.messages.at(-1).value.state, 'closed');
});
