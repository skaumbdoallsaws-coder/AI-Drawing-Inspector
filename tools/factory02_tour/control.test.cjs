'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {TourControl, verifyArrival, withTimeout} = require('./control.cjs');

test('recording waits for an explicit cue', () => {
    const c = new TourControl();
    assert.equal(c.paused, true);
    assert.equal(c.started, false);
    c.toggle();
    assert.equal(c.paused, false);
    assert.equal(c.started, true);
    assert.equal(c.epoch, 1);
});
test('pause and resume invalidate a pending route', () => {
    const c = new TourControl(false);
    const epoch = c.epoch;
    c.toggle(); c.toggle();
    assert.equal(c.paused, false);
    assert.equal(c.started, true);
    assert.notEqual(c.epoch, epoch);
});
test('stop is terminal, including while paused', () => {
    const c = new TourControl(true);
    c.stop();
    assert.equal(c.toggle(), false);
    assert.throws(() => c.check(), /tour_stopped/);
});
test('camera time includes slow frames but excludes all paused time', () => {
    let time = 1000;
    const c = new TourControl(false, () => time);
    time += 270;
    assert.equal(c.now(), 270);
    c.toggle(); time += 30000;
    assert.equal(c.now(), 270);
    c.toggle(); time += 410;
    assert.equal(c.now(), 680);
});
test('waiting for the recording cue does not advance camera time', () => {
    let time = 0;
    const c = new TourControl(true, () => time);
    time = 45000;
    assert.equal(c.now(), 0);
    c.toggle(); time += 1000;
    assert.equal(c.now(), 1000);
});
test('waiting for the first cue does not consume the mid-tour pause limit', () => {
    let time = 0;
    const c = new TourControl(true, () => time);
    time = 600000;
    assert.equal(c.pauseTimedOut(), false);
    c.toggle();
    assert.equal(c.pauseTimedOut(), false);
    c.toggle();
    time += 300001;
    assert.equal(c.pauseTimedOut(), true);
    c.toggle();
    assert.equal(c.pauseTimedOut(), false);
});
test('arrival requires active grounded walker and exact destination', () => {
    const state = {active: true, route: {active: false, reason: 'arrived'}, position: {x: 3, z: 4}};
    assert.equal(verifyArrival(state, {x: 3, z: 4}), 0);
    assert.throws(() => verifyArrival(state, {x: 5, z: 4}), /short/);
    assert.throws(() => verifyArrival({...state, active: false}, {x: 3, z: 4}), /did not arrive/);
    assert.throws(() => verifyArrival({...state, route: {active: false, reason: 'route_blocked'}}, {x: 3, z: 4}), /did not arrive/);
});
test('renderer command timeout reports a stalled promise', async () => {
    await assert.rejects(withTimeout(new Promise(() => {}), 'Renderer command', 10), /Renderer command timed out/);
});
test('bounded command preserves values and errors', async () => {
    assert.equal(await withTimeout(Promise.resolve(42), 'Command', 1000), 42);
    await assert.rejects(withTimeout(Promise.reject(new Error('original failure')), 'Command', 1000), /original failure/);
});
