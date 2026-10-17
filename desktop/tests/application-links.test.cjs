'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { installApplicationLinks } = require('../src/application-links.cjs');
const { parseRuntimeOptions } = require('../src/runtime-settings.cjs');
const origin = 'http://127.0.0.1:8480';
function fixture(browser = false) {
  const handlers = {}, downloads = [], external = [], reloads = [], opened = [];
  const window = { webContents: {
    setWindowOpenHandler: fn => { handlers.popup = fn; },
    on: (name, fn) => { handlers[name] = fn; }, downloadURL: url => downloads.push(url),
  } };
  const api = installApplicationLinks({ window, network: { local: url => {
    const u = new URL(url); return u.origin === origin && !u.username && !u.password;
  } }, external: url => external.push(url), reload: url => reloads.push(url),
    ...(browser ? { openBrowser: url => opened.push(url), isDocument: url => url.endsWith('.pdf') } : {}) });
  return { ...api, handlers, downloads, external, reloads, opened };
}
test('normal desktop previews chat links and documents without downloading or unloading the app', () => {
  const f = fixture(true), urls = ['https://example.com/', origin + '/generated/manual.pdf'];
  for (const url of urls) f.handlers.popup({ url });
  assert.deepEqual(f.opened, urls);
  assert.deepEqual(f.external, []); assert.deepEqual(f.downloads, []); assert.deepEqual(f.reloads, []);
  f.handlers.popup({ url: origin + '/?facilityLayoutId=fl-manual' });
  assert.deepEqual(f.reloads, [origin + '/?facilityLayoutId=fl-manual']);
});

test('browser acceptance is an exclusive explicit option', () => {
  const args = ['--profile-file', path.resolve('profile.json'), '--python', path.resolve('python.exe')];
  const out = path.resolve('evidence');
  assert.equal(parseRuntimeOptions(args).browserAcceptanceOutput, undefined);
  assert.equal(parseRuntimeOptions([...args, '--browser-acceptance-output', out]).browserAcceptanceOutput, out);
  for (const flag of ['--acceptance-output', '--workflow-acceptance-output', '--startup-diagnostics-output', '--research-acceptance-output']) {
    assert.throws(() => parseRuntimeOptions([...args, '--browser-acceptance-output', out, flag, out]));
  }
});

test('generation acceptance is explicit and excludes other acceptance modes', () => {
  const args = ['--profile-file', path.resolve('profile.json'), '--python', path.resolve('python.exe')];
  const out = path.resolve('generation-evidence');
  assert.equal(parseRuntimeOptions(args).generationAcceptanceOutput, undefined);
  assert.equal(parseRuntimeOptions([...args, '--generation-acceptance-output', out]).generationAcceptanceOutput, out);
  for (const flag of ['--acceptance-output', '--workflow-acceptance-output', '--browser-acceptance-output', '--startup-diagnostics-output', '--research-acceptance-output']) {
    assert.throws(() => parseRuntimeOptions([...args, '--generation-acceptance-output', out, flag, out]));
  }
});
for (const suffix of ['/api/parts-manual/MMLE-50D/artifacts/manual.pdf',
  '/api/work-instructions/MMLE-50D/artifact.pdf', '/generated/exports/report.docx',
  '/api/profiles', '/static/logo.png']) {
  test('same-window and popup artifact handoffs download without unloading: ' + suffix, () => {
    const f = fixture(); let prevented = 0;
    const url = origin + suffix;
    f.handlers['will-navigate']({ preventDefault: () => prevented++ }, url);
    assert.deepEqual(f.handlers.popup({ url }), { action: 'deny' });
    assert.equal(prevented, 1);
    assert.deepEqual(f.downloads, [url, url]);
    assert.deepEqual(f.external, []); assert.deepEqual(f.reloads, []);
  });
}
test('application reload uses draft protection and remote links use confirmation', () => {
  const f = fixture();
  f.handlers.popup({ url: origin + '/?facilityLayoutId=fl-manual' });
  f.handlers.popup({ url: 'https://example.com/manual' });
  assert.deepEqual(f.reloads, [origin + '/?facilityLayoutId=fl-manual']);
  assert.deepEqual(f.external, ['https://example.com/manual']);
  assert.deepEqual(f.downloads, []);
});
test('only owned blobs download; executable, credentialed and foreign blobs are denied', () => {
  const f = fixture();
  f.handlers.popup({ url: 'blob:' + origin + '/export' });
  for (const url of ['blob:https://example.com/export', 'javascript:alert(1)', 'file:///C:/private',
    'https://user:pass@example.com/', 'http://127.0.0.1:8480@evil.invalid/']) {
    assert.equal(f.destination(url), 'deny');
    f.handlers.popup({ url });
  }
  assert.deepEqual(f.downloads, ['blob:' + origin + '/export']);
  assert.deepEqual(f.external, []);
});
test('workflow acceptance has explicit exclusive output and no effect on ordinary options', () => {
  const args = ['--profile-file', path.resolve('profile.json'), '--python', path.resolve('python.exe')];
  assert.equal(parseRuntimeOptions(args).workflowAcceptanceOutput, undefined);
  const out = path.resolve('evidence');
  assert.equal(parseRuntimeOptions([...args, '--workflow-acceptance-output', out]).workflowAcceptanceOutput, out);
  for (const flag of ['--acceptance-output', '--startup-diagnostics-output', '--research-acceptance-output']) {
    assert.throws(() => parseRuntimeOptions([...args, '--workflow-acceptance-output', out, flag, out]));
  }
});
