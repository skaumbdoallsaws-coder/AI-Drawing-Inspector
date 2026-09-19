'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createRecoveryStore } = require('../src/recovery-store.cjs');

const identity = { backendId: 'backend-a', storeId: 'store-a', principalId: 'principal-a' };
function record() {
  return { schemaVersion: 1, identity: { ...identity },
    document: { tenantId: 'tenant-a', siteId: 'site-a', documentId: 'fl-main', baseRevision: 'base-a', draftRevision: 'draft-a' },
    handle: { requestId: 'request-a', transactionId: 'transaction-a', phase: 'acknowledgment_pending', state: 'unknown' },
    payload: { expectedTransactionRevision: 'transaction-revision-a', history: ['move'], selection: ['machine-a'] } };
}
async function fixture(t, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'inspectorpro-recovery-test-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  return { directory, store: await createRecoveryStore({ directory, identity, ...options }) };
}

test('durability acknowledgment and identity-bound record survive store recreation', async t => {
  const f = await fixture(t); const input = record();
  const ack = await f.store.write({ key: 'undo_a', record: input });
  assert.equal(ack.acknowledged, true);
  assert.match(ack.durability, /sync-atomic-replace$/);
  const reloaded = await createRecoveryStore({ directory: f.directory, identity });
  assert.deepEqual((await reloaded.read('undo_a')).record, input);
  assert.equal((await reloaded.list())[0].handle.transactionId, 'transaction-a');
});

test('pending or unknown handle cannot be cleared or overwritten without its checkpoint', async t => {
  const { store } = await fixture(t);
  const ack = await store.write({ key: 'undo_a', record: record() });
  await assert.rejects(store.clear({ key: 'undo_a', expectedCheckpointId: ack.checkpointId }), { code: 'recovery_unresolved' });
  await assert.rejects(store.write({ key: 'undo_a', record: record() }), { code: 'recovery_checkpoint_conflict' });
  assert.equal((await store.read('undo_a')).checkpointId, ack.checkpointId);
});

test('reconciled handle clears only with its latest checkpoint', async t => {
  const { store } = await fixture(t);
  const ack = await store.write({ key: 'undo_a', record: record() });
  const reconciled = record(); reconciled.handle.state = 'reconciled';
  const next = await store.write({ key: 'undo_a', record: reconciled, expectedCheckpointId: ack.checkpointId });
  await assert.rejects(store.clear({ key: 'undo_a', expectedCheckpointId: ack.checkpointId }), { code: 'recovery_checkpoint_conflict' });
  assert.equal((await store.clear({ key: 'undo_a', expectedCheckpointId: next.checkpointId })).cleared, true);
  assert.equal(await store.read('undo_a'), null);
});

test('new operation or changed revision cannot replace an existing transaction', async t => {
  const { store } = await fixture(t);
  const ack = await store.write({ key: 'undo_a', record: record() });
  for (const change of [value => { value.handle.transactionId = 'other'; }, value => { value.document.draftRevision = 'newer'; }]) {
    const next = record(); change(next);
    await assert.rejects(store.write({ key: 'undo_a', record: next, expectedCheckpointId: ack.checkpointId }), { code: 'recovery_binding_conflict' });
  }
  assert.equal((await store.read('undo_a')).checkpointId, ack.checkpointId);
});

test('two stores with fl-main cannot share recovery identity', async t => {
  const f = await fixture(t);
  await assert.rejects(createRecoveryStore({ directory: f.directory, identity: { ...identity, storeId: 'store-b' } }), { code: 'recovery_identity_mismatch' });
  const input = record(); input.identity.principalId = 'other-principal';
  await assert.rejects(async () => f.store.write({ key: 'undo_a', record: input }), { code: 'recovery_identity_mismatch' });
});

test('renderer paths, invalid schema, and cyclic or oversized data are rejected', async t => {
  const { store } = await fixture(t, { maxRecordBytes: 1600 });
  for (const key of ['../escape', 'C:\\file', 'a/b', '', 'a'.repeat(129)]) {
    await assert.rejects(async () => store.write({ key, record: record() }), { code: 'recovery_key_invalid' });
  }
  const cyclic = record(); cyclic.payload.self = cyclic;
  await assert.rejects(async () => store.write({ key: 'undo_a', record: cyclic }), { code: 'recovery_schema_invalid' });
  const missing = record(); delete missing.document.baseRevision;
  await assert.rejects(async () => store.write({ key: 'undo_a', record: missing }), { code: 'recovery_schema_invalid' });
  const big = record(); big.payload.large = 'x'.repeat(2000);
  await assert.rejects(store.write({ key: 'undo_a', record: big }), { code: 'recovery_record_too_large' });
  assert.deepEqual(await store.list(), []);
});

test('quota failure retains every unresolved record', async t => {
  const { store } = await fixture(t, { maxRecords: 1 });
  const ack = await store.write({ key: 'undo_a', record: record() });
  await assert.rejects(store.write({ key: 'undo_b', record: record() }), { code: 'recovery_store_full' });
  assert.equal((await store.read('undo_a')).checkpointId, ack.checkpointId);
});

test('concurrent replacement uses compare-and-swap, not last-writer-wins', async t => {
  const { store } = await fixture(t);
  const ack = await store.write({ key: 'undo_a', record: record() });
  const attempts = await Promise.allSettled([1, 2].map(() => store.write({ key: 'undo_a', record: record(), expectedCheckpointId: ack.checkpointId })));
  assert.equal(attempts.filter(value => value.status === 'fulfilled').length, 1);
  assert.equal(attempts.find(value => value.status === 'rejected').reason.code, 'recovery_checkpoint_conflict');
});

test('failed atomic replacement gives no acknowledgment and retains previous handle', async t => {
  const f = await fixture(t);
  const ack = await f.store.write({ key: 'undo_a', record: record() });
  t.mock.method(fs, 'rename', async () => { throw Object.assign(new Error('Injected rename failure'), { code: 'EACCES' }); });
  await assert.rejects(f.store.write({ key: 'undo_a', record: record(), expectedCheckpointId: ack.checkpointId }), { code: 'EACCES' });
  assert.equal((await f.store.read('undo_a')).checkpointId, ack.checkpointId);
  assert.equal((await fs.readdir(f.directory)).some(name => name.endsWith('.tmp')), false);
});

test('caller mutations after enqueue do not alter the checkpoint', async t => {
  const { store } = await fixture(t);
  const input = record();
  const writing = store.write({ key: 'undo_a', record: input });
  input.payload.selection.push('other-machine');
  await writing;
  assert.deepEqual((await store.read('undo_a')).record.payload.selection, ['machine-a']);
});

test('file sync failure gives no acknowledgment and leaves existing durable record intact', async t => {
  const f = await fixture(t);
  const ack = await f.store.write({ key: 'undo_a', record: record() });
  const realOpen = fs.open;
  t.mock.method(fs, 'open', async (...args) => {
    const handle = await realOpen(...args);
    if (String(args[0]).endsWith('.tmp')) {
      handle.sync = async () => { throw Object.assign(new Error('Injected disk sync failure'), { code: 'EIO' }); };
    }
    return handle;
  });
  await assert.rejects(f.store.write({ key: 'undo_a', record: record(), expectedCheckpointId: ack.checkpointId }), { code: 'EIO' });
  assert.equal((await f.store.read('undo_a')).checkpointId, ack.checkpointId);
});

test('a pre-request record can acquire its backend transaction binding without changing request identity', async t => {
  const { store } = await fixture(t);
  const requestOnly = record(); delete requestOnly.handle.transactionId;
  requestOnly.handle.phase = 'preparing'; requestOnly.handle.state = 'pending';
  const ack = await store.write({ key: 'undo_a', record: requestOnly });
  await store.write({ key: 'undo_a', record: record(), expectedCheckpointId: ack.checkpointId });
  assert.equal((await store.read('undo_a')).record.handle.transactionId, 'transaction-a');
});

test('unacknowledged crash temporary files consume quota and are not treated as receipts', async t => {
  const f = await fixture(t, { maxTotalBytes: 2048 });
  const orphan = '.00000000-0000-0000-0000-000000000000.tmp';
  await fs.writeFile(path.join(f.directory, orphan), 'x'.repeat(1900));
  await assert.rejects(f.store.write({ key: 'undo_a', record: record() }), { code: 'recovery_store_full' });
  assert.deepEqual(await f.store.list(), []);
  assert.equal((await fs.stat(path.join(f.directory, orphan))).size, 1900);
});
