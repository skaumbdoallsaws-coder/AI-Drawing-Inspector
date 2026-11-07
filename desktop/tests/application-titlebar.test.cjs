'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('normal native window integrates OS caption controls without replacing close protection', () => {
  const source = fs.readFileSync(path.join(__dirname, '../src/application-main.cjs'), 'utf8');
  assert.match(source, /titleBarStyle: 'hidden'/);
  assert.match(source, /titleBarOverlay: \{ color: '#111d2a', symbolColor: '#d8dee6', height: 42 \}/);
  assert.match(source, /window\.on\('close', event => \{ if \(!closing\) \{ event\.preventDefault\(\); void change\('close'\);/);
});

test('native preload installs header-only drag regions and a registration-only bridge without arbitrary IPC', () => {
  const events = new Map();
  const styles = [];
  const exposed = [];
  const ipcCalls = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/application-preload.cjs'), 'utf8'), {
    require(name) {
      assert.equal(name, 'electron');
      return {
        contextBridge: { exposeInMainWorld: (name, api) => exposed.push([name, api]) },
        ipcRenderer: { on() {}, send: (...args) => ipcCalls.push(['send', ...args]),
          invoke: (...args) => ipcCalls.push(['invoke', ...args]) },
      };
    },
    document: {
      getElementById() { return null; },
      addEventListener(name, callback, options) { events.set(name, { callback, options }); },
      createElement: tag => ({ tag }),
      head: { appendChild: element => styles.push(element) },
    },
    MutationObserver: class { observe() {} },
  });
  assert.equal(styles.length, 0);
  assert.equal(events.get('DOMContentLoaded').options.once, true);
  events.get('DOMContentLoaded').callback();
  assert.equal(styles.length, 1);
  const css = styles[0].textContent;
  assert.match(css, /\.app-container > \.toolbar \{\s*-webkit-app-region: drag/);
  assert.match(css, /env\(titlebar-area-width, 100%\)/);
  assert.match(css, /\.window-controls \{ display: none; \}/);
  for (const control of ['button', 'input', 'nav', '.toolbar-search-wrap']) {
    assert.ok(css.includes('.toolbar ' + control));
  }
  assert.match(css, /-webkit-app-region: no-drag/);
  assert.deepEqual(exposed.map(([name, api]) => [name, Object.keys(api)]), [
    ['InspectorProNativeApplication', ['registerLifecycleObserver', 'registerPackagingClose', 'registerDeparturePreparation']],
  ]);
  const api = exposed[0][1];
  assert.equal(Object.isFrozen(api), true);
  for (const name of ['send', 'sendSync', 'invoke', 'on', 'ipcRenderer', 'close', 'reload', 'restart', 'closePackaging']) {
    assert.equal(api[name], undefined, 'No renderer IPC or native action capability: ' + name);
  }
  let callbacks = 0;
  for (const name of ['registerLifecycleObserver', 'registerPackagingClose', 'registerDeparturePreparation']) {
    for (const invalid of [null, {}, 'arbitrary-channel']) assert.throws(() => api[name](invalid));
    api[name](() => { callbacks++; });
    assert.throws(() => api[name](() => {}), /already registered/);
  }
  assert.equal(callbacks, 0, 'Registration must not execute a lifecycle action');
  assert.deepEqual(ipcCalls, [], 'Registration must not dispatch arbitrary IPC');
});
