const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const index = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const icons = require('../static/facility_ribbon_icons.js');
const registryText = index.match(/const FACILITY_LAYOUT_RIBBON_COMMANDS = Object.freeze\((\{[^]*?\n        \})\);/)[1];
const commands = vm.runInNewContext('(' + registryText + ')');
test('every actual Facility command has its own transparent small icon and a valid primary asset', () => {
    assert.equal(Object.keys(commands).length, 44);
    for (const command of [...Object.keys(commands), 'more']) {
        for (const small of [true, false]) {
            const url = icons.source(command, small);
            assert.ok(fs.statSync(path.join(root, url.slice(1))).size > 100, command);
        }
        const svg = fs.readFileSync(path.join(root, icons.source(command, true).slice(1)), 'utf8');
        assert.ok(svg.includes('viewBox="0 0 64 64"'));
        assert.ok(svg.includes('<linearGradient'));
        assert.ok(!/<(?:script|image|foreignObject)|https?:\/\/(?!www.w3.org)/i.test(svg));
    }
});
test('matching commands reuse approved Packaging art instead of duplicate copies', () => {
    for (const command of ['appearance', 'auto-arrange', 'save', 'undo', 'redo']) {
        assert.match(icons.source(command), /packaging-ribbon-icons/);
    }
});
test('each menu retains its real options and order', () => {
    for (const options of [
        ['rectangle-zone', 'polygon-zone', 'bulk-zones'], ['appearance', 'component-materials'],
        ['decals', 'lettering'], ['interior-walls', 'floor-surfaces', 'floor-plan', 'columns'],
        ['align', 'distribute', 'relative', 'distance', 'offset'],
        ['linear-pattern', 'circular-pattern', 'perimeter-pattern', 'mirror'],
        ['cell-layout', 'create-cell-group', 'ungroup-cell'], ['vertical-stack', 'surface-stack', 'swap'],
    ]) assert.ok(index.includes('[' + options.map(x => "'" + x + "'").join(', ') + ']'));
    assert.ok(index.includes("['saved-movement', 'clear-all']"));
});
test('compact controls keep labels in the DOM, accessible titles and authoritative state handling', () => {
    const css = fs.readFileSync(path.join(root, 'static/facility_ribbon_icons.css'), 'utf8');
    assert.match(css, /\.facility-icon-only \.documentation-command-label[^}]+clip-path: inset\(50%\)/s);
    assert.match(index, /_trainFacilityRibbonTitle\(command\)/);
    assert.match(index, /button\.disabled = !stateForCommand/);
    assert.match(index, /states\[command\] && states\[command\]\.disabled/);
    assert.match(index, /await workspace\.executeCommand\(command\)/);
    assert.match(css, /data-overflow-group="layout"/);
});
