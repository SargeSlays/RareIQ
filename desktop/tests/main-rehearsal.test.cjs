'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{EventEmitter}=require('node:events'),{pathToFileURL}=require('node:url');
const mainSource=fs.readFileSync(path.join(__dirname,'../main.cjs'),'utf8');
const generation='a'.repeat(32),tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
  const state={handlers:new Map(),windows:[],calls:[],writes:[],dialogs:[],answers:[],saves:[],poll:null,ready:null,quit:null,refreshFailure:null,local:false,pendingStart:null};
  const profile='F:/Temp/ProducerPlease-rehearsal-unit',origin='http://127.0.0.1:8765';
  const app=new EventEmitter();Object.assign(app,{setName(){},setAppUserModelId(){},setPath(){},requestSingleInstanceLock:()=>true,exit(){},getVersion:()=> 'unit',whenReady:()=>({then(callback){const promise=Promise.resolve().then(callback);state.ready=promise;return promise;}}),quit(){state.calls.push('app.quit');}});
  class Window extends EventEmitter{
    constructor(){super();const contents=new EventEmitter();Object.assign(contents,{mainFrame:{url:'about:blank'},getURL:()=>contents.mainFrame.url,setWindowOpenHandler(){},executeJavaScript:async()=>true,isDestroyed:()=>false});this.webContents=contents;this.dead=false;state.windows.push(this);}
    async loadFile(file){this.webContents.mainFrame.url=pathToFileURL(file).href;}
    async loadURL(url){this.webContents.mainFrame.url=url;}
    isDestroyed(){return this.dead;}isMinimized(){return false;}show(){}focus(){}hide(){}destroy(){this.dead=true;}
    static getAllWindows(){return state.windows;}
  }
  const partition={setPermissionRequestHandler(){},setDisplayMediaRequestHandler(){}};
  const electron={app,BrowserWindow:Window,Menu:{setApplicationMenu(){},buildFromTemplate:value=>value},dialog:{async showMessageBox(...args){const options=args.at(-1);state.dialogs.push(options);return {response:state.answers.shift()??0};},async showSaveDialog(_window,options){state.saves.push(options);return state.saveChoice??{canceled:true};}},ipcMain:{handle:(channel,handler)=>state.handlers.set(channel,handler)},shell:{openExternal:async()=>{}},session:{fromPartition:()=>partition},desktopCapturer:{},safeStorage:{}};
  class Broadcast{
    constructor(options){state.broadcast=this;this.options=options;this.outputProfile={id:'prepared-profile',format:'hd'};this.preparing=false;this.ownsEncoding=false;this.capture={show(){}};}
    active(){return this.rehearsing||state.productionActive===true;}status(){return {phase:this.rehearsing?'rehearsing':'prepared',ownershipPending:false,targets:[]};}
    async check(){state.calls.push('broadcast.check');}async prepare(){state.calls.push('broadcast.prepare');}async start(){state.calls.push('broadcast.start');await this.options.canPublish();}
    async stop(){state.calls.push('broadcast.stop');}async stopTarget(){state.calls.push('broadcast.stopTarget');}async close(){state.calls.push('broadcast.close');return state.broadcastClose!==false;}async setLiveAudio(){}
  }
  class Rehearsal{
    constructor(options){state.rehearsal=this;this.options=options;this.mode='production';this.bus='off';}
    status(){return {room:{mode:this.mode,active:this.mode!=='production',publishing_allowed:this.mode==='production',revision:3,generation,checks:[{id:'video',label:'Program picture',status:'not_tested'}]},local:{state:state.local?'encoding':'idle',running:state.local,frames:7,audioSamples:12,vodAudioSamples:0,bytesMuxed:99,ownershipPending:false},monitor:{bus:this.bus,available:true,vodAvailable:false},outputPrepared:true};}
    active(){return state.local;}publishingAllowed(){return this.mode==='production'&&!state.local;}
    async refresh(){state.calls.push('rehearsal.refresh');if(state.refreshFailure)throw Object.assign(Error(state.refreshFailure),{code:state.refreshFailure});return this.status();}
    async canPublish(){state.calls.push('rehearsal.canPublish');return this.publishingAllowed();}
    async check(){state.calls.push('rehearsal.check');}async enter(value){state.calls.push(['rehearsal.enter',value]);this.mode='rehearsal';}
    async start(value){state.calls.push(['rehearsal.start',value]);state.local=true;if(state.pendingStart)await state.pendingStart;}
    async stop(){state.calls.push('rehearsal.stop');state.local=false;this.bus='off';}
    async exit(value){state.calls.push(['rehearsal.exit',value]);this.mode='production';}async recover(value){state.calls.push(['rehearsal.recover',value]);this.mode='production';}
    async mark(value){state.calls.push(['rehearsal.mark',value]);}async monitor(value){state.calls.push(['rehearsal.monitor',value]);this.bus=value.bus;}
    async close(){state.calls.push('rehearsal.close');if(state.closeThrows)throw Error('private close details');return state.rehearsalClose!==false;}
  }
  const safeCodes=new Set(['rehearsal_revision_conflict','rehearsal_generation_conflict','rehearsal_not_active','rehearsal_storage_invalid']);
  const fakeFs={mkdirSync(){},readFileSync:()=>JSON.stringify({buildKind:'local-development'}),existsSync:()=>true,appendFileSync(){},writeFileSync(file,value,options){state.writes.push({file,value,options});if(state.writeFailure)throw Error('private path');}};
  const modules={'./kick-connection.cjs':{createKickResolver:()=>async()=>{}},'./saved-account-resolver.cjs':{createSavedAccountResolver:options=>{state.savedAccountOptions=options;return async()=>{};}},electron,'node:fs':fakeFs,'./policy.cjs':{sameStudio:(url,expected)=>new URL(url).origin===expected,studioOrigin:value=>value,applySessionPolicy(){},trustedMain:(event,contents)=>event.sender===contents&&event.senderFrame===contents.mainFrame,allowedExternal:()=>false},'./backend.cjs':{Backend:class{async start(){this.started={identity:{instance_id:'unit',boot_id:'unit'}};return {origin};}async close(){return {running:false};}}},'./startup.cjs':{loadInitialStudio:async(contents,url)=>{contents.mainFrame.url=url;}},'./runtime.cjs':{resolveRuntime:()=>({python:'unit',sharedEncoderWorker:'unit',encoderWorker:'unit'})},'./twitch-connection.cjs':{createTwitchResolver:()=>async()=>{},createTwitchConnection:()=>Object.assign(async()=>({ok:true}),{checkSaved:async()=>{}})},'./destinations.cjs':{DestinationStore:class{async public(){return {};}async save(value){state.calls.push(['destination.save',value]);return value;}}},'./output-profiles.cjs':{OutputProfileStore:class{async public(){return {};}}},'./stream-info.cjs':{StreamInfoStore:class{},createStreamInfoActions:()=>({list:async()=>({}),save:async()=>({})})},'./profile-actions.cjs':{createProfileActions:()=>({save:async value=>value,remove:async()=>{},select:async()=>{}})},'./capture-picker.cjs':{createCapturePicker:()=>({handler(){},close(){}})},'./broadcast.cjs':{NativeBroadcast:Broadcast},'./shared-encoder.cjs':{SharedEncoderGroup:class{}},'./output-capture.cjs':{createOutputCapture:options=>{state.captureOptions=options;return {}; }},'./rehearsal.cjs':{RehearsalCoordinator:Rehearsal,sanitizeSourceCallbackCode:(value,fallback)=>safeCodes.has(value?.code||value?.message||value)?value?.code||value?.message||value:fallback},'./account-authorization.cjs':{createAccountAuthorization:()=>async()=>{}},'./provider-connection.cjs':{createProviderConnection:()=>async()=>{}},'./stream-metadata.cjs':{createStreamMetadataHandler:()=>async()=>{}},'./app-setup-import.cjs':{createAppSetupImporter:()=>async()=>{}},'./quit.cjs':{createQuitCoordinator:options=>{state.quit=options;return {request(){},finished:false,draining:false};}}};
  const context={require:name=>Object.hasOwn(modules,name)?modules[name]:require(name),__dirname:path.resolve(__dirname,'..'),process:{argv:[],env:{PRODUCER_DESKTOP_DATA:profile,PRODUCER_DESKTOP_RUNTIME:'F:/unit/runtime.json'},pid:123,resourcesPath:'F:/unit'},URL,AbortSignal,Promise,console,setInterval:callback=>{state.poll=callback;return {unref(){}};},clearInterval(){},fetch:async(url,options)=>{state.requestCalls??=[];state.requestCalls.push({url,options});return {ok:state.requestResponse?.ok??true,json:async()=>state.requestResponse?.value??({ok:true})};}};
  vm.runInNewContext(mainSource,context,{filename:'main.cjs'});
  state.boot=async()=>{await state.ready;const studio=state.windows[0];await state.handlers.get('producer:settings')({sender:studio.webContents,senderFrame:studio.webContents.mainFrame});state.settings=state.windows[1];state.event={sender:state.settings.webContents,senderFrame:state.settings.webContents.mainFrame};state.invoke=value=>state.handlers.get('producer:rehearsal')(state.event,vm.runInNewContext('('+JSON.stringify(value)+')',context));return state;};
  return state;
}
const command=(action,extra={})=>({action,requestId:'unit-request',revision:3,generation,...extra});

test('original Main exposes only the trusted settings rehearsal bridge and fails closed on unknown actions',async()=>{
  const f=await fixture().boot(),handler=f.handlers.get('producer:rehearsal');assert.equal((await handler({sender:{},senderFrame:{}},{action:'status'})).reason,'local_operator_required');
  for(const value of [{action:'constructor'},{action:'status',unexpected:true},command('mark',{checkId:'video',checkState:'invented'}),command('exit',{revision:-1}),command('start',{profileId:45})])assert.equal((await f.invoke(value)).reason,'invalid_rehearsal_command');
  assert.equal(f.dialogs.length,0);const value=await f.invoke({action:'status'});assert.equal(value.ok,true);assert.equal(value.room.mode,'production');
});
test('original Main maps UI commands and derives the prepared profile without destination lookup',async()=>{
  const f=await fixture().boot();assert.equal((await f.invoke(command('enter'))).ok,true);assert.equal((await f.invoke(command('start'))).ok,true);
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls.find(call=>Array.isArray(call)&&call[0]==='rehearsal.enter')[1])),{requestId:'unit-request',revision:3});
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls.find(call=>Array.isArray(call)&&call[0]==='rehearsal.start')[1])),{requestId:'unit-request',revision:3,generation,profileId:'prepared-profile'});
  await f.invoke(command('mark',{checkId:'video',checkState:'passed'}));assert.deepEqual(JSON.parse(JSON.stringify(f.calls.find(call=>Array.isArray(call)&&call[0]==='rehearsal.mark')[1])),{requestId:'unit-request',revision:3,generation,checkId:'video',status:'passed'});
});
test('original Main checks publishing freshly and polls both production and local ownership',async()=>{
  const f=await fixture().boot();await f.broadcast.options.canPublish();assert.ok(f.calls.includes('rehearsal.canPublish'));f.poll();await tick();assert.ok(f.calls.includes('broadcast.check'));assert.ok(f.calls.includes('rehearsal.check'));
  f.rehearsal.mode='rehearsal';const publicValue=await f.handlers.get('producer:broadcast:status')(f.event);assert.equal(publicValue.publishingAllowed,false);assert.equal(publicValue.rehearsal.room.mode,'rehearsal');
});
test('original Main exit and recovery default to Cancel and return an unchanged successful cancellation',async()=>{
  const f=await fixture().boot();f.rehearsal.mode='rehearsal';for(const action of ['exit','recover']){const result=await f.invoke(command(action));assert.equal(result.ok,true);assert.equal(result.cancelled,true);assert.equal(result.room.mode,'rehearsal');assert.equal(f.dialogs.at(-1).defaultId,0);assert.equal(f.dialogs.at(-1).cancelId,0);}
  f.answers.push(1);assert.equal((await f.invoke(command('exit'))).room.mode,'production');
});
test('original Main local Stop supersedes pending Start and remains available during another mutation',async()=>{
  const f=await fixture().boot();f.rehearsal.mode='rehearsal';let resolve;f.pendingStart=new Promise(done=>resolve=done);const start=f.invoke(command('start'));await tick();assert.equal(f.local,true);
  assert.equal((await f.invoke(command('mark',{checkId:'video',checkState:'passed'}))).reason,'destination_change_pending');assert.equal((await f.invoke({action:'stop'})).ok,true);assert.equal(f.local,false);resolve();await start;
});
test('original Main keeps local capture separate and turns monitoring off before a replacement Prepare',async()=>{
  const f=await fixture().boot();f.local=true;await assert.rejects(f.handlers.get('producer:broadcast:prepare')(f.event,{}),/destination_broadcast_busy/);await assert.rejects(f.handlers.get('producer:destinations:save')(f.event,{}),/destination_broadcast_busy/);
  f.local=false;await f.handlers.get('producer:broadcast:prepare')(f.event,{});const monitor=f.calls.findIndex(call=>Array.isArray(call)&&call[0]==='rehearsal.monitor');assert.ok(monitor>=0);assert.ok(monitor<f.calls.indexOf('broadcast.prepare'));
  f.broadcast.options.createCapture({});f.local=true;f.captureOptions.onError('output_lost');await tick();assert.ok(f.calls.includes('rehearsal.stop'));assert.ok(!f.calls.includes('broadcast.stop'));
});
test('original Main global Stop and Quit release local ownership before production capture',async()=>{
  const f=await fixture().boot();f.local=true;await f.handlers.get('producer:broadcast:stop')(f.event);assert.equal(f.calls.at(-1),'rehearsal.stop');f.rehearsalClose=false;assert.equal(await f.quit.release(),false);assert.ok(!f.calls.includes('broadcast.close'));assert.ok(!f.windows.some(window=>window.dead));
  f.rehearsalClose=true;f.closeThrows=true;assert.equal(await f.quit.release(),false);assert.ok(!f.calls.includes('broadcast.close'));f.closeThrows=false;await f.quit.release();assert.ok(f.calls.indexOf('rehearsal.close')<f.calls.indexOf('broadcast.close'));assert.ok(f.windows.every(window=>window.dead));
});
test('original Main exports only bounded rehearsal metadata to a native chosen path, with no overwrite',async()=>{
  const f=await fixture().boot();f.rehearsal.mode='rehearsal';assert.equal((await f.invoke(command('export_report'))).cancelled,true);assert.equal(f.writes.length,0);assert.match(f.saves[0].defaultPath,/^F:[/\\]Users[/\\].+[/\\]Documents[/\\]ProducerPlease[/\\]Rehearsals[/\\]/);
  f.saveChoice={canceled:false,filePath:'F:/Temp/rehearsal-unit.json'};assert.equal((await f.invoke(command('export_report'))).reportSaved,true);const saved=f.writes[0];assert.equal(saved.options.flag,'wx');const report=JSON.parse(saved.value);assert.equal(report.platformDeliveryVerified,false);assert.equal(report.hardwareVerified,false);assert.equal(report.room.checks[0].operatorObservation,true);assert.doesNotMatch(saved.value,/generation|destination|account|streamKey|source|chat/);
  f.writeFailure=true;assert.equal((await f.invoke(command('export_report'))).reason,'rehearsal_report_not_saved');
});
test('original Main preserves only known rehearsal errors and redacts unknown private errors',async()=>{
  const f=await fixture().boot();f.refreshFailure='rehearsal_storage_invalid';assert.equal((await f.invoke({action:'status'})).reason,'rehearsal_storage_invalid');f.refreshFailure='private path and token';assert.equal((await f.invoke({action:'status'})).reason,'rehearsal_status_unavailable');f.requestResponse={ok:false,value:{ok:false,reason:'rehearsal_storage_invalid'}};await assert.rejects(f.rehearsal.options.request('/api/production/rehearsal'),{code:'rehearsal_storage_invalid'});f.requestResponse.value.reason='private credentials';await assert.rejects(f.rehearsal.options.request('/api/production/rehearsal'),{code:'studio_unavailable'});
});
test('the sandboxed settings preload exposes the native rehearsal invocation without Node access',()=>{
  let bridge,channel,payload;const source=fs.readFileSync(path.join(__dirname,'../settings-preload.cjs'),'utf8');vm.runInNewContext(source,{require:()=>({contextBridge:{exposeInMainWorld:(_name,value)=>{bridge=value;}},ipcRenderer:{invoke:(name,value)=>{channel=name;payload=value;}}})});const value={action:'stop'};bridge.rehearsal(value);assert.equal(channel,'producer:rehearsal');assert.equal(payload,value);assert.equal(Object.isFrozen(bridge),true);
});


test('Main rehearsal HTTP commands carry the exact local Origin required by the original router',async()=>{
  const f=await fixture().boot();
  await f.rehearsal.options.request('/api/production/rehearsal/enter',{request_id:'origin-regression',expected_revision:0});
  const request=f.requestCalls.at(-1);assert.equal(request.url,'http://127.0.0.1:8765/api/production/rehearsal/enter');assert.equal(request.options.headers.Origin,'http://127.0.0.1:8765');assert.equal(request.options.headers['Content-Type'],'application/json');assert.equal(request.options.method,'POST');
});


test('monitor selection checks fresh room generation while Off bypasses setup mutations',async()=>{
  const f=await fixture().boot();f.rehearsal.mode='rehearsal';
  const stale=await f.invoke(command('monitor',{bus:'live',generation:'b'.repeat(32)}));assert.equal(stale.reason,'rehearsal_generation_conflict');assert.ok(!f.calls.some(call=>Array.isArray(call)&&call[0]==='rehearsal.monitor'));
  const selected=await f.invoke(command('monitor',{bus:'live'}));assert.equal(selected.ok,true);assert.equal(selected.monitor.bus,'live');
  let release;f.pendingStart=new Promise(resolve=>{release=resolve;});const start=f.invoke(command('start'));await tick();
  const off=await f.invoke({action:'monitor',bus:'off'});assert.equal(off.ok,true);assert.equal(off.monitor.bus,'off');release();await start;
});


test('Main passes both private provider resolvers to its sole saved-account coordinator',async()=>{
  const f=await fixture().boot();assert.equal(f.savedAccountOptions.origin,'http://127.0.0.1:8765');assert.equal(typeof f.savedAccountOptions.resolveTwitch,'function');assert.equal(typeof f.savedAccountOptions.resolveKick,'function');
});
