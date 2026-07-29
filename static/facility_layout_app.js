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
            });
        const session = options.session
            || requireFunction(Session.createSession, 'createSession')({
                previewOperations: transport.previewOperations,
                applyOperations: transport.applyOperations,
                reloadLayout: transport.reloadLayout,
            });

        let workspace = null;
        let destroyed = false;
        let loadReceipt = null;
        let error = null;

        const ready = Promise.resolve().then(async function () {
            if (destroyed) throw destroyedError();
            const receipt = options.initialReceipt
                || await transport.reloadLayout();
            if (destroyed) throw destroyedError();
            loadReceipt = receipt;
            session.load(loadReceipt);
            workspace = requireFunction(
                Workspace.createWorkspace,
                'createWorkspace'
            )({
                root: host,
                session: session,
                layoutRuntime: Layout,
                assetCatalog: options.assetCatalog || [],
                gridSize: options.gridSize,
                topPlanOptions: options.topPlanOptions,
                threeRuntime: options.threeRuntime
                    || (root && root.InspectorProFacilityThree),
                threeOptions: options.threeOptions,
                eventToWorld: options.eventToWorld,
                marqueeResolver: options.marqueeResolver,
                installPlanMarquee: options.installPlanMarquee,
                commandIcons: options.commandIcons,
                onStateChange: options.onStateChange,
                onError: options.onError,
            });
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
            get workspace() { return workspace; },
            getState: function () {
                return {
                    apiVersion: API_VERSION,
                    destroyed: destroyed,
                    loaded: Boolean(workspace),
                    error: error,
                    loadReceipt: clone(loadReceipt),
                    workspace: workspace ? workspace.getState() : null,
                };
            },
            destroy: function () {
                if (destroyed) return false;
                destroyed = true;
                if (workspace) workspace.destroy();
                workspace = null;
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
