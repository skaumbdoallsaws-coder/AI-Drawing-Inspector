# Managed recovery startup timing and Undo status recapture

Updated: 2026-09-14. The prior ten-case native recovery acceptance stands. Apply and Undo status-bar captures are verified; the UI follow-up is closed. General editing and embedded browsing remain gated.

## Native follow-up closed

**The Apply and Undo status-bar follow-up is closed.** The ordinary unelevated Undo recapture `20260914-164703-058` passed all five recovery checks; the screenshot was inspected and shows `Unsaved changes | 1 selected | Plan view | select` without the stale interruption error. Exact draft, selection and Undo restoration, one durable read-only lookup, once-only transaction endpoints, zero Save calls, process cleanup and both backend resource receipts were verified. Source/isolated saved layouts and the earlier failed checkpoint remain unchanged.

Backend startup took 13.479 s and 18.706 s. All nine spatial jobs completed; the longest execution was 430.037 ms. The earlier intermittent timeout causes remain unresolved. Retain their diagnostics as reliability follow-ups; this successful recapture does not establish a performance fix or rewrite the previous failures.

[Native result](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/check.json), [inspected screenshot](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/managed-recovery.png), and [independent evidence audit](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058-independent-audit.json). The earlier ten-case managed recovery acceptance stands. General editing and embedded browsing remain gated. No application code, tests or native checks were run or changed during this documentation review.

## Historical startup failure

The unelevated two-case [native matrix](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-081001-547/native-matrix.json) passed Apply and stopped before Undo's Electron launch. Apply's screenshot was inspected: its bottom bar reads `Unsaved changes | 1 selected | Plan view | select`, without the stale interruption error. Its five recovery checks, exact frames, once-only endpoints, zero Save calls and backend cleanup passed.

Undo's case envelope lasted 47.406 seconds, including startup supervision and cleanup. This is not an exact backend import measurement. Its backend log contains one untimestamped library-selection message. There is no worker/config/transaction-registry/recovery-journal evidence for Undo because the readiness deadline expired before the native worker launched. Process termination and output-stream closure were confirmed. The application cleanup receipt is missing, so resource cleanup for that failed run remains unverified. The original failed checkpoint and source/isolated layout hashes remain unchanged.

The [independent evidence audit](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-081001-547-independent-audit.json) records the saved observations. Earlier successful, instrumented rendering runs took 12.901–38.713 seconds from their checkpoint clock to application lifespan startup. Those different harness runs establish timing variability, not this failure's cause.

## Diagnostic gap and implementation

The facility backend imports `run-rendering-backend.py` under a module name. Its existing checkpoints were enabled only when that file was executed as `__main__`, so the facility path suppressed server-import and lifespan diagnostics. This explains the missing phase evidence; it does not explain the slow import itself.

The explicitly executed facility `--serve` entry now flushes the existing bootstrap marker before bulk imports and opts into the shared checkpoint reporter. Elapsed checkpoint time starts at wrapper entry. Fixed phase records cover wrapper preparation, application import, recovery registry and catalog initialization, asset mounting, lifespan startup, and the existing cleanup/receipt path. Ordinary module imports remain silent. Checkpoints carry fixed phase metadata, process/instance identity and timing; they do not serialize credentials, arguments or draft payloads.

The managed supervisor records spawn/readiness/runtime-verification timestamps and monotonic durations. It retains bounded, owned-process checkpoint summaries at readiness, failure, and final cleanup. Partial/missing/foreign diagnostics do not become proof of readiness. Diagnostic projection failures do not replace the primary startup error. Public identity, private runtime identity, original process ownership, and the matching resource-cleanup receipt remain mandatory.

The readiness timeout stays **45 seconds**. No retry, lease, Save, recovery, application-startup workload, or production-shell permission change was made.

## Fresh measurement and verification

One fresh isolated **Undo engine** case exercised the initial backend and its managed restart. It passed all five recovery checks with zero Save calls, once-only endpoints, unchanged saved layouts and verified cleanup for both owned processes. No Electron renderer was launched in this measurement.

| Measurement | Initial backend | Restarted backend |
| --- | ---: | ---: |
| Supervisor spawn-to-verified-runtime time | 7.063 s | 5.249 s |
| Application import phase | 6.439 s | 4.613 s |
| Recovery catalog build phase | 9 ms | 10 ms |
| Wrapper entry to lifespan startup | 6.921 s | 4.947 s |

[Measured Undo engine evidence](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-undo-startup-20260914-083301/undo-success/check.json). The earlier slow startup did not reproduce; its precise cause remains unknown. These timings do not justify claiming that startup performance was fixed or that the native Undo recapture passed.

**126 Python tests passed**, including 174 subtests, covering existing lifecycle/cleanup, evidence parsing, facility boundaries and supervision plus the new opt-in/timing checks. The [regression log](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-startup-regression-tests.log) is retained. Independent code review found no change to readiness, ownership or cleanup authority. No unchanged full native matrix, Apply capture, empty-window or asset-rendering check was repeated.

## Retained diagnostic procedure

This recapture has passed and its screenshot has been inspected. No additional unchanged run is requested.

The [Undo-only launcher](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/check-inspectorpro-undo-status.ps1) remains available for a future relevant regression. It creates fresh isolated data and retains sandboxing. Earlier native runs were performed in ordinary unelevated PowerShell; none was launched during this documentation review.

Keep the diagnostic implementation and earlier failure artifacts. A future spatial failure should be correlated by failed edit, job ID and backend instance; a startup failure uses its own checkpoints and cleanup receipt. Timeout causes remain unresolved. Do not increase the deadlines or repeat the full matrix solely to close this already verified UI follow-up.
