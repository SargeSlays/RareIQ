/* Running isolated Studio and guest pages; no device capture or external actions. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8769',destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Absolute evidence directory required');
fs.mkdirSync(destination,{recursive:true});
async function captureTool(page,id,theme,width){
  const selector=id==='production-audience'?'#productionAudience':id==='production-vision'?'#productionVision':'.production-greenroom';
  const tool=page.locator(selector);
  const controls=await tool.evaluate(async panel=>{
    const workspace=panel.closest('.workspace'),failures=[];let checked=0;
    for(const control of panel.querySelectorAll('button,input,select,textarea,a,summary')){
      const closed=control.closest('details:not([open])');
      if(closed&&!closed.querySelector('summary')?.contains(control))continue;
      if(!control.getClientRects().length)continue; // Inputs in closed disclosures are intentionally hidden.
      control.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
      await new Promise(requestAnimationFrame);
      const box=control.getBoundingClientRect(),bounds=panel.getBoundingClientRect(),view=workspace.getBoundingClientRect();
      const hit=document.elementFromPoint(box.x+box.width/2,box.y+box.height/2);
      const within=box.left>=bounds.left-1&&box.right<=bounds.right+1&&box.top>=view.top-1&&box.bottom<=view.bottom+1;
      const reachable=control.disabled||hit===control||control.contains(hit);
      const label=control.getAttribute('aria-label')||control.textContent.trim().slice(0,50);
      if(!within||!reachable)failures.push({tag:control.tagName,id:control.id,label,reason:!within?'clipped':'covered'});
      checked++;
    }
    return {checked,failures};
  });
  assert.ok(controls.checked>0,`${id} has no visible controls`);
  assert.deepEqual(controls.failures,[],`${id} control reachability ${theme} ${width}`);
  // Locator screenshots expand a tall element's capture area, but this app scrolls
  // inside a fixed-height workspace. Capture actual viewport slices so ancestors
  // don't clip/reflow into misleading preflight or blank screenshot regions.
  const slices=[];let offset=0,complete=false;
  for(let index=0;index<12;index++){
    await tool.evaluate((panel,offset)=>{
      let scroller=panel.parentElement;
      while(scroller&&(!['auto','scroll'].includes(getComputedStyle(scroller).overflowY)||scroller.scrollHeight<=scroller.clientHeight+2))scroller=scroller.parentElement;
      scroller=scroller||document.scrollingElement;
      const box=panel.getBoundingClientRect(),top=scroller===document.scrollingElement?0:scroller.getBoundingClientRect().top;
      const header=panel.closest('.studio-dock-tool')?.querySelector('.studio-dock-handle'),inset=header?.getBoundingClientRect().height||0;
      scroller.scrollTop+=box.top-top+offset-inset;
    },offset);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const frame=await tool.evaluate(panel=>{
      let scroller=panel.parentElement;
      while(scroller&&(!['auto','scroll'].includes(getComputedStyle(scroller).overflowY)||scroller.scrollHeight<=scroller.clientHeight+2))scroller=scroller.parentElement;
      const view=scroller?scroller.getBoundingClientRect():{left:0,top:0,right:innerWidth,bottom:innerHeight};
      const box=panel.getBoundingClientRect(),header=panel.closest('.studio-dock-tool')?.querySelector('.studio-dock-handle');
      const headerBottom=header?header.getBoundingClientRect().bottom:0;
      const x=Math.max(0,view.left,box.left),y=Math.max(0,view.top,box.top,headerBottom),right=Math.min(innerWidth,view.right,box.right),bottom=Math.min(innerHeight,view.bottom,box.bottom);
      return {clip:{x,y,width:right-x,height:bottom-y},complete:box.bottom<=Math.min(innerHeight,view.bottom)+1};
    });
    assert.ok(frame.clip.width>20&&frame.clip.height>20,`${id} has no visible screenshot area`);
    const name=`${id}${index?'-part-'+(index+1):''}-${theme}-${width}.png`;
    await page.screenshot({path:path.join(destination,name),clip:frame.clip,animations:'disabled'});
    slices.push({file:name,...frame.clip});
    if(frame.complete){complete=true;break;}
    offset+=Math.max(40,frame.clip.height-40);
  }
  assert.ok(complete,`${id} footer was not reached`);
  return {controls:controls.checked,slices};
}
async function main(){
  assert.equal((await fetch(base+'/__qa__/guest-fixture').then(r=>r.json())).isolated_guest_fixture,true);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']});
  const results=[],faults=[],expectedFixtureFailures=[];
  try{
    for(const theme of ['dark','light'])for(const [width,height] of [[1920,1080],[3840,2160],[960,900],[390,844]]){
      const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'}),page=await context.newPage();
      page.on('pageerror',error=>(error.message==='read_blocked_in_guest_fixture'?expectedFixtureFailures:faults).push(error.message));
      await page.goto(base+'/control?workspace=studio');
      await page.locator('#instantSplash').waitFor({state:'hidden'});
      await page.locator('.production-greenroom .greenroom-connection').waitFor();
      await page.waitForFunction(()=>document.querySelector('.production-greenroom')?.dataset.connection==='connected');
      await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      await page.waitForTimeout(2000);
      const measure=()=>page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        panelScrolls:[...document.querySelectorAll('.studio-dock-tool:not([hidden])')].filter(el=>['auto','scroll'].includes(getComputedStyle(el).overflowY)&&el.scrollHeight>el.clientHeight+2).length,
        tools:document.querySelectorAll('.studio-dock-tool').length}));
      const studio=await measure();
      await page.screenshot({path:path.join(destination,`studio-${theme}-${width}.png`)});
      results.push({theme,width,studio,toolEvidence:{}});
      const docks=await page.evaluate(()=>{const workspace=document.querySelector('[data-studio-docks="ready"]');return Boolean(workspace?._studioDocks);});assert.equal(docks,true);
      for(const id of ['production-greenroom','production-audience','production-vision']){
        await page.evaluate(id=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool(id),id);
        await page.waitForTimeout(100);
        results[results.length-1].toolEvidence[id]=await captureTool(page,id,theme,width);
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
