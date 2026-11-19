'use strict';
// Native capability proof: every submitted PCM sample is exactly zero.
const {app,BrowserWindow,ipcMain}=require('electron'),fs=require('node:fs'),path=require('node:path');
const {createLocalMonitor}=require('../local-monitor.cjs');
const evidence=process.env.PRODUCER_MONITOR_SILENT_EVIDENCE;
if(!evidence||!path.isAbsolute(evidence)||fs.existsSync(evidence))throw Error('Fresh isolated evidence required');
fs.mkdirSync(evidence,{recursive:true});app.setPath('userData',path.join(evidence,'profile'));app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
app.whenReady().then(async()=>{
  const result={passed:false,syntheticZeroPcmOnly:true,audibleInput:false,sourceDiscovery:false,hardwareListeningVerified:false};const monitor=createLocalMonitor({BrowserWindow,ipcMain,baseDir:path.resolve(__dirname,'..'),timeoutMs:3000});
  try{
    const pending=monitor.prepare();pending.catch(()=>{});await new Promise(resolve=>setTimeout(resolve,150));const target=BrowserWindow.getAllWindows()[0];if(target)result.renderer=await target.webContents.executeJavaScript('({protocol:location.protocol,secure:window.isSecureContext,hasAudioWorkletNode:typeof AudioWorkletNode==="function"})',false);
    await pending;result.ready=monitor.status().ready;result.zeroPacketConsumed=await monitor.write(Buffer.alloc(3840));if(!result.ready||!result.zeroPacketConsumed)throw Error('silent_monitor_unavailable');monitor.stop();result.stopped=monitor.status().running===false;result.passed=result.stopped;
  }catch(error){result.reason=error.code||'silent_monitor_failed';}
  finally{monitor.close();fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2),{flag:'wx'});console.log(JSON.stringify(result));app.exit(result.passed?0:1);}
});
