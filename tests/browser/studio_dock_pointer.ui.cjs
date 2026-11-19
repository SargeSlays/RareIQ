/* Full /control pointer regression against the verified loopback-only synthetic fixture. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const destination=process.argv[2],base=process.argv[3]||'http://127.0.0.1:8770';
if(!destination||!path.isAbsolute(destination))throw Error('Supply an absolute evidence directory.');
if(base!=='http://127.0.0.1:8770')throw Error('Only the isolated viewer-chat fixture on loopback port8770 is permitted.');
fs.mkdirSync(destination,{recursive:true});
async function marker(){const response=await fetch(base+'/__qa__/viewer-chat-marker');assert.equal(response.ok,true);const value=await response.json();assert.equal(value.synthetic_viewer_chat_fixture,true);assert.equal(value.provider_network,false);assert.equal(value.hardware,false);assert.equal(value.real_credentials,false);return value;}
async function pointerTarget(locator,label){
  await locator.scrollIntoViewIfNeeded();
  const result=await locator.evaluate(element=>{const box=element.getBoundingClientRect(),x=box.left+box.width/2,y=box.top+box.height/2,hit=document.elementFromPoint(x,y);return {x,y,width:box.width,height:box.height,inViewport:x>=0&&x<innerWidth&&y>=0&&y<innerHeight,receivesPointer:Boolean(hit&&(hit===element||element.contains(hit))),coveringTag:hit?.tagName||null,coveringClass:typeof hit?.className==='string'?hit.className.slice(0,160):null};});
  assert.equal(result.inViewport,true,label+' is reachable in the viewport: '+JSON.stringify(result));assert.equal(result.receivesPointer,true,label+' receives the pointer: '+JSON.stringify(result));return result;
}
async function main(){
  const before=await marker(),browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']}),results=[],faults=[],knownFixtureFaults=[],blockedExternal=[],blockedMutations=[];let current='startup',page,caseDiagnostics=null;
  try{
    for(const theme of ['dark','light'])for(const width of [960,1366,1920,3840]){
      current=theme+'-'+width;caseDiagnostics={theme,width};const context=await browser.newContext({viewport:{width,height:width===3840?2160:width>=1920?1080:900},reducedMotion:'reduce'});page=await context.newPage();
      page.on('pageerror',error=>{const fault={case:current,message:error.message};if(error.message==='read_blocked_in_guest_fixture')knownFixtureFaults.push(fault);else faults.push(fault);});
      await context.route('**/*',route=>{const request=route.request(),url=new URL(request.url());if(url.origin!==base){blockedExternal.push({case:current,origin:url.origin,path:url.pathname});return route.abort();}if(!['GET','HEAD'].includes(request.method())){blockedMutations.push({case:current,method:request.method(),path:url.pathname});return route.fulfill({status:403,contentType:'application/json',body:'{"ok":false,"reason":"pointer_regression_mutation_blocked"}'});}return route.continue();});
      await context.addInitScript(()=>{
        window.__dockPointerGuard={captureAttempts:0,externalSockets:0,windowOpenAttempts:0};
        const blockedCapture=async()=>{window.__dockPointerGuard.captureAttempts++;throw new DOMException('Physical capture is disabled in this pointer regression.','NotAllowedError');};
        if(navigator.mediaDevices){navigator.mediaDevices.getUserMedia=blockedCapture;navigator.mediaDevices.getDisplayMedia=blockedCapture;}
        navigator.getUserMedia=()=>{window.__dockPointerGuard.captureAttempts++;throw Error('Physical capture blocked');};
        window.open=()=>{window.__dockPointerGuard.windowOpenAttempts++;return null;};
        const NativeSocket=window.WebSocket;
        window.WebSocket=class extends NativeSocket{constructor(url,protocols){const parsed=new URL(url,location.href);if(parsed.origin!=='ws://127.0.0.1:8770'){window.__dockPointerGuard.externalSockets++;throw Error('Nonlocal socket blocked');}super(url,protocols);}};
        const NativePeer=window.RTCPeerConnection;if(NativePeer)window.RTCPeerConnection=class extends NativePeer{constructor(config={},constraints){super({...config,iceServers:[]},constraints);}};
      });
      await page.goto(base+'/control?qa-dock-pointer='+encodeURIComponent(current),{waitUntil:'domcontentloaded'});
      const workspace=page.locator('.workspace[data-workspace="broadcast"]');await workspace.locator('.studio-dock-frame').waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelector('.workspace[data-workspace="broadcast"]')?.dataset.studioDocks==='ready');
      await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      const toolbar=workspace.locator('.studio-dock-toolbar'),viewer=workspace.locator('.production-viewer-chat'),openViewer=toolbar.getByRole('button',{name:'Viewer chat',exact:true});
      const toolbarPointer=await pointerTarget(openViewer,'Viewer chat toolbar button');await openViewer.click({timeout:8000});
      const summary=viewer.locator('.viewer-chat-connections > summary');const summaryPointer=await pointerTarget(summary,'Platform connections summary');await summary.click({timeout:8000});
      const manage=viewer.locator('[data-viewer-accounts]');await manage.waitFor({state:'visible'});await manage.scrollIntoViewIfNeeded();
      const geometry=await workspace.evaluate((element,width)=>{
        const bounds=selector=>{const node=element.querySelector(selector),box=node?.getBoundingClientRect();return box?{top:box.top,bottom:box.bottom,left:box.left,right:box.right,width:box.width,height:box.height}:null;};
        const guest=element.querySelector('[data-studio-tool="production-greenroom"]'),visible=Boolean(guest&&!guest.hidden&&guest.getBoundingClientRect().width&&getComputedStyle(guest).display!=='none');
        return {width,horizontal:document.documentElement.scrollWidth>innerWidth+1,right:bounds('.studio-dock-right'),bottom:bounds('.studio-dock-bottom'),greenroom:bounds('[data-studio-tool="production-greenroom"]'),greenroomVisible:visible,rightGridRow:getComputedStyle(element.querySelector('.studio-dock-right')).gridRow};
      },width);
      caseDiagnostics.geometry=geometry;assert.equal(geometry.horizontal,false,current+' horizontal overflow');assert.equal(geometry.greenroomVisible,true,current+' full-width green room remains visible');
      if(width>1100)assert.ok(geometry.right.bottom<=geometry.bottom.top+1,current+' right dock must finish above the full-width bottom dock: '+JSON.stringify(geometry));
      const managePointer=await pointerTarget(manage,'Manage accounts');
      const banner=workspace.locator(':scope > .workspace-readiness'),retry=banner.locator('button');let readiness=null;
      if(await banner.isVisible()){const box=await banner.boundingBox();assert.ok(box.width>0&&box.x>=0&&box.x+box.width<=width+1,current+' readiness banner fits horizontally');if(await retry.isVisible())readiness=await pointerTarget(retry,'Readiness Retry');else readiness={visible:true,retryVisible:false};}
      // Use ordinary pointer clicks. A fixed banner or overlapping green room must never intercept this path.
      await manage.click({timeout:8000});const dialog=page.locator('.platform-accounts-dialog[open]');await dialog.waitFor({state:'visible'});await page.screenshot({path:path.join(destination,current+'-accounts.png'),animations:'disabled'});
      const close=dialog.locator('[data-accounts-close]'),closePointer=await pointerTarget(close,'Account dialog Close');await close.click({timeout:8000});await dialog.waitFor({state:'hidden'});
      assert.equal(await page.evaluate(()=>Boolean(document.activeElement?.matches('[data-viewer-accounts]'))),true,current+' Close returns focus to Manage accounts');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,current+' horizontal overflow after dialog Close');
      const guard=await page.evaluate(()=>window.__dockPointerGuard);assert.equal(guard.captureAttempts,0,current+' never requests physical capture');assert.equal(guard.externalSockets,0,current+' never attempts an external socket');assert.equal(guard.windowOpenAttempts,0,current+' never opens an external window');
      await pointerTarget(manage,'Manage accounts after Close');await page.screenshot({path:path.join(destination,current+'-dock.png'),animations:'disabled'});results.push({theme,width,geometry,toolbarPointer,summaryPointer,managePointer,closePointer,readiness,guard});await context.close();page=null;
    }
    const after=await marker();assert.equal(after.program_generation,before.program_generation,'Program generation is unchanged');assert.deepEqual(faults,[]);
    const output={passed:true,synthetic:true,hardware:false,actualAuthorization:false,checks:results.length,programGenerationUnchanged:true,blockedExternal,blockedMutations,knownFixtureFaults,faults,results};fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify(output,null,2));console.log(JSON.stringify({passed:true,checks:results.length,hardware:false,knownFixtureFaults:knownFixtureFaults.length,unknownPageErrors:faults.length,blockedExternal:blockedExternal.length,blockedMutations:blockedMutations.length}));
  }catch(error){if(page){await page.screenshot({path:path.join(destination,'failure-'+current+'.png'),animations:'disabled'}).catch(()=>{});if(caseDiagnostics)caseDiagnostics.guard=await page.evaluate(()=>window.__dockPointerGuard).catch(()=>null);}fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify({passed:false,failedCase:current,error:error.message,caseDiagnostics,results,knownFixtureFaults,faults,blockedExternal,blockedMutations},null,2));throw error;}
  finally{await browser.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
