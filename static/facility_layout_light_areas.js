// General lights on or off by area in the Facility 3D view (docs/facility-lighting-plan.md, L7).
//
// The scene can switch the general lighting on only inside some areas, or everywhere except inside them
// (adjustments.lightAreas). General lighting is the lamps that throw floor pools: a steady glow facing down, hung at
// least 3 m up. Exit signs, beacons and displays stay on. An area is a named floor area (facilityFloorSurfaces) or a
// rectangle on the plan. A lamp is inside an area when its centre is, seen from above, so a light row that crosses
// areas is switched lamp by lamp.
//
// This module resolves the areas, tests points against them and patches a glow material's shader to read a small
// on/off table: one texel per part per copy (the parts of a glow geometry, each lens one, come from the light pools
// module's lampPartsOf). The 3D adapter fills the tables, so a batch of light rows stays one draw call and changing
// the areas rebuilds nothing.
(function (root, factory) {
    'use strict';

    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityLightAreas = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const MODES = ['only', 'except'];
    const MAX_AREAS = 64;
    const TABLE_WIDTH = 2048;  // texels per row of an on/off table; a longer table wraps onto more rows
    const EDGE = 1e-6;         // metres: a point this close to an area's edge is inside it

    function finite(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function boundsOf(points) {
        const bounds = { minX: Infinity, minZ: Infinity, maxX: -Infinity, maxZ: -Infinity };
        points.forEach(function (point) {
            bounds.minX = Math.min(bounds.minX, point[0]);
            bounds.minZ = Math.min(bounds.minZ, point[1]);
            bounds.maxX = Math.max(bounds.maxX, point[0]);
            bounds.maxZ = Math.max(bounds.maxZ, point[1]);
        });
        return bounds;
    }

    // The scene's lightAreas, with each floor area's outline looked up in the layout. Null when the scene has none:
    // general lights on everywhere. A floor area that is gone lights nothing and is listed as missing.
    function resolveAreas(value, layout) {
        if (!value || typeof value !== 'object' || MODES.indexOf(value.mode) < 0 || !Array.isArray(value.areas)) {
            return null;
        }
        const extensions = layout && layout.extensions || {};
        const rows = extensions.facilityFloorSurfaces && Array.isArray(extensions.facilityFloorSurfaces.surfaces)
            ? extensions.facilityFloorSurfaces.surfaces : [];
        const floors = new Map(rows.filter(Boolean).map(function (row) { return [row.surfaceId, row]; }));
        const shapes = [];
        const missing = [];
        value.areas.slice(0, MAX_AREAS).forEach(function (area) {
            if (area && typeof area.surfaceId === 'string') {
                const floor = floors.get(area.surfaceId);
                const points = floor && Array.isArray(floor.boundary) ? floor.boundary.filter(function (point) {
                    return point && finite(point.x) && finite(point.z);
                }).map(function (point) { return [point.x, point.z]; }) : [];
                if (points.length < 3) {
                    missing.push(area.surfaceId);
                    return;
                }
                shapes.push({ kind: 'floor', surfaceId: area.surfaceId, label: String(floor.label || area.surfaceId),
                    points: points, bounds: boundsOf(points) });
                return;
            }
            const box = area && area.rectangle;
            if (!box || !['minX', 'minZ', 'maxX', 'maxZ'].every(function (key) { return finite(box[key]); })
                    || box.maxX <= box.minX || box.maxZ <= box.minZ) return;
            const points = [[box.minX, box.minZ], [box.maxX, box.minZ], [box.maxX, box.maxZ], [box.minX, box.maxZ]];
            shapes.push({ kind: 'rectangle', points: points, bounds: boundsOf(points) });
        });
        return { mode: value.mode, shapes: shapes, missing: missing };
    }

    function onEdge(ax, az, bx, bz, x, z) {
        const length = Math.hypot(bx - ax, bz - az);
        if (Math.abs((bx - ax) * (z - az) - (bz - az) * (x - ax)) > EDGE * Math.max(1, length)) return false;
        return x >= Math.min(ax, bx) - EDGE && x <= Math.max(ax, bx) + EDGE
            && z >= Math.min(az, bz) - EDGE && z <= Math.max(az, bz) + EDGE;
    }

    // Inside a simple polygon ([[x, z], ...]) or on its edge.
    function insidePolygon(points, x, z) {
        let inside = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
            const xi = points[i][0];
            const zi = points[i][1];
            const xj = points[j][0];
            const zj = points[j][1];
            if (onEdge(xi, zi, xj, zj, x, z)) return true;
            if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi) + xi) inside = !inside;
        }
        return inside;
    }

    function insideShape(shape, x, z) {
        const bounds = shape.bounds;
        if (x < bounds.minX - EDGE || x > bounds.maxX + EDGE || z < bounds.minZ - EDGE || z > bounds.maxZ + EDGE) {
            return false;
        }
        return shape.kind === 'rectangle' || insidePolygon(shape.points, x, z);
    }

    // Whether general lighting at plan point (x, z) is on under these areas (null: on everywhere).
    function lit(areas, x, z) {
        if (!areas) return true;
        const inside = areas.shapes.some(function (shape) { return insideShape(shape, x, z); });
        return areas.mode === 'only' ? inside : !inside;
    }

    // An on/off table's size: `parts` texels per copy, wrapped onto rows of at most TABLE_WIDTH.
    function tableSize(parts, copies) {
        const texels = Math.max(1, Math.max(1, parts) * Math.max(1, copies));
        const width = Math.min(TABLE_WIDTH, texels);
        return { width: width, height: Math.ceil(texels / width) };
    }

    // The name three.js gives the renderer's tone mapping in its shader chunk (ACESFilmic for
    // ACESFilmicToneMapping), or null without one.
    function toneMappingName(THREE, value) {
        const names = ['Linear', 'Reinhard', 'Cineon', 'ACESFilmic', 'AgX', 'Neutral'];
        for (let i = 0; i < names.length; i += 1) {
            const constant = THREE && THREE[names[i] + 'ToneMapping'];
            if (constant !== undefined && constant === value) return names[i];
        }
        return null;
    }

    function occurrences(text, part) {
        return String(text).split(part).length - 1;
    }

    // Patch a lit material's shader (onBeforeCompile) so each part's glow is times its on/off texel. A lamp switched
    // off draws as the plain plastic it is: a glowing Lights finish skips tone mapping, so its off lamps are
    // tone-mapped here, the way the renderer does every other surface. False, unpatched, when the shader has
    // changed shape.
    function patchGlowShader(shader, toneMapping) {
        const main = 'void main() {';
        const emissive = '#include <emissivemap_fragment>';
        const toneMapped = '#include <tonemapping_fragment>';
        if (!shader || occurrences(shader.vertexShader, main) !== 1 || occurrences(shader.fragmentShader, main) !== 1
                || occurrences(shader.fragmentShader, emissive) !== 1
                || occurrences(shader.fragmentShader, toneMapped) !== 1) return false;
        const offColor = toneMapping ? toneMapping + 'ToneMapping( color )' : 'color';
        shader.vertexShader = shader.vertexShader.replace(main, [
            'attribute float facilityLamp;',
            'uniform sampler2D facilityLampTable;',
            'uniform int facilityLampParts;',
            'uniform int facilityLampWidth;',
            'uniform float facilityLampMaskOn;',
            'flat varying float vFacilityLampLit;',
            main,
            '#ifdef USE_INSTANCING',
            '\tint facilityLampTexel = gl_InstanceID * facilityLampParts + int( facilityLamp + 0.5 );',
            '#else',
            '\tint facilityLampTexel = int( facilityLamp + 0.5 );',
            '#endif',
            '\tvFacilityLampLit = facilityLampMaskOn > 0.5 ? texelFetch( facilityLampTable, ivec2( facilityLampTexel'
                + ' % facilityLampWidth, facilityLampTexel / facilityLampWidth ), 0 ).r : 1.0;',
        ].join('\n'));
        shader.fragmentShader = shader.fragmentShader
            .replace(main, [
                'flat varying float vFacilityLampLit;',
                '#ifndef TONE_MAPPING',
                '#include <tonemapping_pars_fragment>',
                'vec3 facilityLampOffToneMapping( vec3 color ) { return ' + offColor + '; }',
                '#endif',
                main,
            ].join('\n'))
            .replace(emissive, emissive + '\n\ttotalEmissiveRadiance *= vFacilityLampLit;')
            .replace(toneMapped, [
                '#ifndef TONE_MAPPING',
                '\tgl_FragColor.rgb = mix( facilityLampOffToneMapping( gl_FragColor.rgb ), gl_FragColor.rgb,'
                    + ' vFacilityLampLit );',
                '#endif',
                toneMapped,
            ].join('\n'));
        return true;
    }

    return {
        MODES: MODES.slice(),
        MAX_AREAS: MAX_AREAS,
        resolveAreas: resolveAreas,
        insidePolygon: insidePolygon,
        lit: lit,
        tableSize: tableSize,
        toneMappingName: toneMappingName,
        patchGlowShader: patchGlowShader,
    };
}));
