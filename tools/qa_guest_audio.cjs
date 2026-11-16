/* Generated audio, isolated fixture, no physical device, recording or speaker output. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const BASE='http://127.0.0.1:8768',destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Absolute evidence directory required');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  const marker=await fetch(BASE+'/__qa__/guest-fixture').then(r=>r.json());assert.equal(marker.isolated_guest_fixture,true);assert.equal(marker.hardware,false);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding']});
  const errors=[],results={synthetic:true,hardware:false,externalBroadcast:false};
  const request=async(url,body)=>{const response=await fetch(BASE+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});assert.ok(response.ok,'fixture API status '+response.status);return response.json();};
  let count=0;const stamp=Date.now();
  const mutate=async(url,body={})=>request(url,{...body,expected_revision:(await request('/api/production/greenroom')).revision,request_id:`audio_${stamp}_${++count}`});
  async function until(check,label,ms=15000){const end=Date.now()+ms;while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out: '+label);}
  try{
    await mutate('/api/production/greenroom/room/close');await mutate('/api/production/greenroom/room/open');
    const receiver=await browser.newPage();receiver.on('pageerror',e=>errors.push(e.message));await receiver.goto(BASE+'/guest');
    await receiver.evaluate(()=>{
      window.received=null;window.receiver=ProducerGuestMedia.createReceiver({role:'producer',onTracks:(id,tracks)=>{window.received=tracks.microphone;}});receiver.connect();
      window.level=async()=>{const track=window.received;if(!track)return 0;if(window.measured!==track){window.sink?.pause();window.source?.disconnect();window.measured=track;window.measureContext??=new AudioContext();window.sink=document.createElement('audio');sink.muted=true;sink.srcObject=new MediaStream([track]);document.body.append(sink);await sink.play();window.source=measureContext.createMediaStreamSource(sink.srcObject);window.analyser=measureContext.createAnalyser();analyser.fftSize=2048;source.connect(analyser);await measureContext.resume();}const values=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(values);return Math.sqrt(values.reduce((a,b)=>a+b*b,0)/values.length);};
    });
    const guest=await browser.newPage({viewport:{width:1280,height:1000}});guest.on('pageerror',e=>errors.push(e.message));
    await guest.addInitScript(()=>{
      navigator.mediaDevices.getUserMedia=async()=>{window.rawContext=new AudioContext();window.rawTone=rawContext.createOscillator();window.rawGain=rawContext.createGain();rawGain.gain.value=.1;rawTone.frequency.value=880;const output=rawContext.createMediaStreamDestination();output.channelCount=1;rawTone.connect(rawGain).connect(output);rawTone.start();await rawContext.resume();window.rawTrack=output.stream.getAudioTracks()[0];return output.stream;};
      navigator.mediaDevices.enumerateDevices=async()=>[];
    });
    const invitation=await mutate('/api/production/greenroom/invites',{label:'Synthetic guest audio',ttl_minutes:10});
    await guest.goto(invitation.join_url);await guest.locator('#guestName').fill('Synthetic guest audio');await guest.locator('#guestMicrophone').click();await guest.locator('#guestJoin').click();
    await until(async()=>{const s=await request('/api/production/greenroom');return s.participants.some(p=>p.name==='Synthetic guest audio'&&p.connected);},'guest connected');
    const participant=(await request('/api/production/greenroom')).participants.find(p=>p.name==='Synthetic guest audio');await mutate('/api/production/greenroom/participants/'+participant.id,{action:'admit'});
    const level=()=>receiver.evaluate(()=>level());await until(async()=>await level()>.01,'raw tone received');
    results.presets={};for(const preset of ['deep','radio','robot','megaphone','natural']){await guest.locator('#guestVoicePreset').selectOption(preset);await new Promise(r=>setTimeout(r,300));await until(async()=>await level()>.001,preset+' received');results.presets[preset]=await level();}
    await guest.locator('summary').click();await guest.locator('#guestNoiseGate').click();
    await guest.evaluate(()=>{rawGain.gain.value=0;});await until(async()=>await level()<.0001&&/Closed/.test(await guest.locator('#guestGateStatus').innerText()),'gate closes');
    const trackBefore=await receiver.evaluate(()=>received.id);
    results.cues={};for(const [id,label] of [['guestCueChime','chime'],['guestCueSuccess','success'],['guestCueBuzzer','buzzer'],['guestCueDrumroll','drumroll']]){await guest.locator('#'+id).click();await until(async()=>await level()>.001,label+' bypasses gate');results.cues[label]=true;await guest.locator('#guestSoundsStop').click();await until(async()=>await level()<.0001,label+' stops');}
    await guest.locator('#guestSoundVolume').fill('0');await guest.locator('#guestCueBuzzer').click();await new Promise(r=>setTimeout(r,200));assert.ok(await level()<.0001,'zero sound volume mutes cue');await guest.locator('#guestSoundsStop').click();await guest.locator('#guestSoundVolume').fill('50');
    const rate=16000,length=rate*2,wav=Buffer.alloc(44+length*2);wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(rate,24);wav.writeUInt32LE(rate*2,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(length*2,40);for(let i=0;i<length;i++)wav.writeInt16LE(Math.round(Math.sin(i/rate*2*Math.PI*660)*10000),44+i*2);
    await guest.locator('#guestSoundFile').setInputFiles({name:'Fixture tone.wav',mimeType:'audio/wav',buffer:wav});await until(()=>guest.getByRole('button',{name:'Play Fixture tone.wav',exact:true}).count(),'local sound loaded');await guest.getByRole('button',{name:'Play Fixture tone.wav',exact:true}).click();await until(async()=>await level()>.001,'local clip received');await guest.getByRole('button',{name:'Remove Fixture tone.wav',exact:true}).click();await until(async()=>await level()<.0001,'removal stops clip');
    assert.equal(await receiver.evaluate(()=>received.id),trackBefore,'effect and sound controls retain outgoing track');
    await guest.locator('#guestCueDrumroll').click();await guest.locator('#guestMicrophone').click();await until(()=>guest.locator('#guestCueChime').isDisabled(),'mic off disables soundboard');assert.equal(await guest.evaluate(()=>rawTrack.readyState),'ended');assert.equal(await guest.locator('#guestSoundList').innerText(),'');
    results.gateSilence=true;results.cuesBypassGate=true;results.volumeMute=true;results.localClip=true;results.stableTrack=true;results.micOffCleanup=true;
    await guest.locator('#guestLeave').click();assert.equal(await guest.locator('#guestBadge').innerText(),'LEFT THE ROOM');
    results.layouts=[];for(const theme of ['ignite','daylight'])for(const width of [390,960,1920,3840]){await guest.setViewportSize({width,height:width===3840?2160:1080});await guest.evaluate(theme=>document.documentElement.setAttribute('data-operator-skin',theme),theme);const overflow=await guest.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert.equal(overflow,false,theme+' '+width);await guest.screenshot({path:path.join(destination,`audio-${theme}-${width}.png`),fullPage:true});results.layouts.push({theme,width,overflow});}
    assert.deepEqual(errors,[]);results.pageErrors=errors;fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
