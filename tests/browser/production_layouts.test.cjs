const test=require('node:test'),assert=require('node:assert/strict');
const layouts=require('../../rareiq/web/static/production_layouts.js');
const uuid='12345678-1234-1234-1234-123456789abc',guest='guest:'+'a'.repeat(32),CAM='camera:1',CAM2=guest+':camera',AUDIO=guest+':audio',TEXT='text:'+uuid,SCREEN=guest+':screen';
test('Smart layout selects Solo, Interview, Panel or Presentation without counting text and microphones',()=>{
  assert.equal(layouts.presetPlan('smart',[TEXT,AUDIO]).available,false);
  const solo=layouts.presetPlan('smart',[TEXT,AUDIO,CAM]);assert.equal(solo.label,'Solo');assert.equal(solo.layout,'auto');
  const interview=layouts.presetPlan('smart',[CAM,TEXT,CAM2,AUDIO]);assert.equal(interview.label,'Interview');assert.equal(interview.layout,'grid');
  assert.equal(layouts.presetPlan('smart',[CAM,CAM2,'camera:2',AUDIO]).label,'Panel');
  for(const content of [SCREEN,'image:'+uuid,'video:'+uuid,'browser:'+uuid]){const original=[CAM,TEXT,content,AUDIO],plan=layouts.presetPlan('smart',original);assert.equal(plan.label,'Presentation');assert.equal(plan.layout,'spotlight');assert.deepEqual(plan.sources,[content,TEXT,CAM,AUDIO]);assert.deepEqual(original,[CAM,TEXT,content,AUDIO]);}
});
test('PiP requires exactly two pictures; presets preserve every selected source and never mutate input',()=>{
  for(const sources of [[],[TEXT,AUDIO],[CAM,TEXT],[CAM,CAM2,'camera:2',TEXT]])assert.equal(layouts.presetPlan('pip',sources).available,false);
  const sources=[CAM,TEXT,SCREEN,AUDIO],pip=layouts.presetPlan('pip',sources);assert.equal(pip.available,true);assert.equal(pip.layout,'pip');assert.deepEqual(pip.sources,[SCREEN,TEXT,CAM,AUDIO]);
  for(const preset of ['smart','grid','focus','pip']){const plan=layouts.presetPlan(preset,sources);assert.deepEqual([...plan.sources].sort(),[...sources].sort());assert.equal(plan.sources[1],TEXT);assert.equal(plan.sources[3],AUDIO);assert.notEqual(plan.sources,sources);}
  assert.equal(layouts.presetPlan('grid',[CAM]).available,false);assert.equal(layouts.presetPlan('focus',[CAM]).available,false);
});
test('lead selection reorders selected pictures only and rejects stale or nonvisual choices',()=>{
  const sources=[TEXT,CAM,AUDIO,CAM2];assert.deepEqual(layouts.leadFirst(sources,CAM2),[TEXT,CAM2,AUDIO,CAM]);
  for(const value of ['camera:4',AUDIO,TEXT])assert.throws(()=>layouts.leadFirst(sources,value),/lead_not_selected/);
  for(const invalid of [[CAM,CAM],['https://example.com'],[CAM,CAM2,SCREEN,TEXT,AUDIO,'camera:2','camera:3']])assert.throws(()=>layouts.presetPlan('smart',invalid),/invalid_preview_sources/);
});
test('recommendations are read-only and explicit application recomputes the latest Preview',()=>{
  let selected=[CAM,CAM2],reads=0;const applied=[];
  layouts.presetPlan('smart',selected);assert.equal(applied.length,0);selected=[CAM,SCREEN,TEXT];
  const result=layouts.applyPreset('smart',()=>{reads++;return selected;},(sources,layout)=>applied.push({sources,layout}));
  assert.equal(reads,1);assert.equal(result.label,'Presentation');assert.deepEqual(applied,[{sources:[SCREEN,CAM,TEXT],layout:'spotlight'}]);assert.deepEqual(selected,[CAM,SCREEN,TEXT]);
  selected=[TEXT,AUDIO];assert.equal(layouts.applyPreset('pip',()=>selected,()=>assert.fail('Unavailable presets must not apply')).available,false);
});
