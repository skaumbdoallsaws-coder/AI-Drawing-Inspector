'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const { blankLayout, sameCreatedLayout, createSheets, savedLayoutOptions } = require('../static/facility_layout_sheets');
const { createHttpTransport } = require('../static/facility_layout_transport');
const source = {
    schemaVersion: 1, layoutId: 'fl-source', displayName: 'Manual',
    association: { siteId: 'site-local', areaId: 'main' }, coordinateFrame: { units: 'm' },
    sourceShellRef: { shellId: 'shell-1', shellRevision: 'a'.repeat(64) },
    policySetRef: { policySetId: 'policy-1', policySetRevision: 'b'.repeat(64) },
    placements: [{ placementId: 'existing' }], zones: [{ zoneId: 'zone-existing' }],
    extensions: { facilityPlan: { widthMeters: 100 }, navigation: { inherited: 'forbidden' } },
};
const clone = x => JSON.parse(JSON.stringify(x));
test('rename updates only the intended draft and the sheet/tree summary', async () => {
    const f = fixture(); await f.controller.addBlank();
    await f.controller.rename('fl-test-1', 'Assembly', 'draft-1');
    assert.equal(f.controller.state().layouts[1].displayName, 'Assembly');
    assert.equal(f.controller.state().layouts[1].dirty, true);
    assert.equal(f.docs.get('fl-test-1').layout.displayName, 'Layout 1');
    assert.equal(f.first.state.layout.displayName, 'Manual');
    await assert.rejects(f.controller.rename('fl-test-1', 'Stale', 'draft-1'), /changed/);
});
test('delete archives the saved sheet, discards its confirmed local edits, and preserves the fallback exactly', async () => {
    const f = fixture(); f.first.state.dirty = true; const before = clone(f.first.state);
    await f.controller.addBlank(); const deleted = f.controller.apps()[1];
    await f.controller.rename('fl-test-1', 'Unsaved', 'draft-1');
    await f.controller.remove('fl-test-1', deleted.state.draftRevision);
    assert.equal(f.controller.state().activeId, source.layoutId);
    assert.equal(f.docs.get('fl-test-1').layout.status, 'archived');
    assert.equal(deleted.state.destroyed, true);
    assert.deepEqual(f.first.state, before);
    assert.equal(f.controller.state().layouts.length, 1);
    deleted.notify(); assert.equal(f.controller.state().layouts.length, 1);
    await f.controller.refresh(); assert.equal(f.controller.state().availableLayouts.length, 1);
});
test('deleting an inactive sheet does not switch the current view', async () => {
    const f = fixture(); await f.controller.addBlank(); await f.controller.addBlank();
    await f.controller.remove('fl-test-1', 'draft-1');
    assert.equal(f.controller.state().activeId, 'fl-test-2');
});
test('last open sheet cannot be removed', async () => {
    const f = fixture(); await assert.rejects(f.controller.remove(source.layoutId, 'draft-1'), /at least one/);
    assert.equal(f.calls.archives, 0);
});
test('stale, busy, proposal, preview and read-only deletion are refused before transport', async () => {
    const f = fixture(); await f.controller.addBlank(); const target = f.controller.apps()[1];
    await assert.rejects(f.controller.remove('fl-test-1', 'old'), /changed/);
    for (const [key, value] of [['busy', true], ['designAuthorityState', 'pending'], ['generatedDraft', {}], ['designProposalDraft', {}]]) {
        const old = target.state[key]; target.state[key] = value;
        await assert.rejects(f.controller.remove('fl-test-1', 'draft-1'), /Finish/);
        target.state[key] = old;
    }
    const readonly = fixture({ canCreate: () => false });
    readonly.controller.register(app(blankLayout(source, 'fl-other', 'Other')));
    await assert.rejects(readonly.controller.remove('fl-other', 'draft-1'), /not enabled/);
    const preview = fixture({ assertEditable: () => { throw new Error('preview'); } });
    await preview.controller.addBlank();
    await assert.rejects(preview.controller.remove('fl-test-1', 'draft-1'), /preview/);
    assert.equal(f.calls.archives + readonly.calls.archives + preview.calls.archives, 0);
});
test('a definitive archive rejection preserves local edits and releases the session', async () => {
    const f = fixture(); await f.controller.addBlank(); const target = f.controller.apps()[1];
    target.state.dirty = true; const before = clone(target.state);
    f.transport.archiveLayout = async () => { throw Object.assign(new Error('revision conflict'), { status: 409 }); };
    await assert.rejects(f.controller.remove('fl-test-1', 'draft-1'), /revision conflict/);
    assert.deepEqual(target.state, before);
    assert.equal(f.controller.state().layouts.length, 2);
    assert.equal(f.controller.observation().pending, false);
});
test('lost archive acknowledgment reconciles exact saved contents without saving the dirty draft', async () => {
    const f = fixture(); await f.controller.addBlank(); const archive = f.transport.archiveLayout;
    f.transport.archiveLayout = async id => { await archive(id); throw new Error('lost reply'); };
    await f.controller.rename('fl-test-1', 'Local name', 'draft-1');
    await f.controller.remove('fl-test-1', 'draft-1-renamed');
    assert.equal(f.calls.archives, 1); assert.equal(f.controller.state().layouts.length, 1);
    assert.equal(f.docs.get('fl-test-1').layout.displayName, 'Layout 1');
});
test('unknown archive outcome retains the recovery handle and lock until retry', async () => {
    const f = fixture(); await f.controller.addBlank(); const target = f.controller.apps()[1];
    const archive = f.transport.archiveLayout, get = f.transport.getLayout;
    f.transport.archiveLayout = async id => { await archive(id); throw new Error('lost reply'); };
    f.transport.getLayout = async () => { throw new Error('offline'); };
    await assert.rejects(f.controller.remove('fl-test-1', 'draft-1'), /Retry Delete/);
    assert.equal(target.state.busy, true); assert.equal(f.controller.observation().pending, true);
    assert.equal(f.controller.state().layouts.length, 2);
    f.transport.archiveLayout = async () => { throw Object.assign(new Error('already advanced'), { status: 409 }); };
    f.transport.getLayout = get;
    await f.controller.remove('fl-test-1', 'draft-1');
    assert.equal(f.calls.archives, 1);
    assert.equal(f.controller.observation().pending, false);
    assert.equal(f.controller.state().layouts.length, 1);
});
test('replacement mount failure retains archived-sheet recovery and does not archive again on retry', async () => {
    let fail = false;
    const f = fixture({ activate: async ({ retained, receipt }) => { if (fail) throw new Error('mount'); return retained || app(receipt.layout); } });
    await f.controller.addBlank(); fail = true;
    await assert.rejects(f.controller.remove('fl-test-1', 'draft-1'), /mount/);
    assert.equal(f.controller.observation().pending, true);
    fail = false; await f.controller.remove('fl-test-1', 'draft-1');
    assert.equal(f.calls.archives, 1); assert.equal(f.controller.state().layouts.length, 1);
});
test('archive transport is scoped, revision-bound and does not issue Save', async () => {
    const requests = [];
    const transport = createHttpTransport({ siteId: 'site-a', layoutId: 'fl-a', sessionId: 'session-test',
        fetch: async (url, init) => { requests.push({ url, init }); return { ok: true, json: async () => ({}) }; } });
    await transport.archiveLayout('fl-b', 'a'.repeat(64));
    assert.equal(requests[0].url, '/api/facility-layouts/site-a/fl-b/archive');
    assert.equal(requests[0].init.method, 'POST');
    assert.deepEqual(JSON.parse(requests[0].init.body), { baseRevision: 'a'.repeat(64) });
    assert.equal(requests[0].init.headers['X-InspectorPro-Session'], 'session-test');
    assert.throws(() => transport.archiveLayout('fl-b', 'bad'), /baseRevision/);
});
function app(layout) {
    const listeners = [];
    const state = { layout: clone(layout), baseLayout: clone(layout), dirty: false, busy: false,
        designAuthorityState: 'ready', selection: ['existing'], history: ['manual'], draftRevision: 'draft-1', baseRevision: 'a'.repeat(64) };
    return { state, session: { getState: () => clone(state),
        subscribe: fn => { listeners.push(fn); return () => listeners.splice(listeners.indexOf(fn), 1); },
        renameLayout: async name => {
            if (state.busy) throw new Error('busy');
            state.layout.displayName = name; state.dirty = true; state.draftRevision += '-renamed';
            listeners.forEach(fn => fn(clone(state)));
        },
        beginSheetDeletion: () => { state.busy = true; return () => { state.busy = false; }; },
    }, destroy: () => { state.destroyed = true; },
        notify: () => listeners.forEach(fn => fn(clone(state))) };
}
function fixture(extra = {}) {
    let id = 0, renders = 0;
    const docs = new Map([[source.layoutId, { layout: clone(source) }]]);
    const calls = { creates: 0, gets: 0, archives: 0 };
    const transport = {
        listLayouts: async () => ({ layouts: [...docs.values()].map(x => x.layout) }),
        getLayout: async id => { calls.gets++; if (!docs.has(id)) throw new Error('missing'); return clone(docs.get(id)); },
        createLayout: async layout => { calls.creates++; const receipt = { layout: clone(layout) }; docs.set(layout.layoutId, receipt); return receipt; },
        archiveLayout: async id => { calls.archives++; const receipt = docs.get(id); receipt.layout.status = 'archived'; return clone(receipt); },
    };
    const controller = createSheets({ transport, canCreate: () => true, newId: () => 'fl-test-' + ++id,
        onChange: () => renders++, activate: async ({ retained, receipt }) => retained || app(receipt.layout), ...extra });
    const first = app(source); controller.register(first);
    return { controller, first, transport, docs, calls, renders: () => renders };
}
test('blank sheets share exact references but none of the layout contents or provenance', () => {
    const before = clone(source), blank = blankLayout(source, 'fl-blank', 'Layout 1');
    for (const key of ['zones', 'placements', 'routes', 'floorMarkings', 'processBindings', 'utilityNetworks', 'dismissedSuggestions']) {
        assert.deepEqual(blank[key], []);
    }
    for (const key of ['sourceShellRef', 'association', 'coordinateFrame', 'policySetRef']) assert.deepEqual(blank[key], source[key]);
    assert.deepEqual(blank.extensions, { facilityPlan: source.extensions.facilityPlan });
    blank.sourceShellRef.shellId = 'other'; assert.deepEqual(source, before);
});
test('invalid identifiers, schema and missing references are rejected', () => {
    assert.throws(() => blankLayout(source, '../escape', 'A'));
    assert.throws(() => blankLayout({ ...source, schemaVersion: 2 }, 'fl-a', 'A'));
    assert.throws(() => blankLayout({ ...source, sourceShellRef: null }, 'fl-a', 'A'));
    assert.throws(() => blankLayout(source, 'fl-a', ' '));
});
test('multiple sheets preserve unsaved sessions, selection and independent Undo history', async () => {
    const f = fixture(); f.first.state.dirty = true;
    const before = clone(f.first.state);
    await f.controller.addBlank(); await f.controller.addBlank();
    assert.equal(f.controller.state().layouts.length, 3);
    assert.equal(f.controller.state().activeId, 'fl-test-2');
    await f.controller.activate(source.layoutId);
    assert.equal(f.controller.apps()[0], f.first);
    assert.deepEqual(f.first.state, before);
    assert.deepEqual(f.controller.state().layouts.map(x => x.displayName), ['Manual', 'Layout 1', 'Layout 2']);
});
test('refresh keeps saved test layouts in inventory without opening tabs or loading sessions', async () => {
    const f = fixture();
    for (let i = 0; i < 5; i++) {
        const layout = blankLayout(source, 'fl-fixture-' + i, 'FDL Coordinate-Free Material Travel');
        f.docs.set(layout.layoutId, { layout });
    }
    await f.controller.refresh();
    assert.equal(f.controller.state().availableLayouts.length, 6);
    assert.deepEqual(f.controller.state().layouts.map(x => x.layoutId), [source.layoutId]);
    assert.equal(f.controller.state().activeId, source.layoutId);
    assert.equal(f.controller.apps().length, 1);
    assert.equal(f.calls.gets, 0);
    await f.controller.activate('fl-fixture-3');
    await f.controller.refresh();
    assert.deepEqual(f.controller.state().layouts.map(x => x.layoutId), [source.layoutId, 'fl-fixture-3']);
    assert.equal(f.calls.gets, 1);
    assert.equal(f.docs.size, 6);
});
test('new sheet names account for unopened saved layouts', async () => {
    const f = fixture();
    f.docs.set('fl-existing', { layout: blankLayout(source, 'fl-existing', 'Layout 1') });
    await f.controller.refresh();
    await f.controller.addBlank();
    assert.deepEqual(f.controller.state().layouts.map(x => x.displayName), ['Manual', 'Layout 2']);
});
test('a refused Open never makes a saved layout appear as an open sheet', async () => {
    const f = fixture({ activate: async () => { throw new Error('blocked'); } });
    f.docs.set('fl-other', { layout: blankLayout(source, 'fl-other', 'Other') });
    await f.controller.refresh();
    await assert.rejects(f.controller.activate('fl-other'), /blocked/);
    assert.equal(f.controller.state().layouts.length, 1);
    assert.equal(f.controller.state().availableLayouts.length, 2);
});
test('native lifecycle observation includes hidden dirty, pending and busy sheets', async () => {
    const f = fixture(); await f.controller.addBlank();
    f.first.state.dirty = true; f.first.state.busy = true; f.first.state.designAuthorityState = 'undo_acknowledgment_pending';
    const state = f.controller.observation();
    assert.equal(state.dirty, true); assert.equal(state.busy, true); assert.equal(state.pending, true);
    assert.equal(state.documents.length, 2);
});
test('a lost create reply reconciles the exact blank rather than creating another', async () => {
    const f = fixture(), create = f.transport.createLayout;
    f.transport.createLayout = async layout => { await create(layout); throw new Error('reply lost'); };
    await f.controller.addBlank();
    assert.equal(f.calls.creates, 1); assert.equal(f.controller.state().activeId, 'fl-test-1');
});
test('failed creation retries the same ID; a mismatching document is not adopted', async () => {
    const f = fixture(), create = f.transport.createLayout; const ids = [];
    f.transport.createLayout = async layout => { ids.push(layout.layoutId); throw new Error('offline'); };
    await assert.rejects(f.controller.addBlank(), /offline/);
    assert.equal(f.controller.state().activeId, source.layoutId);
    f.docs.set('fl-test-1', { layout: { ...blankLayout(source, 'fl-test-1', 'Layout 1'), placements: [{}] } });
    await assert.rejects(f.controller.addBlank(), /offline/);
    f.docs.delete('fl-test-1'); f.transport.createLayout = create;
    await f.controller.addBlank();
    assert.deepEqual(ids, ['fl-test-1', 'fl-test-1']);
    assert.equal(f.controller.state().activeId, 'fl-test-1');
});
test('a failed create retry remains bound to its source after switching sheets', async () => {
    const f = fixture(), create = f.transport.createLayout;
    f.transport.createLayout = async () => { throw new Error('offline'); };
    await assert.rejects(f.controller.addBlank(), /offline/);
    const other = blankLayout(source, 'fl-other', 'Other');
    other.sourceShellRef.shellId = 'other-shell';
    f.docs.set(other.layoutId, { layout: other });
    await f.controller.activate(other.layoutId);
    f.transport.createLayout = create;
    await f.controller.addBlank();
    assert.equal(f.docs.get('fl-test-2').layout.sourceShellRef.shellId, 'other-shell');
    await f.controller.activate(source.layoutId);
    await f.controller.addBlank();
    assert.equal(f.controller.state().activeId, 'fl-test-1');
    assert.equal(f.docs.get('fl-test-1').layout.sourceShellRef.shellId, 'shell-1');
});
test('equivalent JSON key ordering and server timestamps match, changed contents do not', () => {
    const blank = blankLayout(source, 'fl-a', 'A');
    const actual = Object.fromEntries(Object.entries(blank).reverse()); actual.createdAt = 'server';
    assert.ok(sameCreatedLayout(actual, blank));
    assert.equal(sameCreatedLayout({ ...actual, displayName: 'different' }, blank), false);
});
test('double activation and double Add are serialized', async () => {
    let release;
    const f = fixture({ activate: async ({ receipt }) => { await new Promise(resolve => { release = resolve; }); return app(receipt.layout); } });
    const first = f.controller.addBlank();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(await f.controller.addBlank(), false);
    assert.equal(await f.controller.activate('fl-other'), false);
    release(); await first; assert.equal(f.calls.creates, 1);
});
test('switch refusal and failed load leave active draft intact', async () => {
    const f = fixture({ assertSwitchable: () => { throw new Error('pending'); } });
    await assert.rejects(f.controller.addBlank(), /pending/); assert.equal(f.calls.creates, 0);
    const other = fixture({ activate: async () => { throw new Error('load failed'); } });
    await assert.rejects(other.controller.addBlank(), /load failed/);
    assert.equal(other.controller.state().activeId, source.layoutId);
    assert.equal(other.controller.state().layouts.length, 1);
    assert.equal(other.controller.state().availableLayouts.length, 2);
});
test('read-only creation is refused before transport', async () => {
    const f = fixture({ canCreate: () => false });
    await assert.rejects(f.controller.addBlank(), /not enabled/); assert.equal(f.calls.creates, 0);
});
test('camera and selection notifications do not rebuild sheet tabs', () => {
    const f = fixture(), before = f.renders();
    f.first.state.camera = { x: 4 }; f.first.notify();
    assert.equal(f.renders(), before);
    f.first.state.layout.displayName = 'Renamed'; f.first.notify();
    assert.equal(f.renders(), before + 1);
});
test('collection transport preserves site scope, session header and explicit non-default creation', async () => {
    const requests = [];
    const transport = createHttpTransport({ siteId: 'site-a', layoutId: 'fl-a', sessionId: 'session-test',
        fetch: async (url, init) => { requests.push({ url, init }); return { ok: true, json: async () => ({}) }; } });
    await transport.listLayouts(); await transport.getLayout('fl-b'); await transport.createLayout({ layoutId: 'fl-c' });
    assert.deepEqual(requests.map(x => x.url), ['/api/facility-layouts/site-a', '/api/facility-layouts/site-a/fl-b', '/api/facility-layouts/site-a']);
    assert.ok(requests.every(x => x.init.headers['X-InspectorPro-Session'] === 'session-test'));
    assert.deepEqual(JSON.parse(requests[2].init.body), { layout: { layoutId: 'fl-c' }, makeDefault: false });
});
test('normal desktop close protection observes all layout sheets', () => {
    const html = fs.readFileSync(require('node:path').join(__dirname, '../static/index.html'), 'utf8');
    assert.ok(html.includes('rows.facility = _trainFacilitySheets ? _trainFacilitySheets.observation()'));
});

test('saved layout options exclude archived records and distinguish duplicate names by identity', () => {
    const rows = [{layoutId: 'fl-b', displayName: 'Same'}, {layoutId: 'fl-a', displayName: 'Same'},
        {layoutId: 'fl-factory', displayName: 'Factory 02'}, {layoutId: 'fl-hidden', displayName: 'Archived', status: 'archived'}];
    const before = clone(rows);
    assert.deepEqual(savedLayoutOptions(rows), [
        {layoutId: 'fl-factory', label: 'Factory 02'},
        {layoutId: 'fl-a', label: 'Same (fl-a)'}, {layoutId: 'fl-b', label: 'Same (fl-b)'},
    ]);
    assert.deepEqual(rows, before);
});

function chooserFixture() {
    const f = fixture();
    f.docs.set('fl-factory', {layout: blankLayout(source, 'fl-factory', 'Factory 02')});
    const html = fs.readFileSync(require('node:path').join(__dirname, '../static/index.html'), 'utf8');
    const code = html.slice(html.indexOf('function _trainCanOpenFacilitySheet('),
        html.indexOf('async function _trainActivateFacilitySheet('));
    let dialog;
    const context = { state: {activeTab: 'training'}, _trainIsFacilityLayoutMode: () => true,
        _trainFacilitySheets: f.controller, _trainFacilityLayoutAuthoringApp: f.first,
        _trainAssertSheetSwitchable() {}, _trainFacilitySheetAction: fn => fn(),
        document: {querySelector: () => ({})}, window: {InspectorProFacilitySheets: {
            openLayoutDialog: (host, rows, submit) => { dialog = {host, rows, submit}; },
        }} };
    require('node:vm').runInNewContext(code + ';this.choose = _trainChooseSavedFacilitySheet;', context);
    return {f, context, dialog: () => dialog};
}

test('File Open lists saved layouts without opening them and activates only the chosen sheet', async () => {
    const {f, context, dialog} = chooserFixture();
    f.first.state.dirty = true;
    const before = clone(f.first.state);
    await context.choose();
    assert.equal(dialog().rows.length, 2);
    assert.equal(f.controller.apps().length, 1);
    assert.equal(f.calls.gets, 0);
    await dialog().submit('fl-factory');
    assert.deepEqual(f.controller.state().layouts.map(r => r.layoutId), ['fl-source', 'fl-factory']);
    assert.equal(f.calls.creates, 0);
    assert.equal(f.calls.archives, 0);
    await f.controller.activate('fl-source');
    assert.deepEqual(f.first.state, before);
});

test('File Open rejects pending work before refreshing inventory', async () => {
    const {f, context, dialog} = chooserFixture();
    f.transport.listLayouts = async () => { throw new Error('Must not refresh'); };
    context._trainAssertSheetSwitchable = () => { throw new Error('Pending work'); };
    await assert.rejects(context.choose(), /Pending work/);
    assert.equal(dialog(), undefined);
});

test('File Open refuses a selection if the workspace changed while the chooser was open', async () => {
    const {f, context, dialog} = chooserFixture();
    await context.choose();
    context.state.activeTab = 'drawing';
    assert.throws(() => dialog().submit('fl-factory'), /workspace changed/);
    assert.equal(f.calls.gets, 0);
    assert.equal(f.controller.apps().length, 1);
});

for (const change of ['workflow', 'controller', 'session']) {
    test('File Open rejects a stale chooser after a ' + change + ' change', async () => {
        const {f, context, dialog} = chooserFixture();
        const list = f.transport.listLayouts;
        f.transport.listLayouts = async () => {
            if (change === 'workflow') context.state.activeTab = 'drawing';
            if (change === 'controller') context._trainFacilitySheets = {state: () => ({busy: false})};
            if (change === 'session') context._trainFacilityLayoutAuthoringApp = {};
            return list();
        };
        await assert.rejects(context.choose(), /workspace changed/);
        assert.equal(dialog(), undefined);
        assert.equal(f.controller.apps().length, 1);
    });
}

test('failed retained-sheet installation releases its renderer before restoring the old sheet', async () => {
    const html = fs.readFileSync(require('node:path').join(__dirname, '../static/index.html'), 'utf8');
    const code = html.slice(html.indexOf('async function _trainActivateFacilitySheet('),
        html.indexOf('function _trainSetupFacilitySheets('));
    const events = [];
    const host = { isConnected: true, prepend: node => events.push('attach-' + node.id) };
    function view(id) {
        const root = { id, remove: () => events.push('remove-' + id) };
        return { workspace: { root, clearMotionPlayback() {}, clearActivityPlayback() {},
            threeAdapter: { park: () => events.push('park-' + id) } },
            suspend: () => events.push('suspend-' + id), resume: () => events.push('resume-' + id) };
    }
    const previous = view('old'), retained = view('next');
    let binds = 0;
    const context = { _trainAssertSheetSwitchable() {}, _trainIsFacilityLayoutMode: () => true,
        document: { getElementById: id => id === 'trainViewportHost' ? host : null },
        _trainBindStructureTree() { if (++binds === 1) throw new Error('installation failed'); },
        _trainFacilityLayoutAuthoringApp: previous };
    require('node:vm').runInNewContext(code + ';this.activateSheet = _trainActivateFacilitySheet;', context);
    await assert.rejects(context.activateSheet({ previous, retained, layoutId: 'next' }), /installation failed/);
    assert.equal(context._trainFacilityLayoutAuthoringApp, previous);
    assert.ok(events.indexOf('park-next') < events.indexOf('resume-old'));
    assert.ok(events.includes('remove-next'));
});
