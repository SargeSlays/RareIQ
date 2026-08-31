/* A replay follows the server timeline, including reloads and reconnections. */
const replay = document.getElementById("replay");
const frame = document.getElementById("frame");
const progress = document.getElementById("progress");
let playback = null, drawTimer = 0, imageRequest = 0, frameUrl = "";

function clearReplay() {
  clearTimeout(drawTimer);
  drawTimer = 0;
  playback = null;
  imageRequest++;
  frameUrl = "";
  frame.onload = frame.onerror = null;
  frame.removeAttribute("src");
  replay.classList.remove("active");
  progress.style.width = "0%";
}

function drawReplay() {
  clearTimeout(drawTimer);
  drawTimer = 0;
  if (!playback) return;
  const {item, play} = playback;
  const elapsed = Math.max(0, Date.now() / 1000 - play.started_at);
  const position = elapsed * item.fps * play.speed;
  const index = Math.floor(position + 1e-7);
  if (index >= item.frames) {
    clearReplay();
    return;
  }
  const url = `/api/production/replay/${encodeURIComponent(item.id)}/frame/${index}?g=${play.generation}`;
  if (frameUrl !== url) {
    frameUrl = url;
    const request = ++imageRequest;
    frame.onload = () => {
      if (request === imageRequest && playback) replay.classList.add("active");
    };
    frame.onerror = () => {
      if (request === imageRequest) clearReplay();
    };
    frame.src = url;
  }
  progress.style.width = `${Math.min(100, position / item.frames * 100)}%`;
  drawTimer = setTimeout(drawReplay, Math.max(10, (index + 1 - position) * 1000 / item.fps / play.speed));
}

function renderReplay(state) {
  const play = state.playback || {};
  const item = (state.highlights || []).find(item => item.id === play.highlight_id);
  if (play.active !== true || !item || !Number.isInteger(item.frames) || item.frames < 1 ||
      !Number.isFinite(item.fps) || item.fps < 1 || item.fps > 60 ||
      !Number.isFinite(play.speed) || play.speed < .25 || play.speed > 2 ||
      !Number.isFinite(play.started_at) || play.started_at <= 0) {
    clearReplay();
    return;
  }
  const key = `${item.id}:${play.generation}:${play.started_at}`;
  if (playback?.key !== key) clearReplay();
  playback = {item, play, key};
  drawReplay();
}

RareIQOverlay.start({
  interval: 250,
  load: signal => RareIQOverlay.json("/api/production/replay", signal),
  render: renderReplay,
  clear: clearReplay,
});
