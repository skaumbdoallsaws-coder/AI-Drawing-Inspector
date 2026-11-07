'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { runOwnedChild } = require('./owned-child-runner.cjs');
const root = path.resolve(__dirname, '../..');
async function main() {
  const [electron, profileFile, python, output] = process.argv.slice(2);
  if (![electron, profileFile, python, output].every(p => typeof p === 'string' && path.isAbsolute(p))) {
    throw Error('Supply absolute Electron, test profile, Python, and evidence directory paths.');
  }
  const profile = JSON.parse(fs.readFileSync(profileFile, 'utf8'));
  const fixture = JSON.parse(fs.readFileSync(path.join(profile.dataRoot, 'packaging-check.json'), 'utf8'));
  if (fixture.disposable !== true || fixture.store !== profile.dataRoot || !profile.profileId.startsWith('packaging-native-')) throw Error('Disposable packaging profile required');
  const env = { ...process.env };
  for (const name of Object.keys(env)) if (/^(ELECTRON_RUN_AS_NODE|NODE_OPTIONS)$/i.test(name)) delete env[name];
  const result = await runOwnedChild({ executable: electron,
    args: [path.join(__dirname, 'packaging-native-entry.cjs'), '--profile-file', profileFile,
      '--python', python, '--acceptance-output', output], cwd: root, env,
    logPath: path.join(path.dirname(output), 'driver.log'), timeoutMs: 600000 });  // The runner's maximum; the full run restarts the backend three times.
  console.log(JSON.stringify(result));
  if (!result.ok) process.exitCode = 1;
  else {
    const report = JSON.parse(fs.readFileSync(path.join(output, 'packaging-native.json'), 'utf8'));
    console.log(JSON.stringify(report));
    if (report.status !== 'passed') process.exitCode = 1;
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
