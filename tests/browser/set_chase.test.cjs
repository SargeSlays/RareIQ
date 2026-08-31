const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const folder=path.resolve(__dirname,'../../rareiq/web/static');
const model=require(path.join(folder,'set_chase_state.js'));
const cards=n=>Array.from({length:n},(_,i)=>({id:String(i),name:`Card ${i}`}));
test('case hits rotate first, top hits next; no omissions or duplicate padding',()=>{
  const pages=model.pages({cards_per_page:4,case_hits:cards(7),top_hits:cards(5)});
  assert.deepEqual(pages.map(p=>[p.group,p.cards.length,p.start]),[['case_hits',4,0],['case_hits',3,4],['top_hits',4,0],['top_hits',1,4]]);
});
test('three-card mode, empty groups and a single card remain valid',()=>{
  assert.deepEqual(model.pages({}),[]);
  assert.deepEqual(model.pages({cards_per_page:3,top_hits:cards(7)}).map(p=>p.cards.length),[3,3,1]);
  assert.equal(model.pages({case_hits:cards(1)})[0].cards.length,1);
});
test('shared epoch math wraps deterministically, including reconnects and late tabs',()=>{
  for(const [ms,page] of [[0,0],[7999,0],[8000,1],[23999,2],[24000,0],[80000,1]])assert.equal(model.position(3,8,ms).index,page);
  assert.deepEqual(model.position(3,8,-20),{index:0,progress:0});
  assert.equal(model.position(1,8,1000).progress,1);
  assert.equal(model.position(3,8,4000).progress,.5);
});
test('artwork rejects external, executable and encoded traversal URLs',()=>{
  for(const url of ['https://a.test/card','javascript:alert(1)','//evil.test/card','/api/catalog-engine/image/en/../x','/api/catalog-engine/image/en/%2e%2e','/api/catalog-engine/image/en/%252e%252e','/api/catalog-engine/image/en/a?key=x','/api/catalog-engine/image/en/a\\b'])assert.equal(model.artwork(url),'');
  assert.equal(model.artwork('/api/catalog-engine/image/en_set/card.png'),'/api/catalog-engine/image/en_set/card.png');
});
function renderer({preview=false}={}){
  class Node{constructor(){this.children=[];this.hidden=true;this.style={setProperty(key,value){this[key]=value;}};} append(...n){this.children.push(...n);} replaceChildren(...n){this.children=n;}}
  const elements=new Map(),timers=new Map();let options,id=0,now=0;
  const get=id=>{if(!elements.has(id))elements.set(id,new Node());return elements.get(id);};
  const context=vm.createContext({document:{getElementById:get,createElement:()=>new Node(),documentElement:{classList:{add(){}}}},location:{search:preview?'?preview=1':''},URLSearchParams,
    performance:{now:()=>now},window:{RareIQSetChase:model,RareIQOverlay:{start:o=>{options=o;}}},
    setInterval:fn=>{timers.set(++id,fn);return id;},clearInterval:id=>timers.delete(id)});
  vm.runInContext(fs.readFileSync(path.join(folder,'overlay_set_chase.js'),'utf8'),context);
  return {get,options,timers,tick(ms){now+=ms;for(const fn of timers.values())fn();}};
}
test('polling unchanged state does not rebuild cards; draft revision cannot reset live pages',()=>{
  const app=renderer(),payload={visible:true,config:{set_name:'Test',set_id:'test',language:'English',cards_per_page:4,seconds_per_page:8,case_hits:cards(5)},theme:{accent:'#8be8ca'},started_at_ms:1000,server_now_ms:1000};
  app.options.render(payload);const first=app.get('chaseCards').children[0];
  app.options.render({...payload,revision:9});assert.equal(app.get('chaseCards').children[0],first);
  app.tick(8000);assert.equal(app.get('chaseRange').textContent,'5–5 of 5');
  assert.equal(app.get('chaseCards').style['--chase-columns'],'1');
  app.options.clear();assert.equal(app.timers.size,0);assert.equal(app.get('chaseStrip').hidden,true);
});
test('empty and offline outputs are transparent and have no animation timer',()=>{
  const app=renderer();app.options.render({visible:false});assert.equal(app.timers.size,0);assert.equal(app.get('chaseEmpty').hidden,true);
  app.options.render({visible:true,config:{},server_now_ms:1});assert.equal(app.timers.size,0);assert.equal(app.get('chaseStrip').hidden,true);
});
test('source is silent, transparent, full-card and reduced-motion aware',()=>{
  const css=fs.readFileSync(path.join(folder,'overlay_set_chase.css'),'utf8');
  assert.match(css,/object-fit:contain/);assert.match(css,/background:transparent/);assert.match(css,/prefers-reduced-motion/);
  const js=fs.readFileSync(path.join(folder,'overlay_set_chase.js'),'utf8');assert.doesNotMatch(js,/innerHTML|new Audio|\.play\(/);
});

test('preview distinguishes an empty draft from a disconnected source and recovers',()=>{
  const app=renderer({preview:true});
  app.options.render({visible:false});assert.match(app.get('chaseEmpty').textContent,/Save a set/);
  app.options.render({visible:true,config:{},server_now_ms:1});assert.match(app.get('chaseEmpty').textContent,/Add cards/);
  app.options.clear();assert.match(app.get('chaseEmpty').textContent,/Connection lost/);
  assert.equal(app.get('chaseEmpty').hidden,false);assert.equal(app.timers.size,0);
  app.options.render({visible:true,config:{case_hits:cards(1)},server_now_ms:1});
  assert.equal(app.get('chaseEmpty').hidden,true);assert.equal(app.get('chaseStrip').hidden,false);
});

test('reconnected broadcast resumes its shared page and never displays preview error text',()=>{
  const app=renderer(),config={seconds_per_page:8,case_hits:cards(5)};
  app.options.render({visible:true,config,started_at_ms:1000,server_now_ms:1000});
  app.options.clear();assert.equal(app.get('chaseEmpty').hidden,true);
  app.options.render({visible:true,config,started_at_ms:1000,server_now_ms:10000});
  assert.equal(app.get('chaseRange').textContent,'5–5 of 5');assert.equal(app.get('chaseEmpty').hidden,true);
  assert.equal(app.timers.size,1);
});
