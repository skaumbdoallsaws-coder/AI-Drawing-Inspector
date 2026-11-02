'use strict';

// The ribbon's own operations for the patterns that do not go through the command adapter: the workspace builds
// a mirror, circular or perimeter result with static/facility_layout_patterns.js and hands it to the session's
// applyPattern. For tests/test_sage_pattern_tools.py only; Node never runs in the app.
// Input on stdin: {layout, catalog, operationIdNamespace, ids, collect, builder, options}.
// Output: {ok: true, operations} or {ok: false, error}.
const fs = require('fs');
const sessionModule = require('../static/facility_layout_session.js');
const patterns = require('../static/facility_layout_patterns.js');

const CAPTURED = Symbol('operation plan captured');
const builders = {
    mirror: [patterns.buildMirror, 'Mirror layout selection'],
    circular: [patterns.buildCircularPattern, 'Circular layout pattern'],
    perimeter: [patterns.buildRectangularPerimeter, 'Rectangular perimeter pattern'],
};

async function main() {
    const input = JSON.parse(fs.readFileSync(0, 'utf8'));
    let operations;
    const session = sessionModule.createSession({
        operationIdNamespace: input.operationIdNamespace,
        previewOperations: async request => {
            operations = request.operations;
            throw CAPTURED;
        },
        applyOperations: async () => { throw new Error('The runner cannot save'); },
    });
    session.load({ layout: input.layout, revision: '0'.repeat(64) });
    const seed = patterns.collectSelection(input.layout, input.catalog, input.ids, input.collect || {});
    const [build, label] = builders[input.builder];
    const result = build(seed, input.options || {});
    try {
        await session.applyPattern(result, label);
        throw new Error('The session sent no operations');
    } catch (error) {
        if (error !== CAPTURED) throw error;
    }
    process.stdout.write(JSON.stringify({ ok: true, operations }));
}

main().catch(error => {
    process.stdout.write(JSON.stringify({ ok: false, error: String(error && error.message || error) }));
    process.exitCode = 1;
});
