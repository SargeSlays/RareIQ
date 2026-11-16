const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const controls=require('../../rareiq/web/static/audience_controls.js');
const overlay=require('../../rareiq/web/static/audience_overlay.js');
const root=path.resolve(__dirname,'../../rareiq/web/static');

test('audience interface source stays valid UTF-8 across Windows edits',()=>{
  assert.doesNotThrow(()=>new TextDecoder('utf-8',{fatal:true}).decode(fs.readFileSync(path.join(root,'audience_controls.js'))));
});

test('rule defaults and revision preconditions remain separate from provider provenance',()=>{
  const rule=controls.defaultRule('local-rule');
  assert.equal(rule.event,'first_chat');
  const request=controls.mutation('save_rule',rule,7,'retry-id');
  assert.equal(request.expected_revision,7);
  assert.equal(request.request_id,'retry-id');
  assert.equal('verified' in request,false);
});

test('overlay rejects URLs, unsupported animation and excessive duration',()=>{
  const value={title:'Welcome',subtitle:'First chat this session',animation:'slide',duration_ms:3000,platform:'twitch'};
  assert.deepEqual(overlay.graphic(value),value);
  assert.equal(overlay.graphic({...value,animation:'url(https://example.invalid)'}),null);
  assert.equal(overlay.graphic({...value,duration_ms:100000}),null);
  assert.equal(overlay.graphic({...value,title:'x'.repeat(241)}),null);
});

test('private preview escapes participant text and never polls live output',()=>{
  const elements=new Map(),listeners={},timers=[];
  for(const name of ['audienceGraphic','audienceGraphicTitle','audienceGraphicKind','audienceGraphicPlatform','audiencePreviewLabel'])elements.set(name,{hidden:true,dataset:{},textContent:'',offsetWidth:10});
  const parent={},location={search:'?preview=1',origin:'http://studio.test'};
  const context={window:null,parent,location,document:{body:{dataset:{}},getElementById:id=>elements.get(id)},URLSearchParams,Symbol,Number,Set,clearTimeout(){},setTimeout(fn){timers.push(fn);return timers.length;},fetch(){assert.fail('Preview requested live output');}};
  context.window={addEventListener:(name,fn)=>{listeners[name]=fn;}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'audience_overlay.js'),'utf8'),context);
  const graphic={title:'<img src=x onerror=alert(1)>',subtitle:'First chat this session',animation:'slide',duration_ms:3000,platform:'preview'};
  listeners.message({origin:location.origin,source:parent,data:{type:'producer-audience-preview',graphic}});
  assert.equal(elements.get('audienceGraphicTitle').textContent,graphic.title);
  assert.equal(elements.get('audienceGraphic').hidden,false);
  assert.equal('innerHTML' in elements.get('audienceGraphicTitle'),false);
  timers.at(-1)();assert.equal(elements.get('audienceGraphic').hidden,true);
  listeners.message({origin:'https://other.invalid',source:parent,data:{type:'producer-audience-preview',graphic}});
  assert.equal(elements.get('audienceGraphic').hidden,true);
});

test('source copy requires current authenticated connection and explains missing host setup',()=>{
  const source={implemented:true,state:'connected',connected:true,authorized:true,verified:true};
  assert.equal(controls.connected(source),true);
  for(const change of [{connected:false},{authorized:false},{verified:false},{state:'reconnecting'}])assert.equal(controls.connected({...source,...change}),false);
  assert.match(controls.connectionMessage({implemented:true,reason:'credentials_required'}),/setup is missing on this host/);
  assert.match(controls.connectionMessage(source),/observing first chats/);
  assert.doesNotMatch(controls.connectionMessage(source),/viewer arrived|watcher joined/);
});

test('unsupported follow, subscription and disconnected platform rules wait truthfully',()=>{
  const twitch={platform:'twitch',state:'connected',connected:true,authorized:true,verified:true,available_events:['first_chat','featured_chat']};
  const rule={platform:'any',event:'first_chat',enabled:true};
  assert.equal(controls.ruleAvailability(rule,[twitch]),'Ready');
  for(const change of [{event:'follow'},{event:'subscription'},{platform:'youtube'},{platform:'kick'}])assert.equal(controls.ruleAvailability({...rule,...change},[twitch]),'Waiting for supported connection');
  assert.equal(controls.ruleAvailability({...rule,enabled:false},[twitch]),'Paused');
  assert.equal(controls.ruleAvailability(rule,[]),'Waiting for supported connection');
});

test('one-click feature uses observed account IDs, never the display name as identity',()=>{
  const person={platform:'twitch',channel_id:'123',subject_id:'456',label:'Same display name',observed_chats:2};
  assert.deepEqual(controls.featureRequest(person),{platform:'twitch',channel_id:'123',subject_id:'456',label:'Same display name'});
  assert.equal(controls.featureRequest({...person,subject_id:undefined}),null);
  assert.equal(controls.featureRequest({...person,platform:'unknown'}),null);
  assert.equal(controls.featureRequest({...person,subject_id:'x'.repeat(161)}),null);
});

test('platform requests are explicit, empty, serialized and never accept credentials',async()=>{
  const calls=[];let complete;
  const command=controls.createPlatformCommands((...args)=>{calls.push(args);return new Promise(resolve=>{complete=resolve;});});
  assert.equal(calls.length,0);
  const pending=command.run('connect');
  await assert.rejects(command.run('connect'),/platform_command_busy/);
  assert.equal(calls[0][0],'/api/production/audience/twitch/connect');
  assert.equal(calls[0][1].body,'{}');assert.equal(calls[0][2],30000);
  complete({response:{ok:true},data:{state:'not_connected'}});await pending;
  assert.equal(command.busy(),false);
  await assert.rejects(command.run('send-chat'),/invalid_platform_command/);
});

function panelFixture(hostname='127.0.0.1',platform='twitch'){
  const ids=new Map(),calls=[],intervals=[];let source={platform,implemented:true,state:'not_connected',connected:false,authorized:false,verified:false,reason:'explicit_connection_required'};
  class Element{
    constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.listeners={};this.textContent='';this.value='';this.disabled=false;this.type='text';this.fields=new Map();this.elements={namedItem:name=>{if(!this.fields.has(name))this.fields.set(name,new Element('input'));return this.fields.get(name);}};}
    set innerHTML(value){for(const match of value.matchAll(/id="([^"]+)"/g))ids.set(match[1],new Element());ids.get('audienceRuleForm').elements.namedItem('enabled').type='checkbox';}
    append(...values){this.children.push(...values);}appendChild(value){this.append(value);return value;}
    replaceChildren(...values){this.children=[...values];}
    querySelector(selector){return selector.startsWith('#')?ids.get(selector.slice(1)):new Element('option');}
    querySelectorAll(){return [];}
    setAttribute(){}removeAttribute(){}addEventListener(type,callback){this.listeners[type]=callback;}focus(){}
  }
  const state=()=>({revision:1,enabled:true,sources:[source,...['twitch','youtube','kick'].filter(p=>p!==platform).map(platform=>({platform,implemented:false}))],rules:[],featured:[],participants:[],history:[]});
  const context={document:{hidden:false,createElement:tag=>new Element(tag)},location:{hostname,origin:'http://'+hostname},crypto:require('node:crypto').webcrypto,AbortController,
    setTimeout(){return 1;},clearTimeout(){},setInterval(fn){intervals.push(fn);},
    fetch:async(url,options={})=>{calls.push({url,options});if(url.endsWith('/connect'))source={...source,state:'connected',connected:true,authorized:true,verified:true};if(url.endsWith('/disconnect'))source={...source,state:'not_connected',connected:false,authorized:false,verified:false};return {ok:true,json:async()=>url==='/api/production/audience'?state():source};}};
  context.window=context;vm.runInNewContext(fs.readFileSync(path.join(root,'audience_controls.js'),'utf8'),context);
  context.ProducerAudienceControls.mount(new Element());
  return {ids,calls,intervals,context,button:()=>ids.get('audienceSources').children[0].children.find(child=>child.tagName==='button')};
}
async function settlePanel(){for(let i=0;i<15;i++)await Promise.resolve();}

test('mounted panel observes cached status but connects only after an explicit local click',async()=>{
  const f=panelFixture();await settlePanel();
  assert.deepEqual(f.calls.map(call=>call.url),['/api/production/audience']);
  assert.equal(f.button().textContent,'Connect Twitch');
  assert.equal(f.ids.get('audienceMasterStatus').textContent,'Armed · no connected sources');
  await f.button().listeners.click();await settlePanel();
  assert.equal(f.button().textContent,'Disconnect Twitch');
  assert.equal(f.ids.get('audienceMasterStatus').textContent,'Armed · observing chat');
  assert.equal(f.calls.find(call=>call.url.endsWith('/connect')).options.body,'{}');
  await f.button().listeners.click();await settlePanel();
  assert.equal(f.button().textContent,'Connect Twitch');
  assert.match(f.ids.get('audienceFeedback').textContent,/Twitch disconnected/);
  f.intervals[0]();await settlePanel();
  assert.equal(f.calls.filter(call=>call.options.method==='POST').length,2);
});

test('remote panel explains host-only controls and stale status never remains connected',async()=>{
  const f=panelFixture('192.0.2.10');await settlePanel();
  assert.equal(f.button().disabled,true);assert.match(f.button().title,/production host/);
  f.context.fetch=async()=>{throw Error('offline');};f.intervals[0]();await settlePanel();
  assert.match(f.ids.get('audienceFeedback').textContent,/Refresh to retry/);
  assert.equal(f.ids.get('audienceMasterStatus').textContent,'Armed · no connected sources');
});

test('YouTube commands use their own route and status without enabling other platforms',async()=>{
  const f=panelFixture('127.0.0.1','youtube');await settlePanel();
  assert.equal(f.button().textContent,'Connect YouTube');
  assert.equal(f.calls.filter(call=>call.options.method==='POST').length,0);
  await f.button().listeners.click();await settlePanel();
  assert.equal(f.button().textContent,'Disconnect YouTube');
  assert.deepEqual(f.calls.filter(call=>call.options.method==='POST').map(call=>call.url),['/api/production/audience/youtube/connect']);
  assert.match(f.ids.get('audienceFeedback').textContent,/YouTube connected/);
  assert.match(controls.connectionMessage({platform:'youtube',implemented:true,reason:'no_active_chat'}),/No active YouTube/);
  assert.doesNotMatch(controls.connectionMessage({platform:'youtube',implemented:true,reason:'credentials_required'}),/Twitch/);
});

test('Kick remains visibly unavailable until its registration is approved',()=>{
  const source={platform:'kick',implemented:true,reason:'dashboard_registration_approval_required'};
  const control=controls.platformControl(source,true);
  assert.equal(control.disabled,true);assert.equal(control.label,'Kick setup required');
  assert.match(control.title,/No public receiver is active/);
  assert.match(controls.connectionMessage(source),/receiver remains inactive/);
  assert.equal(controls.platformControl({...source,dashboard_registration_approved:true},false).disabled,true);
});

test('platform command selector rejects arbitrary routes and resets after network failure',async()=>{
  const calls=[],commands=controls.createPlatformCommands(async url=>{calls.push(url);throw Error('network failure');});
  await assert.rejects(commands.run('connect','../../guest'),/invalid_platform_command/);
  await assert.rejects(commands.run('connect','toString'),/invalid_platform_command/);
  assert.equal(calls.length,0);
  await assert.rejects(commands.run('connect','youtube'),/network failure/);
  assert.equal(commands.busy(),false);
  assert.deepEqual(calls,['/api/production/audience/youtube/connect']);
});
