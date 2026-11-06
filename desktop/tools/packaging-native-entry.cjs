'use strict';
// Runs inside the actual sandboxed application, using a disposable profile only.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const driver = require.resolve('./application-check.cjs');
require(driver);
require.cache[driver].exports = { run: async ({ window, profile, output, observe, runtime, change, network }) => {
  const fixture = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'packaging-check.json'), 'utf8'));
  assert.equal(fixture.disposable, true);
  assert.equal(fixture.store, profile.dataRoot);
  assert.ok(profile.profileId.startsWith('packaging-native-'));
  const hash = bytes => createHash('sha256').update(bytes).digest('hex');
  const original = hash(await fs.readFile(fixture.stepSource));
  const stepName = 'TEST native straight rack and pusher ' + Date.now();
  const report = { status: 'running', checks: [], captures: [], sourceUnchanged: false, liveQuotes: false, liveInference: false };
  await fs.mkdir(output, { recursive: true });
  const persist = () => fs.writeFile(path.join(output, 'packaging-native.json'), JSON.stringify(report, null, 2));
  const js = async code => {
    try { return await window.webContents.executeJavaScript(code, true); }
    catch (error) { throw Error(error.message + '\nTest expression: ' + code, { cause: error }); }
  };
  const doc = `document.getElementById('packagingWorkspaceFrame').contentDocument`;
  const child = `document.getElementById('packagingWorkspaceFrame').contentWindow`;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function until(code, label, timeout = 60000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await js(code)) return;
      await pause(150);
    }
    throw Error(label);
  }
  async function click(expression) {
    // Activate the real native-renderer DOM control. This avoids OS pointer
    // interference while exercising the same handlers and protected requests.
    await js(`(()=>{const b=${expression};if(!b||b.disabled||!b.checkVisibility())throw Error('Unavailable control');b.scrollIntoView({block:'nearest'});b.click();})()`);
    await pause(120);
    await until(`!document.getElementById('packagingWorkspaceFrame')?.contentWindow?.InspectorProPackaging?.getDesktopLifecycleObservation().busy`, 'Control did not finish',180000);
  }
  const selector = (s, embedded = false) => `${embedded ? doc : 'document'}.querySelector(${JSON.stringify(s)})`;
  const button = label => `[...${doc}.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===${JSON.stringify(label)}&&b.checkVisibility())`;
  const fill = (name, value) => js(`(()=>{const d=${doc},n=d.querySelector('[name="${name}"]');n.value=${JSON.stringify(String(value))};n.dispatchEvent(new n.ownerDocument.defaultView.Event('input',{bubbles:true}));n.dispatchEvent(new n.ownerDocument.defaultView.Event('change',{bubbles:true}));})()`);
  async function panel(id) {
    if (await js(`${doc}.getElementById('tool-panel').checkVisibility() && ${doc}.getElementById('panel-title').textContent.toLowerCase()===${JSON.stringify(id)}`)) return;
    await click(selector('#packaging-ribbon-' + id));
    await until(`${doc}.getElementById('tool-panel').checkVisibility() && ${doc}.getElementById('panel-title').textContent.toLowerCase()===${JSON.stringify(id)}`, 'Panel did not open: ' + id);
  }
  const closePanel = () => click(selector('#close-panel', true));
  async function command(id) {
    if (['save', 'undo', 'redo'].includes(id)) return click(selector('#packaging-ribbon-' + id));
    await click(selector('[data-packaging-command-menu*="new"]'));
    await click(selector('#packaging-menu-' + id));
  }
  async function saved() {
    await until(`${doc}.getElementById('document-status').textContent.includes('Saved') && !${child}.InspectorProPackaging.getDesktopLifecycleObservation().dirty`, 'Document did not save');
  }
  const api = route => js(`(async()=>{const r=await ${child}.fetch('/api/packaging'+${JSON.stringify(route)},{headers:{'X-InspectorPro-Request':'packaging'}});if(!r.ok)throw Error('API '+r.status);return r.json();})()`);
  async function capture(name) {
    await pause(500);
    const image = await window.webContents.capturePage();
    assert.ok(!image.isEmpty());
    await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
    report.captures.push(name); await persist();
    return image;
  }
  async function mount() {
    await until(`!!document.querySelector('[data-tab="training"]')`, 'Application did not load', 120000);
    await click(selector('[data-tab="training"]'));
    await click(selector('#trainingTypeRibbonTrigger'));
    await click(selector('#trainingTypeRibbonOption-packaging_shipping'));
    await until(`!!document.querySelector('#packaging-ribbon-product:not([disabled])')`, 'Native packaging frame did not authenticate');
    await until(`!!${doc}.querySelector('#viewport canvas')`, 'Native canvas missing');
  }
  try {
    window.maximize(); window.webContents.setBackgroundThrottling(false);
    report.stage = 'mount'; await persist(); await mount();
    const status = await api('/status'); assert.ok(status.capabilities.includes('step_import'));
    report.checks.push('native authenticated iframe and STEP capability');
    await panel('product');
    await js(`${doc}.getElementById('document-name').value='TEST native desktop package';${doc}.getElementById('document-name').dispatchEvent(new (${child}.Event)('input',{bubbles:true}));`);
    await fill('quantity', 6); await fill('mass_basis', 'estimate'); await fill('product_mass', .5);
    await fill('mass_evidence', 'Acceptance fixture assumption, not a product measurement');
    await fill('contents', 'ordinary_nonhazardous');
    await click(button('Add manual product')); await command('save'); await saved(); await closePanel();
    report.stage = 'arrange'; await persist();
    await panel('arrange'); await fill('tare', .2); await fill('tare_evidence', 'TEST fixture assumption'); await fill('payload', 10);
    await click(button('Apply alternative')); await click(button('Generate candidates'));
    await until(`${button('Apply candidate')}?.disabled===false`, 'No arrangement candidate');
    await click(button('Apply candidate')); await closePanel();
    await panel('carton'); await fill('allowance', .05); await fill('allowance_evidence', 'TEST packing allowance');
    await click(button('Apply carton')); await command('save'); await saved(); await closePanel();
    await panel('validation');
    await until(`${doc}.getElementById('validation-panel').textContent.includes('3.25 kg')`, 'Unexpected gross mass');
    await closePanel();
    const first = await capture('01-native-ribbon-package');
    await click(button('Top')); const top = await capture('02-native-top');
    assert.notEqual(hash(first.toPNG()), hash(top.toPNG()), 'Camera did not change pixels');
    const bounds = await js(`(()=>{const r=${doc}.querySelector('#viewport canvas').getBoundingClientRect(),f=document.getElementById('packagingWorkspaceFrame').getBoundingClientRect();return{x:Math.round(r.x+f.x),y:Math.round(r.y+f.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
    const bitmap = top.crop(bounds).toBitmap(); const colors = new Set();
    for (let i=0;i<bitmap.length;i+=64) colors.add(bitmap.subarray(i,i+3).toString('hex'));
    assert.ok(colors.size>40,'Blank native canvas'); report.canvasColors=colors.size;
    await command('undo'); await saved(); await command('redo'); await saved();
    report.checks.push('manual editing, arrangement, validated mass, save, undo/redo, rendered camera changes');
    report.stage = 'pdf'; await persist();
    const pdfPath=path.join(output,'native-review.pdf');
    const downloaded = new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Native PDF download timed out')),30000);
      window.webContents.session.once('will-download',(event,item)=>{
        item.setSavePath(pdfPath);
        item.once('done',(_event,state)=>{clearTimeout(timer);state==='completed'?resolve():reject(Error('PDF '+state));});
      });
    });
    await command('pdf'); await downloaded;
    assert.equal((await fs.readFile(pdfPath)).subarray(0,5).toString(),'%PDF-');
    report.checks.push('native authenticated PDF download completed');
    await panel('rates'); assert.equal(await js(`${button('Compare rates')}.disabled`), true); await closePanel();
    report.stage = 'real STEP import'; await persist();
    await command('new'); await panel('product');
    const dbg=window.webContents.debugger; dbg.attach('1.3');
    try {
      const result=await dbg.sendCommand('Runtime.evaluate',{expression:selector('[name="source_file"]',true)});
      assert.ok(result.result.objectId);
      await dbg.sendCommand('DOM.setFileInputFiles',{files:[fixture.stepSource],objectId:result.result.objectId});
    } finally {dbg.detach();}
    await click(button('Import STEP'));
    await until(`${doc}.getElementById('editor').textContent.includes('dimensions locked')`, 'STEP import failed',180000);
    await fill('quantity',4); await click(button('Apply product'));
    await js(`${doc}.getElementById('document-name').value=${JSON.stringify(stepName)};${doc}.getElementById('document-name').dispatchEvent(new (${child}.Event)('input',{bubbles:true}));`);
    await command('save'); await saved(); await closePanel();
    await until(`${doc}.getElementById('scene-message').textContent===''`, 'Imported mesh not rendered',90000);
    await click(button('Fit view')); await capture('03-real-step');
    const documents=(await api('/documents')).documents;
    const selected=documents.find(d=>d.name===stepName); assert.ok(selected);
    const imported=await api('/documents/'+selected.id);
    assert.equal(imported.design.quantity,4); assert.equal(imported.design.product.source_revision,original);
    report.importedDocument=selected.id;
    const source=await api('/sources/'+imported.design.product.source_id);
    assert.equal(source.solid_count,5); report.solidCount=source.solid_count;
    report.checks.push('real five-solid STEP import, four-pair quantity, saved source provenance, native mesh');
    window.unmaximize(); window.setSize(1000,760); await pause(500); await capture('04-compact');
    const overflow=await js(`({outer:document.documentElement.scrollWidth>innerWidth+1,inner:${doc}.documentElement.scrollWidth>${child}.innerWidth+1})`);
    assert.deepEqual(overflow,{outer:false,inner:false});
    report.checks.push('compact native ribbon and viewport without overflow');
    report.stage='departure'; await persist();
    const state=await observe(); assert.equal(state.pending,true,'Mounted editor must keep native transitions guarded');
    await command('close');
    await until(`!document.getElementById('packagingWorkspaceFrame')`, 'Close Packaging did not unmount');
    const closed=await observe(); assert.equal(closed.pending,false);
    await change('restart');
    await until(`!!document.querySelector('[data-tab="training"]')`, 'Native restart failed',120000);
    await mount(); await command('open');
    await until(`${doc}.getElementById('document-list').textContent.includes(${JSON.stringify(stepName)})`, 'Saved package missing after restart');
    await click(`[...${doc}.querySelectorAll('.document-row')].find(r=>r.textContent.includes(${JSON.stringify(stepName)})).querySelector('button')`);
    await saved(); await capture('05-reopened-after-restart');
    report.checks.push('guarded Close Packaging, real backend restart, saved document reopen');
    report.stage='controlled backend outage'; await persist();
    const stopped=await runtime.stop();
    assert.equal(stopped.resourcesClosed,true);assert.equal(stopped.terminationConfirmed,true);
    network.setEnabled(false);window.webContents.send('ip-application-freeze',true);
    await until('document.documentElement.inert===true','Native freeze missing');
    const { Menu }=require('electron');
    const leave=Menu.getApplicationMenu().items.find(i=>i.label==='Document').submenu.items.find(i=>i.label==='Close Packaging');
    assert.ok(leave);await leave.click();
    await until(`!document.getElementById('packagingWorkspaceFrame')`,'Clean offline departure failed');
    assert.equal(await js('document.documentElement.inert'),true,'Departure must not unfreeze the offline app');
    await change('restart');
    await until('document.documentElement.inert===false','Restart did not unfreeze');
    report.checks.push('saved clean departure through native menu while backend stopped and renderer inert; restart');
    assert.equal(runtime.getState().status,'ready');
    report.sourceUnchanged=hash(await fs.readFile(fixture.stepSource))===original; assert.equal(report.sourceUnchanged,true);
    report.status='passed'; report.stage='complete';
  } catch(error) {
    report.status='failed';report.error=error.stack;
    report.screen=await js(`document.body.innerText.slice(-5000)`).catch(()=>null);
    report.childMessage=await js(`${doc}.getElementById('message').textContent`).catch(()=>null);
    await capture('failure').catch(()=>{});throw error;
  } finally {await persist();}
}};
require('../src/application-main.cjs');
