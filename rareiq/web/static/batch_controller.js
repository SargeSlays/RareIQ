/*
 * BatchController
 * Owns boxes, packs, cards, recent scans, undo/export and Auto-add workflow.
 */
function renderSession(s) {
  state.session = s || {};
  const box = `${s?.active_box_number || 1}/${s?.boxes_total || 1}`;
  const pack = `${s?.active_pack_number || 1}/${s?.packs_per_box || 5}`;
  const cards = Number(s?.card_count || 0);
  const value = money(s?.total_value || 0);
  $("batchBox").textContent = box;
  $("batchPack").textContent = pack;
  $("batchCards").textContent = String(cards);
  $("batchValue").textContent = value;
  $("kpiBatch").textContent = value;
  $("kpiCards").textContent = `${cards} cards`;
  const packsPerBox = Number(s?.packs_per_box || 5);
  const activePack = Number(s?.active_pack_number || 1);
  const progress = Math.max(0, Math.min(100, ((activePack - 1) / packsPerBox) * 100));
  $("batchProgressFill").style.width = `${progress}%`;

  const pulls = Array.isArray(s?.recent_cards) ? s.recent_cards : [];
  const totalValue = pulls.reduce((sum,card)=>sum+Number(card.raw_value || 0),0);
  const hits = pulls.filter(card=>{
    const rarity = String(card.rarity || "").toUpperCase();
    return ["EX","GX","VMAX","VSTAR","SAR","SR","UR","IR","SIR","DOUBLE RARE","ILLUSTRATION RARE"].some(token=>rarity.includes(token));
  }).length;
  const best = pulls.reduce((value,card)=>Math.max(value,Number(card.raw_value || 0)),0);
  $("summaryCards").textContent = String(cards);
  $("summaryHits").textContent = String(hits);
  $("summaryAvg").textContent = money(cards ? totalValue/cards : 0);
  $("summaryTop").textContent = money(best);
  $("batchStatus").textContent = s?.customer
    ? `${s.customer} • ${s.order_number || "No order"} • ${s.product_name || "No product"}`
    : "No active customer batch.";
}

async function startSession() {
  const result = await post("/api/session/start", {
    customer:$("customer").value.trim() || "Walk-in",
    order_number:$("order").value.trim() || "N/A",
    product_name:$("product").value.trim() || "Card Session",
    boxes_total:Number($("boxes").value || 1),
    packs_per_box:Number($("packs").value || 5)
  });
  if (result?.session) renderSession(result.session);
}

function recognitionSignature(r){
  const candidate = topCandidate(r) || {};
  const fingerprint = String(r?.artwork_fingerprint || "").trim().toLowerCase();
  const number = String(candidate.collector_number || r?.collector_number || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g,"");
  const language = String(candidate.language || r?.language || "")
    .trim()
    .toLowerCase();
  const setName = String(candidate.set_name || "")
    .trim()
    .toLowerCase();
  const name = String(candidate.name || candidate.printed_name || r?.name_candidate || "")
    .trim()
    .toLowerCase();

  // Artwork fingerprint is the most stable identity while a card remains on screen.
  if(fingerprint) return `fp:${fingerprint}`;
  return `card:${number}|${language}|${setName}|${name}`;
}

function showWorkflowToast(message,type="ok"){
  const toast = $("workflowToast");
  toast.textContent = message;
  toast.className = "workflow-toast" + (type === "error" ? " error" : type === "warn" ? " warn" : "");
  clearTimeout(showWorkflowToast.timer);
  showWorkflowToast.timer = setTimeout(()=>toast.textContent="",3200);
}

function saveAutoAddPreference(){
  localStorage.setItem("rareiq-auto-add",$("autoAddVerified").checked ? "1" : "0");
  localStorage.setItem("rareiq-auto-add-test",$("autoAddTestMode").checked ? "1" : "0");
  const status = $("autoAddLatchStatus");
  if(status && $("autoAddTestMode").checked){
    status.textContent = "TEST MODE — unverified candidates may be added";
  }
}

async function confirmCurrentCard(auto=false){
  if(autoAddInFlight) return;
  autoAddInFlight = true;
  try{
    const testMode = Boolean($("autoAddTestMode")?.checked);
    const currentStateId = state.recognitionState?.state_id || "";
    const endpoint = auto
      ? testMode
        ? `/api/session/test-auto-confirm-recognition?state_id=${encodeURIComponent(currentStateId)}`
        : `/api/session/auto-confirm-recognition?state_id=${encodeURIComponent(currentStateId)}`
      : "/api/session/confirm-recognition";
    const result = await post(endpoint);
    if(!result.ok){
      showWorkflowToast(result.error || "Card could not be added.","error");
      if(result.reason === "reference_required"){
        const status = $("autoAddLatchStatus");
        if(status) status.textContent = "Import this card's set before auto-add";
      }
      return;
    }
    if(result.duplicate_suppressed){
      showWorkflowToast(
        result.reason === "same_physical_card"
          ? "Same physical card detected — not added again."
          : "Duplicate scan suppressed.",
        "warn"
      );
      const status = $("autoAddLatchStatus");
      if(status) status.textContent = "Same card blocked — present a different card";
    }else{
      const isTestAdd = Boolean(result.card?.unverified_test_add);
      showWorkflowToast(
        `${result.card?.card_name || "Card"} added${isTestAdd ? " as an unverified test scan" : " to the current pack"}.`,
        isTestAdd ? "warn" : "ok"
      );
      const status = $("autoAddLatchStatus");
      if(status){
        status.textContent = isTestAdd
          ? "TEST ADD complete — present a different card"
          : auto
            ? "Added — waiting for a different card"
            : "Card added manually";
      }
    }
    if(result.session) renderSession(result.session);
    await refreshSessionWorkflow();
  }catch(error){
    showWorkflowToast(String(error),"error");
  }finally{
    autoAddInFlight = false;
  }
}

async function rejectCurrentCard(){
  const result = await post("/api/session/reject-recognition");
  if(!result.ok){
    showWorkflowToast(result.error || "Card could not be rejected.","error");
    return;
  }
  showWorkflowToast(`${result.rejected?.card_name || "Candidate"} rejected.`,"warn");
  await refreshSessionWorkflow();
}

function renderRecentScans(cards){
  const root = $("recentScans");
  root.innerHTML = "";
  if(!cards?.length){
    root.innerHTML = '<div class="recent-empty">No cards added yet.</div>';
    return;
  }
  cards.slice(0,6).forEach(card=>{
    const row = document.createElement("div");
    row.className = "recent-card";
    const visual = card.reference_image_url
      ? `<img src="${card.reference_image_url}" alt="">`
      : '<div class="recent-placeholder">CARD</div>';
    row.innerHTML = `
      ${visual}
      <div>
        <div class="recent-name">${card.english_name || card.card_name || "Unknown Card"}</div>
        <div class="recent-meta">${card.printed_name && card.english_name ? card.printed_name + " • " : ""}${card.collector_number || "—"} • ${card.language || "Unknown"} • ${card.rarity || "UNKNOWN"}</div>
      </div>
      <div class="recent-value">${money(card.raw_value || 0)}</div>`;
    root.appendChild(row);
  });
}

async function refreshSessionWorkflow(){
  try{
    const result = await fetch("/api/session/status",{cache:"no-store"}).then(r=>r.json());
    if(result.session){
      result.session.recent_cards = result.recent_cards || [];
      renderSession(result.session);
    }
    renderRecentScans(result.recent_cards || []);
    renderCoverageGuard(result.recognition_readiness || {});
    if(result.recognition_state) renderUnifiedRecognition(result.recognition_state);
  }catch(error){
    console.warn("Session workflow refresh failed",error);
  }
}

function exportSession(){
  window.open("/api/session/export","_blank");
}

function maybeAutoAdd(snapshot){
  if(!$("autoAddVerified")?.checked){
    autoReadySince = null;
    window.__rareiqPendingStateId = null;
    return;
  }

  const testMode = Boolean($("autoAddTestMode")?.checked);
  const readiness = snapshot?.auto_add || {};
  const ready = testMode
    ? Boolean(readiness.test_ready)
    : Boolean(readiness.production_ready);

  if(!ready || !snapshot?.state_id){
    autoReadySince = null;
    window.__rareiqPendingStateId = null;
    return;
  }

  if(window.__rareiqPendingStateId !== snapshot.state_id){
    window.__rareiqPendingStateId = snapshot.state_id;
    autoReadySince = Date.now();
    $("autoAddLatchStatus").textContent = testMode
      ? "TEST MODE — immutable candidate stabilizing…"
      : "Verified candidate stabilizing…";
    return;
  }

  const stableFor = testMode ? 650 : AUTO_ADD_STABLE_MS;
  if(Date.now() - autoReadySince < stableFor) return;

  const now = Date.now();
  if(autoAddInFlight || now - lastAutoAttemptAt < AUTO_ADD_ATTEMPT_COOLDOWN_MS) return;

  lastAutoAttemptAt = now;
  autoReadySince = null;
  $("autoAddLatchStatus").textContent = "Validating immutable state…";
  setTimeout(()=>confirmCurrentCard(true),120);
}

window.BatchController = Object.freeze({
  render: renderSession,
  start: startSession,
  refresh: refreshSessionWorkflow,
  confirm: confirmCurrentCard,
  reject: rejectCurrentCard,
  export: exportSession,
  autoAdd: maybeAutoAdd,
});
