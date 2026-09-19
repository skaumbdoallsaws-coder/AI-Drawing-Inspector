'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
    path.resolve(__dirname, '..', 'static', 'index.html'),
    'utf8'
);

let passed = 0;

function test(name, fn) {
    fn();
    passed += 1;
    process.stdout.write('PASS ' + name + '\n');
}

test('dark viewport scenes use the shared studio gradient', function () {
    assert(source.includes('--viewport-bg-gradient: linear-gradient('));
    assert(source.includes('_applyCadViewportBackground(scene);'));
    assert(source.includes(
        'var(--viewport-bg-gradient, var(--viewport-bg, var(--bg-main)))'
    ));
});

test('themed renderers output sRGB on old and new Three runtimes', function () {
    assert(source.includes('function _configureThemedRendererColorSpace('));
    assert(source.includes('renderer.outputColorSpace = threeRuntime.SRGBColorSpace;'));
    assert(source.includes('renderer.outputEncoding = threeRuntime.sRGBEncoding;'));
    assert(source.includes('_configureThemedRendererColorSpace(renderer);'));
});

test('temporary preview scenes participate in theme changes without leaking', function () {
    assert(source.includes('_registerThemedScene(scene);'));
    assert(source.includes('_registerThemedRenderer(renderer);'));
    assert(source.includes('window.__themedScenes.delete(viewer.scene);'));
    assert(source.includes('window.__themedRenderers.delete(viewer.renderer);'));
});

process.stdout.write(passed + '/3 passed\n');
