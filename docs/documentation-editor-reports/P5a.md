# P5a - measured scale and recovery

## P5a-1

### CHANGED

- Added tests/test_documentation_recovery.py and tests/documentation_recovery_support.py. They reuse the small transaction scene fixture, create stores only under pytest's temporary root, and start real child processes with CREATE_NO_WINDOW, redirected output and no stdin. Barriers wrap existing os.replace calls inside the child; refresh uses its existing candidate-validation callback. No product crash hook was added. Every case uses assert_complete: public read plus canonical-byte comparison of the complete scene/history/receipt projection. For a future schema it first asserts the public refusal, then compares the canonical bytes of the refused file.
- Added tools/benchmark_documentation_editor.py, tools/documentation_benchmark_support.py and tests/test_documentation_benchmark.py. Generated catalogues/plans go through the parts compiler; generated manuscripts replace only the operations content provider, then go through the real operations compiler and flow planner. The existing synthetic CAD picture/manifest generators are reused, and captures pass through the real artifact writers. Every tenth compiled page has four authored objects: rich text, table, image and shape.
- server.py reuses the current page-setup publication, compiles each needed scene state once within the check, and returns the checked candidate instead of compiling it again. The design report is requested only when current-versus-candidate findings require it. The existing check in parts_manual/documentation.py now sees the final candidate journal and edit versions, before persistence, so the reused document has the final revision. The same path serves Sage. No schema or successful command shape changed.
- (Withdrawn in the supervisor gate below; the routes read requests as in b624c22.) server.py uses _documentation_stated_fields for both scene commands and object batches. A model contributes only model_fields_set; a dictionary contributes only its supplied keys. Explicit null/false survive; absent aspectLock does not become an explicit unlock or a null.
- documentation/targets.py and codex_runtime/documentation_tools.py add read_document_pages(tableStructureOnly=true). Table-bearing fields return columns, row IDs, parallel cellIds/headers/textLengths arrays and mergedRanges (zero-based row/column, rowspan/colspan), without the envelope, plain text or provenance text copies. Hashes and bindings stay the same. Structural reads can bind table operations; they cannot authorize unread whole-text/range replacements. Default reads are unchanged. The existing 64 KiB ceiling remains.
- Added tests/test_documentation_server_reads.py for compact reads, the maximum 600-cell read (540 cells after the gate), request presence (removed in the gate), compile counters and candidate-versus-fresh-read equality. Updated the read-option pins in all three Codex inventory test files. No client, smoke, baseline, compiler or exporter file was changed.

### Recovery case table

“Reachable” below means a concrete existing seam is wired in the test, not that the child was executed here. All runtime outcomes remain NOT RUN.

| Case | Reachability / named point | Assertions and findings to check |
| --- | --- | --- |
| 1. Before replace | Reachable: before_replace on the scene file | Old complete state; abandoned temp is not read as the scene; retry applies once. |
| 2. After replace, before receipt delivery | Reachable: after_replace | Complete new state and recorded receipt; retry leaves history/revision unchanged. |
| 3. Refresh rebuild | Reachable: refresh_compile through the existing validate_candidate callback, with changed generated-source binding | Kill while the candidate is rebuilt; committed scene remains complete and unchanged. |
| 4. PDF/DOCX export | Reachable: export_before_replace, export_payload, export_ready, for both formats | No ready metadata before its replace; ready metadata names complete length/hash-verified bytes; retry opens a real PDF/ZIP; scene unchanged. |
| 5. ENOSPC | Reachable: temp creation, write, flush, fsync and replace, for the regular scene write and both first-migration writes | DocumentationSceneError reaches caller; old state stays; ordinary exception cleanup removes the temp. |
| 6. Permissions | Reachable: PermissionError at temp creation and winerror 32 at replace | Existing error and cleanup; real replacement retry loop, with its delay suppressed only in the test; retry after removal applies once. |
| 7. Two processes | Reachable: two prepared pre-images synchronized at race/before replace | Exactly one success, stale_revision for the other, complete winning state and correct retries. Source inspection predicts a failure: the lock is process-local (see below). No xfail. |
| 8. Interrupted migration | Reachable: before_backup, after_backup, before_replace and after_replace | Original bytes remain in the original file or v7 backup; next open/write completes; backup exact. |
| 9. Future schema | Reachable: version 9 through public read | Existing unsupported-schema refusal; scene and pre-existing backup bytes unchanged. |
| 10. Restart | Reachable: independent commit and read processes | Exact public-read canonical bytes, including history and receipts. |
| 11. Restore original backup | Reachable: copy only the versioned bytes into another temporary store | Opens to the pre-migration publication/scene; source store is not overwritten. |
| 12. Retained/evicted receipts | Reachable: retained retry after later edits; real eviction path with retention temporarily reduced to two | Retained result exact; evicted stale pre-image gets content_hash_mismatch and cannot apply again. |

No case was omitted for lack of a product seam. Tests are unmarked: a failed promise stays a failure for supervisor review.

### Findings (source inspection; runtime confirmation pending)

- The scene repository uses threading.RLock, not process exclusion. Two processes can both pass the pre-image checks, wait with complete candidate files, then replace the same scene and both report success. The synchronized test is expected to expose a lost update/receipt while still verifying that the final file is one complete candidate. The test also permits a future process lock to serialize access; it does not require both writers to reach the seam. No locking fix was made.
- Killing a process before replace bypasses finally cleanup. The abandoned .tmp-documentation-* file is ignored by public reads and later writes; later writes do not sweep it. Ordinary ENOSPC/PermissionError exceptions do run cleanup. The tests distinguish those cases.
- The benchmark's large parts fixtures exercise the compiler's existing fixed contents/group-index pages (23 groups at 50 pages, 48 at 100). Their fixed row placement can extend beyond those frames. This is not repaired or hidden by the benchmark; any export refusal is recorded separately from successful timing samples. Visual scale assessment remains P5a-2.

### Optional-field audit

The objects route's outer body has no optional fields: documentId, expectedRevision, requestId, sourceRevision, manualPlanRevision, sceneRevision and operations are all required. It uses dictionaries rather than adding Pydantic defaults. Both routes now use the same presence reader (withdrawn in the supervisor gate below).

| Scene command body field(s) | Meaning when unstated |
| --- | --- |
| targetId | Existing empty/default target addressing; operations requiring an object/element still reject a missing target. |
| translation, rotation, sizeDelta | No vector supplied; the relevant translate/rotate/resize validator refuses it. |
| transforms, arrangement | No arrangement payload supplied; relevant arrangement validation applies. |
| cameraPreset, explodeDelta | No view/spacing value supplied; the relevant operation refuses it. |
| anchorSide, anchorPoint | No anchor choice; set_anchor requires exactly one. |
| leaderStyle, endCondition, repeatedPartStrategy | No requested route/end/repeated-part value; the relevant setter requires one. |
| documentObject | No object to add; add_object requires it. |
| frame | No frame supplied; only an explicit aspectLock change can use the existing frame. |
| aspectLock | Preserve the current lock and enforce its ratio; explicit true/false follows the P4a-2 rule. |
| crop | Existing nullable crop behavior: the crop setter reads absent as null/removal. |
| order | No full order supplied; scene set_object_order requires one. |
| objectIds | No authored selection supplied; arrange_objects requires a valid selection. |
| text | Existing update_text empty-string projection. |
| richText | No rich envelope; replace_rich_text refuses it. |
| expectedContentHash | No observed rich hash; the existing rich write binding check applies. |
| wholeFieldReplacement | False: no authority to discard a rich field through plain replacement. |
| style | No style patch; update_style requires a nonempty valid patch. |
| theme, pageMasters | No theme/template payload; the relevant global operation validates what it needs. |
| pageSetup | Refused for set_page_setup; explicit null returns to design geometry. |
| actor | Existing user default. |

| Object-operation optional field(s) | Meaning when unstated |
| --- | --- |
| x, y, width, height, rotation | Keep that frame component; on an aspect-locked object a lone width/height carries the other if aspectLock is absent. |
| aspectLock | Preserve lock/ratio; explicit true/false states the new proportions/lock. |
| order | Use the alternative objectId + to addressing; one form must be complete. |
| objectId, to (set_object_order) | Use the alternative complete order list. |
| crop | Existing nullable crop behavior reads absent as removal; the advertised tool schema requires the key. |

Other object-operation fields (pageId, the applicable hash/hash list, objectId for frame/crop, objectIds and arrangement for arrange) are required by their operation. This slice does not change their validation.

### Benchmark interpretation

- Each run is a fresh hidden process over a separate copy of the temporary generated fixture. Cold open measures scene read plus compile, excluding Python startup/input decoding; the OS disk cache is not purged. Commit and undo include the response compilation. PDF/DOCX call builders directly, not cached artifact responses. Capture preparation/carry happens outside export timing.
- Median and nearest-rank p95 use five samples by default. Units, raw samples, actual pages/blocks/objects/BOM rows/CAD figures/scene bytes and output byte counts are written to JSON. Missed p95 budgets print MISSED with the measurement; errors print ERROR/NOT MEASURED and an incomplete sample set cannot pass a budget. The reporting tool exits 0 even on a missed budget or measured failure.
- Requested one-page publications cannot be full publications from these compilers: minimum operations is four pages and minimum parts is six. The tool keeps those mandatory pages and reports both requestedPages and actual pages. The generated 50/100-page inputs target those complete sizes. It never slices compiled pages to manufacture the requested count.
- Peak RSS uses psutil peak_wset where available; otherwise the actual platform peak (Windows GetProcessMemoryInfo or POSIX resource.ru_maxrss). JSON records the selected method. No RSS/timing number has been measured here.
- P0.md has no numeric open/export/RSS measurement to compare. The table prints “not recorded”; JSON carries null P0 measurements with the source, not an invented baseline.
- Scene-state compile counters exclude the separate source-identity catalogue build with no scene. The accepted route tests require at most two scene-state compiles and fresh-read byte equality; a refusal counter allows at most three distinct states. The check also reuses already supplied current publications. This does not cache source identities across requests.

### TESTS

- Python AST syntax checks passed for all 13 changed/new Python files, through pythonw.exe tools/run_hidden.pyw with hidden child flags and redirected output.
- git diff --check passed. All written files use LF. server.py's UTF-8 BOM is retained; its added lines are ASCII (pre-existing non-ASCII text was left untouched).
- No pytest, benchmark, browser or export run was made. No performance or recovery pass count is claimed.

### NOT RUN

Run these in the supervisor environment through the existing hidden runner:

~~~text
python -m pytest -q tests/test_documentation_recovery.py --durations=20
python -m pytest -q tests/test_documentation_benchmark.py tests/test_documentation_server_reads.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_change_undo.py tests/test_documentation_page_setup.py tests/test_documentation_objects.py tests/test_documentation_tables.py tests/test_documentation_rich_text.py
python -m pytest -q tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py
python tools/benchmark_documentation_editor.py --pages 1 50 100 --runs 5 --out "$env:TEMP\documentation-benchmark.json"
python tools/documentation_baseline.py --inventory
python tools/documentation_baseline.py --local --inventory
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python -m pytest -q tests/test_documentation_baseline.py
python -m pytest -q tests/test_parts_manual.py tests/test_inspection_sheet.py
python -m pytest -q tests/test_specification_sheet_slots.py tests/test_specification_sheet_workflow.py
python -m pytest -q tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
python -m pytest -q tests/test_documentation_form_fields.py tests/test_documentation_library_assembly.py tests/test_parts_manual_ui_contract.py tests/test_parts_manual_callout_quality.py
python -m pytest -q tests/test_operations_manual_precoding_contracts.py
python -m pytest -q tests
~~~

Confirm the recovery file finishes within three minutes; it uses small stores, bounded child waits, and a shortened retention window rather than 1,000 writes. Browser P5a, keyboard/accessibility/scaling and retained memory over 20 open/close cycles are P5a-2, not implemented or claimed here.

### DEVIATIONS

- Full compiler minimums replace the impossible one-page full-publication fixture: operations 4, parts 6, explicitly recorded. No compiler or export bypass.
- No numeric P0 comparison is possible because P0 recorded none.
- Read-only-directory and sharing-violation cases inject the OS PermissionError at the writer seam; they do not change filesystem ACLs. The eviction test reduces the retention window only inside the test for speed.
- Runtime reachability, recovery duration and benchmark results await Claude. The suspected process-race failure is intentionally not fixed or marked xfail.
- Baseline JSON, smoke, client controls, schema, compilers and exporters are unchanged. No commit or index/history mutation was made.

### OPEN QUESTIONS

- Confirm and decide the two-process writer finding; the test remains a release gate failure if both callers succeed.
- Decide whether abandoned crash temps should be swept in a later fix. They currently cannot become the committed scene.
- Review measured budgets and large-fixture generator findings on the supervisor's Windows machine; no budget was relaxed.

## P5a-1 supervisor gate (Claude, 2026-11-13)

### What I ran and what it showed

The recovery file, first run: 35 of 36 cases passed in 19 s. The one failure is the finding the report
predicted: two processes that prepared the same pre-image both replaced the scene and both reported success,
and the first one's edit and receipt were gone. Every other promise held as written: old or new state and never
a mixture, for a kill before the replace, after it, during a refresh, during an export, on a full disk, on a
denied replace, on an interrupted first migration, on a newer schema, across a restart and after restoring the
versioned backup into another store.

The other new files, first run: 5 failures, none in the product. Three tool-list tests read a `read_only` key
that read tools do not carry (the default is read-only); the largest-table test built 50 x 12 cells, which one
text box cannot store (96 KiB; an empty table stops near 46 x 12); the benchmark's operations manual did not
compile.

### What I changed

- `ai_inspector/parts_manual/documentation.py`: one transaction on a store at a time across processes. The
  repository's lock was a thread lock. `_store_writer(root)` keeps it and adds a lock that other processes see:
  on Windows a named mutex (`Local\InspectorPro-documentation-` + the SHA-256 of the store root), elsewhere
  `fcntl.flock` on the store folder itself. It is taken once per outermost transaction, waited for up to 60 s
  (then the refusal "another InspectorPro process is writing this documentation store; try again") and released
  by the system if the process dies. The eleven transaction blocks of the repository use it. The second process
  now reads the first one's scene inside the lock and gets the usual stale-revision refusal. The class-level
  `transaction_lock` the routes hold is unchanged.
  Nothing is written for the lock. My first version took an empty lock file in the store root; the full suites
  then failed three tests that compare a store byte for byte around a refused operation
  (`test_slot_sage_cannot_confirm`, `test_sage_cannot_confirm_value`,
  `test_invalid_second_operation_commits_nothing[scene]`): a refusal must leave the store exactly as it was.
  The mutex keeps that promise; those tests are unchanged and pass.
- `server.py`: the scene command route passes the whole request body again, as committed in b624c22, and the
  stated-fields reader of this round is removed with its test. The scene validators read many fields by key and
  take None as "not supplied"; passing only the stated fields would turn a request that leaves a needed field out
  into a KeyError. The carried item (one reader for both routes) is withdrawn; the optional-field table above
  stays as the record of what an unstated field means.
- `tools/documentation_benchmark_support.py`: the generated operations manual has the three claims its fixed
  front pages read; its figures have the manual's own height (a lower frame is wider than the capture envelope
  and is refused); text objects are created plain and then given their rich content, as the product requires;
  the number of sections for a requested page count is found by compiling, so 50 and 100 requested pages are
  50 and 100 pages.
- `tests/test_codex_readonly_pilot.py`, `tests/test_codex_assisted_tools.py`,
  `tests/test_codex_documentation_tools.py`: `spec.get("read_only", True)`.
- `tests/test_documentation_server_reads.py`: the largest table every box accepts, 45 x 12 (540 cells); its
  structure-only read fits the 64 KiB tool answer.
- `ai_inspector/codex_runtime/documentation_tools.py`: the read tool says that a structure-only read is enough
  for `create_table` and `modify_table`, not for text edits (which is what the write guard enforces).

Kept as built: the page-setup check compiles each scene state once and its candidate document serves the
answer (the check now runs when the journal entry is final; the answer equals a fresh read on the four real
documents); the structure-only table read and its write rule (every table operation still binds the content
hash; no table operation writes cell text).

### Benchmark (this machine, five runs, median / p95)

| Document | Pages | Open | Save | Undo | Reload | PDF | DOCX | Peak memory |
|---|---|---|---|---|---|---|---|---|
| Operations manual | 5 | 0.12 / 0.12 s | 0.04 / 0.04 s | 0.05 / 0.06 s | 0.02 / 0.02 s | 0.49 / 0.51 s | 0.10 / 0.18 s | 117 MiB |
| Operations manual | 50 | 0.23 / 0.29 s | 0.25 / 0.35 s | 0.33 / 0.42 s | 0.14 / 0.15 s | 11.3 / 11.7 s | 0.27 / 0.28 s | 129 MiB |
| Operations manual | 99 | 0.35 / 0.37 s | 0.47 / 0.50 s | 0.61 / 0.62 s | 0.27 / 0.28 s | 23.5 / 23.8 s | 0.43 / 0.46 s | 142 MiB |
| Parts manual | 6 | 0.04 / 0.05 s | 0.07 / 0.09 s | 0.09 / 0.10 s | 0.04 / 0.04 s | 0.50 / 0.50 s | none | 103 MiB |
| Parts manual | 50 | 0.75 / 0.81 s | 1.39 / 1.45 s | 1.82 / 1.83 s | 0.71 / 0.78 s | 7.3 / 8.3 s | none | 169 MiB |
| Parts manual | 100 | 1.60 / 1.63 s | 2.98 / 3.17 s | 3.95 / 4.19 s | 1.55 / 1.62 s | 16.7 / 17.1 s | none | 233 MiB |

`python tools/benchmark_documentation_editor.py --pages 1 50 100 --runs 5`, run alone on a quiet machine (628 s).
The smallest complete publications are 5 and 6 pages; the generator reaches 99 operations pages for a request
of 100. Every tenth page carries four authored objects; a parts BOM page has 20 rows. Save and undo include the
compile of the answer. The parts manual has no Word export.

| Budget (plan, provisional) | Operations manual | Parts manual |
|---|---|---|
| Open 100 pages <= 5 s | MET, 0.37 s | MET, 1.63 s |
| Save <= 1 s | MET, 0.50 s at 99 pages | MISSED: 1.45 s at 50 pages, 3.17 s at 100 |
| PDF of 100 pages <= 30 s | MET, 23.8 s | MET, 17.1 s |
| DOCX of 100 pages <= 30 s | MET, 0.46 s | not applicable |

An earlier run of the same tool while other jobs were using the machine took up to twice as long (parts, 100
pages: save 6.3 s, PDF 32 s at p95): the PDF budget holds on a quiet machine only.

Where a parts save goes (one profiled save on the 100-page fixture): the repository reads the scene twice and
builds the generated inventory three times, and each build compiles the identity catalogue of the whole
generated document again (eight compiles, each starting with a full copy of a 7.7 MB document). Nothing in it
depends on the edit. That is old code (P1), not this slice's; it goes to Codex in P5a-2 as one build per
transaction, with the same bytes as the proof.

No budget is changed here and nothing was tuned. P0 recorded no timing to compare with.

### Measured and left

- Saving an edit on a parts manual of 50 pages or more is over the 1 s budget (table above).
- A process killed before the replace leaves its staged `.tmp-documentation-*` file behind. It is never read as
  the scene; nothing sweeps it.
- The specification sheet's slot store and the parts-manual plan repository still have thread locks only.
- The mutex is per Windows session (`Local\`): two servers under two signed-in users on one data folder would
  not see each other. One mutex handle per store root stays open for the life of the process (four in a server).
- The benchmark report says the generated parts manuals' contents and group-index pages place more rows than
  their frames hold (23 groups at 50 pages, 48 at 100). Not looked at here: P5a-2 opens these manuals in the
  browser and reports it with pictures.

### Gates

| Gate | Result |
|---|---|
| `tests/test_documentation_recovery.py` | 36 passed, 16 s |
| New and tool-list tests (5 files) | 162 passed |
| Baseline checks, shared and local | exit 0, exit 0 |
| Documentation suites, final code | 2044 passed, 1 failed: the known `test_source_ids_references_and_local_hashes_are_closed` |
| Node suites | 479 passed, 5 passed |
| Smokes, final code (wait factor 4) | P4a 475/475, P3b 169/169, P2b 36/36, P2a 23/23, P1a 27/27, P1c 35/35 |
| Smokes, lock-file version | all nine passed: P4b 198/198 (wait factor 6, 1903 s), P4a 475/475, P3b 169/169, P3a 194/194, P2b 36/36, P2a 23/23, P1a 27/27, P1b 46/46, P1c 35/35 |
| Wide suites, final code | the same 179 known failures, none new, none gone (parts a-d: 21, 64, 58 + 9 errors, 27) |

P4b, P3a and P1b did not run again after the lock became a mutex; they write through it in the same way as the
six phases that did. No smoke phase exists for this slice (P5a-2 adds it). The flag
`INSPECTORPRO_DOCUMENTATION_RICH_TEXT` stays off by default.


## P5a-2

### CHANGED

- Added run_p5a in tests/smoke_documentation_editor.py, implemented in tests/documentation_editor_scale_smoke.py with injected, test-only instrumentation in tests/documentation_editor_scale_probe.js. --phase all runs separate hidden child processes and snapshots and writes an aggregate report. Earlier phases do not prepare or load scale fixtures.
- Added tests/documentation_editor_scale_support.py, imported only by the sanitized launcher for INSPECTORPRO_DOC_SMOKE_PHASE=P5a. It prepares the benchmark fixtures before HTTP startup and installs the permitted real-MMLE fallbacks. Its loopback-only switch preserves each variant's temporary scene/plan bytes between visits. No fixture endpoint or hook was added to server.py.
- tools/documentation_benchmark_support.py adds assembly_number, defaulting to NUMBER, to profile, prepare, capture and attached. Default benchmark inputs and callers stay the same.
- Browser clocks use performance.now in one evaluation per action. Typing records 50 individual trusted key presses per run, from keydown to the second animation frame after input. Selection starts at trusted pointerdown; key and pointer endpoints are recorded before the driver round trip returns. PDF response observation continues if export backgrounds the originating tab. Five runs are retained for open, page change, typing, selection, save diagnostics, undo, redo, reload and object-batch settling; three for each requested ribbon PDF export. Median and nearest-rank p95 retain raw samples. Budget checks pass whether met or missed and carry met/p95/median/budget; unavailable measurements fail.
- Checks cover editor counts and document/window CDP listeners around 20 distinct-field edit cycles; forced-GC heap, canvas/context counts and one surface after 20 large-publication open/three-page/close cycles; keyboard event evidence; names, menu/dialog labels and status announcements; both themes' contrast; and eight viewport/device-scale pairs. Picture checks use P4b's homogeneous 3x3 patches, minimum 30 samples and maximum 8 RGB-level difference. Publication lookups are scoped to #documentationPublicationSurface. No fixed sleep or keyboard.insert_text was added.
- Minimal product fixes: labelled generic ribbon menus, arrow/Home/End navigation and Escape/focus return; Page Setup returns its command promise; More proxies await the same command callback so keyboard focus returns after redraw. Enter on a focused ribbon/menu control no longer opens a selected text box instead. Theme gets dialog attributes, initial focus, a Tab boundary and Escape/dismiss return. Symbol/Table Escape returns to its opener. Rich controls get role=toolbar; Symbol gets a labelled dialog role; Symbol/Table buttons advertise dialogs. The status span is a polite, atomic live region; a successful rich save announces "Text saved." Existing shortcuts, including Escape-cancel, are retained.
- Bumped documentation_rich_text.js to ?v=20261113-p5a-2. No CSS or other static JS changed. Added tests/documentation_scale_probe.test.cjs and tests/test_documentation_scale_harness.py for arithmetic, additive assembly arguments, actual counts, phase isolation, waits and refusal classification. No existing pin needed rewriting on source inspection.
- No schema, compiler, exporter, baseline, Sage tool or performance optimization changed. In particular, publication text fitting, bundle loading, P4b word measurement and generated-inventory construction are untouched.

### Harness replacements and fixture sizes

The workspace path was read first: _renderDocumentationWorkflowTab returns before creating the workspace when assemblyContext.has_glb is false. A generated entry in server.assembly_profiles serves server reads/exports but cannot open this workspace. No product gate or model-readiness check was changed.

The phase loads /?assemblyProfile=MMLE-50D, waits for the real assembly context, then uses the existing __compareDbg.openDocumentationWorkflow, document-type picker and Refresh callback. The timed open ends with the first page's text drawn. It is an application open, not a cold browser/process launch. Fixture switching and the initial metadata read are outside the clock; subsequent runs retain product caches. PDF timing includes the response body and excludes artifact download/screenshots. Cache hits are retained, not disabled.

| Fixture | Path / replacement | Size evidence |
| --- | --- | --- |
| Real MMLE cover | Original copied plan/scene and real model; the plan's one-page interaction case uses the cover | Runtime records the complete publication count, not a fabricated one-page document. |
| Generated parts 50 / 100 | prepare(d/p, parts, N, assembly_number=SCALE-P50/SCALE-P100), real compilers/repositories and accepted synthetic captures | P5a-1 reference sizes: 50 / 100 pages, 460 / 960 BOM rows, 20 / 40 objects, 25 / 50 figures, 23 / 48 top-level groups. New preparation records actual values. |
| Generated operations 50 | prepare(d/o, operations, 50, assembly_number=SCALE-O50) | Expected 50 pages and 20 objects. Actual blocks/figures/scene bytes come from preparation. |
| Browser parts 50 / 100 | MMLE fallback through the real parts_manual_section_create route handler: a nested chain of service groups reuses 20 distinct real definitions from an eligible leaf. Its own scene has four authored kinds every tenth page, through add_object then replace_rich_text. | Actual pages, rows, objects, figures, blocks, groups and bytes are fixtures.parts50 / parts100. The middle 20-row BOM gets text/table objects only if absent; measuredObjects records the resulting count. |
| Browser operations 50 | Only in the launcher, a scratch flag makes prototype_sections append sections(n), with a text-only tail when needed. The original manuscript/evidence/compiler/model remain; the provider swap is serialized and restored after each build. | Actual counts are fixtures.operations50. Compiled pages are never sliced. |

All variants live under the phase's temporary d/p and d/o. Only plan/scene control files and the scratch manuscript flag are switched, by atomic replacement under harness/repository locks. Captures and assets retain managed revision keys. capture(...) uses the existing 2400 x 1800 synthetic picture and validated manifests; this is not live CAD capture proof.

**New actual browser fixture counts are NOT RUN here.** p5a-measurements.json records them, wait factor, viewport and device scale. A fixture-size gate requires the requested 50/100 pages; if a fallback differs, its gate fails and timing is still labelled with the actual compiled count. A missing eligible leaf or unbuildable fallback is an error, never a substitute passing fixture.

### Keyboard paths found and added

| Step | Existing path | This round |
| --- | --- | --- |
| Reach page | Native Tab order; canvas already has tabindex=0 and a named region | Retained; actual Tab counts/targets recorded. |
| Insert text | Tab to Insert Text, or More's proxy, then Enter | Added generic menu navigation and Escape return. |
| Enter editor | Focus object (selects it), or focus canvas with box selected, then Enter | Excluded focused ribbon/menu controls from the object Enter handler. |
| Type / bold | Contenteditable input and Tiptap Ctrl+B | Unchanged. |
| Leave editor | Escape cancels; Done or blur saves | Unchanged; Escape-to-save is unavailable, separately reported. |
| Move / delete | Arrow 1 pt, Shift+Arrow 10 pt; Delete/Backspace removes one | Unchanged. |
| Undo / redo | Ctrl+Z / Ctrl+Y outside input/editor | Unchanged; waits use stored revision and rendered state. |
| Page Setup | Native activation opened the menu; arrow/Home/End/Escape return were missing | Added those paths; same command/write. |
| Theme dialog | Native fields and Close; no explicit Escape/focus return | Added attributes, initial focus, Tab boundary and return. |
| Symbol / Table | Tab to controls; Escape returned to editor | Labelled Symbol dialog, popup attributes; Escape returns to opener. |

After its event counter starts, the keyboard sequence uses page.keyboard only, not element.focus or app commands. Native keyboard activation also emits trusted click(detail=0). The literal zero-click gate is retained, with separate detail/pointerType records; native behavior is not changed to manufacture a zero.

### Accessible names and contrast

| Surface / controls | Source inventory |
| --- | --- |
| Ribbon buttons/menu items | Existing aria-label/title and text; menus now have explicit role and label. |
| Document-type selector | Existing named combobox/listbox and keyboard selection. |
| Box Font family, Font size, Text color / Outline color, Shape fill | Title-only names; accepted by the brief and listed as titleOnly in runtime evidence. |
| Rich controls | Text or labelled inputs; explicitly named toolbar role added. |
| Symbol / Table | Named dialogs and popup attributes; symbol choices use Unicode names. |
| Theme | Labelled dialog and explicit Close name added. |
| Status | role=status, aria-live=polite, aria-atomic=true; mutation evidence for save, refusal, undo and finished export. |

| Literal text/background pair | Calculated source ratio | Runtime qualification |
| --- | --- | --- |
| Rich controls #edf6ff / #213b4c | 10.71 | Computed styles/states and both themes still checked. |
| Rich panels #eef6fc / #122532 | 14.38 | Same. |
| Symbol legends #b9cfdf / #122532 | 9.77 | Same. |
| Menu #34444f / #ffffff | 10.07 | Ancestor/theme rules may change the effective pair. |
| Primary/export #075f91 / #dff2fb | 5.97 | Same. |
| Status / other theme-dependent text | NOT MEASURED | Phase records foreground, first opaque ancestor, size/weight, ratio and threshold. |

These are calculations on source literals, not browser passes. accessibility[] retains every runtime name, title-only name, unlabeled panel and below-threshold pair. Threshold is 4.5, or 3 for 24 px text / 18.66 px bold. No color/geometry fix was chosen without measured evidence. Scaling retains every clipped/overlapping rectangle, four scroll-corner coordinates and pixel samples, including an editing-toolbar check per viewport.

### Findings for the product owner

| Finding | Evidence / measurement produced | Change |
| --- | --- | --- |
| 100-page parts save | Server p95 3170 ms from P5a-1. Browser save_done has five Done-to-saved intervals; save_escape records cancellation/unchanged revision. New numbers NOT RUN; MMLE fallback distinguished from standalone fixture. | No speed change; successful-save announcement only. |
| Full read after rich command | P2a approximately 1 s. Raw fetch start/end separates precondition reads from post-commit documentation-scene reads under findings.parts_save.richReadAfterSave. | None. |
| Object batch settles around 2200 ms | Five nudge-to-redraw measurements on operations50 in object_batch_operations50. | None. |
| Toolbar overlays top 90 px | Toolbar/surface rectangles and measured vertical overlap in CSS px. | No layout change. |
| Final-table gap types into last cell | Control+End, ArrowDown, typing P5aGap; resulting JSON/caret ancestors recorded, draft cancelled. | None. |
| Search traverses all targets per result page | Carried source finding; not an A2 timing action. No server hook or cache added. | None. |
| Parts contents/group-index rows overflow | Standalone generated PDFs exported via the existing HTTP route; row words/drawings compared with compiled frames and PNGs saved. Fallback pages have separate canvas/PDF row evidence. Their top-level group count differs. | No generator/renderer fix; unavailable original generated browser measurement explicitly fails. |

### TESTS

- Python AST checks passed for the six changed/new Python implementation/test files, through pythonw.exe tools/run_hidden.pyw with hidden redirected children.
- node --check passed for static/documentation_rich_text.js, tests/documentation_editor_scale_probe.js and tests/documentation_scale_probe.test.cjs.
- Four classic inline index.html scripts parsed with vm.Script without execution; the import map is data.
- git diff --check passed. Written files use LF; new index.html lines are ASCII. server.py and its BOM are unchanged.
- No pytest, Node suite, fixture preparation, browser, export or benchmark was run. No runtime pass count, measurement or new actual fixture count is claimed.

### NOT RUN

Run through the existing hidden runner in the supervisor environment:

~~~text
python -m pytest -q tests/test_documentation_scale_harness.py tests/test_documentation_editor_smoke.py tests/test_documentation_benchmark.py
node --test tests/documentation_scale_probe.test.cjs tests/documentation_rich_text.test.cjs tests/documentation_tables.test.cjs tests/documentation_objects.test.cjs tests/documentation_page_setup.test.cjs
python -m pytest -q tests/test_parts_manual_ui_contract.py tests/test_documentation_rich_text.py tests/test_documentation_tables.py tests/test_documentation_objects.py tests/test_documentation_page_setup.py
python tests/smoke_documentation_editor.py --phase P5a
python tests/smoke_documentation_editor.py --phase all
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python -m pytest -q tests
~~~

Set DOC_SMOKE_SLOW=4 in the hidden runner's environment for P5a (PowerShell environment assignment: $env:DOC_SMOKE_SLOW='4'). Artifacts are .runtime/de/p5a-measurements.json, report.json, p5a-*.png and p5a-*.pdf; none was generated here. The all dispatcher writes report-<phase>.json and all-report.json.

Expected duration, not measured: roughly 25-40 minutes on the gate machine, mostly fixture preparation/accepted captures, 20 complete large-document cycles, 20 editor cycles, synchronous page/rail layout, response reads and eight fresh browser contexts. T never scales elapsed samples. The total includes server startup; action waits are bounded by remaining phase time and an unavailable measurement is not retried five times. Verify the 40-minute requirement at factor 4; no deferred speed change was made to meet it.

### DEVIATIONS

- Used the authorized MMLE fallback for both browser types because model-free assemblies cannot enter the workspace. Original benchmark fixtures and their parts PDF evidence remain separate.
- Escape is already Cancel. Changing it would violate the instruction to preserve shortcuts. Escape-to-save therefore fails as unavailable; Done-to-save is explicitly named.
- Trusted keyboard click(detail=0) is counted literally, so the zero-click gate may fail despite no pointer use. Events are not relabelled.
- Runtime-dependent counts, clipping and contrast require the supervisor's environment. Minimal source-backed attributes/keyboard paths were added; no speculative styling or speed fix.
- Earlier phase bodies remain unchanged. Shared harness edits are phase registration, strictly scoped refusal/download classification and P5a-only fixture copying. No baseline or history/index mutation.

### OPEN QUESTIONS

- Should the save budget formally use Done/blur while keeping Escape as Cancel? That diagnostic is already recorded.
- Should the zero-pointer gate permit trusted keyboard click(detail=0), while forbidding pointer-origin clicks and pointerdown/mousedown? Both counts are preserved.
- Review actual fallback counts and the unavailable original group-index browser path; original PDF and fallback canvas evidence are deliberately separate.
- Run and review P5a before P5a-3. Save/read cost, toolbar overlap, final-table gap, search traversal and generator overflow remain findings, not fixes.

## P5a-2 supervisor gate (Claude, 2026-11-13)

### What I ran and what it showed

The phase (`python tests/smoke_documentation_editor.py --phase P5a`) ran twelve times on temporary snapshots and
stores: at debug sizes (parts 20 and 30 pages, operations 36 pages) while the harness was corrected, then at the
full sizes (parts 50 and 100 pages, operations 50 pages). As delivered it did not reach its first measurement.
After the corrections below every stage runs.

At full size the editor meets the budgets for typing, selection and PDF export and misses the two that involve
loading or saving a whole document: open (35 s against 5 s) and save (17 s against 1 s). Nothing was tuned and
no budget is changed: the numbers below are the "before" for the speed round (P5a-3).

Run 12 is the reference: the final code, full size, a machine with the user's other programs idle, every stage
except `memory_cycles`, with the stage `profiles` added. It took 41 minutes and failed only what it must: the
twelve ribbon and toolbar cut-off checks (findings 2 and 3) and the two checks that mark a run with a stage or
time option (`p5a_all_stages`, `p5a_phase_time_gate`).

The machine matters. Run 9 measured the same stages while other programs used most of the processor and got
about twice these times (open 100 pages 65.9 s, save 30.2 s, PDF 43.9 s, which misses its budget); it was
stopped in `memory_cycles` when free memory fell to 513 MB (the browser held 1.7 GB by then; finding 1). Run
10 was spoiled by the same load. `memory_cycles` therefore has a debug-size result only (run 11, on the final
code). The whole phase in one run with twenty cycles is owed at the P5a-3 gate, once finding 1 is closed.

### Measurements (full size, run 12, wait factor 4, 1720 x 1080, device scale 1)

Fixtures as prepared: MMLE-50D parts manual 18 pages, 86 list rows, 12 figures; parts 50: 50 pages, 598 rows,
44 figures, 24 objects; parts 100: 100 pages, 1398 rows, 94 figures, 40 objects; operations 50: 50 pages, 160
blocks, 16 figures, 20 objects. Five samples per action (three per PDF, 250 keys per typing row); median / p95.

| Action | Measured | Budget (plan) |
| --- | --- | --- |
| Open, MMLE-50D parts manual (18 pages) | 6.5 / 6.6 s | - |
| Open, parts manual 50 pages | 16.9 / 17.4 s | - |
| Open, parts manual 100 pages | 35.5 / 37.7 s | 5 s: missed |
| Open, operations manual 50 pages | 8.1 / 8.8 s | - |
| Page change, 100-page parts manual | 5.1 / 6.0 s | - |
| Selection of an object | 37 / 58 ms | 150 ms: met |
| Typing in a text box | 14 / 22 ms | 100 ms: met |
| Typing in a table cell | 14 / 22 ms | 100 ms: met |
| Escape (cancel an edit), 100 pages | 2.4 / 2.7 s | - |
| Save a text edit with Done, 100 pages | 17.4 / 18.2 s | 1 s: missed |
| Undo, 100 pages | 15.9 / 17.1 s | - |
| Redo, 100 pages | 16.8 / 17.7 s | - |
| Refresh, 100 pages | 13.5 / 13.9 s | - |
| Object nudge, operations manual 50 pages | 4.5 / 4.6 s | - |
| PDF, parts manual 100 pages | 25.0 / 26.2 s | 30 s: met |
| PDF, operations manual 50 pages | 3.0 / 19.0 s | 30 s: met (first export 19.0 s, later 2.6 and 3.0 s) |

"Open" is the phase's action: the workspace opens (it loads the document) and the phase then presses Refresh
(a second load); both loads are in the number. The wait factor 4 only lengthens the harness's own waits; it is
not in the measured intervals.

Editor cycles at full size: 20 cycles, one editor alive at a time, the same document and window listeners
before and after. The keyboard-only sequence and the four announcements (save, refusal, undo, export) pass at
full size.

### Where the time goes

Browser, one open of the 100-page parts manual (CPU profile, 48.7 s under the profiler):
`_documentationRenderPageRail` 23.9 s, all of it in drawing every page once for its thumbnail
(`_documentationBuildPageThumbnail` -> `_documentationRenderPublicationPage` ->
`_documentationFitPublicationText` 21.5 s, of which 17.0 s is `getBoundingClientRect` itself: the fit loop
writes a font size and reads a box in turn, so every read is a forced layout); 9.7 s idle, waiting for the
server; `animate`, the 3D viewer's frame loop, 7.0 s behind the workspace. One page change (5.4 s):
`_documentationActivatePage` 4.4 s, of which 4.1 s is building the page rail again. A save (36.2 s under the
profiler): 26.8 s idle, waiting for the server, and 3.8 s in the rail. An undo (32.3 s): 22.5 s idle, 4.5 s in
the rail. A nudge on the operations manual (11.3 s): 8.7 s idle.

Requests, without a profiler. Save with Done on the 100-page parts manual (17.6 s): `GET documentation-scene`
3.3 s (the read before the write), `POST documentation-scene/commands` 6.9 s, `GET documentation-scene` 3.4 s,
then about 4 s of drawing. Undo (15.4 s): `POST .../undo` 7.7 s, `GET` 3.4 s. Redo (16.7 s): `POST .../redo`
7.9 s, `GET` 3.4 s. Refresh (13.3 s): `GET documentation-scene` 3.6 s, then about 9 s of drawing. Nudge
(4.3 s): `POST /api/documentation/<type>/<assembly>/objects` 2.7 s, `GET` 1.3 s. The first `GET
documentation-scene` after a document switch takes 8.6 s, the next 4.0 s. PDF of the 100-page parts manual
(25.0 s): `GET /api/parts-manual/<assembly>/document` 3.8 s, then `POST .../pdf` 21.2 s. Operations manual, 50
pages: `GET` 1.4 s and `POST .../pdf` 1.2 s once the first export (19.0 s) has run.

The phase's 100-page parts fixture is heavier than the generated one of the P5a-1 benchmark (1398 list rows
and 94 real figures, against 20 rows per list page and synthetic captures): the benchmark measured open 1.6 s,
save 3.0 s and PDF 16.7 s in the server on its 100 pages; the same server work is about twice that here.

Server, one route at a time under cProfile (about twice the unprofiled time; on Python 3.14 the profiler also
sees the other threads of the process, so the counts and the shares are the evidence):

| Route (100-page parts manual unless said) | Profiled | Calls | `copy.deepcopy` | Repeated work |
| --- | --- | --- | --- | --- |
| `GET documentation-scene` | 7.0 s | 15.4 M | 3.9 M calls, 4.0 s | `build_manual_document` 2, `compile_identities` 7, `text_targets` 6, `_load_descriptor` 94 |
| `POST documentation-scene/commands` (text save) | 15.4 s | 33.0 M | 8.9 M calls, 9.2 s | `documentation.read` 3 (4.9 s), `compile_identities` 17, `text_targets` 12, `catalog_from` 10 |
| `POST documentation-scene/undo` | 17.9 s | 36.5 M | 10.0 M calls, 10.1 s | `documentation.read` 4 (4.5 s), `compile_identities` 20, `text_targets` 12, `catalog_from` 12 |
| `POST .../objects` (nudge, operations 50) | 7.1 s | 13.7 M | 4.5 M calls, 5.1 s | `document_snapshot` runs the whole scene read (3.3 s), `read` 4, `compile_identities` 18, `text_targets` 11 |
| `GET documentation-scene` (operations 50) | 3.4 s | 6.5 M | 2.0 M calls, 2.3 s | `build_operations_manual_document` 2, `compile_identities` 7, `text_targets` 6 |

More than half of every write is `copy.deepcopy`. One text save hashes 251540 values (`commands.digest`, a
sha256 over canonical JSON) and makes 220762 generated ids for targets it has already compiled. Redo was not
profiled; it runs the same `move_history` as undo.

### What I changed in the harness

- The page never calls the driver. As delivered, the probe called a binding the driver had exposed while the
  driver was itself waiting in an evaluation: Playwright's sync API cannot serve that and the phase hung at its
  first trusted key. Now the observer is armed in the page (`P5aProbe.arm`), the driver sends the key or the
  press, and a second call collects (`P5aProbe.collect`, `P5aProbe.typed`).
- Every evaluation is bounded, and the measurements file is written as the phase goes (a progress marker and
  the failed checks so far), so a stopped run leaves what it measured.
- The parts fixture: the chain of generated service groups hangs under the real leaf group with the most
  parts; the authored text box and table are placed on a parts-list page in the middle of the publication
  (`typingPageId`); objects are named `document-object-p5a-<page>-<0 text|1 table|2 image|3 shape>`.
- Selection: the phase clears the selection by activating the page again (Escape on a parts-manual page goes
  to the overview page; finding 4), and the observer judges the press by its position and counts the object's
  own `.documentation-object-handle`.
- Keyboard save is leaving the editor with Tab (focus out commits; Escape is Cancel and stays Cancel); bold is
  read from the drawn `<strong>`. The zero-pointer gate counts `pointerdown` and `mousedown` (0 required) and
  allows the trusted `click` with `detail` 0 that the browser sends for Enter on a button. These settle the
  two open questions of the P5a-2 report above.
- Editor cycles reuse fields on debug fixtures that have fewer than twenty (`editor_cycle_fields`).
- Contrast pairs that come from styles older than this build are recorded
  (`findings.contrast_older_styles`), not failed (finding 6).
- The census lists the live canvas contexts by where they were created.
- The picture check lists the points inside the header wordmark box (20, 8, 140, 40 pt) as a finding
  (finding 5); every other point must still match.
- Options for runs that are not gate runs: `DOC_SMOKE_P5A_PAGES=a,b,c` (fixture sizes; adds the failing
  check `p5a_full_scale_fixtures`), `DOC_SMOKE_P5A_ONLY=stage,...` (adds the failing check `p5a_all_stages`),
  `DOC_SMOKE_P5A_CYCLES` (20 is the gate; `p5a_memory_cycle_count`), `DOC_SMOKE_P5A_MINUTES` (40 is the
  gate; `p5a_phase_time_gate`), `DOC_SMOKE_P5A_GENERATED=1`, `DOC_SMOKE_PROFILE=1` (browser CPU profiles in
  the stage `profiles`, and a profile of a documentation route on request, printed to the server log). A run
  with a size, stage, cycle or time option fails by construction and can never be read as a gate pass.

### What I changed in the product

`static/documentation_rich_text.js`: Escape in the Symbol or Table panel. Before this slice Escape closed the
panel and put the focus in the text. The delivered change put it on the panel's button in every case. A
toolbar button pressed with the pointer leaves the caret in the text (its `pointerdown` is prevented), so a
pointer user who closed the panel with Escape lost the caret. Now the focus goes back to where it was when the
panel was opened: into the text when it was opened from there, to the button when it was opened from the
keyboard (`notePanelOrigin`, `leavePanel`). The phase checks both (`*_pointer_focus`, `*_focus`).

My first version of this judged the focus at the moment of Escape. The Table panel takes the focus when it
opens (its Rows field), so that version left a pointer user on the Table button. Smoke phase P3b found it: it
closes the Table panel with Escape and pastes into the text next; the paste went to the button, the refusal
"Tables cannot be pasted here" never appeared and the phase stopped after 131 checks. The rule above is the
correction; P3b passes with it (table below).

`static/documentation_conflicts.js` (`?v=20261113-p5a-2`): the open review pane's 5 s change check compares
the server with what the page shows, not only with the review's own copy. Smoke phase P4b found the defect on
the busy machine: Sage applied a page setup, the pane saw the new revision and reloaded the page; Sage's undo
landed while that reload was running; the review loaded right after the reload was already at the undo's
revision, so the check found nothing new and the page kept showing Letter (`p4b_sage_undo_redraw`, the only
failed check of 198). The code is older than this slice (P1c-3, P2a-1); a slow reload (a busy machine, a large
document) makes the window wide, and Sage often makes several changes in a row. Now the check also reloads
when the scene revision on the server differs from the one in the page's payload, once per server revision
(`caughtUp`), so a page that cannot catch up is never reloaded in a loop. Two Node tests drive the real
controller through both cases; both fail on the committed file.

The rest of the delivered product change was read line by line and kept: menu keyboard navigation
(`_documentationMenuKeyboard`, `_documentationInvoke`), the theme dialog's role, focus trap and Escape, the
status line as a live region with "Text saved." after a rich-text save (`options.onSaved`), Enter on a focused
ribbon button no longer opening the selected text box, and Page Setup returning its promise.

### Findings in the product

1. Canvas contexts stay alive. Every opening of the Documentation workspace mounts the 3D scene again
   (`_renderDocumentationWorkflowTab` -> `_initAssembly3DScene`) and the previous mount is not released: one
   WebGL renderer of the viewer, the 160 x 160 WebGL renderer and three 64 x 64 canvases of
   `createOrientationGizmo`, and one canvas of `_makeCadViewportBackgroundTexture` remain. Debug size: 25 live
   contexts before three open/close cycles, 61 after; 187 before twenty, 427 after
   (`p5a_viewer_contexts_after_cycles` fails). Heap growth over twenty cycles at debug size: 54.7 MB (limit
   100 MB). At full size, after about forty openings, the browser held 1.7 GB and an open took minutes.
2. The ribbon is cut at 1366 x 768: "Export ... as PDF" ends at x 1382 and Preview starts at x 1388 while the
   ribbon is clipped at x 1320. At 1720 x 1080 with an object selected or a text edited, Preview and "Export
   an editable DOCX copy" are pushed out to x 1674 - 1770 (`p5a_scale_*_controls`,
   `p5a_scale_*_editing_controls` fail at every device scale).
3. The editing toolbar is cut at 1366 px: it wraps to four rows and `.documentation-rich-controls`
   (`max-height: 106px; overflow: auto`) shows three and a half; the link field, Link and Unlink are in the
   cut row.
4. Escape on a parts-manual page goes up to the overview page even with an authored object selected (the
   older capture-phase key handler runs first).
5. The header wordmark is drawn heavier and about 12 pt further left on the page than in the PDF (2 of 688
   sample points at 200 %, 1720 x 1080). Recorded; not failed.
6. Contrast below 4.5:1 in two older styles: the Publish button (white on its blue, 4.14:1) and the 8 px
   menu headings of the light theme (3.94:1). Every pair this build added passes in both themes.
7. Keyboard reach is long at full size: 80 Tab presses from the top of the page to Insert Text, 48 to 100
   from the ribbon to the page (every item of the page rail is a tab stop). The keyboard-only sequence itself
   passes: insert a text box, type, bold, save, move, delete, undo, redo, Page Setup to Letter and back, with
   no pointer event.
8. The toolbar covers the top 32 px of the page at 1720 x 1080; text typed after a final table goes into the
   last cell (there is no paragraph after the table to put the caret in). Both carried from earlier rounds.
9. The contents page of a parts manual with many groups draws below its frame in the PDF: on the 50-page and
   the 100-page fixture (44 and 94 contents rows) one row (6 words) ends at 606 pt; the frame ends at 564 pt.
   Carried from P5a-1 (23 and 48 groups). The phase does not yet read the contents rows on the page (0 rows
   read), so the page side of this finding is not measured.
10. Every API request writes one telemetry row through a new SQLite connection and a commit, on the server's
    event loop (`_telemetry_endpoint_timing` -> `record_endpoint_event`). In a route profile on the quiet
    machine 14 rows took 0.67 s (48 ms each); under load 34 rows took 8.4 s. Outside this build; recorded.
11. The status line announces the user's own undo and redo as "Sage: Undid the document change." and "Sage:
    Redid the document change." (`_documentationMoveHistory` puts the assistant's name before every history
    message). Older wording; recorded.

Findings 1 to 4 and the speed are the P5a-3 round. Findings 5 to 11 are for the product owner.

### Gates

Everything below ran on the final code of this slice except the three smoke phases marked "before". The
suites, the baselines, run 12 and the smoke phases without a mark ran on a quiet machine.

| Gate | Result |
| --- | --- |
| Node suites (`node --test`) | 483 passed: conflicts 20, objects 168, page setup 2, publication 2, rich text 258, scale probe 2, search 20, tables 11; inline scripts 4/4; borrow callouts 5/5 |
| Complete documentation suites | 2050 passed, 1 failed: `test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed` (the stored hash of SRC-IP-MMLE-REGISTRY; it has failed in every gate since the baseline before P0). P5a-1: 2044 passed and the same failure |
| Tests that read a changed product file (89 selected tests and 5 files) | 151 passed, 11 failed: 7 of the known wide list and 4 in `tests/test_training_process_map.py` |
| Wide suite, four parts | 3855 passed, 68 skipped, 179 failed or errored: the 179 known since P3a-1, none new, none gone |
| Baselines | `tools/documentation_baseline.py --check` exit 0; `--local --check` exit 0 ("Documentation baseline matches; reopened stores were unchanged.") |
| Smoke P1a | 27/27 |
| Smoke P1b | 46/46 |
| Smoke P1c | 35/35 |
| Smoke P2a | 23/23 |
| Smoke P2b | 36/36 |
| Smoke P3a | 194/194 (before) |
| Smoke P3b | 169/169 (before) |
| Smoke P4a | 475/475 (before) |
| Smoke P4b | 198/198; 197/198 before the review-pane fix (`p4b_sage_undo_redraw`) |
| Smoke P5a, full size without `memory_cycles` (run 12) | 187/201: the twelve cut-off checks (findings 2 and 3) and the two by-construction checks fail |
| Smoke P5a, debug size (run 11: keyboard, announcements and colours, scaling, overflow) | 161/177: the same twelve, three by-construction checks, and `p5a_announcement_export`, which needs the export stages this run left out (it passes in run 12) |

"Before": P3a, P3b and P4a ran on the code before the review-pane fix (`static/documentation_conflicts.js`) and
were not run again (they took 50, 48 and 100 minutes on the busy machine). None of them opens the review pane:
only P1c and P4b do, both ran on the fixed code, and the fix changes nothing while the pane is closed (the
check returns at its first line). P3b and P4a ran on the final `static/documentation_rich_text.js`.

The 4 failures in `tests/test_training_process_map.py` are not from this build: the file is in no gate list of
this build, the tests fail on pins of the training process map and on its fixture data, and this slice's diff
of `static/index.html` has no line of that code. Recorded for the product owner.

Not run in this slice: the stage `memory_cycles` at full size (above), and the desktop smoke
(`tests/smoke_documentation_editor_desktop.cjs`), which belongs to P5b.

### Left for the P5a-3 gate

- The whole phase at full size in one run with twenty memory cycles and the 40-minute limit (run 12 took 41
  minutes without the memory stage and with the profile stage, which a gate run does not have).
- The nine smoke phases, the complete suites, the wide suite and the baselines on the P5a-3 code.

## P5a-3

### CHANGED

This is a source/static-check handoff, not an after-performance result. The supervisor's P5a-2 numbers above remain the measured before values. No schema, tool inventory, stored-format, renderer-version, baseline or export-drawing change was made.

| Item | Functions/files changed, and expected saving | Left / verification |
| --- | --- | --- |
| A1: page rail | In static/index.html, _documentationRenderPageRail reconciles existing named, tabbable buttons; _documentationSelectRailPage changes the active mark without rebuilding the rail. _documentationQueueRailThumbnails uses IntersectionObserver (300 px near-view margin) and one page per idle callback. _documentationBuildPageThumbnail renders in a separate inert, hidden surface, never on the live page. | No eager offscreen population. Editing, crop, busy state and drags defer work; completion resumes it. Expected to remove the all-page draw from opening and both all-page draws from activation (23.9 s and 4.1 s respectively in the supplied profiles). Browser timings remain unmeasured here. |
| A2: fitting | _documentationFitPublicationText sets row geometry, collects every computed style/box and canvas text measure, then writes every font size/weight/line height. _documentationScalePageRailThumbnails likewise reads widths before writing transforms. | Same formula, fonts and fixed column/frame widths. Expected to remove per-cell forced layouts (17 s of the supplied open profile); the new Node old/new comparison checks identical fitted styles. |
| A3: covered viewer | _initAssembly3DScene.animate returns before motion, label, gizmo and scene rendering when _assemblyMountIsCovered says the mount is detached, hidden, on a text page, or covered by its ready accepted capture. Live editing, generation and capture takeover retain their render path. | One current RAF checks visibility; visible Assembly animation is unchanged. Expected to remove the covered viewer's render work (7 s of the supplied open profile). |
| A4: reads | request_work.py bounds pure catalogue/inventory/scene-read reuse to the request. identity.catalog_from and refresh.inventory reuse completed identities. provenance.project_document builds effective text targets once and omits authored fields from its otherwise-needed source-only scan. _documentation_editor_read omits its discarded duplicate hash map. The four scene-read paths consume their privately owned compiler/artifact results. | Baseline and scene-applied compilations remain distinct. Exact old/new canonical response tests cover generated parts/operations with and without authored objects, all four MMLE types, and rich-text flag on/off. They are written, not run. |
| A5: writes/history/object batches | Repository apply_command/apply_batch/undo_change/move_history share request work. _saved_result runs the existing read projection on the committed candidate instead of reopening/parsing it; move_history passes its locked pre-image into undo_change. The host's _compiled_snapshot/object_snapshot no longer calls a whole scene route or builds a discarded ribbon/text read for an object batch. Command/history pre-image builders request editor_read=False. | One disk JSON projection and reuse of identical inventories/catalogues; distinct generated/current/candidate values still have distinct work. The atomic writer, process mutex, validation, hashes, receipts and rollback-byte reads are retained. Counters and exact store/answer comparisons cover commands, undo, redo, object batches and replay. |
| A6: post-command read | Audited _documentationReadAfterMutation, rich save, table remount and _documentationObjectBatch. The existing helper already uses a complete response when it contains richTextFields. | No GET removed: normal command/history answers lack the fresh rich-field read, and table/object answers are receipts/bindings rather than the full document. Reusing them would leave field hashes stale. APIs were not expanded. |
| A7: PDF route | The four document GETs and PDF routes (including fillable specification) skip a discarded editor read and use the same request-local derivations/owned artifact attachment. | No PDF/DOCX builder changed. The pre-export GET and POST still compile independently for freshness; figure descriptors/readiness remain checked. The existing operations export cache builds PDF and DOCX on its first miss, explaining work absent on later hits; no second cache added. Profiling/byte proof is NOT RUN below. |
| A8: bundle / word check | documentation_rich_text.js starts the pinned Tiptap import only on first ready access, with one shared success/failure promise. The P4b word reader caches styles, clipping ancestors and block identities, reuses one Range, and reads fully visible ASCII runs together. | Clipped and non-ASCII text retains the old per-code-point visibility algorithm. Same pages, words, NFKC, exceptions, accepted-capture waits and comparisons. New Node tests compare the old/new reader on wrapping, inline joins, case, clips, Unicode and excluded overlays. |
| B1: mount leak | _disposeAssembly3DMount is the common remount/tab-disposal owner: token invalidation, RAF/camera-RAF cancellation, resize observer and delayed refit cleanup, orbit-listener abort, technical/display pass cleanup, gizmo/renderer context loss, background texture disposal, and theme-registry removal. cad_viewport.js also releases the gizmo context and axes' label references. | Cached GLTF geometry/materials remain owned by their cache. The old animation callback also checks its mount token before scheduling another frame. Full-size context/heap measurements must prove the leak closed. |
| B2: ribbon | Existing More proxies now include Figure, Annotate, Object and Values history; marks/disabled state refresh when More opens. Container queries collapse Content/Edit and these groups at <=1450 px; at <=1660 px an Object group sends Figure/Annotate to More. | Same controls and handlers, no new menu. Verify all three selection/edit states at 1366 and 1720 CSS px. A harness that directly locates a now-collapsed source button must use its existing More action; the supervisor-owned scale harness is otherwise untouched. |
| B3: toolbar | documentation_rich_text.css removes the 106 px height cap and internal clipping from .documentation-rich-controls. | All wrapped rows can show; the existing attached strip and page overlap remain. |
| B4: Escape | The older capture-phase onKeyDown clears authored selection before its overview navigation branch; it defers crop/editor Escape to their owners. | Added only the requested trusted-key check to documentation_editor_scale_smoke.py: selected object, page before/after, selection cleared. With no selection, overview navigation is unchanged. |

Thumbnail validity: the key contains the whole compiled page, API/document identity, theme/page masters/paper, product/publication labels, specification slots/sheet/release gate, and that page's validated rich text/style/error fields. It includes the active live camera pose and callout routes when the live view is used. Stored picture status, URL, sha and figure revision are in the page. Only document-wide documentRevision and request bindings are excluded: unchanged capture bytes/figure identity and unchanged drawn text do not need a new picture after an unrelated edit. Captures, page edits, style changes, paper changes and live-pose invalidation change the key. Closing the workspace releases the observer and pending work.

Copy/authority audit:

- compile_identities/bind_document still copy at the source-input boundary. The four builders receive that private document before owned=True provenance/review projection. Public project_document/project_slots/project_review still copy by default.
- Server build/command/history/PDF paths pass only freshly compiled documents to owned=True artifact attachment. Public artifact helpers still copy by default. Work-instruction with_figure_revisions preserves its public default copy and the separate revision-hash copy. Nothing mutates a shared compiled-document cache; none was added.
- Request reuse has a 32-entry cap and ends in finally. Keys cover complete input values; scene reads also re-stat the file (device/inode/size/mtime_ns/ctime_ns) before reuse. Atomic replacement invalidates a pre-image read, including a replacement by another process. Cached results are private and copied on return. Changed inputs miss; invalid non-JSON inputs reach the original validators.
- The old implementation is loaded only by tests from commit 4669cd06834010b945f83dea84cac24795fab985 with hidden read-only git show. No old server startup, checkout, environment/session load or real store is used. Tests compare canonical response bytes and actual stored bytes; mutation-isolation checks remain explicit.

Pins: test_assembly_display_styles now follows the shared disposer while retaining the rendering-priority assertions. The refresh capture spy forwards the new private ownership keyword. cad_viewport.test.cjs retains its original resource-disposal count and also checks context loss/empty axes. The existing lightweight-rail pin remains valid. Static URLs changed to ?v=20261114-p5a-3 for documentation_rich_text.js, documentation_rich_text.css and cad_viewport.js. Baselines, exporter algorithms, the scale fixtures/probes and the nine other smoke phase bodies are untouched.

### TESTS

Static checks passed: in-memory Python compilation of all 19 changed/new Python files; node --check for the four changed/new standalone JavaScript test/product files; parsing all four classic inline scripts in index.html; git diff --check. All 26 changed/new files use LF, server.py retains its UTF-8 BOM, and every added server.py/index.html line is ASCII. No pytest, Node behavioral suite, browser, export, benchmark or profiler was run in this sandbox.

### NOT RUN

Use the supervisor's Python environment and hidden launcher (pythonw tools/run_hidden.pyw <python-or-node> ... on Windows). These commands are the payloads to that launcher:

~~~text
python -m pytest -q tests/test_documentation_performance.py tests/test_documentation_recovery.py tests/test_documentation_server_reads.py tests/test_documentation_transactions.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_provenance.py tests/test_documentation_objects.py tests/test_documentation_rich_text.py tests/test_parts_manual_ui_contract.py tests/test_assembly_display_styles.py
node --test tests/documentation_performance.test.cjs tests/cad_viewport.test.cjs tests/documentation_rich_text.test.cjs tests/documentation_tables.test.cjs tests/documentation_conflicts.test.cjs tests/documentation_objects.test.cjs tests/documentation_page_setup.test.cjs tests/documentation_publication.test.cjs tests/documentation_search.test.cjs tests/documentation_scale_probe.test.cjs
python -m pytest -q tests -k "documentation or parts_manual or operations_manual or work_instruction or specification_sheet"
python -m pytest -q tests
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tools/benchmark_documentation_editor.py --pages 1 50 100 --runs 5 --out .runtime/de/p5a-3-server.json
python tests/smoke_documentation_editor.py --phase P5a
python tests/smoke_documentation_editor.py --phase all
~~~

For the P5a gate set DOC_SMOKE_SLOW=4, leave the rich-text flag under the harness's control, and unset DOC_SMOKE_P5A_PAGES / ONLY / CYCLES / MINUTES / GENERATED and DOC_SMOKE_PROFILE. This keeps full sizes, all stages, twenty memory cycles and the forty-minute gate. Repeat the supervisor's profile run separately with DOC_SMOKE_PROFILE=1; it is not the timing gate. Existing known suite failures remain for the supervisor to classify against the gate above.

To profile the benchmark worker itself (not its waiting parent), run each command through the hidden launcher. Fixtures live only in TemporaryDirectory; profiles go to the evidence folder:

~~~text
python -c "import os,tempfile,cProfile; from pathlib import Path; os.environ['INSPECTORPRO_DOCUMENTATION_RICH_TEXT']='1'; from tools.documentation_benchmark_support import prepare; from tools.benchmark_documentation_editor import sample; d=tempfile.TemporaryDirectory(prefix='p5a3-'); root=Path(d.name); prepare(root,'parts',100); Path('.runtime/de').mkdir(parents=True,exist_ok=True); p=cProfile.Profile(); p.runcall(sample,root); p.dump_stats('.runtime/de/p5a-3-parts.prof'); d.cleanup()"
python -c "import os,tempfile,cProfile; from pathlib import Path; os.environ['INSPECTORPRO_DOCUMENTATION_RICH_TEXT']='1'; from tools.documentation_benchmark_support import prepare; from tools.benchmark_documentation_editor import sample; d=tempfile.TemporaryDirectory(prefix='p5a3-'); root=Path(d.name); prepare(root,'operations',50); Path('.runtime/de').mkdir(parents=True,exist_ok=True); p=cProfile.Profile(); p.runcall(sample,root); p.dump_stats('.runtime/de/p5a-3-operations.prof'); d.cleanup()"
~~~

### DEVIATIONS

- No after numbers or runtime pass claims. Profiling, memory, geometry, clipping and byte-equivalence execution need the supervisor's environment.
- A4/A5 remove repeated derivations of identical inputs, not every separate compilation: generated identity baselines, scene-applied output and a changed candidate still need their own compiler state. Per-state reuse and disk-read counters are covered; the new whole-route counts must be measured. Source-isolation copies and receipt/migration defenses were deliberately retained.
- A6 retains reads whose response is incomplete. A7 retains the independent pre-export GET/POST and the existing export cache, rather than introducing cross-request compiler/capture authority.
- No changes to the product-owner findings in C, the baseline files, benchmark fixtures, phase budgets or phase instrumentation. The only scale-harness edit is B4; the P4b word-reader optimization changes no assertion.

### OPEN QUESTIONS

- Do the full-size context census and forced-GC measurement now return to the before-cycle counts, and does the complete phase fit forty minutes? No full-size memory result exists yet.
- What are the new open/save/undo/nudge/PDF medians and p95s, and which repeated compiler/copy costs remain dominant? The supplied budgets are unchanged.
- Do the responsive More placements pass all viewport/selection states, and do all old/new response/store comparisons plus both unchanged baselines pass? These are gates, not assumed results.

## P5a-3 supervisor gate (Claude, 2026-11-14)

### What I ran and what it showed

The delivered change (26 files) was read as a diff and then run: the Node suites, the documentation suites,
the server benchmark, the phase at full size, the nine smoke phases, the wide suite and both baseline checks.
Codex ran static checks only, as agreed.

The speed work holds. On the 100-page parts manual an open went from 35.5 s to 10.1 s, a save from 17.4 s to
7.1 s, a page change from 5.1 s to 0.84 s (table below). Two budgets are still missed: open 100 pages (5 s)
and save (1 s). No budget is changed; both stay written findings (below).

Four defects in the delivered change were found by running it and are corrected here: the viewer's WebGL
contexts were still not released (finding 1 of the P5a-2 gate), Escape with an object selected left the focus
on the unselected object, the new Escape rule also took Escape away from an open menu, and the ribbon was
still cut with an object selected at 1720 x 1080 (finding 2). One shortcut in the server was corrected by
reading. Each is described under "What I changed in the product".

The phase's complete runs in this gate (full size, wait factor 4, 1720 x 1080, twenty memory cycles):

| Run | Code | Machine | Result |
| --- | --- | --- | --- |
| 13 | As delivered, with correction 1 below (correction 2 went in while it ran) | quiet | 191/201 in 38 min: 143 live canvas contexts after twenty cycles (63 before), the menu focus check, and the text measurements that could not run after it |
| 14 | Corrections 1 to 4 | quiet | 201/201 in 27 min: the first complete pass of the phase |
| 15 | Final (corrections 1 to 6) | busy | 196/198 in 43.5 min: the 40-minute limit (2595 s), and the last stage, which the limit cut off |

Run 15 is the final code on a machine I could not make quiet: at each of four readings between 06:20 and
10:00 the user's file-sync service was using between two thirds of a processor core and nearly two cores,
and memory was paging (1151 pages a second when measured). Every measured action took about 1.7 times as
long as in run 14, the server's own work included (PDF of 100 pages 33.4 s against 19.1 s; that code is the
same in both runs). The stage the limit cut off (`overflow_findings`) was
then run alone at full size on the final code: 12/13, the one failure being `p5a_all_stages`, which marks a
run of chosen stages. So every check of the phase has passed on the final code except the limit itself.
Still owed: one complete run of the final code inside the 40 minutes on a quiet machine. It is the first
step of the P5b gate.

### Measurements (full size, wait factor 4, 1720 x 1080, device scale 1)

The fixtures are those of the P5a-2 gate. Five samples per action (three per PDF, 250 keys per typing row);
median / p95. "Before" is run 12 of the P5a-2 gate.

| Action | Before (run 12, quiet) | After (run 14, quiet) | Final code (run 15, busy) | Budget (plan) |
| --- | --- | --- | --- | --- |
| Open, MMLE-50D parts manual (18 pages) | 6.5 / 6.6 s | 4.5 / 5.2 s | 6.3 / 10.7 s | - |
| Open, parts manual 50 pages | 16.9 / 17.4 s | 6.8 / 7.1 s | 11.0 / 12.9 s | - |
| Open, parts manual 100 pages | 35.5 / 37.7 s | 10.1 / 11.1 s | 19.2 / 21.6 s | 5 s: missed |
| Open, operations manual 50 pages | 8.1 / 8.8 s | 4.7 / 6.1 s | 6.9 / 9.8 s | - |
| Page change, 100-page parts manual | 5.1 / 6.0 s | 0.84 / 0.86 s | 0.93 / 0.98 s | - |
| Selection of an object | 37 / 58 ms | 16 / 29 ms | 39 / 46 ms | 150 ms: met |
| Typing in a text box | 14 / 22 ms | 14 / 17 ms | 17 / 35 ms | 100 ms: met |
| Typing in a table cell | 14 / 22 ms | 14 / 18 ms | 20 / 31 ms | 100 ms: met |
| Escape (cancel an edit), 100 pages | 2.4 / 2.7 s | 86 / 139 ms | 170 / 341 ms | - |
| Save a text edit with Done, 100 pages | 17.4 / 18.2 s | 7.1 / 7.4 s | 13.0 / 16.0 s | 1 s: missed |
| Undo, 100 pages | 15.9 / 17.1 s | 5.6 / 6.3 s | 12.3 / 13.7 s | - |
| Redo, 100 pages | 16.8 / 17.7 s | 5.9 / 6.4 s | 10.3 / 11.0 s | - |
| Refresh, 100 pages | 13.5 / 13.9 s | 3.0 / 3.2 s | 5.5 / 6.2 s | - |
| Object nudge, operations manual 50 pages | 4.5 / 4.6 s | 2.1 / 2.5 s | 4.2 / 4.3 s | - |
| PDF, parts manual 100 pages | 25.0 / 26.2 s | 19.1 / 20.6 s | 33.4 / 37.4 s | 30 s: met on the quiet machine, missed on the busy one |
| PDF, operations manual 50 pages | 3.0 / 19.0 s | 1.3 / 15.9 s | 2.8 / 27.6 s | 30 s: met (the first export is the slow one) |

Between run 14 and run 15 the product changed in one place: the ribbon fit (corrections 5 and 6), which runs
in every ribbon render and so in every selection. The scaling stage now times it: 1.5 to 1.9 ms per pass at
1720 x 1080 with a text object selected (two folds), 0.06 ms at 1366 x 768 (none), on the busy machine.

Memory, twenty open/close cycles of the Documentation workspace at full size: 9 live canvas contexts before
and 9 after in run 14, 8 and 8 in run 15 (run 13: 63 before, 143 after). Retained heap growth 2.3 MB and
2.2 MB (limit 100 MB). Editor cycles: twenty, one editor alive at a time, the same document and window
listeners before and after.

Server benchmark (`python tools/benchmark_documentation_editor.py --pages 1 50 100 --runs 5`, generated
fixtures, median / p95), to read against the P5a-1 table above:

| Document | Pages | Open | Save | Undo | Reload | PDF | Peak memory |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Operations manual | 5 | 0.11 / 0.11 s | 0.03 / 0.03 s | 0.03 / 0.03 s | 0.02 / 0.02 s | 0.49 / 0.57 s | 117 MiB |
| Operations manual | 50 | 0.27 / 0.29 s | 0.23 / 0.23 s | 0.24 / 0.33 s | 0.17 / 0.19 s | 14.9 / 16.2 s | 129 MiB |
| Operations manual | 99 | 0.43 / 0.45 s | 0.44 / 0.45 s | 0.47 / 0.47 s | 0.33 / 0.34 s | 31.3 / 32.4 s | 140 MiB |
| Parts manual | 6 | 0.04 / 0.06 s | 0.05 / 0.06 s | 0.04 / 0.05 s | 0.03 / 0.04 s | 0.70 / 0.91 s | 103 MiB |
| Parts manual | 50 | 0.60 / 0.75 s | 0.77 / 0.80 s | 0.78 / 0.81 s | 0.64 / 0.66 s | 9.8 / 10.4 s | 161 MiB |
| Parts manual | 100 | 1.43 / 1.47 s | 1.70 / 1.81 s | 1.80 / 2.00 s | 1.42 / 1.57 s | 22.6 / 23.3 s | 218 MiB |

A save on the 50-page parts manual now meets the 1 s budget (0.80 s at p95; P5a-1: 1.45 s). On 100 pages it
is 1.81 s (P5a-1: 3.17 s): still missed. Undo on 100 pages went from 4.19 s to 2.00 s.

The PDF column is slower than in the P5a-1 table, and the operations manual of 99 pages is over its 30 s
budget in this run (32.4 s at p95; P5a-1: 23.8 s). That is the machine, not this slice. The slice does not
touch the PDF code, and the commit before it (4669cd0, exported to a scratch folder) was run alternately with
the new code on 50 pages in the same hour: operations PDF 14.8 and 15.4 s on the old code, 14.8 and 15.1 s
on the new (P5a-1 measured 11.3 s). The same alternation shows the gain of this slice by itself: a save on
the 50-page parts manual 1.85 and 1.68 s on the old code, 0.81 and 1.02 s on the new; undo 2.34 and 2.44 s
against 0.82 and 1.03 s. (The last new-code run overlapped a test run of mine.) As P5a-1 already found, the
PDF budget holds on a quiet machine only.

### Budgets still missed (written findings; no budget is changed)

1. Open, 100-page parts manual: 10.1 s against 5 s (before: 35.5 s). The phase's "open" is two loads (the
   workspace opens and the phase presses Refresh). The server's share is about 1.5 s a load (benchmark); the
   rest is the browser drawing the page, the rail's 100 buttons and the first previews.
2. Save a text edit with Done, 100-page parts manual: 7.1 s against 1 s (before: 17.4 s). The server alone
   misses the budget: 1.81 s at p95 on the benchmark's lighter 100 pages, and the phase's fixture is about
   twice as heavy (1398 list rows, 94 figures). The page then reads the document again and draws it.
3. Undo and redo follow the save (5.6 s and 5.9 s); the plan sets no budget for them.

Where a save still goes (one save on the benchmark's 100-page parts manual under cProfile: 5.0 s profiled,
1.76 s unprofiled, 10.4 M calls): the write itself (`apply_command`) 2.7 s, the compile of the answer
(`build_manual_document`) 2.4 s. `copy.deepcopy` is 2.8 s of the 5.0 s (2.8 M calls). The scene is read
twice (`_read_scene`, 2.2 s), the identity catalogue is compiled twice (`compile_identities`, 1.2 s) and
32 893 values are hashed (0.6 s). At the P5a-2 gate one save on the heavier fixture made 33.0 M calls, 8.9 M
of them in `copy.deepcopy`, with 17 identity compiles.

What is left is one compile and one copy of the whole document per write and per answer. Taking that away
needs a compile of the changed page only, or an answer that carries the changed page only. That is a design
change with its own proofs (the same bytes on every page that did not change), not a tuning step, and it is
in no slice of this plan. It goes to the product owner with the list at the end of P5b.

### What I changed in the product

1. `ai_inspector/documentation/provenance.py`, `project_document`. The delivered shortcut reuses the effective
   text targets as the source targets when the scene has no generated text override, and looked for the key
   `text` only. `text_targets` takes a generated element's text from `text` and from `richText`; a scene with
   only a rich-text override would have shown the edited text as the source text. Both keys are looked at.
2. `static/index.html`, Escape with an object selected (delivered B4). The selection was cleared but the
   keyboard focus stayed on the object. An object's focus means "selected" (its focus event selects it), so
   the page held an unselected object with the focus, on which Enter and the arrow keys did nothing. The focus
   now leaves with the selection and goes to the page (`.documentation-canvas-stage`); Tab reaches the
   objects again from there.
3. `static/index.html` and `static/cad_viewport.js`, the viewer's contexts (delivered B1). The common disposer
   was right and still released nothing: run 13 counted 143 live contexts after twenty cycles. A heap snapshot
   of the test browser showed why. three.js r128 puts one `dispose` listener per renderer on every geometry,
   material and texture that renderer has drawn; the model is cached and shared by every mount
   (`state.partsManualBaseMeshPositions`, the cached GLTF), and the orientation gizmo's sprites share one
   geometry; so every closed renderer stayed reachable from the cache. `_releaseSceneGpuResources(scene)` now
   runs in `_disposeAssembly3DMount` before the renderer goes: it calls `dispose()` once on each geometry,
   material, texture (uniforms included) and instanced mesh of the scene, which frees the GPU copies and
   detaches those listeners. Nothing of the cached model is destroyed; the next renderer uploads its own
   copy, as a new context must anyway. The gizmo disposes its shared sprite geometry once.
4. `static/index.html`, Escape in an open menu (delivered B4). The capture-phase key handler runs before the
   menu's own; with an object selected it cleared the selection, which redraws the ribbon under the open
   menu, and the keyboard focus was lost (run 13, `p5a_light_menu_focus_0`). An event from inside an open
   menu, list or dialog (`[data-ribbon-dropdown], [role="menu"], [role="listbox"], [role="dialog"],
   [aria-expanded="true"]`) is now left to its owner. One behaviour change follows: Escape in an open menu on
   a parts-manual page no longer also goes to the overview page; it closes the menu.
5. `static/index.html`, the ribbon with an object selected (delivered B2). The container rules fold groups by
   the ribbon's width alone. The Format group (font, size, bold, italic, colour) and the Object group come
   and go with the selection. With a text box selected on the operations manual at 1720 x 1080 the rules
   folded Figure into More and the rest still did not fit: Delete, Publish, Preview, the DOCX export and More
   itself lay past the ribbon's end (ten controls cut), so the folded commands could not be reached at all.
   Smoke phase P3b stopped there (153 checks passed, then a press on Capture All found nothing to press). The
   phase's scaling stage had not seen it: it measured the ribbon with nothing selected and with the text
   editor open, not with an object selected. `_documentationFitWorkflowRibbon` now runs after every ribbon
   render and when the ribbon's width changes: while the last group ends beyond the command bar it folds one
   more group into More, in the order Figure, Annotate, Values, Content, Edit, Object
   (`data-documentation-folded`). The delivered rules stay as the first step. Only a group that More can show
   is folded; the Format group and Publish never are.
6. The same function: the fit runs once per render. A ResizeObserver reports once right after `observe()`;
   that report repeated the fit the render had just done, so it is ignored when the width is the fitted one.

Everything else in the delivered change was read and kept: the request-local reuse
(`ai_inspector/documentation/request_work.py`), `owned=True` on privately built documents, the rail that keeps
its buttons and builds previews in idle time, the batched text fit, the covered 3D viewer that stops drawing,
the lazy Tiptap import, the toolbar without its height cap, and the faster word reader of P4b.

### What I changed in the harness and the tests

- `tests/documentation_editor_scale_smoke.py`: `escape_selected_object_stays_on_page` also records where the
  focus went; new check `escape_open_menu_keeps_selection`; the two panel checks that press with the pointer
  wait two animation frames before they read the focus (Tiptap focuses on the next frame; the check failed
  once for that reason alone); new checks `p5a_scale_<scale>_<size>_selected_controls` (an object selected,
  no editor open: nothing cut, the Format and Object groups present, Publish on the ribbon, and More there
  whenever a group is folded), which also record the cost of one fit (`fitMs`). On the delivered code the new
  check fails at 1720 x 1080 at every device scale (ten controls cut); it passes with correction 5.
- `tests/smoke_documentation_editor.py`: `ribbon_click()`. A command that is folded is pressed on its More
  entry, with the pointer, as a user would; a folded dropdown is skipped because More lists its items
  directly. Before, a Playwright click scrolled the clipped ribbon to reach a button past its end, which is
  how the earlier gates passed with a cut ribbon. The ribbon presses of the nine phases that can meet a fold
  (Capture All, Undo, Redo, Find, the View menu, and the two `press` helpers of P4a and P4b) go through it.
- The same file, phase P4b, `<name>_generated_bounds`. The check read a preview from every item of the page
  rail at once. The rail now builds a preview only for an item near its view, in idle time, and keeps the old
  one until then; right after the switch to A4 the check found 18 of 32 items without a preview and 7 with
  the Letter preview (55 of 128 blocks). It now brings each item into the rail's view and measures it once
  its preview is the one for the current page. What it proves is unchanged: 128 of 128 blocks inside the page.
- `tests/test_parts_manual_ui_contract.py`: the pin "no preview work while Sage is working" follows the rule
  from the rail's render function to the idle queue.
- `tests/cad_viewport.test.cjs` and `tests/documentation_performance.test.cjs`: the disposer's order and the
  gizmo's sprite geometry; two tests for the measured fit (a fake command bar; the stylesheet rules for every
  group the fit may fold; the once-per-render guard).
- `tests/test_documentation_performance.py`: the tests that compare with the old implementation skip when
  commit 4669cd0 is not in the repository (a shallow clone), and say so.

### Findings in the product (for the product owner)

1. With a text object selected at 1720 x 1080, Undo, Redo and Find are in More (the Edit group is the fifth to
   fold). Ctrl+Z, Ctrl+Y and Ctrl+F work as before. A wider window or no selection shows them on the ribbon.
2. A More entry copies its command's disabled state when More opens; a command that becomes available while
   More is open stays grey until More is opened again. Older behaviour; recorded.
3. After a paper change the rail's previews of pages far from the rail's view stay as they were (the old
   paper) until they are scrolled near. By design of the idle queue; recorded because it is visible.
4. The font and size fields of the Format group have no More entry, so that group cannot be folded. At
   1366 x 768 with a text object selected the ribbon fits (the Object group is in More there).
5. Findings 1 to 4 of the P5a-2 gate are closed by this slice. Its findings 5 to 11 are unchanged.

### Gates

Everything below ran on the final code of this slice unless a row says otherwise.

| Gate | Result |
| --- | --- |
| Node suites (`node --test`) | 498 passed: cad viewport 5, conflicts 20, objects 168, page setup 2, performance 10, publication 2, rich text 258, scale probe 2, search 20, tables 11; inline scripts 4/4; borrow callouts 5/5 |
| Complete documentation suites | 2075 passed, 1 failed: `test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed` (known since the baseline before P0). P5a-2: 2050 passed and the same failure |
| Tests that read a changed product file (89 selected tests and 5 files) | 151 passed, 11 failed: the same 11 as at the P5a-2 gate (7 of the known wide list, 4 in `tests/test_training_process_map.py`) |
| Wide suite, four parts | 3855 passed, 68 skipped, 179 failed or errored: the 179 known since P3a-1, none new, none gone |
| Baselines | `tools/documentation_baseline.py --check` exit 0; `--local --check` exit 0 ("Documentation baseline matches; reopened stores were unchanged.") |
| Smoke P1a | 27/27 |
| Smoke P1b | 46/46 |
| Smoke P1c | 35/35 |
| Smoke P2a | 23/23 |
| Smoke P2b | 36/36 |
| Smoke P3a | 194/194 |
| Smoke P3b | 169/169 |
| Smoke P4a | 475/475 |
| Smoke P4b | 198/198 |
| Smoke P5a, full size, twenty memory cycles, quiet machine (run 14: the code before corrections 5 and 6) | 201/201 in 27 min |
| Smoke P5a, full size, twenty memory cycles, final code, busy machine (run 15) | 196/198 in 43.5 min: the 40-minute limit and the stage it cut off |
| Smoke P5a, stage `overflow_findings` alone, full size, final code | 12/13: `p5a_all_stages` only (by construction) |
| Smoke P5a, stage `scaling` alone, debug sizes, final code | 55/59: the four by-construction checks only; the eight `selected_controls` checks pass |

The nine smoke phases, the suites, the wide suite and the baselines ran in one chain on the final code. The
last harness addition (the recorded `fitMs`) came after the chain; the stage `scaling` and the tests that pin
the harness files (44 passed) were run again with it.

Not run in this slice: a complete run of the phase on the final code on a quiet machine (above; first step of
the P5b gate), and the desktop smoke (`tests/smoke_documentation_editor_desktop.cjs`), which belongs to P5b.
