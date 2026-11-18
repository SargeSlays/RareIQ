/* Bundled app evaluation: fresh profile, isolated local port, no capture/transmission. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {_electron}=require('playwright');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function main(){
  const evidence=path.resolve(process.argv[2]||''),executable=process.argv[3];if(!process.argv[2]||!executable||!path.isAbsolute(executable))throw Error('Absolute evidence and executable required');
  fs.mkdirSync(evidence,{recursive:false});const profile=path.join(evidence,'profile'),port=8770,origin='http://127.0.0.1:'+port;
  const result={complete:false,physicalCapture:false,externalBroadcast:false,existingStudioTouched:false};let app,identity;
  const env={};for(const key of ['SystemRoot','WINDIR','COMSPEC','USERPROFILE','LOCALAPPDATA','APPDATA','USERNAME','USERDOMAIN','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE'])if(process.env[key])env[key]=process.env[key];
  Object.assign(env,{PATH:process.env.SystemRoot+'\\System32;'+process.env.SystemRoot,TEMP:evidence,TMP:evidence,PYTHONPATH:path.join(evidence,'not-a-python-install'),PYTHONHOME:path.join(evidence,'not-a-python-install'),PRODUCER_DESKTOP_QA_PROFILE:profile,PRODUCER_DESKTOP_QA_PORT:String(port)});
  const api=async route=>{const response=await fetch(origin+route);assert.equal(response.ok,true);return response.json();};
  try{
    app=await _electron.launch({executablePath:executable,env,args:['--preview']});
    result.guardInstalledBeforeWindow=await app.evaluate(({app,BrowserWindow})=>{
      const install=contents=>{contents.session.webRequest.onBeforeRequest((details,reply)=>{
        const url=new URL(details.url),local=url.origin==='http://127.0.0.1:8770'||url.origin==='ws://127.0.0.1:8770';
        const safe=!url.pathname.startsWith('/api/camera')&&!url.pathname.startsWith('/api/boot')&&!url.pathname.startsWith('/api/system/start')&&!url.pathname.startsWith('/api/recording');
        reply({cancel:!['file:','data:','blob:','devtools:'].includes(url.protocol)&&(!local||!safe)});
      });};app.on('web-contents-created',(_event,contents)=>install(contents));for(const window of BrowserWindow.getAllWindows())install(window.webContents);return BrowserWindow.getAllWindows().length===0;
    });
    const studio=await app.firstWindow();await studio.waitForURL(origin+'/control?workspace=studio&desktop=1',{timeout:90000});await studio.locator('#instantSplash').waitFor({state:'hidden'});await studio.locator('.native-broadcast-readiness').waitFor();
    await studio.locator('.native-preview-notice').waitFor();assert.equal((await studio.evaluate(()=>producerDesktop.info())).preview,true);
    identity=await api('/api/desktop/status');assert.equal(identity.native_encoding.active,false);assert.equal((await api('/api/production/session')).session.active,false);
    const opened=app.waitForEvent('window');await studio.locator('[data-studio-open=broadcast][data-studio-view=setup]').click();const settings=await opened;await settings.locator('#status').filter({hasText:'Stream keys stay protected'}).waitFor();
    const status=await settings.evaluate(()=>producerSettings.status());assert.equal(status.broadcast.available,true);assert.equal(status.destinations.length,0);assert.equal(await settings.locator('#prepareOutput').isEnabled(),true);assert.equal(await settings.locator('#destinationStep').innerText(),'Not saved');
    const before=await api('/api/production/switcher');await settings.locator('#chooseSources').click();await studio.locator('[data-image-import]').waitFor({state:'visible'});const after=await api('/api/production/switcher');assert.equal(after.generation,before.generation);assert.deepEqual(after.preview_sources,before.preview_sources);
    await studio.screenshot({path:path.join(evidence,'bundled-studio.png')});await studio.locator('[data-studio-open=broadcast][data-studio-view=setup]').click();await settings.screenshot({path:path.join(evidence,'bundled-setup.png')});
    const prefs=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().map(w=>w.webContents.getLastWebPreferences()));assert.ok(prefs.every(p=>p.sandbox&&p.contextIsolation&&!p.nodeIntegration));
    Object.assign(result,{complete:true,bundledBackendStarted:true,managedRuntimeAvailable:true,sourceNavigation:true,navigationDoesNotTake:true,developmentPythonNotOnPath:true,protectedStorageAvailable:status.secureStorageAvailable});
    if(process.argv.includes('--program')){result.complete=false;result.program=await require('./bundled-program.cjs').exerciseBundledProgram(app,{origin,evidence:path.join(evidence,'program'),resources:path.join(path.dirname(executable),'resources')});result.complete=true;}
  }finally{
    if(app)await app.close().catch(()=>{});await pause(500);
    try{const status=await api('/api/desktop/status'),session=await api('/api/production/session');
      if(identity&&status.pid===identity.pid&&status.server_session_id===identity.server_session_id&&status.clients===0&&status.native_encoding.active===false&&session.session.active===false&&session.session.recording.active===false){
        // The exact new QA server may remain because OBS cannot be confirmed idle.
        // Verify its executable before terminating this owned, isolated test only.
        const expected=path.join(path.dirname(executable),'resources/python/python.exe');
        const command='(Get-CimInstance Win32_Process -Filter "ProcessId = '+Number(status.pid)+'").ExecutablePath';
        const actual=execFileSync('powershell.exe',['-NoProfile','-Command',command],{encoding:'utf8',windowsHide:true}).trim();
        if(path.resolve(actual).toLowerCase()===path.resolve(expected).toLowerCase()){process.kill(status.pid);result.ownedTestBackendStopped=true;}
      }
    }catch(_){}
    fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
