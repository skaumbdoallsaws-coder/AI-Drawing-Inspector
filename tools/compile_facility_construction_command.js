'use strict';

// Compile only: the host validates these operations against authoritative
// documents. The preview interception never claims an edit or validation pass.
const fs = require('fs');
const sessionModule = require('../static/facility_layout_session.js');
const patterns = require('../static/facility_layout_patterns.js');
const adapterModule = require('../static/facility_layout_command_adapter.js');
const contract = require('../static/contracts/facility-construction-commands-v1.json');
const CAPTURED = Symbol('operation plan captured');

async function main() {
    const input = JSON.parse(fs.readFileSync(0, 'utf8'));
    if (!/^[0-9a-f]{40}$/.test(input.operationIdNamespace || '')) {
        throw new Error('Compiler operation namespace is required');
    }
    let operations;
    const session = sessionModule.createSession({
        operationIdNamespace: input.operationIdNamespace,
        previewOperations: async request => {
            operations = request.operations;
            throw CAPTURED;
        },
        applyOperations: async () => { throw new Error('Compiler cannot save'); },
    });
    session.load({ layout: input.layout, revision: input.command.expectedDraftRevision });
    const adapter = adapterModule.createAdapter(contract, patterns, session, () => input.catalog);
    try {
        await adapter.execute(input.command);
        throw new Error('Compiler produced no operation plan');
    } catch (error) {
        if (error !== CAPTURED) throw error;
    }
    if (!operations.length || operations.length > 500) throw new Error('Construction operation budget exceeded');
    process.stdout.write(JSON.stringify({ ok: true, operations }));
}

main().catch(error => {
    process.stdout.write(JSON.stringify({ ok: false, error: {
        code: error.code || 'facility_construction_compile_failed', message: String(error.message || error),
    } }));
    process.exitCode = 1;
});
