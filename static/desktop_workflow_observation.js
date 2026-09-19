(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProDesktopWorkflowObservation = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const WORKFLOWS = Object.freeze({
        drawing: 'Drawing and inspection', model: '3D Model', assembly: 'Assembly',
        processMap: 'Process Map', documentation: 'Documentation', training: 'Training',
        report: 'Report', sessions: 'Edit sessions', agent: 'Chat and voice', curation: 'Region curation',
    });
    const FLAGS = Object.freeze(['loaded', 'dirty', 'busy', 'pending']);
    const failure = (code, message) => Object.assign(new Error(message || code), { code });
    function capture(sources, rendererGeneration) {
        if (!sources || typeof rendererGeneration !== 'string' || !rendererGeneration
                || Object.keys(sources).length !== Object.keys(WORKFLOWS).length) {
            throw failure('desktop_workflow_coverage_unavailable');
        }
        const workflows = Object.keys(WORKFLOWS).map(workflowId => {
            const value = sources[workflowId];
            if (!value || Object.keys(value).length !== FLAGS.length
                    || FLAGS.some(key => typeof value[key] !== 'boolean')) {
                throw failure('desktop_workflow_coverage_unavailable');
            }
            return { workflowId, ...Object.fromEntries(FLAGS.map(key => [key, value[key]])) };
        });
        return { schemaVersion: 1, rendererGeneration, workflows };
    }
    function assertEmpty(snapshot, rendererGeneration) {
        if (!snapshot || snapshot.schemaVersion !== 1 || snapshot.rendererGeneration !== rendererGeneration
                || !Array.isArray(snapshot.workflows)
                || new Set(snapshot.workflows.map(row => row?.workflowId)).size !== snapshot.workflows.length) {
            throw failure('desktop_workflow_coverage_unavailable');
        }
        const sources = {};
        for (const row of snapshot.workflows) {
            if (!row || !Object.hasOwn(WORKFLOWS, row.workflowId)
                    || Object.keys(row).length !== FLAGS.length + 1) throw failure('desktop_workflow_coverage_unavailable');
            sources[row.workflowId] = Object.fromEntries(FLAGS.map(key => [key, row[key]]));
        }
        const checked = capture(sources, rendererGeneration);
        const blocked = checked.workflows.filter(row => FLAGS.some(key => row[key]));
        if (blocked.length) {
            const error = failure('desktop_workflow_recovery_not_enabled',
                'Close or restart is blocked by ' + blocked.map(row => WORKFLOWS[row.workflowId]).join(', ')
                + '. Desktop recovery for this work is not enabled. Keep this window open; no work was discarded.');
            error.workflows = blocked.map(row => row.workflowId);
            throw error;
        }
        return checked;
    }
    // Empty means no observed work, not recovery coverage for a loaded workflow.
    return Object.freeze({ capture, assertEmpty, WORKFLOWS });
}));
