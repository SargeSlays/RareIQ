const {test}=require('node:test');
const assert=require('node:assert/strict');
const {normalize,normalizeSets,KEY}=require('../../rareiq/web/static/studio_docks.js');
test('dock defaults keep production essentials visible without changing older workspace preferences',()=>{
  const state=normalize(null,['production-scenes','show-preflight','production-session','operator-health','obs-control']);
  assert.equal(state.tools['production-scenes'].position,'left');
  assert.equal(state.tools['show-preflight'].visible,true);
  assert.equal(state.tools['obs-control'].visible,false);
  assert.equal(KEY,'rareiq.studio.docks.v1');
});
test('saved layout survives reload with hidden tools and bounded floating positions',()=>{
  const saved={version:1,tools:{a:{visible:false,position:'float',height:460,x:190,y:70}}};
  assert.deepEqual(normalize(saved,['a']),saved);
  assert.deepEqual(normalize(normalize(saved,['a']),['a']),saved);
});
test('untrusted storage cannot inject tools, unsupported positions, or unbounded dimensions',()=>{
  const state=normalize({version:1,tools:{a:{position:'window',visible:'yes',height:999999,x:-80,y:Infinity},secret:{token:'never preserve'}}},['a']);
  assert.deepEqual(Object.keys(state.tools),['a']);
  assert.equal(state.tools.a.position,'right');assert.equal(state.tools.a.visible,false);
  assert.equal(state.tools.a.height,800);assert.equal(state.tools.a.x,0);assert.equal(state.tools.a.y,40);
  assert.equal(normalize({version:99,tools:{a:{visible:true}}},['a']).tools.a.visible,false);
});
test('tool sets use independent IDs even when project labels match',()=>{
  const raw={version:1,active:'second',profiles:[{id:'first',label:'Friday show',layout:{version:1,tools:{a:{visible:true}}},workspaces:['soundboard']},{id:'second',label:'Friday show',layout:{version:1,tools:{a:{visible:false}}},workspaces:['creator']}]};
  const sets=normalizeSets(raw,['a']);assert.equal(sets.profiles.length,2);assert.equal(sets.active,'second');assert.equal(sets.profiles[0].layout.tools.a.visible,true);assert.equal(sets.profiles[1].layout.tools.a.visible,false);
  assert.deepEqual(normalizeSets(sets,['a']),sets);
});
test('tool sets reject unsupported versions, unknown workspaces and arbitrary saved payload fields',()=>{
  assert.deepEqual(normalizeSets({version:99,workspaces:['soundboard']},['a']),{version:1,active:'',workspaces:[],profiles:[]});
  const sets=normalizeSets({version:1,active:'gone',workspaces:['fake','soundboard'],profiles:[null,{id:'ok',label:' Demo ',secret:'omit',workspaces:['fake','live']},{id:'ok',label:'Duplicate'}]},['a']);
  assert.equal(sets.active,'');assert.deepEqual(sets.workspaces,['soundboard']);assert.equal(sets.profiles.length,1);assert.equal(sets.profiles[0].label,'Demo');assert.deepEqual(sets.profiles[0].workspaces,['live']);assert.equal('secret' in sets.profiles[0],false);
});

test('old workspace selections migrate to audio docks without overriding an explicit dock choice',()=>{
  const ids=['production-scenes','workspace-soundboard','workspace-voice-mod'];
  const state=normalize({version:1,tools:{'workspace-voice-mod':{visible:false}}},ids,['soundboard','voice-mod']);
  assert.equal(state.tools['workspace-soundboard'].visible,true);
  assert.equal(state.tools['workspace-voice-mod'].visible,false);
  const sets=normalizeSets({version:1,active:'audio',workspaces:['soundboard','settings'],profiles:[{id:'audio',label:'Audio',layout:{version:1,tools:{}},workspaces:['soundboard','voice-mod','settings']}]},ids);
  assert.deepEqual(sets.workspaces,['settings']);
  assert.equal(sets.profiles[0].layout.tools['workspace-soundboard'].visible,true);
  assert.equal(sets.profiles[0].layout.tools['workspace-voice-mod'].visible,true);
  assert.deepEqual(sets.profiles[0].workspaces,['settings']);
  assert.deepEqual(normalizeSets(sets,ids),sets);
});
