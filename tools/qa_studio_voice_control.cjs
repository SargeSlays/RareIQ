// Actual served UI + offline synthetic AudioWorklet input. No device or production writes.
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
// Explicit synthetic-fixture mode only; ordinary QA never writes audio bytes.
const syntheticWavPath=process.env.RAREIQ_QA_VOICE_WAV;
const syntheticWav=syntheticWavPath?fs.readFileSync(syntheticWavPath):null;
const commandMode=process.env.RAREIQ_QA_VOICE_MODE==='ptt'?'ptt':'wake';
const openFlow=process.env.RAREIQ_QA_OPEN_FLOW==='true';
if(syntheticWav){assert.ok(syntheticWav.length<=2*1024*1024,'Synthetic WAV fixture must be at most 2 MiB');assert.equal(syntheticWav.toString('ascii',0,4),'RIFF');assert.equal(syntheticWav.toString('ascii',8,12),'WAVE');}
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080}}),requests=[],blocked=[],errors=[];let startPayload=null,audioReceived=0;
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.pathname.startsWith('/api/production/voice/')){
        if(url.pathname.endsWith('/start'))startPayload=request.postDataJSON();
        requests.push({path:url.pathname,query:Object.fromEntries(url.searchParams),bytes:request.postDataBuffer()?.length||0});
        if(syntheticWav&&url.pathname.endsWith('/audio')){fs.mkdirSync('.tmp/refinish/voice',{recursive:true});fs.writeFileSync('.tmp/refinish/voice/captured-synthetic-utterance.wav',request.postDataBuffer());}
        if(url.pathname.endsWith('/audio'))audioReceived++;
        const result=url.pathname.endsWith('/start')?{ok:true,state:'armed',session_id:'qa-offline',practice:true,mode:commandMode,ptt_down:false}:url.pathname.endsWith('/stop')?{ok:true,state:'stopped'}:{ok:true,state:'armed',practice:true,mode:commandMode,ptt_down:commandMode==='ptt',last_result:audioReceived?{state:'validated',message:'QA fixture: Practice command validated; no action taken.',at:1700000000}:null};
        result.diagnostics={shortcut_presses:commandMode==='ptt'?audioReceived:0,audio_sequence:audioReceived};
        result.open_flow=url.pathname.endsWith('/stop')?false:openFlow;
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
      }
      if(!['GET','HEAD'].includes(request.method())){blocked.push(url.pathname);return route.abort();}
      return route.continue();
    });
    await page.addInitScript(()=>{window.mediaStarts=0;navigator.mediaDevices.getUserMedia=async()=>{window.mediaStarts++;throw Error('QA blocks microphone capture')};HTMLMediaElement.prototype.play=function(){window.mediaStarts++;return Promise.resolve()};});
    await page.goto(origin+'/control?workspace=voice-mod&voice-qa=1',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.StudioVoiceControl);
    await page.locator('.nav-button[data-target="voice-mod"]').click();
    await page.evaluate(()=>{window.voiceConsoleNodes=['studioVoiceControls','studioVoiceStart','studioVoiceStop','studioVoiceMode','studioVoicePractice','studioVoiceOpenFlow','studioVoiceWakeSummary','voiceModInput','voiceModStart'].map(id=>document.getElementById(id));});
    assert.equal(await page.locator('#studioVoiceStart').isDisabled(),true);assert.equal(await page.locator('#studioVoicePractice').isChecked(),true);
    assert.equal(await page.locator('#studioVoiceMode').inputValue(),'wake');await page.locator('#studioVoiceMode').selectOption(commandMode);
    assert.equal(await page.locator('#studioVoiceOpenFlow').isChecked(),false);
    if(openFlow)await page.locator('#studioVoiceOpenFlow').check();
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
    assert.equal(startPayload.open_flow,openFlow);assert.equal(await page.locator('#studioVoiceOpenFlow').isDisabled(),true);
    assert.match(await page.locator('#studioVoiceWakeSummary').textContent(),openFlow?/Open flow · no wake phrase/:/Wake phrase required/);
    if(commandMode==='ptt')assert.match(await page.locator('#studioVoiceStatus').textContent(),/Hold Ctrl\+Alt\+V/);
    await page.evaluate(()=>offlineVoiceQA.context.startRendering());
    await page.waitForFunction(()=>document.getElementById('studioVoiceOutcome').textContent.includes('QA fixture'));
    assert.match(await page.locator('#studioVoiceDiagnostics').textContent(),/Audio received: 1/);
    assert.doesNotMatch(await page.locator('#studioVoiceDiagnostics').textContent(),/Last result: none yet/);
    const audio=requests.filter(request=>request.path.endsWith('/audio'));assert.equal(audio.length,1);assert.ok(audio[0].bytes>44&&audio[0].bytes<=192044);assert.equal(audio[0].query.sequence,'1');assert.equal(audio[0].query.session_id,'qa-offline');
    assert.ok(Number(audio[0].query.started_at)<Number(audio[0].query.ended_at));if(commandMode==='ptt')assert.equal(await page.evaluate(()=>StudioVoiceControl.status().ptt_down),true);
    await page.locator('#studioVoiceStop').click();await page.waitForFunction(()=>StudioVoiceControl.status().state==='stopped');
    assert.equal(await page.locator('#studioVoiceOpenFlow').isChecked(),false);assert.equal(await page.locator('#studioVoiceOpenFlow').isDisabled(),false);
    assert.equal(await page.evaluate(()=>voiceModState.active),true);assert.equal(await page.evaluate(()=>mediaStarts),0);
    await page.waitForFunction(()=>!document.getElementById('instantSplash')||getComputedStyle(document.getElementById('instantSplash')).visibility==='hidden');
    fs.mkdirSync('.tmp/refinish/voice',{recursive:true});
    const layouts=[];
    for(const skin of ['ignite','daylight'])for(const [width,height] of [[1920,1080],[3840,2160],[1366,768],[720,900]]){
      await page.setViewportSize({width,height});await page.evaluate(s=>applyStudioTheme(s,false),skin);
      await page.locator('#studioVoiceControls').scrollIntoViewIfNeeded();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      const layout=await page.locator('#studioVoiceControls').evaluate(console=>({first:console.parentElement.firstElementChild===console,fullWidth:Math.abs(console.getBoundingClientRect().width-console.parentElement.getBoundingClientRect().width)<3,overflow:console.scrollWidth>console.clientWidth+2,detailsClosed:!console.querySelector('details').open}));assert.deepEqual(layout,{first:true,fullWidth:true,overflow:false,detailsClosed:true});layouts.push({skin,width,...layout});
      await page.locator('#studioVoiceControls').screenshot({path:`.tmp/refinish/voice/${skin}-${width}.png`});
    }
    await page.setViewportSize({width:1920,height:1080});await page.locator('.nav-button[data-target="broadcast"]').click();
    const drawer=page.getByRole('dialog',{name:'Session tools'});await page.getByRole('button',{name:/^Session tools/}).click();await drawer.getByRole('button',{name:'Clear all tools',exact:true}).click();await drawer.getByLabel('Voice studio',{exact:true}).check();await drawer.getByLabel('Voice studio position',{exact:true}).selectOption('right');await drawer.getByRole('button',{name:'Close',exact:true}).click();
    const dock=page.locator('.studio-dock-tool .voice-mod-shell');assert.equal(await dock.isVisible(),true);
    await page.locator('#studioVoiceControls').scrollIntoViewIfNeeded();
    const dockBounds=await page.locator('#studioVoiceControls').evaluate(console=>({width:console.clientWidth,overflow:console.scrollWidth>console.clientWidth+2}));assert.equal(dockBounds.overflow,false);assert.ok(dockBounds.width<700);
    assert.equal(await page.evaluate(()=>voiceConsoleNodes.every(node=>node===document.getElementById(node.id))),true);assert.equal(requests.filter(r=>r.path.endsWith('/start')).length,1);
    await page.locator('#studioVoiceControls').screenshot({path:'.tmp/refinish/voice/daylight-narrow-dock.png'});
    await page.locator('.nav-button[data-target="voice-mod"]').click();assert.equal(await page.evaluate(()=>voiceConsoleNodes.every(node=>node===document.getElementById(node.id))),true);assert.equal(await page.evaluate(()=>mediaStarts),0);
    assert.deepEqual(errors,[]);assert.equal(blocked.some(path=>!['/api/camera/start','/api/recognition/set-context','/api/output/soundboard'].includes(path)),false);
    const report={layer:'Served Edge UI + offline synthetic AudioWorklet + inert host-response fixtures',mode:commandMode,startPayload,input:syntheticWav?'provided synthetic WAV':'generated synthetic tone',capturedSyntheticUtterance:syntheticWav?'.tmp/refinish/voice/captured-synthetic-utterance.wav':null,mediaStarts:0,actualVoiceRequests:0,originalNodesRetained:true,layouts,dockBounds,requests,blocked};
    fs.writeFileSync(`.tmp/refinish/voice/qa-results-${commandMode}-${openFlow?'open':'guarded'}.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close()}
})().catch(error=>{console.error(error.stack);process.exitCode=1});
