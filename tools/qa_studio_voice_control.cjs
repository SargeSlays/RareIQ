// Actual served UI + offline synthetic AudioWorklet input. No device or production writes.
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
// Explicit synthetic-fixture mode only; ordinary QA never writes audio bytes.
const syntheticWavPath=process.env.RAREIQ_QA_VOICE_WAV;
const syntheticWav=syntheticWavPath?fs.readFileSync(syntheticWavPath):null;
const commandMode=process.env.RAREIQ_QA_VOICE_MODE==='ptt'?'ptt':'wake';
if(syntheticWav){assert.ok(syntheticWav.length<=2*1024*1024,'Synthetic WAV fixture must be at most 2 MiB');assert.equal(syntheticWav.toString('ascii',0,4),'RIFF');assert.equal(syntheticWav.toString('ascii',8,12),'WAVE');}
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080}}),requests=[],blocked=[],errors=[];let startPayload=null;
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.pathname.startsWith('/api/production/voice/')){
        if(url.pathname.endsWith('/start'))startPayload=request.postDataJSON();
        requests.push({path:url.pathname,query:Object.fromEntries(url.searchParams),bytes:request.postDataBuffer()?.length||0});
        if(syntheticWav&&url.pathname.endsWith('/audio')){fs.mkdirSync('.tmp/refinish/voice',{recursive:true});fs.writeFileSync('.tmp/refinish/voice/captured-synthetic-utterance.wav',request.postDataBuffer());}
        const result=url.pathname.endsWith('/start')?{ok:true,state:'armed',session_id:'qa-offline',practice:true,mode:commandMode,ptt_down:false}:url.pathname.endsWith('/stop')?{ok:true,state:'stopped'}:{ok:true,state:'armed',practice:true,mode:commandMode,ptt_down:commandMode==='ptt',last_result:{state:'validated',message:'QA fixture: Practice command validated; no action taken.'}};
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
      }
      if(!['GET','HEAD'].includes(request.method())){blocked.push(url.pathname);return route.abort();}
      return route.continue();
    });
    await page.addInitScript(()=>{window.mediaStarts=0;navigator.mediaDevices.getUserMedia=async()=>{window.mediaStarts++;throw Error('QA blocks microphone capture')};HTMLMediaElement.prototype.play=function(){window.mediaStarts++;return Promise.resolve()};});
    await page.goto(origin+'/control?workspace=voice-mod&voice-qa=1',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.StudioVoiceControl);
    await page.locator('.nav-button[data-target="voice-mod"]').click();
    assert.equal(await page.locator('#studioVoiceStart').isDisabled(),true);assert.equal(await page.locator('#studioVoicePractice').isChecked(),true);
    assert.equal(await page.locator('#studioVoiceMode').inputValue(),'wake');await page.locator('#studioVoiceMode').selectOption(commandMode);
    await page.evaluate(async bytes=>{
      const context=new OfflineAudioContext(1,bytes?384000:96000,48000);
      let buffer;
      if(bytes){
        const decoded=await context.decodeAudioData(new Uint8Array(bytes).buffer);
        if(decoded.duration>6)throw Error('Synthetic spoken fixture must be at most six seconds.');
        buffer=context.createBuffer(1,decoded.length+48000,48000);const samples=buffer.getChannelData(0);
        for(let channel=0;channel<decoded.numberOfChannels;channel++){const input=decoded.getChannelData(channel);for(let i=0;i<input.length;i++)samples[12000+i]+=input[i]/decoded.numberOfChannels;}
      }else{
        buffer=context.createBuffer(1,96000,48000);const samples=buffer.getChannelData(0);
        for(let i=12000;i<36000;i++)samples[i]=.1*Math.sin(i*2*Math.PI*330/48000);
      }
      const source=context.createBufferSource();source.buffer=buffer;source.start();
      Object.defineProperty(context,'state',{get:()=> 'running'});
      window.offlineVoiceQA={context,source};
      voiceModState={...voiceModState,active:true,context,source,inputStream:{getAudioTracks:()=>[{readyState:'live'}]}};
      setVoiceModStatus('live','Synthetic offline QA input');
    },syntheticWav?Array.from(syntheticWav):null);
    await page.locator('#studioVoiceStart').click();
    await page.waitForFunction(()=>StudioVoiceControl.status().state==='armed');
    assert.equal(await page.locator('#studioVoicePractice').isDisabled(),true);
    assert.equal(await page.locator('#studioVoiceMode').isDisabled(),true);assert.equal(startPayload.mode,commandMode);
    if(commandMode==='ptt')assert.match(await page.locator('#studioVoiceStatus').textContent(),/Hold Ctrl\+Alt\+V/);
    await page.evaluate(()=>offlineVoiceQA.context.startRendering());
    await page.waitForFunction(()=>document.getElementById('studioVoiceOutcome').textContent.includes('QA fixture'));
    const audio=requests.filter(request=>request.path.endsWith('/audio'));assert.equal(audio.length,1);assert.ok(audio[0].bytes>44&&audio[0].bytes<=192044);assert.equal(audio[0].query.sequence,'1');assert.equal(audio[0].query.session_id,'qa-offline');
    assert.ok(Number(audio[0].query.started_at)<Number(audio[0].query.ended_at));if(commandMode==='ptt')assert.equal(await page.evaluate(()=>StudioVoiceControl.status().ptt_down),true);
    await page.locator('#studioVoiceStop').click();await page.waitForFunction(()=>StudioVoiceControl.status().state==='stopped');
    assert.equal(await page.evaluate(()=>voiceModState.active),true);assert.equal(await page.evaluate(()=>mediaStarts),0);
    await page.waitForFunction(()=>!document.getElementById('instantSplash')||getComputedStyle(document.getElementById('instantSplash')).visibility==='hidden');
    fs.mkdirSync('.tmp/refinish/voice',{recursive:true});
    for(const [skin,width,height] of [['ignite',1920,1080],['daylight',1366,768],['daylight',720,900]]){
      await page.setViewportSize({width,height});await page.evaluate(s=>applyStudioTheme(s,false),skin);
      await page.locator('#studioVoiceControls').scrollIntoViewIfNeeded();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.locator('#studioVoiceControls').screenshot({path:`.tmp/refinish/voice/${skin}-${width}.png`});
    }
    assert.deepEqual(errors,[]);assert.equal(blocked.some(path=>!['/api/camera/start','/api/recognition/set-context','/api/output/soundboard'].includes(path)),false);
    const report={layer:'Served Edge UI + offline synthetic AudioWorklet + inert host-response fixtures',mode:commandMode,startPayload,input:syntheticWav?'provided synthetic WAV':'generated synthetic tone',capturedSyntheticUtterance:syntheticWav?'.tmp/refinish/voice/captured-synthetic-utterance.wav':null,mediaStarts:0,actualVoiceRequests:0,requests,blocked};
    fs.writeFileSync('.tmp/refinish/voice/qa-results.json',JSON.stringify(report,null,2));fs.writeFileSync(`.tmp/refinish/voice/qa-results-${commandMode}.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
