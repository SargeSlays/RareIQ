// Exercises the served controller in Edge with inert APIs and no media activation.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const page=await browser.newPage();let interceptedWrites=0;
    await page.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!==origin)return route.abort();
      if(url.pathname.startsWith('/api/')){
        if(!['GET','HEAD'].includes(request.method()))interceptedWrites++;
        return route.fulfill({status:200,contentType:'application/json',body:'{"ok":true}'});
      }
      return route.continue();
    });
    await page.routeWebSocket('**',socket=>socket.close());
    await page.addInitScript(()=>{
      window.mediaStarts=0;
      navigator.mediaDevices.getUserMedia=async()=>{window.mediaStarts++;throw Error('Media blocked by QA');};
      HTMLMediaElement.prototype.play=function(){window.mediaStarts++;return Promise.resolve();};
    });
    await page.goto(origin+'/control?rundown-qa='+Date.now());
    await page.waitForFunction(()=>typeof goProductionRundown==='function'&&typeof waitProductionRundown==='function');
    await page.waitForTimeout(250);
    const result=await page.evaluate(async()=>{
      const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
      const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
      const notices=[],events=[];let renders=0,saves=0,sounds=0,spotify=0;
      notify=(...args)=>notices.push(args);logProductionEvent=(...args)=>events.push(args);
      renderProductionSwitcher=()=>renders++;renderProductionScreen=()=>{};
      renderProductionRundown=()=>{};saveProductionRundown=()=>saves++;
      stopAllSoundboardAudio=()=>sounds++;spotifyCommand=async()=>spotify++;
      document.getElementById('rundownRehearsal').checked=false;
      const configure=(follow=true)=>{
        productionScenes=[{id:'fixture',name:'Fixture',transition:'cut',soundboard_action:'keep',spotify_action:'keep'}];
        productionRundown=[{type:'scene',target:'fixture',label:'Fixture',auto_follow:follow},{type:'wait',label:'Next',delay_seconds:1}];
        productionRundownIndex=0;
      };
      configure();Object.assign(productionScenes[0],{soundboard_action:'stop',spotify_action:'play'});
      const delayed=deferred();api=()=>delayed.promise;
      const stopped=goProductionRundown();stopProductionRundown();delayed.resolve({ok:true,program_slot:1});await stopped;
      await new Promise(resolve=>setTimeout(resolve,75));
      const stop={index:productionRundownIndex,running:productionRundownRunning,timer:productionRundownTimer,renders,saves,sounds,spotify,notices:notices.map(item=>item[0])};
      configure(false);const old=deferred(),next=deferred();let requests=0;
      api=()=>++requests===1?old.promise:next.promise;
      const first=goProductionRundown();stopProductionRundown();const second=goProductionRundown();
      old.resolve({ok:true,program_slot:1});await first;
      const newerStillOwned=productionRundownRunning&&productionRundownIndex===0;
      await goProductionRundown();next.resolve({ok:true,program_slot:1});await second;
      const race={newerStillOwned,requests,index:productionRundownIndex,running:productionRundownRunning};
      configure();api=async()=>({ok:true,program_slot:1,obs_warning:'Fixture unavailable'});
      productionScenes[0].spotify_action='play';spotifyCommand=async()=>{throw Error('Fixture unavailable');};
      const partial=await goProductionRundown();
      const warning={partial:partial.partial,warnings:partial.warnings.length,index:productionRundownIndex,timer:productionRundownTimer};
      configure(false);api=async()=>({ok:true,program_slot:1});const music=deferred();
      productionScenes[0].spotify_action='play';spotifyCommand=()=>music.promise;
      const complete=goProductionRundown();await tick();const awaitingMusic=productionRundownRunning&&productionRundownIndex===0;
      music.resolve();await complete;
      return {stop,race,warning,complete:{awaitingMusic,index:productionRundownIndex},mediaStarts};
    });
    assert.deepEqual(result.stop,{index:0,running:false,timer:0,renders:0,saves:0,sounds:0,spotify:0,notices:['Rundown Stopped']});
    assert.deepEqual(result.race,{newerStillOwned:true,requests:2,index:1,running:false});
    assert.deepEqual(result.warning,{partial:true,warnings:2,index:0,timer:0});
    assert.deepEqual(result.complete,{awaitingMusic:true,index:1});assert.equal(result.mediaStarts,0);
    console.log(JSON.stringify({servedEdgeCases:4,passed:true,apiWritesForwarded:0,interceptedWrites,...result}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
