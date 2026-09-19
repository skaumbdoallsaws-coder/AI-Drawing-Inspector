'use strict';

const { contextBridge, ipcRenderer } = require('electron');
const capabilities = Object.freeze({ schemaVersion: 1, mode: 'rendering-spike', interactive: false,
  researchBrowsing: false, managedBackend: false, durableWorkflowRecovery: false });
let inputLockDiagnostics = () => ({ schemaVersion: 1, mainFrame: false, acknowledged: false,
  nativeInertSupported: false, initial: { before: null, after: null }, repairHistory: [],
  current: { bodyPresent: false, totalRoots: 0, reportedRoots: 0, truncated: false,
    protectedRootCount: 0, allProtectedRootsLocked: false, roots: [] } });

// No filesystem, arbitrary IPC, script execution or backend credentials are exposed.
contextBridge.exposeInMainWorld('InspectorProDesktop', Object.freeze({
  getCapabilities: () => capabilities,
  getInputLockDiagnostics: () => inputLockDiagnostics(),
}));

if (process.isMainFrame) {
  let statusBanner = null;
  let initialized = false, acknowledged = false, observedBody = null;
  let initialBefore = null, initialAfter = null, repairSequence = 0;
  const repairHistory = [];
  const nativeInert = typeof HTMLElement === 'function'
    ? Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'inert') : null;
  const nativeInertSupported = Boolean(nativeInert && typeof nativeInert.get === 'function'
    && typeof nativeInert.set === 'function');
  const isHtml = element => typeof HTMLElement === 'function' && element instanceof HTMLElement;
  const bounded = (value, maximum = 96) => typeof value === 'string' ? value.slice(0, maximum) : '';
  function summary(element) {
    let inertValue, inertType = 'unavailable';
    try { inertValue = element.inert; inertType = typeof inertValue; } catch (_error) { /* Diagnostic read only. */ }
    return { tag: bounded(element.tagName, 32), namespace: bounded(element.namespaceURI, 128),
      id: bounded(element.getAttribute('id') || ''), className: bounded(element.getAttribute('class') || ''),
      inertAttribute: element.hasAttribute('inert'), inertType,
      inertOwnProperty: Object.prototype.hasOwnProperty.call(element, 'inert'),
      inertValue: typeof inertValue === 'boolean' ? inertValue : null,
      isHTMLElement: isHtml(element), banner: element === statusBanner };
  }
  function locked(element) {
    if (!nativeInertSupported || !isHtml(element)) return false;
    try {
      return nativeInert.get.call(element) === true && element.hasAttribute('inert');
    } catch (_error) { return false; }
  }
  function snapshot() {
    const body = document.body;
    const roots = body ? Array.from(body.children) : [];
    const protectedRoots = roots.filter(root => root !== statusBanner);
    return { bodyPresent: Boolean(body), totalRoots: roots.length, reportedRoots: Math.min(48, roots.length),
      truncated: roots.length > 48, protectedRootCount: protectedRoots.length,
      allProtectedRootsLocked: Boolean(body && statusBanner && statusBanner.parentNode === body
        && protectedRoots.length > 0 && protectedRoots.every(locked)),
      roots: roots.slice(0, 48).map(summary) };
  }
  function remember(reason, action, root) {
    repairHistory.push({ sequence: ++repairSequence, reason, action, rootSummary: summary(root) });
    if (repairHistory.length > 12) repairHistory.shift();
  }
  inputLockDiagnostics = () => JSON.parse(JSON.stringify({ schemaVersion: 1, mainFrame: true,
    acknowledged, nativeInertSupported, initial: { before: initialBefore, after: initialAfter },
    repairHistory, current: snapshot() }));

  // Install at preload time, before application listeners, including during loading.
  for (const type of ['pointerdown', 'click', 'dblclick', 'keydown', 'drop', 'paste', 'beforeinput', 'submit']) {
    window.addEventListener(type, event => {
      if (!statusBanner || !event.composedPath().includes(statusBanner)) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
  }
  function freeze(reason) {
    if (document.documentElement) document.documentElement.dataset.inspectorproDesktop = 'rendering-spike';
    const body = document.body;
    observedBody = body;
    if (!body || !statusBanner) return;
    if (statusBanner.parentNode !== body) {
      body.append(statusBanner);
      remember(reason, 'restore-banner', statusBanner);
    }
    if (!nativeInertSupported) return;
    if (nativeInert.get.call(statusBanner)) nativeInert.set.call(statusBanner, false);
    for (const child of Array.from(body.children)) {
      // Only the exact preload-owned banner is exempt. A duplicate ID grants no access.
      if (child === statusBanner) continue;
      let protectedRoot = child;
      try {
        if (!isHtml(child)) {
          // SVGElement.inert is an expando, not the native HTMLElement property.
          // Keep the original node/identity and layout; enforce inert through an
          // actual HTML ancestor without cloning or re-executing application nodes.
          const wrapper = document.createElement('div');
          wrapper.style.display = 'contents';
          // Diagnostic marker only; the captured native inert getter is authority.
          wrapper.setAttribute('data-inspectorpro-inert-wrapper', '');
          nativeInert.set.call(wrapper, true);
          body.insertBefore(wrapper, child);
          wrapper.append(child);
          protectedRoot = wrapper;
          remember(reason, 'wrap-non-html-root', child);
        }
        // Test the native property before writing to avoid observer feedback loops.
        if (!nativeInert.get.call(protectedRoot)) {
          nativeInert.set.call(protectedRoot, true);
          remember(reason, 'restore-native-inert', protectedRoot);
        }
      } catch (_error) {
        // Verification below stays false; never acknowledge a failed lock.
        remember(reason, 'repair-failed', child);
      }
    }
  }
  function acknowledgeIfVerified() {
    if (!acknowledged && snapshot().allProtectedRootsLocked) {
      acknowledged = true;
      ipcRenderer.send('desktop-spike:frozen');
    }
  }
  const observer = new MutationObserver(records => {
    if (!initialized) return;
    const body = document.body;
    const bodyChanged = body !== observedBody;
    const relevant = bodyChanged || records.some(record =>
      (record.type === 'childList' && record.target === body)
      || (record.type === 'attributes' && record.target.parentNode === body
        && (record.target === statusBanner
          ? nativeInertSupported && nativeInert.get.call(statusBanner) === true : !locked(record.target))));
    if (relevant) {
      freeze(bodyChanged ? 'body-replaced' : 'mutation');
      acknowledgeIfVerified();
    }
  });
  function initialize() {
    if (initialized) return;
    initialBefore = snapshot();
    const banner = document.createElement('aside');
    statusBanner = banner;
    banner.id = 'inspectorpro-desktop-spike-banner';
    banner.setAttribute('aria-label', 'Desktop prototype status');
    banner.style.cssText = 'position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#122537;color:#fff;border:1px solid #5e8ca8;border-radius:9px;padding:10px 16px;font:14px system-ui;box-shadow:0 3px 15px #0005;display:flex;align-items:center;gap:18px;max-width:90vw;';
    const text = document.createElement('span');
    text.textContent = 'InspectorPro desktop rendering preview · Editing and research browsing are disabled';
    const close = document.createElement('button');
    close.textContent = 'Close preview';
    close.style.cssText = 'font:inherit;color:#fff;background:#285b80;border:1px solid #7aabc8;border-radius:5px;padding:5px 10px;white-space:nowrap;cursor:pointer;';
    close.addEventListener('click', () => ipcRenderer.send('desktop-spike:close'));
    banner.append(text, close);
    initialized = true;
    // Observe above body so replacing it cannot bypass the lock or lose Close.
    observer.observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['inert'] });
    freeze('initial');
    initialAfter = snapshot();
    acknowledgeIfVerified();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true });
  else initialize();
}
