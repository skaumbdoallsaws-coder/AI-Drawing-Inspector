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
    const NAVIGATION_ACTIVITY_MAXIMUM_ACTORS = 64;
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

    function motionPackageRequest(value) {
        const source = object(value, 'motion package request');
        const allowed = new Set([
            'routeId',
            'vehicleProfileRef',
            'vehiclePlacementId',
            'load',
            'allowReverse',
            'travelDirection',
        ]);
        Object.keys(source).forEach(function (key) {
            if (!allowed.has(key)) {
                throw new TypeError(
                    'motion package request field ' + key + ' is not supported'
                );
            }
        });
        const profile = object(
            source.vehicleProfileRef,
            'vehicleProfileRef'
        );
        const result = {
            routeId: boundedIdentifier(source.routeId, 'routeId'),
            vehicleProfileRef: {
                vehicleProfileId: boundedIdentifier(
                    profile.vehicleProfileId,
                    'vehicleProfileId'
                ),
                vehicleProfileRevision: hash(
                    profile.vehicleProfileRevision,
                    'vehicleProfileRevision'
                ),
            },
        };
        if (source.vehiclePlacementId !== undefined) {
            result.vehiclePlacementId = boundedIdentifier(
                source.vehiclePlacementId,
                'vehiclePlacementId'
            );
        }
        if (source.load !== undefined) result.load = clone(object(source.load, 'load'));
        if (source.allowReverse !== undefined) {
            if (typeof source.allowReverse !== 'boolean') {
                throw new TypeError('allowReverse must be a boolean');
            }
            result.allowReverse = source.allowReverse;
        }
        if (source.travelDirection !== undefined) {
            if (!['forward', 'reverse'].includes(source.travelDirection)) {
                throw new TypeError('travelDirection must be forward or reverse');
            }
            result.travelDirection = source.travelDirection;
        }
        return result;
    }

    function manualNavigationValidationRequest(value) {
        const source = object(value, 'manual navigation validation request');
        const allowed = new Set([
            'actorPlacementId',
            'actorClass',
            'actorProfileRef',
            'constraintMode',
            'direction',
            'points',
            'prototypeMode',
        ]);
        Object.keys(source).forEach(function (key) {
            if (!allowed.has(key)) {
                throw new TypeError(
                    'manual navigation validation field ' + key
                        + ' is not supported'
                );
            }
        });
        if (!['pedestrian', 'vehicle'].includes(source.actorClass)) {
            throw new TypeError('actorClass must be pedestrian or vehicle');
        }
        if (source.prototypeMode !== undefined
                && typeof source.prototypeMode !== 'boolean') {
            throw new TypeError('prototypeMode must be a boolean');
        }
        if (![
            'guide', 'locked_segment', 'complete_override',
            'avoid_region', 'preferred_corridor',
        ].includes(source.constraintMode)) {
            throw new TypeError('constraintMode is invalid');
        }
        if (!['forward', 'reverse', 'bidirectional'].includes(
            source.direction
        )) {
            throw new TypeError('direction is invalid');
        }
        if (!Array.isArray(source.points)
                || source.points.length < 2
                || source.points.length > 2048) {
            throw new TypeError(
                'manual navigation points must contain 2 to 2048 points'
            );
        }
        const points = source.points.map(function (value, index) {
            const point = object(value, 'points[' + index + ']');
            if (Object.keys(point).some(function (key) {
                return !['x', 'z'].includes(key);
            })) {
                throw new TypeError('manual navigation points support x and z');
            }
            const x = Number(point.x);
            const z = Number(point.z);
            if (!Number.isFinite(x) || !Number.isFinite(z)) {
                throw new TypeError('manual navigation points must be finite');
            }
            return { x: x, z: z };
        });
        const result = {
            actorPlacementId: boundedIdentifier(
                source.actorPlacementId,
                'actorPlacementId'
            ),
            actorClass: source.actorClass,
            constraintMode: source.constraintMode,
            direction: source.direction,
            points: points,
        };
        if (source.prototypeMode !== undefined) {
            result.prototypeMode = source.prototypeMode;
        }
        if (source.actorProfileRef !== undefined) {
            const profile = object(source.actorProfileRef, 'actorProfileRef');
            const profileKind = nonEmptyString(
                profile.profileKind,
                'actorProfileRef.profileKind'
            );
            if (profileKind !== source.actorClass) {
                throw new TypeError('actor profile kind must match actorClass');
            }
            result.actorProfileRef = {
                profileKind: profileKind,
                profileId: boundedIdentifier(
                    profile.profileId,
                    'actorProfileRef.profileId'
                ),
                profileRevision: hash(
                    profile.profileRevision,
                    'actorProfileRef.profileRevision'
                ),
            };
        }
        if (source.actorClass === 'vehicle' && !result.actorProfileRef) {
            throw new TypeError(
                'vehicle validation requires an exact actorProfileRef'
            );
        }
        return result;
    }

    function navigationSnapshotRequest(value) {
        const source = object(value, 'navigation snapshot request');
        const allowed = new Set([
            'movementProgramId',
            'actorPlacementId',
            'actorClass',
            'actorProfileRef',
            'prototypeMode',
        ]);
        Object.keys(source).forEach(function (key) {
            if (!allowed.has(key)) {
                throw new TypeError(
                    'navigation snapshot field ' + key + ' is not supported'
                );
            }
        });
        const result = {};
        if (source.movementProgramId !== undefined) {
            result.movementProgramId = boundedIdentifier(
                source.movementProgramId,
                'movementProgramId'
            );
        }
        if (source.actorPlacementId !== undefined) {
            result.actorPlacementId = boundedIdentifier(
                source.actorPlacementId,
                'actorPlacementId'
            );
        }
        if (source.actorClass !== undefined) {
            if (!['pedestrian', 'vehicle'].includes(source.actorClass)) {
                throw new TypeError('actorClass must be pedestrian or vehicle');
            }
            result.actorClass = source.actorClass;
        }
        if (source.prototypeMode !== undefined) {
            if (typeof source.prototypeMode !== 'boolean') {
                throw new TypeError('prototypeMode must be a boolean');
            }
            result.prototypeMode = source.prototypeMode;
        }
        if (source.actorProfileRef !== undefined) {
            const profile = object(source.actorProfileRef, 'actorProfileRef');
            result.actorProfileRef = {
                profileKind: nonEmptyString(
                    profile.profileKind,
                    'actorProfileRef.profileKind'
                ),
                profileId: boundedIdentifier(
                    profile.profileId,
                    'actorProfileRef.profileId'
                ),
                profileRevision: hash(
                    profile.profileRevision,
                    'actorProfileRef.profileRevision'
                ),
            };
        }
        if (!result.movementProgramId
                && (!result.actorPlacementId || !result.actorClass
                    || !result.actorProfileRef)) {
            throw new TypeError(
                'navigation snapshot requires a movementProgramId or an exact actor binding'
            );
        }
        return result;
    }

    function actorJourneyRequest(value) {
        const source = object(value, 'actor journey request');
        const allowed = new Set([
            'navigationPackageId',
            'movementProgramId',
            'load',
            'allowReverse',
            'prototypeMode',
        ]);
        Object.keys(source).forEach(function (key) {
            if (!allowed.has(key)) {
                throw new TypeError(
                    'actor journey field ' + key + ' is not supported'
                );
            }
        });
        const result = {
            navigationPackageId: boundedIdentifier(
                source.navigationPackageId,
                'navigationPackageId',
                80
            ),
            movementProgramId: boundedIdentifier(
                source.movementProgramId,
                'movementProgramId'
            ),
        };
        if (source.load !== undefined) {
            result.load = clone(object(source.load, 'load'));
        }
        ['allowReverse', 'prototypeMode'].forEach(function (field) {
            if (source[field] !== undefined) {
                if (typeof source[field] !== 'boolean') {
                    throw new TypeError(field + ' must be a boolean');
                }
                result[field] = source[field];
            }
        });
        return result;
    }

    function navigationHandoffRequest(value) {
        const source = object(value, 'navigation handoff request');
        const allowed = new Set([
            'handoffProgramId',
            'journeySolutionIds',
        ]);
        Object.keys(source).forEach(function (key) {
            if (!allowed.has(key)) {
                throw new TypeError(
                    'navigation handoff field ' + key + ' is not supported'
                );
            }
        });
        if (!Array.isArray(source.journeySolutionIds)
                || source.journeySolutionIds.length !== 2) {
            throw new TypeError(
                'journeySolutionIds must contain exactly two identities'
            );
        }
        const journeySolutionIds = source.journeySolutionIds.map(
            function (identity) {
                return boundedIdentifier(identity, 'journeySolutionId', 80);
            }
        );
        if (new Set(journeySolutionIds).size !== 2) {
            throw new TypeError('journeySolutionIds must be distinct');
        }
        return {
            handoffProgramId: boundedIdentifier(
                source.handoffProgramId,
                'handoffProgramId'
            ),
            journeySolutionIds: journeySolutionIds,
        };
    }

    function navigationActivityRequest(value) {
        const source = object(value, 'navigation activity request');
        const allowed = new Set([
            'journeySolutionIds',
            'handoffResultIds',
            'scenarioLabel',
            'prototypeMode',
        ]);
        Object.keys(source).forEach(function (key) {
            if (!allowed.has(key)) {
                throw new TypeError(
                    'navigation activity field ' + key + ' is not supported'
                );
            }
        });
        if (!Array.isArray(source.journeySolutionIds)
                || !source.journeySolutionIds.length
                || source.journeySolutionIds.length > NAVIGATION_ACTIVITY_MAXIMUM_ACTORS) {
            throw new TypeError(
                'journeySolutionIds must contain between 1 and ' + NAVIGATION_ACTIVITY_MAXIMUM_ACTORS + ' identities'
            );
        }
        const journeySolutionIds = source.journeySolutionIds.map(
            identity => boundedIdentifier(identity, 'journeySolutionId', 80)
        );
        if (new Set(journeySolutionIds).size !== journeySolutionIds.length) {
            throw new TypeError('journeySolutionIds must be unique');
        }
        if (source.prototypeMode !== true) {
            throw new TypeError('prototypeMode must be true');
        }
        const result = {
            journeySolutionIds: journeySolutionIds,
            handoffResultIds: Array.isArray(source.handoffResultIds)
                ? source.handoffResultIds.map(
                    identity => boundedIdentifier(
                        identity,
                        'handoffResultId',
                        80
                    )
                ) : [],
            prototypeMode: true,
        };
        if (new Set(result.handoffResultIds).size
                !== result.handoffResultIds.length) {
            throw new TypeError('handoffResultIds must be unique');
        }
        if (source.scenarioLabel !== undefined) {
            result.scenarioLabel = nonEmptyString(
                source.scenarioLabel,
                'scenarioLabel'
            );
        }
        return result;
    }

    function activityScenarioRequest(value) {
        const source = object(value, 'activity scenario request');
        const allowed = new Set([
            'preset',
            'prototypeMode',
            'scenarioLabel',
            'maximumActors',
        ]);
        Object.keys(source).forEach(function (key) {
            if (!allowed.has(key)) {
                throw new TypeError(
                    'activity scenario request field ' + key
                        + ' is not supported'
                );
            }
        });
        if (![
            'mobile_actors_on_authored_routes',
            'reference_complete_navigation',
            'reference_candidate_navigation',
            'reference_downstream_navigation',
            'reference_finished_goods_putaway',
            'reference_finished_goods_dispatch',
            'reference_receiving_putaway',
        ].includes(source.preset)) {
            throw new TypeError('activity scenario preset is unsupported');
        }
        if (source.prototypeMode !== true) {
            throw new TypeError('activity scenario requires prototypeMode true');
        }
        const result = {
            preset: source.preset,
            prototypeMode: true,
        };
        if (source.scenarioLabel !== undefined) {
            result.scenarioLabel = nonEmptyString(
                source.scenarioLabel,
                'scenarioLabel'
            );
        }
        if (source.maximumActors !== undefined) {
            if (!Number.isInteger(source.maximumActors)
                    || source.maximumActors < 1
                    || source.maximumActors > 24) {
                throw new TypeError('maximumActors must be an integer from 1 to 24');
            }
            result.maximumActors = source.maximumActors;
        }
        return result;
    }

    const FLOOR_PLAN_MAX_BYTES = 25 * 1024 * 1024;

    function errorFromResponse(response, body) {
        const envelope = body && typeof body === 'object'
            ? (
                body.error
                || (body.detail && body.detail.error)
                || body.detail
                || body
            )
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
        const designUrl = baseUrl + '/api/facility-layout-design/'
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

        async function siteRequest(action, requestOptions, milliseconds) {
            const controller = new AbortController();
            const external = requestOptions && requestOptions.signal;
            const cancel = function () { controller.abort(); };
            if (external) {
                if (external.aborted) cancel();
                else external.addEventListener('abort', cancel, { once: true });
            }
            let expired = false;
            const timer = setTimeout(function () { expired = true; controller.abort(); }, milliseconds);
            try {
                return await action(Object.assign({}, requestOptions, { signal: controller.signal }));
            } catch (error) {
                if (expired) throw new Error('The site service took too long. Your site is unchanged. Please try again.');
                throw error;
            } finally {
                clearTimeout(timer);
                if (external) external.removeEventListener('abort', cancel);
            }
        }

        async function importDecalImage(file, requestOptions) {
            if (!file || !['image/png', 'image/jpeg'].includes(file.type) || file.size > 10 * 1024 * 1024) {
                throw new TypeError('Choose a PNG or JPEG image smaller than 10 MB.');
            }
            const response = await fetchImpl(layoutUrl + '/decal-images', {
                method: 'POST', credentials: options.credentials || 'same-origin',
                headers: Object.assign({}, headers, {'Content-Type': file.type, 'X-InspectorPro-Session': sessionId}),
                body: file, signal: requestOptions && requestOptions.signal,
            });
            const result = await response.json().catch(function () { return {}; });
            if (!response.ok) throw errorFromResponse(response, result);
            return result;
        }

        // Floor-plan import (docs/facility-floor-plan-import-plan.md): the DXF goes up as it is, its display name
        // percent-encoded in a header. A drawing the site already has comes back without being read again.
        async function importFloorPlan(file, requestOptions) {
            if (!file || typeof file.size !== 'number') throw new TypeError('Choose a DXF file.');
            if (file.size > FLOOR_PLAN_MAX_BYTES) {
                throw new TypeError('The drawing is larger than 25 MB, more than the import supports.');
            }
            const response = await fetchImpl(layoutUrl + '/floor-plan-imports', {
                method: 'POST', cache: 'no-store', credentials: options.credentials || 'same-origin',
                headers: Object.assign({}, headers, {
                    'Content-Type': 'application/dxf',
                    'X-InspectorPro-Session': sessionId,
                    'X-Floor-Plan-Name': encodeURIComponent(String(file.name || 'drawing.dxf').slice(0, 240)),
                }),
                body: file, signal: requestOptions && requestOptions.signal,
            });
            const result = await response.json().catch(function () { return {}; });
            if (!response.ok) throw errorFromResponse(response, result);
            return result;
        }

        function floorPlanPath(importId, suffix) {
            const id = String(importId || '');
            if (!/^fpi-[a-f0-9]{32}$/.test(id)) throw new TypeError('A floor-plan import id is required.');
            return '/floor-plan-imports/' + id + (suffix || '');
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

        async function designRequest(path, method, body, requestOptions, urlOverride) {
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
                (urlOverride || designUrl) + (path || ''), init
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
            designUrl: designUrl,
            sessionId: sessionId,
            listLayouts: function () {
                return designRequest('', 'GET', undefined, {},
                    baseUrl + '/api/facility-layouts/' + encodedSite);
            },
            getLayout: function (id) {
                return designRequest('', 'GET', undefined, {},
                    baseUrl + '/api/facility-layouts/' + encodedSite + '/'
                        + encodeURIComponent(boundedIdentifier(id, 'layoutId', 132)));
            },
            createLayout: function (layout) {
                return designRequest('', 'POST', { layout: object(layout, 'layout'), makeDefault: false }, {},
                    baseUrl + '/api/facility-layouts/' + encodedSite);
            },
            archiveLayout: function (id, revision) {
                return designRequest('/archive', 'POST', { baseRevision: hash(revision, 'baseRevision') }, {},
                    baseUrl + '/api/facility-layouts/' + encodedSite + '/'
                        + encodeURIComponent(boundedIdentifier(id, 'layoutId', 132)));
            },
            listGenerationPlanningSources: function () {
                return designRequest('/sources', 'GET', undefined, {},
                    baseUrl + '/api/facility-layout-planning/' + encodedSite + '/' + encodedLayout);
            },
            inspectGenerationPlanningPreview: function (summary, editorContext) {
                return designRequest('/inspect', 'POST', {
                    workspaceId: boundedIdentifier(summary.workspaceId, 'workspaceId'),
                    request: {previewId: hash(summary.previewId, 'previewId'), previewRevision: hash(summary.previewRevision, 'previewRevision')},
                    editorContext: editorContext,
                }, {}, baseUrl + '/api/facility-layout-planning/' + encodedSite + '/' + encodedLayout);
            },
            selectGenerationPlanningPreview: function (summary, editorContext) {
                return designRequest('/select', 'POST', {
                    workspaceId: boundedIdentifier(summary.workspaceId, 'workspaceId'),
                    request: {previewId: hash(summary.previewId, 'previewId'), previewRevision: hash(summary.previewRevision, 'previewRevision')},
                    editorContext: editorContext,
                }, {}, baseUrl + '/api/facility-layout-planning/' + encodedSite + '/' + encodedLayout);
            },
            createGenerationDestination: function (request, editorContext) {
                return designRequest('/destination', 'POST', {
                    workspaceId: boundedIdentifier('destination-' + sessionId, 'workspaceId'),
                    request: request, editorContext: editorContext,
                }, {}, baseUrl + '/api/facility-layout-planning/' + encodedSite + '/' + encodedLayout);
            },
            getConstructionPreview: function (proposalId) {
                const url = baseUrl + '/api/facility-layout-agent/' + encodedSite + '/' + encodedLayout + '/construction/';
                return designRequest(boundedIdentifier(proposalId, 'proposalId'), 'GET', undefined, {}, url);
            },
            approveConstructionPreview: function (proposalId, binding) {
                const url = baseUrl + '/api/facility-layout-agent/' + encodedSite + '/' + encodedLayout + '/construction/';
                return designRequest(boundedIdentifier(proposalId, 'proposalId') + '/approve-unsaved', 'POST', {
                    requestId: boundedIdentifier(binding.requestId, 'requestId'), sessionId: sessionId,
                    editorGenerationId: boundedIdentifier(binding.editorGenerationId, 'editorGenerationId'),
                    expectedDraftRevision: hash(binding.expectedDraftRevision, 'expectedDraftRevision'),
                    candidateRevision: hash(binding.candidateRevision, 'candidateRevision'),
                }, {}, url);
            },
            createDesignBrief: function (payload, requestOptions) {
                const value = object(payload, 'design brief payload');
                return designRequest('/briefs', 'POST', {
                    briefId: value.briefId === undefined
                        ? undefined
                        : boundedIdentifier(value.briefId, 'briefId'),
                    workspaceId: boundedIdentifier(
                        value.workspaceId || 'workspace-facility-layout',
                        'workspaceId'
                    ),
                    editorFrame: clone(object(value.editorFrame, 'editorFrame')),
                    semanticIntent: clone(object(
                        value.semanticIntent,
                        'semanticIntent'
                    )),
                    sourceTurnRef: boundedIdentifier(
                        value.sourceTurnRef,
                        'sourceTurnRef',
                        160
                    ),
                }, requestOptions);
            },
            inspectDesignBrief: function (payload, requestOptions) {
                const value = object(payload, 'design brief inspection payload');
                const briefId = boundedIdentifier(value.briefId, 'briefId');
                const query = value.briefRevision
                    ? '?briefRevision=' + encodeURIComponent(hash(
                        value.briefRevision,
                        'briefRevision'
                    ))
                    : '';
                return designRequest(
                    '/briefs/' + encodeURIComponent(briefId) + query,
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            updateDesignBrief: function (payload, requestOptions) {
                const value = object(payload, 'design brief update payload');
                const briefId = boundedIdentifier(value.briefId, 'briefId');
                return designRequest(
                    '/briefs/' + encodeURIComponent(briefId) + '/revisions',
                    'POST',
                    {
                        semanticIntent: clone(object(
                            value.semanticIntent,
                            'semanticIntent'
                        )),
                        sourceTurnRef: boundedIdentifier(
                            value.sourceTurnRef,
                            'sourceTurnRef',
                            160
                        ),
                    },
                    requestOptions
                );
            },
            startDesignPreview: function (payload, requestOptions) {
                const value = object(payload, 'design preview payload');
                const briefId = boundedIdentifier(value.briefId, 'briefId');
                const body = {
                    briefRevision: hash(value.briefRevision, 'briefRevision'),
                    workspaceId: boundedIdentifier(
                        value.workspaceId || 'workspace-facility-layout',
                        'workspaceId'
                    ),
                    clientGenerationId: boundedIdentifier(
                        value.clientGenerationId,
                        'clientGenerationId',
                        160
                    ),
                    mode: value.mode === 'lab' ? 'lab' : 'production_sage',
                };
                if (value.runId) {
                    body.runId = boundedIdentifier(value.runId, 'runId');
                }
                return designRequest(
                    '/briefs/' + encodeURIComponent(briefId) + '/preview',
                    'POST',
                    body,
                    requestOptions
                );
            },
            continueDesignPreview: function (payload, requestOptions) {
                const value = object(payload, 'design preview continuation payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return designRequest(
                    '/runs/' + encodeURIComponent(runId) + '/continue',
                    'POST',
                    { maximumToolCalls: value.maximumToolCalls || 10 },
                    requestOptions
                );
            },
            cancelDesignPreview: function (payload, requestOptions) {
                const value = object(payload, 'design preview cancellation payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return designRequest(
                    '/runs/' + encodeURIComponent(runId) + '/cancel',
                    'POST',
                    {},
                    requestOptions
                );
            },
            inspectDesignProposal: function (payload, requestOptions) {
                const value = object(payload, 'design proposal inspection payload');
                const proposalId = boundedIdentifier(
                    value.proposalId,
                    'proposalId'
                );
                const query = '?proposalRevision=' + encodeURIComponent(hash(
                    value.proposalRevision,
                    'proposalRevision'
                )) + '&includeCandidateLayout=' + (
                    value.includeCandidateLayout === true ? 'true' : 'false'
                );
                return designRequest(
                    '/proposals/' + encodeURIComponent(proposalId) + query,
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            prepareDesignProposalApply: function (payload, requestOptions) {
                const value = object(payload, 'design proposal apply payload');
                const proposalId = boundedIdentifier(
                    value.proposalId,
                    'proposalId'
                );
                const body = {
                    proposalRevision: hash(
                        value.proposalRevision,
                        'proposalRevision'
                    ),
                    rootUndoFrame: clone(object(
                        value.rootUndoFrame,
                        'rootUndoFrame'
                    )),
                    previousInstallationState: clone(object(
                        value.previousInstallationState,
                        'previousInstallationState'
                    )),
                    expectedResultEditorGenerationId: boundedIdentifier(
                        value.expectedResultEditorGenerationId,
                        'expectedResultEditorGenerationId',
                        160
                    ),
                    expectedResultCommandJournalHash: hash(
                        value.expectedResultCommandJournalHash,
                        'expectedResultCommandJournalHash'
                    ),
                };
                if (value.expectedSourceOwner) {
                    body.expectedSourceOwner = clone(object(
                        value.expectedSourceOwner,
                        'expectedSourceOwner'
                    ));
                }
                if (value.transactionId) {
                    body.transactionId = boundedIdentifier(
                        value.transactionId,
                        'transactionId'
                    );
                    body.expectedTransactionRevision = hash(
                        value.expectedTransactionRevision,
                        'expectedTransactionRevision'
                    );
                }
                return designRequest(
                    '/proposals/' + encodeURIComponent(proposalId)
                        + '/apply/prepare',
                    'POST',
                    body,
                    requestOptions
                );
            },
            commitDesignProposalApply: function (payload, requestOptions) {
                const value = object(payload, 'design apply commit payload');
                const transactionId = boundedIdentifier(
                    value.transactionId,
                    'transactionId'
                );
                return designRequest(
                    '/transactions/' + encodeURIComponent(transactionId)
                        + '/apply/commit',
                    'POST',
                    {
                        expectedTransactionRevision: hash(
                            value.expectedTransactionRevision,
                            'expectedTransactionRevision'
                        ),
                        adoptionToken: opaqueToken(
                            value.adoptionToken,
                            'adoptionToken'
                        ),
                    },
                    requestOptions
                );
            },
            acknowledgeDesignProposalApply: function (payload, requestOptions) {
                const value = object(payload, 'design apply acknowledgement');
                const transactionId = boundedIdentifier(
                    value.transactionId,
                    'transactionId'
                );
                return designRequest(
                    '/transactions/' + encodeURIComponent(transactionId)
                        + '/apply/acknowledge',
                    'POST',
                    {
                        expectedTransactionRevision: hash(
                            value.expectedTransactionRevision,
                            'expectedTransactionRevision'
                        ),
                        adoptionToken: opaqueToken(
                            value.adoptionToken,
                            'adoptionToken'
                        ),
                        observedInstallationFingerprint: hash(
                            value.observedInstallationFingerprint,
                            'observedInstallationFingerprint'
                        ),
                    },
                    requestOptions
                );
            },
            recoverDesignProposalApply: function (payload, requestOptions) {
                const value = object(payload, 'design apply recovery payload');
                const transactionId = boundedIdentifier(
                    value.transactionId,
                    'transactionId'
                );
                return designRequest(
                    '/transactions/' + encodeURIComponent(transactionId)
                        + '/apply/recover',
                    'POST',
                    {
                        expectedTransactionRevision: hash(
                            value.expectedTransactionRevision,
                            'expectedTransactionRevision'
                        ),
                        observedInstallationFingerprint: hash(
                            value.observedInstallationFingerprint,
                            'observedInstallationFingerprint'
                        ),
                    },
                    requestOptions
                );
            },
            saveDesignProposalDraft: function (payload, requestOptions) {
                const value = object(payload, 'design proposal save payload');
                const transactionId = boundedIdentifier(
                    value.transactionId,
                    'transactionId'
                );
                return designRequest(
                    '/transactions/' + encodeURIComponent(transactionId)
                        + '/save',
                    'POST',
                    {
                        expectedTransactionRevision: hash(
                            value.expectedTransactionRevision,
                            'expectedTransactionRevision'
                        ),
                        observedDraftRevision: hash(
                            value.observedDraftRevision,
                            'observedDraftRevision'
                        ),
                        observedCommandJournalHash: hash(
                            value.observedCommandJournalHash,
                            'observedCommandJournalHash'
                        ),
                        explicitApproval: value.explicitApproval === true,
                    },
                    requestOptions
                );
            },
            inspectDesignUndo: function (payload, requestOptions) {
                const value = object(payload, 'design undo inspection payload');
                const transactionId = boundedIdentifier(
                    value.transactionId,
                    'transactionId'
                );
                return designRequest(
                    '/transactions/' + encodeURIComponent(transactionId)
                        + '/undo',
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            prepareDesignUndo: function (payload, requestOptions) {
                const value = object(payload, 'design undo prepare payload');
                const transactionId = boundedIdentifier(
                    value.transactionId,
                    'transactionId'
                );
                return designRequest(
                    '/transactions/' + encodeURIComponent(transactionId)
                        + '/undo/prepare',
                    'POST',
                    {
                        expectedTransactionRevision: hash(
                            value.expectedTransactionRevision,
                            'expectedTransactionRevision'
                        ),
                    },
                    requestOptions
                );
            },
            acknowledgeDesignUndo: function (payload, requestOptions) {
                const value = object(payload, 'design undo acknowledgement');
                const transactionId = boundedIdentifier(
                    value.transactionId,
                    'transactionId'
                );
                return designRequest(
                    '/transactions/' + encodeURIComponent(transactionId)
                        + '/undo/acknowledge',
                    'POST',
                    {
                        expectedTransactionRevision: hash(
                            value.expectedTransactionRevision,
                            'expectedTransactionRevision'
                        ),
                        observedDraftRevision: hash(
                            value.observedDraftRevision,
                            'observedDraftRevision'
                        ),
                        observedCommandJournalHash: hash(
                            value.observedCommandJournalHash,
                            'observedCommandJournalHash'
                        ),
                    },
                    requestOptions
                );
            },
            startG1Generation: function (payload, requestOptions) {
                const value = object(payload, 'G1 generation payload');
                return generationRequest('/g1', 'POST', value, requestOptions);
            },
            startFullFactoryGeneration: function (payload, requestOptions) {
                const value = object(payload, 'full-factory generation payload');
                return generationRequest(
                    '/full-factory',
                    'POST',
                    value,
                    requestOptions
                );
            },
            startFacilityPlanningGeneration: function (payload, requestOptions) {
                const value = object(
                    payload,
                    'Facility Planning generation payload'
                );
                return generationRequest(
                    '/planning-package',
                    'POST',
                    value,
                    requestOptions
                );
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
            amendGenerationCirculation: function (payload, requestOptions) {
                const value = object(payload, 'generation circulation payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/circulation',
                    'POST',
                    {
                        expectedDraftRevision: nonEmptyString(
                            value.expectedDraftRevision,
                            'expectedDraftRevision'
                        ),
                        prototypeMode: value.prototypeMode === true,
                        circulation: object(
                            value.circulation,
                            'circulation'
                        ),
                    },
                    requestOptions
                );
            },
            amendGenerationSubdivisions: function (payload, requestOptions) {
                const value = object(payload, 'generation subdivision payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/subdivisions',
                    'POST',
                    {
                        expectedDraftRevision: nonEmptyString(
                            value.expectedDraftRevision,
                            'expectedDraftRevision'
                        ),
                        prototypeMode: value.prototypeMode === true,
                        subdivision: object(
                            value.subdivision,
                            'subdivision'
                        ),
                    },
                    requestOptions
                );
            },
            amendGenerationAssets: function (payload, requestOptions) {
                const value = object(payload, 'generation asset payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/assets',
                    'POST',
                    {
                        expectedDraftRevision: nonEmptyString(
                            value.expectedDraftRevision,
                            'expectedDraftRevision'
                        ),
                        prototypeMode: value.prototypeMode === true,
                        assetPlacement: object(
                            value.assetPlacement,
                            'assetPlacement'
                        ),
                    },
                    requestOptions
                );
            },
            amendFacilityProgramResourceBatch: function (
                payload,
                requestOptions
            ) {
                const value = object(
                    payload,
                    'FacilityProgram resource amendment payload'
                );
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId)
                        + '/facility-program/resource-batch',
                    'POST',
                    {
                        expectedDraftRevision: nonEmptyString(
                            value.expectedDraftRevision,
                            'expectedDraftRevision'
                        ),
                        prototypeMode: value.prototypeMode === true,
                        resourceBatchId: boundedIdentifier(
                            value.resourceBatchId,
                            'resourceBatchId'
                        ),
                        patch: object(value.patch, 'patch'),
                    },
                    requestOptions
                );
            },
            amendGenerationCells: function (payload, requestOptions) {
                const value = object(payload, 'generation cell payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/cells',
                    'POST',
                    {
                        expectedDraftRevision: nonEmptyString(
                            value.expectedDraftRevision,
                            'expectedDraftRevision'
                        ),
                        prototypeMode: value.prototypeMode === true,
                        cellComposition: object(
                            value.cellComposition,
                            'cellComposition'
                        ),
                    },
                    requestOptions
                );
            },
            amendGenerationCellReplication: function (payload, requestOptions) {
                const value = object(payload, 'generation cell replication payload');
                const runId = boundedIdentifier(value.runId, 'runId');
                return generationRequest(
                    '/runs/' + encodeURIComponent(runId) + '/cell-replication',
                    'POST',
                    {
                        expectedDraftRevision: nonEmptyString(
                            value.expectedDraftRevision,
                            'expectedDraftRevision'
                        ),
                        prototypeMode: value.prototypeMode === true,
                        cellReplication: object(
                            value.cellReplication,
                            'cellReplication'
                        ),
                    },
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
            importDecalImage: importDecalImage,
            importFloorPlan: importFloorPlan,
            floorPlanGeometry: function (importId, requestOptions) {
                return request(floorPlanPath(importId, '/geometry'), 'GET', undefined, requestOptions);
            },
            alignFloorPlan: function (importId, body, requestOptions) {
                return request(floorPlanPath(importId, '/alignment'), 'POST', object(body, 'alignment request'),
                    requestOptions);
            },
            // Site context: the server fetches public USGS imagery and stores it per site.
            fetchSiteParcel: function (payload, requestOptions) {
                const value = object(payload, 'site parcel request');
                return siteRequest(function (config) { return request('/site-parcel', 'POST', {
                    latitude: Number(value.latitude), longitude: Number(value.longitude),
                    originLatitude: Number(value.originLatitude), originLongitude: Number(value.originLongitude),
                }, config); }, requestOptions, 45000);
            },
            traceSitePhoto: function (payload, requestOptions) {
                const value = object(payload, 'site trace request');
                const body = { layout: object(value.layout, 'layout') };
                if (value.box) {
                    const box = object(value.box, 'box');
                    body.box = { minX: Number(box.minX), maxX: Number(box.maxX), minZ: Number(box.minZ), maxZ: Number(box.maxZ) };
                } else {
                    body.x = Number(value.x);
                    body.z = Number(value.z);
                }
                return siteRequest(function (config) { return request('/site-trace', 'POST', body, config); },
                    requestOptions, 60000);
            },
            fetchSiteRoads: function (payload, requestOptions) {
                const value = object(payload, 'site roads request');
                return siteRequest(function (config) { return request('/site-roads', 'POST', {
                    geoBounds: object(value.geoBounds, 'geoBounds'),
                }, config); }, requestOptions, 60000);
            },
            fetchSiteOverlay: function (payload, requestOptions) {
                const value = object(payload, 'site layer request');
                return siteRequest(function (config) { return request('/site-overlay', 'POST', {
                    layer: String(value.layer), geoBounds: object(value.geoBounds, 'geoBounds'),
                    widthPixels: Number(value.widthPixels), heightPixels: Number(value.heightPixels),
                }, config); }, requestOptions, 120000);
            },
            checkSiteLayers: function (payload, requestOptions) {
                return siteRequest(function (config) {
                    return request('/site-layer-checks', 'POST', { layout: object(payload.layout, 'layout') }, config);
                }, requestOptions, 180000);
            },
            analyzeSiteContext: function (payload, requestOptions) {
                return siteRequest(function (config) {
                    return request('/site-analysis', 'POST', { layout: object(payload.layout, 'layout') }, config);
                }, requestOptions, 30000);
            },
            fetchSiteImagery: function (payload, requestOptions) {
                const value = object(payload, 'site imagery request');
                const body = {
                    latitude: Number(value.latitude),
                    longitude: Number(value.longitude),
                    halfSizeMeters: Number(value.halfSizeMeters),
                };
                if (value.source) body.source = String(value.source);
                return siteRequest(function (config) { return request('/site-imagery', 'POST', body, config); },
                    requestOptions, 180000);
            },
            geocodeAddress: async function (address, requestOptions) {
                return siteRequest(async function (config) {
                const response = await fetchImpl(baseUrl + '/api/facility-site-geocode/' + encodedSite, {
                    method: 'POST', cache: 'no-store', credentials: options.credentials || 'same-origin',
                    headers: Object.assign({}, headers, {
                        'Content-Type': 'application/json', 'X-InspectorPro-Session': sessionId,
                    }),
                    body: JSON.stringify({ address: String(address || '') }),
                    signal: config.signal,
                });
                const result = await response.json().catch(function () { return {}; });
                if (!response.ok) throw errorFromResponse(response, result);
                return result;
                }, requestOptions, 45000);
            },
            // The globe flight: the server starts fetching the tiles the dive will draw.
            prefetchSiteGlobe: async function (payload, requestOptions) {
                const value = object(payload, 'globe prefetch request');
                return siteRequest(async function (config) {
                const response = await fetchImpl(baseUrl + '/api/facility-site-globe/' + encodedSite + '/prefetch', {
                    method: 'POST', cache: 'no-store', credentials: options.credentials || 'same-origin',
                    headers: Object.assign({}, headers, {
                        'Content-Type': 'application/json', 'X-InspectorPro-Session': sessionId,
                    }),
                    body: JSON.stringify({ latitude: Number(value.latitude), longitude: Number(value.longitude) }),
                    signal: config.signal,
                });
                const result = await response.json().catch(function () { return {}; });
                if (!response.ok) throw errorFromResponse(response, result);
                return result;
                }, requestOptions, 15000);
            },
            createMotionPackage: function (payload, requestOptions) {
                const value = object(payload, 'motion package payload');
                return request('/motion-packages', 'POST', {
                    baseRevision: hash(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    request: motionPackageRequest(value.request),
                }, requestOptions);
            },
            getMotionPackage: function (payload, requestOptions) {
                const value = object(payload, 'motion package fetch payload');
                const packageId = boundedIdentifier(
                    value.packageId,
                    'packageId',
                    80
                );
                const activeRevision = hash(
                    value.activeRevision,
                    'activeRevision'
                );
                return request(
                    '/motion-packages/' + encodeURIComponent(packageId)
                        + '?activeRevision=' + encodeURIComponent(activeRevision),
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            validateManualNavigationPath: function (payload, requestOptions) {
                const value = object(
                    payload,
                    'manual navigation validation payload'
                );
                return request('/navigation/manual-path/validate', 'POST', {
                    baseRevision: hash(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    request: manualNavigationValidationRequest(value.request),
                }, requestOptions);
            },
            compileNavigationSnapshot: function (payload, requestOptions) {
                const value = object(payload, 'navigation snapshot payload');
                return request('/navigation/snapshots/compile', 'POST', {
                    baseRevision: hash(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    request: navigationSnapshotRequest(value.request),
                }, requestOptions);
            },
            getNavigationPackage: function (payload, requestOptions) {
                const value = object(payload, 'navigation package fetch payload');
                const packageId = boundedIdentifier(
                    value.packageId,
                    'packageId',
                    80
                );
                return request(
                    '/navigation/packages/' + encodeURIComponent(packageId),
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            planActorJourney: function (payload, requestOptions) {
                const value = object(payload, 'actor journey payload');
                return request('/navigation/journeys/plan', 'POST', {
                    baseRevision: hash(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    request: actorJourneyRequest(value.request),
                }, requestOptions);
            },
            getActorJourney: function (payload, requestOptions) {
                const value = object(payload, 'actor journey fetch payload');
                const journeySolutionId = boundedIdentifier(
                    value.journeySolutionId,
                    'journeySolutionId',
                    80
                );
                return request(
                    '/navigation/journeys/'
                        + encodeURIComponent(journeySolutionId),
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            compileNavigationHandoff: function (payload, requestOptions) {
                const value = object(payload, 'navigation handoff payload');
                return request('/navigation/handoffs/compile', 'POST', {
                    baseRevision: hash(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    request: navigationHandoffRequest(value.request),
                }, requestOptions);
            },
            getNavigationHandoff: function (payload, requestOptions) {
                const value = object(payload, 'navigation handoff fetch payload');
                const resultId = boundedIdentifier(
                    value.handoffResultId,
                    'handoffResultId',
                    80
                );
                return request(
                    '/navigation/handoffs/' + encodeURIComponent(resultId),
                    'GET',
                    undefined,
                    requestOptions
                );
            },
            buildNavigationActivityScenario: function (payload, requestOptions) {
                const value = object(payload, 'navigation activity payload');
                return request('/navigation/activity-scenarios', 'POST', {
                    baseRevision: hash(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    request: navigationActivityRequest(value.request),
                }, requestOptions);
            },
            createActivityScenario: function (payload, requestOptions) {
                const value = object(payload, 'activity scenario payload');
                return request('/activity-scenarios', 'POST', {
                    baseRevision: hash(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    request: activityScenarioRequest(value.request),
                }, requestOptions);
            },
            getActivityScenario: function (payload, requestOptions) {
                const value = object(payload, 'activity scenario fetch payload');
                const scenarioId = boundedIdentifier(
                    value.scenarioId,
                    'scenarioId',
                    80
                );
                const activeRevision = hash(
                    value.activeRevision,
                    'activeRevision'
                );
                return request(
                    '/activity-scenarios/' + encodeURIComponent(scenarioId)
                        + '?activeRevision=' + encodeURIComponent(activeRevision),
                    'GET',
                    undefined,
                    requestOptions
                );
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
            // The lighting coverage estimate of one area (lighting plan CC3): read only.
            lightingCoverage: function (payload, requestOptions) {
                const value = payload || {};
                if (!value.area || typeof value.area !== 'object' || Array.isArray(value.area)) {
                    throw new TypeError('A lighting coverage area is required.');
                }
                return request('/lighting/coverage', 'POST', {
                    baseRevision: nonEmptyString(value.baseRevision, 'baseRevision'),
                    operations: operationBatch(value.operations || []),
                    area: clone(value.area),
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
            createOperationUndoPreview: function (payload, requestOptions) {
                const value = object(payload, 'operation undo preview payload');
                return request('/operation-undo-preview', 'POST', {
                    baseRevision: nonEmptyString(value.baseRevision, 'baseRevision'),
                    receiptId: boundedIdentifier(value.receiptId, 'receiptId'),
                    ...(value.editMode === 'direct' ? { editMode: 'direct' } : {}),
                }, requestOptions);
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
                const direct = value.authorizationMode === 'direct' && value.directConsent === true;
                if (value.explicitApproval !== true && !direct) {
                    throw new TypeError('explicitApproval must equal true');
                }
                return request('/approvals', 'POST', {
                    proposalId: boundedIdentifier(
                        value.proposalId,
                        'proposalId'
                    ),
                    binding: transactionBinding(value.binding),
                    idempotencyKey: idempotencyKey(value.idempotencyKey),
                    explicitApproval: !direct,
                    ...(direct ? { authorizationMode: 'direct', directConsent: true } : {}),
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
        NAVIGATION_ACTIVITY_MAXIMUM_ACTORS: NAVIGATION_ACTIVITY_MAXIMUM_ACTORS,
        createHttpTransport: createHttpTransport,
    });
}));
