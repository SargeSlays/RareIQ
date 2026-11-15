const test=require('node:test');
const assert=require('node:assert/strict');
const {ProductionSceneEdits}=require('../../rareiq/web/static/production_scene_edits.js');
test('polling cannot silently rebase an open scene draft',()=>{
  const edits=new ProductionSceneEdits(()=> 'request-one');edits.loaded(3);edits.begin();edits.loaded(4);
  assert.equal(edits.prepare({name:'draft'}).expected_revision,3);
  edits.begin();assert.equal(edits.prepare({name:'draft'}).expected_revision,4);
});
test('uncertain retries reuse their ID but changed payloads get a new one',()=>{
  let id=0;const edits=new ProductionSceneEdits(()=> String(++id));edits.loaded(0);edits.begin();
  assert.deepEqual(edits.prepare({name:'one'}),edits.prepare({name:'one'}));
  assert.equal(edits.prepare({name:'two'}).request_id,'2');
  edits.saved(1);assert.throws(()=>edits.prepare({name:'two'}));
});
test('saving before the first scene snapshot is blocked',()=>{
  const edits=new ProductionSceneEdits();assert.throws(()=>edits.begin());assert.throws(()=>edits.loaded(undefined));
});
test('paired HTTP clients can create request IDs without randomUUID',()=>{
  const id=ProductionSceneEdits.requestId({getRandomValues:array=>array.fill(11)});
  assert.equal(id,'0b'.repeat(16));
});
test('late acknowledgements cannot move a newer observed snapshot backwards',()=>{
  const edits=new ProductionSceneEdits(()=> 'request-one');edits.loaded(0);edits.begin();edits.loaded(2);
  edits.saved(1);assert.equal(edits.revision,2);edits.loaded(1);assert.equal(edits.revision,2);
});
test('every Studio entry point loads the shared edit model before the controller',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const directory=path.resolve(__dirname,'../../rareiq/web/static');let checked=0;
  for(const name of fs.readdirSync(directory).filter(name=>name.endsWith('.html'))){
    const html=fs.readFileSync(path.join(directory,name),'utf8');
    const controller=html.indexOf('src="/static/studiox.js');if(controller<0)continue;
    const model=html.indexOf('src="/static/production_scene_edits.js');
    assert.ok(model>=0&&model<controller,name+' must load the scene edit model first');checked++;
  }
  assert.ok(checked>1,'Include both the main Studio and legacy entry points');
});
