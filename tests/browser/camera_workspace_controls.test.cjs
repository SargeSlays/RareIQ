const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');

class Element {
  constructor(tag='select'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';this.textContent='';this.disabled=false;this.rebuilds=0;}
  appendChild(child){child.parentElement=this;this.children.push(child);}
  replaceChildren(){this.children=[];this.rebuilds++;}
  get options(){return this.children.flatMap(c=>c.tagName==='OPTGROUP'?c.children:[c]);}
  get selectedOptions(){return this.options.filter(o=>o.value===this.value);}
  cloneNode(){return Object.assign(new Element(this.tagName),{value:this.value,textContent:this.textContent,disabled:this.disabled});}
  setAttribute(){}
  focus(){this.focused=true;}
}
function runtime(){
  const nodes=new Map(),messages=[],writes=[],requests=[];
  for(const id of ['cameraSelect','cameraSlot1Source','stagingSourceSelect','cameraSlot3Source','cameraSlot4Source'])nodes.set(id,new Element());
  const master=nodes.get('cameraSelect');
  for(const [value,text] of [['one','Camera One'],['two','Camera Two'],['three','Camera Three'],['four','Camera Four']]){
    const option=new Element('option');Object.assign(option,{value,textContent:text});master.appendChild(option);
  }
  master.value='one';
  const document={activeElement:null,createElement:tag=>new Element(tag),querySelector:()=>null,querySelectorAll:()=>[]};
  const context=vm.createContext({$:id=>nodes.get(id),document,window:{},
    cameraWorkspacePreferences:{activeSlot:1,layout:'quad',sources:{'1':'one','2':null,'3':null,'4':null},sides:{'1':'unassigned','2':'unassigned','3':'unassigned','4':'unassigned'}},
    cameraWorkspaceSlotStates:{},cameraWorkspaceSlotActions:new Set(),cameraWorkspaceStateSignature:'',secondaryBayPreferences:{stagingSource:null},
    cameraDeviceKeyFromValue:v=>v,decodeCameraValue:v=>({name:v}),sourceIdFromCameraValue:v=>v||null,cameraOptionValue:c=>c.source_id,
    saveCameraWorkspacePreferences:()=>writes.push('workspace'),saveSecondaryBayPreferences:()=>writes.push('secondary'),
    notify:(...args)=>messages.push(args),normalizeCameraWorkspacePreferences:v=>v,alignScanZone(){},renderSecondaryWorkspaceBay(){},
    api:async(url,options)=>{requests.push({url,...options});throw Error('unavailable');}
  });
  vm.runInContext(source.slice(source.indexOf('function cameraWorkspaceSourceOwner('),source.indexOf('function normalizeSecondaryBayPreferences(')),context);
  context.renderCameraWorkspace=()=>context.syncCameraWorkspaceSourceOptions();
  return {context,nodes,document,messages,writes,requests};
}

test('frame IDs cannot invalidate the camera presentation signature',()=>{
  const {context:c}=runtime();
  assert.equal(c.cameraWorkspaceSlotSignature([{slot_id:2,source_id:'two',connected:true,frame_id:1}]),c.cameraWorkspaceSlotSignature([{slot_id:2,source_id:'two',connected:true,frame_id:200}]));
  assert.notEqual(c.cameraWorkspaceSlotSignature([{slot_id:2,connected:true}]),c.cameraWorkspaceSlotSignature([{slot_id:2,connected:false}]));
});
test('stable telemetry preserves all four native dropdown option nodes',()=>{
  const {context:c,nodes}=runtime();c.syncCameraWorkspaceSourceOptions();
  const first=nodes.get('stagingSourceSelect').options[1];
  for(let i=0;i<100;i++)c.syncCameraWorkspaceSourceOptions();
  assert.equal(nodes.get('stagingSourceSelect').rebuilds,1);
  assert.equal(nodes.get('stagingSourceSelect').options[1],first);
  assert.equal(first.disabled,true);
  for(const id of ['cameraSlot1Source','cameraSlot3Source','cameraSlot4Source'])assert.equal(nodes.get(id).rebuilds,1);
});
test('device changes are deferred while a source picker is focused and applied on blur',()=>{
  const {context:c,nodes,document}=runtime();c.syncCameraWorkspaceSourceOptions();
  const select=nodes.get('stagingSourceSelect');document.activeElement=select;
  c.cameraWorkspacePreferences.sources['3']='three';c.syncCameraWorkspaceSourceOptions();assert.equal(select.rebuilds,1);
  document.activeElement=null;c.syncCameraWorkspaceSourceOptions();assert.equal(select.rebuilds,2);
  assert.equal(select.options.find(o=>o.value==='three').disabled,true);
});
test('assignment failure rolls back source choices and persisted secondary preferences',async()=>{
  const app=runtime();await app.context.setCameraWorkspaceSource(2,'two');
  assert.equal(app.context.cameraWorkspacePreferences.sources['2'],null);
  assert.equal(app.context.secondaryBayPreferences.stagingSource,null);
  assert.equal(app.nodes.get('stagingSourceSelect').value,'');
  assert.equal(app.messages.at(-1)[2],'error');assert.ok(app.writes.includes('workspace'));assert.equal(app.writes.filter(x=>x==='secondary').length,2);
});
test('each secondary slot uses its own API and clearing sends null without activating',async()=>{
  for(const slot of [2,3,4]){
    const app=runtime();app.context.api=async(url,options)=>{app.requests.push({url,...options});const body=JSON.parse(options.body);return {slot:{slot_id:slot,source:body.source_id?{source_id:body.source_id}:null,source_id:body.source_id,side:body.side,role:'staging'}};};
    await app.context.setCameraWorkspaceSource(slot,['','one','two','three','four'][slot]);
    assert.equal(app.requests[0].url,`/api/camera-slots/${slot}/source`);assert.equal(app.requests[0].method,'PUT');
    await app.context.setCameraWorkspaceSource(slot,'');assert.equal(JSON.parse(app.requests[1].body).source_id,null);
    assert.equal(app.context.cameraWorkspacePreferences.activeSlot,1);
  }
});
test('owned physical cameras cannot be assigned twice',async()=>{
  const app=runtime();await app.context.setCameraWorkspaceSource(3,'one');assert.equal(app.requests.length,0);assert.equal(app.messages[0][0],'Camera Already Assigned');
});
test('background telemetry cannot overwrite a pending source assignment',()=>{
  const {context:c}=runtime();c.cameraWorkspacePreferences.sources['2']='two';c.cameraWorkspaceSlotActions.add('assign-2');
  c.syncCameraWorkspaceSlotStates([{slot_id:2,source:null,source_id:null,role:'staging'}]);assert.equal(c.cameraWorkspacePreferences.sources['2'],'two');
});
test('Manage Cameras reveals all slots and focuses the first unassigned source',()=>{
  const {context:c,nodes}=runtime();c.setCameraWorkspaceLayout=layout=>{c.cameraWorkspacePreferences.layout=layout;};
  c.manageCameraWorkspace();assert.equal(c.cameraWorkspacePreferences.layout,'quad');assert.equal(nodes.get('stagingSourceSelect').focused,true);
});
