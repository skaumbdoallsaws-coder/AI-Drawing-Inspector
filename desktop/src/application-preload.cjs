'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// Native caption buttons share the existing app header. Keep interactive header
// content outside drag regions and reserve the OS-reported caption-button area.
document.addEventListener('DOMContentLoaded', () => {
  const style = document.createElement('style');
  style.id = 'inspectorpro-native-titlebar';
  style.textContent = `
    .app-container > .toolbar {
      -webkit-app-region: drag;
      user-select: none;
      padding-left: max(12px, env(titlebar-area-x, 0px));
      padding-right: calc(12px + 100% - env(titlebar-area-x, 0px) - env(titlebar-area-width, 100%));
    }
    .app-container > .toolbar .window-controls { display: none; }
    .app-container > .toolbar button,
    .app-container > .toolbar input,
    .app-container > .toolbar select,
    .app-container > .toolbar a,
    .app-container > .toolbar nav,
    .app-container > .toolbar [role="button"],
    .app-container > .toolbar .toolbar-icons,
    .app-container > .toolbar .toolbar-search-wrap,
    .app-container > .toolbar .toolbar-controls,
    .app-container > .toolbar .toolbar-right > * {
      -webkit-app-region: no-drag;
    }
    .app-container > .toolbar input { user-select: text; }
  `;
  document.head.appendChild(style);
  const agent = document.getElementById('rightRailAgent');
  if (agent) {
    const button = document.createElement('button');
    button.id = 'rightRailBrowser'; button.className = 'right-rail-icon'; button.title = 'Browser';
    button.setAttribute('aria-label', 'Toggle browser'); button.setAttribute('aria-expanded', 'false');
    button.style.cssText = 'padding:0;background:transparent;color:inherit;font:inherit;';
    const icon = document.createElement('span'); icon.setAttribute('aria-hidden', 'true');
    icon.style.cssText = 'width:22px;height:22px;display:block;background:currentColor;mask:url(/static/assets/desktop-browser-globe.svg) center/contain no-repeat;';
    const tooltip = document.createElement('span'); tooltip.className = 'right-rail-tooltip'; tooltip.textContent = 'Browser';
    button.append(icon, tooltip); agent.after(button);
    button.addEventListener('click', () => browserCommand({ action: 'toggle' }));
    void ipcRenderer.invoke('ip-browser-command', { action: 'state' }).then(browserState);
  }
}, { once: true });
function browserState(value) {
  const button = document.getElementById('rightRailBrowser');
  button?.classList.toggle('active', value?.visible === true);
  button?.setAttribute('aria-expanded', String(value?.visible === true));
}
function browserCommand(request) {
  return ipcRenderer.invoke('ip-browser-command', request).then(browserState).catch(error => {
    const button = document.getElementById('rightRailBrowser');
    if (button) button.title = 'Browser unavailable: ' + error.message;
  });
}
ipcRenderer.on('ip-browser-state', (_event, value) => browserState(value));
ipcRenderer.on('ip-browser-release-pointer', () => document.exitPointerLock?.());
let browserStyle = null;
ipcRenderer.on('ip-browser-layout', (_event, value) => {
  if (!value || !Number.isFinite(value.reservedCssPixels) || value.reservedCssPixels < 0) return;
  if (!browserStyle) { browserStyle = document.createElement('style'); document.head.appendChild(browserStyle); }
  browserStyle.textContent = value.visible && !value.obscuresApp
    ? '.app-container > :not(.toolbar){width:calc(100% - ' + value.reservedCssPixels + 'px)!important;min-width:0!important;}' : '';
  document.exitPointerLock?.(); window.dispatchEvent(new Event('resize'));
});
document.addEventListener('click', event => {
  const link = event.target.closest?.('a[href]');
  if (!event.isTrusted || !link || link.hasAttribute('download')) return;
  const url = new URL(link.href, location.href);
  if (!['https:', 'http:'].includes(url.protocol) || (url.origin === location.origin && url.pathname === '/')) return;
  event.preventDefault(); event.stopImmediatePropagation();
  void browserCommand({ action: 'open', url: url.href });
}, true);
let lastOverlay = false;
new MutationObserver(() => {
  const visible = [...document.querySelectorAll('dialog[open],[aria-modal="true"],.modal-overlay.active')]
    .some(node => node.getBoundingClientRect().width > 0 && node.getBoundingClientRect().height > 0);
  if (visible !== lastOverlay) { lastOverlay = visible; ipcRenderer.send('ip-browser-overlay', visible); }
}).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['open', 'aria-modal', 'class', 'hidden'] });
let observe = null;
contextBridge.exposeInMainWorld('InspectorProNativeApplication', Object.freeze({
  registerLifecycleObserver(callback) {
    if (typeof callback !== 'function' || observe) throw new Error('Lifecycle observer is already registered or invalid');
    observe = callback;
  },
}));
ipcRenderer.on('ip-application-observe', (_event, id) => {
  let result;
  try { result = observe ? observe() : null; } catch (_) { result = null; }
  ipcRenderer.send('ip-application-observed', id, result);
});
let overlay = null;
let previousInert = null;
ipcRenderer.on('ip-application-freeze', (_event, frozen) => {
  if (!frozen) {
    overlay?.remove(); overlay = null;
    if (previousInert !== null) document.documentElement.inert = previousInert;
    previousInert = null; return;
  }
  // No application roots are replaced or renamed. Freeze is temporary and
  // limited to a backend transition, never the normal editing state.
  if (previousInert === null) previousInert = document.documentElement.inert;
  document.documentElement.inert = true;
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.textContent = 'InspectorPro backend is restarting. Your draft remains in this window.';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:#182128e8;color:white;display:grid;place-items:center;font:16px system-ui;pointer-events:all';
    document.documentElement.appendChild(overlay);
  }
});
