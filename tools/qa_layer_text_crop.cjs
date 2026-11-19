/* Real compositor pixels with generated literal text; no server or devices. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const evidence=process.argv[2];if(!evidence||!path.isAbsolute(evidence))throw Error('Absolute evidence path required');fs.mkdirSync(evidence,{recursive:true});
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']});
  const result={passed:false,generatedTextOnly:true,physicalCapture:false,broadcast:false,recording:false};
  try{
    const page=await browser.newPage({viewport:{width:640,height:360},reducedMotion:'reduce'});await page.route('**/*',route=>route.abort());
    await page.setContent('<!doctype html><html><body style="margin:0;background:black"><main id="canvas" style="width:640px;height:360px"></main></body></html>');
    await page.addStyleTag({content:fs.readFileSync('rareiq/web/static/program_composition.css','utf8')});
    for(const file of ['production_layer_editor.js','program_composition.js'])await page.addScriptTag({content:fs.readFileSync('rareiq/web/static/'+file,'utf8')});
    await page.evaluate(()=>{
      window.textId='text:12345678-1234-1234-1234-123456789abc';window.statuses=[];
      window.testView=new ProducerCompositionView({container:document.querySelector('#canvas'),muted:true,onStatus:value=>statuses.push(value),fetch:async()=>({ok:true,json:async()=>({source:{id:textId,name:'Generated crop test',text:'MMMMMMMM',position:'center'}})})});
      window.showCrop=right=>testView.render({generation:right?1:0,preview_sources:[],program_sources:[textId],program_layout:'custom',program_layers:{[textId]:{...ProducerLayerEditor.defaults(),crop:{top:0,right,bottom:0,left:0}}},program_composition_id:(right?'b':'a').repeat(64),transition:'cut',duration_ms:0});showCrop(0);
    });
    await page.waitForFunction(()=>statuses.at(-1)?.rendered===true);await page.screenshot({path:path.join(evidence,'text-baseline.png')});
    await page.evaluate(()=>showCrop(.5));await page.waitForFunction(()=>statuses.at(-1)?.rendered===true&&statuses.at(-1)?.generation===1);
    result.clipPath=await page.locator('.composition-text-content').evaluate(node=>getComputedStyle(node).clipPath);assert.match(result.clipPath,/50%/);await page.screenshot({path:path.join(evidence,'text-cropped.png')});
    const count=file=>Number(execFileSync(path.resolve('.venv/Scripts/python.exe'),['-B','-c','from PIL import Image;import sys;print(sum(all(c>240 for c in p) for p in Image.open(sys.argv[1]).convert("RGB").getdata()))',path.join(evidence,file)],{encoding:'utf8'}));
    result.baselineWhitePixels=count('text-baseline.png');result.croppedWhitePixels=count('text-cropped.png');assert.ok(result.baselineWhitePixels>100);assert.ok(result.croppedWhitePixels>result.baselineWhitePixels*.3&&result.croppedWhitePixels<result.baselineWhitePixels*.65);result.passed=true;
  }finally{fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));await browser.close();}
  console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
