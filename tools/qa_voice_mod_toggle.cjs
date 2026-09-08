// Served Edge controls with synthetic media objects; no capture, playback, or API writes.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080}}),blocked=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/**',route=>{if(!['GET','HEAD'].includes(route.request().method())){blocked.push(new URL(route.request().url()).pathname);return route.abort();}return route.continue();});
    await page.addInitScript(()=>{
      const pending=[],streams=[],contexts=[];window.toggleQA={pending,streams,contexts,playbackCalls:0};
      navigator.mediaDevices.enumerateDevices=async()=>[{kind:'audioinput',deviceId:'',label:'Synthetic QA input'}];
      navigator.mediaDevices.getUserMedia=()=>new Promise((resolve,reject)=>pending.push({resolve,reject}));
      HTMLMediaElement.prototype.play=function(){toggleQA.playbackCalls++;return Promise.resolve();};
      const track=()=>({readyState:'live',stopped:false,stop(){this.stopped=true;this.readyState='ended';},addEventListener(){}});
      const stream=()=>{const t=track(),s={track:t,getTracks:()=>[t],getAudioTracks:()=>[t]};streams.push(s);return s;};
      toggleQA.grant=index=>pending[index].resolve(stream());
      window.AudioContext=class{
        constructor(){this.state='running';this.destination={};contexts.push(this);}
        async resume(){} async close(){this.state='closed';}
        node(){return {connect(){},disconnect(){},gain:{value:1},getByteTimeDomainData(values){values.fill(128);}};}
        createGain(){return this.node();}createMediaStreamSource(){return this.node();}createAnalyser(){return this.node();}
        createMediaStreamDestination(){return {...this.node(),stream:stream()};}
      };
    });
    await page.goto(origin+'/control?workspace=voice-mod&toggle-qa=1',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.StudioVoiceControl);
    await page.locator('.nav-button[data-target="voice-mod"]').click();
    await page.waitForFunction(()=>!document.getElementById('instantSplash')||getComputedStyle(document.getElementById('instantSplash')).visibility==='hidden');
    await page.addStyleTag({content:'#notificationStack,#operatorToast { visibility:hidden!important; }'});
    const button=page.locator('#voiceModStart');await page.evaluate(()=>{window.originalVoiceToggle=document.getElementById('voiceModStart');});
    assert.equal(await page.locator('#voiceModStop').count(),0);assert.equal(await button.textContent(),'Start');
    await button.click();assert.equal(await button.textContent(),'Cancel');assert.equal(await button.isEnabled(),true);
    await button.click();assert.equal(await button.textContent(),'Start');assert.equal(await page.evaluate(()=>toggleQA.pending.length),1);
    await page.evaluate(()=>toggleQA.grant(0));await page.waitForFunction(()=>toggleQA.streams[0].track.stopped);assert.equal(await page.evaluate(()=>toggleQA.contexts.length),0);
    await button.click();await page.evaluate(()=>toggleQA.grant(1));await page.waitForFunction(()=>voiceModState.active);
    assert.equal(await button.textContent(),'Stop');assert.equal(await button.getAttribute('aria-label'),'Stop Voice Mod');
    fs.mkdirSync('.tmp/refinish/voice-toggle',{recursive:true});
    for(const skin of ['ignite','daylight']){await page.evaluate(s=>applyStudioTheme(s,false),skin);await page.waitForTimeout(200);await page.locator('.voice-mod-control-card').screenshot({path:`.tmp/refinish/voice-toggle/${skin}-active.png`});}
    await button.click();assert.equal(await button.textContent(),'Start');assert.equal(await page.evaluate(()=>toggleQA.streams.every(s=>s.track.stopped)),true);
    await button.click();await page.evaluate(()=>toggleQA.pending[2].reject(Error('Synthetic permission denial')));await page.waitForFunction(()=>document.getElementById('voiceModState').dataset.state==='error');assert.equal(await button.textContent(),'Start');
    await page.locator('.nav-button[data-target="broadcast"]').click();await page.getByRole('button',{name:/^Session tools/}).click();
    const drawer=page.getByRole('dialog',{name:'Session tools'});await drawer.getByRole('button',{name:'Clear all tools',exact:true}).click();await drawer.getByLabel('Voice studio',{exact:true}).check();await drawer.getByLabel('Voice studio position',{exact:true}).selectOption('right');await drawer.getByRole('button',{name:'Close',exact:true}).click();
    assert.equal(await page.locator('.studio-dock-tool #voiceModStart').count(),1);assert.equal(await page.evaluate(()=>originalVoiceToggle===document.getElementById('voiceModStart')),true);
    await button.click();assert.equal(await button.textContent(),'Cancel');await button.click();await page.evaluate(()=>toggleQA.grant(3));await page.waitForFunction(()=>toggleQA.streams.at(-1).track.stopped);
    await page.locator('.voice-mod-control-card').scrollIntoViewIfNeeded();assert.equal(await page.locator('.voice-mod-control-card').evaluate(el=>el.scrollWidth>el.clientWidth+2),false);
    await page.locator('.voice-mod-control-card').screenshot({path:'.tmp/refinish/voice-toggle/daylight-dock-idle.png'});
    await page.locator('.nav-button[data-target="voice-mod"]').click();assert.equal(await page.evaluate(()=>originalVoiceToggle===document.getElementById('voiceModStart')),true);
    const final=await page.evaluate(()=>({requests:toggleQA.pending.length,contexts:toggleQA.contexts.length,active:voiceModState.active,allTracksStopped:toggleQA.streams.every(s=>s.track.stopped),allContextsClosed:toggleQA.contexts.every(c=>c.state==='closed'),playbackCalls:toggleQA.playbackCalls}));
    assert.deepEqual(final,{requests:4,contexts:1,active:false,allTracksStopped:true,allContextsClosed:true,playbackCalls:0});assert.deepEqual(errors,[]);
    assert.equal(blocked.some(path=>!['/api/camera/start','/api/recognition/set-context','/api/output/soundboard'].includes(path)),false);
    const report={layer:'Served Edge + synthetic media objects; all actual API writes blocked',singleToggle:true,originalNodeRetained:true,permissionCancellation:'passed',latePermissionRelease:'passed',activeStop:'passed',failureRecovery:'passed',dockCancellation:'passed',actualMediaStarts:0,...final,blocked};
    fs.writeFileSync('.tmp/refinish/voice-toggle/qa-results.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
