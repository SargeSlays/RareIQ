/* Actual local editor/output acceptance with generated pictures only. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const evidence=process.argv[2],base=process.argv[3]||'http://127.0.0.1:8786';
if(!evidence||!path.isAbsolute(evidence))throw Error('Absolute evidence directory required');fs.mkdirSync(evidence,{recursive:true});
const python=path.resolve('.venv/Scripts/python.exe');
async function main(){
  assert.equal((await fetch(base+'/__qa__/guest-fixture').then(r=>r.json())).isolated_guest_fixture,true);
  const result={passed:false,generatedPicturesOnly:true,physicalCapture:false,broadcast:false,recording:false,layouts:[]},errors=[],stamp=Date.now(),previewName='Layer Preview '+stamp,sceneName='Layer Program '+stamp;
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required']});
  const api=async(url,body)=>{const response=await fetch(base+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),value=await response.json();assert.ok(response.ok,`${url}: ${value.reason}`);return value;};
  const read=()=>api('/api/production/switcher');
  async function until(check,label){const end=Date.now()+20000;while(Date.now()<end){if(await check())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timed out: '+label);}
  try{
    const context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:'reduce'});
    await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    await context.addInitScript(()=>{for(const key of ['getUserMedia','getDisplayMedia'])navigator.mediaDevices[key]=async()=>{throw Error('Physical capture forbidden');};});
    const producer=await context.newPage();producer.on('pageerror',error=>{if(!error.message.includes('read_blocked_in_guest_fixture'))errors.push(error.message);});
    await producer.goto(base+'/control?workspace=studio&layersqa=1',{waitUntil:'domcontentloaded'});await producer.locator('#instantSplash').waitFor({state:'hidden'});
    await producer.waitForFunction(()=>document.querySelector('[data-studio-docks="ready"]')?._studioDocks);
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    const ids=[];
    for(const kind of ['split','blue']){
      const data=await producer.evaluate(kind=>{const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;const ctx=canvas.getContext('2d');ctx.fillStyle=kind==='blue'?'rgb(0,0,255)':'rgb(255,0,0)';ctx.fillRect(0,0,640,360);if(kind==='split'){ctx.fillStyle='rgb(0,255,0)';ctx.fillRect(320,0,320,360);}return canvas.toDataURL('image/png').split(',')[1];},kind);
      const response=await fetch(base+'/api/creator/assets',{method:'POST',headers:{'Content-Type':'image/png','X-RareIQ-Filename':'generated-'+kind+'.png'},body:Buffer.from(data,'base64')}).then(r=>r.json());assert.equal(response.created,true);ids.push('image:'+response.asset.id);
    }
    const initial=await read();await api('/api/production/switcher/preview',{preview_sources:ids,layout:'grid',expected_generation:initial.generation,expected_preview_revision:initial.preview_revision});
    const editor=producer.locator('.production-layer-editor');await editor.waitFor();await editor.locator('summary').click();
    await until(()=>editor.locator('[data-layer-source] option').count().then(count=>count===2),'source selection synchronized');
    const output=await context.newPage();output.on('pageerror',error=>errors.push(error.message));await output.setViewportSize({width:1280,height:720});await output.goto(base+'/program?layersqa=1',{waitUntil:'domcontentloaded'});
    const original=await read();
    async function edit(field,value){const input=editor.locator('[data-layer-field="'+field+'"]');await input.fill(String(value));await input.dispatchEvent('change');}
    await editor.locator('[data-layer-source]').selectOption(ids[1]);
    for(const [field,value]of [['x',0],['y',0],['width',100],['height',100],['z',1]])await edit(field,value);
    await editor.locator('[data-layer-source]').selectOption(ids[0]);
    for(const [field,value]of [['x',10],['y',20],['width',50],['height',50],['opacity',100],['z',10]])await edit(field,value);
    await editor.locator('[data-layer-crop="left"]').fill('50');await editor.locator('[data-layer-crop="left"]').dispatchEvent('change');
    await new Promise(resolve=>setTimeout(resolve,600));
    assert.equal((await read()).generation,original.generation);assert.equal((await read()).preview_layout,'grid');result.draftDoesNotMutate=true;
    await editor.locator('[data-layer-apply]').click();await until(async()=>(await read()).preview_layout==='custom','custom Preview applied');
    const staged=await read();assert.equal(staged.generation,original.generation);assert.equal(staged.preview_layers[ids[0]].crop.left,.5);
    await until(()=>editor.locator('[data-layer-save-preview]').isEnabled(),'confirmed Preview can create scene');
    await editor.locator('[data-layer-save-preview]').click();await producer.locator('#productionSceneName').fill(previewName);await producer.locator('#productionSceneEditor').evaluate(form=>form.requestSubmit());
    await until(async()=>(await api('/api/production/scenes')).scenes.some(scene=>scene.name===previewName),'Preview scene saved without Take');assert.equal((await read()).generation,original.generation);result.savePreviewWithoutTake=true;
    const savedPreview=(await api('/api/production/scenes')).scenes.find(scene=>scene.name===previewName);
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    await until(()=>producer.locator('[data-room-take]').isEnabled(),'ID-bound output ready');
    await producer.locator('.production-layout-advanced>summary').click();await producer.locator('[data-room-transition]').selectOption('cut');await producer.locator('.production-layout-advanced>summary').click();await producer.locator('[data-room-take]').click();
    await until(async()=>{const current=await read();return current.program_composition_id===staged.preview_composition_id&&current.generation>original.generation;},'authoritative transformed Take');
    await until(()=>output.evaluate(id=>ProducerProgramOutput.snapshot().rendered&&ProducerProgramOutput.snapshot().programCompositionId===id,staged.preview_composition_id),'transformed Program receipt');
    const geometry=await output.locator('.composition-layer:not(.composition-outgoing)>.composition-tile').evaluateAll(nodes=>nodes.map(node=>{const rect=node.getBoundingClientRect();return {id:node.dataset.source,x:rect.x,y:rect.y,width:rect.width,height:rect.height,opacity:getComputedStyle(node).opacity,hidden:getComputedStyle(node).visibility,z:getComputedStyle(node).zIndex};}));
    const foreground=geometry.find(item=>item.id===ids[0]);assert.ok(Math.abs(foreground.x-128)<2);assert.ok(Math.abs(foreground.y-144)<2);assert.ok(Math.abs(foreground.width-640)<2);assert.ok(Math.abs(foreground.height-360)<2);result.geometry=geometry;
    async function pixel(name,x=180,y=190){const file=path.join(evidence,name+'.png');await output.screenshot({path:file});return JSON.parse(execFileSync(python,['-B','-c','from PIL import Image;import sys,json;print(json.dumps(list(Image.open(sys.argv[1]).convert("RGB").getpixel((int(sys.argv[2]),int(sys.argv[3]))))))',file,String(x),String(y)],{encoding:'utf8'}));}
    result.cropPixel=await pixel('cropped-program');assert.ok(result.cropPixel[1]>240&&result.cropPixel[0]<15&&result.cropPixel[2]<15,'left crop must emit green source pixels rather than red or covered blue');
    const beforeDraft=(await read()).generation;
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-scenes'));
    await producer.locator('[data-scene-id="'+savedPreview.id+'"]').getByRole('button',{name:'Preview',exact:true}).click();
    await until(async()=>(await read()).preview_composition_id===staged.preview_composition_id,'saved custom Preview recalled after bus swap');
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    await until(()=>editor.locator('[data-layer-source] option').evaluateAll(nodes=>nodes.map(node=>node.value)).then(values=>values.includes(ids[0])),'recalled editor sources');
    await editor.locator('[data-layer-source]').selectOption(ids[0]);await editor.locator('.production-layer-stage').scrollIntoViewIfNeeded();
    await producer.waitForTimeout(300);
    const stageBox=await editor.locator('.production-layer-stage').boundingBox(),hitBox=await editor.locator('[data-layer-hit]').first().boundingBox();
    await producer.mouse.move(hitBox.x+hitBox.width/2,hitBox.y+hitBox.height/2);await producer.mouse.down();await producer.mouse.move(hitBox.x+hitBox.width/2+stageBox.width*.05,hitBox.y+hitBox.height/2,{steps:3});await producer.mouse.up();
    result.pointer={stageBox,hitBox,xAfterDrag:await editor.locator('[data-layer-field="x"]').inputValue()};assert.ok(Number(result.pointer.xAfterDrag)>14);assert.equal((await read()).generation,beforeDraft);
    await editor.locator('[data-layer-hit]').first().focus();await producer.keyboard.press('ArrowRight');assert.ok(Number(await editor.locator('[data-layer-field="x"]').inputValue())>15);
    const resize=await editor.locator('[data-layer-resize]').boundingBox();await producer.mouse.move(resize.x+resize.width/2,resize.y+resize.height/2);await producer.mouse.down();await producer.mouse.move(resize.x+resize.width/2+stageBox.width*.05,resize.y+resize.height/2,{steps:3});await producer.mouse.up();assert.ok(Number(await editor.locator('[data-layer-field="width"]').inputValue())>54);
    assert.equal((await read()).generation,beforeDraft);result.pointerKeyboardDraftOnly=true;
    await editor.locator('[data-layer-apply]').click();await until(async()=>{const current=await read();return current.preview_layers[ids[0]].x>.15;},'fractional pointer draft applied');await until(()=>editor.locator('[data-layer-save-preview]').isEnabled(),'fractional pointer Apply confirmed');assert.equal((await read()).generation,beforeDraft);result.fractionalPointerApplyConfirmed=true;
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-scenes'));await producer.locator('[data-scene-id="'+savedPreview.id+'"]').getByRole('button',{name:'Preview',exact:true}).click();await until(async()=>(await read()).preview_layers[ids[0]].x===.1,'original saved geometry recalled after pointer proof');await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    await editor.locator('[data-layer-reload]').click();
    await editor.locator('[data-layer-source]').selectOption(ids[0]);await editor.locator('[data-layer-locked]').check();assert.equal(await editor.locator('[data-layer-field="x"]').isDisabled(),true);await editor.locator('[data-layer-locked]').uncheck();
    await edit('opacity',50);await editor.locator('[data-layer-apply]').click();await until(async()=>(await read()).preview_layers?.[ids[0]]?.opacity===.5,'opacity staged');const opacityStaged=await read();await until(()=>producer.locator('[data-room-take]').isEnabled(),'opacity ready');await producer.locator('[data-room-take]').click();await until(async()=>(await read()).generation>beforeDraft,'opacity Taken');
    await until(()=>output.evaluate(id=>ProducerProgramOutput.snapshot().rendered&&ProducerProgramOutput.snapshot().programCompositionId===id,opacityStaged.preview_composition_id),'opacity exact-generation rendered');result.opacityPixel=await pixel('opacity-program');assert.ok(result.opacityPixel[1]>100&&result.opacityPixel[1]<155&&result.opacityPixel[2]>100&&result.opacityPixel[2]<155,'opacity must blend green with blue');
    // Save Current and recall through the actual scene controls, not a fixture API shortcut.
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-scenes'));
    await producer.locator('#productionSaveScene').click();await producer.locator('#productionSceneName').fill(sceneName);
    await producer.locator('#productionSceneEditor').evaluate(form=>form.requestSubmit());
    await until(async()=>(await api('/api/production/scenes')).scenes.some(scene=>scene.name===sceneName),'saved custom scene');
    const saved=(await api('/api/production/scenes')).scenes.find(scene=>scene.name===sceneName);assert.equal(saved.layout,'custom');assert.equal(saved.layers[ids[0]].opacity,.5);assert.equal(saved.layers[ids[0]].crop.left,.5);
    await api('/api/production/switcher/preview',{preview_sources:['camera:3'],layout:'auto',expected_generation:(await read()).generation,expected_preview_revision:(await read()).preview_revision});
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));await until(()=>producer.locator('[data-room-take]').isEnabled(),'alternate camera ready');await producer.locator('[data-room-take]').click();await until(async()=>(await read()).program_sources[0]==='camera:3','alternate camera Taken');
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-scenes'));
    await producer.locator('[data-scene-id="'+saved.id+'"]').getByRole('button',{name:'Preview',exact:true}).click();
    await until(async()=>{const current=await read();return current.preview_layout==='custom'&&current.preview_layers[ids[0]]?.opacity===.5;},'saved layer recall into Preview');result.savedSceneRoundTrip=true;
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    const recalled=await read();await until(()=>producer.locator('[data-room-take]').isEnabled(),'recalled exact output ready');await producer.locator('[data-room-take]').click();await until(()=>output.evaluate(id=>ProducerProgramOutput.snapshot().rendered&&ProducerProgramOutput.snapshot().programCompositionId===id,recalled.preview_composition_id),'recalled Program exact-ID receipt');result.recallPixel=await pixel('recalled-program');assert.ok(result.recallPixel[1]>100&&result.recallPixel[1]<155&&result.recallPixel[2]>100&&result.recallPixel[2]<155);
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-scenes'));await producer.locator('[data-scene-id="'+saved.id+'"]').getByRole('button',{name:'Preview',exact:true}).click();await until(async()=>(await read()).preview_composition_id===recalled.preview_composition_id,'editor restored for layout checks');await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    for(const theme of ['ignite','daylight'])for(const width of [390,860,1920,3840]){
      await producer.setViewportSize({width,height:width===3840?2160:1080});await producer.evaluate(theme=>{document.documentElement.dataset.operatorSkin=theme;document.documentElement.dataset.theme=theme==='daylight'?'light':'dark';},theme);
      await editor.scrollIntoViewIfNeeded();const checks=await editor.evaluate(node=>({overflow:document.documentElement.scrollWidth>innerWidth,localOverflow:node.scrollWidth>node.clientWidth+1,buttons:[...node.querySelectorAll('.production-layer-actions button,input[type=number],select')].map(button=>({width:button.getBoundingClientRect().width,height:button.getBoundingClientRect().height}))}));
      assert.equal(checks.overflow,false);assert.equal(checks.localOverflow,false);assert.ok(checks.buttons.every(button=>button.height>=44));await editor.screenshot({path:path.join(evidence,`layers-${theme}-${width}.png`)});result.layouts.push({theme,width,...checks});
    }
    assert.deepEqual(errors,[]);result.passed=true;result.errors=errors;
  }finally{fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));await browser.close();}
  console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
