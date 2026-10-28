(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityEquipmentDecals = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    // Decals projected onto equipment. A saved decal stores its anchor in the
    // placement's own coordinates; these helpers turn that into a projector in
    // world space and clip the image onto whatever geometry lies under it.

    const DECAL_FLAG = 'facilityEquipmentDecal';

    function projector(THREE, objectMatrixWorld, anchor) {
        const position = new THREE.Vector3(anchor.position.x, anchor.position.y, anchor.position.z)
            .applyMatrix4(objectMatrixWorld);
        const normal = new THREE.Vector3(anchor.normal.x, anchor.normal.y, anchor.normal.z)
            .transformDirection(objectMatrixWorld);
        const helper = new THREE.Object3D();
        helper.position.copy(position);
        // Upright by default: keep the sign's top toward +Y unless the surface
        // faces straight up or down, where north (+Z) becomes the top.
        helper.up.set(0, Math.abs(normal.y) > 0.98 ? 0 : 1, Math.abs(normal.y) > 0.98 ? 1 : 0);
        helper.lookAt(position.clone().add(normal));
        helper.rotateZ((Number(anchor.rotationDegrees) || 0) * Math.PI / 180);
        return { position: position, normal: normal, orientation: helper.rotation.clone() };
    }

    // Keep only triangles that face the projector, so a sign never bleeds onto
    // the inside or back of a thin panel inside the projection depth.
    function keepFacing(THREE, geometry, normal) {
        const positions = geometry.attributes.position, normals = geometry.attributes.normal, uvs = geometry.attributes.uv;
        if (!positions || !normals) return geometry;
        const keep = [];
        const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
        for (let i = 0; i + 2 < positions.count; i += 3) {
            a.fromBufferAttribute(normals, i); b.fromBufferAttribute(normals, i + 1); c.fromBufferAttribute(normals, i + 2);
            if (a.add(b).add(c).normalize().dot(normal) > 0.2) keep.push(i, i + 1, i + 2);
        }
        if (keep.length === positions.count) return geometry;
        const result = new THREE.BufferGeometry();
        [['position', positions, 3], ['normal', normals, 3], ['uv', uvs, 2]].forEach(function (entry) {
            if (!entry[1]) return;
            const array = new Float32Array(keep.length * entry[2]);
            keep.forEach(function (index, row) {
                for (let k = 0; k < entry[2]; k += 1) array[row * entry[2] + k] = entry[1].array[index * entry[2] + k];
            });
            result.setAttribute(entry[0], new THREE.Float32BufferAttribute(array, entry[2]));
        });
        geometry.dispose();
        return result;
    }

    function decalMaterial(THREE, texture) {
        const material = new THREE.MeshStandardMaterial({
            map: texture, transparent: true, alphaTest: 0.02, depthWrite: false,
            polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4, roughness: 0.55, metalness: 0,
        });
        material.name = 'FacilityEquipmentDecal';
        material.userData = { [DECAL_FLAG]: true, facilityAuthoredFinish: true };
        return material;
    }

    // `target` is a world-space copy of the placement's model with current
    // matrices. Returns world-space meshes ready to add to the scene root.
    function buildDecalMeshes(THREE, DecalGeometry, target, decal, material) {
        if (!DecalGeometry || !target) return [];
        target.updateMatrixWorld(true);
        const pose = projector(THREE, target.matrixWorld, decal.anchor);
        const depth = Math.max(0.03, Math.min(0.25, Math.min(decal.widthMeters, decal.heightMeters) * 0.35));
        const size = new THREE.Vector3(decal.widthMeters, decal.heightMeters, depth);
        const reach = Math.hypot(size.x, size.y, size.z) / 2;
        const meshes = [];
        target.traverse(function (mesh) {
            if (!mesh.isMesh || mesh.isInstancedMesh || !mesh.geometry || !mesh.geometry.attributes.position) return;
            if (mesh.material && mesh.material.userData && mesh.material.userData[DECAL_FLAG]) return;
            if (!mesh.geometry.boundingSphere) mesh.geometry.computeBoundingSphere();
            const sphere = mesh.geometry.boundingSphere.clone().applyMatrix4(mesh.matrixWorld);
            if (sphere.center.distanceTo(pose.position) > sphere.radius + reach) return;
            let geometry = new DecalGeometry(mesh, pose.position, pose.orientation, size);
            if (!geometry.attributes.position || geometry.attributes.position.count === 0) {
                geometry.dispose();
                return;
            }
            geometry = keepFacing(THREE, geometry, pose.normal);
            if (!geometry.attributes.position || geometry.attributes.position.count === 0) {
                geometry.dispose();
                return;
            }
            const decalMesh = new THREE.Mesh(geometry, material);
            decalMesh.name = 'FacilityEquipmentDecal:' + decal.decalId;
            decalMesh.renderOrder = 3;
            decalMesh.userData = { [DECAL_FLAG]: true, decalId: decal.decalId, placementId: decal.placementId };
            meshes.push(decalMesh);
        });
        return meshes;
    }

    // Convert a world-space surface hit into the anchor saved with the layout:
    // the placement's own coordinates, unscaled and unrotated.
    function anchorFromHit(THREE, placementMatrixWorld, point, normal, rotationDegrees) {
        const inverse = new THREE.Matrix4().copy(placementMatrixWorld).invert();
        const local = new THREE.Vector3(point.x, point.y, point.z).applyMatrix4(inverse);
        const localNormal = new THREE.Vector3(normal.x, normal.y, normal.z).transformDirection(inverse);
        const round = function (value, places) { const f = Math.pow(10, places); return Math.round(value * f) / f; };
        return {
            position: { x: round(local.x, 5), y: round(local.y, 5), z: round(local.z, 5) },
            normal: { x: round(localNormal.x, 6), y: round(localNormal.y, 6), z: round(localNormal.z, 6) },
            rotationDegrees: Number(rotationDegrees) || 0,
        };
    }

    return {
        DECAL_FLAG: DECAL_FLAG,
        projector: projector,
        keepFacing: keepFacing,
        decalMaterial: decalMaterial,
        buildDecalMeshes: buildDecalMeshes,
        anchorFromHit: anchorFromHit,
    };
}));
