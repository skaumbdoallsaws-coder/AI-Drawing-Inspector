'use strict';

const assert = require('assert');
const App = require('../static/facility_layout_app.js');

const tests = [];
function test(name, fn) { tests.push({ name, fn }); }

function rootElement() {
    return { ownerDocument: {}, marker: 'host' };
}

function fixture() {
    const calls = [];
    const receipt = {
        revision: 'a'.repeat(64),
        layout: {
            layoutId: 'fl-a',
            placements: [],
            zones: [],
        },
    };
    const transport = {
        previewOperations: async () => ({}),
        applyOperations: async () => ({}),
        placementCandidates: async () => ({}),
        placementCandidatePreview: async () => ({}),
        createLayoutProposals: async () => ({}),
        getLayoutProposalPreview: async () => ({}),
        cancelLayoutProposal: async () => ({}),
        approveLayoutProposal: async () => ({}),
        applyLayoutProposal: async () => ({}),
        getLayoutReceipt: async () => ({}),
        reloadLayout: async () => {
            calls.push('reload');
            return receipt;
        },
    };
    const session = {
        load(value) { calls.push(['load', value]); },
    };
    const workspace = {
        getState: () => ({ viewMode: 'plan' }),
        suspend: () => { calls.push('suspend'); return true; },
        resume: root => { calls.push(['resume', root]); return true; },
        destroy: () => { calls.push('destroy'); },
    };
    const options = {
        root: rootElement(),
        siteId: 'site-a',
        layoutId: 'fl-a',
        assetCatalog: [{ assetId: 'asset-a' }],
        transport,
        session,
        transportRuntime: {},
        sessionRuntime: {},
        layoutRuntime: {},
        workspaceRuntime: {
            createWorkspace(value) {
                calls.push(['workspace', value]);
                return workspace;
            },
        },
    };
    return { options, calls, receipt, session, workspace };
}

test('loads canonical receipt before mounting one shared workspace', async () => {
    const value = fixture();
    const app = App.createFacilityLayoutApp(value.options);
    await app.ready;
    assert.strictEqual(value.calls[0], 'reload');
    assert.deepStrictEqual(value.calls[1], ['load', value.receipt]);
    assert.strictEqual(value.calls[2][0], 'workspace');
    assert.strictEqual(value.calls[2][1].session, value.session);
    assert.strictEqual(value.calls[2][1].assetCatalog, value.options.assetCatalog);
    assert.strictEqual(app.getState().loaded, true);
    assert.strictEqual(app.getState().workspace.viewMode, 'plan');
});

test('accepts an initial receipt without a read request', async () => {
    const value = fixture();
    value.options.initialReceipt = value.receipt;
    const app = App.createFacilityLayoutApp(value.options);
    await app.ready;
    assert.deepStrictEqual(value.calls.map(item => (
        Array.isArray(item) ? item[0] : item
    )), ['load', 'workspace']);
});

test('suspend and resume preserve the loaded app until final destroy', async () => {
    const value = fixture();
    const nextRoot = rootElement();
    nextRoot.marker = 'next-host';
    const app = App.createFacilityLayoutApp(value.options);
    await app.ready;
    assert.strictEqual(app.suspend(), true);
    assert.strictEqual(app.suspend(), false);
    assert.strictEqual(app.getState().suspended, true);
    assert.strictEqual(app.resume(nextRoot), true);
    assert.strictEqual(app.resume(nextRoot), false);
    assert.strictEqual(app.getState().suspended, false);
    assert.ok(value.calls.includes('suspend'));
    assert.deepStrictEqual(
        value.calls.find(item => Array.isArray(item) && item[0] === 'resume'),
        ['resume', nextRoot]
    );
    assert.strictEqual(app.destroy(), true);
    assert.ok(value.calls.includes('destroy'));
});

test('destroy is idempotent and prevents late workspace mount', async () => {
    const value = fixture();
    let resolveReload;
    value.options.transport.reloadLayout = () => new Promise(resolve => {
        resolveReload = resolve;
    });
    let reportedErrors = 0;
    value.options.onError = () => { reportedErrors += 1; };
    const app = App.createFacilityLayoutApp(value.options);
    await Promise.resolve();
    assert.strictEqual(app.destroy(), true);
    assert.strictEqual(app.destroy(), false);
    resolveReload(value.receipt);
    await assert.rejects(app.ready, error => {
        assert.strictEqual(error.name, 'AbortError');
        assert.strictEqual(error.code, 'facility_layout_app_destroyed');
        return true;
    });
    assert.strictEqual(reportedErrors, 0);
    assert.strictEqual(app.getState().loadReceipt, null);
    assert.strictEqual(value.calls.some(item => (
        Array.isArray(item) && item[0] === 'workspace'
    )), false);
});

test('wires proposal transports and owned advisory into the workspace', async () => {
    const value = fixture();
    const advisorCalls = [];
    const advisor = {
        getState: () => ({ activeRequestId: null }),
        destroy: () => {
            advisorCalls.push('destroy');
            return true;
        },
    };
    let sessionConfig = null;
    value.options.session = null;
    value.options.sessionRuntime = {
        createSession(config) {
            sessionConfig = config;
            return value.session;
        },
    };
    value.options.spatialAdvisorRuntime = {
        createSpatialAdvisor() {
            advisorCalls.push('create');
            return advisor;
        },
    };
    const app = App.createFacilityLayoutApp(value.options);
    await app.ready;
    assert.strictEqual(
        sessionConfig.placementCandidates,
        value.options.transport.placementCandidates
    );
    assert.strictEqual(
        sessionConfig.placementCandidatePreview,
        value.options.transport.placementCandidatePreview
    );
    [
        'createLayoutProposals',
        'getLayoutProposalPreview',
        'cancelLayoutProposal',
        'approveLayoutProposal',
        'applyLayoutProposal',
        'getLayoutReceipt',
    ].forEach(name => {
        assert.strictEqual(
            sessionConfig[name],
            value.options.transport[name]
        );
    });
    const workspaceOptions = value.calls.find(
        item => Array.isArray(item) && item[0] === 'workspace'
    )[1];
    assert.strictEqual(workspaceOptions.spatialAdvisor, advisor);
    assert.deepStrictEqual(app.getState().spatialAdvisor, {
        activeRequestId: null,
    });
    app.destroy();
    assert.deepStrictEqual(advisorCalls, ['create', 'destroy']);
});

(async () => {
    let passed = 0;
    for (const item of tests) {
        try {
            await item.fn();
            passed += 1;
            console.log('ok - ' + item.name);
        } catch (error) {
            console.error('not ok - ' + item.name);
            throw error;
        }
    }
    console.log('Facility layout app tests: ' + passed + '/' + tests.length
        + ' passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
