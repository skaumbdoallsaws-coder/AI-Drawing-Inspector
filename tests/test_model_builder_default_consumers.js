'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const components = require('../static/facility_layout_component_materials.js');

function model() {
    function part(key, data) {
        return {isMesh: true, name: key, userData: {facilityPartKey: key},
            material: {name: 'surface', color: {set() {}}, userData: data}};
    }
    const lens = part('p:lamp/lens#0', {facilityDefaultFinish: 'light-stack-green',
        facilityDefaultFinishAdjustments: {color: '#123456', roughness: .25, metalness: .1},
        facilityFinishGroup: 'lamp'});
    const other = part('p:lamp/other#0', {facilityFinishGroup: 'lamp'});
    const print = part('p:lamp/print#0', {facilityArtwork: true, facilityDefaultFinish: 'light-stack-green'});
    const nodes = [lens, other, print];
    return {nodes, traverse(visitor) { nodes.forEach(visitor); }, userData: {}};
}

const finishes = {materialFor(value) { return {name: value.appearanceId, userData: {resolved: value}}; }};

test('default adjustments flatten, override wins, reset restores default', () => {
    const first = model();
    assert.deepEqual(components.recordDefaults(first), [{key: 'p:lamp/lens#0', appearanceId: 'light-stack-green',
        group: 'lamp', color: '#123456', roughness: .25, metalness: .1}]);
    assert.deepEqual(components.apply(first, null, 'artifact', finishes), ['p:lamp/lens#0']);
    assert.equal(first.nodes[0].material.userData.resolved.color, '#123456');
    assert.equal(first.nodes[2].material.userData.facilityArtwork, true);
    const overridden = model();
    components.recordDefaults(overridden);
    components.apply(overridden, {representation: 'artifact', overrides: [
        {key: 'p:lamp/lens#0', appearanceId: 'light-stack-amber'}]}, 'artifact', finishes);
    assert.equal(overridden.nodes[0].material.name, 'light-stack-amber');
    const reset = model();
    components.recordDefaults(reset);
    components.apply(reset, {representation: 'artifact', overrides: []}, 'artifact', finishes);
    assert.equal(reset.nodes[0].material.name, 'light-stack-green');
});

test('finish groups suppress defaults; artwork takes its own part finish but never a default', () => {
    const root = model();
    components.recordDefaults(root);
    assert.deepEqual(components.apply(root, {representation: 'artifact', overrides: [
        {key: 'p:lamp/other#0', appearanceId: 'light-stack-amber'},
        {key: 'p:lamp/print#0', appearanceId: 'light-stack-amber'}]}, 'artifact', finishes),
    ['p:lamp/other#0', 'p:lamp/print#0']);
    assert.equal(root.nodes[0].material.userData.facilityDefaultFinish, 'light-stack-green');
    assert.equal(root.nodes[2].material.name, 'light-stack-amber');
});

test('invalid adjustment values are discarded', () => {
    const root = model();
    root.nodes[0].material.userData.facilityDefaultFinishAdjustments =
        {color: 'red', roughness: NaN, metalness: true};
    assert.deepEqual(components.recordDefaults(root), [{key: 'p:lamp/lens#0',
        appearanceId: 'light-stack-green', group: 'lamp'}]);
});
