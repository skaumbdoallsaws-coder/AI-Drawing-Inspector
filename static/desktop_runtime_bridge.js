(function (root, factory) {
    'use strict';
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProDesktopRuntimeBridge = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const METHODS = new Set(['snapshot', 'freeze', 'unfreeze', 'restoreRecovery',
        'acceptReconciliation', 'setStartupRecoveryGate', 'inspectOtherWorkflows']);
    const prepared = new WeakMap();
    let active = null;
    let startupPromise = null;
    let inspectOtherWorkflows = null;
    let startupState = { status: 'not-started', stage: 'not-started', code: null, documentId: null };
    const clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
    const failure = code => Object.assign(new Error(code), { code });
    const sameFields = (left, right, fields) => fields.every(key => left[key] === right[key]);
    function desktop() {
        const value = root && root.InspectorProDesktop;
        return value && typeof value.getRuntime === 'function'
            && typeof value.onLifecycleRequest === 'function' ? value : null;
    }
    function validRuntime(value, options) {
        if (!value || value.schemaVersion !== 1 || value.mode !== 'desktop-managed'
                || !value.identity || !value.owner
                || ['backendId', 'storeId', 'principalId'].some(key => typeof value.identity[key] !== 'string' || !value.identity[key])
                || ['sessionId', 'ownerId'].some(key => typeof value.owner[key] !== 'string' || !value.owner[key])
                || typeof value.instanceId !== 'string' || !value.instanceId
                || value.capabilities?.generalEditing !== false
                || typeof value.capabilities?.researchBrowsing !== 'boolean'
                || (value.capabilities.researchBrowsing && value.capabilities.researchIsolation !== 'public-https-proxy-v1')
                || typeof value.capabilities?.facilityAcceptance !== 'boolean') {
            throw failure('desktop_runtime_facility_binding');
        }
        if (value.document === null && value.capabilities.facilityAcceptance === false) return value;
        if (!value.document || typeof value.document.tenantId !== 'string' || !value.document.tenantId
                || value.document.siteId !== options.siteId || value.document.documentId !== options.layoutId) {
            throw failure('desktop_runtime_facility_binding');
        }
        return value;
    }
    function pendingLegacyRecovery(options) {
        const storage = options.designUndoRecoveryStorage || root.sessionStorage;
        const key = 'InspectorPro:facility-design-undo:' + String(options.siteId || 'site-local')
            + ':' + String(options.layoutId || 'fl-main');
        // Retain every existing value, including malformed data, for explicit
        // recovery. The desktop partition never silently migrates web state.
        if (storage && typeof storage.getItem === 'function' && storage.getItem(key) !== null) {
            throw failure('desktop_runtime_legacy_recovery_required');
        }
    }
    function startFacilityWorkspace({ activateFacility, inspectOtherWorkflows: inspect } = {}) {
        if (startupPromise) return startupPromise;
        startupPromise = (async () => {
            const native = desktop();
            if (!native) return (startupState = { ...startupState, status: 'browser', stage: 'complete' });
            if (typeof inspect === 'function') inspectOtherWorkflows = inspect;
            startupState = { ...startupState, status: 'starting', stage: 'runtime-validation' };
            const supplied = await native.getRuntime();
            if (supplied?.status !== 'ready' || supplied?.capabilities?.save !== false) throw failure('desktop_runtime_not_ready');
            const runtime = validRuntime(supplied, { siteId: supplied.document?.siteId, layoutId: supplied.document?.documentId });
            if (runtime.document === null) return (startupState = { ...startupState, status: 'read-only', stage: 'complete' });
            if (runtime.capabilities.facilityAcceptance !== true || runtime.document.siteId !== 'site-local'
                    || !/^fl-[A-Za-z0-9._-]{1,128}$/.test(runtime.document.documentId)) throw failure('desktop_runtime_facility_binding');
            const query = new URLSearchParams(root.location?.search || '');
            const requested = query.getAll('facilityLayoutId');
            if (requested.length > 1 || (requested.length === 1 && requested[0] !== runtime.document.documentId)) {
                throw failure('desktop_runtime_startup_document_mismatch');
            }
            if (typeof activateFacility !== 'function') throw failure('desktop_runtime_startup_unavailable');
            startupState = { ...startupState, stage: 'activating', documentId: runtime.document.documentId };
            const mounted = await activateFacility(clone(runtime.document));
            startupState = { ...startupState, stage: 'attachment-verification' };
            if (mounted !== true || !active?.attached || !active.element.isConnected
                    || !sameFields(active.runtime.identity, runtime.identity, ['backendId', 'storeId', 'principalId'])
                    || !sameFields(active.runtime.owner, runtime.owner, ['sessionId', 'ownerId'])
                    || !sameFields(active.runtime.document, runtime.document, ['tenantId', 'siteId', 'documentId'])
                    || active.runtime.instanceId !== runtime.instanceId) throw failure('desktop_runtime_startup_not_attached');
            startupState = { ...startupState, status: 'ready', stage: 'complete' };
            return clone(startupState);
        })().catch(error => {
            startupState = { ...startupState, status: 'failed', code: error.code || 'desktop_runtime_startup_failed' };
            throw error;
        });
        return startupPromise;
    }
    async function prepareFacilityOptions(input) {
        const native = desktop();
        if (!native) return input;
        const runtime = validRuntime(await native.getRuntime(), input);
        if (input.desktopRecoveryHooks || input.designUndoRecovery) throw failure('desktop_runtime_recovery_already_configured');
        pendingLegacyRecovery(input);
        const options = Object.assign({}, input, {
            sessionId: runtime.owner.sessionId,
            // The installed desktop hook owns all durable operation checkpoints.
            // Do not read, clear, or overwrite legacy sessionStorage records.
            designUndoRecovery: { load: async () => null, persist: async () => {}, clear: async () => {} },
        });
        prepared.set(options, { runtime, native });
        return options;
    }
    async function attachFacility(app, element, options) {
        const native = desktop();
        if (!native) return { mode: 'browser', attached: false };
        if (active || !app || !element || !prepared.has(options)) throw failure('desktop_runtime_attach_invalid');
        const setup = prepared.get(options);
        await app.ready;
        if (app.getState().destroyed || !element.isConnected) throw failure('desktop_runtime_facility_unavailable');
        pendingLegacyRecovery(options);
        const currentRuntime = validRuntime(await native.getRuntime(), options);
        if (!setup.runtime.document && !currentRuntime.document) {
            // No acceptance document was granted. Preload remains fully locked;
            // read-only rendering does not install a write/recovery authority.
            return { mode: 'desktop-managed', attached: false, readOnly: true };
        }
        if (!setup.runtime.document || !currentRuntime.document) throw failure('desktop_runtime_identity_changed');
        if (!sameFields(currentRuntime.identity, setup.runtime.identity, ['backendId', 'storeId', 'principalId'])
                || !sameFields(currentRuntime.owner, setup.runtime.owner, ['sessionId', 'ownerId'])
                || !sameFields(currentRuntime.document, setup.runtime.document, ['tenantId', 'siteId', 'documentId'])
                || currentRuntime.instanceId !== setup.runtime.instanceId) throw failure('desktop_runtime_identity_changed');
        // The host ID owns the integrated ribbon/pane CSS and workspace lookup.
        // Desktop recovery must bind that existing element, not rename it.
        if (element.id !== 'trainFacilityLayoutAuthoring') throw failure('desktop_runtime_facility_root_missing');
        const facade = app.session.installDesktopRecovery({ startupRecoveryPending: true, allowSave: false,
            binding: { identity: clone(currentRuntime.identity), document: clone(currentRuntime.document), owner: clone(currentRuntime.owner) },
            persistOperation: record => native.persistOperation(record),
            clearOperation: record => native.clearOperation(record) });
        const entry = { app, element, facade, runtime: currentRuntime, attached: false };
        active = entry;
        const unsubscribe = native.onLifecycleRequest((request, control) => {
            try {
                if (!control || typeof control.assertCurrent !== 'function') throw failure('desktop_runtime_control_required');
                control.assertCurrent();
                if (active !== entry || app.getState().destroyed || !element.isConnected) throw failure('desktop_runtime_facility_unavailable');
                if (!request || !METHODS.has(request.method)) throw failure('desktop_runtime_request_rejected');
                if (request.method === 'unfreeze' && request.args?.rendererGeneration
                        && request.args.rendererGeneration !== facade.snapshot().rendererGeneration) throw failure('facility_desktop_stale_state');
                // These installed session facade methods are synchronous. Check
                // the proxied main-owned cancellation guard at the actual effect.
                control.assertCurrent();
                let result;
                if (request.method === 'inspectOtherWorkflows') {
                    if (!inspectOtherWorkflows || !root.InspectorProDesktopWorkflowObservation) {
                        throw failure('desktop_workflow_coverage_unavailable');
                    }
                    result = root.InspectorProDesktopWorkflowObservation.capture(
                        inspectOtherWorkflows(), facade.snapshot().rendererGeneration);
                } else result = request.method === 'snapshot' ? facade.snapshot() : facade[request.method](request.args);
                control.assertCurrent();
                return { ok: true, result: clone(result) };
            } catch (error) {
                // Explicit data retains typed errors across Electron worlds;
                // thrown Error custom properties are not relied upon over IPC.
                return { ok: false, error: { code: typeof error?.code === 'string' ? error.code : 'desktop_runtime_renderer_error' } };
            }
        });
        const snapshot = facade.snapshot();
        try {
            const reply = await native.attachFacility({ schemaVersion: 1,
                identity: clone(currentRuntime.identity), owner: clone(currentRuntime.owner),
                document: Object.assign({}, currentRuntime.document, snapshot.document),
                runtimeInstanceId: currentRuntime.instanceId,
                rendererGeneration: snapshot.rendererGeneration, stateSequence: snapshot.stateSequence });
            if (reply?.ready !== true) throw failure('desktop_runtime_attach_rejected');
            entry.attached = true;
            return { mode: 'desktop-managed', attached: true, recoveryRequired: reply.recoveryRequired !== false };
        } catch (error) {
            unsubscribe();
            if (active === entry) active = null;
            // The installed session gate remains blocked; a new mount or an
            // explicit recovery decision is required after failed attachment.
            throw error;
        }
    }
    return Object.freeze({ prepareFacilityOptions, attachFacility, startFacilityWorkspace,
        getStartupStatus: () => clone(startupState) });
}));
