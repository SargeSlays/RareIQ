/* Running isolated Studio and guest pages; no device capture or external actions. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8769',destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Absolute evidence directory required');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  assert.equal((await fetch(base+'/__qa__/guest-fixture').then(r=>r.json())).isolated_guest_fixture,true);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']});
  const results=[],faults=[],expectedFixtureFailures=[];
  try{
    for(const theme of ['dark','light'])for(const [width,height] of [[1920,1080],[3840,2160],[960,900],[390,844]]){
      const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'}),page=await context.newPage();
      page.on('pageerror',error=>(error.message==='read_blocked_in_guest_fixture'?expectedFixtureFailures:faults).push(error.message));
      await page.goto(base+'/control?workspace=studio');
      await page.locator('.production-greenroom .greenroom-connection').waitFor();
      await page.waitForFunction(()=>document.querySelector('.production-greenroom')?.dataset.connection==='connected');
      await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      await page.waitForTimeout(2000);
      const measure=()=>page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        panelScrolls:[...document.querySelectorAll('.studio-dock-tool:not([hidden])')].filter(el=>['auto','scroll'].includes(getComputedStyle(el).overflowY)&&el.scrollHeight>el.clientHeight+2).length,
        tools:document.querySelectorAll('.studio-dock-tool').length}));
      const studio=await measure();
      await page.screenshot({path:path.join(destination,`studio-${theme}-${width}.png`)});
      results.push({theme,width,studio});
      const docks=await page.evaluate(()=>{const workspace=document.querySelector('[data-studio-docks="ready"]');return Boolean(workspace?._studioDocks);});assert.equal(docks,true);
      for(const id of ['production-greenroom','production-audience','production-vision']){
        await page.evaluate(id=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool(id),id);
        await page.waitForTimeout(100);
        await page.locator(id==='production-audience'?'#productionAudience':id==='production-vision'?'#productionVision':'.production-greenroom').screenshot({path:path.join(destination,`${id}-${theme}-${width}.png`)});
      }
      await page.goto(base+'/guest');
      await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      const guest=await measure();results[results.length-1].guest=guest;
      await page.screenshot({path:path.join(destination,`guest-${theme}-${width}.png`),fullPage:true});
      assert.ok(guest.scrollWidth<=width,`Guest horizontal overflow ${theme} ${width}`);
      await context.close();
    }
    fs.writeFileSync(path.join(destination,'ui-results.json'),JSON.stringify({results,pageErrors:faults,expectedFixtureFailures},null,2));
    assert.deepEqual(faults,[]);assert.ok(results.every(r=>r.studio.scrollWidth<=r.width),'Studio horizontal overflow');
    assert.ok(results.every(r=>r.studio.panelScrolls===0),'Nested tool scrolling');
    console.log(JSON.stringify({baselines:results.length,pageErrors:faults.length,horizontalOverflow:false,nestedToolScrollbars:false}));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
