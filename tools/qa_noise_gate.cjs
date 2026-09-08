// Real served AudioWorklet with offline synthetic audio; no physical capture or playback.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',route=>['GET','HEAD'].includes(route.request().method())?route.continue():route.abort());
    await page.routeWebSocket('**',socket=>socket.close());
    await page.addInitScript(()=>{
      navigator.mediaDevices.getUserMedia=async()=>{throw Error('Physical capture prohibited in QA');};
      navigator.mediaDevices.enumerateDevices=async()=>[];
      HTMLMediaElement.prototype.play=()=>Promise.resolve();
    });
    await page.goto('http://127.0.0.1:9040/control?workspace=voice-mod&gate-qa=1',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.StudioNoiseGate&&typeof updateVoiceModGate==='function');
    await page.locator('.nav-button[data-target="voice-mod"]').click();
    await page.waitForFunction(()=>!document.getElementById('instantSplash')||getComputedStyle(document.getElementById('instantSplash')).visibility==='hidden');
    const enabled=page.locator('#voiceModGateEnabled'),threshold=page.locator('#voiceModGateThreshold');
    assert.equal(await enabled.isChecked(),false);assert.equal(await threshold.isDisabled(),true);
    await enabled.check();await threshold.fill('-40');await threshold.dispatchEvent('input');
    const rendered=await page.evaluate(async()=>{
      async function render(enabled){
        const context=new OfflineAudioContext(2,48000*3,48000),buffer=context.createBuffer(2,48000*3,48000);
        for(let c=0;c<2;c++)for(let i=0;i<buffer.length;i++)buffer.getChannelData(c)[i]=Math.sin(2*Math.PI*440*i/48000)*(i>=24000&&i<48000?.1:.001)*(c?-1:1);
        const source=context.createBufferSource();source.buffer=buffer;
        const gate=StudioNoiseGate.create(context,source,context.destination,()=>{});
        await gate.configure({enabled,thresholdDb:-40});source.start();const result=await context.startRendering();gate.close();
        const samples=result.getChannelData(0),rms=(a,b)=>Math.sqrt(samples.slice(a*48000,b*48000).reduce((sum,x)=>sum+x*x,0)/((b-a)*48000));
        let stereoError=0;for(let i=0;i<samples.length;i++)stereoError=Math.max(stereoError,Math.abs(samples[i]+result.getChannelData(1)[i]));
        return {quiet:rms(.1,.4),voice:rms(.7,.9),tail:rms(2.5,2.9),stereoError};
      }
      return {on:await render(true),off:await render(false)};
    });
    assert.ok(rendered.on.quiet<.000001);assert.ok(rendered.on.voice>.06);assert.ok(rendered.on.tail<.000001);assert.ok(rendered.off.quiet>.0006);assert.equal(rendered.on.stereoError,0);
    await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>document.getElementById('voiceModGateEnabled')?.checked);
    assert.equal(await threshold.inputValue(),'-40');await enabled.uncheck();assert.equal(await threshold.isDisabled(),true);
    await page.waitForFunction(()=>!document.getElementById('instantSplash')||getComputedStyle(document.getElementById('instantSplash')).visibility==='hidden');
    await page.addStyleTag({content:'#notificationStack,#operatorToast { visibility:hidden!important; }'});
    fs.mkdirSync('.tmp/refinish/noise-gate',{recursive:true});
    for(const [width,height] of [[1920,1080],[3840,2160],[1100,800]])for(const theme of ['ignite','daylight']){
      await page.setViewportSize({width,height});await page.evaluate(theme=>applyStudioTheme(theme,false),theme);
      const card=page.locator('.voice-mod-control-card');await card.scrollIntoViewIfNeeded();
      assert.equal(await card.evaluate(el=>el.scrollWidth>el.clientWidth+2),false);
      await card.screenshot({path:`.tmp/refinish/noise-gate/${theme}-${width}.png`});
    }
    assert.deepEqual(errors,[]);const report={layer:'Served Edge AudioWorklet, offline synthetic stereo audio',rendered,preferences:'persist across reload',themes:['ignite','daylight'],viewports:[1920,3840,1100],physicalCapture:false,playback:false};
    fs.writeFileSync('.tmp/refinish/noise-gate/results.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
