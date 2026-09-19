'use strict';
// Native, real-backend checks. Only a prepared facility copy may be used.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const digest = data => createHash('sha256').update(data).digest('hex');

async function run({ window, network, profile, root, output, observe }) {
  const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
  assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
  assert.notEqual(path.resolve(profile.facilityRoot), path.resolve(root, '.runtime/facility-layout'));
  await fs.mkdir(output, { recursive: true });
  const report = { schemaVersion: 1, status: 'running', checks: [], errors: [], screenshots: [],
    unverified: ['Provider-generated inspection, manuals and training', 'Microphone recording',
      'SolidWorks extraction requires the CAD application', 'DFM has an empty viewport in the shared web application'] };
  const persist = () => fs.writeFile(path.join(output, 'workflows-check.json'), JSON.stringify(report, null, 2));
  await persist();
  const js = async code => {
    let timer;
    try { return await Promise.race([window.webContents.executeJavaScript(`(async()=>(${code}))()`, true),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('renderer-evaluation-timeout')), 30000); })]); }
    finally { clearTimeout(timer); }
  };
  const until = async (code, label, ms = 45000) => {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) { const value = await js(code); if (value) return value; await pause(200); }
    throw new Error(label);
  };
  const click = async selector => {
    const point = await js(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el||el.disabled||el.closest('[inert]'))throw Error('Unavailable control: '+${JSON.stringify(selector)});const r=el.getBoundingClientRect();if(!r.width||!r.height)throw Error('Hidden control: '+${JSON.stringify(selector)});return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
    window.focus(); window.webContents.focus();
    window.webContents.sendInputEvent({ type: 'mouseMove', ...point });
    window.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
    window.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...point });
    await pause(250);
  };
  const screenshot = async name => {
    await pause(600);
    const image = await window.webContents.capturePage();
    assert.equal(image.isEmpty(), false);
    await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
    report.screenshots.push(name + '.png');
  };
  const check = async (name, task) => {
    const row = { name, status: 'running', started: new Date().toISOString() };
    report.checks.push(row); await persist();
    try { row.evidence = await task(); row.status = 'passed'; }
    catch (error) { row.status = 'failed'; row.error = error.message; await screenshot('failure-' + name).catch(() => {}); }
    row.finished = new Date().toISOString(); await persist();
  };
  window.webContents.on('console-message', details => {
    if (details.level === 'error') report.errors.push({ stage: report.checks.at(-1)?.name, message: String(details.message).slice(0, 700) });
  });
  const app = '_trainFacilityLayoutAuthoringApp';
  // Post-processing can report two screen-quad triangles before the GLB loads.
  // Inspect the actual mounted asset, not the renderer's final-pass counter.
  const assemblyReady = `(()=>{const live=state.assyLiveScene;let meshes=0,vertices=0;live?.traverse(o=>{if(o.isMesh&&o.geometry?.attributes.position?.count){meshes++;vertices+=o.geometry.attributes.position.count;}});return state.assyGlbAvailable&&state.assyLoadedNumber==='MMLE-50D'&&live?.parent===state.assyScene&&!document.querySelector('#assy-loading')&&meshes>0&&vertices>0?{meshes,vertices}:false;})()`;
  window.setTitle('InspectorPro - Workflow verification');
  await until(`!!window.${app}?.session?.getState().loaded`, 'facility-not-ready');
  const original = await js(`${app}.session.getState()`);
  let draftBaseline = original;
  await js(`(()=>{window.__workflowCheckFacility = ${app};return true;})()`);
  await check('facility-and-library', async () => {
    assert.equal(original.baseRevision, source.originalSha256);
    assert.equal(original.layout.placements.length, 827);
    await click('#trainFacilityLayoutAssets');
    await until(`${app}.workspace.assetBrowserState.open`, 'asset-library-not-open');
    await screenshot('01-facility-library');
    await click('#trainFacilityLayoutAssets');
    return { placements: original.layout.placements.length, zones: original.layout.zones.length };
  });
  await check('load-existing-assembly', async () => {
    const profiles = await js('state.profiles.map(p=>({id:p.part_number,kind:p.context_kind}))');
    assert.ok(profiles.some(p => p.id === 'MMLE-50D'));
    await js(`selectPartNumber('MMLE-50D',false)`);
    await until(`assemblyContextAvailable && assemblyContext?.assembly_number === 'MMLE-50D'`, 'assembly-context-not-ready');
    return { profiles: profiles.length, assembly: 'MMLE-50D' };
  });
  await check('unsaved-facility-draft', async () => {
    const zone = original.layout.zones[0];
    await js(`${app}.session.editZoneLabel(${JSON.stringify(zone.zoneId)},'Native workflow preservation check')`);
    draftBaseline = await js(`${app}.session.getState()`);
    assert.equal(draftBaseline.dirty, true);
    assert.notEqual(draftBaseline.draftRevision, original.draftRevision);
    return { original: original.draftRevision, draft: draftBaseline.draftRevision, saved: false };
  });
  for (const tab of ['drawing', '3dmodel', 'assembly', 'report', 'usage', 'sessions', 'dfm']) {
    await check('tab-' + tab, async () => {
      await click('.tab[data-tab="' + tab + '"]');
      await until(`state.activeTab === ${JSON.stringify(tab)}`, 'tab-not-active');
      let geometry = null;
      if (tab === '3dmodel') geometry = await until(assemblyReady, 'model-mesh-not-rendered', 90000);
      if (tab === 'drawing') assert.equal(await js(`getComputedStyle(document.querySelector('.left-panel')).display !== 'none'`), true);
      if (tab === 'assembly') geometry = await until(assemblyReady, 'assembly-mesh-not-rendered', 90000);
      if (tab === 'sessions') await until('sessionsTabState.loaded && !sessionsTabState.loading', 'sessions-not-loaded');
      await screenshot('02-' + tab);
      return { ...await js(`({active:state.activeTab,inert:!!document.querySelector('[inert]'),canvas:document.querySelectorAll('#viewportContent canvas').length})`), geometry };
    });
  }
  await click('.tab[data-tab="training"]');
  const workflowTypes = await js('TRAINING_TYPES.map(t=>({id:t.value,label:t.label}))');
  for (const type of workflowTypes.filter(t => !['facility_layout', 'assembly'].includes(t.id))) {
    await check('workflow-' + type.id, async () => {
      await click('#trainingTypeRibbonTrigger');
      await click('#trainingTypeRibbonOption-' + type.id);
      await until(`trainingState.type === ${JSON.stringify(type.id)}`, 'workflow-type-not-selected');
      await until(`!!document.querySelector('#trainViewportHost, #documentationWorkspace, .documentation-workflow-bootstrap')`, 'workflow-host-not-mounted');
      if (type.id === 'documentation') await until(`!!document.getElementById('documentationWorkspace')`, 'documentation-not-open', 90000);
      await screenshot('03-' + type.id);
      const result = await js(`({type:trainingState.type,mode:trainingState.viewportMode,host:!!document.querySelector('#trainViewportHost, #documentationWorkspace'),ribbonControls:[...document.querySelectorAll('#ribbon button')].map(e=>({id:e.id,disabled:e.disabled})),inert:!!document.querySelector('#trainingTypeRibbonTrigger')?.closest('[inert]')})`);
      assert.equal(result.inert, false);
      return result;
    });
    if (type.id === 'documentation') {
      const types = await js('DOCUMENTATION_DOCUMENT_TYPES.filter(t=>t.available).map(t=>t.value)');
      for (const value of types) await check('document-' + value, async () => {
        await click('#documentationTypeRibbonTrigger');
        await click('#documentationTypeRibbonOption-' + value);
        await until(`!!document.getElementById('documentationWorkspace')`, 'document-workspace-not-open', 90000);
        // Workflow entry intentionally presents a blank authoring surface.
        // Refresh is the existing UI action for revealing the saved baseline.
        await click('#documentationRefreshRibbon');
        await until(`!!document.getElementById('documentationWorkspace') && state.partsManualDocumentation?.document?.pages?.length > 0`, 'existing-document-not-open', 90000);
        const selected = await js(`document.getElementById('documentationTypeRibbonSelect')?.value`);
        assert.equal(selected, value);
        assert.equal(await js(`!!document.getElementById('documentationWorkspace')`), true);
        await screenshot('04-' + value);
        return await js(`({selected:state.documentationDocumentType,pages:state.partsManualDocumentation.document.pages.length,inert:!!document.getElementById('documentationWorkspace').closest('[inert]')})`);
      });
    }
  }
  await check('same-window-export-retains-workspace', async () => {
    const before = await js(`${app}.session.getState().draftRevision`);
    const file = path.join(output, 'native-download.png');
    let listener, timer;
    const downloaded = new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error('download-not-started')), 15000);
      listener = (_event, item) => {
        item.setSavePath(file);
        item.once('done', (_e, status) => status === 'completed' ? resolve() : reject(new Error('download-' + status)));
      };
      window.webContents.session.once('will-download', listener);
    });
    try {
      await js(`(()=>{const link=document.createElement('a');link.href='/static/logo.png';link.download='native-download.png';link.click();return true;})()`);
      await downloaded;
    } finally { clearTimeout(timer); window.webContents.session.removeListener('will-download', listener); }
    const bytes = await fs.readFile(file);
    assert.equal(digest(bytes), digest(await fs.readFile(path.join(root, 'static/logo.png'))));
    assert.equal(await js(`${app} === window.__workflowCheckFacility`), true);
    assert.equal(await js(`${app}.session.getState().draftRevision`), before);
    return { bytes: bytes.length, sameEditor: true };
  });
  await check('image-upload-through-file-input', async () => {
    await click('.tab[data-tab="drawing"]');
    await js(`(async()=>{const blob=await (await fetch('/static/logo.png')).blob();const transfer=new DataTransfer();transfer.items.add(new File([blob],'native-upload.png',{type:'image/png'}));fileInput.files=transfer.files;fileInput.dispatchEvent(new Event('change',{bubbles:true}));return true;})()`);
    await until(`state.file?.name==='native-upload.png' && document.querySelector('#drawingWrapper img')?.naturalWidth>0`, 'uploaded-image-not-rendered');
    await screenshot('05-image-upload');
    return { pipeline: 'file-input/FileReader/drawing-renderer', image: 'existing logo test fixture' };
  });
  await check('facility-session-restored', async () => {
    await click('.tab[data-tab="training"]');
    await click('#trainingTypeRibbonTrigger'); await click('#trainingTypeRibbonOption-facility_layout');
    await until(`${app}.workspace.root.isConnected && ${app}.getState().suspended===false`, 'facility-not-restored');
    const restored = await js(`${app}.session.getState()`);
    assert.equal(await js(`${app} === window.__workflowCheckFacility`), true);
    for (const key of ['layout', 'draftRevision', 'history', 'historyCursor', 'selection']) assert.deepEqual(restored[key], draftBaseline[key]);
    assert.equal(restored.dirty, true);
    await click('.facility-ribbon-commandbar [data-facility-ribbon-command="undo"]');
    await until(`${app}.session.getState().draftRevision === ${JSON.stringify(original.draftRevision)}`, 'undo-did-not-restore-original');
    assert.deepEqual(await js(`${app}.session.getState().layout`), original.layout);
    await screenshot('06-facility-restored');
    return { sameEditor: true, unsavedDraftPreserved: true, undoRestoredOriginal: true, observation: await observe() };
  });
  // Opening the reference Process Map can materialize an unsaved migrated
  // draft. Inspect it last; do not accept a discard prompt or Save it.
  await check('workflow-assembly', async () => {
    await click('#trainingTypeRibbonTrigger'); await click('#trainingTypeRibbonOption-assembly');
    await until(`trainingState.type === 'assembly' && !!_trainCurrentProcessFlowEditor()`, 'process-map-not-mounted');
    await until(`InspectorProProcessMap.mapNodes(_trainCurrentProcessFlowEditor().processMap).length > 0`, 'process-map-nodes-not-loaded');
    await screenshot('07-process-map');
    return await js(`({type:trainingState.type,dirty:!!_trainCurrentProcessFlowEditor().dirty,sourceNodes:InspectorProProcessMap.mapNodes(_trainCurrentProcessFlowEditor().processMap).length})`);
  });
  report.network = network.getEvidence();
  report.originalUnchanged = digest(await fs.readFile(source.originalPath)) === source.originalSha256;
  const documentSources = await fs.readFile(path.join(profile.dataRoot, 'workflow-documents-source.json'), 'utf8').then(JSON.parse).catch(() => []);
  report.originalDocumentsUnchanged = true;
  for (const item of documentSources) {
    if (digest(await fs.readFile(item.path)) !== item.sha256) report.originalDocumentsUnchanged = false;
  }
  report.originalDocumentFilesChecked = documentSources.length;
  report.status = report.checks.every(c => c.status === 'passed') && report.originalUnchanged
    && report.originalDocumentsUnchanged
    && report.network.refused === 0 && report.network.saveCalls === 0 ? 'passed' : 'failed';
  await persist();
  return report;
}
module.exports = { run };
