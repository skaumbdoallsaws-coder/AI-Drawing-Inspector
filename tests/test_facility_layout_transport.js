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

test('binds the complete Facility design loop to one session and exact revisions', async () => {
    const calls = [];
    const signal = new AbortController().signal;
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-design',
        sessionId: 'session-design-one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { ok: true });
        },
    });
    const revisionA = 'a'.repeat(64);
    const revisionB = 'b'.repeat(64);
    const revisionC = 'c'.repeat(64);
    const revisionD = 'd'.repeat(64);
    const revisionE = 'e'.repeat(64);
    const intent = {
        schema_version: 'facility-design-intent-v1',
        operation: 'add_geometry_locks',
        target_labels: ['Main Boulevard'],
    };
    const editorFrame = {
        schemaVersion: 'facility-design-editor-frame-v1',
        draftRevision: revisionA,
    };

    await transport.createDesignBrief({
        workspaceId: 'workspace-facility-layout',
        editorFrame,
        semanticIntent: intent,
        sourceTurnRef: 'turn-one',
    }, { signal });
    await transport.inspectDesignBrief({
        briefId: 'brief-one',
        briefRevision: revisionA,
    });
    await transport.updateDesignBrief({
        briefId: 'brief-one',
        semanticIntent: intent,
        sourceTurnRef: 'turn-two',
    });
    await transport.startDesignPreview({
        briefId: 'brief-one',
        briefRevision: revisionA,
        workspaceId: 'workspace-facility-layout',
        clientGenerationId: 'generation-one',
        mode: 'lab',
    });
    await transport.continueDesignPreview({
        runId: 'run-one',
        maximumToolCalls: 10,
    });
    await transport.cancelDesignPreview({ runId: 'run-one' });
    await transport.inspectDesignProposal({
        proposalId: 'proposal-one',
        proposalRevision: revisionB,
        includeCandidateLayout: false,
    });
    await transport.prepareDesignProposalApply({
        proposalId: 'proposal-one',
        proposalRevision: revisionB,
        rootUndoFrame: editorFrame,
        previousInstallationState: { kind: 'root' },
        expectedResultEditorGenerationId: 'editor-generation-one',
        expectedResultCommandJournalHash: revisionC,
    });
    await transport.commitDesignProposalApply({
        transactionId: 'transaction-one',
        expectedTransactionRevision: revisionD,
        adoptionToken: 'adoption-token-one',
    });
    await transport.acknowledgeDesignProposalApply({
        transactionId: 'transaction-one',
        expectedTransactionRevision: revisionD,
        adoptionToken: 'adoption-token-one',
        observedInstallationFingerprint: revisionE,
    });
    await transport.recoverDesignProposalApply({
        transactionId: 'transaction-one',
        expectedTransactionRevision: revisionD,
        observedInstallationFingerprint: revisionE,
    });
    await transport.saveDesignProposalDraft({
        transactionId: 'transaction-one',
        expectedTransactionRevision: revisionD,
        observedDraftRevision: revisionB,
        observedCommandJournalHash: revisionC,
        explicitApproval: true,
    });
    await transport.inspectDesignUndo({ transactionId: 'transaction-one' });
    await transport.prepareDesignUndo({
        transactionId: 'transaction-one',
        expectedTransactionRevision: revisionD,
    });
    await transport.acknowledgeDesignUndo({
        transactionId: 'transaction-one',
        expectedTransactionRevision: revisionD,
        observedDraftRevision: revisionA,
        observedCommandJournalHash: revisionC,
    });

    assert.strictEqual(calls.length, 15);
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layout-design/site-a/fl-design/briefs'
    );
    assert.strictEqual(calls[0].init.signal, signal);
    calls.forEach(call => {
        assert.strictEqual(
            call.init.headers['X-InspectorPro-Session'],
            'session-design-one'
        );
        assert.strictEqual(call.init.cache, 'no-store');
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layout-design/site-a/fl-design/briefs/brief-one'
            + '?briefRevision=' + revisionA
    );
    assert.strictEqual(
        calls[3].url,
        '/api/facility-layout-design/site-a/fl-design/briefs/brief-one/preview'
    );
    assert.deepStrictEqual(JSON.parse(calls[3].init.body), {
        briefRevision: revisionA,
        workspaceId: 'workspace-facility-layout',
        clientGenerationId: 'generation-one',
        mode: 'lab',
    });
    assert.strictEqual(
        calls[5].url,
        '/api/facility-layout-design/site-a/fl-design/runs/run-one/cancel'
    );
    assert.strictEqual(
        calls[6].url,
        '/api/facility-layout-design/site-a/fl-design/proposals/proposal-one'
            + '?proposalRevision=' + revisionB
            + '&includeCandidateLayout=false'
    );
    assert.ok(calls[7].url.endsWith('/proposals/proposal-one/apply/prepare'));
    assert.ok(calls[8].url.endsWith('/transactions/transaction-one/apply/commit'));
    assert.ok(calls[9].url.endsWith('/transactions/transaction-one/apply/acknowledge'));
    assert.ok(calls[10].url.endsWith('/transactions/transaction-one/apply/recover'));
    assert.ok(calls[11].url.endsWith('/transactions/transaction-one/save'));
    assert.deepStrictEqual(JSON.parse(calls[11].init.body), {
        expectedTransactionRevision: revisionD,
        observedDraftRevision: revisionB,
        observedCommandJournalHash: revisionC,
        explicitApproval: true,
    });
    assert.ok(calls[12].url.endsWith('/transactions/transaction-one/undo'));
    assert.ok(calls[13].url.endsWith('/transactions/transaction-one/undo/prepare'));
    assert.ok(calls[14].url.endsWith('/transactions/transaction-one/undo/acknowledge'));
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

test('unwraps FastAPI detail errors from generation endpoints', async () => {
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-a',
        fetch: async () => response(422, {
            detail: {
                error: {
                    code: 'facility_asset_set_unplaceable',
                    message: 'The requested crane does not fit.',
                    details: {
                        placedCount: 0,
                        requestedCount: 1,
                    },
                },
            },
        }),
    });
    await assert.rejects(
        transport.continueGenerationRun({
            runId: 'run-one',
            explicitStageAcceptance: false,
        }),
        error => {
            assert.strictEqual(error.status, 422);
            assert.strictEqual(
                error.code,
                'facility_asset_set_unplaceable'
            );
            assert.strictEqual(
                error.message,
                'The requested crane does not fit.'
            );
            assert.deepStrictEqual(error.details, {
                placedCount: 0,
                requestedCount: 1,
            });
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

test('validates one exact manual navigation path without authoring geometry', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-a',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { valid: true, mutated: false });
        },
    });
    const result = await transport.validateManualNavigationPath({
        baseRevision: 'a'.repeat(64),
        operations: [{ op: 'move_placement', placementId: 'pl-operator' }],
        request: {
            actorPlacementId: 'pl-operator',
            actorClass: 'pedestrian',
            actorProfileRef: {
                profileKind: 'pedestrian',
                profileId: 'pedestrian-profile:asset-operator',
                profileRevision: 'b'.repeat(64),
            },
            constraintMode: 'complete_override',
            direction: 'forward',
            points: [{ x: 1, z: 2 }, { x: 5, z: 2 }],
            prototypeMode: true,
        },
    });
    assert.deepStrictEqual(result, { valid: true, mutated: false });
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site-a/fl-a/navigation/manual-path/validate'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        baseRevision: 'a'.repeat(64),
        operations: [{ op: 'move_placement', placementId: 'pl-operator' }],
        request: {
            actorPlacementId: 'pl-operator',
            actorClass: 'pedestrian',
            actorProfileRef: {
                profileKind: 'pedestrian',
                profileId: 'pedestrian-profile:asset-operator',
                profileRevision: 'b'.repeat(64),
            },
            constraintMode: 'complete_override',
            direction: 'forward',
            points: [{ x: 1, z: 2 }, { x: 5, z: 2 }],
            prototypeMode: true,
        },
    });
    assert.throws(
        () => transport.validateManualNavigationPath({
            baseRevision: 'a'.repeat(64),
            operations: [],
            request: {
                actorPlacementId: 'pl-operator',
                actorClass: 'pedestrian',
                constraintMode: 'complete_override',
                direction: 'forward',
                points: [{ x: 1, z: 2, y: 0 }, { x: 5, z: 2 }],
            },
        }),
        /support x and z/
    );
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
    await transport.amendGenerationCirculation({
        runId: 'fgr-run-001',
        expectedDraftRevision: 'd'.repeat(64),
        prototypeMode: true,
        circulation: {
            action: 'create',
            route_kind: 'material',
            width: 6,
            source_unit: 'm',
            source_department: 'Receiving',
            target_department: 'Assembly',
            via_departments: [],
            direction: 'two_way',
            label: null,
            execution_mode: 'authorized_draft_run',
        },
    });
    await transport.amendGenerationSubdivisions({
        runId: 'fgr-run-001',
        expectedDraftRevision: 'e'.repeat(64),
        prototypeMode: true,
        subdivision: {
            parent_department: 'Assembly',
            count: 2,
            labels: ['Mechanical Build', 'Electrical Build'],
            proportions: null,
            arrangement: 'columns',
            orientation: 'auto',
            rows: null,
            preserve_parent: true,
            execution_mode: 'authorized_draft_run',
        },
    });
    await transport.amendGenerationAssets({
        runId: 'fgr-run-001',
        expectedDraftRevision: 'f'.repeat(64),
        prototypeMode: true,
        assetPlacement: {
            asset_id: 'asset-cnc-mill',
            asset_definition_revision: '9'.repeat(64),
            quantity: 2,
            target_area: 'Mechanical Build',
            orientation_mode: 'long_side_east_west',
            facing_direction: null,
            resource_role: 'production',
            access_requirement: 'physical_only',
            preserve_hierarchy: true,
            execution_mode: 'authorized_draft_run',
        },
    });
    await transport.amendGenerationCells({
        runId: 'fgr-run-001',
        expectedDraftRevision: '1'.repeat(64),
        prototypeMode: true,
        cellComposition: {
            target_area: 'Mechanical Build',
            candidate_strategies: ['line', 'l', 'u'],
            selected_strategy: null,
            objective: 'shortest_travel',
            preferred_gap_meters: 1,
            invert_u: false,
            process_sequence_placement_ids: [],
            preserve_departments: true,
            preserve_routes: true,
            preserve_markings: true,
            preserve_locked_and_manual: true,
            execution_mode: 'authorized_draft_run',
        },
    });
    await transport.amendGenerationCellReplication({
        runId: 'fgr-run-001',
        expectedDraftRevision: '2'.repeat(64),
        prototypeMode: true,
        cellReplication: {
            source_cell: 'Mechanical Build',
            target_areas: ['Electrical Build', 'Test'],
            copy_current_edited_state: false,
            preserve_departments: true,
            preserve_routes: true,
            preserve_markings: true,
            preserve_source_cell: true,
            preserve_manual_and_locked: true,
            execution_mode: 'authorized_draft_run',
        },
    });
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
        root + '/runs/fgr-run-001/circulation',
        root + '/runs/fgr-run-001/subdivisions',
        root + '/runs/fgr-run-001/assets',
        root + '/runs/fgr-run-001/cells',
        root + '/runs/fgr-run-001/cell-replication',
        root + '/runs/fgr-run-001/undo',
        root + '/runs/fgr-run-001/save',
    ]);
    assert.deepStrictEqual(calls.map(item => item.init.method), [
        'POST', 'POST', 'GET', 'POST', 'POST', 'POST', 'POST', 'POST',
        'POST', 'POST',
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
    assert.deepStrictEqual(JSON.parse(calls[3].init.body), {
        expectedDraftRevision: 'd'.repeat(64),
        prototypeMode: true,
        circulation: {
            action: 'create',
            route_kind: 'material',
            width: 6,
            source_unit: 'm',
            source_department: 'Receiving',
            target_department: 'Assembly',
            via_departments: [],
            direction: 'two_way',
            label: null,
            execution_mode: 'authorized_draft_run',
        },
    });
    assert.deepStrictEqual(JSON.parse(calls[4].init.body), {
        expectedDraftRevision: 'e'.repeat(64),
        prototypeMode: true,
        subdivision: {
            parent_department: 'Assembly',
            count: 2,
            labels: ['Mechanical Build', 'Electrical Build'],
            proportions: null,
            arrangement: 'columns',
            orientation: 'auto',
            rows: null,
            preserve_parent: true,
            execution_mode: 'authorized_draft_run',
        },
    });
    assert.deepStrictEqual(JSON.parse(calls[5].init.body), {
        expectedDraftRevision: 'f'.repeat(64),
        prototypeMode: true,
        assetPlacement: {
            asset_id: 'asset-cnc-mill',
            asset_definition_revision: '9'.repeat(64),
            quantity: 2,
            target_area: 'Mechanical Build',
            orientation_mode: 'long_side_east_west',
            facing_direction: null,
            resource_role: 'production',
            access_requirement: 'physical_only',
            preserve_hierarchy: true,
            execution_mode: 'authorized_draft_run',
        },
    });
    assert.deepStrictEqual(JSON.parse(calls[6].init.body), {
        expectedDraftRevision: '1'.repeat(64),
        prototypeMode: true,
        cellComposition: {
            target_area: 'Mechanical Build',
            candidate_strategies: ['line', 'l', 'u'],
            selected_strategy: null,
            objective: 'shortest_travel',
            preferred_gap_meters: 1,
            invert_u: false,
            process_sequence_placement_ids: [],
            preserve_departments: true,
            preserve_routes: true,
            preserve_markings: true,
            preserve_locked_and_manual: true,
            execution_mode: 'authorized_draft_run',
        },
    });
    assert.deepStrictEqual(JSON.parse(calls[7].init.body), {
        expectedDraftRevision: '2'.repeat(64),
        prototypeMode: true,
        cellReplication: {
            source_cell: 'Mechanical Build',
            target_areas: ['Electrical Build', 'Test'],
            copy_current_edited_state: false,
            preserve_departments: true,
            preserve_routes: true,
            preserve_markings: true,
            preserve_source_cell: true,
            preserve_manual_and_locked: true,
            execution_mode: 'authorized_draft_run',
        },
    });
    assert.deepStrictEqual(JSON.parse(calls[9].init.body), {
        cumulativeDiffHash: 'a'.repeat(64),
        explicitApproval: true,
    });
});

test('starts one full-factory generation program on the durable run API', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        sessionId: 'full-factory-session-001',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { runId: 'fgr-full-001' });
        },
    });
    const fullFactory = {
        facility_envelope: {
            width: 120,
            depth: 90,
            source_unit: 'm',
            display_name: 'Full Factory',
            grid_size: 1,
        },
        departments: {
            count: 2,
            labels: ['Inbound', 'Dispatch'],
            proportions: null,
            arrangement: 'columns',
            orientation: 'horizontal',
            rows: null,
        },
        circulation: { routes: [], crossings: [] },
        subdivisions: [],
        asset_placements: [],
        seed_cell: null,
        cell_replication: null,
        execution_mode: 'authorized_draft_run',
    };
    await transport.startFullFactoryGeneration({
        prototypeMode: true,
        supersedeActiveDraft: true,
        workspaceId: 'workspace-facility-layout',
        fullFactory,
    });
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layout-generation/site%20a/layout%2Fone/full-factory'
    );
    assert.strictEqual(calls[0].init.method, 'POST');
    const body = JSON.parse(calls[0].init.body);
    assert.deepStrictEqual(body.fullFactory, fullFactory);
    assert.strictEqual(
        calls[0].init.headers['X-InspectorPro-Session'],
        'full-factory-session-001'
    );
});

test('starts one trusted Facility Planning package on the durable run API', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        sessionId: 'planning-package-session-001',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { runId: 'fgr-planning-001' });
        },
    });
    await transport.startFacilityPlanningGeneration({
        prototypeMode: true,
        supersedeActiveDraft: true,
        planningPackageId: 'mmle-50d-facility-planning-v1',
    });
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layout-generation/site%20a/layout%2Fone/planning-package'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        prototypeMode: true,
        supersedeActiveDraft: true,
        planningPackageId: 'mmle-50d-facility-planning-v1',
    });
});

test('sends one closed FacilityProgram resource amendment', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        sessionId: 'planning-amendment-session-001',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { runId: 'fgr-planning-001' });
        },
    });
    await transport.amendFacilityProgramResourceBatch({
        runId: 'fgr-planning-001',
        expectedDraftRevision: 'a'.repeat(64),
        prototypeMode: true,
        resourceBatchId: 'raw-material-racks',
        patch: { quantity: 89 },
    });
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layout-generation/site%20a/layout%2Fone/runs/'
            + 'fgr-planning-001/facility-program/resource-batch'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        expectedDraftRevision: 'a'.repeat(64),
        prototypeMode: true,
        resourceBatchId: 'raw-material-racks',
        patch: { quantity: 89 },
    });
});

test('creates a summary-only motion request and fetches full evidence by revision', async () => {
    const calls = [];
    const revision = 'a'.repeat(64);
    const vehicleRevision = 'b'.repeat(64);
    const packageId = 'fmp-' + 'c'.repeat(64);
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { packageId });
        },
    });
    await transport.createMotionPackage({
        baseRevision: revision,
        operations: [],
        request: {
            routeId: 'route-main',
            vehicleProfileRef: {
                vehicleProfileId: 'forklift-one',
                vehicleProfileRevision: vehicleRevision,
            },
            travelDirection: 'forward',
        },
    });
    await transport.getMotionPackage({
        packageId,
        activeRevision: revision,
    });

    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site%20a/layout%2Fone/motion-packages'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        baseRevision: revision,
        operations: [],
        request: {
            routeId: 'route-main',
            vehicleProfileRef: {
                vehicleProfileId: 'forklift-one',
                vehicleProfileRevision: vehicleRevision,
            },
            travelDirection: 'forward',
        },
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layouts/site%20a/layout%2Fone/motion-packages/'
            + packageId + '?activeRevision=' + revision
    );
    assert.strictEqual(calls[1].init.method, 'GET');
});

test('motion transport rejects model-authored geometry and grid resolution', async () => {
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'layout-one',
        fetch: async () => response(200, {}),
    });
    await assert.rejects(
        async () => transport.createMotionPackage({
            baseRevision: 'a'.repeat(64),
            operations: [],
            request: {
                routeId: 'route-main',
                vehicleProfileRef: {
                    vehicleProfileId: 'forklift-one',
                    vehicleProfileRevision: 'b'.repeat(64),
                },
                gridResolutionMeters: 0.001,
            },
        }),
        /gridResolutionMeters is not supported/
    );
});

test('compiles a summary-only navigation snapshot and fetches its full package', async () => {
    const calls = [];
    const revision = 'a'.repeat(64);
    const packageId = 'nsp-' + 'c'.repeat(24);
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { packageId });
        },
    });
    await transport.compileNavigationSnapshot({
        baseRevision: revision,
        operations: [],
        request: { movementProgramId: 'nmp-operator-cycle' },
    });
    await transport.getNavigationPackage({ packageId });

    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site%20a/layout%2Fone/navigation/snapshots/compile'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        baseRevision: revision,
        operations: [],
        request: { movementProgramId: 'nmp-operator-cycle' },
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layouts/site%20a/layout%2Fone/navigation/packages/'
            + packageId
    );
    assert.strictEqual(calls[1].init.method, 'GET');
});

test('navigation snapshot transport rejects authored geometry and incomplete bindings', async () => {
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'layout-one',
        fetch: async () => response(200, {}),
    });
    await assert.rejects(
        async () => transport.compileNavigationSnapshot({
            baseRevision: 'a'.repeat(64),
            request: {
                actorPlacementId: 'pl-operator',
                actorClass: 'pedestrian',
                actorProfileRef: {
                    profileKind: 'pedestrian',
                    profileId: 'operator-profile',
                    profileRevision: 'b'.repeat(64),
                },
                points: [{ x: 1, z: 2 }, { x: 3, z: 4 }],
            },
        }),
        /points is not supported/
    );
    await assert.rejects(
        async () => transport.compileNavigationSnapshot({
            baseRevision: 'a'.repeat(64),
            request: { actorPlacementId: 'pl-operator' },
        }),
        /requires a movementProgramId or an exact actor binding/
    );
});

test('plans an identity-only actor journey and fetches full geometry separately', async () => {
    const calls = [];
    const revision = 'a'.repeat(64);
    const packageId = 'nsp-' + 'b'.repeat(24);
    const journeySolutionId = 'njs-' + 'c'.repeat(24);
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { journeySolutionId });
        },
    });
    await transport.planActorJourney({
        baseRevision: revision,
        operations: [],
        request: {
            navigationPackageId: packageId,
            movementProgramId: 'nmp-operator-cycle',
        },
    });
    await transport.getActorJourney({ journeySolutionId });

    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site%20a/layout%2Fone/navigation/journeys/plan'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body).request, {
        navigationPackageId: packageId,
        movementProgramId: 'nmp-operator-cycle',
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layouts/site%20a/layout%2Fone/navigation/journeys/'
            + journeySolutionId
    );
});

test('actor journey transport rejects model-authored waypoints', async () => {
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'layout-one',
        fetch: async () => response(200, {}),
    });
    await assert.rejects(
        async () => transport.planActorJourney({
            baseRevision: 'a'.repeat(64),
            request: {
                navigationPackageId: 'nsp-' + 'b'.repeat(24),
                movementProgramId: 'nmp-operator-cycle',
                waypoints: [{ x: 1, z: 2 }],
            },
        }),
        /waypoints is not supported/
    );
});

test('compiles an identity-only navigation handoff and fetches its result', async () => {
    const calls = [];
    const revision = 'a'.repeat(64);
    const handoffResultId = 'nhr-' + 'd'.repeat(24);
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { handoffResultId });
        },
    });
    await transport.compileNavigationHandoff({
        baseRevision: revision,
        operations: [],
        request: {
            handoffProgramId: 'nhp-transfer',
            journeySolutionIds: ['njs-source', 'njs-target'],
        },
    });
    await transport.getNavigationHandoff({ handoffResultId });

    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site%20a/layout%2Fone/navigation/handoffs/compile'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body).request, {
        handoffProgramId: 'nhp-transfer',
        journeySolutionIds: ['njs-source', 'njs-target'],
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layouts/site%20a/layout%2Fone/navigation/handoffs/'
            + handoffResultId
    );
});

test('navigation handoff transport rejects geometry and duplicate journeys', async () => {
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'layout-one',
        fetch: async () => response(200, {}),
    });
    await assert.rejects(
        async () => transport.compileNavigationHandoff({
            baseRevision: 'a'.repeat(64),
            request: {
                handoffProgramId: 'nhp-transfer',
                journeySolutionIds: ['njs-one', 'njs-two'],
                position: { x: 1, z: 2 },
            },
        }),
        /position is not supported/
    );
    await assert.rejects(
        async () => transport.compileNavigationHandoff({
            baseRevision: 'a'.repeat(64),
            request: {
                handoffProgramId: 'nhp-transfer',
                journeySolutionIds: ['njs-one', 'njs-one'],
            },
        }),
        /must be distinct/
    );
});

test('builds navigation activity from opaque journey and handoff identities', async () => {
    const calls = [];
    const revision = 'a'.repeat(64);
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { scenarioId: 'fas-one' });
        },
    });
    await transport.buildNavigationActivityScenario({
        baseRevision: revision,
        operations: [],
        request: {
            journeySolutionIds: ['njs-one', 'njs-two'],
            handoffResultIds: ['nhr-one'],
            scenarioLabel: 'Reviewed navigation playback',
            prototypeMode: true,
        },
    });
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site%20a/layout%2Fone/navigation/activity-scenarios'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body).request, {
        journeySolutionIds: ['njs-one', 'njs-two'],
        handoffResultIds: ['nhr-one'],
        scenarioLabel: 'Reviewed navigation playback',
        prototypeMode: true,
    });
});

test('complete reference movement preset remains closed and coordinate free', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site-local',
        layoutId: 'fl-reference-manual-20260812',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { scenarioId: 'fas-reference' });
        },
    });
    await transport.createActivityScenario({
        baseRevision: 'a'.repeat(64),
        operations: [],
        request: {
            preset: 'reference_complete_navigation',
            prototypeMode: true,
            maximumActors: 23,
            scenarioLabel: 'Complete reference movement',
        },
    });
    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site-local/fl-reference-manual-20260812/activity-scenarios'
    );
    assert.deepStrictEqual(JSON.parse(calls[0].init.body).request, {
        preset: 'reference_complete_navigation',
        prototypeMode: true,
        maximumActors: 23,
        scenarioLabel: 'Complete reference movement',
    });
    await assert.rejects(
        async () => transport.createActivityScenario({
            baseRevision: 'a'.repeat(64),
            request: {
                preset: 'reference_complete_navigation',
                prototypeMode: true,
                x: 10,
            },
        }),
        /field x is not supported/
    );
    await assert.rejects(
        async () => transport.createActivityScenario({
            baseRevision: 'a'.repeat(64),
            request: {
                preset: 'reference_complete_navigation',
                prototypeMode: true,
                maximumActors: 25,
            },
        }),
        /integer from 1 to 24/
    );
});

test('reference downstream preset remains closed and coordinate free', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site-local',
        layoutId: 'fl-reference-manual-20260812',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { scenarioId: 'fas-downstream' });
        },
    });
    await transport.createActivityScenario({
        baseRevision: 'a'.repeat(64),
        operations: [],
        request: {
            preset: 'reference_downstream_navigation',
            prototypeMode: true,
            maximumActors: 8,
            scenarioLabel: 'Downstream operator movement candidates',
        },
    });
    assert.deepStrictEqual(JSON.parse(calls[0].init.body).request, {
        preset: 'reference_downstream_navigation',
        prototypeMode: true,
        maximumActors: 8,
        scenarioLabel: 'Downstream operator movement candidates',
    });
});

test('finished goods vehicle-cycle presets remain closed and coordinate free', async () => {
    for (const preset of [
        'reference_finished_goods_putaway',
        'reference_finished_goods_dispatch',
    ]) {
        const calls = [];
        const transport = Transport.createHttpTransport({
            siteId: 'site-local',
            layoutId: 'fl-reference-manual-20260812',
            fetch: async (url, init) => {
                calls.push({ url, init });
                return response(200, { scenarioId: 'fas-finished-goods' });
            },
        });
        await transport.createActivityScenario({
            baseRevision: 'a'.repeat(64),
            operations: [],
            request: {
                preset,
                prototypeMode: true,
                maximumActors: 1,
                scenarioLabel: preset.endsWith('dispatch')
                    ? 'Finished Goods dispatch cycle'
                    : 'Finished Goods put-away cycle',
            },
        });
        const request = JSON.parse(calls[0].init.body).request;
        assert.strictEqual(request.preset, preset);
        assert.strictEqual(request.maximumActors, 1);
        assert.strictEqual(request.prototypeMode, true);
    }
});

test('receiving vehicle-cycle preset remains closed and coordinate free', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site-local',
        layoutId: 'fl-reference-manual-20260812',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { scenarioId: 'fas-receiving' });
        },
    });
    await transport.createActivityScenario({
        baseRevision: 'a'.repeat(64),
        operations: [],
        request: {
            preset: 'reference_receiving_putaway',
            prototypeMode: true,
            maximumActors: 2,
            scenarioLabel: 'Receiving pallet-to-rack cycles',
        },
    });
    assert.deepStrictEqual(JSON.parse(calls[0].init.body).request, {
        preset: 'reference_receiving_putaway',
        prototypeMode: true,
        maximumActors: 2,
        scenarioLabel: 'Receiving pallet-to-rack cycles',
    });
    await assert.rejects(
        async () => transport.createActivityScenario({
            baseRevision: 'a'.repeat(64),
            request: {
                preset: 'reference_receiving_putaway',
                prototypeMode: true,
                maximumActors: 2,
                waypoint: { x: 25, z: 160 },
            },
        }),
        /field waypoint is not supported/
    );
});

test('navigation activity rejects coordinate fields and more than 24 actors', async () => {
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'layout-one',
        fetch: async () => response(200, {}),
    });
    await assert.rejects(
        async () => transport.buildNavigationActivityScenario({
            baseRevision: 'a'.repeat(64),
            request: {
                journeySolutionIds: ['njs-one'],
                prototypeMode: true,
                waypoints: [{ x: 1, z: 2 }],
            },
        }),
        /waypoints is not supported/
    );
    await assert.rejects(
        async () => transport.buildNavigationActivityScenario({
            baseRevision: 'a'.repeat(64),
            request: {
                journeySolutionIds: Array.from(
                    { length: 21 },
                    (_, index) => 'njs-' + index
                ),
                prototypeMode: true,
            },
        }),
        /between 1 and 20/
    );
});

test('construction transport binds approval to the editor session and never saves', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({siteId: 'site-a', layoutId: 'layout-one', sessionId: 'session-pilot',
        fetch: async (url, init) => { calls.push({url, init}); return response(200, {ok: true}); }});
    const proposalId = 'fcp-' + 'a'.repeat(64);
    await transport.getConstructionPreview(proposalId);
    await transport.approveConstructionPreview(proposalId, {requestId: 'approval-one', sessionId: 'not-authority',
        editorGenerationId: 'editor-one', expectedDraftRevision: 'b'.repeat(64), candidateRevision: 'c'.repeat(64)});
    assert.ok(calls[0].url.endsWith('/construction/' + proposalId));
    assert.strictEqual(calls[0].init.method, 'GET');
    assert.ok(calls[1].url.endsWith('/approve-unsaved'));
    assert.strictEqual(calls[1].init.method, 'POST');
    assert.strictEqual(JSON.parse(calls[1].init.body).sessionId, 'session-pilot');
    assert.strictEqual(calls[1].init.headers['X-InspectorPro-Session'], 'session-pilot');
    assert.ok(calls.every(call => call.init.method !== 'PUT'));
    await assert.rejects(async () => transport.approveConstructionPreview(proposalId, {
        requestId: 'approval-two', editorGenerationId: 'editor-one', expectedDraftRevision: 'bad', candidateRevision: 'c'.repeat(64)}));
    assert.strictEqual(calls.length, 2);
});

test('generation source and exact candidate requests are read-only and scoped', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({siteId: 'site-a', layoutId: 'empty', sessionId: 'session-pilot',
        fetch: async (url, init) => { calls.push({url, init}); return response(200, {}); }});
    await transport.listGenerationPlanningSources();
    const editor = {baseRevision: 'a'.repeat(64), draftRevision: 'a'.repeat(64), dirty: false};
    await transport.inspectGenerationPlanningPreview({workspaceId: 'planning-session', previewId: 'b'.repeat(64),
        previewRevision: 'c'.repeat(64)}, editor);
    assert.strictEqual(calls[0].url, '/api/facility-layout-planning/site-a/empty/sources');
    assert.strictEqual(calls[0].init.method, 'GET');
    assert.strictEqual(calls[1].url, '/api/facility-layout-planning/site-a/empty/inspect');
    assert.deepStrictEqual(JSON.parse(calls[1].init.body).editorContext, editor);
    assert.ok(calls.every(call => !/apply|save/.test(call.url)));
    await assert.rejects(async () => transport.inspectGenerationPlanningPreview({workspaceId: 'x', previewId: 'bad', previewRevision: 'x'}, editor));
    assert.strictEqual(calls.length, 2);
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
