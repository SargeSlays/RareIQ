/* Packaged production pipeline rehearsal: generated media -> owned local FLV only. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

async function exerciseBundledProgram(app,{origin,evidence,resources}={}){
  const local=new URL(origin);
  if(local.protocol!=='http:'||local.hostname!=='127.0.0.1'||!local.port||local.port==='8765'||local.origin!==origin)throw Error('Owned isolated packaged backend origin required');
  if(typeof evidence!=='string'||typeof resources!=='string'||!path.isAbsolute(evidence)||!path.isAbsolute(resources))throw Error('Absolute F: evidence and packaged resources required');
  evidence=path.resolve(evidence);resources=path.resolve(resources);
  if(process.platform==='win32'&&path.parse(evidence).root.toLowerCase()!=='f:\\')throw Error('Program evidence must use F:');
  fs.mkdirSync(evidence,{recursive:true});
  const filename=path.join(evidence,'program-local-only.flv');if(fs.existsSync(filename))throw Error('Program evidence must not replace an existing recording');
  const result={complete:false,syntheticOnly:true,physicalCapture:false,externalBroadcast:false,platformLiveVerified:false,productModulesFromPackage:true};
  const api=async(route,body,headers)=>{
    if(!route.startsWith('/api/')||route.includes('://'))throw Error('Local API route required');
    const response=await fetch(origin+route,body===undefined?{}:{method:'POST',headers:headers||{'Content-Type':'application/json'},body:Buffer.isBuffer(body)?body:JSON.stringify(body)});
    const value=await response.json();assert.ok(response.ok&&value.ok!==false,route+': '+(value.reason||response.status));return value;
  };
  async function until(check,label,timeout=25000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await pause(100);}throw Error('Timed out: '+label);}
  try{
    const initial=await api('/api/desktop/status');assert.equal(initial.native_encoding.active,false);
    const session=(await api('/api/production/session')).session;assert.equal(session.active,false);assert.equal(session.recording.active,false);
    result.runtime=await app.evaluate(async({app,BrowserWindow,ipcMain},config)=>{
      const path=process.getBuiltinModule('node:path'),require=process.getBuiltinModule('node:module').createRequire(path.join(process.resourcesPath,'app.asar','package.json')),fs=require('node:fs');
      if(globalThis.bundledProgramRehearsal)throw Error('Packaged rehearsal already exists');
      const resources=fs.realpathSync(config.resources);
      if(resources!==fs.realpathSync(process.resourcesPath))throw Error('Actual packaged resources required');
      const evidence=fs.realpathSync(config.evidence),relative=path.relative(resources,evidence);
      if(!relative||!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative))throw Error('Evidence cannot be written into packaged resources');
      const archive=path.join(resources,'app.asar'),{resolveRuntime}=require(path.join(archive,'runtime.cjs'));
      const manifest=JSON.parse(fs.readFileSync(path.join(resources,'runtime.json'),'utf8'));
      if(manifest.buildKind!=='bundled-runtime')throw Error('Bundled runtime manifest required');
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
      const identity={pid:status.pid,server_session_id:status.server_session_id},events=[],errors=[];
      let capture,encoder,generator;
      const broadcast=new NativeBroadcast({request,identity,ownerPid:process.pid,confirm:async()=>true,
        destinations:{getPrivateDestination:async id=>{if(id!=='packaged-local-file-only')throw Error('Synthetic destination required');return {name:'PACKAGED LOCAL FILE ONLY',serverUrl:'rtmps://never-contact.invalid/live',streamKey:'synthetic-never-transmitted'};}},
        createCapture:dimensions=>(capture=createOutputCapture({BrowserWindow,ipcMain,origin:config.origin,baseDir:archive,...dimensions,partition:'persist:packaged-local-program-rehearsal',onError:code=>{errors.push(code);if(broadcast.active())broadcast.stop(code).catch(()=>{});}})),
        createEncoder:onState=>{
          encoder=new Encoder({python:runtime.python,workerPath:runtime.encoderWorker,pythonPackages:runtime.pythonPackages,artifactRoot:evidence,onState:state=>{events.push(state);onState(state);}});
          return {status:()=>encoder.status(),sendVideo:(...args)=>encoder.sendVideo(...args),sendAudio:(...args)=>encoder.sendAudio(...args),stop:()=>encoder.stop(),
            start:({destination,...settings})=>{
              if(destination?.streamKey!=='synthetic-never-transmitted')throw Error('Synthetic profile required');
              // Crucial boundary: no destination, stream key or network transport
              // is passed to the real bundled encoder worker. Only this F: file.
              return encoder.start({...settings,codec:'libx264',testOutput:path.join(evidence,'program-local-only.flv')});
            }};
        }});
      globalThis.bundledProgramRehearsal={broadcast,identity,events,errors,get capture(){return capture;},get encoder(){return encoder;},
        snapshot(){return {broadcast:broadcast.status(),capture:capture?.status(),encoder:encoder?.status(),errors:[...errors]};},
        async generate(){
          generator=new BrowserWindow({show:false,width:640,height:360,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,autoplayPolicy:'no-user-gesture-required',backgroundThrottling:false}});
          generator.webContents.setAudioMuted(true);
          try{
            await generator.loadURL('data:text/html,<canvas width="640" height="360"></canvas>');
            const generated=await generator.webContents.executeJavaScript(`(async()=>{
              const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d'),audio=new AudioContext({sampleRate:48000,sinkId:{type:'none'}});await audio.resume();
              const sink=audio.createMediaStreamDestination(),tone=audio.createOscillator(),gain=audio.createGain();tone.frequency.value=440;gain.gain.value=.15;tone.connect(gain).connect(sink);tone.start();
              const stream=canvas.captureStream(30);for(const track of sink.stream.getAudioTracks())stream.addTrack(track);
              const chunks=[],recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus',videoBitsPerSecond:1800000});recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
              let frame=0;const paint=()=>{ctx.fillStyle='#137049';ctx.fillRect(0,0,640,360);ctx.fillStyle='#e146a5';ctx.fillRect((frame++*7)%540,170,100,90);ctx.fillStyle='white';ctx.font='bold 27px sans-serif';ctx.fillText('PACKAGED GENERATED SOURCE',20,65);ctx.font='18px sans-serif';ctx.fillText('Local file only · 440 Hz · '+frame,30,100);};paint();
              const timer=setInterval(paint,33);recorder.start(250);await new Promise(resolve=>setTimeout(resolve,8000));
              await new Promise(resolve=>{recorder.onstop=resolve;recorder.stop();});clearInterval(timer);tone.stop();stream.getTracks().forEach(track=>track.stop());await audio.close();
              ctx.fillStyle='#1647a0';ctx.fillRect(0,0,640,360);ctx.fillStyle='white';ctx.font='bold 28px sans-serif';ctx.fillText('PACKAGED SECOND SOURCE',25,150);
              return {webm:Array.from(new Uint8Array(await new Blob(chunks,{type:'video/webm'}).arrayBuffer())),png:canvas.toDataURL('image/png').split(',')[1]};
            })()`,true);
            fs.writeFileSync(path.join(evidence,'program-generated-source.webm'),Buffer.from(generated.webm));fs.writeFileSync(path.join(evidence,'program-generated-image.png'),Buffer.from(generated.png,'base64'));
          }finally{generator.destroy();generator=null;}
        },
        async close(){generator?.destroy();generator=null;return broadcast.close();},
      };
      return {buildKind:runtime.buildKind,python:runtime.python,worker:runtime.encoderWorker,pythonPackages:runtime.pythonPackages,ffmpeg:runtime.ffmpeg,archive,backendPid:identity.pid};
    },{origin,evidence,resources,identity:{pid:initial.pid,server_session_id:initial.server_session_id}});
    await app.evaluate(()=>bundledProgramRehearsal.generate());
    const asset=async(file,type)=>(await api('/api/creator/assets',fs.readFileSync(path.join(evidence,file)),{'Content-Type':type,'X-RareIQ-Filename':file})).asset;
    const video=await asset('program-generated-source.webm','video/webm'),image=await asset('program-generated-image.png','image/png');
    const title=(await api('/api/production/sources/text',{name:'Packaged rehearsal title',text:'PACKAGED PROGRAM · LOCAL FILE ONLY',position:'lower-third',request_id:'packaged_rehearsal_title_'+Date.now()})).source;
    const videoSource='video:'+video.id,imageSource='image:'+image.id,titleSource=title.id;assert.match(titleSource,/^text:[a-f0-9-]{36}$/);
    await api('/api/production/switcher/preview',{preview_sources:[videoSource]});await app.evaluate(()=>bundledProgramRehearsal.broadcast.prepare({format:'hd'}));
    await until(()=>app.evaluate((_electron,source)=>bundledProgramRehearsal.capture.status().readySources.includes(source),videoSource),'owned output decodes imported video');
    await until(async()=>{const state=await api('/api/production/switcher');return state.guest_output.ready_groups.length>0&&state.guest_output.ready_groups.every(group=>group.includes(videoSource));},'backend acknowledges video readiness in every output');
    let sequence=0;const take=()=>api('/api/production/switcher/take',{transition:'cut',duration_ms:0,request_id:'packaged_program_take_'+Date.now()+'_'+(++sequence),expires_at:Date.now()/1000+30});
    await take();await until(()=>app.evaluate(async()=>{await bundledProgramRehearsal.broadcast.check();return bundledProgramRehearsal.broadcast.status().ready;}),'actual packaged receiver preflight');
    result.preflight=await app.evaluate(()=>bundledProgramRehearsal.broadcast.preflight);assert.equal(result.preflight.ready,true);
    const capturedPeer=await app.evaluate(()=>bundledProgramRehearsal.capture.status().peerId);assert.equal(result.preflight.output.peer_id,capturedPeer);
    await app.evaluate(()=>bundledProgramRehearsal.capture.window.webContents.executeJavaScript(`(()=>{const note=document.querySelector('[data-browser-review-note]');note.hidden=false;note.textContent='PREPARATION WARNING MUST NEVER BE ENCODED';note.style.cssText='position:fixed;inset:0;background:rgb(255,0,255);z-index:9999;display:block';})()`));
    await app.evaluate(()=>bundledProgramRehearsal.broadcast.start({destinationId:'packaged-local-file-only',format:'hd'}));
    await until(()=>app.evaluate(()=>bundledProgramRehearsal.broadcast.status().phase==='sending'),'bundled encoder consumes owned capture');
    result.cleanControlsExcluded=await app.evaluate(()=>bundledProgramRehearsal.capture.window.webContents.executeJavaScript(`document.documentElement.dataset.nativeCapture==='active'&&getComputedStyle(document.querySelector('[data-browser-review-note]')).display==='none'`));assert.equal(result.cleanControlsExcluded,true);
    assert.equal((await api('/api/desktop/status')).native_encoding.active,true);
    await api('/api/production/switcher/preview',{preview_sources:[imageSource,titleSource],layout:'auto'});
    await until(()=>app.evaluate((_electron,ids)=>ids.every(id=>bundledProgramRehearsal.capture.status().readySources.includes(id)),[imageSource,titleSource]),'same receiver decodes image and title');
    await pause(1800);await app.evaluate(()=>bundledProgramRehearsal.capture.window.minimize());assert.equal(await app.evaluate(()=>bundledProgramRehearsal.capture.window.isMinimized()),true);
    await pause(900);const switched=await take(),generation=switched.generation;
    await until(()=>app.evaluate(async(_electron,generation)=>{await bundledProgramRehearsal.broadcast.check();const state=bundledProgramRehearsal.broadcast.preflight;return state?.ready&&state.generation===generation;},generation),'Program change rendered while output minimized');
    await pause(2300);result.beforeStop=await app.evaluate(()=>bundledProgramRehearsal.snapshot());assert.equal(result.beforeStop.broadcast.phase,'sending');
    assert.equal(result.beforeStop.capture.peerId,capturedPeer);
    await app.evaluate(()=>bundledProgramRehearsal.broadcast.stop());
    result.preparationUiRestored=await app.evaluate(()=>bundledProgramRehearsal.capture.window.webContents.executeJavaScript(`(()=>{const note=document.querySelector('[data-browser-review-note]');const restored=!document.documentElement.dataset.nativeCapture&&getComputedStyle(note).display!=='none';note.hidden=true;note.removeAttribute('style');note.textContent='';return restored;})()`));assert.equal(result.preparationUiRestored,true);
    result.afterStop=await app.evaluate(()=>bundledProgramRehearsal.snapshot());assert.equal(result.afterStop.broadcast.active,false);assert.equal(result.afterStop.encoder.running,false);
    assert.equal((await api('/api/desktop/status')).native_encoding.active,false);result.encodingReleasedWhileOwnerAlive=await app.evaluate(()=>process.pid)>0;
    await app.evaluate(()=>bundledProgramRehearsal.capture.window.restore());const output=app.windows().find(page=>page.url().startsWith(origin+'/output/studio'));
    await output.screenshot({path:path.join(evidence,'program-output-final.png')});assert.equal(await app.evaluate(()=>bundledProgramRehearsal.close()),true);
    const metadata=JSON.parse(execFileSync('ffprobe',['-v','error','-count_frames','-show_streams','-show_format','-of','json',filename],{encoding:'utf8',windowsHide:true}));fs.writeFileSync(path.join(evidence,'program-ffprobe.json'),JSON.stringify(metadata,null,2));
    const v=metadata.streams.find(stream=>stream.codec_type==='video'),a=metadata.streams.find(stream=>stream.codec_type==='audio'),duration=Number(metadata.format.duration),frames=Number(v.nb_read_frames);
    assert.equal(v.codec_name,'h264');assert.equal(v.width,1280);assert.equal(v.height,720);assert.equal(a.codec_name,'aac');assert.equal(Number(a.sample_rate),48000);assert.equal(a.channels,2);assert.ok(duration>=5&&duration<14);assert.ok(frames/duration>=25);
    const ffmpeg=result.runtime.ffmpeg||'ffmpeg';
    const pcm=execFileSync(ffmpeg,['-v','error','-i',filename,'-t','1.5','-vn','-f','f32le','-ar','48000','-ac','2','pipe:1'],{windowsHide:true,maxBuffer:4*1024*1024});
    let power=0,sin=0,cos=0;const samples=pcm.length/8;for(let i=0;i<samples;i++){const sample=pcm.readFloatLE(i*8);power+=sample*sample;sin+=sample*Math.sin(2*Math.PI*440*i/48000);cos+=sample*Math.cos(2*Math.PI*440*i/48000);}
    const rms=Math.sqrt(power/samples),tone=2*Math.hypot(sin,cos)/samples;assert.ok(rms>.02&&tone>.02,'generated public tone must survive bundled encoding');
    const colors=[];for(const [label,seconds] of [['video',.8],['second-source',duration-.7]]){
      execFileSync(ffmpeg,['-y','-v','error','-ss',String(seconds),'-i',filename,'-frames:v','1',path.join(evidence,'program-'+label+'.png')],{windowsHide:true});
      colors.push([...execFileSync(ffmpeg,['-v','error','-ss',String(seconds),'-i',filename,'-vf','scale=1:1','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],{windowsHide:true})]);
    }
    assert.ok(colors[0][1]>colors[0][2]+15,'first encoded Program is green generated video');assert.ok(colors[1][2]>colors[1][1]+15,'minimized output changes to blue image/title');
    for(const [group,key] of [['capture','droppedFrames'],['capture','droppedAudioPackets'],['encoder','droppedVideoFrames'],['encoder','droppedAudioPackets']])assert.equal(result.beforeStop[group][key],0);
    assert.deepEqual(result.beforeStop.errors,[]);
    Object.assign(result,{complete:true,duration,videoFrames:frames,effectiveFps:frames/duration,publicToneRms:rms,publicToneAmplitude440Hz:tone,decodedProgramColors:colors,minimizedDuringTake:true,actualBundledBackend:true,actualAssetImport:true,actualPreflight:true,actualNativeBroadcast:true,actualOutputCapture:true,actualBundledEncoder:true});
    return result;
  }catch(error){result.error=error.message;try{result.failureSnapshot=await app.evaluate(()=>globalThis.bundledProgramRehearsal?.snapshot());result.failureSwitcher=await api('/api/production/switcher');}catch(_){}throw error;}
  finally{
    try{const closed=await app.evaluate(async()=>{const rehearsal=globalThis.bundledProgramRehearsal;if(!rehearsal)return true;const closed=await rehearsal.close();if(closed)delete globalThis.bundledProgramRehearsal;return closed;});result.cleanupConfirmed=closed===true&&(await api('/api/desktop/status')).native_encoding.active===false;}catch(_){result.cleanupConfirmed=false;}
    const cleanupFailure=result.complete&&!result.cleanupConfirmed;if(cleanupFailure){result.complete=false;result.error='packaged_program_cleanup_unconfirmed';}
    fs.writeFileSync(path.join(evidence,'program-results.json'),JSON.stringify(result,null,2));
    if(cleanupFailure)throw Error(result.error);
  }
}
module.exports={exerciseBundledProgram};
