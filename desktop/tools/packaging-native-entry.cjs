'use strict';
// Runs inside the actual sandboxed application, using a disposable profile only.
// The disposable fixture in the profile's data root selects the run:
//  - full (default): manual editing, artwork, Undo/Redo, PDF, the real STEP import, a native Reload and a Restart
//    backend over checkpointed unsaved work, the guarded departure, a controlled backend loss and, last, a native
//    Close over checkpointed unsaved work, which leaves packaging-recovery-expected.json for the next run;
//  - recover: with that file present, the restarted application must offer the work back, restore it and save it;
//  - missing (fixture.expectMissing): each component withheld on purpose must fail clearly when used, while manual
//    editing and saving keep working.
const fs = require('node:fs/promises');
const path = require('node:path');
const zlib = require('node:zlib');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const driver = require.resolve('./application-check.cjs');
require(driver);

// Text of a ReportLab PDF (standard fonts): its content streams are ASCII85 and Flate encoded.
function pdfText(bytes) {
  const a85 = text => {
    const body = text.replace(/\s+/g, '').replace(/~>$/, ''), out = [];
    for (let i = 0; i < body.length;) {
      if (body[i] === 'z') { out.push(0, 0, 0, 0); i += 1; continue; }
      const group = body.slice(i, i + 5); i += 5;
      const padded = group.padEnd(5, 'u');
      let value = 0;
      for (const char of padded) value = value * 85 + (char.charCodeAt(0) - 33);
      const four = [value >>> 24, (value >>> 16) & 255, (value >>> 8) & 255, value & 255];
      out.push(...four.slice(0, group.length - 1));
    }
    return Buffer.from(out);
  };
  const source = bytes.toString('latin1'), strings = [];
  for (const match of source.matchAll(/<<([^]*?)>>\s*stream\r?\n([^]*?)endstream/g)) {
    let data = Buffer.from(match[2], 'latin1');
    try {
      if (/ASCII85Decode/.test(match[1])) data = a85(match[2].slice(0, match[2].indexOf('~>') + 2));
      if (/FlateDecode/.test(match[1])) data = zlib.inflateSync(data);
    } catch (_) { continue; }
    for (const literal of data.toString('latin1').matchAll(/\(((?:\\.|[^\\)])*)\)\s*Tj/g)) {
      strings.push(literal[1].replace(/\\([()\\])/g, '$1'));
    }
  }
  return strings.join(' ');
}

require.cache[driver].exports = { run: async ({ window, profile, output, observe, runtime, change, network }) => {
  const fixture = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'packaging-check.json'), 'utf8'));
  assert.equal(fixture.disposable, true);
  assert.equal(fixture.store, profile.dataRoot);
  assert.ok(profile.profileId.startsWith('packaging-native-'));
  const expectedFile = path.join(profile.dataRoot, 'packaging-recovery-expected.json');
  const expected = await fs.readFile(expectedFile, 'utf8').then(JSON.parse, () => null);
  const mode = fixture.expectMissing?.length ? 'missing' : expected && !expected.recovered ? 'recover' : 'full';
  const hash = bytes => createHash('sha256').update(bytes).digest('hex');
  const original = fixture.stepSource ? hash(await fs.readFile(fixture.stepSource)) : null;
  const report = { status: 'running', mode, checks: [], captures: [], sourceUnchanged: false, liveQuotes: false, liveInference: false };
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
  const value = name => js(`${doc}.querySelector('[name="${name}"]')?.value ?? null`);
  const rename = name => js(`${doc}.getElementById('document-name').value=${JSON.stringify(name)};${doc}.getElementById('document-name').dispatchEvent(new (${child}.Event)('input',{bubbles:true}));`);
  const notice = () => js(`${doc}.getElementById('message').textContent`);
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
  async function setFile(name, file) {
    const dbg = window.webContents.debugger; dbg.attach('1.3');
    try {
      const result = await dbg.sendCommand('Runtime.evaluate', { expression: selector(`[name="${name}"]`, true) });
      assert.ok(result.result.objectId);
      await dbg.sendCommand('DOM.setFileInputFiles', { files: [file], objectId: result.result.objectId });
    } finally { dbg.detach(); }
  }
  const recoveryOpen = `${doc}?.getElementById('resource-dialog')?.open && ${doc}.getElementById('resource-dialog').textContent.includes('Recover unsaved work')`;
  // A native confirm() blocks the renderer, and with it this driver. Answer the editor's prompts as a user who
  // accepts them would, and keep every prompt in the evidence. The product's prompts are unchanged.
  report.confirmations = [];
  const answerPrompts = () => js(`(()=>{const w=${child};if(!w||w.__packagingCheckPrompts)return;w.__packagingCheckPrompts=[];w.confirm=m=>{w.__packagingCheckPrompts.push(String(m).slice(0,240));return true;};})()`);
  async function prompts() {
    const answered = await js(`(()=>{const w=${child};const v=w?.__packagingCheckPrompts||[];if(w)w.__packagingCheckPrompts=[];return v;})()`).catch(() => []);
    report.confirmations.push(...answered);
  }
  async function mount({ recovery = false } = {}) {
    await until(`!!document.querySelector('[data-tab="training"]')`, 'Application did not load', 120000);
    await click(selector('[data-tab="training"]'));
    await click(selector('#trainingTypeRibbonTrigger'));
    await click(selector('#trainingTypeRibbonOption-packaging_shipping'));
    if (recovery) {
      // The editor offers stored drafts as soon as it loads; the ribbon waits until that dialog is answered.
      await until(`!!(${recoveryOpen})`, 'Recovery was not offered', 90000);
      await answerPrompts();  // After the editor document loaded, so the answer belongs to that window.
      return;
    }
    await until(`!!document.querySelector('#packaging-ribbon-product:not([disabled])')`, 'Native packaging frame did not authenticate');
    await until(`!!${doc}.querySelector('#viewport canvas')`, 'Native canvas missing');
    await answerPrompts();
  }
  async function covered(label) {
    // A native transition may skip the question only when the editor's exact state is stored or clean.
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      const state = await observe();
      if (!state.dirty && !state.busy && !state.pending) return state;
      await pause(250);
    }
    throw Error(label + ': not covered ' + JSON.stringify(await js(`${child}.InspectorProPackaging.getDepartureCoverage()`)));
  }
  async function openDocument(name) {
    await command('open');
    await until(`${doc}.getElementById('document-list').textContent.includes(${JSON.stringify(name)})`, 'Saved package missing: ' + name);
    await click(`[...${doc}.querySelectorAll('.document-row')].find(r=>r.textContent.includes(${JSON.stringify(name)})).querySelector('button')`);
    await saved();
  }
  async function restoreFirst(name, editor, typed) {
    const text = await js(`${doc}.getElementById('resource-dialog').textContent`);
    assert.ok(text.includes(name), 'Recovery does not list the draft: ' + text.slice(0, 400));
    assert.ok(text.includes(`values typed in the ${editor} panel, not applied`), 'Recovery omits the typed values: ' + text.slice(0, 400));
    await click(`[...${doc}.querySelectorAll('#resource-dialog button')].find(b=>b.getAttribute('aria-label')==='Restore 1')`);
    await until(`!${doc}.getElementById('resource-dialog')?.open`, 'Recovery dialog did not close');
    assert.equal(await js(`${doc}.getElementById('document-name').value`), name);
    assert.ok((await notice()).includes(`Values typed in the ${editor} panel are back, still unapplied`), 'Typed values note missing');
    for (const [field, typedValue] of Object.entries(typed)) assert.equal(await value(field), String(typedValue), 'Typed value not restored: ' + field);
    await click(button('Reset fields'));
    await command('save'); await saved();
    const drafts = (await api('/drafts')).drafts;
    assert.deepEqual(drafts.filter(draft => draft.name === name), [], 'Recovery draft kept after the save');
  }
  async function downloadPdf(file) {
    const downloaded = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Native PDF download timed out')), 30000);
      window.webContents.session.once('will-download', (event, item) => {
        item.setSavePath(file);
        item.once('done', (_event, state) => { clearTimeout(timer); state === 'completed' ? resolve() : reject(Error('PDF ' + state)); });
      });
    });
    await command('pdf'); await downloaded;
    const bytes = await fs.readFile(file);
    assert.equal(bytes.subarray(0, 5).toString(), '%PDF-');
    return bytes;
  }
  async function manualProduct(name, quantity) {
    await panel('product');
    await rename(name);
    await fill('quantity', quantity); await fill('mass_basis', 'estimate'); await fill('product_mass', .5);
    await fill('mass_evidence', 'Acceptance fixture assumption, not a product measurement');
    await fill('contents', 'ordinary_nonhazardous');
    await click(button('Add manual product')); await command('save'); await saved(); await closePanel();
  }
  const current = async () => {
    const documents = (await api('/documents')).documents;
    const name = await js(`${doc}.getElementById('document-name').value`);
    const row = documents.find(item => item.name === name); assert.ok(row, 'Saved document missing: ' + name);
    return api('/documents/' + row.id);
  };

  async function full() {
    const stepName = 'TEST native straight rack and pusher ' + Date.now();
    report.stage = 'mount'; await persist(); await mount();
    const status = await api('/status');
    for (const capability of ['step_import', 'draft_recovery', 'surface_graphics']) assert.ok(status.capabilities.includes(capability), capability);
    report.checks.push('native authenticated iframe; STEP, recovery and artwork capabilities');
    await manualProduct('TEST native desktop package', 6);
    report.stage = 'arrange'; await persist();
    await panel('arrange'); await fill('tare', .2); await fill('tare_evidence', 'TEST fixture assumption'); await fill('payload', 10);
    await click(button('Apply alternative')); await click(button('Generate candidates'));
    await until(`${button('Apply candidate')}?.disabled===false`, 'No arrangement candidate');
    await click(button('Apply candidate')); await prompts(); await closePanel();
    assert.ok(report.confirmations.some(text => text.startsWith('Replace all package arrangements')), 'Apply candidate did not ask');
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
    for (let i = 0; i < bitmap.length; i += 64) colors.add(bitmap.subarray(i, i + 3).toString('hex'));
    assert.ok(colors.size > 40, 'Blank native canvas'); report.canvasColors = colors.size;
    report.checks.push('manual editing, arrangement, validated mass, save, rendered camera changes');

    report.stage = 'artwork'; await persist();
    const { nativeImage } = require('electron');
    const width = 192, height = 96, pixels = Buffer.alloc(width * height * 4);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4, edge = x < 6 || y < 6 || x >= width - 6 || y >= height - 6, band = ((x >> 4) + (y >> 4)) % 2;
      pixels.set(edge ? [20, 20, 20, 255] : band ? [40, 140, 230, 255] : [250, 250, 250, 255], i);  // BGRA
    }
    const artwork = path.join(output, 'TEST-native-artwork.png');
    await fs.writeFile(artwork, nativeImage.createFromBitmap(pixels, { width, height }).toPNG());
    const lettering = 'TEST-NATIVE-LETTERING';
    await panel('graphics');
    await setFile('graphic_file', artwork);
    await click(button('Add image'));
    await until(`${doc}.getElementById('message').textContent.includes('Image added to draft.')`, 'Artwork image not added', 90000);
    await click(button('Add lettering'));
    await fill('graphic_text', lettering);
    await click(`${doc}.querySelector('form button[aria-label="Add lettering"]')`);
    await command('save'); await saved(); await closePanel();
    const withArt = await current();
    const graphics = withArt.design.packages[0].graphics;
    assert.deepEqual(graphics.map(g => g.kind).sort(), ['image', 'text']);
    const image = graphics.find(g => g.kind === 'image');
    assert.equal(graphics.find(g => g.kind === 'text').text, lettering);
    await api('/images/' + image.image_id);
    report.artwork = { imageId: image.image_id, graphics: graphics.length, documentRevision: withArt.revision };
    await capture('03-native-artwork');
    report.checks.push('artwork: imported PNG image and lettering on the carton, saved with the document');
    await command('undo'); await saved();
    const undone = (await current()).design.packages[0].graphics?.length || 0;
    assert.ok(undone < 2, 'Undo did not remove the artwork edit');
    await command('redo'); await saved();
    assert.equal((await current()).design.packages[0].graphics.length, 2, 'Redo did not restore the artwork');
    report.checks.push(`Undo removes the artwork edit (${undone} graphics left) and Redo restores both`);

    report.stage = 'pdf'; await persist();
    const text = pdfText(await downloadPdf(path.join(output, 'native-review.pdf')));
    for (const expectedText of ['Surface graphic schedule', lettering, image.image_id]) assert.ok(text.includes(expectedText), 'Report text lacks ' + expectedText);
    report.checks.push('native authenticated PDF download; the report lists the artwork schedule, lettering and image reference');
    await panel('rates'); assert.equal(await js(`${button('Compare rates')}.disabled`), true); await closePanel();

    report.stage = 'real STEP import'; await persist();
    await command('new'); await panel('product');
    await setFile('source_file', fixture.stepSource);
    await click(button('Import STEP'));
    await until(`${doc}.getElementById('editor').textContent.includes('dimensions locked')`, 'STEP import failed', 180000);
    await fill('quantity', 4); await click(button('Apply product'));
    await rename(stepName);
    await command('save'); await saved(); await closePanel();
    await until(`${doc}.getElementById('scene-message').textContent===''`, 'Imported mesh not rendered', 90000);
    await click(button('Fit view')); await capture('04-real-step');
    const imported = await current();
    assert.equal(imported.design.quantity, 4); assert.equal(imported.design.product.source_revision, original);
    report.importedDocument = imported.id;
    const source = await api('/sources/' + imported.design.product.source_id);
    assert.equal(source.solid_count, 5); report.solidCount = source.solid_count;
    report.checks.push('real five-solid STEP import, four-pair quantity, saved source provenance, native mesh');
    window.unmaximize(); window.setSize(1000, 760); await pause(500); await capture('05-compact');
    const overflow = await js(`({outer:document.documentElement.scrollWidth>innerWidth+1,inner:${doc}.documentElement.scrollWidth>${child}.innerWidth+1})`);
    assert.deepEqual(overflow, { outer: false, inner: false });
    report.checks.push('compact native ribbon and viewport without overflow');
    window.maximize(); await pause(500);

    report.stage = 'reload over checkpointed work'; await persist();
    const reloadName = stepName + ' reload draft';
    await rename(reloadName); await panel('product'); await fill('quantity', 3);  // Typed, not applied.
    await covered('Reload');
    await change('reload');
    await mount({ recovery: true });
    await restoreFirst(reloadName, 'product', { quantity: 3 });
    assert.equal((await current()).design.quantity, 4, 'The typed quantity was applied');
    await closePanel();
    report.checks.push('native Reload over unsaved work kept in its recovery draft: no question, offered back with its typed values, restored, saved');

    report.stage = 'restart over checkpointed work'; await persist();
    const restartName = stepName + ' restart draft';
    await rename(restartName); await covered('Restart');
    const instance = runtime.getState().instanceId;
    await change('restart');
    assert.notEqual(runtime.getState().instanceId, instance); assert.equal(runtime.getState().status, 'ready');
    assert.equal(await js(`${doc}.getElementById('document-name').value`), restartName, 'Restart lost the unsaved name');
    await command('save'); await saved();
    assert.equal((await current()).design.name, restartName);
    report.checks.push('Restart backend over unsaved work kept in its recovery draft: no question, editor kept, saved on the new backend');

    report.stage = 'departure'; await persist();
    const clean = await covered('Clean editor');
    assert.equal(clean.affected.includes('packaging'), false);
    await command('open');
    await until(`${doc}.getElementById('open-dialog').open`, 'Open dialog missing');
    const asking = await observe();
    assert.equal(asking.pending, true, 'An open packaging dialog must keep native transitions guarded');
    assert.ok(asking.affected.includes('packaging'));
    await js(`${doc}.getElementById('open-dialog').close()`);
    await covered('Dialog closed');
    report.checks.push('clean mounted editor does not block native transitions; an open packaging dialog does');
    await command('close');
    await until(`!document.getElementById('packagingWorkspaceFrame')`, 'Close Packaging did not unmount');
    const closed = await observe(); assert.equal(closed.pending, false);
    await change('restart');
    await until(`!!document.querySelector('[data-tab="training"]')`, 'Native restart failed', 120000);
    await mount(); await openDocument(restartName); await capture('06-reopened-after-restart');
    report.checks.push('Close Packaging, real backend restart, saved document reopen');

    report.stage = 'controlled backend outage'; await persist();
    const stopped = await runtime.stop();
    assert.equal(stopped.resourcesClosed, true); assert.equal(stopped.terminationConfirmed, true);
    network.setEnabled(false); window.webContents.send('ip-application-freeze', true);
    await until('document.documentElement.inert===true', 'Native freeze missing');
    const { Menu } = require('electron');
    const leave = Menu.getApplicationMenu().items.find(i => i.label === 'Document').submenu.items.find(i => i.label === 'Close Packaging');
    assert.ok(leave); await leave.click();
    await until(`!document.getElementById('packagingWorkspaceFrame')`, 'Clean offline departure failed');
    assert.equal(await js('document.documentElement.inert'), true, 'Departure must not unfreeze the offline app');
    await change('restart');
    await until('document.documentElement.inert===false', 'Restart did not unfreeze');
    assert.equal(runtime.getState().status, 'ready');
    report.checks.push('saved clean departure through native menu while backend stopped and renderer inert; restart');

    report.network = network.getEvidence();
    report.offline = { localRequests: report.network.localRequests, refused: report.network.refused,
      refusedDestinations: [...new Set(report.network.refusedRequests.map(item => item.destination))] };
    delete report.network;
    report.checks.push(`network limited to the application origin: ${report.offline.localRequests} local requests, ${report.offline.refused} refused`);

    report.stage = 'close over checkpointed work'; await persist();
    await mount(); await openDocument(restartName);
    const closeName = stepName + ' close draft';
    await rename(closeName); await panel('product'); await fill('quantity', 2);
    await covered('Close');
    report.sourceUnchanged = hash(await fs.readFile(fixture.stepSource)) === original; assert.equal(report.sourceUnchanged, true);
    await fs.writeFile(expectedFile, JSON.stringify({ name: closeName, editor: 'product', typed: { quantity: 2 }, savedQuantity: 4 }));
    // Passed unless the close is refused: the application then quits, and the recover run checks the draft.
    await prompts();
    report.status = 'passed'; report.stage = 'closing over checkpointed work'; await persist();
    void change('close');
    await pause(90000);
    report.status = 'failed'; report.error = 'Native Close did not proceed over checkpointed work'; await persist();
    throw Error(report.error);
  }

  async function recover() {
    report.stage = 'recover after native close'; await persist();
    await mount({ recovery: true });
    await capture('01-recovery-offered');
    await restoreFirst(expected.name, expected.editor, expected.typed);
    const restored = await current();
    assert.equal(restored.design.name, expected.name);
    assert.equal(restored.design.quantity, expected.savedQuantity, 'The typed quantity was applied');
    await capture('02-recovered-and-saved');
    await fs.writeFile(expectedFile, JSON.stringify({ ...expected, recovered: restored.revision }));
    report.checks.push('after a native Close over unsaved work, the next start offered it back with its typed values; restored and saved');
    report.sourceUnchanged = hash(await fs.readFile(fixture.stepSource)) === original; assert.equal(report.sourceUnchanged, true);
  }

  async function missing() {
    report.stage = 'missing components'; await persist(); await mount();
    const status = await api('/status');
    report.statusUnsupported = status.unsupported; report.statusCapabilities = status.capabilities;
    await manualProduct('TEST native missing components', 2);
    const before = await current();
    report.missing = {};
    const expectNotice = async (code, phrase) => {
      await until(`${doc}.getElementById('message').textContent.includes(${JSON.stringify(phrase)})`, 'No clear notice for ' + code, 120000);
      report.missing[code] = await notice();
      assert.equal((await current()).revision, before.revision, code + ' changed the saved document');
    };
    if (fixture.expectMissing.includes('step_worker')) {
      await panel('product'); await setFile('source_file', fixture.stepSource);
      await click(button('Import STEP'));
      await expectNotice('step_worker', 'geometry');
      await click(button('Reset fields')); await closePanel();
    }
    if (fixture.expectMissing.includes('arrangement')) {
      await panel('arrange'); await fill('tare', .2); await fill('tare_evidence', 'TEST fixture assumption'); await fill('payload', 10);
      await click(button('Apply alternative')); await click(button('Generate candidates'));
      await expectNotice('arrangement', 'Manual packing still works');
      await closePanel();
    }
    if (fixture.expectMissing.includes('pdf_report')) {
      await command('pdf');
      await expectNotice('pdf_report', 'PDF reports are not available in this installation');
    }
    await click(button('Add carton')); await command('save'); await saved();  // Manual packing still works.
    assert.ok((await current()).design.packages.length >= 1, 'Manual carton not saved');
    await capture('01-manual-work-without-components');
    report.checks.push('each withheld component fails with a clear notice when used; the saved design is unchanged; manual editing and saving still work');
    if (original) { report.sourceUnchanged = hash(await fs.readFile(fixture.stepSource)) === original; assert.equal(report.sourceUnchanged, true); }
  }

  try {
    window.maximize(); window.webContents.setBackgroundThrottling(false);
    await ({ full, recover, missing })[mode]();
    await prompts();
    report.status = 'passed'; report.stage = 'complete';
  } catch (error) {
    await prompts();
    report.status = 'failed'; report.error = error.stack;
    report.screen = await js(`document.body.innerText.slice(-5000)`).catch(() => null);
    report.childMessage = await js(`${doc}.getElementById('message').textContent`).catch(() => null);
    report.coverage = await js(`${child}.InspectorProPackaging.getDepartureCoverage()`).catch(() => null);
    await capture('failure').catch(() => {}); throw error;
  } finally { await persist(); }
}};
require('../src/application-main.cjs');
