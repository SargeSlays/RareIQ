const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.resolve(__dirname, "../../rareiq/web/static/studiox.js"), "utf8");
function section(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from, `Missing production code section: ${start}`);
  return source.slice(from, to);
}
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function element() {
  return {
    value: "", checked: false, dataset: {}, style: {setProperty(name, value) { this[name] = value; }, removeProperty(name) { delete this[name]; }},
    textContent: "", options: [], children: [], classList: {add() {}, remove() {}, toggle() {}},
    setAttribute() {}, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; this.options = items; },
  };
}
function sandbox() {
  const elements = new Map(), storage = new Map(), frames = new Map(), players = [], notices = [];
  let nextFrame = 0;
  class Audio {
    constructor(url) { this.src = url; this.dataset = {}; this.listeners = new Map(); this.playback = deferred(); this.currentTime = 0; this.paused = false; players.push(this); }
    addEventListener(name, handler) { this.listeners.set(name, handler); }
    removeEventListener(name, handler) { if (this.listeners.get(name) === handler) this.listeners.delete(name); }
    emit(name) { this.listeners.get(name)?.({target: this}); }
    play() { return this.playback.promise; }
    pause() { this.paused = true; }
    remove() { this.removed = true; }
    removeAttribute(name) { delete this[name]; }
    load() {}
  }
  const context = vm.createContext({
    $, document: {querySelector: () => null, querySelectorAll: () => [], createElement: element},
    Audio, console, crypto: {randomUUID: () => "new-pad"},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
    requestAnimationFrame: fn => { const id = ++nextFrame; frames.set(id, fn); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    Option: function(text, value) { return {text, value}; },
    notify: (...args) => notices.push(args),
    spotifyState: {connected: false}, spotifyDuckedVolume: null, spotifyCommand: async () => ({}),
    navigator: {mediaDevices: {enumerateDevices: async () => []}},
    addEventListener() {},
  });
  function $(id) { return elements.get(id) || null; }
  context.window = context;
  const run = code => vm.runInContext(code, context);
  return {context, run, elements, storage, frames, players, notices,
    mount(id, props = {}) { const node = Object.assign(element(), props); elements.set(id, node); return node; },
    soundboard() { run(section("let soundboardState=", "function addSoundboardImageControls")); },
    voice() {
      run(section('const VOICE_MOD_PREFERENCES_KEY=', 'let cameraFxState='));
      run(section('function voiceModPreferences()', 'const CAMERA_FX_PRESETS='));
    },
  };
}
const pad = id => ({id, label: id, asset: {url: `/audio/${id}`, name: id}, asset_id: id});

test("sound failure advances a queued sequence only once, even when both error and play rejection fire", async () => {
  const app = sandbox(); app.soundboard();
  for (const id of ["a", "b", "c"]) app.context.playSoundboardPad(pad(id));
  app.players[0].emit("error");
  app.players[0].playback.reject(new Error("decode failed"));
  await settle();
  assert.equal(app.players.length, 2);
  assert.equal(app.run("soundboardQueue.length"), 1);
  assert.equal(app.run("activeSoundboardPlayers.size"), 1);
});

test("Stop All invalidates old playback callbacks before another sequence starts", async () => {
  const app = sandbox(); app.soundboard();
  app.context.playSoundboardPad(pad("old"));
  app.context.stopAllSoundboardAudio();
  for (const id of ["new", "next"]) app.context.playSoundboardPad(pad(id));
  app.players[0].playback.reject(new Error("aborted by stop"));
  await settle();
  assert.equal(app.players.length, 2);
  assert.equal(app.run("soundboardQueue.length"), 1);
  assert.equal(app.notices.length, 0);
});

test("digital output mirrors successful playback, volume and Stop All with local monitoring off", async () => {
  const app = sandbox(), added = [], removed = [], volumes = [];
  app.context.RareIQSoundboardOutput = {
    localVolume: () => 0,
    add: (audio, sound, volume) => added.push({audio, sound, volume}),
    remove: audio => removed.push(audio),
    volume: value => volumes.push(value),
  };
  app.soundboard(); app.context.setSoundboardVolume(40);
  app.context.playSoundboardPad(pad("output"));
  const player = app.players[0];
  assert.equal(player.volume, 0);
  assert.equal(added.length, 0);
  player.playback.resolve(); await settle();
  assert.equal(added.length, 1);
  assert.equal(added[0].audio, player);
  assert.equal(added[0].sound.asset_id, "output");
  assert.equal(added[0].volume, .4);
  app.context.setSoundboardVolume(70);
  assert.equal(player.volume, 0);
  assert.equal(volumes.at(-1), .7);
  app.context.stopAllSoundboardAudio();
  assert.deepEqual(removed, [player]);
  assert.equal(player.paused, true);
});

test("late playback success after Stop All never publishes stale sound to OBS", async () => {
  const app = sandbox(), added = [];
  app.context.RareIQSoundboardOutput = {
    localVolume: value => value,
    add: audio => added.push(audio),
    remove() {},
  };
  app.soundboard(); app.context.playSoundboardPad(pad("old-output"));
  app.context.stopAllSoundboardAudio();
  app.players[0].playback.resolve(); await settle();
  assert.equal(added.length, 0);
  assert.equal(app.frames.size, 0);
});

test("layered sounds share exactly one animation loop and Stop All cancels it", async () => {
  const app = sandbox(); app.soundboard();
  app.context.setSoundboardPlaybackMode("layer");
  for (const id of ["a", "b", "c"]) app.context.playSoundboardPad(pad(id));
  for (const player of app.players) player.playback.resolve();
  await settle();
  assert.equal(app.frames.size, 1);
  app.context.stopAllSoundboardAudio();
  assert.equal(app.frames.size, 0);
  assert.ok(app.players.every(player => player.paused));
});

test("switching layered playback to queue starts queued audio after all layers finish", () => {
  const app = sandbox(); app.soundboard();
  app.context.setSoundboardPlaybackMode("layer");
  app.context.playSoundboardPad(pad("a")); app.context.playSoundboardPad(pad("b"));
  app.context.setSoundboardPlaybackMode("queue"); app.context.playSoundboardPad(pad("c"));
  app.players[0].emit("ended");
  assert.equal(app.players.length, 2);
  app.players[1].emit("ended");
  assert.equal(app.players.length, 3);
  assert.equal(app.players[2].src, "/audio/c");
});

test("media decoding errors are reported instead of silently dropping a pad", () => {
  const app = sandbox(); app.soundboard(); app.context.playSoundboardPad(pad("bad"));
  app.players[0].emit("error");
  assert.equal(app.notices.length, 1);
  assert.equal(app.run("activeSoundboardPlayers.size"), 0);
});

test("filtered pad artwork is matched by pad ID, not its visible position", () => {
  const app = sandbox(); app.soundboard();
  const button = element(); button.dataset.padId = "b";
  app.context.document.querySelectorAll = selector => selector.includes("soundboardAppGrid") ? [button] : [];
  app.context.pads = [pad("a"), {...pad("b"), image_asset: {url: "/image-b"}}];
  app.run("soundboardState.pads=pads;refreshSoundPadImages()");
  assert.equal(button.style["--pad-image"], 'url("/image-b")');
});

test("malformed saved layout presets recover to usable defaults", () => {
  const app = sandbox(); app.soundboard();
  app.storage.set("rareiq.soundboard.layouts.v1", JSON.stringify({active: 1.5, presets: [null, {order: "invalid"}]}));
  assert.doesNotThrow(() => app.run("loadSoundboardLayouts();orderedSoundboardPads()"));
  assert.equal(app.run("soundboardLayouts.presets.length"), 10);
  assert.equal(app.run("Number.isInteger(soundboardLayouts.active)"), true);
});

test("audio upload retains existing pad images", async () => {
  const app = sandbox(); const calls = [];
  app.soundboard();
  app.run(section("async function uploadSoundboardAudio(", "async function replayCreatorReveal"));
  app.context.uploadCreatorAsset = async () => ({asset: {id: "new", name: "New", kind: "audio"}});
  app.context.api = async (_url, options) => {
    if (!options) return {pads: [{...pad("old"), image_asset_id: "image-old"}], assets: []};
    calls.push(JSON.parse(options.body)); return {soundboard: []};
  };
  app.context.renderSoundboard = () => {};
  await app.context.uploadSoundboardAudio({name: "new.wav"});
  assert.equal(calls[0].pads[0].image_asset_id, "image-old");
});

test("a full soundboard rejects another upload before creating an orphaned asset", async () => {
  const app = sandbox(); let uploads = 0;
  app.soundboard(); app.run(section("async function uploadSoundboardAudio(", "async function replayCreatorReveal"));
  app.context.uploadCreatorAsset = async () => { uploads++; return {asset: {id: "new", kind: "audio"}}; };
  app.context.api = async () => ({pads: Array.from({length: 50}, (_, i) => pad(String(i)))});
  await assert.rejects(app.context.uploadSoundboardAudio({name: "extra.wav"}), /50 pads/);
  assert.equal(uploads, 0);
});

function track() { return {stopped: false, stop() { this.stopped = true; }, addEventListener() {}}; }
function session(close) {
  const input = track(), output = track();
  return {active: true, context: {state: "running", close}, inputStream: {getTracks: () => [input]},
    destination: {stream: {getTracks: () => [output]}}, oscillators: [], meterFrame: 0, input, output};
}

function installMicrophone(app, {resume = async () => {}} = {}) {
  const input = track(), output = track(), contexts = [];
  const stream = {getTracks: () => [input], getAudioTracks: () => [input]};
  app.context.navigator.mediaDevices.getUserMedia = async () => stream;
  app.context.AudioContext = class {
    constructor() { this.state = "running"; this.destination = {}; contexts.push(this); }
    resume = resume;
    async close() { this.state = "closed"; }
    node() { return {connect() {}, gain: {value: 1}, getByteTimeDomainData(values) { values.fill(128); }}; }
    createGain() { return this.node(); }
    createMediaStreamSource() { return this.node(); }
    createAnalyser() { return this.node(); }
    createMediaStreamDestination() { return {...this.node(), stream: {getTracks: () => [output]}}; }
  };
  return {input, output, contexts};
}

test("the clean microphone pipeline starts, respects zero output, and releases its streams", async () => {
  const app = sandbox(); app.voice(); const mic = installMicrophone(app);
  app.mount("voiceModOutput", {value: "0"});
  await app.context.startVoiceMod();
  assert.equal(app.run("voiceModState.active"), true);
  assert.equal(app.run("voiceModState.outputGain.gain.value"), 0);
  await app.context.stopVoiceMod();
  assert.equal(mic.input.stopped, true); assert.equal(mic.output.stopped, true);
  assert.equal(app.frames.size, 0);
});

test("cancel during AudioContext resume releases the microphone immediately", async () => {
  const app = sandbox(); app.voice(); const resuming = deferred();
  const mic = installMicrophone(app, {resume: () => resuming.promise});
  const start = app.context.startVoiceMod(); await settle();
  await app.context.stopVoiceMod();
  assert.equal(mic.input.stopped, true);
  assert.equal(mic.contexts[0].state, "closed");
  resuming.resolve(); await start;
  assert.equal(app.run("voiceModState.active"), false);
});

test("cancel during an old context shutdown prevents a queued restart", async () => {
  const app = sandbox(); app.voice(); const closing = deferred(); let requests = 0;
  app.context.current = session(() => closing.promise);
  app.run("voiceModState=current");
  app.context.navigator.mediaDevices.getUserMedia = async () => { requests++; throw new Error("unexpected microphone request"); };
  const starting = app.context.startVoiceMod();
  await app.context.stopVoiceMod(); closing.resolve();
  await starting;
  assert.equal(requests, 0);
});

test("microphone stop clears active state and both tracks even when AudioContext.close rejects", async () => {
  const app = sandbox(); app.voice();
  app.context.current = session(async () => { throw new Error("device gone"); });
  app.run("voiceModState=current;window.rareiqVoiceModStream=current.destination.stream");
  await app.context.stopVoiceMod().catch(() => {});
  assert.equal(app.run("voiceModState.active"), false);
  assert.equal(app.context.rareiqVoiceModStream, null);
  assert.equal(app.context.current.input.stopped, true);
  assert.equal(app.context.current.output.stopped, true);
});

test("a late microphone shutdown cannot clear a newer audio session", async () => {
  const app = sandbox(); app.voice(); const closing = deferred();
  app.context.current = session(() => closing.promise);
  app.run("voiceModState=current;window.rareiqVoiceModStream=current.destination.stream");
  const stopping = app.context.stopVoiceMod();
  app.context.newer = session(async () => {});
  app.run("voiceModState=newer;window.rareiqVoiceModStream=newer.destination.stream");
  closing.resolve(); await stopping;
  assert.equal(app.run("voiceModState===newer"), true);
  assert.equal(app.context.rareiqVoiceModStream, app.context.newer.destination.stream);
});

test("saved microphone selection survives preference restoration before device discovery", async () => {
  const app = sandbox(); app.voice();
  app.mount("voiceModInput"); app.mount("voiceModGain", {value: "100"}); app.mount("voiceModMix", {value: "75"}); app.mount("voiceModOutput", {value: "100"});
  app.storage.set("rareiq.voiceMod.preferences.v1", JSON.stringify({deviceId: "usb-mic", preset: "clean"}));
  app.context.restoreVoiceModPreferences();
  app.context.navigator.mediaDevices.enumerateDevices = async () => [{kind: "audioinput", deviceId: "usb-mic", label: "USB microphone"}];
  await app.context.refreshVoiceModInputs();
  assert.equal(app.elements.get("voiceModInput").value, "usb-mic");
});

test("a missing saved microphone stays selected instead of silently using another device", async () => {
  const app = sandbox(); app.voice(); app.mount("voiceModInput"); app.mount("voiceModInputStatus");
  app.storage.set("rareiq.voiceMod.preferences.v1", JSON.stringify({deviceId: "missing-mic"}));
  app.context.navigator.mediaDevices.enumerateDevices = async () => [{kind: "audioinput", deviceId: "other", label: "Other microphone"}];
  await app.context.refreshVoiceModInputs();
  assert.equal(app.elements.get("voiceModInput").value, "missing-mic");
  assert.equal(app.elements.get("voiceModInputStatus").dataset.state, "error");
  let constraint;
  app.context.navigator.mediaDevices.getUserMedia = async value => { constraint = value; throw new Error("device unavailable"); };
  await assert.rejects(app.context.startVoiceMod(), /device unavailable/);
  assert.equal(constraint.audio.deviceId.exact, "missing-mic");
});

test("a late device enumeration cannot replace a newer device list", async () => {
  const app = sandbox(); app.voice(); app.mount("voiceModInput"); const old = deferred();
  app.context.navigator.mediaDevices.enumerateDevices = () => old.promise;
  const loading = app.context.refreshVoiceModInputs();
  app.context.navigator.mediaDevices.enumerateDevices = async () => [{kind: "audioinput", deviceId: "new", label: "New microphone"}];
  await app.context.refreshVoiceModInputs();
  old.resolve([{kind: "audioinput", deviceId: "old", label: "Old microphone"}]); await loading;
  assert.equal(app.elements.get("voiceModInput").options[1].value, "new");
});

test("cancelling microphone permission stops a late granted stream", async () => {
  const app = sandbox(); app.voice(); const permission = deferred(), input = track();
  app.context.navigator.mediaDevices.getUserMedia = () => permission.promise;
  const starting = app.context.startVoiceMod();
  await app.context.stopVoiceMod();
  permission.resolve({getTracks: () => [input]});
  await starting;
  assert.equal(input.stopped, true);
  assert.equal(app.run("voiceModState.active"), false);
});
