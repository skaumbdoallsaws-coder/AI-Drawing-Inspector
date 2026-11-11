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
