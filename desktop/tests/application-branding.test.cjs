'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { APP_NAME, APP_ID, ICON_PATH, brandApplication, brandWindow } = require('../src/application-branding.cjs');

test('native application and taskbar share the InspectorPro identity and icon', () => {
  const calls = [];
  brandApplication({ setName: value => calls.push(['name', value]),
    setAppUserModelId: value => calls.push(['identity', value]) }, 'win32');
  brandWindow({ setAppDetails: value => calls.push(['window', value]) }, 'win32');
  assert.deepEqual(calls, [['name', APP_NAME], ['identity', APP_ID], ['window', {
    appId: APP_ID, appIconPath: ICON_PATH, appIconIndex: 0,
  }]]);
  assert.equal(APP_NAME, 'InspectorPro');
  assert.equal(APP_ID, 'InspectorPro.Desktop');
});

test('non-Windows platforms do not call Windows-only identity APIs', () => {
  const names = [];
  for (const platform of ['linux', 'darwin']) {
    brandApplication({ setName: value => names.push(value) }, platform);
    brandWindow({}, platform);
  }
  assert.deepEqual(names, ['InspectorPro', 'InspectorPro']);
});

test('checked-in icon contains each Windows display size as valid PNG data', () => {
  const data = fs.readFileSync(ICON_PATH);
  assert.equal(data.readUInt16LE(0), 0);
  assert.equal(data.readUInt16LE(2), 1);
  const count = data.readUInt16LE(4);
  assert.equal(count, 9);
  const sizes = [];
  for (let i = 0; i < count; i++) {
    const offset = 6 + i * 16;
    const width = data[offset] || 256;
    assert.equal(data[offset + 1] || 256, width);
    const length = data.readUInt32LE(offset + 8);
    const start = data.readUInt32LE(offset + 12);
    assert.ok(start >= 6 + count * 16 && length > 24 && start + length <= data.length);
    assert.equal(data.subarray(start, start + 8).toString('hex'), '89504e470d0a1a0a');
    assert.equal(data.readUInt32BE(start + 16), width);
    assert.equal(data.readUInt32BE(start + 20), width);
    sizes.push(width);
  }
  assert.deepEqual(sizes, [16, 20, 24, 32, 40, 48, 64, 128, 256]);
});

test('ordinary startup and shortcut installer use the new icon before showing the app', () => {
  const main = fs.readFileSync(path.join(__dirname, '../src/application-main.cjs'), 'utf8');
  assert.ok(main.indexOf('brandApplication(app)') < main.indexOf('app.whenReady()'));
  assert.match(main, /new BrowserWindow\([\s\S]*?icon: ICON_PATH/);
  const startup = main.slice(main.indexOf('async function start() {'));
  assert.ok(startup.indexOf('brandWindow(window)') < startup.indexOf('window.loadURL(url.href)'));
  const installer = fs.readFileSync(path.join(__dirname, '../../scripts/install_inspectorpro_native_shortcut.ps1'), 'utf8');
  assert.ok(installer.includes("'assets\\inspectorpro.ico'"));
  assert.ok(installer.includes('$shortcut.IconLocation = "$icon,0"'));
  assert.ok(!installer.includes('$shortcut.IconLocation = "$Electron,0"'));
});
