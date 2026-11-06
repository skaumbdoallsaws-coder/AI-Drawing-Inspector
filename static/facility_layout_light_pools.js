// Floor light pools for the Facility 3D view (docs/facility-lighting-plan.md, L3), and outdoor light beams (L8).
//
// A lamp is a piece of glowing surface that faces down, like the lens of a high-bay light. A lamp hung high enough
// throws a soft, round pool of light on the floor below it. The pools are a picture of light, not lighting: one
// additive quad per lamp, merged into one mesh per group of models, and they light nothing else. An outdoor lamp
// (a Lights finish with a beam angle) throws its pool where its aim meets the ground, sized by the beam, and shows a
// soft see-through cone down to it. This module finds the lamps in a geometry and builds the quads and the cone; the
// 3D adapter decides when they show.
//
// Lamps that light things (2026-11-02, the gym's Evening): a pendant hung below MIN_HEIGHT over a table, and an
// accent spot (a Lights finish whose emission is marked accent), are candidates for a few real spot lights without
// shadows (spotsOf, spotSettings; the adapter gives SPOT_COUNT of them to the candidates nearest the view). The
// general lighting's pools also add a gentle fill on everything standing under them: fillField sums the pools into
// a small map over the plan, and patchFillShader adds it to a lit material's indirect light below the lamps. The
// fill is only under zone ceilings (the user's choice, 2026-11-02): the adapter passes only pools whose lamp is in
// a zone with a ceiling, and fillMask gives the shader those zones' footprint, outside which it adds nothing.
//
// Low lights and uplights (2026-11-05, the gym's garden): an outdoor finish marked low (a bollard, a path light, a
// lantern) throws its pool from LOW_MIN_HEIGHT up, from each glowing piece with a patch facing down (bulbsOf), and
// shows no beam; an accent finish marked uplight (a spike light at a palm's foot) is aimed along the patches of its
// lens that face up.
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
    const LOW_MIN_HEIGHT = 0.1;    // metres above the ground: a low outdoor light (a bollard) throws its pool from here
    const TEXTURE_SIZE = 64;
    const BEAM_REACH = 80;         // metres along an outdoor lamp's aim to look for the ground (L8)
    const BEAM_STEP = 0.25;        // metres per step while looking
    const BEAM_SEGMENTS = 24;      // around a beam cone
    const SPOT_COUNT = 8;          // real spot lights in Evening; a fixed number, so lit materials compile once
    const SPOT_MIN_HEIGHT = 0.5;   // metres above the floor: a pendant hangs between this and MIN_HEIGHT
    const SPOT_REACH = { accent: 8, pendant: 6 };  // metres; a spot's light fades to nothing there
    const SPOT_DEFAULT_LUMENS = { accent: 700, pendant: 1500 };  // a lamp without estimate data (an authored glow)
    const SPOT_MAX_ANGLE = 85;     // degrees from the aim to a spot's edge
    const SPOT_PENUMBRA = 0.8;
    // three's light units per lux (an estimated, typical lux), set by eye in the gym's Evening: a warm white pendant
    // (4,000 lm, 110 degrees) gives about 500 lux on a table 1.7 m below it, which then reads about as lit as under
    // the daytime scene's sun (2.4).
    const LUX_TO_SCENE = 1 / 250;
    const FILL_SPREAD = 2;         // general lighting's fill reaches this many pool radii from a lamp
    const FILL_PEAK = 0.7;         // fill (three's irradiance) under one lamp, a quarter of the daytime sun's
    const FILL_LIMIT = 1.5;        // where many lamps overlap
    const FILL_CELL = 0.25;        // metres per texel of the fill map, coarser on a large plan
    const FILL_MAX_CELLS = 512;    // per side
    const FILL_MASK_SUBDIVIDE = 2; // the ceiling mask's texels per fill map texel, each way
    const FILL_EDGE_TEXELS = 2;    // the ceiling mask's distances reach this many of its texels from the edge
    const FILL_MASK_INSET = 0.01;  // metres: a face on a ceiling zone's edge (a wall's outer face) is outside
    const FILL_EDGE_PROBE = 1e-3;  // metres: an edge piece is an edge if points this far to its sides differ
    const FILL_CORNER_CUT = 1e-4;  // metres: an edge is cut at another outline's corner nearer than this
    const FILL_ALONGSIDE = 0.1;    // the sine of the widest angle at which another edge runs alongside an edge piece
    const FILL_BELOW = 0.05;       // the fill lights what is at least this far below its lamps (not a ceiling)
    const partCache = new WeakMap();
    const lampCache = new WeakMap();
    const upPartCache = new WeakMap();
    const upLampCache = new WeakMap();

    // The parts of a glowing geometry, numbered in the order they first appear: its pieces, joined wherever corners
    // meet (by position, so a hard edge does not split a piece). A part is a lamp when it faces down: its patches of
    // downward-facing triangles of at least MIN_LAMP_AREA add up to at least MIN_LAMP_SHARE of its surface. So a
    // lens is a lamp, and the thin bottom edge of an exit sign is not. A lamp's centre is the area-weighted centre of
    // those patches, and its aim (nx, ny, nz) their area-weighted normal; vertexPart gives each vertex its part's
    // number (L7 switches lamps by area with it). Cached. With UP (an uplight's lens, 2026-11-05) the same for the
    // patches that face up, cached apart.
    function lampPartsOf(geometry, up) {
        if (!geometry || !geometry.attributes || !geometry.attributes.position) {
            return { parts: [], lamps: 0, vertexPart: new Float32Array(0) };
        }
        const cache = up ? upPartCache : partCache;
        if (cache.has(geometry)) return cache.get(geometry);
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
            if (length <= 1e-12 || (up ? -ny : ny) / length >= FACING_DOWN) continue;
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
        cache.set(geometry, result);
        return result;
    }

    // The lamps in a geometry (see lampPartsOf; with UP, those facing up), in its own coordinates, sorted along x,
    // then z, then y. Cached.
    function lampsOf(geometry, up) {
        if (!geometry || !geometry.attributes || !geometry.attributes.position) return [];
        const cache = up ? upLampCache : lampCache;
        if (cache.has(geometry)) return cache.get(geometry);
        const parts = lampPartsOf(geometry, up).parts;
        const lamps = parts.filter(function (part) { return part.lamp; }).map(function (part) {
            return { x: part.x, y: part.y, z: part.z, area: part.area, nx: part.nx, ny: part.ny, nz: part.nz };
        });
        lamps.sort(function (a, b) { return a.x - b.x || a.z - b.z || a.y - b.y; });
        cache.set(geometry, lamps);
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
    // A low outdoor light (beam.low, 2026-11-05: a bollard, a lantern) throws one from each glowing piece with a patch
    // facing down (bulbsOf: a lantern's glass faces down only at its foot), LOW_MIN_HEIGHT above the ground, and its
    // pool is marked low: it shows no beam. A copy's low pools from this mesh share its light: each gets the color over
    // their number, so a festoon string's eight bulbs together are as bright as one lantern. Each lit mesh is one light
    // (the coverage estimate shares per part the same way).
    function poolsOf(THREE, mesh, toRoot, color, floorY, beam) {
        const low = Boolean(beam && beam.low);
        const lamps = low ? bulbsOf(mesh && mesh.geometry) : lampsOf(mesh && mesh.geometry);
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
            const first = pools.length;
            lamps.forEach(function (lamp) {
                point.set(lamp.x, lamp.y, lamp.z).applyMatrix4(matrix);
                if (beam) {
                    aim.set(lamp.nx, lamp.ny, lamp.nz).transformDirection(matrix);
                    if (aim.y > FACING_DOWN) return;
                    const hit = aimedPool(point, aim, beam.angleDegrees, beam.groundAt);
                    if (!hit || point.y - hit.y < (low ? LOW_MIN_HEIGHT : MIN_HEIGHT)) return;
                    const pool = { x: hit.x, y: hit.y, z: hit.z, radius: hit.radius, color: color,
                        lamp: { x: point.x, y: point.y, z: point.z }, aim: { x: aim.x, y: aim.y, z: aim.z },
                        length: hit.length, beamAngleDegrees: beam.angleDegrees };
                    if (low) pool.low = true;
                    pools.push(pool);
                    return;
                }
                const height = point.y - floorY;
                if (height < MIN_HEIGHT) return;
                pools.push({ x: point.x, z: point.z, radius: poolRadius(height), color: color, lampY: point.y });
            });
            const made = pools.length - first;
            if (low && made > 1) {
                const shared = color.clone().multiplyScalar(1 / made);
                for (let k = first; k < pools.length; k += 1) pools[k].color = shared;
            }
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

    // ---- Lamps that light things (2026-11-02) ----------------------------------------------------------------
    // The parts of a glowing geometry with a patch facing down, as lampsOf gives lamps, without the share a lamp
    // needs: a bare bulb under a pendant's shade faces down only at its tip (about a tenth of its surface). Cached.
    const bulbCache = new WeakMap();
    function bulbsOf(geometry) {
        if (!geometry || !geometry.attributes || !geometry.attributes.position) return [];
        if (bulbCache.has(geometry)) return bulbCache.get(geometry);
        const bulbs = lampPartsOf(geometry).parts.filter(function (part) { return part.area > 0; }).map(function (part) {
            return { x: part.x, y: part.y, z: part.z, area: part.area, nx: part.nx, ny: part.ny, nz: part.nz };
        });
        bulbCache.set(geometry, bulbs);
        return bulbs;
    }

    // The spot light candidates a glowing mesh gives, one per copy (an instanced mesh draws many), in the coordinates
    // `toRoot` maps world space into: its accent lamps (glow.accent: aimed along the lens as placed, at any height)
    // or else its pendants: a finish with lighting data (glow.lumens, from its estimate: never a sign, beacon or
    // signal lamp) on lamps or bare bulbs (bulbsOf) still facing down there, hung SPOT_MIN_HEIGHT to MIN_HEIGHT above
    // `floorY` (higher ones throw pools). A copy's lamps make one spot at their area-weighted centre, aimed along
    // their mean aim. An uplight (glow.uplight, 2026-11-05) is aimed along the part of its lens that faces up.
    function spotsOf(THREE, mesh, toRoot, glow, floorY) {
        if (!glow) return [];
        const accent = glow.accent === true;
        const geometry = mesh && mesh.geometry;
        const lamps = accent ? lampsOf(geometry, glow.uplight === true)
            : Number(glow.lumens) > 0 ? bulbsOf(geometry) : [];
        if (!lamps.length) return [];
        const base = new THREE.Matrix4().multiplyMatrices(toRoot, mesh.matrixWorld);
        const instance = new THREE.Matrix4();
        const matrix = new THREE.Matrix4();
        const point = new THREE.Vector3();
        const aim = new THREE.Vector3();
        const spots = [];
        const copies = mesh.isInstancedMesh ? mesh.count : 1;
        for (let copy = 0; copy < copies; copy += 1) {
            if (mesh.isInstancedMesh) {
                mesh.getMatrixAt(copy, instance);
                matrix.multiplyMatrices(base, instance);
            } else {
                matrix.copy(base);
            }
            if (Math.abs(matrix.determinant()) < 1e-12) continue;  // a hidden, zero-scale copy
            const sum = { x: 0, y: 0, z: 0, ax: 0, ay: 0, az: 0, area: 0, lamps: 0 };
            lamps.forEach(function (lamp) {
                point.set(lamp.x, lamp.y, lamp.z).applyMatrix4(matrix);
                aim.set(lamp.nx, lamp.ny, lamp.nz).transformDirection(matrix);
                if (!accent) {
                    const height = point.y - floorY;
                    if (aim.y > FACING_DOWN || height < SPOT_MIN_HEIGHT || height >= MIN_HEIGHT) return;
                }
                const weight = lamp.area > 0 ? lamp.area : 1;
                sum.x += point.x * weight;
                sum.y += point.y * weight;
                sum.z += point.z * weight;
                sum.ax += aim.x * weight;
                sum.ay += aim.y * weight;
                sum.az += aim.z * weight;
                sum.area += weight;
                sum.lamps += 1;
            });
            const length = Math.hypot(sum.ax, sum.ay, sum.az);
            if (!sum.lamps || !(length > 0)) continue;
            spots.push({ x: sum.x / sum.area, y: sum.y / sum.area, z: sum.z / sum.area,
                aim: { x: sum.ax / length, y: sum.ay / length, z: sum.az / length },
                kind: accent ? 'accent' : 'pendant', lamps: sum.lamps });
        }
        return spots;
    }

    // A spot light's settings for a candidate: three's SpotLight intensity is in candela, the peak of a beam whose
    // intensity falls as cos^m off its aim, half its peak at half the beam angle (as the coverage estimate, CC), times
    // LUX_TO_SCENE. The lumens and beam come from the finish's estimate data, else its emission's beam angle, else
    // typical values. The cone runs to 1.5 times half the beam (at most SPOT_MAX_ANGLE) with a soft edge, so it is
    // about half as bright at half the beam angle; the light fades to nothing at SPOT_REACH.
    function spotSettings(spot, glow) {
        const kind = spot.kind === 'accent' ? 'accent' : 'pendant';
        const lumens = Number(glow && glow.lumens) > 0 ? Number(glow.lumens) : SPOT_DEFAULT_LUMENS[kind];
        let beam = Number(glow && (glow.estimateBeamAngleDegrees || glow.beamAngleDegrees));
        if (!(beam >= 10 && beam <= 170)) beam = kind === 'accent' ? 30 : 110;
        const half = beam * Math.PI / 360;
        const m = Math.log(0.5) / Math.log(Math.cos(half));
        const candela = lumens * (m + 1) / (2 * Math.PI);
        return {
            intensity: candela * LUX_TO_SCENE,
            angle: Math.min(SPOT_MAX_ANGLE * Math.PI / 180, 1.5 * half),
            penumbra: SPOT_PENUMBRA,
            distance: SPOT_REACH[kind],
            decay: 2,
        };
    }

    // The fill general lighting gives what stands under it, as a map over the plan: each lit pool ({x, z, radius,
    // color {r, g, b}, lampY}) adds its color times FILL_PEAK, falling smoothly to nothing FILL_SPREAD radii out;
    // the sum is capped at FILL_LIMIT. The alpha is the highest lamp over the texel, less FILL_BELOW: the fill
    // lights only what is lower. Null without pools. Texel (i, j) covers x from minX + i cell, z from minZ + j cell.
    function fillField(pools) {
        const lit = (pools || []).filter(function (pool) {
            return pool && Number.isFinite(pool.x) && Number.isFinite(pool.z) && pool.radius > 0
                && Number.isFinite(pool.lampY) && pool.color;
        });
        if (!lit.length) return null;
        let minX = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxZ = -Infinity;
        lit.forEach(function (pool) {
            const reach = pool.radius * FILL_SPREAD;
            minX = Math.min(minX, pool.x - reach);
            minZ = Math.min(minZ, pool.z - reach);
            maxX = Math.max(maxX, pool.x + reach);
            maxZ = Math.max(maxZ, pool.z + reach);
        });
        const cell = Math.max(FILL_CELL, (maxX - minX) / FILL_MAX_CELLS, (maxZ - minZ) / FILL_MAX_CELLS);
        const cols = Math.max(1, Math.ceil((maxX - minX) / cell));
        const rows = Math.max(1, Math.ceil((maxZ - minZ) / cell));
        const data = new Float32Array(cols * rows * 4);
        lit.forEach(function (pool) {
            const reach = pool.radius * FILL_SPREAD;
            const top = pool.lampY - FILL_BELOW;
            const i0 = Math.max(0, Math.floor((pool.x - reach - minX) / cell));
            const i1 = Math.min(cols - 1, Math.floor((pool.x + reach - minX) / cell));
            const j0 = Math.max(0, Math.floor((pool.z - reach - minZ) / cell));
            const j1 = Math.min(rows - 1, Math.floor((pool.z + reach - minZ) / cell));
            for (let j = j0; j <= j1; j += 1) {
                const dz = minZ + (j + 0.5) * cell - pool.z;
                for (let i = i0; i <= i1; i += 1) {
                    const dx = minX + (i + 0.5) * cell - pool.x;
                    const t = (dx * dx + dz * dz) / (reach * reach);
                    if (t >= 1) continue;
                    const weight = FILL_PEAK * (1 - t) * (1 - t);
                    const k = (j * cols + i) * 4;
                    data[k] += pool.color.r * weight;
                    data[k + 1] += pool.color.g * weight;
                    data[k + 2] += pool.color.b * weight;
                    data[k + 3] = Math.max(data[k + 3], top);
                }
            }
        });
        for (let k = 0; k < data.length; k += 4) {
            for (let c = 0; c < 3; c += 1) data[k + c] = Math.min(FILL_LIMIT, data[k + c]);
        }
        return { minX: minX, minZ: minZ, cell: cell, cols: cols, rows: rows, data: data, pools: lit.length };
    }

    // The zone ceilings' footprint over a fill map ({minX, minZ, cell, cols, rows}), for the shader to cut the fill
    // off at its edge: a map FILL_MASK_SUBDIVIDE times finer over the same plan, with `channels` (1, 2 or 4) values
    // per texel. The shader takes the largest; above zero it adds the fill.
    // - A sample mixes the texels around it, and they read the edges within FILL_EDGE_TEXELS texels, so only the
    //   outlines within four texels (0.5 m) of a point can change its value. Outlines nearer each other than that
    //   without touching clash, and go in different channels (maskChannels): every point inside reads, in one
    //   channel, the outlines around it less those across a gap from it, as if those were not there. A room's wall a
    //   few centimetres from the next room keeps its fill, also when a hallway joins them or rooms meet nearby, and
    //   outlines that meet share a channel there, so an edge two of them share is not an edge.
    // - A channel holds, per texel, the signed distance in metres (+ inside) to the edge of its footprints, clamped
    //   to FILL_EDGE_TEXELS texels, less FILL_MASK_INSET (maskField). Read with linear filtering it is above zero
    //   only inside them:
    //   - Each texel is also held at or below the signed distance to the line of every footprint edge within a
    //     texel diagonal of it (that edge may cross a cell the texel is a corner of). Linear filtering mixes a
    //     cell's four texels, so in a cell an edge crosses the value is at most that edge's line distance, which is
    //     below zero on the edge's outer side, where any outside point of the cell is. A cell no edge crosses is
    //     all inside or all outside.
    //   - Along a straight edge that changes nothing: the cut is exactly on the edge, less the inset. Only in an
    //     inner (reflex) corner of a footprint does it take about a texel and a half off the inside.
    //   - The map's own border texels are outside, so the clamped reads beyond the last texel centres are too.
    // - Outside every ceiling, every channel is at or below zero (a channel is a union of ceilings). When more than
    //   four channels would be needed, some outlines share one: near the ones they clash with their fill is cut a
    //   little, never lit outside. So is a single outline's own notch narrower than a texel diagonal, or a notch
    //   between two outlines that touch (they share a channel).
    // Built once per grid and outlines: each outline's inside by scanlines, the distances only near the edges.
    function fillMask(grid, outlines) {
        const minX = grid.minX;
        const minZ = grid.minZ;
        const cell = grid.cell / FILL_MASK_SUBDIVIDE;
        const cols = grid.cols * FILL_MASK_SUBDIVIDE;
        const rows = grid.rows * FILL_MASK_SUBDIVIDE;
        const shapes = (outlines || []).map(function (outline) {
            return (Array.isArray(outline) ? outline : []).filter(function (point) {
                return point && Number.isFinite(point.x) && Number.isFinite(point.z);
            });
        }).filter(function (points) { return points.length >= 3; });
        const reach = FILL_EDGE_TEXELS * cell;
        // The views coloured in four channels; with no such colouring, the grouping of aca8df1 (maskGroups).
        const channelled = maskChannels(shapes, minX, minZ, cell, cols, rows, reach + 2 * cell);
        const groups = channelled || maskGroups(shapes, 2 * reach + 2 * cell);
        const channels = groups.length <= 2 ? Math.max(1, groups.length) : 4;
        const data = new Float32Array(cols * rows * channels).fill(-reach - FILL_MASK_INSET);
        groups.forEach(function (group, channel) {
            const field = maskField(group, minX, minZ, cell, cols, rows, !channelled);
            for (let k = 0; k < field.length; k += 1) data[k * channels + channel] = field[k];
        });
        return { minX: minX, minZ: minZ, cell: cell, cols: cols, rows: rows, channels: channels, data: data };
    }

    // The outlines in at most four channels, as lists of outlines. Two outlines clash when they do not touch (overlap
    // or meet) but are nearer each other than `apart`, the reach of a sample: in one channel the edges of one would
    // cut the other's fill.
    // - An outline inside another adds no edge and no area: it is left out (the other covers it in every channel).
    // - A point inside a ceiling should read its view: the outlines within `apart` of it, nearest first from one that
    //   holds it, leaving out any that clashes with one already in. Two rooms 8 cm apart joined by a hallway: in the
    //   first room the first and the hallway; in the hallway over the gap, the hallway and the nearer room. Where
    //   rooms meet, all of them.
    // - Outlines that clash with none are in every view and every channel; with no clash at all there is one channel
    //   with every outline. Clashing outlines with the same clash partners (a unit) are in a view all or none: none
    //   clashes with another, and what keeps one out keeps all out. Views and channels take a unit as one.
    // - Views are taken at each texel corner (the centre of the cell a sample mixes), from each outline within half
    //   a cell diagonal of it, over the outlines within `apart` and a cell, so they hold for every point of the cell.
    //   Only corners within that distance of an outline's edge need one: a corner deep inside an outline reads the
    //   full value in any channel with it, and one far from every outline is dark in all.
    // - A channel holds views with no clash between any of their outlines, so a point's channel has, near it, exactly
    //   its view: a colouring of the views in four colours, two views that would clash in different ones (maskColours).
    //   Null when it finds none (the caller then uses maskGroups).
    // - Ties go by plan position, so the mask does not depend on the order of the outlines.
    function maskChannels(shapes, minX, minZ, cell, cols, rows, apart) {
        const list = uncoveredOutlines(shapes);
        const count = list.length;
        const boxes = list.map(outlineBox);
        const clashes = list.map(function () { return []; });
        for (let i = 0; i < count; i += 1) {
            for (let j = i + 1; j < count; j += 1) {
                if (boxGap(boxes[i], boxes[j]) >= apart) continue;
                const distance = outlineDistance(list[i], list[j]);
                if (distance > 1e-4 && distance < apart) {
                    clashes[i].push(j);
                    clashes[j].push(i);
                }
            }
        }
        const clashing = clashes.map(function (others) { return others.length > 0; });
        if (clashing.indexOf(true) < 0) return [shapes];
        // Ties go by plan position, not by the order of the outlines.
        const keys = list.map(function (points) { return points.map(function (q) { return q.x + ' ' + q.z; }).join(','); });
        const byPlace = list.map(function (shape, k) { return k; }).sort(function (a, b) {
            const p = boxes[a];
            const q = boxes[b];
            return p.minX - q.minX || p.minZ - q.minZ || p.maxX - q.maxX || p.maxZ - q.maxZ
                || (keys[a] < keys[b] ? -1 : keys[a] > keys[b] ? 1 : 0);
        });
        // Units, numbered by plan position.
        const unitOf = new Int32Array(count).fill(-1);
        const units = [];
        const unitKeys = new Map();
        byPlace.forEach(function (k) {
            if (!clashing[k]) return;
            const key = clashes[k].slice().sort(function (a, b) { return a - b; }).join(',');
            if (!unitKeys.has(key)) {
                unitKeys.set(key, units.length);
                units.push([]);
            }
            unitOf[k] = unitKeys.get(key);
            units[unitOf[k]].push(k);
        });
        const unitCount = units.length;
        const unitClashes = units.map(function (members) {
            const others = [];
            clashes[members[0]].forEach(function (k) { if (others.indexOf(unitOf[k]) < 0) others.push(unitOf[k]); });
            return others;
        });
        const clash = function (a, b) { return unitClashes[a].indexOf(b) >= 0; };
        const around = apart + cell;
        const around2 = around * around;
        const own2 = cell * cell / 2 * (1 + 1e-6);
        const spanOf = function (box) {
            return {
                minX: box.minX - around, maxX: box.maxX + around, minZ: box.minZ - around, maxZ: box.maxZ + around,
                i0: Math.max(0, Math.floor((box.minX - around - minX) / cell)),
                i1: Math.min(cols, Math.ceil((box.maxX + around - minX) / cell)),
                j0: Math.max(0, Math.floor((box.minZ - around - minZ) / cell)),
                j1: Math.min(rows, Math.ceil((box.maxZ + around - minZ) / cell)),
            };
        };
        const spans = boxes.map(spanOf);
        const unitSpans = units.map(function (members) {
            const box = { minX: Infinity, minZ: Infinity, maxX: -Infinity, maxZ: -Infinity };
            members.forEach(function (k) {
                box.minX = Math.min(box.minX, boxes[k].minX);
                box.minZ = Math.min(box.minZ, boxes[k].minZ);
                box.maxX = Math.max(box.maxX, boxes[k].maxX);
                box.maxZ = Math.max(box.maxZ, boxes[k].maxZ);
            });
            return spanOf(box);
        });
        // A view keeps two units only near both and when they do not clash: the corners within `around` of such a
        // pair, row by row, and of them only those within `around` of an outline's edge (marked below).
        const rects = [];
        for (let a = 0; a < unitCount; a += 1) {
            for (let b = a + 1; b < unitCount; b += 1) {
                if (clash(a, b)) continue;
                const rect = {
                    i0: Math.max(unitSpans[a].i0, unitSpans[b].i0), i1: Math.min(unitSpans[a].i1, unitSpans[b].i1),
                    j0: Math.max(unitSpans[a].j0, unitSpans[b].j0), j1: Math.min(unitSpans[a].j1, unitSpans[b].j1),
                };
                if (rect.i0 <= rect.i1 && rect.j0 <= rect.j1) rects.push(rect);
            }
        }
        const views = new Map();
        const record = function (view) {
            if (view.length < 2) return;
            const kept = view.slice().sort(function (a, b) { return a - b; });
            const key = kept.join(',');
            if (!views.has(key)) views.set(key, kept);
        };
        if (rects.length) {
            const row = cols + 1;
            const edges = new Uint8Array(row * (rows + 1));
            list.forEach(function (points) {
                points.forEach(function (p, k) { markBand(edges, p, points[(k + 1) % points.length], around, minX, minZ, cell, cols, rows); });
            });
            // The outlines near each tile of 16 x 16 texel corners, the largest first (likely to hold a corner deep).
            const TILE = 16;
            const tileCols = Math.floor(cols / TILE) + 1;
            const tiles = [];
            const areas = list.map(outlineArea);
            spans.forEach(function (span, k) {
                for (let tj = Math.floor(span.j0 / TILE); tj <= Math.floor(span.j1 / TILE); tj += 1) {
                    for (let ti = Math.floor(span.i0 / TILE); ti <= Math.floor(span.i1 / TILE); ti += 1) {
                        const at = tj * tileCols + ti;
                        (tiles[at] = tiles[at] || []).push(k);
                    }
                }
            });
            tiles.forEach(function (tile) { if (tile) tile.sort(function (a, b) { return areas[b] - areas[a] || a - b; }); });
            const distance = new Float64Array(unitCount);
            const seen = new Float64Array(unitCount);
            const blocked = new Float64Array(unitCount);
            let stamp = 0;
            let last = [];
            const order = function (a, b) { return distance[a] - distance[b] || a - b; };
            const greedy = function (near, seed) {
                stamp += 1;
                const view = [];
                const take = function (u) {
                    view.push(u);
                    unitClashes[u].forEach(function (other) { blocked[other] = stamp; });
                };
                if (seed >= 0) take(seed);
                near.forEach(function (u) { if (u !== seed && blocked[u] !== stamp) take(u); });
                return view;
            };
            const visit = function (i, j) {
                const x = minX + i * cell;
                const z = minZ + j * cell;
                const tile = tiles[Math.floor(j / TILE) * tileCols + Math.floor(i / TILE)];
                if (!tile) return 0;
                stamp += 1;
                const mark = stamp;
                const near = [];
                let seeded = false;
                let plain = false;
                for (let t = 0; t < tile.length; t += 1) {
                    const k = tile[t];
                    const span = spans[k];
                    if (x < span.minX || x > span.maxX || z < span.minZ || z > span.maxZ) continue;
                    const edge = edgeDistance2(list[k], x, z);
                    const inside = insideOutline(list[k], x, z);
                    // Deep inside k: no edge near any point of the cell, the full value in every channel with k. So
                    // are the next corners in the row, until one comes within `around` of k's edges: skip them.
                    if (inside && edge >= around2) return Math.max(0, Math.floor((Math.sqrt(edge) - around) / cell - 1e-9));
                    const d = inside ? 0 : edge;
                    if (!(d < around2)) continue;
                    if (d <= own2) seeded = true;
                    if (!clashing[k]) {
                        // A seed that clashes with nothing: the plain nearest-first view.
                        if (d <= own2) plain = true;
                        continue;
                    }
                    const u = unitOf[k];
                    if (seen[u] !== mark) {
                        seen[u] = mark;
                        distance[u] = d;
                        near.push(u);
                    } else if (d < distance[u]) {
                        distance[u] = d;
                    }
                }
                if (!seeded || near.length < 2) return 0;
                // Units that all clash with one another (a gap between rooms): a view keeps one at most.
                let together = false;
                for (let a = 0; a < near.length && !together; a += 1) {
                    for (let b = a + 1; b < near.length; b += 1) {
                        if (!clash(near[a], near[b])) {
                            together = true;
                            break;
                        }
                    }
                }
                if (!together) return 0;
                near.sort(order);
                // The same units in the same order, with the same seeds, as the last corner: the same views.
                const signature = near.map(function (u) { return distance[u] <= own2 ? -1 - u : u; });
                signature.push(plain ? -1 : 0);
                if (signature.length === last.length && signature.every(function (u, at) { return u === last[at]; })) return 0;
                last = signature;
                // The plain view is also a seed's own when the seed holds the corner (the outlines holding it
                // overlap, never clash, and come first anyway) or clashes with no unit near.
                near.forEach(function (seed) {
                    if (distance[seed] > own2) return;
                    if (distance[seed] === 0 || !unitClashes[seed].some(function (other) { return seen[other] === mark; })) {
                        plain = true;
                    } else {
                        record(greedy(near, seed));
                    }
                });
                if (plain) record(greedy(near, -1));
                return 0;
            };
            rects.sort(function (p, q) { return p.i0 - q.i0; });
            for (let j = 0; j <= rows; j += 1) {
                let next = 0;
                last = [];
                rects.forEach(function (rect) {
                    if (j < rect.j0 || j > rect.j1) return;
                    for (let i = Math.max(rect.i0, next); i <= rect.i1; i += 1) {
                        if (edges[j * row + i]) i += visit(i, j);
                    }
                    next = Math.max(next, rect.i1 + 1);
                });
            }
        }
        // Each unit alone too, then only the views no other holds.
        const sets = Array.from(views.values());
        units.forEach(function (members, u) { sets.push([u]); });
        sets.sort(function (a, b) {
            if (a.length !== b.length) return b.length - a.length;
            for (let k = 0; k < a.length; k += 1) if (a[k] !== b[k]) return a[k] - b[k];
            return 0;
        });
        const maximal = sets.filter(function (set, index) {
            return !sets.some(function (other, at) {
                return at < index && set.every(function (u) { return other.indexOf(u) >= 0; });
            });
        });
        const colours = maskColours(maximal, unitClashes, unitCount, 4);
        if (!colours) return null;
        const members = [];
        maximal.forEach(function (set, index) {
            while (members.length <= colours[index]) members.push(new Uint8Array(unitCount));
            set.forEach(function (u) { members[colours[index]][u] = 1; });
        });
        return members.map(function (member) {
            return list.filter(function (shape, k) { return !clashing[k] || member[unitOf[k]]; });
        });
    }

    // A colouring of `sets` (lists of units) in at most `limit` colours, two sets with clashing units in different
    // ones, or null: a small exact search (the set with the most colours around it first, then the most conflicts),
    // over each connected group of conflicting sets on its own, each given up past a step budget.
    function maskColours(sets, unitClashes, unitCount, limit) {
        const count = sets.length;
        const marks = new Uint8Array(unitCount);
        const conflicts = sets.map(function () { return []; });
        sets.forEach(function (set, a) {
            marks.fill(0);
            set.forEach(function (u) { unitClashes[u].forEach(function (other) { marks[other] = 1; }); });
            for (let b = a + 1; b < count; b += 1) {
                if (sets[b].some(function (u) { return marks[u]; })) {
                    conflicts[a].push(b);
                    conflicts[b].push(a);
                }
            }
        });
        const colours = new Int32Array(count).fill(-1);
        const placed = new Uint8Array(count);
        for (let first = 0; first < count; first += 1) {
            if (placed[first]) continue;
            const group = [first];
            placed[first] = 1;
            for (let at = 0; at < group.length; at += 1) {
                conflicts[group[at]].forEach(function (b) {
                    if (!placed[b]) {
                        placed[b] = 1;
                        group.push(b);
                    }
                });
            }
            group.sort(function (a, b) { return a - b; });
            let steps = 0;
            const solve = function (done, used) {
                if (done === group.length) return true;
                if ((steps += 1) > 20000) return false;
                let pick = -1;
                let pickSeen = -1;
                group.forEach(function (a) {
                    if (colours[a] >= 0) return;
                    let seenColours = 0;
                    conflicts[a].forEach(function (b) { if (colours[b] >= 0) seenColours |= 1 << colours[b]; });
                    let bits = 0;
                    for (let c = seenColours; c; c &= c - 1) bits += 1;
                    if (bits > pickSeen || (bits === pickSeen && conflicts[a].length > conflicts[pick].length)) {
                        pick = a;
                        pickSeen = bits;
                    }
                });
                let taken = 0;
                conflicts[pick].forEach(function (b) { if (colours[b] >= 0) taken |= 1 << colours[b]; });
                for (let c = 0; c < Math.min(limit, used + 1); c += 1) {
                    if (taken & (1 << c)) continue;
                    colours[pick] = c;
                    if (solve(done + 1, Math.max(used, c + 1))) return true;
                    colours[pick] = -1;
                }
                return false;
            };
            if (!solve(0, 0)) return null;
        }
        return Array.from(colours);
    }

    // Marks the texel corners within `reach` of segment pq, row by row.
    function markBand(marks, p, q, reach, minX, minZ, cell, cols, rows) {
        const length = Math.hypot(q.x - p.x, q.z - p.z);
        const ux = length > 0 ? (q.x - p.x) / length : 1;
        const uz = length > 0 ? (q.z - p.z) / length : 0;
        const j0 = Math.max(0, Math.floor((Math.min(p.z, q.z) - reach - minZ) / cell));
        const j1 = Math.min(rows, Math.ceil((Math.max(p.z, q.z) + reach - minZ) / cell));
        for (let j = j0; j <= j1; j += 1) {
            const range = capsuleRow(p.x, p.z, ux, uz, length, reach, minZ + j * cell);
            if (!range) continue;
            const i0 = Math.max(0, Math.ceil((range[0] - minX) / cell - 1e-9));
            const i1 = Math.min(cols, Math.floor((range[1] - minX) / cell + 1e-9));
            for (let i = i0; i <= i1; i += 1) marks[j * (cols + 1) + i] = 1;
        }
    }

    // The x-range [lo, hi] of the points on line z within `reach` of the segment from (px, pz) along unit (ux, uz)
    // for `length`, or null. The points within reach form a capsule, so on each line an interval.
    function capsuleRow(px, pz, ux, uz, length, reach, z) {
        let lo = Infinity;
        let hi = -Infinity;
        for (let end = 0; end < 2; end += 1) {
            const ex = px + ux * length * end;
            const dz = z - (pz + uz * length * end);
            if (Math.abs(dz) <= reach) {
                const w = Math.sqrt(reach * reach - dz * dz);
                lo = Math.min(lo, ex - w);
                hi = Math.max(hi, ex + w);
            }
        }
        // Along the segment: 0 <= (X - p).u <= length and |(X - p).n| <= reach, each linear in x.
        let a = -Infinity;
        let b = Infinity;
        const terms = [[ux, (z - pz) * uz, 0, length], [-uz, (z - pz) * ux, -reach, reach]];
        for (let k = 0; k < 2; k += 1) {
            const slope = terms[k][0];
            const offset = terms[k][1] - slope * px;
            if (Math.abs(slope) < 1e-12) {
                if (offset < terms[k][2] || offset > terms[k][3]) {
                    a = Infinity;
                    b = -Infinity;
                }
                continue;
            }
            const x1 = (terms[k][2] - offset) / slope;
            const x2 = (terms[k][3] - offset) / slope;
            a = Math.max(a, Math.min(x1, x2));
            b = Math.min(b, Math.max(x1, x2));
        }
        if (a <= b) {
            lo = Math.min(lo, a);
            hi = Math.max(hi, b);
        }
        return lo <= hi ? [lo, hi] : null;
    }

    // The grouping of aca8df1, for layouts whose views do not colour in four (maskChannels). The outlines in at most
    // four channels, as lists of outlines. Two outlines touch when they overlap or meet, and
    // clash when they do not but are nearer each other than `apart`: in one channel their edges would cut each
    // other's fill. A group grows from an outline through the outlines touching it, leaving out any that clashes with
    // one already in; groups are made until each outline and each touching pair is in one, so no shared edge is an
    // edge in all of them (two rooms a wall's width apart, joined by a hallway: {room, hallway} and {room 2,
    // hallway}). Groups that overlap or come nearer than `apart` take different channels; one that finds no free
    // channel joins the one with the fewest groups near it.
    function maskGroups(shapes, apart) {
        const count = shapes.length;
        const boxes = shapes.map(outlineBox);
        const distances = new Map();
        const between = function (i, j) {
            if (i === j) return 0;
            const key = Math.min(i, j) * count + Math.max(i, j);
            if (!distances.has(key)) {
                distances.set(key, boxGap(boxes[i], boxes[j]) >= apart ? Infinity : outlineDistance(shapes[i], shapes[j]));
            }
            return distances.get(key);
        };
        const clashing = function (i, j) {
            const distance = between(i, j);
            return distance > 1e-4 && distance < apart;
        };
        const touches = shapes.map(function (shape, i) {
            const list = [];
            for (let j = 0; j < count; j += 1) if (j !== i && between(i, j) <= 1e-4) list.push(j);
            return list;
        });
        const groups = [];
        const grow = function (seed) {
            const members = seed.slice();
            const queue = seed.slice();
            while (queue.length) {
                touches[queue.shift()].forEach(function (next) {
                    if (members.indexOf(next) >= 0) return;
                    if (members.some(function (member) { return clashing(member, next); })) return;
                    members.push(next);
                    queue.push(next);
                });
            }
            groups.push(members.sort(function (a, b) { return a - b; }));
        };
        const grouped = function (list) {
            return groups.some(function (group) {
                return list.every(function (index) { return group.indexOf(index) >= 0; });
            });
        };
        for (let i = 0; i < count; i += 1) if (!grouped([i])) grow([i]);
        touches.forEach(function (list, i) {
            list.forEach(function (j) { if (j > i && !grouped([i, j])) grow([i, j]); });
        });
        const kept = groups.filter(function (group, index) {
            return !groups.some(function (other, at) {
                return at !== index && group.every(function (member) { return other.indexOf(member) >= 0; })
                    && (other.length > group.length || at < index);
            });
        });
        const near = function (a, b) {
            return a.some(function (i) { return b.some(function (j) { return between(i, j) < apart; }); });
        };
        const channels = [];
        kept.forEach(function (group, index) {
            const crowd = channels.map(function (members) {
                return members.filter(function (other) { return near(kept[other], group); }).length;
            });
            let choice = crowd.indexOf(0);
            if (choice < 0 && channels.length < 4) {
                channels.push([]);
                choice = channels.length - 1;
            }
            if (choice < 0) choice = crowd.indexOf(Math.min.apply(null, crowd));
            channels[choice].push(index);
        });
        return channels.map(function (members) {
            const indices = [];
            members.forEach(function (group) {
                kept[group].forEach(function (index) { if (indices.indexOf(index) < 0) indices.push(index); });
            });
            return indices.map(function (index) { return shapes[index]; });
        });
    }

    // The outlines not inside another (of two the same, the first), in their order.
    function uncoveredOutlines(shapes) {
        const boxes = shapes.map(outlineBox);
        const areas = shapes.map(outlineArea);
        const kept = [];
        shapes.map(function (shape, k) { return k; }).sort(function (a, b) { return areas[b] - areas[a] || a - b; })
            .forEach(function (k) {
                if (!kept.some(function (c) { return outlineInside(shapes[k], boxes[k], shapes[c], boxes[c]); })) kept.push(k);
            });
        return kept.sort(function (a, b) { return a - b; }).map(function (k) { return shapes[k]; });
    }

    // Whether outline `inner` lies inside outline `outer` (its edges may run along outer's). Each edge of either is cut
    // where it meets the other outline (crossing it, touching it at a corner or running along it); every piece of
    // inner's edges must be inside or on outer, and no piece of outer's edges strictly inside inner. A notch of outer
    // that only touches inner's edges (its tip on one, its mouth on another) leaves part of inner uncovered: kept.
    function outlineInside(inner, innerBox, outer, outerBox) {
        const slack = 1e-9;
        if (innerBox.minX < outerBox.minX - slack || innerBox.maxX > outerBox.maxX + slack
            || innerBox.minZ < outerBox.minZ - slack || innerBox.maxZ > outerBox.maxZ + slack) return false;
        const on = function (points, x, z) { return edgeDistance2(points, x, z) <= 1e-12; };
        const pieces = function (points, other, keep) {
            for (let k = 0; k < points.length; k += 1) {
                const p = points[k];
                const q = points[(k + 1) % points.length];
                const cuts = edgeCuts(p, q, other).concat([0, 1]).sort(function (a, b) { return a - b; });
                for (let c = 0; c + 1 < cuts.length; c += 1) {
                    if (!(cuts[c + 1] - cuts[c] > 1e-9)) continue;
                    const t = (cuts[c] + cuts[c + 1]) / 2;
                    if (!keep(p.x + (q.x - p.x) * t, p.z + (q.z - p.z) * t)) return false;
                }
            }
            return true;
        };
        return pieces(inner, outer, function (x, z) { return insideOutline(outer, x, z) || on(outer, x, z); })
            && pieces(outer, inner, function (x, z) { return !insideOutline(inner, x, z) || on(inner, x, z); });
    }

    // Where segment pq meets outline `other`, as fractions of pq: its edges' crossings and the corners on pq.
    function edgeCuts(p, q, other) {
        const cuts = [];
        const dx = q.x - p.x;
        const dz = q.z - p.z;
        const length2 = dx * dx + dz * dz;
        if (!(length2 > 0)) return cuts;
        for (let k = 0; k < other.length; k += 1) {
            const r = other[k];
            const t = other[(k + 1) % other.length];
            // A corner of other on pq.
            const along = ((r.x - p.x) * dx + (r.z - p.z) * dz) / length2;
            const ox = r.x - p.x - dx * along;
            const oz = r.z - p.z - dz * along;
            if (along > 0 && along < 1 && ox * ox + oz * oz <= 1e-12) cuts.push(along);
            // Its edge rt crossing pq.
            const ex = t.x - r.x;
            const ez = t.z - r.z;
            const denominator = dx * ez - dz * ex;
            if (Math.abs(denominator) < 1e-15) continue;
            const s = ((r.x - p.x) * ez - (r.z - p.z) * ex) / denominator;
            const u = ((r.x - p.x) * dz - (r.z - p.z) * dx) / denominator;
            if (s > 0 && s < 1 && u >= 0 && u <= 1) cuts.push(s);
        }
        return cuts;
    }

    function outlineArea(points) {
        let twice = 0;
        for (let k = 0, m = points.length - 1; k < points.length; m = k, k += 1) {
            twice += points[m].x * points[k].z - points[k].x * points[m].z;
        }
        return Math.abs(twice) / 2;
    }

    // The squared plan distance from point (x, z) to an outline's edges (inside or out).
    function edgeDistance2(points, x, z) {
        let best = Infinity;
        for (let k = 0, m = points.length - 1; k < points.length; m = k, k += 1) {
            const ax = points[m].x;
            const az = points[m].z;
            const dx = points[k].x - ax;
            const dz = points[k].z - az;
            const length = dx * dx + dz * dz;
            const t = length > 0 ? Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / length)) : 0;
            const ex = x - ax - dx * t;
            const ez = z - az - dz * t;
            if (ex * ex + ez * ez < best) best = ex * ex + ez * ez;
        }
        return best;
    }

    function outlineBox(points) {
        const box = { minX: Infinity, minZ: Infinity, maxX: -Infinity, maxZ: -Infinity };
        points.forEach(function (point) {
            box.minX = Math.min(box.minX, point.x);
            box.minZ = Math.min(box.minZ, point.z);
            box.maxX = Math.max(box.maxX, point.x);
            box.maxZ = Math.max(box.maxZ, point.z);
        });
        return box;
    }

    function boxGap(a, b) {
        return Math.hypot(Math.max(0, a.minX - b.maxX, b.minX - a.maxX), Math.max(0, a.minZ - b.maxZ, b.minZ - a.maxZ));
    }

    // The plan distance between two outlines: 0 when they overlap or touch.
    function outlineDistance(a, b) {
        if (insideOutline(b, a[0].x, a[0].z) || insideOutline(a, b[0].x, b[0].z)) return 0;
        let best = Infinity;
        a.forEach(function (p, i) {
            const q = a[(i + 1) % a.length];
            b.forEach(function (r, j) {
                best = Math.min(best, segmentDistance(p, q, r, b[(j + 1) % b.length]));
            });
        });
        return best;
    }

    function segmentDistance(p, q, r, t) {
        if (segmentsCross(p, q, r, t)) return 0;
        return Math.min(pointSegment(p, r, t), pointSegment(q, r, t), pointSegment(r, p, q), pointSegment(t, p, q));
    }

    // Whether segments pq and rt cross at a point inside both.
    function segmentsCross(p, q, r, t) {
        const cross = function (o, u, v) { return (u.x - o.x) * (v.z - o.z) - (u.z - o.z) * (v.x - o.x); };
        const d1 = cross(r, t, p);
        const d2 = cross(r, t, q);
        const d3 = cross(p, q, r);
        const d4 = cross(p, q, t);
        return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
    }

    function pointSegment(v, a, b) {
        const dx = b.x - a.x;
        const dz = b.z - a.z;
        const length = dx * dx + dz * dz;
        const t = length > 0 ? Math.max(0, Math.min(1, ((v.x - a.x) * dx + (v.z - a.z) * dz) / length)) : 0;
        return Math.hypot(v.x - a.x - dx * t, v.z - a.z - dz * t);
    }

    // One mask channel: the signed, clamped distance to the edge of these outlines' union (see fillMask).
    // An edge piece is part of that edge when points to each side of its middle differ (inside one outline or none).
    // - Coloured layouts (b4348cc): edges are cut where another edge crosses them or another outline's corner is
    //   nearer than FILL_CORNER_CUT, and the points are FILL_EDGE_PROBE to each side.
    // - The fallback grouping (2026-11-03), where outlines 0.1-1 mm apart share a channel: edges are also cut at other
    //   outlines' corners within twice FILL_EDGE_PROBE, so an outline running beside part of a piece does not decide
    //   for all of it. And the points are no farther than half the distance to an edge running alongside the piece
    //   (within FILL_ALONGSIDE) but not parallel to it, so they cannot jump a slanted gap between the two. Parallel
    //   outlines under 1 mm apart, and edges crossing such a gap, are still one surface.
    function maskField(shapes, minX, minZ, cell, cols, rows, fallback) {
        const inside = new Uint8Array(cols * rows);
        shapes.forEach(function (points) {
            for (let j = 0; j < rows; j += 1) {
                const z = minZ + (j + 0.5) * cell;
                const crossings = [];
                for (let a = 0, b = points.length - 1; a < points.length; b = a, a += 1) {
                    const p = points[a];
                    const q = points[b];
                    if ((p.z > z) !== (q.z > z)) crossings.push(p.x + (z - p.z) * (q.x - p.x) / (q.z - p.z));
                }
                crossings.sort(function (u, v) { return u - v; });
                for (let k = 0; k + 1 < crossings.length; k += 2) {
                    const i0 = Math.max(0, Math.ceil((crossings[k] - minX) / cell - 0.5));
                    const i1 = Math.min(cols - 1, Math.ceil((crossings[k + 1] - minX) / cell - 0.5) - 1);
                    for (let i = i0; i <= i1; i += 1) inside[j * cols + i] = 1;
                }
            }
        });
        const reach = FILL_EDGE_TEXELS * cell;
        const diagonal = Math.SQRT2 * cell * (1 + 1e-6);
        const near = new Float32Array(cols * rows).fill(reach);
        const lines = new Float32Array(cols * rows).fill(Infinity);
        const insideAny = function (x, z) {
            return shapes.some(function (points) { return insideOutline(points, x, z); });
        };
        // In the fallback, every edge with its bounds, for the probe's bound (probeAt).
        const edges = [];
        if (fallback) {
            shapes.forEach(function (points) {
                points.forEach(function (a, index) {
                    const b = points[(index + 1) % points.length];
                    const length = Math.hypot(b.x - a.x, b.z - a.z);
                    if (!(length > 1e-9)) return;
                    edges.push({ a: a, b: b, length: length, ux: (b.x - a.x) / length, uz: (b.z - a.z) / length,
                        minX: Math.min(a.x, b.x) - FILL_EDGE_PROBE * 2, maxX: Math.max(a.x, b.x) + FILL_EDGE_PROBE * 2,
                        minZ: Math.min(a.z, b.z) - FILL_EDGE_PROBE * 2, maxZ: Math.max(a.z, b.z) + FILL_EDGE_PROBE * 2 });
                });
            });
        }
        const probeAt = function (mx, mz, ux, uz) {
            let probe = FILL_EDGE_PROBE;
            edges.forEach(function (edge) {
                if (mx < edge.minX || mx > edge.maxX || mz < edge.minZ || mz > edge.maxZ) return;
                // Only an edge running alongside, not parallel (nor the piece's own edge), and beside the middle:
                // its nearest point inside the edge, not a corner (the piece is cut there).
                const sine = Math.abs(ux * edge.uz - uz * edge.ux);
                if (sine < 1e-9 || sine > FILL_ALONGSIDE) return;
                const along = (mx - edge.a.x) * edge.ux + (mz - edge.a.z) * edge.uz;
                if (along <= 0 || along >= edge.length) return;
                probe = Math.min(probe, Math.abs((mx - edge.a.x) * edge.uz - (mz - edge.a.z) * edge.ux) / 2);
            });
            return Math.max(probe, 1e-6);
        };
        const cornerCut = fallback ? 2 * FILL_EDGE_PROBE : FILL_CORNER_CUT;
        shapes.forEach(function (points, shape) {
            points.forEach(function (p, index) {
                const q = points[(index + 1) % points.length];
                const length = Math.hypot(q.x - p.x, q.z - p.z);
                if (!(length > 1e-9)) return;
                const ux = (q.x - p.x) / length;
                const uz = (q.z - p.z) / length;
                // Cut where another edge crosses this one or another outline's corner is near it (cornerCut).
                const cuts = [0, length];
                shapes.forEach(function (others, other) {
                    others.forEach(function (r, k) {
                        const t = others[(k + 1) % others.length];
                        const off = Math.abs(ux * (r.z - p.z) - uz * (r.x - p.x));
                        if (other !== shape && (fallback ? off <= cornerCut : off < cornerCut)) {
                            cuts.push((r.x - p.x) * ux + (r.z - p.z) * uz);
                        }
                        const ex = t.x - r.x;
                        const ez = t.z - r.z;
                        const denominator = ux * ez - uz * ex;
                        if (Math.abs(denominator) < 1e-12) return;
                        const along = ((r.x - p.x) * ez - (r.z - p.z) * ex) / denominator;
                        const across = ((r.x - p.x) * uz - (r.z - p.z) * ux) / denominator;
                        if (across > 0 && across < 1) cuts.push(along);
                    });
                });
                const sorted = cuts.filter(function (t) { return t >= 0 && t <= length; })
                    .sort(function (u, v) { return u - v; });
                for (let k = 0; k + 1 < sorted.length; k += 1) {
                    const from = sorted[k];
                    const to = sorted[k + 1];
                    if (!(to - from > 1e-6)) continue;
                    const middle = (from + to) / 2;
                    const mx = p.x + ux * middle;
                    const mz = p.z + uz * middle;
                    const probe = fallback ? probeAt(mx, mz, ux, uz) : FILL_EDGE_PROBE;
                    const left = insideAny(mx - uz * probe, mz + ux * probe);
                    if (left === insideAny(mx + uz * probe, mz - ux * probe)) continue;
                    // The normal into the footprint.
                    const nx = left ? -uz : uz;
                    const nz = left ? ux : -ux;
                    const ax = p.x + ux * from;
                    const az = p.z + uz * from;
                    const span = to - from;
                    const i0 = Math.max(0, Math.floor((Math.min(ax, p.x + ux * to) - reach - minX) / cell));
                    const i1 = Math.min(cols - 1, Math.floor((Math.max(ax, p.x + ux * to) + reach - minX) / cell));
                    const j0 = Math.max(0, Math.floor((Math.min(az, p.z + uz * to) - reach - minZ) / cell));
                    const j1 = Math.min(rows - 1, Math.floor((Math.max(az, p.z + uz * to) + reach - minZ) / cell));
                    // Only texels within `reach` of the piece change: on each row, its band.
                    for (let j = j0; j <= j1; j += 1) {
                        const cz = minZ + (j + 0.5) * cell - az;
                        const range = capsuleRow(ax, az, ux, uz, span, reach * (1 + 1e-6), cz + az);
                        if (!range) continue;
                        const r0 = Math.max(i0, Math.floor((range[0] - minX) / cell - 0.5));
                        const r1 = Math.min(i1, Math.ceil((range[1] - minX) / cell - 0.5));
                        for (let i = r0; i <= r1; i += 1) {
                            const cx = minX + (i + 0.5) * cell - ax;
                            const t = Math.max(0, Math.min(span, cx * ux + cz * uz));
                            const distance = Math.hypot(cx - ux * t, cz - uz * t);
                            const at = j * cols + i;
                            if (distance < near[at]) near[at] = distance;
                            if (distance <= diagonal) lines[at] = Math.min(lines[at], cx * nx + cz * nz);
                        }
                    }
                }
            });
        });
        const data = new Float32Array(cols * rows);
        for (let j = 0; j < rows; j += 1) {
            for (let i = 0; i < cols; i += 1) {
                const k = j * cols + i;
                const border = i === 0 || j === 0 || i === cols - 1 || j === rows - 1;
                const signed = Math.min(inside[k] ? near[k] : -near[k], lines[k]) - FILL_MASK_INSET;
                data[k] = border ? Math.min(signed, -FILL_MASK_INSET) : signed;
            }
        }
        return data;
    }

    // A fill mask's value at plan point (x, z) as the shader reads it: the largest of its channels, each filtered.
    function sampleMask(mask, x, z) {
        let best = -Infinity;
        for (let channel = 0; channel < (mask.channels || 1); channel += 1) {
            best = Math.max(best, sampleLinear(mask, x, z, mask.channels || 1, channel));
        }
        return best;
    }

    // A map's value at plan point (x, z) as the GPU's linear filtering reads it (texel centres, clamped at the
    // border): for the fill mask, positive inside the footprint.
    function sampleLinear(field, x, z, channels, channel) {
        const step = channels || 1;
        const u = (x - field.minX) / field.cell - 0.5;
        const v = (z - field.minZ) / field.cell - 0.5;
        const i = Math.floor(u);
        const j = Math.floor(v);
        const fu = u - i;
        const fv = v - j;
        const at = function (column, row) {
            const a = Math.min(field.cols - 1, Math.max(0, column));
            const b = Math.min(field.rows - 1, Math.max(0, row));
            return field.data[(b * field.cols + a) * step + (channel || 0)];
        };
        return (at(i, j) * (1 - fu) + at(i + 1, j) * fu) * (1 - fv) + (at(i, j + 1) * (1 - fu) + at(i + 1, j + 1) * fu) * fv;
    }

    // Whether plan point (x, z) is inside the outline (an array of {x, z}, even-odd).
    function insideOutline(outline, x, z) {
        let hit = false;
        const points = Array.isArray(outline) ? outline : [];
        for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
            const a = points[i];
            const b = points[j];
            if ((a.z > z) !== (b.z > z) && x < (b.x - a.x) * (z - a.z) / (b.z - a.z) + a.x) hit = !hit;
        }
        return hit;
    }

    // A lit material's fragment shader with the fill added to its indirect light (before lights_fragment_end, where
    // three adds the ambient light): the point's world position from the view position, mapped onto the fill map by
    // facilityFillMatrix (x and z to 0..1, y kept), and lit only below the map's lamps. False when the shader has no
    // lights (an unlit material).
    const FILL_UNIFORMS = 'uniform sampler2D facilityFillMap;\nuniform sampler2D facilityFillMask;\n'
        + 'uniform vec4 facilityFillChannels;\nuniform mat4 facilityFillMatrix;\n'
        + 'uniform float facilityFillStrength;\n';
    const FILL_FRAGMENT = [
        'if ( facilityFillStrength > 0.0 ) {',
        '    vec3 facilityWorld = transpose( mat3( viewMatrix ) ) * ( - vViewPosition - viewMatrix[ 3 ].xyz );',
        '    vec4 facilityAt = facilityFillMatrix * vec4( facilityWorld, 1.0 );',
        '    if ( facilityAt.x >= 0.0 && facilityAt.x <= 1.0 && facilityAt.z >= 0.0 && facilityAt.z <= 1.0 ) {',
        '        vec4 facilityFill = texture2D( facilityFillMap, facilityAt.xz );',
        // Unused channels of the mask read -1.
        '        vec4 facilityMask = mix( vec4( - 1.0 ), texture2D( facilityFillMask, facilityAt.xz ), facilityFillChannels );',
        '        float facilityCeiling = max( max( facilityMask.r, facilityMask.g ), max( facilityMask.b, facilityMask.a ) );',
        '        if ( facilityAt.y < facilityFill.a && facilityCeiling > 0.0 ) {',
        '            irradiance += facilityFill.rgb * facilityFillStrength;',
        '        }',
        '    }',
        '}',
    ].join('\n');

    function patchFillShader(shader) {
        const marker = '#include <lights_fragment_end>';
        // Every lit shader includes lights_fragment_begin before it, which reads vViewPosition.
        if (!shader || typeof shader.fragmentShader !== 'string' || shader.fragmentShader.indexOf(marker) < 0) return false;
        shader.fragmentShader = FILL_UNIFORMS + shader.fragmentShader.replace(marker, FILL_FRAGMENT + '\n' + marker);
        return true;
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
        LOW_MIN_HEIGHT: LOW_MIN_HEIGHT,
        BEAM_REACH: BEAM_REACH,
        SPOT_COUNT: SPOT_COUNT,
        SPOT_MIN_HEIGHT: SPOT_MIN_HEIGHT,
        SPOT_REACH: SPOT_REACH,
        LUX_TO_SCENE: LUX_TO_SCENE,
        FILL_SPREAD: FILL_SPREAD,
        FILL_PEAK: FILL_PEAK,
        FILL_LIMIT: FILL_LIMIT,
        FILL_BELOW: FILL_BELOW,
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
        bulbsOf: bulbsOf,
        spotsOf: spotsOf,
        spotSettings: spotSettings,
        fillField: fillField,
        fillMask: fillMask,
        sampleMask: sampleMask,
        sampleLinear: sampleLinear,
        FILL_EDGE_TEXELS: FILL_EDGE_TEXELS,
        FILL_MASK_SUBDIVIDE: FILL_MASK_SUBDIVIDE,
        FILL_MASK_INSET: FILL_MASK_INSET,
        insideOutline: insideOutline,
        patchFillShader: patchFillShader,
    };
}));
