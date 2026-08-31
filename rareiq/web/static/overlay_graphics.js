const box = document.getElementById("graphic");
const title = document.getElementById("graphicTitle");
const subtitle = document.getElementById("graphicSubtitle");
const image = document.getElementById("graphicImage");
const colors = {cyan: "var(--overlay-accent)", purple: "#b7a6df", gold: "var(--overlay-warning)", green: "var(--overlay-success)", red: "var(--overlay-danger)"};
let signature = "", hideTimer = 0, fallbackShownAt = 0, generation;

function clearGraphic() {
  clearTimeout(hideTimer);
  box.classList.remove("visible");
}

function renderGraphic(payload) {
  const graphic = payload.graphic || {};
  const now = Date.now();
  if (graphic.generation !== generation) {
    generation = graphic.generation;
    fallbackShownAt = now;
  }
  const next = JSON.stringify(graphic);
  if (next !== signature) {
    signature = next;
    title.textContent = graphic.title || "";
    subtitle.textContent = graphic.subtitle || "";
    box.dataset.kind = graphic.kind || "lower-third";
    box.dataset.style = graphic.style || "glass";
    box.style.setProperty("--accent", colors[graphic.accent] || colors.cyan);
    image.hidden = !graphic.image_url;
    if (graphic.image_url) image.src = graphic.image_url;
    else image.removeAttribute("src");
  }
  const duration = Math.max(0, Number(graphic.duration_ms) || 0);
  const shownAt = Number(graphic.shown_at) * 1000 || fallbackShownAt;
  const remaining = duration ? Math.max(0, shownAt + duration - now) : Infinity;
  const visible = graphic.visible === true && graphic.safety_status !== "blocked" && remaining > 0;
  clearTimeout(hideTimer);
  // Visibility is authoritative state, not an animation-generation side effect.
  box.classList.toggle("visible", visible);
  if (visible && duration) hideTimer = setTimeout(clearGraphic, remaining);
}

RareIQOverlay.start({
  interval: 250,
  load: signal => RareIQOverlay.json("/api/production/graphics", signal),
  render: renderGraphic,
  clear: clearGraphic,
});
