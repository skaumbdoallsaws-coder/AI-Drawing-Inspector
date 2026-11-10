# P1a - read-bound atomic edits, in place

Date: 2026-11-09. Builder: Codex. Reviewer/tester/committer: Claude.

Implementation is wired through the existing scene and slot owners. There is no
edit.json adoption or partial reader/writer cutover. This review round corrects
the migration test oracle and browser smoke; production code and baseline
expectations were not changed. **The revised runtime gate is NOT RUN by the
builder and is not claimed passed.** Claude reruns it, re-records the deliberate
synthetic /table/scene baseline difference after review, and commits only when
the gate passes. No commit, branch, index mutation, installation, network access,
pytest execution or app/browser launch was performed by the builder.

## CHANGED

This review round:

- **tests/test_documentation_transactions.py:** pin the legacy-reader revision to
  e3fc2f7708123a6db577db01cbbe71c57fcba94241cde4af3978ebf8cf7d9ab1, measured by
  Claude with the old and new repository readers on the same sanitized excerpt.
  The old reader already normalized that excerpt, so its raw-file hash was the
  wrong oracle. Keep the no-write-on-read and original-v2-byte backup assertions.
- **tests/smoke_documentation_editor.py:** if the workspace opens blank, click the
  real Refresh ribbon button. Its existing _documentationReloadWorkflow path
  calls _documentationRefreshScene({revealAll: true}) and exposes the seeded
  document's pages without generation. Record before/after generation snapshots,
  page counts and unchanged scene/manual-plan hashes on every open; continue
  through the existing real double-click edit, HTTP stale Sage request, reopen,
  receipt, retry, undo and document-switch checks. No synthetic page state or
  localStorage seeding is used. Every failed check and fatal exception attempts
  a screenshot before browser teardown; report the filename or why capture was
  unavailable. Cleanup still stops the isolated server after browser failures.
- **Smoke error reporting:** retain raw HTTP/console evidence and separate only
  known sanitized-fixture GET failures (404 drawing-map/drawing-pdf/part-features/
  process-map previews; 500 reference-views) and their correlated console errors.
  All documentation-route errors remain fatal. The missing ignored
  static/contracts/semantic-knowledge-prototype-v1.json is documented as a known
  server-startup log limitation; an unexpected browser fetch error is not waived.
- **tests/test_documentation_editor_smoke.py:** add pure classification tests for
  those exact method/status/path exceptions, their console consequences, fatal
  documentation routes, and unknown HTTP/console/network failures. They launch
  neither the app nor a browser.
- **Preserved Claude's fixes:** PYTHONUSERBASE=site.getuserbase() and the isolated
  INSPECTORPRO_FACILITY_LAYOUT_ROOT in the smoke; extended-length Windows path
  normalization in tests/documentation_editor_smoke_server.py. The helper file
  is unchanged in this review round. No production or static JS change, so no
  new cache-version bump is needed.

P1a implementation carried forward:

- **Storage:** ai_inspector/parts_manual/documentation.py keeps ownership of
  documentation-scene.json. Schema 2 loads as schema 3 in memory without writing.
  The first explicit write keeps original bytes in documentation-scene.v2.json.
  apply_batch validates the complete candidate under the existing RLock, commits
  once, and stores one batch entry in the existing cursor history. Old entries
  and apply_command remain supported. Undo/redo advance monotonic target counters
  and replay a batch as one step. All scene writes use the same save helper.
  The rendering revision uses its historical projection so transaction metadata
  does not invalidate untouched captures/exports.
- **Slots:** specification_sheet/slots.py keeps ownership of slots.json. Schema 1
  upgrades in memory to 2; first write keeps slots.v1.json. All mutators stage in
  a transaction, including compound row/value/settings changes, before one fsynced
  replacement. apply_batch exposes value batches. Slot undo remains P1b work.
  specification_sheet/document.py separates layout and storage versions to preserve
  the generated plan hash.
- **Contracts:** documentation/commands.py provides hashes, checks, errors and
  receipts. Each store retains the newest 1,000 receipts in explicit commit order.
  Identical retries return the original receipt; reused IDs with changed payloads
  fail. Older revisions require matching pre-images for every dependency and no
  open conflict. Monotonic field/collection counters protect evicted retries,
  including change-then-revert. Requests are bounded to 256 KiB; scenes keep the
  2,000-entry history and 16 MiB size caps. No-op receipts may be saved without
  changing content/revision/cursor.
- **Reads:** documentation/targets.py exposes full exact strings, UTF-8 hashes,
  document/source/plan bindings and a per-turn ReadBindings cache. Parts descriptions
  stay definition-keyed and use their existing page-parts-index storage. Native
  parts headings and authored text objects are readable targets. Summaries mark
  excerpts. Failed/oversized reads cannot authorize writes; generated identities
  across refresh remain P1c work.
- **Host and Sage:** server.py and codex_runtime/documentation_tools.py connect
  edit_document_text to one apply_batch call. Omitted preconditions come only from
  successful model-visible reads in the turn. Internal validation/readiness reads
  do not authorize mutations. apply_document_edits is additive and rejects mixed
  text/value batches with "send text and value edits as separate requests".
  Specialized sheet tools keep their value/research/draft/approval rules and old
  inputs, adding bindings and receipts. Workspace slot requests validate dependency
  coverage and hash the actual request body. Actor authority stays in the host.
  documentation_pilot.py and progress.py distinguish synchronous receipt-based
  edits from queued workflows.
- **UI:** static/documentation_commands.js and static/index.html keep existing
  routes. Saves capture document/revision at edit start. Stale errors reload only
  the bound model while keeping the draft visible; delayed results cannot replace
  a newly selected document. Script URL: ?v=20261109-p1a-2. Server BOM and LF are
  preserved. Added strings in server.py/index.html are ASCII; existing Unicode
  was not rewritten.
- **Tests:** test_documentation_transactions.py covers old shapes/backups, atomic
  failure, batch undo/redo, stale/future/binding rejection, both older-revision
  outcomes, open conflicts, retry/reuse, eviction/ABA, structural dependencies,
  threads racing one read, denied replace, crash-after-commit recovery, full
  reads/excerpts, no-ops, and UI guards. test_documentation_store_chokepoint.py
  permits each filename only in its existing owner, with an explicit empty
  allowlist and indirect-I/O scan fixtures. Updated documentation/specification
  tool tests, the operations host test, the scene version assertion and
  readonly/assisted catalog separation assertions. Kept the sanitized MMLE v2
  excerpt. Removed the superseded edit_store.py and envelope worker foundation.
- **Browser deliverable:** tests/smoke_documentation_editor.py --phase P1a copies
  reviewed source and authorized MMLE engineering inputs into a temporary snapshot.
  tests/documentation_editor_smoke_server.py disables dotenv, blocks outbound
  connections, and guards filesystem mutations. All five document roots and both
  appearance roots are redirected using their already-existing environment
  overrides, along with the facility host's import-time root; no additional
  production root override was needed. Playwright edits a real BOM
  description, sends a stale Sage-host request over HTTP, reopens, verifies original
  v2 bytes, commits/retries a two-target Sage batch, checks the disk receipt,
  undoes it in one UI step, and switches types during a held save. JSON evidence
  goes to .runtime/de/report.json with screenshots/logs. Failures exit nonzero;
  temporary stores are cleaned. This is a host/browser proof, not provider inference.
  Later --phase values fail explicitly until implemented.
- **Plan:** section 3.1 and P1a/P1b/P1c now describe additive versions in the two
  existing stores, independent undo groups and a single backend process. Future
  rich/object/page metadata references were aligned; those features were not built.

## TESTS

Builder checks in this review round, through hidden child processes:

- Python ast.parse on tests/test_documentation_transactions.py,
  tests/smoke_documentation_editor.py, tests/documentation_editor_smoke_server.py
  and tests/test_documentation_editor_smoke.py: all four parsed, exit 0. No
  application imports or test execution.
- git diff --check: exit 0.
- Source inspection confirmed the Refresh control, revealAll path, and remembered
  page visibility on reopen. This is static reasoning, not a browser pass.
- Verified Claude's three isolation fixes remain; the smoke-server helper is
  byte-for-byte unchanged in this round. Files written in this round use LF.

Claude's supplied results **before these review fixes**, not builder runs:

- Transactions + chokepoint + Codex documentation + Codex specification tools:
  **121 passed, 1 failed** (the incorrect legacy revision oracle fixed above).
- Full documentation suites: **400 passed, 3 failed** (that oracle, the deliberate
  synthetic baseline change, and the known pre-existing source-closure failure).
- python tools/documentation_baseline.py --local --check: **MATCHES**, including
  operations/work instructions/reviewed specification documents, exports and undo.
- python tools/documentation_baseline.py --check: differs **only /table/scene**,
  the complete raw scene now carrying additive v3 keys. Expectations remain intact
  for Claude to re-record after this round.
- Browser smoke: isolated server started, isolation/outbound protection reported
  OK, source inputs unchanged, opening did not rewrite, and full bound target read
  passed. It then timed out at the hidden page rail because the fresh workspace
  was blank. The revised Refresh path, edit/reopen/receipt checks and failure
  screenshots still require Claude's browser run.

Earlier P1a handoff checks (not rerun in this narrow review round) included Python
parsing of 23 files, JS syntax checks, the AST ownership scan and production-file
encoding checks. No runtime pass is inferred from those static checks.

## NOT RUN

The builder is prohibited from running pytest or the app and lacks the runtime
dependencies/browser. Claude runs these exact commands in its isolated environment
with the authorized local inputs and library snapshot. Use the hidden Windows
runner: pythonw.exe tools/run_hidden.pyw <python.exe> <arguments>, parent
windowsHide=true, redirected output, no visible terminal.

~~~text
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_store_chokepoint.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_documentation_editor_smoke.py
python -m pytest -q tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_mcp_schema_types.py
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
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_parts_manual_isolated_pilot_publication.py --assembly MMLE-50D --minimum-occurrences 200 --expected-pages 18 --expected-technical-pages 12
~~~

The only accepted pre-existing failure is
 tests/test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed.
The unavailable tricycle editor smokes are replaced by the MMLE editor smoke.

## DEVIATIONS

- No new design deviation in this review. The existing real Refresh action is
  the lightest UI path that reveals the seeded pages; no generation run is needed.
  Known fixture failures are reported separately as directed by the supervisor;
  documentation errors are never allowlisted.
- The supervisor's in-place decision supersedes the envelope design. No cross-file
  transaction/undo or cross-process lock is provided. Thread tests match the
  desktop's single backend; a child tests restart after commit/before response.
  Legacy manual scene commands retain exact baseRevision checks. Sage batches
  and bound slot writes support matching older reads.
- Unknown future schemas fail closed and preserve bytes. This slice does not render
  an unknown future format read-only; the plan states that boundary explicitly.
- No-op requests may persist a receipt without a content revision/history change,
  allowing request-ID reuse checks even when the value was already equal.
- **Deliberate baseline difference:** expected.json's table.scene hashes the entire
  scene, so schema 3 and transaction counters intentionally change it. Claude
  confirmed that /table/scene is the only synthetic difference and the local
  baseline matches. No expectation or baseline normalization was edited. Claude
  will re-record the reviewed value before both baseline checks can be green.
  No replacement hash is invented here.
- Sage text batches now commit all-or-nothing as one undo step. Old inputs without
  a prior complete read fail safely. The P0 collector does not directly exercise
  Sage batching; these behavior changes have dedicated tests. Slot receipt
  undoable is false until P1b.

## OPEN QUESTIONS

No implementation-design question needs a user decision. Claude's rerun of the
corrected oracle, error classifier and real-browser smoke remains open, followed
by the reviewed /table/scene baseline re-record. Unexpected failures must be fixed
or explicitly reviewed before commit. Provenance, named undo, refresh/conflicts,
rich text and later slices remain outside P1a. Do not stage .runtime evidence, full local inputs,
generated stores or library trees.

## Supervisor gate (Claude, 2026-11-09)

- Browser smoke `tests/smoke_documentation_editor.py --phase P1a`: PASS, 27/27 checks (isolated real server, real
  browser, real Refresh control, real presses). Two smoke fixes by the supervisor: a manual page redraws on every
  press, so an inline edit starts on two separate presses within half a second (`begin_edit`, the same path as
  `_documentationTextPressed`), not a browser double-click; edit-target locators are scoped to
  `#documentationPublicationSurface` because the page thumbnails carry the same `data-documentation-edit-target`
  attributes and sit first in document order.
- Documentation suites: 434 passed, 1 failed (pre-existing
  `test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed`); JS 5/5.
- Wider suites (codex, facility, authored, sage, industrial): 3848 passed, 170 failed, 9 errors. Every failure also
  fails at the base code (model-import worktree run); no new failure.
- Baselines: `--check` re-recorded twice (identical) and promoted; only `/table/scene` changed (schema 3 keys).
  `--local --check` matches unchanged.
