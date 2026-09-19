# InspectorPro native rendering checks

The ordinary, unelevated minimal-page run at `outputs/inspectorpro-normal-user-after-paint-20260912-211818-720` passed all six stages, captured the correct page, exited 0 and confirmed process termination and output-stream closure. The report, launch hash, process receipt and screenshot were independently inspected in this task. This verifies one minimal-page run; it does not accept InspectorPro workflows or establish the exact cause of the earlier failures.

The first ordinary-user two-stage run (`outputs/inspectorpro-rendering-20260912-215359-430`) passed backend identity, input lock, fixture markup, isolation and first paint. It then failed `wideCapture` with `capture_outer_size_mismatch` before screenshot capture was attempted. Electron exited 1 with termination and pipe EOF confirmed. Stage 2 did not start in that run.

The instrumented ordinary-user rerun (`outputs/inspectorpro-rendering-20260912-221011-142`) recorded a 1440 × 816 window immediately after construction, inside a 1536 × 816 work area at 125% scale. The requested 960-DIP height exceeded that work area. The menu did not change outer size. The same five checks passed, capture was not reached, and Stage 2 did not start. Main exit 1, termination and pipe EOF were confirmed.

The user authorized a work-area-aware window policy. It is now implemented for the rendering diagnostic, with strict checks against the calculated dimensions. The next native run verified that policy, then reached a separate full-app lock failure described below.

## Current rendering and responsive-layout follow-up

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

All **249 Node tests and 78 Python tests** passed after the production changes. The ordinary two-stage launcher must now be rerun against this CSS and `chrome-layout-v1`, followed by direct inspection of its full-app screenshots. Editing and embedded browsing remain disabled.

## Earlier backend-startup follow-up

The unelevated run in `outputs/inspectorpro-rendering-20260912-231034-432` passed the strengthened inert fixture. Native SVG focus was blocked through its inert HTML parent, Close preview remained focusable, and all four capture rechecks found zero unlocked roots. Both fitted-size screenshots and lifecycle close passed; the captures were inspected. Exact 1440 × 960 coverage remains `not-exercised` on this display.

The full-app renderer did not launch. Backend PID 34188 missed the unchanged 45-second readiness deadline with a zero-byte `backend.log`. Termination was confirmed, but no matching lifespan shutdown receipt existed, so graceful resource cleanup was unverified. The original timeout remains the primary failure; the missing receipt is separate cleanup evidence. The post-stop exit code does not establish a startup crash. This run cannot identify the stalled startup phase.

The backend diagnostic now emits an immediately flushed bootstrap marker before bulk launcher imports and structured checkpoints around fixture preparation, dependency paths, the write guard, Uvicorn import, `server` import, application lifespan startup/shutdown, resource cleanup and receipt writing. Child Python uses `-u` and `PYTHONUNBUFFERED=1`. The 45-second default and HTTP identity/shutdown-receipt acceptance rules are unchanged.

Parent events use **`backend-parent.jsonl`**; child stdout/stderr and checkpoints use **`backend.log`**. Keeping them separate avoids Windows inherited-handle append-position conflicts. Before preparation/spawn, the parent writes a starting result; it then persists launch metadata, owned PID and phase transitions. `startupDiagnosticsAtFailure` is collected before sending a stop signal, so shutdown messages cannot replace the last startup observation. `startupDiagnostics` records the post-cleanup view. Parsing is bounded to a 256 KiB tail and 64 retained checkpoint records, checks instance/PID, and records missing, truncated, partial, malformed or unreadable evidence. Neither checkpoints nor a process exit substitute for the existing HTTP identity or matching resource-cleanup receipt.

The aggregate failed report now points to the backend result and both logs even when the stage raises. Diagnostic read/persistence failures do not replace an already active startup/cleanup exception. No environment dump, provider credential, timeout increase, runtime replacement, application source change or layout Save was introduced.

Two actual isolated **backend-only** checks passed in the restricted session; neither launched Electron. The first (`outputs/inspectorpro-backend-startup-checkpoints-20260912-232949-782`) recorded 37.444 seconds importing `server` and application lifespan startup completed at 38.713 seconds after the first structured checkpoint. It used the intermediate shared-log implementation, which has since been replaced with separate parent/child logs.

The final separate-log check (`outputs/inspectorpro-backend-startup-separated-20260912-233235-785`) recorded 12.347 seconds importing `server` and lifespan startup completed at 12.901 seconds. All seven allowed/denied HTTP checks passed with Profiles: 0. The owned backend terminated with exit 3 after CTRL_BREAK, and the matching durable resource-cleanup receipt was verified. Forty child checkpoints were retained; child and parent logs contained 11,051 and 1,898 bytes respectively. That saved parent file uses prefixed records; the final writer now emits plain JSON lines, verified by the real-child log test and the 45-test orchestration suite. Backend output is a file, so no pipe-EOF or independent descendant-termination claim is made.

These runs establish working checkpoint collection and two successful local backend starts. Their timing differs; they do not prove where the earlier unelevated run stalled or resolve full-app rendering acceptance. The final `rendering-check.json` explicitly records `fullRenderingPassed: false`.

## Reading backend startup evidence

| Evidence | Interpretation |
| --- | --- |
| `backend-parent.jsonl` | Parent preparation, spawn return/PID, readiness wait, HTTP checks and shutdown phases; independently flushed and synchronized |
| `backend-launch.json` | Exact Python command, isolated working directory, instance ID, unbuffered flag and unchanged timeout; no environment dump |
| `backend.log` bootstrap marker only | Script entry was reached; structured logging/minimal imports had not yet completed |
| No child bootstrap/checkpoint | Child script progress is unverified; use parent launch/PID evidence, not an assumed DLL/import diagnosis |
| `server-import-starting` without completion | The current observation is inside application import; this does not identify a particular nested module or root cause |
| `application-lifespan-startup-completed` | Application lifespan yielded; only the parent's matching HTTP identity check establishes serving readiness |
| `startupDiagnosticsAtFailure` | Instance/PID-filtered log snapshot before termination was requested |
| `startupDiagnostics` | Final snapshot, which may include cleanup checkpoints after the original failure |
| `gracefulResourceCleanupVerified` | True only after termination and the exact launched instance's durable cleanup receipt are verified |

Structured child lines use prefix `INSPECTORPRO_DESKTOP_BACKEND_CHECKPOINT ` followed by schema version, PID, wall-clock milliseconds, fixed phase, sequence, elapsed milliseconds and validated instance UUID. The earliest bootstrap literal is separate. Tail truncation means earlier markers may be outside coverage; a false `bootstrapMarkerObserved` is not evidence that the script never entered. Raw logs remain available for inspection. The pre-script Python interpreter/site initialization phase cannot emit script checkpoints.

## Earlier full-app lock failure and correction

The unelevated rerun in `outputs/inspectorpro-rendering-20260912-224028-487` passed all eight Stage 1 checks, including wide 1440 × 816 and narrow 900 × 700 captures, isolation and lifecycle close. Both screenshots were inspected. Exact 1440 × 960 coverage was correctly `not-exercised`. Stage 2 reached the real InspectorPro toolbar, viewport, workflow tabs and **Profiles: 0**, but failed at `markup`: `Application input-lock evidence is incomplete`, `frozen: false`, after the initial lock acknowledgment. Full-app screenshots were not reached. Electron termination/pipe EOF and the backend's matching resource-cleanup acknowledgment were confirmed.

The source contains a direct-body SVG sprite alongside 23 scripts and nine divs, matching the report's 33 protected roots. The old preload assigned `.inert = true` to every root. On an SVG this is an ordinary JavaScript property, not the native `HTMLElement.inert` setter; it does not create an inert root. Context isolation also means that expando is not shared with the main-world probe. The saved report did not identify individual failing nodes, so it cannot independently prove that this was the only unlocked root. The source defect is concrete and consistent with the acknowledgment/DOM disagreement.

The corrected preload wraps each non-HTML body root in a native inert HTML `div` using `display: contents`, preserving the original SVG node and its descendants. Existing HTML roots remain in place and use the captured native inert getter/setter. Only the exact preload-owned banner node is exempt. The observer repairs late roots, removed inert attributes and body replacement without unconditional writes. The acknowledgment is sent only after verifying a nonempty set of native inert HTML roots.

The HTML specification defines inert on `HTMLElement`; SVG has a separate interface. Current Blink also requires an HTML element when deciding whether an element is an inert root. A bare SVG inert attribute is therefore not used as the fix. `display: contents` omits the wrapper's layout box while retaining its DOM/flat-tree ancestry; full-app rendering must still confirm visual compatibility. [HTML inert](https://html.spec.whatwg.org/multipage/interaction.html#inert), [SVG interface](https://svgwg.org/svg2-draft/types.html#InterfaceSVGElement), [current Blink implementation](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/dom/element.cc), [CSS display](https://drafts.csswg.org/css-display/#box-generation), [Electron context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation).

The corrected SVG fixture has since passed natively. The full-app lock and capture check still requires a successful backend start. The app HTML, layouts and runtime/security configuration were not edited. The shell now makes a temporary DOM wrapper during the rendering preview. Editing and embedded browsing remain disabled.

## Run both stages from an ordinary terminal

The prepared workstation launcher is `C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-desktop-rendering.ps1`. It reports the Administrator token and refuses an elevated terminal. It uses the existing isolated snapshot, creates separate fresh report/data directories and runs both stages in order.

```powershell
& 'C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-desktop-rendering.ps1'
```

The default backend port is **8197**. An occupied port is a failure; the tool does not stop its owner or silently change ports. To select a different port intentionally, pass `-Port NUMBER` to the launcher.

For another isolated snapshot, run from its root:

```powershell
python desktop/tools/run-rendering-check.py --port 8197 --profile-id rendering-check --output .runtime/rendering-report-001 --data-root .runtime/desktop-spike/rendering-data-001
```

Both paths must be fresh and separate. The full-app fixture requires an empty library. The tool refuses a live-source checkout, overlapping report/data roots, mismatched runtime pin, and stale report-directory reuse. It reads and hashes the already installed Electron executable; it does not download or replace the runtime. Both stages use the same binary and verify the hash before launch.

## Stage 1: inert shell

A local static fixture runs inside the actual InspectorPro Electron host and preload. The check verifies backend identity, the input-lock handshake and DOM state, the explicit fixture marker, disabled capabilities, isolated renderer preferences, and the expected native view counts. It waits for first paint, captures wide and narrow windows, and awaits both a committed close decision and actual window destruction.

The fixture now includes a focusable direct-body SVG. A parser-time baseline records that it can receive focus both without and with a bare SVG inert attribute. After preload locking, a native check requires a connected native inert HTML parent, blocked SVG focus and successful focus on the unique Close preview button; focus is cleared afterward. Only this controlled fixture receives focus probes. The full application receives read-only DOM diagnostics.

The full backend is not started unless the inert stage has passed its report checks, produced both PNGs, exited 0, and reached diagnostic-pipe EOF.

## Stage 2: isolated full application

The tool starts the existing FastAPI application directly with the verified fixture launcher's scrubbed environment, isolated storage and empty library. Readiness must match the exact launched instance. It verifies seven allowed/denied HTTP requests before opening Electron.

The full-app renderer check requires the actual InspectorPro title and visible toolbar, upload area, viewport and workflow tabs. The profile count must change from its static placeholder to **Profiles: 0**, showing that application initialization reached the isolated backend. The empty viewport is expected. A drawing canvas, loaded model or populated ribbon is not expected without opening content. The preview banner by itself cannot satisfy these checks.

Wide and narrow captures use the same first-paint/frame approach that passed the minimal diagnostic. Each capture has bounded waits, a unique renderer checkpoint, current page/size checks and nonempty PNG dimension validation. The narrow capture also verifies that the requested resize reached the renderer. There is one capture attempt per size, without automatic retries, visible-window fallback, GPU switches or weakened security settings.

After Electron exits, the tool stops the backend it started and requires a matching per-instance acknowledgment that the original lifespan and fixture resource cleanup completed. Windows/Uvicorn can return exit 3 after CTRL_BREAK despite completing cleanup; that exit code is retained, and the matching acknowledgment is required instead of treating termination alone as clean shutdown. Primary failures remain visible if cleanup also fails.

## Input-lock contract and diagnostics

New reports require `inputLockRevision: html-root-lock-v1`. An old preload acknowledgment cannot substitute for current lock evidence. The initial markup probe and each capture recheck require a positive protected-root count, one unique banner, zero unlocked roots, and matching current preload evidence.

- `lockEvidence` contains all-root counts plus bounded root summaries and `unlockedRoots`: tag, namespace, ID/class, HTML identity, native inert value, inert attribute, expando/type and wrapper marker. All roots are checked even when the diagnostic list is truncated.
- `preloadLockDiagnostics` contains before/after initialization snapshots, a bounded repair history, and a fresh current snapshot. It identifies the exact banner by node identity and reports native-property verification. The exposed API returns read-only serializable copies without page text or form values.
- Four `input-lock-rechecked` events must appear exactly once in this order: `before-wide-capture`, `after-wide-capture`, `before-narrow-capture`, `after-narrow-capture`. Each contains new root evidence; missing fields cannot inherit an earlier passing acknowledgment. A failure stops the stage.
- Both parent runners independently require the current contract and all four rechecks. The inert fixture additionally requires `fixtureFocusProof`, including both parser baseline observations and native HTML-parent/focus results. Unit tests use controlled DOM/VM fixtures; the September 12 23:10 fixture run also established native SVG/Close focus behavior. Full-app validation remains pending.

On failure, compare `preloadLockDiagnostics.initial.before`, `.initial.after`, `.repairHistory`, `.current`, and `lockEvidence.unlockedRoots`. This distinguishes the original SVG-root problem from later initialization changes. Do not remove the lock assertion or infer success from visible markup alone.

## Work-area-aware size policy

The diagnostic selects the primary display after Electron is ready and freezes that display's bounds, work area and scale for the run. It computes integer DIP bounds inside the work area, with fractional left/top rounded up and right/bottom rounded down. No DPI multiplication is applied to these dimensions.

| Target | Preferred outer size | Effective outer size |
| --- | --- | --- |
| Wide | 1440 × 960 DIP | Each dimension capped to available work area |
| Narrow | 900 × 700 DIP | Each dimension capped to available work area |

For the measured 1536 × 816 work area, this means **1440 × 816 wide** and **900 × 700 narrow**. A larger supporting display retains the exact **1440 × 960** wide test. Windows smaller than the existing 800 × 600 minimum, or a display unable to provide two distinct planned sizes, are rejected with an explicit policy error.

The wide window is centered explicitly inside the selected work area. The narrow resize retains that position. The policy applies to `--smoke-output` diagnostics; ordinary preview launch behavior is unchanged. Framing, menu handling, capture options, security settings and the existing one-DIP content/viewport rounding allowance remain unchanged.

The calculated plan is saved as `windowSizePolicy` (`revision: work-area-v1`) before window creation. Both captures must exactly match their planned outer dimensions. Unexpected operating-system clamping remains a failure; actual dimensions never redefine the expected target. Selected-display identity, bounds, work area and scale changes are latched as failures, including changes reported after current state has restored. Current window bounds must remain inside the frozen work area.

`referenceWideCapture` separately reports the exact 1440 × 960 coverage. Its status is `passed` only after a successful capture at that exact target. On this display it is `not-exercised`, with a work-area reason, even if the fitted wide capture passes. Both Python and Node parent runners validate the canonical plan, captured outer sizes and exact-size coverage before accepting a stage.

## Window-size diagnostics

Reports now include `geometryDiagnosticsRevision: window-geometry-v1`. Read the `window-geometry` events and the top-level `captureFailure` object if a size check fails.

- Window snapshots record requested and actual outer/content dimensions, bounds, minimum/maximum size, menu visibility, window visibility/state and zoom.
- Matching and primary displays are identified separately, with display bounds, available work area and scale. Native dimensions are labeled as device-independent pixels (DIP); the Windows physical-pixel rectangle is explicitly a `dipToScreenRect` conversion, not an independent HWND measurement. [Electron screen API](https://www.electronjs.org/docs/latest/api/screen)
- Snapshots occur after construction, around menu setup, at first paint, on resize/move/display changes, and around the narrow-size request. Capture records retain renderer inner/outer dimensions, DPR, frame checkpoints and optional visual-viewport data before validation and on failure.
- A diagnostic getter failure is recorded separately and cannot replace the original capture error. Strict equality now applies to the precomputed work-area-aware outer sizes described above. There is no post-failure target adjustment, tolerance increase, capture retry, GPU change or security change.

The measured constructor result matches Electron 44.3.0's native centering behavior: `Center()` clamps centered bounds to the display work area. The policy now requests a fitting target and explicit position before construction. [Pinned Electron source](https://raw.githubusercontent.com/electron/electron/v44.3.0/shell/browser/native_window_views.cc)

The first failed run's files are retained unchanged. A new run creates a fresh report directory. A repeated size mismatch is still a failed rendering stage, now with measurements available to choose a concrete correction.

## Evidence and limits

| Artifact | What it records |
| --- | --- |
| `rendering-check.json` | Overall stage status, binary identity and `fullRenderingPassed` |
| `inert-fixture/report.json` | Eight shell rendering/lifecycle checks and both capture records |
| `full-application/report.json` | Same checks plus actual application markup/startup evidence |
| Each stage's `desktop-wide.png` / `desktop-narrow.png` | Screenshots requiring visual inspection |
| Each stage's `electron.log`, `events.jsonl`, `launch.json` | Startup, stage failures, exact binary and context |
| Each stage's `process-result.json` | Directly owned Electron exit, termination and pipe EOF |
| `backend-result.json` / `backend.log` | Current phase, bounded child checkpoint snapshots, readiness, HTTP checks and backend shutdown acknowledgment |
| `backend-parent.jsonl` / `backend-launch.json` | Separate parent lifecycle diagnostics and exact isolated child launch metadata |

Electron processes and the backend are direct children of this tool. It does not introduce an additional Windows Job Object or kill processes discovered by port/name. Electron owns its Chromium descendants; this diagnostic does not independently prove termination of every descendant. Electron stream closure is established through EOF. Backend stdout is a log file, so no backend pipe-EOF claim is made.

The backend-only verification can run separately with `--backend-check-only`; its result explicitly sets `fullRenderingPassed: false` and never resolves or launches Electron. This mode has passed in the restricted session, including profile count 0, all seven HTTP checks and matching shutdown acknowledgment. It does not replace either native rendering stage.

Even if both native stages pass, this remains an inert rendering checkpoint for the full web entry point. It does not exercise loaded CAD assets, live Sage, facility editing/Undo, process-map drafts, voice, native helpers, production authentication or embedded browsing. Editing and embedded browsing remain disabled until the implementation plan's acceptance gates pass.
