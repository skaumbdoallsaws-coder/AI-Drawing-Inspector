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
