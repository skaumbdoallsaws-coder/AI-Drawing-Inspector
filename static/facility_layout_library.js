(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityLibrary = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    // Appearance, scene and decal libraries bundled under /static/facility_library.
    // Nothing here touches the network beyond those local files, so opening a
    // project never depends on a third-party service. Appearances are visual only.

    const BASE_URL = '/static/facility_library/';
    const OVERRIDE_FIELDS = Object.freeze(['color', 'roughness', 'metalness', 'opacity', 'textureStrength',
        'sizeMeters', 'rotationDegrees', 'offsetMeters', 'mapping', 'grain', 'pattern', 'periodSeconds']);
    const PREFERENCES_KEY = 'inspectorpro.facilityLibrary.v1';
    const MAX_RECENTS = 12;
    const clone = value => JSON.parse(JSON.stringify(value));

    function absolute(baseUrl, path) {
        return path ? baseUrl + String(path).replace(/^\/+/, '') : null;
    }

    function indexLibrary(documents, baseUrl) {
        const base = baseUrl || BASE_URL;
        const appearanceDoc = documents.appearances, sceneDoc = documents.scenes, decalDoc = documents.decals;
        [appearanceDoc, sceneDoc, decalDoc].forEach(function (doc) {
            if (!doc || doc.schemaVersion !== 1) throw new Error('Unsupported facility library manifest');
        });
        const textureSets = new Map(appearanceDoc.textureSets.map(function (row) {
            const maps = {};
            Object.keys(row.maps || {}).forEach(function (kind) { maps[kind] = absolute(base, row.maps[kind]); });
            return [row.textureSetId, Object.assign(clone(row), { maps: maps })];
        }));
        const appearances = new Map(appearanceDoc.appearances.map(function (row) {
            return [row.appearanceId, Object.assign(clone(row), { thumbnailUrl: absolute(base, row.thumbnail) })];
        }));
        const environments = new Map(sceneDoc.environments.map(function (row) {
            return [row.environmentId, Object.assign(clone(row), { url: absolute(base, row.file) })];
        }));
        const scenes = new Map(sceneDoc.scenes.map(function (row) {
            return [row.sceneId, Object.assign(clone(row), { thumbnailUrl: absolute(base, row.thumbnail) })];
        }));
        const decals = new Map(decalDoc.decals.map(function (row) {
            return [row.decalId, Object.assign(clone(row), { url: absolute(base, row.file) })];
        }));
        return {
            libraryVersion: appearanceDoc.libraryVersion,
            baseUrl: base,
            categories: clone(appearanceDoc.categories),
            sceneGroups: clone(sceneDoc.groups),
            decalGroups: clone(decalDoc.groups),
            appearances: appearances,
            textureSets: textureSets,
            scenes: scenes,
            environments: environments,
            decals: decals,
        };
    }

    function createLibraryStore(options) {
        const settings = options || {};
        const baseUrl = settings.baseUrl || BASE_URL;
        const fetchImpl = settings.fetch || (typeof fetch === 'function' ? fetch.bind(globalThis) : null);
        // The manifests are cached hard; a new library version asks for them again.
        const query = settings.version ? '?v=' + encodeURIComponent(settings.version) : '';
        let library = settings.library || null;
        let pending = null;
        let failure = null;
        const listeners = new Set();
        function notify() {
            listeners.forEach(function (listener) {
                try { listener(library); } catch (_) { /* A listener must not break loading. */ }
            });
        }
        function load() {
            if (library) return Promise.resolve(library);
            if (pending) return pending;
            if (!fetchImpl) return Promise.reject(new Error('The facility library cannot be loaded here.'));
            pending = Promise.all(['appearances', 'scenes', 'decals'].map(function (name) {
                return fetchImpl(baseUrl + name + '.json' + query, { cache: 'force-cache' }).then(function (response) {
                    if (!response.ok) throw new Error('Facility library file ' + name + ' is unavailable.');
                    return response.json();
                });
            })).then(function (docs) {
                library = indexLibrary({ appearances: docs[0], scenes: docs[1], decals: docs[2] }, baseUrl);
                failure = null;
                notify();
                return library;
            }).catch(function (error) {
                failure = error;
                pending = null;
                throw error;
            });
            return pending;
        }
        return {
            load: load,
            get: function () { return library; },
            error: function () { return failure; },
            subscribe: function (listener) {
                listeners.add(listener);
                return function () { listeners.delete(listener); };
            },
        };
    }

    function customAppearances(layout) {
        const value = layout && layout.extensions && layout.extensions.facilityAppearances;
        return value && Array.isArray(value.custom) ? value.custom : [];
    }

    function pickOverrides(value) {
        const result = {};
        OVERRIDE_FIELDS.forEach(function (key) {
            if (value && value[key] !== undefined) result[key] = clone(value[key]);
        });
        return result;
    }

    function halfBrightness(color) {
        const value = parseInt(String(color).slice(1), 16);
        return '#' + [16, 8, 0].map(function (shift) {
            return ('0' + Math.round(((value >> shift) & 255) / 2).toString(16)).slice(-2);
        }).join('');
    }

    function mergeFinish(base, overrides, textureSet) {
        const result = clone(base);
        ['roughness', 'metalness', 'opacity'].forEach(function (key) {
            if (overrides[key] !== undefined) result[key] = overrides[key];
        });
        // On a light (a finish with an emission) the color recolors the light: the glow takes it, and the unlit lens
        // the same color at half brightness, so a blink's dark step or a switched-off lamp keeps its color.
        if (overrides.color !== undefined) {
            if (result.emission) {
                result.emission.color = overrides.color;
                result.color = halfBrightness(overrides.color);
            } else {
                result.color = overrides.color;
            }
        }
        // A light's pattern may be chosen per use, e.g. a red stack lamp that blinks.
        if (result.emission && overrides.pattern !== undefined) {
            delete result.emission.pattern;
            delete result.emission.periodSeconds;
            if (overrides.pattern !== 'steady') {
                result.emission.pattern = overrides.pattern;
                result.emission.periodSeconds = overrides.periodSeconds;
            }
        }
        if (result.texture && textureSet) {
            const texture = result.texture;
            if (overrides.sizeMeters !== undefined) texture.sizeMeters = overrides.sizeMeters;
            if (overrides.rotationDegrees !== undefined) texture.rotationDegrees = overrides.rotationDegrees;
            if (overrides.offsetMeters !== undefined) texture.offsetMeters = overrides.offsetMeters.slice();
            if (overrides.mapping !== undefined) texture.mapping = overrides.mapping;
            if (overrides.grain !== undefined) texture.grain = overrides.grain;
            if (overrides.textureStrength !== undefined) texture.strength = overrides.textureStrength;
            texture.offsetMeters = texture.offsetMeters || [0, 0];
            texture.maps = clone(textureSet.maps);
            texture.roughnessMean = textureSet.roughnessMean;
            texture.tileMeters = textureSet.tileMeters;
        } else {
            result.texture = null;
        }
        return result;
    }

    // Resolve a saved placement or part appearance into everything the renderer
    // needs. Precedence: library base, then the layout's custom finish, then the
    // per-use overrides. Returns null for the legacy plain-color form.
    function resolveAppearance(library, value, layout) {
        if (!library || !value || typeof value !== 'object' || !value.appearanceId) return null;
        let base = library.appearances.get(value.appearanceId);
        let label = base && base.label;
        let customOverrides = {};
        if (!base && /^custom-/.test(value.appearanceId)) {
            const custom = customAppearances(layout).find(function (row) {
                return row.appearanceId === value.appearanceId;
            });
            base = custom && library.appearances.get(custom.baseAppearanceId);
            customOverrides = custom ? pickOverrides(custom) : {};
            label = custom && custom.label;
        }
        if (!base) return { appearanceId: value.appearanceId, missing: true, label: value.appearanceId };
        const textureSet = base.texture ? library.textureSets.get(base.texture.textureSetId) : null;
        const merged = mergeFinish(mergeFinish(base, customOverrides, textureSet), pickOverrides(value), textureSet);
        merged.appearanceId = value.appearanceId;
        merged.baseAppearanceId = base.appearanceId;
        merged.label = label || base.label;
        merged.model = merged.model || 'standard';
        return merged;
    }

    function finishSignature(resolved, scale) {
        if (!resolved) return '';
        const texture = resolved.texture ? {
            set: resolved.texture.textureSetId, size: resolved.texture.sizeMeters, rotation: resolved.texture.rotationDegrees,
            offset: resolved.texture.offsetMeters, mapping: resolved.texture.mapping, grain: resolved.texture.grain,
            strength: resolved.texture.strength, scale: Number(scale || 1).toFixed(4),
        } : null;
        const emission = resolved.emission ? [resolved.emission.color, resolved.emission.intensity]
            .concat(resolved.emission.pattern ? [resolved.emission.pattern, resolved.emission.periodSeconds] : [])
            .concat(resolved.emission.beamAngleDegrees ? [resolved.emission.beamAngleDegrees] : []) : null;
        return JSON.stringify([resolved.appearanceId, resolved.missing === true, resolved.model, resolved.color,
            resolved.roughness, resolved.metalness, resolved.opacity, resolved.transmission || 0, resolved.ior || 0,
            resolved.thickness || 0, resolved.clearcoat || 0, resolved.clearcoatRoughness || 0, texture, emission]);
    }

    function layoutScene(layout) {
        const value = layout && layout.extensions && layout.extensions.facilityScene;
        return value && typeof value === 'object' ? value : null;
    }

    // Scene adjustments replace the matching preset values; an unknown or absent
    // scene is the Classic look, which preserves InspectorPro's original viewport.
    function resolveScene(library, value) {
        const saved = value && typeof value === 'object' ? value : null;
        const preset = library && saved && library.scenes.get(saved.sceneId)
            || library && library.scenes.get('classic')
            || { sceneId: 'classic', label: 'Classic', environment: null, environmentIntensity: 0, background: 'theme',
                ambient: 1.55, directional: 2, exposure: 1.22, shadows: false };
        const result = clone(preset);
        const adjustments = saved && saved.adjustments && typeof saved.adjustments === 'object' ? saved.adjustments : {};
        ['exposure', 'environmentIntensity', 'ambient', 'directional', 'background', 'shadows',
            'environmentRotationDegrees', 'lights', 'lightAreas', 'glowHalo'].forEach(function (key) {
            if (adjustments[key] !== undefined) result[key] = clone(adjustments[key]);
        });
        result.environmentRotationDegrees = result.environmentRotationDegrees || 0;
        // Lamps, beacons and signs glow unless the scene switches the lights off. lightAreas, when set, switches the
        // general lighting by area (docs/facility-lighting-plan.md, L7).
        result.lights = result.lights !== false;
        // The glow halo (L6) is off unless the scene turns it on; the view draws it only where there are pools.
        result.glowHalo = result.glowHalo === true;
        const environment = library && result.environment && result.environment !== 'room'
            ? library.environments.get(result.environment) : null;
        result.environmentUrl = environment ? environment.url : null;
        return result;
    }

    function words(text) {
        return String(text || '').toLowerCase().split(/\s+/).filter(Boolean);
    }

    function matches(row, query) {
        const terms = words(query);
        if (!terms.length) return true;
        const haystack = [row.label, row.description, row.category, row.group, row.code, row.appearanceId,
            row.sceneId, row.decalId].concat(row.tags || []).join(' ').toLowerCase();
        return terms.every(function (term) { return haystack.indexOf(term) >= 0; });
    }

    function appearanceRows(library, layout) {
        const rows = Array.from(library.appearances.values()).map(function (row) {
            return Object.assign({ kind: 'appearance', id: row.appearanceId }, row);
        });
        customAppearances(layout).forEach(function (custom) {
            const resolved = resolveAppearance(library, { appearanceId: custom.appearanceId }, layout);
            if (!resolved || resolved.missing) return;
            rows.push(Object.assign({}, resolved, { kind: 'appearance', id: custom.appearanceId, custom: true,
                label: custom.label, thumbnailUrl: library.appearances.get(custom.baseAppearanceId).thumbnailUrl,
                tags: ['custom'].concat(library.appearances.get(custom.baseAppearanceId).tags || []) }));
        });
        return rows;
    }

    // One query interface for the browser grid and for agents.
    function search(library, options) {
        if (!library) return [];
        const settings = options || {};
        const kind = settings.kind || 'appearance';
        let rows;
        if (kind === 'scene') {
            rows = Array.from(library.scenes.values()).map(function (row) {
                return Object.assign({ kind: 'scene', id: row.sceneId }, row);
            });
            if (settings.group) rows = rows.filter(function (row) { return row.group === settings.group; });
        } else if (kind === 'decal') {
            rows = Array.from(library.decals.values()).map(function (row) {
                return Object.assign({ kind: 'decal', id: row.decalId }, row);
            });
            if (settings.group) rows = rows.filter(function (row) { return row.group === settings.group; });
        } else {
            rows = appearanceRows(library, settings.layout);
            if (settings.category === 'custom') rows = rows.filter(function (row) { return row.custom; });
            else if (settings.category) rows = rows.filter(function (row) { return row.category === settings.category; });
        }
        return rows.filter(function (row) { return matches(row, settings.query); });
    }

    function findItem(library, kind, id, layout) {
        if (!library) return null;
        if (kind === 'scene') {
            const row = library.scenes.get(id);
            return row ? Object.assign({ kind: 'scene', id: id }, row) : null;
        }
        if (kind === 'decal') {
            const row = library.decals.get(id);
            return row ? Object.assign({ kind: 'decal', id: id }, row) : null;
        }
        return appearanceRows(library, layout).find(function (row) { return row.id === id; }) || null;
    }

    // Favorites and recents are per-viewer conveniences, so they live in local
    // storage and tolerate storage that is blocked or empty.
    function createPreferences(storage) {
        let cache = null;
        function read() {
            if (cache) return cache;
            let value = null;
            try { value = JSON.parse(storage && storage.getItem(PREFERENCES_KEY) || 'null'); } catch (_) { value = null; }
            cache = {
                favorites: Array.isArray(value && value.favorites) ? value.favorites.filter(isRef) : [],
                recents: Array.isArray(value && value.recents) ? value.recents.filter(isRef) : [],
            };
            return cache;
        }
        function isRef(item) {
            return item && typeof item === 'object' && ['appearance', 'scene', 'decal'].indexOf(item.kind) >= 0
                && typeof item.id === 'string' && item.id.length <= 80;
        }
        function write() {
            try { if (storage) storage.setItem(PREFERENCES_KEY, JSON.stringify(cache)); } catch (_) { /* Optional. */ }
        }
        function same(a, b) { return a.kind === b.kind && a.id === b.id; }
        return {
            favorites: function () { return read().favorites.slice(); },
            recents: function () { return read().recents.slice(); },
            isFavorite: function (kind, id) {
                return read().favorites.some(function (item) { return same(item, { kind: kind, id: id }); });
            },
            toggleFavorite: function (kind, id) {
                const state = read(), ref = { kind: kind, id: id };
                const index = state.favorites.findIndex(function (item) { return same(item, ref); });
                if (index >= 0) state.favorites.splice(index, 1);
                else state.favorites.unshift(ref);
                state.favorites = state.favorites.slice(0, 60);
                write();
                return index < 0;
            },
            pushRecent: function (kind, id) {
                const state = read(), ref = { kind: kind, id: id };
                state.recents = [ref].concat(state.recents.filter(function (item) { return !same(item, ref); }))
                    .slice(0, MAX_RECENTS);
                write();
            },
        };
    }

    // What the current layout uses, for the "In this layout" node: finishes on
    // whole objects and parts, the saved scene, and decals of both kinds.
    function layoutUsage(library, layout) {
        const appearances = new Map();
        const placements = layout && Array.isArray(layout.placements) ? layout.placements : [];
        function note(appearanceId, placementId, part) {
            if (!appearances.has(appearanceId)) appearances.set(appearanceId, { appearanceId: appearanceId, placementIds: [], partCount: 0 });
            const entry = appearances.get(appearanceId);
            if (part) entry.partCount += 1;
            if (entry.placementIds.indexOf(placementId) < 0) entry.placementIds.push(placementId);
        }
        let plainColors = 0;
        placements.forEach(function (placement) {
            const appearance = placement.appearance;
            if (appearance && appearance.appearanceId) note(appearance.appearanceId, placement.placementId, false);
            else if (appearance && appearance.color) plainColors += 1;
            const parts = placement.componentMaterials && placement.componentMaterials.overrides || [];
            parts.forEach(function (row) { if (row.appearanceId) note(row.appearanceId, placement.placementId, true); });
        });
        const rows = Array.from(appearances.values()).map(function (entry) {
            const item = findItem(library, 'appearance', entry.appearanceId, layout);
            return Object.assign(entry, { label: item ? item.label : entry.appearanceId, missing: !item });
        }).sort(function (a, b) { return a.label.localeCompare(b.label); });
        const extensions = layout && layout.extensions || {};
        const wallDecals = extensions.facilityDecals && Array.isArray(extensions.facilityDecals.artworks)
            ? extensions.facilityDecals.artworks.length : 0;
        const equipmentDecals = extensions.facilityEquipmentDecals && Array.isArray(extensions.facilityEquipmentDecals.decals)
            ? clone(extensions.facilityEquipmentDecals.decals) : [];
        const scene = layoutScene(layout);
        return {
            appearances: rows,
            plainColors: plainColors,
            scene: scene ? clone(scene) : null,
            sceneLabel: resolveScene(library, scene).label,
            wallDecals: wallDecals,
            equipmentDecals: equipmentDecals,
        };
    }

    return {
        BASE_URL: BASE_URL,
        OVERRIDE_FIELDS: OVERRIDE_FIELDS,
        indexLibrary: indexLibrary,
        createLibraryStore: createLibraryStore,
        customAppearances: customAppearances,
        resolveAppearance: resolveAppearance,
        finishSignature: finishSignature,
        layoutScene: layoutScene,
        resolveScene: resolveScene,
        search: search,
        findItem: findItem,
        createPreferences: createPreferences,
        layoutUsage: layoutUsage,
    };
}));
