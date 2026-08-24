
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g,character=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]);
let selectedCamera = null;
let cameraStreamStarted = false;
let previousCardId = null;
let autoCaptureEnabled = true;
let captureBannerTimer = null;
let newestRecognitionGeneration = -1;
let newestRecognitionRevision = -1;
let currentServerSessionId = null;
const MOBILE_OPERATOR_VIEW_KEY="rareiq.mobileOperatorView";
const BROADCAST_WORKSPACE_VIEW_KEY="rareiq.broadcastWorkspaceView";
let studioXExactMatchMomentKey = null;
let studioXExactMatchMomentTimer = null;
let recognitionPresentationMemory={key:"ready",presentation:null,changedAt:0};
const RECOGNITION_LATENCY_SESSION_KEY="rareiq.recognitionLatency.session.v1";
let recognitionLatencySamples=loadRecognitionLatencySamples();
let lastRecognitionLatencySampleKey="";
let activityItems = [];
let cameraFitMode = "adaptive";
let cardZoomEnabled = false;
const STUDIOX_PREFERENCES_KEY="rareiq.studiox.workspacePreferences.v1";
const STUDIOX_SECONDARY_BAY_KEY="rareiq.studiox.secondaryBayPreferences.v1";
const CAMERA_WORKSPACE_KEY="rareiq.studiox.cameraWorkspace.v1";
const STUDIOX_THEME_KEY="rareiq.studiox.theme.v1";
const CAMERA_WORKSPACE_LAYOUTS=["single","dual-side","triple","quad"];
const CAMERA_RECOVER_ENDPOINT="/api/camera/recover";
let studioXPreferences={
  version:1,
  layoutPreset:"intelligence",
  viewerMode:"auto",
  previewZoom:1,
  inspectorWidth:null,
};
let sessionStartedAt = Date.now();
let sessionCards = 0;
let sessionHits = 0;
let sessionValue = 0;
let sessionMatches = 0;
let sessionAttempts = 0;
let cameraBootstrapRunning = false;
let cameraStreamRetryTimer = null;
let cameraStreamFailures = 0;
let cameraDiscoveryTimer = null;
let cameraStatusPollTimer = null;
let cameraAutostartComplete = false;
let cameraStartInFlight = false;
let cameraConnectionAvailable = null;
let cameraConnectionFailure = null;
let viewerBridgeTimer = null;
let viewerBridgeConnected = false;
let viewerBridgeGeneration = 0;
let bootAutoEnterTimer = null;
let studioEntered = false;
let ui4DiagnosticsOpen = false;
let ui4HealthOpen = false;
let ui4InspectorTab = "details";
let ui4InspectorView = "current";
let ui4RecentScans = [];
let cardPlaceholderResetTimer = null;
let secondaryFocusGeometry = null;
let lastValidCardFocusGeometry = null;
let lastValidCardFocusAt = 0;
let lastCardFocusGeometryReason = "unavailable";
const CARD_FOCUS_LAST_VALID_MS = 1800;
let secondaryBayPreferences={
  version:1,
  mode:"camera-2",
  visible:true,
  size:"standard",
  activeSource:null,
  stagingSource:null,
  manualPinned:false,
};
let cameraWorkspacePreferences={
  version:1,
  layout:"single",
  activeSlot:1,
  sources:{"1":null,"2":null,"3":null,"4":null},
  sides:{"1":"unassigned","2":"unassigned","3":"unassigned","4":"unassigned"},
};
let cameraWorkspaceSlotStates={};
let collectionInventory=[];
let collectionImportBackup=null;
let inventoryCheckoutItem=null,inventorySellRecommendation=null;
const selectedInventoryListingIds=new Set();
const INVENTORY_FEE_PRESET_KEY="rareiq.inventory.feePresets.v1",INVENTORY_DEFAULT_FEE_PRESETS={in_person:0,ebay:13.25,tcgplayer:10.25,whatnot:8,shopify:2.9,other:0};
const INVENTORY_FULFILLMENT_PRESET_KEY="rareiq.inventory.fulfillmentPresets.v1",INVENTORY_DEFAULT_FULFILLMENT_PRESETS={in_person:{shipping:0,packaging:0},ebay:{shipping:4.75,packaging:.65},tcgplayer:{shipping:1.25,packaging:.45},whatnot:{shipping:0,packaging:.65},shopify:{shipping:4.75,packaging:.65},other:{shipping:0,packaging:0}};
function inventoryFeePresets(){try{return {...INVENTORY_DEFAULT_FEE_PRESETS,...JSON.parse(localStorage.getItem(INVENTORY_FEE_PRESET_KEY)||"{}")}}catch(_error){return {...INVENTORY_DEFAULT_FEE_PRESETS}}}
function inventoryFulfillmentPresets(){try{return {...INVENTORY_DEFAULT_FULFILLMENT_PRESETS,...JSON.parse(localStorage.getItem(INVENTORY_FULFILLMENT_PRESET_KEY)||"{}")}}catch(_error){return {...INVENTORY_DEFAULT_FULFILLMENT_PRESETS}}}
function applyInventoryChannelPreset(){const channel=$("inventorySaleChannel")?.value||"other",rate=Number(inventoryFeePresets()[channel]??0),fulfillment=inventoryFulfillmentPresets()[channel]||{};if($("inventoryFeePercent"))$("inventoryFeePercent").value=String(rate);if($("inventoryShippingCost"))$("inventoryShippingCost").value=String(Number(fulfillment.shipping||0));if($("inventoryPackagingCost"))$("inventoryPackagingCost").value=String(Number(fulfillment.packaging||0));setCardText("inventoryFeePresetNote",`${channel.replaceAll("_"," ")} estimate · ${rate.toFixed(2)}% fees · ${portfolioMoney(fulfillment.shipping||0)} postage · ${portfolioMoney(fulfillment.packaging||0)} supplies`);return updateInventorySellRecommendation()}
function saveInventoryChannelPreset(){const channel=$("inventorySaleChannel")?.value||"other",rate=Math.min(95,Math.max(0,Number($("inventoryFeePercent")?.value||0))),presets=inventoryFeePresets();presets[channel]=rate;localStorage.setItem(INVENTORY_FEE_PRESET_KEY,JSON.stringify(presets));setCardText("inventoryFeePresetNote",`${channel.replaceAll("_"," ")} custom rate saved · ${rate.toFixed(2)}%`);return updateInventorySellRecommendation()}
function saveInventoryFulfillmentPreset(){const channel=$("inventorySaleChannel")?.value||"other",presets=inventoryFulfillmentPresets(),shipping=Math.max(0,Number($("inventoryShippingCost")?.value||0)),packaging=Math.max(0,Number($("inventoryPackagingCost")?.value||0));presets[channel]={shipping,packaging};localStorage.setItem(INVENTORY_FULFILLMENT_PRESET_KEY,JSON.stringify(presets));setCardText("inventoryFeePresetNote",`${channel.replaceAll("_"," ")} fulfillment saved · ${portfolioMoney(shipping)} postage · ${portfolioMoney(packaging)} supplies`);return updateInventorySellRecommendation()}
let inventoryScannerStream=null,inventoryScannerTimer=null,inventoryScannerBusy=false,inventoryScannerLastCode="",inventoryScannerLastAt=0;
const VOICE_MOD_PREFERENCES_KEY="rareiq.voiceMod.preferences.v1";
const CAMERA_FX_PREFERENCES_KEY="rareiq.cameraFx.preferences.v1";
const VOICE_MOD_PRESETS={clean:"Clean Studio",deep:"Deep Broadcast",robot:"Robot",radio:"Radio",megaphone:"Megaphone"};
let voiceModState={context:null,inputStream:null,source:null,inputGain:null,dryGain:null,wetGain:null,outputGain:null,monitorGain:null,destination:null,analyser:null,nodes:[],oscillators:[],meterFrame:0,active:false};
let cameraFxState={enabled:false,frame:0,lastFrame:0};

const studioThemeMedia=window.matchMedia("(prefers-color-scheme: light)");
function studioThemePreference(){try{return localStorage.getItem(STUDIOX_THEME_KEY)||"system"}catch(_error){return "system"}}
function applyStudioTheme(preference=studioThemePreference(),persist=false){
  const choice=["dark","light","system"].includes(preference)?preference:"system";
  const resolved=choice==="system"?(studioThemeMedia.matches?"light":"dark"):choice;
  document.documentElement.dataset.theme=resolved;document.documentElement.dataset.themePreference=choice;
  document.querySelectorAll("[data-theme-choice]").forEach(button=>{const active=button.dataset.themeChoice===choice;button.classList.toggle("active",active);button.setAttribute("aria-checked",String(active));});
  const toggle=$("studioThemeToggle"),label=$("studioThemeToggleLabel"),next=resolved==="dark"?"light":"dark";
  if(toggle){toggle.dataset.theme=resolved;toggle.setAttribute("aria-pressed",String(resolved==="light"));toggle.setAttribute("aria-label",`Switch to ${next} mode`);toggle.title=`Switch to ${next} mode`;}
  if(label)label.textContent=next[0].toUpperCase()+next.slice(1);
  if(persist){try{localStorage.setItem(STUDIOX_THEME_KEY,choice)}catch(_error){}notify("Appearance Updated",choice==="system"?`Following system · ${resolved}`:`${choice[0].toUpperCase()}${choice.slice(1)} mode enabled`,"success");}
}
studioThemeMedia.addEventListener?.("change",()=>{if(studioThemePreference()==="system")applyStudioTheme("system")});





function notify(title,detail="",type="info"){
  const stack=$("notificationStack");
  if(!stack) return;

  const node=document.createElement("div");
  node.className=`riq-notification ${type}`;
  node.innerHTML=`
    <div class="notification-icon" aria-hidden="true">${type==="error"?"!":""}</div>
    <div class="notification-copy">
      <strong>${title}</strong>
      <span>${detail}</span>
    </div>
  `;
  stack.appendChild(node);

  setTimeout(()=>{
    node.style.opacity="0";
    node.style.transform="translateX(18px)";
    node.style.transition=".22s ease";
  },2800);
  setTimeout(()=>node.remove(),3100);
}

function updateAiPulse(state,label){
  const pulse=$("aiPulse");
  const text=$("aiPulseLabel");
  if(!pulse||!text) return;
  pulse.classList.remove("working","matched","error");

  if(state==="searching") pulse.classList.add("working");
  if(state==="matched"||state==="captured") pulse.classList.add("matched");
  if(state==="error") pulse.classList.add("error");

  text.textContent=label||(
    state==="searching"?"AI THINKING":
    state==="matched"?"MATCH FOUND":
    state==="captured"?"CAPTURED":
    state==="error"?"AI ERROR":
    "AI IDLE"
  );
}

function setCopilot(status,message){
  const badge=$("copilotBadge");
  const body=$("copilotBody");
  if(badge) badge.textContent=status;
  if(body) body.innerHTML=message;
}

function money(value){
  const amount = Number(value || 0);

  return new Intl.NumberFormat(
    "en-US",
    {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }
  ).format(
    Number.isFinite(amount)
      ? amount
      : 0
  );
}

function updateSessionStats(){
  const elapsed=Math.max(0,Math.floor((Date.now()-sessionStartedAt)/1000));
  const minutes=Math.floor(elapsed/60);
  const seconds=elapsed%60;
  const accuracy=sessionAttempts?`${Math.round(sessionMatches/sessionAttempts*100)}%`:"--";

  if($("sessionCards")) $("sessionCards").textContent=String(sessionCards);
  if($("sessionHits")) $("sessionHits").textContent=String(sessionHits);
  if($("sessionValue")) $("sessionValue").textContent=money(sessionValue);
  if($("sessionAccuracy")) $("sessionAccuracy").textContent=accuracy;
  if($("sessionElapsed")) $("sessionElapsed").textContent=
    `${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}`;
  if($("emptySessionCards")) $("emptySessionCards").textContent=`${sessionCards} cards`;
}

function updateConfidenceRing(value){
  const normalized=Math.max(0,Math.min(1,Number(value||0)));
  const percent=Math.round(normalized*100);
  const ring=$("confidenceRing");
  if(ring) ring.style.setProperty("--confidence",String(percent));
  if($("confidenceRingValue")) $("confidenceRingValue").textContent=`${percent}%`;
}

function toggleShortcutOverlay(force){
  const overlay=$("shortcutOverlay");
  if(!overlay) return;
  const visible=typeof force==="boolean"?force:!overlay.classList.contains("visible");
  overlay.classList.toggle("visible",visible);
}

function shortcutBackdropClose(event){
  if(event.target===$("shortcutOverlay")) toggleShortcutOverlay(false);
}

function applyAuthoritativeSession(session={}){
  if(!session||typeof session!=="object") return;
  sessionCards=Math.max(0,Number(session.card_count||0));
  sessionHits=Math.max(0,Number(session.hit_count||0));
  sessionValue=Math.max(0,Number(session.total_value||0));
  if($("sessionPacks")) $("sessionPacks").textContent=String(
    Math.max(1,Number(session.active_pack_number||1))
  );
  if($("sessionBoxes")) $("sessionBoxes").textContent=String(
    Math.max(1,Number(session.active_box_number||1))
  );
  updateSessionStats();
}

let recognitionDecisionInFlight=false;
let lastApprovedInventoryCard=null;
let activeInventoryAllocationGroup="";
const APPROVED_INVENTORY_KEY="rareiq.inventory.approvedIntake.v1";
function approvedInventoryPrefs(){try{return {...{auto:false,costMode:"fixed",cost:0,cardsPerPack:6,condition:"raw",location:"",openLabel:true},...JSON.parse(localStorage.getItem(APPROVED_INVENTORY_KEY)||"{}")}}catch{return {auto:false,costMode:"fixed",cost:0,cardsPerPack:6,condition:"raw",location:"",openLabel:true}}}
function saveApprovedInventoryPrefs(){const prefs={auto:Boolean($("approvedInventoryAuto")?.checked),costMode:$("approvedInventoryCostMode")?.value||"fixed",cost:Math.max(0,Number($("approvedInventoryCost")?.value||0)),cardsPerPack:Math.max(1,Number($("approvedInventoryCardsPerPack")?.value||6)),condition:$("approvedInventoryCondition")?.value||"raw",location:$("approvedInventoryLocation")?.value||"",openLabel:Boolean($("approvedInventoryLabel")?.checked)};localStorage.setItem(APPROVED_INVENTORY_KEY,JSON.stringify(prefs));renderApprovedInventoryPrefs();refreshApprovedInventoryCostPreview().catch(()=>{});return prefs}
function renderApprovedInventoryPrefs(){const prefs=approvedInventoryPrefs();if($("approvedInventoryAuto"))$("approvedInventoryAuto").checked=prefs.auto;if($("approvedInventoryCostMode"))$("approvedInventoryCostMode").value=prefs.costMode;if($("approvedInventoryCost"))$("approvedInventoryCost").value=String(prefs.cost);if($("approvedInventoryCardsPerPack"))$("approvedInventoryCardsPerPack").value=String(prefs.cardsPerPack);if($("approvedInventoryCondition"))$("approvedInventoryCondition").value=prefs.condition;if($("approvedInventoryLocation"))$("approvedInventoryLocation").value=prefs.location;if($("approvedInventoryLabel"))$("approvedInventoryLabel").checked=prefs.openLabel;if($("approvedInventoryState"))$("approvedInventoryState").textContent=prefs.auto?"Automatic after approval":"Manual intake";if($("approvedInventoryAdd"))$("approvedInventoryAdd").disabled=!lastApprovedInventoryCard;if($("approvedInventoryFixedCost"))$("approvedInventoryFixedCost").hidden=prefs.costMode!=="fixed";if($("approvedInventoryPackCards"))$("approvedInventoryPackCards").hidden=prefs.costMode!=="pack_share"}
function approvedInventoryRarityWeight(card={}){return {"Special":8,"Illustration Rare":6,"Double Rare":4,"Rare":2,"Standard":1}[rarityEventTier(card)]||1}
async function approvedInventoryAllocation(card={}){const prefs=approvedInventoryPrefs();if(prefs.costMode==="fixed")return {cost:prefs.cost,currency:"USD",description:`Fixed ${portfolioMoney(prefs.cost,"USD")} per card`};const payload=await api("/api/production/session/pack-economics"),economics=payload.economics||{},settings=economics.settings||{},packCost=Number(economics.effective_pack_cost||0),currency=settings.currency||"USD";if(prefs.costMode==="rarity_weighted"){const weight=approvedInventoryRarityWeight(card);return {cost:0,currency,weighted:true,totalPackCost:packCost,weight,description:`${portfolioMoney(packCost,currency)} rarity-weighted pack ledger · ${weight}× weight`}}const cards=Math.max(1,Number(prefs.cardsPerPack||6));return {cost:Math.round(packCost/cards*100)/100,currency,description:`${portfolioMoney(packCost,currency)} pack ÷ ${cards} cards`}}
async function refreshApprovedInventoryCostPreview(){const allocation=await approvedInventoryAllocation(lastApprovedInventoryCard||{});if($("approvedInventoryCostPreview"))$("approvedInventoryCostPreview").textContent=allocation.weighted?`${allocation.description}. Every approved card in this pack is rebalanced automatically.`:`${allocation.description} = ${portfolioMoney(allocation.cost,allocation.currency)} cost basis per approved card.`;return allocation}
async function lockInventoryAllocation(group){if(!group)return null;const result=await api("/api/inventory/allocations/lock",{method:"POST",body:JSON.stringify({group})});if(result.locked&&activeInventoryAllocationGroup===group)activeInventoryAllocationGroup="";return result}
async function createApprovedInventory(card=lastApprovedInventoryCard){if(!card)throw new Error("Approve an exact card first.");if(!(card.set_id||card.set_code||card.set_name)||!(card.collector_number||card.card_number))throw new Error("Exact set and collector number are required for inventory.");const prefs=approvedInventoryPrefs(),allocation=await approvedInventoryAllocation(card),inventoryCard={...card,currency:allocation.currency},payload={card:inventoryCard,cost_basis:allocation.cost,asking_price:null,condition:prefs.condition,location:prefs.location,notes:`Created from approved RareIQ scan · ${allocation.description}`,allocation_group:allocation.weighted?card._inventoryAllocationGroup||"":"",allocation_weight:allocation.weight||1};const result=await api("/api/inventory/items",{method:"POST",body:JSON.stringify(payload)});let item=result.item;if(!item?.item_id)throw new Error(result.reason||"Inventory item was not returned.");if(allocation.weighted){const balanced=await api("/api/inventory/allocations/rebalance",{method:"POST",body:JSON.stringify({group:payload.allocation_group,total_cost:allocation.totalPackCost,currency:allocation.currency})});item=(balanced.items||[]).find(candidate=>candidate.item_id===item.item_id)||item;if(card._inventoryAllocationComplete)await lockInventoryAllocation(payload.allocation_group)}lastApprovedInventoryCard=null;renderApprovedInventoryPrefs();notify(card._inventoryAllocationComplete?"Pack Ledger Locked":"Inventory Item Created",`${item.english_name||item.card_name} · ${item.item_id} · cost ${portfolioMoney(item.cost_basis,item.currency)}`,"success");if(prefs.openLabel)window.open(item.label_url,"_blank");loadInventory().catch(()=>{});return item}
async function handleApprovedInventory(result){if(!result?.card||result.duplicate_suppressed)return;const reveal=result.reveal_sequence||{},packNumber=Math.max(1,Number(reveal.pack_number||$("sessionPacks")?.textContent||1)),sessionKey=String(result.session?.session_id||currentServerSessionId||"active-session"),group=`${sessionKey}:pack-${packNumber}`;activeInventoryAllocationGroup=group;lastApprovedInventoryCard={...result.card,_inventoryAllocationGroup:group,_inventoryAllocationComplete:Number(reveal.position||0)>=Number(reveal.expected_cards||Infinity)};renderApprovedInventoryPrefs();refreshApprovedInventoryCostPreview().catch(()=>{});if(approvedInventoryPrefs().auto)await createApprovedInventory(lastApprovedInventoryCard)}
const AUTO_ADD_VERIFIED_KEY="rareiq.autoAddVerified.v1";
const PACK_SPEED_RUN_KEY="rareiq.packSpeedRun.v1";
const PACK_SPEED_HISTORY_KEY="rareiq.packSpeedHistory.v1";
const PACK_AUTO_FINISH_KEY="rareiq.packAutoFinish.v1";
const PACK_REARM_KEY="rareiq.packRearm.v1";
const PACK_RECAP_STYLE_KEY="rareiq.packRecapStyle.v1";
const PACK_AUTO_RECAP_KEY="rareiq.packAutoRecap.v1";
const PACK_RECOVERY_METRICS_KEY="rareiq.packRecoveryMetrics.v1";
const PACK_TUNING_OUTCOME_KEY="rareiq.packTuningOutcome.v1";
const PACK_TUNING_HISTORY_KEY="rareiq.packTuningHistory.v1";
const PACK_BEST_TUNING_KEY="rareiq.packBestTuning.v1";
const PACK_TUNING_REVALIDATION_KEY="rareiq.packTuningRevalidation.v1";
let lastAutoAddStateId=null;
let packSpeedRun=loadPackSpeedRun();
let packRearmGate=loadPackRearmGate();
let packRecapTimer=0,packRecapCountdownTimer=0,packRecapDueAt=0,packRecapLiveTimer=0,packRecapLiveDueAt=0;
const PACK_STALL_RECOVERY_MS=2500;
let packRecoveryState={generation:null,startedAt:0,attempted:false,attemptedAt:0,recorded:false,status:"idle"};

function loadPackRecoveryMetrics(){try{const value=JSON.parse(localStorage.getItem(PACK_RECOVERY_METRICS_KEY)||"[]");return Array.isArray(value)?value.slice(-50):[]}catch{return[]}}
function recordPackRecoveryMetric(outcome,generation,elapsedMs,context={}){const rows=loadPackRecoveryMetrics(),elapsed=Math.max(0,Math.round(Number(elapsedMs)||0)),card=context?.card||context?.snapshot?.primary_candidate||{};rows.push({outcome:String(outcome||"unknown"),generation:Number(generation)||0,elapsed_ms:elapsed,card_name:card.english_name||card.name||card.printed_name||"Unverified card",collector_number:card.collector_number||card.card_number||"",set_name:card.set_name||"",reference_image_url:card.reference_image_url||card.image_url||"",at:new Date().toISOString()});try{localStorage.setItem(PACK_RECOVERY_METRICS_KEY,JSON.stringify(rows.slice(-50)))}catch{}renderPackRecoveryMetrics();renderPackRecoveryHistory();return rows.at(-1)}
function packRecoveryMetricSummary(){const rows=loadPackRecoveryMetrics(),recovered=rows.filter(row=>row.outcome==="recovered"),failed=rows.filter(row=>row.outcome==="failed"),average=recovered.length?Math.round(recovered.reduce((sum,row)=>sum+Number(row.elapsed_ms||0),0)/recovered.length):null;return{attempts:rows.length,recovered:recovered.length,failed:failed.length,successRate:rows.length?Math.round(recovered.length/rows.length*100):null,averageMs:average}}
function packRecoveryThresholdMs(){const summary=packRecoveryMetricSummary();if(summary.attempts<4)return PACK_STALL_RECOVERY_MS;if(summary.successRate>=75&&Number.isFinite(summary.averageMs))return Math.max(1600,Math.min(2400,Math.round(summary.averageMs+750)));if(summary.successRate<40)return 3500;return 2500}
function renderPackRecoveryMetrics(){const scoreboard=$("packSessionScoreboard");if(!scoreboard)return;let node=$("packRecoverySummary");if(!node){node=document.createElement("span");node.innerHTML='<small>Recovery</small><b id="packRecoverySummary">No retries</b>';scoreboard.append(node);node=$("packRecoverySummary")}const summary=packRecoveryMetricSummary(),threshold=packRecoveryThresholdMs();node.textContent=!summary.attempts?`Armed · ${(threshold/1000).toFixed(1)}s`:`${summary.recovered}/${summary.attempts} · ${summary.successRate}% · ${summary.averageMs===null?"—":`${summary.averageMs}ms`} · ${(threshold/1000).toFixed(1)}s`;node.title=summary.attempts?`${summary.recovered} recovered, ${summary.failed} failed, ${summary.averageMs??0} ms average recovery time; retry threshold ${(threshold/1000).toFixed(1)} seconds`:`Pack Speed recovery is armed at ${(threshold/1000).toFixed(1)} seconds`}
function savePackRecoveryMetrics(rows=[]){try{localStorage.setItem(PACK_RECOVERY_METRICS_KEY,JSON.stringify(rows.slice(-50)))}catch{}}
async function retryPackRecovery(index){const rows=loadPackRecoveryMetrics(),row=rows[index],context=window.__rareiqCardContext||{},generation=Number(context?.snapshot?.generation),present=context?.snapshot?.card_present===true||context?.snapshot?.vision?.visible===true||context?.snapshot?.vision?.vision?.visible===true;if(!row||generation!==Number(row.generation)||!present){notify("Recovery Retry Unavailable","That stalled generation is no longer the live card. Use Correct to review its reference safely.","error");return false}packRecoveryState={generation,startedAt:Date.now(),attempted:true,attemptedAt:Date.now(),recorded:false,status:"retrying"};renderPackSpeedAutomationState(context);try{const result=await api("/api/camera/capture",{method:"POST",body:"{}"});if(!result?.ok||!(result?.job_accepted||result?.queued))throw new Error(result?.reason||"Recognition retry was not accepted.");row.manual_retries=Math.max(0,Number(row.manual_retries)||0)+1;row.last_manual_retry_at=new Date().toISOString();savePackRecoveryMetrics(rows);packRecoveryState.status="submitted";renderPackRecoveryHistory();renderPackSpeedAutomationState(context);notify("Recovery Retry Submitted",`${row.card_name||"Card"} is being recognized again.`,"success");return true}catch(error){packRecoveryState.status="attention";renderPackSpeedAutomationState(context);notify("Recovery Retry Failed",error.message||String(error),"error");return false}}
function dismissPackRecovery(index){const rows=loadPackRecoveryMetrics();if(!rows[index])return false;const [removed]=rows.splice(index,1);savePackRecoveryMetrics(rows);renderPackRecoveryMetrics();renderPackRecoveryHistory();notify("Recovery Entry Dismissed",`${removed.card_name||"Card"} was removed from recovery history.`,"success");return true}
function correctPackRecovery(index){const row=loadPackRecoveryMetrics()[index],context=window.__rareiqCardContext||{},current=Number(context?.snapshot?.generation);if(!row)return false;if(current===Number(row.generation)){openMatchCorrectionWorkflow();return true}if(row.reference_image_url){openReferenceLightbox(row.reference_image_url,row.card_name||"Recovery reference",[row.set_name,row.collector_number,"Historical recovery entry"].filter(Boolean).join(" · "));notify("Historical Recovery Reference","This older card can be inspected, but it cannot replace the current live recognition.","info");return true}notify("Correction Unavailable","No reference image was retained for this recovery entry.","error");return false}
function renderPackRecoveryHistory(){const detail=$("packRunDetail"),scoreboard=$("packSessionScoreboard");if(!detail||!scoreboard)return;let history=$("packRecoveryHistory");if(!history){history=document.createElement("details");history.id="packRecoveryHistory";history.className="pack-recovery-history";history.innerHTML='<summary><span><small>RECOVERY HISTORY</small><b id="packRecoveryHistorySummary">No stalls recorded</b></span><i>⌄</i></summary><div id="packRecoveryHistoryRows"></div>';scoreboard.after(history);history.addEventListener("click",event=>{const button=event.target.closest("[data-recovery-action]");if(!button)return;const index=Number(button.dataset.recoveryIndex),action=button.dataset.recoveryAction;if(action==="retry")retryPackRecovery(index);else if(action==="dismiss")dismissPackRecovery(index);else if(action==="correct")correctPackRecovery(index)})}const rows=loadPackRecoveryMetrics(),host=$("packRecoveryHistoryRows"),label=$("packRecoveryHistorySummary"),currentGeneration=Number(window.__rareiqCardContext?.snapshot?.generation);if(label)label.textContent=rows.length?`${rows.length} attempt${rows.length===1?"":"s"} · latest 10 shown`:"No stalls recorded";if(host)host.innerHTML=rows.length?rows.map((row,index)=>({...row,_index:index})).slice(-10).reverse().map(row=>`<article data-outcome="${escapeHtml(row.outcome||"unknown")}">${row.reference_image_url?`<img src="${escapeHtml(row.reference_image_url)}" alt="">`:'<i>?</i>'}<span><b>${escapeHtml(row.card_name||"Unverified card")}</b><small>${escapeHtml([row.set_name,row.collector_number].filter(Boolean).join(" · ")||`Generation ${Number(row.generation)||0}`)}</small></span><strong>${row.outcome==="recovered"?"Recovered":"Needs review"}</strong><em>${Math.round(Number(row.elapsed_ms)||0)}ms</em><time>${new Date(row.at).toLocaleTimeString([],{hour:"numeric",minute:"2-digit",second:"2-digit"})}</time><nav>${row.outcome==="failed"?`<button type="button" data-recovery-action="retry" data-recovery-index="${row._index}" ${currentGeneration!==Number(row.generation)?"disabled":""}>Retry</button><button type="button" data-recovery-action="correct" data-recovery-index="${row._index}">Correct</button>`:""}<button type="button" data-recovery-action="dismiss" data-recovery-index="${row._index}">Dismiss</button></nav></article>`).join(""):'<p>No recovery attempts in this workspace yet.</p>'}
function packSessionHealth(){const cards=(packSpeedRun.records||[]).slice(-5),latencies=cards.map(row=>Number(row.total)).filter(Number.isFinite),slow=latencies.filter(value=>value>=1000).length,average=latencies.length?Math.round(latencies.reduce((sum,value)=>sum+value,0)/latencies.length):null,recoveries=loadPackRecoveryMetrics().slice(-5),failures=recoveries.filter(row=>row.outcome==="failed").length,recoverySummary=packRecoveryMetricSummary(),reasons=[];let state="healthy";if(latencies.length>=3&&average>1500){state="critical";reasons.push(`${average}ms recent average`)}else if(slow>=2){state="watch";reasons.push(`${slow}/${latencies.length} recent cards over 1s`)}if(recoveries.length>=3&&failures>=2){state="critical";reasons.push(`${failures}/${recoveries.length} recent recoveries failed`)}else if(recoverySummary.attempts>=4&&recoverySummary.successRate<60&&state!=="critical"){state="watch";reasons.push(`${recoverySummary.successRate}% recovery success`)}if(!reasons.length)reasons.push(latencies.length?`${average}ms recent average · ${slow} slow`:"Waiting for pack timing samples");return{state,reasons,averageMs:average,slowCards:slow,recoveryFailures:failures}}
let currentPackSessionHealthRecommendation={action:null};
function loadPackTuningOutcome(){try{return JSON.parse(localStorage.getItem(PACK_TUNING_OUTCOME_KEY)||"null")}catch{return null}}
function savePackTuningOutcome(value){try{value?localStorage.setItem(PACK_TUNING_OUTCOME_KEY,JSON.stringify(value)):localStorage.removeItem(PACK_TUNING_OUTCOME_KEY)}catch{}return value}
function loadPackTuningHistory(){try{const rows=JSON.parse(localStorage.getItem(PACK_TUNING_HISTORY_KEY)||"[]");return Array.isArray(rows)?rows.slice(-20):[]}catch{return[]}}
function savePackTuningHistory(rows=[]){try{localStorage.setItem(PACK_TUNING_HISTORY_KEY,JSON.stringify(rows.slice(-20)))}catch{}return rows}
function packTuningScope(){const card=window.__rareiqCardContext?.card||window.__rareiqCardContext?.snapshot?.primary_candidate||{},game=String(card.game||card.game_name||"pokemon").trim().toLowerCase(),language=String(card.language||$("recognitionLanguage")?.value||"unknown").trim().toLowerCase(),set=String(card.set_id||card.set_code||card.set_name||$("setContextSelect")?.value||"unscoped").trim().toLowerCase();return`${game}|${language}|${set}`}
function packTuningScopeLabel(scope=packTuningScope()){const parts=String(scope).split("|");return parts[2]&&parts[2]!=="unscoped"?parts[2]:"Current set"}
function loadPackBestTunings(){try{const value=JSON.parse(localStorage.getItem(PACK_BEST_TUNING_KEY)||"{}");return value&&typeof value==="object"&&!Array.isArray(value)?value:{}}catch{return{}}}
function loadPackBestTuning(scope=packTuningScope()){return loadPackBestTunings()[scope]||null}
function savePackBestTuning(value,scope=value?.scope||packTuningScope()){const profiles=loadPackBestTunings();if(value)profiles[scope]={...value,scope};else delete profiles[scope];try{localStorage.setItem(PACK_BEST_TUNING_KEY,JSON.stringify(profiles))}catch{}return value?profiles[scope]:null}
function loadPackTuningRevalidation(){try{return JSON.parse(localStorage.getItem(PACK_TUNING_REVALIDATION_KEY)||"null")}catch{return null}}
function savePackTuningRevalidation(value){try{value?localStorage.setItem(PACK_TUNING_REVALIDATION_KEY,JSON.stringify(value)):localStorage.removeItem(PACK_TUNING_REVALIDATION_KEY)}catch{}return value}
function beginPackTuningOutcome(recommendation,previous={}){const samples=(packSpeedRun.records||[]).map(row=>Number(row.total)).filter(Number.isFinite).slice(-3),recoveries=loadPackRecoveryMetrics(),applied=recommendation.action==="safe-handoff"?{sensitivity:cardRemovalSettings.sensitivity}:{mode:$("setContextMode")?.value||"manual",value:$("setContextSelect")?.value||"",set:recommendation.set||""},scope=packTuningScope(),entry={id:`tuning-${Date.now()}`,scope,scopeLabel:packTuningScopeLabel(scope),action:recommendation.action,label:recommendation.title||"Session tuning",appliedAt:new Date().toISOString(),previous,applied,baselineAverage:samples.length?Math.round(samples.reduce((sum,value)=>sum+value,0)/samples.length):null,baselineSamples:samples.length,recoveryAttempts:recoveries.length,recoveryFailures:recoveries.filter(row=>row.outcome==="failed").length,status:"measuring",summary:"Measuring 0/3 cards",reverted:false};savePackTuningHistory([...loadPackTuningHistory(),entry]);return savePackTuningOutcome(entry)}
function packRevalidationIncludesTimestamp(timestamp,tuning){const workflow=loadPackTuningRevalidation();if(!workflow||workflow.scope!==tuning.scope||workflow.targetAction!==tuning.action)return true;const time=Date.parse(timestamp),insidePause=(workflow.pauses||[]).some(interval=>time>=Date.parse(interval.startedAt)&&time<=Date.parse(interval.endedAt));if(insidePause)return false;if(workflow.paused&&time>=Date.parse(workflow.pausedAt))return false;return true}
function packTuningOutcomeResult(){const tuning=loadPackTuningOutcome();if(!tuning)return null;const after=(packSpeedRun.records||[]).filter(row=>Date.parse(row.at)>Date.parse(tuning.appliedAt)&&packRevalidationIncludesTimestamp(row.at,tuning)).slice(0,3),values=after.map(row=>Number(row.total)).filter(Number.isFinite),recoveries=loadPackRecoveryMetrics().slice(Number(tuning.recoveryAttempts)||0),failures=recoveries.filter(row=>row.outcome==="failed").length,average=values.length?Math.round(values.reduce((sum,value)=>sum+value,0)/values.length):null,complete=values.length>=3,difference=complete&&Number.isFinite(tuning.baselineAverage)?Number(tuning.baselineAverage)-average:null;let status="measuring",summary=`Measuring ${values.length}/3 cards`;if(complete&&tuning.action==="safe-handoff"){status=failures?"worse":"improved";summary=failures?`${failures} handoff failure${failures===1?"":"s"} after tuning`:"3 clean handoffs after tuning"}else if(complete&&difference!==null){status=difference>50?"improved":difference< -50?"worse":"steady";summary=Math.abs(difference)<=50?`Steady · ${average}ms average`:`${Math.abs(difference)}ms ${difference>0?"faster":"slower"} · ${average}ms average`}else if(complete){status="steady";summary=`Measured · ${average}ms average`}return{...tuning,samples:values.length,average,difference,failures,complete,status,summary}}
const PACK_BEST_TUNING_MAX_AGE_MS=30*24*60*60*1000;
function packTuningConfigurationFingerprint(){return JSON.stringify({camera:$("cameraSlot1Source")?.value||$("cameraSelect")?.value||"",workspace:$("workspaceLayoutPreset")?.value||document.body.dataset.workspacePreset||"",recognition:$("recognitionModeSelect")?.value||document.body.dataset.recognitionMode||"",setMode:$("setContextMode")?.value||"auto",set:$("setContextSelect")?.value||"",viewer:$("viewerModeSelect")?.value||"auto"})}
const PACK_TUNING_CONFIGURATION_LABELS={camera:"Camera source",workspace:"Workspace",recognition:"Recognition mode",setMode:"Set mode",set:"Selected set",viewer:"Viewer mode"};
function parsePackTuningFingerprint(value){try{const parsed=JSON.parse(value||"{}");return parsed&&typeof parsed==="object"?parsed:{}}catch{return{}}}
function packBestTuningFreshness(profile){if(!profile)return{fresh:false,reason:"missing",ageMs:null,changedFields:[],detail:"No proven profile exists for this set."};const ageMs=Math.max(0,Date.now()-Date.parse(profile.lastConfirmedAt||profile.learnedAt||0)),saved=parsePackTuningFingerprint(profile.configurationFingerprint),active=parsePackTuningFingerprint(packTuningConfigurationFingerprint()),changedFields=Object.keys(PACK_TUNING_CONFIGURATION_LABELS).filter(key=>String(saved[key]??"")!==String(active[key]??"")),changedLabels=changedFields.map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]);if(changedFields.length)return{fresh:false,reason:"configuration-changed",ageMs,changedFields,detail:`Revalidate after changing: ${changedLabels.join(", ")}.`};if(!Number.isFinite(ageMs)||ageMs>PACK_BEST_TUNING_MAX_AGE_MS){const days=Number.isFinite(ageMs)?Math.floor(ageMs/86400000):30;return{fresh:false,reason:"expired",ageMs,changedFields:[],detail:`Profile is ${days} days old. Complete two successful measurements to refresh it.`}}return{fresh:true,reason:"current",ageMs,changedFields:[],detail:`Current configuration · confirmed ${Math.max(0,Math.floor(ageMs/86400000))} days ago.`}}
function packBestTuningConfidence(successfulRuns=0,freshness={fresh:true}){const runs=Math.max(0,Number(successfulRuns)||0),fresh=freshness.fresh!==false;return{level:!fresh?"revalidate":runs>=4?"proven":runs>=2?"trusted":"provisional",recommended:fresh&&runs>=2,successfulRuns:runs,needed:fresh?Math.max(0,2-runs):2}}
function startPackTuningRevalidation(){const scope=packTuningScope(),profile=loadPackBestTuning(scope),freshness=packBestTuningFreshness(profile);if(!profile||freshness.fresh)return false;savePackTuningRevalidation({active:true,scope,targetAction:profile.action,completed:0,required:2,resultIds:[],startedAt:new Date().toISOString(),configurationFingerprint:packTuningConfigurationFingerprint()});renderPackTuningHistory();notify("Revalidation Started",`Complete two successful ${profile.label||"tuning"} measurements in the current configuration.`,"success");return true}
function cancelPackTuningRevalidation(){const workflow=loadPackTuningRevalidation();if(!workflow?.active)return false;savePackTuningRevalidation({...workflow,active:false,cancelledAt:new Date().toISOString()});renderPackTuningHistory();notify("Revalidation Cancelled","The historical profile was preserved and no settings were changed.","success");return true}
function pausePackTuningRevalidation(){const workflow=loadPackTuningRevalidation();if(!workflow?.active||workflow.paused)return false;savePackTuningRevalidation({...workflow,paused:true,pausedAt:new Date().toISOString()});renderPackTuningHistory();notify("Revalidation Paused","Scans are excluded until you resume this run.","success");return true}
function packRevalidationConfigurationChanges(workflow){const saved=parsePackTuningFingerprint(workflow?.configurationFingerprint),active=parsePackTuningFingerprint(packTuningConfigurationFingerprint());return Object.keys(PACK_TUNING_CONFIGURATION_LABELS).filter(key=>String(saved[key]??"")!==String(active[key]??""))}
function packTuningRestorationPreview(workflow){if(!workflow)return[];const saved=parsePackTuningFingerprint(workflow.configurationFingerprint),active=parsePackTuningFingerprint(packTuningConfigurationFingerprint());return packRevalidationConfigurationChanges(workflow).map(key=>({key,label:PACK_TUNING_CONFIGURATION_LABELS[key],saved:String(saved[key]??"")||"Not selected",current:String(active[key]??"")||"Not selected"}))}
function selectedPackTuningRestorationFields(){return new Set([...document.querySelectorAll('#packTuningRestorationPreview input[data-restore-field]:checked')].map(input=>input.dataset.restoreField).filter(Boolean))}
function packTuningRestoreReceiptUpdate(workflow,receipt){return{latestRestoreReceipt:receipt,restoreReceipts:[...(workflow?.restoreReceipts||[]),receipt].slice(-10)}}
function requestPackTuningRunConfigurationRestore(){const fields=selectedPackTuningRestorationFields(),confirmation=$("packTuningRestoreConfirmation"),workflow=loadPackTuningRevalidation();if(!workflow?.active||!workflow.autoPaused)return false;if(!fields.size){notify("Choose Settings to Restore","Select at least one changed setting before restoring.","error");return false}const rows=packTuningRestorationPreview(workflow).filter(row=>fields.has(row.key));if(!confirmation||!rows.length)return false;confirmation.dataset.fields=JSON.stringify([...fields]);confirmation.hidden=false;const summary=$("packTuningRestoreConfirmationSummary");if(summary)summary.textContent=rows.map(row=>`${row.label}: ${row.current} → ${row.saved}`).join(" · ");return true}
function guardPackTuningRevalidationConfiguration(workflow=loadPackTuningRevalidation()){if(!workflow?.active||workflow.paused)return workflow;const changedFields=packRevalidationConfigurationChanges(workflow);if(!changedFields.length)return workflow;const next={...workflow,paused:true,autoPaused:true,pausedAt:new Date().toISOString(),pauseReason:"configuration-changed",changedFields};savePackTuningRevalidation(next);notify("Revalidation Auto-paused",`Restore ${changedFields.map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]).join(", ")} before resuming.`,"error");return next}
async function restorePackTuningRunConfiguration(selectedFields){const workflow=loadPackTuningRevalidation();if(!workflow?.active||!workflow.autoPaused)return false;const saved=parsePackTuningFingerprint(workflow.configurationFingerprint),fields=selectedFields instanceof Set?selectedFields:selectedPackTuningRestorationFields();if(!fields.size){notify("Choose Settings to Restore","Select at least one changed setting before restoring.","error");return false}try{if(fields.has("camera")&&saved.camera!==undefined){if($("cameraSlot1Source")){$("cameraSlot1Source").value=saved.camera;await setActiveCameraWorkspaceSource(saved.camera)}else if($("cameraSelect")){$("cameraSelect").value=saved.camera;await selectCamera()}}if(fields.has("workspace")&&saved.workspace!==undefined&&$("workspaceLayoutPreset")){$("workspaceLayoutPreset").value=saved.workspace;applyWorkspaceLayoutPreset(saved.workspace)}if(fields.has("recognition")&&saved.recognition!==undefined&&$("recognitionModeSelect")){$("recognitionModeSelect").value=saved.recognition;setRecognitionMode(saved.recognition)}if(fields.has("setMode")&&saved.setMode!==undefined&&$("setContextMode"))$("setContextMode").value=saved.setMode;if(fields.has("set")&&saved.set!==undefined&&$("setContextSelect"))$("setContextSelect").value=saved.set;if(fields.has("setMode")||fields.has("set"))await updateRecognitionSetContext();if(fields.has("viewer")&&saved.viewer!==undefined&&$("viewerModeSelect")){$("viewerModeSelect").value=saved.viewer;setStudioXViewerMode(saved.viewer)}const remaining=packRevalidationConfigurationChanges(workflow),receipt={completedAt:new Date().toISOString(),requested:[...fields],restored:[...fields].filter(key=>!remaining.includes(key)),remaining,resumed:!remaining.length},receiptUpdate=packTuningRestoreReceiptUpdate(workflow,receipt);if(remaining.length){savePackTuningRevalidation({...workflow,changedFields:remaining,...receiptUpdate});renderPackTuningHistory();notify("Selected Settings Restored",`${remaining.length} difference${remaining.length===1?" remains":"s remain"}. Revalidation stays paused until every setting matches.`,"success");return false}savePackTuningRevalidation({...workflow,changedFields:[],...receiptUpdate});notify("Run Configuration Restored","All saved controls match. Revalidation is resuming from its prior count.","success");return resumePackTuningRevalidation()}catch(error){notify("Configuration Restore Failed",error.message||String(error),"error");return false}}
function resumePackTuningRevalidation(){const workflow=loadPackTuningRevalidation();if(!workflow?.active||!workflow.paused)return false;const changedFields=packRevalidationConfigurationChanges(workflow);if(changedFields.length){notify("Restore Configuration First",`${changedFields.map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]).join(", ")} must match the run's starting configuration.`,"error");return false}const endedAt=new Date().toISOString(),pauses=[...(workflow.pauses||[]),{startedAt:workflow.pausedAt,endedAt}];savePackTuningRevalidation({...workflow,paused:false,autoPaused:false,pausedAt:null,pauseReason:null,changedFields:[],pauses,resumedAt:endedAt});renderPackSpeedRun();notify("Revalidation Resumed","The measurement continues from its previous card count.","success");return true}
function recordPackTuningRevalidation(result){const workflow=loadPackTuningRevalidation();if(!workflow?.active||workflow.paused||result.status!=="improved"||result.scope!==workflow.scope||result.action!==workflow.targetAction||workflow.configurationFingerprint!==packTuningConfigurationFingerprint()||(workflow.resultIds||[]).includes(result.id))return workflow;const resultIds=[...(workflow.resultIds||[]),result.id],completed=Math.min(Number(workflow.required)||2,resultIds.length),done=completed>=Number(workflow.required||2),next={...workflow,resultIds,completed,active:!done,completedAt:done?new Date().toISOString():null};savePackTuningRevalidation(next);if(done)notify("Profile Revalidated","Two fresh successful measurements restored Best Known eligibility.","success");return next}
function packTuningRevalidationInstruction(workflow,measurement=packTuningOutcomeResult()){if(!workflow)return"Start revalidation to collect two fresh successful measurements.";if(Number(workflow.completed)>=Number(workflow.required||2))return"Revalidation complete. Best Known is available for this configuration.";const run=Math.min(2,Number(workflow.completed||0)+1),samples=measurement?.action===workflow.targetAction&&!measurement.complete?Number(measurement.samples)||0:0,remaining=Math.max(0,3-samples);if(workflow.autoPaused)return`Auto-paused at ${samples}/3 cards · restore ${workflow.changedFields.map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]).join(", ")} to resume.`;if(workflow.paused)return`Paused during run ${run}/2 at ${samples}/3 cards. Unrelated scans will not count.`;if(workflow.targetAction==="safe-handoff")return`Run ${run}/2 · Apply Use Safe handoff above, scan ${remaining||3} more card${remaining===1?"":"s"}, and fully remove each card before presenting the next.`;if(workflow.targetAction==="lock-set")return`Run ${run}/2 · Apply Lock set above, then scan ${remaining||3} card${remaining===1?"":"s"} from this exact set without changing camera or workspace settings.`;return`Run ${run}/2 · Apply the matching Session Health recommendation and complete ${remaining||3} more card${remaining===1?"":"s"}.`}
function updatePackBestTuning(result){if(!result?.complete||result.status!=="improved"||result.reverted||!result.scope)return null;const score=result.action==="safe-handoff"?Math.max(1,3-Number(result.failures||0)):Math.max(1,Number(result.difference)||1),current=loadPackBestTuning(result.scope),fingerprint=packTuningConfigurationFingerprint(),currentFresh=packBestTuningFreshness(current),same=current?.action===result.action&&currentFresh.fresh&&current.configurationFingerprint===fingerprint,runs=same?Math.max(0,Number(current.successfulRuns)||1)+1:1,best=same&&Number(current.score)>=score?current:{...current,id:result.id,applied:result.applied,score,summary:result.summary},saved=savePackBestTuning({...best,scope:result.scope,scopeLabel:result.scopeLabel,action:result.action,label:result.label,configurationFingerprint:fingerprint,successfulRuns:runs,confidence:packBestTuningConfidence(runs).level,lastConfirmedAt:new Date().toISOString(),learnedAt:same?current?.learnedAt||new Date().toISOString():new Date().toISOString()},result.scope);recordPackTuningRevalidation(result);return saved}
function syncPackTuningHistoryResult(result){if(!result)return;const rows=loadPackTuningHistory(),index=rows.findIndex(row=>row.id===result.id);if(index<0)return;if(rows[index].status===result.status&&rows[index].summary===result.summary)return;rows[index]={...rows[index],status:result.status,summary:result.summary,average:result.average,difference:result.difference,failures:result.failures,complete:result.complete};savePackTuningHistory(rows);updatePackBestTuning({...result,...rows[index]})}
function renderPackTuningOutcome(){const alert=$("packSessionHealth"),node=$("packSessionHealthOutcome"),revert=$("packSessionHealthRevert");if(!alert||!node)return;const result=packTuningOutcomeResult();node.hidden=!result;if(revert)revert.hidden=!result||result.reverted;if(!result)return;syncPackTuningHistoryResult(result);node.dataset.status=result.status;node.textContent=result.summary;node.title=`${result.label} · baseline ${result.baselineAverage===null?"not available":`${result.baselineAverage}ms`} · ${result.summary}`}
function packSessionHealthRecommendation(health=packSessionHealth()){if(health.state==="healthy")return{action:null,title:"",detail:""};if(health.recoveryFailures>=2){if(cardRemovalSettings.sensitivity==="safe")return{action:null,title:"Safe handoff active",detail:"Safe removal timing is already protecting the next-card handoff."};return{action:"safe-handoff",title:"Use Safe handoff",detail:"Increase the empty-frame confirmation window without changing recognition safeguards."}}const latency=packRunRecommendation(packSpeedRun.records||[]);if(latency.action==="lock-set")return{...latency,title:`Lock ${latency.set}`,detail:"Constrain candidate search to this pack's verified set. Exact-version checks stay enabled."};return{action:null,title:latency.title,detail:latency.detail}}
async function applyPackSessionHealthRecommendation(){const recommendation=currentPackSessionHealthRecommendation;if(recommendation.action==="safe-handoff"){const previous={sensitivity:cardRemovalSettings.sensitivity};cardRemovalSettings.sensitivity="safe";saveCardRemovalSettings();beginPackTuningOutcome(recommendation,previous);renderCardRemovalSettings();renderPackSessionHealth();renderPackTuningHistory();notify("Safe Handoff Applied","Pack Speed will compare the next three handoffs. Exact-card verification is unchanged.","success");return true}if(recommendation.action==="lock-set"){const previous={mode:$("setContextMode")?.value||"auto",value:$("setContextSelect")?.value||""};currentPackRunRecommendation=recommendation;const applied=await applyPackRunRecommendation();if(applied)beginPackTuningOutcome(recommendation,previous);renderPackSessionHealth();renderPackTuningHistory();return Boolean(applied)}return false}
async function revertLatestPackTuning(){const tuning=loadPackTuningOutcome(),history=loadPackTuningHistory(),latest=history.at(-1);if(!tuning||!latest||latest.id!==tuning.id||tuning.reverted)return false;if(tuning.action==="safe-handoff"){cardRemovalSettings.sensitivity=CARD_REMOVAL_PRESETS[tuning.previous?.sensitivity]?tuning.previous.sensitivity:"adaptive";saveCardRemovalSettings();renderCardRemovalSettings()}else if(tuning.action==="lock-set"){if($("setContextMode"))$("setContextMode").value=tuning.previous?.mode||"auto";if($("setContextSelect")&&tuning.previous?.value)$("setContextSelect").value=tuning.previous.value;await updateRecognitionSetContext()}tuning.reverted=true;tuning.revertedAt=new Date().toISOString();savePackTuningOutcome(tuning);latest.reverted=true;latest.revertedAt=tuning.revertedAt;savePackTuningHistory(history);renderPackSessionHealth();renderPackTuningHistory();notify("Tuning Reverted",`${tuning.label} was restored to its previous operator setting.`,"success");return true}
async function applyPackBestTuning(){const scope=packTuningScope(),profile=loadPackBestTuning(scope),freshness=packBestTuningFreshness(profile),confidence=packBestTuningConfidence(profile?.successfulRuns,freshness);if(!profile||profile.scope!==scope||!confidence.recommended)return false;const recommendation={action:profile.action,title:`Best Known · ${profile.label||"tuning"}`,set:profile.applied?.set||""};if(profile.action==="safe-handoff"){const previous={sensitivity:cardRemovalSettings.sensitivity};cardRemovalSettings.sensitivity=CARD_REMOVAL_PRESETS[profile.applied?.sensitivity]?profile.applied.sensitivity:"safe";saveCardRemovalSettings();beginPackTuningOutcome(recommendation,previous);renderCardRemovalSettings()}else if(profile.action==="lock-set"){const previous={mode:$("setContextMode")?.value||"auto",value:$("setContextSelect")?.value||""};if(!profile.applied?.value)return notify("Best Profile Unavailable","The saved set is not available in this workspace.","error");if($("setContextMode"))$("setContextMode").value=profile.applied.mode||"manual";if($("setContextSelect"))$("setContextSelect").value=profile.applied.value;await updateRecognitionSetContext();beginPackTuningOutcome(recommendation,previous)}else return false;renderPackSpeedRun();notify("Best Known Profile Applied",`${profile.scopeLabel||"Current set"} · ${confidence.level} from ${confidence.successfulRuns} successful measurements. RareIQ will measure the next three cards and keep rollback available.`,"success");return true}
function renderPackTuningHistory(){const coach=$("packRunCoach");if(!coach)return;let panel=$("packTuningHistory");if(!panel){panel=document.createElement("details");panel.id="packTuningHistory";panel.className="pack-tuning-history";panel.innerHTML='<summary><span><small>TUNING HISTORY</small><b id="packTuningHistorySummary">No changes applied</b></span><mark id="packBestTuningConfidence" hidden>Provisional</mark><button id="packBestTuningApply" type="button" hidden>Apply Best Known</button><i>⌄</i></summary><p id="packBestTuningFreshnessReason" hidden></p><section id="packTuningRevalidation" hidden><span><b id="packTuningRevalidationTitle">Revalidation 0/2</b><em id="packTuningRevalidationInstruction">Two fresh successful measurements required</em></span><progress id="packTuningRevalidationProgress" max="2" value="0"></progress><button id="packTuningRevalidationStart" type="button">Start Revalidation</button><button id="packTuningRevalidationPause" type="button" hidden>Pause</button><button id="packTuningRevalidationResume" type="button" hidden>Resume</button><button id="packTuningRevalidationRestore" type="button" hidden>Restore Selected</button><button id="packTuningRevalidationCancel" type="button" hidden>Cancel</button></section><div id="packTuningRestorationPreview" hidden></div><div id="packTuningRestoreReceipt" hidden></div><div id="packTuningHistoryRows"></div>';coach.before(panel);$("packBestTuningApply").addEventListener("click",event=>{event.preventDefault();applyPackBestTuning()});$("packTuningRevalidationStart").addEventListener("click",startPackTuningRevalidation);$("packTuningRevalidationPause").addEventListener("click",pausePackTuningRevalidation);$("packTuningRevalidationResume").addEventListener("click",resumePackTuningRevalidation);$("packTuningRevalidationRestore").addEventListener("click",requestPackTuningRunConfigurationRestore);$("packTuningRevalidationCancel").addEventListener("click",cancelPackTuningRevalidation)}const scope=packTuningScope(),rows=loadPackTuningHistory().filter(row=>row.scope===scope),host=$("packTuningHistoryRows"),label=$("packTuningHistorySummary"),best=loadPackBestTuning(scope),freshness=packBestTuningFreshness(best),confidence=packBestTuningConfidence(best?.successfulRuns,freshness),workflow=guardPackTuningRevalidationConfiguration(),activeWorkflow=workflow?.scope===scope?workflow:null,bestButton=$("packBestTuningApply"),confidenceNode=$("packBestTuningConfidence"),reasonNode=$("packBestTuningFreshnessReason"),revalidation=$("packTuningRevalidation"),revalidationStart=$("packTuningRevalidationStart"),revalidationPause=$("packTuningRevalidationPause"),revalidationResume=$("packTuningRevalidationResume"),revalidationRestore=$("packTuningRevalidationRestore"),revalidationCancel=$("packTuningRevalidationCancel"),restorationPreview=$("packTuningRestorationPreview"),restoreReceipt=$("packTuningRestoreReceipt");panel.dataset.scope=scope;panel.dataset.confidence=best?confidence.level:"none";panel.dataset.freshness=freshness.reason;if(label)label.textContent=best?!freshness.fresh?`${freshness.reason==="expired"?"Expired":"Configuration changed"} · revalidate ${Number(activeWorkflow?.completed)||0}/2`:confidence.recommended?`${best.scopeLabel||packTuningScopeLabel(scope)} · ${best.summary}`:`Learning ${confidence.successfulRuns}/2 · ${best.scopeLabel||packTuningScopeLabel(scope)}`:rows.length?`${rows.length} change${rows.length===1?"":"s"} · ${packTuningScopeLabel(scope)}`:`No tuning · ${packTuningScopeLabel(scope)}`;if(reasonNode){reasonNode.hidden=!best||freshness.fresh;reasonNode.textContent=freshness.detail;reasonNode.title=freshness.changedFields?.length?`Changed fields: ${freshness.changedFields.join(", ")}`:""}if(revalidation){revalidation.hidden=!best||freshness.fresh;revalidation.dataset.state=activeWorkflow?.autoPaused?"auto-paused":activeWorkflow?.paused?"paused":activeWorkflow?.active?"active":activeWorkflow?.completed>=2?"complete":"idle";revalidation.dataset.targetAction=activeWorkflow?.targetAction||best?.action||""}if($("packTuningRevalidationTitle"))$("packTuningRevalidationTitle").textContent=activeWorkflow?.completed>=2?"Revalidation complete":`Revalidation ${Number(activeWorkflow?.completed)||0}/2`;if($("packTuningRevalidationInstruction"))$("packTuningRevalidationInstruction").textContent=packTuningRevalidationInstruction(activeWorkflow);if($("packTuningRevalidationProgress"))$("packTuningRevalidationProgress").value=Math.min(2,Number(activeWorkflow?.completed)||0);if(revalidationStart)revalidationStart.hidden=Boolean(activeWorkflow?.active)||Number(activeWorkflow?.completed)>=2;if(revalidationPause)revalidationPause.hidden=!activeWorkflow?.active||Boolean(activeWorkflow?.paused);if(revalidationResume)revalidationResume.hidden=!activeWorkflow?.active||!activeWorkflow?.paused||Boolean(activeWorkflow?.autoPaused);if(revalidationRestore)revalidationRestore.hidden=!activeWorkflow?.active||!activeWorkflow?.autoPaused;if(revalidationCancel)revalidationCancel.hidden=!activeWorkflow?.active;if(restorationPreview){const previewRows=activeWorkflow?.autoPaused?packTuningRestorationPreview(activeWorkflow):[];restorationPreview.hidden=!previewRows.length;restorationPreview.innerHTML=previewRows.length?`<header><b>Choose settings to restore</b><button id="packTuningRestoreSelectAll" type="button">Select all</button></header>${previewRows.map(row=>`<article data-field="${escapeHtml(row.key)}"><label><input type="checkbox" data-restore-field="${escapeHtml(row.key)}" checked><span>${escapeHtml(row.label)}</span></label><span><small>Current</small><em>${escapeHtml(row.current)}</em></span><i>→</i><span><small>Saved run</small><strong>${escapeHtml(row.saved)}</strong></span></article>`).join("")}<footer id="packTuningRestoreConfirmation" hidden><b>Confirm selected changes</b><p id="packTuningRestoreConfirmationSummary"></p><span><button id="packTuningRestoreCancel" type="button">Cancel</button><button id="packTuningRestoreApply" type="button">Apply changes</button></span></footer>`:"";const selectAll=$("packTuningRestoreSelectAll"),confirmation=$("packTuningRestoreConfirmation");if(selectAll)selectAll.addEventListener("click",()=>{restorationPreview.querySelectorAll("input[data-restore-field]").forEach(input=>input.checked=true);if(confirmation)confirmation.hidden=true});restorationPreview.querySelectorAll("input[data-restore-field]").forEach(input=>input.addEventListener("change",()=>{if(confirmation)confirmation.hidden=true}));const restoreCancel=$("packTuningRestoreCancel"),restoreApply=$("packTuningRestoreApply");if(restoreCancel)restoreCancel.addEventListener("click",()=>{confirmation.hidden=true});if(restoreApply)restoreApply.addEventListener("click",()=>{let fields=[];try{fields=JSON.parse(confirmation.dataset.fields||"[]")}catch(error){fields=[]}restorePackTuningRunConfiguration(new Set(fields))})}if(restoreReceipt){const receipt=activeWorkflow?.latestRestoreReceipt,receiptHistory=(activeWorkflow?.restoreReceipts||[]).slice(0,-1).reverse().slice(0,9);restoreReceipt.hidden=!receipt;if(receipt){const restored=(receipt.restored||[]).map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]||key),remaining=(receipt.remaining||[]).map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]||key);restoreReceipt.dataset.status=receipt.resumed?"resumed":"paused";restoreReceipt.innerHTML=`<header><span><small>RESTORE RECEIPT</small><b>${receipt.resumed?"Configuration verified · revalidation resumed":"Partial restore · revalidation paused"}</b></span><time>${escapeHtml(new Date(receipt.completedAt).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"}))}</time></header><section><span><small>Restored</small><strong>${escapeHtml(restored.join(", ")||"None")}</strong></span><span><small>Remaining</small><em>${escapeHtml(remaining.join(", ")||"None")}</em></span></section>${receiptHistory.length?`<details><summary>Previous restoration attempts <mark>${receiptHistory.length}</mark></summary><div>${receiptHistory.map(item=>`<details class="pack-restore-history-item" data-status="${item.resumed?"resumed":"paused"}"><summary><time>${escapeHtml(new Date(item.completedAt).toLocaleTimeString([],{hour:"numeric",minute:"2-digit",second:"2-digit"}))}</time><span><b>${item.resumed?"Resumed":"Stayed paused"}</b><small>${Number(item.restored?.length)||0} restored · ${Number(item.remaining?.length)||0} remaining</small></span><i>⌄</i></summary><section><span><small>Restored settings</small><strong>${escapeHtml((item.restored||[]).map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]||key).join(", ")||"None")}</strong></span><span><small>Remaining mismatches</small><em>${escapeHtml((item.remaining||[]).map(key=>PACK_TUNING_CONFIGURATION_LABELS[key]||key).join(", ")||"None")}</em></span></section></details>`).join("")}</div></details>`:""}`}}if(confidenceNode){confidenceNode.hidden=!best;confidenceNode.textContent=best?freshness.fresh?`${confidence.level} · ${confidence.successfulRuns}×`:"Revalidate":"";confidenceNode.title=best?freshness.detail:""}if(bestButton){bestButton.hidden=!best||!confidence.recommended;bestButton.title=confidence.recommended?`${best.scopeLabel||packTuningScopeLabel(scope)} · ${confidence.level} from ${confidence.successfulRuns} successful measurements · ${best.summary}`:""}if(host)host.innerHTML=rows.length?rows.slice(-5).reverse().map(row=>`<article data-status="${escapeHtml(row.reverted?"reverted":row.status||"measuring")}"><span><b>${escapeHtml(row.label||"Session tuning")}</b><small>${escapeHtml(row.scopeLabel||packTuningScopeLabel(row.scope))} · ${new Date(row.appliedAt).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"})}</small></span><strong>${escapeHtml(row.reverted?"Reverted":row.summary||"Measuring")}</strong></article>`).join(""):'<p>No tuning has been measured for this set.</p>'}
function renderPackSessionHealth(){const detail=$("packRunDetail"),coach=$("packRunCoach");if(!detail||!coach)return;let alert=$("packSessionHealth");if(!alert){alert=document.createElement("aside");alert.id="packSessionHealth";alert.className="pack-session-health";alert.innerHTML='<i></i><span><small>SESSION HEALTH</small><b id="packSessionHealthTitle">Healthy</b><em id="packSessionHealthDetail">Waiting for timing samples</em></span><strong id="packSessionHealthOutcome" hidden></strong><button id="packSessionHealthRevert" type="button" hidden>Revert</button><button id="packSessionHealthApply" type="button" hidden>Apply safe tuning</button>';coach.before(alert);$("packSessionHealthApply").addEventListener("click",applyPackSessionHealthRecommendation);$("packSessionHealthRevert").addEventListener("click",revertLatestPackTuning)}const health=packSessionHealth(),titles={healthy:"Healthy",watch:"Watch",critical:"Critical"},button=$("packSessionHealthApply");currentPackSessionHealthRecommendation=packSessionHealthRecommendation(health);alert.dataset.state=health.state;$("packSessionHealthTitle").textContent=titles[health.state];$("packSessionHealthDetail").textContent=health.reasons.join(" · ");if(button){button.hidden=!currentPackSessionHealthRecommendation.action;button.textContent=currentPackSessionHealthRecommendation.title||"Apply safe tuning";button.title=currentPackSessionHealthRecommendation.detail||""}renderPackTuningOutcome();alert.setAttribute("role",health.state==="critical"?"alert":"status");alert.setAttribute("aria-label",`${titles[health.state]} Pack Speed session: ${health.reasons.join(", ")}`)}

function loadPackSpeedRun(){try{const stored=localStorage.getItem(PACK_SPEED_RUN_KEY)||sessionStorage.getItem(PACK_SPEED_RUN_KEY),value=JSON.parse(stored||"null")||{},legacy=Array.isArray(value.latencies)?value.latencies.filter(Number.isFinite).map(total=>({name:"Previous card",total})):[],records=(Array.isArray(value.records)?value.records:legacy).slice(-100);return{records,startedAt:value.startedAt||records[0]?.at||null,expectedCards:Math.max(0,Number(value.expectedCards)||0)}}catch{return{records:[],startedAt:null,expectedCards:0}}}
function savePackSpeedRun(){try{localStorage.setItem(PACK_SPEED_RUN_KEY,JSON.stringify(packSpeedRun));sessionStorage.removeItem(PACK_SPEED_RUN_KEY)}catch{}}
function loadPackSpeedHistory(){try{const value=JSON.parse(localStorage.getItem(PACK_SPEED_HISTORY_KEY)||"[]");return Array.isArray(value)?value.slice(-25):[]}catch{return[]}}
function packAutoFinishPrefs(){try{return{enabled:true,expectedCards:6,...JSON.parse(localStorage.getItem(PACK_AUTO_FINISH_KEY)||"{}")}}catch{return{enabled:true,expectedCards:6}}}
function loadPackRearmGate(){try{return{active:false,finishedStateId:"",...JSON.parse(localStorage.getItem(PACK_REARM_KEY)||"{}")}}catch{return{active:false,finishedStateId:""}}}
function savePackRearmGate(){try{localStorage.setItem(PACK_REARM_KEY,JSON.stringify(packRearmGate))}catch{}}
function armNextPackGate(){packRearmGate={active:true,finishedStateId:String(lastAutoAddStateId||""),armedAt:new Date().toISOString()};savePackRearmGate();renderPackRearmState()}
function clearNextPackGate(){if(!packRearmGate.active)return false;packRearmGate={active:false,finishedStateId:"",rearmedAt:new Date().toISOString()};savePackRearmGate();renderPackRearmState();return true}
function renderPackRearmState(){const node=$("packRearmState");if(!node)return;node.dataset.state=packRearmGate.active?"waiting":"ready";node.textContent=packRearmGate.active?"Remove final card":"Next pack ready"}
function savePackAutoFinishPrefs(){const prefs={enabled:Boolean($("packAutoFinishEnabled")?.checked),expectedCards:Math.max(1,Math.min(30,Number($("packSpeedExpectedCards")?.value)||6))};localStorage.setItem(PACK_AUTO_FINISH_KEY,JSON.stringify(prefs));renderPackSpeedRun();return prefs}
function packRunSummaryData(run=packSpeedRun){const records=run.records||[],values=records.map(row=>Number(row.total)).filter(Number.isFinite),started=Date.parse(run.startedAt||records[0]?.at||""),finished=Date.parse(records.at(-1)?.at||""),hasPrice=row=>row.marketValue!==null&&row.marketValue!==undefined&&row.marketValue!==""&&Number.isFinite(Number(row.marketValue)),rarity_counts={},tier_counts={},priced=records.filter(hasPrice),tierRank={standard:0,low:1,medium:2,grail:3};records.forEach(row=>{const rarity=String(row.rarity||"Unknown"),tier=String(row.hitTier||"standard");rarity_counts[rarity]=(rarity_counts[rarity]||0)+1;tier_counts[tier]=(tier_counts[tier]||0)+1});const strongest_pull=records.slice().sort((a,b)=>(tierRank[String(b.hitTier||"standard")]||0)-(tierRank[String(a.hitTier||"standard")]||0)||(hasPrice(b)?Number(b.marketValue):-1)-(hasPrice(a)?Number(a.marketValue):-1))[0]||null;return{cards:records.length,average_ms:values.length?Math.round(values.reduce((sum,value)=>sum+value,0)/values.length):null,fastest_ms:values.length?Math.round(Math.min(...values)):null,slowest_ms:values.length?Math.round(Math.max(...values)):null,under_one_second_rate:values.length?Math.round(values.filter(value=>value<1000).length/values.length*100):null,elapsed_ms:Number.isFinite(started)&&Number.isFinite(finished)?Math.max(0,finished-started):null,rarity_counts,tier_counts,hits:records.filter(row=>["low","medium","grail"].includes(String(row.hitTier))).length,verified_value_total:Math.round(priced.reduce((sum,row)=>sum+Number(row.marketValue),0)*100)/100,valued_cards:priced.length,unvalued_cards:records.length-priced.length,strongest_pull:strongest_pull?{card_name:strongest_pull.name,collector_number:strongest_pull.number,rarity:strongest_pull.rarity,hit_tier:strongest_pull.hitTier,market_value:hasPrice(strongest_pull)?Number(strongest_pull.marketValue):null,reference_image_url:strongest_pull.referenceImage||""}:null}}
function archivePackSpeedRun(){if(!(packSpeedRun.records||[]).length)return null;const history=loadPackSpeedHistory(),archive={schema:"rareiq-pack-speed-v1",finishedAt:new Date().toISOString(),startedAt:packSpeedRun.startedAt,summary:packRunSummaryData(),records:packSpeedRun.records};history.push(archive);localStorage.setItem(PACK_SPEED_HISTORY_KEY,JSON.stringify(history.slice(-25)));return archive}
function exportPackSpeedRun(){if(!(packSpeedRun.records||[]).length)return notify("Nothing to Export","Complete at least one card first.","error");const report={schema:"rareiq-pack-speed-v1",exportedAt:new Date().toISOString(),startedAt:packSpeedRun.startedAt,summary:packRunSummaryData(),previousPack:loadPackSpeedHistory().at(-1)?.summary||null,records:packSpeedRun.records},url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"})),link=document.createElement("a");link.href=url;link.download=`rareiq-pack-${new Date().toISOString().replace(/[:.]/g,"-")}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify("Pack Report Exported",`${report.summary.cards} cards exported with timing details.`,"success")}
function ensurePackSessionActions(){const detail=$("packRunDetail"),header=detail?.querySelector("header"),scoreboard=$("packSessionScoreboard");if(!header||!scoreboard)return;let actions=$("packSessionActions");if(!actions){const prefs=packAutoFinishPrefs();actions=document.createElement("nav");actions.id="packSessionActions";actions.className="pack-session-actions";actions.innerHTML=`<b id="packRearmState" data-state="ready">Next pack ready</b><label title="Archive automatically when the expected card count is reached"><input id="packAutoFinishEnabled" type="checkbox" ${prefs.enabled?"checked":""}><span>Auto finish</span><input id="packSpeedExpectedCards" type="number" min="1" max="30" value="${Math.max(1,Math.min(30,Number(prefs.expectedCards)||6))}" aria-label="Expected cards per pack"></label><button id="packRunExport" type="button">Export</button><button id="packRunFinish" type="button">Finish Pack</button>`;actions.append($("packRunClose"));header.append(actions);$("packRunExport").addEventListener("click",exportPackSpeedRun);$("packRunFinish").addEventListener("click",resetPackSpeedRun);$("packAutoFinishEnabled").addEventListener("change",savePackAutoFinishPrefs);$("packSpeedExpectedCards").addEventListener("change",savePackAutoFinishPrefs);renderPackRearmState()}if(!$("packSessionComparison")){const item=document.createElement("span");item.className="comparison";item.innerHTML='<small>Vs previous</small><b id="packSessionComparison">No baseline</b>';scoreboard.append(item)}}
function maybeCompletePackSpeedRun(result={}){const reveal=result?.reveal_sequence||{},prefs=packAutoFinishPrefs(),expected=Math.max(1,Number(reveal.expected_cards)||Number(packSpeedRun.expectedCards)||Number(prefs.expectedCards)||6);packSpeedRun.expectedCards=expected;savePackSpeedRun();if(!prefs.enabled||packSpeedRun.records.length<expected)return false;const archived=archivePackSpeedRun();packSpeedRun={records:[],startedAt:null,expectedCards:0};armNextPackGate();savePackSpeedRun();renderPackSpeedRun();if(archived)schedulePackRecap();notify("Pack Auto-finished",`${archived?.summary?.cards||expected} verified cards archived. Remove the final card to arm the next pack.`,"success");return true}
function renderPackSessionComparison(){ensurePackSessionActions();const node=$("packSessionComparison");if(!node)return;const current=packRunSummaryData(),previous=loadPackSpeedHistory().at(-1)?.summary||null,difference=current.average_ms!==null&&Number.isFinite(Number(previous?.average_ms))?Number(previous.average_ms)-current.average_ms:null,expected=Math.max(1,Number(packSpeedRun.expectedCards)||Number(packAutoFinishPrefs().expectedCards)||6);node.textContent=difference===null?(previous?`Previous · ${previous.cards} cards`:"No baseline"):difference===0?"Same pace":`${Math.abs(Math.round(difference))} ms ${difference>0?"faster":"slower"}`;node.dataset.direction=difference===null?"idle":difference>=0?"faster":"slower";if($("packSessionCompleted"))$("packSessionCompleted").textContent=`${current.cards} / ${expected} cards`}
function ensurePackHistoryChart(){const detail=$("packRunDetail"),coach=$("packRunCoach");if(!detail||!coach)return null;let chart=$("packHistoryChart");if(chart)return chart;chart=document.createElement("section");chart.id="packHistoryChart";chart.className="pack-history-chart";chart.innerHTML='<header><div><small>RECENT PACKS</small><b id="packHistoryTrend">Collecting baseline</b></div><span id="packHistoryRange">0 completed</span></header><div id="packHistoryBars" aria-label="Recent pack average recognition latency"></div>';coach.before(chart);return chart}
function renderPackHistoryChart(){const chart=ensurePackHistoryChart();if(!chart)return;const history=loadPackSpeedHistory(),archived=history.slice(-7).map((item,index)=>({label:`P${Math.max(1,history.length-6+index)}`,average:Number(item?.summary?.average_ms),cards:Number(item?.summary?.cards)||0,active:false})).filter(item=>Number.isFinite(item.average)),current=packRunSummaryData(),points=current.average_ms===null?archived:[...archived,{label:"LIVE",average:Number(current.average_ms),cards:current.cards,active:true}],values=points.map(item=>item.average),peak=Math.max(1,...values),first=values[0],last=values.at(-1),change=Number.isFinite(first)&&Number.isFinite(last)&&first>0?(last-first)/first:0,trend=points.length<2?"baseline":change<=-.08?"improving":change>=.08?"slowing":"stable",labels={baseline:"Collecting baseline",improving:`Improving · ${Math.round(Math.abs(change)*100)}%`,slowing:`Slowing · ${Math.round(Math.abs(change)*100)}%`,stable:"Pace stable"};chart.dataset.trend=trend;$("packHistoryTrend").textContent=labels[trend];$("packHistoryRange").textContent=`${archived.length} finished${current.cards?` · ${current.cards} live`:""}`;$("packHistoryBars").innerHTML=points.length?points.map(item=>`<article data-active="${item.active}" data-health="${item.average<=750?"fast":item.average<=1000?"watch":"slow"}" title="${item.label}: ${Math.round(item.average)} ms average across ${item.cards} cards"><span><i style="--pack-bar:${Math.max(12,Math.round(item.average/peak*100))}%"></i></span><b>${Math.round(item.average)}</b><small>${item.label}</small></article>`).join(""):'<p>Finish the first pack to begin performance trending.</p>'}
function packRecapStyle(){try{return localStorage.getItem(PACK_RECAP_STYLE_KEY)||"clean"}catch{return"clean"}}
function packAutoRecapPrefs(){try{return{enabled:false,delaySeconds:5,...JSON.parse(localStorage.getItem(PACK_AUTO_RECAP_KEY)||"{}")}}catch{return{enabled:false,delaySeconds:5}}}
function savePackAutoRecapPrefs(){const prefs={enabled:Boolean($("packAutoRecapEnabled")?.checked),delaySeconds:Math.max(1,Math.min(30,Number($("packAutoRecapDelay")?.value)||5))};localStorage.setItem(PACK_AUTO_RECAP_KEY,JSON.stringify(prefs));if(!prefs.enabled)cancelPendingPackRecap();renderPackRecapAutomation();return prefs}
function renderPackRecapAutomation(){const status=$("packAutoRecapStatus"),cancel=$("packAutoRecapCancel"),hide=$("packRecapHide");if(!status||!cancel)return;const pending=Math.max(0,Math.ceil((packRecapDueAt-Date.now())/1000)),live=Math.max(0,Math.ceil((packRecapLiveDueAt-Date.now())/1000)),state=packRecapLiveTimer?"live":packRecapTimer?"armed":"idle";status.dataset.state=state;status.textContent=state==="live"?`ON AIR · ${live}s`:state==="armed"?`On air in ${pending}s`:packAutoRecapPrefs().enabled?"Auto recap ready":"Auto recap off";cancel.hidden=!packRecapTimer;if(hide)hide.hidden=!packRecapLiveTimer}
function cancelPendingPackRecap(notifyUser=true){const active=Boolean(packRecapTimer);clearTimeout(packRecapTimer);clearInterval(packRecapCountdownTimer);packRecapTimer=packRecapCountdownTimer=0;packRecapDueAt=0;renderPackRecapAutomation();if(active&&notifyUser)notify("Auto Recap Cancelled","The finished-pack recap will not go on-air automatically.","success");return active}
function schedulePackRecap(){const prefs=packAutoRecapPrefs();if(!prefs.enabled)return false;cancelPendingPackRecap(false);packRecapDueAt=Date.now()+prefs.delaySeconds*1000;packRecapTimer=setTimeout(()=>{packRecapTimer=0;clearInterval(packRecapCountdownTimer);packRecapCountdownTimer=0;packRecapDueAt=0;sendPackSpeedRecapOverlay("take").catch(error=>notify("Auto Recap Failed",error.message||String(error),"error")).finally(renderPackRecapAutomation)},prefs.delaySeconds*1000);packRecapCountdownTimer=setInterval(renderPackRecapAutomation,250);renderPackRecapAutomation();notify("Auto Recap Armed",`Finished-pack recap will go on-air in ${prefs.delaySeconds} seconds.`,"success");return true}
function ensurePackPullSummary(){const detail=$("packRunDetail"),chart=$("packHistoryChart");if(!detail||!chart)return null;let panel=$("packPullSummary");if(panel)return panel;const auto=packAutoRecapPrefs();panel=document.createElement("section");panel.id="packPullSummary";panel.className="pack-pull-summary";panel.innerHTML=`<header><div class="pack-pull-identity"><small id="packPullScope">CURRENT PACK</small><b id="packPullBest">Waiting for pulls</b><strong id="packPullValue">Value unavailable</strong></div><aside><select id="packRecapStyle" aria-label="Pack recap style"><option value="clean">Clean</option><option value="hype">Hype</option><option value="grail">Grail</option><option value="stats">Stats</option></select><label title="Automatically take the finished-pack recap live after a cancel window"><input id="packAutoRecapEnabled" type="checkbox" ${auto.enabled?"checked":""}><span>Auto air</span><input id="packAutoRecapDelay" type="number" min="1" max="30" value="${Math.max(1,Math.min(30,Number(auto.delaySeconds)||5))}" aria-label="Automatic recap delay in seconds"><span>s</span></label><b id="packAutoRecapStatus" data-state="idle">Auto recap off</b><button id="packAutoRecapCancel" type="button" hidden>Cancel</button><button id="packRecapHide" type="button" hidden>Hide Now</button><button id="packPullPreviewRecap" type="button">Preview</button><button id="packPullSendRecap" type="button">Take Live</button></aside></header><div><span><small>Hits</small><b id="packPullHits">0</b></span><span><small>Pricing</small><b id="packPullCoverage">0 / 0</b></span><span class="rarities"><small>Rarities</small><b id="packPullRarities">Waiting</b></span></div>`;chart.after(panel);$("packRecapStyle").value=packRecapStyle();$("packRecapStyle").addEventListener("change",event=>localStorage.setItem(PACK_RECAP_STYLE_KEY,event.target.value));$("packAutoRecapEnabled").addEventListener("change",savePackAutoRecapPrefs);$("packAutoRecapDelay").addEventListener("change",savePackAutoRecapPrefs);$("packAutoRecapCancel").addEventListener("click",()=>cancelPendingPackRecap());$("packRecapHide").addEventListener("click",()=>hidePackSpeedRecap().catch(error=>notify("Recap Not Hidden",error.message||String(error),"error")));$("packPullPreviewRecap").addEventListener("click",()=>sendPackSpeedRecapOverlay("preview").catch(error=>notify("Recap Not Previewed",error.message||String(error),"error")));$("packPullSendRecap").addEventListener("click",()=>sendPackSpeedRecapOverlay("take").catch(error=>notify("Recap Not Sent",error.message||String(error),"error")));renderPackRecapAutomation();return panel}
function renderPackPullSummary(){const panel=ensurePackPullSummary();if(!panel)return;const current=packRunSummaryData(),last=loadPackSpeedHistory().at(-1)?.summary||null,summary=current.cards?current:last,scope=current.cards?"CURRENT PACK":"LAST FINISHED PACK";$("packPullScope").textContent=summary?scope:"PACK PULLS";$("packPullBest").textContent=summary?.strongest_pull?.card_name||"Waiting for pulls";$("packPullValue").textContent=summary?.valued_cards?`$${Number(summary.verified_value_total).toFixed(2)} verified`:"Value unavailable";$("packPullHits").textContent=String(summary?.hits||0);$("packPullCoverage").textContent=summary?`${summary.valued_cards||0} / ${summary.cards||0}`:"0 / 0";$("packPullRarities").textContent=summary?Object.entries(summary.rarity_counts||{}).map(([name,count])=>`${name} ${count}`).join(" · ")||"Unknown":"Waiting";[$("packPullPreviewRecap"),$("packPullSendRecap")].forEach(button=>{button.disabled=!last;button.title=last?"Use the most recently finished pack":"Finish a pack to enable its recap"});panel.dataset.tier=summary?.strongest_pull?.hit_tier||"standard"}
function buildPackRecapGraphic(summary,style=packRecapStyle()){const pull=summary.strongest_pull,rarities=Object.entries(summary.rarity_counts||{}).map(([name,count])=>`${name} ×${count}`).join(" · "),value=summary.valued_cards?`Verified value $${Number(summary.verified_value_total).toFixed(2)}`:`${summary.unvalued_cards||summary.cards} unpriced`,presets={clean:{graphicStyle:"glass",accent:"cyan",duration:8000,title:pull?.card_name?`Best Pull · ${pull.card_name}`:"Pack Recap",subtitle:[`${summary.cards} cards`,`${summary.hits||0} hits`,value,rarities]},hype:{graphicStyle:"neon",accent:"purple",duration:10000,title:pull?.card_name?`PACK HIT · ${pull.card_name}`:"PACK RECAP",subtitle:[`${summary.hits||0} HITS`,value,rarities]},grail:{graphicStyle:"neon",accent:"gold",duration:0,title:pull?.card_name?`${pull.hit_tier==="grail"?"GRAIL PULL":"BEST PULL"} · ${pull.card_name}`:"GRAIL WATCH",subtitle:[pull?.rarity,value,`${summary.cards} cards`,rarities]},stats:{graphicStyle:"solid",accent:"green",duration:8000,title:`Pack Recap · ${summary.cards} Cards`,subtitle:[`${summary.hits||0} hits`,value,`${summary.valued_cards||0}/${summary.cards} priced`,rarities]}};const selected=presets[style]||presets.clean;return{kind:"announcement",style:selected.graphicStyle,accent:selected.accent,duration_ms:selected.duration,title:selected.title,subtitle:selected.subtitle.filter(Boolean).join(" · "),image_url:pull?.reference_image_url||""}}
async function hidePackSpeedRecap(){clearTimeout(packRecapLiveTimer);clearInterval(packRecapCountdownTimer);packRecapLiveTimer=packRecapCountdownTimer=0;packRecapLiveDueAt=0;const result=await sendProductionGraphic("hide");renderPackRecapAutomation();return result}
async function sendPackSpeedRecapOverlay(action="take"){const summary=loadPackSpeedHistory().at(-1)?.summary;if(!summary?.cards)throw new Error("Finish a pack before sending its recap.");if(action==="take")cancelPendingPackRecap(false);const graphic=buildPackRecapGraphic(summary,$("packRecapStyle")?.value||packRecapStyle());if($("productionGraphicKind"))$("productionGraphicKind").value=graphic.kind;if($("productionGraphicStyle"))$("productionGraphicStyle").value=graphic.style;if($("productionGraphicAccent"))$("productionGraphicAccent").value=graphic.accent;if($("productionGraphicDuration"))$("productionGraphicDuration").value=String(graphic.duration_ms);if($("productionGraphicTitle"))$("productionGraphicTitle").value=graphic.title;if($("productionGraphicSubtitle"))$("productionGraphicSubtitle").value=graphic.subtitle;if($("productionGraphicPreviewFrame"))$("productionGraphicPreviewFrame").dataset.imageUrl=graphic.image_url;const result=await sendProductionGraphic(action);if(action==="take"){const duration=Math.max(3000,Number(graphic.duration_ms)||12000);clearTimeout(packRecapLiveTimer);packRecapLiveDueAt=Date.now()+duration;packRecapLiveTimer=setTimeout(()=>hidePackSpeedRecap().catch(error=>notify("Recap Auto-hide Failed",error.message||String(error),"error")),duration);clearInterval(packRecapCountdownTimer);packRecapCountdownTimer=setInterval(renderPackRecapAutomation,250);renderPackRecapAutomation()}return result}
function packRunStage(timings={}){const sum=keys=>keys.reduce((total,key)=>total+Math.max(0,Number(timings[key])||0),0),stages={detect:sum(["queue_ms","prepare_ms","global_visual_ms"]),candidate:sum(["exact_reference_ms","reference_identifier_ms","artwork_preflight_ms","artwork_search_ms"]),verify:sum(["ocr_ms","ranking_ms","finalize_ms"])};return Object.entries(stages).sort((a,b)=>b[1]-a[1])[0]?.[0]||"unknown"}
let currentPackRunRecommendation={stage:"waiting",action:null};
function packRunRecommendation(records=[]){if(records.length<2)return{stage:"waiting",title:"Waiting for pack data",detail:"Complete two cards to receive a safe tuning recommendation.",action:null};const counts=records.reduce((result,row)=>{const key=["detect","candidate","verify"].includes(row.bottleneck)?row.bottleneck:"unknown";result[key]=(result[key]||0)+1;return result},{detect:0,candidate:0,verify:0,unknown:0}),stage=Object.entries(counts).sort((a,b)=>b[1]-a[1])[0][0],sets=records.map(row=>String(row.set||"").trim()).filter(Boolean),commonSet=sets.length&&sets.every(value=>value.toLowerCase()===sets[0].toLowerCase())?sets[0]:"";if(stage==="candidate"&&commonSet&&$("setContextMode")?.value!=="manual")return{stage,title:"Candidate search is the bottleneck",detail:`Lock ${commonSet} to shrink the search space for the rest of this pack.`,action:"lock-set",set:commonSet};if(stage==="candidate")return{stage,title:"Candidate search is the bottleneck",detail:"The set is already constrained or cards span multiple sets. Keep the current safety checks active.",action:null};if(stage==="detect")return{stage,title:"Detection is the bottleneck",detail:"Improve card framing, contrast, and lighting. RareIQ will not change camera controls automatically.",action:null};if(stage==="verify")return{stage,title:"Verification is the bottleneck",detail:"Check glare over the footer and collector number. Exact-version safeguards remain enabled.",action:null};return{stage:"unknown",title:"No dominant stage yet",detail:"Continue the pack to collect a larger timing sample.",action:null}}
function renderPackRunCoach(records){currentPackRunRecommendation=packRunRecommendation(records);const recommendation=currentPackRunRecommendation,host=$("packRunCoach"),button=$("packRunCoachApply");if(host)host.dataset.stage=recommendation.stage;if($("packRunCoachTitle"))$("packRunCoachTitle").textContent=recommendation.title;if($("packRunCoachDetail"))$("packRunCoachDetail").textContent=recommendation.detail;if(button){button.hidden=!recommendation.action;button.textContent=recommendation.action==="lock-set"?"Lock set":"Apply tuning"}}
async function applyPackRunRecommendation(){const recommendation=currentPackRunRecommendation;if(recommendation.action!=="lock-set")return false;const target=recognitionSetOptions.find(item=>String(item.set_name||item.name||"").toLowerCase()===String(recommendation.set||"").toLowerCase());if(!target){notify("Set Lock Unavailable",`${recommendation.set} is not available in the loaded set selector.`,"error");return false}const value=`${target.provider||""}|${target.language||""}|${target.set_id||target.id||""}`;if($("setContextSelect"))$("setContextSelect").value=value;if($("setContextMode"))$("setContextMode").value="manual";await updateRecognitionSetContext();renderPackSpeedRun();notify("Pack Tuning Applied",`${recommendation.set} is locked for faster candidate search.`,"success");return true}
function packPredictionSpeedComparison(records=[]){const valid=records.filter(row=>Number.isFinite(Number(row.total))),predicted=valid.filter(row=>Number(row.predictionConsumed)>0),standard=valid.filter(row=>!(Number(row.predictionConsumed)>0)),average=rows=>rows.length?rows.reduce((sum,row)=>sum+Number(row.total),0)/rows.length:null,predictedAverage=average(predicted),standardAverage=average(standard),difference=predictedAverage!==null&&standardAverage!==null?standardAverage-predictedAverage:null,improvement=difference!==null&&standardAverage>0?difference/standardAverage*100:null;return{predictedCount:predicted.length,standardCount:standard.length,predictedAverage,standardAverage,difference,improvement,ready:predicted.length>0&&standard.length>0}}
function ensurePackLearningControls(rows){let controls=$("packLearningControls");if(controls)return controls;controls=document.createElement("section");controls.id="packLearningControls";controls.className="pack-learning-controls";controls.innerHTML='<div class="pack-learning-identity"><img id="packLearningThumb" alt="Active pack wrapper" hidden><span><b>ACTIVE PRODUCT LEARNING</b><span id="packLearningScope">Loading context…</span></span></div><select id="packLearningSelector" aria-label="Choose learned pack wrapper"><option value="">No learned wrappers</option></select><label><input id="packLearningEnabled" type="checkbox" checked><span>Enabled</span></label><button id="packLearningRename" type="button">Rename</button><button id="packLearningInspect" type="button">Inspect</button><button id="packLearningUndo" type="button" hidden>Undo</button><button id="packLearningRecover" type="button">Recover</button><button id="packLearningExport" type="button">Export</button><button id="packLearningImport" type="button">Import</button><button id="packLearningReset" type="button">Reset</button><input id="packLearningImportFile" type="file" accept="application/json,.json" hidden><div id="packLearningEvidence" hidden></div><div id="packLearningBackups" hidden></div>';rows.before(controls);$("packLearningSelector").addEventListener("change",event=>activatePackLearningContext(event.target.value));$("packLearningEnabled").addEventListener("change",()=>setPackLearningEnabled($("packLearningEnabled").checked));$("packLearningRename").addEventListener("click",renamePackLearningContext);$("packLearningInspect").addEventListener("click",()=>loadPackLearningStatus(true));$("packLearningThumb").addEventListener("click",()=>{const thumb=$("packLearningThumb");if(!thumb.hidden&&thumb.src)openReferenceLightbox(thumb.src,thumb.dataset.label||"Pack wrapper reference","Compare the learned wrapper against the live camera")});$("packLearningUndo").addEventListener("click",undoPackLearningTransition);$("packLearningRecover").addEventListener("click",loadPackLearningBackups);$("packLearningExport").addEventListener("click",exportPackLearningModel);$("packLearningImport").addEventListener("click",()=>$("packLearningImportFile").click());$("packLearningImportFile").addEventListener("change",event=>importPackLearningModel(event.target.files?.[0]));$("packLearningReset").addEventListener("click",resetPackLearningContext);loadPackLearningStatus(false);return controls}
function renderPackLearningEvidence(contexts=[]){const evidence=$("packLearningEvidence");if(!evidence)return;const edges=contexts.flatMap(context=>Object.entries(context.successors||{}).map(([to,count])=>({from:Number(context.from),to:Number(to),count:Number(count)||0})));evidence.innerHTML=edges.length?edges.map(edge=>`<article><span><b>${edge.from} → ${edge.to}</b><small>${edge.count} verified observation${edge.count===1?"":"s"}</small></span><button type="button" data-remove-transition="${edge.from}:${edge.to}">Remove</button></article>`).join(""):'<p>No learned transitions for this product.</p>';evidence.querySelectorAll("[data-remove-transition]").forEach(button=>button.addEventListener("click",()=>{const [from,to]=button.dataset.removeTransition.split(":").map(Number);removePackLearningTransition(from,to)}))}
async function loadPackLearningStatus(expand=false){const payload=await api("/api/recognition/pack-learning"),scope=(payload.scope||[]).filter(Boolean),enabled=payload.enabled!==false,evidence=$("packLearningEvidence"),undo=$("packLearningUndo"),thumb=$("packLearningThumb"),selector=$("packLearningSelector"),label=payload.context_label||scope[3]||"Default pack context",reference=payload.pack_reference||null,references=payload.pack_references||[];if(selector){selector.innerHTML=references.length?references.map(item=>`<option value="${escapeHtml(item.id||"")}" ${item.id===reference?.id?"selected":""}>${escapeHtml(item.pack_label||item.set_name||"Learned wrapper")} · ${escapeHtml(item.language||"Any")}</option>`).join(""):'<option value="">No learned wrappers</option>';selector.disabled=!references.length}if($("packLearningEnabled"))$("packLearningEnabled").checked=enabled;if($("packLearningScope"))$("packLearningScope").textContent=`${label} · ${scope[1]||scope[0]||"No active set"} · ${Number(payload.context_count)||0} learned positions`;if(thumb){thumb.hidden=!reference?.image_url;if(reference?.image_url){thumb.src=`${reference.image_url}?v=${encodeURIComponent(reference.id||"")}`;thumb.dataset.label=label;thumb.title=`Open ${label} wrapper reference`;thumb.onerror=()=>{thumb.hidden=true}}}if(undo){undo.hidden=!payload.undo_available;undo.title=payload.undo_available?`Restore the last transition removed within ${Number(payload.undo_seconds)||30} seconds`:"No recent transition removal"}renderPackLearningEvidence(payload.contexts||[]);if(evidence&&expand)evidence.hidden=!evidence.hidden;return payload}
async function activatePackLearningContext(referenceId){if(!referenceId)return;try{const payload=await api("/api/recognition/pack-learning/activate",{method:"POST",body:JSON.stringify({reference_id:referenceId})});await Promise.all([loadRecognitionSets(),loadPackArtworkIndex()]);await loadPackLearningStatus(false);notify("Pack Wrapper Activated",`${payload.pack_reference?.pack_label||"Learned wrapper"} is now driving set filtering and order learning.`,"success")}catch(error){await loadPackLearningStatus(false);notify("Wrapper Switch Failed",error.message||String(error),"error")}}
async function setPackLearningEnabled(enabled){try{await api("/api/recognition/pack-learning/enabled",{method:"POST",body:JSON.stringify({enabled})});await loadPackLearningStatus(false);notify(enabled?"Pack Learning Enabled":"Pack Learning Disabled",enabled?"RareIQ can learn and use this product's verified ordering.":"Predictions and learning are paused for this product only.","success")}catch(error){if($("packLearningEnabled"))$("packLearningEnabled").checked=!enabled;notify("Learning Control Failed",error.message||String(error),"error")}}
async function renamePackLearningContext(){try{const current=await loadPackLearningStatus(false),label=prompt("Name this pack wrapper or product:",current.context_label||"");if(label===null)return;const clean=label.trim();if(!clean)throw new Error("Pack product name cannot be empty.");await api("/api/recognition/pack-learning/rename",{method:"POST",body:JSON.stringify({label:clean})});await loadPackLearningStatus(false);notify("Pack Product Renamed",`Active learning now shows as ${clean}.`,"success")}catch(error){notify("Rename Failed",error.message||String(error),"error")}}
async function resetPackLearningContext(){if(!confirm("Reset learned ordering for this active product only? RareIQ will create a local recovery backup first."))return;const payload=await api("/api/recognition/pack-learning/reset",{method:"POST"});await loadPackLearningStatus(false);notify("Product Learning Reset",`${Number(payload.removed_contexts)||0} learned positions removed.${payload.backup_path?" Recovery backup saved.":""}`,"success")}
async function removePackLearningTransition(from,to){if(!confirm(`Remove learned transition ${from} → ${to} from this product?`))return;const payload=await api("/api/recognition/pack-learning/remove-transition",{method:"POST",body:JSON.stringify({from_number:from,to_number:to})});await loadPackLearningStatus(false);notify(payload.removed_count?"Transition Removed":"Transition Not Found",payload.removed_count?`${payload.removed_count} observations removed; all other learning was preserved.`:"No matching learned edge remains.",payload.removed_count?"success":"error")}
async function undoPackLearningTransition(){const payload=await api("/api/recognition/pack-learning/undo-transition",{method:"POST"});await loadPackLearningStatus(false);notify(payload.restored_count?"Transition Restored":"Undo Expired",payload.restored_count?`${payload.restored_count} observations restored.`:"The correction could no longer be restored.",payload.restored_count?"success":"error")}
async function exportPackLearningModel(){const payload=await api("/api/recognition/pack-learning/export"),model=payload.model||{},scope=model.scope||[],blob=new Blob([JSON.stringify(model,null,2)],{type:"application/json"}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=`rareiq-pack-learning-${String(scope[0]||"set")}-${String(scope[3]||"product")}.json`;link.click();URL.revokeObjectURL(link.href);notify("Learning Model Exported","The active product backup was downloaded.","success")}
async function importPackLearningModel(file){if(!file)return;try{const model=JSON.parse(await file.text()),preview=await api("/api/recognition/pack-learning/import-preview",{method:"POST",body:JSON.stringify({model})});if(!preview.compatible)throw new Error(preview.reason||"This backup is not compatible with the active product.");const scope=preview.scope||[],exported=Number(preview.exported_at)?new Date(Number(preview.exported_at)*1000).toLocaleString():"Unknown date",summary=[`Product: ${preview.product_label||scope[3]||"Unknown product"}`,`Set: ${scope[1]||scope[0]||"Unknown"}`,`Exported: ${exported}`,`Learned positions: ${Number(preview.positions)||0}`,`Transitions: ${Number(preview.transitions)||0}`,`Verified observations: ${Number(preview.observations)||0}`,`Learning state: ${preview.enabled===false?"Disabled":"Enabled"}`,`Integrity: ${preview.integrity_valid?"SHA-256 verified":"FAILED"}`,"", "Compatibility: Exact match", "RareIQ will save the current model locally before replacement.", "", "Replace the active product model with this backup?"].join("\n");if(!confirm(summary))return;const payload=await api("/api/recognition/pack-learning/import",{method:"POST",body:JSON.stringify({model})});await loadPackLearningStatus(false);notify("Learning Model Imported",`${Number(payload.imported_entries)||0} transition entries restored.${payload.backup_path?" Previous model backed up locally.":""}`,"success")}catch(error){notify("Learning Import Failed",error.message||String(error),"error")}finally{if($("packLearningImportFile"))$("packLearningImportFile").value=""}}
async function loadPackLearningBackups(){const payload=await api("/api/recognition/pack-learning/backups"),host=$("packLearningBackups"),backups=payload.backups||[];if(!host)return;host.hidden=false;host.innerHTML=backups.length?backups.map(item=>`<article data-compatible="${item.compatible?"true":"false"}"><span><b>${escapeHtml(String(item.product_label||"Pack product"))} · ${new Date(Number(item.exported_at||0)*1000).toLocaleString()}</b><small>${escapeHtml(String(item.reason||"recovery"))} · ${Number(item.positions)||0} positions · ${Number(item.observations)||0} observations · ${item.integrity_valid?"SHA-256 verified":"integrity failed"}</small></span><button type="button" data-restore-backup="${escapeHtml(item.backup_id||"")}" ${item.compatible?"":"disabled"}>Restore</button></article>`).join(""):'<p>No recovery snapshots for this product yet.</p>';host.querySelectorAll("[data-restore-backup]").forEach(button=>button.addEventListener("click",()=>restorePackLearningBackup(button.dataset.restoreBackup)))}
async function restorePackLearningBackup(backupId){if(!confirm("Restore this recovery snapshot? RareIQ will back up the current model first."))return;const payload=await api("/api/recognition/pack-learning/restore",{method:"POST",body:JSON.stringify({backup_id:backupId})});await loadPackLearningStatus(false);await loadPackLearningBackups();notify("Recovery Snapshot Restored",`${Number(payload.imported_entries)||0} transition entries restored.`,"success")}
function renderPackPredictionSummary(records=[]){const rows=$("packRunRows");if(!rows)return;let panel=$("packPredictionSummary");if(!panel){panel=document.createElement("section");panel.id="packPredictionSummary";panel.className="pack-prediction-summary";panel.setAttribute("aria-label","Predictive preload performance");panel.innerHTML='<span><small>Prediction hits</small><b id="packPredictionHits">0</b></span><span><small>Total saved</small><b id="packPredictionSaved">0 ms</b></span><span><small>Average / card</small><b id="packPredictionAverage">0 ms</b></span><span><small>Hit coverage</small><b id="packPredictionCoverage">0%</b></span><span><small>Predicted avg</small><b id="packPredictedSpeed">Collecting</b></span><span><small>Standard avg</small><b id="packStandardSpeed">Collecting</b></span><span class="comparison"><small>Measured difference</small><b id="packPredictionDifference">Collecting</b></span>';rows.before(panel);ensurePackLearningControls(rows)}const hits=records.reduce((sum,row)=>sum+Math.max(0,Number(row.predictionConsumed)||0),0),saved=records.reduce((sum,row)=>sum+Math.max(0,Number(row.predictionSaved)||0),0),average=records.length?saved/records.length:0,coverage=records.length?hits/records.length*100:0,comparison=packPredictionSpeedComparison(records);$("packPredictionHits").textContent=String(hits);$("packPredictionSaved").textContent=`${Math.round(saved)} ms`;$("packPredictionAverage").textContent=`${Math.round(average)} ms`;$("packPredictionCoverage").textContent=`${Math.round(coverage)}%`;$("packPredictedSpeed").textContent=comparison.predictedAverage===null?"Collecting":`${Math.round(comparison.predictedAverage)} ms`;$("packStandardSpeed").textContent=comparison.standardAverage===null?"Collecting":`${Math.round(comparison.standardAverage)} ms`;$("packPredictionDifference").textContent=!comparison.ready?"Collecting":comparison.difference>=0?`${Math.round(comparison.difference)} ms faster · ${Math.round(comparison.improvement)}%`:`${Math.abs(Math.round(comparison.difference))} ms slower`;panel.dataset.state=hits?"active":"idle";panel.dataset.comparison=comparison.ready?(comparison.difference>=0?"faster":"slower"):"collecting";panel.setAttribute("aria-label",`${hits} prediction hits; ${Math.round(saved)} milliseconds saved total; ${comparison.ready?`${Math.abs(Math.round(comparison.difference))} milliseconds ${comparison.difference>=0?"faster":"slower"} measured recognition time`:"collecting predicted and standard comparison samples"}`)}
function renderPackSpeedRun(){const records=packSpeedRun.records||[],values=records.map(row=>Number(row.total)).filter(Number.isFinite),count=records.length,average=values.length?Math.round(values.reduce((sum,value)=>sum+value,0)/values.length):null,subsecond=values.length?Math.round(values.filter(value=>value<1000).length/values.length*100):null,fastest=values.length?Math.min(...values):null,slowest=values.length?Math.max(...values):null,started=Date.parse(packSpeedRun.startedAt||records[0]?.at||""),finished=Date.parse(records.at(-1)?.at||""),elapsed=Number.isFinite(started)&&Number.isFinite(finished)?Math.max(0,finished-started):null,elapsedLabel=elapsed===null?"—":elapsed>=60000?`${Math.floor(elapsed/60000)}m ${Math.floor(elapsed%60000/1000)}s`:`${Math.max(0.1,elapsed/1000).toFixed(1)}s`;if($("packRunCards"))$("packRunCards").textContent=String(count);if($("packRunAverage"))$("packRunAverage").textContent=average===null?"—":`${average}ms`;if($("packRunSubsecond"))$("packRunSubsecond").textContent=subsecond===null?"—":`${subsecond}%`;if($("packSpeedRun"))$("packSpeedRun").dataset.health=!count?"idle":subsecond>=90?"fast":subsecond>=60?"mixed":"slow";if($("packRunSummary"))$("packRunSummary").textContent=count?`${count} cards · ${average}ms average · ${subsecond}% under target`:"No completed cards yet";if($("packSessionElapsed"))$("packSessionElapsed").textContent=elapsedLabel;if($("packSessionFastest"))$("packSessionFastest").textContent=fastest===null?"—":`${Math.round(fastest)} ms`;if($("packSessionSlowest"))$("packSessionSlowest").textContent=slowest===null?"—":`${Math.round(slowest)} ms`;if($("packSessionCompleted"))$("packSessionCompleted").textContent=`${count} card${count===1?"":"s"}`;renderPackRunCoach(records);renderPackPredictionSummary(records);const rows=$("packRunRows");if(rows)rows.innerHTML=records.length?records.slice(-12).reverse().map((row,index)=>`<article data-health="${Number(row.total)<1000?"fast":"slow"}" data-cache="${escapeHtml(row.cacheState||"unknown")}"><i>${records.length-index}</i><div><b>${escapeHtml(row.name||"Recognized card")}</b><span>${escapeHtml([row.number,row.set].filter(Boolean).join(" · ")||"Identity verified")}</span><small class="pack-cache-result">${escapeHtml(row.cacheState?`${row.cacheState} cache · ${Number(row.cacheHits)||0} hits · ${Math.round(Number(row.cacheSaved)||0)}ms saved`:"cache data pending")}${row.predictionConsumed?escapeHtml(` · prediction hit · ${Math.round(Number(row.predictionSaved)||0)}ms saved`):""}</small></div><strong>${Math.round(Number(row.total)||0)}ms</strong><em>${escapeHtml(row.bottleneck||"unknown")}</em></article>`).join(""):'<p>No completed cards in this run.</p>'}
function packRunCacheSample(context={}){const timing=context?.snapshot?.artwork_index?.status?.reference_cache_timing||context?.raw?.artwork_index?.status?.reference_cache_timing||{},current={hits:Math.max(0,(Number(timing.image_hits)||0)+(Number(timing.feature_hits)||0)),misses:Math.max(0,(Number(timing.image_misses)||0)+(Number(timing.feature_misses)||0)),saved:Math.max(0,Number(timing.estimated_saved_ms)||0)},previous=(packSpeedRun.records||[]).at(-1)?.cacheTotals||{hits:0,misses:0,saved:0},delta=(value,before)=>value>=Number(before||0)?value-Number(before||0):value,hits=delta(current.hits,previous.hits),misses=delta(current.misses,previous.misses),saved=delta(current.saved,previous.saved),state=hits>0&&misses===0?"warm":misses>0&&hits===0?"cold":hits>0&&misses>0?"mixed":"idle";return{cacheState:state,cacheHits:hits,cacheMisses:misses,cacheSaved:saved,cacheTotals:current}}
function packRunPredictionSample(context={}){const stats=context?.snapshot?.catalog?.prediction_prefetch||context?.raw?.catalog?.prediction_prefetch||{},current={consumed:Math.max(0,Number(stats.consumed)||0),saved:Math.max(0,Number(stats.estimated_saved_ms)||0)},previous=(packSpeedRun.records||[]).at(-1)?.predictionTotals||{consumed:0,saved:0},delta=(value,before)=>value>=Number(before||0)?value-Number(before||0):value,consumed=delta(current.consumed,previous.consumed),saved=delta(current.saved,previous.saved);return{predictionConsumed:consumed,predictionSaved:saved,predictionTotals:current}}
function recordPackSpeedSuccess(context={}){const timings=context?.snapshot?.stage_timings||context?.raw?.stage_timings||{},latency=Number(timings.total_ms??context?.snapshot?.last_latency_ms??context?.raw?.last_latency_ms),card=context?.card||context?.snapshot?.primary_candidate||{},reveal=context?.packReveal||{},cache=packRunCacheSample(context),prediction=packRunPredictionSample(context),at=new Date().toISOString(),marketValue=reveal.market_value!==null&&reveal.market_value!==undefined&&reveal.market_value!==""&&Number.isFinite(Number(reveal.market_value))?Number(reveal.market_value):null;if(!packSpeedRun.startedAt)packSpeedRun.startedAt=at;if(Number(context.expectedCards)>0)packSpeedRun.expectedCards=Math.max(1,Number(context.expectedCards));packSpeedRun.records.push({name:card.english_name||card.name||card.printed_name||reveal.card_name||"Recognized card",number:card.collector_number||card.card_number||reveal.collector_number||"",set:card.set_name||"",rarity:reveal.rarity||card.rarity||"Unknown",hitTier:reveal.hit_tier||card.hit_tier||"standard",marketValue,referenceImage:reveal.reference_image_url||card.reference_image_url||card.image_url||"",total:Number.isFinite(latency)?Math.max(0,latency):0,bottleneck:packRunStage(timings),...cache,...prediction,at});packSpeedRun.records=packSpeedRun.records.slice(-100);savePackSpeedRun();renderPackSpeedRun()}
function setPackRunDetail(open){if($("packRunDetail"))$("packRunDetail").hidden=!open;if($("packRunOpen"))$("packRunOpen").setAttribute("aria-expanded",open?"true":"false")}
function resetPackSpeedRun(){packSpeedRun={records:[],startedAt:null};savePackSpeedRun();renderPackSpeedRun();notify("New Pack Started","Pack Speed statistics are ready for a fresh opening.","success")}

const renderPackSpeedRunCore=renderPackSpeedRun;
renderPackSpeedRun=function(){renderPackSpeedRunCore();renderPackSessionComparison();renderPackHistoryChart();renderPackPullSummary();renderPackRecoveryMetrics();renderPackRecoveryHistory();renderPackSessionHealth();renderPackTuningHistory()};
resetPackSpeedRun=function(){const archived=archivePackSpeedRun();packSpeedRun={records:[],startedAt:null,expectedCards:0};if(archived)armNextPackGate();savePackSpeedRun();renderPackSpeedRun();if(archived)schedulePackRecap();notify(archived?"Pack Finished":"New Pack Started",archived?`${archived.summary.cards} cards archived · remove the final card to rearm.`:"Pack Speed statistics are ready for a fresh opening.","success")};

function autoAddVerifiedEnabled(){
  try{return localStorage.getItem(AUTO_ADD_VERIFIED_KEY)==="true"}catch{return false}
}

function renderAutoAddVerified(){
  const input=$("autoAddVerifiedEnabled");
  if(input)input.checked=autoAddVerifiedEnabled();
  document.body.dataset.autoAddVerified=autoAddVerifiedEnabled()?"on":"off";
  document.body.dataset.packSpeed=autoAddVerifiedEnabled()?"on":"off";
  renderPackSpeedAutomationState(window.__rareiqCardContext||{});
}

function renderPackSpeedAutomationState(context={}){
  const host=document.querySelector(".auto-add-verified-control"),detail=host?.querySelector("small");
  if(!host||!detail)return;
  const pack=($(`setContextMode`)?.value||"auto")==="pack",enabled=autoAddVerifiedEnabled(),handoff=String(document.body.dataset.cardHandoff||"");
  const recovery=["watching","retrying","submitted","attention"].includes(packRecoveryState.status)?packRecoveryState.status:"";
  const state=!enabled?"manual":pack&&packRearmGate.active?"pack-complete":recognitionDecisionInFlight?"adding":["approved","rejected"].includes(handoff)?"remove":handoff==="ready"?"ready":context?.verified===true?"verified":recovery||"armed";
  const labels={manual:"Manual approval",armed:"Auto armed",verified:"Verified · adding",adding:"Adding card…",remove:"Remove card",ready:"Ready for next",watching:"Scanning · recovery armed",retrying:"Stall detected · retrying",submitted:"Recovery scan submitted",attention:"Needs operator review","pack-complete":"Pack complete · remove card"};
  host.dataset.automationState=state;
  detail.textContent=labels[state]||labels.armed;
}

async function observePackSpeedStallRecovery(context={}){
  if(!autoAddVerifiedEnabled()||packRearmGate.active||recognitionDecisionInFlight||["approved","rejected"].includes(document.body.dataset.cardHandoff||""))return;
  const snapshot=context?.snapshot||{},present=snapshot?.card_present===true||snapshot?.vision?.visible===true||snapshot?.vision?.vision?.visible===true,phase=String(snapshot?.phase||snapshot?.continuous_state||snapshot?.continuous?.state||"").toUpperCase(),generation=Number(snapshot?.generation);
  if(context?.verified===true||!present||!["STABLE","RECOGNIZING"].includes(phase)||!Number.isFinite(generation)){
    if(context?.verified===true&&packRecoveryState.attempted&&!packRecoveryState.recorded){recordPackRecoveryMetric("recovered",packRecoveryState.generation,Date.now()-packRecoveryState.attemptedAt,context);packRecoveryState.recorded=true}
    if(!present||context?.verified===true)packRecoveryState={generation:null,startedAt:0,attempted:false,attemptedAt:0,recorded:false,status:"idle"};
    return;
  }
  if(packRecoveryState.generation!==generation){packRecoveryState={generation,startedAt:Date.now(),attempted:false,attemptedAt:0,recorded:false,status:"watching"};renderPackSpeedAutomationState(context);return}
  if(packRecoveryState.attempted||Date.now()-packRecoveryState.startedAt<packRecoveryThresholdMs())return;
  packRecoveryState={...packRecoveryState,attempted:true,attemptedAt:Date.now(),recorded:false,status:"retrying"};
  renderPackSpeedAutomationState(context);
  try{
    const result=await api("/api/camera/capture",{method:"POST",body:"{}"});
    packRecoveryState.status=result?.ok&&(result?.job_accepted||result?.queued)?"submitted":"attention";
    if(packRecoveryState.status==="attention"&&!packRecoveryState.recorded){recordPackRecoveryMetric("failed",generation,Date.now()-packRecoveryState.attemptedAt,window.__rareiqCardContext||context);packRecoveryState.recorded=true}
  }catch(_error){packRecoveryState.status="attention";if(!packRecoveryState.recorded){recordPackRecoveryMetric("failed",generation,Date.now()-packRecoveryState.attemptedAt,window.__rareiqCardContext||context);packRecoveryState.recorded=true}}
  renderPackSpeedAutomationState(window.__rareiqCardContext||context);
}

async function maybeAutoAddVerified(context){
  if(!autoAddVerifiedEnabled()||context?.verified!==true||recognitionDecisionInFlight)return null;
  if(packRearmGate.active){renderCardRemovalProgress(0,"Pack complete · remove final card to rearm",true);return null}
  if(["approved","rejected"].includes(document.body.dataset.cardHandoff))return null;
  const stateId=String(context?.snapshot?.state_id||"");
  if(!stateId||stateId===lastAutoAddStateId)return null;
  lastAutoAddStateId=stateId;
  renderPackSpeedAutomationState(context);
  const result=await runRecognitionDecision({
    buttonId:"approveButton",
    url:`/api/session/auto-confirm-recognition?state_id=${encodeURIComponent(stateId)}`,
    pendingLabel:"Auto-adding…",
    successTitle:"Card Auto-added",
    successDetail:"Verified identity added to the active session.",
    activityTitle:"Card Auto-added",
    quietReasons:["stale_recognition_state"],
    silentSuccess:true,
  });
  if(result){const expectedCards=Number(result.reveal_sequence?.expected_cards)||0,packReveal=result.reveal_sequence?.current||{};recordPackSpeedSuccess({...context,expectedCards,packReveal});await handleApprovedInventory(result).catch(error=>notify("Inventory Not Created",error.message||String(error),"error"));advancePackSessionCard(result.reveal_sequence);maybeCompletePackSpeedRun(result);beginCardHandoff("approved")}
  return result;
}

async function runRecognitionDecision({buttonId,url,pendingLabel,successTitle,successDetail,activityTitle,quietReasons=[],silentSuccess=false}){
  const button=$(buttonId);
  if(!button||button.disabled||recognitionDecisionInFlight) return null;
  const originalLabel=button.textContent;
  recognitionDecisionInFlight=true;
  ["approveButton","rejectButton","decisionApproveButton","decisionRejectButton"].forEach(id=>{
    const actionButton=$(id);
    if(actionButton) actionButton.disabled=true;
  });
  button.disabled=true;
  button.textContent=pendingLabel;
  try{
    const response=await fetch(url,{method:"POST"});
    const payload=await response.json().catch(()=>({}));
    if(!response.ok||payload.ok!==true){
      if(quietReasons.includes(payload.reason))return null;
      throw new Error(payload.error||payload.message||"The card action could not be completed.");
    }
    applyAuthoritativeSession(payload.session);
    if(!silentSuccess)notify(successTitle,successDetail,"success");
    addActivity(activityTitle,successDetail);
    return payload;
  }catch(error){
    const detail=error instanceof Error?error.message:String(error);
    notify("Card Action Failed",detail,"error");
    addActivity("Card Action Failed",detail);
    return null;
  }finally{
    recognitionDecisionInFlight=false;
    button.textContent=originalLabel;
    const context=window.__rareiqCardContext;
    const actionable=context?.verified===true;
    ["approveButton","rejectButton","decisionApproveButton","decisionRejectButton"].forEach(id=>{
      const actionButton=$(id);
      if(actionButton) actionButton.disabled=!actionable;
    });
    renderPackSpeedAutomationState(context||{});
  }
}

async function operatorApprove(){
  const result=await runRecognitionDecision({
    buttonId:"approveButton",
    url:"/api/session/confirm-recognition",
    pendingLabel:"Approving…",
    successTitle:"Card Approved",
    successDetail:"Added to the active session.",
    activityTitle:"Card Approved",
  });
  if(result){await handleApprovedInventory(result).catch(error=>notify("Inventory Not Created",error.message||String(error),"error"));advancePackSessionCard(result.reveal_sequence);beginCardHandoff("approved");}
  return result;
}

async function operatorReject(){
  const result=await runRecognitionDecision({
    buttonId:"rejectButton",
    url:"/api/session/reject-recognition",
    pendingLabel:"Rejecting…",
    successTitle:"Card Rejected",
    successDetail:"Recorded as rejected. Use Next / Clear when the card is removed.",
    activityTitle:"Card Rejected",
  });
  if(result) beginCardHandoff("rejected");
  return result;
}

let cardHandoffTimer=0;
let cardRemovalMissingPolls=0;
let cardRemovalMissingSince=0;
let cardRemovalClearPending=false;
let cardHandoffStartedAt=0;
let cardHandoffGeneration=null;
let cardHandoffStateId="";
let cardEntryCueTimer=0;
let lastObservedCardPresent=null;
const CARD_REMOVAL_SETTINGS_KEY="rareiq.automaticCardRemoval.v1";
const CARD_HANDOFF_TIMING_KEY="rareiq.cardHandoffTimings.v1";
const CARD_REMOVAL_PRESETS={adaptive:{polls:3,ms:650,label:"Adaptive · Normal"},safe:{polls:5,ms:1200,label:"Safe"},normal:{polls:3,ms:650,label:"Normal"},fast:{polls:2,ms:300,label:"Fast"}};
let cardRemovalSettings=loadCardRemovalSettings();
function loadCardRemovalSettings(){try{const saved=JSON.parse(localStorage.getItem(CARD_REMOVAL_SETTINGS_KEY)||"null")||{};return{enabled:saved.enabled!==false,sensitivity:CARD_REMOVAL_PRESETS[saved.sensitivity]?saved.sensitivity:"adaptive",soundEnabled:saved.soundEnabled===true}}catch{return{enabled:true,sensitivity:"adaptive",soundEnabled:false}}}
function saveCardRemovalSettings(){try{localStorage.setItem(CARD_REMOVAL_SETTINGS_KEY,JSON.stringify(cardRemovalSettings))}catch{}}
function loadCardHandoffTimings(){try{const rows=JSON.parse(localStorage.getItem(CARD_HANDOFF_TIMING_KEY)||"[]");return Array.isArray(rows)?rows.filter(row=>Number.isFinite(Number(row?.elapsed))).slice(-30):[]}catch{return[]}}
function cardHandoffTimingStats(){const rows=loadCardHandoffTimings(),values=rows.map(row=>Number(row.elapsed)).sort((a,b)=>a-b),median=values.length?values[Math.floor(values.length/2)]:null,average=values.length?Math.round(values.reduce((sum,value)=>sum+value,0)/values.length):null;return{count:values.length,median,average}}
function refreshAdaptiveCardRemovalPreset(){const stats=cardHandoffTimingStats(),source=stats.count<4?CARD_REMOVAL_PRESETS.normal:stats.median<=800?CARD_REMOVAL_PRESETS.fast:stats.median<=1800?CARD_REMOVAL_PRESETS.normal:CARD_REMOVAL_PRESETS.safe;CARD_REMOVAL_PRESETS.adaptive={...source,label:`Adaptive · ${source.label}`};return stats}
function recordCardHandoffTiming(elapsed,method="removal"){const value=Math.round(Number(elapsed));if(!Number.isFinite(value)||value<150||value>15000)return;const rows=loadCardHandoffTimings();rows.push({elapsed:value,method,at:Date.now()});try{localStorage.setItem(CARD_HANDOFF_TIMING_KEY,JSON.stringify(rows.slice(-30)))}catch{}refreshAdaptiveCardRemovalPreset();renderCardRemovalSettings()}
function renderCardRemovalSettings(){const stats=refreshAdaptiveCardRemovalPreset(),preset=CARD_REMOVAL_PRESETS[cardRemovalSettings.sensitivity];if($("automaticCardRemovalEnabled"))$("automaticCardRemovalEnabled").checked=cardRemovalSettings.enabled;if($("automaticCardRemovalSensitivity"))$("automaticCardRemovalSensitivity").value=cardRemovalSettings.sensitivity;if($("cardHandoffSoundEnabled"))$("cardHandoffSoundEnabled").checked=cardRemovalSettings.soundEnabled;if($("automaticCardRemovalSummary"))$("automaticCardRemovalSummary").textContent=cardRemovalSettings.enabled?`${preset.label} · ${preset.polls} empty polls / ${preset.ms}ms${stats.count?` · ${stats.count} turns · ${stats.average}ms avg`:" · learning starts after 4 turns"}`:"Off · use Next / Clear manually";document.body.dataset.autoCardRemoval=cardRemovalSettings.enabled?"on":"off"}
function playCardHandoffReadySound(){
  if(!cardRemovalSettings.soundEnabled) return;
  const AudioContextClass=window.AudioContext||window.webkitAudioContext;
  if(!AudioContextClass) return;
  try{
    const context=new AudioContextClass();
    const play=()=>{
      const start=context.currentTime;
      const gain=context.createGain();
      const oscillator=context.createOscillator();
      oscillator.type="sine";
      oscillator.frequency.setValueAtTime(660,start);
      oscillator.frequency.exponentialRampToValueAtTime(880,start+.12);
      gain.gain.setValueAtTime(.0001,start);
      gain.gain.exponentialRampToValueAtTime(.045,start+.018);
      gain.gain.exponentialRampToValueAtTime(.0001,start+.16);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start+.17);
      oscillator.addEventListener("ended",()=>context.close().catch(()=>{}),{once:true});
    };
    if(context.state==="suspended") context.resume().then(play).catch(()=>context.close().catch(()=>{}));
    else play();
  }catch{}
}
function renderCardRemovalProgress(percent=0,label="Waiting for removal",visible=false){const progress=$("cardRemovalProgress"),value=Math.max(0,Math.min(100,Math.round(Number(percent)||0)));if(!progress)return;progress.hidden=!visible;progress.setAttribute("aria-valuenow",String(value));if($("cardRemovalProgressLabel"))$("cardRemovalProgressLabel").textContent=label;if($("cardRemovalProgressBar"))$("cardRemovalProgressBar").style.width=`${value}%`}
function observeCardEntryFeedback(snapshot={}){
  const present=snapshot?.card_present===true||snapshot?.vision?.visible===true||snapshot?.vision?.vision?.visible===true;
  const entered=present&&lastObservedCardPresent===false;
  lastObservedCardPresent=present;
  if(!entered||["approved","rejected"].includes(document.body.dataset.cardHandoff)) return;
  clearTimeout(cardEntryCueTimer);
  clearTimeout(cardHandoffTimer);
  delete document.body.dataset.cardHandoff;
  document.body.dataset.cardEntry="detected";
  renderCardRemovalProgress(0,"Waiting for removal",false);
  cardEntryCueTimer=setTimeout(()=>delete document.body.dataset.cardEntry,720);
}
function beginCardHandoff(outcome="cleared"){
  clearTimeout(cardHandoffTimer);
  cardRemovalMissingPolls=0;
  cardRemovalMissingSince=0;
  cardHandoffStartedAt=Date.now();
  cardHandoffGeneration=Number.isFinite(Number(window.__rareiqCardContext?.snapshot?.generation))?Number(window.__rareiqCardContext.snapshot.generation):null;
  cardHandoffStateId=String(window.__rareiqCardContext?.snapshot?.state_id||"");
  renderCardRemovalProgress(0,cardRemovalSettings.enabled?"Auto-clear armed · remove card":"Remove card · use Next when ready",true);
  document.body.dataset.cardHandoff=outcome;
  renderPackSpeedAutomationState(window.__rareiqCardContext||{});
  if($("decisionVerdict")) $("decisionVerdict").textContent=outcome==="approved"?"CARD APPROVED":outcome==="rejected"?"CARD REJECTED":"CLEARING CARD";
  if($("decisionCardName")) $("decisionCardName").textContent=outcome==="cleared"?"Preparing next scan":"Remove card from the scan zone";
  if($("aiState")) $("aiState").textContent=outcome==="cleared"?"NEXT CARD":"REMOVE CARD";
  if($("aiDetail")) $("aiDetail").textContent=outcome==="cleared"?"Present the next card when ready.":"RareIQ will hold this result until the card leaves view.";
}

function observeCompletedCardRemoval(snapshot={}){
  const handoff=document.body.dataset.cardHandoff;
  const present=snapshot?.card_present===true||snapshot?.vision?.visible===true||snapshot?.vision?.vision?.visible===true;
  const phase=String(snapshot?.phase||snapshot?.continuous_state||snapshot?.continuous?.state||"").toUpperCase();
  if(packRearmGate.active&&!present&&phase==="EMPTY")clearNextPackGate();
  if(!cardRemovalSettings.enabled||!["approved","rejected"].includes(handoff)||cardRemovalClearPending) return;
  const generation=Number(snapshot?.generation);
  const stateId=String(snapshot?.state_id||"");
  const replacementStateConfirmed=Boolean(stateId)&&stateId!==cardHandoffStateId;
  const directReplacement=present&&replacementStateConfirmed&&cardHandoffGeneration!==null&&Number.isFinite(generation)&&generation>cardHandoffGeneration&&["CHANGING","ACQUIRING","STABLE","RECOGNIZING"].includes(phase);
  if(directReplacement){
    const elapsed=Math.max(0,Date.now()-cardHandoffStartedAt);
    resetRecognitionPresentation("verified_direct_replacement");
    completeCardHandoff(elapsed,"replacement");
    cardHandoffGeneration=generation;
    cardHandoffStateId=stateId;
    cardRemovalMissingPolls=0;
    cardRemovalMissingSince=0;
    return;
  }
  if(!present&&phase==="EMPTY"){
    cardRemovalClearPending=true;
    const elapsed=Math.max(0,Date.now()-cardHandoffStartedAt);
    resetRecognitionPresentation("physical_removal_confirmed");
    completeCardHandoff(elapsed);
    cardRemovalClearPending=false;
    cardRemovalMissingPolls=0;
    cardRemovalMissingSince=0;
    return;
  }
  if(present){
    cardRemovalMissingPolls=0;
    cardRemovalMissingSince=0;
    renderCardRemovalProgress(0,"Card still visible · waiting for removal",true);
    return;
  }
  const now=Date.now();
  if(!cardRemovalMissingSince) cardRemovalMissingSince=now;
  cardRemovalMissingPolls+=1;
  const preset=CARD_REMOVAL_PRESETS[cardRemovalSettings.sensitivity];
  const pollProgress=cardRemovalMissingPolls/preset.polls;
  const timeProgress=(now-cardRemovalMissingSince)/preset.ms;
  const progress=Math.min(1,pollProgress,timeProgress);
  renderCardRemovalProgress(progress*100,`Confirming removal · ${Math.min(cardRemovalMissingPolls,preset.polls)}/${preset.polls} checks`,true);
  const stable=cardRemovalMissingPolls>=preset.polls&&now-cardRemovalMissingSince>=preset.ms;
  if(!stable) return;
  cardRemovalClearPending=true;
  requestNextRecognition()
    .then(()=>notify("Next Card Ready","Completed card removed · recognition re-armed.","success"))
    .catch(error=>{
      delete document.body.dataset.cardHandoff;
      syncResultDecisionStrip();
      console.error("automatic_card_removal_clear_failed",error);
    })
    .finally(()=>{
      cardRemovalClearPending=false;
      cardRemovalMissingPolls=0;
      cardRemovalMissingSince=0;
    });
}

function completeCardHandoff(elapsedMs=null,method="removal"){
  document.body.dataset.cardHandoff="ready";
  renderPackSpeedAutomationState(window.__rareiqCardContext||{});
  const timing=Number.isFinite(elapsedMs)?` · ${Math.round(elapsedMs)}ms`:"";
  if(method==="replacement")renderCardRemovalProgress(100,`New card confirmed${timing} · recognition continuing`,true);
  else renderCardRemovalProgress(100,`Removal confirmed${timing} · ready for next`,true);
  if($("decisionVerdict")) $("decisionVerdict").textContent="READY FOR NEXT";
  if($("decisionCardName")) $("decisionCardName").textContent="Present next card";
  if($("aiState")) $("aiState").textContent="READY";
  if($("aiDetail")) $("aiDetail").textContent=method==="replacement"?"New card acquired. Recognition is continuing automatically.":"Place the next card inside the scan zone.";
  playCardHandoffReadySound();
  if(Number.isFinite(elapsedMs))recordCardHandoffTiming(elapsedMs,method);
  cardHandoffTimer=setTimeout(()=>{delete document.body.dataset.cardHandoff;renderCardRemovalProgress(0,"Waiting for removal",false);syncResultDecisionStrip()},900);
}

function operatorDetails(){
  notify("Card Details","Detailed card intelligence view is queued.","info");
  addActivity("Details Requested","Opening full card intelligence.");
}

function isTypingTarget(target){
  const tag=(target?.tagName||"").toLowerCase();
  return tag==="input"||tag==="textarea"||tag==="select"||target?.isContentEditable;
}

document.addEventListener("keydown",event=>{
  if(isTypingTarget(event.target)) return;

  if(event.altKey&&document.body.dataset.ui4Workspace==="live"&&["1","2","3"].includes(event.key)){
    event.preventDefault();
    const preset={"1":"intelligence","2":"balanced","3":"monitor"}[event.key];
    applyWorkspaceLayoutPreset(preset);
    announceWorkspaceLayoutPreset(preset);
  }else if(event.key===" "){
    event.preventDefault();
    captureCamera();
  }else if(event.key.toLowerCase()==="a"){
    operatorApprove();
  }else if(event.key.toLowerCase()==="r"){
    operatorReject();
  }else if(event.key.toLowerCase()==="d"){
    operatorDetails();
  }else if(event.key.toLowerCase()==="p"){
    openCameraPopout();
  }else if(event.key.toLowerCase()==="z"){
    toggleCardZoom();
  }else if(event.key.toLowerCase()==="f"){
    openCameraPopout();
  }else if(event.key==="?" || (event.shiftKey&&event.key==="/")){
    toggleShortcutOverlay();
  }else if(event.key==="Escape"){
    resetUI4PresentationSurfaces();
    toggleShortcutOverlay(false);
    setRecognitionLatencyReportOpen(false);
  }
});

function applyCardZoom(enabled){
  cardZoomEnabled=Boolean(enabled);
  const workspace=document.querySelector(".camera-workspace");
  const toggle=$("cameraZoomToggle");
  if(workspace) workspace.classList.toggle("zoom-card",cardZoomEnabled);
  if(toggle) toggle.classList.toggle("active",cardZoomEnabled);
  localStorage.setItem("rareiq.cardZoom",cardZoomEnabled?"on":"off");
}

function toggleCardZoom(){
  applyCardZoom(!cardZoomEnabled);
  addActivity(
    cardZoomEnabled?"Card Zoom Enabled":"Card Zoom Disabled",
    cardZoomEnabled
      ?"Camera view enlarged for close card inspection."
      :"Camera returned to normal framing."
  );
}

function updateResolutionBadge(vision={}){
  const actual=vision.actual_resolution;
  const requested=vision.requested_resolution;
  const badge=$("resolutionBadge");
  if(!badge) return;

  if(Array.isArray(actual)&&actual.length>=2){
    const fallback=Boolean(vision.resolution_fallback);
    badge.textContent=`${actual[0]}x${actual[1]}${fallback?" FALLBACK":""}`;
    badge.classList.toggle("fallback",fallback);
    badge.title=fallback&&Array.isArray(requested)
      ? `Camera requested ${requested[0]}x${requested[1]} and supplied ${actual[0]}x${actual[1]}.`
      : `Camera input ${actual[0]}x${actual[1]}.`;
  }else{
    badge.textContent="CAMERA --";
    badge.classList.remove("fallback");
    badge.title="Waiting for the first camera frame.";
  }
}

function alignScanZone(vision={}){
  const workspace=document.querySelector(".camera-workspace");
  const stage=workspace?.querySelector(".camera-stage-inner");
  const feed=$("cameraFeed");
  const zone=$("scanZone");
  if(!workspace||!stage||!feed||!zone) return;

  const actual=vision.actual_resolution||[];
  const sourceWidth=Number(feed.naturalWidth||actual[0]||0);
  const sourceHeight=Number(feed.naturalHeight||actual[1]||0);
  const workspaceWidth=stage.clientWidth;
  const workspaceHeight=stage.clientHeight;
  if(!sourceWidth||!sourceHeight||!workspaceWidth||!workspaceHeight) return;

  const zoneValues=vision.scan_zone||{
    left:0.10,top:0.08,right:0.90,bottom:0.92
  };
  const fit=cameraFitMode==="fill"?"cover":"contain";
  const scale=fit==="cover"
    ? Math.max(workspaceWidth/sourceWidth,workspaceHeight/sourceHeight)
    : Math.min(workspaceWidth/sourceWidth,workspaceHeight/sourceHeight);
  const renderedWidth=sourceWidth*scale;
  const renderedHeight=sourceHeight*scale;
  const offsetX=stage.offsetLeft+(workspaceWidth-renderedWidth)/2;
  const offsetY=stage.offsetTop+(workspaceHeight-renderedHeight)/2;
  workspace.style.setProperty("--camera-render-left",`${offsetX}px`);
  workspace.style.setProperty("--camera-render-top",`${offsetY}px`);

  zone.style.left=`${offsetX+renderedWidth*Number(zoneValues.left)}px`;
  zone.style.top=`${offsetY+renderedHeight*Number(zoneValues.top)}px`;
  zone.style.width=`${renderedWidth*(Number(zoneValues.right)-Number(zoneValues.left))}px`;
  zone.style.height=`${renderedHeight*(Number(zoneValues.bottom)-Number(zoneValues.top))}px`;
  zone.style.right="auto";
  zone.style.bottom="auto";
  applyStudioXViewerPresentation(
    window.__rareiqCardContext||null,
    vision
  );
}

function applyCameraFit(mode){
  const valid=["adaptive","fill","frame"];
  cameraFitMode=valid.includes(mode)?mode:"adaptive";

  const workspace=document.querySelector(".camera-workspace");
  const label=$("cameraFitLabel");
  const toggle=$("cameraFitToggle");

  if(workspace){
    workspace.classList.remove("fit-adaptive","fit-fill","fit-frame","full-frame");
    workspace.classList.add(`fit-${cameraFitMode}`);
  }

  const names={
    adaptive:"ADAPTIVE",
    fill:"FILL CROP",
    frame:"FULL FRAME"
  };
  if(label) label.textContent=names[cameraFitMode];
  if(toggle) toggle.classList.toggle("active",cameraFitMode==="adaptive");

  localStorage.setItem("rareiq.cameraFitMode",cameraFitMode);
  alignScanZone(window.__rareiqVisionTelemetry||{});
}

function cycleCameraFit(){
  const order=["adaptive","fill","frame"];
  const index=order.indexOf(cameraFitMode);
  applyCameraFit(order[(index+1)%order.length]);

  const descriptions={
    adaptive:"Complete image preserved with responsive safe framing.",
    fill:"Video fills the viewport and may crop the outer edges.",
    frame:"Complete camera image shown with strict containment."
  };
  addActivity(
    `${$("cameraFitLabel").textContent} View`,
    descriptions[cameraFitMode]
  );
}

function setStateChip(id,state,label){
  const chip=$(id);
  if(!chip) return;
  chip.classList.remove("on","working","warning","error");
  if(state) chip.classList.add(state);
  const value=chip.querySelector("b");
  if(value) value.textContent=label;
}

function applyRecognitionPresentation(presentation){
  const panel=$("recognitionStatePanel");
  const label=$("recognitionStateLabel");
  const placeholder=$("cardPlaceholder");
  const key=presentation?.key||"ready";
  document.body.dataset.recognitionPresentation=key;
  const title=presentation?.title||"READY";
  const detail=presentation?.detail||"";
  const confidence=normalize(presentation?.confidence||0);
  const legacyState=
    key==="exact-match" ? "matched" :
    key==="error" ? "error" :
    key==="ready" ? "idle" :
    "searching";
  clearTimeout(cardPlaceholderResetTimer);
  if(placeholder){
    placeholder.classList.remove(
      "state-waiting","state-searching","state-matched","state-error"
    );
    placeholder.classList.add(
      key==="exact-match" ? "state-matched" :
      key==="error" ? "state-error" :
      key==="ready" ? "state-waiting" :
      "state-searching"
    );
    placeholder.dataset.recognitionState=key;
  }
  if($("cardPlaceholderTitle")){
    $("cardPlaceholderTitle").textContent=presentation?.placeholderTitle||title;
  }
  if($("cardPlaceholderDetail")){
    $("cardPlaceholderDetail").textContent=presentation?.placeholderDetail||detail;
  }
  if($("aiState")) $("aiState").textContent=title;
  if($("aiDetail")) $("aiDetail").textContent=detail;
  if($("confidence")) $("confidence").textContent=`${Math.round(confidence*100)}%`;
  if($("cardStatus")) $("cardStatus").textContent=title;
  if($("cameraFeedStateLabel")) $("cameraFeedStateLabel").textContent=title;
  if($("unifiedScanStatus")){
    $("unifiedScanStatus").dataset.state=key;
    $("unifiedScanStatus").dataset.presentation=key;
  }
  const progressIndex={
    ready:0,
    detecting:1,
    scanning:1,
    "candidate-found":2,
    verifying:2,
    "review-needed":2,
    "exact-match":3,
    error:0,
  }[key]??0;
  document.querySelectorAll("[data-recognition-stage]").forEach((stage,index)=>{
    stage.classList.toggle("complete",index<progressIndex);
    stage.classList.toggle("current",index===progressIndex);
    if(index===progressIndex){
      stage.setAttribute("aria-current","step");
    }else{
      stage.removeAttribute("aria-current");
    }
  });
  const detailNode=$("recognitionStateDetail");
  if(panel){
    panel.classList.remove("idle","searching","matched","captured","error");
    panel.classList.add(legacyState);
  }
  const cameraWorkspace=document.querySelector(".camera-workspace");
  if(cameraWorkspace){
    cameraWorkspace.classList.remove(
      "state-idle","state-searching","state-matched","state-captured","state-error"
    );
    cameraWorkspace.classList.add(`state-${legacyState}`);
    cameraWorkspace.dataset.recognitionState=key;
  }
  if(label) label.textContent=title;
  if(detailNode) detailNode.textContent=detail;
  const aiChipState =
    legacyState==="searching" ? "working" :
    legacyState==="matched" ? "on" :
    legacyState==="error" ? "error" : "";
  setStateChip("aiStateChip",aiChipState,title);
  updateAiPulse(legacyState);
  setCoreState(key);
}

function setRecognitionState(state,detail=""){
  const legacyPresentations={
    idle:{key:"ready",title:"READY",placeholderTitle:"Ready for Card"},
    searching:{key:"scanning",title:"SCANNING",placeholderTitle:"Scanning Card"},
    captured:{key:"verifying",title:"VERIFYING",placeholderTitle:"Verifying Card"},
    matched:{key:"exact-match",title:"EXACT MATCH",placeholderTitle:"Exact Match"},
    error:{key:"error",title:"ERROR",placeholderTitle:"Recognition Unavailable"},
  };
  applyRecognitionPresentation({
    ...(legacyPresentations[state]||legacyPresentations.idle),
    detail,
    confidence:0,
  });
}

function renderRecognitionLatencyTrace(snapshot={},raw={}){
  renderReferenceCacheMetrics(snapshot,raw);
  renderPackPredictionReadiness(snapshot,raw);
  const timings=snapshot?.stage_timings||raw?.stage_timings||{};
  const packCycle=snapshot?.pack_cycle_timings||raw?.pack_cycle_timings||raw?.continuous?.pack_cycle||{};
  const packCycleTotal=Number(packCycle?.removal_to_verified_ms);
  const sum=(keys)=>{
    const values=keys.map(key=>Number(timings[key])).filter(Number.isFinite);
    return values.length?values.reduce((total,value)=>total+Math.max(0,value),0):null;
  };
  const values={
    latencyDetectValue:sum(["queue_ms","prepare_ms","global_visual_ms"]),
    latencyCandidateValue:sum(["exact_reference_ms","reference_identifier_ms","artwork_preflight_ms","artwork_search_ms"]),
    latencyVerifyValue:sum(["ocr_ms","ranking_ms","finalize_ms"]),
    latencyTotalValue:Number(timings.total_ms??snapshot?.last_latency_ms??raw?.latency_ms),
  };
  const measuredStages=[values.latencyDetectValue,values.latencyCandidateValue,values.latencyVerifyValue]
    .filter(Number.isFinite)
    .reduce((total,value)=>total+value,0);
  if(measuredStages>0){
    values.latencyTotalValue=Math.max(
      measuredStages,
      Number.isFinite(values.latencyTotalValue)?values.latencyTotalValue:0
    );
  }
  Object.entries(values).forEach(([id,value])=>{
    if($(id)) $(id).textContent=Number.isFinite(value)?`${Math.round(value)} ms`:"—";
  });
  const trace=$("recognitionLatencyTrace");
  if(!trace) return;
  const active=Object.values(values).some(Number.isFinite);
  const total=values.latencyTotalValue;
  const stages=[
    ["detect",values.latencyDetectValue],
    ["candidate",values.latencyCandidateValue],
    ["verify",values.latencyVerifyValue],
  ].filter(([,value])=>Number.isFinite(value));
  const bottleneck=stages.sort((left,right)=>right[1]-left[1])[0]?.[0]||"unknown";
  const health=!Number.isFinite(total)?"idle":total>=650?"slow":total>=300?"elevated":"normal";
  const labels={idle:"Timing idle",normal:"Latency normal",elevated:`Elevated · ${bottleneck}`,slow:`Slow · ${bottleneck}`};
  const sampleKey=[currentServerSessionId??"session",snapshot?.generation??"",total].join(":");
  if(Number.isFinite(total)&&sampleKey!==lastRecognitionLatencySampleKey){
    lastRecognitionLatencySampleKey=sampleKey;
    recognitionLatencySamples.push({total:Math.max(0,total),bottleneck,detect:values.latencyDetectValue,candidate:values.latencyCandidateValue,verify:values.latencyVerifyValue,at:new Date().toISOString()});
    recognitionLatencySamples=recognitionLatencySamples.slice(-12);
    saveRecognitionLatencySamples();
  }
  const split=Math.floor(recognitionLatencySamples.length/2);
  const average=values=>values.reduce((sum,value)=>sum+value.total,0)/Math.max(1,values.length);
  const earlier=split?average(recognitionLatencySamples.slice(0,split)):null;
  const recent=split?average(recognitionLatencySamples.slice(split)):null;
  const delta=Number.isFinite(earlier)&&earlier>0?(recent-earlier)/earlier:0;
  const trend=recognitionLatencySamples.length<4?"waiting":delta>.12?"degrading":delta<-.12?"improving":"stable";
  const trendLabels={waiting:"Trend · waiting",stable:"Trend · stable",improving:"Trend · improving",degrading:"Trend · slowing"};
  trace.dataset.active=active?"true":"false";
  trace.dataset.health=health;
  trace.dataset.bottleneck=bottleneck;
  trace.dataset.trend=trend;
  const healthLabel=Number.isFinite(packCycleTotal)
    ? `${labels[health]} · Pack ${Math.round(packCycleTotal)} ms`
    : labels[health];
  if($("latencyHealthLabel")) $("latencyHealthLabel").textContent=healthLabel;
  if($("latencyTrendLabel")) $("latencyTrendLabel").textContent=trendLabels[trend];
  if($("latencyTrendBars")){
    const peak=Math.max(1,...recognitionLatencySamples.map(sample=>sample.total));
    $("latencyTrendBars").innerHTML=recognitionLatencySamples.map(sample=>`<b style="--latency-bar:${Math.max(14,Math.round(sample.total/peak*100))}%"></b>`).join("");
  }
  if($("latencyTrend")) $("latencyTrend").setAttribute("aria-label",`${trendLabels[trend]}; ${recognitionLatencySamples.length} recent samples`);
  trace.setAttribute("aria-label",health==="idle"?"Recognition stage latency idle":`${healthLabel}; ${Math.round(total)} milliseconds recognition total`);
  renderPackSpeedMetrics(snapshot,raw);
}

function renderPackPredictionReadiness(snapshot={},raw={}){
  const host=$("packNextReady"),value=$("packNextReadyValue");
  if(!host||!value)return;
  const stats=snapshot?.catalog?.prediction_prefetch||raw?.catalog?.prediction_prefetch||{};
  const active=Math.max(0,Number(stats.active)||0),ready=Math.max(0,Number(stats.ready)||0),warmed=Math.max(0,Number(stats.warmed)||0),errors=Math.max(0,Number(stats.errors)||0),queued=Math.max(0,Number(stats.queued)||0);
  const state=active>0?"warming":ready>0?"ready":errors>0&&!warmed?"unavailable":"idle";
  const labels={warming:"Warming",ready:"Ready",unavailable:"Offline",idle:"Idle"};
  host.dataset.state=state;
  value.textContent=labels[state];
  host.title=state==="ready"?`${ready} predicted card lookup${ready===1?"":"s"} prepared`:state==="warming"?`Preparing ${active} predicted card lookup${active===1?"":"s"}`:state==="unavailable"?`${errors} predicted lookup${errors===1?"":"s"} unavailable`:"RareIQ will prepare likely next cards after learning this pack sequence.";
  host.setAttribute("aria-label",`${labels[state]} next-card prediction; ${queued} queued, ${warmed} warmed, ${errors} unavailable`);
}

function renderReferenceCacheMetrics(snapshot={},raw={}){
  const status=snapshot?.artwork_index?.status||raw?.artwork_index?.status||{};
  const timing=status?.reference_cache_timing||{};
  const prewarm=status?.reference_prewarm||{};
  const panel=$("referenceCacheMetrics");
  if(!panel)return;
  const hits=Math.max(0,Number(timing.warm_hits)||0);
  const misses=Math.max(0,(Number(timing.image_misses)||0)+(Number(timing.feature_misses)||0));
  const coldPrep=(Number(timing.average_image_decode_ms)||0)+(Number(timing.average_feature_build_ms)||0);
  const saved=Math.max(0,Number(timing.estimated_saved_ms)||0);
  const state=prewarm.state==="warming"?"warming":hits>0?"warm":misses>0?"cold":"idle";
  const labels={warming:"Warming",warm:"Warm",cold:"Cold start",idle:"Waiting"};
  panel.dataset.state=state;
  $("referenceCacheState").textContent=labels[state];
  $("referenceCacheHits").textContent=String(hits);
  $("referenceCacheCold").textContent=misses?`${Math.round(coldPrep)} ms`:`—`;
  $("referenceCacheSaved").textContent=`${Math.round(saved)} ms`;
  panel.setAttribute("aria-label",`${labels[state]} reference cache; ${hits} warm hits; approximately ${Math.round(saved)} milliseconds saved`);
}

function renderPackSpeedMetrics(snapshot={},raw={}){
  const panel=$("packSpeedMetrics");
  if(!panel)return;
  const runtime=raw?.ocr_runtime||snapshot?.ocr_runtime||{};
  const latency=raw?.latency_summary||snapshot?.latency_summary||{};
  const attempts=Math.max(0,Number(runtime.footer_recognition_only_attempts)||0);
  const hits=Math.max(0,Number(runtime.footer_recognition_only_hits)||0);
  const fallbacks=Math.max(0,Number(runtime.footer_detector_fallbacks)||0);
  const hitRate=Number.isFinite(Number(runtime.footer_recognition_only_hit_rate))
    ? Math.max(0,Math.min(1,Number(runtime.footer_recognition_only_hit_rate)))
    : attempts?Math.min(1,hits/attempts):0;
  const mode=String(runtime.last_footer_mode||"").toLowerCase();
  const captureP95=Number(latency.capture_p95_ms);
  const underOneSecond=Number(latency.under_one_second_rate);
  const sampleCount=Math.max(0,Number(latency.capture_sample_count??latency.sample_count)||0);
  const recentTotals=recognitionLatencySamples.map(sample=>Number(sample?.total)).filter(Number.isFinite);
  const rollingAverage=recentTotals.length?recentTotals.reduce((sum,value)=>sum+value,0)/recentTotals.length:null;
  const state=mode==="recognition_only"?"fast":mode||fallbacks?"fallback":"idle";
  const performance=!Number.isFinite(captureP95)||!Number.isFinite(underOneSecond)?"idle"
    :captureP95<=750&&underOneSecond>=.9?"good"
    :captureP95<=1000&&underOneSecond>=.75?"watch":"slow";
  const modeLabel=state==="fast"?"Direct":state==="fallback"?"Detector":"Waiting";
  panel.dataset.state=state;
  panel.dataset.performance=performance;
  $("packFooterMode").textContent=fallbacks?`${modeLabel} · ${fallbacks}`:modeLabel;
  $("packFooterHitRate").textContent=attempts?`${hits} / ${attempts} · ${Math.round(hitRate*100)}%`:"0 / 0";
  $("packCaptureP95").textContent=Number.isFinite(captureP95)?`${Math.round(captureP95)} ms`:"—";
  $("packUnderOneSecond").textContent=Number.isFinite(underOneSecond)?`${Math.round(Math.max(0,Math.min(1,underOneSecond))*100)}%`:"—";
  $("packRollingAverage").textContent=Number.isFinite(rollingAverage)?`${Math.round(rollingAverage)} ms · ${sampleCount}`:sampleCount?`${sampleCount} scans`:"—";
  panel.setAttribute("aria-label",`${modeLabel} footer path; ${hits} of ${attempts} direct hits; ${fallbacks} detector fallbacks; camera p95 ${Number.isFinite(captureP95)?Math.round(captureP95)+" milliseconds":"waiting"}; ${Number.isFinite(underOneSecond)?Math.round(underOneSecond*100)+" percent":"waiting"} under one second; ${sampleCount} measured scans`);
}

function loadRecognitionLatencySamples(){
  try{
    const saved=JSON.parse(sessionStorage.getItem(RECOGNITION_LATENCY_SESSION_KEY)||"[]");
    return Array.isArray(saved)?saved.filter(sample=>Number.isFinite(Number(sample?.total))).slice(-12):[];
  }catch{return[]}
}
function saveRecognitionLatencySamples(){try{sessionStorage.setItem(RECOGNITION_LATENCY_SESSION_KEY,JSON.stringify(recognitionLatencySamples))}catch{}}
function deriveRecognitionLatencyRecommendation(samples=recognitionLatencySamples){
  if(samples.length<4) return {state:"waiting",stage:"unknown",title:"Collecting a baseline",detail:"Complete at least four scans before RareIQ recommends a performance adjustment."};
  const recent=samples.slice(-6),average=recent.reduce((sum,sample)=>sum+Number(sample.total||0),0)/recent.length;
  const counts=recent.reduce((result,sample)=>{const stage=["detect","candidate","verify"].includes(sample.bottleneck)?sample.bottleneck:"unknown";result[stage]=(result[stage]||0)+1;return result},{detect:0,candidate:0,verify:0,unknown:0});
  const dominant=Object.entries(counts).sort((left,right)=>right[1]-left[1])[0];
  const sustained=average>=300&&dominant[1]>=Math.ceil(recent.length/2);
  if(!sustained) return {state:"healthy",stage:dominant[0],title:"Performance looks healthy",detail:"No sustained recognition slowdown is present in the recent session sample."};
  const guidance={
    detect:{title:"Check camera delivery",detail:"Detection is the repeated bottleneck. Verify camera frame rate, resolution, lighting, USB bandwidth, and capture delivery."},
    candidate:{title:"Check artwork-index search",detail:"Candidate search is repeatedly slow. Review active catalog size, artwork-index health, and storage performance."},
    verify:{title:"Check OCR and verification load",detail:"Verification is repeatedly slow. Check image sharpness, glare, OCR workload, and competing CPU usage."},
    unknown:{title:"Review the exported timing report",detail:"Total latency is elevated, but available stage timings do not isolate one subsystem."},
  };
  return {state:"action",stage:dominant[0],...guidance[dominant[0]]};
}
function buildRecognitionLatencyReport(){
  const totals=recognitionLatencySamples.map(sample=>Number(sample.total)).sort((a,b)=>a-b);
  const count=totals.length;
  const percentile=value=>count?totals[Math.min(count-1,Math.max(0,Math.ceil(count*value)-1))]:null;
  const stageDistribution=recognitionLatencySamples.reduce((result,sample)=>{result[sample.bottleneck]=(result[sample.bottleneck]||0)+1;return result},{detect:0,candidate:0,verify:0,unknown:0});
  return {schema:"rareiq-recognition-latency-v1",exported_at:new Date().toISOString(),session_id:currentServerSessionId,summary:{scan_count:count,average_ms:count?Math.round(totals.reduce((sum,value)=>sum+value,0)/count):null,median_ms:percentile(.5),p95_ms:percentile(.95),maximum_ms:count?totals[count-1]:null,stage_distribution:stageDistribution},recommendation:deriveRecognitionLatencyRecommendation(),samples:recognitionLatencySamples};
}
function exportRecognitionLatencyReport(){
  const payload=buildRecognitionLatencyReport();
  const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:"application/json"}));
  const link=document.createElement("a");
  link.href=url;
  link.download=`rareiq-latency-${new Date().toISOString().replace(/[:.]/g,"-")}.json`;
  link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  notify("Latency Report Exported",`${payload.summary.scan_count} session scans included.`,"success");
}
function renderRecognitionLatencyReport(){
  const report=buildRecognitionLatencyReport(),summary=report.summary;
  const metric=(label,value)=>`<div><span>${label}</span><b>${value==null?"—":`${Math.round(value)} ms`}</b></div>`;
  if($("latencyReportSubtitle")) $("latencyReportSubtitle").textContent=summary.scan_count?`${summary.scan_count} completed scans in this browser session.`:"Complete a recognition to begin the report.";
  if($("latencyReportGuidance")){
    $("latencyReportGuidance").dataset.state=report.recommendation.state;
    $("latencyReportGuidance").dataset.stage=report.recommendation.stage;
    $("latencyReportGuidance").querySelector("strong").textContent=report.recommendation.title;
    $("latencyReportGuidance").querySelector("p").textContent=report.recommendation.detail;
  }
  if($("latencyReportMetrics")) $("latencyReportMetrics").innerHTML=metric("Average",summary.average_ms)+metric("Median",summary.median_ms)+metric("P95",summary.p95_ms)+metric("Maximum",summary.maximum_ms);
  const stageTotal=Math.max(1,summary.scan_count);
  if($("latencyReportStages")) $("latencyReportStages").innerHTML=Object.entries(summary.stage_distribution).map(([stage,count])=>`<div><span>${stage}</span><i><b style="width:${Math.round(count/stageTotal*100)}%"></b></i><strong>${count}</strong></div>`).join("");
  if($("latencyReportSamples")) $("latencyReportSamples").innerHTML=report.samples.length?report.samples.slice().reverse().map((sample,index)=>`<div><span>#${report.samples.length-index}</span><b>${Math.round(sample.total)} ms</b><small>${sample.bottleneck||"unknown"}</small><time>${new Date(sample.at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"})}</time></div>`).join(""):"<p>No latency samples yet.</p>";
}
function setRecognitionLatencyReportOpen(open){
  const overlay=$("latencyReportOverlay");
  if(!overlay) return;
  if(open) renderRecognitionLatencyReport();
  overlay.hidden=!open;
  document.body.classList.toggle("latency-report-open",Boolean(open));
  if(open) $("latencyReportClose")?.focus();
}

function showCaptureBanner(success,title,detail){
  const banner=$("captureBanner");
  if(!banner) return;
  banner.classList.toggle("error",!success);
  $("captureBannerIcon").textContent=success?"":"!";
  $("captureBannerTitle").textContent=title;
  $("captureBannerDetail").textContent=detail||"";
  banner.classList.add("visible");
  clearTimeout(captureBannerTimer);
  captureBannerTimer=setTimeout(()=>banner.classList.remove("visible"),3200);
}

function addActivity(title,detail){
  const now=new Date();
  const stamp=now.toLocaleTimeString([],{
    hour:"2-digit",minute:"2-digit",second:"2-digit"
  });
  activityItems.unshift({stamp,title,detail});
  activityItems=activityItems.slice(0,4);
  const feed=$("activityFeed");
  if(!feed) return;
  feed.innerHTML=activityItems.map(item=>`
    <div class="activity-item">
      <time>${item.stamp}</time>
      <strong>${item.title}</strong>
      <span>${item.detail||""}</span>
    </div>
  `).join("");
}

function applyAutoCaptureState(enabled){
  autoCaptureEnabled=Boolean(enabled);
  const toggle=$("autoCaptureToggle");
  if(toggle) toggle.classList.toggle("on",autoCaptureEnabled);
  const label=$("autoCaptureLabel");
  if(label) label.textContent=autoCaptureEnabled?"ON":"OFF";
  if($("emptyAutoState")) $("emptyAutoState").textContent=autoCaptureEnabled?"ON":"OFF";
  setStateChip(
    "autoStateChip",
    autoCaptureEnabled?"on":"",
    autoCaptureEnabled?"ON":"OFF"
  );
}

async function toggleAutoCapture(){
  const next=!autoCaptureEnabled;
  try{
    const result=await api("/api/camera/auto-capture",{
      method:"POST",
      body:JSON.stringify({enabled:next})
    });
    const vision=result.vision||{};
    const enabled=vision.auto_capture_enabled ?? next;
    applyAutoCaptureState(enabled);
    addActivity(
      enabled?"Auto Capture Enabled":"Auto Capture Disabled",
      enabled?"RareIQ will capture stable cards automatically.":"Manual capture only."
    );
  }catch{
    showCaptureBanner(false,"AUTO CAPTURE ERROR","RareIQ could not change the setting.");
    addActivity("Auto Capture Error","Setting change failed.");
  }
}

function switchWorkspace(name){
  document.body.dataset.ui4Workspace=name;
  if(name!=="live")setUI4HealthOpen(false);
  document.querySelectorAll(".workspace").forEach(el=>{
    el.classList.toggle("active",el.dataset.workspace===name);
  });
  document.querySelectorAll(".nav-button").forEach(el=>{
    el.classList.toggle("active",el.dataset.target===name);
  });
  refreshWorkspaceReadiness(name).catch(()=>{});
  if(name==="collection") Promise.all([loadCollection(),loadLibrarySyncStatus()]).catch(error=>{
    notify("Collection Unavailable",error.message||String(error),"error");
  });
  if(name==="creator") Promise.all([loadRevealSequence(),loadCreatorAssets()]).catch(error=>notify("Creator State Unavailable",error.message||String(error),"error"));
  if(name==="soundboard") loadSoundboard().catch(error=>notify("Soundboard Unavailable",error.message||String(error),"error"));
  if(name==="voice-mod") refreshVoiceModInputs().catch(error=>notify("Microphones Unavailable",error.message||String(error),"error"));
  if(name==="spotify") loadSpotify().catch(error=>renderSpotifyError(error.message||String(error)));
  if(name==="broadcast") Promise.all([loadProductionSwitcher(),loadProductionScenes(),loadProductionReplay(),loadProductionScreen(),loadOperatorHealth(),loadShowPreflight(),loadProductionSession(),loadRecordingSettings(),loadObsStatus(),loadBroadcastDestinations(),loadShowAnalytics(),loadCardShowAnalytics(),loadPackTracker(),loadPackEconomics(),loadBreakHistory()]).catch(error=>notify("Production Tools Unavailable",error.message||String(error),"error"));
}

function voiceModPreferences(){try{return JSON.parse(localStorage.getItem(VOICE_MOD_PREFERENCES_KEY)||"{}")||{}}catch(_error){return {}}}
function saveVoiceModPreferences(){try{localStorage.setItem(VOICE_MOD_PREFERENCES_KEY,JSON.stringify({deviceId:$("voiceModInput")?.value||"",preset:$("voiceModPreset")?.value||"clean",gain:Number($("voiceModGain")?.value||100),mix:Number($("voiceModMix")?.value||75),output:Number($("voiceModOutput")?.value||100),monitor:Boolean($("voiceModMonitor")?.checked)}))}catch(_error){}}
function setVoiceModStatus(state,label){const host=$("voiceModState");if(host){host.dataset.state=state;host.querySelector("span").textContent=label}if($("voiceModStart"))$("voiceModStart").disabled=state==="live"||state==="starting";if($("voiceModStop"))$("voiceModStop").disabled=state!=="live"}
async function refreshVoiceModInputs(){if(!navigator.mediaDevices?.enumerateDevices)throw new Error("Microphone selection is not supported in this browser.");const devices=(await navigator.mediaDevices.enumerateDevices()).filter(device=>device.kind==="audioinput"),select=$("voiceModInput");if(!select)return devices;const preferred=select.value||voiceModPreferences().deviceId||"";select.replaceChildren(new Option("Default microphone",""),...devices.map((device,index)=>new Option(device.label||`Microphone ${index+1}`,device.deviceId)));if([...select.options].some(option=>option.value===preferred))select.value=preferred;return devices}
function voiceModDistortion(amount=35){const curve=new Float32Array(44100),k=Number(amount),deg=Math.PI/180;for(let i=0;i<curve.length;i++){const x=i*2/curve.length-1;curve[i]=(3+k)*x*20*deg/(Math.PI+k*Math.abs(x))}return curve}
function connectVoiceModPreset(context,input,wet,preset){const nodes=[],oscillators=[];let tail=input;const add=node=>{tail.connect(node);tail=node;nodes.push(node);return node};if(preset==="deep"){const low=add(context.createBiquadFilter());low.type="lowpass";low.frequency.value=1450;low.Q.value=.7;const bass=add(context.createBiquadFilter());bass.type="lowshelf";bass.frequency.value=210;bass.gain.value=8;const compressor=add(context.createDynamicsCompressor());compressor.threshold.value=-24;compressor.ratio.value=4}else if(preset==="robot"){const mod=add(context.createGain());mod.gain.value=.58;const oscillator=context.createOscillator(),depth=context.createGain();oscillator.frequency.value=42;depth.gain.value=.42;oscillator.connect(depth);depth.connect(mod.gain);oscillator.start();oscillators.push(oscillator);nodes.push(depth);const band=add(context.createBiquadFilter());band.type="bandpass";band.frequency.value=1200;band.Q.value=.8}else if(preset==="radio"){const high=add(context.createBiquadFilter());high.type="highpass";high.frequency.value=420;const low=add(context.createBiquadFilter());low.type="lowpass";low.frequency.value=3200;const compressor=add(context.createDynamicsCompressor());compressor.threshold.value=-30;compressor.ratio.value=8}else if(preset==="megaphone"){const band=add(context.createBiquadFilter());band.type="bandpass";band.frequency.value=1650;band.Q.value=.75;const shaper=add(context.createWaveShaper());shaper.curve=voiceModDistortion(55);shaper.oversample="2x";const compressor=add(context.createDynamicsCompressor());compressor.threshold.value=-28;compressor.ratio.value=10}tail.connect(wet);return {nodes,oscillators}}
function updateVoiceModLevels(){const gain=Number($("voiceModGain")?.value||100),mix=Number($("voiceModMix")?.value||75),output=Number($("voiceModOutput")?.value||100),monitor=$("voiceModMonitor")?.checked?1:0;if($("voiceModGainValue"))$("voiceModGainValue").textContent=`${gain}%`;if($("voiceModMixValue"))$("voiceModMixValue").textContent=`${mix}%`;if($("voiceModOutputValue"))$("voiceModOutputValue").textContent=`${output}%`;if(voiceModState.inputGain)voiceModState.inputGain.gain.value=gain/100;if(voiceModState.dryGain)voiceModState.dryGain.gain.value=1-mix/100;if(voiceModState.wetGain)voiceModState.wetGain.gain.value=mix/100;if(voiceModState.outputGain)voiceModState.outputGain.gain.value=output/100;if(voiceModState.monitorGain)voiceModState.monitorGain.gain.value=monitor;saveVoiceModPreferences()}
function meterVoiceMod(){cancelAnimationFrame(voiceModState.meterFrame);if(!voiceModState.active||!voiceModState.analyser)return;const samples=new Uint8Array(voiceModState.analyser.fftSize);voiceModState.analyser.getByteTimeDomainData(samples);let sum=0;for(const value of samples){const centered=(value-128)/128;sum+=centered*centered}const rms=Math.sqrt(sum/samples.length),db=rms?20*Math.log10(rms):-Infinity,level=Math.max(0,Math.min(100,(db+60)/60*100));if($("voiceModMeterFill"))$("voiceModMeterFill").style.width=`${level}%`;if($("voiceModLevel"))$("voiceModLevel").textContent=Number.isFinite(db)?`${db.toFixed(1)} dB`:"−∞ dB";voiceModState.meterFrame=requestAnimationFrame(meterVoiceMod)}
async function stopVoiceMod(){cancelAnimationFrame(voiceModState.meterFrame);voiceModState.oscillators.forEach(oscillator=>{try{oscillator.stop()}catch(_error){}});voiceModState.inputStream?.getTracks().forEach(track=>track.stop());if(voiceModState.context&&voiceModState.context.state!=="closed")await voiceModState.context.close();voiceModState={context:null,inputStream:null,source:null,inputGain:null,dryGain:null,wetGain:null,outputGain:null,monitorGain:null,destination:null,analyser:null,nodes:[],oscillators:[],meterFrame:0,active:false};window.rareiqVoiceModStream=null;if($("voiceModMeterFill"))$("voiceModMeterFill").style.width="0%";if($("voiceModLevel"))$("voiceModLevel").textContent="−∞ dB";if($("voiceModRoute"))$("voiceModRoute").textContent="RareIQ stream unavailable until started";setVoiceModStatus("idle","Microphone idle")}
async function startVoiceMod(){if(!navigator.mediaDevices?.getUserMedia)throw new Error("Microphone capture is not supported in this browser.");if(voiceModState.active)await stopVoiceMod();setVoiceModStatus("starting","Requesting microphone");const deviceId=$("voiceModInput")?.value||"",stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:deviceId?{exact:deviceId}:undefined,echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false}),AudioContextClass=window.AudioContext||window.webkitAudioContext,context=new AudioContextClass();await context.resume();const source=context.createMediaStreamSource(stream),inputGain=context.createGain(),dryGain=context.createGain(),wetGain=context.createGain(),mixBus=context.createGain(),outputGain=context.createGain(),analyser=context.createAnalyser(),monitorGain=context.createGain(),destination=context.createMediaStreamDestination();analyser.fftSize=1024;source.connect(inputGain);inputGain.connect(dryGain);dryGain.connect(mixBus);const preset=$("voiceModPreset")?.value||"clean",effect=connectVoiceModPreset(context,inputGain,wetGain,preset);wetGain.connect(mixBus);mixBus.connect(outputGain);outputGain.connect(analyser);analyser.connect(destination);analyser.connect(monitorGain);monitorGain.connect(context.destination);voiceModState={context,inputStream:stream,source,inputGain,dryGain,wetGain,outputGain,monitorGain,destination,analyser,nodes:effect.nodes,oscillators:effect.oscillators,meterFrame:0,active:true};window.rareiqVoiceModStream=destination.stream;if($("voiceModPresetName"))$("voiceModPresetName").textContent=VOICE_MOD_PRESETS[preset]||preset;if($("voiceModRoute"))$("voiceModRoute").textContent="Processed RareIQ audio stream ready";updateVoiceModLevels();setVoiceModStatus("live","Voice Mod live");await refreshVoiceModInputs();meterVoiceMod();notify("Voice Mod Live",`${VOICE_MOD_PRESETS[preset]||preset} processing is active.`,"success")}
function restoreVoiceModPreferences(){const prefs=voiceModPreferences();if($("voiceModPreset"))$("voiceModPreset").value=VOICE_MOD_PRESETS[prefs.preset]?prefs.preset:"clean";[["voiceModGain",prefs.gain??100],["voiceModMix",prefs.mix??75],["voiceModOutput",prefs.output??100]].forEach(([id,value])=>{if($(id))$(id).value=String(value)});if($("voiceModMonitor"))$("voiceModMonitor").checked=Boolean(prefs.monitor);updateVoiceModLevels()}
const CAMERA_FX_PRESETS={clean:{brightness:100,contrast:100,saturation:100,sepia:0,hue:0},vibrant:{brightness:104,contrast:112,saturation:145,sepia:0,hue:0},cinematic:{brightness:92,contrast:128,saturation:86,sepia:12,hue:-8},warm:{brightness:103,contrast:106,saturation:118,sepia:22,hue:-7},cool:{brightness:101,contrast:108,saturation:112,sepia:0,hue:12},noir:{brightness:98,contrast:145,saturation:0,sepia:0,hue:0},vintage:{brightness:98,contrast:108,saturation:78,sepia:38,hue:-12}};
function cameraFxPreferences(){try{return JSON.parse(localStorage.getItem(CAMERA_FX_PREFERENCES_KEY)||"{}")||{}}catch(_error){return {}}}
function cameraFxValues(){return {enabled:cameraFxState.enabled,preset:document.querySelector("[data-camera-fx-preset][aria-pressed=true]")?.dataset.cameraFxPreset||"clean",brightness:Number($("cameraFxBrightness")?.value||100),contrast:Number($("cameraFxContrast")?.value||100),saturation:Number($("cameraFxSaturation")?.value||100),blur:Number($("cameraFxBlur")?.value||0),chroma:Boolean($("cameraFxChroma")?.checked),keyColor:$("cameraFxKeyColor")?.value||"#00ff00",tolerance:Number($("cameraFxTolerance")?.value||32),softness:Number($("cameraFxSoftness")?.value||18)}}
function saveCameraFxPreferences(){try{localStorage.setItem(CAMERA_FX_PREFERENCES_KEY,JSON.stringify(cameraFxValues()))}catch(_error){}}
function cameraFxFilter(){const values=cameraFxValues(),preset=CAMERA_FX_PRESETS[values.preset]||CAMERA_FX_PRESETS.clean;return `brightness(${values.brightness}%) contrast(${values.contrast}%) saturate(${values.saturation}%) sepia(${preset.sepia}%) hue-rotate(${preset.hue}deg) blur(${values.blur}px)`}
function renderCameraFxControls(){const values=cameraFxValues(),filter=cameraFxFilter();[["cameraFxBrightnessValue",`${values.brightness}%`],["cameraFxContrastValue",`${values.contrast}%`],["cameraFxSaturationValue",`${values.saturation}%`],["cameraFxBlurValue",`${values.blur}px`],["cameraFxToleranceValue",`${values.tolerance}%`],["cameraFxSoftnessValue",`${values.softness}%`]].forEach(([id,label])=>{if($(id))$(id).textContent=label});const preview=$("cameraFxPreview"),feed=$("cameraFeed"),canvas=$("cameraFxCanvas");if(preview){preview.src=feed?.src||"";preview.style.filter=filter}if(feed)feed.style.filter=cameraFxState.enabled&&!values.chroma?filter:"none";if(canvas)canvas.style.filter=cameraFxState.enabled&&values.chroma?filter:"none";const host=$("cameraFxState");if(host){host.dataset.state=cameraFxState.enabled?"live":"off";host.querySelector("span").textContent=cameraFxState.enabled?values.chroma?"Green screen live":`${values.preset} live`:"Effects bypassed"}if($("cameraFxApply"))$("cameraFxApply").textContent=cameraFxState.enabled?"Disable Effects":"Enable Effects";document.body.dataset.cameraFx=cameraFxState.enabled?"on":"off";saveCameraFxPreferences()}
function cameraFxColor(hex){const value=parseInt(hex.slice(1),16);return [(value>>16)&255,(value>>8)&255,value&255]}
function renderCameraFxFrame(timestamp=0){cancelAnimationFrame(cameraFxState.frame);const values=cameraFxValues(),feed=$("cameraFeed"),canvas=$("cameraFxCanvas");if(!cameraFxState.enabled||!values.chroma||!feed||!canvas){if(canvas)canvas.hidden=true;return}cameraFxState.frame=requestAnimationFrame(renderCameraFxFrame);if(timestamp-cameraFxState.lastFrame<66||!feed.complete||!feed.naturalWidth)return;cameraFxState.lastFrame=timestamp;const scale=Math.min(1,960/feed.naturalWidth),width=Math.max(1,Math.round(feed.naturalWidth*scale)),height=Math.max(1,Math.round(feed.naturalHeight*scale));if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height}const context=canvas.getContext("2d",{willReadFrequently:true});try{context.drawImage(feed,0,0,width,height);const frame=context.getImageData(0,0,width,height),key=cameraFxColor(values.keyColor),threshold=values.tolerance*4.42,soft=Math.max(1,values.softness*2.55);for(let index=0;index<frame.data.length;index+=4){const distance=Math.hypot(frame.data[index]-key[0],frame.data[index+1]-key[1],frame.data[index+2]-key[2]);if(distance<threshold)frame.data[index+3]=Math.max(0,Math.min(255,(distance-(threshold-soft))/soft*255))}context.putImageData(frame,0,0);canvas.hidden=false}catch(_error){canvas.hidden=true}}
function setCameraFxPreset(name){const preset=CAMERA_FX_PRESETS[name]||CAMERA_FX_PRESETS.clean;document.querySelectorAll("[data-camera-fx-preset]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.cameraFxPreset===name)));[["cameraFxBrightness",preset.brightness],["cameraFxContrast",preset.contrast],["cameraFxSaturation",preset.saturation]].forEach(([id,value])=>{if($(id))$(id).value=String(value)});renderCameraFxControls();renderCameraFxFrame()}
function toggleCameraFx(){cameraFxState.enabled=!cameraFxState.enabled;renderCameraFxControls();renderCameraFxFrame();notify(cameraFxState.enabled?"Camera Effects Live":"Camera Effects Bypassed",cameraFxState.enabled?"Program styling is active; recognition remains on the clean feed.":"The clean camera output is restored.","success")}
function resetCameraFx(){cameraFxState.enabled=false;if($("cameraFxBlur"))$("cameraFxBlur").value="0";if($("cameraFxChroma"))$("cameraFxChroma").checked=false;if($("cameraFxTolerance"))$("cameraFxTolerance").value="32";if($("cameraFxSoftness"))$("cameraFxSoftness").value="18";setCameraFxPreset("clean");renderCameraFxControls();renderCameraFxFrame()}
function restoreCameraFxPreferences(){const prefs=cameraFxPreferences(),preset=CAMERA_FX_PRESETS[prefs.preset]?prefs.preset:"clean";cameraFxState.enabled=Boolean(prefs.enabled);[["cameraFxBrightness",prefs.brightness??CAMERA_FX_PRESETS[preset].brightness],["cameraFxContrast",prefs.contrast??CAMERA_FX_PRESETS[preset].contrast],["cameraFxSaturation",prefs.saturation??CAMERA_FX_PRESETS[preset].saturation],["cameraFxBlur",prefs.blur??0],["cameraFxTolerance",prefs.tolerance??32],["cameraFxSoftness",prefs.softness??18],["cameraFxKeyColor",prefs.keyColor||"#00ff00"]].forEach(([id,value])=>{if($(id))$(id).value=String(value)});if($("cameraFxChroma"))$("cameraFxChroma").checked=Boolean(prefs.chroma);document.querySelectorAll("[data-camera-fx-preset]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.cameraFxPreset===preset)));renderCameraFxControls();renderCameraFxFrame()}

let productionSwitcherState={program_slot:1,preview_slot:2,transition:"fade",duration_ms:500,generation:0};
let productionScenes=[];
let operatorHealthTimer=0;
let productionSessionState={active:false,started_at:0,events:[],recording:{configured:false,active:false}},productionSessionTimer=0;
function analyticsRows(containerId,values={},empty="No activity yet."){const box=$(containerId),entries=Object.entries(values).sort((a,b)=>b[1]-a[1]);if(!box)return;const max=Math.max(1,...entries.map(([,value])=>Number(value)||0));box.replaceChildren(...(entries.length?entries.map(([label,value])=>{const row=document.createElement("div");row.className="analytics-row";row.innerHTML="<span></span><i><b></b></i><strong></strong>";row.querySelector("span").textContent=label;row.querySelector("b").style.width=`${Math.max(4,Number(value)/max*100)}%`;row.querySelector("strong").textContent=String(value);return row;}):[Object.assign(document.createElement("p"),{textContent:empty})]));}
function renderShowAnalytics(payload={}){const data=payload.analytics||payload,counts=data.counts||{},incidents=data.incidents||[];if($("analyticsDuration"))$("analyticsDuration").textContent=sessionTime(data.duration_seconds||0);if($("analyticsEvents"))$("analyticsEvents").textContent=String(data.total_events||0);if($("analyticsCueGap"))$("analyticsCueGap").textContent=`${data.average_cue_interval_seconds||0}s`;if($("analyticsIncidents"))$("analyticsIncidents").textContent=String(incidents.length);if($("analyticsReplays"))$("analyticsReplays").textContent=String(counts.replay||0);if($("analyticsGraphics"))$("analyticsGraphics").textContent=String(counts.graphic||0);analyticsRows("analyticsScenes",data.scene_usage,"No scene activity yet.");analyticsRows("analyticsCameras",data.camera_usage,"No camera activity yet.");if($("analyticsIncidentList"))$("analyticsIncidentList").replaceChildren(...(incidents.length?incidents.slice().reverse().map(event=>{const row=document.createElement("div");row.className="analytics-incident";row.innerHTML="<div><strong></strong><small></small></div><span></span>";row.querySelector("strong").textContent=event.title;row.querySelector("small").textContent=event.detail||event.kind;row.querySelector("span").textContent=new Date(event.timestamp*1000).toLocaleTimeString();return row;}):[Object.assign(document.createElement("p"),{textContent:"No incidents logged."})]));if($("analyticsRecording"))$("analyticsRecording").textContent=data.recording_verified?"Recording verified":"Recording not verified";}
async function loadShowAnalytics(){const payload=await api("/api/production/session/analytics");renderShowAnalytics(payload);return payload;}
let cardShowAnalyticsState={top_pulls:[]};
function renderCardShowAnalytics(payload={}){const data=payload.analytics||payload;cardShowAnalyticsState=data;if($("cardAnalyticsRevealed"))$("cardAnalyticsRevealed").textContent=String(data.cards_revealed||0);if($("cardAnalyticsPace"))$("cardAnalyticsPace").textContent=`${data.average_seconds_between_cards||0}s`;if($("cardAnalyticsValue"))$("cardAnalyticsValue").textContent=data.valued_cards?`$${Number(data.verified_value_total||0).toFixed(2)}`:"Unavailable";if($("cardAnalyticsCoverage"))$("cardAnalyticsCoverage").textContent=`${data.valued_cards||0} / ${data.unvalued_cards||0}`;if($("cardAnalyticsInventory"))$("cardAnalyticsInventory").textContent=String(data.inventory_added||0);if($("cardAnalyticsCollection"))$("cardAnalyticsCollection").textContent=String(data.collection_copies||0);analyticsRows("cardAnalyticsTiers",data.tier_counts,"No reveal data yet.");analyticsRows("cardAnalyticsRarities",data.rarity_counts,"No rarity data yet.");const top=$("cardAnalyticsTopPulls"),pulls=data.top_pulls||[];if(top)top.replaceChildren(...(pulls.length?pulls.map((card,index)=>{const row=document.createElement("article");row.innerHTML="<b></b><div><strong></strong><small></small></div><span></span>";row.querySelector("b").textContent=`#${index+1}`;row.querySelector("strong").textContent=card.card_name||"Verified card";row.querySelector("small").textContent=[card.rarity,card.collector_number].filter(Boolean).join(" · ");row.querySelector("span").textContent=`$${Number(card.market_value).toFixed(2)}`;return row;}):[Object.assign(document.createElement("p"),{textContent:"No verified market values available."})]));if($("cardAnalyticsTopPullGraphic"))$("cardAnalyticsTopPullGraphic").disabled=!pulls.length;if($("cardAnalyticsPricing"))$("cardAnalyticsPricing").textContent=data.valued_cards?`${data.valued_cards} valued · ${data.unvalued_cards} excluded without verified pricing`:"Market totals unavailable · no verified pricing";}
async function loadCardShowAnalytics(){const payload=await api("/api/production/session/card-analytics");renderCardShowAnalytics(payload);return payload;}
async function takeTopPullGraphic(){const card=cardShowAnalyticsState.top_pulls?.[0];if(!card)return;if($("productionGraphicKind"))$("productionGraphicKind").value="card";if($("productionGraphicTitle"))$("productionGraphicTitle").value=`Top Pull · ${card.card_name||"Verified Card"}`;if($("productionGraphicSubtitle"))$("productionGraphicSubtitle").value=[card.rarity,card.collector_number,`Verified value $${Number(card.market_value).toFixed(2)}`].filter(Boolean).join(" · ");if($("productionGraphicPreviewFrame"))$("productionGraphicPreviewFrame").dataset.imageUrl=card.reference_image_url||"";await sendProductionGraphic("take");}
let packTrackerState={current_pack:null,packs:[]};
function renderPackTracker(payload={}){const data=payload.tracker||payload,current=data.current_pack||{},strongest=current.strongest_pull;packTrackerState=data;if($("packTrackerPosition"))$("packTrackerPosition").textContent=`Pack ${current.pack_number||1} · Card ${data.position||current.cards||0} of ${data.expected_cards||6}`;if($("packTrackerHits"))$("packTrackerHits").textContent=String(current.hits||0);if($("packTrackerHitRate"))$("packTrackerHitRate").textContent=`${current.hit_rate||0}%`;if($("packTrackerValue"))$("packTrackerValue").textContent=current.valued_cards?`$${Number(current.verified_value||0).toFixed(2)}`:"Unavailable";if($("packTrackerCoverage"))$("packTrackerCoverage").textContent=`${current.valued_cards||0} / ${current.unvalued_cards||0}`;if($("packTrackerStrongest"))$("packTrackerStrongest").textContent=strongest?.card_name||"Waiting for cards";if($("packTrackerRecap"))$("packTrackerRecap").disabled=!current.cards;const comparison=$("packTrackerComparison"),packs=data.packs||[],max=Math.max(1,...packs.map(pack=>Number(pack.verified_value)||0));if(comparison)comparison.replaceChildren(...(packs.length?packs.map(pack=>{const row=document.createElement("article");row.innerHTML="<div><strong></strong><small></small></div><i><b></b></i><span></span>";row.querySelector("strong").textContent=`Pack ${pack.pack_number}`;row.querySelector("small").textContent=`${pack.cards} cards · ${pack.hits} hits · ${pack.hit_rate}%`;row.querySelector("b").style.width=`${pack.valued_cards?Math.max(4,Number(pack.verified_value)/max*100):0}%`;row.querySelector("span").textContent=pack.valued_cards?`$${Number(pack.verified_value).toFixed(2)}`:"Unpriced";return row;}):[Object.assign(document.createElement("p"),{textContent:"No completed pack data yet."})]));if($("packTrackerBest"))$("packTrackerBest").textContent=data.best_pack?`Best pack: #${data.best_pack.pack_number} · ${data.best_pack.valued_cards?`$${Number(data.best_pack.verified_value).toFixed(2)}`:"value unavailable"}`:"Best pack unavailable";}
async function loadPackTracker(){const payload=await api("/api/production/session/pack-tracker");renderPackTracker(payload);return payload;}
async function takePackFinaleGraphic(){const pack=packTrackerState.current_pack;if(!pack?.cards)return;const pull=pack.strongest_pull;if($("productionGraphicKind"))$("productionGraphicKind").value="announcement";if($("productionGraphicTitle"))$("productionGraphicTitle").value=`Pack ${pack.pack_number} Recap`;if($("productionGraphicSubtitle"))$("productionGraphicSubtitle").value=[`${pack.cards} cards`,`${pack.hits} hits`,`${pack.hit_rate}% hit rate`,pack.valued_cards?`Verified value $${Number(pack.verified_value).toFixed(2)}`:"Market value unavailable",pull?.card_name?`Top: ${pull.card_name}`:null].filter(Boolean).join(" · ");if($("productionGraphicPreviewFrame"))$("productionGraphicPreviewFrame").dataset.imageUrl=pull?.reference_image_url||"";await sendProductionGraphic("take");}
function economicsMoney(value,currency="USD"){try{return new Intl.NumberFormat(undefined,{style:"currency",currency}).format(Number(value)||0)}catch{return `$${(Number(value)||0).toFixed(2)}`}}
function renderPackEconomics(payload={}){const data=payload.economics||payload,settings=data.settings||{},currency=settings.currency||"USD";[["packEconomicsPackCost",settings.pack_cost],["packEconomicsBoxCost",settings.box_cost],["packEconomicsPacksPerBox",settings.packs_per_box],["packEconomicsCurrency",currency]].forEach(([id,value])=>{if($(id))$(id).value=value??""});const values={economicsOpenedPacks:data.opened_packs||0,economicsEffectiveCost:economicsMoney(data.effective_pack_cost,currency),economicsTotalCost:economicsMoney(data.total_cost,currency),economicsVerifiedReturn:economicsMoney(data.verified_return,currency),economicsBreakEven:`${data.break_even_percent||0}%`,economicsMargin:economicsMoney(data.verified_margin,currency),economicsUnresolved:data.unresolved_cards||0,economicsRealizedSales:economicsMoney(data.inventory_realized_all_time,currency),economicsInventoryProfit:economicsMoney(data.inventory_profit_all_time,currency)};Object.entries(values).forEach(([id,value])=>{if($(id))$(id).textContent=String(value)});if($("economicsStatus"))$("economicsStatus").textContent=data.valuation_status==="minimum_verified"?"Minimum verified · unpriced cards excluded":"Complete verified valuation";const rows=$("economicsPackRows");if(rows)rows.replaceChildren(...((data.packs||[]).length?data.packs.map(pack=>{const article=document.createElement("article");article.innerHTML="<strong></strong><span></span><b></b>";article.querySelector("strong").textContent=`Pack ${pack.pack_number} · ${pack.cards} cards`;article.querySelector("span").textContent=`Cost ${economicsMoney(pack.cost,currency)} · Return ${economicsMoney(pack.verified_return,currency)} · ${pack.unresolved_cards} unpriced`;article.querySelector("b").textContent=`Margin ${economicsMoney(pack.verified_margin,currency)}`;article.dataset.margin=Number(pack.verified_margin)>=0?"positive":"negative";return article;}):[Object.assign(document.createElement("p"),{textContent:"No pack history yet."})]));}
async function loadPackEconomics(){const payload=await api("/api/production/session/pack-economics");renderPackEconomics(payload);return payload;}
async function savePackEconomics(event){event?.preventDefault();const payload=await api("/api/production/session/pack-economics",{method:"POST",body:JSON.stringify({pack_cost:Number($("packEconomicsPackCost")?.value||0),box_cost:Number($("packEconomicsBoxCost")?.value||0),packs_per_box:Number($("packEconomicsPacksPerBox")?.value||1),currency:$("packEconomicsCurrency")?.value||"USD"})});renderPackEconomics(payload);notify("Pack Economics Saved","Cost basis and break-even reporting updated.","success");}
function renderBreakHistory(payload={}){const history=payload.history||[],summary=payload.summary||{},money=value=>economicsMoney(value,"USD"),fields={historyCompleted:summary.completed_sessions||0,historyPacks:summary.opened_packs||0,historyCards:summary.cards_revealed||0,historyCost:money(summary.total_cost),historyReturn:money(summary.verified_return),historyMargin:money(summary.verified_margin),historyUnresolved:summary.unresolved_cards||0};Object.entries(fields).forEach(([id,value])=>{if($(id))$(id).textContent=String(value)});if($("breakHistoryStatus"))$("breakHistoryStatus").textContent=history.length?`${history.length} archived session${history.length===1?"":"s"}`:"No completed sessions";const list=$("breakHistoryList");if(list)list.replaceChildren(...(history.length?history.map(item=>{const economics=item.economics||{},pull=item.strongest_pull,article=document.createElement("article");article.innerHTML="<header><div><strong></strong><span></span></div><b></b></header><div class='history-metrics'></div><footer></footer>";article.querySelector("strong").textContent=new Date(Number(item.ended_at||0)*1000).toLocaleString();article.querySelector("span").textContent=`${formatElapsed(item.duration_seconds||0)} · ${item.cards_revealed||0} cards · ${economics.opened_packs||0} packs`;article.querySelector("b").textContent=money(economics.verified_margin);article.querySelector("b").dataset.margin=Number(economics.verified_margin)>=0?"positive":"negative";const metrics=article.querySelector(".history-metrics");[["Cost",money(economics.total_cost)],["Return",money(economics.verified_return)],["Break even",`${economics.break_even_percent||0}%`],["Pace",`${item.average_seconds_between_cards||0}s/card`],["Unpriced",economics.unresolved_cards||0]].forEach(([label,value])=>{const node=document.createElement("span");node.innerHTML="<small></small><strong></strong>";node.querySelector("small").textContent=label;node.querySelector("strong").textContent=value;metrics.append(node)});article.querySelector("footer").textContent=pull?`Top pull: ${pull.card_name} · ${money(pull.market_value)}`:"No verified top pull";return article;}):[Object.assign(document.createElement("p"),{textContent:"End a production session to create the first durable snapshot."})]));}
let breakHistoryArchive={history:[],summary:{}};
function applyBreakHistoryFilters(){const query=($("breakHistorySearch")?.value||"").trim().toLowerCase(),filter=$("breakHistoryFilter")?.value||"all",sort=$("breakHistorySort")?.value||"newest";let history=(breakHistoryArchive.history||[]).filter(item=>{const economics=item.economics||{},pull=item.strongest_pull||{},text=[item.session_id,pull.card_name,pull.set_name,pull.card_number].join(" ").toLowerCase();if(query&&!text.includes(query))return false;const margin=Number(economics.verified_margin||0),unresolved=Number(economics.unresolved_cards||0);return filter==="profitable"?margin>=0:filter==="loss"?margin<0:filter==="unresolved"?unresolved>0:filter==="complete"?unresolved===0:true});history.sort((a,b)=>sort==="margin"?Number(b.economics?.verified_margin||0)-Number(a.economics?.verified_margin||0):sort==="return"?Number(b.economics?.verified_return||0)-Number(a.economics?.verified_return||0):sort==="cards"?Number(b.cards_revealed||0)-Number(a.cards_revealed||0):Number(b.ended_at||0)-Number(a.ended_at||0));renderBreakHistory({history,summary:breakHistoryArchive.summary});document.querySelectorAll("#breakHistoryList>article").forEach((article,index)=>{const item=history[index];if(!item)return;const link=document.createElement("a");link.className="riq-button history-report-link";link.href=`/production/session/history/${encodeURIComponent(item.session_id)}/report`;link.target="_blank";link.rel="noopener";link.textContent="Open Frozen Report";article.append(link)});if($("breakHistoryStatus"))$("breakHistoryStatus").textContent=`${history.length} of ${breakHistoryArchive.history.length} archived sessions`;}
async function loadBreakHistory(){const payload=await api("/api/production/session/history");breakHistoryArchive={history:payload.history||[],summary:payload.summary||{}};applyBreakHistoryFilters();return payload;}
let obsState={connected:false,scenes:[],streaming:false,recording:false,scene_map:{}};
let broadcastDestinationState={destinations:[],summary:{},routing:{}};
function obsSceneName(value){return typeof value==="string"?value:value?.sceneName||value?.scene_name||value?.name||"";}
function renderObsDiagnostic(){const box=$("obsDiagnostic"),diagnostic=obsState.diagnostic||{};if(!box)return;box.dataset.code=obsState.connected?"connected":diagnostic.code||"unknown";box.querySelector("strong").textContent=obsState.connected?"OBS CONNECTED":diagnostic.message||"OBS is offline";box.querySelector("span").textContent=obsState.connected?`${obsState.current_scene||"No active scene"} · WebSocket control ready`:diagnostic.action||"Open OBS connection settings";}
function renderObsStatus(payload={}){obsState=payload.obs||payload;const connected=Boolean(obsState.connected);if($("obsConnectionStatus"))$("obsConnectionStatus").textContent=connected?`Connected · ${obsState.obs_version||"OBS"}`:(obsState.error||"Offline");if($("obsCapabilityStatus"))$("obsCapabilityStatus").textContent=obsState.client_installed?"OBS WebSocket client ready": "Install obsws-python to enable OBS control";if($("obsHost"))$("obsHost").value=obsState.host||"127.0.0.1";if($("obsPort"))$("obsPort").value=String(obsState.port||4455);if($("obsEnabled"))$("obsEnabled").checked=Boolean(obsState.enabled);if($("obsSceneSelect")){const names=(obsState.scenes||[]).map(obsSceneName).filter(Boolean);$("obsSceneSelect").replaceChildren(...(names.length?names.map(name=>new Option(name,name)):[new Option("No scenes loaded","")]));if(obsState.current_scene)$("obsSceneSelect").value=obsState.current_scene;}if($("obsStreamToggle"))$("obsStreamToggle").textContent=obsState.streaming?"STOP STREAM":"START STREAM";if($("obsRecordToggle"))$("obsRecordToggle").textContent=obsState.recording?"STOP OBS RECORDING":"START OBS RECORDING";if($("obsLiveSummary"))$("obsLiveSummary").textContent=[obsState.streaming?"STREAMING":null,obsState.recording?"RECORDING":null].filter(Boolean).join(" · ")||"Offline";renderObsSceneMap();}
function renderObsSceneMap(){const map=$("obsSceneMap");if(!map)return;const names=(obsState.scenes||[]).map(obsSceneName).filter(Boolean);map.replaceChildren(...productionScenes.map(scene=>{const label=document.createElement("label");label.innerHTML="<span></span><select></select>";label.querySelector("span").textContent=scene.name;label.querySelector("select").dataset.rareiqScene=scene.id;label.querySelector("select").replaceChildren(new Option("Do not sync",""),...names.map(name=>new Option(name,name)));label.querySelector("select").value=obsState.scene_map?.[scene.id]||"";return label;}));}
async function loadObsStatus(){const payload=await api("/api/production/obs");renderObsStatus(payload);renderObsDiagnostic();return payload;}
function broadcastDestinationCard(destination){
  const card=document.createElement("article");
  card.className="broadcast-destination-card";
  card.dataset.state=destination.state||"unknown";
  const header=document.createElement("header"),mark=document.createElement("i"),identity=document.createElement("div"),name=document.createElement("strong"),transport=document.createElement("span"),state=document.createElement("b");
  mark.textContent=String(destination.name||"?").slice(0,2).toUpperCase();
  name.textContent=destination.name||"Unknown platform";
  transport.textContent=destination.transport||"External encoder";
  identity.append(name,transport);
  state.textContent=destination.state_label||"Unavailable";
  header.append(mark,identity,state);
  const capabilities=document.createElement("div");
  capabilities.className="broadcast-destination-capabilities";
  (destination.capabilities||[]).forEach(value=>{const item=document.createElement("span");item.textContent=value;capabilities.append(item);});
  const note=document.createElement("p");note.textContent=destination.note||"Platform connector is not configured.";
  const setup=document.createElement("small");setup.textContent=`Setup: ${destination.setup_method||"Platform authorization required"}`;
  card.append(header,capabilities,note,setup);
  return card;
}
function renderBroadcastDestinations(payload={}){
  broadcastDestinationState=payload;
  const routing=payload.routing||{},summary=payload.summary||{},status=$("broadcastRoutingStatus"),grid=$("broadcastDestinationGrid"),summaryBox=$("broadcastDestinationSummary");
  if(status){status.dataset.state=routing.platform_live_verified?"verified":routing.streaming?"unverified":routing.connected?"ready":"setup";status.querySelector("strong").textContent=routing.platform_live_verified?"Platform output verified":routing.streaming?"Encoder active · platforms unverified":routing.connected?"OBS connected · output idle":"External encoder setup required";status.querySelector("span").textContent=routing.detail||"No platform is assumed live until its connector confirms it.";}
  if(summaryBox)summaryBox.replaceChildren(...[["connected","connected"],["ready","ready"],["live","live"],["needs_setup","need setup"]].map(([key,label])=>{const item=document.createElement("span");item.textContent=`${Number(summary[key]||0)} ${label}`;return item;}));
  if(grid)grid.replaceChildren(...(payload.destinations||[]).map(broadcastDestinationCard));
}
function renderBroadcastDestinationsUnavailable(error){
  const status=$("broadcastRoutingStatus"),grid=$("broadcastDestinationGrid"),summaryBox=$("broadcastDestinationSummary");
  if(status){status.dataset.state="unavailable";status.querySelector("strong").textContent="Destination status unavailable";status.querySelector("span").textContent="RareIQ could not reach the read-only connector status endpoint.";}
  if(summaryBox)summaryBox.replaceChildren(...["connected","ready","live"].map(label=>{const item=document.createElement("span");item.textContent=`— ${label}`;return item;}));
  if(grid){const unavailable=document.createElement("div");unavailable.className="broadcast-destination-unavailable";const title=document.createElement("strong");title.textContent="Destination connectors unavailable";const detail=document.createElement("span");detail.textContent=error?.message||"Use Refresh Status to try again.";const guidance=document.createElement("small");guidance.textContent="No platform connection or live state is being assumed.";unavailable.append(title,detail,guidance);grid.replaceChildren(unavailable);}
}
async function loadBroadcastDestinations(){try{const payload=await api("/api/production/destinations");renderBroadcastDestinations(payload);return payload;}catch(error){renderBroadcastDestinationsUnavailable(error);throw error;}}
async function saveObsSettings(event){event.preventDefault();const scene_map={};document.querySelectorAll("#obsSceneMap select").forEach(select=>{if(select.value)scene_map[select.dataset.rareiqScene]=select.value;});const payload=await api("/api/production/obs/settings",{method:"POST",body:JSON.stringify({host:$("obsHost")?.value.trim()||"127.0.0.1",port:Number($("obsPort")?.value)||4455,password:$("obsPassword")?.value||"",enabled:Boolean($("obsEnabled")?.checked),scene_map})});if($("obsPassword"))$("obsPassword").value="";renderObsStatus(payload);notify(payload.obs?.connected?"OBS Connected":"OBS Settings Saved",payload.obs?.connected?"RareIQ scene synchronization is ready.":payload.obs?.error||"OBS is not connected.",payload.obs?.connected?"success":"error");}
async function obsCommand(action,scene=null){const payload=await api("/api/production/obs/command",{method:"POST",body:JSON.stringify({action,scene})});renderObsStatus(payload);return payload;}
function renderObsBootstrap(payload={}){const result=payload.bootstrap||payload,plan=result.plan||[],created=new Set((result.created||[]).map(item=>item.scene)),skipped=new Map((result.skipped||[]).map(item=>[item.scene,item.reason])),ready=result.ready===true||result.dry_run===false&&!result.diagnostic;const status=$("obsBootstrapStatus"),create=$("obsBootstrapCreate"),diagnostic=result.diagnostic||{};if(create)create.disabled=!ready;if(status){status.dataset.state=ready?"ready":"blocked";status.querySelector("strong").textContent=ready?"AUTHENTICATED · READY":"SETUP REQUIRED";status.querySelector("span").textContent=ready?`${result.create_count??plan.length} to create · ${result.preserve_count??0} existing scenes preserved · ${result.obs_version||"OBS"}`:diagnostic.action||diagnostic.message||"Connect OBS WebSocket, then preview again.";}if($("obsBootstrapPlan"))$("obsBootstrapPlan").replaceChildren(...plan.map(item=>{const row=document.createElement("article");row.innerHTML="<div><strong></strong><code></code></div><span></span>";row.querySelector("strong").textContent=item.scene;row.querySelector("code").textContent=item.url;row.querySelector("span").textContent=result.dry_run?(item.action==="preserve"?"PRESERVE":"CREATE"):created.has(item.scene)?"CREATED":skipped.get(item.scene)||"SKIPPED";row.dataset.state=created.has(item.scene)?"created":skipped.has(item.scene)||item.action==="preserve"?"skipped":"planned";return row;}));}
async function bootstrapObs(dry_run){if(!dry_run&&!confirm("Create the planned RareIQ scenes and browser inputs in connected OBS? Existing scenes will be skipped."))return;const payload=await api("/api/production/obs/bootstrap",{method:"POST",body:JSON.stringify({base_url:location.origin,dry_run})});renderObsBootstrap(payload);if(!dry_run){renderObsStatus(payload.bootstrap?.status||{});const mapped=Object.keys(payload.bootstrap?.mapped||{}).length;notify("OBS Bootstrap Complete",`${payload.bootstrap?.created?.length||0} created · ${payload.bootstrap?.skipped?.length||0} preserved · ${mapped} cues mapped`,"success");}}
function renderRecordingSettings(payload={}){const settings=payload.settings||payload;if($("recordingPreset"))$("recordingPreset").value=settings.preset||"balanced";if($("recordingMinimumFree"))$("recordingMinimumFree").value=String(settings.minimum_free_gb||2);if($("recordingOutputDir"))$("recordingOutputDir").value=settings.output_dir||"";if($("recordingCommand"))$("recordingCommand").value=settings.command_template||"";if($("recordingDiskEstimate"))$("recordingDiskEstimate").textContent=`${(Number(settings.free_bytes||0)/1073741824).toFixed(1)} GB free · about ${Number(settings.estimated_minutes||0).toLocaleString()} recording minutes`;}
function renderEncoderGuide(payload={}){const capabilities=payload.capabilities||{},sources=payload.browser_sources||{},origin=location.origin;if($("recordingFfmpegStatus"))$("recordingFfmpegStatus").textContent=`FFmpeg: ${capabilities.ffmpeg?.installed?"Detected":"Not detected"}`;if($("recordingObsStatus"))$("recordingObsStatus").textContent=`OBS: ${capabilities.obs?.installed?"Detected":"Not detected"}`;if($("recordingUseTestPreset"))$("recordingUseTestPreset").dataset.command=capabilities.templates?.["ffmpeg-test"]||"";if($("recordingUseDevicePreset"))$("recordingUseDevicePreset").dataset.command=capabilities.templates?.["ffmpeg-device"]||"";const grid=$("recordingBrowserSources");if(grid)grid.replaceChildren(...Object.entries(sources).map(([name,path])=>{const row=document.createElement("article"),url=`${origin}${path}`;row.innerHTML="<div><strong></strong><code></code></div><button type=\"button\">Copy</button>";row.querySelector("strong").textContent=name.replaceAll("_"," ");row.querySelector("code").textContent=url;row.querySelector("button").addEventListener("click",()=>navigator.clipboard.writeText(url).then(()=>notify("URL Copied",url,"success")).catch(()=>notify("Copy Failed","Select and copy the displayed URL.","error")));return row;}));}
async function loadRecordingSettings(){const payload=await api("/api/production/recording/settings");renderRecordingSettings(payload);renderEncoderGuide(payload);return payload;}
async function saveRecordingSettings(event){event.preventDefault();const payload=await api("/api/production/recording/settings",{method:"POST",body:JSON.stringify({preset:$("recordingPreset")?.value||"balanced",minimum_free_gb:Number($("recordingMinimumFree")?.value)||2,output_dir:$("recordingOutputDir")?.value.trim()||"recordings",command_template:$("recordingCommand")?.value.trim()||""})});renderRecordingSettings(payload.settings);notify("Recording Settings Saved","Run a test before relying on the encoder during a show.","success");}
async function testRecordingSettings(){if($("recordingTest"))$("recordingTest").disabled=true;if($("recordingTestResult"))$("recordingTestResult").textContent="Testing encoder for two seconds…";try{const payload=await api("/api/production/recording/test",{method:"POST"});if($("recordingTestResult"))$("recordingTestResult").textContent=payload.test?.verified?`Verified · ${payload.test.output_bytes} bytes written`:"Test finished but output could not be verified";notify(payload.test?.verified?"Recording Verified":"Recording Unverified",payload.test?.output_path||"Check encoder configuration.",payload.test?.verified?"success":"error");}finally{if($("recordingTest"))$("recordingTest").disabled=false;await loadRecordingSettings();}}
function sessionTime(seconds){const value=Math.max(0,Math.floor(seconds));return [Math.floor(value/3600),Math.floor(value%3600/60),value%60].map(item=>String(item).padStart(2,"0")).join(":");}
function productionMetadataPayload(){return{name:$("productionSessionName")?.value.trim()||"",customer:$("productionSessionCustomer")?.value.trim()||"",break_id:$("productionSessionBreakId")?.value.trim()||"",operator_notes:$("productionSessionNotes")?.value.trim()||""}}
async function saveProductionSessionMetadata(event){event?.preventDefault();const payload=await api("/api/production/session/metadata",{method:"POST",body:JSON.stringify(productionMetadataPayload())});renderProductionSession(payload);notify("Session Details Saved","Archive and reports will use these identifiers.","success");}
function renderProductionSession(payload={}){productionSessionState=payload.session||productionSessionState;const active=Boolean(productionSessionState.active),events=productionSessionState.events||[];if($("productionSessionTitle"))$("productionSessionTitle").textContent=active?"Production Session Live":"Show Not Started";if($("productionSessionStart"))$("productionSessionStart").disabled=active;if($("productionSessionStop"))$("productionSessionStop").disabled=!active;if($("productionRecordingStatus"))$("productionRecordingStatus").textContent=productionSessionState.recording?.configured?(productionSessionState.recording.active?"Recording hook: active":"Recording hook: ready"):"Recording hook: not configured";if($("productionEventLog"))$("productionEventLog").replaceChildren(...(events.length?events.slice().reverse().slice(0,25).map(event=>{const row=document.createElement("article");row.innerHTML="<div><strong></strong><small></small></div><span></span>";row.querySelector("strong").textContent=event.title;row.querySelector("small").textContent=event.detail||event.kind;row.querySelector("span").textContent=new Date(event.timestamp*1000).toLocaleTimeString();return row;}):[Object.assign(document.createElement("p"),{textContent:"No session events yet."})]));updateProductionSessionClock();}
function updateProductionSessionClock(){const elapsed=productionSessionState.started_at?((productionSessionState.active?Date.now()/1000:productionSessionState.ended_at||Date.now()/1000)-productionSessionState.started_at):0;if($("productionSessionClock"))$("productionSessionClock").textContent=sessionTime(elapsed);}
async function loadProductionSession(){const payload=await api("/api/production/session");renderProductionSession(payload);if(!productionSessionTimer)productionSessionTimer=setInterval(updateProductionSessionClock,1000);return payload;}
async function setProductionSession(active){if(!active)return stopProductionShow();const payload=await api("/api/production/session/start",{method:"POST",body:JSON.stringify(productionMetadataPayload())});renderProductionSession(payload);notify("Session Started","Operator logging is active.","success");}
async function stopProductionShow(){if(!confirm("End the show, stop active RareIQ/OBS recording and streaming, clear output layers, and finalize the production report?"))return null;const button=$("productionSessionStop"),status=$("productionSessionEndStatus");if(button)button.disabled=true;if(status){status.hidden=false;status.dataset.state="working";status.textContent="Ending show safely…";}try{const payload=await api("/api/production/show/stop",{method:"POST"});renderProductionSession(payload);renderProductionSwitcher(payload.safe||{});renderObsStatus(payload.obs||{});const steps=payload.steps||[];if(status){status.dataset.state=steps.some(step=>step.state==="warn")?"warning":"complete";status.innerHTML=steps.map(step=>`<span data-state="${escapeHtml(step.state)}">${step.state==="pass"?"✓":step.state==="warn"?"!":"–"} ${escapeHtml(step.detail)}</span>`).join("");}notify("Show Ended","Outputs are safe and the production report is finalized.","success");await Promise.all([loadShowPreflight(),loadOperatorHealth(),loadShowAnalytics(),loadBreakHistory()]);return payload;}catch(error){if(status){status.dataset.state="error";status.textContent=error.message||String(error);}throw error;}finally{if(button)button.disabled=!productionSessionState.active;}}
async function markProductionIncident(event){event.preventDefault();const title=$("productionIncidentTitle")?.value.trim();if(!title)return;const payload=await api("/api/production/session/events",{method:"POST",body:JSON.stringify({kind:"incident",title,detail:$("productionIncidentDetail")?.value.trim()||""})});renderProductionSession(payload);event.target.reset();notify("Event Marked",title,"success");}
async function logProductionEvent(kind,title,detail=""){if(!productionSessionState.active)return null;try{const payload=await api("/api/production/session/events",{method:"POST",body:JSON.stringify({kind,title,detail})});renderProductionSession(payload);return payload.event;}catch{return null;}}
function healthCard(name,state){const card=document.querySelector(`[data-health="${name}"]`);if(card)card.dataset.state=state;}
function renderOperatorHealth(payload={}){const sessions=payload.sessions||[],connected=Number(payload.connected_cameras)||0,configured=Number(payload.configured_cameras)||0,program=Number(payload.program_slot)||1,replaySeconds=Math.round(Number(payload.replay_buffered_frames||0)/Math.max(1,Number(payload.replay_fps)||5)),recognition=String(payload.recognition_state||"ready").replaceAll("_"," "),confidence=Math.round(Number(payload.recognition_confidence||0)*((Number(payload.recognition_confidence||0)<=1)?100:1)),audioActive=(soundboardQueue?.length||0)>0||Boolean(spotifyState?.playback?.is_playing),layers=[];if(payload.production_screen_visible)layers.push("Screen");if(payload.graphic_visible)layers.push("Graphic");if($("operatorCameraHealth"))$("operatorCameraHealth").textContent=`${connected}/${configured||sessions.length||0} Online`;if($("operatorCameraDetail"))$("operatorCameraDetail").textContent=configured?"Configured production sources":"No cameras configured";if($("operatorProgramHealth"))$("operatorProgramHealth").textContent=`Camera ${program}`;if($("operatorSceneDetail"))$("operatorSceneDetail").textContent=payload.active_scene_id||"Manual switcher";if($("operatorRecognitionHealth"))$("operatorRecognitionHealth").textContent=recognition;if($("operatorRecognitionDetail"))$("operatorRecognitionDetail").textContent=`${confidence}% confidence`;if($("operatorAudioHealth"))$("operatorAudioHealth").textContent=audioActive?"Active":"Idle";if($("operatorAudioDetail"))$("operatorAudioDetail").textContent=spotifyState?.playback?.is_playing?"Spotify playing":soundboardQueue?.length?`${soundboardQueue.length} sound(s) queued`:"Outputs ready";if($("operatorReplayHealth"))$("operatorReplayHealth").textContent=replaySeconds>=3?"Ready":"Buffering";if($("operatorReplayDetail"))$("operatorReplayDetail").textContent=`${replaySeconds}s rolling buffer`;if($("operatorOutputHealth"))$("operatorOutputHealth").textContent=layers.length?layers.join(" + "):"Clean";if($("operatorOutputDetail"))$("operatorOutputDetail").textContent=layers.length?"Active on browser output":"No takeover active";healthCard("cameras",connected>0||configured===0?"good":"bad");healthCard("recognition",recognition.includes("error")?"bad":"good");healthCard("replay",replaySeconds>=3?"good":"warn");healthCard("output",layers.length?"active":"good");const unhealthy=configured>0&&connected===0;if($("operatorHealthSummary"))$("operatorHealthSummary").textContent=unhealthy?"ACTION REQUIRED":"SYSTEMS READY";if($("operatorHealthUpdated"))$("operatorHealthUpdated").textContent=`Updated ${new Date().toLocaleTimeString()}`;}
async function loadOperatorHealth(){const payload=await api("/api/production/operator-health");renderOperatorHealth(payload);if(!operatorHealthTimer)operatorHealthTimer=setInterval(()=>{if(document.hidden!==true&&document.body.dataset.ui4Workspace==="broadcast")loadOperatorHealth().catch(()=>{});},3000);return payload;}
function renderShowPreflight(payload={}){const preflight=payload.preflight||{},checks=preflight.checks||[],blockers=preflight.blockers||[],warnings=preflight.warnings||[],ready=Boolean(preflight.ready),root=$("showPreflight");if(root)root.dataset.state=ready?"ready":"blocked";if($("showPreflightVerdict"))$("showPreflightVerdict").textContent=ready?"READY TO GO LIVE":"NOT READY";if($("showPreflightSummary"))$("showPreflightSummary").textContent=ready?(warnings.length?"Core systems are ready. Review optional warnings before air.":"All production systems passed."):`${blockers.length} blocking issue${blockers.length===1?"":"s"} must be fixed before air.`;if($("showPreflightCounts"))$("showPreflightCounts").textContent=`${blockers.length} blocker${blockers.length===1?"":"s"} · ${warnings.length} warning${warnings.length===1?"":"s"}`;if($("showPreflightUpdated"))$("showPreflightUpdated").textContent=`Checked ${new Date((Number(preflight.checked_at)||Date.now()/1000)*1000).toLocaleTimeString()}`;if($("showStartButton"))$("showStartButton").disabled=!ready||Boolean(productionSessionState.active);if($("showStartProgress"))$("showStartProgress").textContent=ready?"Ready. Startup will reset the output to Main Card first.":"Preflight must pass before startup.";if($("showPreflightChecks"))$("showPreflightChecks").innerHTML=checks.map(check=>`<article data-state="${escapeHtml(check.state||"warn")}"><i>${check.state==="pass"?"✓":check.state==="fail"?"!":"•"}</i><div><strong>${escapeHtml(check.label||"Check")}</strong><span>${escapeHtml(check.detail||"")}</span>${check.action?`<small>${escapeHtml(check.action)}</small>`:""}</div><b>${escapeHtml(String(check.state||"warn").toUpperCase())}</b></article>`).join("")||"<p>No preflight checks returned.</p>";}
async function loadShowPreflight(){const payload=await api("/api/production/preflight");renderShowPreflight(payload);return payload;}
async function startProductionShow(){const button=$("showStartButton"),progress=$("showStartProgress");if(button)button.disabled=true;if(progress)progress.textContent="Starting show · securing Main Card output…";try{const payload=await api("/api/production/show/start",{method:"POST",body:JSON.stringify({...productionMetadataPayload(),start_obs_stream:Boolean($("showStartObsStream")?.checked),start_obs_recording:Boolean($("showStartObsRecording")?.checked)})});renderProductionSession(payload);renderProductionSwitcher(payload.safe||{});renderObsStatus(payload.obs||{});if(progress)progress.textContent=(payload.steps||[]).map(step=>`${step.state==="pass"?"✓":step.state==="warn"?"!":"–"} ${step.detail}`).join(" · ");notify("Show Started",`${(payload.steps||[]).filter(step=>step.state==="pass").length} startup steps completed.`,"success");await Promise.all([loadShowPreflight(),loadOperatorHealth()]);return payload;}catch(error){if(error.payload?.preflight)renderShowPreflight({preflight:error.payload.preflight});if(progress)progress.textContent=error.payload?.reason==="preflight_blocked"?"Startup blocked. Resolve the failed preflight checks.":error.message||String(error);throw error;}finally{if(button&&!productionSessionState.active)button.disabled=$("showPreflight")?.dataset.state!=="ready";}}
async function activateOperatorSafeScene(){stopProductionRundown();stopAllSoundboardAudio();const state=await api("/api/production/safe",{method:"POST"});renderProductionSwitcher(state);renderProductionScreen(state.screen||{});await loadOperatorHealth();const detail=state.obs_warning?`Local recovery complete; OBS warning: ${state.obs_warning}`:"Camera 1 live; overlays, replay, automation, sounds, and mapped OBS output restored";logProductionEvent("safety","SAFE recovery activated",detail);notify(state.obs_warning?"Safe Scene · OBS Attention":"Safe Scene Active",state.obs_warning?"RareIQ recovered locally, but OBS did not confirm the mapped Main scene.":"Camera 1 and mapped OBS Main are live; takeover layers and automation are stopped.",state.obs_warning?"warning":"success");}
let productionRundown=[],productionRundownIndex=0,productionRundownTimer=0,productionRundownRunning=false;
const productionRundownKey="rareiq.production.rundown.v1";
const productionRundownTemplatesKey="rareiq.production.rundown.templates.v1";
function productionRundownTemplates(){try{const value=JSON.parse(localStorage.getItem(productionRundownTemplatesKey)||"{}");return value&&typeof value==="object"?value:{};}catch{return {};}}
function renderRundownTemplates(){const select=$("rundownTemplateSelect"),templates=productionRundownTemplates();if(select)select.replaceChildren(new Option("Current rundown",""),...Object.keys(templates).sort().map(name=>new Option(name,name)));}
function saveRundownTemplate(){const name=$("rundownTemplateName")?.value.trim();if(!name)return notify("Template Name Required","Name this rundown before saving.","error");const templates=productionRundownTemplates();templates[name]={name,cues:structuredClone(productionRundown),saved_at:new Date().toISOString()};localStorage.setItem(productionRundownTemplatesKey,JSON.stringify(templates));renderRundownTemplates();if($("rundownTemplateSelect"))$("rundownTemplateSelect").value=name;notify("Template Saved",`${name} · ${productionRundown.length} cues`,"success");}
function loadRundownTemplate(){const name=$("rundownTemplateSelect")?.value,template=productionRundownTemplates()[name];if(!template)return;productionRundown=structuredClone(template.cues||[]);productionRundownIndex=0;saveProductionRundown();renderProductionRundown();notify("Template Loaded",name,"success");}
function duplicateProductionCue(){const cue=productionRundown[productionRundownIndex];if(!cue)return;productionRundown.splice(productionRundownIndex+1,0,{...structuredClone(cue),id:crypto.randomUUID?.()||String(Date.now()),label:`${cue.label} Copy`});productionRundownIndex++;saveProductionRundown();renderProductionRundown();}
function exportProductionRundown(){const payload={schema:"rareiq-rundown-v1",exported_at:new Date().toISOString(),cues:productionRundown};const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:"application/json"})),link=document.createElement("a");link.href=url;link.download=`rareiq-rundown-${new Date().toISOString().slice(0,10)}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function importProductionRundown(file){const payload=JSON.parse(await file.text());if(payload.schema!=="rareiq-rundown-v1"||!Array.isArray(payload.cues))throw new Error("This is not a RareIQ rundown file");productionRundown=payload.cues.slice(0,100).filter(cue=>cue&&typeof cue.type==="string");productionRundownIndex=0;saveProductionRundown();renderProductionRundown();}
async function preflightProductionRundown(){const issues=[],warnings=[],replay=productionRundown.some(cue=>cue.type==="replay")?await loadProductionReplay().catch(()=>({highlights:[]})):null;productionRundown.forEach((cue,index)=>{const label=`Cue ${index+1} (${cue.label||cue.type})`;if(cue.type==="scene"&&!productionScenes.some(scene=>scene.id===cue.target))issues.push(`${label}: scene is unavailable`);if(cue.type==="replay"&&!replay?.highlights?.length)issues.push(`${label}: no replay highlight is ready`);if(cue.type==="graphic"&&cue.target!=="hide"&&!$("productionGraphicTitle")?.value.trim())warnings.push(`${label}: configured graphic has no title`);if(Number(cue.delay_seconds)>300)warnings.push(`${label}: delay exceeds five minutes`);if(cue.auto_follow&&index===productionRundown.length-1)warnings.push(`${label}: auto-follow has no next cue`);if(!["scene","screen","graphic","replay","live","sound-stop","wait"].includes(cue.type))issues.push(`${label}: unsupported cue type`);});const result=$("rundownPreflightResults");if(result){result.hidden=false;result.classList.toggle("has-errors",issues.length>0);result.replaceChildren(Object.assign(document.createElement("strong"),{textContent:issues.length?`BLOCKED · ${issues.length} issue${issues.length===1?"":"s"}`:`READY · ${productionRundown.length} cues checked`}),...issues.map(text=>Object.assign(document.createElement("p"),{textContent:`✕ ${text}`})),...warnings.map(text=>Object.assign(document.createElement("p"),{textContent:`⚠ ${text}`})));}return {ok:issues.length===0,issues,warnings};}
function saveProductionRundown(){localStorage.setItem(productionRundownKey,JSON.stringify({cues:productionRundown,index:productionRundownIndex}));}
function loadProductionRundown(){try{const saved=JSON.parse(localStorage.getItem(productionRundownKey)||"{}");productionRundown=Array.isArray(saved.cues)?saved.cues.slice(0,100):[];productionRundownIndex=Math.min(Math.max(0,Number(saved.index)||0),Math.max(0,productionRundown.length-1));}catch{productionRundown=[];productionRundownIndex=0;}renderProductionRundown();}
function rundownTargets(type){if(type==="scene")return productionScenes.map(scene=>({value:scene.id,label:scene.name}));if(type==="screen")return Object.keys(productionScreenPresets).map(value=>({value,label:productionScreenPresets[value].title}));if(type==="graphic")return [{value:"current",label:"Current configured graphic"},{value:"hide",label:"Hide graphic"}];return [{value:"default",label:type==="replay"?"Most recent highlight":"Immediate"}];}
function renderRundownTargets(){const select=$("rundownCueTarget"),items=rundownTargets($("rundownCueType")?.value||"scene");if(select)select.replaceChildren(...items.map(item=>new Option(item.label,item.value)));}
function renderProductionRundown(){const list=$("productionRundownList");if(!list)return;list.replaceChildren(...(productionRundown.length?productionRundown.map((cue,index)=>{const row=document.createElement("li");row.draggable=true;row.dataset.index=String(index);row.classList.toggle("is-next",index===productionRundownIndex);row.innerHTML=`<button type="button" class="rundown-handle" aria-label="Reorder cue">⋮⋮</button><span></span><strong></strong><button type="button" class="rundown-remove" aria-label="Remove cue">×</button>`;row.querySelector("span").textContent=String(index+1).padStart(2,"0");row.querySelector("strong").textContent=cue.label||`${cue.type}: ${cue.target}`;row.addEventListener("click",event=>{if(event.target.closest(".rundown-remove"))return;productionRundownIndex=index;saveProductionRundown();renderProductionRundown();});row.querySelector(".rundown-remove").addEventListener("click",()=>{productionRundown.splice(index,1);productionRundownIndex=Math.min(productionRundownIndex,Math.max(0,productionRundown.length-1));saveProductionRundown();renderProductionRundown();});row.addEventListener("dragstart",event=>event.dataTransfer.setData("text/plain",String(index)));row.addEventListener("dragover",event=>event.preventDefault());row.addEventListener("drop",event=>{event.preventDefault();const from=Number(event.dataTransfer.getData("text/plain"));const [moved]=productionRundown.splice(from,1);productionRundown.splice(index,0,moved);productionRundownIndex=index;saveProductionRundown();renderProductionRundown();});return row;}):[Object.assign(document.createElement("li"),{textContent:"No cues yet — add a scene, screen, graphic, replay, or audio action."})]));if($("rundownStatus"))$("rundownStatus").textContent=productionRundown.length?`Next ${productionRundownIndex+1}/${productionRundown.length} · ${productionRundown[productionRundownIndex]?.label||"Cue"}`:"Ready · 0 cues";}
function addProductionRundownCue(){const type=$("rundownCueType")?.value||"scene",target=$("rundownCueTarget")?.value||"default",fallback=$("rundownCueTarget")?.selectedOptions?.[0]?.textContent||type,label=$("rundownCueLabel")?.value.trim()||fallback,delay_seconds=Math.max(0,Number($("rundownCueDelay")?.value)||0),auto_follow=Boolean($("rundownCueAutoFollow")?.checked);productionRundown.push({id:crypto.randomUUID?.()||String(Date.now()),type,target,label,delay_seconds,auto_follow});if(productionRundown.length===1)productionRundownIndex=0;if($("rundownCueLabel"))$("rundownCueLabel").value="";saveProductionRundown();renderProductionRundown();}
async function executeProductionCue(cue,{rehearsal=false}={}){if(!cue)return;if(rehearsal){await new Promise(resolve=>setTimeout(resolve,Math.min(500,Math.max(100,Number(cue.delay_seconds||0)*1000))));return;}if(cue.type==="wait"){await new Promise(resolve=>{productionRundownTimer=setTimeout(resolve,Math.max(0,Number(cue.delay_seconds||0))*1000);});}else if(cue.type==="scene"){const scene=productionScenes.find(item=>item.id===cue.target);if(!scene)throw new Error("Scene is no longer available");await takeProductionScene(scene);}else if(cue.type==="screen"){applyProductionScreenPreset(cue.target);await takeProductionScreen();}else if(cue.type==="graphic"){await sendProductionGraphic(cue.target==="hide"?"hide":"take");}else if(cue.type==="replay"){const payload=await loadProductionReplay(),latest=payload.highlights?.[0];if(!latest)throw new Error("No replay highlight is ready");await takeProductionReplay(latest.id);}else if(cue.type==="live"){await hideProductionScreen();await stopProductionReplay();}else if(cue.type==="sound-stop")stopAllSoundboardAudio();}
async function goProductionRundown(){const cue=productionRundown[productionRundownIndex];if(!cue||productionRundownRunning)return;productionRundownRunning=true;const rehearsal=Boolean($("rundownRehearsal")?.checked);try{if(cue.type!=="wait"&&Number(cue.delay_seconds)>0)await new Promise(resolve=>{productionRundownTimer=setTimeout(resolve,Number(cue.delay_seconds)*1000);});await executeProductionCue(cue,{rehearsal});const canAdvance=productionRundownIndex<productionRundown.length-1;if(canAdvance)productionRundownIndex++;saveProductionRundown();renderProductionRundown();notify(rehearsal?"Cue Rehearsed":"Cue Fired",cue.label,"success");productionRundownRunning=false;if(cue.auto_follow&&canAdvance)productionRundownTimer=setTimeout(()=>goProductionRundown().catch(error=>notify("Cue Failed",error.message||String(error),"error")),50);}catch(error){productionRundownRunning=false;throw error;}}
function stopProductionRundown(){clearTimeout(productionRundownTimer);productionRundownTimer=0;productionRundownRunning=false;if($("rundownStatus"))$("rundownStatus").textContent="Automation stopped · selected cue preserved";notify("Rundown Stopped","No further cues will auto-follow.","success");}
function stepProductionRundown(delta){productionRundownIndex=Math.min(Math.max(0,productionRundownIndex+delta),Math.max(0,productionRundown.length-1));saveProductionRundown();renderProductionRundown();}
function renderProductionSwitcher(state={}){productionSwitcherState={...productionSwitcherState,...state};const program=Number(productionSwitcherState.program_slot)||1,preview=Number(productionSwitcherState.preview_slot)||2,generation=Number(productionSwitcherState.generation)||0;if($("productionProgramLabel"))$("productionProgramLabel").textContent=`Camera ${program}`;if($("productionPreviewLabel"))$("productionPreviewLabel").textContent=`Camera ${preview}`;if($("productionProgramPreview"))$("productionProgramPreview").src=`/api/camera-slots/${program}/stream?g=${generation}`;if($("productionPreviewPreview"))$("productionPreviewPreview").src=`/api/camera-slots/${preview}/stream?g=${generation}`;if($("productionTransition"))$("productionTransition").value=productionSwitcherState.transition||"fade";if($("productionDuration"))$("productionDuration").value=String(productionSwitcherState.duration_ms||500);document.querySelectorAll("[data-production-slot]").forEach(button=>{const slot=Number(button.dataset.productionSlot);button.classList.toggle("is-program",slot===program);button.classList.toggle("is-preview",slot===preview);button.disabled=slot===program;});}
async function loadProductionSwitcher(){const state=await api("/api/production/switcher");renderProductionSwitcher(state);return state;}
function renderProductionScenes(scenes=[]){productionScenes=scenes;const grid=$("productionSceneGrid");if(!grid)return;grid.replaceChildren(...(scenes.length?scenes.map(scene=>{const card=document.createElement("article");card.className="production-scene-card";card.dataset.sceneId=scene.id;card.innerHTML=`<div><span></span><strong></strong><small></small></div><div class="production-scene-actions"></div>`;card.querySelector("span").textContent=`Camera ${scene.program_slot} · ${scene.transition}`;card.querySelector("strong").textContent=scene.name;card.querySelector("small").textContent=`Spotify: ${scene.spotify_action} · Sounds: ${scene.soundboard_action}`;const actions=card.querySelector(".production-scene-actions"),take=document.createElement("button"),edit=document.createElement("button"),remove=document.createElement("button");take.type=edit.type=remove.type="button";take.textContent="TAKE";edit.textContent="Edit";remove.textContent="×";take.addEventListener("click",()=>takeProductionScene(scene).catch(error=>notify("Scene Failed",error.message||String(error),"error")));edit.addEventListener("click",()=>openProductionSceneEditor(scene));remove.addEventListener("click",()=>deleteProductionScene(scene.id).catch(error=>notify("Scene Not Deleted",error.message||String(error),"error")));actions.append(take,edit,remove);return card;}):[Object.assign(document.createElement("p"),{textContent:"No production scenes saved."})]));}
async function loadProductionScenes(){const payload=await api("/api/production/scenes");renderProductionScenes(payload.scenes||[]);return payload;}
function openProductionSceneEditor(scene=null){const current=scene||{id:"",name:"New Scene",program_slot:productionSwitcherState.program_slot,preview_slot:productionSwitcherState.preview_slot,transition:productionSwitcherState.transition,duration_ms:productionSwitcherState.duration_ms,spotify_action:"keep",soundboard_action:"keep"};if($("productionSceneId"))$("productionSceneId").value=current.id||"";if($("productionSceneName"))$("productionSceneName").value=current.name;if($("productionSceneProgram"))$("productionSceneProgram").value=String(current.program_slot);if($("productionScenePreview"))$("productionScenePreview").value=String(current.preview_slot);if($("productionSceneTransition"))$("productionSceneTransition").value=current.transition;if($("productionSceneSpotify"))$("productionSceneSpotify").value=current.spotify_action;if($("productionSceneSoundboard"))$("productionSceneSoundboard").value=current.soundboard_action;if($("productionSceneEditor"))$("productionSceneEditor").hidden=false;}
async function saveProductionScene(event){event.preventDefault();const payload=await api("/api/production/scenes",{method:"POST",body:JSON.stringify({id:$("productionSceneId")?.value||null,name:$("productionSceneName")?.value||"Scene",program_slot:Number($("productionSceneProgram")?.value)||1,preview_slot:Number($("productionScenePreview")?.value)||2,transition:$("productionSceneTransition")?.value||"fade",duration_ms:Number($("productionDuration")?.value)||500,spotify_action:$("productionSceneSpotify")?.value||"keep",soundboard_action:$("productionSceneSoundboard")?.value||"keep"})});renderProductionScenes(payload.scenes||[]);$("productionSceneEditor").hidden=true;notify("Scene Saved",payload.scene?.name||"Production scene saved.","success");}
async function deleteProductionScene(id){const payload=await api(`/api/production/scenes/${encodeURIComponent(id)}`,{method:"DELETE"});renderProductionScenes(payload.scenes||[]);}
async function takeProductionScene(scene){const state=await api(`/api/production/scenes/${encodeURIComponent(scene.id)}/take`,{method:"POST"});renderProductionSwitcher(state);renderProductionScreen(state.screen||{});if(scene.soundboard_action==="stop")stopAllSoundboardAudio();if(scene.spotify_action==="play"||scene.spotify_action==="pause")spotifyCommand(scene.spotify_action).catch(()=>{});document.querySelectorAll(".production-scene-card").forEach(card=>card.classList.toggle("is-live",card.dataset.sceneId===scene.id));logProductionEvent("scene",`Scene: ${scene.name}`,`Camera ${state.program_slot} · ${scene.transition}`);notify("Scene Live",`${scene.name} is now on Program.`,"success");}
async function setProductionPreview(slot){const state=await api("/api/production/switcher/preview",{method:"POST",body:JSON.stringify({preview_slot:Number(slot),transition:$("productionTransition")?.value||"fade",duration_ms:Number($("productionDuration")?.value)||500})});renderProductionSwitcher(state);}
async function takeProductionShot(cut=false){const transition=cut?"cut":$("productionTransition")?.value||"fade",state=await api("/api/production/switcher/take",{method:"POST",body:JSON.stringify({preview_slot:productionSwitcherState.preview_slot,transition,duration_ms:cut?0:Number($("productionDuration")?.value)||500})});renderProductionSwitcher(state);logProductionEvent("camera",`Camera ${state.program_slot} live`,transition);notify(cut?"Camera Cut":"Transition Complete",`Camera ${state.program_slot} is now live.`,"success");}
function handleProductionShortcut(event){if(document.body.dataset.ui4Workspace!=="broadcast"||event.target?.matches("input,select,textarea"))return;if(event.altKey&&/^[1-9]$/.test(event.key)){const scene=productionScenes[Number(event.key)-1];if(scene){event.preventDefault();takeProductionScene(scene).catch(()=>{});}return;}if(event.key.toLowerCase()==="g"){event.preventDefault();goProductionRundown().catch(error=>notify("Cue Failed",error.message||String(error),"error"));}else if(event.code==="Space"){event.preventDefault();takeProductionShot(true).catch(()=>{});}else if(event.key==="Enter"){event.preventDefault();takeProductionShot(false).catch(()=>{});}else if(event.key.toLowerCase()==="b"){event.preventDefault();applyProductionScreenPreset("brb");takeProductionScreen().catch(()=>{});}else if(event.key.toLowerCase()==="l"){event.preventDefault();hideProductionScreen().catch(()=>{});}else if(/^[1-4]$/.test(event.key))setProductionPreview(Number(event.key)).catch(()=>{});}
function productionGraphicPayload(){return {kind:$("productionGraphicKind")?.value||"lower-third",style:$("productionGraphicStyle")?.value||"glass",accent:$("productionGraphicAccent")?.value||"cyan",duration_ms:Number($("productionGraphicDuration")?.value)||0,title:$("productionGraphicTitle")?.value||"",subtitle:$("productionGraphicSubtitle")?.value||"",image_url:$("productionGraphicPreviewFrame")?.dataset.imageUrl||""};}
async function sendProductionGraphic(action){const options={method:"POST"};if(action!=="hide")options.body=JSON.stringify(productionGraphicPayload());const payload=await api(`/api/production/graphics/${action}`,options);if(action!=="preview")logProductionEvent("graphic",action==="hide"?"Graphic hidden":`Graphic: ${payload.graphic?.title||"On air"}`,payload.graphic?.subtitle||"");notify(action==="take"?"Graphic On Air":action==="hide"?"Graphic Hidden":"Graphic Previewed",payload.graphic?.title||"Broadcast graphics updated.","success");return payload;}
function renderProductionReplay(payload={}){if($("productionReplayBuffer"))$("productionReplayBuffer").textContent=`${Math.round((payload.buffered_frames||0)/(payload.fps||5))}s buffered · ${payload.highlights?.length||0} highlights`;const history=$("productionReplayHistory"),items=payload.highlights||[];if(history)history.replaceChildren(...(items.length?items.map(item=>{const card=document.createElement("article");card.className="production-replay-item";card.innerHTML=`<div><strong></strong><span></span></div><button type="button">TAKE REPLAY</button>`;card.querySelector("strong").textContent=item.name;card.querySelector("span").textContent=`${item.duration_seconds}s · Camera ${item.slot_id} · ${new Date(item.created_at*1000).toLocaleTimeString()}`;card.querySelector("button").addEventListener("click",()=>takeProductionReplay(item.id).catch(error=>notify("Replay Failed",error.message||String(error),"error")));return card;}):[Object.assign(document.createElement("p"),{textContent:"No highlights saved yet."})]));}
async function loadProductionReplay(){const payload=await api("/api/production/replay");renderProductionReplay(payload);return payload;}
async function markProductionReplay(){const payload=await api("/api/production/replay/mark",{method:"POST",body:JSON.stringify({seconds:Number($("productionReplayLength")?.value)||8,name:$("productionReplayName")?.value||"Highlight"})});await loadProductionReplay();notify("Highlight Saved",payload.highlight?.name||"Replay is ready.","success");}
async function takeProductionReplay(id){await api("/api/production/replay/take",{method:"POST",body:JSON.stringify({highlight_id:id,speed:Number($("productionReplaySpeed")?.value)||1})});logProductionEvent("replay","Replay on air",id);notify("Replay On Air","The selected highlight is playing.","success");}
async function stopProductionReplay(){await api("/api/production/replay/stop",{method:"POST"});notify("Back To Live","Replay output returned to Program.","success");}
const productionScreenPresets={"starting-soon":{title:"Starting Soon",message:"The stream will begin shortly.",minutes:5,accent:"cyan"},brb:{title:"Be Right Back",message:"We are taking a short break.",minutes:2,accent:"purple"},ending:{title:"Thanks for Watching",message:"Follow and subscribe for the next live card stream.",minutes:0,accent:"gold"},countdown:{title:"Countdown",message:"Get ready — we are almost live.",minutes:10,accent:"green"}};
function applyProductionScreenPreset(mode){const preset=productionScreenPresets[mode]||productionScreenPresets["starting-soon"];if($("productionScreenMode"))$("productionScreenMode").value=mode;if($("productionScreenTitle"))$("productionScreenTitle").value=preset.title;if($("productionScreenMessage"))$("productionScreenMessage").value=preset.message;if($("productionScreenMinutes"))$("productionScreenMinutes").value=String(preset.minutes);if($("productionScreenAccent"))$("productionScreenAccent").value=preset.accent;}
function productionScreenPayload(){return {mode:$("productionScreenMode")?.value||"starting-soon",title:$("productionScreenTitle")?.value||"Starting Soon",message:$("productionScreenMessage")?.value||"",countdown_seconds:Math.max(0,Number($("productionScreenMinutes")?.value)||0)*60,accent:$("productionScreenAccent")?.value||"cyan"};}
async function takeProductionScreen(){const payload=await api("/api/production/screen/take",{method:"POST",body:JSON.stringify(productionScreenPayload())});document.querySelectorAll("[data-production-screen-preset]").forEach(button=>button.classList.toggle("is-live",button.dataset.productionScreenPreset===payload.screen?.mode));logProductionEvent("screen",`Screen: ${payload.screen?.title||"Takeover"}`,payload.screen?.mode||"");notify("Production Screen Live",payload.screen?.title||"Full-screen graphic is on air.","success");}
async function hideProductionScreen(){await api("/api/production/screen/hide",{method:"POST"});document.querySelectorAll("[data-production-screen-preset]").forEach(button=>button.classList.remove("is-live"));notify("Returned To Live","The production screen is hidden.","success");}
function renderProductionScreen(state={}){const mode=String(state.mode||"starting-soon");if($("productionScreenMode"))$("productionScreenMode").value=mode;if($("productionScreenAccent"))$("productionScreenAccent").value=state.accent||"cyan";if($("productionScreenMinutes"))$("productionScreenMinutes").value=String(Math.max(0,Math.round(Number(state.countdown_seconds||0)/60)));if($("productionScreenTitle"))$("productionScreenTitle").value=state.title||"";if($("productionScreenMessage"))$("productionScreenMessage").value=state.message||"";document.querySelectorAll("[data-production-screen-preset]").forEach(button=>{const active=button.dataset.productionScreenPreset===mode&&Boolean(state.visible);button.classList.toggle("is-live",active);button.setAttribute("aria-pressed",String(active));});if($("productionScreenForm"))$("productionScreenForm").classList.toggle("is-on-air",Boolean(state.visible));}
async function loadProductionScreen(){const state=await api("/api/production/screen");renderProductionScreen(state);return state;}
function fillProductionGraphicFromCard(){const card=latestState?.current_card||latestState?.primary_candidate||latestState?.card||{};const name=card.english_name||card.name||card.printed_name||"Current Card",set=card.set_name||card.set||"",number=card.collector_number||card.card_number||card.local_card_id||"",image=card.image_url||card.reference_image_url||card.artwork_url||"";if($("productionGraphicKind"))$("productionGraphicKind").value="card";if($("productionGraphicTitle"))$("productionGraphicTitle").value=name;if($("productionGraphicSubtitle"))$("productionGraphicSubtitle").value=[set,number].filter(Boolean).join(" · ")||"Live card recognition";if($("productionGraphicPreviewFrame"))$("productionGraphicPreviewFrame").dataset.imageUrl=image;}

let spotifyState={configured:false,connected:false,playback:null,devices:[],queue:[]},spotifyRefreshTimer=0,spotifyDuckedVolume=null;
function spotifyTime(ms){const seconds=Math.max(0,Math.floor((Number(ms)||0)/1000));return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`;}
function renderSpotifyError(message){["spotifyResults","spotifyPlaylists"].forEach(id=>{if($(id))$(id).innerHTML=`<p>${escapeHtml(message)}</p>`;});}
function renderSpotifySetup(payload={}){const card=$("spotifySetupCard"),configured=payload.configured===true;if(card)card.hidden=configured;if($("spotifyClientId"))$("spotifyClientId").value=payload.client_id||"";if($("spotifyRedirectUri"))$("spotifyRedirectUri").value=payload.redirect_uri||"http://127.0.0.1:8765/api/spotify/callback";if($("spotifyDeveloperDashboard")&&payload.developer_dashboard_url)$("spotifyDeveloperDashboard").href=payload.developer_dashboard_url;if($("spotifySetupStatus"))$("spotifySetupStatus").textContent=configured?"Client ID saved":"Setup required";["spotifyConnect","spotifyToolConnect"].forEach(id=>{const button=$(id);if(button){button.dataset.configured=String(configured);button.textContent=payload.connected?`Connected${payload.profile?.display_name?` · ${payload.profile.display_name}`:""}`:configured?"Authorize Spotify":"Set Up Spotify";}})}
async function saveSpotifySetup(){const button=$("spotifySaveSetup"),clientId=$("spotifyClientId")?.value?.trim()||"",redirectUri=$("spotifyRedirectUri")?.value?.trim()||"";if(!clientId)throw new Error("Paste the Client ID from your Spotify developer app.");if(button){button.disabled=true;button.textContent="Saving…"}try{const payload=await api("/api/spotify/setup",{method:"POST",body:JSON.stringify({client_id:clientId,redirect_uri:redirectUri})});renderSpotifySetup(payload);notify("Spotify Setup Saved","Opening Spotify authorization…","success");window.location.assign("/api/spotify/connect")}finally{if(button){button.disabled=false;button.textContent="Save & Continue"}}}
async function startSpotifyConnection(event){event?.preventDefault?.();const payload=await api("/api/spotify/setup",{retries:0});renderSpotifySetup(payload);if(!payload.configured){switchWorkspace("spotify");$("spotifySetupCard")?.scrollIntoView({behavior:"smooth",block:"start"});notify("Spotify Setup Required","Create a Spotify developer app and paste its Client ID.","error");return}window.location.assign("/api/spotify/connect")}
function renderSpotify(payload={}){spotifyState=payload;const playback=payload.playback||{},item=playback.item||{},image=item.album?.images?.[0]?.url||"",artist=(item.artists||[]).map(value=>value.name).join(", ")||"Connect your account to begin",duration=Number(item.duration_ms)||0,progress=Number(playback.progress_ms)||0,percent=duration?Math.min(100,progress/duration*100):0;[["spotifyTrackName","spotifyArtistName","spotifyAlbumArt","spotifyAlbumPlaceholder","spotifyProgress","spotifyTime"],["spotifyToolTrack","spotifyToolArtist","spotifyToolArt",null,"spotifyToolProgress",null]].forEach(([trackId,artistId,artId,placeholderId,progressId,timeId])=>{if($(trackId))$(trackId).textContent=item.name||(!payload.configured?"Spotify setup required":"Spotify not connected");if($(artistId))$(artistId).textContent=artist;if($(artId)){if(image){$(artId).src=image;$(artId).hidden=false}else $(artId).hidden=true;}if(placeholderId&&$(placeholderId))$(placeholderId).hidden=Boolean(image);if($(progressId))$(progressId).style.width=`${percent}%`;if(timeId&&$(timeId))$(timeId).textContent=`${spotifyTime(progress)} / ${spotifyTime(duration)}`;});["spotifyConnect","spotifyToolConnect"].forEach(id=>{const button=$(id);if(button)button.textContent=payload.connected?`Connected${payload.profile?.display_name?` · ${payload.profile.display_name}`:""}`:"Connect Spotify";});const devices=$("spotifyDevice");if(devices){devices.replaceChildren(...((payload.devices||[]).length?payload.devices.map(device=>new Option(`${device.name}${device.is_active?" · Active":""}`,device.id)):[new Option("No Spotify device available","")]));devices.value=(payload.devices||[]).find(device=>device.is_active)?.id||devices.value;}if($("spotifyVolume"))$("spotifyVolume").value=String(playback.device?.volume_percent??50);if(!payload.configured)renderSpotifyError("Set SPOTIFY_CLIENT_ID and restart RareIQ to connect Spotify.");}
function renderSpotifyEnhancements(){const playback=spotifyState.playback||{},queue=spotifyState.queue||[],isPlaying=playback.is_playing===true;if($("spotifyPlay"))$("spotifyPlay").textContent=isPlaying?"❚❚":"▶";if($("spotifyToolPlay"))$("spotifyToolPlay").textContent=isPlaying?"❚❚":"▶";if($("spotifyShuffle")){$("spotifyShuffle").setAttribute("aria-pressed",String(playback.shuffle_state===true));$("spotifyShuffle").classList.toggle("active",playback.shuffle_state===true);}if($("spotifyRepeat")){$("spotifyRepeat").dataset.repeat=playback.repeat_state||"off";$("spotifyRepeat").textContent=`Repeat ${playback.repeat_state||"off"}`;}if($("spotifyQueueCount"))$("spotifyQueueCount").textContent=`${queue.length} tracks`;if($("spotifyQueue"))$("spotifyQueue").replaceChildren(...(queue.length?queue.map(item=>spotifyResultCard(item,"queue")):[Object.assign(document.createElement("p"),{textContent:"Spotify's upcoming tracks will appear here."})]));const duck=localStorage.getItem("rareiq.spotify.duckSoundboard")==="true";["spotifyDuckEnabled","spotifyAppDuckEnabled"].forEach(id=>{if($(id))$(id).checked=duck;});}
async function loadSpotify(){const payload=await api("/api/spotify/status");renderSpotifySetup(payload);renderSpotify(payload);renderSpotifyEnhancements();if(payload.connected&&!spotifyRefreshTimer)spotifyRefreshTimer=setInterval(()=>{if(document.hidden!==true)loadSpotify().catch(()=>{})},5000);if(payload.connected)loadSpotifyPlaylists().catch(()=>{});return payload;}
async function spotifyCommand(action,extra={}){await api("/api/spotify/player",{method:"POST",body:JSON.stringify({action,device_id:$("spotifyDevice")?.value||null,...extra})});setTimeout(()=>loadSpotify().catch(()=>{}),250);}
function spotifyResultCard(item,type="track"){const card=document.createElement("article");card.className="spotify-result-card";const image=item.album?.images?.[0]?.url||item.images?.[0]?.url;if(image){const img=document.createElement("img");img.src=image;img.alt="";card.append(img);}const copy=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("span");name.textContent=item.name||"Untitled";meta.textContent=type==="track"||type==="queue"?(item.artists||[]).map(value=>value.name).join(", "):`${item.tracks?.total||0} tracks`;copy.append(name,meta);const actions=document.createElement("span");if(type==="track")[["Play","play"],["Queue","queue"]].forEach(([label,action])=>{const button=document.createElement("button");button.type="button";button.textContent=label;button.addEventListener("click",()=>spotifyCommand(action,{uri:item.uri}).catch(error=>notify("Spotify Command Failed",error.message||String(error),"error")));actions.append(button);});if(type==="playlist"){const button=document.createElement("button");button.type="button";button.textContent="Play";button.addEventListener("click",()=>spotifyCommand("play",{uri:item.uri}).catch(error=>notify("Spotify Playlist Failed",error.message||String(error),"error")));actions.append(button);}card.append(copy,actions);return card;}
function setSpotifyDucking(enabled){localStorage.setItem("rareiq.spotify.duckSoundboard",String(Boolean(enabled)));["spotifyDuckEnabled","spotifyAppDuckEnabled"].forEach(id=>{if($(id))$(id).checked=Boolean(enabled);});}
function cycleSpotifyRepeat(){const current=spotifyState.playback?.repeat_state||"off",next=current==="off"?"context":current==="context"?"track":"off";spotifyCommand("repeat",{repeat_state:next}).catch(error=>notify("Spotify Repeat Failed",error.message||String(error),"error"));}
async function searchSpotify(query){const payload=await api(`/api/spotify/search?q=${encodeURIComponent(query)}`),results=$("spotifyResults"),tracks=payload.results?.tracks?.items||[],playlists=(payload.results?.playlists?.items||[]).filter(Boolean);if(results)results.replaceChildren(...tracks.map(item=>spotifyResultCard(item,"track")),...playlists.map(item=>spotifyResultCard(item,"playlist")));}
async function loadSpotifyPlaylists(){const payload=await api("/api/spotify/playlists"),items=(payload.playlists?.items||[]).filter(Boolean);if($("spotifyPlaylists"))$("spotifyPlaylists").replaceChildren(...items.map(item=>spotifyResultCard(item,"playlist")));}

function renderRevealSequence(state={}){
  const config=state.config||{};
  if($("creatorRevealEnabled")) $("creatorRevealEnabled").checked=config.enabled!==false;
  if($("creatorBuildSuspense")) $("creatorBuildSuspense").checked=config.build_suspense!==false;
  if($("creatorAudioEnabled")) $("creatorAudioEnabled").checked=config.audio_enabled===true;
  if($("creatorAnimationsEnabled")) $("creatorAnimationsEnabled").checked=config.animations_enabled!==false;
  if($("creatorParticlesEnabled")) $("creatorParticlesEnabled").checked=config.particles_enabled!==false;
  if($("creatorFlashEnabled")) $("creatorFlashEnabled").checked=config.flash_enabled!==false;
  if($("creatorMinimumAnimationTier")) $("creatorMinimumAnimationTier").value=config.minimum_animation_tier||"low";
  if($("creatorAnimationIntensity")) $("creatorAnimationIntensity").value=Number(config.animation_intensity??75);
  if($("creatorIntensityValue")) $("creatorIntensityValue").textContent=`${Number(config.animation_intensity??75)}%`;
  if($("creatorAnimationDuration")) $("creatorAnimationDuration").value=String(config.animation_duration_ms||3200);
  if($("creatorExpectedCards")) $("creatorExpectedCards").value=Number(config.expected_cards||state.expected_cards||6);
  if($("creatorRareSlot")) $("creatorRareSlot").value=Number(config.rare_slot||state.rare_slot||6);
  if($("creatorMediumValueThreshold")) $("creatorMediumValueThreshold").value=Number(config.medium_value_threshold??25);
  if($("creatorGrailValueThreshold")) $("creatorGrailValueThreshold").value=Number(config.grail_value_threshold??150);
  if($("creatorArmingDelay")) $("creatorArmingDelay").value=String(config.arming_delay_ms??0);
  const copy=config.reaction_copy||{};
  if($("creatorStandardCopy")) $("creatorStandardCopy").value=copy.standard||"Aww — next pack!";
  if($("creatorLowCopy")) $("creatorLowCopy").value=copy.low||"Nice pull!";
  if($("creatorMediumCopy")) $("creatorMediumCopy").value=copy.medium||"YES! BIG HIT!";
  if($("creatorGrailCopy")) $("creatorGrailCopy").value=copy.grail||"OH MY GOD — GRAIL HIT!";
  if($("creatorGrailPreset")) $("creatorGrailPreset").value=config.custom_grail_preset==="none"?"":config.custom_grail_preset||"";
  if($("creatorSuspenseValue")) $("creatorSuspenseValue").textContent=`${Number(state.suspense_percent||0)}%`;
  if($("creatorSuspenseBar")) $("creatorSuspenseBar").style.width=`${Number(state.suspense_percent||0)}%`;
  if($("creatorRevealPhase")) $("creatorRevealPhase").textContent=`Pack ${Number(state.pack_number||1)} · ${state.phase||"ready"} · card ${Number(state.position||0)} of ${Number(state.expected_cards||6)}`;
  const current=state.current_card||null;
  const tier=String(state.reaction_tier||current?.hit_tier||"standard");
  const reasonLabels={operator_override:"Operator override",verified_market_value:"Verified market value",grail_catalog_classification:"Catalog grail classification",catalog_rarity:"Verified catalog rarity",no_qualifying_hit_evidence:"No qualifying hit evidence"};
  if($("creatorHitDecision")) $("creatorHitDecision").dataset.tier=tier;
  if($("creatorHitTier")) $("creatorHitTier").textContent=current?({standard:"Standard pull",low:"Rare",medium:"Big Hit",grail:"Grail"}[tier]||tier):"No hit classified";
  if($("creatorHitReason")) $("creatorHitReason").textContent=current?(reasonLabels[current.hit_reason]||"Verified recognition evidence"):"Waiting for verified card evidence";
  if($("creatorHitValue")) $("creatorHitValue").textContent=current?.market_value!=null?`Verified value · ${money(current.market_value)}`:"Value unavailable · rarity fallback active";
  const arming=state.arming||{};
  if($("creatorRevealArming")) $("creatorRevealArming").hidden=!arming.active;
  if($("creatorArmingCountdown")) $("creatorArmingCountdown").textContent=arming.active?`Revealing in ${(Number(arming.countdown_ms||0)/1000).toFixed(1)}s`:arming.cancelled?"Reveal cancelled":"Not armed";
  if($("creatorReactionPreview")) $("creatorReactionPreview").textContent=state.reaction_copy||state.current_card?.card_name||"Waiting for the first verified card.";
  const history=$("creatorRevealHistory"),historyItems=Array.isArray(state.history)?state.history:[];
  if(history)history.replaceChildren(...(historyItems.length?historyItems.map(item=>{const row=document.createElement("div");row.className="creator-reveal-history-row";row.dataset.tier=item.hit_tier||"standard";const copy=document.createElement("div");const title=document.createElement("strong");title.textContent=item.card_name||"Verified card";const meta=document.createElement("small");const value=item.market_value!=null?` · ${money(item.market_value)}`:"";meta.textContent=`${({low:"Rare",medium:"Big Hit",grail:"Grail",standard:"Standard"}[item.hit_tier]||item.hit_tier)} · Pack ${item.pack_number}${value} · ${new Date(Number(item.verified_at||0)*1000).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"})}`;copy.append(title,meta);const replay=document.createElement("button");replay.className="riq-button";replay.type="button";replay.textContent="Replay";replay.addEventListener("click",()=>replayCreatorReveal(item.reveal_id));row.append(copy,replay);return row;}):[Object.assign(document.createElement("p"),{textContent:"No reveals yet."})]));
  const slots=$("creatorSequenceSlots");
  if(slots) slots.replaceChildren(...Array.from({length:Number(state.expected_cards||6)},(_,index)=>{const item=document.createElement("i");item.className=index<Number(state.position||0)?"done":"";item.textContent=String(index+1);return item;}));
}

async function loadRevealSequence(){
  const payload=await api("/api/creator/reveal-sequence");
  renderRevealSequence(payload.state||{});
  return payload;
}

function renderLiveRevealAnimationTool(state={}){const config=state.config||{},enabled=config.animations_enabled!==false;if($("liveRevealAnimationsEnabled"))$("liveRevealAnimationsEnabled").checked=enabled;if($("liveRevealAnimationState"))$("liveRevealAnimationState").textContent=enabled?"On":"Off";if($("liveRevealMinimumTier"))$("liveRevealMinimumTier").textContent=({low:"Rare+",medium:"Big Hit+",grail:"Grail only"}[config.minimum_animation_tier]||"Rare+");if($("liveRevealCountdown"))$("liveRevealCountdown").textContent=Number(config.arming_delay_ms||0)?`${Number(config.arming_delay_ms)/1000}s`:"Instant";if($("liveRevealSoundEnabled"))$("liveRevealSoundEnabled").checked=config.audio_enabled===true;if($("liveRevealParticlesEnabled"))$("liveRevealParticlesEnabled").checked=config.particles_enabled!==false;if($("liveRevealFlashEnabled"))$("liveRevealFlashEnabled").checked=config.flash_enabled!==false;setStudioXWidgetState("reveal-animations",enabled?"available":"unavailable");}
async function setLiveRevealAnimationsEnabled(enabled){const payload=await api("/api/creator/reveal-sequence",{method:"POST",body:JSON.stringify({animations_enabled:Boolean(enabled)})});renderRevealSequence(payload.state||{});renderLiveRevealAnimationTool(payload.state||{});notify(enabled?"Reveal Animations On":"Reveal Animations Off",enabled?"Verified hits will trigger configured effects.":"Recognition continues without reveal effects.","success");}
async function setLiveRevealEffect(key,enabled){const payload=await api("/api/creator/reveal-sequence",{method:"POST",body:JSON.stringify({[key]:Boolean(enabled)})});renderRevealSequence(payload.state||{});renderLiveRevealAnimationTool(payload.state||{});}

let soundboardState={pads:[],assets:[]};
const SOUNDBOARD_LAYOUT_KEY="rareiq.soundboard.layouts.v1";
let soundboardLayouts={active:0,locked:false,presets:[]};
function loadSoundboardLayouts(){try{const saved=JSON.parse(localStorage.getItem(SOUNDBOARD_LAYOUT_KEY)||"{}");soundboardLayouts={active:Math.max(0,Math.min(9,Number(saved.active)||0)),locked:Boolean(saved.locked),presets:Array.isArray(saved.presets)?saved.presets.slice(0,10):[]};}catch{soundboardLayouts={active:0,locked:false,presets:[]};}}
function saveSoundboardLayouts(){localStorage.setItem(SOUNDBOARD_LAYOUT_KEY,JSON.stringify(soundboardLayouts));}
function ensureSoundboardLayouts(){if(!soundboardLayouts.presets.length)soundboardLayouts.presets=[{name:"Default",order:soundboardState.pads.map(pad=>pad.id)}];while(soundboardLayouts.presets.length<10)soundboardLayouts.presets.push({name:`Preset ${soundboardLayouts.presets.length+1}`,order:[]});soundboardLayouts.active=Math.min(soundboardLayouts.active,9);}
function orderedSoundboardPads(){ensureSoundboardLayouts();const order=soundboardLayouts.presets[soundboardLayouts.active].order||[],rank=new Map(order.map((id,index)=>[id,index]));soundboardState.pads.sort((a,b)=>(rank.get(a.id)??999)-(rank.get(b.id)??999));return soundboardState.pads;}
function storeCurrentSoundboardOrder(){ensureSoundboardLayouts();soundboardLayouts.presets[soundboardLayouts.active].order=soundboardState.pads.map(pad=>pad.id);saveSoundboardLayouts();}
function syncSoundboardLayoutControls(){ensureSoundboardLayouts();["soundboardToolPreset","soundboardAppPreset"].forEach(id=>{const select=$(id);if(!select)return;select.replaceChildren(...soundboardLayouts.presets.map((preset,index)=>new Option(`${index+1}. ${preset.name}`,String(index))));select.value=String(soundboardLayouts.active);});["soundboardToolLock","soundboardAppLock"].forEach(id=>{const button=$(id);if(!button)return;button.setAttribute("aria-pressed",String(soundboardLayouts.locked));button.textContent=soundboardLayouts.locked?"Layout Locked":"Lock Layout";});}
function renameSoundboardPreset(){ensureSoundboardLayouts();const preset=soundboardLayouts.presets[soundboardLayouts.active],name=window.prompt("Name this Soundboard preset",preset.name);if(name===null)return;preset.name=String(name).trim().slice(0,30)||preset.name;saveSoundboardLayouts();syncSoundboardLayoutControls();}
function setSoundboardPreset(index){soundboardLayouts.active=Math.max(0,Math.min(9,Number(index)||0));ensureSoundboardLayouts();const order=soundboardLayouts.presets[soundboardLayouts.active].order||[];if(order.length){const rank=new Map(order.map((id,i)=>[id,i]));soundboardState.pads.sort((a,b)=>(rank.get(a.id)??999)-(rank.get(b.id)??999));}else storeCurrentSoundboardOrder();saveSoundboardLayouts();renderSoundboard(soundboardState);renderSoundboardApp();refreshSoundPadImages();}
function toggleSoundboardLayoutLock(){soundboardLayouts.locked=!soundboardLayouts.locked;saveSoundboardLayouts();syncSoundboardLayoutControls();renderSoundboard(soundboardState);renderSoundboardApp();refreshSoundPadImages();}
function enableSoundboardDrag(container,selector){if(!container||soundboardLayouts.locked)return;container.querySelectorAll(selector).forEach(button=>{button.draggable=true;button.addEventListener("dragstart",event=>{button.classList.add("is-dragging");event.dataTransfer.setData("text/plain",button.dataset.padId||"");event.dataTransfer.effectAllowed="move"});button.addEventListener("dragend",()=>button.classList.remove("is-dragging"));button.addEventListener("dragover",event=>{event.preventDefault();button.classList.add("is-drag-over")});button.addEventListener("dragleave",()=>button.classList.remove("is-drag-over"));button.addEventListener("drop",event=>{event.preventDefault();button.classList.remove("is-drag-over");const sourceId=event.dataTransfer.getData("text/plain"),targetId=button.dataset.padId;if(!sourceId||!targetId||sourceId===targetId)return;const from=soundboardState.pads.findIndex(pad=>pad.id===sourceId),to=soundboardState.pads.findIndex(pad=>pad.id===targetId);if(from<0||to<0)return;const [moved]=soundboardState.pads.splice(from,1);soundboardState.pads.splice(to,0,moved);storeCurrentSoundboardOrder();renderSoundboard(soundboardState);renderSoundboardApp();refreshSoundPadImages();});});}
const activeSoundboardPlayers=new Set();
let soundboardPlaybackFrame=0;
const soundboardQueue=[];
function soundboardPlaybackMode(){return localStorage.getItem("rareiq.soundboard.playbackMode")==="layer"?"layer":"queue";}
function setSoundboardPlaybackMode(mode){const value=mode==="layer"?"layer":"queue";localStorage.setItem("rareiq.soundboard.playbackMode",value);["soundboardToolPlaybackMode","soundboardAppPlaybackMode"].forEach(id=>{if($(id))$(id).value=value;});syncSoundboardQueueCount();}
function moveSoundboardQueueItem(index,direction){const target=index+direction;if(index<0||target<0||index>=soundboardQueue.length||target>=soundboardQueue.length)return;[soundboardQueue[index],soundboardQueue[target]]=[soundboardQueue[target],soundboardQueue[index]];syncSoundboardQueueCount();}
function removeSoundboardQueueItem(index){if(index<0||index>=soundboardQueue.length)return;soundboardQueue.splice(index,1);syncSoundboardQueueCount();}
function clearSoundboardQueue(){soundboardQueue.splice(0);syncSoundboardQueueCount();}
function renderSoundboardQueueList(containerId,compact=false){const list=$(containerId);if(!list)return;if(!soundboardQueue.length){const empty=document.createElement("li");empty.className="is-empty";empty.textContent=compact?"Queue is empty":"Queue is empty — trigger pads to build a sequence.";list.replaceChildren(empty);return;}list.replaceChildren(...soundboardQueue.map((pad,index)=>{const item=document.createElement("li");item.dataset.queueIndex=String(index);const position=document.createElement("b");position.textContent=String(index+1).padStart(2,"0");const copy=document.createElement("div");const name=document.createElement("strong");name.textContent=pad.label||"Sound";const asset=document.createElement("small");asset.textContent=pad.asset?.name||"Audio";copy.append(name,asset);const actions=document.createElement("span");[["↑",-1,"Move earlier"],["↓",1,"Move later"]].forEach(([text,direction,title])=>{const button=document.createElement("button");button.type="button";button.textContent=text;button.title=title;button.disabled=direction<0?index===0:index===soundboardQueue.length-1;button.addEventListener("click",()=>moveSoundboardQueueItem(index,direction));actions.append(button);});const remove=document.createElement("button");remove.type="button";remove.textContent="×";remove.title=`Remove ${pad.label||"sound"} from queue`;remove.addEventListener("click",()=>removeSoundboardQueueItem(index));actions.append(remove);item.append(position,copy,actions);return item;}));}
function syncSoundboardQueueCount(){const label=`${soundboardQueue.length} queued`;if($("soundboardToolQueueCount"))$("soundboardToolQueueCount").textContent=label;if($("soundboardAppQueueCount"))$("soundboardAppQueueCount").textContent=label;renderSoundboardQueueList("soundboardToolQueue",true);renderSoundboardQueueList("soundboardAppQueue");}
function soundboardVolume(){const value=Number(localStorage.getItem("rareiq.soundboard.volume")??100);return Math.max(0,Math.min(100,Number.isFinite(value)?value:100));}
function formatSoundboardTime(seconds){const safe=Math.max(0,Number.isFinite(seconds)?seconds:0),minutes=Math.floor(safe/60);return `${minutes}:${String(Math.floor(safe%60)).padStart(2,"0")}`;}
function syncSoundboardPlayback(){const players=[...activeSoundboardPlayers],activeIds=new Set(players.map(player=>player.dataset.padId));document.querySelectorAll("[data-pad-id]").forEach(button=>button.classList.toggle("is-playing",activeIds.has(button.dataset.padId)));const current=players.at(-1),duration=Number(current?.duration),elapsed=Number(current?.currentTime)||0,remaining=Number.isFinite(duration)?Math.max(0,duration-elapsed):0,progress=Number.isFinite(duration)&&duration>0?Math.min(100,elapsed/duration*100):0;[["soundboardToolNowPlaying","soundboardToolNowPlayingName","soundboardToolNowPlayingTime","soundboardToolNowPlayingProgress"],["soundboardAppNowPlaying","soundboardAppNowPlayingName","soundboardAppNowPlayingTime","soundboardAppNowPlayingProgress"]].forEach(([wrapId,nameId,timeId,progressId])=>{const wrap=$(wrapId),name=$(nameId),time=$(timeId),bar=$(progressId);if(wrap)wrap.dataset.state=current?"playing":"idle";if(name)name.textContent=current?.dataset.padLabel||"Nothing playing";if(time)time.textContent=current?(Number.isFinite(duration)?`${formatSoundboardTime(remaining)} left · ${formatSoundboardTime(elapsed)} / ${formatSoundboardTime(duration)}`:"Loading…"):"0:00 left";if(bar)bar.style.width=`${progress}%`;});if(players.length)soundboardPlaybackFrame=requestAnimationFrame(syncSoundboardPlayback);else soundboardPlaybackFrame=0;}
function startSoundboardPlaybackSync(){if(!soundboardPlaybackFrame)soundboardPlaybackFrame=requestAnimationFrame(syncSoundboardPlayback);}
function stopAllSoundboardAudio(){soundboardQueue.splice(0);activeSoundboardPlayers.forEach(player=>{player.pause();player.currentTime=0;player.remove()});activeSoundboardPlayers.clear();if(spotifyDuckedVolume!==null){const restore=spotifyDuckedVolume;spotifyDuckedVolume=null;spotifyCommand("volume",{volume_percent:restore}).catch(()=>{});}if(soundboardPlaybackFrame)cancelAnimationFrame(soundboardPlaybackFrame);soundboardPlaybackFrame=0;syncSoundboardQueueCount();syncSoundboardPlayback();}
function startSoundboardPad(pad,queued=false){if(localStorage.getItem("rareiq.spotify.duckSoundboard")==="true"&&spotifyState.connected&&spotifyDuckedVolume===null){spotifyDuckedVolume=Number(spotifyState.playback?.device?.volume_percent??50);spotifyCommand("volume",{volume_percent:Math.max(5,Math.round(spotifyDuckedVolume*.3))}).catch(()=>{});}const player=new Audio(pad.asset.url);player.volume=soundboardVolume()/100;player.dataset.padId=pad.id;player.dataset.padLabel=pad.label||pad.asset.name||"Sound";activeSoundboardPlayers.add(player);const dispose=()=>{activeSoundboardPlayers.delete(player);player.remove();if(queued&&soundboardQueue.length)startSoundboardPad(soundboardQueue.shift(),true);syncSoundboardQueueCount();if(!activeSoundboardPlayers.size){if(spotifyDuckedVolume!==null){const restore=spotifyDuckedVolume;spotifyDuckedVolume=null;spotifyCommand("volume",{volume_percent:restore}).catch(()=>{});}if(soundboardPlaybackFrame)cancelAnimationFrame(soundboardPlaybackFrame);soundboardPlaybackFrame=0;syncSoundboardPlayback();}};player.addEventListener("ended",dispose,{once:true});player.addEventListener("error",dispose,{once:true});player.play().then(startSoundboardPlaybackSync).catch(error=>{dispose();notify("Sound Blocked",error.message||"Browser prevented playback.","error")});syncSoundboardPlayback();}
function playSoundboardPad(pad){if(!pad?.asset?.url)return;if(soundboardPlaybackMode()==="queue"&&activeSoundboardPlayers.size){soundboardQueue.push(pad);syncSoundboardQueueCount();return;}startSoundboardPad(pad,soundboardPlaybackMode()==="queue");}
function setSoundboardVolume(value){const volume=Math.max(0,Math.min(100,Number(value)||0));localStorage.setItem("rareiq.soundboard.volume",String(volume));activeSoundboardPlayers.forEach(player=>{player.volume=volume/100});if($("soundboardVolume"))$("soundboardVolume").value=String(volume);if($("soundboardVolumeValue"))$("soundboardVolumeValue").textContent=`${volume}%`;}
function refreshSoundPadImages(){const playable=soundboardState.pads.filter(pad=>pad.asset);[["#soundboardPads .studiox-sound-pad",playable],["#cameraSoundboardPads .camera-sound-pad",playable.slice(0,6)],["#soundboardAppGrid .soundboard-app-pad",playable]].forEach(([selector,pads])=>document.querySelectorAll(selector).forEach((button,index)=>{const image=pads[index]?.image_asset?.url;if(image){button.classList.add("has-pad-image");button.style.setProperty("--pad-image",`url("${image}")`)}else{button.classList.remove("has-pad-image");button.style.removeProperty("--pad-image")}}));}
function addSoundboardImageControls(){const visuals=soundboardState.assets.filter(asset=>asset.kind==="visual");document.querySelectorAll("#soundboardPadConfig .studiox-soundboard-config-row").forEach((row,index)=>{const select=document.createElement("select");select.dataset.soundboardImage=String(index);select.append(new Option("No button image",""),...visuals.map(asset=>new Option(asset.name,asset.id)));select.value=soundboardState.pads[index]?.image_asset_id||"";const upload=document.createElement("label");upload.className="riq-button soundboard-image-upload";upload.textContent="Image";const input=document.createElement("input");input.type="file";input.accept="image/png,image/jpeg,image/webp,image/gif";input.addEventListener("change",()=>uploadSoundboardPadImage(index,input.files?.[0]).catch(error=>notify("Image Not Added",error.message||String(error),"error")));upload.append(input);row.insertBefore(select,row.lastElementChild);row.insertBefore(upload,row.lastElementChild)});}
async function uploadSoundboardPadImage(index,file){if(!file)return;const result=await uploadCreatorAsset(file),asset=result?.asset;if(!asset?.id||asset.kind!=="visual")throw new Error("A valid image was not returned");soundboardState.assets=[...soundboardState.assets.filter(item=>item.id!==asset.id),asset];soundboardState.pads[index]={...soundboardState.pads[index],image_asset_id:asset.id,image_asset:asset};await saveSoundboard();await loadSoundboard();}
function renderSoundboard(payload={}){soundboardState={pads:Array.isArray(payload.pads)?payload.pads:[],assets:Array.isArray(payload.assets)?payload.assets:[]};const audioAssets=soundboardState.assets.filter(asset=>asset.kind==="audio"),playable=orderedSoundboardPads().filter(p=>p.asset),makePad=(pad,quick=false)=>{const button=document.createElement("button");button.type="button";button.className=quick?"camera-sound-pad":"studiox-sound-pad";button.dataset.padId=pad.id;button.textContent=pad.label;button.title=soundboardLayouts.locked?`Play ${pad.label}`:`Play or drag ${pad.label}`;button.addEventListener("click",()=>playSoundboardPad(pad));return button;};const pads=$("soundboardPads");if(pads){pads.replaceChildren(...(playable.length?playable.map(pad=>makePad(pad)):[Object.assign(document.createElement("p"),{textContent:"Add audio to create your first sound pad."})]));enableSoundboardDrag(pads,".studiox-sound-pad");}const quickPads=$("cameraSoundboardPads");if(quickPads){quickPads.replaceChildren(...playable.slice(0,6).map(pad=>makePad(pad,true)));quickPads.hidden=playable.length===0;}const config=$("soundboardPadConfig");if(config)config.replaceChildren(...soundboardState.pads.map((pad,index)=>{const row=document.createElement("div");row.className="studiox-soundboard-config-row";const label=document.createElement("input");label.value=pad.label||`Sound ${index+1}`;label.maxLength=40;label.dataset.soundboardLabel=String(index);const select=document.createElement("select");select.dataset.soundboardAsset=String(index);select.append(new Option("Choose audio",""),...audioAssets.map(asset=>new Option(asset.name,asset.id)));select.value=pad.asset_id||"";const remove=document.createElement("button");remove.type="button";remove.className="riq-button";remove.textContent="Remove";remove.addEventListener("click",()=>{soundboardState.pads.splice(index,1);storeCurrentSoundboardOrder();renderSoundboard(soundboardState);renderSoundboardApp();addSoundboardImageControls();refreshSoundPadImages();});row.append(label,select,remove);return row;}));if($("soundboardToolPadCount"))$("soundboardToolPadCount").textContent=`${soundboardState.pads.length} / 50`;syncSoundboardLayoutControls();setStudioXWidgetState("soundboard","available");}
function renderSoundboardApp(){const search=String($("soundboardSearch")?.value||"").toLowerCase(),playable=orderedSoundboardPads().filter(p=>p.asset&&p.label.toLowerCase().includes(search)),grid=$("soundboardAppGrid");if(grid){grid.replaceChildren(...(playable.length?playable.map(pad=>{const button=document.createElement("button");button.type="button";button.className="soundboard-app-pad";button.dataset.padId=pad.id;button.innerHTML=`<i aria-hidden="true">▶</i><strong></strong><small>${pad.asset?.name||"Audio"}</small>`;button.querySelector("strong").textContent=pad.label;button.addEventListener("click",()=>playSoundboardPad(pad));return button;}):[Object.assign(document.createElement("p"),{textContent:soundboardState.pads.length?"No pads match your search.":"Upload audio to create your first sound pad."})]));enableSoundboardDrag(grid,".soundboard-app-pad");}if($("soundboardPadCount"))$("soundboardPadCount").textContent=`${soundboardState.pads.length} / 50 pads`;const config=$("soundboardAppConfig");if(config)config.replaceChildren(...soundboardState.pads.map((pad,index)=>{const row=document.createElement("div");row.className="studiox-soundboard-config-row";const label=document.createElement("input");label.value=pad.label;label.dataset.soundboardAppLabel=String(index);const select=document.createElement("select");select.dataset.soundboardAppAsset=String(index);select.append(new Option("Choose audio",""),...soundboardState.assets.map(asset=>new Option(asset.name,asset.id)));select.value=pad.asset_id||"";row.append(label,select);return row;}));syncSoundboardLayoutControls();}
async function loadSoundboard(){loadSoundboardLayouts();const payload=await api("/api/soundboard");renderSoundboard(payload);renderSoundboardApp();addSoundboardImageControls();refreshSoundPadImages();syncPriceAlertNotificationControls();return payload;}
async function saveSoundboardApp(){soundboardState.pads=soundboardState.pads.map((pad,index)=>({...pad,label:document.querySelector(`[data-soundboard-app-label='${index}']`)?.value||pad.label,asset_id:document.querySelector(`[data-soundboard-app-asset='${index}']`)?.value||pad.asset_id}));const payload=await api("/api/soundboard",{method:"POST",body:JSON.stringify({pads:soundboardState.pads})});renderSoundboard({pads:payload.soundboard||[],assets:soundboardState.assets});renderSoundboardApp();notify("Soundboard Saved","Your 50-pad layout is ready.","success");}
async function uploadSoundboardFiles(files){for(const file of Array.from(files||[]))await uploadSoundboardAudio(file);await loadSoundboard();}
async function saveSoundboard(){const pads=soundboardState.pads.map((pad,index)=>({...pad,label:document.querySelector(`[data-soundboard-label='${index}']`)?.value||pad.label,asset_id:document.querySelector(`[data-soundboard-asset='${index}']`)?.value||null,image_asset_id:document.querySelector(`[data-soundboard-image='${index}']`)?.value||pad.image_asset_id||null}));const payload=await api("/api/soundboard",{method:"POST",body:JSON.stringify({pads})});renderSoundboard({pads:payload.soundboard||[],assets:soundboardState.assets});refreshSoundPadImages();notify("Soundboard Saved","Your streamer pads are ready.","success");}
async function uploadSoundboardAudio(file){if(!file)return;const result=await uploadCreatorAsset(file);const asset=result?.asset;if(!asset?.id)throw new Error("Uploaded audio was not returned by the server");const current=await api("/api/soundboard"),pads=(current.pads||[]).map(pad=>({id:pad.id,label:pad.label,asset_id:pad.asset_id}));if(pads.length>=50)throw new Error("Soundboard supports up to 50 pads");pads.push({id:`pad-${Date.now()}`,label:asset.name||file.name.replace(/\.[^.]+$/,"")||`Sound ${pads.length+1}`,asset_id:asset.id});const saved=await api("/api/soundboard",{method:"POST",body:JSON.stringify({pads})});renderSoundboard({pads:saved.soundboard||[],assets:[...(current.assets||[]).filter(item=>item.id!==asset.id),asset]});notify("Sound Pad Added",`${asset.name} is ready in the camera toolbar.`,"success");}

async function replayCreatorReveal(revealId){
  const payload=await api("/api/creator/reveal-sequence/replay",{method:"POST",body:JSON.stringify({reveal_id:revealId})});
  renderRevealSequence(payload.state||{});
  notify("Reveal Replaying","Pack position and recognition history were not changed.","success");
}

function renderCreatorAssets(payload={}){
  const assets=Array.isArray(payload.assets)?payload.assets:[];
  const mapping=payload.mapping||{};
  const library=$("creatorAssetLibrary");
  if(library){
    library.replaceChildren(...(assets.length?assets.map(asset=>{const row=document.createElement("div");row.className="creator-asset-row";const name=document.createElement("strong");name.textContent=asset.name;const kind=document.createElement("span");kind.textContent=`${asset.kind} · ${asset.mime}`;row.append(name,kind);return row;}):[Object.assign(document.createElement("p"),{textContent:"No custom assets loaded."})]));
  }
  const matrix=$("creatorTierMapping");
  if(!matrix) return;
  const tiers=["standard","low","medium","grail"];
  matrix.replaceChildren(...tiers.map(tier=>{const card=document.createElement("div");card.className="creator-tier-card";const title=document.createElement("strong");title.textContent=tier==="standard"?"Standard / miss":`${tier[0].toUpperCase()}${tier.slice(1)} hit`;card.append(title);["audio","visual"].forEach(kind=>{const label=document.createElement("label");label.append(Object.assign(document.createElement("span"),{textContent:kind}));const select=document.createElement("select");select.dataset.tier=tier;select.dataset.kind=kind;select.append(new Option("None",""),...assets.filter(a=>a.kind===kind).map(a=>new Option(a.name,a.id)));select.value=mapping[tier]?.[kind]?.id||"";select.addEventListener("change",()=>mapCreatorAsset(tier,kind,select.value));label.append(select);card.append(label)});return card;}));
}

async function loadCreatorAssets(){const payload=await api("/api/creator/assets");renderCreatorAssets(payload);return payload;}
async function uploadCreatorAsset(file){
  if(!file)return;
  const response=await fetch("/api/creator/assets",{method:"POST",headers:{"Content-Type":file.type,"X-RareIQ-Filename":file.name},body:file});
  const payload=await response.json().catch(()=>({}));if(!response.ok||payload.ok===false)throw new Error(payload.error||"Asset upload failed");
  await loadCreatorAssets();notify("Reaction Asset Added",`${file.name} is ready to map.`,"success");return payload;
}
async function mapCreatorAsset(tier,kind,assetId){const payload=await api("/api/creator/assets/map",{method:"POST",body:JSON.stringify({tier,kind,asset_id:assetId||null})});renderCreatorAssets(payload);notify("Reaction Mapping Saved",`${tier} ${kind} updated.`,"success");}

function previewCreatorAnimation(tier){
  const url=new URL("/overlay/reveal-sequence",window.location.origin);
  url.searchParams.set("preview",tier);
  url.searchParams.set("intensity",String(Number($("creatorAnimationIntensity")?.value||75)));
  url.searchParams.set("duration",String(Number($("creatorAnimationDuration")?.value||3200)));
  url.searchParams.set("particles",String($("creatorParticlesEnabled")?.checked!==false));
  url.searchParams.set("flash",String($("creatorFlashEnabled")?.checked!==false));
  window.open(url.toString(),`rareiq-${tier}-preview`,`noopener`);
}

function creatorShortcutTargetIsEditable(target){return Boolean(target?.closest?.("input,select,textarea,[contenteditable='true']"));}
function handleCreatorRevealShortcut(event){
  if(document.body.dataset.ui4Workspace!=="creator"||creatorShortcutTargetIsEditable(event.target))return;
  const armed=$("creatorRevealArming")?.hidden===false;let action=null;
  if(event.code==="Space"&&armed)action=()=>$("creatorRevealNow")?.click();
  else if(event.key==="Escape"&&armed)action=()=>$("creatorCancelReveal")?.click();
  else if(event.altKey&&event.key==="1")action=()=>previewCreatorAnimation("low");
  else if(event.altKey&&event.key==="2")action=()=>previewCreatorAnimation("medium");
  else if(event.altKey&&event.key==="3")action=()=>previewCreatorAnimation("grail");
  else if(event.altKey&&event.key.toLowerCase()==="n")action=()=>$("creatorNextPack")?.click();
  if(action){event.preventDefault();action();}
}

async function saveRevealSequence(){
  const expected=Number($("creatorExpectedCards")?.value||6);
  const rare=Math.min(expected,Number($("creatorRareSlot")?.value||expected));
  const mediumThreshold=Math.max(0,Number($("creatorMediumValueThreshold")?.value||25));
  const grailThreshold=Math.max(mediumThreshold,Number($("creatorGrailValueThreshold")?.value||150));
  if($("creatorGrailValueThreshold")) $("creatorGrailValueThreshold").value=String(grailThreshold);
  const state=await api("/api/creator/reveal-sequence",{method:"POST",body:JSON.stringify({enabled:$("creatorRevealEnabled")?.checked!==false,build_suspense:$("creatorBuildSuspense")?.checked!==false,expected_cards:expected,rare_slot:rare,medium_value_threshold:mediumThreshold,grail_value_threshold:grailThreshold,arming_delay_ms:Number($("creatorArmingDelay")?.value||0),reaction_copy:{standard:$("creatorStandardCopy")?.value,low:$("creatorLowCopy")?.value,medium:$("creatorMediumCopy")?.value,grail:$("creatorGrailCopy")?.value},custom_grail_preset:$("creatorGrailPreset")?.value||"none",audio_enabled:$("creatorAudioEnabled")?.checked===true,animations_enabled:$("creatorAnimationsEnabled")?.checked!==false,animation_intensity:Number($("creatorAnimationIntensity")?.value||75),animation_duration_ms:Number($("creatorAnimationDuration")?.value||3200),particles_enabled:$("creatorParticlesEnabled")?.checked!==false,flash_enabled:$("creatorFlashEnabled")?.checked!==false,minimum_animation_tier:$("creatorMinimumAnimationTier")?.value||"low"})});
  renderRevealSequence(state.state||{});notify("Reveal Rules Saved","The browser source will use the new sequence.","success");
}

let librarySyncTimer=0;
function libraryPercent(value,total){
  return total?Math.max(0,Math.min(100,Math.round(Number(value||0)/Number(total)*100))):0;
}
async function loadLibrarySyncStatus(){
  const payload=await api("/api/master-builder/status");
  const state=payload.builder||{},catalog=state.catalog||{};
  const completed=Number(state.sets_completed||0),failed=Number(state.sets_failed||0);
  const processed=completed+failed,discovered=Number(state.sets_discovered||0);
  const currentDone=Number(state.current_set_processed||0),currentTotal=Number(state.current_set_total||0);
  const currentPercent=libraryPercent(currentDone,currentTotal),overallPercent=libraryPercent(processed,discovered);
  const panel=$("librarySyncPanel");
  if(panel)panel.dataset.state=state.busy?"running":String(state.phase||"idle").toLowerCase();
  if($("librarySyncPhase"))$("librarySyncPhase").textContent=state.phase||"IDLE";
  if($("librarySyncSets"))$("librarySyncSets").textContent=`${processed.toLocaleString()} / ${discovered.toLocaleString()}`;
  if($("librarySyncImages"))$("librarySyncImages").textContent=Number(catalog.images||state.images||0).toLocaleString();
  if($("librarySyncCoverage"))$("librarySyncCoverage").textContent=`${Number(catalog.coverage_percent||0).toFixed(1)}%`;
  if($("librarySyncFailures"))$("librarySyncFailures").textContent=String(failed);
  if($("librarySyncProvider"))$("librarySyncProvider").textContent=state.busy?[state.current_provider,state.current_language].filter(Boolean).join(" · ")||"Preparing provider":"TCGdex + Pokémon TCG API";
  if($("librarySyncCurrent"))$("librarySyncCurrent").textContent=state.current_set_name||state.last_completed||"No active download";
  if($("librarySyncCurrentDetail"))$("librarySyncCurrentDetail").textContent=state.busy?`${currentDone.toLocaleString()} of ${currentTotal.toLocaleString()} cards · ${Number(state.queue_remaining||0).toLocaleString()} sets queued`:state.last_error||"Progress is saved between sessions.";
  if($("librarySyncCurrentPercent"))$("librarySyncCurrentPercent").textContent=`${currentPercent}%`;
  if($("librarySyncCurrentBar"))$("librarySyncCurrentBar").style.width=`${currentPercent}%`;
  if($("librarySyncOverallText"))$("librarySyncOverallText").textContent=`${processed.toLocaleString()} of ${discovered.toLocaleString()} sets processed`;
  if($("librarySyncOverallBar"))$("librarySyncOverallBar").style.width=`${overallPercent}%`;
  if($("librarySyncNote"))$("librarySyncNote").textContent=state.last_error?`Last error: ${state.last_error}`:state.busy?"Downloading reference artwork in the background. Recognition and collection tools remain available.":state.phase==="COMPLETE"?"Worldwide reference library and visual index are ready.":"Reference images improve exact-version recognition. Resume whenever the app is online.";
  if($("librarySyncStart"))$("librarySyncStart").disabled=Boolean(state.busy);
  if($("librarySyncPause"))$("librarySyncPause").disabled=!state.busy;
  clearTimeout(librarySyncTimer);
  if(document.body.dataset.ui4Workspace==="collection")librarySyncTimer=setTimeout(()=>loadLibrarySyncStatus().catch(()=>{}),2000);
  return state;
}
async function startLibrarySync(){
  const result=await api("/api/master-builder/start",{method:"POST",body:"{}"});
  notify(result.ok?"Library Sync Started":"Library Sync Unavailable",result.ok?"Worldwide card artwork will download in the background.":result.error||"Unable to start sync.",result.ok?"success":"error");
  return loadLibrarySyncStatus();
}
async function pauseLibrarySync(){
  await api("/api/master-builder/stop",{method:"POST",body:"{}"});
  notify("Library Sync Pausing","The active provider request will finish and progress will be preserved.","success");
  return loadLibrarySyncStatus();
}

function collectionDate(value){
  const date=new Date(Number(value||0)*1000);
  return Number.isNaN(date.getTime())?"--":date.toLocaleString([],{
    month:"short",day:"numeric",hour:"numeric",minute:"2-digit"
  });
}

async function loadCollection(){
  const payload=await api("/api/collection");
  if($("collectionTotal")) $("collectionTotal").textContent=String(payload.total_cards||0);
  if($("collectionUnique")) $("collectionUnique").textContent=String(payload.unique_cards||0);
  if($("collectionDuplicates")) $("collectionDuplicates").textContent=String(payload.duplicate_copies||0);
  const cards=Array.isArray(payload.cards)?payload.cards:[];
  collectionInventory=cards;
  populateInventoryCards(cards);
  loadInventory().catch(()=>{});
  populateCollectionFilters(cards);
  renderCollectionRows();
  renderCollectionSets(Array.isArray(payload.sets)?payload.sets:[]);
  renderCollectionValuation(payload.valuation||{});
  renderCollectionTrends(payload.trends||{});
  renderCollectionGoals(Array.isArray(payload.goals)?payload.goals:[],payload);
  renderDuplicateQueue(cards,payload);
  if($("collectionUpdated")) $("collectionUpdated").textContent=cards.length?`${cards.length} exact versions`:"Waiting for verified scans";
  const corrections=Array.isArray(payload.corrections)?payload.corrections:[];
  const correctionList=$("collectionCorrections");
  if(correctionList){
    correctionList.replaceChildren(...corrections.map(correction=>{
      const row=document.createElement("div");
      row.className="collection-correction";
      const status=correction.undone_at?"Undone":`${Number(correction.delta)>0?"+":""}${correction.delta}`;
      row.innerHTML=`<div><strong>${status}</strong><span>${correction.reason||"Operator correction"} · ${collectionDate(correction.created_at)}</span></div>`;
      if(!correction.undone_at){
        const undo=document.createElement("button");
        undo.type="button";
        undo.className="riq-button collection-undo";
        undo.textContent="Undo";
        undo.addEventListener("click",()=>undoCollectionCorrection(correction.id));
        row.appendChild(undo);
      }
      return row;
    }));
  }
  if($("collectionCorrectionsEmpty")) $("collectionCorrectionsEmpty").hidden=corrections.length>0;
  return payload;
}

function populateInventoryCards(cards){const select=$("inventoryCard");if(!select)return;const value=select.value;select.replaceChildren(new Option("Choose an owned card",""),...cards.map(card=>new Option(`${card.english_name||card.card_name} · ${card.set_name||card.set_code||"--"} #${card.collector_number||"--"}`,card.version_key)));select.value=value;}
function renderPriceWatchlist(payload={}){
  const host=$("priceWatchlist"),rows=Array.isArray(payload.alerts)?payload.alerts:[];
  if($("priceWatchlistSummary"))$("priceWatchlistSummary").textContent=`${payload.triggered||0} triggered · ${payload.total||0} watched`;
  const scheduler=payload.scheduler||{};
  if($("priceWatchSchedule"))$("priceWatchSchedule").textContent=scheduler.busy?"Checking watched cards…":scheduler.last_run_at?`Last checked ${readablePriceTimestamp(scheduler.last_run_at)} · next ${readablePriceTimestamp(scheduler.next_run_at)}`:"Automatic checks every 6 hours";
  if(!host)return;
  if(!rows.length){host.replaceChildren(Object.assign(document.createElement("p"),{textContent:"No price targets configured."}));return}
  dispatchTriggeredPriceAlerts(rows);
  host.replaceChildren(...rows.map(alert=>{const row=document.createElement("article");row.dataset.triggered=String(Boolean(alert.triggered));const info=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("span"),status=document.createElement("b"),remove=document.createElement("button");name.textContent=alert.card_name||alert.identity;meta.textContent=[alert.inventory_item_id,alert.set_name,alert.collector_number].filter(Boolean).join(" · ")||alert.identity;info.append(name,meta);const target=cardMoney(alert.target,alert.currency),current=alert.current==null?"No verified price":cardMoney(alert.current,alert.current_currency||alert.currency);status.textContent=`${alert.triggered?"TRIGGERED":"WATCHING"} · ${current} · ${alert.direction==="below"?"≤":"≥"} ${target}`;remove.type="button";remove.className="riq-button";remove.textContent="Remove";remove.addEventListener("click",()=>alert.inventory_item_id?removeInventoryPriceAlert(alert):removePriceWatchAlert(alert.identity));row.append(info,status,remove);return row;}));
}
const PRICE_ALERT_PREFS_KEY="rareiq.priceAlerts.notifications.v1";
function priceAlertPrefs(){try{return {...{desktop:false,soundPadId:""},...JSON.parse(localStorage.getItem(PRICE_ALERT_PREFS_KEY)||"{}")}}catch{return {desktop:false,soundPadId:""}}}
function savePriceAlertPrefs(){const prefs={desktop:Boolean($("priceAlertDesktop")?.checked),soundPadId:$("priceAlertSound")?.value||""};localStorage.setItem(PRICE_ALERT_PREFS_KEY,JSON.stringify(prefs));return prefs}
function syncPriceAlertNotificationControls(){const prefs=priceAlertPrefs();if($("priceAlertDesktop"))$("priceAlertDesktop").checked=prefs.desktop;const select=$("priceAlertSound"),playable=soundboardState.pads.filter(pad=>pad.asset);if(select){select.replaceChildren(new Option("Off",""),...playable.map(pad=>new Option(pad.label||pad.asset.name,pad.id)));select.value=playable.some(pad=>pad.id===prefs.soundPadId)?prefs.soundPadId:""}}
async function requestPriceAlertNotifications(){if(!("Notification" in window))throw new Error("Desktop notifications are not supported in this browser.");const permission=await Notification.requestPermission();if(permission!=="granted")throw new Error("Notification permission was not granted.");if($("priceAlertDesktop"))$("priceAlertDesktop").checked=true;savePriceAlertPrefs();notify("Desktop Alerts Enabled","Triggered card prices can now notify you outside RareIQ.","success")}
function dispatchTriggeredPriceAlerts(rows=[]){const prefs=priceAlertPrefs();rows.filter(alert=>alert.triggered).forEach(alert=>{const eventKey=`${alert.identity}|${alert.inventory_item_id||"card"}|${alert.current}|${alert.target}|${alert.direction}`,storageKey=`rareiq.priceAlert.fired.${eventKey}`;if(sessionStorage.getItem(storageKey))return;sessionStorage.setItem(storageKey,"1");const name=alert.card_name||alert.identity,detail=`${cardMoney(alert.current,alert.current_currency||alert.currency)} reached your ${cardMoney(alert.target,alert.currency)} target.`;notify("Price Target Triggered",`${name}${alert.inventory_item_id?` · ${alert.inventory_item_id}`:""} · ${detail}`,"success");if(prefs.desktop&&window.Notification?.permission==="granted")new Notification(`RareIQ · ${name}`,{body:detail,tag:`rareiq-price-${alert.inventory_item_id||alert.identity}`});const pad=soundboardState.pads.find(item=>item.id===prefs.soundPadId&&item.asset);if(pad)playSoundboardPad(pad)})}
async function loadPriceWatchlist(){const payload=await api("/api/catalog/price-alerts");renderPriceWatchlist(payload);return payload}
async function refreshPriceWatchlist(){const button=$("priceWatchRefresh");if(button)button.disabled=true;try{await api("/api/catalog/price-alerts/refresh",{method:"POST"});notify("Watchlist Refresh Started","RareIQ is checking verified pricing for every watched card.","success");setTimeout(()=>loadPriceWatchlist().catch(()=>{}),1500)}finally{if(button)button.disabled=false}}
async function removePriceWatchAlert(identity){await api("/api/catalog/price-alerts/remove",{method:"POST",body:JSON.stringify({identity})});notify("Price Alert Removed","The card was removed from your watchlist.","success");return loadPriceWatchlist()}
async function setInventoryPriceAlert(item){const raw=window.prompt(`Target price for ${item.item_id}`,String(item.asking_price||item.acquisition_valuation?.market||""));if(raw===null)return;const target=Number(raw);if(!Number.isFinite(target)||target<0)throw new Error("Enter a valid target price.");const direction=window.confirm("Trigger when the price reaches or rises above this target?\nChoose Cancel for at or below.")?"above":"below";await api(`/api/inventory/items/${encodeURIComponent(item.item_id)}/price-alert`,{method:"POST",body:JSON.stringify({direction,target,currency:item.currency||"USD",enabled:true})});notify("Inventory Alert Saved",`${item.item_id} · ${direction==="above"?"at or above":"at or below"} ${cardMoney(target,item.currency||"USD")}`,"success");return loadPriceWatchlist()}
async function removeInventoryPriceAlert(alert){await api(`/api/inventory/items/${encodeURIComponent(alert.inventory_item_id)}/price-alert`,{method:"POST",body:JSON.stringify({direction:alert.direction||"above",target:Number(alert.target||0),currency:alert.currency||"USD",enabled:false})});notify("Inventory Alert Removed",`${alert.inventory_item_id} is no longer watched.`,"success");return loadPriceWatchlist()}
function renderInventory(payload={}){if($("inventoryStatus"))$("inventoryStatus").textContent=`${Number(payload.in_stock||0)} in stock · ${Number(payload.sold_count||0)} sold`;[["inventoryCost",payload.inventory_cost],["inventoryAsking",payload.asking_value],["inventorySales",payload.gross_sales],["inventoryProfit",payload.net_profit]].forEach(([id,value])=>{if($(id))$(id).textContent=money(value||0)});const host=$("inventoryItems");if(!host)return;const items=Array.isArray(payload.items)?payload.items:[];host.replaceChildren(...items.map(item=>{const row=document.createElement("article");row.className=`inventory-item ${item.status}`;const select=document.createElement("input");select.type="checkbox";select.className="inventory-label-select";select.value=item.item_id;select.setAttribute("aria-label",`Select ${item.item_id} for batch actions`);select.disabled=item.status!=="in_stock";select.addEventListener("change",updateInventoryBatchSelection);const valuation=item.acquisition_valuation||{},valuationLabel=item.pricing_resolution_id?` · acquired at ${portfolioMoney(valuation.market,valuation.currency)} via ${valuation.provider||"verified quote"}`:"",listing=item.active_listing,listingLabel=listing?` · LISTED ${String(listing.channel||"other").replaceAll("_"," ")} ${listing.listing_id||listing.listing_record_id}`:"";row.innerHTML=`<img src="${item.qr_url}" alt="QR ${item.item_id}"><div><strong>${item.english_name||item.card_name}</strong><span>${item.item_id} · ${item.set_name||item.set_code||"--"} #${item.collector_number||"--"}</span><small>${item.status==="sold"?`Sold ${money(item.sale?.gross||0)} · profit ${money(item.sale?.profit||0)} · ${item.sale?.channel||"sale"}`:`Cost ${money(item.cost_basis||0)} · ask ${item.asking_price==null?"--":money(item.asking_price)}`}${valuationLabel}${listingLabel}</small></div><a class="riq-button" href="${item.profile_url}" target="_blank">Profile</a><a class="riq-button" href="${item.label_url}" target="_blank">Print Label</a>`;row.prepend(select);const alertAction=document.createElement("button");alertAction.type="button";alertAction.className="riq-button";alertAction.textContent="Set Alert";alertAction.addEventListener("click",()=>setInventoryPriceAlert(item).catch(error=>notify("Alert Not Saved",error.message||String(error),"error")));row.append(alertAction);if(item.status==="in_stock"){const listingAction=document.createElement("button");listingAction.type="button";listingAction.className="riq-button";listingAction.textContent=listing?"End Listing":"Mark Listed";listingAction.addEventListener("click",()=>((listing?endInventoryListing(item):activateInventoryListing(item)).catch(error=>notify("Listing Not Updated",error.message||String(error),"error"))));row.append(listingAction)}const action=document.createElement("button");action.className="riq-button";if(item.status==="in_stock"){action.textContent="Sell";action.addEventListener("click",()=>checkoutInventoryItem(item))}else{action.textContent="Void / Return";action.addEventListener("click",()=>voidInventorySale(item))}row.append(action);return row;}));updateInventoryBatchSelection();}
function portfolioMoney(value,currency="USD"){const number=Number(value);return Number.isFinite(number)?new Intl.NumberFormat("en-US",{style:"currency",currency:String(currency||"USD").toUpperCase(),minimumFractionDigits:2,maximumFractionDigits:2}).format(number):"Unavailable"}
function renderInventoryValuation(data={}){const currency=data.currency||"USD",available=Number(data.priced||0)>0;if($("inventoryValuationCoverage"))$("inventoryValuationCoverage").textContent=`${Number(data.coverage_percent||0).toFixed(1)}% priced · ${data.priced||0}/${data.in_stock||0}`;setCardText("inventoryVerifiedValue",available?portfolioMoney(data.verified_value,currency):null,"Unavailable");setCardText("inventoryUnrealized",available?portfolioMoney(data.unrealized_profit,currency):null,"Unavailable");setCardText("inventoryMovement",available?portfolioMoney(data.movement,currency):null,"Unavailable");setCardText("inventoryTargetUpside",available?portfolioMoney(data.target_upside,currency):null,"Unavailable");setCardText("inventoryUnpriced",String(data.unpriced||0));const note=$("inventoryValuationNote");if(note)note.textContent=`${data.unpriced||0} unpriced · ${data.stale_excluded||0} stale · ${data.unverified_excluded||0} unverified · ${data.excluded_non_usd||0} non-USD excluded from verified totals.`;[["inventoryUnrealized",data.unrealized_profit],["inventoryMovement",data.movement]].forEach(([id,value])=>{const node=$(id);if(node)node.dataset.direction=Number(value||0)>=0?"positive":"negative"});renderInventoryPackLedgers(data.allocation_groups||[],currency)}
function updateInventoryListingSelection(){const count=selectedInventoryListingIds.size;setCardText("inventoryListingSelectedCount",`${count} selected`);if($("inventoryListingSmartReprice"))$("inventoryListingSmartReprice").disabled=!count;if($("inventoryListingReprice"))$("inventoryListingReprice").disabled=!count;if($("inventoryListingEnd"))$("inventoryListingEnd").disabled=!count}
function selectInventoryListings(mode="all"){document.querySelectorAll(".inventory-listing-select").forEach(input=>{const selected=mode==="all"||(mode==="stale"&&input.dataset.stale==="true");input.checked=selected;if(selected)selectedInventoryListingIds.add(input.value);else selectedInventoryListingIds.delete(input.value)});updateInventoryListingSelection()}
function renderInventoryListingDashboard(data={}){setCardText("inventoryListingsActive",String(data.active||0));setCardText("inventoryListingsStale",String(data.stale||0));setCardText("inventoryListingsUnlisted",String(data.unlisted||0));setCardText("inventoryListingsExposure",portfolioMoney(data.asking_exposure||0,data.currency||"USD"));const listings=data.listings||[],validIds=new Set(listings.map(listing=>listing.item_id));[...selectedInventoryListingIds].forEach(id=>{if(!validIds.has(id))selectedInventoryListingIds.delete(id)});const channels=$("inventoryListingChannels"),rows=$("inventoryListingRows");if(channels)channels.replaceChildren(...(data.channels||[]).map(channel=>{const card=document.createElement("article");const name=document.createElement("strong"),meta=document.createElement("span");name.textContent=String(channel.channel||"other").replaceAll("_"," ");meta.textContent=`${channel.active||0} active · ${portfolioMoney(channel.asking_value,data.currency||"USD")}`;card.append(name,meta);return card}));if(rows)rows.replaceChildren(...(listings.length?listings.map(listing=>{const row=document.createElement("article");row.dataset.stale=String(Boolean(listing.stale));const select=document.createElement("input"),info=document.createElement("div"),name=document.createElement("strong"),meta=document.createElement("span"),age=document.createElement("b"),profile=document.createElement("a");select.type="checkbox";select.className="inventory-listing-select";select.value=listing.item_id;select.dataset.stale=String(Boolean(listing.stale));select.checked=selectedInventoryListingIds.has(listing.item_id);select.setAttribute("aria-label",`Select listing for ${listing.card_name||listing.item_id}`);select.addEventListener("change",()=>{if(select.checked)selectedInventoryListingIds.add(select.value);else selectedInventoryListingIds.delete(select.value);updateInventoryListingSelection()});name.textContent=listing.card_name||listing.item_id;meta.textContent=`${listing.item_id} · ${String(listing.channel||"other").replaceAll("_"," ")} · ${listing.listing_id||"No marketplace ID"} · ${portfolioMoney(listing.asking_price,listing.currency)}`;info.append(name,meta);age.textContent=listing.stale?`STALE · ${listing.age_days} days`:`${listing.age_days} days`;profile.className="riq-button";profile.href=listing.listing_url||listing.profile_url;profile.target="_blank";profile.rel="noopener";profile.textContent=listing.listing_url?"Open Listing":"Open Profile";row.append(select,info,age,profile);return row}):[Object.assign(document.createElement("p"),{textContent:"No active marketplace listings."})]));updateInventoryListingSelection()}
function renderInventoryRepriceHistory(data={}){const host=$("inventoryRepriceHistory"),entries=data.entries||[];if(!host)return;host.replaceChildren(...(entries.length?entries.map(entry=>{const detail=entry.detail||{},row=document.createElement("article"),info=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("span"),impact=document.createElement("b"),sync=document.createElement("i"),rollback=document.createElement("button");title.textContent=entry.card_name||entry.entity_id;meta.textContent=`${portfolioMoney(detail.previous_price)} → ${portfolioMoney(detail.asking_price)} · ${new Date(Number(entry.timestamp||0)*1000).toLocaleString()}`;info.append(title,meta);impact.textContent=detail.profit_delta==null?"Profit impact unavailable":`${Number(detail.profit_delta)>=0?"+":""}${portfolioMoney(detail.profit_delta)} expected profit`;impact.dataset.direction=Number(detail.profit_delta||0)>=0?"positive":"negative";sync.textContent=entry.sync_status==="local_only"?"LOCAL ONLY":"SYNCED";rollback.type="button";rollback.className="riq-button";rollback.textContent=entry.rollback_available?"Rollback":"Protected";rollback.disabled=!entry.rollback_available;rollback.addEventListener("click",()=>rollbackInventoryReprice(entry).catch(error=>notify("Rollback Failed",error.message||String(error),"error")));row.append(info,impact,sync,rollback);return row}):[Object.assign(document.createElement("p"),{textContent:"No repricing changes recorded."})]))}
function renderInventoryMarketplaceSync(data={}){const counts=data.counts||{};setCardText("inventorySyncPending",String(counts.pending_approval||0));setCardText("inventorySyncReady",String(counts.ready||0));setCardText("inventorySyncSucceeded",String(counts.succeeded||0));setCardText("inventorySyncFailed",String(counts.failed||0));setCardText("inventorySyncSafety",data.external_writes_enabled?"External writes enabled":"Safe simulation · external writes off");const connectors=$("inventorySyncConnectors"),jobs=$("inventorySyncJobs");if(connectors)connectors.replaceChildren(...(data.connectors||[]).map(connector=>{const card=document.createElement("article"),name=document.createElement("strong"),meta=document.createElement("span");name.textContent=String(connector.channel||"other").replaceAll("_"," ");meta.textContent=connector.connected?"Connected":`${connector.mode||"simulation"} · no external writes`;card.append(name,meta);return card}));if(jobs)jobs.replaceChildren(...((data.jobs||[]).length?(data.jobs||[]).map(job=>{const row=document.createElement("article"),info=document.createElement("div"),title=document.createElement("strong"),meta=document.createElement("span"),status=document.createElement("b"),actions=document.createElement("nav");title.textContent=`${String(job.operation||"update").replaceAll("_"," ")} · ${job.item_id}`;meta.textContent=`${String(job.channel||"other").replaceAll("_"," ")} · ${new Date(Number(job.created_at||0)*1000).toLocaleString()} · ${job.attempts||0} attempts${job.last_error?` · ${job.last_error}`:""}`;info.append(title,meta);status.textContent=String(job.status||"pending").replaceAll("_"," ");status.dataset.status=job.status;if(job.status==="pending_approval")actions.append(syncJobButton("Approve",()=>updateInventoryMarketplaceSync(job,"approve")));if(job.status==="ready"){actions.append(syncJobButton("Test Success",()=>updateInventoryMarketplaceSync(job,"simulate","success")));actions.append(syncJobButton("Test Failure",()=>updateInventoryMarketplaceSync(job,"simulate","failure")))}if(job.status==="failed")actions.append(syncJobButton("Retry",()=>updateInventoryMarketplaceSync(job,"retry")));row.append(info,status,actions);return row}):[Object.assign(document.createElement("p"),{textContent:"No marketplace changes queued."})]))}
function syncJobButton(label,handler){const button=document.createElement("button");button.type="button";button.className="riq-button";button.textContent=label;button.addEventListener("click",()=>handler().catch(error=>notify("Sync Queue Not Updated",error.message||String(error),"error")));return button}
async function updateInventoryMarketplaceSync(job,action,simulatedOutcome="success"){if(action==="approve"&&!window.confirm(`Approve the local ${job.operation} job for ${job.channel}? External writes remain disabled.`))return;await api(`/api/inventory/marketplace-sync/${encodeURIComponent(job.job_id)}`,{method:"POST",body:JSON.stringify({action,simulated_outcome:simulatedOutcome})});notify("Sync Queue Updated",`${job.job_id} · ${action}${action==="simulate"?` ${simulatedOutcome}`:""}.`,simulatedOutcome==="failure"?"warning":"success");return loadInventory()}
function renderInventoryPackLedgers(groups=[],currency="USD"){
  const host=$("inventoryPackLedgers");
  if($("inventoryPackLedgerSummary"))$("inventoryPackLedgerSummary").textContent=`${groups.length} tracked ${groups.length===1?"pack":"packs"}`;
  if(!host)return;
  if(!groups.length){host.replaceChildren(Object.assign(document.createElement("p"),{textContent:"Rarity-weighted pack ledgers will appear here."}));return}
  host.replaceChildren(...groups.map(group=>{
    const details=document.createElement("details"),summary=document.createElement("summary"),profit=Number(group.unrealized_profit||0),roi=group.roi_percent==null?"--":`${Number(group.roi_percent).toFixed(1)}%`,strongest=group.strongest_pull;
    details.className="inventory-pack-ledger";details.dataset.direction=profit>=0?"positive":"negative";
    summary.innerHTML=`<div><strong>${String(group.group).split(":").pop().replace("pack-","Pack ")}</strong><span>${group.cards} cards · ${Number(group.coverage_percent||0).toFixed(0)}% priced${group.complete?"":" · provisional"}</span></div><div><span>Allocated Cost</span><strong>${portfolioMoney(group.cost_basis,currency)}</strong></div><div><span>Verified Value</span><strong>${portfolioMoney(group.verified_value,currency)}</strong></div><div><span>Unrealized P/L</span><strong>${portfolioMoney(profit,currency)} · ${roi} ROI</strong></div>`;
    const body=document.createElement("div");body.className="inventory-pack-detail";
    const pull=document.createElement("header");pull.innerHTML=strongest?`<span>Strongest pull</span><strong>${strongest.card_name} · ${portfolioMoney(strongest.market,currency)}</strong>`:`<span>Strongest pull</span><strong>Waiting for verified prices</strong>`;
    const cards=document.createElement("div");cards.replaceChildren(...(group.items||[]).map(item=>{const card=document.createElement("div"),itemProfit=item.unrealized_profit;card.innerHTML=`<span>${item.card_name} · #${item.collector_number||"--"}</span><b>${portfolioMoney(item.cost_basis,currency)} cost</b><b>${item.priced?portfolioMoney(item.market,currency):"Unpriced"}</b><strong>${itemProfit==null?"--":portfolioMoney(itemProfit,currency)}</strong>`;card.dataset.direction=Number(itemProfit||0)>=0?"positive":"negative";return card}));
    const actions=document.createElement("footer"),report=document.createElement("a"),csvLink=document.createElement("a"),encoded=encodeURIComponent(group.group);actions.className="inventory-pack-report-actions";report.className="riq-button primary";report.href=`/api/inventory/allocations/${encoded}/report`;report.target="_blank";report.textContent="Open Pack Report";csvLink.className="riq-button";csvLink.href=`/api/inventory/allocations/${encoded}/report.csv`;csvLink.textContent="Download CSV";actions.append(report,csvLink);
    body.append(pull,cards,actions);details.append(summary,body);return details;
  }));
}
function renderBreakPerformance(data={}){
  const currency=data.currency||"USD",packs=data.packs||[],best=data.best_pack,bestBox=data.best_box,host=$("breakPerformanceRows");
  if($("breakPerformanceSummary"))$("breakPerformanceSummary").textContent=`${data.pack_count||0} packs · ${data.box_count||0} boxes`;
  setCardText("breakBestPack",best?`Pack ${best.pack_number} · ${best.roi_percent==null?"--":`${best.roi_percent}% ROI`}`:null,"Unavailable");
  setCardText("breakBestPackDetail",best?`${portfolioMoney(best.total_return,currency)} return · ${best.hit_rate}% hit rate · ${best.strongest_pull?.card_name||"no priced pull"}`:null,"Waiting for completed packs");
  setCardText("breakBestBox",bestBox?`${bestBox.packs} packs · ${bestBox.roi_percent==null?"--":`${bestBox.roi_percent}% ROI`}`:null,"Unavailable");
  setCardText("breakBestBoxDetail",bestBox?`${portfolioMoney(bestBox.total_return,currency)} return · ${portfolioMoney(bestBox.realized_sales,currency)} realized`:null,"Waiting for completed boxes");
  if(!host)return;
  if(!packs.length){host.replaceChildren(Object.assign(document.createElement("p"),{textContent:"Performance rankings will appear as pack ledgers are created."}));return}
  host.replaceChildren(...packs.map((pack,index)=>{const row=document.createElement("article"),roi=pack.roi_percent==null?"--":`${pack.roi_percent}%`;row.dataset.direction=Number(pack.profit||0)>=0?"positive":"negative";row.innerHTML=`<b>#${index+1}</b><div><strong>Pack ${pack.pack_number}</strong><span>${pack.cards} cards · ${pack.coverage_percent}% covered</span></div><div><span>ROI</span><strong>${roi}</strong></div><div><span>Hit Rate</span><strong>${pack.hit_rate}%</strong></div><div><span>Total Return</span><strong>${portfolioMoney(pack.total_return,currency)}</strong></div><div><span>Realized</span><strong>${portfolioMoney(pack.realized_sales,currency)}</strong></div><div><span>Strongest Pull</span><strong>${pack.strongest_pull?.card_name||"Unpriced"}</strong></div>`;return row}));
}
function renderBusinessTrends(data={}){const currency=data.currency||"USD",totals=data.totals||{},rows=data.rows||[],expenses=data.expenses||[];[["businessTrendRevenue",totals.revenue],["businessTrendProfit",totals.card_profit],["businessTrendExpenses",totals.expenses],["businessTrendNet",totals.operating_net]].forEach(([id,value])=>setCardText(id,portfolioMoney(value||0,currency)));if($("businessTrendNet"))$("businessTrendNet").dataset.direction=Number(totals.operating_net||0)>=0?"positive":"negative";const chart=$("businessTrendChart"),max=Math.max(1,...rows.flatMap(row=>[Math.abs(Number(row.revenue||0)),Math.abs(Number(row.card_profit||0)),Math.abs(Number(row.expenses||0)),Math.abs(Number(row.operating_net||0))]));if(chart)chart.replaceChildren(...(rows.length?rows.map(row=>{const day=document.createElement("article");day.innerHTML=`<span>${new Date(`${row.date}T12:00:00`).toLocaleDateString([],{month:"short",day:"numeric"})}</span><div title="Revenue ${portfolioMoney(row.revenue,currency)}"><i data-kind="revenue" style="height:${Math.max(2,Math.abs(Number(row.revenue||0))/max*100)}%"></i></div><div title="Profit ${portfolioMoney(row.card_profit,currency)}"><i data-kind="profit" style="height:${Math.max(2,Math.abs(Number(row.card_profit||0))/max*100)}%"></i></div><div title="Expenses ${portfolioMoney(row.expenses,currency)}"><i data-kind="expense" style="height:${Math.max(2,Math.abs(Number(row.expenses||0))/max*100)}%"></i></div><div title="Net ${portfolioMoney(row.operating_net,currency)}"><i data-kind="net" style="height:${Math.max(2,Math.abs(Number(row.operating_net||0))/max*100)}%"></i></div>`;return day}):[Object.assign(document.createElement("p"),{textContent:"No business activity in this range."})]));const list=$("inventoryExpenses");if(list)list.replaceChildren(...(expenses.length?expenses.map(expense=>{const row=document.createElement("article"),remove=document.createElement("button"),recurrence=expense.recurrence&&expense.recurrence!=="none"?` · ${expense.recurrence}`:"";row.innerHTML=`<div><strong>${expense.category}${recurrence}</strong><span>${expense.note||"Operating expense"} · ${new Date(Number(expense.incurred_at)*1000).toLocaleDateString()}</span></div><b>${portfolioMoney(expense.amount,expense.currency)}</b>`;if(expense.receipt_url){const receipt=document.createElement("a");receipt.className="riq-button";receipt.href=expense.receipt_url;receipt.target="_blank";receipt.textContent="Receipt";row.append(receipt)}remove.type="button";remove.className="riq-button";remove.textContent="Remove";remove.addEventListener("click",()=>removeInventoryExpense(expense.expense_id));row.append(remove);return row}):[Object.assign(document.createElement("p"),{textContent:"No expenses recorded."})]))}
function expenseReceiptData(file){return new Promise((resolve,reject)=>{if(!file){resolve({receipt_name:"",receipt_data_url:""});return}if(file.size>5*1024*1024){reject(new Error("Receipt must be 5 MB or smaller."));return}const reader=new FileReader();reader.onload=()=>resolve({receipt_name:file.name,receipt_data_url:String(reader.result||"")});reader.onerror=()=>reject(new Error("Receipt could not be read."));reader.readAsDataURL(file)})}
async function addInventoryExpense(event){event.preventDefault();const receipt=await expenseReceiptData($("inventoryExpenseReceipt")?.files?.[0]),payload={category:$("inventoryExpenseCategory").value,amount:Number($("inventoryExpenseAmount").value),currency:"USD",note:$("inventoryExpenseNote").value,recurrence:$("inventoryExpenseRecurrence").value,...receipt};await api("/api/inventory/expenses",{method:"POST",body:JSON.stringify(payload)});$("inventoryExpenseAmount").value="";$("inventoryExpenseNote").value="";$("inventoryExpenseReceipt").value="";notify("Expense Recorded",`${payload.category} · ${portfolioMoney(payload.amount,"USD")}`,"success");return loadInventory()}
async function removeInventoryExpense(expenseId){await api(`/api/inventory/expenses/${encodeURIComponent(expenseId)}`,{method:"DELETE"});notify("Expense Removed","Business totals were recalculated.","success");return loadInventory()}
function decorateExpenseEditButtons(expenses=[]){document.querySelectorAll("#inventoryExpenses>article").forEach((row,index)=>{const expense=expenses[index];if(!expense||row.querySelector("[data-expense-edit]"))return;const edit=document.createElement("button");edit.type="button";edit.className="riq-button";edit.dataset.expenseEdit=expense.expense_id;edit.textContent="Edit";edit.addEventListener("click",()=>editInventoryExpense(expense));row.insertBefore(edit,row.lastElementChild)})}
async function editInventoryExpense(expense){const amount=window.prompt("Expense amount",String(expense.amount));if(amount===null)return;const note=window.prompt("Expense note",expense.note||"");if(note===null)return;const recurrence=window.prompt("Recurrence: none, weekly, monthly, or annual",expense.recurrence||"none");if(recurrence===null)return;await api(`/api/inventory/expenses/${encodeURIComponent(expense.expense_id)}`,{method:"PATCH",body:JSON.stringify({amount:Number(amount),note,recurrence})});notify("Expense Updated","Business and tax totals were recalculated.","success");return loadInventory()}
function renderTaxComparison(data={}){const currency=data.currency||"USD",year=data.year||new Date().getFullYear(),changes=data.changes||{},percent=data.change_percent||{},format=(key)=>`${portfolioMoney(changes[key]||0,currency)}${percent[key]==null?"":` · ${percent[key]}%`}`;if($("taxComparisonYears"))$("taxComparisonYears").textContent=`${year} vs ${year-1}`;setCardText("taxComparisonRevenue",format("revenue"));setCardText("taxComparisonDeductions",format("operating_expenses"));setCardText("taxComparisonNet",format("net_income"));[["taxComparisonRevenue",changes.revenue],["taxComparisonDeductions",changes.operating_expenses],["taxComparisonNet",changes.net_income]].forEach(([id,value])=>{if($(id))$(id).dataset.direction=Number(value||0)>=0?"positive":"negative"})}
function renderAccountingControls(profilePayload={},auditPayload={}){const profile=profilePayload.profile||{};if($("businessProfileName"))$("businessProfileName").value=profile.company_name||"";if($("businessProfileCurrency"))$("businessProfileCurrency").value=profile.currency||"USD";if($("businessProfileFiscalStart"))$("businessProfileFiscalStart").value=String(profile.fiscal_year_start||1);if($("businessProfileBasis"))$("businessProfileBasis").value=profile.reporting_basis||"cash";const backup=profilePayload.backup||{};if($("accountingBackupStatus"))$("accountingBackupStatus").textContent=backup.latest?`Protected · ${backup.count} daily ${backup.count===1?"backup":"backups"}`:"Daily backup arms on next change";const host=$("accountingAuditLog"),entries=auditPayload.entries||[];if(!host)return;host.replaceChildren(...(entries.length?entries.map(entry=>{const row=document.createElement("article"),detail=entry.detail||{},summary=entry.action==="expense.created"?`${detail.category||"Expense"} · ${portfolioMoney(detail.amount||0,profile.currency||"USD")}`:entry.action==="inventory.created"?`${detail.quantity||1} inventory ${Number(detail.quantity||1)===1?"item":"items"}`:entry.action.replaceAll("."," ");row.innerHTML=`<div><strong>${summary}</strong><span>${entry.entity_id||entry.entity_type||"Business record"}</span></div><time>${new Date(Number(entry.timestamp||0)*1000).toLocaleString()}</time>`;return row}):[Object.assign(document.createElement("p"),{textContent:"No accounting changes recorded."})]))}
async function saveBusinessProfile(event){event.preventDefault();const payload={company_name:$("businessProfileName").value.trim(),currency:$("businessProfileCurrency").value,fiscal_year_start:Number($("businessProfileFiscalStart").value),reporting_basis:$("businessProfileBasis").value};await api("/api/inventory/business-profile",{method:"PATCH",body:JSON.stringify(payload)});notify("Business Profile Saved",`${payload.company_name} · ${payload.currency} · ${payload.reporting_basis} basis`,"success");return loadInventory()}
function selectedAccountingPeriod(){const value=$("periodCloseMonth")?.value||"";const [year,month]=value.split("-").map(Number);return {year,month}}
function renderProfitAndLoss(data={}){const statement=data.statement||{},currency=data.currency||"USD";setCardText("periodRevenue",portfolioMoney(statement.revenue||0,currency));setCardText("periodGrossProfit",portfolioMoney(statement.gross_profit||0,currency));setCardText("periodOperatingCosts",portfolioMoney(Number(statement.selling_expenses||0)+Number(statement.operating_expenses||0),currency));setCardText("periodNetIncome",portfolioMoney(statement.net_income||0,currency));if($("periodNetIncome"))$("periodNetIncome").dataset.direction=Number(statement.net_income||0)>=0?"positive":"negative";if($("periodCloseState"))$("periodCloseState").textContent=data.closed?"Closed · locked":"Open period";if($("periodCloseNote"))$("periodCloseNote").textContent=data.closed?`Locked ${new Date(Number(data.close?.closed_at||0)*1000).toLocaleString()}. Historical totals are protected.`:"Review the statement, then close the finished month to protect its history.";if($("periodCloseButton"))$("periodCloseButton").disabled=Boolean(data.closed);if($("periodCloseExport"))$("periodCloseExport").href=`/api/inventory/profit-and-loss.csv?year=${data.period?.slice(0,4)}&month=${Number(data.period?.slice(5,7)||1)}`}
async function loadProfitAndLoss(){const {year,month}=selectedAccountingPeriod();if(!year||!month)return;renderProfitAndLoss(await api(`/api/inventory/profit-and-loss?year=${year}&month=${month}`))}
async function closeAccountingPeriod(event){event.preventDefault();const {year,month}=selectedAccountingPeriod();if(!year||!month)throw new Error("Choose a finished month.");if(!window.confirm(`Close ${year}-${String(month).padStart(2,"0")}? Expenses in this month can no longer be edited or deleted.`))return;await api("/api/inventory/accounting/close",{method:"POST",body:JSON.stringify({year,month})});notify("Accounting Period Closed",`${year}-${String(month).padStart(2,"0")} is now protected.`,"success");return loadInventory()}
function selectedInventoryLabelIds(){return [...document.querySelectorAll(".inventory-label-select:checked")].map(input=>input.value).slice(0,100)}
function updateInventoryBatchSelection(){const count=selectedInventoryLabelIds().length;if($("inventoryBatchCount"))$("inventoryBatchCount").textContent=`${count} selected`;if($("inventoryPrintSelected"))$("inventoryPrintSelected").disabled=!count;if($("inventoryPrepareListings"))$("inventoryPrepareListings").disabled=!count}
function selectAllInventoryLabels(selected=true){document.querySelectorAll(".inventory-label-select:not(:disabled)").forEach(input=>{input.checked=selected});updateInventoryBatchSelection()}
function printSelectedInventoryLabels(){const ids=selectedInventoryLabelIds();if(!ids.length)return;window.open(`/api/inventory/labels/print?item_ids=${encodeURIComponent(ids.join(","))}`,"_blank")}
function inventoryCsvCell(value){const text=String(value??"");return /[",\r\n]/.test(text)?`"${text.replaceAll('"','""')}"`:text}
async function prepareInventoryListings(){const itemIds=selectedInventoryLabelIds();if(!itemIds.length)throw new Error("Select at least one in-stock card.");const channel=$("inventoryListingChannel")?.value||"other",feePercent=Number(inventoryFeePresets()[channel]??0),fulfillment=inventoryFulfillmentPresets()[channel]||{},payload={item_ids:itemIds,channel,fee_percent:feePercent,shipping_cost:Number(fulfillment.shipping||0),packaging_cost:Number(fulfillment.packaging||0),desired_profit_percent:25},result=await api("/api/inventory/listing-drafts",{method:"POST",body:JSON.stringify(payload)}),drafts=result.drafts||[];if(!drafts.length)throw new Error("No selected cards are eligible for listing.");const fields=["status","channel","sku","title","description","price","currency","quantity","condition","set_name","collector_number","language","rarity","reference_image_url","verified_market","cost_basis","expected_fees","shipping_cost","packaging_cost","expected_profit","profile_url"],csv=[fields.join(","),...drafts.map(draft=>fields.map(field=>inventoryCsvCell(draft[field])).join(","))].join("\r\n"),url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})),link=document.createElement("a");link.href=url;link.download=`rareiq-${channel}-listing-drafts-${new Date().toISOString().slice(0,10)}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify("Listing Drafts Prepared",`${drafts.length} ${channel.replaceAll("_"," ")} ${drafts.length===1?"draft":"drafts"} downloaded${result.skipped?.length?` · ${result.skipped.length} skipped`:""}.`,"success");}
async function activateInventoryListing(item){const channel=$("inventoryListingChannel")?.value||"other",listingId=window.prompt(`Enter the ${channel.replaceAll("_"," ")} listing ID for ${item.item_id}`,item.active_listing?.listing_id||"");if(listingId===null)return;const listingUrl=window.prompt("Optional marketplace listing URL",item.active_listing?.listing_url||"");if(listingUrl===null)return;await api(`/api/inventory/items/${encodeURIComponent(item.item_id)}/listing`,{method:"POST",body:JSON.stringify({action:"activate",channel,listing_id:listingId.trim(),listing_url:listingUrl.trim(),asking_price:item.asking_price})});notify("Listing Activated",`${item.item_id} is now tracked on ${channel.replaceAll("_"," ")}.`,"success");return loadInventory()}
async function endInventoryListing(item){const listing=item.active_listing;if(!listing)return;if(!window.confirm(`End listing ${listing.listing_id||listing.listing_record_id}?`))return;await api(`/api/inventory/items/${encodeURIComponent(item.item_id)}/listing`,{method:"POST",body:JSON.stringify({action:"end",channel:listing.channel||"other",listing_id:listing.listing_id||""})});notify("Listing Ended",`${item.item_id} remains in stock.`,"success");return loadInventory()}
async function bulkUpdateInventoryListings(action){const itemIds=[...selectedInventoryListingIds];if(!itemIds.length)throw new Error("Select at least one active listing.");let adjustment=0;if(action==="reprice"){const value=window.prompt("Percentage adjustment for selected listings (use -10 to reduce by 10%)","-5");if(value===null)return;adjustment=Number(value);if(!Number.isFinite(adjustment)||adjustment< -95||adjustment>1000)throw new Error("Enter a percentage from -95 to 1000.");if(!window.confirm(`Reprice ${itemIds.length} selected ${itemIds.length===1?"listing":"listings"} by ${adjustment}%?`))return}else if(!window.confirm(`End ${itemIds.length} selected ${itemIds.length===1?"listing":"listings"}? Cards will remain in stock.`))return;const result=await api("/api/inventory/listings/bulk",{method:"POST",body:JSON.stringify({item_ids:itemIds,action,price_adjustment_percent:adjustment})});selectedInventoryListingIds.clear();notify(action==="reprice"?"Listings Repriced":"Listings Ended",`${result.updated||0} updated${result.failed?` · ${result.failed} skipped`:""}.`,result.failed?"warning":"success");return loadInventory()}
function inventorySmartRepriceProfiles(){const fees=inventoryFeePresets(),fulfillment=inventoryFulfillmentPresets(),profiles={};new Set([...Object.keys(fees),...Object.keys(fulfillment),"other"]).forEach(channel=>{const costs=fulfillment[channel]||{};profiles[channel]={fee_percent:Number(fees[channel]||0),shipping_cost:Number(costs.shipping||0),packaging_cost:Number(costs.packaging||0)}});return profiles}
async function smartRepriceInventoryListings(){const itemIds=[...selectedInventoryListingIds];if(!itemIds.length)throw new Error("Select at least one active listing.");const desiredInput=window.prompt("Desired profit margin percentage","25");if(desiredInput===null)return;const floorInput=window.prompt("Minimum profit dollars per card","2");if(floorInput===null)return;const desiredProfit=Number(desiredInput),minimumProfit=Number(floorInput);if(!Number.isFinite(desiredProfit)||desiredProfit<0||!Number.isFinite(minimumProfit)||minimumProfit<0)throw new Error("Profit margin and minimum profit must be zero or greater.");const payload={item_ids:itemIds,desired_profit_percent:desiredProfit,minimum_profit:minimumProfit,channel_profiles:inventorySmartRepriceProfiles(),apply:false},preview=await api("/api/inventory/listings/smart-reprice",{method:"POST",body:JSON.stringify(payload)}),rows=preview.recommendations||[];if(!rows.length)throw new Error("No selected listing has enough pricing information.");const sample=rows.slice(0,8).map(row=>`${row.card_name||row.item_id}: ${portfolioMoney(row.current_price,row.currency)} → ${portfolioMoney(row.recommended_price,row.currency)} · profit ${portfolioMoney(row.expected_profit,row.currency)}`).join("\n"),more=rows.length>8?`\n…and ${rows.length-8} more`:"";if(!window.confirm(`SMART REPRICE PREVIEW\n\n${sample}${more}\n\nApply these ${rows.length} protected prices?`))return;const applied=await api("/api/inventory/listings/smart-reprice",{method:"POST",body:JSON.stringify({...payload,apply:true})}),result=applied.applied||{};selectedInventoryListingIds.clear();notify("Smart Reprice Applied",`${result.updated||0} listings updated${result.failed?` · ${result.failed} skipped`:""}.`,result.failed?"warning":"success");return loadInventory()}
async function rollbackInventoryReprice(entry){const detail=entry.detail||{};if(!window.confirm(`Restore ${entry.card_name||entry.entity_id} from ${portfolioMoney(detail.asking_price)} to ${portfolioMoney(detail.previous_price)}?`))return;await api("/api/inventory/listings/reprice-rollback",{method:"POST",body:JSON.stringify({audit_id:entry.audit_id})});notify("Reprice Rolled Back",`${entry.entity_id} restored to ${portfolioMoney(detail.previous_price)}. Marketplace remains unchanged.`,"success");return loadInventory()}
function breakPerformanceQuery(){const period=$("breakPerformancePeriod")?.value||"lifetime",setFilter=$("breakPerformanceSet")?.value?.trim()||"",query=`period=${encodeURIComponent(period)}&set_filter=${encodeURIComponent(setFilter)}`;if($("breakPerformanceExport"))$("breakPerformanceExport").href=`/api/inventory/break-performance.csv?${query}`;return query}
async function loadInventory(){const performanceQuery=breakPerformanceQuery(),trendDays=Number($("businessTrendDays")?.value||30),taxYear=Number($("inventoryTaxYear")?.value||new Date().getFullYear()),period=selectedAccountingPeriod(),staleDays=Number($("inventoryListingStaleDays")?.value||30),[payload,,valuation,performance,trends,taxComparison,profile,audit,profitLoss,listingDashboard,repriceHistory,syncQueue]=await Promise.all([api("/api/inventory"),loadPriceWatchlist().catch(()=>null),api("/api/inventory/valuation").catch(()=>null),api(`/api/inventory/break-performance?${performanceQuery}`).catch(()=>null),api(`/api/inventory/business-trends?days=${trendDays}`).catch(()=>null),api(`/api/inventory/tax-comparison?year=${taxYear}`).catch(()=>null),api("/api/inventory/business-profile").catch(()=>null),api("/api/inventory/audit-log?limit=50").catch(()=>null),period.year&&period.month?api(`/api/inventory/profit-and-loss?year=${period.year}&month=${period.month}`).catch(()=>null):null,api(`/api/inventory/listing-dashboard?stale_days=${staleDays}`).catch(()=>null),api("/api/inventory/listings/reprice-history?limit=100").catch(()=>null),api("/api/inventory/marketplace-sync?limit=100").catch(()=>null)]);renderInventory(payload);if(valuation)renderInventoryValuation(valuation);if(listingDashboard)renderInventoryListingDashboard(listingDashboard);if(repriceHistory)renderInventoryRepriceHistory(repriceHistory);if(syncQueue)renderInventoryMarketplaceSync(syncQueue);if(performance)renderBreakPerformance(performance);if(trends){renderBusinessTrends(trends);decorateExpenseEditButtons(trends.expenses||[])}if(taxComparison)renderTaxComparison(taxComparison);if(profile||audit)renderAccountingControls(profile||{},audit||{});if(profitLoss)renderProfitAndLoss(profitLoss);return payload;}
async function createInventoryItem(event){event.preventDefault();const card=collectionInventory.find(item=>item.version_key===$("inventoryCard").value);if(!card)throw new Error("Choose an owned card first.");const quantity=Math.max(1,Math.min(100,Number($("inventoryQuantity")?.value||1)));const payload={card,quantity,cost_basis:Number($("inventoryCostBasis").value||0),asking_price:$("inventoryAskingPrice").value===""?null:Number($("inventoryAskingPrice").value),condition:$("inventoryCondition").value,location:$("inventoryLocation").value};const result=await api("/api/inventory/items/batch",{method:"POST",body:JSON.stringify(payload)});const ids=(result.items||[]).map(item=>item.item_id);notify("QR Inventory Batch Created",`${ids.length} unique ${ids.length===1?"item is":"items are"} ready to print.`,"success");if(ids.length)window.open(`/api/inventory/labels/print?item_ids=${encodeURIComponent(ids.join(","))}`,"_blank");return loadInventory();}
async function findInventoryItem(event){event.preventDefault();const code=$("inventoryLookup").value.trim().toUpperCase();if(!code)return;const result=await api(`/api/inventory/items/${encodeURIComponent(code)}`);const item=result.item;notify("Inventory Item Found",`${item.english_name||item.card_name} · ${item.status.replace("_"," ")}`,item.status==="in_stock"?"success":"warning");if(item.status==="in_stock")checkoutInventoryItem(item);}
function updateInventoryCheckoutPreview(){if(!inventoryCheckoutItem)return;const gross=Number($("inventorySalePrice")?.value||0),fees=Number($("inventorySaleFees")?.value||0),shipping=Number($("inventoryShippingCost")?.value||0),packaging=Number($("inventoryPackagingCost")?.value||0),cost=Number(inventoryCheckoutItem.cost_basis||0);if($("inventoryNetPreview"))$("inventoryNetPreview").textContent=money(gross-fees-shipping-packaging);if($("inventoryProfitPreview"))$("inventoryProfitPreview").textContent=money(gross-fees-shipping-packaging-cost);}
async function updateInventorySellRecommendation(){if(!inventoryCheckoutItem)return;const feePercent=Math.max(0,Number($("inventoryFeePercent")?.value||0)),shipping=Math.max(0,Number($("inventoryShippingCost")?.value||0)),packaging=Math.max(0,Number($("inventoryPackagingCost")?.value||0)),profit=Math.max(0,Number($("inventoryDesiredProfit")?.value||0)),query=new URLSearchParams({fee_percent:String(feePercent),shipping_cost:String(shipping),packaging_cost:String(packaging),desired_profit_percent:String(profit)}),result=await api(`/api/inventory/items/${encodeURIComponent(inventoryCheckoutItem.item_id)}/sell-recommendation?${query}`),recommendation=result.recommendation||{};inventorySellRecommendation=recommendation;setCardText("inventoryRecommendedPrice",portfolioMoney(recommendation.recommended_price,recommendation.currency),"Unavailable");const market=recommendation.verified_market==null?"no verified market quote":`verified market ${portfolioMoney(recommendation.verified_market,recommendation.currency)}`;setCardText("inventoryRecommendationDetail",`${market} · break-even ${portfolioMoney(recommendation.break_even_price,recommendation.currency)} · target ${portfolioMoney(recommendation.target_price,recommendation.currency)} · fulfillment ${portfolioMoney(recommendation.fulfillment_cost,recommendation.currency)} · expected profit ${portfolioMoney(recommendation.expected_profit,recommendation.currency)}`);}
function applyInventorySellRecommendation(){if(!inventorySellRecommendation)return;$("inventorySalePrice").value=Number(inventorySellRecommendation.recommended_price||0).toFixed(2);$("inventorySaleFees").value=Number(inventorySellRecommendation.expected_fees||0).toFixed(2);updateInventoryCheckoutPreview();}
function closeInventoryCheckout(){inventoryCheckoutItem=null;if($("inventoryCheckoutOverlay"))$("inventoryCheckoutOverlay").hidden=true;}
function checkoutInventoryItem(item){inventoryCheckoutItem=item;inventorySellRecommendation=null;$("inventoryCheckoutItemId").value=item.item_id;$("inventoryCheckoutTitle").textContent=item.english_name||item.card_name||"Sell inventory item";const valuation=item.acquisition_valuation||{};$("inventoryCheckoutMeta").textContent=`${item.item_id} · cost ${money(item.cost_basis||0)} · ${item.location||"No location"}${item.pricing_resolution_id?` · acquired at ${portfolioMoney(valuation.market,valuation.currency)}`:""}`;$("inventorySalePrice").value=item.asking_price??"";$("inventorySaleFees").value="0";$("inventoryShippingCost").value="0";$("inventoryPackagingCost").value="0";$("inventoryOrderReference").value="";$("inventoryCheckoutOverlay").hidden=false;updateInventoryCheckoutPreview();applyInventoryChannelPreset().catch(error=>setCardText("inventoryRecommendationDetail",error.message||String(error)));$("inventorySalePrice").focus();}
async function completeInventoryCheckout(event){event.preventDefault();if(!inventoryCheckoutItem)throw new Error("No inventory item selected.");const payload={sale_price:Number($("inventorySalePrice").value),fees:Number($("inventorySaleFees").value||0),shipping_cost:Number($("inventoryShippingCost").value||0),packaging_cost:Number($("inventoryPackagingCost").value||0),channel:$("inventorySaleChannel").value,order_reference:$("inventoryOrderReference").value};await api(`/api/inventory/items/${encodeURIComponent(inventoryCheckoutItem.item_id)}/sell`,{method:"POST",body:JSON.stringify(payload)});notify("Card Sold",`${inventoryCheckoutItem.item_id} removed from active stock and profit recorded.`,"success");$("inventoryLookup").value="";closeInventoryCheckout();return loadInventory();}
async function voidInventorySale(item){if(!window.confirm(`Void the sale for ${item.item_id} and return it to active stock?`))return;await api(`/api/inventory/items/${encodeURIComponent(item.item_id)}/void-sale`,{method:"POST",body:JSON.stringify({reason:"operator_return_or_correction"})});notify("Sale Voided",`${item.item_id} returned to active stock.`,"success");return loadInventory();}
function stopInventoryScanner(){clearTimeout(inventoryScannerTimer);inventoryScannerTimer=null;inventoryScannerStream?.getTracks().forEach(track=>track.stop());inventoryScannerStream=null;inventoryScannerBusy=false;$("inventoryScannerVideo")?.remove();if($("inventoryScannerOverlay"))$("inventoryScannerOverlay").hidden=true;}
async function inventoryScannerCameras(){const devices=await navigator.mediaDevices.enumerateDevices();const cameras=devices.filter(device=>device.kind==="videoinput");const select=$("inventoryScannerCamera");if(select){const current=select.value;select.replaceChildren(...cameras.map((camera,index)=>new Option(camera.label||`Camera ${index+1}`,camera.deviceId)));if(cameras.some(camera=>camera.deviceId===current))select.value=current;}return cameras;}
async function startInventoryScanner(){
  if(!navigator.mediaDevices?.getUserMedia)throw new Error("Camera scanning is not supported in this browser.");
  if(typeof BarcodeDetector==="undefined")throw new Error("This browser does not support live QR detection. Use Chrome or enter the RIQ code manually.");
  stopInventoryScanner();$("inventoryScannerOverlay").hidden=false;$("inventoryScannerStatus").textContent="Starting camera...";
  const deviceId=$("inventoryScannerCamera")?.value;inventoryScannerStream=await navigator.mediaDevices.getUserMedia({video:deviceId?{deviceId:{exact:deviceId},width:{ideal:1280},height:{ideal:720}}:{facingMode:{ideal:"environment"},width:{ideal:1280},height:{ideal:720}},audio:false});
  const video=document.createElement("video");video.id="inventoryScannerVideo";video.playsInline=true;video.muted=true;$("inventoryScannerView").prepend(video);video.srcObject=inventoryScannerStream;await video.play();await inventoryScannerCameras();$("inventoryScannerStatus").textContent="Ready · hold the QR code inside the frame";scanInventoryQrFrame();
}
async function scanInventoryQrFrame(){
  if(!inventoryScannerStream||inventoryScannerBusy)return;inventoryScannerBusy=true;
  try{const detector=new BarcodeDetector({formats:["qr_code"]});const codes=await detector.detect($("inventoryScannerVideo"));const value=String(codes[0]?.rawValue||"").trim().toUpperCase();const now=Date.now();if(/^RIQ-[A-F0-9]{12}$/.test(value)&&!(value===inventoryScannerLastCode&&now-inventoryScannerLastAt<3000)){inventoryScannerLastCode=value;inventoryScannerLastAt=now;$("inventoryScannerStatus").textContent=`Found ${value}`;const result=await api(`/api/inventory/items/${encodeURIComponent(value)}`);stopInventoryScanner();if(result.item.status==="in_stock")checkoutInventoryItem(result.item);else notify("Already Sold",`${value} was sold previously.`,"warning");return;}}catch(error){if(inventoryScannerStream)$("inventoryScannerStatus").textContent=error.message||"QR detection paused";}finally{inventoryScannerBusy=false;}inventoryScannerTimer=setTimeout(scanInventoryQrFrame,180);
}

function dispositionControls(card){
  const disposition=card.disposition||{};
  const quantity=Number(card.quantity||0);
  const trade=Number(disposition.trade||0),sell=Number(disposition.sell||0);
  const keep=Math.max(0,quantity-trade-sell);
  const wrapper=document.createElement("div");
  wrapper.className="collection-disposition-controls";
  wrapper.innerHTML=`<label>Keep <b>${keep}</b></label><label>Trade <input type="number" min="0" max="${quantity}" value="${trade}"></label><label>Sell <input type="number" min="0" max="${quantity}" value="${sell}"></label><button type="button">Save</button>`;
  wrapper.querySelector("button").addEventListener("click",async()=>{
    const inputs=wrapper.querySelectorAll("input");
    try{
      await updateCollectionDisposition(card.version_key,Number(inputs[0].value||0),Number(inputs[1].value||0));
    }catch(error){notify("Allocation Not Saved",error.message||String(error),"error");}
  });
  return wrapper;
}

function renderDuplicateQueue(cards,summary={}){
  const duplicates=cards.filter(card=>Number(card.quantity||0)>1);
  const grid=$("collectionDuplicateGrid");
  if(grid){
    grid.replaceChildren(...duplicates.map(card=>{
      const article=document.createElement("article");
      article.innerHTML=`<div><strong>${card.english_name||card.card_name||"Unknown card"}</strong><span>${card.set_name||card.set_code||"Unknown set"} · ${card.collector_number||"--"}</span></div><b>${Number(card.quantity||0)} copies</b>`;
      article.appendChild(dispositionControls(card));
      return article;
    }));
  }
  if($("collectionDuplicatesEmpty")) $("collectionDuplicatesEmpty").hidden=duplicates.length>0;
  if($("collectionDispositionCount")) $("collectionDispositionCount").textContent=`${Number(summary.trade_copies||0)} trade · ${Number(summary.sell_copies||0)} sell`;
}

async function updateCollectionDisposition(versionKey,trade,sell){
  await api("/api/collection/disposition",{method:"POST",body:JSON.stringify({version_key:versionKey,trade,sell})});
  notify("Duplicate Allocation Saved",`${trade} trade · ${sell} sell`,"success");
  return loadCollection();
}

async function readCollectionBackup(){
  const file=$("collectionBackupFile")?.files?.[0];
  if(!file) throw new Error("Choose a RareIQ JSON backup first.");
  let payload;
  try{payload=JSON.parse(await file.text());}catch(_error){throw new Error("The selected file is not valid JSON.");}
  const result=await api("/api/collection/import/preview",{method:"POST",body:JSON.stringify({backup:payload})});
  collectionImportBackup=payload;
  const preview=$("collectionImportPreview");
  if(preview){
    const conflicts=Array.isArray(result.conflicts)?result.conflicts:[];
    preview.hidden=false;
    preview.innerHTML=`<div><strong>${Number(result.new_versions||0)}</strong><span>new versions</span></div><div><strong>${Number(result.new_events||0)}</strong><span>new scan events</span></div><div><strong>${Number(result.conflict_count||0)}</strong><span>quantity conflicts</span></div><p>Conflict strategy: keep the higher owned quantity; union history by stable ID.</p>${conflicts.length?`<details><summary>Review ${conflicts.length} conflicts</summary><div>${conflicts.map(item=>`<span>${item.card_name||item.version_key}: local ${item.local_quantity}, backup ${item.incoming_quantity} → ${item.resolved_quantity}</span>`).join("")}</div></details>`:""}`;
  }
  if($("mergeCollectionBackup")) $("mergeCollectionBackup").disabled=false;
  notify("Backup Preview Ready","Review the merge summary before continuing.","success");
}

async function mergeCollectionBackup(){
  if(!collectionImportBackup) throw new Error("Preview a valid backup first.");
  const result=await api("/api/collection/import/merge",{method:"POST",body:JSON.stringify({backup:collectionImportBackup})});
  collectionImportBackup=null;
  if($("mergeCollectionBackup")) $("mergeCollectionBackup").disabled=true;
  if($("collectionImportPreview")) $("collectionImportPreview").hidden=true;
  if($("collectionBackupFile")) $("collectionBackupFile").value="";
  notify("Backup Merged",`${Number(result.new_versions||0)} versions added without overwriting local inventory.`,"success");
  return loadCollection();
}

function renderCollectionGoals(goals,summary={}){
  const grid=$("collectionGoalGrid");
  if(grid){
    grid.replaceChildren(...goals.map(goal=>{
      const article=document.createElement("article");
      article.className=`collection-goal-card priority-${goal.priority}${goal.complete?" complete":""}`;
      const label=goal.target_type==="card"
        ?(goal.resolved_name||goal.card_name||`${goal.set_name} #${goal.collector_number}`)
        :`${goal.set_name} collection`;
      article.innerHTML=`<div class="collection-goal-head"><span>${goal.priority} priority · ${goal.target_type}</span><button type="button" aria-label="Archive goal">×</button></div><strong>${label}</strong><small>${goal.target_type==="card"?`${goal.set_name} · ${goal.collector_number}`:`Target ${goal.target_quantity} unique versions`}</small><div class="collection-progress-track"><i style="width:${Number(goal.progress_percent||0)}%"></i></div><div class="collection-goal-foot"><span>${Number(goal.current_quantity||0)} / ${Number(goal.target_quantity||1)} · ${Number(goal.progress_percent||0)}%</span><b>${goal.complete?"Complete":goal.identity_status==="catalog_resolved"?"Catalog matched":"Manual target"}</b></div>${goal.notes?`<p>${goal.notes}</p>`:""}`;
      article.querySelector("button").addEventListener("click",()=>archiveCollectionGoal(goal.id));
      return article;
    }));
  }
  if($("collectionGoalsEmpty")) $("collectionGoalsEmpty").hidden=goals.length>0;
  if($("collectionGoalCount")) $("collectionGoalCount").textContent=`${Number(summary.active_goals||0)} active · ${Number(summary.completed_goals||0)} complete`;
}

async function createCollectionGoal(event){
  event.preventDefault();
  const targetType=$("collectionGoalType")?.value||"card";
  const payload={
    target_type:targetType,set_name:$("collectionGoalSet")?.value||"",
    collector_number:targetType==="card"?$("collectionGoalNumber")?.value||null:null,
    target_quantity:Number($("collectionGoalQuantity")?.value||1),
    priority:$("collectionGoalPriority")?.value||"medium",notes:$("collectionGoalNotes")?.value||""
  };
  await api("/api/collection/goals",{method:"POST",body:JSON.stringify(payload)});
  $("collectionGoalNotes").value="";
  notify("Goal Added","Collection progress will update automatically.","success");
  return loadCollection();
}

async function archiveCollectionGoal(goalId){
  await api(`/api/collection/goals/${encodeURIComponent(goalId)}/archive`,{method:"POST"});
  notify("Goal Archived","The goal was removed from the active watchlist.","success");
  return loadCollection();
}

function renderCollectionTrends(trends){
  const daily=Array.isArray(trends.daily)?trends.daily:[];
  const renderBars=(element,key,formatter)=>{
    if(!element) return;
    const maximum=Math.max(1,...daily.map(item=>Math.abs(Number(item[key]||0))));
    element.replaceChildren(...daily.slice(-14).map(item=>{
      const value=Number(item[key]||0);
      const bar=document.createElement("div");
      bar.className=value<0?"negative":"";
      bar.title=`${item.date}: ${formatter(value)}`;
      bar.innerHTML=`<i style="height:${Math.max(value===0?2:8,Math.abs(value)/maximum*100)}%"></i><span>${String(item.date||"").slice(5)}</span>`;
      return bar;
    }));
  };
  renderBars($("collectionAcquisitionChart"),"cards_delta",value=>`${value>0?"+":""}${value} cards`);
  renderBars($("collectionValueChart"),"verified_value_delta",value=>money(value));
  if($("collectionTrendWindow")) $("collectionTrendWindow").textContent=`Last ${Number(trends.window_days||30)} days`;
  if($("collectionBaselineNote")) $("collectionBaselineNote").hidden=trends.has_legacy_baseline!==true;
  const growth=Array.isArray(trends.set_growth)?trends.set_growth:[];
  const setGrowth=$("collectionSetGrowth");
  if(setGrowth){
    setGrowth.replaceChildren(...growth.slice(0,6).map(item=>{
      const row=document.createElement("div");
      row.innerHTML=`<span>${item.set_name||"Unknown set"}</span><strong>${Number(item.cards_delta||0)>0?"+":""}${Number(item.cards_delta||0)}</strong>`;
      return row;
    }));
  }
  const activity=Array.isArray(trends.recent_activity)?trends.recent_activity:[];
  const activityList=$("collectionActivity");
  if(activityList){
    activityList.replaceChildren(...activity.slice(0,10).map(item=>{
      const row=document.createElement("div");
      const delta=Number(item.quantity_delta||0);
      row.innerHTML=`<i class="${delta<0?"negative":""}">${delta>0?"+":""}${delta}</i><span><strong>${item.card_name||item.label||"Collection baseline"}</strong><small>${item.set_name||item.label||""}${item.collector_number?` · ${item.collector_number}`:""}</small></span><time>${collectionDate(item.created_at)}</time>`;
      return row;
    }));
  }
}

function renderCollectionValuation(valuation){
  const currency=valuation.currency||"USD";
  const format=value=>new Intl.NumberFormat("en-US",{style:"currency",currency,maximumFractionDigits:2}).format(Number(value||0));
  if($("collectionPortfolioValue")) $("collectionPortfolioValue").textContent=format(valuation.portfolio_value);
  if($("collectionPricingCoverage")) $("collectionPricingCoverage").textContent=`${Number(valuation.pricing_coverage_percent||0)}% pricing coverage`;
  if($("collectionPricingCounts")) $("collectionPricingCounts").textContent=`${Number(valuation.priced_copies||0)} priced · ${Number(valuation.unpriced_copies||0)} unpriced`;
  const renderList=(element,items,labelKey,countKey)=>{
    if(!element) return;
    element.replaceChildren(...items.slice(0,6).map(item=>{
      const row=document.createElement("div");
      row.innerHTML=`<span>${item[labelKey]||"Unknown"}<small>${Number(item[countKey]||0)} copies</small></span><strong>${format(item.value)}</strong>`;
      return row;
    }));
  };
  renderList($("collectionSetValues"),Array.isArray(valuation.set_values)?valuation.set_values:[],"set_name","priced_copies");
  renderList($("collectionRarityValues"),Array.isArray(valuation.rarity_values)?valuation.rarity_values:[],"rarity","copies");
  const hits=Array.isArray(valuation.biggest_hits)?valuation.biggest_hits:[];
  const hitGrid=$("collectionBiggestHits");
  if(hitGrid){
    hitGrid.replaceChildren(...hits.slice(0,5).map((card,index)=>{
      const article=document.createElement("article");
      article.innerHTML=`<span>#${index+1}</span><div><strong>${card.english_name||card.card_name||"Unknown card"}</strong><small>${card.set_name||"Unknown set"} · ${card.collector_number||"--"}</small></div><b>${format(card.unit_price)}</b>`;
      return article;
    }));
  }
  if($("collectionValueEmpty")) $("collectionValueEmpty").hidden=hits.length>0;
}

function renderCollectionSets(sets){
  const grid=$("collectionSetGrid");
  if(grid){
    grid.replaceChildren(...sets.map(set=>{
      const article=document.createElement("article");
      article.className="collection-set-card";
      const available=set.checklist_status==="available";
      const percent=available?Math.max(0,Math.min(100,Number(set.completion_percent||0))):0;
      article.innerHTML=`
        <div class="collection-set-title"><div><strong>${set.set_name||"Unknown set"}</strong><span>${set.set_code||"Local collection"}</span></div><b>${available?`${percent}%`:"Owned"}</b></div>
        <div class="collection-set-stats"><span><b>${Number(set.owned_versions||0)}</b> versions</span><span><b>${Number(set.total_copies||0)}</b> copies</span><span><b>${Number(set.duplicate_copies||0)}</b> duplicates</span></div>
        ${available?`<div class="collection-progress-track" aria-label="${percent}% complete"><i style="width:${percent}%"></i></div><p>${Number(set.catalog_owned||0)} of ${Number(set.catalog_total||0)} catalog cards owned</p>`:`<p>Reference checklist not loaded — completion is not estimated.</p>`}
      `;
      if(available&&Array.isArray(set.missing_cards)&&set.missing_cards.length){
        const details=document.createElement("details");
        details.className="collection-missing-list";
        const summary=document.createElement("summary");
        summary.textContent=`${set.missing_cards.length} missing cards`;
        details.appendChild(summary);
        const list=document.createElement("div");
        set.missing_cards.forEach(card=>{
          const item=document.createElement("span");
          item.textContent=`${card.collector_number||"--"} · ${card.card_name||card.printed_name||"Unknown card"}`;
          list.appendChild(item);
        });
        details.appendChild(list);
        article.appendChild(details);
      }
      return article;
    }));
  }
  if($("collectionSetsEmpty")) $("collectionSetsEmpty").hidden=sets.length>0;
  if($("collectionSetCount")) $("collectionSetCount").textContent=`${sets.length} ${sets.length===1?"set":"sets"}`;
}

function populateCollectionFilters(cards){
  const populate=(element,values,label)=>{
    if(!element) return;
    const selected=element.value;
    element.replaceChildren(new Option(label,""),...values.map(value=>new Option(value,value)));
    if(values.includes(selected)) element.value=selected;
  };
  populate($("collectionSetFilter"),[...new Set(cards.map(card=>card.set_name||card.set_code).filter(Boolean))].sort(),"All sets");
  populate($("collectionLanguageFilter"),[...new Set(cards.map(card=>card.language).filter(Boolean))].sort(),"All languages");
}

function renderCollectionRows(){
  const query=($("collectionSearch")?.value||"").trim().toLocaleLowerCase();
  const setFilter=$("collectionSetFilter")?.value||"";
  const languageFilter=$("collectionLanguageFilter")?.value||"";
  const duplicatesOnly=$("collectionDuplicatesOnly")?.checked===true;
  const sort=$("collectionSort")?.value||"recent";
  const cards=collectionInventory.filter(card=>{
    const haystack=[card.card_name,card.english_name,card.printed_name,card.set_name,card.set_code,card.collector_number].join(" ").toLocaleLowerCase();
    return (!query||haystack.includes(query))
      &&(!setFilter||(card.set_name||card.set_code)===setFilter)
      &&(!languageFilter||card.language===languageFilter)
      &&(!duplicatesOnly||Number(card.quantity||0)>1);
  }).sort((a,b)=>{
    if(sort==="name") return String(a.english_name||a.card_name||"").localeCompare(String(b.english_name||b.card_name||""));
    if(sort==="quantity") return Number(b.quantity||0)-Number(a.quantity||0);
    if(sort==="number") return String(a.collector_number||"").localeCompare(String(b.collector_number||""),undefined,{numeric:true});
    return Number(b.last_seen_at||0)-Number(a.last_seen_at||0);
  });
  const rows=$("collectionRows");
  if(rows){
    rows.replaceChildren(...cards.map(card=>{
      const tr=document.createElement("tr");
      const values=[
        card.english_name||card.card_name||card.printed_name||"Unknown card",
        card.set_name||card.set_code||"--",
        card.collector_number||"--",
        card.language||"--",
        collectionDate(card.last_seen_at),
      ];
      values.forEach((value,index)=>{
        const td=document.createElement("td");
        td.textContent=value;
        tr.appendChild(td);
        if(index===3){
          const quantity=document.createElement("td");
          quantity.className="collection-quantity";
          quantity.innerHTML=`<button type="button" aria-label="Remove one copy">−</button><strong>${Number(card.quantity||0)}</strong><button type="button" aria-label="Add one copy">+</button>`;
          const buttons=quantity.querySelectorAll("button");
          buttons[0].addEventListener("click",()=>adjustCollection(card.version_key,-1));
          buttons[1].addEventListener("click",()=>adjustCollection(card.version_key,1));
          tr.appendChild(quantity);
        }
      });
      if(Number(card.quantity||0)>1){
        const allocation=document.createElement("td");
        allocation.className="collection-row-allocation";
        allocation.colSpan=6;
        allocation.appendChild(dispositionControls(card));
        const allocationRow=document.createElement("tr");
        allocationRow.className="collection-allocation-row";
        allocationRow.appendChild(allocation);
        tr.afterRow=allocationRow;
      }
      return tr;
    }).flatMap(row=>row.afterRow?[row,row.afterRow]:[row]));
  }
  const hasInventory=collectionInventory.length>0;
  if($("collectionEmpty")){
    $("collectionEmpty").hidden=cards.length>0;
    $("collectionEmpty").textContent=hasInventory?"No cards match these filters.":"Approve a verified card to begin your collection.";
  }
  if($("collectionTableWrap")) $("collectionTableWrap").hidden=cards.length===0;
  if($("collectionUpdated")&&hasInventory) $("collectionUpdated").textContent=`${cards.length} of ${collectionInventory.length} exact versions`;
}

async function adjustCollection(versionKey,delta){
  const payload=await api("/api/collection/adjust",{
    method:"POST",
    body:JSON.stringify({version_key:versionKey,delta,reason:"operator_quantity_correction"})
  });
  notify("Collection Updated",`${delta>0?"Added":"Removed"} one copy.`,"success");
  return loadCollection();
}

async function undoCollectionCorrection(correctionId){
  await api(`/api/collection/corrections/${encodeURIComponent(correctionId)}/undo`,{method:"POST"});
  notify("Correction Undone","The previous quantity is restored.","success");
  return loadCollection();
}

function switchDock(name){
  document.querySelectorAll(".dock-tab").forEach(el=>{
    el.classList.toggle("active",el.dataset.dock===name);
  });
  document.querySelectorAll(".dock-panel").forEach(el=>{
    el.classList.toggle("active",el.dataset.panel===name);
  });
}

function toggleDock(){
  setUI4DiagnosticsOpen(!ui4DiagnosticsOpen);
}

async function api(path,options={}){
  const {timeoutMs=15000,retries:requestedRetries,signal:externalSignal,...fetchOptions}=options;
  const method=String(fetchOptions.method||"GET").toUpperCase();
  const retries=Number.isFinite(requestedRetries)?Math.max(0,Number(requestedRetries)):(method==="GET"?1:0);
  let response=null,lastError=null;
  document.dispatchEvent(new CustomEvent("rareiq:api-start",{detail:{path,method}}));
  for(let attempt=0;attempt<=retries;attempt+=1){
    const controller=new AbortController();
    const timeout=window.setTimeout(()=>controller.abort(new DOMException(`Request timed out after ${timeoutMs} ms`,"TimeoutError")),timeoutMs);
    const abortExternal=()=>controller.abort(externalSignal.reason);
    externalSignal?.addEventListener?.("abort",abortExternal,{once:true});
    try{
      response=await fetch(path,{cache:"no-store",headers:{"Content-Type":"application/json"},...fetchOptions,signal:controller.signal});
      if(response.ok||![502,503,504].includes(response.status)||attempt===retries)break;
      lastError=new Error(`Temporary service error: ${response.status}`);
    }catch(error){
      lastError=error;
      if(externalSignal?.aborted||attempt===retries)break;
    }finally{
      window.clearTimeout(timeout);
      externalSignal?.removeEventListener?.("abort",abortExternal);
    }
    await new Promise(resolve=>window.setTimeout(resolve,180*(attempt+1)));
  }
  if(!response){
    const error=lastError?.name==="AbortError"||lastError?.name==="TimeoutError"
      ?new Error(`RareIQ did not receive a response from ${path} within ${timeoutMs/1000} seconds.`)
      :new Error(navigator.onLine===false?"This device is offline.":lastError?.message||`Unable to reach ${path}.`);
    document.dispatchEvent(new CustomEvent("rareiq:api-error",{detail:{path,method,error}}));
    throw error;
  }

  const contentType=response.headers.get("content-type")||"";
  const text=await response.text();
  let payload=null;

  if(contentType.includes("application/json")){
    try{
      payload=text?JSON.parse(text):{};
    }catch(error){
      throw new Error(`Invalid JSON from ${path}: ${error.message}`);
    }
  }else{
    const preview=text.replace(/\s+/g," ").slice(0,160);
    throw new Error(
      `API ${path} returned ${response.status} ${response.statusText} as ${contentType||"unknown content"}: ${preview}`
    );
  }

  if(!response.ok){
    const requestError=new Error(
      payload?.message ||
      payload?.error ||
      payload?.reason ||
      `Request failed: ${response.status} ${response.statusText}`
    );
    requestError.payload=payload;
    requestError.status=response.status;
    document.dispatchEvent(new CustomEvent("rareiq:api-error",{detail:{path,method,error:requestError}}));
    throw requestError;
  }

  document.dispatchEvent(new CustomEvent("rareiq:api-end",{detail:{path,method,status:response.status}}));
  return payload;
}

let cameraPtzDevices=[];
let cameraPtzSnapshot={};
function positionCameraPtzPanel(){const panel=$("cameraPtzPanel"),button=$("cameraPtzButton");if(!panel||!button||panel.hidden)return;const anchor=button.getBoundingClientRect(),gap=8,width=Math.min(360,Math.max(280,window.innerWidth-24)),left=Math.max(12,Math.min(anchor.left,window.innerWidth-width-12)),top=Math.max(12,Math.min(anchor.bottom+gap,window.innerHeight-24));panel.classList.add("ptz-floating");panel.style.width=`${width}px`;panel.style.left=`${left}px`;panel.style.right="auto";panel.style.top=`${top}px`;panel.style.maxHeight=`${Math.max(240,window.innerHeight-top-12)}px`}
function renderCameraPtzStatus(ptz={},cameras=null){
  const message=$("cameraPtzMessage");
  const panel=$("cameraPtzPanel");
  if(!message||!panel)return;
  if(Array.isArray(cameras))cameraPtzDevices=cameras;
  cameraPtzSnapshot=ptz;
  const state=ptz.state||"offline";
  const capabilities=ptz.profile?.capabilities||{};
  panel.dataset.state=state;
  message.textContent=ptz.message||"Camera movement controls are ready.";
  panel.querySelectorAll("[data-ptz-action]").forEach(button=>{
    const action=button.dataset.ptzAction||"";
    const capability=action.startsWith("pan_")?"pan":action.startsWith("tilt_")?"tilt":action.startsWith("zoom_")?"zoom":action.includes("preset")?"presets":action;
    button.disabled=state==="offline"||capabilities[capability]===false;
    button.title=capabilities[capability]===false?`${capability} is not exposed by this camera`:"";
    if(button.dataset.ptzPreset){
      button.classList.toggle("saved",Boolean(ptz.presets?.[button.dataset.ptzPreset]));
    }
  });
  const capabilityHost=$("cameraPtzCapabilities");
  if(capabilityHost){
    const transports=ptz.profile?.transport||{};
    capabilityHost.innerHTML=["pan","tilt","zoom","recenter","presets","autofocus","tracking"].map(name=>{
      const enabled=Boolean(capabilities[name]);
      const assisted=transports[name]==="insta360-controller";
      return `<span class="${enabled?"available":"unavailable"}${assisted?" assisted":""}" title="${assisted?"Uses Insta360 Controller":""}">${enabled?"✓":"—"} ${name}${assisted?" · app":""}</span>`;
    }).join("");
  }
  const picker=$("cameraPtzDevice");
  if(picker&&cameraPtzDevices.length){
    picker.innerHTML=cameraPtzDevices.map((camera,index)=>{
      const profile=camera.control_profile||{};
      const selected=camera.selected||camera.source_id===ptz.selected_source_id;
      return `<option value="${index}" ${selected?"selected":""}>${camera.name} · ${profile.label||"Camera"} · ${profile.control_score||0} controls</option>`;
    }).join("");
  }
  const properties=ptz.properties||{};
  document.querySelectorAll("[data-imaging-row]").forEach(row=>{
    const property=properties[row.dataset.imagingRow]||{};
    row.classList.toggle("unavailable",!property.readable);
    row.querySelectorAll("button").forEach(button=>button.disabled=!property.readable);
    const output=row.querySelector("output");
    if(output)output.textContent=property.readable?Number(property.value).toFixed(property.value%1?1:0):"—";
  });
  document.querySelectorAll("[data-camera-imaging-toggle]").forEach(button=>{
    const name=button.dataset.cameraImagingToggle;
    const property=properties[name]||{};
    const active=name==="auto_exposure"?Number(property.value)>=.5:Number(property.value)>0;
    button.disabled=!property.readable;
    button.classList.toggle("active",active);
    button.setAttribute("aria-pressed",String(active));
  });
}

async function refreshCameraPtzStatus(){
  try{
    const payload=await api("/api/camera/ptz",{timeoutMs:5000});
    renderCameraPtzStatus(payload.ptz,payload.cameras);
  }catch(error){
    renderCameraPtzStatus({state:"offline",message:error.message});
  }
}

async function activateCameraPtzDevice(){
  const device=cameraPtzDevices[Number($("cameraPtzDevice")?.value)];
  if(!device)return;
  const button=$("cameraPtzActivate");
  if(button){button.disabled=true;button.textContent="Opening…"}
  try{
    await api("/api/camera/start",{method:"POST",timeoutMs:18000,body:JSON.stringify({camera_index:device.index,camera_backend:device.backend})});
    notify("Camera controls ready",`${device.name} is now the active controlled camera.`,"success");
    await refreshCameraPtzStatus();
  }catch(error){
    renderCameraPtzStatus({state:"limited",message:error.message});
  }finally{
    if(button){button.disabled=false;button.textContent="Use"}
  }
}

async function setCameraImagingControl(control,value){
  const panel=$("cameraPtzPanel");
  panel?.classList.add("working");
  try{
    const payload=await api("/api/camera/ptz",{
      method:"POST",timeoutMs:3000,
      body:JSON.stringify({action:"set_imaging",control,value,speed:$("cameraPtzSpeed")?.value||"medium"})
    });
    renderCameraPtzStatus(payload.ptz);
  }catch(error){
    renderCameraPtzStatus(error.payload?.ptz||{...cameraPtzSnapshot,state:"limited",message:error.message});
  }finally{panel?.classList.remove("working")}
}

async function runCameraPtzAction(action,preset=null){
  const panel=$("cameraPtzPanel");
  const message=$("cameraPtzMessage");
  panel?.classList.add("working");
  if(message)message.textContent=`Sending ${action.replaceAll("_"," ")}…`;
  try{
    const payload=await api("/api/camera/ptz",{
      method:"POST",
      timeoutMs:3000,
      body:JSON.stringify({action,speed:$("cameraPtzSpeed")?.value||"medium",preset})
    });
    renderCameraPtzStatus(payload.ptz);
  }catch(error){
    renderCameraPtzStatus(error.payload?.ptz||{state:"limited",message:error.message});
  }finally{
    panel?.classList.remove("working");
  }
}

const WORKSPACE_READINESS={
  collection:{path:"/api/collection",label:"Collection & inventory",describe:payload=>`${Number(payload?.summary?.total_cards||payload?.total_cards||0).toLocaleString()} cards indexed`},
  broadcast:{path:"/api/production/preflight",label:"Production tools",describe:payload=>payload?.preflight?.ready?"Preflight ready":`${payload?.preflight?.blockers?.length||0} preflight item(s) need attention`,state:payload=>payload?.preflight?.ready?"ready":"setup"},
  creator:{path:"/api/creator/reveal-sequence",label:"Creator tools",describe:payload=>payload?.state?.enabled===false?"Reveal engine disabled":"Reveal engine ready"},
  soundboard:{path:"/api/soundboard",label:"Soundboard",describe:payload=>`${payload?.pads?.length||0} of 50 pads configured`},
  spotify:{path:"/api/spotify/status",label:"Spotify DJ",describe:payload=>payload?.connected?"Connected and ready":"Connect Spotify to enable playback",state:payload=>payload?.connected?"ready":"setup"},
  "ai-lab":{path:"/api/system/health",label:"AI Lab",describe:()=>"Diagnostics service online"},
  library:{path:"/api/master-builder/status",label:"Reference library",describe:payload=>`${payload?.builder?.sets_completed||0} of ${payload?.builder?.sets_discovered||0} sets synced`,state:payload=>payload?.builder?.busy?"working":"ready"},
  settings:{path:"/api/system/health",label:"System settings",describe:()=>"RareIQ services online"}
};

const BROADCAST_WORKSPACE_PANELS={
  live:[".workspace-readiness",".production-session-metadata",".production-session",".operator-health",".show-preflight",".production-switcher-shell"],
  destinations:[".broadcast-destinations"],
  show:[".rundown-safety",".rundown-library",".rundown-preflight",".production-rundown",".production-scenes"],
  graphics:[".production-graphics",".production-replay",".production-screens"],
  insights:[".pack-economics",".pack-tracker",".card-show-analytics",".show-analytics"],
  history:[".break-history-controls",".break-history",".production-report-actions"],
  setup:[".obs-diagnostic",".obs-bootstrap",".obs-control",".encoder-guide",".recording-settings"],
};

function setBroadcastWorkspaceView(requested,{persist=true,focus=false,scroll=true}={}){
  const workspace=document.querySelector('.workspace[data-workspace="broadcast"]');
  if(!workspace)return "live";
  const views=Object.keys(BROADCAST_WORKSPACE_PANELS);
  const view=views.includes(requested)?requested:"live";
  workspace.dataset.broadcastView=view;
  workspace.querySelectorAll("[data-broadcast-panel]").forEach(panel=>{panel.hidden=panel.dataset.broadcastPanel!==view});
  workspace.querySelectorAll("[data-broadcast-view]").forEach(button=>{
    const selected=button.dataset.broadcastView===view;
    button.setAttribute("aria-selected",selected?"true":"false");
    button.tabIndex=selected?0:-1;
    if(selected&&focus)button.focus();
  });
  if(scroll)workspace.scrollTo({top:0,behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
  if(persist){try{localStorage.setItem(BROADCAST_WORKSPACE_VIEW_KEY,view)}catch(_error){}}
  return view;
}

function initializeBroadcastWorkspace(){
  const workspace=document.querySelector('.workspace[data-workspace="broadcast"]');
  const tabs=$("broadcastWorkspaceTabs");
  if(!workspace||!tabs)return;
  Object.entries(BROADCAST_WORKSPACE_PANELS).forEach(([view,selectors])=>selectors.forEach(selector=>{
    const panel=workspace.querySelector(selector);
    if(panel)panel.dataset.broadcastPanel=view;
  }));
  tabs.querySelectorAll("[data-broadcast-view]").forEach(button=>{
    button.addEventListener("click",()=>setBroadcastWorkspaceView(button.dataset.broadcastView));
    button.addEventListener("keydown",event=>{
      const buttons=[...tabs.querySelectorAll("[data-broadcast-view]")];
      const current=buttons.indexOf(button);
      const key=event.key;
      if(!["ArrowLeft","ArrowRight","Home","End"].includes(key))return;
      event.preventDefault();
      const next=key==="Home"?0:key==="End"?buttons.length-1:(current+(key==="ArrowRight"?1:-1)+buttons.length)%buttons.length;
      setBroadcastWorkspaceView(buttons[next].dataset.broadcastView,{focus:true});
    });
  });
  let saved="live";
  try{saved=localStorage.getItem(BROADCAST_WORKSPACE_VIEW_KEY)||"live"}catch(_error){}
  setBroadcastWorkspaceView(saved,{persist:false,scroll:false});
}

function readinessPanel(workspace){
  let panel=workspace?.querySelector(":scope > .workspace-readiness");
  if(panel||!workspace)return panel;
  panel=document.createElement("aside");
  panel.className="workspace-readiness";
  panel.dataset.state="checking";
  panel.setAttribute("role","status");
  panel.setAttribute("aria-live","polite");
  panel.innerHTML='<i aria-hidden="true"></i><div><strong>Checking tools</strong><span>Confirming workspace services…</span></div><button type="button">Retry</button>';
  panel.querySelector("button").addEventListener("click",()=>refreshWorkspaceReadiness(workspace.dataset.workspace,true));
  workspace.prepend(panel);
  return panel;
}

function setWorkspaceReadiness(name,state,title,detail,latency=0){
  const workspace=document.querySelector(`.workspace[data-workspace="${CSS.escape(name)}"]`),panel=readinessPanel(workspace),nav=document.querySelector(`.nav-button[data-target="${CSS.escape(name)}"]`);
  if(!panel)return;
  panel.dataset.state=state;
  panel.querySelector("strong").textContent=title;
  panel.querySelector("span").textContent=`${detail}${latency?` · ${latency} ms`:""}`;
  panel.querySelector("button").hidden=!["error","setup"].includes(state);
  window.clearTimeout(panel._collapseTimer);
  panel.hidden=false;
  if(state==="ready")panel._collapseTimer=window.setTimeout(()=>{panel.hidden=true},2200);
  if(nav){nav.dataset.toolState=state;nav.title=`${nav.getAttribute("aria-label")||name}: ${detail}`}
}

async function refreshWorkspaceReadiness(name,announce=false){
  const started=performance.now(),definition=WORKSPACE_READINESS[name];
  if(name==="voice-mod"){
    const supported=Boolean(navigator.mediaDevices?.getUserMedia&&(window.AudioContext||window.webkitAudioContext));
    setWorkspaceReadiness(name,supported?"ready":"error","Voice Mod",supported?"Microphone processing supported":"Audio capture is unavailable in this browser");
    return supported;
  }
  if(name==="camera-fx"){
    const supported=Boolean(document.createElement("canvas").getContext?.("2d")&&window.requestAnimationFrame);
    setWorkspaceReadiness(name,supported?"ready":"error","Camera Effects",supported?"Effects engine ready; recognition remains clean":"Canvas effects are unavailable in this browser");
    return supported;
  }
  if(!definition)return true;
  setWorkspaceReadiness(name,"checking",definition.label,"Checking service…");
  try{
    const payload=await api(definition.path,{timeoutMs:name==="collection"?25000:8000,retries:0});
    const state=definition.state?.(payload)||"ready",detail=definition.describe?.(payload)||"Ready";
    setWorkspaceReadiness(name,state,definition.label,detail,Math.round(performance.now()-started));
    if(announce)notify(`${definition.label} Checked`,detail,state==="error"?"error":"success");
    return state!=="error";
  }catch(error){
    setWorkspaceReadiness(name,"error",definition.label,error.message||"Service unavailable");
    if(announce)notify(`${definition.label} Unavailable`,error.message||String(error),"error");
    return false;
  }
}

function initializeWorkspaceReadiness(){
  document.querySelectorAll('.workspace[data-workspace]').forEach(workspace=>{
    const name=workspace.dataset.workspace;
    if(WORKSPACE_READINESS[name]||name==="voice-mod"||name==="camera-fx")readinessPanel(workspace);
  });
}





function markViewerLive(){
  viewerBridgeConnected=true;
  cameraAutoStartDone=true;
  setCameraAutostartState("live","CAMERA LIVE");
  cameraAutostartComplete=true;
  cameraStreamStarted=true;
  cameraStreamFailures=0;

  clearTimeout(viewerBridgeTimer);
  clearTimeout(cameraStreamRetryTimer);

  const recovery=$("cameraRecovery");
  const placeholder=$("cameraPlaceholder");
  const workspace=document.querySelector(".camera-workspace");

  if(recovery){
    recovery.classList.remove("visible","success","error");
    recovery.classList.add("suppressed");
  }

  if(placeholder){
    placeholder.classList.add("hidden");
  }

  if(workspace){
    workspace.classList.add("viewer-live");
  }

  setViewerBridgeState("live","LIVE VIEWER");
}

function markViewerOffline(){
  viewerBridgeConnected=false;
  cameraStreamStarted=false;

  const recovery=$("cameraRecovery");
  const workspace=document.querySelector(".camera-workspace");

  if(workspace){
    workspace.classList.remove("viewer-live");
  }

  if(recovery){
    recovery.classList.remove("suppressed");
  }
}


let backgroundInitializationStarted=false;
let cameraAutoStartTimer=null;
let cameraAutoStartAttempts=0;
let cameraAutoStartInFlight=false;
let cameraAutoStartDone=false;
let operatorToastTimer=null;


function setCameraAutostartState(state,label){
  const chip=$("cameraAutostartChip");
  const text=$("cameraAutostartLabel");
  if(!chip||!text) return;

  chip.classList.remove("searching","starting","live","error");
  chip.classList.add(state);
  text.textContent=label;
}

function showOperatorToast(message,state="success"){
  const toast=$("operatorToast");
  if(!toast) return;

  clearTimeout(operatorToastTimer);
  toast.classList.remove("success","error");
  toast.classList.add(state,"visible");
  toast.textContent=message;

  operatorToastTimer=setTimeout(()=>{
    toast.classList.remove("visible");
  },2400);
}

function viewerHasLiveFrame(){
  const feed=$("cameraFeed");
  return Boolean(feed&&feed.naturalWidth>0&&feed.naturalHeight>0);
}

async function attemptCameraAutostart(){
  if(cameraAutoStartDone||cameraAutoStartInFlight) return;

  if(viewerHasLiveFrame()){
    cameraAutoStartDone=true;
    setCameraAutostartState("live","CAMERA LIVE");
    markViewerLive();
    return;
  }

  cameraAutoStartInFlight=true;
  cameraAutoStartAttempts+=1;
  setCameraAutostartState(
    cameraAutoStartAttempts===1?"searching":"starting",
    cameraAutoStartAttempts===1?"FINDING CAMERA":`STARTING ${cameraAutoStartAttempts}/12`
  );

  try{
    const result=await api("/api/cameras?force=true");
    const cameras=result.cameras||[];

    if(!cameras.length){
      throw new Error("No cameras detected yet.");
    }

    const select=$("cameraSelect");
    if(select){
      const saved=localStorage.getItem("rareiq.selectedCamera");
      if(saved&&[...select.options].some(option=>option.value===saved)){
        select.value=saved;
      }
    }

    const camera=readSelectedCamera();
    if(!camera) throw new Error("Select a camera source.");

    const startResult=await api("/api/camera/start",{
      method:"POST",
      body:JSON.stringify({
        camera_index:Number(camera.index),
        camera_backend:Number(camera.backend)
      })
    });

    if(startResult?.ok===false){
      throw new Error(
        startResult?.manager?.last_error ||
        startResult?.manager?.message ||
        "Camera start failed."
      );
    }

    connectMainViewer(true);

    await delay(650);

    if(viewerHasLiveFrame()){
      cameraAutoStartDone=true;
      setCameraAutostartState("live","CAMERA LIVE");
      markViewerLive();
      showOperatorToast(`${camera.name||"Camera"} started automatically.`);
      return;
    }

    throw new Error("Waiting for first frame.");
  }catch(error){
    if(cameraAutoStartAttempts>=12){
      setCameraAutostartState("error","MANUAL START");
      showOperatorToast(
        "Camera did not auto-start. Manual Start remains available.",
        "error"
      );
      return;
    }

    clearTimeout(cameraAutoStartTimer);
    cameraAutoStartTimer=setTimeout(
      attemptCameraAutostart,
      cameraAutoStartAttempts<4?700:1400
    );
  }finally{
    cameraAutoStartInFlight=false;
  }
}

async function restartFeed(){
  const camera=readSelectedCamera();
  if(!camera){
    setCameraStatus("SELECT A CAMERA","var(--gold)");
    updateActiveCameraName(null,"select");
    showOperatorToast("Select a camera before restarting it.","error");
    return;
  }
  cameraAutoStartDone=false;
  cameraAutoStartAttempts=0;
  cameraAutoStartInFlight=false;

  setCameraAutostartState("starting","RESTARTING FEED");
  markViewerOffline();

  try{
    await api("/api/camera/stop",{
      method:"POST",
      body:"{}"
    });
  }catch{}

  await delay(300);

  connectMainViewer(true);
  await ensureCameraStarted(true);
}

async function startBackgroundInitialization(){
  if(backgroundInitializationStarted) return;
  backgroundInitializationStarted=true;

  /*
  Restore the proven camera startup sequence from Studio X 6.0.3:
  1. Bootstrap the saved camera.
  2. Attach the main viewer immediately.
  3. Let First Frame Wins suppress stale loading overlays.
  */
  try{
    bootstrapCamera();
  }catch{}

  try{
    verifyAndConnectMainViewer();
  }catch{}

  setTimeout(attemptCameraAutostart,180);

  try{ loadRecognition(); }catch{}
  try{ loadSystemHealth(); }catch{}
  try{ loadCameraManagerState(); }catch{}

  setInterval(()=>{if(document.hidden!==true)loadCameraStatus({forceStream:false})},1800);
  setInterval(()=>{if(document.hidden!==true)loadSystemHealth()},5000);
  setInterval(()=>{if(document.hidden!==true)loadCameraManagerState()},1800);
}

function setViewerBridgeState(state,label){
  const node=$("viewerBridgeState");
  const text=$("viewerBridgeLabel");
  if(!node||!text) return;
  node.classList.remove("connecting","live","error");
  node.classList.add(state);
  text.textContent=label;
}

function connectMainViewer(force=false){
  const feed=$("cameraFeed");
  if(!feed) return;
  if(viewerBridgeConnected&&!force&&feed.naturalWidth>0) return;

  clearTimeout(viewerBridgeTimer);
  viewerBridgeGeneration+=1;
  viewerBridgeConnected=false;
  setViewerBridgeState("connecting","CONNECTING VIEWER");

  feed.removeAttribute("src");
  feed.src=`/api/camera/stream?viewer=main&ts=${Date.now()}&generation=${viewerBridgeGeneration}`;

  if(feed.naturalWidth>0&&feed.naturalHeight>0){
    markViewerLive();
    return;
  }

  viewerBridgeTimer=setTimeout(()=>{
    if(!(feed.naturalWidth>0&&feed.naturalHeight>0)){
      setViewerBridgeState("connecting","RETRYING VIEWER");
      connectMainViewer(true);
    }
  },1800);
}

async function verifyAndConnectMainViewer(){
  try{
    const result=await api("/api/cameras?force=false");
    if((result.cameras||[]).length){
      connectMainViewer(true);
      return true;
    }
    setViewerBridgeState("error","NO CAMERA FOUND");
    return false;
  }catch{
    setViewerBridgeState("error","VIEWER API ERROR");
    return false;
  }
}


function enterStudio(reason="ready"){
  return reason;
}

function scheduleAutomaticStudioEntry(){
  return;
}

function renderBootStatus(status){
  return status;
}

function enterStudioDegraded(){
  return;
}

async function runBootSequence(force=false){
  // Compatibility shim. Studio no longer waits on boot diagnostics.
  startBackgroundInitialization();
}

function delay(ms){
  return new Promise(resolve=>setTimeout(resolve,ms));
}

function setCameraRecovery(title,detail,state=""){
  const recovery=$("cameraRecovery");
  const feed=$("cameraFeed");
  if(!recovery) return;

  if(
    viewerBridgeConnected ||
    (feed && feed.naturalWidth>0 && feed.naturalHeight>0)
  ){
    markViewerLive();
    return;
  }

  recovery.classList.remove("success","error");
  if(state) recovery.classList.add(state);
  recovery.classList.add("visible");

  if($("cameraRecoveryTitle")) $("cameraRecoveryTitle").textContent=title;
  if($("cameraRecoveryDetail")) $("cameraRecoveryDetail").textContent=detail;
}

function hideCameraRecovery(delayMs=0){
  const recovery=$("cameraRecovery");
  if(!recovery) return;

  setTimeout(()=>{
    recovery.classList.remove("visible","success","error");
  },delayMs);
}

function cameraStatusOnline(status){
  const manager=status?.manager||{};
  const vision=status?.vision||status||{};
  return Boolean(
    manager.state==="running" &&
    manager.worker_alive===true &&
    manager.frame_fresh===true &&
    manager.stalled!==true &&
    vision.running===true &&
    !manager.last_error &&
    !vision.error
  );
}

async function waitForCameraReady(timeoutMs=15000){
  const started=Date.now();

  while(Date.now()-started<timeoutMs){
    try{
      const ready=await api("/api/camera/ready");
      if(ready.ok&&ready.frame_fresh&&ready.worker_alive){
        return ready;
      }
      setCameraRecovery(
        "Camera starting...",
        ready.message||"Waiting for the first frame."
      );
    }catch{}

    await delay(300);
  }

  return null;
}

async function ensureCameraStarted(force=false){
  if(cameraStartInFlight) return false;
  if(cameraAutostartComplete&&!force) return true;

  const camera=readSelectedCamera();
  if(!camera) return false;

  cameraStartInFlight=true;

  try{
    setCameraRecovery(
      "Starting camera...",
      camera.name||"Opening the selected video device."
    );

    const result=await api("/api/camera/start",{
      method:"POST",
      body:JSON.stringify({
        camera_index:Number(camera.index),
        camera_backend:Number(camera.backend)
      })
    });

    if(result?.ok===false){
      throw new Error(
        result?.manager?.last_error ||
        result?.manager?.message ||
        "Camera failed to start."
      );
    }

    if(result?.already_running){
      cameraAutostartComplete=true;
    }
    cameraStreamFailures=0;
    cameraStreamStarted=false;
    startCameraStream(true);

    const ready=await waitForCameraReady();

    if(ready){
      cameraAutostartComplete=true;
      cameraConnectionAvailable=true;
      cameraConnectionFailure=null;
      setCameraActionAvailability(true);
      updateActiveCameraName(camera,"active");
      setCameraRecovery(
        "Camera online",
        ready.message||camera.name||"Live preview connected.",
        "success"
      );
      hideCameraRecovery(650);
      return true;
    }

    throw new Error("The camera manager did not receive a live frame.");
  }catch(error){
    cameraAutostartComplete=false;
    setCameraDisconnectedPresentation(camera,error?.message||`Could not open ${camera.name||"selected camera"}`);
    return false;
  }finally{
    cameraStartInFlight=false;
  }
}

function scheduleCameraDiscovery(){
  clearTimeout(cameraDiscoveryTimer);

  cameraDiscoveryTimer=setTimeout(async()=>{
    if(cameraAutostartComplete) return;

    const cameras=await loadCameraList({
      retries:1,
      delay:450,
      silent:true
    });

    if(cameras.length){
      const camera=readSelectedCamera();
      if(camera) await ensureCameraStarted();
      else return;
    }

    if(!cameraAutostartComplete){
      scheduleCameraDiscovery();
    }
  },1600);
}

async function loadCameraList(options={}){
  const {retries=5,delay=650,silent=false}=options;
  const force=options.force??!silent;
  const select=$("cameraSelect");
  if(!silent) select.innerHTML=`<option value="">Scanning cameras...</option>`;

  for(let attempt=0;attempt<=retries;attempt+=1){
    try{
      const result=await api(`/api/cameras?force=${force?"true":"false"}`);
      const cameras=sortCameraDevices(result.cameras||[]);
      if(cameras.length){
        const saved=localStorage.getItem("rareiq.selectedCamera");
        const savedCamera=decodeCameraValue(saved);
        const savedVirtual=isVirtualCamera(savedCamera);
        const prompt=savedVirtual
          ?"Saved virtual camera requires confirmation"
          :saved
          ?"Saved camera unavailable -- select a camera"
          :"Select a camera";
        select.replaceChildren();
        const promptOption=document.createElement("option");
        promptOption.value="";
        promptOption.textContent=prompt;
        select.appendChild(promptOption);
        appendCameraGroup(select,"Physical Cameras",cameras.filter(camera=>!isVirtualCamera(camera)));
        appendCameraGroup(select,"Virtual Cameras",cameras.filter(isVirtualCamera));
        const savedMatch=saved&&[...select.options].find(option=>{
          if(option.value===saved) return true;
          const candidate=decodeCameraValue(option.value);
          return candidate&&savedCamera&&
            Number(candidate.index)===Number(savedCamera.index)&&
            Number(candidate.backend)===Number(savedCamera.backend);
        });
        const savedAvailable=Boolean(savedMatch);
        if(savedAvailable&&!savedVirtual){
          select.value=savedMatch.value;
          localStorage.setItem("rareiq.selectedCamera",savedMatch.value);
          readSelectedCamera();
          updateActiveCameraName(selectedCamera,"selected");
        }else{
          select.value="";
          selectedCamera=null;
          updateActiveCameraName(savedVirtual?savedCamera:null,savedVirtual?"virtual":"select");
        }
        syncSecondarySourceOptions(cameras);
        syncCameraWorkspaceSourceOptions();
        renderCameraWorkspace();
        await refreshCameraSlotState();
        return cameras;
      }
    }catch{}

    if(attempt<retries){
      select.innerHTML=`<option value="">Camera scan retry ${attempt+1}/${retries}...</option>`;
      await new Promise(resolve=>setTimeout(resolve,delay));
    }
  }

  select.innerHTML=`<option value="">No cameras detected</option>`;
  selectedCamera=null;
  updateActiveCameraName(null,"none");
  syncSecondarySourceOptions([]);
  syncCameraWorkspaceSourceOptions();
  renderCameraWorkspace();
  return [];
}

let studioXRecognitionMode="single";
let multiCardPollTimer=null;
const STUDIOX_RECOGNITION_MODE_KEY="rareiq.studiox.recognition-mode";
const STUDIOX_UNIQUE_VARIANTS_KEY="rareiq.studiox.unique-variants";
const STUDIOX_MULTI_CARD_COUNT_KEY="rareiq.studiox.multi-card-count";
const STUDIOX_SET_MODE_KEY="rareiq.studiox.set-mode";
const STUDIOX_SET_CHOICE_KEY="rareiq.studiox.set-choice";
const STUDIOX_PACK_SESSION_KEY="rareiq.studiox.pack-session";
const STUDIOX_PACK_AUTO_DETECT_KEY="rareiq.studiox.pack-auto-detect";
const STUDIOX_PACK_AUTO_ADVANCE_KEY="rareiq.studiox.pack-auto-advance";
const STUDIOX_PACK_AUTO_NEXT_KEY="rareiq.studiox.pack-auto-next";
const STUDIOX_PACK_PROFILES_KEY="rareiq.studiox.pack-profiles";
const STUDIOX_WORKFLOW_SESSION_KEY="rareiq.studiox.workflow-chosen";
let recognitionSetOptions=[];
let packArtworkIndex={reference_count:0,references:[]};
let packAutoDetectTimer=null,packAutoDetectInFlight=false,packAutoLocked=false,packAutoAdvancePending=false,packAutoNextPending=false;
function packAutoDetectEnabled(){try{return localStorage.getItem(STUDIOX_PACK_AUTO_DETECT_KEY)==="true"}catch(_error){return false}}
function packAutoAdvanceEnabled(){try{return localStorage.getItem(STUDIOX_PACK_AUTO_ADVANCE_KEY)!=="false"}catch(_error){return true}}
function packAutoNextEnabled(){try{return localStorage.getItem(STUDIOX_PACK_AUTO_NEXT_KEY)!=="false"}catch(_error){return true}}
function packProfileKey(match={}){return String(match.id||[match.provider,match.language,match.set_id||match.set_name].filter(Boolean).join("|")||"default")}
function readPackProfiles(){try{return JSON.parse(localStorage.getItem(STUDIOX_PACK_PROFILES_KEY)||"{}")||{}}catch(_error){return {}}}
function packProfileFor(match=packArtworkIndex.last_match||{}){const local=readPackProfiles()[packProfileKey(match)]||{},remote=match.pack_profile||{},expectedCards=Math.max(1,Math.min(30,Number(remote.expected_cards)||Number(local.expectedCards)||10)),rareSlot=Math.max(1,Math.min(expectedCards,Number(remote.rare_slot)||Number(local.rareSlot)||expectedCards));return{expectedCards,rareSlot}}
function applyPackProfile(match=packArtworkIndex.last_match||{}){const profile=packProfileFor(match),cards=$("packExpectedCards"),rare=$("packRareSlot");if(cards)cards.value=String(profile.expectedCards);if(rare){[...rare.options].forEach(option=>option.disabled=Number(option.value)>profile.expectedCards);rare.value=String(profile.rareSlot)}}
function renderPackProfileSuggestion(learning={}){const box=$("packProfileSuggestion"),suggestion=learning?.suggested_profile;if(!box)return;box.hidden=!suggestion;if(!suggestion)return;const confidence=Math.round(Number(learning.confidence||0)*100),count=Number(learning.observation_count||0);setCardText("packProfileSuggestionText",`Observed ${suggestion.expected_cards} cards · rare at ${suggestion.rare_slot} (${count} packs, ${confidence}% agreement)`);box.dataset.expectedCards=String(suggestion.expected_cards);box.dataset.rareSlot=String(suggestion.rare_slot)}
async function saveActivePackProfile(){const match=packArtworkIndex.last_match||{},expectedCards=Math.max(1,Number($("packExpectedCards")?.value)||10),rareSlot=Math.max(1,Math.min(expectedCards,Number($("packRareSlot")?.value)||expectedCards)),profiles=readPackProfiles();profiles[packProfileKey(match)]={expectedCards,rareSlot};try{localStorage.setItem(STUDIOX_PACK_PROFILES_KEY,JSON.stringify(profiles))}catch(_error){}match.pack_profile={expected_cards:expectedCards,rare_slot:rareSlot};applyPackProfile(match);if(match.id){try{await api("/api/recognition/pack-profile",{method:"POST",body:JSON.stringify({reference_id:match.id,expected_cards:expectedCards,rare_slot:rareSlot})})}catch(error){notify("Profile Saved Locally",`RareIQ could not sync this wrapper profile: ${error.message||error}`,"warning");return}}notify("Pack Profile Saved",`${expectedCards} cards · rare position ${rareSlot}`,"success")}
async function observeCompletedPack(session,revealState=null){if(!session?.active||!session.reference_id||session.profile_observed)return null;const sequence=Array.isArray(revealState?.sequence)?revealState.sequence:[],observedCards=Math.max(1,Math.min(30,Number(revealState?.position)||Number(session.last_confirmed_position)||1)),hit=sequence.find(item=>["low","medium","grail"].includes(String(item?.hit_tier||""))),rareSlot=Number(hit?.position)||Number(session.observed_rare_slot)||null;session.profile_observed=true;writePackSession(session);try{const payload=await api("/api/recognition/pack-profile/observe",{method:"POST",body:JSON.stringify({reference_id:session.reference_id,observed_cards:observedCards,rare_slot:rareSlot})});if(packArtworkIndex.last_match?.id===session.reference_id){packArtworkIndex.last_match.profile_learning=payload.profile_learning;renderPackProfileSuggestion(payload.profile_learning)}return payload}catch(error){session.profile_observed=false;writePackSession(session);console.warn("Pack profile observation failed",error);return null}}
function stopPackAutoDetect(){if(packAutoDetectTimer){clearTimeout(packAutoDetectTimer);packAutoDetectTimer=null}}
function schedulePackAutoDetect(delay=350){stopPackAutoDetect();if(!packAutoDetectEnabled()||$("setContextMode")?.value!=="pack"||packAutoLocked||!Number(packArtworkIndex.reference_count||0))return;packAutoDetectTimer=setTimeout(runPackAutoDetect,delay)}
async function runPackAutoDetect(){packAutoDetectTimer=null;if(packAutoDetectInFlight||!packAutoDetectEnabled()||$("setContextMode")?.value!=="pack"||packAutoLocked)return;packAutoDetectInFlight=true;try{const matched=await scanPackSet(true);if(!matched)schedulePackAutoDetect(1200)}finally{packAutoDetectInFlight=false}}

async function loadTCGGames(){
  const payload=await api("/api/tcg/games");
  const select=$("tcgGameSelect");
  if(!select)return payload;
  const games=Array.isArray(payload.games)?payload.games.filter(game=>game.enabled!==false):[];
  const selection=payload.selection||{};
  const resolved=games.find(game=>game.game_id===selection.resolved_game_id);
  select.replaceChildren(new Option(`Auto · ${resolved?.name||"Pokémon"}`,"auto"));
  games.forEach(game=>select.append(new Option(game.name,game.game_id)));
  select.value=selection.mode==="manual"&&games.some(game=>game.game_id===selection.game_id)
    ? selection.game_id
    : "auto";
  document.body.dataset.tcgGame=selection.resolved_game_id||payload.default_game_id||"pokemon";
  return payload;
}

async function updateTCGSelection(){
  const select=$("tcgGameSelect");
  if(!select)return;
  const gameId=select.value;
  select.disabled=true;
  try{
    const payload=await api("/api/tcg/selection",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({mode:gameId==="auto"?"auto":"manual",game_id:gameId==="auto"?null:gameId})
    });
    document.body.dataset.tcgGame=payload.selection?.resolved_game_id||"pokemon";
    await loadTCGGames();
    await loadRecognitionSets();
    notify("Game Selection Updated",gameId==="auto"?"RareIQ will detect the trading card game automatically.":`${select.options[select.selectedIndex]?.text||gameId} locked for recognition.`,"success");
  }catch(error){
    await loadTCGGames().catch(()=>{});
    notify("Game Selection Failed",error.message||String(error),"error");
  }finally{
    select.disabled=false;
  }
}

function readPackSession(){try{return JSON.parse(localStorage.getItem(STUDIOX_PACK_SESSION_KEY)||"null")}catch{return null}}
function writePackSession(session){try{session?localStorage.setItem(STUDIOX_PACK_SESSION_KEY,JSON.stringify(session)):localStorage.removeItem(STUDIOX_PACK_SESSION_KEY)}catch{}}
function renderPackSession(){
  const session=readPackSession(),active=Boolean(session?.active);
  document.body.dataset.packSession=active?"active":"";
  if($("nextPackSessionButton")) $("nextPackSessionButton").hidden=!active;
  if(!active)return;
  const card=Math.max(1,Math.min(Number(session.card||1),Number(session.size||10)));
  const complete=Boolean(session.complete);
  if($("setContextStatus")) $("setContextStatus").textContent=complete
    ? `${session.set_name} · PACK COMPLETE · ${session.size}/${session.size}`
    : `${session.set_name} · ${session.language||"Any language"} · CARD ${card}/${session.size}`;
  if($("nextPackSessionButton")) $("nextPackSessionButton").textContent=complete?"Scan Next Pack":"Next Pack";
}
function advancePackSessionCard(revealState=null){
  const session=readPackSession();if(!session?.active)return;
  const wasComplete=Boolean(session.complete);
  const size=Math.max(1,Number(session.size||10)),card=Math.max(1,Number(session.card||1));
  const confirmedPosition=Number(revealState?.position||0);
  if(confirmedPosition>0)session.last_confirmed_position=confirmedPosition;
  const sequence=Array.isArray(revealState?.sequence)?revealState.sequence:[],observedHit=sequence.find(item=>["low","medium","grail"].includes(String(item?.hit_tier||"")));
  if(observedHit?.position)session.observed_rare_slot=Number(observedHit.position);
  if(confirmedPosition>=size)session.complete=true;
  else session.card=Math.max(card+1,confirmedPosition+1);
  if(revealState?.pack_number)session.pack_number=Number(revealState.pack_number);
  writePackSession(session);renderPackSession();
  if(session.complete&&!wasComplete){observeCompletedPack(session,revealState);if(packAutoNextEnabled()&&!packAutoNextPending){packAutoNextPending=true;notify("Pack Complete","Returning to wrapper detection for the next pack.","success");setTimeout(()=>startNextPackSession().catch(error=>notify("Next Pack Not Armed",error.message||String(error),"error")).finally(()=>{packAutoNextPending=false}),650)}}
}
async function startNextPackSession(){
  const finishedSession=readPackSession();if(finishedSession?.active&&!finishedSession.profile_observed)await observeCompletedPack(finishedSession).catch(()=>{});
  if(activeInventoryAllocationGroup)await lockInventoryAllocation(activeInventoryAllocationGroup).catch(()=>{});
  writePackSession(null);delete document.body.dataset.packSession;
  if($("nextPackSessionButton")) $("nextPackSessionButton").hidden=true;
  if($("setContextMode")) $("setContextMode").value="pack";
  try{localStorage.setItem(STUDIOX_SET_MODE_KEY,"pack");}catch(_error){}
  try{await requestNextRecognition();}catch(_error){}
  renderRecognitionSetContext({selection_mode:"pack",locked:false});
  renderPackArtworkReadiness();
  notify("Ready for Next Pack","Place the wrapper in view and press Scan Pack.","success");
}

function selectedRecognitionSet(){
  const value=$("setContextSelect")?.value||"";
  return recognitionSetOptions.find(item=>`${item.provider||""}|${item.language||""}|${item.set_id||item.id||""}`===value)||null;
}

function renderRecognitionSetOptions(query=""){
  const select=$("setContextSelect");if(!select)return;
  const selected=select.value,needle=String(query||"").trim().toLowerCase();
  const filtered=recognitionSetOptions.filter(item=>!needle||[item.set_name,item.name,item.set_id,item.id,item.language,item.provider].some(value=>String(value||"").toLowerCase().includes(needle)));
  select.replaceChildren(Object.assign(document.createElement("option"),{value:"",textContent:needle?`${filtered.length} matching sets…`:`Choose set…`}));
  filtered.forEach(item=>{const option=document.createElement("option");option.value=`${item.provider||""}|${item.language||""}|${item.set_id||item.id||""}`;option.textContent=`${item.set_name||item.name||item.set_id} · ${item.language||"Any"}${item.references_ready===false?" · downloading":""}`;select.append(option)});
  if([...select.options].some(option=>option.value===selected))select.value=selected;
}

async function chooseRecognitionWorkflow(workflow="identify"){
  const pack=workflow==="pack";try{sessionStorage.setItem(STUDIOX_WORKFLOW_SESSION_KEY,pack?"pack":"identify");localStorage.setItem(STUDIOX_PACK_AUTO_DETECT_KEY,pack?"true":"false")}catch(_error){}
  if($("setContextMode"))$("setContextMode").value=pack?"pack":"auto";
  if($("recognitionWorkflowPrompt"))$("recognitionWorkflowPrompt").hidden=true;
  await updateRecognitionSetContext();
  notify(pack?"Pack Scan Armed":"Card Identify Ready",pack?"Place a wrapper in view. Pack artwork detection is now active.":"RareIQ will identify single cards across all downloaded sets. Pack detection is off.","success");
}

async function initializeRecognitionWorkflow(){
  let choice="";try{choice=sessionStorage.getItem(STUDIOX_WORKFLOW_SESSION_KEY)||""}catch(_error){}
  if(choice)return;
  try{localStorage.setItem(STUDIOX_SET_MODE_KEY,"auto");localStorage.setItem(STUDIOX_PACK_AUTO_DETECT_KEY,"false")}catch(_error){}
  if($("setContextMode"))$("setContextMode").value="auto";
  await updateRecognitionSetContext().catch(()=>{});
  if($("recognitionWorkflowPrompt"))$("recognitionWorkflowPrompt").hidden=false;
}

function renderRecognitionSetContext(status={}){
  const mode=status.selection_mode||"auto";
  const active=status.active_set||{};
  if($("setContextMode")) $("setContextMode").value=mode;
  if($("setContextSelect")) $("setContextSelect").hidden=mode==="auto";
  if($("setContextSearch")) $("setContextSearch").hidden=mode==="auto";
  if($("scanPackSetButton")) $("scanPackSetButton").hidden=mode!=="pack";
  if($("learnPackSetButton")) $("learnPackSetButton").hidden=mode!=="pack";
  if($("setContextStatus")) $("setContextStatus").textContent=status.locked
    ? `${active.name||active.set_id||"Set locked"} · ${active.language||"Any language"}`
    : "All downloaded sets";
  document.body.dataset.setContext=mode;
  renderRecognitionWorkflowChrome(mode);
  packAutoLocked=Boolean(mode==="pack"&&status.locked);
  renderPackRecognition(mode==="pack"?packArtworkIndex.last_match:null,Boolean(status.locked));
  if(mode==="pack"&&!status.locked)schedulePackAutoDetect();else stopPackAutoDetect();
}

function renderRecognitionWorkflowChrome(mode=$("setContextMode")?.value||"auto"){
  const pack=mode==="pack",stats=$("packSpeedRun"),control=document.querySelector(".auto-add-verified-control"),title=control?.querySelector("b"),detail=control?.querySelector("small");
  if(!pack&&packRearmGate.active)clearNextPackGate();
  if(stats)stats.hidden=!pack;
  if(control){control.dataset.workflow=pack?"pack":"identify";control.title=pack?"Automatically add verified pack cards and rearm after removal":"Automatically clear the verified card after removal and identify the next single card"}
  if(title)title.textContent=pack?"Pack Speed":"Auto Next";
  if(detail)detail.textContent=pack?"Auto-add + clear":"Remove card to continue";
  renderPackSpeedAutomationState(window.__rareiqCardContext||{});
}

function selectedPackReferenceCount(){
  const selected=selectedRecognitionSet();
  if(!selected) return 0;
  const wantedId=String(selected.set_id||selected.id||"").toLowerCase();
  const wantedName=String(selected.set_name||selected.name||"").toLowerCase();
  const wantedLanguage=String(selected.language||"any").toLowerCase();
  return (packArtworkIndex.references||[]).filter(item=>{
    const sameSet=[item.set_id,item.set_name].map(value=>String(value||"").toLowerCase())
      .some(value=>value&&(value===wantedId||value===wantedName));
    const language=String(item.language||"any").toLowerCase();
    return sameSet&&(language==="any"||wantedLanguage==="any"||language===wantedLanguage);
  }).length;
}

function renderPackArtworkReadiness(){
  if(($("setContextMode")?.value||"auto")!=="pack") return;
  const selected=selectedRecognitionSet();
  const count=selectedPackReferenceCount();
  if($("learnPackSetButton")) $("learnPackSetButton").textContent=count?"Add Pack View":"Learn Pack";
  if($("scanPackSetButton")) $("scanPackSetButton").disabled=!packArtworkIndex.reference_count;
  if($("setContextStatus")) $("setContextStatus").textContent=!selected
    ? `${packArtworkIndex.reference_count||0} learned pack references · choose a set to teach`
    : count
      ? `${selected.set_name||selected.name} · ${count} learned view${count===1?"":"s"} · ready to scan`
      : `${selected.set_name||selected.name} · not learned yet`;
}

function renderPackRecognition(match=null,locked=false){
  const panel=$("packRecognitionPanel");
  if(!panel) return;
  const found=Boolean(match?.set_id||match?.set_name);
  panel.hidden=($("setContextMode")?.value||"auto")!=="pack";
  panel.dataset.state=found?"matched":"waiting";
  setCardText("packRecognitionTitle",found?"Pack Match Found":"Ready to identify a pack");
  setCardText("packRecognitionBadge",found?"SET MATCH":"WAITING");
  setCardText("packRecognitionSet",found?(match.set_name||match.set_id):"No pack scanned");
  setCardText("packRecognitionLanguage",found?(match.language||"Any"):"—");
  setCardText("packRecognitionSetId",found?(match.set_id||"—"):"—");
  setCardText("packRecognitionConfidence",found?`${Math.round(Number(match.score||0)*100)}%`:"0%");
  setCardText("packRecognitionLock",locked?"Locked for card OCR":"Not locked");
  setCardText("packRecognitionEvidence",found
    ? `Artwork ${Math.round(Number(match.hash_score||0)*100)}% · color ${Math.round(Number(match.color_score||0)*100)}%`
    : "Choose a set to learn its first wrapper, or scan a learned pack.");
  setCardText("packRecognitionConfirmation",found&&locked
    ? `${match.set_name||match.set_id} is now the active card-recognition set`
    : "Waiting for pack evidence");
  if($("packStartCardsButton")) $("packStartCardsButton").disabled=!(found&&locked);
  const image=$("packRecognitionImage"),placeholder=$("packRecognitionPlaceholder");
  if(image){image.hidden=!found;if(found)image.src=`/api/recognition/pack-reference/${encodeURIComponent(match.id)}?v=${Date.now()}`;}
  if(placeholder)placeholder.hidden=found;
  if(found)applyPackProfile(match);
  renderPackProfileSuggestion(found?match.profile_learning:{});
}

async function loadPackArtworkIndex(){
  try{ packArtworkIndex=await api("/api/recognition/pack-index"); }
  catch(_error){ packArtworkIndex={reference_count:0,references:[]}; }
  renderPackArtworkReadiness();
  renderPackRecognition(packArtworkIndex.last_match,Boolean(packArtworkIndex.last_match));
  if($("setContextMode")?.value==="pack"&&!packAutoLocked)schedulePackAutoDetect();
}

async function loadRecognitionSets(){
  try{
    const payload=await api("/api/sets");
    recognitionSetOptions=payload.sets||[];
    const select=$("setContextSelect");
    if(select)renderRecognitionSetOptions($("setContextSearch")?.value||"");
    renderRecognitionSetContext(payload.status||{});
    try{
      const authoritative=Boolean(payload.status?.locked);
      if(authoritative){
        const active=payload.status.active_set||{};
        const activeId=String(active.set_id||active.id||"");
        const activeLanguage=String(active.language||"").toLowerCase();
        const activeOption=[...select.options].find(option=>{
          const parts=option.value.split("|");
          return parts[2]===activeId&&(!activeLanguage||String(parts[1]||"").toLowerCase()===activeLanguage);
        });
        if(activeOption) select.value=activeOption.value;
        localStorage.setItem(STUDIOX_SET_MODE_KEY,payload.status.selection_mode||"auto");
        if(activeOption) localStorage.setItem(STUDIOX_SET_CHOICE_KEY,activeOption.value);
      }else{
        const savedMode=localStorage.getItem(STUDIOX_SET_MODE_KEY);
        const savedChoice=localStorage.getItem(STUDIOX_SET_CHOICE_KEY);
        const sessionWorkflow=sessionStorage.getItem(STUDIOX_WORKFLOW_SESSION_KEY)||"";
        if(savedMode&&["auto","manual"].includes(savedMode)) $("setContextMode").value=savedMode;
        if(savedMode==="pack"&&sessionWorkflow==="pack") $("setContextMode").value="pack";
        if(savedChoice&&[...select.options].some(option=>option.value===savedChoice)) select.value=savedChoice;
        if(savedMode==="pack"&&sessionWorkflow==="pack") renderRecognitionSetContext({selection_mode:"pack",locked:false});
      }
    }catch(_error){}
    await loadPackArtworkIndex();
    renderPackSession();
    await initializeRecognitionWorkflow();
  }catch(error){
    if($("setContextStatus")) $("setContextStatus").textContent="Set catalog unavailable";
  }
}

async function updateRecognitionSetContext(){
  const mode=$("setContextMode")?.value||"auto";
  writePackSession(null);delete document.body.dataset.packSession;
  if($("nextPackSessionButton")) $("nextPackSessionButton").hidden=true;
  try{
    localStorage.setItem(STUDIOX_SET_MODE_KEY,mode);
    localStorage.setItem(STUDIOX_SET_CHOICE_KEY,$("setContextSelect")?.value||"");
    localStorage.setItem(STUDIOX_PACK_AUTO_DETECT_KEY,mode==="pack"?"true":"false");
  }catch(_error){}
  if(mode==="pack"){
    renderRecognitionSetContext({selection_mode:"pack",locked:false});
    renderPackArtworkReadiness();
    return;
  }
  const selected=selectedRecognitionSet();
  if(mode==="manual"&&!selected){
    renderRecognitionSetContext({selection_mode:"manual",locked:false});
    return;
  }
  const payload=await api("/api/recognition/set-context",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({mode,set_id:selected?.set_id||selected?.id,set_name:selected?.set_name||selected?.name,language:selected?.language,provider:selected?.provider})
  });
  renderRecognitionSetContext(payload);
}

async function scanPackSet(silent=false){
  if(!silent&&$("setContextStatus")) $("setContextStatus").textContent="Reading pack artwork…";
  try{
    const payload=await api("/api/recognition/scan-pack",{method:"POST"});
    if(payload.pack_match) packArtworkIndex.last_match=payload.pack_match;
    packAutoLocked=Boolean(payload.locked);
    renderRecognitionSetContext(payload);
    renderPackRecognition(payload.pack_match,Boolean(payload.locked));
    if(silent&&payload.pack_match){notify("Pack Recognized",`${payload.pack_match.pack_label||payload.pack_match.set_name||"Learned wrapper"} activated automatically.`,"success");if(packAutoAdvanceEnabled()&&!packAutoAdvancePending){packAutoAdvancePending=true;setTimeout(()=>startCardsFromPack(true).finally(()=>{packAutoAdvancePending=false}),500)}}
    return Boolean(payload.pack_match&&payload.locked);
  }catch(error){
    if(!silent&&$("setContextStatus")) $("setContextStatus").textContent=error.message||"Pack not recognized";
    return false;
  }
}

async function startCardsFromPack(automatic=false){
  const match=packArtworkIndex.last_match;
  if(!(match?.set_id||match?.set_name)){
    notify("Pack Match Required","Scan and lock the pack before starting card recognition.","error");
    return;
  }
  const button=$("packStartCardsButton");
  if(button) button.disabled=true;
  try{
    const payload=await api("/api/recognition/set-context",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({mode:"manual",set_id:match.set_id,set_name:match.set_name,language:match.language,provider:match.provider})
    });
    const select=$("setContextSelect");
    if($("setContextMode")) $("setContextMode").value="manual";
    if(select){
      const option=[...select.options].find(item=>{
        const [provider,language,setId]=item.value.split("|");
        return setId===String(match.set_id||"")&&(!match.provider||provider===String(match.provider))&&(!match.language||language.toLowerCase()===String(match.language).toLowerCase());
      });
      if(option) select.value=option.value;
    }
    try{localStorage.setItem(STUDIOX_SET_MODE_KEY,"manual");localStorage.setItem(STUDIOX_SET_CHOICE_KEY,select?.value||"");}catch(_error){}
    renderRecognitionSetContext(payload);
    let rearmed=true;
    try{await requestNextRecognition();}catch(_clearError){rearmed=false;}
    let revealState=null;
    try{
      const profile=packProfileFor(match),revealPayload=await api("/api/creator/reveal-sequence",{method:"POST",body:JSON.stringify({expected_cards:profile.expectedCards,rare_slot:profile.rareSlot})});
      revealState=revealPayload.state||null;
      if(Number(revealState?.position||0)>0){
        const nextPayload=await api("/api/creator/reveal-sequence/next-pack",{method:"POST"});
        revealState=nextPayload.state||revealState;
      }
    }catch(_revealError){}
    writePackSession({active:true,reference_id:match.id||"",set_id:match.set_id,set_name:match.set_name||match.set_id,language:match.language||"Any language",size:Number(revealState?.expected_cards||10),card:Number(revealState?.position||0)+1,pack_number:Number(revealState?.pack_number||1),complete:false,profile_observed:false});
    renderPackSession();
    notify(
      rearmed?(automatic?"Card Scanning Started Automatically":"Pack Set Locked"):"Pack Set Locked · Clear Manually",
      rearmed
        ? `${match.set_name||match.set_id} only · wrapper evidence cleared · ready for card 1.`
        : `${match.set_name||match.set_id} only · press Next / Clear after removing the wrapper.`,
      rearmed?"success":"warning"
    );
  }catch(error){
    notify("Card Scanning Not Started",error.message||"Could not preserve the pack set lock.","error");
    if(button) button.disabled=false;
  }
}

async function learnPackSet(){
  const selected=selectedRecognitionSet();
  if(!selected){
    if($("setContextStatus")) $("setContextStatus").textContent="Choose the pack set first";
    return;
  }
  if($("setContextStatus")) $("setContextStatus").textContent="Learning pack artwork…";
  try{
    const payload=await api("/api/recognition/learn-pack",{
      method:"POST",body:JSON.stringify({mode:"pack",set_id:selected.set_id||selected.id,set_name:selected.set_name||selected.name,language:selected.language,provider:selected.provider})
    });
    packArtworkIndex=payload.status||packArtworkIndex;
    renderPackArtworkReadiness();
  }catch(error){
    if($("setContextStatus")) $("setContextStatus").textContent=error.message||"Pack learning failed";
  }
}

function captureRecognitionMode(){
  return studioXRecognitionMode==="six-card-grid"
    ? captureMultiCardGrid()
    : captureCamera();
}

function syncRecognitionModeWorkspace(){
  const isMulti=studioXRecognitionMode==="six-card-grid";
  document.body.dataset.recognitionMode=studioXRecognitionMode;
  const panel=$("multiCardPanel");
  if(panel) panel.hidden=!isMulti;

  // Responsive layouts re-parent inspector sections. Always clear stale mode
  // classes globally before applying the current mode to the live parent.
  document.querySelectorAll(".multi-card-suppressed").forEach(node=>node.classList.remove("multi-card-suppressed"));
  const currentView=document.querySelector(".ui4-current-card-view");
  const multiCardContainer=panel?.parentElement||currentView;
  if(isMulti&&multiCardContainer){
    [...multiCardContainer.children].forEach(node=>{
      if(node!==panel) node.classList.add("multi-card-suppressed");
    });
  }
  if($("recognitionModeSelect")) $("recognitionModeSelect").value=studioXRecognitionMode;
  if($("singleCardControl")) $("singleCardControl").hidden=studioXRecognitionMode!=="single";
  if(!isMulti){
    setUI4InspectorView("current",false);
    if(currentView) currentView.scrollTop=0;
    const inspector=document.querySelector(".inspector");
    if(inspector) inspector.scrollTop=0;
  }
}

function setRecognitionMode(mode){
  studioXRecognitionMode=mode==="six-card-grid"?"six-card-grid":"single";
  try{localStorage.setItem(STUDIOX_RECOGNITION_MODE_KEY,studioXRecognitionMode)}catch(_error){}
  syncRecognitionModeWorkspace();
  requestAnimationFrame(()=>syncRecognitionModeWorkspace());
  if(studioXRecognitionMode==="six-card-grid"){
    loadMultiCardStatus();
  }else{
    clearTimeout(multiCardPollTimer);
    renderMultiCardCameraOverlay([]);
  }
}

function multiCardName(card={}){
  return card.english_name||card.printed_name||card.name||"Candidate found";
}

function multiCardReferenceImage(card={}){
  const direct=card.reference_image_url||card.image_url||"";
  if(direct) return String(direct).replaceAll("\\","/");
  const local=card.image_path||card.reference_image||card.local_image||"";
  return local?`/api/reference-image?path=${encodeURIComponent(String(local))}`:"";
}

function renderMultiCardCameraOverlay(slots=[],selectedSlots=[],forceSinglePicker=false){
  const overlay=$("multiCardCameraOverlay");
  const stage=overlay?.parentElement;
  const image=$("cameraFeed");
  if(!overlay||!stage||!image) return;
  const width=stage.clientWidth||1;
  const height=stage.clientHeight||1;
  overlay.setAttribute("viewBox",`0 0 ${width} ${height}`);
  overlay.replaceChildren();
  if(studioXRecognitionMode!=="six-card-grid"&&!forceSinglePicker){overlay.hidden=true;return}
  const naturalWidth=image.naturalWidth||width;
  const naturalHeight=image.naturalHeight||height;
  const contain=getComputedStyle(image).objectFit==="contain";
  const scale=contain?Math.min(width/naturalWidth,height/naturalHeight):Math.max(width/naturalWidth,height/naturalHeight);
  const renderedWidth=naturalWidth*scale;
  const renderedHeight=naturalHeight*scale;
  const offsetX=(width-renderedWidth)/2;
  const offsetY=(height-renderedHeight)/2;
  const namespace="http://www.w3.org/2000/svg";
  const selected=new Set(selectedSlots.map(Number));
  slots.filter(item=>Array.isArray(item.polygon)&&item.polygon.length===4).forEach(item=>{
    const points=item.polygon.map(point=>[offsetX+Number(point[0])*renderedWidth,offsetY+Number(point[1])*renderedHeight]);
    const polygon=document.createElementNS(namespace,"polygon");
    polygon.setAttribute("points",points.map(point=>point.join(",")).join(" "));
    polygon.dataset.slot=String(item.slot);polygon.dataset.state=String(item.status||"detected");polygon.dataset.selected=String(selected.has(Number(item.slot)));overlay.appendChild(polygon);
    const center=points.reduce((total,point)=>[total[0]+point[0]/4,total[1]+point[1]/4],[0,0]);
    const badge=document.createElementNS(namespace,"circle");
    badge.setAttribute("cx",String(center[0]));badge.setAttribute("cy",String(center[1]));badge.setAttribute("r","18");badge.dataset.slot=String(item.slot);overlay.appendChild(badge);
    const label=document.createElementNS(namespace,"text");
    label.setAttribute("x",String(center[0]));label.setAttribute("y",String(center[1]+1));label.textContent=String(item.slot);label.dataset.slot=String(item.slot);overlay.appendChild(label);
  });
  overlay.hidden=overlay.childElementCount===0;
}

let singleCardPickerActive=false;

async function toggleSingleCardPicker(){
  singleCardPickerActive=!singleCardPickerActive;
  const button=$("singleCardPickerButton");
  if(button){
    button.setAttribute("aria-pressed",String(singleCardPickerActive));
    button.textContent=singleCardPickerActive?"Cancel Choice":"Choose Card";
  }
  if(!singleCardPickerActive){renderMultiCardCameraOverlay([]);return}
  setCardText("singleCardTargetStatus","Detecting card regions…");
  setCardText("singleCardTargetGuidance","Keep the cards still for a moment.");
  const payload=await api("/api/single-card/regions");
  const slots=Array.isArray(payload.slots)?payload.slots:[];
  const detected=Number(payload.detected_count||slots.length||0);
  if(detected===1&&slots[0]?.slot){
    setCardText("singleCardTargetStatus","One card found · recognizing");
    setCardText("singleCardTargetGuidance","RareIQ selected the only detected card automatically.");
    return recognizePickedSingleCard(slots[0].slot,true);
  }
  if(detected<1){
    singleCardPickerActive=false;if(button){button.setAttribute("aria-pressed","false");button.textContent="Choose Card"}
    renderMultiCardCameraOverlay([]);setCardText("singleCardTargetStatus","No card found");setCardText("singleCardTargetGuidance","Move one card fully into view and try again.");setRecognitionState("searching","No complete card region detected.");return;
  }
  renderMultiCardCameraOverlay(slots,[],true);
  setCardText("singleCardTargetStatus",`${detected} cards found · choose one`);
  setCardText("singleCardTargetGuidance","Click a numbered box in the camera view.");
  setRecognitionState("searching",`Choose one of ${detected} numbered card regions.`);
}

async function recognizePickedSingleCard(slot,automatic=false){
  singleCardPickerActive=false;
  const button=$("singleCardPickerButton");
  if(button){button.setAttribute("aria-pressed","false");button.textContent="Choose Card"}
  renderMultiCardCameraOverlay([]);
  const result=await api(`/api/single-card/pick/${Number(slot)}`,{method:"POST",body:"{}"});
  if(!result.job_accepted) throw new Error(result.reason||"picked_card_not_accepted");
  setCardText("singleCardTargetStatus",`Card ${Number(slot)} submitted`);
  setCardText("singleCardTargetGuidance",automatic?"Automatically selected from a single detected region.":"Your numbered selection is being verified.");
  setRecognitionState("captured",`Card ${Number(slot)} submitted for single-card recognition.`);
}

function renderMultiCardStatus(payload={}){
  const slots=Array.isArray(payload.slots)?payload.slots:[];
  const selectedSlots=Array.isArray(payload.selected_slots)?payload.selected_slots.map(Number):[];
  const capacity=Math.max(2,Math.min(12,Number(payload.max_cards||$("multiCardMaxCards")?.value||6)));
  document.querySelectorAll("[data-multi-card-slot]").forEach(node=>{node.hidden=Number(node.dataset.multiCardSlot)>capacity});
  renderMultiCardCameraOverlay(slots,selectedSlots);
  slots.forEach(item=>{
    const node=document.querySelector(`[data-multi-card-slot="${item.slot}"]`);
    if(!node) return;
    node.dataset.state=item.status||"empty";
    const title=node.querySelector("strong");
    const detail=node.querySelector("p");
    const card=item.card||{};
    node.classList.toggle("is-temporal-verified",Boolean(item.temporal_confirmation));
    node.classList.toggle("is-confirming",!item.verified&&Number(item.temporal_confirmation_progress||0)>0);
    node.classList.toggle("is-output-selected",selectedSlots.includes(Number(item.slot)));
    let showButton=node.querySelector(".multi-card-show-toggle");
    if(!showButton){showButton=document.createElement("button");showButton.type="button";showButton.className="multi-card-show-toggle";showButton.dataset.slot=String(item.slot);node.appendChild(showButton)}
    showButton.textContent=selectedSlots.includes(Number(item.slot))?"On Screen":"Show";
    showButton.setAttribute("aria-pressed",String(selectedSlots.includes(Number(item.slot))));
    showButton.disabled=!item.card;
    let artwork=node.querySelector("img");
    const referenceImage=item.card?multiCardReferenceImage(card):"";
    if(referenceImage){
      if(!artwork){artwork=document.createElement("img");artwork.alt="";node.querySelector("span")?.after(artwork)}
      artwork.src=referenceImage;artwork.hidden=false;
    }else if(artwork){artwork.remove()}
    if(title) title.textContent=item.card?multiCardName(card):String(item.status||"Waiting").replaceAll("-"," ");
    let facts=node.querySelector(".multi-card-facts");
    if(!facts){facts=document.createElement("dl");facts.className="multi-card-facts";node.appendChild(facts)}
    const identifier=item.printed_code||item.collector_number||card.collector_number||card.card_number||"--";
    const setName=card.set_name||card.set||card.set_id||"Unknown set";
    const language=card.language_code||card.language||item.language||"--";
    const confidence=Math.round(Number(item.confidence||card.confidence||0)*100);
    const statusLabel=item.verified?"Verified":item.card?"Review needed":String(item.status||"Waiting").replaceAll("-"," ");
    facts.replaceChildren();
    [["Card #",identifier],["Set",setName],["Confidence",`${confidence}%`],["Status",statusLabel],["Language",language]].forEach(([label,value])=>{
      const row=document.createElement("div");
      const term=document.createElement("dt");term.textContent=label;
      const description=document.createElement("dd");description.textContent=String(value);
      row.append(term,description);facts.appendChild(row);
    });
    let verification=node.querySelector(".multi-card-verification");
    if(!verification){verification=document.createElement("small");verification.className="multi-card-verification";node.appendChild(verification)}
    const temporalProgress=Number(item.temporal_confirmation_progress||0);
    verification.textContent=item.temporal_confirmation
      ?"Temporally verified"
      :!item.verified&&temporalProgress>0
      ?`Confirming ${temporalProgress}/${Number(item.temporal_confirmation_required||2)}`
      :item.verified
      ?"Exact this scan"
      :item.card
      ?"Provisional · needs confirmation"
      :"";
    verification.hidden=!verification.textContent;
    if(detail){
      detail.textContent=item.card
        ?`${statusLabel} · ${selectedSlots.includes(Number(item.slot))?"Selected for screen":"Not on screen"}`
        :item.status==="not-detected"
        ?"No card detected"
        :item.status==="recognizing"
        ?"Analyzing card"
        :"Waiting for capture";
    }
  });
  const detected=Number(payload.detected_count||0);
  const completed=Number(payload.completed_count||0);
  setCardText(
    "multiCardSummary",
    payload.status==="complete"
      ?`${detected} card${detected===1?"":"s"} processed · select Show for on-screen output`
      :payload.status==="recognizing"
      ?`Recognizing ${detected} cards · ${completed} complete`
      :payload.status==="no-cards-detected"
      ?"No cards detected · increase spacing and try again"
      :"Ready for multi-card capture"
  );
  setCardText(
    "multiCardGuidance",
    payload.status==="recognizing"
      ?`Keep all ${detected} detected card${detected===1?"":"s"} still while RareIQ verifies each one.`
      :"Arrange up to twelve cards with clear gaps, then scan the full zone."
  );
  if(studioXRecognitionMode==="six-card-grid"&&payload.status==="recognizing"){
    clearTimeout(multiCardPollTimer);
    multiCardPollTimer=setTimeout(loadMultiCardStatus,80);
  }
}

async function loadMultiCardStatus(){
  try{renderMultiCardStatus(await api("/api/multi-card/status"))}
  catch(error){console.warn("multi_card_status_failed",error)}
}

async function captureMultiCardGrid(){
  const uniqueVariants=Boolean($("multiCardUniqueVariants")?.checked);
  const requestedCards=Math.max(2,Math.min(12,Number($("multiCardMaxCards")?.value||6)));
  setCardText("multiCardSummary",`Detecting up to ${requestedCards} cards…`);
  const payload=await api("/api/multi-card/capture",{
    method:"POST",
    body:JSON.stringify({unique_variants:uniqueVariants,max_cards:requestedCards})
  });
  renderMultiCardStatus(payload);
  return payload;
}

async function toggleMultiCardOutput(slot){
  const current=await api("/api/multi-card/status");
  const selected=new Set((current.selected_slots||[]).map(Number));
  selected.has(Number(slot))?selected.delete(Number(slot)):selected.add(Number(slot));
  const payload=await api("/api/multi-card/select",{method:"POST",body:JSON.stringify({slots:[...selected]})});
  renderMultiCardStatus(payload);
  if(payload.rare_intelligence){
    studioXPokedexPayload=payload.rare_intelligence;
    const identity=payload.rare_intelligence.identity||{};
    studioXPokedexKey=String(identity.card_id||`${identity.set_name||""}:${identity.collector_number||""}:${identity.card_name||""}`);
    renderPokedexPayload(studioXPokedexPayload);
    setStudioXWidgetState("pokedex",studioXPokedexPayload.status||"available");
  }
}

const VIRTUAL_CAMERA_TERMS=[
  "virtual","obs","streamlabs","manycam","snap camera","ndi","intcast",
  "bytecast","xsplit","iriun","epoccam","droidcam"
];

function isVirtualCamera(camera){
  const name=String(camera?.name||"").trim().toLowerCase();
  return Boolean(name&&VIRTUAL_CAMERA_TERMS.some(term=>name.includes(term)));
}

function decodeCameraValue(value){
  if(!value) return null;
  try{
    return JSON.parse(decodeURIComponent(value));
  }catch{
    return null;
  }
}

function cameraOptionValue(camera,index=0){
  return encodeURIComponent(JSON.stringify({
    source_id:camera?.source_id||null,
    index:Number(camera?.index??index),
    backend:Number(camera?.backend??700),
    name:camera?.name||`Camera ${index+1}`
  }));
}

function sourceIdFromCameraValue(value){
  return decodeCameraValue(value)?.source_id||null;
}

function sortCameraDevices(cameras=[]){
  return [...cameras].sort((left,right)=>{
    const virtualOrder=Number(isVirtualCamera(left))-Number(isVirtualCamera(right));
    if(virtualOrder) return virtualOrder;
    const instaOrder=Number(!/insta360/i.test(left?.name||""))-Number(!/insta360/i.test(right?.name||""));
    if(instaOrder) return instaOrder;
    const nameOrder=String(left?.name||"").localeCompare(String(right?.name||""));
    if(nameOrder) return nameOrder;
    return Number(left?.backend||0)-Number(right?.backend||0);
  });
}

function appendCameraGroup(select,label,cameras){
  if(!cameras.length) return;
  const group=document.createElement("optgroup");
  group.label=label;
  cameras.forEach((camera,index)=>{
    const option=document.createElement("option");
    option.value=cameraOptionValue(camera,index);
    option.textContent=`${camera.name||`Camera ${index+1}`}${camera.backend_name?`  |  ${camera.backend_name}`:""}`;
    option.dataset.cameraKind=isVirtualCamera(camera)?"virtual":"physical";
    group.appendChild(option);
  });
  select.appendChild(group);
}

async function runCameraSourceAction(select){
  const action=select?.value||"";
  if(select) select.value="";
  if(action==="refresh") await loadCameraList({force:true});
  else if(action==="reconnect") await reconnectCamera();
  else if(action==="restart") await restartFeed();
}

function arrangeCameraToolbar(){
  const toolbar=document.querySelector(".toolbar");
  if(!toolbar) return;
  const menu=toolbar.querySelector(".premium-more-menu");
  const popover=toolbar.querySelector(".premium-more-popover");
  const actions=toolbar.querySelector(".premium-actions-row");
  const compact=window.matchMedia("(max-width: 1180px)").matches;
  const secondary=[
    document.querySelector('[data-ui4-action="diagnostics"]'),
    document.querySelector('[data-ui4-action="health"]'),
  ].filter(Boolean);
  if(compact&&popover){
    secondary.forEach(node=>popover.appendChild(node));
  }else if(actions){
    secondary.forEach(node=>actions.appendChild(node));
  }
  if(menu?.open&&compact){
    menu.open=false;
  }
}

function updateActiveCameraName(camera,state="active"){
  const output=$("activeCameraName");
  if(!output) return;
  if(!camera){
    output.textContent=state==="none"?"No cameras detected":"Select a camera";
    output.dataset.state=state;
    return;
  }
  const label=camera.name||`Camera ${Number(camera.index)+1}`;
  const select=$("cameraSelect");
  const matchingOption=[...(select?.options||[])].find(option=>{
    const candidate=decodeCameraValue(option.value);
    return candidate&&(
      (Number(candidate.index)===Number(camera.index)&&Number(candidate.backend)===Number(camera.backend))||
      String(candidate.name||"").trim()===String(camera.name||"").trim()
    );
  });
  if(select&&matchingOption) select.value=matchingOption.value;
  output.textContent=
    state==="virtual"?`${label} -- confirmation required`:
    state==="disconnected"?`${label} -- disconnected`:
    `Active: ${label}`;
  output.dataset.state=state;
  updateViewerInspectionHeader();
}

function updateViewerInspectionHeader(
  context=window.__rareiqCardContext||null
){
  const mode=$("viewerInspectionMode");
  const cardState=$("viewerInspectionCardState");
  const recognition=$("viewerInspectionRecognitionMode");
  if(mode){
    mode.textContent=$("viewerModeStatus")?.textContent?.trim()||"Auto · full frame";
  }
  if(cardState){
    cardState.textContent=context?.presentation?.title||"READY";
  }
  if(recognition){
    recognition.textContent=
      context?.verified===true
        ?"Verified identity"
        :context?.card
        ?"Candidate review"
        :"Live recognition";
  }
}

function setCameraActionAvailability(connected){
  document.body.classList.toggle("camera-disconnected",!connected);
  const capture=document.querySelector('[onclick="captureCamera()"]');
  const auto=$("autoCaptureToggle");
  if(capture) capture.disabled=!connected;
  if(auto) auto.disabled=!connected;
}

function setCameraDisconnectedPresentation(camera,error=""){
  cameraConnectionAvailable=false;
  cameraConnectionFailure={camera,error:String(error||"")};
  markViewerOffline();
  setCameraActionAvailability(false);
  const name=camera?.name||"Selected camera";
  const failure=String(error||"").trim();
  const failedSource=failure.toLowerCase().includes(name.toLowerCase())
    ?failure
    :`Could not open ${name}`;
  const detail=`${failedSource.replace(/[.\s]+$/g,"")}. Select a physical camera or refresh devices`;
  setCameraStatus("CAMERA DISCONNECTED","var(--red)");
  setStateChip("cameraStateChip","error","DISCONNECTED");
  updateActiveCameraName(camera,"disconnected");
  applyRecognitionPresentation({
    key:"error",
    state:"error",
    title:"DISCONNECTED",
    detail,
    placeholderTitle:"Camera Disconnected",
    placeholderDetail:"Select a physical camera or refresh devices",
    confidence:0,
  });
  const recovery=$("cameraRecovery");
  if(recovery){
    recovery.classList.remove("suppressed","success");
    recovery.classList.add("visible","error");
  }
  if($("cameraRecoveryTitle")) $("cameraRecoveryTitle").textContent=`Could not open ${name}`;
  if($("cameraRecoveryDetail")) $("cameraRecoveryDetail").textContent="Select a physical camera or refresh devices";
}

function readSelectedCamera(){
  const value = $("cameraSelect").value;
  if(!value){
    selectedCamera = null;
    return null;
  }
  try{
    selectedCamera = JSON.parse(decodeURIComponent(value));
    localStorage.setItem("rareiq.selectedCamera",value);
    return selectedCamera;
  }catch{
    selectedCamera = null;
    return null;
  }
}

async function selectCamera(){
  resetRecognitionPresentation("active_source_changed");
  readSelectedCamera();
  secondaryBayPreferences.activeSource=$("cameraSelect")?.value||null;
  cameraWorkspacePreferences.sources["1"]=$("cameraSelect")?.value||null;
  [2,3,4].forEach(slot=>{
    if(cameraWorkspacePreferences.sources[String(slot)]===cameraWorkspacePreferences.sources["1"]){
      cameraWorkspacePreferences.sources[String(slot)]=null;
      if(slot===2) secondaryBayPreferences.stagingSource=null;
    }
  });
  normalizeSecondarySourcePair();
  saveSecondaryBayPreferences();
  saveCameraWorkspacePreferences();
  renderSecondaryWorkspaceBay();
  renderCameraWorkspace();
  cameraAutostartComplete=false;
  if(!selectedCamera){
    updateActiveCameraName(null,"select");
    return;
  }
  updateActiveCameraName(selectedCamera,"selected");
  const started=await ensureCameraStarted(true);
  if(started) updateActiveCameraName(selectedCamera,"active");
}

async function startSelectedCamera(){
  const camera=readSelectedCamera();

  if(!camera){
    setCameraStatus("SELECT A CAMERA","var(--gold)");
    return;
  }

  cameraAutostartComplete=false;
  await ensureCameraStarted(true);
}

async function stopCamera(){
  try{
    await api("/api/camera/stop",{method:"POST",body:"{}"});
  }finally{
    $("cameraFeed").removeAttribute("src");
    const placeholder = $("cameraPlaceholder");
    if(placeholder) placeholder.classList.remove("hidden");
    cameraStreamStarted=false;
    await loadCameraStatus();
  }
}

async function reconnectCamera(){
  const camera=readSelectedCamera();
  if(!camera){
    setCameraDisconnectedPresentation(
      null,
      "Select a physical camera or refresh devices"
    );
    return;
  }
  cameraAutostartComplete=false;
  cameraStreamStarted=false;
  cameraStreamFailures=0;

  setCameraRecovery(
    `Reconnecting ${camera.name||"camera"}...`,
    "RareIQ is reopening the exact selected source."
  );

  try{
    const connected=await ensureCameraStarted(true);
    if(!connected) throw new Error(`Could not open ${camera.name||"selected camera"}`);
    updateActiveCameraName(camera,"active");
  }catch(error){
    setCameraDisconnectedPresentation(camera,error?.message);
  }
}

async function captureCamera(){
  setRecognitionState("searching","Saving current corrected card crop...");
  try{
    const result=await api("/api/camera/capture",{
      method:"POST",
      body:"{}"
    });

    if(result.ok && (result.job_accepted || result.queued)){
      const file=result.path ? String(result.path).split(/[\/]/).pop() : "Capture saved";
      const queued=Boolean(result.queued);
      setCameraStatus(queued?"RECOGNITION QUEUED":"RECOGNITION ACCEPTED","var(--green)");
      setRecognitionState("captured",queued?"Fresh crop queued for recognition.":"Fresh crop submitted for recognition.");
      showCaptureBanner(true,queued?"RECOGNITION QUEUED":"RECOGNITION ACCEPTED",file);
      notify(queued?"Recognition Queued":"Recognition Accepted",file,"success");
      addActivity("Manual Capture",`${file} / generation ${result.generation}`);
    }else if(result.ok){
      setCameraStatus("CROP SAVED / JOB REJECTED","var(--gold)");
      setRecognitionState("error",result.reason||"Recognition job was not accepted.");
      showCaptureBanner(false,"JOB NOT ACCEPTED",result.reason||"Crop saved only.");
    }else{
      setCameraStatus("NO CARD CROP","var(--gold)");
      setRecognitionState("error","No corrected card image is available yet.");
      showCaptureBanner(false,"CAPTURE NOT SAVED",result.error||"No corrected card crop available.");
      notify("Capture Not Saved",result.error||"No corrected crop.","error");
      addActivity("Capture Failed",result.error||"No corrected crop.");
    }
  }catch{
    setCameraStatus("CAPTURE FAILED","var(--red)");
    setRecognitionState("error","Capture request failed.");
    showCaptureBanner(false,"CAPTURE FAILED","RareIQ could not save the card.");
    addActivity("Capture Failed","Request error.");
  }
}

function startCameraStream(force=false){ connectMainViewer(force); }

function __oldStartCameraStream(force=false){
  const feed=$("cameraFeed");
  if(!feed) return;
  if(cameraStreamStarted&&!force&&feed.getAttribute("src")) return;

  clearTimeout(cameraStreamRetryTimer);
  const placeholder=$("cameraPlaceholder");
  const recovery=$("cameraRecovery");

  if(recovery){
    recovery.classList.add("visible");
    $("cameraRecoveryTitle").textContent="Connecting camera...";
    $("cameraRecoveryDetail").textContent="Waiting for the first live frame.";
  }

  feed.src=`/api/camera/stream?ts=${Date.now()}&retry=${cameraStreamFailures}`;
  cameraStreamStarted=true;

  cameraStreamRetryTimer=setTimeout(()=>{
    const hasFrame=feed.naturalWidth>0&&feed.naturalHeight>0;
    if(!hasFrame){
      cameraStreamStarted=false;
      cameraStreamFailures+=1;
      if(cameraStreamFailures<=8){
        if(recovery){
          recovery.classList.add("visible");
          $("cameraRecoveryTitle").textContent="Restoring live preview...";
          $("cameraRecoveryDetail").textContent=`Retry ${cameraStreamFailures} of 8`;
        }
        startCameraStream(true);
      }else{
        if(placeholder) placeholder.classList.remove("hidden");
        if(recovery){
          recovery.classList.add("visible");
          $("cameraRecoveryTitle").textContent="Live preview unavailable";
          $("cameraRecoveryDetail").textContent="Use Reconnect or Refresh Camera.";
        }
      }
    }
  },1400);
}

function setCameraStatus(text,color){
  $("cameraStatus").textContent=text;
  $("cameraStatus").style.color=color;
}


async function bootstrapCamera(){
  if(cameraBootstrapRunning) return;
  cameraBootstrapRunning=true;
  cameraAutostartComplete=false;

  try{
    setCameraRecovery(
      "Discovering cameras...",
      "RareIQ is scanning Windows video devices."
    );

    const cameras=await loadCameraList({
      retries:10,
      delay:700
    });

    if(!cameras.length){
      setCameraStatus("CAMERA NOT FOUND","var(--gold)");
      setStateChip("cameraStateChip","warning","DISCOVERING");
      setCameraRecovery(
        "Waiting for camera...",
        "RareIQ will continue checking automatically."
      );
      scheduleCameraDiscovery();
      return;
    }

    const started=await ensureCameraStarted(true);

    if(!started){
      scheduleCameraDiscovery();
    }
  }finally{
    cameraBootstrapRunning=false;
  }
}

async function loadCameraStatus(options={}){
  const {forceStream=false}=options;
  try{
    const status = await api("/api/camera/status");
    const manager=status.manager||{};
    const vision=status.vision||status;
    const online=cameraStatusOnline(status);
    cameraConnectionAvailable=online;
    cameraConnectionFailure=online?null:{
      camera:manager.selected_camera||selectedCamera,
      error:manager.last_error||manager.message||"Camera is disconnected",
    };
    updateActiveCameraName(
      manager.selected_camera||selectedCamera,
      online?"active":"disconnected"
    );
    const stalled=Boolean(
      manager.stalled ||
      manager.state==="stalled" ||
      manager.health_reason==="frame_progress_stalled"
    );
    setCameraStatus(
      online ? "CAMERA ONLINE" : (stalled ? "CAMERA STALLED" : "CAMERA OFFLINE"),
      online ? "var(--green)" : "var(--red)"
    );
    setStateChip(
      "cameraStateChip",
      online?"on":(stalled?"warning":"error"),
      online?"ONLINE":(stalled?"STALLED":"OFFLINE")
    );
    applyAutoCaptureState(vision.auto_capture_enabled ?? true);
    window.__rareiqVisionTelemetry=vision;
    updateResolutionBadge(vision);
    alignScanZone(vision);
    const feed=$("cameraFeed");
    const viewerHasFrame=Boolean(feed&&feed.naturalWidth>0&&feed.naturalHeight>0);

    if(viewerHasFrame){
      markViewerLive();
      alignScanZone(window.__rareiqVisionTelemetry||{});
    }else if(online){
      if(forceStream||!cameraStreamStarted){
        startCameraStream(forceStream);
      }
    }else if(!cameraStartInFlight){
      setStateChip("cameraStateChip","warning","STARTING");
    }

    if(online){
      setCameraActionAvailability(true);
    }else{
      setCameraDisconnectedPresentation(
        cameraConnectionFailure.camera,
        cameraConnectionFailure.error
      );
    }

    if(vision.fps){
      $("fpsValue").textContent = `${Math.round(Number(vision.fps))} FPS`;
    }
  }catch{
    if(!cameraStartInFlight&&!cameraAutostartComplete){
      setCameraStatus("CAMERA STATUS RETRYING","var(--gold)");
    }
  }
}

function normalize(value){
  const number=Number(value||0);
  return Math.max(0,Math.min(1,number>1?number/100:number));
}

function setSignal(name,value){
  const percent=Math.round(normalize(value)*100);
  const bar=$(`${name}Bar`);
  const text=$(`${name}Value`);
  const hudBar=$(`${name}HudBar`);
  const hudText=$(`${name}HudValue`);
  if(bar) bar.style.width=`${percent}%`;
  if(text) text.textContent=`${percent}%`;
  if(hudBar) hudBar.style.width=`${percent}%`;
  if(hudText) hudText.textContent=`${percent}%`;
}

const PIPELINE_STAGE_DEFINITIONS=[
  {key:"detect",label:"Detect",aliases:["detect","detection","visible","card_detected"]},
  {key:"stabilize",label:"Stabilize",aliases:["stabilize","acquiring","stable","lock","card_locked"]},
  {key:"capture",label:"Capture",aliases:["capture","prepare","crop","card_captured"]},
  {key:"recognize",label:"Recognize",aliases:["recognize","read","ocr","searching","recognition"]},
  {key:"match",label:"Match",aliases:["match","artwork","verify","verified","candidate"]}
];
const PIPELINE_STATES=["waiting","active","complete","warning","failed","skipped"];
const PIPELINE_STATE_LABELS={
  waiting:"Waiting",active:"Active",complete:"Complete",
  warning:"Warning",failed:"Failed",skipped:"Skipped"
};
const PIPELINE_STATE_ICONS={
  waiting:" | ",active:"▶",complete:"✓",warning:"!",failed:"×",skipped:"–"
};

function normalizePipelineState(stage){
  if(!stage||typeof stage!=="object") return "waiting";
  const raw=String(stage.status??stage.state??"").trim().toLowerCase();
  if(stage.failed===true||stage.error===true||["error","failed","failure"].includes(raw)) return "failed";
  if(stage.warning===true||["warning","warn","degraded"].includes(raw)) return "warning";
  if(stage.skipped===true||["skipped","skip","not_applicable"].includes(raw)) return "skipped";
  if(stage.done===true||["done","complete","completed","success","succeeded"].includes(raw)) return "complete";
  if(stage.active===true||["running","active","working","processing","in_progress"].includes(raw)) return "active";
  if(["idle","pending","waiting","queued",""].includes(raw)) return "waiting";
  return "waiting";
}

function renderPipeline(stages,hasCard){
  const sourceStages=Array.isArray(stages)?stages:[];
  const normalizedStages=sourceStages.map(stage=>({
    key:String(stage?.key??stage?.name??"").trim().toLowerCase(),
    state:normalizePipelineState(stage)
  }));
  const precedence={failed:6,warning:5,active:4,complete:3,skipped:2,waiting:1};
  let activeClaimed=false;

  document.querySelectorAll(".pipeline-step").forEach((el,index)=>{
    const definition=PIPELINE_STAGE_DEFINITIONS[index];
    const matches=normalizedStages.filter(stage=>definition.aliases.includes(stage.key));
    let state=matches.reduce(
      (selected,stage)=>precedence[stage.state]>precedence[selected]?stage.state:selected,
      "waiting"
    );
    if(hasCard&&!matches.length) state="complete";
    if(state==="active"){
      if(activeClaimed) state="waiting";
      else activeClaimed=true;
    }

    PIPELINE_STATES.forEach(value=>el.classList.remove(`state-${value}`));
    el.classList.remove("active","done");
    el.classList.add(`state-${state}`);
    el.classList.toggle("active",state==="active");
    el.classList.toggle("done",state==="complete");
    el.dataset.state=state;
    if(state==="active") el.setAttribute("aria-current","step");
    else el.removeAttribute("aria-current");

    const status=PIPELINE_STATE_LABELS[state];
    const statusNode=el.querySelector(".process-status b");
    const icon=el.querySelector(".process-state-icon");
    if(statusNode) statusNode.textContent=status;
    if(icon) icon.textContent=PIPELINE_STATE_ICONS[state];
    el.setAttribute("aria-label",`${definition.label}: ${status}`);
  });
}

function setScanState(payload,card,confidence){
  const zone=$("scanZone");
  const status=String(payload.status||"").toLowerCase();

  zone.classList.remove("detected","reading","verified");
  if(
    card&&confidence>=.68&&
    payload?.recognition_locked===true&&
    String(payload?.verification_state||"").toUpperCase()==="VERIFIED"
  ){
    zone.classList.add("verified");
  }else if(status.includes("ocr")||status.includes("read")){
    zone.classList.add("reading");
  }else if(status.includes("detect")||payload.card_detected){
    zone.classList.add("detected");
  }
}

function triggerHit(){
  document.body.classList.remove("hit-flash");
  void document.body.offsetWidth;
  document.body.classList.add("hit-flash");
  $("scanZone").classList.add("hit");
  setTimeout(()=>$("scanZone").classList.remove("hit"),1000);
}


function setCoreState(state){
  const orb = $("coreOrb");
  const label = $("coreLabel");
  if(!orb || !label) return;
  orb.classList.remove("scanning","matched","complete");
  const normalized = String(state||"idle").toLowerCase();
  if(["detecting","scanning","candidate-found","verifying","review-needed"].includes(normalized)){
    orb.classList.add("scanning");
    label.textContent=normalized.replaceAll("-"," ").toUpperCase();
  }else if(["matched","verified","exact-match"].includes(normalized)){
    orb.classList.add("matched");
    label.textContent="EXACT MATCH";
  }else if(normalized==="complete"){
    orb.classList.add("complete");
    label.textContent="COMPLETE";
  }else if(normalized==="error"){
    label.textContent="ERROR";
  }else{
    label.textContent="READY";
  }
}

function resetRecognitionPresentation(reason="reset"){
  recognitionPresentationMemory={key:"ready",presentation:null,changedAt:0};
  clearCardFocusGeometry();
  resetUI4PresentationSurfaces();
  previousCardId=null;
  const empty=$("inspectorEmpty");
  const main=$("inspectorMain");
  if(empty) empty.style.display="none";
  if(main) main.style.display="grid";
  if($("cardArt")) $("cardArt").innerHTML="";
  if($("cardName")) $("cardName").textContent="Ready to Scan";
  if($("cardMeta")) $("cardMeta").textContent="";
  if($("cardStatus")) $("cardStatus").textContent="READY";
  if($("confidence")) $("confidence").textContent="0%";
  updateConfidenceRing(0);
  setSignal("vision",0);
  setSignal("ocr",0);
  setSignal("collector",0);
  setSignal("fusion",0);
  renderPipeline([],false);
  renderRecognitionLatencyTrace();
  resetExtendedCardData();
  setCoreState("idle");
  window.__rareiqRecognitionPoll={
    revision:null,
    generation:null,
    serverSessionId:currentServerSessionId,
    phase:"EMPTY",
    candidateCount:0,
    resetReason:reason,
    updatedAt:Date.now(),
  };
  updateSharedCardContext(
    deriveSharedCardContext(
      deriveRecognitionPresentation({phase:"IDLE"},null,[]),
      null,
      {phase:"IDLE"},
      []
    )
  );
}

async function requestNextRecognition(){
  beginCardHandoff("cleared");
  const response=await fetch("/api/recognition/clear",{method:"POST"});
  const payload=await response.json().catch(()=>({}));
  if(!response.ok||payload.ok!==true){
    throw new Error(payload.message||payload.error||"Unable to clear recognition.");
  }
  resetRecognitionPresentation("operator_clear");
  completeCardHandoff();
  return payload;
}

function normalizeStudioXPreferences(value){
  const layouts=["intelligence","balanced","monitor","custom"];
  const viewerModes=["auto","full-frame","card-focus"];
  const zoom=Number(value?.previewZoom);
  const inspectorWidth=Number(value?.inspectorWidth);
  return {
    version:1,
    layoutPreset:layouts.includes(value?.layoutPreset)
      ? value.layoutPreset
      : "intelligence",
    viewerMode:viewerModes.includes(value?.viewerMode)
      ? value.viewerMode
      : "auto",
    previewZoom:Number.isFinite(zoom)
      ? Math.max(.8,Math.min(2.5,zoom))
      : 1,
    inspectorWidth:Number.isFinite(inspectorWidth)
      ? Math.max(340,Math.min(760,inspectorWidth))
      : null,
  };
}

function normalizeCameraWorkspacePreferences(value){
  const source=value?.sources&&typeof value.sources==="object"?value.sources:{};
  const sides=value?.sides&&typeof value.sides==="object"?value.sides:{};
  const normalizeSource=slot=>typeof source[String(slot)]==="string"&&source[String(slot)]?source[String(slot)]:null;
  const normalizeSide=slot=>["unassigned","player-1","player-2"].includes(sides[String(slot)])?sides[String(slot)]:"unassigned";
  const savedLayout=value?.layout==="dual-stack"?"dual-side":value?.layout;
  return {
    version:1,
    layout:CAMERA_WORKSPACE_LAYOUTS.includes(savedLayout)?savedLayout:"single",
    activeSlot:[1,2,3,4].includes(Number(value?.activeSlot))?Number(value.activeSlot):1,
    sources:{"1":normalizeSource(1),"2":normalizeSource(2),"3":normalizeSource(3),"4":normalizeSource(4)},
    sides:{"1":normalizeSide(1),"2":normalizeSide(2),"3":normalizeSide(3),"4":normalizeSide(4)},
  };
}

function loadCameraWorkspacePreferences(){
  try{
    return normalizeCameraWorkspacePreferences(JSON.parse(localStorage.getItem(CAMERA_WORKSPACE_KEY)||"null"));
  }catch{
    return normalizeCameraWorkspacePreferences(null);
  }
}

function saveCameraWorkspacePreferences(){
  try{localStorage.setItem(CAMERA_WORKSPACE_KEY,JSON.stringify(cameraWorkspacePreferences));}catch{}
}

async function refreshCameraSlotState(){
  try{
    const result=await api("/api/camera-slots");
    (result.slots||[]).forEach(slot=>{
      const id=String(slot.slot_id);
      cameraWorkspaceSlotStates[id]=slot;
      cameraWorkspacePreferences.sources[id]=slot.source
        ?cameraOptionValue(slot.source,slot.slot_id-1)
        :null;
      cameraWorkspacePreferences.sides[id]=slot.side||"unassigned";
      if(slot.role==="active"){
        cameraWorkspacePreferences.activeSlot=slot.slot_id;
        const active=$("cameraSelect");
        const value=cameraWorkspacePreferences.sources[id];
        if(active&&value&&[...active.options].some(option=>option.value===value)) active.value=value;
      }
      if(slot.slot_id===2) secondaryBayPreferences.stagingSource=cameraWorkspacePreferences.sources[id];
    });
    saveSecondaryBayPreferences();
    saveCameraWorkspacePreferences();
    renderCameraWorkspace();
    return result;
  }catch{
    return null;
  }
}

function cameraWorkspaceVisibleSlots(layout=cameraWorkspacePreferences.layout){
  return layout==="single"?[1]:layout==="dual-side"?[1,2]:layout==="triple"?[1,2,3]:[1,2,3,4];
}

function syncCameraWorkspaceSourceOptions(){
  const active=$("cameraSelect");
  if(!active) return;
  const selectForSlot=slot=>slot===1?$("cameraSlot1Source"):slot===2?$("stagingSourceSelect"):$(`cameraSlot${slot}Source`);
  [1,2,3,4].forEach(slot=>{
    const select=selectForSlot(slot);
    if(!select) return;
    const current=slot===1?active.value:cameraWorkspacePreferences.sources[String(slot)];
    select.replaceChildren();
    const prompt=document.createElement("option");
    prompt.value="";
    prompt.textContent=slot===1?"Select a camera":"No camera selected";
    select.appendChild(prompt);
    [...active.children].forEach(child=>{
      const target=child.tagName==="OPTGROUP"?document.createElement("optgroup"):select;
      if(child.tagName==="OPTGROUP") target.label=child.label;
      const options=child.tagName==="OPTGROUP"?[...child.children]:[child];
      options.filter(option=>option.value).forEach(option=>{
        const clone=option.cloneNode(true);
        const owner=[1,2,3,4].find(other=>other!==slot&&cameraWorkspacePreferences.sources[String(other)]===clone.value);
        if(owner){
          clone.disabled=true;
          clone.textContent=`${clone.textContent} — Camera ${owner}`;
        }
        target.appendChild(clone);
      });
      if(child.tagName==="OPTGROUP"&&target.children.length) select.appendChild(target);
    });
    const available=[...select.options].some(option=>option.value===current);
    if(current&&!available){
      const missing=document.createElement("option");
      const decoded=decodeCameraValue(current);
      missing.value=current;
      missing.textContent=`${decoded?.name||"Saved camera"} — missing`;
      missing.disabled=true;
      select.appendChild(missing);
    }
    select.value=current||"";
  });
}

function renderCameraWorkspace(){
  const workspace=document.querySelector(".camera-workspace");
  if(!workspace) return;
  const layout=cameraWorkspacePreferences.layout;
  const visible=new Set(cameraWorkspaceVisibleSlots(layout));
  workspace.dataset.cameraLayout=layout;
  workspace.dataset.activeSlot=String(cameraWorkspacePreferences.activeSlot);
  workspace.classList.toggle("has-secondary-bay",visible.has(2));
  document.querySelectorAll("[data-camera-layout-option]").forEach(button=>{
    const selected=button.dataset.cameraLayoutOption===layout;
    button.classList.toggle("is-selected",selected);
    button.setAttribute("aria-pressed",String(selected));
  });
  if($("cameraSlot1Side")) $("cameraSlot1Side").value=cameraWorkspacePreferences.sides["1"];
  if($("cameraSlot1Connection")) $("cameraSlot1Connection").textContent=cameraConnectionAvailable===true?"CONNECTED":cameraConnectionAvailable===false?"DISCONNECTED":"CONNECTING";
  if($("cameraSlot2Side")) $("cameraSlot2Side").value=cameraWorkspacePreferences.sides["2"];
  [3,4].forEach(slot=>{
    const tile=$(`cameraWorkspaceSlot${slot}`);
    const source=cameraWorkspacePreferences.sources[String(slot)];
    if(tile) tile.hidden=!visible.has(slot);
    if($(`cameraSlot${slot}Side`)) $(`cameraSlot${slot}Side`).value=cameraWorkspacePreferences.sides[String(slot)];
    if($(`promoteCameraSlot${slot}`)) $(`promoteCameraSlot${slot}`).disabled=!source;
    const connectionState=cameraWorkspaceSlotStates[String(slot)]?.connection_state;
    if($(`cameraSlot${slot}Connection`)) $(`cameraSlot${slot}Connection`).textContent=source
      ?String(connectionState||"connecting").toUpperCase()
      :"NOT CONNECTED";
    const preview=$(`cameraSlot${slot}Preview`);
    if(preview){
      if(source){
        preview.hidden=false;
        preview.onload=()=>{
          if($(`cameraSlot${slot}Connection`)) $(`cameraSlot${slot}Connection`).textContent="CONNECTED";
          const detail=tile?.querySelector(".camera-workspace-staging-surface span");
          if(detail) detail.hidden=true;
        };
        preview.onerror=()=>{
          preview.hidden=true;
          if($(`cameraSlot${slot}Connection`)) $(`cameraSlot${slot}Connection`).textContent="DISCONNECTED";
          const detail=tile?.querySelector(".camera-workspace-staging-surface span");
          if(detail){
            detail.hidden=false;
            detail.textContent="Camera disconnected";
          }
        };
        const url=`/api/camera-slots/${slot}/stream`;
        if(preview.getAttribute("src")!==url) preview.src=url;
      }else{
        preview.hidden=true;
        preview.removeAttribute("src");
      }
    }
    const detail=tile?.querySelector(".camera-workspace-staging-surface span");
    if(detail&&!source){
      detail.hidden=false;
      detail.innerHTML="No camera selected<br>Choose a source from Manage Cameras";
    }
  });
  const bay=$("secondaryWorkspaceBay");
  if(bay) bay.hidden=!visible.has(2);
  if($("cameraSlot2Connection")) $("cameraSlot2Connection").textContent=cameraWorkspacePreferences.sources["2"]
    ?String(cameraWorkspaceSlotStates["2"]?.connection_state||"connecting").toUpperCase()
    :"NOT CONNECTED";
  syncCameraWorkspaceSourceOptions();
}

function setCameraWorkspaceLayout(layout){
  cameraWorkspacePreferences=normalizeCameraWorkspacePreferences({...cameraWorkspacePreferences,layout});
  saveCameraWorkspacePreferences();
  renderCameraWorkspace();
  alignScanZone(window.__rareiqVisionTelemetry||{});
}

async function setCameraWorkspaceSource(slot,value){
  if(slot===1) return;
  const owner=[1,2,3,4].find(other=>other!==slot&&cameraWorkspacePreferences.sources[String(other)]===value);
  if(value&&owner){
    renderCameraWorkspace();
    return;
  }
  cameraWorkspacePreferences.sources[String(slot)]=value||null;
  if(slot===2){
    secondaryBayPreferences.stagingSource=value||null;
    saveSecondaryBayPreferences();
  }
  saveCameraWorkspacePreferences();
  try{
    await api(`/api/camera-slots/${slot}/source`,{
      method:"PUT",
      body:JSON.stringify({
        source_id:sourceIdFromCameraValue(value),
        side:cameraWorkspacePreferences.sides[String(slot)]
      })
    });
  }catch(error){
    cameraWorkspacePreferences.sources[String(slot)]=null;
    showToast(error.message||"Could not assign camera.");
  }
  renderCameraWorkspace();
}

async function setCameraWorkspaceSide(slot,value){
  cameraWorkspacePreferences.sides[String(slot)]=["player-1","player-2"].includes(value)?value:"unassigned";
  saveCameraWorkspacePreferences();
  const source=cameraWorkspacePreferences.sources[String(slot)];
  if(source){
    try{
      await api(`/api/camera-slots/${slot}/source`,{
        method:"PUT",
        body:JSON.stringify({
          source_id:sourceIdFromCameraValue(source),
          side:cameraWorkspacePreferences.sides[String(slot)]
        })
      });
    }catch(error){
      showToast(error.message||"Could not update camera side.");
    }
  }
}

async function promoteCameraWorkspaceSlot(slot){
  const active=$("cameraSelect");
  const source=cameraWorkspacePreferences.sources[String(slot)];
  if(!active||!source||source===active.value) return;
  try{
    await api(`/api/camera-slots/${slot}/activate`,{method:"POST"});
    cameraWorkspacePreferences.activeSlot=slot;
    active.value=source;
    saveCameraWorkspacePreferences();
    await refreshCameraSlotState();
    cameraStreamStarted=false;
    startCameraStream();
  }catch(error){
    showToast(error.message||"Could not activate camera.");
  }
}

async function setActiveCameraWorkspaceSource(value){
  const active=$("cameraSelect");
  if(!active||active.value===value) return;
  active.value=value||"";
  await selectCamera();
}

function normalizeSecondaryBayPreferences(value){
  const modes=["hidden","camera-2","card-focus","locked-capture","broadcast-preview","recent-captures"];
  const sizes=["compact","standard","large"];
  const firstRun=!value||typeof value!=="object";
  const requestedMode=modes.includes(value?.mode)?value.mode:"camera-2";
  const mode=(
    requestedMode==="hidden"||
    (requestedMode==="card-focus"&&value?.manualPinned!==true)
  )?"camera-2":requestedMode;
  return {
    version:1,
    mode,
    visible:true,
    size:sizes.includes(value?.size)?value.size:"standard",
    activeSource:typeof value?.activeSource==="string"&&value.activeSource?value.activeSource:null,
    stagingSource:typeof value?.stagingSource==="string"&&value.stagingSource?value.stagingSource:null,
    manualPinned:typeof value?.manualPinned==="boolean"
      ? value.manualPinned
      : !firstRun,
  };
}

function deriveAutoSecondaryBayPresentation(context=null){
  const manual={
    mode:secondaryBayPreferences.mode,
    visible:secondaryBayPreferences.visible,
    size:secondaryBayPreferences.size,
    automatic:false,
  };
  if(
    secondaryBayPreferences.mode==="hidden"||
    secondaryBayPreferences.manualPinned||
    secondaryBayPreferences.mode!=="card-focus"
  ) return manual;
  const key=context?.presentation?.key||"ready";
  const geometry=normalizedCardFocusGeometry(window.__rareiqVisionTelemetry||{});
  if(key==="verifying"&&geometry){
    return {mode:"card-focus",visible:true,size:"standard",automatic:true};
  }
  if(key==="exact-match"&&geometry){
    return {mode:"card-focus",visible:true,size:"standard",automatic:true};
  }
  if(["detecting","scanning","candidate-found"].includes(key)&&geometry){
    return {mode:"card-focus",visible:true,size:"compact",automatic:true};
  }
  return {mode:"card-focus",visible:false,size:"compact",automatic:true};
}

function loadSecondaryBayPreferences(){
  try{
    return normalizeSecondaryBayPreferences(
      JSON.parse(localStorage.getItem(STUDIOX_SECONDARY_BAY_KEY)||"null")
    );
  }catch{
    return normalizeSecondaryBayPreferences(null);
  }
}

function saveSecondaryBayPreferences(){
  try{
    localStorage.setItem(
      STUDIOX_SECONDARY_BAY_KEY,
      JSON.stringify(secondaryBayPreferences)
    );
  }catch{}
}

function normalizeSecondarySourcePair(){
  const active=$("cameraSelect")?.value||secondaryBayPreferences.activeSource||null;
  const available=new Set(
    [...($("cameraSelect")?.options||[])].map(option=>option.value).filter(Boolean)
  );
  secondaryBayPreferences.activeSource=available.has(active)?active:null;
  if(
    !available.has(secondaryBayPreferences.stagingSource)||
    secondaryBayPreferences.stagingSource===secondaryBayPreferences.activeSource
  ){
    secondaryBayPreferences.stagingSource=null;
  }
  if($("stagingSourceSelect")){
    $("stagingSourceSelect").value=secondaryBayPreferences.stagingSource||"";
  }
}

function syncSecondarySourceOptions(){
  const activeSelect=$("cameraSelect");
  const staging=$("stagingSourceSelect");
  if(!activeSelect||!staging) return;
  const current=secondaryBayPreferences.stagingSource;
  staging.innerHTML='<option value="">No staging camera</option>';
  [...activeSelect.options].filter(option=>option.value).forEach(option=>{
    const clone=document.createElement("option");
    clone.value=option.value;
    clone.textContent=option.textContent;
    staging.appendChild(clone);
  });
  secondaryBayPreferences.stagingSource=current;
  normalizeSecondarySourcePair();
  saveSecondaryBayPreferences();
  renderSecondaryWorkspaceBay();
}

function truthfulLockedCapture(context){
  const snapshot=context?.snapshot||{};
  const card=context?.card||{};
  const url=
    snapshot.locked_capture_url||
    snapshot.stable_capture_url||
    snapshot.capture_url||
    card.locked_capture_url||
    card.capture_url||
    null;
  return url?{
    url,
    capturedAt:snapshot.captured_at||card.captured_at||null,
  }:null;
}

function setSecondaryBayUnavailable(title,detail){
  const image=$("secondaryBayImage");
  const broadcast=$("secondaryBroadcastPreview");
  if(image){
    image.hidden=true;
    image.removeAttribute("src");
  }
  if(broadcast){
    broadcast.hidden=true;
    broadcast.removeAttribute("src");
  }
  if($("secondaryBayUnavailable")) $("secondaryBayUnavailable").hidden=false;
  if($("secondaryBayStateTitle")) $("secondaryBayStateTitle").textContent=title;
  if($("secondaryBayStateDetail")) $("secondaryBayStateDetail").textContent=detail;
}

function renderSecondaryWorkspaceBay(context=window.__rareiqCardContext||null){
  const bay=$("secondaryWorkspaceBay");
  const workspace=document.querySelector(".camera-workspace");
  if(!bay) return;
  normalizeSecondarySourcePair();
  const effective=deriveAutoSecondaryBayPresentation(context);
  const mode=effective.mode;
  const visible=effective.visible&&mode!=="hidden";
  bay.hidden=!visible;
  bay.dataset.bayMode=mode;
  bay.dataset.baySize=effective.size;
  bay.dataset.bayControl=effective.automatic?"automatic":"manual";
  workspace?.classList.toggle("has-secondary-bay",visible);
  const heights={
    compact:"var(--secondary-bay-compact)",
    standard:"var(--secondary-bay-standard)",
    large:"var(--secondary-bay-large)",
  };
  workspace?.style.setProperty("--secondary-bay-height",heights[effective.size]);
  if($("secondaryBayMode")) $("secondaryBayMode").value=mode;
  if($("secondaryBaySize")) $("secondaryBaySize").value=secondaryBayPreferences.size;
  const twoSources=Boolean(
    secondaryBayPreferences.activeSource&&
    secondaryBayPreferences.stagingSource&&
    secondaryBayPreferences.activeSource!==secondaryBayPreferences.stagingSource
  );
  ["swapSourcesButton","promoteStagingButton"].forEach(id=>{
    if($(id)) $(id).disabled=!twoSources;
  });
  if(!visible) return;
  if($("secondaryBayBadge")){
    $("secondaryBayBadge").textContent=mode==="camera-2"?"STAGING":"ACTIVE";
  }
  if(mode==="camera-2"){
    const image=$("secondaryBayImage");
    if(secondaryBayPreferences.stagingSource){
      $("secondaryBayUnavailable").hidden=true;
      image.hidden=false;
      image.onload=()=>{
        if($("cameraSlot2Connection")) $("cameraSlot2Connection").textContent="CONNECTED";
      };
      image.onerror=()=>{
        if($("cameraSlot2Connection")) $("cameraSlot2Connection").textContent="DISCONNECTED";
        setSecondaryBayUnavailable("CAMERA 2","Camera disconnected");
      };
      const source="/api/camera-slots/2/stream";
      if(image.getAttribute("src")!==source) image.src=source;
      image.style.objectPosition="50% 50%";
      image.style.transform="none";
    }else{
      setSecondaryBayUnavailable(
        "CAMERA 2",
        "No camera selected\nChoose a source from Manage Cameras"
      );
    }
  }else if(mode==="card-focus"){
    const geometry=smoothedCardFocusGeometry(
      normalizedCardFocusGeometry(window.__rareiqVisionTelemetry||{}),
      context?.verified===true
    );
    if(!geometry){
      secondaryFocusGeometry=null;
      setSecondaryBayUnavailable(
        "Card focus unavailable — unstable card geometry",
        "RareIQ is retaining the full frame until a conservative card-shaped polygon is stable."
      );
    }else{
      const image=$("secondaryBayImage");
      const lockedCapture=context?.verified?truthfulLockedCapture(context):null;
      $("secondaryBayUnavailable").hidden=true;
      image.hidden=false;
      const source=lockedCapture?.url||"/api/camera/stream?viewer=secondary-card-focus";
      if(image.getAttribute("src")!==source) image.src=source;
      image.dataset.frameState=lockedCapture?"locked-capture":"live-active-source";
      applySecondaryCardFocusGeometry(image,geometry);
    }
  }else if(mode==="locked-capture"){
    const capture=truthfulLockedCapture(context);
    if(!capture){
      setSecondaryBayUnavailable("No locked capture","A stable captured frame has not been supplied by the current session.");
    }else{
      const image=$("secondaryBayImage");
      $("secondaryBayUnavailable").hidden=true;
      image.hidden=false;
      if(image.src!==new URL(capture.url,location.href).href) image.src=capture.url;
      if($("secondaryBayStateDetail")) $("secondaryBayStateDetail").textContent=capture.capturedAt?`Captured ${capture.capturedAt}`:"Captured frame";
    }
  }else if(mode==="broadcast-preview"){
    const frame=$("secondaryBroadcastPreview");
    $("secondaryBayUnavailable").hidden=true;
    frame.hidden=false;
    if(!frame.getAttribute("src")) frame.src="/program?embedded=1";
  }else if(mode==="recent-captures"){
    setSecondaryBayUnavailable("No recent capture frames","Recent scan identities are available, but no truthful captured-frame feed is present.");
  }
  renderCameraWorkspace();
}

function setSecondaryBayMode(mode){
  secondaryBayPreferences=normalizeSecondaryBayPreferences({
    ...secondaryBayPreferences,
    mode,
    visible:mode!=="hidden",
    manualPinned:mode!=="hidden",
  });
  saveSecondaryBayPreferences();
  renderSecondaryWorkspaceBay();
  alignScanZone(window.__rareiqVisionTelemetry||{});
}

function setSecondaryStagingSource(value){
  secondaryBayPreferences.stagingSource=value||null;
  cameraWorkspacePreferences.sources["2"]=value||null;
  normalizeSecondarySourcePair();
  saveSecondaryBayPreferences();
  saveCameraWorkspacePreferences();
  renderSecondaryWorkspaceBay();
  renderCameraWorkspace();
}

async function promoteSecondaryStagingSource(){
  const active=$("cameraSelect");
  const staging=secondaryBayPreferences.stagingSource;
  if(!active||!staging||staging===active.value) return;
  const previous=active.value;
  active.value=staging;
  secondaryBayPreferences.stagingSource=previous||null;
  cameraWorkspacePreferences.sources["1"]=staging;
  cameraWorkspacePreferences.sources["2"]=previous||null;
  saveCameraWorkspacePreferences();
  await selectCamera();
}

function loadStudioXPreferences(){
  try{
    return normalizeStudioXPreferences(
      JSON.parse(localStorage.getItem(STUDIOX_PREFERENCES_KEY)||"null")
    );
  }catch{
    return normalizeStudioXPreferences(null);
  }
}

function saveStudioXPreferences(){
  try{
    localStorage.setItem(
      STUDIOX_PREFERENCES_KEY,
      JSON.stringify(studioXPreferences)
    );
  }catch{}
}

function applyWorkspaceLayoutPreset(preset,{persist=true}={}){
  studioXPreferences=normalizeStudioXPreferences({
    ...studioXPreferences,
    layoutPreset:preset,
  });
  document.body.dataset.workspacePreset=studioXPreferences.layoutPreset;
  if(studioXPreferences.layoutPreset!=="custom"){
    studioXPreferences.inspectorWidth=null;
    document.body.style.removeProperty("--sx-custom-inspector-width");
  }
  if($("workspaceLayoutPreset")){
    $("workspaceLayoutPreset").value=studioXPreferences.layoutPreset;
  }
  if(persist) saveStudioXPreferences();
  applyInspectorWidth();
}

function announceWorkspaceLayoutPreset(preset){
  const messages={intelligence:"More room for card identity, recognition evidence, and tools.",balanced:"Camera and card intelligence now share the workspace evenly.",monitor:"The live camera is emphasized while essential card information stays visible.",custom:"Your manually resized camera and information split is active."};
  notify("Workspace Updated",messages[preset]||messages.balanced,"success");
}

function inspectorWidthBounds(){
  const viewport=document.documentElement.clientWidth||window.innerWidth;
  const rail=parseFloat(getComputedStyle(document.body).getPropertyValue("--sx-app-rail-width"))||68;
  const minimumCamera=Math.min(820,Math.max(520,viewport*.48));
  return {min:340,max:Math.max(340,Math.min(760,viewport-rail-minimumCamera-30))};
}
function applyInspectorWidth(width=studioXPreferences.inspectorWidth){
  if(studioXPreferences.layoutPreset!=="custom"){
    document.body.style.removeProperty("--sx-custom-inspector-width");return;
  }
  if(window.matchMedia("(max-width: 1100px)").matches){document.body.style.removeProperty("--sx-custom-inspector-width");return;}
  if(!Number.isFinite(Number(width))){document.body.style.removeProperty("--sx-custom-inspector-width");return;}
  const bounds=inspectorWidthBounds(),value=Math.round(Math.max(bounds.min,Math.min(bounds.max,Number(width))));
  document.body.style.setProperty("--sx-custom-inspector-width",`${value}px`);
}
function initializeInspectorResize(){
  const column=document.querySelector(".ui4-inspector-column");
  if(!column||$("inspectorResizeHandle"))return;
  const handle=document.createElement("button");
  handle.id="inspectorResizeHandle";handle.className="ui4-inspector-resize-handle";handle.type="button";
  handle.setAttribute("aria-label","Resize card information panel");handle.setAttribute("role","separator");handle.setAttribute("aria-orientation","vertical");handle.title="Drag or use arrow keys to resize · Double-click to reset";
  column.prepend(handle);
  const updateResizeHandle=value=>{const bounds=inspectorWidthBounds(),width=Math.round(Number(value)||column.getBoundingClientRect().width);handle.setAttribute("aria-valuemin",String(bounds.min));handle.setAttribute("aria-valuemax",String(bounds.max));handle.setAttribute("aria-valuenow",String(width));handle.dataset.widthLabel=`${width}px`;};
  const commitInspectorWidth=width=>{const bounds=inspectorWidthBounds(),value=Math.round(Math.max(bounds.min,Math.min(bounds.max,Number(width))));document.body.style.setProperty("--sx-custom-inspector-width",`${value}px`);studioXPreferences.inspectorWidth=value;studioXPreferences.layoutPreset="custom";document.body.dataset.workspacePreset="custom";if($("workspaceLayoutPreset"))$("workspaceLayoutPreset").value="custom";saveStudioXPreferences();updateResizeHandle(value);};
  let startX=0,startWidth=0;
  handle.addEventListener("pointerdown",event=>{if(event.button!==0)return;startX=event.clientX;startWidth=column.getBoundingClientRect().width;handle.setPointerCapture(event.pointerId);document.body.dataset.inspectorResizing="true";});
  handle.addEventListener("pointermove",event=>{if(!handle.hasPointerCapture(event.pointerId))return;const bounds=inspectorWidthBounds(),width=Math.max(bounds.min,Math.min(bounds.max,startWidth+(startX-event.clientX)));document.body.style.setProperty("--sx-custom-inspector-width",`${Math.round(width)}px`);updateResizeHandle(width);});
  handle.addEventListener("pointerup",event=>{if(!handle.hasPointerCapture(event.pointerId))return;handle.releasePointerCapture(event.pointerId);delete document.body.dataset.inspectorResizing;commitInspectorWidth(column.getBoundingClientRect().width);});
  handle.addEventListener("keydown",event=>{const keys=["ArrowLeft","ArrowRight","Home","End"];if(!keys.includes(event.key))return;event.preventDefault();const bounds=inspectorWidthBounds(),current=column.getBoundingClientRect().width,step=event.shiftKey?40:16;const next=event.key==="Home"?bounds.min:event.key==="End"?bounds.max:current+(event.key==="ArrowLeft"?step:-step);commitInspectorWidth(next);});
  handle.addEventListener("dblclick",()=>{studioXPreferences.inspectorWidth=null;studioXPreferences.layoutPreset="balanced";saveStudioXPreferences();applyWorkspaceLayoutPreset("balanced",{persist:false});updateResizeHandle(column.getBoundingClientRect().width);notify("Panel Width Reset","Balanced responsive layout restored.","success");});
  applyInspectorWidth();
  updateResizeHandle(column.getBoundingClientRect().width);
}

function normalizedCardFocusPoints(value){
  const source=Array.isArray(value)
    ? value
    : Array.isArray(value?.points)
    ? value.points
    : [];
  if(source.length!==4) return null;
  const points=source.map(point=>({
    x:Number(Array.isArray(point)?point[0]:point?.x),
    y:Number(Array.isArray(point)?point[1]:point?.y),
  }));
  if(!points.every(point=>Number.isFinite(point.x)&&Number.isFinite(point.y))) return null;
  const normalized=points.every(
    point=>point.x>=-.08&&point.x<=1.08&&point.y>=-.08&&point.y<=1.08
  );
  const frame=visionFrameDimensions(window.__rareiqVisionTelemetry||{});
  if(!normalized&&(!frame.width||!frame.height)) return null;
  const mapped=points.map(point=>({
    x:normalized?Math.max(0,Math.min(1,point.x)):point.x/frame.width,
    y:normalized?Math.max(0,Math.min(1,point.y)):point.y/frame.height,
  }));
  return mapped.every(point=>point.x>=0&&point.x<=1&&point.y>=0&&point.y<=1)
    ? mapped
    : null;
}

function cardFocusSegmentsIntersect(a,b,c,d){
  const orientation=(p,q,r)=>
    (q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x);
  const abC=orientation(a,b,c);
  const abD=orientation(a,b,d);
  const cdA=orientation(c,d,a);
  const cdB=orientation(c,d,b);
  return abC*abD<0&&cdA*cdB<0;
}

function cardFocusGeometryQuality(points,vision={}){
  /*
   * Frontend-only focus gate. Trading cards are portrait rectangles, so the
   * accepted polygon is deliberately conservative: width/height .58-.84,
   * bounds no wider than 56% or taller than 90% of frame, and polygon area no
   * larger than 56% of the configured scan zone. Recognition still receives
   * the untouched backend geometry.
   */
  if(!Array.isArray(points)||points.length!==4){
    return {valid:false,reason:"missing-corners"};
  }
  if(
    cardFocusSegmentsIntersect(points[0],points[1],points[2],points[3])||
    cardFocusSegmentsIntersect(points[1],points[2],points[3],points[0])
  ){
    return {valid:false,reason:"self-intersecting"};
  }
  const cross=points.map((point,index)=>{
    const next=points[(index+1)%4];
    const after=points[(index+2)%4];
    return (next.x-point.x)*(after.y-next.y)-(next.y-point.y)*(after.x-next.x);
  });
  if(cross.some(value=>Math.abs(value)<.0005)||!(cross.every(value=>value>0)||cross.every(value=>value<0))){
    return {valid:false,reason:"corner-order"};
  }
  const distance=(left,right)=>Math.hypot(right.x-left.x,right.y-left.y);
  const width=(distance(points[0],points[1])+distance(points[3],points[2]))/2;
  const height=(distance(points[1],points[2])+distance(points[0],points[3]))/2;
  const aspect=height?width/height:0;
  const left=Math.min(...points.map(point=>point.x));
  const right=Math.max(...points.map(point=>point.x));
  const top=Math.min(...points.map(point=>point.y));
  const bottom=Math.max(...points.map(point=>point.y));
  const boundsWidth=right-left;
  const boundsHeight=bottom-top;
  const area=Math.abs(points.reduce((sum,point,index)=>{
    const next=points[(index+1)%4];
    return sum+point.x*next.y-next.x*point.y;
  },0)/2);
  const scan=vision?.scan_zone;
  const scanArea=scan
    ? Math.max(.0001,(Number(scan.right)-Number(scan.left))*(Number(scan.bottom)-Number(scan.top)))
    : 1;
  if(aspect<.58||aspect>.84) return {valid:false,reason:"implausible-aspect",aspect};
  if(boundsWidth>.56||boundsHeight>.9) return {valid:false,reason:"implausible-bounds",aspect};
  if(area<.025||area/scanArea>.56) return {valid:false,reason:"implausible-area",aspect};
  return {valid:true,reason:"valid",aspect,area,boundsWidth,boundsHeight};
}

function clearCardFocusGeometry(){
  secondaryFocusGeometry=null;
  lastValidCardFocusGeometry=null;
  lastValidCardFocusAt=0;
  lastCardFocusGeometryReason="unavailable";
}

function visionFrameDimensions(vision={}){
  const actual=vision?.actual_resolution||vision?.frame_shape||[];
  return {
    width:Number(actual[0]||$("cameraFeed")?.naturalWidth||0),
    height:Number(actual[1]||$("cameraFeed")?.naturalHeight||0),
  };
}

function normalizedCardFocusGeometry(vision={}){
  const cornerSource=
    normalizedCardFocusPoints(vision?.card_corners)||
    normalizedCardFocusPoints(vision?.perspective_corners)||
    normalizedCardFocusPoints(vision?.polygon);
  const quality=cornerSource
    ? cardFocusGeometryQuality(cornerSource,vision)
    : {valid:false,reason:"missing-corners"};
  const perspective=quality.valid?cornerSource:null;
  if(cornerSource&&!quality.valid){
    lastCardFocusGeometryReason=quality.reason;
    return null;
  }
  let zone=null;
  if(perspective?.length===4){
    zone={
      left:Math.min(...perspective.map(point=>point.x)),
      top:Math.min(...perspective.map(point=>point.y)),
      right:Math.max(...perspective.map(point=>point.x)),
      bottom:Math.max(...perspective.map(point=>point.y)),
    };
  }else if(vision?.stable===true){
    zone=vision?.detected_card_bounds||vision?.card_bounds||null;
  }
  if(!zone) return null;
  const left=Number(zone.left);
  const top=Number(zone.top);
  const right=Number(zone.right);
  const bottom=Number(zone.bottom);
  if(
    ![left,top,right,bottom].every(Number.isFinite)||
    right<=left||bottom<=top||
    left<0||top<0||right>1||bottom>1
  ) return null;
  const geometry={
    left,top,right,bottom,
    centerX:(left+right)/2,
    centerY:(top+bottom)/2,
    width:right-left,
    height:bottom-top,
    perspective,
  };
  lastValidCardFocusGeometry={...geometry};
  lastValidCardFocusAt=Date.now();
  lastCardFocusGeometryReason="valid";
  return geometry;
}

function smoothedCardFocusGeometry(next,locked=false){
  if(!next){
    if(
      lastValidCardFocusGeometry&&
      Date.now()-lastValidCardFocusAt<=CARD_FOCUS_LAST_VALID_MS
    ){
      return {...lastValidCardFocusGeometry,retained:true};
    }
    return null;
  }
  if(!secondaryFocusGeometry||locked){
    secondaryFocusGeometry={...next};
    return secondaryFocusGeometry;
  }
  const blend=.24;
  secondaryFocusGeometry={
    ...next,
    left:secondaryFocusGeometry.left+(next.left-secondaryFocusGeometry.left)*blend,
    top:secondaryFocusGeometry.top+(next.top-secondaryFocusGeometry.top)*blend,
    right:secondaryFocusGeometry.right+(next.right-secondaryFocusGeometry.right)*blend,
    bottom:secondaryFocusGeometry.bottom+(next.bottom-secondaryFocusGeometry.bottom)*blend,
    centerX:secondaryFocusGeometry.centerX+(next.centerX-secondaryFocusGeometry.centerX)*blend,
    centerY:secondaryFocusGeometry.centerY+(next.centerY-secondaryFocusGeometry.centerY)*blend,
    width:secondaryFocusGeometry.width+(next.width-secondaryFocusGeometry.width)*blend,
    height:secondaryFocusGeometry.height+(next.height-secondaryFocusGeometry.height)*blend,
  };
  return secondaryFocusGeometry;
}

function applySecondaryCardFocusGeometry(image,geometry){
  const content=image?.parentElement;
  const frame=visionFrameDimensions(window.__rareiqVisionTelemetry||{});
  if(!image||!content||!geometry||!frame.width||!frame.height) return false;
  const bayWidth=content.clientWidth;
  const bayHeight=content.clientHeight;
  if(!bayWidth||!bayHeight) return false;
  const containScale=Math.min(bayWidth/frame.width,bayHeight/frame.height);
  const renderedWidth=frame.width*containScale;
  const renderedHeight=frame.height*containScale;
  const letterboxX=(bayWidth-renderedWidth)/2;
  const letterboxY=(bayHeight-renderedHeight)/2;
  const cropWidth=renderedWidth*geometry.width;
  const cropHeight=renderedHeight*geometry.height;
  const cropCenterX=letterboxX+renderedWidth*geometry.centerX;
  const cropCenterY=letterboxY+renderedHeight*geometry.centerY;
  const focusScale=Math.max(1,Math.min(8,Math.min(
    bayWidth*.92/cropWidth,
    bayHeight*.92/cropHeight
  )));
  const translateX=bayWidth/2-cropCenterX*focusScale;
  const translateY=bayHeight/2-cropCenterY*focusScale;
  image.style.setProperty("--secondary-focus-scale",String(focusScale));
  image.style.setProperty("--secondary-focus-translate-x",`${translateX}px`);
  image.style.setProperty("--secondary-focus-translate-y",`${translateY}px`);
  const polygon=(geometry.perspective||[
    {x:geometry.left,y:geometry.top},{x:geometry.right,y:geometry.top},
    {x:geometry.right,y:geometry.bottom},{x:geometry.left,y:geometry.bottom},
  ]).map(point=>`${letterboxX+point.x*renderedWidth}px ${letterboxY+point.y*renderedHeight}px`).join(",");
  image.style.clipPath=`polygon(${polygon})`;
  image.dataset.focusPresentation="tight-card-crop";
  image.dataset.perspectiveCorrection=geometry.perspective?"polygon":"bounds";
  return true;
}

function applyStudioXViewerPresentation(
  context=window.__rareiqCardContext||null,
  vision=window.__rareiqVisionTelemetry||{}
){
  const workspace=document.querySelector(".camera-workspace");
  const feed=$("cameraFeed");
  if(!workspace||!feed) return;
  const geometry=smoothedCardFocusGeometry(
    normalizedCardFocusGeometry(vision),
    context?.verified===true
  );
  const requested=studioXPreferences.viewerMode;
  const stableLock=Boolean(
    context?.verified&&
    context?.presentation?.key==="exact-match"
  );
  const wantsFocus=
    requested==="card-focus"||
    (requested==="auto"&&stableLock);
  const focusAvailable=Boolean(wantsFocus&&geometry);
  const effectiveMode=focusAvailable?"card-focus":"full-frame";
  const focusScale=focusAvailable
    ? Math.max(1,Math.min(3,Math.min(.88/geometry.width,.88/geometry.height)))
    : 1;
  const combinedScale=Math.max(
    .8,
    Math.min(4,focusScale*studioXPreferences.previewZoom)
  );
  const originX=focusAvailable?geometry.centerX*100:50;
  const originY=focusAvailable?geometry.centerY*100:50;
  workspace.dataset.viewerMode=requested;
  workspace.dataset.viewerEffectiveMode=effectiveMode;
  workspace.dataset.focusGeometry=geometry?"available":"unavailable";
  workspace.dataset.perspectiveGeometry=geometry?.perspective?"available":"unavailable";
  workspace.style.setProperty("--studiox-preview-scale",String(combinedScale));
  workspace.style.setProperty("--studiox-preview-origin-x",`${originX}%`);
  workspace.style.setProperty("--studiox-preview-origin-y",`${originY}%`);
  if($("viewerModeSelect")) $("viewerModeSelect").value=requested;
  if($("viewerZoomValue")){
    $("viewerZoomValue").textContent=`${Math.round(studioXPreferences.previewZoom*100)}%`;
  }
  if($("viewerModeStatus")){
    $("viewerModeStatus").textContent=
      requested==="card-focus"&&!geometry
        ? "Card focus unavailable — showing full frame"
        : requested==="auto"
        ? stableLock&&geometry
          ? "Auto · card focus"
          : "Auto · full frame"
        : effectiveMode==="card-focus"
        ? "Card focus"
        : "Full frame";
  }
  updateViewerInspectionHeader(context);
}

function setStudioXViewerMode(mode){
  studioXPreferences=normalizeStudioXPreferences({
    ...studioXPreferences,
    viewerMode:mode,
  });
  saveStudioXPreferences();
  applyStudioXViewerPresentation();
}

function setStudioXPreviewZoom(value){
  studioXPreferences=normalizeStudioXPreferences({
    ...studioXPreferences,
    previewZoom:value,
  });
  saveStudioXPreferences();
  applyStudioXViewerPresentation();
}

function adjustStudioXPreviewZoom(delta){
  setStudioXPreviewZoom(studioXPreferences.previewZoom+delta);
}

function resetStudioXPreviewZoom(){
  setStudioXPreviewZoom(1);
}

function isAuthoritativelyVerified(snapshot={}){
  const state=String(snapshot?.verification_state||"").toUpperCase();
  return Boolean(
    snapshot?.recognition_locked===true&&
    state==="VERIFIED"&&
    snapshot?.result_current!==false
  );
}

function isAuthoritativeSetLockedCard(card={}){
  const signals=card?.signals||{};
  return Boolean(
    card?.set_locked_identity_agreement===true&&
    card?.retrieval_only!==true&&
    Number(signals.collector_number||0)>=1&&
    Number(card?.visual_similarity??card?.visual_score??card?.score??0)>=.72
  );
}

function recognitionCandidateConfidence(card={},fallback=0){
  const fused=normalize(card?.fused_score??card?.score??card?.confidence??fallback);
  if(!isAuthoritativeSetLockedCard(card)) return fused;
  return Math.max(
    fused,
    normalize(card?.visual_similarity??card?.visual_score??card?.artwork_score??0)
  );
}

function deriveRecognitionPresentation(snapshot={},card=null,candidates=[]){
  const verificationState=String(snapshot?.verification_state||"").toUpperCase();
  const phase=verificationState==="SET_MISMATCH"
    ? verificationState
    : String(
        snapshot?.continuous_state||
        snapshot?.phase||
        snapshot?.status||
        snapshot?.verification_state||
        "IDLE"
      ).toUpperCase();
  const confidence=recognitionCandidateConfidence(
    card||{},
    snapshot?.overall_confidence??snapshot?.confidence??0
  );
  const verified=Boolean(
    isAuthoritativelyVerified(snapshot)&&card&&(
      card.verification_strong===true||
      isAuthoritativeSetLockedCard(card)||
      ["database","live_catalog","catalog"].includes(
        String(card.source||"").toLowerCase()
      )
    )
  );
  const hasCandidate=Boolean(card||candidates.length);
  const cardDetected=Boolean(
    snapshot?.card_present===true||
    snapshot?.vision?.visible===true||
    snapshot?.vision?.vision?.visible===true
  );
  if(phase==="SET_MISMATCH"){
    const mismatch=snapshot?.set_mismatch||{};
    const locked=mismatch.locked_set_name||snapshot?.active_set?.active_set?.name||"selected set";
    const observed=[mismatch.observed_language,mismatch.observed_collector_number].filter(Boolean).join(" · ");
    return {
      key:"set-mismatch",
      state:"warning",
      title:"WRONG SET SELECTED",
      detail:`This card${observed?` (${observed})`:""} does not belong to ${locked}. Choose the correct set or switch Set to Auto.`,
      placeholderTitle:"Set Mismatch",
      confidence,
    };
  }
  if(["ERROR","FAILED"].includes(phase)){
    return {key:"error",state:"error",title:"ERROR",detail:"Recognition is temporarily unavailable.",placeholderTitle:"Recognition Unavailable",confidence};
  }
  if(verified){
    return {key:"exact-match",state:"matched",title:"EXACT MATCH",detail:"Identity verified against the active catalog.",placeholderTitle:"Exact Match",confidence};
  }
  if(
    hasCandidate&&
    ["REVIEW","REVIEW_NEEDED","LOW_CONFIDENCE"].includes(phase)
  ){
    return {key:"review-needed",state:"searching",title:"REVIEW NEEDED",detail:"Candidate evidence needs operator review.",placeholderTitle:"Review Needed",confidence};
  }
  if(["VERIFYING","VERIFICATION","RECOGNIZING"].includes(phase)){
    return {key:"verifying",state:"searching",title:"VERIFYING",detail:"Confirming the strongest identity across recognition signals.",placeholderTitle:"Verifying Card",confidence};
  }
  if(candidates.length){
    return {key:"candidate-found",state:"searching",title:"CANDIDATE FOUND",detail:"RareIQ found reference evidence and is selecting the strongest identity.",placeholderTitle:"Candidate Found",confidence};
  }
  if(["DETECTING","CARD_DETECTED","ACQUIRING"].includes(phase)&&cardDetected){
    return {key:"detecting",state:"searching",title:"DETECTING",detail:"Card geometry is being stabilized inside the scan zone.",placeholderTitle:"Detecting Card",confidence};
  }
  if(cardDetected||!["IDLE","EMPTY","LOST"].includes(phase)){
    return {key:"scanning",state:"searching",title:"SCANNING",detail:"Analyzing artwork, text, and collector data.",placeholderTitle:"Scanning Card",confidence};
  }
  return {key:"ready",state:"idle",title:"READY",detail:"Place a card inside the scan zone.",placeholderTitle:"Ready for Card",confidence:0};
}

function stabilizeRecognitionPresentation(presentation,snapshot={}){
  const next=presentation||{key:"ready"};
  const present=snapshot?.card_present===true||snapshot?.vision?.visible===true||snapshot?.vision?.vision?.visible===true;
  const now=Date.now();
  const rank={detecting:1,scanning:2,"candidate-found":3,verifying:4};
  const previous=recognitionPresentationMemory.presentation;
  const canSmooth=present&&previous&&rank[previous.key]&&rank[next.key];
  const briefRegression=canSmooth&&rank[next.key]<rank[previous.key]&&now-recognitionPresentationMemory.changedAt<480;
  if(briefRegression) return {...previous,confidence:Math.max(normalize(previous.confidence||0),normalize(next.confidence||0))};
  if(next.key!==recognitionPresentationMemory.key){
    recognitionPresentationMemory={key:next.key,presentation:next,changedAt:now};
  }else{
    recognitionPresentationMemory.presentation=next;
  }
  if(!present||["ready","exact-match","review-needed","error"].includes(next.key)){
    recognitionPresentationMemory={key:next.key,presentation:next,changedAt:now};
  }
  return next;
}

async function loadRecognition(){
  try{
    const result=await api(`/api/recognition-state?t=${Date.now()}`);
    const currentCardResult={card:result?.current_card||null};

    const snapshot =
      result?.recognition_state ||
      result?.state ||
      result?.snapshot ||
      result ||
      {};

    if(result?.provenance?.available===true){
      AUTO_SCREENSHOT_BACKEND_AVAILABLE=true;
      autoScreenshotBackendStatus=result.provenance.status||autoScreenshotBackendStatus;
      renderAutoScreenshotConfig(result.provenance.settings||loadAutoScreenshotConfig());
    }

    const serverSessionId=String(
      result?.server_session_id ??
      snapshot?.server_session_id ??
      ""
    );
    if(serverSessionId && serverSessionId!==currentServerSessionId){
      const hadPreviousSession=currentServerSessionId!==null;
      currentServerSessionId=serverSessionId;
      newestRecognitionGeneration=-1;
      newestRecognitionRevision=-1;
      resetRecognitionPresentation(
        hadPreviousSession ? "server_session_changed" : "server_session_initialized"
      );
      setUI4InspectorView("current",false);
    }

    const generation=Number(snapshot?.generation ?? 0);
    const revision=Number(snapshot?.revision ?? 0);
    if(
      generation < newestRecognitionGeneration ||
      (generation === newestRecognitionGeneration && revision < newestRecognitionRevision)
    ){
      return;
    }
    newestRecognitionGeneration=Math.max(newestRecognitionGeneration,generation);
    newestRecognitionRevision=revision;

    if(cameraConnectionAvailable===false){
      setCameraDisconnectedPresentation(
        cameraConnectionFailure?.camera||selectedCamera,
        cameraConnectionFailure?.error||"Camera is disconnected"
      );
      return;
    }

    const raw =
      snapshot?.raw_recognition ||
      snapshot?.payload ||
      snapshot?.latest ||
      {};

    const rawVerifiedCurrent=Boolean(
      raw?.recognition_locked===true&&
      String(raw?.verification_state||"").toUpperCase()==="VERIFIED"&&
      Number(raw?.generation??-1)===generation
    );

    const candidates = rawVerifiedCurrent&&Array.isArray(raw?.candidates)
      ? raw.candidates
      : Array.isArray(snapshot?.candidates)
      ? snapshot.candidates
      : Array.isArray(raw?.candidates)
      ? raw.candidates
      : [];

    const identityAgrees = candidate => {
      const signals = candidate?.signals || {};
      return Number(signals.ocr_name || 0) >= 0.75 ||
        Number(signals.collector_number || 0) >= 1;
    };

    const isPresentableCandidate = candidate => {
      if(!candidate || candidate.retrieval_only === true) return false;
      const source=String(candidate.source||"").toLowerCase();
      const safeSetLockedProvisional =
        source === "global_visual_index" &&
        candidate.provisional === true &&
        candidate.set_locked_identity_agreement === true &&
        identityAgrees(candidate);
      if(source === "ocr_provisional") return false;
      if(source === "global_visual_index" && !safeSetLockedProvisional) return false;
      return safeSetLockedProvisional ||
        identityAgrees(candidate) ||
        candidate.verification_strong === true ||
        candidate.artwork_verification_strong === true;
    };

    const realIdentityCandidate =
      candidates.find(
        candidate =>
          candidate &&
          candidate.source !== "ocr_provisional" &&
          candidate.retrieval_only !== true &&
          ["database", "live_catalog", "catalog"].includes(
            String(candidate.source || "").toLowerCase()
          ) &&
          identityAgrees(candidate) &&
          (
            candidate.image_path ||
            candidate.reference_image ||
            candidate.local_image ||
            candidate.reference_image_url
          )
      ) || null;

    const verifiedVisualCandidate =
      candidates.find(
        candidate =>
          candidate &&
          isPresentableCandidate(candidate) &&
          candidate.verification_strong === true &&
          identityAgrees(candidate)
      ) || null;

    const authoritativeSetLockedCandidate =
      candidates.find(candidate=>isAuthoritativeSetLockedCard(candidate))||null;

    const presentablePrimary = isPresentableCandidate(snapshot.primary_candidate)
      ? snapshot.primary_candidate
      : null;
    const presentableProvisional = isPresentableCandidate(snapshot.provisional_candidate)
      ? snapshot.provisional_candidate
      : null;
    const presentableCandidate =
      candidates.find(candidate => isPresentableCandidate(candidate)) || null;

    const canonicalCurrent=currentCardResult?.card;
    const canonicalVerified=Boolean(
      canonicalCurrent &&
      canonicalCurrent.recognition_locked === true &&
      String(canonicalCurrent.verification_state||"").toUpperCase() === "VERIFIED" &&
      (snapshot?.result_current !== false||rawVerifiedCurrent)
    );
    const canonicalCard=canonicalVerified?{
      ...canonicalCurrent,
      id:canonicalCurrent.card_id||canonicalCurrent.id,
      name:canonicalCurrent.card_name||canonicalCurrent.name,
      score:canonicalCurrent.confidence,
      fused_score:canonicalCurrent.confidence,
    }:null;
    const collectorIdentityKey=value=>String(value||"").trim().toLowerCase().replaceAll(" ","").split("/").map(part=>String(Number(part)||0)).join("/");
    const observedCollector=collectorIdentityKey(
      snapshot?.ocr_collector_number||snapshot?.collector_number
    );
    const canonicalCollector=collectorIdentityKey(
      canonicalCurrent?.collector_number
    );
    const canonicalPreview=canonicalCurrent&&observedCollector&&canonicalCollector===observedCollector&&(
      canonicalCurrent.card_id||canonicalCurrent.card_name
    )&&(
      canonicalCurrent.reference_image_url||canonicalCurrent.image_url
    )?{
      ...canonicalCurrent,
      id:canonicalCurrent.card_id||canonicalCurrent.id,
      name:canonicalCurrent.card_name||canonicalCurrent.name,
      score:canonicalCurrent.confidence,
      fused_score:canonicalCurrent.confidence,
      provisional:true,
      canonical_preview:true,
    }:null;

    let card =
      authoritativeSetLockedCandidate ||
      canonicalCard ||
      canonicalPreview ||
      verifiedVisualCandidate ||
      realIdentityCandidate ||
      presentablePrimary ||
      presentableProvisional ||
      presentableCandidate ||
      null;

    const authoritativeVerificationState=String(
      snapshot?.verification_state||""
    ).toUpperCase();
    const phase = authoritativeVerificationState==="SET_MISMATCH"
      ? authoritativeVerificationState
      : String(
          snapshot?.continuous_state ||
          snapshot?.phase ||
          raw?.status ||
          snapshot?.verification_state ||
          "IDLE"
        ).toUpperCase();
    if(!card&&phase==="SET_MISMATCH"){
      const mismatch=snapshot?.set_mismatch||{};
      const generation=Number(snapshot?.generation||raw?.generation||Date.now());
      card={
        id:`set-mismatch:${generation}`,
        name:"Card outside selected set",
        collector_number:mismatch.observed_collector_number||snapshot?.collector_number||null,
        language:mismatch.observed_language||snapshot?.language||null,
        reference_image_url:`/api/camera/crop.jpg?generation=${generation}`,
        provisional:true,
        set_mismatch:true,
      };
    }
    const clearInspector =
      ["EMPTY", "CHANGING"].includes(phase) ||
      (phase === "LOST" && !snapshot?.card_present);

    const hadVisibleCard = Boolean(
      previousCardId &&
      $("inspectorMain")?.style.display !== "none"
    );


    const missingCurrentCard =
      !card &&
      !candidates.length;

    if(
      hadVisibleCard &&
      (
        clearInspector ||
        missingCurrentCard
      )
    ){
      return;
    }

    if (clearInspector) {
      snapshot.primary_candidate = null;
      snapshot.provisional_candidate = null;
      candidates.length = 0;
      card = null;

      resetRecognitionPresentation("backend_empty");
      setRecognitionState("idle", "Waiting for a card.");

      setCopilot(
        "STANDBY",
        "Place a card in the scan zone. RareIQ will identify, verify, and explain what it finds."
      );

      return;
    }

    const confidence = recognitionCandidateConfidence(
      card||{},
      (
        card === snapshot?.primary_candidate
          ? snapshot?.overall_confidence ?? snapshot?.confidence
          : null
      ) ?? raw?.fused_score ?? raw?.confidence ?? 0
    );

      const locked = Boolean(
        snapshot?.recognition_locked ||
        raw?.recognition_locked
      );

      const hasCandidate = Boolean(
        card ||
        snapshot?.provisional_candidate ||
        candidates.length
      );

      const verified = Boolean(
        canonicalVerified || (
        (isAuthoritativelyVerified(snapshot)||rawVerifiedCurrent)&&(
          authoritativeSetLockedCandidate ||
          realIdentityCandidate ||
          verifiedVisualCandidate
        ))
      );

      const provisionalName=String(
        card?.english_name||card?.printed_name||card?.name||""
      );
      const provisionalLooksUnidentified=
        !verified&&(
          !provisionalName||
          provisionalName.length>70||
          provisionalName.includes("-Set-List-")||
          provisionalName.includes("-Pokemon-")||
          provisionalName.includes("-Pokipair-")||
          /\.(jpg|jpeg|png|webp|avif)$/i.test(provisionalName)
        );
      if(hadVisibleCard&&provisionalLooksUnidentified){
        return;
      }

    const presentationSnapshot=rawVerifiedCurrent?{
      ...snapshot,
      recognition_locked:true,
      verification_state:"VERIFIED",
      result_current:true,
      status:"VERIFIED",
      phase:"VERIFIED",
    }:{...snapshot,status:phase};
    const presentation=stabilizeRecognitionPresentation(deriveRecognitionPresentation(
      presentationSnapshot,
      card,
      candidates
    ),snapshot);

    applyRecognitionPresentation(presentation);

    if(phase === "CHANGING"){
      setCopilot("CHANGING","RareIQ invalidated the previous result and is acquiring the replacement card.");
    }else if(phase === "RECOGNIZING"){
      setCopilot("RECOGNIZING","RareIQ is processing the newest card generation.");
    }else if(verified && card){
      setCopilot(
        "VERIFIED",
        `RareIQ verified <b>${
          card.name ||
          card.english_name ||
          card.printed_name ||
          "this card"
        }</b> at ${Math.round(confidence*100)}% confidence.`
      );
    }else if(hasCandidate){
      setCopilot(
        "ANALYZING",
        `RareIQ found reference evidence and is verifying the strongest candidate.`
      );
    }else if(phase !== "IDLE"){
      setCopilot(
        "ANALYZING",
        `RareIQ is <b>${phase.replaceAll("_"," ").toLowerCase()}</b>. Visual, OCR, and database signals are being fused.`
      );
    }else{
      updateConfidenceRing(0);

      setCopilot(
        "STANDBY",
        "Place a card in the scan zone. RareIQ will identify, verify, and explain what it finds."
      );
    }

    const uiPayload = {
      ...raw,
      ...snapshot,
      status: phase,
      candidates,
      card,
      confidence,
      fused_score: confidence,
      pipeline_stages:
        snapshot?.pipeline_stages ||
        raw?.pipeline_stages ||
        [],
      latency_ms:
        snapshot?.stage_timings?.total_ms ??
        raw?.latency_ms ??
        0,
    };

    setScanState(
      uiPayload,
      card,
      confidence
    );

    const vision =
      snapshot?.artwork_index?.score ??
      card?.visual_score ??
      card?.artwork_score ??
      raw?.visual_score ??
      raw?.artwork_score ??
      confidence;

    const collectorOcrEvidence=Boolean(
      snapshot?.collector_ocr?.diagnostics?.some?.(diagnostic=>
        diagnostic?.variants?.some?.(variant=>variant?.collector_number)
      )
    );
    const ocr =
      card?.ocr_score ??
      raw?.ocr_score ??
      (snapshot?.ocr_collector_number||snapshot?.collector_number
        ? normalize(snapshot?.ocr_confidence||snapshot?.confidence||1)
        : collectorOcrEvidence ? 1 : 0);

    const collector =
      card?.collector_score ??
      raw?.collector_score ??
      ((snapshot?.ocr_collector_number||snapshot?.collector_number||card?.collector_number) ? 1 : 0);

    setSignal("vision",vision);
    setSignal("ocr",ocr);
    setSignal("collector",collector);
    setSignal("fusion",confidence);

    const empty = $("inspectorEmpty");
    const main = $("inspectorMain");

    if(card && !clearInspector){
      if(empty) empty.style.display="none";
      if(main) main.style.display="grid";

      const cardId =
        card.id ||
        `${card.set_id||""}:${card.collector_number||""}:${
          card.name ||
          card.english_name ||
          card.printed_name ||
          ""
        }`;

      const rawCardName = String(
        card.english_name ||
        card.printed_name ||
        card.name ||
        ""
      ).trim();

      const setId = String(
        card.set_id ||
        card.set_name ||""
      ).trim();

      const collectorNumber = String(
        card.collector_number ||
        ""
      ).trim();

      const looksLikeFilename =
        rawCardName.length > 70 ||
        rawCardName.includes("-Set-List-") ||
        rawCardName.includes("-Pokemon-") ||
        rawCardName.includes("-Pokipair-") ||
        rawCardName.includes("-Store-") ||
        /\.(jpg|jpeg|png|webp|avif)$/i.test(
          rawCardName
        );

      $("cardName").textContent =
        looksLikeFilename || !rawCardName
          ? [
              "Unidentified",
              setId,
              collectorNumber
                ? `Card ${collectorNumber}`
                : "Card"
            ]
              .filter(Boolean)
              .join(" ")
          : rawCardName;

      $("cardMeta").textContent = card.set_mismatch
        ? "Live card crop  |  Select the correct set or switch Set to Auto"
        : verified
        ? [
            card.set_name,
            card.collector_number || snapshot?.collector_number,
            card.language || snapshot?.language,
            card.rarity
          ].filter(Boolean).join("  |  ")
        : "Candidate only  |  Exact version unresolved";
      renderIdentityVerdictBadge(presentation,verified);

      const rawValue = Number(
        card.market_price ||
        card.price ||
        0
      );

      const psa10 = Number(
        card.psa10_price ||
        0
      );

      const population = Number(
        card.population ||
        card.psa10_population ||
        0
      );

      $("cardValue").textContent =
        !verified
          ? "WAITING FOR VERIFIED IDENTITY"
          : rawValue > 0
          ? `$${rawValue.toFixed(2)}`
          : "VALUE PENDING";

      $("rawValue").textContent =
        rawValue > 0
          ? `$${rawValue.toFixed(2)}`
          : "--";

      $("psaValue").textContent =
        psa10 > 0
          ? `$${psa10.toFixed(2)}`
          : "--";

      $("populationValue").textContent =
        population > 0
          ? String(population)
          : "--";

      $("cardStatus").textContent=presentation.title;

      if(verified||card.set_mismatch){
        renderExtendedCardData(card,snapshot,confidence,verified);
      }else{
        resetExtendedCardData();
        renderProvisionalIdentityData(card,snapshot);
      }

      const localImage =
        card.image_path ||
        card.reference_image ||
        card.local_image ||
        "";

      const imageSources = [
        card.reference_image_url,
        card.image_url,
        localImage
          ? "/api/reference-image?path=" + encodeURIComponent(String(localImage))
          : "",
      ].filter((source,index,items)=>source&&items.indexOf(source)===index);

      if(imageSources.length){
        const source = String(imageSources[0]).replaceAll("\\","/");
        $("cardArt").innerHTML =
          `<img src="${source}" alt="${verified ? "Verified card reference" : card.set_mismatch ? "Live card crop" : "Provisional candidate reference"}">`;
        const imageElement=$("cardArt").querySelector("img");
        if(imageElement){imageElement.tabIndex=0;imageElement.setAttribute("role","button");imageElement.setAttribute("aria-label","Enlarge reference artwork")}
        let fallbackIndex=1;
        imageElement?.addEventListener("error",()=>{
          const fallback=imageSources[fallbackIndex++];
          if(fallback){
            imageElement.src=String(fallback).replaceAll("\\","/");
          }else{
            $("cardArt").replaceChildren();
            $("cardArt").classList.remove("is-provisional");
          }
        });
        $("cardArt").classList.toggle("is-provisional",!verified);
      }else{
        $("cardArt").replaceChildren();
        $("cardArt").classList.remove("is-provisional");
      }

      if(
        verified &&
        cardId &&
        cardId !== previousCardId
      ){
        sessionCards += 1;
        sessionAttempts += 1;
        sessionMatches += 1;
        sessionValue += rawValue;

        if(rawValue >= 100){
          sessionHits += 1;
        }

        updateSessionStats();

        addActivity(
          "Match Found",
          `${
            card.name ||
            card.english_name ||
            card.printed_name ||
            "Card"
          }  |  ${Math.round(confidence*100)}%`
        );

        notify(
          rawValue >= 100
            ? "High-Value Match"
            : "Match Found",
          `${
            card.name ||
            card.english_name ||
            card.printed_name ||
            "Card"
          }  |  ${Math.round(confidence*100)}%`,
          "success"
        );

        if(
          previousCardId &&
          rawValue >= 100
        ){
          triggerHit();
      }
    }else if(clearInspector){
      if(empty) empty.style.display="none";
      if(main) main.style.display="grid";
      $("cardName").textContent="Ready to Scan";
      $("cardMeta").textContent="";
      $("cardArt").innerHTML="";
      resetExtendedCardData();
      updateConfidenceRing(0);
    }

      if(cardId){
        previousCardId = cardId;
      }
    }else{
      if(empty) empty.style.display="none";
      if(main) main.style.display="grid";
      $("cardName").textContent="Verifying Card";
      $("cardMeta").textContent="Retrieval candidates hidden until identity evidence agrees";
      $("cardArt").replaceChildren();
      $("cardArt").classList.remove("is-provisional");
      $("cardStatus").textContent="VERIFYING";
      resetExtendedCardData();
      updateConfidenceRing(0);
    }

    renderPipeline(
      uiPayload.pipeline_stages,
      verified
    );

    updateSharedCardContext(
      deriveSharedCardContext(
        presentation,
        verified?card:provisionalIdentityCard(card),
        snapshot,
        candidates
      )
    );

    $("latencyValue").textContent =
      uiPayload.latency_ms
        ? `${Math.round(Number(uiPayload.latency_ms))} ms`
        : phase === "IDLE"
        ? "Idle"
        : "Active";

    const latencySummary =
      snapshot?.latency_summary || raw?.latency_summary || {};
    renderRecognitionLatencyTrace(snapshot,raw);
    const recognitionPath =
      snapshot?.recognition_path || raw?.recognition_path || null;
    const captureLatency = Number(
      snapshot?.capture_to_result_ms ??
      snapshot?.stage_timings?.capture_to_result_ms ??
      raw?.capture_to_result_ms
    );
    const p95Latency = Number(latencySummary?.p95_ms);
    const fastPathRate = Number(latencySummary?.fast_path_rate);
    $("recognitionPathValue").textContent = recognitionPath
      ? recognitionPath.toUpperCase()
      : phase === "IDLE" ? "Idle" : "Full";
    $("latencyP95Value").textContent = Number.isFinite(p95Latency)
      ? `${Math.round(p95Latency)} ms`
      : "—";
    $("captureLatencyValue").textContent = Number.isFinite(captureLatency)
      ? `${Math.round(captureLatency)} ms`
      : "—";
    $("fastPathRateValue").textContent = Number.isFinite(fastPathRate)
      ? `${Math.round(fastPathRate * 100)}%`
      : "—";

    $("cardsValue").textContent =
      String(
        snapshot?.session_cards ||
        raw?.session_cards ||
        0
      );

    $("hitsValue").textContent =
      String(
        snapshot?.session_hits ||
        raw?.session_hits ||
        0
      );

    window.__rareiqRecognitionPoll = {
      serverSessionId:currentServerSessionId,
      generation: snapshot?.generation ?? null,
      revision: snapshot?.revision ?? null,
      phase,
      candidateCount:
        candidates.length ||
        snapshot?.candidate_count ||
        0,
      updatedAt: Date.now(),
    };
  }catch(error){
    console.warn(
      "RareIQ recognition poll failed",
      error
    );

    setRecognitionState(
      "error",
      "Recognition state unavailable."
    );
  }
}


async function loadSystemHealth(){
  try{
    const result=await api("/api/system/health");
    const components=result.components||{};

    Object.entries(components).forEach(([name,component])=>{
      const card=document.querySelector(`[data-health="${name}"]`);
      if(!card) return;

      card.classList.toggle("healthy",Boolean(component.healthy));
      card.classList.toggle("error",!component.healthy);

      const state=card.querySelector("strong");
      const message=card.querySelector("p");
      if(state) state.textContent=String(component.state||"unknown").toUpperCase();
      if(message) message.textContent=component.message||"No status message.";
    });
  }catch{}
}

let serverConnectionState="connected";
let serverConnectionHideTimer=0;
function setServerConnectionState(state,detail=""){
  const banner=$("serverConnectionBanner");
  if(!banner)return;
  window.clearTimeout(serverConnectionHideTimer);
  const titles={offline:"DEVICE OFFLINE",unreachable:"RAREIQ UNREACHABLE",checking:"CHECKING CONNECTION",reconnected:"RAREIQ RECONNECTED",connected:"RAREIQ CONNECTED"};
  const defaults={offline:"Reconnect this device to the network, then retry.",unreachable:"This browser cannot reach the RareIQ server.",checking:"Trying the existing RareIQ server connection.",reconnected:"Live operator updates have resumed.",connected:"The live operator session is available."};
  serverConnectionState=state;
  banner.dataset.state=state;
  banner.hidden=state==="connected";
  setCardText("serverConnectionTitle",titles[state]||titles.unreachable);
  setCardText("serverConnectionDetail",detail||defaults[state]||defaults.unreachable);
  const retry=$("serverConnectionRetry");
  if(retry){retry.hidden=["connected","reconnected"].includes(state);retry.disabled=state==="checking"}
  syncMobileOperatorDeck();
  if(state==="reconnected")serverConnectionHideTimer=window.setTimeout(()=>setServerConnectionState("connected"),2400);
}

async function retryServerConnection(){
  setServerConnectionState("checking");
  try{
    await api("/api/boot/ping",{timeoutMs:5000,retries:0});
    setServerConnectionState("reconnected");
  }catch(error){
    setServerConnectionState(navigator.onLine===false?"offline":"unreachable",error.message||"");
  }
}

function initializeServerConnectionStatus(){
  $("serverConnectionRetry")?.addEventListener("click",retryServerConnection);
  window.addEventListener("offline",()=>setServerConnectionState("offline"));
  window.addEventListener("online",retryServerConnection);
  document.addEventListener("rareiq:api-error",event=>{
    if(event.detail?.error?.status)return;
    setServerConnectionState(navigator.onLine===false?"offline":"unreachable",event.detail?.error?.message||"");
  });
  document.addEventListener("rareiq:api-end",()=>{
    if(["offline","unreachable","checking"].includes(serverConnectionState))setServerConnectionState("reconnected");
  });
  if(navigator.onLine===false)setServerConnectionState("offline");
}

let foregroundRefreshInFlight=false;
async function refreshStudioXAfterForeground(){
  if(document.hidden===true||foregroundRefreshInFlight)return false;
  foregroundRefreshInFlight=true;
  try{
    await Promise.allSettled([
      loadRecognition(),
      loadCameraStatus({forceStream:false}),
      loadCameraManagerState(),
      loadSystemHealth(),
    ]);
    return true;
  }finally{
    foregroundRefreshInFlight=false;
  }
}

function initializeVisibilityAwareRefresh(){
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden!==true)refreshStudioXAfterForeground();
  });
}

let mobileWakeLock=null;
let mobileWakeLockRequested=false;
function mobileWakeLockSupported(){
  return typeof navigator.wakeLock?.request==="function";
}

function renderMobileWakeLockState(state="off",detail=""){
  const toggle=$("mobileWakeLockEnabled");
  const supported=mobileWakeLockSupported();
  if(toggle){toggle.disabled=!supported;toggle.checked=supported&&mobileWakeLockRequested}
  const defaults={off:"Off · enable for this operator session",active:"Active · screen will remain awake",paused:"Paused while Studio X is hidden",unsupported:"Unavailable in this browser",error:"Could not keep the screen awake"};
  const status=detail||defaults[supported?state:"unsupported"];
  setCardText("mobileWakeLockStatus",status);
  const deckToggle=$("mobileOperatorWakeLock");
  if(deckToggle){deckToggle.disabled=!supported;deckToggle.dataset.state=supported?state:"unsupported";deckToggle.setAttribute("aria-pressed",supported&&mobileWakeLockRequested?"true":"false");deckToggle.title=status}
  document.querySelector(".mobile-wake-lock")?.setAttribute("data-state",supported?state:"unsupported");
}

async function releaseMobileWakeLock(){
  const lock=mobileWakeLock;
  mobileWakeLock=null;
  if(lock&&!lock.released){
    try{await lock.release()}catch(_error){}
  }
  renderMobileWakeLockState(mobileWakeLockRequested?"paused":"off");
}

async function requestMobileWakeLock(){
  if(!mobileWakeLockRequested||!mobileWakeLockSupported()){
    renderMobileWakeLockState(mobileWakeLockSupported()?"off":"unsupported");
    return false;
  }
  if(document.hidden===true){renderMobileWakeLockState("paused");return false}
  try{
    mobileWakeLock=await navigator.wakeLock.request("screen");
    mobileWakeLock.addEventListener("release",()=>{
      mobileWakeLock=null;
      renderMobileWakeLockState(mobileWakeLockRequested?"paused":"off");
    },{once:true});
    renderMobileWakeLockState("active");
    return true;
  }catch(error){
    mobileWakeLockRequested=false;
    renderMobileWakeLockState("error",error.message||"");
    notify("Screen Awake Unavailable",error.message||"This browser denied the screen wake request.","error");
    return false;
  }
}

function initializeMobileWakeLock(){
  renderMobileWakeLockState(mobileWakeLockSupported()?"off":"unsupported");
  const setRequested=requested=>{mobileWakeLockRequested=requested===true;if(mobileWakeLockRequested)requestMobileWakeLock();else releaseMobileWakeLock()};
  $("mobileWakeLockEnabled")?.addEventListener("change",event=>setRequested(event.target.checked===true));
  $("mobileOperatorWakeLock")?.addEventListener("click",()=>setRequested(!mobileWakeLockRequested));
  document.addEventListener("visibilitychange",()=>{
    if(!mobileWakeLockRequested)return;
    if(document.hidden===true)releaseMobileWakeLock();else requestMobileWakeLock();
  });
}

let deferredStudioXInstallPrompt=null;
function studioXIsStandalone(){
  return window.matchMedia?.("(display-mode: standalone)")?.matches===true||navigator.standalone===true;
}

function renderStudioXInstallState(state="guidance",detail=""){
  const installed=studioXIsStandalone()||state==="installed";
  const installable=Boolean(deferredStudioXInstallPrompt)&&!installed;
  const panel=document.querySelector(".mobile-install-state");
  const button=$("mobileInstallButton");
  if(panel)panel.dataset.state=installed?"installed":state;
  if(button){button.disabled=!installable;button.textContent=installed?"Installed":"Install Studio X"}
  const defaults={guidance:"Use your browser menu to Add to Home Screen.",ready:"Native install is ready on this device.",accepted:"Install accepted · finishing setup.",dismissed:"Install dismissed · you can try again later.",installed:"Running as an installed Studio X app."};
  setCardText("mobileInstallStatus",detail||defaults[installed?"installed":state]||defaults.guidance);
}

async function installStudioXApp(){
  const prompt=deferredStudioXInstallPrompt;
  if(!prompt||studioXIsStandalone())return false;
  deferredStudioXInstallPrompt=null;
  try{
    await prompt.prompt();
    const choice=await prompt.userChoice;
    const accepted=choice?.outcome==="accepted";
    renderStudioXInstallState(accepted?"accepted":"dismissed");
    return accepted;
  }catch(error){
    renderStudioXInstallState("guidance",error.message||"");
    return false;
  }
}

function initializeStudioXInstallPrompt(){
  renderStudioXInstallState(studioXIsStandalone()?"installed":deferredStudioXInstallPrompt?"ready":"guidance");
  $("mobileInstallButton")?.addEventListener("click",installStudioXApp);
}

window.addEventListener("beforeinstallprompt",event=>{
  event.preventDefault();
  deferredStudioXInstallPrompt=event;
  renderStudioXInstallState("ready");
});
window.addEventListener("appinstalled",()=>{
  deferredStudioXInstallPrompt=null;
  renderStudioXInstallState("installed");
});

let mobileAccessUrl="";
function renderMobileAccessStatus(status={}){
  const panel=document.querySelector(".mobile-access-settings");
  const enabled=status.enabled===true;
  const urls=Array.isArray(status.lan_urls)?status.lan_urls.filter(value=>typeof value==="string"&&value.startsWith("http")):[];
  mobileAccessUrl=enabled&&urls.length?urls[0]:"";
  if(panel) panel.dataset.state=enabled?(mobileAccessUrl?"ready":"warning"):"local";
  setCardText("mobileAccessMode",enabled?"AUTHENTICATED LAN":"LOCAL ONLY");
  setCardText("mobileAccessPairing",enabled?(status.paired?"THIS DEVICE PAIRED":"PAIRING REQUIRED"):(status.token_configured?"READY · NOT ENABLED":"NOT CONFIGURED"));
  setCardText("mobileAccessSummary",enabled?"Remote control is protected by per-server pairing.":"This RareIQ process accepts connections from this computer only.");
  const addresses=$("mobileAccessAddresses");
  if(addresses){
    addresses.replaceChildren();
    if(mobileAccessUrl){
      urls.forEach(url=>{const code=document.createElement("code");code.textContent=url;addresses.append(code)});
    }else{
      const message=document.createElement("p");
      message.textContent=enabled?"No private LAN address is currently available.":"No mobile URL is published while RareIQ is in local-only mode.";
      addresses.append(message);
    }
  }
  const copy=$("mobileAccessCopy");
  if(copy) copy.disabled=!mobileAccessUrl;
  setCardText("mobileAccessGuidance",enabled?"Open the mobile URL on the same trusted network, then pair with the secret shown only by the server setup command.":"To prepare access safely, run: python tools/server_control.py mobile-setup (dry-run by default). No setting on this page changes the server binding.");
}
async function loadMobileAccessStatus(){
  const panel=document.querySelector(".mobile-access-settings");
  if(panel) panel.dataset.state="checking";
  try{
    renderMobileAccessStatus(await api("/api/remote-access/status"));
  }catch(error){
    if(panel) panel.dataset.state="error";
    setCardText("mobileAccessMode","UNAVAILABLE");
    setCardText("mobileAccessPairing","UNKNOWN");
    setCardText("mobileAccessSummary",error.message||"Remote access status could not be loaded.");
  }
}

async function copyMobileAccessUrl(){
  if(!mobileAccessUrl) return;
  try{
    await navigator.clipboard.writeText(mobileAccessUrl);
    notify("Mobile URL Copied",mobileAccessUrl,"success");
  }catch(error){
    notify("Copy Failed",error.message||String(error),"error");
  }
}

async function loadCameraManagerState(){
  try{
    const status=await api("/api/camera/status");
    const manager=status.manager||{};
    const node=$("cameraManagerState");
    if(node){
      node.textContent=[
        `STATE: ${String(manager.state||"unknown").toUpperCase()}`,
        `GENERATION: ${manager.generation??0}`,
        `CACHED DEVICES: ${manager.cached_devices??0}`,
        `RECOVERIES: ${manager.recovery_count??0}`,
        `MESSAGE: ${manager.message||"None"}`
      ].join("   |   ");
    }
  }catch{}
}

function openCameraPopout(){
  const width=Math.min(1280,window.screen.availWidth||1280);
  const height=Math.min(820,window.screen.availHeight||820);
  window.open(
    "/camera-popout",
    "rareiq-camera-popout",
    `popup=yes,width=${width},height=${height},resizable=yes,scrollbars=no`
  );
}

function openProgram(){
  window.open("/program","rareiq-program","width=1280,height=720");
}

async function maintenance(path,label){
  $("systemStatus").textContent=`${label} started...`;
  try{
    const result=await api(path,{method:"POST",body:"{}"});
    $("systemStatus").textContent=result.ok===false
      ? (result.error||`${label} failed.`)
      : `${label} queued.`;
  }catch{
    $("systemStatus").textContent=`${label} failed.`;
  }
}

const fetchLearnedCorrections=()=>api("/api/intelligence/corrections?limit=30");
const revokeLearnedCorrection=id=>api(`/api/intelligence/corrections/${encodeURIComponent(id)}`,{method:"DELETE"});
function setUI4DiagnosticsOpen(open){
  ui4DiagnosticsOpen=Boolean(open);
  const drawer=document.querySelector(".ui4-diagnostics-drawer");
  if(drawer){
    drawer.classList.toggle("open",ui4DiagnosticsOpen);
    drawer.setAttribute("aria-hidden",ui4DiagnosticsOpen?"false":"true");
  }
  const trigger=document.querySelector('[data-ui4-action="diagnostics"]');
  if(trigger) trigger.setAttribute("aria-expanded",ui4DiagnosticsOpen?"true":"false");
  if($("dockToggle")) $("dockToggle").textContent="Close";
}

function setUI4HealthOpen(open){
  ui4HealthOpen=Boolean(open);
  const popover=document.querySelector(".ui4-health-popover");
  if(popover){
    popover.classList.toggle("open",ui4HealthOpen);
    popover.setAttribute("aria-hidden",ui4HealthOpen?"false":"true");
  }
  const trigger=document.querySelector('[data-ui4-action="health"]');
  if(trigger) trigger.setAttribute("aria-expanded",ui4HealthOpen?"true":"false");
  if($("mobileOperatorStatus")) $("mobileOperatorStatus").setAttribute("aria-expanded",ui4HealthOpen?"true":"false");
}

function setUI4InspectorTab(name){
  ui4InspectorTab=name||"details";
  document.querySelectorAll("[data-inspector-tab]").forEach(button=>{
    const selected=button.dataset.inspectorTab===ui4InspectorTab;
    button.classList.toggle("active",selected);
    button.setAttribute("aria-selected",selected?"true":"false");
    button.tabIndex=selected?0:-1;
  });
  document.querySelectorAll("[data-inspector-panel]").forEach(panel=>{
    panel.hidden=panel.dataset.inspectorPanel!==ui4InspectorTab;
  });
}

function resetUI4PresentationSurfaces(){
  setUI4DiagnosticsOpen(false);
  setUI4HealthOpen(false);
  setUI4InspectorTab("details");
}

function recentScanConfidence(value){
  const numeric=Number(value||0);
  return Math.round(Math.max(0,Math.min(100,numeric<=1?numeric*100:numeric)));
}

let referenceCompareZoom=1;
let referenceSelectedCandidate=-1;
let referenceSelectedCatalogCandidate=null;
function setReferenceCompareZoom(value){referenceCompareZoom=Math.max(0.75,Math.min(3,Number(value)||1));if($("referenceCompareStage"))$("referenceCompareStage").style.setProperty("--compare-zoom",String(referenceCompareZoom));setCardText("referenceZoomValue",`${Math.round(referenceCompareZoom*100)}%`)}
function setReferenceCompareMode(mode="side"){const overlay=$("referenceLightbox");if(!overlay)return;overlay.dataset.compareMode=mode;$("referenceSideBySide")?.classList.toggle("active",mode==="side");$("referenceOverlayMode")?.classList.toggle("active",mode==="overlay");if($("referenceBlendControl"))$("referenceBlendControl").hidden=mode!=="overlay"}
function syncReferenceVerification(){const confirmed=value=>String(value||"").toLowerCase().includes("confirm"),confidence=Number(String($("confidenceRingValue")?.textContent||"0").replace("%","")),card=window.__rareiqCardContext?.card||{};[["compareCheckArtwork",confidence>=75],["compareCheckNumber",confirmed($("collectorNumberCheck")?.textContent)||$("cardCollectorNumber")?.textContent!=="--"],["compareCheckSet",confirmed($("setConfirmationCheck")?.textContent)||$("cardSetName")?.textContent!=="--"],["compareCheckLanguage",confirmed($("languageCheck")?.textContent)||$("cardLanguage")?.textContent!=="--"]].forEach(([id,ok])=>{if($(id))$(id).dataset.confirmed=String(Boolean(ok))});const learned=$("compareLearnedMatch");if(learned){learned.hidden=!card.operator_learned;learned.dataset.confirmed="true";learned.textContent=card.learned_match_type==="approximate"?`Learned near-match · ${card.learned_fingerprint_distance} bit distance`:"Learned exact match"}if($("referenceApprove"))$("referenceApprove").disabled=Boolean($("approveButton")?.disabled);if($("referenceReject"))$("referenceReject").disabled=Boolean($("rejectButton")?.disabled)}
function selectReferenceCorrectionCandidate(candidate,{index=-1,catalog=false}={}){const source=multiCardReferenceImage(candidate);referenceSelectedCandidate=catalog?-1:index;referenceSelectedCatalogCandidate=catalog?candidate:null;if(source){$("referenceLightboxImage").src=source;$("referenceLightboxOpen").href=source}setCardText("referenceLightboxTitle",candidate.english_name||candidate.name||candidate.printed_name||"Selected candidate");setCardText("referenceLightboxMeta",[candidate.set_name,candidate.collector_number||candidate.printed_code,candidate.language].filter(Boolean).join(" · "));renderReferenceCandidates();renderReferenceCatalogResults(window.__rareiqCatalogCorrectionResults||[]);if($("referenceApprove"))$("referenceApprove").textContent="Approve selected"}
function makeReferenceCandidateButton(candidate,{index=-1,catalog=false}={}){const button=document.createElement("button"),source=multiCardReferenceImage(candidate),selected=catalog?referenceSelectedCatalogCandidate&&(referenceSelectedCatalogCandidate.id===candidate.id):index===referenceSelectedCandidate;button.type="button";button.dataset.selected=String(Boolean(selected));button.innerHTML=`${source?`<img src="${escapeHtml(source)}" alt="">`:"<i></i>"}<span><strong>${escapeHtml(candidate.english_name||candidate.name||candidate.printed_name||"Candidate")}</strong><small>${escapeHtml([candidate.set_name,candidate.collector_number||candidate.printed_code,candidate.language].filter(Boolean).join(" · ")||"Identity details pending")}</small></span>${catalog?"<b>CATALOG</b>":`<b>${recentScanConfidence(candidate.fused_score??candidate.score??candidate.confidence??0)}%</b>`}`;button.addEventListener("click",()=>selectReferenceCorrectionCandidate(candidate,{index,catalog}));return button}
function renderReferenceCandidates(){const host=$("referenceCandidateList"),candidates=window.__rareiqCardContext?.candidates||[];if(!host)return;host.replaceChildren(...(candidates.length?candidates.slice(0,12).map((candidate,index)=>makeReferenceCandidateButton(candidate,{index})):[Object.assign(document.createElement("p"),{textContent:"No suggested alternatives are available. Search the local library below."})]))}
function renderReferenceCatalogResults(results=[]){const host=$("referenceCatalogResults");if(!host)return;host.hidden=false;host.replaceChildren(...(results.length?results.map(candidate=>makeReferenceCandidateButton(candidate,{catalog:true})):[Object.assign(document.createElement("p"),{textContent:"No local catalog cards matched that search."})]))}
async function searchReferenceCatalog(event){event?.preventDefault();const query=String($("referenceCatalogSearchInput")?.value||"").trim();if(query.length<2){setCardText("referenceCatalogSearchStatus","Enter at least two characters");return}setCardText("referenceCatalogSearchStatus","Searching local card library…");const payload=await api(`/api/intelligence/catalog-search?q=${encodeURIComponent(query)}&limit=24`);window.__rareiqCatalogCorrectionResults=payload.results||[];renderReferenceCatalogResults(window.__rareiqCatalogCorrectionResults);setCardText("referenceCatalogSearchStatus",`${payload.count||0} catalog result${payload.count===1?"":"s"} · ${query}`)}
async function loadReferenceCorrectionHistory(){
  const host=$("referenceCorrectionHistoryList"),stats=$("referenceCorrectionStats"),list=$("referenceCorrectionRows");
  if(!host||!stats||!list)return;
  const payload=await fetchLearnedCorrections(),rows=payload.corrections||[];
  host.hidden=false;
  stats.innerHTML=`<span><b>${Number(payload.active||0)}</b> Active</span><span><b>${Number(payload.applications||0)}</b> Reused</span><span><b>${Number(payload.exact_applications||0)}</b> Exact</span><span data-risk="${Number(payload.approximate_applications||0)>0?"review":"clear"}"><b>${Number(payload.approximate_applications||0)}</b> Near-match</span>`;
  list.replaceChildren(...(rows.length?rows.map(row=>{
    const item=document.createElement("article"),candidate=row.candidate||{},undo=document.createElement("button"),uses=Number(row.times_applied||0),near=Number(row.approximate_applies||0),exact=Number(row.exact_applies||0);
    item.dataset.active=String(row.active!==false);item.dataset.risk=near>0?"review":"clear";
    item.innerHTML=`<div><strong>${escapeHtml(candidate.english_name||candidate.name||candidate.printed_name||"Corrected identity")}</strong><span>${escapeHtml([candidate.set_name,candidate.collector_number,candidate.language].filter(Boolean).join(" · ")||"Identity details unavailable")}</span><small>Learned ${new Date(Number(row.created_at||0)*1000).toLocaleString()}${row.last_applied_at?` · last used ${new Date(Number(row.last_applied_at)*1000).toLocaleString()}`:""}</small></div><aside><b>${uses} use${uses===1?"":"s"}</b><span>${exact} exact · ${near} near</span>${near>0?"<em>Manual review</em>":"<em>Auto-safe</em>"}</aside>`;
    undo.type="button";undo.className="riq-button";undo.textContent=row.active===false?"Revoked":"Undo learning";undo.disabled=row.active===false;undo.addEventListener("click",async()=>{await revokeLearnedCorrection(row.id);notify("Correction Reverted","Future scans will no longer use that learned identity.","success");loadReferenceCorrectionHistory()});item.append(undo);return item;
  }):[Object.assign(document.createElement("p"),{textContent:"No operator corrections have been learned yet."})]));
}
function openReferenceLightbox(source,title="Card verification",meta="Compare against the live card"){
  const overlay=$("referenceLightbox"),image=$("referenceLightboxImage");
  if(!overlay||!image||!source)return;
  image.src=String(source).replaceAll("\\","/");
  if($("referenceLiveCropImage"))$("referenceLiveCropImage").src=`/api/camera/crop.jpg?compare=${Date.now()}`;
  setCardText("referenceLightboxTitle",title);
  setCardText("referenceLightboxMeta",meta);
  if($("referenceLightboxOpen"))$("referenceLightboxOpen").href=image.src;
  referenceSelectedCandidate=-1;referenceSelectedCatalogCandidate=null;window.__rareiqCatalogCorrectionResults=[];if($("referenceApprove"))$("referenceApprove").textContent="Approve match";if($("referenceCandidates"))$("referenceCandidates").hidden=true;if($("referenceCatalogResults"))$("referenceCatalogResults").hidden=true;if($("referenceCatalogSearchInput"))$("referenceCatalogSearchInput").value="";setCardText("referenceCatalogSearchStatus","Suggested matches");renderReferenceCandidates();setReferenceCompareZoom(1);setReferenceCompareMode("side");syncReferenceVerification();overlay.hidden=false;
  document.body.classList.add("reference-lightbox-open");
  $("referenceLightboxClose")?.focus();
}
function closeReferenceLightbox(){if($("referenceLightbox"))$("referenceLightbox").hidden=true;document.body.classList.remove("reference-lightbox-open")}
function openCurrentReferenceLightbox(){const image=$("cardArt")?.querySelector("img");if(!image)return;const meta=[$("cardSetName")?.textContent,$("cardCollectorNumber")?.textContent,$("cardLanguage")?.textContent].filter(value=>value&&value!=="--").join(" · ");openReferenceLightbox(image.currentSrc||image.src,$("cardName")?.textContent||"Card verification",meta||"Compare against the live card")}
function openMatchCorrectionWorkflow(){
  const image=$("cardArt")?.querySelector("img");
  if(!image){notify("Correction Unavailable","Wait for a catalog reference image before correcting the match.","error");return}
  openCurrentReferenceLightbox();
  if($("referenceCandidates"))$("referenceCandidates").hidden=false;
  renderReferenceCandidates();
  if($("referenceApprove"))$("referenceApprove").textContent="Select the correct card";
}
async function approveReferenceSelection(){
  let result;
  const context=window.__rareiqCardContext||{};
  if(referenceSelectedCatalogCandidate){
    result=await api("/api/session/confirm-recognition-catalog-candidate",{method:"POST",body:JSON.stringify({state_id:context.snapshot?.state_id,candidate:referenceSelectedCatalogCandidate})}).catch(error=>{notify("Catalog Match Not Approved",error.message||String(error),"error");return null});
  }else if(referenceSelectedCandidate>=0){
    result=await api("/api/session/confirm-recognition-candidate",{method:"POST",body:JSON.stringify({state_id:context.snapshot?.state_id,candidate_index:referenceSelectedCandidate})}).catch(error=>{notify("Candidate Not Approved",error.message||String(error),"error");return null});
  }else{
    result=await operatorApprove();
    if(result)closeReferenceLightbox();
    return result;
  }
  if(result){
    applyAuthoritativeSession(result.session);
    await handleApprovedInventory(result).catch(error=>notify("Inventory Not Created",error.message||String(error),"error"));
    advancePackSessionCard(result.reveal_sequence);
    beginCardHandoff("approved");
    notify("Corrected Match Approved","The selected catalog identity was added and learned for future scans.","success");
    closeReferenceLightbox();
  }
  return result;
}

function renderUI4RecentScanDetail(card){
  const view=document.querySelector(".ui4-recent-scans-view");
  if(!view) return;
  view.replaceChildren();
  const back=document.createElement("button");
  back.type="button";
  back.className="ui4-history-back";
  back.textContent="Back to Recent Scans";
  back.addEventListener("click",()=>renderUI4RecentScans(ui4RecentScans));
  const detail=document.createElement("article");
  detail.className="ui4-history-detail";
  const heading=document.createElement("div");
  heading.className="ui4-history-detail-heading";
  if(card.reference_image_url){
    const image=document.createElement("img");
    image.src=card.reference_image_url;
    image.alt="";
    detail.appendChild(image);
  }
  const name=document.createElement("h3");
  name.textContent=card.card_name||card.printed_name||"Unknown card";
  const meta=document.createElement("p");
  meta.textContent=[card.set_name,card.collector_number].filter(Boolean).join("  |  ")||"Set details unavailable";
  const confidence=document.createElement("strong");
  confidence.textContent=`${recentScanConfidence(card.confidence)}% confidence`;
  const stamp=document.createElement("time");
  stamp.textContent=card.timestamp?new Date(Number(card.timestamp)*1000).toLocaleString():"Time unavailable";
  const historyPricing=normalizeCardPricing(card);
  const values=document.createElement("p");
  values.className="ui4-history-detail-prices";
  values.textContent=[
    nullableCardNumber(historyPricing.rawMarket)!==null
      ? `Raw ${cardMoney(historyPricing.rawMarket)}`
      : "Raw value unavailable",
    nullableCardNumber(historyPricing.psa10)!==null
      ? `PSA 10 ${cardMoney(historyPricing.psa10)}`
      : "PSA 10 unavailable"
  ].join("  |  ");
  heading.append(name,meta);
  detail.append(heading,values,confidence,stamp);
  const live=document.createElement("button");
  live.type="button";
  live.className="ui4-return-live";
  live.textContent="Return to Live Card";
  live.addEventListener("click",()=>setUI4InspectorView("current",false));
  view.append(back,detail,live);
}

function renderUI4RecentScans(cards=[]){
  const view=document.querySelector(".ui4-recent-scans-view");
  if(!view) return;
  ui4RecentScans=[...cards]
    .sort((left,right)=>Number(right.timestamp||0)-Number(left.timestamp||0))
    .slice(0,20);
  if($("recentScanCount")) $("recentScanCount").textContent=String(ui4RecentScans.length);
  view.replaceChildren();
  const header=document.createElement("header");
  header.className="ui4-history-drawer-head";
  const heading=document.createElement("div");
  const eyebrow=document.createElement("span");
  eyebrow.textContent="SESSION ACTIVITY";
  const title=document.createElement("strong");
  title.textContent="Recent Scans";
  heading.append(eyebrow,title);
  const close=document.createElement("button");
  close.type="button";
  close.setAttribute("aria-label","Close recent scans");
  close.textContent="×";
  close.addEventListener("click",()=>setUI4InspectorView("current",false));
  header.append(heading,close);
  view.appendChild(header);
  if(!ui4RecentScans.length){
    const empty=document.createElement("div");
    empty.className="ui4-history-empty";
    const title=document.createElement("strong");
    title.textContent="No recent scans";
    const copy=document.createElement("span");
    copy.textContent="Completed cards from this session will appear here.";
    empty.append(title,copy);
    view.appendChild(empty);
    return;
  }
  const list=document.createElement("div");
  list.className="ui4-history-list";
  ui4RecentScans.forEach(card=>{
    const row=document.createElement("button");
    row.type="button";
    row.className="ui4-history-row";
    row.addEventListener("click",()=>renderUI4RecentScanDetail(card));
    const thumb=document.createElement("span");
    thumb.className="ui4-history-thumb";
    if(card.reference_image_url){
      const image=document.createElement("img");
      image.src=card.reference_image_url;
      image.alt="";
      thumb.appendChild(image);
    }
    const identity=document.createElement("span");
    identity.className="ui4-history-identity";
    const name=document.createElement("strong");
    name.textContent=card.card_name||card.printed_name||"Unknown card";
    const meta=document.createElement("span");
    meta.textContent=[card.set_name,card.collector_number].filter(Boolean).join("  |  ")||"Set details unavailable";
    const historyPricing=normalizeCardPricing(card);
    const prices=document.createElement("span");
    prices.className="ui4-history-prices";
    prices.textContent=[
      nullableCardNumber(historyPricing.rawMarket)!==null
        ? `Raw ${cardMoney(historyPricing.rawMarket)}`
        : null,
      nullableCardNumber(historyPricing.psa10)!==null
        ? `PSA 10 ${cardMoney(historyPricing.psa10)}`
        : null
    ].filter(Boolean).join("  |  ")||"Value unavailable";
    identity.append(name,meta,prices);
    const result=document.createElement("span");
    result.className="ui4-history-result";
    const confidence=document.createElement("b");
    confidence.textContent=`${recentScanConfidence(card.confidence)}%`;
    const stamp=document.createElement("time");
    stamp.textContent=card.timestamp?new Date(Number(card.timestamp)*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}):"--";
    result.append(confidence,stamp);
    row.append(thumb,identity,result);
    list.appendChild(row);
  });
  view.appendChild(list);
}

async function loadUI4RecentScans(){
  const view=document.querySelector(".ui4-recent-scans-view");
  if(view) view.setAttribute("aria-busy","true");
  try{
    const payload=await api("/api/recent-pulls?limit=20");
    renderUI4RecentScans(Array.isArray(payload.cards)?payload.cards:[]);
  }catch{
    renderUI4RecentScans([]);
  }finally{
    if(view) view.setAttribute("aria-busy","false");
  }
}

function setUI4InspectorView(name,loadHistory=true){
  ui4InspectorView=name==="recent"?"recent":"current";
  document.querySelectorAll("[data-inspector-view]").forEach(button=>{
    const selected=button.dataset.inspectorView===ui4InspectorView;
    button.classList.toggle("active",selected);
    button.setAttribute("aria-selected",selected?"true":"false");
    button.tabIndex=selected?0:-1;
  });
  const current=document.querySelector(".ui4-current-card-view");
  const recent=document.querySelector(".ui4-recent-scans-view");
  if(current) current.hidden=false;
  if(recent) recent.hidden=ui4InspectorView!=="recent";
  current?.setAttribute("aria-hidden","false");
  recent?.setAttribute("aria-hidden",String(ui4InspectorView!=="recent"));
  document.querySelector(".inspector")?.setAttribute("data-primary-view",ui4InspectorView);
  syncMobileOperatorViewButtons();
  syncMobileOperatorDeck();
  if(ui4InspectorView==="recent"&&loadHistory) loadUI4RecentScans();
}

function syncInspectorNavigationState(){
  const state=String($("recognitionStateLabel")?.textContent||"").trim().toUpperCase();
  const live=$("currentCardLiveState");
  if(!live) return;
  const active=state&&!/READY|WAITING|NO CARD/.test(state);
  live.textContent=active?"LIVE":"READY";
  live.dataset.live=active?"true":"false";
}

const STUDIOX_WIDGET_LAYOUT_KEY="rareiq.studiox.widgetLayout.v2";
const STUDIOX_WIDGET_LAYOUT_LEGACY_KEY="rareiq.studiox.widgetLayout.v1";
const STUDIOX_WIDGET_IDS=[
  "identify","pokedex","reveal-animations","soundboard","spotify","ai-grade","market","candidates","details","diagnostics",
  "auto-screenshot"
];
const STUDIOX_WIDGET_TITLES={
  identify:"Identify",
  pokedex:"Rare Intelligence",
  "reveal-animations":"Reveal Animations",
  soundboard:"Soundboard",
  spotify:"Spotify DJ",
  "ai-grade":"AI Grade",
  market:"Market",
  candidates:"Candidates",
  details:"Details",
  diagnostics:"Diagnostics",
  "auto-screenshot":"Auto Screenshot",
};
const STUDIOX_WORKBENCH_CATEGORIES={card:["identify","pokedex","details","ai-grade"],recognition:["identify","candidates","diagnostics","auto-screenshot"],stream:["reveal-animations","soundboard","spotify"],business:["market"],all:[]};
const STUDIOX_WORKBENCH_TAB_KEY="rareiq.studiox.workbenchTab.v1";
const STUDIOX_WORKBENCH_CONTEXT={card:{eyebrow:"CARD WORKBENCH",title:"Card profile and intelligence",description:"Review verified identity, species intelligence, condition, and card details.",action:"Review identity"},recognition:{eyebrow:"RECOGNITION LAB",title:"Evidence and verification",description:"Inspect candidates, diagnostics, provenance, and the evidence behind the match.",action:"Open candidates"},stream:{eyebrow:"STREAM CONTROL",title:"Audience effects and audio",description:"Run reveal animations, sound cues, and music without leaving the live card.",action:"Stop all audio"},business:{eyebrow:"BUSINESS DESK",title:"Value and commerce",description:"Review verified market data and commercial context without invented pricing.",action:"Refresh market"},all:{eyebrow:"POWER USER",title:"All intelligence tools",description:"Full workspace with custom ordering, visibility, sizing, and pinning.",action:"Manage tools"}};
function syncStudioXWorkbenchContext(){const context=STUDIOX_WORKBENCH_CONTEXT[document.body.dataset.workbenchTab||"card"];if($("workbenchEyebrow"))$("workbenchEyebrow").textContent=context.eyebrow;if($("workbenchTitle"))$("workbenchTitle").textContent=context.title;if($("workbenchDescription"))$("workbenchDescription").textContent=context.description;if($("workbenchPrimaryAction"))$("workbenchPrimaryAction").textContent=context.action;}
async function refreshCurrentMarket(){
  const buttons=[$("marketRefreshButton"),document.body.dataset.workbenchTab==="business"?$("workbenchPrimaryAction"):null].filter(Boolean);
  buttons.forEach(button=>button.disabled=true);
  try{
    await api("/api/catalog/refresh-current",{method:"POST"});
    if($("marketWidgetState")) $("marketWidgetState").textContent="Refreshing verified market sources…";
    notify("Market Refresh Started","Fetching current public pricing for the verified card.","success");
  }catch(error){
    notify("Market Refresh Unavailable",error?.message||"Verify a card before refreshing pricing.","error");
  }finally{buttons.forEach(button=>button.disabled=false)}
}
async function saveManualPrice(event){
  event.preventDefault();
  const market=Number($("manualPriceMarket")?.value);
  if(!Number.isFinite(market)||market<0){notify("Price Required","Enter a valid market price.","error");return}
  const optional=id=>$(id)?.value===""?null:Number($(id)?.value);
  const result=await api("/api/catalog/manual-price",{method:"POST",body:JSON.stringify({market,low:optional("manualPriceLow"),high:optional("manualPriceHigh"),currency:$("manualPriceCurrency")?.value||"USD",note:$("manualPriceNote")?.value||""})});
  const pricing=result.pricing||{};
  setCardText("rawValue",cardMoney(pricing.market,pricing.currency));
  setCardText("rawLowValue",cardMoney(pricing.low,pricing.currency));
  setCardText("rawHighValue",cardMoney(pricing.high,pricing.currency));
  setCardText("pricingSource",pricing.source);
  setCardText("pricingUpdatedAt",readablePriceTimestamp(pricing.updated_at));
  setCardText("pricingConfidence","VERIFIED · MANUAL");
  setCardText("pricingFreshness",pricing.freshness||"just updated");
  setCardText("pricingProviderCount","Manual source");
  setCardText("pricingMovement",pricing.trend?`${String(pricing.trend).toUpperCase()} · ${Number(pricing.change_percent||0).toFixed(2)}%`:"Snapshot saved");
  renderPriceHistory(pricing.history||[],pricing.currency||pricing.unit||"USD");
  if($("marketWidgetState")) $("marketWidgetState").textContent="Manual verified price saved.";
  notify("Verified Price Saved",`${cardMoney(pricing.market)} · ${pricing.currency||pricing.unit||"USD"}`,"success");
}
async function selectMarketProviderQuote(button){
  if(!button||button.disabled)return;
  button.disabled=true;
  try{
    const result=await api("/api/catalog/select-quote",{method:"POST",body:JSON.stringify({source:button.dataset.source,variant:button.dataset.variant||"standard",currency:button.dataset.currency,reason:$("marketResolutionReason")?.value||"trusted-provider",note:$("marketResolutionNote")?.value||""})});
    const pricing=normalizeCardPricing(result.match||{pricing:result.pricing||{}});
    renderMarketProviderComparison(pricing);
    loadMarketResolutionHistory().catch(()=>{});
    if(result.match) renderCardDetails(result.match);
    if($("marketResolutionNote"))$("marketResolutionNote").value="";
    notify("Provider Quote Selected",`${button.dataset.source} is now the verified valuation source.`,"success");
  }catch(error){notify("Quote Selection Failed",error?.message||"Refresh market data and try again.","error");button.disabled=false}
}
async function undoMarketProviderQuote(button){
  if(!button||button.disabled)return;
  button.disabled=true;
  try{
    const result=await api("/api/catalog/select-quote/undo",{method:"POST"});
    const pricing=normalizeCardPricing(result.match||{pricing:result.pricing||{}});
    renderMarketProviderComparison(pricing);
    loadMarketResolutionHistory().catch(()=>{});
    if(result.match) renderCardDetails(result.match);
    notify("Provider Selection Undone","The prior pricing state has been restored.","success");
  }catch(error){notify("Undo Failed",error?.message||"No provider selection is available to undo.","error");button.disabled=false}
}
async function loadMarketResolutionHistory(){
  const host=$("marketResolutionHistoryRows"),state=$("marketResolutionHistoryState");
  if(!host||!state)return;
  state.textContent="Loading…";
  try{
    const result=await api("/api/catalog/quote-resolution-history");
    const history=Array.isArray(result.history)?result.history:[];
    state.textContent=history.length?`${history.length} decision${history.length===1?"":"s"}`:"No decisions";
    host.innerHTML=history.length?history.map(item=>{
      const undone=Boolean(item.undone_at),currency=String(item.currency||"USD").toUpperCase();
      const reasons={"trusted-provider":"Trusted provider","recent-sale":"Recent verified sale","variant-match":"Exact variant / condition","regional-market":"Regional market relevance",other:"Other evidence"};
      return `<article data-status="${undone?"undone":"active"}"><span><b>${escapeHtml(item.source||"Provider quote")}</b><small>${escapeHtml(item.variant||"standard")} · ${escapeHtml(currency)}</small><q>${escapeHtml(reasons[item.reason]||item.reason||"Operator decision")}${item.note?` · ${escapeHtml(item.note)}`:""}</q></span><strong>${cardMoney(item.market,currency)}</strong><em>${undone?"REVERTED":"ACTIVE"}</em><time>${escapeHtml(readablePriceTimestamp(undone?item.undone_at:item.created_at))}</time></article>`;
    }).join(""):`<p>No operator decisions recorded for this card.</p>`;
  }catch(error){state.textContent="Unavailable";host.innerHTML=`<p>${escapeHtml(error?.message||"History could not be loaded.")}</p>`}
}
function exportMarketResolutionHistory(format="csv"){
  const normalized=format==="json"?"json":"csv",link=document.createElement("a");
  link.href=`/api/catalog/quote-resolution-history/export?format=${normalized}`;
  link.download="";
  document.body.appendChild(link);link.click();link.remove();
  notify("Pricing Audit Exported",`${normalized.toUpperCase()} report includes all provider-resolution decisions.`,"success");
}
async function savePriceAlert(event){
  event.preventDefault();
  const target=Number($("priceAlertTarget")?.value);
  if(!Number.isFinite(target)||target<0){notify("Alert Target Required","Enter a valid target price.","error");return}
  const alert={direction:$("priceAlertDirection")?.value||"above",target,currency:$("priceAlertCurrency")?.value||"USD",enabled:true};
  await api("/api/catalog/price-alert",{method:"POST",body:JSON.stringify(alert)});
  renderPriceAlert({...alert,triggered:false});
  loadPriceWatchlist().catch(()=>{});
  notify("Price Alert Saved",`${alert.direction==="above"?"At or above":"At or below"} ${cardMoney(target,alert.currency)}`,"success");
}
async function clearPriceAlert(){
  await api("/api/catalog/price-alert",{method:"POST",body:JSON.stringify({direction:"above",target:0,currency:$("priceAlertCurrency")?.value||"USD",enabled:false})});
  renderPriceAlert(null);if($("priceAlertTarget"))$("priceAlertTarget").value="";
  loadPriceWatchlist().catch(()=>{});
  notify("Price Alert Cleared","The current card no longer has a target alert.","success");
}
function renderPriceAlert(alert){
  const form=$("priceAlertForm");
  if(form)form.dataset.triggered=String(Boolean(alert?.triggered));
  if(!alert){setCardText("priceAlertState","No alert configured");return}
  if($("priceAlertDirection"))$("priceAlertDirection").value=alert.direction||"above";
  if($("priceAlertTarget"))$("priceAlertTarget").value=alert.target??"";
  if($("priceAlertCurrency"))$("priceAlertCurrency").value=alert.currency||"USD";
  const condition=alert.direction==="below"?"at or below":"at or above";
  setCardText("priceAlertState",alert.triggered?`TRIGGERED · ${condition} ${cardMoney(alert.target,alert.currency)}`:`Watching ${condition} ${cardMoney(alert.target,alert.currency)}`);
}
function runStudioXWorkbenchAction(){const tab=document.body.dataset.workbenchTab||"card";if(tab==="card"||tab==="recognition"){switchDock("candidates");setUI4DiagnosticsOpen(true)}else if(tab==="stream")stopAllSoundboardAudio();else if(tab==="business"){refreshCurrentMarket()}else document.querySelector("#widgetManager>summary")?.click();}
function setStudioXWorkbenchTab(tab,persist=true){const selected=STUDIOX_WORKBENCH_CATEGORIES[tab]?tab:"card",allowed=new Set(STUDIOX_WORKBENCH_CATEGORIES[selected]);document.body.dataset.workbenchTab=selected;document.querySelectorAll("[data-workbench-tab]").forEach(button=>button.setAttribute("aria-selected",String(button.dataset.workbenchTab===selected)));document.querySelectorAll("[data-studiox-widget]").forEach(widget=>{widget.classList.toggle("workbench-category-hidden",selected!=="all"&&!allowed.has(widget.dataset.studioxWidget));});if(persist)localStorage.setItem(STUDIOX_WORKBENCH_TAB_KEY,selected);}
const STUDIOX_DEFAULT_WIDGET_LAYOUT={
  version:2,
  order:[...STUDIOX_WIDGET_IDS],
  hidden:[],
  collapsed:["details","diagnostics"],
  pinned:["identify"],
  sizes:{
    identify:"wide",
    pokedex:"wide",
    "reveal-animations":"wide",
    soundboard:"wide",
    spotify:"wide",
    "ai-grade":"standard",
    market:"standard",
    candidates:"compact",
    details:"compact",
    diagnostics:"compact",
    "auto-screenshot":"wide",
  },
};
let studioXWidgetLayout=null;

const AUTO_SCREENSHOT_CONFIG_KEY="rareiq.studiox.autoScreenshot.v1";
let AUTO_SCREENSHOT_BACKEND_AVAILABLE=false;
let autoScreenshotBackendStatus={state:"unavailable",event_id:null,error:null};
let autoScreenshotInitialized=false;
const AUTO_SCREENSHOT_WORKFLOWS=[
  "single-card-sales","pack-ripping","pack-battle"
];
const AUTO_SCREENSHOT_TRIGGERS=[
  "manual","exact-match","rarity-threshold","value-threshold","qualifying-hit"
];

function defaultAutoScreenshotConfig(){
  return {
    version:1,
    enabled:false,
    workflowMode:"single-card-sales",
    triggerReason:"manual",
    captureTypes:{fullFrame:true,cardFocus:false,evidenceView:false},
    customerId:null,
    vendorId:null,
    packNumber:null,
    turnNumber:null,
    playerSide:null,
    includeTimestamp:true,
    includeRecognitionEvidence:true,
    minimumConfidence:.9,
    oneCapturePerCard:true,
  };
}

function normalizedOptionalText(value){
  const text=String(value??"").trim();
  return text?text.slice(0,120):null;
}

function normalizedPositiveInteger(value){
  const number=Number(value);
  return Number.isInteger(number)&&number>0?number:null;
}

function normalizeAutoScreenshotConfig(value={}){
  const defaults=defaultAutoScreenshotConfig();
  const workflowMode=AUTO_SCREENSHOT_WORKFLOWS.includes(value.workflowMode)
    ?value.workflowMode
    :defaults.workflowMode;
  const triggerReason=AUTO_SCREENSHOT_TRIGGERS.includes(value.triggerReason)
    ?value.triggerReason
    :defaults.triggerReason;
  const minimum=Number(value.minimumConfidence);
  return {
    ...defaults,
    enabled:AUTO_SCREENSHOT_BACKEND_AVAILABLE&&value.enabled===true,
    workflowMode,
    triggerReason,
    captureTypes:{
      fullFrame:value.captureTypes?.fullFrame!==false,
      cardFocus:value.captureTypes?.cardFocus===true,
      evidenceView:value.captureTypes?.evidenceView===true,
    },
    customerId:normalizedOptionalText(value.customerId),
    vendorId:normalizedOptionalText(value.vendorId),
    packNumber:normalizedPositiveInteger(value.packNumber),
    turnNumber:normalizedPositiveInteger(value.turnNumber),
    playerSide:workflowMode==="pack-battle"&&["player-1","player-2"].includes(value.playerSide)
      ?value.playerSide
      :null,
    includeTimestamp:value.includeTimestamp!==false,
    includeRecognitionEvidence:value.includeRecognitionEvidence!==false,
    minimumConfidence:Number.isFinite(minimum)
      ?Math.min(1,Math.max(0,minimum))
      :defaults.minimumConfidence,
    oneCapturePerCard:true,
  };
}

function loadAutoScreenshotConfig(){
  try{
    return normalizeAutoScreenshotConfig(
      JSON.parse(localStorage.getItem(AUTO_SCREENSHOT_CONFIG_KEY)||"null")||{}
    );
  }catch{
    return defaultAutoScreenshotConfig();
  }
}

function saveAutoScreenshotConfig(config){
  const normalized=normalizeAutoScreenshotConfig(config);
  try{
    localStorage.setItem(AUTO_SCREENSHOT_CONFIG_KEY,JSON.stringify(normalized));
  }catch{}
  return normalized;
}

async function requestAutoScreenshotBackend(path,options={}){
  const response=await fetch(path,{
    cache:"no-store",
    headers:{"Content-Type":"application/json",...(options.headers||{})},
    ...options,
  });
  const payload=await response.json().catch(()=>({ok:false,error:"invalid_response"}));
  if(!response.ok||payload.ok===false){
    throw new Error(payload.message||payload.error||`Request failed (${response.status})`);
  }
  return payload;
}

function autoScreenshotIdentityVerdict(context={}){
  const key=String(context?.presentation?.key||"");
  if(key==="exact-match"&&context.verified===true) return "exact-match";
  if(key==="review-needed") return "review-needed";
  if(["candidate-found","verifying"].includes(key)) return "provisional";
  return "unknown";
}

function autoScreenshotTriggerQualifies(config,context={},options={}){
  const value=normalizeAutoScreenshotConfig(config);
  if(!AUTO_SCREENSHOT_BACKEND_AVAILABLE||!value.enabled) return false;
  const verdict=autoScreenshotIdentityVerdict(context);
  const confidence=Number(context.visualConfidence);
  if(!Number.isFinite(confidence)||confidence<value.minimumConfidence) return false;
  if(value.triggerReason==="manual") return options.manual===true;
  if(value.triggerReason==="exact-match") return verdict==="exact-match";
  if(value.triggerReason==="rarity-threshold"){
    return verdict==="exact-match"&&Boolean(options.truthfulRarity);
  }
  if(value.triggerReason==="value-threshold"){
    return verdict==="exact-match"&&Number.isFinite(options.truthfulMarketValue);
  }
  return verdict==="exact-match"&&options.qualifyingHit===true;
}

function buildAutoScreenshotProvenanceEvent(confirmation,context,config){
  if(!confirmation?.ok||!confirmation.eventId||!confirmation.capturedAt){
    throw new Error("Backend confirmation is required for screenshot provenance.");
  }
  const value=normalizeAutoScreenshotConfig(config);
  const card=context?.card||{};
  return Object.freeze({
    version:1,
    eventId:String(confirmation.eventId),
    sessionId:normalizedOptionalText(confirmation.sessionId),
    customerId:value.customerId,
    vendorId:value.vendorId,
    workflowMode:value.workflowMode,
    packNumber:value.packNumber,
    turnNumber:value.turnNumber,
    playerSide:value.playerSide,
    cardContextId:String(confirmation.cardContextId||context?.identityKey||""),
    cardIdentity:{
      cardId:normalizedOptionalText(card.id),
      englishName:normalizedOptionalText(card.english_name||card.canonical_name),
      printedName:normalizedOptionalText(card.printed_name||card.name),
      set:normalizedOptionalText(card.set_name||card.set_id),
      localCardId:normalizedOptionalText(card.collector_number),
      officialNumber:normalizedOptionalText(context?.officialCollectorNumber),
      identityVerdict:autoScreenshotIdentityVerdict(context),
      visualConfidence:Number.isFinite(Number(context?.visualConfidence))
        ?Number(context.visualConfidence)
        :null,
    },
    triggerReason:value.triggerReason,
    capturedAt:String(confirmation.capturedAt),
    cameraSource:normalizedOptionalText(confirmation.cameraSource),
    assets:{
      fullFrame:normalizedOptionalText(confirmation.assets?.fullFrame),
      cardFocus:normalizedOptionalText(confirmation.assets?.cardFocus),
      evidenceView:normalizedOptionalText(confirmation.assets?.evidenceView),
      clipId:normalizedOptionalText(confirmation.assets?.clipId),
    },
  });
}

function createAutoScreenshotCorrectionRevision(originalEvent,confirmation,cardIdentity){
  if(!originalEvent?.eventId||!confirmation?.ok||!confirmation?.revisionId){
    throw new Error("Confirmed revision metadata is required.");
  }
  return Object.freeze({
    originalEventId:String(originalEvent.eventId),
    revisionId:String(confirmation.revisionId),
    revisedAt:String(confirmation.revisedAt||""),
    cardIdentity:{...cardIdentity},
  });
}

function readAutoScreenshotForm(){
  return normalizeAutoScreenshotConfig({
    enabled:$("autoScreenshotEnabled")?.checked===true,
    workflowMode:$("autoScreenshotWorkflow")?.value,
    triggerReason:$("autoScreenshotTrigger")?.value,
    captureTypes:{
      fullFrame:$("autoScreenshotFullFrame")?.checked===true,
      cardFocus:$("autoScreenshotCardFocus")?.checked===true,
      evidenceView:$("autoScreenshotEvidenceView")?.checked===true,
    },
    customerId:$("autoScreenshotCustomerId")?.value,
    vendorId:$("autoScreenshotVendorId")?.value,
    packNumber:$("autoScreenshotPackNumber")?.value,
    turnNumber:$("autoScreenshotTurnNumber")?.value,
    playerSide:$("autoScreenshotPlayerSide")?.value,
    includeTimestamp:$("autoScreenshotTimestamp")?.checked===true,
    includeRecognitionEvidence:$("autoScreenshotEvidence")?.checked===true,
    minimumConfidence:Number($("autoScreenshotMinimumConfidence")?.value)/100,
  });
}

function renderAutoScreenshotConfig(config=loadAutoScreenshotConfig()){
  const value=normalizeAutoScreenshotConfig(config);
  const assignments={
    autoScreenshotWorkflow:value.workflowMode,
    autoScreenshotTrigger:value.triggerReason,
    autoScreenshotCustomerId:value.customerId||"",
    autoScreenshotVendorId:value.vendorId||"",
    autoScreenshotPackNumber:value.packNumber||"",
    autoScreenshotTurnNumber:value.turnNumber||"",
    autoScreenshotPlayerSide:value.playerSide||"",
    autoScreenshotMinimumConfidence:Math.round(value.minimumConfidence*100),
  };
  Object.entries(assignments).forEach(([id,fieldValue])=>{
    if($(id)) $(id).value=fieldValue;
  });
  if($("autoScreenshotEnabled")){
    $("autoScreenshotEnabled").checked=value.enabled;
    $("autoScreenshotEnabled").disabled=!AUTO_SCREENSHOT_BACKEND_AVAILABLE;
  }
  if($("autoScreenshotFullFrame")) $("autoScreenshotFullFrame").checked=value.captureTypes.fullFrame;
  if($("autoScreenshotCardFocus")) $("autoScreenshotCardFocus").checked=value.captureTypes.cardFocus;
  if($("autoScreenshotEvidenceView")) $("autoScreenshotEvidenceView").checked=value.captureTypes.evidenceView;
  if($("autoScreenshotTimestamp")) $("autoScreenshotTimestamp").checked=value.includeTimestamp;
  if($("autoScreenshotEvidence")) $("autoScreenshotEvidence").checked=value.includeRecognitionEvidence;
  if($("autoScreenshotManualCapture")) $("autoScreenshotManualCapture").disabled=!AUTO_SCREENSHOT_BACKEND_AVAILABLE;
  const state=AUTO_SCREENSHOT_BACKEND_AVAILABLE
    ?String(autoScreenshotBackendStatus.state||(value.enabled?"armed":"configured"))
    :"unavailable";
  const labels={configured:"Configured",armed:"Armed",capturing:"Capturing",saved:"Saved",error:"Error",unavailable:"Unavailable"};
  if($("autoScreenshotState")) $("autoScreenshotState").textContent=labels[state]||"Configured";
  if($("autoScreenshotStatus")){
    $("autoScreenshotStatus").textContent=!AUTO_SCREENSHOT_BACKEND_AVAILABLE
      ?"Screenshot capture engine not connected"
      :autoScreenshotBackendStatus.error
      ?String(autoScreenshotBackendStatus.error)
      :autoScreenshotBackendStatus.event_id
      ?`Saved event ${autoScreenshotBackendStatus.event_id}`
      :value.enabled
      ?"Automatic provenance capture armed"
      :"Manual screenshot available";
  }
  setStudioXWidgetState("auto-screenshot",state);
  return value;
}

async function persistAutoScreenshotSettings(config){
  const payload=await requestAutoScreenshotBackend("/api/provenance/settings",{
    method:"PUT",
    body:JSON.stringify({settings:config}),
  });
  autoScreenshotBackendStatus=payload.status||autoScreenshotBackendStatus;
  return saveAutoScreenshotConfig(payload.settings||config);
}

async function manualAutoScreenshotCapture(){
  const button=$("autoScreenshotManualCapture");
  if(button) button.disabled=true;
  autoScreenshotBackendStatus={state:"capturing",event_id:null,error:null};
  renderAutoScreenshotConfig();
  try{
    const result=await requestAutoScreenshotBackend("/api/provenance/capture",{method:"POST"});
    autoScreenshotBackendStatus={state:"saved",event_id:result.eventId,error:null};
  }catch(error){
    autoScreenshotBackendStatus={state:"error",event_id:null,error:String(error?.message||error)};
  }finally{
    renderAutoScreenshotConfig();
  }
}

async function initializeAutoScreenshotConfiguration(){
  const form=$("autoScreenshotForm");
  if(!form||autoScreenshotInitialized) return;
  autoScreenshotInitialized=true;
  // Bind the manual action before awaiting capability discovery. The
  // recognition poll may enable this control independently, so its handler
  // must not depend on the rest of the Studio X shell initializing cleanly.
  $("autoScreenshotManualCapture")?.addEventListener("click",manualAutoScreenshotCapture);
  renderAutoScreenshotConfig();
  try{
    const payload=await requestAutoScreenshotBackend("/api/provenance/settings");
    AUTO_SCREENSHOT_BACKEND_AVAILABLE=payload.available===true;
    autoScreenshotBackendStatus=payload.status||autoScreenshotBackendStatus;
    renderAutoScreenshotConfig(saveAutoScreenshotConfig(payload.settings||{}));
  }catch{
    AUTO_SCREENSHOT_BACKEND_AVAILABLE=false;
    renderAutoScreenshotConfig();
  }
  form.addEventListener("change",async()=>{
    const config=saveAutoScreenshotConfig(readAutoScreenshotForm());
    renderAutoScreenshotConfig(config);
    if(!AUTO_SCREENSHOT_BACKEND_AVAILABLE) return;
    try{
      renderAutoScreenshotConfig(await persistAutoScreenshotSettings(config));
    }catch(error){
      autoScreenshotBackendStatus={state:"error",event_id:null,error:String(error?.message||error)};
      renderAutoScreenshotConfig(config);
    }
  });
}

function defaultStudioXWidgetLayout(){
  return {
    version:STUDIOX_DEFAULT_WIDGET_LAYOUT.version,
    order:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.order],
    hidden:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.hidden],
    collapsed:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.collapsed],
    pinned:[...STUDIOX_DEFAULT_WIDGET_LAYOUT.pinned],
    sizes:{...STUDIOX_DEFAULT_WIDGET_LAYOUT.sizes},
  };
}

function normalizeStudioXWidgetLayout(value){
  if(!value||![1,2].includes(value.version)) return defaultStudioXWidgetLayout();
  const validList=list=>Array.isArray(list)
    ? [...new Set(list.filter(id=>STUDIOX_WIDGET_IDS.includes(id)))]
    : [];
  const savedOrder=validList(value.order);
  if(!savedOrder.includes("pokedex")){
    const identifyIndex=savedOrder.indexOf("identify");
    savedOrder.splice(identifyIndex>=0?identifyIndex+1:0,0,"pokedex");
  }
  const validSizes=["compact","standard","wide"];
  const sizes={...STUDIOX_DEFAULT_WIDGET_LAYOUT.sizes};
  if(value.version===2&&value.sizes&&typeof value.sizes==="object"){
    STUDIOX_WIDGET_IDS.forEach(id=>{
      if(validSizes.includes(value.sizes[id])) sizes[id]=value.sizes[id];
    });
  }
  return {
    version:2,
    order:[
      ...savedOrder,
      ...STUDIOX_WIDGET_IDS.filter(id=>!savedOrder.includes(id)),
    ],
    hidden:validList(value.hidden),
    collapsed:validList(value.collapsed),
    pinned:validList(value.pinned),
    sizes,
  };
}

function loadStudioXWidgetLayout(){
  try{
    const savedV2=localStorage.getItem(STUDIOX_WIDGET_LAYOUT_KEY);
    const savedV1=localStorage.getItem(STUDIOX_WIDGET_LAYOUT_LEGACY_KEY);
    return normalizeStudioXWidgetLayout(
      JSON.parse(savedV2||savedV1||"null")
    );
  }catch{
    return defaultStudioXWidgetLayout();
  }
}

function saveStudioXWidgetLayout(){
  try{
    localStorage.setItem(
      STUDIOX_WIDGET_LAYOUT_KEY,
      JSON.stringify(studioXWidgetLayout)
    );
  }catch{}
}

function widgetStateLabel(widget){
  return String(widget?.dataset.widgetState||"empty")
    .replaceAll("-"," ");
}

function ensureStudioXWidgetChrome(widget){
  if(widget.querySelector(":scope > .studiox-widget-header")) return;
  const id=widget.dataset.studioxWidget;
  const header=document.createElement("header");
  header.className="studiox-widget-header";
  header.innerHTML=`
    <button class="studiox-widget-focus" type="button" data-widget-focus="${id}">
      <span>${STUDIOX_WIDGET_TITLES[id]||id}</span>
      <small data-widget-status>${widgetStateLabel(widget)}</small>
    </button>
    <button class="studiox-widget-drag-handle" type="button" draggable="true"
      data-widget-drag-handle="${id}" aria-label="Drag to reorder ${STUDIOX_WIDGET_TITLES[id]}"
      title="Drag to reorder"><span aria-hidden="true">⋮⋮</span><small>DRAG</small></button>
    <div class="studiox-widget-controls">
      <button type="button" data-widget-action="pin" aria-label="Pin ${STUDIOX_WIDGET_TITLES[id]}">Pin</button>
      <button type="button" data-widget-action="up" aria-label="Move ${STUDIOX_WIDGET_TITLES[id]} up">↑</button>
      <button type="button" data-widget-action="down" aria-label="Move ${STUDIOX_WIDGET_TITLES[id]} down">↓</button>
      <button type="button" data-widget-action="size" aria-label="Change ${STUDIOX_WIDGET_TITLES[id]} size">Size</button>
      <button type="button" data-widget-action="collapse" aria-label="Collapse ${STUDIOX_WIDGET_TITLES[id]}">Collapse</button>
    </div>
  `;
  widget.prepend(header);
}

function clearStudioXWidgetDropIndicators(workspace){
  workspace?.querySelectorAll(".is-dragging,.is-drop-before,.is-drop-after").forEach(widget=>{
    widget.classList.remove("is-dragging","is-drop-before","is-drop-after");
  });
}

function setStudioXWidgetOverviewFocus(id){
  const workspace=$("widgetWorkspace");
  if(!workspace||!STUDIOX_WIDGET_IDS.includes(id)) return;
  updateStudioXWidgetLayout(id,"collapse");
}

function setAllStudioXWidgetsCollapsed(collapsed){
  studioXWidgetLayout=normalizeStudioXWidgetLayout(
    studioXWidgetLayout||loadStudioXWidgetLayout()
  );
  studioXWidgetLayout.collapsed=collapsed
    ? STUDIOX_WIDGET_IDS.filter(id=>!studioXWidgetLayout.hidden.includes(id))
    : [];
  applyStudioXWidgetLayout({persist:true});
}

function reorderStudioXWidgetByDrop(sourceId,targetId,placeAfter=false){
  if(!STUDIOX_WIDGET_IDS.includes(sourceId)||!STUDIOX_WIDGET_IDS.includes(targetId)) return;
  if(sourceId===targetId) return;
  studioXWidgetLayout=normalizeStudioXWidgetLayout(
    studioXWidgetLayout||loadStudioXWidgetLayout()
  );
  const order=studioXWidgetLayout.order.filter(id=>id!==sourceId);
  const targetIndex=order.indexOf(targetId);
  if(targetIndex<0) return;
  order.splice(targetIndex+(placeAfter?1:0),0,sourceId);
  studioXWidgetLayout.order=order;
  applyStudioXWidgetLayout({persist:true});
}

function applyStudioXWidgetLayout({persist=false}={}){
  const workspace=$("widgetWorkspace");
  if(!workspace) return;
  studioXWidgetLayout=normalizeStudioXWidgetLayout(
    studioXWidgetLayout||loadStudioXWidgetLayout()
  );
  const pinned=studioXWidgetLayout.order.filter(
    id=>studioXWidgetLayout.pinned.includes(id)
  );
  const unpinned=studioXWidgetLayout.order.filter(
    id=>!studioXWidgetLayout.pinned.includes(id)
  );
  studioXWidgetLayout.order=[...pinned,...unpinned];
  studioXWidgetLayout.order.forEach(id=>{
    const widget=workspace.querySelector(`[data-studiox-widget="${id}"]`);
    if(!widget) return;
    ensureStudioXWidgetChrome(widget);
    workspace.appendChild(widget);
    widget.hidden=studioXWidgetLayout.hidden.includes(id);
    widget.classList.toggle(
      "is-collapsed",
      studioXWidgetLayout.collapsed.includes(id)
    );
    widget.classList.toggle(
      "is-pinned",
      studioXWidgetLayout.pinned.includes(id)
    );
    widget.classList.remove("is-overview-active","is-overview-card","is-focused");
    widget.dataset.widgetSize=studioXWidgetLayout.sizes[id];
    const collapse=widget.querySelector('[data-widget-action="collapse"]');
    if(collapse){
      const collapsed=widget.classList.contains("is-collapsed");
      collapse.textContent=collapsed?"Expand":"Collapse";
      collapse.setAttribute("aria-expanded",collapsed?"false":"true");
    }
    const titleToggle=widget.querySelector("[data-widget-focus]");
    if(titleToggle){
      const expanded=!widget.classList.contains("is-collapsed");
      titleToggle.setAttribute("aria-expanded",String(expanded));
      titleToggle.setAttribute("aria-label",`${expanded?"Close":"Open"} ${STUDIOX_WIDGET_TITLES[id]||id}`);
      titleToggle.title=expanded?"Close tool":"Open tool";
    }
    const pin=widget.querySelector('[data-widget-action="pin"]');
    if(pin){
      const isPinned=widget.classList.contains("is-pinned");
      pin.textContent=isPinned?"Unpin":"Pin";
      pin.setAttribute("aria-pressed",isPinned?"true":"false");
    }
    const size=widget.querySelector('[data-widget-action="size"]');
    if(size) size.textContent=studioXWidgetLayout.sizes[id];
  });
  document.querySelectorAll("[data-widget-visibility]").forEach(input=>{
    input.checked=!studioXWidgetLayout.hidden.includes(
      input.dataset.widgetVisibility
    );
  });
  delete workspace.dataset.activeOverviewWidget;
  if(persist) saveStudioXWidgetLayout();
}

function updateStudioXWidgetLayout(id,action,value=null){
  if(!STUDIOX_WIDGET_IDS.includes(id)) return;
  studioXWidgetLayout=normalizeStudioXWidgetLayout(
    studioXWidgetLayout||loadStudioXWidgetLayout()
  );
  if(action==="visibility"){
    studioXWidgetLayout.hidden=studioXWidgetLayout.hidden.filter(item=>item!==id);
    if(value===false) studioXWidgetLayout.hidden.push(id);
  }else if(action==="collapse"){
    const collapsed=studioXWidgetLayout.collapsed.includes(id);
    studioXWidgetLayout.collapsed=studioXWidgetLayout.collapsed.filter(item=>item!==id);
    if(!collapsed) studioXWidgetLayout.collapsed.push(id);
  }else if(action==="pin"){
    const pinned=studioXWidgetLayout.pinned.includes(id);
    studioXWidgetLayout.pinned=studioXWidgetLayout.pinned.filter(item=>item!==id);
    if(!pinned) studioXWidgetLayout.pinned.push(id);
  }else if(action==="size"){
    const sizes=["compact","standard","wide"];
    const current=sizes.indexOf(studioXWidgetLayout.sizes[id]);
    studioXWidgetLayout.sizes[id]=sizes[(current+1)%sizes.length];
  }else if(action==="up"||action==="down"){
    const index=studioXWidgetLayout.order.indexOf(id);
    const target=index+(action==="up"?-1:1);
    if(index>=0&&target>=0&&target<studioXWidgetLayout.order.length){
      [
        studioXWidgetLayout.order[index],
        studioXWidgetLayout.order[target],
      ]=[
        studioXWidgetLayout.order[target],
        studioXWidgetLayout.order[index],
      ];
    }
  }
  applyStudioXWidgetLayout({persist:true});
}

function resetStudioXWidgetLayout(){
  studioXWidgetLayout=defaultStudioXWidgetLayout();
  applyStudioXWidgetLayout({persist:true});
}

function setPremiumIntelligenceTab(name="identify"){
  const widget=document.querySelector(`[data-studiox-widget="${name}"]`);
  if(!widget) return;
  document.querySelectorAll("[data-studiox-widget]").forEach(node=>{
    node.classList.toggle("is-focused",node===widget);
  });
  widget.querySelector(".studiox-widget-focus")?.focus({preventScroll:true});
}

function provisionalIdentityCard(card=null){
  if(!card) return null;
  return {
    name:card.english_name||card.canonical_name||card.printed_name||card.name||"Candidate",
    english_name:card.english_name||card.canonical_name||null,
    printed_name:card.printed_name||null,
    language:card.language||card.language_code||null,
    visual_score:card.visual_score??card.artwork_score??card.score??null,
    score:card.score??card.fused_score??null,
    provisional:true,
  };
}

function deriveSharedCardContext(presentation,card=null,snapshot={},candidates=[]){
  const grading=
    snapshot?.ai_grade||
    snapshot?.grading||
    card?.ai_grade||
    card?.grading||
    null;
  const allowedGradeStates=[
    "unavailable","waiting-for-stable-capture","front-analysis-ready",
    "back-image-required","analyzing","error"
  ];
  let gradeState=String(grading?.state||"").toLowerCase();
  if(!allowedGradeStates.includes(gradeState)){
    gradeState=["detecting","scanning","candidate-found","verifying"].includes(presentation.key)
      ? "waiting-for-stable-capture"
      : "unavailable";
  }
  const verified=presentation.key==="exact-match";
  return {
    revision:Number(snapshot?.revision||0),
    identityKey:String(
      card?.identity_override_key||
      card?.id||
      `${card?.set_id||""}:${card?.collector_number||""}`
    ),
    presentation:{...presentation},
    card:card||null,
    candidates:Array.isArray(candidates)?[...candidates]:[],
    verified,
    visualConfidence:normalize(
      card?.visual_score??
      card?.artwork_score??
      presentation?.confidence??
      0
    ),
    officialCollectorNumber:
      card?.official_collector_number||
      snapshot?.official_collector_number||
      null,
    market:deriveMarketPresentation(card||{}),
    snapshot:{...snapshot},
    grading,
    gradeState,
  };
}

function setStudioXWidgetState(id,state){
  const widget=document.querySelector(`[data-studiox-widget="${id}"]`);
  if(!widget) return;
  widget.dataset.widgetState=state;
  const status=widget.querySelector("[data-widget-status]");
  if(status) status.textContent=String(state).replaceAll("-"," ");
}

function deriveLiveAnalysisSteps(context){
  const snapshot=context.snapshot||{};
  const vision=snapshot?.vision?.vision||snapshot?.vision||{};
  const presentation=context.presentation.key;
  const active=!["ready","exact-match"].includes(presentation);
  const detected=Boolean(
    snapshot.card_present===true||
    vision.visible===true||
    context.card||
    context.candidates.length
  );
  const geometryStable=Boolean(
    vision.stable===true||
    Number(vision.stable_frames||0)>=Number(vision.stable_target||Infinity)
  );
  const artworkEvidence=Boolean(
    context.candidates.length||
    context.card?.visual_score||
    context.card?.artwork_score||
    snapshot?.artwork_index?.score
  );
  const collectorEvidence=Boolean(
    snapshot.collector_number||
    context.card?.collector_number
  );
  const error=presentation==="error";
  return {
    detection:error?"error":detected?"complete":active?"active":"pending",
    geometry:error?"error":geometryStable?"complete":detected?"active":"pending",
    artwork:error?"error":artworkEvidence?"complete":detected&&["scanning","candidate-found","verifying","review-needed"].includes(presentation)?"active":"pending",
    collector:error?"error":collectorEvidence?"complete":artworkEvidence&&["scanning","candidate-found","verifying","review-needed"].includes(presentation)?"active":"pending",
    catalog:error?"error":context.verified?"complete":["candidate-found","verifying","review-needed"].includes(presentation)?"active":"pending",
  };
}

function hasTruthfulRecognizedIdentity(context){
  const card=context?.card;
  if(!card) return false;
  const name=firstCardValue(card,["english_name","canonical_name","printed_name","name"]);
  const locator=firstCardValue(card,["collector_number","official_collector_number","set_id","set_name"]);
  if(
    !context.verified&&
    card.provisional===true&&
    name&&
    ["candidate-found","review-needed"].includes(context.presentation.key)
  ){
    return true;
  }
  return Boolean(
    name&&locator&&
    ["candidate-found","review-needed","exact-match"].includes(context.presentation.key)
  );
}

function renderLiveAnalysisTimeline(context){
  const timeline=$("liveAnalysisTimeline");
  const header=$("cardContextHeader");
  const pending=$("identityPendingPlaceholder");
  if(!timeline||!header||!pending) return;
  const recognized=context.verified||hasTruthfulRecognizedIdentity(context);
  const showCardContext=recognized||context.presentation.key==="set-mismatch";
  const scanning=!recognized&&!["ready","exact-match"].includes(context.presentation.key);
  const state=context.presentation.key;
  const currentView=document.querySelector(".ui4-current-card-view");
  const inspectorMain=$("inspectorMain");
  if(currentView) currentView.dataset.presentationState=state;
  if(inspectorMain) inspectorMain.dataset.presentationState=state;
  timeline.hidden=!scanning;
  pending.hidden=showCardContext;
  header.hidden=!showCardContext;
  header.inert=!showCardContext;
  if($("liveAnalysisTitle")){
    $("liveAnalysisTitle").textContent=context.presentation.placeholderTitle;
  }
  if($("liveAnalysisState")){
    $("liveAnalysisState").textContent=context.presentation.title;
  }
  if($("liveAnalysisDetail")){
    $("liveAnalysisDetail").textContent=context.presentation.detail;
  }
  if($("identityPendingTitle")) $("identityPendingTitle").textContent="IDENTITY PENDING";
  if($("identityPendingDetail")){
    $("identityPendingDetail").textContent=
      context.presentation.key==="ready"
        ?"Waiting for card"
        : context.presentation.key==="set-mismatch"
        ?"Choose the correct set or switch Set to Auto"
        : context.presentation.key==="review-needed"
        ?"Waiting for operator confirmation"
        :"Waiting for catalog confirmation";
  }
  const labels={
    pending:"Pending",
    active:"In progress",
    complete:"Complete",
    unavailable:"Unavailable",
    error:"Error",
  };
  const steps=deriveLiveAnalysisSteps(context);
  Object.entries(steps).forEach(([name,state])=>{
    const row=timeline.querySelector(`[data-analysis-step="${name}"]`);
    if(!row) return;
    row.dataset.stepState=state;
    const label=row.querySelector("b");
    if(label) label.textContent=labels[state];
  });
}

function renderAuthoritativeCardContextHeader(context){
  renderLiveAnalysisTimeline(context);
  renderIdentityVerdictBadge(context.presentation,context.verified);
  if(context.verified||hasTruthfulRecognizedIdentity(context)) return;
  const presentation=context.presentation;
  if($("resultEyebrow")) $("resultEyebrow").textContent="Live Recognition";
  if($("cardName")){
    $("cardName").textContent=
      presentation.key==="ready"
        ? "Ready for card"
        : presentation.placeholderTitle;
  }
  if($("cardMeta")) $("cardMeta").textContent=presentation.detail;
  if($("cardStatus")) $("cardStatus").textContent=presentation.title;
  if($("cardValue")) $("cardValue").textContent="Waiting for confirmed identity";
  if($("cardArt")) $("cardArt").replaceChildren();
  resetExtendedCardData();
}

function renderIdentityVerdictBadge(presentation={},verified=false){
  const badge=$("identityVerdictBadge");
  if(!badge) return;
  const provisional=!verified&&[
    "candidate-found","verifying","review-needed"
  ].includes(presentation.key);
  badge.hidden=!(verified||provisional);
  badge.dataset.verdict=verified?"exact-match":"provisional";
  badge.textContent=verified?"EXACT MATCH":"CANDIDATE · VERIFYING";
}

function renderIdentifyWidget(context){
  const snapshot=context.snapshot||{};
  const temporalProgress=Number(snapshot.temporal_confirmation_progress||0);
  const temporalRequired=Number(snapshot.temporal_confirmation_required||2);
  const scanning=!context.verified&&!["ready","error"].includes(context.presentation.key);
  setCardText(
    "identifyCatalogStatus",
    context.verified
      ?"Exact"
      : scanning
      ? context.presentation.key==="verifying"
        ?"Catalog verification in progress"
        :"Recognition evidence gathering"
      :"Waiting for card"
  );
  setCardText(
    "identifyVisualConfidence",
    `${Math.round(context.visualConfidence*100)}%`
  );
  setCardText(
    "identifyAcceptanceEvidence",
    !context.card
      ? scanning
        ? "Waiting for stronger evidence"
        : "Not available"
      : context.verified
      ? "Verified catalog identity"
      : "Operator review required"
  );
  const identifyWidget=document.querySelector('[data-studiox-widget="identify"]');
  if(identifyWidget){
    identifyWidget.dataset.identityVerdict=
      context.verified?"verified":scanning?"pending":context.card?"provisional":"empty";
  }
  const evidence=$("identifyEvidence");
  if(evidence){
    const card=context.card||{};
    const exactDiagnostics=snapshot.exact_reference_diagnostics||{};
    const exactCandidates=Array.isArray(exactDiagnostics.candidates)?exactDiagnostics.candidates:[];
    const exactLeader=exactCandidates[0]||null;
    const exactRunnerUp=exactCandidates[1]||null;
    const exactDecision=exactDiagnostics.status
      ? exactDiagnostics.status==="resolved"
        ? `Resolved · ${exactDiagnostics.score_gap} point lead`
        : exactDiagnostics.reason
      : null;
    const exactProgress=Number(exactDiagnostics.confirmation_progress||0);
    const exactRequired=Number(exactDiagnostics.confirmation_required||2);
    const followUpLabels={
      "waiting-for-fresh-foil-sample":"Sampling foil response…",
      "timed-out-safely":"No distinct foil sample yet — card remains safely unlocked",
      "selected-card-lost":"Selected card moved or disappeared — pick it again",
      "confirmed":"Exact version confirmed",
    };
    const artworkScore=firstCardValue(card,["visual_score","artwork_score"]);
    const rows=[
      ["Exact-version decision",exactDecision],
      ["Version confirmation",exactProgress?`${exactProgress}/${exactRequired} distinct captures`:null],
      ["Follow-up sample",followUpLabels[exactDiagnostics.follow_up_state]||null],
      ["Leading reference",exactLeader?`${exactLeader.collector_number||"--"} · score ${exactLeader.score}`:null],
      ["Runner-up reference",exactRunnerUp?`${exactRunnerUp.collector_number||"--"} · score ${exactRunnerUp.score}`:null],
      [
        "Temporal confirmation",
        snapshot.temporal_confirmation===true
          ?`Verified across ${Number(snapshot.temporal_confirmation_count||temporalRequired)} stable scans`
          :temporalProgress>0
          ?`Confirming ${temporalProgress}/${temporalRequired}`
          :null,
      ],
      [
        "Artwork match",
        artworkScore!==null
          ? `${context.verified?"Strong · ":""}${Math.round(normalize(artworkScore)*100)}% visual confidence`
          : null,
      ],
      ["Collector number",firstCardValue(card,["collector_number","card_number"])?(context.verified?"Confirmed":firstCardValue(card,["collector_number","card_number"])):null],
      ["Set confirmation",firstCardValue(card,["set_name","set","set_code","set_id"])?(context.verified?"Confirmed":firstCardValue(card,["set_name","set","set_code","set_id"])):null],
      ["Language",firstCardValue(card,["language","language_name","language_code"])?(context.verified?"Confirmed":firstCardValue(card,["language","language_name","language_code"])):null],
      ["Variant",firstCardValue(card,["variant","variant_name","rarity_variant"])],
    ].filter(([,value])=>value!==null&&value!==undefined&&String(value).trim());
    evidence.dataset.summaryLabel=context.verified?"Identity verified":"Identity evidence";
    evidence.replaceChildren();
    rows.forEach(([label,value])=>{
      const row=document.createElement("div");
      const name=document.createElement("span");
      const detail=document.createElement("b");
      name.textContent=label;
      detail.textContent=String(value);
      row.append(name,detail);
      evidence.appendChild(row);
    });
    evidence.hidden=!rows.length;
  }
  setStudioXWidgetState(
    "identify",
    context.verified
      ?"available"
      : scanning
      ?"verification-in-progress"
      : context.card
      ?"review-needed"
      :"empty"
  );
}

function renderAIGradeWidget(context){
  const grading=context.grading||{};
  const values={
    aiGradeCentering:grading.centering,
    aiGradeCorners:grading.corners,
    aiGradeEdges:grading.edges,
    aiGradeSurface:grading.surface,
    aiGradeRange:grading.estimated_range,
    aiGradeConfidence:grading.confidence,
  };
  setCardText(
    "aiGradeState",
    context.gradeState==="waiting-for-stable-capture"
      ?"Waiting for a stable card capture"
      : context.gradeState==="unavailable"
      ?"Unavailable"
      : context.gradeState.replaceAll("-"," "),
    "Unavailable"
  );
  Object.entries(values).forEach(([id,value])=>{
    setCardText(id,value,"Pending");
  });
  const gradeMetrics=$("aiGradeMetrics");
  if(gradeMetrics){
    gradeMetrics.hidden=!Object.values(values).some(
      value=>value!==undefined&&value!==null&&value!==""
    );
  }
  const emptyDetail=$("aiGradeEmptyDetail");
  if(emptyDetail){
    const hasMetrics=Object.values(values).some(
      value=>value!==undefined&&value!==null&&value!==""
    );
    emptyDetail.hidden=hasMetrics;
    emptyDetail.textContent=
      context.gradeState==="waiting-for-stable-capture"
        ?"Waiting for a stable card capture."
        :"AI Grade is unavailable because no grading provider is connected.";
  }
  setStudioXWidgetState("ai-grade",context.gradeState);
}

function renderMarketWidget(context){
  const scanning=!context.verified&&!["ready","error"].includes(context.presentation.key);
  const state=context.card&&context.verified?context.market.key:"identity-pending";
  const hasMetrics=["available","stale","unverified","conflict"].includes(state);
  const messages={
    pending:"Retrieving market intelligence",
    available:"Current public market data",
    stale:"Stale quote · refresh before using for valuation",
    unverified:"Quote available · provenance is not strong enough for verified valuation",
    conflict:"Provider conflict · review comparable quotes before valuation",
    "no-data":"No verified market data is available for this card.",
    "provider-error":"Market provider unavailable.",
    "identity-pending":"Waiting for confirmed identity",
  };
  setCardText("marketWidgetState",messages[state],"No public market data.");
  const marketWidget=document.querySelector('[data-studiox-widget="market"]');
  marketWidget?.querySelectorAll(".ui4-price-primary,.ui4-price-grid").forEach(node=>{
    node.hidden=!hasMetrics;
  });
  const footnote=marketWidget?.querySelector(".ui4-price-footnote");
  if(footnote){
    footnote.hidden=!["available","stale","unverified","conflict","pending"].includes(state);
  }
  if($("cardValue")){
    $("cardValue").textContent=
      state==="identity-pending"
        ?"Waiting for confirmed identity"
        : state==="pending"
        ?"Retrieving market intelligence"
        : state==="no-data"&&context.verified
        ?"No public market data"
        : state==="provider-error"
        ?"Market provider unavailable"
        : state==="stale"
        ?"Stale quote · refresh required"
        : state==="unverified"
        ?"Unverified market quote"
        : state==="conflict"
        ?"Conflicting provider quotes"
        : $("cardValue").textContent;
  }
  setStudioXWidgetState(
    "market",
    state==="pending"
      ? "fetching"
      : state==="provider-error"
      ? "provider-unavailable"
      : state
  );
}

function renderCandidatesWidget(context){
  const count=context.candidates.length;
  const searching=!context.verified&&["detecting","scanning","candidate-found","verifying"].includes(context.presentation.key);
  setCardText(
    "candidateWidgetSummary",
    count
      ? `${count} alternative candidate${count===1?"":"s"} available for review.`
      : searching
      ? "Searching catalog candidates"
      : context.verified
      ? "Exact identity verified. No alternative candidates require review."
      : context.presentation.key==="review-needed"
      ? "No verified candidates found"
      : "No alternative candidates are available."
  );
  setStudioXWidgetState(
    "candidates",
    context.presentation.key==="error"
      ? "error"
      : context.presentation.key==="review-needed"
      ? "review-needed"
      : count
      ? "alternatives-available"
      : searching
      ? "searching"
      : context.verified
      ? "verified"
      : "no-candidates"
  );
  const reviewButton=$("candidateReviewButton");
  const correctButton=$("correctMatchButton");
  const correctionAvailable=count>0&&Boolean(context.card);
  if(reviewButton){
    reviewButton.hidden=!correctionAvailable;
    reviewButton.textContent=context.verified?"Correct Match":"Review Candidates";
  }
  if(correctButton){
    correctButton.hidden=!correctionAvailable;
    correctButton.textContent=context.verified?"Correct Match":"Review Match";
  }
}

function renderDetailsWidget(context){
  const widget=document.querySelector('[data-studiox-widget="details"]');
  const available=context.verified&&context.card;
  if(widget&&!available) widget.dataset.widgetSize="compact";
  setStudioXWidgetState("details",available?"available":"empty");
}

function renderDiagnosticsWidget(context){
  const snapshot=context.snapshot||{};
  const card=context.card||{};
  const detectedCollector=
    snapshot.ocr_collector_number||null;
  const printedCode=
    snapshot.ocr_printed_code||null;
  const collectorConfidence=normalize(
    snapshot.ocr_confidence??
    0
  );
  const identifierVerified=Boolean(
    snapshot.identifier_reference_match===true
  );
  setCardText("diagnosticRecognitionState",context.presentation.title);
  setCardText(
    "diagnosticVisualConfidence",
    `${Math.round(context.visualConfidence*100)}%`
  );
  setCardText(
    "diagnosticCatalogVerification",
    context.verified?"Verified":"Not verified"
  );
  setCardText(
    "diagnosticPipelineState",
    context.presentation.key.replaceAll("-"," ")
  );
  setCardText("diagnosticCollectorNumber",detectedCollector,"Waiting");
  setCardText("diagnosticPrintedCode",printedCode,"Waiting");
  setCardText(
    "diagnosticCollectorConfidence",
    `${Math.round(collectorConfidence*100)}%`
  );
  setCardText(
    "diagnosticIdentifierVerification",
    identifierVerified
      ? "Reference confirmed"
      : detectedCollector||printedCode
      ? "Evidence captured"
      : "Pending"
  );
  setStudioXWidgetState(
    "diagnostics",
    context.presentation.key==="error"?"error":"available"
  );
}

function renderAutoScreenshotWidget(){
  renderAutoScreenshotConfig();
}

let studioXPokedexKey=null;
let studioXPokedexPayload=null;
let studioXPokedexLoading=false;
let studioXPokedexOnAir=false;

function renderPokedexPayload(payload){
  const pokemon=payload?.pokemon||null;
  const content=$("pokedexContent");
  const empty=$("pokedexEmpty");
  if(content) content.hidden=!pokemon;
  if(empty){
    empty.hidden=Boolean(pokemon);
    empty.textContent=studioXPokedexLoading
      ?"Loading Rare Intelligence…"
      :"Scan and verify a card to load Rare Intelligence.";
  }
  if(pokemon){
    setCardText("pokedexNumber",pokemon.id?`#${String(pokemon.id).padStart(4,"0")} · RARE INTELLIGENCE`:"RARE INTELLIGENCE");
    setCardText("pokedexName",pokemon.name);
    setCardText("pokedexGenus",pokemon.genus,"Species data");
    setCardText("pokedexHeight",pokemon.height_m!=null?`${pokemon.height_m} m`:null);
    setCardText("pokedexWeight",pokemon.weight_kg!=null?`${pokemon.weight_kg} kg`:null);
    setCardText("pokedexAbilities",(pokemon.abilities||[]).join(", "));
    setCardText("pokedexFlavor",pokemon.flavor_text,"");
    const artwork=$("pokedexArtwork");
    if(artwork){
      artwork.hidden=!pokemon.artwork_url;
      if(pokemon.artwork_url) artwork.src=pokemon.artwork_url;
    }
    const types=$("pokedexTypes");
    if(types){
      types.replaceChildren(...(pokemon.types||[]).map(type=>{
        const chip=document.createElement("span");
        chip.textContent=String(type).toUpperCase();
        chip.dataset.type=String(type).toLowerCase();
        return chip;
      }));
    }
  }
  if(typeof payload?.on_air==="boolean") studioXPokedexOnAir=payload.on_air;
  const held=payload?.held===true;
  const provisional=payload?.provisional===true&&!held;
  const heldNotice=$("pokedexHeldNotice");
  if(heldNotice){
    heldNotice.hidden=!(held||provisional);
    heldNotice.setAttribute("aria-live","polite");
  }
  setCardText("pokedexProfileNoticeLabel",provisional?"Current species":"Last verified profile");
  setCardText(
    "pokedexProfileNoticeCopy",
    provisional
      ?"Species follows the current card. Exact set and printing are still being verified."
      :"Selected card is still provisional. Holding verified intelligence."
  );
  const multiCardHeldNotice=$("multiCardHeldNotice");
  if(multiCardHeldNotice){
    multiCardHeldNotice.hidden=!held;
    multiCardHeldNotice.setAttribute("aria-live","polite");
  }
  const widget=document.querySelector('[data-studiox-widget="pokedex"]');
  if(widget){
    widget.classList.toggle("is-held-profile",held);
    widget.classList.toggle("is-provisional-profile",provisional);
  }
  const onAir=studioXPokedexOnAir;
  if($("pokedexOnAir")) $("pokedexOnAir").checked=onAir;
  setCardText(
    "pokedexBroadcastStatus",
    provisional
      ?onAir?"Current species live · printing provisional":"Current species · printing provisional"
      :held
      ?onAir?"Held verified profile live on 16:9 source":"Held profile · 16:9 overlay hidden"
      :onAir?"Live on 16:9 browser source":"16:9 overlay hidden"
  );
  const tier=String(payload?.reveal?.hit_tier||"");
  setCardText(
    "rareIntelligenceRevealTier",
    tier?`${tier.replaceAll("-"," ")} · ${payload.reveal.reaction_copy||"Card revealed"}`:"Waiting for verified rarity"
  );
}

async function loadStudioXPokedex(key){
  if(studioXPokedexLoading) return;
  studioXPokedexLoading=true;
  renderPokedexPayload(null);
  try{
    const payload=await api("/api/rare-intelligence/current");
    if(studioXPokedexKey!==key) return;
    studioXPokedexPayload=payload;
    renderPokedexPayload(payload);
  }catch(error){
    console.warn("pokedex_load_failed",error);
    setStudioXWidgetState("pokedex","error");
  }finally{
    studioXPokedexLoading=false;
    // Card changes can arrive while the previous species request is in flight.
    // Resolve the newest key immediately instead of leaving the old profile on
    // screen until another unrelated workspace render happens.
    if(studioXPokedexKey&&studioXPokedexKey!==key){
      void loadStudioXPokedex(studioXPokedexKey);
    }
  }
}

async function hydrateHeldRareIntelligence(){
  try{
    const payload=await api("/api/rare-intelligence/current");
    if(payload?.pokemon&&payload?.held===true){
      studioXPokedexPayload=payload;
      renderPokedexPayload(payload);
      setStudioXWidgetState("pokedex",payload.status||"available");
    }
  }catch(error){
    console.warn("held_rare_intelligence_hydration_failed",error);
  }
}

function renderPokedexWidget(context){
  const card=context?.card&&context?.snapshot?.result_current!==false?context.card:null;
  const key=card?String(card.id||`${card.set_id||""}:${card.collector_number||""}:${card.name||card.english_name||""}`):null;
  if(!key){
    const currentCardPresent=context?.snapshot?.card_present===true||context?.snapshot?.recognition_locked===true;
    if(currentCardPresent){
      studioXPokedexKey=null;
      studioXPokedexPayload=null;
      renderPokedexPayload({status:"pending",reason:"current_species_pending",pokemon:null,held:false,provisional:true});
      setStudioXWidgetState("pokedex","pending");
      return;
    }
    if(studioXPokedexPayload?.held===true&&studioXPokedexPayload?.pokemon){
      renderPokedexPayload(studioXPokedexPayload);
      setStudioXWidgetState("pokedex",studioXPokedexPayload.status||"available");
      return;
    }
    studioXPokedexKey=null;
    studioXPokedexPayload=null;
    renderPokedexPayload(null);
    setStudioXWidgetState("pokedex","empty");
    return;
  }
  setStudioXWidgetState("pokedex",studioXPokedexPayload?studioXPokedexPayload.status:"fetching");
  if(key!==studioXPokedexKey){
    studioXPokedexKey=key;
    studioXPokedexPayload=null;
    loadStudioXPokedex(key);
  }else{
    renderPokedexPayload(studioXPokedexPayload);
  }
}

async function setPokedexOnAir(enabled){
  const payload=await api("/api/rare-intelligence/on-air",{
    method:"POST",
    body:JSON.stringify({enabled:Boolean(enabled)})
  });
  studioXPokedexOnAir=Boolean(payload.on_air);
  studioXPokedexPayload={...(studioXPokedexPayload||{}),on_air:studioXPokedexOnAir};
  renderPokedexPayload(studioXPokedexPayload);
}

const RARE_INTELLIGENCE_THEME_DEFAULTS={preset:"rareiq",accent_color:"#53d5f2",secondary_color:"#b574ff",background_color:"#05111e",text_color:"#f7fbff",panel_opacity:.94,corner_radius:30,scale:100,alignment:"left",font:"inter",brand_text:"RAREIQ · LIVE INTELLIGENCE",show_art:true,show_facts:true,show_flavor:true,show_brand:true};
const RARE_INTELLIGENCE_THEME_PRESETS={
  rareiq:{...RARE_INTELLIGENCE_THEME_DEFAULTS},
  minimal:{preset:"minimal",accent_color:"#f8fafc",secondary_color:"#94a3b8",background_color:"#080c12",text_color:"#f8fafc",panel_opacity:.76,corner_radius:14,scale:90,alignment:"left",font:"system",brand_text:"",show_art:true,show_facts:false,show_flavor:false,show_brand:false},
  broadcast:{preset:"broadcast",accent_color:"#ffd166",secondary_color:"#ff5c8a",background_color:"#140b20",text_color:"#ffffff",panel_opacity:.97,corner_radius:24,scale:110,alignment:"right",font:"inter",brand_text:"LIVE CARD INTELLIGENCE",show_art:true,show_facts:true,show_flavor:true,show_brand:true}
};
const RI_THEME_FIELDS={preset:"riThemePreset",accent_color:"riThemeAccent",secondary_color:"riThemeSecondary",background_color:"riThemeBackground",text_color:"riThemeText",alignment:"riThemeAlignment",font:"riThemeFont",brand_text:"riThemeBrandText",show_art:"riThemeShowArt",show_facts:"riThemeShowFacts",show_flavor:"riThemeShowFlavor",show_brand:"riThemeShowBrand"};
function readRareIntelligenceTheme(){
  const theme={...RARE_INTELLIGENCE_THEME_DEFAULTS};
  Object.entries(RI_THEME_FIELDS).forEach(([key,id])=>{const input=$(id);if(input) theme[key]=input.type==="checkbox"?input.checked:input.value});
  theme.panel_opacity=Number($("riThemeOpacity")?.value||94)/100;
  theme.corner_radius=Number($("riThemeRadius")?.value||30);
  theme.scale=Number($("riThemeScale")?.value||100);
  return theme;
}
function renderRareIntelligenceTheme(theme={}){
  const value={...RARE_INTELLIGENCE_THEME_DEFAULTS,...theme};
  Object.entries(RI_THEME_FIELDS).forEach(([key,id])=>{const input=$(id);if(input){if(input.type==="checkbox") input.checked=Boolean(value[key]);else input.value=value[key]}});
  if($("riThemeOpacity")) $("riThemeOpacity").value=Math.round(value.panel_opacity*100);
  if($("riThemeRadius")) $("riThemeRadius").value=value.corner_radius;
  if($("riThemeScale")) $("riThemeScale").value=value.scale;
  if($("riThemeOpacityValue")) $("riThemeOpacityValue").value=`${Math.round(value.panel_opacity*100)}%`;
  if($("riThemeRadiusValue")) $("riThemeRadiusValue").value=`${value.corner_radius}px`;
  if($("riThemeScaleValue")) $("riThemeScaleValue").value=`${value.scale}%`;
  $("rareIntelligenceThemePreview")?.contentWindow?.postMessage({type:"rare-intelligence-theme-preview",theme:value},location.origin);
}
async function loadRareIntelligenceTheme(){
  const payload=await api("/api/overlay/state");
  renderRareIntelligenceTheme(payload?.state?.rare_intelligence_theme);
}
async function saveRareIntelligenceTheme(){
  const theme=readRareIntelligenceTheme();
  await api("/api/overlay/state",{method:"POST",body:JSON.stringify({state:{rare_intelligence_theme:theme}})});
  studioXPokedexPayload={...(studioXPokedexPayload||{}),theme};
  renderRareIntelligenceTheme(theme);
  setCardText("rareIntelligenceThemeStatus","Saved · live source updated");
}

const STUDIOX_WIDGET_RENDERERS={
  identify:renderIdentifyWidget,
  pokedex:renderPokedexWidget,
  "reveal-animations":()=>{},
  soundboard:()=>{},
  "ai-grade":renderAIGradeWidget,
  market:renderMarketWidget,
  candidates:renderCandidatesWidget,
  details:renderDetailsWidget,
  diagnostics:renderDiagnosticsWidget,
  "auto-screenshot":renderAutoScreenshotWidget,
};

function updateSharedCardContext(context){
  window.__rareiqCardContext=context;
  observeCardEntryFeedback(context.snapshot||{});
  observeCompletedCardRemoval(context.snapshot||{});
  observePackSpeedStallRecovery(context).catch(error=>console.warn("pack_speed_recovery_failed",error));
  renderPackSpeedAutomationState(context);
  document.body.dataset.presentationState=context.presentation.key;
  applyStudioXExactMatchMoment(context);
  updateViewerInspectionHeader(context);
  applyRecognitionPresentation(context.presentation);
  if(context.verified===true){
    updateConfidenceRing(Math.max(
      normalize(context.presentation?.confidence||0),
      normalize(context.visualConfidence||0),
      normalize(context.card?.fused_score??context.card?.score??0),
      normalize(context.snapshot?.overall_confidence??context.snapshot?.confidence??0)
    ));
  }
  renderAuthoritativeCardContextHeader(context);
  applyStudioXViewerPresentation(
    context,
    window.__rareiqVisionTelemetry||{}
  );
  renderSecondaryWorkspaceBay(context);
  const actionable=context.verified===true;
  ["approveButton","rejectButton","detailsButton"].forEach(id=>{
    const button=$(id);
    if(button) button.disabled=!actionable;
  });
  if($("nextClearButton")) $("nextClearButton").disabled=false;
  queueMicrotask(()=>maybeAutoAddVerified(context).catch(error=>console.error("auto_add_verified_failed",error)));
  Object.entries(STUDIOX_WIDGET_RENDERERS).forEach(([id,renderer])=>{
    try{
      renderer(context);
    }catch(error){
      console.warn(`Studio X widget ${id} failed`,error);
      setStudioXWidgetState(id,"error");
    }
  });
  document.dispatchEvent(
    new CustomEvent("rareiq:card-context",{detail:context})
  );
}

function applyStudioXExactMatchMoment(context={}){
  syncResultDecisionStrip();
  const exact=context?.presentation?.key==="exact-match"&&context?.verified===true;
  if(!exact){
    document.body.classList.remove("studiox-exact-match-moment");
    if(["ready","detecting","scanning"].includes(context?.presentation?.key)){
      studioXExactMatchMomentKey=null;
    }
    return;
  }
  const key=[
    currentServerSessionId||"server",
    context?.snapshot?.generation??"generation",
    context?.identityKey||"card",
  ].join(":");
  if(key===studioXExactMatchMomentKey) return;
  studioXExactMatchMomentKey=key;
  clearTimeout(studioXExactMatchMomentTimer);
  document.body.classList.remove("studiox-exact-match-moment");
  requestAnimationFrame(()=>{
    document.body.classList.add("studiox-exact-match-moment");
    studioXExactMatchMomentTimer=setTimeout(()=>{
      document.body.classList.remove("studiox-exact-match-moment");
    },720);
  });
}

function syncMobileOperatorDeck(){
  const sourceName=$("cardName")?.textContent?.trim();
  const name=sourceName&&sourceName!=="No verified identity"&&sourceName!=="—"?sourceName:"Waiting for card";
  const confidence=$("confidenceRingValue")?.textContent?.trim()||"0%";
  const state=$("identityVerdictBadge")?.textContent?.trim()||$("recognitionStateLabel")?.textContent?.trim()||"SEARCHING";
  setCardText("mobileOperatorCardName",name);
  setCardText("mobileOperatorConfidence",confidence);
  setCardText("mobileOperatorState",state);
  const connectionUnavailable=["offline","unreachable","checking"].includes(serverConnectionState);
  const connectionLabel={offline:"OFFLINE",unreachable:"UNREACHABLE",checking:"CHECKING",reconnected:"RESTORED",connected:"ONLINE"}[serverConnectionState]||"UNREACHABLE";
  setCardText("mobileOperatorConnection",connectionLabel);
  const region=document.querySelector(".ui4-mobile-action-region");
  const decisionAvailable=name!=="Waiting for card"&&(!$("approveButton")?.disabled||!$("rejectButton")?.disabled);
  const recognitionProcessing=name!=="Waiting for card"&&!decisionAvailable;
  const actions=ui4InspectorView==="recent"?"history":decisionAvailable?"decision":recognitionProcessing?"processing":"scan";
  if(region){region.dataset.state=state.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")||"searching";region.dataset.connection=serverConnectionState;region.dataset.actions=actions}
  if($("mobileOperatorWorking")) $("mobileOperatorWorking").textContent=/VERIFY|CANDIDATE/.test(state.toUpperCase())?"Verifying":"Working";
  if($("mobileOperatorNext")) $("mobileOperatorNext").disabled=connectionUnavailable||Boolean($("nextClearButton")?.disabled);
  if($("mobileOperatorCapture")) $("mobileOperatorCapture").disabled=connectionUnavailable||Boolean(document.querySelector(".premium-capture-action")?.disabled);
  if($("mobileOperatorApprove")) $("mobileOperatorApprove").disabled=connectionUnavailable||Boolean($("approveButton")?.disabled);
  if($("mobileOperatorReject")) $("mobileOperatorReject").disabled=connectionUnavailable||Boolean($("rejectButton")?.disabled);
  if($("mobileOperatorReconnect")) $("mobileOperatorReconnect").disabled=connectionUnavailable;
}

function setMobileOperatorView(requested,{persist=true}={}){
  const view=["camera","both","card"].includes(requested)?requested:"both";
  document.body.dataset.mobileOperatorView=view;
  syncMobileOperatorViewButtons();
  if(persist){try{localStorage.setItem(MOBILE_OPERATOR_VIEW_KEY,view)}catch(_error){}}
  return view;
}

function syncMobileOperatorViewButtons(){
  const recent=ui4InspectorView==="recent";
  document.querySelectorAll(".mobile-operator-view-switcher [data-mobile-operator-view]").forEach(button=>button.setAttribute("aria-pressed",!recent&&button.dataset.mobileOperatorView===document.body.dataset.mobileOperatorView?"true":"false"));
  document.querySelector(".mobile-operator-view-switcher [data-mobile-operator-destination='recent-scans']")?.setAttribute("aria-pressed",recent?"true":"false");
}

function setMobileOperatorDestination(destination){
  if(destination==="recent-scans"){
    setMobileOperatorView("card");
    setUI4InspectorView("recent");
    return "recent-scans";
  }
  const view=setMobileOperatorView(destination);
  setUI4InspectorView("current",false);
  return view;
}

function syncResultDecisionStrip(){const name=$("cardName")?.textContent?.trim()||"No verified identity",number=$("cardCollectorNumber")?.textContent?.trim()||"—",confidence=$("confidenceRingValue")?.textContent?.trim()||"0%",verdict=$("identityVerdictBadge")?.textContent?.trim()||$("recognitionStateLabel")?.textContent?.trim()||"WAITING FOR CARD";if($("decisionCardName"))$("decisionCardName").textContent=name;if($("decisionCollectorNumber"))$("decisionCollectorNumber").textContent=number;if($("decisionConfidence"))$("decisionConfidence").textContent=confidence;if($("decisionVerdict"))$("decisionVerdict").textContent=verdict;[["decisionApproveButton","approveButton"],["decisionRejectButton","rejectButton"],["decisionNextButton","nextClearButton"]].forEach(([target,source])=>{if($(target))$(target).disabled=Boolean($(source)?.disabled)});syncMobileOperatorDeck();}

function initializeStudioXUI4(){
  if(document.body.dataset.ui4Initialized==="true") return;
  const camera=document.querySelector(".camera-workspace");
  const inspector=document.querySelector(".inspector");
  const inspectorMount=document.querySelector(".ui4-inspector-column");
  const pipeline=document.querySelector(".pipeline-rail");
  const dock=document.querySelector(".dock");
  const toolbar=document.querySelector(".toolbar");
  const appbar=document.querySelector(".appbar");
  if(!camera||!inspector||!inspectorMount||!pipeline||!dock||!toolbar||!appbar) return;
  document.body.dataset.ui4Initialized="true";
  const mobileOperator=document.querySelector(".ui4-mobile-action-region");
  if(mobileOperator&&mobileOperator.parentElement!==document.body) document.body.appendChild(mobileOperator);
  let savedMobileOperatorView="both";
  try{savedMobileOperatorView=localStorage.getItem(MOBILE_OPERATOR_VIEW_KEY)||"both"}catch(_error){}
  setMobileOperatorView(savedMobileOperatorView,{persist:false});
  initializeInspectorResize();
  const decisionActions=document.querySelector(".result-decision-actions"),correctMatch=$("correctMatchButton");
  if(decisionActions&&correctMatch&&correctMatch.parentElement!==decisionActions)decisionActions.insertBefore(correctMatch,$("decisionNextButton"));
  $("decisionApproveButton")?.addEventListener("click",operatorApprove);
  $("decisionRejectButton")?.addEventListener("click",operatorReject);
  $("decisionNextButton")?.addEventListener("click",()=>$("nextClearButton")?.click());
  $("mobileOperatorCapture")?.addEventListener("click",()=>Promise.resolve().then(()=>captureRecognitionMode()).catch(error=>notify("Capture Failed",error.message||String(error),"error")));
  $("mobileOperatorApprove")?.addEventListener("click",()=>$("approveButton")?.click());
  $("mobileOperatorReject")?.addEventListener("click",()=>$("rejectButton")?.click());
  $("mobileOperatorHistoryLive")?.addEventListener("click",()=>setMobileOperatorDestination("card"));
  $("mobileOperatorHistoryRefresh")?.addEventListener("click",loadUI4RecentScans);
  $("mobileOperatorNext")?.addEventListener("click",()=>$("nextClearButton")?.click());
  $("mobileOperatorReconnect")?.addEventListener("click",()=>Promise.resolve().then(()=>reconnectCamera()).catch(error=>notify("Camera Reconnect Failed",error.message||String(error),"error")));
  $("mobileOperatorStatus")?.addEventListener("click",()=>setUI4HealthOpen(!ui4HealthOpen));
  document.querySelectorAll(".mobile-operator-view-switcher [data-mobile-operator-view]").forEach(button=>button.addEventListener("click",()=>setMobileOperatorDestination(button.dataset.mobileOperatorView)));
  document.querySelector(".mobile-operator-view-switcher [data-mobile-operator-destination='recent-scans']")?.addEventListener("click",()=>setMobileOperatorDestination("recent-scans"));
  const observeStudioXTarget=(observer,target,options)=>{if(typeof Node==="undefined"||!(target instanceof Node))return false;try{observer.observe(target,options);return true}catch(error){console.warn("Studio X observer skipped",error);return false}};
  const decisionObserver=new MutationObserver(syncResultDecisionStrip);["cardName","cardCollectorNumber","confidenceRingValue","identityVerdictBadge","recognitionStateLabel","approveButton","rejectButton","nextClearButton"].forEach(id=>observeStudioXTarget(decisionObserver,$(id),{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:["disabled","hidden"]}));
  const inspectorNavigationObserver=new MutationObserver(syncInspectorNavigationState);observeStudioXTarget(inspectorNavigationObserver,$("recognitionStateLabel"),{subtree:true,childList:true,characterData:true});syncResultDecisionStrip();syncInspectorNavigationState();
  document.querySelectorAll("[data-workbench-tab]").forEach(button=>button.addEventListener("click",()=>setStudioXWorkbenchTab(button.dataset.workbenchTab)));
  document.querySelectorAll("[data-workbench-tab]").forEach(button=>button.addEventListener("click",syncStudioXWorkbenchContext));
  $("workbenchPrimaryAction")?.addEventListener("click",runStudioXWorkbenchAction);
  $("marketRefreshButton")?.addEventListener("click",refreshCurrentMarket);
  $("manualPriceForm")?.addEventListener("submit",saveManualPrice);
  $("marketProviderComparison")?.addEventListener("toggle",event=>{if(event.currentTarget.open)loadMarketResolutionHistory().catch(()=>{})});
  document.querySelectorAll("[data-resolution-export]").forEach(button=>button.addEventListener("click",()=>exportMarketResolutionHistory(button.dataset.resolutionExport)));
  $("priceAlertForm")?.addEventListener("submit",event=>savePriceAlert(event).catch(error=>notify("Alert Not Saved",error.message||String(error),"error")));
  $("priceAlertClear")?.addEventListener("click",()=>clearPriceAlert().catch(error=>notify("Alert Not Cleared",error.message||String(error),"error")));
  setStudioXWorkbenchTab(localStorage.getItem(STUDIOX_WORKBENCH_TAB_KEY)||"card",false);
  syncStudioXWorkbenchContext();
  const savedDensity=localStorage.getItem("rareiq.workspaceDensity")||"balanced";
  document.body.dataset.workspaceDensity=["compact","balanced","focus"].includes(savedDensity)?savedDensity:"balanced";
  document.querySelectorAll("button[data-workspace-density]").forEach(button=>{button.setAttribute("aria-pressed",String(button.dataset.workspaceDensity===document.body.dataset.workspaceDensity));button.addEventListener("click",event=>{event.stopPropagation();document.body.dataset.workspaceDensity=button.dataset.workspaceDensity;localStorage.setItem("rareiq.workspaceDensity",button.dataset.workspaceDensity);document.querySelectorAll("button[data-workspace-density]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));notify("Workspace Rebalanced",button.dataset.workspaceDensity==="compact"?"Camera reduced · more room for tools":button.dataset.workspaceDensity==="focus"?"Camera focus restored":"Balanced production layout active","success");});});

  if(inspector.parentElement!==inspectorMount) inspectorMount.appendChild(inspector);
  if(pipeline.parentElement!==camera) camera.appendChild(pipeline);
  dock.classList.add("ui4-diagnostics-drawer");
  dock.setAttribute("aria-hidden","true");
  if(dock.parentElement!==camera) camera.appendChild(dock);

  const rail=document.querySelector(".ui4-navigation-rail");
  if(rail && !rail.querySelector('[data-ui4-action="rail"]')){
    const toggle=document.createElement("button");
    toggle.className="ui4-rail-toggle";
    toggle.dataset.ui4Action="rail";
    toggle.type="button";
    toggle.setAttribute("aria-label","Toggle compact navigation");
    toggle.textContent="Menu";
    toggle.addEventListener("click",()=>document.body.classList.toggle("ui4-rail-compact"));
    rail.prepend(toggle);
  }

  const recovery=toolbar.querySelector('[onclick="reconnectCamera()"]');
  if(recovery) recovery.textContent="Reconnect Camera";
  const manual=toolbar.querySelector('[onclick="captureCamera()"]');
  if(manual) manual.textContent="Capture";

  const healthButton=document.createElement("button");
  healthButton.className="ui4-command-button";
  healthButton.dataset.ui4Action="health";
  healthButton.type="button";
  healthButton.textContent="Status";
  healthButton.setAttribute("aria-expanded","false");
  healthButton.addEventListener("click",()=>setUI4HealthOpen(!ui4HealthOpen));

  const diagnosticsButton=document.createElement("button");
  diagnosticsButton.className="ui4-command-button";
  diagnosticsButton.dataset.ui4Action="diagnostics";
  diagnosticsButton.type="button";
  diagnosticsButton.textContent="Diagnostics";
  diagnosticsButton.setAttribute("aria-expanded","false");
  diagnosticsButton.addEventListener("click",()=>setUI4DiagnosticsOpen(!ui4DiagnosticsOpen));
  const actionsRow=toolbar.querySelector(".premium-actions-row")||toolbar;
  actionsRow.append(diagnosticsButton,healthButton);

  const healthPopover=document.createElement("div");
  healthPopover.className="ui4-health-popover";
  healthPopover.setAttribute("role","dialog");
  healthPopover.setAttribute("aria-label","System status and camera actions");
  healthPopover.setAttribute("aria-hidden","true");
  const lowFrequency=[
    toolbar.querySelector('[onclick="startSelectedCamera()"]'),
    toolbar.querySelector('[onclick="stopCamera()"]'),
    toolbar.querySelector('[onclick="openCameraPopout()"]'),
    $("resolutionBadge"),
    document.querySelector(".ui4-app-health"),
    document.querySelector(".system-status-strip"),
  ].filter(Boolean);
  lowFrequency.forEach(node=>healthPopover.appendChild(node));
  document.querySelector(".ui4-command-bar")?.appendChild(healthPopover);
  const mountHealthPopover=()=>{
    const target=window.matchMedia("(max-width: 959px)").matches?document.body:document.querySelector(".ui4-command-bar");
    if(target&&healthPopover.parentElement!==target) target.appendChild(healthPopover);
  };
  mountHealthPopover();
  window.addEventListener("resize",mountHealthPopover,{passive:true});
  arrangeCameraToolbar();
  window.addEventListener("resize",arrangeCameraToolbar,{passive:true});
  window.addEventListener("resize",applyInspectorWidth,{passive:true});

  const primaryTabs=inspector.querySelector(".ui4-inspector-primary-tabs");
  const currentView=document.createElement("div");
  currentView.className="ui4-current-card-view";
  const recentView=document.createElement("div");
  recentView.className="ui4-recent-scans-view";
  recentView.hidden=true;
  [...inspector.children].forEach(child=>{
    if(child!==primaryTabs&&!child.classList.contains("inspector-head")) currentView.appendChild(child);
  });
  inspector.append(currentView,recentView);
  $("inspectorSectionNav")?.addEventListener("click",event=>{
    const button=event.target.closest("[data-inspector-section]");
    const target=button?$(button.dataset.inspectorSection):null;
    if(!target)return;
    const offset=target.getBoundingClientRect().top-currentView.getBoundingClientRect().top+currentView.scrollTop-112;
    currentView.scrollTo({top:Math.max(0,offset),behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
    $("inspectorSectionNav")?.querySelectorAll("button").forEach(item=>item.setAttribute("aria-current",item===button?"true":"false"));
  });
  if($("inspectorEmpty")) $("inspectorEmpty").style.display="none";
  if($("inspectorMain")) $("inspectorMain").style.display="grid";
  primaryTabs?.querySelectorAll("[data-inspector-view]").forEach(button=>{
    button.addEventListener("click",()=>setUI4InspectorView(button.dataset.inspectorView));
  });

  const widgetWorkspace=$("widgetWorkspace");
  if(widgetWorkspace){
    widgetWorkspace.addEventListener("click",event=>{
      const actionButton=event.target.closest("[data-widget-action]");
      const widget=event.target.closest("[data-studiox-widget]");
      if(actionButton&&widget){
        updateStudioXWidgetLayout(
          widget.dataset.studioxWidget,
          actionButton.dataset.widgetAction
        );
        return;
      }
      const focusButton=event.target.closest("[data-widget-focus]");
      if(focusButton){
        setStudioXWidgetOverviewFocus(focusButton.dataset.widgetFocus);
      }
    });
    widgetWorkspace.addEventListener("dragstart",event=>{
      const handle=event.target.closest("[data-widget-drag-handle]");
      const widget=handle?.closest("[data-studiox-widget]");
      if(!handle||!widget) return;
      widgetWorkspace.dataset.draggedWidget=widget.dataset.studioxWidget;
      widget.classList.add("is-dragging");
      event.dataTransfer.effectAllowed="move";
      event.dataTransfer.setData("text/plain",widget.dataset.studioxWidget);
    });
    widgetWorkspace.addEventListener("dragover",event=>{
      const target=event.target.closest("[data-studiox-widget]");
      const sourceId=widgetWorkspace.dataset.draggedWidget;
      if(!sourceId||!target||target.dataset.studioxWidget===sourceId) return;
      event.preventDefault();
      event.dataTransfer.dropEffect="move";
      widgetWorkspace.querySelectorAll(".is-drop-before,.is-drop-after").forEach(widget=>{
        widget.classList.remove("is-drop-before","is-drop-after");
      });
      const bounds=target.getBoundingClientRect();
      target.classList.add(event.clientY>=bounds.top+(bounds.height/2)?"is-drop-after":"is-drop-before");
    });
    widgetWorkspace.addEventListener("drop",event=>{
      const target=event.target.closest("[data-studiox-widget]");
      const sourceId=widgetWorkspace.dataset.draggedWidget||event.dataTransfer.getData("text/plain");
      if(!sourceId||!target) return;
      event.preventDefault();
      const placeAfter=target.classList.contains("is-drop-after");
      reorderStudioXWidgetByDrop(sourceId,target.dataset.studioxWidget,placeAfter);
      delete widgetWorkspace.dataset.draggedWidget;
      clearStudioXWidgetDropIndicators(widgetWorkspace);
    });
    widgetWorkspace.addEventListener("dragend",()=>{
      delete widgetWorkspace.dataset.draggedWidget;
      clearStudioXWidgetDropIndicators(widgetWorkspace);
    });
  }
  document.querySelectorAll("[data-widget-visibility]").forEach(input=>{
    input.addEventListener("change",()=>{
      updateStudioXWidgetLayout(
        input.dataset.widgetVisibility,
        "visibility",
        input.checked
      );
    });
  });
  document.querySelector("[data-widget-reset]")?.addEventListener(
    "click",
    resetStudioXWidgetLayout
  );
  document.querySelector("[data-widget-expand-all]")?.addEventListener(
    "click",()=>setAllStudioXWidgetsCollapsed(false)
  );
  document.querySelector("[data-widget-collapse-all]")?.addEventListener(
    "click",()=>setAllStudioXWidgetsCollapsed(true)
  );
  studioXPreferences=loadStudioXPreferences();
  renderCardRemovalSettings();
  $("automaticCardRemovalEnabled")?.addEventListener("change",event=>{cardRemovalSettings.enabled=event.target.checked;saveCardRemovalSettings();renderCardRemovalSettings();notify("Card Handoff Updated",cardRemovalSettings.enabled?"Automatic card removal clearing is enabled.":"Use Next / Clear to advance cards.","success")});
  $("automaticCardRemovalSensitivity")?.addEventListener("change",event=>{cardRemovalSettings.sensitivity=CARD_REMOVAL_PRESETS[event.target.value]?event.target.value:"normal";saveCardRemovalSettings();renderCardRemovalSettings();notify("Removal Sensitivity Updated",`${CARD_REMOVAL_PRESETS[cardRemovalSettings.sensitivity].label} handoff timing active.`,"success")});
  $("cardHandoffSoundEnabled")?.addEventListener("change",event=>{cardRemovalSettings.soundEnabled=event.target.checked;saveCardRemovalSettings();renderCardRemovalSettings();notify("Ready Sound Updated",cardRemovalSettings.soundEnabled?"A quiet tone will confirm the next armed scan.":"Card handoff audio is off.","success")});
  $("latencyReportExport")?.addEventListener("click",exportRecognitionLatencyReport);
  $("latencyReportView")?.addEventListener("click",()=>setRecognitionLatencyReportOpen(true));
  $("latencyReportClose")?.addEventListener("click",()=>setRecognitionLatencyReportOpen(false));
  $("latencyReportDismiss")?.addEventListener("click",()=>setRecognitionLatencyReportOpen(false));
  $("latencyReportDownload")?.addEventListener("click",exportRecognitionLatencyReport);
  $("latencyReportOverlay")?.addEventListener("click",event=>{if(event.target===$("latencyReportOverlay"))setRecognitionLatencyReportOpen(false)});
  secondaryBayPreferences=loadSecondaryBayPreferences();
  cameraWorkspacePreferences=loadCameraWorkspacePreferences();
  applyWorkspaceLayoutPreset(
    studioXPreferences.layoutPreset,
    {persist:false}
  );
  $("workspaceLayoutPreset")?.addEventListener("change",event=>{
    const preset=event.target.value;
    applyWorkspaceLayoutPreset(preset);
    announceWorkspaceLayoutPreset(preset);
  });
  $("viewerModeSelect")?.addEventListener("change",event=>{
    setStudioXViewerMode(event.target.value);
  });
  $("viewerZoomOut")?.addEventListener("click",()=>{
    adjustStudioXPreviewZoom(-.1);
  });
  $("viewerZoomReset")?.addEventListener("click",resetStudioXPreviewZoom);
  $("viewerZoomIn")?.addEventListener("click",()=>{
    adjustStudioXPreviewZoom(.1);
  });
  $("secondaryBayMode")?.addEventListener("change",event=>setSecondaryBayMode(event.target.value));
  $("secondaryBaySize")?.addEventListener("change",event=>{
    secondaryBayPreferences=normalizeSecondaryBayPreferences({...secondaryBayPreferences,size:event.target.value});
    saveSecondaryBayPreferences();
    renderSecondaryWorkspaceBay();
  });
  $("cameraSlot1Source")?.addEventListener("change",event=>setActiveCameraWorkspaceSource(event.target.value));
  $("stagingSourceSelect")?.addEventListener("change",event=>setCameraWorkspaceSource(2,event.target.value));
  $("swapSourcesButton")?.addEventListener("click",promoteSecondaryStagingSource);
  $("promoteStagingButton")?.addEventListener("click",()=>promoteCameraWorkspaceSlot(2));
  $("collapseSecondaryBay")?.addEventListener("click",()=>setSecondaryBayMode("hidden"));
  $("cameraWorkspaceLayout")?.addEventListener("click",event=>{
    const button=event.target.closest("[data-camera-layout-option]");
    if(button) setCameraWorkspaceLayout(button.dataset.cameraLayoutOption);
  });
  $("manageCamerasButton")?.addEventListener("click",()=>{
    const actions=document.querySelector(".camera-source-compact-menu");
    actions?.focus();
    actions?.scrollIntoView({block:"nearest",inline:"nearest"});
  });
  $("cameraPtzButton")?.addEventListener("click",async()=>{
    const panel=$("cameraPtzPanel");
    const opening=Boolean(panel?.hidden);
    if(panel){if(opening&&panel.parentElement!==document.body)document.body.append(panel);panel.hidden=!opening;if(opening)positionCameraPtzPanel()}
    $("cameraPtzButton").setAttribute("aria-expanded",String(opening));
    if(opening)await refreshCameraPtzStatus();
  });
  window.addEventListener("resize",positionCameraPtzPanel,{passive:true});
  $("cameraPtzPanel")?.addEventListener("click",event=>{
    if(event.target.closest("[data-ptz-close]")){
      $("cameraPtzPanel").hidden=true;
      $("cameraPtzButton").setAttribute("aria-expanded","false");
      return;
    }
    const button=event.target.closest("[data-ptz-action]");
    if(!button)return;
    let action=button.dataset.ptzAction;
    const preset=button.dataset.ptzPreset?Number(button.dataset.ptzPreset):null;
    if(preset&&event.shiftKey)action="save_preset";
    runCameraPtzAction(action,preset);
  });
  $("cameraPtzActivate")?.addEventListener("click",activateCameraPtzDevice);
  $("cameraPtzPanel")?.addEventListener("click",event=>{
    const stepper=event.target.closest("[data-camera-imaging]");
    if(stepper){
      const control=stepper.dataset.cameraImaging;
      const current=Number(cameraPtzSnapshot.properties?.[control]?.value||0);
      setCameraImagingControl(control,current+Number(stepper.dataset.cameraDelta||0));
      return;
    }
    const toggle=event.target.closest("[data-camera-imaging-toggle]");
    if(toggle){
      const control=toggle.dataset.cameraImagingToggle;
      const current=Number(cameraPtzSnapshot.properties?.[control]?.value||0);
      const value=control==="auto_exposure"?(current>=.5?.25:.75):(current>0?0:1);
      setCameraImagingControl(control,value);
    }
  });
  $("cameraSlot1Side")?.addEventListener("change",event=>setCameraWorkspaceSide(1,event.target.value));
  $("cameraSlot2Side")?.addEventListener("change",event=>setCameraWorkspaceSide(2,event.target.value));
  [3,4].forEach(slot=>{
    $(`cameraSlot${slot}Source`)?.addEventListener("change",event=>setCameraWorkspaceSource(slot,event.target.value));
    $(`cameraSlot${slot}Side`)?.addEventListener("change",event=>setCameraWorkspaceSide(slot,event.target.value));
    $(`promoteCameraSlot${slot}`)?.addEventListener("click",()=>promoteCameraWorkspaceSlot(slot));
  });
  if(secondaryBayPreferences.activeSource&&$("cameraSelect")){
    const savedActive=secondaryBayPreferences.activeSource;
    if([...$("cameraSelect").options].some(option=>option.value===savedActive)){
      $("cameraSelect").value=savedActive;
    }
  }
  renderSecondaryWorkspaceBay();
  cameraWorkspacePreferences.sources["1"]=$("cameraSelect")?.value||cameraWorkspacePreferences.sources["1"];
  cameraWorkspacePreferences.sources["2"]=secondaryBayPreferences.stagingSource||cameraWorkspacePreferences.sources["2"];
  saveCameraWorkspacePreferences();
  renderCameraWorkspace();
  studioXWidgetLayout=loadStudioXWidgetLayout();
  applyStudioXWidgetLayout();
  updateSharedCardContext(
    deriveSharedCardContext(
      deriveRecognitionPresentation({phase:"IDLE"},null,[]),
      null,
      {phase:"IDLE"},
      []
    )
  );

  const actions=document.querySelector(".inspector-actions");
  const reaction=actions?[...actions.querySelectorAll("button")].find(
    button=>["Reaction","Next Card","Next / Clear"].includes(button.textContent.trim())
  ):null;
  if(reaction){
    reaction.textContent="Next / Clear";
    reaction.addEventListener("click",()=>{
      requestNextRecognition().catch(error=>{
        delete document.body.dataset.cardHandoff;
        syncResultDecisionStrip();
        console.error("recognition_clear_failed",error);
      });
    });
  }
  setPremiumIntelligenceTab("identify");
  setUI4InspectorView("current",false);
  setUI4DiagnosticsOpen(false);
  setUI4HealthOpen(false);
  switchWorkspace("live");
}


document.addEventListener("DOMContentLoaded",()=>{
  initializeServerConnectionStatus();
  initializeVisibilityAwareRefresh();
  initializeMobileWakeLock();
  initializeStudioXInstallPrompt();
  initializeWorkspaceReadiness();
  initializeBroadcastWorkspace();
  loadTCGGames().then(loadRecognitionSets).catch(()=>loadRecognitionSets());
  $("tcgGameSelect")?.addEventListener("change",updateTCGSelection);
  renderAutoAddVerified();
  renderPackSpeedRun();
  $("packRunOpen")?.addEventListener("click",()=>setPackRunDetail(Boolean($("packRunDetail")?.hidden)));
  $("packRunClose")?.addEventListener("click",()=>setPackRunDetail(false));
  $("packRunCoachApply")?.addEventListener("click",()=>applyPackRunRecommendation().catch(error=>notify("Tuning Not Applied",error.message||String(error),"error")));
  $("packRunReset")?.addEventListener("click",resetPackSpeedRun);
  $("autoAddVerifiedEnabled")?.addEventListener("change",event=>{
    try{localStorage.setItem(AUTO_ADD_VERIFIED_KEY,String(event.target.checked))}catch(_error){}
    if(event.target.checked){
      lastAutoAddStateId=String(window.__rareiqCardContext?.snapshot?.state_id||"")||null;
      cardRemovalSettings.enabled=true;
      cardRemovalSettings.sensitivity="adaptive";
      saveCardRemovalSettings();
      renderCardRemovalSettings();
    }
    renderAutoAddVerified();
    notify("Pack Speed Updated",event.target.checked?"Armed for the next card · adaptive removal timing enabled.":"Manual approval mode active.","success");
  });
  $("setContextMode")?.addEventListener("change",updateRecognitionSetContext);
  $("setContextSelect")?.addEventListener("change",updateRecognitionSetContext);
  $("setContextSearch")?.addEventListener("input",event=>renderRecognitionSetOptions(event.target.value));
  $("workflowIdentifyButton")?.addEventListener("click",()=>chooseRecognitionWorkflow("identify").catch(error=>notify("Workflow Not Changed",error.message||String(error),"error")));
  $("workflowPackButton")?.addEventListener("click",()=>chooseRecognitionWorkflow("pack").catch(error=>notify("Workflow Not Changed",error.message||String(error),"error")));
  $("scanPackSetButton")?.addEventListener("click",scanPackSet);
  $("learnPackSetButton")?.addEventListener("click",learnPackSet);
  if($("packAutoDetect"))$("packAutoDetect").checked=packAutoDetectEnabled();
  $("packAutoDetect")?.addEventListener("change",event=>{try{localStorage.setItem(STUDIOX_PACK_AUTO_DETECT_KEY,String(event.target.checked))}catch(_error){}if(event.target.checked){packAutoLocked=false;schedulePackAutoDetect(100)}else stopPackAutoDetect();notify(event.target.checked?"Automatic Pack Detection On":"Automatic Pack Detection Off",event.target.checked?"Known wrappers will activate their set automatically.":"Use Scan Pack whenever you want to identify a wrapper.","success")});
  if($("packAutoAdvance"))$("packAutoAdvance").checked=packAutoAdvanceEnabled();
  $("packAutoAdvance")?.addEventListener("change",event=>{try{localStorage.setItem(STUDIOX_PACK_AUTO_ADVANCE_KEY,String(event.target.checked))}catch(_error){}notify(event.target.checked?"Automatic Card Handoff On":"Automatic Card Handoff Off",event.target.checked?"A confident pack match will begin card scanning automatically.":"Use Start Scanning Cards after each pack match.","success")});
  if($("packAutoNext"))$("packAutoNext").checked=packAutoNextEnabled();
  $("packAutoNext")?.addEventListener("change",event=>{try{localStorage.setItem(STUDIOX_PACK_AUTO_NEXT_KEY,String(event.target.checked))}catch(_error){}notify(event.target.checked?"Automatic Next Pack On":"Automatic Next Pack Off",event.target.checked?"Completing the final card will re-arm wrapper detection.":"Use Next Pack when the current pack is complete.","success")});
  ["packExpectedCards","packRareSlot"].forEach(id=>{const select=$(id);if(!(select instanceof HTMLSelectElement))return;if(!select.options.length)for(let value=1;value<=30;value++)select.append(new Option(String(value),String(value)));select.addEventListener("change",saveActivePackProfile)});applyPackProfile();
  $("packProfileApplySuggestion")?.addEventListener("click",async()=>{const box=$("packProfileSuggestion"),expected=Math.max(1,Number(box?.dataset.expectedCards)||10),rare=Math.max(1,Math.min(expected,Number(box?.dataset.rareSlot)||expected));if($("packExpectedCards"))$("packExpectedCards").value=String(expected);applyPackProfile({...packArtworkIndex.last_match,pack_profile:{expected_cards:expected,rare_slot:rare}});if($("packRareSlot"))$("packRareSlot").value=String(rare);await saveActivePackProfile();renderPackProfileSuggestion({})});
  $("packStartCardsButton")?.addEventListener("click",()=>startCardsFromPack(false));
  $("nextPackSessionButton")?.addEventListener("click",startNextPackSession);
  applyStudioTheme();
  document.querySelectorAll("[data-theme-choice]").forEach(button=>button.addEventListener("click",()=>applyStudioTheme(button.dataset.themeChoice,true)));
  $("studioThemeToggle")?.addEventListener("click",()=>applyStudioTheme(document.documentElement.dataset.theme==="light"?"dark":"light",true));
  initializeAutoScreenshotConfiguration();
  initializeStudioXUI4();
  loadMobileAccessStatus();
  $("mobileAccessRefresh")?.addEventListener("click",loadMobileAccessStatus);
  $("mobileAccessCopy")?.addEventListener("click",copyMobileAccessUrl);
  // Initial recognition/context rendering can clear the empty widget once.
  // Hydrate durable held intelligence after that startup pass settles.
  setTimeout(hydrateHeldRareIntelligence,300);
  $("recognitionModeSelect")?.addEventListener("change",event=>setRecognitionMode(event.target.value));
  $("singleCardPickerButton")?.addEventListener("click",()=>toggleSingleCardPicker().catch(error=>console.error("single_card_picker_failed",error)));
  $("multiCardCameraOverlay")?.addEventListener("click",event=>{
    if(!singleCardPickerActive||studioXRecognitionMode!=="single") return;
    const slot=event.target?.dataset?.slot;
    if(slot) recognizePickedSingleCard(slot).catch(error=>console.error("single_card_pick_failed",error));
  });
  $("multiCardCaptureButton")?.addEventListener("click",()=>captureMultiCardGrid().catch(error=>console.error("multi_card_capture_failed",error)));
  const uniqueVariants=$("multiCardUniqueVariants");
  if(uniqueVariants){
    try{uniqueVariants.checked=localStorage.getItem(STUDIOX_UNIQUE_VARIANTS_KEY)==="true"}catch(_error){}
    uniqueVariants.addEventListener("change",()=>{
      try{localStorage.setItem(STUDIOX_UNIQUE_VARIANTS_KEY,String(uniqueVariants.checked))}catch(_error){}
    });
  }
  const maxCards=$("multiCardMaxCards");
  if(maxCards){
    try{maxCards.value=localStorage.getItem(STUDIOX_MULTI_CARD_COUNT_KEY)||"12"}catch(_error){}
    maxCards.addEventListener("change",()=>{
      try{localStorage.setItem(STUDIOX_MULTI_CARD_COUNT_KEY,maxCards.value)}catch(_error){}
      document.querySelectorAll("[data-multi-card-slot]").forEach(node=>{node.hidden=Number(node.dataset.multiCardSlot)>Number(maxCards.value||6)});
    });
  }
  $("multiCardResults")?.addEventListener("click",event=>{
    const button=event.target.closest(".multi-card-show-toggle");
    if(button) toggleMultiCardOutput(button.dataset.slot).catch(error=>console.error("multi_card_select_failed",error));
  });
  let savedRecognitionMode="single";
  try{savedRecognitionMode=localStorage.getItem(STUDIOX_RECOGNITION_MODE_KEY)||"single"}catch(_error){}
  setRecognitionMode(savedRecognitionMode);
  $("pokedexOnAir")?.addEventListener("change",event=>{
    setPokedexOnAir(event.target.checked).catch(error=>{
      event.target.checked=!event.target.checked;
      console.error("pokedex_overlay_toggle_failed",error);
    });
  });
  $("rareIntelligenceCustomize")?.addEventListener("click",()=>{
    const editor=$("rareIntelligenceThemeEditor");if(!editor)return;
    editor.hidden=!editor.hidden;
    if(!editor.hidden) loadRareIntelligenceTheme().catch(error=>console.warn("rare_intelligence_theme_load_failed",error));
  });
  $("riThemeSave")?.addEventListener("click",()=>saveRareIntelligenceTheme().catch(error=>setCardText("rareIntelligenceThemeStatus",error.message||"Save failed")));
  $("riThemeReset")?.addEventListener("click",()=>{
    renderRareIntelligenceTheme(RARE_INTELLIGENCE_THEME_DEFAULTS);
    setCardText("rareIntelligenceThemeStatus","RareIQ defaults previewed · save to apply");
  });
  $("riThemePreset")?.addEventListener("change",event=>{
    const preset=RARE_INTELLIGENCE_THEME_PRESETS[event.target.value];
    if(!preset)return;
    renderRareIntelligenceTheme(preset);
    setCardText("rareIntelligenceThemeStatus",`${event.target.options[event.target.selectedIndex]?.text||"Preset"} previewed · save to apply`);
  });
  $("rareIntelligenceThemeEditor")?.addEventListener("input",()=>{
    if($("riThemePreset")&&document.activeElement?.id!=="riThemePreset") $("riThemePreset").value="custom";
    renderRareIntelligenceTheme(readRareIntelligenceTheme());
    setCardText("rareIntelligenceThemeStatus","Previewing unsaved changes");
  });
  setTimeout(()=>verifyAndConnectMainViewer(),120);
  const bridgeFeed=$("cameraFeed");
  if(bridgeFeed){
    bridgeFeed.addEventListener("load",()=>{
      markViewerLive();
      renderCameraFxControls();
      renderCameraFxFrame();
    });
    bridgeFeed.addEventListener("error",()=>{
      markViewerOffline();
      setViewerBridgeState("connecting","RECOVERING VIEWER");
      clearTimeout(viewerBridgeTimer);
      viewerBridgeTimer=setTimeout(()=>connectMainViewer(true),700);
    });
  }

  document.querySelectorAll(".nav-button").forEach(button=>{
    button.addEventListener("click",()=>switchWorkspace(button.dataset.target));
  });
  restoreVoiceModPreferences();
  $("voiceModStart")?.addEventListener("click",()=>startVoiceMod().catch(error=>{setVoiceModStatus("error","Microphone unavailable");notify("Voice Mod Not Started",error.message||String(error),"error")}));
  $("voiceModStop")?.addEventListener("click",()=>stopVoiceMod().catch(error=>notify("Voice Mod Not Stopped",error.message||String(error),"error")));
  $("voiceModRefresh")?.addEventListener("click",()=>refreshVoiceModInputs().then(devices=>notify("Microphones Refreshed",`${devices.length} input${devices.length===1?"":"s"} available.`,"success")).catch(error=>notify("Microphones Unavailable",error.message||String(error),"error")));
  ["voiceModGain","voiceModMix","voiceModOutput","voiceModMonitor"].forEach(id=>$(id)?.addEventListener("input",updateVoiceModLevels));
  $("voiceModInput")?.addEventListener("change",saveVoiceModPreferences);
  $("voiceModPreset")?.addEventListener("change",event=>{saveVoiceModPreferences();if($("voiceModPresetName"))$("voiceModPresetName").textContent=VOICE_MOD_PRESETS[event.target.value]||event.target.value;if(voiceModState.active)startVoiceMod().catch(error=>notify("Preset Not Applied",error.message||String(error),"error"))});
  navigator.mediaDevices?.addEventListener?.("devicechange",()=>refreshVoiceModInputs().catch(()=>{}));
  restoreCameraFxPreferences();
  $("cameraFxApply")?.addEventListener("click",toggleCameraFx);
  $("cameraFxReset")?.addEventListener("click",resetCameraFx);
  $("cameraFxPresets")?.addEventListener("click",event=>{const button=event.target.closest("[data-camera-fx-preset]");if(button)setCameraFxPreset(button.dataset.cameraFxPreset)});
  ["cameraFxBrightness","cameraFxContrast","cameraFxSaturation","cameraFxBlur","cameraFxTolerance","cameraFxSoftness","cameraFxKeyColor"].forEach(id=>$(id)?.addEventListener("input",()=>{renderCameraFxControls();renderCameraFxFrame()}));
  $("cameraFxChroma")?.addEventListener("change",()=>{renderCameraFxControls();renderCameraFxFrame()});
  $("refreshCollection")?.addEventListener("click",()=>loadCollection().catch(error=>{
    notify("Collection Unavailable",error.message||String(error),"error");
  }));
  $("librarySyncStart")?.addEventListener("click",()=>startLibrarySync().catch(error=>notify("Library Sync Unavailable",error.message||String(error),"error")));
  $("librarySyncPause")?.addEventListener("click",()=>pauseLibrarySync().catch(error=>notify("Library Sync Unavailable",error.message||String(error),"error")));
  $("inventoryIntakeForm")?.addEventListener("submit",event=>createInventoryItem(event).catch(error=>notify("Inventory Item Not Created",error.message||String(error),"error")));
  $("inventoryLookupForm")?.addEventListener("submit",event=>findInventoryItem(event).catch(error=>notify("Inventory Item Not Found",error.message||String(error),"error")));
  ["approvedInventoryAuto","approvedInventoryCostMode","approvedInventoryCost","approvedInventoryCardsPerPack","approvedInventoryCondition","approvedInventoryLocation","approvedInventoryLabel"].forEach(id=>$(id)?.addEventListener("change",saveApprovedInventoryPrefs));
  $("approvedInventoryAdd")?.addEventListener("click",()=>createApprovedInventory().catch(error=>notify("Inventory Not Created",error.message||String(error),"error")));
  renderApprovedInventoryPrefs();
  refreshApprovedInventoryCostPreview().catch(()=>{});
  $("priceAlertDesktop")?.addEventListener("change",savePriceAlertPrefs);
  $("priceAlertSound")?.addEventListener("change",savePriceAlertPrefs);
  $("priceAlertPermission")?.addEventListener("click",()=>requestPriceAlertNotifications().catch(error=>notify("Notifications Not Enabled",error.message||String(error),"error")));
  $("priceWatchRefresh")?.addEventListener("click",()=>refreshPriceWatchlist().catch(error=>notify("Watchlist Not Refreshed",error.message||String(error),"error")));
  syncPriceAlertNotificationControls();
  $("inventoryCheckoutForm")?.addEventListener("submit",event=>completeInventoryCheckout(event).catch(error=>notify("Sale Not Completed",error.message||String(error),"error")));
  $("inventoryApplyRecommendation")?.addEventListener("click",applyInventorySellRecommendation);
  $("inventorySaleChannel")?.addEventListener("change",()=>applyInventoryChannelPreset().catch(error=>notify("Preset Unavailable",error.message||String(error),"error")));
  $("inventoryFeePercent")?.addEventListener("change",()=>saveInventoryChannelPreset().catch(error=>notify("Preset Not Saved",error.message||String(error),"error")));
  ["inventoryShippingCost","inventoryPackagingCost"].forEach(id=>$(id)?.addEventListener("change",()=>saveInventoryFulfillmentPreset().catch(error=>notify("Fulfillment Profile Not Saved",error.message||String(error),"error"))));
  $("inventoryDesiredProfit")?.addEventListener("change",()=>updateInventorySellRecommendation().catch(error=>notify("Recommendation Unavailable",error.message||String(error),"error")));
  ["inventoryCheckoutClose","inventoryCheckoutCancel"].forEach(id=>$(id)?.addEventListener("click",closeInventoryCheckout));
  ["inventorySalePrice","inventorySaleFees","inventoryShippingCost"].forEach(id=>$(id)?.addEventListener("input",updateInventoryCheckoutPreview));
  $("inventoryCheckoutOverlay")?.addEventListener("click",event=>{if(event.target===$("inventoryCheckoutOverlay"))closeInventoryCheckout()});
  $("inventoryStartScanner")?.addEventListener("click",()=>startInventoryScanner().catch(error=>{stopInventoryScanner();notify("QR Scanner Unavailable",error.message||String(error),"error")}));
  $("inventoryScannerClose")?.addEventListener("click",stopInventoryScanner);$("inventoryScannerRetry")?.addEventListener("click",()=>startInventoryScanner().catch(error=>notify("Camera Not Started",error.message||String(error),"error")));
  $("inventoryScannerCamera")?.addEventListener("change",()=>startInventoryScanner().catch(error=>notify("Camera Not Started",error.message||String(error),"error")));
  $("inventoryScannerOverlay")?.addEventListener("click",event=>{if(event.target===$("inventoryScannerOverlay"))stopInventoryScanner()});
  $("inventorySelectAll")?.addEventListener("click",()=>selectAllInventoryLabels(true));
  $("inventoryClearSelection")?.addEventListener("click",()=>selectAllInventoryLabels(false));
  $("inventoryPrintSelected")?.addEventListener("click",printSelectedInventoryLabels);
  $("inventoryPrepareListings")?.addEventListener("click",()=>prepareInventoryListings().catch(error=>notify("Listings Not Prepared",error.message||String(error),"error")));
  $("inventoryListingStaleDays")?.addEventListener("change",()=>loadInventory().catch(error=>notify("Listing Dashboard Not Refreshed",error.message||String(error),"error")));
  $("inventoryListingSelectAll")?.addEventListener("click",()=>selectInventoryListings("all"));
  $("inventoryListingSelectStale")?.addEventListener("click",()=>selectInventoryListings("stale"));
  $("inventoryListingClear")?.addEventListener("click",()=>selectInventoryListings("none"));
  $("inventoryListingSmartReprice")?.addEventListener("click",()=>smartRepriceInventoryListings().catch(error=>notify("Smart Reprice Failed",error.message||String(error),"error")));
  $("inventoryListingReprice")?.addEventListener("click",()=>bulkUpdateInventoryListings("reprice").catch(error=>notify("Listings Not Repriced",error.message||String(error),"error")));
  $("inventoryListingEnd")?.addEventListener("click",()=>bulkUpdateInventoryListings("end").catch(error=>notify("Listings Not Ended",error.message||String(error),"error")));
  $("breakPerformanceApply")?.addEventListener("click",()=>loadInventory().catch(error=>notify("Report Filter Failed",error.message||String(error),"error")));
  $("breakPerformancePeriod")?.addEventListener("change",breakPerformanceQuery);
  $("breakPerformanceSet")?.addEventListener("input",breakPerformanceQuery);
  $("businessTrendDays")?.addEventListener("change",()=>loadInventory().catch(()=>{}));
  $("inventoryExpenseForm")?.addEventListener("submit",event=>addInventoryExpense(event).catch(error=>notify("Expense Not Added",error.message||String(error),"error")));
  $("businessProfileForm")?.addEventListener("submit",event=>saveBusinessProfile(event).catch(error=>notify("Profile Not Saved",error.message||String(error),"error")));
  $("cardArt")?.addEventListener("click",event=>{if(event.target.closest("img"))openCurrentReferenceLightbox()});
  $("cardArt")?.addEventListener("keydown",event=>{if((event.key==="Enter"||event.key===" ")&&event.target.closest("img")){event.preventDefault();openCurrentReferenceLightbox()}});
  $("referenceLightboxClose")?.addEventListener("click",closeReferenceLightbox);
  $("referenceLightbox")?.addEventListener("click",event=>{if(event.target===$("referenceLightbox"))closeReferenceLightbox()});
  document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!$("referenceLightbox")?.hidden)closeReferenceLightbox()});
  $("referenceZoomOut")?.addEventListener("click",()=>setReferenceCompareZoom(referenceCompareZoom-.25));
  $("referenceZoomFit")?.addEventListener("click",()=>setReferenceCompareZoom(1));
  $("referenceZoomIn")?.addEventListener("click",()=>setReferenceCompareZoom(referenceCompareZoom+.25));
  $("referenceCompareStage")?.addEventListener("wheel",event=>{event.preventDefault();setReferenceCompareZoom(referenceCompareZoom+(event.deltaY<0?.15:-.15))},{passive:false});
  $("referenceSideBySide")?.addEventListener("click",()=>setReferenceCompareMode("side"));
  $("referenceOverlayMode")?.addEventListener("click",()=>setReferenceCompareMode("overlay"));
  $("referenceAlternates")?.addEventListener("click",()=>{if($("referenceCandidates"))$("referenceCandidates").hidden=!$("referenceCandidates").hidden;renderReferenceCandidates()});
  $("referenceCorrectionHistory")?.addEventListener("click",()=>loadReferenceCorrectionHistory().catch(error=>notify("History Not Loaded",error.message||String(error),"error")));
  $("referenceCatalogSearchForm")?.addEventListener("submit",event=>searchReferenceCatalog(event).catch(error=>notify("Catalog Search Failed",error.message||String(error),"error")));
  $("candidateReviewButton")?.addEventListener("click",openMatchCorrectionWorkflow);
  $("correctMatchButton")?.addEventListener("click",openMatchCorrectionWorkflow);
  $("referenceBlendOpacity")?.addEventListener("input",event=>$("referenceCompareStage")?.style.setProperty("--live-opacity",String(Number(event.target.value)/100)));
  $("referenceApprove")?.addEventListener("click",approveReferenceSelection);
  $("referenceReject")?.addEventListener("click",async()=>{const result=await operatorReject();if(result)closeReferenceLightbox()});
  if($("periodCloseMonth")){const previous=new Date();previous.setDate(1);previous.setMonth(previous.getMonth()-1);$("periodCloseMonth").value=`${previous.getFullYear()}-${String(previous.getMonth()+1).padStart(2,"0")}`}
  $("periodCloseReview")?.addEventListener("click",()=>loadProfitAndLoss().catch(error=>notify("Report Not Loaded",error.message||String(error),"error")));
  $("periodCloseMonth")?.addEventListener("change",()=>loadProfitAndLoss().catch(()=>{}));
  $("periodCloseForm")?.addEventListener("submit",event=>closeAccountingPeriod(event).catch(error=>notify("Period Not Closed",error.message||String(error),"error")));
  if($("inventoryTaxYear")){$("inventoryTaxYear").value=String(new Date().getFullYear());const updateTaxExport=()=>{$("inventoryTaxExport").href=`/api/inventory/tax-summary.csv?year=${encodeURIComponent($("inventoryTaxYear").value)}`};$("inventoryTaxYear").addEventListener("input",updateTaxExport);$("inventoryTaxYear").addEventListener("change",()=>loadInventory().catch(()=>{}));updateTaxExport()}
  $("collectionGoalForm")?.addEventListener("submit",event=>createCollectionGoal(event).catch(error=>notify("Goal Not Added",error.message||String(error),"error")));
  $("collectionGoalType")?.addEventListener("change",event=>{
    const number=$("collectionGoalNumber");
    if(number) number.disabled=event.target.value!=="card";
  });
  $("previewCollectionBackup")?.addEventListener("click",()=>readCollectionBackup().catch(error=>{
    collectionImportBackup=null;
    if($("mergeCollectionBackup")) $("mergeCollectionBackup").disabled=true;
    notify("Backup Not Valid",error.message||String(error),"error");
  }));
  $("mergeCollectionBackup")?.addEventListener("click",()=>mergeCollectionBackup().catch(error=>notify("Merge Failed",error.message||String(error),"error")));
  $("collectionBackupFile")?.addEventListener("change",()=>{
    collectionImportBackup=null;
    if($("mergeCollectionBackup")) $("mergeCollectionBackup").disabled=true;
    if($("collectionImportPreview")) $("collectionImportPreview").hidden=true;
  });
  $("saveRevealSequence")?.addEventListener("click",()=>saveRevealSequence().catch(error=>notify("Reveal Rules Not Saved",error.message||String(error),"error")));
  $("creatorNextPack")?.addEventListener("click",()=>api("/api/creator/reveal-sequence/next-pack",{method:"POST"}).then(payload=>renderRevealSequence(payload.state||{})).catch(error=>notify("Pack Reset Failed",error.message||String(error),"error")));
  $("creatorRevealNow")?.addEventListener("click",()=>api("/api/creator/reveal-sequence/release",{method:"POST"}).then(payload=>renderRevealSequence(payload.state||{})).catch(error=>notify("Reveal Failed",error.message||String(error),"error")));
  $("creatorCancelReveal")?.addEventListener("click",()=>api("/api/creator/reveal-sequence/cancel",{method:"POST"}).then(payload=>renderRevealSequence(payload.state||{})).catch(error=>notify("Cancel Failed",error.message||String(error),"error")));
  $("creatorAnimationIntensity")?.addEventListener("input",event=>{if($("creatorIntensityValue"))$("creatorIntensityValue").textContent=`${event.target.value}%`});
  document.querySelectorAll("[data-animation-preview]").forEach(button=>button.addEventListener("click",()=>previewCreatorAnimation(button.dataset.animationPreview)));
  window.addEventListener("keydown",handleCreatorRevealShortcut);
  $("creatorAssetUpload")?.addEventListener("change",event=>uploadCreatorAsset(event.target.files?.[0]).catch(error=>notify("Asset Not Added",error.message||String(error),"error")).finally(()=>{event.target.value="";}));
  $("liveRevealAnimationsEnabled")?.addEventListener("change",event=>setLiveRevealAnimationsEnabled(event.target.checked).catch(error=>{event.target.checked=!event.target.checked;notify("Animation Setting Failed",error.message||String(error),"error");}));
  [["liveRevealSoundEnabled","audio_enabled"],["liveRevealParticlesEnabled","particles_enabled"],["liveRevealFlashEnabled","flash_enabled"]].forEach(([id,key])=>$(id)?.addEventListener("change",event=>setLiveRevealEffect(key,event.target.checked).catch(error=>{event.target.checked=!event.target.checked;notify("Effect Setting Failed",error.message||String(error),"error");})));
  $("openRevealCreatorSettings")?.addEventListener("click",()=>switchWorkspace("creator"));
  loadRevealSequence().then(payload=>renderLiveRevealAnimationTool(payload.state||{})).catch(()=>setStudioXWidgetState("reveal-animations","error"));
  $("soundboardStop")?.addEventListener("click",stopAllSoundboardAudio);
  $("soundboardVolume")?.addEventListener("input",event=>setSoundboardVolume(event.target.value));setSoundboardVolume(soundboardVolume());
  $("soundboardAddPad")?.addEventListener("click",()=>{if(soundboardState.pads.length>=50)return notify("Pad Limit Reached","Soundboard supports up to 50 pads.","error");soundboardState.pads.push({id:crypto.randomUUID?.()||`pad-${Date.now()}`,label:`Sound ${soundboardState.pads.length+1}`,asset_id:null,asset:null});renderSoundboard(soundboardState);renderSoundboardApp();addSoundboardImageControls();refreshSoundPadImages();});
  $("soundboardSave")?.addEventListener("click",()=>saveSoundboard().catch(error=>notify("Soundboard Not Saved",error.message||String(error),"error")));
  $("soundboardUpload")?.addEventListener("change",event=>uploadSoundboardFiles(event.target.files).catch(error=>notify("Sounds Not Added",error.message||String(error),"error")).finally(()=>{event.target.value="";}));
  loadSoundboard().catch(()=>setStudioXWidgetState("soundboard","error"));
  $("soundboardSearch")?.addEventListener("input",renderSoundboardApp);
  $("soundboardAppStop")?.addEventListener("click",stopAllSoundboardAudio);
  $("soundboardAppVolume")?.addEventListener("input",event=>{setSoundboardVolume(event.target.value);if($("soundboardAppVolumeValue"))$("soundboardAppVolumeValue").textContent=`${event.target.value}%`;});
  $("soundboardAppUpload")?.addEventListener("change",event=>uploadSoundboardFiles(event.target.files).catch(error=>notify("Sounds Not Added",error.message||String(error),"error")).finally(()=>{event.target.value="";}));
  $("soundboardAppAddPad")?.addEventListener("click",()=>{if(soundboardState.pads.length>=50)return notify("Pad Limit Reached","Soundboard supports 50 pads.","error");soundboardState.pads.push({id:`pad-${Date.now()}`,label:`Sound ${soundboardState.pads.length+1}`,asset_id:null,asset:null});renderSoundboard(soundboardState);renderSoundboardApp();});
  $("soundboardAppSave")?.addEventListener("click",()=>saveSoundboardApp().catch(error=>notify("Soundboard Not Saved",error.message||String(error),"error")));
  $("soundboardToolPreset")?.addEventListener("change",event=>setSoundboardPreset(event.target.value));
  $("soundboardAppPreset")?.addEventListener("change",event=>setSoundboardPreset(event.target.value));
  $("soundboardToolLock")?.addEventListener("click",toggleSoundboardLayoutLock);
  $("soundboardAppLock")?.addEventListener("click",toggleSoundboardLayoutLock);
  $("soundboardAppRenamePreset")?.addEventListener("click",renameSoundboardPreset);
  $("soundboardToolPlaybackMode")?.addEventListener("change",event=>setSoundboardPlaybackMode(event.target.value));
  $("soundboardAppPlaybackMode")?.addEventListener("change",event=>setSoundboardPlaybackMode(event.target.value));
  $("soundboardToolClearQueue")?.addEventListener("click",event=>{event.preventDefault();event.stopPropagation();clearSoundboardQueue();});
  $("soundboardAppClearQueue")?.addEventListener("click",clearSoundboardQueue);
  setSoundboardPlaybackMode(soundboardPlaybackMode());
  $("spotifySearchForm")?.addEventListener("submit",event=>{event.preventDefault();searchSpotify($("spotifySearch")?.value||"").catch(error=>renderSpotifyError(error.message||String(error)));});
  $("spotifyRefresh")?.addEventListener("click",()=>loadSpotify().catch(error=>renderSpotifyError(error.message||String(error))));
  $("spotifyDevice")?.addEventListener("change",event=>spotifyCommand("transfer",{device_id:event.target.value}).catch(error=>notify("Spotify Device Failed",error.message||String(error),"error")));
  $("spotifyVolume")?.addEventListener("change",event=>spotifyCommand("volume",{volume_percent:Number(event.target.value)}).catch(error=>notify("Spotify Volume Failed",error.message||String(error),"error")));
  [["spotifyPrevious","previous"],["spotifyToolPrevious","previous"],["spotifyNext","next"],["spotifyToolNext","next"]].forEach(([id,action])=>$(id)?.addEventListener("click",()=>spotifyCommand(action).catch(error=>notify("Spotify Command Failed",error.message||String(error),"error"))));
  ["spotifyPlay","spotifyToolPlay"].forEach(id=>$(id)?.addEventListener("click",()=>spotifyCommand(spotifyState.playback?.is_playing?"pause":"play").catch(error=>notify("Spotify Command Failed",error.message||String(error),"error"))));
  $("spotifyShuffle")?.addEventListener("click",()=>spotifyCommand("shuffle",{state:spotifyState.playback?.shuffle_state!==true}).catch(error=>notify("Spotify Shuffle Failed",error.message||String(error),"error")));
  $("spotifyRepeat")?.addEventListener("click",cycleSpotifyRepeat);
  ["spotifyDuckEnabled","spotifyAppDuckEnabled"].forEach(id=>$(id)?.addEventListener("change",event=>setSpotifyDucking(event.target.checked)));
  ["spotifyConnect","spotifyToolConnect"].forEach(id=>$(id)?.addEventListener("click",event=>startSpotifyConnection(event).catch(error=>notify("Spotify Connection Failed",error.message||String(error),"error"))));
  $("spotifySaveSetup")?.addEventListener("click",()=>saveSpotifySetup().catch(error=>notify("Spotify Setup Failed",error.message||String(error),"error")));
  $("spotifyCopyRedirect")?.addEventListener("click",()=>navigator.clipboard.writeText($("spotifyRedirectUri")?.value||"").then(()=>notify("Redirect URI Copied","Paste it into the Spotify app settings exactly as shown.","success")).catch(()=>notify("Copy Failed","Select and copy the redirect URI manually.","error")));
  $("spotifyOpenApp")?.addEventListener("click",()=>switchWorkspace("spotify"));
  loadSpotify().catch(()=>{});
  document.querySelectorAll("[data-production-slot]").forEach(button=>button.addEventListener("click",()=>setProductionPreview(button.dataset.productionSlot).catch(error=>notify("Preview Not Changed",error.message||String(error),"error"))));
  $("productionCut")?.addEventListener("click",()=>takeProductionShot(true).catch(error=>notify("Cut Failed",error.message||String(error),"error")));
  $("productionAuto")?.addEventListener("click",()=>takeProductionShot(false).catch(error=>notify("Transition Failed",error.message||String(error),"error")));
  $("productionRefresh")?.addEventListener("click",()=>loadProductionSwitcher().catch(error=>notify("Sources Not Refreshed",error.message||String(error),"error")));
  $("productionTransition")?.addEventListener("change",()=>setProductionPreview(productionSwitcherState.preview_slot).catch(()=>{}));
  $("productionDuration")?.addEventListener("change",()=>setProductionPreview(productionSwitcherState.preview_slot).catch(()=>{}));
  window.addEventListener("keydown",handleProductionShortcut);
  loadProductionRundown();
  $("rundownCueType")?.addEventListener("change",renderRundownTargets);
  $("rundownAdd")?.addEventListener("click",addProductionRundownCue);
  $("rundownGo")?.addEventListener("click",()=>goProductionRundown().catch(error=>notify("Cue Failed",error.message||String(error),"error")));
  $("rundownPrevious")?.addEventListener("click",()=>stepProductionRundown(-1));
  $("rundownNext")?.addEventListener("click",()=>stepProductionRundown(1));
  $("rundownClear")?.addEventListener("click",()=>{productionRundown=[];productionRundownIndex=0;saveProductionRundown();renderProductionRundown();});
  $("rundownStop")?.addEventListener("click",stopProductionRundown);
  $("operatorHealthRefresh")?.addEventListener("click",()=>loadOperatorHealth().catch(error=>notify("Health Check Failed",error.message||String(error),"error")));
  $("showPreflightRefresh")?.addEventListener("click",()=>loadShowPreflight().then(payload=>notify(payload.preflight?.ready?"Ready To Go Live":"Preflight Needs Attention",payload.preflight?.ready?"Core production systems passed.":`${payload.preflight?.blockers?.length||0} blocker(s) found.`,payload.preflight?.ready?"success":"error")).catch(error=>notify("Preflight Failed",error.message||String(error),"error")));
  $("showStartButton")?.addEventListener("click",()=>startProductionShow().catch(error=>notify("Show Not Started",error.payload?.reason==="preflight_blocked"?"Resolve the blocking preflight checks first.":error.message||String(error),"error")));
  $("operatorSafeScene")?.addEventListener("click",()=>activateOperatorSafeScene().catch(error=>notify("Safe Recovery Failed",error.message||String(error),"error")));
  $("productionSessionStart")?.addEventListener("click",()=>setProductionSession(true).catch(error=>notify("Session Not Started",error.message||String(error),"error")));
  $("productionSessionMetadata")?.addEventListener("submit",event=>saveProductionSessionMetadata(event).catch(error=>notify("Details Not Saved",error.message||String(error),"error")));
  $("productionSessionStop")?.addEventListener("click",()=>setProductionSession(false).catch(error=>notify("Session Not Stopped",error.message||String(error),"error")));
  $("productionIncidentForm")?.addEventListener("submit",event=>markProductionIncident(event).catch(error=>notify("Event Not Marked",error.message||String(error),"error")));
  $("showAnalyticsRefresh")?.addEventListener("click",()=>loadShowAnalytics().catch(error=>notify("Analytics Failed",error.message||String(error),"error")));
  $("cardAnalyticsRefresh")?.addEventListener("click",()=>loadCardShowAnalytics().catch(error=>notify("Card Analytics Failed",error.message||String(error),"error")));
  $("cardAnalyticsTopPullGraphic")?.addEventListener("click",()=>takeTopPullGraphic().catch(error=>notify("Top Pull Graphic Failed",error.message||String(error),"error")));
  $("packTrackerRefresh")?.addEventListener("click",()=>loadPackTracker().catch(error=>notify("Pack Tracker Failed",error.message||String(error),"error")));
  $("packTrackerRecap")?.addEventListener("click",()=>takePackFinaleGraphic().catch(error=>notify("Pack Recap Failed",error.message||String(error),"error")));
  $("packEconomicsRefresh")?.addEventListener("click",()=>loadPackEconomics().catch(error=>notify("Pack Economics Failed",error.message||String(error),"error")));
  $("packEconomicsForm")?.addEventListener("submit",event=>savePackEconomics(event).catch(error=>notify("Pack Economics Failed",error.message||String(error),"error")));
  $("breakHistoryRefresh")?.addEventListener("click",()=>loadBreakHistory().catch(error=>notify("Break History Failed",error.message||String(error),"error")));
  $("breakHistorySearch")?.addEventListener("input",applyBreakHistoryFilters);
  $("breakHistoryFilter")?.addEventListener("change",applyBreakHistoryFilters);
  $("breakHistorySort")?.addEventListener("change",applyBreakHistoryFilters);
  $("recordingSettingsToggle")?.addEventListener("click",()=>{$("recordingSettingsForm").hidden=!$("recordingSettingsForm").hidden;});
  $("recordingSettingsForm")?.addEventListener("submit",event=>saveRecordingSettings(event).catch(error=>notify("Settings Not Saved",error.message||String(error),"error")));
  $("recordingTest")?.addEventListener("click",()=>testRecordingSettings().catch(error=>{if($("recordingTestResult"))$("recordingTestResult").textContent=error.message||String(error);notify("Recording Test Failed",error.message||String(error),"error");}));
  $("recordingUseTestPreset")?.addEventListener("click",()=>{if($("recordingCommand"))$("recordingCommand").value=$("recordingUseTestPreset").dataset.command||"";if($("recordingSettingsForm"))$("recordingSettingsForm").hidden=false;});
  $("recordingUseDevicePreset")?.addEventListener("click",()=>{if($("recordingCommand"))$("recordingCommand").value=$("recordingUseDevicePreset").dataset.command||"";if($("recordingSettingsForm"))$("recordingSettingsForm").hidden=false;});
  $("obsSettingsToggle")?.addEventListener("click",()=>{$("obsSettingsForm").hidden=!$("obsSettingsForm").hidden;});
  $("obsSettingsForm")?.addEventListener("submit",event=>saveObsSettings(event).catch(error=>notify("OBS Settings Failed",error.message||String(error),"error")));
  $("obsRefresh")?.addEventListener("click",()=>loadObsStatus().catch(error=>notify("OBS Refresh Failed",error.message||String(error),"error")));
  $("broadcastDestinationsRefresh")?.addEventListener("click",()=>loadBroadcastDestinations().then(()=>notify("Destination Status Refreshed","RareIQ refreshed verified connector and encoder states.","success")).catch(error=>notify("Destinations Unavailable",error.message||String(error),"error")));
  $("obsTakeScene")?.addEventListener("click",()=>obsCommand("set-scene",$("obsSceneSelect")?.value||null).catch(error=>notify("OBS Scene Failed",error.message||String(error),"error")));
  $("obsStreamToggle")?.addEventListener("click",()=>obsCommand(obsState.streaming?"stop-stream":"start-stream").catch(error=>notify("OBS Stream Failed",error.message||String(error),"error")));
  $("obsRecordToggle")?.addEventListener("click",()=>obsCommand(obsState.recording?"stop-record":"start-record").catch(error=>notify("OBS Recording Failed",error.message||String(error),"error")));
  $("obsBootstrapPreview")?.addEventListener("click",()=>bootstrapObs(true).catch(error=>notify("Bootstrap Preview Failed",error.message||String(error),"error")));
  $("obsBootstrapCreate")?.addEventListener("click",()=>bootstrapObs(false).catch(error=>notify("OBS Bootstrap Failed",error.message||String(error),"error")));
  $("rundownTemplateSave")?.addEventListener("click",saveRundownTemplate);
  $("rundownTemplateLoad")?.addEventListener("click",loadRundownTemplate);
  $("rundownDuplicate")?.addEventListener("click",duplicateProductionCue);
  $("rundownExport")?.addEventListener("click",exportProductionRundown);
  $("rundownImport")?.addEventListener("change",event=>{const file=event.target.files?.[0];if(file)importProductionRundown(file).then(()=>notify("Rundown Imported",`${productionRundown.length} cues loaded.`,"success")).catch(error=>notify("Import Failed",error.message||String(error),"error"));event.target.value="";});
  $("rundownPreflight")?.addEventListener("click",()=>preflightProductionRundown().then(result=>notify(result.ok?"Preflight Passed":"Preflight Blocked",result.ok?"Rundown is ready for air.":`${result.issues.length} issue(s) require attention.`,result.ok?"success":"error")));
  renderRundownTemplates();
  renderRundownTargets();
  $("productionNewScene")?.addEventListener("click",()=>openProductionSceneEditor());
  $("productionSaveScene")?.addEventListener("click",()=>openProductionSceneEditor({id:"",name:`Scene ${productionScenes.length+1}`,program_slot:productionSwitcherState.program_slot,preview_slot:productionSwitcherState.preview_slot,transition:productionSwitcherState.transition,duration_ms:productionSwitcherState.duration_ms,spotify_action:"keep",soundboard_action:"keep"}));
  $("productionSceneEditor")?.addEventListener("submit",event=>saveProductionScene(event).catch(error=>notify("Scene Not Saved",error.message||String(error),"error")));
  $("productionCancelScene")?.addEventListener("click",()=>{$("productionSceneEditor").hidden=true;});
  $("productionGraphicsForm")?.addEventListener("submit",event=>{event.preventDefault();sendProductionGraphic("take").catch(error=>notify("Graphic Failed",error.message||String(error),"error"));});
  $("productionGraphicPreview")?.addEventListener("click",()=>sendProductionGraphic("preview").catch(error=>notify("Preview Failed",error.message||String(error),"error")));
  $("productionGraphicHide")?.addEventListener("click",()=>sendProductionGraphic("hide").catch(error=>notify("Graphic Not Hidden",error.message||String(error),"error")));
  $("productionGraphicCardFill")?.addEventListener("click",fillProductionGraphicFromCard);
  $("productionReplayMark")?.addEventListener("click",()=>markProductionReplay().catch(error=>notify("Highlight Not Saved",error.message||String(error),"error")));
  $("productionReplayStop")?.addEventListener("click",()=>stopProductionReplay().catch(error=>notify("Replay Not Stopped",error.message||String(error),"error")));
  document.querySelectorAll("[data-production-screen-preset]").forEach(button=>button.addEventListener("click",()=>applyProductionScreenPreset(button.dataset.productionScreenPreset)));
  $("productionScreenForm")?.addEventListener("submit",event=>{event.preventDefault();takeProductionScreen().catch(error=>notify("Screen Not Taken",error.message||String(error),"error"));});
  $("productionScreenHide")?.addEventListener("click",()=>hideProductionScreen().catch(error=>notify("Screen Not Hidden",error.message||String(error),"error")));
  ["collectionSearch","collectionSetFilter","collectionLanguageFilter","collectionSort","collectionDuplicatesOnly"].forEach(id=>{
    $(id)?.addEventListener(id==="collectionSearch"?"input":"change",renderCollectionRows);
  });
  document.querySelectorAll(".dock-tab").forEach(button=>{
    button.addEventListener("click",()=>switchDock(button.dataset.dock));
  });

  const feed = $("cameraFeed");
  if(feed){
    feed.addEventListener("load",()=>{
      clearTimeout(cameraStreamRetryTimer);
      cameraStreamFailures=0;
      cameraStreamStarted=true;
      cameraAutostartComplete=true;
      alignScanZone(window.__rareiqVisionTelemetry||{});
      const placeholder=$("cameraPlaceholder");
      const recovery=$("cameraRecovery");
      if(placeholder) placeholder.classList.add("hidden");
      if(recovery) recovery.classList.remove("visible");
    });

    feed.addEventListener("error",()=>{
      clearTimeout(cameraStreamRetryTimer);
      cameraStreamStarted=false;
      cameraStreamFailures+=1;
      const placeholder=$("cameraPlaceholder");
      const recovery=$("cameraRecovery");
      if(placeholder) placeholder.classList.remove("hidden");

      if(cameraStreamFailures<=8){
        if(recovery){
          recovery.classList.add("visible");
          $("cameraRecoveryTitle").textContent="Recovering live preview...";
          $("cameraRecoveryDetail").textContent=`Retry ${cameraStreamFailures} of 8`;
        }
        cameraStreamRetryTimer=setTimeout(()=>startCameraStream(true),650);
      }else if(recovery){
        cameraAutostartComplete=false;
        recovery.classList.add("visible");
        $("cameraRecoveryTitle").textContent="Live preview unavailable";
        $("cameraRecoveryDetail").textContent="RareIQ will keep trying automatically.";
        scheduleCameraDiscovery();
      }
    });
  }

  const savedFit=localStorage.getItem("rareiq.cameraFitMode")||"adaptive";
  applyCameraFit(savedFit);
  applyCardZoom(localStorage.getItem("rareiq.cardZoom")==="on");
  updateResolutionBadge();
  window.addEventListener("resize",()=>{
    alignScanZone(window.__rareiqVisionTelemetry||{});
    renderSecondaryWorkspaceBay();
  });
  applyAutoCaptureState(true);
  setStateChip("databaseStateChip","on","READY");
  setStateChip("broadcastStateChip","","OFF");
  setRecognitionState("idle","Waiting for a card.");
  addActivity("RareIQ Ready","Camera and recognition controls loaded.");
  updateSessionStats();
  setInterval(updateSessionStats,1000);

  startBackgroundInitialization();


  setInterval(()=>{if(document.hidden!==true)loadRecognition()},600);
});


/* =========================================================
   RareIQ UI 4.0 card intelligence normalization
   Frontend placeholders only. Missing values remain null.
   ========================================================= */

function firstCardValue(source,keys){
  for(const key of keys){
    const value=source?.[key];
    if(value!==undefined&&value!==null&&value!=="") return value;
  }
  return null;
}

function nullableCardNumber(value){
  if(value===undefined||value===null||value==="") return null;
  const number=Number(value);
  return Number.isFinite(number)&&number>0?number:null;
}

function cardMoney(value,currency="USD"){
  const number=nullableCardNumber(value);
  return number===null
    ? "No public data"
    : new Intl.NumberFormat("en-US",{
        style:"currency",
        currency:String(currency||"USD").toUpperCase(),
        minimumFractionDigits:2,
        maximumFractionDigits:2
      }).format(number);
}

function cardText(value,fallback="--"){
  const text=String(value??"").trim();
  return text||fallback;
}

function setCardText(id,value,fallback="--"){
  const node=$(id);
  if(node) node.textContent=cardText(value,fallback);
}

function normalizeCardPricing(card={}){
  const pricing=card.pricing||{};
  const prices=card.prices||{};
  const market=pricing.market||pricing.market_price||prices.market||prices.raw||null;

  return {
    currency:firstCardValue(pricing,["currency","unit"])||"USD",
    rawMarket:firstCardValue(card,[
      "market_price","raw_market","raw_value","price"
    ])??market,
    rawLow:firstCardValue(card,[
      "raw_low","low_price","market_low"
    ])??firstCardValue(pricing,["low","low_price"]),
    rawHigh:firstCardValue(card,[
      "raw_high","high_price","market_high"
    ])??firstCardValue(pricing,["high","high_price"]),
    psa10:firstCardValue(card,[
      "psa10_price","psa_10_price","graded_10_value"
    ])??firstCardValue(pricing,["psa10","psa_10"]),
    psa9:firstCardValue(card,[
      "psa9_price","psa_9_price","graded_9_value"
    ])??firstCardValue(pricing,["psa9","psa_9"]),
    psa8:firstCardValue(card,[
      "psa8_price","psa_8_price","graded_8_value"
    ])??firstCardValue(pricing,["psa8","psa_8"]),
    lastSoldRaw:firstCardValue(card,[
      "last_sold_raw","raw_last_sold"
    ])??firstCardValue(pricing,["last_sold_raw"]),
    lastSoldPsa10:firstCardValue(card,[
      "last_sold_psa10","psa10_last_sold"
    ])??firstCardValue(pricing,["last_sold_psa10"]),
    population:firstCardValue(card,[
      "population","psa10_population","psa_10_population"
    ]),
    salesVolume30d:firstCardValue(card,[
      "sales_volume_30d","sales_30d","volume_30d"
    ])??firstCardValue(pricing,["sales_volume_30d"]),
    provider:firstCardValue(card,[
      "price_source","pricing_source"
    ])??firstCardValue(pricing,["source","provider"]),
    updatedAt:firstCardValue(card,[
      "price_updated_at","pricing_updated_at"
    ])??firstCardValue(pricing,["updated_at","updatedAt"]),
    confidence:firstCardValue(pricing,["confidence"]),
    freshness:firstCardValue(pricing,["freshness"]),
    freshnessStatus:firstCardValue(pricing,["freshness_status"])||"unknown",
    ageSeconds:firstCardValue(pricing,["age_seconds"]),
    verified:pricing.verified!==false,
    valuationEligible:pricing.valuation_eligible!==false,
    verificationState:firstCardValue(pricing,["verification_state"])||"unknown",
    verificationReason:firstCardValue(pricing,["verification_reason"]),
    provenance:pricing.provenance||null,
    quoteConsensus:pricing.quote_consensus||pricing.provenance?.consensus||null,
    consensusStatus:firstCardValue(pricing.quote_consensus||pricing.provenance?.consensus||{},["status"])||"single-source",
    consensusSpread:firstCardValue(pricing.quote_consensus||pricing.provenance?.consensus||{},["spread_percent"]),
    providerCount:Number(firstCardValue(pricing,["provider_count"])||pricing.quotes?.length||0),
    quotes:Array.isArray(pricing.quotes)?pricing.quotes:[],
    selectionReason:firstCardValue(pricing,["selection_reason"]),
    operatorSelected:pricing.operator_selected===true,
    resolutionId:firstCardValue(pricing,["resolution_id"]),
    trend:firstCardValue(pricing,["trend"]),
    changePercent:firstCardValue(pricing,["change_percent"]),
    historyCount:Number(firstCardValue(pricing,["history_count"])||0),
    history:Array.isArray(pricing.history)?pricing.history:[],
    alert:pricing.alert||null
  };
}

function deriveMarketPresentation(card={},pricing=normalizeCardPricing(card)){
  const providerError=Boolean(
    card?.pricing_error||
    card?.provider_error||
    pricing?.status==="error"
  );
  const pending=Boolean(
    card?.pricing_pending||
    pricing?.status==="pending"
  );
  const hasValue=[
    pricing.rawMarket,pricing.rawLow,pricing.rawHigh,
    pricing.psa10,pricing.psa9,pricing.psa8
  ].some(value=>nullableCardNumber(value)!==null);
  if(providerError) return {key:"provider-error",label:"Provider unavailable"};
  if(pending) return {key:"pending",label:"Fetching market data"};
  if(hasValue&&pricing.consensusStatus==="divergent") return {key:"conflict",label:`${cardMoney(pricing.rawMarket)} · PRICE CONFLICT`};
  if(hasValue&&pricing.freshnessStatus==="stale") return {key:"stale",label:`${cardMoney(pricing.rawMarket)} · STALE`};
  if(hasValue&&!pricing.verified) return {key:"unverified",label:`${cardMoney(pricing.rawMarket)} · UNVERIFIED`};
  if(hasValue) return {key:"available",label:cardMoney(pricing.rawMarket)};
  return {key:"no-data",label:"No public market data"};
}

function rarityEventTier(card={}){
  const rarity=String(
    card.rarity_tier||
    card.rarity||
    ""
  ).toLowerCase();

  if(
    rarity.includes("special art")||
    rarity.includes("special illustration")||
    rarity.includes("sar")||
    rarity.includes("secret")
  ) return "Special";

  if(
    rarity.includes("illustration")||
    rarity.includes("art rare")||
    rarity.includes("ir")
  ) return "Illustration Rare";

  if(
    rarity.includes("double rare")||
    rarity.includes("double")||
    rarity.includes("ex")
  ) return "Double Rare";

  if(rarity.includes("rare")) return "Rare";
  return "Standard";
}

function rarityAnimationName(tier){
  return {
    "Special":"Cinematic chase reveal",
    "Illustration Rare":"Illustration shimmer",
    "Double Rare":"Double Rare burst",
    "Rare":"Rare shimmer",
    "Standard":"Standard reveal"
  }[tier]||"Standard reveal";
}

function raritySoundName(tier){
  return {
    "Special":"Special card fanfare",
    "Illustration Rare":"Illustration Rare hit",
    "Double Rare":"Double Rare hit",
    "Rare":"Rare hit",
    "Standard":"Default scan"
  }[tier]||"Default scan";
}

function readablePriceTimestamp(value){
  if(!value) return "--";
  const numeric=Number(value);
  const date=Number.isFinite(numeric)
    ? new Date(numeric<100000000000?numeric*1000:numeric)
    : new Date(value);
  return Number.isNaN(date.getTime())
    ? "--"
    : date.toLocaleString();
}

function renderMarketProviderComparison(pricing={}){
  const host=$("marketProviderComparisonRows"),summary=$("marketProviderComparisonSummary");
  if(!host||!summary)return;
  const quotes=Array.isArray(pricing.quotes)?pricing.quotes:[];
  if(!quotes.length){summary.textContent="No comparable quotes";host.innerHTML="<p>No provider quotes are available.</p>";return}
  const selectedMarket=nullableCardNumber(pricing.rawMarket),selectedProvider=String(pricing.provider||"").toLowerCase(),selectedCurrency=String(pricing.currency||"USD").toUpperCase();
  const comparable=quotes.filter(quote=>String(quote.unit||quote.currency||"").toUpperCase()===selectedCurrency&&nullableCardNumber(quote.market)!==null);
  summary.textContent=pricing.consensusStatus==="operator-resolved"?`${quotes.length} sources · operator resolved`:pricing.consensusStatus==="divergent"?`${quotes.length} sources · conflict`:pricing.consensusStatus==="aligned"?`${comparable.length} comparable · aligned`:pricing.consensusStatus==="mixed"?`${comparable.length} comparable · mixed`:`${quotes.length} source${quotes.length===1?"":"s"}`;
  host.innerHTML=quotes.map(quote=>{
    const market=nullableCardNumber(quote.market),currency=String(quote.unit||quote.currency||"USD").toUpperCase(),source=String(quote.source||"Unknown provider"),selected=source.toLowerCase()===selectedProvider&&currency===selectedCurrency&&market===selectedMarket;
    const action=selected&&pricing.operatorSelected?`<button type="button" data-market-quote-undo>Undo</button>`:!selected&&market!==null?`<button type="button" data-market-quote-select data-source="${escapeHtml(source)}" data-variant="${escapeHtml(quote.variant||"standard")}" data-currency="${escapeHtml(currency)}">Use quote</button>`:`<i>${selected?"IN USE":"--"}</i>`;
    return `<article data-selected="${selected?"true":"false"}" data-comparable="${currency===selectedCurrency?"true":"false"}"><span><b>${escapeHtml(source)}</b><small>${escapeHtml(quote.variant||"standard")} · ${escapeHtml(currency)}</small></span><strong>${cardMoney(market,currency)}</strong><em>${selected?"SELECTED":currency===selectedCurrency?"COMPARED":"OTHER CURRENCY"}</em><time>${escapeHtml(readablePriceTimestamp(quote.updated_at))}</time>${action}</article>`;
  }).join("");
  host.querySelectorAll("[data-market-quote-select]").forEach(button=>button.addEventListener("click",()=>selectMarketProviderQuote(button)));
  host.querySelectorAll("[data-market-quote-undo]").forEach(button=>button.addEventListener("click",()=>undoMarketProviderQuote(button)));
}

function renderPriceHistory(history=[],currency="USD"){
  const chart=$("priceHistoryChart"),ledger=$("priceHistoryLedger");
  if(!chart||!ledger) return;
  const points=(Array.isArray(history)?history:[]).filter(item=>Number.isFinite(Number(item?.market))).slice(-12);
  if(!points.length){
    chart.innerHTML="<p>Refresh or save a verified price to establish a baseline.</p>";
    ledger.innerHTML="";
    setCardText("priceHistoryTitle","Waiting for snapshots");
    setCardText("priceHistoryRange","--");
    return;
  }
  const values=points.map(item=>Number(item.market)),min=Math.min(...values),max=Math.max(...values),span=max-min||1;
  const coords=values.map((value,index)=>`${points.length===1?50:(index/(points.length-1))*100},${88-((value-min)/span)*72}`).join(" ");
  chart.innerHTML=`<svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Verified market price trend"><defs><linearGradient id="priceHistoryFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#54e2c1" stop-opacity=".34"/><stop offset="1" stop-color="#54e2c1" stop-opacity="0"/></linearGradient></defs><polygon points="0,100 ${coords} 100,100" fill="url(#priceHistoryFill)"/><polyline points="${coords}" fill="none" stroke="#54e2c1" stroke-width="2.4" vector-effect="non-scaling-stroke"/></svg>`;
  setCardText("priceHistoryTitle",`${points.length} verified snapshot${points.length===1?"":"s"}`);
  setCardText("priceHistoryRange",`${cardMoney(min,currency)} – ${cardMoney(max,currency)}`);
  ledger.innerHTML=points.slice(-4).reverse().map(item=>`<div><span>${cardText(item.source,"Verified")}</span><b>${cardMoney(item.market,item.currency||currency)}</b><time>${readablePriceTimestamp(item.captured_at)}</time></div>`).join("");
}

function syncCardMetadataVisibility(){
  [
    "cardSetName","cardSetCode","cardCollectorNumber","cardOfficialNumber",
    "cardLanguage","cardRarity","cardVariant","cardFinish","cardReleaseYear",
  ].forEach(id=>{
    const value=$(id);
    const field=value?.closest(".ui4-identity-grid>div");
    if(!value||!field) return;
    const text=String(value.textContent||"").trim().toLowerCase();
    field.hidden=!text||text==="--"||text==="null"||text==="undefined";
  });
}

function renderProvisionalIdentityData(card={},snapshot={}){
  const printedName=firstCardValue(card,["printed_name","localized_name","name"]);
  const englishName=firstCardValue(card,["english_name","translated_name","canonical_name"])||(
    String(card.language||snapshot?.language||"").toLowerCase()==="english"?printedName:null
  );
  setCardText("cardPrintedName",printedName);
  setCardText("cardEnglishName",englishName);
  setCardText("cardPokemonName",firstCardValue(card,["pokemon_name","character_name","species"])||englishName||printedName);
}

function renderExtendedCardData(card={},snapshot={},confidence=0,verified=false){
  const printedName=firstCardValue(card,[
    "printed_name","localized_name","name"
  ]);
  const englishName=firstCardValue(card,[
    "english_name","translated_name","canonical_name"
  ]);
  const pricing=normalizeCardPricing(card);
  const marketPresentation=deriveMarketPresentation(card,pricing);
  const tier=rarityEventTier(card);

  setCardText("cardPrintedName",printedName);
  setCardText("cardEnglishName",englishName);
  setCardText("cardPokemonName",firstCardValue(card,[
    "pokemon_name","character_name","species"
  ])||englishName||printedName);

  setCardText("cardSetName",firstCardValue(card,[
    "set_name","set"
  ]));
  setCardText("cardSetCode",firstCardValue(card,[
    "set_code","set_id"
  ]));
  setCardText("cardCollectorNumber",firstCardValue(card,[
    "collector_number","card_number"
  ])||snapshot?.collector_number);
  const officialNumber=firstCardValue(card,[
    "official_collector_number"
  ])||snapshot?.official_collector_number;
  setCardText("cardOfficialNumber",officialNumber);
  const officialField=$("officialNumberField");
  if(officialField) officialField.hidden=!officialNumber;
  setCardText("cardLanguage",firstCardValue(card,[
    "language","language_name","language_code"
  ])||snapshot?.language);
  setCardText("cardRarity",card.rarity);
  setCardText("cardVariant",firstCardValue(card,[
    "variant","variant_name","rarity_variant"
  ]));
  setCardText("cardFinish",firstCardValue(card,[
    "finish","foil","foil_type","surface"
  ]));
  setCardText("cardReleaseYear",firstCardValue(card,[
    "release_year","year"
  ]));
  setCardText("cardTypeValue",firstCardValue(card,[
    "card_type","category","supertype"
  ]));
  setCardText("cardHpValue",firstCardValue(card,["hp"]));
  setCardText("cardEnergyType",firstCardValue(card,[
    "energy_type","type","types"
  ]));

  setCardText("rawValue",cardMoney(pricing.rawMarket,pricing.currency));
  setCardText("rawLowValue",cardMoney(pricing.rawLow,pricing.currency));
  setCardText("rawHighValue",cardMoney(pricing.rawHigh,pricing.currency));
  setCardText("psaValue",cardMoney(pricing.psa10));
  setCardText("psa9Value",cardMoney(pricing.psa9));
  setCardText("psa8Value",cardMoney(pricing.psa8));
  setCardText("lastSoldRawValue",cardMoney(pricing.lastSoldRaw));
  setCardText("lastSoldPsa10Value",cardMoney(pricing.lastSoldPsa10));
  setCardText("populationValue",pricing.population);
  setCardText("salesVolumeValue",pricing.salesVolume30d);
  setCardText("pricingSource",pricing.provider,"No provider connected");
  setCardText("pricingUpdatedAt",readablePriceTimestamp(pricing.updatedAt));
  setCardText("pricingConfidence",pricing.confidence?`${String(pricing.confidence).toUpperCase()} · ${pricing.verified?"VERIFIED":"NOT VERIFIED"}`:null,"Unavailable");
  setCardText("pricingFreshness",pricing.freshness||readablePriceTimestamp(pricing.updatedAt));
  setCardText("pricingProviderCount",pricing.providerCount?`${pricing.providerCount} source${pricing.providerCount===1?"":"s"}`:pricing.provider==="Manual verified"?"Manual source":"0 sources");
  setCardText("pricingConsensus",pricing.consensusStatus==="divergent"?`CONFLICT · ${Number(pricing.consensusSpread||0).toFixed(1)}% spread`:pricing.consensusStatus==="aligned"?`ALIGNED · ${Number(pricing.consensusSpread||0).toFixed(1)}% spread`:pricing.consensusStatus==="mixed"?`MIXED · ${Number(pricing.consensusSpread||0).toFixed(1)}% spread`:"Single comparable source");
  renderMarketProviderComparison(pricing);
  const movement=pricing.trend
    ? `${String(pricing.trend).toUpperCase()} · ${Number(pricing.changePercent||0)>=0?"+":""}${Number(pricing.changePercent||0).toFixed(2)}%`
    : pricing.historyCount?"Baseline captured":"Not enough history";
  setCardText("pricingMovement",movement);
  renderPriceHistory(pricing.history,pricing.currency);
  renderPriceAlert(pricing.alert);
  const priceSummary=document.querySelector(".ui4-price-summary");
  if(priceSummary) priceSummary.dataset.marketState=marketPresentation.key;
  setCardText("cardValue",marketPresentation.label);

  setCardText("rarityTierValue",tier);
  setCardText("overlayAnimationValue",rarityAnimationName(tier));
  setCardText("overlaySoundValue",raritySoundName(tier));
  setCardText(
    "overlayTrackingValue",
    verified
      ? "Locked to recognized card"
      : confidence>=0.68
      ? "Candidate tracking"
      : "Waiting for lock"
  );
  syncCardMetadataVisibility();
}

function resetExtendedCardData(){
  [
    "cardPrintedName",
    "cardEnglishName",
    "cardPokemonName",
    "cardSetName",
    "cardSetCode",
    "cardCollectorNumber",
    "cardLanguage",
    "cardRarity",
    "cardVariant",
    "cardFinish",
    "cardReleaseYear",
    "cardTypeValue",
    "cardHpValue",
    "cardEnergyType",
    "rawLowValue",
    "rawHighValue",
    "psa9Value",
    "psa8Value",
    "lastSoldRawValue",
    "lastSoldPsa10Value",
    "salesVolumeValue",
    "pricingUpdatedAt",
    "pricingFreshness"
  ].forEach(id=>setCardText(id,null));

  setCardText("rawValue",null,"No public data");
  setCardText("psaValue",null,"No public data");
  setCardText("populationValue",null);
  setCardText("pricingSource",null,"No provider connected");
  setCardText("pricingConfidence",null,"Unavailable");
  setCardText("pricingProviderCount","0 verified");
  setCardText("pricingConsensus","Waiting for comparable quotes");
  renderMarketProviderComparison({quotes:[]});
  setCardText("pricingMovement","Not enough history");
  renderPriceHistory([],"USD");
  renderPriceAlert(null);
  const officialField=$("officialNumberField");
  if(officialField) officialField.hidden=true;
  syncCardMetadataVisibility();
  const priceSummary=document.querySelector(".ui4-price-summary");
  if(priceSummary) priceSummary.dataset.marketState="pending";
  setCardText("rarityTierValue","Standard");
  setCardText("overlayAnimationValue","Standard reveal");
  setCardText("overlaySoundValue","Default scan");
  setCardText("overlayTrackingValue","Waiting for lock");
}







