'use strict';

function installApplicationLinks({ window, network, external, reload, openBrowser = null, isDocument = () => false }) {
  function destination(url) {
    let parsed;
    try { parsed = new URL(url); } catch (_) { return 'deny'; }
    if (parsed.username || parsed.password) return 'deny';
    if (parsed.protocol === 'blob:' && network.local(parsed.pathname)) return 'download';
    if (!['http:', 'https:'].includes(parsed.protocol)) return 'deny';
    if (!network.local(url)) return openBrowser ? 'browser' : 'external';
    if (openBrowser && isDocument(url)) return 'browser';
    return parsed.pathname === '/' ? 'application' : 'download';
  }
  function follow(url) {
    switch (destination(url)) {
      case 'download': window.webContents.downloadURL(url); break;
      case 'external': void external(url); break;
      case 'browser': void openBrowser(url); break;
      case 'application': void reload(url); break;
    }
  }
  window.webContents.setWindowOpenHandler(({ url }) => {
    follow(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    // Published manuals use location.assign; keep the editor and its unsaved
    // state alive while the ordinary authenticated download handles the file.
    event.preventDefault();
    follow(url);
  });
  return { destination };
}

module.exports = { installApplicationLinks };
