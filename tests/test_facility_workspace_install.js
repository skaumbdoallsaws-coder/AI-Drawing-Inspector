'use strict';

const assert = require('node:assert/strict');
const { fixture } = require('./facility_workspace_install_harness.js');

async function scenario(baseline, review, count = 32) {
    const f = await fixture(baseline, count, count > 32 ? 'digest' : true);
    const snapshots = [];
    try {
        f.setDirect(!review);
        f.session.selectMany(['placement-0', 'placement-1', 'zone-0', 'marking-0']);
        snapshots.push(f.snapshot());
        const commit = await f.measure(f.commit);
        snapshots.push(f.snapshot());
        if (review) {
            await f.session.approveAndApplyLayoutProposal();
            snapshots.push(f.snapshot());
        }
        const undo = await f.measure(f.undo);
        snapshots.push(f.snapshot());
        if (review) {
            await f.session.approveAndApplyLayoutProposal();
            snapshots.push(f.snapshot());
        }
        if (!baseline) {
            assert.equal(commit.renders, 1, 'commit or preview renders once');
            assert.equal(undo.renders, 1, 'Undo or Undo preview renders once');
            assert.equal(commit.stages['session.normalizeLayoutAlternative'].calls, 1);
            assert.equal(commit.stages['editor.collectTopPlanGeometry'].calls, 1);
        }
        return snapshots;
    } finally { f.dispose(); }
}

async function historyScenario(baseline) {
    const f = await fixture(baseline, 8, true);
    try {
        const result = [];
        f.session.selectMany(['placement-0']);
        await f.session.renameLayout('Local draft');
        result.push(f.snapshot());
        await f.session.undo();
        result.push(f.snapshot());
        await f.session.redo();
        result.push(f.snapshot());
        return result;
    } finally { f.dispose(); }
}

async function replacementScenario(baseline) {
    const f = await fixture(baseline, 8, true);
    try {
        f.session.selectMany(['placement-0', 'placement-1', 'zone-0', 'marking-0']);
        f.session.beginGhostPlacement({ assetId: 'asset-0', assetDefinitionRevision: 'asset-rev-0',
            worldPosition: { x: 4, y: 0, z: 4 } });
        const layout = JSON.parse(JSON.stringify(f.layout));
        layout.placements.shift();
        layout.zones.shift();
        layout.floorMarkings.shift();
        layout.extensions.facilityPlan = { widthMeters: 400, depthMeters: 200,
            gridSpacingMeters: 2, majorGridSpacingMeters: 10 };
        const result = await f.measure(() => f.session.load({ revision: 'e'.repeat(64), layout }));
        if (!baseline) assert.equal(result.renders, 1, 'layout, environment, selection and ghost clear render together');
        return f.snapshot();
    } finally { f.dispose(); }
}

async function main() {
    for (const review of [false, true]) {
        const before = await scenario(true, review);
        const after = await scenario(false, review);
        assert.deepEqual(after, before, (review ? 'review' : 'direct')
            + ' commit and Undo preserve state, history, SVG, 3D inputs and events');
        console.log('PASS ' + (review ? 'review' : 'direct') + ' commit + Undo match c476a2f');
    }
    assert.deepEqual(await historyScenario(false), await historyScenario(true));
    console.log('PASS local draft, Undo and Redo match c476a2f');
    assert.deepEqual(await replacementScenario(false), await replacementScenario(true));
    console.log('PASS changed environment, removed selection and ghost clear match c476a2f');
    assert.deepEqual(await scenario(false, false, 2250), await scenario(true, false, 2250));
    console.log('PASS Factory-scale commit + Undo match c476a2f (SHA-256 of every snapshot field and event)');

    const f = await fixture(false, 8);
    try {
        const states = [];
        f.session.subscribe(state => {
            states.push(state.busy);
            assert.equal(f.workspace.state.busy, state.busy);
            assert.equal(f.workspace.root.getAttribute('aria-busy'), String(state.busy));
            if (state.busy) assert.throws(() => f.session.load({}), /busy/);
        });
        f.setFailure(true);
        const renders = f.top.renderCount;
        await assert.rejects(f.commit(), /Synthetic failure/);
        assert.deepEqual(states, [true, false]);
        assert.equal(f.top.renderCount, renders, 'busy and error updates do not render the plan');
        assert.match(f.workspace.statusText.textContent, /Synthetic failure/);
        console.log('PASS busy guards and failure status remain synchronous without plan renders');

        f.top.beginUpdate();
        f.top.beginUpdate();
        f.top.setSelections(['placement-0', 'zone-0']);
        f.top.endUpdate();
        assert.equal(f.top.renderCount, renders);
        f.top.endUpdate();
        assert.equal(f.top.renderCount, renders + 1);
        f.top.setSelections(['placement-0', 'zone-0']);
        f.top.setGhostPlacement(null);
        assert.equal(f.top.renderCount, renders + 1, 'unchanged selection and empty ghost are no-ops');
        f.top.setSelections(['zone-0', 'placement-0']);
        assert.equal(f.top.selection, 'zone-0', 'selection order remains meaningful');
        console.log('PASS nested plan transactions and selection ordering');

        f.session.beginGhostPlacement({ assetId: 'asset-0', assetDefinitionRevision: 'asset-rev-0',
            worldPosition: { x: 4, y: 0, z: 4 } });
        const ghostRenders = f.top.renderCount;
        await assert.rejects(f.commit(), /Synthetic failure/);
        assert.equal(f.top.renderCount, ghostRenders, 'busy leaves the unchanged ghost visible without rebuilding');
        console.log('PASS busy updates preserve a visible ghost without rendering');

        const controllerLayout = JSON.stringify(f.workspace.controller.layout);
        f.top.layout.placements[0].metadata.instanceLabel = 'Plan-only mutation';
        assert.equal(JSON.stringify(f.workspace.controller.layout), controllerLayout);
        assert.notEqual(f.session.getState().layout.placements[0].metadata.instanceLabel, 'Plan-only mutation');
        const setLayout = f.top.setLayout;
        f.top.setLayout = function (layout) {
            layout.displayName = 'Custom adapter mutation';
            return setLayout.call(this, layout);
        };
        f.workspace.controller._notifyLayout();
        assert.equal(JSON.stringify(f.workspace.controller.layout), controllerLayout,
            'overridden adapters still receive a defensive copy');
        f.top.setLayout = setLayout;
        f.top.beginUpdate();
        f.top.fit();
        const replacement = JSON.parse(JSON.stringify(f.layout));
        replacement.placements[0].transform.position.x += 20;
        f.top.setLayout(replacement);
        f.top.fit();
        f.top.endUpdate();
        assert.deepEqual(f.top.geometry, f.runtime.editor.collectTopPlanGeometry(replacement, f.top.options),
            'a second document in the transaction invalidates cached geometry');
        console.log('PASS plan, controller and session retain separate document ownership');
    } finally { f.dispose(); }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
