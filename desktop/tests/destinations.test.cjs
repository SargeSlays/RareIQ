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

test('linked Kick saves only an encrypted account reference and privately refreshes its secure ingest settings',async t=>{
  const ref='c'.repeat(64),calls=[];
  const accountResolver=async(accountRef,options)=>{calls.push({accountRef,options});return {platform:'kick',accountRef,serverUrl:'rtmps://ingest.provider.com:443/private-live',streamKey:'private-kick-key-'+calls.length};};
  const f=await fixture(t,{accountResolver}),input={requestId:'kick-link',name:'Kick account',platform:'kick',accountRef:ref};
  await rejects(f.store.save(input),'invalid_destination_fields');
  const saved=await f.store.saveAccount(input),pub=saved.destination;assert.equal(pub.linkedAccount,true);assert.equal(pub.configured,true);assert.equal(pub.serverConfigured,false);
  for(const key of ['connected','verified','platformLive','networkVerified'])assert.equal(pub[key],false);
  assert.equal(calls.length,0,'saving a link never fetches private settings');
  const disk=await fs.readFile(f.file,'utf8'),stored=JSON.parse(disk),decoded=JSON.parse((await f.cipher.decryptStringAsync(Buffer.from(stored.profiles[0].encrypted,'base64'))).result);
  assert.deepEqual(decoded,{id:pub.id,platform:'kick',allowInsecureRtmp:false,accountRef:ref});
  const first=await f.store.getPrivateDestination(pub.id);assert.equal(first.serverUrl,'rtmps://ingest.provider.com/private-live');assert.equal(first.streamKey,'private-kick-key-1');assert.deepEqual(calls,[{accountRef:ref,options:{platform:'kick'}}]);
  const reloaded=new DestinationStore({directory:f.directory,cipher:f.cipher,platform:'win32',accountResolver});assert.equal((await reloaded.private(pub.id)).streamKey,'private-kick-key-2');
  assert.equal(await fs.readFile(f.file,'utf8'),disk,'resolved settings are never persisted');
  for(const value of [disk,JSON.stringify(await reloaded.public()),JSON.stringify(saved)])for(const sensitive of [ref,'private-kick-key','private-live','rtmps://ingest.provider.com'])assert.equal(value.includes(sensitive),false);
});

test('linked accounts deduplicate by provider and reference and cannot silently change providers',async t=>{
  const ref='d'.repeat(64),f=await fixture(t),input={name:'Same identity hash',accountRef:ref};
  const twitch=await f.store.saveAccount({...input,platform:'twitch',requestId:'twitch-account'}),kick=await f.store.saveAccount({...input,platform:'kick',requestId:'kick-account'});
  assert.notEqual(twitch.destination.id,kick.destination.id);const repeated=await f.store.saveAccount({...input,platform:'kick',requestId:'kick-account-again'});assert.equal(repeated.destination.id,kick.destination.id);assert.equal((await f.store.public()).destinations.length,2);
  assert.equal((await f.store.saveAccount({...input,platform:'kick',requestId:'kick-account'})).replayed,true);
  await rejects(f.store.saveAccount({...input,id:twitch.destination.id,platform:'kick',requestId:'cross-provider'}),'account_destination_managed');
  await rejects(f.store.saveAccount({...input,id:kick.destination.id,platform:'kick',accountRef:'e'.repeat(64),requestId:'cross-account'}),'account_destination_managed');
  await rejects(f.store.save(payload({id:kick.destination.id,platform:'kick',requestId:'manual-kick',serverUrl:'rtmps://ingest.provider.com/app'})),'account_destination_managed');
});

test('Kick linked input accepts no URL, key or insecure transport fields even when empty',async t=>{
  const f=await fixture(t),input={name:'Kick account',platform:'kick',accountRef:'f'.repeat(64),requestId:'kick-input'};
  for(const change of [{serverUrl:''},{streamKey:''},{clearKey:false},{allowInsecureRtmp:false},{streamKey:'private'},{serverUrl:'rtmps://ingest.provider.com/app'},{accountRef:'bad'},{platform:'youtube'}])await rejects(f.store.saveAccount({...input,...change}),'invalid_linked_account');
  assert.equal((await f.store.public()).destinations.length,0);
});

test('Kick resolution requires the pinned provider, account and a validated RTMPS endpoint with no guessed upgrade',async t=>{
  const ref='c'.repeat(64);let reply={platform:'kick',accountRef:ref,serverUrl:'rtmps://ingest.provider.com/app',streamKey:'private-kick-key'};
  const f=await fixture(t,{accountResolver:async()=>reply}),id=(await f.store.saveAccount({name:'Kick',platform:'kick',accountRef:ref,requestId:'kick-resolve'})).destination.id,valid={...reply};
  for(const change of [{platform:'twitch'},{platform:undefined},{accountRef:'d'.repeat(64)},{streamKey:''},{streamKey:'bad\nkey'},{access_token:'private'},{publicLabel:'unrequested'}]){reply={...valid,...change};await rejects(f.store.private(id),'account_authorization_required');}
  for(const serverUrl of ['rtmp://ingest.provider.com/app','https://ingest.provider.com/app','rtmps://127.0.0.1/app','rtmps://private.local/app','rtmps://user:secret@ingest.provider.com/app','rtmps://ingest.provider.com/app?key=secret']){reply={...valid,serverUrl};await assert.rejects(f.store.private(id),error=>error.name==='DestinationError');}
  reply={...valid};assert.equal((await f.store.private(id)).serverUrl,valid.serverUrl);
});

test('a linked Kick ciphertext containing a cached endpoint is rejected instead of silently reusing credentials',async t=>{
  const f=await fixture(t),id=(await f.store.saveAccount({name:'Kick',platform:'kick',accountRef:'c'.repeat(64),requestId:'kick-cipher'})).destination.id;
  const value=JSON.parse(await fs.readFile(f.file,'utf8')),profile=value.profiles[0],secret=JSON.parse((await f.cipher.decryptStringAsync(Buffer.from(profile.encrypted,'base64'))).result);secret.serverUrl='rtmps://ingest.provider.com/app';profile.encrypted=(await f.cipher.encryptStringAsync(JSON.stringify(secret))).toString('base64');const malformed=JSON.stringify(value);await fs.writeFile(f.file,malformed);
  const reloaded=new DestinationStore({directory:f.directory,cipher:f.cipher,platform:'win32'});assert.equal((await reloaded.public()).destinations[0].status,'locked');await rejects(reloaded.private(id),'destination_credentials_unavailable');assert.equal(await fs.readFile(f.file,'utf8'),malformed);
});
const rejects = (promise, code) => assert.rejects(promise, error => error.code === code && error.message === code);

test('linked accounts persist a reference, resolve a fresh private key at Start, and never expose it publicly', async t => {
  const ref='a'.repeat(64); let calls=0;
  const accountResolver=async accountRef=>{calls++;return {accountRef,streamKey:'private-derived-'+calls};};
  const f=await fixture(t,{accountResolver}), input={requestId:'link-one',platform:'twitch',name:'Twitch account',accountRef:ref};
  await rejects(f.store.save(input),'invalid_destination_fields');
  const saved=await f.store.saveAccount(input);assert.equal(saved.destination.linkedAccount,true);
  assert.equal((await f.store.saveAccount(input)).replayed,true);
  const second=await f.store.saveAccount({...input,requestId:'link-two'});assert.equal(second.destination.id,saved.destination.id);
  assert.equal((await f.store.public()).destinations.length,1);assert.equal(calls,0);
  const reloaded=new DestinationStore({directory:f.directory,cipher:f.cipher,platform:'win32',accountResolver});
  assert.equal((await reloaded.getPrivateDestination(saved.destination.id)).streamKey,'private-derived-1');
  assert.equal((await reloaded.getPrivateDestination(saved.destination.id)).streamKey,'private-derived-2');
  const disk=await fs.readFile(f.file,'utf8'), visible=JSON.stringify(await reloaded.public());
  for(const value of [disk,visible])assert.equal(value.includes('private-derived'),false);
  await rejects(reloaded.save(payload({id:saved.destination.id,requestId:'edit-account'})),'account_destination_managed');
  await reloaded.remove(saved.destination.id);
  await rejects(reloaded.saveAccount(input),'destination_request_retired');
});

test('linked destination fails closed after disconnect, wrong account, invalid keys or missing native resolver',async t=>{
  let reply;const f=await fixture(t,{accountResolver:async()=>reply}), ref='b'.repeat(64);
  const saved=await f.store.saveAccount({requestId:'link',name:'Linked channel',platform:'twitch',accountRef:ref});
  for(reply of [null,{accountRef:'c'.repeat(64),streamKey:'wrong-account'},{accountRef:ref,streamKey:'bad key'},{accountRef:ref,streamKey:''}])await rejects(f.store.private(saved.destination.id),'account_authorization_required');
  const offline=new DestinationStore({directory:f.directory,cipher:f.cipher,platform:'win32'});
  await rejects(offline.private(saved.destination.id),'account_authorization_required');
  const ineligible=new DestinationStore({directory:f.directory,cipher:f.cipher,platform:'win32',accountResolver:async()=>{throw Error('streaming_not_available');}});
  await rejects(ineligible.private(saved.destination.id),'streaming_not_available');
  for(const change of [{streamKey:'manual'},{platform:'youtube'},{serverUrl:'rtmps://provider.com/live'},{accountRef:'bad'}])await rejects(f.store.saveAccount({requestId:'bad',name:'Bad',platform:'twitch',accountRef:ref,...change}),'invalid_linked_account');
});

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


test('origin-only Kick ingest is used without inventing a path and unavailable secure transport stays actionable',async t=>{
 const ref='a'.repeat(64);let unavailable=false;const f=await fixture(t,{accountResolver:async()=>{if(unavailable)throw Error('secure_ingest_unavailable');return {platform:'kick',accountRef:ref,serverUrl:'rtmps://ingest.provider.com:443',streamKey:'app/synthetic-private-key'};}});
 const saved=await f.store.saveAccount({name:'Kick origin only',platform:'kick',accountRef:ref,requestId:'origin-only'});const value=await f.store.private(saved.destination.id);assert.equal(value.serverUrl,'rtmps://ingest.provider.com');assert.equal(value.streamKey,'app/synthetic-private-key');unavailable=true;await rejects(f.store.private(saved.destination.id),'secure_ingest_unavailable');
});
