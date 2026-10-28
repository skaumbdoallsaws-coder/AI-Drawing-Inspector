/**
 * Appearances, Scenes and Signs panel for the Assembly tab (docs/assembly-signs-scenes-plan.md, AD5).
 *
 * The Facility library on the loaded machine: finishes on the whole machine, the selected parts or the selected
 * faces, a lighting scene, and ISO 7010 signs or imported logos on a side of a part or on a face. Faces are selected
 * in the 3D view (a click on the machine, as in SOLIDWORKS). A sign or finish can also be dragged onto the 3D view,
 * where it lands on the part under the pointer, or on the selected faces when dropped on one. Every change is written to the assembly's appearance on the server (the same document Sage writes), so
 * the view, Sage and the Specification Sheet's picture agree. Faces: docs/assembly-face-selection-plan.md.
 *
 * The panel owns no data: `viewer` reads and writes through the app's routes and the 3D view.
 */
(function (root, factory) {
    'use strict';
    const library = root.InspectorProFacilityLibrary
        || (typeof require === 'function' ? require('./facility_layout_library.js') : null);
    const api = factory(library);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProAssemblyLibraryPanel = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (libraryApi) {
    'use strict';

    const DRAG_TYPE = 'application/x-inspectorpro-assembly-library';
    const SIDES = [['front', 'Front'], ['back', 'Back'], ['left', 'Left'], ['right', 'Right'], ['top', 'Top'],
        ['bottom', 'Bottom']];
    const ROTATIONS = [['0', 'Upright'], ['90', 'Turned left'], ['-90', 'Turned right'], ['180', 'Upside down']];
    // Where the 3D view could not draw a sign (it reports each one to the server).
    const STATUS_NOTES = { no_surface: 'not drawn: no surface faces that way there',
        part_missing: 'not drawn: the part is not in the view', image_missing: 'not drawn: its picture is missing',
        no_fit: 'not drawn: no flat, uncovered spot there, even much smaller',
        face_missing: 'not drawn: its face is not on the model any more' };
    // What a face is, as the pane names it (docs/assembly-face-selection-plan.md).
    const FACE_KINDS = { plane: 'Flat face', cylinder: 'Cylindrical face', cone: 'Conical face',
        sphere: 'Spherical face', torus: 'Rounded face', other: 'Curved face' };

    function faceKey(ref) { return ref.part + '#' + (Number(ref.mesh) || 0) + ':' + ref.face; }

    // A face as the store keeps it: which copy of the part, its number there and its fingerprint.
    function faceRef(ref) {
        const kept = { mesh: Number(ref.mesh) || 0, face: ref.face, fingerprint: ref.fingerprint };
        if (ref.approximate) kept.approximate = true;
        return kept;
    }

    function storedFace(row) {
        return Object.assign({ part: row.part }, faceRef(row), { finish: row.finish });
    }

    function element(doc, tag, attributes, text) {
        const node = doc.createElement(tag);
        Object.keys(attributes || {}).forEach(function (key) {
            const value = attributes[key];
            if (value === null || value === undefined || value === false) return;
            if (key === 'className') node.className = value;
            else if (value === true) node.setAttribute(key, '');
            else node.setAttribute(key, String(value));
        });
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function clamp(value, low, high, fallback) {
        const number = Number(value);
        if (!Number.isFinite(number)) return fallback;
        return Math.min(high, Math.max(low, number));
    }

    // The fields a sign keeps when the list is written back (the server adds the resolved ones again).
    function storedSign(row) {
        const kept = { signId: row.signId, label: row.label, part: row.part, side: row.side, across: row.across,
            up: row.up, widthMeters: row.widthMeters, rotationDegrees: row.rotationDegrees };
        if (row.decalId) kept.decalId = row.decalId;
        else kept.imageId = row.imageId;
        if (row.anchor) kept.anchor = row.anchor;
        if (row.face) kept.face = faceRef(row.face);
        return kept;
    }

    const WORDED_ATTRIBUTES = ['placeholder', 'aria-label', 'title'];

    function createAssemblyLibraryPanel(options) {
        const settings = options || {};
        const doc = settings.document;
        const host = settings.host;
        const store = settings.store;
        const viewer = settings.viewer;
        if (!doc || !host || !store || !viewer) {
            throw new Error('The assembly library panel needs a document, host, library store and viewer.');
        }
        // The same pane serves one part in the 3D Model tab: the library sections it shows (appearances, scenes,
        // decals for safety signs, logos; all by default) and its words as [from, to] pairs, applied in order.
        const sections = new Set(Array.isArray(settings.sections) ? settings.sections
            : ['appearances', 'scenes', 'decals', 'logos']);
        const words = (Array.isArray(settings.words) ? settings.words : []).filter(function (pair) {
            return Array.isArray(pair) && pair[0] && typeof pair[1] === 'string';
        });

        const state = {
            node: { kind: 'machine', id: 'machine' },
            expanded: new Set(),
            query: '',
            selected: null,
            target: 'whole',
            color: null,
            part: '',
            side: 'front',
            width: null,
            rotation: '0',
            appearance: null,
            appearanceFor: '',
            busy: false,
            loading: null,
        };
        let destroyed = false;

        // ---- DOM skeleton -------------------------------------------------------
        const panel = element(doc, 'section', { className: 'ip-flib', 'data-scope': 'assembly',
            'aria-label': 'Appearances, scenes and signs on the machine' });
        const head = element(doc, 'div', { className: 'ip-flib-head' });
        const title = element(doc, 'span', { className: 'ip-flib-title' }, 'Appearances, Scenes & Signs');
        const scopeLabel = element(doc, 'span', { className: 'ip-flib-scope-label' });
        head.append(title, scopeLabel);
        const search = element(doc, 'input', { className: 'ip-flib-search', type: 'search',
            placeholder: 'Search finishes, scenes, signs', 'aria-label': 'Search the library' });
        const tree = element(doc, 'div', { className: 'ip-flib-tree', role: 'tree', 'aria-label': 'Library folders' });
        const gridHead = element(doc, 'div', { className: 'ip-flib-grid-head' });
        const grid = element(doc, 'div', { className: 'ip-flib-grid', role: 'listbox', 'aria-label': 'Library items' });
        const hint = element(doc, 'div', { className: 'ip-flib-hint' });
        const faceBar = element(doc, 'div', { className: 'ip-flib-actions ip-flib-faces', 'aria-label': 'Faces' });
        const editor = element(doc, 'div', { className: 'ip-flib-editor', 'aria-label': 'Selected item' });
        const status = element(doc, 'div', { className: 'ip-flib-status', role: 'status', 'aria-live': 'polite' });
        const picker = element(doc, 'input', { type: 'file', accept: 'image/png,image/jpeg', hidden: true,
            'aria-hidden': 'true' });
        panel.append(head, search, tree, gridHead, grid, hint, faceBar, editor, status, picker);
        host.textContent = '';
        host.append(panel);
        if (words.length && typeof MutationObserver === 'function') {
            // Every text and label the pane shows reads in its own words, however it was drawn.
            reword(panel);
            new MutationObserver(function (records) {
                records.forEach(function (record) {
                    if (record.type === 'childList') record.addedNodes.forEach(reword);
                    else reword(record.target);
                });
            }).observe(panel, { subtree: true, childList: true, characterData: true, attributes: true,
                attributeFilter: WORDED_ATTRIBUTES });
        }

        function say(text) {
            return words.reduce(function (value, pair) { return value.split(pair[0]).join(pair[1]); }, String(text));
        }

        function reword(node) {
            if (node.nodeType === 3) {
                const next = say(node.nodeValue);
                if (next !== node.nodeValue) node.nodeValue = next;
                return;
            }
            if (node.nodeType !== 1) return;
            WORDED_ATTRIBUTES.forEach(function (name) {
                const value = node.getAttribute(name);
                const next = value ? say(value) : value;
                if (next !== value) node.setAttribute(name, next);
            });
            Array.from(node.childNodes).forEach(reword);
        }

        search.addEventListener('input', function () {
            state.query = search.value;
            renderGrid();
        });
        // Parts are ticked in the Parts list or the colour legend (a click in the 3D view orbits, it does not
        // select; "Pick on the machine" below is the click-to-place), so the selection can change while the panel
        // is open; it is read again on the way in.
        panel.addEventListener('pointerenter', function () { if (state.selected) renderEditor(); });
        picker.addEventListener('change', function () {
            const file = picker.files && picker.files[0];
            picker.value = '';
            if (file) importLogo(file);
        });

        // ---- Context ------------------------------------------------------------
        function number() { return String(viewer.assemblyNumber() || ''); }
        function lib() { return store.get(); }
        function selectedParts() { return (viewer.selectedParts() || []).map(String).filter(Boolean); }
        function selectedFaces() { return viewer.selectedFaces ? viewer.selectedFaces() || [] : []; }
        function faceName(ref) {
            return (ref.approximate ? 'Surface' : FACE_KINDS[ref.kind] || 'Face') + ' of ' + partName(ref.part);
        }
        function partName(part) {
            // A library machine's bodies have long ids; the end tells them apart.
            const name = String(viewer.partName ? viewer.partName(part) || part : part);
            return name.length > 32 ? '...' + name.slice(-22) : name;
        }
        function current() {
            return state.appearance && state.appearanceFor === number() ? state.appearance : null;
        }

        function setStatus(text, tone) {
            status.textContent = text || '';
            status.setAttribute('data-tone', tone || 'info');
        }

        function load() {
            const assembly = number();
            if (!assembly) {
                state.appearance = null;
                state.appearanceFor = '';
                render();
                return Promise.resolve(null);
            }
            const loading = Promise.resolve(viewer.load(assembly)).then(function (data) {
                if (destroyed || assembly !== number()) return null;
                state.appearance = data || null;
                state.appearanceFor = assembly;
                render();
                return data;
            }).catch(function () {
                if (!destroyed) setStatus('The machine\'s appearance could not be read.', 'error');
                return null;
            });
            state.loading = loading;
            return loading;
        }

        // One write at a time: the panel stays put while the server and the 3D view catch up.
        function write(label, action) {
            const assembly = number();
            if (!assembly) { setStatus('Load a machine in the Assembly tab first.', 'error'); return Promise.resolve(false); }
            if (state.busy) return Promise.resolve(false);
            state.busy = true;
            renderEditor();
            setStatus(label + '...');
            return Promise.resolve().then(function () { return action(assembly); }).then(function (data) {
                if (data) {
                    state.appearance = data;
                    state.appearanceFor = assembly;
                }
                return Promise.resolve(viewer.redraw && viewer.redraw()).then(function () {
                    state.busy = false;
                    setStatus(label + ' - done.');
                    render();
                    return true;
                });
            }).catch(function (error) {
                state.busy = false;
                setStatus(String(error && error.message || error || 'The change could not be saved.'), 'error');
                renderEditor();
                return false;
            });
        }

        // ---- Tree ---------------------------------------------------------------
        function machineRows() {
            const data = current();
            const library = lib();
            if (!data || !library) return [];
            const rows = [];
            const assigned = data.assigned || {};
            if (assigned.whole) {
                const item = libraryApi.findItem(library, 'appearance', assigned.whole.appearanceId, null);
                if (item) rows.push(Object.assign({}, item, { usageNote: 'Whole machine', usage: { whole: true } }));
            }
            Object.keys(assigned.parts || {}).forEach(function (part) {
                const item = libraryApi.findItem(library, 'appearance', assigned.parts[part].appearanceId, null);
                if (item) rows.push(Object.assign({}, item, { usageNote: 'On ' + partName(part), usage: { part: part } }));
            });
            const faceShown = data.faceStatus || {};
            (assigned.faces || []).forEach(function (row) {
                const item = libraryApi.findItem(library, 'appearance', row.finish && row.finish.appearanceId, null);
                const missing = faceShown[faceKey(row)] === 'face_missing' ? ' - ' + STATUS_NOTES.face_missing : '';
                if (item) {
                    rows.push(Object.assign({}, item, { usageNote: 'On a face of ' + partName(row.part) + missing,
                        usage: { face: faceKey(row), row: row } }));
                }
            });
            const sceneId = data.scene && data.scene.sceneId || 'classic';
            const scene = sections.has('scenes') ? libraryApi.findItem(library, 'scene', sceneId, null) : null;
            if (scene) rows.push(Object.assign({}, scene, { usageNote: 'Scene' }));
            const shown = data.signStatus || {};
            (sections.has('decals') || sections.has('logos') ? data.signs || [] : []).forEach(function (row) {
                rows.push({ kind: 'placed-sign', id: row.signId, label: row.label, url: row.url, aspect: row.aspect,
                    row: row, usageNote: 'On ' + partName(row.part) + (row.face ? ', on a picked face' : ', ' + row.side)
                        + (STATUS_NOTES[shown[row.signId]] ? ' - ' + STATUS_NOTES[shown[row.signId]] : '') });
            });
            return rows;
        }

        function logos() {
            const data = current();
            return (data && data.images || []).map(function (image) {
                return { kind: 'logo', id: image.imageId, label: image.label || 'Logo', url: image.url,
                    aspect: image.aspect || 1, widthMeters: 0.3 };
            });
        }

        function treeNodes() {
            const library = lib();
            const data = current();
            const signed = sections.has('decals') || sections.has('logos');
            const nodes = [{ kind: 'machine', id: 'machine', label: 'On this machine', depth: 0,
                count: data ? (signed ? (data.signs || []).length : 0)
                    + Object.keys(data.assigned && data.assigned.parts || {}).length
                    + (data.assigned && data.assigned.faces || []).length
                    + (data.assigned && data.assigned.whole ? 1 : 0) : 0 }];
            nodes.push({ kind: 'root', id: 'appearances', label: 'Appearances', depth: 0, parent: true });
            if (library && state.expanded.has('appearances')) {
                library.categories.forEach(function (category) {
                    nodes.push({ kind: 'category', id: category.categoryId, label: category.label, depth: 1 });
                });
            }
            if (sections.has('scenes')) nodes.push({ kind: 'root', id: 'scenes', label: 'Scenes', depth: 0, parent: true });
            if (library && sections.has('scenes') && state.expanded.has('scenes')) {
                library.sceneGroups.forEach(function (group) {
                    nodes.push({ kind: 'scene-group', id: group.groupId, label: group.label, depth: 1 });
                });
            }
            if (sections.has('decals')) {
                nodes.push({ kind: 'root', id: 'decals', label: 'Safety signs', depth: 0, parent: true });
            }
            if (library && sections.has('decals') && state.expanded.has('decals')) {
                library.decalGroups.forEach(function (group) {
                    nodes.push({ kind: 'decal-group', id: group.groupId, label: group.label, depth: 1 });
                });
            }
            if (sections.has('logos')) nodes.push({ kind: 'logos', id: 'logos', label: 'Logos', depth: 0, count: logos().length });
            return nodes;
        }

        function sameNode(a, b) { return a && b && a.kind === b.kind && a.id === b.id; }

        function chooseNode(node) {
            state.node = { kind: node.kind, id: node.id };
            if (node.parent) {
                if (state.expanded.has(node.id)) state.expanded.delete(node.id);
                else { state.expanded.clear(); state.expanded.add(node.id); }
            }
            state.query = '';
            search.value = '';
            render();
        }

        function renderTree() {
            tree.textContent = '';
            treeNodes().forEach(function (node) {
                const chosen = sameNode(node, state.node);
                const row = element(doc, 'div', {
                    className: 'ip-flib-node', role: 'treeitem', tabindex: chosen ? '0' : '-1',
                    'aria-level': String(node.depth + 1), 'aria-selected': chosen ? 'true' : 'false',
                    'aria-expanded': node.parent ? String(state.expanded.has(node.id)) : null,
                    'data-node-kind': node.kind, 'data-node-id': node.id,
                });
                row.style.setProperty('--ip-flib-depth', String(node.depth));
                row.append(element(doc, 'span', { className: 'ip-flib-twisty', 'aria-hidden': 'true' },
                    node.parent ? (state.expanded.has(node.id) ? 'v' : '>') : ''),
                element(doc, 'span', { className: 'ip-flib-node-label' }, node.label));
                if (node.count) row.append(element(doc, 'span', { className: 'ip-flib-count' }, String(node.count)));
                row.addEventListener('click', function () { chooseNode(node); });
                row.addEventListener('keydown', function (event) {
                    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseNode(node); }
                });
                tree.append(row);
            });
        }

        // ---- Grid ---------------------------------------------------------------
        function itemsForNode() {
            const library = lib();
            if (!library) return [];
            if (state.query.trim()) {
                return ['appearance', 'scene', 'decal'].filter(function (kind) {
                    return sections.has(kind === 'appearance' ? 'appearances' : kind + 's');
                }).reduce(function (rows, kind) {
                    return rows.concat(libraryApi.search(library, { kind: kind, query: state.query, layout: null }));
                }, []);
            }
            const node = state.node;
            if (node.kind === 'machine') return machineRows();
            if (node.kind === 'logos') return logos();
            if (node.kind === 'root' && node.id === 'appearances') return libraryApi.search(library, { kind: 'appearance', layout: null });
            if (node.kind === 'category') return libraryApi.search(library, { kind: 'appearance', category: node.id, layout: null });
            if (node.kind === 'root' && node.id === 'scenes') return libraryApi.search(library, { kind: 'scene' });
            if (node.kind === 'scene-group') return libraryApi.search(library, { kind: 'scene', group: node.id });
            if (node.kind === 'root' && node.id === 'decals') return libraryApi.search(library, { kind: 'decal' });
            if (node.kind === 'decal-group') return libraryApi.search(library, { kind: 'decal', group: node.id });
            return [];
        }

        function itemKey(item) {
            const usage = item.usage || {};
            return item.kind + ':' + item.id + (usage.part ? ':' + usage.part : '') + (usage.face ? ':' + usage.face : '');
        }

        function swatch(item) {
            const box = element(doc, 'span', { className: 'ip-flib-thumb', 'aria-hidden': 'true',
                'data-kind': item.kind === 'logo' || item.kind === 'placed-sign' ? 'decal' : item.kind });
            if (item.kind === 'decal' || item.kind === 'logo' || item.kind === 'placed-sign') {
                if (item.url) box.append(element(doc, 'img', { src: item.url, alt: '', draggable: 'false' }));
                return box;
            }
            if (item.thumbnailUrl) {
                box.append(element(doc, 'img', { src: item.thumbnailUrl, alt: '', draggable: 'false' }));
            } else {
                box.classList.add('ip-flib-thumb-drawn');
                box.style.setProperty('--ip-flib-color', item.color || '#9aa2a9');
            }
            return box;
        }

        function renderGrid() {
            grid.textContent = '';
            const node = treeNodes().find(function (item) { return sameNode(item, state.node); });
            gridHead.textContent = state.query.trim() ? 'Results for "' + state.query.trim() + '"' : node ? node.label : '';
            if (state.node.kind === 'logos' && !state.query.trim()) {
                const add = element(doc, 'button', { type: 'button', className: 'ip-flib-item',
                    title: 'Import a PNG or JPEG logo for this machine' }, 'Import logo...');
                add.addEventListener('click', function () {
                    if (!number()) setStatus('Load a machine in the Assembly tab first.', 'error');
                    else picker.click();
                });
                grid.append(add);
            }
            if (!lib()) {
                grid.append(element(doc, 'div', { className: 'ip-flib-empty' },
                    store.error() ? 'The library could not be loaded.' : 'Loading the library...'));
                return;
            }
            const items = itemsForNode();
            if (!items.length) {
                grid.append(element(doc, 'div', { className: 'ip-flib-empty' }, !number()
                    ? 'Load a machine in the Assembly tab to give it finishes, a scene and signs.'
                    : state.node.kind === 'machine' ? 'This machine has no library finishes or signs yet.'
                    : state.node.kind === 'logos' ? 'Imported logos appear here.' : 'Nothing matches.'));
                return;
            }
            items.forEach(function (item) {
                const selected = state.selected && itemKey(state.selected) === itemKey(item);
                const tile = element(doc, 'div', {
                    className: 'ip-flib-item', role: 'option', tabindex: '0',
                    draggable: item.kind === 'placed-sign' ? null : 'true',
                    'aria-selected': selected ? 'true' : 'false',
                    title: item.label + (item.usageNote ? ' - ' + item.usageNote : ''),
                    'data-kind': item.kind, 'data-id': item.id,
                });
                tile.append(swatch(item), element(doc, 'span', { className: 'ip-flib-name' }, item.label));
                if (item.usageNote) tile.append(element(doc, 'span', { className: 'ip-flib-note-line' }, item.usageNote));
                tile.addEventListener('click', function () { selectItem(item); });
                tile.addEventListener('keydown', function (event) {
                    if (event.key === 'Enter') { event.preventDefault(); selectItem(item); }
                });
                tile.addEventListener('dragstart', function (event) {
                    if (!event.dataTransfer) return;
                    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ kind: item.kind, id: item.id }));
                    event.dataTransfer.effectAllowed = 'copy';
                });
                grid.append(tile);
            });
        }

        // ---- Editor -------------------------------------------------------------
        function selectItem(item) {
            stopPick();
            state.selected = item;
            state.color = item.kind === 'appearance' ? (item.color || null) : null;
            state.width = item.kind === 'decal' || item.kind === 'logo' ? Number(item.widthMeters) || 0.3 : null;
            state.rotation = '0';
            const parts = selectedParts();
            state.target = selectedFaces().length ? 'faces' : parts.length ? 'parts' : 'whole';
            if (parts.length && parts.indexOf(state.part) < 0) state.part = parts[0];
            renderGrid();
            renderEditor();
        }

        function field(labelText, control, note) {
            const row = element(doc, 'label', { className: 'ip-flib-field' });
            row.append(element(doc, 'span', { className: 'ip-flib-field-label' }, labelText), control);
            if (note) row.append(element(doc, 'span', { className: 'ip-flib-field-note' }, note));
            return row;
        }

        function select(options, value, onChange, labelText) {
            const control = element(doc, 'select', { 'aria-label': labelText });
            options.forEach(function (pair) {
                control.append(element(doc, 'option', { value: pair[0], selected: pair[0] === value }, pair[1]));
            });
            control.value = value;
            control.addEventListener('change', function () { onChange(control.value); });
            return control;
        }

        function button(text, onClick, extra) {
            const control = element(doc, 'button', Object.assign({ type: 'button', disabled: state.busy }, extra || {}),
                text);
            control.addEventListener('click', onClick);
            return control;
        }

        function editorHead(item, subtitle) {
            const headRow = element(doc, 'div', { className: 'ip-flib-editor-head' });
            const names = element(doc, 'div', { className: 'ip-flib-editor-names' });
            names.append(element(doc, 'strong', null, item.label), element(doc, 'small', null, subtitle));
            headRow.append(swatch(item), names);
            return headRow;
        }

        function renderEditor() {
            editor.textContent = '';
            const item = state.selected;
            const assembly = number();
            scopeLabel.textContent = assembly ? String(viewer.assemblyName && viewer.assemblyName() || assembly)
                : 'No machine loaded';
            const parts = selectedParts();
            hint.textContent = !assembly ? 'Load a machine in the Assembly tab.'
                : parts.length ? parts.length + ' part' + (parts.length === 1 ? '' : 's') + ' selected.'
                : 'Pick a spot on the machine, or drag an item onto it.';
            renderFaceBar(assembly);
            if (!item) return;
            if (item.kind === 'appearance') renderFinishEditor(item, parts);
            else if (item.kind === 'scene') renderSceneEditor(item);
            else if (item.kind === 'decal' || item.kind === 'logo') renderSignEditor(item, parts);
            else if (item.kind === 'placed-sign') renderPlacedSignEditor(item);
        }

        function renderFaceBar(assembly) {
            // The faces selected in the 3D view (a click selects one, Ctrl- or Shift-click adds or removes one); a
            // finish or sign can then go on them.
            faceBar.textContent = '';
            if (!assembly || !viewer.faceAt) return;
            const faces = selectedFaces();
            if (!faces.length) {
                faceBar.append(element(doc, 'span', { className: 'ip-flib-field-note' },
                    'Click a face on the machine to select it; Ctrl-click adds one.'));
                return;
            }
            faceBar.append(element(doc, 'span', { className: 'ip-flib-field-note', title: faces.map(faceName).join('\n') },
                faces.length === 1 ? faceName(faces[0]) + ' selected.' : faces.length + ' faces selected.'),
            button('Clear faces', function () { setFaces([]); }));
        }

        function renderFinishEditor(item, parts) {
            editor.append(editorHead(item, item.description || 'Finish'));
            const faces = selectedFaces();
            if (state.target === 'faces' && !faces.length) state.target = parts.length ? 'parts' : 'whole';
            const segment = element(doc, 'div', { className: 'ip-flib-segment', role: 'radiogroup',
                'aria-label': 'Apply to' });
            [['whole', 'Whole machine'], ['parts', parts.length ? 'Selected parts (' + parts.length + ')' : 'Selected parts'],
                ['faces', faces.length ? 'Selected faces (' + faces.length + ')' : 'Selected faces']]
                .forEach(function (pair) {
                    const option = element(doc, 'button', { type: 'button', role: 'radio',
                        'aria-checked': state.target === pair[0] ? 'true' : 'false',
                        disabled: (pair[0] === 'parts' && !parts.length) || (pair[0] === 'faces' && !faces.length) },
                    pair[1]);
                    option.addEventListener('click', function () { state.target = pair[0]; renderEditor(); });
                    segment.append(option);
                });
            editor.append(segment);
            const color = element(doc, 'input', { type: 'color', value: state.color || item.color || '#9aa2a9',
                'aria-label': 'Colour' });
            color.addEventListener('input', function () { state.color = color.value; });
            const fields = element(doc, 'div', { className: 'ip-flib-fields' });
            fields.append(field('Colour', color, item.color ? 'The library colour unless you change it.' : null));
            editor.append(fields);
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            const onFaces = state.target === 'faces';
            actions.append(button('Apply', function () {
                if (onFaces) applyFaceFinish(item, faces);
                else applyFinish(item, state.target === 'parts' ? parts : null);
            }, { className: 'ip-flib-primary' }),
            button(onFaces ? 'Remove from selected faces' : state.target === 'parts' ? 'Remove from selected parts'
                : 'Remove whole-machine finish', function () {
                if (onFaces) removeFaceFinish(faces);
                else removeFinish(state.target === 'parts' ? parts : null);
            }), pickButton(item, false));
            if (item.usage && item.usage.row) {
                actions.append(button('Remove from this face', function () { removeFaceFinish([item.usage.row]); }));
            }
            editor.append(actions);
        }

        function renderSceneEditor(item) {
            editor.append(editorHead(item, item.description || 'Scene'));
            editor.append(element(doc, 'p', { className: 'ip-flib-note' },
                'Lights the Assembly view and the Specification Sheet\'s picture (on its white page). Line drawings stay '
                + 'black and white.'));
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            actions.append(button('Use this scene', function () { applyScene(item.id); }, { className: 'ip-flib-primary' }));
            if (item.id !== 'classic') actions.append(button('Back to Classic', function () { applyScene('classic'); }));
            editor.append(actions);
        }

        function renderSignEditor(item, parts) {
            editor.append(editorHead(item, item.kind === 'logo' ? 'Imported logo' : (item.code || 'Sign')));
            const fields = element(doc, 'div', { className: 'ip-flib-fields' });
            if (parts.length) {
                if (parts.indexOf(state.part) < 0) state.part = parts[0];
                fields.append(field('Part', select(parts.map(function (part) { return [part, partName(part)]; }),
                    state.part, function (value) { state.part = value; }, 'Part')));
            } else {
                fields.append(element(doc, 'p', { className: 'ip-flib-note' },
                    'Pick the spot on the machine, or drag the sign onto it. Parts ticked in the Parts list '
                    + 'can be chosen here.'));
            }
            fields.append(field('Side', select(SIDES, state.side, function (value) { state.side = value; }, 'Side'),
                'As seen in the view\'s Front and Right buttons.'));
            const width = element(doc, 'input', { type: 'number', min: '0.02', max: '3', step: '0.01',
                value: String(state.width || 0.3), 'aria-label': 'Width in metres' });
            width.addEventListener('input', function () { state.width = clamp(width.value, 0.02, 3, 0.3); });
            fields.append(field('Width (m)', width),
                field('Turn', select(ROTATIONS, state.rotation, function (value) { state.rotation = value; }, 'Turn')));
            editor.append(fields);
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            actions.append(pickButton(item, true), button('Place on part', function () {
                if (!parts.length) { setStatus('Tick a part first, or pick the spot on the machine.', 'error'); return; }
                placeSign(item, { part: state.part, side: state.side });
            }, { disabled: state.busy || !parts.length }));
            const faces = selectedFaces();
            if (faces.length) {
                // One sign on each selected face, kept inside it.
                actions.append(button(faces.length === 1 ? 'Place on selected face' : 'Place on selected faces ('
                    + faces.length + ')', function () { placeSignsOnFaces(item, faces); }));
            }
            editor.append(actions);
            if (item.kind === 'decal') {
                editor.append(element(doc, 'p', { className: 'ip-flib-source' },
                    'ISO 7010 sign, public domain. Signs are visual aids: check the site\'s rules and the current '
                    + 'ISO 7010 edition before relying on them.'));
            }
        }

        function renderPlacedSignEditor(item) {
            const row = item.row;
            editor.append(editorHead(item, 'On ' + partName(row.part) + (row.face ? ', on a picked face'
                : ', ' + row.side + ' side')));
            editor.append(element(doc, 'p', { className: 'ip-flib-note' }, (row.widthMeters || 0.3) + ' m wide'
                + (row.anchor ? ', placed where it was dropped.' : '.')));
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            actions.append(button('Remove sign', function () { removeSign(row.signId); }, { className: 'ip-flib-danger' }));
            editor.append(actions);
        }

        // ---- Writes -------------------------------------------------------------
        function finishFor(item) {
            const value = { appearanceId: item.id };
            const color = state.color && item.kind === 'appearance' ? String(state.color).toLowerCase() : null;
            if (color && color !== String(item.color || '').toLowerCase()) value.color = color;
            return value;
        }

        function applyFinish(item, parts) {
            return write(parts ? 'Applying ' + item.label + ' to ' + parts.length + ' part' + (parts.length === 1 ? '' : 's')
                : 'Applying ' + item.label + ' to the machine', function (assembly) {
                const assigned = (current() || {}).assigned || {};
                const next = { whole: assigned.whole || null, parts: Object.assign({}, assigned.parts || {}) };
                if (parts) parts.forEach(function (part) { next.parts[part] = finishFor(item); });
                else next.whole = finishFor(item);
                return viewer.saveFinishes(assembly, next);
            });
        }

        function removeFinish(parts) {
            return write(parts ? 'Removing finishes from the selected parts' : 'Removing the whole-machine finish',
                function (assembly) {
                    const assigned = (current() || {}).assigned || {};
                    const next = { whole: parts ? assigned.whole || null : null, parts: Object.assign({}, assigned.parts || {}) };
                    (parts || []).forEach(function (part) { delete next.parts[part]; });
                    return viewer.saveFinishes(assembly, next);
                });
        }

        // A face's finish wins over its part's and the machine's; it goes on every copy of the part.
        function saveFaces(assembly, rows) {
            const assigned = (current() || {}).assigned || {};
            return viewer.saveFinishes(assembly, { whole: assigned.whole || null, parts: assigned.parts || {},
                faces: rows });
        }

        function applyFaceFinish(item, faces) {
            return write('Applying ' + item.label + ' to ' + (faces.length === 1 ? faceName(faces[0])
                : faces.length + ' faces'), function (assembly) {
                const keys = new Set(faces.map(faceKey));
                const rows = (((current() || {}).assigned || {}).faces || [])
                    .filter(function (row) { return !keys.has(faceKey(row)); }).map(storedFace);
                faces.forEach(function (face) {
                    rows.push(storedFace(Object.assign({}, face, { finish: finishFor(item) })));
                });
                return saveFaces(assembly, rows);
            });
        }

        function removeFaceFinish(faces) {
            return write('Removing the finish from ' + (faces.length === 1 ? 'the face' : faces.length + ' faces'),
                function (assembly) {
                    const keys = new Set(faces.map(faceKey));
                    return saveFaces(assembly, (((current() || {}).assigned || {}).faces || [])
                        .filter(function (row) { return !keys.has(faceKey(row)); }).map(storedFace));
                });
        }

        function setFaces(list) {
            if (viewer.setSelectedFaces) viewer.setSelectedFaces(list);
            renderEditor();
        }

        function applyScene(sceneId) {
            const library = lib();
            const scene = library && library.scenes.get(sceneId);
            return write('Lighting the machine with ' + (scene ? scene.label : sceneId), function (assembly) {
                return viewer.saveScene(assembly, sceneId === 'classic' ? null : sceneId);
            });
        }

        function signRow(item, where) {
            const row = { label: item.label, part: where.part, side: where.side || 'front',
                widthMeters: clamp(state.width || item.widthMeters, 0.02, 3, 0.3),
                rotationDegrees: Number(state.rotation) || 0 };
            if (item.kind === 'logo') row.imageId = item.id;
            else row.decalId = item.id;
            if (where.anchor) row.anchor = where.anchor;
            if (where.face) row.face = faceRef(where.face);
            return row;
        }

        function placeSign(item, where) {
            return write('Placing ' + item.label + ' on ' + partName(where.part), function (assembly) {
                const rows = ((current() || {}).signs || []).map(storedSign);
                rows.push(signRow(item, where));
                return viewer.saveSigns(assembly, rows);
            });
        }

        function placeSignsOnFaces(item, faces) {
            return write('Placing ' + item.label + ' on ' + (faces.length === 1 ? faceName(faces[0])
                : faces.length + ' faces'), function (assembly) {
                const rows = ((current() || {}).signs || []).map(storedSign);
                faces.slice(0, 12).forEach(function (face) {
                    rows.push(signRow(item, { part: face.part, side: face.side, face: face }));
                });
                return viewer.saveSigns(assembly, rows);
            });
        }

        function removeSign(signId) {
            state.selected = null;
            return write('Removing the sign', function (assembly) {
                const rows = ((current() || {}).signs || []).filter(function (row) { return row.signId !== signId; })
                    .map(storedSign);
                return viewer.saveSigns(assembly, rows);
            });
        }

        function importLogo(file) {
            return write('Importing ' + (file.name || 'the logo'), function (assembly) {
                return Promise.resolve(viewer.importImage(assembly, file)).then(function () {
                    state.node = { kind: 'logos', id: 'logos' };
                    return viewer.load(assembly);
                });
            });
        }

        // ---- Picking a spot on the 3D view ---------------------------------------
        // One click on the machine (a press and release without dragging, so orbiting still works) puts the
        // chosen sign or finish on the part under the pointer, as a drop does. Esc cancels.
        let picking = null;
        function pickButton(item, primary) {
            const active = Boolean(picking && picking.item === item);
            return button(active ? 'Cancel pick' : 'Pick on the machine', function () {
                if (active) { stopPick(); setStatus('Pick cancelled.'); } else startPick(item);
            }, { className: primary && !active ? 'ip-flib-primary' : '', disabled: state.busy && !active });
        }

        function startPick(item) {
            stopPick();
            if (viewer.stopTools) viewer.stopTools();
            const target = viewer.dropTarget && viewer.dropTarget();
            if (!target || !number()) { setStatus('Load a machine in the Assembly tab.', 'error'); return; }
            let down = null;
            const onDown = function (event) { down = event.button === 0 ? [event.clientX, event.clientY] : null; };
            const onUp = function (event) {
                const start = down;
                down = null;
                if (!start || event.button !== 0) return;
                if (Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 4) return;
                const hit = viewer.pickSurfaceAt(event.clientX, event.clientY);
                if (!hit) { setStatus('Click a part of the machine.', 'error'); return; }
                stopPick();
                if (item.kind === 'appearance') applyFinish(item, [hit.part]);
                else placeSign(item, hit);
            };
            const onKey = function (event) {
                if (event.key === 'Escape') { stopPick(); setStatus('Pick cancelled.'); }
            };
            target.addEventListener('pointerdown', onDown, true);
            target.addEventListener('pointerup', onUp, true);
            doc.addEventListener('keydown', onKey);
            target.classList.add('ip-flib-drop-active');
            picking = {
                item: item,
                stop: function () {
                    target.removeEventListener('pointerdown', onDown, true);
                    target.removeEventListener('pointerup', onUp, true);
                    doc.removeEventListener('keydown', onKey);
                    target.classList.remove('ip-flib-drop-active');
                },
            };
            setStatus('Click the machine where ' + item.label + ' should go. Esc cancels.');
            renderEditor();
        }

        function stopPick() {
            if (!picking) return;
            const was = picking;
            picking = null;
            was.stop();
            if (state.selected === was.item) renderEditor();
        }

        // ---- Dropping onto the 3D view ------------------------------------------
        function findDropped(payload) {
            const library = lib();
            if (!payload || !library) return null;
            if (payload.kind === 'logo') return logos().find(function (item) { return item.id === payload.id; }) || null;
            return libraryApi.findItem(library, payload.kind, payload.id, null);
        }

        function droppedPayload(event) {
            const transfer = event.dataTransfer;
            if (!transfer) return null;
            const types = Array.from(transfer.types || []);
            if (types.indexOf(DRAG_TYPE) < 0) return null;
            try { return JSON.parse(transfer.getData(DRAG_TYPE) || 'null'); } catch (_) { return null; }
        }

        function overViewer(event) {
            const target = viewer.dropTarget && viewer.dropTarget();
            return Boolean(target && event.target && typeof target.contains === 'function' && target.contains(event.target));
        }

        let dropTarget = null;
        function onDragOver(event) {
            const transfer = event.dataTransfer;
            const types = transfer ? Array.from(transfer.types || []) : [];
            if (types.indexOf(DRAG_TYPE) < 0 || !overViewer(event)) {
                if (dropTarget) { dropTarget.classList.remove('ip-flib-drop-active'); dropTarget = null; }
                return;
            }
            event.preventDefault();
            transfer.dropEffect = 'copy';
            dropTarget = viewer.dropTarget();
            dropTarget.classList.add('ip-flib-drop-active');
        }
        function onDrop(event) {
            if (dropTarget) { dropTarget.classList.remove('ip-flib-drop-active'); dropTarget = null; }
            const payload = droppedPayload(event);
            if (!payload || !overViewer(event)) return;
            event.preventDefault();
            const item = findDropped(payload);
            if (!item) return;
            if (item.kind === 'scene') { applyScene(item.id); return; }
            const face = viewer.faceAt ? viewer.faceAt(event.clientX, event.clientY) : null;
            const chosen = selectedFaces();
            if (face && chosen.some(function (ref) { return faceKey(ref) === faceKey(face); })) {
                // Dropped on a selected face: a finish goes on every selected face, a sign on that face.
                selectItem(item);
                if (item.kind === 'appearance') applyFaceFinish(item, chosen);
                else placeSign(item, { part: face.part, side: face.side, face: face });
                return;
            }
            const hit = viewer.pickSurfaceAt(event.clientX, event.clientY);
            if (!hit) { setStatus('Drop it on a part of the machine.', 'error'); return; }
            selectItem(item);
            if (item.kind === 'appearance') applyFinish(item, [hit.part]);
            else placeSign(item, hit);
        }
        doc.addEventListener('dragover', onDragOver);
        doc.addEventListener('drop', onDrop);

        // ---- Render -------------------------------------------------------------
        function render() {
            if (destroyed) return;
            renderTree();
            renderGrid();
            if (state.selected && state.selected.kind === 'placed-sign'
                && !((current() || {}).signs || []).some(function (row) { return row.signId === state.selected.id; })) {
                state.selected = null;
            }
            renderEditor();
        }

        if (typeof store.subscribe === 'function') store.subscribe(function () { render(); });
        if (typeof store.load === 'function') {
            store.load().then(render).catch(function () { render(); });
        }
        render();
        load();

        return {
            element: panel,
            // The machine or its appearance changed (a model loaded, Sage wrote): read it again.
            refresh: function () { return load(); },
            open: function (request) {
                const ask = request || {};
                if (ask.kind === 'scene') state.node = { kind: 'root', id: 'scenes' };
                else if (ask.kind === 'decal') state.node = { kind: 'root', id: 'decals' };
                else if (ask.kind === 'appearance') state.node = { kind: 'root', id: 'appearances' };
                return load();
            },
            bind: function () { return load(); },
            // The view's Smart Dimension takes the pointer: picking here stops.
            stopPicking: function () { stopPick(); },
            // While "Pick on the machine" waits for a click, the view does not select.
            isPicking: function () { return Boolean(picking); },
            // The view's selected faces changed: a finish now goes on them by default.
            selectionChanged: function () {
                if (selectedFaces().length) state.target = 'faces';
                renderEditor();
            },
            destroy: function () {
                destroyed = true;
                stopPick();
                doc.removeEventListener('dragover', onDragOver);
                doc.removeEventListener('drop', onDrop);
                host.textContent = '';
            },
        };
    }

    return { createAssemblyLibraryPanel: createAssemblyLibraryPanel, DRAG_TYPE: DRAG_TYPE, storedSign: storedSign,
        storedFace: storedFace };
}));
