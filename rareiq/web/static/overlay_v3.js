
const $=(id)=>document.getElementById(id);
function applyBrand(brand){
  const root=document.documentElement;
  const map={background:"--overlay-chrome",panel:"--overlay-panel-glass",border:"--overlay-border",primary:"--overlay-accent",secondary:"--overlay-success",gold:"--overlay-warning",danger:"--overlay-danger",text:"--overlay-text",muted:"--overlay-muted"};
  Object.entries(map).forEach(([k,v])=>{if(brand[k])root.style.setProperty(v,brand[k])});
  if($("creatorName"))$("creatorName").textContent=brand.creator_name||"RareIQ Creator";
}
function renderOverlay([brandResult,stateResult]){
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
      const image=document.createElement(card.reference_image_url?"img":"span");
      if(card.reference_image_url){image.src=card.reference_image_url;image.alt=""}else image.textContent="Card artwork";
      $("cardThumb").replaceChildren(image);
    }
}
RareIQOverlay.start({
  load:signal=>Promise.all([RareIQOverlay.json("/api/brand",signal),RareIQOverlay.json("/api/overlay/state",signal)]),
  render:renderOverlay,
  clear:()=>renderOverlay([{}, {state:{}}]),
});
