const test=require('node:test'),assert=require('node:assert/strict');
const images=require('../../rareiq/web/static/production_image_library.js');
const controls=require('../../rareiq/web/static/greenroom_controls.js');
const SOURCE='image:12345678-1234-1234-1234-123456789abc';

test('image import accepts bounded local formats and rejects arbitrary paths and URLs',()=>{
  assert.equal(images.imageUrl(SOURCE),'/api/creator/assets/12345678-1234-1234-1234-123456789abc');
  for(const source of ['image:../../secret','https://example.test/x.png','image:<svg>'])assert.equal(images.imageUrl(source),null);
  assert.equal(images.fileType({name:'title.JPG',type:''}),'image/jpeg');
  assert.equal(images.fileType({name:'title.png',type:'text/html'}),null);
  assert.equal(images.uploadProblem({name:'title.png',type:'image/png',size:1024}),null);
  assert.match(images.uploadProblem({name:'title.png',size:0}),/empty/);
  assert.match(images.uploadProblem({name:'title.webp',size:8*1024*1024+1}),/8 MB/);
  assert.match(images.uploadProblem({name:'vector.svg',type:'image/svg+xml',size:10}),/PNG/);
});

test('image chooser preserves camera/guest composition and waits for one output to receive every source',()=>{
  global.ProducerImageLibrary=images;
  try{
    const guest='guest:'+'a'.repeat(32)+':camera';
    const room={participants:[{state:'admitted',connected:true,sources:{camera:guest},media:{camera:true}}],output:{connected:2,ready_groups:[[SOURCE],[guest]]}};
    const switcher={program_sources:[],preview_sources:[SOURCE,guest],image_sources:[{id:SOURCE,name:'Title'}]};
    assert.equal(controls.sourceAvailable(SOURCE,switcher,room),true);
    assert.equal(controls.takeReadiness(switcher,room).ready,false);
    room.output.ready_groups=[[SOURCE,guest]];assert.equal(controls.takeReadiness(switcher,room).ready,true);
    assert.deepEqual(controls.togglePreview(SOURCE,switcher,room),[guest]);
    switcher.image_sources=[];assert.equal(controls.takeReadiness(switcher,room).ready,false);
  }finally{delete global.ProducerImageLibrary;}
});
