const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const index = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8').replace(/\r\n/g, '\n');

const configMatch = index.match(
    /const FACILITY_LAYOUT_RIBBON_CONFIG = Object\.freeze\(\[(.*?)\]\);/s
);
assert.ok(configMatch, 'Facility ribbon command registry exists');
const commandIds = [...configMatch[1].matchAll(/commands:\s*\[([^\]]*)\]/gs)]
    .flatMap(match => [...match[1].matchAll(/['"]([^'"]+)['"]/g)])
    .map(match => match[1]);

const implementationStart = index.indexOf('function _trainFacilityRibbonTitle');
const implementationEnd = index.indexOf(
    'function _trainRenderProcessMapRibbon',
    implementationStart
);
assert.ok(implementationStart >= 0 && implementationEnd > implementationStart);
const implementation = index.slice(implementationStart, implementationEnd);
commandIds.forEach(command => {
    assert.ok(
        implementation.includes(`'${command}'`) || implementation.includes(`"${command}"`),
        `Facility ribbon keeps ${command} reachable`
    );
});

const facilityCssStart = index.indexOf('.ribbon.facility-layout-ribbon {', 0);
const facilityCssEnd = index.indexOf('.ribbon-facility-icon {', facilityCssStart);
assert.ok(facilityCssStart >= 0 && facilityCssEnd > facilityCssStart);
const facilityCss = index.slice(facilityCssStart, facilityCssEnd);
assert.ok(facilityCss.includes('overflow: visible;'));
assert.ok(!facilityCss.includes('overflow-x: auto'));
assert.ok(index.includes('container-name: facility-ribbon'));
assert.ok(index.includes('@container facility-ribbon (max-width: 1450px)'));
assert.ok(index.includes('@container facility-ribbon (max-width: 1120px)'));
assert.ok(index.includes("facilityQuery.get('facilityAssets') === '1'"));
assert.ok(index.includes('appInstance.workspace.openAssetBrowser()'));

[
    'facility-ribbon-shell',
    'facility-workflow-selector',
    'facility-ribbon-commandbar',
    'facility-ribbon-overflow-menu',
    'data-facility-ribbon-group',
    'data-facility-separator-for',
    'data-facility-ribbon-command',
].forEach(token => assert.ok(index.includes(token), token));

[
    ['selection', 'Selection'],
    ['create', 'Create'],
    ['edit', 'Edit'],
    ['position', 'Position'],
    ['build', 'Build'],
    ['history', 'History'],
    ['layout', 'Layout'],
    ['more', 'More'],
].forEach(([key, label]) => {
    assert.ok(implementation.includes(`appendGroup('${key}', '${label}'`)
        || implementation.includes(`'${key}',\n                '${label}'`));
});

console.log(`Facility ribbon organization: ${commandIds.length} commands remain reachable`);
