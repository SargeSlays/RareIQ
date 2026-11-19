'use strict';
const {setTimeout:sleep,setImmediate:yieldTurn}=require('node:timers/promises');
// A zero-duration timer can still wait a full Windows timer quantum. Yield to
// pending I/O when behind the absolute deadline instead of adding another wait.
async function waitUntil(deadline,{now=()=>performance.now(),delay=sleep,yieldNow=yieldTurn}={}){
  const remaining=deadline-now();
  if(remaining>=1)await delay(remaining);else await yieldNow();
}
module.exports={waitUntil};
