(function (root, factory) {
    'use strict';
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilitySpatialAdvisor = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const API_VERSION = 1;
    const DEFAULT_WORKER_URL = '/static/facility_layout_spatial_worker.js';

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function abortError(reason) {
        const error = new Error(reason || 'Spatial advisory request was cancelled.');
        error.name = 'AbortError';
        error.code = 'facility_spatial_advisory_cancelled';
        return error;
    }

    function protocolError(message) {
        const error = new Error(message);
        error.name = 'FacilitySpatialAdvisoryError';
        error.code = 'facility_spatial_advisory_protocol_error';
        return error;
    }

    function createSpatialAdvisor(inputOptions) {
        const options = inputOptions || {};
        const WorkerCtor = options.Worker || (root && root.Worker);
        const worker = typeof options.workerFactory === 'function'
            ? options.workerFactory(options.workerUrl || DEFAULT_WORKER_URL)
            : (
                typeof WorkerCtor === 'function'
                    ? new WorkerCtor(
                        options.workerUrl || DEFAULT_WORKER_URL,
                        { name: 'InspectorPro facility spatial advisory' }
                    )
                    : null
            );
        if (!worker || typeof worker.postMessage !== 'function') {
            throw new TypeError('Web Worker support is required');
        }

        let sequence = 0;
        let active = null;
        let destroyed = false;

        function detachAbort(request) {
            if (request && request.signal && request.abortHandler
                    && typeof request.signal.removeEventListener === 'function') {
                request.signal.removeEventListener('abort', request.abortHandler);
            }
        }

        function rejectActive(error, postCancel) {
            if (!active) return false;
            const request = active;
            active = null;
            detachAbort(request);
            if (postCancel !== false) {
                worker.postMessage({
                    type: 'cancel',
                    requestId: request.requestId,
                });
            }
            request.reject(error);
            return true;
        }

        function handleMessage(event) {
            const message = event && event.data || {};
            if (!active || message.requestId !== active.requestId) return;
            const request = active;
            active = null;
            detachAbort(request);
            if (message.type === 'advisory-error') {
                const error = protocolError(
                    message.error && message.error.message
                    || 'Spatial advisory worker failed.'
                );
                error.code = message.error && message.error.code || error.code;
                request.reject(error);
                return;
            }
            if (message.type !== 'advisory-result'
                    || !message.advisory
                    || message.advisory.authoritative !== false
                    || message.advisory.authority !== 'browser-advisory') {
                request.reject(protocolError(
                    'Spatial worker returned an invalid advisory envelope.'
                ));
                return;
            }
            request.resolve(clone(message.advisory));
        }

        function handleError(event) {
            if (!active) return;
            const error = new Error(
                event && event.message || 'Spatial advisory worker failed.'
            );
            error.name = 'FacilitySpatialAdvisoryError';
            error.code = 'facility_spatial_advisory_worker_error';
            rejectActive(error, false);
        }

        if (typeof worker.addEventListener === 'function') {
            worker.addEventListener('message', handleMessage);
            worker.addEventListener('error', handleError);
        } else {
            worker.onmessage = handleMessage;
            worker.onerror = handleError;
        }

        function request(payload, requestOptions) {
            if (destroyed) return Promise.reject(abortError(
                'Spatial advisory is destroyed.'
            ));
            const requestConfig = requestOptions || {};
            const signal = requestConfig.signal;
            if (signal && signal.aborted) {
                return Promise.reject(abortError('Spatial advisory was aborted.'));
            }
            rejectActive(abortError(
                'Spatial advisory was superseded by a newer request.'
            ));
            sequence += 1;
            const requestId = 'facility-spatial-advisory-' + sequence;
            return new Promise(function (resolve, reject) {
                const abortHandler = function () {
                    if (active && active.requestId === requestId) {
                        rejectActive(abortError(
                            'Spatial advisory was aborted.'
                        ));
                    }
                };
                active = {
                    requestId: requestId,
                    resolve: resolve,
                    reject: reject,
                    signal: signal || null,
                    abortHandler: abortHandler,
                };
                if (signal && typeof signal.addEventListener === 'function') {
                    signal.addEventListener('abort', abortHandler, { once: true });
                }
                worker.postMessage({
                    type: 'analyze',
                    requestId: requestId,
                    payload: clone(payload),
                });
            });
        }

        function cancel(reason) {
            return rejectActive(abortError(reason));
        }

        function destroy() {
            if (destroyed) return false;
            destroyed = true;
            rejectActive(abortError('Spatial advisory was destroyed.'));
            if (typeof worker.removeEventListener === 'function') {
                worker.removeEventListener('message', handleMessage);
                worker.removeEventListener('error', handleError);
            } else {
                worker.onmessage = null;
                worker.onerror = null;
            }
            if (typeof worker.terminate === 'function') worker.terminate();
            return true;
        }

        return Object.freeze({
            apiVersion: API_VERSION,
            request: request,
            cancel: cancel,
            destroy: destroy,
            getState: function () {
                return {
                    apiVersion: API_VERSION,
                    destroyed: destroyed,
                    activeRequestId: active && active.requestId || null,
                    requestCount: sequence,
                };
            },
        });
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        DEFAULT_WORKER_URL: DEFAULT_WORKER_URL,
        createSpatialAdvisor: createSpatialAdvisor,
    });
}));
