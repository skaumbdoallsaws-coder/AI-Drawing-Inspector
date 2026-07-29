(function (root, factory) {
    'use strict';

    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityWorkspace = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const API_VERSION = 1;
    const ASSET_MIME = 'application/x-inspectorpro-facility-asset';
    const DEFAULT_GRID_SIZE = 0.5;
    const DEFAULT_DUPLICATE_OFFSET = Object.freeze({ x: 1, y: 0, z: 1 });
    const TOOL_MODES = Object.freeze(['select', 'pan', 'rectangle-zone', 'polygon-zone']);
    const VIEW_MODES = Object.freeze(['plan', '3d']);
    let dragSequence = 0;

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function cleanString(value, fallback) {
        return typeof value === 'string' && value.trim()
            ? value.trim()
            : fallback;
    }

    function boundedText(value, maximum) {
        const text = cleanString(value, '');
        const limit = maximum || 120;
        return text.length <= limit
            ? text
            : text.slice(0, Math.max(0, limit - 3)) + '...';
    }

    function candidateSafetyStatus(value) {
        return value === 'safe' || value === 'unsafe'
            ? value
            : 'unverified';
    }

    function candidateSafetyLabel(value) {
        const status = candidateSafetyStatus(value);
        if (status === 'safe') return 'Authoritatively validated';
        if (status === 'unsafe') return 'Invalid placement';
        return 'Engineering evidence incomplete';
    }

    function candidateFindingSummary(findings) {
        if (!Array.isArray(findings) || !findings.length) return '';
        const maximum = 2;
        const visible = findings.slice(0, maximum).map(function (finding) {
            if (typeof finding === 'string') return boundedText(finding, 100);
            if (!finding || typeof finding !== 'object') return '';
            return boundedText(
                finding.message || finding.label || finding.code,
                100
            );
        }).filter(Boolean);
        if (!visible.length) return '';
        const remaining = findings.length - visible.length;
        return 'Findings: ' + visible.join('; ')
            + (remaining > 0 ? '; +' + remaining + ' more' : '');
    }

    function candidateMetricSummary(metrics) {
        if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) {
            return '';
        }
        const preferred = [
            'errorCount',
            'unverifiedCount',
            'warningCount',
            'physicalCollisions',
            'clearanceConflicts',
            'distanceFromRequested',
        ];
        const keys = preferred.filter(function (key) {
            return Object.prototype.hasOwnProperty.call(metrics, key);
        }).concat(Object.keys(metrics).sort().filter(function (key) {
            return !preferred.includes(key);
        })).slice(0, 3);
        const values = keys.map(function (key) {
            const value = metrics[key];
            if (typeof value === 'number' && Number.isFinite(value)) {
                return key + ' ' + Number(value.toFixed(3));
            }
            if (typeof value === 'string' || typeof value === 'boolean') {
                return key + ' ' + boundedText(String(value), 40);
            }
            return '';
        }).filter(Boolean);
        return values.length ? 'Metrics: ' + values.join(', ') : '';
    }

    function candidateAssessment(candidate) {
        const source = candidate || {};
        const status = candidateSafetyStatus(source.safetyStatus);
        const details = [
            candidateFindingSummary(source.findings),
            candidateMetricSummary(source.metrics),
        ].filter(Boolean);
        return {
            status: status,
            label: candidateSafetyLabel(status),
            summary: details.join('. '),
        };
    }

    function assertObject(value, label) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new TypeError(label + ' must be an object');
        }
        return value;
    }

    function setAttributes(element, attributes) {
        Object.keys(attributes || {}).forEach(function (name) {
            const value = attributes[name];
            if (value === undefined || value === null || value === false) return;
            if (name === 'className') {
                element.className = String(value);
            } else if (name === 'textContent') {
                element.textContent = String(value);
            } else if (name === 'disabled') {
                element.disabled = Boolean(value);
                if (value) element.setAttribute('disabled', '');
                else element.removeAttribute('disabled');
            } else if (name === 'hidden') {
                element.hidden = Boolean(value);
            } else {
                element.setAttribute(name, value === true ? '' : String(value));
            }
        });
        return element;
    }

    function element(documentRef, tagName, attributes, text) {
        const node = documentRef.createElement(tagName);
        setAttributes(node, attributes);
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function clearElement(node) {
        while (node && node.firstChild) node.removeChild(node.firstChild);
    }

    function append(parent) {
        Array.prototype.slice.call(arguments, 1).forEach(function (child) {
            if (child) parent.appendChild(child);
        });
        return parent;
    }

    function normalizeQuarterTurns(turns) {
        const value = finite(turns, 0);
        if (!Number.isInteger(value)) {
            throw new TypeError('quarter turns must be an integer');
        }
        return ((value % 4) + 4) % 4;
    }

    function quarterTurnQuaternion(turns) {
        const normalized = normalizeQuarterTurns(turns === undefined ? 1 : turns);
        const angle = normalized * Math.PI / 2;
        return {
            x: 0,
            y: Math.sin(angle / 2),
            z: 0,
            w: Math.cos(angle / 2),
        };
    }

    function snapCoordinate(value, gridSize) {
        const number = finite(value, 0);
        const step = finite(gridSize, DEFAULT_GRID_SIZE);
        if (step <= 0) return number;
        const snapped = Math.round(number / step) * step;
        return Math.abs(snapped) < 1e-12 ? 0 : Number(snapped.toFixed(9));
    }

    function snapWorldPoint(value, gridSize) {
        assertObject(value, 'world point');
        return {
            x: snapCoordinate(value.x, gridSize),
            y: finite(value.y, 0),
            z: snapCoordinate(value.z, gridSize),
        };
    }

    function createAssetDragPayload(asset, dragSessionId) {
        const source = assertObject(asset, 'asset');
        const payload = {
            assetId: cleanString(source.assetId, ''),
            assetDefinitionRevision: cleanString(source.assetDefinitionRevision, ''),
            dragSessionId: cleanString(dragSessionId, ''),
        };
        if (!payload.assetId) throw new TypeError('assetId is required');
        if (!payload.assetDefinitionRevision) {
            throw new TypeError('assetDefinitionRevision is required');
        }
        if (!payload.dragSessionId) throw new TypeError('dragSessionId is required');
        return JSON.stringify(payload);
    }

    function dragPayloadText(value) {
        if (typeof value === 'string') return value;
        const transfer = value && (
            value.dataTransfer
            || (typeof value.getData === 'function' ? value : null)
        );
        if (!transfer || typeof transfer.getData !== 'function') return '';
        return transfer.getData(ASSET_MIME)
            || transfer.getData('application/json')
            || transfer.getData('text/plain')
            || '';
    }

    function parseAssetDragPayload(value) {
        const text = dragPayloadText(value);
        if (!text) return null;
        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (error) {
            return null;
        }
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
        const result = {
            assetId: cleanString(parsed.assetId, ''),
            assetDefinitionRevision: cleanString(
                parsed.assetDefinitionRevision,
                ''
            ),
            dragSessionId: cleanString(parsed.dragSessionId, ''),
        };
        return result.assetId && result.assetDefinitionRevision && result.dragSessionId
            ? result
            : null;
    }

    function catalogArray(catalog) {
        if (Array.isArray(catalog)) return catalog.slice();
        if (!catalog || typeof catalog !== 'object') return [];
        if (Array.isArray(catalog.entries)) return catalog.entries.slice();
        if (Array.isArray(catalog.assets)) return catalog.assets.slice();
        return Object.keys(catalog).sort().map(function (key) {
            const record = catalog[key];
            if (!record || typeof record !== 'object') return null;
            return record.assetId ? record : Object.assign({ assetId: key }, record);
        }).filter(Boolean);
    }

    function normalizeCatalog(catalog) {
        return catalogArray(catalog).map(function (record) {
            const definition = record.definition || record.assetDefinition || {};
            return {
                source: record,
                assetId: cleanString(record.assetId || definition.assetId, ''),
                assetDefinitionRevision: cleanString(
                    record.assetDefinitionRevision
                    || record.publishedAssetDefinitionRevision
                    || record.definitionRevision
                    || definition.assetDefinitionRevision,
                    ''
                ),
                label: cleanString(
                    record.displayName
                    || record.label
                    || record.name
                    || definition.displayName
                    || record.assetId,
                    'Unnamed asset'
                ),
                category: cleanString(
                    record.category
                    || record.assetClass
                    || record.assetType
                    || definition.category,
                    'Other'
                ),
                description: cleanString(
                    record.description || definition.description,
                    ''
                ),
            };
        }).filter(function (record) {
            return record.assetId && record.assetDefinitionRevision;
        }).sort(function (left, right) {
            return left.category.localeCompare(right.category)
                || left.label.localeCompare(right.label)
                || left.assetId.localeCompare(right.assetId);
        });
    }

    function zoneDimensions(zone) {
        const points = zone && Array.isArray(zone.boundary) ? zone.boundary : [];
        if (!points.length) return null;
        let minX = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxZ = -Infinity;
        points.forEach(function (point) {
            const x = finite(point && point.x, NaN);
            const z = finite(point && point.z, NaN);
            if (!Number.isFinite(x) || !Number.isFinite(z)) return;
            minX = Math.min(minX, x);
            maxX = Math.max(maxX, x);
            minZ = Math.min(minZ, z);
            maxZ = Math.max(maxZ, z);
        });
        if (!Number.isFinite(minX)) return null;
        return {
            width: maxX - minX,
            depth: maxZ - minZ,
            center: {
                x: (minX + maxX) / 2,
                y: finite(zone.floorElevation, 0),
                z: (minZ + maxZ) / 2,
            },
        };
    }

    function quaternionYawDegrees(value) {
        const q = value || {};
        const x = finite(q.x, 0);
        const y = finite(q.y, 0);
        const z = finite(q.z, 0);
        const w = finite(q.w, 1);
        const radians = Math.atan2(
            2 * (w * y + x * z),
            1 - 2 * (y * y + z * z)
        );
        let degrees = radians * 180 / Math.PI;
        if (degrees < 0) degrees += 360;
        return Number(degrees.toFixed(6));
    }

    function targetDataId(target, attribute, boundary) {
        let current = target;
        while (current && current !== boundary) {
            if (typeof current.getAttribute === 'function') {
                const value = current.getAttribute(attribute);
                if (value) return value;
            }
            current = current.parentNode;
        }
        return null;
    }

    function isTypingTarget(target) {
        const name = String(target && target.nodeName || '').toLowerCase();
        return name === 'input' || name === 'textarea' || name === 'select'
            || Boolean(target && target.isContentEditable);
    }

    function createDragSessionId() {
        dragSequence += 1;
        return 'facility-drag-' + Date.now().toString(36)
            + '-' + dragSequence.toString(36);
    }

    function selectionRecord(layout, selection) {
        if (!layout || !Array.isArray(selection) || selection.length !== 1) return null;
        const id = selection[0];
        const placement = layout.placements.find(function (item) {
            return item.placementId === id;
        });
        if (placement) return { kind: 'placement', value: placement };
        const zone = layout.zones.find(function (item) {
            return item.zoneId === id;
        });
        return zone ? { kind: 'zone', value: zone } : null;
    }

    function Workspace(inputOptions) {
        const options = assertObject(inputOptions || {}, 'workspace options');
        this.options = options;
        this.root = options.root;
        if (!this.root || !this.root.ownerDocument) {
            throw new TypeError('workspace root with ownerDocument is required');
        }
        this.document = this.root.ownerDocument;
        this.session = options.session;
        if (!this.session || typeof this.session.subscribe !== 'function'
                || typeof this.session.getState !== 'function') {
            throw new TypeError('FacilitySession instance is required');
        }
        this.layoutRuntime = options.layoutRuntime
            || (root && root.InspectorProFacilityLayout);
        if (!options.controller && (!this.layoutRuntime
                || typeof this.layoutRuntime.createEditor !== 'function'
                || typeof this.layoutRuntime.createTopPlanAdapter !== 'function')) {
            throw new TypeError('FacilityLayout runtime or controller is required');
        }
        this.assetCatalog = normalizeCatalog(options.assetCatalog || []);
        this.gridSize = finite(options.gridSize, DEFAULT_GRID_SIZE);
        if (this.gridSize <= 0) this.gridSize = DEFAULT_GRID_SIZE;
        this.eventToWorld = options.eventToWorld || options.worldPointFromPointer;
        this.marqueeResolver = typeof options.marqueeResolver === 'function'
            ? options.marqueeResolver : null;
        this.toolMode = 'select';
        this.viewMode = 'plan';
        this.state = this.session.getState();
        this.destroyed = false;
        this.listeners = [];
        this.pending = Promise.resolve();
        this.lastError = null;
        this.activeDrag = null;
        this.dragAdvisory = null;
        this.spatialAdvisor = options.spatialAdvisor || null;
        this.ownsSpatialAdvisor = options.ownsSpatialAdvisor === true;
        this.useAuthoritativePlacementCandidates =
            options.useAuthoritativePlacementCandidates === true;
        this.pointerGesture = null;
        this.pointerCaptureId = null;
        this.pointerFallbackCleanup = null;
        this.polygonPoints = [];
        this.suppressAdapterSelection = null;
        this.lastLayoutFingerprint = null;
        this.unsubscribe = null;
        this.marqueeCleanup = null;
        this.createdTopAdapter = false;
        this.createdThreeAdapter = false;
        this.ownsController = !options.controller;
        this._build();
        this._connectRendering();
        this._connectEvents();
        this.unsubscribe = this.session.subscribe(this._handleSessionState.bind(this));
        this._handleSessionState(this.state);
    }

    Workspace.prototype._listen = function (target, type, handler, options) {
        target.addEventListener(type, handler, options);
        this.listeners.push(function () {
            target.removeEventListener(type, handler, options);
        });
    };

    Workspace.prototype._button = function (command, label, keyHint) {
        const button = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-command',
            'data-command': command,
            'aria-label': label,
            title: keyHint ? label + ' (' + keyHint + ')' : label,
        });
        append(button,
            element(this.document, 'span', {
                className: 'ip-flw-command-icon',
                'aria-hidden': 'true',
            }, this.options.commandIcons && this.options.commandIcons[command]
                || label.charAt(0).toUpperCase()),
            element(this.document, 'span', {
                className: 'ip-flw-command-label',
            }, label)
        );
        return button;
    };

    Workspace.prototype._build = function () {
        clearElement(this.root);
        this.root.className = (
            (this.root.className ? this.root.className + ' ' : '')
            + 'ip-flw-root'
        ).trim();
        this.root.setAttribute('data-facility-workspace', '');
        this.root.setAttribute('aria-label', 'Facility layout workspace');

        this.toolbar = element(this.document, 'div', {
            className: 'ip-flw-toolbar',
            role: 'toolbar',
            'aria-label': 'Facility layout tools',
        });
        [
            ['select', 'Select', 'V'],
            ['pan', 'Pan', 'H'],
            ['rectangle-zone', 'Rectangle zone', ''],
            ['polygon-zone', 'Polygon zone', ''],
            ['rotate', 'Rotate 90', 'R'],
            ['duplicate', 'Duplicate', 'Ctrl+D'],
            ['delete', 'Delete', 'Delete'],
            ['lock', 'Lock', 'L'],
            ['undo', 'Undo', 'Ctrl+Z'],
            ['redo', 'Redo', 'Ctrl+Y'],
            ['fit', 'Fit', 'F'],
            ['save', 'Save', 'Ctrl+S'],
        ].forEach(function (spec) {
            this.toolbar.appendChild(this._button(spec[0], spec[1], spec[2]));
        }, this);

        this.assetPane = element(this.document, 'aside', {
            className: 'ip-flw-assets',
            'aria-label': 'Asset catalog',
        });
        const assetHeader = element(this.document, 'div', {
            className: 'ip-flw-pane-header',
        });
        assetHeader.appendChild(element(this.document, 'h2', {}, 'Assets'));
        const searchLabel = element(this.document, 'label', {
            className: 'ip-flw-search',
        });
        searchLabel.appendChild(element(this.document, 'span', {
            className: 'ip-flw-visually-hidden',
        }, 'Search assets'));
        this.assetSearch = element(this.document, 'input', {
            type: 'search',
            placeholder: 'Search assets',
            'aria-label': 'Search assets',
            autocomplete: 'off',
        });
        searchLabel.appendChild(this.assetSearch);
        assetHeader.appendChild(searchLabel);
        this.assetTree = element(this.document, 'div', {
            className: 'ip-flw-asset-tree',
            role: 'tree',
            'aria-label': 'Available facility assets',
        });
        append(this.assetPane, assetHeader, this.assetTree);

        this.viewportPane = element(this.document, 'main', {
            className: 'ip-flw-viewport-pane',
        });
        this.viewTabs = element(this.document, 'div', {
            className: 'ip-flw-view-tabs',
            role: 'tablist',
            'aria-label': 'Facility layout view',
        });
        this.planTab = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-view-tab',
            role: 'tab',
            'data-view': 'plan',
            'aria-controls': 'ip-flw-plan-view',
        }, 'Plan');
        this.threeTab = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-view-tab',
            role: 'tab',
            'data-view': '3d',
            'aria-controls': 'ip-flw-three-view',
        }, '3D');
        append(this.viewTabs, this.planTab, this.threeTab);

        this.viewportStack = element(this.document, 'div', {
            className: 'ip-flw-viewport-stack',
        });
        this.planView = element(this.document, 'div', {
            id: 'ip-flw-plan-view',
            className: 'ip-flw-view ip-flw-plan-view',
            role: 'tabpanel',
            'aria-label': 'Plan view',
            tabindex: '0',
        });
        this.threeView = element(this.document, 'div', {
            id: 'ip-flw-three-view',
            className: 'ip-flw-view ip-flw-three-view',
            role: 'tabpanel',
            'aria-label': '3D view',
            tabindex: '0',
        });
        this.ghostOverlay = element(this.document, 'div', {
            className: 'ip-flw-ghost',
            hidden: true,
            'aria-hidden': 'true',
        });
        this.advisoryLiveRegion = element(this.document, 'div', {
            className: 'ip-flw-visually-hidden',
            role: 'status',
            'aria-live': 'polite',
            'aria-atomic': 'true',
        });
        this.gestureOverlay = element(this.document, 'div', {
            className: 'ip-flw-gesture-overlay',
            hidden: true,
            'aria-hidden': 'true',
        });
        append(this.viewportStack,
            this.planView,
            this.threeView,
            this.ghostOverlay,
            this.advisoryLiveRegion,
            this.gestureOverlay
        );
        this.validationNotice = element(this.document, 'div', {
            className: 'ip-flw-validation-notice',
            role: 'note',
        });
        this.validationNotice.appendChild(element(this.document, 'span', {
            className: 'ip-flw-advisory-authority',
        }, 'Browser overlap feedback is advisory. The server validates every accepted placement.'));
        this.candidateControls = element(this.document, 'div', {
            className: 'ip-flw-view-tabs ip-flw-candidate-controls',
            role: 'group',
            'aria-label': 'Authoritative placement alternatives',
            hidden: true,
        });
        this.candidateSummary = element(this.document, 'span', {
            className: 'ip-flw-candidate-summary',
            role: 'status',
            'aria-live': 'polite',
            'aria-atomic': 'true',
        });
        append(this.candidateControls,
            this.candidateSummary,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'previous',
                'aria-label': 'Previous placement alternative',
                title: 'Previous placement alternative',
            }, 'Previous'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'next',
                'aria-label': 'Next placement alternative',
                title: 'Next placement alternative',
            }, 'Next'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'accept',
                'aria-label': 'Accept placement alternative',
                title: 'Accept placement alternative',
            }, 'Accept'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'dismiss',
                'aria-label': 'Dismiss placement alternatives',
                title: 'Dismiss placement alternatives',
            }, 'Dismiss')
        );
        this.validationNotice.appendChild(this.candidateControls);
        append(this.viewportPane,
            this.viewTabs,
            this.viewportStack,
            this.validationNotice
        );

        this.propertiesPane = element(this.document, 'aside', {
            className: 'ip-flw-properties',
            'aria-label': 'Selection properties',
        });
        const propertyHeader = element(this.document, 'div', {
            className: 'ip-flw-pane-header',
        });
        propertyHeader.appendChild(element(this.document, 'h2', {}, 'Properties'));
        this.propertiesBody = element(this.document, 'div', {
            className: 'ip-flw-properties-body',
        });
        append(this.propertiesPane, propertyHeader, this.propertiesBody);

        this.statusBar = element(this.document, 'div', {
            className: 'ip-flw-statusbar',
        });
        this.statusText = element(this.document, 'div', {
            className: 'ip-flw-status',
            role: 'status',
            'aria-live': 'polite',
        });
        this.coordinateText = element(this.document, 'div', {
            className: 'ip-flw-coordinates',
            'aria-label': 'Pointer world coordinates',
        }, 'X 0.00  Z 0.00');
        append(this.statusBar, this.statusText, this.coordinateText);

        this.shell = element(this.document, 'div', {
            className: 'ip-flw-shell',
        });
        append(this.shell, this.assetPane, this.viewportPane, this.propertiesPane);
        append(this.root, this.toolbar, this.shell, this.statusBar);
        this._renderAssetTree('');
        this._setViewMode('plan');
        this._setToolMode('select');
    };

    Workspace.prototype._connectRendering = function () {
        const options = this.options;
        this.topAdapter = options.topAdapter || null;
        if (!this.topAdapter && this.layoutRuntime) {
            this.topAdapter = this.layoutRuntime.createTopPlanAdapter(
                this.planView,
                Object.assign({}, options.topPlanOptions || {}, {
                    assetCatalog: clone(options.assetCatalog || []),
                })
            );
            this.createdTopAdapter = true;
        }

        this.threeAdapter = options.threeAdapter || null;
        if (!this.threeAdapter && options.threeRuntime
                && typeof options.threeRuntime.createThreeAdapter === 'function') {
            this.threeAdapter = options.threeRuntime.createThreeAdapter(
                options.threeOptions || {}
            );
            this.createdThreeAdapter = true;
        }
        if (this.threeAdapter && typeof this.threeAdapter.mount === 'function') {
            const diagnostics = typeof this.threeAdapter.getDiagnostics === 'function'
                ? this.threeAdapter.getDiagnostics() : {};
            if (!diagnostics.mounted) this.threeAdapter.mount(this.threeView);
        }
        // _build() establishes the initial tab state before adapters exist.
        // Reconcile once mounting finishes so a real 3D adapter immediately
        // enables the segmented control.
        this._setViewMode(this.viewMode);

        const adapters = [this.topAdapter, this.threeAdapter].filter(Boolean);
        this.controller = options.controller || this.layoutRuntime.createEditor({
            assetCatalog: clone(options.assetCatalog || []),
            adapters: adapters,
        });
        if (options.controller
                && typeof this.controller.setAssetCatalog === 'function') {
            this.controller.setAssetCatalog(options.assetCatalog || []);
        }
        const selectionHandler = this._handleAdapterSelection.bind(this);
        adapters.forEach(function (adapter) {
            if (typeof adapter.setSelectionHandler === 'function') {
                adapter.setSelectionHandler(selectionHandler);
            }
        });

        if (typeof options.installPlanMarquee === 'function') {
            const cleanup = options.installPlanMarquee({
                host: this.planView,
                getMode: function () { return this.toolMode; }.bind(this),
                select: this.applyMarqueeSelection.bind(this),
                eventToWorld: this._eventWorld.bind(this),
            });
            this.marqueeCleanup = typeof cleanup === 'function' ? cleanup : null;
        }
    };

    Workspace.prototype._connectEvents = function () {
        this._listen(this.toolbar, 'click', this._handleToolbarClick.bind(this));
        this._listen(this.viewTabs, 'click', this._handleViewTabClick.bind(this));
        this._listen(this.assetSearch, 'input', function () {
            this._renderAssetTree(this.assetSearch.value || '');
        }.bind(this));
        this._listen(this.assetTree, 'dragstart', this._handleAssetDragStart.bind(this));
        this._listen(this.assetTree, 'dragend', this._cancelGhost.bind(this));
        this._listen(this.assetTree, 'keydown', this._handleAssetKeyDown.bind(this));
        this._listen(this.viewportStack, 'dragover', this._handleDragOver.bind(this));
        this._listen(this.viewportStack, 'drop', this._handleDrop.bind(this));
        this._listen(this.viewportStack, 'dragleave', this._handleDragLeave.bind(this));
        this._listen(
            this.candidateControls,
            'click',
            this._handleCandidateAction.bind(this)
        );
        this._listen(this.planView, 'pointerdown', this._handlePlanPointerDown.bind(this));
        this._listen(this.planView, 'pointermove', this._handlePlanPointerMove.bind(this));
        this._listen(this.planView, 'pointerup', this._handlePlanPointerUp.bind(this));
        this._listen(this.planView, 'pointercancel', this._cancelPointerGesture.bind(this));
        this._listen(
            this.planView,
            'lostpointercapture',
            this._handleLostPointerCapture.bind(this)
        );
        this._listen(this.planView, 'wheel', this._handlePlanWheel.bind(this), {
            passive: false,
        });
        this._listen(this.planView, 'click', this._handlePlanClick.bind(this));
        this._listen(this.planView, 'dblclick', this._handlePlanDoubleClick.bind(this));
        this._listen(this.propertiesBody, 'change', this._handlePropertyChange.bind(this));
        this._listen(this.root, 'keydown', this._handleKeyDown.bind(this));
    };

    Workspace.prototype._renderAssetTree = function (query) {
        const needle = String(query || '').trim().toLowerCase();
        const groups = new Map();
        this.assetCatalog.forEach(function (record) {
            const searchable = (
                record.label + ' ' + record.assetId + ' '
                + record.category + ' ' + record.description
            ).toLowerCase();
            if (needle && !searchable.includes(needle)) return;
            if (!groups.has(record.category)) groups.set(record.category, []);
            groups.get(record.category).push(record);
        });
        clearElement(this.assetTree);
        if (!groups.size) {
            this.assetTree.appendChild(element(this.document, 'p', {
                className: 'ip-flw-empty',
            }, 'No matching assets'));
            return;
        }
        Array.from(groups.keys()).sort().forEach(function (category) {
            const group = element(this.document, 'section', {
                className: 'ip-flw-asset-group',
                role: 'group',
                'aria-label': category,
            });
            group.appendChild(element(this.document, 'h3', {}, category));
            groups.get(category).forEach(function (record) {
                const row = element(this.document, 'div', {
                    className: 'ip-flw-asset-row',
                    role: 'treeitem',
                    tabindex: '0',
                    draggable: 'true',
                    'aria-label': 'Place ' + record.label,
                    title: 'Drag ' + record.label + ' into the layout',
                    'data-asset-id': record.assetId,
                    'data-asset-revision': record.assetDefinitionRevision,
                });
                append(row,
                    element(this.document, 'span', {
                        className: 'ip-flw-asset-symbol',
                        'aria-hidden': 'true',
                    }, 'A'),
                    element(this.document, 'span', {
                        className: 'ip-flw-asset-copy',
                    }),
                    element(this.document, 'span', {
                        className: 'ip-flw-drag-grip',
                        'aria-hidden': 'true',
                    }, '::')
                );
                const copy = row.children[1];
                copy.appendChild(element(this.document, 'strong', {}, record.label));
                copy.appendChild(element(this.document, 'small', {}, record.assetId));
                group.appendChild(row);
            }, this);
            this.assetTree.appendChild(group);
        }, this);
    };

    Workspace.prototype._assetFromRow = function (target) {
        const assetId = targetDataId(target, 'data-asset-id', this.assetTree);
        if (!assetId) return null;
        return this.assetCatalog.find(function (record) {
            return record.assetId === assetId;
        }) || null;
    };

    Workspace.prototype._handleAssetDragStart = function (event) {
        const asset = this._assetFromRow(event.target);
        if (!asset) return;
        const dragSessionId = (typeof this.options.createDragSessionId === 'function'
            ? this.options.createDragSessionId(asset)
            : createDragSessionId());
        const text = createAssetDragPayload(asset, dragSessionId);
        const transfer = event.dataTransfer;
        if (transfer && typeof transfer.setData === 'function') {
            transfer.setData(ASSET_MIME, text);
            transfer.setData('text/plain', text);
            transfer.effectAllowed = 'copy';
        }
        this.activeDrag = {
            payload: parseAssetDragPayload(text),
            asset: asset,
        };
        this._clearDragAdvisory();
        this.session.beginGhostPlacement({
            assetId: asset.assetId,
            assetDefinitionRevision: asset.assetDefinitionRevision,
            metadata: {
                instanceLabel: asset.label,
                dragSessionId: dragSessionId,
            },
        });
    };

    Workspace.prototype._payloadForEvent = function (event) {
        const parsed = parseAssetDragPayload(event);
        if (parsed) return parsed;
        return this.activeDrag && this.activeDrag.payload || null;
    };

    Workspace.prototype._ensureGhost = function (payload) {
        const current = this.session.getState().ghostPlacement;
        if (current && current.assetId === payload.assetId
                && current.assetDefinitionRevision === payload.assetDefinitionRevision) {
            return;
        }
        if (current) this.session.cancelGhostPlacement();
        const asset = this.assetCatalog.find(function (record) {
            return record.assetId === payload.assetId
                && record.assetDefinitionRevision === payload.assetDefinitionRevision;
        });
        this.session.beginGhostPlacement({
            assetId: payload.assetId,
            assetDefinitionRevision: payload.assetDefinitionRevision,
            metadata: {
                instanceLabel: asset ? asset.label : payload.assetId,
                dragSessionId: payload.dragSessionId,
            },
        });
    };

    Workspace.prototype._catalogAssetFromTarget = function (target) {
        const assetId = targetDataId(target, 'data-asset-id', this.assetTree);
        const revision = targetDataId(
            target,
            'data-asset-revision',
            this.assetTree
        );
        if (!assetId || !revision) return null;
        return this.assetCatalog.find(function (record) {
            return record.assetId === assetId
                && record.assetDefinitionRevision === revision;
        }) || null;
    };

    Workspace.prototype._keyboardPlacementWorld = function () {
        const configured = this.options.keyboardPlacementPoint;
        const supplied = typeof configured === 'function'
            ? configured({
                viewMode: this.viewMode,
                adapter: this.topAdapter,
                workspace: this,
            })
            : configured;
        if (supplied && typeof supplied === 'object') {
            return snapWorldPoint(supplied, this.gridSize);
        }
        if (this.topAdapter
                && typeof this.topAdapter.clientToWorld === 'function') {
            const rect = typeof this.planView.getBoundingClientRect === 'function'
                ? this.planView.getBoundingClientRect()
                : null;
            const left = finite(rect && rect.left, 0);
            const top = finite(rect && rect.top, 0);
            const width = Math.max(
                1,
                finite(rect && rect.width, this.planView.clientWidth || 1)
            );
            const height = Math.max(
                1,
                finite(rect && rect.height, this.planView.clientHeight || 1)
            );
            const world = this.topAdapter.clientToWorld({
                clientX: left + width / 2,
                clientY: top + height / 2,
                floorY: 0,
            });
            if (world) return snapWorldPoint(world, this.gridSize);
        }
        return { x: 0, y: 0, z: 0 };
    };

    Workspace.prototype._handleAssetKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key !== 'enter' && key !== ' ') return;
        const asset = this._catalogAssetFromTarget(event.target);
        if (!asset) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (this.state.busy) return;
        const world = this._keyboardPlacementWorld();
        this.session.beginGhostPlacement({
            assetId: asset.assetId,
            assetDefinitionRevision: asset.assetDefinitionRevision,
            metadata: {
                instanceLabel: asset.label,
                inputMethod: 'keyboard',
            },
        });
        this.session.updateGhostPlacement(world, true);
        this._renderGhost(world, asset.assetId);
        this._invoke('Place asset', function () {
            return this.session.commitGhostPlacement({
                positionMode: 'manual',
            });
        }.bind(this));
    };

    Workspace.prototype._eventWorld = function (event) {
        const adapter = this.viewMode === '3d' ? this.threeAdapter : this.topAdapter;
        const context = {
            viewMode: this.viewMode,
            adapter: adapter,
            controller: this.controller,
            root: this.viewportStack,
        };
        let result = null;
        if (typeof this.eventToWorld === 'function') {
            result = this.eventToWorld(event, context);
        } else if (this.viewMode === '3d'
                && adapter
                && typeof adapter.worldPointOnFloor === 'function') {
            result = adapter.worldPointOnFloor(event, 0);
        } else if (adapter && typeof adapter.clientToWorld === 'function') {
            result = adapter.clientToWorld(event);
        }
        if (!result || typeof result !== 'object') {
            throw new Error('eventToWorld did not return a world point');
        }
        return snapWorldPoint(result, this.gridSize);
    };

    Workspace.prototype._tryEventWorld = function (event) {
        try {
            return this._eventWorld(event);
        } catch (error) {
            return null;
        }
    };

    Workspace.prototype._handleDragOver = function (event) {
        const payload = this._payloadForEvent(event);
        if (!payload) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        this._ensureGhost(payload);
        const world = this._tryEventWorld(event);
        if (!world) {
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
            this._showGesture('No valid facility-floor point');
            return;
        }
        this.activeDrag = {
            payload: payload,
            asset: this.activeDrag && this.activeDrag.asset || null,
        };
        this.session.updateGhostPlacement(world, true);
        this._requestDragAdvisory(payload, world);
        this._renderGhost(world, payload.assetId);
        this._setCoordinates(world);
    };

    Workspace.prototype._handleDrop = function (event) {
        const payload = this._payloadForEvent(event);
        if (!payload) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this._ensureGhost(payload);
        const world = this._tryEventWorld(event);
        if (!world) {
            this.session.cancelGhostPlacement();
            this.activeDrag = null;
            this._hideGhost();
            this._showGesture('Placement cancelled: no valid floor point');
            return;
        }
        this.session.updateGhostPlacement(world, true);
        this._cancelAdvisoryRequest('Drop completed.');
        if (this.useAuthoritativePlacementCandidates
                && typeof this.session.requestPlacementAlternatives
                    === 'function') {
            this._invoke('Find placement alternatives', function () {
                return this.session.requestPlacementAlternatives({
                    assetId: payload.assetId,
                    assetDefinitionRevision:
                        payload.assetDefinitionRevision,
                    requestedPosition: world,
                    maximumCandidates: 8,
                });
            }.bind(this));
        } else {
            this._invoke('Place asset', function () {
                return this.session.commitGhostPlacement({
                    positionMode: 'manual',
                });
            }.bind(this));
        }
        this.activeDrag = null;
        this.dragAdvisory = null;
        this._hideGhost();
    };

    Workspace.prototype._handleDragLeave = function (event) {
        const related = event && event.relatedTarget;
        if (related && typeof this.viewportStack.contains === 'function'
                && this.viewportStack.contains(related)) return;
        this._cancelGhost();
    };

    Workspace.prototype._cancelGhost = function () {
        if (this.destroyed) return;
        this._cancelAdvisoryRequest('Drag cancelled.');
        if (this.session.getState().ghostPlacement) {
            this.session.cancelGhostPlacement();
        }
        this.activeDrag = null;
        this.dragAdvisory = null;
        this._hideGhost();
    };

    Workspace.prototype._cancelAdvisoryRequest = function (reason) {
        if (this.spatialAdvisor
                && typeof this.spatialAdvisor.cancel === 'function') {
            this.spatialAdvisor.cancel(reason);
        }
    };

    Workspace.prototype._clearDragAdvisory = function () {
        this._cancelAdvisoryRequest('A new drag started.');
        this.dragAdvisory = null;
    };

    Workspace.prototype._requestDragAdvisory = function (payload, world) {
        if (!this.spatialAdvisor
                || typeof this.spatialAdvisor.request !== 'function'
                || !this.state.layout) {
            this.dragAdvisory = null;
            return;
        }
        const dragSessionId = payload.dragSessionId;
        const positionKey = [
            world.x,
            world.y,
            world.z,
        ].join('|');
        this.dragAdvisory = {
            authority: 'browser-advisory',
            authoritative: false,
            status: 'pending',
            summary: 'Checking coarse overlap and zone placement.',
            dragSessionId: dragSessionId,
            positionKey: positionKey,
        };
        this._renderGhost(world, payload.assetId);
        const catalog = this.assetCatalog.map(function (record) {
            return clone(record.source || record);
        });
        this.spatialAdvisor.request({
            layoutRevision: this.state.baseRevision,
            layout: this.state.layout,
            assetCatalog: catalog,
            ghost: {
                assetId: payload.assetId,
                assetDefinitionRevision: payload.assetDefinitionRevision,
                worldPosition: world,
            },
        }).then(function (advisory) {
            if (this.destroyed || !this.activeDrag
                    || this.activeDrag.payload.dragSessionId !== dragSessionId) {
                return;
            }
            const current = this.session.getState().ghostPlacement;
            if (!current || !current.worldPosition
                    || [
                        current.worldPosition.x,
                        current.worldPosition.y,
                        current.worldPosition.z,
                    ].join('|') !== positionKey) {
                return;
            }
            this.dragAdvisory = Object.assign({}, clone(advisory), {
                dragSessionId: dragSessionId,
                positionKey: positionKey,
            });
            this._renderGhost(current.worldPosition, payload.assetId);
        }.bind(this)).catch(function (error) {
            if (error && error.name === 'AbortError') return;
            if (this.destroyed || !this.activeDrag
                    || this.activeDrag.payload.dragSessionId !== dragSessionId) {
                return;
            }
            const current = this.session.getState().ghostPlacement;
            this.dragAdvisory = {
                authority: 'browser-advisory',
                authoritative: false,
                status: 'unavailable',
                summary: 'Coarse advisory is unavailable. The server remains authoritative.',
                dragSessionId: dragSessionId,
                positionKey: positionKey,
            };
            if (current && current.worldPosition) {
                this._renderGhost(current.worldPosition, payload.assetId);
            }
        }.bind(this));
    };

    Workspace.prototype._renderGhost = function (world, assetId) {
        const active = this.session.getState().ghostPlacement || {};
        const candidate = active.metadata
            && active.metadata.previewKind
                === 'authoritative-placement-candidate'
            ? active.metadata
            : null;
        const advisory = candidate ? null : this.dragAdvisory;
        const ghost = {
            assetId: active.assetId || assetId,
            assetDefinitionRevision: active.assetDefinitionRevision || '',
            worldPosition: world,
            valid: active.valid !== false,
            metadata: Object.assign({}, clone(active.metadata || {}), {
                spatialAdvisory: clone(advisory),
            }),
        };
        [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
            function (adapter) {
                if (typeof adapter.setGhostPlacement === 'function') {
                    adapter.setGhostPlacement(ghost);
                }
            }
        );
        this.ghostOverlay.hidden = false;
        this.ghostOverlay.setAttribute('data-active', 'true');
        if (candidate) {
            const assessment = candidateAssessment(candidate);
            this.ghostOverlay.setAttribute(
                'data-advisory-state',
                'server-authoritative'
            );
            this.ghostOverlay.setAttribute(
                'data-safety-status',
                assessment.status
            );
            this.ghostOverlay.textContent = cleanString(assetId, 'Asset')
                + ' | Authoritative option '
                + (finite(candidate.candidateIndex, 0) + 1)
                + ' of ' + finite(candidate.candidateCount, 1)
                + (candidate.family ? ' | ' + candidate.family : '')
                + ' | ' + assessment.label
                + (assessment.summary ? ' | ' + assessment.summary : '')
                + ' | X ' + world.x.toFixed(2)
                + ' Z ' + world.z.toFixed(2);
            const announcement = 'Authoritative placement option '
                + (finite(candidate.candidateIndex, 0) + 1)
                + ' of ' + finite(candidate.candidateCount, 1)
                + (candidate.family ? ', ' + candidate.family : '')
                + '. ' + assessment.label
                + (assessment.summary ? '. ' + assessment.summary : '')
                + '. Not yet applied.';
            if (this.advisoryLiveRegion.textContent !== announcement) {
                this.advisoryLiveRegion.textContent = announcement;
            }
        } else {
            this.ghostOverlay.removeAttribute('data-safety-status');
            const status = advisory && advisory.status || 'unavailable';
            this.ghostOverlay.setAttribute('data-advisory-state', status);
            this.ghostOverlay.textContent = cleanString(assetId, 'Asset')
                + ' | X ' + world.x.toFixed(2)
                + ' Z ' + world.z.toFixed(2)
                + (advisory
                    ? ' | Advisory: ' + cleanString(
                        advisory.summary,
                        status
                    )
                    : ' | Advisory: server check on placement');
            const announcement = advisory
                ? 'Placement advisory: ' + cleanString(
                    advisory.summary,
                    status
                )
                : 'Placement advisory will be confirmed by the server.';
            if (this.advisoryLiveRegion.textContent !== announcement) {
                this.advisoryLiveRegion.textContent = announcement;
            }
        }
    };

    Workspace.prototype._hideGhost = function () {
        [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
            function (adapter) {
                if (typeof adapter.setGhostPlacement === 'function') {
                    adapter.setGhostPlacement(null);
                }
            }
        );
        this.ghostOverlay.hidden = true;
        this.ghostOverlay.removeAttribute('data-active');
        this.ghostOverlay.removeAttribute('data-advisory-state');
        this.ghostOverlay.removeAttribute('data-safety-status');
        this.ghostOverlay.textContent = '';
        this.advisoryLiveRegion.textContent = '';
    };

    Workspace.prototype._handleCandidateAction = function (event) {
        const action = targetDataId(
            event.target,
            'data-candidate-action',
            this.candidateControls
        );
        if (!action || this.state.busy) return;
        if (action === 'previous') {
            this.session.cyclePlacementAlternative(-1);
        } else if (action === 'next') {
            this.session.cyclePlacementAlternative(1);
        } else if (action === 'dismiss') {
            this.session.dismissPlacementAlternatives();
        } else if (action === 'accept') {
            this._invoke('Accept placement alternative', function () {
                return this.session.acceptPlacementAlternative();
            }.bind(this));
        }
    };

    Workspace.prototype._renderCandidateControls = function () {
        const proposal = this.state.placementAlternatives;
        if (!proposal || !Array.isArray(proposal.candidates)
                || !proposal.candidates.length) {
            this.candidateControls.hidden = true;
            this.candidateControls.removeAttribute('data-safety-status');
            this.candidateSummary.textContent = '';
            return;
        }
        const candidate = proposal.candidates[proposal.selectedIndex];
        const assessment = candidateAssessment(candidate);
        this.candidateControls.hidden = false;
        this.candidateControls.setAttribute(
            'data-safety-status',
            assessment.status
        );
        this.candidateSummary.textContent = 'Placement option '
            + (proposal.selectedIndex + 1)
            + ' of ' + proposal.candidates.length
            + (candidate.family ? ': ' + candidate.family : '')
            + '. ' + assessment.label
            + (assessment.summary ? '. ' + assessment.summary : '')
            + '. Not yet applied.';
        const cycleDisabled = proposal.candidates.length < 2 || this.state.busy;
        ['previous', 'next'].forEach(function (action) {
            const button = this.candidateControls.querySelector(
                '[data-candidate-action="' + action + '"]'
            );
            if (button) button.disabled = cycleDisabled;
        }, this);
        ['accept', 'dismiss'].forEach(function (action) {
            const button = this.candidateControls.querySelector(
                '[data-candidate-action="' + action + '"]'
            );
            if (button) {
                button.disabled = this.state.busy
                    || (action === 'accept'
                        && assessment.status === 'unsafe');
            }
        }, this);
    };

    Workspace.prototype._handleAdapterSelection = function (placementId) {
        if (this.suppressAdapterSelection === placementId) {
            this.suppressAdapterSelection = null;
            return;
        }
        this.session.select(placementId);
    };

    Workspace.prototype.handleViewSelection = function (id, event) {
        const additive = Boolean(event && (event.ctrlKey || event.metaKey));
        return this.session.select(id, {
            additive: additive,
            toggle: additive,
        });
    };

    Workspace.prototype.applyMarqueeSelection = function (ids, event) {
        return this.session.selectMany(Array.isArray(ids) ? ids : [], {
            additive: Boolean(event && (event.ctrlKey || event.metaKey)),
        });
    };

    Workspace.prototype._worldDelta = function (start, end) {
        return {
            x: snapCoordinate(end.x - start.x, this.gridSize),
            y: finite(end.y, 0) - finite(start.y, 0),
            z: snapCoordinate(end.z - start.z, this.gridSize),
        };
    };

    Workspace.prototype._beginPointerCapture = function (event) {
        this._releasePointerCapture();
        const pointerId = event && Number.isFinite(Number(event.pointerId))
            ? Number(event.pointerId)
            : null;
        this.pointerCaptureId = pointerId;
        let captured = false;
        if (pointerId !== null
                && this.planView
                && typeof this.planView.setPointerCapture === 'function') {
            try {
                this.planView.setPointerCapture(pointerId);
                captured = true;
            } catch (error) {
                captured = false;
            }
        }
        if (captured || !this.document
                || typeof this.document.addEventListener !== 'function') return;
        const move = function (nextEvent) {
            if (this.planView.contains(nextEvent.target)) return;
            this._handlePlanPointerMove(nextEvent);
        }.bind(this);
        const up = function (nextEvent) {
            if (this.planView.contains(nextEvent.target)) return;
            this._handlePlanPointerUp(nextEvent);
        }.bind(this);
        const cancel = this._cancelPointerGesture.bind(this);
        this.document.addEventListener('pointermove', move);
        this.document.addEventListener('pointerup', up);
        this.document.addEventListener('pointercancel', cancel);
        this.pointerFallbackCleanup = function () {
            this.document.removeEventListener('pointermove', move);
            this.document.removeEventListener('pointerup', up);
            this.document.removeEventListener('pointercancel', cancel);
        }.bind(this);
    };

    Workspace.prototype._releasePointerCapture = function () {
        const pointerId = this.pointerCaptureId;
        this.pointerCaptureId = null;
        if (pointerId !== null
                && this.planView
                && typeof this.planView.releasePointerCapture === 'function') {
            try {
                if (typeof this.planView.hasPointerCapture !== 'function'
                        || this.planView.hasPointerCapture(pointerId)) {
                    this.planView.releasePointerCapture(pointerId);
                }
            } catch (error) {
                // The browser may release capture automatically after pointerup.
            }
        }
        if (this.pointerFallbackCleanup) this.pointerFallbackCleanup();
        this.pointerFallbackCleanup = null;
    };

    Workspace.prototype._handleLostPointerCapture = function () {
        if (!this.pointerGesture) return;
        this.pointerCaptureId = null;
        this._cancelPointerGesture();
    };

    Workspace.prototype._handlePlanPointerDown = function (event) {
        if (this.toolMode === 'pan') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.pointerGesture = {
                kind: 'pan',
                clientX: finite(event.clientX, 0),
                clientY: finite(event.clientY, 0),
            };
            this._beginPointerCapture(event);
            return;
        }
        const world = this._eventWorld(event);
        const placementId = targetDataId(
            event.target,
            'data-placement-id',
            this.planView
        );
        if (placementId && this.toolMode === 'select') {
            const additive = Boolean(event && (event.ctrlKey || event.metaKey));
            const alreadySelected = this.state.selection.includes(placementId);
            if (additive || !alreadySelected) {
                this.handleViewSelection(placementId, event);
            }
            this.suppressAdapterSelection = placementId;
            this.pointerGesture = {
                kind: 'move',
                placementId: placementId,
                start: world,
                last: world,
            };
            this._beginPointerCapture(event);
            return;
        }
        const zoneId = targetDataId(
            event.target,
            'data-zone-id',
            this.planView
        );
        if (zoneId && this.toolMode === 'select') {
            this.handleViewSelection(zoneId, event);
            this.suppressAdapterSelection = zoneId;
            return;
        }
        if (this.toolMode === 'rectangle-zone') {
            this.pointerGesture = { kind: 'rectangle-zone', start: world, last: world };
            this._showGesture('Zone: ' + world.x.toFixed(2) + ', ' + world.z.toFixed(2));
            this._beginPointerCapture(event);
            return;
        }
        if (this.toolMode === 'select') {
            this.pointerGesture = { kind: 'marquee', start: world, last: world };
            this._showGesture('Selection');
            this._beginPointerCapture(event);
        }
    };

    Workspace.prototype._handlePlanPointerMove = function (event) {
        if (this.pointerGesture && this.pointerGesture.kind === 'pan') {
            const clientX = finite(event.clientX, this.pointerGesture.clientX);
            const clientY = finite(event.clientY, this.pointerGesture.clientY);
            if (this.topAdapter
                    && typeof this.topAdapter.panByPixels === 'function') {
                this.topAdapter.panByPixels(
                    clientX - this.pointerGesture.clientX,
                    clientY - this.pointerGesture.clientY
                );
            }
            this.pointerGesture.clientX = clientX;
            this.pointerGesture.clientY = clientY;
            return;
        }
        let world;
        try {
            world = this._eventWorld(event);
        } catch (error) {
            return;
        }
        this._setCoordinates(world);
        if (!this.pointerGesture) return;
        this.pointerGesture.last = world;
        if (this.pointerGesture.kind === 'rectangle-zone') {
            this._showGesture(
                'Zone ' + Math.abs(world.x - this.pointerGesture.start.x).toFixed(2)
                + ' x ' + Math.abs(world.z - this.pointerGesture.start.z).toFixed(2)
            );
        } else if (this.pointerGesture.kind === 'marquee') {
            this._showGesture('Selection region');
        }
    };

    Workspace.prototype._handlePlanPointerUp = function (event) {
        const gesture = this.pointerGesture;
        this.pointerGesture = null;
        this._releasePointerCapture();
        this._hideGesture();
        if (!gesture) return;
        if (gesture.kind === 'pan') return;
        const end = this._eventWorld(event);
        if (gesture.kind === 'move') {
            const delta = this._worldDelta(gesture.start, end);
            if (delta.x || delta.y || delta.z) {
                this._invoke('Move selection', function () {
                    return this.session.moveSelected(delta);
                }.bind(this));
            }
            return;
        }
        if (gesture.kind === 'rectangle-zone') {
            if (gesture.start.x !== end.x || gesture.start.z !== end.z) {
                this._invoke('Create rectangle zone', function () {
                    return this.session.createRectangleZone(
                        gesture.start,
                        end,
                        { label: 'New zone', zoneType: 'workcell' }
                    );
                }.bind(this));
            }
            return;
        }
        if (gesture.kind === 'marquee') {
            const resolver = this.marqueeResolver
                || (this.topAdapter
                    && typeof this.topAdapter.resolveMarquee === 'function'
                    ? this.topAdapter.resolveMarquee.bind(this.topAdapter)
                    : null);
            if (resolver) {
                const ids = resolver({
                    start: gesture.start,
                    end: end,
                    layout: clone(this.state.layout),
                    event: event,
                });
                this.applyMarqueeSelection(ids, event);
            } else if (!event.ctrlKey && !event.metaKey) {
                this.session.clearSelection();
            }
        }
    };

    Workspace.prototype._handlePlanWheel = function (event) {
        if (!this.topAdapter
                || typeof this.topAdapter.zoomAt !== 'function') return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        const delta = finite(event.deltaY, 0);
        const factor = Math.exp(-delta * 0.0015);
        this.topAdapter.zoomAt(event, factor);
        const world = this._tryEventWorld(event);
        if (world) this._setCoordinates(world);
    };

    Workspace.prototype._cancelPointerGesture = function () {
        this.pointerGesture = null;
        this._releasePointerCapture();
        this._hideGesture();
    };

    Workspace.prototype._handlePlanClick = function (event) {
        if (this.toolMode !== 'polygon-zone') return;
        if (targetDataId(event.target, 'data-placement-id', this.planView)) return;
        const world = this._eventWorld(event);
        this.polygonPoints.push(world);
        this._showGesture(this.polygonPoints.length + ' polygon points');
    };

    Workspace.prototype._handlePlanDoubleClick = function (event) {
        if (this.toolMode !== 'polygon-zone') return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this._finishPolygon();
    };

    Workspace.prototype._finishPolygon = function () {
        if (this.polygonPoints.length < 3) return false;
        const points = this.polygonPoints.slice();
        this.polygonPoints = [];
        this._hideGesture();
        this._invoke('Create polygon zone', function () {
            return this.session.createPolygonZone(
                points,
                { label: 'New zone', zoneType: 'workcell' }
            );
        }.bind(this));
        return true;
    };

    Workspace.prototype._showGesture = function (text) {
        this.gestureOverlay.hidden = false;
        this.gestureOverlay.textContent = text;
    };

    Workspace.prototype._hideGesture = function () {
        this.gestureOverlay.hidden = true;
        this.gestureOverlay.textContent = '';
    };

    Workspace.prototype._setCoordinates = function (world) {
        this.coordinateText.textContent = 'X ' + finite(world.x, 0).toFixed(2)
            + '  Z ' + finite(world.z, 0).toFixed(2);
    };

    Workspace.prototype._handleToolbarClick = function (event) {
        const command = targetDataId(event.target, 'data-command', this.toolbar);
        if (!command) return;
        this.executeCommand(command);
    };

    Workspace.prototype.executeCommand = function (command) {
        if (TOOL_MODES.includes(command)) {
            this._setToolMode(command);
            return Promise.resolve(this.getState());
        }
        if (command === 'fit') {
            this.controller.fit();
            return Promise.resolve(this.getState());
        }
        const actions = {
            rotate: function () { return this.session.rotateSelected90(); },
            duplicate: function () {
                return this.session.duplicateSelected(DEFAULT_DUPLICATE_OFFSET);
            },
            delete: function () { return this.session.deleteSelected(); },
            undo: function () { return this.session.undo(); },
            redo: function () { return this.session.redo(); },
            save: function () { return this.session.save(); },
            lock: function () {
                const placements = this.state.layout.placements.filter(function (item) {
                    return this.state.selection.includes(item.placementId);
                }, this);
                const allLocked = placements.length > 0 && placements.every(
                    function (item) { return item.positionMode === 'locked'; }
                );
                return allLocked
                    ? this.session.unlockSelected()
                    : this.session.lockSelected();
            },
        };
        const action = actions[command];
        if (!action) return Promise.resolve(this.getState());
        return this._invoke(command, action.bind(this));
    };

    Workspace.prototype._handleViewTabClick = function (event) {
        const view = targetDataId(event.target, 'data-view', this.viewTabs);
        if (VIEW_MODES.includes(view)) this._setViewMode(view);
    };

    Workspace.prototype._setViewMode = function (mode) {
        if (!VIEW_MODES.includes(mode)) throw new TypeError('invalid view mode');
        if (mode === '3d' && !this.threeAdapter) mode = 'plan';
        this.viewMode = mode;
        const plan = mode === 'plan';
        this.planView.hidden = !plan;
        this.threeView.hidden = plan;
        this.planTab.setAttribute('aria-selected', plan ? 'true' : 'false');
        this.planTab.setAttribute('tabindex', plan ? '0' : '-1');
        this.threeTab.setAttribute('aria-selected', plan ? 'false' : 'true');
        this.threeTab.setAttribute('tabindex', plan ? '-1' : '0');
        this.threeTab.disabled = !this.threeAdapter;
        this.root.setAttribute('data-view-mode', mode);
        if (this.threeAdapter && typeof this.threeAdapter.invalidate === 'function'
                && mode === '3d') {
            this.threeAdapter.invalidate();
        }
        this._renderStatus();
        return mode;
    };

    Workspace.prototype._setToolMode = function (mode) {
        if (!TOOL_MODES.includes(mode)) throw new TypeError('invalid tool mode');
        this.toolMode = mode;
        this.polygonPoints = [];
        this._cancelPointerGesture();
        this.root.setAttribute('data-tool-mode', mode);
        const buttons = this.toolbar.querySelectorAll
            ? this.toolbar.querySelectorAll('[data-command]')
            : [];
        Array.prototype.forEach.call(buttons, function (button) {
            const command = button.getAttribute('data-command');
            if (TOOL_MODES.includes(command)) {
                button.setAttribute(
                    'aria-pressed',
                    command === mode ? 'true' : 'false'
                );
            } else {
                button.removeAttribute('aria-pressed');
            }
        });
        this._renderStatus();
        return mode;
    };

    Workspace.prototype._handlePropertyChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-property',
            this.propertiesBody
        );
        if (!field) return;
        const selected = selectionRecord(this.state.layout, this.state.selection);
        if (!selected) return;
        if (selected.kind === 'zone' && (field === 'width' || field === 'depth')) {
            const width = finite(
                this.propertiesBody.querySelector('[data-property="width"]').value,
                NaN
            );
            const depth = finite(
                this.propertiesBody.querySelector('[data-property="depth"]').value,
                NaN
            );
            this._invoke('Resize zone', function () {
                return this.session.editZoneDimensions(
                    selected.value.zoneId,
                    { width: width, depth: depth }
                );
            }.bind(this));
            return;
        }
        if (selected.kind !== 'placement') return;
        const placement = selected.value;
        if (['x', 'y', 'z'].includes(field)) {
            const current = placement.transform.position;
            const next = finite(event.target.value, NaN);
            if (!Number.isFinite(next)) return;
            const delta = { x: 0, y: 0, z: 0 };
            delta[field] = snapCoordinate(next, field === 'y' ? 0 : this.gridSize)
                - finite(current[field], 0);
            this._invoke('Move selection', function () {
                return this.session.moveSelected(delta);
            }.bind(this));
        } else if (field === 'rotation') {
            const requested = finite(event.target.value, NaN);
            if (!Number.isFinite(requested)) return;
            const current = quaternionYawDegrees(placement.transform.quaternion);
            const turns = Math.round((requested - current) / 90);
            if (Math.abs(current + turns * 90 - requested) > 0.001) {
                this._setError(new Error('Rotation must use 90-degree increments'));
                return;
            }
            this._invoke('Rotate selection', function () {
                return this.session.rotateSelected90(turns);
            }.bind(this));
        }
    };

    Workspace.prototype._field = function (label, property, value, options) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-property-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        const attributes = Object.assign({
            type: 'number',
            value: Number.isFinite(value) ? String(Number(value.toFixed(4))) : '',
            'data-property': property,
            'aria-label': label,
        }, options || {});
        wrapper.appendChild(element(this.document, 'input', attributes));
        return wrapper;
    };

    Workspace.prototype._renderProperties = function () {
        clearElement(this.propertiesBody);
        if (!this.state.loaded) {
            this.propertiesBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-empty',
            }, 'Load a layout to begin.'));
            return;
        }
        if (!this.state.selection.length) {
            this.propertiesBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-empty',
            }, 'Select an asset or zone.'));
            return;
        }
        if (this.state.selection.length > 1) {
            this.propertiesBody.appendChild(element(this.document, 'div', {
                className: 'ip-flw-selection-summary',
            }, this.state.selection.length + ' objects selected'));
            return;
        }
        const selected = selectionRecord(this.state.layout, this.state.selection);
        if (!selected) return;
        if (selected.kind === 'placement') {
            const placement = selected.value;
            const heading = cleanString(
                placement.metadata && placement.metadata.instanceLabel,
                placement.assetId
            );
            this.propertiesBody.appendChild(element(this.document, 'h3', {}, heading));
            this.propertiesBody.appendChild(element(this.document, 'dl', {
                className: 'ip-flw-property-list',
            }));
            const list = this.propertiesBody.children[
                this.propertiesBody.children.length - 1
            ];
            [
                ['Asset', placement.assetId],
                ['Placement', placement.placementId],
                ['Position ownership', placement.positionMode],
            ].forEach(function (pair) {
                list.appendChild(element(this.document, 'dt', {}, pair[0]));
                list.appendChild(element(this.document, 'dd', {}, pair[1]));
            }, this);
            const transform = placement.transform || {};
            const position = transform.position || {};
            const grid = element(this.document, 'div', {
                className: 'ip-flw-property-grid',
            });
            append(grid,
                this._field('X position', 'x', finite(position.x, 0), {
                    step: String(this.gridSize),
                }),
                this._field('Y position', 'y', finite(position.y, 0), {
                    step: '0.1',
                }),
                this._field('Z position', 'z', finite(position.z, 0), {
                    step: String(this.gridSize),
                }),
                this._field(
                    'Rotation (degrees)',
                    'rotation',
                    quaternionYawDegrees(transform.quaternion),
                    { step: '90' }
                )
            );
            this.propertiesBody.appendChild(grid);
        } else {
            const zone = selected.value;
            const dimensions = zoneDimensions(zone);
            this.propertiesBody.appendChild(element(
                this.document,
                'h3',
                {},
                cleanString(zone.label, zone.zoneId)
            ));
            this.propertiesBody.appendChild(element(
                this.document,
                'p',
                { className: 'ip-flw-property-kind' },
                cleanString(zone.zoneType, 'zone')
            ));
            if (dimensions) {
                const grid = element(this.document, 'div', {
                    className: 'ip-flw-property-grid',
                });
                append(grid,
                    this._field('Zone width', 'width', dimensions.width, {
                        min: '0.01',
                        step: String(this.gridSize),
                    }),
                    this._field('Zone depth', 'depth', dimensions.depth, {
                        min: '0.01',
                        step: String(this.gridSize),
                    })
                );
                this.propertiesBody.appendChild(grid);
            }
        }
    };

    Workspace.prototype._renderToolbarState = function () {
        const hasSelection = this.state.selection.length > 0;
        const selectedPlacements = this.state.layout
            ? this.state.layout.placements.filter(function (placement) {
                return this.state.selection.includes(placement.placementId);
            }, this)
            : [];
        const hasPlacement = selectedPlacements.length > 0;
        const states = {
            rotate: !hasPlacement,
            duplicate: !hasPlacement,
            delete: !hasSelection,
            lock: !hasPlacement,
            undo: !this.state.canUndo,
            redo: !this.state.canRedo,
            save: !this.state.dirty,
        };
        Object.keys(states).forEach(function (command) {
            const button = this.toolbar.querySelector(
                '[data-command="' + command + '"]'
            );
            if (button) button.disabled = Boolean(states[command] || this.state.busy);
        }, this);
        const lock = this.toolbar.querySelector('[data-command="lock"]');
        if (lock) {
            const allLocked = selectedPlacements.length > 0
                && selectedPlacements.every(function (placement) {
                    return placement.positionMode === 'locked';
                });
            lock.setAttribute('aria-label', allLocked ? 'Unlock' : 'Lock');
            lock.setAttribute('title', (allLocked ? 'Unlock' : 'Lock') + ' (L)');
            const label = lock.querySelector('.ip-flw-command-label');
            if (label) label.textContent = allLocked ? 'Unlock' : 'Lock';
        }
    };

    Workspace.prototype._renderStatus = function () {
        if (!this.statusText || !this.state) return;
        const parts = [];
        if (!this.state.loaded) parts.push('No layout loaded');
        else if (this.state.busy) parts.push('Working');
        else if (this.state.conflict) parts.push('Revision conflict');
        else parts.push(this.state.dirty ? 'Unsaved changes' : 'Saved');
        parts.push(this.state.selection.length + ' selected');
        parts.push(this.viewMode === '3d' ? '3D view' : 'Plan view');
        parts.push(this.toolMode.replace(/-/g, ' '));
        if (this.lastError) parts.push('Error: ' + this.lastError.message);
        if (this.state.placementAlternatives) {
            parts.push('Authoritative placement preview');
        }
        this.statusText.textContent = parts.join(' | ');
        this.root.setAttribute('aria-busy', this.state.busy ? 'true' : 'false');
    };

    Workspace.prototype._syncController = function () {
        if (!this.state.layout || !this.controller) return;
        const layoutFingerprint = JSON.stringify(this.state.layout);
        if (layoutFingerprint !== this.lastLayoutFingerprint) {
            this.controller.setLayout(this.state.layout);
            this.lastLayoutFingerprint = layoutFingerprint;
        }
        const placementIds = new Set(this.state.layout.placements.map(function (item) {
            return item.placementId;
        }));
        const primary = this.state.selection.find(function (id) {
            return placementIds.has(id);
        }) || null;
        if (primary) this.controller.select(primary);
        else this.controller.clearSelection();
        if (this.topAdapter && typeof this.topAdapter.setSelections === 'function') {
            this.topAdapter.setSelections(this.state.selection);
        } else if (this.topAdapter
                && typeof this.topAdapter.setSelection === 'function') {
            this.topAdapter.setSelection(primary);
        }
        if (this.threeAdapter && typeof this.threeAdapter.setSelection === 'function') {
            this.threeAdapter.setSelection(this.state.selection.filter(function (id) {
                return placementIds.has(id);
            }));
        }
    };

    Workspace.prototype._handleSessionState = function (state) {
        if (this.destroyed) return;
        this.state = state || this.session.getState();
        this.lastError = this.state.lastError || this.lastError;
        this._syncController();
        if (this.state.ghostPlacement
                && this.state.ghostPlacement.worldPosition) {
            this._renderGhost(
                this.state.ghostPlacement.worldPosition,
                this.state.ghostPlacement.assetId
            );
        } else if (!this.state.ghostPlacement) {
            this._hideGhost();
        }
        this._renderProperties();
        this._renderToolbarState();
        this._renderCandidateControls();
        this._renderStatus();
        if (typeof this.options.onStateChange === 'function') {
            this.options.onStateChange(clone(this.state));
        }
    };

    Workspace.prototype._setError = function (error) {
        this.lastError = error instanceof Error ? error : new Error(String(error));
        this._renderStatus();
        if (typeof this.options.onError === 'function') {
            this.options.onError(this.lastError);
        }
    };

    Workspace.prototype._invoke = function (label, action) {
        const run = this.pending.then(function () {
            if (this.destroyed) throw new Error('facility workspace is destroyed');
            return action();
        }.bind(this));
        this.pending = run.then(function (result) {
            this.lastError = null;
            this._renderStatus();
            return result;
        }.bind(this), function (error) {
            this._setError(error);
            return undefined;
        }.bind(this));
        return run;
    };

    Workspace.prototype.whenIdle = function () {
        return this.pending;
    };

    Workspace.prototype._handleKeyDown = function (event) {
        if (!event || isTypingTarget(event.target)) return;
        const key = String(event.key || '').toLowerCase();
        const modifier = Boolean(event.ctrlKey || event.metaKey);
        let command = null;
        if (modifier && key === 'z' && event.shiftKey) command = 'redo';
        else if (modifier && key === 'z') command = 'undo';
        else if (modifier && key === 'y') command = 'redo';
        else if (modifier && key === 's') command = 'save';
        else if (modifier && key === 'd') command = 'duplicate';
        else if (key === 'delete' || key === 'backspace') command = 'delete';
        else if (!modifier && key === 'r') command = 'rotate';
        else if (!modifier && key === 'l') command = 'lock';
        else if (!modifier && key === 'f') command = 'fit';
        else if (!modifier && key === 'v') command = 'select';
        else if (!modifier && key === 'h') command = 'pan';
        else if (key === 'enter' && this.toolMode === 'polygon-zone') {
            if (this._finishPolygon() && typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            return;
        } else if (key === 'escape') {
            this.polygonPoints = [];
            this._cancelPointerGesture();
            if (this.state.placementAlternatives
                    && typeof this.session.dismissPlacementAlternatives
                        === 'function') {
                this.session.dismissPlacementAlternatives();
            } else {
                this._cancelGhost();
            }
            this._setToolMode('select');
            if (typeof event.preventDefault === 'function') event.preventDefault();
            return;
        }
        if (!command) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this.executeCommand(command);
    };

    Workspace.prototype.getState = function () {
        return {
            apiVersion: API_VERSION,
            destroyed: this.destroyed,
            toolMode: this.toolMode,
            viewMode: this.viewMode,
            gridSize: this.gridSize,
            session: clone(this.state),
            activeDrag: clone(this.activeDrag && this.activeDrag.payload),
            dragAdvisory: clone(this.dragAdvisory),
            polygonPointCount: this.polygonPoints.length,
            lastError: this.lastError,
        };
    };

    Workspace.prototype.destroy = function () {
        if (this.destroyed) return false;
        this.destroyed = true;
        if (this.unsubscribe) this.unsubscribe();
        this.unsubscribe = null;
        if (this.marqueeCleanup) this.marqueeCleanup();
        this.marqueeCleanup = null;
        this._releasePointerCapture();
        this._cancelAdvisoryRequest('Workspace destroyed.');
        if (this.ownsSpatialAdvisor && this.spatialAdvisor
                && typeof this.spatialAdvisor.destroy === 'function') {
            this.spatialAdvisor.destroy();
        }
        this.spatialAdvisor = null;
        this.listeners.splice(0).forEach(function (remove) { remove(); });
        if (this.ownsController && this.controller
                && typeof this.controller.dispose === 'function') {
            this.controller.dispose();
        } else {
            if (this.createdTopAdapter && this.topAdapter
                    && typeof this.topAdapter.dispose === 'function') {
                this.topAdapter.dispose();
            }
            if (this.createdThreeAdapter && this.threeAdapter
                    && typeof this.threeAdapter.dispose === 'function') {
                this.threeAdapter.dispose();
            }
        }
        this._hideGhost();
        clearElement(this.root);
        this.root.removeAttribute('data-facility-workspace');
        this.root.removeAttribute('data-tool-mode');
        this.root.removeAttribute('data-view-mode');
        return true;
    };

    function createWorkspace(options) {
        return new Workspace(options);
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        ASSET_MIME: ASSET_MIME,
        DEFAULT_GRID_SIZE: DEFAULT_GRID_SIZE,
        TOOL_MODES: TOOL_MODES,
        VIEW_MODES: VIEW_MODES,
        Workspace: Workspace,
        createWorkspace: createWorkspace,
        createAssetDragPayload: createAssetDragPayload,
        parseAssetDragPayload: parseAssetDragPayload,
        snapWorldPoint: snapWorldPoint,
        quarterTurnQuaternion: quarterTurnQuaternion,
        normalizeCatalog: normalizeCatalog,
        zoneDimensions: zoneDimensions,
    });
}));
