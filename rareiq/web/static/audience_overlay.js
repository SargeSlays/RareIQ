(function(root){
  'use strict';
  const animations=new Set(['slide','pop','spotlight']);
  function graphic(value){
    if(!value||typeof value.title!=='string'||value.title.length>240||typeof value.subtitle!=='string'||value.subtitle.length>80||!animations.has(value.animation))return null;
    if(!Number.isInteger(value.duration_ms)||value.duration_ms<1500||value.duration_ms>10000)return null;
    if(!['twitch','youtube','kick','preview'].includes(value.platform))return null;
    return value;
  }
  if(typeof module==='object'&&module.exports){module.exports={graphic};return;}
  const box=document.getElementById('audienceGraphic'),title=document.getElementById('audienceGraphicTitle'),kind=document.getElementById('audienceGraphicKind'),platform=document.getElementById('audienceGraphicPlatform');
  const preview=new URLSearchParams(location.search).get('preview')==='1';
  document.body.dataset.preview=String(preview);
  document.getElementById('audiencePreviewLabel').hidden=!preview;
  let timer=0,lastId=null,closed=false;
  function clear(){clearTimeout(timer);box.hidden=true;lastId=null;}
  function render(value,remaining,id){
    const item=graphic(value);
    if(!item||remaining<=0){clear();return;}
    if(id!==lastId){box.hidden=true;void box.offsetWidth;box.dataset.animation=item.animation;lastId=id;}
    title.textContent=item.title;kind.textContent=item.subtitle;platform.textContent=item.platform==='preview'?'Animation preview':item.platform;
    box.hidden=false;clearTimeout(timer);timer=setTimeout(clear,Math.min(item.duration_ms,remaining));
  }
  if(preview){
    window.addEventListener('message',event=>{
      if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='producer-audience-preview')return;
      const item=graphic(event.data.graphic);
      if(item)render(item,item.duration_ms,Symbol('preview'));
    });
  }else{
    async function poll(){
      if(closed)return;
      const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),3000);
      try{
        const response=await fetch('/api/production/audience/output',{cache:'no-store',signal:controller.signal});
        if(!response.ok)throw new Error('unavailable');
        const data=await response.json(),item=data.enabled&&data.graphic;
        if(!item||!Number.isFinite(item.remaining_ms))clear();
        else render(item,item.remaining_ms,item.id);
      }catch(_){clear();}finally{clearTimeout(timeout);if(!closed)setTimeout(poll,500);}
    }
    poll();
  }
  window.addEventListener('pagehide',()=>{closed=true;clear();});
})(typeof window==='object'?window:globalThis);
