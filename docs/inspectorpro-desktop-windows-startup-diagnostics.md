# Windows Electron startup diagnostic

Updated: 2026-09-12, America/Chicago. The latest ordinary run passed both automated rendering stages, including backend startup and verified resource cleanup. The remaining known issue is narrow-window toolbar/tab layout; its CSS/geometry follow-up is described in the rendering guide.

## Verified minimal-page result: loading and capture passed

The user ran the updated `after-paint` diagnostic outside the restricted session and confirmed the process was unelevated. The report at `outputs/inspectorpro-normal-user-after-paint-20260912-211818-720/minimal-report.json`, launch identity, process receipt and screenshot were inspected. All six checks passed: page load, page assertions, isolation, first paint, renderer frames and capture. The screenshot showed the correct minimal page. The directly owned process exited 0, with termination and diagnostic-stream closure confirmed. Paths under `outputs/` in this document refer to `C:\Users\might\Documents\Codex\2026-09-12\hi\outputs`.

This run used the same Electron **44.3.0** executable and SHA-256 as the earlier runs. Its main PID was `24460`, renderer PID `3136`; the hidden window remained hidden, and capture used unchanged API defaults with one attempt. Report timestamps are UTC (`2026-09-13T02:18:20Z`), corresponding to September 12 at 21:18 in the workstation's time zone.

## Failure history and what the successful comparison establishes

All three comparisons occurred on September 12, 2026 in the workstation's time zone. The earlier ordinary-user report remains at `outputs/inspectorpro-normal-user-20260912-204530-671/minimal-report.json` and records the 20:45 capture failure. It has not been overwritten by the later pass.

| Stage | Earlier restricted run | Ordinary user, 20:45 | Ordinary user after-paint, 21:18 |
| --- | --- | --- | --- |
| Main process/window creation | Reached | Reached | Passed |
| Renderer/page load | Renderer launch failed | Passed | Passed |
| DOM and isolation checks | Not reached | Passed | Passed |
| First-paint observation | Not instrumented | Not instrumented | Passed |
| Renderer frame checkpoint | Not instrumented | Not instrumented | Passed |
| Screenshot | Not reached | `UnknownVizError` | Passed; correct page inspected |
| Owned main process/streams | Termination and closure confirmed | Termination and closure confirmed | Exit 0; termination and closure confirmed |

The restricted startup failure did not reproduce in either ordinary-user run. The later capture passed after adding first-paint and renderer-frame waits. These results support continuing to the inert shell and full application, but do not conclusively identify the cause of either earlier failure or prove that timing alone explains the capture error. No missing DLL or driver defect was established. The reports record configuration and DOM checks; the user's separate process check establishes the unelevated context.

Electron 44.3.0 maps Chromium's `CopyFromSurfaceError::kUnknownVizError` to this error. The message does not identify a driver fault. Electron's capture tests wait for `ready-to-show`, which is distinct from `did-finish-load`. [Pinned Electron source](https://raw.githubusercontent.com/electron/electron/v44.3.0/shell/browser/api/electron_api_web_contents.cc), [pinned capture tests](https://github.com/electron/electron/blob/v44.3.0/spec/api-browser-window-spec.ts), [first-paint documentation](https://www.electronjs.org/docs/latest/api/browser-window#using-the-ready-to-show-event)

## Capture-readiness diagnostic that passed

The updated diagnostic (`capture-readiness-v1`) registers its first-paint listener before loading the page. By default it waits up to 10 seconds for `ready-to-show`, then up to 5 seconds for two renderer animation-frame callbacks, then performs one capture with a 10-second deadline. The animation callbacks are a scheduling checkpoint, not proof that Chromium's compositor can copy its surface. There are no automatic capture retries and no fallback capture that hides the first error.

The window remains hidden. Capture options, GPU settings, sandboxing and other security settings stay the same. The report now persists separate outcomes for page load, DOM checks, isolation, first paint, renderer frames and capture. It also records visibility, dimensions, scale, paint timing entries and the failed stage. A successful page check cannot turn a failed capture into a pass.

The successful run used the prepared PowerShell launcher's `after-paint` mode and a fresh result directory. To repeat that focused diagnostic when needed, the equivalent command from the isolated snapshot's `desktop` directory is:

```powershell
node tools/electron-minimal.cjs --label normal-user --capture-mode after-paint
```

For a separately labeled baseline comparison, `--capture-mode immediate` skips the two readiness waits; the PowerShell launcher also accepts `-CaptureMode immediate`. A baseline uses current instrumentation and is not a byte-identical reproduction of the earlier harness. Neither mode shows the window or changes capture API defaults. Each output records its mode and diagnostic revision. The successful `after-paint` capture establishes this one minimal-page checkpoint, without accepting InspectorPro workflows.

## Next ordinary-terminal run: inert shell, then full application

The latest inert-shell run passed both fitted sizes and native SVG focus proof. Backend startup then timed out with an empty log before launching the full-app renderer. The checkpoint-instrumented backend needs the next ordinary, unelevated terminal run. Follow [InspectorPro native rendering checks](inspectorpro-desktop-rendering-checks.md) for the staged assertions, fresh fixture storage, process ownership and evidence limits. The workstation command is:

```powershell
& 'C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-desktop-rendering.ps1'
```

The direct Python orchestrator runs the actual Electron host/preload against a controlled inert page first. Only after that process exits successfully with all checks and stream EOF confirmed does it start the isolated backend and test the complete empty InspectorPro application. It checks exact page identity, initialization, isolation, first paint, both window captures and completed lifecycle closure. Editing and research browsing remain disabled throughout. Neither native stage is claimed as passed by the minimal diagnostic or by the Node/Python regression suites.

## Historical restricted child-startup failure

The standalone entry point `desktop/tools/minimal-electron/main.cjs` opens one local static HTML page. It imports no InspectorPro application code, makes no backend connection, and has no preload. It explicitly enables Chromium sandboxing and keeps context isolation, disabled Node integration, and web security. The runner uses the project's pinned Electron package and records the executable's SHA-256 to make comparisons reproducible.

The earlier restricted Codex run on September 12 reached `app.whenReady()` and created the window, then recorded:

- GPU process: `crashed`, exit `-1073741515` (`0xC0000135`).
- Renderer: `launch-failed`, reported exit `49`.
- Main process: exit `1`; termination and stdio closure confirmed.
- No successful page load or screenshot.

The executable was Electron **44.3.0** at `desktop/node_modules/electron/dist/electron.exe` in the isolated snapshot. Its SHA-256 was `e048632e03fabc96de5e10afbebc0aa31f4e1674155ea3d270597fe7523f9d80`.

This reproduced child startup failure independently of InspectorPro and its preload. It did not identify a missing file, prove a driver defect, or establish the precise execution-context restriction. Microsoft defines `0xC0000135` as `STATUS_DLL_NOT_FOUND`; the status alone does not name the dependency. [Microsoft NTSTATUS reference](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55)

## Repeating the focused minimal comparison

Run from an ordinary, unelevated PowerShell terminal in the isolated snapshot's `desktop` directory:

```powershell
node tools/electron-minimal.cjs --label normal-user
```

The diagnostic opens a hidden window and stops its owned process. It creates a fresh short temporary Chromium profile and a new output directory. It does not install dependencies, disable security controls, change Windows policy, use the live backend, or touch application layouts. Keep the same installed binary for this comparison; do not reinstall or move it between the two runs.

Optional `--output PATH` must name a new directory. A caller-supplied label records the intended context; it is not proof of the Windows process token. For this workstation, a prepared launcher is also available in the Codex task's `outputs/diagnose-inspectorpro-desktop.ps1`.

Retain these files:

| File | Evidence |
| --- | --- |
| `launch.json` | Exact executable, hash, package version, runtime and profile paths |
| `electron.log` | Incremental stdout/stderr and owned-process lifecycle markers |
| `minimal-events.jsonl` | Electron main/child/renderer events, including the main PID |
| `minimal-report.json` | Last recorded page status and isolation assertions if reached |
| `process-result.json` | Exit, timeout, termination and stream-closure result |
| `minimal-page.png` | Created only after the page loads and its assertions pass |

The available command tool in this Codex session runs inside a restricted environment. No separate approved normal-user executor was found. The user completed both ordinary-terminal comparisons above, including the successful capture-readiness run. Further native checks use the same ordinary-terminal route.

Use the recorded failed stage to select any further investigation. A successful page load followed by a capture failure does not call for assuming another DLL startup failure. Process Monitor startup tracing below remains available if child launch failure reproduces; it is not the current next step. The next step is the prepared inert-shell/full-application check above.

## Capture child startup with Process Monitor

Process Monitor was not found on PATH or in the checked common tool locations on this workstation. Download it only from [Microsoft Sysinternals](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon). Its capture requires administrative permissions; keep the Electron reproduction running from the ordinary unelevated terminal. This capture has not been run by the agent. [Microsoft capture instructions](https://learn.microsoft.com/en-us/troubleshoot/windows-client/shell-experience/troubleshoot-apps-start-failure-use-process-monitor)

1. Open Process Monitor, stop capture with Ctrl+E, reset filters, and clear events with Ctrl+X.
2. Start capture immediately before one run of the prepared minimal diagnostic. Stop immediately after it exits; keep the capture short.
3. Save all events in native PML format locally. Use Process Tree and the diagnostic's PID/time/executable to select that launch and its children.
4. Inspect process creation/exit, DLL search paths, successful image loads, and access-denied results near the failing child's termination. Preserve the successful events as well as failures.
5. Identify the dependency/path or access condition from the complete sequence before selecting a repair. A single `NAME NOT FOUND` event can be a normal intermediate search and is not sufficient evidence.

These steps follow Microsoft's [capture procedure](https://techcommunity.microsoft.com/t5/IIS-Support-Blog/Basic-Steps-for-Making-a-Process-Monitor-ProcMon-Capture/ba-p/348401) and [startup troubleshooting guidance](https://techcommunity.microsoft.com/blog/iis-support-blog/troubleshooting-service-startup-issues-with-process-monitor/347414). Keep PML files local; they can contain activity from other processes captured during the interval.

## Inert-shell size check: September 12, 21:53 local

The user ran the prepared two-stage launcher unelevated. The report at `outputs/inspectorpro-rendering-20260912-215359-430/inert-fixture/report.json` confirms backend identity, input lock, fixture markup, isolation and first paint passed. The wide capture stage rejected the outer size with `capture_outer_size_mismatch`. It did not reach `capturePage()`, so this is not another UnknownVizError. Actual dimensions were not logged in the old report. Main exit 1, owned termination and pipe EOF were confirmed; Stage 2 was not started.

The revised diagnostic records construction/menu/paint/resize/capture measurements before validation. It includes actual and requested bounds, renderer viewport/DPR, matching-display work area/scale and diagnostic getter errors. The exact requested sizes remain unchanged. Rerun the same prepared ordinary-terminal launcher; see `docs/inspectorpro-desktop-rendering-checks.md` for field names and interpretation. No runtime replacement or security change is proposed from this size mismatch.

## Work-area evidence and policy: September 12, 22:10 local

The unelevated report in `outputs/inspectorpro-rendering-20260912-221011-142` records requested 1440 × 960, actual 1440 × 816 and matching-display work area 1536 × 816, all in DIP, at scale 1.25. Actual height already matched the work-area height immediately after construction. Menu setup changed content dimensions only. The original five checks passed; capture was not reached, Stage 2 was not started, and process exit 1 plus termination/pipe EOF were confirmed.

The authorized policy now calculates the effective window sizes before creation and preserves strict checks against that plan. This display targets wide 1440 × 816 and narrow 900 × 700. Exact 1440 × 960 coverage remains unexercised here; supporting displays run it automatically. Display changes invalidate the frozen plan instead of silently changing targets. See `docs/inspectorpro-desktop-rendering-checks.md` for algorithm, coverage fields and unchanged acceptance limits. Native verification of the fitted sizes passed in the 22:40 run below.

## Fitted sizes passed; full-app lock failed: September 12, 22:40 local

The unelevated rerun in `outputs/inspectorpro-rendering-20260912-224028-487` passed all eight Stage 1 checks, including wide 1440 × 816 and narrow 900 × 700 captures, isolation and lifecycle close. Both screenshots were inspected. Exact 1440 × 960 coverage was correctly `not-exercised`. Stage 2 reached the real InspectorPro toolbar, viewport, workflow tabs and **Profiles: 0**, but failed at `markup`: `Application input-lock evidence is incomplete`, `frozen: false`, after the initial lock acknowledgment. Full-app screenshots were not reached. Electron termination/pipe EOF and the backend's matching resource-cleanup acknowledgment were confirmed.

The source contains a direct-body SVG sprite alongside 23 scripts and nine divs, matching the report's 33 protected roots. The old preload assigned `.inert = true` to every root. On an SVG this is an ordinary JavaScript property, not the native `HTMLElement.inert` setter; it does not create an inert root. Context isolation also means that expando is not shared with the main-world probe. The saved report did not identify individual failing nodes, so it cannot independently prove that this was the only unlocked root. The source defect is concrete and consistent with the acknowledgment/DOM disagreement.

The corrected preload wraps each non-HTML body root in a native inert HTML `div` using `display: contents`, preserving the original SVG node and its descendants. Existing HTML roots remain in place and use the captured native inert getter/setter. Only the exact preload-owned banner node is exempt. The observer repairs late roots, removed inert attributes and body replacement without unconditional writes. The acknowledgment is sent only after verifying a nonempty set of native inert HTML roots.

The HTML specification defines inert on `HTMLElement`; SVG has a separate interface. Current Blink also requires an HTML element when deciding whether an element is an inert root. A bare SVG inert attribute is therefore not used as the fix. `display: contents` omits the wrapper's layout box while retaining its DOM/flat-tree ancestry; full-app rendering must still confirm visual compatibility. [HTML inert](https://html.spec.whatwg.org/multipage/interaction.html#inert), [SVG interface](https://svgwg.org/svg2-draft/types.html#InterfaceSVGElement), [current Blink implementation](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/dom/element.cc), [CSS display](https://drafts.csswg.org/css-display/#box-generation), [Electron context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation).

This is an implemented source correction with regression coverage, not a successful native rerun. The app HTML, layouts and runtime/security configuration were not edited. The shell now makes a temporary DOM wrapper during the rendering preview. Editing and embedded browsing remain disabled.

The prepared rerun retains the same installed Electron binary and capture/security settings. It adds a controlled SVG focus proof to Stage 1 and native root diagnostics with four fresh capture-lock checks to both stages. No full-app focus or editing commands are introduced. See the rendering guide for `html-root-lock-v1` fields.

## Backend timeout and flushed checkpoints: September 12, 23:10 follow-up

The unelevated run in `outputs/inspectorpro-rendering-20260912-231034-432` passed the strengthened inert fixture. Native SVG focus was blocked through its inert HTML parent, Close preview remained focusable, and all four capture rechecks found zero unlocked roots. Both fitted-size screenshots and lifecycle close passed; the captures were inspected. Exact 1440 × 960 coverage remains `not-exercised` on this display.

The full-app renderer did not launch. Backend PID 34188 missed the unchanged 45-second readiness deadline with a zero-byte `backend.log`. Termination was confirmed, but no matching lifespan shutdown receipt existed, so graceful resource cleanup was unverified. The original timeout remains the primary failure; the missing receipt is separate cleanup evidence. The post-stop exit code does not establish a startup crash. This run cannot identify the stalled startup phase.

The backend diagnostic now emits an immediately flushed bootstrap marker before bulk launcher imports and structured checkpoints around fixture preparation, dependency paths, the write guard, Uvicorn import, `server` import, application lifespan startup/shutdown, resource cleanup and receipt writing. Child Python uses `-u` and `PYTHONUNBUFFERED=1`. The 45-second default and HTTP identity/shutdown-receipt acceptance rules are unchanged.

Parent events use **`backend-parent.jsonl`**; child stdout/stderr and checkpoints use **`backend.log`**. Keeping them separate avoids Windows inherited-handle append-position conflicts. Before preparation/spawn, the parent writes a starting result; it then persists launch metadata, owned PID and phase transitions. `startupDiagnosticsAtFailure` is collected before sending a stop signal, so shutdown messages cannot replace the last startup observation. `startupDiagnostics` records the post-cleanup view. Parsing is bounded to a 256 KiB tail and 64 retained checkpoint records, checks instance/PID, and records missing, truncated, partial, malformed or unreadable evidence. Neither checkpoints nor a process exit substitute for the existing HTTP identity or matching resource-cleanup receipt.

The aggregate failed report now points to the backend result and both logs even when the stage raises. Diagnostic read/persistence failures do not replace an already active startup/cleanup exception. No environment dump, provider credential, timeout increase, runtime replacement, application source change or layout Save was introduced.

Two actual isolated **backend-only** checks passed in the restricted session; neither launched Electron. The first (`outputs/inspectorpro-backend-startup-checkpoints-20260912-232949-782`) recorded 37.444 seconds importing `server` and application lifespan startup completed at 38.713 seconds after the first structured checkpoint. It used the intermediate shared-log implementation, which has since been replaced with separate parent/child logs.

The final separate-log check (`outputs/inspectorpro-backend-startup-separated-20260912-233235-785`) recorded 12.347 seconds importing `server` and lifespan startup completed at 12.901 seconds. All seven allowed/denied HTTP checks passed with Profiles: 0. The owned backend terminated with exit 3 after CTRL_BREAK, and the matching durable resource-cleanup receipt was verified. Forty child checkpoints were retained; child and parent logs contained 11,051 and 1,898 bytes respectively. That saved parent file uses prefixed records; the final writer now emits plain JSON lines, verified by the real-child log test and the 45-test orchestration suite. Backend output is a file, so no pipe-EOF or independent descendant-termination claim is made.

These runs establish working checkpoint collection and two successful local backend starts. Their timing differs; they do not prove where the earlier unelevated run stalled or resolve full-app rendering acceptance. The final `rendering-check.json` explicitly records `fullRenderingPassed: false`.

## Ordinary two-stage run passed: September 12, 23:39 local

The ordinary, unelevated run in `outputs/inspectorpro-rendering-20260912-233933-718` passed both automated stages with `passed: true` and `fullRenderingPassed: true`. Both Electron processes passed captures, four fresh input-lock rechecks, isolation and lifecycle close, then exited 0 with termination and diagnostic EOF confirmed. The full application retained 33 native inert HTML roots. Backend application import took 23.546 seconds; the parent verified HTTP identity, all seven boundary checks, Profiles: 0, termination and the matching resource-cleanup receipt. The backend's exit 3 after CTRL_BREAK was retained.

The wide and narrow full-app screenshots were inspected. The narrow image shows toolbar contents overlapping around Ready/search and the Sessions tab clipped outside the center column. The web window controls are also outside the narrow image, and Run Inspection wraps. The automated pass used the previous nonzero-rectangle checks and does not establish complete visual acceptance. Exact 1440 × 960 coverage remains correctly `not-exercised` on the available display.

The earlier silent backend timeout did not recur in this run. Startup checkpoints and receipt verification remain enabled; the timeout stays 45 seconds. Continue with the responsive CSS and geometry check described in `docs/inspectorpro-desktop-rendering-checks.md`.

## Remaining acceptance

The standalone minimal page has passed once, including its inspected screenshot. Run the prepared two-stage rendering check next and inspect both window captures from each stage. A passing main process, Node suite, Python suite or minimal page does not replace InspectorPro native rendering evidence. Even a full-app rendering pass would cover the inert, empty entry point only; interactive workflows, loaded assets, live agents and embedded browsing remain gated by the implementation plan.
