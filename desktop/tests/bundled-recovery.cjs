/* Actual packaged output-loss recovery. Synthetic PNG, two owned local FLVs only. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

async function exerciseBundledRecovery(app,{origin,evidence,resources}={}){
  const local=new URL(origin);
  if(local.protocol!=='http:'||local.hostname!=='127.0.0.1'||!local.port||['8765','8767'].includes(local.port)||local.origin!==origin)throw Error('Owned isolated packaged backend required');
  if(typeof evidence!=='string'||typeof resources!=='string'||!path.isAbsolute(evidence)||!path.isAbsolute(resources))throw Error('Absolute evidence and packaged resources required');
  evidence=path.resolve(evidence);resources=path.resolve(resources);
  if(process.platform==='win32'&&path.parse(evidence).root.toLowerCase()!=='f:\\')throw Error('Recovery evidence must use F:');
  fs.mkdirSync(evidence,{recursive:true});
  const files=['recovery-first.flv','recovery-second.flv'];for(const name of files)if(fs.existsSync(path.join(evidence,name)))throw Error('Recovery evidence must not replace an existing recording');
  const result={complete:false,syntheticOnly:true,physicalCapture:false,externalBroadcast:false,platformLiveVerified:false};
  const api=async(route,body,headers)=>{
    if(!route.startsWith('/api/')||route.includes('://'))throw Error('Local API route required');
    const response=await fetch(origin+route,body===undefined?{}:{method:'POST',headers:headers||{'Content-Type':'application/json'},body:Buffer.isBuffer(body)?body:JSON.stringify(body)}),value=await response.json();
    assert.ok(response.ok&&value.ok!==false,route+': '+(value.reason||response.status));return value;
  };
  async function until(check,label,timeout=25000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await pause(100);}throw Error('Timed out: '+label);}
  const snapshot=()=>app.evaluate(()=>bundledRecoveryRehearsal.snapshot());
  try{
    const initial=await api('/api/desktop/status'),session=(await api('/api/production/session')).session;
    assert.equal(initial.native_encoding.active,false);assert.equal(session.active,false);assert.equal(session.recording.active,false);
    result.runtime=await app.evaluate(async({app,BrowserWindow,ipcMain},config)=>{
      const path=process.getBuiltinModule('node:path'),require=process.getBuiltinModule('node:module').createRequire(path.join(process.resourcesPath,'app.asar','package.json'));
      const fs=require('node:fs'),{spawn}=require('node:child_process');
      if(globalThis.bundledRecoveryRehearsal)throw Error('Recovery rehearsal already exists');
      const resources=fs.realpathSync(config.resources),evidence=fs.realpathSync(config.evidence),difference=path.relative(resources,evidence);
      if(resources!==fs.realpathSync(process.resourcesPath))throw Error('Actual packaged resources required');
      if(!difference||!difference.startsWith('..'+path.sep)&&!path.isAbsolute(difference))throw Error('Evidence cannot be written into packaged resources');
      const archive=path.join(resources,'app.asar'),{resolveRuntime}=require(path.join(archive,'runtime.cjs'));
      const manifest=JSON.parse(fs.readFileSync(path.join(resources,'runtime.json'),'utf8'));if(manifest.buildKind!=='bundled-runtime')throw Error('Bundled runtime required');
      const runtime=resolveRuntime(manifest,resources,app.getPath('userData'),{port:Number(new URL(config.origin).port)});
      const {NativeBroadcast}=require(path.join(archive,'broadcast.cjs')),{Encoder}=require(path.join(archive,'encoder.cjs')),{createOutputCapture}=require(path.join(archive,'output-capture.cjs'));
      const request=async(route,body)=>{
        if(!route.startsWith('/api/')||route.includes('://'))throw Error('Non-local request forbidden');
        const response=await fetch(config.origin+route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),value=await response.json();
        const preflight=body===undefined&&route.startsWith('/api/production/native-preflight?')&&typeof value.preflight?.ready==='boolean';
        if(!response.ok||value.ok===false&&!preflight)throw Error(value.reason||'packaged_backend_request_failed');return value;
      };
      const status=await request('/api/desktop/status');
      if(status.pid!==config.identity.pid||status.server_session_id!==config.identity.server_session_id||status.native_encoding.active)throw Error('Owned backend identity changed');
      const identity={pid:status.pid,server_session_id:status.server_session_id},workers=[],encoders=[],captures=[],errors=[],events=[];
      let confirmations=0,generator=null;
      const broker=new NativeBroadcast({request,identity,ownerPid:process.pid,confirm:async()=>{confirmations++;return true;},onState:state=>events.push(state),
        destinations:{getPrivateDestination:async id=>{if(id!=='recovery-local-file-only')throw Error('Synthetic destination required');return {name:'LOCAL RECOVERY REHEARSAL',serverUrl:'rtmps://never-contact.invalid/live',streamKey:'synthetic-recovery-never-transmitted'};}},
        createCapture:dimensions=>{
          const capture=createOutputCapture({BrowserWindow,ipcMain,origin:config.origin,baseDir:archive,...dimensions,partition:'persist:packaged-recovery-rehearsal',
            onError:code=>{errors.push(code);if(broker.active())broker.stop(code).catch(()=>{});}});captures.push(capture);return capture;
        },
        createEncoder:onState=>{
          const number=encoders.length;if(number>1)throw Error('No automatic third encoder is permitted');
          const encoder=new Encoder({python:runtime.python,workerPath:runtime.encoderWorker,pythonPackages:runtime.pythonPackages,artifactRoot:evidence,onState,
            spawnProcess:(...args)=>{const child=spawn(...args);workers.push(child);return child;}});encoders.push(encoder);
          return {status:()=>encoder.status(),sendVideo:(...args)=>encoder.sendVideo(...args),sendAudio:(...args)=>encoder.sendAudio(...args),stop:()=>encoder.stop(),
            start:({destination,width,height,fps,bitrate})=>{
              if(destination?.streamKey!=='synthetic-recovery-never-transmitted')throw Error('Synthetic profile required');
              // Deliberately drop the complete destination and every transport
              // option. The real worker receives only an owned local-file target.
              return encoder.start({width,height,fps,bitrate,codec:'libx264',testOutput:path.join(evidence,number===0?'recovery-first.flv':'recovery-second.flv')});
            }};
        }});
      globalThis.bundledRecoveryRehearsal={broker,errors,events,
        snapshot(){return {broker:broker.status(),capture:broker.capture?.status(),windowId:broker.capture?.window?.isDestroyed()===false?broker.capture.window.id:null,
          confirmations,captures:captures.length,encoders:encoders.map(encoder=>encoder.status()),workers:workers.map(child=>({pid:child.pid,exited:child.exitCode!==null||child.signalCode!==null,exitCode:child.exitCode,signalCode:child.signalCode})),errors:[...errors]};},
        async generate(){
          generator=new BrowserWindow({show:false,width:640,height:360,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});generator.webContents.setAudioMuted(true);
          try{await generator.loadURL('data:text/html,<canvas width="640" height="360"></canvas>');
            const png=await generator.webContents.executeJavaScript(`(()=>{const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d');ctx.fillStyle='#1647a0';ctx.fillRect(0,0,640,360);ctx.fillStyle='white';ctx.font='bold 26px sans-serif';ctx.fillText('PACKAGED OUTPUT RECOVERY',24,140);ctx.font='19px sans-serif';ctx.fillText('Generated picture · local files only',24,180);return canvas.toDataURL('image/png').split(',')[1];})()`);
            fs.writeFileSync(path.join(evidence,'recovery-generated.png'),Buffer.from(png,'base64'));
          }finally{generator.destroy();generator=null;}
        },
        restoreExistingOutput(){
          const capture=broker.capture,window=capture.window,before=capture.status(),id=window.id,url=window.webContents.getURL();
          window.minimize();if(!window.isMinimized())throw Error('Output was not minimized');capture.show();
          return {sameWindow:capture.window===window&&window.id===id,sameDocument:url===window.webContents.getURL()&&before.peerId===capture.status().peerId,
            minimized:window.isMinimized(),reviewOpen:capture.status().browserReviewOpen,capturing:capture.status().capturing};
        },
        destroyOwnOutput(){if(broker.status().phase!=='sending')throw Error('Output loss requires active local encoding');broker.capture.window.destroy();},
        async close(){
          generator?.destroy();generator=null;
          let closed=await broker.close();
          for(const encoder of encoders)if(encoder.status().running)await encoder.stop();
          if(!closed)closed=await broker.close();
          if(closed)for(const capture of captures)capture.close();
          return {closed,workers:workers.map(child=>({pid:child.pid,exited:child.exitCode!==null||child.signalCode!==null})),running:encoders.some(encoder=>encoder.status().running),ownershipPending:broker.status().ownershipPending};
        },
      };
      return {archive,python:runtime.python,worker:runtime.encoderWorker,pythonPackages:runtime.pythonPackages,backendPid:identity.pid};
    },{origin,evidence,resources,identity:{pid:initial.pid,server_session_id:initial.server_session_id}});
    await app.evaluate(()=>bundledRecoveryRehearsal.generate());
    const asset=(await api('/api/creator/assets',fs.readFileSync(path.join(evidence,'recovery-generated.png')),{'Content-Type':'image/png','X-RareIQ-Filename':'recovery-generated.png'})).asset,source='image:'+asset.id;
    await api('/api/production/switcher/preview',{preview_sources:[source]});await app.evaluate(()=>bundledRecoveryRehearsal.broker.prepare({format:'hd'}));
    const allReady=async()=>{const state=await api('/api/production/switcher'),output=state.guest_output,own=(await snapshot()).capture;return own?.readySources.includes(source)&&output.connected>0&&output.ready_groups.length>=output.connected&&output.ready_groups.every(group=>group.includes(source));};
    await until(allReady,'all actual output groups decoded image');
    await api('/api/production/switcher/take',{transition:'cut',duration_ms:0,request_id:'packaged_recovery_take_'+Date.now(),expires_at:Date.now()/1000+30});
    await until(async()=>{const state=await api('/api/production/switcher');if(state.guest_output.rendered_generation!==state.generation)return false;return app.evaluate(async()=>{await bundledRecoveryRehearsal.broker.check();return bundledRecoveryRehearsal.broker.status().ready;});},'actual Program receipt and exact receiver preflight');
    result.firstPreflight=await app.evaluate(()=>bundledRecoveryRehearsal.broker.preflight);
    const first=await snapshot();assert.equal(result.firstPreflight.output.peer_id,first.capture.peerId);assert.equal(first.confirmations,0);
    await app.evaluate(()=>bundledRecoveryRehearsal.broker.start({destinationId:'recovery-local-file-only',format:'hd'}));
    await until(async()=>{const state=await snapshot();return state.broker.phase==='sending'&&state.broker.frames>=30;},'first real encoder frames');
    result.beforeLoss=await snapshot();assert.equal(result.beforeLoss.confirmations,1);assert.equal((await api('/api/desktop/status')).native_encoding.active,true);
    result.viewOutput=await app.evaluate(()=>bundledRecoveryRehearsal.restoreExistingOutput());assert.deepEqual(result.viewOutput,{sameWindow:true,sameDocument:true,minimized:false,reviewOpen:false,capturing:true});
    const firstPage=app.windows().find(page=>page.url().startsWith(origin+'/output/studio'));await firstPage.screenshot({path:path.join(evidence,'recovery-first-output.png')});
    await app.evaluate(()=>bundledRecoveryRehearsal.destroyOwnOutput());
    await until(async()=>{const state=await snapshot();return !state.broker.active&&!state.broker.ownershipPending&&state.workers.every(worker=>worker.exited)&&!(await api('/api/desktop/status')).native_encoding.active;},'output-loss shutdown and lease release');
    result.afterLoss=await snapshot();assert.equal(result.afterLoss.broker.phase,'failed');assert.equal(result.afterLoss.broker.reason,'output_closed');assert.ok(result.afterLoss.broker.frames>=result.beforeLoss.broker.frames&&result.afterLoss.broker.frames>0);assert.deepEqual(result.afterLoss.errors,['output_closed']);
    await pause(350);const stillStopped=await snapshot();assert.equal(stillStopped.confirmations,1);assert.equal(stillStopped.encoders.length,1);assert.equal(stillStopped.captures,1);assert.equal(stillStopped.broker.active,false);assert.equal((await api('/api/desktop/status')).native_encoding.active,false);result.noAutomaticRestart=true;
    await app.evaluate(()=>bundledRecoveryRehearsal.broker.prepare({format:'hd'}));
    await until(async()=>{if(!await allReady())return false;return app.evaluate(async()=>{await bundledRecoveryRehearsal.broker.check();return bundledRecoveryRehearsal.broker.status().ready;});},'new receiver prepared after output loss');
    result.secondPreflight=await app.evaluate(()=>bundledRecoveryRehearsal.broker.preflight);const prepared=await snapshot();
    assert.notEqual(prepared.windowId,first.windowId);assert.notEqual(prepared.capture.peerId,first.capture.peerId);assert.equal(result.secondPreflight.output.peer_id,prepared.capture.peerId);assert.equal(prepared.confirmations,1);assert.equal(prepared.encoders.length,1);
    await app.evaluate(()=>bundledRecoveryRehearsal.broker.start({destinationId:'recovery-local-file-only',format:'hd'}));
    await until(async()=>{const state=await snapshot();return state.broker.phase==='sending'&&state.broker.frames>=30;},'explicit second start produces frames');
    await pause(350);result.secondSending=await snapshot();assert.equal(result.secondSending.confirmations,2);assert.equal(result.secondSending.encoders.length,2);assert.equal((await api('/api/desktop/status')).native_encoding.active,true);
    await app.evaluate(()=>bundledRecoveryRehearsal.broker.stop());
    result.afterStop=await snapshot();assert.equal(result.afterStop.broker.active,false);assert.equal(result.afterStop.broker.ownershipPending,false);assert.equal(result.afterStop.broker.reason,null);assert.ok(result.afterStop.broker.frames>0);assert.ok(result.afterStop.workers.every(worker=>worker.exited));assert.equal((await api('/api/desktop/status')).native_encoding.active,false);
    const secondPage=app.windows().find(page=>page.url().startsWith(origin+'/output/studio'));await secondPage.screenshot({path:path.join(evidence,'recovery-second-output.png')});
    result.files=[];
    for(const name of files){const metadata=JSON.parse(execFileSync('ffprobe',['-v','error','-count_frames','-show_streams','-show_format','-of','json',path.join(evidence,name)],{encoding:'utf8',windowsHide:true}));fs.writeFileSync(path.join(evidence,name+'.ffprobe.json'),JSON.stringify(metadata,null,2));
      const video=metadata.streams.find(stream=>stream.codec_type==='video'),audio=metadata.streams.find(stream=>stream.codec_type==='audio');assert.equal(video.codec_name,'h264');assert.equal(video.width,1280);assert.equal(video.height,720);assert.equal(audio.codec_name,'aac');assert.equal(Number(audio.sample_rate),48000);assert.equal(audio.channels,2);assert.ok(Number(video.nb_read_frames)>=30);assert.ok(Number(metadata.format.duration)>=.8&&Number(metadata.format.duration)<10);
      result.files.push({name,duration:Number(metadata.format.duration),frames:Number(video.nb_read_frames),video:'h264',audio:'aac',sampleRate:48000});
    }
    Object.assign(result,{complete:true,actualBundledModules:true,actualBackendReceipts:true,exactPeerPreflight:true,newWindowAndPeer:true,explicitSecondConfirmation:true,retainedFailureMetrics:true,leaseReleasedAfterLoss:true,leaseReleasedAfterStop:true});
    return result;
  }catch(error){result.error=error.message;try{result.failureSnapshot=await snapshot();}catch(_){}throw error;}
  finally{
    try{result.cleanup=await app.evaluate(async()=>{const value=globalThis.bundledRecoveryRehearsal;if(!value)return {closed:true,workers:[],running:false,ownershipPending:false};const result=await value.close();if(result.closed&&!result.running&&result.workers.every(worker=>worker.exited))delete globalThis.bundledRecoveryRehearsal;return result;});
      result.cleanupConfirmed=result.cleanup.closed&&!result.cleanup.running&&!result.cleanup.ownershipPending&&result.cleanup.workers.every(worker=>worker.exited)&&(await api('/api/desktop/status')).native_encoding.active===false;
    }catch(_){result.cleanupConfirmed=false;}
    const cleanupFailure=result.complete&&!result.cleanupConfirmed;if(cleanupFailure){result.complete=false;result.error='packaged_recovery_cleanup_unconfirmed';}
    fs.writeFileSync(path.join(evidence,'recovery-results.json'),JSON.stringify(result,null,2));if(cleanupFailure)throw Error(result.error);
  }
}
module.exports={exerciseBundledRecovery};
