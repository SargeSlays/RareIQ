/* Populated scene-header geometry regression on an isolated backend; no media actions. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const evidence=process.argv[2],base=process.argv[3]||'http://127.0.0.1:8779';
if(!evidence||!path.isAbsolute(evidence))throw Error('Absolute evidence directory required');
fs.mkdirSync(evidence,{recursive:true});
async function main(){
  assert.equal((await fetch(base+'/__qa__/guest-fixture').then(response=>response.json())).isolated_guest_fixture,true);
  for(const [index,name] of ['Interview and presentation','Starting soon','Be right back'].entries()){
    const state=await fetch(base+'/api/production/scenes').then(response=>response.json());
    if(state.scenes.some(scene=>scene.name===name))continue;
    const response=await fetch(base+'/api/production/scenes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,program_slot:1,preview_slot:2,transition:'fade',expected_revision:state.revision,request_id:'scene_controls_'+index})});
    assert.equal(response.status,200);
  }
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']}),result={passed:false,hardware:false,broadcast:false,recording:false,layouts:[]};
  try{
    const context=await browser.newContext({viewport:{width:1600,height:1000},reducedMotion:'reduce'});
    await context.addInitScript(()=>{for(const name of ['getUserMedia','getDisplayMedia'])navigator.mediaDevices[name]=async()=>{throw Error('Physical capture forbidden');};HTMLMediaElement.prototype.play=()=>Promise.reject(Error('Media playback forbidden'));});
    await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    const page=await context.newPage();await page.goto(base+'/control?workspace=studio',{waitUntil:'domcontentloaded'});await page.locator('#instantSplash').waitFor({state:'hidden'});
    await page.waitForFunction(()=>document.querySelector('[data-studio-docks="ready"]')?._studioDocks);await page.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-scenes'));
    await page.evaluate(()=>setBroadcastWorkspaceView('live',{persist:false,scroll:false}));
    const tool=page.locator('[data-studio-tool="production-scenes"]');await tool.locator('.production-scene-card').first().waitFor();assert.equal(await tool.locator('.production-scene-card').count(),3);
    for(const theme of ['ignite','daylight'])for(const [width,height] of [[390,1080],[860,1080],[1600,1000],[1920,1080],[3840,2160]]){
      await page.setViewportSize({width,height});await page.evaluate(theme=>applyStudioTheme(theme,false),theme);await page.evaluate(()=>document.fonts.ready);await tool.scrollIntoViewIfNeeded();
      const checks=await tool.evaluate(element=>{
        const buttons=[...element.querySelectorAll('.production-scenes > header > div:last-child > button')].map(button=>{
          const box=button.getBoundingClientRect(),ranges=[],walker=document.createTreeWalker(button,NodeFilter.SHOW_TEXT);let text;
          while(text=walker.nextNode())if(text.textContent.trim()){const range=document.createRange();range.selectNodeContents(text);for(const rect of range.getClientRects())ranges.push({left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom});}
          return {label:button.innerText.trim(),height:box.height,width:box.width,clientHeight:button.clientHeight,scrollHeight:button.scrollHeight,clipped:ranges.some(rect=>rect.top<box.top-.5||rect.bottom>box.bottom+.5||rect.left<box.left-.5||rect.right>box.right+.5),lines:ranges.length};
        });
        const preflightButtons=[...document.querySelectorAll('[data-studio-tool="show-preflight"] button')].map(button=>{const box=button.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(button);const label=range.getBoundingClientRect();return {label:button.innerText.trim(),width:box.width,height:box.height,clipped:label.top<box.top-.5||label.bottom>box.bottom+.5||label.left<box.left-.5||label.right>box.right+.5};});
        return {leftDock:!!element.closest('.studio-dock-left'),dockView:element.closest('.studio-dock-frame').dataset.view,dockWidth:element.getBoundingClientRect().width,overflow:element.scrollWidth>element.clientWidth+1,pageOverflow:document.documentElement.scrollWidth>innerWidth+1,buttons,preflightButtons};
      });
      assert.equal(checks.leftDock,true);assert.equal(checks.overflow,false);assert.equal(checks.pageOverflow,false);
      assert.equal(checks.dockView,'live');if(width>=1600)assert.ok(checks.dockWidth<400,'Scenes must be in the narrow Live side column');
      assert.deepEqual(checks.buttons.map(button=>button.label),['Save Current','New Scene']);
      for(const button of checks.buttons){assert.ok(button.height>=44,theme+' '+width+' '+button.label+' target');assert.equal(button.clipped,false,theme+' '+width+' '+button.label+' clipped');assert.ok(button.scrollHeight<=button.clientHeight+1,theme+' '+width+' '+button.label+' overflow');}
      for(const button of checks.preflightButtons)assert.equal(button.clipped,false,theme+' '+width+' '+button.label+' preflight clipped');
      await tool.locator('.production-scenes > header').screenshot({path:path.join(evidence,`scene-actions-${theme}-${width}.png`)});result.layouts.push({theme,width,height,...checks});
    }
    await page.setViewportSize({width:1600,height:1000});await tool.locator('#productionNewScene').focus();await page.keyboard.press('Enter');await tool.locator('#productionSceneEditor').waitFor({state:'visible'});await tool.locator('#productionCancelScene').click();
    result.keyboardAction=true;result.passed=true;
  }finally{await browser.close();fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));}
  console.log(JSON.stringify({passed:result.passed,layouts:result.layouts.length,keyboardAction:result.keyboardAction}));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
