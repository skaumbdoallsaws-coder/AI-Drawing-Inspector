'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { loadRuntimeProfile } = require('../src/runtime-settings.cjs');
const { createManagedRuntime } = require('../src/runtime-supervisor.cjs');
const { createRuntimeLifecycle } = require('../src/runtime-lifecycle.cjs');
const { createSession } = require('../../static/facility_layout_session.js');
const { createHttpTransport } = require('../../static/facility_layout_transport.js');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = value => crypto.createHash('sha256').update(Buffer.isBuffer(value) ? value : JSON.stringify(value)).digest('hex');
async function main() {
  const [profileFile, python, output] = process.argv.slice(2);
  if (![profileFile,python,output].every(value => typeof value === 'string' && path.isAbsolute(value))) throw new Error('Usage: node runtime-backend-check.cjs ABS_PROFILE ABS_PYTHON ABS_OUTPUT');
  await fs.mkdir(output, { recursive: false });
  const profile = await loadRuntimeProfile(profileFile);
  if (!profile.acceptanceLayoutId) throw new Error('Marked isolated acceptance profile required');
  const proposal = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'runtime-proposal.json'), 'utf8'));
  const appRoot = path.resolve(__dirname, '../..');
  const marker = JSON.parse(await fs.readFile(path.join(profile.dataRoot,'facility-recovery-fixture.json'),'utf8'));
  const layoutPath = path.join(profile.dataRoot,'facility/layouts/local/site-local/layouts',profile.acceptanceLayoutId+'.json');
  const source = JSON.parse(await fs.readFile(path.join(appRoot,'desktop-checkpoint.json'),'utf8')).source;
  const sourceLayout = path.join(source,'.runtime/facility-layout/layouts/local/site-local/layouts',profile.acceptanceLayoutId+'.json');
  const before = { source: hash(await fs.readFile(sourceLayout)), isolated: hash(await fs.readFile(layoutPath)) };
  const report = { schemaVersion: 1, mode: 'real-session-protected-runtime-engine', status: 'running', nativeAcceptance: false,
    startedAt: new Date().toISOString(), checks: {}, before, generalEditing: false, researchBrowsing: false };
  const save = () => fs.writeFile(path.join(output,'check.json'),JSON.stringify(report,null,2));
  const supervisor = createManagedRuntime({ profile, python, appRoot, logRoot: path.join(output,'backend') });
  const sentinel = http.createServer((_request,response) => response.end('unrelated'));
  await new Promise(resolve => sentinel.listen(0,'127.0.0.1',resolve));
  let runtime, controller, facade, access = true, held = null, drop = null, pending = null, closed = false;
  try {
    runtime = await supervisor.start(); report.runtime = runtime; report.checks.privateReady = 'passed'; await save();
    for (const route of ['/', '/static/index.html', '/api/profiles', '/api/admin/memory/health','/api/desktop-shell/runtime']) {
      const response = await fetch(profile.origin+route,{redirect:'error'}); assert.equal(response.status,401,route); await response.arrayBuffer();
    }
    assert.equal((await fetch(profile.origin+'/api/desktop-shell/identity')).status,200);
    const external = await fetch(profile.origin+'/api/profiles',{headers:{'X-InspectorPro-Desktop-Token':supervisor.getCredential(),Origin:'https://untrusted.example'}});
    assert.equal(external.status,403); await external.arrayBuffer();
    report.checks.credentialBoundary = 'passed';
    const fetcher = async(url,init={}) => {
      if (!access) throw new TypeError('Transport interrupted for owned backend recovery');
      const response = await fetch(url,{...init,redirect:'error',headers:{...init.headers,'X-InspectorPro-Desktop-Token':supervisor.getCredential(),
        'X-InspectorPro-Session':runtime.owner.sessionId,...(controller?.getOperationRequestId()?{'X-InspectorPro-Desktop-Request-Id':controller.getOperationRequestId()}:{})}});
      return response;
    };
    const transport = createHttpTransport({ siteId:'site-local',layoutId:profile.acceptanceLayoutId,baseUrl:profile.origin,sessionId:runtime.owner.sessionId,fetch:fetcher });
    let holdKind = null;
    const wrapped={...transport};
    for(const [kind,name] of [['apply','acknowledgeDesignProposalApply'],['undo','acknowledgeDesignUndo']]) wrapped[name]=async input=>{
      const response=await transport[name](input);
      if(holdKind===kind){held={kind,transactionId:input.transactionId};await new Promise((_resolve,reject)=>drop=()=>reject(new TypeError('Held acknowledgment lost at managed restart')));}
      return response;
    };
    const session=createSession({...wrapped,loadDesignUndoRecovery:async()=>null,persistDesignUndoRecovery:async()=>{},clearDesignUndoRecovery:async()=>{}});
    session.load(await transport.reloadLayout());
    facade=session.installDesktopRecovery({startupRecoveryPending:true,allowSave:false,
      binding:{identity:runtime.identity,document:runtime.document,owner:runtime.owner},
      persistOperation:record=>controller.persist(record),clearOperation:record=>controller.clear(record)});
    controller=createRuntimeLifecycle({profile,supervisor,editor:facade,setBackendAccess:value=>{access=value;},lockInput:()=>{},
      closeConnections:async()=>{if(drop){const reject=drop;drop=null;reject();}if(pending)await pending;},
      commitWindow:async(_request,control,finalizeDiscard)=>{control.assertCurrent();if(finalizeDiscard)await finalizeDiscard();closed=true;},decideClose:async()=> 'cancel'});
    const initial=facade.snapshot();
    const attached=await controller.attach({schemaVersion:1,identity:runtime.identity,owner:runtime.owner,document:{...runtime.document,...initial.document},
      runtimeInstanceId:runtime.instanceId,rendererGeneration:initial.rendererGeneration,stateSequence:initial.stateSequence});
    assert.equal(attached.ready,true); assert.equal(attached.recoveryRequired,false); report.checks.actualSessionAttach='passed';
    session.select(proposal.zoneId); await session.editZoneLabel(proposal.zoneId,proposal.labels.edit1); await session.editZoneLabel(proposal.zoneId,proposal.labels.edit2);
    const manual=facade.snapshot(); report.manualFrameHash=hash(manual.editorFrame);
    assert.equal((await controller.close()).status,'cancelled'); assert.deepEqual(facade.snapshot(),manual); assert.equal(closed,false);
    report.checks.twoEditsCloseCancel='passed'; await save();
    for(const kind of ['apply','undo']) {
      holdKind=kind; held=null; let operationError=null;
      pending=(kind==='apply'?session.applyDesignProposal(proposal.proposal):session.undoDesignProposal()).catch(error=>{operationError={code:error.code,message:error.message};});
      const until=Date.now()+45000; while(!held&&Date.now()<until){if(operationError)throw Object.assign(new Error(operationError.message),operationError);await pause(25);}
      assert.ok(held,'Acknowledgment did not reach held state');
      const beforePending=facade.snapshot();
      assert.equal((await controller.close()).status,'cancelled'); assert.deepEqual(facade.snapshot(),beforePending);
      const result=await controller.restart(); assert.equal(result.status,'reconciled',JSON.stringify(result));
      runtime=supervisor.getState().runtime;
      assert.equal(result.exactDraftSelectionHistoryRetained,true); assert.equal(result.verifiedProposalMetadataAdopted,true);
      report[kind]={status:result.status,pendingFrameHash:hash(beforePending.editorFrame),afterFrameHash:hash(facade.snapshot().editorFrame),
        instanceId:runtime.instanceId,resolutions:result.resolutions.map(item=>({requestId:item.requestId,transactionId:item.transactionId,outcome:item.outcome}))};
      if(kind==='undo') assert.deepEqual(facade.snapshot().editorFrame,manual.editorFrame);
      assert.equal(session.getState().canSave,false); await assert.rejects(session.save(),error=>/desktop.*save|save.*desktop/.test(error.code||''));
      report.checks[kind+'PendingRestart']='passed'; await save();
    }
    assert.equal(await (await fetch('http://127.0.0.1:'+sentinel.address().port)).text(),'unrelated'); report.checks.unrelatedServerSurvival='passed';
    report.after={source:hash(await fs.readFile(sourceLayout)),isolated:hash(await fs.readFile(layoutPath))}; assert.deepEqual(report.after,before);
    report.checks.savedLayoutsUnchanged='passed'; report.status='passed';
  } catch(error) { report.status='failed';report.error={code:error.code||null,message:error.message,stack:error.stack}; }
  finally {
    report.cleanup=await supervisor.stop(); report.backends=supervisor.getEvidence();
    if(!report.cleanup.terminationConfirmed||!report.cleanup.stdioClosed||!report.cleanup.resourcesClosed){report.status='failed';report.cleanupFailed=true;}
    await new Promise(resolve=>sentinel.close(resolve)); report.finishedAt=new Date().toISOString(); await save();
  }
  console.log(JSON.stringify({status:report.status,checks:report.checks,error:report.error||null,output}));
  process.exitCode=report.status==='passed'?0:1;
}
main().catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});
