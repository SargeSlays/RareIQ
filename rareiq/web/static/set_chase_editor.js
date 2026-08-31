(() => {
  "use strict";
  const $=id=>document.getElementById(id), model=window.RareIQSetChase;
  if(window.self!==window.top&&new URLSearchParams(location.search).get("embed")==="creator")document.body.classList.add("creator-embedded");
  let state=null,draft=null,sets=[],results=[],dirty=false,busy=false,searchSerial=0,controller=null,rarityReady=false;
  let rarityMode="highest",selectedRarities=new Set(),rarityOptions=[],rarityInputs=[],raritySignature="";
  let pendingDiscard=null;
  let output=null,connected=null,remoteChanged=false,statusTimer=0,statusSerial=0,statusController=null,closed=false;
  const sameSet=set=>Boolean(set&&draft&&set.set_id===draft.set_id&&set.language.toLocaleLowerCase()===draft.language.toLocaleLowerCase());
  function notice(text,error=false){$("editorStatus").textContent=text;$("editorStatus").classList.toggle("error",error);}
  async function api(path,options={}){
    const response=await fetch(path,{cache:"no-store",...options,signal:options.signal||AbortSignal.timeout(15000)});
    const data=await response.json();if(!response.ok||data.ok===false){const error=new Error(data.detail||data.error||"Request failed");error.status=response.status;throw error;}return data;
  }
  function stopStatus(){statusSerial++;clearTimeout(statusTimer);statusController?.abort();statusController=null;}
  function scheduleStatus(){clearTimeout(statusTimer);if(!closed)statusTimer=setTimeout(refreshStatus,3000);}
  function acceptOutput(settings){output={visible:settings.visible,config:settings.program,revision:settings.revision};connected=true;remoteChanged=Boolean(state&&settings.revision!==state.revision);}
  function acceptSettings(){acceptOutput(state);}
  async function refreshStatus(){
    if(closed)return;
    if(busy||statusController){scheduleStatus();return;}
    const serial=++statusSerial,active=new AbortController();statusController=active;
    try{
      const data=await api("/api/creator/set-chase/status",{signal:AbortSignal.any([active.signal,AbortSignal.timeout(4000)])});
      if(serial!==statusSerial||closed)return;
      output=data;connected=true;remoteChanged=Boolean(state&&data.revision!==state.revision);controls();
    }catch{
      if(serial!==statusSerial||closed)return;
      connected=false;controls();
    }finally{if(serial===statusSerial){statusController=null;scheduleStatus();}}
  }
  function controls(){
    for(const id of ["theme","pageSize","duration","customColors","accent","secondary"])$(id).disabled=busy||!draft;
    for(const id of ["cardQuery","clearFilters"])$(id).disabled=busy||!draft;
    $("rarityFilter").disabled=busy||!draft||!rarityReady;
    $("accent").disabled=$("secondary").disabled=busy||!draft||!$("customColors").checked;
    const writeBlocked=busy||!state||connected===false||remoteChanged;
    $("save").disabled=writeBlocked||!draft;$("publish").disabled=writeBlocked||dirty||!state?.draft||!(state.draft.case_hits.length+state.draft.top_hits.length);
    $("hide").disabled=busy||connected!==true||!output?.visible;$("reload").disabled=busy;$("useSet").disabled=busy||!sets.length||$("setPicker").value===""||sameSet(sets[Number($("setPicker").value)]);$("searchCards").disabled=busy||!draft;
    const live=connected===true&&Boolean(output?.visible);
    $("airState").textContent=connected===null?"Checking output":connected===false?"CONNECTION LOST":live?"LIVE · published strip":"OFF AIR";
    $("airState").classList.toggle("live",live);$("airState").classList.toggle("unknown",connected===false);
    $("outputStatus").textContent=connected!==true?"Live output cannot be confirmed.":live?`On air: ${output.config?.set_name||"Published set"}`:"Browser source is hidden.";
    $("previewStatus").textContent=dirty?"Unsaved edits · save to update preview":"Saved draft only · not the live output";
    $("syncStatus").hidden=connected!==false&&!remoteChanged;
    $("syncStatus").textContent=connected===false?"Connection lost · retrying automatically. Your editor changes are kept; publishing is paused until the output is confirmed."
      :remoteChanged?"Saved settings changed in another window. Your editor changes are kept. Reload saved to sync before saving or publishing.":"";
  }
  function changed(){dirty=true;controls();notice("Unsaved changes · live output is unchanged.");}
  function renderSets({selectDraft=false}={}){
    const query=$("setFilter").value.toLocaleLowerCase(), select=$("setPicker"),previous=select.value;
    select.replaceChildren();const placeholder=document.createElement("option");placeholder.value="";placeholder.textContent="Choose a set and language";select.append(placeholder);
    sets.forEach((set,index)=>{if(!`${set.set_name} ${set.set_id} ${set.language}`.toLocaleLowerCase().includes(query))return;
      const option=document.createElement("option");option.value=String(index);option.textContent=`${set.set_name} · ${set.set_id} · ${set.language}`;select.append(option);});
    const desired=selectDraft&&draft?String(sets.findIndex(sameSet)):previous;
    if(Array.from(select.options).some(o=>o.value===desired))select.value=desired;select.disabled=false;controls();
  }
  function renderDraft(){
    $("selectedSet").textContent=draft?`${draft.set_name} · ${draft.set_id} · ${draft.language}`:"No set selected";
    $("theme").value=draft?.theme||"auto";$("pageSize").value=String(draft?.cards_per_page||4);$("duration").value=String(draft?.seconds_per_page||8);
    $("customColors").checked=Boolean(draft?.accent||draft?.secondary);$("accent").value=draft?.accent||"#8be8ca";$("secondary").value=draft?.secondary||"#c6e98a";
    renderRotation();controls();
  }
  function image(card){
    const art=document.createElement("div");art.className="card-art";
    const missing=()=>{const text=document.createElement("span");text.textContent="Artwork unavailable";art.setAttribute("aria-label",`${card.name}: artwork unavailable`);art.replaceChildren(text);};
    const url=model.artwork(card.image_url);
    if(url){const img=document.createElement("img");img.alt=card.name;img.onerror=missing;img.src=url;art.append(img);}else missing();
    return art;
  }
  function placeCard(card,target){
    if(busy||!draft)return;
    const source=["case_hits","top_hits"].find(group=>draft[group].some(row=>row.id===card.id));
    if(source===target)return;
    if(draft[target].length>=32){notice("That group already has 32 cards. Remove one before adding or moving another.",true);return;}
    const row=source?draft[source].splice(draft[source].findIndex(row=>row.id===card.id),1)[0]:{...card};
    draft[target].push(row);changed();renderRotation();renderResults();
  }
  function renderRotation(){
    for(const [group,id] of [["case_hits","caseHits"],["top_hits","topHits"]]){
      const list=$(id),rows=draft?.[group]||[];list.replaceChildren();
      if(!rows.length){const p=document.createElement("p");p.className="empty";p.textContent="Add cards from the catalog above.";list.append(p);}
      rows.forEach((card,index)=>{const li=document.createElement("li"),name=document.createElement("div"),number=document.createElement("small");
        name.className="card-name";name.textContent=card.name;number.textContent=card.collector_number;name.append(number);li.append(image(card),name);
        const destination=group==="case_hits"?"top_hits":"case_hits",destinationLabel=destination==="top_hits"?"Top hits":"Case hits";
        const move=document.createElement("button");move.type="button";move.className="move-group";move.textContent=`To ${destinationLabel.toLowerCase()}`;move.setAttribute("aria-label",`Move ${card.name} to ${destinationLabel}`);move.disabled=draft[destination].length>=32;move.onclick=()=>placeCard(card,destination);li.append(move);
        for(const [label,delta] of [["Move up",-1],["Move down",1],["Remove",0]]){const button=document.createElement("button");button.type="button";button.textContent=delta<0?"↑":delta>0?"↓":"×";button.setAttribute("aria-label",`${label} ${card.name}`);button.disabled=delta!==0&&(index+delta<0||index+delta>=rows.length);
          button.onclick=()=>{if(busy)return;if(delta){[rows[index],rows[index+delta]]=[rows[index+delta],rows[index]];}else rows.splice(index,1);changed();renderRotation();renderResults();};li.append(button);}
        list.append(li);});
    }
    $("rotationCount").textContent=`${(draft?.case_hits.length||0)+(draft?.top_hits.length||0)} cards · case hits → top hits`;
  }
  function renderResults(){
    const root=$("catalogResults");root.replaceChildren();const selected=new Map();
    for(const group of ["case_hits","top_hits"])for(const card of draft?.[group]||[])selected.set(card.id,group);
    for(const card of results){const article=document.createElement("article"),copy=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("small"),actions=document.createElement("div");
      article.className="catalog-card";name.textContent=card.name;meta.textContent=card.collector_number||"Catalog card";actions.className="pick-actions";
      const rarity=document.createElement("span");rarity.className="rarity-badge";rarity.textContent=card.rarity||"Unlisted";rarity.title="Catalog rarity";meta.append(rarity);
      for(const [group,label] of [["case_hits","Case hit"],["top_hits","Top hit"]]){const button=document.createElement("button");button.type="button";button.textContent=selected.get(card.id)===group?`In ${label.toLowerCase()}s`:selected.has(card.id)?`Move to ${label.toLowerCase()}s`:`+ ${label}`;button.disabled=selected.get(card.id)===group||!draft||draft[group].length>=32;
        button.onclick=()=>placeCard(card,group);actions.append(button);}
      copy.append(name,meta,actions);article.append(image(card),copy);root.append(article);}
  }
  function resetSearch(){
    searchSerial++;
    controller?.abort();
    results=[];
    rarityReady=false;
    rarityMode="highest";
    selectedRarities.clear();
    rarityOptions=[];rarityInputs=[];raritySignature="";
    $("cardQuery").value="";
    $("rarityOptions").replaceChildren();
    $("raritySummary").textContent="Choose a set to see rarity levels.";
    $("catalogResults").setAttribute("aria-busy","false");
    renderResults();
  }
  function updateRaritySelection(){
    for(const input of rarityInputs)input.checked=rarityMode==="all"||selectedRarities.has(input.value);
    $("allRarities").setAttribute("aria-pressed",String(rarityMode==="all"));
    $("raritySummary").textContent=rarityMode==="all"?"All levels · highest first"
      :rarityMode==="highest"&&selectedRarities.size?"Highest tier selected · highest first"
      :`${selectedRarities.size} selected · highest rarity first`;
  }
  function renderRarities(options){
    rarityOptions=options;
    const signature=JSON.stringify(options);
    // Preserve checkbox focus across searches when the set's facets are unchanged.
    if(signature!==raritySignature){
      raritySignature=signature;rarityInputs=[];$("rarityOptions").replaceChildren();
      for(const option of options){
        const label=document.createElement("label"),input=document.createElement("input"),name=document.createElement("span"),count=document.createElement("small");
        label.className="rarity-chip";input.type="checkbox";input.value=option.value;
        name.textContent=option.value||"Unlisted";count.textContent=String(option.count);
        input.setAttribute("aria-label",`${option.value||"Unlisted"} rarity (${option.count} ${option.count===1?"card":"cards"})`);
        input.onchange=()=>{
          if(busy){updateRaritySelection();return;}
          rarityMode="selected";
          selectedRarities=new Set(rarityInputs.filter(item=>item.checked).map(item=>item.value));
          updateRaritySelection();search();
        };
        label.append(input,name,count);$("rarityOptions").append(label);rarityInputs.push(input);
      }
    }
    rarityReady=true;
    updateRaritySelection();
    controls();
  }
  function emptyResults(message){
    const empty=document.createElement("p");
    empty.className="catalog-empty";
    empty.textContent=message;
    $("catalogResults").replaceChildren(empty);
  }
  async function search(){
    if(!draft||busy)return;
    const serial=++searchSerial;
    controller?.abort();
    if(rarityMode==="selected"&&!selectedRarities.size){
      results=[];
      $("catalogResults").setAttribute("aria-busy","false");
      $("searchStatus").textContent="No rarity levels selected.";
      emptyResults("Select at least one rarity above to show its cards. All rarities is always your choice.");
      return;
    }
    controller=new AbortController();
    const active=controller,timeout=setTimeout(()=>active.abort(),15000);
    const params=new URLSearchParams({set_id:draft.set_id,language:draft.language,q:$("cardQuery").value.trim()});
    if(rarityMode==="highest")params.set("highest","true");
    else if(rarityMode==="selected")for(const rarity of selectedRarities)params.append("rarity",rarity);
    results=[];
    renderResults();
    $("catalogResults").setAttribute("aria-busy","true");
    $("searchStatus").textContent="Searching this set…";
    try{
      const data=await api(`/api/creator/set-chase/cards?${params}`,{signal:active.signal});
      if(serial!==searchSerial)return;
      results=data.results;
      if(rarityMode==="highest")selectedRarities=new Set(data.selected_rarities||[]);
      renderRarities(data.rarities);
      renderResults();
      const count=results.length,total=data.total;
      $("searchStatus").textContent=count<total
        ?`Showing ${count} of ${total} matches · narrow by name or rarity`
        :`${total} matching ${total===1?"card":"cards"} · ${data.set_total} in this set`;
      if(!count)emptyResults("No cards match these filters. Reset filters or try another name or rarity.");
    }catch(error){
      if(serial!==searchSerial)return;
      $("searchStatus").textContent=error.name==="AbortError"?"Search timed out or was canceled. Try again.":error.message;
      emptyResults("Catalog search is unavailable. Your rotation is unchanged.");
    }finally{
      clearTimeout(timeout);
      if(serial===searchSerial)$("catalogResults").setAttribute("aria-busy","false");
    }
  }
  async function load(){
    stopStatus();busy=true;resetSearch();controls();
    try{
      state=await api("/api/creator/set-chase");
      acceptSettings();
      draft=state.draft?structuredClone(state.draft):null;
      dirty=false;$("setFilter").value="";renderSets({selectDraft:true});renderDraft();
      $("searchStatus").textContent=draft?"Loading catalog rarities…":"Choose a set to browse its catalog cards.";
      notice("Saved draft loaded · publishing is always explicit.");
    }catch(error){state=null;connected=false;notice(error.message,true);}
    finally{busy=false;controls();scheduleStatus();}
    if(state&&draft)search();
  }
  async function change(action){
    if(busy||!state||connected===false||(remoteChanged&&action!=="hide"))return;
    if(action==="take"&&(dirty||!state.draft||!(state.draft.case_hits.length+state.draft.top_hits.length)))return;
    if(action==="draft"){
      const duration=Number($("duration").value);if(!Number.isInteger(duration)||duration<4||duration>30){notice("Choose a whole-number duration from 4–30 seconds.",true);return;}
      Object.assign(draft,{theme:$("theme").value,cards_per_page:Number($("pageSize").value),seconds_per_page:duration,accent:$("customColors").checked?$("accent").value:"",secondary:$("customColors").checked?$("secondary").value:""});
    }
    const keepLocalBase=action==="hide"&&remoteChanged,revision=action==="hide"?output.revision:state.revision;
    stopStatus();busy=true;controls();notice(action==="draft"?"Saving draft…":action==="take"?"Publishing saved draft…":"Hiding live strip…");
    try{const updated=await api(`/api/creator/set-chase/${action}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision,...(action==="draft"?{config:draft}:{})})});
      if(keepLocalBase)acceptOutput(updated);else{state=updated;acceptSettings();}
      if(action==="draft"){dirty=false;draft=structuredClone(state.draft);renderDraft();}
      notice(action==="take"?"Published · browser sources now show the saved set.":action==="hide"?"Live strip hidden. Your editor changes are kept.":"Draft saved · preview updated. Live output is unchanged.");
    }catch(error){if(error.status===409)remoteChanged=true;else if(!error.status)connected=false;notice(error.message,true);}finally{busy=false;controls();scheduleStatus();}
  }
  $("setFilter").addEventListener("input",renderSets);
  $("setPicker").addEventListener("change",controls);
  function confirmDiscard(action,message){
    pendingDiscard=action;$("discardMessage").textContent=message;$("discardDialog").showModal();$("keepEditing").focus();
  }
  $("keepEditing").onclick=()=>{pendingDiscard=null;$("discardDialog").close();renderSets({selectDraft:true});};
  $("discardDialog").addEventListener("cancel",()=>{pendingDiscard=null;renderSets({selectDraft:true});});
  $("discardChanges").onclick=()=>{const action=pendingDiscard;pendingDiscard=null;$("discardDialog").close();action?.();};
  $("useSet").onclick=()=>{
    if(busy||$("setPicker").value==="")return;
    const set=sets[Number($("setPicker").value)];if(!set||sameSet(set))return;
    const use=()=>{
      draft={set_id:set.set_id,set_name:set.set_name,language:set.language,theme:"auto",accent:"",secondary:"",cards_per_page:4,seconds_per_page:8,case_hits:[],top_hits:[]};
      resetSearch();renderDraft();changed();search();
    };
    if(draft&&(dirty||draft.case_hits.length||draft.top_hits.length))confirmDiscard(use,`Switch to ${set.set_name}? This clears the editor’s current card list and unsaved changes. The saved draft and live strip stay unchanged until you save or publish.`);
    else use();
  };
  $("searchForm").onsubmit=event=>{event.preventDefault();search();};
  $("allRarities").onclick=()=>{if(busy||!draft||!rarityReady)return;rarityMode="all";updateRaritySelection();search();};
  $("clearRarities").onclick=()=>{if(busy||!draft||!rarityReady)return;rarityMode="selected";selectedRarities.clear();updateRaritySelection();search();};
  $("clearFilters").onclick=()=>{
    if(busy||!draft)return;
    $("cardQuery").value="";rarityMode="highest";
    selectedRarities=new Set(rarityOptions.length?[rarityOptions[0].value]:[]);
    updateRaritySelection();search();
  };
  for(const id of ["theme","pageSize","duration","customColors","accent","secondary"])$(id).addEventListener("input",()=>{if(!busy&&draft)changed();});
  $("save").onclick=()=>change("draft");$("publish").onclick=()=>change("take");$("hide").onclick=()=>change("hide");
  $("reload").onclick=()=>{if(busy)return;if(dirty)confirmDiscard(load,"Reload the saved draft and discard your unsaved changes? Your live strip will not change.");else load();};
  const source=`${location.origin}/overlay/set-chase`;$("sourceUrl").textContent=source;
  $("copySource").onclick=async()=>{try{await navigator.clipboard.writeText(source);notice("Browser-source URL copied.");}catch{notice("Clipboard unavailable. Select and copy the URL shown above.",true);}};
  load();api("/api/creator/set-chase/sets").then(data=>{const unique=new Map();for(const set of data.sets||[]){if(set.set_id&&set.set_name&&set.language)unique.set(`${set.set_id}|${set.language}`,set);}sets=[...unique.values()];renderSets({selectDraft:true});controls();if(!sets.length)notice("No searchable catalog sets yet. Import a set through Library, then refresh this page.");}).catch(error=>{$("setPicker").replaceChildren(new Option("Catalog unavailable · refresh page to retry",""));notice(error.message,true);});
  window.addEventListener("beforeunload",event=>{if(dirty){event.preventDefault();event.returnValue="";}});
  window.addEventListener("pagehide",()=>{closed=true;stopStatus();searchSerial++;controller?.abort();});
  window.addEventListener("pageshow",event=>{if(event.persisted){closed=false;scheduleStatus();}});
})();
