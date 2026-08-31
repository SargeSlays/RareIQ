const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const script=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
const source=script.slice(script.indexOf('const CREATOR_WORKSPACE_VIEW_KEY='),script.indexOf('const BROADCAST_WORKSPACE_PANELS='));
function setup(saved='rules'){
  const nodes=new Map(),writes=[];
  const get=id=>{if(!nodes.has(id))nodes.set(id,{hidden:false});return nodes.get(id);};
  const buttons=['rules','live','assets','chase'].map(view=>({dataset:{creatorView:view},attributes:{},handlers:{},classList:{toggle(){}},
    setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,fn){this.handlers[k]=fn;},focus(){this.focused=true;}}));
  const tabs={querySelectorAll:()=>buttons};nodes.set('creatorWorkspaceTabs',tabs);
  const frame={dataset:{src:'/creator/set-chase?embed=creator'},loads:0,hasAttribute(){return this.loads>0;},set src(value){this.url=value;this.loads++;}};
  nodes.set('creatorChaseFrame',frame);
  const heading={querySelector:get},content={querySelector:()=>heading,scrollTo(){}},layout={};
  const workspace={dataset:{},querySelector:q=>q==='.creator-reveal-layout'?layout:content};
  const context=vm.createContext({document:{querySelector:()=>workspace},$:get,window:{matchMedia:()=>({matches:true})},
    localStorage:{getItem:()=>saved,setItem:(...args)=>writes.push(args)}});
  vm.runInContext(source+'\ninitializeCreatorWorkspace();',context);
  return {get,buttons,frame,workspace,layout,writes,select:view=>vm.runInContext(`setCreatorWorkspaceView(${JSON.stringify(view)})`,context)};
}
test('Creator lazily opens Set Chase once and leaves its draft document intact across tab changes',()=>{
  const app=setup();assert.equal(app.frame.loads,0);assert.equal(app.get('creatorChasePanel').hidden,true);
  app.select('chase');assert.equal(app.frame.loads,1);assert.equal(app.frame.url,'/creator/set-chase?embed=creator');
  const draft={unsaved:true};app.frame.document=draft;
  for(const view of ['rules','live','assets']){
    app.select(view);assert.equal(app.get('creatorChasePanel').hidden,true);
    app.select('chase');assert.equal(app.get('creatorChasePanel').hidden,false);
    assert.equal(app.frame.document,draft);assert.equal(app.frame.loads,1);assert.equal(app.layout.hidden,true);
  }
  assert.equal(app.get('h2').textContent,'Set Chase Bar');
});
test('saved Chase view loads once and keyboard navigation maintains one selected tab',()=>{
  const app=setup('chase');assert.equal(app.frame.loads,1);
  app.buttons[3].handlers.keydown({key:'Home',preventDefault(){}});
  assert.equal(app.workspace.dataset.creatorView,'rules');assert.equal(app.buttons[0].focused,true);
  app.buttons[0].handlers.keydown({key:'End',preventDefault(){}});
  assert.equal(app.workspace.dataset.creatorView,'chase');assert.equal(app.buttons[3].focused,true);
  assert.equal(app.frame.loads,1);assert.equal(app.buttons.filter(b=>b.attributes['aria-selected']==='true').length,1);
  assert.equal(app.buttons.filter(b=>b.tabIndex===0).length,1);
});
test('unknown saved Creator views fall back without loading an offscreen editor',()=>{
  const app=setup('obsolete');assert.equal(app.workspace.dataset.creatorView,'rules');assert.equal(app.frame.loads,0);
});
