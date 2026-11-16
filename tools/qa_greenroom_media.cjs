/* Real Chromium WebRTC against the isolated fixture only. No real devices/audio output. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const BASE='http://127.0.0.1:8768';
const destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('An absolute evidence directory is required');
fs.mkdirSync(destination,{recursive:true});

async function main(){
  const marker=await fetch(BASE+'/__qa__/guest-fixture').then(r=>r.json());
  assert.equal(marker.isolated_guest_fixture,true);assert.equal(marker.hardware,false);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding']});
  const faults=[];const results={isolated:true,realPeerConnections:true,syntheticMedia:true,hardware:false};
  const api=async(url,body)=>{const response=await fetch(BASE+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const value=await response.json();if(!response.ok)throw Error(`${url}: ${value.reason||response.status}`);return value;};
  const room=()=>api('/api/production/greenroom');
  let sequence=0;const runId=Date.now().toString(36);
  async function mutate(url,body={}){const state=await room();return api(url,{...body,expected_revision:state.revision,request_id:'qa_'+runId+'_'+(++sequence)});}
  async function until(check,label,timeout=20000){const end=Date.now()+timeout;let value;while(Date.now()<end){value=await check();if(value)return value;await new Promise(r=>setTimeout(r,200));}throw Error('Timed out: '+label);}
  function observe(page){page.on('pageerror',error=>faults.push(error.message));}
  async function guest(label,color,frequency){
    const invitation=await mutate('/api/production/greenroom/invites',{label,ttl_minutes:10});
    const context=await browser.newContext({viewport:{width:1280,height:900}});const page=await context.newPage();observe(page);
    await page.addInitScript(({color,frequency})=>{
      const retained=[];window.__fixtureMedia=retained;
      function video(fill){const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;const ctx=canvas.getContext('2d');let n=0;const timer=setInterval(()=>{ctx.fillStyle=fill;ctx.fillRect(0,0,640,360);ctx.fillStyle='#ffffff';ctx.fillRect((n++*7)%600,330,35,12);},40);retained.push({canvas,timer});return canvas.captureStream(25).getVideoTracks()[0];}
      function audio(hz){const context=new AudioContext();const oscillator=context.createOscillator(),gain=context.createGain(),output=context.createMediaStreamDestination();oscillator.frequency.value=hz;gain.gain.value=.05;oscillator.connect(gain).connect(output);oscillator.start();context.resume();retained.push({context,oscillator});return output.stream.getAudioTracks()[0];}
      Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async constraints=>new MediaStream([...(constraints.video?[video(color)]:[]),...(constraints.audio?[audio(frequency)]:[])])});
      Object.defineProperty(navigator.mediaDevices,'getDisplayMedia',{value:async()=>new MediaStream([video('#166f45'),audio(frequency+220)])});
      Object.defineProperty(navigator.mediaDevices,'enumerateDevices',{value:async()=>[]});
    },{color,frequency});
    await page.goto(invitation.join_url);await page.locator('#guestName').fill(label);
    await page.locator('#guestCamera').click();await page.locator('#guestMicrophone').click();await page.locator('#guestJoin').click();
    const participant=await until(async()=>{const state=await room();return state.participants.find(p=>p.name===label&&p.connected&&p.media.camera&&p.media.microphone);},label+' publishes');
    return {context,page,participant};
  }
  let output;
  try{
    await mutate('/api/production/greenroom/room/close');
    await mutate('/api/production/greenroom/room/open');
    await api('/api/production/switcher/preview',{preview_sources:[],layout:'auto'});
    await api('/api/production/switcher/take',{preview_sources:[],transition:'cut',duration_ms:0,layout:'auto'});
    await api('/api/production/switcher/preview',{preview_sources:[],layout:'auto'});
    const producer=await browser.newPage();observe(producer);await producer.goto(BASE+'/guest');
    await producer.evaluate(()=>{window.__receiver=ProducerGuestMedia.createReceiver({role:'producer',onState:state=>{window.__roomState=state;},onTracks:()=>{}});window.__receiver.connect();});
    output=await browser.newPage({viewport:{width:1280,height:720}});observe(output);await output.goto(BASE+'/program');
    const first=await guest('Fixture blue','#204fa8',440),second=await guest('Fixture amber','#b66a12',880);
    await until(async()=>{const state=await room();return state.participants.filter(p=>p.connected).length===2;},'two waiting guests');
    assert.equal(await output.locator('video').count(),0,'waiting guests never reach output');
    assert.equal(await output.locator('audio').count(),0,'waiting guest audio never reaches output');
    await mutate('/api/production/greenroom/participants/'+first.participant.id,{action:'admit'});
    await mutate('/api/production/greenroom/participants/'+second.participant.id,{action:'admit'});
    const a=first.participant.sources.camera,b=second.participant.sources.camera;
    await api('/api/production/switcher/preview',{preview_sources:[a],layout:'auto'});
    await until(async()=>{const state=await room();return state.output.ready_sources.includes(a);},'output receives muted Preview');
    assert.equal(await output.locator('audio').count(),0,'Preview cannot create Program audio');
    let taken=await api('/api/production/switcher/take',{preview_sources:[a],transition:'fade',duration_ms:250,layout:'auto'});
    console.log(JSON.stringify({taken}));
    await until(async()=>{const state=await room();return state.output.rendered_generation===taken.generation;},'first guest rendered');
    assert.equal(await output.locator('audio').count(),1,'one Program microphone');
    await first.page.locator('#guestScreen').click();
    const screen=first.participant.sources.screen;
    await until(async()=>{const state=await room();return state.participants.find(p=>p.id===first.participant.id)?.media.screen;},'screen published');
    await api('/api/production/switcher/preview',{preview_sources:[a,screen,b],layout:'grid'});
    await until(async()=>{const state=await room();return [a,screen,b].every(s=>state.output.ready_sources.includes(s));},'three-source output preparation');
    taken=await api('/api/production/switcher/take',{preview_sources:[a,screen,b],layout:'grid',transition:'slide',duration_ms:250});
    await until(async()=>{const state=await room();return state.output.rendered_generation===taken.generation;},'guest grid rendered');
    await until(()=>output.locator('.composition-layer:not(.composition-outgoing) video').count().then(n=>n===3),'three visible guest sources');
    assert.equal(await output.locator('audio').count(),3,'two unique microphones plus one shared-screen audio track');
    results.guestGrid={generation:taken.generation,sources:3,audioTracks:3};
    await output.screenshot({path:path.join(destination,'guest-program-grid.png')});
    // Program mute is a producer mix decision, independent of the guest's capture
    // and its conference return stream. All tones/media here are generated fixtures.
    await producer.evaluate(async()=>{window.__conference=ProducerGuestMedia.createConferenceAudio(__receiver);window.__conferenceContext=new AudioContext();await __conference.start(__conferenceContext);});
    await until(()=>first.page.evaluate(()=>Boolean(document.getElementById('guestReturnAudio').srcObject?.getAudioTracks().length)),'conference return before Program mute');
    await first.page.evaluate(()=>{window.__returnBeforeMute=document.getElementById('guestReturnAudio').srcObject.getAudioTracks()[0];});
    await output.evaluate(()=>{window.__videosBeforeMute=[...document.querySelectorAll('.composition-layer:not(.composition-outgoing) video')];window.__audioBeforeMute=[...document.querySelectorAll('audio')];});
    const audioControl='/api/production/greenroom/participants/'+first.participant.id;
    await mutate(audioControl,{action:'program_audio',microphone_muted:true,screen_muted:false});
    await until(()=>output.locator('audio').count().then(n=>n===2),'Program microphone mute keeps shared screen audio');
    await mutate(audioControl,{action:'program_audio',microphone_muted:true,screen_muted:true});
    await until(()=>output.locator('audio').count().then(n=>n===1),'Program screen mute leaves other participant mic');
    assert.equal(await output.evaluate(()=>__videosBeforeMute.every(v=>v.isConnected&&v.readyState>=2)),true,'Program videos survive both audio mute changes');
    assert.equal(await output.evaluate(()=>__audioBeforeMute.filter(a=>!a.isConnected).every(a=>a.paused&&a.srcObject===null)),true,'muted consumers release playback');
    assert.equal(await first.page.evaluate(()=>__returnBeforeMute===document.getElementById('guestReturnAudio').srcObject?.getAudioTracks()[0]&&__returnBeforeMute.readyState==='live'),true,'conference return track remains intact');
    const returnLevels=await second.page.evaluate(async()=>{
      const stream=document.getElementById('guestReturnAudio').srcObject;if(!stream)return null;
      const context=new AudioContext(),source=context.createMediaStreamSource(stream),analyser=context.createAnalyser();analyser.fftSize=8192;source.connect(analyser);await context.resume();
      await new Promise(resolve=>setTimeout(resolve,450));const bins=new Float32Array(analyser.frequencyBinCount);analyser.getFloatFrequencyData(bins);const levels={};
      for(const hz of [440,660]){let peak=-160;for(let i=0;i<bins.length;i++)if(Math.abs(i*context.sampleRate/analyser.fftSize-hz)<20)peak=Math.max(peak,bins[i]);levels[hz]=Number.isFinite(peak)?Math.round(peak*10)/10:-160;}
      source.disconnect();await context.close();return levels;
    });
    assert.ok(returnLevels&&returnLevels[440]>-75&&returnLevels[660]>-75,'muted participant mic and screen audio remain in conference return');
    const duringMute=(await room()).participants.find(p=>p.id===first.participant.id);
    assert.equal(duringMute.media.microphone,true);assert.equal(duringMute.media.screen_audio,true);assert.equal(duringMute.media.camera,true);assert.equal(duringMute.media.screen,true);
    await mutate(audioControl,{action:'program_audio',microphone_muted:false,screen_muted:true});
    await until(()=>output.locator('audio').count().then(n=>n===2),'Program mic unmute retains screen silence');
    await mutate(audioControl,{action:'program_audio',microphone_muted:false,screen_muted:false});
    await until(()=>output.locator('audio').count().then(n=>n===3),'Program screen audio unmute restores deduplicated mix');
    assert.equal(await output.evaluate(()=>__videosBeforeMute.every(v=>v.isConnected&&v.readyState>=2)),true);
    results.programAudioMute={microphoneIndependent:true,screenIndependent:true,videoUnchanged:true,captureUnchanged:true,returnTrackUnchanged:true,returnLevels,consumersReleased:true,unmuteRestoresDeduplicatedMix:true};
    await mutate('/api/production/greenroom/participants/'+first.participant.id,{action:'remove'});
    await until(async()=>{const state=await room();return state.switcher.program_sources.length===1&&state.switcher.program_sources[0]===b;},'removed guest disappears from Program');
    await until(()=>output.locator('audio').count().then(n=>n===1),'removed guest audio stops');
    assert.ok((await room()).participants.find(p=>p.id===first.participant.id).state==='removed');
    await second.page.locator('#guestLeave').click();
    await until(async()=>{const state=await room();return state.switcher.program_sources.length===0;},'last guest leaves to blank');
    await until(()=>output.locator('audio').count().then(n=>n===0),'last guest audio stops');
    results.removalClearsVideoAndAudio=true;results.previewMuted=true;results.waitingExcluded=true;results.pageErrors=faults;
    assert.deepEqual(faults,[]);fs.writeFileSync(path.join(destination,'webrtc-results.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify(results));
  }catch(error){
    const state=await room();const debug={error:error.message,output:state.output,switcher:state.switcher,pageErrors:faults,
      dom:output?await output.evaluate(()=>({program:document.querySelector('[data-producer-program-output]')?.dataset,
        videos:[...document.querySelectorAll('video')].map(v=>({ready:v.readyState,width:v.videoWidth,paused:v.paused,tile:v.parentElement.dataset})),
        audio:[...document.querySelectorAll('audio')].map(v=>({ready:v.readyState,paused:v.paused}))})):null};
    fs.writeFileSync(path.join(destination,'failure.json'),JSON.stringify(debug,null,2));throw error;
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
