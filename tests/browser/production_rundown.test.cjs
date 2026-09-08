const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
const code=[source.match(/^let productionRundown=.*$/m)[0],
  source.slice(source.indexOf('function waitProductionRundown('),source.indexOf('function clearProductionRundown(')),
  source.slice(source.indexOf('async function takeProductionScene('),source.indexOf('async function setProductionPreview('))].join('\n');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function app(overrides={}){
  const calls={saved:0,rendered:0,switcher:0,spotify:[],sounds:0,replays:[],events:[],notices:[]},timers=new Map();
  let serial=0;
  const nodes={rundownRehearsal:{checked:false},rundownStatus:{textContent:''}};
  const context=vm.createContext({
    $:id=>nodes[id],document:{querySelectorAll:()=>[]},
    productionScenes:[{id:'main',name:'Main',transition:'cut',spotify_action:'keep',soundboard_action:'keep'}],
    api:async()=>({ok:true,program_slot:1}),
    renderProductionSwitcher:()=>calls.switcher++,renderProductionScreen:()=>{},
    spotifyCommand:async action=>calls.spotify.push(action),stopAllSoundboardAudio:()=>calls.sounds++,
    logProductionEvent:(...args)=>calls.events.push(args),notify:(...args)=>calls.notices.push(args),
    saveProductionRundown:()=>calls.saved++,renderProductionRundown:()=>calls.rendered++,
    loadProductionReplay:async()=>({highlights:[{id:'clip'}]}),takeProductionReplay:async id=>calls.replays.push(id),
    setTimeout:(fn,ms)=>{timers.set(++serial,{fn,ms});return serial;},clearTimeout:id=>timers.delete(id),
    ...overrides,
  });
  vm.runInContext(code,context);
  vm.runInContext('productionRundown=[{type:"scene",target:"main",label:"Main",auto_follow:true},{type:"sound-stop",label:"Stop sounds"}]',context);
  return {context,calls,timers,nodes,state:()=>vm.runInContext('({index:productionRundownIndex,running:productionRundownRunning})',context)};
}
test('Stop suppresses delayed scene UI/audio follow-ups, advancement and auto-follow',async()=>{
  const pending=deferred(),ui=app({api:()=>pending.promise});
  Object.assign(ui.context.productionScenes[0],{spotify_action:'play',soundboard_action:'stop'});
  const running=ui.context.goProductionRundown();ui.context.stopProductionRundown();
  pending.resolve({ok:true,program_slot:1});await running;
  assert.equal(ui.state().index,0);assert.equal(ui.state().running,false);
  assert.equal(ui.calls.switcher,0);assert.equal(ui.calls.sounds,0);assert.deepEqual(ui.calls.spotify,[]);
  assert.equal(ui.calls.saved,0);assert.equal(ui.calls.rendered,0);assert.equal(ui.timers.size,0);
  assert.deepEqual(ui.calls.notices.map(item=>item[0]),['Rundown Stopped']);
});
test('late completion from a stopped run cannot unlock or advance a newer run',async()=>{
  const old=deferred(),next=deferred();let requests=0;
  const ui=app({api:()=>++requests===1?old.promise:next.promise});
  const first=ui.context.goProductionRundown();ui.context.stopProductionRundown();
  const second=ui.context.goProductionRundown();old.resolve({ok:true,program_slot:1});await first;
  assert.equal(ui.state().running,true);assert.equal(ui.state().index,0);assert.equal(ui.calls.saved,0);
  await ui.context.goProductionRundown();assert.equal(requests,2);
  next.resolve({ok:true,program_slot:1});await second;
  assert.equal(ui.state().running,false);assert.equal(ui.state().index,1);assert.equal(ui.calls.saved,1);
  assert.equal(ui.timers.size,1);
});
for(const mode of ['delay','wait','rehearsal'])test(`Stop settles a cancelled ${mode} without firing or advancing`,async()=>{
  let requests=0;const ui=app({api:async()=>{requests++;return {ok:true,program_slot:1};}});
  if(mode==='wait')vm.runInContext('productionRundown[0].type="wait"',ui.context);
  if(mode==='rehearsal')ui.nodes.rundownRehearsal.checked=true;
  else vm.runInContext('productionRundown[0].delay_seconds=2',ui.context);
  const running=ui.context.goProductionRundown();assert.equal(ui.timers.size,1);
  ui.context.stopProductionRundown();await running;
  assert.equal(requests,0);assert.equal(ui.timers.size,0);assert.equal(ui.calls.saved,0);assert.equal(ui.state().index,0);
});
test('Stop during replay lookup prevents the subsequent replay take',async()=>{
  const pending=deferred(),ui=app({loadProductionReplay:()=>pending.promise});
  vm.runInContext('productionRundown[0].type="replay"',ui.context);
  const running=ui.context.goProductionRundown();ui.context.stopProductionRundown();
  pending.resolve({highlights:[{id:'clip'}]});await running;
  assert.deepEqual(ui.calls.replays,[]);assert.equal(ui.calls.saved,0);
});
test('OBS and Spotify partial outcomes warn and pause rundown on its selected cue',async()=>{
  const ui=app({api:async()=>({ok:true,program_slot:1,obs_warning:'offline'}),spotifyCommand:async()=>{throw Error('offline');}});
  ui.context.productionScenes[0].spotify_action='pause';
  const outcome=await ui.context.goProductionRundown();
  assert.equal(outcome.partial,true);assert.equal(outcome.warnings.length,2);
  assert.equal(ui.state().index,0);assert.equal(ui.state().running,false);assert.equal(ui.timers.size,0);
  assert.equal(ui.calls.saved,0);assert.match(ui.nodes.rundownStatus.textContent,/Paused/);
  assert.deepEqual(ui.calls.notices.map(item=>item[2]),['warning','warning']);
});
test('complete scene waits for requested Spotify action before success and advancement',async()=>{
  const pending=deferred(),ui=app({spotifyCommand:()=>pending.promise});
  ui.context.productionScenes[0].spotify_action='play';
  const running=ui.context.goProductionRundown();await settle();
  assert.equal(ui.state().running,true);assert.equal(ui.calls.saved,0);assert.equal(ui.calls.notices.length,0);
  pending.resolve();await running;
  assert.equal(ui.state().index,1);assert.equal(ui.calls.saved,1);
  assert.deepEqual(ui.calls.notices.map(item=>item[0]),['Scene Changed','Cue Fired']);
});
test('Stop during already-sent Spotify action suppresses its late success feedback',async()=>{
  const pending=deferred(),ui=app({spotifyCommand:()=>pending.promise});
  ui.context.productionScenes[0].spotify_action='play';
  const running=ui.context.goProductionRundown();await settle();ui.context.stopProductionRundown();
  pending.resolve();await running;
  assert.equal(ui.calls.saved,0);assert.equal(ui.calls.events.length,0);assert.equal(ui.timers.size,0);
  assert.deepEqual(ui.calls.notices.map(item=>item[0]),['Rundown Stopped']);
});
