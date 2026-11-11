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
    assert.deepEqual(p.content[2].marks, [{ type: 'link', attrs: { href: 'https://example.com/source' } }]);
    assert.equal(core.plainText(result), 'red\nsource');
    assert.deepEqual(normalize(result), result);
});

test('bounded colors and empty textStyle marks', () => {
    for (const [value, expected] of [['RED', '#ff0000'], ['rebeccapurple', '#663399'], ['#AbC', '#aabbcc'],
        ['#AABBCC', '#aabbcc'], ['rgb(0, 128, 255)', '#0080ff'], ['rgb(256,0,0)', null],
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
    assert.throws(() => normalize(doc([list(4)])), tooLarge);
    let deep = text('a');
    for (let n = 0; n < 13; n++) deep = paragraph([deep]);
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
    assert.throws(() => normalize(doc([paragraph([text('a', [{ type: 'strike' }])])])));
    assert.throws(() => normalize(doc([paragraph([text('\ud800')])])));
    assert.throws(() => normalize(doc([paragraph([text('')])])));
});

test('schema 2 is readable but cannot enter the schema 1 editor or save normalization', () => {
    const richText = { format: 'tiptap', schemaVersion: 2, doc: doc([paragraph([text('kept')])]) };
    const before = JSON.stringify(richText);
    assert.match(core.readOnlyReason({ richText }), /cannot be edited here yet/);
    assert.match(core.readOnlyReason({ richText }), /Sage/);
    assert.equal(core.readOnlyReason({ richText: { ...richText, schemaVersion: 1 } }), '');
    assert.equal(core.readOnlyReason({ text: 'old plain field' }), '');
    assert.throws(() => normalize(richText), { code: 'unsupported_rich_text_schema' });
    for (const attr of ['textAlign', 'indent', 'spaceBefore', 'spaceAfter', 'lineHeight']) {
        assert.throws(() => normalize(doc([paragraph([text('kept')], { [attr]: attr === 'textAlign' ? 'left' : 1 })])),
            { code: 'unsupported_rich_text_schema' });
    }
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
