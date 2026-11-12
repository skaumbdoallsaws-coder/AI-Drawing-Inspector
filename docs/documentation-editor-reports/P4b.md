# Page setup and fidelity gate

## P4b-1

This section is corrected to the round-2 decisions below. The supervisor found that the original export pre-pass rejected existing generator defects; it has been removed.

CHANGED

- Added `documentation/layout.py`: Letter/A4 presets in each type's design orientation, strict preset validation, margins, and shared geometry with an exact identity path. All four editable types are enabled; inspection sheets have no presets.
- `parts_manual/documentation.py`, `documentation/changes.py` and `server.py`: scene schema 8, pure version-7 migration and first-write backup; optional `pageSetup` in the revision; `set_page_setup` with exact undo/redo and a current-versus-candidate fit comparison before persistence. Reads and command/history answers expose `pageSetupOptions`. Registry entries expose preset IDs. Sage's operation set is unchanged.
- The four compilers and their layout modules now use the selected geometry. Operations measures and paginates in the stretched content rectangle; parts keeps its row counts; work-instruction and specification frames stretch without scaling typography. Capture requests include page size only when the geometry is not identity.
- The PDF builders use actual paper dimensions and stretched coordinates, including the fillable specification. DOCX uses actual section dimensions/orientation and each builder's existing margins. Added per-type `fit_report` functions and shared `documentation/fit.py` collection: captures are skipped, failures retain their target IDs and existing evidence, and overflowing rich layouts do not stop collection. Plain authored parts text is measured by the diagnostic collector only. Exports do not run that collector; PDF/DOCX retain their existing refusal behavior and messages, with the additive rich-overflow reason field.
- Added `tests/test_documentation_page_setup.py` covering presets, geometry, migration/backups/revisions, four routes, undo/redo, refusal without writes, fit collection, paper exports, capture staleness and identity compatibility against commit `8ac3838`. Updated explicit scene-version expectations in existing tests and one smoke assertion.
- No client edits were needed: page surfaces, generated frames, object sizes and thumbnail aspects already use `publicationLayout`. No static file changed, so no cache-version bump is needed. Baseline JSON files are untouched.

TESTS

- Static checks only: AST parsing passed for all 28 changed/new Python files; `git diff --check` passed.
- Changed/new files use LF; added server lines are ASCII; the server UTF-8 BOM is preserved.
- No pytest, application execution, exports, browser, baseline checks or commits were run.

NOT RUN

Claude must run these in the equipped environment with the hidden-process launcher:

```text
python -m pytest -q tests/test_documentation_page_setup.py
python -m pytest -q tests/test_documentation_objects.py tests/test_documentation_transactions.py tests/test_documentation_change_undo.py tests/test_documentation_provenance.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_rich_text.py tests/test_documentation_rich_blocks.py tests/test_documentation_rich_exports.py tests/test_documentation_export_matrix.py
python -m pytest -q tests/test_parts_manual.py tests/test_operations_manual_workspace.py tests/test_specification_sheet_workflow.py tests/test_work_instruction_workflow.py tests/test_documentation_editor_smoke.py tests/test_codex_documentation_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
```

Expected baseline change: only the scene schema number in the synthetic table scene (7 to 8). Without a setup, compiled-document fingerprints, existing scene/figure revisions, page sizes, exported text and undo facts should remain unchanged. Review the actual baseline diff before promotion. The new PDF byte and DOCX XML comparisons are written but unrun. No P4b smoke was added; that belongs to P4b-2.

DEVIATIONS

- No document type was deferred. No page-setup control, Sage operation, export-matrix axis or smoke phase was added.
- DOCX remains a flow document: its existing growing text boxes are preserved, so PDF frame-height refusals are not imposed on DOCX. Its own column-width failures use the unified overflow shape. This preserves the existing growing-cell compatibility test.

OPEN QUESTIONS

- Runtime acceptance is pending for all four preset compilers, candidate-fit refusals, pagination/contents, capture invalidation and PDF/DOCX geometry. No rendered fidelity measurements are claimed.
- The supervisor measured existing omissions in parts PDFs and clipped work-instruction text, plus an operations contents finding. These remain diagnostic findings and are deferred to the fidelity round. They no longer block exports or unchanged/better page setups.


## P4b-1 round 2

CHANGED

- `documentation/fit.py`: added pure `new_failures(current, candidate)`. Identity is (targetId, reason), independent of pagination; only new findings or an excess-height increase above 4 pt over the largest current excess block the command. Findings without comparable measurements block only when new.
- `server.py` and `parts_manual/documentation.py`: compile and measure both scenes under the existing write lock. Candidate compiler exceptions become `layout_overflow` with the compiler message and no targets. Nothing is written on refusal. The model, schema and geometry are retained.
- The three PDF builders no longer run an export fit pre-pass. The collector's export flag and the extra DOCX preflight were removed. Rich overflow details retain all previous keys and gain `reason`; the three legacy refusal messages, glyph checks and rotation checks are preserved. The existing `8ac3838` byte/XML comparisons remain in the tests.
- The operations compiler applies its orphan-continuation assertion only to identity geometry; the bounds assertion still runs for every geometry. All four compilers add capture page size only for nonidentity geometry. Parts/specification Letter therefore retain their design figure revisions and captures.
- Generated fit attribution now identifies the actual drawn element. Parts headings, cover fields, footer fields, control/history rows, contents entries, group entries and BOM/index cells receive independent targets, using stable IDs where available. Operations headers/footers and specification slots also have explicit targets. No old frame, rectangle, type size or fitting limit was changed; `_fit_text` is unchanged.
- Reworked `test_documentation_page_setup.py`: corrected rounding and fixtures, added the differential-fit cases, both presets on all real document types, immutable-history-aware undo comparisons, fresh captures through the real artifact stores, PDF/DOCX paper sizes, contents/BOM checks, identity-capture retention, candidate compiler refusals, attribution, absent-scene answers and export-prepass prohibition. No readiness check is patched away in the real-document export tests.

Geometry audit (work instructions and specification; no additional geometry mutation was needed):

| Key | Treatment and reason |
| --- | --- |
| `layoutBlocks[].frame.x/y/width/height` | Stretched per axis, including work-instruction benchmark/action/legend frames and specification feature cards. |
| `rowHeights[]` | Stretched vertically: these are fixed row allocations in page points. Row minimums and typography remain the builders' own. |
| `columnGap` | Stretched horizontally: it positions columns in the page frame. |
| Specification `columnWidths[]` | Unchanged: normalized shares (0.58/0.42), not point widths. The containing frame stretches. |
| `columns`, `itemNumber`, row/item order and counts | Unchanged: counts or semantic identifiers, not page dimensions. |
| `fontSize`, `style.fontSize`, `style.lineHeight`, `style.fontWeight` | Unchanged: type metrics/weight, explicitly excluded from stretch. |
| Nested row/item/cell frames, standalone column positions or block heights | Neither compiler emits them. The new inventory test checks this; all current point rectangles are the block `frame`. No block padding/radius fields were found. |
| `renderRequest.frame`, `image.targetAspectRatio` | Frame stretched; aspect recomputed from the resulting image area, retaining the existing 18 pt caption reservation where applicable. |
| `image.minimumWidthPx/minimumHeightPx`, captured `widthPx/heightPx`, occupancy limits/tolerances | Unchanged: pixel-resolution/quality rules or normalized fractions, not publication points. |
| CAD camera/explode/translation values and authored-object frames | Unchanged: CAD coordinates or page fractions; authored frames already use the actual page size. |

Page-setup answer audit:

| Answer functions | Scene supplied to options |
| --- | --- |
| `operations_manual_documentation_scene_command`, `_operations_manual_documentation_history` (undo/redo) | Full repository `apply_command` / `move_history` result, including `scene`. |
| `work_instructions_documentation_scene_command`, `_work_instructions_documentation_history` (undo/redo) | Full repository result, including `scene`. |
| `specification_sheet_documentation_scene_command`, `_specification_sheet_documentation_history` (undo/redo) | Full scene-repository result, including `scene`; these are not slot-store history answers. |
| `parts_manual_documentation_scene_command`, `_parts_manual_documentation_history` (undo/redo) | Full repository result, including `scene`. |

The helper now uses `loaded.get("scene") or {}`; a partial/receipt-only answer gets design options with `current: null`. The four scene reads also expose options through `_documentation_editor_read` on both its normal and early-return paths, from their loaded scene.

TESTS

- Static only: AST parsing and pytest parameter/signature checks passed for 28 changed/new Python files; `git diff --check` passed. LF, server ASCII additions and its UTF-8 BOM checked.
- Supervisor-provided round-1 results: 48 passed / 18 failed; both baselines blocked by the withdrawn export fit pass. Those are prior results, not results for this revision.
- No pytest, application, capture, export, browser or baseline execution by the builder. No commits.

NOT RUN

Run with the hidden-process launcher in the supervisor environment:

```text
python -m pytest -q tests/test_documentation_page_setup.py
python -m pytest -q tests/test_documentation_rich_exports.py tests/test_documentation_rich_blocks.py tests/test_documentation_tables.py tests/test_documentation_export_matrix.py tests/test_documentation_objects.py tests/test_documentation_refresh.py tests/test_documentation_transactions.py tests/test_documentation_change_undo.py
python -m pytest -q tests/test_parts_manual.py tests/test_operations_manual_workspace.py tests/test_specification_sheet_workflow.py tests/test_work_instruction_workflow.py tests/test_documentation_editor_smoke.py tests/test_codex_documentation_tools.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
```

Expected baseline difference: only the synthetic table scene's schema number. Baseline JSON is untouched.

DEVIATIONS

- The revised supervisor decisions replace the original absolute fit/export gate and capture condition. No document type is deferred; no client, Sage operation or smoke-phase change was added.
- Undo tests compare restored scene publication fields and the entire compiled document except `documentRevision`/`documentationSceneRevision`: the immutable undo journal necessarily produces new revision strings. Journal metadata is not represented as byte-for-byte restoration.
- Draft captures use 1200 x 900 PNGs through the artifact store. Parts uses its existing 2400 x 1800 technical-picture fixture and validated balloon manifests to satisfy its stricter capture QA.

OPEN QUESTIONS

- Runtime acceptance remains pending: real preset acceptance/clearing, capture retention/staleness, export byte/XML equality and both baselines. No runtime or visual success is claimed for this revision.
- The supervisor's measured generator omissions remain for the fidelity round; this revision diagnoses them without correcting their geometry or blocking legacy exports.

## P4b-1 supervisor gate (Claude, 2026-11-12)

### What round 1 did on the real documents, and the decisions that replaced it

Round 1 ran the fit report before every export and refused on any finding. On the four real MMLE documents:

| Document | Design page | Letter | A4 |
| --- | --- | --- | --- |
| Parts manual | 7 findings | refused (the same 7) | refused (the same 7) |
| Operations manual | 1 finding | 422, orphan continuation page | 422, orphan continuation page |
| Work instructions | 1 finding | refused (that 1) | refused (that 1) |
| Specification sheet | 0 | accepted | accepted |

Every export of the first three was refused, with or without a page setup. The findings themselves are right
(see "Measured and left"), so the report stays and its use changed:

1. Exports do not run the report. They refuse what they refused at 8ac3838, cost one build, and give the same
   bytes without a page setup (`test_no_setup_pdf_bytes_equal_committed_caller` and its DOCX twin).
2. `set_page_setup` compares the report of the publication as it is with the report on the new page and refuses
   only what is new or more than 4 pt worse (`fit.new_failures`, key = target and reason).
3. A candidate the compiler cannot lay out is refused as `layout_overflow` with the compiler's reason.
4. The orphan-continuation rule applies to the design page only.
5. The page size enters a figure's revision only when the page really changes (Letter on a parts manual or a
   specification sheet keeps every capture).

### What I changed after round 2

- `server.py` `_documentation_page_setup_check`: when the publication already has a page setup, the findings of
  its design page count as known too, for generated content only. Without this the operations manual could be
  put on Letter and not taken back: its contents block is 5 pt over its frame on the design page and fits on
  Letter, so clearing the setup was "new". Authored objects are still judged against the current page alone
  (their author can change them). Test `test_old_findings_of_the_design_page_do_not_block_another_paper_or_the_way_back`.
- `operations_manual/flow.py` `_html_width`: on a stretched page, text the exporter draws as HTML (list items,
  figure keys) is wrapped with the renderer's real need. Measured: a one-line HTML box needs the Helvetica width
  plus 2.00 pt at 7.2, 7.8 and 9.4 pt, and a label or quantity is drawn in bold. On A4 item 5 of "10.1 Charging
  Preparation" was 715.77 pt wide in a 716.67 pt column: the layout kept one row, the renderer wrapped, and the
  export of the whole manual was refused. The design page keeps its estimate, so no baseline moves. The figure
  key estimate also takes the 27 pt the exporter draws a keyed item in (it has always taken 23). Tests
  `test_html_drawn_items_keep_the_renderers_need_on_a_stretched_page`,
  `test_the_renderers_need_is_what_the_estimate_reserves`.
- `server.py` `_documentation_prepare_scene_command`: an `aspectLock` the request did not state is dropped. The
  body model filled None and `set_object_frame` through the command route was refused "aspectLock must be a
  boolean" (the page and Sage use the objects route, which was not affected).
- The refusal for a compiler error names the compiler's findings (the parts validation error's text is a fixed
  sentence).
- `docs/documentation-editor-reports/baseline/expected.json`: `table.scene` only. Proof: the whole synthetic
  baseline, collected with the scene's schema number put back to 7, equals the committed file.

### Results on the real documents (final code)

Every preset of every type is accepted and undone exactly: parts 18 -> 18 pages (Letter is the design page),
operations 33 -> 32 on Letter and 32 on A4, work instructions 20 -> 20, specification 1 -> 1. The A4 exports
with placeholder captures were rendered and read page by page (cover, control, contents, a list page, a figure
page, a table page of each): bands, footers, tables, lists and figure frames sit where they should, and the
list item above wraps to two lines.

### Gates

- New tests `tests/test_documentation_page_setup.py`: 118 passed.
- Focused suite: 1853 passed.
- Both baseline checks exit 0 (synthetic after the one-value promotion; local MMLE unchanged).
- Smokes (DOC_SMOKE_SLOW=4): P4a 475/475, P3b 169/169, P3a 194/194, P2b 36/36, P2a 23/23, P1a 27/27,
  P1b 46/46, P1c 35/35. The first P3a run ended after 119 passed checks on a dropped connection of the test's
  own request (`read ECONNRESET` on a scene read; no server error in the log); the rerun passed.
- Documentation suites: 1910 passed and the 1 known failure
  (`test_source_ids_references_and_local_hashes_are_closed`). Node: 475/475 and 5/5.
- Wide suites: 170 failed, 9 errors, 3852 passed, 68 skipped = the same 179 known IDs, nothing new.

### Measured and left (for the fidelity round, where the baselines change on purpose)

`insert_textbox` writes nothing when the text does not fit. On the design page today:

- Parts PDF: the 18 pt body headings "DOCUMENT CONTROL" (box 28 pt), "TABLE OF CONTENTS" and the parts index
  heading (boxes 30 pt) need 30.3 pt and are not in the PDF; the cover's assembly line needs 53.3 pt in a 50 pt
  box. The page shows all of them.
- Work instructions: one block of `page-wi-operation-wi-lift-03d` needs 44 pt in 34 pt and loses its last line.
- Operations manual: the contents rows are 5 pt over the block's frame (nothing is lost).
- The flow engine's estimate for HTML-drawn text is 2 pt (and the bold part) optimistic on the design page too;
  it shows only when a line ends within that distance of its column.

### Notes for later rounds

- P4b-2: the Page Setup control, Sage's operation, smoke phase P4b. P4b-3: the export matrix axis, the omissions
  above, the operations DOCX header band (carried), Word/LibreOffice.
- Decision against the plan's wording: presets exist in the design orientation only, and margins are the
  preset's (the plan names portrait/landscape and margins in points). The other orientation needs a layout
  planner per type; it is not in this release.
- `set_page_setup` compiles and measures up to three times (current, design, candidate): about 1 s each on the
  operations manual. P5a if it shows.
- P5a: the command route and the objects route differ in how they read an unstated field; one reader would do.
