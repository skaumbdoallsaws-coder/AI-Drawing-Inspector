'use strict';

/**
 * FT2 acceptance for the structure tree renderer.
 * Covers lazy expansion, grouping, the unzoned branch, the empty state, the
 * read-only preview rule, and the two-key expansion contract from section 6 -
 * including the four-step sequence the third review asked for.
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
    assert.deepStrictEqual(drawn.map(function (r) { return r.id; }), ['auto', 'unzoned']);
    assert.strictEqual(drawn[0].expanded, 'false', 'lazy: children not built yet');
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
    tree.render({ model: structure.deriveStructure({}), view: { kind: 'draft' } });
    assert.strictEqual(rows(element).length, 0);
    assert.strictEqual(element.childNodes.length, 1);
    assert.ok(/No zones or equipment yet/.test(element.childNodes[0].textContent));
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
        onSelect: function (kind, rowId) { selected.push([kind, rowId]); },
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
        onSelect: function (kind, rowId) { selected.push([kind, rowId]); },
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

console.log('\n' + passed + '/' + passed + ' facility layout structure tree checks passed');
