/* Shared operator/browser-source rules. Scan completion never implies verification. */
window.RareIQMultiCard = (() => {
  const emptyStates = new Set(["empty", "waiting", "not-detected"]);
  function name(card = {}) {
    return card.english_name || card.printed_name || card.canonical_name || card.name || card.display_name || "Unidentified card";
  }
  function referenceImage(card = {}) {
    const direct = card.reference_image_url || card.image_url;
    if (direct) return String(direct).replaceAll("\\", "/");
    const local = card.image_path || card.reference_image || card.local_image;
    if (!local || typeof local !== "string") return "";
    return /^(https?:\/\/|\/api\/|\/static\/)/i.test(local)
      ? local.replaceAll("\\", "/") : `/api/reference-image?path=${encodeURIComponent(local)}`;
  }
  function ready(item = {}) {
    const card = item.card;
    return Boolean(item.output_ready !== false && item.verified === true && item.status === "verified"
      && card && name(card) !== "Unidentified card" && !item.exact_version_unresolved
      && !card.exact_version_unresolved && !card.provisional);
  }
  function visibleSlots(payload = {}) {
    return (Array.isArray(payload.slots) ? payload.slots : [])
      .filter(item => item && Number.isInteger(item.slot) && item.slot >= 1 && item.slot <= 12 && !emptyStates.has(item.status));
  }
  function counts(payload = {}) {
    const slots = visibleSlots(payload);
    const pending = slots.filter(item => item.status === "recognizing").length;
    const verified = slots.filter(ready).length;
    return {detected: slots.length, processed: slots.length - pending, verified, pending, review: slots.length - pending - verified};
  }
  function presentation(payload = {}, capacity = 12) {
    const status = String(payload.status || "idle"), total = counts(payload);
    // Capture returns ok:false when geometry found no cards; that is not a transport failure.
    if (status === "no-cards-detected") return {state:"warning", badge:"No cards found", summary:"No complete card regions detected", guidance:"Separate the cards, keep every border visible, and scan again."};
    if (status === "error" || payload.ok === false) return {state:"warning", badge:"Scan unavailable", summary:"The scan could not be completed", guidance:payload.message || "Check the camera connection and try Scan Cards again."};
    if (status === "detecting") return {state:"active", badge:"Finding cards", summary:`Scanning for up to ${capacity} complete cards`, guidance:"Hold the cards still with every border visible."};
    if (status === "recognizing") return {state:"active", badge:"Recognition active", summary:`${total.processed} of ${total.detected} analyzed · ${total.verified} verified`, guidance:"Results appear below as each card is analyzed. Only verified identities can go on screen."};
    if (status === "complete" && !total.detected) return {state:"warning", badge:"No cards found", summary:"No complete card regions detected", guidance:"Separate the cards, keep every border visible, and scan again."};
    if (status === "complete") return {
      state:total.review ? "warning" : "complete",
      badge:payload.restored ? "Saved scan" : total.review ? "Review needed" : "Scan complete",
      summary:`${total.verified} of ${total.detected} verified${total.review ? ` · ${total.review} need review` : ""}`,
      guidance:payload.restored ? "Showing saved results, not a fresh capture. Scan Cards to identify what is on the table now."
        : total.review ? "Unverified cards stay off screen. Check their reference details or reposition them and scan again."
        : "Choose Show on a verified result to send it to the selected-card browser source."
    };
    return {state:"ready", badge:"Ready to scan", summary:`Find up to ${capacity} cards`, guidance:"Place complete cards in view, then choose Scan Cards. Only detected cards will appear below."};
  }
  function confidence(item = {}) {
    const value = item.confidence ?? item.card?.confidence;
    return typeof value === "number" && Number.isFinite(value) ? `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` : "Not scored";
  }
  function cameraPresentation(payload = {}) {
    const model = presentation(payload, Number(payload.max_cards) || 12);
    const key = payload.status === "no-cards-detected" ? "review-needed"
      : payload.ok === false || payload.status === "error" ? "error"
      : model.state === "complete" ? "exact-match"
      : model.state === "warning" ? "review-needed"
      : payload.status === "detecting" ? "detecting"
      : model.state === "active" ? "scanning" : "ready";
    return {key, title:model.badge.toUpperCase(), detail:`${model.summary}. ${model.guidance}`};
  }
  return {name, referenceImage, ready, visibleSlots, counts, presentation, confidence, cameraPresentation};
})();
