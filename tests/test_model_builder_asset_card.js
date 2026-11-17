'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const workspace = require('../static/facility_layout_workspace.js');

test('built asset card line comes from catalog provenance', () => {
    const rows = workspace.normalizeCatalog([{assetId: 'asset-built-sample', assetDefinitionRevision: 'rev-1',
        displayName: 'Sample', category: 'Equipment',
        buildProvenance: {sizeBasis: {kind: 'typical', note: 'approximate class size'}}},
    {assetId: 'asset-import-sample', assetDefinitionRevision: 'rev-2', displayName: 'Import'}]);
    const built = rows.find(row => row.assetId === 'asset-built-sample');
    const imported = rows.find(row => row.assetId === 'asset-import-sample');
    assert.equal(workspace.builtAssetLine(built), 'Built by Sage - typical');
    assert.equal(workspace.builtAssetLine(imported), '');
});
