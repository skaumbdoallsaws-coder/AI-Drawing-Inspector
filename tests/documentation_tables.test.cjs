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
    assert.throws(() => core.normalize(actual.doc), { code: 'unsupported_rich_text_schema' });
    assert.equal(core.readOnlyReason({ richText: actual, richTextCapabilities: core.FULL_CAPABILITIES }),
        'This text box contains a table. Tables cannot be edited here yet.');
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

test('static renderer produces a fixed authored table without editor registration', () => {
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
    assert.ok(!core.IDENTIFIED.includes('table'));
    assert.doesNotMatch(source.slice(0, source.indexOf('function applyBoxStyle(')), /\bTable(?:Row|Cell|Header)?\b/);
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
