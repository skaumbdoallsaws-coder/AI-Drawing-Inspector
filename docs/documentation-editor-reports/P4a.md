# P4a - basic object controls

## P4a-1

CHANGED

- `parts_manual/documentation.py`: scene schema 7, read-only upgrades from 1-6 and the first-write v6 backup; explicit bottom-to-top `objectOrder`, restore normalization, crop and aspect lock, four replayed operations, legacy resize/rotation checks, version keys and atomic object batches. All four document compilers expose `documentationObjectOrder`.
- New `documentation/objects.py`: ordered reads, hashes, rotated boxes, eight arrangements, contain/cover/crop placement, managed-asset resolution, PDF images/shapes and DOCX pictures. `commands.py`, `targets.py`, `changes.py`, `refresh.py`, `server.py` and `documentation_tools.py` bind `read_document_objects` and the four operations to pre-image hashes, receipts and one document undo step. Sage cannot add/delete objects.
- `static/index.html`: paint and target enumeration follow the order list; image crops use `object-view-box` with contain; shape opacity is applied once instead of twice. No new workspace controls or external static JS changes.
- Parts, operations, work-instruction and specification PDFs, including fillable specification, share the ordered image/shape drawing and retain existing text paths. Operations, work-instruction and specification DOCX use native cropped/rotated pictures and individual transparent shape PNGs at 4 px/pt. Managed assets use the parts asset store. Renderer/cache stamps now cover any authored object.
- Shape geometry follows the canvas SVG's centred 100-unit square. One composition pixel equals one PDF point: the non-scaling stroke is `1.5 * lineWidth` pt; revision-cloud dashes are 7/4 pt and detail-box dashes 6/4 pt. The ellipse, rounded rectangle and open arrow paths retain the SVG coordinates. These are code-derived rules; browser/PDF measurement remains pending.
- Added `test_documentation_objects.py` and `test_documentation_export_matrix.py`; updated schema, renderer and tool pins. Added P4a smoke for all four document types, asset upload, Sage operations, order/frame/pixel checks, exports, reload and undo. Earlier smoke sequences remain unchanged apart from the schema-version assertion.
- Updated `documentation-editor-capability-matrix.md`: DOCX objects occupy top/left/ID flow positions; overlap and stacking are not reproduced.

TESTS

- Static checks only: Python AST parsing passed for 34 changed/new Python files; all four executable inline scripts in `index.html` compiled.
- `git diff --check` passed. Changed/new files use LF; added server/index lines are ASCII; the server UTF-8 BOM is preserved.
- No runtime tests, exports, browser measurements, baseline checks or commits were run.
- Compatibility tests load the previous drawing modules and exporter callers from `5cf7f26`: PDFs compare bytes with only random PDF IDs suppressed; DOCX compares every XML/relationship part. They cover default-opacity text-only/no-object output and have not been run.

NOT RUN

Claude must run these in the equipped environment through the hidden-process launcher on Windows:

```text
node --test tests/documentation*.test.cjs
python -m pytest -q tests/test_documentation_objects.py tests/test_documentation_export_matrix.py tests/test_documentation_rich_exports.py tests/test_documentation_typography.py tests/test_documentation_tables.py tests/test_documentation_rich_text.py tests/test_documentation_rich_blocks.py tests/test_documentation_search.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_editor_smoke.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_parts_manual.py tests/test_operations_manual_workspace.py tests/test_specification_sheet_workflow.py tests/test_work_instruction_workflow.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python tests/smoke_documentation_editor.py --phase P1c
python tests/smoke_documentation_editor.py --phase P2a
python tests/smoke_documentation_editor.py --phase P2b
python tests/smoke_documentation_editor.py --phase P3a
python tests/smoke_documentation_editor.py --phase P3b
python tests/smoke_documentation_editor.py --phase P4a
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
```

Inspect the canvas/PDF PNGs and render the three DOCX outputs in Word. The smoke records which document types actually export; a disabled Publish button after real captures is a failed gate with its reason, not a passing skip.

DEVIATIONS

- Native Word text has no run alpha. DOCX text opacity is represented by blending direct text, fill and border colors against white, keeping text editable. Consequently, text-only DOCX with opacity below 1 changes from the old exporter, which ignored opacity. This resolves the requested opacity behavior at the expense of the blanket text-only compatibility requirement for that case; the default-opacity oracle remains exact. This needs supervisor acceptance.
- No other intended scope deviations. No handles, crop mode, arrangement controls, new keys, grouping, CAD-transform changes, parts DOCX or inspection-sheet objects.

OPEN QUESTIONS

- Runtime acceptance is pending, especially image clipping/clockwise rotation/transparency, shape pixel geometry, Word crop/rotation/extent rendering, stale/retry/undo behavior and the no-image/no-shape compatibility oracles.
- Confirm the DOCX text-opacity compatibility decision above. Word flow cannot reproduce page overlap/stacking; that limitation is recorded in the capability matrix.


## P4a-1 supervisor gate

Reviewed, fixed and gated by Claude on 2026-11-11 on the worktree (doc-editor at 5cf7f26 plus this round). Codex
built the round in 49 minutes and ran static checks only; every runtime gate below was run by the supervisor, one
heavy job at a time.

### Findings fixed by the supervisor

1. Picture sizes. `objects.pixel_size` called `fitz.image_profile`, which raises a TypeError in this PyMuPDF
   build for every picture (91 of the 95 failures of the first run of the two new test files). A new
   `objects.picture_info` reads the header with Pillow and returns the displayed size and the EXIF orientation;
   `pixel_size` wraps it.
2. Camera-turned photos. A JPEG that carries an EXIF orientation is shown turned by the browser and by MuPDF's
   image-to-PDF path, but not by `fitz.Pixmap` (the path for opacity below 1) and not by Word 16 (measured on
   all eight orientations). `objects.upright` re-encodes such a JPEG upright (quality 95, colour profile kept)
   for those two paths, and crops are taken on the displayed picture everywhere. Page, PDF and DOCX now agree.
3. Opacity. The alpha of a picture drawn below full opacity was scaled in a Python loop over every sample; it
   is now one `bytes.translate` call.
4. Cropped pictures on the page. `object-view-box` chooses the part of the picture but does not clip: in a
   frame of other proportions the picture beyond the crop showed in the bands beside the kept part (the PDF
   was right). A cropped object is now a size container and its `<img>` gets exactly the kept part's box once
   the picture has loaded (hidden until then).
5. Order on the page. The two readers of a page's order use the union of `documentationObjectOrder` and the
   object keys, so an object missing from the list is still drawn and still a target.
6. Document revisions. The four `_apply_scene` builders wrote `documentationObjectOrder: []` on every page,
   which changed the `documentRevision` of every existing document. They now write the list only when the page
   has authored objects.
7. Tests and baseline.
   - Two object tests reset a scene without the `figure` target the code requires; the arrangement tolerance
     is 1.5e-6 (the stored frames are rounded to 6 decimals).
   - Three stale assertions: the document schema in tests/test_documentation_provenance.py is 6 (only the
     scene schema moved to 7), and the renderer stamps in the specification-sheet and work-instruction
     workflow tests.
   - The export matrix gained a camera-turned JPEG in all eight orientations: 48 PDF cases (contain, cover and
     crop at two opacities) and 8 DOCX cases.
   - `baseline/expected.json`: the hash of `table/scene` was promoted. A field-by-field dump of that scene
     from a clean export of 5cf7f26 against this round shows one changed leaf of 141: `schemaVersion` 6 to 7.
     The local baseline has no changed leaf.
8. Smoke harness (written without a run).
   - Publishing a parts manual answers with `artifact`, not `pdf` (the fatal KeyError of run 1).
   - The page then sends the browser to that PDF, an attachment; headless Chromium reports the navigation as
     net::ERR_ABORTED. The harness accepts that once per publish, for the exact URL the publish answered with,
     and lists it under the known fixture limitations.
   - A camera step on all four document types: an orientation-6 JPEG, cropped to its shown top-right quadrant,
     in a frame of other proportions over a white box. It checks the page at every step (inside the kept part
     and in the bands beside it), the PDF, the DOCX (upright media, crop, no rotation) and Sage's read.
   - P3b, found in the regression run: the step that types after the final table clicked the last cell,
     pressed Ctrl+End and ArrowDown and sent the text with `keyboard.insert_text`, without waiting. It
     depended on timing in three ways (see Numbers). It now arrows out of the last cell into the gap, waits
     for the editor's own selection after the click and after each key, types with real key presses and
     records each wait; a miss is a failed check, not a 120 s timeout.

### Accepted

- Word has no alpha for text runs. In the DOCX a text box's opacity is shown by blending its text, fill and
  border colours against white; the text stays editable. Pictures and shapes carry real transparency.
- The DOCX is a flow document: objects follow each other in order, top to bottom; overlap and stacking are
  not reproduced (recorded in the capability matrix).
- Pictures turn in steps of 90 degrees; shapes and text boxes at any angle.

### Observed, not changed

- A shape is drawn inside a centred square of its frame's shorter side (the page's SVG has a 100 x 100 view
  box). The PDF now matches the page; before this round the PDF filled the frame. Letting shapes fill their
  frame is a small change on both sides if wanted.
- An orientation stored in a PNG's EXIF chunk is ignored (the picture is taken as upright), as browsers
  commonly do for PNG.
- The edge of a crop blends about half a source pixel of the neighbouring colour (a hairline on the test
  picture, not visible on photos).
- Editor, found while fixing the P3b smoke step (this round does not touch the editor). At the gap after a
  table that ends a text box, typed text becomes a new paragraph: the editor inserts it itself, from the
  keypress. Text that arrives without key events (an IME commit, dictation, the emoji panel) is placed by the
  browser at its own caret, and after ArrowDown out of the last cell that caret is still at the end of the
  cell: such text goes into the last cell. After Ctrl+End it goes into a new paragraph. This is the editor
  library's behaviour at a gap cursor; handling `beforeinput` at the gap would close it (a P5a candidate).

### Visual check

- Real app, all four document types: the page against the PDF region for the cropped and turned picture, the
  shape, the text box and the camera photo.
- Word 16 renders of the three exported DOCX files: the cropped turned picture, the shape picture, the text
  box and the camera photo upright.

### Numbers

- Node 307/307 (rich text 258, conflicts 18, search 20, tables 11).
- The two new test files: 297 passed (241 written by Codex, 56 camera cases added by the supervisor).
- Focused suite 1722 passed, none failed, on the final product code (the first run: 1717 passed, 5 failed: the
  three stale assertions and two baseline checks of finding 7).
- Smoke P4a: run 1 stopped at 49 of 50 checks (the parts export answer); run 2 passed 231 of 232 (the download
  navigation); run 3 351/351 on the final code, all four document types.
- Smokes P3a 194/194, P2b 36/36, P2a 23/23, P1a 27/27, P1b 46/46, P1c 35/35, each on its first run, alone.
- Smoke P3b: 168 of 169 on its first run in the chain (the text typed after the final table went into a
  cell), then a re-run with a first harness fix stopped at the same step (nothing had been typed, so the Done
  press waited 120 s for a save; memory was at 0.6 GB). Three experiments on the same harness (one to three
  minutes each, 26 trials) logged the editor's and the browser's selection after each key:
  - a click and Ctrl+End reach the editor on the browser's selectionchange event, after the key; ArrowDown
    sent before that acts on the old caret cell (the first run: the table's arrow handler moved to the cell
    below it);
  - Ctrl+End already lands in the gap, and ArrowDown pressed at the gap moves the browser's caret out of the
    editor for some milliseconds; text sent in that time is lost (the re-run);
  - `keyboard.insert_text` sends no key events, so the browser places the text at its own caret; typed text
    at a gap is inserted by the editor from the keypress. With real key presses the text became a new
    paragraph in 7 of 7 trials, by ArrowDown and by Ctrl+End.
  None of this is a product change of this round (it does not touch the editor); the earlier passes were
  timing luck. The step was rewritten (finding 8) and run 3 passed 169/169.
- Both baseline checks exit 0 (stores reopened unchanged).
- Documentation suites 1779 passed plus the 1 pre-existing failure
  (test_operations_manual_precoding_contracts::test_source_ids_references_and_local_hashes_are_closed).
- Wide suites 170 failed / 9 errors / 3851 passed / 68 skipped: the same 179 failure IDs as at P3a-1, nothing new.
- The product files were last written at 14:22 (static/index.html), before smoke run 3 of P4a and every gate
  after it. The smoke file was written at 15:10 and 16:53 (the P3b step only, a part no other phase runs);
  P3b run 3 and tests/test_documentation_editor_smoke.py (35 passed) ran on the final file.
- Word 16 renders of the three exported DOCX files and the PDF regions, checked against the canvas.

### Notes for later rounds

- P4a-2: the workspace controls post bound batches to a new /objects route; crop mode draws its own picture
  and keeps the page's clip mechanism of finding 4.
- P5a: structure-only read of a table for Sage; lazy load of the editor bundle (carried); text input without
  key events at the gap after a final table (see Observed).
- Smoke harness: `keyboard.insert_text` is not typing. Use it only inside a text selection; at a gap, a cell
  selection or a selected object use `keyboard.type`. Never send a key after a click or a native caret key
  without waiting for the editor's own selection.
- P4b: the operations DOCX header band covers the top of chapter headings in Word (carried).
