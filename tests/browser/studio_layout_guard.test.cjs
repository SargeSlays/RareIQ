'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { assertViewportControl, assertNoHorizontalOverflow } =
  require('../../tools/qa_production_freshness.cjs');

const viewport = { width: 320, height: 740 };
const visible = { x: 10, y: 20, width: 120, height: 44, visible: true, hit: true };

test('visible controls and a contained document satisfy visual geometry guards', () => {
  assertViewportControl(visible, viewport);
  assertNoHorizontalOverflow(320, 320);
});

for (const [name, patch] of [
  ['hidden control', { visible: false }],
  ['blank or covered viewport', { hit: false }],
  ['horizontal clipping', { x: 280 }],
  ['vertical clipping', { y: 730 }],
  ['negative off-screen position', { x: -120 }],
  ['empty control', { height: 0 }],
  ['invalid geometry', { width: NaN }]
]) {
  test('visual guard rejects ' + name, () => {
    assert.throws(() => assertViewportControl({ ...visible, ...patch }, viewport));
  });
}

test('document overflow cannot count as a visual pass', () => {
  assert.throws(() => assertNoHorizontalOverflow(320, 480));
  assert.throws(() => assertNoHorizontalOverflow(320, NaN));
});

test('main Studio shortcut uses the combined output without replacing camera-only routes', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../rareiq/web/static/control.html'), 'utf8');
  const shortcut = html.match(/<a\b[^>]*\bid="productionStudioOutput"[^>]*>/);
  assert.ok(shortcut, 'Studio output shortcut is missing');
  assert.match(shortcut[0], /href="\/output\/studio"/);
  assert.match(shortcut[0], /rel="noopener"/);
});
