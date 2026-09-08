(function(root){
  "use strict";
  const KEY="rareiq.studio.docks.v1", POSITIONS=["left","right","top","bottom","float"];
  const DEFAULTS={"production-scenes":"left","show-preflight":"right","production-session":"bottom","operator-health":"bottom"};
  const SETS_KEY="rareiq.studio.toolsets.v1";
  const WORKSPACES={soundboard:"Soundboard","voice-mod":"Voice studio","camera-fx":"Camera effects",spotify:"Spotify DJ",creator:"Creator studio",live:"RareIQ Card Studio",collection:"Collection",ai:"AI Lab",library:"Reference library",settings:"Studio settings"};
  const PORTABLE={soundboard:".soundboard-app-shell","voice-mod":".voice-mod-shell"};
  function normalizeSets(raw,ids){
    if(raw?.version!==1)raw=null;
    const profiles=[],seen=new Set(),allowed=values=>Array.isArray(values)?Object.keys(WORKSPACES).filter(id=>values.includes(id)&&!ids.includes(`workspace-${id}`)):[];
    if(raw?.version===1&&Array.isArray(raw.profiles))for(const item of raw.profiles.slice(0,12)){
      if(!item||typeof item.id!=="string"||!/^[\w-]{1,80}$/.test(item.id)||seen.has(item.id)||typeof item.label!=="string"||!item.label.trim())continue;
      seen.add(item.id);profiles.push({id:item.id,label:item.label.trim().slice(0,60),layout:normalize(item.layout,ids,item.workspaces),workspaces:allowed(item.workspaces)});
    }
    return {version:1,active:seen.has(raw?.active)?raw.active:"",workspaces:allowed(raw?.workspaces),profiles};
  }
  function normalize(raw,ids,previousWorkspaces=[]){
    const tools={};
    for(const id of ids){
      const saved=raw?.version===1?raw.tools?.[id]:null;
      tools[id]={position:POSITIONS.includes(saved?.position)?saved.position:DEFAULTS[id]||"right",
        visible:typeof saved?.visible==="boolean"?saved.visible:Boolean(DEFAULTS[id]||(Array.isArray(previousWorkspaces)&&previousWorkspaces.includes(id.replace(/^workspace-/,""))&&id.startsWith("workspace-"))),
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
    for(const [id,selector] of Object.entries(PORTABLE)){
      const origin=document.querySelector(`.workspace[data-workspace="${id}"]`),panel=origin?.querySelector(selector);
      if(!panel)continue;
      const anchor=document.createComment(`Studio home: ${id}`);panel.before(anchor);
      panel.dataset.studioWorkspaceTool=id;panel.tabIndex=0;panel.setAttribute("aria-label",WORKSPACES[id]);
      // These remain the original controls and media owner. Keys in an audio tool never switch Program.
      panel.addEventListener("keydown",event=>{
        if(!panel.closest(".studio-dock-tool"))return;
        event.stopPropagation();
        if(id!=="soundboard"||event.repeat||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||!/^\d$/.test(event.key)||event.target.closest("input,textarea,select,button,a,[contenteditable=true]"))return;
        const pad=panel.querySelector(`[data-soundboard-shortcut="${event.key==="0"?"10":event.key}"]`);
        if(pad){event.preventDefault();pad.click();}
      });
      let routing;
      if(id==="soundboard"){
        const output=panel.querySelector(".soundboard-output-controls");
        if(output){
          const home=document.createComment("Soundboard routing home"),details=document.createElement("details"),summary=document.createElement("summary");
          output.before(home);details.className="studio-audio-routing";summary.textContent="Audio output & routing";details.append(summary);routing={output,home,details};
        }
      }
      registry.set(`workspace-${id}`,{panel,origin,anchor,routing,view:"live",title:WORKSPACES[id]});
    }
    let raw;try{raw=JSON.parse(root.localStorage.getItem(KEY));}catch{}
    let rawSets;try{rawSets=JSON.parse(root.localStorage.getItem(SETS_KEY));}catch{}
    let state=normalize(raw,[...registry.keys()],rawSets?.version===1?rawSets.workspaces:[]),view="live",activeWorkspace=workspace.classList.contains("active")?"broadcast":"";
    let sets=normalizeSets(rawSets,[...registry.keys()]);
    const el=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text)node.textContent=text;return node;};
    const button=(text,action)=>{const node=el("button","riq-button",text);node.type="button";node.addEventListener("click",action);return node;};
    const frame=el("section","studio-dock-frame"),toolbar=el("header","studio-dock-toolbar"),grid=el("div","studio-dock-grid");
    frame.setAttribute("aria-label","Customizable production studio");
    const title=el("div","studio-dock-title"),heading=el("strong","","Production studio"),status=el("span","studio-dock-status","Your tools. Your layout.");
    status.setAttribute("role","status");title.append(heading,status);
    const toolWindows=root.ProducerStudioToolWindows?.create({status:message=>{status.textContent=message;},returned:id=>{root.switchWorkspace?.("broadcast");root.setBroadcastWorkspaceView?.("live");state.tools[id].visible=true;render();drawerTrigger=registry.get(id)?.options;if(library.open)library.close();drawerTrigger?.focus();}});
    const library=el("dialog","studio-dock-library");library.id="studioDockLibrary";library.hidden=true;library.setAttribute("aria-label","Session tools");
    let drawerTrigger;
    function openLibrary(trigger=toolsButton,id){
      drawerTrigger=trigger;library.hidden=false;if(!library.open)library.showModal();toolsButton.setAttribute("aria-expanded","true");
      if(id){search.value="";filterRows();registry.get(id).row.scrollIntoView({block:"nearest"});registry.get(id).position.focus();}
    }
    const toolsButton=button("Session tools",()=>openLibrary());
    toolsButton.setAttribute("aria-controls",library.id);toolsButton.setAttribute("aria-expanded","false");
    const fullscreen=button("Full screen",async()=>{
      try{if(document.fullscreenElement===workspace)await document.exitFullscreen();else if(workspace.requestFullscreen)await workspace.requestFullscreen();else status.textContent="Full screen is unavailable in this browser. Use the browser's full screen command.";}
      catch{status.textContent="The browser could not enter full screen. You can keep using the studio here.";}
    });
    document.addEventListener("fullscreenchange",()=>{fullscreen.textContent=document.fullscreenElement===workspace?"Exit full screen":"Full screen";fullscreen.setAttribute("aria-pressed",String(document.fullscreenElement===workspace));});
    fullscreen.setAttribute("aria-pressed","false");
    const reset=button("Reset layout",()=>{state=normalize(null,[...registry.keys()]);render();save("Default layout restored.");});
    const tabs=workspace.querySelector(".broadcast-workspace-tabs"),viewChoice=el("select"),launcher=el("select");
    viewChoice.setAttribute("aria-label","Studio view");
    tabs.querySelectorAll("[data-broadcast-view]").forEach(tab=>{const option=el("option","",tab.textContent);option.value=tab.dataset.broadcastView;viewChoice.append(option);});
    viewChoice.addEventListener("change",()=>root.setBroadcastWorkspaceView?.(viewChoice.value));
    let navigating=false;
    async function openWorkspace(id){
      if(!WORKSPACES[id]||navigating)return;
      navigating=true;
      try{if(document.fullscreenElement===workspace)await document.exitFullscreen();if(library.open){drawerTrigger=null;library.close();}root.switchWorkspace?.(id);}
      catch{status.textContent=drawerStatus.textContent="Could not leave full screen. Exit full screen and try opening the workspace again.";}
      finally{navigating=false;launcher.value="";}
    }
    launcher.setAttribute("aria-label","Open session workspace");launcher.addEventListener("change",()=>openWorkspace(launcher.value));
    toolbar.append(viewChoice,title,launcher,toolsButton,fullscreen);
    const drawerHeader=el("header","studio-tool-drawer-heading"),drawerTitle=el("h2","","Session tools"),close=button("Close",()=>library.close());
    drawerHeader.append(drawerTitle,close);
    const help=el("p","","Choose your tools for Live Control. Workspaces are added to Open session workspace. Selection does not start a show, playback, or recording.");
    const profileBar=el("section","studio-tool-profiles"),profileChoice=el("select"),profileName=el("input");
    profileChoice.setAttribute("aria-label","Saved tool set");profileName.setAttribute("aria-label","New tool set name");profileName.placeholder="Project or session tool set";profileName.maxLength=60;
    const newSet=button("Save as new",()=>{
      const label=profileName.value.trim();if(!label){drawerStatus.textContent="Enter a name for this tool set.";profileName.focus();return;}
      if(sets.profiles.length>=12){drawerStatus.textContent="Twelve tool sets are saved. Select one to update it, or remove a saved set.";return;}
      const id=root.crypto?.randomUUID?.()||`set-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      sets.profiles.push({id,label,layout:normalize(state,[...registry.keys()]),workspaces:[...sets.workspaces]});sets.active=id;profileName.value="";render();save("Tool set saved. Use Save changes to update this saved set.");
    });
    const updateSet=button("Save changes",()=>{const active=sets.profiles.find(item=>item.id===sets.active);if(!active)return;active.layout=normalize(state,[...registry.keys()]);active.workspaces=[...sets.workspaces];render();save("Saved tool set updated.");});
    const removeSet=button("Remove saved set",()=>{sets.profiles=sets.profiles.filter(item=>item.id!==sets.active);sets.active="";render();save("Saved tool set removed. Your current tools remain available.");});
    profileChoice.addEventListener("change",()=>{sets.active=profileChoice.value;const selected=sets.profiles.find(item=>item.id===sets.active);if(selected){state=normalize(selected.layout,[...registry.keys()]);sets.workspaces=[...selected.workspaces];}render();save("Tool set loaded.");});
    profileBar.append(profileChoice,profileName,newSet,updateSet,removeSet);
    const bulk=el("div","studio-tool-bulk"),search=el("input"),drawerStatus=el("p","studio-tool-drawer-status");
    search.type="search";search.placeholder="Find a tool…";search.setAttribute("aria-label","Find session tools");drawerStatus.setAttribute("role","status");
    function selectAll(visible){for(const item of Object.values(state.tools))item.visible=visible;sets.workspaces=visible?[...workspaceToggles.keys()]:[];render();save(visible?"All session tools selected.":"Session tools cleared. Preview and Program remain available.");}
    bulk.append(button("Select all tools",()=>selectAll(true)),button("Clear all tools",()=>selectAll(false)),reset);
    const list=el("div","studio-tool-list"),rows=[],empty=el("p","studio-tools-empty","No tools match your search.");empty.hidden=true;list.append(empty);
    function filterRows(){const query=search.value.trim().toLocaleLowerCase();for(const row of rows)row.hidden=!row.dataset.search.includes(query);empty.hidden=rows.some(row=>!row.hidden);}
    search.addEventListener("input",filterRows);
    library.append(drawerHeader,help,profileBar,bulk,search,drawerStatus,list);
    library.addEventListener("close",()=>{library.hidden=true;toolsButton.setAttribute("aria-expanded","false");drawerTrigger?.focus();});
    library.addEventListener("keydown",event=>event.stopPropagation());
    const workspaceToggles=new Map();
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
      try{root.localStorage.setItem(KEY,JSON.stringify(state));root.localStorage.setItem(SETS_KEY,JSON.stringify(sets));status.textContent=drawerStatus.textContent=message;}
      catch{status.textContent=drawerStatus.textContent="Layout changed for this visit. This browser could not save it.";}
    }
    function place(id,position){state.tools[id].position=position;state.tools[id].visible=true;render();save();if(library.open)registry.get(id).position.focus();else registry.get(id).options.focus();}
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
      const pop=button("Pop out",()=>toolWindows?.open(id,item.title,item.panel));
      pop.setAttribute("aria-label",`Pop out ${item.title}`);pop.disabled=!toolWindows;
      if(!toolWindows)pop.title="Tool windows are unavailable. Reload the studio to try again.";
      const options=button("⋯",()=>openLibrary(options,id));options.setAttribute("aria-label",`Options for ${item.title}`);options.setAttribute("aria-haspopup","dialog");
      header.append(name,options);wrapper.append(header,item.panel);if(item.origin)wrapper.dataset.toolWorkspace=item.origin.dataset.workspace;
      const row=el("section","studio-tool-row"),label=el("label"),toggle=el("input");row.dataset.search=(item.title+" "+item.view).toLocaleLowerCase();row.dataset.toolRow=id;
      toggle.type="checkbox";toggle.addEventListener("change",()=>{state.tools[id].visible=toggle.checked;render();save();});label.append(toggle,document.createTextNode(item.title));
      const hint=el("small","",`${[...tabs.querySelectorAll("[data-broadcast-view]")].find(tab=>tab.dataset.broadcastView===item.view)?.textContent||item.view} · Studio dock`);row.append(label,hint,position,pop);list.append(row);rows.push(row);
      Object.assign(item,{wrapper,position,toggle,options,row});
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
    for(const [id,labelText] of Object.entries(WORKSPACES).filter(([id])=>!registry.has(`workspace-${id}`))){
      const row=el("section","studio-tool-row"),label=el("label"),toggle=el("input");row.dataset.search=labelText.toLocaleLowerCase();toggle.type="checkbox";
      toggle.addEventListener("change",()=>{sets.workspaces=Object.keys(WORKSPACES).filter(key=>key===id?toggle.checked:sets.workspaces.includes(key));render();save();});label.append(toggle,document.createTextNode(labelText));
      const open=button("Open workspace",()=>openWorkspace(id));open.setAttribute("aria-label",`Open ${labelText} workspace`);
      row.append(label,el("small","","Workspace · opens in its own view"),open);list.append(row);rows.push(row);workspaceToggles.set(id,toggle);
    }
    function fitFrame(){
      if(view!=="live"||root.innerWidth<=1100||!workspace.getBoundingClientRect().width)return;
      frame.style.setProperty("--studio-frame-height",`${Math.max(320,root.innerHeight-Math.max(0,frame.getBoundingClientRect().top)-20)}px`);
    }
    function render(){
      frame.dataset.view=view;viewChoice.value=view;stage.hidden=view!=="live";center.hidden=view!=="live";
      for(const [id,item] of registry){
        const saved=state.tools[id],region=regions[saved.position];
        if(item.wrapper.parentElement!==region)region.append(item.wrapper);
        item.wrapper.hidden=view==="live"?!saved.visible:item.view!==view;
        if(item.origin){
          const docked=activeWorkspace==="broadcast"&&view==="live"&&saved.visible;
          if(docked&&item.panel.parentElement!==item.wrapper)item.wrapper.append(item.panel);
          else if(!docked&&item.panel.parentElement!==item.origin)item.anchor.after(item.panel);
          if(item.routing){
            const {output,home,details}=item.routing;
            if(docked){if(details.parentElement!==item.panel)home.after(details);if(output.parentElement!==details)details.append(output);}
            else{home.after(output);details.remove();}
          }
        }
        item.panel.hidden=false;item.position.value=saved.position;item.toggle.checked=saved.visible;
        item.wrapper.dataset.position=saved.position;
        item.wrapper.style.height=view==="live"?`${saved.height}px`:"";
        if(saved.position==="float"&&!item.wrapper.hidden)clampFloat(item,saved);
      }
      for(const region of Object.values(regions)){const count=[...region.children].filter(node=>!node.hidden).length;region.dataset.empty=String(!count);region.dataset.count=String(count);}
      const selectedCount=Object.values(state.tools).filter(item=>item.visible).length+sets.workspaces.length;
      toolsButton.textContent=`Session tools · ${selectedCount}`;
      launcher.replaceChildren(Object.assign(el("option","","Open workspace…"),{value:""}),...sets.workspaces.map(id=>Object.assign(el("option","",WORKSPACES[id]),{value:id})));
      launcher.hidden=!sets.workspaces.length;
      for(const [id,toggle] of workspaceToggles)toggle.checked=sets.workspaces.includes(id);
      profileChoice.replaceChildren(Object.assign(el("option","","Current studio"),{value:""}),...sets.profiles.map(item=>Object.assign(el("option","",item.label),{value:item.id})));
      const active=sets.profiles.find(item=>item.id===sets.active),changed=active&&(JSON.stringify(active.layout)!==JSON.stringify(state)||JSON.stringify(active.workspaces)!==JSON.stringify(sets.workspaces));
      if(changed)profileChoice.querySelector(`option[value="${sets.active}"]`).textContent=active.label+" · modified";
      profileChoice.value=sets.active;updateSet.disabled=!changed;updateSet.title=sets.active?"Update the selected saved tool set":"Choose a saved tool set first";removeSet.disabled=!sets.active;removeSet.title=sets.active?"Remove this saved tool set":"Choose a saved tool set first";
      root.requestAnimationFrame(fitFrame);
    }
    root.addEventListener("resize",()=>{fitFrame();for(const [id,item] of registry)if(state.tools[id].position==="float")clampFloat(item,state.tools[id]);});
    if(typeof ResizeObserver!=="undefined")new ResizeObserver(()=>{for(const [id,item] of registry)if(state.tools[id].position==="float")clampFloat(item,state.tools[id]);}).observe(grid);
    workspace.dataset.studioDocks="ready";
    if(typeof ResizeObserver!=="undefined")new ResizeObserver(fitFrame).observe(workspace);
    workspace._studioDocks={syncWorkspace(name){activeWorkspace=name;render();},setView(next){view=next;render();},snapshot(){return normalize(state,[...registry.keys()]);}};
    render();return workspace._studioDocks;
  }
  const api=Object.freeze({init,normalize,normalizeSets,KEY,SETS_KEY,POSITIONS,WORKSPACES,PORTABLE});
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  else root.ProducerStudioDocks=api;
})(typeof window!=="undefined"?window:globalThis);
