'use strict';
const { app, BrowserWindow, ipcMain } = require('electron');
const http = require('node:http'), path = require('node:path');
const { createOutputCapture } = require('../output-capture.cjs');
app.setPath('userData', process.env.PRODUCER_OUTPUT_QA_PROFILE);
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
function wave(frequency) {
  const n = 48000 * 5, bytes = Buffer.alloc(44 + n * 2); bytes.write('RIFF'); bytes.writeUInt32LE(36 + n * 2, 4); bytes.write('WAVEfmt ', 8); bytes.writeUInt32LE(16, 16); bytes.writeUInt32LE(1, 20); bytes.writeUInt16LE(1, 22); bytes.writeUInt32LE(48000, 24); bytes.writeUInt32LE(96000, 28); bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34); bytes.write('data', 36); bytes.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) bytes.writeInt16LE(Math.round(Math.sin(2 * Math.PI * frequency * i / 48000) * 16000), 44 + i * 2);
  return bytes;
}
const media = new Map([440, 880, 1100].map(f => ['/tone-' + f + '.wav', wave(f)]));
const base = '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:black}iframe{border:0}audio{display:none}</style></head><body>';
let server, capture;
app.whenReady().then(async () => {
  server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
    if (media.has(pathname)) { res.writeHead(200, { 'Content-Type': 'audio/wav', 'Content-Length': media.get(pathname).length }); return res.end(media.get(pathname)); }
    res.setHeader('Content-Type', 'text/html');
    if (pathname === '/output/studio') return res.end(base + '<iframe class="program" src="/program" allow="autoplay" style="width:100%;height:100%"></iframe><iframe class="audio" src="/output/soundboard" allow="autoplay" style="position:absolute;width:1px;height:1px"></iframe><iframe class="backstage" src="/private" allow="autoplay" style="position:absolute;width:1px;height:1px"></iframe></body></html>');
    if (pathname === '/program') return res.end(base + `<canvas style="width:100%;height:100%" width="1280" height="720"></canvas><audio id="tone" src="/tone-440.wav" loop autoplay></audio><iframe src="/private" allow="autoplay" style="position:absolute;width:1px;height:1px"></iframe><script>window.reviewOpen=false;window.ProducerProgramOutput={snapshot:()=>({peerId:'synthetic-output-peer',generation:1,rendered:true,browserReviewOpen:window.reviewOpen,readySources:['camera:1'],audioBlocked:false})};const tone=document.querySelector('audio');tone.volume=.4;let n=0;const ctx=document.querySelector('canvas').getContext('2d');setInterval(()=>{ctx.fillStyle=n++%2?'#ff0000':'#0000ff';ctx.fillRect(0,0,1280,720);ctx.fillStyle='white';ctx.fillRect(n%1200,300,60,60);},40);</script></body></html>`);
    if (pathname === '/output/soundboard') return res.end(base + '<audio id="sound" src="/tone-880.wav" loop autoplay muted></audio></body></html>');
    if (pathname === '/private') return res.end(base + '<audio src="/tone-1100.wav" loop autoplay></audio></body></html>');
    res.statusCode = 404; res.end(base + 'Unknown fixture');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const stats = { video: [], audio: [], errors: [] };
  capture = createOutputCapture({ BrowserWindow, ipcMain, origin, width: Number(process.env.PRODUCER_OUTPUT_QA_WIDTH || 1280), height: Number(process.env.PRODUCER_OUTPUT_QA_HEIGHT || 720), onError: code => stats.errors.push(code) });
  globalThis.outputFixture = {
    capture, stats, origin,
    reset() { stats.video = []; stats.audio = []; },
    async start() { return capture.startCapture((buffer, ptsUs) => { stats.video.push({ ptsUs, bytes: buffer.length, b: buffer[0], r: buffer[2] }); if (stats.video.length > 120) stats.video.shift(); return true; }, (buffer, ptsUs) => {
      let sum = 0, stereoError = 0; for (let i = 0; i < buffer.length; i += 8) { const l = buffer.readFloatLE(i), r = buffer.readFloatLE(i + 4); sum += l * l; stereoError += Math.abs(l - r); }
      stats.audio.push({ ptsUs, rms: Math.sqrt(sum / (buffer.length / 8)), stereoError, bytes: buffer.length }); if (stats.audio.length > 200) stats.audio.shift(); return true;
    }); },
    close() { capture.close(); server.close(); app.quit(); },
  };
  await capture.prepare(); globalThis.outputFixture.ready = true;
}).catch(error => { globalThis.outputFixtureError = error.message; });
app.on('window-all-closed', () => {});
