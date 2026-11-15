// Requires the isolated scene fixture; refuses to mutate the production server.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const origin=process.env.RAREIQ_SCENE_QA_ORIGIN||'http://127.0.0.1:8767';
const output=process.env.RAREIQ_QA_OUTPUT;
(async()=>{
  assert.ok(output,'Set RAREIQ_QA_OUTPUT to an evidence directory');
  assert.equal((await (await fetch(origin+'/__qa__/scene-fixture')).json()).isolated_scene_fixture,true);
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const contexts=await Promise.all([browser.newContext({viewport:{width:1920,height:1080}}),browser.newContext({viewport:{width:1920,height:1080}})]);
    for(const context of contexts){
      await context.addInitScript(()=>{navigator.mediaDevices.getUserMedia=()=>Promise.reject(Error('QA'));navigator.mediaDevices.getDisplayMedia=()=>Promise.reject(Error('QA'));HTMLMediaElement.prototype.play=()=>Promise.reject(Error('QA'));});
      await context.route('**/api/**',route=>{
        const request=route.request(),url=new URL(request.url());
        if(['GET','HEAD'].includes(request.method())&&!url.pathname.endsWith('/stream'))return route.continue();
        if(url.origin===origin&&url.pathname==='/api/production/scenes'&&request.method()==='POST')return route.continue();
        return route.abort();
      });
    }
    const [first,second]=await Promise.all(contexts.map(c=>c.newPage()));
    for(const page of [first,second]){await page.goto(origin+'/control?workspace=studio',{waitUntil:'domcontentloaded'});await page.waitForSelector('#productionSceneActivity');}
    await first.locator('#productionNewScene').click();await first.locator('#productionSceneName').fill('Browser QA scene');
    await first.locator('#productionSceneEditor [type="submit"]').click();await first.locator('#productionSceneEditor').waitFor({state:'hidden'});
    await second.getByRole('button',{name:'Edit',exact:true}).waitFor();
    await first.getByRole('button',{name:'Edit',exact:true}).click();
    await second.getByRole('button',{name:'Edit',exact:true}).click();
    await first.locator('#productionSceneName').fill('First operator revision');
    await second.locator('#productionSceneName').fill('Second operator unsaved draft');
    await first.locator('#productionSceneEditor [type="submit"]').click();await first.locator('#productionSceneEditor').waitFor({state:'hidden'});
    // Wait for the second client to observe the new snapshot while its editor stays open.
    await second.locator('#productionSceneGrid').getByText('First operator revision',{exact:true}).waitFor();
    const conflict=second.waitForResponse(r=>r.url().endsWith('/api/production/scenes')&&r.request().method()==='POST');
    await second.locator('#productionSceneEditor [type="submit"]').click();
    assert.equal((await conflict).status(),409);
    assert.equal(await second.locator('#productionSceneName').inputValue(),'Second operator unsaved draft');
    assert.equal(await second.locator('#productionSceneEditor').isVisible(),true);
    await second.locator('#productionSceneActivity summary').click();
    await second.locator('#productionSceneActivity li').filter({hasText:'scene revision conflict'}).waitFor();
    await second.locator('#productionSceneActivity').scrollIntoViewIfNeeded();
    const sceneTool=second.locator('[data-studio-tool="production-scenes"]');
    assert.ok(await sceneTool.evaluate(e=>e.scrollWidth<=e.clientWidth+2),'Populated scene tool must not overflow horizontally');
    await second.screenshot({path:path.join(output,'scene-conflict-history.png')});
    for(const theme of ['ignite','daylight'])for(const [width,height] of [[1920,1080],[3840,2160],[960,900]]){
      await second.setViewportSize({width,height});
      await second.evaluate(theme=>applyStudioTheme(theme,false),theme);
      await second.locator('#productionSceneEditor').scrollIntoViewIfNeeded();
      assert.ok(await sceneTool.evaluate(e=>e.scrollWidth<=e.clientWidth+2),'Populated scene tool overflows '+theme+' '+width);
      assert.ok(await sceneTool.evaluate(e=>e.scrollHeight<=e.clientHeight+2),'Populated scene tool is clipped '+theme+' '+width);
      await second.screenshot({path:path.join(output,`scene-editor-${theme}-${width}.png`)});
    }
    const history=await (await fetch(origin+'/api/production/scenes/activity')).json();
    assert.equal(history.events.length,3);assert.ok(history.events.every(e=>e.identity_verified===false));
    fs.writeFileSync(path.join(output,'scene-browser-results.json'),JSON.stringify({passed:true,clients:2,draftPreserved:true,conflictStatus:409,events:3}));
    console.log('Two-client scene history and conflict recovery passed');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
