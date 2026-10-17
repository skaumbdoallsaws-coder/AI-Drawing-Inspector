'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Session = require('../static/facility_layout_session.js');
const Transport = require('../static/facility_layout_transport.js');
const App = require('../static/facility_layout_app.js');
const { Workspace } = require('../static/facility_layout_workspace.js');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));
const A = 'a'.repeat(64);
const B = 'b'.repeat(64);
const C = 'c'.repeat(64);
const reference = { siteId: 'site-a', layoutId: 'fl-a', revision: A, proposalId: 'flp-exact' };

function layout(displayName = 'Original') {
    return { layoutId: 'fl-a', association: { siteId: 'site-a' }, displayName,
        placements: [], zones: [], routes: [] };
}

function binding(revision = A) {
    return { target: { domain: 'facility-layout', scopeId: 'fls:' + '9'.repeat(64), resourceId: 'fl-a' },
        baseRevision: revision, diffHash: 'd'.repeat(64), dependencyFingerprint: 'e'.repeat(64) };
}

function preview(undo = false) {
    return {
        proposalId: undo ? 'flp-undo' : 'flp-exact', action: 'layout.apply', previewPure: true,
        transactionBinding: binding(undo ? B : A), createdAt: 1800000000, expiresAt: 1800003600,
        alternative: {
            alternativeId: undo ? 'exact-undo' : 'exact-edit',
            strategy: undo ? 'exact-undo-v1' : 'exact-operations-v1',
            operations: undo ? [{ op: 'restore_approved_revision', receiptId: 'flr-approved' }]
                : [{ op: 'rename_layout', displayName: 'Approved' }],
            metrics: { operationCount: 1 }, ghostPreview: { layout: layout(undo ? 'Original' : 'Approved') },
            transactionBinding: binding(undo ? B : A),
        },
    };
}

function proposalSet(value) {
    return { layoutRevision: value.transactionBinding.baseRevision, previewPure: value.previewPure,
        selectedProposalId: value.proposalId, alternatives: [{ ...clone(value.alternative),
            proposalId: value.proposalId, createdAt: value.createdAt, expiresAt: value.expiresAt }] };
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}

function fixture() {
    const calls = [];
    let saved = { revision: A, layout: layout() };
    let approvedId = null;
    const server = {
        getPreview: payload => preview(payload.proposalId === 'flp-undo'),
        undoPreview: () => proposalSet(preview(true)),
        applyReceipt: () => approvedId === 'flp-undo'
            ? { receiptId: 'flr-undone', revision: C, layout: layout() }
            : { receiptId: 'flr-approved', revision: B, layout: layout('Approved') },
    };
    const transport = {
        siteId: 'site-a', layoutId: 'fl-a',
        async getLayoutProposalPreview(payload, options) {
            calls.push(['preview', clone(payload), options]);
            return clone(await server.getPreview(payload));
        },
        async createOperationUndoPreview(payload, options) {
            calls.push(['undo-preview', clone(payload), options]);
            return clone(await server.undoPreview(payload));
        },
        async approveLayoutProposal(payload) {
            calls.push(['approve', clone(payload)]);
            approvedId = payload.proposalId;
            return { approvalToken: 'explicit-user-token' };
        },
        async applyLayoutProposal(payload) {
            calls.push(['apply', clone(payload)]);
            saved = clone(server.applyReceipt());
            return clone(saved);
        },
        async previewOperations(payload) {
            calls.push(['manual-preview', clone(payload)]);
            const document = clone(saved.layout);
            payload.operations.forEach(op => { document.displayName = op.displayName; });
            return { revision: payload.operations.length ? C : saved.revision, document };
        },
        async applyOperations(payload) {
            calls.push(['manual-save', clone(payload)]);
            saved = { revision: C, layout: layout('Manual') };
            return clone(saved);
        },
        async cancelLayoutProposal(payload) { calls.push(['cancel', clone(payload)]); return {}; },
        async reloadLayout() { return clone(saved); },
        async prepareDesignUndo() { throw new Error('Unexpected design Undo'); },
    };
    const session = Session.createSession(transport);
    session.load(saved);
    return { session, transport, server, calls };
}

async function applyExact(f) {
    await f.session.fetchAndInstallOperationProposal(reference);
    await f.session.approveAndApplyLayoutProposal();
}

function assertNoWrites(f) {
    assert.equal(f.calls.some(call => ['approve', 'apply', 'manual-save', 'manual-preview'].includes(call[0])), false);
}

test('GET preview installs the exact server ghost without editing or approving', async () => {
    const f = fixture();
    const signal = new AbortController().signal;
    const snapshots = [];
    f.session.subscribe(state => snapshots.push(state));
    const state = await f.session.fetchAndInstallOperationProposal(reference, { signal });
    assert.deepEqual(f.calls, [['preview', { proposalId: reference.proposalId }, { signal }]]);
    assert.deepEqual(state.layout, layout());
    assert.equal(state.baseRevision, A);
    assert.equal(state.dirty, false);
    assert.deepEqual(state.operations, []);
    const alternative = state.layoutProposal.alternatives[0];
    assert.equal(alternative.proposalId, reference.proposalId);
    assert.deepEqual(alternative.transactionBinding, binding());
    assert.deepEqual(alternative.ghostPreview.layout, layout('Approved'));
    assert.equal(snapshots.some(snapshot => snapshot.busy), true);
    assert.equal(snapshots.at(-1).busy, false);
    assertNoWrites(f);
});

test('binding alias is accepted and still revalidated at explicit approval', async () => {
    const f = fixture();
    f.server.getPreview = () => {
        const value = preview();
        value.binding = value.transactionBinding;
        delete value.transactionBinding;
        return value;
    };
    await applyExact(f);
    assert.deepEqual(f.calls.map(call => call[0]), ['preview', 'preview', 'approve', 'apply']);
    assert.deepEqual(f.calls[2][1].binding, binding());
    assert.equal(f.calls[2][1].explicitApproval, true);
    assert.equal(f.calls[3][1].approvalToken, 'explicit-user-token');
    assert.equal(f.calls[2][1].idempotencyKey, f.calls[3][1].idempotencyKey);
});

for (const [name, mutate] of [
    ['proposal ID', value => { value.proposalId = 'flp-other'; }],
    ['inner proposal ID', value => { value.alternative.proposalId = 'flp-other'; }],
    ['purity', value => { value.previewPure = false; }],
    ['base revision', value => { value.alternative.transactionBinding.baseRevision = B; }],
    ['scope binding', value => { value.alternative.transactionBinding.target.scopeId = 'other-scope'; }],
    ['diff binding', value => { value.transactionBinding.diffHash = 'f'.repeat(64); }],
    ['dependency binding', value => { value.transactionBinding.dependencyFingerprint = 'f'.repeat(64); }],
    ['target resource', value => {
        value.transactionBinding.target.resourceId = 'fl-other';
        value.alternative.transactionBinding.target.resourceId = 'fl-other';
    }],
    ['target domain', value => {
        value.transactionBinding.target.domain = 'process-map';
        value.alternative.transactionBinding.target.domain = 'process-map';
    }],
    ['ghost layout', value => { value.alternative.ghostPreview.layout.layoutId = 'fl-other'; }],
    ['ghost site', value => { value.alternative.ghostPreview.layout.association.siteId = 'other-site'; }],
    ['proposal subtype', value => { value.alternative.strategy = 'auto-arrange'; }],
]) {
    test('rejects mismatched server ' + name, async () => {
        const f = fixture();
        f.server.getPreview = () => { const value = preview(); mutate(value); return value; };
        await assert.rejects(f.session.fetchAndInstallOperationProposal(reference));
        assert.equal(f.session.getState().layoutProposal, null);
        assert.equal(f.session.getState().busy, false);
        assertNoWrites(f);
    });
}

test('rejects raw operations and foreign references before fetching', async () => {
    const f = fixture();
    for (const input of [
        { ...reference, operations: preview().alternative.operations },
        { ...reference, revision: B }, { ...reference, layoutId: 'fl-other' },
        { ...reference, siteId: 'site-other' },
    ]) await assert.rejects(f.session.fetchAndInstallOperationProposal(input));
    assert.equal(f.calls.length, 0);
});

test('a dirty editor cannot fetch an operation proposal', async () => {
    const f = fixture();
    await f.session.renameLayout('Manual');
    await assert.rejects(f.session.fetchAndInstallOperationProposal(reference));
    assert.deepEqual(f.calls.map(call => call[0]), ['manual-preview']);
});

test('busy fetch blocks editor mutation and rejects a changed active context', async () => {
    const f = fixture();
    const pending = deferred();
    f.server.getPreview = () => pending.promise;
    let current = true;
    const request = f.session.fetchAndInstallOperationProposal(reference, { isCurrent: () => current });
    assert.equal(f.session.getState().busy, true);
    assert.throws(() => f.session.load({ revision: B, layout: layout() }), { code: 'session_busy' });
    await assert.rejects(f.session.renameLayout('Manual'), { code: 'session_busy' });
    current = false;
    pending.resolve(preview());
    await assert.rejects(request, { code: 'layout_proposal_stale' });
    assert.equal(f.session.getState().layoutProposal, null);
    assert.equal(f.session.getState().busy, false);
    assertNoWrites(f);
});

test('existing preview survives busy notifications and a failed fetch', async () => {
    const f = fixture();
    await f.session.fetchAndInstallOperationProposal(reference);
    const before = f.session.getState().layoutProposal;
    const pending = deferred();
    f.server.getPreview = () => pending.promise;
    const snapshots = [];
    f.session.subscribe(state => snapshots.push(state));
    const request = f.session.fetchAndInstallOperationProposal(reference);
    pending.reject(new Error('Network unavailable'));
    await assert.rejects(request, /Network unavailable/);
    assert.equal(snapshots.some(snapshot => snapshot.busy), true);
    snapshots.forEach(snapshot => assert.deepEqual(snapshot.layoutProposal, before));
    assertNoWrites(f);
});

test('explicit approval refuses a changed server binding without approving', async () => {
    const f = fixture();
    await f.session.fetchAndInstallOperationProposal(reference);
    f.server.getPreview = () => {
        const value = preview();
        value.transactionBinding.diffHash = 'f'.repeat(64);
        value.alternative.transactionBinding.diffHash = 'f'.repeat(64);
        return value;
    };
    await assert.rejects(f.session.approveAndApplyLayoutProposal(), { code: 'layout_proposal_stale' });
    assert.equal(f.session.getState().layoutProposal.alternatives[0].proposalId, 'flp-exact');
    assertNoWrites(f);
});

test('Undo requests the committed receipt preview and waits for a second explicit approval', async () => {
    const f = fixture();
    await applyExact(f);
    assert.equal(f.session.getState().canUndo, true);
    assert.deepEqual(f.session.getState().recentReceiptIds, ['flr-approved']);
    assert.deepEqual(f.session.getState().lastApprovedOperationCommit, {
        receiptId: 'flr-approved', revision: B, siteId: 'site-a', layoutId: 'fl-a',
        editorGenerationId: f.session.getState().editorGenerationId,
    });
    const before = f.calls.length;
    const undoState = await f.session.undo();
    assert.deepEqual(f.calls.slice(before).map(call => call.slice(0, 2)), [
        ['undo-preview', { baseRevision: B, receiptId: 'flr-approved' }],
    ]);
    assert.equal(undoState.layout.displayName, 'Approved');
    assert.equal(undoState.baseRevision, B);
    assert.equal(undoState.dirty, false);
    assert.equal(undoState.canUndo, false);
    assert.equal(undoState.layoutProposal.alternatives[0].ghostPreview.layout.displayName, 'Original');
    await f.session.approveAndApplyLayoutProposal();
    assert.deepEqual(f.calls.slice(before).map(call => call[0]), ['undo-preview', 'preview', 'approve', 'apply']);
    assert.equal(f.session.getState().layout.displayName, 'Original');
    assert.equal(f.session.getState().baseRevision, C);
    assert.equal(f.session.getState().canUndo, false);
    assert.equal(f.session.getState().lastApprovedOperationCommit, null);
});

test('dismissing Undo does not restore anything and allows another preview', async () => {
    const f = fixture();
    await applyExact(f);
    await f.session.undo();
    await f.session.dismissLayoutProposal();
    assert.equal(f.session.getState().layout.displayName, 'Approved');
    assert.equal(f.session.getState().canUndo, true);
    assert.equal(f.calls.filter(call => call[0] === 'apply').length, 1);
});

test('missing receipt IDs are never inferred from an older recent receipt', async () => {
    const f = fixture();
    await applyExact(f);
    f.session.load({ revision: A, layout: layout() });
    f.server.applyReceipt = () => ({ revision: B, layout: layout('Approved') });
    await applyExact(f);
    assert.deepEqual(f.session.getState().recentReceiptIds, ['flr-approved']);
    assert.equal(f.session.getState().canUndo, false);
    await f.session.undo();
    assert.equal(f.calls.some(call => call[0] === 'undo-preview'), false);
});

test('manual undo and redo remain ordinary draft operations and invalidate receipt Undo', async () => {
    const f = fixture();
    await applyExact(f);
    await f.session.renameLayout('Manual');
    await assert.rejects(f.session.requestOperationUndoPreview(), { code: 'layout_proposal_stale' });
    assert.equal(f.session.getState().canUndo, true);
    await f.session.undo();
    assert.equal(f.session.getState().layout.displayName, 'Approved');
    assert.equal(f.session.getState().dirty, false);
    assert.equal(f.session.getState().canUndo, false);
    assert.equal(f.session.getState().canRedo, true);
    await assert.rejects(f.session.requestOperationUndoPreview(), { code: 'layout_proposal_stale' });
    await f.session.redo();
    assert.equal(f.session.getState().layout.displayName, 'Manual');
    assert.equal(f.calls.some(call => call[0] === 'undo-preview'), false);
});

for (const [name, change] of [
    ['discarded manual edits', async f => { await f.session.renameLayout('Manual'); f.session.discard(); }],
    ['saved manual edits', async f => { await f.session.renameLayout('Manual'); await f.session.save(); }],
    ['another revision', f => f.session.load({ revision: C, layout: layout() })],
    ['another document at the same revision', f => f.session.load({ revision: B,
        layout: { ...layout(), layoutId: 'fl-other' } })],
]) {
    test('receipt Undo is unavailable after ' + name, async () => {
        const f = fixture();
        await applyExact(f);
        await change(f);
        assert.equal(f.session.getState().canUndo, false);
        await assert.rejects(f.session.requestOperationUndoPreview(), { code: 'layout_proposal_stale' });
        assert.equal(f.calls.some(call => call[0] === 'undo-preview'), false);
    });
}

for (const [name, mutate] of [
    ['revision', value => { value.layoutRevision = C; }],
    ['receipt', value => { value.alternatives[0].operations[0].receiptId = 'flr-other'; }],
    ['type', value => { value.alternatives[0].strategy = 'exact-operations-v1'; }],
]) {
    test('rejects undo preview with a mismatched ' + name, async () => {
        const f = fixture();
        await applyExact(f);
        f.server.undoPreview = () => { const value = proposalSet(preview(true)); mutate(value); return value; };
        await assert.rejects(f.session.undo(), { code: 'layout_proposal_stale' });
        assert.equal(f.session.getState().layout.displayName, 'Approved');
        assert.equal(f.session.getState().layoutProposal, null);
        assert.equal(f.calls.filter(call => call[0] === 'apply').length, 1);
    });
}

// Extract the shipped functions/registry entry, as the chat frontend tests do.
function implementation(name) {
    let start = html.indexOf('function ' + name + '(');
    assert.ok(start >= 0, name);
    if (html.slice(start - 6, start) === 'async ') start -= 6;
    let depth = 0;
    const body = html.indexOf('{', html.indexOf(')', start));
    for (let i = body; i < html.length; i++) {
        if (html[i] === '{') depth++;
        if (html[i] === '}' && --depth === 0) return html.slice(start, i + 1);
    }
    throw new Error('Unterminated function: ' + name);
}

function handlerFixture() {
    const f = fixture();
    const app = { session: f.session, transport: f.transport };
    const context = vm.createContext({
        _trainFacilityLayoutAuthoringApp: app, currentAgent: 'deviation-analyst',
        _trainIsFacilityLayoutMode: () => true,
        _sageFacilityEditMode: () => 'direct',
        buildAgentAttachments: () => ({ facility_layout: { siteId: 'site-a', layoutId: 'fl-a', revision: A } }),
        getAgentSession: () => ({ chatSessionId: 'chat-test' }),
        performance, console: { log() {}, error() {} },
        setTimeout: () => 0, clearTimeout: () => {}, AbortController, _newExecutionId: () => 'tool-test',
        TOOL_TIMEOUT_MS: {}, DEFAULT_TOOL_TIMEOUT_MS: 30000,
    });
    for (const name of ['_trainFacilityAgentReference', '_trainPresentCodexFacilityPreview', 'executeToolCall',
        '_facilityRuntimeActionMode', '_enforceFacilityChatToolBoundary', '_stripViewportDisruptiveToolCalls']) {
        vm.runInContext(implementation(name), context);
    }
    const start = html.indexOf('                present_codex_facility_preview: {');
    const end = html.indexOf('                build_facility_layout_preview:', start);
    assert.ok(start >= 0 && end > start);
    vm.runInContext('const TOOL_REGISTRY = {' + html.slice(start, end) + '};', context);
    const readsStart = html.indexOf('const _FACILITY_CHAT_READ_TOOLS =');
    vm.runInContext(html.slice(readsStart, html.indexOf(']);', readsStart) + 3), context);
    const dispatch = (args = reference, agent = 'deviation-analyst') => context.executeToolCall(
        { name: 'present_codex_facility_preview', args }, agent);
    return { ...f, app, context, dispatch };
}

test('actual registry allows only deviation-analyst and never accepts raw model operations', async () => {
    const f = handlerFixture();
    for (const agent of ['inspector', 'parts-finder', undefined]) {
        const result = await f.context.executeToolCall({ name: 'present_codex_facility_preview', args: reference }, agent);
        assert.equal(result.error, 'agent_not_allowed');
    }
    assert.equal((await f.dispatch({ ...reference, operations: [] })).error, 'operation_proposal_reference_required');
    assert.equal((await f.dispatch({ ...reference, layoutId: 'other' })).error, 'layout_proposal_stale');
    assert.equal(f.calls.length, 0);
    const result = await f.dispatch();
    assert.equal(result.ok, true);
    assert.equal(result.approvalRequired, true);
    assert.equal(result.saved, false);
    assert.equal(result.layoutChanged, false);
    assert.equal(f.session.getState().layoutProposal.alternatives[0].proposalId, reference.proposalId);
    assertNoWrites(f);
});

function enableDirect(f) {
    f.server.getPreview = payload => {
        const value = preview(payload.proposalId === 'flp-undo');
        Object.assign(value.alternative, { editMode: 'direct', directApplyPolicy: { eligible: true } });
        return value;
    };
    f.server.undoPreview = () => proposalSet(f.server.getPreview({ proposalId: 'flp-undo' }));
}

test('direct edit saves without a visible ghost and one Undo restores the entire batch', async () => {
    const f = fixture();
    enableDirect(f);
    const snapshots = [];
    f.session.subscribe(state => snapshots.push(state));
    await f.session.fetchAndInstallOperationProposal(reference, { applyDirectly: true });
    assert.deepEqual(f.calls.map(call => call[0]), ['preview', 'approve', 'apply']);
    assert.equal(f.calls[1][1].authorizationMode, 'direct');
    assert.equal(f.calls[1][1].explicitApproval, false);
    assert.equal(f.session.getState().layout.displayName, 'Approved');
    assert.equal(f.session.getState().canUndo, true);
    assert.equal(snapshots.some(state => state.layoutProposal), false);
    await f.session.undo();
    assert.equal(f.session.getState().layout.displayName, 'Original');
    assert.equal(f.session.getState().canUndo, false);
    assert.equal(snapshots.some(state => state.layoutProposal), false);
    assert.equal(f.calls.find(call => call[0] === 'undo-preview')[1].editMode, 'direct');
});

test('review-required and Preview First edits never auto-approve', async () => {
    for (const mode of ['preview', 'ineligible']) {
        const f = fixture();
        enableDirect(f);
        if (mode === 'ineligible') {
            const get = f.server.getPreview;
            f.server.getPreview = payload => {
                const value = get(payload);
                value.alternative.directApplyPolicy.eligible = false;
                return value;
            };
        }
        await f.session.fetchAndInstallOperationProposal(reference, { applyDirectly: mode !== 'preview' });
        assert.ok(f.session.getState().layoutProposal);
        assertNoWrites(f);
    }
});

test('direct edit rechecks cancellation and context after approval before commit', async () => {
    for (const cancel of [false, true]) {
        const f = fixture();
        enableDirect(f);
        let current = true;
        const controller = new AbortController();
        const approve = f.transport.approveLayoutProposal;
        f.transport.approveLayoutProposal = async payload => {
            const value = await approve(payload);
            if (cancel) controller.abort(); else current = false;
            return value;
        };
        // Session captures the transport options by reference.
        await assert.rejects(f.session.fetchAndInstallOperationProposal(reference,
            { applyDirectly: true, isCurrent: () => current, signal: controller.signal }));
        assert.equal(f.calls.some(call => call[0] === 'apply'), false);
        assert.equal(f.session.getState().layout.displayName, 'Original');
    }
});

test('lost commit reply retries the same token and idempotency key, never a second approval', async () => {
    const f = fixture();
    enableDirect(f);
    const apply = f.transport.applyLayoutProposal;
    let first = true;
    f.transport.applyLayoutProposal = async payload => {
        const value = await apply(payload);
        if (first) { first = false; throw new TypeError('Failed to fetch'); }
        return value;
    };
    await f.session.fetchAndInstallOperationProposal(reference, { applyDirectly: true });
    assert.equal(f.calls.filter(call => call[0] === 'approve').length, 1);
    const commits = f.calls.filter(call => call[0] === 'apply');
    assert.equal(commits.length, 2);
    assert.deepEqual(commits[0][1], commits[1][1]);
});

test('actual chat handler reports a saved direct edit and ignores its replay on a newer revision', async () => {
    const f = handlerFixture();
    enableDirect(f);
    f.context.buildAgentAttachments = () => ({ facility_layout: {
        siteId: 'site-a', layoutId: 'fl-a', revision: f.session.getState().baseRevision } });
    const result = await f.dispatch({ ...reference, editMode: 'direct' });
    assert.equal(result.saved, true);
    assert.equal(result.approvalRequired, false);
    assert.equal(result.undoAvailable, true);
    assert.equal((await f.dispatch({ ...reference, editMode: 'direct' })).error, 'layout_proposal_stale');
    assert.equal(f.calls.filter(call => call[0] === 'apply').length, 1);
});

test('actual registry rejects dirty editors before transport', async () => {
    const f = handlerFixture();
    await f.session.renameLayout('Manual');
    assert.equal((await f.dispatch()).ok, false);
    assert.equal(f.calls.some(call => call[0] === 'preview'), false);
});

for (const change of ['app', 'revision', 'site', 'mode']) {
    test('actual handler rejects a changed ' + change + ' during GET', async () => {
        const f = handlerFixture();
        const pending = deferred();
        f.server.getPreview = () => pending.promise;
        const request = f.dispatch();
        if (change === 'app') f.context._trainFacilityLayoutAuthoringApp = { ...f.app };
        if (change === 'revision') f.context.buildAgentAttachments = () => ({ facility_layout: { ...reference, revision: B } });
        if (change === 'site') f.context.buildAgentAttachments = () => ({ facility_layout: { ...reference, siteId: 'site-other' } });
        if (change === 'mode') f.context._trainIsFacilityLayoutMode = () => false;
        pending.resolve(preview());
        assert.equal((await request).error, 'layout_proposal_stale');
        assert.equal(f.session.getState().layoutProposal, null);
        assert.equal(f.session.getState().busy, false);
        assertNoWrites(f);
    });
}

test('actual PREVIEW policy keeps only the declared Codex presentation tool', () => {
    const f = handlerFixture();
    const result = f.context._enforceFacilityChatToolBoundary([
        { name: 'present_codex_facility_preview', args: reference },
        { name: 'preview_facility_move', args: {} }, { name: 'ui_actions', args: { actions: [] } },
    ], { facility_action_mode: 'PREVIEW', facility_runtime_policy: {
        allowedToolNames: ['present_codex_facility_preview'],
    } });
    assert.equal(result.mode, 'PREVIEW');
    assert.deepEqual(clone(result.toolCalls), [{ name: 'present_codex_facility_preview', args: reference }]);
});

test('HTTP undo transport sends only the exact receipt/revision to the scoped preview route', async () => {
    const calls = [];
    const signal = new AbortController().signal;
    const transport = Transport.createHttpTransport({ siteId: 'site a', layoutId: 'layout/one',
        fetch: async (url, init) => { calls.push({ url, init });
            return { ok: true, status: 200, json: async () => proposalSet(preview(true)) }; } });
    await transport.createOperationUndoPreview({ baseRevision: B, receiptId: 'flr-approved', operations: [] }, { signal });
    assert.equal(calls[0].url, '/api/facility-layouts/site%20a/layout%2Fone/operation-undo-preview');
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(calls[0].init.signal, signal);
    assert.equal(calls[0].init.credentials, 'same-origin');
    assert.deepEqual(JSON.parse(calls[0].init.body), { baseRevision: B, receiptId: 'flr-approved' });
    assert.throws(() => transport.createOperationUndoPreview({ baseRevision: B }), /receiptId/);
    assert.equal(calls.length, 1);
});

function appFixture(f) {
    return App.createFacilityLayoutApp({ root: { ownerDocument: {} },
        siteId: 'site-a', layoutId: 'fl-a', transport: f.transport,
        initialReceipt: { revision: A, layout: layout() },
        transportRuntime: Transport, sessionRuntime: Session, layoutRuntime: {},
        enableSpatialAdvisory: false,
        workspaceRuntime: { createWorkspace: () => ({ getState: () => ({}), suspend() {}, resume() {}, destroy() {} }) },
    });
}

test('app wires the real session through approved edit and Undo preview', async () => {
    const f = fixture();
    const app = appFixture(f);
    await app.ready;
    await applyExact({ ...f, session: app.session });
    await app.session.undo();
    assert.equal(f.calls.at(-1)[0], 'undo-preview');
    assert.equal(app.session.getState().layoutProposal.alternatives[0].strategy, 'exact-undo-v1');
    app.destroy();
});

test('existing Undo and proposal controls require explicit approval and remain visible while busy', async () => {
    const f = fixture();
    function element(attributes = {}) {
        return { disabled: false, hidden: true, textContent: '',
            getAttribute: key => attributes[key] || null,
            setAttribute: (key, value) => { attributes[key] = value; },
            removeAttribute: key => { delete attributes[key]; },
            querySelector: () => null };
    }
    const undoButton = element({ 'data-command': 'undo' });
    const candidates = Object.fromEntries(['accept', 'dismiss', 'previous', 'next'].map(action =>
        [action, element({ 'data-candidate-action': action })]));
    const w = Object.assign(Object.create(Workspace.prototype), {
        session: f.session, state: f.session.getState(), options: {},
        capabilities: { manualAuthoring: true },
        _canEditAppearance: () => false, _selectedPlacementRecords: () => [], _layoutContentCount: () => 0,
        toolbar: { querySelector: selector => selector === '[data-command="undo"]' ? undoButton : null,
            querySelectorAll: () => [undoButton] },
        candidateControls: element(), candidateSummary: element(), validationNotice: element(),
        proposalReview: element(), proposalChangeText: element(), proposalBindingText: element(),
        proposalDiagnosticText: element(),
        _invoke(_label, action) { this.pending = Promise.resolve(action()); return this.pending; },
    });
    w.candidateControls.querySelector = selector => candidates[selector.match(/="([^"]+)"/)[1]];
    for (const name of ['assetBrowser', 'pattern', 'planSettings', 'bulkZone', 'cellGroup', 'aisle',
        'navigation', 'clearAll', 'precision']) w[name + 'State'] = { open: false };
    f.session.subscribe(state => {
        w.state = state;
        w._renderToolbarState();
        w._renderCandidateControls();
    });
    const click = action => w._handleCandidateAction({ target: candidates[action] });
    await f.session.fetchAndInstallOperationProposal(reference);
    assert.equal(w.candidateControls.hidden, false);
    assert.equal(candidates.accept.textContent, 'Approve');
    assert.equal(candidates.accept.disabled, false);
    assertNoWrites(f);
    click('accept');
    assert.equal(w.candidateControls.hidden, false);
    assert.equal(candidates.accept.disabled, true);
    await w.pending;
    assert.equal(undoButton.disabled, false);
    assert.equal(w.candidateControls.hidden, true);

    const deferredUndo = deferred();
    f.server.undoPreview = () => deferredUndo.promise;
    const request = w.executeCommand('undo');
    assert.equal(undoButton.disabled, true);
    deferredUndo.resolve(proposalSet(preview(true)));
    await request;
    assert.equal(w.candidateControls.hidden, false);
    assert.equal(candidates.accept.disabled, false);
    assert.equal(undoButton.disabled, true);
    assert.equal(w.state.layout.displayName, 'Approved');
    assert.equal(f.calls.filter(call => call[0] === 'apply').length, 1);
    click('accept');
    const whileBusy = w.pending;
    assert.equal(w.candidateControls.hidden, false);
    assert.equal(candidates.accept.disabled, true);
    click('accept');
    assert.equal(w.pending, whileBusy);
    await whileBusy;
    assert.equal(w.state.layout.displayName, 'Original');
    assert.equal(w.candidateControls.hidden, true);
    assert.equal(undoButton.disabled, true);
    assert.equal(f.calls.filter(call => call[0] === 'apply').length, 2);
});

for (const lifecycle of ['suspend', 'destroy']) {
    test('app ' + lifecycle + ' rejects an in-flight operation or Undo preview', async () => {
        for (const undo of [false, true]) {
            const f = fixture();
            const app = appFixture(f);
            await app.ready;
            if (undo) await applyExact({ ...f, session: app.session });
            const pending = deferred();
            if (undo) f.server.undoPreview = () => pending.promise;
            else f.server.getPreview = () => pending.promise;
            const request = undo ? app.session.undo() : app.session.fetchAndInstallOperationProposal(reference);
            app[lifecycle]();
            pending.resolve(undo ? proposalSet(preview(true)) : preview());
            await assert.rejects(request, { code: 'layout_proposal_stale' });
            assert.equal(app.session.getState().layoutProposal, null);
            assert.equal(app.session.getState().busy, false);
            assert.equal(app.session.getState().canUndo, false);
            app.destroy();
        }
    });
}
