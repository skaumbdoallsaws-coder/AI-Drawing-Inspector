'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { validateApplicationOrigin } = require('./navigation-policy.cjs');

const KEYS = ['schemaVersion', 'product', 'mode', 'backendId', 'storeId', 'profileId', 'researchBrowsing', 'interactive'];
function validateIdentity(value) {
  if (!value || value.schemaVersion !== 1 || value.product !== 'InspectorPro' ||
      value.mode !== 'rendering-spike' || value.interactive !== false || value.researchBrowsing !== false ||
      !['backendId', 'storeId'].every(k => typeof value[k] === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value[k])) ||
      typeof value.profileId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value.profileId)) {
    throw new Error('Backend is not a supported isolated rendering profile');
  }
  return Object.freeze(Object.fromEntries(KEYS.map(key => [key, value[key]])));
}

async function verifyBackend({ origin, identityFile, fetchImpl = fetch }) {
  origin = validateApplicationOrigin(origin);
  const stat = await fs.stat(identityFile);
  if (!stat.isFile() || stat.size > 16384) throw new Error('Invalid backend identity file');
  const marker = JSON.parse(await fs.readFile(identityFile, 'utf8'));
  if (marker.origin !== origin) throw new Error('Backend origin differs from the explicit identity file');
  const expected = validateIdentity(marker);
  const response = await fetchImpl(origin + '/api/desktop-shell/identity', {
    redirect: 'error', signal: AbortSignal.timeout(5000), headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error('Backend identity handshake failed');
  // This is a fixture identity comparison, not production pairing/authentication.
  const reader = response.body.getReader();
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.length;
      if (size > 16384) throw new Error('Backend identity response exceeds its limit');
      chunks.push(value);
    }
  } finally { await reader.cancel().catch(() => {}); }
  const actual = validateIdentity(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error('Backend/store identity mismatch');
  return Object.freeze({ origin, identity: expected });
}

async function bindProfile(directory, verified) {
  await fs.mkdir(directory, { recursive: true });
  const profilePath = path.join(directory, 'profile.json');
  const value = { schemaVersion: 1, origin: verified.origin, identity: verified.identity };
  const encoded = JSON.stringify(value, null, 2) + '\n';
  try {
    const previous = JSON.parse(await fs.readFile(profilePath, 'utf8'));
    if (JSON.stringify(previous) !== JSON.stringify(value)) throw new Error('This shell profile belongs to another origin/backend/store. Choose a separate state root; no migration was performed.');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    const handle = await fs.open(profilePath, 'wx');
    try { await handle.writeFile(encoded); await handle.sync(); } finally { await handle.close(); }
  }
  const partitionKey = createHash('sha256').update(JSON.stringify(value)).digest('hex');
  return { partition: 'persist:ip-' + partitionKey.slice(0, 32), profilePath };
}

function parseOptions(args, root) {
  if (args[0] === '--') args = args.slice(1);
  const allowed = new Set(['--backend', '--identity-file', '--state-root', '--smoke-output', '--expected-page']);
  const values = {};
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    if (!allowed.has(flag) || Object.hasOwn(values, flag) || !args[index + 1] || args[index + 1].startsWith('--')) {
      throw new Error('Usage: npm start -- --backend http://127.0.0.1:PORT --identity-file PATH [--state-root PATH]');
    }
    values[flag] = args[index + 1];
  }
  if (!values['--backend'] || !values['--identity-file']) throw new Error('An explicit backend origin and its isolated identity file are required');
  const expectedPage = values['--expected-page'] || 'full-application';
  if (!['inert-fixture', 'full-application'].includes(expectedPage)
      || (values['--expected-page'] && !values['--smoke-output'])) throw new Error('An expected page kind requires smoke output and a supported kind');
  return { origin: validateApplicationOrigin(values['--backend']), identityFile: path.resolve(values['--identity-file']),
    stateRoot: path.resolve(values['--state-root'] || path.join(root, '.runtime', 'shell')),
    smokeOutput: values['--smoke-output'] ? path.resolve(values['--smoke-output']) : null, expectedPage };
}

module.exports = { validateIdentity, verifyBackend, bindProfile, parseOptions };
