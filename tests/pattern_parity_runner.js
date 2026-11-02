'use strict';

// The ribbon's builders (static/facility_layout_patterns.js) on shared fixtures, for
// tests/test_layout_patterns_parity.py, which runs the Python port on the same input.
// Input on stdin: {layout, catalog, cases: [{name, builder, ids, collect, options}]}.
const fs = require('fs');
const patterns = require('../static/facility_layout_patterns.js');

const builders = {
    linear: patterns.buildLinearPattern,
    cell: patterns.buildCellLayout,
    circular: patterns.buildCircularPattern,
    perimeter: patterns.buildRectangularPerimeter,
    mirror: patterns.buildMirror,
    stack: patterns.buildVerticalStack,
    surface: patterns.buildSurfaceStack,
};

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = input.cases.map(function (item) {
    try {
        const seed = patterns.collectSelection(input.layout, input.catalog, item.ids, item.collect || {});
        const result = item.builder === 'seed' ? null : builders[item.builder](seed, item.options || {});
        return { name: item.name, ok: true, seed: seed, result: result };
    } catch (error) {
        return { name: item.name, ok: false, error: String(error && error.message || error) };
    }
});
process.stdout.write(JSON.stringify(results));
