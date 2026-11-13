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
