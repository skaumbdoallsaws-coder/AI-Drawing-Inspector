'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { guardSavedFacilityContext } = require('../static/chat_stream_runtime.js');

function fixture() {
    const state = { loaded: true, dirty: false, conflict: null, baseRevision: 'r1', draftRevision: 'r1',
        layout: { layoutId: 'gym', association: { siteId: 'site' } } };
    const current = { active: true, requestCurrent: true, state };
    let listener, poll, invalidations = 0, disposed = 0;
    const guard = guardSavedFacilityContext({ reference: { siteId: 'site', layoutId: 'gym', revision: 'r1' },
        readCurrent: () => current, subscribe: fn => { listener = fn; return () => disposed++; },
        setInterval: fn => { poll = fn; return 1; }, clearInterval: () => disposed++,
        onInvalidate: () => invalidations++ });
    return { state, current, guard, notify: () => listener(), poll: () => poll(),
        counts: () => ({invalidations, disposed}) };
}
for (const mutation of [f => f.state.dirty = true, f => f.state.conflict = {},
    f => f.state.baseRevision = 'r2', f => f.state.draftRevision = 'r2',
    f => f.state.layout.layoutId = 'another', f => f.state.layout.association.siteId = 'foreign',
    f => f.current.active = false, f => f.current.requestCurrent = false]) {
    test('changed saved context cancels once and cannot recover silently: ' + mutation, () => {
        const f = fixture();
        mutation(f); f.notify(); f.poll();
        assert.equal(f.guard.check(), false);
        assert.equal(f.counts().invalidations, 1);
        f.guard.dispose(); f.guard.dispose();
        assert.equal(f.counts().disposed, 2);
    });
}
test('unchanged context survives status notifications and disposal removes listeners', () => {
    const f = fixture(); f.state.busy = true; f.notify(); f.poll();
    assert.equal(f.guard.check(), true);
    assert.equal(f.counts().invalidations, 0);
    f.guard.dispose(); f.state.dirty = true; f.poll();
    assert.equal(f.counts().invalidations, 0);
});
