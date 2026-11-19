/* Real Settings markup/browser; synthetic public metadata responses only. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const evidence=process.argv[2],root=path.resolve(__dirname,'..');
if(!evidence||!path.isAbsolute(evidence)||fs.existsSync(evidence))throw Error('A fresh absolute evidence directory is required.');
fs.mkdirSync(evidence,{recursive:true});
async function main(){
  const browser=await chromium.launch({headless:true,channel:'chrome'}),context=await browser.newContext({viewport:{width:860,height:1080},reducedMotion:'reduce'}),page=await context.newPage(),errors=[],results={passed:false,synthetic:true,realProviderCalls:false,realBroadcast:false,layouts:[]};
  page.on('pageerror',error=>errors.push(error.message));
  await context.route('**/*',route=>{
    const url=new URL(route.request().url()),name=url.pathname==='/'?'settings.html':url.pathname.slice(1),allowed=new Set(['settings.html','settings.css','settings-stream-metadata.js','assets/producer-please.tokens.css','assets/icon-192.png']);
    if(url.origin!=='https://metadata-fixture.local')return route.abort();
    if(['settings.js','settings-accounts.js','settings-provider-accounts.js','settings-stream-info.js'].includes(name))return route.fulfill({contentType:'application/javascript',body:''});
    if(!allowed.has(name))return route.abort();const file=name.startsWith('assets/')?path.resolve(root,'../rareiq/web/static/brand/producer-please-v2',name.slice(7)):path.join(root,name);return route.fulfill({path:file});
  });
  try{
    await page.goto('https://metadata-fixture.local/');await page.evaluate(()=>{
      document.querySelector('#streamInfo').open=true;document.querySelector('#streamInfoSharedTitle').value='Synthetic saved show';document.querySelector('#streamInfoSharedDescription').value='Synthetic saved description';
      const qa=window.metadataQa={calls:[],busy:[],mode:'normal',platform:'twitch'};
      window.metadataEditor=ProducerStreamMetadata.create({root:document.querySelector('#streamMetadata'),onBusy:value=>qa.busy.push(value),api:{streamMetadata:async value=>{
        qa.calls.push(value);if(value.action==='inspect'){const result={platform:value.platform,authorized:true,editable:true,channel_id:'synthetic-channel',public_label:'Synthetic connected channel',capabilities:{title:true,description:value.platform==='youtube',category_id:true,tags:true}};if(value.broadcastId)result.broadcast_id=value.broadcastId;else result.broadcasts=value.platform==='youtube'?[{id:'synthetic-broadcast',title:'Synthetic planned broadcast',state:'ready'}]:[];return result;}
        if(value.action==='categories')return {categories:[{id:'1234',name:'Synthetic official category'}]};if(value.action==='permission')return {ok:true};return {state:qa.mode==='uncertain'?'unconfirmed':'applied',request_id:value.requestId};
      }}});
      metadataEditor.setContext({destination:{id:'synthetic-destination',name:'Synthetic Twitch',platform:'twitch'},revision:3,dirty:false,locked:false});
    });
    await page.waitForFunction(()=>!document.querySelector('#streamMetadataApply').disabled);assert.equal(await page.evaluate(()=>metadataQa.calls.filter(value=>value.action==='categories').length),0);
    await page.locator('#streamMetadataQuery').fill('Synthetic game');await page.locator('#streamMetadataSearch').click();await page.locator('#streamMetadataCategory').selectOption('1234');await page.evaluate(()=>{metadataQa.mode='uncertain';});await page.locator('#streamMetadataApply').click();await page.locator('#streamMetadataStatus').filter({hasText:'not confirmed'}).waitFor();await page.locator('#streamMetadataCheck').click();await page.locator('#streamMetadataStatus').filter({hasText:'still unconfirmed'}).waitFor();await page.evaluate(()=>{metadataQa.mode='normal';});await page.locator('#streamMetadataApply').click();await page.locator('#streamMetadataStatus').filter({hasText:'Updated connected channel'}).waitFor();assert.equal(await page.evaluate(()=>{const values=metadataQa.calls.filter(value=>value.action==='apply');return JSON.stringify(values[0])===JSON.stringify(values[1]);}),true);
    await page.evaluate(()=>metadataEditor.setContext({dirty:true}));assert.equal(await page.locator('#streamMetadataApply').isDisabled(),true);await page.evaluate(()=>metadataEditor.setContext({dirty:false,locked:true}));assert.equal(await page.locator('#streamMetadataApply').isDisabled(),true);await page.evaluate(()=>metadataEditor.setContext({locked:false,destination:{id:'synthetic-youtube',name:'Synthetic YouTube',platform:'youtube'}}));await page.waitForFunction(()=>document.querySelector('#streamMetadataBroadcast').options.length===2);assert.equal(await page.locator('#streamMetadataBroadcast').inputValue(),'');assert.equal(await page.locator('#streamMetadataApply').isDisabled(),true);await page.locator('#streamMetadataBroadcast').selectOption('synthetic-broadcast');await page.waitForFunction(()=>!document.querySelector('#streamMetadataApply').disabled);
    assert.equal(await page.locator('#streamMetadataBroadcast').inputValue(),'synthetic-broadcast');await page.locator('#streamMetadataApply').click();await page.locator('#streamMetadataStatus').filter({hasText:'Updated connected channel'}).waitFor();assert.equal(await page.evaluate(()=>metadataQa.calls.at(-1).broadcastId),'synthetic-broadcast');
    for(const theme of ['ignite','daylight'])for(const width of [390,860,1920,3840]){
      await page.setViewportSize({width,height:width===3840?2160:1080});await page.evaluate(value=>{document.documentElement.dataset.operatorSkin=value;},theme);
      const check=await page.locator('#streamMetadata').evaluate(section=>({horizontal:document.documentElement.scrollWidth>innerWidth+1,targets:[...section.querySelectorAll('button,input,select')].filter(node=>node.getClientRects().length).every(node=>node.getBoundingClientRect().height>=44),clipped:[...section.querySelectorAll('button')].filter(node=>node.getClientRects().length).some(node=>node.scrollWidth>node.clientWidth+1)}));assert.equal(check.horizontal,false,theme+' '+width+' overflow');assert.equal(check.targets,true,theme+' '+width+' target size');assert.equal(check.clipped,false,theme+' '+width+' clipped buttons');await page.locator('#streamInfo').screenshot({path:path.join(evidence,theme+'-'+width+'.png'),animations:'disabled'});results.layouts.push({theme,width,...check});
    }
    await page.locator('#streamMetadataQuery').focus();await page.keyboard.press('Tab');assert.equal(await page.locator('#streamMetadataSearch').evaluate(node=>document.activeElement===node),true);assert.deepEqual(errors,[]);Object.assign(results,{passed:true,exactRetry:true,readDoesNotConfirmWrite:true,explicitBroadcast:true,dirtyGuard:true,lockedGuard:true,lazyCategories:true,keyboard:true,errors});
  }catch(error){results.error=error.message;throw error;}finally{fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(results,null,2));await browser.close();}
  console.log(JSON.stringify(results));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
