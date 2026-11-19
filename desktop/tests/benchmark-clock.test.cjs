'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{waitUntil}=require('./benchmark-clock.cjs');
test('coarse Windows timers cannot accumulate delays while the benchmark is already late',async()=>{
  let clock=0,yields=0,maxLag=0;const quantum=15.625;
  for(let i=0;i<1000;i++){
    maxLag=Math.max(maxLag,clock-i*10);
    await waitUntil((i+1)*10,{now:()=>clock,delay:async ms=>{clock+=Math.max(quantum,Math.ceil(ms/quantum)*quantum);},yieldNow:async()=>{clock+=.05;yields++;}});
  }
  assert.ok(yields>0);assert.ok(maxLag<quantum+1);assert.ok(clock<10000+quantum+1);
});
