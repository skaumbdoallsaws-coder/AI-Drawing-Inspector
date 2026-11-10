# P1b - documentation editor

## P1b-1

Date: 2026-11-09. Builder: Codex. Reviewer, runtime tester and committer: Claude.

Implemented only text-safe work-instruction figure captures. P1a's scene-schema-3
and slot-schema-2 owners remain in place. No edit.json envelope, provenance,
confirmation flow, named undo, slot journal or P1b smoke extension was added.
No commit, branch, index mutation, network access, installation, application
launch or pytest execution was performed by the builder.

### CHANGED

- **ai_inspector/work_instructions/document.py:** generated document schema 1 -> 2;
  figureRevision on each figure-bearing page. The identity binds assembly, source,
  plan, render pipeline, page and effective render request, including image sizing
  and framing contracts. CAD composition retains figure camera/transforms/explode,
  group/occurrence overrides and balloon/leader overrides. Text, typography and
  authored page objects stay in documentationComposition and are excluded from
  renderRequest at _apply_scene, fixing the original wiring defect. Attached image
  metadata is excluded from figure hashing. documentRevision still identifies the
  complete text/export document. Schema 2 is reserved for the P1b-2 additions too.
- **ai_inspector/operations_manual/artifacts.py:** work-instruction-only dispatch
  stores captures under each page's figure revision; figure_revision is an optional
  additive writer input. Attachment checks source, plan, page, figure identity and
  PNG digest, clears unvalidated incoming image state and projects ready captures
  onto the current documentRevision. captureRevision records the actual storage
  identity for export lookup. Existing operations/specification branches retain
  their previous document-revision behavior.
- **Legacy captures:** reconstruct the canonical schema-1 documentRevision from
  the current source/plan/pipeline and full historical request, and accept only
  matching legacy artifact metadata and PNG bytes. A schema-1 document must also
  match its original recorded hash. The full page composition must agree with the
  effective CAD composition. There is no directory scan or arbitrary old-revision
  fallback. Read migration computes schema 2/figure identities in memory and does
  not write. Explicit workspace or Sage mutations adopt only unchanged, validated
  legacy captures under figure identities, preserving all old artifact bytes.
- **ai_inspector/work_instructions/exports.py:** readiness checks the effective
  figure revision, and PDF/DOCX export reattaches validated disk captures before
  rendering. **ai_inspector/operations_manual/exports.py:** four shared cover/body
  image lookups use a document-aware path helper; operations still resolves the
  identical documentRevision path. This small shared-renderer change is necessary
  because both work-instruction export formats delegate to it.
- **server.py:** accepts optional per-page figureRevision on work-instruction
  uploads. Matching figure identity permits a capture started before a text edit;
  a supplied stale figure is rejected even with a current documentRevision. Older
  callers without it retain the exact documentRevision guard. Existing builders,
  command/history routes and exports use the revised attachment/carry helpers.
  Sage's existing scene batch adopts legacy captures after a committed mutation.
  No Sage tool schema or inventory changed.
- **static/index.html:** submits the page figureRevision, with the existing
  specification document figureRevision fallback. Work-instruction composition
  reads use the complete page composition so inline text/style controls continue
  to see their overrides. This is inline script only; no external static JS file
  changed, so no JS URL cache-version bump applies. Added strings are ASCII.
- **tests/test_work_instruction_workflow.py:** added the two requested regressions.
  The capture/edit/export test edits page-work-instructions-cover / wi-cover-status,
  asserts unchanged capture bytes/figure identities, downloads PDF/DOCX and checks
  edited text, then changes the real camera through set_view and requires only
  that page's recapture. Legacy coverage uses an independently constructed old
  document hash and artifact shape, verifies read-only access, rejects a changed
  old figure and tests first-mutation adoption through both workspace and Sage.
  Additional cases cover capture-input sensitivity, stale upload rejection,
  text-edit/upload overlap, tampered artifact bindings/digest and future schemas.
- **docs/documentation-editor-reports/P1b.md:** this P1b-1 handoff. Later rounds
  append their own sections.

### TESTS

Builder checks only; these are not runtime-suite or browser results:

- Python ast.parse on all six changed Python files: exit 0, no application imports
  or test execution. Changed files were re-parsed after final guard/test edits.
  Invoked C:/Python314/pythonw.exe tools/run_hidden.pyw C:/Python314/python.exe -c
  with a stdlib-only AST parser and explicit source-file paths, parent windowsHide
  and redirected pipes.
- node --input-type=module --check on each of static/index.html's four executable
  inline script bodies via stdin: all four exit 0. No browser or app launched.
- git diff --check: exit 0.
- In-process byte/diff checks: all written files use LF; server.py retains its
  UTF-8 BOM; additions to server.py/static/index.html are ASCII.
- Static review traced the actual CAD camera, transforms, callout routing and image
  sizing consumers; it is not live capture proof. New pytest captures are synthetic.

### NOT RUN

Claude runs these outside the builder sandbox, with the authorized local inputs,
isolated stores and the supplied library snapshot. The builder lacks pytest,
numpy, Pillow, PyMuPDF and a browser; no substitutes or dependency installs were
used. Use the hidden Windows runner and redirected output as in P1a.

Required focused gate and both baselines:

~~~text
python -m pytest -q tests/test_work_instruction_workflow.py tests/test_operations_manual_workspace.py tests/test_specification_sheet*.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
~~~

Full documentation suites, including the existing transaction/tool gates:

~~~text
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_store_chokepoint.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_documentation_editor_smoke.py
python -m pytest -q tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_mcp_schema_types.py
python -m pytest -q tests/test_documentation_baseline.py tests/test_parts_manual.py tests/test_inspection_sheet.py
python -m pytest -q tests/test_specification_sheet_slots.py tests/test_specification_sheet_workflow.py tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
python -m pytest -q tests/test_documentation_form_fields.py tests/test_documentation_library_assembly.py tests/test_parts_manual_ui_contract.py tests/test_parts_manual_callout_quality.py tests/test_operations_manual_precoding_contracts.py
python tests/smoke_documentation_editor.py --phase P1a
~~~

Retain the known pre-existing failure separately:
 tests/test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed.
P1b-3 owns the P1b browser-smoke extension; it was neither added nor claimed here.

### DEVIATIONS

No functional scope deviation. Two small adjacent integrations were necessary:
the shared PDF/DOCX image lookup and the inline UI composition/capture inputs.
They preserve operations/specification behavior. The baseline probe and its tests
are unchanged because it already records the required facts without repair when
export succeeds. Baseline expectation JSON files are untouched.

Expected local baseline behavior changes under workInstructions:

| Fact | Before | Expected after P1b-1 |
| --- | --- | --- |
| textEditInvalidatesPageCapture | true | false |
| pagesNeedingCaptureAfterTextEdit | [page-work-instructions-cover] | [] |
| textEditExportHttpStatus | 422 | 200 |
| recapturedPageIds | [page-work-instructions-cover] | [] |

**Baseline expectation discrepancy to review:** the requested schema 2, page
figureRevision, captureRevision and changed capture URLs also change the complete
semantic document hashes at /workInstructions/before, /workInstructions/edited
and /workInstructions/reopened. tools/documentation_baseline.py intentionally
removes clocks only, so expecting literally only the four facts above to differ
would conflict with the schema change. Do not weaken normalization to hide these
metadata changes. Claude must verify and re-record/promote those three hashes as
well as the four facts after review. No replacement hash was invented here.
PDF/DOCX text/dimensions and every operations/specification baseline are expected
to remain unchanged; this expectation has not been measured by the builder.

### OPEN QUESTIONS

No implementation decision requires user input. Claude's runtime/export review,
baseline comparison (including the three metadata hashes above), P1a smoke and
commit remain pending. P1b-2 must preserve the historical schema-1 hash projection
when adding provenance fields to this same schema 2; that next round is unstarted.

### P1b-1 supervisor gate (Claude, 2026-11-09)

- tests/test_work_instruction_workflow.py 18 passed; operations workspace + specification suites 70 passed.
- Documentation suites: 447 passed + the known pre-existing failure (before the local baseline promotion the
  baseline test also failed, as expected); JS 5/5. Wider suites: 3848 passed, 170 failed, 9 errors, all failing at
  the base too; no new failure.
- Local baseline re-recorded twice (identical) and promoted. Changed exactly: the four workInstructions capture
  facts (false, [], 200, []) and the three schema-2 document hashes (before/edited/reopened). Operations and
  specification facts, and every export fingerprint, unchanged. Synthetic `--check` matches unchanged.
- Browser smoke --phase P1a: 27/27.
- Supervisor test changes: the WI DOCX text assertion was removed (the WI DOCX never carries the cover status
  line, a P0 finding owned by P4); the smoke classifies an aborted /api/bridge/status poll as known (unit test).

## P1b-2

Date: 2026-11-09. Builder: Codex. Reviewer, runtime tester and committer: Claude.

Provenance, row/item support, review markings, customer-export gating and
scene-backed UI confirmation are implemented for review. **This round is not
claimed complete: specification-slot confirmation is an explicit scope gap.**
The user requires confirmation to be undoable but reserves the slot undo journal
for P1b-3. An asynchronous clarification was sent; no answer was received during
this work. Slots retain their existing review/acceptance controls. The new
confirmation endpoint and proposal reject slot confirmation, and the new button
is not offered for slots. See DEVIATIONS and OPEN QUESTIONS before committing.

No named-change undo/redo, slot undo journal, new persistence envelope or P1b
browser-smoke steps were added. No commit, branch/index mutation, network access,
installation, application launch or pytest execution was performed.

### CHANGED

- **ai_inspector/operations_manual/content.py, flow.py, document.py:** generated
  schema 1 -> 2. Explicit registered-claim relations accompany the nine published
  specification rows and the precisely bound control-list items. Annotated blocks
  carry evidenceBindingVersion 1; claimIds/sourceIds survive pagination and split
  row fragments. Unbound material keeps conservative block scope. Existing
  evidenceClaimIds and evidenceCitations remain compatibility/audit receipts.
  A historical plan projection removes only the new binding keys when calculating
  manualPlanRevision, preserving existing scene bindings and positional overrides.
  The page-6 "1,100 lb" source prose is unchanged.
- **ai_inspector/documentation/provenance.py (new), targets.py, commands.py:** pure
  generated/legacy projections and additive fieldMeta. Metadata records origin,
  evidenceStatus, original claim/source links and source revision, generated
  value/hash, actor and change ID. Active support is separate from originalEvidence.
  Bound rows lose only their own support; an unknown cell relation marks the row.
  Paragraphs and unbound tables/lists use block scope. Partially bound lists retain
  item scope until an unbound item requires whole-block marking. Complete original
  values remain available for confirmation. Exact unchanged text/style keeps its
  citation; typing the old string after a semantic edit keeps edited_unverified.
  Source-support summaries accompany the document and Sage reads. Parts headings,
  shared BOM text and authored text objects also receive unbound origin metadata.
- **ai_inspector/parts_manual/documentation.py:** fieldMeta is additive in scene
  schema 3 and replayed from the existing command prefix. Existing cursor undo/redo
  restores value and provenance together. Confirmation is one existing batch entry
  using an update_text leaf with the exact current text and confirmation metadata;
  it introduces no new persisted command operation. Its receipt/change ID is shared
  by the metadata. The normal command/batch paths reject confirmation metadata;
  only the trusted server handler opts in. No named undo was implemented.
- **ai_inspector/specification_sheet/slots.py, document.py:** fieldMeta is additive
  in slot schema 2; generated sheet schema advances 1 -> 2. Native mutations seed
  metadata from the effective compiled values, including old scene overrides.
  Old stores are projected without writing; first mutations adopt metadata. Existing
  overrides_evidence, overrides_cad, source distinctions, acceptance records and
  engineering gates remain. Clearing a slot still returns to its generated default.
  Slot confirmation and undo are not implemented in this diff.
- **ai_inspector/parts_manual/document.py:** generated schema 4 -> 5, preserving
  definition-keyed text and the original generated BOM text in provenance.
  **ai_inspector/work_instructions/document.py:** adds provenance to schema 2
  without another bump. The historical schema-1 hash projection strips only these
  additive keys, including page support summaries; figure identities are unchanged.
- **server.py:** manual/Sage text writes use the common provenance preparation.
  GET /api/documentation/{documentType}/{assemblyNumber}/confirmation-targets
  returns complete affected scopes and hashes. UI-only POST
  /api/documentation/{documentId}/confirm-values validates expectedRevision,
  requestId and each scope hash, rejects extra authority fields, commits atomically
  and returns one idempotent receipt. Confirmation records by/at/changeId/valueHash;
  another semantic edit clears it. Scene confirmation carries unchanged captures.
  Hostile origins/hosts and preflights use the app's existing product trust check.
  The handler calls the already configured in-process principal resolver directly,
  avoiding facility bootstrap side effects. Its existing no-identity fallback is
  the fixed **local-user** principal; no credential/account/session-file read was
  added or performed. Customer/controlled modes on operations, work-instruction
  and specification review routes reject unconfirmed cited scopes with
  unconfirmed_cited_values and the exact target list. Controlled-release
  prerequisites remain separately enforced.
- **ai_inspector/operations_manual/exports.py,
  ai_inspector/specification_sheet/exports.py,
  ai_inspector/work_instructions/exports.py:** review/draft PDF and DOCX render
  "Edited - source does not verify this value" and a source-support legend near
  affected rows/blocks. Legacy generated inputs receive pure provenance projection
  before gating/rendering. Operations caches require provenanceVersion 1 so an old
  cached export cannot bypass the markings. Confirmed customer operations artifacts
  have separate short mode suffixes and no edited warning or active source link for
  the confirmed scope. Untouched rows may still cite the same original source.
- **static/documentation_commands.js, static/index.html:** row/item/block and
  specification-slot markers, properties with original sources, and a visible
  "Confirm as entered by me" dialog. It displays every value in each affected
  scope and former sources, uses fresh server hashes, and requires event.isTrusted
  both to open and to submit. Only that handler contains the confirm-values POST.
  CSS markers do not enter editable textContent. Sage source summaries use active
  support. Script URL bumped to ?v=20261109-p1b-2. Server BOM, LF and ASCII additions
  to server.py/index.html are preserved.
- **ai_inspector/codex_runtime/documentation_tools.py, documentation_pilot.py:**
  read-only propose_document_value_confirmation returns a proposal ID, document ID,
  target/hash list and awaiting_user, without mutating a document. It currently
  declines slots consistently with the missing slot UI action. Full reads expose
  provenance and relevant confirmation scopes; source-support summaries distinguish
  edited values. Existing tool inputs/names and specification acceptance authority
  are preserved. Updated all four requested pinned tool-inventory test files.
- **tests/test_documentation_provenance.py (new):** all 15 named plan tests plus
  atomic-scope and old-slot/parts-shape cases. Compilation tests use the real MMLE
  compiler and local registered claims; synthetic shapes isolate legacy/split-row
  behavior. Tests cover support scope, exact-value/format behavior, export/Sage
  markers, customer rejection, confirmation receipts/principal/undo, stale hashes,
  hostile origins/preflights, UI trusted-event guards, server/browser registry scans,
  nonmutating proposals and clearing confirmation on another edit. These tests
  have been authored, not executed.
- **tests/test_work_instruction_workflow.py:** independently constructed schema-1
  fixture omits additive provenance before hashing. Claude's removal of the WI
  DOCX cover-status assertion is retained. The smoke and its aborted bridge-poll
  classification test are byte-for-byte unchanged in this round.
- **tools/documentation_baseline.py, tests/test_documentation_baseline.py:** the
  citation probe records active row support separately from original block/source
  receipts, row binding/status, other rows' claims, customer refusal/targets and
  review markings. It continues measuring the original source register independently.
  No baseline JSON was edited. Slot metadata change IDs use the existing patched
  secrets source, keeping baseline runs deterministic without stripping IDs.

### TESTS

Builder static checks only; no runtime-suite or browser pass is inferred:

- Python ast.parse over all 25 changed/new Python source files: passed. Invoked
  C:/Python314/pythonw.exe tools/run_hidden.pyw C:/Python314/python.exe -c with
  explicit paths and a stdlib-only AST parser; no application imports.
- node --input-type=module --check via stdin for the four executable inline
  scripts in static/index.html and static/documentation_commands.js: all passed.
- git diff --check: passed.
- In-process byte/diff checks: written files use LF; server.py retains efbbbf;
  additions to server.py/static/index.html are ASCII. Baseline JSON and both
  supervisor smoke files have no diff.

### NOT RUN

Claude runs these outside this sandbox with isolated stores and the authorized
local MMLE/library inputs. The builder lacks pytest, numpy, Pillow, PyMuPDF and a
browser; none were installed or replaced. Use the hidden Windows runner and
redirected pipes. No P1b smoke extension belongs to this round.

Required focused gate and both baselines:

~~~text
python -m pytest -q tests/test_documentation_provenance.py tests/test_operations_manual*.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
~~~

Full documentation and wider suites, then the existing browser smoke:

~~~text
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_store_chokepoint.py tests/test_documentation_editor_smoke.py tests/test_codex_mcp_schema_types.py
python -m pytest -q tests/test_documentation_baseline.py tests/test_parts_manual.py tests/test_inspection_sheet.py
python -m pytest -q tests/test_specification_sheet*.py tests/test_work_instruction_workflow.py
python -m pytest -q tests/test_documentation_form_fields.py tests/test_documentation_library_assembly.py tests/test_parts_manual_ui_contract.py tests/test_parts_manual_callout_quality.py tests/test_operations_manual_precoding_contracts.py
python -m pytest -q tests/test_codex*.py tests/test_facility*.py tests/test_authored*.py tests/test_sage*.py tests/test_industrial*.py
python tests/smoke_documentation_editor.py --phase P1a
~~~

Retain the known source-closure failure separately:
 tests/test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed.
Wider failures must be compared to Claude's base as in prior rounds, not waived
by this report. Export marker placement and trusted UI behavior still need actual
runtime/browser review; syntax checks do not prove them.

### DEVIATIONS

- **Incomplete slot confirmation:** the required undoable generic confirmation is
  implemented for scene-backed documents only. Providing it for slots needs the
  undo mechanism reserved explicitly for P1b-3. No new nonundoable confirmation or
  journal was substituted. Existing slot acceptance does not set entered_by_user
  or clear this citation gate. Edited specification customer export remains blocked
  until the source value is restored or slot confirmation is completed. This is
  an unresolved requirement, not a claimed pass or an approved scope change.
- Original block evidenceClaimIds and top-level evidenceCitations intentionally
  remain. Active links are row/item/block metadata and source-support summaries;
  stripping the compatibility receipts would violate the plan. The probe now
  measures both, rather than treating the old receipt as active support.
- The baseline probe extension is required to observe the repaired contract;
  normalization and expectation JSON were not weakened or hand-edited.

Expected baseline changes for Claude to inspect and re-record:

| Location/fact | Expected result |
| --- | --- |
| operations/citationDefect/rowBindingsPresent | true |
| operations/citationDefect/editedRowEvidenceStatus | edited_unverified |
| operations/citationDefect/otherRowsClaimsRetained | true |
| effectiveAfter/activeEvidenceClaimIds and claimCitations | empty for capacity |
| effectiveAfter/originalClaimCitations | original OEM source receipt retained |
| compiledBlockKeepsCapacityClaim, changedValueKeepsBlockClaimIds | remain true: compatibility block receipt |
| changedValueKeepsCitationAuthorities | false: edited row has no active OEM support |
| customerExportHttpStatus, customerExportError | 422, unconfirmed_cited_values |
| customerExportTargets | one row scope, alias spec-table-1.r0, page-specifications-1 |
| reviewExportMarked | PDF true, DOCX true |
| operations edited export fingerprints | change because marker/legend text is printed |
| specification edited export fingerprints | change because marker/legend text is printed |
| all affected document/scene semantic hashes | change for schema/additive provenance/support metadata |
| workInstructions capture facts | stay false, [], 200, [] from P1b-1 |
| workInstructions before/edited/reopened hashes | change for provenance; schema remains 2 |

Untouched export text/geometry, the specification golden text, capture behavior,
reopen/no-write facts and existing undo behavior should otherwise remain. Synthetic
parts/specification document hashes and the raw table scene hash also change for
additive metadata. No replacement hash was invented. The page-6 capacity wording
and exports/valuePageNumbers observation stay unchanged in meaning; reconciling
that separate source-backed prose is a later feature.

### OPEN QUESTIONS

- Resolve the slot-confirmation/journal split before declaring P1b-2 complete:
  retain the current restriction until P1b-3, or explicitly authorize the minimal
  slot undo mechanism in this round. The clarification sent during implementation
  remains unanswered. All independent work is available for review.
- Claude must run the exact gates, review actual PDF/DOCX/UI markings, compare and
  promote measured baselines, and decide whether the above gap prevents this
  round's commit. The builder has made no commit and claims no runtime pass.

### P1b-2 supervisor gate (Claude, 2026-11-09)

- Targeted provenance/operations/Sage tool tests: 197 passed + the known pre-existing failure.
- Documentation suites: 470 passed + the known pre-existing failure; JS 5/5. Wider suites: 3849 passed, 170 failed,
  9 errors, all failing at the base too; no new failure. Browser smoke --phase P1a: 27/27.
- Baselines re-recorded twice (identical) and promoted. Synthetic: only document hashes (parts, specification) and
  /table/scene changed; no synthetic export changed. Local: operations citationDefect flips as planned (edited row
  has no active claims, edited_unverified; other rows keep claims; customer export 422 unconfirmed_cited_values
  with the row target; review PDF/DOCX marked), operations/specification edited exports gain the marker and
  legend, document hashes change with the new schemas.
- Visual check of the marked review pages: operations page 10 (marker under the edited value, legend under the
  table) and the specification sheet (marker under Rated Capacity, legend above the footer; it sits close to the
  row rule, a spacing note for P4). The sheet's feature card still says "1,100 lb Rated Capacity" from its source:
  cross-document consistency stays later work.
- Supervisor fix: SlotStore.__init__ resolved slots.json itself; during a concurrent replace Windows resolves it to
  its \?\ form and the containment check raised (test_two_threads_cannot_overwrite_one_read[slots] failed 11/15).
  It now resolves the assembly folder, like the scene store (0/15).
- Decision: specification slot confirmation moves to P1b-3 with the slot undo journal.
