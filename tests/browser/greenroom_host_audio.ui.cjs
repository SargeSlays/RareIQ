/* Actual WebRTC against the explicitly isolated fixture; synthesized audio only, no devices. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const BASE='http://127.0.0.1:8768',root=path.resolve(__dirname,'../../rareiq/web/static'),destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Supply an absolute evidence directory.');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  const marker=await fetch(BASE+'/__qa__/guest-fixture').then(response=>response.json());
  assert.equal(marker.isolated_guest_fixture,true);assert.equal(marker.hardware,false);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding']});
  let sequence=0;const run=Date.now(),errors=[],result={isolated:true,realPeerConnections:true,syntheticAudio:true,hardware:false};
  const api=async(url,body)=>{const response=await fetch(BASE+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),value=await response.json();if(!response.ok)throw Error(value.reason||'fixture_request_failed');return value;};
  const room=()=>api('/api/production/greenroom');
  const mutate=async(url,body={})=>api(url,{...body,expected_revision:(await room()).revision,request_id:`hostqa_${run}_${++sequence}`});
  async function until(check,label,timeout=20000){const limit=Date.now()+timeout;while(Date.now()<limit){const value=await check();if(value)return value;await new Promise(resolve=>setTimeout(resolve,150));}throw Error('Timed out: '+label);}
  async function synth(page,frequency){
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(frequency=>{
      window.syntheticAudio={captures:0,stops:0,contexts:[],peers:[]};const NativePC=RTCPeerConnection;window.RTCPeerConnection=class extends NativePC{constructor(...args){super(...args);syntheticAudio.peers.push(this);}};
      Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async constraints=>{
        if(constraints.video)throw Error('No video capture in this audio fixture');
        const context=new AudioContext(),oscillator=context.createOscillator(),gain=context.createGain(),output=context.createMediaStreamDestination();
        oscillator.frequency.value=frequency;gain.gain.value=.15;oscillator.connect(gain).connect(output);oscillator.start();await context.resume();
        syntheticAudio.captures++;syntheticAudio.contexts.push(context);const track=output.stream.getAudioTracks()[0],stop=track.stop.bind(track);
        track.stop=()=>{syntheticAudio.stops++;stop();oscillator.stop();context.close();};return output.stream;
      }});
      Object.defineProperty(navigator.mediaDevices,'enumerateDevices',{value:async()=>[]});
    },frequency);
  }
  async function guest(name,frequency){
    const invitation=await mutate('/api/production/greenroom/invites',{label:name,ttl_minutes:10}),context=await browser.newContext(),page=await context.newPage();await synth(page,frequency);
    await page.goto(invitation.join_url);await page.locator('#guestName').fill(name);await page.locator('#guestMicrophone').click();await page.locator('#guestJoin').click();
    const participant=await until(async()=>(await room()).participants.find(p=>p.name===name&&p.connected&&p.media.microphone),name+' mic publishes');return {page,participant};
  }
  async function spectrum(page){return page.evaluate(async()=>{
    const stream=document.getElementById('guestReturnAudio').srcObject;if(!stream)return null;
    const context=new AudioContext(),source=context.createMediaStreamSource(stream),analyser=context.createAnalyser();analyser.fftSize=8192;source.connect(analyser);await context.resume();
    await new Promise(resolve=>setTimeout(resolve,450));const values=new Float32Array(analyser.frequencyBinCount);analyser.getFloatFrequencyData(values);const result={};
    for(const frequency of [440,660,880]){let peak=-160;for(let i=0;i<values.length;i++)if(Math.abs(i*context.sampleRate/analyser.fftSize-frequency)<20)peak=Math.max(peak,values[i]);result[frequency]=Number.isFinite(peak)?Math.round(peak*10)/10:-160;}
    source.disconnect();await context.close();return result;
  });}
  let producer,output;
  try{
    await mutate('/api/production/greenroom/room/close');await mutate('/api/production/greenroom/room/open');
    await api('/api/production/switcher/preview',{preview_sources:[],layout:'auto'});await api('/api/production/switcher/take',{preview_sources:[],layout:'auto',transition:'cut',duration_ms:0});
    producer=await browser.newPage({viewport:{width:1440,height:1000}});await synth(producer,660);await producer.goto(BASE+'/guest');
    await producer.evaluate(()=>{document.body.innerHTML='<main id="hostWorkspace"></main>';document.body.className='pp-shell studiox-ui4 studiox-premium studiox-command-deck';document.body.dataset.operatorLayout='v2';document.body.dataset.studioxVisualSystem='unified';document.documentElement.dataset.theme='dark';});
    for(const file of ['brand/producer-please-v2/producer-please.tokens.css','greenroom_controls.css'])await producer.addStyleTag({url:BASE+'/static/'+file});
    await producer.addScriptTag({url:BASE+'/static/greenroom_controls.js'});await producer.evaluate(()=>ProducerGreenroomControls.mount(document.getElementById('hostWorkspace')));
    await until(()=>producer.locator('[data-host-mic]').isEnabled(),'host control ready');
    assert.equal(await producer.evaluate(()=>syntheticAudio.captures),0);
    await producer.locator('[data-host-mic]').click();
    const host=await until(async()=>(await room()).participants.find(p=>p.name==='Producer microphone'&&p.connected&&p.state==='admitted'&&p.media.microphone),'host microphone publishes');
    assert.deepEqual((await room()).switcher.program_sources,[],'adding microphone never takes Program');
    assert.deepEqual((await room()).switcher.preview_sources,[],'adding microphone never changes Preview');
    const first=await guest('Audio guest one',440),second=await guest('Audio guest two',880);
    assert.equal(await first.page.evaluate(()=>document.getElementById('guestReturnAudio').srcObject),null,'waiting guest receives no return audio');
    await mutate('/api/production/greenroom/participants/'+first.participant.id,{action:'admit'});
    await mutate('/api/production/greenroom/participants/'+second.participant.id,{action:'admit'});
    await until(()=>first.page.evaluate(()=>Boolean(document.getElementById('guestReturnAudio').srcObject?.getAudioTracks().length)),'first guest return stream');
    await until(()=>second.page.evaluate(()=>Boolean(document.getElementById('guestReturnAudio').srcObject?.getAudioTracks().length)),'second guest return stream');
    result.firstReturn=await until(async()=>{const v=await spectrum(first.page);result.lastFirstReturn=v;return v&&v[660]>-65&&v[880]>-65&&v[440]<Math.min(v[660],v[880])-15?v:false;},'first guest mix-minus');
    result.secondReturn=await until(async()=>{const v=await spectrum(second.page);return v&&v[660]>-65&&v[440]>-65&&v[880]<Math.min(v[660],v[440])-15?v:false;},'second guest mix-minus');
    output=await browser.newPage();output.on('pageerror',error=>errors.push(error.message));await output.goto(BASE+'/program');
    await producer.locator(`[data-participant-id="${host.id}"] [data-source-kind="audio"]`).click();
    await until(async()=>(await room()).output.ready_sources.includes(host.sources.audio),'host mic output preparation');
    await producer.locator('[data-room-take]').click();
    await until(async()=>{const state=await room();return state.switcher.program_sources.includes(host.sources.audio)&&state.output.rendered_generation===state.switcher.generation;},'host mic rendered after explicit Take');
    assert.equal(await output.locator('audio').count(),1,'one host Program mic');result.hostProgramAudio=true;
    await producer.locator('[data-host-mic]').click();await until(()=>producer.evaluate(()=>syntheticAudio.stops===1),'owned host track stopped');
    await until(async()=>(await room()).switcher.program_sources.length===0,'host removal clears Program');await until(()=>output.locator('audio').count().then(n=>n===0),'host Program audio cleared');
    result.afterHostStop=await until(async()=>{const v=await spectrum(first.page);return v&&v[880]>-65&&v[660]<v[880]-15&&v[440]<v[880]-15?v:false;},'return mix drops host mic');
    result.noCaptureOnMount=true;result.explicitTake=true;result.waitingExcluded=true;result.hostTrackCleaned=true;result.errors=errors;assert.deepEqual(errors,[]);
    await producer.screenshot({path:path.join(destination,'host-audio-controls.png'),fullPage:true});fs.writeFileSync(path.join(destination,'host-audio-results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(error){const debug=producer?await producer.evaluate(async()=>({participants:ProducerGreenroomControls.receiver().state()?.room.participants.map(p=>({name:p.name,state:p.state,tracks:Object.fromEntries(Object.entries(ProducerGreenroomControls.receiver().tracks(p.id)).map(([k,t])=>[k,t?{muted:t.muted,enabled:t.enabled,state:t.readyState}:null]))})),stats:await Promise.all(syntheticAudio.peers.map(async pc=>[...await pc.getStats()].map(([,s])=>s).filter(s=>['inbound-rtp','outbound-rtp','media-source'].includes(s.type)).map(s=>({type:s.type,kind:s.kind,energy:s.totalAudioEnergy,level:s.audioLevel,received:s.bytesReceived,sent:s.bytesSent}))))})).catch(()=>null):null;fs.writeFileSync(path.join(destination,'host-audio-failure.json'),JSON.stringify({error:error.message,result,debug,state:await room(),errors,notice:producer?await producer.locator('.greenroom-notice').textContent().catch(()=>null):null},null,2));throw error;}
  finally{await browser.close();}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
