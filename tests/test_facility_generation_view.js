'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { create } = require('../static/facility_layout_generation_view.js');

function fixture() {
    let state = {baseRevision: 'base-a', draftRevision: 'base-a', editorGenerationId: 1, history: [], dirty: false};
    const stored = new Map(), requests = [], navigations = [];
    const transport = {layoutId: 'original', sessionId: 'session', createGenerationDestination: async request => {
        requests.push(request); return {layoutId: 'created'};
    }};
    const workspace = {designTransport: transport, session: {getState: () => state},
        _renderDesignPanel() {}, _syncController() {},
        document: {defaultView: {sessionStorage: {getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value)},
            location: {href: 'http://localhost/?facilityLayoutId=original', assign: url => navigations.push(url)}}}};
    return {workspace, transport, requests, navigations, view: create(workspace),
        update: changes => { state = {...state, ...changes}; }};
}
const values = {displayName: 'Concept', widthMeters: 40, depthMeters: 30, confirmConceptualFloor: true};

test('destination retry retains the same request key across view recreation', async () => {
    const f = fixture();
    await f.view.createDestination(values);
    await create(f.workspace).createDestination(values);
    assert.equal(f.requests[0].requestKey, f.requests[1].requestKey);
    assert.match(f.navigations[0], /facilityLayoutId=created/);
});

test('a changed saved base starts a new destination request', async () => {
    const f = fixture();
    await f.view.createDestination(values);
    f.update({baseRevision: 'base-b', draftRevision: 'base-b', editorGenerationId: 2});
    await f.view.createDestination(values);
    assert.notEqual(f.requests[0].requestKey, f.requests[1].requestKey);
    assert.equal(f.requests[1].expectedBaseRevision, 'base-b');
});

test('an edit followed by Undo during destination creation prevents late navigation', async () => {
    const f = fixture();
    let finish;
    f.transport.createGenerationDestination = () => new Promise(resolve => { finish = resolve; });
    const pending = f.view.createDestination(values);
    f.update({editorGenerationId: 3});
    finish({layoutId: 'retained-concept'});
    await assert.rejects(pending, /retained as retained-concept/);
    assert.deepEqual(f.navigations, []);
});

test('dirty editor cannot create a destination', async () => {
    const f = fixture();
    f.update({dirty: true});
    await assert.rejects(f.view.createDestination(values), /Resolve the current draft/);
    assert.deepEqual(f.requests, []);
});

function renderFixture() {
    const f = fixture(), document = f.workspace.document;
    function element(_document, tag, attributes = {}, text = '') {
        return Object.assign({tag, textContent: text, children: [], style: {}, listeners: {}, parentNode: null,
            get firstChild() { return this.children[0] || null; },
            setAttribute(key, value) { this[key] = value; },
            contains(node) { return this === node || this.children.some(child => child.contains(node)); },
            appendChild(child) {
                if (child.parentNode) child.parentNode.removeChild(child);
                this.children.push(child); child.parentNode = this; return child;
            },
            removeChild(child) {
                if (child.contains(document.activeElement)) document.activeElement = null;
                this.children.splice(this.children.indexOf(child), 1); child.parentNode = null;
            },
            addEventListener(name, handler) { this.listeners[name] = handler; },
            focus() { document.activeElement = this; },
        }, attributes);
    }
    document.createTextNode = text => element(document, '#text', {}, text);
    const title = new Map();
    Object.assign(f.workspace, {root: element(document, 'div'), designState: {collapsed: false},
        capabilities: {designLoopApply: true, agentWrite: true},
        designPanel: element(document, 'aside'), designPanelBody: element(document, 'div'),
        designPanelToggle: element(document, 'button'), designPanelTitle: {querySelector(selector) {
            if (!title.has(selector)) title.set(selector, element(document, 'span'));
            return title.get(selector);
        }}});
    const view = create(f.workspace, element);
    f.workspace._renderDesignPanel = () => view.render();
    f.workspace._cancelPointerGesture = () => {};
    f.workspace.assetBrowserState = {open: false};
    f.workspace.controller = {fit() {}};
    return {...f, view};
}

test('late source listing and session refresh preserve an open concept form and focus', async () => {
    const f = renderFixture(), {view} = f, document = f.workspace.document;
    let finishListing;
    f.transport.listGenerationPlanningSources = () => new Promise(resolve => { finishListing = resolve; });
    const opening = view.open();
    const body = f.workspace.designPanel.firstChild;
    const form = body.children.find(node => node.tag === 'details');
    const inputs = form.children.filter(node => node.tag === 'label').map(label => label.firstChild);
    form.open = true;
    inputs[0].value = 'My assembly room'; inputs[1].value = '35'; inputs[2].value = '25';
    inputs[3].checked = true; inputs[0].focus();
    finishListing({sources: []}); await opening;
    assert.equal(body.children.find(node => node.tag === 'details'), form);
    assert.equal(form.open, true);
    assert.equal(document.activeElement, inputs[0]);
    assert.deepEqual(inputs.slice(0, 3).map(node => node.value), ['My assembly room', '35', '25']);
    assert.equal(inputs[3].checked, true);
    const button = form.children.find(node => node.tag === 'button');
    f.update({dirty: true}); view.render(); assert.equal(button.disabled, true);
    f.update({dirty: false}); view.render(); assert.equal(button.disabled, false);
    button.listeners.click();
    assert.deepEqual(f.requests[0], {displayName: 'My assembly room', widthMeters: 35, depthMeters: 25,
        confirmConceptualFloor: true, expectedBaseRevision: 'base-a', requestKey: f.requests[0].requestKey});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.navigations.length, 1);
});

test('concise chat does not remove planning assumptions, unknowns or engineering limits', async () => {
    const f = renderFixture();
    f.transport.listGenerationPlanningSources = async () => ({sources: []});
    await f.view.open();
    f.view.begin('turn-a');
    const summary = {clientTurnId: 'turn-a', workspaceId: f.view.reference().workspaceId,
        sourceContextRef: {artifactKind: 'generation-provisional-context', artifactId: 'source-a', artifactRevision: 'source-rev'},
        baseRevision: 'base-a', candidateRevision: 'candidate-a', previewRevision: 'preview-rev',
        previewId: 'preview-a', ledgerRevision: 'ledger-a'};
    const notes = {assumptions: ['One metre gap is illustrative.'], unknowns: ['Installed fixture is unknown.'],
        historicalAssumptions: ['Original count was provisional.']};
    f.transport.inspectGenerationPlanningPreview = async () => ({...summary,
        candidateLayout: {placements: []}, counts: {placements: 9, zones: 4}, planningNotes: notes});
    await f.view.show(summary);
    const text = node => [node.textContent, ...node.children.map(text)].join(' ');
    const shown = text(f.workspace.designPanel);
    for (const value of ['Checks and limits', 'Manufacturing feasibility', 'station-to-station transfers',
        'safety approval are not established', 'not verified operating clearance',
        'Current assumptions', 'Still unknown', 'Original assumptions (not revalidated)', ...Object.values(notes).flat()]) {
        assert.ok(shown.includes(value), value);
    }
    assert.ok(shown.includes('Not applied or saved'));
});
