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
        const encodedSite = encodeURIComponent(siteId);
        const encodedLayout = encodeURIComponent(layoutId);
        const layoutUrl = baseUrl + '/api/facility-layouts/'
            + encodedSite + '/' + encodedLayout;

        async function request(path, method, body, requestOptions) {
            const requestConfig = requestOptions || {};
            const init = {
                method: method || 'GET',
                cache: 'no-store',
                credentials: options.credentials || 'same-origin',
                headers: Object.assign({}, headers),
            };
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

        return Object.freeze({
            apiVersion: API_VERSION,
            siteId: siteId,
            layoutId: layoutId,
            layoutUrl: layoutUrl,
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
        });
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        createHttpTransport: createHttpTransport,
    });
}));
