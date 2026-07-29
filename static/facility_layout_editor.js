(function (root, factory) {
    'use strict';
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityLayout = api;
}(typeof window !== 'undefined'
    ? window
    : (typeof self !== 'undefined' ? self : null), function (root) {
    'use strict';

    const API_VERSION = 1;
    const DEFAULT_VIEW_PADDING = 24;
    const DEFAULT_FALLBACK_FOOTPRINT = Object.freeze([
        Object.freeze({ x: -0.6, z: -0.4 }),
        Object.freeze({ x: 0.6, z: -0.4 }),
        Object.freeze({ x: 0.6, z: 0.4 }),
        Object.freeze({ x: -0.6, z: 0.4 }),
    ]);

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function finite(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function finiteOr(value, fallback) {
        return finite(value) ? value : fallback;
    }

    function assertLayout(layout) {
        if (!layout || typeof layout !== 'object' || Array.isArray(layout)) {
            throw new TypeError('facility layout must be an object');
        }
        if (layout.schemaVersion !== 1) {
            throw new Error('unsupported facility layout schema version');
        }
        ['zones', 'placements', 'routes'].forEach(function (key) {
            if (!Array.isArray(layout[key])) {
                throw new TypeError('facility layout ' + key + ' must be an array');
            }
        });
        const placementIds = new Set();
        layout.placements.forEach(function (placement) {
            const placementId = placement && placement.placementId;
            if (typeof placementId !== 'string' || !placementId) {
                throw new TypeError('every placement requires a stable placementId');
            }
            if (placementIds.has(placementId)) {
                throw new Error('duplicate placementId: ' + placementId);
            }
            placementIds.add(placementId);
        });
        return layout;
    }

    function point(value) {
        if (!value || !finite(value.x) || !finite(value.z)) return null;
        return { x: value.x, z: value.z };
    }

    function normalizePointList(value) {
        if (!Array.isArray(value) || value.length < 3) return null;
        const result = value.map(point);
        return result.every(Boolean) ? result : null;
    }

    function rectangleFromSize(width, depth) {
        const safeWidth = finite(width) && width > 0 ? width : 1.2;
        const safeDepth = finite(depth) && depth > 0 ? depth : 0.8;
        return [
            { x: -safeWidth / 2, z: -safeDepth / 2 },
            { x: safeWidth / 2, z: -safeDepth / 2 },
            { x: safeWidth / 2, z: safeDepth / 2 },
            { x: -safeWidth / 2, z: safeDepth / 2 },
        ];
    }

    function footprintFromValue(value) {
        if (!value) return null;
        const direct = normalizePointList(value);
        if (direct) return direct;
        if (typeof value !== 'object' || Array.isArray(value)) return null;

        const named = normalizePointList(value.footprint)
            || normalizePointList(value.footprintPolygon)
            || normalizePointList(value.points);
        if (named) return named;

        const polygons = value.footprintPolygons
            || (value.geometry && value.geometry.footprintPolygons);
        if (Array.isArray(polygons) && polygons.length) {
            const polygon = normalizePointList(polygons[0]);
            if (polygon) return polygon;
        }

        if (finite(value.width) || finite(value.depth)) {
            return rectangleFromSize(value.width, value.depth);
        }
        if (value.size && (finite(value.size.x) || finite(value.size.z))) {
            return rectangleFromSize(value.size.x, value.size.z);
        }
        if (value.min && value.max
                && finite(value.min.x) && finite(value.max.x)
                && finite(value.min.z) && finite(value.max.z)
                && value.max.x > value.min.x && value.max.z > value.min.z) {
            return [
                { x: value.min.x, z: value.min.z },
                { x: value.max.x, z: value.min.z },
                { x: value.max.x, z: value.max.z },
                { x: value.min.x, z: value.max.z },
            ];
        }
        return null;
    }

    function resolveLocalFootprint(placement, options) {
        const resolver = options && options.resolveAssetBounds;
        if (typeof resolver === 'function') {
            const resolved = footprintFromValue(resolver(placement));
            if (resolved) return resolved;
        }

        const maps = options && [
            options.assetFootprints,
            options.assetBounds,
            options.assetBoundsByAssetId,
        ];
        if (maps) {
            for (let index = 0; index < maps.length; index += 1) {
                const map = maps[index];
                if (!map || typeof map !== 'object') continue;
                const value = map[placement.assetDefinitionRevision]
                    || map[placement.assetId];
                const resolved = footprintFromValue(value);
                if (resolved) return resolved;
            }
        }

        const embedded = footprintFromValue(placement.footprint)
            || footprintFromValue(placement.bounds)
            || footprintFromValue(placement.metadata);
        if (embedded) return embedded;

        const fallback = footprintFromValue(options && options.fallbackFootprint);
        return fallback || DEFAULT_FALLBACK_FOOTPRINT.map(point);
    }

    function rotatePointByQuaternion(value, quaternion) {
        const q = quaternion || {};
        const qx = finiteOr(q.x, 0);
        const qy = finiteOr(q.y, 0);
        const qz = finiteOr(q.z, 0);
        const qw = finiteOr(q.w, 1);
        const vx = value.x;
        const vy = 0;
        const vz = value.z;

        const ix = qw * vx + qy * vz - qz * vy;
        const iy = qw * vy + qz * vx - qx * vz;
        const iz = qw * vz + qx * vy - qy * vx;
        const iw = -qx * vx - qy * vy - qz * vz;

        return {
            x: ix * qw + iw * -qx + iy * -qz - iz * -qy,
            z: iz * qw + iw * -qz + ix * -qy - iy * -qx,
        };
    }

    function placementFootprint(placement, options) {
        const transform = placement && placement.transform || {};
        const position = transform.position || {};
        const origin = {
            x: finiteOr(position.x, 0),
            z: finiteOr(position.z, 0),
        };
        return resolveLocalFootprint(placement || {}, options || {}).map(function (local) {
            const rotated = rotatePointByQuaternion(local, transform.quaternion);
            return {
                x: origin.x + rotated.x,
                z: origin.z + rotated.z,
            };
        });
    }

    function collectTopPlanGeometry(layout, options) {
        assertLayout(layout);
        const geometry = {
            zones: [],
            routes: [],
            placements: [],
        };
        layout.zones.forEach(function (zone) {
            const polygon = normalizePointList(zone && zone.boundary);
            if (!polygon) return;
            geometry.zones.push({
                zoneId: zone.zoneId,
                zoneType: zone.zoneType,
                label: zone.label,
                points: polygon,
            });
        });
        layout.routes.forEach(function (route) {
            const points = Array.isArray(route && route.centerline)
                ? route.centerline.map(point).filter(Boolean)
                : [];
            if (points.length < 2) return;
            geometry.routes.push({
                routeId: route.routeId,
                routeKind: route.routeKind,
                corridorWidth: finiteOr(route.corridorWidth, 0),
                points: points,
            });
        });
        layout.placements.forEach(function (placement) {
            geometry.placements.push({
                placementId: placement.placementId,
                assetId: placement.assetId,
                positionMode: placement.positionMode,
                label: placement.metadata && (
                    placement.metadata.instanceLabel || placement.metadata.label
                ) || placement.assetId || placement.placementId,
                points: placementFootprint(placement, options),
            });
        });
        return geometry;
    }

    function collectTopPlanBounds(layout, options) {
        const geometry = collectTopPlanGeometry(layout, options);
        let minX = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxZ = -Infinity;
        function include(value) {
            minX = Math.min(minX, value.x);
            minZ = Math.min(minZ, value.z);
            maxX = Math.max(maxX, value.x);
            maxZ = Math.max(maxZ, value.z);
        }
        geometry.zones.forEach(function (zone) { zone.points.forEach(include); });
        geometry.routes.forEach(function (route) {
            const half = route.corridorWidth / 2;
            route.points.forEach(function (value) {
                include({ x: value.x - half, z: value.z - half });
                include({ x: value.x + half, z: value.z + half });
            });
        });
        geometry.placements.forEach(function (placement) {
            placement.points.forEach(include);
        });
        if (!finite(minX)) {
            minX = -1;
            minZ = -1;
            maxX = 1;
            maxZ = 1;
        }
        if (maxX === minX) {
            minX -= 0.5;
            maxX += 0.5;
        }
        if (maxZ === minZ) {
            minZ -= 0.5;
            maxZ += 0.5;
        }
        return { minX: minX, minZ: minZ, maxX: maxX, maxZ: maxZ };
    }

    function createTopPlanProjection(bounds, viewport, padding) {
        const width = Math.max(1, finiteOr(viewport && viewport.width, 1));
        const height = Math.max(1, finiteOr(viewport && viewport.height, 1));
        const requestedPadding = Math.max(
            0,
            finiteOr(padding, DEFAULT_VIEW_PADDING)
        );
        const safePadding = Math.min(
            requestedPadding,
            Math.max(0, Math.min(width, height) / 2 - 0.5)
        );
        const spanX = Math.max(1e-9, bounds.maxX - bounds.minX);
        const spanZ = Math.max(1e-9, bounds.maxZ - bounds.minZ);
        const availableWidth = Math.max(1, width - safePadding * 2);
        const availableHeight = Math.max(1, height - safePadding * 2);
        const scale = Math.min(availableWidth / spanX, availableHeight / spanZ);
        const renderedWidth = spanX * scale;
        const renderedHeight = spanZ * scale;
        return Object.freeze({
            width: width,
            height: height,
            padding: safePadding,
            scale: scale,
            offsetX: (width - renderedWidth) / 2,
            offsetY: (height - renderedHeight) / 2,
            minX: bounds.minX,
            minZ: bounds.minZ,
            maxX: bounds.maxX,
            maxZ: bounds.maxZ,
        });
    }

    function projectTopPlanPoint(value, projection) {
        return {
            x: projection.offsetX + (value.x - projection.minX) * projection.scale,
            y: projection.offsetY + (projection.maxZ - value.z) * projection.scale,
        };
    }

    function unprojectTopPlanPoint(value, projection) {
        return {
            x: projection.minX + (value.x - projection.offsetX) / projection.scale,
            z: projection.maxZ - (value.y - projection.offsetY) / projection.scale,
        };
    }

    function svgElement(documentRef, name) {
        return documentRef.createElementNS('http://www.w3.org/2000/svg', name);
    }

    function setAttributes(element, attributes) {
        Object.keys(attributes).forEach(function (key) {
            element.setAttribute(key, String(attributes[key]));
        });
        return element;
    }

    function pointString(points, projection) {
        return points.map(function (value) {
            const projected = projectTopPlanPoint(value, projection);
            return projected.x + ',' + projected.y;
        }).join(' ');
    }

    function removeChildren(element) {
        while (element.firstChild) element.removeChild(element.firstChild);
    }

    function targetPlacementId(target, boundary) {
        let cursor = target;
        while (cursor && cursor !== boundary) {
            if (typeof cursor.getAttribute === 'function') {
                const placementId = cursor.getAttribute('data-placement-id');
                if (placementId) return placementId;
            }
            cursor = cursor.parentNode;
        }
        return null;
    }

    function TopPlanAdapter(host, options) {
        if (!(this instanceof TopPlanAdapter)) {
            return new TopPlanAdapter(host, options);
        }
        if (!host || typeof host.appendChild !== 'function') {
            throw new TypeError('top-plan host must be a DOM element');
        }
        this.options = options || {};
        this.host = host;
        this.document = this.options.document || host.ownerDocument
            || (root && root.document);
        if (!this.document || typeof this.document.createElementNS !== 'function') {
            throw new Error('top-plan adapter requires SVG DOM support');
        }
        this.id = String(this.options.id || 'top-plan');
        this.type = 'top-plan';
        this.layout = null;
        this.geometry = null;
        this.projection = null;
        this.selection = null;
        this.selectionHandler = null;
        this.renderCount = 0;
        this.observerCount = 0;
        this.disposed = false;

        this.svg = svgElement(this.document, 'svg');
        setAttributes(this.svg, {
            'aria-label': this.options.ariaLabel || 'Facility top plan',
            role: 'img',
            width: '100%',
            height: '100%',
            preserveAspectRatio: 'none',
            'data-facility-layout-view': this.id,
        });
        this._handlePick = this._handlePick.bind(this);
        this.svg.addEventListener('click', this._handlePick);
        this.host.appendChild(this.svg);

        const ResizeObserverCtor = this.options.ResizeObserver
            || (root && root.ResizeObserver);
        if (typeof ResizeObserverCtor === 'function') {
            this.resizeObserver = new ResizeObserverCtor(function () {
                if (!this.disposed) this.fit();
            }.bind(this));
            this.resizeObserver.observe(this.host);
            this.observerCount = 1;
        } else {
            this.resizeObserver = null;
        }
    }

    TopPlanAdapter.prototype._measure = function () {
        if (typeof this.options.getSize === 'function') {
            const size = this.options.getSize(this.host) || {};
            return {
                width: Math.max(1, finiteOr(size.width, 1)),
                height: Math.max(1, finiteOr(size.height, 1)),
            };
        }
        return {
            width: Math.max(
                1,
                finiteOr(this.host.clientWidth, finiteOr(this.options.width, 1))
            ),
            height: Math.max(
                1,
                finiteOr(this.host.clientHeight, finiteOr(this.options.height, 1))
            ),
        };
    };

    TopPlanAdapter.prototype._render = function () {
        if (this.disposed || !this.svg) return;
        const size = this._measure();
        setAttributes(this.svg, {
            viewBox: '0 0 ' + size.width + ' ' + size.height,
        });
        removeChildren(this.svg);
        this.renderCount += 1;
        if (!this.layout) return;

        this.geometry = collectTopPlanGeometry(this.layout, this.options);
        if (!this.projection
                || this.projection.width !== size.width
                || this.projection.height !== size.height) {
            this.projection = createTopPlanProjection(
                collectTopPlanBounds(this.layout, this.options),
                size,
                this.options.padding
            );
        }

        const zoneLayer = svgElement(this.document, 'g');
        zoneLayer.setAttribute('data-layer', 'zones');
        this.geometry.zones.forEach(function (zone) {
            const polygon = svgElement(this.document, 'polygon');
            setAttributes(polygon, {
                points: pointString(zone.points, this.projection),
                fill: '#dcecf3',
                'fill-opacity': '0.38',
                stroke: '#4d7c8a',
                'stroke-width': '1.5',
                'vector-effect': 'non-scaling-stroke',
                'data-zone-id': zone.zoneId,
            });
            zoneLayer.appendChild(polygon);
        }, this);
        this.svg.appendChild(zoneLayer);

        const routeLayer = svgElement(this.document, 'g');
        routeLayer.setAttribute('data-layer', 'routes');
        this.geometry.routes.forEach(function (route) {
            const polyline = svgElement(this.document, 'polyline');
            const routeColor = route.routeKind === 'forklift'
                ? '#d97706'
                : (route.routeKind === 'operator' ? '#2563eb' : '#5b6472');
            setAttributes(polyline, {
                points: pointString(route.points, this.projection),
                fill: 'none',
                stroke: routeColor,
                'stroke-width': Math.max(
                    2,
                    route.corridorWidth * this.projection.scale
                ),
                'stroke-opacity': '0.58',
                'stroke-linejoin': 'round',
                'stroke-linecap': 'round',
                'data-route-id': route.routeId,
            });
            routeLayer.appendChild(polyline);
        }, this);
        this.svg.appendChild(routeLayer);

        const placementLayer = svgElement(this.document, 'g');
        placementLayer.setAttribute('data-layer', 'placements');
        this.geometry.placements.forEach(function (placement) {
            const selected = placement.placementId === this.selection;
            const polygon = svgElement(this.document, 'polygon');
            setAttributes(polygon, {
                points: pointString(placement.points, this.projection),
                fill: selected ? '#bfe3ff' : '#e8edf2',
                stroke: selected ? '#0878d1' : '#526273',
                'stroke-width': selected ? '3' : '1.5',
                'vector-effect': 'non-scaling-stroke',
                tabindex: '0',
                role: 'button',
                'aria-label': placement.label,
                'aria-selected': selected ? 'true' : 'false',
                'data-placement-id': placement.placementId,
                'data-asset-id': placement.assetId || '',
            });
            placementLayer.appendChild(polygon);
        }, this);
        this.svg.appendChild(placementLayer);
    };

    TopPlanAdapter.prototype._handlePick = function (event) {
        const placementId = targetPlacementId(event && event.target, this.svg);
        if (placementId) this.pick(placementId);
    };

    TopPlanAdapter.prototype.setSelectionHandler = function (handler) {
        this.selectionHandler = typeof handler === 'function' ? handler : null;
    };

    TopPlanAdapter.prototype.setLayout = function (layout) {
        if (this.disposed) return false;
        this.layout = layout ? clone(assertLayout(layout)) : null;
        if (this.selection && this.layout && !this.layout.placements.some(
            function (placement) { return placement.placementId === this.selection; },
            this
        )) {
            this.selection = null;
        }
        this.projection = null;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.setSelection = function (placementId) {
        if (this.disposed) return false;
        const next = placementId || null;
        if (this.selection === next) return true;
        this.selection = next;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.pick = function (placementId) {
        if (this.disposed || !this.layout) return false;
        const exists = this.layout.placements.some(function (placement) {
            return placement.placementId === placementId;
        });
        if (!exists) return false;
        if (this.selectionHandler) this.selectionHandler(placementId, this);
        else this.setSelection(placementId);
        return true;
    };

    TopPlanAdapter.prototype.fit = function () {
        if (this.disposed || !this.layout) return null;
        this.projection = createTopPlanProjection(
            collectTopPlanBounds(this.layout, this.options),
            this._measure(),
            this.options.padding
        );
        this._render();
        return clone(this.projection);
    };

    TopPlanAdapter.prototype.getDiagnostics = function () {
        return {
            id: this.id,
            type: this.type,
            mounted: !this.disposed && !!this.svg && this.svg.parentNode === this.host,
            observerCount: this.observerCount,
            renderCount: this.renderCount,
            selection: this.selection,
            placementIds: this.layout
                ? this.layout.placements.map(function (placement) {
                    return placement.placementId;
                })
                : [],
        };
    };

    TopPlanAdapter.prototype.dispose = function () {
        if (this.disposed) return;
        this.disposed = true;
        if (this.resizeObserver) this.resizeObserver.disconnect();
        this.resizeObserver = null;
        this.observerCount = 0;
        if (this.svg) {
            this.svg.removeEventListener('click', this._handlePick);
            if (this.svg.parentNode) this.svg.parentNode.removeChild(this.svg);
        }
        this.selectionHandler = null;
        this.layout = null;
        this.geometry = null;
        this.projection = null;
    };

    function parseControllerArguments(layoutOrOptions, maybeOptions) {
        if (layoutOrOptions && layoutOrOptions.schemaVersion === 1) {
            return {
                layout: layoutOrOptions,
                options: maybeOptions || {},
            };
        }
        const options = layoutOrOptions || {};
        return {
            layout: options.layout || null,
            options: options,
        };
    }

    function FacilityLayoutEditorController(layoutOrOptions, maybeOptions) {
        if (!(this instanceof FacilityLayoutEditorController)) {
            return new FacilityLayoutEditorController(layoutOrOptions, maybeOptions);
        }
        const parsed = parseControllerArguments(layoutOrOptions, maybeOptions);
        this.layout = null;
        this.assetCatalog = clone(parsed.options.assetCatalog || []);
        this.selection = null;
        this.views = [];
        this.pendingViewUpdates = [];
        this.viewUpdateGeneration = 0;
        this.disposed = false;
        const adapters = parsed.options.adapters || parsed.options.views || [];
        if (!Array.isArray(adapters)) {
            throw new TypeError('facility layout adapters must be an array');
        }
        adapters.forEach(this._attachView.bind(this));
        if (parsed.layout) this.setLayout(parsed.layout);
    }

    FacilityLayoutEditorController.prototype._assertActive = function () {
        if (this.disposed) throw new Error('facility layout editor is disposed');
    };

    FacilityLayoutEditorController.prototype._attachView = function (adapter) {
        if (!adapter || typeof adapter !== 'object') {
            throw new TypeError('facility layout adapter must be an object');
        }
        const handler = function (placementId) {
            if (!this.disposed) this.select(placementId);
        }.bind(this);
        let detach = null;
        if (typeof adapter.setSelectionHandler === 'function') {
            adapter.setSelectionHandler(handler);
            detach = function () { adapter.setSelectionHandler(null); };
        } else if (typeof adapter.subscribeSelection === 'function') {
            detach = adapter.subscribeSelection(handler);
        }
        this.views.push({
            adapter: adapter,
            detach: typeof detach === 'function' ? detach : null,
        });
    };

    FacilityLayoutEditorController.prototype._placementExists = function (placementId) {
        return !!this.layout && this.layout.placements.some(function (placement) {
            return placement.placementId === placementId;
        });
    };

    FacilityLayoutEditorController.prototype._notifyLayout = function () {
        const generation = this.viewUpdateGeneration + 1;
        this.viewUpdateGeneration = generation;
        const pending = [];
        this.views.forEach(function (entry) {
            if (typeof entry.adapter.setLayout === 'function') {
                entry.adapter.setLayout(clone(this.layout));
            } else if (typeof entry.adapter.setScene === 'function') {
                const result = entry.adapter.setScene({
                    layout: clone(this.layout),
                    assetCatalog: clone(this.assetCatalog),
                });
                if (result && typeof result.then === 'function') {
                    pending.push(Promise.resolve(result));
                }
            }
        }, this);
        this.pendingViewUpdates = pending;
        if (pending.length) {
            Promise.allSettled(pending).then(function () {
                if (!this.disposed
                        && this.viewUpdateGeneration === generation) {
                    this.pendingViewUpdates = [];
                }
            }.bind(this));
        }
    };

    FacilityLayoutEditorController.prototype._notifySelection = function () {
        this.views.forEach(function (entry) {
            if (typeof entry.adapter.setSelection === 'function') {
                entry.adapter.setSelection(this.selection);
            }
        }, this);
    };

    FacilityLayoutEditorController.prototype.setLayout = function (layout) {
        this._assertActive();
        this.layout = clone(assertLayout(layout));
        if (this.selection && !this._placementExists(this.selection)) {
            this.selection = null;
        }
        this._notifyLayout();
        this._notifySelection();
        return this.getState();
    };

    FacilityLayoutEditorController.prototype.setAssetCatalog = function (catalog) {
        this._assertActive();
        this.assetCatalog = clone(catalog || []);
        if (this.layout) this._notifyLayout();
        return this.getState();
    };

    FacilityLayoutEditorController.prototype.ready = function () {
        this._assertActive();
        const generation = this.viewUpdateGeneration;
        return Promise.all(this.pendingViewUpdates.slice()).then(function () {
            if (!this.disposed && this.viewUpdateGeneration === generation) {
                this.pendingViewUpdates = [];
            }
            return this.getState();
        }.bind(this));
    };

    FacilityLayoutEditorController.prototype.select = function (placementId) {
        this._assertActive();
        if (typeof placementId !== 'string' || !this._placementExists(placementId)) {
            return false;
        }
        if (this.selection === placementId) return true;
        this.selection = placementId;
        this._notifySelection();
        return true;
    };

    FacilityLayoutEditorController.prototype.clearSelection = function () {
        this._assertActive();
        if (this.selection === null) return false;
        this.selection = null;
        this._notifySelection();
        return true;
    };

    FacilityLayoutEditorController.prototype.fit = function () {
        this._assertActive();
        const results = [];
        this.views.forEach(function (entry) {
            if (typeof entry.adapter.fit === 'function') {
                results.push(entry.adapter.fit());
            }
        });
        return results;
    };

    FacilityLayoutEditorController.prototype.getState = function () {
        const viewDiagnostics = this.views.map(function (entry, index) {
            const adapter = entry.adapter;
            const diagnostics = typeof adapter.getDiagnostics === 'function'
                ? adapter.getDiagnostics()
                : {};
            return Object.assign({
                id: String(adapter.id || adapter.viewId || ('view-' + index)),
                type: String(adapter.type || 'view'),
                mounted: !this.disposed,
                observerCount: 0,
                renderCount: 0,
                selection: this.selection,
            }, diagnostics);
        }, this);
        const observerCount = viewDiagnostics.reduce(function (total, item) {
            return total + finiteOr(item.observerCount, 0);
        }, 0);
        const renderCount = viewDiagnostics.reduce(function (total, item) {
            return total + finiteOr(item.renderCount, 0);
        }, 0);
        return {
            apiVersion: API_VERSION,
            disposed: this.disposed,
            layout: clone(this.layout),
            layoutId: this.layout && this.layout.layoutId || null,
            selectedPlacementId: this.selection,
            selection: this.selection
                ? { kind: 'placement', placementId: this.selection }
                : null,
            diagnostics: {
                mountedViews: viewDiagnostics.filter(function (item) {
                    return item.mounted;
                }).length,
                pendingViewUpdates: this.pendingViewUpdates.length,
                observerCount: observerCount,
                renderCount: renderCount,
                selection: this.selection,
                views: viewDiagnostics,
            },
        };
    };

    FacilityLayoutEditorController.prototype.dispose = function () {
        if (this.disposed) return;
        this.views.forEach(function (entry) {
            if (entry.detach) entry.detach();
            if (typeof entry.adapter.dispose === 'function') {
                entry.adapter.dispose();
            }
        });
        this.views = [];
        this.pendingViewUpdates = [];
        this.viewUpdateGeneration += 1;
        this.assetCatalog = [];
        this.selection = null;
        this.disposed = true;
    };

    function createEditor(layoutOrOptions, maybeOptions) {
        return new FacilityLayoutEditorController(layoutOrOptions, maybeOptions);
    }

    function createTopPlanAdapter(host, options) {
        return new TopPlanAdapter(host, options);
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        DEFAULT_FALLBACK_FOOTPRINT: DEFAULT_FALLBACK_FOOTPRINT,
        FacilityLayoutEditorController: FacilityLayoutEditorController,
        TopPlanAdapter: TopPlanAdapter,
        createEditor: createEditor,
        createTopPlanAdapter: createTopPlanAdapter,
        collectTopPlanBounds: collectTopPlanBounds,
        collectTopPlanGeometry: collectTopPlanGeometry,
        createTopPlanProjection: createTopPlanProjection,
        placementFootprint: placementFootprint,
        projectTopPlanPoint: projectTopPlanPoint,
        unprojectTopPlanPoint: unprojectTopPlanPoint,
    });
}));
