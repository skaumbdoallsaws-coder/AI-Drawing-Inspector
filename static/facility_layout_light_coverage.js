// Lighting coverage overlay (docs/facility-lighting-plan.md, CC3). The server's estimate (estimated lux on a 1 m grid
// over one area) drawn on the floor in the plan and the 3D view, with the listed dark spots outlined and numbered.
// The bands are one amber hue from dark to light (OKLCH hue 82, lightness 0.19 to 0.96 in even steps), so a dark
// spot looks dark. Shown on request, never saved with the layout.
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.InspectorProFacilityLightCoverage = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const CAPTION = 'Estimate, not a lighting design. No code-compliance claims.';
    const ENCODING = 'uint16le-tenths';
    const OUTSIDE = 65535;          // a grid cell outside the checked area
    const MAX_CELLS = 600000;       // as the server
    const LIFT = 0.05;              // m above the drawn floor (the light pools lie at 0.02)
    const OUTLINE_LIFT = 0.08;
    const OPACITY = 0.8;
    // Each band: its lower bound in estimated lux, label and color.
    const BANDS = Object.freeze([
        { from: 0, label: 'Under 1', color: '#1c1202' },
        { from: 1, label: '1 to 5', color: '#3b2b07' },
        { from: 5, label: '5 to 10', color: '#604509' },
        { from: 10, label: '10 to 20', color: '#876207' },
        { from: 20, label: '20 to 50', color: '#af8008' },
        { from: 50, label: '50 to 100', color: '#d9a00f' },
        { from: 100, label: '100 to 200', color: '#fec348' },
        { from: 200, label: '200 and up', color: '#fff0d6' },
    ].map(Object.freeze));

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function bandOf(lux) {
        let index = 0;
        while (index + 1 < BANDS.length && lux >= BANDS[index + 1].from) index += 1;
        return index;
    }

    function bytesOf(text) {
        if (typeof atob === 'function') {
            const binary = atob(text);
            const bytes = new Uint8Array(binary.length);
            for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
            return bytes;
        }
        if (typeof Buffer === 'function') return new Uint8Array(Buffer.from(text, 'base64'));
        throw new Error('This browser cannot read the lighting estimate.');
    }

    // The server's grid: cells row by row from the south-west one (row = z, column = x). band: -1 outside the area.
    function decode(payload) {
        const grid = payload && payload.grid;
        const cols = grid ? Math.floor(finite(grid.cols, 0)) : 0;
        const rows = grid ? Math.floor(finite(grid.rows, 0)) : 0;
        const cell = grid ? finite(grid.cellMeters, 0) : 0;
        if (!grid || grid.encoding !== ENCODING || typeof grid.values !== 'string' || cols < 1 || rows < 1
                || cols * rows > MAX_CELLS || !(cell > 0)
                || !Number.isFinite(Number(grid.originX)) || !Number.isFinite(Number(grid.originZ))) {
            throw new Error('The lighting estimate came back in a form this view cannot draw.');
        }
        const bytes = bytesOf(grid.values);
        if (bytes.length !== cols * rows * 2) throw new Error('The lighting estimate came back incomplete.');
        const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        const lux = new Float32Array(cols * rows);
        const bands = new Int8Array(cols * rows);
        let inside = 0;
        for (let index = 0; index < cols * rows; index += 1) {
            const value = view.getUint16(index * 2, true);
            if (value === OUTSIDE) {
                lux[index] = NaN;
                bands[index] = -1;
            } else {
                lux[index] = value / 10;
                bands[index] = bandOf(value / 10);
                inside += 1;
            }
        }
        return { originX: Number(grid.originX), originZ: Number(grid.originZ), cell: cell, cols: cols, rows: rows,
            lux: lux, bands: bands, inside: inside };
    }

    function rgbOf(color) {
        return [1, 3, 5].map(function (start) { return parseInt(color.slice(start, start + 2), 16); });
    }

    // The plan's picture of the grid, one pixel per cell, north up; null where the page has no canvas.
    function planImage(documentRef, grid) {
        const canvas = documentRef && typeof documentRef.createElement === 'function'
            ? documentRef.createElement('canvas') : null;
        const context = canvas && typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
        if (!context || typeof context.createImageData !== 'function' || typeof canvas.toDataURL !== 'function') {
            return null;
        }
        canvas.width = grid.cols;
        canvas.height = grid.rows;
        const image = context.createImageData(grid.cols, grid.rows);
        const colors = BANDS.map(function (band) { return rgbOf(band.color); });
        for (let row = 0; row < grid.rows; row += 1) {
            for (let col = 0; col < grid.cols; col += 1) {
                const band = grid.bands[row * grid.cols + col];
                if (band < 0) continue;
                const offset = ((grid.rows - 1 - row) * grid.cols + col) * 4;
                image.data[offset] = colors[band][0];
                image.data[offset + 1] = colors[band][1];
                image.data[offset + 2] = colors[band][2];
                image.data[offset + 3] = 255;
            }
        }
        context.putImageData(image, 0, 0);
        return canvas.toDataURL('image/png');
    }

    function ringPoints(values) {
        const points = [];
        for (let index = 0; index + 1 < (values || []).length; index += 2) {
            const x = Number(values[index]);
            const z = Number(values[index + 1]);
            if (Number.isFinite(x) && Number.isFinite(z)) points.push({ x: x, z: z });
        }
        return points;
    }

    // The listed dark spots: number, centre and outline rings ({x, z} points).
    function spotsOf(payload) {
        return (payload && Array.isArray(payload.spots) ? payload.spots : []).map(function (spot) {
            return { number: spot.number, x: finite(spot.centre && spot.centre.x, 0), z: finite(spot.centre && spot.centre.z, 0),
                rings: (Array.isArray(spot.outline) ? spot.outline : []).map(ringPoints).filter(function (ring) {
                    return ring.length >= 3;
                }) };
        });
    }

    // What the plan draws: the picture over the grid's rectangle, and the spots.
    function planView(documentRef, grid, spots) {
        return { image: planImage(documentRef, grid), opacity: OPACITY, minX: grid.originX, minZ: grid.originZ,
            maxX: grid.originX + grid.cols * grid.cell, maxZ: grid.originZ + grid.rows * grid.cell, spots: spots };
    }

    function insidePolygon(points, x, z) {
        let inside = false;
        for (let index = 0, previous = points.length - 1; index < points.length; previous = index, index += 1) {
            const a = points[index];
            const b = points[previous];
            if ((a.z > z) !== (b.z > z) && x < (b.x - a.x) * (z - a.z) / (b.z - a.z) + a.x) inside = !inside;
        }
        return inside;
    }

    // The top of what the 3D view draws under a point: the highest ground surface or floor area there, else the floor.
    function floorHeight(layout, groundRuntime) {
        const rows = (groundRuntime && typeof groundRuntime.surfaces === 'function' && groundRuntime.surfaces(layout)) || [];
        const base = finite(layout && layout.coordinateFrame && layout.coordinateFrame.floorElevation, 0);
        const surfaces = layout && layout.extensions && layout.extensions.facilityFloorSurfaces;
        const floors = (surfaces && Array.isArray(surfaces.surfaces) ? surfaces.surfaces : []).filter(function (row) {
            return row && Array.isArray(row.boundary) && row.boundary.length >= 3;
        });
        return function (x, z) {
            let top = -Infinity;
            rows.forEach(function (surface) {
                if (x >= surface.minX - 1e-8 && x <= surface.maxX + 1e-8 && z >= surface.minZ - 1e-8
                        && z <= surface.maxZ + 1e-8) {
                    top = Math.max(top, groundRuntime.height(surface, { x: x, z: z }));
                }
            });
            floors.forEach(function (floor) {
                if (insidePolygon(floor.boundary, x, z)) top = Math.max(top, finite(floor.elevation, base));
            });
            return Number.isFinite(top) ? top : base;
        };
    }

    // What the 3D view draws: per band, flat 1 m quads just above the floor under each cell's centre (no slant across
    // a kerb or dock edge); the spot outlines as line segments along the floor, a point at least every metre.
    function sceneView(grid, spots, heightAt) {
        const counts = BANDS.map(function () { return 0; });
        for (let index = 0; index < grid.bands.length; index += 1) if (grid.bands[index] >= 0) counts[grid.bands[index]] += 1;
        const parts = counts.map(function (count, band) {
            return count ? { band: band, color: BANDS[band].color, positions: new Float32Array(count * 12),
                indices: new Uint32Array(count * 6), used: 0 } : null;
        });
        const size = grid.cell;
        for (let row = 0; row < grid.rows; row += 1) {
            for (let col = 0; col < grid.cols; col += 1) {
                const band = grid.bands[row * grid.cols + col];
                if (band < 0) continue;
                const part = parts[band];
                const x = grid.originX + col * size;
                const z = grid.originZ + row * size;
                const y = heightAt(x + size / 2, z + size / 2) + LIFT;
                const first = part.used * 4;
                part.positions.set([x, y, z, x + size, y, z, x + size, y, z + size, x, y, z + size], first * 3);
                part.indices.set([first, first + 2, first + 1, first, first + 3, first + 2], part.used * 6);
                part.used += 1;
            }
        }
        const outline = [];
        spots.forEach(function (spot) {
            spot.rings.forEach(function (ring) {
                ring.forEach(function (start, index) {
                    const end = ring[(index + 1) % ring.length];
                    const steps = Math.max(1, Math.ceil(Math.hypot(end.x - start.x, end.z - start.z) / size));
                    for (let step = 0; step < steps; step += 1) {
                        [step, step + 1].forEach(function (at) {
                            const px = start.x + (end.x - start.x) * at / steps;
                            const pz = start.z + (end.z - start.z) * at / steps;
                            outline.push(px, heightAt(px, pz) + OUTLINE_LIFT, pz);
                        });
                    }
                });
            });
        });
        return { opacity: OPACITY, parts: parts.filter(Boolean).map(function (part) {
            return { band: part.band, color: part.color, positions: part.positions, indices: part.indices };
        }), outline: new Float32Array(outline) };
    }

    // The 3D objects for a scene view, under ROOT: one mesh per band, then the outlines. Not pickable.
    function sceneObjects(THREE, view, root) {
        view.parts.forEach(function (part) {
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.BufferAttribute(part.positions, 3));
            geometry.setIndex(new THREE.BufferAttribute(part.indices, 1));
            const material = new THREE.MeshBasicMaterial({ color: part.color, transparent: true, opacity: view.opacity,
                depthWrite: false, toneMapped: false, fog: false,
                polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 });
            const mesh = new THREE.Mesh(geometry, material);
            mesh.name = 'FacilityLightCoverage:band-' + part.band;
            mesh.renderOrder = 3;
            mesh.raycast = function () {};
            mesh.userData.facilityLightCoverage = { band: part.band, cells: part.indices.length / 6 };
            root.add(mesh);
        });
        if (view.outline.length && THREE.LineSegments) {
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.BufferAttribute(view.outline, 3));
            const line = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: '#ffffff',
                transparent: true, opacity: 0.95, depthWrite: false, toneMapped: false, fog: false }));
            line.name = 'FacilityLightCoverage:dark-spots';
            line.renderOrder = 4;
            line.raycast = function () {};
            line.userData.facilityLightCoverage = { outline: view.outline.length / 6 };
            root.add(line);
        }
        root.name = 'FacilityLightCoverage';
        return root;
    }

    // Everything the views and the Scenes pane need from one server reply.
    function prepare(payload, options) {
        const value = options || {};
        const grid = decode(payload);
        const spots = spotsOf(payload);
        const summary = payload.summary || {};
        return {
            summary: summary,
            caption: CAPTION,
            bands: BANDS,
            spots: (summary.darkSpots && Array.isArray(summary.darkSpots.listed) ? summary.darkSpots.listed : [])
                .map(function (spot, index) { return Object.assign({ number: index + 1 }, spot); }),
            plan: planView(value.document, grid, spots),
            scene: sceneView(grid, spots, floorHeight(value.layout, value.groundRuntime)),
        };
    }

    return { CAPTION: CAPTION, BANDS: BANDS, OUTSIDE: OUTSIDE, LIFT: LIFT, OPACITY: OPACITY, bandOf: bandOf,
        decode: decode, planImage: planImage, spotsOf: spotsOf, floorHeight: floorHeight, sceneView: sceneView,
        sceneObjects: sceneObjects, prepare: prepare };
});
