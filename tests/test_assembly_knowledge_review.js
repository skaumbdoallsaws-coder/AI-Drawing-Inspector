'use strict';

const assert = require('assert');
const review = require('../static/assembly_knowledge_review.js');

let passed = 0;

function test(name, fn) {
    fn();
    passed += 1;
    process.stdout.write('PASS ' + name + '\n');
}

test('asset URL encodes identifiers and preserves path segments', function () {
    assert.strictEqual(
        review.assetUrl(
            'fixture product',
            'akp-123',
            'visuals/presentation/front view.png'
        ),
        '/api/training/assembly-knowledge/fixture%20product/akp-123/assets/'
            + 'visuals/presentation/front%20view.png'
    );
});

test('review payload normalization rejects non-array rows', function () {
    assert.deepStrictEqual(
        review.normalizeReviewPayload({
            review: {
                identity: { packageId: 'akp-1' },
                items: {},
                findings: null,
            },
        }),
        {
            identity: { packageId: 'akp-1' },
            summary: {},
            assets: {},
            sourceStatus: {},
            items: [],
            findings: [],
        }
    );
});

test('review action is bound to package and source revisions', function () {
    const body = review.reviewActionBody(
        {
            identity: {
                packageRevision: 'a'.repeat(64),
                sourceRevision: 'b'.repeat(64),
            },
        },
        { claimId: 'claim-1' },
        'confirm',
        'reviewer'
    );
    assert.deepStrictEqual(body, {
        baseRevision: 'a'.repeat(64),
        sourceRevision: 'b'.repeat(64),
        claimId: 'claim-1',
        action: 'confirm',
        actor: 'reviewer',
    });
});

test('edit action carries only the explicit replacement value', function () {
    const body = review.reviewActionBody(
        {
            identity: {
                packageRevision: 'a'.repeat(64),
                sourceRevision: 'b'.repeat(64),
            },
        },
        { claimId: 'claim-1' },
        'edit',
        'reviewer',
        { label: 'Reviewed operation' }
    );
    assert.deepStrictEqual(body.editedValue, { label: 'Reviewed operation' });
});

process.stdout.write(passed + '/4 passed\n');
