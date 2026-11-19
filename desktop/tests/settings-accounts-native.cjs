/* Original packaged account IPC + real isolated encrypted persistence.
   Synthetic provider HTTP, no helper resolution, devices, capture or broadcasts. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),{_electron}=require('playwright');
const evidence=process.argv[2],executable=process.argv[3],root=path.resolve(__dirname,'../..'),origin='http://127.0.0.1:8768';
if(!evidence||!path.isAbsolute(evidence)||fs.existsSync(evidence)||!executable||!path.isAbsolute(executable))throw Error('Fresh absolute evidence and packaged executable required.');
fs.mkdirSync(evidence,{recursive:true});const profile=path.join(evidence,'profile');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const safe=value=>{assert.doesNotMatch(JSON.stringify(value),/access_token|refresh_token|streamKey|encrypted|client_secret/);return value;};
async function main(){
  let server,app,settings;const result={passed:false,originalAccountHandlers:true,syntheticProvider:true,realCredentials:false,actualBroadcast:false,hardware:false};
  const marker=()=>fetch(origin+'/__qa__/desktop-accounts').then(response=>response.json());
  try{
    let occupied=false;try{await fetch(origin+'/__qa__/guest-fixture',{signal:AbortSignal.timeout(800)});occupied=true;}catch(_){}assert.equal(occupied,false,'Fixture port must be unused; never take over an existing server.');
    server=spawn(path.join(root,'.venv/Scripts/python.exe'),['-B',path.join(root,'tools/qa_desktop_accounts_fixture.py'),path.join(evidence,'server'), '8768'],{cwd:root,windowsHide:true,stdio:['ignore','ignore','ignore'],env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
    let available=false;for(let attempt=0;attempt<80;attempt++){if(server.exitCode!==null)throw Error('Owned fixture failed to start');try{const state=await marker();if(state.isolated_desktop_accounts===true){available=true;break;}}catch(_){}await delay(250);}assert.equal(available,true,'Owned fixture readiness');
    const before=await fetch(origin+'/api/production/switcher').then(response=>response.json());
    async function launch(){
      app=await _electron.launch({executablePath:executable,args:[],env:{...process.env,PRODUCER_DESKTOP_QA_ORIGIN:origin,PRODUCER_DESKTOP_QA_PROFILE:profile,ELECTRON_ENABLE_LOGGING:'0'}});app.context().setDefaultTimeout(15000);
      await app.evaluate(({app,BrowserWindow,shell,ipcMain})=>{
        globalThis.__accountNativeGuards={external:0,externalWindows:0,forbiddenControls:0};shell.openExternal=async()=>{__accountNativeGuards.externalWindows++;throw Error('External navigation forbidden');};
        const install=contents=>{contents.session.setPermissionCheckHandler(()=>false);contents.session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));contents.session.setDisplayMediaRequestHandler((_request,callback)=>callback(null));contents.session.webRequest.onBeforeRequest((details,callback)=>{const url=new URL(details.url),local=url.origin==='http://127.0.0.1:8768'||url.origin==='ws://127.0.0.1:8768',file=['file:','data:','blob:','devtools:'].includes(url.protocol);if(!file&&!local)__accountNativeGuards.external++;callback({cancel:!file&&!local});});};app.on('web-contents-created',(_event,contents)=>install(contents));for(const window of BrowserWindow.getAllWindows())install(window.webContents);
        for(const channel of ['producer:broadcast:prepare','producer:broadcast:start','producer:broadcast:stop','producer:broadcast:stop-target']){ipcMain.removeHandler(channel);ipcMain.handle(channel,()=>{__accountNativeGuards.forbiddenControls++;throw Error('Capture and broadcast forbidden in account proof');});}
      });
      const studio=await app.firstWindow();await studio.waitForURL(origin+'/control?workspace=studio&desktop=1');await studio.locator('#instantSplash').waitFor({state:'hidden'});assert.equal(path.resolve(await app.evaluate(({app})=>app.getPath('userData'))).toLowerCase(),path.resolve(profile).toLowerCase());
      const opened=app.waitForEvent('window');await studio.evaluate(()=>producerDesktop.openBroadcastSettings());settings=await opened;await settings.locator('#twitchBadge').filter({hasText:'Chat connected'}).waitFor();return studio;
    }
    async function close(){if(!app)return;const owned=app;app=null;await owned.evaluate(({app})=>app.exit(0)).catch(()=>{});await owned.close().catch(()=>{});}
    await launch();const invoke=value=>settings.evaluate(value=>producerSettings.twitchAccount(value),value);
    const initial=safe(await invoke({action:'status'}));assert.equal(initial.account.authorized,true);assert.equal(initial.account.streaming_authorized,false);
    if(await settings.evaluate(()=>typeof producerSettings.providerAccount==='function')){
      for(const platform of ['youtube','kick']){const value=safe(await settings.evaluate(platform=>producerSettings.providerAccount({platform,action:'status'}),platform));assert.equal(value.ok,true);assert.equal(value.account.platform,platform);await settings.locator('#'+platform+'Account').waitFor();}
      result.originalProviderStatus=true;
    }
    const pending=safe(await invoke({action:'begin'}));assert.equal(pending.ok,true,JSON.stringify(pending));assert.equal(pending.account.state,'pending');assert.equal(pending.account.verification_url,'https://www.twitch.tv/activate');
    assert.equal(safe(await invoke({action:'cancel'})).account.authorized,true);assert.equal(safe(await invoke({action:'check'})).account.streaming_authorized,false);
    const deniedLink=safe(await invoke({action:'link',requestId:'native-chat-only'}));assert.equal(deniedLink.ok,false);assert.equal(deniedLink.reason,'account_authorization_required');
    const openedUntrusted=app.waitForEvent('window');const untrustedId=await app.evaluate(async({BrowserWindow})=>{const path=process.getBuiltinModule('node:path'),window=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,preload:path.join(process.resourcesPath,'app.asar','settings-preload.cjs')}});await window.loadURL('data:text/html,<title>Untrusted account fixture</title>');return window.id;});const untrusted=await openedUntrusted;
    await delay(1200);const callsBefore=(await marker()).calls.length;
    for(const action of ['status','begin','link','disconnect']){const denied=safe(await untrusted.evaluate(value=>producerSettings.twitchAccount(value),{action,...(action==='link'?{requestId:'untrusted-link'}:{})}));assert.deepEqual(denied,{ok:false,reason:'local_operator_required'});}
    if(await untrusted.evaluate(()=>typeof producerSettings.providerAccount==='function'))for(const platform of ['youtube','kick'])for(const action of ['status','begin','authorize','disconnect'])assert.deepEqual(safe(await untrusted.evaluate(value=>producerSettings.providerAccount(value),{platform,action,...(action==='authorize'?{flowId:'a'.repeat(32)}:{})})),{ok:false,reason:'local_operator_required'});
    assert.equal((await marker()).calls.length,callsBefore,'Untrusted calls never reach account HTTP');await app.evaluate(({BrowserWindow},id)=>BrowserWindow.fromId(id)?.destroy(),untrustedId);
    await settings.locator('#destinationForm input[name=name]').fill('Preserved native manual draft');
    assert.equal((await fetch(origin+'/__qa__/desktop-accounts/authorize',{method:'POST'}).then(response=>response.json())).synthetic_authorization,true);
    await settings.locator('#twitchCheck').click();await settings.locator('#twitchLink').waitFor({state:'visible'});await settings.locator('#twitchLink').click();await settings.locator('#twitchStatus').filter({hasText:'destination saved'}).waitFor();
    const state=safe(await settings.evaluate(()=>producerSettings.status()));assert.equal(state.destinations.length,1);const destination=state.destinations[0];assert.equal(destination.linkedAccount,true);assert.equal(destination.configured,true);assert.equal(await settings.locator('[data-edit-destination-id]').isDisabled(),true);assert.equal(await settings.locator('#destinationForm input[name=name]').inputValue(),'Preserved native manual draft');
    const repeated=safe(await invoke({action:'link',requestId:'native-repeat-link'}));assert.equal(repeated.ok,true);assert.equal(repeated.destination.id,destination.id);assert.equal((await settings.evaluate(()=>producerSettings.status())).destinations.length,1);
    for(const theme of ['ignite','daylight']){await settings.evaluate(theme=>document.documentElement.dataset.operatorSkin=theme,theme);await settings.locator('#twitchAccount').screenshot({path:path.join(evidence,'native-account-'+theme+'.png'),animations:'disabled'});}
    const persisted=JSON.parse(fs.readFileSync(path.join(profile,'destinations.json'),'utf8'));assert.equal(persisted.profiles.length,1);assert.equal(typeof persisted.profiles[0].encrypted,'string');assert.doesNotMatch(JSON.stringify(persisted),/fixture_channel.*streamKey|synthetic-draft-key|access_token|refresh_token/);
    const guards=await app.evaluate(()=>__accountNativeGuards);assert.deepEqual(guards,{external:0,externalWindows:0,forbiddenControls:0});await close();
    // Reopening the entire native application must reload its saved encrypted reference.
    app=await _electron.launch({executablePath:executable,args:[],env:{...process.env,PRODUCER_DESKTOP_QA_ORIGIN:origin,PRODUCER_DESKTOP_QA_PROFILE:profile,ELECTRON_ENABLE_LOGGING:'0'}});app.context().setDefaultTimeout(15000);const studio=await app.firstWindow();await studio.waitForURL(origin+'/control?workspace=studio&desktop=1');const opened=app.waitForEvent('window');await studio.evaluate(()=>producerDesktop.openBroadcastSettings());settings=await opened;await settings.locator('#twitchBadge').filter({hasText:'Streaming access saved'}).waitFor();const reopened=safe(await settings.evaluate(()=>producerSettings.status()));assert.equal(reopened.destinations[0].id,destination.id);assert.equal(reopened.destinations[0].linkedAccount,true);
    const disconnected=safe(await settings.evaluate(()=>producerSettings.twitchAccount({action:'disconnect'})));assert.equal(disconnected.ok,true);assert.equal(disconnected.account.authorized,false);assert.equal((await settings.evaluate(()=>producerSettings.status())).destinations.length,1);
    const after=await fetch(origin+'/api/production/switcher').then(response=>response.json());assert.equal(after.generation,before.generation);assert.deepEqual(after.program_sources,before.program_sources);assert.deepEqual(after.preview_sources,before.preview_sources);
    Object.assign(result,{passed:true,trustedStatus:true,trustedBeginCancelCheck:true,chatOnlyLinkBlocked:true,untrustedBlocked:true,untrustedHttpCalls:0,linkedDestinationSaved:true,reopenedFromEncryptedDisk:true,duplicateLinkSameDestination:true,disconnect:true,noSecretsOverIPC:true,manualDraftPreserved:true,programUnchanged:true,guards});await close();
  }catch(error){result.error=error.message;if(settings)await settings.locator('#twitchAccount').screenshot({path:path.join(evidence,'failure-card.png')}).catch(()=>{});throw error;}finally{
    if(app){await app.evaluate(({app})=>app.exit(0)).catch(()=>{});await app.close().catch(()=>{});}if(server&&server.exitCode===null){server.kill();await Promise.race([new Promise(resolve=>server.once('close',resolve)),delay(5000)]);}result.fixtureStopped=!server||server.exitCode!==null||server.signalCode!==null;fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
