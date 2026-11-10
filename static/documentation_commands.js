/* Read-bound guards for the existing documentation workspace save routes. */
(function (root) {
    'use strict';
    function capture(payload, page, apiBase) {
        if (!payload?.scene) return null;
        return {
            apiBase,
            payload: { revision: payload.revision, scene: {
                assemblyNumber: payload.scene.assemblyNumber,
                sourceRevision: payload.scene.sourceRevision,
                manualPlanRevision: payload.scene.manualPlanRevision,
            } },
            page: page ? { pageId: page.pageId, title: page.title } : null,
            slotBinding: payload.slotBinding ? structuredClone(payload.slotBinding) : null,
        };
    }
    function isCurrent(bound, payload, apiBase) {
        return Boolean(bound && payload?.scene && bound.apiBase === apiBase
            && bound.payload.scene.assemblyNumber === payload.scene.assemblyNumber
            && bound.payload.revision === payload.revision
            && (!bound.slotBinding || bound.slotBinding.revision === payload.slotBinding?.revision));
    }
    function message(error) {
        const text = String(error?.message || 'The edit could not be saved.');
        return /revision|hash|conflict|stale|changed/i.test(text)
            ? 'This document changed after your read. Your draft is still visible. Reopen the document and review the newer text before retrying.'
            : text;
    }
    function slotRequest(bound, path, body) {
        const read = bound?.slotBinding;
        if (!read) return body;
        const keys = path === 'values' ? body.values.map(item => 'slot:' + item.slot) : ['@sheet'];
        if (keys.some(key => key.endsWith('.label'))) keys.push('@sheet');
        const hashes = Object.fromEntries(keys.map(key => [key, read.hashes[key]]));
        return { ...body, editBinding: {
            documentId: read.documentId, expectedRevision: read.revision,
            sourceRevision: read.sourceRevision, manualPlanRevision: read.manualPlanRevision,
            requestId: root.crypto.randomUUID(), hashes, payload: body,
        } };
    }
    root.DocumentationCommands = { capture, isCurrent, message, slotRequest };
})(globalThis);
