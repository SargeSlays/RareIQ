/* Explicit full native rehearsal. Generated media, isolated loopback, local FLV only. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn,execFileSync}=require('node:child_process'),{once}=require('node:events'),net=require('node:net');
const {_electron}=require('playwright');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

// Serialized into an F: bootstrap. All imports below are actual production modules.
function electronMain(){
  const {app,BrowserWindow,ipcMain}=require('electron'),fs=require('node:fs'),path=require('node:path');
  const config=JSON.parse(process.env.PRODUCER_NATIVE_REHEARSAL);
  const {NativeBroadcast}=require(path.join(config.project,'desktop/broadcast.cjs'));
  const {Encoder}=require(path.join(config.project,'desktop/encoder.cjs'));
  const {createOutputCapture}=require(path.join(config.project,'desktop/output-capture.cjs'));
  app.setPath('userData',path.join(config.evidence,'profile'));
  app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
  app.on('window-all-closed',()=>{});
  app.on('web-contents-created',(_event,contents)=>{
    contents.session.webRequest.onBeforeRequest((details,reply)=>{
      const url=new URL(details.url),sameFixture=url.origin===config.origin||url.origin===config.origin.replace(/^http/,'ws');
      reply({cancel:!['data:','blob:','devtools:'].includes(url.protocol)&&!sameFixture});
    });
    contents.session.setPermissionRequestHandler((_contents,_permission,reply)=>reply(false));
    contents.session.setPermissionCheckHandler(()=>false);
  });
  app.whenReady().then(async()=>{
    const request=async(route,body)=>{
      if(!route.startsWith('/api/')||route.includes('://'))throw Error('non_fixture_request');
      const response=await fetch(config.origin+route,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
      const value=await response.json();if(!response.ok||value.ok===false)throw Error(value.reason||'fixture_request_failed');return value;
    };
    const status=await request('/api/desktop/status'),events=[],errors=[];
    const identity={pid:status.pid,server_session_id:status.server_session_id};
    let capture,encoder;
    const broadcast=new NativeBroadcast({request,identity,ownerPid:process.pid,confirm:async()=>true,
      destinations:{getPrivateDestination:async()=>({name:'LOCAL REHEARSAL ONLY',serverUrl:'rtmps://example.invalid/live',streamKey:'invalid-synthetic-never-sent'})},
      createCapture:size=>(capture=createOutputCapture({BrowserWindow,ipcMain,origin:config.origin,baseDir:path.join(config.project,'desktop'),...size,
        partition:'persist:isolated-native-rehearsal',onError:code=>errors.push(code)})),
      createEncoder:onState=>{
        encoder=new Encoder({python:config.python,workerPath:path.join(config.project,'desktop/encoder_worker.py'),
          pythonPackages:config.pythonPackages,artifactRoot:config.evidence,onState:snapshot=>{events.push(snapshot);onState(snapshot);}});
        return {status:()=>encoder.status(),sendVideo:(...args)=>encoder.sendVideo(...args),sendAudio:(...args)=>encoder.sendAudio(...args),stop:()=>encoder.stop(),
          start:({destination,...settings})=>{
            if(destination?.streamKey!=='invalid-synthetic-never-sent')throw Error('synthetic_profile_required');
            // No destination or transport survives this boundary. Worker opens a local file.
            return encoder.start({...settings,codec:'libx264',testOutput:path.join(config.evidence,'native-program.flv')});
          }};
      }});
    globalThis.nativeRehearsal={broadcast,request,identity,errors,events,ownerPid:process.pid,
      get capture(){return capture;},get encoder(){return encoder;},
      async generate(){
        const generator=new BrowserWindow({show:false,width:640,height:360,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,autoplayPolicy:'no-user-gesture-required',backgroundThrottling:false}});
        generator.webContents.setAudioMuted(true);
        await generator.loadURL('data:text/html,<canvas width="640" height="360"></canvas>');
        const generated=await generator.webContents.executeJavaScript(`(async()=>{
          const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d'),audio=new AudioContext({sampleRate:48000});await audio.resume();
          const sink=audio.createMediaStreamDestination(),tone=audio.createOscillator(),gain=audio.createGain();tone.frequency.value=440;gain.gain.value=.15;tone.connect(gain).connect(sink);tone.start();
          const stream=canvas.captureStream(30);for(const track of sink.stream.getAudioTracks())stream.addTrack(track);
          const chunks=[],recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus',videoBitsPerSecond:1800000});
          recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
          let frame=0;const paint=()=>{ctx.fillStyle='#137049';ctx.fillRect(0,0,640,360);ctx.fillStyle='#e146a5';ctx.fillRect((frame++*7)%540,170,100,90);ctx.fillStyle='white';ctx.font='bold 27px sans-serif';ctx.fillText('GENERATED SOURCE',30,65);ctx.font='18px sans-serif';ctx.fillText('Local rehearsal · 440 Hz tone · '+frame,30,100);};paint();
          const timer=setInterval(paint,33);recorder.start(250);await new Promise(resolve=>setTimeout(resolve,7000));
          await new Promise(resolve=>{recorder.onstop=resolve;recorder.stop();});clearInterval(timer);tone.stop();stream.getTracks().forEach(track=>track.stop());await audio.close();
          ctx.fillStyle='#1647a0';ctx.fillRect(0,0,640,360);ctx.fillStyle='white';ctx.font='bold 30px sans-serif';ctx.fillText('SECOND PROGRAM SOURCE',30,150);
          return {webm:Array.from(new Uint8Array(await new Blob(chunks,{type:'video/webm'}).arrayBuffer())),png:canvas.toDataURL('image/png').split(',')[1]};
        })()`,true);
        fs.writeFileSync(path.join(config.evidence,'generated-source.webm'),Buffer.from(generated.webm));
        fs.writeFileSync(path.join(config.evidence,'generated-image.png'),Buffer.from(generated.png,'base64'));generator.destroy();return true;
      },
      snapshot(){return {broadcast:broadcast.status(),capture:capture?.status(),encoder:encoder?.status(),errors:[...errors]};},
    };
  }).catch(error=>{globalThis.nativeRehearsalError=error.message;});
}

async function main(){
  const evidence=path.resolve(process.argv[2]||''),electron=process.argv[3];
  if(!process.argv[2]||!path.isAbsolute(process.argv[2])||!electron||!path.isAbsolute(electron))throw Error('Supply NEW absolute evidence directory and Electron executable');
  if(process.platform==='win32'&&path.parse(evidence).root.toLowerCase()!=='f:\\')throw Error('Evidence must use F:');
  fs.mkdirSync(evidence,{recursive:false});
  const project=path.resolve(__dirname,'../..'),python=path.join(project,'.venv/Scripts/python.exe');
  const probe=net.createServer();probe.listen(0,'127.0.0.1');await once(probe,'listening');const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
  const origin='http://127.0.0.1:'+port,result={complete:false,syntheticOnly:true,hardware:false,externalBroadcast:false,platformLiveVerified:false};
  let fixture,app,captureBeforeStop;
  const fixtureLog=fs.openSync(path.join(evidence,'fixture.log'),'w');
  const api=async(route,body,headers)=>{
    const response=await fetch(origin+route,body===undefined?{}:{method:'POST',headers:headers||{'Content-Type':'application/json'},body:Buffer.isBuffer(body)?body:JSON.stringify(body)});
    const value=await response.json();assert.ok(response.ok&&value.ok!==false,route+': '+(value.reason||response.status));return value;
  };
  async function until(check,label,timeout=20000){const end=Date.now()+timeout;while(Date.now()<end){try{if(await check())return;}catch(error){if(fixture?.exitCode!==null)throw error;}await pause(100);}throw Error('Timed out: '+label);}
  try{
    fixture=spawn(python,['-B',path.join(project,'tools/qa_native_desktop_fixture.py'),path.join(evidence,'fixture-state'),String(port)],{cwd:project,windowsHide:true,stdio:['ignore',fixtureLog,fixtureLog],env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
    await until(async()=>{const marker=await fetch(origin+'/__qa__/guest-fixture').then(r=>r.json());return marker.native_desktop_fixture===true;},'isolated native fixture',45000);
    for(const route of ['/api/system/shutdown','/api/desktop/stop'])assert.equal((await fetch(origin+route,{method:'POST'})).status,403);
    const config={project,evidence,origin,python,pythonPackages:'F:/Caches/ProducerPlease/python-packages'};
    const bootstrap=path.join(evidence,'native-rehearsal-app.cjs');fs.writeFileSync(bootstrap,'('+electronMain.toString()+')();\n');
    app=await _electron.launch({executablePath:electron,args:[bootstrap],env:{...process.env,PRODUCER_NATIVE_REHEARSAL:JSON.stringify(config)}});
    await until(()=>app.evaluate(()=>Boolean(globalThis.nativeRehearsal)||Boolean(globalThis.nativeRehearsalError)),'native coordinator');
    assert.equal(await app.evaluate(()=>globalThis.nativeRehearsalError),undefined);
    await app.evaluate(()=>nativeRehearsal.generate());
    const asset=async(file,type)=>(await api('/api/creator/assets',fs.readFileSync(path.join(evidence,file)),{'Content-Type':type,'X-RareIQ-Filename':file})).asset;
    const video=await asset('generated-source.webm','video/webm'),image=await asset('generated-image.png','image/png');
    const title=(await api('/api/production/sources/text',{name:'Rehearsal title',text:'LOCAL NATIVE PIPELINE',position:'lower-third',request_id:'native_rehearsal_title'})).source;
    const videoSource='video:'+video.id,imageSource='image:'+image.id,titleSource=title.id;
    assert.match(titleSource,/^text:[a-f0-9-]{36}$/);
    await api('/api/production/switcher/preview',{preview_sources:[videoSource]});
    await app.evaluate(()=>nativeRehearsal.broadcast.prepare({format:'hd'}));
    await until(async()=>{const state=await api('/api/production/switcher');return state.guest_output.ready_sources.includes(videoSource);},'actual video decoded in output');
    let sequence=0;
    const take=()=>api('/api/production/switcher/take',{transition:'cut',duration_ms:0,request_id:'native_take_'+(++sequence),expires_at:Date.now()/1000+30});
    await take();
    await until(()=>app.evaluate(async()=>{await nativeRehearsal.broadcast.check();return nativeRehearsal.broadcast.status().ready;}),'exact output native preflight');
    result.preflight=await app.evaluate(()=>nativeRehearsal.broadcast.preflight);
    assert.ok(result.preflight.output.peer_id);assert.equal(result.preflight.ready,true);
    await app.evaluate(()=>nativeRehearsal.capture.window.webContents.executeJavaScript(`(()=>{const note=document.querySelector('[data-browser-review-note]');note.hidden=false;note.textContent='SYNTHETIC PREPARATION UI — MUST NOT BE ENCODED';note.style.cssText='position:fixed;inset:0;background:rgb(255,0,255);z-index:9999;display:block';})()`));
    await app.evaluate(()=>nativeRehearsal.broadcast.start({destinationId:'local-file-only',format:'hd'}));
    await until(()=>app.evaluate(()=>nativeRehearsal.broadcast.status().phase==='sending'),'encoder receives real capture');
    result.cleanControlsExcluded=await app.evaluate(()=>nativeRehearsal.capture.window.webContents.executeJavaScript(`document.documentElement.dataset.nativeCapture==='active'&&getComputedStyle(document.querySelector('[data-browser-review-note]')).display==='none'`));assert.equal(result.cleanControlsExcluded,true,'preparation UI must never enter captured Program');
    assert.equal((await api('/api/desktop/status')).native_encoding.active,true);
    await api('/api/production/switcher/preview',{preview_sources:[imageSource,titleSource],layout:'auto'});
    await until(async()=>{const ready=(await api('/api/production/switcher')).guest_output.ready_sources;return ready.includes(imageSource)&&ready.includes(titleSource);},'image/title decoded before Take');
    await pause(1800);
    await app.evaluate(()=>nativeRehearsal.capture.window.minimize());
    assert.equal(await app.evaluate(()=>nativeRehearsal.capture.window.isMinimized()),true);
    await pause(900);await take();
    await until(()=>app.evaluate(async()=>{await nativeRehearsal.broadcast.check();return nativeRehearsal.broadcast.preflight?.ready&&nativeRehearsal.broadcast.preflight.generation===2;}),'new Program rendered while minimized');
    await pause(1800);
    captureBeforeStop=await app.evaluate(()=>nativeRehearsal.snapshot());
    result.beforeStop=captureBeforeStop;assert.equal(captureBeforeStop.broadcast.phase,'sending');
    await app.evaluate(()=>nativeRehearsal.broadcast.stop());
    result.preparationUiRestored=await app.evaluate(()=>nativeRehearsal.capture.window.webContents.executeJavaScript(`(()=>{const note=document.querySelector('[data-browser-review-note]');const restored=!document.documentElement.dataset.nativeCapture&&getComputedStyle(note).display!=='none';note.hidden=true;note.removeAttribute('style');note.textContent='';return restored;})()`));assert.equal(result.preparationUiRestored,true,'stopping restores the preparation UI');
    result.afterStop=await app.evaluate(()=>nativeRehearsal.snapshot());
    assert.equal(result.afterStop.broadcast.active,false);assert.equal(result.afterStop.encoder.running,false);
    const idle=await api('/api/desktop/status');assert.equal(idle.native_encoding.active,false);
    result.ownerStillAlive=await app.evaluate(()=>process.pid);assert.ok(result.ownerStillAlive>0);
    result.encodingReleasedWhileOwnerAlive=true;
    await app.evaluate(()=>nativeRehearsal.capture.window.restore());
    const output=app.windows().find(window=>window.url().startsWith(origin+'/output/studio'));
    await output.screenshot({path:path.join(evidence,'native-output-final.png')});
    await app.evaluate(()=>nativeRehearsal.broadcast.close());
    const filename=path.join(evidence,'native-program.flv');
    const metadata=JSON.parse(execFileSync('ffprobe',['-v','error','-count_frames','-show_streams','-show_format','-of','json',filename],{encoding:'utf8',windowsHide:true}));
    fs.writeFileSync(path.join(evidence,'ffprobe.json'),JSON.stringify(metadata,null,2));
    const v=metadata.streams.find(s=>s.codec_type==='video'),a=metadata.streams.find(s=>s.codec_type==='audio'),duration=Number(metadata.format.duration);
    assert.equal(v.codec_name,'h264');assert.equal(v.width,1280);assert.equal(v.height,720);
    assert.equal(a.codec_name,'aac');assert.equal(Number(a.sample_rate),48000);assert.equal(a.channels,2);
    assert.ok(duration>=4.5&&duration<12,'bounded local output duration');
    const frames=Number(v.nb_read_frames);assert.ok(frames/duration>=25,'sustained encoded frame rate');
    const pcm=execFileSync('ffmpeg',['-v','error','-i',filename,'-t','1.5','-vn','-f','f32le','-ar','48000','-ac','2','pipe:1'],{windowsHide:true,maxBuffer:4*1024*1024});
    let power=0,sin=0,cos=0;const samples=pcm.length/8;
    for(let i=0;i<samples;i++){const sample=pcm.readFloatLE(i*8);power+=sample*sample;sin+=sample*Math.sin(2*Math.PI*440*i/48000);cos+=sample*Math.cos(2*Math.PI*440*i/48000);}
    const rms=Math.sqrt(power/samples),toneAmplitude=2*Math.hypot(sin,cos)/samples;
    assert.ok(rms>.02&&toneAmplitude>.02,'generated public 440Hz tone survived encode');
    const colors=[];
    for(const [label,seconds] of [['video',.8],['second-source',Math.max(0,duration-.7)]]){
      execFileSync('ffmpeg',['-y','-v','error','-ss',String(seconds),'-i',filename,'-frames:v','1',path.join(evidence,label+'.png')],{windowsHide:true});
      colors.push([...execFileSync('ffmpeg',['-v','error','-ss',String(seconds),'-i',filename,'-vf','scale=1:1','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],{windowsHide:true})]);
    }
    assert.ok(colors[0][1]>colors[0][2]+15,'encoded first Program retains generated green video');
    assert.ok(colors[1][2]>colors[1][1]+15,'encoded Program changes to blue image while window remains minimized');
    result.decodedProgramColors=colors;
    assert.equal(captureBeforeStop.capture.droppedFrames,0);assert.equal(captureBeforeStop.capture.droppedAudioPackets,0);
    assert.equal(captureBeforeStop.encoder.droppedVideoFrames,0);assert.equal(captureBeforeStop.encoder.droppedAudioPackets,0);
    assert.deepEqual(captureBeforeStop.errors,[]);
    Object.assign(result,{complete:true,duration,videoFrames:frames,effectiveFps:frames/duration,publicToneRms:rms,publicToneAmplitude440Hz:toneAmplitude,minimizedDuringTake:true,actualAssetImport:true,actualPreflight:true,actualNativeBroadcast:true,actualOutputCapture:true,actualLocalEncoder:true});
  }catch(error){
    result.error=error.message;
    if(app)try{result.failureSnapshot=await app.evaluate(()=>nativeRehearsal.snapshot());}catch(_){}
    try{result.failureSwitcher=await api('/api/production/switcher');}catch(_){}
    throw error;
  }
  finally{
    if(app){try{await app.evaluate(async()=>{await globalThis.nativeRehearsal?.broadcast.close();});}catch(_){}await app.close().catch(()=>{});}
    if(fixture&&fixture.exitCode===null){fixture.kill();await once(fixture,'close').catch(()=>{});}
    fs.closeSync(fixtureLog);fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));
  }
  console.log(JSON.stringify({complete:result.complete,evidence,duration:result.duration,effectiveFps:result.effectiveFps,publicToneRms:result.publicToneRms}));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
