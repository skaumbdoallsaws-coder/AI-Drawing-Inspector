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
