// Floor light pools for the Facility 3D view (docs/facility-lighting-plan.md, L3), and outdoor light beams (L8).
//
// A lamp is a piece of glowing surface that faces down, like the lens of a high-bay light. A lamp hung high enough
// throws a soft, round pool of light on the floor below it. The pools are a picture of light, not lighting: one
// additive quad per lamp, merged into one mesh per group of models, and they light nothing else. An outdoor lamp
// (a Lights finish with a beam angle) throws its pool where its aim meets the ground, sized by the beam, and shows a
// soft see-through cone down to it. This module finds the lamps in a geometry and builds the quads and the cone; the
// 3D adapter decides when they show.
(function (root, factory) {
    'use strict';

    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityLightPools = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const FACING_DOWN = -0.7;      // a triangle faces down when its unit normal's y is below this
    const MIN_LAMP_AREA = 0.0005;  // square metres; a smaller downward patch is a sliver, not a lamp
    const MIN_LAMP_SHARE = 0.2;    // a lamp faces down: at least this share of its part's surface (a lens: about half)
    const MIN_HEIGHT = 3;          // metres above the floor; lower glows (signs, displays, beacons) throw no pool
    const TEXTURE_SIZE = 64;
    const BEAM_REACH = 80;         // metres along an outdoor lamp's aim to look for the ground (L8)
    const BEAM_STEP = 0.25;        // metres per step while looking
    const BEAM_SEGMENTS = 24;      // around a beam cone
    const partCache = new WeakMap();
    const lampCache = new WeakMap();

    // The parts of a glowing geometry, numbered in the order they first appear: its pieces, joined wherever corners
    // meet (by position, so a hard edge does not split a piece). A part is a lamp when it faces down: its patches of
    // downward-facing triangles of at least MIN_LAMP_AREA add up to at least MIN_LAMP_SHARE of its surface. So a
    // lens is a lamp, and the thin bottom edge of an exit sign is not. A lamp's centre is the area-weighted centre of
    // those patches, and its aim (nx, ny, nz) their area-weighted normal; vertexPart gives each vertex its part's
    // number (L7 switches lamps by area with it). Cached.
    function lampPartsOf(geometry) {
        if (!geometry || !geometry.attributes || !geometry.attributes.position) {
            return { parts: [], lamps: 0, vertexPart: new Float32Array(0) };
        }
        if (partCache.has(geometry)) return partCache.get(geometry);
        const position = geometry.attributes.position;
        const index = geometry.index;
        const triangles = Math.floor((index ? index.count : position.count) / 3);
        const corners = new Map();
        const cornerOf = function (vertex) {
            const key = Math.round(position.getX(vertex) * 1e4) + ',' + Math.round(position.getY(vertex) * 1e4) + ','
                + Math.round(position.getZ(vertex) * 1e4);
            if (!corners.has(key)) corners.set(key, corners.size);
            return corners.get(key);
        };
        const pieces = unionFind();
        const patches = unionFind();
        const vertices = new Int32Array(triangles * 3);
        const firstCorner = new Int32Array(triangles);
        const areas = new Float64Array(triangles);
        const downward = [];
        for (let t = 0; t < triangles; t += 1) {
            const keys = [];
            const p = [];
            for (let k = 0; k < 3; k += 1) {
                const vertex = index ? index.getX(3 * t + k) : 3 * t + k;
                vertices[3 * t + k] = vertex;
                keys.push(cornerOf(vertex));
                p.push([position.getX(vertex), position.getY(vertex), position.getZ(vertex)]);
            }
            keys.forEach(pieces.add);
            pieces.join(keys[0], keys[1]);
            pieces.join(keys[1], keys[2]);
            firstCorner[t] = keys[0];
            const e1 = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]];
            const e2 = [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]];
            const nx = e1[1] * e2[2] - e1[2] * e2[1];
            const ny = e1[2] * e2[0] - e1[0] * e2[2];
            const nz = e1[0] * e2[1] - e1[1] * e2[0];
            const length = Math.sqrt(nx * nx + ny * ny + nz * nz);
            areas[t] = length / 2;
            if (length <= 1e-12 || ny / length >= FACING_DOWN) continue;
            keys.forEach(patches.add);
            patches.join(keys[0], keys[1]);
            patches.join(keys[1], keys[2]);
            // Half the cross product is the triangle's normal weighted by its area.
            downward.push({ key: keys[0], area: length / 2, x: (p[0][0] + p[1][0] + p[2][0]) / 3,
                y: (p[0][1] + p[1][1] + p[2][1]) / 3, z: (p[0][2] + p[1][2] + p[2][2]) / 3,
                nx: nx / 2, ny: ny / 2, nz: nz / 2 });
        }
        const partOfPiece = new Map();
        const parts = [];
        for (let t = 0; t < triangles; t += 1) {
            const piece = pieces.find(firstCorner[t]);
            if (!partOfPiece.has(piece)) {
                partOfPiece.set(piece, parts.length);
                parts.push({ lamp: false, x: 0, y: 0, z: 0, area: 0, surface: 0, nx: 0, ny: 0, nz: 0 });
            }
            parts[partOfPiece.get(piece)].surface += areas[t];
        }
        const patchSums = new Map();
        downward.forEach(function (triangle) {
            const top = patches.find(triangle.key);
            const patch = patchSums.get(top) || { area: 0, x: 0, y: 0, z: 0, nx: 0, ny: 0, nz: 0,
                piece: pieces.find(triangle.key) };
            patch.area += triangle.area;
            patch.x += triangle.x * triangle.area;
            patch.y += triangle.y * triangle.area;
            patch.z += triangle.z * triangle.area;
            patch.nx += triangle.nx;
            patch.ny += triangle.ny;
            patch.nz += triangle.nz;
            patchSums.set(top, patch);
        });
        patchSums.forEach(function (patch) {
            if (patch.area < MIN_LAMP_AREA) return;  // a sliver
            const part = parts[partOfPiece.get(patch.piece)];
            part.area += patch.area;
            part.x += patch.x;
            part.y += patch.y;
            part.z += patch.z;
            part.nx += patch.nx;
            part.ny += patch.ny;
            part.nz += patch.nz;
        });
        parts.forEach(function (part) {
            part.lamp = part.area > 0 && part.area >= MIN_LAMP_SHARE * part.surface;
            if (part.area > 0) {
                part.x /= part.area;
                part.y /= part.area;
                part.z /= part.area;
            }
            const aim = Math.sqrt(part.nx * part.nx + part.ny * part.ny + part.nz * part.nz);
            if (aim > 0) {
                part.nx /= aim;
                part.ny /= aim;
                part.nz /= aim;
            }
        });
        const vertexPart = new Float32Array(position.count);
        for (let t = 0; t < triangles; t += 1) {
            const part = partOfPiece.get(pieces.find(firstCorner[t]));
            for (let k = 0; k < 3; k += 1) vertexPart[vertices[3 * t + k]] = part;
        }
        const result = { parts: parts, lamps: parts.filter(function (part) { return part.lamp; }).length,
            vertexPart: vertexPart };
        partCache.set(geometry, result);
        return result;
    }

    // The lamps in a geometry (see lampPartsOf), in its own coordinates, sorted along x, then z, then y. Cached.
    function lampsOf(geometry) {
        if (!geometry || !geometry.attributes || !geometry.attributes.position) return [];
        if (lampCache.has(geometry)) return lampCache.get(geometry);
        const lamps = lampPartsOf(geometry).parts.filter(function (part) { return part.lamp; }).map(function (part) {
            return { x: part.x, y: part.y, z: part.z, area: part.area, nx: part.nx, ny: part.ny, nz: part.nz };
        });
        lamps.sort(function (a, b) { return a.x - b.x || a.z - b.z || a.y - b.y; });
        lampCache.set(geometry, lamps);
        return lamps;
    }

    function unionFind() {
        const parent = new Map();
        const find = function (key) {
            let top = key;
            while (parent.get(top) !== top) top = parent.get(top);
            while (key !== top) {
                const next = parent.get(key);
                parent.set(key, top);
                key = next;
            }
            return top;
        };
        return {
            add: function (key) { if (!parent.has(key)) parent.set(key, key); },
            find: find,
            join: function (a, b) {
                const topA = find(a);
                const topB = find(b);
                if (topA !== topB) parent.set(topB, topA);
            },
        };
    }

    // The pool under a lamp hung `height` metres up: wider the higher it hangs, within reason.
    function poolRadius(height) {
        return Math.min(6, Math.max(1.5, 0.5 * height));
    }

    // Where an outdoor lamp's beam meets the ground (L8): from `origin` along the unit vector `aim` until it reaches
    // the ground, groundAt(x, z, nearY) giving the ground's height under a point. The pool there has the distance
    // along the aim times tan(beam angle / 2) as its radius, so a wall light's pool lands in front of the wall. Null
    // when the aim does not point down or meets no ground within BEAM_REACH.
    function aimedPool(origin, aim, beamAngleDegrees, groundAt) {
        if (!(aim.y < 0)) return null;
        let before = 0;
        let gapBefore = origin.y - groundAt(origin.x, origin.z, origin.y);
        if (!(gapBefore > 0)) return null;
        for (let t = BEAM_STEP; t <= BEAM_REACH + 1e-9; t += BEAM_STEP) {
            const y = origin.y + aim.y * t;
            const gap = y - groundAt(origin.x + aim.x * t, origin.z + aim.z * t, y);
            if (gap <= 0) {
                const length = before + (t - before) * gapBefore / (gapBefore - gap);
                const x = origin.x + aim.x * length;
                const z = origin.z + aim.z * length;
                return { x: x, y: groundAt(x, z, origin.y + aim.y * length), z: z, length: length,
                    radius: length * Math.tan(beamAngleDegrees * Math.PI / 360) };
            }
            before = t;
            gapBefore = gap;
        }
        return null;
    }

    // The pools a mesh throws, for every copy of it (an instanced mesh draws many), in the coordinates `toRoot`
    // maps world space into. Only lamps that still face down there and hang MIN_HEIGHT above `floorY` count.
    // With `beam` ({angleDegrees, groundAt}, an outdoor Lights finish, L8) each lamp's pool lies where its aim meets
    // the ground instead (aimedPool), MIN_HEIGHT above it, and also records the lamp, its aim and the beam's length.
    function poolsOf(THREE, mesh, toRoot, color, floorY, beam) {
        const lamps = lampsOf(mesh && mesh.geometry);
        if (!lamps.length) return [];
        const base = new THREE.Matrix4().multiplyMatrices(toRoot, mesh.matrixWorld);
        const instance = new THREE.Matrix4();
        const matrix = new THREE.Matrix4();
        const point = new THREE.Vector3();
        const down = new THREE.Vector3();
        const aim = new THREE.Vector3();
        const pools = [];
        const copies = mesh.isInstancedMesh ? mesh.count : 1;
        for (let copy = 0; copy < copies; copy += 1) {
            if (mesh.isInstancedMesh) {
                mesh.getMatrixAt(copy, instance);
                matrix.multiplyMatrices(base, instance);
            } else {
                matrix.copy(base);
            }
            if (Math.abs(matrix.determinant()) < 1e-12) continue;  // a hidden, zero-scale copy
            down.set(0, -1, 0).transformDirection(matrix);
            if (down.y > FACING_DOWN) continue;  // tipped over: its lamps no longer face the floor
            lamps.forEach(function (lamp) {
                point.set(lamp.x, lamp.y, lamp.z).applyMatrix4(matrix);
                if (beam) {
                    aim.set(lamp.nx, lamp.ny, lamp.nz).transformDirection(matrix);
                    if (aim.y > FACING_DOWN) return;
                    const hit = aimedPool(point, aim, beam.angleDegrees, beam.groundAt);
                    if (!hit || point.y - hit.y < MIN_HEIGHT) return;
                    pools.push({ x: hit.x, y: hit.y, z: hit.z, radius: hit.radius, color: color,
                        lamp: { x: point.x, y: point.y, z: point.z }, aim: { x: aim.x, y: aim.y, z: aim.z },
                        length: hit.length, beamAngleDegrees: beam.angleDegrees });
                    return;
                }
                const height = point.y - floorY;
                if (height < MIN_HEIGHT) return;
                pools.push({ x: point.x, z: point.z, radius: poolRadius(height), color: color });
            });
        }
        return pools;
    }

    // A round spot with a soft edge: white, with the falloff in alpha (additive blending adds color x alpha).
    function poolTexture(THREE) {
        const size = TEXTURE_SIZE;
        const data = new Uint8Array(size * size * 4);
        for (let y = 0; y < size; y += 1) {
            for (let x = 0; x < size; x += 1) {
                const dx = (x + 0.5) / size * 2 - 1;
                const dy = (y + 0.5) / size * 2 - 1;
                const d2 = Math.min(1, dx * dx + dy * dy);
                const i = (y * size + x) * 4;
                data[i] = 255;
                data[i + 1] = 255;
                data[i + 2] = 255;
                data[i + 3] = Math.round(255 * (1 - d2) * (1 - d2));
            }
        }
        const texture = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
        texture.magFilter = THREE.LinearFilter;
        texture.minFilter = THREE.LinearMipmapLinearFilter;
        texture.generateMipmaps = true;
        texture.needsUpdate = true;
        return texture;
    }

    // One square per pool, lying face up at height `y` (above its own ground, for an outdoor lamp's pool), colored
    // per pool.
    function poolGeometry(THREE, pools, y) {
        const positions = new Float32Array(pools.length * 12);
        const uvs = new Float32Array(pools.length * 8);
        const colors = new Float32Array(pools.length * 12);
        const indices = new Uint32Array(pools.length * 6);
        const corners = [[-1, -1, 0, 0], [1, -1, 1, 0], [1, 1, 1, 1], [-1, 1, 0, 1]];
        pools.forEach(function (pool, p) {
            const height = pool.y === undefined ? y : pool.y + y;
            corners.forEach(function (corner, k) {
                const v = p * 4 + k;
                positions.set([pool.x + corner[0] * pool.radius, height, pool.z + corner[1] * pool.radius], v * 3);
                uvs.set([corner[2], corner[3]], v * 2);
                colors.set([pool.color.r, pool.color.g, pool.color.b], v * 3);
            });
            const v = p * 4;
            indices.set([v, v + 2, v + 1, v, v + 3, v + 2], p * 6);  // counter-clockwise seen from above
        });
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        geometry.setIndex(new THREE.BufferAttribute(indices, 1));
        geometry.computeBoundingSphere();
        geometry.computeBoundingBox();
        return geometry;
    }

    // A beam (L8): an open cone with its tip at the origin and its base, radius 1, at y -1, facing out. beamAlong runs
    // from 0 at the tip to 1 at the base. The 3D view places one per outdoor lamp: scaled (radius, length, radius),
    // turned from straight down to the lamp's aim and moved to the lamp.
    function beamGeometry(THREE) {
        const segments = BEAM_SEGMENTS;
        const positions = [];
        const normals = [];
        const along = [];
        const indices = [];
        const s = Math.SQRT1_2;
        for (let i = 0; i <= segments; i += 1) {  // the base ring (its seam doubled)
            const angle = 2 * Math.PI * i / segments;
            positions.push(Math.cos(angle), -1, Math.sin(angle));
            normals.push(s * Math.cos(angle), s, s * Math.sin(angle));
            along.push(1);
        }
        for (let i = 0; i < segments; i += 1) {  // the tip, once per side, with that side's normal
            const angle = 2 * Math.PI * (i + 0.5) / segments;
            positions.push(0, 0, 0);
            normals.push(s * Math.cos(angle), s, s * Math.sin(angle));
            along.push(0);
            indices.push(segments + 1 + i, i + 1, i);
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
        geometry.setAttribute('beamAlong', new THREE.Float32BufferAttribute(along, 1));
        geometry.setIndex(indices);
        geometry.computeBoundingSphere();
        return geometry;
    }

    // The beam's look: brightest at the lamp, fading toward the ground and toward the cone's edge as seen (where
    // its surface turns away from the eye). Additive, so it only adds light; per-cone color from the instance color.
    const BEAM_VERTEX_SHADER = [
        'attribute float beamAlong;',
        'varying float vBeamAlong;',
        'varying float vBeamFacing;',
        'varying vec3 vBeamColor;',
        '#include <common>',
        'void main() {',
        '    #include <beginnormal_vertex>',
        '    #include <defaultnormal_vertex>',
        '    #include <begin_vertex>',
        '    #include <project_vertex>',
        '    vBeamAlong = beamAlong;',
        '    vBeamFacing = abs(dot(normalize(transformedNormal), normalize(-mvPosition.xyz)));',
        '    vBeamColor = vec3(1.0);',
        '    #ifdef USE_INSTANCING_COLOR',
        '    vBeamColor = instanceColor;',
        '    #endif',
        '}',
    ].join('\n');
    const BEAM_FRAGMENT_SHADER = [
        'uniform float facilityBeamStrength;',
        'varying float vBeamAlong;',
        'varying float vBeamFacing;',
        'varying vec3 vBeamColor;',
        'void main() {',
        '    float down = 1.0 - clamp(vBeamAlong, 0.0, 1.0);',
        '    gl_FragColor = vec4(vBeamColor, facilityBeamStrength * down * down * vBeamFacing * vBeamFacing);',
        '    #include <colorspace_fragment>',
        '}',
    ].join('\n');

    return {
        FACING_DOWN: FACING_DOWN,
        MIN_LAMP_AREA: MIN_LAMP_AREA,
        MIN_LAMP_SHARE: MIN_LAMP_SHARE,
        MIN_HEIGHT: MIN_HEIGHT,
        BEAM_REACH: BEAM_REACH,
        BEAM_VERTEX_SHADER: BEAM_VERTEX_SHADER,
        BEAM_FRAGMENT_SHADER: BEAM_FRAGMENT_SHADER,
        lampPartsOf: lampPartsOf,
        lampsOf: lampsOf,
        poolRadius: poolRadius,
        aimedPool: aimedPool,
        poolsOf: poolsOf,
        poolTexture: poolTexture,
        poolGeometry: poolGeometry,
        beamGeometry: beamGeometry,
    };
}));
