/* Public mode indicator only. No guest identity, program content or private room data. */
(() => {
  'use strict';
  function create({document:doc=document,fetch:request=fetch,setTimer=setTimeout,clearTimer=clearTimeout}={}){
    let closed=false,timer=null,pending=false,serial=0,failures=0,seenActive=false;
    const output=doc.querySelector('main[aria-label="Clean Studio Program output"]'),badge=doc.createElement('div');
    badge.className=output?'rehearsal-mode-badge rehearsal-output-watermark':'rehearsal-mode-badge';
    badge.setAttribute('data-rehearsal-badge','');badge.setAttribute('role','status');badge.setAttribute('aria-live','polite');badge.hidden=true;
    if(output)output.append(badge);else doc.body.prepend(badge);
    function paint(value){
      if(!value||typeof value.active!=='boolean'||typeof value.generation!=='string'||!/^[a-f0-9]{32}$/.test(value.generation)||!['production','entering','rehearsal','recovery_required'].includes(value.mode))throw Error('rehearsal_mode_unavailable');
      seenActive=value.active||value.mode!=='production';badge.hidden=!seenActive;
      badge.textContent=seenActive?'REHEARSAL — not broadcasting':'';badge.dataset.state='ready';
      doc.documentElement.dataset.rehearsalMode=seenActive?'active':'production';
      doc.documentElement.dataset.rehearsalGeneration=value.generation;
    }
    function schedule(){clearTimer(timer);if(!closed)timer=setTimer(()=>{timer=null;void poll();},Math.min(1000*2**Math.min(failures,4),15000));}
    async function poll(){
      if(closed||pending)return;pending=true;const token=++serial;
      try{const response=await request('/api/guest/rehearsal',{cache:'no-store',credentials:'same-origin',headers:{Accept:'application/json'}});if(!response.ok)throw Error('rehearsal_mode_unavailable');const value=await response.json();if(closed||token!==serial)return;paint(value);failures=0;}
      catch(error){if(closed||token!==serial)return;++failures;if(seenActive){badge.hidden=false;badge.textContent='REHEARSAL — status unavailable';badge.dataset.state='warning';}}
      finally{pending=false;if(!closed)schedule();}
    }
    function close(){if(closed)return;closed=true;++serial;clearTimer(timer);}
    void poll();return {close};
  }
  window.ProducerRehearsalBadge=Object.freeze({create});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>create(),{once:true});else create();
})();
