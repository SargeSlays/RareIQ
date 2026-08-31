const screen = document.getElementById("screen"), title = document.getElementById("title");
const message = document.getElementById("message"), countdown = document.getElementById("countdown");
const bar = document.getElementById("bar"), eyebrow = document.getElementById("eyebrow");
const colors = {cyan: "var(--overlay-accent)", purple: "#b7a6df", gold: "var(--overlay-warning)", green: "var(--overlay-success)", red: "var(--overlay-danger)"};
const labels = {"starting-soon": "STREAM STARTING", brb: "BE RIGHT BACK", ending: "STREAM COMPLETE", countdown: "COUNTDOWN"};

function renderScreen(payload) {
  const state = payload.screen || {};
  title.textContent = state.title || "Starting Soon";
  message.textContent = state.message || "";
  eyebrow.textContent = labels[state.mode] || "LIVE PRODUCTION";
  screen.style.setProperty("--accent", colors[state.accent] || colors.cyan);
  screen.classList.toggle("visible", state.visible === true);
  const total = Number(state.countdown_seconds) || 0;
  const elapsed = Math.max(0, Date.now() / 1000 - (Number(state.started_at) || 0));
  const left = Math.max(0, Math.ceil(total - elapsed));
  countdown.textContent = total ? `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}` : "";
  bar.style.width = total ? `${Math.max(0, left / total * 100)}%` : "100%";
}

RareIQOverlay.start({
  interval: 250,
  load: signal => RareIQOverlay.json("/api/production/screen", signal),
  render: renderScreen,
  clear: () => screen.classList.remove("visible"),
});
