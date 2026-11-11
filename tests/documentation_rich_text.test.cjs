'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../static/documentation_rich_text_core.js');

const id = n => `rt-00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const factory = () => { let n = 100; return () => id(++n); };
const text = (value, marks) => ({ type: 'text', text: value, ...(marks ? { marks } : {}) });
const paragraph = (content = [], attrs = {}) => ({ type: 'paragraph', attrs, content });
const doc = content => ({ type: 'doc', content });
const normalize = (value, options = {}) => core.normalize(value, { idFactory: factory(), ...options });

test('normalizes representative Tiptap defaults without changing the projection', () => {
    const input = doc([{ type: 'orderedList', attrs: { id: id(1), start: 2, type: null }, content: [
        { type: 'listItem', attrs: { id: id(2) }, content: [paragraph([
            text('red', [{ type: 'textStyle', attrs: { color: 'rgb(255, 0, 16)', fontFamily: null } },
                { type: 'bold', attrs: {} }]),
            { type: 'hardBreak', attrs: { id: null } },
            text('source', [{ type: 'link', attrs: { href: 'https://example.com/source', target: '_self',
                rel: 'opener', class: 'pasted', title: 'discarded' } }]),
        ], { id: id(3), textAlign: null })] },
    ] }]);
    const result = normalize(input);
    const list = result.doc.content[0];
    assert.deepEqual(list.attrs, { id: id(1), start: 2 });
    const p = list.content[0].content[0];
    assert.deepEqual(p.attrs, { id: id(3) });
    assert.deepEqual(p.content[0].marks, [{ type: 'bold' }, { type: 'textStyle', attrs: { color: '#ff0010' } }]);
    assert.deepEqual(p.content[2].marks, [{ type: 'link', attrs: { href: 'https://example.com/source', ...core.LINK } }]);
    assert.equal(core.plainText(result), 'red\nsource');
    assert.deepEqual(normalize(result), result);
});

test('bounded colors and empty textStyle marks', () => {
    for (const [value, expected] of [['RED', '#ff0000'], ['rebeccapurple', '#663399'], ['#AbC', '#aabbcc'],
        ['#AABBCC', '#aabbcc'], ['tomato', '#ff6347'], ['LightSlateGrey', '#778899'], ['rgb(0, 128, 255)', '#0080ff'], ['rgb(256,0,0)', null],
        ['rgba(0,0,0,0)', null], ['transparent', null], ['url(file:///a)', null], [null, null]]) {
        assert.equal(core.color(value), expected);
    }
    const result = normalize(doc([paragraph([text('plain', [{ type: 'textStyle', attrs: { color: null } }]),
        text('also plain', [{ type: 'textStyle', attrs: {} }])])]));
    assert.equal(result.doc.content[0].content[0].marks, undefined);
    assert.equal(result.doc.content[0].content[1].marks, undefined);
});

test('only absolute HTTP(S) links survive; no input attributes reach the server', () => {
    for (const value of ['javascript:alert(1)', 'data:text/html,a', 'file:///c:/a', 'mailto:a@b.com',
        '//host/a', '/path', 'c:\\a', '\\\\server\\share', 'https://u:p@host/', 'http://host:99999',
        'https://', 'https://host/a\nb', 'https://@host/a', 'https:///host/a']) {
        // The URL constructor repairs a missing authority; the client must not.
        assert.equal(core.href(value), null, value);
        const result = normalize(doc([paragraph([text('data', [{ type: 'link', attrs: { href: value } }])])]));
        assert.equal(result.doc.content[0].content[0].marks, undefined);
    }
    assert.equal(core.href('HTTPS://example.com/a?q=x#z'), 'HTTPS://example.com/a?q=x#z');
});

test('IDs are assigned to every block and break, and split/pasted duplicates are re-keyed', () => {
    const result = normalize(doc([paragraph([text('one'), { type: 'hardBreak' }], { id: id(1) }),
        paragraph([text('split')], { id: id(1) }),
        { type: 'heading', attrs: { level: 3, id: 'RT-INVALID' }, content: [text('Title')] },
        { type: 'bulletList', content: [{ type: 'listItem', content: [paragraph([text('item')])] }] },
    ]));
    const ids = [...core.nodeIds(result)];
    assert.equal(ids.length, 7);
    assert.ok(ids.every(value => core.ID.test(value)));
    assert.equal(result.doc.content[0].attrs.id, id(1));
    assert.notEqual(result.doc.content[1].attrs.id, id(1));
    assert.equal(result.doc.attrs, undefined);
    assert.equal(result.doc.content[0].content[0].attrs, undefined);
});

test('other fields reserve their IDs, while the current field keeps its IDs', () => {
    const own = { pageId: 'p', targetId: 'one', richText: normalize(doc([paragraph([], { id: id(1) })])) };
    const other = { pageId: 'p', targetId: 'two', richText: normalize(doc([paragraph([], { id: id(2) })])) };
    const reserved = core.reservedIds([own, other], own);
    assert.deepEqual([...reserved], [id(2)]);
    const result = normalize(doc([paragraph([], { id: id(1) }), paragraph([], { id: id(2) }),
        paragraph([], { id: id(2) })]), { reservedIds: reserved });
    const ids = [...core.nodeIds(result)];
    assert.equal(ids.length, 3);
    assert.ok(ids.includes(id(1)) && !ids.includes(id(2)));
});

for (const value of ['', '\n', '\n\n', 'a\r\nb', '\t', '\t a\t b ', ' leading', 'trailing ',
    '  repeated   spaces  ', 'emoji \u{1f642}', 'e\u0301', ' \n\r\n\t\u{1f642}e\u0301  ']) {
    test('lossless plain conversion / multiline paste: ' + JSON.stringify(value), () => {
        const envelope = core.fromPlain(value, { idFactory: factory() });
        assert.equal(core.plainText(envelope), value);
        const pasted = normalize(doc([paragraph(envelope.doc.content[0].content || [])]));
        assert.equal(core.plainText(pasted), value);
        assert.equal(envelope.doc.content.length, 1);
        assert.equal(envelope.doc.content[0].type, 'paragraph');
    });
}

test('node, byte, depth, list and ordered-start bounds are checked before saving', () => {
    const tooLarge = error => error.code === 'rich_text_too_large';
    normalize(doc([paragraph(Array.from({ length: 510 }, () => text('a')))]));
    assert.throws(() => normalize(doc([paragraph(Array.from({ length: 511 }, () => text('a')))])), tooLarge);
    assert.throws(() => normalize(doc([paragraph([text('x'.repeat(24576))])])), tooLarge);
    assert.throws(() => normalize(doc([paragraph([text('\u{1f642}'.repeat(6200))])])), tooLarge);
    function list(level) {
        return { type: 'bulletList', content: [{ type: 'listItem', content: [paragraph([text('item')]),
            ...(level > 1 ? [list(level - 1)] : [])] }] };
    }
    normalize(doc([list(3)]));
    assert.equal(normalize(doc([list(6)])).schemaVersion, 2);
    assert.throws(() => normalize(doc([list(7)])), tooLarge);
    let deep = text('a');
    for (let n = 0; n < 15; n++) deep = paragraph([deep]);
    assert.throws(() => normalize(doc([deep])), tooLarge);
    for (const start of [0, 10000, 1.5, true]) assert.throws(() => normalize(doc([
        { type: 'orderedList', attrs: { start }, content: [{ type: 'listItem', content: [paragraph()] }] },
    ])));
});

test('size includes server-owned link attributes and UTF-8 canonical JSON', () => {
    const source = normalize(doc([paragraph([text('link', [{ type: 'link', attrs: { href: 'https://example.com' } }])])]));
    const server = structuredClone(source);
    Object.assign(server.doc.content[0].content[0].marks[0].attrs, core.LINK);
    const overhead = Buffer.byteLength(core.canonical(server)) - 4;
    const make = n => doc([paragraph([text('x'.repeat(n), [{ type: 'link', attrs: { href: 'https://example.com' } }])])]);
    normalize(make(core.LIMITS.bytes - overhead));
    assert.throws(() => normalize(make(core.LIMITS.bytes - overhead + 1)), { code: 'rich_text_too_large' });
});

test('unsupported nodes, marks and malformed text remain errors', () => {
    for (const type of ['image', 'video', 'table', 'codeBlock', 'script']) {
        assert.throws(() => normalize(doc([{ type, attrs: { src: 'file:///secret' } }])));
    }
    assert.throws(() => normalize(doc([paragraph([text('a', [{ type: 'backgroundColor' }])])])));
    assert.throws(() => normalize(doc([paragraph([text('\ud800')])])));
    assert.throws(() => normalize(doc([paragraph([text('')])])));
});

test('read-only guard checks stored versions, features and depth without modifying the value', () => {
    const richText = normalize(doc([paragraph([text('kept', [{ type: 'strike' }])])]));
    const before = JSON.stringify(richText);
    assert.equal(core.readOnlyReason({ richText, richTextCapabilities: core.FULL_CAPABILITIES }), '');
    for (const capabilities of [
        { ...core.FULL_CAPABILITIES, schemaVersions: [1] },
        { ...core.FULL_CAPABILITIES, features: core.FEATURES.filter(name => name !== 'strike') },
    ]) assert.match(core.readOnlyReason({ richText, richTextCapabilities: capabilities }), /read-only/);
    const list = normalize(doc([{ type: 'bulletList', content: [{ type: 'listItem', content: [paragraph([text('item')])] }] }]));
    assert.match(core.readOnlyReason({ richText: list, richTextCapabilities: { ...core.FULL_CAPABILITIES, listDepth: 0 } }), /read-only/);
    assert.equal(core.readOnlyReason({ text: 'old plain field' }), '');
    const nonminimal = normalize(doc([paragraph([text('body')])])); nonminimal.schemaVersion = 2;
    assert.match(core.readOnlyReason({ richText: nonminimal, richTextCapabilities: { ...core.FULL_CAPABILITIES, schemaVersions: [1] } }), /read-only/);
    assert.equal(JSON.stringify(richText), before);
});

test('rich font tokens and legacy box aliases use the export families', () => {
    assert.deepEqual(Object.keys(core.FONT_MAP), ['Arial', 'Helvetica', 'Times New Roman', 'Courier New']);
    assert.equal(core.font('Helvetica').canvas, 'Arial');
    assert.equal(core.font('Georgia').canvas, 'Times New Roman');
    assert.equal(core.font('Inter').canvas, 'Arial');
    assert.equal(core.font('Arial').ascent, .9053);
    assert.deepEqual(core.RENDER_MARKS, ['bold', 'italic', 'underline', 'strike', 'subscript', 'superscript', 'highlight', 'textStyle', 'link']);
});

for (const vector of require('./fixtures/rich_text_v2_vectors.json')) {
    test('shared typography vector: ' + vector.name, () => {
        if (vector.code) assert.throws(() => core.normalize(vector.input), { code: vector.code });
        else assert.deepEqual(core.normalize(vector.input), vector.expected);
    });
}

test('paste maps only token families, px sizes and bounded paragraph attributes', () => {
    const raw = doc([paragraph([
        text('dropped', [{ type: 'textStyle', attrs: { fontFamily: 'Georgia, Arial', fontSize: '12pt', color: 'unresolvable' } }]),
        text('kept', [{ type: 'textStyle', attrs: { fontFamily: '"hELVetica", sans-serif', fontSize: '16.26px', color: 'rgb(17, 34, 51)' } }]),
        text('outside', [{ type: 'textStyle', attrs: { fontSize: '48.01px' } }]),
        text('low', [{ type: 'textStyle', attrs: { fontSize: '5.99px' } }]),
    ], { textAlign: 'justify', indent: 73, spaceBefore: -1, spaceAfter: 36.5, lineHeight: 2.05, namedStyle: null })]);
    const result = normalize(raw);
    const p = result.doc.content[0];
    assert.deepEqual(p.attrs, { id: id(101) });
    assert.equal(p.content[0].marks, undefined);
    assert.deepEqual(p.content[1].marks, [{ type: 'textStyle', attrs: { fontFamily: 'Helvetica', fontSize: 16.5, color: '#112233' } }]);
    assert.equal(p.content[2].marks, undefined);
    assert.equal(p.content[3].marks, undefined);
    assert.equal(result.schemaVersion, 2);
    const dropped = normalize(doc([raw.content[0].content.length && paragraph([raw.content[0].content[0]], { textAlign: 'justify' })]));
    assert.equal(dropped.schemaVersion, 1);
});

test('Tiptap null defaults disappear, explicit server defaults remain schema two', () => {
    const defaults = Object.fromEntries(core.PARAGRAPH_ATTRS.map(name => [name, null]));
    const value = normalize(doc([paragraph([text('body')], defaults)]));
    assert.equal(value.schemaVersion, 1);
    for (const [name, number] of [['indent', 0], ['spaceBefore', 0], ['spaceAfter', 0], ['lineHeight', 1.2], ['textAlign', 'left']]) {
        const explicit = structuredClone(value); explicit.schemaVersion = 2;
        explicit.doc.content[0].attrs[name] = number;
        assert.equal(core.normalize(explicit).schemaVersion, 2);
    }
});

test('editor representation round-trips the minimal version and all typography', () => {
    const value = normalize(doc([paragraph([text('body', [{ type: 'textStyle', attrs: { fontSize: '9.5px', fontFamily: 'Arial' } }])],
        { namedStyle: 'note', indent: 18, spaceBefore: 3.5, spaceAfter: 4, lineHeight: 1.15, textAlign: 'center' })]));
    const editing = core.editorDocument(value);
    assert.equal(editing.content[0].content[0].marks[0].attrs.fontSize, '9.5px');
    assert.deepEqual(normalize(editing), value);
    assert.throws(() => normalize(editing, { capabilities: { ...core.FULL_CAPABILITIES, features: [] } }),
        { code: 'unsupported_rich_text_feature' });
});


test('the box underline wrapper is editor presentation and never becomes stored formatting', () => {
    const value = normalize(doc([paragraph([text('box'), text(' own', [{ type: 'underline' }, { type: 'textStyle', attrs: { fontSize: '24px' } }])])]));
    const editing = core.editorDocument(value, { boxUnderline: true });
    assert.ok(editing.content[0].content.every(run => run.marks.some(mark => mark.type === 'documentationInheritedUnderline')));
    assert.deepEqual(normalize(editing), value);
    const foreign = structuredClone(value);
    foreign.doc.content[0].content[0].marks = [{ type: 'documentationInheritedUnderline' }];
    assert.throws(() => core.normalize(foreign), { code: 'invalid_rich_text' });
});


test('generated base line height is explicit in both static and editing wrappers', () => {
    const fs = require('node:fs'), vm = require('node:vm');
    const source = fs.readFileSync(require.resolve('../static/documentation_rich_text.js'), 'utf8');
    const apply = source.slice(source.indexOf('function applyBoxStyle('), source.indexOf('// Only the validated read'));
    const render = source.slice(source.indexOf('function render('), source.indexOf('// Paste reads'));
    class Element {
        constructor(tag) { this.tagName = tag.toUpperCase(); this.style = {}; this.dataset = {}; this.children = []; }
        appendChild(child) { this.children.push(child); return child; }
        replaceChildren(...children) { this.children = children; }
        prepend(child) { this.children.unshift(child); }
        get firstElementChild() { return this.children[0]; }
        setAttribute() {} addEventListener() {}
    }
    const context = vm.createContext({ core, document: { createElement: tag => new Element(tag) } });
    vm.runInContext(apply + render, context);
    for (const base of [1.35, 1.4, 1.6, 10 / 7.4]) {
        const style = { fontFamily: 'Arial', fontSize: 7.4, baseLineHeight: base, color: '#596a76' };
        const host = new Element('div');
        context.render(host, normalize(doc([paragraph([text('Copy')])])), style);
        const editing = new Element('div'); context.applyBoxStyle(editing, style);
        assert.deepEqual(host.children[0].style, editing.style);
        assert.equal(editing.style.lineHeight, String(base));
        assert.equal(editing.style.fontSize, '7.4px');
    }
    assert.equal(core.baseLineHeight({}), 1.2);
    const notice = new Element('div');
    context.render(notice, normalize(doc([paragraph([text('Copy')])])), { signalWord: 'NOTICE', baseLineHeight: 1.4 });
    const signal = notice.children[0].children[0].children[0];
    assert.equal(signal.textContent, 'NOTICE');
    assert.equal(signal.contentEditable, 'false');
    assert.match(source, /applyBoxStyle\(editorHost, options.boxStyle\)/);
    assert.match(source, /Number\(value\) === base \? null/);
});

test('notice and caption capability sets register only allowed schema extensions', () => {
    const fs = require('node:fs'), vm = require('node:vm');
    const source = fs.readFileSync(require.resolve('../static/documentation_rich_text.js'), 'utf8');
    const extensionSource = source.slice(source.indexOf('function extensions('), source.indexOf('function mount('));
    const fake = name => ({ name, extend(spec) { return { ...fake(name), spec }; }, configure(options) { return { ...this, options }; } });
    const kit = Object.fromEntries(['StarterKit', 'TextStyle', 'Color', 'FontFamily', 'FontSize', 'Highlight', 'Subscript', 'Superscript', 'TextAlign'].map(n => [n, fake(n)]));
    kit.Extension = kit.Mark = { create: value => value };
    const context = vm.createContext({ kit, core, cssColor: core.color });
    vm.runInContext(extensionSource, context);
    const caps = { schemaVersions: [1, 2], features: ['bold', 'italic', 'underline', 'strike', 'subscript', 'superscript', 'highlight', 'color', 'link'], listDepth: 0 };
    const installed = context.extensions(caps, () => {}, () => {}, false, 'NOTICE');
    const starter = installed.find(e => e.name === 'StarterKit');
    for (const name of ['heading', 'bulletList', 'orderedList', 'listItem', 'listKeymap']) assert.equal(starter.options[name], false);
    for (const name of ['FontFamily', 'FontSize', 'TextAlign']) assert.ok(!installed.some(e => e.name === name));
    assert.ok(installed.some(e => e.name === 'Highlight'));
    const global = installed.find(e => e.name === 'documentationParagraphTypography').addGlobalAttributes();
    assert.equal(Object.keys(global[0].attributes).length, 0);
    const size = normalize(doc([paragraph([text('too large', [{ type: 'textStyle', attrs: { fontSize: '12px' } }])])]));
    assert.match(core.readOnlyReason({ richText: size, richTextCapabilities: caps }), /read-only/);
    const marks = normalize(doc([paragraph([text('allowed', [{ type: 'italic' }, { type: 'highlight', attrs: { color: '#aabbcc' } }])])]));
    assert.equal(core.readOnlyReason({ richText: marks, richTextCapabilities: caps }), '');
});
