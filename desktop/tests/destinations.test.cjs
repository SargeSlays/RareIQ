'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { randomBytes, createCipheriv, createDecipheriv } = require('node:crypto');
const { DestinationStore, PRESETS, validateServerUrl } = require('../destinations.cjs');

function syntheticCipher() {
  const key = randomBytes(32);
  return {
    available: true,
    async isAsyncEncryptionAvailable() { return this.available; },
    async encryptStringAsync(value) {
      const iv = randomBytes(12), cipher = createCipheriv('aes-256-gcm', key, iv);
      const data = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
      return Buffer.concat([iv, cipher.getAuthTag(), data]);
    },
    async decryptStringAsync(value) {
      const decipher = createDecipheriv('aes-256-gcm', key, value.subarray(0, 12));
      decipher.setAuthTag(value.subarray(12, 28));
      return { result: Buffer.concat([decipher.update(value.subarray(28)), decipher.final()]).toString('utf8'), shouldReEncrypt: false };
    },
  };
}
async function fixture(t, options = {}) {
  const root = path.resolve(os.tmpdir());
  const directory = await fs.mkdtemp(path.join(root, 'rareiq-destination-'));
  t.after(async () => { assert.equal(path.dirname(path.resolve(directory)), root); await fs.rm(directory, { recursive: true, force: true }); });
  const cipher = syntheticCipher();
  const store = new DestinationStore({ directory, cipher, platform: 'win32', ...options });
  return { store, cipher, directory, file: path.join(directory, 'destinations.json') };
}
const payload = overrides => ({ requestId: 'first-save', name: 'My channel', platform: 'twitch', streamKey: 'synthetic-secret-9a82', ...overrides });
const rejects = (promise, code) => assert.rejects(promise, error => error.code === code && error.message === code);

test('official Twitch secure preset; other platforms require their dashboard URL', () => {
  assert.equal(PRESETS.find(p => p.id === 'twitch').serverUrl, 'rtmps://ingest.global-contribute.live-video.net/app');
  assert.equal(PRESETS.find(p => p.id === 'youtube').serverUrl, '');
  assert.equal(PRESETS.find(p => p.id === 'kick').serverUrl, '');
  assert.equal(validateServerUrl('rtmps://INGEST.provider.com:443/app/'), 'rtmps://ingest.provider.com/app');
  assert.equal(validateServerUrl('rtmp://ingest.provider.com:1935/live', { platform: 'custom', allowInsecureRtmp: true }), 'rtmp://ingest.provider.com/live');
});

test('rejects nonbroadcast schemes, credentials, local/private/literal hosts and ambiguous URLs', () => {
  const invalid = [
    'https://ingest.provider.com/app', 'http://ingest.provider.com/app', 'file:///app', 'javascript:alert(1)',
    'rtmp://ingest.provider.com/app', 'rtmps://name:secret@ingest.provider.com/app',
    'rtmps://ingest.provider.com/app?key=secret', 'rtmps://ingest.provider.com/app#secret',
    'rtmps://ingest.provider.com/app?', 'rtmps://ingest.provider.com/app#',
    'rtmps://localhost/app', 'rtmps://machine/app', 'rtmps://a.local/app', 'rtmps://a.local./app',
    'rtmps://a.internal/app', 'rtmps://a.home.arpa/app', 'rtmps://a.lan/app', 'rtmps://a.test/app',
    'rtmps://127.0.0.1/app', 'rtmps://10.0.0.1/app', 'rtmps://169.254.169.254/app', 'rtmps://8.8.8.8/app',
    'rtmps://[::1]/app', 'rtmps://[fd00::1]/app', 'rtmps://2130706433/app', 'rtmps://0x7f000001/app',
    'rtmps://0177.0.0.1/app', 'rtmps://%31%32%37.0.0.1/app', 'rtmps://ingest.provider.com:65536/app',
    'rtmps://ingest.provider.com:0/app', 'rtmps://ingest.provider.com/app\\secret',
    'rtmps://ingest.provider.com/app%0asecret', 'rtmps://ingest.provider.com/app%3Fsecret',
    'rtmps://ingest.provider.com/app/{stream_key}', ' rtmps://ingest.provider.com/app',
  ];
  for (const value of invalid) assert.throws(() => validateServerUrl(value), error => error.name === 'DestinationError', value);
  assert.throws(() => validateServerUrl('rtmp://ingest.provider.com/app', { platform: 'twitch', allowInsecureRtmp: true }));
});

test('encrypted persistence, public redaction and main-only private access survive reload', async t => {
  const { store, cipher, directory, file } = await fixture(t);
  const secretServer = 'rtmps://ingest.provider.com/private-path-secret';
  const result = await store.save(payload({ platform: 'custom', serverUrl: secretServer }));
  const status = await store.public();
  assert.equal(result.destination.configured, true);
  assert.equal(status.destinations[0].connected, false);
  assert.equal(status.destinations[0].verified, false);
  assert.equal(status.destinations[0].platformLive, false);
  assert.equal(status.destinations[0].networkVerified, false);
  const disk = await fs.readFile(file, 'utf8');
  for (const serialized of [disk, JSON.stringify(result), JSON.stringify(status)]) {
    assert.equal(serialized.includes('synthetic-secret-9a82'), false);
    assert.equal(serialized.includes('private-path-secret'), false);
  }
  const reloaded = new DestinationStore({ directory, cipher, platform: 'win32' });
  const privateValue = await reloaded.getPrivateDestination(result.destination.id);
  assert.equal(privateValue.streamKey, 'synthetic-secret-9a82');
  assert.equal(privateValue.serverUrl, secretServer);
  assert.deepEqual(await reloaded.public(), status);
});

test('concurrent retries and restart replay create one profile; changed request conflicts', async t => {
  const { store, cipher, directory } = await fixture(t);
  const values = await Promise.all([store.save(payload()), store.save(payload()), store.save(payload())]);
  assert.equal(new Set(values.map(v => v.destination.id)).size, 1);
  assert.deepEqual(values.map(v => v.replayed), [false, true, true]);
  assert.equal((await store.public()).destinations.length, 1);
  const reloaded = new DestinationStore({ directory, cipher, platform: 'win32' });
  assert.equal((await reloaded.save(payload())).replayed, true);
  await rejects(store.save(payload({ streamKey: 'different-secret' })), 'destination_request_conflict');
});

test('blank key preserves; explicit clearing persists and stale retry never restores it', async t => {
  const { store, cipher, directory } = await fixture(t);
  const initial = await store.save(payload()); const id = initial.destination.id;
  await store.save(payload({ id, requestId: 'rename', name: 'Renamed', streamKey: '' }));
  assert.equal((await store.private(id)).streamKey, 'synthetic-secret-9a82');
  const cleared = await store.save(payload({ id, requestId: 'clear', streamKey: '', clearKey: true }));
  assert.equal(cleared.destination.configured, false);
  assert.equal(cleared.destination.status, 'needs_key');
  await rejects(store.private(id), 'destination_key_required');
  assert.equal((await store.save(payload())).destination.keyConfigured, false);
  const reloaded = new DestinationStore({ directory, cipher, platform: 'win32' });
  assert.equal((await reloaded.public()).destinations[0].keyConfigured, false);
});

test('changing a server cannot silently transfer a preserved stream key', async t => {
  const { store } = await fixture(t);
  const id = (await store.save(payload())).destination.id;
  await rejects(store.save(payload({ id, requestId: 'change', platform: 'custom', serverUrl: 'rtmps://ingest.provider.com/app', streamKey: '' })), 'destination_key_replacement_required');
  const updated = await store.save(payload({ id, requestId: 'change', platform: 'custom', serverUrl: 'rtmps://ingest.provider.com/app', streamKey: 'replacement' }));
  assert.equal(updated.destination.configured, true);
  assert.equal((await store.private(id)).streamKey, 'replacement');
});

test('DPAPI unavailable fails closed without creating plaintext; existing metadata remains locked', async t => {
  const { store, cipher, file } = await fixture(t);
  cipher.available = false;
  await rejects(store.save(payload()), 'secure_storage_unavailable');
  await assert.rejects(fs.stat(file), { code: 'ENOENT' });
  assert.equal((await store.public()).secureStorageAvailable, false);
  cipher.available = true;
  const id = (await store.save(payload())).destination.id;
  cipher.available = false;
  assert.equal((await store.public()).destinations[0].status, 'locked');
  await rejects(store.private(id), 'secure_storage_unavailable');
});

test('encryption/decryption errors never expose provider messages or secrets', async t => {
  const { store, cipher } = await fixture(t);
  const encrypt = cipher.encryptStringAsync;
  cipher.encryptStringAsync = async () => { throw Error('provider error synthetic-secret-9a82'); };
  await rejects(store.save(payload()), 'destination_encryption_failed');
  cipher.encryptStringAsync = encrypt;
  const id = (await store.save(payload())).destination.id;
  cipher.decryptStringAsync = async () => { throw Error('provider error synthetic-secret-9a82'); };
  assert.equal((await store.public()).destinations[0].status, 'locked');
  await rejects(store.private(id), 'destination_credentials_unavailable');
});

test('failed atomic rename preserves prior disk/in-memory data and permits retry', async t => {
  let failRename = false;
  const fileSystem = { ...fs, async rename(from, to) { if (failRename) throw Error('private filesystem diagnostic'); return fs.rename(from, to); } };
  const { store, file, directory } = await fixture(t, { fileSystem });
  const id = (await store.save(payload())).destination.id;
  const before = await fs.readFile(file, 'utf8');
  const update = payload({ id, requestId: 'update', name: 'Next', streamKey: 'new-secret' });
  failRename = true;
  await rejects(store.save(update), 'destination_storage_unavailable');
  assert.equal(await fs.readFile(file, 'utf8'), before);
  assert.equal((await store.private(id)).streamKey, 'synthetic-secret-9a82');
  assert.deepEqual(await fs.readdir(directory), ['destinations.json']);
  failRename = false;
  assert.equal((await store.save(update)).replayed, false);
  assert.equal((await store.private(id)).streamKey, 'new-secret');
});

test('removal is idempotent and old request IDs cannot resurrect removed keys', async t => {
  const { store } = await fixture(t);
  const id = (await store.save(payload())).destination.id;
  assert.equal((await store.remove(id)).alreadyAbsent, false);
  assert.equal((await store.remove(id)).alreadyAbsent, true);
  await rejects(store.save(payload()), 'destination_request_retired');
  await rejects(store.private(id), 'destination_not_found');
});

test('malformed existing storage is preserved and never replaced by a fresh store', async t => {
  const { store, file } = await fixture(t);
  const malformed = '{not valid JSON';
  await fs.writeFile(file, malformed);
  await rejects(store.public(), 'destination_storage_invalid');
  await rejects(store.save(payload()), 'destination_storage_invalid');
  assert.equal(await fs.readFile(file, 'utf8'), malformed);
});

test('explicit options and ID validation cannot be bypassed through renderer payloads', async t => {
  const { store } = await fixture(t);
  await rejects(store.save(payload({ requestId: '' })), 'destination_request_id_required');
  await rejects(store.save(payload({ clearKey: true })), 'conflicting_destination_key_action');
  await rejects(store.save(payload({ platform: 'custom', serverUrl: 'rtmp://ingest.provider.com/live', allowInsecureRtmp: 'true' })), 'invalid_destination_option');
  await rejects(store.save(payload({ platform: 'youtube' })), 'invalid_destination_url');
  await rejects(store.save(payload({ id: '../profile' })), 'invalid_destination_id');
  await rejects(store.save(payload({ token: 'extra-secret' })), 'invalid_destination_fields');
  await rejects(store.save(payload({ streamKey: 'key\ncommand' })), 'invalid_destination_key');
});

test('additional platform labels require the operator supplied secure server and key',async t=>{
  for(const platform of ['rumble','facebook','tiktok','x','instagram']){
    assert.equal(PRESETS.find(p=>p.id===platform).serverUrl,'');
    assert.equal(validateServerUrl('rtmps://ingest.provider.com/app',{platform}),'rtmps://ingest.provider.com/app');
    assert.throws(()=>validateServerUrl('rtmp://ingest.provider.com/app',{platform}));
  }
});
