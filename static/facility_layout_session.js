(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilitySession = api;
}(typeof window !== 'undefined'
    ? window
    : (typeof self !== 'undefined' ? self : null), function () {
    'use strict';

    const API_VERSION = 1;
    const DEFAULT_DUPLICATE_OFFSET = Object.freeze({ x: 1, y: 0, z: 1 });
    const DEFAULT_QUATERNION = Object.freeze({ x: 0, y: 0, z: 0, w: 1 });
    const ORDINARY_OPERATION_TYPES = Object.freeze([
        'place_asset',
        'move_placement',
        'rotate_placement',
        'duplicate_placement',
        'delete_placement',
        'set_position_mode',
        'add_zone',
        'edit_zone',
        'delete_zone',
    ]);

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function deepFreeze(value) {
        if (!value || typeof value !== 'object' || Object.isFrozen(value)) {
            return value;
        }
        Object.freeze(value);
        Object.keys(value).forEach(function (key) {
            deepFreeze(value[key]);
        });
        return value;
    }

    function frozenClone(value) {
        return deepFreeze(clone(value));
    }

    function object(value, label) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new TypeError(label + ' must be an object');
        }
        return value;
    }

    function nonEmptyString(value, label) {
        if (typeof value !== 'string' || !value.trim()) {
            throw new TypeError(label + ' must be a non-empty string');
        }
        return value;
    }

    function finite(value, label) {
        if (typeof value !== 'number' || !Number.isFinite(value)) {
            throw new TypeError(label + ' must be a finite number');
        }
        return value;
    }

    function positive(value, label) {
        const result = finite(value, label);
        if (result <= 0) throw new RangeError(label + ' must be greater than zero');
        return result;
    }

    function worldPosition(value) {
        object(value, 'world position');
        return {
            x: finite(value.x, 'world position.x'),
            y: value.y === undefined ? 0 : finite(value.y, 'world position.y'),
            z: finite(value.z, 'world position.z'),
        };
    }

    function worldPoint(value) {
        object(value, 'world point');
        return {
            x: finite(value.x, 'world point.x'),
            z: finite(value.z, 'world point.z'),
        };
    }

    function quaternion(value) {
        const source = value || DEFAULT_QUATERNION;
        object(source, 'quaternion');
        const result = {
            x: finite(source.x, 'quaternion.x'),
            y: finite(source.y, 'quaternion.y'),
            z: finite(source.z, 'quaternion.z'),
            w: finite(source.w, 'quaternion.w'),
        };
        const magnitude = Math.hypot(result.x, result.y, result.z, result.w);
        if (!magnitude) throw new RangeError('quaternion cannot have zero length');
        Object.keys(result).forEach(function (key) {
            result[key] /= magnitude;
            if (Math.abs(result[key]) < 1e-12) result[key] = 0;
        });
        return result;
    }

    function multiplyQuaternion(left, right) {
        return quaternion({
            x: left.w * right.x + left.x * right.w
                + left.y * right.z - left.z * right.y,
            y: left.w * right.y - left.x * right.z
                + left.y * right.w + left.z * right.x,
            z: left.w * right.z + left.x * right.y
                - left.y * right.x + left.z * right.w,
            w: left.w * right.w - left.x * right.x
                - left.y * right.y - left.z * right.z,
        });
    }

    function quarterTurnQuaternion(turns) {
        const normalizedTurns = ((turns % 4) + 4) % 4;
        const angle = normalizedTurns * Math.PI / 2;
        return quaternion({
            x: 0,
            y: Math.sin(angle / 2),
            z: 0,
            w: Math.cos(angle / 2),
        });
    }

    function layoutFromReceipt(receipt, label) {
        object(receipt, label || 'receipt');
        const candidates = [
            receipt.layout,
            receipt.document,
            receipt.operationResult && receipt.operationResult.document,
            receipt.result && receipt.result.document,
        ];
        const layout = candidates.find(function (item) {
            return item && typeof item === 'object' && !Array.isArray(item);
        });
        if (!layout) throw new TypeError((label || 'receipt') + ' has no layout document');
        if (!Array.isArray(layout.placements) || !Array.isArray(layout.zones)) {
            throw new TypeError((label || 'receipt') + ' has an invalid layout document');
        }
        return layout;
    }

    function revisionFromReceipt(receipt, required) {
        const revision = receipt.revision
            || receipt.currentRevision
            || (receipt.result && receipt.result.revision);
        if (required) return nonEmptyString(revision, 'receipt revision');
        return revision;
    }

    function createdIdsFromReceipt(receipt) {
        const ids = receipt.createdIds
            || (receipt.operationResult && receipt.operationResult.createdIds)
            || (receipt.result && receipt.result.createdIds)
            || [];
        return Array.isArray(ids) ? ids.filter(function (id) {
            return typeof id === 'string' && id;
        }) : [];
    }

    function ordinaryOperations(value, label) {
        if (!Array.isArray(value) || !value.length) {
            throw new TypeError(label + ' must contain exact ordinary operations');
        }
        return value.map(function (operation, index) {
            object(operation, label + '[' + index + ']');
            const operationType = nonEmptyString(
                operation.op,
                label + '[' + index + '].op'
            );
            if (!ORDINARY_OPERATION_TYPES.includes(operationType)) {
                throw new TypeError(
                    label + '[' + index + '] must use an ordinary operation'
                );
            }
            return clone(operation);
        });
    }

    function candidateOperations(candidate, index) {
        const source = candidate.operations
            || candidate.exactOperations
            || (candidate.operation ? [candidate.operation] : null);
        if (source === null) return null;
        return ordinaryOperations(
            source,
            'placement candidate ' + index + ' operations'
        );
    }

    function candidateTransform(candidate, operations, layout) {
        if (candidate.transform && candidate.transform.position) {
            return clone(candidate.transform);
        }
        if (candidate.ghostPlacement
                && candidate.ghostPlacement.worldPosition) {
            return {
                position: clone(candidate.ghostPlacement.worldPosition),
                quaternion: clone(
                    candidate.ghostPlacement.quaternion
                    || DEFAULT_QUATERNION
                ),
                scale: candidate.ghostPlacement.scale || 1,
            };
        }
        for (let index = 0; index < (operations || []).length; index += 1) {
            const operation = operations[index];
            if (operation.op === 'place_asset'
                    && operation.placement
                    && operation.placement.transform) {
                return clone(operation.placement.transform);
            }
            if (operation.op === 'move_placement' && operation.position) {
                const placement = placementById(layout, operation.placementId);
                return {
                    position: clone(operation.position),
                    quaternion: clone(
                        placement
                        && placement.transform
                        && placement.transform.quaternion
                        || DEFAULT_QUATERNION
                    ),
                    scale: placement
                        && placement.transform
                        && placement.transform.scale
                        || 1,
                };
            }
            if (operation.op === 'duplicate_placement' && operation.position) {
                const source = placementById(
                    layout,
                    operation.sourcePlacementId
                );
                return {
                    position: clone(operation.position),
                    quaternion: clone(
                        operation.quaternion
                        || (source && source.transform.quaternion)
                        || DEFAULT_QUATERNION
                    ),
                    scale: source && source.transform.scale || 1,
                };
            }
        }
        throw new TypeError('placement candidate has no preview transform');
    }

    function candidateAssetIdentity(candidate, operations, layout, request) {
        if (candidate.assetId && candidate.assetDefinitionRevision) {
            return {
                assetId: candidate.assetId,
                assetDefinitionRevision: candidate.assetDefinitionRevision,
            };
        }
        for (let index = 0; index < (operations || []).length; index += 1) {
            const operation = operations[index];
            if (operation.op === 'place_asset' && operation.placement) {
                return {
                    assetId: operation.placement.assetId,
                    assetDefinitionRevision:
                        operation.placement.assetDefinitionRevision,
                };
            }
            const placementId = operation.placementId
                || operation.sourcePlacementId;
            const placement = placementId
                ? placementById(layout, placementId)
                : null;
            if (placement) {
                return {
                    assetId: placement.assetId,
                    assetDefinitionRevision:
                        placement.assetDefinitionRevision,
                };
            }
        }
        if (request && request.assetId && request.assetDefinitionRevision) {
            return {
                assetId: request.assetId,
                assetDefinitionRevision: request.assetDefinitionRevision,
            };
        }
        throw new TypeError('placement candidate has no asset identity');
    }

    function placementCandidateRequest(value) {
        const container = object(value, 'placement candidate request');
        const source = container.request && typeof container.request === 'object'
            ? object(container.request, 'placement candidate request.request')
            : container;
        const request = {
            assetId: nonEmptyString(source.assetId, 'candidate request assetId'),
            assetDefinitionRevision: nonEmptyString(
                source.assetDefinitionRevision,
                'candidate request assetDefinitionRevision'
            ),
            requestedPosition: worldPosition(source.requestedPosition),
        };
        [
            'requestedQuaternion',
            'targetPlacementId',
            'enabledFamilies',
            'maximumCandidates',
            'positionMode',
            'metadata',
        ].forEach(function (key) {
            if (source[key] !== undefined) request[key] = clone(source[key]);
        });
        return request;
    }

    function candidateSafetyStatus(candidate) {
        if (candidate.safetyStatus === 'safe'
                || candidate.safetyStatus === 'unverified'
                || candidate.safetyStatus === 'unsafe') {
            return candidate.safetyStatus;
        }
        if (candidate.valid === false) return 'unsafe';
        return candidate.safe === true ? 'safe' : 'unverified';
    }

    function requestFromAlternatives(receipt, request) {
        if (request) return placementCandidateRequest(request);
        if (receipt.request) return placementCandidateRequest(receipt.request);
        if (receipt.assetId && receipt.assetDefinitionRevision
                && receipt.requestedPosition) {
            return placementCandidateRequest(receipt);
        }
        return null;
    }

    function normalizePlacementAlternatives(
        receipt,
        expectedRevision,
        layout,
        request
    ) {
        object(receipt, 'placement alternatives receipt');
        const revision = nonEmptyString(
            receipt.baseRevision || receipt.revision,
            'placement alternatives baseRevision'
        );
        if (revision !== expectedRevision) {
            const error = new Error('Placement alternatives are stale');
            error.code = 'stale_revision';
            error.currentRevision = expectedRevision;
            error.details = {
                candidateRevision: revision,
                currentRevision: expectedRevision,
            };
            throw error;
        }
        const rawCandidates = receipt.candidates || receipt.alternatives;
        if (!Array.isArray(rawCandidates) || !rawCandidates.length) {
            throw new TypeError(
                'placement alternatives receipt requires candidates'
            );
        }
        const normalizedRequest = requestFromAlternatives(receipt, request);
        const candidates = rawCandidates.map(function (raw, index) {
            const candidate = object(raw, 'placement candidate ' + index);
            const operations = candidateOperations(candidate, index);
            const identity = candidateAssetIdentity(
                candidate,
                operations,
                layout,
                normalizedRequest
            );
            const safetyStatus = candidateSafetyStatus(candidate);
            return {
                candidateId: nonEmptyString(
                    candidate.candidateId || candidate.alternativeId,
                    'placement candidate ' + index + ' candidateId'
                ),
                assetId: nonEmptyString(identity.assetId, 'candidate assetId'),
                assetDefinitionRevision: nonEmptyString(
                    identity.assetDefinitionRevision,
                    'candidate assetDefinitionRevision'
                ),
                family: typeof candidate.family === 'string'
                    ? candidate.family : '',
                summary: typeof candidate.summary === 'string'
                    ? candidate.summary : '',
                transform: candidateTransform(candidate, operations, layout),
                valid: safetyStatus !== 'unsafe'
                    && candidate.valid !== false,
                safe: safetyStatus === 'safe',
                safetyStatus: safetyStatus,
                findings: clone(candidate.findings || []),
                metrics: clone(candidate.metrics || {}),
                beforeAfterMetrics: clone(candidate.beforeAfterMetrics || {}),
                selectionPolicy: clone(candidate.selectionPolicy),
                operations: operations,
            };
        });
        const candidateIds = new Set(candidates.map(function (candidate) {
            return candidate.candidateId;
        }));
        if (candidateIds.size !== candidates.length) {
            throw new TypeError(
                'placement alternatives require unique candidate IDs'
            );
        }
        const selectedId = receipt.selectedCandidateId
            || receipt.selectedAlternativeId;
        const selectedIndex = Math.max(0, candidates.findIndex(function (item) {
            return item.candidateId === selectedId;
        }));
        return {
            authority: 'server-authoritative',
            authoritative: true,
            baseRevision: revision,
            request: normalizedRequest,
            layoutFingerprint: receipt.layoutFingerprint || null,
            obstacleFingerprint: receipt.obstacleFingerprint || null,
            spatialEngineVersion: receipt.spatialEngineVersion || null,
            candidatePolicyVersion: receipt.candidatePolicyVersion || null,
            selectedIndex: selectedIndex,
            candidates: candidates,
        };
    }

    function normalizePlacementCandidatePreview(
        receipt,
        expectedRevision,
        expectedCandidateId
    ) {
        object(receipt, 'placement candidate preview receipt');
        const revision = nonEmptyString(
            receipt.baseRevision || receipt.revision,
            'placement candidate preview baseRevision'
        );
        if (revision !== expectedRevision) {
            const error = new Error('Placement candidate preview is stale');
            error.code = 'stale_revision';
            error.currentRevision = expectedRevision;
            error.details = {
                candidateRevision: revision,
                currentRevision: expectedRevision,
            };
            throw error;
        }
        const candidate = object(
            receipt.candidate,
            'placement candidate preview candidate'
        );
        const candidateId = nonEmptyString(
            candidate.candidateId || receipt.candidateId,
            'placement candidate preview candidateId'
        );
        if (candidateId !== expectedCandidateId) {
            const error = new Error(
                'Placement candidate preview does not match the selection'
            );
            error.code = 'spatial_candidate_stale';
            error.details = {
                expectedCandidateId: expectedCandidateId,
                candidateId: candidateId,
            };
            throw error;
        }
        const safetyStatus = candidateSafetyStatus(candidate);
        if (safetyStatus === 'unsafe' || candidate.valid === false) {
            const error = new Error('Invalid placement cannot be accepted');
            error.code = 'spatial_validation_failed';
            error.details = {
                candidateId: candidateId,
                safetyStatus: safetyStatus,
                findings: clone(candidate.findings || []),
            };
            throw error;
        }
        object(receipt.preview, 'placement candidate authoritative preview');
        layoutFromReceipt(
            receipt.preview,
            'placement candidate authoritative preview'
        );
        const source = receipt.operations
            || receipt.exactOperations
            || (receipt.operation ? [receipt.operation] : null);
        return {
            candidateId: candidateId,
            safetyStatus: safetyStatus,
            findings: clone(candidate.findings || []),
            metrics: clone(candidate.metrics || {}),
            operations: ordinaryOperations(
                source,
                'placement candidate preview operations'
            ),
            selectionPolicy: clone(
                receipt.selectionPolicy || candidate.selectionPolicy
            ),
        };
    }

    function selectedIdsInLayout(layout, selectedIds) {
        const available = new Set();
        layout.placements.forEach(function (placement) {
            available.add(placement.placementId);
        });
        layout.zones.forEach(function (zone) {
            available.add(zone.zoneId);
        });
        return selectedIds.filter(function (id) {
            return available.has(id);
        });
    }

    function layoutObjectIds(layout) {
        const result = new Set();
        if (!layout) return result;
        (layout.placements || []).forEach(function (placement) {
            if (placement && placement.placementId) result.add(placement.placementId);
        });
        (layout.zones || []).forEach(function (zone) {
            if (zone && zone.zoneId) result.add(zone.zoneId);
        });
        return result;
    }

    function placementById(layout, placementId) {
        return layout.placements.find(function (placement) {
            return placement.placementId === placementId;
        }) || null;
    }

    function zoneById(layout, zoneId) {
        return layout.zones.find(function (zone) {
            return zone.zoneId === zoneId;
        }) || null;
    }

    function flattenBatches(batches, cursor) {
        const operations = [];
        batches.slice(0, cursor).forEach(function (batch) {
            batch.operations.forEach(function (operation) {
                operations.push(clone(operation));
            });
        });
        return operations;
    }

    function conflictDetails(error) {
        if (!error || typeof error !== 'object') return null;
        const details = error.details
            || (error.body && error.body.details)
            || (error.response && error.response.details)
            || {};
        const code = error.code
            || (error.body && error.body.code)
            || (error.response && error.response.code);
        const currentRevision = error.currentRevision || details.currentRevision;
        const stale = error.status === 409
            || code === 'revision_conflict'
            || code === 'stale_revision'
            || Boolean(currentRevision);
        return stale ? {
            code: code || 'revision_conflict',
            currentRevision: currentRevision || null,
        } : null;
    }

    function normalizeZoneOptions(options) {
        const source = options || {};
        return {
            zoneType: source.zoneType || 'workcell',
            label: source.label || 'New zone',
            floorElevation: source.floorElevation === undefined
                ? 0
                : finite(source.floorElevation, 'floorElevation'),
            anchors: clone(source.anchors || []),
            evidence: clone(source.evidence || []),
        };
    }

    function rectangleBoundary(start, end) {
        const first = worldPoint(start);
        const second = worldPoint(end);
        const minX = Math.min(first.x, second.x);
        const maxX = Math.max(first.x, second.x);
        const minZ = Math.min(first.z, second.z);
        const maxZ = Math.max(first.z, second.z);
        if (maxX === minX || maxZ === minZ) {
            throw new RangeError('rectangle zone must have positive width and depth');
        }
        return [
            { x: minX, z: minZ },
            { x: maxX, z: minZ },
            { x: maxX, z: maxZ },
            { x: minX, z: maxZ },
        ];
    }

    function polygonBoundary(points) {
        if (!Array.isArray(points) || points.length < 3) {
            throw new RangeError('polygon zone requires at least three points');
        }
        const boundary = points.map(worldPoint);
        const area = boundary.reduce(function (sum, point, index) {
            const next = boundary[(index + 1) % boundary.length];
            return sum + point.x * next.z - next.x * point.z;
        }, 0) / 2;
        if (!area) throw new RangeError('polygon zone must have positive area');
        return area > 0 ? boundary : boundary.slice().reverse();
    }

    function resizedZoneBoundary(boundary, width, depth) {
        if (!Array.isArray(boundary) || boundary.length < 3) {
            throw new TypeError('zone boundary must contain at least three points');
        }
        const points = boundary.map(worldPoint);
        const bounds = points.reduce(function (result, point) {
            result.minX = Math.min(result.minX, point.x);
            result.maxX = Math.max(result.maxX, point.x);
            result.minZ = Math.min(result.minZ, point.z);
            result.maxZ = Math.max(result.maxZ, point.z);
            return result;
        }, {
            minX: Infinity,
            maxX: -Infinity,
            minZ: Infinity,
            maxZ: -Infinity,
        });
        const currentWidth = bounds.maxX - bounds.minX;
        const currentDepth = bounds.maxZ - bounds.minZ;
        if (!(currentWidth > 0) || !(currentDepth > 0)) {
            throw new RangeError('zone boundary must have positive width and depth');
        }
        const requestedWidth = positive(width, 'zone width');
        const requestedDepth = positive(depth, 'zone depth');
        const center = {
            x: (bounds.minX + bounds.maxX) / 2,
            z: (bounds.minZ + bounds.maxZ) / 2,
        };
        const scaleX = requestedWidth / currentWidth;
        const scaleZ = requestedDepth / currentDepth;
        return points.map(function (point) {
            return {
                x: center.x + (point.x - center.x) * scaleX,
                z: center.z + (point.z - center.z) * scaleZ,
            };
        });
    }

    function createSession(options) {
        const config = options || {};
        if (typeof config.previewOperations !== 'function') {
            throw new TypeError('previewOperations transport is required');
        }
        if (typeof config.applyOperations !== 'function') {
            throw new TypeError('applyOperations transport is required');
        }

        let baseLayout = null;
        let baseRevision = null;
        let draftLayout = null;
        let batches = [];
        let cursor = 0;
        let selectedIds = [];
        let camera = null;
        let ghost = null;
        let placementAlternatives = null;
        let busy = false;
        let conflict = null;
        let lastError = null;
        const listeners = new Set();

        function requireLoaded() {
            if (!baseLayout) throw new Error('facility layout session is not loaded');
        }

        function notify() {
            const snapshot = getState();
            listeners.forEach(function (listener) {
                listener(snapshot);
            });
        }

        function setBusy(value) {
            busy = value;
            notify();
        }

        function assertIdle() {
            if (busy) {
                const error = new Error('facility layout session is busy');
                error.code = 'session_busy';
                throw error;
            }
        }

        function currentOperations() {
            return flattenBatches(batches, cursor);
        }

        function installReceipt(receipt, requireRevision) {
            const layout = frozenClone(layoutFromReceipt(receipt, 'layout receipt'));
            const revision = revisionFromReceipt(receipt, requireRevision);
            baseLayout = layout;
            baseRevision = revision || baseRevision;
            draftLayout = layout;
            batches = [];
            cursor = 0;
            selectedIds = selectedIdsInLayout(layout, selectedIds);
            ghost = null;
            placementAlternatives = null;
            conflict = null;
            lastError = null;
        }

        async function preview(operations) {
            const receipt = await config.previewOperations({
                baseRevision: baseRevision,
                operations: clone(operations),
            });
            return {
                receipt: receipt,
                layout: frozenClone(layoutFromReceipt(receipt, 'preview receipt')),
                createdIds: createdIdsFromReceipt(receipt),
            };
        }

        async function commitGesture(label, operations, selectionPolicy) {
            requireLoaded();
            assertIdle();
            if (!Array.isArray(operations) || !operations.length) {
                return getState();
            }
            const batch = deepFreeze({
                label: nonEmptyString(label, 'gesture label'),
                operations: frozenClone(operations),
            });
            const candidateBatches = batches.slice(0, cursor).concat([batch]);
            const candidateOperations = flattenBatches(
                candidateBatches,
                candidateBatches.length
            );
            const previousObjectIds = layoutObjectIds(draftLayout);
            setBusy(true);
            try {
                const result = await preview(candidateOperations);
                if (result.receipt.changed === false) {
                    draftLayout = result.layout;
                    selectedIds = selectedIdsInLayout(
                        draftLayout,
                        selectedIds
                    );
                    ghost = null;
                    placementAlternatives = null;
                    conflict = null;
                    lastError = null;
                    return getState();
                }
                batches = candidateBatches;
                cursor = batches.length;
                draftLayout = result.layout;
                conflict = null;
                lastError = null;
                if (selectionPolicy === 'created') {
                    selectedIds = selectedIdsInLayout(
                        draftLayout,
                        result.createdIds.filter(function (identifier) {
                            return !previousObjectIds.has(identifier);
                        })
                    );
                } else if (selectionPolicy === 'preserve') {
                    selectedIds = selectedIdsInLayout(draftLayout, selectedIds);
                } else if (Array.isArray(selectionPolicy)) {
                    selectedIds = selectedIdsInLayout(
                        draftLayout,
                        selectionPolicy
                    );
                }
                ghost = null;
                placementAlternatives = null;
            } catch (error) {
                const stale = conflictDetails(error);
                if (stale) conflict = stale;
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        async function recompute(targetCursor) {
            requireLoaded();
            assertIdle();
            const normalizedCursor = Math.max(0, Math.min(batches.length, targetCursor));
            if (normalizedCursor === cursor) return getState();
            setBusy(true);
            try {
                const result = await preview(flattenBatches(batches, normalizedCursor));
                cursor = normalizedCursor;
                draftLayout = result.layout;
                selectedIds = selectedIdsInLayout(draftLayout, selectedIds);
                ghost = null;
                placementAlternatives = null;
                conflict = null;
                lastError = null;
            } catch (error) {
                const stale = conflictDetails(error);
                if (stale) conflict = stale;
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        function getState() {
            return {
                apiVersion: API_VERSION,
                loaded: Boolean(baseLayout),
                baseRevision: baseRevision,
                baseLayout: clone(baseLayout),
                layout: clone(draftLayout),
                operations: currentOperations(),
                history: batches.map(function (batch, index) {
                    return {
                        label: batch.label,
                        operationCount: batch.operations.length,
                        applied: index < cursor,
                    };
                }),
                historyCursor: cursor,
                canUndo: cursor > 0 && !busy,
                canRedo: cursor < batches.length && !busy,
                dirty: cursor > 0,
                busy: busy,
                conflict: clone(conflict),
                selection: selectedIds.slice(),
                camera: clone(camera),
                ghostPlacement: clone(ghost),
                placementAlternatives: clone(placementAlternatives),
                lastError: lastError,
            };
        }

        function load(receipt) {
            assertIdle();
            selectedIds = [];
            camera = null;
            installReceipt(receipt, true);
            notify();
            return getState();
        }

        async function reload(receipt) {
            assertIdle();
            if (receipt) return load(receipt);
            if (typeof config.reloadLayout !== 'function') {
                throw new Error('reloadLayout transport is not configured');
            }
            setBusy(true);
            try {
                const latest = await config.reloadLayout();
                selectedIds = [];
                installReceipt(latest, true);
            } catch (error) {
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        function subscribe(listener) {
            if (typeof listener !== 'function') {
                throw new TypeError('session listener must be a function');
            }
            listeners.add(listener);
            return function () {
                listeners.delete(listener);
            };
        }

        function setCameraState(nextCamera) {
            camera = nextCamera === null ? null : frozenClone(object(nextCamera, 'camera'));
            notify();
            return clone(camera);
        }

        function select(id, selectionOptions) {
            requireLoaded();
            const value = nonEmptyString(id, 'selection ID');
            const opts = selectionOptions || {};
            const exists = selectedIdsInLayout(draftLayout, [value]).length > 0;
            if (!exists) return getState();
            if (opts.toggle) {
                selectedIds = selectedIds.includes(value)
                    ? selectedIds.filter(function (item) { return item !== value; })
                    : selectedIds.concat([value]);
            } else if (opts.additive) {
                if (!selectedIds.includes(value)) selectedIds = selectedIds.concat([value]);
            } else {
                selectedIds = [value];
            }
            notify();
            return getState();
        }

        function selectMany(ids, selectionOptions) {
            requireLoaded();
            if (!Array.isArray(ids)) throw new TypeError('selection IDs must be an array');
            const valid = selectedIdsInLayout(draftLayout, ids.filter(function (id) {
                return typeof id === 'string' && id;
            }));
            if (selectionOptions && selectionOptions.additive) {
                selectedIds = Array.from(new Set(selectedIds.concat(valid)));
            } else {
                selectedIds = Array.from(new Set(valid));
            }
            notify();
            return getState();
        }

        function clearSelection() {
            selectedIds = [];
            notify();
            return getState();
        }

        function beginGhostPlacement(asset) {
            requireLoaded();
            object(asset, 'ghost asset');
            placementAlternatives = null;
            ghost = {
                assetId: nonEmptyString(asset.assetId, 'assetId'),
                assetDefinitionRevision: nonEmptyString(
                    asset.assetDefinitionRevision,
                    'assetDefinitionRevision'
                ),
                worldPosition: asset.worldPosition
                    ? worldPosition(asset.worldPosition)
                    : null,
                valid: asset.valid !== false,
                metadata: clone(asset.metadata || {}),
            };
            notify();
            return clone(ghost);
        }

        function updateGhostPlacement(position, valid) {
            if (!ghost) throw new Error('ghost placement is not active');
            ghost = {
                ...ghost,
                worldPosition: worldPosition(position),
                valid: valid !== false,
            };
            notify();
            return clone(ghost);
        }

        function cancelGhostPlacement() {
            ghost = null;
            placementAlternatives = null;
            notify();
            return getState();
        }

        function alternativeGhost(proposal) {
            const candidate = proposal.candidates[proposal.selectedIndex];
            return {
                assetId: candidate.assetId,
                assetDefinitionRevision: candidate.assetDefinitionRevision,
                worldPosition: worldPosition(candidate.transform.position),
                quaternion: clone(
                    candidate.transform.quaternion || DEFAULT_QUATERNION
                ),
                scale: candidate.transform.scale || 1,
                valid: candidate.valid !== false,
                metadata: {
                    previewKind: 'authoritative-placement-candidate',
                    authority: 'server-authoritative',
                    candidateId: candidate.candidateId,
                    candidateIndex: proposal.selectedIndex,
                    candidateCount: proposal.candidates.length,
                    family: candidate.family,
                    summary: candidate.summary,
                    safetyStatus: candidate.safetyStatus,
                    findings: clone(candidate.findings),
                    metrics: clone(candidate.metrics),
                },
            };
        }

        function installPlacementAlternatives(receipt, request) {
            requireLoaded();
            assertIdle();
            placementAlternatives = deepFreeze(
                normalizePlacementAlternatives(
                    receipt,
                    baseRevision,
                    draftLayout,
                    request
                )
            );
            ghost = deepFreeze(alternativeGhost(placementAlternatives));
            conflict = null;
            lastError = null;
            notify();
            return getState();
        }

        async function requestPlacementAlternatives(request) {
            requireLoaded();
            assertIdle();
            if (typeof config.placementCandidates !== 'function') {
                throw new Error(
                    'placementCandidates transport is not configured'
                );
            }
            const value = object(
                request,
                'placement alternatives request'
            );
            const signal = value.signal;
            const candidateRequest = placementCandidateRequest(value);
            const payload = {
                baseRevision: baseRevision,
                operations: currentOperations(),
                request: candidateRequest,
            };
            setBusy(true);
            try {
                const receipt = await config.placementCandidates(
                    payload,
                    signal ? { signal: signal } : undefined
                );
                placementAlternatives = deepFreeze(
                    normalizePlacementAlternatives(
                        receipt,
                        baseRevision,
                        draftLayout,
                        candidateRequest
                    )
                );
                ghost = deepFreeze(alternativeGhost(placementAlternatives));
                conflict = null;
                lastError = null;
            } catch (error) {
                const stale = conflictDetails(error);
                if (stale) conflict = stale;
                placementAlternatives = null;
                ghost = null;
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        function cyclePlacementAlternative(offset) {
            requireLoaded();
            assertIdle();
            if (!placementAlternatives) {
                throw new Error('placement alternatives are not active');
            }
            const delta = offset === undefined ? 1 : finite(
                offset,
                'placement alternative offset'
            );
            if (!Number.isInteger(delta)) {
                throw new TypeError(
                    'placement alternative offset must be an integer'
                );
            }
            const count = placementAlternatives.candidates.length;
            const nextIndex = (
                (placementAlternatives.selectedIndex + delta) % count + count
            ) % count;
            placementAlternatives = deepFreeze({
                ...placementAlternatives,
                selectedIndex: nextIndex,
            });
            ghost = deepFreeze(alternativeGhost(placementAlternatives));
            notify();
            return getState();
        }

        function dismissPlacementAlternatives() {
            placementAlternatives = null;
            if (ghost && ghost.metadata
                    && ghost.metadata.previewKind
                        === 'authoritative-placement-candidate') {
                ghost = null;
            }
            notify();
            return getState();
        }

        async function acceptPlacementAlternative(options) {
            requireLoaded();
            assertIdle();
            if (!placementAlternatives) {
                throw new Error('placement alternatives are not active');
            }
            if (placementAlternatives.baseRevision !== baseRevision) {
                const error = new Error('Placement alternatives are stale');
                error.code = 'stale_revision';
                error.currentRevision = baseRevision;
                throw error;
            }
            const proposal = placementAlternatives;
            const candidate = placementAlternatives.candidates[
                placementAlternatives.selectedIndex
            ];
            if (candidate.safetyStatus === 'unsafe'
                    || candidate.valid === false) {
                const error = new Error('Invalid placement cannot be accepted');
                error.code = 'spatial_validation_failed';
                error.details = {
                    candidateId: candidate.candidateId,
                    safetyStatus: candidate.safetyStatus,
                    findings: clone(candidate.findings),
                };
                throw error;
            }
            let operations = candidate.operations;
            let selectionPolicy = candidate.selectionPolicy;
            if (proposal.request
                    && typeof config.placementCandidatePreview === 'function') {
                const requestOptions = options || {};
                let receipt;
                setBusy(true);
                try {
                    receipt = await config.placementCandidatePreview({
                        baseRevision: baseRevision,
                        operations: currentOperations(),
                        request: clone(proposal.request),
                        candidateId: candidate.candidateId,
                    }, requestOptions.signal
                        ? { signal: requestOptions.signal }
                        : undefined);
                    const resolved = normalizePlacementCandidatePreview(
                        receipt,
                        baseRevision,
                        candidate.candidateId
                    );
                    if (placementAlternatives !== proposal
                            || proposal.selectedIndex
                                !== placementAlternatives.selectedIndex) {
                        const error = new Error(
                            'Placement alternative changed during preview'
                        );
                        error.name = 'AbortError';
                        error.code = 'placement_candidate_preview_superseded';
                        throw error;
                    }
                    operations = resolved.operations;
                    if (resolved.selectionPolicy !== undefined) {
                        selectionPolicy = resolved.selectionPolicy;
                    }
                    conflict = null;
                    lastError = null;
                } catch (error) {
                    const stale = conflictDetails(error);
                    if (stale) conflict = stale;
                    lastError = error;
                    throw error;
                } finally {
                    setBusy(false);
                }
            }
            if (!operations) {
                throw new Error(
                    'placementCandidatePreview transport is required '
                    + 'to accept this alternative'
                );
            }
            const exactOperations = ordinaryOperations(
                operations,
                'accepted placement candidate operations'
            );
            const creates = exactOperations.some(function (operation) {
                return operation.op === 'place_asset'
                    || operation.op === 'duplicate_placement';
            });
            selectionPolicy = selectionPolicy !== undefined
                ? selectionPolicy
                : (creates ? 'created' : 'preserve');
            await commitGesture(
                'Accept placement alternative',
                exactOperations,
                selectionPolicy
            );
            placementAlternatives = null;
            ghost = null;
            notify();
            return getState();
        }

        async function commitGhostPlacement(options) {
            if (!ghost) throw new Error('ghost placement is not active');
            if (!ghost.valid || !ghost.worldPosition) {
                ghost = null;
                notify();
                return getState();
            }
            const request = {
                assetId: ghost.assetId,
                assetDefinitionRevision: ghost.assetDefinitionRevision,
                worldPosition: ghost.worldPosition,
                metadata: ghost.metadata,
                ...(options || {}),
            };
            try {
                return await placeAsset(request);
            } finally {
                if (ghost) {
                    ghost = null;
                    notify();
                }
            }
        }

        async function placeAsset(request) {
            object(request, 'placement request');
            const position = worldPosition(request.worldPosition || request.position);
            const placement = {
                assetId: nonEmptyString(request.assetId, 'assetId'),
                assetDefinitionRevision: nonEmptyString(
                    request.assetDefinitionRevision,
                    'assetDefinitionRevision'
                ),
                transform: {
                    position: position,
                    quaternion: quaternion(request.quaternion),
                    scale: request.scale === undefined
                        ? 1
                        : positive(request.scale, 'placement scale'),
                },
                positionMode: request.positionMode || 'manual',
                snapRelationship: request.snapRelationship === undefined
                    ? null
                    : clone(request.snapRelationship),
                metadata: clone(request.metadata || {}),
            };
            if (!['auto', 'manual', 'locked'].includes(placement.positionMode)) {
                throw new TypeError('positionMode must be auto, manual, or locked');
            }
            return commitGesture('Place asset', [{
                op: 'place_asset',
                placement: placement,
            }], 'created');
        }

        function selectedPlacements() {
            requireLoaded();
            return selectedIds.map(function (id) {
                return placementById(draftLayout, id);
            }).filter(Boolean);
        }

        async function moveSelected(delta) {
            const movement = worldPosition(delta);
            const placements = selectedPlacements();
            const operations = placements.map(function (placement) {
                const current = placement.transform.position;
                return {
                    op: 'move_placement',
                    placementId: placement.placementId,
                    position: {
                        x: current.x + movement.x,
                        y: current.y + movement.y,
                        z: current.z + movement.z,
                    },
                    movementKind: 'user',
                };
            });
            return commitGesture('Move selection', operations, 'preserve');
        }

        async function rotateSelected90(turns) {
            const count = turns === undefined ? 1 : finite(turns, 'quarter turns');
            if (!Number.isInteger(count)) {
                throw new TypeError('quarter turns must be an integer');
            }
            const rotation = quarterTurnQuaternion(count);
            const operations = selectedPlacements().map(function (placement) {
                return {
                    op: 'rotate_placement',
                    placementId: placement.placementId,
                    quaternion: multiplyQuaternion(
                        rotation,
                        quaternion(placement.transform.quaternion)
                    ),
                    movementKind: 'user',
                };
            });
            return commitGesture('Rotate selection', operations, 'preserve');
        }

        async function duplicateSelected(offset) {
            const delta = worldPosition(offset || DEFAULT_DUPLICATE_OFFSET);
            const operations = selectedPlacements().map(function (placement) {
                const current = placement.transform.position;
                return {
                    op: 'duplicate_placement',
                    sourcePlacementId: placement.placementId,
                    position: {
                        x: current.x + delta.x,
                        y: current.y + delta.y,
                        z: current.z + delta.z,
                    },
                    positionMode: 'manual',
                };
            });
            return commitGesture('Duplicate selection', operations, 'created');
        }

        async function deleteSelected() {
            requireLoaded();
            const placementIds = selectedIds.filter(function (id) {
                return Boolean(placementById(draftLayout, id));
            });
            const zoneIds = selectedIds.filter(function (id) {
                return Boolean(zoneById(draftLayout, id));
            });
            const operations = placementIds.map(function (placementId) {
                return { op: 'delete_placement', placementId: placementId };
            }).concat(zoneIds.map(function (zoneId) {
                return { op: 'delete_zone', zoneId: zoneId };
            }));
            return commitGesture('Delete selection', operations, []);
        }

        async function setSelectedLocked(locked) {
            const positionMode = locked ? 'locked' : 'manual';
            const operations = selectedPlacements().map(function (placement) {
                return {
                    op: 'set_position_mode',
                    placementId: placement.placementId,
                    positionMode: positionMode,
                };
            });
            return commitGesture(locked ? 'Lock selection' : 'Unlock selection',
                operations, 'preserve');
        }

        async function createRectangleZone(start, end, options) {
            const normalized = normalizeZoneOptions(options);
            return commitGesture('Create rectangle zone', [{
                op: 'add_zone',
                zone: {
                    zoneType: normalized.zoneType,
                    label: normalized.label,
                    boundary: rectangleBoundary(start, end),
                    floorElevation: normalized.floorElevation,
                    anchors: normalized.anchors,
                    evidence: normalized.evidence,
                },
            }], 'created');
        }

        async function createPolygonZone(points, options) {
            const normalized = normalizeZoneOptions(options);
            return commitGesture('Create polygon zone', [{
                op: 'add_zone',
                zone: {
                    zoneType: normalized.zoneType,
                    label: normalized.label,
                    boundary: polygonBoundary(points),
                    floorElevation: normalized.floorElevation,
                    anchors: normalized.anchors,
                    evidence: normalized.evidence,
                },
            }], 'created');
        }

        async function editZoneDimensions(zoneId, dimensions) {
            requireLoaded();
            const id = nonEmptyString(zoneId, 'zoneId');
            const zone = zoneById(draftLayout, id);
            if (!zone) throw new Error("unknown zone '" + id + "'");
            object(dimensions, 'zone dimensions');
            return commitGesture('Resize zone', [{
                op: 'edit_zone',
                zoneId: id,
                patch: {
                    boundary: resizedZoneBoundary(
                        zone.boundary,
                        dimensions.width,
                        dimensions.depth
                    ),
                },
            }], [id]);
        }

        async function undo() {
            return recompute(cursor - 1);
        }

        async function redo() {
            return recompute(cursor + 1);
        }

        async function save() {
            requireLoaded();
            assertIdle();
            if (!cursor) return getState();
            const operations = currentOperations();
            let savedReceipt = null;
            setBusy(true);
            try {
                savedReceipt = await config.applyOperations({
                    baseRevision: baseRevision,
                    operations: clone(operations),
                });
                const savedSelection = selectedIds.slice();
                installReceipt(savedReceipt, true);
                selectedIds = selectedIdsInLayout(draftLayout, savedSelection);
            } catch (error) {
                const stale = conflictDetails(error);
                if (stale) conflict = stale;
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return {
                state: getState(),
                receipt: clone(savedReceipt),
            };
        }

        function discard() {
            requireLoaded();
            assertIdle();
            draftLayout = baseLayout;
            batches = [];
            cursor = 0;
            selectedIds = selectedIdsInLayout(draftLayout, selectedIds);
            ghost = null;
            placementAlternatives = null;
            conflict = null;
            lastError = null;
            notify();
            return getState();
        }

        return Object.freeze({
            apiVersion: API_VERSION,
            load: load,
            reload: reload,
            discard: discard,
            discardAndReload: reload,
            getState: getState,
            getOperations: currentOperations,
            subscribe: subscribe,
            setCameraState: setCameraState,
            select: select,
            selectMany: selectMany,
            clearSelection: clearSelection,
            beginGhostPlacement: beginGhostPlacement,
            updateGhostPlacement: updateGhostPlacement,
            cancelGhostPlacement: cancelGhostPlacement,
            commitGhostPlacement: commitGhostPlacement,
            installPlacementAlternatives: installPlacementAlternatives,
            requestPlacementAlternatives: requestPlacementAlternatives,
            cyclePlacementAlternative: cyclePlacementAlternative,
            dismissPlacementAlternatives: dismissPlacementAlternatives,
            acceptPlacementAlternative: acceptPlacementAlternative,
            placeAsset: placeAsset,
            moveSelected: moveSelected,
            rotateSelected90: rotateSelected90,
            duplicateSelected: duplicateSelected,
            deleteSelected: deleteSelected,
            lockSelected: function () { return setSelectedLocked(true); },
            unlockSelected: function () { return setSelectedLocked(false); },
            createRectangleZone: createRectangleZone,
            createPolygonZone: createPolygonZone,
            editZoneDimensions: editZoneDimensions,
            undo: undo,
            redo: redo,
            save: save,
        });
    }

    return Object.freeze({
        apiVersion: API_VERSION,
        createSession: createSession,
    });
}));
