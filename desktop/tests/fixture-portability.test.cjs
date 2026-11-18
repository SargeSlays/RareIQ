'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

test('desktop filesystem fixtures use and clean an isolated OS temporary directory', t => {
  const parent = path.resolve(os.tmpdir());
  const root = fs.mkdtempSync(path.join(parent, 'rareiq-fixture-portability-'));
  t.after(() => {
    assert.equal(path.dirname(path.resolve(root)), parent);
    fs.rmSync(root, { recursive: true, force: true });
  });
  const temporary = path.join(root, 'isolated-temp');
  fs.mkdirSync(temporary);
  const preload = path.join(root, 'guard.cjs');
  fs.writeFileSync(preload, `
    const assert = require('node:assert/strict');
    const fs = require('node:fs');
    const path = require('node:path');
    const root = path.resolve(process.env.RAREIQ_FIXTURE_TEMP_ROOT);
    function guard(target) {
      const relative = path.relative(root, path.resolve(target));
      assert.ok(relative === '' || (!path.isAbsolute(relative) && relative !== '..' && !relative.startsWith('..' + path.sep)), 'Fixture allocation escaped isolated temporary directory');
    }
    for (const name of ['mkdirSync', 'mkdtempSync']) {
      const original = fs[name];
      fs[name] = function(target, ...args) { guard(target); return original.call(this, target, ...args); };
    }
    for (const name of ['mkdir', 'mkdtemp']) {
      const original = fs.promises[name];
      fs.promises[name] = function(target, ...args) { guard(target); return original.call(this, target, ...args); };
    }
  `);
  // A nested runner must not inherit the outer runner's worker context: Node 22
  // otherwise skips every file with a warning and exits successfully.
  const environment = { ...process.env, TEMP: temporary, TMP: temporary, TMPDIR: temporary, RAREIQ_FIXTURE_TEMP_ROOT: temporary };
  delete environment.NODE_TEST_CONTEXT;
  const result = spawnSync(process.execPath, [
    '--require', preload, '--test', '--test-reporter=tap',
    path.join(__dirname, 'destinations.test.cjs'),
    path.join(__dirname, 'runtime.test.cjs'),
  ], {
    encoding: 'utf8', timeout: 30000,
    env: environment,
  });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /encrypted persistence, public redaction/);
  assert.match(result.stdout, /bundled paths resolve against app resources/);
  assert.doesNotMatch(result.stderr, /skipping running files/);
  assert.deepEqual(fs.readdirSync(temporary), [], 'Fixtures left temporary profiles behind');
});
