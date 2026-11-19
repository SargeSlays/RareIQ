'use strict';
const {studioOrigin}=require('./policy.cjs');

// MJPEG and other persistent resources may keep loadURL pending after the UI is usable.
// Readiness belongs to the exact initial top-level document, not its resource load.
function loadInitialStudio(contents,target,{timeoutMs=45000}={}){
  try{
    const url=new URL(target);studioOrigin(url.origin);
    if(url.href!==target||url.pathname!=='/control'||url.username||url.password||url.hash
        ||!Number.isSafeInteger(timeoutMs)||timeoutMs<1||timeoutMs>120000
        ||!contents||typeof contents.loadURL!=='function'||typeof contents.on!=='function')throw Error();
  }catch(_){return Promise.reject(Object.assign(Error('The initial studio address is invalid.'),{code:'studio_startup_invalid'}));}
  return new Promise((resolve,reject)=>{
    let settled=false,timer;
    const handlers={
      'dom-ready':()=>{
        if(contents.isDestroyed())return finish('destroyed');
        if(contents.getURL()!==target||contents.mainFrame?.url!==target)return finish('untrusted');
        finish();
      },
      'did-fail-load':(_event,_code,_description,_url,main)=>{if(main!==false)finish('load_failed');},
      'did-start-navigation':(_event,url,_inPlace,main)=>{if(main!==false&&url!==target)finish('untrusted');},
      'destroyed':()=>finish('destroyed'),
      'render-process-gone':()=>finish('renderer_unavailable'),
    };
    function finish(reason){
      if(settled)return;settled=true;clearTimeout(timer);
      for(const [name,handler] of Object.entries(handlers))contents.removeListener(name,handler);
      if(reason){
        const messages={destroyed:'The studio window closed before it was ready.',untrusted:'The studio opened an unexpected address.',
          load_failed:'The studio page could not load. Reopen the desktop app and retry.',
          renderer_unavailable:'The studio window could not initialize. Reopen the desktop app and retry.',
          timeout:'The studio page did not become ready in time. Reopen the desktop app and retry.'};
        reject(Object.assign(Error(messages[reason]),{code:'studio_startup_'+reason}));
      }else resolve();
    }
    if(contents.isDestroyed())return finish('destroyed');
    for(const [name,handler] of Object.entries(handlers))contents.on(name,handler);
    timer=setTimeout(()=>finish('timeout'),timeoutMs);
    try{
      // Always consume late load rejections, including reload's ERR_ABORTED after DOM-ready.
      Promise.resolve(contents.loadURL(target)).catch(()=>finish('load_failed'));
    }catch(_){finish('load_failed');}
  });
}
module.exports={loadInitialStudio};
