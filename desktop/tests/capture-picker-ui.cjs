'use strict';
// Explicit visual rehearsal: intercepted local assets and synthetic choices only.
const assert = require('node:assert/strict'), fs = require('node:fs/promises'), path = require('node:path');
const { chromium } = require('playwright');
async function main() {
  const output = process.argv[2]; if (!output || !path.isAbsolute(output)) throw Error('Absolute evidence directory required');
  await fs.mkdir(output, { recursive: true });
  const root = path.resolve(__dirname, '..'), assets = new Map();
  for (const name of ['capture-picker.html', 'capture-picker.js', 'capture-picker.css']) assets.set('/' + name, await fs.readFile(path.join(root, name), 'utf8'));
  assets.set('/assets/producer-please.tokens.css', await fs.readFile(path.join(root, '../rareiq/web/static/brand/producer-please-v2/producer-please.tokens.css'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--mute-audio'] });
  try {
    for (const [width, height, skin] of [[900, 740, 'ignite'], [480, 620, 'ignite'], [900, 740, 'daylight'], [480, 620, 'daylight']]) {
      const page = await browser.newPage({ viewport: { width, height } });
      const faults = []; page.on('pageerror', error => faults.push(error.message));
      await page.route('**/*', route => { const url = new URL(route.request().url()), body = url.hostname === 'picker.invalid' && assets.get(url.pathname); return typeof body === 'string' ? route.fulfill({ status: 200, contentType: url.pathname.endsWith('.css') ? 'text/css' : url.pathname.endsWith('.js') ? 'text/javascript' : 'text/html', body }) : route.abort(); });
      await page.addInitScript(() => {
        window.chosen = []; window.cancelled = 0;
        const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180;
        const ctx = canvas.getContext('2d'); ctx.fillStyle = '#20242A'; ctx.fillRect(0, 0, 320, 180); ctx.fillStyle = '#FF8A00'; ctx.fillRect(40, 35, 240, 110);
        const thumbnail = canvas.toDataURL();
        window.producerCapturePicker = { list: async () => ({ phase: 'ready', audioIncluded: false, sources: [
          { id: 'choice-screen', name: 'Screen 1', kind: 'screen', thumbnail },
          { id: 'choice-slides', name: 'Presentation — sample slide deck', kind: 'window', thumbnail },
          { id: 'choice-long', name: 'A long window name that should stay within the source card without hiding any selection controls', kind: 'window', thumbnail },
          { id: 'choice-plain', name: '<script>text only</script>', kind: 'window', thumbnail: '' },
        ] }), choose: id => { window.chosen.push(id); return new Promise(() => {}); }, cancel: async () => { window.cancelled++; return { cancelled: true }; } };
        for (const name of ['getUserMedia', 'getDisplayMedia']) navigator.mediaDevices[name] = async () => { throw Error('Real capture forbidden'); };
      });
      await page.goto('https://picker.invalid/capture-picker.html');
      await page.locator('.source').last().waitFor();
      await page.evaluate(value => document.documentElement.dataset.operatorSkin = value, skin);
      assert.equal(await page.locator('input:checked').count(), 0);
      assert.equal(await page.locator('#shareCapture').isDisabled(), true);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.equal(await page.evaluate(() => document.getElementById('choices').getBoundingClientRect().bottom <= document.querySelector('footer').getBoundingClientRect().top), true);
      await page.locator('.source').nth(1).click();
      assert.equal(await page.locator('#shareCapture').isEnabled(), true);
      await page.locator('#shareCapture').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, `picker-${width}-${skin}.png`), fullPage: true });
      await page.locator('#shareCapture').click();
      await page.keyboard.press('Escape');
      assert.deepEqual(await page.evaluate(() => ({ chosen, cancelled })), { chosen: ['choice-slides'], cancelled: 1 });
      assert.deepEqual(faults, []); await page.close();
    }
    console.log('PASS: 4 synthetic layouts, explicit selection, Escape cancellation, no real capture');
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
