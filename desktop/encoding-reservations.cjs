'use strict';

const ROUTE = '/api/desktop/encoding-status';
const PURPOSES = new Set(['broadcast', 'recording', 'replay', 'rehearsal']);
const fail = code => Object.assign(Error(code), {code});

// The backend owns one process reservation. This broker owns its local reasons
// for keeping that reservation and never clears it while another reason remains.
function createEncodingReservations({request, identity, ownerPid} = {}) {
  if (typeof request !== 'function' || !Number.isSafeInteger(identity?.pid) || identity.pid < 1 ||
      typeof identity.server_session_id !== 'string' || !identity.server_session_id ||
      !Number.isSafeInteger(ownerPid) || ownerPid < 1) throw fail('invalid_encoding_reservations');
  const pinned = Object.freeze({pid: identity.pid, server_session_id: identity.server_session_id, owner_pid: ownerPid});
  const holds = new Map();
  let tail = Promise.resolve();
  const serialize = operation => {
    const work = tail.then(operation);
    tail = work.catch(() => {});
    return work;
  };
  function validate(body) {
    if (!body || typeof body !== 'object' || Array.isArray(body) ||
        Object.keys(body).some(key => !['pid', 'server_session_id', 'owner_pid', 'active', 'mode', 'rehearsal_generation'].includes(key)) ||
        Object.entries(pinned).some(([key, value]) => body[key] !== value) || typeof body.active !== 'boolean')
      throw fail('encoding_reservation_identity_mismatch');
    const mode = body.mode ?? 'broadcast', generation = body.rehearsal_generation;
    if (!['broadcast', 'rehearsal'].includes(mode) ||
        (mode === 'rehearsal' ? typeof generation !== 'string' || !/^[a-f0-9]{32}$/.test(generation) : generation !== undefined))
      throw fail('invalid_encoding_reservation');
    return {mode, ...(mode === 'rehearsal' ? {rehearsal_generation: generation} : {})};
  }
  const same = (a, b) => a.mode === b.mode && a.rehearsal_generation === b.rehearsal_generation;
  function confirm(result, expected) {
    const value = result?.native_encoding;
    if (result?.ok !== true || !value || typeof value !== 'object' || Array.isArray(value) ||
        value.active !== expected.active || value.owner_pid !== (expected.active ? pinned.owner_pid : null) ||
        (value.mode ?? 'broadcast') !== (expected.active ? expected.mode : 'broadcast') ||
        value.rehearsal_generation !== (expected.active ? expected.rehearsal_generation : undefined))
      throw fail('encoding_reservation_unconfirmed');
    return result;
  }
  async function update(purpose, body) {
    const scope = validate(body), own = holds.get(purpose);
    if (own && !same(own, scope)) throw fail('encoding_reservation_conflict');
    if (body.active) {
      if ([...holds.values()].some(hold => !same(hold, scope))) throw fail('encoding_reservation_conflict');
      // Even a lost claim response can mean the backend accepted ownership.
      const hold = {...scope, state: 'uncertain'};
      holds.set(purpose, hold);
      try {
        const payload = {...pinned, active: true, ...scope};
        const result = confirm(await request(ROUTE, payload), payload);
        hold.state = 'held';
        return result;
      } catch (error) { throw error; }
    }
    if (!own) return {ok: true, active: holds.size > 0};
    const remaining = [...holds.entries()].filter(([name]) => name !== purpose);
    own.state = 'uncertain';
    // Reassert aggregate ownership when another coordinator still holds it.
    // Remove this hold only after that update has actually been confirmed.
    const payload = {...pinned, active: remaining.length > 0, ...(remaining[0]?.[1] || scope)};
    delete payload.state;
    const result = confirm(await request(ROUTE, payload), payload);
    holds.delete(purpose);
    return result;
  }
  return {
    requestFor(purpose) {
      if (!PURPOSES.has(purpose)) throw fail('invalid_encoding_reservation_purpose');
      return (url, body) => {
        if (url !== ROUTE) return request(url, body);
        const snapshot = body && {...body};
        return serialize(() => update(purpose, snapshot));
      };
    },
    status() {
      return {active: holds.size > 0, holds: [...holds].map(([purpose, hold]) => ({purpose, ...hold}))};
    },
  };
}

module.exports = {createEncodingReservations};
