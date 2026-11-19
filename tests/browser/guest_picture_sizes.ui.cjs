/* Isolated synthetic gallery: no guest server, account, hardware or network access. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'../../rareiq/web/static'),destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Supply an absolute evidence directory.');fs.mkdirSync(destination,{recursive:true});
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']}),page=await browser.newPage({viewport:{width:1920,height:1080}}),faults=[],results=[];
  page.on('pageerror',error=>faults.push(error.message));await page.route('**/*',route=>route.abort());
  try{
    await page.setContent('<!doctype html><html data-theme="dark"><body class="pp-shell"><main class="guest-layout"><section id="guestRoom"></section><section class="guest-stage"><div class="guest-preview"><video></video></div></section><section class="guest-card">Camera and microphone controls</section><aside id="guestChat">Backstage chat</aside></main></body></html>');
    for(const file of ['brand/producer-please-v2/producer-please.tokens.css','guest.css','guest_room.css'])await page.addStyleTag({content:fs.readFileSync(path.join(root,file),'utf8')});
    await page.addScriptTag({content:fs.readFileSync(path.join(root,'guest_room.js'),'utf8')});
    await page.evaluate(()=>{
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;const ctx=canvas.getContext('2d');ctx.fillStyle='#334455';ctx.fillRect(0,0,640,360);ctx.fillStyle='white';ctx.font='32px sans-serif';ctx.fillText('Synthetic room picture',50,190);
      const track=canvas.captureStream(1).getVideoTracks()[0],stop=track.stop.bind(track),fixture=window.fixture={track,stops:0,canvas};track.stop=()=>{fixture.stops++;stop();};
      const person=(id,name,state='admitted')=>({id,name,state,connected:true,media:{camera:true,microphone:true}});fixture.self=person('self','You');fixture.other=person('other','Another guest');fixture.waiting=person('waiting','Waiting guest','waiting');fixture.room={participants:[fixture.self,fixture.other,fixture.waiting]};
      fixture.gallery=ProducerGuestRoom.mount(document.getElementById('guestRoom'));fixture.update=()=>fixture.gallery.update({room:fixture.room,self:fixture.self,localCamera:track,tracks:()=>({camera:track})});fixture.update();fixture.videos=[...document.querySelectorAll('.guest-room-person video')];fixture.streams=fixture.videos.map(video=>video.srcObject);
    });
    const toggle=page.locator('[data-room-picture-size]');assert.equal(await toggle.getAttribute('aria-pressed'),'false');assert.equal(await toggle.textContent(),'Larger pictures');await toggle.focus();await page.keyboard.press('Enter');assert.equal(await toggle.getAttribute('aria-pressed'),'true');await page.keyboard.press('Space');assert.equal(await toggle.getAttribute('aria-pressed'),'false');
    const unchanged=()=>page.evaluate(()=>fixture.videos.every((video,index)=>video===document.querySelectorAll('.guest-room-person video')[index]&&video.srcObject===fixture.streams[index])&&fixture.track.readyState==='live'&&fixture.track.enabled&&fixture.stops===0);
    assert.equal(await unchanged(),true,'keyboard resizing preserves borrowed video owners');
    for(const reducedMotion of ['no-preference','reduce'])for(const theme of ['dark','light'])for(const width of [390,960,1920,3840]){
      await page.setViewportSize({width,height:width>=1920?1080:900});await page.emulateMedia({reducedMotion});await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      const compact=await page.locator('.guest-room-person').first().boundingBox();assert.ok(compact.width<=281,`compact ${width}`);assert.ok((await toggle.boundingBox()).height>=42);
      await toggle.click();const large=await page.locator('.guest-room-person').first().boundingBox();assert.ok(large.width<=641,`large ${width}`);assert.ok(large.width>=compact.width,`deliberate larger ${width}`);
      const geometry=await page.evaluate(()=>({horizontal:document.documentElement.scrollWidth>innerWidth,duplicatePreview:getComputedStyle(document.querySelector('.guest-stage>.guest-preview')).display,videoFit:getComputedStyle(document.querySelector('.guest-room-person video')).objectFit,transition:getComputedStyle(document.querySelector('.guest-room-person')).transitionDuration}));
      assert.equal(geometry.horizontal,false);assert.equal(geometry.videoFit,'contain');assert.equal(geometry.duplicatePreview,'none');if(reducedMotion==='reduce')assert.equal(geometry.transition,'0s');assert.equal(await unchanged(),true);
      if(reducedMotion==='reduce'&&[390,1920].includes(width))await page.screenshot({path:path.join(destination,`guest-${theme}-${width}-large.png`),fullPage:true,animations:'disabled'});
      await toggle.click();if(reducedMotion==='reduce'&&[390,1920].includes(width))await page.screenshot({path:path.join(destination,`guest-${theme}-${width}-compact.png`),fullPage:true,animations:'disabled'});
      results.push({width,theme,reducedMotion,compact:compact.width,large:large.width,...geometry});
    }
    await page.evaluate(()=>{fixture.self={...fixture.self,state:'waiting'};fixture.update();});assert.equal(await page.locator('.guest-room-person').count(),1,'waiting guests see only their own picture');assert.match(await page.locator('[data-room-guidance]').textContent(),/waiting room/);assert.equal(await page.evaluate(()=>fixture.stops),0,'privacy detaches borrowed remote pictures without stopping tracks');
    await toggle.click();assert.equal(await page.locator('.guest-room-person').count(),1,'larger pictures cannot bypass waiting privacy');await page.evaluate(()=>fixture.gallery.clear());assert.equal(await toggle.getAttribute('aria-pressed'),'false','ending gallery returns to compact default');
    assert.deepEqual(faults,[]);fs.writeFileSync(path.join(destination,'summary.json'),JSON.stringify({isolated:true,hardware:false,results,checks:['compact default','keyboard toggle','borrowed tracks retained','touch target','size bounds','no horizontal overflow','dark/light','reduced motion','no duplicate desktop preview','waiting privacy','compact reset'],faults},null,2));console.log(JSON.stringify({passed:true,geometryChecks:results.length,hardware:false}));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
