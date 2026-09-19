# Managed recovery spatial setup investigation

Updated: 2026-09-14. The prior ten-case native recovery acceptance stands. Apply and Undo status-bar captures are verified; the UI follow-up is closed. General editing and embedded browsing remain gated.

## Native follow-up closed

**The Apply and Undo status-bar follow-up is closed.** The ordinary unelevated Undo recapture `20260914-164703-058` passed all five recovery checks; the screenshot was inspected and shows `Unsaved changes | 1 selected | Plan view | select` without the stale interruption error. Exact draft, selection and Undo restoration, one durable read-only lookup, once-only transaction endpoints, zero Save calls, process cleanup and both backend resource receipts were verified. Source/isolated saved layouts and the earlier failed checkpoint remain unchanged.

Backend startup took 13.479 s and 18.706 s. All nine spatial jobs completed; the longest execution was 430.037 ms. The earlier intermittent timeout causes remain unresolved. Retain their diagnostics as reliability follow-ups; this successful recapture does not establish a performance fix or rewrite the previous failures.

[Native result](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/check.json), [inspected screenshot](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/managed-recovery.png), and [independent evidence audit](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058-independent-audit.json). The earlier ten-case managed recovery acceptance stands. General editing and embedded browsing remain gated. No application code, tests or native checks were run or changed during this documentation review.

## Historical spatial failure

The ordinary unelevated native run `20260914-133749-350` passed backend startup in **20.429 seconds**, within the unchanged 45-second deadline. It then failed with `Facility Layout spatial execution exceeded its time limit.` during one of the initial two zone-label edits, before proposal creation, Apply, Undo, or backend restart.

The saved report did not distinguish the first edit from the second and did not retain the spatial job ID or its queue/execution timing. Both label edits use the real preview/operation kernel, including baseline and candidate spatial validation. The error belongs to that execution path, independently of backend readiness. Existing production spatial execution uses a five-second deadline.

Worker and backend termination, closed diagnostic streams, the matching application resource-cleanup receipt, and unrelated-server survival were verified. Source and isolated saved layouts were unchanged. No transaction registry was created before this failure, so this particular report does not supply a numerical Save counter. The earlier failed recovery checkpoint remains unchanged.

[Native failure audit](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-133749-350-independent-audit.json) and [original native result](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-133749-350/undo-success/check.json).

## Exact-fixture profiling

A read-only probe used the failed fixture's 827 placements, 45 zones, eight routes and 37 copied asset definitions with the production spatial context and diagnostic function. Unprofiled diagnostics completed in **209 ms wall time / 203 ms thread CPU**. A cProfile run completed in 960 ms with an identical result hash. Context preparation took approximately 29 ms.

This excludes executor queuing, HTTP, routing, native rendering and concurrent host load. The probe used a separate ten-second cooperative investigation bound; the production five-second deadline was not changed. It did not reproduce the native timeout and does not establish its cause. There is no evidence here to justify increasing tolerances, bypassing preview validation, or claiming a geometry performance fix.

[Read-only profile](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/failed-native-spatial-profile-20260914.json).

## Diagnostic changes

All changes are in the explicitly authorized test harness:

- `facility-managed-setup.cjs` persists each initial snapshot, manual edit and proposal-preparation stage before execution and after settlement. Errors retain bounded message/code/status and a validated spatial job ID. The native adapter returns these fields across Electron IPC, which can otherwise drop custom fields on a rejected JavaScript error.
- `facility_spatial_diagnostics.py` observes the existing executor instance only when the managed-harness flag is enabled. Flushed `INSPECTORPRO_FACILITY_SPATIAL_JOB` records include backend instance/PID, job ID, configured deadline, queue duration, execution duration, thread CPU and cancellation/error outcome.
- The observer returns the original job and future and uses the same pool, capacity, token and deadline. It neither retries operations nor changes results. It does not serialize layout arguments or credentials. Diagnostic output is synchronous and can add overhead; these are instrumented measurements, not a zero-overhead performance benchmark.

No production geometry, routing, preview validation, ownership, transaction, Save, startup-timeout or ordinary desktop capability was changed.

## Verification and fresh engine result

**54 Node tests passed. 56 Python tests and 16 subtests passed.** These include renderer error-field preservation, first/second-edit failure staging, diagnostic-write failures, real executor queue/capacity, cancellation, typed errors, idempotent installation and preservation of the original job/future/deadline. Logs: [Node](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/spatial-setup-node-tests.log), [Python](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/spatial-setup-python-tests.log).

One fresh isolated Undo **engine** case passed both manual edits (4.624 s and 4.164 s end to end), proposal preparation, and Close/Cancel state preservation. End-to-end edit time includes more than the spatial job itself. All nine observed spatial jobs completed without cancellation: execution ranged from 0.576 to 1149.670 ms and queue time from 0.106 to 2.362 ms. The native timeout did not reproduce. The case reached pending Undo and started the managed restart.

That restart failed separately: the second backend exceeded the 45-second readiness deadline, with `server-import-starting` as its last checkpoint. Its application resource-cleanup receipt is missing, so resource cleanup for that second process remains unverified. Owned-process termination and diagnostic-stream closure were confirmed; the first backend's resource receipt was verified. The unrelated fixture survived. Durable endpoint counts were once each, the Save counter was zero, and saved layout hashes were unchanged.

This engine case is **failed overall**. Its setup observations validate the new diagnostics, not successful recovery or native screenshot acceptance. The retained worker report stopped at the restart stage; use the outer `check.json` for the final failed outcome. The original native spatial-timeout cause remains unresolved, as does the reason for variable backend import time.

[Fresh engine result](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-spatial-setup-20260914-163002/undo-success/check.json) and [setup report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/managed-spatial-setup-20260914-163002/undo-success/report.json).

## Retained diagnostic procedure

This recapture has passed and its screenshot has been inspected. No additional unchanged run is requested.

The [Undo-only launcher](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/check-inspectorpro-undo-status.ps1) remains available for a future relevant regression. It creates fresh isolated data and retains sandboxing. Earlier native runs were performed in ordinary unelevated PowerShell; none was launched during this documentation review.

Keep the diagnostic implementation and earlier failure artifacts. A future spatial failure should be correlated by failed edit, job ID and backend instance; a startup failure uses its own checkpoints and cleanup receipt. Timeout causes remain unresolved. Do not increase the deadlines or repeat the full matrix solely to close this already verified UI follow-up.
