'use strict';

// Main-process only. Never expose private()/getPrivateDestination() over IPC.
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID, createHash } = require('node:crypto');
const { isIP } = require('node:net');

const PRESETS = Object.freeze([
  // Official secure template, checked 2026-11-18. This is not a reachability claim.
  // https://dev.twitch.tv/docs/video-broadcast/reference/ingest
  Object.freeze({ id: 'twitch', name: 'Twitch', serverUrl: 'rtmps://ingest.global-contribute.live-video.net/app', helpUrl: 'https://dev.twitch.tv/docs/video-broadcast/reference/ingest' }),
  Object.freeze({ id: 'youtube', name: 'YouTube', serverUrl: '', helpUrl: 'https://support.google.com/youtube/answer/10364924?hl=en' }),
  Object.freeze({ id: 'kick', name: 'Kick', serverUrl: '', helpUrl: 'https://help.kick.com/en/articles/7066931-how-to-stream-on-kick-com' }),
  ...[['rumble','Rumble'],['facebook','Facebook'],['tiktok','TikTok'],['x','X'],['instagram','Instagram']].map(([id,name])=>Object.freeze({id,name,serverUrl:'',helpUrl:''})),
  Object.freeze({ id: 'custom', name: 'Custom', serverUrl: '', helpUrl: '' }),
]);
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const REQUEST = /^[A-Za-z0-9_-]{1,80}$/;
const PLATFORM = new Set(PRESETS.map(item => item.id));
const FIELDS = new Set(['id', 'requestId', 'name', 'platform', 'serverUrl', 'streamKey', 'clearKey', 'allowInsecureRtmp']);
const MAX_PROFILES = 20, MAX_RECEIPTS = 256, MAX_FILE_BYTES = 1024 * 1024;

class DestinationError extends Error {
  constructor(code) { super(code); this.name = 'DestinationError'; this.code = code; }
}
const fail = code => { throw new DestinationError(code); };
const plain = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function validateServerUrl(value, { platform = 'custom', allowInsecureRtmp = false } = {}) {
  if (!PLATFORM.has(platform) || typeof allowInsecureRtmp !== 'boolean') fail('invalid_destination_platform');
  if (typeof value !== 'string' || !value || value.length > 2048 || /[\s\\\x00-\x1f\x7f]/.test(value)) fail('invalid_destination_url');
  let url;
  try { url = new URL(value); } catch (_) { fail('invalid_destination_url'); }
  const insecure = url.protocol === 'rtmp:';
  if (url.protocol !== 'rtmps:' && !(insecure && platform === 'custom' && allowInsecureRtmp === true)) fail('secure_destination_required');
  if (url.username || url.password || value.includes('?') || value.includes('#') || url.search || url.hash) fail('destination_url_contains_credentials');
  const hostname = url.hostname.toLowerCase().replace(/\.$/, '');
  // Reject literal/alternate-encoded IPs and non-public-looking names. This is
  // syntax validation, NOT DNS isolation: the encoder must recheck resolved IPs.
  let normalizedHost;
  try { normalizedHost = new URL('https://' + url.host).hostname; } catch (_) { fail('invalid_destination_host'); }
  if (isIP(normalizedHost.replace(/^\[|\]$/g, '')) || !/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*$/.test(hostname)
      || /(?:^|\.)(?:localhost|local|internal|intranet|lan|home|corp|test|invalid|example|onion)$/.test(hostname)
      || hostname.endsWith('.home.arpa') || hostname.endsWith('.arpa')) fail('nonpublic_destination_host');
  if (url.port && (!/^\d+$/.test(url.port) || Number(url.port) < 1 || Number(url.port) > 65535)) fail('invalid_destination_port');
  let decodedPath;
  try { decodedPath = decodeURIComponent(url.pathname); } catch (_) { fail('invalid_destination_url'); }
  if (/[\s\\\x00-\x1f\x7f?#]/.test(decodedPath) || /[{}]/.test(decodedPath)) fail('invalid_destination_url');
  url.hostname = hostname;
  if ((url.protocol === 'rtmps:' && url.port === '443') || (insecure && url.port === '1935')) url.port = '';
  url.pathname = url.pathname.replace(/\/+$/, '') || '/';
  return url.href.replace(/\/$/, '');
}

function normalizeInput(payload, account = false) {
  if (!plain(payload) || Object.keys(payload).some(key => !FIELDS.has(key) && !(account && key === 'accountRef'))) fail('invalid_destination_fields');
  if (account && (payload.platform !== 'twitch' || typeof payload.accountRef !== 'string' || !/^[a-f0-9]{64}$/.test(payload.accountRef) || payload.streamKey || payload.clearKey || payload.allowInsecureRtmp || payload.serverUrl)) fail('invalid_linked_account');
  if (payload.id !== undefined && (typeof payload.id !== 'string' || !UUID.test(payload.id))) fail('invalid_destination_id');
  if (typeof payload.requestId !== 'string' || !REQUEST.test(payload.requestId)) fail('destination_request_id_required');
  if (typeof payload.name !== 'string' || !payload.name.trim() || payload.name.trim().length > 80 || /[\x00-\x1f\x7f]/.test(payload.name)) fail('invalid_destination_name');
  if (!PLATFORM.has(payload.platform)) fail('invalid_destination_platform');
  for (const key of ['clearKey', 'allowInsecureRtmp']) if (payload[key] !== undefined && typeof payload[key] !== 'boolean') fail('invalid_destination_option');
  if (payload.streamKey !== undefined && (typeof payload.streamKey !== 'string' || payload.streamKey.length > 4096 || /[\s\x00-\x1f\x7f]/.test(payload.streamKey))) fail('invalid_destination_key');
  if (payload.clearKey && payload.streamKey) fail('conflicting_destination_key_action');
  if (payload.serverUrl !== undefined && typeof payload.serverUrl !== 'string') fail('invalid_destination_url');
  if (payload.allowInsecureRtmp && payload.platform !== 'custom') fail('secure_destination_required');
  return { id: payload.id || null, requestId: payload.requestId, name: payload.name.trim(), platform: payload.platform,
    serverUrl: payload.serverUrl || null, streamKey: payload.streamKey || null, clearKey: payload.clearKey === true,
    allowInsecureRtmp: payload.allowInsecureRtmp === true, ...(account ? { accountRef: payload.accountRef } : {}) };
}

class DestinationStore {
  #directory; #file; #cipher; #fs; #platform; #accountResolver; #state = null; #queue = Promise.resolve();
  constructor({ directory, cipher, fileSystem = fs, platform = process.platform, accountResolver } = {}) {
    if (typeof directory !== 'string' || !path.isAbsolute(directory)) fail('destination_directory_required');
    this.#directory = directory;
    this.#file = path.join(directory, 'destinations.json');
    this.#cipher = cipher;
    this.#fs = fileSystem;
    this.#platform = platform;
    this.#accountResolver = accountResolver;
  }
  #serial(action) {
    const result = this.#queue.then(action);
    this.#queue = result.catch(() => {});
    return result;
  }
  async #available() {
    try {
      return this.#platform === 'win32' && typeof this.#cipher?.encryptStringAsync === 'function'
        && typeof this.#cipher?.decryptStringAsync === 'function'
        && await this.#cipher?.isAsyncEncryptionAvailable() === true;
    } catch (_) { return false; }
  }
  async #load() {
    if (this.#state) return;
    let raw;
    try {
      const stat = await this.#fs.stat(this.#file);
      if (!stat.isFile() || stat.size > MAX_FILE_BYTES) fail('destination_storage_invalid');
      raw = await this.#fs.readFile(this.#file, 'utf8');
    } catch (error) {
      if (error.code === 'ENOENT') { this.#state = { version: 1, profiles: [], receipts: [] }; return; }
      if (error instanceof DestinationError) throw error;
      fail('destination_storage_unavailable');
    }
    let value;
    try { value = JSON.parse(raw); } catch (_) { fail('destination_storage_invalid'); }
    if (!plain(value) || value.version !== 1 || !Array.isArray(value.profiles) || value.profiles.length > MAX_PROFILES
        || !Array.isArray(value.receipts) || value.receipts.length > MAX_RECEIPTS) fail('destination_storage_invalid');
    const ids = new Set(), requests = new Set();
    for (const p of value.profiles) {
      if (!plain(p) || !UUID.test(p.id) || ids.has(p.id) || !PLATFORM.has(p.platform)
          || typeof p.name !== 'string' || !p.name.trim() || p.name.length > 80 || /[\x00-\x1f\x7f]/.test(p.name)
          || typeof p.allowInsecureRtmp !== 'boolean' || (p.allowInsecureRtmp && p.platform !== 'custom')
          || !Number.isFinite(p.updatedAt) || typeof p.encrypted !== 'string' || p.encrypted.length > 32768
          || !/^[A-Za-z0-9+/]+={0,2}$/.test(p.encrypted)) fail('destination_storage_invalid');
      ids.add(p.id);
    }
    for (const r of value.receipts) {
      if (!plain(r) || !REQUEST.test(r.requestId) || requests.has(r.requestId) || !UUID.test(r.id) || !/^[a-f0-9]{64}$/.test(r.fingerprint)) fail('destination_storage_invalid');
      requests.add(r.requestId);
    }
    this.#state = value;
  }
  async #decode(profile) {
    let decoded;
    try {
      const result = await this.#cipher.decryptStringAsync(Buffer.from(profile.encrypted, 'base64'));
      // Electron async safeStorage returns {result, shouldReEncrypt}.
      if (!plain(result) || typeof result.result !== 'string') fail('destination_credentials_unavailable');
      decoded = JSON.parse(result.result);
      if (!plain(decoded) || decoded.id !== profile.id || decoded.platform !== profile.platform
          || typeof decoded.streamKey !== 'string' || decoded.streamKey.length > 4096 || /[\s\x00-\x1f\x7f]/.test(decoded.streamKey)
          || typeof decoded.allowInsecureRtmp !== 'boolean' || decoded.allowInsecureRtmp !== profile.allowInsecureRtmp) fail('destination_credentials_unavailable');
      decoded.serverUrl = validateServerUrl(decoded.serverUrl, profile);
      if (decoded.accountRef !== undefined && (decoded.platform !== 'twitch' || !/^[a-f0-9]{64}$/.test(decoded.accountRef) || decoded.streamKey)) fail('destination_credentials_unavailable');
      return decoded;
    } catch (_) { fail('destination_credentials_unavailable'); }
  }
  async #publicProfile(profile, available) {
    let keyConfigured = false, serverConfigured = false, locked = !available, linkedAccount = false;
    if (available) {
      try { const secret = await this.#decode(profile); linkedAccount = Boolean(secret.accountRef); keyConfigured = Boolean(secret.streamKey) || linkedAccount; serverConfigured = Boolean(secret.serverUrl); }
      catch (_) { locked = true; }
    }
    return { id: profile.id, name: profile.name, platform: profile.platform, updatedAt: profile.updatedAt,
      insecureTransport: profile.allowInsecureRtmp, keyConfigured, serverConfigured,
      configured: !locked && keyConfigured && serverConfigured, status: locked ? 'locked' : keyConfigured ? 'configured' : 'needs_key',
      connected: false, verified: false, platformLive: false, networkVerified: false, ...(linkedAccount ? { linkedAccount: true } : {}) };
  }
  public() {
    return this.#serial(async () => {
      await this.#load();
      const secureStorageAvailable = await this.#available();
      const destinations = await Promise.all(this.#state.profiles.map(p => this.#publicProfile(p, secureStorageAvailable)));
      return { destinations, secureStorageAvailable, presets: PRESETS.map(p => ({ ...p })) };
    });
  }
  async #persist(next) {
    const temporary = path.join(this.#directory, '.destinations-' + randomUUID() + '.tmp');
    let handle;
    try {
      await this.#fs.mkdir(this.#directory, { recursive: true, mode: 0o700 });
      handle = await this.#fs.open(temporary, 'wx', 0o600);
      await handle.writeFile(JSON.stringify(next), 'utf8');
      await handle.sync();
      await handle.close(); handle = null;
      await this.#fs.rename(temporary, this.#file);
    } catch (_) {
      try { await handle?.close(); } catch (_) {}
      try { await this.#fs.unlink(temporary); } catch (_) {}
      fail('destination_storage_unavailable');
    }
    this.#state = next;
  }
  save(payload) {
    return this.#save(payload, false);
  }
  // Main-owned account coordinator only. Renderer destination-save never accepts accountRef.
  saveAccount(payload) {
    return this.#save(payload, true);
  }
  #save(payload, account) {
    // Snapshot caller input before entering the queue; no caller-owned object is retained.
    let input;
    try { input = normalizeInput(payload, account); } catch (error) { return Promise.reject(error); }
    return this.#serial(async () => {
      await this.#load();
      if (!await this.#available()) fail('secure_storage_unavailable');
      const fingerprint = createHash('sha256').update(JSON.stringify(input)).digest('hex');
      const receipt = this.#state.receipts.find(r => r.requestId === input.requestId);
      if (receipt) {
        if (receipt.fingerprint !== fingerprint) fail('destination_request_conflict');
        const profile = this.#state.profiles.find(p => p.id === receipt.id);
        if (!profile) fail('destination_request_retired');
        return { saved: true, replayed: true, destination: await this.#publicProfile(profile, true) };
      }
      let previous = input.id ? this.#state.profiles.find(p => p.id === input.id) : null;
      if (account && !input.id) {
        for (const candidate of this.#state.profiles) {
          if (candidate.platform === 'twitch' && (await this.#decode(candidate)).accountRef === input.accountRef) { previous = candidate; break; }
        }
      }
      if (input.id && !previous) fail('destination_not_found');
      if (!previous && this.#state.profiles.length >= MAX_PROFILES) fail('destination_library_full');
      const oldSecret = previous ? await this.#decode(previous) : null;
      if (oldSecret?.accountRef && !account || account && oldSecret && oldSecret.accountRef !== input.accountRef) fail('account_destination_managed');
      const server = input.serverUrl || (previous?.platform === input.platform ? oldSecret.serverUrl : PRESETS.find(p => p.id === input.platform).serverUrl);
      const serverUrl = validateServerUrl(server, input);
      if (oldSecret?.streamKey && (oldSecret.serverUrl !== serverUrl || previous.platform !== input.platform)
          && !input.streamKey && !input.clearKey) fail('destination_key_replacement_required');
      const streamKey = input.clearKey ? '' : input.streamKey || oldSecret?.streamKey || '';
      const id = previous?.id || randomUUID();
      const secret = { id, platform: input.platform, serverUrl, streamKey, allowInsecureRtmp: input.allowInsecureRtmp, ...(account ? { accountRef: input.accountRef } : {}) };
      let encrypted;
      try {
        const bytes = await this.#cipher.encryptStringAsync(JSON.stringify(secret));
        if (!Buffer.isBuffer(bytes) || !bytes.length || bytes.length > 24576) fail('destination_encryption_failed');
        encrypted = bytes.toString('base64');
      } catch (_) { fail('destination_encryption_failed'); }
      const profile = { id, name: input.name, platform: input.platform, allowInsecureRtmp: input.allowInsecureRtmp, encrypted, updatedAt: Date.now() };
      const profiles = previous ? this.#state.profiles.map(p => p.id === id ? profile : p) : [...this.#state.profiles, profile];
      const receipts = [...this.#state.receipts, { requestId: input.requestId, id, fingerprint }].slice(-MAX_RECEIPTS);
      await this.#persist({ version: 1, profiles, receipts });
      return { saved: true, replayed: false, destination: await this.#publicProfile(profile, true) };
    });
  }
  remove(id) {
    return this.#serial(async () => {
      if (typeof id !== 'string' || !UUID.test(id)) fail('invalid_destination_id');
      await this.#load();
      const found = this.#state.profiles.some(p => p.id === id);
      if (found) await this.#persist({ ...this.#state, profiles: this.#state.profiles.filter(p => p.id !== id) });
      return { removed: true, alreadyAbsent: !found, id };
    });
  }
  getPrivateDestination(id) {
    return this.#serial(async () => {
      if (typeof id !== 'string' || !UUID.test(id)) fail('invalid_destination_id');
      await this.#load();
      if (!await this.#available()) fail('secure_storage_unavailable');
      const profile = this.#state.profiles.find(p => p.id === id);
      if (!profile) fail('destination_not_found');
      const secret = await this.#decode(profile);
      if (secret.accountRef) {
        if (typeof this.#accountResolver !== 'function') fail('account_authorization_required');
        let resolved;
        try { resolved = await this.#accountResolver(secret.accountRef); } catch (error) { fail(error?.message === 'streaming_not_available' ? 'streaming_not_available' : 'account_authorization_required'); }
        if (!plain(resolved) || resolved.accountRef !== secret.accountRef || typeof resolved.streamKey !== 'string' || !resolved.streamKey || resolved.streamKey.length > 4096 || /[\s\x00-\x1f\x7f]/.test(resolved.streamKey)) fail('account_authorization_required');
        secret.streamKey = resolved.streamKey;
      }
      if (!secret.streamKey) fail('destination_key_required');
      // Main encoder only: never log, return through IPC, or put in command previews.
      return { ...secret, name: profile.name, networkVerified: false };
    });
  }
  private(id) { return this.getPrivateDestination(id); }
}

module.exports = { DestinationStore, DestinationError, PRESETS, validateServerUrl };
