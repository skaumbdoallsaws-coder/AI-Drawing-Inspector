'use strict';
// Loaded ONLY by Electron. The application entry, preload and policies are real.
const electron=require('electron');
const fs=require('node:fs');
const path=require('node:path');
const C=require('./documentation-editor-contract.cjs');
const {runOwnedChild}=require('./owned-child-runner.cjs');
const {parseRuntimeOptions}=require('../src/runtime-settings.cjs');
const root=path.resolve(__dirname,'../..');
const options=parseRuntimeOptions(process.argv.slice(2));
const config=C.validateRun({root,electron:process.execPath,python:options.python,profileFile:options.profileFile,output:options.acceptanceOutput});
const stage=process.env.DOC_DESKTOP_STAGE;
if (!['edit','restart','export'].includes(stage)) throw Error('Invalid desktop smoke stage');
const slow=Number(process.env.DOC_SMOKE_SLOW || 1);
if (!Number.isFinite(slow) || slow<1 || slow>10) throw Error('DOC_SMOKE_SLOW must be 1..10');
const T=ms=>Math.round(ms*slow), deadlines={control:T(20000),load:T(90000),write:T(90000),capture:T(240000),export:T(180000)};
const report=C.newReport(config,stage), file=path.join(config.output,stage+'.json');
report.timeouts=deadlines; report.waitFactor=slow; report.editAttempts=[]; report.nativeDialogs=[];
report.electron=process.versions.electron; report.node=process.versions.node;
const flush=()=>C.writeReport(file,report);
const record=(name,passed,detail={})=>{C.check(report,name,passed,detail);flush();};
const streams=new Map(), pendingBodies=new Set();
const originalFetch=global.fetch;
global.fetch=async function(input,init) {
  const url=typeof input==='string'?input:input.url || String(input);
  const row={transport:'main-fetch',url,method:init?.method || 'GET'}; report.requests.push(row);
  try { const response=await originalFetch.call(this,input,init); row.status=response.status; return response; }
  catch(error) {row.error=error.code || error.name;throw error;}
};
// Attach before the first load; never replace the shell's webRequest handlers.
electron.app.on('web-contents-created',(_event,contents)=>{
  contents.on('console-message',(...args)=>{
    const details=args.find(v=>v && typeof v==='object' && 'level' in v && 'message' in v)
      || {level:args[1],message:args[2],lineNumber:args[3],sourceId:args[4]};
    if(details.level==='error' || details.level===3) report.consoleErrors.push({message:details.message,sourceId:details.sourceId,line:details.lineNumber,contents:contents.id});
  });
  for(const name of ['will-navigate','will-redirect','will-frame-navigate']) contents.on(name,(event,details)=>{
    const url=typeof details==='string'?details:details?.url || event.url;
    queueMicrotask(()=>{if(event.defaultPrevented)report.blockedNavigations.push({event:name,url,contents:contents.id});});
  });
  contents.on('render-process-gone',(_e,details)=>report.failedRequests.push({type:'renderer-gone',contents:contents.id,...details}));
  try {
    contents.debugger.attach('1.3');
    contents.debugger.on('message',(_e,method,p)=>{
      const id=contents.id+':'+p.requestId;
      if(method==='Page.windowOpen') report.windowOpens.push({url:p.url,userGesture:p.userGesture,contents:contents.id});
      if(method==='Network.requestWillBeSent') {
        const row={transport:'renderer',id,url:p.request.url,method:p.request.method,resourceType:p.type};
        streams.set(id,row);report.requests.push(row);
      } else if(method==='Network.responseReceived') {
        const row=streams.get(id);if(row){row.status=p.response.status;row.mimeType=p.response.mimeType;}
      } else if(method==='Network.loadingFailed') {
        const row=streams.get(id);if(row){row.error=p.errorText;report.failedRequests.push({...row});}
      } else if(method==='Network.loadingFinished') {
        const row=streams.get(id);
        if(row?.method==='POST' && /\/api\/(parts-manual|operations-manual)\/MMLE-50D\/pdf(?:\?|$)/.test(row.url)) {
          const job=contents.debugger.sendCommand('Network.getResponseBody',{requestId:p.requestId}).then(body=>{
            row.result=JSON.parse(body.base64Encoded?Buffer.from(body.body,'base64').toString():body.body);
          }).catch(error=>{row.bodyError=error.message;}).finally(()=>pendingBodies.delete(job));pendingBodies.add(job);
        }
      }
    });
    void Promise.all([contents.debugger.sendCommand('Network.enable'),contents.debugger.sendCommand('Page.enable')]).catch(error=>record('network_observer_'+contents.id,false,{error:error.message}));
  } catch(error) {record('network_observer_'+contents.id,false,{error:error.message});}
});
// Every native message box is recorded with its wording and its real result. One is answered only when the
// scenario armed an answer for it, and the answer is a press on the named button of this process's actual dialog
// (documentation-editor-evidence.py press-dialog). A dialog nobody armed is left alone and runs into its deadline.
let armedDialog=null;
const originalDialog=electron.dialog.showMessageBox;
electron.dialog.showMessageBox=function(...args){
  const options=args.find(a=>a && Array.isArray(a.buttons)) || {};
  const row={title:options.title || null,message:options.message || null,detail:options.detail || null,buttons:options.buttons || [],shownAt:new Date().toISOString(),answer:null};
  report.nativeDialogs.push(row);
  const result=originalDialog.apply(this,args); // Keep the actual native dialog and its decision.
  if(armedDialog && options.title===armedDialog.title && row.buttons.includes(armedDialog.button)){
    const answer=armedDialog, out=path.join(config.output,stage+'-native-dialog-'+report.nativeDialogs.length+'.json');armedDialog=null;
    row.answer={button:answer.button,reason:answer.reason,file:out};
    answer.job=runOwnedChild({executable:config.python,args:[path.join(root,'desktop/tools/documentation-editor-evidence.py'),'press-dialog','--pid',String(process.pid),'--title',answer.title,'--button',answer.button,'--timeout',String(T(20000)/1000),'--out',out],cwd:root,env:C.environment(config),logPath:path.join(config.output,'native-dialog.log'),timeoutMs:Math.min(T(25000),600000)})
      .then(child=>{row.answer.helperOk=child.ok;row.answer.result=fs.existsSync(out)?C.json(out):null;return row.answer;});
  }
  return Promise.resolve(result).then(value=>{row.response=value?.response ?? null;row.resolvedAt=new Date().toISOString();try{flush();}catch(_){/* evidence only */}return value;});
};
const PARTS='illustrated_parts_manual', OPS='operations_and_maintenance_manual';
const heading='Desktop gate heading', surface='#documentationPublicationSurface';
const state='window.__compareDbg.state';
const visible='e => !!e && !!e.getClientRects().length && getComputedStyle(e).visibility !== "hidden"';
function withoutIds(value) {
  if(Array.isArray(value))return value.map(withoutIds);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>k!=='id').map(([k,v])=>[k,withoutIds(v)]));
  return value;
}
async function run(context) {
  const {window,network,runtime,change,observe,ensureBrowser}=context, wc=window.webContents;
  const evaluate=source=>wc.executeJavaScript(source,true);
  async function until(name,probe,timeout=deadlines.control) {
    const start=Date.now();let last;
    while(Date.now()-start<timeout) {
      if(window.isDestroyed())throw Error(name+': application closed');
      last=await probe();if(last)return last;
      await new Promise(resolve=>setTimeout(resolve,80));
    }
    throw Error(name+' timed out; last='+JSON.stringify(last));
  }
  const wait=(name,expr,timeout)=>until(name,()=>evaluate(expr),timeout);
  const settled=()=>wait('workspace settled','!!document.querySelector("#documentationWorkspace") && !document.querySelector("#documentationWorkspace.busy") && !!window.__compareDbg?.state.partsManualDocumentation?.document',deadlines.write);
  const frame=()=>evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  async function clickExpression(expr,count=1) {
    window.focus();wc.focus();
    for(let press=1;press<=count;press++) {
      const point=await until('click target',()=>evaluate('(()=>{const e='+expr+';if(!('+visible+')(e)||e.disabled)return null;e.scrollIntoView({block:"nearest",inline:"nearest"});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()'));
      wc.sendInputEvent({type:'mouseMove',x:Math.round(point.x),y:Math.round(point.y)});
      wc.sendInputEvent({type:'mouseDown',x:Math.round(point.x),y:Math.round(point.y),button:'left',clickCount:press});
      wc.sendInputEvent({type:'mouseUp',x:Math.round(point.x),y:Math.round(point.y),button:'left',clickCount:press});
      await frame();
    }
  }
  const click=(selector,count=1)=>clickExpression('document.querySelector('+JSON.stringify(selector)+')',count);
  const named=(scope,name)=>clickExpression('[...document.querySelectorAll('+JSON.stringify(scope+' button')+')].find(e=>('+visible+')(e)&&(e.textContent.trim()==='+JSON.stringify(name)+'||e.getAttribute("aria-label")==='+JSON.stringify(name)+'))');
  async function key(keyCode,modifiers=[]) {
    wc.sendInputEvent({type:'keyDown',keyCode,modifiers});wc.sendInputEvent({type:'keyUp',keyCode,modifiers});await frame();
  }
  async function type(text) {
    for(const char of text) {wc.sendInputEvent({type:'keyDown',keyCode:char});wc.sendInputEvent({type:'char',keyCode:char});wc.sendInputEvent({type:'keyUp',keyCode:char});}
    await frame();
  }
  async function fill(selector,text) {await click(selector);await key('A',['control']);await type(text);await key('Tab');}
  // A native list: open it with a press, walk to the option with the arrow keys and confirm with Enter.
  async function choose(selector,value) {
    const index=await evaluate('[...(document.querySelector('+JSON.stringify(selector)+')?.options || [])].findIndex(o=>o.value==='+JSON.stringify(value)+')');
    if(index<0)throw Error('No option '+value+' in '+selector);
    await click(selector);await key('Home');
    for(let step=0;step<index;step++)await key('Down');
    await key('Return');
    await wait('list choice '+value,'document.querySelector('+JSON.stringify(selector)+')?.value==='+JSON.stringify(value));
  }
  // Type the heading text, then make its block a level-2 heading through the editor's own Style list. (The
  // Ctrl+Alt+2 shortcut is not used: on Windows Ctrl+Alt is AltGr and the key event never reached the editor.)
  async function typeHeading() {
    await type(heading);await choose('[data-rich-control="style"]','h2');
    await wait('heading applied','DocumentationRichText.active?.editor.isActive("heading",{level:2})===true');
  }
  async function ribbon(selector) {
    if(await evaluate('('+visible+')(document.querySelector('+JSON.stringify(selector)+'))')) {await click(selector);return 'ribbon';}
    if(await evaluate('document.querySelector('+JSON.stringify(selector)+')?.classList.contains("documentation-ribbon-menu-trigger")'))return 'more-items';
    await wait('enabled ribbon command','!!document.querySelector('+JSON.stringify(selector)+') && !document.querySelector('+JSON.stringify(selector)+').disabled');
    if(!await evaluate('document.querySelector("#documentationOverflowMenuRibbon")?.getAttribute("aria-expanded")==="true"'))await click('#documentationOverflowMenuRibbon');
    await wait('More open','document.querySelector("#documentationOverflowMenuRibbon")?.getAttribute("aria-expanded")==="true"');
    await clickExpression('[...document.querySelectorAll(".documentation-ribbon-overflow-menu .documentation-menu-item")].find(e=>e._documentationSource===document.querySelector('+JSON.stringify(selector)+')&&('+visible+')(e))');
    return 'more';
  }
  const payload=()=>evaluate(state+'.partsManualDocumentation');
  function differences(a,b,at='',out=[]) {
    if(out.length>=20)return out;
    if(a && b && typeof a==='object' && typeof b==='object' && Array.isArray(a)===Array.isArray(b)) {
      for(const k of new Set([...Object.keys(a),...Object.keys(b)]))differences(a[k],b[k],at+'/'+k,out);
    } else if(C.canonical(a)!==C.canonical(b)) {
      out.push({path:at,page:a===undefined?'(absent)':JSON.stringify(a).slice(0,160),store:b===undefined?'(absent)':JSON.stringify(b).slice(0,160)});
    }
    return out;
  }
  // Reading a scene adds an identity map `confirmationAliases` ({id: id}) to the metadata of a confirmed field
  // (ai_inspector/documentation/identity.py); the store receives it with the next write. It changes no value and
  // no hash (provenance.py falls back to the same keys). Only such identity maps are left out of the page/store
  // comparison, and they are counted; a map that renames anything still counts as a difference.
  function withoutIdentityAliases(value,counter) {
    if(Array.isArray(value))return value.map(item=>withoutIdentityAliases(item,counter));
    if(!value || typeof value!=='object')return value;
    return Object.fromEntries(Object.entries(value).filter(([key,item])=>{
      const identity=key==='confirmationAliases' && item && typeof item==='object' && Object.entries(item).every(([a,b])=>a===b);
      if(identity)counter.count++;
      return !identity;
    }).map(([key,item])=>[key,withoutIdentityAliases(item,counter)]));
  }
  async function evidence(kind,name,before=null) {
    // The page takes the server's answer a moment after the store has it. Give the page a bounded time to show
    // the stored scene, and keep exactly what still differs.
    let disk, ui, page, store, shown, stored;const started=Date.now();
    const read=async()=>{
      disk=C.diskScene(config,kind);ui=await payload();page={count:0};store={count:0};
      shown=withoutIdentityAliases(ui.scene,page);stored=withoutIdentityAliases(disk.scene,store);
      return C.canonical(shown)===C.canonical(stored);
    };
    let equal=await read();
    while(!equal && Date.now()-started<T(5000)) {await new Promise(resolve=>setTimeout(resolve,200));equal=await read();}
    const snapshot=path.join(config.output,name+'-scene.json');C.writeReport(snapshot,disk.scene);
    return {documentType:kind,pageId:await evaluate(state+'.partsManualDocumentationPageId'),objectId:await evaluate(state+'.partsManualDocumentationSelection?.targetId || null'),
      revisionBefore:before?.revision ?? null,revisionAfter:disk.revision,sceneSha256:disk.sha256,persistedState:snapshot,scene:disk.scene,
      uiSceneEqual:equal,uiSceneWaitMs:Date.now()-started,uiSceneDifferences:equal?[]:differences(shown,stored),
      readTimeIdentityAliasMaps:{page:page.count,store:store.count}};
  }
  const shot=async name=>{const target=path.join(config.output,name+'.png');fs.writeFileSync(target,(await wc.capturePage()).toPNG());report.screenshots.push(target);flush();};
  async function navigate(pageId) {
    await clickExpression('[...document.querySelectorAll(".documentation-page-item")].find(e=>e.dataset.pageId==='+JSON.stringify(pageId)+')');
    await wait('page selected',state+'.partsManualDocumentationPageId==='+JSON.stringify(pageId)+' && !document.querySelector("#documentationWorkspace.busy")',deadlines.load);
  }
  async function open(kind=PARTS) {
    if(!await evaluate('!!document.querySelector("#documentationWorkspace")')) {
      await click('.tab[data-tab="training"]');await click('#trainingTypeRibbonTrigger');await click('#trainingTypeRibbonOption-documentation');await settled();
    }
    if(await evaluate(state+'.documentationDocumentType')!==kind) {
      await click('#documentationTypeRibbonTrigger');await click('#documentationTypeRibbonOption-'+kind);
      await wait('document type',state+'.documentationDocumentType==='+JSON.stringify(kind)+' && '+state+'.partsManualDocumentation?.document?.documentType==='+JSON.stringify(kind)+' && !document.querySelector("#documentationWorkspace.busy")',deadlines.load);
    }
    if(!await evaluate('('+state+'.partsManualDocumentation?.document?.pages || []).length && document.querySelector("#documentationPublicationSurface")?.innerText.trim().length')) {await ribbon('#documentationRefreshRibbon');await settled();}
    await wait('publication drawn','document.querySelector("#documentationPublicationSurface")?.innerText.trim().length>0',deadlines.load);
  }
  const objectSelector=id=>surface+' [data-documentation-object-id="'+id+'"]';
  // The workspace starts a text edit on two presses within half a second, timed by event.timeStamp, because every
  // press redraws the page and the browser never sees a double-click (_documentationTextPressed and
  // _documentationRichObjectPressed). Waiting for the redraw between the presses pushes them apart on a busy
  // machine, so both presses are queued back to back, the way a person's double press arrives, and repeated when
  // one lands during a redraw (at most three times, as tests/smoke_documentation_editor.py does). Attempts are evidence.
  async function doublePress(expr,started,name) {
    for(let attempt=1;attempt<=3;attempt++) {
      await wait('workspace idle','!document.querySelector("#documentationWorkspace.busy")',deadlines.write);
      window.focus();wc.focus();
      const point=await until('press target',()=>evaluate('(()=>{const e='+expr+';if(!('+visible+')(e))return null;e.scrollIntoView({block:"nearest",inline:"nearest"});const r=e.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()'));
      wc.sendInputEvent({type:'mouseMove',x:point.x,y:point.y});
      for(let press=0;press<2;press++) {
        wc.sendInputEvent({type:'mouseDown',x:point.x,y:point.y,button:'left',clickCount:1});
        wc.sendInputEvent({type:'mouseUp',x:point.x,y:point.y,button:'left',clickCount:1});
      }
      try {await wait(name,started,T(5000));report.editAttempts.push({name,attempt});flush();return;}
      catch(error) {
        if(attempt===3)throw Error(name+' did not start after three double presses');
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    }
  }
  async function editObject(id) {await doublePress('document.querySelector('+JSON.stringify(objectSelector(id))+')','!!window.DocumentationRichText?.active','rich editor mounted');}
  async function done() {await click('[data-rich-action="done"]');await wait('draft saved','!window.DocumentationRichText?.active && !document.querySelector("#documentationWorkspace.busy")',deadlines.write);}
  async function history(kind,action,keyboard=false) {
    const before=C.diskScene(config,kind);
    if(keyboard){await click(surface);await key(action==='undo'?'Z':'Y',['control']);}
    else await ribbon(action==='undo'?'#documentationUndoRibbon':'#documentationRedoRibbon');
    await until(action+' persisted',()=>C.diskScene(config,kind).sha256!==before.sha256,deadlines.write);await settled();
    return evidence(kind,stage+'-'+action+(keyboard?'-key':'-ribbon'),before);
  }
  async function insertText(kind) {
    const before=C.diskScene(config,kind), previous=new Set(Object.values(before.scene.pages || {}).flatMap(p=>Object.keys(p.documentObjects || {})));
    await ribbon('#documentationInsertTextRibbon');await settled();
    const found=await until('insert stored',()=>{
      for(const [pageId,p] of Object.entries(C.diskScene(config,kind).scene.pages || {}))for(const id of Object.keys(p.documentObjects || {}))if(!previous.has(id))return {pageId,id};return null;
    },deadlines.write);
    await wait('object drawn','!!document.querySelector('+JSON.stringify(objectSelector(found.id))+')');
    // Grow the box through its actual handle, leaving room for heading/list/table.
    const drag=await evaluate('(()=>{const e=document.querySelector('+JSON.stringify(objectSelector(found.id))+'),h=e.querySelector("[data-handle=se]"),s=document.querySelector("#documentationPublicationSurface"),r=h.getBoundingClientRect(),q=s.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,dx:q.width*.18,dy:q.height*.48};})()');
    const prior=C.diskScene(config,kind).sha256;
    wc.sendInputEvent({type:'mouseDown',x:Math.round(drag.x),y:Math.round(drag.y),button:'left',clickCount:1});
    for(let i=1;i<=8;i++){wc.sendInputEvent({type:'mouseMove',x:Math.round(drag.x+drag.dx*i/8),y:Math.round(drag.y+drag.dy*i/8),button:'left'});await frame();}
    wc.sendInputEvent({type:'mouseUp',x:Math.round(drag.x+drag.dx),y:Math.round(drag.y+drag.dy),button:'left',clickCount:1});
    await until('resized on disk',()=>C.diskScene(config,kind).sha256!==prior,deadlines.write);await settled();await editObject(found.id);await key('A',['control']);return found;
  }
  async function exportUi(kind,label,format) {
    const offset=report.requests.length;await ribbon(format==='pdf'?'#documentationPublishRibbon':'#documentationExportDocxRibbon');
    const row=await until('export response',()=>report.requests.slice(offset).find(r=>r.result && r.method==='POST' && /\/pdf(?:\?|$)/.test(r.url)),deadlines.export);
    if(row.status!==200)throw Error('Export refused: '+JSON.stringify(row.result));
    await settled();return retainExports(kind,label,row.result,format);
  }
  async function retainExports(kind,label,result,openedFormat) {
    const pane=await ensureBrowser(), selected=result[openedFormat] || (openedFormat==='pdf'?result.artifact:null);
    await until('native document preview',()=>pane.snapshot().tabs.some(t=>t.kind==='document' && t.url===new URL(selected.url,config.profile.origin).href && !t.loading && !t.error),deadlines.load);
    const previews=pane.snapshot(), artifacts=[];
    function walk(dir) {return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(dir,e.name)):/\.(pdf|docx)$/i.test(e.name)?[path.join(dir,e.name)]:[]);}
    const store=config.marker.stores[kind===PARTS?'PARTS_MANUAL_ROOT':'OPERATIONS_MANUAL_ROOT'];
    for(const format of ['pdf','docx']) {
      const descriptor=result[format] || (format==='pdf'?result.artifact:null);if(!descriptor)continue;
      const found=walk(store).find(p=>C.sha(fs.readFileSync(p))===descriptor.sha256);
      if(!found)throw Error('Export receipt does not match a complete file in the disposable store');
      const target=path.join(config.output,label+'.'+format);fs.copyFileSync(found,target);
      const parsed=path.join(config.output,label+'-'+format+'-text.json');
      const child=await runOwnedChild({executable:config.python,args:[path.join(root,'desktop/tools/documentation-editor-evidence.py'),'inspect','--file',target,'--out',parsed],cwd:root,env:C.environment(config),logPath:path.join(config.output,'evidence.log'),timeoutMs:Math.min(T(30000),600000)});
      if(!child.ok)throw Error('Export text helper failed: '+JSON.stringify(child));
      const text=C.json(parsed);artifacts.push({format,url:new URL(descriptor.url,config.profile.origin).href,source:found,path:target,sha256:descriptor.sha256,bytes:fs.statSync(target).size,textEvidence:parsed,headingPresent:text.text.includes(heading)});
    }
    report.artifacts.push(...artifacts);record(label,artifacts.every(a=>a.bytes>0 && a.headingPresent),{...(await evidence(kind,label)),nativePreview:previews,artifacts});
    for(const view of pane.getViews()) {view.webContents.focus();view.webContents.sendInputEvent({type:'keyDown',keyCode:'W',modifiers:['control']});view.webContents.sendInputEvent({type:'keyUp',keyCode:'W',modifiers:['control']});}
    await until('previews closed',()=>pane.snapshot().tabs.length===0);wc.focus();await frame();
  }
  async function closeSaved(name) {
    // The shell counts the Workflows tab's goal as unsaved work whenever its type is not Facility Layout (an
    // observation-only rule, desktop/tests/workflow-source-observation.test.cjs), so the application asks before
    // every close from Documentation, saved or not. With the documentation row clean and nothing else reported,
    // the scenario answers that real dialog with "Close without saving". Any other unsaved-work report fails
    // here and is never answered.
    const observation=await observe(), rows=JSON.parse(observation.fingerprint).rows;
    const others=observation.affected.filter(k=>k!=='training');
    const clean=!rows.documentation.dirty && !rows.documentation.busy && !rows.documentation.pending && others.length===0;
    const answer=observation.dirty?{title:'Unsaved work',button:'Close without saving',reason:'Only the Workflows goal is reported; the documents are saved'}:null;
    record(name,clean,{observation,documentationRow:rows.documentation,expectedPrompt:answer,parts:C.diskScene(config,PARTS),operations:fs.existsSync(path.join(config.marker.stores.OPERATIONS_MANUAL_ROOT,'mmle-50d','documentation-scene.json'))?C.diskScene(config,OPS):null});
    if(!clean)throw Error('Unsaved work is reported outside the Workflows goal: '+observation.affected.join(', '));
    finishNetwork();C.finish(report);flush();armedDialog=answer;await change('close');
    // app.quit owns shutdown, not application-check's emergency finally path.
    if(!window.isDestroyed())throw Error('The application refused its saved close');
    await new Promise(()=>{});
  }
  function finishNetwork() {
    if(report.checks.some(c=>c.name==='network_'+stage))return;
    report.policy=network.getEvidence();report.backends=runtime.getEvidence();
    const outside=report.requests.concat(report.windowOpens).filter(r=>/^https?:|^wss?:/.test(r.url) && ![config.profile.origin,config.profile.origin.replace('http:','ws:'),'https://inspectorpro-document.invalid'].includes(new URL(r.url).origin));
    report.outboundRequests=outside;
    const optional=report.requests.filter(C.optionalRequest);report.expectedRequests=optional;
    const failures=report.requests.filter(r=>r.status>=400&&!C.optionalRequest(r));
    const aborts=report.failedRequests.filter(r=>!(r.error==='net::ERR_ABORTED' && r.method==='GET' && (/\/static\//.test(r.url)||/\/api\/bridge\/status/.test(r.url))));
    const blocked=report.blockedNavigations.filter(n=>!n.url || !report.artifacts.some(a=>a.url===n.url));
    record('network_'+stage,outside.length===0 && failures.length===0 && aborts.length===0 && report.policy.refused===0 && blocked.length===0,
      {outside,failures,aborts,blocked:report.policy.refusedRequests,blockedNavigations:blocked,internalPreviewOrigin:'inspectorpro-document.invalid is an in-memory protocol, not an outbound host'});
    const unexpected=report.consoleErrors.filter(e=>!optional.some(r=>e.sourceId===r.url && /Failed to load resource/.test(e.message)));
    record('console_'+stage,unexpected.length===0,{unexpected,expected:report.consoleErrors.filter(e=>!unexpected.includes(e))});
  }
  try {
    record('application_'+stage,process.versions.electron==='44.3.0' && wc.getLastWebPreferences().sandbox===true
      && wc.getLastWebPreferences().contextIsolation===true && wc.getLastWebPreferences().nodeIntegration===false,
      {electron:process.versions.electron,preload:wc.getLastWebPreferences().preload,mode:config.profile.mode});
    // The application has just shown its start page. Let that page finish its start-up requests before the
    // driver's own reload onto the assembly: a reload in the middle cuts them, and the start page then logs
    // "[ServerMemory] Initialization failed" for a request the driver itself ended.
    await wait('start page loaded','document.readyState==="complete" && document.getElementById("agentMemoryStatus")?.dataset.state!=="initializing"',deadlines.load);
    await until('start page requests answered',()=>report.requests.every(r=>r.transport!=='renderer' || r.status!==undefined || !!r.error),deadlines.load);
    report.startPage={requests:report.requests.length,memoryState:await evaluate('document.getElementById("agentMemoryStatus")?.dataset.state || null')};
    await wc.loadURL(config.profile.origin+'/?assemblyProfile=MMLE-50D');
    await wait('MMLE assembly','window.__compareDbg?.state?.partNumber==="MMLE-50D" && !!window.__compareDbg?.state?.assyLiveScene',deadlines.load);
    await open();
    if(stage==='edit') {
      record('rich_entry_points',await evaluate(state+'.partsManualDocumentation.documentationRichText===true && !!document.querySelector("#documentationInsertTextRibbon")'),await evidence(PARTS,'initial'));
      const part=await insertText(PARTS);report.part=part;
      await typeHeading();await key('Return');
      await click('[data-rich-action="bullets"]');await type('Parent service item');await key('Return');
      await type('Nested service item');await click('[data-rich-action="increase indent"]');
      await key('Return');await key('Return');await key('Return');
      await key('B',['control']);await type('Bold check');await key('B',['control']);await type(' link');
      await key('Left',['control','shift']);
      await fill('[data-rich-control="http-or-https-link"]','https://example.com/manual');await click('[data-rich-action="link"]');
      await key('End',['control']);await key('Right');
      await click('[data-rich-action="table"]');await fill('.documentation-table-menu [aria-label="Rows"]','2');await fill('.documentation-table-menu [aria-label="Columns"]','2');
      await click('[data-rich-action="insert-table"]');
      await wait('table remounted','!!DocumentationRichText.active?.editor.getJSON().content.some(n=>n.type==="table") && !DocumentationRichText.active.saving',deadlines.write);
      await type('First cell');await key('Tab');await type('Second cell');
      const draft=await evaluate('DocumentationRichTextCore.normalize(DocumentationRichText.active.editor.getJSON(),{editor:true})');
      const before=C.diskScene(config,PARTS);await done();
      const saved=await evidence(PARTS,'rich-saved',before), value=saved.scene.pages[part.pageId].documentObjects[part.id].content;
      const nodes=[];const visit=n=>{nodes.push(n);(n.content||[]).forEach(visit);};visit(value.doc);
      record('rich_saved',saved.uiSceneEqual && C.canonical(withoutIds(value))===C.canonical(withoutIds(draft))
        && nodes.some(n=>n.type==='heading') && nodes.filter(n=>n.type==='bulletList').length>=2
        && nodes.some(n=>n.marks?.some(m=>m.type==='bold')) && nodes.some(n=>n.marks?.some(m=>m.type==='link'))
        && nodes.some(n=>n.type==='table') && nodes.some(n=>n.text==='First cell') && nodes.some(n=>n.text==='Second cell'),{...saved,objectId:part.id,envelope:value});
      const undo=await history(PARTS,'undo');record('ribbon_undo',C.canonical(undo.scene.pages[part.pageId].documentObjects[part.id].content)===C.canonical(before.scene.pages[part.pageId].documentObjects[part.id].content),{...undo,objectId:part.id});
      const redo=await history(PARTS,'redo');record('ribbon_redo',C.canonical(redo.scene.pages[part.pageId].documentObjects[part.id].content)===C.canonical(value),{...redo,objectId:part.id});
      const ku=await history(PARTS,'undo',true);record('keyboard_undo',C.canonical(ku.scene.pages[part.pageId].documentObjects[part.id].content)===C.canonical(before.scene.pages[part.pageId].documentObjects[part.id].content),{...ku,objectId:part.id});
      const kr=await history(PARTS,'redo',true);record('keyboard_redo',C.canonical(kr.scene.pages[part.pageId].documentObjects[part.id].content)===C.canonical(value),{...kr,objectId:part.id});
      const partsDocument=(await payload()).document;
      await shot('rich-parts');
      await open(OPS);await navigate('page-specifications-1');
      const alias='spec-table-1.r0.c1', target=surface+' [data-documentation-edit-target="'+alias+'"]';
      const citedBefore=C.diskScene(config,OPS);
      await doublePress('document.querySelector('+JSON.stringify(target)+')','!!document.querySelector(\'#documentationPublicationSurface [contenteditable="true"]\')','cited text edit');
      await key('A',['control']);await type('1,000 lb');await key('Return');
      await until('cited text persisted',()=>C.diskScene(config,OPS).sha256!==citedBefore.sha256,deadlines.write);await settled();
      const cited=await evidence(OPS,'cited-edit',citedBefore);
      const metadata=Object.entries(cited.scene.fieldMeta || {}).filter(([,v])=>JSON.stringify(v).includes('edited_unverified'));
      record('cited_edit',metadata.length>0 && await evaluate('!!document.querySelector("#documentationPublicationSurface [data-evidence-marker]")'),{...cited,alias,provenance:metadata});
      report.notRun.push({step:'e_source_conflict',reason:'The browser P1c source fixture patches the catalogue and installs /__p1c/source-fixture. Application mode installs neither. No test route, source compiler mutation or forged conflict is introduced; the supervisor witnessed gate must cover refresh and resolution.'});
      // Parts has no DOCX. Type the same heading in the OM for both native formats.
      await navigate((await payload()).document.pages[0].pageId);const ops=await insertText(OPS);await typeHeading();await done();report.ops=ops;
      const oh=await evidence(OPS,'operations-heading');record('operations_heading',oh.uiSceneEqual && JSON.stringify(oh.scene.pages[ops.pageId].documentObjects[ops.id].content).includes(heading),{...oh,objectId:ops.id});
      C.writeReport(path.join(config.output,'continuation.json'),{part,ops,parts:C.diskScene(config,PARTS),operations:C.diskScene(config,OPS),partsDocument,operationsDocument:(await payload()).document,partsBeforeSave:before.scene.pages[part.pageId].documentObjects[part.id].content});
      await shot('cited-operations');await closeSaved('saved_close_requested');
    } else if(stage==='restart') {
      const prior=C.json(path.join(config.output,'continuation.json'));
      record('restart_disk_exact',C.diskScene(config,PARTS).sha256===prior.parts.sha256 && C.diskScene(config,OPS).sha256===prior.operations.sha256,
        {parts:await evidence(PARTS,'restart-parts'),operations:C.diskScene(config,OPS)});
      record('restart_parts_document',C.canonical((await payload()).document)===C.canonical(prior.partsDocument),{documentType:PARTS,documentRevision:(await payload()).document.documentRevision});
      await open(OPS);
      record('restart_operations_document',C.canonical((await payload()).document)===C.canonical(prior.operationsDocument),{documentType:OPS,documentRevision:(await payload()).document.documentRevision});
      await open(PARTS);await navigate(prior.part.pageId);
      const undo=await history(PARTS,'undo');record('restart_undo',undo.revisionAfter!==prior.parts.revision && undo.uiSceneEqual && C.canonical(undo.scene.pages[prior.part.pageId].documentObjects[prior.part.id].content)===C.canonical(prior.partsBeforeSave),{...undo,objectId:prior.part.id});
      const redo=await history(PARTS,'redo');record('restart_redo',C.canonical(redo.scene.pages)===C.canonical(prior.parts.scene.pages),redo);
      await editObject(prior.part.id);await key('End',['control']);await type(' Unsaved desktop draft');
      await wait('dirty draft','DocumentationRichText.active?.dirty===true');
      const before=C.diskScene(config,PARTS), draft=await evaluate('DocumentationRichText.active.editor.getJSON()');
      report.dirtyClose={before,draft,observation:await observe(),outcome:'pending'};flush();await shot('dirty-before-close');
      let closed=false;
      const dialogsBefore=report.nativeDialogs.length, dirtyObservation=report.dirtyClose.observation;
      const keep={title:'Unsaved work',button:'Cancel',reason:'Keep the open rich-text draft'};armedDialog=keep;
      const dirtyClosed=()=>{
        closed=true;const after=C.diskScene(config,PARTS), saved=JSON.stringify(after.scene.pages).includes('Unsaved desktop draft');
        const asked=report.nativeDialogs.length>dialogsBefore;
        report.dirtyClose.outcome=saved?'saved-before-close':asked?'asked-before-close':'silently-lost';
        record('dirty_close',saved || asked,{...report.dirtyClose,after,dialogs:report.nativeDialogs.slice(dialogsBefore)});finishNetwork();C.finish(report);flush();
      };
      window.once('closed',dirtyClosed);
      await change('close');
      if(closed)await new Promise(()=>{});
      window.removeListener('closed',dirtyClosed);armedDialog=null;
      const answered=keep.job?await keep.job:null, prompt=report.nativeDialogs[dialogsBefore] || null;
      const kept=await evaluate('DocumentationRichText.active?.dirty===true');
      report.dirtyClose.outcome=prompt?'asked-and-cancelled':'refused';report.dirtyClose.prompt=prompt;
      // The open draft is reported by its own workflow, not only through the Workflows goal.
      record('dirty_close',kept && C.diskScene(config,PARTS).sha256===before.sha256 && dirtyObservation.dirty===true
        && dirtyObservation.affected.includes('documentation')
        && (!prompt || (answered?.helperOk===true && answered.result?.pressed===true && prompt.response===0)),
        {...report.dirtyClose,after:C.diskScene(config,PARTS),answer:answered});
      await click('[data-rich-action="cancel"]');await wait('draft discarded intentionally','!DocumentationRichText.active');
      await closeSaved('restart_saved_close_requested');
    } else {
      const prior=C.json(path.join(config.output,'continuation.json'));
      await open(OPS);await navigate(prior.ops.pageId);
      await exportUi(OPS,'review','pdf');await exportUi(OPS,'review-docx','docx');
      await navigate('page-specifications-1');await click(surface+' [data-documentation-edit-target="spec-table-1.r0.c1"]');
      if(!await evaluate('[...document.querySelectorAll("#documentationProperties button")].some(e=>('+visible+')(e)&&e.textContent.trim()==="Confirm as entered by me")'))await ribbon('#documentationInspectorRibbon');
      await named('#documentationProperties','Confirm as entered by me');await wait('confirmation dialog','!!document.querySelector("dialog[open]")');
      await named('dialog[open]','Confirm as entered by me');await settled();
      await until('confirmation persisted',()=>JSON.stringify(C.diskScene(config,OPS).scene.fieldMeta).includes('entered_by_user'),deadlines.write);
      await wait('confirmation shown','JSON.stringify('+state+'.partsManualDocumentation.scene.fieldMeta).includes("entered_by_user") && !document.querySelector("#documentationWorkspace.busy")',deadlines.write);
      const confirmed=await evidence(OPS,'confirmed');record('user_confirmation',confirmed.uiSceneEqual,confirmed);
      // No Customer mode button exists. As in P1b, use the public endpoint via
      // the authenticated application session, then its real native preview.
      // The private credential stays exclusively in the production runtime.
      const result=await evaluate('fetch("/api/operations-manual/MMLE-50D/pdf?mode=customer",{method:"POST"}).then(async r=>({status:r.status,body:await r.json()}))');
      if(result.status!==200)throw Error('Customer export refused: '+JSON.stringify(result));
      for(const format of ['pdf','docx']) {
        await evaluate('window.open('+JSON.stringify(new URL(result.body[format].url,config.profile.origin).href)+',"_blank","noopener")');
        await retainExports(OPS,'customer-'+format,result.body,format);
      }
      record('customer_transport',true,{method:'Application same-origin POST /pdf?mode=customer, followed by real native document preview',reason:'No customer-mode selector exists in the workspace ribbon'});
      await shot('final-operations');await closeSaved('export_saved_close_requested');
    }
  } catch(error) {
    record('scenario_'+stage,false,{message:error.message,stack:error.stack});
    if(!window.isDestroyed()) {await shot('failure-'+stage).catch(()=>{});report.lastObservation=await observe().catch(()=>null);}
    finishNetwork();C.finish(report);flush();throw error;
  }
}
const driver=require.resolve('./application-check.cjs');require(driver);require.cache[driver].exports={run};
flush();
require('../src/application-main.cjs');
