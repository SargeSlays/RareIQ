const test=require('node:test');
const assert=require('node:assert/strict');
const controls=require('../../rareiq/web/static/greenroom_controls.js');
test('returning a guest to waiting has a distinct activity label from ending access',()=>{
  assert.equal(controls.activityEntry({action:'guest.wait',outcome:'succeeded'}).action,'Guest returned to waiting room');
  assert.equal(controls.activityEntry({action:'guest.remove',outcome:'succeeded'}).action,'Guest removed');
});
const {sourceAvailable,togglePreview,takeReadiness,createRequests}=controls;

test('custom geometry needs an exact staged output receipt and changed IDs count as a new shot',()=>{
  const {room,switcher}=fixture();switcher.preview_sources=['camera:1'];switcher.program_sources=['camera:1'];switcher.preview_layout='custom';switcher.program_layout='custom';
  switcher.preview_composition_id='a'.repeat(64);switcher.program_composition_id='b'.repeat(64);
  room.output.preview_composition_ready=false;assert.equal(takeReadiness(switcher,room).ready,false);assert.match(takeReadiness(switcher,room).message,/exact Preview layers/);
  room.output.preview_composition_ready=true;assert.equal(takeReadiness(switcher,room).ready,true);
  switcher.program_composition_id=switcher.preview_composition_id;assert.equal(takeReadiness(switcher,room).ready,false);assert.match(takeReadiness(switcher,room).message,/already on Program/);
});
test('current audio blockage overrides a previous renderer receipt with a concrete recovery action',()=>{
  assert.match(controls.outputStatusLabel({connected:1,rendered_generation:3,audio_blocked:true},3),/open Studio Output and choose Enable output sound/);
  assert.match(controls.outputStatusLabel({connected:1,rendered_generation:3,audio_blocked:false},3),/reports this Program shot/);
  assert.match(controls.outputStatusLabel({connected:1,rendered_generation:2,audio_blocked:false},3),/waiting/);
  assert.match(controls.outputStatusLabel({connected:0,rendered_generation:3,audio_blocked:true},3),/No Studio Output/);
});
function fixture(){
  const participants=Array.from({length:3},(_,i)=>{const id=String(i+1).repeat(32);return {id,state:'admitted',connected:true,media:{camera:true,screen:true,microphone:true},sources:{camera:`guest:${id}:camera`,screen:`guest:${id}:screen`,audio:`guest:${id}:audio`}};});
  return {room:{participants,output:{connected:1,ready_sources:participants.flatMap(p=>Object.values(p.sources))}},switcher:{program_sources:['camera:1'],preview_sources:['camera:2'],program_layout:'auto',preview_layout:'auto',slots:[{slot_id:1,source_id:'local-1',connected:true,production_readiness:{ready:true}},{slot_id:2,source_id:null,connected:false,production_readiness:{ready:false}}]}};
}
test('Adding a guest replaces unavailable legacy Preview, retaining ready local cameras',()=>{
  const {room,switcher}=fixture(),source=room.participants[0].sources.camera;
  assert.deepEqual(togglePreview(source,switcher,room),[source]);
  switcher.preview_sources=['camera:1','camera:2'];
  assert.deepEqual(togglePreview(source,switcher,room),['camera:1',source]);
});
test('Waiting, disconnected and disabled media never become selectable',()=>{
  const {room,switcher}=fixture(),person=room.participants[0];
  for(const state of ['waiting','removed']){person.state=state;assert.equal(sourceAvailable(person.sources.camera,switcher,room),false);}
  person.state='admitted';person.connected=false;assert.throws(()=>togglePreview(person.sources.audio,switcher,room),/source_unavailable/);
  person.connected=true;person.media.microphone=false;assert.equal(sourceAvailable(person.sources.audio,switcher,room),false);
  assert.equal(sourceAvailable(person.sources.screen,switcher,room),true);
  assert.equal(sourceAvailable('camera:4',switcher,room),false);
});
test('Preview supports six sources, toggles off and preserves intentional empty arrays',()=>{
  const {room,switcher}=fixture(),sources=room.participants.flatMap(p=>Object.values(p.sources));
  switcher.preview_sources=sources.slice(0,6);
  assert.throws(()=>togglePreview(sources[6],switcher,room),/preview_source_limit/);
  assert.equal(togglePreview(sources[0],switcher,room).length,5);
  switcher.preview_sources=[];assert.deepEqual(togglePreview(sources[0],switcher,room),[sources[0]]);
  assert.equal(takeReadiness(switcher,room).ready,false);
});
test('Guest Take requires received output feeds, source availability and a changed composition',()=>{
  const {room,switcher}=fixture(),source=room.participants[0].sources.camera;
  switcher.preview_sources=[source];assert.equal(takeReadiness(switcher,room).ready,true);
  room.output.ready_sources=[];assert.equal(takeReadiness(switcher,room).ready,false);
  room.output.ready_sources=[source];switcher.program_sources=[source];assert.equal(takeReadiness(switcher,room).ready,false);
  switcher.preview_layout='grid';assert.equal(takeReadiness(switcher,room).ready,true);
  room.participants[0].connected=false;assert.equal(takeReadiness(switcher,room).ready,false);
});
test('Local camera readiness needs a connected source and explicit production readiness',()=>{
  const {room,switcher}=fixture();assert.equal(sourceAvailable('camera:1',switcher,room),true);
  delete switcher.slots[0].production_readiness;assert.equal(sourceAvailable('camera:1',switcher,room),false);
});
test('One output must have the complete guest shot; separate output readiness cannot be combined',()=>{
  const {room,switcher}=fixture(),a=room.participants[0].sources.camera,b=room.participants[1].sources.camera;
  switcher.preview_sources=[a,b];room.output.ready_sources=[a,b];room.output.ready_groups=[[a],[b]];
  assert.equal(takeReadiness(switcher,room).ready,false);
  room.output.ready_groups=[[a],[a,b]];assert.equal(takeReadiness(switcher,room).ready,true);
  room.output.ready_groups=[];assert.equal(takeReadiness(switcher,room).ready,false);
  delete room.output.ready_groups;assert.equal(takeReadiness(switcher,room).ready,true,'older hosts use their readiness union');
});
test('Mutation retries reuse their original receipt and revision after an uncertain response',async()=>{
  let revision=7,serial=0;const calls=[];
  const api=createRequests(async(path,options)=>{calls.push({path,...JSON.parse(options.body)});if(calls.length===1)throw Error('network');return {ok:true,status:200,json:async()=>({ok:true})};},()=>revision,()=>`receipt-${++serial}`);
  await assert.rejects(api.mutate('/invites',{label:'Guest'}),/connection_unavailable/);
  revision=10;await api.mutate('/invites',{label:'Guest'});assert.deepEqual(calls[0],calls[1]);
  await api.mutate('/invites',{label:'Guest'});assert.equal(calls[2].expected_revision,10);assert.notEqual(calls[2].request_id,calls[1].request_id);
});
test('Authoritative conflicts clear the old receipt without dropping the caller draft',async()=>{
  let serial=0;const calls=[],draft={label:'Unchanged guest'};
  const api=createRequests(async(path,options)=>{calls.push(JSON.parse(options.body));return calls.length===1?{ok:false,status:409,json:async()=>({ok:false,reason:'room_revision_conflict'})}:{ok:true,status:200,json:async()=>({ok:true})};},()=>calls.length?8:7,()=>`receipt-${++serial}`);
  await assert.rejects(api.mutate('/invites',draft),/room_revision_conflict/);await api.mutate('/invites',draft);
  assert.equal(draft.label,'Unchanged guest');assert.equal(calls[1].expected_revision,8);assert.notEqual(calls[0].request_id,calls[1].request_id);
});
test('Repeated mutation clicks are serialized and busy clears after completion',async()=>{
  let finish;const api=createRequests(()=>new Promise(resolve=>{finish=resolve;}),()=>1,()=> 'receipt');
  const first=api.mutate('/room',{});assert.equal(api.busy(),true);
  await assert.rejects(api.mutate('/room',{}),/producer_request_busy/);
  finish({ok:true,status:200,json:async()=>({ok:true})});await first;assert.equal(api.busy(),false);
});
test('Unknown server failures never expose response contents in UI errors',async()=>{
  const api=createRequests(async()=>({ok:false,status:403,json:async()=>({reason:'private / secret <content>'})}),()=>1);
  await assert.rejects(api.request('/read'),error=>error.message==='request_rejected'&&error.status===403);
});
test('Activity labels expose actor type and verified truth without private identifiers or raw details',()=>{
  const event={actor_kind:'host_voice',actor_id:'private-account-id',identity_verified:false,action:'program.take',outcome:'requested',target:'private-peer-id',timestamp:123,details:{token:'private-token'}};
  const entry=controls.activityEntry(event);assert.equal(entry.actor,'Voice');assert.equal(entry.outcome,'Requested');assert.equal(entry.verified,false);
  assert.ok(!JSON.stringify(entry).includes('private-'));
  assert.equal(controls.activityEntry({...event,actor_kind:'program_renderer',action:'program.rendered',outcome:'confirmed'}).outcome,'Renderer confirmed');
  assert.equal(controls.activityEntry({...event,actor_kind:'verified_account',identity_verified:true}).verified,true);
  assert.equal(controls.activityEntry({...event,identity_verified:'true'}).verified,false);
  const hostile='<img src=x onerror=alert(1)>';
  assert.equal(controls.activityEntry({...event,action:'guest.admit',target:'guest'},[{id:'guest',name:hostile}]).guest,hostile);
  assert.equal(controls.activityEntry({...event,actor_kind:hostile}).actor,'Unidentified source');
});

test('Private invitation links reject unsafe and unexpected destinations and explain local scope',()=>{
  const suffix='/guest#invite='+'b'.repeat(64);
  for(const origin of ['http://localhost:8765','http://127.0.0.1:8765','http://[::1]:8765']){
    const result=controls.invitationLink(origin+suffix);assert.equal(result.local,true);assert.match(result.hint,/this computer only/);assert.equal(result.url,origin+suffix);
  }
  const remote=controls.invitationLink('https://studio.example'+suffix);assert.equal(remote.local,false);assert.match(remote.hint,/each person/);
  for(const value of ['',null,'javascript:alert(1)','file:///guest#invite='+'b'.repeat(64),'https://user:password@studio.example'+suffix,'https://studio.example/control#invite='+'b'.repeat(64),'https://studio.example/guest?token=private#invite='+'b'.repeat(64),'https://studio.example'+suffix+'&extra=secret'])assert.equal(controls.invitationLink(value),null);
});

test('Program audio toggles use the latest independent flags without changing source availability',()=>{
  const {room,switcher}=fixture(),person=room.participants[0];
  assert.deepEqual(controls.programAudioChange(person,'microphone'),{action:'program_audio',microphone_muted:true,screen_muted:false});
  person.program_audio={microphone_muted:true,screen_muted:true};
  assert.deepEqual(controls.programAudioChange(person,'microphone'),{action:'program_audio',microphone_muted:false,screen_muted:true});
  assert.deepEqual(controls.programAudioChange(person,'screen'),{action:'program_audio',microphone_muted:true,screen_muted:false});
  assert.equal(sourceAvailable(person.sources.camera,switcher,room),true);assert.equal(sourceAvailable(person.sources.screen,switcher,room),true);
  assert.throws(()=>controls.programAudioChange(person,'camera'),/invalid_audio_kind/);
  const entry=controls.activityEntry({action:'guest.program_audio',outcome:'succeeded'});assert.equal(entry.action,'Program audio setting changed');assert.equal(entry.outcome,'Recorded');
});


test('partial connection warnings stay on the affected guest across room refreshes and clear on recovery',()=>{
  const warnings=controls.createPeerWarnings(),{room,switcher}=fixture(),a=room.participants[0],b=room.participants[1],output=JSON.stringify(room.output);
  warnings.update({scope:'peer',state:'peer_reconnecting',peer_id:'a-link',participant_id:a.id,reason:'private signaling details'});
  assert.match(warnings.text(a.id),/Reconnecting this guest/);assert.equal(warnings.text(b.id),'');
  warnings.prune(room.participants.map(p=>({...p})));assert.match(warnings.text(a.id),/Reconnecting/);
  warnings.update({scope:'signaling',state:'connected',peer_id:'control'});assert.match(warnings.text(a.id),/Reconnecting/);
  warnings.update({scope:'peer',state:'peer_failed',peer_id:'a-link',participant_id:a.id});assert.match(warnings.text(a.id),/could not reconnect/);
  assert.ok(!warnings.text(a.id).includes('private'));assert.equal(JSON.stringify(room.output),output);
  switcher.preview_sources=[a.sources.audio];room.output.ready_sources=[];assert.equal(takeReadiness(switcher,room).ready,false,'warnings never grant output readiness');
  warnings.update({scope:'peer',state:'connected',peer_id:'a-link',participant_id:a.id});assert.equal(warnings.text(a.id),'');
  warnings.update({scope:'peer',state:'peer_disconnected',peer_id:'b-link',participant_id:b.id});warnings.update({scope:'peer',state:'peer_removed',peer_id:'b-link'});assert.equal(warnings.text(b.id),'');
  warnings.update({scope:'peer',state:'peer_failed',peer_id:'a-link',participant_id:a.id});warnings.prune(room.participants.filter(p=>p.id!==a.id));assert.equal(warnings.text(a.id),'');
});
