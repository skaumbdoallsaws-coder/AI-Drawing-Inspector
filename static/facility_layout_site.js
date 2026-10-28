/* Site tab: the layout's place on the Earth (site context, SC1).
 *
 * A top-down view of the property frame with true north up: the aerial photo at
 * true scale, the building's outline at its pose, and a panel to place the layout
 * by address or coordinates. Coordinates are property-frame metres (+X east,
 * +Z north); the server keeps the georeference and derives each photo's corners
 * (ai_inspector/facility_layout/site_context.py). Imagery is context, not a survey.
 */
(function (root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilitySite = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';
    const drawing = typeof module === 'object' && module.exports
        ? require('./facility_layout_editor.js') : root.InspectorProFacilityLayout;
    const globe = typeof module === 'object' && module.exports
        ? require('./facility_layout_site_globe.js') : root.InspectorProFacilitySiteGlobe;
    const copy = value => JSON.parse(JSON.stringify(value));
    const formatMeters = value => Number(value).toFixed(2) + ' m / ' + (Number(value) * 3.280839895).toFixed(1) + ' ft';
    const pointsText = points => drawing.polygonPointString(points,
        { offsetX: 0, offsetY: 0, minX: 0, maxZ: 0, scale: 1 });

    function parseBoundary(text) {
        const lines = String(text).trim().split(/\n+/);
        const points = lines.map(line => {
            const values = line.trim().split(/[\s,;]+/).map(Number);
            if (values.length !== 2 || !values.every(Number.isFinite)) throw new Error('Each vertex needs X, Z in meters.');
            return { x: values[0], z: values[1] };
        });
        if (points.length < 3 || points.length > 128) throw new Error('A boundary needs 3 to 128 vertices.');
        return points;
    }

    function replaceBoundary(property, boundary) {
        const value = copy(property);
        const before = value.boundary;
        if (before.length !== boundary.length) {
            value.streetEdges = []; value.rearEdges = []; value.entrances = [];
        } else {
            value.entrances = (value.entrances || []).map(entrance => {
                const i = entrance.edgeIndex;
                const a = before[i], b = before[(i + 1) % before.length];
                const dx = b.x - a.x, dz = b.z - a.z;
                const t = Math.max(0, Math.min(1, ((entrance.x - a.x) * dx + (entrance.z - a.z) * dz) / (dx * dx + dz * dz)));
                const c = boundary[i], d = boundary[(i + 1) % boundary.length];
                return Object.assign({}, entrance, { x: c.x + t * (d.x - c.x), z: c.z + t * (d.z - c.z) });
            });
        }
        value.boundary = copy(boundary);
        return value;
    }

    const SVG = 'http://www.w3.org/2000/svg';
    const SITE_KEY = 'facilitySiteContext';
    const AREA_SIZES = [[150, '300 m square'], [250, '500 m square'], [500, '1 km square']];
    const PHOTO_SOURCES = [['standard', 'Standard: USGS NAIP, nationwide'],
        ['mngeo_metro', 'High resolution: Twin Cities metro, 2025']];
    const LAYER_ROWS = [['flood', 'Flood zones', 'FEMA flood map'], ['wetlands', 'Wetlands', 'USFWS wetlands'],
        ['contours', 'Contours', 'USGS elevation'], ['soils', 'Soils', 'USDA soil survey']];
    const LAYER_NAMES = { flood: 'Flood', wetlands: 'Wetlands', contours: 'Ground', soils: 'Soils' };
    const SOURCE_NAMES = { usgs_naip: 'USGS NAIP', usgs_imagery: 'USGS The National Map',
        mngeo_metro: 'Metropolitan Council / MnGeo 2025 metro photo' };
    const AREA_KINDS = ['truck_court', 'trailer_parking', 'parking', 'drive', 'sidewalk', 'landscape', 'outdoor_storage',
        'existing_pavement'];
    // Reference outlines (site_context.REFERENCE_AREA_KINDS): drawn dashed on the Site tab, never built in 3D,
    // where the photo already shows them.
    const REFERENCE_AREA_KINDS = ['existing_pavement'];
    const SURFACES = {
        asphalt: { material: 'concrete', color: '#3d4247', roughness: 0.95 },
        concrete: { material: 'concrete', color: '#aaaeb0', roughness: 0.95 },
        grass: { material: 'turf', color: '#3c794c', roughness: 1 },
    };
    const kindLabel = value => value.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
    // Roads from the US Census map (site_roads.py): line width in screen pixels by kind.
    const ROAD_WIDTHS = { highway: 5, arterial: 4, ramp: 2, local: 2.5, service: 1.5, alley: 1.5, private: 1.5,
        parking_aisle: 1.2, railroad: 2 };
    const HIGHWAY_NAME = /(hwy|highway|interstate|route)\b|^(us|i)[ -]\d/i;
    // Vehicle routes to the main road (site_access.vehicle_routes): one line each way, on the right of its
    // direction of travel as traffic drives, with arrowheads. Incoming solid, outgoing dashed.
    const ROUTE_COLORS = { trucks: '#ff4d6d', cars: '#38bdf8', shared: '#c084fc' };
    const ROUTE_NAMES = { trucks: 'Trucks', cars: 'Cars', shared: 'Vehicles' };

    function areaSurfaces(layout) {
        const site = siteContextOf(layout);
        if (!site) return [];
        return (site.areas || []).filter(area => REFERENCE_AREA_KINDS.indexOf(area.kind) < 0).map(area => Object.assign({
            surfaceId: area.areaId, label: area.label,
            elevation: Number(layout.coordinateFrame && layout.coordinateFrame.floorElevation || 0) - 0.025,
            boundary: area.boundary.map(p => propertyToBuilding(site.buildingPose, p.x, p.z)),
        }, SURFACES[area.surface] || SURFACES.asphalt));
    }
    const MIN_METERS_PER_PIXEL = 0.02;
    const MAX_METERS_PER_PIXEL = 20;

    function siteContextOf(layout) {
        const extensions = layout && layout.extensions;
        const value = extensions && extensions[SITE_KEY];
        return value && value.georeference ? value : null;
    }

    function planSize(layout) {
        const plan = (layout && layout.extensions && layout.extensions.facilityPlan) || {};
        return { width: Number(plan.widthMeters) || 40, depth: Number(plan.depthMeters) || 30 };
    }

    // A point of the layout's own frame, in the property frame.
    function buildingToProperty(pose, x, z) {
        const bearing = (Number(pose.bearingDegrees) || 0) * Math.PI / 180;
        const cos = Math.cos(bearing);
        const sin = Math.sin(bearing);
        return {
            x: Number(pose.x) + x * cos + z * sin,
            z: Number(pose.z) - x * sin + z * cos,
        };
    }

    // ...and back: what the 3D view needs to lay a photo under the building.
    function propertyToBuilding(pose, x, z) {
        const bearing = (Number(pose.bearingDegrees) || 0) * Math.PI / 180;
        const dx = x - Number(pose.x);
        const dz = z - Number(pose.z);
        return {
            x: dx * Math.cos(bearing) - dz * Math.sin(bearing),
            z: dx * Math.sin(bearing) + dz * Math.cos(bearing),
        };
    }

    function buildingOutline(layout, site) {
        const size = planSize(layout);
        return [[0, 0], [size.width, 0], [size.width, size.depth], [0, size.depth]].map(function (corner) {
            return buildingToProperty(site.buildingPose, corner[0], corner[1]);
        });
    }

    function imageRect(image) {
        const corners = image.corners;
        return {
            minX: (corners[0].x + corners[3].x) / 2,
            maxX: (corners[1].x + corners[2].x) / 2,
            minZ: (corners[0].z + corners[1].z) / 2,
            maxZ: (corners[2].z + corners[3].z) / 2,
        };
    }

    // The photo's pixels run evenly in latitude and longitude, so a point on it
    // maps to latitude/longitude by proportion across its box.
    function latLonAt(image, x, z) {
        const rect = imageRect(image);
        const bounds = image.geoBounds;
        const u = (x - rect.minX) / (rect.maxX - rect.minX);
        const v = (z - rect.minZ) / (rect.maxZ - rect.minZ);
        if (!(u >= 0 && u <= 1 && v >= 0 && v <= 1)) return null;
        return {
            latitude: bounds.south + v * (bounds.north - bounds.south),
            longitude: bounds.west + u * (bounds.east - bounds.west),
        };
    }

    // The same proportion carried past the photo's edges, for framing rather than picking.
    function geoPoint(image, x, z) {
        const rect = imageRect(image);
        const bounds = image.geoBounds;
        return {
            latitude: bounds.south + (z - rect.minZ) / (rect.maxZ - rect.minZ) * (bounds.north - bounds.south),
            longitude: bounds.west + (x - rect.minX) / (rect.maxX - rect.minX) * (bounds.east - bounds.west),
        };
    }

    // The panel covers the map's left edge, so a view centres its content in the area beside it.
    function panelWidth(viewWidth) {
        return Math.min(290, viewWidth * 0.4);
    }

    function viewForBox(box, viewSize) {
        const beside = panelWidth(viewSize.width);
        const mpp = Math.min(MAX_METERS_PER_PIXEL, Math.max(MIN_METERS_PER_PIXEL,
            Math.max((box.maxX - box.minX) / (viewSize.width - beside), (box.maxZ - box.minZ) / viewSize.height) * 1.04));
        return { cx: (box.minX + box.maxX) / 2 - beside * mpp / 2, cz: (box.minZ + box.maxZ) / 2, mpp: mpp };
    }

    // Each point moved `distance` to the right of the direction of travel (x east, z north).
    function offsetLine(points, distance) {
        return points.map(function (point, index) {
            const before = points[Math.max(0, index - 1)];
            const after = points[Math.min(points.length - 1, index + 1)];
            const dx = after.x - before.x, dz = after.z - before.z, length = Math.hypot(dx, dz) || 1;
            return { x: point.x + dz / length * distance, z: point.z - dx / length * distance };
        });
    }

    // Arrowheads pointing along a line: one every `spacing` metres and one at its end.
    function arrowsAlong(points, spacing, size) {
        const arrows = [];
        const head = (x, z, ux, uz) => [{ x: x + ux * size, z: z + uz * size },
            { x: x - ux * size * 0.6 + uz * size * 0.7, z: z - uz * size * 0.6 - ux * size * 0.7 },
            { x: x - ux * size * 0.6 - uz * size * 0.7, z: z - uz * size * 0.6 + ux * size * 0.7 }];
        let travelled = 0, next = spacing / 2, last = null;
        for (let i = 1; i < points.length; i++) {
            const a = points[i - 1], b = points[i], length = Math.hypot(b.x - a.x, b.z - a.z);
            if (!length) continue;
            const ux = (b.x - a.x) / length, uz = (b.z - a.z) / length;
            while (next <= travelled + length - size * 2) {
                arrows.push(head(a.x + ux * (next - travelled), a.z + uz * (next - travelled), ux, uz));
                next += spacing;
            }
            travelled += length;
            last = { x: b.x - ux * size, z: b.z - uz * size, ux: ux, uz: uz };
        }
        if (last) arrows.push(head(last.x, last.z, last.ux, last.uz));
        return arrows;
    }

    // A line cut into dashes `on` metres long with `off` metre gaps.
    function dashes(points, on, off) {
        const pieces = [];
        let current = [points[0]], drawn = 0, gap = 0, drawing = true;
        for (let i = 1; i < points.length; i++) {
            let a = points[i - 1];
            const b = points[i];
            let left = Math.hypot(b.x - a.x, b.z - a.z);
            while (left > 1e-9) {
                const room = drawing ? on - drawn : off - gap;
                const step = Math.min(room, left);
                const t = step / left;
                const point = { x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t };
                if (drawing) { current.push(point); drawn += step; } else { gap += step; }
                left -= step;
                a = point;
                if (drawing && drawn >= on - 1e-9) { pieces.push(current); drawing = false; gap = 0; }
                else if (!drawing && gap >= off - 1e-9) { drawing = true; drawn = 0; current = [point]; }
            }
        }
        if (drawing && current.length > 1) pieces.push(current);
        return pieces;
    }

    // The main road a route reaches, by its route name ("State Hwy 95") when it has one.
    function routeTarget(route, roads) {
        const road = (roads || []).find(item => item.label === route.mainRoad);
        return (road && (road.names || []).find(name => HIGHWAY_NAME.test(name))) || route.mainRoad || '';
    }

    // One name per road, on its longest straight stretch, turned to read left to right. A highway
    // shows its route name ("State Hwy 95") rather than a town's street name for it.
    function roadLabels(roads) {
        const best = {};
        (roads || []).forEach(function (road) {
            if (road.kind === 'railroad' || !road.names || !road.names.length || !road.line) return;
            const text = ((road.kind === 'highway' || road.kind === 'arterial')
                && road.names.find(name => HIGHWAY_NAME.test(name))) || road.names[0];
            for (let index = 1; index < road.line.length; index += 1) {
                const a = road.line[index - 1];
                const b = road.line[index];
                const length = Math.hypot(b.x - a.x, b.z - a.z);
                if (best[road.label] && best[road.label].length >= length) continue;
                let angle = Math.atan2(-(b.z - a.z), b.x - a.x) * 180 / Math.PI;
                if (angle > 90) angle -= 180;
                if (angle <= -90) angle += 180;
                best[road.label] = { text: text, x: (a.x + b.x) / 2, z: (a.z + b.z) / 2,
                    angle: Math.round(angle * 10) / 10, length: length };
            }
        });
        return Object.keys(best).map(key => best[key]);
    }

    // What a trace found, in words: size, shape, and how far to trust it.
    function traceSummary(traced) {
        const axes = ['north-south', 'northeast-southwest', 'east-west', 'northwest-southeast'];
        const axis = axes[Math.round(Number(traced.longAxisBearingDegrees) / 45) % 4];
        return 'Traced ' + Number(traced.areaAcres).toFixed(2) + ' ac ('
            + Math.round(traced.areaSquareMeters).toLocaleString('en-US') + ' sq m), about '
            + Math.round(traced.lengthMeters) + ' x ' + Math.round(traced.widthMeters) + ' m, long side ' + axis
            + ', perimeter ' + Math.round(traced.perimeterMeters) + ' m. Accurate to about ' + traced.accuracyMeters + ' m'
            + (traced.touchesPhotoEdge ? '; it runs past the photo\'s edge' : '')
            + '. Existing pavement as seen on the photo, not a property line. Check the corners, then Apply area.';
    }

    function niceLength(meters) {
        const power = Math.pow(10, Math.floor(Math.log10(Math.max(meters, 1e-6))));
        const steps = [1, 2, 5, 10];
        for (let index = 0; index < steps.length; index += 1) {
            if (steps[index] * power >= meters) return steps[index] * power;
        }
        return 10 * power;
    }

    function parseCoordinates(text) {
        const parts = String(text || '').split(/[\s,;]+/).filter(Boolean).map(Number);
        if (parts.length !== 2 || !parts.every(Number.isFinite)) return null;
        if (Math.abs(parts[0]) > 89 || Math.abs(parts[1]) > 180) return null;
        return { latitude: parts[0], longitude: parts[1] };
    }

    function imageFields(image) {
        return {
            imageId: image.imageId,
            imagePath: image.imagePath,
            source: image.source,
            captured: image.captured === undefined ? null : image.captured,
            geoBounds: image.geoBounds,
            widthPixels: image.widthPixels,
            heightPixels: image.heightPixels,
        };
    }

    function firstImageId(site) {
        return site && site.imagery && site.imagery.length ? site.imagery[0].imageId : '';
    }

    // A straight-line distance on the photo, in the property frame (metres).
    function measureDistance(a, b) {
        return Math.hypot(Number(b.x) - Number(a.x), Number(b.z) - Number(a.z));
    }

    function formatDistance(meters) {
        const m = Number(meters);
        if (!Number.isFinite(m)) return '';
        const feet = m / 0.3048;
        const metric = m >= 1000 ? (m / 1000).toFixed(3) + ' km' : m.toFixed(m >= 100 ? 1 : 2) + ' m';
        return metric + ' (' + (feet >= 1000 ? Math.round(feet).toLocaleString('en-US') : feet.toFixed(1)) + ' ft)';
    }

    function sourceLabel(image) {
        const name = SOURCE_NAMES[image.source] || 'USGS The National Map';
        return name + (image.captured ? ', flown ' + image.captured : '') + ' (public domain)';
    }

    function create(options) {
        const documentRef = options.document;
        const session = options.session;
        const state = {
            layout: null, site: null, view: null, mode: 'idle', busy: false,
            message: '', error: '', matches: [], halfSize: 250, opacity: 0.9,
            changing: false, confirmRemove: false, drag: null, visible: false,
            request: null, destroyed: false,
            key: '', address: '', coordinates: '', photoSource: 'standard', measure: [], measureHover: null,
            hiddenLayers: {}, overlayOpacity: 0.8, notice: '',
            section: 'location', propertyDraft: null, poseDraft: null, sketch: [],
            // The settings pane folds away once the site is placed (null: folded whenever a site is placed).
            collapsed: null,
            areaDraft: null,
            readOnly: false, flight: null,
            analysis: null, analysisError: '', analysisRequest: null,
            metricsHost: null,
        };

        function node(tag, attributes, text) {
            const result = documentRef.createElement(tag);
            Object.keys(attributes || {}).forEach(function (key) {
                if (key === 'className') result.className = attributes[key];
                else result.setAttribute(key, attributes[key]);
            });
            if (text !== undefined) result.textContent = text;
            return result;
        }

        function svgNode(tag, attributes) {
            const result = documentRef.createElementNS(SVG, tag);
            Object.keys(attributes || {}).forEach(function (key) { result.setAttribute(key, attributes[key]); });
            return result;
        }

        const element = node('div', {
            id: 'ip-flw-site-view', className: 'ip-flw-view ip-flw-site-view',
            role: 'tabpanel', 'aria-label': 'Site view', tabindex: '0',
        });
        const svg = svgNode('svg', { class: 'ip-flw-site-canvas', 'aria-hidden': 'true' });
        const imageLayer = svgNode('g', {});
        const outlineLayer = svgNode('g', {});
        svg.appendChild(imageLayer);
        svg.appendChild(outlineLayer);
        const measureLayer = svgNode('g', { class: 'ip-flw-site-measure-layer' });
        svg.appendChild(measureLayer);
        const traceLayer = svgNode('g', { class: 'ip-flw-site-trace-layer' });
        svg.appendChild(traceLayer);
        const panel = node('div', { className: 'ip-flw-site-panel', role: 'region', 'aria-label': 'Site' });
        const north = node('div', { className: 'ip-flw-site-north', title: 'True north is up' });
        north.appendChild(node('span', { className: 'ip-flw-site-north-arrow', 'aria-hidden': 'true' }));
        north.appendChild(node('span', {}, 'N'));
        const scale = node('div', { className: 'ip-flw-site-scale', 'aria-hidden': 'true' });
        const scaleBar = node('div', { className: 'ip-flw-site-scale-bar' });
        const scaleLabel = node('div', { className: 'ip-flw-site-scale-label' });
        scale.appendChild(scaleBar);
        scale.appendChild(scaleLabel);
        const credit = node('div', { className: 'ip-flw-site-credit' });
        const progress = node('div', { className: 'ip-flw-site-progress', role: 'status', 'aria-live': 'polite' });
        progress.hidden = true;
        const measureToggle = node('button', { type: 'button', className: 'ip-flw-site-measure-toggle',
            'aria-pressed': 'false', title: 'Measure a distance on the photo' }, 'Measure');
        const measureHint = node('div', { className: 'ip-flw-site-measure-hint', role: 'status' });
        measureHint.hidden = true;
        measureToggle.addEventListener('click', function () {
            if (state.mode === 'measure') { setMode('idle'); return; }
            state.sketch = []; state.measure = []; state.measureHover = null;
            setMode('measure');
            element.focus();
        });
        [svg, panel, north, scale, credit, progress, measureToggle, measureHint]
            .forEach(function (child) { element.appendChild(child); });

        // The measuring line: two clicks on the photo, a live line to the cursor after the first.
        function renderMeasure() {
            measureLayer.textContent = '';
            const active = state.mode === 'measure' && Boolean(state.site) && Boolean(state.view);
            measureToggle.setAttribute('aria-pressed', active ? 'true' : 'false');
            measureToggle.textContent = active ? 'Done' : 'Measure';
            measureHint.hidden = !active;
            element.classList.toggle('ip-flw-site-measuring', active);
            if (!active) return;
            const points = state.measure.slice(0, 2);
            if (points.length === 1 && state.measureHover) points.push(state.measureHover);
            measureHint.textContent = points.length < 2 ? 'Click two points on the photo. Esc to stop.'
                : 'Distance: ' + formatDistance(measureDistance(points[0], points[1]))
                    + (state.measure.length === 2 ? '. Click again to start a new one.' : '');
            if (!points.length) return;
            const mpp = state.view.mpp;
            if (points.length === 2) {
                measureLayer.appendChild(svgNode('line', { class: 'ip-flw-site-measure-line',
                    x1: points[0].x, y1: -points[0].z, x2: points[1].x, y2: -points[1].z, 'stroke-width': 2 * mpp,
                    'stroke-dasharray': [6 * mpp, 4 * mpp].join(' ') }));
                const label = svgNode('text', { class: 'ip-flw-site-measure-label', 'font-size': 13 * mpp,
                    'stroke-width': 3 * mpp, 'text-anchor': 'middle',
                    x: (points[0].x + points[1].x) / 2, y: -(points[0].z + points[1].z) / 2 - 8 * mpp });
                label.textContent = formatDistance(measureDistance(points[0], points[1]));
                measureLayer.appendChild(label);
            }
            points.forEach(function (p) {
                measureLayer.appendChild(svgNode('circle', { class: 'ip-flw-site-measure-point', cx: p.x, cy: -p.z,
                    r: 4 * mpp, 'stroke-width': 1.5 * mpp }));
            });
        }

        function size() {
            return {
                width: Math.max(1, element.clientWidth || 800),
                height: Math.max(1, element.clientHeight || 600),
            };
        }

        function fitView() {
            const site = state.site;
            if (!site) return;
            const boundary = site.property && site.property.boundary;
            const box = boundary && boundary.length
                ? { minX: Math.min(...boundary.map(p => p.x)) - 5, maxX: Math.max(...boundary.map(p => p.x)) + 5,
                    minZ: Math.min(...boundary.map(p => p.z)) - 5, maxZ: Math.max(...boundary.map(p => p.z)) + 5 }
                : site.imagery && site.imagery.length
                ? imageRect(site.imagery[0])
                : (function () {
                    const outline = buildingOutline(state.layout, site);
                    const xs = outline.map(function (p) { return p.x; });
                    const zs = outline.map(function (p) { return p.z; });
                    return { minX: Math.min.apply(null, xs) - 40, maxX: Math.max.apply(null, xs) + 40,
                        minZ: Math.min.apply(null, zs) - 40, maxZ: Math.max.apply(null, zs) + 40 };
                }());
            state.view = viewForBox(box, size());
        }

        function screenToProperty(clientX, clientY) {
            const rect = element.getBoundingClientRect();
            const view = size();
            const millimeters = value => Math.round(value * 1000) / 1000;
            return {
                x: millimeters(state.view.cx + (clientX - rect.left - view.width / 2) * state.view.mpp),
                z: millimeters(state.view.cz - (clientY - rect.top - view.height / 2) * state.view.mpp),
            };
        }

        function renderCanvas() {
            // A hidden view measures 0 x 0: fit and draw only once it shows.
            if (!state.visible) return;
            const site = state.site;
            imageLayer.textContent = '';
            outlineLayer.textContent = '';
            credit.textContent = '';
            if (!site) {
                scale.hidden = true;
                measureToggle.hidden = true;
                renderMeasure();
                return;
            }
            measureToggle.hidden = false;
            if (!state.view) fitView();
            const view = size();
            const mpp = state.view.mpp;
            svg.setAttribute('viewBox', [state.view.cx - view.width * mpp / 2, -state.view.cz - view.height * mpp / 2,
                view.width * mpp, view.height * mpp].join(' '));
            (site.imagery || []).forEach(function (image) {
                const rect = imageRect(image);
                imageLayer.appendChild(svgNode('image', {
                    href: image.imagePath, x: rect.minX, y: -rect.maxZ,
                    width: rect.maxX - rect.minX, height: rect.maxZ - rect.minZ,
                    preserveAspectRatio: 'none', opacity: state.opacity,
                }));
            });
            (site.overlays || []).forEach(function (overlay) {
                if (state.hiddenLayers[overlay.layer]) return;
                const rect = imageRect(overlay);
                imageLayer.appendChild(svgNode('image', {
                    href: overlay.imagePath, x: rect.minX, y: -rect.maxZ, class: 'ip-flw-site-overlay',
                    width: rect.maxX - rect.minX, height: rect.maxZ - rect.minZ,
                    preserveAspectRatio: 'none', opacity: state.overlayOpacity,
                }));
            });
            const roads = site.roads && !state.hiddenLayers.roads ? site.roads.items || [] : [];
            roads.forEach(function (road) {
                if (!road.line || road.line.length < 2) return;
                const line = { points: pointsText(road.line), class: 'ip-flw-site-road ip-flw-site-road-' + road.kind,
                    'stroke-width': (ROAD_WIDTHS[road.kind] || 1.5) * mpp };
                if (road.kind === 'railroad') line['stroke-dasharray'] = [6 * mpp, 4 * mpp].join(' ');
                imageLayer.appendChild(svgNode('polyline', line));
            });
            roadLabels(roads).forEach(function (spot) {
                const label = svgNode('text', { x: spot.x, y: -spot.z, class: 'ip-flw-site-road-label',
                    'font-size': 11 * mpp, 'stroke-width': 3 * mpp, 'text-anchor': 'middle',
                    'dominant-baseline': 'middle', transform: 'rotate(' + spot.angle + ' ' + spot.x + ' ' + (-spot.z) + ')' });
                label.textContent = spot.text;
                imageLayer.appendChild(label);
            });
            const routes = site.routes && !state.hiddenLayers.routes
                ? site.routes.filter(route => route.mainRoad && route.points.length > 1) : [];
            routes.forEach(function (route) {
                const color = ROUTE_COLORS[route.use] || ROUTE_COLORS.shared;
                const outward = offsetLine(route.points, 5 * mpp);
                const inward = offsetLine(route.points.slice().reverse(), 5 * mpp);
                [[inward, false], [outward, true]].forEach(function (pair) {
                    const line = { points: pointsText(pair[0]), class: 'ip-flw-site-route', stroke: color,
                        'stroke-width': 2.5 * mpp, 'data-site-route': route.routeId };
                    if (pair[1]) line['stroke-dasharray'] = [7 * mpp, 5 * mpp].join(' ');
                    imageLayer.appendChild(svgNode('polyline', line));
                    arrowsAlong(pair[0], 90 * mpp, 5 * mpp).forEach(function (arrow) {
                        imageLayer.appendChild(svgNode('polygon', { points: pointsText(arrow), fill: color,
                            class: 'ip-flw-site-route-arrow' }));
                    });
                });
                const end = route.points[route.points.length - 1];
                const label = svgNode('text', { x: end.x, y: -end.z - 16 * mpp, class: 'ip-flw-site-route-label',
                    fill: color, 'font-size': 11 * mpp, 'stroke-width': 3 * mpp, 'text-anchor': 'middle' });
                label.textContent = (ROUTE_NAMES[route.use] || 'Vehicles') + ' to '
                    + routeTarget(route, site.roads && site.roads.items) + ', ' + Math.round(route.lengthMeters) + ' m';
                imageLayer.appendChild(label);
            });
            const property = state.propertyDraft || site.property;
            (site.areas || []).filter(area => !state.areaDraft || area.areaId !== state.areaDraft.areaId)
                .concat(state.areaDraft ? [state.areaDraft] : []).forEach(function (area) {
                    if (!area.boundary.length) return;
                    const selected = state.section === 'areas' && state.areaDraft && area.areaId === state.areaDraft.areaId;
                    const existing = area.kind === 'existing_pavement';
                    const shape = { class: 'ip-flw-site-area' + (existing ? ' ip-flw-site-area-existing' : ''),
                        points: pointsText(area.boundary), fill: existing ? 'rgb(0 229 255 / 12%)'
                            : (SURFACES[area.surface] || SURFACES.asphalt).color,
                        stroke: selected ? '#eed084' : existing ? '#00e5ff' : '#d6e1e5',
                        'stroke-width': (selected ? 2.5 : existing ? 2 : 1) * mpp, 'data-site-area': area.areaId };
                    if (existing) shape['stroke-dasharray'] = [8 * mpp, 5 * mpp].join(' ');
                    outlineLayer.appendChild(svgNode('polygon', shape));
                    const center = area.boundary.reduce((sum, p) => ({ x: sum.x + p.x / area.boundary.length,
                        z: sum.z + p.z / area.boundary.length }), { x: 0, z: 0 });
                    const label = svgNode('text', { x: center.x, y: -center.z, 'font-size': 11 * mpp,
                        class: 'ip-flw-site-edge-label', 'text-anchor': 'middle', 'pointer-events': 'none' });
                    // A traced area's label names its photo and date after a dash; the map shows just the name.
                    label.textContent = existing ? area.label.split(/\s+[—–]\s+|\s+-\s+/)[0] : area.label;
                    outlineLayer.appendChild(label);
                    if (selected && !state.readOnly && state.mode !== 'area') area.boundary.forEach((p, i) => outlineLayer.appendChild(svgNode('circle', {
                        cx: p.x, cy: -p.z, r: 5 * mpp, class: 'ip-flw-site-handle', 'data-site-area-vertex': i,
                        'stroke-width': 1.5 * mpp })));
                });
            if (property && property.boundary && property.boundary.length) {
                const boundary = property.boundary;
                outlineLayer.appendChild(svgNode('polygon', { class: 'ip-flw-site-property',
                    points: pointsText(boundary), 'stroke-width': 2 * mpp }));
                boundary.forEach(function (p, i) {
                    const q = boundary[(i + 1) % boundary.length];
                    const length = Math.hypot(q.x - p.x, q.z - p.z);
                    const text = 'E' + (i + 1) + '  ' + length.toFixed(1) + ' m';
                    // Only an edge long enough to hold its label at this zoom gets one (about 6.6 px a character):
                    // a river bank of short edges otherwise piles its labels on top of each other.
                    if (length >= text.length * 6.6 * mpp) {
                        const label = svgNode('text', { x: (p.x + q.x) / 2, y: -(p.z + q.z) / 2 - 5 * mpp,
                            class: 'ip-flw-site-edge-label', 'font-size': 11 * mpp, 'text-anchor': 'middle' });
                        label.textContent = text;
                        outlineLayer.appendChild(label);
                    }
                    if (state.section === 'property' && !state.readOnly) outlineLayer.appendChild(svgNode('circle', {
                        cx: p.x, cy: -p.z, r: 5 * mpp, class: 'ip-flw-site-handle', 'data-site-vertex': i,
                        'stroke-width': 1.5 * mpp }));
                });
                (property.entrances || []).forEach(function (entrance) {
                    outlineLayer.appendChild(svgNode('circle', { cx: entrance.x, cy: -entrance.z,
                        r: 5 * mpp, class: 'ip-flw-site-entrance', 'stroke-width': 2 * mpp }));
                });
            }
            // Reference points: features a builder can find on site, as labelled triangles (RP1, RP2, ...).
            (site.references || []).forEach(function (reference) {
                const s = 7 * mpp, x = reference.x, y = -reference.z;
                const marker = svgNode('polygon', { class: 'ip-flw-site-reference', 'stroke-width': 1.5 * mpp,
                    points: [[x, y - s], [x + s * 0.87, y + s * 0.5], [x - s * 0.87, y + s * 0.5]].map(p => p.join(',')).join(' '),
                    'data-site-reference': reference.referenceId });
                const tip = svgNode('title', {});
                tip.textContent = reference.label + ' (' + reference.source.replace('_', ' ') + ', about '
                    + reference.accuracyMeters + ' m)';
                marker.appendChild(tip);
                outlineLayer.appendChild(marker);
                const label = svgNode('text', { x: x + s * 1.1, y: y - s * 0.6, class: 'ip-flw-site-reference-label',
                    'font-size': 11 * mpp, 'stroke-width': 3 * mpp });
                label.textContent = reference.referenceId.replace(/^rp-(\d+)$/, 'RP$1').toUpperCase();
                outlineLayer.appendChild(label);
            });
            if (state.sketch.length) outlineLayer.appendChild(svgNode('polyline', {
                points: pointsText(state.sketch), class: 'ip-flw-site-sketch', 'stroke-width': 2 * mpp }));
            const posedSite = state.poseDraft ? Object.assign({}, site, { buildingPose: state.poseDraft }) : site;
            const outline = buildingOutline(state.layout, posedSite);
            outlineLayer.appendChild(svgNode('polygon', {
                class: 'ip-flw-site-building',
                points: pointsText(outline), 'data-site-pose': 'move',
                'stroke-width': 2.5 * mpp,
            }));
            if (state.section === 'building' && !state.readOnly) {
                const dimensions = planSize(state.layout);
                const pose = posedSite.buildingPose;
                const center = buildingToProperty(pose, dimensions.width / 2, dimensions.depth / 2);
                const handle = buildingToProperty(pose, dimensions.width / 2, dimensions.depth + 20 * mpp);
                outlineLayer.appendChild(svgNode('line', { x1: center.x, y1: -center.z, x2: handle.x, y2: -handle.z,
                    stroke: '#eed084', 'stroke-width': 1.5 * mpp }));
                [['move', center], ['rotate', handle]].forEach(function (entry) {
                    outlineLayer.appendChild(svgNode('circle', { cx: entry[1].x, cy: -entry[1].z, r: 7 * mpp,
                        class: 'ip-flw-site-handle', 'data-site-pose': entry[0], 'stroke-width': 2 * mpp }));
                });
            }
            const tick = 6 * mpp;
            outlineLayer.appendChild(svgNode('path', {
                class: 'ip-flw-site-origin', 'stroke-width': 1.5 * mpp,
                d: 'M' + (-tick) + ',0H' + tick + 'M0,' + (-tick) + 'V' + tick,
            }));
            const length = niceLength(110 * mpp);
            scale.hidden = false;
            scaleBar.style.width = Math.round(length / mpp) + 'px';
            scaleLabel.textContent = length >= 1000 ? (length / 1000) + ' km' : length + ' m';
            const shown = (site.overlays || []).filter(o => !state.hiddenLayers[o.layer]).map(o => o.attribution.split(' (')[0]);
            if (roads.length) shown.push('US Census roads');
            if (site.imagery && site.imagery.length) credit.textContent = 'Imagery: ' + sourceLabel(site.imagery[0])
                + (shown.length ? ' | Layers: ' + shown.join(', ') : '');
            element.classList.toggle('ip-flw-site-picking', state.mode === 'pick');
            element.classList.toggle('ip-flw-site-picking-parcel', state.mode === 'parcel');
            element.classList.toggle('ip-flw-site-tracing', state.mode === 'trace');
            renderMeasure();
            renderTraceBox();
        }

        // The box being dragged in trace mode.
        function renderTraceBox() {
            traceLayer.textContent = '';
            const box = state.traceBox;
            if (!box || state.mode !== 'trace' || !state.view) return;
            const mpp = state.view.mpp;
            traceLayer.appendChild(svgNode('rect', { class: 'ip-flw-site-trace-box',
                x: Math.min(box.start.x, box.end.x), y: -Math.max(box.start.z, box.end.z),
                width: Math.abs(box.end.x - box.start.x), height: Math.abs(box.end.z - box.start.z),
                'stroke-width': 2 * mpp, 'stroke-dasharray': [6 * mpp, 4 * mpp].join(' ') }));
        }

        async function traceAt(request) {
            state.notice = '';
            const result = await run('Tracing the pavement on the photo...', function (signal) {
                return session.traceSitePhoto(request, { signal: signal });
            });
            if (!result.ok || !result.value) return;
            const traced = result.value;
            const photo = traced.photo || {};
            state.mode = 'idle';
            state.areaDraft = Object.assign(newArea(), { kind: 'existing_pavement', surface: 'asphalt',
                label: ('Existing pavement (' + (SOURCE_NAMES[photo.source] || 'site photo')
                    + (photo.captured ? ', ' + photo.captured : '') + ')').slice(0, 120),
                boundary: traced.outline });
            state.notice = traceSummary(traced);
            renderPanel();
            renderCanvas();
        }

        function button(label, action, extra) {
            const result = node('button', Object.assign({ type: 'button', className: 'ip-flw-site-button' }, extra || {}),
                label);
            result.disabled = state.busy;
            result.addEventListener('click', action);
            return result;
        }

        function renderPanel() {
            progress.hidden = !(state.message || state.error);
            progress.textContent = state.error || state.message;
            progress.classList.toggle('ip-flw-site-progress-error', Boolean(state.error));
            element.setAttribute('aria-busy', String(state.busy));
            panel.textContent = '';
            state.metricsHost = null;
            const site = state.site;
            const folding = Boolean(site) && !state.changing && !state.readOnly;
            const collapsed = folding && (state.collapsed === null ? true : state.collapsed);
            panel.classList.toggle('ip-flw-site-panel-collapsed', collapsed);
            if (collapsed) {
                const open = button('Site', function () { state.collapsed = false; renderPanel(); },
                    { className: 'ip-flw-site-button ip-flw-site-expand', 'aria-expanded': 'false',
                        title: 'Show the site settings' });
                open.disabled = false;
                panel.appendChild(open);
                return;
            }
            if (folding) {
                const head = node('div', { className: 'ip-flw-site-head' });
                head.appendChild(node('span', { className: 'ip-flw-site-head-title' }, 'Site'));
                const hide = button('Hide', function () { state.collapsed = true; renderPanel(); },
                    { className: 'ip-flw-site-button ip-flw-site-collapse', 'aria-expanded': 'true',
                        title: 'Hide the site settings' });
                hide.disabled = false;
                head.appendChild(hide);
                panel.appendChild(head);
            }
            if (state.readOnly) {
                panel.appendChild(node('div', { className: 'ip-flw-site-title' }, 'Site proposal'));
                renderMetrics(); return;
            }
            if (site && !state.changing) {
                const tabs = node('div', { className: 'ip-flw-site-sections', role: 'group', 'aria-label': 'Site settings' });
                ['location', 'property', 'building', 'areas', 'layers'].forEach(function (section) {
                    tabs.appendChild(button(section[0].toUpperCase() + section.slice(1), function () {
                        state.section = section; state.mode = 'idle'; state.sketch = []; state.notice = '';
                        state.propertyDraft = site.property ? copy(site.property) : null;
                        state.poseDraft = copy(site.buildingPose); renderPanel(); renderCanvas();
                    }, { 'aria-pressed': String(state.section === section) }));
                });
                panel.appendChild(tabs);
                if (state.section === 'property') { renderPropertyPanel(); return; }
                if (state.section === 'building') { renderBuildingPanel(); return; }
                if (state.section === 'areas') { renderAreasPanel(); return; }
                if (state.section === 'layers') { renderLayersPanel(); return; }
            }
            if (!site || state.changing) {
                panel.appendChild(node('div', { className: 'ip-flw-site-title' },
                    site ? 'Move this layout to another site' : 'Place this layout on a real site'));
                const address = node('input', { type: 'text', className: 'ip-flw-site-input',
                    'aria-label': 'Street address', placeholder: 'Street address, city, state' });
                address.value = state.address;
                address.addEventListener('input', function () { state.address = address.value; });
                const find = button('Find', function () { findAddress(address.value); });
                address.addEventListener('keydown', function (event) {
                    if (event.key === 'Enter') findAddress(address.value);
                });
                panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'US street address'));
                const row = node('div', { className: 'ip-flw-site-row' });
                row.appendChild(address);
                row.appendChild(find);
                panel.appendChild(row);
                state.matches.forEach(function (match) {
                    panel.appendChild(button(match.label, function () {
                        place(match.latitude, match.longitude, 'address', match.label);
                    }, { className: 'ip-flw-site-button ip-flw-site-match' }));
                });
                const coordinates = node('input', { type: 'text', className: 'ip-flw-site-input',
                    'aria-label': 'Latitude and longitude', placeholder: '44.9778, -93.2650' });
                coordinates.value = state.coordinates;
                coordinates.addEventListener('input', function () { state.coordinates = coordinates.value; });
                const placeAt = button('Place', function () {
                    const point = parseCoordinates(coordinates.value);
                    if (!point) {
                        state.error = 'Enter latitude and longitude in degrees, for example 44.9778, -93.2650.';
                        renderPanel();
                        return;
                    }
                    place(point.latitude, point.longitude, 'coordinates', '');
                });
                panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'Or latitude, longitude'));
                const row2 = node('div', { className: 'ip-flw-site-row' });
                row2.appendChild(coordinates);
                row2.appendChild(placeAt);
                panel.appendChild(row2);
                const area = node('select', { className: 'ip-flw-site-input', 'aria-label': 'Photo area' });
                AREA_SIZES.forEach(function (option) {
                    const choice = node('option', { value: String(option[0]) }, option[1]);
                    if (option[0] === state.halfSize) choice.selected = true;
                    area.appendChild(choice);
                });
                area.addEventListener('change', function () { state.halfSize = Number(area.value) || 250; });
                panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'Aerial photo area'));
                panel.appendChild(area);
                panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'Photo source'));
                panel.appendChild(photoSourceSelect());
                if (site) panel.appendChild(button('Cancel', function () {
                    state.changing = false; state.matches = []; state.error = ''; renderPanel();
                }));
                panel.appendChild(node('p', { className: 'ip-flw-site-note' },
                    'Addresses are looked up by the US Census geocoder. Standard photos come from USGS NAIP '
                    + '(US only); in the 7-county Twin Cities metro a sharper, leaf-off 2025 photo '
                    + '(Metropolitan Council / MnGeo) is available. Both are public domain. '
                    + 'Imagery is context, not a survey.'));
            } else {
                panel.appendChild(node('div', { className: 'ip-flw-site-title' }, 'Site'));
                const reference = site.georeference;
                if (reference.label) panel.appendChild(node('div', { className: 'ip-flw-site-place' }, reference.label));
                panel.appendChild(node('div', { className: 'ip-flw-site-coordinates' },
                    reference.originLatitude.toFixed(6) + ', ' + reference.originLongitude.toFixed(6)));
                panel.appendChild(node('div', { className: 'ip-flw-site-note' }, site.imagery && site.imagery.length
                    ? sourceLabel(site.imagery[0]) : 'No aerial photo yet.'));
                if (state.notice) panel.appendChild(node('p', { className: 'ip-flw-site-note' }, state.notice));
                if (state.mode === 'pick') {
                    panel.appendChild(node('p', { className: 'ip-flw-site-hint' },
                        'Click the photo where the building\'s centre should be. Esc cancels.'));
                    panel.appendChild(button('Cancel', function () { setMode('idle'); }));
                } else {
                    const imagery = site.imagery && site.imagery.length;
                    const moveButton = button('Move building on the photo', function () { setMode('pick'); });
                    moveButton.disabled = state.busy || !imagery;
                    panel.appendChild(moveButton);
                    panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'Photo source'));
                    panel.appendChild(photoSourceSelect());
                    panel.appendChild(button(imagery ? 'New photo here' : 'Fetch a photo', refreshPhoto));
                    panel.appendChild(button('Change location', function () {
                        state.changing = true; state.error = ''; renderPanel();
                    }));
                    panel.appendChild(button(state.confirmRemove ? 'Click again to remove' : 'Remove site', function () {
                        if (!state.confirmRemove) {
                            state.confirmRemove = true;
                            renderPanel();
                            return;
                        }
                        state.confirmRemove = false;
                        run('Removing the site...', function () { return session.setSiteContext(null); });
                    }, { className: 'ip-flw-site-button ip-flw-site-danger' }));
                    if (imagery) {
                        const slider = node('input', { type: 'range', min: '20', max: '100',
                            className: 'ip-flw-site-opacity', 'aria-label': 'Photo opacity' });
                        slider.value = String(Math.round(state.opacity * 100));
                        slider.addEventListener('input', function () {
                            state.opacity = Number(slider.value) / 100;
                            renderCanvas();
                        });
                        panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'Photo'));
                        panel.appendChild(slider);
                    }
                }
            }
            if (state.message) panel.appendChild(node('p', { className: 'ip-flw-site-status', role: 'status' },
                state.message));
            if (state.error) panel.appendChild(node('p', { className: 'ip-flw-site-error', role: 'alert' },
                state.error));
        }

        function photoSourceSelect() {
            const select = node('select', { className: 'ip-flw-site-input', 'aria-label': 'Photo source' });
            PHOTO_SOURCES.forEach(function (option) {
                const choice = node('option', { value: option[0] }, option[1]);
                if (option[0] === state.photoSource) choice.selected = true;
                select.appendChild(choice);
            });
            select.disabled = state.busy;
            select.addEventListener('change', function () { state.photoSource = select.value || 'standard'; });
            return select;
        }

        function setMode(mode) {
            if (mode !== 'measure') { state.measure = []; state.measureHover = null; }
            state.mode = mode;
            renderPanel();
            renderCanvas();
        }

        function numberField(label, value, change, min, max) {
            const field = node('label', { className: 'ip-flw-site-label' }, label);
            const input = node('input', { type: 'number', step: '0.1', min: min, max: max,
                className: 'ip-flw-site-input', 'aria-label': label });
            input.value = String(value); input.disabled = state.busy;
            input.addEventListener('input', function () { change(input.value === '' ? NaN : Number(input.value)); });
            field.appendChild(input); panel.appendChild(field); return input;
        }

        function renderMetrics() {
            const target = state.metricsHost || node('div', { className: 'ip-flw-site-metrics' });
            if (!state.metricsHost) { state.metricsHost = target; panel.appendChild(target); }
            target.textContent = '';
            if (state.analysisError) target.appendChild(node('p', { className: 'ip-flw-site-error' }, state.analysisError));
            const analysis = state.analysis;
            if (!analysis) return;
            if (analysis.metrics) {
                const m = analysis.metrics;
                target.appendChild(node('p', { className: 'ip-flw-site-note' },
                    m.lotAreaSquareMeters.toFixed(1) + ' sq m / ' + m.lotAreaAcres.toFixed(2) + ' acres; building coverage ' +
                    m.buildingCoveragePercent.toFixed(1) + '%'));
                const distances = node('details', {});
                distances.appendChild(node('summary', {}, 'Building clearance by edge'));
                m.edges.forEach(function (edge) { distances.appendChild(node('div', { className: 'ip-flw-site-note' },
                    'E' + (edge.edgeIndex + 1) + ' ' + edge.kind + ': ' + formatMeters(edge.buildingDistanceMeters))); });
                target.appendChild(distances);
                if (m.pavedAreaSquareMeters !== undefined) target.appendChild(node('p', { className: 'ip-flw-site-note' },
                    'Paved area: ' + m.pavedAreaSquareMeters.toFixed(1) + ' sq m'));
                (m.areas || []).forEach(area => target.appendChild(node('div', { className: 'ip-flw-site-note' },
                    area.label + ': ' + area.areaSquareMeters.toFixed(1) + ' sq m')));
            }
            (analysis.findings || []).forEach(function (finding) {
                target.appendChild(node('p', { className: 'ip-flw-site-finding', 'data-site-finding': finding.code }, finding.message));
            });
            target.appendChild(node('p', { className: 'ip-flw-site-note' }, 'User-supplied boundary and setbacks. Not a survey or compliance review.'));
        }

        function renderBuildingPanel() {
            const pose = state.poseDraft || (state.poseDraft = copy(state.site.buildingPose));
            numberField('Building X (m)', pose.x, value => { pose.x = value; renderCanvas(); }, -5000, 5000);
            numberField('Building Z (m)', pose.z, value => { pose.z = value; renderCanvas(); }, -5000, 5000);
            numberField('True bearing (degrees)', pose.bearingDegrees, value => { pose.bearingDegrees = value; renderCanvas(); }, -360, 360);
            panel.appendChild(button('Apply building position', commitPose));
            if (typeof options.onOpenWalls === 'function') panel.appendChild(button('Walls and dock openings', options.onOpenWalls));
            renderMetrics();
        }

        function newArea() {
            return { areaId: 'area-' + (root.crypto && root.crypto.randomUUID ? root.crypto.randomUUID() : Date.now()),
                label: 'Outdoor area', kind: 'parking', surface: 'asphalt', boundary: [] };
        }

        function renderAreasPanel() {
            const area = state.areaDraft || (state.areaDraft = newArea());
            const select = node('select', { className: 'ip-flw-site-input', 'aria-label': 'Outdoor area' });
            select.appendChild(node('option', { value: '' }, 'New area'));
            (state.site.areas || []).forEach(item => select.appendChild(node('option', { value: item.areaId }, item.label)));
            select.value = (state.site.areas || []).some(item => item.areaId === area.areaId) ? area.areaId : '';
            select.addEventListener('change', function () {
                state.areaDraft = copy((state.site.areas || []).find(item => item.areaId === select.value) || newArea());
                state.mode = 'idle'; state.sketch = []; renderPanel(); renderCanvas();
            });
            panel.appendChild(select);
            const name = node('input', { type: 'text', maxlength: 120, className: 'ip-flw-site-input', 'aria-label': 'Area name' });
            name.value = area.label; name.addEventListener('input', () => { area.label = name.value; renderCanvas(); }); panel.appendChild(name);
            [['Area kind', 'kind', AREA_KINDS], ['Area surface', 'surface', Object.keys(SURFACES)]].forEach(function (entry) {
                const input = node('select', { className: 'ip-flw-site-input', 'aria-label': entry[0] });
                entry[2].forEach(value => input.appendChild(node('option', { value: value }, kindLabel(value))));
                input.value = area[entry[1]];
                input.addEventListener('change', function () {
                    area[entry[1]] = input.value;
                    if (entry[1] === 'kind') {
                        area.surface = input.value === 'landscape' ? 'grass' : input.value === 'sidewalk' ? 'concrete' : 'asphalt';
                        renderPanel();
                    }
                    renderCanvas();
                }); panel.appendChild(input);
            });
            panel.appendChild(button(state.mode === 'area' ? 'Cancel drawing' : 'Draw area', function () {
                state.sketch = []; setMode(state.mode === 'area' ? 'idle' : 'area');
            }));
            const photo = state.site.imagery && state.site.imagery[0];
            const trace = button(state.mode === 'trace' ? 'Cancel tracing' : 'Trace pavement on the photo', function () {
                state.sketch = []; state.traceBox = null; state.notice = '';
                setMode(state.mode === 'trace' ? 'idle' : 'trace');
            });
            trace.disabled = state.busy || !photo;
            panel.appendChild(trace);
            if (state.mode === 'trace') panel.appendChild(node('p', { className: 'ip-flw-site-hint' },
                'Click a paved area on the photo, or drag a box around just the part you mean. Esc cancels.'));
            if (state.notice) panel.appendChild(node('p', { className: 'ip-flw-site-note' }, state.notice));
            if (state.mode === 'area') {
                const finish = button('Finish area', finishBoundary); finish.disabled = state.busy || state.sketch.length < 3;
                panel.appendChild(finish);
            }
            const coordinates = node('textarea', { className: 'ip-flw-site-input ip-flw-site-vertices', rows: 5,
                'aria-label': 'Area vertices X, Z (m)', spellcheck: 'false' });
            coordinates.value = area.boundary.map(p => p.x + ', ' + p.z).join('\n'); panel.appendChild(coordinates);
            panel.appendChild(button('Apply area', async function () {
                try { area.boundary = parseBoundary(coordinates.value); await commitArea(); }
                catch (error) { state.error = error.message; renderPanel(); }
            }));
            if ((state.site.areas || []).some(item => item.areaId === area.areaId)) panel.appendChild(button('Delete area', async function () {
                const result = await run('Deleting outdoor area...', () => session.deleteSiteArea(area.areaId));
                if (result.ok) state.areaDraft = newArea(); renderPanel(); renderCanvas();
            }, { className: 'ip-flw-site-button ip-flw-site-danger' }));
            renderMetrics();
        }

        async function commitArea() {
            const result = await run('Updating outdoor area...', () => session.upsertSiteArea(copy(state.areaDraft)));
            if (result.ok) { state.mode = 'idle'; state.sketch = []; }
            renderPanel(); renderCanvas();
        }

        function renderPropertyPanel() {
            panel.appendChild(button(state.mode === 'boundary' ? 'Cancel drawing' : 'Draw boundary', function () {
                state.sketch = []; setMode(state.mode === 'boundary' ? 'idle' : 'boundary');
            }));
            const photo = state.site.imagery && state.site.imagery[0];
            const parcel = button(state.mode === 'parcel' ? 'Cancel parcel pick' : 'Use county parcel', function () {
                state.sketch = []; setMode(state.mode === 'parcel' ? 'idle' : 'parcel');
            });
            parcel.disabled = state.busy || !photo || state.readOnly;
            panel.appendChild(parcel);
            if (state.mode === 'parcel') panel.appendChild(node('p', { className: 'ip-flw-site-hint' },
                'Click inside the lot on the photo. Minnesota counties that publish open parcel data. Esc cancels.'));
            if (state.notice) panel.appendChild(node('p', { className: 'ip-flw-site-note' }, state.notice));
            if (state.mode === 'boundary') {
                panel.appendChild(node('div', { className: 'ip-flw-site-note' }, state.sketch.length + ' vertices'));
                const finish = button('Finish boundary', finishBoundary); finish.disabled = state.busy || state.sketch.length < 3;
                panel.appendChild(finish);
            }
            const property = state.propertyDraft;
            const coordinates = node('textarea', { className: 'ip-flw-site-input ip-flw-site-vertices',
                rows: 5, 'aria-label': 'Boundary vertices X, Z (m)', spellcheck: 'false' });
            coordinates.value = property ? property.boundary.map(p => p.x + ', ' + p.z).join('\n') : '';
            panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'Boundary vertices X, Z (m)'));
            panel.appendChild(coordinates);
            panel.appendChild(button('Apply boundary coordinates', async function () {
                try {
                    const boundary = parseBoundary(coordinates.value);
                    if (property && boundary.length !== property.boundary.length &&
                        ((property.entrances || []).length || (property.streetEdges || []).length || (property.rearEdges || []).length)) {
                        if (!root.confirm('Changing the vertex count clears edge assignments and entrances. Continue?')) return;
                    }
                    state.propertyDraft = property ? replaceBoundary(property, boundary) : newProperty(boundary, 'user_coordinates');
                    state.propertyDraft.source = 'user_coordinates'; await commitProperty();
                } catch (error) { state.error = error.message; renderPanel(); }
            }));
            if (property) {
                ['street', 'side', 'rear'].forEach(function (kind) {
                    numberField(kind[0].toUpperCase() + kind.slice(1) + ' setback (m)', property.setbacksMeters[kind],
                        value => { property.setbacksMeters[kind] = value; }, 0, 500);
                });
                property.boundary.forEach(function (p, i) {
                    const q = property.boundary[(i + 1) % property.boundary.length];
                    const row = node('label', { className: 'ip-flw-site-edge-row' },
                        'E' + (i + 1) + '  ' + formatMeters(Math.hypot(q.x - p.x, q.z - p.z)));
                    const select = node('select', { 'aria-label': 'Edge ' + (i + 1) + ' type', className: 'ip-flw-site-input' });
                    const current = property.streetEdges.includes(i) ? 'street' : property.rearEdges.includes(i) ? 'rear' : 'side';
                    ['side', 'street', 'rear'].forEach(kind => { const option = node('option', { value: kind }, kind);
                        option.selected = kind === current; select.appendChild(option); });
                    select.addEventListener('change', function () {
                        property.streetEdges = property.streetEdges.filter(index => index !== i);
                        property.rearEdges = property.rearEdges.filter(index => index !== i);
                        if (select.value !== 'side') property[select.value + 'Edges'].push(i);
                    });
                    row.appendChild(select); panel.appendChild(row);
                    const length = node('input', { type: 'number', min: 0.1, step: 0.1, className: 'ip-flw-site-input',
                        'aria-label': 'Edge ' + (i + 1) + ' length (m)' });
                    length.value = Math.hypot(q.x - p.x, q.z - p.z).toFixed(3);
                    length.addEventListener('change', function () {
                        const oldLength = Math.hypot(q.x - p.x, q.z - p.z), nextLength = Number(length.value);
                        if (!(nextLength > 0) || !(oldLength > 0)) return;
                        const boundary = copy(property.boundary);
                        boundary[(i + 1) % boundary.length] = { x: p.x + (q.x - p.x) * nextLength / oldLength,
                            z: p.z + (q.z - p.z) * nextLength / oldLength };
                        Object.assign(property, replaceBoundary(property, boundary));
                        renderPanel(); renderCanvas();
                    });
                    panel.appendChild(length);
                });
                panel.appendChild(button('Apply setbacks and edge types', commitProperty));
                const entranceSection = node('details', {});
                entranceSection.appendChild(node('summary', {}, 'Entrances'));
                const edge = node('select', { className: 'ip-flw-site-input', 'aria-label': 'Entrance edge' });
                property.boundary.forEach((_, i) => edge.appendChild(node('option', { value: i }, 'Edge ' + (i + 1))));
                const use = node('select', { className: 'ip-flw-site-input', 'aria-label': 'Entrance use' });
                ['shared', 'trucks', 'cars', 'pedestrians'].forEach(kind => use.appendChild(node('option', { value: kind }, kind)));
                const width = node('input', { type: 'number', min: 0.5, max: 50, step: 0.5,
                    className: 'ip-flw-site-input', 'aria-label': 'Entrance width (m)' }); width.value = '4';
                entranceSection.appendChild(edge); entranceSection.appendChild(use); entranceSection.appendChild(width);
                const position = node('input', { type: 'number', min: 0, max: 100, step: 1,
                    className: 'ip-flw-site-input', 'aria-label': 'Entrance position along edge (%)' }); position.value = '50';
                entranceSection.appendChild(position);
                entranceSection.appendChild(button('Add entrance', async function () {
                    const i = Number(edge.value), a = property.boundary[i], b = property.boundary[(i + 1) % property.boundary.length];
                    const fraction = Number(position.value) / 100;
                    if (!(fraction >= 0 && fraction <= 1)) { state.error = 'Entrance position must be between 0 and 100%.'; renderPanel(); return; }
                    property.entrances.push({ entranceId: 'entrance-' + Date.now(), edgeIndex: i,
                        x: a.x + fraction * (b.x - a.x), z: a.z + fraction * (b.z - a.z), use: use.value, widthMeters: Number(width.value) });
                    await commitProperty();
                }));
                (property.entrances || []).forEach(function (entrance) {
                    const row = node('div', { className: 'ip-flw-site-edge-row' },
                        'E' + (entrance.edgeIndex + 1) + ' ' + entrance.use + ' ' + entrance.widthMeters + ' m');
                    row.appendChild(button('Remove', function () {
                        property.entrances = property.entrances.filter(item => item.entranceId !== entrance.entranceId);
                        commitProperty();
                    }, { 'aria-label': 'Remove entrance ' + entrance.entranceId }));
                    entranceSection.appendChild(row);
                });
                panel.appendChild(entranceSection);
            }
            renderMetrics();
        }

        function newProperty(boundary, source) {
            return { boundary: copy(boundary), source: source, setbacksMeters: { street: 0, side: 0, rear: 0 },
                streetEdges: [], rearEdges: [], entrances: [] };
        }

        async function commitProperty() {
            const result = await run('Updating property...', () => session.setSiteContext(
                Object.assign({}, state.site, { property: copy(state.propertyDraft) })));
            if (result.ok) { state.mode = 'idle'; state.sketch = []; }
            renderPanel(); renderCanvas();
        }

        async function pickParcel(point) {
            const site = state.site;
            const photo = site.imagery && site.imagery[0];
            const target = photo && latLonAt(photo, point.x, point.z);
            if (!target) { state.error = 'Click inside the photo.'; renderPanel(); return; }
            setMode('idle');
            const found = await run('Looking up the county parcel...', function (signal) {
                return session.fetchSiteParcel({ latitude: target.latitude, longitude: target.longitude,
                    originLatitude: site.georeference.originLatitude, originLongitude: site.georeference.originLongitude },
                    { signal: signal });
            });
            if (!found.ok || !found.value) return;
            const parcel = found.value;
            const property = state.site.property;
            if (property && ((property.entrances || []).length || (property.streetEdges || []).length
                || (property.rearEdges || []).length)
                && !root.confirm('The parcel replaces the boundary and clears edge types and entrances. Continue?')) return;
            const draft = newProperty(parcel.boundary, 'county_parcel');
            if (property) draft.setbacksMeters = copy(property.setbacksMeters);
            draft.sourceLabel = (parcel.county + ' County parcel ' + parcel.parcelId).trim().slice(0, 160);
            state.propertyDraft = draft;
            const saved = await run('Applying the parcel...', () => session.setSiteContext(
                Object.assign({}, state.site, { property: copy(draft) }), 'Use county parcel'));
            if (!saved.ok) return;
            state.notice = 'Parcel ' + parcel.parcelId + (parcel.legal ? ' (' + parcel.legal + ')' : '')
                + (parcel.acres ? ', ' + Number(parcel.acres).toFixed(2) + ' acres' : '')
                + '. From the county tax map, not a survey; simplified from ' + parcel.simplified.fromVertices
                + ' to ' + parcel.simplified.toVertices + ' points. Mark the street edge and entrances again.';
            state.collapsed = true;  // the property is in: fold the pane away (its note waits inside)
            renderPanel(); renderCanvas();
        }

        function renderLayersPanel() {
            const site = state.site;
            const photo = site.imagery && site.imagery[0];
            const overlays = site.overlays || [];
            panel.appendChild(node('div', { className: 'ip-flw-site-title' }, 'Public reference layers'));
            function layerRow(key, title, text, available) {
                const line = node('label', { className: 'ip-flw-site-layer-row' });
                const box = node('input', { type: 'checkbox', 'aria-label': 'Show ' + title });
                box.checked = available && !state.hiddenLayers[key];
                box.disabled = !available;
                box.addEventListener('change', function () { state.hiddenLayers[key] = !box.checked; renderCanvas(); });
                line.appendChild(box);
                line.appendChild(node('span', { className: 'ip-flw-site-layer-name' }, title));
                line.appendChild(node('span', { className: 'ip-flw-site-layer-state' }, text));
                panel.appendChild(line);
            }
            layerRow('roads', 'Roads', site.roads ? site.roads.items.length + ' from the US Census, ' + site.roads.fetched
                : 'not loaded', Boolean(site.roads));
            const routeCount = (site.routes || []).filter(route => route.mainRoad).length;
            layerRow('routes', 'Routes', routeCount ? routeCount + ' to the main road'
                : 'none: needs a truck or car entrance and roads', Boolean(routeCount));
            LAYER_ROWS.forEach(function (row) {
                const overlay = overlays.find(item => item.layer === row[0]);
                layerRow(row[0], row[1], overlay ? (overlay.detail || row[2]) + ', ' + overlay.captured : 'not loaded',
                    Boolean(overlay));
            });
            const load = button(overlays.length || site.roads ? 'Reload layers for this photo' : 'Load layers for this photo',
                loadLayers);
            load.disabled = state.busy || !photo || state.readOnly;
            panel.appendChild(load);
            if (overlays.length) {
                const slider = node('input', { type: 'range', min: '20', max: '100', className: 'ip-flw-site-opacity',
                    'aria-label': 'Layer opacity' });
                slider.value = String(Math.round(state.overlayOpacity * 100));
                slider.addEventListener('input', function () { state.overlayOpacity = Number(slider.value) / 100; renderCanvas(); });
                panel.appendChild(node('label', { className: 'ip-flw-site-label' }, 'Layer opacity'));
                panel.appendChild(slider);
            }
            const check = button('Check building, lot and areas', checkLayers);
            check.disabled = state.busy || state.readOnly;
            panel.appendChild(check);
            renderLayerChecks();
            panel.appendChild(node('p', { className: 'ip-flw-site-note' }, 'Public reference data from the US Census, FEMA, '
                + 'USFWS, USGS and USDA, drawn by each agency\'s service. Road lines are centerlines; widths are not '
                + 'included. Not a survey, permit or compliance review.'));
        }

        function renderLayerChecks() {
            const checks = state.site.layerChecks;
            if (!checks) return;
            const stale = ((state.analysis && state.analysis.findings) || []).some(f => f.code === 'site_layer_checks_stale');
            panel.appendChild(node('p', { className: stale ? 'ip-flw-site-error' : 'ip-flw-site-note' },
                'Checked ' + checks.checkedAt + (stale ? ' for an earlier layout. Check again.' : '.')));
            const targets = [];
            checks.results.forEach(function (result) {
                let group = targets.find(item => item.label === result.targetLabel);
                if (!group) { group = { label: result.targetLabel, results: [] }; targets.push(group); }
                group.results.push(result);
            });
            targets.forEach(function (group) {
                const box = node('div', { className: 'ip-flw-site-check-group' });
                box.appendChild(node('div', { className: 'ip-flw-site-check-target' }, group.label));
                LAYER_ROWS.forEach(function (row) {
                    const result = group.results.find(item => item.layer === row[0]);
                    if (!result) return;
                    let text = result.items.map(item => item.label).join('; ');
                    if (result.metric) text = (text ? text + '. ' : '') + 'Ground ' + result.metric.minElevationMeters.toFixed(1)
                        + ' to ' + result.metric.maxElevationMeters.toFixed(1) + ' m';
                    const worst = result.items.some(i => i.severity === 'high') ? 'high'
                        : result.items.some(i => i.severity === 'moderate') ? 'moderate' : 'none';
                    box.appendChild(node('div', { className: 'ip-flw-site-check-item ip-flw-site-check-' + worst },
                        LAYER_NAMES[row[0]] + ': ' + (text || 'none found')));
                });
                panel.appendChild(box);
            });
            checks.errors.forEach(error => panel.appendChild(node('p', { className: 'ip-flw-site-error' }, error.message)));
        }

        async function loadLayers() {
            const photo = state.site.imagery && state.site.imagery[0];
            if (!photo) return;
            const errors = [];
            const result = await run('Loading roads, flood, wetland, contour and soil layers...', async function (signal, assertCurrent) {
                const roadsJob = typeof session.fetchSiteRoads === 'function'
                    ? session.fetchSiteRoads({ geoBounds: photo.geoBounds }, { signal: signal }).catch(function (error) {
                        if (signal.aborted) throw error;
                        errors.push('Roads: ' + ((error.body && error.body.error && error.body.error.message) || error.message));
                        return null;
                    }) : Promise.resolve(null);
                const loaded = await Promise.all([Promise.all(LAYER_ROWS.map(row => session.fetchSiteOverlay({ layer: row[0],
                    geoBounds: photo.geoBounds, widthPixels: photo.widthPixels, heightPixels: photo.heightPixels },
                    { signal: signal }).catch(function (error) {
                    if (signal.aborted) throw error;
                    errors.push(row[1] + ': ' + ((error.body && error.body.error && error.body.error.message) || error.message));
                    return null;
                }))), roadsJob]);
                const fetched = loaded[0];
                const roads = loaded[1];
                assertCurrent();
                if (!fetched.some(Boolean) && !roads) throw new Error('No layer could be loaded. ' + errors.join(' '));
                const kept = (state.site.overlays || []).filter(o => !fetched.some(f => f && f.layer === o.layer));
                const next = Object.assign({}, state.site, { overlays: kept.concat(fetched.filter(Boolean)) });
                if (roads) next.roads = roads;
                return session.setSiteContext(next, 'Load reference layers');
            });
            if (result.ok && errors.length) { state.error = 'Some layers did not load. ' + errors.join(' '); renderPanel(); }
        }

        async function checkLayers() {
            await run('Checking flood zones, wetlands, soils and ground...', async function (signal, assertCurrent) {
                const checks = await session.checkSiteLayers({ signal: signal });
                assertCurrent();
                return session.setSiteContext(Object.assign({}, state.site, { layerChecks: checks }), 'Check site layers');
            });
        }

        async function commitPose() {
            await run('Positioning building...', () => session.setBuildingPose(copy(state.poseDraft)));
            renderPanel(); renderCanvas();
        }

        async function finishBoundary() {
            if (state.sketch.length < 3) return;
            if (state.mode === 'area') { state.areaDraft.boundary = copy(state.sketch); await commitArea(); return; }
            if (state.site.property && !root.confirm('Replace the property boundary and clear its edge assignments and entrances?')) return;
            state.propertyDraft = newProperty(state.sketch, 'user_drawn');
            await commitProperty();
        }

        async function refreshAnalysis() {
            if (state.analysisRequest) state.analysisRequest.abort();
            state.analysis = null; state.analysisError = '';
            if (!state.site || typeof session.analyzeSiteContext !== 'function') return;
            const controller = new AbortController(); state.analysisRequest = controller;
            try {
                const result = await session.analyzeSiteContext({ signal: controller.signal }, state.layout);
                if (!state.destroyed && state.analysisRequest === controller) state.analysis = result;
            } catch (error) {
                if (!controller.signal.aborted) state.analysisError = 'Site analysis unavailable: ' + error.message;
            }
            if (!state.destroyed && state.analysisRequest === controller && state.visible && state.metricsHost) renderMetrics();
        }

        async function run(message, action) {
            if (state.busy || state.destroyed || state.readOnly) return { ok: false, value: null };
            const controller = new AbortController();
            state.request = controller;
            const assertCurrent = function () {
                if (state.destroyed || state.request !== controller || controller.signal.aborted) {
                    throw new Error('The site request was cancelled.');
                }
            };
            state.busy = true;
            state.message = message;
            state.error = '';
            renderPanel();
            try {
                const value = await action(controller.signal, assertCurrent);
                assertCurrent();
                return { ok: true, value: value };
            } catch (error) {
                if (state.request !== controller || state.destroyed) return { ok: false, value: null };
                state.error = (error && (error.body && error.body.error && error.body.error.message))
                    || (error && error.message) || 'That did not work.';
                return { ok: false, value: null };
            } finally {
                if (state.request === controller && !state.destroyed) {
                    state.request = null;
                    state.busy = false;
                    state.message = '';
                    renderPanel();
                }
            }
        }

        async function findAddress(text) {
            if (state.busy || state.destroyed) return;
            const query = String(text || '').trim();
            if (query.length < 3) {
                state.error = 'Enter a street address.';
                renderPanel();
                return;
            }
            state.matches = [];
            const result = await run('Looking up the address...', function (signal) {
                return session.geocodeAddress(query, { signal: signal });
            });
            if (!result.ok) return;
            state.matches = (result.value && result.value.matches) || [];
            if (state.matches.length === 1) {
                const match = state.matches[0];
                await place(match.latitude, match.longitude, 'address', match.label);
                return;
            }
            if (!state.matches.length) state.error = 'No US address matched. Check the spelling, or enter coordinates.';
            renderPanel();
        }

        async function place(latitude, longitude, placedBy, label) {
            if (state.site && (state.site.property || (state.site.areas || []).length) &&
                !root.confirm('Changing location replaces the property boundary, entrances, building pose and outdoor areas. Continue?')) return;
            const georeference = { originLatitude: latitude, originLongitude: longitude, placedBy: placedBy, label: label };
            const flight = startFlight(latitude, longitude);
            let photo = null;
            state.notice = '';
            const placed = await run('Fetching the aerial photo...', async function (signal, assertCurrent) {
                photo = await session.fetchSiteImagery({ latitude: latitude, longitude: longitude,
                    halfSizeMeters: state.halfSize, source: state.photoSource }, { signal: signal });
                assertCurrent();
                const roads = await roadsFor(photo, signal);
                assertCurrent();
                const context = { version: 1, georeference: georeference, imagery: [imageFields(photo)] };
                if (roads) context.roads = roads;
                return session.setSiteContext(context);
            });
            if (placed.ok) {
                state.changing = false;
                state.matches = [];
                state.collapsed = true;  // the place is in: fold the pane away so the photo has the room
                renderPanel();
            }
            if (flight) landFlight(flight, placed.ok ? photo : null);
        }

        // The globe turns to the new place and dives in while the photo loads. Presentation only:
        // without WebGL, the library or motion, the photo simply appears as before.
        function startFlight(latitude, longitude) {
            const siteId = state.layout && state.layout.association && state.layout.association.siteId;
            if (!globe || !siteId || !state.visible || state.busy || state.readOnly || !globe.wanted(documentRef)) return null;
            if (state.flight) state.flight.cancel();
            const view = size();
            const half = state.halfSize;
            const landing = viewForBox({ minX: -half, maxX: half, minZ: -half, maxZ: half }, view);
            const reference = state.site && state.site.georeference;
            const flight = globe.createFlight({
                document: documentRef, host: element,
                tileUrl: '/api/facility-site-globe/' + encodeURIComponent(siteId) + '/{z}/{x}/{y}.jpg',
                onEnd: function () {
                    if (state.flight !== flight) return;
                    state.flight = null;
                    element.classList.remove('ip-flw-site-flying');
                },
            });
            state.flight = flight;
            element.classList.add('ip-flw-site-flying');
            // The server fetches the dive's tiles in parallel; the browser alone would fall behind.
            const ready = typeof session.prefetchSiteGlobe === 'function'
                ? session.prefetchSiteGlobe({ latitude: latitude, longitude: longitude }).catch(function () {}) : null;
            flight.fly({
                latitude: latitude, longitude: longitude, padLeft: panelWidth(view.width), ready: ready,
                zoom: globe.zoomForMetersPerPixel(landing.mpp, latitude),
                previous: reference ? { latitude: reference.originLatitude, longitude: reference.originLongitude } : null,
            });
            return flight;
        }

        // Where the Site view looks now: the centre of the area beside the panel, and its scale.
        function flightCamera() {
            const site = state.site;
            if (!site || !site.imagery || !site.imagery.length) return null;
            if (!state.view) fitView();
            const point = geoPoint(site.imagery[0], state.view.cx + panelWidth(size().width) * state.view.mpp / 2,
                state.view.cz);
            return { latitude: point.latitude, longitude: point.longitude, metersPerPixel: state.view.mpp };
        }

        // The globe stays until the photo is drawn beneath it, then settles on the same framing and fades.
        function landFlight(flight, photo) {
            if (!photo) { flight.land(null); return; }
            const later = typeof root.requestAnimationFrame === 'function'
                ? root.requestAnimationFrame.bind(root) : function (callback) { setTimeout(callback, 16); };
            later(function () { flight.land(firstImageId(state.site) === photo.imageId ? flightCamera() : null); });
        }

        // Roads come with every new photo. A failure is reported; it never stops the photo.
        async function roadsFor(photo, signal) {
            if (typeof session.fetchSiteRoads !== 'function') return null;
            try {
                return await session.fetchSiteRoads({ geoBounds: photo.geoBounds }, { signal: signal });
            } catch (error) {
                if (signal.aborted) throw error;
                state.notice = 'Roads did not load (' + ((error.body && error.body.error && error.body.error.message)
                    || error.message) + '). Load them from Layers.';
                return null;
            }
        }

        async function refreshPhoto() {
            const site = state.site;
            const reference = site.georeference;
            state.notice = '';
            await run('Fetching a new aerial photo...', async function (signal, assertCurrent) {
                const photo = await session.fetchSiteImagery({ latitude: reference.originLatitude,
                    longitude: reference.originLongitude, halfSizeMeters: state.halfSize,
                    source: state.photoSource }, { signal: signal });
                assertCurrent();
                const roads = await roadsFor(photo, signal);
                assertCurrent();
                return session.setSiteContext(Object.assign({}, site, { imagery: [imageFields(photo)] },
                    roads ? { roads: roads } : {}));
            });
        }

        async function moveBuildingTo(point) {
            const dimensions = planSize(state.layout);
            const pose = state.site.buildingPose;
            const offset = buildingToProperty({ x: 0, z: 0, bearingDegrees: pose.bearingDegrees }, dimensions.width / 2, dimensions.depth / 2);
            state.poseDraft = { x: point.x - offset.x, z: point.z - offset.z, bearingDegrees: pose.bearingDegrees };
            setMode('idle');
            await commitPose();
        }

        element.addEventListener('wheel', function (event) {
            if (!state.site || !state.view || panel.contains(event.target)) return;
            event.preventDefault();
            const before = screenToProperty(event.clientX, event.clientY);
            const factor = Math.exp(Math.max(-1, Math.min(1, event.deltaY / 400)));
            state.view.mpp = Math.min(MAX_METERS_PER_PIXEL, Math.max(MIN_METERS_PER_PIXEL, state.view.mpp * factor));
            const after = screenToProperty(event.clientX, event.clientY);
            state.view.cx += before.x - after.x;
            state.view.cz += before.z - after.z;
            renderCanvas();
        }, { passive: false });

        svg.addEventListener('pointerdown', function (event) {
            if (!state.site || !state.view || state.busy || event.button !== 0) return;
            state.drag = { x: event.clientX, y: event.clientY, cx: state.view.cx, cz: state.view.cz, moved: false };
            if (state.mode === 'trace' && !state.readOnly) {
                state.drag.kind = 'trace'; state.drag.start = screenToProperty(event.clientX, event.clientY);
                if (typeof svg.setPointerCapture === 'function') svg.setPointerCapture(event.pointerId);
                return;
            }
            if (state.readOnly || state.mode === 'measure' || state.mode === 'parcel') {
                if (typeof svg.setPointerCapture === 'function') svg.setPointerCapture(event.pointerId);
                return;
            }
            const vertex = event.target.getAttribute('data-site-vertex');
            const areaVertex = event.target.getAttribute('data-site-area-vertex');
            const areaId = event.target.getAttribute('data-site-area');
            const poseMode = event.target.getAttribute('data-site-pose');
            if (areaVertex !== null && state.section === 'areas' && state.mode !== 'area') {
                state.drag.kind = 'area-vertex'; state.drag.index = Number(areaVertex); state.drag.area = copy(state.areaDraft);
            } else if (areaId && state.section === 'areas' && state.mode !== 'area') {
                const selected = (state.site.areas || []).find(item => item.areaId === areaId);
                if (selected) { state.areaDraft = copy(selected); renderPanel(); renderCanvas(); }
            } else if (vertex !== null && state.section === 'property' && state.mode !== 'boundary') {
                state.drag.kind = 'vertex'; state.drag.index = Number(vertex); state.drag.property = copy(state.propertyDraft);
            } else if (poseMode && state.section === 'building') {
                state.drag.kind = poseMode; state.drag.pose = copy(state.poseDraft || state.site.buildingPose);
                state.drag.start = screenToProperty(event.clientX, event.clientY);
            }
            if (typeof svg.setPointerCapture === 'function') svg.setPointerCapture(event.pointerId);
        });
        svg.addEventListener('pointermove', function (event) {
            const drag = state.drag;
            if (!drag) return;
            const dx = event.clientX - drag.x;
            const dy = event.clientY - drag.y;
            if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
            const point = screenToProperty(event.clientX, event.clientY);
            if (drag.kind === 'trace') {
                state.traceBox = drag.moved ? { start: drag.start, end: point } : null;
                renderTraceBox();
                return;
            }
            if (drag.kind === 'area-vertex') {
                state.areaDraft = copy(drag.area); state.areaDraft.boundary[drag.index] = point;
            } else if (drag.kind === 'vertex') {
                const boundary = copy(drag.property.boundary); boundary[drag.index] = point;
                state.propertyDraft = replaceBoundary(drag.property, boundary);
            } else if (drag.kind === 'move') {
                state.poseDraft = Object.assign({}, drag.pose, { x: drag.pose.x + point.x - drag.start.x,
                    z: drag.pose.z + point.z - drag.start.z });
            } else if (drag.kind === 'rotate') {
                const dimensions = planSize(state.layout);
                const center = buildingToProperty(drag.pose, dimensions.width / 2, dimensions.depth / 2);
                const bearing = (Math.atan2(point.x - center.x, point.z - center.z) * 180 / Math.PI + 360) % 360;
                const offset = buildingToProperty({ x: 0, z: 0, bearingDegrees: bearing }, dimensions.width / 2, dimensions.depth / 2);
                state.poseDraft = { x: center.x - offset.x, z: center.z - offset.z, bearingDegrees: bearing };
            } else if (state.mode !== 'boundary' && state.mode !== 'area') {
                state.view.cx = drag.cx - dx * state.view.mpp;
                state.view.cz = drag.cz + dy * state.view.mpp;
            }
            renderCanvas();
        });
        svg.addEventListener('pointerup', function (event) {
            const drag = state.drag;
            state.drag = null;
            if (drag && drag.kind === 'trace') {
                const end = screenToProperty(event.clientX, event.clientY);
                state.traceBox = null;
                renderTraceBox();
                const wide = Math.abs(end.x - drag.start.x) >= 10 && Math.abs(end.z - drag.start.z) >= 10;
                traceAt(drag.moved && wide ? { box: { minX: Math.min(drag.start.x, end.x), maxX: Math.max(drag.start.x, end.x),
                    minZ: Math.min(drag.start.z, end.z), maxZ: Math.max(drag.start.z, end.z) } } : { x: drag.start.x, z: drag.start.z });
                return;
            }
            if (drag && drag.moved && drag.kind) {
                if (drag.kind === 'area-vertex') commitArea(); else if (drag.kind === 'vertex') commitProperty(); else commitPose();
                return;
            }
            if (drag && !drag.moved && (state.mode === 'boundary' || state.mode === 'area')) {
                if (state.sketch.length < 128) drawing.appendPolygonVertex(state.sketch, screenToProperty(event.clientX, event.clientY));
                renderPanel(); renderCanvas(); return;
            }
            if (drag && !drag.moved && state.mode === 'parcel') {
                pickParcel(screenToProperty(event.clientX, event.clientY));
                return;
            }
            if (drag && !drag.moved && state.mode === 'measure') {
                const point = screenToProperty(event.clientX, event.clientY);
                state.measure = state.measure.length === 1 ? [state.measure[0], point] : [point];
                state.measureHover = null;
                renderMeasure();
                return;
            }
            if (drag && !drag.moved && state.mode === 'pick') {
                moveBuildingTo(screenToProperty(event.clientX, event.clientY));
            }
        });
        element.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && state.flight) { state.flight.cancel(); return; }
            if (event.key === 'Escape') { state.sketch = []; state.drag = null; setMode('idle'); }
            if (event.key === 'Enter' && (state.mode === 'boundary' || state.mode === 'area') && !panel.contains(event.target)) finishBoundary();
        });
        svg.addEventListener('pointermove', function (event) {
            if (state.mode !== 'measure' || state.drag || state.measure.length !== 1 || !state.view) return;
            state.measureHover = screenToProperty(event.clientX, event.clientY);
            renderMeasure();
        });
        svg.addEventListener('dblclick', function () { if (state.mode === 'boundary' || state.mode === 'area') finishBoundary(); });
        svg.addEventListener('pointercancel', function () {
            state.drag = null; state.propertyDraft = state.site.property ? copy(state.site.property) : null;
            state.poseDraft = copy(state.site.buildingPose); renderCanvas();
        });

        return {
            element: element,
            render: function (layout, settings) {
                const readOnly = Boolean(settings && settings.readOnly);
                if (state.readOnly !== readOnly || (state.layout && state.layout.layoutId !== (layout && layout.layoutId))) {
                    state.areaDraft = null;
                    state.sketch = []; state.drag = null; state.mode = 'idle';
                    if (state.flight) state.flight.cancel();
                    if (state.request) state.request.abort();
                    if (state.analysisRequest) state.analysisRequest.abort();
                    state.request = null;
                    state.key = null;
                    state.busy = false;
                    state.message = ''; state.error = ''; state.matches = []; state.changing = false;
                }
                const site = siteContextOf(layout);
                state.readOnly = readOnly;
                const key = JSON.stringify([site, planSize(layout), readOnly]);
                state.layout = layout || null;
                // Session updates arrive for every edit; most do not touch the site.
                if (key === state.key) return;
                state.key = key;
                const previous = state.site;
                state.site = site;
                state.propertyDraft = site && site.property ? copy(site.property) : null;
                state.poseDraft = site ? copy(site.buildingPose) : null;
                if (state.areaDraft) state.areaDraft = site && (site.areas || []).find(area => area.areaId === state.areaDraft.areaId)
                    ? copy(site.areas.find(area => area.areaId === state.areaDraft.areaId)) : null;
                refreshAnalysis();
                if (!site) {
                    state.view = null;
                    state.mode = 'idle';
                    state.confirmRemove = false;
                } else if (!previous || firstImageId(previous) !== firstImageId(site)) {
                    state.view = null;
                } else if (state.view && firstImageId(site)) {
                    // Same photo, new origin: the photo stays still on screen and the building moves.
                    const before = imageRect(previous.imagery[0]);
                    const after = imageRect(site.imagery[0]);
                    state.view.cx += after.minX - before.minX;
                    state.view.cz += after.minZ - before.minZ;
                }
                if (state.visible) {
                    renderPanel();
                    renderCanvas();
                }
            },
            show: function () {
                state.visible = true;
                renderPanel();
                renderCanvas();
            },
            hide: function () {
                state.visible = false;
                if (state.flight) state.flight.cancel();
                state.mode = 'idle'; state.sketch = []; state.drag = null;
            },
            fit: function () {
                state.view = null;
                renderCanvas();
                return true;
            },
            zoomBy: function (factor) {
                if (!state.view) return false;
                state.view.mpp = Math.min(MAX_METERS_PER_PIXEL, Math.max(MIN_METERS_PER_PIXEL,
                    state.view.mpp / (Number(factor) || 1)));
                renderCanvas();
                return true;
            },
            destroy: function () {
                state.destroyed = true;
                if (state.flight) state.flight.cancel();
                if (state.request) state.request.abort();
                if (state.analysisRequest) state.analysisRequest.abort();
                if (element.parentNode) element.parentNode.removeChild(element);
            },
        };
    }

    return {
        create: create,
        siteContextOf: siteContextOf,
        buildingToProperty: buildingToProperty,
        propertyToBuilding: propertyToBuilding,
        buildingOutline: buildingOutline,
        imageRect: imageRect,
        latLonAt: latLonAt,
        geoPoint: geoPoint,
        viewForBox: viewForBox,
        roadLabels: roadLabels,
        routeColor: use => ROUTE_COLORS[use] || ROUTE_COLORS.shared,
        dashes: dashes,
        offsetLine: offsetLine,
        arrowsAlong: arrowsAlong,
        routeTarget: routeTarget,
        traceSummary: traceSummary,
        niceLength: niceLength,
        parseCoordinates: parseCoordinates,
        measureDistance: measureDistance,
        formatDistance: formatDistance,
        parseBoundary: parseBoundary,
        replaceBoundary: replaceBoundary,
        appendPolygonVertex: drawing.appendPolygonVertex,
        areaSurfaces: areaSurfaces,
    };
}));
