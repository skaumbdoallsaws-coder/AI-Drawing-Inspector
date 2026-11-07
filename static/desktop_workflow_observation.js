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
        packaging: 'Packaging & Shipping',
    });
    const FLAGS = Object.freeze(['loaded', 'dirty', 'busy', 'pending']);
    const failure = (code, message) => Object.assign(new Error(message || code), { code });
    const empty = () => ({ loaded: false, dirty: false, busy: false, pending: false });
    function checkedFlags(value) {
        const fields = value && typeof value === 'object' ? Object.getOwnPropertyDescriptors(value) : {};
        if (!value || typeof value !== 'object' || Array.isArray(value)
                || Object.keys(value).length !== FLAGS.length
                || FLAGS.some(key => !Object.hasOwn(fields, key) || typeof fields[key].value !== 'boolean')) {
            throw failure('desktop_workflow_coverage_unavailable');
        }
        return Object.fromEntries(FLAGS.map(key => [key, fields[key].value]));
    }
    function mergeFlags(left, right) {
        left = checkedFlags(left); right = checkedFlags(right);
        return Object.fromEntries(FLAGS.map(key => [key, left[key] || right[key]]));
    }
    function observePackaging(host) {
        // Read-only, synchronous observations, never a navigation confirmation,
        // discard action, serialized draft, or grant of recovery/write authority.
        try {
            const document = host?.document;
            if (!document || typeof document.querySelectorAll !== 'function') throw failure('desktop_workflow_coverage_unavailable');
            const frames = document.querySelectorAll('#packagingWorkspaceFrame');
            if (frames.length > 1) throw failure('desktop_workflow_coverage_unavailable');
            const owner = host.InspectorProPackagingHost;
            let observed = empty();
            if (owner !== undefined && owner !== null) {
                if (typeof owner.getDesktopLifecycleObservation !== 'function') throw failure('desktop_workflow_coverage_unavailable');
                observed = checkedFlags(owner.getDesktopLifecycleObservation());
            }
            const frame = frames[0];
            if (frame) {
                if (!owner || frame.tagName !== 'IFRAME' || frame.isConnected !== true) throw failure('desktop_workflow_coverage_unavailable');
                const requested = new URL(frame.src, host.location.href);
                const child = frame.contentWindow, content = frame.contentDocument;
                const adapter = child?.InspectorProPackaging;
                if (requested.origin !== host.location.origin || requested.pathname !== '/packaging'
                        || !content || child.document !== content || content.readyState !== 'complete'
                        || child.location.href !== requested.href
                        || typeof adapter?.getDesktopLifecycleObservation !== 'function') {
                    throw failure('desktop_workflow_coverage_unavailable');
                }
                observed = mergeFlags(observed, checkedFlags(adapter.getDesktopLifecycleObservation()));
                // A mounted, saved editor is still an uncovered workspace.
                observed.loaded = true;
                if (frame.contentWindow !== child || frame.contentDocument !== content || child.document !== content
                        || child.InspectorProPackaging !== adapter || content.readyState !== 'complete'
                        || child.location.href !== requested.href || new URL(frame.src, host.location.href).href !== requested.href
                        || frame.isConnected !== true) throw failure('desktop_workflow_coverage_unavailable');
            }
            const currentFrames = document.querySelectorAll('#packagingWorkspaceFrame');
            if (host.document !== document || host.InspectorProPackagingHost !== owner
                    || currentFrames.length !== frames.length || currentFrames[0] !== frame) {
                throw failure('desktop_workflow_coverage_unavailable');
            }
            // The general application observer considers dirty/busy/pending,
            // not loaded. Do not offer discard for an uncovered saved editor.
            observed.pending = FLAGS.some(key => observed[key]);
            return observed;
        } catch (_) {
            throw failure('desktop_workflow_coverage_unavailable');
        }
    }
    // Recovery coverage, for the native application's close, reload and restart only. Covered means leaving now
    // loses nothing: no host Sage work, and the mounted editor itself proves that its exact current state is its
    // stored recovery draft (or that nothing is unsaved). Any doubt, error or missing hook means not covered.
    function packagingCoverage(host) {
        try {
            const owner = host?.InspectorProPackagingHost;
            const flags = owner ? checkedFlags(owner.getDesktopLifecycleObservation()) : empty();
            if (flags.dirty || flags.busy || flags.pending) return { covered: false, token: '' };
            const frames = host.document.querySelectorAll('#packagingWorkspaceFrame');
            if (frames.length > 1) return { covered: false, token: '' };
            if (!frames.length) return { covered: true, token: 'unmounted' };
            const adapter = frames[0].contentWindow?.InspectorProPackaging;
            const coverage = typeof adapter?.getDepartureCoverage === 'function' ? adapter.getDepartureCoverage() : null;
            if (coverage?.covered !== true || typeof coverage.token !== 'string' || coverage.token.length > 200) return { covered: false, token: '' };
            return { covered: true, token: coverage.token };
        } catch (_) {
            return { covered: false, token: '' };
        }
    }
    function withPackaging(sources, host, { recovery = false } = {}) {
        const observed = observePackaging(host);
        const reported = sources && Object.hasOwn(sources, 'packaging') ? checkedFlags(sources.packaging) : empty();
        let packaging = mergeFlags(reported, observed);
        packaging.pending = FLAGS.some(key => packaging[key]);
        // The strict observation above still runs first; only a proven-covered editor stops blocking.
        if (recovery && packaging.pending && !reported.dirty && !reported.busy && !reported.pending
                && packagingCoverage(host).covered) packaging = empty();
        return { ...sources, packaging };
    }
    function capture(sources, rendererGeneration) {
        if (!sources || typeof rendererGeneration !== 'string' || !rendererGeneration
                || Object.keys(sources).length !== Object.keys(WORKFLOWS).length) {
            throw failure('desktop_workflow_coverage_unavailable');
        }
        const workflows = Object.keys(WORKFLOWS).map(workflowId => {
            const value = sources[workflowId];
            return { workflowId, ...checkedFlags(value) };
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
    return Object.freeze({ capture, assertEmpty, observePackaging, withPackaging, packagingCoverage, WORKFLOWS });
}));
