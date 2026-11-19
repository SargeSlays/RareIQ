/* Real loopback HTTP + production UI; synthetic message ingress, no provider/hardware. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const [origin,destination]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin||'')||!path.isAbsolute(destination||''))throw Error('Supply fixture origin and absolute evidence directory.');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']}),page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[],results=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const post=async(data)=>{const response=await page.request.post(origin+'/__qa__/viewer-chat-message',{data});assert.equal(response.status(),200);return response.json();};
  const refresh=async()=>page.evaluate(()=>window.chatFixture.controller.refresh());
  try{
    const marker=await (await page.request.get(origin+'/__qa__/viewer-chat-marker')).json();
    assert.deepEqual(marker,{synthetic_viewer_chat_fixture:true,provider_network:false,hardware:false,real_credentials:false,program_generation:0});
    await page.goto(origin+'/__qa__/viewer-chat');
    await page.waitForFunction(()=>document.querySelector('[data-viewer-status]')?.textContent.includes('stopped'));
    assert.equal((await post({platform:'twitch'})).ok,false,'disabled transcript drops incoming messages');
    await page.locator('[data-viewer-start]').click();
    await page.waitForFunction(()=>document.querySelector('[data-viewer-start]').hidden);
    await page.locator('.viewer-chat-connections summary').click();
    assert.equal(await page.locator('[data-viewer-connect="kick"]').isDisabled(),true);
    await page.locator('[data-viewer-connect="twitch"]').click();
    await page.waitForFunction(()=>document.querySelector('[data-viewer-connect="twitch"]').textContent==='Disconnect Twitch');
    for(const [platform,count]of [['twitch',3],['youtube',2],['kick',1]])assert.equal((await post({platform,count})).ok,true);
    await refresh();
    assert.equal(await page.locator('[data-viewer-messages]>li').count(),6);
    assert.equal(await page.locator('[data-viewer-messages] img').count(),0,'viewer text is never parsed as markup');
    assert.match(await page.locator('[data-viewer-messages]').innerText(),/<img src=x onerror=alert\(1\)>/);
    for(const [platform,count]of [['twitch',3],['youtube',2],['kick',1],['all',6]]){
      await page.locator('[data-viewer-filter="'+platform+'"]').click();
      assert.equal(await page.locator('[data-viewer-messages]>li').count(),count);
    }
    await post({platform:'twitch',count:100});await refresh();
    await page.locator('[data-viewer-messages]').evaluate(el=>{el.scrollTop=0;el.dispatchEvent(new Event('scroll'));});
    await post({platform:'youtube',count:2});await refresh();
    await page.waitForFunction(()=>!document.querySelector('[data-viewer-latest]').hidden);
    assert.match(await page.locator('[data-viewer-latest]').innerText(),/2 new/);
    await page.locator('[data-viewer-latest]').click();
    assert.equal(await page.locator('[data-viewer-latest]').isVisible(),false);
    await page.route('**/api/production/viewer-chat?*',route=>route.abort());
    await refresh();assert.equal(await page.locator('[data-viewer-messages]>li').count(),108,'temporary loss preserves existing messages');
    assert.equal(await page.locator('[data-viewer-retry]').isVisible(),true);
    await page.unroute('**/api/production/viewer-chat?*');await refresh();
    assert.equal(await page.locator('[data-viewer-retry]').isVisible(),false);
    await post({platform:'twitch',count:330});await refresh();
    assert.equal(await page.locator('[data-viewer-messages]>li').count(),300,'server and UI bound retained messages');
    for(const theme of ['dark','light'])for(const width of [390,960,1920,3840]){
      await page.setViewportSize({width,height:width===3840?2160:width===390?844:1080});
      await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      await page.emulateMedia({reducedMotion:'reduce'});
      const geometry=await page.evaluate(()=>({surface:getComputedStyle(document.querySelector('.production-viewer-chat')).backgroundColor,text:getComputedStyle(document.querySelector('.production-viewer-chat h3')).color,width:innerWidth,scroll:document.documentElement.scrollWidth,buttons:[...document.querySelectorAll('.viewer-chat-panel button')].filter(el=>el.offsetParent!==null).map(el=>({label:el.textContent,height:el.getBoundingClientRect().height,width:el.getBoundingClientRect().width}))}));
      assert.ok(geometry.scroll<=width+1,'no horizontal page overflow');
      const rgb=value=>value.match(/\d+/g).slice(0,3).map(Number),lum=value=>rgb(value).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;}).reduce((a,v,i)=>a+v*[0.2126,0.7152,0.0722][i],0),l=[lum(geometry.surface),lum(geometry.text)].sort((a,b)=>b-a);
      assert.ok((l[0]+0.05)/(l[1]+0.05)>=4.5,'heading contrast follows selected skin');
      assert.ok(geometry.buttons.every(el=>el.height>=32&&el.width>0),'controls remain usable');
      await page.screenshot({path:path.join(destination,`viewer-${theme}-${width}.png`),fullPage:false});results.push({theme,width,overflow:geometry.scroll-width});
    }
    await page.setViewportSize({width:1920,height:1080});
    await page.locator('[data-viewer-accounts]').click();
    await page.waitForFunction(()=>document.querySelector('.platform-accounts-dialog').open&&document.querySelector('[data-accounts-begin]')?.disabled===false);
    await page.locator('[data-account-platform="twitch"] [data-accounts-begin]').click();
    await page.waitForFunction(()=>document.querySelector('[data-accounts-code]').textContent==='DEMO-1234');
    await page.screenshot({path:path.join(destination,'accounts-synthetic-pending.png'),fullPage:false});
    await page.locator('[data-account-platform="twitch"] [data-accounts-cancel]').click();
    await page.waitForFunction(()=>document.querySelector('[data-account-platform="twitch"] [data-accounts-pending]').hidden);
    await page.locator('[data-accounts-close]').click();
    await page.locator('[data-viewer-stop]').click();
    await page.waitForFunction(()=>document.querySelector('[data-viewer-messages]').children.length===0&&!document.querySelector('[data-viewer-start]').hidden);
    assert.equal((await post({platform:'youtube'})).ok,false,'stopped feed cannot refill');
    const history=await (await page.request.get(origin+'/api/production/greenroom/activity')).json();
    assert.ok(history.events.some(e=>e.action==='viewer_chat.listening'&&e.details.enabled===false));
    assert.ok(history.events.some(e=>e.action==='platform.chat.connect'&&e.target==='twitch'));
    assert.ok(history.events.some(e=>e.action==='platform.account.begin'&&e.target==='twitch'));
    assert.ok(history.events.every(e=>!JSON.stringify(e.details).includes('Synthetic message')&&!JSON.stringify(e.details).includes('DEMO-1234')));
    const after=await (await page.request.get(origin+'/__qa__/viewer-chat-marker')).json();assert.equal(after.program_generation,0);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify({complete:true,providerNetwork:false,hardware:false,programUnchanged:true,retainedMessageLimit:300,filters:true,literalText:true,pause:true,recovery:true,stopClears:true,accountability:true,results},null,2));
    console.log('Viewer chat: HTTP/UI controls, filters, literal text, pause/recovery, retention, stop/privacy, account flow, history and 8 theme/viewport cases passed.');
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
