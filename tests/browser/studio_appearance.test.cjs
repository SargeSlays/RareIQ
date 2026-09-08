const test = require('node:test');
const assert = require('node:assert/strict');
const {create, KEY, LEGACY_KEY} = require('../../rareiq/web/static/studio_appearance.js');
function host(initial = {}, blocked = false) {
  const values = new Map(Object.entries(initial));
  const media = {matches: false};
  const page = {dataset: {workspace: 'live'}, draft: {name: 'Keep this scene'}};
  return {values, media, page, matchMedia: () => media, document: {documentElement: page}, localStorage: {
    getItem: key => {if (blocked) throw Error('blocked'); return values.get(key) ?? null;},
    setItem: (key, value) => {if (blocked) throw Error('blocked'); values.set(key, value);}
  }};
}
test('first use defaults to Ignite; legacy migration is idempotent and preserves rollback data', () => {
  assert.equal(create(host()).snapshot().resolvedSkin, 'ignite');
  for (const [legacy, expected] of [['dark', 'ignite'], ['light', 'daylight'], ['system', 'ignite']]) {
    const h = host({[LEGACY_KEY]: legacy});
    const a = create(h);
    assert.equal(a.snapshot().resolvedSkin, expected);
    assert.equal(a.snapshot().followSystem, legacy === 'system');
    a.select('ember', true);
    assert.equal(create(h).snapshot().resolvedSkin, 'ember');
    assert.equal(h.values.get(LEGACY_KEY), legacy);
  }
});
test('five valid selections survive reload and malformed records recover safely', () => {
  for (const skin of ['ignite', 'afterdark', 'voltage', 'ember', 'daylight']) {
    const h = host(); const a = create(h); a.select(skin, true);
    assert.equal(create(h).snapshot().resolvedSkin, skin);
    assert.equal(h.page.dataset.theme, skin === 'daylight' ? 'light' : 'dark');
  }
  for (const value of ['bad json', '{}', 'null', JSON.stringify({version: 2, skin: 'other', followSystem: true})]) {
    assert.equal(create(host({[KEY]: value})).snapshot().resolvedSkin, 'ignite');
  }
});
test('OS following resolves in memory and explicit selection disables it', () => {
  const h = host({[LEGACY_KEY]: 'system'}); const a = create(h);
  h.media.matches = true; a.apply(); assert.equal(a.snapshot().resolvedSkin, 'daylight');
  a.select('voltage', true); h.media.matches = false; a.apply();
  assert.equal(a.snapshot().resolvedSkin, 'voltage'); assert.equal(a.snapshot().followSystem, false);
});
test('blocked storage keeps unsaved state without mutating other operator data', () => {
  const h = host({}, true); const draft = h.page.draft; const a = create(h);
  a.select('daylight', true); h.media.matches = false; a.apply();
  assert.equal(a.snapshot().resolvedSkin, 'daylight'); assert.equal(a.snapshot().persisted, false);
  for (let i=0; i<20; i++) a.select(i % 2 ? 'dark' : 'light', true);
  assert.equal(h.page.draft, draft); assert.equal(h.page.dataset.workspace, 'live');
});
