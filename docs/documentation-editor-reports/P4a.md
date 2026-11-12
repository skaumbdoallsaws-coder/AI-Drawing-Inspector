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

## P4a-2

CHANGED

- `server.py`: added the bound `POST /objects` workspace route, using the existing object batch path with actor `user`, and cheap `objectBinding` on every scene read, including the early return. Object controls do not require the rich-text flag.
- `documentation/objects.py` and `codex_runtime/documentation_tools.py`: an explicit `aspectLock` accepts new proportions without carrying a dimension; changing the lock alone is valid. Unstated-lock checks and saved-log replay retain their existing behavior. Tool names are unchanged.
- New `static/documentation_objects_core.js`: shared, DOM-free placement, rotated boxes, eight-handle resize, movement, crop geometry, insertion sizing and order availability. Its script URL is versioned `20261111-p4a-2`.
- `static/index.html`: object selection, eight rotated handles, group dragging, queued point nudges, Lock ratio, Order and keyboard shortcuts, authored-object Align/Distribute, crop Apply/Reset/Cancel, focus/Enter/Delete, and proportionate locked image insertion. Gestures use one bound batch path with transport retry, scene reread, retained selection and refusal rollback. Legacy insert/rotate/delete also refresh the object binding. Plain-editor cancellation restores the handles.
- Added Node geometry tests and 360 Python-generated vectors, their stale-fixture test and gitignore exception; extended object route/binding/aspect tests and the tool-schema pin. Added P4a smoke part 2 after the unchanged part 1, using pointer/key input, state-based waits, stored-frame/order checks, crop inside/outside pixels, undo, reload and PDF pixel comparison.

TESTS

- Static checks only: six changed Python files passed AST parsing; the new core, Node test file, all four executable inline scripts in `index.html` and 27 browser snippets in the new smoke passed JavaScript parsing.
- The fixture generator ran successfully: 180 placement and 180 box vectors. This generated test data; it did not run the tests.
- `git diff --check` passed. Changed/new files use LF; added server/index lines are ASCII; the server UTF-8 BOM is preserved.
- No pytest, Node runtime tests, browser smoke, exports, baseline checks or commits were run.

NOT RUN

Claude must run these in the equipped environment, using the hidden-process launcher on Windows:

```text
node --test tests/documentation*.test.cjs
python -m pytest -q tests/test_documentation_objects.py tests/test_documentation_export_matrix.py tests/test_documentation_editor_smoke.py tests/test_codex_documentation_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_specification_sheet_tools.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_change_undo.py tests/test_documentation_provenance.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_rich_text.py tests/test_documentation_tables.py tests/test_documentation_rich_exports.py
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

Inspect the new handles, crop, multi-selection, final-page and PDF PNGs and the recorded gesture values. Run P4a with the harness rich-text flag; the route tests also exercise the flag off on all four document types.

DEVIATIONS

- No intended scope deviations. Scene schema, Sage tool names, object exports, CAD operations and shape drawing are unchanged. A very thin legacy picture with no crop rectangle satisfying both the picture bounds and minimum frame dimensions cannot be resized in crop mode.

OPEN QUESTIONS

- Runtime acceptance remains pending: real rotated-handle anchors, crop placement and outside-image pixels, queued input, focus traversal, retry/refusal recovery, exact undo and the existing export/baseline gates. No browser or export measurements are claimed by this build.

## P4a-2 supervisor gate

Reviewed, fixed and gated by Claude on 2026-11-11 on the worktree (doc-editor at f4f73cb plus this round). Codex
built the round in 36 minutes and ran static checks only; every runtime gate below was run by the supervisor, one
heavy job at a time. The first browser run of the new controls was the supervisor's.

### Findings fixed by the supervisor

1. Icons. The new buttons named five icons (`check`, `close`, `lock`, `layers`, `crop`) that exist neither in
   the inline set nor in the ribbon pack: blank buttons and five 404s. Five SVGs were added in the pack's style
   (24 x 24, 1.75 stroke, round caps, currentColor) and listed in the UI contract test. (The pack's manifest is
   a local file that git ignores; it was left as it is.)
2. A second scene read after every command. The page's answer normaliser read the whole scene again whenever
   an answer carried no `objectBinding`, and no command, undo or redo answer carried one: 1.9 MB and 0.7 s
   more after every command on the operations manual. Part 1 of the P4a smoke, which fitted well inside its
   28 minutes at P4a-1, took 27 minutes alone. The eight command, undo and redo answers now carry the binding
   (`_documentation_object_binding`, also used by the read); the normaliser has its P4a-1 rule again; the
   object path reads the binding once, and only when a payload came from an answer without it. A test compares
   each command, undo and redo answer's binding with the next read on all four document types.
3. Workspace keys. The handler returned whenever any text editor was open; before, the workspace's own
   shortcuts (undo, redo, zoom, Escape, nudge) stopped only while the focus was in the editor. That rule is
   back; only the new object keys are off while an editor is open. While a change is being saved the handler
   swallowed every key press (Tab and F5 included); now it holds back only the workspace's own keys.
4. Crop mode rebuilt the whole ribbon on every pointer move. It is built when the mode begins and ends; Reset
   is available when the picture has a stored crop.
5. Selection, found by the first browser run:
   - Inserting an object while another was selected left the handles and the floating toolbar on the old
     object while the ribbon showed the new one (the "keep the set" option kept a set the new target was not
     part of; the option predates this round). A set is now kept only around one of its own members.
   - Undo and redo reduced a selection of several objects to the last one picked. They keep the set (the
     members that still exist), as a save does.
   - The selection outline went to the first element with the object's id in the document, which is the
     rail's thumbnail copy of the page (a lookup that predates this round; visible now with several objects).
     The lookups are scoped to the page, and thumbnails are copied without handles or selection marks.
   - The floating toolbar of several objects stood above the last one picked and covered its neighbour, which
     could then not be pressed to move the selection. It stands beside the whole selection.
   - After Refresh (and any page activation) the ribbon's Object group stayed, enabled, with nothing selected.
     The ribbon is redrawn when an activation clears a selection.
6. Keyboard focus. Objects are recreated at every redraw, and the rail draws every page on the same layer for
   its thumbnails, so the object with the focus lost it after each change. The focus is remembered and given
   back when the object's page is next drawn, unless it went elsewhere meanwhile.
7. Crop mode and the rail. Drawing another page for a thumbnail ended the crop mode without a word. While the
   crop mode holds the page the rail keeps the previews it has, as it does while a text editor is open.
8. `server.py`: two blank lines before the new route (four were left).
9. The smoke's new part (harness only):
   - several steps record the same name (`selection_1`, `object_pressed`) and the report keeps one result
     per name: four failures were hidden by later passes in one run. The first failure of a name now stays;
   - lookups by object id and by class also matched the rail's thumbnail copy; they are scoped to the page;
   - presses went to the centre of an object's box even when another object or the toolbar covered it; they
     go to a point of the object that nothing covers;
   - waits are sized to the measured times (15 s by default, 60 s for a write's answer and for the queued
     nudges, 120 s for opening the 33-page manual); a control that is absent is a failed check, not a 30 s
     fatal wait;
   - new checks: Refresh removes the Object group; thumbnails carry no handles or selection marks.
10. The smoke's shared parts (harness only), found by the regression smokes:
    - the canvas measuring script took every child of a text box as content. A selected object now carries its
      eight handles as children, so the content height became the frame height: two P3b checks failed
      (`p3b2-typed_canvas_table_box`, `p3b2-final_canvas_table_box`: 385.8 against 88 and 100). The script
      leaves the handles out. No product code measures content this way;
    - a shared machine. The desktop app was open from 21:03 to about 22:04 and again from 22:12, and its 3D
      view held the GPU: one figure capture took about 70 s (62 s of it in the render step) instead of a few
      seconds. P3b and P1c ended on the 240 s wait for Capture All, P3a on its 28-minute limit, P1b on a press
      that waited 30 s for a frame (the stall probe: no animation frame in 3 s with the page idle). No product
      check failed in these four runs apart from the two measuring failures above. `DOC_SMOKE_SLOW=<factor>`
      now multiplies every wait the smoke gives in milliseconds (through `T(...)`) and Playwright's default
      action wait; with the default 1 every wait is what it was. The four phases were run again with 6, one
      at a time (see Numbers).

### Accepted

- The object keys (order, Delete, Enter, nudge) are off while any text editor is open on the page.
- Tab walks the objects in stacking order (the browser's own order); focus selects.
- A press on overlapping objects selects the top one.
- Part 2 of the smoke starts from the open workspace part 1 leaves behind (it has no start of its own).

### Observed, not changed

- An object change settles in about 2.2 s on the 33-page operations manual: the object batch 1.5 s and the
  scene read after it 0.7 s (a scene command takes 1.4 s; measured in process on this machine). The preview is
  immediate and nudges queue behind the save; other object gestures wait. The batch path builds the document
  more than once: a P5a benchmark candidate.
- In one run on a loaded machine (the app took two minutes to start) the cover's thumbnail drew its figure
  area black for a while and was right again after Refresh. The thumbnail takes the figure from the live 3D
  view; nothing in this round's code paths touches that.
- The status line reads "Sage: Undid the document change." after the user's own undo (wording older than
  this round).
- Pictures still turn in steps of 90 degrees and shapes draw inside a centred square of their frame (P4a-1).

### Visual check

- Real app, operations manual cover: the eight handles on an inserted picture; the crop mode with its dimmed
  outside and Apply, Reset and Cancel; three objects selected with the toolbar beside the selection and no
  handles; the final page; and the exported PDF page against the canvas (colour samples in the four quadrants
  and in the bands beside the contained picture, equal within 8 levels).

### Numbers

- Node 475/475 (conflicts 18, objects 168, rich text 258, search 20, tables 11).
- The round's test files (objects, Sage documentation tools, smoke contract, parts UI contract, export matrix):
  421 passed.
- Focused suite 1735 passed, none failed (65 minutes; the machine was busy).
- Smoke P4a, part 2 alone while fixing, five runs: no open workspace; 102 of 121; 91 of 101; 120 of 122 (two
  write answers over 10 s); 125/125. Full runs: 474 of 475 in 1166 s (Capture All was at 91 percent after its
  60 s wait, since raised); 475/475 in 1611 s on the final product code; 475/475 in 2247 s on the final smoke
  file.
- Regression smokes, first pass in the chain: P2b 36/36, P2a 23/23, P1a 27/27. P3b, P3a, P1b and P1c ended on
  waits while the desktop app was open (finding 10): P3b 151 of 153 checks (the two measuring failures) and
  then the Capture All wait; P3a its 28-minute limit; P1b 34 checks, then a press that got no frame; P1c 16
  checks, then the Capture All wait.
- The same four again, alone, with DOC_SMOKE_SLOW=6: P1c 35/35 in 271 s, P3b 169/169 in 719 s, P3a 194/194 in
  994 s. P1b: 43 checks passed, then the 180 s wait for the work-instruction export's answer ran out (the
  server answered the same upload step in 4 to 50 s during that run, and that wait was not yet covered by the
  factor); run again with every wait covered: 46/46 in 616 s.
- tests/test_documentation_editor_smoke.py on the final smoke file: 35 passed.
- Both baseline checks exit 0 (stores reopened unchanged).
- Documentation suites 1792 passed plus the 1 pre-existing failure
  (test_operations_manual_precoding_contracts::test_source_ids_references_and_local_hashes_are_closed).
- Wide suites 170 failed / 9 errors / 3852 passed / 68 skipped: the same 179 failure IDs as at P3a-1, nothing new.
- The product files were last written at 19:07 on 2026-11-11 (static/index.html), before the final chain began
  at 19:34. The smoke file was written three times after that, harness only: the measuring filter (21:43), the
  wait factor for captures and presses (22:54), the factor for every wait (00:12). P1c and P3b ran again on the
  version of 22:54; P3a, the contract test, P4a and the last P1b ran on the final file.

### Notes for later rounds

- P4b: page setup changes the page size the object geometry uses (`_documentationObjectSize`); the vectors in
  `tests/fixtures/documentation_object_vectors.json` are per page size.
- P5a: the time of an object batch (see Observed); a scene answer that carries the built document could spare
  the read after an object batch.
- Smoke harness: scope every lookup to `#documentationPublicationSurface` (the rail holds a copy of the active
  page with the same attributes); press where nothing covers; never reuse a check name without keeping the
  first failure; write every new wait as `timeout=T(milliseconds)`; a measurement of an object's content leaves
  out `.documentation-object-handle` and `.documentation-resize-handle`.
- Gate machine: the desktop app and the smokes share one GPU. A smoke that ends on a wait while the desktop app
  is open is run again alone with `DOC_SMOKE_SLOW` before anything is concluded from it.
