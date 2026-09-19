(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityDesktopAdapter = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    // Explicit installation only. Importing this module does not enable editing,
    // grant native authority, recover a transaction, or change a web session.
    function createAdapter(options) {
        const session = options && (options.session || options.app && options.app.session);
        if (!session || typeof session.installDesktopRecovery !== 'function') {
            throw new TypeError('A real facility session with desktop recovery hooks is required');
        }
        if (options.app && options.app.desktopRecovery) return options.app.desktopRecovery;
        return session.installDesktopRecovery({
            persistOperation: options.persistOperation,
            clearOperation: options.clearOperation,
            startupRecoveryPending: options.startupRecoveryPending === true,
        });
    }

    return Object.freeze({ apiVersion: 1, createAdapter: createAdapter });
}));
