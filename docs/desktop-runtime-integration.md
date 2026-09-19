# Managed desktop integration milestone

Current follow-up (2026-09-15): native normal-entry facility recovery is now
verified. See [runtime/research implementation and remaining gates](desktop-research-runtime-implementation.md).
The historical pending statements below describe the original batch. General
editing remains gated; the full all-workflow desktop is not complete.

Updated: 2026-09-14, America/Chicago. This is one implementation and review batch under the desktop shell plan.

## Outcome and acceptance boundary

The normal Electron entry now hosts the existing full InspectorPro page through a protected, owned Python backend. The full application mounts its actual facility session into the desktop lifecycle bridge. An explicitly marked isolated facility profile can exercise manual edits, Close/Cancel and durable Apply/Undo recovery. General editing, Save, provider execution, native helpers and embedded research browsing remain disabled in this runtime.

**Implementation and real-backend engine checks are complete; normal-entry native Electron acceptance is pending.** No native launch was performed for this milestone in the restricted execution session. Earlier accepted native rendering, asset and ten-case recovery evidence remains valid at its original scope; it does not prove this new integration. Ordinary browser development remains on its existing server path.

This batch combines normal launch, backend request protection, real application lifecycle integration, local draft recovery, and one consolidated acceptance launcher. Internal agent reviews and automated tests occur during implementation. External review is requested at this milestone, not after each small fix.

## What changed

| Area | Delivered behavior | Main files |
| --- | --- | --- |
| Normal application launch | `npm start` uses the managed runtime; the former inert preview remains available explicitly through `npm run start:preview` | `desktop/src/entry.cjs`, `runtime-main.cjs`, `desktop/package.json` |
| Explicit profile | Fixed loopback origin, stable backend/store/principal/owner identity, store bound to an isolated local directory; no automatic adoption or migration of a live store | `desktop/runtime/profile.py`, `create_profile.py`, `desktop/src/runtime-settings.cjs` |
| Owned backend | Private stdin bootstrap/shutdown, per-process credential and instance ID, readiness only after application lifespan/listener startup, verified shutdown receipts | `desktop/runtime/managed_backend.py`, `desktop/src/runtime-supervisor.cjs` |
| Backend boundary | Authentication before application/static/API dispatch; exact Host/Origin rules; narrow accepted route set; WebSocket, unsupported workflows and Save denied | `desktop/runtime/boundary.py` |
| Desktop network authority | Only the attributable InspectorPro main frame receives the credential for the exact local HTTP origin. Subframes, unattributed workers, external requests and redirects are refused. Blob/data resources receive no credential | `desktop/src/runtime-network.cjs` |
| Application bridge | Fixed IPC methods, bounded JSON and deadlines, cooperative cancellation at the session effect, real facility session attached after load; only its approved DOM subtree can receive input | `desktop/src/runtime-preload.cjs`, `runtime-peer.cjs`, `static/desktop_runtime_bridge.js`, `static/index.html` |
| Lifecycle/recovery | Exact frame checks around Close/Cancel; backend restart retains the renderer and reconciles durable transactions before restoring authority | `desktop/src/runtime-lifecycle.cjs`, `facility-managed-recovery.cjs`, `facility-recovery-adapter.cjs` |
| Local draft recovery | Verified plain manual draft restoration includes selection and complete Undo/Redo state. Active proposal metadata cannot use this path to bypass transaction reconciliation | `static/facility_layout_session.js`, recovery adapter |
| Explicit discard | Cleanup succeeds before an atomic retirement receipt is written and before renderer destruction. Original checkpoint files remain on disk; only the exact adopted checkpoint set is retired | recovery adapter, `desktop/src/runtime-window-commit.cjs` |
| Diagnostics | Owned-process and stream closure recorded on failures; credentials redacted even when split across stdout/stderr chunks | supervisor and launcher |

The main process has no general renderer-controlled filesystem, shell, arbitrary HTTP or JavaScript evaluation API. Acceptance automation executes from a main-process-only module enabled by an explicit isolated acceptance profile and output argument.

Browser pairing is backend groundwork only: a successful pair ends on a protected read-only confirmation page. Paired cookies can read runtime/CSRF metadata but cannot enter the application, fetch its assets, or call recovery/mutation routes. There is no supported credential-delivery UI or interactive attach-mode acceptance in this batch. The normal browser server is unchanged.

## Checks completed

The consolidated regression run passed:

- 437 desktop Node tests.
- 214 desktop Python tests and 247 subtests; one environment-dependent symlink test skipped.
- 60 shared facility session checks and 85 shared workspace checks.

[Regression report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/desktop-runtime-regressions-1/regression-check.json) contains the individual commands' logs and outcomes. Focused follow-up checks cover final review fixes without repeating the unchanged recovery matrix.

The final focused bridge/session/attach/window tests passed 53 checks after review corrections; [focused log](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/desktop-runtime-final-focused-node.log). All four inline application script blocks and runtime JavaScript files passed syntax checks. Launcher tests also verify real Python user-site dependency discovery under its sanitized environment.

The actual protected backend was launched three times by the new supervisor and exercised with the real facility session and operation services. Eight combined checks passed: private readiness, credential boundary, real session attachment, two edits followed by Close/Cancel, pending Apply restart, pending Undo restart, unrelated-server survival, and saved-layout hash preservation. Startup times were 28.666 s, 10.025 s and 9.239 s. Every owned backend exited with confirmed stream closure and a successful application resource receipt.

[Real-backend engine report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/desktop-runtime-integration-engine-2/check.json). Both source and isolated saved layouts retained SHA-256 `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`. The first engine attempt failed in test attachment setup before edits; its diagnostics remain in the neighboring `desktop-runtime-integration-engine-1` directory. The corrected run includes full tenant/site/document binding.

Transaction recovery uses a durable pre-dispatch marker and recorded real service response, followed by a read-only transaction/lease/artifact lookup in the new backend instance. Recovery does not replay the command or acquire another lease. Tests separately verify equivalent retry caching, conflicting retry rejection and unknown-outcome refusal. Unique journal keys alone are not reported as measured execution counts.

Internal review found and fixed startup sequence validation, late process-response checks, blob credential handling, split-stream credential redaction, final discard ordering, active-proposal misuse of plain-draft recovery, failed-startup exit, and native checks that could otherwise pass while the facility subtree remained locked.

## Current blocker and the next diagnostic run

The rerun `20260914-225148-37fb376d` hit the unchanged 45-second backend readiness deadline at `application-import`, before the full application loaded. Owned process termination and stream closure were confirmed, but the backend was forcibly terminated and its resource cleanup was not verified. It produced no screenshot and did not exercise the attachment correction. [Retained failed-run report](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-runtime-20260914-225148-37fb376d/native-launch.json).

Before another application-acceptance run, use the prepared **startup diagnostics only** mode from an ordinary unelevated PowerShell terminal:

```powershell
& 'C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\run-inspectorpro-runtime-integration.ps1' -StartupDiagnosticsOnly
```

This uses the same pinned Electron 44.3.0 executable, normal `entry.cjs`, Python executable, managed profile preparation, sanitized launch environment, private bootstrap, sandbox and 45-second backend deadline. It prepares a fresh isolated layout and asset copy. It skips the offline acceptance-proposal seed, loads only the locked starting page, then stops the backend immediately after private readiness and authenticated runtime verification. It never loads the full application, attaches the editor, runs recovery, captures a screenshot or calls Save. Skipping the seed changes preceding workload and may affect filesystem caches; this run is for diagnosis, not an equivalent startup-performance benchmark.

The opt-in adds these observations:

- CPython `-X importtime` records completed imports' self and cumulative times in the incrementally drained, bounded owned-process log. The command-line option is documented in the [Python 3.14 command-line reference](https://docs.python.org/3.14/using/cmdline.html#cmdoption-X). Instrumentation adds overhead; its timing alone does not establish a fix or a production startup baseline.
- A Python stack baseline is written before application setup, followed by at most one timed dump after 30 seconds and one dump on an explicit shutdown request. A C watchdog can collect the timed stack while the main Python thread is blocked. If startup completes earlier, the watchdog is cancelled; no timed dump is expected. Stack output omits frame locals, source text and command-line arguments. Cancellation precedes closing its file descriptor, as required by the [faulthandler documentation](https://docs.python.org/3.14/library/faulthandler.html#dumping-the-tracebacks-after-a-timeout).
- Phase checkpoints carry monotonic elapsed times, the previous phase's duration, sequence, process ID and instance ID. Parent evidence separates time to readiness/failure from time spent shutting down and closing streams. These records cannot grant readiness or write authority.

Evidence lives under the fresh profile's `desktop-logs` directory: `<instanceId>.log`, `<instanceId>-import-stacks.log`, `<instanceId>-import-diagnostics.json`, and the existing process receipt. Stack/metadata files are exclusively created, never replacements for old diagnostic evidence. An early watchdog writes to stderr until the profile is validated. File/handler failures emit fixed diagnostic-error metadata and preserve the underlying application lifecycle and primary error; they prevent a diagnostic pass.

The launcher's `native-launch.json` links to `native/startup-diagnostics-result.json` on both completed and failed startup runs when the receipt could be written. A diagnostic pass requires matching owned process/instance evidence, import timing output, validated metadata and a nonempty baseline stack, readiness, isolation and verified graceful cleanup. Forced termination remains a failed outcome with cleanup unverified. A pass sets `nativeAcceptance: false` and cannot satisfy application, editing or recovery acceptance.

Review the last checkpoint, completed import timings and any timed/shutdown stack together. A slow completed import and a stack blocked in another module describe different observations; neither alone identifies the underlying cause. Diagnose this evidence before retrying full application acceptance. The earlier accepted recovery checkpoints still stand, and general editing and embedded browsing remain gated.

Validation for this diagnostic batch: **66 Node tests, 30 Python tests and 75 Python subtests passed**. Controlled subprocess tests verify a real blocked import's retained stack after forced exit, completed import timing, cancelled watchdog silence, and diagnostic start/bind/stop failures without replacing application lifecycle results. Supervisor/main/launcher checks cover partial stream chunks, missing/foreign/empty diagnostic evidence, unchanged launch environment and deadline, and cleanup before receipt persistence. Both main and launcher reject incomplete isolation evidence. Two internal reviewers checked the Python lifecycle and the main/supervisor/launcher boundary. [Combined verification and logs](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/desktop-runtime-import-diagnostics/verification.json). Argument-only validation confirmed the same Electron pin/hash; **no native Electron or full application backend was launched in this batch**. The real import stall remains unidentified.

### Startup attachment correction after the first native run

The first normal-entry native run (`20260914-204222-57b672af`) reached backend readiness in 35.42 seconds, then failed with `desktop_full_application_attach_timeout`. It completed verified cleanup, but performed no editing, recovery or screenshot acceptance. [Retained native evidence](C:/Users/might/Documents/Codex/2026-09-12/hi/outputs/inspectorpro-runtime-20260914-204222-57b672af/native-launch.json).

The missing startup route is corrected: after profile/assembly initialization settles, the bridge validates the main-provided runtime and document, applies Facility Layout defaults before switching to Workflows, and awaits the single mount started by that switch. The authorized document is used even if the URL omits `facilityLayoutId`. Query parameters alone never enable the desktop route; mismatches fail before mounting. Repeated startup calls join the original attempt.

Managed startup now preserves typed authoring/bootstrap/attachment failures instead of treating a legacy-viewer fallback as success. The native driver records the startup stage and code and requires both completed startup and actual lifecycle attachment. Input locks, capability gates, the 45-second backend deadline and the 60-second attachment deadline are unchanged.

**58 focused Node tests passed**, including 33 new startup checks with the actual session/bridge and extracted application initialization, activation and mount functions. These cover delayed profile loading, one mount, authorized-document selection, retained-recovery gating, and failure without legacy fallback. The four inline application script blocks and changed JavaScript passed syntax checks. This verifies the code correction; native acceptance remains pending. The consolidated command below is the subsequent application checkpoint, after startup diagnostics have been reviewed.

From an ordinary **unelevated** PowerShell terminal:

```powershell
& 'C:\Users\might\Documents\Codex\2026-09-12\hi\outputs\run-inspectorpro-runtime-integration.ps1'
```

Optional `-Port 8463` selects a free explicit port. The launcher never finds and terminates a server by port. `-ValidateOnly` verifies prepared paths and the installed Electron pin without launching the application.

The launcher prepares one fresh isolated copy of the manual layout, creates a managed profile, generates a legitimate acceptance proposal offline, then starts **the normal `entry.cjs`** with the same installed Electron 44.3.0 binary. The offline seeder uses the existing accepted proposal fixture and real operation services; it adds no fixture-only HTTP routes and does not invoke Sage or Save.

The native driver checks:

1. Full application mount, actual facility attachment, sandbox/context isolation, disabled general capabilities, and input restricted to the facility subtree.
2. Two manual edits followed by Close/Cancel, with exact snapshot preservation and input availability after cancellation.
3. Pending Apply and pending Undo through owned backend restarts, with the renderer retained, exact frame/history checks, and Save still blocked.
4. A recovered full-application screenshot, five transaction request paths observed once each, zero observed Save requests, and unchanged saved-layout hashes.
5. Close without saving, durable discard finalization, all owned backend receipts, Electron termination, and diagnostic stream closure.

Acknowledgment loss is injected after the real response has been produced, using Electron's main-process debugger connection and Chromium Fetch response-stage interception. This control is not exposed through IPC or available to external content. See [Electron debugger API](https://www.electronjs.org/docs/latest/api/debugger) and [Chromium Fetch protocol](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/).

Each stage persists logs and a process result. The combined `native-launch.json` points to `native/runtime-integration-check.json`, `native/runtime-final-result.json` and `native/full-application-recovered.png`. An automated pass still requires visual inspection of that screenshot. The screenshot records observed window geometry; the old exact 1440 × 960 case is not silently marked exercised.

The new native checkpoint does not repeat the unchanged ten-case isolated recovery matrix. Plain-draft reopening and retirement are covered by real-session/adapter tests in this batch; native reopen-after-discard is not claimed. The earlier accepted 37-GLB/827-transform/library checkpoint is not presented as a new full-app asset audit.

## Developer use

Create an empty isolated developer profile with explicit absolute paths, using a fresh profile file and data directory:

```powershell
& 'C:\Python314\python.exe' desktop/runtime/create_profile.py `
  --profile-file 'C:\your-workspace\desktop-profile.json' `
  --data-root 'C:\your-workspace\desktop-data' `
  --profile-id 'developer-desktop' --port 8463

Set-Location desktop
npm ci
npm start -- --profile-file 'C:\your-workspace\desktop-profile.json' --python 'C:\Python314\python.exe'
```

The empty profile renders the whole application with interaction locked at this acceptance stage. The prepared native launcher is the supported way to obtain a marked facility test profile. Do not point a developer profile at the live manual layout store or remove capability checks to make an unsupported workflow appear enabled.

The File menu offers retained-draft review and Close; View offers guarded Reload; Backend offers owned restart. Close defaults to Cancel for dirty work. Multiple retained unresolved checkpoints remain blocked for explicit review. A failed initial start may close after owned-process/stream termination is confirmed, while retaining its failed application-cleanup evidence. This exception cannot close an attached facility or an unresolved restart as though cleanup succeeded.

## Remaining product work

- Pass and visually review this normal-entry native checkpoint, fixing its findings within the same batch.
- Integrate and accept truthful lifecycle coverage for other workflows, including assets/files, motion, voice and live Sage; general editing and Save require their own authorization and persistence checks.
- Complete supported attach/pairing UX and acceptance; no interactive paired browser is claimed here.
- Build the isolated tabbed research pane after the protected runtime is accepted. Citation opening, tabs, resizing and engineering-state preservation belong in one browser milestone.
- Installer/runtime bundling, clean-machine distribution, updates and agent browser control remain later work.

The existing externally docked motion panel is outside the facility subtree and remains inert in this milestone. Plain manual drafts are checkpointed when preparing a lifecycle decision, and transaction checkpoints retain their required frame; this is not per-gesture autosave. Abrupt loss before a checkpoint, renderer/process-loss UX, competing retained recovery choices, and earlier intermittent startup/spatial timeouts remain follow-ups; this run does not establish a fix for those earlier timeout causes.

## Review cadence

For the rest of this project, group three to five connected implementation steps into a concrete milestone. Run necessary tests and obtain internal agent review during the batch. Send the user's coding agent one report with scope, files, test evidence, limitations and the next acceptance command. Escalate earlier only for a real blocker, a product decision, or a required permission; do not require the user to relay every local correction between agents.
