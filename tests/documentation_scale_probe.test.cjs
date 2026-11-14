const test = require('node:test');
const assert = require('node:assert/strict');
const {summary, contrast} = require('./documentation_editor_scale_probe.js');

test('P5a uses an unscaled median and nearest-rank p95, retaining the raw samples', () => {
    const samples = [100, 1, 4, 3, 2];
    assert.deepEqual(summary(samples), {samples, median: 3, p95: 100});
    assert.deepEqual(samples, [100, 1, 4, 3, 2]);
    assert.equal(summary([1, 2, 3, 4]).median, 2.5);
    assert.equal(summary(Array.from({length: 50}, (_, i) => i + 1)).p95, 48);
    assert.throws(() => summary([]));
    assert.throws(() => summary([NaN]));
    assert.throws(() => summary([-1]));
});

test('P5a contrast uses sRGB linearisation and composites translucent text', () => {
    assert.equal(contrast([0, 0, 0, 1], [255, 255, 255, 1]), 21);
    assert.equal(contrast([255, 255, 255], [255, 255, 255]), 1);
    assert.ok(Math.abs(contrast([0, 0, 0, .5], [255, 255, 255]) - 3.976653024912438) < 1e-12);
    assert.ok(contrast([119, 119, 119], [255, 255, 255]) < 4.5);
});
