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
        "role: 'dialog'",
        "role: 'list'",
        "role: 'listitem'",
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

check('V2 authoring does not depend on the legacy semantic fixture', () => {
    const index = source('static/index.html');
    assert.ok(index.includes(
        'if (trainingState.facilityLayoutError) return Promise.resolve(null);'
    ));
    assert.ok(index.includes(
        'const runtimesReady = _trainFacilityAuthoringRuntimesReady();'
    ));

    const renderStart = index.indexOf(
        'function _trainRenderFacilityLayoutViewer()'
    );
    const renderEnd = index.indexOf(
        'let _trainFacilityLayoutAuthoringApp',
        renderStart
    );
    assert.ok(renderStart >= 0 && renderEnd > renderStart);
    assert.ok(!index.slice(renderStart, renderEnd).includes(
        '_trainEnsureFacilityLayoutLoaded()'
    ));

    const trainingStart = index.indexOf('function _renderTrainingTab()');
    const trainingEnd = index.indexOf(
        'function _trainBuildLeftRail()',
        trainingStart
    );
    assert.ok(trainingStart >= 0 && trainingEnd > trainingStart);
    assert.ok(index.slice(trainingStart, trainingEnd).includes(
        'if (!_trainFacilityAuthoringRuntimesReady())'
    ));

    const panelStart = index.indexOf(
        'function _trainAppendFacilityLayoutPanel(body)'
    );
    const panelEnd = index.indexOf(
        'function _trainAppendFacilityLayoutPanelRefresh()',
        panelStart
    );
    assert.ok(panelStart >= 0 && panelEnd > panelStart);
    assert.ok(index.slice(panelStart, panelEnd).includes(
        '&& !_trainFacilityAuthoringRuntimesReady()'
    ));

    const legacyStart = index.indexOf(
        'function _trainMountLegacyFacilityLayoutViewer()'
    );
    assert.ok(legacyStart >= 0);
    assert.ok(index.slice(legacyStart, legacyStart + 600).includes(
        '_trainEnsureFacilityLayoutLoaded()'
    ));
});

check('integrated Facility Layout editing commands live in the main ribbon', () => {
    const index = source('static/index.html');
    assert.ok(index.includes('FACILITY_LAYOUT_RIBBON_CONFIG'));
    assert.ok(index.includes('function _trainRenderFacilityLayoutRibbon'));
    assert.ok(index.includes('externalCommandSurface: true'));
    assert.ok(index.includes('20260807-viewport-recording'));
    [
        'Selection',
        'Create',
        'Arrange',
        'History',
        'Layout',
        'Document',
        'rectangle-zone',
        'polygon-zone',
        'auto-arrange',
        'data-facility-ribbon-command',
        'onCommandStateChange',
    ].forEach(token => assert.ok(index.includes(token), token));

    const css = source('static/facility_layout_workspace.css');
    assert.ok(css.includes('#trainFacilityLayoutAuthoring > .ip-flw-toolbar'));
    assert.ok(css.includes('--ip-flw-toolbar-height: 0px'));
    assert.ok(css.includes(
        'grid-template-rows: minmax(0, 1fr) var(--ip-flw-status-height)'
    ));

    const iconRoot = path.join(
        ROOT,
        'static',
        'assets',
        'facility-layout-ribbon-icons'
    );
    assert.ok(fs.existsSync(path.join(iconRoot, 'LICENSE.txt')));
    [
        'cursor-click', 'hand', 'rectangle', 'polygon', 'arrow-clockwise',
        'copy', 'trash', 'lock-simple', 'arrow-u-up-left',
        'arrow-u-up-right', 'corners-out', 'magic-wand', 'floppy-disk',
    ].forEach(name => assert.ok(
        fs.existsSync(path.join(iconRoot, 'svg', name + '.svg')),
        name
    ));
    [
        'sphere', 'magnifying-glass-minus', 'magnifying-glass-plus',
        'bounding-box', 'cube-focus', 'cube', 'grid-four',
    ].forEach(name => assert.ok(
        fs.existsSync(path.join(iconRoot, 'svg', name + '.svg')),
        name
    ));
    assert.ok(css.includes('.ip-flw-three-navigation'));
    assert.ok(css.includes('.ip-flw-three-nav-button'));
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

console.log(`${passed}/6 facility layout P11 contract checks passed`);
