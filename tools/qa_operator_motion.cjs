// Actual served Edge UI; isolated preferences, no API writes or device starts.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try {
    const context=await browser.newContext({viewport:{width:1920,height:1080}}),page=await context.newPage(),errors=[],blocked=[];
    page.on('pageerror',e=>errors.push(e.message));
    await context.route('**/api/**',route=>{
      const request=route.request();
      if(!['GET','HEAD'].includes(request.method())){blocked.push(new URL(request.url()).pathname);return route.abort();}
      return route.continue();
    });
    await context.addInitScript(()=>{
      window.mediaStarts=0;
      navigator.mediaDevices.getUserMedia=async()=>{window.mediaStarts++;throw Error('QA blocks media capture');};
      HTMLMediaElement.prototype.play=function(){window.mediaStarts++;return Promise.resolve();};
    });
    await page.goto(origin+'/control?workspace=studio&motion-qa=1',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>window.StudioMotion?.status());
    await page.locator('.nav-button[data-target="settings"]').click();
    await page.locator('#settingsTabAppearance').click();
    const choices=page.getByRole('radiogroup',{name:'Motion intensity'});
    await choices.getByRole('radio',{name:'Studio',exact:true}).click();
    assert.equal(await page.evaluate(()=>StudioMotion.status().preferred),'studio');
    assert.match(await page.locator('#studioMotionStatus').textContent(),/saved on this device/);
    await page.keyboard.press('ArrowRight');assert.equal(await page.evaluate(()=>StudioMotion.status().preferred),'reduced');
    await page.keyboard.press('End');assert.equal(await page.evaluate(()=>StudioMotion.status().preferred),'off');
    await page.keyboard.press('Home');assert.equal(await page.evaluate(()=>StudioMotion.status().preferred),'expressive');
    // Inert fixtures exercise native activation in the actual app; no production command runs.
    await page.evaluate(()=>{
      const fixture=document.createElement('section');fixture.id='qaMotionControls';fixture.setAttribute('aria-label','QA inert controls');
      const button=document.createElement('button');button.id='qaMotionButton';button.type='button';button.textContent='QA inert scene';
      window.motionFixtureClicks=0;button.addEventListener('click',()=>window.motionFixtureClicks++);fixture.append(button);
      const busy=document.createElement('button');busy.id='qaMotionBusy';busy.type='button';busy.textContent='QA busy action';busy.addEventListener('click',()=>{busy.disabled=true;});fixture.append(busy);
      const protectedBranch=document.createElement('div');protectedBranch.setAttribute('data-pp-motion-exclude','');const protectedButton=document.createElement('button');protectedButton.id='qaMotionProtected';protectedButton.textContent='Protected';protectedBranch.append(protectedButton);fixture.append(protectedBranch);
      const artworkButton=document.createElement('button');artworkButton.id='qaMotionArtwork';artworkButton.append(document.createElement('img'));fixture.append(artworkButton);
      document.getElementById('settingsAppearance').prepend(fixture);
    });
    await page.waitForFunction(()=>document.getElementById('qaMotionButton').hasAttribute('data-ppm-ripple'));
    const buttonProof=await page.evaluate(()=>{
      const button=document.getElementById('qaMotionButton'),before=button.getBoundingClientRect().toJSON();
      button.click();button.click();const ripples=button.querySelectorAll('.ppm-ripple').length,after=button.getBoundingClientRect().toJSON();
      button.disabled=true;button.click();
      const busy=document.getElementById('qaMotionBusy');busy.click();busy.click();
      return {clicks:motionFixtureClicks,ripples,busyRipples:busy.querySelectorAll('.ppm-ripple').length,before,after,protected:document.getElementById('qaMotionProtected').hasAttribute('data-ppm-ripple'),artwork:document.getElementById('qaMotionArtwork').hasAttribute('data-ppm-ripple'),actualControls:['productionReplayMark','showStartButton','obsStreamToggle'].every(id=>document.getElementById(id).hasAttribute('data-ppm-ripple'))};
    });
    assert.equal(buttonProof.clicks,2);assert.equal(buttonProof.ripples,2);assert.equal(buttonProof.busyRipples,1);assert.deepEqual(buttonProof.before,buttonProof.after);assert.equal(buttonProof.protected,false);assert.equal(buttonProof.artwork,false);assert.equal(buttonProof.actualControls,true);
    await page.evaluate(()=>document.getElementById('qaMotionControls').remove());
    const limiter=await page.evaluate(()=>{const before=obsState;renderObsStatus({...before,streaming:true});const limited=StudioMotion.status();renderObsStatus({...before,streaming:false});const restored=StudioMotion.status();return {limited,restored};});
    assert.equal(limiter.limited.effective,'studio');assert.equal(limiter.limited.preferred,'expressive');assert.equal(limiter.restored.effective,'expressive');
    await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>document.body.offsetHeight);await page.waitForFunction(()=>StudioMotion.status().effective==='reduced');
    await page.emulateMedia({reducedMotion:'no-preference'});await page.evaluate(()=>document.body.offsetHeight);await page.waitForFunction(()=>StudioMotion.status().effective==='expressive');
    const unchanged=await page.evaluate(()=>{
      const nodes=Array.from(document.querySelectorAll('video,canvas,iframe'));
      const field=document.getElementById('sargeAdvisorQuestion');field.value='Unsaved motion QA';
      const appearance=localStorage.getItem('rareiq.studiox.appearance.v2');
      for(let i=0;i<20;i++)document.querySelectorAll('[data-studio-motion]')[i%4].click();
      return {nodes:nodes.every(node=>node.isConnected),edit:field.value,appearance:appearance===localStorage.getItem('rareiq.studiox.appearance.v2'),mediaStarts};
    });
    assert.equal(unchanged.nodes,true);assert.equal(unchanged.edit,'Unsaved motion QA');assert.equal(unchanged.appearance,true);assert.equal(unchanged.mediaStarts,0);
    await choices.getByRole('radio',{name:'Studio',exact:true}).click();await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.StudioMotion?.status());
    assert.equal(await page.evaluate(()=>StudioMotion.status().preferred),'studio');
    await page.locator('.nav-button[data-target="settings"]').click();await page.locator('#settingsTabAppearance').click();
    await page.waitForFunction(()=>!document.getElementById('instantSplash')||getComputedStyle(document.getElementById('instantSplash')).visibility==='hidden');
    await page.evaluate(()=>document.querySelectorAll('.riq-notification').forEach(node=>dismissNotification(node,{immediate:true})));
    fs.mkdirSync('.tmp/refinish/motion',{recursive:true});
    const results=[];
    for(const skin of ['ignite','afterdark','voltage','ember','daylight']){
      await page.evaluate(skin=>applyStudioTheme(skin,false),skin);
      await page.waitForTimeout(120);
      assert.equal(await page.evaluate(()=>StudioMotion.status().preferred),'studio');
      await page.locator('#settingsAppearance').screenshot({path:`.tmp/refinish/motion/${skin}-appearance.png`});
      results.push({skin,width:1920,overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
    }
    for(const skin of ['ignite','daylight'])for(const [width,height] of [[1366,768],[3840,2160],[720,900]]){
      await page.setViewportSize({width,height});await page.evaluate(s=>applyStudioTheme(s,false),skin);await page.waitForTimeout(100);
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert.equal(overflow,false);
      if(width===720){
        await page.locator('#studioMotionStatus').evaluate(node=>node.scrollIntoView({block:'center'}));
        const clear=await page.evaluate(()=>{const status=document.getElementById('studioMotionStatus').getBoundingClientRect(),nav=document.querySelector('.ui4-mobile-action-region')?.getBoundingClientRect();return !nav||nav.height===0||status.bottom<=nav.top;});
        assert.equal(clear,true,'Motion status must scroll clear of fixed mobile navigation');
      }
      await page.locator('#settingsAppearance').screenshot({path:`.tmp/refinish/motion/${skin}-${width}-appearance.png`});results.push({skin,width,overflow});
    }
    await page.setViewportSize({width:1920,height:1080});
    // Test denied persistence after startup without touching production settings.
    await page.evaluate(()=>{window.realSetItem=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key==='producerplease.operator.motion.v1')throw Error('QA denied motion preference');return realSetItem.call(this,key,value)};});
    await choices.getByRole('radio',{name:'Off',exact:true}).click();assert.equal(await page.evaluate(()=>StudioMotion.status().effective),'off');assert.match(await page.locator('#studioMotionStatus').textContent(),/not saved/);
    assert.deepEqual(errors,[]);
    assert.equal(await page.evaluate(()=>mediaStarts),0);
    assert.equal(blocked.some(path=>!['/api/camera/start','/api/recognition/set-context','/api/output/soundboard'].includes(path)),false);
    const report={runtime:'actual served Edge',checks:['keyboard','persistence','blocked storage','skin independence','original media nodes and unsaved edits','OBS status limiter','OS reduced motion','dynamic production button markers, stationary bounds, one original handler, disabled guard and exclusions'],buttonProof,mediaStarts:0,blockedWrites:[...new Set(blocked)],results};
    fs.writeFileSync('.tmp/refinish/motion/qa-results.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
