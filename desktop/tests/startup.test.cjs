'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events'),fs=require('node:fs'),path=require('node:path');
const {loadInitialStudio}=require('../startup.cjs');
const URL='http://127.0.0.1:8765/control?workspace=studio&desktop=1';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
  const contents=new EventEmitter();let resolve,reject;
  const loading=new Promise((yes,no)=>{resolve=yes;reject=no;});
  Object.assign(contents,{url:'about:blank',mainFrame:{url:'about:blank'},dead:false,loads:0,
    isDestroyed(){return this.dead;},getURL(){return this.url;},loadURL(url){this.loads++;this.url=url;this.mainFrame.url=url;return loading;}});
  return {contents,resolve,reject,ready(){contents.emit('dom-ready');},clean(){assert.deepEqual(contents.eventNames(),[]);}};
}

test('exact DOM-ready resolves while an MJPEG resource load remains pending and removes listeners',async()=>{
  const f=fixture(),ready=loadInitialStudio(f.contents,URL);f.ready();await ready;f.clean();assert.equal(f.contents.loads,1);
});

test('a late reload ERR_ABORTED is consumed after startup is already complete',async()=>{
  const f=fixture(),errors=[],record=error=>errors.push(error);process.on('unhandledRejection',record);
  try{const ready=loadInitialStudio(f.contents,URL);f.ready();await ready;f.reject(Error('ERR_ABORTED: synthetic private URL'));await tick();assert.deepEqual(errors,[]);f.clean();}
  finally{process.removeListener('unhandledRejection',record);}
});

test('load completion alone does not establish top-level DOM readiness',async()=>{
  const f=fixture();let complete=false;const ready=loadInitialStudio(f.contents,URL).then(()=>{complete=true;});f.resolve();await tick();assert.equal(complete,false);f.ready();await ready;f.clean();
});

test('pre-ready load rejection and top-frame failure remain startup failures',async()=>{
  for(const action of [f=>f.reject(Error('ERR_ABORTED private detail')),f=>f.contents.emit('did-fail-load',{},-105,'private detail',URL,true)]){
    const f=fixture(),ready=loadInitialStudio(f.contents,URL);action(f);await assert.rejects(ready,error=>error.code==='studio_startup_load_failed'&&!error.message.includes('private'));f.clean();
  }
});

test('subframe loads and navigation cannot complete or fail the top-level startup',async()=>{
  const f=fixture(),ready=loadInitialStudio(f.contents,URL);f.contents.emit('did-fail-load',{},-3,'aborted','https://widget.example',false);f.contents.emit('did-start-navigation',{},'https://widget.example',false,false);f.ready();await ready;f.clean();
});

test('wrong document, frame or main-frame navigation fails closed before readiness',async()=>{
  for(const action of [f=>{f.contents.url='https://untrusted.example/control';f.ready();},f=>{f.contents.mainFrame.url=URL+'&replaced=1';f.ready();},f=>f.contents.emit('did-start-navigation',{},'http://127.0.0.1:8765/guest',false,true)]){
    const f=fixture(),ready=loadInitialStudio(f.contents,URL);action(f);await assert.rejects(ready,{code:'studio_startup_untrusted'});f.clean();
  }
});

test('destroyed or crashed renderer before readiness rejects and cleans up',async()=>{
  for(const action of [f=>f.contents.emit('destroyed'),f=>f.contents.emit('render-process-gone')]){
    const f=fixture(),ready=loadInitialStudio(f.contents,URL);action(f);await assert.rejects(ready,error=>['studio_startup_destroyed','studio_startup_renderer_unavailable'].includes(error.code));f.clean();
  }
  const f=fixture();f.contents.dead=true;await assert.rejects(loadInitialStudio(f.contents,URL),{code:'studio_startup_destroyed'});assert.equal(f.contents.loads,0);f.clean();
});

test('a missing DOM-ready receipt times out and removes handlers',async()=>{
  const f=fixture();await assert.rejects(loadInitialStudio(f.contents,URL,{timeoutMs:10}),{code:'studio_startup_timeout'});f.clean();f.reject(Error('late rejected load'));await tick();
});

test('synchronous load failure is sanitized and cleaned up',async()=>{
  const f=fixture();f.contents.loadURL=()=>{throw Error('private transport detail');};await assert.rejects(loadInitialStudio(f.contents,URL),{code:'studio_startup_load_failed'});f.clean();
});

test('invalid origins and target paths never initiate navigation',async()=>{
  for(const target of ['https://127.0.0.1:8765/control','http://other.example:8765/control','http://127.0.0.1:8765/guest',URL+'#unexpected']){
    const f=fixture();await assert.rejects(loadInitialStudio(f.contents,target),{code:'studio_startup_invalid'});assert.equal(f.contents.loads,0);f.clean();
  }
});

test('Main applies DOM-ready startup only to its initial studio document',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../main.cjs'),'utf8');assert.ok(source.includes("await loadInitialStudio(studio.webContents,origin+'/control?workspace=studio&desktop=1')"));assert.equal((source.match(/await loadInitialStudio\(/g)||[]).length,1);
});
