'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let passed = 0;

function source(relative) {
    return fs.readFileSync(path.join(ROOT, relative), 'utf8');
}

function check(name, callback) {
    try {
        callback();
        passed += 1;
        console.log('PASS ' + name);
    } catch (error) {
        console.error('FAIL ' + name);
        throw error;
    }
}

check('facility workspace exposes the static ARIA contract', () => {
    const workspace = source('static/facility_layout_workspace.js');
    [
        "Facility layout workspace",
        "role: 'toolbar'",
        "role: 'tree'",
        "role: 'treeitem'",
        "role: 'tablist'",
        "role: 'tabpanel'",
        "'aria-live': 'polite'",
        "'aria-selected'",
        "'aria-pressed'",
        "'aria-busy'",
    ].forEach(token => assert.ok(workspace.includes(token), token));

    const css = source('static/facility_layout_workspace.css');
    assert.ok(css.includes(':focus-visible'));
    assert.ok(css.includes('prefers-reduced-motion: reduce'));
});

check('WebGL loss and restoration are symmetric and demand driven', () => {
    const adapter = source('static/facility_layout_three_adapter.js');
    assert.ok(adapter.includes("'webglcontextlost'"));
    assert.ok(adapter.includes("'webglcontextrestored'"));
    assert.ok(adapter.includes('event.preventDefault()'));
    assert.ok(adapter.includes("enterDegraded('webgl_context_lost'"));
    assert.ok(adapter.includes("notifyStatus('ready', null)"));
    assert.ok(adapter.includes('removeListener('));
});

check('behavioral recovery and corrupt-asset tests remain present', () => {
    const tests = source('tests/test_facility_layout_three_adapter.js');
    assert.ok(tests.includes(
        'context loss degrades 3D without throwing'
    ));
    assert.ok(tests.includes(
        'context restoration replays edits made while 3D was degraded'
    ));
    assert.ok(tests.includes(
        'WebGL-unavailable mode retains scene identity'
    ));
    assert.ok(tests.includes(
        'keeps failed assets as deterministic footprint boxes'
    ));
});

check('pilot runbook carries the mandatory safety disclaimer', () => {
    const runbook = source('docs/facility-layout-p11-pilot-runbook.md');
    const disclaimer = [
        'InspectorPro assists industrial layout planning and validation.',
        'It does not replace required facility, safety, regulatory, or',
        'professional engineering approval.',
    ].join(' ');
    assert.ok(runbook.replace(/\r?\n/g, ' ').includes(disclaimer));
});

console.log(`${passed}/4 facility layout P11 contract checks passed`);
