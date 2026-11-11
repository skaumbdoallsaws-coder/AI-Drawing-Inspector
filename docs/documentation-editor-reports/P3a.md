# P3a - narrative editing

## P3a-1

### CHANGED

- `rich_text.py` and new `rich_fonts.py`: schema 2 validation, canonical mark order, minimal-version writes, unchanged stored envelopes on reads, six list levels, and the shared font/metrics table. The 24 KiB and 512-node limits remain.
- `rich_layout.py` and `rich_docx.py`: run fonts/sizes, scripts, highlight, strike, paragraph alignment/indent/spacing/line height, and six-level numbering. PDF uses canvas vertical metrics and unions inline line boxes; styled hard breaks participate. Export cache versions advance.
- `documentation_rich_text.js`, core, CSS and `index.html`: static typography, mapped rich box fonts, explicit script/highlight styles, schema-2 read-only protection before mount and save, and bumped static URLs. Schema-1 canvas mark nesting remains. No extensions, ribbon controls or box-font options were added.
- `documentation_tools.py` and its schema inventory assertion accept versions 1/2 and describe the new bounds and minimal-version rule. Tool names remain unchanged; the readonly/assisted inventories do not pin the changed envelope.
- New `tests/test_documentation_typography.py`, updated rich-text/export/Node tests, and extended export comparisons cover the new fields. The compatibility oracle loads `49cdaed` rendering modules and exporter callers into isolated modules, verifies the old drawing/writing code ran, compares DOCX XML bytes, and computes permitted PDF vertical deltas. The existing export file's schema-1 vectors feed this oracle.
- `smoke_documentation_editor.py --phase P3a` authors three objects through Sage, checks reload/read-only behavior, measures canvas lines and glyph/highlight rectangles, exports through the UI, and changes one run size. P2b and P3a share canvas/export/download/text helpers. The smoke saves full/region images, PDF/DOCX artifacts, the 48 pt canvas/PDF pair, and strike measurements.

### TESTS

Static checks only, all passed:

- AST parsing of 11 changed/new Python files; no application imports or test execution.
- JavaScript syntax checks of the adapter, core, Node test file, and four inline scripts in index.html.
- `git diff --check`; LF checks; ASCII-only index.html additions; unchanged server.py UTF-8 BOM.

### NOT RUN

No pytest, Node tests, baselines, browser smoke, PDF/DOCX rendering or Word review ran. No visual artifacts or measured Chromium results were produced here.

Claude should run these through the existing hidden Windows launcher:

~~~text
python -m pytest -q tests/test_documentation_typography.py tests/test_documentation_rich_text.py tests/test_documentation_rich_exports.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_editor_smoke.py tests/test_documentation_conflicts_ui.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py
python -m pytest -q tests/test_parts_manual.py tests/test_specification_sheet_workflow.py tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
node --test tests/documentation*.test.cjs
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python tests/smoke_documentation_editor.py --phase P1c
python tests/smoke_documentation_editor.py --phase P2a
python tests/smoke_documentation_editor.py --phase P2b
python tests/smoke_documentation_editor.py --phase P3a
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
~~~

The compatibility oracle requires commit `49cdaed`. Word rendering remains with the user.

### DEVIATIONS

- Scope follows the supervisor's P3a-1 split. Named styles, wider eligibility, controls, search/replace, symbols and justification remain later work.
- Schema-2 CSS explicitly sets decoration thickness from the supplied table and disables underline ink skipping to match continuous PDF strokes. Native Chromium decoration placement still requires measurement.
- DOCX uses native `w:vertAlign`: Word chooses script size and offset, as authorized. Exact Word/canvas script geometry is not claimed.

### OPEN QUESTIONS

Chromium's actual line-through position and thickness are **unverified**, not inferred from the font table. The PDF currently uses position 0.2588 em above baseline and thickness 0.0498 em; the canvas specifies that thickness but uses native line-through placement. The smoke records both raster measurements in `p3a-comparison.json`. Underline placement, mixed-font content boxes, list-marker placement and Word layout also await the required real-app/Word review. No rendering rule is claimed proven exact before those gates pass.

The implementation is ready for supervisor review, not a shipping acceptance. No commit, branch/index mutation, network access, package installation or real-store access was performed.

## P3a-1 supervisor gate

Reviewed, fixed and gated by Claude on 2026-11-10. Codex's build ran static checks only; every run below was made
here, in the worktree, one heavy job at a time.

### Findings and fixes

1. Canvas line boxes are rounded by Blink. Smoke P3a first failed 33/39: its six canvas checks missed the 0.5 px
   glyph tolerance by up to 1.0 px. Chromium rounds each font's ascent and descent to whole pixels per size (glyph
   content boxes of 6, 11, 14, 27 and 53 px for Arial at 6, 9.5, 12, 24 and 48 px), keeps line heights in LayoutUnits
   (1/64 px) and floors the ascent-side half-leading. `line_box`, `layout_text` and `prepare_pdf_objects` take
   `canvas_rounding=True` to reproduce this, for measuring the real canvas only; the smoke compares lines, glyphs and
   highlight fragments with that model within 0.25 px. Exports stay exact: Blink rounds in device pixels, so any
   rounding would fit one display scale only.
2. Plain text boxes now use the canvas metrics too. The build kept them on the P2b metrics of the PDF's Helvetica
   program and on the P2b underline. The canvas draws plain and rich text with the same CSS and fonts, and the shared
   plain path (specification, operations, work instructions) has been unreleased since P2b-1; only y values move. The
   parts manual's legacy plain path is separate and unchanged. Two P2b assertions that pinned the glyph top at
   "frame top + 2" now pin the exact first baseline.
3. Decorations follow Chromium, measured (the build's open question). Chromium 141; Arial, Times New Roman and
   Courier New; 12 to 100 px; regular and bold; at device scale 1 and under the canvas's scale(0.985):
   - line-through is centred a third of the whole-pixel ascent above the baseline, as thick as the rounded CSS
     thickness;
   - an underline's top edge lies max(1, ceil(t/2)) px below the baseline, so its centre lies about one thickness
     below; t is the rounded CSS thickness for a length, and a tenth of the size for `auto`;
   - the fonts' own underline (post) and strikeout (OS/2) positions are not used.
   The PDF now centres strike at ascent / 3 above the baseline and an underline one thickness below it. Schema-2 runs
   use the font thicknesses their CSS sets. Schema-1 and plain text keep CSS `auto` on the canvas, so their underline
   is a tenth of the size: P2b's centre (0.1 x size) is kept and only its width changes (from max(.5, .04 x size)).
   Before, the PDF strike sat 1.6 px below the canvas at 48 px and 4.6 px below at 100 px. The unused position fields
   left the Python and JS font tables. The smoke's strike check now crops both rasters at known whole-pixel origins
   and measures each against its exact baseline: canvas -13.52 px (Blink model -14.0), PDF -14.54 px (model -14.48);
   thickness 2.00 and 2.44 px (models 2 and 2.39).
4. DOCX: in Word, an indented list item's text started at the list indent. The numbering level defines its own list
   tab at the list indent, and Word sends the text after the number to the first stop after it, before the
   paragraph's own stop. The paragraph now clears the level's stop. Word 16: "Level 6" moves from 275.33 to 293.33 pt,
   40 + 18 pt past level 5 as on the canvas; its marker stays at 262.01 pt.
5. DOCX: a justified box overrode a paragraph's own textAlign, which wins on the canvas and in the PDF.
   `content_model` keeps "justify" for the box (the PDF still lays it out flush left; justification is later work),
   and only that maps to `w:jc both`. New test.
6. Smoke: a highlight fragment that ends in hanging white space at a line end may end inside that space (Chromium's
   inline box covers part of a hanging space); its right edge may now fall anywhere in the hanging tail.

Accepted as built: the refusal order glyph, overflow, rotation; DOCX scripts through `w:vertAlign` (Word's own
scale and offset); schema-2 fields read-only in the editor, with the notice and no mount; the Node fixture change (the
schema-1 boundary now refuses paragraph attributes instead of stripping them, and the P2a editor loads no TextAlign
extension); minimal-version writes and stored envelopes on reads; the 49cdaed oracle (DOCX XML bytes equal; PDF equal
except the prescribed y and decoration moves, now with the `auto` underline rule).

### Visual review

- Canvas and PDF crops of the three smoke objects: mixed fonts and sizes on one line, highlight, strike, scripts, a
  link with a size, alignment, the six-level lists with level 6 indented, and the Georgia box in Times New Roman.
  They match.
- 48 pt side-by-side: glyphs, highlight and strike line up.
- Word 16 render of the smoke's DOCX (2 pages): the same content, with highlight as shading and Word's own script
  geometry; level 6 indented as on the canvas after fix 4.
- Editor: a schema-2 field shows "This formatting cannot be edited here yet." and mounts no editor.

### Numbers

- Focused suite: 932 passed. Rich text, typography and exports: 346 passed. Node: 40/40 (conflicts 18, rich
  text 22).
- Smokes: P3a 39/39, P2b 36/36, P2a 23/23, P1a 27/27, P1b 46/46, P1c 35/35.
- Both baseline checks exit 0; the reopened stores were unchanged.
- Documentation suites: 989 passed, plus the 1 pre-existing failure
  (`test_operations_manual_precoding_contracts.py::test_source_ids_references_and_local_hashes_are_closed`).
- Wide suites: 170 failed, 9 errors, 3851 passed: the base set, nothing new; the same 7 base failures pass.
- Chromium probes: line-through in 9 font/size cases at device scale 1 and 3 under scale(0.985); underline in 12
  cases with the CSS thickness and 30 with `auto`.
- Word 16: the smoke DOCX before and after fix 4, and a hand-patched copy that proved the tab fix first.

### Notes for later slices

- P3a-2, when it lifts the read-only guard: the editor must render with the same static CSS. An object is stored as
  schema 2 once it uses any schema-2 feature, and its underlines then switch from CSS `auto` (a tenth of the size) to
  the font thickness. Both exports follow the canvas either way, and at body sizes both paint 1 px, but decide in
  P3a-2 whether schema-2 CSS should keep `auto` underlines so that adding a strike never changes other runs.
- `canvas_rounding` models device scale 1, for measurement only. Keep the exports exact.
- P4b: plain text boxes whose font is Georgia or Inter still draw that font on the canvas (the textContent path),
  while the exports use Times or Helvetica. This predates P3a. Map the box font as rich objects now do, or cover it in
  the fidelity matrix.

## P3a-2

### CHANGED

- `ai_inspector/documentation/rich_text.py` and `rich_fonts.py`: top-level paragraph named styles, the shared feature vocabulary, feature/depth inventory, capability validation, and CSS-auto decoration metrics in every schema. Removed the obsolete font-specific decoration thicknesses.
- `rich_layout.py` and `rich_docx.py`: Title, Caption and Note base formatting, paragraph struts, explicit run overrides, native DOCX styles with direct formatting, and renderer cache-version bumps. Removed `Content.schema2`; retained the schema-1 compatibility oracle.
- `targets.py`, `parts_manual/documentation.py` and `codex_runtime/documentation_tools.py`: additive `richTextCapabilities` reads, capability enforcement on the shared UI/Sage write path, and updated tool descriptions. Target eligibility and tool names remain as authorized for this slice.
- `static/documentation_rich_text.js`, `documentation_rich_text_core.js`, `documentation_rich_text.css` and `index.html`: capability-scoped extensions and the ordered ribbon controls; schema-2 editing; named styles; selection state, resets, local undo boundaries, bounded lists, paste mapping and minimal-version saves. Static/editor typography shares CSS. An editor-only underline wrapper preserves sized-link and box-underline rendering without entering stored JSON. Clear formatting preserves paragraph IDs. The full toolbar uses an attached ribbon strip. Changed static URLs were bumped to `20261110-p3a-2`; plain boxes also disable ink skipping.
- `tests/test_documentation_typography.py`, `documentation_rich_text.test.cjs`, `documentation_rich_export_support.py`, `test_documentation_rich_exports.py` and `test_codex_documentation_tools.py`: named-style/export checks, auto decorations, narrowed capabilities, mirror tests, paste/read-only coverage and updated pins. Added 230 shared vectors in `tests/fixtures/rich_text_v2_vectors.json`; `.gitignore` allows only that requested fixture through the existing JSON ignore rule.
- `tests/smoke_documentation_editor.py`: P3a part 2 exercises the real ribbon, expected canonical envelopes, local/document undo, clear formatting, paste, reopen, capabilities and canvas/PDF/DOCX comparisons. Part 1 now checks schema-2 mounting and the auto strike rule. P2a/P2b flows remain unchanged; the shared canvas helper also measures the editor's content.

### TESTS

Final static checks only, all passed:

- AST parsing of all 12 changed Python files.
- `node --check` on both changed JavaScript modules and `tests/documentation_rich_text.test.cjs`.
- Syntax compilation of four inline application scripts and 86 smoke JavaScript snippets.
- JSON parsing of the 230 shared vectors; no vector assertions executed.
- `git diff --check`, LF checks, ASCII checks on added `index.html` lines, and verification that the untouched `server.py` retains its UTF-8 BOM.

### NOT RUN

No pytest, Node test suite, baseline, browser smoke, PDF/DOCX rendering or Word review ran. No visual artifacts were produced here. Claude should run these through the existing hidden Windows launcher:

~~~text
python -m pytest -q tests/test_documentation_typography.py tests/test_documentation_rich_text.py tests/test_documentation_rich_exports.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_editor_smoke.py tests/test_documentation_conflicts_ui.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py
python -m pytest -q tests/test_parts_manual.py tests/test_specification_sheet_workflow.py tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
node --test tests/documentation*.test.cjs
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python tests/smoke_documentation_editor.py --phase P1c
python tests/smoke_documentation_editor.py --phase P2a
python tests/smoke_documentation_editor.py --phase P2b
python tests/smoke_documentation_editor.py --phase P3a
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
~~~

The compatibility oracle requires commit `49cdaed`. Review the P3a screenshots/exports and render the DOCX in Word.

### DEVIATIONS

Scope follows the revised P3a-2 instructions. Wider eligibility remains P3a-3; find/replace and symbols remain P3a-4. Color controls accept color text so mixed selections can display an empty value.

DOCX retains Word's script geometry and half-point font-size units. Consequently, fractional named-style sizes round to the nearest half point, as existing heading sizes do; exact Word/canvas geometry is not claimed.

### OPEN QUESTIONS

The supplied Chromium measurements are implemented: auto strokes are size / 10 thick, strike is centered ascent / 3 above the baseline, and underline is centered one thickness below it. Chromium snaps paint to pixels; exports retain exact units. No new Chromium measurements were made here.

Runtime acceptance is pending, especially the expanded ribbon, per-run inherited underline, named-style geometry, selection/undo behavior and editor/static measurements. Every new style still needs the real-app measurement gate before shipping. Work is uncommitted and ready for supervisor review.

## P3a-2 supervisor gate

Reviewed, fixed and gated by Claude on 2026-11-10. Codex's build ran static checks only; every run below was made
here, in the worktree, one heavy job at a time.

### Findings and fixes

1. DOCX: Word's built-in Title style (python-docx's default template, which the exports start from) carries a bottom
   border (single, 4F81BD), contextual spacing, 0.25 pt letter spacing and kerning from 14 pt. Direct run formatting
   overrode the font, size, colour, bold and italic, but not these, so Word drew a blue rule under every Title and
   set it wider than the canvas. A named-style paragraph now turns them off directly: every pBdr side "nil",
   contextualSpacing 0 (in CT_PPr order), and run/paragraph-mark spacing 0 and kern 0. The template's Caption style
   (bold, blue, 9 pt) was already overridden by the explicit b/i/color/sz. Schema-1 DOCX bytes are unchanged (the
   49cdaed oracle passes). The named-style test also parsed an already-parsed styles part (3 failures); it now uses
   the parsed part and asserts the new properties and the pPr order.
2. Clear formatting split nested lists. Tiptap's clearNodes lifts each node one level only: clearing a six-level list
   saved five separate one-item bullet lists and a paragraph (smoke P3a 121/123; both clear checks failed). Clear
   formatting now lifts each selected block with the list command until it is in no list, then makes every selected
   block a plain paragraph with its own ID and removes every mark in the selection; a caret clears its whole block.
   Unselected items stay valid lists: a new smoke check clears "List 3" alone and expects List 1 > List 2, then the
   paragraph, then List 4 > List 5 > List 6, with List 3's ID kept. The first version of this fix ran the list
   command inside the ribbon's chain and threw "Inconsistent open depths" on the second lift (rerun 120/124, all
   three clear checks plus the browser-error check): prosemirror-schema-list maps positions through its
   transaction's whole mapping, and Tiptap's chain state caches its selection until `tr` is read. Each lift now runs
   on a fresh EditorState of the current document and its steps are replayed onto the chain's transaction. A
   harness that runs the shipped Clear formatting code against the pinned bundle passes a caret clear inside a
   six-level list, select-all, a range across three levels and a multi-paragraph ordered item: IDs kept, no page
   errors, and one undo restores the original exactly.
3. Colour controls were text fields only (the build's deviation, so a mixed selection can show an empty value). A
   native colour picker now sits beside each field: a pick applies the colour as one undoable change; the picker
   shows the shared colour, or black when the selection has none or mixes colours (the field stays empty then).
   New smoke checks: the picker mirrors the field, a pick updates the field, one Ctrl+Z restores the previous
   colour, and no highlight shows black.

Accepted as built: the capability vocabulary, inventory and refusal (unsupported_rich_text_feature on both write
paths); readOnlyReason over capabilities; the 230 shared vectors (pytest validate and Node normalize agree); the
editor-only underline mark for links and underlined boxes (never stored: normalize drops it, Node test); the
dispatch wrapper that keeps list depth, named-style placement and the presentation mark in each transaction; the
closeHistory meta key (the pinned bundle's PluginKey name) that starts one undo group per ribbon action; the Title,
Caption and Note table; CSS auto decorations in every schema with skip-ink none on all authored text.

### Visual review

- Ribbon (p3a-part2-ribbon.png, 1720 x 1080): every control in the brief's order on a three-row strip below the
  command bar; toggles show their pressed state; the colour pickers sit beside their fields.
- Edited box (p3a-p3a2-edited.png) against Word 16's render of the smoke DOCX: Title, Caption and Note sizes and
  colours; the Styled run (bold, italic, underline, strike, colour, highlight); sub and sup; the link; centred and
  right alignment; indent and spacing; six list levels with the same bullet glyphs. Word draws no rule under the
  Title, and the Caption is grey italic, not bold. The PDF is compared line by line by the smoke
  (typography_export_check).
- A schema-2 box mounts the editor without moving text (p3a-schema2-editor.png); the editor's lines match the static
  view within 1 px (smoke check).

### Numbers

- Node 274/274 (rich text 256, conflicts 18).
- Focused suite 1174 passed (after the fixes; Codex's build had 1171 plus the 3 named-style test failures).
- Clear formatting harness (the shipped code against the pinned bundle in Chromium): 5/5 cases, undo exact.
- Smoke P3a: run 1 121/123 (both clear checks), run 2 120/124 (the first clear fix), run 3 128/128, and 128/128
  again in the gate chain.
- Smokes P2b 36/36, P2a 23/23, P1a 27/27, P1b 46/46, P1c 35/35.
- Both baseline checks exit 0 (stores reopened unchanged).
- Documentation suites 1231 passed plus the 1 pre-existing failure
  (test_operations_manual_precoding_contracts::test_source_ids_references_and_local_hashes_are_closed).
- Wide suites 170 failed / 9 errors / 3851 passed: the same 179 failure IDs as at P3a-1, nothing new.
- Word 16 render of the smoke's edited DOCX (2 pages), checked against the canvas.

### Notes for later slices

- The editing toolbar is a three-row strip that overlays the top of the canvas (about 90 px at 1720 x 1080). A box at
  the very top of a page can sit under it while editing. Reserve the space or dock the strip in the UX pass (P5a).
- DOCX scripts and half-point sizes stay Word's own (the build's note): a 0.85 x 12 pt caption is 10 pt in Word.


## P3a-3

Implemented by Codex; reviewed, fixed and gated by the supervisor (see the gate section below).

### CHANGED

- `targets.py`, `identity.py`, `rich_text.py`, `parts_manual/documentation.py`, and `server.py`: one eligibility/capability table for operations-manual and work-instruction paragraphs, notices, and captions; canonical override `richText` with its plain projection; whole-field replacement protection; shared node-ID reservation; scene 6 with first-write v5 backup; one batched editor read. Reads add `richTextStyle` for the shared base style.
- `provenance.py` and `refresh.py`: rich formatting participates in manual provenance, confirmation, and three-way refresh, including formatting-only edits whose plain text still equals the generated source. Existing reset, resolution, and restore paths retain their contracts.
- New `rich_blocks.py`, plus `rich_layout.py`, `rich_docx.py`, and both manuals' exporters: rich paragraphs, centred notice copy columns, immutable signal prefixes with a 3 pt gap, and centred captions; native DOCX runs; PDF overflow refusal; renderer-version bumps. Legacy plain drawing branches remain in place. Generated DOCX paragraphs receive invisible standard bookmarks for export comparison.
- `documentation_rich_text.js`, its core/CSS, and `index.html`: generated fields mount the existing capability-limited editor, render with the advertised base style, and commit page-element rich replacements. The signal is outside the editor's content DOM. Line spacing resets to the target's base ratio. Static cache URLs are bumped.
- `documentation_tools.py`, regression tests and pins: updated Sage description without new tool names; generated-field storage, capability, refresh, restore, migration, service, PDF/DOCX, and Node coverage. Export comparisons now support generated native paragraphs. P3a smoke part 3 reuses navigation, editing, export, and canvas helpers and adds operations/WI checks, captures, screenshots, undo/redo, reopening, and capture-reuse checks.

### TESTS

- Passed static Python AST parsing for 25 changed/new Python files, then rechecked the final test/smoke edits.
- Passed `node --check` for both changed JavaScript modules and `tests/documentation_rich_text.test.cjs`; parsed all four executable inline scripts in `index.html`.
- Passed `git diff --check`. Written files use LF. Added server/index lines are ASCII; existing non-ASCII text is unchanged and the server BOM is preserved.
- No runtime tests, browser measurements, baselines, exports, or Word rendering were run. No commits, branches, or index changes.

### NOT RUN

Claude must run these in the equipped isolated environment:

```text
python -m pytest -q tests/test_documentation_rich_blocks.py tests/test_documentation_typography.py tests/test_documentation_rich_text.py tests/test_documentation_rich_exports.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_editor_smoke.py tests/test_documentation_conflicts_ui.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py
python -m pytest -q tests/test_parts_manual.py tests/test_specification_sheet_workflow.py tests/test_operations_manual_workspace.py tests/test_work_instruction_workflow.py
node --test tests/documentation*.test.cjs
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python tests/smoke_documentation_editor.py --phase P1c
python tests/smoke_documentation_editor.py --phase P2a
python tests/smoke_documentation_editor.py --phase P2b
python tests/smoke_documentation_editor.py --phase P3a
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
```

Review the saved part-3 canvas/PDF PNGs and render the DOCX in Word. The new plain-export oracle loads the actual de5e171 exporter; the existing 49cdaed oracle remains.

### DEVIATIONS

No intentional scope deviation. The additive `richTextStyle` read field avoids a second client eligibility/style table. The notice's DOCX spacer uses native `w:fitText=60` (twips) to request exactly 3 pt instead of approximating it with rounded character spacing. Its Word rendering is not yet verified.

### OPEN QUESTIONS

- Supervisor measurement must confirm generated-block baselines, line wrapping, notice centring, immutable signal behavior, caption centring, and editor/static equality before shipping.
- Verify Word's 3 pt fitted spacer and notice table geometry. Existing Word script sizing/offset and half-point size rounding remain as accepted at P3a-2.
- Runtime compatibility, migration backups, the complete smoke chain, and both baselines remain unverified here. The previously measured Chromium auto-decoration rules are unchanged.


## P3a-3 supervisor gate

Reviewed, fixed and gated by Claude on 2026-11-11 on the worktree (doc-editor at de5e171 plus this round). Codex
built the round in 42 minutes and ran static checks only; every runtime gate below was run by the supervisor, one
heavy job at a time.

### Findings fixed by the supervisor

1. Every DOCX export of a generated rich block failed with a TypeError: `write_content` passed the bookmark name as
   `_element(..., name=...)`, which collides with `_element`'s own first parameter (the tag name). The bookmark name
   is now set as an attribute. All eight `test_rich_generated_pdf_docx_geometry` cases had failed on it.
2. Canvas weights. On Windows, Arial weights above 700 resolve to Arial Black, a wider and taller face that no
   export draws. Two paths reached it. Bold marks render as `strong`, whose UA weight is `bolder` (900 inside a box
   whose base weight is 700): the work-instruction stage paragraph's glyph boxes were 13 px tall instead of 10. The
   notice signal word was CSS weight 800: "DANGER" was 46.8 px wide on the canvas and 43.33 pt (Helvetica-Bold) in
   the PDF, so the copy started 3.5 px later and the line box grew from 14 to 15 px. Rich content now draws bold at
   exactly 700, the signal at 700, and a box's base weight as the exports do (600 or more is 700). The plain
   notice's signal CSS was 800 as well (Arial Black on the canvas, Helvetica-Bold in every export); it is now 700,
   so a notice keeps its signal face when it becomes rich. The same rule closes a latent P2b case: a bold mark in a
   text box whose box style is bold.
3. `test_scene_v5_backup_and_future_refusal` expected `DocumentEditError` or `ValueError` from a read of a future
   scene. Reads refuse an unknown schema with `DocumentationSceneError`, as for every earlier version; the test now
   asserts that error and that the refused file is unchanged.
4. Editor read cost. `_documentation_editor_read` lost its early return, so every scene GET built a full snapshot,
   also for parts manuals and specification sheets, which have no eligible generated blocks (10-15 ms per read on
   MMLE-50D, with zero fields). The early return is restored for those types when they hold no text objects; it is
   exactly equivalent (their request list was always empty). Operations manuals and work instructions now pay for
   a real read: 67-99 ms and 48-94 ms per GET for 49 and 96 eligible fields (about 8-13 % of the GET). Accepted;
   see the notes.
5. Baseline: the synthetic `table/scene` fingerprint changed. Re-fingerprinting the new scene with
   `schemaVersion: 5` gives exactly the recorded value, so the scene schema number is the only change; the
   expectation is promoted as at P2a-1. The local MMLE baseline is unchanged.

### Accepted

- The rich notice in DOCX is a two-column borderless table (the symbol, then the vertically centred copy), where
  the plain notice is one paragraph (picture, signal, text in the template's Normal style). The rich path follows
  the canvas; the plain-block export mismatches remain P4b work.
- Refresh treats a formatting-only override as a user edit: it is never adopted, and it conflicts when the source
  text changes. As designed.
- The workspace route now checks open conflicts for whole-field replacements too. Only user and Sage edits send
  `wholeFieldReplacement`; conflict resolution never does.
- Generated DOCX narrative paragraphs carry invisible bookmarks (`rich_<hash>_<n>`, about 31 characters, under
  Word's 40) for the export comparison.

### Visual review

- Canvas and PDF crops of all four proofs agree after finding 2: the notice ("DANGER" bold, "Never" italic on
  #ffee80, the copy 3 px after the signal), the bulleted operations paragraph (bold #2468ac "Complete"), the centred
  caption ("Figure" bold, #596a76) and the Sage-written work-instruction stage paragraph (bold #2468ac at 9 px).
- Editors: the notice mounts with the marks-only ribbon and the signal outside the editable copy; the paragraph
  ribbon has Font, Size, alignment, indents, spacing and lists, no Style; Line spacing offers "1.4 (default)" (14/10
  for operations body text). The mounted signal measures as bold (ink density 61.8 against 61.7 for a plain bold
  signal and 37-42 for regular copy).
- Word 16 render of both DOCX exports (41 and 38 pages): the notice table draws the symbol, then "DANGER"
  (Arial-BoldMT) and "Never" (Arial-ItalicMT, highlighted) at 170.3 pt, so the fitText spacer gives 2.8 pt against
  the requested 3; the bullet paragraph's text starts at the 40 pt list indent with Word's Symbol bullet; the
  caption is centred at 7.5 pt with "Figure" bold; the work-instruction paragraph is Arial-BoldMT 9 pt #2468ac.
  The copy column is centred in a row of the frame's height while the symbol stays at the top of its cell, so the
  copy sits a little lower beside the symbol than on the canvas (flow layout; accepted).

### Numbers

- Node 276/276 (rich text 258, conflicts 18).
- Focused suite: Codex's build 1280 passed and 10 failed (the eight DOCX geometry cases of finding 1, the
  future-schema test of finding 3 and the baseline check of finding 5). After the fixes the rich-block and baseline
  files pass 132/132, and the documentation suites below ran on the final code.
- Smoke P3a: run 1 172/176 (the four canvas weight checks of finding 2), run 2 175/176 (only the browser-failures
  check: two THREE.WebGLProgram shader errors while the machine was short of memory), run 3 176/176.
- Smokes P2b 36/36, P2a 23/23, P1a 27/27, P1c 35/35. P1b stopped at 39/40 in the gate chain ("THREE.WebGLRenderer:
  Error creating WebGL context", the same low-memory period) and passed 46/46 on the rerun.
- Both baseline checks exit 0 (stores reopened unchanged).
- Documentation suites 1347 passed plus the 1 pre-existing failure
  (test_operations_manual_precoding_contracts::test_source_ids_references_and_local_hashes_are_closed).
- Wide suites 170 failed / 9 errors / 3851 passed / 68 skipped: the same 179 failure IDs as at P3a-1, nothing new.
  The first run hung for an hour without CPU in
  test_facility_layout_generation_run_repository::test_cross_process_single_writer_lease_is_synchronized (a
  multiprocessing spawn test outside this work, during the low-memory period). It was stopped and the suite rerun in
  four parts on the same code; that test passed.
- Every file of the round was last written at 01:07; smoke run 2 and every later gate ran after that.
- Word 16 render of both smoke DOCX exports (41 and 38 pages), checked against the canvas and the PDF.

### Notes for later

- P5a: the editor read on operations manuals and work instructions reads every eligible field on every scene GET
  (about 50-100 ms on MMLE-50D). If documents grow, read on demand or cache by revision.
- P4b: the plain notice PDF draws 8.4 pt copy at x+64; the canvas and the rich path draw 10 px at x+68. The plain
  DOCX notice is one paragraph in the template font.
- P4b (since P2b-1, every rich bullet list): Chromium draws disc, circle and square markers as shapes, not text. With
  a rounded ascent A (9 for Arial at 10 px), the symbol is (A*2/3 + 1)/2 px square (3 px), its box starts A*2/3 + 7 +
  1 px before the text and the symbol is inset 1 px (text - 13 to text - 10, centre text - 11.5; the canvas measured
  12), 3*(A - A*2/3)/2 px below the line's ascent top. The PDF draws the U+2022 glyph and a space, ending at the text
  (centre about text - 4.5 pt, a 2.6 pt dot). Ordered markers ("1. ") already match. The smokes exclude markers from
  the line comparison, which is why no gate caught it.
- P4b: the operations DOCX header band reaches about 8 pt into the body, so the top of every chapter heading (at
  48.6 pt) is covered in Word. Pre-existing: plain export bytes are unchanged since de5e171, and the overlap is on
  pages without rich content.
- The smoke's "Target closed" asyncio messages (123 this run, 57 at P3a-2) are Playwright response-finished
  callbacks for pages the harness closed; they are not failures.
