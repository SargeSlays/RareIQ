'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../settings.js'),'utf8');
const prepared={phase:'prepared',active:false,ready:true,prepared:true,format:'hd',available:true};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
class Element{
  constructor(){this.listeners=new Map();this.children=[];this.dataset={};this.value='';this.textContent='';this.hidden=false;this.disabled=false;}
  addEventListener(name,fn){this.listeners.set(name,fn);}
  fire(name='click'){return this.listeners.get(name)?.({preventDefault(){}});}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(){}
  focus(){this.focused=true;}
  scrollIntoView(){this.scrolled=true;}
}
async function fixture(options={}){
  const nodes=new Map(),timers=[],calls={start:0,stop:0,poll:0,save:0,remove:0,sources:0,view:0,profileSave:0,profileSelect:0,profileRemove:0,prepare:0,targetStop:0};let profileState=options.profiles?{profiles:require('../output-profiles.cjs').defaultProfiles(),selectedProfileId:'hd-balanced'}:null,state={...prepared,...(profileState?{profileId:'hd-balanced',outputProfile:JSON.parse(JSON.stringify(profileState.profiles[0]))}:{})},destinations=options.destinations||[{id:'one',name:'Synthetic',platform:'twitch',configured:true,keyConfigured:true}];
  const node=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const form=node('#destinationForm');form.elements=[];
  for(const name of ['name','platform','serverUrl','streamKey']){const element=new Element();form.elements.push(element);form.elements[name]=element;}
  form.elements.name.value='Synthetic';form.elements.platform.value='twitch';form.elements.streamKey.value='synthetic-never-sent';form.reset=()=>{};
  node('#outputFormat').value='hd';
  node('#destinationFormTitle').textContent='Add a destination';
  const descendants=element=>element.children.flatMap(child=>[child,...descendants(child)]);
  const document={querySelector:node,createElement:()=>new Element(),documentElement:{dataset:{}},querySelectorAll:selector=>{
    const key={'[data-destination-id]':'destinationId','[data-remove-destination-id]':'removeDestinationId','[data-edit-destination-id]':'editDestinationId','[data-select-destination-id]':'selectDestinationId','[data-stop-destination-id]':'stopDestinationId'}[selector];return descendants(node('#destinations')).filter(element=>key in element.dataset);
  }};
  const api={status:async()=>({secureStorageAvailable:true,broadcast:state,destinations,...(profileState?{outputProfiles:profileState}:{})}),
    startBroadcast:async()=>{calls.start++;return state;},stopBroadcast:async()=>{calls.stop++;return state={...prepared};},
    broadcastStatus:async()=>{calls.poll++;return state;},prepareOutput:async value=>{calls.prepare++;if(value.profileId){const profile=profileState.profiles.find(item=>item.id===value.profileId);state={...prepared,profileId:profile.id,format:profile.format,outputProfile:JSON.parse(JSON.stringify(profile))};}return state;},
    save:async()=>{calls.save++;},remove:async()=>{calls.remove++;},openPlatform:()=>{},openSources:async()=>{calls.sources++;return {ok:true};},viewOutput:async()=>{calls.view++;return {ok:true};},
    listOutputProfiles:async()=>profileState,saveOutputProfile:async value=>{calls.profileSave++;const {requestId,id,...settings}=value,profile={id:id||'new-profile',...settings,updatedAt:calls.profileSave};profileState={profiles:id?profileState.profiles.map(item=>item.id===id?profile:item):[...profileState.profiles,profile],selectedProfileId:profile.id};return profileState;},selectOutputProfile:async id=>{calls.profileSelect++;profileState={...profileState,selectedProfileId:id};return profileState;},removeOutputProfile:async id=>{calls.profileRemove++;profileState={profiles:profileState.profiles.filter(item=>item.id!==id),selectedProfileId:profileState.profiles.find(item=>item.id!==id).id};return profileState;},stopBroadcastTarget:async id=>{calls.targetStop++;state={...state,targets:state.targets.map(item=>item.destinationId===id?{...item,phase:'stopped'}:item)};return state;}};
  vm.runInNewContext(source,{document,producerSettings:api,window:{close(){}},localStorage:{getItem(){},setItem(){}},crypto:{randomUUID:()=> 'synthetic-request'},
    setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval(){},addEventListener(){}},{filename:'settings.js'});
  await settle();return {node,form,api,calls,descendants,poll:()=>timers[0](),set state(value){state=value;},get state(){return state;},get profiles(){return profileState;},get checks(){return document.querySelectorAll('[data-select-destination-id]');},get targetButtons(){return document.querySelectorAll('[data-stop-destination-id]');},get start(){return document.querySelectorAll('[data-destination-id]')[0];},get remove(){return document.querySelectorAll('[data-remove-destination-id]')[0];},get edit(){return document.querySelectorAll('[data-edit-destination-id]')[0];}};
}
test('stopped encoder failures override readiness and format hints without exposing unknown errors',async()=>{
  const f=await fixture();f.node('#outputFormat').value='portrait';
  for(const [reason,expected] of [['encoder_backpressure',/could not keep up/],['encoder_failed',/encoder failed/],['rtmps://private/secret-key',/stopped unexpectedly/]]){
    f.state={...prepared,phase:'failed',reason};await f.poll();const text=f.node('#broadcastSummary').textContent;
    assert.match(text,expected);assert.doesNotMatch(text,/Ready to send|secret-key|format changed/);
  }
});
test('pending Start keeps polling and Cancel available, prevents duplicate requests, and ignores late success',async()=>{
  const f=await fixture(),start=deferred(),stop=deferred();
  f.api.startBroadcast=()=>{f.calls.start++;return start.promise;};f.api.stopBroadcast=()=>{f.calls.stop++;return stop.promise;};
  const starting=f.start.fire();assert.equal(f.node('#stopBroadcast').hidden,false);assert.equal(f.node('#stopBroadcast').disabled,false);assert.equal(f.node('#stopBroadcast').textContent,'Cancel start');
  await f.start.fire();await f.form.fire('submit');await f.remove.fire();assert.equal(f.calls.start,1);assert.equal(f.calls.save,0);assert.equal(f.calls.remove,0);
  f.state={...prepared,phase:'starting',active:true,ready:false};await f.poll();assert.equal(f.calls.poll,1);assert.match(f.node('#broadcastSummary').textContent,/Broadcast starting/);
  const stopping=f.node('#stopBroadcast').fire();await f.node('#stopBroadcast').fire();assert.equal(f.calls.stop,1);assert.equal(f.node('#stopBroadcast').disabled,true);
  stop.resolve({...prepared});await stopping;start.resolve({...prepared,phase:'sending',active:true,ready:false});await starting;
  assert.equal(f.node('#stopBroadcast').hidden,true);assert.match(f.node('#status').textContent,/Transmission stopped/);assert.doesNotMatch(f.node('#broadcastSummary').textContent,/Sending/);
});
test('late Start rejection and pre-cancellation poll cannot overwrite a completed Stop',async()=>{
  const f=await fixture(),start=deferred(),poll=deferred();f.api.startBroadcast=()=>start.promise;const starting=f.start.fire();
  f.api.broadcastStatus=()=>poll.promise;const polling=f.poll();await f.node('#stopBroadcast').fire();
  poll.resolve({...prepared,phase:'sending',active:true});await polling;start.reject(Error('rtmps://private/secret-key'));await starting;
  assert.equal(f.node('#stopBroadcast').hidden,true);assert.equal(f.node('#status').textContent,'Transmission stopped.');assert.doesNotMatch(f.node('#broadcastSummary').textContent,/Sending|secret-key/);
});
test('status polling preserves destination save and remove locks until their requests finish',async()=>{
  const f=await fixture(),save=deferred(),remove=deferred();f.api.save=()=>{f.calls.save++;return save.promise;};
  const saving=f.form.fire('submit');await f.poll();await f.start.fire();await f.form.fire('submit');
  assert.equal(f.calls.start,0);assert.equal(f.calls.save,1);assert.equal(f.start.disabled,true);assert.ok(f.form.elements.every(element=>element.disabled));
  save.resolve();await saving;assert.equal(f.start.disabled,false);assert.ok(f.form.elements.every(element=>!element.disabled));
  f.api.remove=()=>{f.calls.remove++;return remove.promise;};const removing=f.remove.fire();await f.poll();await f.remove.fire();
  assert.equal(f.calls.remove,1);assert.equal(f.start.disabled,true);remove.resolve();await removing;assert.equal(f.start.disabled,false);
});
test('browser-mode backend explains the explicit restart without starting or stopping anything',async()=>{
  const f=await fixture();f.state={...prepared,ready:false,reason:'desktop_mode_required'};await f.poll();
  assert.match(f.node('#broadcastSummary').textContent,/started in browser mode\. Close its sessions and restart it from the desktop app/);
  assert.equal(f.start.disabled,true);assert.equal(f.calls.start,0);assert.equal(f.calls.stop,0);
});

test('broadcast guide distinguishes a checked output, changed format and secure destination',async()=>{
  const f=await fixture();assert.equal(f.node('#outputStep').textContent,'Ready');assert.equal(f.node('#destinationStep').textContent,'Saved securely');
  f.node('#outputFormat').value='portrait';f.node('#outputFormat').fire('change');assert.equal(f.node('#outputStep').textContent,'Prepare new format');assert.equal(f.start.disabled,true);
  f.api.status=async()=>({secureStorageAvailable:true,broadcast:{...prepared,ready:false,prepared:false},destinations:[]});await f.form.fire('submit');
  assert.equal(f.node('#outputStep').textContent,'Not prepared');assert.equal(f.node('#destinationStep').textContent,'Not saved');assert.equal(f.node('#programStep').textContent,'Check Program');
});

test('source navigation keeps destination drafts, blocks repeat clicks, and reports a recoverable failure',async()=>{
  const f=await fixture(),open=deferred();f.api.openSources=()=>{f.calls.sources++;return open.promise;};
  const name=f.form.elements.name.value,key=f.form.elements.streamKey.value,pending=f.node('#chooseSources').fire();await f.node('#chooseSources').fire();
  assert.equal(f.calls.sources,1);assert.equal(f.node('#chooseSources').disabled,true);assert.equal(f.calls.start,0);assert.equal(f.calls.save,0);
  open.reject(Error('private error'));await pending;assert.match(f.node('#status').textContent,/could not open/);assert.equal(f.node('#chooseSources').disabled,false);
  assert.equal(f.form.elements.name.value,name);assert.equal(f.form.elements.streamKey.value,key);assert.doesNotMatch(f.node('#status').textContent,/private error/);
  f.api.openSources=async()=>({ok:true});await f.node('#chooseSources').fire();assert.match(f.node('#status').textContent,/draft is kept/);
  f.node('#addDestination').fire();assert.equal(f.form.scrolled,true);assert.equal(f.form.elements.name.focused,true);
});

test('pending Stop acknowledgment keeps Stop available and blocks new transmission',async()=>{
  const f=await fixture();f.state={...prepared,phase:'failed',ownershipPending:true,reason:'studio_status_unconfirmed'};await f.poll();
  assert.equal(f.node('#stopBroadcast').hidden,false);assert.equal(f.node('#stopBroadcast').disabled,false);assert.equal(f.node('#prepareOutput').disabled,true);assert.equal(f.start.disabled,true);
  await f.start.fire();assert.equal(f.calls.start,0);assert.equal(f.node('#recoveryPanel').hidden,false);assert.match(f.node('#recoveryInstructions').textContent,/choose Stop broadcast again/);
  await f.node('#stopBroadcast').fire();assert.equal(f.calls.stop,1);assert.equal(f.node('#recoveryPanel').hidden,true);
});

test('View output stays usable during sending without starting or preparing another output',async()=>{
  const f=await fixture(),view=deferred();f.state={...prepared,phase:'sending',active:true,ready:false};await f.poll();f.api.viewOutput=()=>{f.calls.view++;return view.promise;};
  assert.equal(f.node('#viewOutput').disabled,false);const pending=f.node('#viewOutput').fire();await f.node('#viewOutput').fire();assert.equal(f.calls.view,1);assert.equal(f.node('#stopBroadcast').disabled,false);
  view.resolve({ok:true});await pending;assert.equal(f.calls.start,0);assert.match(f.node('#status').textContent,/does not change Program/);
  f.state={...prepared,prepared:false,ready:false};await f.poll();assert.equal(f.node('#viewOutput').disabled,true);
});

test('connection recovery remains explicit, preserves input drafts and hides unknown error text',async()=>{
  const f=await fixture();f.state={...prepared,phase:'failed',reason:'tls_verification_failed'};await f.poll();assert.match(f.node('#recoveryInstructions').textContent,/date and time/);assert.equal(f.calls.start,0);assert.equal(f.form.elements.streamKey.value,'synthetic-never-sent');
  f.state={...prepared,phase:'failed',reason:'rtmps://private/secret-key'};await f.poll();assert.doesNotMatch(f.node('#broadcastSummary').textContent+f.node('#recoveryInstructions').textContent,/secret-key|private/);
  f.state={...prepared,phase:'sending',active:true,ready:false,reason:'output_not_ready'};await f.poll();assert.match(f.node('#broadcastSummary').textContent,/Waiting for output readiness/);assert.equal(f.node('#outputStep').textContent,'Checking output');
});

test('normal startup reservation does not show an unconfirmed-stop recovery warning',async()=>{
  const f=await fixture();f.state={...prepared,phase:'starting',active:true,ready:false,ownershipPending:true};await f.poll();assert.equal(f.node('#recoveryPanel').hidden,true);assert.match(f.node('#broadcastSummary').textContent,/Broadcast starting/);
});

test('editing never reads saved secrets and keeps Add draft through cancel',async()=>{
  const f=await fixture(),original={name:f.form.elements.name.value,key:f.form.elements.streamKey.value};await f.edit.fire();
  assert.equal(f.form.elements.streamKey.value,'');assert.equal(f.form.elements.serverUrl.value,'');assert.equal(f.form.elements.streamKey.required,false);assert.equal(f.form.elements.platform.disabled,true);
  assert.equal(f.node('#destinationFormTitle').textContent,'Edit destination');assert.equal(f.start.disabled,true);await f.start.fire();assert.equal(f.calls.start,0);
  f.form.elements.name.value='Unsaved correction';await f.node('#cancelEdit').fire();assert.equal(f.form.elements.name.value,original.name);assert.equal(f.form.elements.streamKey.value,original.key);assert.equal(f.node('#cancelEdit').hidden,true);assert.equal(f.start.disabled,false);
});

test('rename omits saved server/key, keeps id, and restores Add draft after success',async()=>{
  const f=await fixture();let payload;f.api.save=async value=>{payload=value;f.calls.save++;};await f.edit.fire();f.form.elements.name.value='Renamed';await f.form.fire('submit');
  assert.equal(payload.id,'one');assert.equal(payload.name,'Renamed');assert.equal('streamKey' in payload,false);assert.equal('serverUrl' in payload,false);assert.equal(f.calls.start,0);assert.equal(f.node('#destinationFormTitle').textContent,'Add a destination');assert.equal(f.form.elements.streamKey.value,'synthetic-never-sent');
});

test('editing server requires replacement key and a failed retry keeps draft and request id',async()=>{
  const f=await fixture();f.api.status=async()=>({secureStorageAvailable:true,broadcast:prepared,destinations:[{id:'other',name:'YouTube',platform:'youtube',configured:true,keyConfigured:true}]});await f.form.fire('submit');await f.edit.fire();
  f.form.elements.serverUrl.value='rtmps://secure.provider.com/live';await f.form.fire('submit');assert.match(f.node('#status').textContent,/replacement stream key/);assert.equal(f.calls.save,1);
  const attempts=[];f.api.save=async value=>{attempts.push(value);if(attempts.length===1)throw Error('private raw detail');};f.form.elements.streamKey.value='synthetic-replacement';await f.form.fire('submit');assert.equal(f.form.elements.streamKey.value,'synthetic-replacement');assert.equal(f.node('#cancelEdit').hidden,false);assert.doesNotMatch(f.node('#status').textContent,/private raw/);
  await f.form.fire('submit');assert.deepEqual(attempts[0],attempts[1]);assert.equal(attempts[1].id,'other');assert.equal(attempts[1].streamKey,'synthetic-replacement');assert.equal(attempts[1].serverUrl,'rtmps://secure.provider.com/live');
});

test('all destination edits and mutations stop during sending or unconfirmed ownership',async()=>{
  const f=await fixture();for(const state of [{...prepared,active:true,phase:'sending'},{...prepared,ownershipPending:true,phase:'failed'}]){f.state=state;await f.poll();assert.equal(f.edit.disabled,true);assert.equal(f.remove.disabled,true);assert.equal(f.node('#platformDashboard').disabled,false);await f.edit.fire();await f.remove.fire();await f.form.fire('submit');assert.equal(f.node('#destinationFormTitle').textContent,'Add a destination');assert.equal(f.calls.remove,0);assert.equal(f.calls.save,0);assert.ok(f.form.elements.every(element=>element.disabled));}
});

test('ambiguous Add retry retains its receipt after an intervening edit and cancel',async()=>{
  const f=await fixture(),attempts=[];f.api.save=async value=>{attempts.push(value);if(attempts.length===1)throw Error('acknowledgment lost');};await f.form.fire('submit');await f.edit.fire();await f.node('#cancelEdit').fire();await f.form.fire('submit');assert.deepEqual(attempts[0],attempts[1]);
});

test('saved output profiles populate explicit encoding and routing defaults without preparing or starting',async()=>{
  const f=await fixture({profiles:true});assert.equal(f.node('#outputProfileSection').hidden,false);assert.equal(f.node('#legacyOutputFormat').hidden,true);assert.equal(f.node('#profileFps').value,'30');assert.equal(f.node('#profileVideoBitrate').value,'4000');assert.equal(f.node('#profileCodec').value,'auto');assert.equal(f.node('#profileTwitchVod').checked,false);const routes=f.descendants(f.node('#profileAudioRouting')).filter(element=>element.dataset.audioRouteBus==='vod');assert.equal(routes.find(element=>element.dataset.audioRouteSource==='voice:default').checked,true);assert.equal(routes.find(element=>element.dataset.audioRouteSource==='video:default').checked,false);assert.equal(f.calls.start,0);assert.equal(f.calls.prepare,0);
});

test('profile drafts survive polling, require Save, and changed settings under the same id require Prepare again',async()=>{
  const f=await fixture({profiles:true});f.node('#profileVideoBitrate').value='8000';f.node('#profileVideoBitrate').fire('input');await f.poll();assert.equal(f.node('#profileVideoBitrate').value,'8000');assert.equal(f.start.disabled,true);assert.equal(f.node('#prepareOutput').disabled,true);await f.start.fire();assert.equal(f.calls.start,0);
  await f.node('#outputProfileForm').fire('submit');assert.equal(f.calls.profileSave,1);assert.equal(f.node('#prepareOutput').disabled,false);assert.equal(f.start.disabled,true);assert.match(f.node('#broadcastSummary').textContent,/Output profile changed/);await f.start.fire();assert.equal(f.calls.start,0);await f.node('#prepareOutput').fire();assert.equal(f.calls.prepare,1);assert.equal(f.start.disabled,false);assert.equal(f.state.outputProfile.videoBitrateKbps,8000);
});

test('profile save retry preserves the exact receipt and draft after an uncertain result',async()=>{
  const f=await fixture({profiles:true}),attempts=[],save=f.api.saveOutputProfile;f.api.saveOutputProfile=async value=>{attempts.push(value);if(attempts.length===1)throw Error('private filesystem detail');return save(value);};f.node('#outputProfileName').value='My saved show';f.node('#profileFps').value='60';f.node('#profileTwitchVod').checked=true;f.node('#outputProfileName').fire('input');await f.node('#outputProfileForm').fire('submit');assert.equal(f.node('#outputProfileName').value,'My saved show');assert.match(f.node('#outputProfileStatus').textContent,/draft is kept/);assert.doesNotMatch(f.node('#outputProfileStatus').textContent,/private/);await f.node('#outputProfileForm').fire('submit');assert.deepEqual(attempts[0],attempts[1]);assert.equal(attempts[0].fps,60);assert.equal(attempts[0].twitchVod,true);assert.equal('streamKey' in attempts[0],false);
});

test('profile selection and save-as-new preserve existing profile identity and prevent accidental transmission',async()=>{
  const f=await fixture({profiles:true});f.node('#outputProfileSelect').value='portrait-hd';await f.node('#outputProfileSelect').fire('change');assert.equal(f.node('#profileFormat').value,'portrait');assert.equal(f.node('#outputFormat').value,'portrait');assert.equal(f.start.disabled,true);f.node('#outputProfileName').value='Portrait show';await f.node('#saveOutputProfileAsNew').fire();assert.equal(f.profiles.profiles.length,4);assert.equal(f.profiles.profiles.find(item=>item.id==='portrait-hd').name,'Portrait HD');assert.equal(f.profiles.selectedProfileId,'new-profile');assert.equal(f.calls.start,0);
});

test('audio routing exposes fixed source labels, keeps exact overrides and protects live-session editing',async()=>{
  const f=await fixture({profiles:true}),source='video:12345678-1234-1234-1234-123456789abc';f.state={...f.state,audioSourcesAvailable:[{id:source,category:'video',label:'private-file-name'}]};await f.poll();let inputs=f.descendants(f.node('#profileAudioRouting')).filter(element=>element.dataset.audioRouteSource===source);const vod=inputs.find(element=>element.dataset.audioRouteBus==='vod');assert.equal(vod.checked,false);vod.checked=true;vod.fire('change');await f.node('#outputProfileForm').fire('submit');assert.deepEqual({...f.profiles.profiles.find(item=>item.id==='hd-balanced').audioRouting[source]},{live:true,vod:true});assert.equal(f.descendants(f.node('#profileAudioRouting')).some(element=>element.textContent.includes('private-file-name')),false);
  f.state={...f.state,phase:'sending',active:true,ready:false};await f.poll();inputs=f.descendants(f.node('#profileAudioRouting')).filter(element=>element.dataset.audioRouteSource);assert.ok(inputs.every(element=>element.disabled));assert.equal(f.node('#profileCodec').disabled,true);assert.equal(f.node('#saveOutputProfileAsNew').disabled,true);
});

test('multi-destination selection is capped at eight and Start selected sends only selected ids plus saved profile',async()=>{
  const destinations=Array.from({length:10},(_,index)=>({id:'target-'+index,name:'Target '+index,platform:'custom',configured:true,keyConfigured:true})),f=await fixture({profiles:true,destinations});let started;f.api.startBroadcast=async value=>{started=value;f.calls.start++;return f.state;};f.node('#selectAllDestinations').fire();assert.equal(f.checks.filter(item=>item.checked).length,8);f.checks[8].checked=true;f.checks[8].fire('change');assert.equal(f.checks[8].checked,false);await f.node('#startSelectedDestinations').fire();assert.equal(started.destinationIds.length,8);assert.equal(started.profileId,'hd-balanced');assert.equal('format' in started,false);assert.equal(f.calls.start,1);assert.equal(f.calls.save,0);
});

test('single-target Stop preserves other sending destinations and hides raw failure reasons',async()=>{
  const f=await fixture({destinations:[{id:'one',name:'First',platform:'twitch',configured:true},{id:'two',name:'Second',platform:'youtube',configured:true}]});f.state={...prepared,phase:'sending',active:true,ready:false,targets:[{destinationId:'one',phase:'sending'},{destinationId:'two',phase:'sending'}]};await f.poll();assert.equal(f.targetButtons[0].hidden,false);await f.targetButtons[0].fire();assert.equal(f.calls.targetStop,1);assert.equal(f.state.targets[0].phase,'stopped');assert.equal(f.state.targets[1].phase,'sending');assert.equal(f.calls.stop,0);assert.match(f.node('#status').textContent,/Destination stopped/);
  f.state={...f.state,targets:[f.state.targets[0],{destinationId:'two',phase:'failed',reason:'private-key-in-error'}]};await f.poll();assert.equal(f.descendants(f.node('#destinations')).some(element=>element.textContent.includes('private-key-in-error')),false);
});

test('Settings exposes every platform class with manual secure ingest guidance and no extra dashboard shortcuts',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../settings.html'),'utf8');for(const platform of ['twitch','youtube','kick','rumble','facebook','tiktok','x','instagram','custom'])assert.ok(html.includes('value="'+platform+'"'));assert.match(html,/secure RTMPS server/);assert.match(html,/Guest soundboards and voice effects arrive mixed/);assert.match(html,/nested browser sources is currently excluded/);
});

test('saved-profile hints preserve a runtime-unavailable blocker and keep Prepare disabled',async()=>{
  const f=await fixture({profiles:true});f.state={...prepared,phase:'idle',available:false,prepared:false,ready:false,profileId:null,outputProfile:null};await f.poll();assert.match(f.node('#broadcastSummary').textContent,/managed desktop runtime/);assert.doesNotMatch(f.node('#broadcastSummary').textContent,/Output profile changed/);assert.equal(f.node('#prepareOutput').disabled,true);
});
