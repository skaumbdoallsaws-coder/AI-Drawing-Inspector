# Desktop runtime and research implementation

Updated: 2026-09-15, America/Chicago.

## Status

**The entire desktop-shell plan is not complete.** The normal-entry facility
lifecycle checkpoint now has native evidence, and an isolated research-pane
implementation has passed its functional checks. General editing, provider
execution, Save and research browsing remain gated outside the acceptance
harness. This is not an all-workflow desktop release.

The native visibility finding is closed by
`inspectorpro-runtime-20260915-162852-b2a8888f`: both wide and narrow owned-window
composites were captured on the first attempt and inspected, together with the
real library and 3D scene. This accepts that capture checkpoint, not the whole
desktop product. Earlier accepted isolated checkpoints retain their scope.

The subsequent workflow-coverage batch adds a conservative Close/Restart
guard. Loaded or unsettled non-facility work now blocks lifecycle actions;
this does not add recovery support or enable editing for those workflows.

The subsequent [research security follow-up](desktop-research-security-acceptance.md)
passes native page/frame/dedicated/shared/service-worker isolation, local network
denial, popup ownership and download cancellation. It also fixes stale navigation
failures and suspension ownership. The full Node suite now passes 599 tests.

**Latest combined run: `inspectorpro-runtime-20260915-173342-aa0dafb0`, passed.**
The project-owned PowerShell launcher completed end to end. Its five screenshots
were inspected, and the saved native/research/cleanup receipts were revalidated
using the current validators. The full shell remains gated for the requirements
listed below.

Current evidence: [launcher](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-173342-aa0dafb0/native-launch.json),
[recovery](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-173342-aa0dafb0/native/runtime-integration-check.json),
[research](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-173342-aa0dafb0/native/research-check.json),
[cleanup](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-173342-aa0dafb0/native/runtime-final-result.json),
and [visual review](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-173342-aa0dafb0/visual-review.json).
The source snapshot is `source-20260915-173310-203173fb`, manifest
`c198059b484006fc0f68ccdfdddbf0bdad97cfc8f287de56b989dc2bd513c3f9`.
Thirteen core/driver files match the project. All three owned backends closed
normally with verified resource/stream closure; startups were 14.597 s, 10.825 s
and 23.474 s. Zero Save calls and the unchanged manual-layout hash were verified.
These timings do not close the prior intermittent timeout findings.

## Implemented

| Area | Behavior and ownership |
| --- | --- |
| Normal entry | Verified the existing managed entry, protected backend and actual facility session, not a replacement HTML fixture. |
| Research host | `desktop/src/research-pane.cjs`: main-owned WebContentsView tabs, exact-URL deduplication, eight-tab limit, independent navigation, hide/reopen, expanded narrow mode, reload, stop and explicit external-browser confirmation. |
| Isolation | Research has a separate session-only partition, sandbox/context isolation, no Node, no application preload, no device/media/permission grants and no application credential headers. |
| Network | `research-policy.cjs` and `research-proxy.cjs`: HTTPS public IPv4 only, private/reserved/loopback and numeric aliases refused. A CONNECT proxy resolves and pins the actual public address; there is no DIRECT or loopback bypass. Mixed public/private DNS answers fail closed. IPv6, non-443 services and HTTP are intentionally unsupported. |
| Controls | Local trusted controls have their own restricted session/preload and sender/main-frame checks. Untrusted page titles use text content. Tab popups do not create native windows or receive a bridge. Downloads require native destination selection, have cancellation/status, and never auto-execute. |
| Workspace continuity | The existing application webContents remains alive. Pane transitions resize available application width, release pointer lock, and hide research for application overlays/lifecycle work. Multiple suspension owners cannot release one another's lock. Reload follows the focused research tab or the existing guarded application reload. |
| Responsive toolbar | The shared toolbar now uses its available body-container width, not the entire native viewport width. Wide research no longer overlaps Ready/search with application tools. |
| Snapshot repair | The safe snapshot includes Python source under `desktop/runtime`; previously the generic runtime-data exclusion omitted the backend launcher. It still excludes runtime data, credentials, dependencies and links. |
| Diagnostics | Real mesh/group/transform diagnostics survive failure. Native capture only accepts the owned window. Enumeration waits are bounded; the PrintWindow fallback uses an absolute PowerShell path and refuses blank output. Separate component images never masquerade as a native composite. |
| Windows visibility | Backend/CLI helpers remain hidden. Only the actual Electron application launch omits `SW_HIDE`, leaving its first window display under application control. Capture checks require `isVisible`, not merely focus or painted renderer pixels. |
| Workflow guard | The actual application's observers report loaded/dirty/busy/pending state for drawing, model, assembly, Process Map, documentation, training, report, sessions, chat/voice and curation. Missing or stale coverage blocks. Checks occur before preparation and again before commit/restart. Late refusal cancels the temporary facility freeze without discarding either workflow. |
| Reproducibility | `desktop/tools/check-runtime.ps1` creates a fresh source snapshot and isolated fixture and invokes the project-owned acceptance runner. No dependence on copied temporary task scripts. |

The application-startup patch also collapses the unrelated Drawing sidebar
when entering the authorized facility workspace. Existing web entry remains
separate. No original layout, catalog entry, GLB or prior failure receipt was
modified.

## Verified behavior

The earlier functional run used the pinned Electron 44.3.0 binary and Python 3.14 from an
unelevated process. It started and stopped three owned backends. Startup times
were 15.605 s, 15.227 s and 9.742 s, within the unchanged 45-second deadline.
These observations do not explain the older intermittent import timeouts.

- Actual InspectorPro startup and facility attachment; no Node/process exposed
  in the application renderer.
- Two manual edits, Close/Cancel, exact frame/selection/history retention.
- Held Apply and Undo acknowledgments, backend restart, durable reconciliation,
  retained renderer, and all five transaction mutation endpoints called once.
- Research open/hide state transitions while both acknowledgments were pending,
  with exact session snapshots preserved. These are state/transaction checks,
  not screenshots of a visibly painted pending-operation interaction.
- Zero Save calls. Each backend's termination, pipe closure and resource-cleanup
  receipt matched its owned process and instance.
- A real public HTTPS page loaded in the research renderer. HTTP and HTTPS
  probes against local backend addresses/aliases failed. Unit tests additionally
  cover schemes, private/mixed DNS answers, address pinning, header removal,
  permissions, sender rejection, tab limits, popup denial and disposal.
- 827 real-mesh placements across 37 asset groups; 827 audited transforms,
  zero transform mismatches and zero missing placements. The library contains
  38 actual cards in this isolated fixture; visible first-row thumbnails and
  labels were inspected. This run did not repeat the earlier per-card scrolling
  audit of all 37 reference asset types.
- Wide and narrow owned-window screenshots inspected in the subsequent
  `162852-b2a8888f` run; toolbar bounds/overlap checks passed. Whole-factory Plan
  labels are crowded at the small split-pane zoom, so this is not a claim of
  complete layout-usability acceptance at that scale.

## Resolved visibility cause

The launcher passed `STARTF_USESHOWWINDOW` with `SW_HIDE` to Electron itself.
Windows can override the application's first `ShowWindow` call with that
startup setting. The controlled hidden-launch probe reproduced a focused but
invisible first wide window; the second show became visible. Removing that
override only for the GUI application made wide, narrow and return-wide visible
and capturable on the first attempt. The same fix passed the full application
run. This matches the [Microsoft ShowWindow contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindow).

- [Hidden-launch probe](../../.runtime/research-geometry-20260915-a/result.json)
- [Application-controlled probe](../../.runtime/research-geometry-20260915-b/result.json)
- [Full native launcher](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-162852-b2a8888f/native-launch.json)
- [Wide native composite](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-162852-b2a8888f/native/research-wide.png)
- [Narrow native composite](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-162852-b2a8888f/native/research-narrow.png)

No timeout, geometry tolerance, Chromium sandbox setting or capture-success
criterion was weakened. The earlier missing screenshot was not a GLB defect.

## Workflow guard and reliability

The real Process Map editor was mounted in an isolated native fixture, two
unsaved steps were added, and Close/Restart were refused with exact map/history,
selection and facility-frame preservation. Process Map Undo still worked and
the existing backend instance survived. This proves refusal/preservation, not
Process Map restart recovery or a working interactive Process Map desktop mode.

`165328-7c7d6b5a` passed this new check and Apply restart, then failed Undo restart
with `desktop_backend_startup_timeout`. Its backend reported `application-ready`
at 15.187 seconds on its internal clock; the parent recorded those checkpoints
only at 48.806 seconds. All owned cleanup was verified. The location/cause of
that delay is still unproven; do not describe it as a confirmed Python import
stall or claim that a later successful run fixes it.

Parent diagnostics now record spawn return, private-control send, first stdout
and stderr arrival, and maximum synchronous log-write duration. These are
observations only; readiness still requires exact owned-process identity and
authenticated verification within the unchanged 45-second budget.

The final project-launcher run started its three backends in 9.408 s, 12.763 s
and 13.991 s. Spawn returned in 13-18 ms and maximum measured log writes were
1-2 ms in this run. All three shutdown receipts matched their instance and PID,
with resource/stream closure, exit 0 and no forced termination. These successful
measurements do not explain the preceding timeout.

The saved manual layout SHA-256 before and after remained:

```text
a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088
```

The earlier failed recovery checkpoint was independently rehashed and remains
`526a8ad8eba7ab405e418a14b26143cb527bc13ef01758c14c3ea8396aac1384`.

## Tests and evidence

- **570 Node tests passed** in `node --test desktop/tests/*.test.cjs`.
- **229 Python tests passed, 1 skipped, 306 subtests passed** in
  `python -m pytest desktop/tests -q -p no:cacheprovider`.
- The added parent-timing assertions also passed the 29-test supervisor suite.
- The first full Node follow-up found a stale initialization test fixture that
  omitted the new observer callback. That fixture was corrected to assert its
  wiring; the complete suite then passed. The failed JUnit is retained.

Earlier combined evidence, retained from before the research security follow-up:

- [Corrected Node JUnit](../../.runtime/desktop-completion-evidence/node-followup-corrected.xml)
- [Python JUnit](../../.runtime/desktop-completion-evidence/python-followup.xml)
- [Project launcher result](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native-launch.json)
- [Lifecycle results including real Process Map refusal](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native/runtime-integration-check.json)
- [Research and mesh results](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native/research-check.json)
- [Owned cleanup](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native/runtime-final-result.json)
- [Visual review record](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/visual-review.json)
- [Wide research](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native/research-wide.png)
- [Narrow research](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native/research-narrow.png)
- [Asset library](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native/research-facility-assets.png)
- [3D scene](../../.runtime/desktop-acceptance/evidence/inspectorpro-runtime-20260915-170311-35d3ebbc/native/research-facility-scene.png)

Earlier source snapshot: `source-20260915-170249-daece972`, manifest SHA-256
`461ea31166def0bbd57e3d219bfc61434394985084565a2f3c284333a854c984`.
Twelve core source files, including the main/preload/peer/lifecycle/supervisor,
shared application/observers, and acceptance drivers, were hash-compared at that
checkpoint. The later research security follow-up changes the pane and main
lifecycle wiring; its source binding/evidence is recorded separately. It is not
represented as part of that earlier native snapshot.

Earlier functional evidence relative to this document (these links preserve
the pre-visibility-fix run, not the current capture verdict):

- [Node JUnit](../../.runtime/desktop-completion-evidence/node-final.xml)
- [Python JUnit](../../.runtime/desktop-completion-evidence/python-final.xml)
- [Final native launcher report](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-155155-e0cbc53e/native-launch.json)
- [Research results and diagnostics](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-155155-e0cbc53e/native/research-check.json)
- [Recovery and pending-operation results](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-155155-e0cbc53e/native/runtime-integration-check.json)
- [Final cleanup receipt](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-155155-e0cbc53e/native/runtime-final-result.json)
- [Narrow native research capture](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-155155-e0cbc53e/native/research-narrow.png)
- [Actual library](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-155155-e0cbc53e/native/research-facility-assets.png)
- [Actual 3D scene](../../.runtime/desktop-completion-evidence/inspectorpro-runtime-20260915-155155-e0cbc53e/native/research-facility-scene.png)

Earlier functional source snapshot: `desktop-completion-20260915-e`, manifest SHA-256
`55bd35deac72e9be10376f8b0caf72b4722a16a20554d842b2f95ed46f8177d0`.
The later stricter receipt validator, its tests, project PowerShell wrapper
and documentation were verified separately; they were not part of that native
snapshot. This paragraph is historical provenance, not the current source binding.

## Remaining work, in order

1. **Complete all-workflow lifecycle integration and authorization.** Drawing,
   assembly, Process Maps, reports, sessions, chat and background jobs still need
   actual draft/pending-operation recovery. The new guard deliberately refuses
   uncovered work; unsupported APIs are denied, not completed. Do not unlock
   their DOM or routes before these adapters exist.
2. **Complete trusted-app permissions and live Sage.** Voice consent/denial,
   standard clipboard, viewport pointer lock/focus re-entry, motion/drone,
   streaming and the unchanged four-command construction pilot need actual
   Electron evidence. The backend Node compiler dependency must be explicitly
   available. No live provider requests were made in this batch.
3. **Complete research compatibility/security acceptance.** Controlled hostile
   frames, dedicated/shared/service workers, redirects, WebSockets, local network
   denial and download cancellation now have native evidence. Still exercise
   real-backend cross-boundary attacks in the combined shell, PDFs/file dialogs,
   standard clipboard, supported citation sites,
   focus/camera/selection preservation, scaling/zoom/monitor changes and tab
   memory cleanup. The initial prototype tests do not establish all these gates.
4. **Finish interactive attach and release launch.** Pairing is currently a
   read-only foundation, not accepted interactive attach. Verify stable-address
   storage/migration, cross-store separation and normal-browser compatibility.
   Clean-machine packaging/signing remains the plan's later milestone.
5. **Resolve intermittent startup/loader reliability.** Retain the failed
   restart described above and the earlier GLB timeout. Later successful runs
   do not establish their cause. Also improve Plan label density in split view.

These are implementation and acceptance tasks from the existing plan, not
optional polish. Do not mark Milestone A/B or the full shell complete based
only on this facility-focused checkpoint.

## Project-owned check

From the project root in an ordinary unelevated PowerShell terminal, use the
installed directory containing the pinned Electron `node_modules`:

```powershell
& '.\desktop\tools\check-runtime.ps1' `
  -ElectronDesktop 'C:\Users\might\Documents\Codex\2026-09-12\hi\work\inspectorpro-desktop\desktop' `
  -Python 'C:\Python314\python.exe' -Research
```

Omit `-Research` for the normal-entry lifecycle check, or use
`-StartupDiagnosticsOnly` for startup only. The occupied-port case refuses
without killing or moving another server. This command is an acceptance
harness, not the finished end-user launcher, and does not enable general edits.
