// Offline Studio dock/component QA. This is not a live-app or OBS acceptance test.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

function assertViewportControl(box, viewport, label = 'Control') {
  for (const key of ['x', 'y', 'width', 'height']) {
    assert.ok(Number.isFinite(box[key]), label + ': invalid ' + key);
  }
  assert.ok(box.width > 0 && box.height > 0, label + ': empty bounds');
  assert.ok(box.visible === true, label + ': hidden or transparent');
  assert.ok(box.x >= -1 && box.y >= -1, label + ': outside viewport');
  assert.ok(box.x + box.width <= viewport.width + 1, label + ': horizontal clipping');
  assert.ok(box.y + box.height <= viewport.height + 1, label + ': vertical clipping');
  assert.ok(box.hit === true, label + ': covered or clipped by another element');
}

function assertNoHorizontalOverflow(width, scrollWidth) {
  assert.ok(Number.isFinite(width) && width > 0, 'Invalid viewport width');
  assert.ok(Number.isFinite(scrollWidth) && scrollWidth <= width + 1,
    'Studio has document horizontal overflow');
}

async function main() {
  const { chromium } = require('playwright');
  const root = path.resolve(__dirname, '..');
  const staticRoot = path.join(root, 'rareiq/web/static');
  const output = path.join(root, '.tmp/studio-readiness-qa');
  const origin = 'http://rareiq.invalid';
  await fs.mkdir(output, { recursive: true });
  const control = await fs.readFile(path.join(staticRoot, 'control.html'), 'utf8');
  const script = await fs.readFile(path.join(staticRoot, 'studiox.js'), 'utf8');
  const docks = await fs.readFile(path.join(staticRoot, 'studio_docks.js'), 'utf8');
  const start = script.indexOf('const productionInputThumbnails=');
  const end = script.indexOf('async function loadProductionSwitcher(', start);
  assert.ok(start >= 0 && end > start, 'Switcher renderer boundary is missing');
  const renderer = script.slice(start, end);
  const report = {
    scope: 'offline Studio dock component; synthetic cameras; not full-app acceptance',
    passed: false, cases: 0, views: [], assetFailures: [], blockedRequests: 0,
    forwardedRequests: 0, syntheticCameraRequests: 0, screenshots: []
  };
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  let page;
  try {
    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 }, reducedMotion: 'reduce',
      serviceWorkers: 'block'
    });
    await context.addInitScript(() => {
      window.__studioQa = { mediaAttempts: 0, socketAttempts: 0 };
      const mediaBlocked = () => {
        window.__studioQa.mediaAttempts++;
        throw new Error('Real media is forbidden in offline Studio QA');
      };
      HTMLMediaElement.prototype.play = mediaBlocked;
      if (navigator.mediaDevices) {
        navigator.mediaDevices.getUserMedia = mediaBlocked;
        navigator.mediaDevices.getDisplayMedia = mediaBlocked;
      }
      window.WebSocket = window.EventSource = class {
        constructor() {
          window.__studioQa.socketAttempts++;
          throw new Error('Live connections are forbidden in offline Studio QA');
        }
      };
    });
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== 'GET' || url.origin !== origin) {
        report.blockedRequests++;
        return route.abort();
      }
      if (url.pathname === '/fixture') {
        return route.fulfill({ contentType: 'text/html; charset=utf-8',
          body: '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>' });
      }
      if (url.pathname.startsWith('/static/')) {
        const filename = path.resolve(staticRoot, decodeURIComponent(url.pathname.slice(8)));
        const relative = path.relative(staticRoot, filename);
        if (relative.startsWith('..') || path.isAbsolute(relative) || filename.endsWith('.js')) {
          report.blockedRequests++;
          return route.abort();
        }
        try {
          const body = await fs.readFile(filename);
          const types = { '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml; charset=utf-8',
            '.woff2': 'font/woff2', '.woff': 'font/woff', '.png': 'image/png',
            '.jpg': 'image/jpeg', '.webp': 'image/webp' };
          return route.fulfill({ body, contentType: types[path.extname(filename)] || 'application/octet-stream' });
        } catch {
          report.assetFailures.push(relative);
          return route.abort();
        }
      }
      if (/^\/api\/camera-slots\/[1-4]\/stream$/.test(url.pathname)) {
        report.syntheticCameraRequests++;
        return route.fulfill({ contentType: 'image/svg+xml; charset=utf-8',
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#183631"/><text x="320" y="180" text-anchor="middle" fill="white" font-size="24">Synthetic camera</text></svg>' });
      }
      report.blockedRequests++;
      return route.abort();
    });

    async function mount(savedLayout = null) {
      const current = await context.newPage();
      await current.goto(origin + '/fixture');
      const markup = await current.evaluate(({ html, savedLayout }) => {
        localStorage.clear();
        if (savedLayout) localStorage.setItem('rareiq.studio.docks.v1', JSON.stringify(savedLayout));
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const body = doc.body.cloneNode(false);
        // Isolate the dock component from navigation chrome, not from its theme or dock CSS.
        body.style.cssText = 'display:block!important;margin:0!important;padding:0!important;height:auto!important;overflow:auto!important';
        const mount = document.createElement('div');
        mount.style.cssText = 'padding:16px;min-width:0';
        const source = doc.querySelector('[data-workspace="broadcast"]');
        const workspace = source.cloneNode(false);
        workspace.classList.add('active');
        workspace.style.cssText = 'display:block!important;width:100%!important;height:auto!important;min-height:0!important;overflow:visible!important';
        workspace.append(source.querySelector('.broadcast-workspace-tabs'));
        for (const name of ['production-switcher-shell', 'production-scenes',
          'show-preflight', 'production-session', 'operator-health']) {
          const panel = source.querySelector('.' + name);
          panel.dataset.broadcastPanel = 'live';
          workspace.append(panel);
        }
        mount.append(workspace);
        body.append(mount);
        const styles = [...doc.querySelectorAll('link[rel="stylesheet"]')].map(el => el.outerHTML).join('');
        return '<!doctype html><html data-theme="dark"><head><meta charset="utf-8">' +
          '<title>RareIQ isolated Studio QA</title><base href="http://rareiq.invalid/">' +
          styles + '</head>' + body.outerHTML + '</html>';
      }, { html: control, savedLayout });
      await current.setContent(markup);
      await current.addScriptTag({ content: docks });
      await current.addScriptTag({ content: 'let productionSwitcherState={};const $=id=>document.getElementById(id);' + renderer });
      await current.evaluate(() => {
        ProducerStudioDocks.init(document.querySelector('[data-workspace="broadcast"]')).setView('live');
        document.getElementById('showPreflightSummary').textContent =
          'Synthetic fixture: outputs and devices are not exercised.';
        document.getElementById('productionSceneGrid').textContent = 'No scenes in this synthetic fixture.';
      });
      await current.evaluate(() => document.fonts.ready);
      return current;
    }

    async function render(ready) {
      await page.evaluate(value => renderProductionSwitcher({
        program_slot: 1, preview_slot: 2, generation: 1,
        slots: [1, 2].map(slot => ({
          slot_id: slot, source_id: 'synthetic-' + slot, connected: true,
          production_readiness: slot === 1 ? { ready: true } : value === null ? undefined :
            { ready: value, detail: value ? 'Fresh frame' : 'Camera 2 is connected but stale (last frame 5.0s ago)' }
        }))
      }), ready);
    }

    async function checkControl(selector, viewport) {
      await page.locator(selector).scrollIntoViewIfNeeded();
      const box = await page.locator(selector).evaluate(el => {
        const rect = el.getBoundingClientRect();
        const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
        let visible = !el.closest('[hidden]');
        for (let node = el; node; node = node.parentElement) {
          const css = getComputedStyle(node);
          if (css.display === 'none' || css.visibility !== 'visible' || Number(css.opacity) === 0) visible = false;
        }
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
          visible, hit: Boolean(hit && (hit === el || el.contains(hit))) };
      });
      assertViewportControl(box, viewport, selector);
    }

    page = await mount();
    const savedBefore = await page.evaluate(() =>
      document.querySelector('[data-workspace="broadcast"]')._studioDocks.snapshot());
    const outputLink = page.locator('#productionStudioOutput');
    assert.equal(await outputLink.getAttribute('href'), '/output/studio');
    assert.match(await outputLink.getAttribute('rel'), /noopener/);
    for (const [width, height] of [[1920, 1080], [3840, 2160], [1366, 768], [1024, 768], [390, 844], [320, 740]]) {
      const backgrounds = {};
      for (const theme of ['dark', 'light']) {
        await page.setViewportSize({ width, height });
        await page.evaluate(value => {
          document.documentElement.dataset.theme = value;
          if (value === 'light') document.documentElement.dataset.operatorSkin = 'daylight';
          else delete document.documentElement.dataset.operatorSkin;
        }, theme);
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        await render(false);
        assert.equal(await page.locator('#productionCut').isDisabled(), true);
        assert.equal(await page.locator('#productionAuto').isDisabled(), true);
        assert.match(await page.locator('#productionCut').getAttribute('title'), /stale/);
        assert.match(await page.locator('#productionPreviewLabel').textContent(), /stale/);
        await checkControl('#productionCut', { width, height });
        await checkControl('#productionAuto', { width, height });
        const geometry = await page.evaluate(() => ({
          width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
          background: getComputedStyle(document.body).getPropertyValue('--pp-bg').trim(),
          defaultPanels: [...document.querySelectorAll('.studio-dock-tool[data-custom-height="false"]:not([hidden])')]
            .map(el => ({ id: el.dataset.studioTool, clientHeight: el.clientHeight, scrollHeight: el.scrollHeight }))
        }));
        assertNoHorizontalOverflow(geometry.width, geometry.scrollWidth);
        if (width <= 1100) for (const panel of geometry.defaultPanels) {
          assert.ok(panel.scrollHeight <= panel.clientHeight + 2,
            panel.id + ': default narrow-screen panel unnecessarily clips its content');
        }
        assert.ok(geometry.background, 'Semantic theme tokens were not loaded');
        backgrounds[theme] = geometry.background;
        await checkControl('#showStartButton', { width, height });
        await checkControl('#productionIncidentTitle', { width, height });
        await page.evaluate(() => scrollTo(0, 0));
        const screenshot = 'stale-' + theme + '-' + width + '.png';
        await page.screenshot({ path: path.join(output, screenshot), fullPage: true, animations: 'disabled' });
        report.screenshots.push(screenshot);
        await render(null);
        assert.equal(await page.locator('#productionCut').isDisabled(), true);
        await render(true);
        assert.equal(await page.locator('#productionCut').isEnabled(), true);
        assert.equal(await page.locator('#productionAuto').isEnabled(), true);
        await page.locator('#productionCut').focus();
        assert.equal(await page.locator('#productionCut').evaluate(el => el === document.activeElement), true);
        report.cases += 3;
        report.views.push({ theme, width, height, horizontalOverflow: false });
      }
      assert.notEqual(backgrounds.dark, backgrounds.light, 'Light capture accidentally uses dark theme tokens');
    }
    assert.deepEqual(await page.evaluate(() =>
      document.querySelector('[data-workspace="broadcast"]')._studioDocks.snapshot()), savedBefore);
    assert.deepEqual(await page.evaluate(() => window.__studioQa), { mediaAttempts: 0, socketAttempts: 0 });
    await page.close();
    page = await mount({ version: 1, tools: {
      'show-preflight': { position: 'right', visible: true, height: 420, customHeight: true }
    } });
    await page.setViewportSize({ width: 1024, height: 768 });
    const custom = page.locator('[data-studio-tool="show-preflight"]');
    assert.equal(await custom.getAttribute('data-custom-height'), 'true');
    assert.ok(Math.abs((await custom.boundingBox()).height - 420) <= 2, 'Custom panel height was overwritten');
    assert.deepEqual(await page.evaluate(() => window.__studioQa), { mediaAttempts: 0, socketAttempts: 0 });
    assert.deepEqual(report.assetFailures, [], 'Local assets failed to load');
    report.cases++;
    report.passed = true;
  } catch (error) {
    report.error = error.message;
    if (page && !page.isClosed()) {
      await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true, animations: 'disabled' }).catch(() => {});
    }
    throw error;
  } finally {
    await fs.writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
    await browser.close();
    console.log(JSON.stringify({ passed: report.passed, cases: report.cases,
      views: report.views.length, forwardedRequests: report.forwardedRequests,
      evidence: path.relative(root, output), error: report.error }));
  }
}

module.exports = { assertViewportControl, assertNoHorizontalOverflow };
if (require.main === module) main().catch(error => {
  console.error(error.stack);
  process.exitCode = 1;
});
