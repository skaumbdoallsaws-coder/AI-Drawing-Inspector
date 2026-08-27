'use strict';

const assert = require('assert');
const Transport = require('../static/facility_layout_transport.js');

const tests = [];

function test(name, fn) {
    tests.push({ name, fn });
}

function response(status, body) {
    return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => JSON.parse(JSON.stringify(body)),
    };
}

function binding(revision) {
    return {
        target: {
            domain: 'facility-layout',
            scopeId: 'site-a',
            resourceId: 'fl-a',
        },
        baseRevision: revision,
        diffHash: 'd'.repeat(64),
        dependencyFingerprint: 'e'.repeat(64),
    };
}

test('constructs encoded revision-bound preview and apply requests', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { ok: true });
        },
    });
    await transport.previewOperations({
        baseRevision: 'a'.repeat(64),
        operations: [{ op: 'delete_placement', placementId: 'pl-one' }],
    });
    await transport.applyOperations({
        baseRevision: 'b'.repeat(64),
        operations: [{ op: 'delete_zone', zoneId: 'zone-one' }],
    });
    await transport.reloadLayout();

    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site%20a/layout%2Fone/preview'
    );
    assert.strictEqual(calls[0].init.method, 'POST');
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        baseRevision: 'a'.repeat(64),
        operations: [{ op: 'delete_placement', placementId: 'pl-one' }],
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layouts/site%20a/layout%2Fone'
    );
    assert.strictEqual(calls[1].init.method, 'PUT');
    assert.strictEqual(calls[2].init.method, 'GET');
    assert.strictEqual(calls[2].init.credentials, 'same-origin');
    assert.strictEqual(calls[2].init.cache, 'no-store');
});

test('preserves structured conflict details for the session', async () => {
    const currentRevision = 'c'.repeat(64);
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-a',
        fetch: async () => response(409, {
            error: {
                code: 'revision_conflict',
                message: 'Facility Layout revision conflict.',
                details: { currentRevision },
            },
        }),
    });
    await assert.rejects(
        transport.previewOperations({
            baseRevision: 'd'.repeat(64),
            operations: [],
        }),
        error => {
            assert.strictEqual(error.name, 'FacilityLayoutTransportError');
            assert.strictEqual(error.status, 409);
            assert.strictEqual(error.code, 'revision_conflict');
            assert.strictEqual(error.currentRevision, currentRevision);
            assert.deepStrictEqual(error.details, { currentRevision });
            return true;
        }
    );
});

test('exposes revision-bound authoritative spatial requests', async () => {
    const calls = [];
    const signal = new AbortController().signal;
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-a',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { ok: true });
        },
    });
    await transport.spatialDiagnostics({
        baseRevision: 'e'.repeat(64),
        operations: [{ op: 'move_placement', placementId: 'pl-a' }],
    }, { signal });
    await transport.placementCandidates({
        baseRevision: 'e'.repeat(64),
        operations: [],
        assetId: 'asset-machine',
        assetDefinitionRevision: 'f'.repeat(64),
        requestedPosition: { x: 4, z: 7 },
        enabledFamilies: ['grid', 'boundary'],
        maximumCandidates: 8,
    });
    await transport.placementCandidatePreview({
        baseRevision: 'e'.repeat(64),
        operations: [{ op: 'delete_zone', zoneId: 'zone-old' }],
        request: {
            assetId: 'asset-machine',
            assetDefinitionRevision: 'f'.repeat(64),
            requestedPosition: { x: 8, y: 0, z: 9 },
            positionMode: 'manual',
            metadata: { instanceLabel: 'Machine 4' },
        },
        candidateId: 'candidate-safe',
    }, { signal });
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site-a/fl-a/spatial/diagnostics'
    );
    assert.strictEqual(calls[0].init.signal, signal);
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        baseRevision: 'e'.repeat(64),
        operations: [{ op: 'move_placement', placementId: 'pl-a' }],
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layouts/site-a/fl-a/spatial/candidates'
    );
    assert.deepStrictEqual(JSON.parse(calls[1].init.body), {
        baseRevision: 'e'.repeat(64),
        operations: [],
        request: {
            assetId: 'asset-machine',
            assetDefinitionRevision: 'f'.repeat(64),
            requestedPosition: { x: 4, y: 0, z: 7 },
            enabledFamilies: ['grid', 'boundary'],
            maximumCandidates: 8,
        },
    });
    assert.strictEqual(
        calls[2].url,
        '/api/facility-layouts/site-a/fl-a/spatial/candidates/preview'
    );
    assert.strictEqual(calls[2].init.signal, signal);
    assert.deepStrictEqual(JSON.parse(calls[2].init.body), {
        baseRevision: 'e'.repeat(64),
        operations: [{ op: 'delete_zone', zoneId: 'zone-old' }],
        request: {
            assetId: 'asset-machine',
            assetDefinitionRevision: 'f'.repeat(64),
            requestedPosition: { x: 8, y: 0, z: 9 },
            positionMode: 'manual',
            metadata: { instanceLabel: 'Machine 4' },
        },
        candidateId: 'candidate-safe',
    });
});

test('uses one session identity across the full proposal transaction', async () => {
    const calls = [];
    const revision = 'a'.repeat(64);
    const exactBinding = binding(revision);
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        sessionId: 'facility-browser-session-001',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { ok: true });
        },
    });
    const request = {
        schemaVersion: 1,
        requestId: 'request-browser-001',
        objective: 'place_and_cleanup',
        assetSet: [],
        strategies: ['compact_rows'],
    };
    await transport.createLayoutProposals({
        baseRevision: revision,
        request,
    });
    await transport.getLayoutProposalPreview({
        proposalId: 'proposal-one',
    });
    await transport.cancelLayoutProposal({
        proposalId: 'proposal-one',
    });
    await transport.approveLayoutProposal({
        proposalId: 'proposal-one',
        binding: exactBinding,
        idempotencyKey: 'layout-apply-001',
        explicitApproval: true,
    });
    await transport.applyLayoutProposal({
        approvalToken: 'approval-token-001',
        binding: exactBinding,
        idempotencyKey: 'layout-apply-001',
    });
    await transport.getLayoutReceipt({ receiptId: 'receipt-one' });

    assert.strictEqual(
        transport.sessionId,
        'facility-browser-session-001'
    );
    assert.deepStrictEqual(calls.map(item => item.url), [
        '/api/facility-layouts/site%20a/layout%2Fone/proposals',
        '/api/facility-layouts/site%20a/layout%2Fone/proposals/proposal-one/preview',
        '/api/facility-layouts/site%20a/layout%2Fone/proposals/proposal-one',
        '/api/facility-layouts/site%20a/layout%2Fone/approvals',
        '/api/facility-layouts/site%20a/layout%2Fone/apply',
        '/api/facility-layouts/site%20a/layout%2Fone/receipts/receipt-one',
    ]);
    assert.deepStrictEqual(calls.map(item => item.init.method), [
        'POST', 'GET', 'DELETE', 'POST', 'POST', 'GET',
    ]);
    calls.forEach(item => {
        assert.strictEqual(
            item.init.headers['X-InspectorPro-Session'],
            transport.sessionId
        );
    });
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        baseRevision: revision,
        request,
    });
    assert.deepStrictEqual(JSON.parse(calls[3].init.body), {
        proposalId: 'proposal-one',
        binding: exactBinding,
        idempotencyKey: 'layout-apply-001',
        explicitApproval: true,
    });
    assert.deepStrictEqual(JSON.parse(calls[4].init.body), {
        approvalToken: 'approval-token-001',
        binding: exactBinding,
        idempotencyKey: 'layout-apply-001',
    });
});

test('validates stable identity and revision inputs before fetch', async () => {
    assert.throws(
        () => Transport.createHttpTransport({
            siteId: '',
            layoutId: 'fl-a',
            fetch: async () => response(200, {}),
        }),
        /siteId/
    );
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-a',
        fetch: async () => response(200, {}),
    });
    assert.throws(
        () => transport.applyOperations({ operations: [] }),
        /baseRevision/
    );
    assert.throws(
        () => transport.previewOperations({
            baseRevision: 'a'.repeat(64),
            operations: {},
        }),
        /operations must be an array/
    );
    assert.throws(
        () => transport.placementCandidates({
            baseRevision: 'a'.repeat(64),
            operations: [],
            assetId: 'asset-a',
            assetDefinitionRevision: 'b'.repeat(64),
            requestedPosition: { x: 'not-a-number', z: 0 },
        }),
        /requestedPosition/
    );
    assert.throws(
        () => transport.placementCandidatePreview({
            baseRevision: 'a'.repeat(64),
            operations: [],
            request: {
                assetId: 'asset-a',
                assetDefinitionRevision: 'b'.repeat(64),
                requestedPosition: { x: 1, z: 2 },
            },
        }),
        /candidateId/
    );
    assert.throws(
        () => transport.createLayoutProposals({
            baseRevision: 'a'.repeat(64),
            request: {
                schemaVersion: 1,
                requestId: 'request-one',
                objective: 'cleanup_layout',
                assetSet: [],
                strategies: [],
            },
        }),
        /strategies/
    );
    assert.throws(
        () => transport.approveLayoutProposal({
            proposalId: 'proposal-one',
            binding: binding('a'.repeat(64)),
            idempotencyKey: 'layout-apply-001',
            explicitApproval: false,
        }),
        /explicitApproval/
    );
});

test('binds resumable G1 generation and explicit Save to one session', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        sessionId: 'facility-generation-session-001',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { ok: true });
        },
    });
    await transport.startG1Generation({
        prototypeMode: true,
        executionMode: 'authorized_draft_run',
        facilityEnvelope: {
            width: 100,
            depth: 80,
            sourceUnit: 'm',
            displayName: 'Generated Facility',
        },
        departments: {
            count: 2,
            labels: ['Receiving', 'Assembly'],
            proportions: null,
            arrangement: 'columns',
            orientation: 'auto',
        },
    });
    await transport.continueGenerationRun({
        runId: 'fgr-run-001',
        explicitStageAcceptance: false,
    });
    await transport.getGenerationRun({ runId: 'fgr-run-001' });
    await transport.undoGenerationRun({ runId: 'fgr-run-001' });
    await transport.saveGenerationRun({
        runId: 'fgr-run-001',
        cumulativeDiffHash: 'a'.repeat(64),
        explicitApproval: true,
    });
    const root = '/api/facility-layout-generation/site%20a/layout%2Fone';
    assert.deepStrictEqual(calls.map(item => item.url), [
        root + '/g1',
        root + '/runs/fgr-run-001/continue',
        root + '/runs/fgr-run-001',
        root + '/runs/fgr-run-001/undo',
        root + '/runs/fgr-run-001/save',
    ]);
    assert.deepStrictEqual(calls.map(item => item.init.method), [
        'POST', 'POST', 'GET', 'POST', 'POST',
    ]);
    calls.forEach(item => {
        assert.strictEqual(
            item.init.headers['X-InspectorPro-Session'],
            'facility-generation-session-001'
        );
    });
    assert.deepStrictEqual(JSON.parse(calls[1].init.body), {
        explicitStageAcceptance: false,
    });
    assert.deepStrictEqual(JSON.parse(calls[4].init.body), {
        cumulativeDiffHash: 'a'.repeat(64),
        explicitApproval: true,
    });
});

(async () => {
    let passed = 0;
    for (const item of tests) {
        try {
            await item.fn();
            passed += 1;
            process.stdout.write('ok - ' + item.name + '\n');
        } catch (error) {
            process.stderr.write('not ok - ' + item.name + '\n');
            throw error;
        }
    }
    process.stdout.write(
        'Facility layout transport tests: ' + passed + '/' + tests.length
        + ' passed\n'
    );
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
