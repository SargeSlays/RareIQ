/* The operator and browser source share the same fail-closed identity gate. */
(() => {
  const stage=document.getElementById("stage"), grid=document.getElementById("grid");
  const state=window.RareIQMultiCard;
  let signature="";
  function clear(){signature="";stage.classList.remove("live");grid.replaceChildren();}
  function render(payload={}){
    if(payload.ok===false){clear();return;}
    const selected=new Set((payload.selected_slots||[]).map(Number));
    const cards=state.visibleSlots(payload).filter(item=>selected.has(item.slot)&&state.ready(item));
    const next=JSON.stringify(cards);
    if(signature===next)return;
    signature=next;
    const columns=cards.length<=2?cards.length||1:cards.length<=6?3:4;
    grid.style.setProperty("--columns",String(columns));
    grid.style.setProperty("--rows",String(Math.max(1,Math.ceil(cards.length/columns))));
    grid.dataset.density=cards.length>6?"dense":"standard";
    grid.replaceChildren(...cards.map(slot=>{
      const article=document.createElement("article"), copy=document.createElement("div"), number=document.createElement("div"), title=document.createElement("h2"), meta=document.createElement("p");
      const card=slot.card, reference=state.referenceImage(card);
      if(reference){
        const image=document.createElement("img");
        image.alt=`${state.name(card)} catalog reference`;
        image.onerror=()=>{image.remove();article.classList.add("no-artwork");};
        image.src=reference;article.appendChild(image);
      }else article.classList.add("no-artwork");
      number.className="slot";number.textContent=`Card ${slot.slot} · Verified`;
      title.textContent=state.name(card);
      meta.textContent=[slot.printed_code||card.printed_code||card.collector_number,card.set_name,state.confidence(slot)].filter(Boolean).join(" · ");
      copy.append(number,title,meta);article.appendChild(copy);return article;
    }));
    stage.classList.toggle("live",cards.length>0);
  }
  window.RareIQOverlay.start({load:signal=>window.RareIQOverlay.json("/api/multi-card/status",signal),render,clear});
})();
