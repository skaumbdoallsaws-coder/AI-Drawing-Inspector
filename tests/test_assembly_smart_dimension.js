'use strict';

// Smart Dimension (docs/assembly-smart-dimension-plan.md, D0-D1): the edges of a part worked out from its CAD
// faces, each face's exact surface, what one or two entities measure (SOLIDWORKS' defaults), the angle's
// quadrant, the layout and the value text. Built shapes from three r128, then the robot and forklift GLBs as our
// exporter wrote them.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const THREE = require('../static/vendor/three/0.128.0/build/three.min.js');
const SD = require('../static/assembly_smart_dimension.js');

const close = (actual, expected, tolerance, label) => {
    assert(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} is not ${expected} (within ${tolerance})`);
};

// A shape as our exporter writes a part: each triangle its own three vertices in order, a CAD face per group.
function exported(geometry, kinds, radii) {
    const flat = geometry.toNonIndexed();
    const position = Array.from(flat.getAttribute('position').array);
    const normal = Array.from(flat.getAttribute('normal').array);
    const triangles = position.length / 9;
    const faceOf = new Int32Array(triangles);
    const groups = flat.groups.length ? flat.groups : [{ start: 0, count: triangles * 3, materialIndex: 0 }];
    const starts = [];
    groups.forEach((group, k) => {
        faceOf.fill(k, group.start / 3, (group.start + group.count) / 3);
        starts.push([group.start / 3, group.count / 3]);
    });
    return {
        position, normal, triangles, faceOf, count: groups.length, exact: true,
        faces: groups.map((group, k) => ({ kind: kinds[k], radius: (radii && radii[k]) || 0 })),
        vertex: (u, corner) => 3 * u + corner,
        members: k => {
            const [first, count] = starts[k];
            return Uint32Array.from({ length: count }, (_, i) => first + i);
        },
    };
}

const box = SD.buildEdges(exported(new THREE.BoxGeometry(0.4, 0.2, 0.1), Array(6).fill('plane')));
const cylinder = SD.buildEdges(exported(new THREE.CylinderGeometry(0.05, 0.05, 0.3, 48),
    ['cylinder', 'plane', 'plane'], [0.05, 0, 0]));

const tests = [];
const test = (name, run) => tests.push([name, run]);

test('a box has 12 straight edges and 8 vertices, each edge between two faces', () => {
    assert.strictEqual(box.edges.length, 12);
    assert(box.edges.every(edge => edge.kind === 'line' && edge.faces[1] >= 0));
    assert.strictEqual(box.vertices.length, 8);
    const lengths = box.edges.map(edge => Number(edge.length.toFixed(5))).sort();
    assert.deepStrictEqual(lengths, [0.1, 0.1, 0.1, 0.1, 0.2, 0.2, 0.2, 0.2, 0.4, 0.4, 0.4, 0.4]);
    for (let face = 0; face < 6; face += 1) assert.strictEqual(box.faceEdges(face).length, 4);
    assert(box.vertices.every(vertex => vertex.faces.length === 3));
});

test('a cylinder: its axis and radius, two circles of that radius, no seam edge', () => {
    const side = box && cylinder.face(0);
    assert.strictEqual(side.kind, 'cylinder');
    close(Math.abs(side.axis[1]), 1, 1e-6, 'axis');
    close(Math.hypot(side.point[0], side.point[2]), 0, 1e-6, 'axis through the middle');
    assert.strictEqual(side.radius, 0.05);
    assert.strictEqual(cylinder.edges.length, 2);
    cylinder.edges.forEach(edge => {
        assert.strictEqual(edge.kind, 'circle');
        assert.strictEqual(edge.radius, 0.05);
        close(Math.abs(edge.center[1]), 0.15, 1e-6, 'circle at the cap');
    });
    assert.strictEqual(cylinder.vertices.length, 0);
    const cap = cylinder.face(1);
    assert.strictEqual(cap.kind, 'plane');
    close(Math.abs(cap.normal[1]), 1, 1e-6, 'cap normal');
});

test('a hole: the axis found from inward normals', () => {
    const tube = new THREE.CylinderGeometry(0.02, 0.02, 0.1, 32, 1, true);
    const normals = tube.getAttribute('normal');
    for (let i = 0; i < normals.count; i += 1) {
        normals.setXYZ(i, -normals.getX(i), -normals.getY(i), -normals.getZ(i));
    }
    tube.translate(0.3, 0, -0.2);
    const hole = SD.buildEdges(exported(tube, ['cylinder'], [0.02])).face(0);
    assert.strictEqual(hole.kind, 'cylinder');
    close(hole.point[0], 0.3, 1e-6, 'axis x');
    close(hole.point[2], -0.2, 1e-6, 'axis z');
});

const entity = (edges, kind, index, pick) => {
    const row = kind === 'face' ? SD.faceEntity(edges, index)
        : kind === 'edge' ? SD.edgeEntity(edges, index) : SD.vertexEntity(edges, index);
    if (pick) row.pick = pick;
    return row;
};

test('one entity: a line its length, a circle its diameter, a cylinder face its diameter, a plane nothing', () => {
    const longest = box.edges.findIndex(edge => Math.abs(edge.length - 0.4) < 1e-6);
    const line = SD.measure(entity(box, 'edge', longest));
    assert.strictEqual(line.kind, 'length');
    close(line.value, 0.4, 1e-6, 'line');
    const circle = SD.measure(entity(cylinder, 'edge', 0));
    assert.strictEqual(circle.kind, 'diameter');
    close(circle.value, 0.1, 1e-6, 'circle');
    const side = SD.measure(entity(cylinder, 'face', 0, [0.05, 0.1, 0]));
    assert.strictEqual(side.kind, 'diameter');
    close(side.center[1], 0.1, 1e-6, 'diameter where the face was picked');
    assert.strictEqual(SD.measure(entity(box, 'face', 0)), null);
    assert.strictEqual(SD.measure(entity(box, 'vertex', 0)), null);
});

test('pairs: parallel faces, square faces, vertices, vertex to face, circle to face, parallel edges', () => {
    // three's box faces: +X, -X, +Y, -Y, +Z, -Z.
    const across = SD.measure(entity(box, 'face', 0), entity(box, 'face', 1));
    assert.strictEqual(across.kind, 'distance');
    assert.strictEqual(across.method, 'parallel');
    close(across.value, 0.4, 1e-6, 'width');
    const corner = SD.measure(entity(box, 'face', 0), entity(box, 'face', 2));
    assert.strictEqual(corner.kind, 'angle');
    close(corner.value, Math.PI / 2, 1e-6, 'square faces');
    const vertices = box.vertices.map(vertex => vertex.point);
    const far = vertices.findIndex(p => p[0] > 0 && p[1] > 0 && p[2] > 0);
    const opposite = vertices.findIndex(p => p[0] < 0 && p[1] < 0 && p[2] < 0);
    const diagonal = SD.measure(entity(box, 'vertex', far), entity(box, 'vertex', opposite));
    close(diagonal.value, Math.hypot(0.4, 0.2, 0.1), 1e-6, 'diagonal');
    const toFace = SD.measure(entity(box, 'vertex', far), entity(box, 'face', 3));
    assert.strictEqual(toFace.method, 'perpendicular');
    close(toFace.value, 0.2, 1e-6, 'vertex to the bottom face');
    const capToCap = SD.measure(entity(cylinder, 'edge', 0), entity(cylinder, 'face', 2));
    assert.strictEqual(capToCap.method, 'centre');
    assert([0, 0.3].some(value => Math.abs(capToCap.value - value) < 1e-6), 'circle centre to a cap');
    const tops = box.edges.map((edge, index) => [edge, index])
        .filter(([edge]) => Math.abs(edge.length - 0.4) < 1e-6).map(([, index]) => index);
    const parallel = SD.measure(entity(box, 'edge', tops[0]), entity(box, 'edge', tops[1]));
    assert.strictEqual(parallel.method, 'parallel');
    assert([0.1, 0.2, Math.hypot(0.1, 0.2)].some(value => Math.abs(parallel.value - value) < 1e-6));
});

test('two cylinders side by side: the distance between their axes', () => {
    const second = new THREE.CylinderGeometry(0.05, 0.05, 0.3, 48);
    second.translate(0.25, 0, 0.1);
    const other = SD.buildEdges(exported(second, ['cylinder', 'plane', 'plane'], [0.05, 0, 0]));
    const value = SD.measure(entity(cylinder, 'face', 0), entity(other, 'face', 0));
    assert.strictEqual(value.method, 'parallel');
    close(value.value, Math.hypot(0.25, 0.1), 1e-6, 'axes apart');
});

test('two edges at 60 degrees: the quadrant the text is in gives 60 or 120', () => {
    const a = { type: 'edge', kind: 'line', start: [0, 0, 0], end: [1, 0, 0], anchor: [0.5, 0, 0] };
    const b = { type: 'edge', kind: 'line', start: [0, 0, 0], end: [Math.cos(Math.PI / 3), Math.sin(Math.PI / 3), 0],
        anchor: [0.25, 0.43, 0] };
    const m = SD.measure(a, b);
    assert.strictEqual(m.kind, 'angle');
    close(m.value, Math.PI / 3, 1e-12, 'between');
    const view = { project: p => [p[0] * 100, -p[1] * 100] };
    const inside = SD.layout(m, [0.3, 0.1, 0], view, 'mm');
    assert.strictEqual(inside.label, '60.00°');
    const outside = SD.layout(m, [-0.3, 0.3, 0], view, 'mm');
    assert.strictEqual(outside.label, '120.00°');
    assert.strictEqual(outside.arrows.length, 2);
});

test('the layout of a distance: two extension lines, the dimension line, arrows inside or outside', () => {
    const m = SD.measure({ type: 'vertex', point: [0, 0, 0], anchor: [0, 0, 0] },
        { type: 'vertex', point: [0.25, 0, 0], anchor: [0.25, 0, 0] });
    const view = { project: p => [p[0] * 1000, -p[1] * 1000] };
    const drawn = SD.layout(m, [0.1, 0.05, 0], view, 'mm');
    assert.strictEqual(drawn.label, '250.00');
    assert.strictEqual(drawn.extensions.length, 2);
    assert.strictEqual(drawn.arrows.length, 2);
    assert.deepStrictEqual(drawn.text.map(Math.round), [100, -50]);
    assert(drawn.arrows[0].dx < 0 && drawn.arrows[1].dx > 0, 'arrows point out to the extension lines');
    const tight = SD.layout(m, [0.1, 0.05, 0], { project: p => [p[0] * 40, -p[1] * 40] }, 'in');
    assert.strictEqual(tight.label, '9.84');
    assert(tight.arrows[0].dx > 0 && tight.arrows[1].dx < 0, 'short: arrows outside, pointing in');
});

test('the text point follows the pointer in a plane facing the camera', () => {
    const m = SD.measure({ type: 'vertex', point: [0, 0, 0], anchor: [0, 0, 0] },
        { type: 'vertex', point: [1, 0, 0], anchor: [1, 0, 0] });
    const at = SD.textOnRay(m, { origin: [0.5, 0.3, 5], direction: [0, 0, -1] }, [0, 0, -1]);
    assert.deepStrictEqual(at.map(value => Number(value.toFixed(9))), [0.5, 0.3, 0]);
    const placed = SD.defaultText(m, [0.5, -1, 0], 2);
    assert(placed[1] > 0, 'away from the machine centre');
});

test('without a text point a distance goes out past its parts: across in front, front to back on the right', () => {
    const across = SD.measure({ type: 'vertex', point: [-0.5, 1, 0], anchor: [-0.5, 1, 0] },
        { type: 'vertex', point: [0.5, 1, 0], anchor: [0.5, 1, 0] });
    const deep = SD.measure({ type: 'vertex', point: [0, 1, -0.25], anchor: [0, 1, -0.25] },
        { type: 'vertex', point: [0, 1, 0.25], anchor: [0, 1, 0.25] });
    const box = { min: [-0.5, 0.98, -0.26], max: [0.5, 1.0, 0.26] };
    assert.strictEqual(SD.defaultSide(across), 0);
    assert.strictEqual(SD.defaultSide(deep), 1);
    const front = SD.defaultText(across, [0, 0.5, 0], 2, { box });
    const right = SD.defaultText(deep, [0, 0.5, 0], 2, { box });
    close(front[2], 0.26 + 0.08, 1e-12, 'in front of the box');
    close(right[0], 0.5 + 0.08, 1e-12, 'right of the box');
    assert.deepStrictEqual([front[0], front[1]], [0, 1]);
    const second = SD.defaultText(across, [0, 0.5, 0], 2, { box, stack: 1 });
    close(second[2] - front[2], 0.07, 1e-12, 'stacked further out');
    assert.strictEqual(SD.defaultSide({ kind: 'diameter', value: 1 }), -1);
});

test('values as SOLIDWORKS writes them', () => {
    assert.strictEqual(SD.formatValue({ kind: 'distance', value: 1.2345 }, 'mm'), '1234.50');
    assert.strictEqual(SD.formatValue({ kind: 'diameter', value: 0.0254 }, 'in'), 'Ø1.00');
    assert.strictEqual(SD.formatValue({ kind: 'diameter', sphere: true, value: 0.01 }, 'mm'), 'SØ10.00');
    assert.strictEqual(SD.formatValue({ kind: 'radius', value: 0.0125 }, 'mm'), 'R12.50');
    assert.strictEqual(SD.formatValue({ kind: 'angle', value: Math.PI / 4 }, 'mm'), '45.00°');
});

test('minimum distance between a curve and a face', () => {
    const curve = { type: 'edge', kind: 'curve', points: [[0, 0.5, 0], [0.1, 0.45, 0], [0.2, 0.47, 0]], length: 0.2,
        anchor: [0.1, 0.45, 0] };
    const m = SD.measure(curve, entity(box, 'face', 2));
    assert.strictEqual(m.method, 'minimum');
    close(m.value, 0.35, 1e-6, 'down to the top face');
});

// ---- The re-exported library GLBs ----

function readGlb(file) {
    const data = fs.readFileSync(file);
    const length = data.readUInt32LE(12);
    const doc = JSON.parse(data.slice(20, 20 + length).toString('utf8'));
    const binary = data.slice(20 + length + 8);
    const view = index => {
        const accessor = doc.accessors[index];
        const bufferView = doc.bufferViews[accessor.bufferView];
        const offset = binary.byteOffset + (bufferView.byteOffset || 0) + (accessor.byteOffset || 0);
        const count = accessor.count * (accessor.type === 'VEC3' ? 3 : 1);
        const Type = { 5126: Float32Array, 5125: Uint32Array, 5123: Uint16Array }[accessor.componentType];
        return new Type(binary.buffer.slice(offset, offset + count * Type.BYTES_PER_ELEMENT));
    };
    const rows = [];
    doc.meshes.forEach(mesh => mesh.primitives.forEach(primitive => {
        const cad = primitive.extras && primitive.extras.inspectorpro;
        if (!cad) return;
        const index = view(primitive.indices);
        const triangles = index.length / 3;
        const faceOf = new Int32Array(triangles);
        cad.faces.forEach(([first, count], k) => faceOf.fill(k, first, first + count));
        rows.push({
            position: view(primitive.attributes.POSITION), normal: view(primitive.attributes.NORMAL), triangles,
            faceOf, count: cad.faces.length, exact: true,
            faces: cad.faces.map(([, , kind, , radius]) => ({ kind: cad.faceKinds[kind], radius })),
            vertex: (u, corner) => index[3 * u + corner],
            members: k => Uint32Array.from({ length: cad.faces[k][1] }, (_, i) => cad.faces[k][0] + i),
        });
    }));
    return rows;
}

const LIBRARY = path.join(ROOT, 'generated/industrial_assets/local_library');
[['robot', 'abb-irb6650-robot/User Library-6-axis robot abb6650_320_125_colored.glb', 5000],
    ['forklift', 'forklift-telescopic-red/forklift_truck-with_fork-red_colored.glb', 800]].forEach(([name, file, lines]) => {
    test(`the ${name}: its edges, every circle on a cylinder at that cylinder's radius`, () => {
        const source = path.join(LIBRARY, file);
        if (!fs.existsSync(source)) {
            console.log(`  (skipped: ${file} is not in this checkout)`);
            return;
        }
        const started = Date.now();
        const counts = { line: 0, circle: 0, arc: 0, curve: 0 };
        let checked = 0;
        readGlb(source).forEach(mesh => {
            const edges = SD.buildEdges(mesh);
            edges.edges.forEach(edge => {
                counts[edge.kind] += 1;
                if (edge.kind !== 'circle' && edge.kind !== 'arc') return;
                edge.points.forEach(p => {
                    close(SD.vector.distance(p, edge.center), edge.radius, Math.max(edge.radius * 2e-3, 5e-6), 'on its circle');
                });
                const cylinders = edge.faces.map(face => (face >= 0 ? edges.face(face) : null))
                    .filter(g => g && g.kind === 'cylinder');
                if (cylinders.some(g => Math.abs(g.radius - edge.radius) <= edge.radius * 2e-3)) checked += 1;
            });
        });
        assert(counts.line >= lines, `${name}: ${counts.line} lines`);
        assert(counts.circle + counts.arc > 100, `${name}: circles and arcs ${counts.circle + counts.arc}`);
        assert(checked > 50, `${name}: circles on cylinders ${checked}`);
        console.log(`  ${name}: ${JSON.stringify(counts)}, ${checked} on cylinders, ${Date.now() - started} ms`);
    });
});

test('the cases shared with the server (tests/fixtures/smart_dimension_cases.json): same kind, same text', () => {
    // Faces as the view's face report lists them; Sage's dimensions have no text point, so the view puts the
    // text with defaultText, and an angle drawn there shows the value measured.
    const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'smart_dimension_cases.json'), 'utf8'));
    const view = { project: p => [p[0] * 1000 - p[2] * 300, -p[1] * 1000 + p[2] * 300] };
    fixture.cases.forEach(({ name, faces, expect }) => {
        const entities = faces.map(row => ({ type: 'face', ...row.geometry, anchor: row.center.slice() }));
        const m = SD.measure(entities[0], entities[1]);
        if (expect.error) {
            assert.strictEqual(m, null, name);
            return;
        }
        assert.strictEqual(m.kind, expect.kind, name);
        assert.strictEqual(Boolean(m.sphere), Boolean(expect.sphere), name);
        if (expect.method) assert.strictEqual(m.method, expect.method, name);
        assert.strictEqual(SD.formatValue(m, 'mm'), expect.mm, name);
        assert.strictEqual(SD.formatValue(m, 'in'), expect.in, name);
        const drawn = SD.layout(m, SD.defaultText(m, [0, 0, 0], 1), view, 'mm');
        assert.strictEqual(drawn.label, expect.mm, `${name}: drawn at the default text point`);
    });
});

let failed = 0;
tests.forEach(([name, run]) => {
    try {
        run();
        console.log(`ok - ${name}`);
    } catch (error) {
        failed += 1;
        console.log(`not ok - ${name}\n  ${error && error.stack}`);
    }
});
console.log(`${tests.length - failed}/${tests.length} passed`);
if (failed) process.exit(1);
