'use strict';

// Actual Electron process acceptance against either a controlled fixture or the
// isolated full InspectorPro backend. No browser automation port is exposed.
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const { runOwnedChild } = require('./owned-child-runner.cjs');
const { validateRenderingWindowReport } = require('./rendering-window-policy.cjs');
const { assertInputLockRechecks } = require('../src/rendering-evidence.cjs');
const { assertFixtureFocusProof } = require('./fixture-focus-proof.cjs');
const { randomUUID, createHash } = require('node:crypto');
const os = require('node:os');
const root = path.resolve(__dirname, '..');

async function main() {
  const args = process.argv.slice(2); let server;
  const expectedPage = args.length ? 'full-application' : 'inert-fixture';
  const output = path.resolve(process.env.INSPECTORPRO_DESKTOP_SMOKE_OUTPUT || path.join(root, '.runtime', 'electron-smoke-' + Date.now()));
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.mkdir(output); // Never reuse stale reports or screenshots.
  const logPath = path.join(output, 'electron.log');
  await fs.appendFile(logPath, '\n[smoke] Preparing Electron acceptance run\n');
  try {
    // Keep Chromium cache paths below legacy Windows path limits in deep checkouts.
    const stateRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'ip-desktop-ui-'));
    if (!args.length) {
      const identity = { schemaVersion: 1, product: 'InspectorPro', mode: 'rendering-spike', backendId: randomUUID(),
        storeId: randomUUID(), profileId: 'electron-fixture', researchBrowsing: false, interactive: false };
      server = http.createServer((request, response) => {
        if (request.url === '/api/desktop-shell/identity') { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(identity)); }
        else { response.setHeader('Content-Type', 'text/html'); response.end('<!doctype html><html><head><title>InspectorPro fixture</title></head><body><main data-inspectorpro-rendering-fixture="true"><h1>InspectorPro desktop acceptance fixture</h1><button id="edit">Edit</button><p>Input must be locked. This is a test page, not the product.</p></main><svg xmlns="http://www.w3.org/2000/svg" id="desktop-fixture-svg" width="24" height="24" viewBox="0 0 24 24" tabindex="0" role="img" aria-label="Non-HTML input-lock fixture"><circle cx="12" cy="12" r="9" fill="#286fba"/></svg><script>(() => { const svg = document.getElementById("desktop-fixture-svg"); svg.focus(); const baseline = { svgFocusable: document.activeElement === svg }; svg.blur(); svg.setAttribute("inert", ""); svg.focus(); baseline.svgAttributeStillFocusable = document.activeElement === svg; svg.blur(); svg.removeAttribute("inert"); window.__desktopFixtureFocusBaseline = Object.freeze(baseline); })();</script></body></html>'); }
      });
      await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
      const origin = 'http://127.0.0.1:' + server.address().port;
      const marker = path.join(output, 'identity.json');
      await fs.writeFile(marker, JSON.stringify({ ...identity, origin }));
      args.push('--backend', origin, '--identity-file', marker);
    }
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    env.ELECTRON_ENABLE_LOGGING = '1';
    env.electron_config_cache ||= path.join(root, '.runtime', 'electron-cache');
    process.env.electron_config_cache = env.electron_config_cache;
    const pinnedVersion = require('../package.json').devDependencies.electron;
    if (require('electron/package.json').version !== pinnedVersion) throw new Error('Installed Electron differs from the exact pin');
    const executable = require('electron');
    await fs.writeFile(path.join(output, 'launch.json'), JSON.stringify({ executable, electron: pinnedVersion,
      binarySha256: createHash('sha256').update(await fs.readFile(executable)).digest('hex'),
      expectedPage, diagnosticRevision: 'rendering-readiness-v1', sandboxRequested: true }, null, 2) + '\n');
    // Keep application URL arguments after Chromium's switch terminator.
    const child = await runOwnedChild({ executable,
      args: [path.join(root, 'src', 'main.cjs'), '--', ...args, '--state-root', stateRoot, '--smoke-output', output, '--expected-page', expectedPage],
      cwd: root, env, logPath, timeoutMs: 90000 });
    await fs.writeFile(path.join(output, 'process-result.json'), JSON.stringify(child, null, 2) + '\n');
    if (!child.ok) throw new Error(`Electron failed (${child.status}, exit=${child.code}, pid=${child.pid}, terminationConfirmed=${child.terminationConfirmed}, stdioClosed=${child.stdioClosed}): ${child.error || child.diagnostics}`);
    const report = JSON.parse(await fs.readFile(path.join(output, 'report.json'), 'utf8'));
    const checks = ['backendIdentity', 'inputLock', 'markup', 'isolation', 'firstPaint', 'wideCapture', 'narrowCapture', 'lifecycleClose'];
    if (report.schemaVersion !== 2 || report.diagnosticRevision !== 'rendering-readiness-v1'
        || report.status !== 'passed' || checks.some(check => report.checks?.[check] !== 'passed')
        || report.markup?.kind !== expectedPage || report.electron !== pinnedVersion
        || report.frozen !== true || report.nodeExposed !== false || report.capabilities?.interactive !== false
        || report.capabilities?.researchBrowsing !== false || report.researchViews !== 0 || report.webContentsCount !== 1) {
      throw new Error('Electron rendering assertions failed');
    }
    validateRenderingWindowReport(report);
    assertInputLockRechecks(report, expectedPage);
    if (expectedPage === 'inert-fixture') assertFixtureFocusProof(report.fixtureFocusProof);
    for (const name of ['desktop-wide.png', 'desktop-narrow.png']) {
      if ((await fs.stat(path.join(output, name))).size < 33) throw new Error('Rendering screenshot is missing or empty');
    }
    console.log(JSON.stringify({ passed: true, output, electron: report.electron, mode: report.capabilities.mode }));
  } catch (error) {
    await fs.appendFile(logPath, `\n[smoke] Failed: ${error.message}\n`).catch(logError => {
      error.message += `; cannot persist smoke failure: ${logError.message}`;
    });
    throw error;
  } finally {
    // runOwnedChild settles after close/drain, or after explicitly reporting
    // exhausted cleanup. Never release the fixture merely on a child's exit.
    if (server) await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        server.closeAllConnections();
        reject(new Error('Fixture server shutdown could not be confirmed'));
      }, 2000);
      server.close(error => { clearTimeout(timer); if (error && error.code !== 'ERR_SERVER_NOT_RUNNING') reject(error); else resolve(); });
      server.closeAllConnections();
    }).catch(async error => {
      await fs.appendFile(logPath, `\n[smoke] Cleanup failed: ${error.message}\n`).catch(() => {});
      throw error;
    });
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
