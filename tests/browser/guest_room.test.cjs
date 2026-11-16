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
