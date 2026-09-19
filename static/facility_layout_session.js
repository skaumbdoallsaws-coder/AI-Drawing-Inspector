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
    const DESIGN_EDITOR_FRAME_VERSION = 'facility-design-editor-frame-v1';
    const DEFAULT_DUPLICATE_OFFSET = Object.freeze({ x: 1, y: 0, z: 1 });
    const DEFAULT_QUATERNION = Object.freeze({ x: 0, y: 0, z: 0, w: 1 });
    const ORDINARY_OPERATION_TYPES = Object.freeze([
        'place_asset',
        'move_placement',
        'rotate_placement',
        'duplicate_placement',
        'delete_placement',
        'set_position_mode',
        'set_snap_relationship',
        'add_zone',
        'edit_zone',
        'delete_zone',
        'add_floor_marking',
        'edit_floor_marking',
        'delete_floor_marking',
        'add_aisle',
        'edit_aisle',
        'edit_route',
        'delete_route',
        'set_facility_navigation',
        'clear_layout_contents',
    ]);
    let idempotencySequence = 0;
    let stackSequence = 0;
    let placementSequence = 0;
    let attachmentSequence = 0;
    let patternSequence = 0;
    let editorGenerationSequence = 0;

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

    function timestamp(value, label) {
        if (typeof value === 'number') return positive(value, label);
        return nonEmptyString(value, label);
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

    function yawQuaternion(degrees) {
        const angle = finite(degrees, 'rotation degrees') * Math.PI / 180;
        return quaternion({
            x: 0,
            y: Math.sin(angle / 2),
            z: 0,
            w: Math.cos(angle / 2),
        });
    }

    function quaternionYawDegrees(value) {
        const q = quaternion(value);
        let result = Math.atan2(
            2 * (q.w * q.y + q.x * q.z),
            1 - 2 * (q.y * q.y + q.z * q.z)
        ) * 180 / Math.PI;
        result %= 360;
        if (result < 0) result += 360;
        return result;
    }

    function rotateFloorVector(value, degrees) {
        const point = value || {};
        const radians = finite(degrees, 'rotation degrees') * Math.PI / 180;
        const cosine = Math.cos(radians);
        const sine = Math.sin(radians);
        const result = {
            x: finite(point.x, 'floor vector.x') * cosine
                + finite(point.z, 'floor vector.z') * sine,
            z: -finite(point.x, 'floor vector.x') * sine
                + finite(point.z, 'floor vector.z') * cosine,
        };
        if (Math.abs(result.x) < 1e-12) result.x = 0;
        if (Math.abs(result.z) < 1e-12) result.z = 0;
        return result;
    }

    function transformFloorPoint(value, sourceAnchor, targetAnchor, degrees) {
        const point = worldPoint(value);
        const source = worldPoint(sourceAnchor);
        const target = worldPoint(targetAnchor);
        const rotated = rotateFloorVector({
            x: point.x - source.x,
            z: point.z - source.z,
        }, degrees);
        return {
            x: target.x + rotated.x,
            z: target.z + rotated.z,
        };
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

    function canonicalValue(value) {
        if (Array.isArray(value)) return value.map(canonicalValue);
        if (!value || typeof value !== 'object') return value;
        const result = {};
        Object.keys(value).sort().forEach(function (key) {
            result[key] = canonicalValue(value[key]);
        });
        return result;
    }

    function sha256Hex(value) {
        let text = unescape(encodeURIComponent(String(value)));
        const maxWord = Math.pow(2, 32);
        const words = [];
        const bitLength = text.length * 8;
        const hash = [];
        const constants = [];
        const isComposite = {};
        let primeCount = 0;
        for (let candidate = 2; primeCount < 64; candidate += 1) {
            if (!isComposite[candidate]) {
                for (let multiple = 0; multiple < 313; multiple += candidate) {
                    isComposite[multiple] = candidate;
                }
                if (primeCount < 8) {
                    hash[primeCount] =
                        (Math.pow(candidate, 0.5) * maxWord) | 0;
                }
                constants[primeCount] =
                    (Math.pow(candidate, 1 / 3) * maxWord) | 0;
                primeCount += 1;
            }
        }
        text += '\x80';
        while (text.length % 64 - 56) text += '\x00';
        for (let index = 0; index < text.length; index += 1) {
            words[index >> 2] = (words[index >> 2] || 0) |
                text.charCodeAt(index) << ((3 - index) % 4) * 8;
        }
        words.push((bitLength / maxWord) | 0);
        words.push(bitLength);
        for (let block = 0; block < words.length; block += 16) {
            const schedule = words.slice(block, block + 16);
            const oldHash = hash.slice();
            for (let round = 0; round < 64; round += 1) {
                const w15 = schedule[round - 15];
                const w2 = schedule[round - 2];
                const a = hash[0];
                const e = hash[4];
                const word = round < 16 ? (schedule[round] || 0) : (
                    schedule[round] = (
                        schedule[round - 16]
                        + ((w15 >>> 7 | w15 << 25)
                            ^ (w15 >>> 18 | w15 << 14)
                            ^ (w15 >>> 3))
                        + schedule[round - 7]
                        + ((w2 >>> 17 | w2 << 15)
                            ^ (w2 >>> 19 | w2 << 13)
                            ^ (w2 >>> 10))
                    ) | 0
                );
                const temp1 = (
                    hash[7]
                    + ((e >>> 6 | e << 26)
                        ^ (e >>> 11 | e << 21)
                        ^ (e >>> 25 | e << 7))
                    + ((e & hash[5]) ^ (~e & hash[6]))
                    + constants[round]
                    + word
                ) | 0;
                const temp2 = (
                    ((a >>> 2 | a << 30)
                        ^ (a >>> 13 | a << 19)
                        ^ (a >>> 22 | a << 10))
                    + ((a & hash[1])
                        ^ (a & hash[2])
                        ^ (hash[1] & hash[2]))
                ) | 0;
                hash.pop();
                hash.unshift((temp1 + temp2) | 0);
                hash[4] = (hash[4] + temp1) | 0;
            }
            for (let index = 0; index < 8; index += 1) {
                hash[index] = (hash[index] + oldHash[index]) | 0;
            }
        }
        return hash.map(function (word) {
            return ('00000000' + (word >>> 0).toString(16)).slice(-8);
        }).join('');
    }

    function canonicalHash(value) {
        return sha256Hex(JSON.stringify(canonicalValue(value)));
    }

    function nextEditorGenerationId() {
        editorGenerationSequence += 1;
        return 'facility-editor-' + Date.now().toString(36)
            + '-' + editorGenerationSequence.toString(36);
    }

    function sameStructuredValue(left, right) {
        return JSON.stringify(canonicalValue(left))
            === JSON.stringify(canonicalValue(right));
    }

    function layoutProposalStale(message, details) {
        const error = new Error(message || 'Full-layout proposal is stale');
        error.code = 'layout_proposal_stale';
        error.details = clone(details || {});
        return error;
    }

    function normalizeTransactionBinding(value, expectedRevision) {
        const source = object(value, 'transaction binding');
        const target = object(source.target, 'transaction binding target');
        const binding = {
            target: {
                domain: nonEmptyString(
                    target.domain,
                    'transaction binding target domain'
                ),
                scopeId: nonEmptyString(
                    target.scopeId,
                    'transaction binding target scopeId'
                ),
                resourceId: nonEmptyString(
                    target.resourceId,
                    'transaction binding target resourceId'
                ),
            },
            baseRevision: nonEmptyString(
                source.baseRevision,
                'transaction binding baseRevision'
            ),
            diffHash: nonEmptyString(
                source.diffHash,
                'transaction binding diffHash'
            ),
            dependencyFingerprint: nonEmptyString(
                source.dependencyFingerprint,
                'transaction binding dependencyFingerprint'
            ),
        };
        if (expectedRevision && binding.baseRevision !== expectedRevision) {
            throw layoutProposalStale(
                'Full-layout proposal binding has a stale revision',
                {
                    proposalRevision: binding.baseRevision,
                    currentRevision: expectedRevision,
                }
            );
        }
        return binding;
    }

    function normalizeLayoutAlternative(raw, index, expectedRevision) {
        const source = object(raw, 'layout proposal alternative ' + index);
        const ghost = object(
            source.ghostPreview,
            'layout proposal alternative ghostPreview'
        );
        const layout = layoutFromReceipt(
            { layout: ghost.layout },
            'layout proposal ghost preview'
        );
        if (!Array.isArray(source.operations)) {
            throw new TypeError('layout proposal operations must be an array');
        }
        if (ghost.routeProposals !== undefined
                && !Array.isArray(ghost.routeProposals)) {
            throw new TypeError(
                'layout proposal routeProposals must be an array'
            );
        }
        const metrics = source.metrics === undefined
            ? {}
            : object(source.metrics, 'layout proposal metrics');
        return {
            proposalId: nonEmptyString(
                source.proposalId,
                'layout proposal proposalId'
            ),
            alternativeId: nonEmptyString(
                source.alternativeId,
                'layout proposal alternativeId'
            ),
            strategy: nonEmptyString(
                source.strategy,
                'layout proposal strategy'
            ),
            operations: clone(source.operations),
            ghostPreview: {
                layout: clone(layout),
                routeProposals: clone(ghost.routeProposals || []),
            },
            metrics: clone(metrics),
            transactionBinding: normalizeTransactionBinding(
                source.transactionBinding,
                expectedRevision
            ),
            createdAt: timestamp(
                source.createdAt,
                'layout proposal createdAt'
            ),
            expiresAt: timestamp(
                source.expiresAt,
                'layout proposal expiresAt'
            ),
            findings: clone(source.findings || []),
            newHardFindingIds: clone(source.newHardFindingIds || []),
        };
    }

    function normalizeLayoutProposals(receipt, expectedRevision, request) {
        const source = object(receipt, 'layout proposal receipt');
        if (source.previewPure !== true) {
            throw new TypeError('layout proposal preview must be pure');
        }
        const revision = nonEmptyString(
            source.layoutRevision,
            'layout proposal layoutRevision'
        );
        if (revision !== expectedRevision) {
            throw layoutProposalStale(
                'Full-layout proposal was generated for a stale revision',
                {
                    proposalRevision: revision,
                    currentRevision: expectedRevision,
                }
            );
        }
        if (!Array.isArray(source.alternatives)
                || !source.alternatives.length) {
            throw new TypeError(
                'layout proposal receipt requires alternatives'
            );
        }
        const alternatives = source.alternatives.map(function (item, index) {
            return normalizeLayoutAlternative(item, index, expectedRevision);
        });
        const proposalIds = new Set(alternatives.map(function (item) {
            return item.proposalId;
        }));
        const alternativeIds = new Set(alternatives.map(function (item) {
            return item.alternativeId;
        }));
        if (proposalIds.size !== alternatives.length
                || alternativeIds.size !== alternatives.length) {
            throw new TypeError(
                'layout proposal alternatives require unique IDs'
            );
        }
        const selectedProposalId = nonEmptyString(
            source.selectedProposalId,
            'layout proposal selectedProposalId'
        );
        const selectedIndex = alternatives.findIndex(function (item) {
            return item.proposalId === selectedProposalId;
        });
        if (selectedIndex < 0) {
            throw new TypeError(
                'selectedProposalId must identify one alternative'
            );
        }
        return {
            authority: 'server-authoritative',
            previewPure: true,
            baseRevision: revision,
            request: clone(request),
            selectedIndex: selectedIndex,
            alternatives: alternatives,
        };
    }

    function normalizeLayoutProposalPreview(
        receipt,
        expectedAlternative,
        expectedRevision
    ) {
        const source = object(receipt, 'layout proposal preview receipt');
        if (source.previewPure !== true) {
            throw new TypeError('layout proposal preview must be pure');
        }
        const proposalId = nonEmptyString(
            source.proposalId,
            'layout proposal preview proposalId'
        );
        if (proposalId !== expectedAlternative.proposalId) {
            throw layoutProposalStale(
                'Full-layout proposal preview does not match the selection',
                {
                    expectedProposalId: expectedAlternative.proposalId,
                    proposalId: proposalId,
                }
            );
        }
        const rawAlternative = object(
            source.alternative,
            'layout proposal preview alternative'
        );
        const alternative = normalizeLayoutAlternative({
            ...rawAlternative,
            proposalId: proposalId,
            transactionBinding: rawAlternative.transactionBinding
                || source.transactionBinding,
            createdAt: rawAlternative.createdAt || source.createdAt,
            expiresAt: rawAlternative.expiresAt || source.expiresAt,
        }, 0, expectedRevision);
        const topBinding = normalizeTransactionBinding(
            source.transactionBinding,
            expectedRevision
        );
        if (alternative.alternativeId !== expectedAlternative.alternativeId
                || !sameStructuredValue(
                    topBinding,
                    expectedAlternative.transactionBinding
                )
                || !sameStructuredValue(
                    alternative.transactionBinding,
                    expectedAlternative.transactionBinding
                )) {
            throw layoutProposalStale(
                'Full-layout proposal preview binding changed',
                {
                    expectedAlternativeId:
                        expectedAlternative.alternativeId,
                    alternativeId: alternative.alternativeId,
                }
            );
        }
        return {
            proposalId: proposalId,
            alternative: alternative,
            transactionBinding: topBinding,
        };
    }

    function createIdempotencyKey(config) {
        if (typeof config.createIdempotencyKey === 'function') {
            return nonEmptyString(
                config.createIdempotencyKey(),
                'idempotencyKey'
            );
        }
        idempotencySequence += 1;
        return 'fl-layout-' + Date.now().toString(36)
            + '-' + idempotencySequence.toString(36).padStart(4, '0');
    }

    function selectedIdsInLayout(layout, selectedIds) {
        const available = new Set();
        layout.placements.forEach(function (placement) {
            available.add(placement.placementId);
        });
        layout.zones.forEach(function (zone) {
            available.add(zone.zoneId);
        });
        (layout.floorMarkings || []).forEach(function (marking) {
            available.add(marking.markingId);
        });
        (layout.routes || []).forEach(function (route) {
            available.add(route.routeId);
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
        (layout.floorMarkings || []).forEach(function (marking) {
            if (marking && marking.markingId) result.add(marking.markingId);
        });
        (layout.routes || []).forEach(function (route) {
            if (route && route.routeId) result.add(route.routeId);
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

    function floorMarkingById(layout, markingId) {
        return (layout.floorMarkings || []).find(function (marking) {
            return marking.markingId === markingId;
        }) || null;
    }

    function routeById(layout, routeId) {
        return (layout.routes || []).find(function (route) {
            return route.routeId === routeId;
        }) || null;
    }

    function cellGroupMetadata(zone) {
        const extensions = zone && zone.extensions;
        const cellGroup = extensions && extensions.cellGroup;
        return cellGroup && cellGroup.groupKind === 'manufacturing_cell'
            ? cellGroup : null;
    }

    function pointInBoundary(position, boundary) {
        if (!position || !Array.isArray(boundary) || boundary.length < 3) {
            return false;
        }
        const x = Number(position.x);
        const z = Number(position.z);
        if (!Number.isFinite(x) || !Number.isFinite(z)) return false;
        let inside = false;
        for (let index = 0, previous = boundary.length - 1;
                index < boundary.length; previous = index, index += 1) {
            const a = boundary[index] || {};
            const b = boundary[previous] || {};
            const ax = Number(a.x);
            const az = Number(a.z);
            const bx = Number(b.x);
            const bz = Number(b.z);
            if (![ax, az, bx, bz].every(Number.isFinite)) continue;
            const crosses = (az > z) !== (bz > z)
                && x < (bx - ax) * (z - az) / (bz - az) + ax;
            if (crosses) inside = !inside;
        }
        return inside;
    }

    function expandedCellItemIds(layout, identifiers) {
        const source = layout || {};
        const requested = Array.isArray(identifiers) ? identifiers : [];
        const result = [];
        const seen = new Set();
        function add(identifier) {
            if (!identifier || seen.has(identifier)) return;
            seen.add(identifier);
            result.push(identifier);
        }
        requested.forEach(add);
        (source.zones || []).forEach(function (zone) {
            if (!seen.has(zone.zoneId) || !cellGroupMetadata(zone)) return;
            (source.placements || []).forEach(function (placement) {
                const position = placement.transform
                    && placement.transform.position;
                if (pointInBoundary(position, zone.boundary)) {
                    add(placement.placementId);
                }
            });
            (source.floorMarkings || []).forEach(function (marking) {
                const position = marking.transform
                    && marking.transform.position;
                if (pointInBoundary(position, zone.boundary)) {
                    add(marking.markingId);
                }
            });
        });
        return result;
    }

    function cellGroupLabel(autoNumber) {
        const value = autoNumber || {};
        const baseName = String(value.baseName || 'Cell').trim() || 'Cell';
        const prefix = String(value.prefix || '').trim();
        const sequence = Math.max(0, Math.round(Number(value.sequence) || 0));
        const padding = Math.max(1, Math.min(
            6,
            Math.round(Number(value.padding) || 2)
        ));
        const suffix = (prefix || '') + String(sequence).padStart(padding, '0');
        return baseName + (suffix ? ' ' + suffix : '');
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
            extensions: clone(source.extensions || {}),
        };
    }

    function normalizeFloorMarking(request) {
        const source = object(request, 'floor marking request');
        const markingTypes = [
            'direction_arrow',
            'solid_line',
            'dashed_line',
            'keep_clear',
            'crosswalk',
            'hazard_stripe',
            'floor_text',
            'parking_box',
        ];
        const semanticRoles = [
            'decorative',
            'pedestrian_lane',
            'forklift_lane',
            'material_flow',
            'keep_clear',
            'staging',
            'safety',
            'parking',
        ];
        const markingType = nonEmptyString(
            source.markingType,
            'markingType'
        );
        if (!markingTypes.includes(markingType)) {
            throw new TypeError('markingType is unsupported');
        }
        const semanticRole = source.semanticRole || 'decorative';
        if (!semanticRoles.includes(semanticRole)) {
            throw new TypeError('semanticRole is unsupported');
        }
        const positionMode = source.positionMode || 'manual';
        if (!['auto', 'manual', 'locked'].includes(positionMode)) {
            throw new TypeError('positionMode must be auto, manual, or locked');
        }
        function color(value, fallback, label) {
            const result = String(value || fallback);
            if (!/^#[0-9a-fA-F]{6}$/.test(result)) {
                throw new TypeError(label + ' must be a six-digit hex color');
            }
            return result;
        }
        const label = String(source.label || 'Floor marking').trim();
        if (!label || label.length > 120) {
            throw new RangeError('floor marking label must contain 1 to 120 characters');
        }
        const text = String(source.text || '');
        if (text.length > 120
                || (markingType === 'floor_text' && !text)) {
            throw new RangeError('floor marking text is invalid');
        }
        const opacity = source.opacity === undefined
            ? 1 : finite(source.opacity, 'floor marking opacity');
        if (opacity < 0 || opacity > 1) {
            throw new RangeError('floor marking opacity must be between zero and one');
        }
        const transformSource = object(
            source.transform,
            'floor marking transform'
        );
        const result = {
            markingType: markingType,
            label: label,
            semanticRole: semanticRole,
            transform: {
                position: worldPosition(transformSource.position),
                rotationDegrees: finite(
                    transformSource.rotationDegrees === undefined
                        ? 0 : transformSource.rotationDegrees,
                    'floor marking rotation'
                ),
            },
            width: positive(source.width, 'floor marking width'),
            depth: positive(source.depth, 'floor marking depth'),
            fillColor: color(source.fillColor, '#facc15', 'fillColor'),
            strokeColor: color(source.strokeColor, '#111827', 'strokeColor'),
            opacity: opacity,
            text: text,
            positionMode: positionMode,
            metadata: clone(source.metadata || {}),
            evidence: clone(source.evidence || []),
        };
        if (source.markingId) {
            result.markingId = nonEmptyString(source.markingId, 'markingId');
        }
        return result;
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

    function zoneBounds(boundary) {
        if (!Array.isArray(boundary) || boundary.length < 3) {
            throw new TypeError('zone boundary must contain at least three points');
        }
        return boundary.map(worldPoint).reduce(function (result, point) {
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
    }

    function zoneBoundaryAt(boundary, geometry) {
        const requested = object(geometry, 'zone geometry');
        const bounds = zoneBounds(boundary);
        const width = positive(requested.width, 'zone width');
        const depth = positive(requested.depth, 'zone depth');
        const minX = finite(requested.minX, 'zone minimum X');
        const minZ = finite(requested.minZ, 'zone minimum Z');
        const resized = resizedZoneBoundary(boundary, width, depth);
        const resizedBounds = zoneBounds(resized);
        const deltaX = minX - resizedBounds.minX;
        const deltaZ = minZ - resizedBounds.minZ;
        return resized.map(function (point) {
            return { x: point.x + deltaX, z: point.z + deltaZ };
        });
    }

    function createSession(options) {
        const config = options || {};
        if (config.operationIdNamespace !== undefined
                && !/^[0-9a-f]{40}$/.test(config.operationIdNamespace)) {
            throw new TypeError('operationIdNamespace must be a 40-character digest');
        }
        if (typeof config.previewOperations !== 'function') {
            throw new TypeError('previewOperations transport is required');
        }
        if (typeof config.applyOperations !== 'function') {
            throw new TypeError('applyOperations transport is required');
        }

        let baseLayout = null;
        let baseRevision = null;
        let draftLayout = null;
        let draftRevision = null;
        let batches = [];
        let cursor = 0;
        let selectedIds = [];
        let camera = null;
        let ghost = null;
        let placementAlternatives = null;
        let layoutProposal = null;
        let generatedDraft = null;
        let designProposalDraft = null;
        let designAuthorityState = 'ready';
        let editorGenerationId = nextEditorGenerationId();
        let recentReceiptIds = [];
        let busy = false;
        let conflict = null;
        let lastError = null;
        // Installed only by an explicitly authorized desktop runtime. Ordinary web
        // sessions retain their existing transport and editing behavior.
        let desktopRecovery = null;
        let desktopSequence = 0;
        let desktopFreezeOwner = null;
        let desktopPending = null;
        let desktopRecoveryOwned = false;
        let desktopStartupRecoveryPending = false;
        const retiredDesktopIntents = new Set();
        const listeners = new Set();

        function requireLoaded() {
            if (!baseLayout) throw new Error('facility layout session is not loaded');
        }

        function notify() {
            if (desktopRecovery) desktopSequence += 1;
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
            assertDesktopMutable();
            if (busy) {
                const error = new Error('facility layout session is busy');
                error.code = 'session_busy';
                throw error;
            }
        }

        function desktopError(code, message) {
            const error = new Error(message);
            error.code = code;
            return error;
        }

        function assertDesktopMutable() {
            if (!desktopRecovery) return;
            if (desktopFreezeOwner) throw desktopError(
                'facility_desktop_frozen', 'Facility editor is frozen for a lifecycle decision');
            if (desktopStartupRecoveryPending) throw desktopError(
                'facility_desktop_recovery_unresolved', 'Startup recovery ownership and transaction inspection is unresolved');
            if (desktopPending || desktopRecoveryOwned) throw desktopError(
                'facility_desktop_recovery_unresolved', 'Facility recovery ownership or transaction is unresolved');
            if (designAuthorityState !== 'ready') throw desktopError(
                'facility_desktop_recovery_unresolved', 'Facility design authority must be resolved before another mutation');
        }

        function assertDesktopDispatch() {
            if (desktopRecovery && desktopFreezeOwner) throw desktopError(
                'facility_desktop_frozen', 'Lifecycle freeze prevents another transaction phase');
        }

        function desktopSnapshot() {
            requireLoaded();
            const state = getState();
            return clone({ schemaVersion: 1,
                rendererGeneration: desktopRecovery.rendererGeneration,
                stateSequence: desktopSequence,
                document: { documentId: baseLayout.layoutId, baseRevision: baseRevision,
                    draftRevision: draftRevision },
                editorFrame: captureDesignEditorFrame(),
                designProposalDraft: designProposalDraft,
                designAuthorityState: designAuthorityState,
                camera: camera, ghostPlacement: ghost,
                placementAlternatives: placementAlternatives, layoutProposal: layoutProposal,
                dirty: state.dirty, busy: busy, conflict: conflict,
                recoveryOwned: desktopRecoveryOwned,
                startupRecoveryPending: desktopStartupRecoveryPending,
                pendingOperations: desktopPending ? [desktopPending] : [],
                // The session has no background-job registry. Expose its real
                // busy state separately; the harness must cover other workflows.
                activeJobs: [],
            });
        }

        function beginDesktopOperation(kind, binding) {
            if (!desktopRecovery) return;
            assertDesktopMutable();
            desktopPending = Object.assign({ kind: kind,
                requestId: createIdempotencyKey(config), phase: 'starting', state: 'pending',
                startingAuthorityState: designAuthorityState, responses: {} }, clone(binding || {}));
            notify();
        }

        async function persistDesktopOperation() {
            if (!desktopRecovery || !desktopPending) return;
            await desktopRecovery.persistOperation(Object.assign({}, clone(desktopPending), {
                snapshot: desktopSnapshot(),
            }));
        }

        async function desktopTransport(phase, transport, payload) {
            if (!desktopRecovery) return transport(payload);
            if (!desktopPending) throw desktopError(
                'facility_desktop_operation_missing', 'A transaction requires a recovery identity');
            assertDesktopDispatch();
            if (payload.transactionId) desktopPending.transactionId = payload.transactionId;
            desktopPending.phase = phase + '-pending';
            desktopPending.state = 'pending';
            desktopPending.request = clone(payload);
            notify();
            // Await the actual durable hook, never an asynchronous Storage shim.
            await persistDesktopOperation();
            assertDesktopDispatch();
            let response;
            try {
                response = await transport(payload);
            } catch (error) {
                desktopPending.phase = phase + '-unknown';
                desktopPending.state = 'unknown';
                notify();
                try { await persistDesktopOperation(); }
                catch (checkpointError) { error.recoveryCheckpointError = checkpointError; }
                throw error;
            }
            const envelope = response && response.transaction;
            const transaction = envelope && envelope.transaction;
            if (transaction && transaction.transactionId) desktopPending.transactionId = transaction.transactionId;
            desktopPending.phase = phase + '-received';
            desktopPending.responses[phase] = clone(response);
            notify();
            await persistDesktopOperation();
            return response;
        }

        async function completeDesktopOperation(resolution) {
            if (!desktopRecovery || !desktopPending) return;
            const operation = desktopPending;
            const record = Object.assign({}, clone(desktopPending), {
                resolution: resolution, snapshot: desktopSnapshot(),
            });
            await desktopRecovery.clearOperation(record);
            // The native hook may adopt its independently verified result via
            // acceptReconciliation while this await is pending.
            if (desktopPending === null) return;
            if (desktopPending !== operation) throw desktopError(
                'facility_desktop_stale_state', 'Recovery owner changed during durable reconciliation');
            desktopPending = null;
            desktopRecoveryOwned = false;
            notify();
        }

        function installDesktopRecovery(hooks) {
            if (desktopRecovery) throw desktopError(
                'facility_desktop_adapter_installed', 'Desktop recovery is already installed');
            if (busy) throw desktopError('session_busy', 'Install recovery before starting work');
            if (!hooks || typeof hooks.persistOperation !== 'function'
                    || typeof hooks.clearOperation !== 'function') {
                throw new TypeError('Async persistOperation and clearOperation hooks are required');
            }
            const recoveryBinding = hooks.binding ? clone(hooks.binding) : null;
            if (recoveryBinding && Object.entries({ identity: ['backendId', 'storeId', 'principalId'],
                document: ['tenantId', 'siteId', 'documentId'], owner: ['sessionId', 'ownerId'] }).some(function (entry) {
                    return !recoveryBinding[entry[0]] || entry[1].some(function (key) {
                        const value = recoveryBinding[entry[0]][key];
                        return typeof value !== 'string' || !value || value.length > 512;
                    });
                })) throw desktopError('facility_desktop_recovery_binding', 'A complete native recovery binding is required');
            desktopRecovery = { persistOperation: hooks.persistOperation,
                clearOperation: hooks.clearOperation, rendererGeneration: nextEditorGenerationId(),
                allowSave: hooks.allowSave !== false, binding: recoveryBinding };
            // The desktop runtime starts blocked before native journal inspection.
            // Ordinary web sessions and default hook installation stay unchanged.
            desktopStartupRecoveryPending = hooks.startupRecoveryPending === true;
            if (desktopStartupRecoveryPending) notify();
            function expected(request, allowBusy) {
                if (!request || request.expectedRendererGeneration !== desktopRecovery.rendererGeneration
                        || request.expectedStateSequence !== desktopSequence || (busy && !allowBusy)) {
                    throw desktopError('facility_desktop_stale_state', 'Recovery target state changed');
                }
            }
            return Object.freeze({
                snapshot: desktopSnapshot,
                setStartupRecoveryGate: function (request) {
                    expected(request, true);
                    if (typeof request.blocked !== 'boolean') throw desktopError(
                        'facility_desktop_recovery_binding', 'A native recovery gate decision is required');
                    if (!request.blocked && (desktopPending || desktopRecoveryOwned)) throw desktopError(
                        'facility_desktop_recovery_unresolved', 'An unresolved transaction or recovery owner cannot release the startup gate');
                    if (desktopStartupRecoveryPending !== request.blocked) {
                        desktopStartupRecoveryPending = request.blocked;
                        notify();
                    }
                    return desktopSnapshot();
                },
                freeze: function (request) {
                    if (!request || typeof request.intentId !== 'string' || !request.intentId
                            || request.rendererGeneration !== desktopRecovery.rendererGeneration
                            || request.stateSequence !== desktopSequence) {
                        throw desktopError('facility_desktop_stale_state', 'Lifecycle freeze targets stale editor state');
                    }
                    if (retiredDesktopIntents.has(request.intentId) || retiredDesktopIntents.size >= 1024) throw desktopError(
                        'facility_desktop_stale_intent', 'A completed lifecycle intent cannot freeze the editor again');
                    if (desktopFreezeOwner && desktopFreezeOwner !== request.intentId) throw desktopError(
                        'facility_desktop_freeze_owned', 'Another lifecycle intent owns the freeze');
                    desktopFreezeOwner = request.intentId;
                    return desktopSnapshot();
                },
                unfreeze: function (request) {
                    if (request && !desktopFreezeOwner && retiredDesktopIntents.has(request.intentId)) return desktopSnapshot();
                    if (!request || !desktopFreezeOwner || desktopFreezeOwner !== request.intentId) throw desktopError(
                        'facility_desktop_freeze_owned', 'Only the owning lifecycle intent can release the freeze');
                    retiredDesktopIntents.add(request.intentId);
                    desktopFreezeOwner = null;
                    return desktopSnapshot();
                },
                restoreRecovery: function (request) {
                    expected(request);
                    const snapshot = request.snapshot;
                    const record = request.record;
                    const localDraft = record && record.payload && record.payload.type === 'draft';
                    if (!snapshot || snapshot.schemaVersion !== 1 || !snapshot.editorFrame
                            || !snapshot.document || snapshot.document.documentId !== baseLayout.layoutId
                            || snapshot.document.baseRevision !== baseRevision
                            || snapshot.editorFrame.baseRevision !== baseRevision
                            || !sameStructuredValue(snapshot.editorFrame.baseLayout, baseLayout)
                            || !Array.isArray(snapshot.pendingOperations)
                            || snapshot.pendingOperations.length !== (localDraft ? 0 : 1)) {
                        throw desktopError('facility_desktop_recovery_binding', 'Recovery must match the loaded document and its base');
                    }
                    if (localDraft && (!desktopRecovery.binding || record.schemaVersion !== 1
                            || record.payload.adapter !== 'facility-recovery-v1' || record.handle?.state !== 'reconciled'
                            || !sameStructuredValue(record.identity, desktopRecovery.binding.identity)
                            || !sameStructuredValue(record.payload.owner, desktopRecovery.binding.owner)
                            || Object.keys(desktopRecovery.binding.document).some(function (key) {
                                return record.document?.[key] !== desktopRecovery.binding.document[key];
                            })
                            || record.document.baseRevision !== snapshot.document.baseRevision
                            || record.document.draftRevision !== snapshot.document.draftRevision
                            || !sameStructuredValue(record.payload.snapshot, snapshot)
                            || snapshot.designProposalDraft || snapshot.editorFrame.activeProposal
                            || desktopPending || desktopRecoveryOwned || getState().dirty)) {
                        throw desktopError('facility_desktop_recovery_binding', 'Local draft recovery requires the bound native checkpoint and an unmodified current draft');
                    }
                    const frame = snapshot.editorFrame;
                    if (frame.schemaVersion !== DESIGN_EDITOR_FRAME_VERSION
                            || !frame.draftLayout || frame.draftLayout.layoutId !== baseLayout.layoutId
                            || !Array.isArray(frame.draftLayout.placements) || !Array.isArray(frame.draftLayout.zones)
                            || frame.draftRevision !== snapshot.document.draftRevision
                            || typeof frame.draftRevision !== 'string' || !frame.draftRevision
                            || typeof frame.editorGenerationId !== 'string' || !frame.editorGenerationId
                            || !Array.isArray(frame.batches)
                            || frame.batches.some(batch => !batch || typeof batch.label !== 'string'
                                || !batch.label || !Array.isArray(batch.operations))
                            || !Number.isSafeInteger(frame.cursor) || frame.cursor < 0 || frame.cursor > frame.batches.length
                            || !Array.isArray(frame.selectedIds)
                            || frame.selectedIds.some(id => typeof id !== 'string' || !id)
                            || !sameStructuredValue(frame.selectedIds, selectedIdsInLayout(frame.draftLayout, frame.selectedIds))
                            || !Array.isArray(frame.recentReceiptIds)
                            || frame.recentReceiptIds.length > 6 || frame.recentReceiptIds.some(id => typeof id !== 'string' || !id)
                            || typeof snapshot.designAuthorityState !== 'string') {
                        throw desktopError('facility_desktop_recovery_binding', 'Recovery frame is incomplete or would require lossy repair');
                    }
                    const operation = snapshot.pendingOperations[0];
                    if (!localDraft && (!['apply', 'undo'].includes(operation.kind) || !operation.requestId
                            || !['pending', 'unknown'].includes(operation.state))) throw desktopError(
                        'facility_desktop_recovery_binding', 'Recovery transaction identity is incomplete');
                    if (desktopPending && (desktopPending.requestId !== operation.requestId
                            || desktopPending.transactionId !== operation.transactionId)) throw desktopError(
                        'facility_desktop_recovery_binding', 'An unresolved transaction cannot be replaced');
                    // Native ownership/binding must be verified before invoking
                    // this installed-only method. It performs no network replay.
                    restoreDesignEditorFrame(snapshot.editorFrame);
                    designProposalDraft = clone(snapshot.designProposalDraft);
                    designAuthorityState = snapshot.designAuthorityState;
                    camera = clone(snapshot.camera);
                    ghost = clone(snapshot.ghostPlacement);
                    placementAlternatives = clone(snapshot.placementAlternatives);
                    layoutProposal = clone(snapshot.layoutProposal);
                    conflict = clone(snapshot.conflict);
                    desktopPending = localDraft ? null : clone(operation);
                    desktopRecoveryOwned = !localDraft;
                    notify();
                    return desktopSnapshot();
                },
                acceptReconciliation: function (request) {
                    expected(request, true);
                    if (!desktopPending || request.requestId !== desktopPending.requestId
                            || request.transactionId !== desktopPending.transactionId
                            || request.kind !== desktopPending.kind
                            || !['applied', 'undone', 'not-applied'].includes(request.resolution)) {
                        throw desktopError('facility_desktop_recovery_binding', 'Reconciliation does not match the pending transaction');
                    }
                    if (busy && !desktopPending.phase.endsWith('-received')) throw desktopError(
                        'facility_desktop_recovery_state', 'A transport response is still in flight');
                    const installed = designProposalDraft
                        && designProposalDraft.transactionId === desktopPending.transactionId;
                    if (request.resolution === 'applied' && (desktopPending.kind !== 'apply'
                            || !installed || !['installation_pending', 'active'].includes(designProposalDraft.status)
                            || typeof request.transactionRevision !== 'string' || !request.transactionRevision)) {
                        throw desktopError('facility_desktop_recovery_state', 'The verified Apply result is not installed locally');
                    }
                    const undoPrepared = desktopPending.responses && desktopPending.responses['undo-prepare'];
                    const undoRoot = installed && designProposalDraft.rootUndoFrame
                        || undoPrepared && undoPrepared.rootUndoFrame;
                    const completedUndo = !designProposalDraft && desktopPending.responses
                        && (desktopPending.responses['undo-acknowledge']
                            || (desktopPending.phase === 'undo-prepare-received' && undoPrepared
                                && undoPrepared.mode === 'already_undone' && undoPrepared.readiness === 'ready'));
                    if (request.resolution === 'undone' && (desktopPending.kind !== 'undo'
                            || (!completedUndo && (!installed || designProposalDraft.status !== 'undo_acknowledgment_pending'))
                            || !undoRoot || !sameStructuredValue(draftLayout, undoRoot.draftLayout)
                            || !sameStructuredValue(batches, undoRoot.batches))) {
                        throw desktopError('facility_desktop_recovery_state', 'The verified Undo root frame is not installed locally');
                    }
                    if (request.resolution === 'not-applied' && (desktopPending.kind !== 'apply' || installed)) {
                        throw desktopError('facility_desktop_recovery_state', 'A locally installed transaction cannot be reported absent');
                    }
                    // Native adapter supplies an independently verified result.
                    // Its durable write already finished. Do not call the async
                    // clearOperation hook here (that would recurse into native).
                    if (request.resolution === 'applied') {
                        designProposalDraft.transactionRevision = request.transactionRevision;
                        designProposalDraft.status = 'active';
                        designAuthorityState = 'ready';
                    } else if (request.resolution === 'undone') {
                        designProposalDraft = null;
                        designAuthorityState = 'ready';
                    } else {
                        designAuthorityState = 'ready';
                    }
                    desktopPending = null;
                    desktopRecoveryOwned = false;
                    // The native owner has verified and durably reconciled this
                    // transaction. Its interruption is no longer a current error.
                    lastError = null;
                    notify();
                    return desktopSnapshot();
                },
            });
        }

        function currentOperations() {
            return flattenBatches(batches, cursor);
        }

        function activeProposalFrame() {
            if (!designProposalDraft) return null;
            return {
                proposalId: designProposalDraft.proposalId,
                proposalRevision: designProposalDraft.proposalRevision,
                transactionId: designProposalDraft.transactionId,
                transactionRevision: designProposalDraft.transactionRevision,
                transactionBindingRevision:
                    designProposalDraft.transactionBindingRevision,
                status: designProposalDraft.status,
            };
        }

        function currentCommandJournalHash() {
            if (designProposalDraft
                    && designProposalDraft.commandJournalHash) {
                return designProposalDraft.commandJournalHash;
            }
            return canonicalHash({
                baseRevision: baseRevision,
                batches: clone(batches),
                cursor: cursor,
                generatedDraft: clone(generatedDraft),
            });
        }

        function captureDesignEditorFrame() {
            requireLoaded();
            return {
                schemaVersion: DESIGN_EDITOR_FRAME_VERSION,
                baseLayout: clone(baseLayout),
                baseRevision: baseRevision,
                draftLayout: clone(draftLayout),
                draftRevision: draftRevision,
                batches: clone(batches),
                cursor: cursor,
                selectedIds: selectedIds.slice(),
                generatedDraft: clone(generatedDraft),
                recentReceiptIds: recentReceiptIds.slice(),
                activeProposal: activeProposalFrame(),
                editorGenerationId: editorGenerationId,
                commandJournalHash: currentCommandJournalHash(),
            };
        }

        function restoreDesignEditorFrame(frame) {
            const value = object(frame, 'Facility design editor frame');
            baseLayout = frozenClone(value.baseLayout);
            baseRevision = nonEmptyString(
                value.baseRevision,
                'Facility design base revision'
            );
            draftLayout = frozenClone(value.draftLayout);
            draftRevision = nonEmptyString(
                value.draftRevision,
                'Facility design draft revision'
            );
            batches = frozenClone(value.batches || []);
            cursor = Math.max(0, Math.min(
                batches.length,
                Number(value.cursor) || 0
            ));
            selectedIds = selectedIdsInLayout(
                draftLayout,
                Array.isArray(value.selectedIds) ? value.selectedIds : []
            );
            generatedDraft = value.generatedDraft
                ? frozenClone(value.generatedDraft) : null;
            recentReceiptIds = Array.isArray(value.recentReceiptIds)
                ? value.recentReceiptIds.slice(-6).map(String) : [];
            editorGenerationId = nonEmptyString(
                value.editorGenerationId,
                'Facility design editor generation ID'
            );
            ghost = null;
            placementAlternatives = null;
            layoutProposal = null;
            conflict = null;
        }

        async function persistDesignUndoRecovery(record) {
            if (typeof config.persistDesignUndoRecovery !== 'function') return;
            await config.persistDesignUndoRecovery(clone(record));
        }

        async function clearDesignUndoRecovery() {
            if (typeof config.clearDesignUndoRecovery !== 'function') return;
            await config.clearDesignUndoRecovery();
        }

        function pendingUndoFromPrepared(prepared, prior) {
            const envelope = object(
                prepared.transaction,
                'Facility design Undo transaction'
            );
            const body = envelope.transaction
                && typeof envelope.transaction === 'object'
                ? envelope.transaction : {};
            const binding = body.proposalBinding
                && typeof body.proposalBinding === 'object'
                ? body.proposalBinding : {};
            return {
                proposalId: nonEmptyString(
                    binding.proposalId || (prior && prior.proposalId),
                    'Facility design Undo proposalId'
                ),
                proposalRevision: nonEmptyString(
                    binding.proposalRevision
                        || (prior && prior.proposalRevision),
                    'Facility design Undo proposalRevision'
                ),
                transactionId: nonEmptyString(
                    body.transactionId || (prior && prior.transactionId),
                    'Facility design Undo transactionId'
                ),
                transactionRevision: nonEmptyString(
                    envelope.transactionRevision,
                    'Facility design Undo transactionRevision'
                ),
                transactionBindingRevision:
                    body.installationBindingTransactionRevision
                        || (prior && prior.transactionBindingRevision) || null,
                status: 'undo_acknowledgment_pending',
                commandJournalHash: null,
                rootUndoFrame: null,
                previousInstallationState: prior
                    && prior.previousInstallationState
                    ? frozenClone(prior.previousInstallationState) : null,
                authorityLost: false,
            };
        }

        async function acknowledgePendingDesignUndo(pending, rootFrame) {
            if (typeof config.acknowledgeDesignUndo !== 'function') {
                throw new Error(
                    'acknowledgeDesignUndo transport is not configured'
                );
            }
            await desktopTransport('undo-acknowledge', config.acknowledgeDesignUndo, {
                transactionId: pending.transactionId,
                expectedTransactionRevision: pending.transactionRevision,
                observedDraftRevision: rootFrame.draftRevision,
                observedCommandJournalHash: rootFrame.commandJournalHash,
            });
            designProposalDraft = null;
            designAuthorityState = 'ready';
            await clearDesignUndoRecovery();
            await completeDesktopOperation('undone');
        }

        async function installPreparedDesignUndo(prepared, prior) {
            const rootFrame = object(
                prepared.rootUndoFrame,
                'Facility design root Undo frame'
            );
            restoreDesignEditorFrame(rootFrame);
            if (prepared.mode === 'already_undone'
                    && prepared.readiness === 'ready') {
                designProposalDraft = null;
                designAuthorityState = 'ready';
                await clearDesignUndoRecovery();
                await completeDesktopOperation('undone');
                return;
            }
            if (prepared.mode === 'local_only'
                    && prepared.readiness === 'stale_local_restore') {
                designProposalDraft = null;
                designAuthorityState = 'stale_local_restore';
                if (generatedDraft) {
                    const restoredGeneration = clone(generatedDraft);
                    restoredGeneration.authorityLost = true;
                    generatedDraft = frozenClone(restoredGeneration);
                }
                await clearDesignUndoRecovery();
                await completeDesktopOperation('undone');
                return;
            }
            if (prepared.mode !== 'coordinated') {
                const error = new Error(
                    'Facility design Undo returned an unsupported recovery mode'
                );
                error.code = 'facility_design_undo_mode_invalid';
                throw error;
            }
            const pending = pendingUndoFromPrepared(prepared, prior);
            pending.commandJournalHash = rootFrame.commandJournalHash;
            pending.rootUndoFrame = frozenClone(rootFrame);
            designProposalDraft = pending;
            designAuthorityState = 'undo_acknowledgment_pending';
            await persistDesignUndoRecovery({
                schemaVersion: 1,
                phase: 'acknowledgment_pending',
                transactionId: pending.transactionId,
                expectedTransactionRevision: pending.transactionRevision,
            });
            await acknowledgePendingDesignUndo(pending, rootFrame);
        }

        function designInstallationFingerprint(input) {
            return canonicalHash({
                commandJournalHash: input.commandJournalHash,
                draftRevision: input.draftRevision,
                editorGenerationId: input.editorGenerationId,
                proposalId: input.proposalId || null,
                proposalRevision: input.proposalRevision || null,
                transactionBindingRevision:
                    input.transactionBindingRevision || null,
            });
        }

        function rememberReceipt(receipt) {
            if (!receipt || typeof receipt !== 'object') return;
            const receiptId = receipt.receiptId
                || (receipt.receipt && receipt.receipt.receiptId)
                || (receipt.result && receipt.result.receiptId);
            if (typeof receiptId !== 'string' || !receiptId) return;
            recentReceiptIds = recentReceiptIds.filter(function (item) {
                return item !== receiptId;
            });
            recentReceiptIds.push(receiptId);
            if (recentReceiptIds.length > 6) {
                recentReceiptIds = recentReceiptIds.slice(-6);
            }
        }

        function installReceipt(receipt, requireRevision) {
            const layout = frozenClone(layoutFromReceipt(receipt, 'layout receipt'));
            const revision = revisionFromReceipt(receipt, requireRevision);
            baseLayout = layout;
            baseRevision = revision || baseRevision;
            draftLayout = layout;
            draftRevision = revision || canonicalHash(layout);
            batches = [];
            cursor = 0;
            selectedIds = selectedIdsInLayout(layout, selectedIds);
            ghost = null;
            placementAlternatives = null;
            layoutProposal = null;
            generatedDraft = null;
            designProposalDraft = null;
            designAuthorityState = 'ready';
            editorGenerationId = nextEditorGenerationId();
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
                revision: revisionFromReceipt(receipt, false),
                createdIds: createdIdsFromReceipt(receipt),
            };
        }

        const constructionInstallations = new Map();

        async function installConstructionApproval(approval) {
            requireLoaded();
            assertIdle();
            const binding = approval && approval.binding || {};
            const identifier = approval && approval.approvalId;
            const signature = canonicalHash(approval);
            const prior = constructionInstallations.get(identifier);
            if (prior && prior.signature === signature && prior.generation === editorGenerationId
                    && draftRevision === approval.candidateRevision) return getState();
            if (!/^fca-[0-9a-f]{64}$/.test(identifier || '') || prior
                    || binding.editorGenerationId !== editorGenerationId
                    || binding.expectedDraftRevision !== draftRevision
                    || approval.baseRevision !== baseRevision || cursor !== 0 || batches.length !== 0
                    || generatedDraft || designProposalDraft
                    || (config.sessionId && binding.sessionId !== config.sessionId)) {
                const error = new Error('Construction approval is stale or belongs to another editor frame');
                error.code = 'facility_command_stale';
                throw error;
            }
            await commitGesture('Apply Sage construction', approval.operations, 'created', {
                candidateRevision: approval.candidateRevision,
                editorGenerationId: editorGenerationId,
            });
            constructionInstallations.set(identifier, {signature: signature, generation: editorGenerationId});
            return getState();
        }

        async function commitGesture(label, operations, selectionPolicy, expectedResult) {
            requireLoaded();
            assertIdle();
            if (generatedDraft) {
                const error = new Error(
                    'Save or undo the generated Facility draft before editing it'
                );
                error.code = 'generated_draft_review_required';
                throw error;
            }
            if (designProposalDraft) {
                const error = new Error(
                    'Save or undo the Facility design proposal before editing it'
                );
                error.code = 'design_proposal_review_required';
                throw error;
            }
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
                if (expectedResult && (result.revision !== expectedResult.candidateRevision
                        || editorGenerationId !== expectedResult.editorGenerationId)) {
                    const error = new Error('Construction result no longer matches the approved preview');
                    error.code = 'facility_command_stale';
                    throw error;
                }
                if (result.receipt.changed === false) {
                    draftLayout = result.layout;
                    draftRevision = result.revision
                        || canonicalHash(result.layout);
                    selectedIds = selectedIdsInLayout(
                        draftLayout,
                        selectedIds
                    );
                    ghost = null;
                    placementAlternatives = null;
                    layoutProposal = null;
                    conflict = null;
                    lastError = null;
                    return getState();
                }
                batches = candidateBatches;
                cursor = batches.length;
                draftLayout = result.layout;
                draftRevision = result.revision || canonicalHash(result.layout);
                editorGenerationId = nextEditorGenerationId();
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
                layoutProposal = null;
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
                draftRevision = result.revision || canonicalHash(result.layout);
                editorGenerationId = nextEditorGenerationId();
                selectedIds = selectedIdsInLayout(draftLayout, selectedIds);
                ghost = null;
                placementAlternatives = null;
                layoutProposal = null;
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
            const hasGeneratedDraft = Boolean(generatedDraft);
            const hasDesignProposal = Boolean(designProposalDraft);
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
                canUndo: (cursor > 0 || hasGeneratedDraft || hasDesignProposal)
                    && !busy && (!desktopRecovery || (designAuthorityState === 'ready' && !desktopFreezeOwner && !desktopPending && !desktopRecoveryOwned && !desktopStartupRecoveryPending)),
                canRedo: !hasGeneratedDraft && !hasDesignProposal
                    && cursor < batches.length && !busy
                    && (!desktopRecovery || (designAuthorityState === 'ready' && !desktopFreezeOwner && !desktopPending && !desktopRecoveryOwned && !desktopStartupRecoveryPending)),
                dirty: cursor > 0 || hasGeneratedDraft || hasDesignProposal,
                canSave: (cursor > 0 || hasGeneratedDraft || hasDesignProposal)
                    && designAuthorityState === 'ready'
                    && (!desktopRecovery || desktopRecovery.allowSave)
                    && (!desktopRecovery || (!busy && !desktopFreezeOwner && !desktopPending && !desktopRecoveryOwned && !desktopStartupRecoveryPending))
                    && (!hasGeneratedDraft
                        || generatedDraft.saveEligibility === 'eligible'),
                generatedDraft: clone(generatedDraft),
                designProposalDraft: designProposalDraft ? {
                    proposalId: designProposalDraft.proposalId,
                    proposalRevision: designProposalDraft.proposalRevision,
                    transactionId: designProposalDraft.transactionId,
                    transactionRevision: designProposalDraft.transactionRevision,
                    status: designProposalDraft.status,
                    authorityLost: designProposalDraft.authorityLost === true,
                } : null,
                designAuthorityState: designAuthorityState,
                draftRevision: draftRevision,
                editorGenerationId: editorGenerationId,
                commandJournalHash: currentCommandJournalHash(),
                busy: busy,
                conflict: clone(conflict),
                selection: selectedIds.slice(),
                camera: clone(camera),
                ghostPlacement: clone(ghost),
                placementAlternatives: clone(placementAlternatives),
                layoutProposal: clone(layoutProposal),
                recentReceiptIds: recentReceiptIds.slice(),
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
            assertDesktopMutable();
            camera = nextCamera === null ? null : frozenClone(object(nextCamera, 'camera'));
            notify();
            return clone(camera);
        }

        function select(id, selectionOptions) {
            assertDesktopMutable();
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
            assertDesktopMutable();
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
            assertDesktopMutable();
            selectedIds = [];
            notify();
            return getState();
        }

        function beginGhostPlacement(asset) {
            assertDesktopMutable();
            requireLoaded();
            object(asset, 'ghost asset');
            placementAlternatives = null;
            layoutProposal = null;
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
            assertDesktopMutable();
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
            assertDesktopMutable();
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
            layoutProposal = null;
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
                layoutProposal = null;
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

        function layoutProposalReplacesContents(proposal) {
            return Boolean(
                proposal
                && Array.isArray(proposal.alternatives)
                && proposal.alternatives.length
                && proposal.alternatives.every(function (alternative) {
                    return Array.isArray(alternative.operations)
                        && alternative.operations.length
                        && alternative.operations[0].op
                            === 'clear_layout_contents';
                })
            );
        }

        function assertFullLayoutProposalReady(options) {
            requireLoaded();
            assertIdle();
            const settings = options || {};
            if (cursor > 0 && settings.allowDirtyReplacement !== true) {
                const error = new Error(
                    'Save or discard changes before requesting Auto Arrange'
                );
                error.code = 'layout_proposal_dirty';
                throw error;
            }
            if (conflict) {
                const error = new Error(
                    'Resolve the revision conflict before requesting Auto Arrange'
                );
                error.code = 'layout_proposal_conflict';
                throw error;
            }
        }

        async function requestLayoutProposal(request, options) {
            assertFullLayoutProposalReady();
            if (typeof config.createLayoutProposals !== 'function') {
                throw new Error(
                    'createLayoutProposals transport is not configured'
                );
            }
            const declarativeRequest = clone(
                object(request, 'full-layout proposal request')
            );
            const requestOptions = options || {};
            setBusy(true);
            try {
                const receipt = await config.createLayoutProposals({
                    baseRevision: baseRevision,
                    request: declarativeRequest,
                }, requestOptions.signal
                    ? { signal: requestOptions.signal }
                    : undefined);
                layoutProposal = deepFreeze(normalizeLayoutProposals(
                    receipt,
                    baseRevision,
                    declarativeRequest
                ));
                placementAlternatives = null;
                ghost = null;
                conflict = null;
                lastError = null;
            } catch (error) {
                const stale = conflictDetails(error);
                if (stale) conflict = stale;
                layoutProposal = null;
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        function installLayoutProposal(receipt, request) {
            const declarativeRequest = clone(
                object(request, 'full-layout proposal request')
            );
            const normalized = deepFreeze(normalizeLayoutProposals(
                object(receipt, 'full-layout proposal receipt'),
                baseRevision,
                declarativeRequest
            ));
            assertFullLayoutProposalReady({
                allowDirtyReplacement:
                    layoutProposalReplacesContents(normalized),
            });
            layoutProposal = normalized;
            placementAlternatives = null;
            ghost = null;
            conflict = null;
            lastError = null;
            notify();
            return getState();
        }

        function installGenerationDraft(receipt) {
            requireLoaded();
            assertIdle();
            const value = object(receipt, 'Facility generation receipt');
            const runId = nonEmptyString(value.runId, 'generation runId');
            const expectedBaseRevision = nonEmptyString(
                value.baseLayoutRevision,
                'generation baseLayoutRevision'
            );
            if (expectedBaseRevision !== baseRevision) {
                const error = new Error(
                    'Facility generation draft is bound to a stale layout revision'
                );
                error.code = 'generation_base_layout_changed';
                throw error;
            }
            draftLayout = frozenClone(
                object(value.draftLayout, 'generated Facility draft layout')
            );
            draftRevision = value.draftLayoutRevision
                ? nonEmptyString(
                    value.draftLayoutRevision,
                    'generation draftLayoutRevision'
                )
                : canonicalHash(draftLayout);
            batches = [];
            cursor = 0;
            selectedIds = selectedIdsInLayout(draftLayout, selectedIds);
            ghost = null;
            placementAlternatives = null;
            layoutProposal = null;
            generatedDraft = deepFreeze({
                runId: runId,
                status: String(value.status || 'running'),
                currentStageId: value.currentStageId || null,
                completedStageId: value.completedStageId || null,
                baseLayoutRevision: expectedBaseRevision,
                draftLayoutRevision: value.draftLayoutRevision || null,
                cumulativeDiffHash: value.cumulativeProposal
                    && value.cumulativeProposal.cumulativeDiffHash || null,
                saveEligibility: String(
                    value.saveEligibility || 'blocked'
                ),
                writable: value.writable === true,
                prototypeMode: value.prototypeMode === true,
                workflowScope: value.workflowScope || null,
                fullFactoryProgramRevision:
                    value.fullFactoryProgramRevision || null,
                receiptChain: Array.isArray(value.receiptChain)
                    ? value.receiptChain.map(String) : [],
            });
            designProposalDraft = null;
            editorGenerationId = nextEditorGenerationId();
            conflict = null;
            lastError = null;
            notify();
            return getState();
        }

        async function applyDesignProposal(proposalReference) {
            requireLoaded();
            assertIdle();
            if (designAuthorityState === 'stale_local_restore') {
                const error = new Error(
                    'Reload or rebind the Facility draft before applying another design proposal'
                );
                error.code = 'facility_design_base_rebind_required';
                throw error;
            }
            const reference = object(
                proposalReference,
                'Facility design proposal reference'
            );
            const proposalId = nonEmptyString(
                reference.proposalId,
                'Facility design proposalId'
            );
            const proposalRevision = nonEmptyString(
                reference.proposalRevision,
                'Facility design proposalRevision'
            );
            [
                'prepareDesignProposalApply',
                'commitDesignProposalApply',
                'acknowledgeDesignProposalApply',
                'recoverDesignProposalApply',
            ].forEach(function (name) {
                if (typeof config[name] !== 'function') {
                    throw new Error(name + ' transport is not configured');
                }
            });
            const previousFrame = captureDesignEditorFrame();
            const previousDesignProposal = designProposalDraft;
            const rootFrame = designProposalDraft
                ? clone(designProposalDraft.rootUndoFrame)
                : clone(previousFrame);
            const expectedEditorGenerationId = nextEditorGenerationId();
            const expectedCommandJournalHash = canonicalHash({
                rootCommandJournalHash: rootFrame.commandJournalHash,
                proposalId: proposalId,
                proposalRevision: proposalRevision,
            });
            let prepared = null;
            let committed = null;
            beginDesktopOperation('apply', { proposalId: proposalId, proposalRevision: proposalRevision });
            setBusy(true);
            try {
                const preparePayload = {
                    proposalId: proposalId,
                    proposalRevision: proposalRevision,
                    rootUndoFrame: rootFrame,
                    previousInstallationState: previousFrame,
                    expectedResultEditorGenerationId:
                        expectedEditorGenerationId,
                    expectedResultCommandJournalHash:
                        expectedCommandJournalHash,
                };
                if (designProposalDraft) {
                    preparePayload.transactionId =
                        designProposalDraft.transactionId;
                    preparePayload.expectedTransactionRevision =
                        designProposalDraft.transactionRevision;
                }
                prepared = await desktopTransport('apply-prepare', config.prepareDesignProposalApply, preparePayload);
                const preparedEnvelope = object(
                    prepared.transaction,
                    'Facility design prepared transaction'
                );
                const preparedBody = object(
                    preparedEnvelope.transaction,
                    'Facility design prepared transaction body'
                );
                const transactionId = nonEmptyString(
                    preparedBody.transactionId,
                    'Facility design transactionId'
                );
                const transactionBindingRevision = nonEmptyString(
                    prepared.transactionBindingRevision,
                    'Facility design transaction binding revision'
                );
                const candidateLayout = frozenClone(object(
                    prepared.candidateLayout,
                    'Facility design candidate layout'
                ));
                const candidateOperations = ordinaryOperations(
                    prepared.candidateOperations,
                    'Facility design candidate operations'
                );
                const resultDraftRevision = nonEmptyString(
                    preparedBody.proposalBinding.resultLayoutRevision,
                    'Facility design result layout revision'
                );
                const actualFingerprint = designInstallationFingerprint({
                    draftRevision: resultDraftRevision,
                    proposalId: proposalId,
                    proposalRevision: proposalRevision,
                    transactionBindingRevision: transactionBindingRevision,
                    editorGenerationId: expectedEditorGenerationId,
                    commandJournalHash: expectedCommandJournalHash,
                });
                if (actualFingerprint !== prepared.expectedInstallationFingerprint) {
                    const error = new Error(
                        'Facility design installation fingerprint did not match'
                    );
                    error.code = 'facility_design_installation_fingerprint_mismatch';
                    error.details = {
                        expectedInstallationFingerprint:
                            prepared.expectedInstallationFingerprint,
                        observedInstallationFingerprint: actualFingerprint,
                        fingerprintInput: {
                            draftRevision: resultDraftRevision,
                            proposalId: proposalId,
                            proposalRevision: proposalRevision,
                            transactionBindingRevision:
                                transactionBindingRevision,
                            editorGenerationId: expectedEditorGenerationId,
                            commandJournalHash: expectedCommandJournalHash,
                        },
                    };
                    throw error;
                }
                const adoption = object(
                    prepared.adoption,
                    'Facility design adoption'
                );
                const adoptionToken = nonEmptyString(
                    adoption.adoptionToken,
                    'Facility design adoption token'
                );
                committed = await desktopTransport('apply-commit', config.commitDesignProposalApply, {
                    transactionId: transactionId,
                    expectedTransactionRevision:
                        preparedEnvelope.transactionRevision,
                    adoptionToken: adoptionToken,
                });
                assertDesktopDispatch();
                const rootBatches = clone(rootFrame.batches || []).slice(
                    0,
                    Number(rootFrame.cursor) || 0
                );
                batches = frozenClone(rootBatches.concat([{
                    label: 'Apply Facility design proposal',
                    operations: clone(candidateOperations),
                }]));
                cursor = batches.length;
                draftLayout = candidateLayout;
                draftRevision = resultDraftRevision;
                selectedIds = selectedIdsInLayout(
                    draftLayout,
                    previousFrame.selectedIds || []
                );
                generatedDraft = null;
                editorGenerationId = expectedEditorGenerationId;
                designProposalDraft = {
                    proposalId: proposalId,
                    proposalRevision: proposalRevision,
                    transactionId: transactionId,
                    transactionRevision:
                        committed.transaction.transactionRevision,
                    transactionBindingRevision: transactionBindingRevision,
                    status: 'installation_pending',
                    commandJournalHash: expectedCommandJournalHash,
                    rootUndoFrame: frozenClone(rootFrame),
                    previousInstallationState: frozenClone(previousFrame),
                    authorityLost: false,
                };
                ghost = null;
                placementAlternatives = null;
                layoutProposal = null;
                const acknowledged = await desktopTransport('apply-acknowledge', config.acknowledgeDesignProposalApply, {
                    transactionId: transactionId,
                    expectedTransactionRevision:
                        committed.transaction.transactionRevision,
                    adoptionToken: adoptionToken,
                    observedInstallationFingerprint: actualFingerprint,
                });
                designProposalDraft.transactionRevision =
                    acknowledged.transaction.transactionRevision;
                designProposalDraft.status = 'active';
                conflict = null;
                lastError = null;
                await completeDesktopOperation('applied');
            } catch (error) {
                if (desktopRecovery) {
                    // A lost response is not permission to roll back or retry.
                    // Keep the installed candidate/root frame and operation ID
                    // until the native owner reconciles the backend transaction.
                    designAuthorityState = 'desktop_recovery_required';
                    lastError = error;
                    try { await persistDesktopOperation(); }
                    catch (checkpointError) { error.recoveryCheckpointError = checkpointError; }
                    throw error;
                }
                restoreDesignEditorFrame(previousFrame);
                designProposalDraft = previousDesignProposal;
                if (committed && prepared) {
                    const committedEnvelope = committed.transaction;
                    const priorProposal = previousFrame.activeProposal;
                    const observedPriorFingerprint =
                        designInstallationFingerprint({
                            draftRevision: previousFrame.draftRevision,
                            proposalId: priorProposal
                                && priorProposal.proposalId,
                            proposalRevision: priorProposal
                                && priorProposal.proposalRevision,
                            transactionBindingRevision: priorProposal
                                && priorProposal.transactionBindingRevision,
                            editorGenerationId:
                                previousFrame.editorGenerationId,
                            commandJournalHash:
                                previousFrame.commandJournalHash,
                        });
                    try {
                        await config.recoverDesignProposalApply({
                            transactionId:
                                committedEnvelope.transaction.transactionId,
                            expectedTransactionRevision:
                                committedEnvelope.transactionRevision,
                            observedInstallationFingerprint:
                                observedPriorFingerprint,
                        });
                    } catch (_recoveryError) {
                        error.recoveryError = _recoveryError;
                    }
                }
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        async function undoDesignProposal() {
            requireLoaded();
            assertIdle();
            if (!designProposalDraft) return getState();
            if (typeof config.prepareDesignUndo !== 'function') {
                throw new Error('prepareDesignUndo transport is not configured');
            }
            const pending = designProposalDraft;
            beginDesktopOperation('undo', { transactionId: pending.transactionId });
            setBusy(true);
            try {
                if (pending.status === 'undo_acknowledgment_pending') {
                    await acknowledgePendingDesignUndo(
                        pending,
                        object(
                            pending.rootUndoFrame,
                            'Facility design root Undo frame'
                        )
                    );
                    conflict = null;
                    lastError = null;
                    return getState();
                }
                await persistDesignUndoRecovery({
                    schemaVersion: 1,
                    phase: 'preparing',
                    transactionId: pending.transactionId,
                    expectedTransactionRevision:
                        pending.transactionRevision,
                });
                const prepared = await desktopTransport('undo-prepare', config.prepareDesignUndo, {
                    transactionId: pending.transactionId,
                    expectedTransactionRevision:
                        pending.transactionRevision,
                });
                assertDesktopDispatch();
                await installPreparedDesignUndo(prepared, pending);
                conflict = null;
                lastError = null;
            } catch (error) {
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        async function resumeDesignUndoRecovery(record) {
            requireLoaded();
            assertIdle();
            if (typeof config.prepareDesignUndo !== 'function') {
                throw new Error('prepareDesignUndo transport is not configured');
            }
            let recovery = record;
            if (recovery === undefined
                    && typeof config.loadDesignUndoRecovery === 'function') {
                recovery = await config.loadDesignUndoRecovery();
            }
            if (!recovery) return getState();
            const value = object(
                recovery,
                'Facility design Undo recovery record'
            );
            const transactionId = nonEmptyString(
                value.transactionId,
                'Facility design Undo recovery transactionId'
            );
            const transactionRevision = nonEmptyString(
                value.expectedTransactionRevision,
                'Facility design Undo recovery transactionRevision'
            );
            beginDesktopOperation('undo', { transactionId: transactionId });
            setBusy(true);
            try {
                const prepared = await desktopTransport('undo-prepare', config.prepareDesignUndo, {
                    transactionId: transactionId,
                    expectedTransactionRevision: transactionRevision,
                });
                assertDesktopDispatch();
                await installPreparedDesignUndo(prepared, null);
                conflict = null;
                lastError = null;
            } catch (error) {
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        function cycleLayoutProposal(offset) {
            requireLoaded();
            assertIdle();
            if (!layoutProposal) {
                throw new Error('full-layout proposal is not active');
            }
            const delta = offset === undefined ? 1 : finite(
                offset,
                'layout proposal offset'
            );
            if (!Number.isInteger(delta)) {
                throw new TypeError(
                    'layout proposal offset must be an integer'
                );
            }
            const count = layoutProposal.alternatives.length;
            const nextIndex = (
                (layoutProposal.selectedIndex + delta) % count + count
            ) % count;
            layoutProposal = deepFreeze({
                ...layoutProposal,
                selectedIndex: nextIndex,
            });
            notify();
            return getState();
        }

        async function dismissLayoutProposal(options) {
            requireLoaded();
            assertIdle();
            if (!layoutProposal) {
                throw new Error('full-layout proposal is not active');
            }
            const proposalIds = layoutProposal.alternatives.map(
                function (alternative) { return alternative.proposalId; }
            );
            const requestOptions = options || {};
            layoutProposal = null;
            notify();
            if (typeof config.cancelLayoutProposal !== 'function') {
                return getState();
            }
            setBusy(true);
            try {
                await Promise.all(proposalIds.map(function (proposalId) {
                    return config.cancelLayoutProposal(
                        { proposalId: proposalId },
                        requestOptions.signal
                            ? { signal: requestOptions.signal }
                            : undefined
                    );
                }));
                lastError = null;
            } catch (error) {
                lastError = error;
                throw error;
            } finally {
                setBusy(false);
            }
            return getState();
        }

        async function approveAndApplyLayoutProposal(options) {
            assertFullLayoutProposalReady({
                allowDirtyReplacement:
                    layoutProposalReplacesContents(layoutProposal),
            });
            if (!layoutProposal) {
                throw new Error('full-layout proposal is not active');
            }
            [
                ['getLayoutProposalPreview', config.getLayoutProposalPreview],
                ['approveLayoutProposal', config.approveLayoutProposal],
                ['applyLayoutProposal', config.applyLayoutProposal],
            ].forEach(function (entry) {
                if (typeof entry[1] !== 'function') {
                    throw new Error(entry[0] + ' transport is not configured');
                }
            });
            const proposal = layoutProposal;
            const selectedIndex = proposal.selectedIndex;
            const selected = proposal.alternatives[selectedIndex];
            const requestOptions = options || {};
            const transportOptions = requestOptions.signal
                ? { signal: requestOptions.signal }
                : undefined;
            let appliedReceipt = null;
            let approvalReceipt = null;
            let idempotencyKey = null;
            setBusy(true);
            try {
                const previewReceipt = await config.getLayoutProposalPreview(
                    { proposalId: selected.proposalId },
                    transportOptions
                );
                normalizeLayoutProposalPreview(
                    previewReceipt,
                    selected,
                    baseRevision
                );
                if (layoutProposal !== proposal
                        || layoutProposal.selectedIndex !== selectedIndex) {
                    throw layoutProposalStale(
                        'Full-layout proposal changed during revalidation'
                    );
                }
                idempotencyKey = createIdempotencyKey(config);
                approvalReceipt = await config.approveLayoutProposal({
                    proposalId: selected.proposalId,
                    binding: clone(selected.transactionBinding),
                    idempotencyKey: idempotencyKey,
                    explicitApproval: true,
                }, transportOptions);
                const approvalToken = nonEmptyString(
                    object(
                        approvalReceipt,
                        'layout proposal approval receipt'
                    ).approvalToken,
                    'approvalToken'
                );
                appliedReceipt = await config.applyLayoutProposal({
                    approvalToken: approvalToken,
                    binding: clone(selected.transactionBinding),
                    idempotencyKey: idempotencyKey,
                }, transportOptions);
                rememberReceipt(appliedReceipt);
                const savedSelection = selectedIds.slice();
                installReceipt(appliedReceipt, true);
                selectedIds = selectedIdsInLayout(
                    draftLayout,
                    savedSelection
                );
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
                receipt: clone(appliedReceipt),
                approval: clone(approvalReceipt),
                idempotencyKey: idempotencyKey,
            };
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
            const placement = placementFromRequest(request, position);
            return commitGesture('Place asset', [{
                op: 'place_asset',
                placement: placement,
            }], 'created');
        }

        function placementFromRequest(request, position) {
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
            return placement;
        }

        async function placeAssets(requests) {
            if (!Array.isArray(requests) || !requests.length) {
                throw new TypeError('placement requests must be a non-empty array');
            }
            const operations = requests.map(function (request, index) {
                object(request, 'placement request ' + index);
                return {
                    op: 'place_asset',
                    placement: placementFromRequest(
                        request,
                        worldPosition(request.worldPosition || request.position)
                    ),
                };
            });
            return commitGesture(
                requests.length === 1 ? 'Add asset' : 'Add assets',
                operations,
                'created'
            );
        }

        function selectedPlacements() {
            requireLoaded();
            const expanded = expandedCellItemIds(draftLayout, selectedIds);
            const attached = expandedSurfaceAttachmentPlacementIds(
                draftLayout, expanded
            );
            return expandedStackPlacementIds(draftLayout, attached).map(function (id) {
                return placementById(draftLayout, id);
            }).filter(Boolean);
        }

        function selectedCellZones() {
            requireLoaded();
            return selectedIds.map(function (id) {
                return zoneById(draftLayout, id);
            }).filter(function (zone) {
                return Boolean(cellGroupMetadata(zone));
            });
        }

        function verticalStackRelationship(placement) {
            const relationship = placement && placement.snapRelationship;
            return relationship && relationship.family === 'vertical_stack'
                && typeof relationship.stackId === 'string'
                && relationship.stackId
                ? relationship : null;
        }

        function surfaceAttachmentRelationship(placement) {
            const relationship = placement && placement.snapRelationship;
            return relationship && relationship.family === 'surface_attachment'
                && typeof relationship.supportPlacementId === 'string'
                && relationship.supportPlacementId
                ? relationship : null;
        }

        function expandedSurfaceAttachmentPlacementIds(layout, identifiers) {
            const requested = Array.isArray(identifiers) ? identifiers : [];
            const placements = layout && Array.isArray(layout.placements)
                ? layout.placements : [];
            const requestedSet = new Set(requested);
            let changed = true;
            while (changed) {
                changed = false;
                placements.forEach(function (placement) {
                    const relationship = surfaceAttachmentRelationship(placement);
                    if (!relationship
                            || !requestedSet.has(relationship.supportPlacementId)
                            || requestedSet.has(placement.placementId)) return;
                    requestedSet.add(placement.placementId);
                    changed = true;
                });
            }
            return placements.map(function (placement) {
                return placement.placementId;
            }).filter(function (placementId) {
                return requestedSet.has(placementId);
            }).concat(requested.filter(function (identifier) {
                return !placements.some(function (placement) {
                    return placement.placementId === identifier;
                });
            }));
        }

        function surfaceAttachmentDepth(layout, placementId, trail) {
            const visited = trail || new Set();
            if (visited.has(placementId)) return 0;
            visited.add(placementId);
            const relationship = surfaceAttachmentRelationship(
                placementById(layout, placementId)
            );
            if (!relationship) return 0;
            return 1 + surfaceAttachmentDepth(
                layout,
                relationship.supportPlacementId,
                visited
            );
        }

        function expandedStackPlacementIds(layout, identifiers) {
            const requested = Array.isArray(identifiers) ? identifiers : [];
            const placements = layout && Array.isArray(layout.placements)
                ? layout.placements : [];
            const requestedSet = new Set(requested);
            const stackIds = new Set();
            placements.forEach(function (placement) {
                if (!requestedSet.has(placement.placementId)) return;
                const relationship = verticalStackRelationship(placement);
                if (relationship) stackIds.add(relationship.stackId);
            });
            placements.forEach(function (placement) {
                const relationship = verticalStackRelationship(placement);
                if (relationship && stackIds.has(relationship.stackId)) {
                    requestedSet.add(placement.placementId);
                }
            });
            return placements.map(function (placement) {
                return placement.placementId;
            }).filter(function (placementId) {
                return requestedSet.has(placementId);
            });
        }

        function nextStackId(sourceStackId) {
            stackSequence += 1;
            return String(sourceStackId || 'stack') + ':copy:'
                + (config.operationIdNamespace || Date.now().toString(36)) + ':' + stackSequence.toString(36);
        }

        function nextPlacementId() {
            placementSequence += 1;
            return 'pl-surface-copy-' + (config.operationIdNamespace || Date.now().toString(36)) + '-'
                + placementSequence.toString(36);
        }

        function nextAttachmentId(sourceAttachmentId) {
            attachmentSequence += 1;
            return String(sourceAttachmentId || 'surface') + ':copy:'
                + (config.operationIdNamespace || Date.now().toString(36)) + ':'
                + attachmentSequence.toString(36);
        }

        function duplicatePlacementContext(placements) {
            const sourceIds = new Set(placements.map(function (placement) {
                return placement.placementId;
            }));
            const copiesSurfaceGroup = placements.some(function (placement) {
                const relationship = surfaceAttachmentRelationship(placement);
                return relationship
                    && sourceIds.has(relationship.supportPlacementId);
            });
            const placementIds = new Map();
            if (copiesSurfaceGroup) {
                placements.forEach(function (placement) {
                    placementIds.set(placement.placementId, nextPlacementId());
                });
            }
            return {
                placementIds: placementIds,
                attachmentIds: new Map(),
                stackIds: new Map(),
            };
        }

        function copiedPlacementRelationship(placement, context) {
            const stackRelationship = verticalStackRelationship(placement);
            if (stackRelationship) {
                if (!context.stackIds.has(stackRelationship.stackId)) {
                    context.stackIds.set(
                        stackRelationship.stackId,
                        nextStackId(stackRelationship.stackId)
                    );
                }
                return Object.assign({}, clone(stackRelationship), {
                    stackId: context.stackIds.get(stackRelationship.stackId),
                });
            }
            const relationship = surfaceAttachmentRelationship(placement);
            if (!relationship
                    || !context.placementIds.has(relationship.supportPlacementId)) {
                return null;
            }
            const attachmentId = String(
                relationship.attachmentId
                || relationship.supportPlacementId + ':surface'
            );
            if (!context.attachmentIds.has(attachmentId)) {
                context.attachmentIds.set(
                    attachmentId,
                    nextAttachmentId(attachmentId)
                );
            }
            return Object.assign({}, clone(relationship), {
                attachmentId: context.attachmentIds.get(attachmentId),
                supportPlacementId: context.placementIds.get(
                    relationship.supportPlacementId
                ),
            });
        }

        function selectedFloorMarkings() {
            requireLoaded();
            return expandedCellItemIds(draftLayout, selectedIds).map(function (id) {
                return floorMarkingById(draftLayout, id);
            }).filter(Boolean);
        }

        async function moveSelected(delta) {
            const movement = worldPosition(delta);
            const placements = selectedPlacements();
            const movingPlacementIds = new Set(placements.map(function (placement) {
                return placement.placementId;
            }));
            const operations = [];
            placements.forEach(function (placement) {
                const current = placement.transform.position;
                operations.push({
                    op: 'move_placement',
                    placementId: placement.placementId,
                    position: {
                        x: current.x + movement.x,
                        y: current.y + movement.y,
                        z: current.z + movement.z,
                    },
                    movementKind: 'user',
                });
                const relationship = surfaceAttachmentRelationship(placement);
                if (!relationship
                        || movingPlacementIds.has(relationship.supportPlacementId)) {
                    return;
                }
                const support = placementById(
                    draftLayout,
                    relationship.supportPlacementId
                );
                if (!support) {
                    throw new TypeError(
                        "surface support '" + relationship.supportPlacementId
                        + "' does not exist"
                    );
                }
                const localPosition = rotateFloorVector({
                    x: current.x + movement.x - support.transform.position.x,
                    z: current.z + movement.z - support.transform.position.z,
                }, -quaternionYawDegrees(support.transform.quaternion));
                const currentOffset = finite(
                    relationship.normalOffsetMeters || 0,
                    'surface normal offset'
                );
                const nextOffset = relationship.side === 'below'
                    ? currentOffset - movement.y
                    : currentOffset + movement.y;
                if (nextOffset < -1e-9) {
                    throw new RangeError(
                        'surface movement cannot cross through the support plane'
                    );
                }
                operations.push({
                    op: 'set_snap_relationship',
                    placementId: placement.placementId,
                    snapRelationship: Object.assign({}, clone(relationship), {
                        localPosition: localPosition,
                        normalOffsetMeters: Math.max(0, nextOffset),
                    }),
                });
            });
            selectedFloorMarkings().forEach(function (marking) {
                const current = marking.transform.position;
                operations.push({
                    op: 'edit_floor_marking',
                    markingId: marking.markingId,
                    patch: {
                        transform: {
                            position: {
                                x: current.x + movement.x,
                                y: current.y + movement.y,
                                z: current.z + movement.z,
                            },
                            rotationDegrees: marking.transform.rotationDegrees,
                        },
                        positionMode: 'manual',
                    },
                });
            });
            selectedCellZones().forEach(function (zone) {
                const bounds = zoneBounds(zone.boundary);
                const geometry = {
                    minX: bounds.minX + movement.x,
                    minZ: bounds.minZ + movement.z,
                    width: bounds.maxX - bounds.minX,
                    depth: bounds.maxZ - bounds.minZ,
                };
                operations.push({
                    op: 'edit_zone',
                    zoneId: zone.zoneId,
                    patch: {
                        boundary: zoneBoundaryAt(zone.boundary, geometry),
                        anchors: transformedZoneAnchorsForGeometry(
                            zone,
                            geometry
                        ),
                        floorElevation: finite(
                            zone.floorElevation,
                            'zone floor elevation'
                        ) + movement.y,
                    },
                });
            });
            return commitGesture('Move selection', operations, 'preserve');
        }

        async function movePlacements(updates, label) {
            requireLoaded();
            if (!Array.isArray(updates)) {
                throw new TypeError('placement updates must be an array');
            }
            const seen = new Set();
            const normalizedUpdates = updates.map(function (update, index) {
                object(update, 'placement update ' + index);
                const placementId = nonEmptyString(
                    update.placementId,
                    'placement update ID'
                );
                if (seen.has(placementId)) {
                    throw new TypeError('placement update IDs must be unique');
                }
                seen.add(placementId);
                if (!placementById(draftLayout, placementId)) {
                    throw new TypeError(
                        "placement '" + placementId + "' does not exist"
                    );
                }
                return {
                    placementId: placementId,
                    position: worldPosition(update.position),
                };
            });
            const updateById = new Map(normalizedUpdates.map(function (update) {
                return [update.placementId, update];
            }));
            normalizedUpdates.forEach(function (update) {
                const source = placementById(draftLayout, update.placementId);
                const relationship = verticalStackRelationship(source);
                if (!relationship) return;
                const current = source.transform.position;
                const delta = {
                    x: update.position.x - current.x,
                    y: update.position.y - current.y,
                    z: update.position.z - current.z,
                };
                draftLayout.placements.forEach(function (placement) {
                    const member = verticalStackRelationship(placement);
                    if (!member || member.stackId !== relationship.stackId
                            || updateById.has(placement.placementId)) return;
                    const position = placement.transform.position;
                    updateById.set(placement.placementId, {
                        placementId: placement.placementId,
                        position: {
                            x: position.x + delta.x,
                            y: position.y + delta.y,
                            z: position.z + delta.z,
                        },
                    });
                });
            });
            let attachmentExpanded = true;
            while (attachmentExpanded) {
                attachmentExpanded = false;
                draftLayout.placements.forEach(function (placement) {
                    if (updateById.has(placement.placementId)) return;
                    const relationship = surfaceAttachmentRelationship(placement);
                    if (!relationship) return;
                    const supportUpdate = updateById.get(
                        relationship.supportPlacementId
                    );
                    if (!supportUpdate) return;
                    const support = placementById(
                        draftLayout,
                        relationship.supportPlacementId
                    );
                    if (!support) return;
                    const supportPosition = support.transform.position;
                    const position = placement.transform.position;
                    updateById.set(placement.placementId, {
                        placementId: placement.placementId,
                        position: {
                            x: position.x
                                + supportUpdate.position.x - supportPosition.x,
                            y: position.y
                                + supportUpdate.position.y - supportPosition.y,
                            z: position.z
                                + supportUpdate.position.z - supportPosition.z,
                        },
                    });
                    attachmentExpanded = true;
                });
            }
            const operations = [];
            Array.from(updateById.values()).forEach(function (update) {
                operations.push({
                    op: 'move_placement',
                    placementId: update.placementId,
                    position: update.position,
                    movementKind: 'user',
                });
            });
            Array.from(updateById.values()).forEach(function (update) {
                const placement = placementById(draftLayout, update.placementId);
                const relationship = surfaceAttachmentRelationship(placement);
                if (!relationship) return;
                const support = placementById(
                    draftLayout,
                    relationship.supportPlacementId
                );
                if (!support) {
                    throw new TypeError(
                        "surface support '" + relationship.supportPlacementId
                        + "' does not exist"
                    );
                }
                const supportUpdate = updateById.get(support.placementId);
                const supportPosition = supportUpdate
                    ? supportUpdate.position : support.transform.position;
                const childPosition = placement.transform.position;
                const childDeltaY = update.position.y - childPosition.y;
                const supportDeltaY = supportUpdate
                    ? supportUpdate.position.y - support.transform.position.y : 0;
                const relativeDeltaY = childDeltaY - supportDeltaY;
                const currentOffset = finite(
                    relationship.normalOffsetMeters || 0,
                    'surface normal offset'
                );
                const nextOffset = relationship.side === 'below'
                    ? currentOffset - relativeDeltaY
                    : currentOffset + relativeDeltaY;
                if (nextOffset < -1e-9) {
                    throw new RangeError(
                        'surface movement cannot cross through the support plane'
                    );
                }
                operations.push({
                    op: 'set_snap_relationship',
                    placementId: placement.placementId,
                    snapRelationship: Object.assign({}, clone(relationship), {
                        localPosition: rotateFloorVector({
                            x: update.position.x - supportPosition.x,
                            z: update.position.z - supportPosition.z,
                        }, -quaternionYawDegrees(support.transform.quaternion)),
                        normalOffsetMeters: Math.max(0, nextOffset),
                    }),
                });
            });
            return commitGesture(
                label || 'Position placements',
                operations,
                'preserve'
            );
        }

        async function rotateSelected90(turns) {
            const count = turns === undefined ? 1 : finite(turns, 'quarter turns');
            if (!Number.isInteger(count)) {
                throw new TypeError('quarter turns must be an integer');
            }
            const rotation = quarterTurnQuaternion(count);
            const placements = selectedPlacements();
            const rotatingIds = new Set(placements.map(function (placement) {
                return placement.placementId;
            }));
            const positionCache = new Map();
            function rotatedPosition(placement) {
                if (positionCache.has(placement.placementId)) {
                    return positionCache.get(placement.placementId);
                }
                const relationship = surfaceAttachmentRelationship(placement);
                const support = relationship
                    ? placementById(draftLayout, relationship.supportPlacementId)
                    : null;
                if (!support || !rotatingIds.has(support.placementId)) {
                    const unchanged = clone(placement.transform.position);
                    positionCache.set(placement.placementId, unchanged);
                    return unchanged;
                }
                const supportPosition = rotatedPosition(support);
                const local = relationship.localPosition || { x: 0, z: 0 };
                const worldOffset = rotateFloorVector(
                    local,
                    quaternionYawDegrees(support.transform.quaternion) + count * 90
                );
                const result = {
                    x: supportPosition.x + worldOffset.x,
                    y: placement.transform.position.y,
                    z: supportPosition.z + worldOffset.z,
                };
                positionCache.set(placement.placementId, result);
                return result;
            }
            const operations = [];
            placements.forEach(function (placement) {
                const relationship = surfaceAttachmentRelationship(placement);
                const supportRotates = relationship
                    && rotatingIds.has(relationship.supportPlacementId);
                if (supportRotates) {
                    operations.push({
                        op: 'move_placement',
                        placementId: placement.placementId,
                        position: rotatedPosition(placement),
                        movementKind: 'user',
                    });
                }
                operations.push({
                    op: 'rotate_placement',
                    placementId: placement.placementId,
                    quaternion: multiplyQuaternion(
                        rotation,
                        quaternion(placement.transform.quaternion)
                    ),
                    movementKind: 'user',
                });
                if (relationship && !supportRotates) {
                    operations.push({
                        op: 'set_snap_relationship',
                        placementId: placement.placementId,
                        snapRelationship: Object.assign({}, clone(relationship), {
                            localRotationDegrees: finite(
                                relationship.localRotationDegrees || 0,
                                'surface local rotation'
                            ) + count * 90,
                        }),
                    });
                }
            });
            selectedFloorMarkings().forEach(function (marking) {
                operations.push({
                    op: 'edit_floor_marking',
                    markingId: marking.markingId,
                    patch: {
                        transform: {
                            position: clone(marking.transform.position),
                            rotationDegrees:
                                marking.transform.rotationDegrees + count * 90,
                        },
                        positionMode: 'manual',
                    },
                });
            });
            return commitGesture('Rotate selection', operations, 'preserve');
        }

        async function duplicatePlacements(placementIds, offset) {
            requireLoaded();
            if (!Array.isArray(placementIds)) {
                throw new TypeError('placementIds must be an array');
            }
            const delta = worldPosition(offset || DEFAULT_DUPLICATE_OFFSET);
            const seen = new Set();
            const expandedIds = expandedStackPlacementIds(
                draftLayout,
                expandedSurfaceAttachmentPlacementIds(draftLayout, placementIds)
            );
            const placements = expandedIds.map(function (placementId, index) {
                const identifier = nonEmptyString(
                    placementId,
                    'placementIds[' + index + ']'
                );
                if (seen.has(identifier)) return null;
                seen.add(identifier);
                return placementById(draftLayout, identifier);
            }).filter(Boolean);
            const duplicateContext = duplicatePlacementContext(placements);
            const operations = placements.map(function (placement) {
                const current = placement.transform.position;
                const operation = {
                    op: 'duplicate_placement',
                    sourcePlacementId: placement.placementId,
                    position: {
                        x: current.x + delta.x,
                        y: current.y + delta.y,
                        z: current.z + delta.z,
                    },
                    positionMode: 'manual',
                };
                if (duplicateContext.placementIds.has(placement.placementId)) {
                    operation.newPlacementId = duplicateContext.placementIds.get(
                        placement.placementId
                    );
                }
                const relationship = copiedPlacementRelationship(
                    placement,
                    duplicateContext
                );
                if (relationship) {
                    operation.snapRelationship = relationship;
                }
                return operation;
            });
            return commitGesture(
                placements.length === 1
                    ? 'Duplicate placement' : 'Duplicate placements',
                operations,
                'created'
            );
        }

        async function duplicateItems(itemIds, offset) {
            requireLoaded();
            if (!Array.isArray(itemIds)) {
                throw new TypeError('itemIds must be an array');
            }
            const delta = worldPosition(offset || DEFAULT_DUPLICATE_OFFSET);
            const seen = new Set();
            const expandedCellIds = expandedCellItemIds(draftLayout, itemIds);
            const expandedPlacementIds = new Set(expandedStackPlacementIds(
                draftLayout,
                expandedSurfaceAttachmentPlacementIds(
                    draftLayout,
                    expandedCellIds
                )
            ));
            const requestedItems = expandedCellIds.concat(
                Array.from(expandedPlacementIds)
            );
            const duplicateContext = duplicatePlacementContext(
                Array.from(expandedPlacementIds).map(function (placementId) {
                    return placementById(draftLayout, placementId);
                }).filter(Boolean)
            );
            const cellSequences = new Map();
            (draftLayout.zones || []).forEach(function (zone) {
                const metadata = cellGroupMetadata(zone);
                const autoNumber = metadata && metadata.autoNumber;
                if (!autoNumber || !autoNumber.seriesId) return;
                const sequence = Math.max(
                    0,
                    Math.round(Number(autoNumber.sequence) || 0)
                );
                cellSequences.set(
                    autoNumber.seriesId,
                    Math.max(cellSequences.get(autoNumber.seriesId) || 0, sequence)
                );
            });
            const operations = [];
            requestedItems.forEach(function (itemId, index) {
                const identifier = nonEmptyString(
                    itemId,
                    'itemIds[' + index + ']'
                );
                if (seen.has(identifier)) return;
                seen.add(identifier);
                const placement = placementById(draftLayout, identifier);
                if (placement) {
                    const current = placement.transform.position;
                    const operation = {
                        op: 'duplicate_placement',
                        sourcePlacementId: identifier,
                        position: {
                            x: current.x + delta.x,
                            y: current.y + delta.y,
                            z: current.z + delta.z,
                        },
                        positionMode: 'manual',
                    };
                    if (duplicateContext.placementIds.has(identifier)) {
                        operation.newPlacementId = duplicateContext.placementIds.get(
                            identifier
                        );
                    }
                    const relationship = copiedPlacementRelationship(
                        placement,
                        duplicateContext
                    );
                    if (relationship) {
                        operation.snapRelationship = relationship;
                    }
                    operations.push(operation);
                    return;
                }
                const marking = floorMarkingById(draftLayout, identifier);
                if (marking) {
                    const copy = clone(marking);
                    delete copy.markingId;
                    copy.transform.position.x += delta.x;
                    copy.transform.position.y += delta.y;
                    copy.transform.position.z += delta.z;
                    copy.positionMode = 'manual';
                    operations.push({
                        op: 'add_floor_marking',
                        floorMarking: copy,
                    });
                    return;
                }
                const zone = zoneById(draftLayout, identifier);
                if (!zone || !cellGroupMetadata(zone)) return;
                const copy = clone(zone);
                delete copy.zoneId;
                const bounds = zoneBounds(zone.boundary);
                const geometry = {
                    minX: bounds.minX + delta.x,
                    minZ: bounds.minZ + delta.z,
                    width: bounds.maxX - bounds.minX,
                    depth: bounds.maxZ - bounds.minZ,
                };
                copy.boundary = zoneBoundaryAt(zone.boundary, geometry);
                copy.anchors = transformedZoneAnchorsForGeometry(zone, geometry);
                transformedCellInterfaces(copy, {
                    sourceAnchor: { x: bounds.minX, z: bounds.minZ },
                    targetAnchor: { x: geometry.minX, z: geometry.minZ },
                    rotationDeltaDegrees: 0,
                });
                copy.floorElevation = finite(
                    copy.floorElevation,
                    'zone floor elevation'
                ) + delta.y;
                const metadata = cellGroupMetadata(copy);
                const autoNumber = metadata && metadata.autoNumber;
                if (autoNumber && autoNumber.seriesId) {
                    const next = (cellSequences.get(autoNumber.seriesId) || 0) + 1;
                    cellSequences.set(autoNumber.seriesId, next);
                    autoNumber.sequence = next;
                    copy.label = cellGroupLabel(autoNumber);
                }
                operations.push({ op: 'add_zone', zone: copy });
            });
            return commitGesture(
                operations.length === 1 ? 'Duplicate item' : 'Duplicate items',
                operations,
                'created'
            );
        }

        async function duplicateSelected(offset) {
            return duplicateItems(
                selectedIds.slice(),
                offset || DEFAULT_DUPLICATE_OFFSET
            );
        }

        function transformedZoneAnchor(anchor, copy) {
            const result = clone(anchor);
            if (copy.mirrored === true && copy.mirrorAxis) {
                const start = worldPoint(copy.mirrorAxis.start);
                const end = worldPoint(copy.mirrorAxis.end);
                const dx = end.x - start.x;
                const dz = end.z - start.z;
                const length = Math.hypot(dx, dz);
                if (!(length > 1e-9)) {
                    throw new RangeError('pattern mirror axis is invalid');
                }
                const unit = { x: dx / length, z: dz / length };
                if (result.position) {
                    const point = worldPoint(result.position);
                    const offset = {
                        x: point.x - start.x,
                        z: point.z - start.z,
                    };
                    const projection = offset.x * unit.x
                        + offset.z * unit.z;
                    result.position = Object.assign({}, result.position, {
                        x: start.x + 2 * projection * unit.x - offset.x,
                        z: start.z + 2 * projection * unit.z - offset.z,
                    });
                }
                if (result.facing) {
                    const facing = worldPoint(result.facing);
                    const projection = facing.x * unit.x
                        + facing.z * unit.z;
                    result.facing = Object.assign({}, result.facing, {
                        x: 2 * projection * unit.x - facing.x,
                        z: 2 * projection * unit.z - facing.z,
                    });
                }
                return result;
            }
            if (result.position) {
                const transformed = transformFloorPoint(
                    result.position,
                    copy.sourceAnchor,
                    copy.targetAnchor,
                    copy.rotationDeltaDegrees || 0
                );
                result.position = Object.assign({}, result.position, transformed);
            }
            if (result.facing) {
                const facing = rotateFloorVector(
                    result.facing,
                    copy.rotationDeltaDegrees || 0
                );
                result.facing = Object.assign({}, result.facing, facing);
            }
            return result;
        }

        function transformedCellInterfaces(zone, copy) {
            const metadata = cellGroupMetadata(zone);
            const source = metadata && metadata.functionalInterfaces;
            if (!source || typeof source !== 'object') return;
            const sideVectors = {
                north: { x: 0, z: 1 },
                east: { x: 1, z: 0 },
                south: { x: 0, z: -1 },
                west: { x: -1, z: 0 },
            };
            const cardinalSide = function (vector) {
                const tolerance = 1e-6;
                if (Math.abs(vector.x) <= tolerance) {
                    if (Math.abs(vector.z - 1) <= tolerance) return 'north';
                    if (Math.abs(vector.z + 1) <= tolerance) return 'south';
                }
                if (Math.abs(vector.z) <= tolerance) {
                    if (Math.abs(vector.x - 1) <= tolerance) return 'east';
                    if (Math.abs(vector.x + 1) <= tolerance) return 'west';
                }
                return '';
            };
            Object.keys(source).forEach(function (role) {
                const record = source[role];
                if (!record || typeof record !== 'object') return;
                if (record.position) {
                    record.position = transformedZoneAnchor({
                        position: record.position,
                    }, copy).position;
                }
                if (Array.isArray(record.accessEnvelope)) {
                    record.accessEnvelope = record.accessEnvelope.map(function (point) {
                        return transformedZoneAnchor({
                            position: point,
                        }, copy).position;
                    });
                    if (copy.mirrored === true) {
                        record.accessEnvelope.reverse();
                    }
                }
                const sourceFacing = record.facing || sideVectors[record.side];
                if (!sourceFacing) return;
                const transformed = transformedZoneAnchor({
                    facing: { x: sourceFacing.x, y: 0, z: sourceFacing.z },
                }, copy).facing;
                const side = cardinalSide(transformed);
                if (side) {
                    record.side = side;
                    delete record.facing;
                } else {
                    delete record.side;
                    record.facing = { x: transformed.x, z: transformed.z };
                }
                record.evidenceStatus = 'derived';
            });
        }

        function patternCopyGroupKey(copy) {
            const instance = Number(copy && copy.instanceIndex);
            return Number.isFinite(instance)
                ? 'instance:' + String(instance)
                : 'single-copy-group';
        }

        function patternDuplicateContexts(copies) {
            const placementsByGroup = new Map();
            (Array.isArray(copies) ? copies : []).forEach(function (copy) {
                if (!copy || copy.kind !== 'placement') return;
                const source = placementById(draftLayout, copy.sourceId);
                if (!source) return;
                const key = patternCopyGroupKey(copy);
                if (!placementsByGroup.has(key)) placementsByGroup.set(key, []);
                const group = placementsByGroup.get(key);
                if (!group.some(function (placement) {
                    return placement.placementId === source.placementId;
                })) {
                    group.push(source);
                }
            });
            const contexts = new Map();
            placementsByGroup.forEach(function (placements, key) {
                contexts.set(key, duplicatePlacementContext(placements));
            });
            return contexts;
        }

        function patternCopyOperation(
            copy,
            index,
            cellSequences,
            duplicateContexts,
            provenance
        ) {
            object(copy, 'pattern copy ' + index);
            const sourceId = nonEmptyString(copy.sourceId, 'pattern source ID');
            const position = worldPosition(copy.position);
            const placement = placementById(draftLayout, sourceId);
            if (placement && copy.kind === 'placement') {
                const duplicateContext = duplicateContexts
                    && duplicateContexts.get(patternCopyGroupKey(copy));
                const operation = {
                    op: 'duplicate_placement',
                    sourcePlacementId: sourceId,
                    position: position,
                    positionMode: 'manual',
                    layoutProvenance: Object.assign(
                        {}, clone(provenance), {
                            instanceIndex: copy.instanceIndex,
                        }
                    ),
                };
                if (duplicateContext
                        && duplicateContext.placementIds.has(sourceId)) {
                    operation.newPlacementId = duplicateContext.placementIds.get(
                        sourceId
                    );
                }
                const copiedRelationship = duplicateContext
                    ? copiedPlacementRelationship(placement, duplicateContext)
                    : null;
                if (copy.snapRelationship || copiedRelationship) {
                    operation.snapRelationship = clone(
                        copy.snapRelationship || copiedRelationship
                    );
                }
                if (copy.mirrored === true) {
                    operation.quaternion = yawQuaternion(finite(
                        copy.rotationDegrees,
                        'pattern mirror rotation'
                    ));
                    return operation;
                }
                const rotationDelta = finite(
                    copy.rotationDeltaDegrees || 0,
                    'pattern rotation delta'
                );
                if (Math.abs(rotationDelta) > 1e-9) {
                    operation.quaternion = multiplyQuaternion(
                        yawQuaternion(rotationDelta),
                        quaternion(placement.transform.quaternion)
                    );
                }
                return operation;
            }
            const marking = floorMarkingById(draftLayout, sourceId);
            if (marking && copy.kind === 'floor-marking') {
                const value = clone(marking);
                delete value.markingId;
                value.transform = {
                    position: position,
                    rotationDegrees: finite(
                        copy.rotationDegrees,
                        'pattern floor marking rotation'
                    ),
                };
                value.positionMode = 'manual';
                value.metadata = Object.assign({}, clone(value.metadata || {}), {
                    layoutProvenance: Object.assign(
                        {}, clone(provenance), {
                            instanceIndex: copy.instanceIndex,
                        }
                    ),
                });
                return { op: 'add_floor_marking', floorMarking: value };
            }
            const zone = zoneById(draftLayout, sourceId);
            if (zone && copy.kind === 'zone') {
                const value = clone(zone);
                delete value.zoneId;
                value.boundary = (copy.boundary || []).map(worldPoint);
                value.anchors = (value.anchors || []).map(function (anchor) {
                    return transformedZoneAnchor(anchor, copy);
                });
                const metadata = cellGroupMetadata(value);
                const autoNumber = metadata && metadata.autoNumber;
                if (autoNumber && autoNumber.seriesId && cellSequences) {
                    const next = (cellSequences.get(autoNumber.seriesId) || 0) + 1;
                    cellSequences.set(autoNumber.seriesId, next);
                    autoNumber.sequence = next;
                    value.label = cellGroupLabel(autoNumber);
                }
                transformedCellInterfaces(value, copy);
                value.extensions = Object.assign(
                    {}, clone(value.extensions || {}), {
                        layoutProvenance: Object.assign(
                            {}, clone(provenance), {
                                instanceIndex: copy.instanceIndex,
                            }
                        ),
                    }
                );
                return { op: 'add_zone', zone: value };
            }
            throw new TypeError(
                "pattern source '" + sourceId + "' does not match kind '"
                + String(copy.kind || '') + "'"
            );
        }

        function patternMoveOperations(move, index, provenance) {
            object(move, 'pattern move ' + index);
            const sourceId = nonEmptyString(move.sourceId, 'pattern move source ID');
            const position = worldPosition(move.position);
            const placement = placementById(draftLayout, sourceId);
            if (placement && move.kind === 'placement') {
                return [{
                    op: 'move_placement',
                    placementId: sourceId,
                    position: position,
                    movementKind: 'user',
                    layoutProvenance: clone(provenance),
                }, {
                    op: 'rotate_placement',
                    placementId: sourceId,
                    quaternion: yawQuaternion(finite(
                        move.rotationDegrees,
                        'pattern placement rotation'
                    )),
                    movementKind: 'user',
                    layoutProvenance: clone(provenance),
                }];
            }
            const marking = floorMarkingById(draftLayout, sourceId);
            if (marking && move.kind === 'floor-marking') {
                return [{
                    op: 'edit_floor_marking',
                    markingId: sourceId,
                    patch: {
                        transform: {
                            position: position,
                            rotationDegrees: finite(
                                move.rotationDegrees,
                                'pattern floor marking rotation'
                            ),
                        },
                        positionMode: 'manual',
                    },
                    layoutProvenance: clone(provenance),
                }];
            }
            const zone = zoneById(draftLayout, sourceId);
            if (zone && move.kind === 'zone') {
                const value = clone(zone);
                transformedCellInterfaces(value, move);
                return [{
                    op: 'edit_zone',
                    zoneId: sourceId,
                    patch: {
                        boundary: (move.boundary || []).map(worldPoint),
                        anchors: (value.anchors || []).map(function (anchor) {
                            return transformedZoneAnchor(anchor, move);
                        }),
                        extensions: value.extensions,
                    },
                    layoutProvenance: clone(provenance),
                }];
            }
            throw new TypeError(
                "pattern move source '" + sourceId + "' does not exist"
            );
        }

        async function applyPattern(result, label) {
            requireLoaded();
            object(result, 'pattern result');
            const copies = Array.isArray(result.copies) ? result.copies : [];
            const moves = Array.isArray(result.moves) ? result.moves : [];
            const relationships = Array.isArray(result.relationships)
                ? result.relationships : [];
            patternSequence += 1;
            const seedEntityIds = Array.from(new Set(
                copies.concat(moves).concat(relationships).map(function (item) {
                    return item && item.sourceId;
                }).filter(Boolean)
            )).sort();
            const supportId = result.guide
                && result.guide.supportPlacementId;
            if (supportId && !seedEntityIds.includes(supportId)) {
                seedEntityIds.push(supportId);
                seedEntityIds.sort();
            }
            const command = {
                linear: 'linear_pattern',
                circular: 'circular_pattern',
                perimeter: 'perimeter',
                'cell-layout': 'cell_layout',
                'vertical-stack': 'vertical_stack',
                'surface-stack': 'surface_stack',
                mirror: 'mirror',
                swap: 'swap',
            }[result.mode];
            if (!command) {
                throw new TypeError('pattern result mode is unsupported');
            }
            const provenance = {
                schemaVersion: 1,
                provenanceId: 'layout-pattern:' + (config.operationIdNamespace || Date.now().toString(36))
                    + ':' + patternSequence.toString(36),
                command: command,
                authoredStrategy: result.mode === 'cell-layout'
                    ? (result.shape || null) : null,
                seedEntityIds: seedEntityIds,
                parameters: Object.assign({
                    count: result.count,
                    seedCount: result.seedCount,
                }, clone(result.guide || {})),
                manuallyEditedSinceCreation: false,
            };
            const cellSequences = new Map();
            (draftLayout.zones || []).forEach(function (zone) {
                const metadata = cellGroupMetadata(zone);
                const autoNumber = metadata && metadata.autoNumber;
                if (!autoNumber || !autoNumber.seriesId) return;
                const sequence = Math.max(
                    0,
                    Math.round(Number(autoNumber.sequence) || 0)
                );
                cellSequences.set(
                    autoNumber.seriesId,
                    Math.max(cellSequences.get(autoNumber.seriesId) || 0, sequence)
                );
            });
            const duplicateContexts = patternDuplicateContexts(copies);
            const operations = copies.map(function (copy, index) {
                return patternCopyOperation(
                    copy,
                    index,
                    cellSequences,
                    duplicateContexts,
                    provenance
                );
            });
            relationships.forEach(function (relationship, index) {
                object(relationship, 'pattern relationship ' + index);
                if (relationship.kind !== 'placement') {
                    throw new TypeError(
                        'pattern relationships currently support placements only'
                    );
                }
                operations.push({
                    op: 'set_snap_relationship',
                    placementId: nonEmptyString(
                        relationship.sourceId,
                        'pattern relationship source ID'
                    ),
                    snapRelationship: clone(relationship.snapRelationship),
                    layoutProvenance: clone(provenance),
                });
            });
            moves.forEach(function (move, index) {
                patternMoveOperations(move, index, provenance).forEach(function (operation) {
                    operations.push(operation);
                });
            });
            if (!operations.length) {
                throw new TypeError('pattern result contains no changes');
            }
            operations[0].layoutProvenance = clone(provenance);
            operations[0].layoutProvenanceSeedEntityIds = seedEntityIds.slice();
            return commitGesture(
                label || (copies.length ? 'Create pattern' : 'Arrange cell'),
                operations,
                ['vertical-stack', 'surface-stack'].includes(result.mode)
                    ? 'preserve'
                    : (copies.length ? 'created' : 'preserve')
            );
        }

        async function setPlanSettings(settings) {
            requireLoaded();
            const value = object(settings, 'plan settings');
            return commitGesture('Resize facility plan', [{
                op: 'set_plan_settings',
                planSettings: clone(value),
            }], 'preserve');
        }

        async function clearLayout() {
            requireLoaded();
            return commitGesture('Clear facility layout', [{
                op: 'clear_layout_contents',
            }], []);
        }

        async function deleteSelected() {
            requireLoaded();
            const expandedIds = expandedCellItemIds(draftLayout, selectedIds);
            const placementIds = expandedStackPlacementIds(
                draftLayout,
                expandedSurfaceAttachmentPlacementIds(draftLayout, expandedIds)
            ).filter(function (id) {
                return Boolean(placementById(draftLayout, id));
            }).sort(function (left, right) {
                return surfaceAttachmentDepth(draftLayout, right)
                    - surfaceAttachmentDepth(draftLayout, left);
            });
            const zoneIds = expandedIds.filter(function (id) {
                return Boolean(zoneById(draftLayout, id));
            });
            const markingIds = expandedIds.filter(function (id) {
                return Boolean(floorMarkingById(draftLayout, id));
            });
            const routeIds = expandedIds.filter(function (id) {
                return Boolean(routeById(draftLayout, id));
            });
            const operations = placementIds.map(function (placementId) {
                return { op: 'delete_placement', placementId: placementId };
            }).concat(zoneIds.map(function (zoneId) {
                return { op: 'delete_zone', zoneId: zoneId };
            })).concat(markingIds.map(function (markingId) {
                return {
                    op: 'delete_floor_marking',
                    markingId: markingId,
                };
            })).concat(routeIds.map(function (routeId) {
                return {
                    op: 'delete_route',
                    routeId: routeId,
                };
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
            }).concat(selectedFloorMarkings().map(function (marking) {
                return {
                    op: 'edit_floor_marking',
                    markingId: marking.markingId,
                    patch: { positionMode: positionMode },
                };
            }));
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
                    extensions: normalized.extensions,
                },
            }], 'created');
        }

        async function createZones(requests) {
            requireLoaded();
            if (!Array.isArray(requests) || !requests.length) {
                throw new TypeError('zone requests must be a non-empty array');
            }
            const operations = requests.map(function (request, index) {
                const source = object(request, 'zone request ' + index);
                const normalized = normalizeZoneOptions(source);
                const minX = finite(source.minX, 'zone request minimum X');
                const minZ = finite(source.minZ, 'zone request minimum Z');
                const width = positive(source.width, 'zone request width');
                const depth = positive(source.depth, 'zone request depth');
                return {
                    op: 'add_zone',
                    zone: {
                        zoneType: normalized.zoneType,
                        label: normalized.label,
                        boundary: rectangleBoundary(
                            { x: minX, z: minZ },
                            { x: minX + width, z: minZ + depth }
                        ),
                        floorElevation: normalized.floorElevation,
                        anchors: normalized.anchors,
                        evidence: normalized.evidence,
                        extensions: normalized.extensions,
                    },
                };
            });
            return commitGesture(
                'Create ' + operations.length + ' facility zones',
                operations,
                'created'
            );
        }

        async function createCellGroup(request) {
            requireLoaded();
            const source = object(request, 'cell group request');
            const baseName = nonEmptyString(
                source.baseName || 'Manufacturing Cell',
                'cell group base name'
            ).trim();
            const prefix = String(source.prefix || '').trim();
            const sequence = Math.max(
                0,
                Math.round(finite(
                    source.start === undefined ? 1 : source.start,
                    'cell group starting number'
                ))
            );
            const padding = Math.max(
                1,
                Math.min(6, Math.round(finite(
                    source.numberPadding === undefined
                        ? 2 : source.numberPadding,
                    'cell group number padding'
                )))
            );
            const seriesId = nonEmptyString(
                source.seriesId,
                'cell group series ID'
            );
            const autoNumber = {
                seriesId: seriesId,
                baseName: baseName,
                prefix: prefix,
                start: sequence,
                padding: padding,
                sequence: sequence,
            };
            const interfaceRoles = ['gate', 'loading', 'service'];
            const interfaceSides = new Set([
                'north', 'east', 'south', 'west',
            ]);
            const functionalInterfaces = {};
            const requestedInterfaces = source.functionalInterfaces
                && typeof source.functionalInterfaces === 'object'
                ? source.functionalInterfaces : {};
            interfaceRoles.forEach(function (role) {
                const raw = requestedInterfaces[role];
                const side = typeof raw === 'string'
                    ? raw : raw && raw.side;
                if (!interfaceSides.has(side)) return;
                functionalInterfaces[role] = {
                    side: side,
                    evidenceStatus: 'authored',
                };
            });
            const extensions = Object.assign({}, clone(source.extensions || {}), {
                cellGroup: {
                    schemaVersion: 1,
                    groupKind: 'manufacturing_cell',
                    membership: 'geometric',
                    envelopePadding: Math.max(
                        0,
                        finite(source.envelopePadding || 0, 'cell envelope padding')
                    ),
                    autoNumber: autoNumber,
                    functionalInterfaces: functionalInterfaces,
                },
            });
            return createZones([{
                label: cellGroupLabel(autoNumber),
                zoneType: 'workcell',
                minX: finite(source.minX, 'cell group minimum X'),
                minZ: finite(source.minZ, 'cell group minimum Z'),
                width: positive(source.width, 'cell group width'),
                depth: positive(source.depth, 'cell group depth'),
                extensions: extensions,
            }]);
        }

        async function ungroupCell(zoneId) {
            requireLoaded();
            const id = nonEmptyString(zoneId, 'cell group zone ID');
            const zone = zoneById(draftLayout, id);
            if (!zone || !cellGroupMetadata(zone)) {
                throw new Error("zone '" + id + "' is not a manufacturing cell");
            }
            return commitGesture('Ungroup manufacturing cell', [{
                op: 'delete_zone',
                zoneId: id,
            }], []);
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
                    extensions: normalized.extensions,
                },
            }], 'created');
        }

        function transformedZoneAnchorsForGeometry(zone, geometry) {
            const anchors = Array.isArray(zone.anchors) ? zone.anchors : [];
            if (!anchors.length) return [];
            const source = zoneBounds(zone.boundary);
            const sourceWidth = source.maxX - source.minX;
            const sourceDepth = source.maxZ - source.minZ;
            return anchors.map(function (anchor) {
                const copy = clone(anchor);
                if (!copy.position || !(sourceWidth > 0) || !(sourceDepth > 0)) {
                    return copy;
                }
                const position = worldPosition(copy.position);
                copy.position = Object.assign({}, copy.position, {
                    x: geometry.minX
                        + ((position.x - source.minX) / sourceWidth) * geometry.width,
                    z: geometry.minZ
                        + ((position.z - source.minZ) / sourceDepth) * geometry.depth,
                });
                return copy;
            });
        }

        async function editZoneGeometry(zoneId, geometry) {
            requireLoaded();
            const id = nonEmptyString(zoneId, 'zoneId');
            const zone = zoneById(draftLayout, id);
            if (!zone) throw new Error("unknown zone '" + id + "'");
            const current = zoneBounds(zone.boundary);
            const source = object(geometry, 'zone geometry');
            const normalized = {
                minX: source.minX === undefined
                    ? current.minX : finite(source.minX, 'zone minimum X'),
                minZ: source.minZ === undefined
                    ? current.minZ : finite(source.minZ, 'zone minimum Z'),
                width: source.width === undefined
                    ? current.maxX - current.minX
                    : positive(source.width, 'zone width'),
                depth: source.depth === undefined
                    ? current.maxZ - current.minZ
                    : positive(source.depth, 'zone depth'),
            };
            return commitGesture('Edit zone geometry', [{
                op: 'edit_zone',
                zoneId: id,
                patch: {
                    boundary: zoneBoundaryAt(zone.boundary, normalized),
                    anchors: transformedZoneAnchorsForGeometry(zone, normalized),
                },
            }], [id]);
        }

        async function editZoneDimensions(zoneId, dimensions) {
            requireLoaded();
            const id = nonEmptyString(zoneId, 'zoneId');
            const zone = zoneById(draftLayout, id);
            if (!zone) throw new Error("unknown zone '" + id + "'");
            const source = object(dimensions, 'zone dimensions');
            const boundary = resizedZoneBoundary(
                zone.boundary,
                source.width,
                source.depth
            );
            const bounds = zoneBounds(boundary);
            const geometry = {
                minX: bounds.minX,
                minZ: bounds.minZ,
                width: bounds.maxX - bounds.minX,
                depth: bounds.maxZ - bounds.minZ,
            };
            return commitGesture('Resize zone', [{
                op: 'edit_zone',
                zoneId: id,
                patch: {
                    boundary: boundary,
                    anchors: transformedZoneAnchorsForGeometry(zone, geometry),
                },
            }], [id]);
        }

        async function editZoneLabel(zoneId, label) {
            requireLoaded();
            const id = nonEmptyString(zoneId, 'zoneId');
            const zone = zoneById(draftLayout, id);
            if (!zone) throw new Error("unknown zone '" + id + "'");
            const nextLabel = nonEmptyString(label, 'zone label').trim();
            if (nextLabel.length > 120) {
                throw new RangeError('zone label must be 120 characters or fewer');
            }
            if (zone.label === nextLabel) return getState();
            return commitGesture('Rename zone', [{
                op: 'edit_zone',
                zoneId: id,
                patch: { label: nextLabel },
            }], [id]);
        }

        async function editZoneType(zoneId, zoneType) {
            requireLoaded();
            const id = nonEmptyString(zoneId, 'zoneId');
            const zone = zoneById(draftLayout, id);
            if (!zone) throw new Error("unknown zone '" + id + "'");
            const nextType = nonEmptyString(zoneType, 'zone type').trim();
            if (zone.zoneType === nextType) return getState();
            return commitGesture('Change zone purpose', [{
                op: 'edit_zone',
                zoneId: id,
                patch: { zoneType: nextType },
            }], [id]);
        }

        async function createFloorMarking(request) {
            return commitGesture('Create floor marking', [{
                op: 'add_floor_marking',
                floorMarking: normalizeFloorMarking(request),
            }], 'created');
        }

        async function editFloorMarking(markingId, patch) {
            requireLoaded();
            const id = nonEmptyString(markingId, 'markingId');
            const current = floorMarkingById(draftLayout, id);
            if (!current) throw new Error("unknown floor marking '" + id + "'");
            const merged = Object.assign({}, clone(current), clone(patch || {}));
            if (patch && patch.transform) {
                merged.transform = Object.assign(
                    {},
                    clone(current.transform),
                    clone(patch.transform)
                );
            }
            const normalized = normalizeFloorMarking(merged);
            delete normalized.markingId;
            return commitGesture('Edit floor marking', [{
                op: 'edit_floor_marking',
                markingId: id,
                patch: normalized,
            }], [id]);
        }

        async function createAisle(request) {
            requireLoaded();
            return commitGesture('Create facility aisle', [{
                op: 'add_aisle',
                aisle: clone(object(request, 'facility aisle')),
            }], 'created');
        }

        async function editAisle(routeId, patch) {
            requireLoaded();
            const id = nonEmptyString(routeId, 'routeId');
            if (!routeById(draftLayout, id)) {
                throw new Error("unknown route '" + id + "'");
            }
            return commitGesture('Edit facility aisle', [{
                op: 'edit_aisle',
                routeId: id,
                patch: clone(object(patch, 'facility aisle patch')),
            }], [id]);
        }

        async function setFacilityNavigation(facilityNavigation) {
            requireLoaded();
            return commitGesture('Edit motion path', [{
                op: 'set_facility_navigation',
                authoringSource: 'plan_pointer',
                facilityNavigation: clone(object(
                    facilityNavigation,
                    'facilityNavigation'
                )),
            }], 'preserve');
        }

        async function proposeFacilityNavigation(facilityNavigation) {
            requireLoaded();
            return commitGesture('Propose navigation intent', [{
                op: 'set_facility_navigation',
                authoringSource: 'sage_semantic',
                facilityNavigation: clone(object(
                    facilityNavigation,
                    'facilityNavigation'
                )),
            }], 'preserve');
        }

        async function undo() {
            if (designProposalDraft) {
                return undoDesignProposal();
            }
            if (generatedDraft) {
                requireLoaded();
                assertIdle();
                const pending = clone(generatedDraft);
                setBusy(true);
                try {
                    if (pending.writable && pending.authorityLost !== true) {
                        if (typeof config.undoGenerationDraft !== 'function') {
                            throw new Error(
                                'Generated Facility undo transport is not configured'
                            );
                        }
                        await config.undoGenerationDraft({
                            runId: pending.runId,
                        });
                    }
                    draftLayout = baseLayout;
                    draftRevision = baseRevision;
                    generatedDraft = null;
                    editorGenerationId = nextEditorGenerationId();
                    selectedIds = selectedIdsInLayout(
                        draftLayout, selectedIds
                    );
                    ghost = null;
                    placementAlternatives = null;
                    layoutProposal = null;
                    conflict = null;
                    lastError = null;
                } catch (error) {
                    lastError = error;
                    throw error;
                } finally {
                    setBusy(false);
                }
                return getState();
            }
            return recompute(cursor - 1);
        }

        async function redo() {
            return recompute(cursor + 1);
        }

        async function save() {
            if (desktopRecovery && !desktopRecovery.allowSave) throw desktopError(
                'facility_desktop_save_disabled', 'Save is disabled in this desktop acceptance profile');
            requireLoaded();
            if (designAuthorityState === 'stale_local_restore') {
                const error = new Error(
                    'Reload or rebind the Facility draft before saving it'
                );
                error.code = 'facility_design_base_rebind_required';
                throw error;
            }
            assertIdle();
            // A lost native reply can leave no pending handle in this renderer
            // while its design authority still requires recovery. Enforce the
            // same authority requirement as canSave before every transport.
            if (designAuthorityState !== 'ready') {
                throw desktopError('facility_design_authority_unresolved',
                    'Resolve Facility design authority before saving it');
            }
            if (designProposalDraft) {
                if (typeof config.saveDesignProposalDraft !== 'function') {
                    throw new Error(
                        'Facility design save transport is not configured'
                    );
                }
                const pending = clone(designProposalDraft);
                let savedDesign = null;
                setBusy(true);
                try {
                    savedDesign = await config.saveDesignProposalDraft({
                        transactionId: pending.transactionId,
                        expectedTransactionRevision:
                            pending.transactionRevision,
                        observedDraftRevision: draftRevision,
                        observedCommandJournalHash:
                            currentCommandJournalHash(),
                        explicitApproval: true,
                    });
                    const savedSelection = selectedIds.slice();
                    installReceipt(savedDesign.savedLayout, true);
                    selectedIds = selectedIdsInLayout(
                        draftLayout, savedSelection
                    );
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
                    receipt: clone(savedDesign.saveReceipt),
                    designTransaction: clone(savedDesign.transaction),
                };
            }
            if (generatedDraft) {
                if (generatedDraft.saveEligibility !== 'eligible') {
                    const error = new Error(
                        'Generated Facility draft is not ready to save'
                    );
                    error.code = 'generation_run_not_save_eligible';
                    throw error;
                }
                if (typeof config.saveGenerationDraft !== 'function') {
                    throw new Error(
                        'Generated Facility save transport is not configured'
                    );
                }
                const pending = clone(generatedDraft);
                let savedGeneration = null;
                setBusy(true);
                try {
                    savedGeneration = await config.saveGenerationDraft({
                        runId: pending.runId,
                        cumulativeDiffHash: pending.cumulativeDiffHash,
                        explicitApproval: true,
                    });
                    const savedReceipt = savedGeneration.savedLayout;
                    installReceipt(savedReceipt, true);
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
                    receipt: clone(savedGeneration.saveReceipt),
                    generationRun: clone(savedGeneration.run),
                };
            }
            if (!cursor) return getState();
            const operations = currentOperations();
            let savedReceipt = null;
            setBusy(true);
            try {
                savedReceipt = await config.applyOperations({
                    baseRevision: baseRevision,
                    operations: clone(operations),
                });
                rememberReceipt(savedReceipt);
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
            if (generatedDraft) {
                const error = new Error(
                    'Use Undo to cancel the generated Facility draft'
                );
                error.code = 'generated_draft_undo_required';
                throw error;
            }
            if (designProposalDraft) {
                const error = new Error(
                    'Use Undo to restore the pre-proposal Facility draft'
                );
                error.code = 'design_proposal_undo_required';
                throw error;
            }
            draftLayout = baseLayout;
            draftRevision = baseRevision;
            batches = [];
            cursor = 0;
            selectedIds = selectedIdsInLayout(draftLayout, selectedIds);
            ghost = null;
            placementAlternatives = null;
            layoutProposal = null;
            editorGenerationId = nextEditorGenerationId();
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
            captureDesignEditorFrame: captureDesignEditorFrame,
            installDesktopRecovery: installDesktopRecovery,
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
            requestLayoutProposal: requestLayoutProposal,
            installLayoutProposal: installLayoutProposal,
            installGenerationDraft: installGenerationDraft,
            applyDesignProposal: applyDesignProposal,
            installConstructionApproval: installConstructionApproval,
            undoDesignProposal: undoDesignProposal,
            resumeDesignUndoRecovery: resumeDesignUndoRecovery,
            cycleLayoutProposal: cycleLayoutProposal,
            dismissLayoutProposal: dismissLayoutProposal,
            approveAndApplyLayoutProposal: approveAndApplyLayoutProposal,
            placeAsset: placeAsset,
            placeAssets: placeAssets,
            moveSelected: moveSelected,
            movePlacements: movePlacements,
            rotateSelected90: rotateSelected90,
            duplicatePlacements: duplicatePlacements,
            duplicateItems: duplicateItems,
            duplicateSelected: duplicateSelected,
            applyPattern: applyPattern,
            setPlanSettings: setPlanSettings,
            clearLayout: clearLayout,
            deleteSelected: deleteSelected,
            lockSelected: function () { return setSelectedLocked(true); },
            unlockSelected: function () { return setSelectedLocked(false); },
            createRectangleZone: createRectangleZone,
            createZones: createZones,
            createCellGroup: createCellGroup,
            ungroupCell: ungroupCell,
            createPolygonZone: createPolygonZone,
            editZoneGeometry: editZoneGeometry,
            editZoneDimensions: editZoneDimensions,
            editZoneLabel: editZoneLabel,
            editZoneType: editZoneType,
            createFloorMarking: createFloorMarking,
            editFloorMarking: editFloorMarking,
            createAisle: createAisle,
            editAisle: editAisle,
            setFacilityNavigation: setFacilityNavigation,
            proposeFacilityNavigation: proposeFacilityNavigation,
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
