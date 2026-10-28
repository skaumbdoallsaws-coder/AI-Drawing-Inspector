'use strict';

// Parts manual balloons: a candidate layout that fails on a balloon may borrow that balloon's clear placement from
// another candidate (the MMLE-50D overview figure stopped the build on balloon 10, which three other candidates had
// routed clear). Runs _partsManualBorrowClearCallouts and its real geometry helpers from index.html; the layout
// score is stubbed to "no hard failures" so only the borrowing is tested.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

function functionSource(html, name) {
    // One top-level function of index.html, found by its declaration and closed by matching braces.
    const start = html.indexOf(`        function ${name}(`);
    assert(start > 0, `${name} is in index.html`);
    const open = html.indexOf('{', html.indexOf(')', start));
    let depth = 0;
    for (let index = open; index < html.length; index += 1) {
        if (html[index] === '{') depth += 1;
        else if (html[index] === '}') {
            depth -= 1;
            if (depth === 0) return html.slice(start, index + 1);
        }
    }
    throw new Error(`${name} is not closed`);
}

function loadFunctions() {
    const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
    const names = [
        '_partsManualSegmentIntersectsBounds', '_partsManualSegmentsCross', '_partsManualBalloonAttachment',
        '_partsManualCalloutSegments', '_partsManualAllCalloutSegments', '_partsManualCalloutLeaderLength',
        '_partsManualBalloonBounds', '_partsManualLeaderHitsBalloon', '_partsManualBranchSegments',
        '_partsManualBorrowClearCallouts',
    ];
    const source = names.map(name => functionSource(html, name)).join('\n')
        + '\nfunction _partsManualCalloutLayoutScore() { return { metrics: { hardFailureCount: 0 }, score: 0 }; }'
        + '\nreturn { _partsManualBorrowClearCallouts };';
    return new Function(source)();
}

const { _partsManualBorrowClearCallouts } = loadFunctions();

function row(itemNumber, target, balloon, options = {}) {
    return {
        itemNumber,
        target: { x: target[0], y: target[1] },
        balloon: { x: balloon[0], y: balloon[1] },
        leaderPath: [],
        calloutType: 'representative_with_count',
        manualOverrideApplied: false,
        geometryIntersectionCount: 0,
        routingValidated: true,
        repeatedStrategyValidated: true,
        ...options,
    };
}

const blocked = { geometryIntersectionCount: 1, routingValidated: false };
const tests = [];
const test = (name, body) => tests.push([name, body]);

test('a balloon blocked in the best layout takes its clear placement from another layout', () => {
    const base = { strategy: 'straight-first', routed: [
        row(1, [0.3, 0.5], [0.1, 0.5]),
        row(2, [0.6, 0.5], [0.9, 0.5], blocked),
    ] };
    const lender = { strategy: 'local-compact', routed: [
        row(1, [0.3, 0.5], [0.3, 0.9], blocked),
        row(2, [0.6, 0.3], [0.6, 0.1]),
    ] };
    // the lender fails on item 1 too, so it borrows the other way as well
    const borrowed = _partsManualBorrowClearCallouts([base, lender]);
    assert.deepStrictEqual(borrowed.map(r => r.strategy), ['straight-first+borrowed', 'local-compact+borrowed']);
    const [layout] = borrowed;
    assert.deepStrictEqual(layout.routed.find(r => r.itemNumber === 2).balloon, { x: 0.6, y: 0.1 });
    assert.deepStrictEqual(layout.routed.find(r => r.itemNumber === 1).balloon, { x: 0.1, y: 0.5 });
    assert(layout.routed.every(r => r.routingValidated));
    assert.strictEqual(layout.qaDiagnostics.find(r => r.itemNumber === 2).borrowedFrom, 'local-compact');
    // the candidates themselves are left as they were
    assert.strictEqual(base.routed[1].routingValidated, false);
});

test('a borrowed leader that would cross another leader is refused', () => {
    const base = { strategy: 'straight-first', routed: [
        row(1, [0.3, 0.5], [0.1, 0.5]),
        row(2, [0.6, 0.5], [0.9, 0.5], blocked),
    ] };
    // clear in its own layout, but it runs down across item 1's leader at x = 0.2
    const lender = { strategy: 'gutter', routed: [row(2, [0.2, 0.6], [0.2, 0.3])] };
    assert.strictEqual(_partsManualBorrowClearCallouts([base, lender]).length, 0);
});

test('a borrowed balloon that sits on another leader is refused', () => {
    const base = { strategy: 'straight-first', routed: [
        row(1, [0.5, 0.5], [0.1, 0.5]),
        row(2, [0.8, 0.8], [0.9, 0.9], blocked),
    ] };
    const lender = { strategy: 'lane-vertical', routed: [row(2, [0.3, 0.7], [0.3, 0.5])] };
    assert.strictEqual(_partsManualBorrowClearCallouts([base, lender]).length, 0);
});

test('a balloon the user placed is never replaced', () => {
    const base = { strategy: 'straight-first', routed: [
        row(1, [0.3, 0.5], [0.1, 0.5]),
        row(2, [0.6, 0.5], [0.9, 0.5], { ...blocked, manualOverrideApplied: true }),
    ] };
    const lender = { strategy: 'local-compact', routed: [row(2, [0.6, 0.3], [0.6, 0.1])] };
    assert.strictEqual(_partsManualBorrowClearCallouts([base, lender]).length, 0);
});

test('only a clear placement is lent, and a layout with nothing failing borrows nothing', () => {
    const base = { strategy: 'straight-first', routed: [
        row(1, [0.3, 0.5], [0.1, 0.5]),
        row(2, [0.6, 0.5], [0.9, 0.5], blocked),
    ] };
    const alsoBlocked = { strategy: 'local-compact', routed: [row(2, [0.6, 0.3], [0.6, 0.1], blocked)] };
    assert.strictEqual(_partsManualBorrowClearCallouts([base, alsoBlocked]).length, 0);
    const clean = { strategy: 'local-balanced', routed: [row(1, [0.3, 0.5], [0.1, 0.5])] };
    assert.strictEqual(_partsManualBorrowClearCallouts([clean]).length, 0);
});

let passed = 0;
for (const [name, body] of tests) {
    try {
        body();
        passed += 1;
        console.log(`ok - ${name}`);
    } catch (error) {
        console.log(`not ok - ${name}\n${error.stack}`);
    }
}
console.log(`${passed}/${tests.length} passed`);
if (passed !== tests.length) process.exit(1);
