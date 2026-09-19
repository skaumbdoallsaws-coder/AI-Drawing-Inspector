'use strict';
// Test-only HTTPS responses remain behind the production session policy. No
// private-host exception, credential injection or TLS bypass is installed.
const { app, BrowserWindow } = require('electron');
const electron = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { createResearchPane } = require('../src/research-pane.cjs');
const output = process.argv.at(-1);
if (!path.isAbsolute(output)) throw new Error('Absolute fresh evidence directory required');
fsSync.mkdirSync(output, { recursive: false });
app.setPath('userData', path.join(output, 'profile'));
const report = { schemaVersion: 1, status: 'running', scope: 'isolated-research-security',
  productionNetworkPolicy: true, realRemoteSiteCompatibility: false, checks: {}, stages: [], unexpectedProtocolRequests: [] };
report.runtime = { pid: process.pid, electron: process.versions.electron, chrome: process.versions.chrome };
report.sources = Object.fromEntries(['tools/research-security-check.cjs', 'src/research-pane.cjs', 'src/research-policy.cjs', 'src/research-proxy.cjs', 'src/research-preload.cjs']
  .map(name => [name, createHash('sha256').update(fsSync.readFileSync(path.join(__dirname, '..', name))).digest('hex')]));
let window, pane, browser, canary, deadline;
const canarySockets = new Set();
const save = () => fs.writeFile(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(read, message, milliseconds = 10000) {
  const end = Date.now() + milliseconds;
  while (Date.now() < end) { const value = await read(); if (value) return value; await delay(40); }
  throw new Error(message);
}
async function stage(name, work) {
  report.stage = name; const item = { name, startedAt: new Date().toISOString() }; report.stages.push(item); await save();
  await work(); item.passed = true; await save();
}
const fixtureOrigin = 'https://research-fixture.inspectorpro.org';
const script = body => '<!doctype html><meta charset="utf-8"><title>Controlled research fixture</title><script>' + body + '</script>';
const fetchProbe = `async url=>{try{await fetch(url,{mode:'no-cors'});return {url,blocked:false};}catch(error){return {url,blocked:true,error:error.name};}}`;
async function run() {
  let tcpConnections = 0, httpRequests = 0;
  canary = http.createServer((_request, response) => { httpRequests++; response.writeHead(403); response.end(); });
  canary.on('connection', socket => { tcpConnections++; canarySockets.add(socket); socket.on('close', () => canarySockets.delete(socket)); });
  canary.on('clientError', (_error, socket) => socket.destroy());
  await new Promise((resolve, reject) => { canary.once('error', reject); canary.listen(0, '127.0.0.1', resolve); });
  report.canaryPort = canary.address().port;
  const port = report.canaryPort;
  const targets = ['http://127.0.0.1:', 'https://127.0.0.1:', 'https://localhost:', 'https://2130706433:', 'https://[::1]:']
    .map(origin => origin + port + '/api/profiles');
  const privateURL = targets[1];
  const publicPages = new Set(['/start', '/other', '/popup']);
  const served = Object.create(null);
  report.fixture = { origin: fixtureOrigin, transport: 'test-only in-memory HTTPS handler', served };
  window = new BrowserWindow({ width: 1200, height: 700, show: false, title: 'InspectorPro Research Security Check',
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  await window.loadURL('data:text/html,' + encodeURIComponent('<title>InspectorPro Research Security Check</title><body style="background:#edf2f5;color:#233a45;font:18px system-ui;padding:30px">Isolated browser security check</body>'));
  pane = await createResearchPane({ window, electron, isApplicationSender: () => false });
  const id = pane.open(), contents = pane.getViews()[0].webContents;
  browser = contents.session;
  await browser.protocol.handle('https', request => {
    const url = new URL(request.url);
    if (url.origin !== fixtureOrigin) { report.unexpectedProtocolRequests.push({ origin: url.origin, pathname: url.pathname }); return new Response('Denied', { status: 403 }); }
    served[url.pathname] = (served[url.pathname] || 0) + 1;
    if (publicPages.has(url.pathname)) return new Response(script('window.fixtureReady=true;'), { headers: { 'content-type': 'text/html' } });
    if (url.pathname === '/frame') return new Response(script(`(async()=>{const results=await Promise.all(${JSON.stringify(targets)}.map(${fetchProbe}));parent.postMessage({fixture:'frame',results},${JSON.stringify(fixtureOrigin)});})()`), { headers: { 'content-type': 'text/html' } });
    if (url.pathname === '/worker.js') return new Response(`onmessage=async()=>{postMessage({fixture:'worker',results:await Promise.all(${JSON.stringify(targets)}.map(${fetchProbe}))});};`, { headers: { 'content-type': 'text/javascript' } });
    if (url.pathname === '/shared-worker.js') return new Response(`onconnect=event=>{const port=event.ports[0];port.onmessage=async()=>port.postMessage({fixture:'shared-worker',results:await Promise.all(${JSON.stringify(targets)}.map(${fetchProbe}))});port.start();};`, { headers: { 'content-type': 'text/javascript' } });
    if (url.pathname === '/service-worker.js') return new Response(`self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));self.addEventListener('message',event=>event.waitUntil((async()=>{event.ports[0].postMessage({fixture:'service-worker',results:await Promise.all(${JSON.stringify(targets)}.map(${fetchProbe}))});})()));`, { headers: { 'content-type': 'text/javascript' } });
    if (url.pathname === '/redirect') return new Response(null, { status: 302, headers: { location: privateURL } });
    if (url.pathname === '/download') return new Response('controlled inert text fixture', { headers: { 'content-type': 'application/octet-stream', 'content-disposition': 'attachment; filename="fixture.txt"' } });
    return new Response('Missing fixture', { status: 404 });
  });
  const command = request => pane.chrome.webContents.executeJavaScript(`research.command(${JSON.stringify(request)})`);
  await command({ action: 'navigate', tabId: id, value: fixtureOrigin + '/start' });
  window.show(); window.focus(); contents.focus();
  await until(() => window.isVisible() && window.isFocused() && contents.isFocused(), 'Research fixture did not receive native focus');
  try {
    await stage('renderer-isolation', async () => {
      const exposed = await contents.executeJavaScript('({process:typeof process,require:typeof require,application:typeof InspectorProDesktop,research:typeof research,ready:fixtureReady})');
      assert.deepEqual(exposed, { process: 'undefined', require: 'undefined', application: 'undefined', research: 'undefined', ready: true });
      const preferences = contents.getLastWebPreferences();
      assert.equal(preferences.sandbox, true); assert.equal(preferences.contextIsolation, true); assert.equal(preferences.webSecurity, true); assert.equal(preferences.nodeIntegration, false); assert.ok(!preferences.preload);
      report.checks.rendererIsolation = { exposed, sandbox: true, noPreload: true };
    });
    await stage('frames-workers-and-fetch', async () => {
      const result = await contents.executeJavaScript(`(async()=>{
        const top=await Promise.all(${JSON.stringify(targets)}.map(${fetchProbe}));
        const frame=new Promise(resolve=>{const listener=event=>{if(event.origin===${JSON.stringify(fixtureOrigin)}&&event.data?.fixture==='frame'){removeEventListener('message',listener);resolve(event.data);}};addEventListener('message',listener);const f=document.createElement('iframe');f.src='/frame';document.body.append(f);});
        const worker=new Promise((resolve,reject)=>{const w=new Worker('/worker.js');w.onmessage=event=>{w.terminate();resolve(event.data);};w.onerror=error=>{w.terminate();reject(new Error(error.message));};w.postMessage('run');});
        return {top,frame:await frame,worker:await worker};})()`);
      assert.equal(result.frame.fixture, 'frame'); assert.equal(result.worker.fixture, 'worker');
      for (const items of [result.top, result.frame.results, result.worker.results]) { assert.equal(items.length, targets.length); assert.ok(items.every(item => item.blocked)); }
      assert.equal(served['/frame'], 1); assert.equal(served['/worker.js'], 1);
      report.checks.framesWorkersFetch = result;
    });
    await stage('shared-and-service-workers', async () => {
      const result = await contents.executeJavaScript(`(async()=>{
        const shared=await new Promise((resolve,reject)=>{const worker=new SharedWorker('/shared-worker.js');worker.onerror=event=>reject(new Error(event.message||'Shared worker failed'));worker.port.onmessage=event=>{worker.port.close();resolve(event.data);};worker.port.start();worker.port.postMessage('run');});
        const registration=await navigator.serviceWorker.register('/service-worker.js');
        try {
          await navigator.serviceWorker.ready;
          const service=await new Promise(resolve=>{const channel=new MessageChannel();channel.port1.onmessage=event=>{channel.port1.close();resolve(event.data);};registration.active.postMessage('run',[channel.port2]);});
          return {shared,service};
        } finally {await registration.unregister();}
      })()`);
      assert.equal(result.shared.fixture, 'shared-worker'); assert.equal(result.service.fixture, 'service-worker');
      for (const item of [result.shared, result.service]) { assert.equal(item.results.length, targets.length); assert.ok(item.results.every(value => value.blocked)); }
      assert.equal(served['/shared-worker.js'], 1); assert.equal(served['/service-worker.js'], 1);
      report.checks.sharedServiceWorkers = result;
    });
    await stage('websocket-images-forms-and-navigation', async () => {
      const ws = await contents.executeJavaScript(`new Promise(resolve=>{const w=new WebSocket(${JSON.stringify(privateURL.replace('https:', 'wss:'))});w.onopen=()=>{w.close();resolve({blocked:false});};w.onerror=()=>resolve({blocked:true});})`);
      assert.equal(ws.blocked, true);
      const subresources = await contents.executeJavaScript(`(async()=>{
        const image=new Promise(resolve=>{const i=new Image();i.onload=()=>resolve({blocked:false});i.onerror=()=>resolve({blocked:true});i.src=${JSON.stringify(privateURL)};document.body.append(i);});
        const target=document.createElement('iframe');target.name='post-target';document.body.append(target);
        const form=document.createElement('form');form.action=${JSON.stringify(privateURL)};form.method='POST';form.target='post-target';document.body.append(form);form.submit();
        const privateFrame=document.createElement('iframe');privateFrame.src=${JSON.stringify(privateURL)};document.body.append(privateFrame);
        return {image:await image,formSubmitted:true,privateFrameCreated:true};})()`);
      assert.equal(subresources.image.blocked, true);
      const original = contents.getURL();
      await contents.executeJavaScript(`location.href=${JSON.stringify(privateURL)};void 0`);
      await delay(250); assert.equal(contents.getURL(), original);
      const redirectId = pane.open(fixtureOrigin + '/redirect');
      await until(() => pane.snapshot().tabs.find(tab => tab.id === redirectId)?.error, 'Private redirect did not fail closed');
      await command({ action: 'close', tabId: redirectId });
      await command({ action: 'activate', tabId: id });
      report.checks.subresources = { websocket: ws, ...subresources, mainNavigationBlocked: true, redirectBlocked: true };
    });
    await stage('hidden-background-and-suspended-popups', async () => {
      const popup = () => contents.executeJavaScript(`window.open(${JSON.stringify(fixtureOrigin + '/popup')},'_blank');void 0`, true);
      const observations = [];
      pane.hide(); await popup(); await delay(100); assert.equal(pane.snapshot().visible, false); assert.equal(pane.snapshot().tabs.length, 1); observations.push('hidden');
      pane.show(); pane.suspend(true); await popup(); await delay(100); assert.equal(pane.snapshot().tabs.length, 1); assert.equal(pane.snapshot().suspended, true); observations.push('suspended'); pane.suspend(false);
      const otherId = pane.open(fixtureOrigin + '/other'); await until(() => !pane.snapshot().tabs.find(tab => tab.id === otherId).loading, 'Second tab did not load');
      await popup(); await delay(100); assert.equal(pane.snapshot().tabs.length, 2); assert.equal(pane.snapshot().activeId, otherId); observations.push('background');
      await command({ action: 'close', tabId: otherId }); await command({ action: 'activate', tabId: id });
      contents.focus(); await until(() => contents.isFocused(), 'Active research did not receive focus');
      await popup(); await until(() => pane.snapshot().tabs.length === 2, 'Focused public popup was not routed to a tab');
      const popupId = pane.snapshot().activeId; assert.notEqual(popupId, id); assert.equal(BrowserWindow.getAllWindows().length, 1);
      await command({ action: 'close', tabId: popupId }); await command({ action: 'activate', tabId: id });
      report.checks.popupOwnership = { refused: observations, focusedPopupCreatedIsolatedTab: true, noNativePopupWindow: true };
    });
    await stage('download-cancellation', async () => {
      const downloaded = new Promise(resolve => browser.once('will-download', (_event, item) => { item.once('done', (_event, state) => resolve({ state, filename: item.getFilename() })); item.cancel(); }));
      contents.focus();
      await contents.executeJavaScript("const link=document.createElement('a');link.href='/download';link.download='fixture.txt';document.body.append(link);link.click();void 0", true);
      const result = await downloaded; assert.equal(result.state, 'cancelled'); assert.equal(result.filename, 'fixture.txt');
      report.checks.downloadCancellation = { ...result, nativeFilePickerExercised: false };
    });
    await stage('network-receipts', async () => {
      await delay(300);
      report.network = { tcpConnections, httpRequests, policy: pane.evidence().requestDecisions };
      assert.equal(tcpConnections, 0); assert.equal(httpRequests, 0); assert.deepEqual(report.unexpectedProtocolRequests, []);
      assert.ok(report.network.policy.xhr?.blocked > 0); assert.ok(report.network.policy.webSocket?.blocked > 0); assert.ok(report.network.policy.image?.blocked > 0);
      report.checks.networkNoBypass = true;
    });
    report.status = 'passed';
    report.stage = 'complete';
  } finally {
    report.beforeCleanup = pane.evidence();
    for (const socket of canarySockets) socket.destroy();
  }
}
app.whenReady().then(async () => {
  try {
    await Promise.race([run(), new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('Research security check exceeded 120 seconds')), 120000); })]);
  } catch (error) { report.status = 'failed'; report.error = { message: error.message, stack: error.stack }; }
  finally {
    clearTimeout(deadline);
    const cleanupErrors = [];
    for (const socket of canarySockets) socket.destroy();
    for (const work of [async () => { if (browser) browser.protocol.unhandle('https'); }, async () => { if (pane) await pane.dispose(); },
      async () => { if (window && !window.isDestroyed()) window.destroy(); }, async () => { if (canary?.listening) await new Promise((resolve, reject) => canary.close(error => error ? reject(error) : resolve())); }]) {
      try { await work(); } catch (error) { cleanupErrors.push(error.message); }
    }
    report.cleanup = { errors: cleanupErrors, nativeWindows: BrowserWindow.getAllWindows().length, canaryListening: canary?.listening || false, proxy: pane?.evidence().proxy };
    if (cleanupErrors.length || report.cleanup.nativeWindows || report.cleanup.canaryListening || report.cleanup.proxy?.activeSockets) report.status = 'failed';
    await save(); app.exit(report.status === 'passed' ? 0 : 1);
  }
}).catch(error => { console.error(error); app.exit(1); });
