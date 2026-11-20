const test=require('node:test'),assert=require('node:assert/strict');
const {defaults,normalizeLayers,createModel,moveLayer,groupBounds,transformGroup}=require('../../rareiq/web/static/production_layer_editor.js');
const camera='camera:1',image='image:12345678-1234-1234-1234-123456789abc';
const state=(overrides={})=>({generation:4,preview_revision:7,preview_sources:[camera,image],preview_layout:'grid',...overrides});

test('layer geometry is bounded, canonical, source-keyed and independently copied',()=>{
  const value=normalizeLayers([camera,image],{[camera]:{...defaults(),crop:{top:.1,right:.2,bottom:.3,left:.4}}});
  assert.equal(value[image].z,1);assert.equal(value[camera].crop.left,.4);
  for(const patch of [{x:-.1},{height:0},{width:Infinity},{opacity:NaN},{z:1.5},{locked:'false'},{crop:{top:.6,right:0,bottom:.4,left:0}}])assert.throws(()=>normalizeLayers([camera],{[camera]:{...defaults(),...patch}}),/invalid_layer_geometry/);
  assert.throws(()=>normalizeLayers([camera,camera]),/invalid_layer_sources/);
  assert.deepEqual(Object.keys(normalizeLayers([camera],{...value,orphan:defaults()})),[camera]);
  value[camera].crop.left=0;assert.equal(defaults().crop.left,0);
});

test('drag, numeric edits and selection remain local until explicit CAS-bound Apply',()=>{
  const source=state(),model=createModel();model.observe(source);model.select(image);model.edit(image,{x:.2,y:.3,width:.4,height:.5});
  assert.equal(source.preview_layout,'grid');assert.equal(source.program_layers,undefined);
  const request=model.prepare();assert.equal(request.layout,'custom');assert.equal(request.expected_generation,4);assert.equal(request.expected_preview_revision,7);
  assert.equal(request.layers[image].x,.2);assert.deepEqual(request.preview_sources,[camera,image]);
  assert.deepEqual(model.prepare(),request);request.layers[image].x=.9;assert.equal(model.prepare().layers[image].x,.2);
});

test('polling preserves dirty drafts and stale snapshots cannot rebase them',()=>{
  const model=createModel();model.observe(state());model.edit(camera,{x:.2});
  model.observe(state({preview_revision:6}));assert.equal(model.state().conflict,false);
  model.observe(state({preview_revision:8}));assert.equal(model.state().layers[camera].x,.2);assert.equal(model.state().base.revision,7);assert.equal(model.state().conflict,true);
  assert.throws(()=>model.prepare(),/preview_revision_conflict/);
  model.reload(state({preview_revision:8}));assert.equal(model.state().dirty,false);assert.equal(model.state().base.revision,8);
});

test('lost Apply can reconcile only an authoritative matching Preview; Program changes remain conflicts',()=>{
  const model=createModel();model.observe(state());model.edit(camera,{width:.5});const request=model.prepare();
  model.observe(state({preview_revision:8,preview_layout:'custom',preview_layers:request.layers}));assert.equal(model.state().dirty,false);assert.equal(model.state().pending,null);
  model.edit(camera,{height:.5});model.prepare();model.observe(state({generation:5,preview_revision:9,preview_layout:'custom',preview_layers:model.state().layers}));
  assert.equal(model.state().conflict,true);assert.equal(model.state().dirty,true);
});

test('lock guards all edits except unlocking; hide does not mutate audio or source membership',()=>{
  const model=createModel();model.observe(state());model.edit(camera,{locked:true});
  for(const patch of [{x:.2},{hidden:true},{z:2}])assert.throws(()=>model.edit(camera,patch),/layer_locked/);
  assert.throws(()=>model.reset(camera),/layer_locked/);model.edit(camera,{locked:false});model.edit(camera,{hidden:true});
  assert.deepEqual(model.prepare().preview_sources,[camera,image]);assert.equal(Object.hasOwn(model.prepare(),'audioRouting'),false);
  model.reset(camera);assert.equal(model.state().layers[camera].hidden,false);
});

test('pointer and keyboard geometry clamps remain finite and source objects stay unchanged',()=>{
  const layer={...defaults(),x:.2,y:.4,width:.8,height:.5};assert.deepEqual(moveLayer(layer,5,-5),{x:1,y:0});assert.deepEqual(moveLayer(layer,-5,5,true),{width:.01,height:1});assert.equal(layer.x,.2);
});

test('confirmed Preview preserves its composition ID for explicit scene-form handoff',()=>{
  const model=createModel(),id='c'.repeat(64),layers=normalizeLayers([camera,image]);
  model.observe(state({preview_layout:'custom',preview_layers:layers,preview_composition_id:id}));
  assert.equal(model.state().base.compositionId,id);assert.equal(model.state().dirty,false);
  model.edit(camera,{x:.1});assert.equal(model.state().dirty,true);assert.equal(model.state().base.compositionId,id);
});

test('fractional pointer drafts serialize to backend six-decimal precision and accept the saved result',()=>{
  const model=createModel();model.observe(state());model.edit(camera,{x:.150073124,width:.412345678,crop:{top:0,right:.123456789,bottom:0,left:0}});
  const request=model.prepare();assert.equal(request.layers[camera].x,.150073);assert.equal(request.layers[camera].width,.412346);assert.equal(request.layers[camera].crop.right,.123457);
  assert.doesNotThrow(()=>model.accepted(state({preview_revision:8,preview_layout:'custom',preview_layers:request.layers})));
  assert.equal(model.state().dirty,false);
  assert.throws(()=>normalizeLayers([camera],{[camera]:{...defaults(),crop:{top:.4999996,right:0,bottom:.4999996,left:0}}}),/invalid_layer_geometry/);
});

test('old layer maps gain optional defaults; rotation and group match backend validation',()=>{
  const old=defaults();delete old.rotation;delete old.group;
  assert.equal(normalizeLayers([camera],{[camera]:old})[camera].rotation,0);
  assert.equal(normalizeLayers([camera],{[camera]:old})[camera].group,'');
  for(const patch of [{rotation:null},{rotation:181},{rotation:-181},{rotation:Infinity},{group:null},{group:'a'.repeat(41)},{group:'\u0001bad'},{group:'bad\u0085'},{group:'  '}])assert.throws(()=>normalizeLayers([camera],{[camera]:{...defaults(),...patch}}),/invalid_layer_geometry/);
  const layer=normalizeLayers([camera],{[camera]:{...defaults(),rotation:17.12345678,group:'🎥'.repeat(40)}})[camera];assert.equal(layer.rotation,17.123457);assert.equal([...layer.group].length,40);
});

function grouped(){return normalizeLayers([camera,image],{[camera]:{...defaults(),x:.1,y:.2,width:.2,height:.2,group:'Host <&> title',rotation:30,opacity:.6,crop:{top:.1,right:0,bottom:0,left:0}},[image]:{...defaults(1),x:.4,y:.3,width:.2,height:.3,group:'Host <&> title',hidden:true}});}

test('flat group move and resize preserve proportions and unrelated layer properties',()=>{
  const layers=grouped(),name=layers[camera].group,bounds=groupBounds(layers,name);assert.equal(bounds.width,.5000000000000001);
  const moved=transformGroup([camera,image],layers,name,{x:.2,y:.1});assert.equal(moved[camera].x,.2);assert.equal(moved[image].x,.5);assert.equal(moved[camera].y,.1);assert.equal(moved[image].y,.2);
  const sized=transformGroup([camera,image],moved,name,{width:.4,height:.3});assert.equal(sized[camera].width,.16);assert.equal(sized[image].height,.225);assert.equal(sized[image].x,.44);
  assert.equal(sized[camera].rotation,30);assert.equal(sized[camera].opacity,.6);assert.equal(sized[camera].crop.top,.1);assert.equal(sized[image].hidden,true);assert.equal(sized[image].z,1);assert.deepEqual(layers,grouped());
});

test('all group changes reject atomically for locked members or invalid member bounds',()=>{
  const layers=grouped(),name=layers[camera].group,sources=[camera,image];
  for(const patch of [{x:.6},{height:.01},{width:.01},{x:NaN},{rotation:10}]){const before=structuredClone(layers);assert.throws(()=>transformGroup(sources,layers,name,patch),/layer_group_bounds|invalid_layer_geometry/);assert.deepEqual(layers,before);}
  layers[image].locked=true;assert.throws(()=>transformGroup(sources,layers,name,{x:.2}),/layer_group_locked/);
});

test('group creation, selection and ungroup remain local, literal and CAS-bound',()=>{
  const model=createModel();model.observe(state());model.edit(camera,{x:.1,y:.1,width:.2,height:.2,rotation:-45});model.edit(image,{x:.4,y:.1,width:.2,height:.2});
  model.group([camera,image],'<Host & title>');assert.equal(model.state().selectedGroup,'<Host & title>');model.editGroup({x:.2,width:.4});
  const request=model.prepare();assert.equal(request.layers[camera].group,'<Host & title>');assert.equal(request.layers[camera].rotation,-45);assert.equal(request.expected_preview_revision,7);assert.equal(Object.hasOwn(request,'audioRouting'),false);
  model.accepted(state({preview_layout:'custom',preview_layers:request.layers,preview_revision:8}));assert.equal(model.state().dirty,false);
  const before=model.state().layers;model.ungroup();assert.equal(model.state().selectedGroup,'');assert.equal(model.state().layers[camera].group,'');assert.equal(model.state().layers[image].x,before[image].x);assert.equal(model.state().layers[camera].rotation,-45);
});

test('a locked member blocks grouping, ungrouping and all transforms without dirty partial state',()=>{
  const model=createModel(),layers=grouped(),name=layers[camera].group;layers[image].locked=true;model.observe(state({preview_layout:'custom',preview_layers:layers}));model.selectGroup(name);const before=model.state();
  for(const action of [()=>model.editGroup({x:.2}),()=>model.ungroup(),()=>model.group([camera,image],'New name')]){assert.throws(action,/layer_group_locked/);assert.deepEqual(model.state(),before);}
  assert.throws(()=>model.group([camera],'Solo'),/invalid_layer_group/);
});

test('pointer group transforms always use their captured origin and retain six-decimal Apply precision',()=>{
  const model=createModel(),layers=grouped(),name=layers[camera].group;model.observe(state({preview_layout:'custom',preview_layers:layers}));model.selectGroup(name);
  model.editGroup({x:.150073124},layers);model.editGroup({x:.160073124},layers);const request=model.prepare();assert.equal(request.layers[camera].x,.160073);assert.equal(request.layers[image].x,.460073);
  model.accepted(state({preview_layout:'custom',preview_layers:request.layers,preview_revision:8}));assert.equal(model.state().dirty,false);
});
