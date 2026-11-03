'use strict';

// Real session, workspace, controller and SVG renderer; only the DOM and 3D sink
// are test doubles. No browser, network, private layouts or installed packages.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const { createHash } = require('node:crypto');
const ROOT = path.resolve(__dirname, '..');
const BASELINE = 'c476a2f'; // These three modules are unchanged through fb59e2c.
const clone = value => JSON.parse(JSON.stringify(value));

function testDocument() {
    // Reuse the workspace suite's DOM without running its tests or fixtures.
    const source = fs.readFileSync(path.join(__dirname, 'test_facility_layout_workspace.js'), 'utf8');
    const dom = source.slice(source.indexOf('function selectorMatcher('), source.indexOf('class FakeSurfaceManager'));
    const Document = vm.runInThisContext('(function () {\n' + dom + '\nreturn FakeDocument; })()');
    const document = new Document();
    document.createElementNS = (namespace, name) => document.createElement(name);
    return document;
}

function syntheticLayout(count = 2250) {
    const catalog = Array.from({ length: 230 }, (_, i) => ({
        assetId: 'asset-' + i, assetDefinitionRevision: 'asset-rev-' + i,
        displayName: 'Synthetic machine ' + i,
        definition: { geometry: { aabb: { minimum: { x: -1, y: 0, z: -1 },
            maximum: { x: 1, y: 2, z: 1 } } } },
    }));
    const rectangle = (x, z, w, d) => [{ x, z }, { x: x + w, z },
        { x: x + w, z: z + d }, { x, z: z + d }];
    const layout = {
        schemaVersion: 1, layoutId: 'synthetic-factory', displayName: 'Synthetic factory',
        association: { siteId: 'synthetic-site' },
        placements: Array.from({ length: count }, (_, i) => ({
            placementId: 'placement-' + i, assetId: catalog[i % 230].assetId,
            assetDefinitionRevision: catalog[i % 230].assetDefinitionRevision,
            transform: { position: { x: 3 + (i % 75) * 4, y: 0, z: 3 + Math.floor(i / 75) * 4 },
                quaternion: { x: 0, y: 0, z: 0, w: 1 }, scale: 1 },
            positionMode: 'manual', metadata: { instanceLabel: 'Machine ' + i,
                // Realistic document payload without any private asset data.
                notes: 'Synthetic manufacturing evidence. '.repeat(80) },
        })),
        zones: Array.from({ length: 40 }, (_, i) => ({ zoneId: 'zone-' + i,
            zoneType: 'workcell', label: 'Department ' + i,
            boundary: rectangle((i % 8) * 40, Math.floor(i / 8) * 26, 40, 26) })),
        floorMarkings: Array.from({ length: 300 }, (_, i) => ({ markingId: 'marking-' + i,
            markingType: 'direction_arrow', label: 'Flow ' + i, width: 1, depth: 2,
            transform: { position: { x: (i % 50) * 6, y: 0, z: Math.floor(i / 50) * 20 },
                rotationDegrees: 90 } })),
        routes: [], extensions: {},
    };
    return { layout, catalog };
}

function profiler() {
    let rows = {}, stack = [], enabled = false;
    return {
        reset() { rows = {}; stack = []; enabled = true; },
        stop() { enabled = false; return rows; },
        measure(name, action) {
            if (!enabled) return action();
            const frame = { start: performance.now(), children: 0 };
            stack.push(frame);
            try { return action(); } finally {
                const elapsed = performance.now() - frame.start;
                stack.pop();
                if (stack.length) stack[stack.length - 1].children += elapsed;
                const row = rows[name] || (rows[name] = { calls: 0, ms: 0, selfMs: 0 });
                row.calls++;
                row.ms += elapsed;
                row.selfMs += elapsed - frame.children;
            }
        },
    };
}

function loadRuntime(baseline, profile) {
    const cache = new Map();
    const names = ['session', 'workspace', 'editor'];
    function load(name) {
        if (cache.has(name)) return cache.get(name);
        const file = 'static/facility_layout_' + name + '.js';
        const gitArgs = ['show', BASELINE + ':' + file];
        let source = baseline ? execFileSync(process.platform === 'win32' ? 'pythonw.exe' : 'git',
            process.platform === 'win32' ? [path.join(ROOT, 'tools/run_hidden.pyw'), 'git', ...gitArgs] : gitArgs,
            { cwd: ROOT, windowsHide: true, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 })
            : fs.readFileSync(path.join(ROOT, file), 'utf8');
        const functions = name === 'session'
            ? ['clone', 'getState', 'normalizeLayoutAlternative', 'installReceipt', 'setBusy']
            : name === 'workspace' ? ['clone', 'normalizeCatalog']
                : ['clone', 'collectTopPlanGeometry', 'collectTopPlanBounds'];
        for (const fn of functions) {
            const label = fn === 'setBusy' ? '"session.busy." + args[0]' : '"' + name + '.' + fn + '"';
            source = source.replace('function ' + fn + '(',
                'function ' + fn + '(...args) { return __profile.measure(' + label
                + ', () => ' + fn + 'Measured(...args)); }\n    function ' + fn + 'Measured(');
        }
        const module = { exports: {} };
        const nativeRequire = createRequire(path.join(ROOT, file));
        const requireModule = spec => {
            const match = spec.match(/^\.\/facility_layout_(session|workspace|editor)\.js$/);
            return match ? load(match[1]) : nativeRequire(spec);
        };
        class FixedDate extends Date { static now() { return 1800000000000; } }
        vm.runInThisContext('(function(require, module, exports, __profile, Date) {\n' + source + '\n})',
            { filename: (baseline ? BASELINE + '/' : '') + file })(requireModule, module, module.exports, profile, FixedDate);
        cache.set(name, module.exports);
        return module.exports;
    }
    const runtime = Object.fromEntries(names.map(name => [name, load(name)]));
    function wrap(prototype, methods, prefix) {
        for (const method of methods) {
            const original = prototype[method];
            prototype[method] = function (...args) {
                return profile.measure(prefix + '.' + method, () => original.apply(this, args));
            };
        }
    }
    wrap(runtime.workspace.Workspace.prototype, ['_handleSessionState', '_syncController'], 'workspace');
    wrap(runtime.editor.FacilityLayoutEditorController.prototype, ['setLayout', '_notifyLayout'], 'controller');
    wrap(runtime.editor.TopPlanAdapter.prototype, ['_render'], 'plan');
    return runtime;
}

async function fixture(baseline = false, count = 2250, capture = false) {
    const profile = profiler();
    const runtime = loadRuntime(baseline, profile);
    const { layout, catalog } = syntheticLayout(count);
    const edited = clone(layout);
    edited.placements[0].transform.position.x += 1;
    const A = 'a'.repeat(64), B = 'b'.repeat(64), C = 'c'.repeat(64);
    const reference = { siteId: layout.association.siteId, layoutId: layout.layoutId,
        revision: A, proposalId: 'proposal-edit' };
    let approvedId, direct = true, failed = false;
    const events = [], scenes = [], selections = [], structureEvents = [], commands = [];
    const captureValue = value => capture === 'digest'
        ? createHash('sha256').update(JSON.stringify(value) || 'undefined').digest('hex') : clone(value);
    function preview(undo = false) {
        const binding = { target: { domain: 'facility-layout', scopeId: 'fls:' + '9'.repeat(64),
            resourceId: layout.layoutId }, baseRevision: undo ? B : A,
            diffHash: 'd'.repeat(64), dependencyFingerprint: 'e'.repeat(64) };
        return { proposalId: undo ? 'proposal-undo' : 'proposal-edit', previewPure: true,
            transactionBinding: binding, createdAt: 1800000000, expiresAt: 1800003600,
            alternative: { alternativeId: undo ? 'undo' : 'edit',
                strategy: undo ? 'exact-undo-v1' : 'exact-operations-v1',
                editMode: direct ? 'direct' : 'preview', directApplyPolicy: { eligible: direct },
                operations: undo ? [{ op: 'restore_approved_revision', receiptId: 'receipt-edit' }]
                    : [{ op: 'move_placement', placementId: 'placement-0', position: edited.placements[0].transform.position }],
                ghostPreview: { layout: undo ? layout : edited }, transactionBinding: binding } };
    }
    const transport = {
        createIdempotencyKey: () => 'synthetic-key',
        async previewOperations(payload) {
            const draft = clone(layout);
            payload.operations.forEach(op => { if (op.op === 'rename_layout') draft.displayName = op.displayName; });
            return { revision: payload.operations.length ? B : A, layout: draft };
        },
        async applyOperations() { return { revision: B, layout: edited }; },
        async getLayoutProposalPreview(payload) { if (failed) throw new Error('Synthetic failure'); return preview(payload.proposalId === 'proposal-undo'); },
        async createOperationUndoPreview() {
            const value = preview(true);
            return { layoutRevision: B, previewPure: true, selectedProposalId: value.proposalId,
                alternatives: [{ ...value.alternative, proposalId: value.proposalId,
                    createdAt: value.createdAt, expiresAt: value.expiresAt }] };
        },
        async approveLayoutProposal(payload) { approvedId = payload.proposalId; return { approvalToken: 'synthetic-approval' }; },
        async applyLayoutProposal() {
            const undo = approvedId === 'proposal-undo';
            return { receiptId: undo ? 'receipt-undo' : 'receipt-edit', revision: undo ? C : B,
                layout: undo ? layout : edited };
        },
        async cancelLayoutProposal() { return {}; },
    };
    const session = runtime.session.createSession(transport);
    session.load({ revision: A, layout });
    const document = testDocument();
    const three = {
        setScene(value) { if (capture) scenes.push(captureValue(value)); this.scene = clone(value); return Promise.resolve(); },
        setSelection(value) { if (capture) selections.push(captureValue(value)); this.selection = clone(value); },
        setProposalPreview(value) { this.preview = clone(value); },
        setGhostPlacement() {},
        fit() {},
    };
    const workspace = runtime.workspace.createWorkspace({
        root: document.createElement('div'), session, layoutRuntime: runtime.editor,
        assetCatalog: catalog, threeAdapter: three, externalCommandSurface: true,
        onStateChange(state) { if (capture) events.push(captureValue(state)); },
        onCommandStateChange(state) { if (capture) commands.push(captureValue(state)); },
    });
    workspace.subscribeStructure(() => { if (capture) structureEvents.push(captureValue(workspace.structureSource())); });
    const top = workspace.topAdapter;
    const serialize = node => ({ name: node.nodeName, attributes: node.attributes,
        text: node.textContent, children: node.children.map(serialize) });
    function snapshot() {
        const controller = workspace.controller.getState();
        // Render counts are the deliberately changed diagnostic, not document
        // state. Assert them separately while comparing every other field.
        delete controller.diagnostics.renderCount;
        controller.diagnostics.views.forEach(view => { delete view.renderCount; });
        const value = { state: session.getState(), workspaceState: workspace.state,
            controller, plan: serialize(top.svg),
            planLayout: top.layout, planSelection: [top.selection, Array.from(top.selections)],
            threeScene: three.scene, threeSelection: three.selection, threePreview: three.preview,
            status: workspace.statusText.textContent, busy: workspace.root.getAttribute('aria-busy'),
            commands: workspace.commandStates, events, scenes, selections, structureEvents, commandEvents: commands };
        return capture === 'digest' ? Object.fromEntries(Object.entries(value).map(([key, item]) =>
            [key, captureValue(item)])) : clone(value);
    }
    async function measure(action) {
        const renders = top.renderCount;
        profile.reset();
        const start = performance.now();
        await action();
        const ms = performance.now() - start;
        const stages = profile.stop();
        return { ms, renders: top.renderCount - renders, stages };
    }
    return { session, workspace, runtime, top, three, profile, reference, layout, edited, snapshot, measure,
        setDirect(value) { direct = value; }, setFailure(value) { failed = value; },
        commit: () => session.fetchAndInstallOperationProposal(reference, { applyDirectly: direct }),
        undo: () => session.requestOperationUndoPreview({ applyDirectly: direct }),
        dispose: () => workspace.destroy(),
    };
}

module.exports = { fixture, BASELINE, syntheticLayout };
