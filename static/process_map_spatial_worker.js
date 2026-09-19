'use strict';

importScripts('process_map_spatial.js');

self.addEventListener('message', function (event) {
    const message = event && event.data ? event.data : {};
    const requestId = String(message.requestId || '');
    if (!requestId || message.operation !== 'arrangement') return;
    try {
        const runtime = self.InspectorProProcessMapSpatial;
        if (!runtime || typeof runtime.generateArrangementPlan !== 'function') {
            throw new Error('spatial runtime unavailable');
        }
        const result = runtime.generateArrangementPlan(
            message.processMap || {},
            message.options || {}
        );
        self.postMessage({ requestId: requestId, ok: true, result: result });
    } catch (error) {
        self.postMessage({
            requestId: requestId,
            ok: false,
            error: error && error.message ? error.message : 'arrangement planning failed',
        });
    }
});
