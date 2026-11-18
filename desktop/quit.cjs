'use strict';
// Closing native windows may synchronously emit window-all-closed. Keep every
// exit path blocked until asynchronous backend cleanup has actually settled.
function createQuitCoordinator({active,confirm,release,exit}){
  let draining=false,finished=false;
  return {
    get draining(){return draining;},get finished(){return finished;},
    request(event){
      if(finished)return;event.preventDefault();if(draining)return;draining=true;
      (async()=>{
        let productionActive=true;try{productionActive=await active();}catch(_){}
        if(productionActive){let approved=false;try{approved=await confirm();}catch(_){}if(!approved){draining=false;return;}}
        try{if(await release()===false){draining=false;return;}}catch(_){/* Preserve the backend on an uncertain close. */}
        finished=true;draining=false;exit();
      })();
    },
  };
}
module.exports={createQuitCoordinator};
