/**
 * Smart Dimension for the Assembly view (docs/assembly-smart-dimension-plan.md).
 *
 * - The CAD edges of a part, worked out from its faces: an edge is where one face's triangles meet another's (or
 *   meet nothing), cut at the vertices where three faces meet. Each is a line, circle, arc or curve; a circle must
 *   match an adjacent cylinder's radius and sit square to its axis, or fit five or more points cleanly.
 * - The exact plane, cylinder axis or sphere of a face.
 * - What one or two picked entities measure, with SOLIDWORKS' Smart Dimension defaults.
 * - Where a dimension's lines, arrows and text go for a text point, and its value as SOLIDWORKS writes it.
 *
 * No three.js: plain [x, y, z] arrays, so the view, the tests and the Python twin
 * (ai_inspector/assembly_knowledge/assembly_dimensions.py) give the same numbers.
 */
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProSmartDimension = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    // Parallel (or square) within 0.05 degrees.
    const PARALLEL_SIN = Math.sin(0.05 * Math.PI / 180);
    // A CAD edge is smooth: a turn sharper than this inside one chain is a vertex the faces did not show.
    const CORNER_COS = Math.cos(75 * Math.PI / 180);
    // A smooth patch is flat when every normal is within half a degree of the mean.
    const FLAT_COS = Math.cos(0.5 * Math.PI / 180);
    // At most this many triangles of a face are kept for minimum distances.
    const SAMPLE_TRIANGLES = 4000;
    const INCH = 0.0254;
    const DIAMETER = 'Ø';
    const DEGREE = '°';

    // ---- Vectors ----
    function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
    function add(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
    function scale(a, s) { return [a[0] * s, a[1] * s, a[2] * s]; }
    function addScaled(a, b, s) { return [a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s]; }
    function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
    function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
    function length(a) { return Math.sqrt(dot(a, a)); }
    function distance(a, b) { return length(sub(a, b)); }
    function unit(a) {
        const l = length(a);
        return l > 1e-300 ? scale(a, 1 / l) : [0, 0, 0];
    }
    function clamp(value, low, high) { return Math.min(high, Math.max(low, value)); }
    // a less its part along the unit vector axis.
    function reject(a, axis) { return addScaled(a, axis, -dot(a, axis)); }
    // Any unit vector square to a.
    function perpendicularTo(a) { return unit(cross(a, Math.abs(a[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0])); }
    function footOnLine(p, origin, direction) { return addScaled(origin, direction, dot(sub(p, origin), direction)); }
    function footOnPlane(p, origin, normal) { return addScaled(p, normal, -dot(sub(p, origin), normal)); }

    function eigenvectors(m) {
        // A symmetric 3x3 [a00, a01, a02, a11, a12, a22] by Jacobi rotations: { values, vectors } (vectors[i] goes
        // with values[i]).
        const a = [[m[0], m[1], m[2]], [m[1], m[3], m[4]], [m[2], m[4], m[5]]];
        const v = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
        for (let sweep = 0; sweep < 60; sweep += 1) {
            const off = Math.abs(a[0][1]) + Math.abs(a[0][2]) + Math.abs(a[1][2]);
            const size = Math.abs(a[0][0]) + Math.abs(a[1][1]) + Math.abs(a[2][2]);
            if (off <= 1e-15 * size || off < 1e-300) break;
            [[0, 1], [0, 2], [1, 2]].forEach(([p, q]) => {
                if (Math.abs(a[p][q]) < 1e-300) return;
                const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
                const t = (theta >= 0 ? 1 : -1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
                const c = 1 / Math.sqrt(t * t + 1);
                const s = t * c;
                for (let k = 0; k < 3; k += 1) {
                    const kp = a[k][p];
                    const kq = a[k][q];
                    a[k][p] = c * kp - s * kq;
                    a[k][q] = s * kp + c * kq;
                }
                for (let k = 0; k < 3; k += 1) {
                    const pk = a[p][k];
                    const qk = a[q][k];
                    a[p][k] = c * pk - s * qk;
                    a[q][k] = s * pk + c * qk;
                }
                for (let k = 0; k < 3; k += 1) {
                    const kp = v[k][p];
                    const kq = v[k][q];
                    v[k][p] = c * kp - s * kq;
                    v[k][q] = s * kp + c * kq;
                }
            });
        }
        return { values: [a[0][0], a[1][1], a[2][2]], vectors: [0, 1, 2].map(i => unit([v[0][i], v[1][i], v[2][i]])) };
    }

    function smallestDirection(m) {
        const { values, vectors } = eigenvectors(m);
        let best = 0;
        for (let i = 1; i < 3; i += 1) if (values[i] < values[best]) best = i;
        return vectors[best];
    }

    function fitCircle(points) {
        // The plane and circle of a chain of points: { center, normal, radius, deviation } (the worst distance of a
        // point from that circle, in or out of its plane), or null.
        const n = points.length;
        if (n < 3) return null;
        let c0 = [0, 0, 0];
        points.forEach(p => { c0 = add(c0, p); });
        c0 = scale(c0, 1 / n);
        const m = [0, 0, 0, 0, 0, 0];
        points.forEach(p => {
            const d = sub(p, c0);
            m[0] += d[0] * d[0]; m[1] += d[0] * d[1]; m[2] += d[0] * d[2];
            m[3] += d[1] * d[1]; m[4] += d[1] * d[2]; m[5] += d[2] * d[2];
        });
        const normal = smallestDirection(m);
        const e1 = perpendicularTo(normal);
        const e2 = cross(normal, e1);
        // Least squares for x^2 + y^2 = 2 a x + 2 b y + k in the plane.
        const s = [0, 0, 0, 0, 0, 0];
        const r = [0, 0, 0];
        const flat = points.map(p => {
            const d = sub(p, c0);
            const x = dot(d, e1);
            const y = dot(d, e2);
            const w = x * x + y * y;
            s[0] += 4 * x * x; s[1] += 4 * x * y; s[2] += 2 * x; s[3] += 4 * y * y; s[4] += 2 * y; s[5] += 1;
            r[0] += 2 * x * w; r[1] += 2 * y * w; r[2] += w;
            return [x, y, dot(d, normal)];
        });
        const det3 = (a, b, c, d, e, f, g, h, i) => a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
        const det = det3(s[0], s[1], s[2], s[1], s[3], s[4], s[2], s[4], s[5]);
        if (!(Math.abs(det) > 1e-300)) return null;
        const a = det3(r[0], s[1], s[2], r[1], s[3], s[4], r[2], s[4], s[5]) / det;
        const b = det3(s[0], r[0], s[2], s[1], r[1], s[4], s[2], r[2], s[5]) / det;
        const k = det3(s[0], s[1], r[0], s[1], s[3], r[1], s[2], s[4], r[2]) / det;
        const radius = Math.sqrt(Math.max(k + a * a + b * b, 0));
        let deviation = 0;
        flat.forEach(([x, y, z]) => {
            deviation = Math.max(deviation, Math.abs(Math.hypot(x - a, y - b) - radius), Math.abs(z));
        });
        return { center: addScaled(addScaled(c0, e1, a), e2, b), normal, radius, deviation };
    }

    // ---- Faces: the exact surface each one lies on ----

    function faceGeometry(source, k) {
        // { kind: plane | cylinder | sphere | other, area, centroid, triangles (a sample, nine numbers each) } with
        // point + normal (plane), point + axis + radius (cylinder) or center + radius (sphere), in the
        // geometry's own coordinates.
        const info = (source.faces && source.faces[k]) || {};
        const position = source.position;
        const normal = source.normal;
        const members = source.members(k);
        const every = Math.max(1, Math.ceil(members.length / SAMPLE_TRIANGLES));
        const sample = [];
        const vertices = [];
        let area = 0;
        let centroid = [0, 0, 0];
        let direction = [0, 0, 0];
        const corner = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
        const triangleNormals = [];
        for (let at = 0; at < members.length; at += 1) {
            const u = members[at];
            for (let c = 0; c < 3; c += 1) {
                const index = source.vertex(u, c);
                corner[c] = [position[3 * index], position[3 * index + 1], position[3 * index + 2]];
                vertices.push(index);
            }
            const n = cross(sub(corner[1], corner[0]), sub(corner[2], corner[0]));
            const piece = length(n) / 2;
            area += piece;
            centroid = addScaled(centroid, add(add(corner[0], corner[1]), corner[2]), piece / 3);
            triangleNormals.push(n);
            if (at % every === 0) sample.push(...corner[0], ...corner[1], ...corner[2]);
        }
        if (area > 0) centroid = scale(centroid, 1 / area);
        const vertexNormal = index => (normal
            ? unit([normal[3 * index], normal[3 * index + 1], normal[3 * index + 2]]) : null);
        if (normal) vertices.forEach(index => { direction = add(direction, vertexNormal(index)); });
        else triangleNormals.forEach(n => { direction = add(direction, n); });
        const result = { kind: 'other', area, centroid, triangles: Float64Array.from(sample),
            approximate: !source.exact };
        const mean = unit(direction);
        const flat = () => {
            if (length(mean) < 0.5) return false;
            if (normal) return vertices.every(index => Math.abs(dot(vertexNormal(index), mean)) >= FLAT_COS);
            return triangleNormals.every(n => length(n) < 1e-30 || Math.abs(dot(unit(n), mean)) >= FLAT_COS);
        };
        if (info.kind === 'plane' || (!source.exact && flat())) {
            return Object.assign(result, { kind: 'plane', point: centroid, normal: mean });
        }
        const radius = Number(info.radius) || 0;
        if (normal && radius > 0 && (info.kind === 'cylinder' || info.kind === 'sphere')) {
            const seen = new Set();
            const rows = [];
            vertices.forEach(index => {
                if (seen.has(index)) return;
                seen.add(index);
                rows.push([[position[3 * index], position[3 * index + 1], position[3 * index + 2]], vertexNormal(index)]);
            });
            let axis = null;
            if (info.kind === 'cylinder') {
                const m = [0, 0, 0, 0, 0, 0];
                rows.forEach(([, n]) => {
                    m[0] += n[0] * n[0]; m[1] += n[0] * n[1]; m[2] += n[0] * n[2];
                    m[3] += n[1] * n[1]; m[4] += n[1] * n[2]; m[5] += n[2] * n[2];
                });
                axis = smallestDirection(m);
            }
            // The centre (or axis) is a radius from each point against its normal: outward on a boss, inward in a
            // hole. The side that brings the centres together is the right one.
            const centres = sign => rows.map(([p, n]) => addScaled(p, n, -sign * radius));
            const spread = list => {
                let mid = [0, 0, 0];
                list.forEach(p => { mid = add(mid, p); });
                mid = scale(mid, 1 / list.length);
                let worst = 0;
                list.forEach(p => {
                    const d = sub(p, mid);
                    worst = Math.max(worst, length(axis ? reject(d, axis) : d));
                });
                return { mid, worst };
            };
            const out = spread(centres(1));
            const inward = spread(centres(-1));
            const best = inward.worst < out.worst ? inward : out;
            if (rows.length && best.worst <= Math.max(radius * 0.02, 2e-5)) {
                return axis
                    ? Object.assign(result, { kind: 'cylinder', point: best.mid, axis, radius })
                    : Object.assign(result, { kind: 'sphere', center: best.mid, radius });
            }
        }
        return result;
    }

    // ---- Edges ----

    function classifyChain(points, faces, geometryOf, size, kindOf) {
        const n = points.length;
        const closed = n > 3 && distance(points[0], points[n - 1]) <= 1e-12;
        let total = 0;
        for (let i = 1; i < n; i += 1) total += distance(points[i - 1], points[i]);
        const tolerance = Math.max(size * 1e-5, 3e-6);
        if (!closed) {
            const span = distance(points[0], points[n - 1]);
            if (span > 0) {
                const along = unit(sub(points[n - 1], points[0]));
                let worst = 0;
                points.forEach(p => { worst = Math.max(worst, length(reject(sub(p, points[0]), along))); });
                if (worst <= tolerance) return { kind: 'line', start: points[0], end: points[n - 1], length: span };
            }
        }
        const circle = (center, normal, radius) => (closed
            ? { kind: 'circle', center, normal, radius, length: total }
            : { kind: 'arc', center, normal, radius, length: total, start: points[0], end: points[n - 1] });
        // On an adjacent cylinder: every point a radius from its axis, all at one place along it.
        for (const face of faces) {
            const g = face >= 0 ? geometryOf(face) : null;
            if (!g || g.kind !== 'cylinder') continue;
            const allowed = Math.max(g.radius * 2e-3, 5e-6);
            let first = null;
            let sum = 0;
            const fits = points.every(p => {
                const d = sub(p, g.point);
                const along = dot(d, g.axis);
                if (first === null) first = along;
                sum += along;
                return Math.abs(length(reject(d, g.axis)) - g.radius) <= allowed && Math.abs(along - first) <= allowed;
            });
            if (fits) return circle(addScaled(g.point, g.axis, sum / n), g.axis, g.radius);
        }
        // A clean fit over five or more points (four beside a torus, cone or sphere, which meet planes and
        // cylinders in circles), turning at least 10 degrees in all.
        const round = faces.some(face => face >= 0 && ['torus', 'cone', 'sphere'].includes(kindOf(face)));
        if (n >= (closed ? 6 : round ? 4 : 5)) {
            const fit = fitCircle(closed ? points.slice(0, -1) : points);
            if (fit && fit.radius > 0 && fit.deviation <= Math.max(fit.radius * 1e-4, 3e-6)
                    && total / fit.radius >= 10 * Math.PI / 180) {
                return circle(fit.center, fit.normal, fit.radius);
            }
        }
        return { kind: 'curve', length: total };
    }

    function buildEdges(source) {
        // source: { position (x, y, z per vertex), normal?, triangles, vertex(u, corner), faceOf (face of each
        // triangle u), faces ([{kind, radius}]), members(k) (face k's triangles), count, exact }.
        // Gives { size, points, edges, vertices, faceEdges(face), face(k) }.
        const position = source.position;
        const total = Math.floor(position.length / 3);
        let lo = [Infinity, Infinity, Infinity];
        let hi = [-Infinity, -Infinity, -Infinity];
        for (let i = 0; i < total; i += 1) {
            const p = [position[3 * i], position[3 * i + 1], position[3 * i + 2]];
            lo = [Math.min(lo[0], p[0]), Math.min(lo[1], p[1]), Math.min(lo[2], p[2])];
            hi = [Math.max(hi[0], p[0]), Math.max(hi[1], p[1]), Math.max(hi[2], p[2])];
        }
        const size = total ? Math.max(distance(lo, hi), 1e-9) : 1e-9;
        // Vertices welded by position: the exporter gives each triangle its own three.
        const quantum = Math.max(size * 1e-7, 1e-12);
        const welded = new Int32Array(total);
        const keys = new Map();
        const coordinates = [];
        for (let i = 0; i < total; i += 1) {
            const x = position[3 * i];
            const y = position[3 * i + 1];
            const z = position[3 * i + 2];
            const key = `${Math.round(x / quantum)},${Math.round(y / quantum)},${Math.round(z / quantum)}`;
            let id = keys.get(key);
            if (id === undefined) {
                id = coordinates.length / 3;
                keys.set(key, id);
                coordinates.push(x, y, z);
            }
            welded[i] = id;
        }
        const point = id => [coordinates[3 * id], coordinates[3 * id + 1], coordinates[3 * id + 2]];
        const span = coordinates.length / 3;
        // Triangle sides: which faces have them.
        const sides = new Map();
        const sideA = [];
        const sideB = [];
        const faceA = [];
        const faceB = [];
        const uses = [];
        for (let u = 0; u < source.triangles; u += 1) {
            const f = source.faceOf[u];
            for (let c = 0; c < 3; c += 1) {
                const p = welded[source.vertex(u, c)];
                const q = welded[source.vertex(u, (c + 1) % 3)];
                if (p === q) continue;
                const key = Math.min(p, q) * span + Math.max(p, q);
                const at = sides.get(key);
                if (at === undefined) {
                    sides.set(key, sideA.length);
                    sideA.push(Math.min(p, q));
                    sideB.push(Math.max(p, q));
                    faceA.push(f);
                    faceB.push(-1);
                    uses.push(1);
                } else {
                    uses[at] += 1;
                    if (faceB[at] < 0 && f !== faceA[at]) faceB[at] = f;
                }
            }
        }
        // The sides between two faces, or one face and nothing, grouped by that pair.
        const groups = new Map();
        const meeting = new Map();
        const touch = (id, face) => {
            let set = meeting.get(id);
            if (!set) meeting.set(id, set = new Set());
            set.add(face);
        };
        for (let s = 0; s < sideA.length; s += 1) {
            let pair;
            if (faceB[s] >= 0) pair = [Math.min(faceA[s], faceB[s]), Math.max(faceA[s], faceB[s])];
            else if (uses[s] === 1) pair = [faceA[s], -1];
            else continue;
            const key = `${pair[0]},${pair[1]}`;
            let group = groups.get(key);
            if (!group) groups.set(key, group = { faces: pair, sides: [] });
            group.sides.push(s);
            [sideA[s], sideB[s]].forEach(id => {
                touch(id, pair[0]);
                touch(id, pair[1] >= 0 ? pair[1] : -1 - pair[0]);
            });
        }
        const geometries = new Map();
        const geometryOf = k => {
            if (!geometries.has(k)) geometries.set(k, k >= 0 && k < source.count ? faceGeometry(source, k) : null);
            return geometries.get(k);
        };
        const kindOf = k => ((source.faces && source.faces[k]) || {}).kind || 'other';
        const edges = [];
        const faceEdges = new Map();
        const vertexIds = new Map();
        const vertices = [];
        const vertexOf = id => {
            if (!vertexIds.has(id)) {
                vertexIds.set(id, vertices.length);
                vertices.push({ point: point(id), faces: Array.from(meeting.get(id) || []).filter(f => f >= 0) });
            }
            return vertexIds.get(id);
        };
        groups.forEach(group => {
            const around = new Map();
            group.sides.forEach(s => {
                [sideA[s], sideB[s]].forEach(id => {
                    if (!around.has(id)) around.set(id, []);
                    around.get(id).push(s);
                });
            });
            const corner = id => (meeting.get(id) || new Set()).size >= 3 || around.get(id).length !== 2;
            const used = new Set();
            const chains = [];
            const walk = (start, first) => {
                const chain = [start];
                let s = first;
                let id = start;
                for (;;) {
                    used.add(s);
                    id = sideA[s] === id ? sideB[s] : sideA[s];
                    chain.push(id);
                    if (id === start || corner(id)) break;
                    const next = around.get(id).find(t => !used.has(t));
                    if (next === undefined) break;
                    s = next;
                }
                return chain;
            };
            around.forEach((list, id) => {
                if (corner(id)) list.forEach(s => { if (!used.has(s)) chains.push(walk(id, s)); });
            });
            group.sides.forEach(s => { if (!used.has(s)) chains.push(walk(sideA[s], s)); });
            chains.forEach(chain => {
                splitAtCorners(chain, point).forEach(piece => {
                    const points = piece.map(point);
                    const row = classifyChain(points, group.faces, geometryOf, size, kindOf);
                    const closed = piece.length > 3 && piece[0] === piece[piece.length - 1];
                    const edge = Object.assign({ index: edges.length, faces: group.faces.slice(), points }, row);
                    edge.vertices = closed ? [] : [vertexOf(piece[0]), vertexOf(piece[piece.length - 1])];
                    edges.push(edge);
                    group.faces.forEach(face => {
                        if (face < 0) return;
                        if (!faceEdges.has(face)) faceEdges.set(face, []);
                        faceEdges.get(face).push(edge.index);
                    });
                });
            });
        });
        return { size, edges, vertices, exact: Boolean(source.exact), face: geometryOf,
            faceEdges: face => faceEdges.get(face) || [] };
    }

    function splitAtCorners(chain, point) {
        const pieces = [];
        let start = 0;
        for (let i = 1; i < chain.length - 1; i += 1) {
            const before = unit(sub(point(chain[i]), point(chain[i - 1])));
            const after = unit(sub(point(chain[i + 1]), point(chain[i])));
            if (dot(before, after) < CORNER_COS) {
                pieces.push(chain.slice(start, i + 1));
                start = i;
            }
        }
        pieces.push(chain.slice(start));
        // A loop cut at a corner started mid-edge: its last piece runs on into its first.
        if (pieces.length > 1 && chain.length > 3 && chain[0] === chain[chain.length - 1]) {
            const last = pieces.pop();
            pieces[0] = last.concat(pieces[0].slice(1));
        }
        return pieces;
    }

    // ---- Entities: a vertex, an edge or a face, in the coordinates measurements are made in ----

    function vertexEntity(edges, index) {
        const row = edges.vertices[index];
        return row ? { type: 'vertex', point: row.point.slice(), anchor: row.point.slice() } : null;
    }

    function edgeEntity(edges, index) {
        const row = edges.edges[index];
        if (!row) return null;
        const entity = { type: 'edge', kind: row.kind, points: row.points.map(p => p.slice()), length: row.length,
            anchor: row.points[Math.floor((row.points.length - 1) / 2)].slice() };
        if (row.kind === 'line') {
            entity.start = row.start.slice();
            entity.end = row.end.slice();
            entity.anchor = scale(add(row.start, row.end), 0.5);
        } else if (row.kind === 'circle' || row.kind === 'arc') {
            Object.assign(entity, { center: row.center.slice(), normal: row.normal.slice(), radius: row.radius });
        }
        return entity;
    }

    function faceEntity(edges, face) {
        const g = edges.face(face);
        if (!g) return null;
        const entity = { type: 'face', kind: g.kind, triangles: g.triangles, anchor: g.centroid.slice(),
            approximate: g.approximate };
        if (g.kind === 'plane') Object.assign(entity, { point: g.point.slice(), normal: g.normal.slice() });
        if (g.kind === 'cylinder') Object.assign(entity, { point: g.point.slice(), axis: g.axis.slice(), radius: g.radius });
        if (g.kind === 'sphere') Object.assign(entity, { center: g.center.slice(), radius: g.radius });
        return entity;
    }

    function transformEntity(entity, m) {
        // The entity carried by a 4x4 matrix (column-major, three.js's elements): points move, directions turn.
        if (!entity) return null;
        const at = p => [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
            m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
            m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14]];
        const turn = d => unit([m[0] * d[0] + m[4] * d[1] + m[8] * d[2], m[1] * d[0] + m[5] * d[1] + m[9] * d[2],
            m[2] * d[0] + m[6] * d[1] + m[10] * d[2]]);
        const stretch = Math.cbrt(Math.abs(m[0] * (m[5] * m[10] - m[9] * m[6]) - m[4] * (m[1] * m[10] - m[9] * m[2])
            + m[8] * (m[1] * m[6] - m[5] * m[2]))) || 1;
        const out = Object.assign({}, entity);
        ['point', 'start', 'end', 'center', 'anchor', 'pick'].forEach(key => { if (entity[key]) out[key] = at(entity[key]); });
        ['normal', 'axis'].forEach(key => { if (entity[key]) out[key] = turn(entity[key]); });
        if (entity.radius) out.radius = entity.radius * stretch;
        if (entity.length) out.length = entity.length * stretch;
        if (entity.points) out.points = entity.points.map(at);
        if (entity.triangles) {
            const list = new Float64Array(entity.triangles.length);
            for (let i = 0; i < list.length; i += 3) {
                const p = at([entity.triangles[i], entity.triangles[i + 1], entity.triangles[i + 2]]);
                list[i] = p[0]; list[i + 1] = p[1]; list[i + 2] = p[2];
            }
            out.triangles = list;
        }
        return out;
    }

    // ---- What one or two entities measure (SOLIDWORKS Smart Dimension defaults) ----

    function asPoint(e) {
        if (e.type === 'vertex') return e.point;
        if (e.type === 'edge' && (e.kind === 'circle' || e.kind === 'arc')) return e.center;
        if (e.type === 'face' && e.kind === 'sphere') return e.center;
        return null;
    }

    function asLine(e) {
        if (e.type === 'edge' && e.kind === 'line') return { origin: e.start, direction: unit(sub(e.end, e.start)) };
        if (e.type === 'face' && e.kind === 'cylinder') return { origin: e.point, direction: e.axis };
        return null;
    }

    function asPlane(e) { return e.type === 'face' && e.kind === 'plane' ? { origin: e.point, normal: e.normal } : null; }

    function pickOf(e) { return e.pick || e.anchor; }

    function measureOne(e) {
        if (!e) return null;
        if (e.type === 'edge') {
            if (e.kind === 'line') return { kind: 'length', value: distance(e.start, e.end), p1: e.start, p2: e.end };
            if (e.kind === 'circle') {
                return { kind: 'diameter', value: 2 * e.radius, center: e.center, normal: e.normal, radius: e.radius };
            }
            if (e.kind === 'arc') {
                return { kind: 'radius', value: e.radius, center: e.center, normal: e.normal, radius: e.radius };
            }
            return { kind: 'length', value: e.length, curve: e.points, anchor: e.anchor };
        }
        if (e.type === 'face' && e.kind === 'cylinder') {
            const center = footOnLine(pickOf(e), e.point, e.axis);
            return { kind: 'diameter', value: 2 * e.radius, center, normal: e.axis, radius: e.radius };
        }
        if (e.type === 'face' && e.kind === 'sphere') {
            return { kind: 'diameter', sphere: true, value: 2 * e.radius, center: e.center, normal: null, radius: e.radius };
        }
        return null;
    }

    function linear(p1, p2, method) {
        return { kind: 'distance', value: distance(p1, p2), p1, p2, method };
    }

    function towards(direction, origin, target) {
        // The direction turned to point from origin toward target.
        return target && dot(sub(target, origin), direction) < 0 ? scale(direction, -1) : direction;
    }

    function angle(apex, u, v) {
        return { kind: 'angle', value: Math.acos(clamp(dot(u, v), -1, 1)), apex, u, v };
    }

    function measureTwo(a, b) {
        if (!a || !b) return null;
        const pa = asPoint(a);
        const pb = asPoint(b);
        const la = asLine(a);
        const lb = asLine(b);
        const qa = asPlane(a);
        const qb = asPlane(b);
        const centre = (a.type === 'edge' && pa) || (b.type === 'edge' && pb) ? 'centre' : undefined;
        if (pa && pb) return linear(pa, pb, centre);
        if (pa && lb) return linear(pa, footOnLine(pa, lb.origin, lb.direction), centre || 'perpendicular');
        if (la && pb) return linear(footOnLine(pb, la.origin, la.direction), pb, centre || 'perpendicular');
        if (pa && qb) return linear(pa, footOnPlane(pa, qb.origin, qb.normal), centre || 'perpendicular');
        if (qa && pb) return linear(footOnPlane(pb, qa.origin, qa.normal), pb, centre || 'perpendicular');
        if (la && lb) {
            if (length(cross(la.direction, lb.direction)) < PARALLEL_SIN) {
                const p1 = footOnLine(pickOf(a), la.origin, la.direction);
                return linear(p1, footOnLine(p1, lb.origin, lb.direction), 'parallel');
            }
            // The lines' nearest points (the same point where they cross).
            const w = sub(la.origin, lb.origin);
            const d = dot(la.direction, lb.direction);
            const denominator = 1 - d * d;
            const s = (d * dot(lb.direction, w) - dot(la.direction, w)) / denominator;
            const t = (dot(lb.direction, w) - d * dot(la.direction, w)) / denominator;
            const apex = addScaled(la.origin, la.direction, s);
            const other = addScaled(lb.origin, lb.direction, t);
            return angle(apex, towards(la.direction, apex, pickOf(a)), towards(lb.direction, other, pickOf(b)));
        }
        const lineAndPlane = (line, plane, lineEntity, lineFirst) => {
            if (Math.abs(dot(line.direction, plane.normal)) < PARALLEL_SIN) {
                const p1 = footOnLine(pickOf(lineEntity), line.origin, line.direction);
                const p2 = footOnPlane(p1, plane.origin, plane.normal);
                return lineFirst ? linear(p1, p2, 'parallel') : linear(p2, p1, 'parallel');
            }
            const t = dot(sub(plane.origin, line.origin), plane.normal) / dot(line.direction, plane.normal);
            const apex = addScaled(line.origin, line.direction, t);
            const along = towards(line.direction, apex, pickOf(lineEntity));
            let flat = unit(reject(along, plane.normal));
            if (length(flat) < 0.5) flat = perpendicularTo(plane.normal);
            return lineFirst ? angle(apex, along, flat) : angle(apex, flat, along);
        };
        if (la && qb) return lineAndPlane(la, qb, a, true);
        if (qa && lb) return lineAndPlane(lb, qa, b, false);
        if (qa && qb) {
            if (length(cross(qa.normal, qb.normal)) < PARALLEL_SIN) {
                const p1 = footOnPlane(pickOf(a), qa.origin, qa.normal);
                return linear(p1, footOnPlane(p1, qb.origin, qb.normal), 'parallel');
            }
            // On the line where the planes meet, nearest the two picks; each face's direction away from it.
            const line = unit(cross(qa.normal, qb.normal));
            const mid = scale(add(pickOf(a), pickOf(b)), 0.5);
            const c = dot(qa.normal, qb.normal);
            const r1 = dot(qa.normal, qa.origin) - dot(qa.normal, mid);
            const r2 = dot(qb.normal, qb.origin) - dot(qb.normal, mid);
            const alpha = (r1 - c * r2) / (1 - c * c);
            const beta = (r2 - c * r1) / (1 - c * c);
            const apex = addScaled(addScaled(mid, qa.normal, alpha), qb.normal, beta);
            let u = unit(reject(sub(pickOf(a), apex), line));
            let v = unit(reject(sub(pickOf(b), apex), line));
            if (length(u) < 0.5) u = unit(cross(qa.normal, line));
            if (length(v) < 0.5) v = unit(cross(line, qb.normal));
            return angle(apex, u, v);
        }
        return minimum(a, b);
    }

    function measure(a, b) {
        return b ? measureTwo(a, b) : measureOne(a);
    }

    // ---- Minimum distance between any two entities ----

    function primitives(e) {
        const points = [];
        const segments = [];
        const triangles = [];
        if (e.type === 'vertex') points.push(e.point);
        else if (e.type === 'edge') {
            if (e.kind === 'line') segments.push([e.start, e.end]);
            else for (let i = 1; i < e.points.length; i += 1) segments.push([e.points[i - 1], e.points[i]]);
        } else if (e.triangles) {
            for (let i = 0; i + 8 < e.triangles.length; i += 9) {
                const t = e.triangles;
                triangles.push([[t[i], t[i + 1], t[i + 2]], [t[i + 3], t[i + 4], t[i + 5]], [t[i + 6], t[i + 7], t[i + 8]]]);
            }
        }
        const corners = points.slice();
        segments.forEach(([p, q]) => { corners.push(p, q); });
        triangles.forEach(([p, q, r]) => { corners.push(p, q, r); });
        return { points, segments, triangles, corners };
    }

    function closestOnSegment(p, a, b) {
        const ab = sub(b, a);
        const l2 = dot(ab, ab);
        return l2 > 0 ? addScaled(a, ab, clamp(dot(sub(p, a), ab) / l2, 0, 1)) : a;
    }

    function closestOnTriangle(p, a, b, c) {
        // Ericson, Real-Time Collision Detection 5.1.5.
        const ab = sub(b, a);
        const ac = sub(c, a);
        const ap = sub(p, a);
        const d1 = dot(ab, ap);
        const d2 = dot(ac, ap);
        if (d1 <= 0 && d2 <= 0) return a;
        const bp = sub(p, b);
        const d3 = dot(ab, bp);
        const d4 = dot(ac, bp);
        if (d3 >= 0 && d4 <= d3) return b;
        const vc = d1 * d4 - d3 * d2;
        if (vc <= 0 && d1 >= 0 && d3 <= 0) return addScaled(a, ab, d1 / (d1 - d3));
        const cp = sub(p, c);
        const d5 = dot(ab, cp);
        const d6 = dot(ac, cp);
        if (d6 >= 0 && d5 <= d6) return c;
        const vb = d5 * d2 - d1 * d6;
        if (vb <= 0 && d2 >= 0 && d6 <= 0) return addScaled(a, ac, d2 / (d2 - d6));
        const va = d3 * d6 - d5 * d4;
        if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) return addScaled(b, sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)));
        const denominator = 1 / (va + vb + vc);
        return addScaled(addScaled(a, ab, vb * denominator), ac, vc * denominator);
    }

    function closestSegments(p1, q1, p2, q2) {
        // Ericson 5.1.9: the nearest points of two segments.
        const d1 = sub(q1, p1);
        const d2 = sub(q2, p2);
        const r = sub(p1, p2);
        const a = dot(d1, d1);
        const e = dot(d2, d2);
        const f = dot(d2, r);
        let s = 0;
        let t = 0;
        if (a <= 1e-30 && e <= 1e-30) return [p1, p2];
        if (a <= 1e-30) t = clamp(f / e, 0, 1);
        else {
            const c = dot(d1, r);
            if (e <= 1e-30) s = clamp(-c / a, 0, 1);
            else {
                const b = dot(d1, d2);
                const denominator = a * e - b * b;
                s = denominator > 1e-30 ? clamp((b * f - c * e) / denominator, 0, 1) : 0;
                t = (b * s + f) / e;
                if (t < 0) { t = 0; s = clamp(-c / a, 0, 1); } else if (t > 1) { t = 1; s = clamp((b - c) / a, 0, 1); }
            }
        }
        return [addScaled(p1, d1, s), addScaled(p2, d2, t)];
    }

    function minimum(a, b) {
        const one = primitives(a);
        const two = primitives(b);
        let best = null;
        const consider = (p, q) => {
            const d = distance(p, q);
            if (!best || d < best[2]) best = [p, q, d];
        };
        const pointTo = (p, set, flip) => {
            set.points.forEach(q => (flip ? consider(q, p) : consider(p, q)));
            set.segments.forEach(([s, t]) => {
                const q = closestOnSegment(p, s, t);
                if (flip) consider(q, p); else consider(p, q);
            });
            set.triangles.forEach(([s, t, u]) => {
                const q = closestOnTriangle(p, s, t, u);
                if (flip) consider(q, p); else consider(p, q);
            });
        };
        one.corners.forEach(p => pointTo(p, two, false));
        two.corners.forEach(q => pointTo(q, one, true));
        one.segments.forEach(([p, q]) => {
            two.segments.forEach(([s, t]) => {
                const [x, y] = closestSegments(p, q, s, t);
                consider(x, y);
            });
        });
        return best ? linear(best[0], best[1], 'minimum') : null;
    }

    // ---- The value as SOLIDWORKS writes it ----

    function formatValue(m, units, value) {
        const amount = value === undefined ? m.value : value;
        if (m.kind === 'angle') return (amount * 180 / Math.PI).toFixed(2) + DEGREE;
        const text = (units === 'in' ? amount / INCH : amount * 1000).toFixed(2);
        if (m.kind === 'diameter') return (m.sphere ? 'S' : '') + DIAMETER + text;
        if (m.kind === 'radius') return 'R' + text;
        return text;
    }

    // ---- Layout: where the lines, arrows and text go for a text point ----

    function dimensionPlane(m, viewDirection) {
        // The plane the dimension is drawn in (and the pointer is followed in).
        if (m.kind === 'angle') {
            const n = cross(m.u, m.v);
            if (length(n) > 1e-6) return { origin: m.apex, normal: unit(n) };
            return { origin: m.apex, normal: viewDirection };
        }
        if (m.kind === 'diameter' || m.kind === 'radius') {
            if (m.normal && Math.abs(dot(m.normal, viewDirection)) > 0.2) return { origin: m.center, normal: m.normal };
            return { origin: m.center, normal: viewDirection };
        }
        if (m.p1 && m.p2 && distance(m.p1, m.p2) > 1e-12) {
            const along = unit(sub(m.p2, m.p1));
            let n = reject(viewDirection, along);
            if (length(n) < 1e-6) n = perpendicularTo(along);
            return { origin: scale(add(m.p1, m.p2), 0.5), normal: unit(n) };
        }
        return { origin: m.anchor || m.p1 || m.center || [0, 0, 0], normal: viewDirection };
    }

    function textOnRay(m, ray, viewDirection) {
        // Where the pointer's ray meets the dimension's plane: the text point it asks for.
        const plane = dimensionPlane(m, viewDirection);
        const denominator = dot(ray.direction, plane.normal);
        if (Math.abs(denominator) < 1e-9) return null;
        const t = dot(sub(plane.origin, ray.origin), plane.normal) / denominator;
        return t > 0 ? addScaled(ray.origin, ray.direction, t) : null;
    }

    // The sides a linear dimension placed without a text point is drawn out to, in this order: the machine's front
    // (+Z) and right (+X) first, which the view's default camera sees, then the others.
    const SIDES = [[0, 0, 1], [1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, 0, -1], [0, -1, 0]];

    function defaultSide(m) {
        // The first side square enough to a distance or length (an index into SIDES), or -1 for anything else.
        if ((m.kind !== 'distance' && m.kind !== 'length') || !m.p1 || !m.p2) return -1;
        if (distance(m.p1, m.p2) < 1e-12) return -1;
        const along = unit(sub(m.p2, m.p1));
        return SIDES.findIndex(side => Math.abs(dot(side, along)) < 0.5);
    }

    function defaultText(m, centre, size, options = {}) {
        // A text point for a dimension placed without one (Sage's). A distance with the box its parts fill (world
        // min and max) goes out past them on its side, as on a drawing, `stack` steps further for each one before
        // it there; anything else goes beside it, away from the machine's centre.
        const reach = Math.max(size, 1e-3);
        const side = options.box ? defaultSide(m) : -1;
        if (side >= 0) {
            const along = unit(sub(m.p2, m.p1));
            const out = unit(reject(SIDES[side], along));
            const mid = scale(add(m.p1, m.p2), 0.5);
            const { min, max } = options.box;
            let limit = -Infinity;
            [min[0], max[0]].forEach(x => [min[1], max[1]].forEach(y => [min[2], max[2]].forEach(z => {
                limit = Math.max(limit, dot(out, [x, y, z]));
            })));
            const beyond = Math.max(0, limit - dot(out, mid));
            return addScaled(mid, out, beyond + (0.04 + 0.035 * (options.stack || 0)) * reach);
        }
        if (m.kind === 'angle') {
            let mid = unit(add(m.u, m.v));
            if (length(mid) < 0.5) mid = m.u;
            return addScaled(m.apex, mid, 0.15 * reach);
        }
        if (m.kind === 'diameter' || m.kind === 'radius') {
            const normal = m.normal || [0, 0, 1];
            let away = unit(reject(sub(m.center, centre), normal));
            if (length(away) < 0.5) away = perpendicularTo(normal);
            return addScaled(m.center, away, m.radius + 0.08 * reach);
        }
        if (m.p1 && m.p2) {
            const mid = scale(add(m.p1, m.p2), 0.5);
            const span = distance(m.p1, m.p2);
            const along = span > 1e-12 ? unit(sub(m.p2, m.p1)) : [1, 0, 0];
            let away = unit(reject(sub(mid, centre), along));
            if (length(away) < 0.5) away = perpendicularTo(along);
            return addScaled(mid, away, 0.06 * reach + 0.1 * span);
        }
        const anchor = m.anchor || [0, 0, 0];
        let away = unit(sub(anchor, centre));
        if (length(away) < 0.5) away = [0, 1, 0];
        return addScaled(anchor, away, 0.08 * reach);
    }

    function layout(m, text, view, units) {
        // Screen pieces for the dimension m with its text at the world point text. view.project(p) gives [x, y] in
        // pixels, or null behind the camera. { lines, extensions, arrows: [{x, y, dx, dy}] (tip and the way it
        // points), text: [x, y], label, value }.
        const out = { lines: [], extensions: [], arrows: [], text: null, label: '', value: m.value };
        const P = p => view.project(p);
        const line = (list, p, q) => { if (p && q) list.push([p[0], p[1], q[0], q[1]]); };
        const flat = (p, q) => {
            if (!p || !q) return null;
            const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
            return d > 1e-9 ? [(q[0] - p[0]) / d, (q[1] - p[1]) / d] : null;
        };
        const arrow = (tip, from) => {
            const d = flat(from, tip);
            if (tip && d) out.arrows.push({ x: tip[0], y: tip[1], dx: d[0], dy: d[1] });
        };
        const extension = (from, to) => {
            // From the feature (a small gap off it) to a little past the dimension line.
            const d = flat(from, to);
            if (!d || Math.hypot(to[0] - from[0], to[1] - from[1]) < 4) return;
            out.extensions.push([from[0] + 3 * d[0], from[1] + 3 * d[1], to[0] + 6 * d[0], to[1] + 6 * d[1]]);
        };
        if (m.kind === 'angle') {
            const plane = cross(m.u, m.v);
            const n = length(plane) > 1e-9 ? unit(plane) : perpendicularTo(m.u);
            const t = reject(sub(text, m.apex), n);
            const rho = length(t) || 1e-3;
            // The quadrant the text is in picks the angle or its supplement.
            let a = m.u;
            let b = m.v;
            const inside = (p, q) => dot(cross(p, t), n) * dot(cross(p, q), n) >= 0
                && dot(cross(t, q), n) * dot(cross(p, q), n) >= 0 && dot(add(p, q), t) >= -1e-12;
            for (const [s1, s2] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
                if (inside(scale(m.u, s1), scale(m.v, s2))) { a = scale(m.u, s1); b = scale(m.v, s2); break; }
            }
            const alpha = Math.acos(clamp(dot(a, b), -1, 1));
            let w = unit(reject(b, a));
            if (length(w) < 0.5) w = unit(cross(n, a));
            const at = phi => addScaled(m.apex, add(scale(a, Math.cos(phi)), scale(w, Math.sin(phi))), rho);
            const steps = Math.max(8, Math.ceil(alpha / (Math.PI / 48)));
            let previous = P(at(0));
            for (let i = 1; i <= steps; i += 1) {
                const next = P(at(alpha * i / steps));
                line(out.lines, previous, next);
                previous = next;
            }
            const small = Math.min(alpha / 8, 0.05);
            arrow(P(at(0)), P(at(small)));
            arrow(P(at(alpha)), P(at(alpha - small)));
            const apex = P(m.apex);
            if (apex) {
                const start = P(at(0));
                const end = P(at(alpha));
                if (start) extension(apex, start);
                if (end) extension(apex, end);
            }
            const phi = clamp(Math.atan2(dot(t, w), dot(t, a)), 0, alpha);
            out.text = P(at(phi));
            out.value = alpha;
        } else if (m.kind === 'diameter' || m.kind === 'radius') {
            const n = m.normal || unit(sub(text, m.center));
            let u = m.normal ? reject(sub(text, m.center), n) : sub(text, m.center);
            u = length(u) > 1e-12 ? unit(u) : perpendicularTo(m.normal || [0, 0, 1]);
            const along = Math.max(dot(sub(text, m.center), u), 0);
            const rim = addScaled(m.center, u, m.radius);
            const tip = addScaled(m.center, u, Math.max(along, m.radius));
            const centre = P(m.center);
            if (m.kind === 'diameter') {
                const far = addScaled(m.center, u, -m.radius);
                line(out.lines, P(far), P(tip));
                arrow(P(far), centre);
                arrow(P(rim), centre);
            } else {
                line(out.lines, centre, P(tip));
                arrow(P(rim), centre);
            }
            out.text = P(addScaled(m.center, u, Math.max(along, m.kind === 'radius' ? m.radius * 0.5 : 0)));
        } else if (m.p1 && m.p2) {
            const span = distance(m.p1, m.p2);
            const one = P(m.p1);
            const two = P(m.p2);
            if (span <= 1e-12) {
                line(out.lines, one, P(text));
                out.text = P(text);
            } else {
                const along = unit(sub(m.p2, m.p1));
                const offset = reject(sub(text, m.p1), along);
                const A = add(m.p1, offset);
                const B = add(m.p2, offset);
                const t = dot(sub(text, A), along);
                const a = P(A);
                const b = P(B);
                const at = P(addScaled(A, along, t));
                line(out.lines, a, b);
                if (t < 0) line(out.lines, at, a);
                if (t > span) line(out.lines, b, at);
                if (a && b) {
                    if (Math.hypot(b[0] - a[0], b[1] - a[1]) >= 26) {
                        arrow(a, b);
                        arrow(b, a);
                    } else {
                        // Too short for arrows inside: outside, pointing in, with short tails.
                        const d = flat(a, b) || [1, 0];
                        out.arrows.push({ x: a[0], y: a[1], dx: d[0], dy: d[1] });
                        out.arrows.push({ x: b[0], y: b[1], dx: -d[0], dy: -d[1] });
                        out.lines.push([a[0] - 16 * d[0], a[1] - 16 * d[1], a[0], a[1]]);
                        out.lines.push([b[0], b[1], b[0] + 16 * d[0], b[1] + 16 * d[1]]);
                    }
                }
                if (length(offset) > 1e-12) {
                    if (one && a) extension(one, a);
                    if (two && b) extension(two, b);
                }
                out.text = at;
            }
        } else {
            // A curve's length: a leader from the curve to the text.
            let near = m.anchor;
            let best = Infinity;
            (m.curve || []).forEach(p => {
                const d = distance(p, text);
                if (d < best) { best = d; near = p; }
            });
            const tip = P(near);
            const at = P(text);
            line(out.lines, tip, at);
            arrow(tip, at);
            out.text = at;
        }
        out.label = formatValue(m, units, out.value);
        return out;
    }

    // ---- Picking on the screen ----

    function screenDistance(points, x, y) {
        // The nearest a screen polyline ([[x, y] | null ...]) comes to (x, y), and where along it.
        let best = Infinity;
        for (let i = 0; i < points.length; i += 1) {
            const p = points[i];
            if (!p) continue;
            best = Math.min(best, Math.hypot(p[0] - x, p[1] - y));
            const q = points[i + 1];
            if (!q) continue;
            const dx = q[0] - p[0];
            const dy = q[1] - p[1];
            const l2 = dx * dx + dy * dy;
            const s = l2 > 0 ? clamp(((x - p[0]) * dx + (y - p[1]) * dy) / l2, 0, 1) : 0;
            best = Math.min(best, Math.hypot(p[0] + s * dx - x, p[1] + s * dy - y));
        }
        return best;
    }

    return {
        PARALLEL_SIN, buildEdges, faceGeometry, fitCircle, vertexEntity, edgeEntity, faceEntity, transformEntity,
        measure, formatValue, dimensionPlane, textOnRay, defaultSide, defaultText, layout, screenDistance,
        vector: { sub, add, scale, addScaled, dot, cross, length, distance, unit, reject, footOnLine, footOnPlane },
    };
}));
