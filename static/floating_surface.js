(function (root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFloating = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    let missingRuntimeWarned = false;

    function noop() {}

    function warnMissingRuntime(logger) {
        if (missingRuntimeWarned) return;
        missingRuntimeWarned = true;
        const target = logger && typeof logger.warn === 'function'
            ? logger
            : (root && root.console);
        if (target && typeof target.warn === 'function') {
            target.warn('InspectorPro floating surfaces are disabled: FloatingUIDOM is unavailable.');
        }
    }

    function resolvePositioning(options) {
        const candidate = options.positioning || (root && root.FloatingUIDOM);
        if (!candidate
            || typeof candidate.computePosition !== 'function'
            || typeof candidate.autoUpdate !== 'function') {
            return null;
        }
        return candidate;
    }

    function validReference(value) {
        return !!value && typeof value.getBoundingClientRect === 'function';
    }

    function validSurface(value) {
        return !!value && !!value.style;
    }

    function createDisabledManager() {
        return {
            available: false,
            open: function () { return false; },
            close: function () { return false; },
            destroy: noop,
            reanchor: function () { return false; },
            reposition: function () { return Promise.resolve(false); },
            isOpen: function () { return false; },
            getActive: function () { return null; },
        };
    }

    function createSurfaceManager(inputOptions) {
        const options = inputOptions || {};
        const doc = options.document || (root && root.document);
        const positioning = resolvePositioning(options);
        const logger = options.logger || (root && root.console);
        if (!doc || !doc.body || !positioning) {
            warnMissingRuntime(logger);
            return createDisabledManager();
        }

        let active = null;
        let destroyed = false;
        let generation = 0;
        let positionRequest = 0;
        let cleanupAutoUpdate = null;
        let listenersAttached = false;

        function reportError(error) {
            if (active && typeof active.onError === 'function') {
                active.onError(error);
                return;
            }
            if (logger && typeof logger.warn === 'function') {
                logger.warn('InspectorPro floating surface positioning failed.', error);
            }
        }

        function removeAutoUpdate() {
            const cleanup = cleanupAutoUpdate;
            cleanupAutoUpdate = null;
            if (typeof cleanup === 'function') cleanup();
        }

        function focusReference(record) {
            if (!record || record.restoreFocus === false) return;
            const target = record.restoreFocusElement || record.reference;
            if (!target || target.isConnected === false || typeof target.focus !== 'function') return;
            try {
                target.focus({ preventScroll: true });
            } catch (_error) {
                target.focus();
            }
        }

        function removeSurface(record) {
            if (!record || record.removeOnClose === false || !record.floating) return;
            if (typeof record.floating.remove === 'function') {
                record.floating.remove();
            } else if (record.floating.parentNode
                && typeof record.floating.parentNode.removeChild === 'function') {
                record.floating.parentNode.removeChild(record.floating);
            }
        }

        function onDocumentPointerDown(event) {
            if (!active) return;
            const target = event && event.target;
            if ((active.floating && typeof active.floating.contains === 'function'
                && active.floating.contains(target))
                || (active.reference && typeof active.reference.contains === 'function'
                    && active.reference.contains(target))) {
                return;
            }
            if (typeof active.shouldCloseOnOutsidePointerDown === 'function'
                && active.shouldCloseOnOutsidePointerDown(event) === false) {
                return;
            }
            close('outside_pointerdown');
        }

        function onDocumentKeyDown(event) {
            if (!active || !event || event.key !== 'Escape') return;
            if (typeof active.shouldCloseOnEscape === 'function'
                && active.shouldCloseOnEscape(event) === false) {
                return;
            }
            if (typeof event.preventDefault === 'function') event.preventDefault();
            if (typeof event.stopPropagation === 'function') event.stopPropagation();
            close('escape');
        }

        function attachListeners() {
            if (listenersAttached || typeof doc.addEventListener !== 'function') return;
            doc.addEventListener('pointerdown', onDocumentPointerDown, true);
            doc.addEventListener('keydown', onDocumentKeyDown, true);
            listenersAttached = true;
        }

        function detachListeners() {
            if (!listenersAttached || typeof doc.removeEventListener !== 'function') return;
            doc.removeEventListener('pointerdown', onDocumentPointerDown, true);
            doc.removeEventListener('keydown', onDocumentKeyDown, true);
            listenersAttached = false;
        }

        function reposition() {
            const record = active;
            if (!record) return Promise.resolve(false);
            const requestGeneration = generation;
            const requestId = ++positionRequest;
            let pending;
            try {
                pending = positioning.computePosition(record.reference, record.floating, {
                    placement: record.placement,
                    strategy: record.strategy,
                    middleware: record.middleware,
                });
            } catch (error) {
                reportError(error);
                return Promise.resolve(false);
            }
            return Promise.resolve(pending).then(function (result) {
                if (!active || active !== record || generation !== requestGeneration
                    || positionRequest !== requestId) return false;
                record.floating.style.position = result.strategy || record.strategy;
                record.floating.style.left = String(result.x) + 'px';
                record.floating.style.top = String(result.y) + 'px';
                if (result.placement && typeof record.floating.setAttribute === 'function') {
                    record.floating.setAttribute('data-placement', result.placement);
                }
                if (typeof record.onPosition === 'function') record.onPosition(result);
                return true;
            }).catch(function (error) {
                if (active === record && generation === requestGeneration
                    && positionRequest === requestId) reportError(error);
                return false;
            });
        }

        function startAutoUpdate() {
            removeAutoUpdate();
            if (!active) return;
            try {
                cleanupAutoUpdate = positioning.autoUpdate(
                    active.reference,
                    active.floating,
                    reposition,
                    active.autoUpdateOptions
                );
            } catch (error) {
                cleanupAutoUpdate = null;
                reportError(error);
                reposition();
            }
        }

        function close(reason, closeOptions) {
            if (!active) return false;
            const record = active;
            active = null;
            generation += 1;
            positionRequest += 1;
            removeAutoUpdate();
            detachListeners();
            removeSurface(record);
            const restore = !closeOptions || closeOptions.restoreFocus !== false;
            if (restore) focusReference(record);
            if (typeof record.onClose === 'function') {
                record.onClose(reason || 'programmatic');
            }
            return true;
        }

        function open(config) {
            const next = config || {};
            if (destroyed || !validReference(next.reference) || !validSurface(next.floating)) {
                return false;
            }
            if (active) close('replaced', { restoreFocus: false });
            if (next.floating.parentNode !== doc.body && typeof doc.body.appendChild === 'function') {
                doc.body.appendChild(next.floating);
            }
            active = {
                reference: next.reference,
                floating: next.floating,
                placement: next.placement || 'top',
                strategy: next.strategy || 'fixed',
                middleware: Array.isArray(next.middleware) ? next.middleware : [],
                autoUpdateOptions: next.autoUpdateOptions || {},
                removeOnClose: next.removeOnClose !== false,
                restoreFocus: next.restoreFocus !== false,
                restoreFocusElement: next.restoreFocusElement || null,
                onClose: next.onClose,
                onError: next.onError,
                onPosition: next.onPosition,
                shouldCloseOnOutsidePointerDown: next.shouldCloseOnOutsidePointerDown,
                shouldCloseOnEscape: next.shouldCloseOnEscape,
                key: next.key == null ? null : String(next.key),
            };
            generation += 1;
            active.floating.style.position = active.strategy;
            attachListeners();
            startAutoUpdate();
            return true;
        }

        function updateActiveConfig(config) {
            if (!active || !config) return;
            if (config.placement) active.placement = config.placement;
            if (config.strategy) active.strategy = config.strategy;
            if (Array.isArray(config.middleware)) active.middleware = config.middleware;
            if (config.autoUpdateOptions) active.autoUpdateOptions = config.autoUpdateOptions;
            if (config.restoreFocusElement) active.restoreFocusElement = config.restoreFocusElement;
        }

        function reanchor(reference, config) {
            if (!active || !validReference(reference)) return false;
            updateActiveConfig(config);
            if (active.reference === reference) {
                generation += 1;
                reposition();
                return true;
            }
            active.reference = reference;
            generation += 1;
            startAutoUpdate();
            return true;
        }

        function destroy() {
            if (destroyed) return;
            destroyed = true;
            close('destroyed', { restoreFocus: false });
        }

        return {
            available: true,
            open,
            close,
            destroy,
            reanchor,
            reposition,
            isOpen: function () { return !!active; },
            getActive: function () {
                if (!active) return null;
                return {
                    key: active.key,
                    reference: active.reference,
                    floating: active.floating,
                    placement: active.placement,
                    strategy: active.strategy,
                };
            },
        };
    }

    return {
        createSurfaceManager,
    };
});
