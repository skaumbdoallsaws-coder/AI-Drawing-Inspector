'use strict';
const fs = require('node:fs');
const path = require('node:path');

// Main-process harness diagnostics only. Never receives renderer-selected paths.
function createCheckpointDiagnosticSink(output) {
  if (!path.isAbsolute(output || '')) throw new TypeError('Absolute harness output required');
  const filename = path.join(output, 'recovery-store-diagnostics.jsonl');
  return event => {
    const line = JSON.stringify({ recordedAt: new Date().toISOString(), ...event }) + '\n';
    // The parent also retains this stream incrementally, including on failure.
    try { fs.writeSync(2, 'INSPECTORPRO_RECOVERY_CHECKPOINT ' + line); } catch (_) {}
    let descriptor;
    try {
      descriptor = fs.openSync(filename, 'a', 0o600);
      fs.writeFileSync(descriptor, line);
      fs.fsyncSync(descriptor);
    } catch (error) {
      try { fs.writeSync(2, 'INSPECTORPRO_RECOVERY_DIAGNOSTIC_WRITE_FAILED ' + (error.code || 'unknown') + '\n'); } catch (_) {}
    } finally {
      if (descriptor !== undefined) { try { fs.closeSync(descriptor); } catch (_) {} }
    }
  };
}
module.exports = { createCheckpointDiagnosticSink };
