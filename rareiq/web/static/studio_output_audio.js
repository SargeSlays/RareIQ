/* Keep clean output untouched unless the browser requires a sound-enable click. */
(function(host){
  'use strict';
  const frame=host.document.querySelector('iframe.program'),button=host.document.querySelector('[data-output-audio-enable]');
  if(!frame||!button)return;
  const status=event=>{
    if(event.origin!==host.location.origin||event.source!==frame.contentWindow||event.data?.type!=='producer-output-audio'||typeof event.data.blocked!=='boolean')return;
    button.hidden=!event.data.blocked;
  };
  const enable=()=>{
    // Direct same-origin invocation preserves the click's user activation.
    try{frame.contentWindow.ProducerProgramOutput?.resumeAudio();}catch(_){/* Keep the recovery button visible. */}
  };
  const reset=()=>{
    // A blocked report may arrive before iframe load. Re-read the current child
    // instead of erasing that report until a status change happens to occur.
    try{const output=frame.contentDocument?.querySelector('[data-producer-program-output]');if(output)button.hidden=output.dataset.audioBlocked!=='true';}catch(_){/* Preserve the last known recovery state. */}
  };
  host.addEventListener('message',status);button.addEventListener('click',enable);frame.addEventListener('load',reset);
  host.addEventListener('pagehide',()=>{host.removeEventListener('message',status);button.removeEventListener('click',enable);frame.removeEventListener('load',reset);},{once:true});
})(window);
