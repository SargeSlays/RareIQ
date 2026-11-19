'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{cleanMeterHealth,cleanMeterStatus}=require('../audio-meters.cjs');
const good=()=>({available:true,live:{peak:.5,rms:.3,clipCount:0},vod:{peak:1,rms:.8,clipCount:2,clipped:true}});
test('meter boundary returns only finite scalar mix diagnostics and preserves independent levels',()=>{
  const v=good(),result=cleanMeterHealth(v);assert.equal(result.fresh,true);assert.equal(result.live.peak,.5);assert.equal(result.vod.clipped,true);v.live.peak=1;assert.equal(result.live.peak,.5);assert.deepEqual(cleanMeterStatus(result),result);
});
test('malformed, stale and private-bearing diagnostics clear both mixes instead of retaining old signal',()=>{
  for(const mutate of [v=>v.available=false,v=>v.live.peak=NaN,v=>v.live.peak=Infinity,v=>v.vod.rms=-1,v=>v.vod.rms=1.1,v=>v.live.peak='0.5',v=>v.live.clipCount=9601,v=>v.live.clipCount=true,v=>v.vod.clipped='yes',v=>v.pcm=new Uint8Array(4),v=>v.live.url='private',v=>delete v.vod]){
    const value=good();mutate(value);const clean=cleanMeterHealth(value);assert.equal(clean.fresh,false);assert.equal(clean.live.peak,0);assert.equal(clean.vod.clipCount,0);assert.doesNotMatch(JSON.stringify(clean),/private|pcm|url/);
  }
});
