/* Actual compositor pixels from generated image fixtures. No server/device/output. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const evidence=process.argv[2];if(!evidence||!path.isAbsolute(evidence))throw Error('Absolute evidence path required');fs.mkdirSync(evidence,{recursive:true});
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']});
  const result={passed:false,generatedImagesOnly:true,physicalCapture:false,broadcast:false,recording:false,checks:[]};
  try{
    const page=await browser.newPage({viewport:{width:640,height:360},reducedMotion:'reduce'});
    await page.route('**/*',route=>{
      const url=new URL(route.request().url());
      if(url.hostname!=='127.0.0.1')return route.abort();
      if(url.pathname==='/fixture')return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body style="margin:0;background:black"><main id="canvas" style="width:640px;height:360px"></main></body></html>'});
      if(url.pathname.startsWith('/api/creator/assets/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="90"><path fill="red" d="M0 0h160v90H0z"/><path fill="blue" d="M160 0h160v90H160z"/></svg>'});
      return route.abort();
    });
    await page.goto('http://127.0.0.1:1/fixture');
    await page.addStyleTag({content:fs.readFileSync('rareiq/web/static/program_composition.css','utf8')});
    for(const file of ['production_layer_editor.js','program_composition.js'])await page.addScriptTag({content:fs.readFileSync('rareiq/web/static/'+file,'utf8')});
    await page.evaluate(()=>{
      window.fixtureId='image:12345678-1234-1234-1234-123456789abc';window.statuses=[];
      window.testView=new ProducerCompositionView({container:document.querySelector('#canvas'),muted:true,onStatus:value=>statuses.push(value)});
      window.show=(generation,rotation,cropRight=0,opacity=1)=>testView.render({generation,preview_sources:[],program_sources:[fixtureId],program_layout:'custom',program_layers:{[fixtureId]:{...ProducerLayerEditor.defaults(),x:.25,y:.375,width:.5,height:.25,rotation,group:'Fixture group',opacity,crop:{top:0,right:cropRight,bottom:0,left:0}}},program_composition_id:String(generation+1).repeat(64),transition:'cut',duration_ms:0});
      show(0,0);
    });
    for(const [generation,rotation,crop,opacity,name] of [[0,0,0,1,'baseline'],[1,90,0,1,'clockwise'],[2,-90,0,1,'counterclockwise'],[3,90,.5,.5,'crop-opacity']]){
      if(generation)await page.evaluate(args=>show(...args),[generation,rotation,crop,opacity]);
      await page.waitForFunction(value=>statuses.at(-1)?.rendered===true&&statuses.at(-1)?.generation===value,generation);
      const geometry=await page.locator('.composition-layer:not(.composition-outgoing)>.composition-tile').evaluate(node=>{const box=node.getBoundingClientRect();return {x:box.x,y:box.y,width:box.width,height:box.height,transform:getComputedStyle(node).transform,origin:getComputedStyle(node).transformOrigin};});
      await page.screenshot({path:path.join(evidence,name+'.png')});result.checks.push({name,rotation,crop,opacity,geometry});
    }
    const samples=JSON.parse(execFileSync(path.resolve('.venv/Scripts/python.exe'),['-X','utf8','-B','-c',
      'from PIL import Image;import json,sys,pathlib;p=pathlib.Path(sys.argv[1]);points=[(200,180),(440,180),(320,80),(320,280)];print(json.dumps({n:[Image.open(p/(n+".png")).convert("RGB").getpixel(pt) for pt in points] for n in ["baseline","clockwise","counterclockwise","crop-opacity"]}))',evidence],{encoding:'utf8'}));
    assert.deepEqual(samples.baseline,[[255,0,0],[0,0,255],[0,0,0],[0,0,0]]);
    assert.deepEqual(samples.clockwise,[[0,0,0],[0,0,0],[255,0,0],[0,0,255]]);
    assert.deepEqual(samples.counterclockwise,[[0,0,0],[0,0,0],[0,0,255],[255,0,0]]);
    assert.deepEqual(samples['crop-opacity'],[[0,0,0],[0,0,0],[128,0,0],[128,0,0]]);
    assert.ok(Math.abs(result.checks[1].geometry.width-90)<.1);assert.ok(Math.abs(result.checks[1].geometry.height-320)<.1);
    result.samples=samples;result.passed=true;await page.evaluate(()=>testView.close());
  }finally{fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));await browser.close();}
  console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
