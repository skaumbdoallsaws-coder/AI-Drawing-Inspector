'use strict';

/**
 * FT2/FT3 acceptance for the structure tree renderer.
 * Covers lazy expansion, grouping, the unzoned branch, the empty state, the
 * read-only preview rule, the two-key expansion contract from section 6 -
 * including the four-step sequence the third review asked for - and FT3
 * selection binding in both directions.
 */

const assert = require('assert');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const structure = require(path.join(ROOT, 'static', 'facility_layout_structure.js'));
const treeModule = require(path.join(ROOT, 'static', 'facility_layout_structure_tree.js'));

let passed = 0;
function check(name, run) {
    run();
    passed += 1;
    console.log('PASS ' + name);
}

// ------------------------------------------------------------ tiny DOM --
// Enough of a document for the renderer: elements, attributes, text, classes,
// a querySelector limited to the selectors the renderer actually uses.
function makeDocument() {
    function node(tag) {
        return {
            tagName: String(tag).toUpperCase(),
            childNodes: [],
            attributes: Object.create(null),
            className: '',
            textContent: '',
            parentNode: null,
            listeners: Object.create(null),
            get firstChild() { return this.childNodes[0] || null; },
            appendChild: function (child) {
                child.parentNode = this;
                this.childNodes.push(child);
                return child;
            },
            removeChild: function (child) {
                const index = this.childNodes.indexOf(child);
                if (index >= 0) this.childNodes.splice(index, 1);
                child.parentNode = null;
                return child;
            },
            replaceChild: function (next, previous) {
                const index = this.childNodes.indexOf(previous);
                if (index < 0) throw new Error('replaceChild: not a child');
                this.childNodes[index] = next;
                next.parentNode = this;
                previous.parentNode = null;
                return previous;
            },
            value: '',
            select: function () {},
            setAttribute: function (key, value) { this.attributes[key] = String(value); },
            getAttribute: function (key) {
                return Object.prototype.hasOwnProperty.call(this.attributes, key)
                    ? this.attributes[key] : null;
            },
            addEventListener: function (type, fn) {
                (this.listeners[type] = this.listeners[type] || []).push(fn);
            },
            removeEventListener: function (type, fn) {
                const list = this.listeners[type] || [];
                const index = list.indexOf(fn);
                if (index >= 0) list.splice(index, 1);
            },
            dispatch: function (type, event) {
                (this.listeners[type] || []).forEach(function (fn) {
                    fn(Object.assign({ target: this, preventDefault: function () {} }, event));
                }, this);
            },
            focus: function () { this.ownerDocument.activeElement = this; },
            contains: function (other) {
                let cursor = other;
                while (cursor) { if (cursor === this) return true; cursor = cursor.parentNode; }
                return false;
            },
            descendants: function () {
                const out = [];
                (function walk(parent) {
                    parent.childNodes.forEach(function (child) {
                        out.push(child);
                        walk(child);
                    });
                }(this));
                return out;
            },
            querySelectorAll: function (selector) {
                const all = this.descendants();
                if (selector === '.ip-fst-row') {
                    return all.filter(function (n) { return n.className === 'ip-fst-row'; });
                }
                const match = /^\[data-row-id="(.*)"\]$/.exec(selector);
                if (match) {
                    const want = match[1].replace(/\\(["\\])/g, '$1');
                    return all.filter(function (n) { return n.getAttribute('data-row-id') === want; });
                }
                if (selector.charAt(0) === '.') {
                    const wanted = selector.slice(1);
                    return all.filter(function (n) { return n.className === wanted; });
                }
                return [];
            },
            querySelector: function (selector) {
                return this.querySelectorAll(selector)[0] || null;
            },
        };
    }
    const doc = {
        activeElement: null,
        createElement: function (tag) {
            const created = node(tag);
            created.ownerDocument = doc;
            return created;
        },
    };
    return doc;
}

function host(doc) {
    const element = doc.createElement('div');
    element.ownerDocument = doc;
    return element;
}

function rect(x0, z0, x1, z1) {
    return [{ x: x0, z: z0 }, { x: x1, z: z0 }, { x: x1, z: z1 }, { x: x0, z: z1 }];
}

function place(id, assetId, x, z) {
    return {
        placementId: id, assetId: assetId, assetDefinitionRevision: 'r1',
        transform: { position: { x: x, y: 0, z: z } },
    };
}

const LAYOUT = {
    zones: [
        { zoneId: 'auto', label: 'Automation', zoneType: 'area', boundary: rect(0, 0, 100, 100) },
        { zoneId: 'cellA', label: 'Cell A', zoneType: 'workcell', boundary: rect(5, 5, 40, 40) },
        { zoneId: 'cellB', label: 'Cell B', zoneType: 'workcell', boundary: rect(50, 5, 90, 40) },
    ],
    placements: [
        place('g1', 'asset-guard', 10, 10),
        place('g2', 'asset-guard', 12, 12),
        place('r1', 'asset-robot', 20, 20),
        place('g3', 'asset-guard', 60, 10),
        place('loose', 'asset-bench', 500, 500),
    ],
};

const LAYOUT_ROW = treeModule.LAYOUT_ROW_ID;

// Every tree now has one root: the layout document. These helpers keep the
// checks about the structure under it.
function idsBelowRoot(element) {
    return rows(element).map(function (r) { return r.id; })
        .filter(function (id) { return id !== LAYOUT_ROW; });
}

function rows(element) {
    return element.querySelectorAll('.ip-fst-row').map(function (row) {
        return {
            id: row.getAttribute('data-row-id'),
            kind: row.getAttribute('data-row-kind'),
            expanded: row.getAttribute('aria-expanded'),
            label: row.childNodes[2] ? row.childNodes[2].textContent : '',
        };
    });
}

function build(doc, element, view) {
    const tree = treeModule.createStructureTree({ document: doc, host: element });
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: view || { kind: 'draft', layoutId: 'L1', revision: 'rev-1' },
        readOnly: false,
    });
    return tree;
}

// ------------------------------------------------------------- rendering --
check('collapsed roots render without their descendants', function () {
    const doc = makeDocument();
    const element = host(doc);
    build(doc, element);
    const drawn = rows(element);
    assert.strictEqual(drawn[0].id, LAYOUT_ROW, 'the layout is the single root');
    assert.strictEqual(drawn[0].kind, 'layout');
    assert.strictEqual(drawn[0].expanded, 'true', 'the root opens by default');
    assert.deepStrictEqual(idsBelowRoot(element), ['auto', 'unzoned']);
    assert.strictEqual(drawn[1].expanded, 'false', 'lazy: children not built yet');
});

check('expanding a zone builds its children on demand', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = build(doc, element);
    tree.setExpandedForTest('auto', true);
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-1' },
    });
    const ids = rows(element).map(function (r) { return r.id; });
    assert.ok(ids.indexOf('cellA') > 0, 'child zone appears');
    assert.ok(ids.indexOf('cellB') > 0);
    assert.strictEqual(ids.indexOf('r1'), -1, 'grandchildren stay lazy');
});

check('a group row shows a count and expands to its placements', function () {
    const doc = makeDocument();
    const element = host(doc);
    const model = structure.deriveStructure(LAYOUT);
    const groupRowId = model.zones.cellA.groups[0].rowId;
    const view = { kind: 'draft', layoutId: 'L1', revision: 'r' };
    const tree = treeModule.createStructureTree({ document: doc, host: element });
    // Render first: expansion is namespaced by the current view, so it is only
    // meaningful once a view exists - which is also the real interaction order.
    tree.render({ model: model, view: view });
    tree.setExpandedForTest('auto', true);
    tree.setExpandedForTest('cellA', true);
    tree.render({ model: model, view: view });

    const group = rows(element).filter(function (r) { return r.kind === 'group'; })[0];
    assert.ok(group, 'a group row is drawn');
    assert.strictEqual(group.expanded, 'false');

    tree.setExpandedForTest(groupRowId, true);
    tree.render({ model: model, view: view });
    const placements = rows(element).filter(function (r) { return r.kind === 'placement'; });
    assert.strictEqual(placements.length, 2, 'two guard panels in Cell A');
});

check('the unzoned branch appears and is marked as a notice, not an error', function () {
    const doc = makeDocument();
    const element = host(doc);
    build(doc, element);
    const unzoned = element.querySelector('[data-row-id="unzoned"]');
    assert.ok(unzoned);
    assert.strictEqual(unzoned.getAttribute('data-tone'), 'notice');
});

check('an empty layout renders an explicit empty state, not a blank pane', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = treeModule.createStructureTree({ document: doc, host: element });
    tree.render({
        model: structure.deriveStructure({}),
        view: { kind: 'draft', displayName: 'Main Facility' },
    });
    // The layout row is still drawn: its name must be visible and renameable
    // on an empty layout, which is exactly when a user would set it.
    assert.deepStrictEqual(idsBelowRoot(element), []);
    assert.strictEqual(rows(element).length, 1);
    assert.strictEqual(rows(element)[0].label, 'Main Facility');
    assert.strictEqual(element.childNodes.length, 2);
    assert.ok(/No zones or equipment yet/.test(element.childNodes[1].textContent));
});

check('invalid zone geometry is reported on its own row', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = treeModule.createStructureTree({ document: doc, host: element });
    tree.render({
        model: structure.deriveStructure({
            zones: [{ zoneId: 'bad', label: 'Bad', boundary: [{ x: 0, z: 0 }] }],
            placements: [],
        }),
        view: { kind: 'draft' },
    });
    const row = element.querySelector('[data-row-id="bad"]');
    assert.strictEqual(row.getAttribute('data-geometry'), 'invalid');
});

// ------------------------------------------------------- caret vs label --
check('the caret expands and the label does not', function () {
    const doc = makeDocument();
    const element = host(doc);
    const selected = [];
    const tree = treeModule.createStructureTree({
        document: doc, host: element,
        onSelect: function (kind, payload) { selected.push([kind, payload.rowId]); },
    });
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'r' },
    });
    const row = element.querySelector('[data-row-id="auto"]');
    const caret = row.childNodes[0];
    const label = row.childNodes[2];

    element.dispatch('click', { target: caret });
    assert.deepStrictEqual(tree.expandedRowIds(), ['auto'], 'caret expanded it');
    assert.deepStrictEqual(selected, [], 'caret selects nothing');

    element.dispatch('click', { target: label });
    assert.deepStrictEqual(selected, [['zone', 'auto']], 'label selects');
});

check('no row selects while a preview is represented', function () {
    const doc = makeDocument();
    const element = host(doc);
    const selected = [];
    const tree = treeModule.createStructureTree({
        document: doc, host: element,
        onSelect: function (kind, payload) { selected.push([kind, payload.rowId]); },
    });
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'candidate', proposalId: 'p1', layoutId: 'L1', revision: 'r' },
        readOnly: true,
    });
    const row = element.querySelector('[data-row-id="auto"]');
    element.dispatch('click', { target: row.childNodes[2] });
    assert.deepStrictEqual(selected, [], 'read-only preview selects nothing');
});

// ------------------------------------------- the two-key expansion rule --
check('expansion survives an edit: revision moves, namespace does not', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = build(doc, element);
    tree.setExpandedForTest('auto', true);

    // Same view, new revision - an ordinary edit.
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-2' },
    });
    assert.deepStrictEqual(tree.expandedRowIds(), ['auto'],
        'a rebuild must not collapse what the user opened');
    assert.ok(rows(element).some(function (r) { return r.id === 'cellA'; }));
});

check('the four-step sequence: draft, edit, candidate, dismiss', function () {
    const doc = makeDocument();
    const element = host(doc);
    const model = structure.deriveStructure(LAYOUT);
    const draft = { kind: 'draft', layoutId: 'L1', revision: 'rev-1' };
    const edited = { kind: 'draft', layoutId: 'L1', revision: 'rev-2' };
    // A candidate carrying the same layout ID and the same zone IDs.
    const candidate = { kind: 'candidate', proposalId: 'p1', layoutId: 'L1', revision: 'rev-9' };

    const tree = treeModule.createStructureTree({ document: doc, host: element });

    // 1. expand a draft branch
    tree.render({ model: model, view: draft });
    tree.setExpandedForTest('auto', true);
    tree.render({ model: model, view: draft });
    assert.deepStrictEqual(tree.expandedRowIds(), ['auto']);

    // 2. move equipment: the branch stays expanded
    tree.render({ model: model, view: edited });
    assert.deepStrictEqual(tree.expandedRowIds(), ['auto'], 'survives the edit');

    // 3. open a candidate sharing the zone IDs: its expansion is independent
    tree.render({ model: model, view: candidate });
    assert.deepStrictEqual(tree.expandedRowIds(), [],
        'the candidate must not inherit the draft expanded set');
    tree.setExpandedForTest('cellA', true);
    tree.render({ model: model, view: candidate });
    assert.deepStrictEqual(tree.expandedRowIds(), ['cellA']);

    // 4. dismiss: the draft's original expansion returns
    tree.render({ model: model, view: edited });
    assert.deepStrictEqual(tree.expandedRowIds(), ['auto'],
        'and the draft must not inherit the candidate expanded set');
});

check('namespace excludes revision and includes kind and proposal', function () {
    const a = treeModule.namespaceOf({ kind: 'draft', layoutId: 'L1', revision: 'r1' });
    const b = treeModule.namespaceOf({ kind: 'draft', layoutId: 'L1', revision: 'r2' });
    const c = treeModule.namespaceOf({ kind: 'candidate', proposalId: 'p', layoutId: 'L1', revision: 'r1' });
    assert.strictEqual(a, b, 'revision must not namespace expansion');
    assert.notStrictEqual(a, c, 'kind and proposal must');
});

// -------------------------------------------------------------- keyboard --
check('arrow keys move focus and open branches', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = build(doc, element);
    const first = element.querySelector('[data-row-id="auto"]');
    first.focus();

    element.dispatch('keydown', { target: first, key: 'ArrowRight' });
    assert.deepStrictEqual(tree.expandedRowIds(), ['auto']);

    const again = element.querySelector('[data-row-id="auto"]');
    element.dispatch('keydown', { target: again, key: 'ArrowDown' });
    assert.strictEqual(doc.activeElement.getAttribute('data-row-id'), 'cellA');

    element.dispatch('keydown', { target: again, key: 'ArrowLeft' });
    assert.deepStrictEqual(tree.expandedRowIds(), []);
});

check('focus survives a rebuild when its row still exists', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = build(doc, element);
    element.querySelector('[data-row-id="auto"]').focus();
    assert.strictEqual(doc.activeElement.getAttribute('data-row-id'), 'auto');

    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-3' },
    });
    assert.strictEqual(doc.activeElement.getAttribute('data-row-id'), 'auto',
        'a rebuild must not drop focus out of the tree');
});

// ------------------------------------------------------------- lifecycle --
check('destroy clears the host and detaches listeners', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = build(doc, element);
    assert.ok(rows(element).length > 0);
    tree.destroy();
    assert.strictEqual(element.childNodes.length, 0);
    assert.strictEqual((element.listeners.click || []).length, 0);
    assert.strictEqual((element.listeners.keydown || []).length, 0);
});

// ------------------------------------------------- FT3 selection binding --
// The model is shared by these checks; row IDs are read from it rather than
// spelled out, because a group's ID is scoped by its parent zone.
const MODEL = structure.deriveStructure(LAYOUT);
const CELL_A_GUARDS = MODEL.zones.cellA.groups.filter(function (group) {
    return group.assetId === 'asset-guard';
})[0];
const CELL_B_GUARDS = MODEL.zones.cellB.groups.filter(function (group) {
    return group.assetId === 'asset-guard';
})[0];

function selectingTree(doc, element) {
    const events = [];
    const tree = treeModule.createStructureTree({
        document: doc, host: element,
        onSelect: function (kind, payload, event) {
            events.push({ kind: kind, payload: payload, event: event });
        },
    });
    return { tree: tree, events: events };
}

function show(tree, selection, openRowIds) {
    const frame = {
        model: MODEL,
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-1' },
        readOnly: false,
        selection: selection || [],
    };
    // Render before expanding: expansion is namespaced by the current view, so
    // it is only meaningful once one exists. This is the real order too - the
    // user opens a branch that is already on screen.
    tree.render(frame);
    if (openRowIds && openRowIds.length) {
        openRowIds.forEach(function (rowId) { tree.setExpandedForTest(rowId, true); });
        tree.render(frame);
    }
}

function selectionOf(element, rowId) {
    const row = element.querySelector('[data-row-id="' + rowId + '"]');
    return row ? row.getAttribute('data-selection') : null;
}

check('a zone row reports its own ID, and Ctrl marks the gesture additive', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, []);

    const label = element.querySelector('[data-row-id="auto"]').childNodes[2];
    element.dispatch('click', { target: label });
    assert.strictEqual(harness.events[0].kind, 'zone');
    assert.deepStrictEqual(harness.events[0].payload.ids, ['auto']);
    assert.strictEqual(harness.events[0].payload.additive, false);

    element.dispatch('click', { target: label, ctrlKey: true });
    assert.strictEqual(harness.events[1].payload.additive, true);
    element.dispatch('click', { target: label, metaKey: true });
    assert.strictEqual(harness.events[2].payload.additive, true, 'meta counts on macOS');
});

check('a group row carries every member, so it acts as a unit', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, [], ['auto', 'cellA']);

    const row = element.querySelector('[data-row-id="' + CELL_A_GUARDS.rowId + '"]');
    element.dispatch('click', { target: row.childNodes[2] });
    assert.strictEqual(harness.events[0].kind, 'group');
    assert.deepStrictEqual(harness.events[0].payload.ids.slice().sort(), ['g1', 'g2']);
});

check('a placement row reports the placement, not its group', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, [], ['auto', 'cellA', CELL_A_GUARDS.rowId]);

    const row = element.querySelector('[data-row-id="g2"]');
    element.dispatch('click', { target: row.childNodes[2] });
    assert.strictEqual(harness.events[0].kind, 'placement');
    assert.deepStrictEqual(harness.events[0].payload.ids, ['g2']);
});

check('the Unzoned header selects nothing: it is a scope, not an entity', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, []);

    const row = element.querySelector('[data-row-id="unzoned"]');
    element.dispatch('click', { target: row.childNodes[2] });
    assert.deepStrictEqual(harness.events, []);
});

check('Enter selects the focused row; the caret is not the only way in', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, []);

    const row = element.querySelector('[data-row-id="auto"]');
    element.dispatch('keydown', { target: row, key: 'Enter' });
    assert.deepStrictEqual(harness.events[0].payload.ids, ['auto']);
    element.dispatch('keydown', { target: row, key: ' ', ctrlKey: true });
    assert.strictEqual(harness.events[1].payload.additive, true);
});

check('no row reaches onSelect by keyboard while a preview is represented', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    harness.tree.render({
        model: MODEL,
        view: { kind: 'candidate', proposalId: 'p1', layoutId: 'L1', revision: 'r' },
        readOnly: true,
        selection: [],
    });
    const row = element.querySelector('[data-row-id="auto"]');
    element.dispatch('keydown', { target: row, key: 'Enter' });
    element.dispatch('click', { target: row.childNodes[2] });
    assert.deepStrictEqual(harness.events, []);
});

// --------------------------------------------------- canvas -> tree state --
check('a selected zone is marked selected', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, ['auto']);
    assert.strictEqual(selectionOf(element, 'auto'), 'all');
    const row = element.querySelector('[data-row-id="auto"]');
    assert.strictEqual(row.getAttribute('aria-selected'), 'true');
    assert.strictEqual(selectionOf(element, 'unzoned'), 'none');
});

check('a group is full when every member is selected and partial when some are', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);

    show(harness.tree, ['g1', 'g2'], ['auto', 'cellA']);
    assert.strictEqual(selectionOf(element, CELL_A_GUARDS.rowId), 'all');

    show(harness.tree, ['g1'], ['auto', 'cellA']);
    assert.strictEqual(
        selectionOf(element, CELL_A_GUARDS.rowId), 'partial',
        'partial is displayed when members are selected individually'
    );
    const placementRow = element.querySelector('[data-row-id="g1"]');
    assert.ok(placementRow, 'a partial group is opened so the member is reachable');
    assert.strictEqual(placementRow.getAttribute('data-selection'), 'all');
    assert.strictEqual(selectionOf(element, 'g2'), 'none');
});

check('a canvas selection reveals its ancestors in a collapsed tree', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);

    show(harness.tree, []);
    assert.deepStrictEqual(idsBelowRoot(element), ['auto', 'unzoned'], 'starts collapsed');

    // Selection arrives from the canvas: a guard panel deep inside Cell B.
    show(harness.tree, ['g3']);
    const ids = rows(element).map(function (r) { return r.id; });
    assert.ok(ids.indexOf('cellB') >= 0, 'the parent zone is opened');
    // A one-member group has no separate placement row: the group row is the
    // placement's representation, and it carries the selection.
    assert.ok(ids.indexOf(CELL_B_GUARDS.rowId) >= 0, 'the selected item is visible');
    assert.strictEqual(selectionOf(element, CELL_B_GUARDS.rowId), 'all');
    assert.strictEqual(selectionOf(element, CELL_A_GUARDS.rowId), null,
        'only the branch holding the selection is opened');
});

check('revealing does not fight a user who collapses a branch', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, ['g3']);
    assert.ok(rows(element).some(function (r) { return r.id === CELL_B_GUARDS.rowId; }));

    // The user collapses the root while the selection is unchanged.
    const caret = element.querySelector('[data-row-id="auto"]').childNodes[0];
    element.dispatch('click', { target: caret });
    assert.deepStrictEqual(idsBelowRoot(element), ['auto', 'unzoned']);

    // An unrelated redraw (a camera move, say) must not re-open it.
    show(harness.tree, ['g3']);
    assert.deepStrictEqual(
        idsBelowRoot(element), ['auto', 'unzoned'],
        'the same selection is revealed once, not on every draw'
    );

    // A new selection reveals again.
    show(harness.tree, ['r1']);
    const robot = MODEL.zones.cellA.groups.filter(function (group) {
        return group.assetId === 'asset-robot';
    })[0];
    assert.ok(rows(element).some(function (r) { return r.id === robot.rowId; }));
});

check('an empty selection clears every mark', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = selectingTree(doc, element);
    show(harness.tree, ['g1'], ['auto', 'cellA']);
    assert.strictEqual(selectionOf(element, CELL_A_GUARDS.rowId), 'partial');
    show(harness.tree, []);
    assert.strictEqual(selectionOf(element, 'auto'), 'none');
});

// ------------------------------------------------- group toggle contract --
check('a group toggle selects every member when any is unselected', function () {
    assert.deepStrictEqual(
        structure.toggleSelection([], ['g1', 'g2']).sort(), ['g1', 'g2']
    );
    assert.deepStrictEqual(
        structure.toggleSelection(['g1'], ['g1', 'g2']).sort(), ['g1', 'g2'],
        'partial toggles up to full, it does not deselect'
    );
});

check('a group toggle deselects only when every member is selected', function () {
    assert.deepStrictEqual(structure.toggleSelection(['g1', 'g2'], ['g1', 'g2']), []);
});

check('a group toggle leaves entities outside the group untouched', function () {
    const next = structure.toggleSelection(['r1', 'cellB', 'g1', 'g2'], ['g1', 'g2']);
    assert.deepStrictEqual(next, ['r1', 'cellB'], 'the robot and the zone survive');

    const back = structure.toggleSelection(next, ['g1', 'g2']);
    assert.deepStrictEqual(back, ['r1', 'cellB', 'g1', 'g2']);
});

check('a second toggle deselects exactly what the first selected', function () {
    const first = structure.toggleSelection(['r1'], ['g1', 'g2']);
    assert.deepStrictEqual(first, ['r1', 'g1', 'g2']);
    assert.deepStrictEqual(
        structure.toggleSelection(first, ['g1', 'g2']), ['r1'],
        'round trip returns to the starting selection'
    );
});

check('a toggle never duplicates an already selected member', function () {
    assert.deepStrictEqual(structure.toggleSelection(['g1'], ['g2', 'g2']), ['g1', 'g2']);
    assert.deepStrictEqual(structure.toggleSelection([], []), []);
});

// -------------------------------------------------- FT4 dynamic behaviour --
check('a zone that disappears takes its rows with it and leaves the rest open', function () {
    const doc = makeDocument();
    const element = host(doc);
    const view = { kind: 'draft', layoutId: 'L1', revision: 'rev-1' };
    const tree = treeModule.createStructureTree({ document: doc, host: element });

    tree.render({ model: structure.deriveStructure(LAYOUT), view: view });
    tree.setExpandedForTest('auto', true);
    tree.setExpandedForTest('cellB', true);
    tree.render({ model: structure.deriveStructure(LAYOUT), view: view });
    assert.ok(rows(element).some(function (r) { return r.id === 'cellB'; }));

    // Cell B is deleted. Its guard panel is still inside Automation, so it
    // reparents rather than vanishing - the derivation's rule, drawn.
    const without = {
        zones: LAYOUT.zones.filter(function (z) { return z.zoneId !== 'cellB'; }),
        placements: LAYOUT.placements,
    };
    tree.render({
        model: structure.deriveStructure(without),
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-2' },
    });
    const after = rows(element);
    assert.ok(!after.some(function (r) { return r.id === 'cellB'; }), 'the zone row is gone');
    assert.ok(after.some(function (r) { return r.id === 'cellA'; }), 'Automation stayed open');
    assert.ok(
        after.some(function (r) { return r.kind === 'group' && /guard/i.test(r.label); }),
        'the orphaned guard panel reparented into Automation'
    );
});

check('undoing a deletion brings the branch back still expanded', function () {
    const doc = makeDocument();
    const element = host(doc);
    const view = { kind: 'draft', layoutId: 'L1', revision: 'rev-1' };
    const tree = treeModule.createStructureTree({ document: doc, host: element });
    const without = {
        zones: LAYOUT.zones.filter(function (z) { return z.zoneId !== 'cellB'; }),
        placements: LAYOUT.placements,
    };

    tree.render({ model: structure.deriveStructure(LAYOUT), view: view });
    tree.setExpandedForTest('auto', true);
    tree.setExpandedForTest('cellB', true);
    tree.render({ model: structure.deriveStructure(LAYOUT), view: view });
    const openBefore = rows(element).filter(function (r) { return r.id === 'cellB'; })[0];
    assert.strictEqual(openBefore.expanded, 'true');

    // Delete, then undo. Expansion is keyed by row ID inside a namespace that
    // revision does not touch, so the branch comes back as the user left it.
    tree.render({
        model: structure.deriveStructure(without),
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-2' },
    });
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-3' },
    });
    const openAfter = rows(element).filter(function (r) { return r.id === 'cellB'; })[0];
    assert.ok(openAfter, 'the zone row is back');
    assert.strictEqual(openAfter.expanded, 'true', 'and still expanded');
});

check('a selection change inside an open branch does not change which rows exist', function () {
    const doc = makeDocument();
    const element = host(doc);
    const view = { kind: 'draft', layoutId: 'L1', revision: 'rev-1' };
    const model = structure.deriveStructure(LAYOUT);
    const guards = model.zones.cellA.groups.filter(function (g) {
        return g.assetId === 'asset-guard';
    })[0];
    const tree = treeModule.createStructureTree({ document: doc, host: element });

    tree.render({ model: model, view: view, selection: [] });
    ['auto', 'cellA', guards.rowId].forEach(function (id) {
        tree.setExpandedForTest(id, true);
    });
    tree.render({ model: model, view: view, selection: [] });
    const before = rows(element).map(function (r) { return r.id; });

    tree.render({ model: model, view: view, selection: ['g1'] });
    assert.deepStrictEqual(
        rows(element).map(function (r) { return r.id; }), before,
        'the row set is identical; only marks changed'
    );
    assert.strictEqual(
        element.querySelector('[data-row-id="g1"]').getAttribute('data-selection'), 'all'
    );
});

check('a moved placement lands under its new zone on the next render', function () {
    const doc = makeDocument();
    const element = host(doc);
    const view = { kind: 'draft', layoutId: 'L1', revision: 'rev-1' };
    const tree = treeModule.createStructureTree({ document: doc, host: element });

    tree.render({ model: structure.deriveStructure(LAYOUT), view: view });
    ['auto', 'cellA', 'cellB'].forEach(function (id) {
        tree.setExpandedForTest(id, true);
    });
    tree.render({ model: structure.deriveStructure(LAYOUT), view: view });

    const countIn = function (zoneId, model) {
        return model.zones[zoneId].directCount;
    };
    const first = structure.deriveStructure(LAYOUT);
    assert.strictEqual(countIn('cellA', first), 3);
    assert.strictEqual(countIn('cellB', first), 1);

    // Drag r1 out of Cell A and into Cell B.
    const moved = {
        zones: LAYOUT.zones,
        placements: LAYOUT.placements.map(function (p) {
            return p.placementId === 'r1' ? place('r1', 'asset-robot', 60, 20) : p;
        }),
    };
    const second = structure.deriveStructure(moved);
    assert.strictEqual(countIn('cellA', second), 2);
    assert.strictEqual(countIn('cellB', second), 2);

    tree.render({
        model: second,
        view: { kind: 'draft', layoutId: 'L1', revision: 'rev-2' },
    });
    const drawn = rows(element);
    const cellB = drawn.filter(function (r) { return r.id === 'cellB'; })[0];
    assert.strictEqual(cellB.expanded, 'true', 'the branch the user opened stayed open');
    const robotUnderB = drawn.some(function (r) {
        return r.kind === 'group' && /robot/i.test(r.label);
    });
    assert.ok(robotUnderB, 'the robot now draws under Cell B');
});

// ------------------------------------------------------ the layout root --
function renamingTree(doc, element, view) {
    const renames = [];
    const tree = treeModule.createStructureTree({
        document: doc, host: element,
        onRename: function (name) { renames.push(name); },
    });
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: view || { kind: 'draft', layoutId: 'L1', revision: 'r',
                        displayName: 'Main Facility' },
        readOnly: view ? Boolean(view.readOnly) : false,
    });
    return { tree: tree, renames: renames };
}

function labelOf(element, rowId) {
    const row = element.querySelector('[data-row-id="' + rowId + '"]');
    return row ? row.childNodes[2].textContent : null;
}

check('the layout is the only root, and every zone hangs under it', function () {
    const doc = makeDocument();
    const element = host(doc);
    renamingTree(doc, element);
    const drawn = rows(element);
    assert.strictEqual(drawn[0].id, LAYOUT_ROW);
    assert.strictEqual(drawn[0].kind, 'layout');
    assert.strictEqual(labelOf(element, LAYOUT_ROW), 'Main Facility');

    const depths = element.querySelectorAll('.ip-fst-row').map(function (row) {
        return row.getAttribute('style');
    });
    assert.strictEqual(depths[0], '--ip-fst-depth:0', 'the layout sits at depth 0');
    assert.ok(
        depths.slice(1).every(function (style) { return style !== '--ip-fst-depth:0'; }),
        'nothing else sits at depth 0'
    );
});

check('the layout row carries the total placement count', function () {
    const doc = makeDocument();
    const element = host(doc);
    renamingTree(doc, element);
    const row = element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]');
    assert.strictEqual(row.childNodes[3].textContent, String(LAYOUT.placements.length));
});

check('a layout with no name falls back rather than showing an empty row', function () {
    const doc = makeDocument();
    const element = host(doc);
    const tree = treeModule.createStructureTree({ document: doc, host: element });
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'r' },
    });
    assert.strictEqual(labelOf(element, LAYOUT_ROW), 'Facility layout');
});

check('the root opens by default and can be collapsed shut', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = renamingTree(doc, element);
    assert.ok(idsBelowRoot(element).length > 0, 'open on arrival');

    const caret = element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]').childNodes[0];
    element.dispatch('click', { target: caret });
    assert.deepStrictEqual(idsBelowRoot(element), [], 'collapsing hides the whole tree');

    // A collapse is remembered, not forgotten back to the default.
    harness.tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'r2',
                displayName: 'Main Facility' },
    });
    assert.deepStrictEqual(idsBelowRoot(element), [], 'still closed after an edit');

    element.dispatch('click', {
        target: element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]').childNodes[0],
    });
    assert.ok(idsBelowRoot(element).length > 0, 'and it opens again');
});

check('double-clicking the layout row opens an editor seeded with the name', function () {
    const doc = makeDocument();
    const element = host(doc);
    renamingTree(doc, element);
    const row = element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]');
    element.dispatch('dblclick', { target: row.childNodes[2] });

    const input = element.querySelector('.ip-fst-rename');
    assert.ok(input, 'an input replaced the label');
    assert.strictEqual(input.value, 'Main Facility');
    assert.strictEqual(doc.activeElement, input, 'and it is focused');
});

check('Enter commits the new name and Escape abandons it', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = renamingTree(doc, element);
    const rowOf = function () {
        return element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]');
    };

    element.dispatch('dblclick', { target: rowOf().childNodes[2] });
    let input = element.querySelector('.ip-fst-rename');
    input.value = 'North Plant';
    input.dispatch('keydown', { target: input, key: 'Enter' });
    assert.deepStrictEqual(harness.renames, ['North Plant']);

    // The tree does not apply the name itself - it asks the host and waits.
    // The host renders again when the session comes back with the new name.
    harness.tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'r2',
                displayName: 'North Plant' },
    });
    assert.strictEqual(labelOf(element, LAYOUT_ROW), 'North Plant');
    assert.ok(!element.querySelector('.ip-fst-rename'), 'the editor is gone');

    element.dispatch('dblclick', { target: rowOf().childNodes[2] });
    input = element.querySelector('.ip-fst-rename');
    input.value = 'Discarded';
    input.dispatch('keydown', { target: input, key: 'Escape' });
    assert.deepStrictEqual(harness.renames, ['North Plant'], 'Escape commits nothing');
    assert.ok(!element.querySelector('.ip-fst-rename'), 'and the editor closes');
    assert.strictEqual(labelOf(element, LAYOUT_ROW), 'North Plant');
});

check('an unchanged or blank name is not sent as a rename', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = renamingTree(doc, element);
    const rowOf = function () {
        return element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]');
    };

    element.dispatch('dblclick', { target: rowOf().childNodes[2] });
    let input = element.querySelector('.ip-fst-rename');
    input.dispatch('keydown', { target: input, key: 'Enter' });   // untouched
    assert.deepStrictEqual(harness.renames, []);

    element.dispatch('dblclick', { target: rowOf().childNodes[2] });
    input = element.querySelector('.ip-fst-rename');
    input.value = '   ';
    input.dispatch('keydown', { target: input, key: 'Enter' });
    assert.deepStrictEqual(harness.renames, [], 'a blank name is refused');
});

check('F2 renames from the keyboard', function () {
    const doc = makeDocument();
    const element = host(doc);
    renamingTree(doc, element);
    const row = element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]');
    element.dispatch('keydown', { target: row, key: 'F2' });
    assert.ok(element.querySelector('.ip-fst-rename'), 'F2 opens the editor');
});

check('a preview cannot be renamed', function () {
    const doc = makeDocument();
    const element = host(doc);
    const harness = renamingTree(doc, element, {
        kind: 'candidate', proposalId: 'p1', layoutId: 'L1', revision: 'r',
        displayName: 'Candidate Facility', readOnly: true,
    });
    const row = element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]');
    assert.strictEqual(row.getAttribute('data-editable'), null);
    element.dispatch('dblclick', { target: row.childNodes[2] });
    element.dispatch('keydown', { target: row, key: 'F2' });
    assert.ok(!element.querySelector('.ip-fst-rename'), 'no editor opens');
    assert.deepStrictEqual(harness.renames, []);
});

check('the layout row selects nothing: it is the document, not an entity', function () {
    const doc = makeDocument();
    const element = host(doc);
    const selected = [];
    const tree = treeModule.createStructureTree({
        document: doc, host: element,
        onSelect: function (kind, payload) { selected.push([kind, payload.rowId]); },
    });
    tree.render({
        model: structure.deriveStructure(LAYOUT),
        view: { kind: 'draft', layoutId: 'L1', revision: 'r', displayName: 'Main' },
    });
    const row = element.querySelector('[data-row-id="' + LAYOUT_ROW + '"]');
    element.dispatch('click', { target: row.childNodes[2] });
    assert.deepStrictEqual(selected, []);
});

console.log('\n' + passed + '/' + passed + ' facility layout structure tree checks passed');
