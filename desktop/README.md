# InspectorPro desktop shell — first implementation slice

Current status (2026-09-15): the project-owned launcher passed normal-entry facility recovery, wide/narrow native research capture, real asset/library checks and refusal to close/restart over an uncovered Process Map draft. Broader workflow recovery, permissions and research compatibility remain pending. General editing and browsing are gated. See the [current implementation report](../docs/desktop-research-runtime-implementation.md) and `tools/check-runtime.ps1`. The full desktop plan is not complete.

The sections below retain the historical first-slice instructions and evidence; their pending statements are superseded by the current report. The complete existing web frontend is the application view; no workflow is being rewritten for Electron.

This slice contains a pinned Electron host, explicit backend/profile identity checks, an inert rendering preload, navigation/permission policies, a lifecycle coordinator, a durable recovery-store foundation, and an isolated launcher for the actual Python application. Research browsing, editing, provider calls, native helpers, and Save are disabled in the rendering spike.

The ordinary, unelevated minimal-page run on September 12, 2026 passed all six checks, captured the correct page, exited 0 and confirmed process termination and output-stream closure. Its report, executable hash and screenshot were inspected. The same Electron binary had earlier failed during restricted child startup and then at capture with `UnknownVizError` in an ordinary-user run. Those historical failures remain documented; their exact causes have not been established. The minimal-page pass does not accept the InspectorPro shell or its workflows. The inert-shell run and its diagnostic follow-up are described below; full-application acceptance remains pending, with editing and research browsing disabled.

The first ordinary-user inert-shell check subsequently failed its exact 1440 × 960 outer-size assertion before `capturePage()` was called. Five prior checks passed, exit 1 and pipe closure were confirmed, and the full backend was not started. Window/display measurements are now recorded before dimensional rejection. The instrumented rerun then confirmed a 1536 × 816 DIP work area: the original window was clamped to 1440 × 816 before menu setup. The user authorized a work-area-aware diagnostic policy; it now plans 1440 × 816 wide and 900 × 700 narrow on that display, with strict equality to those targets. The exact 1440 × 960 test remains automatic on supporting displays and is explicitly unexercised otherwise. The next ordinary-user run passed these fitted sizes; see the current input-lock follow-up below.

## Current input-lock follow-up

The unelevated rerun in `outputs/inspectorpro-rendering-20260912-224028-487` passed all eight Stage 1 checks, including wide 1440 × 816 and narrow 900 × 700 captures, isolation and lifecycle close. Both screenshots were inspected. Exact 1440 × 960 coverage was correctly `not-exercised`. Stage 2 reached the real InspectorPro toolbar, viewport, workflow tabs and **Profiles: 0**, but failed at `markup`: `Application input-lock evidence is incomplete`, `frozen: false`, after the initial lock acknowledgment. Full-app screenshots were not reached. Electron termination/pipe EOF and the backend's matching resource-cleanup acknowledgment were confirmed.

The preload now gives non-HTML roots a genuine inert HTML wrapper and verifies the native property before acknowledging the lock. Root diagnostics and fresh checks before/after both captures are mandatory. The inert fixture additionally proves that a focusable SVG becomes unfocusable while Close preview remains focusable. The strengthened fixture has now passed natively; full-app rendering remains pending after a separate backend timeout. See the rendering guide for the contract and evidence limits.

## Current backend-startup follow-up

The unelevated run in `outputs/inspectorpro-rendering-20260912-231034-432` passed the strengthened inert fixture. Native SVG focus was blocked through its inert HTML parent, Close preview remained focusable, and all four capture rechecks found zero unlocked roots. Both fitted-size screenshots and lifecycle close passed; the captures were inspected. Exact 1440 × 960 coverage remains `not-exercised` on this display.

The full-app renderer did not launch. Backend PID 34188 missed the unchanged 45-second readiness deadline with a zero-byte `backend.log`. Termination was confirmed, but no matching lifespan shutdown receipt existed, so graceful resource cleanup was unverified. The original timeout remains the primary failure; the missing receipt is separate cleanup evidence. The post-stop exit code does not establish a startup crash. This run cannot identify the stalled startup phase.

The backend diagnostic now emits an immediately flushed bootstrap marker before bulk launcher imports and structured checkpoints around fixture preparation, dependency paths, the write guard, Uvicorn import, `server` import, application lifespan startup/shutdown, resource cleanup and receipt writing. Child Python uses `-u` and `PYTHONUNBUFFERED=1`. The 45-second default and HTTP identity/shutdown-receipt acceptance rules are unchanged.

Parent events use **`backend-parent.jsonl`**; child stdout/stderr and checkpoints use **`backend.log`**. Keeping them separate avoids Windows inherited-handle append-position conflicts. Before preparation/spawn, the parent writes a starting result; it then persists launch metadata, owned PID and phase transitions. `startupDiagnosticsAtFailure` is collected before sending a stop signal, so shutdown messages cannot replace the last startup observation. `startupDiagnostics` records the post-cleanup view. Parsing is bounded to a 256 KiB tail and 64 retained checkpoint records, checks instance/PID, and records missing, truncated, partial, malformed or unreadable evidence. Neither checkpoints nor a process exit substitute for the existing HTTP identity or matching resource-cleanup receipt.

The aggregate failed report now points to the backend result and both logs even when the stage raises. Diagnostic read/persistence failures do not replace an already active startup/cleanup exception. No environment dump, provider credential, timeout increase, runtime replacement, application source change or layout Save was introduced.

Two actual isolated **backend-only** checks passed in the restricted session; neither launched Electron. The first (`outputs/inspectorpro-backend-startup-checkpoints-20260912-232949-782`) recorded 37.444 seconds importing `server` and application lifespan startup completed at 38.713 seconds after the first structured checkpoint. It used the intermediate shared-log implementation, which has since been replaced with separate parent/child logs.

The final separate-log check (`outputs/inspectorpro-backend-startup-separated-20260912-233235-785`) recorded 12.347 seconds importing `server` and lifespan startup completed at 12.901 seconds. All seven allowed/denied HTTP checks passed with Profiles: 0. The owned backend terminated with exit 3 after CTRL_BREAK, and the matching durable resource-cleanup receipt was verified. Forty child checkpoints were retained; child and parent logs contained 11,051 and 1,898 bytes respectively. Backend output is a file, so no pipe-EOF or independent descendant-termination claim is made.

These runs establish working checkpoint collection and two successful local backend starts. Their timing differs; they do not prove where the earlier unelevated run stalled or resolve full-app rendering acceptance. The final `rendering-check.json` explicitly records `fullRenderingPassed: false`.

## Current responsive-layout follow-up

The ordinary, unelevated run in `outputs/inspectorpro-rendering-20260912-233933-718` passed both automated stages with `passed: true` and `fullRenderingPassed: true`. Both Electron processes passed captures, four fresh input-lock rechecks, isolation and lifecycle close, then exited 0 with termination and diagnostic EOF confirmed. The full application retained 33 native inert HTML roots. Backend application import took 23.546 seconds; the parent verified HTTP identity, all seven boundary checks, Profiles: 0, termination and the matching resource-cleanup receipt. The backend's exit 3 after CTRL_BREAK was retained.

The wide and narrow full-app screenshots were inspected. The narrow image shows toolbar contents overlapping around Ready/search and the Sessions tab clipped outside the center column. The web window controls are also outside the narrow image, and Run Inspection wraps. The automated pass used the previous nonzero-rectangle checks and does not establish complete visual acceptance. Exact 1440 × 960 coverage remains correctly `not-exercised` on the available display.

The shared web UI CSS now allows the toolbar to grow into rows at widths up to 1200 CSS pixels. Its left and right groups can also wrap when additional controls are visible; controls are retained rather than clipped or hidden. The existing wide toolbar remains 42 pixels high. Workflow tabs wrap as complete tabs inside the center column, with capped widths for long labels in a narrower column; the tab bar does not shrink vertically. The center column can shrink without pushing its tab row beyond its bounds.

This change is in `static/index.html`, so it applies to both the web frontend and desktop host. No workflow logic, document storage, Save operation, backend timeout, Electron binary or security setting is changed.

The full-app harness now checks `chrome-layout-v1` geometry at markup and before/after captures. See the rendering guide for bounds, overlap, wrapping and resize evidence rules. The corrected CSS passed static before/after browser review at narrow widths; the wide fixture retained its 42-pixel toolbar. All 249 Node and 78 Python tests passed. The corrected CSS and new geometry gate still require an ordinary native rerun and screenshot inspection.

## Working directory and isolation

Do not launch the rendering backend from the live application checkout. It requires an isolated source snapshot and refuses overlapping source/data roots. A snapshot preserves the current working source, including the uncommitted construction work, without copying `.env`, live runtime stores, installed packages, or the private asset library.

From the source project root, create a new snapshot outside that root:

```powershell
python desktop/tools/prepare-snapshot.py --destination 'C:\Users\might\Documents\Codex\InspectorProDesktop'
```

The destination must be new or empty. The helper writes a source checkpoint and file-hash manifest. It does not change the source Git index or create a commit. Open a terminal in the new snapshot root for the following commands.

## Launch the actual backend in a restricted fixture

```powershell
python desktop/tools/run-rendering-backend.py --port 8197 --profile-id rendering --data-root .runtime/desktop-spike/rendering
```

The launcher keeps the normal FastAPI lifespan, uses an existing empty fixture library, removes inherited provider credentials from its child, disables dotenv, confines configured stores to the fixture, and denies non-allowlisted API requests. Its Python write guard is defense for this developer fixture, not an OS sandbox or the future production authentication mechanism. It prints an identity/readiness receipt only for the process it started. Ctrl+C stops that owned backend; Electron attach mode does not own it.

The port is persistent for the profile. If it is occupied or a profile's origin changes, startup refuses instead of silently selecting another server/port. Use `--check` to verify startup and stop immediately. Refer to the runtime inventory for startup paths and remaining whole-app isolation limitations.

## Install and launch Electron

Use a second terminal in the snapshot's `desktop` directory:

```powershell
npm ci --no-audit --no-fund
npm start -- --backend http://127.0.0.1:8197 --identity-file ../.runtime/desktop-spike/rendering/desktop-rendering-identity.json
```

Electron is pinned to **44.3.0** in `package-lock.json`; the developer Node runtime must be at least **22.12.0**. Electron 44 downloads its binary lazily on first use. To keep install caches in an explicitly writable location when needed:

```powershell
$env:npm_config_cache = Join-Path $PWD '.runtime/npm-cache'
$env:electron_config_cache = Join-Path $PWD '.runtime/electron-cache'
npm ci --no-audit --no-fund
node node_modules/electron/install.js
```

The npm start script includes a Chromium `--` separator before application options. Preserve that separator in direct Electron invocations; on Windows, a URL followed by additional switches can otherwise cause termination before application code starts. No security switches are disabled.

`--state-root PATH` selects a separate shell profile directory. It binds to the exact origin/backend/store identity and refuses reuse for another store. The default is `desktop/.runtime/shell`. Use a short path on Windows so Chromium cache paths stay within platform limits. Changing an origin is not an implemented migration path in this slice.

## Verification

For the next native check, follow [the two-stage rendering guide](../docs/inspectorpro-desktop-rendering-checks.md). This workstation's prepared launcher verifies the inert shell first, then starts the isolated backend and verifies the complete empty application:

```powershell
& 'C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\check-inspectorpro-desktop-rendering.ps1'
```

Run it in an ordinary, unelevated PowerShell terminal. It directly owns the Electron and backend processes, creates fresh evidence directories and requires every rendering check and cleanup acknowledgment before reporting success. Both automated stages have passed. The next run also requires fresh toolbar/tab geometry and visual inspection of the corrected narrow screenshot. The lower-level commands remain available for focused verification:

```powershell
# Snapshot root
python -m pytest -q -p no:cacheprovider desktop/tests/test_rendering_backend.py desktop/tests/test_prepare_snapshot.py

# desktop directory
npm test
npm run test:electron

# Actual InspectorPro UI instead of the small controlled HTML fixture:
node tools/electron-smoke.cjs --backend http://127.0.0.1:8197 --identity-file ../.runtime/desktop-spike/rendering/desktop-rendering-identity.json
```

The Electron harness uses a hidden real Electron process and preserves sandboxing. It opens its log before setup/spawn, persists output incrementally, and waits for process termination and output drainage. Timeout cleanup targets only its owned child, with bounded escalation; an unconfirmed termination or stream closure is explicitly a failure. Its eight checks cover backend identity, input lock, the exact expected page, isolation, first paint, wide/narrow capture and committed lifecycle closure followed by actual window destruction. Full-app startup must show the real application structure and initialized empty profile count; the preview banner alone cannot pass. Each capture uses a bounded renderer checkpoint and validates image dimensions. Broader input, permission, crash/reload, and native-window workflow acceptance remain required. Missing screenshots or failed stages cannot pass. Default artifacts stay under `desktop/.runtime`; the harness uses a short temporary Chromium profile path on Windows.

For a page independent of InspectorPro and its preload, run `npm run test:electron:minimal`. The default `after-paint` mode registers first-paint observation before load, then waits for `ready-to-show` and two bounded renderer animation frames before a single capture. The report separates page load, isolation, first paint, frames and capture, preserving earlier successes when a later stage fails. There is no automatic capture retry or security fallback. For a separately labeled timing comparison, use `node tools/electron-minimal.cjs --capture-mode immediate`. The diagnostic records the mode, executable hash, child events, dimensions/visibility and exit/cleanup outcome. The verified ordinary-user pass is saved in `outputs/inspectorpro-normal-user-after-paint-20260912-211818-720` under the Codex task. See [Windows startup diagnostics](../docs/inspectorpro-desktop-windows-startup-diagnostics.md) for its evidence and failure history. Full-application desktop acceptance remains pending.

## What these modules establish

- `backend-profile.cjs`: exact explicit fixture identity, stable origin/partition binding, bounded handshake, no silent migration.
- `navigation-policy.cjs` / `permission-policy.cjs`: strict navigation classification and shared request/check permission decisions. All permissions are denied in the spike. Future interactive predicates are not proof that voice or drone controls work in Electron.
- `lifecycle-coordinator.cjs`: intent, generation and sequence validation, cooperative cancellation, timeouts that block, exact supported discard decisions. It requires truthful workflow adapters and guards at the actual side effect.
- `recovery-store.cjs`: bounded identity-bound records, compare-and-swap, atomic replacement and file-sync acknowledgment. It is a single-main-process store; Windows directory flushing is not guaranteed. It does not establish backend truth or authorize reconciliation.
- `main.cjs` / `preload.cjs`: the complete web page in an isolated Electron view with input disabled and no browser/native execution bridge. Safe crash closure applies only to the inert fixture.

### Adapter cancellation contract

Each lifecycle callback receives `(request, control)`. The first argument remains serializable. The second contains `signal`, `isCurrent()`, `assertCurrent()` and `runIfCurrent(effect)` and must stay local to the callback.

Adapters must pass the AbortSignal to supported asynchronous work and check invocation authority immediately before every side effect, including after each await. `runIfCurrent` must contain synchronous work only. Freeze and cleanup ownership must match `request.intentId`. Cancellation revokes prepare/revalidation authority before cleanup; timed-out cleanup cannot act on a later attempt. Callback authority expires on cancellation, timeout, or settlement. The cancel callback owns cleanup, so abort listeners must not perform an unguarded unfreeze.

A check before IPC dispatch does not revoke queued renderer work. Future renderer adapters must validate their own current intent where the freeze or other effect occurs. Arbitrary callbacks and already accepted backend work cannot be forcibly stopped by this coordinator. These controls establish a contract and regressions; they do not establish real workflow integration.

## Next implementation gates

1. Pass the prepared inert-shell and full-application Electron rendering/isolation checks in the ordinary-user environment. The standalone minimal-page capture gate has passed once with its screenshot inspected.
2. Implement workflow adapters for facility, process maps, drawing/FAI, regions, chat and jobs. Cover hidden retained work, not only the active tab.
3. Wire durable recovery through explicit asynchronous hooks and complete Apply/generation/Undo coverage. Do not pass asynchronous IPC into the existing synchronous Storage adapter.
4. Complete backend authentication and session protection across all workflows and both attach/managed modes. The fixture identity endpoint is not production pairing.
5. Add the managed supervisor and tabbed research pane only after their plan gates pass, then execute the real asset/motion/Sage acceptance matrix.

See `docs/inspectorpro-desktop-shell-implementation-plan.md` and `docs/inspectorpro-desktop-runtime-inventory.md` at the project root. A working web application remains the supported development path throughout.
