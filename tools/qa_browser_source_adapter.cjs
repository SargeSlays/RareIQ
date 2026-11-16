/* Isolated, intercepted browser experiment. No external page or hardware access. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const destination=process.argv[2];if(!destination||!path.isAbsolute(destination))throw Error('Absolute evidence directory required');fs.mkdirSync(destination,{recursive:true});
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge'}),result={complete:false,externalNetwork:false,hardware:false,productionConnected:false,requests:0};
  try{
    const page=await browser.newPage({viewport:{width:1280,height:800}});let sourceRequests=0,referrers=[];
    await page.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());result.requests++;
      if(url.href==='https://studio.example.com/rehearsal')return route.fulfill({contentType:'text/html',body:'<!doctype html><title>Isolated browser adapter rehearsal</title><div id="preview" style="width:960px;height:540px"></div><script src="/adapter.js"></script>'});
      if(url.href==='https://studio.example.com/adapter.js')return route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.resolve(__dirname,'../rareiq/web/static/production_browser_source.js'),'utf8')});
      if(url.hostname==='overlay.example.com'){
        sourceRequests++;referrers.push(request.headers().referer||'');
        return route.fulfill({contentType:'text/html',headers:url.pathname==='/blocked'?{'X-Frame-Options':'DENY'}:{},body:`<!doctype html><body style="background:#16334d;color:white;font:32px sans-serif">Isolated browser fixture<script>
          let parentDenied=false;try{void parent.document.body;}catch(e){parentDenied=true;}
          const policy=document.permissionsPolicy||document.featurePolicy;
          parent.postMessage({fixture:true,parentDenied,origin:location.origin,permissions:Object.fromEntries(['camera','microphone','geolocation','autoplay','display-capture','fullscreen'].map(k=>[k,policy?policy.allowsFeature(k):null]))},'*');
        </script>`});
      }
      throw Error('Unexpected request blocked: '+url.origin);
    });
    await page.goto('https://studio.example.com/rehearsal');
    await page.evaluate(()=>{window.reports=[];addEventListener('message',e=>{if(e.data?.fixture)reports.push({...e.data,eventOrigin:e.origin});});window.adapter=ProducerBrowserSource.mount({container:document.querySelector('#preview'),url:'https://overlay.example.com/widget',studioOrigin:location.origin});});
    await page.waitForFunction(()=>adapter.snapshot().phase==='loaded_unverified'&&reports.length>0);
    const first=await page.evaluate(()=>({state:adapter.snapshot(),report:reports[0],attributes:{sandbox:adapter.frame.getAttribute('sandbox'),inert:adapter.frame.inert,tabIndex:adapter.frame.tabIndex}}));
    assert.equal(first.state.phase,'loaded_unverified');assert.equal(first.report.parentDenied,true);assert.equal(first.report.eventOrigin,'null');assert.equal(first.attributes.sandbox,'allow-scripts');assert.equal(first.attributes.inert,true);assert.equal(first.attributes.tabIndex,-1);for(const value of Object.values(first.report.permissions))assert.equal(value,false);assert.ok(referrers.every(v=>v===''));
    const reviewed=await page.evaluate(()=>{const token=adapter.snapshot().reviewToken;window.lastReviewToken=token;return {ok:adapter.review(token),state:adapter.snapshot(),replayed:adapter.review(token)};});assert.equal(reviewed.ok,true);assert.equal(reviewed.state.phase,'visual_reviewed');assert.equal(reviewed.replayed,false);
    await page.evaluate(()=>{window.oldToken=window.lastReviewToken;adapter.reload();if(adapter.snapshot().phase!=='loading')throw Error('Reload retained review');});await page.waitForFunction(()=>adapter.snapshot().phase==='loaded_unverified');assert.equal(await page.evaluate(()=>adapter.review(window.oldToken)),false);
    await page.evaluate(()=>{adapter.destroy();window.adapter=ProducerBrowserSource.mount({container:document.querySelector('#preview'),url:'https://overlay.example.com/blocked',studioOrigin:location.origin});});await page.waitForFunction(()=>adapter.snapshot().phase==='loaded_unverified');assert.equal(await page.evaluate(()=>adapter.snapshot().ready),undefined);
    const before=sourceRequests;await page.evaluate(()=>{adapter.destroy();for(const url of ['https://127.0.0.1','https://studio.example.com/control','javascript:alert(1)']){let rejected=false;try{ProducerBrowserSource.mount({container:document.querySelector('#preview'),url,studioOrigin:location.origin});}catch(_){rejected=true;}if(!rejected)throw Error('Unsafe URL accepted');}});assert.equal(sourceRequests,before);assert.equal(await page.locator('#preview iframe').count(),0);
    Object.assign(result,{complete:true,opaqueSandbox:true,permissionsDenied:true,noReferrer:true,loadNeverReady:true,manualReview:true,reloadInvalidatesReview:true,blockedEmbedNeverReady:true,invalidUrlsNeverNavigate:true,destroyRemovesFrame:true});
  }finally{fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify(result,null,2));await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
