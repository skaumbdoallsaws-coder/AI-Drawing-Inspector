(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityFloorPlan = api;
}(typeof window !== 'undefined'
    ? window
    : (typeof self !== 'undefined' ? self : null), function () {
    'use strict';

    // Floor-plan import, the Plan view side (docs/facility-floor-plan-import-plan.md, sections 5 and 6): an imported
    // DXF drawn under the plan as a tracing underlay. The layout keeps only the reference
    // (extensions.facilityFloorPlanReferences: which stored drawing, its alignment, its layers, its opacity); the
    // drawing comes from the site's floor-plan store. The transform is the one in floor_plan_alignment.py and the
    // shared cases in tests/fixtures/facility_layout/floor_plan/alignment_cases.json:
    //     layout = translation + metersPerDrawingUnit * R(rotationDegrees) * (drawing - sourceOrigin)
    // drawing X -> layout X, drawing Y -> layout Z, R counter-clockwise. The underlay is drawn, never hit-tested,
    // and moves or collides with nothing.

    const KEY = 'facilityFloorPlanReferences';
    const SVG = 'http://www.w3.org/2000/svg';
    const MAX_LABELS = 3000;
    // Each line of a label is an element of its own: a label draws at most MAX_LINES_PER_LABEL lines and the
    // drawing at most MAX_LABEL_LINES, so thousands of labels of a thousand lines each cannot flood the page.
    const MAX_LINES_PER_LABEL = 8;
    const MAX_LABEL_LINES = 6000;
    const SNAP_PIXELS = 12;
    // The click and double click that follow a press the picks took are theirs as well.
    const DEFAULT_OPACITY = 0.6;
    const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
    const UNITS = [['meters', 1], ['millimeters', 0.001], ['centimeters', 0.01], ['inches', 0.0254], ['feet', 0.3048]];
    const STEPS = {
        align: ['drawing', 'layout', 'drawing', 'layout'],
        measure: ['drawing', 'drawing'],
    };
    const PROMPTS = {
        align: ['Click point A on the drawing.', 'Click where point A belongs on the plan.',
            'Click point B on the drawing, well away from A.', 'Click where point B belongs on the plan.'],
        measure: ['Click one end of a length you know on the drawing.', 'Click the other end.'],
    };
    // What a layer shows (floor_plan_references.ROLES). Converting the drawing reads these; "Drawing only" just shows
    // the layer.
    const ROLE_OPTIONS = [['reference', 'Drawing only'], ['wall_centerline', 'Walls: center lines'],
        ['wall_faces', 'Walls: both faces'], ['perimeter', 'Building outline'], ['room_boundary', 'Room outlines'],
        ['text', 'Room names'], ['column', 'Columns (later)'], ['door', 'Doors (later)'], ['ignore', 'Ignore']];
    const WALL_ROLES = ['wall_centerline', 'wall_faces'];
    const CONVERTED_ROLES = ['wall_centerline', 'wall_faces', 'perimeter', 'room_boundary'];
    // The zone types a room can become (floor_plan_conversion.ZONE_TYPES), named as the zone properties name them.
    const ZONE_TYPE_OPTIONS = [['workcell', 'Department / equipment area'], ['receiving', 'Receiving'],
        ['storage', 'Storage'], ['staging', 'Staging'], ['shipping', 'Shipping'], ['inspection', 'Inspection'],
        ['dock', 'Dock'], ['charging', 'Charging'], ['service', 'Service clearance - no equipment'],
        ['operator', 'Operator clearance - no equipment'], ['safety', 'Safety zone - no equipment'],
        ['exclusion', 'Exclusion zone - no equipment'], ['utility', 'Utility corridor - no equipment'],
        ['aisle', 'Aisle - no equipment']];
    // A candidate's state (floor_plan_conversion), in the panel's words.
    const CANDIDATE_STATES = { new: 'to add', there: 'already on the plan', edited: 'changed on the plan since',
        waiting: 'waiting', refused: 'not added', excluded: 'left out' };
    const LISTED_CANDIDATES = 300;
    const OUTDATED_NOTE = 'Changed since this list was made: Update the list to review the change.';
    const CONVERSION_FIELDS = ['wallHeight', 'wallThickness', 'maxThickness', 'outlineHeight', 'outlineThickness',
        'zoneType'];

    function finite(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function referenceOf(layout) {
        const value = layout && layout.extensions && layout.extensions[KEY];
        const references = value && Array.isArray(value.references) ? value.references : [];
        return references.length ? references[0] : null;
    }

    function turn(alignment) {
        const radians = alignment.rotationDegrees * Math.PI / 180;
        return { cos: Math.cos(radians), sin: Math.sin(radians) };
    }

    function toLayout(alignment, u, v) {
        const r = turn(alignment);
        const scale = alignment.metersPerDrawingUnit;
        const du = (u - alignment.sourceOrigin.u) * scale;
        const dv = (v - alignment.sourceOrigin.v) * scale;
        return {
            x: alignment.translationMeters.x + r.cos * du - r.sin * dv,
            z: alignment.translationMeters.z + r.sin * du + r.cos * dv,
        };
    }

    function toDrawing(alignment, x, z) {
        const r = turn(alignment);
        const scale = alignment.metersPerDrawingUnit;
        const dx = x - alignment.translationMeters.x;
        const dz = z - alignment.translationMeters.z;
        return {
            u: alignment.sourceOrigin.u + (r.cos * dx + r.sin * dz) / scale,
            v: alignment.sourceOrigin.v + (r.cos * dz - r.sin * dx) / scale,
        };
    }

    // The SVG matrix(a b c d e f) that takes a point of the stored geometry (drawing units, relative to the
    // geometry's origin) to the plan's projected coordinates: X = offsetX + (x - minX) * scale,
    // Y = offsetY + (maxZ - z) * scale (createTopPlanProjection in facility_layout_editor.js).
    function screenMatrix(alignment, origin, projection) {
        if (!alignment || !projection || !Array.isArray(origin)) return null;
        const r = turn(alignment);
        const k = projection.scale;
        const s = alignment.metersPerDrawingUnit;
        const cu = origin[0] - alignment.sourceOrigin.u;
        const cv = origin[1] - alignment.sourceOrigin.v;
        const tx = alignment.translationMeters.x;
        const tz = alignment.translationMeters.z;
        const matrix = [
            k * s * r.cos,
            -k * s * r.sin,
            -k * s * r.sin,
            -k * s * r.cos,
            projection.offsetX + k * (tx - projection.minX) + k * s * (r.cos * cu - r.sin * cv),
            projection.offsetY + k * (projection.maxZ - tz) - k * s * (r.sin * cu + r.cos * cv),
        ];
        return matrix.every(finite) ? matrix : null;
    }

    function hiddenLayers(reference) {
        return new Set((reference && reference.layers || []).filter(function (layer) {
            return layer.visible === false;
        }).map(function (layer) { return layer.layerId; }));
    }

    // What the drawn content depends on (the alignment and opacity only move or fade it).
    function contentKey(reference) {
        return reference.geometrySha256 + '|' + Array.from(hiddenLayers(reference)).sort().join(',');
    }

    function labelAnchor(align) {
        if (/RIGHT$/.test(align)) return 'end';
        if (/(CENTER|MIDDLE)$/.test(align)) return 'middle';
        return 'start';
    }

    function labelBaseline(align) {
        if (/^TOP/.test(align)) return 'hanging';
        if (/^MIDDLE/.test(align)) return 'central';
        if (/^BOTTOM/.test(align)) return 'text-after-edge';
        return 'alphabetic';
    }

    // A label's lines, at most MAX_LINES_PER_LABEL; the last one kept ends in '...' when more were left out.
    function labelLines(value) {
        const lines = String(value).split('\n', MAX_LINES_PER_LABEL + 1);
        if (lines.length > MAX_LINES_PER_LABEL) {
            lines.length = MAX_LINES_PER_LABEL;
            lines[MAX_LINES_PER_LABEL - 1] += ' ...';
        }
        return lines;
    }

    function appendLabel(documentRef, parent, entity, lines) {
        const text = documentRef.createElementNS(SVG, 'text');
        // The content's matrix turns drawing Y up the screen, so each label is flipped back to read upright.
        text.setAttribute('transform', 'translate(' + entity.at[0] + ' ' + entity.at[1] + ') rotate('
            + (finite(entity.rotation) ? entity.rotation : 0) + ') scale(1 -1)');
        text.setAttribute('font-size', String(finite(entity.height) && entity.height > 0 ? entity.height : 1));
        text.setAttribute('text-anchor', labelAnchor(String(entity.align || '')));
        text.setAttribute('dominant-baseline', labelBaseline(String(entity.align || '')));
        text.setAttribute('data-floor-plan-layer', entity.layer);
        if (lines.length === 1) {
            text.textContent = lines[0];
        } else {
            const align = String(entity.align || '');
            const first = /^MIDDLE/.test(align) ? -(lines.length - 1) * 0.625
                : (/^BOTTOM/.test(align) ? -(lines.length - 1) * 1.25 : 0);
            lines.forEach(function (line, index) {
                const span = documentRef.createElementNS(SVG, 'tspan');
                span.setAttribute('x', '0');
                span.setAttribute('dy', (index ? 1.25 : first) + 'em');
                span.textContent = line;
                text.appendChild(span);
            });
        }
        parent.appendChild(text);
    }

    // The drawing as SVG in its own stored coordinates: one path per visible layer (not one element per entity)
    // and at most MAX_LABELS labels of MAX_LABEL_LINES lines in all.
    function buildUnderlayContent(documentRef, geometry, reference) {
        const hidden = hiddenLayers(reference);
        const group = documentRef.createElementNS(SVG, 'g');
        group.setAttribute('class', 'ip-flw-floor-plan-drawing');
        group.setAttribute('fill', 'none');
        group.setAttribute('stroke', '#475569');
        const paths = new Map();
        const labels = [];
        let lineCount = 0;
        let skipped = 0;
        (geometry && geometry.entities || []).forEach(function (entity) {
            if (!entity || hidden.has(entity.layer)) return;
            if (Array.isArray(entity.points)) {
                if (entity.points.length < 2) return;
                let d = 'M' + entity.points[0][0] + ' ' + entity.points[0][1];
                for (let index = 1; index < entity.points.length; index += 1) {
                    d += ' ' + entity.points[index][0] + ' ' + entity.points[index][1];
                }
                if (entity.closed) d += 'Z';
                const parts = paths.get(entity.layer) || [];
                parts.push(d);
                paths.set(entity.layer, parts);
            } else if (typeof entity.text === 'string' && Array.isArray(entity.at)) {
                if (labels.length >= MAX_LABELS) {
                    skipped += 1;
                    return;
                }
                const lines = labelLines(entity.text);
                if (lineCount + lines.length > MAX_LABEL_LINES) {
                    skipped += 1;
                    return;
                }
                labels.push([entity, lines]);
                lineCount += lines.length;
            }
        });
        paths.forEach(function (parts, layerId) {
            const path = documentRef.createElementNS(SVG, 'path');
            path.setAttribute('d', parts.join(' '));
            path.setAttribute('data-floor-plan-layer', layerId);
            path.setAttribute('vector-effect', 'non-scaling-stroke');
            path.setAttribute('stroke-width', '1');
            group.appendChild(path);
        });
        if (labels.length) {
            const texts = documentRef.createElementNS(SVG, 'g');
            texts.setAttribute('class', 'ip-flw-floor-plan-labels');
            texts.setAttribute('fill', '#475569');
            texts.setAttribute('stroke', 'none');
            texts.setAttribute('font-family', 'Arial, sans-serif');
            labels.forEach(function (label) { appendLabel(documentRef, texts, label[0], label[1]); });
            group.appendChild(texts);
        }
        group.setAttribute('data-floor-plan-paths', String(paths.size));
        group.setAttribute('data-floor-plan-labels', String(labels.length));
        group.setAttribute('data-floor-plan-label-lines', String(lineCount));
        group.setAttribute('data-floor-plan-labels-skipped', String(skipped));
        return group;
    }

    // Every vertex of the drawing's shown layers (HIDDEN: a Set of layer ids left out) in a uniform grid, in stored
    // coordinates, for snapping picks to what the user sees.
    function createSnapIndex(geometry, hidden) {
        const values = [];
        (geometry && geometry.entities || []).forEach(function (entity) {
            if (!entity || !Array.isArray(entity.points) || (hidden && hidden.has(entity.layer))) return;
            entity.points.forEach(function (point) { values.push(point[0], point[1]); });
        });
        const count = values.length / 2;
        if (!count) return { count: 0 };
        const points = Float64Array.from(values);
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        for (let index = 0; index < count; index += 1) {
            const x = points[2 * index];
            const y = points[2 * index + 1];
            if (x < minX) minX = x;
            if (y < minY) minY = y;
            if (x > maxX) maxX = x;
            if (y > maxY) maxY = y;
        }
        const width = maxX - minX;
        const height = maxY - minY;
        // About eight points a cell, and never more cells than points even for a drawing that is one line.
        const cell = Math.max(Math.sqrt(width * height * 8 / count), Math.max(width, height) * 8 / count, 1e-9);
        const columns = Math.floor(width / cell) + 1;
        const rows = Math.floor(height / cell) + 1;
        const starts = new Int32Array(columns * rows + 1);
        const cells = new Int32Array(count);
        for (let index = 0; index < count; index += 1) {
            const column = Math.min(columns - 1, Math.floor((points[2 * index] - minX) / cell));
            const row = Math.min(rows - 1, Math.floor((points[2 * index + 1] - minY) / cell));
            cells[index] = column + row * columns;
            starts[cells[index] + 1] += 1;
        }
        for (let index = 1; index < starts.length; index += 1) starts[index] += starts[index - 1];
        const cursor = starts.slice(0, -1);
        const order = new Int32Array(count);
        for (let index = 0; index < count; index += 1) order[cursor[cells[index]]++] = index;
        return { count: count, points: points, minX: minX, minY: minY, cell: cell, columns: columns, rows: rows,
            starts: starts, order: order };
    }

    // The drawing vertex nearest (u, v) within RADIUS (stored coordinates), or null: the same answer as a full
    // search. Ring by ring outward from the query's cell (a point in ring k is at least (k - 1) cells away),
    // looking only at the cells of each ring that lie in the grid, and stopping once no nearer point can remain.
    // Rings nearer than the grid, and past its farthest corner, hold nothing and are skipped.
    function nearestVertex(index, u, v, radius) {
        if (!index || !index.count || !finite(u) || !finite(v) || !(radius > 0)) return null;
        const columns = index.columns;
        const rows = index.rows;
        const column = Math.floor((u - index.minX) / index.cell);
        const row = Math.floor((v - index.minY) / index.cell);
        const first = Math.max(0, -column, column - (columns - 1), -row, row - (rows - 1));
        const last = Math.max(Math.abs(column), Math.abs(column - (columns - 1)), Math.abs(row),
            Math.abs(row - (rows - 1)));
        const reach = Math.min(last, Math.ceil(radius / index.cell));
        let best = -1;
        let bestDistance = radius;
        const visit = function (id) {
            for (let k = index.starts[id]; k < index.starts[id + 1]; k += 1) {
                const point = index.order[k];
                const distance = Math.hypot(index.points[2 * point] - u, index.points[2 * point + 1] - v);
                if (distance <= bestDistance) {
                    best = point;
                    bestDistance = distance;
                }
            }
        };
        for (let ring = first; ring <= reach; ring += 1) {
            if (best >= 0 && (ring - 1) * index.cell > bestDistance) break;
            const left = Math.max(0, column - ring);
            const right = Math.min(columns - 1, column + ring);
            [row - ring].concat(ring ? [row + ring] : []).forEach(function (r) {
                if (r < 0 || r >= rows) return;
                for (let c = left; c <= right; c += 1) visit(c + r * columns);
            });
            if (!ring) continue;
            const bottom = Math.max(0, row - ring + 1);
            const top = Math.min(rows - 1, row + ring - 1);
            [column - ring, column + ring].forEach(function (c) {
                if (c < 0 || c >= columns) return;
                for (let r = bottom; r <= top; r += 1) visit(c + r * columns);
            });
        }
        return best < 0 ? null
            : { u: index.points[2 * best], v: index.points[2 * best + 1], distance: bestDistance };
    }

    function fileLabel(name) {
        const text = String(name || '').replace(/\.dxf$/i, '').trim();
        return (text || 'Floor plan').slice(0, 120);
    }

    // A first reference for a drawing just imported: drawn at its declared unit (1 m per unit when the file
    // declares none, unconfirmed), its lowest corner on the plan's origin, layers the drawing hides kept hidden.
    function newReference(record, manifest) {
        const units = manifest && manifest.units || {};
        const declared = finite(units.metersPerUnit) && units.metersPerUnit > 0;
        const origin = manifest && Array.isArray(manifest.origin) ? manifest.origin : [0, 0];
        return {
            referenceId: 'fp-main',
            label: fileLabel(record.sourceName),
            sourceName: record.sourceName || 'drawing.dxf',
            importId: record.importId,
            sourceSha256: record.sourceSha256,
            geometrySha256: record.geometrySha256,
            parserVersion: record.parserVersion,
            alignment: {
                sourceOrigin: { u: origin[0], v: origin[1] },
                metersPerDrawingUnit: declared ? units.metersPerUnit : 1,
                rotationDegrees: 0,
                translationMeters: { x: 0, z: 0 },
                unitSource: declared ? 'header' : 'chosen',
                confirmed: declared,
                controlPoints: [],
            },
            layers: (manifest && manifest.layers || []).map(function (layer) {
                return { layerId: layer.layerId, visible: layer.on !== false && layer.frozen !== true,
                    role: 'reference' };
            }),
            opacity: DEFAULT_OPACITY,
            showIn3D: false,
        };
    }

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function html(documentRef, tag, attributes, text) {
        const node = documentRef.createElement(tag);
        Object.keys(attributes || {}).forEach(function (name) {
            const value = attributes[name];
            if (value === false || value === null || value === undefined) return;
            if (name === 'className') node.className = value;
            else node.setAttribute(name, value === true ? '' : String(value));
        });
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function round(value, places) {
        const factor = Math.pow(10, places);
        return Math.round(value * factor) / factor;
    }

    function unitName(metersPerUnit) {
        const match = UNITS.find(function (unit) { return Math.abs(unit[1] - metersPerUnit) < 1e-12; });
        return match ? match[0] : null;
    }

    function actionButton(documentRef, action, label, disabled) {
        return html(documentRef, 'button', { type: 'button', className: 'ip-flw-layer-show-all',
            'data-fp-action': action, disabled: Boolean(disabled) }, label);
    }

    function newConversionForm() {
        return { wallHeight: '', wallThickness: '0.2', maxThickness: '0.6', outlineHeight: '', outlineThickness: '0.3',
            zoneType: '', types: {}, loop: null, replace: false, excluded: [] };
    }

    function rolesOf(reference) {
        const roles = new Set();
        (reference && Array.isArray(reference.layers) ? reference.layers : []).forEach(function (layer) {
            roles.add(layer.role);
        });
        return roles;
    }

    function typedNumber(text) {
        const trimmed = String(text === undefined || text === null ? '' : text).trim();
        const value = trimmed ? Number(trimmed) : NaN;
        return Number.isFinite(value) ? value : null;
    }

    // The settings the conversion takes (floor_plan_conversion.normalize_settings), from the panel's fields (FORM) and
    // the layer roles saved with the underlay (ROLES): a part no layer has is left out, and a part without its height
    // is listed but not added.
    function conversionSettings(form, roles) {
        const settings = { excluded: form.excluded.slice().sort() };
        const put = function (target, key, text) {
            const value = typedNumber(text);
            if (value !== null) target[key] = value;
        };
        if (WALL_ROLES.some(function (role) { return roles.has(role); })) {
            settings.walls = {};
            put(settings.walls, 'heightMeters', form.wallHeight);
            if (roles.has('wall_centerline')) put(settings.walls, 'thicknessMeters', form.wallThickness);
            if (roles.has('wall_faces')) put(settings.walls, 'maxThicknessMeters', form.maxThickness);
        }
        if (roles.has('perimeter')) {
            settings.outline = { replace: form.replace === true };
            put(settings.outline, 'heightMeters', form.outlineHeight);
            put(settings.outline, 'thicknessMeters', form.outlineThickness);
            if (form.loop) settings.outline.loop = form.loop;
        }
        if (roles.has('room_boundary')) {
            settings.rooms = { zoneType: form.zoneType || null, types: Object.assign({}, form.types) };
        }
        return settings;
    }

    // The import panel and everything the workspace delegates to it: which underlay the plan shows, picks while
    // aligning, and the reference operations (each an undoable gesture through the session).
    function FloorPlanController(workspace) {
        this.workspace = workspace;
        this.document = workspace.document;
        this.geometries = new Map();
        this.snapIndexes = new Map();
        this.panel = null;
        this.isOpen = false;
        this.busy = false;
        this.draft = null;
        this.picking = null;
        this.result = null;
        this.hover = null;
        this.message = '';
        this.error = '';
        this.layout = null;
        this.hidden = false;  // the drawing hidden for now (not saved)
        this.shownSignature = '';
        this.syncedReferences = null;
        this.distanceText = '';
        this.epoch = 0;
        this.disposed = false;
        this.preview = false;  // the plan shows a preview (a candidate, Sage's or a construction step)
        this.suspendedTool = null;  // the workspace tool set aside while picking
        this.pressOwned = false;  // the plan's latest press was a pick: the click it ends in is the pick's
        this.finishingPress = null;  // when and where the press that ended the picks was (pressStamp)
        this.sequenceOwned = false;  // the click sequence (a double click) began with a pick
        // Advanced whenever picks, and the answers worked out from them, stop belonging to the drawing (it changed,
        // even if an undo and a redo bring it back; a preview opened; the picks were cleared). An answer on its way
        // is used only if the generation it began in is still the current one.
        this.generation = 0;
        this.watchedToken = null;
        this.watchedPreview = false;
        // Converting the saved underlay to walls, rooms and the building outline (FP2): the panel's fields for its
        // drawing, the server's latest answer, and a change staged for review until its preview closes.
        this.conversion = null;
        this.conversionSequence = 0;
        this.conversionReview = null;
    }

    FloorPlanController.prototype._adapter = function () {
        return this.workspace.topAdapter || null;
    };

    FloorPlanController.prototype._savedReference = function () {
        const state = this.workspace.state;
        return referenceOf(state && state.layout);
    };

    // The reference the panel edits: a drawing imported but not yet added, else the one the layout keeps.
    FloorPlanController.prototype.currentReference = function () {
        return this.draft ? this.draft.reference : this._savedReference();
    };

    // The reference the plan shows: the draft while there is one, else the represented layout's. A preview shows
    // its own underlay (or none), never the draft or the saved one beneath another candidate.
    FloorPlanController.prototype._shownReference = function () {
        if (this.hidden && !this.picking) return null;
        return this.draft && !this.preview ? this.draft.reference : referenceOf(this.layout);
    };

    // What picks and their results depend on: which drawing, where it sits and at what scale. Showing a layer or
    // changing the strength leaves them be.
    FloorPlanController.prototype._referenceToken = function () {
        const reference = this.currentReference();
        return reference ? JSON.stringify([reference.referenceId, reference.importId, reference.alignment]) : '';
    };

    // Picks and results belong to the drawing as it was when they began: an undo or redo, a unit chosen, or a
    // preview put in front of it drops them. (An answer still on its way is checked the same way when it comes
    // back.) Returns whether anything was dropped.
    FloorPlanController.prototype._dropStale = function () {
        const token = this._referenceToken();
        const preview = this.preview;
        if (token !== this.watchedToken || (preview && !this.watchedPreview)) this.generation += 1;
        this.watchedToken = token;
        this.watchedPreview = preview;
        const stale = [this.picking, this.result].some(function (item) {
            return item && (preview || item.token !== token);
        });
        if (!stale) return false;
        this._clearPicks();
        this.message = preview ? 'A preview is showing. Pick the points again once it closes.'
            : 'The drawing changed, so the points picked on it were dropped. Pick them again.';
        return true;
    };

    // Ends any picking and drops its result: the hover ring goes, the drawing tool comes back, and an answer still
    // being worked out from the picks is dropped when it arrives.
    FloorPlanController.prototype._clearPicks = function () {
        this.picking = null;
        this.result = null;
        this.distanceText = '';
        this.generation += 1;
        this._setHover(null);
        this._resumeTool();
    };

    // While picking, a zone tool is set aside (a polygon zone would take Enter, a rectangle a drag) and given back when
    // the picks end. Picks do not begin while a tool that runs its own panel is active (aisles, floor markings, motion
    // paths: setting one aside would end its drawing), and choosing any tool while picking ends the picks, so no tool
    // shares the plan with them.
    const SET_ASIDE_TOOLS = ['rectangle-zone', 'polygon-zone'];
    const PANEL_TOOLS = Object.freeze({ aisle: 'Aisle', 'floor-marking': 'Floor marking', 'motion-path': 'Motion path' });
    // A press this soon after, and this near (screen pixels to), the press that ended the picks is the second press of
    // a double click on the last point: it is the picks' too.
    const DOUBLE_PRESS_MS = 500;
    const DOUBLE_PRESS_PX = 6;

    function pressStamp(event) {
        return {
            time: event && finite(event.timeStamp) && event.timeStamp > 0 ? event.timeStamp : Date.now(),
            x: event && finite(event.clientX) ? event.clientX : 0,
            y: event && finite(event.clientY) ? event.clientY : 0,
        };
    }

    FloorPlanController.prototype._suspendTool = function () {
        const workspace = this.workspace;
        const mode = workspace.toolMode;
        if (SET_ASIDE_TOOLS.indexOf(mode) < 0 || typeof workspace._setToolMode !== 'function') return;
        if (!this.suspendedTool) this.suspendedTool = mode;
        workspace._setToolMode('select', { keepPicks: true });  // not the user's choice: the picks go on
    };

    FloorPlanController.prototype._resumeTool = function () {
        const mode = this.suspendedTool;
        this.suspendedTool = null;
        const workspace = this.workspace;
        if (!mode || this.disposed || workspace.toolMode !== 'select'
                || typeof workspace._setToolMode !== 'function') return;
        workspace._setToolMode(mode, { keepPicks: true });  // a double click on the last point stays the picks'
    };

    // The workspace says a tool was chosen (a button, a key, a panel or a dialog; Select included): picks in progress
    // end, the tool set aside is not given back, and the next press is the chosen tool's, even one that follows the
    // last pick at once.
    FloorPlanController.prototype.toolChosen = function () {
        this.suspendedTool = null;
        this.finishingPress = null;
        if (!this.picking) return;
        this._clearPicks();
        this._refresh();
        this.render();
    };

    // Whether EVENT is the second press of a double click whose first press ended the picks (asked once per press).
    FloorPlanController.prototype._repeatsFinishingPress = function (event) {
        const first = this.finishingPress;
        this.finishingPress = null;
        if (!first || (finite(event && event.button) && event.button !== 0)) return false;
        const press = pressStamp(event);
        const elapsed = press.time - first.time;
        return elapsed >= 0 && elapsed <= DOUBLE_PRESS_MS
            && Math.hypot(press.x - first.x, press.y - first.y) <= DOUBLE_PRESS_PX;
    };

    // A press on the plan begins (the workspace says so before anything else handles it).
    FloorPlanController.prototype.forgetPress = function () {
        this.pressOwned = false;
    };

    // Whether a click on the plan belongs to the picks: any click while picking, the click that ends the press a pick
    // took (however long it was held), and the further clicks of a double click that began with a pick. EVENT.detail
    // is the click count; a press that was not a pick (forgetPress) ends the pick's claim.
    FloorPlanController.prototype.ownsClick = function (event) {
        const count = event && finite(event.detail) && event.detail > 0 ? event.detail : 1;
        this.sequenceOwned = count > 1 ? this.sequenceOwned || this.pressOwned : this.pressOwned;
        this.pressOwned = false;
        return Boolean(this.picking) || this.sequenceOwned;
    };

    // A double click on the plan belongs to the picks while picking, or when its clicks began with a pick.
    FloorPlanController.prototype.ownsDoubleClick = function () {
        return Boolean(this.picking) || this.sequenceOwned;
    };

    FloorPlanController.prototype._geometryEntry = function (importId) {
        if (!importId) return null;
        let entry = this.geometries.get(importId);
        if (!entry) {
            entry = { geometry: null, error: null };
            this.geometries.set(importId, entry);
            const session = this.workspace.session;
            Promise.resolve().then(function () {
                if (!session || typeof session.floorPlanGeometry !== 'function') {
                    throw new Error('Floor-plan import is unavailable.');
                }
                return session.floorPlanGeometry(importId);
            }).then(function (geometry) {
                entry.geometry = geometry;
            }, function (error) {
                entry.error = error;
            }).then(function () {
                if (this.disposed) return;
                this._refresh();
                this.render();
            }.bind(this));
        }
        return entry;
    };

    FloorPlanController.prototype._markers = function () {
        const markers = [];
        const reference = this._shownReference();
        const points = this.picking ? this.picking.points : (this.result && this.result.points) || [];
        const mode = this.picking ? this.picking.mode : this.result && this.result.kind;
        const names = mode === 'measure' ? ['A', 'B'] : ['A', 'A\'', 'B', 'B\''];
        points.forEach(function (point, index) {
            let at = point;
            if (point.kind === 'drawing' && reference) at = toLayout(reference.alignment, point.u, point.v);
            markers.push({ x: at.x, z: at.z, label: names[index], kind: point.kind });
        });
        return markers;
    };

    // Puts on the plan what it should show now; does nothing when that has not changed.
    FloorPlanController.prototype._refresh = function () {
        if (this.disposed) return;
        const adapter = this._adapter();
        if (!adapter || typeof adapter.setFloorPlanUnderlay !== 'function') return;
        const reference = this._shownReference();
        const entry = reference ? this._geometryEntry(reference.importId) : null;
        const geometry = entry && entry.geometry;
        const value = reference && geometry ? {
            key: contentKey(reference),
            reference: reference,
            geometry: geometry,
            markers: this._markers(),
            picking: Boolean(this.picking),
        } : null;
        const signature = value ? JSON.stringify([value.key, reference, value.markers, value.picking]) : '';
        if (signature === this.shownSignature) return;
        this.shownSignature = signature;
        adapter.setFloorPlanUnderlay(value);
    };

    // Called with each layout the plan represents (OPTIONS.preview: a preview, not the layout being edited). The
    // panel is drawn again only when an underlay it shows changed, so a value being typed survives unrelated
    // updates.
    FloorPlanController.prototype.sync = function (layout, options) {
        if (this.disposed) return;
        this.layout = layout || null;
        this.preview = Boolean(options && options.preview);
        const dropped = this._dropStale();
        this._refresh();
        const state = this.workspace.state;
        const reported = this._noteReviewClosed(state);
        // The saved revision and unsaved edits decide what the Walls and rooms section offers.
        const shown = JSON.stringify([referenceOf(this.layout), referenceOf(state && state.layout), this.preview,
            state && state.baseRevision, Boolean(state && state.dirty)]);
        if (shown === this.syncedReferences && !dropped && !reported) return;
        this.syncedReferences = shown;
        if (this.isOpen) this.render();
    };

    // A conversion staged for review: once its preview has shown and closed, the panel says whether it was approved.
    FloorPlanController.prototype._noteReviewClosed = function (state) {
        const review = this.conversionReview;
        if (!review) return false;
        if (this.preview) {
            review.shown = true;
            return false;
        }
        if (!review.shown) return false;
        this.conversionReview = null;
        this.message = state && state.baseRevision !== review.revision
            ? 'Approved: the walls and rooms from the drawing are in the layout.'
            : 'The review closed without a change: the layout is as it was.';
        return true;
    };

    FloorPlanController.prototype.open = function () {
        this.geometries.forEach(function (entry, importId) {  // a drawing that failed to load is tried again
            if (entry.error) this.geometries.delete(importId);
        }, this);
        this.isOpen = true;
        this.error = '';
        this._refresh();
        this.render();
    };

    // Closing drops a drawing not yet added (cancel changes nothing), any alignment in progress and the answer to
    // anything still being read or calculated.
    FloorPlanController.prototype.close = function () {
        this.epoch += 1;
        this.busy = false;
        this.isOpen = false;
        this.draft = null;
        if (this.conversion) this.conversion.answer = null;
        this.conversionReview = null;
        this._clearPicks();
        this.message = '';
        this.error = '';
        this._refresh();
        this.render();
    };

    FloorPlanController.prototype._chooseFile = function () {
        const input = this.panel && this.panel.querySelector('[data-fp-file]');
        if (input && typeof input.click === 'function') input.click();
    };

    FloorPlanController.prototype._fail = function (error) {
        this.error = error && error.message ? error.message : String(error || 'Something went wrong.');
        this.busy = false;
        this.render();
    };

    FloorPlanController.prototype.importFile = async function (file) {
        if (!file) return;
        if (finite(file.size) && file.size > MAX_UPLOAD_BYTES) {
            this._fail(new Error('The drawing is larger than 25 MB, more than the import supports.'));
            return;
        }
        const session = this.workspace.session;
        if (!session || typeof session.importFloorPlan !== 'function') {
            this._fail(new Error('Floor-plan import is unavailable.'));
            return;
        }
        const epoch = this.epoch;
        this.busy = true;
        this.error = '';
        this._clearPicks();
        this.message = 'Reading ' + (file.name || 'the drawing') + '...';
        this.render();
        try {
            const imported = await session.importFloorPlan(file);
            if (epoch !== this.epoch) return;  // closed while it was read: nothing is shown or added
            const record = imported.import;
            const manifest = imported.manifest;
            const reference = newReference(record, manifest);
            const saved = this._savedReference();
            if (saved && saved.importId === record.importId) {
                this.draft = null;
                this.message = 'This drawing is already on the plan.';
            } else {
                if (saved) {  // a new drawing replaces the old one where the old one was
                    reference.referenceId = saved.referenceId;
                    reference.opacity = saved.opacity;
                }
                this.draft = { record: record, manifest: manifest, reference: reference };
                this.hidden = false;
                this.message = (imported.reused ? 'Imported before. ' : '') + 'Check the units and layers, then add '
                    + 'it to the plan.';
            }
            this.busy = false;
            this._refresh();
            this.render();
        } catch (error) {
            if (epoch !== this.epoch) return;
            this.message = '';
            this._fail(error);
        }
    };

    // A change to the reference: kept in the draft until it is added, else saved as one undoable edit.
    FloorPlanController.prototype._change = async function (reference, message) {
        if (this.draft) {
            this.draft.reference = reference;
            const dropped = this._dropStale();
            this.message = (message || '') + (dropped ? (message ? ' ' : '') + 'Pick the points again.' : '');
            this._refresh();
            this.render();
            return;
        }
        const session = this.workspace.session;
        const epoch = this.epoch;
        this.busy = true;
        this.error = '';
        this.render();
        try {
            await session.upsertFloorPlanReference(reference);
            if (epoch !== this.epoch) return;  // closed meanwhile: the edit stands, the panel moved on
            this.busy = false;
            this.message = message || '';
            this.render();
        } catch (error) {
            if (epoch === this.epoch) this._fail(error);
        }
    };

    FloorPlanController.prototype.addDraft = async function () {
        if (!this.draft) return;
        const epoch = this.epoch;
        this.busy = true;
        this.error = '';
        this.render();
        try {
            await this.workspace.session.upsertFloorPlanReference(this.draft.reference);
            if (epoch !== this.epoch) return;
            this.draft = null;
            this.busy = false;
            this.message = 'Added. Undo removes it again.';
            this._refresh();
            this.render();
        } catch (error) {
            if (epoch === this.epoch) this._fail(error);
        }
    };

    FloorPlanController.prototype.remove = async function () {
        const saved = this._savedReference();
        if (!saved) return;
        const epoch = this.epoch;
        this.busy = true;
        this.error = '';
        this._clearPicks();
        this._refresh();
        this.render();
        try {
            await this.workspace.session.deleteFloorPlanReference(saved.referenceId);
            if (epoch !== this.epoch) return;
            this.busy = false;
            this.message = 'Removed the drawing. Walls and zones drawn from it stay.';
            this._refresh();
            this.render();
        } catch (error) {
            if (epoch === this.epoch) this._fail(error);
        }
    };

    FloorPlanController.prototype.startPicking = function (mode) {
        this._dropStale();  // notes the drawing the picks begin on
        const reference = this.currentReference();
        const entry = reference && this._geometryEntry(reference.importId);
        let problem = '';
        const tool = PANEL_TOOLS[this.workspace.toolMode];
        if (this.workspace.viewMode !== 'plan') problem = 'Switch to the Plan view to pick points.';
        else if (this.preview) problem = 'A preview is showing. Close it to pick points on the drawing.';
        else if (!entry || !entry.geometry) problem = 'The drawing is still loading.';
        else if (tool) problem = 'Choose Select first. The ' + tool + ' tool is using the clicks on the plan.';
        else if (this.workspace.lightAreaDraw) problem = 'Finish drawing the light area first.';
        if (problem) {
            this.error = problem;
            this.render();
            return;
        }
        this.picking = { mode: mode, points: [], token: this._referenceToken() };
        this.result = null;
        this.error = '';
        this.message = '';
        this._suspendTool();
        this._refresh();
        this.render();
    };

    FloorPlanController.prototype.cancelPicking = function () {
        this._clearPicks();
        this._refresh();
        this.render();
    };

    FloorPlanController.prototype._setHover = function (point) {
        this.hover = point;
        if (this.disposed) return;
        const adapter = this._adapter();
        if (adapter && typeof adapter.setFloorPlanHover === 'function') adapter.setFloorPlanHover(point);
    };

    FloorPlanController.prototype._snapIndex = function (reference, geometry) {
        const key = contentKey(reference);
        let index = this.snapIndexes.get(key);
        if (!index) {
            if (this.snapIndexes.size >= 4) this.snapIndexes.clear();
            index = createSnapIndex(geometry, hiddenLayers(reference));
            this.snapIndexes.set(key, index);
        }
        return index;
    };

    // The point a click at EVENT picks: on the drawing (snapped to its nearest vertex within SNAP_PIXELS) or on the
    // plan (snapped as the workspace snaps).
    FloorPlanController.prototype._pickAt = function (event, kind) {
        const adapter = this._adapter();
        const reference = this._shownReference();
        if (!adapter || !reference || typeof adapter.planPointAt !== 'function') return null;
        if (kind === 'layout') {
            let world = null;
            try {
                world = this.workspace._eventWorld(event);
            } catch (error) {
                world = adapter.planPointAt(event);
            }
            return world && finite(world.x) && finite(world.z) ? { kind: 'layout', x: world.x, z: world.z } : null;
        }
        const world = adapter.planPointAt(event);
        if (!world || !finite(world.x) || !finite(world.z)) return null;
        const alignment = reference.alignment;
        const drawing = toDrawing(alignment, world.x, world.z);
        const entry = this._geometryEntry(reference.importId);
        const geometry = entry && entry.geometry;
        let u = drawing.u;
        let v = drawing.v;
        let snapped = false;
        const scale = typeof adapter.planScale === 'function' ? adapter.planScale() : null;
        if (geometry && finite(scale) && scale > 0) {
            const origin = geometry.origin || [0, 0];
            const radius = SNAP_PIXELS / scale / alignment.metersPerDrawingUnit;
            const vertex = nearestVertex(this._snapIndex(reference, geometry), u - origin[0], v - origin[1], radius);
            if (vertex) {
                u = vertex.u + origin[0];
                v = vertex.v + origin[1];
                snapped = true;
            }
        }
        const at = toLayout(alignment, u, v);
        return { kind: 'drawing', u: u, v: v, x: at.x, z: at.z, snapped: snapped };
    };

    FloorPlanController.prototype.handlePointerMove = function (event) {
        if (!this.picking || this.workspace.viewMode !== 'plan') return false;
        const kind = STEPS[this.picking.mode][this.picking.points.length];
        const point = kind ? this._pickAt(event, kind) : null;
        this._setHover(point ? { x: point.x, z: point.z, snapped: Boolean(point.snapped) } : null);
        return true;
    };

    FloorPlanController.prototype.handlePointerDown = function (event) {
        this.pressOwned = false;
        const repeat = this._repeatsFinishingPress(event);
        if (this.workspace.viewMode !== 'plan') return false;
        if (!this.picking) {
            // The second press of a double click on the last point: a tool given back would act on it.
            this.pressOwned = repeat;
            return repeat;
        }
        const button = finite(event && event.button) ? event.button : 0;
        if (button === 1) return false;  // the middle button still pans
        this.pressOwned = true;
        if (button !== 0) return true;  // other buttons pick nothing, and while picking no tool has them either
        const steps = STEPS[this.picking.mode];
        const point = this._pickAt(event, steps[this.picking.points.length]);
        if (!point) return true;
        this.picking.points.push(point);
        if (this.picking.points.length === steps.length) {
            this.finishingPress = pressStamp(event);
            const picked = this.picking;
            this.picking = null;
            this._setHover(null);
            this._resumeTool();
            this._finishPicking(picked);
        } else {
            this._refresh();
            this.render();
        }
        return true;
    };

    FloorPlanController.prototype._staleAnswer = function (what) {
        this.busy = false;
        this.result = null;
        this.message = this.preview ? 'A preview opened while ' + what + ' was worked out. Pick the points again '
            + 'once it closes.' : 'The drawing changed while ' + what + ' was worked out. Pick the points again.';
        this._refresh();
        this.render();
    };

    // Whether an answer that began in GENERATION for the drawing TOKEN can still be used.
    FloorPlanController.prototype._current = function (generation, token) {
        return generation === this.generation && !this.preview && token === this._referenceToken();
    };

    FloorPlanController.prototype._finishPicking = async function (picked) {
        const reference = this.currentReference();
        const token = picked.token;
        const generation = this.generation;
        if (!reference || !this._current(generation, token)) {
            this._staleAnswer('the pick');
            return;
        }
        if (picked.mode === 'measure') {
            const a = picked.points[0];
            const b = picked.points[1];
            this.distanceText = '';
            this.result = { kind: 'measure', points: picked.points, token: token,
                drawingDistance: Math.hypot(b.u - a.u, b.v - a.v) };
            this._refresh();
            this.render();
            return;
        }
        const points = picked.points;
        const controls = [
            { source: { u: points[0].u, v: points[0].v }, target: { x: points[1].x, z: points[1].z } },
            { source: { u: points[2].u, v: points[2].v }, target: { x: points[3].x, z: points[3].z } },
        ];
        const body = { controlPoints: controls };
        // A confirmed unit holds its scale (a rigid move); an unconfirmed one lets the points set it.
        if (reference.alignment.confirmed) body.metersPerDrawingUnit = reference.alignment.metersPerDrawingUnit;
        else body.scale = 'fit';
        const epoch = this.epoch;
        this.busy = true;
        this.error = '';
        this.render();
        try {
            const response = await this.workspace.session.alignFloorPlan(reference.importId, body);
            if (epoch !== this.epoch) return;
            if (!this._current(generation, token)) {
                this._staleAnswer('the alignment');
                return;
            }
            this.result = { kind: 'align', points: points, controls: controls, response: response, token: token };
            this.busy = false;
            this._refresh();
            this.render();
        } catch (error) {
            if (epoch !== this.epoch) return;
            this.result = null;
            this._refresh();
            this._fail(error);
        }
    };

    FloorPlanController.prototype.applyAlignment = function () {
        if (this._dropStale()) {
            this._refresh();
            this.render();
            return;
        }
        const reference = this.currentReference();
        if (!reference || !this.result || this.result.kind !== 'align') return;
        if (this.preview || this.result.token !== this._referenceToken()) {
            this._staleAnswer('the alignment');
            return;
        }
        const response = this.result.response;
        const next = clone(reference);
        next.alignment = Object.assign({}, next.alignment, clone(response.alignment), {
            unitSource: response.scale === 'fit' ? 'calibrated' : next.alignment.unitSource,
            confirmed: true,
            controlPoints: clone(this.result.controls),
        });
        this.result = null;
        this._change(next, 'Aligned.');
    };

    FloorPlanController.prototype.applyDistance = async function (meters) {
        if (this._dropStale()) {
            this._refresh();
            this.render();
            return;
        }
        const reference = this.currentReference();
        if (!reference || !this.result || this.result.kind !== 'measure') return;
        const value = Number(meters);
        if (!finite(value) || value <= 0) {
            this.error = 'Enter the real length in meters.';
            this.render();
            return;
        }
        const points = this.result.points;
        const token = this.result.token;
        const generation = this.generation;
        if (!this._current(generation, token)) {
            this._staleAnswer('the scale');
            return;
        }
        const epoch = this.epoch;
        this.busy = true;
        this.error = '';
        this.render();
        try {
            const response = await this.workspace.session.alignFloorPlan(reference.importId, { distance: {
                a: { u: points[0].u, v: points[0].v }, b: { u: points[1].u, v: points[1].v }, meters: value } });
            if (epoch !== this.epoch) return;
            // An undo while it was worked out (the underlay removed, replaced or moved, even if a redo brought it
            // back) or a preview opened drops the answer: it never puts back what the undo took away.
            if (!this._current(generation, token)) {
                this._staleAnswer('the scale');
                return;
            }
            const next = clone(this.currentReference());
            next.alignment = Object.assign({}, next.alignment, { metersPerDrawingUnit: response.metersPerDrawingUnit,
                unitSource: 'calibrated', confirmed: true });
            this.result = null;
            this.busy = false;
            await this._change(next, 'Scale set: 1 drawing unit is ' + round(response.metersPerDrawingUnit, 9)
                + ' m.');
        } catch (error) {
            if (epoch === this.epoch) this._fail(error);
        }
    };

    FloorPlanController.prototype.chooseUnit = function (name) {
        const reference = this.currentReference();
        const unit = UNITS.find(function (item) { return item[0] === name; });
        if (!reference || !unit) return;
        const next = clone(reference);
        next.alignment = Object.assign({}, next.alignment, { metersPerDrawingUnit: unit[1], unitSource: 'chosen',
            confirmed: true });
        this._change(next, 'Drawing unit: ' + unit[0] + '.');
    };

    FloorPlanController.prototype.setLayerVisible = function (layerId, visible) {
        const reference = this.currentReference();
        if (!reference) return;
        const next = clone(reference);
        let found = false;
        next.layers.forEach(function (layer) {
            if (layer.layerId === layerId) {
                layer.visible = visible;
                found = true;
            }
        });
        if (!found) next.layers.push({ layerId: layerId, visible: visible, role: 'reference' });
        this._change(next);
    };

    // What a layer shows (ROLE_OPTIONS): kept in the draft, else one undoable edit like the others.
    FloorPlanController.prototype.setLayerRole = function (layerId, role) {
        const reference = this.currentReference();
        if (!reference || !ROLE_OPTIONS.some(function (option) { return option[0] === role; })) return;
        const next = clone(reference);
        let found = false;
        next.layers.forEach(function (layer) {
            if (layer.layerId === layerId) {
                layer.role = role;
                found = true;
            }
        });
        if (!found) next.layers.push({ layerId: layerId, visible: true, role: role });
        this._change(next);
    };

    FloorPlanController.prototype._roleSelect = function (layer, reference) {
        const doc = this.document;
        const kept = (reference.layers || []).find(function (item) { return item.layerId === layer.layerId; });
        const role = kept && kept.role || 'reference';
        const select = html(doc, 'select', { className: 'ip-flw-floor-plan-role', 'data-fp-role': layer.layerId,
            'aria-label': 'What ' + layer.name + ' shows', title: 'What this layer shows', disabled: this.busy });
        ROLE_OPTIONS.forEach(function (option) {
            select.appendChild(html(doc, 'option', { value: option[0], selected: option[0] === role }, option[1]));
        });
        select.value = role;
        return select;
    };

    // The saved underlay's conversion: the panel's fields for its drawing (kept while it stays the same drawing).
    FloorPlanController.prototype._conversion = function () {
        const saved = this.draft ? null : this._savedReference();
        if (!saved) return null;
        if (!this.conversion || this.conversion.importId !== saved.importId) {
            this.conversion = { importId: saved.importId, form: newConversionForm(), answer: null };
        }
        return this.conversion;
    };

    // The server's answer for the saved layout as it is now: none once the layout was saved again or changed.
    FloorPlanController.prototype._conversionAnswer = function () {
        const conversion = this.conversion;
        const answer = conversion && conversion.answer;
        const state = this.workspace.state || {};
        return answer && answer.importId === conversion.importId && answer.baseRevision === state.baseRevision
            ? answer : null;
    };

    // Why the drawing cannot be converted just now ('' when it can). The server converts the saved layout.
    FloorPlanController.prototype._conversionProblem = function () {
        const state = this.workspace.state || {};
        const saved = this._savedReference();
        if (this.preview) return 'A preview is showing. Approve or dismiss it first.';
        if (!saved) return 'Add the drawing to the plan first.';
        if (!saved.alignment || saved.alignment.confirmed !== true) {
            return 'Choose the drawing\'s unit, or set its scale from a known length, first.';
        }
        if (state.dirty || !state.baseRevision) {
            return 'Save the layout first: the walls and rooms are found in the saved layout.';
        }
        return '';
    };

    // TARGET, a field of the Walls and rooms section, changed: the form keeps it, and a list on show is marked as made
    // before the change. Returns whether TARGET was one of those fields.
    FloorPlanController.prototype._editConversion = function (target) {
        const conversion = this._conversion();
        if (!conversion || !target || typeof target.hasAttribute !== 'function') return false;
        const form = conversion.form;
        if (target.hasAttribute('data-fp-setting')) {
            const name = target.getAttribute('data-fp-setting');
            if (name === 'replace') form.replace = target.checked === true;
            else if (CONVERSION_FIELDS.indexOf(name) >= 0) form[name] = String(target.value);
            else return false;
        } else if (target.hasAttribute('data-fp-outline')) {
            if (target.checked !== true) return true;
            form.loop = target.getAttribute('data-fp-outline');
        } else if (target.hasAttribute('data-fp-keep')) {
            const id = target.getAttribute('data-fp-keep');
            const rest = form.excluded.filter(function (item) { return item !== id; });
            form.excluded = target.checked === true ? rest : rest.concat([id]);
        } else if (target.hasAttribute('data-fp-room-type')) {
            const id = target.getAttribute('data-fp-room-type');
            if (target.value) form.types[id] = String(target.value);
            else delete form.types[id];
        } else {
            return false;
        }
        this._noteSettingsChanged();
        return true;
    };

    // Whether the list on show (ANSWER) can be staged for review: it is current, adds something and is not refused.
    FloorPlanController.prototype._reviewReady = function (answer, outdated) {
        const summary = answer && answer.conversion && answer.conversion.summary || {};
        return !this.busy && !this._conversionProblem() && !outdated && summary.operations > 0 && !summary.blocked;
    };

    FloorPlanController.prototype._outdated = function (answer) {
        const roles = rolesOf(this._savedReference());
        return answer.settingsKey !== JSON.stringify(conversionSettings(this.conversion.form, roles));
    };

    // A field changed while a list is on show: the list is marked as made before the change, and the review (which
    // stages the list on show) waits for it to be updated. In place, so the field keeps its focus.
    FloorPlanController.prototype._noteSettingsChanged = function () {
        const answer = this._conversionAnswer();
        if (!this.panel || !answer) return;
        const outdated = this._outdated(answer);
        const note = this.panel.querySelector('[data-fp-outdated]');
        if (note) {
            note.hidden = !outdated;
            note.textContent = outdated ? OUTDATED_NOTE : '';
        }
        const review = this.panel.querySelector('[data-fp-action="review"]');
        if (review) review.disabled = !this._reviewReady(answer, outdated);
    };

    // Asks the server what the saved underlay converts to (STAGE "candidates"), or stages that as a change and shows it
    // on the plan for review (STAGE "proposal"): Approve adds it to the layout, Dismiss leaves the layout as it is.
    FloorPlanController.prototype.convert = async function (stage) {
        const conversion = this._conversion();
        if (!conversion) return;
        const problem = this._conversionProblem();
        if (problem) {
            this.error = problem;
            this.render();
            return;
        }
        const session = this.workspace.session;
        if (!session || typeof session.convertFloorPlan !== 'function'
                || (stage === 'proposal' && typeof session.fetchAndInstallOperationProposal !== 'function')) {
            this._fail(new Error('Converting the drawing is unavailable.'));
            return;
        }
        const state = this.workspace.state;
        const layout = state.layout || {};
        const revision = state.baseRevision;
        const settings = conversionSettings(conversion.form, rolesOf(this._savedReference()));
        const epoch = this.epoch;
        this.conversionSequence += 1;
        const sequence = this.conversionSequence;
        const current = function () {
            return !this.disposed && epoch === this.epoch && sequence === this.conversionSequence;
        }.bind(this);
        this.busy = true;
        this.error = '';
        this.message = stage === 'proposal' ? 'Preparing the change for review...' : 'Finding walls and rooms...';
        this.render();
        try {
            const answer = await session.convertFloorPlan(conversion.importId,
                { baseRevision: revision, settings: settings, stage: stage });
            if (!current()) return;
            conversion.answer = { importId: conversion.importId, baseRevision: revision,
                settingsKey: JSON.stringify(settings), conversion: answer.conversion };
            if (stage === 'proposal') {
                await session.fetchAndInstallOperationProposal({
                    siteId: layout.association && layout.association.siteId,
                    layoutId: layout.layoutId,
                    revision: revision,
                    proposalId: answer.proposal && answer.proposal.proposalId,
                }, { applyDirectly: false });
                if (!current()) return;
                this.conversionReview = { revision: revision, shown: this.preview };
                this.message = 'The walls and rooms are on the plan to review. Approve adds them to the layout; '
                    + 'Dismiss leaves it as it is.';
            } else {
                this.message = '';
            }
            this.busy = false;
            this.render();
        } catch (error) {
            if (!current()) return;
            this.message = '';
            this._fail(error);
        }
    };

    // The Walls and rooms section: the settings the layers' roles call for, the list of what the drawing converts to,
    // and the review.
    FloorPlanController.prototype._renderConversion = function (panel) {
        const conversion = this._conversion();
        if (!conversion) return;
        const doc = this.document;
        const roles = rolesOf(this._savedReference());
        const section = html(doc, 'div', { className: 'ip-flw-floor-plan-convert', role: 'group',
            'aria-label': 'Walls and rooms from the drawing', 'data-fp-convert': 'true' });
        panel.appendChild(section);
        section.appendChild(html(doc, 'div', { className: 'ip-flw-floor-plan-heading' }, 'Walls and rooms'));
        if (!CONVERTED_ROLES.some(function (role) { return roles.has(role); })) {
            section.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-note' }, 'To turn the drawing into '
                + 'walls and rooms, choose above what its layers show: walls, room outlines or the building outline.'));
            return;
        }
        const form = conversion.form;
        const busy = this.busy;
        const field = function (name, label, step) {
            const row = html(doc, 'label', { className: 'ip-flw-floor-plan-field' }, label);
            const input = html(doc, 'input', { type: 'number', min: '0', step: step, 'data-fp-setting': name,
                disabled: busy });
            input.value = form[name];
            row.appendChild(input);
            section.appendChild(row);
        };
        if (WALL_ROLES.some(function (role) { return roles.has(role); })) {
            field('wallHeight', 'Wall height (m)', '0.1');
            if (roles.has('wall_centerline')) field('wallThickness', 'Wall thickness for center lines (m)', '0.01');
            if (roles.has('wall_faces')) field('maxThickness', 'Thickest wall drawn as two faces (m)', '0.01');
        }
        if (roles.has('perimeter')) {
            field('outlineHeight', 'Outer wall height (m)', '0.1');
            field('outlineThickness', 'Outer wall thickness (m)', '0.01');
        }
        if (roles.has('room_boundary')) {
            const row = html(doc, 'label', { className: 'ip-flw-floor-plan-field' }, 'Rooms become zones of type');
            const select = html(doc, 'select', { 'data-fp-setting': 'zoneType', disabled: busy });
            select.appendChild(html(doc, 'option', { value: '', selected: !form.zoneType }, 'Choose...'));
            ZONE_TYPE_OPTIONS.forEach(function (option) {
                select.appendChild(html(doc, 'option', { value: option[0], selected: option[0] === form.zoneType },
                    option[1]));
            });
            select.value = form.zoneType;
            row.appendChild(select);
            section.appendChild(row);
        }
        const problem = this._conversionProblem();
        if (problem) section.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-warning' }, problem));
        const answer = this._conversionAnswer();
        section.appendChild(actionButton(doc, 'find', answer ? 'Update the list' : 'Find walls and rooms',
            busy || Boolean(problem)));
        if (!answer) return;
        const outdated = this._outdated(answer);
        this._renderCandidates(section, answer.conversion, form, outdated);
        section.appendChild(actionButton(doc, 'review', 'Review the change', !this._reviewReady(answer, outdated)));
    };

    FloorPlanController.prototype._renderCandidates = function (section, result, form, outdated) {
        const doc = this.document;
        const note = function (text, className) {
            section.appendChild(html(doc, 'p', { className: className || 'ip-flw-floor-plan-note' }, text));
        };
        const summary = result.summary || {};
        section.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-warning', 'data-fp-outdated': 'true',
            hidden: !outdated }, outdated ? OUTDATED_NOTE : ''));
        [['Walls', summary.walls], ['Rooms', summary.rooms], ['Building outline', summary.outlines]].forEach(
            function (part) {
                const states = Object.keys(part[1] || {});
                if (!states.length) return;
                note(part[0] + ': ' + states.map(function (state) {
                    return part[1][state] + ' ' + (CANDIDATE_STATES[state] || state);
                }).join(', ') + '.');
            });
        if (summary.blocked) note(summary.blocked.message, 'ip-flw-floor-plan-warning');
        const outlines = Array.isArray(result.outlines) ? result.outlines : [];
        if (outlines.some(function (row) { return row.reason === 'replace_needed' || row.replaces; })) {
            const row = html(doc, 'div', { className: 'ip-flw-layer-check' });
            const input = html(doc, 'input', { id: 'ip-flw-fp-replace', type: 'checkbox', 'data-fp-setting': 'replace',
                disabled: this.busy });
            input.checked = form.replace === true;
            row.appendChild(input);
            row.appendChild(html(doc, 'label', { for: 'ip-flw-fp-replace' }, 'Replace the outer walls on the plan'));
            section.appendChild(row);
        }
        const rows = [];
        outlines.forEach(function (row) { rows.push(['outline', row]); });
        (result.walls || []).forEach(function (row) { rows.push(['wall', row]); });
        (result.rooms || []).forEach(function (row) { rows.push(['room', row]); });
        if (!rows.length) {
            note('Nothing on those layers converts.');
        } else {
            const list = html(doc, 'div', { className: 'ip-flw-floor-plan-candidates', 'data-fp-candidates': 'true',
                role: 'group', 'aria-label': 'What the drawing converts to' });
            rows.slice(0, LISTED_CANDIDATES).forEach(function (item) {
                list.appendChild(this._candidateRow(item[0], item[1], form, outlines.length > 1));
            }, this);
            section.appendChild(list);
            if (rows.length > LISTED_CANDIDATES) {
                note('The first ' + LISTED_CANDIDATES + ' of ' + rows.length + ' are listed.');
            }
        }
        const left = result.unconvertedCounts || {};
        const reasons = Object.keys(left);
        if (reasons.length) {
            const messages = {};
            (result.unconverted || []).forEach(function (row) {
                if (!messages[row.reason]) messages[row.reason] = row.message;
            });
            note('Left as drawing:');
            reasons.forEach(function (reason) { note(left[reason] + ' - ' + (messages[reason] || reason)); });
        }
    };

    // One candidate: what it is, how it stands, a box to leave it out (or, among several outlines, the choice of the
    // building), and a room's own zone type.
    FloorPlanController.prototype._candidateRow = function (kind, row, form, choosing) {
        const doc = this.document;
        const busy = this.busy;
        const line = html(doc, 'div', { className: 'ip-flw-floor-plan-candidate', 'data-fp-candidate': row.candidateId,
            'data-state': row.state });
        const head = html(doc, 'div', { className: 'ip-flw-layer-check' });
        const id = 'ip-flw-fp-c-' + row.candidateId;
        const open = row.state === 'new' || row.state === 'waiting' || row.state === 'excluded';
        let text;
        if (kind === 'wall') {
            text = row.label + ': ' + round(row.lengthMeters, 2) + ' m long, ' + round(row.thicknessMeters, 3)
                + ' m thick';
        } else if (kind === 'room') {
            text = row.label + ': ' + round(row.areaSquareMeters, 1) + ' m2';
        } else {
            text = 'Outline: ' + (finite(row.areaSquareMeters) ? round(row.areaSquareMeters, 1) + ' m2, ' : '')
                + (row.boundary || []).length + ' corners, walls ' + round(row.thicknessMeters, 3) + ' m thick';
        }
        let input = null;
        if (kind === 'outline' && choosing) {
            input = html(doc, 'input', { id: id, type: 'radio', name: 'ip-flw-fp-outline',
                'data-fp-outline': row.candidateId, disabled: busy });
            input.checked = form.loop === row.candidateId;
        } else if (open) {
            input = html(doc, 'input', { id: id, type: 'checkbox', 'data-fp-keep': row.candidateId, disabled: busy });
            input.checked = form.excluded.indexOf(row.candidateId) < 0;
        }
        if (input) head.appendChild(input);
        head.appendChild(html(doc, 'label', input ? { for: id } : {}, text));
        line.appendChild(head);
        line.appendChild(html(doc, 'div', { className: 'ip-flw-floor-plan-state' },
            (CANDIDATE_STATES[row.state] || row.state) + (row.message ? ': ' + row.message : '')));
        if (kind === 'room' && open) {
            const select = html(doc, 'select', { 'data-fp-room-type': row.candidateId,
                'aria-label': 'Zone type for ' + row.label, disabled: busy });
            const own = form.types[row.candidateId] || '';
            select.appendChild(html(doc, 'option', { value: '', selected: !own }, 'Zone type: as above'));
            ZONE_TYPE_OPTIONS.forEach(function (option) {
                select.appendChild(html(doc, 'option', { value: option[0], selected: option[0] === own }, option[1]));
            });
            select.value = own;
            line.appendChild(select);
        }
        return line;
    };

    FloorPlanController.prototype.previewOpacity = function (opacity) {
        const adapter = this._adapter();
        if (adapter && typeof adapter.setFloorPlanOpacity === 'function') adapter.setFloorPlanOpacity(opacity);
    };

    FloorPlanController.prototype.setOpacity = function (opacity) {
        const reference = this.currentReference();
        if (!reference || !finite(opacity)) return;
        const next = clone(reference);
        next.opacity = Math.min(1, Math.max(0.05, round(opacity, 2)));
        if (next.opacity === reference.opacity) return;
        this._change(next);
    };

    FloorPlanController.prototype._build = function () {
        if (this.panel) return this.panel;
        const panel = html(this.document, 'section', {
            className: 'ip-flw-floor-plan-panel',
            'aria-label': 'Floor plan underlay',
            'data-floor-plan-panel': 'true',
            hidden: true,
        });
        panel.addEventListener('click', this._onClick.bind(this));
        panel.addEventListener('change', this._onChange.bind(this));
        panel.addEventListener('input', this._onInput.bind(this));
        this.panel = panel;
        if (this.workspace.viewportStack) this.workspace.viewportStack.appendChild(panel);
        return panel;
    };

    FloorPlanController.prototype._onClick = function (event) {
        const target = event.target && typeof event.target.closest === 'function'
            ? event.target.closest('[data-fp-action]') : null;
        const action = target && target.getAttribute('data-fp-action');
        if (!action || (this.busy && action !== 'close')) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (action === 'close') this.close();
        else if (action === 'choose') this._chooseFile();
        else if (action === 'add') this.addDraft();
        else if (action === 'cancel-draft') this.close();
        else if (action === 'remove') this.remove();
        else if (action === 'align') this.startPicking('align');
        else if (action === 'measure') this.startPicking('measure');
        else if (action === 'cancel-pick') this.cancelPicking();
        else if (action === 'apply-alignment') this.applyAlignment();
        else if (action === 'find') this.convert('candidates');
        else if (action === 'review') this.convert('proposal');
        else if (action === 'apply-distance') {
            const input = this.panel.querySelector('[data-fp-distance]');
            this.applyDistance(input ? input.value : NaN);
        }
    };

    FloorPlanController.prototype._onChange = function (event) {
        const target = event.target;
        if (!target || this.busy) return;
        if (target.hasAttribute('data-fp-file')) {
            const file = target.files && target.files[0];
            target.value = '';
            this.importFile(file);
        } else if (target.hasAttribute('data-fp-layer')) {
            this.setLayerVisible(target.getAttribute('data-fp-layer'), target.checked === true);
        } else if (target.hasAttribute('data-fp-opacity')) {
            this.setOpacity(Number(target.value) / 100);
        } else if (target.hasAttribute('data-fp-unit')) {
            this.chooseUnit(target.value);
        } else if (target.hasAttribute('data-fp-show')) {
            this.hidden = target.checked !== true;
            this._refresh();
            this.render();
        } else if (target.hasAttribute('data-fp-role')) {
            this.setLayerRole(target.getAttribute('data-fp-role'), String(target.value));
        } else {
            this._editConversion(target);
        }
    };

    FloorPlanController.prototype._onInput = function (event) {
        const target = event.target;
        if (target && target.hasAttribute('data-fp-opacity')) this.previewOpacity(Number(target.value) / 100);
        if (target && target.hasAttribute('data-fp-distance')) this.distanceText = String(target.value);
        if (target && target.hasAttribute('data-fp-setting') && !this.busy) this._editConversion(target);
    };

    FloorPlanController.prototype.render = function () {
        if (this.disposed) return;
        const panel = this._build();
        panel.hidden = !this.isOpen;
        if (!this.isOpen) return;
        const doc = this.document;
        const oldList = panel.querySelector('[data-fp-candidates]');
        const scroll = { panel: panel.scrollTop || 0, list: oldList ? oldList.scrollTop || 0 : 0 };
        while (panel.firstChild) panel.removeChild(panel.firstChild);
        const header = html(doc, 'div', { className: 'ip-flw-floor-plan-header' });
        header.appendChild(html(doc, 'div', { className: 'ip-flw-layer-panel-title' }, 'Floor plan'));
        header.appendChild(html(doc, 'button', { type: 'button', className: 'ip-flw-floor-plan-close',
            'data-fp-action': 'close', 'aria-label': 'Close the floor plan panel' }, 'Close'));
        panel.appendChild(header);
        panel.appendChild(html(doc, 'input', { type: 'file', accept: '.dxf,application/dxf,image/vnd.dxf',
            'data-fp-file': 'true', hidden: true, 'aria-hidden': 'true', tabindex: '-1' }));
        if (this.error) panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-error', role: 'alert' },
            this.error));
        if (this.message) panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-note',
            role: 'status' }, this.message));
        const reference = this.currentReference();
        if (this.preview && this.draft) {
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-note' }, 'A preview is showing. This '
                + 'drawing shows again once it closes.'));
        }
        const button = function (action, label, disabled) {
            return html(doc, 'button', { type: 'button', className: 'ip-flw-layer-show-all', 'data-fp-action': action,
                disabled: Boolean(disabled) }, label);
        };
        if (!reference) {
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-note' }, 'Trace over a DXF drawing '
                + 'of the building. It shows in the Plan view only and moves nothing.'));
            panel.appendChild(button('choose', this.busy ? 'Reading...' : 'Import DXF...', this.busy));
            return;
        }
        const entry = this._geometryEntry(reference.importId);
        const geometry = entry && entry.geometry;
        const manifest = this.draft ? this.draft.manifest : geometry;
        panel.appendChild(html(doc, 'div', { className: 'ip-flw-floor-plan-name',
            title: reference.sourceName || reference.label }, reference.sourceName || reference.label));
        if (entry && entry.error && !geometry) {
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-error', role: 'alert' },
                'The drawing for this underlay is not stored here. Import the DXF again to show it.'));
        } else if (!geometry) {
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-note' }, 'Loading the drawing...'));
        }
        const alignment = reference.alignment;
        const declared = manifest && manifest.units || {};
        let unitText;
        if (alignment.unitSource === 'header') unitText = 'Units: ' + (declared.name || 'declared') + ' (from the file)';
        else if (alignment.unitSource === 'calibrated') unitText = 'Scale: 1 unit = ' + round(alignment.metersPerDrawingUnit, 9)
            + ' m (measured)';
        else unitText = 'Units: ' + (unitName(alignment.metersPerDrawingUnit) || (alignment.metersPerDrawingUnit + ' m'))
            + (alignment.confirmed ? ' (chosen)' : ' (not set in the file)');
        panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-units' }, unitText));
        if (!alignment.confirmed) {
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-warning' }, 'The file does not say what '
                + 'unit it is drawn in. Choose it, or measure a length you know.'));
            const select = html(doc, 'select', { 'data-fp-unit': 'true', 'aria-label': 'Drawing unit',
                disabled: this.busy });
            select.appendChild(html(doc, 'option', { value: '' }, 'Choose the unit...'));
            UNITS.forEach(function (unit) { select.appendChild(html(doc, 'option', { value: unit[0] }, unit[0])); });
            panel.appendChild(select);
        }
        // The reader's own unit warning is the prompt above (shown only while the unit is open).
        (manifest && manifest.warnings || []).filter(function (warning) {
            return warning.code !== 'units_unresolved';
        }).slice(0, 4).forEach(function (warning) {
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-warning' }, warning.message));
        });
        if (this.picking) {
            const prompt = PROMPTS[this.picking.mode][this.picking.points.length];
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-prompt', role: 'status' }, prompt));
            panel.appendChild(button('cancel-pick', 'Cancel'));
        } else if (this.result && this.result.kind === 'align') {
            const response = this.result.response;
            const lines = ['Turn ' + round(response.alignment.rotationDegrees, 2) + ' degrees',
                'Scale 1 unit = ' + round(response.alignment.metersPerDrawingUnit, 9) + ' m',
                'Points off by up to ' + round(response.maxResidualMeters, 3) + ' m'];
            if (response.scale !== 'fit' && Math.abs(response.scaleRatio - 1) > 0.005) {
                lines.push('The points suggest a scale ' + round(response.scaleRatio, 3) + ' times the unit: check '
                    + 'the unit or the points.');
            }
            lines.forEach(function (line) {
                panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-note' }, line));
            });
            panel.appendChild(button('apply-alignment', 'Apply alignment', this.busy));
            panel.appendChild(button('cancel-pick', 'Discard'));
        } else if (this.result && this.result.kind === 'measure') {
            panel.appendChild(html(doc, 'p', { className: 'ip-flw-floor-plan-note' }, 'Drawing length: '
                + round(this.result.drawingDistance, 4) + ' units. Its real length in meters:'));
            const length = html(doc, 'input', { type: 'number', min: '0.1', step: 'any', 'data-fp-distance': 'true',
                'aria-label': 'Real length in meters' });
            length.value = this.distanceText;
            panel.appendChild(length);
            panel.appendChild(button('apply-distance', 'Set scale', this.busy));
            panel.appendChild(button('cancel-pick', 'Discard'));
        }
        // Layers that draw nothing (CAD files carry many: 0, Defpoints, unused standards) are left out of the list.
        const drawn = (manifest && Array.isArray(manifest.layers) ? manifest.layers : []).filter(function (layer) {
            return (layer.entities || 0) + (layer.texts || 0) > 0;
        });
        if (drawn.length) {
            const list = html(doc, 'div', { className: 'ip-flw-floor-plan-layers', role: 'group',
                'aria-label': 'Drawing layers' });
            const hidden = hiddenLayers(reference);
            drawn.forEach(function (layer) {
                const id = 'ip-flw-fp-layer-' + layer.layerId;
                const row = html(doc, 'div', { className: 'ip-flw-layer-check' });
                const input = html(doc, 'input', { id: id, type: 'checkbox', 'data-fp-layer': layer.layerId,
                    disabled: this.busy });
                input.checked = !hidden.has(layer.layerId);
                const count = (layer.entities || 0) + (layer.texts || 0);
                row.appendChild(input);
                row.appendChild(html(doc, 'label', { for: id, className: 'ip-flw-floor-plan-layer-name',
                    title: layer.name }, layer.name + ' (' + count + ')'));
                row.appendChild(this._roleSelect(layer, reference));
                list.appendChild(row);
            }, this);
            panel.appendChild(list);
        }
        const opacity = html(doc, 'label', { className: 'ip-flw-floor-plan-opacity' }, 'Strength ');
        const slider = html(doc, 'input', { type: 'range', min: '5', max: '100', step: '5',
            'data-fp-opacity': 'true', 'aria-label': 'Underlay strength', disabled: this.busy });
        slider.value = String(Math.round(reference.opacity * 100));
        opacity.appendChild(slider);
        panel.appendChild(opacity);
        const show = html(doc, 'div', { className: 'ip-flw-layer-check' });
        const showInput = html(doc, 'input', { id: 'ip-flw-fp-show', type: 'checkbox', 'data-fp-show': 'true',
            disabled: Boolean(this.picking) });
        showInput.checked = !this.hidden;
        show.appendChild(showInput);
        show.appendChild(html(doc, 'label', { for: 'ip-flw-fp-show' }, 'Show the drawing'));
        panel.appendChild(show);
        if (!this.picking && !this.result) {
            panel.appendChild(button('align', 'Align by two points', this.busy || !geometry));
            panel.appendChild(button('measure', 'Set scale from a known length', this.busy || !geometry));
        }
        if (this.draft) {
            panel.appendChild(button('add', 'Add to plan', this.busy));
            panel.appendChild(button('cancel-draft', 'Cancel', this.busy));
        } else {
            panel.appendChild(button('choose', 'Replace with another DXF...', this.busy));
            panel.appendChild(button('remove', 'Remove from plan', this.busy));
            if (!this.picking && !this.result) this._renderConversion(panel);
        }
        panel.scrollTop = scroll.panel;
        const list = panel.querySelector('[data-fp-candidates]');
        if (list) list.scrollTop = scroll.list;
    };

    // The workspace is going away: answers still on their way are dropped and nothing is drawn or saved again.
    FloorPlanController.prototype.dispose = function () {
        this.epoch += 1;
        this.disposed = true;
        this.busy = false;
        this.draft = null;
        this.picking = null;
        this.result = null;
        this.generation += 1;
        this.suspendedTool = null;
        this.pressOwned = false;
        this.sequenceOwned = false;
        this.finishingPress = null;
        this.conversion = null;
        this.conversionReview = null;
        if (this.panel && this.panel.parentNode) this.panel.parentNode.removeChild(this.panel);
        this.panel = null;
    };

    function attach(workspace) {
        return new FloorPlanController(workspace);
    }

    return Object.freeze({
        KEY: KEY,
        MAX_LABELS: MAX_LABELS,
        MAX_LINES_PER_LABEL: MAX_LINES_PER_LABEL,
        MAX_LABEL_LINES: MAX_LABEL_LINES,
        UNITS: UNITS,
        ROLE_OPTIONS: ROLE_OPTIONS,
        ZONE_TYPE_OPTIONS: ZONE_TYPE_OPTIONS,
        conversionSettings: conversionSettings,
        referenceOf: referenceOf,
        toLayout: toLayout,
        toDrawing: toDrawing,
        screenMatrix: screenMatrix,
        contentKey: contentKey,
        buildUnderlayContent: buildUnderlayContent,
        createSnapIndex: createSnapIndex,
        nearestVertex: nearestVertex,
        newReference: newReference,
        attach: attach,
        FloorPlanController: FloorPlanController,
    });
}));
