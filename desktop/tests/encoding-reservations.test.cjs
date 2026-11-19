'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createEncodingReservations} = require('../encoding-reservations.cjs');
const route = '/api/desktop/encoding-status';
const identity = {pid: 21, server_session_id: 'synthetic-backend'};
const body = (active, extra = {}) => ({...identity, owner_pid: 34, active, ...extra});
const ack = value => ({ok: true, native_encoding: {active: value.active, owner_pid: value.active ? value.owner_pid : null,
  ...(value.active && value.mode === 'rehearsal' ? {mode: 'rehearsal', rehearsal_generation: value.rehearsal_generation} : {})}});
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };

test('broadcast, recording and replay keep independent holds until the final output stops',async()=>{
 const calls=[],broker=createEncodingReservations({identity,ownerPid:34,request:async(_url,value)=>{calls.push(value);return ack(value);}}),sinks=['broadcast','recording','replay'].map(p=>broker.requestFor(p));
 await Promise.all(sinks.map(request=>request(route,body(true))));assert.equal(broker.status().holds.length,3);
 await sinks[0](route,body(false));await sinks[2](route,body(false));assert.equal(calls.at(-1).active,true);assert.deepEqual(broker.status().holds.map(h=>h.purpose),['recording']);await sinks[1](route,body(false));assert.equal(calls.at(-1).active,false);
});

test('broadcast and recording release only their own hold, with final backend release last', async () => {
  const calls = [], broker = createEncodingReservations({identity, ownerPid: 34, request: async (url, value) => { calls.push({url, value}); return ack(value); }});
  const broadcast = broker.requestFor('broadcast'), recording = broker.requestFor('recording');
  await broadcast(route, body(true)); await recording(route, body(true));
  await broadcast(route, body(false));
  assert.equal(calls.at(-1).value.active, true);
  assert.deepEqual(broker.status().holds.map(item => item.purpose), ['recording']);
  await recording(route, body(false));
  assert.equal(calls.at(-1).value.active, false);
  assert.equal(broker.status().active, false);
  assert.ok(calls.every(call => call.value.owner_pid === 34 && call.value.pid === 21 && !Object.hasOwn(call.value, 'state')));
});

test('parallel claims and releases serialize, while unrelated requests pass through', async () => {
  const pending = deferred(), calls = [];
  const broker = createEncodingReservations({identity, ownerPid: 34, request: async (url, value) => { calls.push({url, value}); if (calls.length === 1) await pending.promise; return ack(value); }});
  const broadcast = broker.requestFor('broadcast'), recording = broker.requestFor('recording');
  const first = broadcast(route, body(true)), second = recording(route, body(true)), third = broadcast(route, body(false));
  await Promise.resolve(); assert.equal(calls.length, 1);
  await recording('/unrelated', {sample: true}); assert.equal(calls.length, 2);
  pending.resolve(); await Promise.all([first, second, third]);
  assert.deepEqual(calls.filter(call => call.url === route).map(call => call.value.active), [true, true, true]);
  assert.deepEqual(broker.status().holds.map(item => item.purpose), ['recording']);
});

test('uncertain claim and release remain owned until a confirmed retry', async () => {
  let fail = true;
  const broker = createEncodingReservations({identity, ownerPid: 34, request: async (_url, value) => { if (fail) throw Error('synthetic lost reply'); return ack(value); }});
  const request = broker.requestFor('recording');
  await assert.rejects(request(route, body(true)));
  assert.equal(broker.status().holds[0].state, 'uncertain');
  await assert.rejects(request(route, body(false)));
  assert.equal(broker.status().active, true);
  fail = false; await request(route, body(false)); assert.equal(broker.status().active, false);
});

test('different modes, rehearsal generations and altered identities never reach backend', async () => {
  const calls = [], broker = createEncodingReservations({identity, ownerPid: 34, request: async (...args) => { calls.push(args); return ack(args[1]); }});
  const rehearsal = broker.requestFor('rehearsal'), recording = broker.requestFor('recording');
  const scope = {mode: 'rehearsal', rehearsal_generation: 'a'.repeat(32)};
  await rehearsal(route, body(true, scope));
  await assert.rejects(recording(route, body(true)), /encoding_reservation_conflict/);
  await assert.rejects(rehearsal(route, body(true, {...scope, rehearsal_generation: 'b'.repeat(32)})), /encoding_reservation_conflict/);
  await assert.rejects(recording(route, {...body(true), owner_pid: 35}), /identity_mismatch/);
  await assert.rejects(recording(route, {...body(true), pid: 99}), /identity_mismatch/);
  await assert.rejects(recording(route, body(true, {mode: 'broadcast', rehearsal_generation: 'a'.repeat(32)})), /invalid_encoding_reservation/);
  assert.equal(calls.length, 1);
  await rehearsal(route, body(false, scope)); assert.equal(calls.at(-1)[1].active, false);
});

test('failed aggregate refresh retains stopping purpose and cannot clear another consumer', async () => {
  const calls = []; let fail = false;
  const broker = createEncodingReservations({identity, ownerPid: 34, request: async (url, value) => { calls.push(value); if (fail) return {ok: false}; return ack(value); }});
  const broadcast = broker.requestFor('broadcast'), recording = broker.requestFor('recording');
  await broadcast(route, body(true)); await recording(route, body(true)); fail = true;
  await assert.rejects(recording(route, body(false)), /unconfirmed/);
  assert.equal(broker.status().holds.length, 2); assert.equal(calls.at(-1).active, true);
  fail = false; await recording(route, body(false)); assert.equal(broker.status().holds.length, 1);
  await recording(route, body(false)); assert.equal(calls.at(-1).active, true);
  await broadcast(route, body(false)); assert.equal(calls.at(-1).active, false);
});

test('queued requests and constructor identity remain pinned against caller mutation', async () => {
  const blocked = deferred(), mutableIdentity = {...identity}, calls = [];
  const broker = createEncodingReservations({identity: mutableIdentity, ownerPid: 34, request: async (_url, value) => {
    calls.push(value); if (calls.length === 1) await blocked.promise; return ack(value);
  }});
  mutableIdentity.pid = 999;
  const first = broker.requestFor('broadcast')(route, body(true)), value = body(true);
  const second = broker.requestFor('recording')(route, value);
  value.active = false; value.pid = 888;
  blocked.resolve(); await Promise.all([first, second]);
  assert.equal(calls.length, 2); assert.equal(calls[1].pid, identity.pid); assert.equal(calls[1].active, true);
});

test('missing, foreign-owner and stale active acknowledgements retain uncertain claims and releases', async () => {
  for (const invalid of [undefined, {}, {ok: true}, {ok: true, native_encoding: {active: true, owner_pid: 999}},
    {ok: true, native_encoding: {active: false, owner_pid: null}},
    {ok: true, native_encoding: {active: true, owner_pid: 34, mode: 'rehearsal', rehearsal_generation: 'a'.repeat(32)}}]) {
    let malformed = true;
    const broker = createEncodingReservations({identity, ownerPid: 34, request: async (_url, value) => malformed ? invalid : ack(value)});
    const recording = broker.requestFor('recording');
    await assert.rejects(recording(route, body(true)), /unconfirmed/);
    assert.equal(broker.status().holds[0].state, 'uncertain');
    malformed = false; await recording(route, body(false)); assert.equal(broker.status().active, false);
  }
  for (const invalid of [undefined, {}, {ok: true}, {ok: true, native_encoding: {active: true, owner_pid: 34}},
    {ok: true, native_encoding: {active: false, owner_pid: 34}},
    {ok: true, native_encoding: {active: false, owner_pid: null, mode: 'rehearsal', rehearsal_generation: 'a'.repeat(32)}}]) {
    let malformed = false;
    const broker = createEncodingReservations({identity, ownerPid: 34, request: async (_url, value) => malformed ? invalid : ack(value)});
    const recording = broker.requestFor('recording');
    await recording(route, body(true)); malformed = true;
    await assert.rejects(recording(route, body(false)), /unconfirmed/); assert.equal(broker.status().active, true);
    malformed = false; await recording(route, body(false)); assert.equal(broker.status().active, false);
  }
});

test('rehearsal acknowledgment must match its pinned generation', async () => {
  const scope = {mode: 'rehearsal', rehearsal_generation: 'a'.repeat(32)};
  const broker = createEncodingReservations({identity, ownerPid: 34, request: async () => ack(body(true, {...scope, rehearsal_generation: 'b'.repeat(32)}))});
  await assert.rejects(broker.requestFor('rehearsal')(route, body(true, scope)), /unconfirmed/);
  assert.equal(broker.status().holds[0].state, 'uncertain');
});
