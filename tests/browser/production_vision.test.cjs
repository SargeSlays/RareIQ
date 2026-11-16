const {test}=require('node:test');
const assert=require('node:assert/strict');
const {pose,observation}=require('../../rareiq/web/static/production_vision_model.js');
const {binding}=require('../../rareiq/web/static/production_vision.js');
test('head direction derives finite forward-axis yaw, not eye landmarks',()=>{
  const a=Math.PI/6,m=[Math.cos(a),0,-Math.sin(a),0,0,1,0,0,Math.sin(a),0,Math.cos(a),0,0,0,0,1];
  assert.ok(Math.abs(pose(m).yaw-30)<.001);
  assert.equal(pose(Array(16).fill(0)),null);
  assert.equal(pose([NaN]),null);
  const face=observation({faceLandmarks:[[]],facialTransformationMatrixes:[{data:m}]},'head');
  assert.equal(face.face_count,1);assert.equal(face.gesture,'neutral');
});
test('only supported hand labels and bounded counts leave model adapter',()=>{
  assert.equal(observation({landmarks:[[]],gestures:[[{categoryName:'Victory',score:.98}]]},'hands').gesture,'victory');
  assert.equal(observation({landmarks:[[]],gestures:[[{categoryName:'remote_command',score:1}]]},'hands').gesture,'neutral');
  assert.equal(observation({landmarks:[[],[],[]]},'hands').hand_count,2);
});
test('bindings use production dispatcher allowlist and explicit transition',()=>{
  assert.deepEqual(binding('camera:2','fade'),{action_id:'program.take',params:{preview_slot:2,transition:'fade',duration_ms:500}});
  assert.deepEqual(binding('scene:scene-id','cut'),{action_id:'scene.take',params:{scene_id:'scene-id'}});
  assert.equal(binding('https://arbitrary','fade'),null);
});
