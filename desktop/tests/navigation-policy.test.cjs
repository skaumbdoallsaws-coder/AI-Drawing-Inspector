'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { parseApplicationUrl, validateApplicationOrigin, classifyNavigation } = require('../src/navigation-policy.cjs');

const ORIGIN = 'http://127.0.0.1:8187';

test('application URLs retain full routes and normalize scheme, hostname and default port', () => {
  assert.deepEqual(parseApplicationUrl('HTTP://LOCALHOST:80/?facilityLayoutId=pilot#view'), {
    url: 'http://localhost/?facilityLayoutId=pilot#view', origin: 'http://localhost', hostname: 'localhost', port: 80,
  });
  assert.equal(parseApplicationUrl('http://[::1]:8187/').origin, 'http://[::1]:8187');
  assert.equal(parseApplicationUrl('https://127.0.0.1/').port, 443);
  assert.equal(validateApplicationOrigin(`${ORIGIN}/`), ORIGIN);
});

test('application origins reject paths and query/fragment delimiters including empty ones', () => {
  for (const suffix of ['/api', '/?', '/#', '?port=9000', '#trusted', '/.', '/..', '/%2e']) {
    assert.throws(() => validateApplicationOrigin(`${ORIGIN}${suffix}`), TypeError, suffix);
  }
});

test('ambiguous loopback spellings cannot become trusted application identities', () => {
  for (const raw of [
    'http://127.1:8187', 'http://2130706433:8187', 'http://0177.0.0.1:8187',
    'http://0x7f000001:8187', 'http://127.0.0.01:8187', 'http://localhost.:8187',
    'http://[0:0:0:0:0:0:0:1]:8187', 'http://[::ffff:127.0.0.1]:8187',
    'http://127.0.0.2:8187', 'http://localhost.evil.test:8187',
    'http://%6cocalhost:8187', 'http://127.0.0.1:08187',
    'http://127.0.0.1:0', 'http://127.0.0.1:', 'http://127.0.0.1:65536',
  ]) assert.throws(() => parseApplicationUrl(raw), TypeError, raw);
});

test('credentials, repaired URL syntax and executable schemes are rejected', () => {
  for (const raw of [undefined, {}, '', ` ${ORIGIN}`, `${ORIGIN}\n`, 'http:\\127.0.0.1:8187',
    'http:///127.0.0.1:8187', 'http://user@127.0.0.1:8187', 'http://@127.0.0.1:8187',
    'http://127.0.0.1:8187@evil.test', 'file:///C:/Windows', 'javascript:alert(1)',
    'data:text/html,hello', 'blob:http://127.0.0.1:8187/id', '//127.0.0.1:8187/',
    `http://127.0.0.1:8187/${'a'.repeat(8192)}`,
  ]) {
    assert.throws(() => parseApplicationUrl(raw), TypeError, String(raw));
    assert.equal(classifyNavigation(raw, ORIGIN).action, 'deny', String(raw));
  }
});

test('application navigation uses the exact configured origin', () => {
  assert.deepEqual(classifyNavigation(`${ORIGIN}/?facilityLayoutId=pilot#3d`, ORIGIN), {
    action: 'allow-app', url: `${ORIGIN}/?facilityLayoutId=pilot#3d`,
  });
  for (const raw of ['http://localhost:8187', 'http://127.0.0.1:8000', 'https://127.0.0.1:8187',
    'http://127.1:8187', 'http://2130706433:8187', 'http://[::1]:8187']) {
    assert.equal(classifyNavigation(raw, ORIGIN).action, 'deny', raw);
  }
  assert.equal(classifyNavigation(`${ORIGIN}/`, `${ORIGIN}/api`).action, 'deny');
});

test('public HTTP(S) returns sanitized external-browser candidates only', () => {
  assert.deepEqual(classifyNavigation('HTTPS://EXAMPLE.COM:443/manual?q=table#installation', ORIGIN), {
    action: 'external-browser', url: 'https://example.com/manual?q=table#installation',
  });
  assert.equal(classifyNavigation('http://example.com/manual', ORIGIN).action, 'external-browser');
  for (const raw of ['https://name:secret@example.com/', 'mailto:sales@example.com', 'inspectorpkg:run',
    'https://example.com\n', 'https://example.com\\@127.0.0.1/']) {
    assert.equal(classifyNavigation(raw, ORIGIN).action, 'deny', raw);
  }
});

test('other local literal destinations are not external-browser candidates', () => {
  for (const host of ['127.0.0.2', 'localhost.', 'sub.localhost', 'printer.local', 'intranet',
    '0.0.0.0', '10.1.2.3', '172.16.1.2', '192.168.1.1', '169.254.169.254',
    '100.64.0.1', '[::1]', '[::ffff:127.0.0.1]', '[fd00::1]']) {
    assert.equal(classifyNavigation(`http://${host}/`, ORIGIN).action, 'deny', host);
  }
});
