const {test}=require('node:test');
const assert=require('node:assert/strict');
const {normalize,KEY}=require('../../rareiq/web/static/studio_docks.js');
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
