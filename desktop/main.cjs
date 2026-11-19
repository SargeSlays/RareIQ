'use strict';
const {app,BrowserWindow,Menu,dialog,ipcMain,shell,session,desktopCapturer}=require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{pathToFileURL}=require('node:url');
const policy=require('./policy.cjs'),{Backend}=require('./backend.cjs');
const {loadInitialStudio}=require('./startup.cjs');
app.setName('Producer, Please');app.setAppUserModelId('com.producerplease.studio');
const preview=process.argv.includes('--preview');
const profile=process.env.PRODUCER_DESKTOP_QA_PROFILE||process.env.PRODUCER_DESKTOP_DATA||path.join('F:/Users',os.userInfo().username,'AppData',preview?'ProducerPleasePreview':'ProducerPlease');
if(!path.isAbsolute(profile))throw Error('Desktop data must use an absolute directory');
for(const directory of [profile,path.join(profile,'browser'),path.join(profile,'logs'),path.join(profile,'crashes')])fs.mkdirSync(directory,{recursive:true});
app.setPath('userData',profile);app.setPath('sessionData',path.join(profile,'browser'));app.setPath('logs',path.join(profile,'logs'));app.setPath('crashDumps',path.join(profile,'crashes'));
let studio,settings,backend,origin,destinations,outputProfiles,capturePicker,quit,runtime,broadcast,rehearsal,polling,choosingSources,destinationMutation=false;
if(!app.requestSingleInstanceLock())app.exit(0);
app.on('second-instance',()=>{if(studio){if(studio.isMinimized())studio.restore();studio.show();studio.focus();}});
function windowOptions(extra={}){return {width:1600,height:1000,minWidth:800,minHeight:600,title:'Producer, Please',icon:path.join(__dirname,'assets','icon-512.png'),backgroundColor:'#101318',autoHideMenuBar:false,...extra,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true,allowRunningInsecureContent:false,webviewTag:false,backgroundThrottling:false,...extra.webPreferences}};}
function secureWindow(window,allowed){window.webContents.setWindowOpenHandler(({url})=>{if(policy.sameStudio(url,origin)&&!new URL(url).pathname.startsWith('/guest')){const child=new BrowserWindow(windowOptions({webPreferences:{partition:'persist:producer-studio'}}));secureWindow(child,origin);child.loadURL(url);}else if(policy.allowedExternal(url)||(policy.sameStudio(url,origin)&&new URL(url).pathname.startsWith('/guest')))shell.openExternal(url);return {action:'deny'};});window.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith(allowed+'/')&&url!==allowed)event.preventDefault();});window.webContents.on('will-redirect',(event,url,_inPlace,isMainFrame)=>{if(isMainFrame!==false&&!policy.sameStudio(url,origin))event.preventDefault();});window.webContents.on('will-attach-webview',event=>event.preventDefault());}
function settingsEvent(event){return settings&&!settings.isDestroyed()&&event.sender===settings.webContents&&event.senderFrame===settings.webContents.mainFrame&&event.senderFrame.url===pathToFileURL(path.join(__dirname,'settings.html')).href;}
async function changeDestination(event,action){
  if(!settingsEvent(event))throw Error('Untrusted request');
  if(destinationMutation)throw Error('destination_change_pending');
  if(!broadcast||broadcast.active()||broadcast.preparing||broadcast.status().ownershipPending||rehearsal?.active())throw Error('destination_broadcast_busy');
  destinationMutation=true;
  try{return await action();}finally{destinationMutation=false;}
}
async function openSettings(){if(settings&&!settings.isDestroyed()){settings.show();settings.focus();return;}
  settings=new BrowserWindow(windowOptions({width:860,height:790,parent:studio,webPreferences:{preload:path.join(__dirname,'settings-preload.cjs'),partition:'persist:producer-settings'}}));settings.webContents.setWindowOpenHandler(()=>({action:'deny'}));settings.webContents.on('will-navigate',event=>event.preventDefault());await settings.loadFile(path.join(__dirname,'settings.html'));
}
async function openSources(event){
  if(!settingsEvent(event))throw Error('Untrusted request');
  if(choosingSources)return choosingSources;
  const owner=settings,target=studio;
  choosingSources=(async()=>{
    const available=()=>target&&target===studio&&!target.isDestroyed()&&policy.sameStudio(target.webContents.getURL(),origin)&&new URL(target.webContents.getURL()).pathname==='/control'&&target.webContents.mainFrame.url===target.webContents.getURL();
    if(!available())throw Error('Studio sources are unavailable. Keep this window open and try again.');
    const frame=target.webContents.mainFrame;
    let opened=false;try{opened=await target.webContents.executeJavaScript('window.ProducerDesktopNavigation?.openSources() === true',false);}catch(_){}
    if(opened!==true||!available()||target.webContents.mainFrame!==frame)throw Error('Studio sources are not ready yet. Keep this window open and try again.');
    if(target.isMinimized())target.restore();target.show();target.focus();
    if(settings===owner&&!owner.isDestroyed())owner.hide();
    return {ok:true};
  })().finally(()=>{choosingSources=null;});
  return choosingSources;
}
function viewOutput(event){
  if(!settingsEvent(event))throw Error('Untrusted request');
  if(typeof broadcast?.capture?.show!=='function')throw Error('Prepare Studio Output before choosing View output.');
  broadcast.capture.show();return {ok:true};
}
app.whenReady().then(async()=>{
  const fixture=process.env.PRODUCER_DESKTOP_QA_ORIGIN;
  const runtimePath=process.env.PRODUCER_DESKTOP_RUNTIME||path.join(process.resourcesPath,'runtime.json');const manifest=JSON.parse(fs.readFileSync(runtimePath,'utf8'));
  if(preview&&manifest.buildKind!=='bundled-runtime')throw Error('Standalone preview needs the bundled desktop build.');
  const qaPort=process.env.PRODUCER_DESKTOP_QA_PROFILE&&process.env.PRODUCER_DESKTOP_QA_PORT?Number(process.env.PRODUCER_DESKTOP_QA_PORT):undefined;
  runtime=require('./runtime.cjs').resolveRuntime(manifest,path.dirname(runtimePath),profile,{port:qaPort??(preview?8767:undefined)});
  if(fixture){origin=policy.studioOrigin(fixture);}else{
    backend=new Backend(runtime,path.join(profile,'backend-owner.json'));const started=await backend.start();origin=policy.studioOrigin(started.origin||started.url);
  }
  const partition=session.fromPartition('persist:producer-studio');policy.applySessionPolicy(partition,origin);
  // Device grants always require an explicit native prompt from the trusted main studio.
  partition.setPermissionRequestHandler(async(contents,permission,callback,details)=>{
    if(!['media','display-capture'].includes(permission)||!policy.sameStudio(contents.getURL(),origin)||details.isMainFrame!==true||!policy.sameStudio(details.requestingUrl,origin))return callback(false);
    if(permission==='display-capture')return callback(true);
    const response=await dialog.showMessageBox(studio,{type:'question',buttons:['Allow this time','Cancel'],defaultId:1,cancelId:1,message:'Allow Producer, Please to use your camera or microphone?',detail:'Choose Allow only after selecting a capture control in the studio.'});callback(response.response===0);
  });
  const {createTwitchResolver,createTwitchConnection}=require('./twitch-connection.cjs');
  const resolveTwitch=createTwitchResolver({runtime});
  const resolveKick=require('./kick-connection.cjs').createKickResolver({runtime});
  const accountResolver=require('./saved-account-resolver.cjs').createSavedAccountResolver({origin,resolveTwitch,resolveKick});
  const {DestinationStore}=require('./destinations.cjs');destinations=new DestinationStore({directory:profile,cipher:require('electron').safeStorage,
    accountResolver});
  const {OutputProfileStore}=require('./output-profiles.cjs');outputProfiles=new OutputProfileStore({directory:profile});
  const {StreamInfoStore,createStreamInfoActions}=require('./stream-info.cjs');
  const streamInfo=new StreamInfoStore({directory:profile});
  const streamInfoActions=createStreamInfoActions({store:streamInfo,trustedSender:settingsEvent,mutate:changeDestination,
    append:entry=>fs.appendFileSync(path.join(profile,'activity.jsonl'),JSON.stringify(entry)+'\n',{mode:0o600})});
  const profileActions=require('./profile-actions.cjs').createProfileActions({store:outputProfiles,append:entry=>fs.appendFileSync(path.join(profile,'activity.jsonl'),JSON.stringify(entry)+'\n',{mode:0o600})});
  studio=new BrowserWindow(windowOptions({webPreferences:{partition:'persist:producer-studio',preload:path.join(__dirname,'preload.cjs')}}));secureWindow(studio,origin);
  const {createCapturePicker}=require('./capture-picker.cjs');capturePicker=createCapturePicker({BrowserWindow,ipcMain,desktopCapturer,studio,origin});partition.setDisplayMediaRequestHandler(capturePicker.handler);
  studio.on('close',event=>{if(backend&&!quit?.finished){event.preventDefault();app.quit();}});
  const {NativeBroadcast}=require('./broadcast.cjs'),{SharedEncoderGroup}=require('./shared-encoder.cjs'),{createOutputCapture}=require('./output-capture.cjs');
  const {RehearsalCoordinator,sanitizeSourceCallbackCode}=require('./rehearsal.cjs');
  const outputSession=session.fromPartition('persist:producer-output');policy.applySessionPolicy(outputSession,origin);
  const request=async(url,body)=>{const response=await fetch(origin+url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json',Origin:origin}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(8000)});const value=await response.json();const preflight=!body&&url.startsWith('/api/production/native-preflight?')&&value.preflight&&typeof value.preflight.ready==='boolean';if(!response.ok||(value.ok===false&&!preflight)){const code=sanitizeSourceCallbackCode(value.reason,'studio_unavailable');throw Object.assign(Error(code),{code});}return value;};
  let lastPhase='';broadcast=new NativeBroadcast({destinations,outputProfiles,identity:backend?.started?.identity,ownerPid:process.pid,request,
    canPublish:()=>rehearsal?rehearsal.canPublish():Promise.reject(Error('rehearsal_status_unavailable')),
    createCapture:dimensions=>createOutputCapture({BrowserWindow,ipcMain,origin,...dimensions,onError:code=>{if(rehearsal?.active())rehearsal.stop(code).catch(()=>{});else if(broadcast?.active())broadcast.stop(code).catch(()=>{});}}),
    createEncoderGroup:onState=>new SharedEncoderGroup({python:runtime.python,workerPath:runtime.sharedEncoderWorker,pythonPackages:runtime.pythonPackages,onState}),
    confirm:async (selection,output,selectionInfo)=>{
      const chosen=Array.isArray(selection)?selection:[selection];
      const vodTargets=output.twitchVod?chosen.filter(target=>target.platform==='twitch').length:0;
      const upload=(chosen.length*(output.videoBitrateKbps+output.audioBitrateKbps)+vodTargets*output.audioBitrateKbps)/1000;
      const info=await streamInfo.public();
      const streamInfoReview='\n\nSaved stream info drafts:\n'+chosen.map((p,index)=>'• '+p.name+': '+((info.overrides[selectionInfo.destinationIds[index]]||info.shared).title.trim()||'No title drafted')).join('\n')+'\nCheck each destination’s update status in Stream info before starting. Saved drafts alone do not confirm platform updates.';
      const detail='Your current Program picture and Live audio will be sent to:\n'+chosen.map(p=>'• '+p.name).join('\n')+'\n\n'+output.name+': '+output.fps+' fps, '+output.videoBitrateKbps+' kbps video, '+output.audioBitrateKbps+' kbps AAC. Approximate combined upload: '+upload.toFixed(1)+' Mbps before overhead.'+(output.twitchVod?'\nA separate VOD mix is sent to Twitch destinations; Twitch archive receipt is not yet verified.':'')+'\nCheck each platform dashboard to confirm receipt.';
      const answer=await dialog.showMessageBox(settings&&!settings.isDestroyed()?settings:studio,{type:'warning',message:'Start a live broadcast?',detail:detail+streamInfoReview,buttons:['Cancel','Start broadcast'],defaultId:0,cancelId:0});return answer.response===1;
    },
    onAudioAudit:entry=>fs.appendFileSync(path.join(profile,'activity.jsonl'),JSON.stringify({at:new Date().toISOString(),action:'audio_mix.set',actor:'Desktop operator',identityVerified:false,profileId:entry.profileId,requestId:entry.requestId,revision:entry.revision})+'\n',{mode:0o600}),
    onState:value=>{
      const state=JSON.stringify({phase:value.phase,targets:value.targets.map(t=>({destinationId:t.destinationId,phase:t.phase,reason:t.reason}))});
      if(state!==lastPhase){lastPhase=state;try{fs.appendFileSync(path.join(profile,'activity.jsonl'),JSON.stringify({at:new Date().toISOString(),action:'broadcast.'+value.phase,actor:'Desktop operator',identityVerified:false,profileId:value.profileId,destinationIds:value.destinationIds,targets:value.targets.map(t=>({destinationId:t.destinationId,phase:t.phase,reason:t.reason})),reason:value.reason||null})+'\n');}catch(_){}}
    }
  });
  rehearsal=new RehearsalCoordinator({broadcast,identity:backend?.started?.identity,ownerPid:process.pid,request,
    createEncoderGroup:onState=>new SharedEncoderGroup({python:runtime.python,workerPath:runtime.sharedEncoderWorker,pythonPackages:runtime.pythonPackages,onState})});
  await rehearsal.refresh().catch(()=>{});
  let nextAccountCheck=0,accountChecking=false;
  polling=setInterval(()=>{
    broadcast.check().catch(()=>{});
    rehearsal.check().catch(()=>{});
    if(!accountChecking&&Date.now()>=nextAccountCheck){accountChecking=true;nextAccountCheck=Date.now()+3600000;twitchConnection.checkSaved().catch(()=>{nextAccountCheck=Date.now()+60000;}).finally(()=>{accountChecking=false;});}
  },1000);polling.unref();
  const publicBroadcast=()=>({...broadcast.status(),rehearsal:rehearsal.status(),publishingAllowed:rehearsal.publishingAllowed(),available:Boolean(runtime.encoderWorker&&fs.existsSync(runtime.encoderWorker)&&runtime.sharedEncoderWorker&&fs.existsSync(runtime.sharedEncoderWorker)&&backend?.started?.identity)});
  const {createAccountAuthorization}=require('./account-authorization.cjs');
  const authorizeAccount=createAccountAuthorization({origin,
    trustedSender:event=>settingsEvent(event)||Boolean(studio&&!studio.isDestroyed()&&policy.trustedMain(event,studio.webContents,origin)
      &&new URL(event.senderFrame.url).pathname==='/control'),
    openExternal:url=>shell.openExternal(url)});

  ipcMain.handle('producer:accounts:authorize',authorizeAccount);
  const twitchConnection=createTwitchConnection({origin,store:destinations,trustedSender:settingsEvent,mutate:changeDestination,
    append:entry=>fs.appendFileSync(path.join(profile,'activity.jsonl'),JSON.stringify(entry)+'\n',{mode:0o600})});
  ipcMain.handle('producer:accounts:twitch',twitchConnection);
  const providerConnection=require('./provider-connection.cjs').createProviderConnection({origin,store:destinations,trustedSender:settingsEvent,mutate:changeDestination,authorize:authorizeAccount,append:entry=>fs.appendFileSync(path.join(profile,'activity.jsonl'),JSON.stringify(entry)+'\n',{mode:0o600})});
  ipcMain.handle('producer:accounts:provider',providerConnection);
  const streamMetadata=require('./stream-metadata.cjs').createStreamMetadataHandler({origin,store:streamInfo,destinations,
    trustedSender:settingsEvent,mutate:changeDestination,
    permission:async(event,platform)=>{
      if(platform==='twitch')return twitchConnection(event,{action:'begin_metadata'});
      const started=await providerConnection(event,{platform,action:'begin_metadata'});
      if(started?.ok!==true||started.account?.state!=='pending')return started;
      return providerConnection(event,{platform,action:'authorize',flowId:started.account.flow_id});
    },
    confirm:async review=>{
      const target=review.channelLabel+(review.broadcastId?' · broadcast '+review.broadcastId:'');
      const fields=Object.keys(review.values).map(name=>name==='category_id'?'category':name).join(', ');
      const answer=await dialog.showMessageBox(settings,{type:'question',message:'Update stream info on '+review.platform+'?',detail:'Connected channel: '+target+'\nDraft: '+review.destinationName+'\nTitle: '+review.values.title+'\nFields to replace: '+fields+'\n\nThis changes the connected channel’s stream information. A manually entered stream key does not verify which channel it belongs to. No broadcast will start.',buttons:['Cancel','Apply stream info'],defaultId:0,cancelId:0});
      return answer.response===1;
    }});
  ipcMain.handle('producer:stream-metadata',streamMetadata);
  ipcMain.handle('producer:rehearsal',async(event,value)=>{
    if(!settingsEvent(event))return {ok:false,reason:'local_operator_required'};
    const envelope=value&&typeof value==='object'&&!Array.isArray(value)&&[Object.prototype,null].includes(Object.getPrototypeOf(value));
    const fields={status:['action'],enter:['action','requestId','revision','generation'],start:['action','requestId','revision','generation','profileId'],stop:['action','requestId','revision','generation'],exit:['action','requestId','revision','generation'],recover:['action','requestId','revision','generation'],mark:['action','requestId','revision','generation','checkId','checkState'],monitor:['action','requestId','revision','generation','bus'],export_report:['action','requestId','revision','generation']};
    if(!envelope||typeof value.action!=='string'||!Object.hasOwn(fields,value.action)||Object.keys(value).some(key=>!fields[value.action].includes(key)))return {ok:false,reason:'invalid_rehearsal_command'};
    if(!['status','stop'].includes(value.action)&&!(value.action==='monitor'&&value.bus==='off')&&(typeof value.requestId!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId)||!Number.isSafeInteger(value.revision)||value.revision<0||value.revision>=Number.MAX_SAFE_INTEGER-2||value.action!=='enter'&&(typeof value.generation!=='string'||!/^[a-f0-9]{32}$/.test(value.generation))))return {ok:false,reason:'invalid_rehearsal_command'};
    if(value.action==='start'&&value.profileId!==undefined&&(typeof value.profileId!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(value.profileId))||value.action==='monitor'&&!['off','live','vod'].includes(value.bus)||value.action==='mark'&&(!['video','audio_live','audio_vod','guests','screens','transitions','recovery'].includes(value.checkId)||!['not_tested','passed','needs_attention'].includes(value.checkState)))return {ok:false,reason:'invalid_rehearsal_command'};
    const status=()=>({ok:true,...rehearsal.status()}),action=value.action;
    try{
      if(action==='status'){await rehearsal.refresh();return status();}
      // Stop must supersede a pending local Start or setup mutation.
      if(action==='stop'){await rehearsal.stop();return status();}
      if(action==='monitor'&&value.bus==='off'){await rehearsal.monitor({bus:'off'});return status();}
      if(destinationMutation)throw Error('destination_change_pending');
      destinationMutation=true;
      try{
        if(action==='exit'||action==='recover'){
          const answer=await dialog.showMessageBox(settings,{type:'warning',message:action==='recover'?'Restore production setup?':'Leave rehearsal?',detail:action==='recover'?'The interrupted rehearsal state will be preserved in a recovery copy. Publishing becomes available only after local encoding has stopped and recovery succeeds. No broadcast or recording will start.':'Local encoding will stop and monitoring will turn off. Publishing becomes available after you leave rehearsal; starting a broadcast still requires its separate confirmation.',buttons:['Cancel',action==='recover'?'Restore production setup':'Leave rehearsal'],defaultId:0,cancelId:0});
          if(answer.response!==1)return {...status(),cancelled:true};
          if(!settingsEvent(event))throw Error('rehearsal_cancelled');
        }
        if(action==='export_report'){
          await rehearsal.refresh();const snapshot=rehearsal.status();
          if(!snapshot.room?.active)throw Error('rehearsal_not_active');
          if(value.revision!==snapshot.room.revision)throw Error('rehearsal_revision_conflict');
          if(value.generation!==snapshot.room.generation)throw Error('rehearsal_generation_conflict');
          const directory=path.join('F:/Users',os.userInfo().username,'Documents','ProducerPlease','Rehearsals');
          fs.mkdirSync(directory,{recursive:true});
          const stamp=new Date().toISOString().replace(/[:.]/g,'-'),choice=await dialog.showSaveDialog(settings,{title:'Save rehearsal report',defaultPath:path.join(directory,'rehearsal-'+stamp+'.json'),filters:[{name:'Rehearsal report',extensions:['json']}],properties:['createDirectory','showOverwriteConfirmation']});
          if(choice.canceled||!choice.filePath)return {...status(),cancelled:true};
          if(!settingsEvent(event))throw Error('rehearsal_cancelled');
          // Deliberately omit source names, destinations, account identities and media.
          const report={schema:1,createdAt:new Date().toISOString(),kind:'local_rehearsal',platformDeliveryVerified:false,hardwareVerified:false,room:{mode:snapshot.room.mode,revision:snapshot.room.revision,checks:snapshot.room.checks.map(check=>({id:check.id,label:check.label,status:check.status,operatorObservation:true}))},local:snapshot.local,monitor:{bus:snapshot.monitor.bus}};
          try{fs.writeFileSync(choice.filePath,JSON.stringify(report,null,2)+'\n',{encoding:'utf8',mode:0o600,flag:'wx'});}catch(_){throw Error('rehearsal_report_not_saved');}
          return {...status(),reportSaved:true};
        }
        const command={requestId:value.requestId,revision:value.revision,generation:value.generation};
        if(action==='enter')await rehearsal.enter({requestId:value.requestId,revision:value.revision});
        else if(action==='start')await rehearsal.start({...command,profileId:value.profileId??broadcast.outputProfile?.id??'current-output'});
        else if(action==='mark')await rehearsal.mark({...command,checkId:value.checkId,status:value.checkState});
        else if(action==='monitor'){
          await rehearsal.refresh();const room=rehearsal.status().room;
          if(room?.mode!=='rehearsal')throw Error('rehearsal_not_active');
          if(room.revision!==value.revision)throw Error('rehearsal_revision_conflict');
          if(room.generation!==value.generation)throw Error('rehearsal_generation_conflict');
          await rehearsal.monitor({bus:value.bus});
        }
        else await rehearsal[action](command);
        return status();
      }finally{destinationMutation=false;}
    }catch(error){const reason=['destination_change_pending','rehearsal_report_not_saved'].includes(error?.message)?error.message:sanitizeSourceCallbackCode(error,'rehearsal_status_unavailable');return {ok:false,reason,...rehearsal.status()};}
  });
  const importAppSetup=require('./app-setup-import.cjs').createAppSetupImporter({origin,trustedSender:settingsEvent,
    chooseFile:async({platform,defaultPath})=>{
      const choice=await dialog.showOpenDialog(settings,{title:'Load '+(platform==='youtube'?'Google Desktop':'Kick private app')+' setup',defaultPath,properties:['openFile'],filters:[{name:'App setup JSON',extensions:['json']}]});
      return choice.canceled?null:choice.filePaths[0]||null;
    }});
  ipcMain.handle('producer:accounts:import-app',async(event,platform)=>{
    try{return await changeDestination(event,()=>importAppSetup(event,platform));}
    catch(error){return {ok:false,reason:['destination_change_pending','destination_broadcast_busy'].includes(error?.message)?error.message:'local_operator_required'};}
  });
  ipcMain.handle('producer:info',event=>{if(!policy.trustedMain(event,studio.webContents,origin))throw Error('Untrusted request');return {name:'Producer, Please',version:app.getVersion(),desktop:true,engine:'standalone',preview};});
  ipcMain.handle('producer:settings',event=>{if(!policy.trustedMain(event,studio.webContents,origin))throw Error('Untrusted request');return openSettings();});
  ipcMain.handle('producer:sources:open',openSources);
  ipcMain.handle('producer:output:view',viewOutput);
  ipcMain.handle('producer:destinations:status',event=>{if(!settingsEvent(event))throw Error('Untrusted request');return Promise.all([destinations.public(),outputProfiles.public()]).then(([value,profiles])=>({...value,outputProfiles:profiles,broadcast:publicBroadcast()}));});
  ipcMain.handle('producer:destinations:save',(event,value)=>changeDestination(event,()=>destinations.save(value)));
  ipcMain.handle('producer:destinations:remove',(event,id)=>changeDestination(event,()=>destinations.remove(id)));
  ipcMain.handle('producer:profiles:list',event=>{if(!settingsEvent(event))throw Error('Untrusted request');return outputProfiles.public();});
  ipcMain.handle('producer:stream-info:list',streamInfoActions.list);
  ipcMain.handle('producer:stream-info:save',streamInfoActions.save);
  ipcMain.handle('producer:profiles:save',(event,value)=>changeDestination(event,()=>profileActions.save(value)));
  ipcMain.handle('producer:profiles:remove',(event,id)=>changeDestination(event,()=>profileActions.remove(id)));
  ipcMain.handle('producer:profiles:select',(event,id)=>changeDestination(event,()=>profileActions.select(id)));
  ipcMain.handle('producer:broadcast:audio',async(event,value)=>{
    if(!settingsEvent(event))throw Error('Untrusted request');
    const requestId=typeof value?.requestId==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(value.requestId)?value.requestId:null;
    try{await broadcast.setLiveAudio(value);return {...publicBroadcast(),audioMixResult:{ok:true,requestId}};}
    catch(error){const codes=new Set(['invalid_audio_session','invalid_audio_request','invalid_audio_routing','audio_output_changed','audio_revision_conflict','audio_request_conflict','audio_routing_conflict','audio_routing_busy','audio_routing_uncertain','audio_routing_timeout','audio_routing_cancelled','audio_routing_unavailable']);return {...publicBroadcast(),audioMixResult:{ok:false,requestId,code:codes.has(error?.code)?error.code:'audio_routing_unavailable'}};}
  });
  ipcMain.handle('producer:broadcast:stop-target',async(event,id)=>{if(!settingsEvent(event))throw Error('Untrusted request');await broadcast.stopTarget(id);return publicBroadcast();});
  ipcMain.handle('producer:broadcast:prepare',async(event,value)=>changeDestination(event,async()=>{await rehearsal.monitor({bus:'off'});await broadcast.prepare(value);return publicBroadcast();}));
  ipcMain.handle('producer:broadcast:start',async(event,value)=>{if(!settingsEvent(event))throw Error('Untrusted request');if(destinationMutation)throw Error('destination_change_pending');await broadcast.start(value);return publicBroadcast();});
  ipcMain.handle('producer:broadcast:stop',async event=>{if(!settingsEvent(event))throw Error('Untrusted request');if(rehearsal.active())await rehearsal.stop();else await broadcast.stop();return publicBroadcast();});
  ipcMain.handle('producer:broadcast:status',event=>{if(!policy.trustedMain(event,studio.webContents,origin)&&!settingsEvent(event))throw Error('Untrusted request');return publicBroadcast();});
  ipcMain.handle('producer:platform',(event,value)=>{if(!settingsEvent(event)||!policy.allowedExternal(value))throw Error('Untrusted address');return shell.openExternal(value);});
  Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'Producer, Please',submenu:[{label:'Broadcast setup…',accelerator:'CmdOrCtrl+,',click:openSettings},{type:'separator'},{label:'Quit',click:()=>app.quit()}]},{label:'View',submenu:[{role:'reload'},{role:'togglefullscreen'},{role:'resetzoom'},{role:'zoomin'},{role:'zoomout'}]},{role:'editMenu'},{label:'Help',submenu:[{label:'About Producer, Please',click:()=>dialog.showMessageBox(studio,{message:'Producer, Please',detail:'Standalone desktop production studio. Configuring a destination, sending media, and verified platform receipt are separate states. '+(runtime?.buildKind==='bundled-runtime'?'This build includes its own backend runtime.':'This local build uses the existing project runtime.')})}]}]));
  await loadInitialStudio(studio.webContents,origin+'/control?workspace=studio&desktop=1');
}).catch(async error=>{await dialog.showMessageBox({type:'error',message:'Producer, Please could not start',detail:typeof error.message==='string'?error.message:'The local runtime is unavailable.'});app.exit(1);});
const {createQuitCoordinator}=require('./quit.cjs');
quit=createQuitCoordinator({
  active:async()=>{
    const responses=await Promise.all(['/api/production/session','/api/production/obs'].map(url=>fetch(origin+url,{signal:AbortSignal.timeout(3000)})));
    const [value,encoder]=await Promise.all(responses.map(r=>r.json()));
    return rehearsal?.active()||broadcast?.active()||responses.some(r=>!r.ok)||value.session?.active!==false||value.session?.recording?.active!==false||encoder.obs?.streaming!==false||encoder.obs?.recording!==false;
  },
  confirm:async()=>{const options={type:'warning',message:'Close the desktop studio?',detail:'A production may still be active. Closing this window can disconnect your local microphone or guest controls. Background production will stay running when its safety cannot be confirmed.',buttons:['Keep studio open','Close window'],defaultId:0,cancelId:0};const answer=studio&&!studio.isDestroyed()?await dialog.showMessageBox(studio,options):await dialog.showMessageBox(options);return answer.response===1;},
  release:async()=>{
    let rehearsalClosed=false;try{rehearsalClosed=await rehearsal?.close()!==false;}catch(_){}
    if(!rehearsalClosed){await dialog.showMessageBox(studio,{type:'warning',message:'Local rehearsal shutdown is not confirmed',detail:'The studio will stay open. Try Stop local encoding again before quitting.'});return false;}
    if(await broadcast?.close()===false){await dialog.showMessageBox(studio,{type:'warning',message:'Broadcast shutdown is not confirmed',detail:'The studio will stay open. Try Stop broadcast again before quitting.'});return false;}clearInterval(polling);capturePicker?.close();for(const window of BrowserWindow.getAllWindows())window.destroy();
    let result;try{result=await backend.close();}catch(_){result={running:null,reason:'shutdown_unconfirmed'};}
    fs.writeFileSync(path.join(profile,'last-close.json'),JSON.stringify({backendRunning:result?.running??null,reason:result?.reason||null}));
  },
  exit:()=>app.quit(),
});
app.on('window-all-closed',()=>{if(!quit.draining)app.quit();});
app.on('before-quit',event=>{if(backend)quit.request(event);});
