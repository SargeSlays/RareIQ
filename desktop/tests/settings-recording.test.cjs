'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createController,normalize,mount}=require('../settings-recording.js');
const record=(extra={})=>({phase:'idle',active:false,ownershipPending:false,canStart:true,available:true,finalized:false,fileName:null,frames:0,audioSamples:0,bytesWritten:0,elapsedMs:0,...extra});
const running=extra=>record({phase:'recording',active:true,canStart:false,...extra});
const reply=extra=>({ok:true,recording:record(extra)});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function fixture(){const calls=[],busy=[],changes=[],installed=[];let serial=0;const f={calls,busy,changes,installed,response:reply()};f.controller=createController({request:async value=>{calls.push(value);return typeof f.response==='function'?f.response(value):structuredClone(f.response);},onChange:value=>changes.push(value),onStatus:value=>installed.push(value),onBusy:value=>busy.push(value),randomId:()=>`request-${++serial}`});f.controller.setContext({recording:record(),locked:false,publishingBlocked:false});return f;}
test('Start fails closed for unavailable, locked, rehearsal, stale, unready or owned output',async()=>{
  const contexts=[{recording:record({available:false})},{locked:true},{publishingBlocked:true},{recording:record({canStart:false})},{recording:running()},{recording:record({ownershipPending:true})},{recording:{phase:'unknown'}}];
  for(const context of contexts){const f=fixture();f.controller.setContext(context);assert.equal(await f.controller.run('start'),false);assert.equal(f.calls.length,0,JSON.stringify(context));}
});
test('repeated Start clicks create one exact request and mutation busy is balanced',async()=>{
  const f=fixture(),pending=deferred();f.response=()=>pending.promise;const first=f.controller.run('start');assert.equal(await f.controller.run('start'),false);assert.equal(f.calls.length,1);assert.deepEqual(f.calls[0],{action:'start',requestId:'request-1'});assert.deepEqual(f.busy,[true]);pending.resolve(reply({phase:'recording',active:true,canStart:false}));assert.equal(await first,true);assert.deepEqual(f.busy,[true,false]);assert.equal(f.controller.snapshot().working,'');
});
test('Stop supersedes pending Start and late success cannot restore its running state',async()=>{
  const f=fixture(),pending=deferred();f.response=value=>value.action==='start'?pending.promise:reply();const first=f.controller.run('start');assert.equal(await f.controller.run('stop'),true);pending.resolve(reply({phase:'recording',active:true,canStart:false}));assert.equal(await first,false);assert.equal(f.controller.snapshot().recording.active,false);assert.deepEqual(f.calls.map(value=>value.action),['start','stop']);assert.equal(f.busy.at(-1),false);
});
test('failed status preserves an independent Stop for an already active recorder',async()=>{
  const f=fixture();f.controller.setContext({recording:running()});f.response=async()=>{throw Error('private path detail');};assert.equal(await f.controller.run('status'),false);assert.equal(f.controller.snapshot().stale,true);assert.equal(await f.controller.run('start'),false);assert.equal(f.controller.snapshot().message.includes('private'),false);f.response=reply();assert.equal(await f.controller.run('stop'),true);assert.deepEqual(f.calls.map(value=>value.action),['status','stop']);
});
test('uncertain Start retains Stop even when the last known status was idle',async()=>{
  const f=fixture();f.response=async()=>{throw Error('synthetic lost response');};assert.equal(await f.controller.run('start'),false);f.response=reply();assert.equal(await f.controller.run('stop'),true);assert.deepEqual(f.calls.map(value=>value.action),['start','stop']);
});
test('an unconfirmed Start keeps the exact retry ID through a read-only status refresh',async()=>{
  const f=fixture();f.response=async()=>{throw Error('synthetic lost response');};await f.controller.run('start');const original=f.calls[0];f.response=reply();assert.equal(await f.controller.run('status'),true);assert.equal(await f.controller.run('retry'),true);assert.deepEqual(f.calls.at(-1),original);
});
test('chooser cancellation retires its request so a deliberate new Start gets a fresh ID',async()=>{
  const f=fixture();await f.controller.run('start');assert.equal(f.controller.snapshot().recording.active,false);await f.controller.run('start');assert.deepEqual(f.calls.map(value=>value.requestId),['request-1','request-2']);
});
test('missing or malformed successful status never enables another Start',async()=>{
  for(const response of [{ok:true},{ok:true,recording:{phase:'unknown'}}]){const f=fixture();f.response=response;assert.equal(await f.controller.run('start'),false);assert.equal(f.controller.snapshot().stale,true);assert.equal(await f.controller.run('start'),false);assert.equal(f.calls.length,1);}
});
test('Settings close retires pending UI callbacks without issuing Stop',async()=>{
  const f=fixture(),pending=deferred();f.response=()=>pending.promise;const start=f.controller.run('start');f.controller.close();pending.resolve(reply({phase:'recording',active:true,canStart:false}));assert.equal(await start,false);assert.deepEqual(f.calls.map(value=>value.action),['start']);assert.equal(await f.controller.run('stop'),false);assert.equal(f.busy.at(-1),false);
});
test('only safe counters and a basename are rendered from native status',()=>{
  const sanitized=normalize(record({frames:-1,audioSamples:Infinity,bytesWritten:'50',elapsedMs:'3000',fileName:'C:private.mkv',reason:'F:/private/key'}));assert.equal(sanitized.frames,0);assert.equal(sanitized.audioSamples,0);assert.equal(sanitized.bytesWritten,0);assert.equal(sanitized.elapsedMs,0);assert.equal(sanitized.fileName,null);assert.equal(sanitized.reason,null);
  for(const fileName of ['F:/private/file.mkv','F:\\private\\file.mkv','bad\n.mkv','x'.repeat(256)])assert.equal(normalize(record({fileName})).fileName,null);assert.equal(normalize(record({fileName:'Show <one>.mkv'})).fileName,'Show <one>.mkv');
});
class Element{constructor(){this.disabled=false;this.textContent='';this.title='';this.attributes={};this.listeners={};}setAttribute(name,value){this.attributes[name]=value;}addEventListener(name,callback){this.listeners[name]=callback;}fire(){return this.listeners.click?.();}}
test('mounted controls use text, explain disabled actions, and expose separate Stop and saved-file states',async()=>{
  const nodes=new Map(),node=name=>{if(!nodes.has(name))nodes.set(name,new Element());return nodes.get(name);},root=new Element();root.querySelector=selector=>node(selector.slice('[data-recording-'.length,-1));
  const calls=[],controller=mount({root,api:{recordingActions:async value=>{calls.push(value);return value.action==='stop'?reply({phase:'saved',finalized:true,fileName:'Saved <show>.mkv',frames:60,elapsedMs:2000,bytesWritten:2097152}):reply({phase:'recording',active:true,canStart:false});}}});controller.setContext({recording:record(),publishingBlocked:false,locked:false});assert.equal(node('start').disabled,false);assert.equal(node('stop').disabled,true);await node('start').fire();assert.equal(node('start').disabled,true);assert.equal(node('stop').disabled,false);assert.equal(node('badge').textContent,'Recording');await node('stop').fire();assert.equal(node('badge').textContent,'Saved');assert.equal(node('reveal').disabled,false);assert.equal(node('file').textContent,'Saved <show>.mkv');assert.equal(node('frames').textContent,'60');assert.equal(node('time').textContent,'00:00:02');assert.equal(node('size').textContent,'2.0 MB');controller.close();assert.deepEqual(calls.map(value=>value.action),['start','stop']);
});
