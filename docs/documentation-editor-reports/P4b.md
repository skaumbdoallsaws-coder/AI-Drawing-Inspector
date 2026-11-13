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

## P4b-2

### CHANGED

- `static/index.html` and new `static/documentation_page_setup_core.js`: Page Setup in the first ribbon group, using only advertised presets and computed unit labels. Current choices are marked; commands, object batches, crop mode and rich editing disable the control. Dispatch preserves null, addresses the publication, and reports success. Fit refusals name up to three blockers from the loaded document, focus the first page/object and retain the current mark. The new script uses `?v=20261112-p4b-2`.
- `documentation_tools.py`, `documentation/commands.py`, `documentation/targets.py`, `parts_manual/documentation.py`, `server.py`: additive reads and one standalone `set_page_setup` operation in the existing tool. The scene reducer and existing fit callback run under the scene lock through the receipt-bearing batch transaction. The read-bound hash includes the scene edit epoch; retries retain their original binding and result. Receipts retain setup, page counts and capture invalidation; refusals add page numbers/titles. Specification changes use the existing sheet completion notification.
- `tests/test_documentation_page_setup.py`, `tests/test_codex_documentation_tools.py`, new `tests/documentation_page_setup.test.cjs`: schema/pin, real reads/writes, mixed requests, unsupported orientation, stale binding, capture identity, retries, named undo, scene-versus-slot revisions, labels and refusal summaries. Read-only/assisted inventories were reviewed; tool names are unchanged.
- `tests/smoke_documentation_editor.py`: registered P4b and added `run_p4b`; earlier phase bodies stay unchanged. Checks cover four menus; paper/surface/rail/block/object geometry; capture gates and PDF sizes; three page images at device scales 1 and 2; history/reopen; named refusal; capture reuse; work-instruction order; Sage change/undo via the existing review poll. Sticky checks, `T(...)` waits and saved evidence follow the harness contract. Only the checked 409 page-setup refusal is added to expected browser failures.
- No compiler, exporter, layout rectangle, baseline, scene schema, tool name or capture implementation changed.

### Page-size audit (decision 3)

- `_documentationPublicationLayout` / `_documentationPageSize`: already read the current payload on use; fallbacks unchanged.
- `_documentationRenderDocumentObjects`, `_documentationObjectSize`, `_documentationPageElementRect`, drag/resize/nudge/crop callers: already use current page dimensions. Fractions and geometry formulas unchanged; paper selection is disabled during object batches/crop.
- `_documentationRenderOperationsPublicationPage` (operations/work/specification) and `_documentationRenderPublicationPage` (parts): surface dimensions and generated frames/regions already use the server layout. Cover chrome reads the current size. No fallback changed.
- `_documentationSizePageCanvas`: already computes fit zoom from the layout; now sets the surface aspect property too. `_documentationUpdatePayload` invokes it after drawing, including history and Sage reloads.
- Thumbnail clones and rail aspect/scale already use `_documentationPageSize`. The live-image thumbnail cache is now cleared on a size change.
- `partsManualDocumentationGeneration` cached page count and revealed IDs could survive repagination. A paper-size change now resets them to the returned pages; active-page fallback follows that list.
- Ribbon choices synchronize from current options, including refusals/history. Newly available controls and paper changes rebuild the ribbon. Global figure refresh recognizes the publication target even when the active page changed.
- Audited `static/documentation_*.js`: no publication dimensions are cached there. Object geometry receives page size from callers; rich/search/review adapters have no design-page dimensions. Review-dialog CSS and Unicode range numbers are unrelated.

### TESTS

Static checks only, as requested: Python AST parsing passed for all 8 changed Python files; JavaScript syntax passed for the new core, its Node test and all 4 inline scripts in index.html; `git diff --check` passed. Changed files have LF endings; the server BOM is retained; added server/index lines are ASCII.

### NOT RUN

Claude must run:

```text
python -m pytest tests/test_documentation_page_setup.py tests/test_documentation_transactions.py tests/test_documentation_change_undo.py tests/test_documentation_objects.py tests/test_codex_documentation_tools.py tests/test_codex_assisted_tools.py tests/test_codex_readonly_pilot.py
node --test tests/documentation_page_setup.test.cjs tests/documentation_objects.test.cjs tests/documentation_rich_text.test.cjs tests/documentation_tables.test.cjs tests/documentation_search.test.cjs tests/documentation_conflicts.test.cjs
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P4b
python tests/smoke_documentation_editor.py --phase P4a
python tests/smoke_documentation_editor.py --phase P3b
python tests/smoke_documentation_editor.py --phase P3a
python tests/smoke_documentation_editor.py --phase P2b
python tests/smoke_documentation_editor.py --phase P2a
python tests/smoke_documentation_editor.py --phase P1c
python tests/smoke_documentation_editor.py --phase P1b
python tests/smoke_documentation_editor.py --phase P1a
python -m pytest tests -k documentation
python -m pytest tests
```

Use `DOC_SMOKE_SLOW=1` on the idle gate machine for the 25-minute budget. No pytest, Node test execution, browser run, export rendering, baseline run or live Sage inference ran here. Runtime results and duration are unverified. No baseline promotion is expected.

### DEVIATIONS

- Reads also expose `pageSetupRevision`, documented as the operation's expectedRevision. Specification reads otherwise carry the slot-store revision while page setup belongs to the scene; existing revisions are preserved.
- Export already auto-captures pending figures. The smoke checks the pre-capture refusal through the export endpoint, then clicks Capture All and exports through the ribbon; export behavior is unchanged.
- The specification smoke takes a design capture before A4 so returning to identity Letter can prove reuse of a real stored capture without a capture POST. The parts preservation check takes one design figure capture (not Capture All) so its ready-capture assertion is non-vacuous in the empty isolated artifact store. Operations likewise takes one design capture to prove stale rather than merely missing after A4.
- The provider-free tool helper has no chat-completion event. The smoke opens the real Review pane and waits for its existing revision poll, with no test reload or app-function redraw.
- DPI comparisons use P4a-2's eight-level RGB tolerance on homogeneous interior patches and save both images. Antialiased edges are excluded; this is not whole-image equality or the deferred export matrix.

### OPEN QUESTIONS

Supervisor runtime validation remains required, especially the 25-minute budget, Capture All timing, DPI samples and specification capture reuse. The recorded generator omissions and operations DOCX header band remain for P4b-3.

## P4b-2 supervisor gate (Claude, 2026-11-12)

### Review

The client change is small because the page already read the page size from `publicationLayout.page` at use:
the menu, the dispatch, the refusal and three resets when the size changes (thumbnail cache, revealed pages,
ribbon). Sage's operation goes through the scene's own command path with the fit check of P4b-1 under the scene
lock. No compiler, exporter, rectangle or baseline changed (both baseline checks exit 0 without a promotion).

### What I changed

- `static/index.html` `_documentationPageSetupItems`: the paper in force was both marked and disabled, so it
  read as an unavailable choice. It is now the active entry and enabled (choosing it does nothing).

### What I looked at in the real browser (smoke screenshots)

- The menu on each of the four documents: heading "Paper", "Design page (960 x 540 pt)", "Letter landscape
  (11 x 8.5 in)", "A4 landscape (297 x 210 mm)" (portrait for the specification sheet).
- The refusal: the status line "A4 landscape was not applied: 1 item does not fit (Page 4: Paper fit).", page 4
  active, the text box selected with its handles, the menu still on the design page.
- Page 4 of the operations manual on A4, page against PDF.

### Found in this gate, for P4b-3 (all exist on the design page today)

The smoke's picture comparison samples flat patches (bands, backgrounds); it does not compare where text
stands. Reading the two pictures of one page side by side shows three differences between the page and the PDF
of the operations manual:

- lists: the PDF gives each item its compiled row height (23 pt for one line); the page lays items out with CSS
  at 16.2 pt from item to item;
- the safety symbol: the PDF draws a notice as a blue circle "i" and hazards as a triangle; the page draws the
  red triangle for every word, NOTICE included;
- the header: the page shows the identity line above the title; the PDF header has the title only.

P4b-3 makes the words of every page equal to the words of its PDF page and fixes these three with the text the
PDFs drop (see the P4b-1 gate).

### Gates

- New and changed tests (page setup, tool inventories): 268 passed. Node `documentation_page_setup.test.cjs` 2/2.
- Focused suite: 1866 passed.
- Both baseline checks exit 0, no promotion.
- Smokes (DOC_SMOKE_SLOW=4): P4b 76/76 (twice: before and after my change; 618 s and 676 s at factor 2 and 4),
  P4a 475/475, P3b 169/169, P3a 194/194, P2b 36/36, P2a 23/23, P1a 27/27, P1b 46/46, P1c 35/35.
- Documentation suites: 1923 passed and the 1 known failure. Node: 477/477 and 5/5.
- Wide suites: 170 failed, 9 errors, 3852 passed, 68 skipped = the same 179 known IDs, nothing new. (The first
  run of all four parts hit the 560 s limit while the machine was busy with other work; the rerun with a longer
  limit completed.)

### Notes for later rounds

- The gate machine: when other applications are busy the suites run at half speed or less (the documentation
  suites took 64 minutes instead of 28). The wide parts need a limit above 560 s then (`wide-part-long.sh`).
- P5a: `set_page_setup` from Sage compiles and measures as the page's command does (up to three times).

## P4b-3

### CHANGED

- **parts_manual/layout.py, parts_manual/pdf.py:** the cover document-control rectangle is 56 pt high (was 50); the 18 pt body-heading rectangles are 32 pt high (were 28 for Document Control and 30 for Contents/Parts Index). Top edges, fonts, sizes and neighbouring rows stay in place. The additional height also fits the stretched A4 rectangles. No fitting threshold or shrink rule changed.
- **work_instructions/document.py:** the benchmark operation's parts list reserves max(34, sum(rowHeights)). The measured eight-item page gets 44 pt, up 10. Its following safety notice moves from y=450 to y=460, retaining its 46 pt height and a 4 pt gap after the list. This is a row-count rule, not a page-ID exception; other frames stay in place.
- **operations_manual/document.py:** contents frames reserve whole rows of at least 18 pt within the content rectangle. Additional contents pages are allocated before body pagination so section references follow them. The real 19-entry design contents frame becomes 342 pt (was 330), with one contents page and unchanged 18 pt row positions. The design-page HTML measurement estimate is untouched.
- **New documentation/safety.py:** one copy of the existing PDF signal-word semantics. Operations and WI compilers attach safetySymbol; PDF drawing imports the table and the canvas consumes the compiled kind/color. Notice is the blue information circle; hazards retain their PDF colors. SVG dimensions and separate triangle rules follow the PDF. The redundant canvas signal label below the symbol is removed; the copy still begins with the signal.
- **static/index.html:** lists use compiled row heights, column gaps and text sizes, with text at the top and no additional CSS row gap. Unmarked rows use one text column. Quantity labels use the PDF's parenthesized form. No external static JavaScript file changed, so no script URL version changed.
- **operations_manual/exports.py, work_instructions/exports.py:** each non-cover operations/WI PDF header gains the identity line, 6.6 pt Helvetica, #879fac, top 7 pt, right inset 28 pt; the existing title stays. DOCX body clearance derives from the page-anchored band; header content is unchanged. The operations cache gains publicationFidelityVersion=1 so older cached PDF/DOCX files rebuild. DOCX renderer pins change to operations-docx-fidelity-v6 and work-instructions-docx-fidelity-v4.
- **Tests:** real fit reports must be empty for all four types on design/Letter/A4. Added contents continuation/numbering, safety semantics, WI allocation and DOCX clearance checks. The export matrix covers every supported paper, authored text/rich/table/image/shape, independent CAD placement with real captures, DOCX page dimensions, and A4 glyph/overflow/missing/stale-capture refusals. Unsupported DOCX types remain explicit.
- **New tests/documentation_fidelity_support.py and compatibility tests:** old callers still run. Existing glyph positions/fonts/sizes/colors, drawings, images and links must stay; only named added text is accepted. Native DOCX XML permits only the new body top margin. Schema-1 typography still checks its analytical baseline/decoration changes, separately accounting for the new header/heading paint sequence. Real MMLE comparisons exercise 8ac3838, including its old 50 pt cover contract; compiler-frame tests pin the WI notice move separately.
- **tests/smoke_documentation_editor.py:** run_p4b_words follows run_p4b. It checks every page of the four design publications and operations on A4, reuses valid captures, exports through the workspace and activates each page once. Visible text-node ranges within the publication surface supply whitespace-normalized word multisets. UI controls are excluded by element. Mismatches save counts, missing/extra words, fragments and both PNGs. The added part records its six-minute budget; earlier smoke bodies are unchanged.

### TESTS

Static checks only: Python AST parsing passed for 15 changed/new Python files; JavaScript syntax passed for all four executable inline scripts and the word-measurement script; git diff --check passed. LF endings and ASCII additions in index.html were checked; server.py is untouched.

No pytest, Node test, browser, PDF renderer, Word, baseline or runtime smoke ran here. Runtime results and durations are unverified.

### NOT RUN

Claude must run:

    python -m pytest tests/test_documentation_page_setup.py tests/test_documentation_export_matrix.py tests/test_documentation_rich_exports.py tests/test_documentation_typography.py tests/test_documentation_tables.py tests/test_documentation_rich_blocks.py tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
    node --test tests/documentation_page_setup.test.cjs tests/documentation_objects.test.cjs tests/documentation_rich_text.test.cjs tests/documentation_tables.test.cjs
    python tools/documentation_baseline.py --check
    python tools/documentation_baseline.py --local --check
    python tests/smoke_documentation_editor.py --phase P4b
    python tests/smoke_documentation_editor.py --phase P4a
    python tests/smoke_documentation_editor.py --phase P3b
    python tests/smoke_documentation_editor.py --phase P3a
    python tests/smoke_documentation_editor.py --phase P2b
    python tests/smoke_documentation_editor.py --phase P2a
    python tests/smoke_documentation_editor.py --phase P1c
    python tests/smoke_documentation_editor.py --phase P1b
    python tests/smoke_documentation_editor.py --phase P1a
    python -m pytest tests -k documentation
    python -m pytest tests

Use DOC_SMOKE_SLOW=1 on an idle machine for the added six-minute budget. Review each word mismatch and its two images. Open operations and WI DOCX exports for design/Letter/A4 in Word and LibreOffice; confirm the first heading clears the band. XML assertions do not replace rendering.

### Expected baseline changes

Baseline JSON files are untouched; review and promotion belong to the supervisor.

- Parts compiled fingerprints: the cover document-control height. PDF text hashes/character counts gain cover metadata and Document Control, Contents and Parts Index headings (five measured body-heading pages). Existing text and row positions remain guarded against the old caller.
- Operations compiled fingerprints: the contents frame and safetySymbol data. The real design publication keeps one contents page and its body page numbers/count. Every non-cover PDF page gains the identity line, changing its text hash/character count. The real 19-entry contents positions stay.
- WI compiled fingerprints: safetySymbol and row-derived parts/notice frames. The measured parts frame grows 10 pt and its notice moves down 10 pt. Every non-cover PDF gains the identity line. The final parts row is explicitly checked in extraction. No design text-flow estimate changed.
- Operations/WI DOCX section top margins and renderer metadata change; native paragraph text stays. Word pagination can change because the body starts below the band.
- Specification/inspection geometry and text stay. Scene schema stays 8; stored values and scene revisions are untouched; no pageSetup key appears on read. Real design page counts/sizes are expected to stay. Compiled document revisions can change with the compiler fields; capture geometry is unchanged.

### Word-comparison exception table (decision 7)

| Exception | Allowed count | Reason |
| --- | ---: | --- |
| None | 0 | No publication word is suppressed. UI controls/handles are excluded by element, not by word. |

The smoke's single source is P4B_WORD_EXCEPTIONS, initially empty. It prints the actual table and writes p4b-words.json and report.p4bWordExceptions. Actual equality/counts remain unmeasured; an unexpected difference fails instead of becoming an exception.

### DOCX header numbers (decision 9)

Band bottom is y plus height. Body top is 12 pt below that. The header paragraph inset is bounded by band height minus the 3 pt accent and 14 pt brand-line allowance, capped at the existing 12 pt; it remains 12 pt for all three pages. Header text and shapes are unchanged.

| Operations and WI page | Band bottom, pt | Requested body top, pt | Stored Word top margin, pt | Header distance, pt |
| --- | ---: | ---: | ---: | ---: |
| Design 960 x 540 | 56 | 68 | 68 | 12 |
| Letter landscape | 63.4667 | 75.4667 | 75.45 | 12 |
| A4 landscape | 61.7327 | 73.7327 | 73.75 | 12 |

Word margins round to twentieths of a point. These are expected geometry/XML values; Word rendering is unverified here.

### DEVIATIONS

- The list audit also found canvas quantities without the PDF's parentheses and synthetic numbers on unmarked list styles. Both are corrected on the canvas for word equality; the PDF list renderer is unchanged.
- The separate canvas-only notice label was removed; its signal remains first in the copy. No signal-word list is duplicated in JavaScript.
- No margins/orientation UI, new page-setup operation, design-page text reflow, baseline edit or relaxed relative-fit rule was introduced. DOCX body clearance is the requested exception to unchanged margins.

### OPEN QUESTIONS

Supervisor runtime verification must establish empty fit reports, full word equality and the added smoke's six-minute budget. Word/LibreOffice must confirm header clearance on all three sizes. There are no pre-authorized word exceptions: a further omission needs a named fix or an explicitly reviewed counted exception, never a word blacklist.


## P4b-3 round 2

### CHANGED

- **static/index.html:** draft banners now use the notice renderer, compiled safetySymbol and signal word; removed their pink box/red-text styling. Operations/WI cover footers use statusLabel with the PDF's DRAFT fallback. Generated table headers use CSS capitals; body cells and authored table headers keep their text. Parts default non-figure header titles use capitals; an explicit override, including an empty value, wins unchanged.
- **static/documentation_publication_core.js, tests/documentation_publication.test.cjs:** pure parts-heading and width-fitting rules, with Node tests. The fitting formula matches parts PDF _fit_text, including the 0.96 allowance and 4.5 pt floor, measured with the page's own font. The new script URL is versioned 20261112-p4b-3-r2.
- **Parts canvas:** BOM cells and group names wrap at the fitted size. The same width-fitting rule covers parts-index entries, document-control values and the parts header/footer fields that the PDF fits. Numeric BOM cells use the PDF's 3 pt side inset. Bold measurement uses weight 700. Cover metadata uses a 1.374 line-height at 9.2 pt (12.6408 pt pitch; four lines occupy 50.5632 pt inside the 56 pt frame). A missing revision no longer invents a cover line; a missing parts-index number no longer invents "Not specified". These match the PDF branches. Stored values are unchanged.
- **tests/smoke_documentation_editor.py:** both word multisets use NFKC. A wrapped text node keeps its original word boundaries; separate blocks/cells and actual inline gaps remain boundaries. SVG text elements are separate boxes. Open specification input hints are excluded by their UI element, not their words. The exception table remains empty.
- **Capture measurement:** part 1 pictures and part 2 words share the accepted-capture gate: current image, decoded pixels, ready class and ready SVG overlay. The product puts the opaque white-backed image at z-index 20 and accepted SVG at 21, above the sibling live viewer's stacking context (container-type: inline-size). The check verifies those computed conditions and that live text lies under the image before excluding that occluded subtree. It does not blacklist balloon classes or use hit testing through pointer-events:none. A failed paint contract is reported immediately after readiness. Evidence records the contract and any uncovered live labels.
- **tests/documentation_paper_support.py; page-setup/export-matrix tests:** module-owned caches key unchanged real publications by (route, paper), and bytes by format too. Every document/report return is a deep copy; real captures remain in module temporary directories. No readiness check is patched. Page-setup fit/semantics/allocation/geometry/pagination/size/oracle tests share compiled documents; size and old-caller checks share current export bytes. Matrix cases share the pristine paper publication, captures and baseline export; modified-object exports and refusal attempts still run separately. Stale-capture cases reuse only design captures; missing-capture cases still use an empty root. Stateful route, undo, retry and relative-fit cases remain fresh. A test guards cache copy isolation. No parameter case or assertion was removed.
- No compiler, PDF/DOCX exporter, server, baseline JSON or saved store was changed in this round. The supervisor's contents-count guard and revised legacy comparison tests are retained.

### Text audit (C)

This is a source comparison, not a claim that the new browser gate has passed.

| Place | PDF | Page before this round | Fixed / left with reason |
| --- | --- | --- | --- |
| Parts cover document control | Conditional revision/date; four 9.2 pt lines in 56 pt | 18 pt pitch clipped line four; invented missing revision | Fixed pitch and conditional revision. |
| Parts body header | Default non-figure title uppercase; override verbatim; width fitting | Mixed-case default; ellipsis | Fixed default rule and fitting; overrides preserved. |
| Parts BOM, including continuation pages | Whole cell text, width fit with 4.5 pt floor, wrap | One line and ellipsis | Fixed all four columns with the PDF rule. |
| Parts overview group index | Whole name fitted; number and figure/page reference | Name cut off | Fixed name fitting/wrap; references unchanged. |
| Parts document information and revision history | Uppercase labels, fitted values; revision lines as compiled | Labels/lines agree; values could ellipsize | Fixed value fitting; revision lines unchanged. |
| Parts contents and body headings | Explicit headings, FIGURE/TITLE/PAGE, compiled entries | Same words after round-1 PDF restoration | Unchanged; no ellipsis rule at these entries. |
| Parts number index | Fitted number/description/reference; empty missing number | Unfitted entries; synthetic missing-number text | Fixed fitting and empty fallback. |
| Operations/WI cover | Compiled kicker/title and statusLabel footer | Footer hardcoded DRAFT | Fixed footer; cover text unchanged. |
| Operations/WI headings, continuation headings, paragraphs | Compiled text/lines, then bounded frame drawing | Same text projection; browser soft wraps | Unchanged; smoke no longer invents spaces at a soft wrap. The design flow estimate stays unchanged. |
| Operations/WI generated tables/key-value tables | Header labels uppercased; cell values as typed | Mixed-case headers | CSS capitals only on generated, unedited headers. Authored tables are outside this selector. |
| Operations/WI lists, legends, contents | Compiled entries, row heights, marker/quantity rules | Round 1 aligned the marker/quantity text and row heights | Retained; no new PDF change. |
| Operations/WI note/status/draft banner | Symbol, signal, copy; no draft box | Draft banner omitted signal/symbol | Fixed draft branch and styling; existing compiled semantics suffice. |
| CAD captions and balloons | Caption and one balloon text set | Caption agrees; two overlay sets exist in DOM | Measurement now counts only the displayed set. Black/radius-13 accepted balloons versus blue/radius-10 PDF balloons remain untouched (B8). |
| Specification filled title/kicker/tagline/headings/features/caption/table | Filled slot text, bounded fitting; REVIEW footer | Same filled slot text; open-slot input prompts also visible | Filled rendering retained; input prompts excluded as UI elements. |
| Specification partially open table row / all-open feature section | Final PDF omits a row if either slot is open; suppresses features heading when all cards are open | Editor can still show a filled row label or section heading beside open inputs | Left and reported: hiding an entered value to satisfy the check would change editing semantics. No exception hides it. A product decision is needed for this editor-versus-final-PDF policy. |
| Header/footer overrides on operations/WI and specification | Some drawing branches use generated strings rather than page-element overrides | Page displays overrides verbatim | Left: honoring the author's text in those PDFs requires an exporter change, forbidden this round. |
| Authored plain/rich text and tables | Existing run drawing, header marks, native content | Existing static renderer | Unchanged; no forced capitalization on authored tables. |
| Review/conflict annotations | Format-specific marker and legend drawing | Existing provenance marker UI (including generated CSS text) | Left: this round's fresh word gate is not a proof of every annotated export mode; marker placement/legend differences require a separate exporter-aware audit. |

### Publication clipping audit (B6)

No -webkit-line-clamp was found in the publication styles. No external documentation_*.css or documentation_*.js file contains an ellipsis/clamp rule.

| Selector | PDF rule | Action |
| --- | --- | --- |
| .documentation-cover-chrome-footer-copy | Original-size textbox | Removed ellipsis/nowrap; allow wrap, retain the frame. |
| .documentation-page-header-meta / -title | Parts width fit; operations/specification original-size textboxes | Removed ellipsis/nowrap; parts additionally use the fitting helper. |
| .documentation-page-footer-left / -right | Parts left fitted; page number and other types original-size | Removed ellipsis/nowrap; fit parts left only. |
| .documentation-page-group-row strong | _fit_text at 7.8 pt bold | Fit and wrap, no ellipsis. |
| .documentation-page-bom th / td | _fit_text for every header/cell | Fit and wrap, no ellipsis; 4.5 pt floor retained. |
| .documentation-control-row strong / span | Fixed uppercase labels; fitted values | Removed ellipsis/nowrap; fit values. |
| Existing contenteditable rules for page text and BOM | Editing state, not export | Existing clip/wrap rules retained. |

Remaining ellipses in the documentation area belong to toolbar titles, page-rail labels, floating selection labels, and capture-takeover titles/stages. They are workspace UI, not publication content. Earlier manual-preview/proposal/occurrence-list ellipses are also outside the publication surface. No such UI word is suppressed by a word blacklist.

### TESTS

Static checks only: Python AST parsing passed for all 17 changed/new Python files in the pending round-1/round-2 tree; JavaScript syntax passed for all four executable inline scripts, the new core, its Node test and both capture/word scripts. The import-map block was excluded from executable-JavaScript parsing. git diff --check passed. Round-2 code files have LF endings and added index.html lines are ASCII. server.py is untouched.

No pytest, Node test execution, browser, renderer, baseline or smoke ran here. No runtime pass count or timing improvement is claimed.

### NOT RUN

Supervisor commands:

    node --test tests/documentation_publication.test.cjs
    python -m pytest tests/test_documentation_page_setup.py tests/test_documentation_export_matrix.py tests/test_documentation_rich_exports.py tests/test_documentation_typography.py tests/test_documentation_tables.py tests/test_documentation_rich_blocks.py tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
    python tests/smoke_documentation_editor.py --phase P4b
    python tools/documentation_baseline.py --check
    python tools/documentation_baseline.py --local --check
    python -m pytest tests -k documentation
    python -m pytest tests

Use DOC_SMOKE_SLOW=1 on an idle machine for the six-minute word-part budget; earlier phase commands remain listed in the round-1 report. Review words-*.json and both page images for any remaining counted difference. Baseline files remain supervisor-owned. This round adds no expected compiled-document, PDF or DOCX baseline delta beyond round 1; only canvas text and measurement change.

### DEVIATIONS

- The audit extends the requested BOM/group fitting to the other parts fields where the PDF already uses the same width-fit rule, and removes two synthetic missing-value differences. No PDF fitting threshold or type size was changed.
- A3/A4 add one computed-style/visibility inspection per page, not another capture or fixed sleep. Image/SVG readiness uses the existing 20-second bound. No timeout was lengthened. The six-minute budget remains unchanged but is unverified.
- Word exceptions: **none (allowed count 0)**. NFKC and excluding proven occluded text correct measurement; they are not publication exceptions. Open input prompts remain excluded by UI element.

### OPEN QUESTIONS

- Run the corrected word check to establish the remaining differences; do not treat this source audit as a browser pass. A ready capture that fails the paint contract must be investigated as a product/visibility difference, not given a longer wait.
- B8 remains with the product owner: accepted-capture balloon color/radius.
- Specification open-row/feature visibility and ignored generated header/footer overrides need the decisions described in the audit; neither is silently normalized away.
- Measure the cache speedup and smoke duration on the supervisor machine. Capture bytes, mutated outputs and all stateful command behavior still need their existing assertions.

## P4b-3 supervisor gate (Claude, 2026-11-12 to 13)

### What I ran and what it showed

Round 1: the eight test files Codex named, 1141 of 1148 passed. The 7 failures were older tests that still asked
for exports byte-equal to an earlier commit; I rewrote them (below). Smoke `--phase P4b`: part 1 passed except
one picture check; the new word check ran on every page of the four real documents (and the operations manual
on A4) and reported 97 pages. I read the saved pictures and words of the pages and sorted the findings:

- measurement: ligatures in the PDF's shaped text (NFKC on both sides), a line change inside one text node
  counted as a word boundary, two balloon label sets in the DOM (the live viewer's and the accepted capture's)
  both counted, one device-scale-2 picture taken while the figure still showed the live viewer;
- real, and old: draft banners (the PDF draws a notice with its signal word, the page drew a pink box without
  it), the cover footer's status (the page said DRAFT, the PDF the document's status label), table headers (the
  PDF in capitals), the parts header title on pages without a figure (capitals in the PDF), the parts cover's
  fourth control line cut off on the page, BOM descriptions and group names cut with an ellipsis on the page
  where the PDF fits and wraps the whole text.

Round 2 (brief `P4b-3-r2`) fixed all of these on the page side; no exporter changed. Smoke after round 2:
196 of 198 checks; the one page left (work instructions, stage 09) is the next point.

### What I changed

- `ai_inspector/operations_manual/document.py`: the build raises if the number of contents pages differs from
  the number the body was numbered for (a silent mismatch would misnumber every entry).
- `static/index.html` `.documentation-accepted-capture.ready`: a one-pixel white ring. The live viewer stays
  mounted under the accepted capture in the same box; on a zoomed page the box edges fall between pixels and one
  blended row of a live balloon label showed at the capture's top edge (seen at 5x on the stage 09 page).
- `tests/smoke_documentation_editor.py`: the paint contract judges the part of a live label that the viewer's
  own clipping layer lets through; that part must lie under the image (within the ring).
- `tests/test_documentation_typography.py` `assert_pdf_schema1_delta`: fonts and links are compared without PDF
  object numbers (they move when a page gains text); a page may gain only the built-in fonts of the additions.
- `tests/test_documentation_page_setup.py`: the parts layout comparison expects 56.0; the plain-text test compares
  with `assert_pdf_fidelity_delta`.
- `tests/test_documentation_rich_blocks.py`: the comparison with de5e171 is renamed and states what this round
  adds (the identity line; the body's top margin), everything else member by member as before.
- `tests/smoke_documentation_editor.py`: publishing the parts manual sends the browser to the PDF (one aborted
  GET); phase P4a classified that hand-off, phase P4b did not and counted it as an unexpected network failure.
  Same classification in both, exactly one per publish.
- `tests/documentation_editor_smoke_server.py`: the proof session of the smoke server lived 30 minutes; on a
  busy machine phase P4a runs longer and its last Sage call met a closed session (`codex_run_closed`). The
  session now lives two hours. Harness only.
- `tests/test_operations_manual_workspace.py`: the pinned page source held the constant DRAFT of the cover
  footer; it now pins the status label rule with DRAFT as the fallback.
- Baselines promoted after reading every changed value. Synthetic (19 values): the parts cover gains 109
  characters (the four control lines), the three body headings 17, 18 and 18; the compiled fingerprints of the
  parts document. Local (210 values): every operations page but the cover gains 56 characters and every
  work-instruction page but the cover 69: the identity line and its line end, nothing else; the compiled
  fingerprints of both documents (contents frame, safety symbol data, the work-instruction frames).

### DOCX in Word

Word (LibreOffice is not installed on this machine), the real operations manual and work instructions, design
page, Letter and A4, six files, rendered read-only to PDF and read page by page:

| Page | Band bottom, pt | First body text top in Word, pt (operations / work instructions) |
| --- | ---: | ---: |
| Design 960 x 540 | 56 | 72.0 / 68.4 |
| Letter landscape | 63.47 | 79.4 / 75.8 |
| A4 landscape | 61.73 | 77.7 / 74.1 |

Before this round the first heading stood at 48.6 pt, under the band. Word's pagination is its own (39 to 45
pages against 33 and 20 in the PDFs), as the plan expects.

### Measured and left

- Word puts the cover picture on a page of its own and on some page sizes leaves a blank page after it. The
  exporter of b3bcc7e did the same (blank pages 3 and 6 on the design page; now 3).
- The work-instruction DOCX footer says DRAFT where the PDF says the status label.
- The page's balloons over an accepted capture are black with a 13 pt radius; the PDF's are the theme blue with
  a 10 pt radius. Asked the product owner.
- From Codex's source audit, for decisions: the specification sheet shows a filled row label beside an open
  slot that the final PDF omits; some operations, work-instruction and specification PDF header and footer
  branches draw generated strings where the page shows an edited one; review and conflict markers were not
  covered by the word check (it runs on unmarked publications).
- The word check takes about 18 minutes at wait factor 4 on this machine (97 pages plus the A4 pass); its own
  budget is 6 minutes times the factor. It holds on a quiet machine and was overrun once when the machine
  stalled. Carried to P5a-2: activate pages faster.
- `_documentationFitPublicationText` reads and writes layout element by element (about 125 forced layouts on a
  parts BOM page per render). Carried to P5a-2 with the typing measurements.
- The work-instruction parts list of `page-wi-operation-wi-lift-03d` was never cut in the PDF: its fourth row was
  drawn 6 pt into the notice below. It now has its own height and the notice sits 10 pt lower.

### Gates

| Gate | Result |
| --- | --- |
| `documentation_baseline.py --check`, `--local --check` | 0, 0 (promoted values) |
| Smoke P4b | 198/198 (third run; the first counted the parts PDF download hand-off as a network failure, the second overran the word check's time budget while the machine stalled, 2666 s against 1440 s; every other check passed in both) |
| Smoke P4a | 475 of 475 (after the proof-session change; the first run stopped at check 271 on the closed session) |
| Smoke P3b, P3a, P2b, P2a, P1a, P1b, P1c | 169, 194, 36, 23, 27, 46, 35: all pass |
| Documentation suites | 1992 passed, 1 known failure (`test_source_ids_references_and_local_hashes_are_closed`); the first run had one more, the pinned cover-footer DRAFT source assertion, updated and rerun (27 of 27 in its file) |
| Node | 479 node:test cases in 7 files, 5 of 5 borrow-callout checks |
| Wide suites | the same 179 known failing IDs, none new, none gone |

Smoke durations varied between 20 and 57 minutes for the same phase and code during this gate; an old watcher
process of mine had been holding one processor core since the morning and is stopped.
