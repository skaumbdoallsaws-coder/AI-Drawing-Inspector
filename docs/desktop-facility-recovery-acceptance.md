# Facility-layout recovery and loaded-asset acceptance

Updated: 2026-09-13. Scope: explicitly authorized isolated test harness.

## Accepted native checkpoint

The ordinary native run `inspectorpro-facility-recovery-20260913-141702-926` passed both Electron phases. The [native run report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-141702-926/check.json) closes the isolated facility recovery and loaded-asset checkpoint, including the transform-audit finding.

- All 827 placements passed with zero transform mismatches; 9,418 instance matrices were audited with zero storage-format error. The `1e-5` tolerance is unchanged, and the 49 raw precision differences remain recorded.
- All 37 referenced GLBs were served and loaded. All 37 referenced library cards and thumbnails passed visibility/loading checks. Both saved screenshots were independently inspected during this follow-up; the full facility renders and the library capture shows populated cards and thumbnails. Per-card evidence covers entries outside the screenshot's current scroll position.
- Two manual edits followed by Close/Cancel, Close/Cancel during Apply and Undo, lost-acknowledgment recovery across two Electron processes, exact Undo restoration, and Close without Save passed. Save remained blocked before restoration and during unresolved recovery.
- Phase 1 recorded eight distinct transaction endpoints once each. Phase 2 retained those counts and added only the recovered Undo's two endpoints. Both phases recorded zero Save calls.
- Original and isolated saved-layout hashes remained unchanged. Both Electron worker exits and diagnostic-stream closure were confirmed; backend termination and its resource-cleanup receipt were verified. Electron descendant-process termination is not separately verified.

This follow-up inspected the saved reports and screenshots; it did not rerun native tests, regression suites, or the unchanged empty-window test. Only acceptance documentation changed. A minor encoding artifact is visible in the test-harness banner separators; it does not invalidate the scoped transform, asset, or recovery evidence.

The backend stayed running between Electron processes. Managed-backend restart, complete top-level desktop integration, other loaded workflows, live Sage in Electron, and ordinary unsaved-edit crash recovery outside the tested transaction boundaries remain unverified. General editing and embedded browsing remain gated.

## Managed-backend follow-up

All ten managed-backend recovery engine cases now pass with the real facility session and actual backend stop/restart. This covers pending Apply and Undo across success, failed startup, identity mismatch, expired lease, and another writer's ownership. Exact draft/selection/Undo contents, stable logical identity with a new process instance, read-only durable lookup, blocked Save, zero duplicate execution, unchanged saved-layout bytes, and unrelated-server survival were verified. See [managed-backend recovery evidence](desktop-managed-backend-recovery.md).

Native Electron acceptance for this new gate remains pending. The prepared launcher runs only the managed-recovery cases; the accepted empty-window and loaded-asset checkpoints need no unchanged rerun. General editing and browsing remain gated.

## What is implemented

- An explicitly installed facility-session recovery facade captures the complete editor frame, including draft, selected IDs, command batches, history cursor, proposal state, and transaction identity. A startup gate blocks editor mutation and Save before journal inspection or recovery restoration.
- Apply and Undo await a durable journal checkpoint before each transport phase. A lost reply retains the operation instead of silently rolling it back, replaying it, or saving.
- A facility adapter uses the existing lifecycle coordinator and recovery store. Close/Cancel checks exact state; transaction reconciliation requires matching backend/store/principal, document, owner, transaction, lease, and editor generation.
- Recovery is an explicit compare-and-swap restore followed by read-only authoritative transaction lookup and local adoption. Historical records are superseded only by an exact newer durable checkpoint after successful reconciliation and adoption.
- A separate native entry/preload/page is prepared to run the actual facility workspace in Electron. It does not enable the ordinary desktop shell. External browsing, native helpers, providers, and Save routes remain unavailable in this test backend.
- The parent owns the backend and two worker processes, retains diagnostic failures, requires worker termination and diagnostic EOF, and verifies the backend's matching resource-cleanup receipt.

## Isolated manual layout and assets

The fixture copies `fl-reference-manual-20260812` from the live project for read-only provenance, using a fresh backend/store identity and transaction store. It includes 827 placements, 45 zones, 8 routes, 50 floor markings, and all 37 referenced GLBs (373,260,908 bytes), plus their thumbnails and required published authority documents. Credentials and live recovery/transaction state are not copied.

Source and copied layout SHA-256:

`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`

The backend run served all 37 GLBs over HTTP with exact byte counts and hashes, exposed the referenced catalog entries, and rejected an unauthenticated layout read. The accepted native follow-up also verifies the real meshes, all placement transforms, and visible library cards/thumbnails.

## Recovery scenarios

| Scenario | Required evidence | Real session/backend result |
| --- | --- | --- |
| Two zone-label edits, Close, Cancel | Exact full editor frame; selected zone; both command batches and cursor retained | Passed |
| Close during Apply | Hold the actual acknowledgment after backend execution; retain request/transaction ID; Cancel and reconcile once | Passed |
| Close during Undo | Same held-acknowledgment race; exact manual draft/history restored | Passed |
| Lost Apply acknowledgment and restart | End first process while reply is withheld; second process restores same durable handle/frame | Passed |
| Reconciliation | Read-only owner/lease/transaction lookup; no transaction endpoint count changes during reconciliation | Passed |
| Recovered Undo | Exact two-edit manual editor frame restored | Passed |
| Close without Save | Explicit discard decision; zero Save requests; original and isolated saved bytes unchanged | Passed |
| Startup before restoration | The editor itself must block Save before recovery restoration, alongside the main adapter gate | Passed, including direct Save rejection before restore |
| Native meshes/library | Actual scene meshes and placement transforms; each referenced asset card and local thumbnail visible | Passed in accepted native run |

The earlier passing engine run is `outputs/facility-recovery-engine-20260913-v4/check.json`. Phase 1 executes exactly eight distinct transaction endpoints once each; phase 2 retains those counts and adds only the recovered Undo's prepare and acknowledgment, for ten total. The backend remains running between worker processes; this proves application-process restart, not a managed-backend restart.

The dedicated page hosts the real facility workspace, session, transport and Three adapter. It is not the complete top-level InspectorPro UI with its other workflows enabled.

The proposal is a bounded deterministic fixture built with the real operation kernel and artifact repository. Apply, Undo, leases, transaction state, editor mutations, and recovery persistence are real. This does not claim provider planning or live Sage acceptance.

## Earlier implementation diagnostics and regression coverage

The first integrated attempt found a test-proposal frame-normalization error: JSON numeric round-tripping did not retain the saved document's canonical representation. The fixture now calls the existing authoritative host normalizer before normal frame validation and journal replay. The successful second run retains all validation.

A report replacement failure on Windows exposed a diagnostics issue. Final writes now retain a separate uniquely named, flushed failure receipt when the normal report is held open, without replacing the original failure. Worker cleanup evidence cannot be reused across phases. Unit tests cover these failure paths.

Verification performed at the earlier implementation checkpoint (not rerun during this documentation update):

- 284 Node desktop tests passed, including the 35 focused recovery tests.
- 60 existing facility-session checks and six existing app checks passed.
- 127 Python tests executed: 126 passed, one symlink-creation capability test skipped.
- Final two-process real-session/backend recovery run passed with zero Save requests, ten distinct transaction endpoints executed once each, worker termination/pipe closure confirmed, and the matching backend cleanup receipt.
- The PowerShell launcher passed parser validation. Native diagnostic additions receive syntax/static checks; they do not supply a successful native run.

Independent review found and closed two additional cases: a lost native reconciliation reply could leave the Save method inconsistent with the blocked UI, and a legitimate already-completed Undo could be rejected during local adoption. Actual Save and installed mutations now reject unresolved authority; received `already_undone`/`ready` may adopt the exact root without a second Undo acknowledgment. Stale local-only restoration remains rejected.

## Historical restricted native attempt

`outputs/facility-recovery-native-20260913-v3/check.json` records a failed native attempt using the same pinned Electron 44.3.0 executable, SHA-256 `e048632e03fabc96de5e10afbebc0aa31f4e1674155ea3d270597fe7523f9d80`. The backend and all 37 asset HTTP checks passed. The first Electron worker exited with code 3221225477 (`0xC0000005`) before producing a facility-stage report; its diagnostic stream contained only a newline. This does not establish where native startup failed or its cause.

Worker termination and diagnostic EOF/closure were confirmed. The backend also terminated with its matching resource-cleanup receipt. Both manual-layout hashes remained unchanged. No native screenshots or visual acceptance were produced. The second worker was not launched. Descendant-process termination is not separately verified.

The prepared native entry adds flushed early progress markers and bounded `progress.json` evidence to distinguish script entry, configuration, app/window creation, page loading, facility readiness, and scenario execution on the next ordinary run. Security settings and the pinned binary are unchanged.

## Native check launcher for future regressions

The prepared ordinary-terminal launcher is:

```powershell
& "C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-facility-recovery.ps1"
```

It refuses an Administrator token, prepares a new isolated copy for each run, uses the installed pinned Electron binary, and runs only facility recovery/loaded-asset checks. It does not run the empty-window fixture. It preserves prior test roots and reports, keeps Chromium sandboxing, and does not edit the live layout.

The accepted native run completed the real-mesh, transform, library, screenshot, and two-process recovery checks. Keep this launcher for future relevant regressions; no unchanged rerun is required to close this checkpoint.

## Remaining acceptance boundaries

The accepted run was supplied from an ordinary unelevated terminal. This follow-up reviewed that evidence without claiming to have launched the native run itself. Chromium sandboxing remained enabled.

This is one facility workflow integration slice. Full InspectorPro workflow switching, loaded drawing/assembly workflows, managed backend restart, voice, live Sage in Electron, ordinary unsaved-edit crash recovery outside the tested transaction boundaries, and embedded research browsing remain separate acceptance gates. General desktop editing is not enabled by this slice.

## Source handoff

The prepared source bundle contains only the two changed frontend modules, new explicit recovery modules/harness/tests, and this report. It contains no runtime store, secret, manual-layout file, or GLB. `outputs/inspectorpro-facility-recovery-handoff.json` records the exact file hashes and whether project installation completed. The patch and source ZIP are beside that receipt. The ordinary desktop main/preload hashes are verified unchanged.

## Accepted native evidence

- [native run report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-141702-926/check.json)
- [Facility screenshot](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-141702-926/phase-1/facility-real-glbs.png)
- [Asset-library screenshot](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-141702-926/phase-1/facility-asset-library.png)
- [Asset and matrix evidence](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-141702-926/phase-1/facility-asset-evidence.json)
- [Restart recovery report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-facility-recovery-20260913-141702-926/phase-2/report.json)
