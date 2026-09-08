// Local Edge QA against the running app. Production writes are blocked by the test.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/production/**',route=>{if(!['GET','HEAD'].includes(route.request().method())){errors.push('Unexpected production write blocked');return route.abort();}return route.continue();});
    await page.goto(origin+'/control?workspace=studio&session-tools=20260908-1');await page.waitForSelector('[data-studio-docks="ready"]');await page.waitForTimeout(300);
    await page.evaluate(()=>{window.heldNodes=['productionProgramPreview','productionTransition','productionSessionName'].map(id=>document.getElementById(id));document.getElementById('productionSessionName').value='Unsaved studio draft';});
    const drawer=page.getByRole('dialog',{name:'Session tools'}),tools=page.getByRole('button',{name:/^Session tools/});
    await tools.click();await drawer.getByRole('button',{name:'Clear all tools',exact:true}).click();assert.equal(await drawer.locator('input[type=checkbox]:checked').count(),0);
    await drawer.getByLabel('Production Scenes',{exact:true}).check();await drawer.getByLabel('Soundboard',{exact:true}).check();await drawer.getByLabel('Production Scenes position',{exact:true}).selectOption('left');
    await drawer.getByLabel('New tool set name').fill('Project Alpha');await drawer.getByRole('button',{name:'Save as new',exact:true}).click();const alpha=await drawer.getByLabel('Saved tool set').inputValue();
    await drawer.getByRole('button',{name:'Select all tools',exact:true}).click();const count=await drawer.locator('input[type=checkbox]').count();assert.equal(await drawer.locator('input[type=checkbox]:checked').count(),count);
    await drawer.getByLabel('New tool set name').fill('Project Beta');await drawer.getByRole('button',{name:'Save as new',exact:true}).click();const beta=await drawer.getByLabel('Saved tool set').inputValue();assert.notEqual(alpha,beta);
    await drawer.getByLabel('Saved tool set').selectOption(alpha);assert.equal(await drawer.locator('input[type=checkbox]:checked').count(),2);
    await drawer.getByLabel('Find session tools').fill('no-tool-matches-this');assert.equal(await drawer.getByText('No tools match your search.').isVisible(),true);await drawer.getByLabel('Find session tools').fill('');
    await page.keyboard.press('Escape');assert.equal(await drawer.isVisible(),false);assert.equal(await tools.evaluate(e=>document.activeElement===e),true);
    assert.equal(await page.getByLabel('Open session workspace').locator('option').count(),2);
    await page.getByRole('button',{name:'Options for Production Scenes',exact:true}).click();assert.equal(await drawer.getByLabel('Production Scenes position',{exact:true}).evaluate(e=>document.activeElement===e),true);
    const popupReady=page.waitForEvent('popup');await drawer.getByRole('button',{name:'Pop out Production Scenes',exact:true}).click();const popup=await popupReady;await popup.waitForSelector('.production-scenes');await popup.getByRole('button',{name:'Return to main studio'}).click();await page.waitForFunction(()=>!document.getElementById('studioDockLibrary').open);assert.equal(await page.getByRole('button',{name:'Options for Production Scenes',exact:true}).evaluate(e=>e===document.activeElement),true);await popup.close();
    assert.equal(await page.evaluate(()=>heldNodes.every(node=>node===document.getElementById(node.id))&&document.getElementById('productionSessionName').value==='Unsaved studio draft'),true);
    await page.reload();await page.waitForSelector('[data-studio-docks="ready"]');await tools.click();assert.equal(await drawer.getByLabel('Saved tool set').inputValue(),alpha);assert.equal(await drawer.locator('input[type=checkbox]:checked').count(),2);
    await drawer.getByLabel('Saved tool set').selectOption(beta);assert.equal(await drawer.locator('input[type=checkbox]:checked').count(),count);
    await drawer.getByRole('button',{name:'Reset layout',exact:true}).click();assert.equal(await drawer.getByRole('button',{name:'Save changes',exact:true}).isEnabled(),true);await drawer.getByRole('button',{name:'Save changes',exact:true}).click();assert.equal(await drawer.getByRole('button',{name:'Save changes',exact:true}).isEnabled(),false);await drawer.getByRole('button',{name:'Close',exact:true}).click();
    for(const view of ['destinations','show','graphics','insights','history','setup','live']){await page.getByLabel('Studio view',{exact:true}).selectOption(view);assert.equal(await page.locator('.studio-dock-frame').getAttribute('data-view'),view);}
    await page.getByRole('button',{name:'Full screen',exact:true}).click();assert.equal(await page.evaluate(()=>!!document.fullscreenElement),true);await tools.click();assert.equal(await drawer.isVisible(),true);await drawer.getByRole('button',{name:'Close',exact:true}).click();await page.getByLabel('Open session workspace').selectOption('settings');await page.waitForFunction(()=>!document.fullscreenElement&&document.querySelector('.workspace[data-workspace=\"settings\"]').classList.contains('active'));await page.locator('.nav-button[data-target=\"broadcast\"]').click();
    const results=[];fs.mkdirSync('.tmp/refinish',{recursive:true});
    for(const skin of ['ignite','daylight'])for(const [width,height] of [[1920,1080],[3840,2088],[1366,768],[720,900]]){
      await page.setViewportSize({width,height});await page.evaluate(s=>applyStudioTheme(s,true),skin);await page.waitForTimeout(100);
      const result=await page.evaluate(()=>{const frame=document.querySelector('.studio-dock-frame').getBoundingClientRect(),grid=document.querySelector('.studio-dock-grid').getBoundingClientRect(),monitor=document.querySelector('.production-monitors').getBoundingClientRect(),transition=document.querySelector('.production-transition-bar').getBoundingClientRect();return{width:innerWidth,height:innerHeight,frameTop:frame.top,frameBottom:frame.bottom,gridBottom:grid.bottom,overflow:document.documentElement.scrollWidth>innerWidth,overlap:monitor.bottom>transition.top+1};});
      assert.equal(result.overflow,false);assert.equal(result.overlap,false);if(width>1100)assert.ok(result.frameBottom<=height+1,JSON.stringify(result));results.push({...result,skin});
      await page.screenshot({path:`.tmp/refinish/session-tools-${skin}-${width}.png`,mask:[page.locator('img:not(.brand-lockup-image):not(.nav-app-icon img),video')]});
    }
    await page.setViewportSize({width:1920,height:1080});await tools.click();await drawer.screenshot({path:'.tmp/refinish/session-tools-drawer.png'});
    await page.evaluate(()=>{Storage.prototype.setItem=function(){throw Error('blocked')};});await drawer.getByRole('button',{name:'Clear all tools',exact:true}).click();assert.match(await drawer.locator('.studio-tool-drawer-status').textContent(),/could not save/);
    assert.deepEqual(errors,[]);console.log(JSON.stringify({count,profiles:'switch and reload passed',drawer:'bulk, search, Escape, focus, popout passed',continuity:'original controls and unsaved input retained',results}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
