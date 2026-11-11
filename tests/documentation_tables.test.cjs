'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const core = require('../static/documentation_rich_text_core.js');
const id = n => 'rt-00000000-0000-4000-8000-' + String(n).padStart(12, '0');

function value() {
    let n = 1;
    const node = (type, content, attrs = {}) => ({ type, attrs: { id: id(n++), ...attrs }, ...(content ? { content } : {}) });
    const paragraph = text => node('paragraph', [{ type: 'text', text }]);
    const columns = [334, 333, 333].map(width => ({ id: id(n++), width }));
    const rows = [
        node('tableRow', [node('tableHeader', [paragraph('Wide')], { colspan: 2, fill: '#AABBCC', verticalAlign: 'middle' }),
            node('tableHeader', [paragraph('Tall')], { rowspan: 2 })]),
        node('tableRow', [node('tableCell', [paragraph('Left')]), node('tableCell', [paragraph('Right')], { verticalAlign: 'bottom' })]),
    ];
    return { format: 'tiptap', schemaVersion: 3, doc: { type: 'doc', content: [
        node('table', rows, { ownership: 'authored', style: 'grid', columns }),
    ] } };
}

test('schema 3 normalizes without losing columns, cell attributes or IDs', () => {
    const input = value(), actual = core.normalize(input);
    assert.equal(actual.schemaVersion, 3);
    assert.equal(core.plainText(actual), 'Wide\nTall\nLeft\nRight');
    assert.equal(actual.doc.content[0].content[0].content[0].attrs.fill, '#aabbcc');
    assert.deepEqual(core.nodeIds(actual), core.nodeIds(input));
    assert.deepEqual(core.usedFeatures(actual), { features: ['table'], listDepth: 0 });
    assert.deepEqual(core.normalize(actual), actual);
    for (const version of [1, 2]) assert.throws(() => core.normalize({ ...input, schemaVersion: version }),
        { code: 'unsupported_rich_text_schema' });
    assert.deepEqual(core.normalize(actual.doc), actual);
    assert.equal(core.readOnlyReason({ richText: actual, richTextCapabilities: core.FULL_CAPABILITIES }),
        '');
    assert.throws(() => core.normalize(actual, { capabilities: { schemaVersions: [1, 2], features: ['bold'], listDepth: 0 } }),
        { code: 'unsupported_rich_text_feature' });
});

test('table grid, placement, IDs and widths fail closed', () => {
    for (const [mutation, code] of [
        [v => v.doc.content[0].attrs.columns[0].width++, 'invalid_table_grid'],
        [v => v.doc.content[0].attrs.columns[0].id = v.doc.content[0].attrs.id, 'rich_text_node_id_collision'],
        [v => v.doc.content[0].content[0].content[0].attrs.colspan = 3, 'invalid_table_grid'],
        [v => v.doc.content[0].content[1].content = [], 'invalid_table_grid'],
        [v => v.doc.content[0].content[1].content[0].content[0].attrs.namedStyle = 'title', 'invalid_rich_text'],
    ]) {
        const input = value(); mutation(input);
        assert.throws(() => core.normalize(input), { code });
    }
});

test('static renderer produces a fixed authored table', () => {
    const source = fs.readFileSync(require.resolve('../static/documentation_rich_text.js'), 'utf8');
    const apply = source.slice(source.indexOf('function applyBoxStyle('), source.indexOf('// Only the validated read'));
    const render = source.slice(source.indexOf('function render('), source.indexOf('// Paste reads'));
    class Element {
        constructor(tag) { this.tagName = tag.toUpperCase(); this.style = {}; this.dataset = {}; this.children = []; this.attributes = {}; }
        appendChild(child) { this.children.push(child); return child; }
        replaceChildren(...children) { this.children = children; }
        setAttribute(name, value) { this.attributes[name] = value; }
        addEventListener() {}
        get firstElementChild() { return this.children[0]; }
    }
    const context = vm.createContext({ core, document: { createElement: tag => new Element(tag) } });
    vm.runInContext(apply + render, context);
    const canonical = core.normalize(value()), host = new Element('div');
    context.render(host, canonical, { fontFamily: 'Arial', fontSize: 10 });
    const table = host.children[0].children[0], model = canonical.doc.content[0];
    assert.equal(table.tagName, 'TABLE');
    assert.equal(table.dataset.richId, model.attrs.id);
    assert.equal(table.dataset.tableStyle, 'grid');
    assert.equal(table.children[0].tagName, 'COLGROUP');
    assert.deepEqual(Array.from(table.children[0].children, c => c.style.width), ['33.4%', '33.3%', '33.3%']);
    assert.deepEqual(Array.from(table.children[0].children, c => c.dataset.richId), model.attrs.columns.map(c => c.id));
    for (const [index, row] of model.content.entries()) {
        const drawn = table.children[index + 1];
        assert.equal(drawn.tagName, 'TR');
        assert.equal(drawn.dataset.richId, row.attrs.id);
        for (const [cellIndex, cell] of row.content.entries()) {
            const drawCell = drawn.children[cellIndex];
            assert.equal(drawCell.tagName, cell.type === 'tableHeader' ? 'TH' : 'TD');
            assert.equal(drawCell.dataset.richId, cell.attrs.id);
            assert.equal(drawCell.colSpan, cell.attrs.colspan || 1);
            assert.equal(drawCell.rowSpan, cell.attrs.rowspan || 1);
            assert.equal(drawCell.style.verticalAlign, cell.attrs.verticalAlign || 'top');
            assert.equal(drawCell.style.backgroundColor, cell.attrs.fill || (cell.type === 'tableHeader' ? '#e9eef2' : 'transparent'));
        }
    }
    for (const name of ['table', 'tableRow', 'tableCell', 'tableHeader']) assert.ok(core.IDENTIFIED.includes(name));
    assert.match(source.slice(0, source.indexOf('function applyBoxStyle(')), /\bTableRow\b/);
    const css = fs.readFileSync(require.resolve('../static/documentation_rich_text.css'), 'utf8');
    assert.match(css, /border-collapse: collapse; table-layout: fixed; width: 100%/);
    assert.match(css, /border: 1px solid #8a98a5; padding: 4px; text-align: left/);
});

test('FEATURES remains the Python feature vocabulary including table', () => {
    const python = fs.readFileSync(require.resolve('../ai_inspector/documentation/rich_text.py'), 'utf8');
    const literal = python.match(/FEATURES = \(([^]*?)\)\n/)[1];
    const names = Array.from(literal.matchAll(/"([^"]+)"/g), match => match[1]);
    assert.deepEqual(core.FEATURES, names);
    assert.deepEqual(core.FULL_CAPABILITIES.schemaVersions, [1, 2, 3]);
});


test('editor table defaults normalize to the stored server shape, preserving all structural IDs', () => {
    const expected = core.normalize(value()), doc = core.editorDocument(expected);
    const table = doc.content[0];
    for (const row of table.content) for (const cell of row.content) {
        cell.attrs = { colspan: 1, rowspan: 1, colwidth: null, fill: null, verticalAlign: 'top', ...cell.attrs };
    }
    assert.deepEqual(core.normalize(doc), expected);
    assert.deepEqual(core.normalize({ ...expected, doc }, { editor: true }), expected);
    assert.deepEqual(core.nodeIds(core.normalize(doc)), core.nodeIds(expected));
    assert.match(core.readOnlyReason({ richText: expected, richTextCapabilities: {
        ...core.FULL_CAPABILITIES, schemaVersions: [1, 2] } }), /read-only/);
    assert.match(core.readOnlyReason({ richText: expected, richTextCapabilities: {
        ...core.FULL_CAPABILITIES, features: core.FEATURES.filter(f => f !== 'table') } }), /read-only/);
    const paragraph = { type: 'paragraph', attrs: { id: null }, content: [{ type: 'text', text: 'New' }] };
    doc.content[0].content[0].content[0].content.push(paragraph);
    const saved = core.normalize(doc, { idFactory: () => id(999) });
    assert.equal(saved.doc.content[0].content[0].content[0].content.at(-1).attrs.id, id(999));
});

test('editor never allocates missing table, row, cell or column IDs', () => {
    const paths = [
        doc => doc.content[0], doc => doc.content[0].content[0],
        doc => doc.content[0].content[0].content[0],
    ];
    for (const get of paths) for (const missing of [null, undefined, 'foreign']) {
        const doc = core.editorDocument(core.normalize(value()));
        get(doc).attrs.id = missing;
        assert.throws(() => core.normalize(doc), { code: 'invalid_table_grid' });
    }
    const doc = core.editorDocument(core.normalize(value()));
    delete doc.content[0].attrs.columns[0].id;
    assert.throws(() => core.normalize(doc), { code: 'invalid_table_grid' });
});

test('table guard permits only content changes and complete removal', () => {
    const old = core.normalize(value()).doc, original = core.canonical(old);
    for (const change of [
        doc => doc.content[0].content[0].content[0].content[0].content[0].text = 'Edited',
        doc => doc.content[0].content[0].content[0].content.push({ type: 'paragraph', attrs: { id: null } }),
        doc => doc.content[0].content[0].content[0].content[0].content = [],
        doc => doc.content = [{ type: 'paragraph', attrs: { id: null } }],
    ]) {
        const next = structuredClone(old); change(next);
        assert.equal(core.tableGuard(old, next), null);
    }
    for (const change of [
        doc => delete doc.content[0].attrs.id,
        doc => doc.content[0].attrs.id = id(900),
    ]) {
        const next = structuredClone(old); change(next);
        assert.equal(core.tableGuard(old, next), core.TABLE_PASTE_NOTICE);
    }
    for (const change of [
        doc => doc.content.push(structuredClone(doc.content[0])),
        doc => doc.content = [{ type: 'bulletList', content: [{ type: 'listItem', content: doc.content }] }],
        doc => doc.content[0].attrs.style = 'plain',
        doc => doc.content[0].attrs.ownership = 'generated',
        doc => doc.content[0].attrs.columns[0].width++,
        doc => doc.content[0].attrs.columns[0].id = id(901),
        doc => doc.content[0].content.reverse(),
        doc => doc.content[0].content[0].attrs.id = id(902),
        doc => doc.content[0].content[0].content[0].attrs.id = id(903),
        doc => doc.content[0].content[0].content[0].type = 'tableCell',
        doc => doc.content[0].content[0].content[0].attrs.colspan = 1,
        doc => doc.content[0].content[0].content[0].attrs.rowspan = 2,
        doc => doc.content[0].content[0].content[0].attrs.fill = '#123456',
        doc => doc.content[0].content[0].content[0].attrs.verticalAlign = 'bottom',
    ]) {
        const next = structuredClone(old); change(next);
        assert.equal(core.tableGuard(old, next), core.TABLE_NOTICE);
    }
    assert.equal(core.canonical(old), original);
    const next = structuredClone(old);
    next.content[0].content[0].content[0].content[0].content[0].text = 'Different text';
    assert.equal(core.tableSignature(old.content[0]), core.tableSignature(next.content[0]));
    assert.equal(core.tableGuard({ type: 'doc', content: [] }, old), core.TABLE_PASTE_NOTICE);
});

const widthVectors = JSON.parse(fs.readFileSync(require.resolve('./fixtures/documentation_table_width_vectors.json'), 'utf8'));
test('column widths reproduce all 200 server largest-remainder vectors', () => {
    assert.equal(widthVectors.cases.length, 200);
    for (const vector of widthVectors.cases) {
        const before = JSON.stringify(vector.columns);
        assert.deepEqual(core.tableWidths(vector.columns, vector.columnId, vector.percent), vector.expected);
        assert.equal(JSON.stringify(vector.columns), before);
    }
});
test('equal widths and afterId use the top-level block, including lists and tables', () => {
    for (let n = 1; n <= 12; n++) {
        const widths = core.equalTableWidths(Array.from({ length: n }, (_, i) => ({ id: id(i), width: 1 })));
        assert.equal(widths.reduce((a, b) => a + b), 1000);
        assert.deepEqual(widths, Array.from({ length: n }, (_, i) => Math.floor(1000 / n) + (i < 1000 % n ? 1 : 0)));
    }
    const doc = { type: 'doc', content: ['paragraph', 'bulletList', 'table'].map((type, i) => ({
        type, attrs: { id: id(i) }, content: [{ type: 'paragraph', attrs: { id: id(100 + i) } }] })) };
    for (let i = 0; i < 3; i++) assert.equal(core.tableAfterId(doc, i), id(i));
    assert.equal(core.tableAfterId(doc, 3), null);
});

test('table extensions use static geometry, paragraph-only cells and no node view', () => {
    const source = fs.readFileSync(require.resolve('../static/documentation_rich_text.js'), 'utf8');
    const fake = name => ({ name, extend(spec) { return { ...fake(name), spec }; },
        configure(options) { return { ...this, options }; } });
    const kit = Object.fromEntries(['StarterKit', 'TextStyle', 'Color', 'FontFamily', 'FontSize', 'Highlight',
        'Subscript', 'Superscript', 'TextAlign', 'Table', 'TableRow', 'TableCell', 'TableHeader'].map(n => [n, fake(n)]));
    kit.Extension = kit.Mark = { create: value => value };
    const context = vm.createContext({ kit, core, cssColor: core.color });
    vm.runInContext(source.slice(source.indexOf('function extensions('), source.indexOf('function mount(')), context);
    const installed = context.extensions(core.FULL_CAPABILITIES, () => {}, () => {}, false);
    const table = installed.find(e => e.name === 'Table');
    assert.equal(table.options.resizable, false); assert.equal(table.options.View, null);
    const model = core.normalize(value()).doc.content[0], rendered = table.spec.renderHTML({ node: model });
    assert.equal(rendered[0], 'table');
    assert.equal(rendered[1]['data-rich-id'], model.attrs.id);
    assert.equal(rendered[1]['data-table-style'], 'grid');
    assert.equal(rendered[2][0], 'colgroup');
    assert.deepEqual(Array.from(rendered[2].slice(1), col => col[1].style), ['width: 33.4%', 'width: 33.3%', 'width: 33.3%']);
    assert.ok(!JSON.stringify(rendered).includes('min-width'));
    for (const name of ['TableCell', 'TableHeader']) {
        const extension = installed.find(e => e.name === name);
        assert.equal(extension.spec.content, 'paragraph+');
        const cell = extension.spec.renderHTML({ node: { attrs: { id: id(300), colspan: 1, rowspan: 1 } } });
        assert.equal(cell[0], name === 'TableHeader' ? 'th' : 'td');
        assert.match(cell[1].style, /vertical-align: top/);
        assert.match(cell[1].style, name === 'TableHeader' ? /#e9eef2/ : /transparent/);
        const attributes = extension.spec.addAttributes.call({ parent: () => ({ colwidth: { default: null } }) });
        assert.equal(attributes.colwidth.default, null);
    }
    const moves = [];
    const keys = table.spec.addKeyboardShortcuts.call({ parent: () => ({}), editor: {
        isActive: () => true, commands: { goToNextCell: () => { moves.push(1); return false; },
            goToPreviousCell: () => { moves.push(-1); return false; } } } });
    assert.equal(keys.Tab(), true); assert.equal(keys['Shift-Tab'](), true);
    assert.deepEqual(moves, [1, -1]);
    const noTable = context.extensions({ ...core.FULL_CAPABILITIES, schemaVersions: [1, 2] }, () => {}, () => {}, false);
    assert.ok(!noTable.some(e => e.name === 'Table'));
});


test('table grid positions identify a merged survivor and the replacement position', () => {
    const table = core.normalize(value()).doc.content[0], { cells, grid } = core.tableCells(table);
    assert.equal(cells.length, 4);
    assert.equal(grid[0][0], grid[0][1]);
    assert.equal(grid[0][2], grid[1][2]);
    assert.deepEqual(cells.map(c => [c.row, c.column]), [[0, 0], [0, 2], [1, 0], [1, 1]]);
    assert.equal(grid[1][2].cell.attrs.id, table.content[0].content[1].attrs.id);
});
