/* Disposable generated-picture proof. Never opens devices or external destinations. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const directory=process.argv[2],base=process.argv[3]||'http://127.0.0.1:8786';
if(!directory||!path.isAbsolute(directory)||fs.existsSync(directory))throw Error('A new absolute evidence directory is required');
fs.mkdirSync(directory,{recursive:true});
const result={passed:false,generatedMediaOnly:true,physicalDevices:false,broadcast:false,recording:false,layouts:[],captures:[]},errors=[];
const api=async(url,body)=>{const response=await fetch(base+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{}),value=await response.json();assert.ok(response.ok,url+': '+value.reason);return value;};
const read=()=>api('/api/production/switcher');
async function until(check,label){const end=Date.now()+20000;while(Date.now()<end){if(await check())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timed out: '+label);}
async function main(){
  assert.equal((await api('/__qa__/guest-fixture')).isolated_guest_fixture,true);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required']});
  try{
    const context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:'reduce'});
    await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    await context.addInitScript(()=>{for(const key of ['getUserMedia','getDisplayMedia'])navigator.mediaDevices[key]=async()=>{throw Error('Physical capture forbidden');};});
    const producer=await context.newPage();producer.on('pageerror',error=>{if(!error.message.includes('read_blocked_in_guest_fixture'))errors.push(error.message);});
    await producer.goto(base+'/control?workspace=studio&groupsqa=1',{waitUntil:'domcontentloaded'});await producer.locator('#instantSplash').waitFor({state:'hidden'});
    await producer.waitForFunction(()=>document.querySelector('[data-studio-docks="ready"]')?._studioDocks);
    const dock=async tool=>producer.evaluate(tool=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool(tool),tool);
    await dock('production-greenroom');
    const ids=[];
    for(const kind of ['split','blue']){
      const data=await producer.evaluate(kind=>{const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;const ctx=canvas.getContext('2d');ctx.fillStyle=kind==='blue'?'rgb(0,0,255)':'rgb(255,0,0)';ctx.fillRect(0,0,640,360);if(kind==='split'){ctx.fillStyle='rgb(0,255,0)';ctx.fillRect(320,0,320,360);}return canvas.toDataURL('image/png').split(',')[1];},kind);
      const response=await fetch(base+'/api/creator/assets',{method:'POST',headers:{'Content-Type':'image/png','X-RareIQ-Filename':'generated-group-'+kind+'.png'},body:Buffer.from(data,'base64')}).then(r=>r.json());assert.equal(response.created,true);ids.push('image:'+response.asset.id);
    }
    const initial=await read();await api('/api/production/switcher/preview',{preview_sources:ids,layout:'grid',expected_generation:initial.generation,expected_preview_revision:initial.preview_revision});
    const editor=producer.locator('.production-layer-editor');await editor.waitFor();await editor.locator('summary').click();
    await until(()=>editor.locator('[data-layer-source] option').count().then(n=>n===2),'editor sources');
    const output=await context.newPage();output.on('pageerror',error=>errors.push(error.message));await output.setViewportSize({width:1280,height:720});await output.goto(base+'/program?groupsqa=1',{waitUntil:'domcontentloaded'});
    await producer.bringToFront();
    const edit=async(field,value)=>{const input=editor.locator('[data-layer-field="'+field+'"]');await input.fill(String(value));await input.dispatchEvent('change');};
    for(let i=0;i<ids.length;i++){await editor.locator('[data-layer-source]').selectOption(ids[i]);for(const [field,value]of [['x',i?50:10],['y',20],['width',20],['height',20],['rotation',i?0:90]])await edit(field,value);}
    for(const id of ids)await editor.locator('[data-layer-member]').evaluateAll((nodes,id)=>{const node=nodes.find(node=>node.dataset.layerMember===id);node.checked=true;node.dispatchEvent(new Event('change',{bubbles:true}));},id);
    const groupName='<Host & title>';await editor.locator('[data-layer-group-name]').fill(groupName);await editor.locator('[data-layer-group-create]').click();
    assert.equal(await editor.locator('[data-layer-group]').inputValue(),groupName);assert.equal(await editor.locator('[data-layer-field="rotation"]').isDisabled(),true);
    await edit('x',20);await edit('y',25);await edit('width',50);await edit('height',25);
    assert.equal((await read()).preview_layout,'grid');assert.equal((await read()).generation,initial.generation);result.groupDraftDoesNotMutate=true;
    await editor.locator('.production-layer-stage').scrollIntoViewIfNeeded();
    const stage=await editor.locator('.production-layer-stage').boundingBox(),hit=await editor.locator('[data-layer-group-hit]').boundingBox();
    await producer.mouse.move(hit.x+hit.width/2,hit.y+hit.height/2);await producer.mouse.down();await producer.mouse.move(hit.x+hit.width/2+stage.width*.03,hit.y+hit.height/2,{steps:3});await producer.mouse.up();
    const draggedX=Number(await editor.locator('[data-layer-field="x"]').inputValue());assert.ok(draggedX>22.5);
    await editor.locator('[data-layer-group-hit]').focus();await producer.waitForTimeout(1200);assert.equal(await editor.locator('[data-layer-group-hit]').evaluate(node=>node===document.activeElement),true);result.canvasFocusSurvivesPoll=true;
    await producer.keyboard.press('ArrowLeft');result.groupKeyboard={before:draggedX,after:Number(await editor.locator('[data-layer-field="x"]').inputValue()),status:await editor.locator('[data-layer-status]').innerText()};assert.ok(result.groupKeyboard.after<draggedX-.5,JSON.stringify(result.groupKeyboard));
    const handle=await editor.locator('[data-layer-group-resize]').boundingBox();await producer.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await producer.mouse.down();await producer.mouse.move(handle.x+handle.width/2+stage.width*.02,handle.y+handle.height/2+stage.height*.02,{steps:3});await producer.mouse.up();assert.ok(Number(await editor.locator('[data-layer-field="width"]').inputValue())>51);result.pointerKeyboardGroupEdit=true;
    for(const [field,value]of [['x',20],['y',25],['width',50],['height',25]])await edit(field,value);
    await editor.locator('[data-layer-source]').selectOption(ids[1]);await editor.locator('[data-layer-locked]').check();await editor.locator('[data-layer-group]').selectOption(groupName);assert.equal(await editor.locator('[data-layer-field="x"]').isDisabled(),true);assert.equal(await editor.locator('[data-layer-ungroup]').isDisabled(),true);
    const lockedX=await editor.locator('[data-layer-field="x"]').inputValue();await editor.locator('[data-layer-group-hit]').focus();await producer.keyboard.press('ArrowRight');assert.equal(await editor.locator('[data-layer-field="x"]').inputValue(),lockedX);assert.match(await editor.locator('[data-layer-status]').innerText(),/Unlock/);result.lockedMemberBlocksWholeGroup=true;
    await editor.locator('[data-layer-source]').selectOption(ids[1]);await editor.locator('[data-layer-locked]').uncheck();await editor.locator('[data-layer-group]').selectOption(groupName);
    await edit('width',1);assert.equal(await editor.locator('[data-layer-field="width"]').inputValue(),'50');assert.match(await editor.locator('[data-layer-status]').innerText(),/not applied/);result.invalidResizeAtomic=true;
    await editor.locator('[data-layer-apply]').click();await until(()=>editor.locator('[data-layer-save-preview]').isEnabled(),'confirmed group Apply');const staged=await read();assert.equal(staged.generation,initial.generation);assert.equal(staged.preview_layers[ids[0]].rotation,90);assert.ok(ids.every(id=>staged.preview_layers[id].group===groupName));result.appliedLayers=staged.preview_layers;
    const sceneName='Rotation group '+Date.now();await editor.locator('[data-layer-save-preview]').click();await producer.locator('#productionSceneName').fill(sceneName);await producer.locator('#productionSceneEditor').evaluate(form=>form.requestSubmit());await until(async()=>(await api('/api/production/scenes')).scenes.some(s=>s.name===sceneName),'saved grouped Preview scene');
    const scene=(await api('/api/production/scenes')).scenes.find(s=>s.name===sceneName);assert.equal(scene.layers[ids[0]].rotation,90);assert.equal(scene.layers[ids[1]].group,groupName);result.savedScenePreservesGroupRotation=true;
    await dock('production-greenroom');await producer.locator('.production-layout-advanced>summary').click();await producer.locator('[data-room-transition]').selectOption('cut');await producer.locator('.production-layout-advanced>summary').click();
    await until(()=>producer.locator('[data-room-take]').isEnabled(),'exact grouped receipt');await producer.locator('[data-room-take]').click();await until(()=>output.evaluate(id=>ProducerProgramOutput.snapshot().rendered&&ProducerProgramOutput.snapshot().programCompositionId===id,staged.preview_composition_id),'rotated Program pixels');
    const rotation=await output.locator('.composition-layer:not(.composition-outgoing)>.composition-tile').evaluateAll(nodes=>nodes.map(node=>({id:node.dataset.source,transform:getComputedStyle(node).transform})));assert.match(rotation.find(n=>n.id===ids[0]).transform,/matrix\(0, 1, -1, 0/);result.rotationMatrices=rotation;
    const image=path.join(directory,'rotated-program.png');await output.screenshot({path:image});const first=staged.preview_layers[ids[0]],cx=Math.round((first.x+first.width/2)*1280),cy=Math.round((first.y+first.height/2)*720);
    result.rotationPixels=JSON.parse(execFileSync(path.resolve('.venv/Scripts/python.exe'),['-B','-c','from PIL import Image;import sys,json;i=Image.open(sys.argv[1]).convert("RGB");x=int(sys.argv[2]);y=int(sys.argv[3]);print(json.dumps([list(i.getpixel((x,y-30))),list(i.getpixel((x,y+30)))]))',image,String(cx),String(cy)],{encoding:'utf8'}));assert.ok(result.rotationPixels[0][0]>240&&result.rotationPixels[0][1]<15);assert.ok(result.rotationPixels[1][1]>240&&result.rotationPixels[1][0]<15);
    const generation=(await read()).generation;
    await dock('production-scenes');await producer.locator('[data-scene-id="'+scene.id+'"]').getByRole('button',{name:'Preview',exact:true}).click();await dock('production-greenroom');await until(()=>editor.locator('[data-layer-group] option').count().then(n=>n===2),'grouped scene recalled');await editor.locator('[data-layer-reload]').click();await editor.locator('[data-layer-group]').selectOption(groupName);await editor.locator('[data-layer-ungroup]').click();await editor.locator('[data-layer-apply]').click();await until(async()=>(await read()).preview_layers[ids[0]].group==='','ungroup Apply');const ungrouped=await read();assert.equal(ungrouped.generation,generation);assert.equal(ungrouped.preview_layers[ids[0]].rotation,90);assert.equal(ungrouped.preview_layers[ids[0]].x,staged.preview_layers[ids[0]].x);result.ungroupPreservesGeometryProgram=true;
    await dock('production-scenes');await producer.locator('[data-scene-id="'+scene.id+'"]').getByRole('button',{name:'Preview',exact:true}).click();await until(async()=>(await read()).preview_composition_id===staged.preview_composition_id,'saved exact group/rotation recalled');await dock('production-greenroom');await editor.locator('[data-layer-reload]').click();result.savedSceneExactRecall=true;
    for(const theme of ['ignite','daylight'])for(const width of [1920,390]){
      await producer.setViewportSize({width,height:1080});await producer.evaluate(theme=>{document.documentElement.dataset.operatorSkin=theme;document.documentElement.dataset.theme=theme==='daylight'?'light':'dark';},theme);
      await editor.locator('[data-layer-group]').selectOption(groupName);
      const metrics=await editor.evaluate(node=>({pageOverflow:document.documentElement.scrollWidth>innerWidth,localOverflow:node.scrollWidth>node.clientWidth+1,targets:[...node.querySelectorAll('.production-layer-actions button,input[type=number],input[type=text],select')].map(node=>({width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height}))}));assert.equal(metrics.pageOverflow,false);assert.equal(metrics.localOverflow,false);assert.ok(metrics.targets.every(t=>t.height>=44));result.layouts.push({theme,width,...metrics});
      for(const [name,selector]of [['groups','[data-layer-group-name]'],['canvas','.production-layer-stage'],['geometry','[data-layer-field="x"]']]){await editor.locator(selector).evaluate(node=>node.scrollIntoView({block:'center'}));await producer.waitForTimeout(100);const file=path.join(directory,name+'-'+theme+'-'+width+'.png');await producer.screenshot({path:file});result.captures.push({name,theme,width,file});}
    }
    assert.deepEqual(errors,[]);result.errors=errors;result.passed=true;
  }finally{fs.writeFileSync(path.join(directory,'results.json'),JSON.stringify(result,null,2));await browser.close();}
  console.log(JSON.stringify({passed:result.passed,layouts:result.layouts.length,captures:result.captures.length,rotationPixels:result.rotationPixels}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
