# P5b - independent release and live desktop gate

## P5b-1

Status: the builder delivered the harness with static checks only. The supervisor
ran it, corrected it, and changed one product expression (see "Supervisor gate"
below). The desktop smoke now passes 45 of 45 checks in the real Electron
application on a disposable profile. P5b remains open: the port, the restart of
the user's application, the witnessed sequence (including step e) and the live
Sage run are still owed. The runner always records releaseGateComplete: false; a
passing automated report does not close the independent release gate.

### CHANGED

- tests/smoke_documentation_editor_desktop.cjs: a Node >= 22.12 runner, using
  desktop/tools/owned-child-runner.cjs. It owns three successive Electron launches
  on one disposable application profile: edit/save/close; restart/history/dirty
  close; review and customer exports. A single 15-minute deadline covers the run,
  including preparation of dependency evidence and normal cleanup. The process
  grace periods have time reserved inside that deadline. DOC_SMOKE_SLOW (1..10)
  scales named condition deadlines, never a measured value or the whole-run cap.
- desktop/tools/documentation-editor-prepare.py: prepares a NEW output below an
  isolated snapshot's .runtime. It uses documentation_baseline.local_inventory's
  engineering input allowlist, the optional semantic-knowledge prototype contract,
  and the browser proof's manual-plan.json/documentation-scene.json seeds. It does
  not copy a library wholesale, import server.py, start a service, or load an
  account/profile from the user's application. It copies all assemblies required
  by the documentation registry's validation (including its MMLE-50D entry), not
  just the model of the selected assembly. A hash/size/destination manifest records
  exactly which supplied inputs were copied. Existing output directories are
  refused; the disposable marker is written last.
- desktop/tools/documentation-editor-contract.cjs: shared preflight, environment,
  disk snapshot and report functions, importable without Electron. Both runner and
  native entry refuse a live checkout (.git or missing snapshot marker), an
  overlapping source/snapshot, an incomplete snapshot, an unmarked/foreign
  profile, linked paths, arbitrary profile extensions, displaced stores/evidence,
  port 8480, or a non-loopback origin. The runner checks that its assigned port is
  free before every launch; it never attaches to an existing app or backend.
- desktop/tools/documentation-editor-native-entry.cjs: installs the same
  main-process-only application-check replacement used by the packaging native
  check, then requires the UNCHANGED application-main.cjs. Application mode,
  application preload, sandbox, context isolation, navigation and permission
  handlers, native document preview and managed backend are the production ones.
  It records the Electron version and webPreferences, and requires 44.3.0.
  Pointer/key input uses webContents.sendInputEvent; no editor commands, synthetic
  DOM click events, private-token extraction or direct scene-store writes are
  used to implement the edits. DOM evaluation reads state and scrolls controls
  into view. Ribbon clicks use the visible command or More's entry whose
  _documentationSource is that command; folded dropdowns expose their items.
- desktop/tools/documentation-editor-evidence.py: a hidden, directly owned helper
  reports the actual interpreter, dependency module locations and search path;
  validates PDF/DOCX files and extracts text; or presses one named button on the
  native #32770 dialog with a named title of the OWNED Electron PID (the builder's
  version pressed Cancel only; see Supervisor gate). The driver forwards the real
  showMessageBox call and records its wording; it does not mock its result.
- desktop/tests/documentation-editor-desktop.test.cjs and
  desktop/tests/test_documentation_editor_prepare.py: safety refusals, isolated
  environment propagation through the existing runtime, report shape, canonical
  disk snapshots, strict optional-request classification, fixture copying and
  incomplete preparation. No package.json/package-lock.json change.

The builder changed no product, compiler, exporter, schema, static asset,
baseline, browser smoke or P5a scale harness file. The supervisor later changed
one expression of the desktop close guard in static/index.html (Supervisor gate,
product change). No static cache version bump is needed: index.html is the page
itself, and no static JS/CSS file changed.

### Disposable stores and backend propagation

Let OUTPUT be the preparation directory and EVIDENCE be OUTPUT/e. All mutable
profile state lives below OUTPUT, with short document-store names:

| Setting / state | Destination and propagation |
| --- | --- |
| Application profile | OUTPUT/profile.json; application mode, unique backend/store/profile IDs, a free 127.0.0.1 port other than 8480 |
| dataRoot | OUTPUT/d, loaded by the existing application profile reader |
| Facility and library | OUTPUT/d/f and OUTPUT/d/l; application_backend assigns the profile's roots before importing server |
| INSPECTORPRO_PARTS_MANUAL_ROOT | OUTPUT/d/p |
| INSPECTORPRO_OPERATIONS_MANUAL_ROOT | OUTPUT/d/o |
| INSPECTORPRO_SPECIFICATION_SHEET_ROOT | OUTPUT/d/s |
| INSPECTORPRO_WORK_INSTRUCTION_ROOT | OUTPUT/d/w |
| INSPECTORPRO_INSPECTION_SHEET_ROOT | OUTPUT/d/i |
| INSPECTORPRO_ASSEMBLY_APPEARANCE_ROOT | OUTPUT/d/a |
| INSPECTORPRO_PART_APPEARANCE_ROOT | OUTPUT/d/b |
| Assets, scenes, receipts, plans, captures and exports | The respective document/appearance roots above, through their existing repositories |
| Telemetry | INSPECTORPRO_METRICS_DB=OUTPUT/d/metrics.sqlite |
| Memory | INSPECTORPRO_MEMORY_DB_PATH=OUTPUT/d/memory.sqlite; memory mode off |
| Chromium profile, shell logs and shutdown evidence | The shell's existing dataRoot/desktop-client and dataRoot/desktop-logs paths; no Chromium state is copied or read by this driver |
| OS/user/temp defaults for the child | OUTPUT/os (including APPDATA/LOCALAPPDATA) and OUTPUT/tmp |
| Rich editing | INSPECTORPRO_DOCUMENTATION_RICH_TEXT=1 |
| Python dependencies | Explicit repeated --dependencies folders become PYTHONPATH; PYTHONNOUSERSITE=1; dependencies.json records the actual interpreter/version/module paths/search path |

The outer runner builds an environment allowlist: OS launch essentials, the
selected Python directory/System32 PATH, and the explicit settings above. It does
not inherit API keys, proxy settings, NODE_OPTIONS, a user's PYTHONPATH or user
profile paths. runtime-supervisor.childEnvironment's APPLICATION branch forwards
these values; its existing Codex/Packaging isolation still runs. The profile has
no modelGateway, codexRuntime or packagingRuntime. application_backend binds the
two profile roots and otherwise retains this environment. No runtime change was
needed. Both explicit dotenv lookup locations (snapshot/.env and its parent/.env)
must be absent; the harness tests existence, never reads them.

Only immutable engineering inputs are copied to their compiler-required paths in
the disposable code snapshot. The library registry copy is below OUTPUT/d/l.
The original source input files are read only by the allowlisted preparation,
never supplied as a writable store. The aggregate report includes the copied
input manifest and checks those copies remained unchanged (apart from the two
explicitly mutable seed files). No source fixture HTTP route is installed. Process-map editing remains off (its
flag is not inherited), so the optional process-map preview GET is refused before
its provisioning writer; generated/training is read-only evidence in this run.
Assembly startup copies any snapshot-root legacy assembly assets only into the
profile library. The normal backend startup/cleanup owns any optional search
browser; its temporary files inherit OUTPUT/tmp.

### Scenario and evidence

| Step | Automated path and evidence |
| --- | --- |
| a | Real application boot, own-origin MMLE assembly selection, Workflows -> Documentation, parts manual; flag and rich entry point check; disk scene snapshot |
| b | Insert Text through ribbon/More, resize using the actual handle, type heading, two-level bullets, bold/link paragraph, insert 2 x 2 table through Table and type two cells, Done. Canonical draft structure is compared with saved content; full IDs/envelope are retained and page/disk state compared. Table insertion's existing draft save and structural write remain separate writes. |
| c | Ribbon Undo/Redo (More aware), then Ctrl+Z/Ctrl+Y, each compared with the precise before/after envelopes on disk |
| d | Operations page-specifications-1, spec-table-1.r0.c1: change cited capacity to 1,000 lb; preserve the evidence marker and record edited_unverified field metadata and history from disk |
| e | NOT RUN: see below; never replaced by an injected conflict |
| f | Actual change('close') policy/cleanup, confirmed process exits, then a fresh Electron/backend on the SAME profile. Compare exact scene bytes, compiled documents, object content and history; undo the prior rich edit and redo it |
| g | Open rich editor and type an unsaved suffix. Call the real close path. Record save-before-close, refusal, or the real native question and Cancel. The question must name documentation among the affected workflows; the run's own helper presses Cancel; the draft must stay open and the store unchanged. Silent loss is a failing check, never repaired or marked expected. If the shell closes, the following owned launch still collects exports. |
| h | Review PDF and DOCX from Operations ribbon commands, observed in the native document preview. Match export receipt SHA256 to the complete file in the disposable store, retain it and parse its text. Confirm the cited value through the trusted user control/dialog. Customer POST through the app session, then window.open into the same native preview for each artifact. |
| i | Observe all webContents via CDP plus main-process fetch URLs/statuses, never headers or credentials. Preserve the shell's network-policy evidence. Unexpected console errors, failed requests, blocked requests, and external destinations fail. Shutdown evidence and owned child exit/stdio/resource confirmation gate each stage. |

Each edit/history check records document type, page/object IDs when applicable,
revision before/after, full on-disk state or its evidence filename, and hashes.
The aggregate report has stage reports, raw request lists, interpreter evidence,
PNGs, artifact paths/hashes/text evidence, and cleanup reports. Partial/missing
stage checks fail, even if Electron happened to exit with code zero. A failed
scenario does not imply a successful close: the outer runner checks the actual
shell cleanup report separately. An unconfirmed termination fails; the driver
never searches for or kills unrelated processes by executable name or port.

Parts has no DOCX. The rich list/table history proof is in Parts; the same heading
is typed in a separate Operations text box so that both native export formats can
be checked for that heading. This smoke's review/customer export pair is the
Operations publication. Captures are made by its normal export/Capture path, not
by forged ready flags or fixture raster substitution. Three full backend starts
and the initial real captures are expected to dominate runtime. The actual
elapsed time is reported; no runtime claim is made from static checks.

Only the browser smoke's existing narrow optional fixture failures are accepted:
GET drawing-map/drawing-pdf/part-features and process-map preview 404s, and GET
reference-views 500s, each listed with its URL/status. Intentional reload aborts
are restricted to GET bridge/status and static resources. The in-memory native
preview origin inspectorpro-document.invalid is separately named; it is a local
protocol handler, not an outbound server. The external example.com hyperlink is
stored but never followed. Every unexpected destination remains a failure.

### TESTS

Builder ran static checks only, with hidden direct subprocesses:

- node --check: the three new runner/helper CJS files plus the new Node test file
  (four files), passed.
- Python ast.parse: preparation helper, evidence helper and its pytest file
  (three files), passed. No application or optional dependency imports executed.
- Explicit LF checks on all new source/report files and read-only git diff/status
  review; no tracked product files changed.

No pytest, Node behavioural tests, Electron, managed backend, browser, provider,
PDF/DOCX generation or live UI was run by the builder. The native checks and their
runtime outcomes remain unverified until the supervisor runs them.

### NOT RUN

Use the supervisor's hidden launcher for every command: direct pythonw.exe plus
tools/run_hidden.pyw, redirected output and windowsHide on its parent; no visible
PowerShell/cmd trampoline. Paths below are absolute placeholders, not defaults to
the user's running app. Use a short SNAPSHOT path on Windows. No install command
is needed or allowed.

From the worktree, offline tests:

    <PYTHONW> tools/run_hidden.pyw <PYTHON> -m pytest -q desktop/tests/test_documentation_editor_prepare.py desktop/tests/test_prepare_snapshot.py desktop/tests/test_packaging_application_profile.py
    <PYTHONW> tools/run_hidden.pyw <NODE> --test desktop/tests/documentation-editor-desktop.test.cjs

The full desktop gate is npm test with cwd=desktop (unchanged package script).
To avoid invoking npm.cmd through a shell, use its installed JavaScript entry:

    <PYTHONW> <WORKTREE>/tools/run_hidden.pyw <NODE> <NPM_CLI_JS> test

Create the isolated code snapshot from the reviewed worktree (supervisor only):

    <PYTHONW> <WORKTREE>/tools/run_hidden.pyw <PYTHON> <WORKTREE>/desktop/tools/prepare-snapshot.py --source <WORKTREE> --destination <SNAPSHOT>

Then cwd=SNAPSHOT:

    <PYTHONW> tools/run_hidden.pyw <PYTHON> desktop/tools/documentation-editor-prepare.py --output <SNAPSHOT>/.runtime/de --inputs <WORKTREE> --dependencies <APP_DEPENDENCY_FOLDER>
    <PYTHONW> tools/run_hidden.pyw <NODE> tests/smoke_documentation_editor_desktop.cjs <ELECTRON_44_3_0_EXE> <SNAPSHOT>/.runtime/de/profile.json <PYTHON> <SNAPSHOT>/.runtime/de/e

Repeat --dependencies for each required installed folder, or omit it if the
selected interpreter already has the app dependencies outside its user site.
Set DOC_SMOKE_SLOW in the hidden launcher's environment, if needed. The report is
<SNAPSHOT>/.runtime/de/e/report.json; a fresh profile/output is required for a new
run. No Electron package resolution from desktop/node_modules is used. Do not
launch this runner from the worktree: its live-checkout refusal is intentional.

Not automated in this slice:

- e, source refresh/conflict/review resolution. P1c's source mutation wraps the
  in-memory catalogue and exposes /__p1c/source-fixture in its test launcher. The
  actual application backend does not load that launcher. Known assemblies are
  served from assembly_profiles; _parts_manual_catalog_for_assembly reloads only
  when a number is absent. Copying the test fixture JSON alone changes nothing. This driver neither installs a route
  nor mutates compiler source nor writes a forged conflict into the store. The
  supervisor must cover a real scratch-source change and resolution in the
  witnessed sequence. The omission is also in the machine-readable report.
- The user's live application restart, port/back-up record, witnessed acceptance,
  live Sage read/edit/retry, and the independent release gate set in plan section
  9. They remain supervisor actions. The PyMuPDF release decision remains open.

### DEVIATIONS

- Source-conflict step e is explicitly omitted for the production-runtime reason
  above, as the brief permits. No fake pass substitutes for it.
- The ribbon has no Customer export mode selector. After the actual user
  confirmation, the driver uses the public customer endpoint in the authenticated
  application session and opens the returned artifacts through the application's
  native preview. This is recorded as customer_transport, not described as a
  ribbon customer control or a Sage run. No private credential is accessed.
- Three owned launches keep the requested order when the dirty-close test itself
  terminates the application. Each closes through the real policy in the normal
  path and has its own process/managed-backend cleanup proof.

### OPEN QUESTIONS

- What does the actual dirty rich-editor close do on this build? The harness
  records the result and fails silent loss; there is deliberately no product fix.
- Can the native Cancel button be driven on the supervisor's Windows build? If it
  is not exposed as the owned standard dialog button, the bounded check fails
  with the observed prompt; the witnessed gate must exercise that path manually.
- Does the entire run, including real capture work, meet 15 minutes on the gate
  machine? The runner caps it and records failure instead of silently extending
  the budget. The supervisor supplies the measured result below.
- P5b is not complete without the independent port/restart/witnessed/live Sage
  gates, including the omitted scratch-source conflict step.

Answers from the supervisor run: the dirty close asks the real native question and
the run's helper presses its Cancel (the draft stays open, nothing is lost); the
owned dialog's buttons are standard #32770 buttons and can be pressed by name; the
whole run took 222 s against the 900 s cap.

## P5b-1 supervisor gate

### Run

Snapshot made from the worktree with desktop/tools/prepare-snapshot.py, then
documentation-editor-prepare.py, then the runner, all through the hidden launcher;
never from the live checkout and never against the user's application.

| Item | Value |
| --- | --- |
| Electron | 44.3.0, the installed package of the user's real repo, executed read-only from its path (no install, no npm ci) |
| Node in Electron | 24.20.0 |
| Python | C:\Python314\python.exe 3.14.0, dependencies from the user's site-packages folder passed as --dependencies |
| DOC_SMOKE_SLOW | 3 |
| Result | final code: passed, 45 of 45 checks, 222 s (cap 900 s); the run before the last runner check: 44 of 44, 214 s |
| Stages | edit 12 checks, restart 10, export 10, plus runner checks (process and backend exits, native dialogs answered by the helper, inputs unchanged, 15-minute cap) |
| Requests | edit 379, restart 243, export 291; outside the app origin 0, failed 0, aborted 0, blocked navigations 0 (export also shows file: and the in-memory preview origin inspectorpro-document.invalid) |
| Optional failures | per stage exactly the accepted list: drawing-map 404 x2, drawing-pdf 404, part-features 404, training 404, reference-views 500 |
| Console | 0 unexpected errors in every stage |
| Owned processes | dependencies probe, edit, restart, export: each exited 0 with termination and stdio close confirmed |

| Check | Revision before -> after | Page equals store |
| --- | --- | --- |
| Rich text saved (heading, two-level list, bold, link, 2 x 2 table) | 4 -> 5 | yes, after 48 ms |
| Ribbon Undo / Redo | 5 -> 6 -> 7 | yes |
| Ctrl+Z / Ctrl+Y | 7 -> 8 -> 9 | yes |
| After restart on the same profile: Undo / Redo | 9 -> 10 -> 11 | yes |
| Cited capacity edit (Operations, page-specifications-1) | -> 1 | yes; evidenceStatus edited_unverified, claim CLM-SPEC-001 and source SRC-OEM-MMLE-WEB-2026 kept |
| User confirmation of that value | -> 5 | yes (see identity maps below); evidenceStatus entered_by_user, confirmed by local-user |

The first comparison (before any edit) records a difference on purpose: the seeded
parts store is a scene of schema 2 and the page shows it migrated to schema 8. The
store takes the migrated form with its first write (revision 4 -> 5). That check
does not require equality.

Exports, each matched to its export receipt's SHA256 and parsed, with the typed
heading found in all four: review PDF 2,148,896 bytes, review DOCX 1,587,304
bytes, customer PDF 2,148,399 bytes, customer DOCX 1,587,235 bytes.

Native dialogs (all "Unsaved work", buttons Cancel / Close without saving), each
answered by the run's own helper on the armed button:

| Stage | Affected workflows | Pressed | Why |
| --- | --- | --- | --- |
| edit, saved close | training | Close without saving | documents saved; only the Workflows goal is reported |
| restart, dirty close | documentation, training | Cancel | keep the open draft; it stayed open and the store was unchanged |
| restart, saved close | training | Close without saving | as above |
| export, saved close | training | Close without saving | as above |

### Supervisor changes to the harness

1. Environment: the stand-in home now has os\AppData\Roaming and
   os\AppData\Local. Without AppData\Roaming, Electron stopped at start with
   0x80000003. A unit test pins it.
2. Start page: the driver waits for the start page to finish its start-up
   requests before its own reload onto the assembly. The reload in the middle cut
   a request and the page logged "[ServerMemory] Initialization failed" for a
   request the driver itself ended.
3. Object entry: the first press on an unfocused object can be taken by the
   selection. Entering the editor and the cited cell is tried with two presses, at
   most three times, and every attempt is recorded (report.editAttempts). In the
   passing run the rich editor opened on the second press in the edit stage and
   on the first after the restart; the cited cell on the first.
4. Heading: made through the editor's own Style list (h2) instead of Ctrl+Alt+2.
   Under injected input that key never reached the editor (on Windows Ctrl+Alt is
   AltGr). The shortcut itself is therefore NOT proved by this smoke; it is a
   witnessed-sequence item.
5. Native dialogs: every showMessageBox is recorded (title, message, detail,
   buttons, response). One is answered only when the scenario armed an answer,
   by the helper pressing that named button of the owned process's dialog. The
   runner check native_dialogs_answered_by_helper fails a dialog nobody armed or
   one answered by anyone else. Reason: an earlier run passed its saved closes
   only because a person at the keyboard answered the dialogs.
6. Saved close: the application asks before every close from Workflows >
   Documentation (finding 1). The saved close now requires the documentation row
   clean and nothing but the Workflows goal reported, then answers "Close without
   saving". Any other unsaved work fails the check and is never answered.
7. Page/store comparison: a bounded wait (5 s times the wait factor), then the
   differing paths are listed. Identity maps confirmationAliases {id: id} are left
   out of the comparison and counted (finding 3); a map that renames anything
   still counts as a difference. The passing run counted 3 on the page and 0 in
   the store for the confirmation and both customer exports.

### Product change (supervisor)

static/index.html, _desktopInspectOtherWorkflows: the documentation row is now
dirty when an open rich-text draft has changes
(window.DocumentationRichText.active.dirty) and busy while it saves (.saving).
Before, a close with an open, changed draft named only "training" as affected, so
the question did not say documentation work would be lost; and from the code,
when the Workflows goal rule does not apply (a Facility Layout goal, or none),
nothing was reported and the close would discard the draft without asking. The
passing run shows "documentation, training". Two rows in
desktop/tests/workflow-source-observation.test.cjs pin it. Only the desktop bridge
calls this function (static/index.html near 22443, 22477, 22511); a browser never
reaches it, so the nine browser smoke phases were not rerun for it.

### Findings (not fixed here)

1. Every close from Workflows > Documentation asks "Unsaved work (training)", even
   when everything is saved: the shell counts the Workflows goal as unsaved work
   whenever its type is not Facility Layout (pre-existing rule, pinned by the
   observation test). This is a product decision for the user.
2. Ctrl+Alt+2 (heading) is not proved under injected input; check it by hand.
3. Reading a scene adds confirmationAliases {id: id} to a confirmed field's
   metadata (ai_inspector/documentation/identity.py); the store gets it only with
   the next write. It changes no value and no hash (provenance.py falls back to
   the same keys), but page and store differ until then.
4. Step e (source change and conflict) cannot run against the production backend
   (no source-change route); the witnessed sequence must cover it on a scratch copy.

### Gates

Run on the final code of this slice (the runner's own-helper check was added
after the suites; it touches only the runner and its unit test, both rerun).

| Gate | Result |
| --- | --- |
| Baseline checks (synthetic, local) | exit 0, exit 0 |
| Desktop Node tests (node --test desktop/tests/*.test.cjs) | 890 tests: 877 pass, 13 fail; the 13 are the same test names that fail on the base commit 2ea742f (environment) |
| Desktop Python tests (pytest desktop/tests) | 443 passed, 1 skipped, 1 failed = the same failure as on the base commit (test_runtime_import_diagnostics ... forced_exit) |
| documentation-editor-desktop.test.cjs | 23 of 23 |
| Pin tests | 151 passed, 11 failed = the same 11 as at the P5a-3 gate |
| Documentation suites (Python) | 2075 passed + the 1 known failure (test_source_ids_references_and_local_hashes_are_closed) |
| Documentation suites (Node) | all files pass, 0 failures |
| Wide suite | 179 failures = the known 179 IDs; none new, none gone |
| Desktop smoke | 45 of 45, 222 s |

The runtime-startup.test.cjs case "viewport replacement suspends the connected
facility" failed on the branch only (its sandbox lacked _disposeAssembly3DMount);
the supervisor's stub now records 'assembly-release' and the case passes.

Not rerun for this slice: the nine browser smoke phases (only the desktop bridge
reaches the changed close guard). The full P5a run owed from P5a-3 ran in the
port rehearsal below (199 of 199 in 27 minutes).

## P5b-2 port rehearsal (supervisor)

The user's real checkout is at the branch base 2ea742f with uncommitted work of
the user's: 18 modified tracked files (CAD finish and appearance runtime, part
tools, facility appearance library; 8 of them also changed by this branch) and
144 untracked new files (cad_*.js, part_gradient/lighting/spotlights.py, a
vendored GLTFLoader, documents). The port must keep all of it. The real checkout
was only read (git status with --no-optional-locks, file reads); nothing was
written to it.

Plan (port_doc_editor.py plan, read-only), branch tip a68d2d8, 31 commits:

| Kind | Files | Meaning |
| --- | --- | --- |
| take | 142 | new in the branch, or unchanged by the user: the branch version |
| take, line endings | 9 | unchanged by the user, working copy differs only in CRLF: the branch version |
| take, earlier copy | 1 | docs/documentation-editor-capability-matrix.md: the user's untracked copy is this branch's first version; it is backed up and replaced |
| identical | 1 | docs/documentation-editor-audit-and-strategy.md |
| clean three-way merge | 6 | assembly_appearance.py, documentation_pilot.py, documentation_tools.py, progress.py, server.py, tests/test_assembly_appearance.py |
| resolved conflict | 2 | static/index.html: the user's _disposeCadFinishRuntime(state) joins the one Assembly mount disposer _disposeAssembly3DMount (after the display pass, before the scene and renderer go, the user's own order); tests/test_assembly_display_styles.py: both sides' assertions |
| stop | 0 | |

Rehearsal copies (all outside the real checkout):

- rs0: prepare-snapshot copy of the real checkout as it is (no port).
- rs2: the same copy with the port applied by the same script.
- rg: a detached git checkout of the branch tip with the user's 18 modified files
  (merged, from rs2) and 144 untracked files on top: the exact post-port state,
  where tests that read earlier commits through git can run.

| Check | Without the port (rs0) | With the port |
| --- | --- | --- |
| User's own tests (assembly appearance, display styles, signs and scenes, codex part tools, facility appearance library) | 140 passed, 1 failed | 141 passed, the same 1 failed (test_manifests_are_complete_and_every_file_matches_its_recorded_hash, a hash in the user's library manifest) |
| tests/test_assembly_library_panel.js | 16 of 16 | 16 of 16 |
| Desktop Python tests | 433 passed + the known 1 | 443 passed + the known 1 |
| Desktop Node tests | 851 pass, 14 fail (13 known + application-close.test.cjs, timing: 3 of 3 alone) | 877 pass, the known 13 |
| Wide suite | 101 failure IDs | the same 101 IDs, 15 more passing tests |
| Documentation suites (rg) | | 2075 passed + the known 1; Node files 9 of 9 |
| Desktop smoke (snapshot of rg) | | 45 of 45, 219 s |
| Browser smoke P1a (rg) | | 27 of 27 |
| Browser smoke P5a (rg), full size, DOC_SMOKE_SLOW=4 | | 199 of 199 in 27 min (limit 40 min); 20 memory cycles, rendering contexts 9 -> 9 with the user's CAD finish release inside the mount disposer |

The P5a run is also the full P5a run of the final code that P5a-3 left owed; it
finished inside 40 minutes while the user's OneDrive sync used about one core.
Its budgets are as at P5a-3: open of 100 pages p95 11.0 s (budget 5 s, missed),
save p95 7.4 s (budget 1 s, missed; server p95 3.2 s), PDF of 100 pages p95
20.3 s (30 s, met), selection p95 33 ms (150 ms, met), typing p95 17 ms. The two
misses stay written findings for the user (an incremental compile is a design
decision).

The documentation suites first ran in rs2, which has no .git: 237 tests that load
an earlier committed module through git show (or list tracked files) failed
there for that reason alone, plus the known 1. In rg they pass.

The rehearsal found one defect, fixed in a68d2d8: the mount dispose test
(tests/documentation_performance.test.cjs) ran the merged disposer in a sandbox
without the user's _disposeCadFinishRuntime and failed with a ReferenceError.
The sandbox now has it, and where the page defines it the test requires its
release in that position (mutation-checked on the merged page).

The first desktop smoke of rg failed only its network checks: the page asked for
the user's untracked new files (static/cad_*.js, the vendored GLTFLoader.js) that
rg did not have yet. They exist in the real checkout. With them, 45 of 45.

Note for the user's own testing: the browser smokes copy tracked files into their
isolated server, so until the user's new files are committed, a browser smoke run
from the real checkout will miss them. The rehearsal put them in rg's index for its
smokes only.
