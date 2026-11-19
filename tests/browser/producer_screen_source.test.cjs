const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/producer_screen_source.js'),'utf8');
const controls=require('../../rareiq/web/static/greenroom_controls.js'),layouts=require('../../rareiq/web/static/production_layouts.js');
const ID='producer:screen:'+'a'.repeat(32),settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
function fixture({allowed=true,capture}={}){
  const nodes=new Map(),events=new Map(),publishers=[],calls={capture:0,select:[],refresh:0},room={producer_sources:[]};let selected=[];
  class Node{
    constructor(){this.listeners=new Map();this.attrs={};this.disabled=false;this.textContent='';}
    setAttribute(key,value){this.attrs[key]=String(value);}
    addEventListener(key,fn){this.listeners.set(key,fn);}
    querySelector(key){if(!nodes.has(key))nodes.set(key,new Node());return nodes.get(key);}
    remove(){this.removed=true;}
  }
  const document={createElement:()=>new Node()},after={ownerDocument:document,after(section){this.section=section;}};
  const host={addEventListener:(key,fn)=>events.set(key,fn),removeEventListener:key=>events.delete(key)};
  vm.runInNewContext(source,{window:host,Promise,Object,String,Error});
  function track(kind='video'){const callbacks=new Map();return {kind,readyState:'live',stops:0,stop(){this.stops++;this.readyState='ended';},addEventListener:(key,fn)=>callbacks.set(key,fn),removeEventListener:key=>callbacks.delete(key),ended(){this.readyState='ended';callbacks.get('ended')?.();}};}
  function stream(){const video=track(),audio=track('audio');return {video,audio,getTracks:()=>[video,audio],getVideoTracks:()=>[video],getAudioTracks:()=>[audio]};}
  const values=stream();
  const api=host.ProducerScreenSource.mount({after,document,room:()=>room,selected:()=>selected,select:id=>{calls.select.push(id);selected=selected.includes(id)?[]:[id];},refresh:async()=>{calls.refresh++;},
    mediaDevices:{getDisplayMedia:options=>{calls.capture++;calls.options=options;return capture?capture(values):Promise.resolve(values);}},
    fetch:async()=>({ok:true,json:async()=>({ok:true,capture_allowed:allowed})}),createPublisher:options=>{
      const publisher={options,tracks:[],closed:0,setTracks(value){this.tracks.push(value);},async connect(){room.producer_sources=[{id:ID,available:true}];options.onState({source_id:ID});},close(){this.closed++;}};publishers.push(publisher);return publisher;
    }});
  return {api,nodes,calls,publishers,room,values,events,selected:()=>selected};
}

test('screen source permission check never captures and remote operators cannot invoke capture',async()=>{
  const f=fixture({allowed:false});await settle();assert.equal(f.calls.capture,0);assert.equal(f.nodes.get('[data-screen-share]').disabled,true);
  await f.api.start();assert.equal(f.calls.capture,0);assert.match(f.nodes.get('[role="status"]').textContent,/this computer/);f.api.close();
});

test('screen capture stays off Preview until selected, includes no audio and cleans up on end',async()=>{
  const f=fixture();await settle();await f.api.start();
  assert.equal(f.calls.capture,1);assert.equal(f.calls.options.audio,false);assert.equal(f.values.audio.stops,1);
  assert.equal(f.api.source(),ID);assert.deepEqual(f.selected(),[]);assert.equal(f.publishers[0].tracks[0].screen,f.values.video);
  assert.equal(f.nodes.get('[data-screen-preview]').disabled,false);f.nodes.get('[data-screen-preview]').listeners.get('click')();assert.deepEqual(f.calls.select,[ID]);
  f.values.video.ended();assert.equal(f.api.source(),null);assert.equal(f.publishers[0].closed,1);assert.equal(f.values.video.stops,1);
  f.publishers[0].options.onState({source_id:ID});assert.equal(f.api.source(),null);f.api.close();
});

test('cancelled pending capture stops late tracks and never starts a publisher',async()=>{
  let resolve;const f=fixture({capture:()=>new Promise(yes=>{resolve=yes;})});await settle();const pending=f.api.start();assert.equal(f.nodes.get('[data-screen-stop]').disabled,false);
  f.api.stop();resolve(f.values);await pending;assert.equal(f.publishers.length,0);assert.equal(f.values.video.stops,1);assert.equal(f.values.audio.stops,1);f.api.close();
});

test('connection loss and page navigation stop owned capture without automatically sharing again',async()=>{
  const f=fixture();await settle();await f.api.start();f.publishers[0].options.onConnection({state:'disconnected'});
  assert.equal(f.values.video.stops,1);assert.equal(f.api.source(),null);assert.equal(f.calls.capture,1);f.events.get('pagehide')();assert.equal(f.events.size,0);
});

test('screen Preview uses one complete output receipt and presentation layouts treat it as content',()=>{
  const room={producer_sources:[{id:ID,available:true}],participants:[],output:{connected:1,ready_groups:[[]]}},state={preview_sources:[ID],program_sources:[]};
  assert.equal(controls.sourceAvailable(ID,state,room),true);assert.equal(controls.takeReadiness(state,room).ready,false);
  room.output.ready_groups=[[ID]];assert.equal(controls.takeReadiness(state,room).ready,true);
  assert.equal(layouts.sourceKind(ID),'content');assert.equal(layouts.presetPlan('smart',[ID,'camera:1']).layout,'spotlight');
  room.producer_sources=[];assert.equal(controls.sourceAvailable(ID,state,room),false);assert.equal(controls.takeReadiness(state,room).ready,false);
});
