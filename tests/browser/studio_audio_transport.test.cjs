const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/soundboard_output.js'),'utf8');
const voice={id:'one',url:'/api/creator/assets/sound',volume:.3,position:2};
function fixture(){
  let now=0,events,watchdog;const players=[],listeners={},status={textContent:''};
  class Audio {
    constructor(){this.dataset={};this.listeners={};this.duration=30;this.plays=0;this.pauses=0;players.push(this);}
    addEventListener(name,fn){this.listeners[name]=fn;}
    load(){} removeAttribute(){} remove(){}
    play(){this.plays++;return Promise.resolve();} pause(){this.pauses++;}
  }
  class EventSource {constructor(){events=this;}close(){this.closed=true;}}
  vm.runInNewContext(source,{
    Audio,EventSource,Date:{now:()=>now},URLSearchParams,location:{search:''},
    document:{body:{classList:{toggle(){}},append(){}},getElementById:id=>id==='status'?status:{}},
    setInterval:fn=>{watchdog=fn;return 1;},clearInterval:()=>{watchdog=null;},
    addEventListener:(name,fn)=>{listeners[name]=fn;}
  });
  return {players,events,listeners,status,send:voices=>events.onmessage({data:JSON.stringify({voices})}),
    advance:ms=>{now+=ms;watchdog?.();}};
}
test('audio transport silences on disconnect and resumes current position once',()=>{
  const f=fixture();f.send([voice]);const old=f.players[0];old.listeners.loadedmetadata();
  f.events.onerror();assert.equal(old.pauses,1);
  f.send([{...voice,position:7}]);const current=f.players[1];current.listeners.loadedmetadata();
  f.send([{...voice,position:8}]);assert.equal(f.players.length,2);assert.equal(current.currentTime,7);assert.equal(current.plays,1);
});
test('missing heartbeats and malformed snapshots silence audio',()=>{
  const f=fixture();f.send([voice]);f.players[0].listeners.loadedmetadata();f.advance(1600);
  assert.equal(f.players[0].pauses,1);f.send([voice]);
  f.events.onmessage({data:'{"voices":null}'});assert.equal(f.players[1].pauses,1);
  assert.equal(f.status.textContent,'Audio state unavailable');
});
test('queued events after pagehide never recreate playback',()=>{
  const f=fixture();f.send([voice]);f.listeners.pagehide();
  assert.equal(f.events.closed,true);assert.equal(f.players[0].pauses,1);
  f.send([voice]);f.players[0].listeners.loadedmetadata();f.advance(2000);
  assert.equal(f.players.length,1);assert.equal(f.players[0].plays,0);
});
