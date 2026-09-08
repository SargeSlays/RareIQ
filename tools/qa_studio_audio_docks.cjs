// Uses the running UI with isolated preferences; blocks writes and media activation.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/**',route=>{
      if(!['GET','HEAD'].includes(route.request().method())){const path=new URL(route.request().url()).pathname;if(!['/api/camera/start','/api/recognition/set-context','/api/output/soundboard'].includes(path))errors.push('Unexpected API write blocked');return route.abort();}
      return route.continue();
    });
    await page.addInitScript(()=>{
      window.mediaStarts=0;
      navigator.mediaDevices.getUserMedia=async()=>{window.mediaStarts++;throw Error('QA blocks media capture');};
      HTMLMediaElement.prototype.play=function(){window.mediaStarts++;return Promise.resolve();};
    });
    await page.goto(origin+'/control?workspace=studio&audio-docks=1');
    await page.waitForSelector('[data-studio-docks="ready"]');
    const drawer=page.getByRole('dialog',{name:'Session tools'}),tools=page.getByRole('button',{name:/^Session tools/});
    await page.evaluate(()=>{
      window.audioNodes=['soundboardAppGrid','soundboardAppUpload','voiceModInput','voiceModGain','voiceModStart'].map(id=>document.getElementById(id));
      const raw=JSON.parse(localStorage.getItem('rareiq.studio.docks.v1')||'{"version":1,"tools":{}}');
      delete raw.tools['workspace-soundboard'];delete raw.tools['workspace-voice-mod'];
      localStorage.setItem('rareiq.studio.docks.v1',JSON.stringify(raw));
      localStorage.setItem('rareiq.studio.toolsets.v1',JSON.stringify({version:1,active:'old',workspaces:['soundboard','voice-mod'],profiles:[{id:'old',label:'Older audio set',layout:raw,workspaces:['soundboard','voice-mod']}]}));
    });
    await page.reload();await page.waitForSelector('[data-studio-docks="ready"]');
    await page.evaluate(()=>{window.audioNodes=['soundboardAppGrid','soundboardAppUpload','voiceModInput','voiceModGain','voiceModStart'].map(id=>document.getElementById(id));});
    await tools.click();
    assert.equal(await drawer.getByLabel('Soundboard',{exact:true}).isChecked(),true);
    assert.equal(await drawer.getByLabel('Voice studio',{exact:true}).isChecked(),true);
    await drawer.getByRole('button',{name:'Clear all tools',exact:true}).click();
    await drawer.getByLabel('Soundboard',{exact:true}).check();await drawer.getByLabel('Voice studio',{exact:true}).check();
    await drawer.getByLabel('Soundboard position',{exact:true}).selectOption('left');
    await drawer.getByLabel('Voice studio position',{exact:true}).selectOption('right');
    await drawer.getByRole('button',{name:'Close',exact:true}).click();
    const sound=page.locator('.studio-dock-tool .soundboard-app-shell'),voice=page.locator('.studio-dock-tool .voice-mod-shell');
    assert.equal(await sound.isVisible(),true);assert.equal(await voice.isVisible(),true);
    assert.equal(await sound.locator('.soundboard-output-controls').isVisible(),false);await sound.getByText('Audio output & routing',{exact:true}).click();assert.equal(await sound.locator('.soundboard-output-controls').isVisible(),true);await sound.getByText('Audio output & routing',{exact:true}).click();
    await page.locator('#soundboardSearch').fill('Unsaved audio search');
    await page.evaluate(()=>{
      document.getElementById('voiceModGain').value='135';document.getElementById('voiceModGain').dispatchEvent(new Event('input',{bubbles:true}));
      window.padClicks=0;const pad=document.createElement('button');pad.dataset.soundboardShortcut='9';pad.textContent='QA inert pad';pad.id='qaInertPad';pad.onclick=()=>window.padClicks++;document.getElementById('soundboardAppGrid').append(pad);
    });
    await sound.focus();await page.keyboard.press('9');assert.equal(await page.evaluate(()=>padClicks),1);
    await sound.focus();await page.keyboard.press('b');await voice.focus();await page.keyboard.press('1');
    await page.locator('.nav-button[data-target="soundboard"]').click();
    assert.equal(await page.locator('.workspace[data-workspace="soundboard"] .soundboard-app-shell').isVisible(),true);
    await page.locator('.nav-button[data-target="voice-mod"]').click();
    assert.equal(await page.locator('.workspace[data-workspace="voice-mod"] .voice-mod-shell').isVisible(),true);
    await page.locator('.nav-button[data-target="broadcast"]').click();
    assert.equal(await sound.isVisible(),true);assert.equal(await voice.isVisible(),true);
    assert.equal(await page.locator('#soundboardSearch').inputValue(),'Unsaved audio search');
    assert.equal(await page.locator('#voiceModGain').inputValue(),'135');
    assert.equal(await page.evaluate(()=>audioNodes.every(node=>node===document.getElementById(node.id))),true);
    await page.getByRole('button',{name:'Options for Voice studio',exact:true}).click();
    const popupReady=page.waitForEvent('popup');await drawer.getByRole('button',{name:'Pop out Voice studio',exact:true}).click();
    const popup=await popupReady;await popup.waitForSelector('#voiceModGain');assert.equal(await popup.locator('[data-tool-workspace=voice-mod]').count(),1);
    await popup.locator('#voiceModGain').fill('145');
    assert.equal(await page.locator('#voiceModGain').inputValue(),'145');
    await popup.getByRole('button',{name:'Return to main studio'}).click();await page.waitForFunction(()=>!document.getElementById('studioDockLibrary').open);await popup.close();
    assert.equal(await page.locator('#voiceModGainValue').textContent(),'145%');
    fs.mkdirSync('.tmp/refinish',{recursive:true});const results=[];
    for(const skin of ['ignite','daylight'])for(const [width,height] of [[1920,1080],[3840,2160],[1366,768],[720,900]]){
      await page.setViewportSize({width,height});await page.evaluate(s=>applyStudioTheme(s,true),skin);await page.waitForTimeout(180);
      const bounds=await page.evaluate(()=>({pageOverflow:document.documentElement.scrollWidth>innerWidth,tools:[...document.querySelectorAll('.studio-dock-tool [data-studio-workspace-tool]')].map(panel=>({name:panel.dataset.studioWorkspaceTool,overflow:panel.scrollWidth>panel.clientWidth+2}))}));
      assert.equal(bounds.pageOverflow,false);assert.ok(bounds.tools.every(tool=>!tool.overflow),JSON.stringify(bounds));results.push({skin,width,...bounds});
      await page.locator('[data-tool-workspace]').evaluateAll(nodes=>nodes.forEach(node=>node.scrollTop=0));
      if(width===1920)await page.screenshot({path:`.tmp/refinish/audio-docks-${skin}.png`,mask:[page.locator('img:not(.brand-lockup-image):not(.nav-app-icon img),video')]});
    }
    await page.setViewportSize({width:1920,height:1080});await page.getByLabel('Studio view',{exact:true}).selectOption('setup');
    assert.equal(await page.locator('.studio-dock-tool .voice-mod-shell').count(),0);
    await page.getByLabel('Studio view',{exact:true}).selectOption('live');assert.equal(await voice.isVisible(),true);
    assert.equal(await page.evaluate(()=>mediaStarts),0);assert.deepEqual(errors,[]);
    console.log(JSON.stringify({migration:'passed',ownership:'original nodes retained',navigation:'dock and workspace passed',popout:'edit propagation passed',mediaStarts:0,results}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
