(() => {
  "use strict";
  const $=id=>document.getElementById(id), strip=$("chaseStrip"), cards=$("chaseCards"), model=window.RareIQSetChase;
  const preview=new URLSearchParams(location.search).get("preview")==="1";
  if(preview)document.documentElement.classList.add("chase-preview");
  let signature="", pages=[], lastPage=-1, config=null, epoch=0, serverAt=0, receivedAt=0, ticker=0;
  function clear(message="Connection lost · reconnecting to RareIQ. The preview will return automatically."){strip.hidden=true;$("chaseEmpty").textContent=message;$("chaseEmpty").hidden=!preview;signature="";pages=[];lastPage=-1;cards.replaceChildren();clearInterval(ticker);ticker=0;}
  function draw(page){
    $("chaseGroup").textContent=page.label;
    $("chaseRange").textContent=`${page.start+1}–${page.start+page.cards.length} of ${page.total}`;
    $("chasePage").textContent=`${lastPage+1} / ${pages.length}`;
    cards.style.setProperty("--chase-columns",String(page.cards.length));
    cards.replaceChildren(...page.cards.map((card,index)=>{
      const article=document.createElement("article"),art=document.createElement("div"),copy=document.createElement("div"),title=document.createElement("h2"),number=document.createElement("p");
      article.className="chase-card";article.style.setProperty("--order",String(index));art.className="chase-art";
      const missing=()=>{const span=document.createElement("span");span.className="chase-missing";span.textContent="Artwork unavailable";art.replaceChildren(span);};
      const url=model.artwork(card.image_url);
      if(url){const img=document.createElement("img");img.alt=`${card.name} · complete card`;img.onerror=missing;img.src=url;art.append(img);}else missing();
      title.textContent=card.name;number.textContent=card.collector_number||"Catalog card";copy.append(title,number);article.append(art,copy);return article;
    }));
  }
  function tick(){
    if(!pages.length)return;
    const elapsed=serverAt+(performance.now()-receivedAt)-epoch;
    const pos=model.position(pages.length,config.seconds_per_page,elapsed);
    if(pos.index!==lastPage){lastPage=pos.index;draw(pages[lastPage]);}
    $("chaseProgress").style.transform=`scaleX(${pos.progress})`;
  }
  function render(payload){
    if(!payload.visible||!payload.config){clear("Save a set and add cards to preview your chase bar.");return;}
    const next=JSON.stringify([payload.config,payload.theme,preview?0:payload.started_at_ms]);
    serverAt=payload.server_now_ms;receivedAt=performance.now();
    if(next!==signature){
      signature=next;config=payload.config;pages=model.pages(config);lastPage=-1;
      epoch=preview?serverAt:payload.started_at_ms;
      $("chaseSet").textContent=config.set_name;$("chaseLanguage").textContent=`${config.language} · ${config.set_id}`;
      for(const [key,field] of [["accent","accent"],["secondary","secondary"],["bg","background"]]){
        const color=payload.theme?.[field];if(/^#[a-f0-9]{6}$/i.test(color))strip.style.setProperty(`--chase-${key}`,color);
      }
    }
    if(!pages.length){clear("Add cards to your saved draft to preview the chase bar.");return;}
    strip.hidden=false;$("chaseEmpty").hidden=true;tick();if(!ticker)ticker=setInterval(tick,100);
  }
  window.RareIQOverlay.start({load:signal=>window.RareIQOverlay.json(`/api/creator/set-chase/status${preview?"?preview=true":""}`,signal),render,clear,interval:2000});
})();
