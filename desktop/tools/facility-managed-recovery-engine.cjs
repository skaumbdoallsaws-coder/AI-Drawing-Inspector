'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const {createSession}=require('../../static/facility_layout_session.js');
const {createHttpTransport}=require('../../static/facility_layout_transport.js');
const {createFacilityRecoveryAdapter}=require('../src/facility-recovery-adapter.cjs');
const {createCheckpointDiagnosticSink}=require('./recovery-checkpoint-diagnostics.cjs');
const {runManagedScenarios}=require('./facility-managed-recovery-scenarios.cjs');

async function main(){
  if(process.env.INSPECTORPRO_FACILITY_RECOVERY_HARNESS!=='1'||process.env.INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS!=='1')throw new Error('Explicit managed recovery harness required');
  const config=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
  const token=(await fs.readFile(config.tokenFile,'utf8')).trim();
  let operation=null;
  const fetcher=(url,options={})=>fetch(url,{...options,redirect:'error',headers:{...options.headers,'X-InspectorPro-Recovery-Test':token,...(operation?{'X-InspectorPro-Recovery-Request':operation.requestId}:{})}});
  const request=async(endpoint,body)=>{
    const response=await fetcher(config.origin+endpoint,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw Object.assign(new Error(result.error?.message||JSON.stringify(result)),{code:result.error?.code});return result;
  };
  const binding=await request('/__facility-recovery__/identity');
  const transport=createHttpTransport({siteId:binding.document.siteId,layoutId:binding.document.documentId,baseUrl:config.origin,sessionId:binding.owner.sessionId,fetch:fetcher});
  let pauseName=null,paused=null,releaseFn=null,dropFn=null,pending=null,operationError=null,beforeAck=false;
  const wrapped={...transport};
  for(const name of ['acknowledgeDesignProposalApply','acknowledgeDesignUndo'])wrapped[name]=async value=>{
    async function hold(){
      paused={name,transactionId:value.transactionId,beforeAcknowledgement:beforeAck};
      try {await new Promise((resolve,reject)=>{releaseFn=resolve;dropFn=reject;});}
      finally{paused=null;pauseName=null;releaseFn=null;dropFn=null;}
    }
    if(pauseName===name&&beforeAck)await hold();
    const result=await transport[name](value);
    if(pauseName===name)await hold();
    return result;
  };
  const session=createSession({...wrapped,loadDesignUndoRecovery:async()=>null,persistDesignUndoRecovery:async()=>{},clearDesignUndoRecovery:async()=>{}});
  session.load(await transport.reloadLayout());
  let adapter,driver;const lookups=[];
  const editor=session.installDesktopRecovery({startupRecoveryPending:true,
    persistOperation:async record=>{const receipt=await adapter.persistOperation(record);operation={requestId:record.requestId};return receipt;},
    clearOperation:record=>adapter.clearOperation(record)});
  adapter=await createFacilityRecoveryAdapter({authorizedIsolatedHarness:true,...binding,editor,recoveryDirectory:path.join(config.dataRoot,'desktop-recovery'),
    onRecoveryDiagnostic:createCheckpointDiagnosticSink(config.output),
    lookupOperation:async value=>{const clientSaveGate=await driver.assertSessionSaveBlocked();const result=await request('/__facility-recovery__/transaction',value);lookups.push({...result,clientSaveGate});if(['lease_expired','ownership_conflict'].includes(result.status))throw Object.assign(new Error('Explicit recovery required: '+result.status),{code:result.status});return result;},
    commitLifecycle:async()=>{throw new Error('Managed restart must not commit window close');},timeoutMs:15000,lookupTimeoutMs:15000});
  driver={mode:'engine',binding,adapter,editor,lookups,request,snapshot:()=>editor.snapshot(),
    editLabel:async(id,label)=>{session.select(id);await session.editZoneLabel(id,label);},
    begin:async(kind,reference,beforeAcknowledgement=false)=>{pauseName=kind==='apply'?'acknowledgeDesignProposalApply':'acknowledgeDesignUndo';beforeAck=beforeAcknowledgement;operationError=null;pending=(kind==='apply'?session.applyDesignProposal(reference):session.undoDesignProposal()).catch(e=>{operationError={code:e.code,message:e.message};});},
    paused:()=>paused,release:async()=>{if(!releaseFn)throw new Error('No held acknowledgment');releaseFn();},
    dropHeldAcknowledgement:async()=>{if(!dropFn)throw new Error('No held acknowledgment');dropFn(Object.assign(new Error('Managed backend restart interrupted the held acknowledgment'),{code:'facility_transport_acknowledgement_lost'}));},
    settled:()=>pending,operationError:()=>operationError,
    assertSessionSaveBlocked:async()=>{assertBlocked();try{await session.save();throw new Error('Session unexpectedly allowed Save');}catch(e){if(!/busy|recovery|frozen|unresolved/i.test(e.message))throw e;return {canSave:false,rejectionCode:e.code,uiChecked:false};}},
  };
  function assertBlocked(){if(session.getState().canSave!==false)throw new Error('Session Save capability is enabled');}
  return runManagedScenarios(driver,config);
}
main().then(report=>{process.stdout.write(JSON.stringify({status:report.status,case:report.case,checks:report.checks})+'\n');process.exit(0);})
  .catch(error=>{process.stderr.write((error.stack||error.message)+'\n');process.exit(1);});
