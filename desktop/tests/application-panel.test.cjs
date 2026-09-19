'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../../static/index.html'), 'utf8');
const start = html.indexOf('        function _desktopRestorePartPanel(tab) {');
const end = html.indexOf('        function _desktopObserveApplication()', start);
function fixture(auto, display) {
  let calls = 0;
  const panel = { style: { display } };
  const context = { _desktopAutoCollapsedPartPanel: auto, document: { querySelector: () => panel },
    window: { _toggleLeftPanel: () => { calls++; panel.style.display = ''; } } };
  vm.runInNewContext(html.slice(start, end), context);
  return { context, panel, calls: () => calls };
}
test('part/upload panel returns once when leaving native Facility startup', () => {
  const f = fixture(true, 'none');
  f.context._desktopRestorePartPanel('training'); assert.equal(f.calls(), 0);
  f.context._desktopRestorePartPanel('drawing'); assert.equal(f.calls(), 1);
  f.panel.style.display = 'none';
  f.context._desktopRestorePartPanel('assembly'); assert.equal(f.calls(), 1);
});
test('ordinary web usage and an already-visible panel are not toggled', () => {
  for (const [auto, display] of [[false, 'none'], [false, ''], [true, '']]) {
    const f = fixture(auto, display); f.context._desktopRestorePartPanel('drawing'); assert.equal(f.calls(), 0);
  }
  assert.match(html, /state\.activeTab = tab;\s*_desktopRestorePartPanel\(tab\);/);
});
