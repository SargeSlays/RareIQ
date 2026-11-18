/* Packaged Settings + Windows encryption. Fresh QA profile and synthetic keys only. */
'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
async function exerciseDestinationEdit(app,{settings,origin,evidence}={}){
  const profile=await app.evaluate(({app})=>app.getPath('userData'));
  assert.ok(profile.startsWith(evidence+path.sep),'Fresh owned evidence profile required');
  const fields=name=>settings.locator(`[name="${name}"]`),save=settings.locator('#saveDestination');
  async function saved(){await settings.locator('#status').filter({hasText:'Destination saved securely.'}).waitFor();}
  async function publicState(){const state=await settings.evaluate(()=>producerSettings.status());const text=JSON.stringify(state);assert.ok(!text.includes('synthetic-qa-')&&!text.includes('provider.com'));return state;}
  async function privateMatches(id,key,server){
    return app.evaluate(async({app,safeStorage},{id,key,server})=>{
      const path=process.getBuiltinModule('node:path'),require=process.getBuiltinModule('node:module').createRequire(path.join(process.resourcesPath,'app.asar','package.json'));
      const {DestinationStore,PRESETS}=require(path.join(process.resourcesPath,'app.asar','destinations.cjs'));
      const store=new DestinationStore({directory:app.getPath('userData'),cipher:safeStorage});
      const value=await store.getPrivateDestination(id);
      return {keyMatches:value.streamKey===key,serverMatches:value.serverUrl===(server||PRESETS[0].serverUrl)};
    },{id,key,server});
  }
  async function fill(name,platform,key,server=''){for(const [field,value] of Object.entries({name,platform,streamKey:key,serverUrl:server})){if(field==='serverUrl'&&platform==='twitch')continue;if(field==='platform')await fields(field).selectOption(value);else await fields(field).fill(value);}}
  const before=await (await fetch(origin+'/api/production/switcher')).json();
  await fill('Synthetic Twitch','twitch','synthetic-qa-twitch');await save.click();await saved();
  const twitch=(await publicState()).destinations[0];assert.equal(twitch.configured,true);
  await fill('Unfinished Add draft','custom','synthetic-qa-unsaved','rtmps://draft.provider.com/live');
  await settings.locator(`[data-edit-destination-id="${twitch.id}"]`).click();
  assert.equal(await fields('streamKey').inputValue(),'');assert.equal(await fields('serverUrl').inputValue(),'');assert.equal(await fields('platform').isDisabled(),true);
  assert.equal(await settings.locator(`[data-destination-id="${twitch.id}"]`).isDisabled(),true);
  await fields('name').fill('Cancelled rename');await settings.locator('#cancelEdit').click();assert.equal(await fields('name').inputValue(),'Unfinished Add draft');assert.equal(await fields('streamKey').inputValue(),'synthetic-qa-unsaved');
  await settings.locator(`[data-edit-destination-id="${twitch.id}"]`).click();await fields('name').fill('Renamed Twitch');await save.click();await saved();
  assert.equal((await publicState()).destinations.length,1);assert.deepEqual(await privateMatches(twitch.id,'synthetic-qa-twitch'),{keyMatches:true,serverMatches:true});
  assert.equal(await fields('name').inputValue(),'Unfinished Add draft');
  await fill('Synthetic YouTube','youtube','synthetic-qa-youtube','rtmps://first.provider.com/live');await save.click();await saved();
  const youtube=(await publicState()).destinations.find(item=>item.platform==='youtube');
  await settings.locator(`[data-edit-destination-id="${youtube.id}"]`).click();await fields('serverUrl').fill('rtmps://replacement.provider.com/live');await save.click();
  await settings.locator('#status').filter({hasText:'replacement stream key'}).waitFor();assert.deepEqual(await privateMatches(youtube.id,'synthetic-qa-youtube','rtmps://first.provider.com/live'),{keyMatches:true,serverMatches:true});
  await fields('streamKey').fill('synthetic-qa-replacement');await save.click();await saved();assert.deepEqual(await privateMatches(youtube.id,'synthetic-qa-replacement','rtmps://replacement.provider.com/live'),{keyMatches:true,serverMatches:true});
  await settings.locator(`[data-edit-destination-id="${youtube.id}"]`).click();
  const layouts=[];
  for(const [width,height] of [[800,900],[1920,1080],[3840,2160]])for(const skin of ['ignite','daylight']){
    await settings.setViewportSize({width,height});if(await settings.evaluate(()=>document.documentElement.dataset.operatorSkin)!==skin)await settings.locator('#themeToggle').click();
    await settings.locator('#destinationForm').scrollIntoViewIfNeeded();assert.equal(await settings.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await settings.locator('#destinationFormHint').evaluate(element=>Math.round(element.getBoundingClientRect().width)===Math.round(element.parentElement.getBoundingClientRect().width)),true);
    await settings.screenshot({path:path.join(evidence,`destination-edit-${width}-${skin}.png`)});layouts.push({width,height,skin});
  }
  await settings.locator('#cancelEdit').click();
  const after=await (await fetch(origin+'/api/production/switcher')).json(),status=await (await fetch(origin+'/api/desktop/status')).json();
  assert.equal(after.generation,before.generation);assert.deepEqual(after.program_sources,before.program_sources);assert.equal(status.native_encoding.active,false);
  assert.equal((await publicState()).destinations.length,2);
  return {complete:true,actualPackagedSettings:true,actualWindowsEncryption:true,syntheticOnly:true,savedSecretsNeverDisplayed:true,renamePreservesCredentials:true,serverReplacementRequiresKey:true,cancelRestoresAddDraft:true,noProgramChange:true,noTransmission:true,layouts};
}
module.exports={exerciseDestinationEdit};
