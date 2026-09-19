'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const {createSession}=require('../../static/facility_layout_session.js');
const {createHttpTransport}=require('../../static/facility_layout_transport.js');
const {createFacilityRecoveryAdapter}=require('../src/facility-recovery-adapter.cjs');
const {runScenarios}=require('./facility-recovery-scenarios.cjs');
async function main(){
  if(process.env.INSPECTORPRO_FACILITY_RECOVERY_HARNESS!=='1')throw new Error('Explicit isolated test harness required');
  const config=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
  const token=(await fs.readFile(config.tokenFile,'utf8')).trim();
  let operation=null;
  const fetcher=(url,options={})=>fetch(url,{...options,headers:{...options.headers,'X-InspectorPro-Recovery-Test':token,...(operation?{'X-InspectorPro-Recovery-Request':operation.requestId}:{})}});
  const request=async(endpoint,body)=>{const response=await fetcher(config.origin+endpoint,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Object.assign(new Error(result.error?.message||JSON.stringify(result)),{code:result.error?.code});return result;};
  const binding=await request('/__facility-recovery__/identity');
  const transport=createHttpTransport({siteId:binding.document.siteId,layoutId:binding.document.documentId,baseUrl:config.origin,sessionId:binding.owner.sessionId,fetch:fetcher});
  let pauseName=null,paused=null,releaseFn=null,pending=null,operationError=null,closed=false;
  const wrapped={...transport};
  for(const name of ['acknowledgeDesignProposalApply','acknowledgeDesignUndo'])wrapped[name]=async value=>{
    const result=await transport[name](value);
    if(pauseName===name){paused={name,transactionId:value.transactionId};await new Promise(resolve=>releaseFn=resolve);paused=null;pauseName=null;}
    return result;
  };
  const session=createSession({...wrapped,loadDesignUndoRecovery:async()=>null,persistDesignUndoRecovery:async()=>{},clearDesignUndoRecovery:async()=>{}});
  session.load(await transport.reloadLayout());
  let adapter;
  const facade=session.installDesktopRecovery({startupRecoveryPending:true,persistOperation:async record=>{const receipt=await adapter.persistOperation(record);operation={requestId:record.requestId};return receipt;},clearOperation:record=>adapter.clearOperation(record)});
  adapter=await createFacilityRecoveryAdapter({authorizedIsolatedHarness:true,...binding,editor:facade,recoveryDirectory:path.join(config.dataRoot,'desktop-recovery'),lookupOperation:value=>request('/__facility-recovery__/transaction',value),commitLifecycle:async()=>{closed=true;},timeoutMs:15000,lookupTimeoutMs:15000});
  const driver={mode:'real-session-real-backend-two-process-harness',binding,adapter,request,snapshot:()=>facade.snapshot(),
    prepareClose:()=>adapter.prepare('close'),isClosed:()=>closed,
    editLabel:async(id,label)=>{session.select(id);await session.editZoneLabel(id,label);},
    begin:async(kind,reference)=>{pauseName=kind==='apply'?'acknowledgeDesignProposalApply':'acknowledgeDesignUndo';operationError=null;pending=(kind==='apply'?session.applyDesignProposal(reference):session.undoDesignProposal()).catch(e=>{operationError={code:e.code,message:e.message};});},
    paused:()=>paused,release:async()=>{const fn=releaseFn;releaseFn=null;if(!fn)throw new Error('No held acknowledgement');fn();},settled:()=>pending,operationError:()=>operationError,
    assertSessionSaveBlocked:async()=>{if(session.getState().canSave!==false)throw new Error('Session Save capability is enabled');try{await session.save();throw new Error('Session unexpectedly allowed Save');}catch(e){if(!['session_busy','facility_desktop_recovery_unresolved','facility_desktop_frozen','facility_desktop_save_blocked'].includes(e.code)&& !/busy|recovery|frozen|unresolved/i.test(e.message))throw e;return {canSave:false,rejectionCode:e.code,uiChecked:false};}},
  };
  return runScenarios(driver,config);
}
main().then(report=>{process.stdout.write(JSON.stringify({status:report.status,phase:report.phase,checks:report.checks})+'\n');process.exit(0);}).catch(error=>{process.stderr.write((error.stack||error.message)+'\n');process.exit(1);});
