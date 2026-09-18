const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/program_view.html'),'utf8');
const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const runtime=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/overlay_runtime.js'),'utf8');
const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve()};
function fixture(){
  const timers=new Map(),listeners={},requests=[],stage={dataset:{},style:{setProperty(){}}};let next=0;
  const frame=()=>{const classes=new Set(['program-frame','out']);return {src:'',loads:0,classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c)},removeAttribute(){this.src=''},classes}};
  const frames=[frame(),frame()],nodes={program:stage,programA:frames[0],programB:frames[1]};
  const current={state:{generation:0,program_slot:1,transition:'cut',duration_ms:0},pending:null};
  const sandbox={document:{getElementById:id=>nodes[id]},fetch:async url=>{requests.push(url);return current.pending||{ok:true,json:async()=>current.state}},setTimeout:(fn,delay)=>{timers.set(++next,{fn,delay});return next},clearTimeout:id=>timers.delete(id),addEventListener:(name,fn)=>listeners[name]=fn};
  sandbox.AbortController=AbortController;sandbox.window=sandbox;
  vm.createContext(sandbox);vm.runInContext(runtime,sandbox);vm.runInContext(source,sandbox);
  const run=async delay=>{const entry=[...timers].find(([,timer])=>timer.delay===delay);assert.ok(entry,`Expected ${delay}ms timer`);timers.delete(entry[0]);await entry[1].fn();await settle()};
  return {frames,stage,current,timers,listeners,requests,run};
}
test('Program reuses the clean reconnecting camera view and does not reload unchanged generations',async()=>{
  const f=fixture();await settle();assert.equal(f.frames[1].src,'/output/camera/1');assert.equal(f.frames[1].classList.contains('out'),false);assert.equal(f.frames[1].classList.contains('program-frame'),true);
  await f.run(0);await f.run(300);assert.equal(f.timers.size,1,'Unchanged state must not start another transition');assert.deepEqual(f.requests,['/api/production/switcher','/api/production/switcher']);
});
test('rapid takes retain the latest camera and retire only the current outgoing view',async()=>{
  const f=fixture();await settle();await f.run(0);
  f.current.state={generation:1,program_slot:2,transition:'fade',duration_ms:500};await f.run(300);
  f.current.state={generation:2,program_slot:3,transition:'zoom',duration_ms:500};await f.run(300);
  assert.equal([...f.timers.values()].filter(timer=>timer.delay===500).length,1);assert.equal(f.frames[1].src,'/output/camera/3');assert.equal(f.frames[1].classList.contains('out'),false);
  await f.run(500);assert.equal(f.frames[0].src,'');assert.equal(f.frames[1].src,'/output/camera/3');assert.equal(f.stage.dataset.transition,'zoom');
});
test('invalid switcher data cannot create another camera subscription',async()=>{
  const f=fixture();await settle();await f.run(0);
  f.current.state={generation:1,program_slot:99,transition:'fade',duration_ms:500};await f.run(300);assert.ok(f.frames.every(frame=>frame.src===''));
});
test('page close releases both views and a late switcher response cannot reopen them',async()=>{
  const f=fixture();await settle();await f.run(0);let resolve;
  f.current.pending=new Promise(done=>resolve=done);
  const poll=[...f.timers.values()].find(timer=>timer.delay===300);const awaiting=poll.fn();
  f.listeners.pagehide();assert.equal(f.timers.size,0);assert.ok(f.frames.every(frame=>frame.src===''));
  resolve({ok:true,json:async()=>({generation:1,program_slot:2})});await awaiting;await settle();assert.equal(f.timers.size,0);assert.ok(f.frames.every(frame=>frame.src===''));
});

test('switcher failure clears Program and same-generation recovery restores it',async()=>{
  const f=fixture();await settle();await f.run(0);
  f.current.pending={ok:false};await f.run(300);
  assert.ok(f.frames.every(frame=>frame.src===''&&frame.classList.contains('out')));
  f.current.pending=null;await f.run(300);
  assert.equal(f.frames.filter(frame=>frame.src==='/output/camera/1').length,1);
});

test('a restart with a reused generation but different Program slot switches cameras',async()=>{
  const f=fixture();await settle();await f.run(0);
  f.current.state={generation:0,program_slot:3,transition:'cut'};await f.run(300);await f.run(0);
  assert.equal(f.frames.filter(frame=>frame.src==='/output/camera/3').length,1);
  assert.ok(f.frames.every(frame=>frame.src!=='/output/camera/1'));
});

test('stalled switcher requests expire, ignore late results, and reconnect',async()=>{
  const f=fixture();await settle();await f.run(0);let resolve;
  f.current.pending=new Promise(done=>resolve=done);
  const entry=[...f.timers].find(([,timer])=>timer.delay===300);f.timers.delete(entry[0]);entry[1].fn();await settle();
  assert.equal(f.requests.length,2);assert.equal([...f.timers.values()].filter(timer=>timer.delay===300).length,0);
  await f.run(4000);assert.ok(f.frames.every(frame=>frame.src===''));
  resolve({ok:true,json:async()=>({generation:9,program_slot:4})});await settle();
  assert.ok(f.frames.every(frame=>frame.src===''));
  f.current.pending=null;await f.run(300);
  assert.equal(f.frames.filter(frame=>frame.src==='/output/camera/1').length,1);
});
