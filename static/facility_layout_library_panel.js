/**
 * Appearances, Scenes and Decals panel for Facility layouts.
 *
 * One pane in the left slot, arranged like a CAD task pane: a library tree on
 * top (Favorites, Recent, In this layout, Appearances, Scenes, Decals), the
 * matching thumbnails below, and an editor for the chosen item. Items can be
 * applied from the editor or dragged onto the 3D view.
 *
 * The panel owns no layout data. Every change goes through the workspace's
 * session (so undo, redo and saving work as for any edit), and every preview
 * goes through the 3D adapter and is discarded on Cancel. Favorites and recents
 * are per-viewer conveniences kept in local storage.
 */
(function (root, factory) {
    'use strict';
    const library = root.InspectorProFacilityLibrary
        || (typeof require === 'function' ? require('./facility_layout_library.js') : null);
    const api = factory(library);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityLibraryPanel = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (libraryApi) {
    'use strict';

    const DRAG_TYPE = 'application/x-inspectorpro-library';
    const PREVIEW_DELAY_MS = 90;
    const SCENE_ADJUSTMENTS = ['exposure', 'environmentIntensity', 'ambient', 'directional', 'background', 'shadows',
        'environmentRotationDegrees', 'lights', 'lightAreas', 'glowHalo'];
    const LIGHT_AREA_MODES = ['only', 'except'];
    const MAX_LIGHT_AREAS = 64;
    const GRAINS = [['part', 'Along each part'], ['length', 'Along object length'], ['width', 'Along object width'],
        ['height', 'Vertical']];
    const MAPPINGS = [['box', 'Box (flat faces)'], ['cylindrical', 'Cylindrical (round parts)'], ['uv', 'Model UVs if present']];

    function element(doc, tag, attributes, text) {
        const node = doc.createElement(tag);
        Object.keys(attributes || {}).forEach(function (key) {
            const value = attributes[key];
            if (value === null || value === undefined || value === false) return;
            if (key === 'className') node.className = value;
            else if (key === 'text') node.textContent = value;
            else if (value === true) node.setAttribute(key, '');
            else node.setAttribute(key, String(value));
        });
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function clamp(value, low, high) {
        const number = Number(value);
        if (!Number.isFinite(number)) return low;
        return Math.min(high, Math.max(low, number));
    }

    function round(value, places) {
        const factor = Math.pow(10, places);
        return Math.round(Number(value) * factor) / factor;
    }

    function randomId(doc) {
        const crypto = doc && doc.defaultView && doc.defaultView.crypto;
        if (crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID().slice(0, 13).toLowerCase();
        return Math.random().toString(36).slice(2, 14);
    }

    function slug(text) {
        return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30) || 'finish';
    }

    // Draw a library sign into a PNG the existing decal import accepts. Saved
    // layouts then keep their own copy and never depend on the library file.
    function rasterizeDecal(doc, item, pixels) {
        return new Promise(function (resolve, reject) {
            const view = doc.defaultView;
            const image = new view.Image();
            image.onload = function () {
                const width = Math.max(64, Math.round(pixels || 1024));
                const aspect = item.aspect > 0 ? item.aspect : 1;
                const canvas = doc.createElement('canvas');
                canvas.width = width;
                canvas.height = Math.max(64, Math.round(width / aspect));
                canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
                canvas.toBlob(function (blob) {
                    if (blob) resolve(blob);
                    else reject(new Error('The sign image could not be prepared.'));
                }, 'image/png');
            };
            image.onerror = function () { reject(new Error('The sign image could not be loaded.')); };
            image.src = item.url;
        });
    }

    function createLibraryPanel(options) {
        const settings = options || {};
        const doc = settings.document;
        const host = settings.host;
        const store = settings.store;
        const preferences = settings.preferences || libraryApi.createPreferences(null);
        if (!doc || !host || !store) throw new Error('The library panel needs a document, host and library store.');

        let workspace = null;
        let unsubscribers = [];
        let previewTimer = null;
        let destroyed = false;
        let dropTarget = null;
        let dropHandlers = null;
        const failedThumbnails = new Set();
        const state = {
            node: { kind: 'category', id: 'metals' },
            expanded: new Set(['appearances']),
            query: '',
            selected: null,
            draft: {},
            scope: 'object',
            partKey: null,
            parts: null,
            partsFor: null,
            partsRepresentation: null,
            partsError: '',
            status: '',
            statusTone: 'info',
            busy: false,
            placing: null,
            saving: false,
            editorKey: null,
            coverageArea: '',
            coverageBusy: false,
            coverageError: '',
        };

        // The Scenes pane's lighting coverage block while it is on show (CC3).
        let coverageBox = null;

        // ---- DOM skeleton -------------------------------------------------------
        const panel = element(doc, 'section', { className: 'ip-flib', 'aria-label': 'Appearances, scenes and decals' });
        const head = element(doc, 'div', { className: 'ip-flib-head' });
        const title = element(doc, 'span', { className: 'ip-flib-title' }, 'Appearances, Scenes & Decals');
        const scopeLabel = element(doc, 'span', { className: 'ip-flib-scope-label' });
        head.append(title, scopeLabel);
        const search = element(doc, 'input', { className: 'ip-flib-search', type: 'search',
            placeholder: 'Search finishes, scenes, signs', 'aria-label': 'Search the library' });
        const tree = element(doc, 'div', { className: 'ip-flib-tree', role: 'tree', 'aria-label': 'Library folders' });
        const gridHead = element(doc, 'div', { className: 'ip-flib-grid-head' });
        const grid = element(doc, 'div', { className: 'ip-flib-grid', role: 'listbox', 'aria-label': 'Library items' });
        const hint = element(doc, 'div', { className: 'ip-flib-hint' });
        const editor = element(doc, 'div', { className: 'ip-flib-editor', 'aria-label': 'Selected item' });
        const status = element(doc, 'div', { className: 'ip-flib-status', role: 'status', 'aria-live': 'polite' });
        panel.append(head, search, tree, gridHead, grid, hint, editor, status);
        host.textContent = '';
        host.append(panel);

        search.addEventListener('input', function () {
            state.query = search.value;
            renderGrid();
        });

        // ---- Context ------------------------------------------------------------
        function context() {
            return workspace && typeof workspace.appearanceLibraryContext === 'function'
                ? workspace.appearanceLibraryContext() : null;
        }
        function library() { return store.get(); }
        function layout() { const ctx = context(); return ctx && ctx.layout || null; }
        function adapter() { const ctx = context(); return ctx && ctx.threeAdapter || null; }

        function setStatus(text, tone) {
            state.status = text || '';
            state.statusTone = tone || 'info';
            status.textContent = state.status;
            status.setAttribute('data-tone', state.statusTone);
        }

        function selectedPlacementIds() {
            const ctx = context();
            if (!ctx || !ctx.layout) return [];
            const placements = new Set((ctx.layout.placements || []).map(function (row) { return row.placementId; }));
            return ctx.selection.filter(function (id) { return placements.has(id); });
        }

        function placementLabel(placementId) {
            const row = (layout() && layout().placements || []).find(function (item) { return item.placementId === placementId; });
            if (!row) return placementId;
            if (row.metadata && row.metadata.instanceLabel) return row.metadata.instanceLabel;
            const ctx = context();
            const entry = (ctx && Array.isArray(ctx.assetCatalog) ? ctx.assetCatalog : [])
                .find(function (item) { return item && item.assetId === row.assetId; });
            return entry && (entry.label || entry.displayName) || row.assetId || placementId;
        }

        // The part outline is the panel's own; it goes when part scope ends.
        function highlightPart(placementId, key) {
            const three = adapter();
            if (!three || typeof three.highlightComponent !== 'function') return;
            three.highlightComponent(placementId, key);
            state.highlighted = Boolean(key);
        }

        function clearPartHighlight() {
            if (!state.highlighted) return;
            const three = adapter();
            if (three && typeof three.highlightComponent === 'function') three.highlightComponent(null);
            state.highlighted = false;
        }

        // ---- Tree ---------------------------------------------------------------
        function treeNodes() {
            const lib = library();
            const nodes = [
                { kind: 'favorites', id: 'favorites', label: 'Favorites', depth: 0, count: preferences.favorites().length },
                { kind: 'recent', id: 'recent', label: 'Recent', depth: 0, count: preferences.recents().length },
                { kind: 'usage', id: 'usage', label: 'In this layout', depth: 0 },
                { kind: 'root', id: 'appearances', label: 'Appearances', depth: 0, parent: true },
            ];
            if (!lib) return nodes;
            if (state.expanded.has('appearances')) {
                lib.categories.forEach(function (category) {
                    nodes.push({ kind: 'category', id: category.categoryId, label: category.label, depth: 1 });
                });
                if (libraryApi.customAppearances(layout()).length) {
                    nodes.push({ kind: 'category', id: 'custom', label: 'Custom (this layout)', depth: 1 });
                }
            }
            nodes.push({ kind: 'root', id: 'scenes', label: 'Scenes', depth: 0, parent: true });
            if (state.expanded.has('scenes')) {
                lib.sceneGroups.forEach(function (group) {
                    nodes.push({ kind: 'scene-group', id: group.groupId, label: group.label, depth: 1 });
                });
            }
            nodes.push({ kind: 'root', id: 'decals', label: 'Decals', depth: 0, parent: true });
            if (state.expanded.has('decals')) {
                lib.decalGroups.forEach(function (group) {
                    nodes.push({ kind: 'decal-group', id: group.groupId, label: group.label, depth: 1 });
                });
            }
            return nodes;
        }

        function sameNode(a, b) { return a && b && a.kind === b.kind && a.id === b.id; }

        function chooseNode(node) {
            state.node = { kind: node.kind, id: node.id };
            if (node.parent) {
                // One library open at a time keeps all three folders in view.
                if (state.expanded.has(node.id)) state.expanded.delete(node.id);
                else { state.expanded.clear(); state.expanded.add(node.id); }
            }
            state.query = '';
            search.value = '';
            render();
        }

        function renderTree() {
            tree.textContent = '';
            const nodes = treeNodes();
            nodes.forEach(function (node, index) {
                const row = element(doc, 'div', {
                    className: 'ip-flib-node', role: 'treeitem', tabindex: sameNode(node, state.node) ? '0' : '-1',
                    'aria-level': String(node.depth + 1), 'aria-selected': sameNode(node, state.node) ? 'true' : 'false',
                    'aria-expanded': node.parent ? String(state.expanded.has(node.id)) : null,
                    'data-node-kind': node.kind, 'data-node-id': node.id,
                });
                row.style.setProperty('--ip-flib-depth', String(node.depth));
                const twisty = element(doc, 'span', { className: 'ip-flib-twisty', 'aria-hidden': 'true' },
                    node.parent ? (state.expanded.has(node.id) ? 'v' : '>') : '');
                const label = element(doc, 'span', { className: 'ip-flib-node-label' }, node.label);
                row.append(twisty, label);
                if (node.count) row.append(element(doc, 'span', { className: 'ip-flib-count' }, String(node.count)));
                row.addEventListener('click', function () { chooseNode(node); });
                row.addEventListener('keydown', function (event) {
                    const rows = Array.from(tree.querySelectorAll('.ip-flib-node'));
                    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                        event.preventDefault();
                        const next = rows[Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))];
                        if (next) next.focus();
                    } else if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        chooseNode(node);
                        focusNode(node);
                    } else if (event.key === 'ArrowRight' && node.parent && !state.expanded.has(node.id)) {
                        event.preventDefault();
                        state.expanded.add(node.id); renderTree(); focusNode(node);
                    } else if (event.key === 'ArrowLeft' && node.parent && state.expanded.has(node.id)) {
                        event.preventDefault();
                        state.expanded.delete(node.id); renderTree(); focusNode(node);
                    }
                });
                tree.append(row);
            });
            // Keep the chosen folder in view when the tree has to scroll.
            const chosen = tree.querySelector('.ip-flib-node[aria-selected="true"]');
            if (chosen && typeof chosen.scrollIntoView === 'function') chosen.scrollIntoView({ block: 'nearest' });
        }

        function focusNode(node) {
            const row = Array.from(tree.querySelectorAll('.ip-flib-node')).find(function (item) {
                return item.getAttribute('data-node-kind') === node.kind && item.getAttribute('data-node-id') === node.id;
            });
            if (row) row.focus();
        }

        // ---- Grid ---------------------------------------------------------------
        function itemsForNode() {
            const lib = library();
            if (!lib) return [];
            const currentLayout = layout();
            if (state.query.trim()) {
                return ['appearance', 'scene', 'decal'].reduce(function (rows, kind) {
                    return rows.concat(libraryApi.search(lib, { kind: kind, query: state.query, layout: currentLayout }));
                }, []);
            }
            const node = state.node;
            const resolve = function (ref) { return libraryApi.findItem(lib, ref.kind, ref.id, currentLayout); };
            if (node.kind === 'favorites') return preferences.favorites().map(resolve).filter(Boolean);
            if (node.kind === 'recent') return preferences.recents().map(resolve).filter(Boolean);
            if (node.kind === 'usage') {
                const usage = libraryApi.layoutUsage(lib, currentLayout);
                const rows = usage.appearances.map(function (row) {
                    const item = resolve({ kind: 'appearance', id: row.appearanceId });
                    return item ? Object.assign({}, item, { usageNote: row.placementIds.length + ' object'
                        + (row.placementIds.length === 1 ? '' : 's') + (row.partCount ? ', ' + row.partCount + ' part' + (row.partCount === 1 ? '' : 's') : '') }) : null;
                }).filter(Boolean);
                const sceneId = usage.scene ? usage.scene.sceneId : 'classic';
                const scene = resolve({ kind: 'scene', id: sceneId });
                if (scene) rows.push(Object.assign({}, scene, { usageNote: 'Saved scene' }));
                usage.equipmentDecals.forEach(function (row) {
                    const base = row.libraryDecalId ? resolve({ kind: 'decal', id: row.libraryDecalId }) : null;
                    rows.push({ kind: 'placed-decal', id: row.decalId, label: row.label, url: base ? base.url : null,
                        aspect: base ? base.aspect : row.widthMeters / row.heightMeters, row: row,
                        usageNote: 'On ' + placementLabel(row.placementId) });
                });
                return rows;
            }
            if (node.kind === 'root' && node.id === 'appearances') return libraryApi.search(lib, { kind: 'appearance', layout: currentLayout });
            if (node.kind === 'category') return libraryApi.search(lib, { kind: 'appearance', category: node.id, layout: currentLayout });
            if (node.kind === 'root' && node.id === 'scenes') return libraryApi.search(lib, { kind: 'scene' });
            if (node.kind === 'scene-group') return libraryApi.search(lib, { kind: 'scene', group: node.id });
            if (node.kind === 'root' && node.id === 'decals') return libraryApi.search(lib, { kind: 'decal' });
            if (node.kind === 'decal-group') return libraryApi.search(lib, { kind: 'decal', group: node.id });
            return [];
        }

        function nodeTitle() {
            if (state.query.trim()) return 'Results for "' + state.query.trim() + '"';
            const node = treeNodes().find(function (item) { return sameNode(item, state.node); });
            return node ? node.label : '';
        }

        function swatch(item, small) {
            const box = element(doc, 'span', { className: 'ip-flib-thumb' + (small ? ' ip-flib-thumb-small' : ''),
                'data-kind': item.kind, 'aria-hidden': 'true' });
            if (item.kind === 'decal' || item.kind === 'placed-decal') {
                if (item.url) box.append(element(doc, 'img', { src: item.url, alt: '', draggable: 'false' }));
                return box;
            }
            const fallback = function () {
                box.textContent = '';
                box.classList.add('ip-flib-thumb-drawn');
                if (item.kind === 'scene') {
                    box.style.setProperty('--ip-flib-scene', /^#/.test(item.background || '') ? item.background : 'var(--viewport-bg-secondary, #1b1f26)');
                    box.setAttribute('data-environment', item.environment ? (item.environment === 'room' ? 'room' : 'hdr') : 'none');
                    return;
                }
                box.style.setProperty('--ip-flib-color', item.emission && item.emission.color || item.color || '#9aa2a9');
                box.setAttribute('data-metal', item.metalness >= 0.5 ? 'true' : 'false');
                const maps = item.texture && item.texture.maps;
                const textureSet = !maps && item.texture && library() && library().textureSets.get(item.texture.textureSetId);
                const map = maps ? (maps.color || maps.detail) : textureSet ? (textureSet.maps.color || textureSet.maps.detail) : null;
                if (map) {
                    box.style.setProperty('--ip-flib-texture', 'url("' + map + '")');
                    box.setAttribute('data-tinted', maps ? String(!maps.color) : String(!textureSet.maps.color));
                }
                if (item.opacity < 1 || item.transmission) box.setAttribute('data-clear', 'true');
            };
            if (item.thumbnailUrl && !failedThumbnails.has(item.thumbnailUrl)) {
                const image = element(doc, 'img', { src: item.thumbnailUrl, alt: '', draggable: 'false' });
                image.addEventListener('error', function () { failedThumbnails.add(item.thumbnailUrl); fallback(); });
                box.append(image);
            } else {
                fallback();
            }
            return box;
        }

        function itemKey(item) { return item.kind + ':' + item.id; }

        function renderGrid() {
            grid.textContent = '';
            gridHead.textContent = nodeTitle();
            const lib = library();
            if (!lib) {
                grid.append(element(doc, 'div', { className: 'ip-flib-empty' },
                    store.error() ? 'The library could not be loaded.' : 'Loading the library...'));
                return;
            }
            const items = itemsForNode();
            if (!items.length) {
                const message = state.node.kind === 'favorites' ? 'Star an item to keep it here.'
                    : state.node.kind === 'recent' ? 'Items you apply appear here.'
                    : state.node.kind === 'usage' ? 'This layout uses no library finishes, scenes or equipment decals yet.'
                    : 'Nothing matches.';
                grid.append(element(doc, 'div', { className: 'ip-flib-empty' }, message));
                return;
            }
            items.forEach(function (item) {
                const selected = state.selected && itemKey(state.selected) === itemKey(item);
                const tile = element(doc, 'div', {
                    className: 'ip-flib-item', role: 'option', tabindex: '0', draggable: item.kind === 'placed-decal' ? null : 'true',
                    'aria-selected': selected ? 'true' : 'false', title: item.label + (item.usageNote ? ' - ' + item.usageNote : ''),
                    'data-kind': item.kind, 'data-id': item.id,
                });
                tile.append(swatch(item), element(doc, 'span', { className: 'ip-flib-name' }, item.label));
                if (item.usageNote) tile.append(element(doc, 'span', { className: 'ip-flib-note-line' }, item.usageNote));
                if (item.kind !== 'placed-decal') {
                    const favorite = preferences.isFavorite(item.kind, item.id);
                    const star = element(doc, 'button', { type: 'button', className: 'ip-flib-fav',
                        'aria-pressed': favorite ? 'true' : 'false',
                        'aria-label': (favorite ? 'Remove ' : 'Add ') + item.label + (favorite ? ' from' : ' to') + ' favorites',
                        title: favorite ? 'Remove from favorites' : 'Add to favorites' }, favorite ? '\u2605' : '\u2606');
                    star.addEventListener('click', function (event) {
                        event.stopPropagation();
                        preferences.toggleFavorite(item.kind, item.id);
                        renderTree(); renderGrid();
                        if (state.selected && itemKey(state.selected) === itemKey(item)) renderEditor(true);
                    });
                    tile.append(star);
                }
                tile.addEventListener('click', function () { selectItem(item); });
                tile.addEventListener('dblclick', function () { selectItem(item); applySelected(); });
                tile.addEventListener('keydown', function (event) {
                    if (event.key === 'Enter') { event.preventDefault(); selectItem(item); applySelected(); }
                    else if (event.key === ' ') { event.preventDefault(); selectItem(item); }
                });
                tile.addEventListener('dragstart', function (event) {
                    if (!event.dataTransfer) return;
                    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ kind: item.kind, id: item.id }));
                    event.dataTransfer.setData('text/plain', item.label);
                    event.dataTransfer.effectAllowed = 'copy';
                    selectItem(item);
                    hint.textContent = item.kind === 'appearance'
                        ? 'Drop on an object to finish it. Hold Shift to finish only the part under the cursor.'
                        : item.kind === 'scene' ? 'Drop anywhere in the 3D view to use this scene.'
                        : 'Drop on equipment to place the sign there, or on a wall to open wall decals.';
                });
                tile.addEventListener('dragend', function () { renderHint(); });
                grid.append(tile);
            });
        }

        // ---- Selection and drafts ----------------------------------------------------
        function selectedItem() {
            if (!state.selected) return null;
            if (state.selected.kind === 'placed-decal') {
                const rows = layout() && layout().extensions && layout().extensions.facilityEquipmentDecals;
                const row = rows && (rows.decals || []).find(function (item) { return item.decalId === state.selected.id; });
                if (!row) return null;
                const base = row.libraryDecalId ? libraryApi.findItem(library(), 'decal', row.libraryDecalId, layout()) : null;
                return { kind: 'placed-decal', id: row.decalId, label: row.label, url: base ? base.url : null,
                    aspect: row.widthMeters / row.heightMeters, row: row };
            }
            return libraryApi.findItem(library(), state.selected.kind, state.selected.id, layout());
        }

        function selectItem(item) {
            const changed = !state.selected || itemKey(state.selected) !== itemKey(item);
            if (!changed) return;
            cancelPreviews();
            state.selected = { kind: item.kind, id: item.id };
            state.draft = {};
            state.saving = false;
            if (item.kind === 'decal') state.draft = { widthMeters: item.widthMeters || 0.3, rotationDegrees: 0 };
            if (item.kind === 'placed-decal') state.draft = { widthMeters: item.row.widthMeters, rotationDegrees: item.row.anchor.rotationDegrees };
            if (item.kind === 'scene') state.draft = savedSceneDraft(item);
            setStatus('');
            renderGrid();
            renderEditor(true);
            schedulePreview();
        }

        // The draft holds only fields the user changed, so saved finishes stay
        // small and keep following future library tuning for everything else.
        function appearanceValue(item) {
            const value = { appearanceId: item.id };
            Object.keys(state.draft).forEach(function (key) {
                if (libraryApi.OVERRIDE_FIELDS.indexOf(key) >= 0 && state.draft[key] !== undefined) value[key] = state.draft[key];
            });
            return value;
        }

        // Re-editing the scene the layout already uses starts from its saved adjustments (the lights switch
        // included), so the editor shows them and Apply keeps them unless they are changed here.
        function savedSceneDraft(item) {
            const ctx = context();
            const saved = ctx ? libraryApi.layoutScene(ctx.layout) : null;
            return saved && saved.sceneId === item.id && saved.adjustments
                ? JSON.parse(JSON.stringify(saved.adjustments)) : {};
        }

        function sceneValue(item) {
            const value = { version: 1, sceneId: item.id };
            const adjustments = {};
            SCENE_ADJUSTMENTS.forEach(function (key) {
                if (state.draft[key] !== undefined) adjustments[key] = state.draft[key];
            });
            if (adjustments.lightAreas) adjustments.lightAreas = presentLightAreas(adjustments.lightAreas);
            if (Object.keys(adjustments).length) value.adjustments = adjustments;
            return value;
        }

        // A floor area removed from the layout since lights nothing; Apply drops it (L7).
        function presentLightAreas(value) {
            const known = new Set(floorAreas().map(function (floor) { return floor.surfaceId; }));
            return { mode: value.mode, areas: (value.areas || []).filter(function (area) {
                return !area.surfaceId || known.has(area.surfaceId);
            }).map(function (area) { return JSON.parse(JSON.stringify(area)); }) };
        }

        function cancelPreviews() {
            if (previewTimer) { clearTimeout(previewTimer); previewTimer = null; }
            const three = adapter();
            if (three && typeof three.clearFinishPreview === 'function') three.clearFinishPreview();
            if (three && typeof three.clearViewportScenePreview === 'function') three.clearViewportScenePreview();
            clearPartHighlight();
        }

        function schedulePreview() {
            if (previewTimer) clearTimeout(previewTimer);
            previewTimer = setTimeout(function () { previewTimer = null; preview(); }, PREVIEW_DELAY_MS);
        }

        function preview() {
            const item = selectedItem();
            const three = adapter();
            const ctx = context();
            if (!item || !three || !ctx || !ctx.canEdit) return;
            if (item.kind === 'scene') {
                if (typeof three.previewViewportScene === 'function') {
                    ctx.show3d();
                    three.previewViewportScene(sceneValue(item));
                }
                return;
            }
            if (item.kind !== 'appearance' || typeof three.previewFinish !== 'function') return;
            const ids = selectedPlacementIds();
            if (!ids.length) return;
            ctx.show3d();
            if (state.scope === 'part') {
                if (ids.length !== 1 || !state.partKey) return;
                three.previewFinish({ placementIds: ids, partKey: state.partKey, appearance: appearanceValue(item) });
            } else {
                three.previewFinish({ placementIds: ids, appearance: appearanceValue(item) });
            }
        }

        // ---- Parts --------------------------------------------------------------
        function ensureParts() {
            const ids = selectedPlacementIds();
            const three = adapter();
            if (ids.length !== 1 || !three || typeof three.getComponentMaterials !== 'function') {
                state.parts = null; state.partsFor = null;
                return;
            }
            if (state.partsFor === ids[0] && (state.parts || state.partsError)) return;
            state.partsFor = ids[0];
            state.parts = null;
            state.partsError = '';
            const ctx = context();
            if (ctx) ctx.show3d();
            Promise.resolve(three.getComponentMaterials(ids[0])).then(function (model) {
                if (destroyed || state.partsFor !== ids[0]) return;
                state.parts = (model.slots || []).map(function (slot) {
                    return { key: slot.key, legacyKey: slot.legacyKey, label: slot.label };
                });
                state.partsRepresentation = model.representation;
                if (!state.parts.length) state.partsError = 'This model has no separate parts.';
                if (!state.partKey || !state.parts.some(function (part) { return part.key === state.partKey; })) {
                    state.partKey = state.parts.length ? state.parts[0].key : null;
                }
                renderEditor(true);
                schedulePreview();
            }).catch(function (error) {
                if (destroyed || state.partsFor !== ids[0]) return;
                state.partsError = error && error.message ? error.message : 'Parts could not be loaded.';
                renderEditor(true);
            });
        }

        function partScopeReason() {
            const ids = selectedPlacementIds();
            if (ids.length !== 1) return 'Select exactly one object to finish one of its parts.';
            if (!adapter()) return 'Part finishes need the 3D view.';
            if (state.partsError) return state.partsError;
            return '';
        }

        // ---- Editor -------------------------------------------------------------
        function field(container, label, control, note) {
            const row = element(doc, 'label', { className: 'ip-flib-field' });
            row.append(element(doc, 'span', { className: 'ip-flib-field-label' }, label), control);
            if (note) row.append(element(doc, 'span', { className: 'ip-flib-field-note' }, note));
            container.append(row);
            return control;
        }

        function range(min, max, step, value, label) {
            return element(doc, 'input', { type: 'range', min: String(min), max: String(max), step: String(step),
                value: String(value), 'aria-label': label });
        }

        function select(choices, value, label) {
            const node = element(doc, 'select', { 'aria-label': label });
            choices.forEach(function (choice) {
                node.append(element(doc, 'option', { value: choice[0], selected: choice[0] === value ? true : null }, choice[1]));
            });
            return node;
        }

        function button(label, handler, extra) {
            const node = element(doc, 'button', Object.assign({ type: 'button' }, extra || {}), label);
            node.addEventListener('click', handler);
            return node;
        }

        function draftValue(item, key, fallback) {
            if (state.draft[key] !== undefined) return state.draft[key];
            if (item[key] !== undefined) return item[key];
            return fallback;
        }

        function textureValue(item, key, fallback) {
            if (state.draft[key] !== undefined) return state.draft[key];
            const texture = item.texture || {};
            const map = { textureStrength: 'strength', sizeMeters: 'sizeMeters', rotationDegrees: 'rotationDegrees',
                mapping: 'mapping', grain: 'grain' };
            return texture[map[key]] !== undefined ? texture[map[key]] : fallback;
        }

        function bindDraft(control, key, parse) {
            control.addEventListener('input', function () {
                state.draft[key] = parse(control);
                schedulePreview();
            });
            control.addEventListener('change', function () {
                state.draft[key] = parse(control);
                schedulePreview();
            });
        }

        function renderEditor(force) {
            const item = selectedItem();
            const ctx = context();
            const ids = selectedPlacementIds();
            const key = [item ? itemKey(item) : '', state.scope, state.partKey, ids.join(','), Boolean(ctx && ctx.canEdit),
                (state.parts || []).length, state.partsError, state.saving, state.busy, state.placing ? 'placing' : ''].join('|');
            if (!force && key === state.editorKey) return;
            state.editorKey = key;
            editor.textContent = '';
            // While editing, the tree yields height to the editor (see CSS).
            panel.setAttribute('data-editing', item ? 'true' : 'false');
            if (!item || state.scope !== 'part' || ids.length !== 1) clearPartHighlight();
            if (!item) {
                editor.append(element(doc, 'p', { className: 'ip-flib-note' },
                    'Choose a finish, scene or sign. Drag it onto the 3D view, or select objects and use Apply.'));
                return;
            }
            const headRow = element(doc, 'div', { className: 'ip-flib-editor-head' });
            const names = element(doc, 'div', { className: 'ip-flib-editor-names' });
            names.append(element(doc, 'strong', {}, item.label));
            const kindLabel = item.kind === 'appearance' ? (item.custom ? 'Custom finish' : (item.texture ? 'Textured finish' : 'Finish'))
                : item.kind === 'scene' ? 'Scene' : item.kind === 'decal' ? (item.code || 'Sign') : 'Placed decal';
            names.append(element(doc, 'small', {}, kindLabel));
            headRow.append(swatch(item, true), names);
            editor.append(headRow);
            if (item.description) editor.append(element(doc, 'p', { className: 'ip-flib-note' }, item.description));
            if (!ctx || !ctx.layout) {
                editor.append(element(doc, 'p', { className: 'ip-flib-note' }, 'Open a facility layout to use the library.'));
                return;
            }
            if (!ctx.canEdit) {
                editor.append(element(doc, 'p', { className: 'ip-flib-note' },
                    'Finish the active preview or operation to apply library items.'));
            }
            if (item.kind === 'appearance') renderAppearanceEditor(item, ctx, ids);
            else if (item.kind === 'scene') renderSceneEditor(item, ctx);
            else if (item.kind === 'decal') renderDecalEditor(item, ctx, ids);
            else if (item.kind === 'placed-decal') renderPlacedDecalEditor(item, ctx);
        }

        function renderAppearanceEditor(item, ctx, ids) {
            // Scopes the application supports: whole objects and single parts.
            // Faces cannot be selected, so there is no face scope.
            const scopes = element(doc, 'div', { className: 'ip-flib-segment', role: 'radiogroup', 'aria-label': 'Apply to' });
            const reason = partScopeReason();
            [['object', ids.length === 1 ? 'Selected object' : 'Selected objects (' + ids.length + ')'], ['part', 'One part']]
                .forEach(function (choice) {
                    const disabled = choice[0] === 'part' && reason;
                    const option = button(choice[1], function () {
                        if (disabled) return;
                        state.scope = choice[0];
                        cancelPreviews();
                        if (state.scope === 'part') ensureParts();
                        renderEditor(true);
                        schedulePreview();
                    }, { role: 'radio', 'aria-checked': state.scope === choice[0] ? 'true' : 'false',
                        disabled: disabled ? true : null, title: disabled ? reason : null });
                    scopes.append(option);
                });
            if (state.scope === 'part' && reason) state.scope = 'object';
            editor.append(scopes);
            if (!ids.length) {
                editor.append(element(doc, 'p', { className: 'ip-flib-note' },
                    'Select objects in the plan, the 3D view or Structure, or drag this finish onto an object.'));
            }
            if (state.scope === 'part') {
                const partRow = element(doc, 'div', { className: 'ip-flib-part' });
                if (!state.parts) {
                    partRow.append(element(doc, 'span', { className: 'ip-flib-note' }, 'Loading parts...'));
                } else {
                    const partSelect = select(state.parts.map(function (part) { return [part.key, part.label]; }),
                        state.partKey, 'Part');
                    partSelect.addEventListener('change', function () {
                        state.partKey = partSelect.value;
                        highlightPart(ids[0], state.partKey);
                        schedulePreview();
                    });
                    partRow.append(partSelect, button('Pick in 3D', function () { startPartPick(ids[0]); },
                        { title: 'Click the part in the 3D view' }));
                    if (state.partKey) highlightPart(ids[0], state.partKey);
                }
                editor.append(partRow);
            }
            const fields = element(doc, 'div', { className: 'ip-flib-fields' });
            // On a light the color is its glow (the library keeps the unlit plastic).
            const glow = item.emission && item.emission.color;
            const color = element(doc, 'input', { type: 'color',
                value: state.draft.color !== undefined ? state.draft.color : glow || draftValue(item, 'color', '#ffffff'),
                'aria-label': glow ? 'Glow color' : 'Color' });
            bindDraft(color, 'color', function (control) { return control.value.toLowerCase(); });
            field(fields, glow ? 'Glow color' : item.texture ? 'Tint' : 'Color', color);
            const roughness = range(0, 1, 0.01, draftValue(item, 'roughness', 0.6), 'Roughness');
            bindDraft(roughness, 'roughness', function (control) { return round(control.value, 2); });
            field(fields, 'Roughness', roughness);
            const metalness = range(0, 1, 0.01, draftValue(item, 'metalness', 0), 'Metalness');
            bindDraft(metalness, 'metalness', function (control) { return round(control.value, 2); });
            field(fields, 'Metalness', metalness);
            const opacity = range(0.05, 1, 0.01, draftValue(item, 'opacity', 1), 'Opacity');
            bindDraft(opacity, 'opacity', function (control) { return round(control.value, 2); });
            field(fields, 'Opacity', opacity);
            if (item.texture) {
                const size = element(doc, 'input', { type: 'number', min: '0.01', max: '50', step: '0.01',
                    value: String(textureValue(item, 'sizeMeters', 1)), 'aria-label': 'Texture size in meters' });
                bindDraft(size, 'sizeMeters', function (control) { return clamp(control.value, 0.01, 50); });
                field(fields, 'Texture size (m)', size, 'One repeat of the texture, in real-world meters.');
                const grain = select(GRAINS, textureValue(item, 'grain', 'length'), 'Grain direction');
                bindDraft(grain, 'grain', function (control) { return control.value; });
                field(fields, 'Grain', grain);
                const rotation = range(-180, 180, 1, textureValue(item, 'rotationDegrees', 0), 'Texture rotation');
                bindDraft(rotation, 'rotationDegrees', function (control) { return Number(control.value); });
                field(fields, 'Rotation', rotation);
                const mapping = select(MAPPINGS, textureValue(item, 'mapping', 'box'), 'Texture mapping');
                bindDraft(mapping, 'mapping', function (control) { return control.value; });
                field(fields, 'Mapping', mapping);
                const strength = range(0, 1, 0.01, textureValue(item, 'textureStrength', 1), 'Texture strength');
                bindDraft(strength, 'textureStrength', function (control) { return round(control.value, 2); });
                field(fields, 'Texture strength', strength);
            }
            editor.append(fields);
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            const canApply = ctx.canEdit && ids.length > 0 && (state.scope !== 'part' || state.partKey);
            actions.append(
                button('Apply', function () { applySelected(); }, { className: 'ip-flib-primary', disabled: !canApply || state.busy ? true : null }),
                button('Cancel', function () { cancelEdits(); }, { disabled: state.busy ? true : null }),
                button('Reset', function () { resetSelection(); }, { disabled: !ctx.canEdit || !ids.length || state.busy ? true : null,
                    title: state.scope === 'part' ? 'Restore this part to its object finish' : 'Restore each object to its own finish' }),
                button('Save as custom', function () { state.saving = true; renderEditor(true); },
                    { disabled: !ctx.canEdit || state.busy ? true : null, title: 'Save these settings with this layout' }));
            editor.append(actions);
            if (state.saving) renderSaveCustom(item);
            if (item.custom) {
                const usage = libraryApi.layoutUsage(library(), ctx.layout).appearances.find(function (row) {
                    return row.appearanceId === item.id;
                });
                editor.append(button('Delete custom finish', function () { deleteCustom(item); }, {
                    className: 'ip-flib-danger', disabled: usage || !ctx.canEdit ? true : null,
                    title: usage ? 'Change the objects that use it first.' : null }));
            }
            const source = item.texture && library() && library().textureSets.get(item.texture.textureSetId);
            editor.append(element(doc, 'p', { className: 'ip-flib-source' }, source
                ? 'Texture: ' + source.source.provider + ' ' + source.source.assetId + ', ' + source.source.license
                    + '. Visual only; engineering material and mass are unchanged.'
                : glow ? 'Glows in the 3D view like a switched-on lamp; it lights no other surface. Visual only.'
                : 'Visual only; engineering material and mass are unchanged.'));
        }

        function renderSaveCustom(item) {
            const row = element(doc, 'div', { className: 'ip-flib-save' });
            const name = element(doc, 'input', { type: 'text', maxlength: '80', 'aria-label': 'Custom finish name',
                placeholder: 'Name, e.g. Smoked oak' });
            name.value = item.custom ? item.label + ' copy' : item.label + ' (custom)';
            row.append(name,
                button('Save', function () { saveCustom(item, name.value); }, { className: 'ip-flib-primary' }),
                button('Cancel', function () { state.saving = false; renderEditor(true); }));
            editor.append(row);
            name.focus();
            name.select();
        }

        function renderSceneEditor(item, ctx) {
            const saved = libraryApi.layoutScene(ctx.layout);
            const resolved = libraryApi.resolveScene(library(), saved);
            editor.append(element(doc, 'p', { className: 'ip-flib-note' },
                'Saved with this layout: ' + resolved.label + '. A scene changes only the view, never the equipment.'));
            const fields = element(doc, 'div', { className: 'ip-flib-fields' });
            const exposure = range(0.2, 3, 0.01, draftValue(item, 'exposure', 1), 'Exposure');
            bindDraft(exposure, 'exposure', function (control) { return round(control.value, 2); });
            field(fields, 'Exposure', exposure);
            if (item.environment) {
                const environment = range(0, 3, 0.01, draftValue(item, 'environmentIntensity', 1), 'Reflection and fill strength');
                bindDraft(environment, 'environmentIntensity', function (control) { return round(control.value, 2); });
                field(fields, 'Reflections', environment);
                const rotation = range(-180, 180, 1, draftValue(item, 'environmentRotationDegrees', 0), 'Lighting rotation');
                bindDraft(rotation, 'environmentRotationDegrees', function (control) { return Number(control.value); });
                field(fields, 'Light direction', rotation);
            }
            const backgroundChoices = [['theme', 'App theme']];
            if (item.environment && item.environment !== 'room') backgroundChoices.push(['environment', 'Scene photo (blurred)']);
            const currentBackground = draftValue(item, 'background', 'theme');
            backgroundChoices.push(['color', 'Solid color']);
            const backgroundKind = /^#/.test(currentBackground) ? 'color' : currentBackground;
            const background = select(backgroundChoices, backgroundKind, 'Background');
            const backgroundColor = element(doc, 'input', { type: 'color', 'aria-label': 'Background color',
                value: /^#/.test(currentBackground) ? currentBackground : '#eef0f2' });
            backgroundColor.hidden = backgroundKind !== 'color';
            const syncBackground = function () {
                backgroundColor.hidden = background.value !== 'color';
                state.draft.background = background.value === 'color' ? backgroundColor.value.toLowerCase() : background.value;
                schedulePreview();
            };
            background.addEventListener('change', syncBackground);
            backgroundColor.addEventListener('input', syncBackground);
            const backgroundRow = element(doc, 'span', { className: 'ip-flib-inline' });
            backgroundRow.append(background, backgroundColor);
            field(fields, 'Background', backgroundRow, 'Your own Display settings background still wins.');
            const shadows = element(doc, 'input', { type: 'checkbox', 'aria-label': 'Sun shadows' });
            shadows.checked = Boolean(draftValue(item, 'shadows', false));
            shadows.addEventListener('change', function () { state.draft.shadows = shadows.checked; schedulePreview(); });
            field(fields, 'Sun shadows', shadows, 'Shadows cost frame rate on very large layouts.');
            const lights = element(doc, 'input', { type: 'checkbox', 'aria-label': 'Lights on' });
            lights.checked = draftValue(item, 'lights', true) !== false;
            lights.addEventListener('change', function () { state.draft.lights = lights.checked; schedulePreview(); });
            field(fields, 'Lights on', lights, 'Off: lamps, beacons and signs show unlit.');
            if (item.lightPools) {
                // Glow halo (lighting L6): saved with the scene, off by default, drawn with the lights on.
                const halo = element(doc, 'input', { type: 'checkbox', 'aria-label': 'Glow halo' });
                halo.checked = draftValue(item, 'glowHalo', false) === true;
                halo.addEventListener('change', function () { state.draft.glowHalo = halo.checked; schedulePreview(); });
                field(fields, 'Glow halo', halo, 'A soft halo around lit lamps, signs and beacons. Costs frame rate.');
            }
            renderLightAreas(fields, item, ctx);
            editor.append(fields);
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            actions.append(
                button('Apply', function () { applySelected(); }, { className: 'ip-flib-primary', disabled: !ctx.canEdit || state.busy ? true : null }),
                button('Cancel', function () { cancelEdits(); }),
                button('Reset to Classic', function () { resetScene(); }, { disabled: !ctx.canEdit || !saved || state.busy ? true : null }));
            editor.append(actions);
            const environment = item.environment && item.environment !== 'room' ? library().environments.get(item.environment) : null;
            editor.append(element(doc, 'p', { className: 'ip-flib-source' }, environment
                ? 'Lighting: ' + environment.source.provider + ' ' + environment.label + ' by ' + environment.source.author + ', '
                    + environment.source.license + '.'
                : item.environment === 'room' ? 'Lighting: built-in neutral room.' : 'Lighting: InspectorPro standard.'));
            coverageBox = element(doc, 'div', { className: 'ip-flib-coverage', role: 'group', 'aria-label': 'Lighting coverage' });
            editor.append(coverageBox);
            fillCoverage(coverageBox, ctx);
        }

        // Lighting coverage (docs/facility-lighting-plan.md, CC3): an estimate of one area from this layout's lights
        // and its saved scene, drawn on the floor in the plan and the 3D view until hidden. Never saved.
        function coverageChoices() {
            const value = layout();
            const choices = [['lot', 'Car parks and truck yards']];
            floorAreas().forEach(function (floor) {
                choices.push(['floor:' + floor.surfaceId, 'Floor area: ' + (floor.label || floor.surfaceId)]);
            });
            (value && Array.isArray(value.zones) ? value.zones : []).forEach(function (zone) {
                if (zone && zone.zoneId) choices.push(['zone:' + zone.zoneId, 'Zone: ' + (zone.label || zone.zoneId)]);
            });
            return choices;
        }

        function coverageArea(choice) {
            if (choice === 'lot') return { lot: true };
            if (choice.indexOf('floor:') === 0) return { floorAreaId: choice.slice(6) };
            return { zoneId: choice.slice(5) };
        }

        function count(value) { return Math.round(Number(value) || 0).toLocaleString('en-US'); }

        function fillCoverage(box, ctx) {
            const shown = ctx && ctx.lightCoverage || null;
            box.textContent = '';
            box.setAttribute('data-token', shown ? String(shown.token) : '');
            box.append(element(doc, 'strong', {}, 'Lighting coverage'));
            const choices = coverageChoices();
            const wanted = shown && shown.choice || state.coverageArea;
            const current = choices.some(function (choice) { return choice[0] === wanted; }) ? wanted : choices[0][0];
            const area = select(choices, current, 'Area to check');
            area.addEventListener('change', function () { state.coverageArea = area.value; });
            const row = element(doc, 'span', { className: 'ip-flib-inline' });
            row.append(area, button(state.coverageBusy ? 'Estimating...' : 'Show', function () { showCoverage(area.value); },
                { className: 'ip-flib-primary', disabled: !ctx || typeof ctx.showLightCoverage !== 'function'
                    || state.coverageBusy ? true : null }));
            if (shown) row.append(button('Hide', hideCoverage));
            box.append(row);
            if (state.coverageError) {
                box.append(element(doc, 'p', { className: 'ip-flib-coverage-error', role: 'alert' }, state.coverageError));
            }
            box.append(element(doc, 'p', { className: 'ip-flib-field-note' }, 'From each lamp\'s height, typical output '
                + 'and beam, with this layout\'s saved scene. Drawn on the floor in the plan and the 3D view; not saved.'));
            if (!shown) return;
            const summary = shown.summary || {};
            const where = summary.area || {};
            const lux = summary.estimatedLux || {};
            const lamps = summary.lamps || {};
            const dark = summary.darkSpots || {};
            const label = String(where.label || 'the area');
            box.append(element(doc, 'p', { className: 'ip-flib-coverage-caption' }, shown.caption));
            box.append(element(doc, 'p', {}, label.charAt(0).toUpperCase() + label.slice(1) + ', ' + count(where.sizeSquareMeters)
                + ' sq m: estimated ' + lux.minimum + ' to ' + lux.maximum + ' lux, mean ' + lux.mean + '.'));
            const off = (lamps.offBySwitch || 0) + (lamps.offByArea || 0);
            box.append(element(doc, 'p', { className: 'ip-flib-field-note' }, (lamps.lightingThisArea || 0) + ' of '
                + (lamps.on || 0) + ' lamps that are on light it' + (off ? '; ' + off + ' off by the scene.' : '.')));
            if (dark.note) {
                box.append(element(doc, 'p', {}, dark.note));
                return;
            }
            box.append(element(doc, 'p', {}, dark.count ? 'Dark spots, below ' + dark.belowLux + ' lux (' + dark.basis + '): '
                + (dark.count > shown.spots.length ? 'the ' + shown.spots.length + ' largest of ' + dark.count : dark.count)
                + ', outlined and numbered on the floor.' : 'No dark spots below ' + dark.belowLux + ' lux (' + dark.basis + ').'));
            if (!shown.spots.length) return;
            const list = element(doc, 'ol', { className: 'ip-flib-coverage-spots' });
            shown.spots.forEach(function (spot) {
                const near = (spot.nearestLamps || []).map(function (lamp) {
                    return lamp.label + ' (' + lamp.distanceMeters + ' m)';
                });
                list.append(element(doc, 'li', {}, count(spot.sizeSquareMeters) + ' sq m around ' + spot.centre.x + ', '
                    + spot.centre.z + ': mean ' + spot.meanLux + ' lux, lowest ' + spot.minimumLux + '.'
                    + (near.length ? ' Nearest: ' + near.join(', ') + '.' : '')));
            });
            box.append(list);
        }

        async function showCoverage(choice) {
            const ctx = context();
            if (!ctx || typeof ctx.showLightCoverage !== 'function' || state.coverageBusy) return;
            state.coverageArea = choice;
            state.coverageBusy = true;
            state.coverageError = '';
            setStatus('Estimating the lighting...', 'info');
            if (coverageBox) fillCoverage(coverageBox, ctx);
            try {
                const shown = await ctx.showLightCoverage(coverageArea(choice), choice);
                setStatus(shown ? 'Shown in the plan and the 3D view.' : '', 'info');
            } catch (error) {
                // Said in the block, by the button: the status line can be one line high with the scene editor open.
                state.coverageError = error && error.message ? error.message : 'The lighting estimate failed.';
                setStatus('', 'info');
            } finally {
                state.coverageBusy = false;
                if (coverageBox) fillCoverage(coverageBox, context());
            }
        }

        function hideCoverage() {
            const ctx = context();
            if (ctx && typeof ctx.hideLightCoverage === 'function') ctx.hideLightCoverage();
            state.coverageError = '';
            setStatus('', 'info');
            if (coverageBox) fillCoverage(coverageBox, context());
        }

        // The workspace drops the estimate when the layout changes; the block follows.
        function syncCoverage(ctx) {
            if (!coverageBox || state.coverageBusy
                    || (typeof editor.contains === 'function' && !editor.contains(coverageBox))) return;
            const token = ctx && ctx.lightCoverage ? String(ctx.lightCoverage.token) : '';
            if (coverageBox.getAttribute('data-token') !== token) fillCoverage(coverageBox, ctx);
        }

        // General lights per area (docs/facility-lighting-plan.md, L7): everywhere, only in some areas, or everywhere
        // except in them. The areas are the layout's floor areas, ticked, and rectangles drawn on the plan.
        function renderLightAreas(fields, item, ctx) {
            const saved = draftValue(item, 'lightAreas', null);
            const mode = saved && LIGHT_AREA_MODES.indexOf(saved.mode) >= 0 ? saved.mode : 'everywhere';
            const choice = select([['everywhere', 'Everywhere'], ['only', 'Only in'], ['except', 'Everywhere except']],
                mode, 'General lights');
            field(fields, 'General lights', choice, 'Lamps hung 3 m or higher. Exit signs and beacons stay on.');
            const box = element(doc, 'div', { className: 'ip-flib-areas', role: 'group', 'aria-label': 'Light areas' });
            fields.append(box);
            let kept = saved && Array.isArray(saved.areas) ? saved.areas : [];
            choice.addEventListener('change', function () {
                const current = state.draft.lightAreas;
                if (current) kept = current.areas;
                if (choice.value === 'everywhere') delete state.draft.lightAreas;
                else state.draft.lightAreas = { mode: choice.value, areas: kept.slice() };
                renderAreaChoices(box, ctx);
                schedulePreview();
            });
            renderAreaChoices(box, ctx);
        }

        function floorAreas() {
            const rows = layout() && layout().extensions && layout().extensions.facilityFloorSurfaces;
            return (rows && Array.isArray(rows.surfaces) ? rows.surfaces : []).filter(function (row) {
                return row && typeof row.surfaceId === 'string';
            });
        }

        function metres(value) { return String(round(value, 1)); }

        function renderAreaChoices(box, ctx) {
            box.textContent = '';
            const value = state.draft.lightAreas;
            box.hidden = !value;
            if (!value) return;
            const full = value.areas.length >= MAX_LIGHT_AREAS;
            const changed = function () { renderAreaChoices(box, ctx); schedulePreview(); };
            const floors = floorAreas();
            const known = new Set(floors.map(function (floor) { return floor.surfaceId; }));
            const list = element(doc, 'div', { className: 'ip-flib-area-list' });
            floors.forEach(function (floor) {
                const ticked = value.areas.some(function (area) { return area.surfaceId === floor.surfaceId; });
                const tick = element(doc, 'input', { type: 'checkbox', 'aria-label': floor.label || floor.surfaceId,
                    disabled: full && !ticked ? true : null });
                tick.checked = ticked;
                tick.addEventListener('change', function () {
                    value.areas = value.areas.filter(function (area) { return area.surfaceId !== floor.surfaceId; });
                    if (tick.checked) value.areas.push({ surfaceId: floor.surfaceId });
                    changed();
                });
                const row = element(doc, 'label', { className: 'ip-flib-area' });
                row.append(tick, element(doc, 'span', { title: floor.label || floor.surfaceId }, floor.label || floor.surfaceId));
                list.append(row);
            });
            if (floors.length) box.append(list);
            else box.append(element(doc, 'p', { className: 'ip-flib-field-note' }, 'This layout has no floor areas; draw one.'));
            value.areas.forEach(function (area) {
                if (area.surfaceId && !known.has(area.surfaceId)) {
                    box.append(element(doc, 'p', { className: 'ip-flib-field-note' }, area.surfaceId
                        + ' was removed from the layout: it lights nothing and is dropped on Apply.'));
                }
                if (!area.rectangle) return;
                const box2 = area.rectangle;
                const row = element(doc, 'div', { className: 'ip-flib-area ip-flib-area-drawn' });
                row.append(element(doc, 'span', {}, 'Drawn ' + metres(box2.maxX - box2.minX) + ' x '
                    + metres(box2.maxZ - box2.minZ) + ' m at ' + metres((box2.minX + box2.maxX) / 2) + ', '
                    + metres((box2.minZ + box2.maxZ) / 2)), button('Remove', function () {
                    value.areas = value.areas.filter(function (other) { return other !== area; });
                    changed();
                }));
                box.append(row);
            });
            box.append(button('Draw an area on the plan', function () { drawLightArea(ctx); },
                { disabled: !ctx.canEdit || full || typeof ctx.drawLightArea !== 'function' ? true : null }));
        }

        // The plan opens for one dragged rectangle; the 3D view (and the preview) come back with it.
        function drawLightArea(ctx) {
            const item = selectedItem();
            const key = item && itemKey(item);
            const layoutId = layout() && layout().layoutId;
            const started = ctx.drawLightArea(function (rectangle) {
                const now = selectedItem();
                const value = state.draft.lightAreas;
                if (!rectangle || !value || !now || itemKey(now) !== key || (layout() && layout().layoutId) !== layoutId) {
                    setStatus(rectangle ? '' : 'No area drawn.');
                    return;
                }
                if (value.areas.length < MAX_LIGHT_AREAS) value.areas.push({ rectangle: rectangle });
                setStatus('Area added. Apply saves it with the scene.');
                renderEditor(true);
                schedulePreview();
            });
            setStatus(started ? 'Drag a rectangle on the plan. Esc cancels.' : 'The plan is not available.', started ? 'info' : 'error');
        }

        function renderDecalEditor(item, ctx, ids) {
            const preview = element(doc, 'div', { className: 'ip-flib-decal-preview' });
            preview.append(element(doc, 'img', { src: item.url, alt: item.label }));
            editor.append(preview);
            const fields = element(doc, 'div', { className: 'ip-flib-fields' });
            const width = element(doc, 'input', { type: 'number', min: '0.05', max: '5', step: '0.01',
                value: String(state.draft.widthMeters || item.widthMeters || 0.3), 'aria-label': 'Sign width in meters' });
            width.addEventListener('input', function () { state.draft.widthMeters = clamp(width.value, 0.05, 5); });
            field(fields, 'Width (m)', width, 'Height follows the sign: ' + round((state.draft.widthMeters || 0.3) / item.aspect, 3) + ' m.');
            const rotation = range(-180, 180, 1, state.draft.rotationDegrees || 0, 'Sign rotation');
            rotation.addEventListener('input', function () { state.draft.rotationDegrees = Number(rotation.value); });
            field(fields, 'Rotation', rotation, 'For signs placed on equipment.');
            editor.append(fields);
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            actions.append(
                button(state.placing ? 'Click a spot on equipment...' : 'Place on equipment', function () {
                    if (state.placing) { stopPlacing('Placement cancelled.'); return; }
                    startPlacing(item);
                }, { className: 'ip-flib-primary', disabled: !ctx.canEdit || state.busy ? true : null,
                    'aria-pressed': state.placing ? 'true' : 'false' }),
                button('Place on a wall...', function () { placeOnWall(item, null); },
                    { disabled: !ctx.canEdit || state.busy ? true : null }));
            editor.append(actions);
            editor.append(element(doc, 'p', { className: 'ip-flib-source' }, item.code + '. Public domain artwork from Wikimedia Commons. '
                + 'Check your site rules and the current ISO 7010 edition before relying on signs.'));
            if (!ids.length && !state.placing) {
                editor.append(element(doc, 'p', { className: 'ip-flib-note' }, 'Tip: drag the sign onto equipment in the 3D view.'));
            }
        }

        function renderPlacedDecalEditor(item, ctx) {
            const row = item.row;
            editor.append(element(doc, 'p', { className: 'ip-flib-note' }, 'On ' + placementLabel(row.placementId) + '.'));
            const fields = element(doc, 'div', { className: 'ip-flib-fields' });
            const width = element(doc, 'input', { type: 'number', min: '0.02', max: '10', step: '0.01',
                value: String(state.draft.widthMeters || row.widthMeters), 'aria-label': 'Decal width in meters' });
            width.addEventListener('input', function () { state.draft.widthMeters = clamp(width.value, 0.02, 10); });
            field(fields, 'Width (m)', width);
            const rotation = range(-180, 180, 1, state.draft.rotationDegrees || 0, 'Decal rotation');
            rotation.addEventListener('input', function () { state.draft.rotationDegrees = Number(rotation.value); });
            field(fields, 'Rotation', rotation);
            editor.append(fields);
            const actions = element(doc, 'div', { className: 'ip-flib-actions' });
            actions.append(
                button('Update', function () { updatePlacedDecal(row); }, { className: 'ip-flib-primary', disabled: !ctx.canEdit || state.busy ? true : null }),
                button('Remove', function () { removePlacedDecal(row); }, { className: 'ip-flib-danger', disabled: !ctx.canEdit || state.busy ? true : null }));
            editor.append(actions);
        }

        // ---- Actions ------------------------------------------------------------
        async function run(label, task) {
            if (state.busy) return null;
            state.busy = true;
            renderEditor(true);
            try {
                const result = await task();
                return result;
            } catch (error) {
                setStatus(label + ': ' + (error && error.message ? error.message : String(error)), 'error');
                return null;
            } finally {
                state.busy = false;
                if (!destroyed) renderEditor(true);
            }
        }

        function pushRecent(kind, id) {
            preferences.pushRecent(kind, id);
            renderTree();
        }

        async function applyAppearance(item, placementIds, partKey) {
            const ctx = context();
            if (!ctx || !ctx.canEdit) throw new Error('Finish the active preview or operation first.');
            if (!placementIds.length) throw new Error('Select or drop onto at least one object.');
            const value = appearanceValue(item);
            if (partKey) {
                const three = adapter();
                const placementId = placementIds[0];
                const model = three && typeof three.getComponentMaterials === 'function'
                    ? await three.getComponentMaterials(placementId) : null;
                if (!model) throw new Error('Load the object in 3D to finish one part.');
                const slot = (model.slots || []).find(function (row) { return row.key === partKey; });
                const placement = ctx.layout.placements.find(function (row) { return row.placementId === placementId; });
                const existing = placement && placement.componentMaterials ? placement.componentMaterials.overrides : [];
                const legacy = slot && slot.legacyKey;
                const overrides = existing.filter(function (row) { return row.key !== partKey && row.key !== legacy; })
                    .concat([Object.assign({ key: partKey }, value)]);
                await ctx.session.setComponentMaterials(placementId, { representation: model.representation, overrides: overrides });
                setStatus(item.label + ' applied to one part of ' + placementLabel(placementId) + '.');
            } else {
                await ctx.session.setPlacementsAppearance(placementIds, value);
                setStatus(item.label + ' applied to ' + placementIds.length + ' object' + (placementIds.length === 1 ? '' : 's') + '.');
            }
            pushRecent('appearance', item.id);
        }

        function applySelected() {
            const item = selectedItem();
            if (!item) return;
            if (item.kind === 'appearance') {
                const ids = selectedPlacementIds();
                run('Apply', function () {
                    return applyAppearance(item, ids, state.scope === 'part' ? state.partKey : null).then(function () {
                        cancelPreviews();
                    });
                });
            } else if (item.kind === 'scene') {
                run('Apply scene', async function () {
                    const ctx = context();
                    if (!ctx || !ctx.canEdit) throw new Error('Finish the active preview or operation first.');
                    await ctx.session.setViewportScene(sceneValue(item));
                    cancelPreviews();
                    pushRecent('scene', item.id);
                    setStatus(item.label + ' is now saved with this layout.');
                });
            } else if (item.kind === 'decal') {
                startPlacing(item);
            }
        }

        function cancelEdits() {
            cancelPreviews();
            state.draft = {};
            const item = selectedItem();
            if (item && item.kind === 'decal') state.draft = { widthMeters: item.widthMeters || 0.3, rotationDegrees: 0 };
            if (item && item.kind === 'scene') state.draft = savedSceneDraft(item);
            stopPlacing();
            setStatus('Changes discarded.');
            renderEditor(true);
        }

        function resetSelection() {
            const ids = selectedPlacementIds();
            run('Reset', async function () {
                const ctx = context();
                if (state.scope === 'part' && ids.length === 1 && state.partKey) {
                    const placement = ctx.layout.placements.find(function (row) { return row.placementId === ids[0]; });
                    const existing = placement && placement.componentMaterials ? placement.componentMaterials.overrides : [];
                    const slot = (state.parts || []).find(function (part) { return part.key === state.partKey; });
                    const remaining = existing.filter(function (row) { return row.key !== state.partKey && (!slot || row.key !== slot.legacyKey); });
                    await ctx.session.setComponentMaterials(ids[0], remaining.length
                        ? { representation: placement.componentMaterials.representation, overrides: remaining } : null);
                    setStatus('The part shows its object finish again.');
                } else {
                    await ctx.session.setPlacementsAppearance(ids, null);
                    setStatus('Each object shows its own finish again.');
                }
                cancelPreviews();
            });
        }

        function resetScene() {
            run('Reset scene', async function () {
                await context().session.setViewportScene(null);
                cancelPreviews();
                setStatus('The Classic scene is restored.');
            });
        }

        function saveCustom(item, name) {
            const label = String(name || '').trim();
            if (!label) { setStatus('Enter a name for the custom finish.', 'error'); return; }
            run('Save custom finish', async function () {
                const ctx = context();
                const existing = libraryApi.customAppearances(ctx.layout).map(function (row) { return JSON.parse(JSON.stringify(row)); });
                const base = item.custom ? item.baseAppearanceId : item.id;
                const inherited = item.custom ? existing.find(function (row) { return row.appearanceId === item.id; }) : null;
                const row = Object.assign({}, inherited || {}, appearanceValue(item), {
                    appearanceId: 'custom-' + slug(label) + '-' + randomId(doc).replace(/[^a-z0-9]/g, '').slice(0, 6),
                    label: label, baseAppearanceId: base,
                });
                await ctx.session.setCustomAppearances({ version: 1, custom: existing.concat([row]) });
                state.saving = false;
                state.selected = { kind: 'appearance', id: row.appearanceId };
                state.draft = {};
                state.node = { kind: 'category', id: 'custom' };
                setStatus(label + ' is saved with this layout.');
                render();
            });
        }

        function deleteCustom(item) {
            run('Delete custom finish', async function () {
                const ctx = context();
                const remaining = libraryApi.customAppearances(ctx.layout).filter(function (row) { return row.appearanceId !== item.id; });
                await ctx.session.setCustomAppearances({ version: 1, custom: remaining });
                state.selected = null;
                setStatus(item.label + ' was deleted.');
                render();
            });
        }

        async function importSign(item) {
            const ctx = context();
            const blob = await rasterizeDecal(doc, item, 1024);
            return ctx.session.importDecalImage(blob);
        }

        function placeOnWall(item, target) {
            run('Place on wall', async function () {
                const ctx = context();
                if (!ctx || !ctx.canEdit) throw new Error('Finish the active preview or operation first.');
                const imported = await importSign(item);
                ctx.openWallDecals({ imported: imported, label: item.label, target: target, aspect: item.aspect,
                    widthMeters: state.draft.widthMeters || item.widthMeters });
                pushRecent('decal', item.id);
            });
        }

        async function placeEquipmentDecal(item, hit) {
            const ctx = context();
            if (!ctx || !ctx.canEdit) throw new Error('Finish the active preview or operation first.');
            const imported = await importSign(item);
            const width = clamp(state.draft.widthMeters || item.widthMeters || 0.3, 0.05, 5);
            const existing = ctx.layout.extensions && ctx.layout.extensions.facilityEquipmentDecals;
            const rows = existing && Array.isArray(existing.decals) ? JSON.parse(JSON.stringify(existing.decals)) : [];
            rows.push({ decalId: 'edecal-' + randomId(doc).replace(/[^a-z0-9]/g, ''), label: item.label,
                imagePath: imported.imagePath, placementId: hit.placementId, anchor: hit.anchor,
                widthMeters: round(width, 4), heightMeters: round(width / (item.aspect || 1), 4), libraryDecalId: item.id });
            await ctx.session.setEquipmentDecals({ version: 1, decals: rows });
            pushRecent('decal', item.id);
            setStatus(item.label + ' placed on ' + placementLabel(hit.placementId) + '.');
        }

        function updatePlacedDecal(row) {
            run('Update decal', async function () {
                const ctx = context();
                const rows = JSON.parse(JSON.stringify(ctx.layout.extensions.facilityEquipmentDecals.decals));
                const target = rows.find(function (item) { return item.decalId === row.decalId; });
                if (!target) throw new Error('This decal is no longer in the layout.');
                const aspect = target.widthMeters / target.heightMeters;
                if (state.draft.widthMeters) {
                    target.widthMeters = round(state.draft.widthMeters, 4);
                    target.heightMeters = round(state.draft.widthMeters / aspect, 4);
                }
                if (state.draft.rotationDegrees !== undefined) target.anchor.rotationDegrees = state.draft.rotationDegrees;
                await ctx.session.setEquipmentDecals({ version: 1, decals: rows });
                setStatus(row.label + ' updated.');
            });
        }

        function removePlacedDecal(row) {
            run('Remove decal', async function () {
                const ctx = context();
                const rows = ctx.layout.extensions.facilityEquipmentDecals.decals.filter(function (item) {
                    return item.decalId !== row.decalId;
                });
                await ctx.session.setEquipmentDecals({ version: 1, decals: rows });
                state.selected = null;
                setStatus(row.label + ' removed.');
                render();
            });
        }

        // ---- 3D interactions: placing, part picking and drops -----------------------------
        function canvasPoint(event) { return { clientX: event.clientX, clientY: event.clientY }; }

        function startPlacing(item) {
            const ctx = context();
            if (!ctx || !ctx.dropTarget || !adapter()) {
                setStatus('Placing signs on equipment needs the 3D view.', 'error');
                return;
            }
            ctx.show3d();
            stopPlacing();
            const target = ctx.dropTarget;
            const handler = function (event) {
                event.preventDefault();
                event.stopPropagation();
                const three = adapter();
                const hit = three && typeof three.decalAnchorAt === 'function'
                    ? three.decalAnchorAt(canvasPoint(event), state.draft.rotationDegrees || 0) : null;
                stopPlacing();
                if (!hit) { setStatus('No equipment under that point. Try again or use Place on a wall.', 'error'); return; }
                if (ctx.isWallAsset(hit.placementId)) { placeOnWall(item, null); return; }
                run('Place sign', function () { return placeEquipmentDecal(item, hit); });
            };
            const key = function (event) { if (event.key === 'Escape') stopPlacing('Placement cancelled.'); };
            target.addEventListener('click', handler, true);
            doc.addEventListener('keydown', key, true);
            state.placing = { target: target, handler: handler, key: key };
            setStatus('Click the spot on the equipment where the sign goes. Esc cancels.');
            renderEditor(true);
        }

        function stopPlacing(message) {
            if (!state.placing) return;
            state.placing.target.removeEventListener('click', state.placing.handler, true);
            doc.removeEventListener('keydown', state.placing.key, true);
            state.placing = null;
            if (message) setStatus(message);
            renderEditor(true);
        }

        function startPartPick(placementId) {
            const ctx = context();
            if (!ctx || !ctx.dropTarget) return;
            const target = ctx.dropTarget;
            const handler = function (event) {
                event.preventDefault();
                event.stopPropagation();
                target.removeEventListener('click', handler, true);
                const three = adapter();
                const hit = three && three.pick(Object.assign(canvasPoint(event), { parts: true }));
                if (!hit || hit.placementId !== placementId || !hit.partKey) {
                    setStatus('Click a part of the selected object.', 'error');
                    return;
                }
                state.partKey = hit.partKey;
                const part = (state.parts || []).find(function (item) { return item.key === hit.partKey; });
                setStatus(part ? 'Part: ' + part.label : '');
                renderEditor(true);
                schedulePreview();
            };
            target.addEventListener('click', handler, true);
            setStatus('Click the part in the 3D view.');
        }

        function readDrag(event) {
            const data = event.dataTransfer;
            if (!data) return null;
            try { return JSON.parse(data.getData(DRAG_TYPE) || 'null'); } catch (_) { return null; }
        }

        function hasLibraryDrag(event) {
            const types = event.dataTransfer && event.dataTransfer.types;
            return Boolean(types && Array.from(types).indexOf(DRAG_TYPE) >= 0);
        }

        function handleDrop(event) {
            const ref = readDrag(event);
            if (!ref) return;
            event.preventDefault();
            const lib = library();
            const ctx = context();
            const item = lib && libraryApi.findItem(lib, ref.kind, ref.id, ctx && ctx.layout);
            const three = adapter();
            if (!item || !ctx || !three) return;
            if (item.kind === 'scene') {
                selectItem(item);
                applySelected();
                return;
            }
            const hit = three.pick(Object.assign(canvasPoint(event), { parts: Boolean(event.shiftKey) }));
            if (item.kind === 'appearance') {
                if (!hit) { setStatus('Drop the finish onto an object.', 'error'); return; }
                const selection = selectedPlacementIds();
                const ids = event.shiftKey ? [hit.placementId]
                    : selection.indexOf(hit.placementId) >= 0 ? selection : [hit.placementId];
                const partKey = event.shiftKey ? hit.partKey : null;
                if (event.shiftKey && !partKey) { setStatus('That spot is not a separate part; drop without Shift to finish the object.', 'error'); return; }
                selectItem(item);
                run('Apply', function () { return applyAppearance(item, ids, partKey); });
                return;
            }
            if (item.kind === 'decal') {
                selectItem(item);
                const anchor = hit && typeof three.decalAnchorAt === 'function'
                    ? three.decalAnchorAt(canvasPoint(event), state.draft.rotationDegrees || 0) : null;
                if (!anchor || ctx.isWallAsset(anchor.placementId)) {
                    placeOnWall(item, null);
                    return;
                }
                run('Place sign', function () { return placeEquipmentDecal(item, anchor); });
            }
        }

        function attachDropTarget() {
            const ctx = context();
            const target = ctx && ctx.dropTarget;
            if (target === dropTarget) return;
            detachDropTarget();
            if (!target) return;
            dropHandlers = {
                over: function (event) {
                    if (!hasLibraryDrag(event)) return;
                    event.preventDefault();
                    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
                    target.classList.add('ip-flib-drop-active');
                },
                leave: function () { target.classList.remove('ip-flib-drop-active'); },
                drop: function (event) {
                    target.classList.remove('ip-flib-drop-active');
                    if (hasLibraryDrag(event)) handleDrop(event);
                },
            };
            target.addEventListener('dragover', dropHandlers.over);
            target.addEventListener('dragleave', dropHandlers.leave);
            target.addEventListener('drop', dropHandlers.drop);
            dropTarget = target;
        }

        function detachDropTarget() {
            if (!dropTarget || !dropHandlers) return;
            dropTarget.removeEventListener('dragover', dropHandlers.over);
            dropTarget.removeEventListener('dragleave', dropHandlers.leave);
            dropTarget.removeEventListener('drop', dropHandlers.drop);
            dropTarget = null;
            dropHandlers = null;
        }

        // ---- Rendering ----------------------------------------------------------
        function renderHead() {
            const ctx = context();
            const ids = selectedPlacementIds();
            scopeLabel.textContent = !ctx || !ctx.layout ? 'No layout open'
                : ids.length ? ids.length + ' selected' : '';
        }

        function renderHint() {
            hint.textContent = state.placing ? '' : 'Drag items onto the 3D view, or select objects and press Apply.';
        }

        function render() {
            if (destroyed) return;
            renderHead();
            renderTree();
            renderGrid();
            renderHint();
            renderEditor(true);
        }

        // Session and structure notifications arrive often; only selection and
        // layout changes need a redraw, and the editor keeps its inputs unless
        // what it shows changed.
        let lastSignature = '';
        function refresh() {
            if (destroyed) return;
            const ctx = context();
            const ids = selectedPlacementIds();
            if (state.partsFor && (ids.length !== 1 || ids[0] !== state.partsFor)) {
                state.parts = null; state.partsFor = null; state.partsError = '';
                if (state.scope === 'part') { state.scope = 'object'; cancelPreviews(); }
            }
            if (state.scope === 'part') ensureParts();
            attachDropTarget();
            const layoutValue = ctx && ctx.layout;
            const signature = JSON.stringify([ids, layoutValue && layoutValue.layoutId,
                layoutValue && libraryApi.layoutUsage(library(), layoutValue), Boolean(ctx && ctx.canEdit), Boolean(library())]);
            syncCoverage(ctx);
            if (signature === lastSignature) return;
            lastSignature = signature;
            renderHead();
            renderTree();
            renderGrid();
            renderEditor(false);
        }

        function bind(nextWorkspace) {
            unsubscribers.forEach(function (stop) { try { stop(); } catch (_) {} });
            unsubscribers = [];
            cancelPreviews();
            stopPlacing();
            detachDropTarget();
            workspace = nextWorkspace || null;
            state.parts = null; state.partsFor = null; state.partsError = '';
            lastSignature = '';
            if (workspace && typeof workspace.subscribeStructure === 'function') {
                unsubscribers.push(workspace.subscribeStructure(refresh));
            }
            const session = workspace && workspace.session;
            if (session && typeof session.subscribe === 'function') {
                const stop = session.subscribe(function () { refresh(); });
                if (typeof stop === 'function') unsubscribers.push(stop);
            }
            refresh();
            render();
        }

        // Open at a tree node, e.g. from the ribbon's Appearance command.
        function open(request) {
            const value = request || {};
            if (['scenes', 'decals', 'appearances'].indexOf(value.node) >= 0) {
                state.expanded.clear();
                state.expanded.add(value.node);
            }
            if (value.node === 'scenes') state.node = { kind: 'root', id: 'scenes' };
            else if (value.node === 'decals') state.node = { kind: 'root', id: 'decals' };
            else if (value.node === 'appearances' && state.node.kind !== 'category') {
                state.node = { kind: 'category', id: 'metals' };
            }
            if (value.scope === 'part' || value.scope === 'object') {
                state.scope = value.scope;
                if (state.scope === 'part') ensureParts();
            }
            render();
            const row = tree.querySelector('.ip-flib-node[aria-selected="true"]');
            if (row) row.focus();
        }

        const stopLibrary = store.subscribe(function () { lastSignature = ''; render(); });
        store.load().catch(function () { render(); });
        render();

        return {
            bind: bind,
            open: open,
            refresh: refresh,
            render: render,
            element: panel,
            state: function () {
                return { node: Object.assign({}, state.node), selected: state.selected && Object.assign({}, state.selected),
                    scope: state.scope, partKey: state.partKey, draft: JSON.parse(JSON.stringify(state.draft)),
                    status: state.status, placing: Boolean(state.placing) };
            },
            select: function (kind, id) {
                const item = libraryApi.findItem(library(), kind, id, layout());
                if (item) selectItem(item);
                return Boolean(item);
            },
            setDraft: function (patch) { Object.assign(state.draft, patch || {}); schedulePreview(); },
            apply: applySelected,
            destroy: function () {
                destroyed = true;
                bind(null);
                stopLibrary();
                if (panel.parentNode) panel.parentNode.removeChild(panel);
            },
        };
    }

    return { createLibraryPanel: createLibraryPanel, rasterizeDecal: rasterizeDecal, DRAG_TYPE: DRAG_TYPE };
}));
