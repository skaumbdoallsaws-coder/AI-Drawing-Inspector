(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityAvatar = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function createAvatar(THREE) {
        const root = new THREE.Group();
        root.name = 'facility-walkthrough-avatar';
        root.userData.navigationOnly = true;
        const body = new THREE.Group(); root.add(body);
        const upperPivot = new THREE.Group(); upperPivot.position.y = .91; body.add(upperPivot);
        const upper = new THREE.Group(); upper.position.y = -.91; upperPivot.add(upper);
        const geometries = new Set(), materials = new Set();
        let meshCount = 0;
        const own = geometry => { geometries.add(geometry); return geometry; };
        const sphere = own(new THREE.SphereGeometry(1, 24, 16));
        const material = (color, roughness = 0.78, metalness = 0) => {
            const value = new THREE.MeshStandardMaterial({ color, roughness, metalness });
            materials.add(value); return value;
        };
        const blue = material(0x35667c), vest = material(0xcbd936), skin = material(0xd4a680);
        const dark = material(0x29343c), silver = material(0xe5e9e9, 0.48, 0.12);
        const hat = material(0xf4bc32, 0.38);
        // The process viewer still uses r128, which requires an explicit skinning material.
        const cloth = 'skinning' in blue ? blue.clone() : blue;
        if (cloth !== blue) { cloth.skinning = true; materials.add(cloth); }
        function mesh(parent, geometry, surface, x, y, z, sx, sy, sz) {
            const value = new THREE.Mesh(geometry, surface);
            meshCount += 1;
            value.position.set(x, y, z); value.scale.set(sx, sy, sz);
            value.castShadow = false; value.receiveShadow = false;
            parent.add(value); return value;
        }
        function joint(parent, x, y, z) {
            const value = new THREE.Group(); value.position.set(x, y, z); parent.add(value); return value;
        }
        function profile(points, samples = 32) {
            return new THREE.SplineCurve(points.map(([r, y]) => new THREE.Vector2(r, y)))
                .getPoints(samples).map(p => new THREE.Vector2(Math.max(0, p.x), p.y));
        }
        function lathe(points, segments = 32, start = 0, length = Math.PI * 2) {
            return own(new THREE.LatheGeometry(points, segments, start, length));
        }
        // Curved clothing and trim share the same profile, avoiding floating flat strips.
        const torsoProfile = profile([[0, 1.025], [.105, 1.025], [.15, 1.05], [.162, 1.12],
            [.18, 1.27], [.207, 1.38], [.213, 1.43], [.18, 1.48], [.07, 1.51], [0, 1.51]], 48);
        mesh(upper, lathe(torsoProfile), vest, 0, 0, 0, 1, 1, .66);
        const trimProfile = torsoProfile.filter(p => p.y >= 1.10 && p.y <= 1.465)
            .map(p => new THREE.Vector2(p.x + .002, p.y));
        for (const angle of [-.54, .54, Math.PI - .54, Math.PI + .54]) {
            mesh(upper, lathe(trimProfile, 4, angle - .065, .13), silver, 0, 0, 0, 1, 1, .66);
        }
        const beltProfile = torsoProfile.filter(p => p.y >= 1.13 && p.y <= 1.18)
            .map(p => new THREE.Vector2(p.x + .003, p.y));
        mesh(upper, lathe(beltProfile), silver, 0, 0, 0, 1, 1, .66);
        mesh(upper, lathe(trimProfile, 2, Math.PI - .014, .028), dark, 0, 0, 0, 1, 1, .67);
        const pelvis = lathe(profile([[0, .855], [.11, .87], [.157, .92], [.164, 1.005],
            [.147, 1.06], [0, 1.065]], 24));
        mesh(upper, pelvis, blue, 0, 0, 0, 1, 1, .77);
        mesh(upper, sphere, blue, 0, 1.507, 0, .064, .04, .059);
        mesh(upper, sphere, skin, 0, 1.546, 0, .047, .061, .048);
        mesh(upper, sphere, skin, 0, 1.668, -.008, .099, .132, .10);
        mesh(upper, sphere, skin, 0, 1.615, -.012, .072, .064, .073);
        for (const side of [-1, 1]) {
            mesh(upper, sphere, skin, side * .096, 1.662, 0, .013, .027, .019);
            mesh(upper, sphere, dark, side * .042, 1.687, -.101, .039, .017, .013);
        }
        mesh(upper, sphere, dark, 0, 1.687, -.113, .026, .008, .007);
        mesh(upper, sphere, skin, 0, 1.655, -.108, .017, .025, .025);
        mesh(upper, sphere, hat, 0, 1.782, -.009, .139, .014, .153);
        const dome = own(new THREE.SphereGeometry(1, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2));
        mesh(upper, dome, hat, 0, 1.776, 0, .12, .100, .124);
        // Two-bone skinning bends a continuous sleeve/trouser surface, without ball-joint seams.
        const legSurface = lathe(profile([[0, -.82], [.049, -.79], [.056, -.70], [.068, -.53],
            [.066, -.37], [.081, -.23], [.094, -.10], [.083, .015], [0, .065]], 48), 24);
        const armSurface = lathe(profile([[0, -.49], [.035, -.47], [.044, -.39], [.052, -.26],
            [.062, -.16], [.073, -.045], [.071, .02], [.046, .065], [0, .08]], 40), 24);
        function skinGeometry(geometry, bendY, blendWidth) {
            const indices = [], weights = [], positions = geometry.attributes.position;
            for (let i = 0; i < positions.count; i++) {
                const t = Math.max(0, Math.min(1, (bendY + blendWidth / 2 - positions.getY(i)) / blendWidth));
                const weight = t * t * (3 - 2 * t);
                indices.push(0, 1, 0, 0); weights.push(1 - weight, weight, 0, 0);
            }
            geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(indices, 4));
            geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights, 4));
        }
        skinGeometry(legSurface, -.37, .16);
        skinGeometry(armSurface, -.26, .13);
        const skeletons = [];
        function limbRig(geometry, x, y, bendY, parent = body) {
            const surface = new THREE.SkinnedMesh(geometry, cloth);
            surface.position.set(x, y, 0); parent.add(surface); meshCount += 1;
            const upper = new THREE.Bone(), lower = new THREE.Bone();
            lower.position.y = bendY; upper.add(lower); surface.add(upper);
            root.updateMatrixWorld(true);
            const skeleton = new THREE.Skeleton([upper, lower]);
            skeletons.push(skeleton); surface.bind(skeleton);
            // A single navigation actor: avoid an outdated bind-pose culling sphere during gait.
            surface.frustumCulled = false;
            return { upper, lower };
        }
        const legs = [], arms = [];
        for (const side of [-1, 1]) {
            const leg = limbRig(legSurface, side * .094, .91, -.37);
            const foot = joint(leg.lower, 0, -.40, 0);
            mesh(foot, sphere, dark, 0, -.055, -.052, .076, .075, .143);
            mesh(foot, sphere, dark, 0, -.11, -.052, .078, .03, .145);
            mesh(foot, sphere, dark, 0, -.013, .011, .061, .088, .068);
            legs.push({ hip: leg.upper, knee: leg.lower, foot });
            const arm = limbRig(armSurface, side * .224, 1.421, -.26, upper);
            mesh(arm.lower, sphere, dark, 0, -.255, -.005, .039, .064, .028);
            mesh(arm.lower, sphere, dark, -side * .027, -.241, -.014, .018, .033, .022);
            arms.push({ shoulder: arm.upper, elbow: arm.lower });
        }
        let phase = 0, blend = 0, yaw = 0, distance = 0, disposed = false;
        let walking = false;
        const poseWeights = { standing: 1, crouching: 0, kneeling: 0, crawling: 0 };
        let posture = 'standing';
        function solveLimb(y, z, a, b) {
            const d = Math.max(.001, Math.min(a + b - .00001, Math.hypot(y, z)));
            const clamp = n => Math.max(-1, Math.min(1, n));
            return { upper: Math.atan2(-z, -y) + Math.acos(clamp((a*a + d*d - b*b)/(2*a*d))),
                lower: Math.acos(clamp((a*a + b*b - d*d)/(2*a*b))) - Math.PI };
        }
        function applyPosture(value, dt) {
            posture = Object.hasOwn(poseWeights, value.posture) ? value.posture : 'standing';
            for (const key of Object.keys(poseWeights)) {
                const target = key === posture ? 1 : 0;
                poseWeights[key] += (target - poseWeights[key]) * (value.snapPose ? 1 : 1 - Math.exp(-12 * dt));
                if (Math.abs(target - poseWeights[key]) < .0001) poseWeights[key] = target;
            }
            const w = poseWeights, low = 1 - w.standing;
            if (!low && !value.grounding) return;
            let hipY = .91 * w.standing + .35 * w.crouching + .447 * w.kneeling + .43 * w.crawling;
            const lean = -.7 * w.crouching - Math.PI / 2 * w.crawling;
            upperPivot.rotation.x = lean;
            const targets = legs.map((leg, i) => {
                const cycle = Math.sin(phase + i * Math.PI);
                const swing = Math.max(0, -cycle) * blend;
                const z = -cycle * .22 * blend * w.standing - .10 * w.crouching
                    + (i ? .38 : -.27) * w.kneeling + (.5 - cycle * .07 * blend) * w.crawling;
                const support = value.supportHeight ? Number(value.supportHeight(i ? .094 : -.094, z)) || 0 : 0;
                return { z, y: .14 + support * w.standing + swing * .13 * w.standing };
            });
            if (w.standing > .99) hipY -= Math.max(0, .14 - Math.min(...targets.map(t => t.y))) + .025;
            body.position.y = hipY - .91;
            legs.forEach((leg, i) => {
                const t = targets[i], angles = solveLimb(t.y - hipY, t.z, .37, .40);
                leg.hip.rotation.x = angles.upper;
                leg.knee.rotation.x = angles.lower;
                leg.foot.rotation.x = -angles.upper - angles.lower;
                if (w.crawling > 0) {
                    const handY = .07 + Math.max(0, Math.sin(phase + i * Math.PI)) * .035 * blend;
                    const shoulderY = hipY + .511 * Math.cos(lean);
                    const hand = solveLimb(handY - shoulderY, -.04, .26, .255);
                    arms[i].shoulder.rotation.x = arms[i].shoulder.rotation.x * (1-w.crawling)
                        + (hand.upper - lean) * w.crawling;
                    arms[i].elbow.rotation.x = arms[i].elbow.rotation.x * (1-w.crawling) + hand.lower * w.crawling;
                }
            });
        }
        function update(value) {
            if (disposed) return false;
            const dt = Math.max(0, Math.min(0.25, value.deltaSeconds || 0));
            const travel = Math.max(0, value.distance || 0);
            // Playback samples absolute path distance so seeking never accumulates gait.
            const sampled = Number.isFinite(value.gaitDistanceMeters);
            distance = sampled ? Math.max(0, value.gaitDistanceMeters) : distance + travel;
            walking = sampled ? value.walking === true : travel > 1e-5;
            if (sampled) phase = distance * Math.PI * 2 / 1.35 % (Math.PI * 2);
            else if (walking) phase = (phase + travel * Math.PI * 2 / 1.35) % (Math.PI * 2);
            const target = walking ? Math.max(0, Math.min(1, value.gaitWeight ?? 1)) : 0;
            blend = sampled ? target : blend + (target - blend) * Math.min(1, dt * 14);
            if (Math.abs(target - blend) < 0.002) blend = target;
            if (Number.isFinite(value.heading)) {
                const difference = Math.atan2(Math.sin(value.heading - yaw), Math.cos(value.heading - yaw));
                yaw += difference * (value.snap ? 1 : Math.min(1, dt * 12));
            }
            root.position.set(value.position.x, value.position.y, value.position.z);
            root.rotation.y = yaw;
            body.position.y = Math.abs(Math.sin(phase * 2)) * 0.018 * blend;
            upperPivot.rotation.x = 0;
            legs.forEach((leg, index) => {
                const cycle = Math.sin(phase + index * Math.PI);
                leg.hip.rotation.x = cycle * 0.48 * blend;
                leg.knee.rotation.x = -Math.max(0, -cycle) * 0.72 * blend;
                leg.foot.rotation.x = -leg.hip.rotation.x * 0.3;
                arms[index].shoulder.rotation.x = -cycle * 0.34 * blend;
                arms[index].elbow.rotation.x = -0.12 - Math.max(0, cycle) * 0.2 * blend;
                arms[index].shoulder.rotation.z = 0;
            });
            applyPosture(value, dt);
            if (value.pointing && posture === 'standing') {
                arms[1].shoulder.rotation.x = 1.2;
                arms[1].shoulder.rotation.z = -.2;
                arms[1].elbow.rotation.x = -.2;
            }
            return blend > 0 || poseWeights[posture] < 1;
        }
        function snapshot() {
            return { visible: root.visible, disposed, heightMeters: 1.876, posture,
                postureBlend: poseWeights[posture],
                distanceMeters: distance, phase, blend, heading: yaw,
                animation: walking ? 'walk' : (blend > 0 ? 'settling' : 'idle'),
                leftHip: legs[0].hip.rotation.x, rightHip: legs[1].hip.rotation.x,
                meshCount, geometryCount: geometries.size, skeletonCount: skeletons.length };
        }
        return {
            root, update, snapshot,
            dispose() {
                if (disposed) return; disposed = true;
                if (root.parent) root.parent.remove(root);
                geometries.forEach(value => value.dispose());
                materials.forEach(value => value.dispose());
                skeletons.forEach(value => value.dispose());
            },
        };
    }
    // Standing placements remain instanced meshes, with no live skeleton per occurrence.
    function createStandingAvatar(THREE) {
        const avatar = createAvatar(THREE);
        const result = new THREE.Group();
        result.name = 'facility-standing-operator';
        const surfaces = new Map();
        try {
            avatar.update({ position: { x: 0, y: 0, z: 0 }, heading: 0, snap: true });
            avatar.root.updateMatrixWorld(true);
            avatar.root.traverse(source => {
                if (!source.isMesh) return;
                const geometry = source.geometry.clone();
                if (source.isSkinnedMesh) {
                    source.skeleton.update();
                    const position = geometry.attributes.position;
                    const point = new THREE.Vector3();
                    for (let i = 0; i < position.count; i++) {
                        point.fromBufferAttribute(position, i);
                        (source.applyBoneTransform || source.boneTransform).call(source, i, point);
                        position.setXYZ(i, point.x, point.y, point.z);
                    }
                    geometry.deleteAttribute('skinIndex');
                    geometry.deleteAttribute('skinWeight');
                    geometry.computeVertexNormals();
                }
                // Catalog operator faces +Z; the shared walking character faces -Z.
                geometry.applyMatrix4(source.matrixWorld).rotateY(Math.PI);
                if (!surfaces.has(source.material)) {
                    const surface = source.material.clone();
                    if ('skinning' in surface) surface.skinning = false;
                    surfaces.set(source.material, surface);
                }
                result.add(new THREE.Mesh(geometry, surfaces.get(source.material)));
            });
            return result;
        } finally {
            avatar.dispose();
        }
    }
    return Object.freeze({ createAvatar, createStandingAvatar });
}));
