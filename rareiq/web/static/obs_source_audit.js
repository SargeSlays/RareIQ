(() => {
  "use strict";
  let instance;
  function init({request,format}){
    if(instance)return instance;
    const $=id=>document.getElementById(id),button=$("obsSourceCheck"),status=$("obsSourceAuditStatus"),rows=$("obsSourceAuditRows");
    if(!button||!status||!rows)return null;
    let busy=false,generation=0,controller=null;
    const message=(state,title,detail)=>{
      status.dataset.state=state;status.querySelector("strong").textContent=title;status.querySelector("span").textContent=detail;
    };
    function invalidate(detail="OBS setup may have changed. Run Check sources for a new snapshot."){
      generation++;controller?.abort();controller=null;busy=false;button.disabled=false;
      rows.replaceChildren();message("unknown","Check needed",detail);
    }
    async function check(){
      if(busy)return;
      busy=true;button.disabled=true;const run=++generation;controller=new AbortController();
      rows.replaceChildren();message("checking","Checking source configuration…","Read-only inspection. No scenes, sources or output controls will be changed.");
      try{
        const payload=await request("/api/production/obs/sources/check",{method:"POST",body:JSON.stringify({base_url:location.origin}),timeoutMs:20000,retries:0,signal:controller.signal});
        if(run!==generation)return;
        const audit=payload.audit;
        if(!audit||!Array.isArray(audit.sources)||!audit.sources.length||typeof audit.connected!=="boolean")throw new Error("Incomplete source report");
        const sources=audit.sources.map(item=>{
          if(!item||typeof item!=="object")throw new Error("Invalid source report");
          const state=audit.connected&&["configured","attention","missing","unavailable"].includes(item.state)?item.state:"unavailable";
          return {...item,state};
        }),configured=sources.filter(item=>item.state==="configured").length;
        const unknown=sources.filter(item=>item.state==="unavailable").length,attention=sources.length-configured-unknown;
        const checked=Number(audit.checked_at),stamp=Number.isFinite(checked)&&checked>0?new Date(checked*1000).toLocaleTimeString():"time unavailable";
        message(audit.connected?(configured===sources.length?"configured":"attention"):"unknown",
          audit.connected?`${configured} of ${sources.length} configured · ${attention} need attention · ${unknown} not checked`:"OBS sources not checked",
          `${audit.diagnostic?.message||"Review each source below."} Snapshot: ${stamp}.`);
        rows.replaceChildren(...sources.map(item=>{
          const row=document.createElement("article"),state=["configured","attention","missing","unavailable"].includes(item.state)?item.state:"unavailable";
          row.dataset.state=state;
          row.innerHTML='<header><strong></strong><span class="obs-source-state"></span></header><p></p><code></code><ul></ul>';
          row.querySelector("strong").textContent=item.label||item.scene||"Browser source";
          row.querySelector(".obs-source-state").textContent={configured:"Configured",attention:"Review setup",missing:"Missing",unavailable:"Not checked"}[state];
          row.querySelector("p").textContent=format(item);
          row.querySelector("code").textContent=item.url||"";
          const issues=Array.isArray(item.issues)?item.issues:[];
          row.querySelector("ul").replaceChildren(...issues.map(issue=>{const li=document.createElement("li");li.textContent=issue.message;return li;}));
          row.querySelector("ul").hidden=!issues.length;
          return row;
        }));
      }catch{
        if(run!==generation)return;
        rows.replaceChildren();message("unknown","Source check unavailable","The request did not finish. Check the connection and try again; no settings were changed.");
      }finally{
        if(run===generation){busy=false;button.disabled=false;controller=null;}
      }
    }
    button.addEventListener("click",check);
    document.addEventListener("rareiq:api-start",event=>{
      if(event.detail?.method==="POST"&&["/api/production/obs/settings","/api/production/obs/bootstrap"].includes(event.detail.path))invalidate();
    });
    instance={check,invalidate};return instance;
  }
  window.RareIQObsSourceAudit={init};
})();
