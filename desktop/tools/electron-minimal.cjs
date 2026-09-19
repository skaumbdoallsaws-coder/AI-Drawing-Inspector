'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createHash } = require('node:crypto');
const { runOwnedChild } = require('./owned-child-runner.cjs');
const root = path.resolve(__dirname, '..');

async function main() {
  const args = process.argv.slice(2);
  const options = { label: 'unspecified', 'capture-mode': 'after-paint',
    output: path.join(root, '.runtime', 'electron-minimal-' + Date.now()) };
  const seen = new Set();
  for (let index = 0; index < args.length; index += 2) {
    if (!['--label', '--output', '--capture-mode'].includes(args[index]) || !args[index + 1] || seen.has(args[index])) {
      throw new Error('Usage: node tools/electron-minimal.cjs [--label NAME] [--output PATH] [--capture-mode after-paint|immediate]');
    }
    seen.add(args[index]);
    options[args[index].slice(2)] = args[index + 1];
  }
  if (!['after-paint', 'immediate'].includes(options['capture-mode'])) throw new Error('Unsupported capture mode');
  const output = path.resolve(options.output);
  // Refuse to mix results from two environments or leave a stale passing report.
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.mkdir(output);
  let result;
  try {
    const stateRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'ip-minimal-'));
    const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
    env.ELECTRON_ENABLE_LOGGING = '1';
    env.electron_config_cache ||= path.join(root, '.runtime', 'electron-cache');
    process.env.electron_config_cache = env.electron_config_cache;
    env.INSPECTORPRO_MINIMAL_OUTPUT = output;
    env.INSPECTORPRO_MINIMAL_STATE = stateRoot;
    env.INSPECTORPRO_MINIMAL_CAPTURE_MODE = options['capture-mode'];
    const pinnedVersion = require('../package.json').devDependencies.electron;
    const installedVersion = require('electron/package.json').version;
    if (installedVersion !== pinnedVersion) throw new Error('Installed Electron does not match the project pin');
    const executable = require('electron');
    const binarySha256 = createHash('sha256').update(await fs.readFile(executable)).digest('hex');
    const receipt = { diagnosticRevision: 'capture-readiness-v1', captureMode: options['capture-mode'],
      callerSuppliedLabel: options.label, startedAt: new Date().toISOString(), executable,
      binarySha256, electronPackageVersion: installedVersion,
      launcherNode: process.versions.node, launcherExecutable: process.execPath,
      platform: process.platform, architecture: process.arch, osRelease: os.release(),
      stateRoot, output, sandboxRequested: true, preload: false, inspectorProLoaded: false };
    await fs.writeFile(path.join(output, 'launch.json'), JSON.stringify(receipt, null, 2) + '\n');
    result = await runOwnedChild({ executable, args: [path.join(__dirname, 'minimal-electron', 'main.cjs'), '--'],
      cwd: root, env, logPath: path.join(output, 'electron.log'), timeoutMs: 45000 });
    await fs.writeFile(path.join(output, 'process-result.json'), JSON.stringify(result, null, 2) + '\n');
    if (!result.ok) throw new Error('Minimal Electron launch failed: ' + result.status + ', exit=' + result.code);
    const report = JSON.parse(await fs.readFile(path.join(output, 'minimal-report.json'), 'utf8'));
    const requiredChecks = ['pageLoad', 'pageAssertions', 'isolation', 'capture',
      ...(options['capture-mode'] === 'after-paint' ? ['firstPaint', 'rendererFrames'] : [])];
    if (report.status !== 'passed' || report.versions.electron !== pinnedVersion
        || report.captureMode !== options['capture-mode']
        || requiredChecks.some(check => report.checks?.[check] !== 'passed')) throw new Error('Pinned minimal Electron page did not pass');
    console.log(JSON.stringify({ passed: true, output, binarySha256, electron: report.versions.electron }));
  } catch (error) {
    await fs.appendFile(path.join(output, 'electron.log'), '\n[minimal diagnostic] ' + error.message + '\n');
    const report = await fs.readFile(path.join(output, 'minimal-report.json'), 'utf8')
      .then(JSON.parse).catch(() => null);
    console.error(JSON.stringify({ passed: false, output, error: error.message,
      failedStage: report?.failedStage ?? null, stageError: report?.error?.message ?? null,
      checks: report?.checks ?? null,
      terminationConfirmed: result?.terminationConfirmed ?? null }));
    process.exitCode = 1;
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
