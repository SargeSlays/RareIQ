/* Synthetic DOM and pointer proof. No native IPC, accounts, devices or broadcast. */
'use strict';
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const evidence=process.argv[2],root=path.resolve(__dirname,'..');
if(!evidence||!path.isAbsolute(evidence)||fs.existsSync(evidence))throw Error('Fresh absolute evidence folder required.');
fs.mkdirSync(evidence,{recursive:true});
const files=new Set(['settings.html','settings.css','settings.js','settings-accounts.js','assets/producer-please.tokens.css','assets/icon-192.png']);
const server=http.createServer((request,response)=>{const name=new URL(request.url,'http://localhost').pathname.slice(1)||'settings.html';if(!files.has(name)){response.writeHead(404);response.end();return;}const file=name.startsWith('assets/')?path.resolve(root,'../rareiq/web/static/brand/producer-please-v2',name.slice(7)):path.join(root,name);response.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.png')?'image/png':'text/html');response.end(fs.readFileSync(file));});
async function main(){let browser;const results={passed:false,synthetic:true,realAccount:false,broadcast:false,checks:[]};
  try{await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
    browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext({reducedMotion:'reduce'});const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      const account={platform:'twitch',state:'authorized',reason:'account_authorized',authorized:true,streaming_authorized:false,app_configured:true,public_label:'fixture_channel',account_ref:'a'.repeat(64),expires_at:Date.now()/1000+3600};
      window.__accountQa={account,calls:[],links:0,failLink:false,opened:[],confirmed:0,broadcast:{phase:'idle',active:false,prepared:false,ready:false,available:true},destinations:[]};
      window.confirm=()=>{__accountQa.confirmed++;return true;};
      window.producerSettings={status:async()=>({secureStorageAvailable:true,broadcast:__accountQa.broadcast,destinations:__accountQa.destinations}),broadcastStatus:async()=>__accountQa.broadcast,openPlatform:async value=>{__accountQa.opened.push(value);},twitchAccount:async value=>{
        __accountQa.calls.push({...value});
        if(value.action==='begin')__accountQa.account={...account,state:'pending',reason:'authorization_pending',user_code:'DEMO-1234',flow_id:'b'.repeat(32),expires_at:Date.now()/1000+600};
        if(value.action==='cancel')__accountQa.account={...account,reason:'authorization_cancelled'};
        if(value.action==='link'){if(__accountQa.failLink){__accountQa.failLink=false;throw Error('Private mock failure');}__accountQa.links++;__accountQa.destinations=[{id:'11111111-1111-1111-1111-111111111111',name:'Twitch · fixture_channel',platform:'twitch',configured:true,linkedAccount:true}];}
        if(value.action==='disconnect')__accountQa.account={platform:'twitch',state:'not_authorized',reason:'authorization_required',authorized:false,streaming_authorized:false,app_configured:true};
        return {ok:true,account:{...__accountQa.account}};
      },save:async()=>{throw Error('Manual destination writes forbidden');},remove:async()=>{throw Error('Destination removal forbidden');},prepareOutput:async()=>{throw Error('Output capture forbidden');},startBroadcast:async()=>{throw Error('Broadcast forbidden');},stopBroadcast:async()=>{throw Error('Broadcast forbidden');},listOutputProfiles:async()=>{throw Error('No profiles in account fixture');}};
    });
    await page.goto(origin+'/settings.html');await page.locator('#twitchBadge').filter({hasText:'Chat connected'}).waitFor();
    await page.locator('#destinationForm input[name=name]').fill('Untouched manual draft');await page.locator('#destinationForm input[name=streamKey]').fill('synthetic-draft-key');
    await page.locator('#twitchBegin').click();await page.locator('#twitchCode').filter({hasText:'DEMO-1234'}).waitFor();await page.locator('#twitchOpen').click();assert.deepEqual(await page.evaluate(()=>__accountQa.opened),['https://www.twitch.tv/activate']);
    for(const theme of ['ignite','daylight'])for(const width of [390,860,1920,3840]){
      await page.setViewportSize({width,height:width===3840?2160:1080});await page.evaluate(theme=>document.documentElement.dataset.operatorSkin=theme,theme);await page.locator('#twitchAccount').scrollIntoViewIfNeeded();
      const check=await page.locator('#twitchAccount').evaluate(root=>{const buttons=[...root.querySelectorAll('button')].filter(item=>!item.hidden&&item.getBoundingClientRect().height>0);return {horizontal:document.documentElement.scrollWidth>innerWidth,targets:buttons.every(item=>item.getBoundingClientRect().height>=44),clipped:buttons.some(item=>item.scrollWidth>item.clientWidth+1)};});assert.equal(check.horizontal,false);assert.equal(check.targets,true);assert.equal(check.clipped,false);
      await page.locator('#twitchAccount').screenshot({path:path.join(evidence,theme+'-'+width+'.png'),animations:'disabled'});results.checks.push({theme,width,...check});
    }
    await page.setViewportSize({width:860,height:1080});await page.locator('#twitchCancel').click();await page.locator('#twitchBadge').filter({hasText:'Chat connected'}).waitFor();assert.equal(await page.locator('#destinationForm input[name=name]').inputValue(),'Untouched manual draft');
    await page.evaluate(()=>{__accountQa.account={...__accountQa.account,state:'authorized',reason:'account_authorized',streaming_authorized:true};});await page.locator('#twitchCheck').click();await page.locator('#twitchLink').waitFor({state:'visible'});
    await page.evaluate(()=>{__accountQa.failLink=true;});await page.locator('#twitchLink').click();await page.locator('#twitchStatus').filter({hasText:'could not be confirmed'}).waitFor();await page.locator('#twitchCheck').click();await page.locator('#twitchLink').click();await page.locator('#twitchStatus').filter({hasText:'destination saved'}).waitFor();
    const links=await page.evaluate(()=>__accountQa.calls.filter(item=>item.action==='link'));assert.equal(links.length,2);assert.equal(links[0].requestId,links[1].requestId);
    assert.equal(await page.locator('[data-edit-destination-id]').isDisabled(),true);await page.getByRole('button',{name:'Manage Twitch · fixture_channel account'}).click();assert.equal(await page.locator('#twitchCheck').evaluate(node=>document.activeElement===node),true);
    await page.evaluate(()=>{__accountQa.broadcast={phase:'sending',active:true,prepared:true,ready:false,available:true};});await page.locator('#twitchLocked').waitFor({state:'visible'});assert.equal(await page.locator('#twitchDisconnect').isDisabled(),true);assert.equal(await page.locator('#twitchLink').isDisabled(),true);
    await page.evaluate(()=>{__accountQa.broadcast={phase:'idle',active:false,prepared:false,ready:false,available:true};});await page.locator('#twitchDisconnect').waitFor({state:'visible'});await page.waitForFunction(()=>!document.querySelector('#twitchDisconnect').disabled);await page.locator('#twitchDisconnect').click();await page.locator('#twitchBadge').filter({hasText:'Not connected'}).waitFor();assert.equal(await page.evaluate(()=>__accountQa.confirmed),1);
    assert.equal(await page.locator('#destinationForm input[name=streamKey]').inputValue(),'synthetic-draft-key');assert.deepEqual(errors,[]);Object.assign(results,{passed:true,exactLinkRetry:true,manualDraftPreserved:true,sendingLocked:true,linkedEditBlocked:true,disconnectConfirmed:true,errors});
    fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
  }catch(error){results.error=error.message;fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(results,null,2));throw error;}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
