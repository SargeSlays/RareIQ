const test=require('node:test');
const assert=require('node:assert/strict');
const room=require('../../rareiq/web/static/guest_room.js');
test('room roster excludes ended and expired sessions and uses authoritative self state',()=>{
  const self={id:'self',state:'waiting',name:'Own name'},people=room.roomPeople({participants:[{id:'self',state:'admitted'},{id:'other',state:'admitted',name:'<img src=x>'},{id:'left',state:'removed'},{id:'expired',state:'waiting',expired:true}]},self);
  assert.deepEqual(people,[self,{id:'other',state:'admitted',name:'<img src=x>'}]);
});
test('a waiting or disconnected session cannot watch admitted cameras',()=>{
  const other={state:'admitted',connected:true};
  for(const self of [null,{state:'waiting',connected:true},{state:'removed',connected:true},{state:'admitted',connected:false}])assert.equal(room.mayWatch(self,other),false);
  assert.equal(room.mayWatch({state:'admitted',connected:true},other),true);
  for(const person of [{state:'waiting',connected:true},{state:'removed',connected:true},{state:'admitted',connected:false}])assert.equal(room.mayWatch({state:'admitted',connected:true},person),false);
});

test('picture size defaults compact and changes only local view state while preserving borrowed tracks',()=>{
  for(const bind of [room.bindPictureSize,require('../../rareiq/web/static/greenroom_controls.js').bindPictureSize]){
    const camera={enabled:true,readyState:'live'},stream={getTracks:()=>[camera]},video={srcObject:stream},container={dataset:{},video},attributes={},handlers={};
    const button={textContent:'',setAttribute:(name,value)=>{attributes[name]=value;},addEventListener:(name,fn)=>{handlers[name]=fn;}};
    const sizes=bind(container,button);assert.equal(container.dataset.pictureSize,'compact');assert.equal(button.textContent,'Larger pictures');assert.equal(attributes['aria-pressed'],'false');
    handlers.click();assert.equal(container.dataset.pictureSize,'large');assert.equal(button.textContent,'Compact pictures');assert.equal(attributes['aria-pressed'],'true');assert.equal(container.video.srcObject,stream);assert.equal(camera.enabled,true);
    handlers.click();assert.equal(container.dataset.pictureSize,'compact');assert.equal(attributes['aria-pressed'],'false');handlers.click();sizes.reset();assert.equal(container.dataset.pictureSize,'compact');assert.equal(container.video.srcObject,stream);
  }
});
