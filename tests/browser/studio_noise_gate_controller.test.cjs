const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture(){
  let resolve,reject;const ready=new Promise((a,b)=>{resolve=a;reject=b;}),nodes=[],states=[];
  const input={links:new Set(),connect(n){this.links.add(n);},disconnect(n){this.links.delete(n);}},output={};
  const context={audioWorklet:{calls:0,addModule(){this.calls++;return ready;}}};
  const host={AudioWorkletNode:class{constructor(){this.port={postMessage:m=>this.message=m,close(){}};nodes.push(this);}connect(){}disconnect(){}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../rareiq/web/static/studio_noise_gate.js'),'utf8'),{window:host});
  return {input,output,context,nodes,states,resolve,reject,gate:host.StudioNoiseGate.create(context,input,output,s=>states.push(s))};
}
test('gate stays bypassed until requested and disabling during load preserves bypass',async()=>{
  const f=fixture();await f.gate.configure({enabled:false});assert.equal(f.context.audioWorklet.calls,0);
  const pending=f.gate.configure({enabled:true});await Promise.resolve();await f.gate.configure({enabled:false});f.resolve();await pending;
  assert.equal(f.nodes.length,0);assert.ok(f.input.links.has(f.output));assert.equal(f.states.at(-1),'Off');
});
test('single loading node accepts latest threshold and restores bypass on failure',async()=>{
  const f=fixture(),a=f.gate.configure({enabled:true,thresholdDb:-45}),b=f.gate.configure({enabled:true,thresholdDb:-30});f.resolve();await Promise.all([a,b]);
  assert.equal(f.context.audioWorklet.calls,1);assert.equal(f.nodes.length,1);assert.equal(f.nodes[0].message.thresholdDb,-30);assert.ok(!f.input.links.has(f.output));
  f.nodes[0].onprocessorerror();assert.ok(f.input.links.has(f.output));assert.equal(f.states.at(-1),'Unavailable · audio unfiltered');
});
test('closing during load never reconnects an abandoned graph',async()=>{
  const f=fixture(),pending=f.gate.configure({enabled:true});f.gate.close();f.resolve();await pending;assert.equal(f.nodes.length,0);
});
test('module failure leaves audio passing and allows a retry',async()=>{
  const f=fixture(),pending=f.gate.configure({enabled:true});f.reject(Error('load failed'));await pending;assert.ok(f.input.links.has(f.output));
  f.context.audioWorklet.addModule=async()=>{};await f.gate.configure({enabled:true});assert.equal(f.nodes.length,1);
});
