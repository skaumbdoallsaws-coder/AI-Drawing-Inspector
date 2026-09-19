'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { until, hash } = require('./facility-recovery-scenarios.cjs');
const { createFacilityManagedRecovery } = require('../src/facility-managed-recovery.cjs');
const { setupStep, setupError } = require('./facility-managed-setup.cjs');

async function atomicJson(file, value) {
  const temporary = file + '.' + randomUUID() + '.tmp';
  const handle = await fs.open(temporary, 'wx');
  try { await handle.writeFile(JSON.stringify(value, null, 2)); await handle.sync(); }
  finally { await handle.close(); }
  await fs.rename(temporary, file);
}

function createRestartChannel(config, pendingOperation) {
  return async control => {
    control.assertCurrent();
    const fault = config.case.endsWith('-failed-restart') ? 'startup-failure'
      : config.case.endsWith('-identity-mismatch') ? 'identity-mismatch' : 'none';
    const leaseFault = config.case.endsWith('-lease-expired') ? 'expired'
      : config.case.endsWith('-other-writer') ? 'other-writer' : 'none';
    await fs.mkdir(config.controlDirectory, { recursive: true });
    control.assertCurrent();
    await atomicJson(path.join(config.controlDirectory, 'request.json'), {
      schemaVersion: 1, requestId: control.requestId, action: 'restart', fault, leaseFault,
      pendingOperation: { requestId: pendingOperation.requestId, transactionId: pendingOperation.transactionId },
    });
    return until(async () => {
      control.assertCurrent();
      try {
        const response = JSON.parse(await fs.readFile(path.join(config.controlDirectory, 'response-' + control.requestId + '.json'), 'utf8'));
        assert.equal(response.schemaVersion, 1); assert.equal(response.requestId, control.requestId);
        return response;
      } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
    }, 'Managed backend supervisor did not return a restart result', 150000);
  };
}

async function runManagedScenarios(driver, config) {
  assert.match(config.case, /^(apply|undo)-(success|failed-restart|identity-mismatch|lease-expired|other-writer)$/);
  const kind = config.case.startsWith('apply-') ? 'apply' : 'undo';
  const success = config.case.endsWith('-success');
  const conflict = /-(lease-expired|other-writer)$/.test(config.case);
  const report = { revision: 'facility-managed-recovery-v1', mode: driver.mode, case: config.case,
    status: 'running', checks: {}, startedAt: new Date().toISOString(), nativeAcceptance: driver.mode === 'native',
    scope: 'isolated managed-backend recovery only', generalEditing: false, researchBrowsing: false };
  await fs.mkdir(config.output, { recursive: true });
  const save = () => atomicJson(path.join(config.output, 'report.json'), report);
  async function check(name, fn) { report.stage = name; await save(); await fn(); report.checks[name] = 'passed'; await save(); }
  async function held(operationKind, proposal, beforeAck = false) {
    await driver.begin(operationKind, proposal, beforeAck);
    const paused = await until(async () => {
      const failure = await driver.operationError(); if (failure) throw Object.assign(new Error(failure.message), { code: failure.code });
      return driver.paused();
    }, 'Actual transaction did not reach the held acknowledgment', 45000);
    assert.equal(paused.name, operationKind === 'apply' ? 'acknowledgeDesignProposalApply' : 'acknowledgeDesignUndo');
    assert.equal(paused.beforeAcknowledgement, beforeAck);
    const state = await driver.snapshot();
    assert.equal(state.pendingOperations.length, 1);
    assert.equal(state.pendingOperations[0].transactionId, paused.transactionId);
    await driver.assertSessionSaveBlocked();
    return state;
  }
  async function release() {
    await driver.release(); await driver.settled();
    assert.equal(await driver.operationError(), null);
  }
  try {
    const initialRuntime = await driver.request('/__facility-recovery__/runtime');
    report.beforeRuntime = initialRuntime;
    const initial = await setupStep(report, save, 'initial-editor-snapshot', () => driver.snapshot());
    const zone = initial.editorFrame.draftLayout.zones[0]; assert.ok(zone?.zoneId);
    const label = (zone.label || 'Facility zone').slice(0, 65);
    await setupStep(report, save, 'manual-edit-1', () => driver.editLabel(zone.zoneId, label + ' [managed edit 1]'));
    await setupStep(report, save, 'manual-edit-2', () => driver.editLabel(zone.zoneId, label + ' [managed edit 2]'));
    const manual = await setupStep(report, save, 'manual-editor-snapshot', () => driver.snapshot());
    assert.equal(manual.editorFrame.cursor, initial.editorFrame.cursor + 2);
    assert.ok(manual.editorFrame.selectedIds.includes(zone.zoneId));
    report.manualFrameHash = hash(manual.editorFrame);
    const proposal = await setupStep(report, save, 'proposal-preparation', () => driver.request('/__facility-recovery__/proposal', {
      operations: [{ op: 'edit_zone', zoneId: zone.zoneId, patch: { label: label + ' [managed Apply]' } }],
      editorFrame: manual.editorFrame,
    }));
    if (kind === 'undo') { await held('apply', proposal); await release(); }
    const pending = await held(kind, kind === 'apply' ? proposal : undefined, conflict);
    const operation = pending.pendingOperations[0];
    report.pendingOperation = { kind, requestId: operation.requestId, transactionId: operation.transactionId,
      holdPoint: conflict ? 'before-acknowledgment-dispatch' : 'after-backend-acknowledgment-before-client-reply' };
    report.pendingFrameHash = hash(pending.editorFrame);
    const handles = await driver.adapter.listRecovery();
    const handle = handles.find(item => item.handle.requestId === operation.requestId);
    assert.ok(handle && handle.handle.transactionId === operation.transactionId);
    report.retainedHandle = handle;
    const makeController = () => createFacilityManagedRecovery({
      authorizedIsolatedHarness: true, adapter: driver.adapter, editor: driver.editor,
      expectedRuntime: initialRuntime, restartBackend: async control => {
        if (driver.setBackendAccess) driver.setBackendAccess(false);
        const response = await createRestartChannel(config, operation)(control);
        report.restart = response; await save(); return response;
      },
      readRuntime: async control => { control.assertCurrent(); report.saveGateBeforeRuntime = await driver.assertSessionSaveBlocked(); return driver.request('/__facility-recovery__/runtime'); },
      quiescePending: async control => {
        control.assertCurrent(); await driver.dropHeldAcknowledgement(); await driver.settled(); control.assertCurrent();
        assert.ok(await driver.operationError(), 'The held success reply must be lost, not delivered after restart');
        assert.deepEqual((await driver.snapshot()).editorFrame, pending.editorFrame);
      },
    });
    await check('cancelBeforeRestartPreservesExactState', async () => {
      const controller = makeController();
      await controller.prepare(); await driver.assertSessionSaveBlocked(); await controller.cancel();
      const after = await driver.snapshot();
      assert.deepEqual(after.editorFrame, pending.editorFrame);
      assert.deepEqual(after.pendingOperations, pending.pendingOperations);
      await driver.assertSessionSaveBlocked();
    });
    const callsBefore = await driver.request('/__facility-recovery__/evidence');
    const lookupStart = driver.lookups.length;
    const controller = makeController();
    await check('restartDuringPendingTransaction', async () => {
      await controller.prepare();
      await driver.assertSessionSaveBlocked();
      const result = await controller.restart(); report.recovery = result;
      if (driver.showRecoveryOutcome) await driver.showRecoveryOutcome(result);
      const after = await driver.snapshot(); report.afterFrameHash = hash(after.editorFrame);
      const expectedFrame = JSON.parse(JSON.stringify(pending.editorFrame));
      if (success && result.status === 'reconciled') {
        if (kind === 'apply') {
          const verified = driver.lookups.slice(lookupStart).find(item => item.status === 'resolved' && item.outcome === 'applied');
          assert.ok(verified?.transactionRevision);
          expectedFrame.activeProposal = {...expectedFrame.activeProposal,status:'active',transactionRevision:verified.transactionRevision};
        } else expectedFrame.activeProposal = null;
      }
      report.expectedAfterFrameHash = hash(expectedFrame);
      assert.deepEqual(after.editorFrame, expectedFrame, 'Restart changed draft, selection, Undo journal, or unverified transaction metadata');
      report.verifiedProposalTransitionOnly = true;
      assert.equal(after.rendererGeneration, pending.rendererGeneration, 'Managed backend restart must retain the renderer');
      const registry = JSON.parse(await fs.readFile(path.join(config.dataRoot, 'recovery-harness-requests.json'), 'utf8'));
      assert.deepEqual(registry.calls, callsBefore.calls, 'Restart/reconciliation dispatched a transaction endpoint');
      assert.equal(registry.deniedSaveCalls, 0);
      report.reconciliationLookups = driver.lookups.slice(lookupStart);
      if (success) {
        assert.equal(result.status, 'reconciled', JSON.stringify(result));
        assert.equal((await controller.getSaveGate()).allowed, true);
        assert.equal(after.pendingOperations.length, 0);
        assert.equal(after.startupRecoveryPending, false);
        if (driver.setBackendAccess) driver.setBackendAccess(true);
      } else {
        assert.equal(result.status, 'requires-recovery', JSON.stringify(result));
        assert.equal((await controller.getSaveGate()).allowed, false);
        await driver.assertSessionSaveBlocked();
        const remaining = await driver.adapter.listRecovery();
        assert.ok(remaining.some(item => item.key === handle.key && item.handle.transactionId === operation.transactionId && !item.adopted));
        assert.equal(after.pendingOperations[0].transactionId, operation.transactionId);
        report.explicitRecovery = { required: true, code: result.code, handleRetained: true, writeAuthority: false };
      }
    });
    await check('durableLookupAndStableIdentity', async () => {
      if (success || conflict) {
        const current = report.restart.afterRuntime;
        assert.ok(current, 'Supervisor must retain verified runtime evidence');
        for (const key of ['identity', 'document', 'owner', 'origin']) assert.deepEqual(current[key], initialRuntime[key]);
        assert.notEqual(current.instanceId, initialRuntime.instanceId);
        assert.notEqual(current.processId, initialRuntime.processId);
        assert.equal(report.reconciliationLookups.length, 1, 'Exactly one durable lookup is required before recovery adoption');
        const lookup = report.reconciliationLookups[0];
        assert.equal(lookup.lookupDiagnostics.instanceId, current.instanceId);
        assert.equal(lookup.lookupDiagnostics.readOnly, true);
        assert.equal(lookup.lookupDiagnostics.registryReloaded, true);
        assert.equal(lookup.lookupDiagnostics.applicationDispatches, 0);
        assert.equal(lookup.clientSaveGate.canSave, false);
        if (driver.mode === 'native') assert.equal(lookup.clientSaveGate.uiChecked, true);
        if (conflict) {
          assert.equal(lookup.status, config.case.endsWith('-lease-expired') ? 'lease_expired' : 'ownership_conflict');
          assert.equal(lookup.writeAuthority, false); assert.equal(lookup.recoveryRequired, true);
        }
      } else {
        assert.equal(report.reconciliationLookups.length, 0, 'Unavailable or mismatched backend cannot receive an authenticated transaction lookup');
        assert.equal(report.restart.status, config.case.endsWith('-identity-mismatch') ? 'identity-mismatch' : 'failed');
      }
    });
    if (success) await check('exactUndoHistoryRestoration', async () => {
      if (kind === 'apply') { await held('undo'); await release(); }
      assert.deepEqual((await driver.snapshot()).editorFrame, manual.editorFrame);
    });
    else await check('failurePreservesDraftAndBlocksSave', async () => {
      await driver.assertSessionSaveBlocked();
      assert.deepEqual((await driver.snapshot()).editorFrame, pending.editorFrame);
      assert.equal((await controller.getSaveGate()).allowed, false);
    });
    await check('zeroSaveAndNoDuplicateExecution', async () => {
      const registry = JSON.parse(await fs.readFile(path.join(config.dataRoot, 'recovery-harness-requests.json'), 'utf8'));
      assert.equal(registry.deniedSaveCalls, 0);
      assert.ok(Object.values(registry.calls).every(count => count === 1));
      report.transactionCalls = registry.calls; report.saveRequests = registry.deniedSaveCalls;
    });
    if (driver.captureEvidence) report.nativeEvidence = await driver.captureEvidence();
    report.status = 'passed'; report.finishedAt = new Date().toISOString(); await save(); return report;
  } catch (error) {
    report.status = 'failed'; report.error = { ...setupError(error), stack: error.stack };
    await save(); throw error;
  }
}
module.exports = { runManagedScenarios, atomicJson };
