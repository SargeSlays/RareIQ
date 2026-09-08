const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
const code=source.slice(source.indexOf('const productionInputThumbnails='),source.indexOf('async function loadProductionSwitcher('))+'\n'+source.slice(source.indexOf('function renderProductionScenes('),source.indexOf('async function loadProductionScenes('));
function element(tag){
  const attributes=new Map(),node={tag,dataset:{},children:[],hidden:false,textContent:'',className:'',listeners:new Map(),classList:{toggle(){}},
    setAttribute(key,value){attributes.set(key,String(value));},getAttribute(key){return attributes.get(key)??null;},removeAttribute(key){attributes.delete(key);},
    append(child){child.parent=this;this.children.push(child);},replaceChildren(...children){this.children=children;},
    querySelector(selector){return this.children.find(child=>selector==='img'?child.tag==='img':selector==='.production-input-empty'?child.className==='production-input-empty':false)||null;},
    cloneNode(){const clone=element(this.tag);clone.alt=this.alt;return clone;},
    replaceWith(replacement){const index=this.parent.children.indexOf(this);this.parent.children[index]=replacement;replacement.parent=this.parent;this.parent=null;},
    addEventListener(name,handler){this.listeners.set(name,handler);}};
  Object.defineProperty(node,'src',{get(){return attributes.get('src')||'';},set(value){attributes.set('src',value);}});
  return node;
}
function app(){
  const buttons=Array.from({length:4},(_,index)=>{const button=element('button');button.dataset.productionSlot=String(index+1);button.append(Object.assign(element('span'),{textContent:`INPUT ${index+1}`}));button.append(Object.assign(element('strong'),{textContent:`Camera ${index+1}`}));button.append(element('img'));button.addEventListener('click',()=>{});return button;});
  const grid=element('div'),nodes={productionSceneGrid:grid},context=vm.createContext({WeakMap,productionSwitcherState:{},productionScenes:[],$:id=>nodes[id]||null,document:{createElement:element,querySelectorAll:()=>buttons}});
  vm.runInContext(code,context);
  const render=slots=>context.renderProductionSwitcher({program_slot:1,preview_slot:2,slots,generation:1});
  return {context,buttons,grid,render};
}
test('missing and offline inputs hide and clear thumbnails with readable fallback and unchanged slot controls',()=>{
  const ui=app(),button=ui.buttons[2],click=button.listeners.get('click');
  button.querySelector('img').src='/api/camera-slots/3/stream';
  ui.render([{slot_id:4,source_id:'four',connected:false}]);
  assert.equal(button.dataset.thumbnailState,'unassigned');assert.equal(button.querySelector('img').hidden,true);assert.equal(button.querySelector('img').getAttribute('src'),null);
  assert.equal(button.querySelector('.production-input-empty').textContent,'No source assigned');
  assert.equal(button.getAttribute('aria-describedby'),'productionInputStatus3');assert.equal(button.disabled,true);
  assert.equal(ui.buttons[3].querySelector('.production-input-empty').textContent,'Source offline');
  assert.equal(button.children[0].textContent,'INPUT 3');assert.equal(button.children[1].textContent,'Camera 3');assert.equal(button.listeners.get('click'),click);
});
test('image error hides broken preview and existing source refresh recovers without replacing the button',()=>{
  const ui=app(),slots=[{slot_id:3,source_id:'three',connected:true}],button=ui.buttons[2];ui.render(slots);
  const first=button.querySelector('img');assert.equal(button.dataset.thumbnailState,'loading');assert.equal(first.hidden,true);
  first.onerror();assert.equal(button.dataset.thumbnailState,'error');assert.equal(first.getAttribute('src'),null);assert.equal(first.hidden,true);
  assert.match(button.querySelector('.production-input-empty').textContent,/Refresh Sources/);
  ui.render(slots);const second=button.querySelector('img');assert.notEqual(first,second);assert.match(second.src,/camera-slots\/3\/stream/);
  second.onload();assert.equal(second.hidden,false);assert.equal(button.querySelector('.production-input-empty').hidden,true);assert.equal(button.dataset.thumbnailState,'ready');assert.equal(button.disabled,false);
  ui.render(slots);assert.equal(button.querySelector('img'),second);assert.equal(button.children.filter(child=>child.className==='production-input-empty').length,1);
});
test('events from old assignment cannot replace current availability or hide a recovered thumbnail',()=>{
  const ui=app(),button=ui.buttons[2];ui.render([{slot_id:3,source_id:'old',connected:true}]);const old=button.querySelector('img');
  ui.render([{slot_id:3,source_id:'new',connected:true}]);const current=button.querySelector('img');current.onload();old.onerror();
  assert.equal(button.dataset.thumbnailState,'ready');assert.equal(current.hidden,false);
  ui.render([]);current.onload();assert.equal(button.dataset.thumbnailState,'unassigned');assert.equal(current.hidden,true);
});
test('empty scenes explain existing creation controls without adding buttons',()=>{
  const ui=app();ui.context.renderProductionScenes([]);
  assert.equal(ui.grid.children.length,1);assert.equal(ui.grid.children[0].tag,'p');
  assert.match(ui.grid.children[0].textContent,/Save Current/);assert.match(ui.grid.children[0].textContent,/New Scene/);
});
