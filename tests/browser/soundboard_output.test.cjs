const test = require('node:test');
const assert = require('node:assert/strict');
const {SoundboardReceiver} = require('../../rareiq/web/static/soundboard_output.js');
class AudioFake {
  constructor(url) { this.url=url;this.listeners={};this.volume=1;this.duration=30;this.plays=0;this.pauses=0; }
  addEventListener(name, handler) { this.listeners[name]=handler; }
  load() {}
  play() { this.plays++;return Promise.resolve(); }
  pause() { this.pauses++; }
  removeAttribute() {}
}
const voice = {id:'one',url:'/api/creator/assets/sound',volume:.3,position:2};
test('audio snapshots reuse players, apply volume, and Stop All disposes them', () => {
  const receiver = new SoundboardReceiver(AudioFake);
  receiver.sync([voice]);
  const audio = receiver.players.get('one').audio;
  audio.listeners.loadedmetadata();
  assert.equal(audio.currentTime,2);assert.equal(audio.plays,1);
  receiver.sync([{...voice,volume:.8,position:3}]);
  assert.equal(receiver.players.get('one').audio,audio);assert.equal(audio.volume,.8);
  assert.equal(audio.currentTime,2); // No continual seeking or stutter.
  receiver.sync([]);assert.equal(receiver.players.size,0);assert.equal(audio.pauses,1);
});
test('layered sounds are independent and ended sounds never replay on heartbeats', () => {
  const receiver = new SoundboardReceiver(AudioFake);
  receiver.sync([voice,{...voice,id:'two'}]);
  receiver.players.get('one').audio.listeners.ended();
  receiver.sync([voice,{...voice,id:'two'}]);
  assert.equal(receiver.players.size,1);assert.ok(receiver.players.has('two'));
});
test('disconnect cancels pending metadata, and stale or arbitrary audio is not played', () => {
  const receiver = new SoundboardReceiver(AudioFake);
  receiver.sync([voice]);const audio = receiver.players.get('one').audio;
  receiver.silence();audio.listeners.loadedmetadata();assert.equal(audio.plays,0);
  receiver.sync([{...voice,id:'old',position:100},{...voice,id:'external',url:'https://example.com/audio.mp3'}]);
  receiver.players.get('old').audio.listeners.loadedmetadata();assert.equal(receiver.players.size,0);
});

test('late events from disconnected audio cannot finish or stop its replacement', () => {
  const reports=[],receiver=new SoundboardReceiver(AudioFake,text=>reports.push(text));
  receiver.sync([voice]);const old=receiver.players.get('one').audio;
  receiver.silence();receiver.sync([{...voice,position:8}]);
  const replacement=receiver.players.get('one').audio;
  old.listeners.error();old.listeners.ended();old.listeners.loadedmetadata();
  assert.equal(receiver.players.get('one').audio,replacement);
  assert.equal(receiver.completed.has('one'),false);assert.equal(reports.length,0);
  replacement.listeners.loadedmetadata();
  assert.equal(replacement.currentTime,8);assert.equal(replacement.plays,1);assert.equal(old.plays,0);
  receiver.sync([{...voice,position:9}]);assert.equal(replacement.plays,1);
});
