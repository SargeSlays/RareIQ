(function(host){
  'use strict';const frame=document.querySelector('iframe.program'),button=document.querySelector('[data-browser-review-open]');if(!frame||!button)return;
  let preparing=new URLSearchParams(location.search).get('browser-review')==='1',wasOpen=false;
  const open=()=>{try{frame.contentWindow.ProducerProgramOutput?.reviewBrowserSources();}catch(_){button.title='Wait for Program to connect, then try again.';}};
  const message=event=>{if(event.origin!==location.origin||event.source!==frame.contentWindow||event.data?.type!=='producer-browser-review')return;frame.style.pointerEvents=event.data.open?'auto':'';if((wasOpen&&!event.data.open)||event.data.note){preparing=false;const url=new URL(location.href);url.searchParams.delete('browser-review');history.replaceState(null,'',url);}wasOpen=event.data.open===true;button.hidden=!preparing||event.data.open===true||event.data.needsReview!==true;button.title=String(event.data.note||'Review browser pages in this output before the show.');const note=document.querySelector('[data-browser-review-note]');if(note){note.textContent=String(event.data.note||'');note.hidden=!event.data.note;}};
  button.addEventListener('click',open);host.addEventListener('message',message);
  if(new URLSearchParams(location.search).get('browser-review')==='1')frame.addEventListener('load',open,{once:true});
  host.addEventListener('pagehide',()=>{button.removeEventListener('click',open);host.removeEventListener('message',message);},{once:true});
})(window);
