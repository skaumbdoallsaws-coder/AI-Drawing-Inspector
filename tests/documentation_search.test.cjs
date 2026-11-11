const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const search = require('../static/documentation_search.js');
const symbols = require('../static/documentation_symbols.js');

for (const cluster of ['🙂', '🇺🇸', '👍🏽', '👩‍🔧', '1️⃣', 'e\u0301', '\r\n', '\u1100\u1161\u11a8', '\u0600A',
    // Extend and SpacingMark characters outside \p{M}, and a Prepend character outside the Arabic block.
    'e\u200c', '\u0e01\u0e33', '\u0e81\u0eb3', '\uff76\uff9e', '\uff8a\uff9f', '\u0d4eA']) {
    test('code points and grapheme boundaries: ' + JSON.stringify(cluster), () => {
        const value = search.points('a' + cluster + 'z');
        const n = Array.from(cluster).length;
        assert.equal(value.length, n + 2);
        assert.equal(value.slice(1, n + 1), cluster);
        for (let i = 0; i <= value.length; i++) assert.equal(value.fromUTF16(value.toUTF16(i)), i);
        assert.equal(search.boundary(value.chars, 1), true);
        assert.equal(search.boundary(value.chars, n + 1), true);
        for (let i = 2; i <= n; i++) assert.equal(search.boundary(value.chars, i), false);
        if (cluster.codePointAt(0) > 0xffff) assert.throws(() => value.fromUTF16(2), /splits/);
    });
}

test('context is bounded in code points without cutting a grapheme', () => {
    const text = 'e\u0301'.repeat(30) + 'X' + '🇺🇸'.repeat(30);
    assert.deepEqual(search.snippet(text, 60, 61), { before: 'e\u0301'.repeat(20), match: 'X', after: '🇺🇸'.repeat(20) });
    assert.deepEqual(search.snippet('e\u0301' + 'a'.repeat(39) + 'X', 41, 42), { before: 'a'.repeat(39), match: 'X', after: '' });
});

test('replace-all preview excludes read-only targets and groups at 100', () => {
    const matches = Array.from({ length: 205 }, (_, index) => ({ targetId: 'one', start: index * 2, end: index * 2 + 1,
        match: 'x', contentHash: 'observed', editable: true }));
    matches.push({ targetId: 'typed', editable: false, reason: 'read_only_derived_field' });
    const original = JSON.stringify(matches);
    assert.deepEqual(search.preview(matches), { total: 206, replaceable: 205, readOnly: 1,
        reasons: { read_only_derived_field: 1 }, groups: 3 });
    const groups = search.groups(matches);
    assert.deepEqual(groups.map(group => group.length), [100, 100, 5]);
    assert.deepEqual(groups.flat().map(m => m.start), Array.from({ length: 205 }, (_, i) => (204 - i) * 2));
    assert.deepEqual(search.operation(groups[0][0], 'pin'), { operation: 'replace_range', targetId: 'one',
        expectedContentHash: 'observed', start: 408, end: 409, expectedText: 'x', text: 'pin' });
    assert.equal(JSON.stringify(matches), original);
});

test('multiple targets keep target order and descending offsets within each', () => {
    const matches = [ ['b', 1], ['a', 5], ['b', 3], ['a', 0] ].map(([targetId, start]) => ({ targetId, start, editable: true }));
    assert.deepEqual(search.groups(matches).flat().map(m => [m.targetId, m.start]), [['b', 3], ['b', 1], ['a', 5], ['a', 0]]);
});

test('symbol groups mirror the Python code-point allowlist exactly', () => {
    const source = fs.readFileSync(path.join(__dirname, '../ai_inspector/documentation/symbols.py'), 'utf8');
    const groups = [...source.matchAll(/\("([^"]+)", "([0-9A-F ]+)"\)/g)]
        .map(match => ({ group: match[1], text: match[2].split(' ').map(code => String.fromCodePoint(parseInt(code, 16))) }));
    assert.equal(groups.length, 3);
    assert.deepEqual(symbols.map(g => ({ group: g.group, text: g.symbols.map(s => s.text) })), groups);
    const all = symbols.flatMap(g => g.symbols);
    assert.equal(all.length, 69);
    assert.equal(new Set(all.map(s => s.text)).size, 68);
    assert.ok(all.every(s => s.name && search.points(s.text).length === 1));
    assert.equal(all.filter(s => s.text === 'Ω').length, 2);
});

test('read-only reasons read as text and the result list is bounded', () => {
    assert.equal(search.reason('read_only_derived_field'), 'typed, locked or derived value');
    assert.equal(search.reason('manual_edit_conflict'), 'open conflict');
    assert.equal(search.reason(undefined), 'typed, locked or derived value');
    assert.equal(search.reason('another_code'), 'another_code');
    assert.equal(search.SHOWN, 1000);
});
