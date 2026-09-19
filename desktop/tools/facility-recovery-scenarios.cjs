'use strict';
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
const hash = value => createHash('sha256').update(canonical(value)).digest('hex');
async function until(fn, message, timeout=20000) {
  const end = Date.now()+timeout;
  while (Date.now()<end) {const result=await fn();if(result)return result;await new Promise(r=>setTimeout(r,50));}
  throw new Error(message);
}

/** Shared assertions; drivers use either actual native renderer or actual Node session. */
async function runScenarios(driver,{phase,dataRoot,output}) {
  const report={revision:'facility-recovery-acceptance-v1',phase,mode:driver.mode,status:'running',checks:{},startedAt:new Date().toISOString()};
  const saveReport=()=>fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  const privateState=path.join(dataRoot,'facility-recovery-scenario-state.json');
  await fs.mkdir(output,{recursive:true});await saveReport();
  async function check(name,action) {report.stage=name;await saveReport();await action();report.checks[name]='passed';await saveReport();}
  async function closeCancel(expectedStatus) {
    const before=await driver.snapshot();
    const decision=await driver.prepareClose();
    assert.equal(decision.status,expectedStatus,JSON.stringify(decision));
    const during=await driver.snapshot();
    assert.deepEqual(during.editorFrame,before.editorFrame);
    assert.deepEqual(during.pendingOperations,before.pendingOperations);
    const cancelled=await driver.adapter.cancel(decision.intentId);
    assert.equal(cancelled.status,'cancelled');
    const after=await driver.snapshot();
    assert.deepEqual(after.editorFrame,before.editorFrame,'Close/Cancel changed exact editor frame');
    assert.deepEqual(after.pendingOperations,before.pendingOperations,'Close/Cancel changed operation identity');
    if(driver.isClosed)assert.equal(await driver.isClosed(),false);
    return before;
  }
  async function held(kind,reference) {
    await driver.begin(kind,reference);
    const paused=await until(async()=>{const failure=await driver.operationError();if(failure)throw Object.assign(new Error(failure.message),{code:failure.code});return driver.paused();},'Actual backend acknowledgement was not reached',45000);
    assert.equal(paused.name,kind==='apply'?'acknowledgeDesignProposalApply':'acknowledgeDesignUndo');
    const snapshot=await driver.snapshot();
    assert.equal(snapshot.pendingOperations.length,1);
    assert.equal(snapshot.pendingOperations[0].transactionId,paused.transactionId);
    assert.equal((await driver.adapter.getSaveGate()).allowed,false);
    await driver.assertSessionSaveBlocked();
    return snapshot;
  }
  async function release() {
    await driver.release();await driver.settled();
    const failure=await driver.operationError();
    assert.equal(failure,null,JSON.stringify(failure));
    assert.equal((await driver.snapshot()).pendingOperations.length,0);
  }
  try {
    if(phase===1) {
      const initial=await driver.snapshot();
      const zone=initial.editorFrame.draftLayout.zones[0];assert.ok(zone?.zoneId);
      const prefix=(zone.label||'Facility zone').slice(0,65);
      await check('twoManualEditsCloseCancel',async()=>{
        await driver.editLabel(zone.zoneId,prefix+' [desktop edit 1]');
        await driver.editLabel(zone.zoneId,prefix+' [desktop edit 2]');
        const snapshot=await closeCancel('needsDecision');
        assert.equal(snapshot.editorFrame.cursor,initial.editorFrame.cursor+2);
        assert.ok(snapshot.editorFrame.selectedIds.includes(zone.zoneId));
        report.manualFrameHash=hash(snapshot.editorFrame);
      });
      const manual=await driver.snapshot();
      const operations=[{op:'edit_zone',zoneId:zone.zoneId,patch:{label:prefix+' [desktop Apply]'}}];
      const proposal=await driver.request('/__facility-recovery__/proposal',{operations,editorFrame:manual.editorFrame});
      await check('closeDuringPendingApply',async()=>{
        await held('apply',proposal);await closeCancel('blocked');await release();
        assert.equal((await driver.snapshot()).editorFrame.draftRevision,proposal.resultLayoutRevision);
      });
      await check('closeDuringPendingUndo',async()=>{
        await held('undo');await closeCancel('blocked');await release();
        assert.deepEqual((await driver.snapshot()).editorFrame,manual.editorFrame,'Undo did not restore both manual edits and their complete history');
      });
      if(driver.checkAssets)await check('loadedAssets',async()=>{report.assets=await driver.checkAssets();});
      await check('lostAcknowledgementDurableHandle',async()=>{
        const next=await driver.request('/__facility-recovery__/proposal',{operations,editorFrame:(await driver.snapshot()).editorFrame});
        const pending=await held('apply',next);
        const handles=await driver.adapter.listRecovery();
        const handle=handles.find(item=>item.handle.requestId===pending.pendingOperations[0].requestId);
        assert.ok(handle);assert.equal(handle.handle.transactionId,pending.pendingOperations[0].transactionId);
        const state={manualFrame:manual.editorFrame,pendingFrame:pending.editorFrame,handle,requestId:handle.handle.requestId,transactionId:handle.handle.transactionId};
        await fs.writeFile(privateState,JSON.stringify(state));
        report.recoveryHandle={key:handle.key,checkpointId:handle.checkpointId,requestId:state.requestId,transactionId:state.transactionId};
        report.pendingFrameHash=hash(pending.editorFrame);
      });
      report.exitPurpose='End this test process while its acknowledged-on-backend response is deliberately withheld. The next process restores the durable handle.';
    } else if(phase===2) {
      const state=JSON.parse(await fs.readFile(privateState,'utf8'));
      await check('restartKeepsSaveBlocked',async()=>{
        assert.equal((await driver.adapter.getSaveGate()).allowed,false);
        await assert.rejects(()=>driver.adapter.assertSaveAllowed(),{code:'facility_save_blocked'});
        const handles=await driver.adapter.listRecovery();
        const handle=handles.find(h=>h.key===state.handle.key);
        assert.ok(handle);assert.equal(handle.handle.transactionId,state.transactionId);
        const before=await driver.snapshot();
        assert.equal(before.startupRecoveryPending,true,'Restart must block the real session before restoring a transaction');
        assert.equal(before.pendingOperations.length,0,'This check must exercise the pre-restore gap');
        report.restartSaveGate={beforeRestore:await driver.assertSessionSaveBlocked(),startupRecoveryPending:true,pendingOperationsBeforeRestore:0};
        await driver.adapter.recover({key:handle.key,expectedCheckpointId:handle.checkpointId,expectedRendererGeneration:before.rendererGeneration,expectedStateSequence:before.stateSequence});
        assert.deepEqual((await driver.snapshot()).editorFrame,state.pendingFrame);
        assert.equal((await driver.adapter.getSaveGate()).allowed,false);
        await driver.assertSessionSaveBlocked();
      });
      await check('readOnlyReconciliationWithoutReplay',async()=>{
        const before=await driver.request('/__facility-recovery__/evidence');
        const result=await driver.adapter.clearOperation({requestId:state.requestId,transactionId:state.transactionId});
        assert.equal(result.outcome,'applied');
        assert.deepEqual((await driver.request('/__facility-recovery__/evidence')).calls,before.calls);
        assert.equal((await driver.adapter.getSaveGate()).allowed,true);
        assert.equal((await driver.snapshot()).startupRecoveryPending,false);
        assert.equal((await driver.snapshot()).pendingOperations.length,0);
      });
      await check('recoveredUndoRestoresExactManualHistory',async()=>{
        await held('undo');await closeCancel('blocked');await release();
        assert.deepEqual((await driver.snapshot()).editorFrame,state.manualFrame);
      });
      await check('closeWithoutSave',async()=>{
        const decision=await driver.prepareClose();assert.equal(decision.status,'needsDecision',JSON.stringify(decision));
        const result=await driver.adapter.commit({...decision,discardDocumentIds:[driver.binding.document.documentId]});
        assert.equal(result.status,'committed',JSON.stringify(result));
        if(driver.isClosed)assert.equal(await driver.isClosed(),true);
      });
    } else throw new Error('Phase must be 1 or 2');
    const evidence=await driver.request('/__facility-recovery__/evidence');
    assert.equal(evidence.deniedSaveCalls,0,'No Save request should be sent even to the isolated backend');
    assert.equal(Object.keys(evidence.calls).length,phase===1?8:10,'Expected actual Apply/Undo endpoint execution inventory');
    assert.ok(Object.values(evidence.calls).every(n=>n===1),'A transaction endpoint executed more than once');
    report.transactionCalls=evidence.calls;
    report.saveRequests=0;
    report.status='passed';report.finishedAt=new Date().toISOString();await saveReport();
    return report;
  }catch(error){report.status='failed';report.error={code:error.code,message:error.message,stack:error.stack};await saveReport();throw error;}
}
module.exports={runScenarios,until,hash};
