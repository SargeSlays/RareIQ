const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'rareiq/web/static/studio_shell.js'),'utf8');
function shell(saved){
  const nodes=new Map(),opened=[],views=[],buttons=[];
  const storage={value:saved,getItem(){return this.value},setItem(key,value){this.value=value}};
  function node(id){if(!nodes.has(id))nodes.set(id,{handlers:{},dataset:{},addEventListener(k,f){this.handlers[k]=f;}});return nodes.get(id)}
  const context={window:{},location:{search:''},URLSearchParams,localStorage:storage,document:{getElementById:node,querySelectorAll:()=>buttons}};
  vm.runInNewContext(source,context);
  return {app:context.window.RareIQStudioShell,storage,node,buttons,opened,views,
    init(){this.app.init({navigate:x=>opened.push(x),view:x=>views.push(x)})}};
}
test('Studio is the new default; old workspace names and aliases remain reachable',()=>{
  const s=shell();assert.equal(s.app.initialWorkspace(),'broadcast');
  for(const [query,want] of [['studio','broadcast'],['cards','live'],['live','live'],['soundboard','soundboard'],['bogus','broadcast']])
    assert.equal(s.app.initialWorkspace('?workspace='+query),want);
});
test('Card Studio can remain the start page without changing any camera or output',()=>{
  const s=shell('live');s.init();assert.equal(s.node('studioStartWorkspace').value,'live');
  assert.equal(s.app.initialWorkspace('?workspace=studio'),'broadcast');
  s.node('studioStartWorkspace').value='broadcast';s.node('studioStartWorkspace').handlers.change();
  assert.equal(s.storage.value,'broadcast');assert.equal(s.opened.length,0);
});
test('blocked storage is safe and saving failures are truthful',()=>{
  const s=shell();s.storage.getItem=()=>{throw Error('blocked')};s.storage.setItem=()=>{throw Error('blocked')};
  assert.equal(s.app.initialWorkspace(),'broadcast');s.init();s.node('studioStartWorkspace').handlers.change();
  assert.match(s.node('studioStartWorkspaceStatus').textContent,/could not be saved/);
});
test('workspace buttons navigate only; they cannot start a show or broadcast',()=>{
  const s=shell();const button=s.node('open');button.dataset.studioOpen='live';s.buttons.push(button);s.init();
  button.handlers.click();assert.deepEqual(s.opened,['live']);
  button.dataset.studioOpen='unknown';button.handlers.click();assert.deepEqual(s.opened,['live']);
});

const studio=fs.readFileSync(path.join(root,'rareiq/web/static/studiox.js'),'utf8');
function readiness(request){
  const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{dataset:{},value:id==='showWorkflow'?'studio':'',replaceChildren(){}});return nodes.get(id)}
  const context=vm.createContext({$:node,api:request,encodeURIComponent,productionSessionState:{active:false},
    renderBroadcastDestinations(){},renderShowPreflight(payload){context.result=payload;}});
  const prefix=studio.slice(studio.indexOf('let showPreflightState='),studio.indexOf('function renderShowPreflight('));
  const loader=studio.slice(studio.indexOf('async function loadShowPreflight('),studio.indexOf('async function startProductionShow('));
  vm.runInContext(prefix+'\n'+loader,context);
  return {node,context,load:()=>vm.runInContext('loadShowPreflight()',context)};
}
const pending=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
test('preflight passes explicit workflow with no retry and ignores older responses',async()=>{
  const first=pending(),second=pending(),calls=[];
  const r=readiness((...args)=>{calls.push(args);return calls.length===1?first.promise:second.promise});
  const a=r.load();r.node('showWorkflow').value='cards';const b=r.load();
  assert.equal(calls[0][0],'/api/production/preflight?workflow=studio');assert.equal(calls[1][0],'/api/production/preflight?workflow=cards');
  assert.equal(calls[1][1].retries,0);
  second.resolve({preflight:{workflow:'cards'}});await b;first.resolve({preflight:{workflow:'studio'}});await a;
  assert.equal(r.context.result.preflight.workflow,'cards');
});
test('failed refresh invalidates readiness and never leaves Start enabled',async()=>{
  const r=readiness(async()=>{throw Error('network')});
  vm.runInContext('showPreflightState={workflow:"studio",ready:true};syncShowStartAvailability()',r.context);
  assert.equal(r.node('showStartButton').disabled,false);
  await assert.rejects(r.load());assert.equal(r.node('showStartButton').disabled,true);
  assert.equal(r.node('showPreflightVerdict').textContent,'CHECK FAILED');
});
test('readiness from another workflow cannot authorize a start',()=>{
  const r=readiness(async()=>({}));
  vm.runInContext('showPreflightState={workflow:"cards",ready:true};syncShowStartAvailability()',r.context);
  assert.equal(r.node('showStartButton').disabled,true);
});
