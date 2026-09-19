(function (root, factory) {
    'use strict';
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityApp = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const API_VERSION = 1;

    function requireFunction(value, label) {
        if (typeof value !== 'function') {
            throw new TypeError(label + ' is required');
        }
        return value;
    }

    function requireRoot(value) {
        if (!value || !value.ownerDocument) {
            throw new TypeError('root element is required');
        }
        return value;
    }

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function moduleApi(options, key, globalKey) {
        const value = options[key] || (root && root[globalKey]);
        if (!value || typeof value !== 'object') {
            throw new TypeError(key + ' runtime is required');
        }
        return value;
    }

    function destroyedError() {
        const error = new Error('facility layout app is destroyed');
        error.name = 'AbortError';
        error.code = 'facility_layout_app_destroyed';
        return error;
    }

    function designUndoRecoveryStore(options) {
        // An explicit async adapter is separate from the synchronous Web Storage
        // API. A durable native acknowledgment must actually be awaited.
        if (options.designUndoRecovery !== undefined) {
            const recovery = options.designUndoRecovery;
            ['load', 'persist', 'clear'].forEach(function (name) {
                requireFunction(recovery && recovery[name], 'designUndoRecovery.' + name);
            });
            return {
                load: async function () { return clone(await recovery.load()); },
                persist: async function (record) { await recovery.persist(clone(record)); },
                clear: async function () { await recovery.clear(); },
            };
        }
        const storage = options.designUndoRecoveryStorage
            || (root && root.sessionStorage) || null;
        const key = 'InspectorPro:facility-design-undo:'
            + String(options.siteId || 'site-local') + ':'
            + String(options.layoutId || 'fl-main');
        if (!storage || typeof storage.getItem !== 'function'
                || typeof storage.setItem !== 'function'
                || typeof storage.removeItem !== 'function') {
            return {
                load: async function () { return null; },
                persist: async function () {},
                clear: async function () {},
            };
        }
        return {
            load: async function () {
                const encoded = storage.getItem(key);
                if (!encoded) return null;
                try {
                    return JSON.parse(encoded);
                } catch (_error) {
                    storage.removeItem(key);
                    return null;
                }
            },
            persist: async function (record) {
                storage.setItem(key, JSON.stringify(record));
            },
            clear: async function () {
                storage.removeItem(key);
            },
        };
    }

    async function resolveSpatialAdvisorRuntime(options) {
        let runtime = options.spatialAdvisorRuntime
            || (root && root.InspectorProFacilitySpatialAdvisor)
            || null;
        if (runtime || options.enableSpatialAdvisory === false
                || !(options.Worker || (root && root.Worker))) {
            return runtime;
        }
        try {
            await import(
                options.spatialAdvisorModuleUrl
                || '/static/facility_layout_spatial_advisor.js'
            );
            runtime = root && root.InspectorProFacilitySpatialAdvisor || null;
        } catch (error) {
            if (typeof options.onAdvisoryUnavailable === 'function') {
                options.onAdvisoryUnavailable(error);
            }
        }
        return runtime;
    }

    function createFacilityLayoutApp(inputOptions) {
        const options = inputOptions || {};
        const host = requireRoot(options.root);
        const Transport = moduleApi(
            options,
            'transportRuntime',
            'InspectorProFacilityTransport'
        );
        const Session = moduleApi(
            options,
            'sessionRuntime',
            'InspectorProFacilitySession'
        );
        const Workspace = moduleApi(
            options,
            'workspaceRuntime',
            'InspectorProFacilityWorkspace'
        );
        const Layout = moduleApi(
            options,
            'layoutRuntime',
            'InspectorProFacilityLayout'
        );
        const transport = options.transport
            || requireFunction(
                Transport.createHttpTransport,
                'createHttpTransport'
            )({
                siteId: options.siteId,
                layoutId: options.layoutId,
                baseUrl: options.baseUrl,
                headers: options.headers,
                credentials: options.credentials,
                fetch: options.fetch,
                sessionId: options.sessionId,
            });
        const designUndoRecovery = designUndoRecoveryStore(options);
        const session = options.session
            || requireFunction(Session.createSession, 'createSession')({
                previewOperations: transport.previewOperations,
                sessionId: transport.sessionId,
                applyOperations: transport.applyOperations,
                reloadLayout: transport.reloadLayout,
                placementCandidates: transport.placementCandidates,
                placementCandidatePreview:
                    transport.placementCandidatePreview,
                createLayoutProposals: transport.createLayoutProposals,
                getLayoutProposalPreview:
                    transport.getLayoutProposalPreview,
                cancelLayoutProposal: transport.cancelLayoutProposal,
                approveLayoutProposal: transport.approveLayoutProposal,
                applyLayoutProposal: transport.applyLayoutProposal,
                getLayoutReceipt: transport.getLayoutReceipt,
                undoGenerationDraft: transport.undoGenerationRun,
                saveGenerationDraft: transport.saveGenerationRun,
                prepareDesignProposalApply:
                    transport.prepareDesignProposalApply,
                commitDesignProposalApply:
                    transport.commitDesignProposalApply,
                acknowledgeDesignProposalApply:
                    transport.acknowledgeDesignProposalApply,
                recoverDesignProposalApply:
                    transport.recoverDesignProposalApply,
                saveDesignProposalDraft:
                    transport.saveDesignProposalDraft,
                prepareDesignUndo: transport.prepareDesignUndo,
                acknowledgeDesignUndo: transport.acknowledgeDesignUndo,
                loadDesignUndoRecovery: designUndoRecovery.load,
                persistDesignUndoRecovery: designUndoRecovery.persist,
                clearDesignUndoRecovery: designUndoRecovery.clear,
            });
        const desktopRecovery = options.desktopRecoveryHooks
            ? requireFunction(session.installDesktopRecovery, 'installDesktopRecovery')(
                options.desktopRecoveryHooks) : null;

        let workspace = null;
        let spatialAdvisor = options.spatialAdvisor || null;
        let ownsSpatialAdvisor = false;
        let destroyed = false;
        let suspended = false;
        let loadReceipt = null;
        let error = null;

        const ready = Promise.resolve().then(async function () {
            if (destroyed) throw destroyedError();
            const receipt = options.initialReceipt
                || await transport.reloadLayout();
            if (destroyed) throw destroyedError();
            if (!spatialAdvisor) {
                const SpatialAdvisor = await resolveSpatialAdvisorRuntime(options);
                if (destroyed) throw destroyedError();
                if (SpatialAdvisor
                        && typeof SpatialAdvisor.createSpatialAdvisor
                            === 'function') {
                    spatialAdvisor = SpatialAdvisor.createSpatialAdvisor({
                        Worker: options.Worker,
                        workerFactory: options.spatialWorkerFactory,
                        workerUrl: options.spatialWorkerUrl,
                    });
                    ownsSpatialAdvisor = true;
                }
            }
            loadReceipt = receipt;
            session.load(loadReceipt);
            if (typeof session.resumeDesignUndoRecovery === 'function') {
                try {
                    await session.resumeDesignUndoRecovery();
                } catch (caught) {
                    error = caught;
                    if (typeof options.onError === 'function') {
                        options.onError(caught);
                    }
                }
            }
            workspace = requireFunction(
                Workspace.createWorkspace,
                'createWorkspace'
            )({
                root: host,
                session: session,
                motionTransport: transport,
                designTransport: transport,
                layoutRuntime: Layout,
                assetCatalog: options.assetCatalog || [],
                capabilities: options.capabilities || {},
                externalCommandSurface:
                    options.externalCommandSurface === true,
                gridSize: options.gridSize,
                motionPanelHost: options.motionPanelHost,
                topPlanOptions: options.topPlanOptions,
                threeRuntime: options.threeRuntime
                    || (root && root.InspectorProFacilityThree),
                threeOptions: options.threeOptions,
                eventToWorld: options.eventToWorld,
                marqueeResolver: options.marqueeResolver,
                installPlanMarquee: options.installPlanMarquee,
                commandIcons: options.commandIcons,
                spatialAdvisor: spatialAdvisor,
                ownsSpatialAdvisor: false,
                useAuthoritativePlacementCandidates:
                    options.useAuthoritativePlacementCandidates === true,
                onAssetBrowserStateChange:
                    options.onAssetBrowserStateChange,
                onCommandStateChange: options.onCommandStateChange,
                onMotionPanelVisibilityChange:
                    options.onMotionPanelVisibilityChange,
                onStateChange: options.onStateChange,
                onError: options.onError,
            });
            if (suspended && typeof workspace.suspend === 'function') {
                workspace.suspend();
            }
            return app;
        }).catch(function (caught) {
            if (caught && caught.code === 'facility_layout_app_destroyed') {
                throw caught;
            }
            error = caught;
            if (typeof options.onError === 'function') options.onError(caught);
            throw caught;
        });

        const app = Object.freeze({
            apiVersion: API_VERSION,
            ready: ready,
            get transport() { return transport; },
            get session() { return session; },
            get desktopRecovery() { return desktopRecovery; },
            get workspace() { return workspace; },
            getState: function () {
                return {
                    apiVersion: API_VERSION,
                    destroyed: destroyed,
                    suspended: suspended,
                    loaded: Boolean(workspace),
                    error: error,
                    loadReceipt: clone(loadReceipt),
                    spatialAdvisor: spatialAdvisor
                        && typeof spatialAdvisor.getState === 'function'
                        ? clone(spatialAdvisor.getState())
                        : null,
                    workspace: workspace ? workspace.getState() : null,
                };
            },
            suspend: function () {
                if (destroyed || suspended) return false;
                suspended = true;
                if (workspace && typeof workspace.suspend === 'function') {
                    workspace.suspend();
                }
                return true;
            },
            resume: function (nextRoot) {
                if (destroyed || !suspended) return false;
                suspended = false;
                if (workspace && typeof workspace.resume === 'function') {
                    workspace.resume(nextRoot || host);
                }
                return true;
            },
            destroy: function () {
                if (destroyed) return false;
                destroyed = true;
                suspended = false;
                if (workspace) workspace.destroy();
                workspace = null;
                if (ownsSpatialAdvisor && spatialAdvisor
                        && typeof spatialAdvisor.destroy === 'function') {
                    spatialAdvisor.destroy();
                }
                spatialAdvisor = null;
                ownsSpatialAdvisor = false;
                loadReceipt = null;
                return true;
            },
        });
        return app;
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        createFacilityLayoutApp: createFacilityLayoutApp,
    });
}));
