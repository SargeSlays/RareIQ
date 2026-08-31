(function(root){
  "use strict";
  const START_KEY="rareiq.studio.start-workspace.v1";
  const WORKSPACES=new Set(["broadcast","live","collection","creator","soundboard","voice-mod","camera-fx","spotify","ai","library","settings"]);
  const aliases={studio:"broadcast",cards:"live"};
  function initialWorkspace(search=location.search,storage){
    const requested=new URLSearchParams(search).get("workspace");
    if(requested&&WORKSPACES.has(aliases[requested]||requested))return aliases[requested]||requested;
    try{return (storage||localStorage).getItem(START_KEY)==="live"?"live":"broadcast";}catch{return "broadcast";}
  }
  function init({navigate,view}){
    const preference=document.getElementById("studioStartWorkspace");
    if(preference){
      preference.value=initialWorkspace("");
      preference.addEventListener("change",()=>{
        const value=preference.value==="live"?"live":"broadcast";
        const status=document.getElementById("studioStartWorkspaceStatus");
        try{localStorage.setItem(START_KEY,value);if(status)status.textContent="Start page saved for this browser.";}
        catch{if(status)status.textContent="Start page could not be saved in this browser.";}
      });
    }
    document.querySelectorAll("[data-studio-open]").forEach(button=>button.addEventListener("click",()=>{
      const target=button.dataset.studioOpen;
      if(!WORKSPACES.has(target))return;
      navigate(target);
      if(target==="broadcast"&&button.dataset.studioView)view(button.dataset.studioView);
    }));
  }
  root.RareIQStudioShell=Object.freeze({initialWorkspace,init});
})(window);
