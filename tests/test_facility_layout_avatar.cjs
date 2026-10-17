'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { createAvatar, createStandingAvatar } = require('../static/facility_layout_avatar.js');

async function main() {
    const THREE = await import(pathToFileURL(path.resolve(__dirname,
        '../static/vendor/three/0.184.0/build/three.module.min.js')).href);
    const standing = createStandingAvatar(THREE);
    const standingBounds = new THREE.Box3().setFromObject(standing, true);
    assert(Math.abs(standingBounds.min.y) < 1e-6);
    assert(Math.abs(standingBounds.max.y - 1.876) < 1e-6);
    standing.traverse(item => {
        if (!item.isMesh) return;
        assert(!item.isSkinnedMesh && !item.skeleton, 'Standing instances must have baked skinning');
        assert(!item.geometry.attributes.skinWeight);
        assert(Array.from(item.geometry.attributes.position.array).every(Number.isFinite));
    });
    const sampled = createAvatar(THREE), peer = createAvatar(THREE);
    const sample = distance => ({ position: { x: 0, y: 0, z: 0 }, heading: 0,
        snap: true, gaitDistanceMeters: distance, walking: true });
    sampled.update(sample(.3));
    const pose = sampled.snapshot();
    sampled.update(sample(50)); sampled.update(sample(.3));
    assert.deepEqual(sampled.snapshot(), pose, 'Seek is independent of playback history');
    assert.equal(peer.snapshot().phase, 0, 'Actors own independent skeletons and gait');
    sampled.update({ ...sample(.3), walking: false });
    assert.equal(sampled.snapshot().blend, 0);
    assert.equal(sampled.snapshot().animation, 'idle');
    sampled.dispose(); peer.dispose();
    const bakedMaterials = new Set();
    standing.traverse(item => { if (item.isMesh) { item.geometry.dispose(); bakedMaterials.add(item.material); } });
    bakedMaterials.forEach(item => item.dispose());
    const avatar = createAvatar(THREE);
    const scene = new THREE.Scene(); scene.add(avatar.root);
    const position = { x: 10, y: 2, z: 15 };
    avatar.update({ position, heading: 0, snap: true });
    const bounds = new THREE.Box3().setFromObject(avatar.root, true);
    assert(Math.abs(bounds.min.y - 2) < 1e-6);
    assert(Math.abs(bounds.max.y - bounds.min.y - avatar.snapshot().heightMeters) < 1e-6);
    assert(bounds.max.x - bounds.min.x < 0.61);
    const geos = new Set(), materials = new Set(); let count = 0;
    avatar.root.traverse(item => { if (item.isMesh) { count++; geos.add(item.geometry); materials.add(item.material); } });
    assert.equal(count, avatar.snapshot().meshCount);
    assert.equal(geos.size, 12);
    assert.equal(materials.size, 6);
    let triangles = 0;
    avatar.root.traverse(item => {
        if (!item.isMesh) return;
        assert.notEqual(item.geometry.type, 'BoxGeometry', 'No blocky body parts');
        assert.equal(item.material.flatShading, false);
        triangles += item.geometry.index.count / 3;
        for (const attribute of ['position', 'normal']) {
            assert(Array.from(item.geometry.attributes[attribute].array).every(Number.isFinite));
        }
    });
    assert(triangles < 45000, 'Single worker has a bounded geometry budget');
    const skins = [];
    avatar.root.traverse(item => { if (item.isSkinnedMesh) skins.push(item); });
    assert.equal(skins.length, 4);
    assert.equal(avatar.snapshot().skeletonCount, 4);
    let disposedSkeletons = 0;
    for (const item of skins) {
        assert.equal(item.skeleton.bones.length, 2);
        const weights = item.geometry.attributes.skinWeight;
        for (let i = 0; i < weights.count; i++) {
            assert(Math.abs(weights.getX(i) + weights.getY(i) - 1) < 1e-6);
            assert(weights.getX(i) >= 0 && weights.getY(i) >= 0);
        }
        const dispose = item.skeleton.dispose.bind(item.skeleton);
        item.skeleton.dispose = () => { disposedSkeletons++; dispose(); };
    }
    let disposed = 0;
    [...geos, ...materials].forEach(item => item.addEventListener('dispose', () => disposed++));
    let minFoot = Infinity;
    for (let i = 0; i < 100; i++) {
        avatar.update({ position, heading: 0.4, distance: 0.03, deltaSeconds: 0.02 });
        minFoot = Math.min(minFoot, new THREE.Box3().setFromObject(avatar.root, true).min.y);
    }
    assert(minFoot > position.y - 0.04, 'No appreciable floor penetration in gait');
    assert.equal(avatar.snapshot().animation, 'walk');
    assert(Math.abs(avatar.snapshot().distanceMeters - 3) < 1e-8);
    assert.notEqual(avatar.snapshot().leftHip, 0);
    for (let i = 0; i < 100; i++) avatar.update({ position, heading: 0.4, distance: 0, deltaSeconds: 0.02 });
    assert.equal(avatar.snapshot().animation, 'idle');
    assert.equal(Math.abs(avatar.snapshot().leftHip), 0);
    assert.equal(Math.abs(avatar.snapshot().rightHip), 0);
    avatar.update({ position, heading: 0, distance: 0.03, deltaSeconds: 0.02 });
    assert.equal(avatar.snapshot().animation, 'walk');
    avatar.update({ position, heading: 0, distance: 0, deltaSeconds: 0.5 });
    assert.equal(avatar.snapshot().animation, 'idle', 'Slow frames do not stretch idle settling');
    avatar.dispose(); avatar.dispose();
    assert.equal(disposed, geos.size + materials.size);
    assert.equal(disposedSkeletons, 4);
    assert.equal(scene.children.length, 0);
    assert.equal(avatar.update({ position }), false);
    console.log('Avatar real-Three geometry, gait, scale, idle and resource disposal passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
