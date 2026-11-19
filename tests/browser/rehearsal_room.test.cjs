'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../rareiq/web/static/rehearsal_room.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(output=false){
  const children=[],timers=new Map(),requests=[],window={},doc={readyState:'loading',addEventListener(){},documentElement:{dataset:{}},querySelector:()=>output?{append:value=>children.push(value)}:null,createElement:()=>({dataset:{},setAttribute(){},hidden:false,textContent:''}),body:{prepend:value=>children.push(value)}};let seq=0,reply={active:false,mode:'production',generation:'11111111111111111111111111111111'},failed=false;
  const request=async(url,options)=>{requests.push({url,options});return {ok:!failed,json:async()=>reply};};
  vm.runInNewContext(source,{window,document:doc,fetch:request,setTimeout:(fn,delay)=>{const id=++seq;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)});
  const editor=window.ProducerRehearsalBadge.create();return {editor,children,timers,requests,doc,setReply:value=>{reply=value;},setFailed:value=>{failed=value;},async poll(){const [id,task]=[...timers.entries()][0];timers.delete(id);task.fn();await tick();}};
}
test('production stays unmarked and active output gets a captured warning with public-safe reads only',async()=>{
  const f=fixture(true);await tick();assert.equal(f.children[0].hidden,true);assert.match(f.children[0].className,/rehearsal-output-watermark/);f.setReply({active:true,mode:'rehearsal',generation:'22222222222222222222222222222222',private_label:'must not display'});await f.poll();assert.equal(f.children[0].hidden,false);assert.equal(f.children[0].textContent,'REHEARSAL — not broadcasting');assert.equal(f.doc.documentElement.dataset.rehearsalMode,'active');assert.equal(f.doc.documentElement.dataset.rehearsalGeneration,'2'.repeat(32));assert.equal(f.requests[0].url,'/api/guest/rehearsal');assert.equal(f.requests[0].options.cache,'no-store');assert.doesNotMatch(f.children[0].textContent,/must not display/);f.editor.close();
});
test('failed and malformed refreshes retain rehearsal warning, back off and clear only on confirmed production',async()=>{
  const f=fixture();await tick();f.setReply({active:true,mode:'entering',generation:'22222222222222222222222222222222'});await f.poll();f.setFailed(true);await f.poll();assert.equal(f.children[0].hidden,false);assert.equal(f.children[0].textContent,'REHEARSAL — status unavailable');assert.equal([...f.timers.values()][0].delay,2000);assert.equal(f.doc.documentElement.dataset.rehearsalGeneration,'2'.repeat(32));f.setFailed(false);f.setReply({mode:'production'});await f.poll();assert.equal(f.children[0].hidden,false);f.setReply({active:false,mode:'production',generation:'33333333333333333333333333333333'});await f.poll();assert.equal(f.children[0].hidden,true);f.editor.close();assert.equal(f.timers.size,0);
});
test('close invalidates an in-flight public read and never schedules another request',async()=>{
  const f=fixture();await tick();f.editor.close();let finish;const doc=f.doc;assert.equal(f.children.length,1);
  const sourceWindow={};vm.runInNewContext(source,{window:sourceWindow,document:doc,fetch:()=>new Promise(resolve=>{finish=()=>resolve({ok:true,json:async()=>({active:true,mode:'rehearsal'})});}),setTimeout:()=>{throw Error('closed callback scheduled a request');},clearTimeout(){}});const instance=sourceWindow.ProducerRehearsalBadge.create();instance.close();finish();await tick();assert.equal(f.children.at(-1).hidden,true);
});
