(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityTransport = api;
}(typeof window !== 'undefined'
    ? window
    : (typeof self !== 'undefined' ? self : null), function () {
    'use strict';

    const API_VERSION = 1;
    const MAX_SESSION_ID_LENGTH = 128;
    const HASH_PATTERN = /^[0-9a-f]{64}$/;
    let sessionSequence = 0;

    function nonEmptyString(value, label) {
        if (typeof value !== 'string' || !value.trim()) {
            throw new TypeError(label + ' must be a non-empty string');
        }
        return value.trim();
    }

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function boundedIdentifier(value, label, maximum) {
        const result = nonEmptyString(value, label);
        if (result.length > (maximum || 128)
                || !/^[A-Za-z0-9][A-Za-z0-9._:@+-]*$/.test(result)) {
            throw new TypeError(label + ' is malformed');
        }
        return result;
    }

    function hash(value, label) {
        const result = nonEmptyString(value, label);
        if (!HASH_PATTERN.test(result)) {
            throw new TypeError(label + ' must be a lowercase SHA-256 hash');
        }
        return result;
    }

    function opaqueToken(value, label, maximum) {
        const result = nonEmptyString(value, label);
        if (result.length > (maximum || 256)
                || !/^[A-Za-z0-9][A-Za-z0-9._~:-]*$/.test(result)) {
            throw new TypeError(label + ' is malformed');
        }
        return result;
    }

    function idempotencyKey(value) {
        const result = nonEmptyString(value, 'idempotencyKey');
        if (result.length < 8 || result.length > 128
                || !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(result)) {
            throw new TypeError('idempotencyKey is malformed');
        }
        return result;
    }

    function defaultSessionId() {
        sessionSequence += 1;
        const cryptoApi = typeof globalThis !== 'undefined'
            ? globalThis.crypto : null;
        if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
            return 'fls-' + cryptoApi.randomUUID();
        }
        return 'fls-' + Date.now().toString(36)
            + '-' + sessionSequence.toString(36);
    }

    function operationBatch(value) {
        if (!Array.isArray(value)) {
            throw new TypeError('operations must be an array');
        }
        return clone(value);
    }

    function object(value, label) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new TypeError(label + ' must be an object');
        }
        return value;
    }

    function declarativeLayoutRequest(value) {
        const source = object(value, 'layout proposal request');
        if (source.schemaVersion !== 1) {
            throw new TypeError('layout proposal request schemaVersion must equal 1');
        }
        nonEmptyString(source.requestId, 'layout proposal requestId');
        nonEmptyString(source.objective, 'layout proposal objective');
        if (!Array.isArray(source.assetSet)) {
            throw new TypeError('layout proposal assetSet must be an array');
        }
        if (!Array.isArray(source.strategies) || !source.strategies.length) {
            throw new TypeError(
                'layout proposal strategies must be a non-empty array'
            );
        }
        return clone(source);
    }

    function transactionBinding(value) {
        const source = object(value, 'transaction binding');
        const target = object(source.target, 'transaction binding target');
        return {
            target: {
                domain: boundedIdentifier(
                    target.domain,
                    'transaction binding target domain'
                ),
                scopeId: boundedIdentifier(
                    target.scopeId,
                    'transaction binding target scopeId'
                ),
                resourceId: boundedIdentifier(
                    target.resourceId,
                    'transaction binding target resourceId'
                ),
            },
            baseRevision: hash(
                source.baseRevision,
                'transaction binding baseRevision'
            ),
            diffHash: hash(source.diffHash, 'transaction binding diffHash'),
            dependencyFingerprint: hash(
                source.dependencyFingerprint,
                'transaction binding dependencyFingerprint'
            ),
        };
    }

    function worldPosition(value, label) {
        const source = object(value, label);
        const result = {
            x: Number(source.x),
            y: source.y === undefined ? 0 : Number(source.y),
            z: Number(source.z),
        };
        if (!Object.keys(result).every(function (key) {
            return Number.isFinite(result[key]);
        })) {
            throw new TypeError(label + ' must contain finite x, y, and z');
        }
        return result;
    }

    function spatialCandidateRequest(value) {
        const container = object(value, 'placement candidate payload');
        const source = object(
            container.request || container,
            'placement candidate request'
        );
        const request = {
            assetId: nonEmptyString(source.assetId, 'assetId'),
            assetDefinitionRevision: nonEmptyString(
                source.assetDefinitionRevision,
                'assetDefinitionRevision'
            ),
            requestedPosition: worldPosition(
                source.requestedPosition,
                'requestedPosition'
            ),
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

    function errorFromResponse(response, body) {
        const envelope = body && typeof body === 'object'
            ? (body.error || body)
            : {};
        const error = new Error(
            envelope.message
            || ('Facility Layout request failed with HTTP ' + response.status)
        );
        error.name = 'FacilityLayoutTransportError';
        error.status = response.status;
        error.code = envelope.code || 'facility_layout_request_failed';
        error.details = clone(envelope.details || {});
        if (error.details.currentRevision) {
            error.currentRevision = error.details.currentRevision;
        }
        error.body = clone(body);
        return error;
    }

    function createHttpTransport(inputOptions) {
        const options = inputOptions || {};
        const fetchImpl = options.fetch
            || (typeof fetch === 'function' ? fetch.bind(globalThis) : null);
        if (typeof fetchImpl !== 'function') {
            throw new TypeError('fetch implementation is required');
        }
        const siteId = nonEmptyString(options.siteId, 'siteId');
        const layoutId = nonEmptyString(options.layoutId, 'layoutId');
        const baseUrl = String(options.baseUrl || '').replace(/\/+$/, '');
        const headers = Object.assign({}, options.headers || {});
        const sessionId = boundedIdentifier(
            options.sessionId || defaultSessionId(),
            'sessionId',
            MAX_SESSION_ID_LENGTH
        );
        const encodedSite = encodeURIComponent(siteId);
        const encodedLayout = encodeURIComponent(layoutId);
        const layoutUrl = baseUrl + '/api/facility-layouts/'
            + encodedSite + '/' + encodedLayout;
        const generationUrl = baseUrl + '/api/facility-layout-generation/'
            + encodedSite + '/' + encodedLayout;

        async function request(path, method, body, requestOptions) {
            const requestConfig = requestOptions || {};
            const init = {
                method: method || 'GET',
                cache: 'no-store',
                credentials: options.credentials || 'same-origin',
                headers: Object.assign({}, headers),
            };
            init.headers['X-InspectorPro-Session'] = sessionId;
            if (requestConfig.signal) init.signal = requestConfig.signal;
            if (body !== undefined) {
                init.headers['Content-Type'] = 'application/json';
                init.body = JSON.stringify(body);
            }
            const response = await fetchImpl(layoutUrl + (path || ''), init);
            const result = await response.json().catch(function () {
                return {};
            });
            if (!response.ok) throw errorFromResponse(response, result);
            return result;
        }

        async function generationRequest(path, method, body, requestOptions) {
            const requestConfig = requestOptions || {};
            const init = {
                method: method || 'GET',
                cache: 'no-store',
                credentials: options.credentials || 'same-origin',
                headers: Object.assign({}, headers),
            };
            init.headers['X-InspectorPro-Session'] = sessionId;
            if (requestConfig.signal) init.signal = requestConfig.signal;
            if (body !== undefined) {
                init.headers['Content-Type'] = 'application/json';
                init.body = JSON.stringify(body);
            }
            const response = await fetchImpl(
                generationUrl + (path || ''), init
            );
            const result = await response.json().catch(function () {
                return {};
            });
            if (!response.ok) throw errorFromResponse(response, result);
            return result;
        }

        return Object.freeze({
            apiVersion: API_VERSION,
            siteId: siteId,
            layoutId: layoutId,
            layoutUrl: layoutUrl,
            generationUrl: generationUrl,
            sessionId: sessionId,
            startG1Generation: function (payload, requestOptions) {
                const value = object(payload, 'G1 generation payload');
                return generationRequest('/g1', 'POST', value, requestOptions);
            },
            continueGenerationRun: function (payload, requestOptions) {
                const value = object(payload, 'generation continuation payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/continue',
                    'POST',
                    {
                        explicitStageAcceptance:
                            value.explicitStageAcceptance === true,
                    },
                    requestOptions
                );
            },
            getGenerationRun: function (payload, requestOptions) {
                const value = object(payload, 'generation run payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId),
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            undoGenerationRun: function (payload, requestOptions) {
                const value = object(payload, 'generation undo payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/undo',
                    'POST',
                    {},
                    requestOptions
                );
            },
            saveGenerationRun: function (payload, requestOptions) {
                const value = object(payload, 'generation save payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                if (value.explicitApproval !== true) {
                    throw new TypeError('explicitApproval must equal true');
                }
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/save',
                    'POST',
                    {
                        cumulativeDiffHash: nonEmptyString(
                            value.cumulativeDiffHash,
                            'cumulativeDiffHash'
                        ),
                        explicitApproval: true,
                    },
                    requestOptions
                );
            },
            previewOperations: function (payload) {
                const value = payload || {};
                return request('/preview', 'POST', {
                    baseRevision: nonEmptyString(
                        value.baseRevision,
                        'baseRevision'
                    ),
                    operations: operationBatch(value.operations),
                });
            },
            applyOperations: function (payload) {
                const value = payload || {};
                return request('', 'PUT', {
                    baseRevision: nonEmptyString(
                        value.baseRevision,
                        'baseRevision'
                    ),
                    operations: operationBatch(value.operations),
                });
            },
            reloadLayout: function () {
                return request('', 'GET');
            },
            spatialDiagnostics: function (payload, requestOptions) {
                const value = payload || {};
                return request('/spatial/diagnostics', 'POST', {
                    baseRevision: nonEmptyString(
                        value.baseRevision,
                        'baseRevision'
                    ),
                    operations: operationBatch(value.operations || []),
                }, requestOptions);
            },
            placementCandidates: function (payload, requestOptions) {
                const value = payload || {};
                return request(
                    '/spatial/candidates',
                    'POST',
                    {
                        baseRevision: nonEmptyString(
                            value.baseRevision,
                            'baseRevision'
                        ),
                        operations: operationBatch(value.operations || []),
                        request: spatialCandidateRequest(value),
                    },
                    requestOptions
                );
            },
            placementCandidatePreview: function (payload, requestOptions) {
                const value = payload || {};
                return request(
                    '/spatial/candidates/preview',
                    'POST',
                    {
                        baseRevision: nonEmptyString(
                            value.baseRevision,
                            'baseRevision'
                        ),
                        operations: operationBatch(value.operations || []),
                        request: spatialCandidateRequest(value),
                        candidateId: nonEmptyString(
                            value.candidateId,
                            'candidateId'
                        ),
                    },
                    requestOptions
                );
            },
            createLayoutProposals: function (payload, requestOptions) {
                const value = object(payload, 'layout proposal payload');
                return request('/proposals', 'POST', {
                    baseRevision: nonEmptyString(
                        value.baseRevision,
                        'baseRevision'
                    ),
                    request: declarativeLayoutRequest(value.request),
                }, requestOptions);
            },
            getLayoutProposalPreview: function (payload, requestOptions) {
                const value = object(payload, 'layout proposal preview payload');
                const proposalId = boundedIdentifier(
                    value.proposalId,
                    'proposalId'
                );
                return request(
                    '/proposals/' + encodeURIComponent(proposalId) + '/preview',
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            cancelLayoutProposal: function (payload, requestOptions) {
                const value = object(payload, 'layout proposal cancel payload');
                const proposalId = boundedIdentifier(
                    value.proposalId,
                    'proposalId'
                );
                return request(
                    '/proposals/' + encodeURIComponent(proposalId),
                    'DELETE',
                    undefined,
                    requestOptions
                );
            },
            approveLayoutProposal: function (payload, requestOptions) {
                const value = object(payload, 'layout proposal approval payload');
                if (value.explicitApproval !== true) {
                    throw new TypeError('explicitApproval must equal true');
                }
                return request('/approvals', 'POST', {
                    proposalId: boundedIdentifier(
                        value.proposalId,
                        'proposalId'
                    ),
                    binding: transactionBinding(value.binding),
                    idempotencyKey: idempotencyKey(value.idempotencyKey),
                    explicitApproval: true,
                }, requestOptions);
            },
            applyLayoutProposal: function (payload, requestOptions) {
                const value = object(payload, 'layout proposal apply payload');
                return request('/apply', 'POST', {
                    approvalToken: opaqueToken(
                        value.approvalToken,
                        'approvalToken',
                        256
                    ),
                    binding: transactionBinding(value.binding),
                    idempotencyKey: idempotencyKey(value.idempotencyKey),
                }, requestOptions);
            },
            getLayoutReceipt: function (payload, requestOptions) {
                const value = object(payload, 'layout receipt payload');
                const receiptId = boundedIdentifier(
                    value.receiptId,
                    'receiptId'
                );
                return request(
                    '/receipts/' + encodeURIComponent(receiptId),
                    'GET',
                    undefined,
                    requestOptions
                );
            },
        });
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        createHttpTransport: createHttpTransport,
    });
}));
