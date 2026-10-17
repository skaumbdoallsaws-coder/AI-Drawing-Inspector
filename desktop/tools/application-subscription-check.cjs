'use strict';
// Opt-in native smoke check: actual Sage UI, saved document reads, no editing.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { captureStream } = require('./codex-stream-evidence.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function run({ window, profile, output }) {
  assert.equal(profile.codexRuntime.authMode, 'chatgpt_plan');
  assert.equal(profile.codexRuntime.allowPaidInference, false);
  const report = { status: 'running', authMode: 'chatgpt_plan', apiFallback: false, turns: [], requests: [] };
  await fs.mkdir(output, { recursive: true });
  const js = code => window.webContents.executeJavaScript(code, true);
  const until = async (check, label) => {
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) { const result = await check(); if (result) return result; await delay(250); }
    throw new Error('Subscription desktop check timed out: ' + label);
  };
  const pending = new Map();
  const onNetwork = (_event, method, params) => {
    if (method === 'Network.requestWillBeSent' && params.request.url.startsWith(profile.origin + '/api/')) {
      report.requests.push({ method: params.request.method, url: params.request.url });
      if (params.request.url.endsWith('/api/agent/chat/v2/stream')) {
        const request = JSON.parse(params.request.postData);
        const turn = { turnId: request.client_turn_id, prompt: request.message };
        report.turns.push(turn);
        pending.set(params.requestId, captureStream(window.webContents.debugger, params.requestId, turn));
      }
    }
    pending.get(params.requestId)?.(method, params);
  };
  window.webContents.debugger.attach('1.3');
  await window.webContents.debugger.sendCommand('Network.enable');
  window.webContents.debugger.on('message', onNetwork);
  try {
    window.maximize();
    const state = 'window._trainFacilityLayoutAuthoringApp.session.getState()';
    await until(() => js('!!window._trainFacilityLayoutAuthoringApp?.session?.getState().loaded'), 'layout');
    const before = await js(state);
    assert.equal(before.layout.layoutId, profile.startupLayoutId);
    assert.equal(before.dirty, false, 'Refuse to test with an unsaved layout');
    report.layoutId = before.layout.layoutId;
    report.revision = before.baseRevision;
    await js("window._selectAgent('deviation-analyst');if(!document.getElementById('agentInput').getBoundingClientRect().width)window._toggleAgentPanel();");
    report.editModeControl = await js(`(()=>{
      const select=document.getElementById('agentFacilityEditMode');
      const rect=select.getBoundingClientRect();
      const previous=select.value;
      select.value='preview';select.dispatchEvent(new Event('change',{bubbles:true}));
      const previewPersisted=localStorage.getItem('inspectorpro.sage.facilityEditMode')==='preview';
      select.value=previous;select.dispatchEvent(new Event('change',{bubbles:true}));
      return {value:select.value,previewPersisted,visible:rect.width>0&&rect.height>0,
        bounds:{x:rect.x,y:rect.y,width:rect.width,height:rect.height}};
    })()`);
    assert.equal(report.editModeControl.visible, true);
    assert.equal(report.editModeControl.previewPersisted, true);
    await until(() => js("!!document.querySelector('#agentChatNewBtn:not([disabled])')"), 'new conversation');
    await js("document.getElementById('agentChatNewBtn').click()");
    await delay(750);
    const prompt = 'Inspect the saved layout and report its name, zone count and placed-asset count. Use the actual InspectorPro tools. Do not edit, preview or save anything. Keep it under 60 words.';
    await js(`(()=>{const input=document.getElementById('agentInput');input.focus();input.value=${JSON.stringify(prompt)};input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    window.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Return' });
    window.webContents.sendInputEvent({ type: 'keyUp', keyCode: 'Return' });
    await until(() => Promise.resolve(report.turns[0]?.terminal), 'Sage response');
    const terminal = report.turns[0].terminal;
    assert.equal(terminal.event, 'response_completed');
    const inspection = terminal.final.codex_inspection;
    assert.equal(inspection.authMode, 'chatgpt_plan');
    assert.equal(inspection.apiFallback, false);
    assert.equal(inspection.engineeringChanges, 0);
    assert.ok(inspection.verifiedToolCalls.some(call => call.ok));
    const after = await js(state);
    assert.equal(after.dirty, false);
    assert.equal(after.baseRevision, before.baseRevision);
    assert.deepEqual(after.layout, before.layout);
    report.sourceUnchanged = true;
    await delay(500);
    const shot = await window.webContents.capturePage();
    assert.equal(shot.isEmpty(), false);
    await fs.writeFile(path.join(output, 'subscription-sage.png'), shot.toPNG());
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.failure = error.message;
    throw error;
  } finally {
    window.webContents.debugger.removeListener('message', onNetwork);
    window.webContents.debugger.detach();
    await fs.writeFile(path.join(output, 'subscription-desktop-check.json'), JSON.stringify(report, null, 2));
  }
}
module.exports = { run };
