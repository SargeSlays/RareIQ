(function(root){
  "use strict";
  const KEY="rareiq.studio.docks.v1", POSITIONS=["left","right","top","bottom","float"];
  const DEFAULTS={"production-scenes":"left","show-preflight":"right","production-session":"bottom","operator-health":"bottom"};
  function normalize(raw,ids){
    const tools={};
    for(const id of ids){
      const saved=raw?.version===1?raw.tools?.[id]:null;
      tools[id]={position:POSITIONS.includes(saved?.position)?saved.position:DEFAULTS[id]||"right",
        visible:typeof saved?.visible==="boolean"?saved.visible:Boolean(DEFAULTS[id]),
        height:Number.isFinite(saved?.height)?Math.max(160,Math.min(800,saved.height)):(["production-scenes","show-preflight"].includes(id)?560:280),
        x:Number.isFinite(saved?.x)?Math.max(0,Math.min(3000,saved.x)):40,
        y:Number.isFinite(saved?.y)?Math.max(0,Math.min(1800,saved.y)):40};
    }
    return {version:1,tools};
  }
  function init(workspace){
    if(!workspace||workspace._studioDocks)return workspace?._studioDocks;
    const stage=workspace.querySelector(".production-switcher-shell");
    if(!stage)return null;
    const registry=new Map();
    workspace.querySelectorAll("[data-broadcast-panel]").forEach(panel=>{
      if(panel===stage||panel.classList.contains("workspace-readiness"))return;
      const id=[...panel.classList].find(name=>!name.startsWith("studiox-"));
      if(!id||registry.has(id))return;
      const labels={"production-session-metadata":"Show details","production-session":"Session control","studio-product-bar":"Studio preferences","production-report-actions":"Reports","break-history-controls":"History filters"};
      registry.set(id,{panel,view:panel.dataset.broadcastPanel,title:labels[id]||panel.querySelector("h2,h3")?.textContent?.trim()||id.replaceAll("-"," ")});
    });
    let raw;try{raw=JSON.parse(root.localStorage.getItem(KEY));}catch{}
    let state=normalize(raw,[...registry.keys()]),view="live";
    const el=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text)node.textContent=text;return node;};
    const button=(text,action)=>{const node=el("button","riq-button",text);node.type="button";node.addEventListener("click",action);return node;};
    const frame=el("section","studio-dock-frame"),toolbar=el("header","studio-dock-toolbar"),grid=el("div","studio-dock-grid");
    frame.setAttribute("aria-label","Customizable production studio");
    const title=el("div","studio-dock-title"),heading=el("strong","","Production studio"),status=el("span","studio-dock-status","Your tools. Your layout.");
    status.setAttribute("role","status");title.append(heading,status);
    const toolWindows=root.ProducerStudioToolWindows?.create({status:message=>{status.textContent=message;},returned:id=>{root.switchWorkspace?.("broadcast");root.setBroadcastWorkspaceView?.("live");state.tools[id].visible=true;render();registry.get(id)?.position.focus();}});
    const library=el("section","studio-dock-library");library.id="studioDockLibrary";library.hidden=true;library.setAttribute("aria-label","Studio tools");
    const toolsButton=button("Tools",()=>{library.hidden=!library.hidden;toolsButton.setAttribute("aria-expanded",String(!library.hidden));});
    toolsButton.setAttribute("aria-controls",library.id);toolsButton.setAttribute("aria-expanded","false");
    const fullscreen=button("Full screen",async()=>{
      try{if(document.fullscreenElement===workspace)await document.exitFullscreen();else if(workspace.requestFullscreen)await workspace.requestFullscreen();else status.textContent="Full screen is unavailable in this browser. Use the browser's full screen command.";}
      catch{status.textContent="The browser could not enter full screen. You can keep using the studio here.";}
    });
    document.addEventListener("fullscreenchange",()=>{fullscreen.textContent=document.fullscreenElement===workspace?"Exit full screen":"Full screen";fullscreen.setAttribute("aria-pressed",String(document.fullscreenElement===workspace));});
    fullscreen.setAttribute("aria-pressed","false");
    const reset=button("Reset layout",()=>{state=normalize(null,[...registry.keys()]);render();save("Default layout restored.");});
    toolbar.append(title,toolsButton,reset,fullscreen);
    const help=el("p","","Choose the tools shown in Live Control. Drag a tool header to an edge, or choose its position. Floating tools stay inside this studio.");
    library.append(help);
    const regions={};
    for(const position of POSITIONS){
      const region=el("section",`studio-dock-region studio-dock-${position}`);region.dataset.dockRegion=position;
      region.setAttribute("aria-label",`${position} tools`);regions[position]=region;grid.append(region);
      if(position!=="float"){
        region.addEventListener("dragover",event=>{if(event.dataTransfer.types.includes("application/x-pp-tool")){event.preventDefault();region.classList.add("is-drop-target");}});
        region.addEventListener("dragleave",()=>region.classList.remove("is-drop-target"));
        region.addEventListener("drop",event=>{event.preventDefault();region.classList.remove("is-drop-target");const id=event.dataTransfer.getData("application/x-pp-tool");if(registry.has(id))place(id,position);});
      }
    }
    const center=el("main","studio-dock-center");center.append(stage);grid.append(center);
    frame.append(toolbar,library,grid);workspace.querySelector(".broadcast-workspace-tabs").after(frame);
    function save(message="Layout saved for this browser."){
      try{root.localStorage.setItem(KEY,JSON.stringify(state));status.textContent=message;}
      catch{status.textContent="Layout changed for this visit. This browser could not save it.";}
    }
    function place(id,position){state.tools[id].position=position;state.tools[id].visible=true;render();save();registry.get(id).position.focus();}
    function clampFloat(item,saved){
      const bounds=grid.getBoundingClientRect();
      if(view!=="live"||item.wrapper.hidden||!bounds.width||!bounds.height)return;
      saved.x=Math.min(saved.x,Math.max(0,bounds.width-item.wrapper.offsetWidth));
      saved.y=Math.min(saved.y,Math.max(0,bounds.height-70));
      item.wrapper.style.left=`${saved.x}px`;item.wrapper.style.top=`${saved.y}px`;
    }
    for(const [id,item] of registry){
      const wrapper=el("section","studio-dock-tool"),header=el("header","studio-dock-handle"),name=el("strong","",item.title),position=el("select");
      wrapper.dataset.studioTool=id;wrapper.setAttribute("aria-label",item.title);header.draggable=true;
      position.setAttribute("aria-label",`${item.title} position`);
      for(const value of POSITIONS){const option=el("option","",value==="float"?"Float in studio":`Dock ${value}`);option.value=value;position.append(option);}
      position.addEventListener("change",()=>place(id,position.value));
      const hide=button("Hide",()=>{state.tools[id].visible=false;render();save(`${item.title} hidden. Restore it from Tools.`);toolsButton.focus();});
      hide.setAttribute("aria-label",`Hide ${item.title}`);
      const pop=button("Pop out",()=>toolWindows?.open(id,item.title,item.panel));
      pop.setAttribute("aria-label",`Pop out ${item.title}`);pop.disabled=!toolWindows;
      if(!toolWindows)pop.title="Tool windows are unavailable. Reload the studio to try again.";
      header.append(name,position,pop,hide);wrapper.append(header,item.panel);
      const label=el("label"),toggle=el("input");toggle.type="checkbox";toggle.addEventListener("change",()=>{state.tools[id].visible=toggle.checked;render();save();});label.append(toggle,document.createTextNode(item.title));library.append(label);
      Object.assign(item,{wrapper,position,toggle,hide});
      header.addEventListener("dragstart",event=>{event.dataTransfer.setData("application/x-pp-tool",id);event.dataTransfer.effectAllowed="move";grid.classList.add("is-dragging");});
      header.addEventListener("dragend",()=>{grid.classList.remove("is-dragging");for(const region of Object.values(regions))region.classList.remove("is-drop-target");});
      // Floating uses the same nodes and listeners; no second controller or media owner.
      header.addEventListener("pointerdown",event=>{
        if(state.tools[id].position!=="float"||event.target.closest("button,select")||event.button!==0||view!=="live")return;
        event.preventDefault();header.draggable=false;header.setPointerCapture(event.pointerId);
        const start={x:event.clientX,y:event.clientY,left:state.tools[id].x,top:state.tools[id].y};
        const move=e=>{state.tools[id].x=Math.max(0,start.left+e.clientX-start.x);state.tools[id].y=Math.max(0,start.top+e.clientY-start.y);clampFloat(item,state.tools[id]);};
        const end=()=>{header.removeEventListener("pointermove",move);header.removeEventListener("pointerup",end);header.removeEventListener("pointercancel",end);header.draggable=true;save();};
        header.addEventListener("pointermove",move);header.addEventListener("pointerup",end);header.addEventListener("pointercancel",end);
      });
      wrapper.addEventListener("pointerup",()=>{if(view!=="live")return;const height=parseFloat(wrapper.style.height);if(Number.isFinite(height)&&height!==state.tools[id].height){state.tools[id].height=Math.max(160,Math.min(800,height));save();}});
    }
    function render(){
      frame.dataset.view=view;stage.hidden=view!=="live";center.hidden=view!=="live";
      for(const [id,item] of registry){
        const saved=state.tools[id],region=regions[saved.position];
        if(item.wrapper.parentElement!==region)region.append(item.wrapper);
        item.wrapper.hidden=view==="live"?!saved.visible:item.view!==view;
        item.panel.hidden=false;item.position.value=saved.position;item.toggle.checked=saved.visible;item.hide.hidden=view!=="live";
        item.wrapper.dataset.position=saved.position;
        item.wrapper.style.height=view==="live"?`${saved.height}px`:"";
        if(saved.position==="float"&&!item.wrapper.hidden)clampFloat(item,saved);
      }
      for(const [position,region] of Object.entries(regions))region.dataset.empty=String(![...region.children].some(node=>!node.hidden));
    }
    root.addEventListener("resize",()=>{for(const [id,item] of registry)if(state.tools[id].position==="float")clampFloat(item,state.tools[id]);});
    if(typeof ResizeObserver!=="undefined")new ResizeObserver(()=>{for(const [id,item] of registry)if(state.tools[id].position==="float")clampFloat(item,state.tools[id]);}).observe(grid);
    workspace.dataset.studioDocks="ready";
    workspace._studioDocks={setView(next){view=next;render();},snapshot(){return normalize(state,[...registry.keys()]);}};
    render();return workspace._studioDocks;
  }
  const api=Object.freeze({init,normalize,KEY,POSITIONS});
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  else root.ProducerStudioDocks=api;
})(typeof window!=="undefined"?window:globalThis);
