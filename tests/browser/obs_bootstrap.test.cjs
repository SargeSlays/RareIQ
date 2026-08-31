const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
function runtime(result){
  const messages=[],nodes=new Map();
  function node(){return {dataset:{},children:[],fields:{},querySelector(key){return this.fields[key]??=node();},replaceChildren(...children){this.children=children;}};}
  for(const id of ['obsBootstrapStatus','obsBootstrapCreate','obsBootstrapPlan'])nodes.set(id,node());
  const context=vm.createContext({$:id=>nodes.get(id),document:{createElement:node},location:{origin:'http://127.0.0.1:9040'},
    confirm:()=>true,api:async()=>({bootstrap:result}),renderObsStatus(){},notify:(...args)=>messages.push(args)});
  vm.runInContext(source.slice(source.indexOf('function renderObsBootstrap('),source.indexOf('function renderRecordingSettings(')),context);
  return {context,nodes,messages};
}
test('OBS source failures stay blocked and cannot emit a success notification',async()=>{
  const app=runtime({dry_run:false,ready:false,plan:[],diagnostic:{message:'1 browser source failed'}});
  await app.context.bootstrapObs(false);
  assert.equal(app.nodes.get('obsBootstrapCreate').disabled,true);
  assert.equal(app.nodes.get('obsBootstrapStatus').dataset.state,'blocked');
  assert.equal(app.messages[0][0],'OBS Setup Incomplete');
  assert.equal(app.messages[0][2],'error');
});
test('OBS preview distinguishes completing an empty scene from preserving existing content',()=>{
  const app=runtime({});
  app.context.renderObsBootstrap({dry_run:true,ready:true,plan:[{scene:'RareIQ Program',action:'complete'},{scene:'RareIQ Graphics',action:'preserve'}]});
  const rows=app.nodes.get('obsBootstrapPlan').children;
  assert.equal(rows[0].querySelector('span').textContent,'COMPLETE EMPTY SCENE');
  assert.equal(rows[1].querySelector('span').textContent,'PRESERVE');
});
test('OBS successful setup reports accurate preserved scenes',async()=>{
  const app=runtime({dry_run:false,ready:true,created:[{scene:'RareIQ Program'}],preserve_count:5,create_count:0,mapped:{'main-card':'RareIQ Program'}});
  await app.context.bootstrapObs(false);
  assert.equal(app.messages[0][2],'success');
  assert.match(app.messages[0][1],/1 created · 5 preserved · 1 cues mapped/);
  assert.equal(app.nodes.get('obsBootstrapStatus').querySelector('strong').textContent,'SETUP COMPLETE');
});

test('OBS preview labels the chase strip size without losing preservation status',()=>{
  const app=runtime({});
  app.context.renderObsBootstrap({dry_run:true,ready:true,plan:[{scene:'RareIQ Set Chase',url:'http://127.0.0.1:9040/overlay/set-chase',width:1280,height:320,placement:'bottom-center',action:'preserve'}]});
  const row=app.nodes.get('obsBootstrapPlan').children[0];
  assert.equal(row.querySelector('small').textContent,'1280 × 320 · Bottom strip · Silent');
  assert.equal(row.querySelector('span').textContent,'PRESERVE');
});

test('disconnected OBS preview does not pretend existing scenes were inspected',()=>{
  const app=runtime({});
  app.context.renderObsBootstrap({dry_run:true,ready:false,plan:[{scene:'RareIQ Set Chase',width:1280,height:320,placement:'bottom-center'}]});
  assert.equal(app.nodes.get('obsBootstrapCreate').disabled,true);
  assert.equal(app.nodes.get('obsBootstrapPlan').children[0].querySelector('span').textContent,'CONNECT TO INSPECT');
});
