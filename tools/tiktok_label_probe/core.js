/* Observed DOM contract, 2026-08-30. Not a TikTok API or authoritative event ledger. */
(function (root) {
  "use strict";
  const VERSION = "0.3.0";
  const SELECTORS = Object.freeze({
    container: '[data-e2e="live-chat-container"]',
    row: '[data-e2e="chat-message"], [data-e2e="enter-message"], [data-e2e="social-message"], [data-index] > div:not([data-e2e])',
    owner: '[data-e2e="message-owner-name"]'
  });
  const CAPABILITIES = Object.freeze({
    chat: "observed-public-dom",
    joins: "observed-public-dom-best-effort",
    stable_viewer_ids: "not-exposed-in-inspected-rows",
    provider_event_ids: "not-exposed-in-inspected-rows",
    gifts: "observed-public-dom-notices-only", gift_quantity_semantics: "unverified",
    gift_streak_completion: "unverified", follows: "observed-public-dom-best-effort",
    fan_club_notices: "observed-public-dom-unattributed", shares: "unverified",
    individual_likes: "unverified", super_fans: "unverified",
    production_actions: "disabled"
  });

  function roomFromUrl(value) {
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || !["www.tiktok.com", "tiktok.com"].includes(url.hostname)
          || url.port || url.username || url.password) return null;
      const match = /^\/@([A-Za-z0-9_.]{1,64})\/live\/?$/.exec(url.pathname);
      return match ? `tiktok:@${match[1].toLowerCase()}` : null;
    } catch (_) { return null; }
  }

  function clean(value, max) {
    return String(value || "").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "")
      .replace(/\s+/g, " ").trim().slice(0, max);
  }

  function readableText(node) {
    if (node.nodeType === 3) return node.textContent || "";
    const tag = String(node.tagName || "").toUpperCase();
    if (["SCRIPT", "STYLE", "TEMPLATE", "SVG"].includes(tag)) return "";
    if (tag === "IMG") return clean(node.getAttribute("alt"), 80);
    return Array.from(node.childNodes || []).map(readableText).join("");
  }

  function parseRow(row) {
    const marker = row.getAttribute("data-e2e");
    if (!marker) return parseUnlabelledNotice(row);
    if (!["chat-message", "enter-message", "social-message"].includes(marker)) return {error: "unmapped-label"};
    const owners = row.querySelectorAll(SELECTORS.owner);
    if (owners.length !== 1) return {error: "owner-shape-changed"};
    const owner = owners[0];
    const displayName = clean(owner.textContent, 128);
    if (!displayName) return {error: "missing-display-name"};
    // Inspected rows: avatar, then a content column containing owner header and body.
    // Fail closed on markup changes instead of parsing badges/tooltips as chat text.
    let column = row.children[1];
    if (marker === "social-message") {
      // Observed follow: icon, content column, then one wrapper holding owner + span.
      if (!column || column.children.length !== 1) return {error: "social-shape-changed"};
      column = column.children[0];
      if (column.children[1]?.tagName !== "SPAN") return {error: "social-shape-changed"};
    }
    if (!column || column.children.length !== 2 || !column.children[0].contains(owner)) {
      return {error: "content-shape-changed"};
    }
    const body = column.children[1];
    if (body.querySelector(SELECTORS.owner)) return {error: "content-shape-changed"};
    const rawText = readableText(body);
    const text = clean(rawText, 4096);
    if (!text) return {error: "empty-content"};
    // Only this English join notice has been inspected; don't infer other actions.
    if (marker === "enter-message" && text !== "joined") return {error: "unmapped-enter-notice"};
    if (marker === "social-message" && text !== "followed the host") return {error: "unmapped-social-notice"};
    return {
      type: marker === "chat-message" ? "chat.message" : marker === "enter-message" ? "viewer.join.observed" : "viewer.follow.observed",
      provider_label: marker,
      actor: {id: null, handle: null, display_name: displayName, identity_quality: "display-name-only"},
      text: marker === "chat-message" ? text : null,
      truncated: rawText.length > 4096 || (owner.textContent || "").length > 128
    };
  }

  function parseUnlabelledNotice(row) {
    // Inspected English gift and Fan Club notices share an icon/list wrapper.
    // A virtual list index is NOT an event ID; never derive identity from prose.
    if (!/^\d+$/.test(row.parentElement?.getAttribute("data-index") || "") || row.children.length !== 2) {
      return {error: "unmapped-label"};
    }
    const [icon, body] = row.children;
    if (icon.children.length !== 1 || String(icon.children[0].tagName).toUpperCase() !== "SVG") return {error: "unmapped-notice-shape"};
    if (body.children.length) return parseGiftNotice(row, body);
    if (!Array.from(body.childNodes).every(node => node.nodeType === 3)) return {error: "unmapped-notice-shape"};
    const text = clean(body.textContent, 4096);
    if (!/^.{1,128} became the No\. [1-9]\d{0,8} fan in the Fan Club$/.test(text)) return {error: "unmapped-notice"};
    return {type: "viewer.fan_club_notice.observed", provider_label: null,
      actor: {id: null, handle: null, display_name: null, identity_quality: "unattributed"},
      text, truncated: false};
  }

  function parseGiftNotice(row, body) {
    // Observed DOM: owner wrapper, " sent ", gift-name span, image span,
    // " × ", quantity text. Badges belong to the owner wrapper, not the name.
    const nodes = Array.from(body.childNodes);
    const [header, sent, name, image, times, quantity] = nodes;
    if (nodes.length !== 6 || header?.tagName !== "DIV" || name?.tagName !== "SPAN"
        || image?.tagName !== "SPAN" || sent?.nodeType !== 3 || times?.nodeType !== 3 || quantity?.nodeType !== 3
        || clean(sent.textContent, 32) !== "sent" || clean(times.textContent, 32) !== "×"
        || !name.childNodes.length || !Array.from(name.childNodes).every(node => node.nodeType === 3)
        || image.childNodes.length !== 1 || image.children[0]?.tagName !== "IMG") return {error: "unmapped-gift-shape"};
    const owners = row.querySelectorAll(SELECTORS.owner);
    if (owners.length !== 1 || !header.contains(owners[0])) return {error: "owner-shape-changed"};
    const displayName = clean(owners[0].textContent, 128);
    if (!displayName) return {error: "missing-display-name"};
    const rawName = name.textContent || "", rawQuantity = (quantity.textContent || "").trim();
    const giftName = clean(rawName, 160);
    // Bound the raw strings before conversion; no truncated or coerced quantities.
    if (!giftName || rawName.length > 160 || !/^[1-9]\d{0,8}$/.test(rawQuantity)) return {error: "unmapped-gift-value"};
    return {type: "gift.notice.observed", provider_label: null,
      actor: {id: null, handle: null, display_name: displayName, identity_quality: "display-name-only"},
      text: null, truncated: (owners[0].textContent || "").length > 128,
      gift: {name: giftName, id: null, displayed_quantity: Number(rawQuantity), quantity_semantics: "unknown",
        streak_id: null, streak_complete: null, coin_value: null}};
  }

  class Recorder {
    constructor({room, sessionId, now = Date.now, capacity = 500, dedupMs = 5000} = {}) {
      if (!room || !sessionId || !Number.isInteger(capacity) || capacity < 1 || capacity > 500
          || !Number.isFinite(dedupMs) || dedupMs < 0 || dedupMs > 60000) throw new Error("Invalid probe settings");
      this.room = room;
      this.sessionId = sessionId;
      this.now = now;
      this.capacity = capacity;
      this.dedupMs = dedupMs;
      this.rows = new WeakMap();
      this.recent = new Map();
      this.events = [];
      this.sequence = 0;
      this.startedAt = new Date(now()).toISOString();
      this.counters = {observed: 0, initial_rows_skipped: 0, redraws_skipped: 0,
        ambiguous_repeats_skipped: 0, malformed_rows: 0, evicted_records: 0, coverage_gaps: 0};
    }

    ingest(entries, {baseline = false} = {}) {
      const emitted = [];
      const time = this.now();
      for (const [key, at] of this.recent) if (time - at >= this.dedupMs) this.recent.delete(key);
      for (const {node, parsed} of entries) {
        const signature = JSON.stringify(parsed);
        if (this.rows.get(node) === signature) { this.counters.redraws_skipped++; continue; }
        this.rows.set(node, signature);
        if (parsed.error) { this.counters.malformed_rows++; continue; }
        const repeated = this.recent.has(signature);
        this.recent.delete(signature);
        this.recent.set(signature, time);
        while (this.recent.size > 1000) this.recent.delete(this.recent.keys().next().value);
        if (baseline) { this.counters.initial_rows_skipped++; continue; }
        // With no provider IDs, two identical new rows may be a redraw OR a genuine
        // repeated comment. Suppress conservatively and report the ambiguity, never
        // claim exact event totals or use these records for prizes/contributions.
        if (repeated) { this.counters.ambiguous_repeats_skipped++; continue; }
        const event = {
          schema_version: 1, observation_id: `${this.sessionId}:${++this.sequence}`,
          platform: "tiktok", room_key: this.room, collector_session_id: this.sessionId,
          provider_event_id: null, occurred_at: null, observed_at: new Date(time).toISOString(),
          type: parsed.type, actor: {...parsed.actor}, text: parsed.text,
          provider_label: parsed.provider_label, truncated: parsed.truncated,
          source: {transport: "public-dom", adapter_version: VERSION, deduplication: "best-effort"},
          eligible_for_actions: false, eligible_for_contributions: false
        };
        if (parsed.type === "gift.notice.observed") {
          // Display observations only: a changed quantity is not an additional
          // transaction. Never sum it or infer streak completion/monetary value.
          event.gift = {name: parsed.gift.name, displayed_quantity: parsed.gift.displayed_quantity,
            id: null, quantity_semantics: "unknown", streak_id: null, streak_complete: null, coin_value: null};
        }
        this.events.push(event);
        if (this.events.length > this.capacity) { this.events.shift(); this.counters.evicted_records++; }
        this.counters.observed++;
        emitted.push(event);
      }
      return emitted;
    }

    coverageGap() { this.counters.coverage_gaps++; }
    summary() { return {counters: {...this.counters}, buffered: this.events.length}; }
    report(includeText = false) {
      return {
        schema_version: 1, kind: "rareiq-live-label-probe", off_air: true, adapter_version: VERSION,
        room_key: this.room, collector_session_id: this.sessionId,
        started_at: this.startedAt, exported_at: new Date(this.now()).toISOString(),
        capabilities: {...CAPABILITIES}, counters: {...this.counters},
        personal_text_included: Boolean(includeText),
        limitations: ["Rendered messages only; completeness unknown", "Display names are not account IDs",
          "Identical messages within five seconds may be undercounted", "No authenticated provider timestamps or event IDs",
          "Gift quantities are display snapshots, never additive; streak completion and coin values are unknown",
          "Do not import as verified contributions, giveaway entries or live alerts"],
        events: this.events.map(event => ({...event, ...(event.gift ? {gift: {...event.gift}} : {}), source: {...event.source}, actor: {...event.actor,
          display_name: includeText || event.actor.display_name === null ? event.actor.display_name : "[redacted]"},
          text: includeText ? event.text : event.text === null ? null : "[redacted]"}))
      };
    }
  }

  const api = Object.freeze({VERSION, SELECTORS, CAPABILITIES, roomFromUrl, parseRow, Recorder});
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RareIQLabelProbeCore = api;
})(typeof window === "undefined" ? {} : window);
