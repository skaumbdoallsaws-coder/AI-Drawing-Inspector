'use strict';
// Usage: node tests/smoke_documentation_editor_desktop.cjs ABS_ELECTRON ABS_PROFILE ABS_PYTHON ABS_EVIDENCE
// Run from an isolated prepare-snapshot.py tree, never the working/live checkout.
const fs=require('node:fs');
const path=require('node:path');
const net=require('node:net');
const C=require('../desktop/tools/documentation-editor-contract.cjs');
const {runOwnedChild}=require('../desktop/tools/owned-child-runner.cjs');
const ROOT=path.resolve(__dirname,'..');
const REQUIRED={edit:['application_edit','rich_entry_points','rich_saved','ribbon_undo','ribbon_redo','keyboard_undo','keyboard_redo','cited_edit','operations_heading','saved_close_requested'],
  restart:['application_restart','restart_disk_exact','restart_undo','restart_redo','dirty_close'],
  export:['application_export','review','review-docx','user_confirmation','customer-pdf','customer-docx','export_saved_close_requested']};
function reportShape(value,stage) {
  return value?.schemaVersion===1 && value.phase==='P5b-1' && value.stage===stage
    && ['passed','failed'].includes(value.status) && Array.isArray(value.checks) && value.checks.length>0
    && value.checks.every(c=>typeof c.name==='string' && typeof c.passed==='boolean' && c.detail && typeof c.detail==='object')
    && Array.isArray(value.notRun) && Array.isArray(value.requests) && Array.isArray(value.artifacts)
    && Array.isArray(value.windowOpens) && Array.isArray(value.blockedNavigations) && Array.isArray(value.screenshots)
    && new Set(value.checks.map(c=>c.name)).size===value.checks.length;
}
async function freePort(origin) {
  const url=new URL(origin);
  await new Promise((resolve,reject)=>{
    const server=net.createServer();server.once('error',()=>reject(Error('The disposable port is in use; never attach to an existing application')));
    server.listen({host:'127.0.0.1',port:+url.port,exclusive:true},()=>server.close(resolve));
  });
}
async function main(args=process.argv.slice(2)) {
  if(args.length!==4)throw Error('Use ABS_ELECTRON ABS_PROFILE ABS_PYTHON ABS_EVIDENCE');
  const [electron,profileFile,python,output]=args;
  const config=C.validateRun({root:ROOT,electron,profileFile,python,output});
  const slow=Number(process.env.DOC_SMOKE_SLOW || 1);
  if(!Number.isFinite(slow)||slow<1||slow>10)throw Error('DOC_SMOKE_SLOW must be 1..10');
  const [major,minor]=process.versions.node.split('.').map(Number);
  if(major<22 || major===22 && minor<12)throw Error('Node >= 22.12 is required');
  const reportPath=path.join(output,'report.json'), started=Date.now(), deadline=started+15*60*1000;
  if(fs.existsSync(reportPath) || fs.existsSync(path.join(output,'edit.json')))throw Error('Use a newly prepared disposable profile; this run already has evidence');
  fs.mkdirSync(output,{recursive:true});await freePort(config.profile.origin);
  const report=C.newReport(config,'aggregate');report.waitFactor=slow;report.maximumRunMs=15*60*1000;
  report.releaseGateComplete=false;report.stages=[];report.processes=[];report.nativeDialogs=[];report.editAttempts=[];
  report.fixture={assemblyNumber:config.marker.assemblyNumber,inputRoot:config.marker.inputRoot,inputs:config.marker.inputs,stores:config.marker.stores};
  const save=()=>C.writeReport(reportPath,report);
  const env=C.environment(config);env.DOC_SMOKE_SLOW=String(slow);
  const helper=path.join(ROOT,'desktop/tools/documentation-editor-evidence.py');
  save();
  try {
    const depFile=path.join(output,'dependencies.json');
    const probe=await runOwnedChild({executable:python,args:[helper,'dependencies','--out',depFile],cwd:ROOT,env,logPath:path.join(output,'dependencies.log'),timeoutMs:60000});
    report.processes.push({stage:'dependencies',...probe});
    if(!probe.ok || !fs.existsSync(depFile))throw Error('The selected Python cannot produce dependency evidence');
    report.pythonRuntime=C.json(depFile);
    C.check(report,'python_dependencies',report.pythonRuntime.complete,{file:depFile,...report.pythonRuntime});save();
    if(!report.pythonRuntime.complete)throw Error('Missing application dependencies; no installation was attempted');
    for(const stage of ['edit','restart','export']) {
      const remaining=deadline-Date.now();if(remaining<45000)throw Error('The 15-minute whole-run deadline was reached');
      await freePort(config.profile.origin);
      const cleanupPath=path.join(config.profile.dataRoot,'last-application-run.json');
      const previous=fs.existsSync(cleanupPath)?C.sha(fs.readFileSync(cleanupPath)):null;
      const child=await runOwnedChild({executable:electron,args:[path.join(ROOT,'desktop/tools/documentation-editor-native-entry.cjs'),
        '--profile-file',profileFile,'--python',python,'--acceptance-output',output],cwd:ROOT,
        env:{...env,DOC_DESKTOP_STAGE:stage},logPath:path.join(output,stage+'-driver.log'),
        timeoutMs:Math.min(550000,remaining-45000),terminationGraceMs:5000,forceKillGraceMs:5000,drainGraceMs:5000});
      report.processes.push({stage,...child});
      C.check(report,stage+'_owned_exit',child.ok && child.terminationConfirmed && child.stdioClosed,child);
      const stagePath=path.join(output,stage+'.json');
      const value=fs.existsSync(stagePath)?C.json(stagePath):null;
      const shape=reportShape(value,stage);C.check(report,stage+'_report_shape',shape,{file:stagePath});
      let clean=false;
      if(fs.existsSync(cleanupPath) && C.sha(fs.readFileSync(cleanupPath))!==previous) {
        const cleanup=C.json(cleanupPath), target=path.join(output,stage+'-cleanup.json');C.writeReport(target,cleanup);
        clean=cleanup.cleanup?.terminationConfirmed===true && cleanup.cleanup?.stdioClosed===true
          && cleanup.cleanup?.resourcesClosed===true && !cleanup.cleanupErrors?.length;
        C.check(report,stage+'_backend_exit',clean,{file:target,cleanup:cleanup.cleanup,errors:cleanup.cleanupErrors || []});
      } else C.check(report,stage+'_backend_exit',false,{reason:'No fresh shutdown evidence. Owned backend termination is unconfirmed; no unrelated process is stopped.'});
      if(shape) {
        report.stages.push({stage,path:stagePath,status:value.status});
        for(const check of value.checks)C.check(report,stage+'.'+check.name,check.passed,check.detail);
        for(const name of REQUIRED[stage])if(!value.checks.some(c=>c.name===name))C.check(report,stage+'.missing_'+name,false,{reason:'Scenario stopped before this check'});
        report.notRun.push(...value.notRun);report.requests.push(...value.requests);report.windowOpens.push(...value.windowOpens);report.blockedNavigations.push(...value.blockedNavigations);report.artifacts.push(...value.artifacts);report.screenshots.push(...value.screenshots);
        report.nativeDialogs.push(...(value.nativeDialogs || []).map(row=>({stage,...row})));report.editAttempts.push(...(value.editAttempts || []).map(row=>({stage,...row})));
      }
      save();
      if(!child.terminationConfirmed || !clean || !shape || (stage==='edit'&&!fs.existsSync(path.join(output,'continuation.json'))))break;
    }
    for(const stage of Object.keys(REQUIRED))if(!report.stages.some(s=>s.stage===stage))C.check(report,'missing_stage_'+stage,false,{reason:'Prerequisite or cleanup failed'});
    // Every native dialog of the run is answered by this run's own helper on the button the scenario armed. The
    // helper's result file is written before the application goes on, so it is read here when the stage report
    // closed first. A dialog nobody armed, or one answered by someone at the keyboard, fails the run.
    for(const row of report.nativeDialogs)if(row.answer && !row.answer.result && row.answer.file && fs.existsSync(row.answer.file))row.answer.result=C.json(row.answer.file);
    const unowned=report.nativeDialogs.filter(row=>!(row.answer?.result?.pressed===true && row.answer.result.button===row.answer.button && row.buttons[row.response]===row.answer.button));
    C.check(report,'native_dialogs_answered_by_helper',unowned.length===0,{dialogs:report.nativeDialogs.length,unowned:unowned.map(row=>({stage:row.stage,title:row.title,detail:row.detail,buttons:row.buttons,response:row.response,answer:row.answer}))});
    // Only the two seeded stores are mutable inputs. All copied engineering inputs stay unchanged.
    const changed=config.marker.inputs.filter(item=>!item.seed && C.sha(fs.readFileSync(item.destination))!==item.sha256);
    C.check(report,'engineering_inputs_unchanged',changed.length===0,{changed:changed.map(i=>i.source)});
  } catch(error) {C.check(report,'runner_failure',false,{code:error.code || null,message:error.message,stack:error.stack});}
  report.elapsedMs=Date.now()-started;C.check(report,'within_15_minutes',report.elapsedMs<=15*60*1000,{elapsedMs:report.elapsedMs});
  C.finish(report);save();process.stdout.write(report.status+' '+reportPath+'\n');return report.status==='passed'?0:1;
}
if(require.main===module)main().then(code=>{process.exitCode=code;},error=>{process.stderr.write(error.message+'\n');process.exitCode=1;});
module.exports={main,freePort,reportShape,REQUIRED};
