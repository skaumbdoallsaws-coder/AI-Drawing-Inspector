# Desktop shell implementation checkpoint

Updated: 2026-09-15 (America/Chicago)

**Latest follow-up:** the normal native facility UI now preserves the browser's
single ribbon and integrated panes. Trusted native control checks and 602 Node
tests passed. Two full native reruns reached pending Apply but did not complete
recovery (acknowledgment-hold timeout, then held-operation settlement timeout).
Current full recovery reacceptance remains pending. See [UI parity evidence](desktop-facility-ui-parity.md).
The accepted runs below are historical checkpoints, not a claim that this latest
full run passed.

**Normal-entry facility recovery and wide/narrow native research capture are verified. The latest project-launcher run also proves that an uncovered Process Map draft blocks Close/Restart without losing either editor's state. The entire desktop plan is not complete.** See the [current consolidated report](desktop-research-runtime-implementation.md) for exact evidence and remaining work. General editing and embedded browsing remain disabled outside the acceptance harness; the new guard is not recovery support for the other workflows.

| Checkpoint | Current status |
| --- | --- |
| Empty application, wide/narrow rendering and responsive toolbar/tabs | Accepted in `20260913-070011-000`; exact 1440 x 960 remains unexercised on the tested display |
| Real facility assets and isolated lifecycle recovery | Accepted in `20260913-141702-926`: 827 placement transforms, 37 referenced GLBs, library visibility, lost acknowledgment and Close without Save |
| Managed backend recovery during Apply/Undo and injected failures | All ten isolated native cases accepted in `20260913-222008-375` |
| Recovery status-bar correction | Apply accepted in `20260914-081001-547`; Undo accepted in `20260914-164703-058`, screenshot inspected |
| Managed normal-entry desktop integration | Native verification passed again in `20260915-173342-aa0dafb0`: hardened pane/main wiring, project launcher, real app, pending Apply/Undo restart, exact editor restoration, zero Save and three verified owned shutdowns. General editing remains gated. |
| Isolated research pane | Wide/narrow owned-window composites captured on the first attempt and inspected; real library and 827 meshes verified. The first-show `SW_HIDE` cause is fixed. Broader browsing acceptance remains open. |
| Research security follow-up | Native page/frame/dedicated/shared/service-worker probes, local request denial, popup ownership and download cancellation passed. Late navigation/confirmation and lifecycle suspension fixes are covered by the 599-test Node suite. See [evidence](desktop-research-security-acceptance.md). |
| Uncovered workflow preservation | Actual state observers and fail-closed lifecycle guard implemented; real Process Map edits/history/Undo survive refused Close and Restart in the latest native run. Other workflow recovery is not implemented by this guard. |
| Complete backend access protection and broader workflow acceptance | Unsupported routes are denied; enabling all workflow operations, permissions, live Sage and interactive attach remains unfinished. |

**The Apply and Undo status-bar follow-up is closed.** The ordinary unelevated Undo recapture `20260914-164703-058` passed all five recovery checks; the screenshot was inspected and shows `Unsaved changes | 1 selected | Plan view | select` without the stale interruption error. Exact draft, selection and Undo restoration, one durable read-only lookup, once-only transaction endpoints, zero Save calls, process cleanup and both backend resource receipts were verified. Source/isolated saved layouts and the earlier failed checkpoint remain unchanged.

Backend startup took 13.479 s and 18.706 s. All nine spatial jobs completed; the longest execution was 430.037 ms. The earlier intermittent timeout causes remain unresolved. Retain their diagnostics as reliability follow-ups; this successful recapture does not establish a performance fix or rewrite the previous failures.

[Native result](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/check.json), [inspected screenshot](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058/undo-success/managed-recovery.png), and [independent evidence audit](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-managed-recovery-20260914-164703-058-independent-audit.json). The earlier ten-case managed recovery acceptance stands. General editing and embedded browsing remain gated. No application code, tests or native checks were run or changed during this documentation review.

See [facility acceptance](desktop-facility-recovery-acceptance.md), [managed recovery acceptance](desktop-managed-backend-recovery.md) and the [implementation plan](inspectorpro-desktop-shell-implementation-plan.md).

## Next implementation milestone

Follow the ordered remaining work in the [September 15 report](desktop-research-runtime-implementation.md#remaining-work-in-order). Do not rerun unchanged isolated recovery matrices. The current Node suite passed 599 tests. The preceding Python verification passed 229 tests, with 306 subtests and one skip; no Python source changed in the research follow-up. A preceding native Undo restart timed out; owned cleanup passed and the root cause remains open. Pairing remains a protected read-only foundation; interactive attach is not accepted. Keep general editing and research gates closed until their separate requirements are met.

Then verify the other workflows' truthful close/recovery coverage and representative input, motion, voice and live Sage behavior in the actual shell. The tabbed research pane follows verified backend protection. Internal launch/release acceptance and clean-machine packaging remain later gates. This update adds no new implementation scope beyond the existing plan.

## Historical foundation record

The following sections retain the earlier implementation and test history. Their past pending statements are superseded by the current checkpoint table above. No unchanged rendering or recovery matrix is requested again.

## Delivered foundation

- Electron 44.3.0 is pinned. The complete existing web frontend is the application view.
- Main/preload modules enforce renderer isolation, input locking, explicit backend/store identity, navigation restrictions, denied permissions/downloads, and disabled research/native execution capabilities.
- Lifecycle coordination checks coverage, pending work, identity, generation and sequence. Cooperative cancellation guards apply immediately before adapter effects. The recovery store supplies bounded identity-bound records, atomic replacement, file synchronization and compare-and-swap; real workflow integration remains unfinished.
- The source snapshot helper excludes credentials, installed packages and live runtime/library stores. The real FastAPI fixture launcher retains the normal application lifespan with isolated storage, scrubbed provider credentials and denied editing/provider/native-helper requests.
- Rendering verification requires actual application markup and initialized empty profile data, first paint, two renderer frames, current window/viewport dimensions, nonempty PNGs at wide/narrow sizes, a committed lifecycle close and actual window destruction.
- The new direct-process Python orchestrator runs the inert fixture first, then starts the isolated full backend only after that stage passes. Reports/logs preserve failures; owned-process termination and Electron pipe EOF are checked. The backend must acknowledge completed lifespan/resource cleanup for that exact instance.

Implementation was developed in `C:\Users\might\Documents\Codex\2026-09-12\hi\work\inspectorpro-desktop`, based on source HEAD `1632770aa18c1e6862614171f751977b051de6d2` plus working source changes. No source-branch switch, Git staging, live server restart or manual-layout Save was performed.

## Earlier verification

- **249 Node tests passed**, including current toolbar/tab geometry, clipped labels, nested controls, wrapped rows, fresh capture evidence and resize-transition handling, alongside the existing lock/lifecycle/identity/capture checks.
- **78 Python tests passed**: snapshot safety (10), fixture launcher (19), orchestration and independent report/geometry validation (49). All three suites were rerun together for this update.
- The prepared ordinary-terminal PowerShell launcher passed parser validation.
- An actual backend-only run passed all seven HTTP checks with profile count 0. The owned backend terminated and produced its matching durable shutdown acknowledgment. Windows exit 3 after CTRL_BREAK was retained; the acknowledgment establishes completed lifespan/resource cleanup. Backend stdout used a file, so no backend pipe-EOF claim is made.
- The latest ordinary two-stage run passed with `fullRenderingPassed: true` and full-app captures inspected. Its narrow image reveals the responsive defect below, so automated rendering success is recorded separately from visual acceptance.

The earlier snapshot exercise copied and verified 1,914 files, including 748 untracked source files. That is historical snapshot evidence, not a count of the subsequently updated handoff. Current delivered source hashes are in the handoff verification file.

## Native diagnostic evidence

| Run | Result | Interpretation |
| --- | --- | --- |
| Original restricted minimal page | GPU child `0xC0000135`; renderer launch-failed/exit 49; main exit 1; termination/streams confirmed | Reproduced without InspectorPro or its preload. No particular DLL or GPU defect was established. |
| Ordinary user, immediate capture: `inspectorpro-normal-user-20260912-204530-671` | Page/isolation passed; capture failed with UnknownVizError; cleanup confirmed | Earlier startup failure did not reproduce in this environment. |
| Ordinary user, after-paint: `inspectorpro-normal-user-after-paint-20260912-211818-720` | All six checks passed; correct screenshot inspected; exit 0/EOF confirmed | One successful minimal-page run. Full application acceptance remains pending. |

The ordinary runs matched the pinned Electron 44.3.0 binary SHA-256 `e048632e03fabc96de5e10afbebc0aa31f4e1674155ea3d270597fe7523f9d80`. The user confirmed the successful run's Administrator token was False. Its report, launch/process receipts and screenshot were inspected directly in this task. Sandboxing and web security remained enabled.

The after-paint diagnostic registers observation before loading, waits for ready-to-show and two bounded animation frames, then captures once. The successful result supports this readiness sequence; it does not establish the exact cause of the earlier failures. Original evidence is retained. No runtime/driver replacement, Windows policy change or security bypass was used.

Earlier startup corrections created profile directories before Electron path configuration and retained the Chromium `--` separator before application arguments. Process Monitor was not used. This session has no separate ordinary-user command executor, so the new native checks require the prepared user-run launcher.

## Inert-shell size-check follow-up

The user confirmed an unelevated run in `outputs/inspectorpro-rendering-20260912-215359-430`. The saved overall/stage reports, launch hash and process receipt were inspected. Backend identity, input lock, fixture markup, isolation and first paint passed. `wideCapture` then failed with `capture_outer_size_mismatch` because actual outer dimensions did not equal the required 1440 × 960. The old report did not preserve the actual measurement. Screenshot capture was never reached, so this is not a recurrence of UnknownVizError. Electron exited 1 with termination and diagnostic EOF confirmed; Stage 2 did not start.

The subsequent unelevated run in `outputs/inspectorpro-rendering-20260912-221011-142` recorded actual 1440 × 816 outer dimensions immediately after construction, matching the 1536 × 816 work area's height at 125% display scale. The menu did not change the outer size. The same five checks passed; screenshot capture and Stage 2 were not reached. Main exit 1, termination and diagnostic EOF were confirmed. The actual work-area restriction explains the 144-DIP height shortfall; content/viewport rounding is separate.

At the user's instruction, the rendering diagnostic now selects a display and computes fitting wide/narrow dimensions before construction. This display plans 1440 × 816 and 900 × 700; a display that supports 1440 × 960 retains that exact test. Strict outer-size equality, frozen-display checks and independent parent report validation prevent unexpected clamping from becoming a pass. Exact 1440 × 960 coverage is labeled `not-exercised` on this display. The ordinary preview constructor, security settings and capture behavior remain unchanged. The next ordinary-terminal run verified the fitted-size policy as recorded below. Both earlier failed runs are retained.

## Full-application input-lock follow-up

The unelevated rerun in `outputs/inspectorpro-rendering-20260912-224028-487` passed all eight Stage 1 checks, including wide 1440 × 816 and narrow 900 × 700 captures, isolation and lifecycle close. Both screenshots were inspected. Exact 1440 × 960 coverage was correctly `not-exercised`. Stage 2 reached the real InspectorPro toolbar, viewport, workflow tabs and **Profiles: 0**, but failed at `markup`: `Application input-lock evidence is incomplete`, `frozen: false`, after the initial lock acknowledgment. Full-app screenshots were not reached. Electron termination/pipe EOF and the backend's matching resource-cleanup acknowledgment were confirmed.

The source contains a direct-body SVG sprite alongside 23 scripts and nine divs, matching the report's 33 protected roots. The old preload assigned `.inert = true` to every root. On an SVG this is an ordinary JavaScript property, not the native `HTMLElement.inert` setter; it does not create an inert root. Context isolation also means that expando is not shared with the main-world probe. The saved report did not identify individual failing nodes, so it cannot independently prove that this was the only unlocked root. The source defect is concrete and consistent with the acknowledgment/DOM disagreement.

The corrected preload wraps each non-HTML body root in a native inert HTML `div` using `display: contents`, preserving the original SVG node and its descendants. Existing HTML roots remain in place and use the captured native inert getter/setter. Only the exact preload-owned banner node is exempt. The observer repairs late roots, removed inert attributes and body replacement without unconditional writes. The acknowledgment is sent only after verifying a nonempty set of native inert HTML roots.

The HTML specification defines inert on `HTMLElement`; SVG has a separate interface. Current Blink also requires an HTML element when deciding whether an element is an inert root. A bare SVG inert attribute is therefore not used as the fix. `display: contents` omits the wrapper's layout box while retaining its DOM/flat-tree ancestry; full-app rendering must still confirm visual compatibility. [HTML inert](https://html.spec.whatwg.org/multipage/interaction.html#inert), [SVG interface](https://svgwg.org/svg2-draft/types.html#InterfaceSVGElement), [current Blink implementation](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/dom/element.cc), [CSS display](https://drafts.csswg.org/css-display/#box-generation), [Electron context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation).

At that checkpoint the correction had regression coverage but no successful native rerun. Both native stages have since passed, as recorded below. The input-lock change did not edit the application HTML or layouts; the shell makes a temporary DOM wrapper during the rendering preview. The later responsive follow-up edits CSS only. Editing and embedded browsing remain disabled.

Fifteen VM regressions execute the actual preload source, including a fixture with the observed 33 roots. They are not native browser proof. The controlled native fixture now records SVG focus before freezing and verifies focus is blocked through a real inert HTML parent afterward, with Close preview still focusable. Node and Python parents require the new `html-root-lock-v1` contract and four fresh ordered lock checks surrounding captures. A restricted-session standalone Chromium probe failed while creating a page and supplied no native inert evidence; the subsequent ordinary-user Electron run supplied the native proof recorded below.

## Backend-startup timeout follow-up

The unelevated run in `outputs/inspectorpro-rendering-20260912-231034-432` passed the strengthened inert fixture. Native SVG focus was blocked through its inert HTML parent, Close preview remained focusable, and all four capture rechecks found zero unlocked roots. Both fitted-size screenshots and lifecycle close passed; the captures were inspected. Exact 1440 × 960 coverage remains `not-exercised` on this display.

The full-app renderer did not launch. Backend PID 34188 missed the unchanged 45-second readiness deadline with a zero-byte `backend.log`. Termination was confirmed, but no matching lifespan shutdown receipt existed, so graceful resource cleanup was unverified. The original timeout remains the primary failure; the missing receipt is separate cleanup evidence. The post-stop exit code does not establish a startup crash. This run cannot identify the stalled startup phase.

The backend diagnostic now emits an immediately flushed bootstrap marker before bulk launcher imports and structured checkpoints around fixture preparation, dependency paths, the write guard, Uvicorn import, `server` import, application lifespan startup/shutdown, resource cleanup and receipt writing. Child Python uses `-u` and `PYTHONUNBUFFERED=1`. The 45-second default and HTTP identity/shutdown-receipt acceptance rules are unchanged.

Parent events use **`backend-parent.jsonl`**; child stdout/stderr and checkpoints use **`backend.log`**. Keeping them separate avoids Windows inherited-handle append-position conflicts. Before preparation/spawn, the parent writes a starting result; it then persists launch metadata, owned PID and phase transitions. `startupDiagnosticsAtFailure` is collected before sending a stop signal, so shutdown messages cannot replace the last startup observation. `startupDiagnostics` records the post-cleanup view. Parsing is bounded to a 256 KiB tail and 64 retained checkpoint records, checks instance/PID, and records missing, truncated, partial, malformed or unreadable evidence. Neither checkpoints nor a process exit substitute for the existing HTTP identity or matching resource-cleanup receipt.

The aggregate failed report now points to the backend result and both logs even when the stage raises. Diagnostic read/persistence failures do not replace an already active startup/cleanup exception. No environment dump, provider credential, timeout increase, runtime replacement, application source change or layout Save was introduced.

Two actual isolated **backend-only** checks passed in the restricted session; neither launched Electron. The first (`outputs/inspectorpro-backend-startup-checkpoints-20260912-232949-782`) recorded 37.444 seconds importing `server` and application lifespan startup completed at 38.713 seconds after the first structured checkpoint. It used the intermediate shared-log implementation, which has since been replaced with separate parent/child logs.

The final separate-log check (`outputs/inspectorpro-backend-startup-separated-20260912-233235-785`) recorded 12.347 seconds importing `server` and lifespan startup completed at 12.901 seconds. All seven allowed/denied HTTP checks passed with Profiles: 0. The owned backend terminated with exit 3 after CTRL_BREAK, and the matching durable resource-cleanup receipt was verified. Forty child checkpoints were retained; child and parent logs contained 11,051 and 1,898 bytes respectively. That saved parent file uses prefixed records; the final writer now emits plain JSON lines, verified by the real-child log test and the 45-test orchestration suite. Backend output is a file, so no pipe-EOF or independent descendant-termination claim is made.

These runs establish working checkpoint collection and two successful local backend starts. Their timing differs; they do not prove where the earlier unelevated run stalled or resolve full-app rendering acceptance. The final `rendering-check.json` explicitly records `fullRenderingPassed: false`.

## Automated rendering passed; narrow visual follow-up

The ordinary, unelevated run in `outputs/inspectorpro-rendering-20260912-233933-718` passed both automated stages with `passed: true` and `fullRenderingPassed: true`. Both Electron processes passed captures, four fresh input-lock rechecks, isolation and lifecycle close, then exited 0 with termination and diagnostic EOF confirmed. The full application retained 33 native inert HTML roots. Backend application import took 23.546 seconds; the parent verified HTTP identity, all seven boundary checks, Profiles: 0, termination and the matching resource-cleanup receipt. The backend's exit 3 after CTRL_BREAK was retained.

The wide and narrow full-app screenshots were inspected. The narrow image shows toolbar contents overlapping around Ready/search and the Sessions tab clipped outside the center column. The web window controls are also outside the narrow image, and Run Inspection wraps. The automated pass used the previous nonzero-rectangle checks and does not establish complete visual acceptance. Exact 1440 × 960 coverage remains correctly `not-exercised` on the available display.

The shared web UI CSS now allows the toolbar to grow into rows at widths up to 1200 CSS pixels. Its left and right groups can also wrap when additional controls are visible; controls are retained rather than clipped or hidden. The existing wide toolbar remains 42 pixels high. Workflow tabs wrap as complete tabs inside the center column, with capped widths for long labels in a narrower column; the tab bar does not shrink vertically. The center column can shrink without pushing its tab row beyond its bounds.

This change is in `static/index.html`, so it applies to both the web frontend and desktop host. No workflow logic, document storage, Save operation, backend timeout, Electron binary or security setting is changed.

The rendering probe now records `chromeLayout` with `revision: chrome-layout-v1` for the full application. It measures toolbar controls/labels and all eight workflow tabs, including their ancestor clipping bounds. A one-CSS-pixel rounding allowance permits normal fractional-DPI geometry. It rejects clipped controls/labels, overlapping unrelated controls, missing/duplicate tabs and invalid geometry; wrapped rows and measured parent/child controls are allowed.

Initial markup and every before/after capture recheck require fresh geometry. The Node and Python parents independently validate those records. A before-narrow snapshot may still have the old renderer size immediately after native resize; it is validated against its own viewport. After-capture geometry must match the verified capture frame's viewport. A stale initial snapshot cannot substitute for current narrow evidence. The controlled inert fixture keeps its separate input-lock/focus contract.

This remains a bounded geometry check for the empty application's toolbar and workflow navigation. It does not replace screenshot inspection or acceptance of loaded drawings/models, agent panels, Sage, editing/Undo, voice, native helpers or embedded browsing.

## Responsive follow-up verification

The static CSS review used the Codex in-app browser with fixed-width, inert HTML fixtures. All 28 application scripts and inline event handlers were removed, and the known collapsed empty-startup dock was reproduced from the application source. This isolated the CSS comparison without running application initialization, loading project assets or enabling editing.

At 886 CSS pixels, the old source reproduced five measured cross-group toolbar overlaps, three controls outside the viewport, and a visibly clipped Sessions tab. The corrected 786- and 886-pixel previews had zero measured cross-group overlaps or controls outside the viewport; Sessions and the other seven tabs were visible in two rows. Revealing the additional Export/New Inspection/Agent toolbar controls at 886 pixels also fit. The 1426-pixel fixture retained the 42-pixel toolbar height and reported no cross-group overlap or viewport overflow; its preview image was inspected only within the browser's visible width.

Read-only rectangles and source hashes are retained in `outputs/inspectorpro-responsive-review`. The helper's initial tab summary counted non-hidden DOM boxes as visible and mistook bottom-aligned multiline labels for separate rows; corrected summaries distinguish fully contained tabs from that original count. The initial standalone Chromium attempt failed before opening a page, and an initial IAB wrapper syntax error was corrected; both diagnostics are preserved. These helper results support the CSS change, but do not establish native Electron acceptance or initialized application behavior.

All **249 Node tests and 78 Python tests** passed after the production changes. The subsequent native run `20260913-070011-000` accepted this CSS and `chrome-layout-v1`, with both full-app screenshots inspected. Editing and embedded browsing remain disabled.

## Historical two-stage launcher

In an ordinary, unelevated PowerShell terminal:

```powershell
& 'C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-desktop-rendering.ps1'
```

It refuses elevation, uses the existing isolated snapshot and installed binary, and creates fresh separate data/report directories. It checks the actual shell/preload on an inert fixture, then the real application on an empty isolated backend. It stops on failure. The default port is 8197; an occupied port is reported rather than reassigned or terminated.

See `docs/inspectorpro-desktop-rendering-checks.md` for assertions, artifacts and cleanup limits. Both stages require visual inspection of their screenshots. Even a pass establishes initial inert rendering of the web entry point, not loaded assets or interactive workflows.

## Independent review history

Both earlier P2 findings were closed by independent review after 74 Node and 24 Python tests passed. Those are historical review counts. The reviewer did not rerun native Electron.

1. Cancellation revokes prepare/revalidation authority before cleanup. Adapters receive an AbortSignal and invocation guards and must check immediately before each effect, including after awaits and in the renderer after IPC. Already accepted external work and uncooperative callbacks cannot be forcibly stopped.
2. Smoke diagnostics persist through setup, spawn, timeout and nonzero exits. Cleanup waits for the owned process and output closure, reporting unconfirmed outcomes as failures.

The new rendering follow-up also waits for actual window closure after lifecycle commit; a close request alone cannot produce a pass. It adds no editing authority.

## Remaining gates

1. Integrate the tested managed backend and facility lifecycle/recovery components into the ordinary launcher.
2. Complete backend session protection across workflows and protected attach pairing; preserve the supported browser launch path.
3. Integrate truthful lifecycle coverage for other workflows, including hidden drafts, FAI edits, regions and in-flight agent/inspection jobs.
4. Verify actual-shell motion, input/voice and live Sage behavior, preserving the accepted facility contracts.
5. Build and accept the tabbed research pane after backend protection is verified.
6. Complete internal release, performance/reliability and operational acceptance. Clean-machine distribution remains separately scoped.

Earlier intermittent timeout causes remain unresolved reliability items. The accepted isolated checks are reusable evidence; they do not establish ordinary interactive integration. The web development path remains available.
