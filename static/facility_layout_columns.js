(function (root, factory) {
    const dialogs = typeof module === 'object' && module.exports
        ? require('./facility_layout_authoring_dialog.js') : root.InspectorProFacilityAuthoringDialog;
    const api = factory(dialogs);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityColumns = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (dialogs) {
    'use strict';

    // Columns (ai_inspector/facility_layout/columns.py): native structural columns, rectangular or round, saved in
    // extensions.facilityColumns. The server checks every value and works out each outline; this dialog only edits
    // the settings. A column read from a DXF keeps its source (the drawing entity it came from).
    const DEFAULTS = { label: 'Column', shape: 'rectangle', widthMeters: 0.4, depthMeters: 0.4, rotationDegrees: 0,
        diameterMeters: 0.4, heightMeters: 6, color: '#8f969c' };

    function settings(layout) {
        const value = layout && layout.extensions && layout.extensions.facilityColumns;
        return (value && Array.isArray(value.columns) ? value.columns : []).map(function (column) {
            const row = JSON.parse(JSON.stringify(column));
            delete row.footprint;
            return row;
        });
    }

    function libraryStore(workspace) {
        const options = workspace.options && workspace.options.threeOptions;
        return options && options.facilityLibrary || null;
    }

    function open(workspace) {
        const state = workspace.session.getState(), layout = state.layout;
        const plan = layout.extensions && layout.extensions.facilityPlan;
        if (!plan) throw new Error('Set the facility plan dimensions first.');
        const floor = layout.coordinateFrame && Number.isFinite(layout.coordinateFrame.floorElevation)
            ? layout.coordinateFrame.floorElevation : 0;
        const entries = settings(layout);
        const picked = entries.find(function (column) { return state.selection.indexOf(column.columnId) >= 0; });
        const ui = dialogs.open(workspace, 'Columns', function () {
            const column = value();
            const index = entries.findIndex(function (row) { return row.columnId === column.columnId; });
            const columns = index >= 0
                ? entries.map(function (row, at) { return at === index ? column : row; })
                : entries.concat([column]);
            return workspace.session.setColumns({ version: 1, columns: columns });
        });
        const selected = ui.field('Column', 'select', picked ? picked.columnId : '',
            [{ value: '', label: 'New column' }].concat(entries.map(function (column) {
                return { value: column.columnId, label: column.label };
            })));
        const name = ui.field('Column name', 'text', DEFAULTS.label);
        name.maxLength = 120;
        const shape = ui.field('Shape', 'select', DEFAULTS.shape,
            [{ value: 'rectangle', label: 'Rectangular' }, { value: 'circle', label: 'Round' }]);
        const x = ui.field('Center X (m)', 'number', Math.min(5, plan.widthMeters / 2));
        const z = ui.field('Center Z (m)', 'number', Math.min(5, plan.depthMeters / 2));
        const width = ui.field('Width along X (m)', 'number', DEFAULTS.widthMeters);
        const depth = ui.field('Depth along Z (m)', 'number', DEFAULTS.depthMeters);
        const rotation = ui.field('Rotation (degrees)', 'number', DEFAULTS.rotationDegrees);
        const diameter = ui.field('Diameter (m)', 'number', DEFAULTS.diameterMeters);
        const height = ui.field('Height (m)', 'number', DEFAULTS.heightMeters);
        const elevation = ui.field('Base elevation (m)', 'number', floor);
        const finish = ui.field('Finish', 'select', '', [{ value: '', label: 'Plain color' }]);
        const color = ui.field('Color', 'color', DEFAULTS.color);
        const source = ui.el('p', { class: 'ip-flw-authoring-note', 'data-column-source': '' });
        ui.body.append(source);
        const remove = ui.el('button', { type: 'button', 'aria-label': 'Delete column', title: 'Delete column' });
        remove.append(ui.el('img', { src: '/static/assets/facility-layout-ribbon-icons/svg/trash.svg',
            width: 18, height: 18, alt: '' }));
        ui.body.append(remove);
        let current = null;

        function addFinish(id, label) {
            if (!id || Array.from(finish.options).some(function (option) { return option.value === id; })) return;
            finish.append(ui.el('option', { value: id }, label || id));
        }
        function fillFinishes(library) {
            if (!library || !library.appearances) return;
            const keep = finish.value;
            Array.from(library.appearances.values()).forEach(function (row) {
                addFinish(row.appearanceId, row.label || row.appearanceId);
            });
            finish.value = keep;
        }
        // The layout's own finishes (facilityAppearances.custom) first, then the library's as it loads.
        const own = layout.extensions && layout.extensions.facilityAppearances;
        (own && Array.isArray(own.custom) ? own.custom : []).forEach(function (row) {
            if (row && typeof row.appearanceId === 'string') addFinish(row.appearanceId, row.label || row.appearanceId);
        });
        const store = libraryStore(workspace);
        if (store && typeof store.get === 'function') {
            if (store.get()) fillFinishes(store.get());
            else if (typeof store.load === 'function') {
                Promise.resolve().then(function () { return store.load(); }).then(fillFinishes, function () {});
            }
        }

        function show() {
            const round = shape.value === 'circle';
            [width, depth, rotation].forEach(function (node) { node.parentElement.hidden = round; });
            diameter.parentElement.hidden = !round;
            color.parentElement.hidden = Boolean(finish.value);
            remove.disabled = !selected.value;
        }
        function load() {
            current = entries.find(function (row) { return row.columnId === selected.value; }) || null;
            const column = current || Object.assign({}, DEFAULTS, {
                center: { x: Number(x.value), z: Number(z.value) }, baseElevation: floor, appearance: null });
            name.value = column.label;
            shape.value = column.shape;
            x.value = column.center.x;
            z.value = column.center.z;
            width.value = column.widthMeters === undefined ? DEFAULTS.widthMeters : column.widthMeters;
            depth.value = column.depthMeters === undefined ? DEFAULTS.depthMeters : column.depthMeters;
            rotation.value = column.rotationDegrees === undefined ? 0 : column.rotationDegrees;
            diameter.value = column.diameterMeters === undefined ? DEFAULTS.diameterMeters : column.diameterMeters;
            height.value = column.heightMeters;
            elevation.value = column.baseElevation;
            const appearance = column.appearance || {};
            if (appearance.appearanceId) addFinish(appearance.appearanceId, appearance.appearanceId);
            finish.value = appearance.appearanceId || '';
            color.value = typeof appearance.color === 'string' ? appearance.color : DEFAULTS.color;
            const from = current && current.source;
            source.textContent = from
                ? 'From drawing ' + from.referenceId + ', entity ' + from.entityId + ' (kept when you edit it).' : '';
            show();
        }
        function appearance() {
            if (!finish.value) return { color: color.value };
            const before = current && current.appearance;
            return before && before.appearanceId === finish.value ? JSON.parse(JSON.stringify(before))
                : { appearanceId: finish.value };
        }
        function value() {
            const id = selected.value || 'col-' + workspace.document.defaultView.crypto.randomUUID();
            const column = { columnId: id, label: name.value, shape: shape.value,
                center: { x: Number(x.value), z: Number(z.value) } };
            if (shape.value === 'circle') column.diameterMeters = Number(diameter.value);
            else {
                column.widthMeters = Number(width.value);
                column.depthMeters = Number(depth.value);
                column.rotationDegrees = Number(rotation.value);
            }
            column.heightMeters = Number(height.value);
            column.baseElevation = Number(elevation.value);
            column.appearance = appearance();
            if (current && current.source) column.source = JSON.parse(JSON.stringify(current.source));
            return column;
        }

        selected.addEventListener('change', load);
        [shape, finish].forEach(function (node) { node.addEventListener('change', show); });
        remove.addEventListener('click', function () {
            ui.commit(function () {
                return workspace.session.setColumns({ version: 1, columns: entries.filter(function (row) {
                    return row.columnId !== selected.value;
                }) });
            });
        });
        load();
        return ui;
    }

    return { settings: settings, open: open };
}));
