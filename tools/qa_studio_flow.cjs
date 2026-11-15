// Served-page layout regression. Mutations and browser device capture are blocked.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:8765';
const output=process.env.RAREIQ_QA_OUTPUT||path.join(require('node:os').tmpdir(),'producer-please-theme');
(async()=>{
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:'reduce'});
    await context.addInitScript(()=>{
      navigator.mediaDevices.getUserMedia=()=>Promise.reject(new Error('Device capture blocked in layout QA'));
      navigator.mediaDevices.getDisplayMedia=()=>Promise.reject(new Error('Screen capture blocked in layout QA'));
      HTMLMediaElement.prototype.play=()=>Promise.reject(new Error('Playback blocked in layout QA'));
    });
    const page=await context.newPage();
    await page.route('**/api/**',route=>['GET','HEAD'].includes(route.request().method())?route.continue():route.abort());
    await page.goto(origin+'/control?workspace=studio&layout=20261115',{waitUntil:'domcontentloaded'});
    await page.waitForSelector('[data-studio-docks="ready"]');
    await page.waitForSelector('.show-preflight-checks article');
    const results=[];
    for(const theme of ['ignite','daylight'])for(const [width,height] of [[1920,1080],[3840,2160],[960,900]]){
      await page.setViewportSize({width,height});
      await page.evaluate(theme=>applyStudioTheme(theme,false),theme);
      await page.evaluate(()=>document.fonts.ready);
      await page.waitForTimeout(150);
      const result=await page.evaluate(()=>{
        const tools=[...document.querySelectorAll('.studio-dock-region:not(.studio-dock-float) > .studio-dock-tool:not([hidden])')];
        return {width:innerWidth,theme:document.documentElement.dataset.theme,
          horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1,
          tools:tools.filter(e=>e.getClientRects().length).map(e=>({id:e.dataset.studioTool,
            nestedScroll:['auto','scroll'].includes(getComputedStyle(e).overflowY)&&e.scrollHeight>e.clientHeight+1,
            clipped:e.scrollHeight>e.clientHeight+2,overflow:e.scrollWidth>e.clientWidth+2})),
          monitorHeight:document.querySelector('.production-monitor img').getBoundingClientRect().height,
          bottomGap:document.querySelector('.studio-dock-bottom').getBoundingClientRect().top-
            Math.max(document.querySelector('.studio-dock-center').getBoundingClientRect().bottom,
              document.querySelector('.studio-dock-left').getBoundingClientRect().bottom),
          monitorOverlap:document.querySelector('.production-monitors').getBoundingClientRect().bottom>
            document.querySelector('.production-transition-bar').getBoundingClientRect().top+1};
      });
      assert.ok(result.tools.length>=4,'Expected real docked tools');
      assert.equal(result.horizontalOverflow,false,JSON.stringify(result));
      assert.equal(result.monitorOverlap,false,JSON.stringify(result));
      assert.ok(result.monitorHeight>=180,JSON.stringify(result));
      if(width>1100)assert.ok(result.bottomGap>=0&&result.bottomGap<=24,JSON.stringify(result));
      assert.ok(result.tools.every(tool=>!tool.nestedScroll&&!tool.clipped&&!tool.overflow),JSON.stringify(result));
      results.push(result);
      await page.screenshot({path:path.join(output,`studio-${theme}-${width}.png`),fullPage:true,
        mask:[page.locator('.production-monitor[data-source-state="connected"] img,video')]});
      await page.locator('.studio-dock-bottom').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(output,`studio-bottom-${theme}-${width}.png`)});
      await page.locator('.studio-dock-toolbar').scrollIntoViewIfNeeded();
    }
    // Saved fixed heights must not reintroduce scrollbars in docked bottom tools.
    await page.locator('.studio-dock-bottom > .studio-dock-tool').evaluateAll(nodes=>nodes.forEach(node=>{
      node.dataset.customHeight='true';node.style.height='160px';
    }));
    assert.ok(await page.locator('.studio-dock-bottom > .studio-dock-tool').evaluateAll(nodes=>nodes.every(node=>node.scrollHeight<=node.clientHeight+2)));
    fs.writeFileSync(path.join(output,'layout-results.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify({passed:true,layouts:results.length,tools:results[0].tools.map(t=>t.id),output}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
