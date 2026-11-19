/* Real local WebRTC with generated canvas video; never opens a personal display picker. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const evidence=process.argv[2],base=process.argv[3]||'http://127.0.0.1:8779';
if(!evidence||!path.isAbsolute(evidence))throw Error('Absolute evidence directory required');fs.mkdirSync(evidence,{recursive:true});
async function main(){
  assert.equal((await fetch(base+'/__qa__/guest-fixture').then(r=>r.json())).isolated_guest_fixture,true);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding']});
  const result={passed:false,generatedVideoOnly:true,physicalCapture:false,broadcast:false,recording:false,layouts:[]},errors=[];
  const read=async()=>fetch(base+'/api/production/switcher').then(r=>r.json());
  async function until(check,label){const end=Date.now()+20000;while(Date.now()<end){if(await check())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timed out: '+label);}
  try{
    const context=await browser.newContext({viewport:{width:1920,height:1080}});
    await context.route('**/*',route=>{const url=new URL(route.request().url());return url.origin===base?route.continue():route.abort();});
    const producer=await context.newPage();producer.on('pageerror',error=>{if(!error.message.includes('read_blocked_in_guest_fixture'))errors.push(error.message);});
    await producer.addInitScript(()=>{
      window.screenCaptureCalls=0;window.screenCaptureOptions=[];window.syntheticScreens=[];
      navigator.mediaDevices.getUserMedia=async()=>{throw Error('Physical microphone/camera forbidden');};
      navigator.mediaDevices.getDisplayMedia=async options=>{
        window.screenCaptureCalls++;window.screenCaptureOptions.push(options);const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=720;const context=canvas.getContext('2d');let frame=0;
        const paint=()=>{context.fillStyle='#173e50';context.fillRect(0,0,1280,720);context.fillStyle='#ffffff';context.font='52px system-ui';context.fillText('GENERATED SCREEN / WINDOW',80,250);context.fillText('VIDEO ONLY · '+frame++,80,340);context.fillRect((frame*9)%1100,500,120,30);};paint();
        const timer=setInterval(paint,30),stream=canvas.captureStream(30);stream.getVideoTracks()[0].addEventListener('ended',()=>clearInterval(timer));window.syntheticScreens.push({stream,timer});return stream;
      };
    });
    await producer.goto(base+'/control?workspace=studio',{waitUntil:'domcontentloaded'});await producer.locator('#instantSplash').waitFor({state:'hidden'});
    await producer.waitForFunction(()=>document.querySelector('[data-studio-docks="ready"]')?._studioDocks);
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    const section=producer.locator('.producer-screen-source');await section.waitFor();await until(()=>section.locator('[data-screen-share]').isEnabled(),'share enabled');
    assert.equal(await producer.evaluate(()=>screenCaptureCalls),0);const before=await read();
    await section.locator('[data-screen-share]').click();await until(()=>section.locator('[data-screen-preview]').isEnabled(),'screen publisher registered');
    assert.deepEqual((await read()).program_sources,before.program_sources);assert.deepEqual((await read()).preview_sources,before.preview_sources);
    if((await read()).preview_sources.length)await producer.locator('[data-preview-clear]').click();await until(async()=>(await read()).preview_sources.length===0,'Preview cleared');
    await section.locator('[data-screen-preview]').click();await until(async()=>(await read()).preview_sources.some(id=>id.startsWith('producer:screen:')),'screen selected in Preview');
    const source=(await read()).preview_sources[0];result.sourceEpochBound=/^producer:screen:[a-f0-9]{32}$/.test(source);assert.equal(result.sourceEpochBound,true);
    const output=await context.newPage();output.on('pageerror',error=>errors.push(error.message));await output.goto(base+'/output/studio',{waitUntil:'domcontentloaded'});
    await until(()=>producer.locator('[data-room-take]').isEnabled(),'decoded output permits Take');
    assert.deepEqual((await read()).program_sources,before.program_sources);
    await producer.locator('[data-room-take]').click();
    await until(async()=>JSON.stringify((await read()).program_sources)===JSON.stringify([source]),'authoritative Program Take');
    const taken=await read();
    await until(()=>output.frameLocator('iframe.program').locator('[data-producer-program-output]').evaluate((_node,{source,generation})=>{const snapshot=ProducerProgramOutput.snapshot();return snapshot.rendered&&snapshot.generation===generation&&JSON.stringify(snapshot.programSources)===JSON.stringify([source]);},{source,generation:taken.generation}),'current Program generation renders the taken source');
    const snapshot=await output.frameLocator('iframe.program').locator('[data-producer-program-output]').evaluate(()=>ProducerProgramOutput.snapshot());
    assert.equal(snapshot.rendered,true);assert.ok(snapshot.readySources.includes(source));result.generatedFrameReceipt=true;
    await until(()=>output.frameLocator('iframe.program').locator('video').evaluate(video=>video.videoWidth>=640),'readable generated screen resolution');
    await until(()=>output.frameLocator('iframe.program').locator('.composition-layer:not(.composition-outgoing)').evaluate(layer=>Number(getComputedStyle(layer).opacity)>.99),'visible transition completion');
    result.output=await output.frameLocator('iframe.program').locator('video').evaluate(video=>({width:video.videoWidth,height:video.videoHeight,muted:video.muted,tracks:video.srcObject.getTracks().map(track=>track.kind),fit:getComputedStyle(video).objectFit}));
    assert.deepEqual(result.output.tracks,['video']);assert.equal(result.output.fit,'contain');
    result.visibility=await output.frameLocator('iframe.program').locator('.composition-layer:not(.composition-outgoing) video').evaluate(video=>{const rect=video.getBoundingClientRect(),canvas=document.createElement('canvas');canvas.width=4;canvas.height=4;const context=canvas.getContext('2d');context.drawImage(video,0,0,4,4);return {width:rect.width,height:rect.height,display:getComputedStyle(video).display,pixel:[...context.getImageData(0,0,1,1).data],bodyHeight:document.body.getBoundingClientRect().height};});
    assert.ok(result.visibility.width>100&&result.visibility.height>100);assert.ok(result.visibility.pixel.slice(0,3).some(value=>value>10));
    await output.screenshot({path:path.join(evidence,'generated-program.png')});
    for(const theme of ['ignite','daylight'])for(const width of [390,860,1920,3840]){
      await producer.setViewportSize({width,height:width===3840?2160:1080});await producer.evaluate(theme=>document.documentElement.setAttribute('data-operator-skin',theme),theme);
      await section.scrollIntoViewIfNeeded();const checks=await section.evaluate(element=>({overflow:document.documentElement.scrollWidth>innerWidth,buttons:[...element.querySelectorAll('button')].map(button=>({height:button.getBoundingClientRect().height,width:button.getBoundingClientRect().width})),text:element.innerText}));
      assert.equal(checks.overflow,false);assert.ok(checks.buttons.every(button=>button.height>=44));assert.match(checks.text,/Video only/);await section.screenshot({path:path.join(evidence,`screen-${theme}-${width}.png`)});result.layouts.push({theme,width,overflow:false,minTarget:Math.min(...checks.buttons.map(button=>button.height))});
    }
    await section.locator('[data-screen-stop]').click();await until(async()=>!(await read()).program_sources.includes(source),'Stop removes Program');
    await until(()=>output.frameLocator('iframe.program').locator('.composition-layer .composition-tile').count().then(count=>count===0),'no fallback picture');
    result.stopRemovedProgram=true;await producer.setViewportSize({width:1920,height:1080});await section.locator('[data-screen-share]').click();await until(()=>section.locator('[data-screen-preview]').isEnabled(),'second screen source');
    const sources=await fetch(base+'/api/production/greenroom').then(r=>r.json());assert.ok(sources.producer_sources.every(item=>item.id!==source));assert.deepEqual((await read()).program_sources,[]);result.newEpochOffProgram=true;
    await producer.evaluate(()=>{for(const item of syntheticScreens){for(const track of item.stream.getTracks()){track.stop();track.dispatchEvent(new Event('ended'));}clearInterval(item.timer);}});
    await until(()=>section.locator('[data-screen-share]').isEnabled(),'ended capture recovers');
    assert.ok((await producer.evaluate(()=>screenCaptureOptions)).every(options=>options.audio===false));assert.deepEqual(errors,[]);result.passed=true;result.pageErrors=errors;
  }finally{await browser.close();fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));}
  console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
