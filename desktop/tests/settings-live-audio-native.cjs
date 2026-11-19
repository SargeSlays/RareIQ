/* Packaged Settings/preload/trust proof; runtime sending state is explicitly synthetic.
   The original Main handler authorizes every fixture call. No capture or encoder starts. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{_electron}=require('playwright');
const evidence=process.argv[2],executable=process.argv[3],origin='http://127.0.0.1:8768';
if(!evidence||!path.isAbsolute(evidence)||!executable||!path.isAbsolute(executable))throw Error('Absolute evidence and packaged executable required.');
fs.mkdirSync(evidence,{recursive:true});const profile=path.join(evidence,'profile');if(fs.existsSync(profile))throw Error('A fresh owned QA profile is required.');
async function main(){
  const marker=await fetch(origin+'/__qa__/guest-fixture').then(response=>response.json());assert.equal(marker.isolated_guest_fixture,true);assert.equal(marker.hardware,false);
  const before=await fetch(origin+'/api/production/switcher').then(response=>response.json());let app,settings;
  const result={passed:false,syntheticSending:true,actualBroadcast:false,hardware:false,realCredentials:false};
  try{
    app=await _electron.launch({executablePath:executable,args:[],env:{...process.env,PRODUCER_DESKTOP_QA_ORIGIN:origin,PRODUCER_DESKTOP_QA_PROFILE:profile,ELECTRON_ENABLE_LOGGING:'0'}});app.context().setDefaultTimeout(15000);
    await app.evaluate(({app,BrowserWindow,shell})=>{
      globalThis.__liveUiGuards={external:0,mutations:0,externalWindows:0,forbiddenControls:0};shell.openExternal=async()=>{__liveUiGuards.externalWindows++;throw Error('External navigation forbidden');};
      const install=contents=>{contents.session.setPermissionCheckHandler(()=>false);contents.session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));contents.session.setDisplayMediaRequestHandler((_request,callback)=>callback(null));contents.session.webRequest.onBeforeRequest((details,callback)=>{const url=new URL(details.url),local=url.origin==='http://127.0.0.1:8768'||url.origin==='ws://127.0.0.1:8768',file=['file:','data:','blob:','devtools:'].includes(url.protocol);if(!file&&!local)__liveUiGuards.external++;if(!['GET','HEAD'].includes(details.method||'GET'))__liveUiGuards.mutations++;callback({cancel:!file&&(!local||!['GET','HEAD'].includes(details.method||'GET'))});});};app.on('web-contents-created',(_event,contents)=>install(contents));for(const window of BrowserWindow.getAllWindows())install(window.webContents);
    });
    const studio=await app.firstWindow();await studio.waitForURL(origin+'/control?workspace=studio&desktop=1');await studio.locator('#instantSplash').waitFor({state:'hidden'});
    assert.equal(path.resolve(await app.evaluate(({app})=>app.getPath('userData'))).toLowerCase(),path.resolve(profile).toLowerCase());
    const opened=app.waitForEvent('window');await studio.evaluate(()=>producerDesktop.openBroadcastSettings());settings=await opened;await settings.locator('#outputProfileSection').waitFor({state:'visible'});
    const baseline=await settings.evaluate(()=>producerSettings.status()),valid={outputId:'11111111-1111-1111-1111-111111111111',expectedRevision:0,requestId:'native-live-trust',audioRouting:{}};
    const unprepared=await settings.evaluate(value=>producerSettings.setLiveAudio(value),valid);assert.equal(unprepared.audioMixResult.ok,false);assert.equal(unprepared.audioMixResult.code,'audio_routing_unavailable');assert.equal(unprepared.broadcast?.active??unprepared.active,false);
    const openedUntrusted=app.waitForEvent('window');const untrustedId=await app.evaluate(async({BrowserWindow})=>{const path=process.getBuiltinModule('node:path'),window=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,preload:path.join(process.resourcesPath,'app.asar','settings-preload.cjs')}});await window.loadURL('data:text/html,<title>Untrusted live mixer</title>');return window.id;});const untrusted=await openedUntrusted;
    assert.equal(await untrusted.evaluate(async value=>{try{await producerSettings.setLiveAudio(value);return false;}catch(_){return true;}},valid),true,'original Main rejects untrusted renderer');
    await app.evaluate(({ipcMain},profile)=>{
      const channel='producer:broadcast:audio',originalAudio=ipcMain._invokeHandlers.get(channel),originalStatus=ipcMain._invokeHandlers.get('producer:broadcast:status'),originalDestinations=ipcMain._invokeHandlers.get('producer:destinations:status');
      const clone=value=>JSON.parse(JSON.stringify(value)),outputId='22222222-2222-2222-2222-222222222222';
      const qa=globalThis.__liveUiQa={calls:[],nextUncertain:false,nextHistory:false,state:{phase:'sending',active:true,prepared:true,ready:false,available:true,format:profile.format,profileId:profile.id,outputProfile:clone(profile),audioMix:{outputId,revision:0,routing:clone(profile.audioRouting),uncertain:false},audioSourcesAvailable:[{id:'guest:'+'a'.repeat(32)+':microphone',category:'voice',label:'Guest microphone'}],audioMeters:{fresh:true,live:{peak:.5,rms:.25,clipCount:0,clipped:false},vod:{peak:.25,rms:.125,clipCount:0,clipped:false}},targets:[]}};
      ipcMain.removeHandler(channel);ipcMain.handle(channel,async(event,value)=>{
        await originalAudio(event,value); // Retains the real sender/main-frame authorization.
        qa.calls.push(clone(value));const mix=qa.state.audioMix;
        if(value.outputId!==mix.outputId||value.expectedRevision!==mix.revision)return {...clone(qa.state),audioMixResult:{ok:false,requestId:value.requestId,code:'audio_revision_conflict'}};
        if(qa.nextUncertain){qa.nextUncertain=false;mix.uncertain=true;mix.pending={requestId:value.requestId,expectedRevision:value.expectedRevision,audioRouting:clone(value.audioRouting)};return {...clone(qa.state),audioMixResult:{ok:false,requestId:value.requestId,code:'audio_routing_timeout'}};}
        if(mix.pending&&JSON.stringify({...mix.pending,outputId:mix.outputId})!==JSON.stringify({requestId:value.requestId,expectedRevision:value.expectedRevision,audioRouting:value.audioRouting,outputId:value.outputId}))throw Error('Changed retry payload');
        qa.state.audioMix={outputId:mix.outputId,revision:mix.revision+1,routing:clone(value.audioRouting),uncertain:false,historyWarning:qa.nextHistory};qa.nextHistory=false;
        return {...clone(qa.state),audioMixResult:{ok:true,requestId:value.requestId}};
      });
      ipcMain.removeHandler('producer:broadcast:status');ipcMain.handle('producer:broadcast:status',async event=>{await originalStatus(event);return clone(qa.state);});
      ipcMain.removeHandler('producer:destinations:status');ipcMain.handle('producer:destinations:status',async event=>({...await originalDestinations(event),broadcast:clone(qa.state)}));
      for(const channel of ['producer:broadcast:prepare','producer:broadcast:start','producer:broadcast:stop','producer:broadcast:stop-target']){ipcMain.removeHandler(channel);ipcMain.handle(channel,()=>{__liveUiGuards.forbiddenControls++;throw Error('Capture or transmission forbidden in Settings proof');});}
    },baseline.outputProfiles.profiles[0]);
    await settings.reload();await settings.locator('#liveAudioMixer').waitFor({state:'visible'});assert.equal(await settings.locator('#profileCodec').isDisabled(),true);
    const live=settings.locator('[data-live-audio-source="voice:default"][data-live-audio-gain="live"]'),vod=settings.locator('[data-live-audio-source="voice:default"][data-live-audio-gain="vod"]');
    await live.fill('6.0206');await vod.fill('-6.0206');await settings.locator('#liveAudioStatus').filter({hasText:'Mix confirmed.'}).waitFor();
    let mix=await app.evaluate(()=>__liveUiQa.state.audioMix);assert.equal(mix.routing['voice:default'].liveGainDb,6.0206);assert.equal(mix.routing['voice:default'].vodGainDb,-6.0206);
    await settings.locator('[data-live-audio-source="soundboard:default"][data-live-audio-include="vod"]').check();await settings.waitForFunction(()=>document.querySelector('#liveAudioStatus').textContent.includes('Mix confirmed.'));
    await app.evaluate(()=>{__liveUiQa.nextUncertain=true;});await live.fill('-12');await settings.locator('#retryLiveAudio').waitFor({state:'visible'});assert.equal(await live.isDisabled(),true);const timedOut=await app.evaluate(()=>__liveUiQa.calls.at(-1));await settings.locator('#retryLiveAudio').click();await settings.locator('#liveAudioStatus').filter({hasText:'Mix confirmed.'}).waitFor();assert.deepEqual(await app.evaluate(()=>__liveUiQa.calls.at(-1)),timedOut);
    await app.evaluate(()=>{__liveUiQa.nextHistory=true;});await settings.locator('#restoreLiveAudio').click();await settings.locator('#liveAudioStatus').filter({hasText:'local activity history could not be written'}).waitFor();await settings.waitForTimeout(1100);assert.match(await settings.locator('#liveAudioStatus').textContent(),/history could not be written/);
    assert.deepEqual((await settings.evaluate(()=>producerSettings.status())).outputProfiles,baseline.outputProfiles);assert.deepEqual(await app.evaluate(()=>__liveUiQa.state.audioMix.routing),baseline.outputProfiles.profiles[0].audioRouting);
    assert.equal(await untrusted.evaluate(async value=>{try{await producerSettings.setLiveAudio(value);return false;}catch(_){return true;}},valid),true,'fixture preserves original Main authorization');await app.evaluate(({BrowserWindow},id)=>BrowserWindow.fromId(id)?.destroy(),untrustedId);
    for(const theme of ['ignite','daylight']){if(await settings.locator('html').getAttribute('data-operator-skin')!==theme)await settings.locator('#themeToggle').click();await settings.locator('#liveAudioMixer').screenshot({path:path.join(evidence,'native-live-'+theme+'.png'),animations:'disabled'});}
    const after=await fetch(origin+'/api/production/switcher').then(response=>response.json());assert.equal(after.generation,before.generation);assert.deepEqual(after.program_sources,before.program_sources);assert.deepEqual(after.preview_sources,before.preview_sources);
    const guards=await app.evaluate(()=>__liveUiGuards);assert.deepEqual(guards,{external:0,mutations:0,externalWindows:0,forbiddenControls:0});
    Object.assign(result,{passed:true,realUnpreparedHandler:true,realUntrustedHandlerBlocked:true,syntheticRuntimeCalls:await app.evaluate(()=>__liveUiQa.calls.length),exactRetry:true,savedProfileUnchanged:true,restoreConfirmed:true,historyWarning:true,programUnchanged:true,guards});
    fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(error){result.error=error.message;if(settings)await settings.screenshot({path:path.join(evidence,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));throw error;}finally{if(app)await app.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
