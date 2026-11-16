const test=require('node:test'),assert=require('node:assert/strict');
const media=require('../../rareiq/web/static/production_media_library.js'),controls=require('../../rareiq/web/static/greenroom_controls.js');
const VIDEO='video:12345678-1234-1234-1234-123456789abc',TEXT='text:12345678-1234-1234-1234-123456789abc';
test('media inputs bound video formats, file size, literal text and fixed positioning',()=>{
  assert.equal(media.sourceId(VIDEO),VIDEO);assert.equal(media.sourceId(TEXT),TEXT);assert.equal(media.sourceId('video:../private'),null);
  assert.equal(media.fileType({name:'clip.MP4'}),'video/mp4');assert.equal(media.fileType({name:'clip.mp4',type:'text/html'}),null);
  assert.equal(media.uploadProblem({name:'clip.webm',size:64*1024*1024}),null);assert.match(media.uploadProblem({name:'clip.webm',size:64*1024*1024+1}),/64 MB/);assert.match(media.uploadProblem({name:'clip.webm',size:0}),/empty/);
  assert.equal(media.textProblem({name:'Title',text:'<b>literal text</b>',position:'center'}),null);assert.match(media.textProblem({name:'Title',text:'x'.repeat(1001),position:'top'}),/1,000/);assert.match(media.textProblem({name:'Title',text:'   ',position:'top'}),/Enter/);assert.match(media.textProblem({name:'Title',text:'ok',position:'script'}),/position/);
  for(const separator of ['\n','\r\n','\r']){assert.equal(media.textProblem({name:'Title',text:Array(8).fill('Line').join(separator),position:'top'}),null);assert.match(media.textProblem({name:'Title',text:Array(9).fill('Line').join(separator),position:'top'}),/8 lines/);}
});
test('video and text enter Preview through catalog validation and one-output readiness',()=>{
  global.ProducerMediaLibrary=media;
  try{const switcher={program_sources:[],preview_sources:[VIDEO,TEXT],production_sources:[{id:VIDEO},{id:TEXT}]},room={participants:[],output:{connected:2,ready_groups:[[VIDEO],[TEXT]]}};
    assert.equal(controls.sourceAvailable(VIDEO,switcher,room),true);assert.equal(controls.takeReadiness(switcher,room).ready,false);room.output.ready_groups=[[VIDEO,TEXT]];assert.equal(controls.takeReadiness(switcher,room).ready,true);assert.deepEqual(controls.togglePreview(TEXT,switcher,room),[VIDEO]);assert.deepEqual(switcher.program_sources,[]);switcher.production_sources=[];assert.equal(controls.sourceAvailable(TEXT,switcher,room),false);
  }finally{delete global.ProducerMediaLibrary;}
});
