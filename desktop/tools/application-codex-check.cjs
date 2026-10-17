'use strict';
// Test-only entry: real desktop and chat; approved editing uses a disposable copy.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash, randomUUID } = require('node:crypto');
const { captureStream } = require('./codex-stream-evidence.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const content = layout => { const copy = structuredClone(layout); delete copy.updatedAt; return copy; };
async function withDeadline(promise, label, milliseconds = 15000) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error(label + ' did not respond within ' + milliseconds + ' ms')), milliseconds);
    })]);
  } finally {
    clearTimeout(timer);
  }
}
async function run({ window, profile, root, output }) {
  if (profile.codexRuntime?.authMode === 'chatgpt_plan') {
    return require('./application-subscription-check.cjs').run({ window, profile, output });
  }
  const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
  assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
  assert.notEqual(path.resolve(profile.facilityRoot), path.resolve(root, '.runtime/facility-layout'));
  assert.equal(profile.codexRuntime?.schemaVersion, 1);
  assert.equal(profile.codexRuntime?.allowPaidInference, true);
  assert.equal(profile.codexRuntime?.model, 'gpt-5.5');
  const report = { status: 'running', scope: 'native Electron, real Codex and MCP, copied gym, no saves',
    requests: [], turns: [], progress: [], errors: [] };
  const cancelOnly = process.env.INSPECTORPRO_CODEX_DESKTOP_CANCEL_ONLY === '1';
  const memoryCheck = process.env.INSPECTORPRO_CODEX_DESKTOP_MEMORY_CHECK === '1';
  const reliability = process.env.INSPECTORPRO_CODEX_DESKTOP_RELIABILITY || '';
  assert.ok(['', 'startup', 'before-restart', 'after-restart', 'editing', 'authoring', 'editor-change'].includes(reliability));
  const authoring = reliability === 'authoring';
  const editing = reliability === 'editing' || authoring;
  if (editing) assert.equal(profile.codexRuntime.editPreviews, true);
  const enforcedMemory = memoryCheck || !!reliability;
  const second = memoryCheck ? JSON.parse(await fs.readFile(path.join(output, 'second-layout.json'), 'utf8')) : null;
  report.cancelOnly = cancelOnly;
  report.memoryCheck = memoryCheck;
  report.reliability = reliability;
  const persist = () => fs.writeFile(path.join(output, 'codex-ui-check.json'), JSON.stringify(report, null, 2));
  const js = code => withDeadline(window.webContents.executeJavaScript(`(async()=>(${code}))()`, true), 'Desktop renderer');
  const app = 'window._trainFacilityLayoutAuthoringApp';
  const until = async (check, message, timeout = 60000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { const value = await check(); if (value) return value; await delay(200); }
    throw new Error(message);
  };
  const shot = async name => {
    window.focus(); window.webContents.focus();
    await js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
    const image = await withDeadline(window.webContents.capturePage(), 'Desktop screenshot');
    assert.equal(image.isEmpty(), false);
    await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
  };
  const control = async (kind, turnId) => {
    const id = randomUUID();
    const temporary = path.join(output, 'control-request.tmp');
    await fs.writeFile(temporary, JSON.stringify({ id, kind, turnId }));
    await fs.rename(temporary, path.join(output, 'control-request.json'));
    const receipt = await until(async () => {
      const value = await fs.readFile(path.join(output, 'control-result.json'), 'utf8').then(JSON.parse).catch(() => null);
      return value?.id === id ? value : null;
    }, 'Test control did not settle: ' + kind, 40000);
    assert.equal(receipt.ok, true);
    return receipt;
  };
  const click = async selector => {
    window.focus(); window.webContents.focus();
    await until(() => js(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return !!e && !e.disabled && !!e.getBoundingClientRect().width;})()`),
      'Control did not become available: ' + selector, 10000);
    await delay(300);
    const point = await js(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});
      if(!e || e.disabled)throw Error('Unavailable control: '+${JSON.stringify(selector)});e.scrollIntoView({block:'nearest'});
      const r=e.getBoundingClientRect();if(!r.width||!r.height)throw Error('Hidden control');
      const p={x:Math.round(r.x+r.width/2),y:Math.round(r.y+(e.matches('textarea')?20:r.height/2))};
      const hit=document.elementFromPoint(p.x,p.y);if(!e.contains(hit))throw Error('Occluded control: '+e.id+' by '+hit?.className);return p;})()`);
    for (const type of ['mouseDown', 'mouseUp']) window.webContents.sendInputEvent({ type, button: 'left', clickCount: 1, ...point });
  };
  const pending = new Map();
  window.webContents.debugger.attach('1.3');
  await window.webContents.debugger.sendCommand('Network.enable');
  const onNetwork = (_event, method, params) => {
    if (method === 'Network.requestWillBeSent' && params.request.url.startsWith(profile.origin + '/api/')) {
      report.requests.push({ method: params.request.method, url: params.request.url });
      if (params.request.url.endsWith('/api/agent/chat/v2/stream')) {
        const payload = JSON.parse(params.request.postData);
        const turn = { turnId: payload.client_turn_id, conversationId: payload.conversation_id,
          agentSessionId: payload.agent_session_id,
          prompt: payload.message, startedAt: Date.now() };
        report.turns.push(turn);
        pending.set(params.requestId, captureStream(window.webContents.debugger, params.requestId, turn));
      }
    }
    pending.get(params.requestId)?.(method, params);
  };
  window.webContents.debugger.on('message', onNetwork);
  try {
    window.maximize();
    await until(() => js(`!!${app}?.session?.getState().loaded`), 'Layout did not mount');
    const before = await js(`${app}.session.getState()`);
    assert.equal(before.layout.layoutId, profile.startupLayoutId);
    assert.equal(before.baseRevision, source.originalSha256);
    assert.equal(before.dirty, false);
    report.layout = { id: before.layout.layoutId, zones: before.layout.zones.length, assets: before.layout.placements.length };
    await js(`(()=>{window._selectAgent('deviation-analyst');if(!document.getElementById('agentInput').getBoundingClientRect().width)window._toggleAgentPanel();})()`);
    if (enforcedMemory) await until(() => js("document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'"), 'Memory did not become ready');
    if (reliability === 'after-restart') {
      const previous = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'recovery-checkpoint.json'), 'utf8'));
      const chat = await js("document.getElementById('agentMessages').innerText");
      for (const turn of previous.turns.filter(t => t.terminal?.event === 'response_completed')) {
        assert.ok(chat.includes(turn.prompt), 'Committed user message missing after restart');
        assert.ok(chat.includes(turn.terminal.final.response.replace(/\*\*/g, '').slice(0, 25)), 'Committed answer missing after restart');
      }
      for (const index of [1, 3]) assert.ok(!chat.includes(previous.turns[index].prompt), 'Uncommitted turn restored as history');
      assert.equal(await js("document.getElementById('agentInput').value"), '');
      report.restartRestoredConversation = true;
    } else {
      await click('#agentChatNewBtn');
      if (enforcedMemory) await until(() => js("document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'"), 'New conversation memory did not become ready');
    }
    await shot('01-ready');
    let prompts = [
      'How many zones and placed assets are in this saved gym? Find the cardio zone and check its dimensions and area. Keep it under 100 words. Do not change anything.',
      'Which zone did we just examine? Recheck its area and name one actual equipment placement in it. Keep it brief. Do not change anything.',
      memoryCheck ? 'Inspect the currently selected saved layout. State its exact name, number of zones and number of placed assets. Is this the gym we inspected earlier? Use current tool data and do not change anything. Keep it under 100 words.'
        : 'Inspect the saved gym and check spatial findings for the cardio area. Do not change anything.',
    ].filter((_prompt, index) => !cancelOnly || index === 2);
    if (reliability === 'startup') prompts = [prompts[0]];
    if (reliability === 'editor-change') prompts = ['Walk me through the saved layout facts: inspect the zones and equipment in this gym. Keep it brief and do not change anything.'];
    if (editing) prompts = ['Inspect this saved gym and preview moving only treadmill pl-e1f4de8e9d905153b1179895 to x=15.2, y=0, z=2.1 metres. Preserve its rotation and everything else. Check the actual validator, and return the preview for my approval. Do not approve or save. Keep the reply brief.'];
    if (authoring) prompts = ['Inspect the saved Cardio - 18 Stations zone. Preview changing its zone fill to #35393E, adding one rubber floor finish over its exact boundary at its existing elevation with color #35393E and roughness 0.85, and adding a decorative solid gold line centered at x=24, y=0, z=9, width 1 m, depth 0.15 m, rotation 0, opacity 1, fill and stroke #C99B39, empty text, label Demo gold line. Generate the floor-marking ID automatically. Leave all equipment, artwork, walls, existing markings, and other zones unchanged. Use the actual preview validator and wait for my approval. Do not save. Keep the reply brief.'];
    if (reliability === 'before-restart') prompts = [prompts[0],
      'Inspect the saved gym and list five actual equipment placements in the cardio area. Do not change anything.',
      prompts[1],
      'Inspect the saved gym and check the recorded dimensions of the strength training zones. Do not change anything.'];
    if (reliability === 'after-restart') prompts = [
      'Which gym zone did we previously examine? Recheck its area and give the current saved layout name and asset count. Do not change anything. Keep it under 100 words.'];
    for (let index = 0; index < prompts.length; index++) {
      const cancelTurn = reliability ? reliability === 'before-restart' && index === 1
        : cancelOnly || (!memoryCheck && index === 2);
      const disconnectTurn = reliability === 'before-restart' && index === 3;
      if (memoryCheck && index === 1) {
        const loaded = new Promise(resolve => window.webContents.once('did-finish-load', resolve));
        window.webContents.reload(); await loaded;
        await until(() => js(`!!${app}?.session?.getState().loaded && document.getElementById('agentMemoryStatus')?.dataset.state === 'ready'`), 'Reload did not restore saved conversation');
        await until(() => js(`document.getElementById('agentMessages')?.innerText.includes(${JSON.stringify(report.turns[0].prompt)})`), 'Prior message missing after reload');
        report.reloadRestoredConversation = true;
        assert.equal(await js("document.getElementById('agentInput').value"), '', 'Sent text returned as a draft after reload');
        // Open the second copied document, then leave both real sheets ready for native tab clicks.
        await js(`_trainFacilitySheets.activate(${JSON.stringify(second.layoutId)})`);
        await click(`.ip-layout-sheet-tab[data-layout-id="${profile.startupLayoutId}"]`);
        await until(() => js(`${app}.session.getState().layout.layoutId === ${JSON.stringify(profile.startupLayoutId)}`), 'Gym was not reselected');
        await shot('04-memory-restored');
      }
      if (memoryCheck && index === 2) {
        await click(`.ip-layout-sheet-tab[data-layout-id="${second.layoutId}"]`);
        await until(() => js(`${app}.session.getState().layout.layoutId === ${JSON.stringify(second.layoutId)}`), 'Second layout did not activate');
        await shot('06-second-layout');
      }
      await js(`(()=>{if(!document.getElementById('agentInput').getBoundingClientRect().width)window._toggleAgentPanel();})()`);
      await click('#agentInput');
      assert.equal(await js("document.getElementById('agentInput').value"), '', 'Composer contains unexpected draft text');
      await window.webContents.insertText(prompts[index]);
      await click('#agentSendBtn');
      await until(() => report.turns[index], 'Chat did not use the streaming endpoint', 10000);
      const turn = report.turns[index];
      assert.equal(turn.prompt, prompts[index]);
      let captured = false;
      const deadline = Date.now() + (editing ? 270000 : 150000);
      while (Date.now() < deadline) {
        if (turn.evidenceError) throw new Error('Chat evidence failed: ' + turn.evidenceError);
        if (turn.networkError && !cancelTurn) throw new Error('Chat request failed: ' + turn.networkError);
        const state = await js(`({pending:document.querySelector('#agentMessages .agent-working-operation')?.innerText || document.querySelector('#agentMessages .agent-stream-pending')?.innerText || '',
          stop:document.getElementById('agentSendBtn')?.getAttribute('aria-label'),
          chat:document.getElementById('agentMessages')?.innerText})`);
        if (state.pending && report.progress.at(-1)?.text !== state.pending) report.progress.push({ turn: index + 1, text: state.pending.slice(0, 500) });
        if (!captured && /connecting|inspecting/i.test(state.pending)) { await shot(`02-progress-${index + 1}`); captured = true; }
        if (memoryCheck && index === 1 && !report.switchBlockedWhileBusy && /Connecting the inspection runtime|Inspecting the saved layout/.test(state.pending)) {
          await click(`.ip-layout-sheet-tab[data-layout-id="${second.layoutId}"]`);
          await delay(300);
          assert.equal(await js(`${app}.session.getState().layout.layoutId`), profile.startupLayoutId);
          assert.equal(await js("document.getElementById('agentSendBtn').getAttribute('aria-label')"), 'Stop generating');
          assert.ok(await js("document.querySelector('.ip-layout-sheet-error')?.innerText.includes('Finish the current operation')"));
          report.switchBlockedWhileBusy = true;
          await shot('05-switch-blocked');
        }
        if (reliability === 'editor-change' && /Inspecting the saved layout/i.test(state.pending)) {
          await js(`${app}.session.renameLayout('Unsaved context-revocation test')`);
          assert.equal(await js(`${app}.session.getState().dirty`), true);
          await until(() => js("document.getElementById('agentSendBtn')?.getAttribute('aria-label') !== 'Stop generating'"), 'Editor change did not cancel the request', 15000);
          turn.contextChangeReceipt = await control('settle-cancel', turn.turnId);
          await click('[data-facility-ribbon-command="undo"]');
          await until(() => js(`!${app}.session.getState().dirty && !${app}.session.getState().busy`), 'Manual undo did not restore the draft');
          report.editorChangeCancelled = true;
          await shot('04-editor-change-cancelled');
          break;
        }
        if (cancelTurn && state.stop === 'Stop generating' && /Inspecting the saved layout/i.test(state.pending)) {
          await click('#agentSendBtn'); turn.stopClicked = true;
          await until(() => js(`document.getElementById('agentSendBtn')?.getAttribute('aria-label') !== 'Stop generating' && !document.querySelector('#agentMessages .agent-stream-pending')`), 'Stop did not restore chat controls', 15000);
          if (reliability) turn.stopReceipt = await control('settle-cancel', turn.turnId);
          else await delay(3000);
          turn.chatAfterStop = await js("document.getElementById('agentMessages').innerText");
          await shot('05-stopped'); break;
        }
        if (disconnectTurn && !turn.disconnectReceipt && /Inspecting the saved layout/i.test(state.pending)) {
          turn.disconnectReceipt = await control('disconnect', turn.turnId);
        }
        if (turn.terminal) {
          if (disconnectTurn) {
            assert.ok(turn.disconnectReceipt, 'Runtime fault was not exercised');
            assert.equal(turn.terminal.event, 'response_error');
            assert.equal(turn.terminal.code, 'codex_runtime_stopped');
            await until(() => js("document.getElementById('agentSendBtn')?.getAttribute('aria-label') !== 'Stop generating'"), 'Disconnect left Stop active');
            turn.visibleError = await js("document.getElementById('agentMessages').innerText");
            assert.ok(turn.visibleError.includes('inspection runtime stopped unexpectedly'));
            assert.ok(turn.visibleError.includes('No engineering changes were made'));
            assert.ok(turn.visibleError.includes('Send a new request to reconnect'));
            assert.equal(await js("document.querySelectorAll('#agentMessages .agent-stream-retry').length"), 0,
              'Non-replayable failure offered a Retry with its rejected turn ID');
            await shot('07-disconnected');
            break;
          }
          assert.equal(turn.terminal.event, 'response_completed', JSON.stringify(turn.terminal));
          const final = turn.terminal.final;
          assert.equal(final.tool_source, 'codex_readonly_pilot');
          assert.equal(final.facility_action_mode, editing ? 'PREVIEW' : 'READ_ONLY');
          if (editing) {
            assert.equal(final.tool_calls.length, 1);
            assert.equal(final.tool_calls[0].name, 'present_codex_facility_preview');
          } else assert.deepEqual(final.tool_calls, []);
          assert.ok(final.codex_inspection.verifiedToolCalls.some(r => r.ok));
          assert.ok(turn.textDeltas > 0);
          if (enforcedMemory) {
            assert.equal(final.memory?.mode, 'enforce');
            assert.ok(final.memory.contextManifestId);
            const expectedId = memoryCheck && index === 2 ? second.layoutId : profile.startupLayoutId;
            assert.equal(final.codex_inspection.document.layoutId, expectedId);
            if (memoryCheck && index === 2) {
              assert.ok(final.response.includes(second.name));
              for (const count of [second.zones, second.assets]) assert.ok(final.response.replace(/,/g, '').includes(String(count)));
            }
          }
          await until(() => js("document.getElementById('agentSendBtn')?.getAttribute('aria-label') !== 'Stop generating' && !document.querySelector('#agentMessages .agent-stream-pending')"), 'Reply stayed pending');
          turn.visibleReply = await js("document.getElementById('agentMessages').innerText");
          assert.ok(turn.visibleReply.includes(final.response.replace(/\*\*/g, '').slice(0, 25)));
          await shot(`03-answer-${index + 1}`); break;
        }
        await delay(200);
      }
      if (reliability === 'editor-change') assert.equal(report.editorChangeCancelled, true, 'Context invalidation was not exercised');
      else if (cancelTurn) assert.equal(turn.stopClicked, true, 'Cancellation was not exercised');
      else if (disconnectTurn) assert.equal(turn.terminal?.event, 'response_error', 'Disconnect was not reported');
      else assert.equal(turn.terminal?.event, 'response_completed', 'Turn timed out');
      await persist();
    }
    if (editing) {
      const proposal = await until(() => js(`${app}.session.getState().layoutProposal`), 'Trusted edit preview did not reach the editor', 30000);
      const pendingState = await js(`${app}.session.getState()`);
      assert.deepEqual(pendingState.layout, before.layout, 'Preview mutated the editor');
      assert.equal(pendingState.baseRevision, before.baseRevision);
      assert.equal(pendingState.dirty, false);
      assert.equal(report.requests.filter(r => /\/facility-layouts\/[^/]+\/[^/]+\/(approvals|apply)$/.test(r.url)).length, 0);
      assert.equal(proposal.alternatives[0].strategy, 'exact-operations-v1');
      const expected = content(before.layout);
      if (authoring) {
        const ghost = proposal.alternatives[0].ghostPreview.layout;
        const zone = expected.zones.find(z => z.label === 'Cardio - 18 Stations');
        const color = ghost.zones.find(z => z.zoneId === zone.zoneId).extensions.style.fillColor;
        assert.equal(color.toLowerCase(), '#35393e');
        zone.extensions.style.fillColor = color;
        const surfaces = ghost.extensions.facilityFloorSurfaces.surfaces;
        assert.equal(surfaces.length, 1);
        assert.deepEqual(surfaces[0].boundary, zone.boundary);
        assert.equal(surfaces[0].elevation, zone.floorElevation);
        assert.equal(surfaces[0].material, 'rubber');
        assert.equal(surfaces[0].color, '#35393e');
        assert.equal(surfaces[0].roughness, .85);
        expected.extensions.facilityFloorSurfaces = structuredClone(ghost.extensions.facilityFloorSurfaces);
        const originalIds = new Set((expected.floorMarkings || []).map(m => m.markingId));
        const additions = ghost.floorMarkings.filter(m => !originalIds.has(m.markingId));
        assert.equal(additions.length, 1);
        const marking = additions[0];
        assert.equal(marking.markingType, 'solid_line');
        assert.equal(marking.semanticRole, 'decorative');
        assert.equal(marking.label, 'Demo gold line');
        assert.deepEqual(marking.transform, {position:{x:24,y:0,z:9},rotationDegrees:0});
        assert.equal(marking.width, 1); assert.equal(marking.depth, .15);
        assert.equal(marking.fillColor.toLowerCase(), '#c99b39');
        assert.equal(marking.strokeColor.toLowerCase(), '#c99b39');
        assert.equal(marking.opacity, 1); assert.equal(marking.text, '');
        const originalMarkings = ghost.floorMarkings.filter(m => originalIds.has(m.markingId));
        assert.deepEqual(originalMarkings, expected.floorMarkings || []);
        expected.floorMarkings = structuredClone(ghost.floorMarkings);
        const add = proposal.alternatives[0].operations.find(op => op.op === 'add_floor_marking');
        assert.ok(add && !add.markingId && !add.floorMarking.markingId, 'Agent did not exercise generated marking ID');
        report.authoringVerified = {zoneFill:true,rubberFloor:true,generatedMarking:true};
      } else expected.placements.find(p => p.placementId === 'pl-e1f4de8e9d905153b1179895').transform.position = {x:15.2,y:0,z:2.1};
      assert.deepEqual(content(proposal.alternatives[0].ghostPreview.layout), expected, 'Unexpected proposal changes');
      await shot('04-edit-preview');
      await click('[data-candidate-action="accept"]');
      await until(() => js(`!!${app}.session.getState().lastApprovedOperationCommit && !${app}.session.getState().busy`), 'Approved operation did not commit', 60000);
      const applied = await js(`${app}.session.getState()`);
      assert.deepEqual(content(applied.layout), expected);
      assert.equal(applied.dirty, false);
      assert.equal(applied.canUndo, true);
      report.approvedOperation = applied.lastApprovedOperationCommit;
      await shot('05-edit-approved');
      if (authoring) {
        await click('[data-view="3d"]');
        await until(() => js(`${app}.workspace.viewMode === '3d' && ${app}.workspace.threeAdapter.getDiagnostics().demandRendering.renderedFrames > 0`),
          'The approved authoring result did not render in 3D');
        await delay(1500);
        await shot('05b-authoring-3d');
        const rect = await js(`(()=>{const e=${app}.workspace.root.querySelector('canvas');const r=e.getBoundingClientRect();
          return {x:Math.round(r.x),y:Math.round(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
        assert.ok(rect.width > 200 && rect.height > 200, '3D viewport has no usable extent');
        const capture = await withDeadline(window.webContents.capturePage(rect), '3D viewport capture');
        const pixels = capture.toBitmap();
        const colors = new Set();
        for (let p = 0; p + 3 < pixels.length; p += 4 * 37) colors.add(pixels.readUInt32LE(p));
        assert.ok(colors.size > 100, '3D viewport is blank');
        report.authoringVerified.rendered3d = {width:rect.width,height:rect.height,sampledColors:colors.size};
        await click('[data-view="plan"]');
      }
      await click('[data-facility-ribbon-command="undo"]');
      const undo = await until(() => js(`${app}.session.getState().layoutProposal`), 'Undo preview did not appear', 30000);
      assert.equal(undo.alternatives[0].strategy, 'exact-undo-v1');
      assert.deepEqual(content(undo.alternatives[0].ghostPreview.layout), content(before.layout));
      assert.deepEqual(content(await js(`${app}.session.getState().layout`)), expected, 'Undo saved before approval');
      await shot('06-undo-preview');
      await click('[data-candidate-action="accept"]');
      await until(() => js(`!${app}.session.getState().busy && !${app}.session.getState().layoutProposal && ${app}.session.getState().baseRevision !== ${JSON.stringify(applied.baseRevision)}`), 'Approved undo did not commit', 60000);
      await shot('07-undo-approved');
      report.approvalCalls = report.requests.filter(r => r.method === 'POST' && /\/facility-layouts\/[^/]+\/[^/]+\/approvals$/.test(r.url)).length;
      report.applyCalls = report.requests.filter(r => r.method === 'POST' && /\/facility-layouts\/[^/]+\/[^/]+\/apply$/.test(r.url)).length;
      report.undoPreviewCalls = report.requests.filter(r => r.method === 'POST' && /\/operation-undo-preview$/.test(r.url)).length;
      assert.equal(report.approvalCalls, 2);
      assert.equal(report.applyCalls, 2);
      assert.equal(report.undoPreviewCalls, 1);
    }
    if (memoryCheck) {
      assert.equal(new Set(report.turns.map(t => t.conversationId)).size, 1);
      assert.equal(new Set(report.turns.map(t => t.agentSessionId)).size, 1);
      assert.equal(report.switchBlockedWhileBusy, true);
      await click(`.ip-layout-sheet-tab[data-layout-id="${profile.startupLayoutId}"]`);
      await until(() => js(`${app}.session.getState().layout.layoutId === ${JSON.stringify(profile.startupLayoutId)}`), 'Could not return to gym');
    }
    const after = await js(`${app}.session.getState()`);
    if (editing) {
      assert.deepEqual(content(after.layout), content(before.layout));
      assert.equal(after.dirty, false);
      assert.equal(after.lastApprovedOperationCommit, null);
      report.editorRestored = true;
    } else if (reliability === 'editor-change') {
      for (const field of ['layout', 'baseRevision', 'draftRevision', 'dirty']) assert.deepEqual(after[field], before[field], field);
      report.editorRestored = true;
    } else {
      for (const field of ['layout', 'baseRevision', 'draftRevision', 'dirty', 'history']) assert.deepEqual(after[field], before[field], field);
      report.editorUnchanged = true;
    }
    report.status = 'passed';
    if (reliability === 'before-restart') await fs.writeFile(path.join(profile.dataRoot, 'recovery-checkpoint.json'), JSON.stringify(report));
  } catch (error) {
    report.status = 'failed'; report.error = error.message;
    await shot('failure').catch(() => {});
    throw error;
  } finally {
    report.sourceUnchanged = hash(await fs.readFile(source.originalPath)) === source.originalSha256;
    const copy = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', profile.startupLayoutId + '.json');
    report.copyUnchanged = hash(await fs.readFile(copy)) === source.originalSha256;
    if (editing) report.copyRestored = JSON.stringify(content(JSON.parse(await fs.readFile(copy, 'utf8')))) === JSON.stringify(content(JSON.parse(await fs.readFile(source.originalPath, 'utf8'))));
    if (second) {
      report.secondSourceUnchanged = hash(await fs.readFile(second.originalPath)) === second.sha256;
      report.secondCopyUnchanged = hash(await fs.readFile(second.copyPath)) === second.sha256;
      if (!report.secondSourceUnchanged || !report.secondCopyUnchanged) report.status = 'failed';
    }
    report.saveCalls = report.requests.filter(r => r.method === 'POST' && /\/save(?:\?|$)/.test(r.url)).length;
    if (!report.sourceUnchanged || !(editing ? report.copyRestored : report.copyUnchanged) || report.saveCalls) report.status = 'failed';
    await persist();
    window.webContents.debugger.removeListener('message', onNetwork);
    window.webContents.debugger.detach();
  }
}
module.exports = { run, withDeadline };
