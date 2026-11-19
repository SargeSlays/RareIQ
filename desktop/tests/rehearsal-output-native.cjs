'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{_electron}=require('playwright');
const evidence=process.argv[2],executablePath=process.argv[3];
if(!evidence||!path.isAbsolute(evidence)||fs.existsSync(evidence)||!executablePath)throw Error('Fresh isolated evidence and Electron executable required');fs.mkdirSync(evidence,{recursive:true});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function main(){let app;const results={passed:false,originalCoordinator:true,originalCapture:true,originalEncoder:true,originalBackendRoom:true,syntheticMedia:true,hardware:false,publicBroadcast:false,recording:false,listeningTest:false};
 try{
  app=await _electron.launch({executablePath,args:[path.join(__dirname,'rehearsal-native-app.cjs')],env:{...process.env,PRODUCER_REHEARSAL_NATIVE_EVIDENCE:evidence}});
  async function until(predicate,label){const end=Date.now()+20000;while(Date.now()<end){const failure=await app.evaluate(()=>globalThis.rehearsalFixtureError);if(failure)throw Error(failure);if(await predicate())return;await pause(80);}throw Error('Timed out: '+label);}
  await until(()=>app.evaluate(()=>globalThis.rehearsalFixture?.ready),'prepared');const page=app.windows()[0];
  results.prepared=await app.evaluate(()=>rehearsalFixture.status());assert.equal(results.prepared.room.mode,'production');assert.equal(results.prepared.monitor.bus,'off');
  await app.evaluate(()=>rehearsalFixture.enter());await app.evaluate(()=>rehearsalFixture.start());
  await until(()=>app.evaluate(()=>rehearsalFixture.status().local.frames>=30&&rehearsalFixture.status().local.vodAudioSamples>24000),'real local encoding');
  const badge=await page.locator('[data-rehearsal-badge]').innerText();assert.equal(badge,'REHEARSAL — not broadcasting');assert.equal(await page.locator('[data-rehearsal-badge]').isVisible(),true);assert.equal(await page.evaluate(()=>document.documentElement.dataset.nativeCapture),'active');
  results.running=await app.evaluate(()=>rehearsalFixture.status());assert.equal(results.running.local.running,true);assert.ok(results.running.local.bytesMuxed>0);assert.equal(results.running.room.publishing_allowed,false);
  await page.screenshot({path:path.join(evidence,'local-encoding-watermark.png')});
  const before=await app.evaluate(()=>rehearsalFixture.broadcast.status().audioMix);
  await app.evaluate(()=>rehearsalFixture.route({'voice:default':{live:true,vod:true,liveGainDb:-6,vodGainDb:-12}}));
  await until(()=>app.evaluate(()=>rehearsalFixture.status().local.frames>60),'continued encoding');
  const after=await app.evaluate(()=>rehearsalFixture.broadcast.status().audioMix);assert.equal(before.outputId,after.outputId);assert.equal(after.revision,before.revision+1);assert.equal(after.routing['voice:default'].vodGainDb,-12);
  const blocked=await app.evaluate(async()=>{try{await rehearsalFixture.broadcast.start({destinationId:'must-never-resolve',profileId:'synthetic-saved'});return false;}catch(error){return error.message;}});assert.equal(blocked,'rehearsal_active');
  await app.evaluate(()=>rehearsalFixture.stop());results.stopped=await app.evaluate(()=>rehearsalFixture.status());assert.equal(results.stopped.local.running,false);assert.equal(results.stopped.local.ownershipPending,false);assert.equal(results.stopped.monitor.bus,'off');
  await app.evaluate(()=>rehearsalFixture.mark());assert.equal((await app.evaluate(()=>rehearsalFixture.status())).room.checks.find(c=>c.id==='video').status,'passed');
  await app.evaluate(()=>rehearsalFixture.exit());results.exited=await app.evaluate(()=>rehearsalFixture.status());assert.equal(results.exited.room.mode,'production');assert.equal(results.exited.local.running,false);
  results.proof=await app.evaluate(()=>rehearsalFixture.proof());assert.equal(results.proof.external,0);assert.equal(results.proof.privateLookups,0);assert.equal(results.proof.outputMuted,true);
  results.liveFadersWhileEncoding=true;results.blockedBeforeDestinationLookup=true;results.passed=true;
 }catch(error){results.error=error.message;throw error;}finally{fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(results,null,2),{flag:'wx'});if(app){try{await app.evaluate(()=>rehearsalFixture?.close());}catch(_){}await app.close();}}
 console.log(JSON.stringify({passed:results.passed,frames:results.running?.local.frames,bytesMuxed:results.running?.local.bytesMuxed,evidence}));}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
