'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { capture, assertEmpty, WORKFLOWS } = require('../../static/desktop_workflow_observation.js');
const empty = () => Object.fromEntries(Object.keys(WORKFLOWS).map(key =>
  [key, { loaded: false, dirty: false, busy: false, pending: false }]));

test('only complete, explicit empty observations may pass', () => {
  const sources = empty(), snapshot = capture(sources, 'renderer-one');
  assert.deepEqual(assertEmpty(snapshot, 'renderer-one'), snapshot);
  sources.processMap.dirty = true;
  assert.equal(snapshot.workflows.find(row => row.workflowId === 'processMap').dirty, false);
  assert.throws(() => assertEmpty(snapshot, 'renderer-two'), { code: 'desktop_workflow_coverage_unavailable' });
});

for (const workflowId of Object.keys(WORKFLOWS)) {
  test(workflowId + ' loaded, dirty, busy or pending independently blocks without mutating state', () => {
    for (const flag of ['loaded', 'dirty', 'busy', 'pending']) {
      const sources = empty(); sources[workflowId][flag] = true;
      const snapshot = capture(sources, 'r'), before = structuredClone(snapshot);
      assert.throws(() => assertEmpty(snapshot, 'r'), error => {
        assert.equal(error.code, 'desktop_workflow_recovery_not_enabled');
        assert.deepEqual(error.workflows, [workflowId]); return true;
      });
      assert.deepEqual(snapshot, before);
    }
  });
}

test('missing, duplicate, unknown and malformed coverage fail closed', () => {
  for (const alter of [sources => { delete sources.processMap; },
    sources => { sources.unknown = sources.processMap; },
    sources => { sources.agent.pending = null; },
    sources => { sources.agent.extra = false; }]) {
    const sources = empty(); alter(sources);
    assert.throws(() => capture(sources, 'r'), { code: 'desktop_workflow_coverage_unavailable' });
  }
  const snapshot = capture(empty(), 'r'); snapshot.workflows.push(snapshot.workflows[0]);
  assert.throws(() => assertEmpty(snapshot, 'r'), { code: 'desktop_workflow_coverage_unavailable' });
});
