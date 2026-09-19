'use strict';
const { performance } = require('node:perf_hooks');

function setupError(error) {
  const result = { message: String(error?.message || error).slice(0, 1024) };
  if (typeof error?.code === 'string') result.code = error.code.slice(0, 128);
  if (Number.isInteger(error?.status)) result.status = error.status;
  if (typeof error?.details?.jobId === 'string' && /^spatial-job-\d+$/.test(error.details.jobId)) {
    result.details = { jobId: error.details.jobId };
  }
  return result;
}

async function setupStep(report, save, name, operation) {
  report.stage = name;
  const record = { name, startedAt: new Date().toISOString(), status: 'running' };
  (report.setupSteps ||= []).push(record);
  await save();
  const started = performance.now();
  let failure;
  let failed = false;
  try {
    const result = await operation();
    record.status = 'passed';
    return result;
  } catch (error) {
    failure = error;
    failed = true;
    record.status = 'failed';
    record.error = setupError(error);
    throw error;
  } finally {
    record.elapsedMs = Math.max(0, performance.now() - started);
    record.finishedAt = new Date().toISOString();
    try { await save(); }
    catch (error) {
      if (!failed) throw error;
      // Retain the operation's primary error if diagnostic persistence fails.
      try { if (failure && typeof failure === 'object') failure.setupDiagnosticWriteFailed = true; }
      catch (_) { /* A frozen thrown value must still remain the primary failure. */ }
    }
  }
}

async function editLabelInRenderer(evaluate, id, label) {
  // Rejected executeJavaScript promises can lose custom Error fields in IPC.
  // Return only bounded diagnostic data; never return the HTTP body or headers.
  const reply = await evaluate(`(async()=>{
    try {
      const session=window.__facilityHarness.session;
      session.select(${JSON.stringify(id)});
      await session.editZoneLabel(${JSON.stringify(id)},${JSON.stringify(label)});
      return {ok:true};
    } catch (error) {
      const evidence=(${setupError.toString()})(error);
      return {ok:false,error:evidence};
    }
  })()`);
  if (!reply || reply.ok !== true) {
    const evidence = setupError(reply?.error || new Error('Renderer edit returned no result'));
    throw Object.assign(new Error(evidence.message), evidence);
  }
}

module.exports = { setupError, setupStep, editLabelInRenderer };
