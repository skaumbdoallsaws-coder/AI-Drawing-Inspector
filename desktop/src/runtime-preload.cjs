'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// Loaded only by the managed application window, never an external browser.
if (process.isMainFrame && process.argv.includes('--inspectorpro-desktop-managed')) {
  const MAX_JSON_CHARACTERS = 16 * 1024 * 1024;
  const ROOT_ID = 'trainFacilityLayoutAuthoring';
  const FACILITY_SURFACES = [
    '.facility-layout-ribbon .facility-ribbon-commandbar',
    '#trainFacilityLayoutAssets', '#trainRightRailPlayback',
    '#trainFacilityMotionPlaybackHost', '#themeToggleBtn',
  ];
  const METHODS = new Set(['snapshot', 'freeze', 'unfreeze', 'restoreRecovery',
    'acceptReconciliation', 'setStartupRecoveryGate', 'inspectOtherWorkflows']);
  const capabilities = { schemaVersion: 1, mode: 'desktop-managed', managedBackend: true,
    generalEditing: false, researchBrowsing: false, save: false, facilityAcceptance: false };
  let callback = null, facilityRoot = null, attached = false, gateBlocked = true;
  let facilitySurfaces = [];
  let forcedLock = false, freezeOwner = null;
  let researchObscures = false, researchStyle = null, lastOverlay = false;
  const cancelled = new Set(), seen = new Set(), pending = new Map();
  const nativeInert = typeof HTMLElement === 'function'
    ? Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'inert') : null;
  const nativeInertSupported = !!(nativeInert?.get && nativeInert?.set);
  const error = code => Object.assign(new Error(code), { code });
  const text = value => typeof value === 'string' && value.length > 0 && value.length <= 512;
  function json(value) {
    if (value === undefined) return undefined;
    const encoded = JSON.stringify(value);
    if (typeof encoded !== 'string' || encoded.length > MAX_JSON_CHARACTERS) throw error('desktop_runtime_payload_invalid');
    return JSON.parse(encoded);
  }
  function errorData(value) {
    return { code: typeof value?.code === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(value.code)
      ? value.code : 'desktop_runtime_renderer_error',
      message: typeof value?.message === 'string' ? value.message.slice(0, 1024) : 'Desktop renderer request failed' };
  }
  function canInteract() {
    return nativeInertSupported && attached && capabilities.facilityAcceptance && !gateBlocked && !forcedLock && !freezeOwner && !researchObscures
      && !!facilityRoot && facilityRoot.isConnected === true;
  }
  function inert(element, value) {
    if (nativeInert?.set && typeof HTMLElement === 'function' && element instanceof HTMLElement) {
      if (nativeInert.get.call(element) !== value) nativeInert.set.call(element, value);
    }
  }
  function inputRoots() {
    return [facilityRoot, ...facilitySurfaces].filter(node => node?.isConnected === true);
  }
  function enforceInputGate() {
    const body = document.body;
    if (!body) return;
    const allow = canInteract();
    const roots = allow ? inputRoots() : [];
    // The integrated facility ribbon and rails live outside the canvas root.
    // Capture their exact nodes at attachment; replacements inherit no grant.
    // Workflow selectors, global toolbars and Sage remain outside this set.
    function visit(parent) {
      for (const child of Array.from(parent.children || [])) {
        const onPath = roots.some(root => child === root || child.contains(root));
        let protectedRoot = child;
        if (!onPath && nativeInertSupported && !(child instanceof HTMLElement)) {
          // SVG.inert is only an expando. A real HTML ancestor also removes its
          // focusable descendants from Tab navigation out of the allowed area.
          const wrapper = document.createElement('div');
          wrapper.style.display = 'contents';
          wrapper.setAttribute('data-inspectorpro-runtime-inert-wrapper', '');
          inert(wrapper, true);
          parent.insertBefore(wrapper, child); wrapper.append(child);
          protectedRoot = wrapper;
        }
        inert(protectedRoot, !onPath);
        if (onPath && !roots.includes(child)) visit(child);
      }
    }
    visit(body);
  }
  for (const type of ['pointerdown', 'click', 'dblclick', 'keydown', 'drop', 'paste', 'beforeinput', 'submit']) {
    window.addEventListener(type, event => {
      if (!canInteract() || !inputRoots().some(root => event.composedPath().includes(root))) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
  }
  const observer = new MutationObserver(() => enforceInputGate());
  observer.observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['inert'] });
  document.addEventListener('DOMContentLoaded', enforceInputGate, { once: true });
  enforceInputGate();

  ipcRenderer.on('desktop-runtime:research-ready', () => { capabilities.researchBrowsing = true; });
  ipcRenderer.on('desktop-runtime:release-pointer', () => { document.exitPointerLock?.(); });
  ipcRenderer.on('desktop-runtime:research-layout', (_event, value) => {
    if (!value || typeof value.visible !== 'boolean' || !Number.isFinite(value.reservedCssPixels) || value.reservedCssPixels < 0) return;
    researchObscures = value.visible && value.obscuresApp === true;
    if (!researchStyle) { researchStyle = document.createElement('style'); document.head.appendChild(researchStyle); }
    researchStyle.textContent = value.visible && !researchObscures
      ? 'body{width:calc(100vw - ' + value.reservedCssPixels + 'px)!important;min-width:0!important;}' : '';
    document.exitPointerLock?.(); enforceInputGate(); window.dispatchEvent(new Event('resize'));
  });
  const overlayObserver = new MutationObserver(() => {
    const visible = Array.from(document.querySelectorAll('dialog[open],[aria-modal="true"],.modal-overlay.active'))
      .some(node => node.getBoundingClientRect().width > 0 && node.getBoundingClientRect().height > 0);
    if (visible !== lastOverlay) { lastOverlay = visible; ipcRenderer.send('desktop-runtime:overlay', visible); }
  });
  overlayObserver.observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['open', 'aria-modal', 'class', 'hidden'] });
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href]');
    if (!event.isTrusted || !link || !/^https:\/\//i.test(link.href)) return;
    event.preventDefault(); event.stopPropagation();
    ipcRenderer.invoke('desktop-runtime:open-research', link.href).catch(() => {});
  }, true);

  ipcRenderer.on('desktop-runtime:input-lock', (_event, request) => {
    // A lock can always be tightened. Only verified attachment/guarded facade
    // replies below can release it, never a renderer-controlled boolean.
    if (request?.locked === true) { forcedLock = true; enforceInputGate(); }
  });
  ipcRenderer.on('desktop-runtime:facility-cancel', (_event, request) => {
    if (text(request?.requestId)) {
      cancelled.add(request.requestId);
      pending.get(request.requestId)?.abort(error('desktop_runtime_request_cancelled'));
      if (cancelled.size > 2048) cancelled.delete(cancelled.values().next().value);
    }
  });
  ipcRenderer.on('desktop-runtime:facility-command', (_event, message) => {
    const requestId = message?.requestId;
    if (!text(requestId)) return;
    function reply(value) { ipcRenderer.send('desktop-runtime:facility-reply', json({ requestId, ...value })); }
    if (!METHODS.has(message.method) || seen.has(requestId) || !callback
        || !Number.isSafeInteger(message.deadlineUnixMs)
        || message.deadlineUnixMs <= Date.now() || message.deadlineUnixMs > Date.now() + 60000) {
      reply({ ok: false, error: errorData(error('desktop_runtime_request_rejected')) }); return;
    }
    seen.add(requestId);
    if (seen.size > 2048) seen.delete(seen.values().next().value);
    const handler = callback, controller = new AbortController();
    pending.set(requestId, controller);
    const timer = setTimeout(() => controller.abort(error('desktop_runtime_request_expired')),
      Math.max(1, message.deadlineUnixMs - Date.now()));
    // Functions are proxied by contextBridge. An AbortSignal itself is not a
    // supported cross-world value; keep it private and expose only fixed guards.
    const control = Object.freeze({ assertCurrent() {
      if (controller.signal.aborted) throw controller.signal.reason;
      if (cancelled.has(requestId)) throw error('desktop_runtime_request_cancelled');
      if (callback !== handler) throw error('desktop_runtime_renderer_detached');
      if (Date.now() >= message.deadlineUnixMs) throw error('desktop_runtime_request_expired');
    } });
    Promise.resolve().then(() => {
      control.assertCurrent();
      return handler(json({ requestId, method: message.method, args: message.args }), control);
    }).then(envelope => {
      if (!envelope || envelope.ok !== true) {
        control.assertCurrent();
        const code = envelope?.error?.code;
        throw error(typeof code === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(code)
          ? code : 'desktop_runtime_renderer_error');
      }
      const state = json(envelope.result);
      // A freeze may have completed before its acknowledgement was cancelled.
      // Preserve its owner so the explicit owning Cancel can still release it.
      if (message.method === 'freeze') { freezeOwner = message.args?.intentId; enforceInputGate(); }
      control.assertCurrent();
      // The real facade validates sequence/generation/intent before producing
      // these replies. A stale or failed request never releases the input lock.
      if (message.method === 'unfreeze' && freezeOwner === message.args?.intentId) {
        freezeOwner = null; forcedLock = false;
      }
      if (message.method === 'setStartupRecoveryGate') {
        gateBlocked = state?.startupRecoveryPending !== false;
        if (!gateBlocked) forcedLock = false;
      }
      if (message.method === 'restoreRecovery') gateBlocked = true;
      enforceInputGate();
      reply({ ok: true, result: state });
    }).catch(failure => { reply({ ok: false, error: errorData(failure) }); })
      .finally(() => {
        clearTimeout(timer); pending.delete(requestId);
        controller.abort(error('desktop_runtime_request_finished'));
      });
  });

  contextBridge.exposeInMainWorld('InspectorProDesktop', Object.freeze({
    getCapabilities: () => Object.freeze({ ...capabilities }),
    getRuntime: async () => json(await ipcRenderer.invoke('desktop-runtime:status')),
    onLifecycleRequest(handler) {
      if (typeof handler !== 'function' || callback) throw error('desktop_runtime_handler_invalid');
      callback = handler;
      return () => { if (callback === handler) {
        callback = null; attached = false; gateBlocked = true;
        for (const controller of pending.values()) controller.abort(error('desktop_runtime_renderer_detached'));
        enforceInputGate();
      } };
    },
    async attachFacility(binding) {
      if (!callback || attached) throw error('desktop_runtime_attach_invalid');
      const node = document.getElementById(ROOT_ID);
      if (!node || node === document.body || !node.isConnected) throw error('desktop_runtime_facility_root_missing');
      const surfaces = FACILITY_SURFACES.flatMap(selector => {
        const matches = Array.from(document.querySelectorAll(selector));
        if (matches.length > 1) throw error('desktop_runtime_facility_surface_ambiguous');
        return matches;
      });
      // Capture before IPC. A replaced node cannot inherit this grant by ID.
      facilityRoot = node;
      facilitySurfaces = surfaces;
      const result = json(await ipcRenderer.invoke('desktop-runtime:facility-attach', json(binding)));
      if (result?.ready !== true || document.getElementById(ROOT_ID) !== node || !node.isConnected
          || surfaces.some(surface => !surface.isConnected)) {
        gateBlocked = true; enforceInputGate(); throw error('desktop_runtime_attach_rejected');
      }
      attached = true;
      capabilities.facilityAcceptance = result.capabilities?.facilityAcceptance === true;
      gateBlocked = result.recoveryRequired !== false;
      forcedLock = false;
      enforceInputGate();
      return result;
    },
    persistOperation: async record => json(await ipcRenderer.invoke('desktop-runtime:facility-persist', json(record))),
    clearOperation: async record => json(await ipcRenderer.invoke('desktop-runtime:facility-clear', json(record))),
    requestClose: async () => json(await ipcRenderer.invoke('desktop-runtime:close')),
    restartBackend: async () => json(await ipcRenderer.invoke('desktop-runtime:restart')),
    openResearch: async url => json(await ipcRenderer.invoke('desktop-runtime:open-research', url)),
    getInputLockDiagnostics: () => ({ schemaVersion: 1, attached, gateBlocked, forcedLock, nativeInertSupported,
      frozen: !!freezeOwner, facilityConnected: !!facilityRoot?.isConnected,
      facilityInputAllowed: canInteract(), generalEditing: false, researchBrowsing: capabilities.researchBrowsing, save: false }),
  }));
}
