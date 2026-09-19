'use strict';
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { randomUUID } = require('node:crypto');
const { researchURL, addressOrSearch, researchHeaders, paneGeometry } = require('./research-policy.cjs');
const { createResearchProxy } = require('./research-proxy.cjs');
const { viewerResource } = require('./document-preview.cjs');
const { loadFavicon, isFaviconDataURL } = require('./browser-favicon.cjs');
const fail = code => Object.assign(new Error(code), { code });
const CHANNEL = 'desktop-research:command';
const SAFE = Object.freeze({ sandbox: true, contextIsolation: true, nodeIntegration: false,
  webSecurity: true, allowRunningInsecureContent: false, devTools: false, navigateOnDragDrop: false });

async function createResearchPane({ window, electron, isApplicationSender, onLayout = () => {}, onFocus = () => {},
  onState = () => {}, topInset = 0, initialSplit = null, homePage = null, createDetachedWindow = null, documentPreview = null, downloadDocument = null }) {
  const { WebContentsView, session, ipcMain, shell, dialog } = electron;
  const proxy = await createResearchProxy();
  const partition = 'ip-research-' + randomUUID();
  const browser = session.fromPartition(partition);
  const chromeSession = session.fromPartition(partition + '-controls');
  let disposed = false, visible = false, expanded = false, suspended = false, activeId = null, serial = 0;
  const suspensions = new Set();
  const tabs = new Map(), downloads = new Set();
  const requestDecisions = Object.create(null);
  const resourceTypes = new Set(['mainFrame', 'subFrame', 'stylesheet', 'script', 'image', 'font', 'object', 'xhr', 'ping', 'cspReport', 'media', 'webSocket', 'other']);
  let lastDownload = null, chrome = null, lastLayout = null, resizeListener = null;
  let host = window, detachedWindow = null;
  let splitFraction = initialSplit, splitter = null;
  const downloadHistory = [];
  try {
  const chromePath = path.resolve(__dirname, '../ui/research.html');
  const chromeURL = pathToFileURL(chromePath).href;
  const splitterURL = pathToFileURL(path.resolve(__dirname, '../ui/splitter.html')).href;
  const chromeFiles = new Set(['research.html', 'research.css', 'research.js', 'splitter.html', 'splitter.js', 'splitter.css', 'icons/picture-in-picture-2.svg', 'icons/download.svg'].map(name => pathToFileURL(path.resolve(__dirname, '../ui', name)).href));
  chromeFiles.add(pathToFileURL(path.resolve(__dirname,'../../static/assets/desktop-browser-globe.svg')).href);
  chromeSession.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !(chromeFiles.has(details.url)
    || (details.resourceType === 'image' && isFaviconDataURL(details.url))) }));
  for (const selected of [browser, chromeSession]) {
    selected.setPermissionCheckHandler(() => false);
    selected.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    selected.setDevicePermissionHandler(() => false);
    selected.setDisplayMediaRequestHandler((_request, callback) => callback({}));
  }
  chrome = new WebContentsView({ webPreferences: { ...SAFE, session: chromeSession, preload: path.join(__dirname, 'research-preload.cjs') } });
  chrome.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  for (const name of ['will-navigate', 'will-redirect', 'will-attach-webview']) chrome.webContents.on(name, event => event.preventDefault());
  chromeSession.on('will-download', event => event.preventDefault());
  window.contentView.addChildView(chrome); chrome.setVisible(false);
  if (initialSplit !== null) {
    splitter = new WebContentsView({ webPreferences: { ...SAFE, session: chromeSession, preload: path.join(__dirname, 'research-preload.cjs') } });
    splitter.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    splitter.webContents.on('will-navigate', event => event.preventDefault());
    window.contentView.addChildView(splitter); splitter.setVisible(false);
  }
  // The CONNECT proxy validates and pins the actual remote IPv4 address. There
  // is no DIRECT fallback, including Chromium's implicit localhost bypass.
  await browser.setProxy({ mode: 'fixed_servers', proxyRules: 'http=127.0.0.1:' + proxy.port + ';https=127.0.0.1:' + proxy.port,
    proxyBypassRules: '<-loopback>' });
  function requestAllowed(details) {
    if (!disposed && viewerResource(details.url)) return true;
    if (disposed || !['https:', 'wss:'].some(scheme => details.url.startsWith(scheme))) return false;
    try { researchURL(details.url.replace(/^wss:/, 'https:')); return true; } catch (_) { return false; }
  }
  browser.webRequest.onBeforeRequest((details, callback) => {
    const allowed = requestAllowed(details), kind = resourceTypes.has(details.resourceType) ? details.resourceType : 'other';
    const counts = requestDecisions[kind] ||= { allowed: 0, blocked: 0 };
    const field = allowed ? 'allowed' : 'blocked'; counts[field] = Math.min(Number.MAX_SAFE_INTEGER, counts[field] + 1);
    callback({ cancel: !allowed });
  });
  browser.webRequest.onBeforeSendHeaders((details, callback) => callback({ cancel: !requestAllowed(details), requestHeaders: researchHeaders(details.requestHeaders) }));
  browser.on('will-download', (event, item, contents) => {
    const tab = [...tabs.values()].find(candidate => candidate.view.webContents === contents);
    if (!tab || tab.id !== activeId || !visible || suspended || downloads.size >= 3) { event.preventDefault(); return; }
    try { for (const url of item.getURLChain()) researchURL(url); } catch (_) { event.preventDefault(); return; }
    trackDownload(item);
  });
  function trackDownload(item) {
    downloads.add(item);
    item.setSaveDialogOptions({ title: 'Save browser download', buttonLabel: 'Save' });
    const entry = { name: item.getFilename().slice(0, 200), state: 'in-progress', received: 0 };
    downloadHistory.push(entry); if (downloadHistory.length > 20) downloadHistory.shift(); lastDownload = entry;
    item.on('updated', () => { entry.state = item.isPaused() ? 'paused' : 'in-progress'; entry.received = item.getReceivedBytes(); lastDownload = entry; publish(); });
    item.once('done', (_event, state) => { downloads.delete(item); entry.state = state; lastDownload = entry; publish(); });
    publish();
  }
  function project() {
    return { visible, expanded, suspended, splitFraction, hostWidth: host.getContentBounds().width, detached: host !== window, canDetach: !!createDetachedWindow, activeId, maximumTabs: 8, download: lastDownload,
      tabs: [...tabs.values()].map(tab => ({ id: tab.id, url: tab.url, title: tab.title, favicon: tab.favicon || null, loading: tab.loading,
        kind: tab.kind || 'website', error: tab.error, canGoBack: tab.kind !== 'document' && tab.view.webContents.navigationHistory.canGoBack(), canGoForward: tab.kind !== 'document' && tab.view.webContents.navigationHistory.canGoForward() })) };
  }
  function layout() {
    if (disposed || window.isDestroyed()) return;
    const { width, height } = host.getContentBounds();
    const inset = host === window ? topInset : 0;
    const geometry = paneGeometry(width, Math.max(1, height - inset), { visible: visible && !suspended, expanded: expanded || host !== window, splitFraction });
    geometry.chrome.y += inset; geometry.page.y += inset;
    const projection = host === window ? { ...geometry, visible: visible && !suspended }
      : { ...paneGeometry(window.getContentBounds().width, window.getContentBounds().height), visible: false };
    const signature = JSON.stringify(projection);
    if (signature !== lastLayout) { lastLayout = signature; onLayout(projection); }
    chrome.setBounds(geometry.chrome); chrome.setVisible(visible && !suspended);
    if (splitter) {
      splitter.setBounds({ x: Math.max(0, geometry.chrome.x - 3), y: inset, width: 6, height: Math.max(1, height - inset) });
      splitter.setVisible(visible && !suspended && host === window && !geometry.obscuresApp);
    }
    for (const tab of tabs.values()) {
      tab.view.setBounds(geometry.page);
      tab.view.setVisible(visible && !suspended && tab.id === activeId && !!tab.url && !tab.error);
    }
  }
  function publish() { if (!disposed) { layout(); chrome.webContents.send('desktop-research:state', project()); splitter?.webContents.send('desktop-research:state', project()); onState(project()); } }
  function byId(id) { const tab = tabs.get(id); if (!tab) throw fail('research_tab_missing'); return tab; }
  function activate(id) { byId(id); activeId = id; visible = true; if (host !== window) { host.show(); host.focus(); } publish(); chrome.webContents.focus(); }
  function moveHost(next) {
    for (const view of [...tabs.values()].map(tab => tab.view).concat(chrome, splitter ? [splitter] : [])) { host.contentView.removeChildView(view); next.contentView.addChildView(view); }
    host = next; lastLayout = null; publish();
  }
  function dock() {
    if (host === window) return;
    const previous = detachedWindow; detachedWindow = null;
    moveHost(window); previous.removeListener('resize', layout); previous.destroy();
    window.show?.(); window.focus?.();
  }
  function detach() {
    if (!createDetachedWindow || disposed || suspended) throw fail('research_detach_unavailable');
    if (host !== window) { host.show(); host.focus(); return; }
    const next = createDetachedWindow(); detachedWindow = next;
    next.on('resize', layout);
    next.on('close', event => { if (!disposed && detachedWindow === next) { event.preventDefault(); dock(); } });
    moveHost(next); next.show(); next.focus();
  }
  function isCurrent(tab, navigation) {
    return !disposed && tabs.get(tab.id) === tab && tab.navigation === navigation;
  }
  function canInteract(tab) {
    return !disposed && !suspended && visible && tabs.get(tab.id) === tab && activeId === tab.id;
  }
  function clearFavicon(tab) {
    tab.faviconController?.abort();tab.faviconEpoch=(tab.faviconEpoch||0)+1;tab.favicon=null;
  }
  async function updateFavicon(tab, urls) {
    if(tab.kind==='document'||disposed)return;
    tab.faviconController?.abort();
    const controller=new AbortController(),epoch=(tab.faviconEpoch||0)+1;
    tab.faviconController=controller;tab.faviconEpoch=epoch;
    const timer=setTimeout(()=>controller.abort(),5000);
    try{
      const icon=await loadFavicon({session:browser,urls,pageURL:tab.url,signal:controller.signal});
      if(!disposed&&tabs.get(tab.id)===tab&&tab.faviconEpoch===epoch&&!controller.signal.aborted){tab.favicon=icon;publish();}
    }finally{clearTimeout(timer);}
  }
  async function loadDocument(tab) {
    const navigation = ++tab.navigation;
    tab.error = null; tab.loading = true; publish();
    try {
      if (!tab.previewURL) {
        const artifact = await documentPreview.prepare(tab.url);
        if (!isCurrent(tab, navigation)) { documentPreview.release(artifact.url); return; }
        tab.previewURL = artifact.url; tab.title = artifact.title;
      }
      await tab.view.webContents.loadURL(tab.previewURL);
    } catch (error) {
      if (isCurrent(tab, navigation)) tab.error = 'Document could not be previewed: ' + (error.code || 'load failed');
    } finally { if (isCurrent(tab, navigation)) { tab.loading = false; publish(); } }
    return project();
  }
  async function navigate(id, input) {
    const tab = byId(id);
    if (tab.kind === 'document') { if (input === tab.url) return loadDocument(tab); open(documentPreview?.accepts(input) ? input : addressOrSearch(input)); return project(); }
    if (documentPreview?.accepts(input)) { open(input); return project(); }
    const url = addressOrSearch(input);
    const navigation = ++tab.navigation;
    clearFavicon(tab);
    tab.url = url; tab.error = null; tab.loading = true; publish();
    try { await tab.view.webContents.loadURL(url); }
    catch (error) { if (isCurrent(tab, navigation) && error.code !== 'ERR_ABORTED') { tab.loading = false; tab.error = 'Page could not load. Retry or open in your browser.'; publish(); } }
    return project();
  }
  function open(raw = null, duplicate = false) {
    if (disposed) throw fail('research_closed');
    if (suspended) throw fail('research_suspended');
    const isDocument = raw !== null && documentPreview?.accepts(raw);
    const url = raw === null ? homePage : isDocument ? raw : researchURL(raw);
    const existing = raw !== null && !duplicate && url && [...tabs.values()].find(tab => tab.url === url);
    if (existing) { activate(existing.id); return existing.id; }
    if (tabs.size >= 8) throw fail('research_tab_limit');
    const view = new WebContentsView({ webPreferences: { ...SAFE, session: isDocument ? documentPreview.session : browser,
      plugins: true, disableDialogs: true, safeDialogs: true } });
    const id = 'research-' + (++serial);
    const tab = { id, view, kind: isDocument ? 'document' : 'website', url: null, title: 'New tab', loading: false, error: null, navigation: 0 };
    tabs.set(id, tab); host.contentView.addChildView(view);
    // Keep the trusted toolbar above site-controlled views.
    host.contentView.addChildView(chrome);
    if (splitter) host.contentView.addChildView(splitter);
    view.webContents.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
    view.webContents.setWindowOpenHandler(({ url: requested }) => {
      if (canInteract(tab) && !tab.error && host.isFocused() && view.webContents.isFocused()) {
        try { open(researchURL(requested)); } catch (_) {}
      }
      return { action: 'deny' };
    });
    view.webContents.on('will-attach-webview', event => event.preventDefault());
    for (const name of ['will-navigate', 'will-redirect', 'will-frame-navigate']) view.webContents.on(name, (event, details) => {
      const target = typeof details === 'string' ? details : details?.url || event.url;
      if (viewerResource(target)) return;
      if (isDocument) { if (target !== tab.previewURL && !documentPreview.viewerResource?.(target)) event.preventDefault(); return; }
      try { researchURL(target); }
      catch (_) { event.preventDefault(); }
    });
    view.webContents.on('focus', onFocus);
    view.webContents.on('did-start-navigation',(event,_url,inPlace,main)=>{
      if((event.isMainFrame??main)&&!(event.isInPlace??inPlace)){clearFavicon(tab);publish();}
    });
    view.webContents.on('page-favicon-updated',(_event,icons)=>{void updateFavicon(tab,icons);});
    view.webContents.on('before-input-event', (event, input) => {
      if (input.type !== 'keyDown' || !(input.control || input.meta)) return;
      if (input.key.toLowerCase() === 'l') {
        event.preventDefault(); chrome.webContents.focus(); chrome.webContents.send('desktop-research:focus-address');
      }
      if (input.key.toLowerCase() === 't') { event.preventDefault(); try { open(); } catch (_) {} }
      if (input.key.toLowerCase() === 'w') { event.preventDefault(); if (canInteract(tab)) close(tab.id); }
    });
    view.webContents.on('page-title-updated', (event, title) => { event.preventDefault(); if (!isDocument) tab.title = String(title).slice(0, 160) || 'Untitled'; publish(); });
    view.webContents.on('did-start-loading', () => { tab.loading = true; publish(); });
    view.webContents.on('did-stop-loading', () => { tab.loading = false; publish(); });
    view.webContents.on('did-navigate', (_event, destination) => { if (!isDocument) tab.url = destination; tab.error = null; publish(); });
    view.webContents.on('did-navigate-in-page', (_event, destination, main) => { if (main && !isDocument) { tab.url = destination; publish(); } });
    view.webContents.on('render-process-gone', () => { tab.navigation++; tab.loading = false; tab.error = 'This tab stopped. Reload to recover it.'; publish(); });
    activate(id);
    if (isDocument) {
      tab.url = url; tab.title = 'Document'; tab.loading = true; publish();
      void loadDocument(tab);
    } else if (url) void navigate(id, url);
    return id;
  }
  function close(id) {
    const tab = byId(id); tab.navigation++; clearFavicon(tab); tabs.delete(id); host.contentView.removeChildView(tab.view); tab.view.webContents.close({ waitForBeforeUnload: false });
    if (tab.previewURL) documentPreview.release(tab.previewURL);
    if (activeId === id) activeId = [...tabs.keys()].at(-1) || null;
    if (!tabs.size) { visible = false; if (host !== window && !disposed) dock(); }
    publish();
    if (!visible) window.webContents.focus();
  }
  async function command(event, request) {
    const fromChrome = event.sender === chrome.webContents && event.senderFrame === chrome.webContents.mainFrame && event.senderFrame.url === chromeURL;
    const fromSplitter = splitter && event.sender === splitter.webContents && event.senderFrame === splitter.webContents.mainFrame && event.senderFrame.url === splitterURL;
    if (disposed || (!fromChrome && !(fromSplitter && ['state', 'resize'].includes(request?.action)))) throw fail('research_sender_rejected');
    if (!request || Object.keys(request).some(key => !['action', 'tabId', 'value'].includes(key)) || typeof request.action !== 'string') throw fail('research_command_invalid');
    if (request.action !== 'state' && request.action !== 'cancel-downloads' && (!visible || suspended)) throw fail('research_not_interactive');
    const id = request.tabId;
    switch (request.action) {
      case 'state': return project();
      case 'new': open(); break;
      case 'activate': activate(id); break;
      case 'close': close(id); break;
      case 'navigate': return navigate(id, request.value);
      case 'back': { const tab = byId(id); if (tab.view.webContents.navigationHistory.canGoBack()) { tab.navigation++; tab.view.webContents.navigationHistory.goBack(); } break; }
      case 'forward': { const tab = byId(id); if (tab.view.webContents.navigationHistory.canGoForward()) { tab.navigation++; tab.view.webContents.navigationHistory.goForward(); } break; }
      case 'reload': { const tab = byId(id); if (tab.url) return navigate(id, tab.url); break; }
      case 'stop': { const tab = byId(id); tab.navigation++; tab.view.webContents.stop(); tab.loading = false; break; }
      case 'hide': visible = false; if (host !== window) host.hide(); publish(); window.webContents.focus(); break;
      case 'expand': expanded = !expanded; break;
      case 'resize': {
        if (host !== window || !Number.isFinite(request.value) || request.value < 0.2 || request.value > 0.8) throw fail('research_split_invalid');
        splitFraction = request.value; expanded = false; break;
      }
      case 'downloads': await dialog.showMessageBox(host, { type: 'info', title: 'Downloads', message: 'Browser downloads',
        detail: downloadHistory.map(item => item.name + ': ' + item.state).join('\n') || 'No downloads in this session.', buttons: ['OK'] }); break;
      case 'zoom-in': { const contents = byId(id).view.webContents; contents.setZoomFactor(Math.min(3, contents.getZoomFactor() + 0.1)); break; }
      case 'zoom-out': { const contents = byId(id).view.webContents; contents.setZoomFactor(Math.max(0.5, contents.getZoomFactor() - 0.1)); break; }
      case 'zoom-reset': byId(id).view.webContents.setZoomFactor(1); break;
      case 'detach': if (host === window) detach(); else dock(); break;
      case 'download': {
        const tab = byId(id);
        if (tab.kind === 'document' && downloadDocument) downloadDocument(tab.url);
        else if (tab.url) tab.view.webContents.downloadURL(researchURL(tab.url));
        break;
      }
      case 'cancel-downloads': for (const item of downloads) item.cancel(); break;
      case 'external': {
        const tab = byId(id), url = researchURL(tab.url), navigation = tab.navigation;
        const answer = await dialog.showMessageBox(host, { type: 'question', message: 'Open this page in your default browser?', detail: url,
          buttons: ['Cancel', 'Open browser'], defaultId: 0, cancelId: 0 });
        if (isCurrent(tab, navigation) && canInteract(tab) && tab.url === url && answer.response === 1) await shell.openExternal(url);
        break;
      }
      default: throw fail('research_command_invalid');
    }
    publish(); return project();
  }
  ipcMain.handle(CHANNEL, command);
  ipcMain.handle('desktop-research:open', (event, value) => {
    if (!isApplicationSender(event) || typeof value !== 'string') throw fail('research_sender_rejected');
    return { tabId: open(value) };
  });
  chrome.webContents.on('focus', onFocus);
  window.on('resize', layout);
  resizeListener = layout;
  await chrome.webContents.loadURL(chromeURL); if (splitter) await splitter.webContents.loadURL(splitterURL); publish();
  return { open, detach, dock, show() { if (disposed) throw fail('research_closed'); if (suspended) throw fail('research_suspended'); if (!tabs.size) open(); else { visible = true; if (host !== window) host.show(); publish(); } },
    hide() { visible = false; if (host !== window) host.hide(); publish(); window.webContents.focus(); },
    suspend(value, reason = 'host') { if (value === true) suspensions.add(reason); else suspensions.delete(reason); suspended = suspensions.size > 0; publish(); },
    reloadFocused() {
      if (!visible || suspended || !activeId || !(chrome.webContents.isFocused() || byId(activeId).view.webContents.isFocused())) return false;
      const tab = byId(activeId); if (tab.url) void navigate(activeId, tab.url);
      return true;
    },
    snapshot: project, layout, trackDownload, refresh() { lastLayout = null; publish(); }, chrome, splitter, getHost: () => host, getViews: () => [...tabs.values()].map(tab => tab.view),
    evidence: () => ({ partition, proxy: proxy.evidence(), requestDecisions: structuredClone(requestDecisions), documents: documentPreview?.evidence?.() || null, ...project() }),
    async dispose() {
      if (disposed) return;
      disposed = true;
      for (const item of downloads) item.cancel();
      for (const id of [...tabs.keys()]) close(id);
      window.removeListener('resize', layout);
      ipcMain.removeHandler(CHANNEL); ipcMain.removeHandler('desktop-research:open');
      host.contentView.removeChildView(chrome); chrome.webContents.close({ waitForBeforeUnload: false });
      if (splitter) { host.contentView.removeChildView(splitter); splitter.webContents.close({ waitForBeforeUnload: false }); }
      if (detachedWindow) { detachedWindow.removeListener('resize', layout); detachedWindow.destroy(); }
      try { await browser.closeAllConnections(); await browser.clearStorageData(); }
      finally { await proxy.close(); }
    } };
  } catch (error) {
    disposed = true;
    if (resizeListener) window.removeListener('resize', resizeListener);
    ipcMain.removeHandler(CHANNEL); ipcMain.removeHandler('desktop-research:open');
    for (const view of [chrome, splitter, ...[...tabs.values()].map(tab => tab.view)].filter(Boolean)) {
      host.contentView.removeChildView(view);
      if (!view.webContents.isDestroyed()) view.webContents.close({ waitForBeforeUnload: false });
    }
    await browser.closeAllConnections().catch(() => {});
    await proxy.close().catch(() => {});
    throw error;
  }
}
module.exports = { createResearchPane };
