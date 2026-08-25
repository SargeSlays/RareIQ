
const $=(id)=>document.getElementById(id);
async function loadJson(path){return fetch(path,{cache:"no-store"}).then(r=>r.json())}
function applyBrand(brand){
  const root=document.documentElement;
  const map={background:"--bg",panel:"--panel",border:"--border",primary:"--primary",secondary:"--success",intelligence:"--intel",gold:"--gold",danger:"--danger",text:"--text",muted:"--muted"};
  Object.entries(map).forEach(([k,v])=>{if(brand[k])root.style.setProperty(v,brand[k])});
  if($("creatorName"))$("creatorName").textContent=brand.creator_name||"RareIQ Creator";
}
async function tick(){
  try{
    const [brandResult,stateResult]=await Promise.all([loadJson("/api/brand"),loadJson("/api/overlay/state")]);
    applyBrand(brandResult.brand||{});
    const state=stateResult.state||{};
    const card=state.current_card_status==="verified"?(state.current_card||{}):{};
    if($("cardName"))$("cardName").textContent=card.card_name||card.english_name||card.name||"Ready for next pull";
    if($("cardMeta"))$("cardMeta").textContent=[card.set_name,card.collector_number,card.rarity].filter(Boolean).join(" • ")||"RareIQ is watching";
    if($("cardPrice"))$("cardPrice").textContent=card.market_price?`$${Number(card.market_price).toFixed(2)}`:"WAITING";
    if($("packValue"))$("packValue").textContent=`$${Number(state.pack_total||0).toFixed(2)}`;
    if($("boxValue"))$("boxValue").textContent=`$${Number(state.box_total||0).toFixed(2)}`;
    if($("packNumber"))$("packNumber").textContent=state.pack_number||1;
    if($("cardThumb")){
      $("cardThumb").innerHTML=card.reference_image_url?`<img src="${card.reference_image_url}" alt="">`:"<span>Card artwork</span>";
    }
  }catch{}
}
tick();setInterval(tick,750);
