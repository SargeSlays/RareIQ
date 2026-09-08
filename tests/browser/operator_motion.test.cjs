const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/producer-please.motion.js'),'utf8');
function fixture({saved=null,blocked=false,reduced=false}={}){
  class Node {
    constructor(tag='DIV'){this.tagName=tag;this.attrs={};this.children=[];this.handlers={};this.isConnected=true;this.parentElement=null;this.calls=[];this.style={setProperty(){},removeProperty(){}};}
    setAttribute(k,v){this.attrs[k]=String(v)} getAttribute(k){return this.attrs[k]??null} hasAttribute(k){return k in this.attrs} removeAttribute(k){delete this.attrs[k]}
    addEventListener(k,f){(this.handlers[k]??=[]).push(f)} removeEventListener(k,f){this.handlers[k]=(this.handlers[k]||[]).filter(x=>x!==f)}
    dispatchEvent(e){for(const f of this.handlers[e.type]||[])f(e)}
    appendChild(n){n.parentElement=this;this.children.push(n);return n}
    contains(n){return this===n||this.children.some(c=>c.contains(n))}
    matches(selector){return selector.split(',').some(s=>{s=s.trim();if(s===':disabled')return this.disabled;const a=s.match(/^\[([^=\]]+)(?:="([^"]+)")?\]$/);return a?this.hasAttribute(a[1])&&(a[2]===undefined||this.getAttribute(a[1])===a[2]):this.tagName.toLowerCase()===s})}
    closest(s){return this.matches(s)?this:this.parentElement?.closest(s)||null}
    querySelectorAll(s){return this.children.flatMap(c=>[...(c.matches(s)?[c]:[]),...c.querySelectorAll(s)])}
    querySelector(s){return this.querySelectorAll(s)[0]||null}
    getBoundingClientRect(){return {width:100,height:50,top:10,left:10,right:110,bottom:60}}
    animate(frames,options){let resolve,reject;const animation={finished:new Promise((a,b)=>{resolve=a;reject=b}),finish:()=>resolve(),cancel:()=>reject(Error('cancelled'))};this.calls.push({frames,options,animation});return animation}
  }
  const root=new Node();root.setAttribute('data-pp-motion-root','');
  const document=new Node();document.hidden=false;document.createElement=tag=>new Node(tag.toUpperCase());
  const media=new Node();media.matches=reduced;
  const storage={value:saved,getItem(){if(blocked)throw Error('blocked');return this.value},setItem(k,v){if(blocked)throw Error('blocked');this.value=v}};
  const window=new Node();Object.assign(window,{Element:Node,HTMLElement:Node,document,localStorage:storage,matchMedia:()=>media,innerWidth:1920,innerHeight:1080,cancelAnimationFrame(){},clearTimeout(){}});
  const context={window,document,Element:Node,CustomEvent:class{constructor(type,options){this.type=type;Object.assign(this,options)}}};
  vm.runInNewContext(source,context);
  const motion=window.PPMotion.create(root);
  return {window,root,document,media,storage,motion,node(tag='DIV',parent=root,attrs={}){const n=parent.appendChild(new Node(tag));for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n}};
}
test('one controller per root, persisted modes, and streaming/OS limits retain preference',()=>{
  const f=fixture({saved:'expressive'});assert.equal(f.motion,f.window.PPMotion.create(f.root));
  assert.equal(f.motion.status().persisted,true);f.motion.setOnAir(true);assert.equal(f.motion.status().effective,'studio');assert.equal(f.motion.status().preferred,'expressive');
  f.media.matches=true;f.media.dispatchEvent({type:'change'});assert.equal(f.motion.status().effective,'reduced');
  f.motion.setMode('off');assert.equal(f.motion.status().effective,'off');
  f.media.matches=false;f.motion.setOnAir(false);f.motion.setMode('voltage');assert.equal(f.motion.status().preferred,'off');
});
test('blocked storage applies in memory without claiming persistence',()=>{
  const f=fixture({blocked:true});assert.equal(f.motion.setMode('studio'),true);assert.equal(f.motion.status().preferred,'studio');assert.equal(f.motion.status().persisted,false);
});
test('storage events update effective preference and expose removed/invalid records',()=>{
  const f=fixture();f.window.dispatchEvent({type:'storage',key:'producerplease.operator.motion.v1',newValue:'reduced'});assert.equal(f.motion.status().effective,'reduced');assert.equal(f.motion.status().persisted,true);
  f.window.dispatchEvent({type:'storage',key:'producerplease.operator.motion.v1',newValue:null});assert.equal(f.motion.status().preferred,'expressive');assert.equal(f.motion.status().persisted,false);
});
test('media, artwork, excluded branches and containing panels cannot animate',async()=>{
  const f=fixture();const targets=[f.root];
  for(const tag of ['VIDEO','CANVAS','IFRAME','IMG','PICTURE']){const box=f.node();targets.push(box,f.node(tag,box));}
  const excluded=f.node('DIV',f.root,{'data-pp-motion-exclude':''});targets.push(excluded,f.node('SPAN',excluded));
  const nested=f.node('DIV',f.root,{'data-pp-motion-root':''});targets.push(f.node('SPAN',nested));
  for(const node of targets){assert.equal(await f.motion.play(node,'confirm'),false);assert.equal(node.calls.length,0)}
});
test('same recognition state is finite; cancellation and off mode preserve state',async()=>{
  const f=fixture(),panel=f.node(),rail=f.node('SPAN',panel,{'data-ppm-scan-rail':''});
  f.motion.setState(panel,'scanning');f.motion.setState(panel,'scanning');assert.equal(rail.calls.length,1);assert.equal(rail.calls[0].options.iterations,3);
  f.motion.setMode('off');await Promise.resolve();f.motion.setState(panel,'found');assert.equal(panel.getAttribute('data-ppm-state'),'found');assert.equal(rail.calls.length,1);
});
test('button feedback preserves stationary native target and never invents completion',async()=>{
  const f=fixture(),button=f.node('BUTTON',f.root,{'data-ppm':'button'});
  f.root.dispatchEvent({type:'click',target:button});assert.equal(button.calls.length,0);
  const face=f.node('SPAN',button,{'data-ppm-face':''});f.root.dispatchEvent({type:'click',target:face});assert.equal(face.calls.length,1);assert.equal(button.calls.length,0);assert.equal(button.getAttribute('data-ppm-state'),null);
  f.motion.destroy();await Promise.resolve();assert.equal(f.motion.status().destroyed,true);assert.equal(f.root.handlers.click.length,0);
});
test('hidden-tab cancellation removes active effects and permits no new effects',async()=>{
  const f=fixture(),node=f.node();const pending=f.motion.play(node,'confirm');f.document.hidden=true;f.document.dispatchEvent({type:'visibilitychange'});
  assert.equal(await pending,false);assert.equal(f.motion.status().activeAnimations,0);assert.equal(await f.motion.play(node,'confirm'),false);
});
