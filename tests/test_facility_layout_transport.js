'use strict';

const assert = require('assert');
const Transport = require('../static/facility_layout_transport.js');

const tests = [];

function test(name, fn) {
    tests.push({ name, fn });
}

function response(status, body) {
    return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => JSON.parse(JSON.stringify(body)),
    };
}

test('constructs encoded revision-bound preview and apply requests', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({
        siteId: 'site a',
        layoutId: 'layout/one',
        fetch: async (url, init) => {
            calls.push({ url, init });
            return response(200, { ok: true });
        },
    });
    await transport.previewOperations({
        baseRevision: 'a'.repeat(64),
        operations: [{ op: 'delete_placement', placementId: 'pl-one' }],
    });
    await transport.applyOperations({
        baseRevision: 'b'.repeat(64),
        operations: [{ op: 'delete_zone', zoneId: 'zone-one' }],
    });
    await transport.reloadLayout();

    assert.strictEqual(
        calls[0].url,
        '/api/facility-layouts/site%20a/layout%2Fone/preview'
    );
    assert.strictEqual(calls[0].init.method, 'POST');
    assert.deepStrictEqual(JSON.parse(calls[0].init.body), {
        baseRevision: 'a'.repeat(64),
        operations: [{ op: 'delete_placement', placementId: 'pl-one' }],
    });
    assert.strictEqual(
        calls[1].url,
        '/api/facility-layouts/site%20a/layout%2Fone'
    );
    assert.strictEqual(calls[1].init.method, 'PUT');
    assert.strictEqual(calls[2].init.method, 'GET');
    assert.strictEqual(calls[2].init.credentials, 'same-origin');
    assert.strictEqual(calls[2].init.cache, 'no-store');
});

test('preserves structured conflict details for the session', async () => {
    const currentRevision = 'c'.repeat(64);
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-a',
        fetch: async () => response(409, {
            error: {
                code: 'revision_conflict',
                message: 'Facility Layout revision conflict.',
                details: { currentRevision },
            },
        }),
    });
    await assert.rejects(
        transport.previewOperations({
            baseRevision: 'd'.repeat(64),
            operations: [],
        }),
        error => {
            assert.strictEqual(error.name, 'FacilityLayoutTransportError');
            assert.strictEqual(error.status, 409);
            assert.strictEqual(error.code, 'revision_conflict');
            assert.strictEqual(error.currentRevision, currentRevision);
            assert.deepStrictEqual(error.details, { currentRevision });
            return true;
        }
    );
});

test('validates stable identity and revision inputs before fetch', async () => {
    assert.throws(
        () => Transport.createHttpTransport({
            siteId: '',
            layoutId: 'fl-a',
            fetch: async () => response(200, {}),
        }),
        /siteId/
    );
    const transport = Transport.createHttpTransport({
        siteId: 'site-a',
        layoutId: 'fl-a',
        fetch: async () => response(200, {}),
    });
    assert.throws(
        () => transport.applyOperations({ operations: [] }),
        /baseRevision/
    );
    assert.throws(
        () => transport.previewOperations({
            baseRevision: 'a'.repeat(64),
            operations: {},
        }),
        /operations must be an array/
    );
});

(async () => {
    let passed = 0;
    for (const item of tests) {
        try {
            await item.fn();
            passed += 1;
            process.stdout.write('ok - ' + item.name + '\n');
        } catch (error) {
            process.stderr.write('not ok - ' + item.name + '\n');
            throw error;
        }
    }
    process.stdout.write(
        'Facility layout transport tests: ' + passed + '/' + tests.length
        + ' passed\n'
    );
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
