'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Session = require('../static/facility_layout_session.js');
const spatial = require('./fixtures/facility_layout/spatial/p6-browser-advisory.json');
const clone = value => JSON.parse(JSON.stringify(value));
const A = 'a'.repeat(64);
const B = 'b'.repeat(64);
const imagePath = '/generated/facility-wall-art/' + A + '.png';
const operations = [
    { op: 'upsert_floor_surface', surface: { surfaceId: 'fs-a', label: 'Floor',
        boundary: [{ x: 1, z: 1 }, { x: 3, z: 1 }, { x: 3, z: 3 }],
        elevation: 0, material: 'rubber', color: '#45484b', roughness: 0.8 } },
    { op: 'delete_floor_surface', surfaceId: 'fs-a' },
    { op: 'upsert_interior_wall', wall: { wallId: 'iw-a', label: 'Wall',
        start: { x: 5, z: 5 }, end: { x: 5, z: 15 }, heightMeters: 3,
        thicknessMeters: 0.2, baseElevation: 0, color: '#45484b', openings: [] } },
    { op: 'delete_interior_wall', wallId: 'iw-a' },
    { op: 'upsert_decal', decal: { artworkId: 'decal-a', label: 'Decal', imagePath,
        uv: [0, 0, 1, 1], region: [0.1, 0.1, 0.2, 0.9], coverage: 1,
        target: { edge: 0, side: 'interior' } } },
    { op: 'delete_decal', artworkId: 'decal-a' },
    { op: 'edit_perimeter_walls', patch: { exteriorFinish: { color: '#45484b' } } },
    { op: 'upsert_wall_artwork', collection: 'artworks', artwork: { artworkId: 'legacy-a',
        imagePath, edge: 1, startMeters: 1, widthMeters: 2, bottomMeters: 0, heightMeters: 2 } },
    { op: 'delete_wall_artwork', collection: 'fittedArtworks', artworkId: 'legacy-b' },
];

function candidateSession() {
    return Session.createSession({
        async previewOperations() { throw new Error('Candidate installation must not preview operations'); },
        async applyOperations() { throw new Error('Candidate installation must not save operations'); },
    });
}

function exactFixture(operation) {
    const before = { layoutId: 'fl-a', association: { siteId: 'site-a' },
        placements: [], zones: [], routes: [], extensions: { authoringTest: 'before' } };
    const after = clone(before);
    after.extensions.authoringTest = operation.op;
    const binding = { target: { domain: 'facility-layout', scopeId: 'fls:' + A, resourceId: 'fl-a' },
        baseRevision: A, diffHash: 'd'.repeat(64), dependencyFingerprint: 'e'.repeat(64) };
    const reference = { siteId: 'site-a', layoutId: 'fl-a', revision: A, proposalId: 'flp-targeted' };
    const preview = { proposalId: reference.proposalId, previewPure: true, action: 'layout.apply',
        binding: clone(binding), createdAt: 1800000000, expiresAt: 1800003600,
        alternative: { alternativeId: 'exact-targeted', strategy: 'exact-operations-v1',
            operations: [clone(operation)], transactionBinding: clone(binding),
            ghostPreview: { layout: after }, metrics: { operationCount: 1 } } };
    const calls = [];
    const session = Session.createSession({ siteId: reference.siteId, layoutId: reference.layoutId,
        async getLayoutProposalPreview(payload) { calls.push(['preview', clone(payload)]); return clone(preview); },
        async approveLayoutProposal(payload) { calls.push(['approve', clone(payload)]); return { approvalToken: 'user-approved' }; },
        async applyLayoutProposal(payload) {
            calls.push(['apply', clone(payload)]);
            return { receiptId: 'flr-targeted', revision: B, layout: clone(after) };
        },
        async previewOperations() { throw new Error('Exact proposals must not enter the manual preview path'); },
        async applyOperations() { throw new Error('Exact proposals must not enter the manual save path'); },
    });
    session.load({ revision: A, layout: before });
    return { session, calls, before, after, reference, preview, binding };
}

for (const operation of operations) {
    test(operation.op + ' is recognized by the ordinary candidate normalizer', () => {
        const session = candidateSession();
        session.load({ revision: 'rev-1', layout: clone(spatial.layout) });
        const receipt = clone(spatial.candidateReceipt);
        receipt.candidates.forEach(candidate => { candidate.operations.push(clone(operation)); });
        session.installPlacementAlternatives(receipt);
        const state = session.getState();
        assert.deepEqual(state.placementAlternatives.candidates[0].operations.at(-1), operation);
        assert.deepEqual(state.layout, spatial.layout);
        assert.equal(state.dirty, false);
        assert.deepEqual(state.operations, []);
    });

    test(operation.op + ' stays server-authoritative until explicit approval', async () => {
        const f = exactFixture(operation);
        await f.session.fetchAndInstallOperationProposal(f.reference);
        let state = f.session.getState();
        assert.deepEqual(f.calls, [['preview', { proposalId: f.reference.proposalId }]]);
        assert.deepEqual(state.layoutProposal.alternatives[0].operations, [operation]);
        assert.deepEqual(state.layoutProposal.alternatives[0].ghostPreview.layout, f.after);
        assert.deepEqual(state.layout, f.before);
        assert.equal(state.dirty, false);
        assert.deepEqual(state.operations, []);
        await f.session.approveAndApplyLayoutProposal();
        state = f.session.getState();
        assert.deepEqual(f.calls.map(call => call[0]), ['preview', 'preview', 'approve', 'apply']);
        assert.deepEqual(f.calls[2][1].binding, f.binding);
        assert.equal(f.calls[2][1].explicitApproval, true);
        assert.equal(f.calls[3][1].approvalToken, 'user-approved');
        assert.equal(f.calls[3][1].idempotencyKey, f.calls[2][1].idempotencyKey);
        assert.equal(Object.hasOwn(f.calls[2][1], 'operations'), false);
        assert.equal(Object.hasOwn(f.calls[3][1], 'operations'), false);
        assert.deepEqual(state.layout, f.after);
        assert.equal(state.baseRevision, B);
        assert.equal(state.lastApprovedOperationCommit.receiptId, 'flr-targeted');
        assert.equal(state.lastApprovedOperationCommit.revision, B);
        assert.equal(state.dirty, false);
    });
}

test('ordinary candidate recognition still rejects unknown operations', () => {
    const session = candidateSession();
    session.load({ revision: 'rev-1', layout: clone(spatial.layout) });
    const receipt = clone(spatial.candidateReceipt);
    receipt.candidates[0].operations = [{ op: 'execute_command', command: 'untrusted' }];
    assert.throws(() => session.installPlacementAlternatives(receipt), /ordinary operation/);
    assert.deepEqual(session.getState().layout, spatial.layout);
    assert.equal(session.getState().dirty, false);
});

test('targeted previews still reject changed binding and raw model operations', async () => {
    const f = exactFixture(operations[6]);
    await assert.rejects(f.session.fetchAndInstallOperationProposal({ ...f.reference, operations }), /only a server proposal reference/);
    assert.equal(f.calls.length, 0);
    await f.session.fetchAndInstallOperationProposal(f.reference);
    f.preview.binding.diffHash = 'f'.repeat(64);
    f.preview.alternative.transactionBinding.diffHash = 'f'.repeat(64);
    await assert.rejects(f.session.approveAndApplyLayoutProposal(), { code: 'layout_proposal_stale' });
    assert.deepEqual(f.calls.map(call => call[0]), ['preview', 'preview']);
    assert.deepEqual(f.session.getState().layout, f.before);
    assert.equal(f.session.getState().dirty, false);
});
