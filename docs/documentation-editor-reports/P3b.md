# P3b - authored non-BOM tables

## P3b-1

CHANGED

- Added `documentation/tables.py`: validated grids, server-allocated IDs, all requested structural/style operations, proportional width redistribution, 12 pt column checks, sequential batches and per-operation identity maps.
- Extended `rich_text.py`, `targets.py`, `search.py` and the JS core for minimal schema 3, table-only 2048-node/96-KiB bounds, column-ID reservations, authored-box capabilities and ranges inside cells. Generated targets retain their previous capabilities.
- Extended `commands.py`, the scene repository, `server.py`, Sage schemas/guidance and pins. Table operations use a shared pre-image hash, coalesce to one write per target, and retain atomic undo and receipt replay. Results are in `receipt.operationResults`. No new tool name, workspace route or scene schema version.
- Added table flow/geometry to `rich_layout.py` using the supplied column and spanning-row rules, including canvas rounding. PDF draws cell fills, rules and existing rich runs. `rich_docx.py` writes fixed nested tables with native paragraphs, spans, vertical merges, fills, borders and unsplittable rows. Both renderer versions are bumped.
- Added static table markup/CSS and the exact schema-3 read-only editor notice. Table extensions and ribbon controls remain for P3b-2. Changed JS/CSS URLs are versioned.
- Added `tests/test_documentation_tables.py`, `tests/documentation_tables.test.cjs`, table-aware export comparisons, capability/schema pins and the isolated `--phase P3b` smoke. The smoke covers Sage operations, range edits, IDs, canvas geometry, grid/plain exports, reload, the editor guard and exact document undo/redo.

TESTS

- Static checks only: Python AST parsing passed for all 18 changed/new Python files; `node --check` passed for both changed static JS files and the new Node test file; all four executable inline scripts in `index.html` compiled.
- `git diff --check` passed. Changed/new files use LF; added server/index lines are ASCII; `server.py` retains its UTF-8 BOM.
- No runtime tests, baselines, browser smokes, exports or visual measurements were run. No commit or index/history mutation was made.

NOT RUN

Claude must run these in the equipped environment, using the hidden-process launcher on Windows:

```text
python -m pytest -q tests/test_documentation_tables.py tests/test_documentation_search.py tests/test_documentation_rich_blocks.py tests/test_documentation_typography.py tests/test_documentation_rich_text.py tests/test_documentation_rich_exports.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_editor_smoke.py tests/test_documentation_conflicts_ui.py tests/test_codex_documentation_tools.py tests/test_codex_specification_sheet_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py tests/test_codex_progress_steps.py
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
python tests/smoke_documentation_editor.py --phase P3b
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
```

The supplied 160-case Chromium fixture is consumed by the new tests and was not changed. Review the smoke's canvas/PDF crops and render both grid/plain DOCX artifacts in Word.

DEVIATIONS

- No feature-scope deviation. Scene schema remains 6; an additive `tableBatch` marker permits replay of larger table batches, following the existing `rangeBatch` pattern.
- The existing 64-KiB tool-response ceiling also applies to table identity results. Oversized results are refused before persistence with `codex_result_too_large`; retry fewer operations. Read and request ceilings are unchanged.
- OOXML requires a paragraph after a nested table at the end of a cell. That empty paragraph uses a one-twip line and contributes no stored text. Word still chooses nested-table row heights, as directed.

OPEN QUESTIONS

- Supervisor acceptance remains required: exact agreement with all 160 row-height cases, real canvas geometry and wrapping, PDF paint/text counts, schema-1/2 compatibility, atomic batches and Word rendering have not been runtime-verified here.
- An insertion/deletion that would leave a row with no starting cell refuses with `invalid_table_grid`. Only merge removes such rows, as explicitly specified. Confirm this interpretation for those uncommon structural cases.


## P3b-1 supervisor gate

Reviewed, fixed and gated by Claude on 2026-11-11 on the worktree (doc-editor at c0cfd33 plus this round). Codex
built the round in 44 minutes and ran static checks only; every runtime gate below was run by the supervisor, one
heavy job at a time.

### Findings fixed by the supervisor

1. Merged-row order. Two merged cells that overlap without one containing the other were served in the wrong
   order (`ar > br`): the brief's words "lower start row" were ambiguous and Codex read them as the larger index.
   Chromium serves the cell that starts higher first. The measured fixture caught it on its first case (row
   heights 47.19 and 47.20 where the browser has 45 and 45). `row_heights` now compares `ar < br`; all 160
   measured cases agree exactly.
2. Deleting a column could be refused. When the deleted column held a row's only starting cell, the result had a
   row in which no cell starts and the delete failed with `invalid_table_grid`, so that column could never be
   deleted (Codex's open question). `delete_column` now removes such a row and shrinks the spans across it, the
   rule the brief gave for a merge. Row and column inserts and row deletes cannot produce such a row.
3. A table that outgrows its text box. The stored bound for a text box with a table is 96 KiB of canonical JSON,
   which stops an empty table at 46 x 12 and a table with short text in every cell at about 400 cells; the
   structural caps of 50 rows and 12 columns can therefore not both be reached. That stands (see Accepted), but
   the refusal was the general `rich_text_too_large`. `create_table`, `insert_row`, `insert_column` and
   `split_cells` now refuse with `table_too_large` and say what to do ("Use fewer cells, or put the rest in a
   second table in another text box."). A whole-field write keeps the general code.
4. An empty cell style (`style: {}`) changed nothing and was accepted. It is refused with
   `invalid_table_operation`.
5. PDF rule corners. Rules were drawn with butt ends, which left a half-point notch at every outer corner.
   They now have projecting ends, so corners close as the canvas borders do.
6. Sage's tool text. `create_table` states the size bound and its refusal; `modify_table` states that inserted
   cells copy the reference row's or column's cell type (insert before the first body row, not after the header
   row, to add a body row at the top) and that deleting a column also removes a row left without cells.
7. Tests written without a run.
   - The Sage sequence test created its text box without a `name` (422 from the scene route).
   - The generated-block refusal test used a scene whose generated block is not rich-eligible, so it met
     `read_only_derived_field` before the table check. It now uses the narrative scene, asserts that the block's
     capabilities have no `table`, and gets `unsupported_rich_text_feature`.
   - Two older expectations were stale: the typography test still required schema 3 to be refused (it now refuses
     4 and requires a schema-3 document without a table to be stored as its minimal version), and the P3a smoke's
     `p3a2_read_capabilities` still expected a text box's capabilities without schema 3.
   - The Sage sequence test runs under the turn's 120 s limit, which a loaded machine exceeded
     (`codex_run_closed`); the limit is not under test and is lifted there.
8. Smoke harness.
   - The canvas screenshot path was `output / stem + "..."` (a TypeError that ended the first run).
   - Canvas against layout allowed 1 px. The table rules are measured to 1/64 px, so the tolerance is 0.05 px.
   - Cell checks were named by server-made IDs that change every run; they are named by position.
   - The reopened canvas was measured under the first measurement's check names and overwrote them.
   - Every cell held one line, so no row rule could fail. New steps wrap one cell to three lines and make the
     merged cell eight lines tall, taller than its two rows (the canvas shares the difference in 1/64 px:
     rows of 71.578125 and 33.421875 px), and set middle alignment in a row with room to spare. A new check
     (`p3b_proof_has_wrapped_and_stretched_rows`) requires that the proof really contains these cases.
   - The read-only step called the helper that waits for an editor, which a schema-3 field must not open; it now
     waits for the notice and requires that no editable element exists.
9. The measured fixture is exempted from the repository's `*.json` ignore rule.

### Accepted

- New cells take the cell type of the reference row or column (my brief). A row inserted after the header row is
  a header row. Sage's tool text says how to get a body row.
- Size. A text box with a table holds 2048 nodes and 96 KiB. Sage's read tools stop at 64 KiB per result, so Sage
  cannot read whole a text box above about 250 cells with short text (`read_result_too_large`); it can still find
  and replace text in its cells by ranges, but it cannot get the IDs for structural operations. Each table
  operation's result carries the whole identity map, so a batch on a large table can exceed the 64 KiB response
  and is then refused before anything is stored (`codex_result_too_large`: send fewer operations). P5a (scale)
  should add a structure-only read; until then large tables are for the workspace.
- Word chooses row heights. A merged cell that is taller than its rows gives its extra height to the last row in
  Word, while the canvas and the PDF share it between the rows as Chromium does. Line breaks, widths, fills,
  rules, alignment and bold are the same in all three.
- A text box that is made narrower after a table was created can leave columns under 12 pt: the canvas still
  draws them and both exports refuse with the reason `table_column_too_narrow` (explicit overflow, as planned).
- The client validator accepts a JSON number written as `250.0` where the server requires an integer type. A
  browser never writes that form.
- `data-rich-id` is now on every rendered block, not only on table nodes.

### Visual check

- Canvas (real app, operations manual): header row with the default header fill, a two-cell merge, a merged cell
  across two rows with a fill, a blue fill, bold, middle and bottom alignment, wrapped text; plain style without
  rules. The page shows the read-only notice and opens no editor.
- PDF: the same line breaks, row heights, fills and rules as the canvas; corners closed.
- Word 16 renders of both DOCX files (grid and plain): the table sits in the text box's flow at the box's left
  edge, with the spans, fills, rules, alignment and bold; see Accepted for row heights.

### Numbers

- Node 300/300 (rich text 258, conflicts 18, search 20, tables 4).
- Tables suite: Codex's build 38 passed and 3 failed (finding 1 and the two tests of finding 7); the final code
  44 passed.
- Focused suite: 1417 passed and 1 failed on the first run (the stale schema-3 expectation); 1418 passed, none
  failed, on the final code.
- Supervisor checks outside the suite: 2478 random structural operations on 300 tables (every result validates
  and is canonical, no ID is ever used twice, and no operation leaves a row without a starting cell); the client
  validator against the server validator on 354 envelopes (156 valid, 198 broken): the same verdict, stored value
  and projection on 348, and 6 that differ only in the JSON number form `250.0`; sizes: an empty table fits up to
  46 x 12, 400 cells with short text fit (50 x 8, 91-94 KiB), and Sage's whole-field read ends at about 250 such
  cells.
- Smoke P3b: run 1 stopped at the screenshot path error after 41 passed checks; run 2 passed 49 checks and
  stopped at the read-only step (the helper waited for an editor); run 3 83/83 on the final code.
- Smokes P3a 194/194, P2b 36/36, P2a 23/23, P1a 27/27, P1b 46/46, P1c 35/35. P3a and P1b each needed a second run:
  the first P3a run lost its WebGL context while a supervisor test ran beside it (1.1 GB of free memory) and
  carried the stale capability check; the first P1b run lost its WebGL context right after and stopped at a
  wait with 39 checks passed. Both passed alone.
- Both baseline checks exit 0 (stores reopened unchanged).
- Documentation suites 1475 passed plus the 1 pre-existing failure
  (test_operations_manual_precoding_contracts::test_source_ids_references_and_local_hashes_are_closed).
- Wide suites 170 failed / 9 errors / 3851 passed / 68 skipped: the same 179 failure IDs as at P3a-1, nothing new.
- The round's product files were last written at 08:38 and the P3b part of the smoke at 08:40; smoke run 3
  (08:40) and every gate after it ran on that code. The P3a part of the smoke was last written at 09:16, before
  its passing run.
- Word 16 renders of the smoke's two operations DOCX files (grid and plain, 42 pages each), checked against the
  canvas and the PDF.

### Notes for later rounds

- P3b-2: the editing surface must give the static geometry (Tiptap's own table view sets min-widths); structure
  changes go through the server operations.
- P5a: structure-only read of a table for Sage; lazy load of the editor bundle (carried).
- P4b: the operations DOCX header band covers the top of chapter headings in Word (carried).


## P3b-2

CHANGED

- `static/documentation_rich_text.js`: capability-gated table extensions edit cell paragraphs using static colgroup/cell markup, `View: null` and no resizing. The transaction guard blocks structural/style changes. Tab stays inside the table; heading, named-style and list controls are disabled in cells.
- `static/documentation_rich_text_core.js`: editor normalization preserves table/row/cell/column IDs, strips Tiptap defaults and allocates new paragraph IDs. Added signatures/guards, grid positions, insertion anchors and proportional/equal widths. Supported schema-3 fields are editable.
- The Table menu follows Symbol and uses server operations for insertion, deletion, merging, splitting, header/fill/alignment/borders and widths. Fill has a native picker and a hex field. Save/conflict handling precedes operations; remount restores the caret by cell ID or grid position. A saved draft plus a table action are **two writes and two document undo steps**; editor Ctrl+Z history starts again after remount.
- `server.py` and `static/index.html`: added the bound user `/tables` route, receipt-preserving transport retry and reload/remount wiring. CSS adds the menu, cell selection overlay and gap cursor. Changed static URLs are bumped.
- Extended Node and pytest coverage for normalization, guards, the 200 width vectors, extension markup/keyboard behavior, route restrictions, user attribution, receipts, refusals and exact undo.
- Added P3b smoke part 2 for real menu/keyboard interactions, 0.05 px mounted/static geometry, caret continuity, paste/width refusals, gap typing, undo/redo, exports and Sage interoperability. It records values/receipts and menu, selection, canvas and PDF PNGs.

TESTS

- Static checks only: Python AST parsing passed for four changed Python files; `node --check` passed for both changed static JS files and the Node test file; all four executable inline scripts in `index.html` compiled.
- `git diff --check` passed. Written files use LF; added server/index lines are ASCII; the server UTF-8 BOM is preserved.
- No runtime tests, browser measurements, exports, baselines or commits were run.

NOT RUN

Claude must run these in the equipped environment, using the hidden-process launcher on Windows:

```text
node --test tests/documentation*.test.cjs
python -m pytest -q tests/test_documentation_tables.py tests/test_documentation_editor_smoke.py tests/test_documentation_rich_text.py tests/test_documentation_typography.py tests/test_documentation_rich_exports.py tests/test_documentation_search.py tests/test_documentation_rich_blocks.py
python -m pytest -q tests/test_documentation_transactions.py tests/test_documentation_provenance.py tests/test_documentation_change_undo.py tests/test_documentation_refresh.py tests/test_documentation_store_chokepoint.py tests/test_documentation_conflicts_ui.py tests/test_codex_documentation_tools.py tests/test_codex_readonly_pilot.py tests/test_codex_assisted_tools.py
python tools/documentation_baseline.py --check
python tools/documentation_baseline.py --local --check
python tests/smoke_documentation_editor.py --phase P1a
python tests/smoke_documentation_editor.py --phase P1b
python tests/smoke_documentation_editor.py --phase P1c
python tests/smoke_documentation_editor.py --phase P2a
python tests/smoke_documentation_editor.py --phase P2b
python tests/smoke_documentation_editor.py --phase P3a
python tests/smoke_documentation_editor.py --phase P3b
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_documentation*.py','tests/test_parts_manual*.py','tests/test_operations_manual*.py','tests/test_specification_sheet*.py','tests/test_work_instruction*.py','tests/test_inspection_sheet*.py') for p in glob.glob(pattern)})))"
python -c "import glob,sys,pytest; sys.exit(pytest.main(['-q']+sorted({p for pattern in ('tests/test_codex*.py','tests/test_facility*.py','tests/test_authored*.py','tests/test_sage*.py','tests/test_industrial*.py') for p in glob.glob(pattern)})))"
```

Review the smoke PNGs and PDF crop, and render the DOCX in Word. The supplied width fixture remains unchanged and untracked for the supervisor to add.

DEVIATIONS

- Part 1's obsolete read-only assertion now checks that an unchanged table mounts and Escape makes no write. Its other proof steps remain; measurement is extracted for reuse by part 2.
- No changes to `tables.py`, the table model, layout, exports, Sage tools, bundle or scene schema.

OPEN QUESTIONS

- Runtime acceptance is pending: width vectors, 0.05 px geometry, cell-selection drag, gap-cursor typing, remount focus, route/undo tests and browser exports have not been executed here.


## P3b-2 supervisor gate

Reviewed, fixed and gated by Claude on 2026-11-11 on the worktree (doc-editor at 4a15e6e plus this round). Codex
built the round in 23 minutes and ran static checks only; every runtime gate below was run by the supervisor, one
heavy job at a time.

### Findings fixed by the supervisor

1. Cost per key in a large table. The table guard serialized the document twice on every transaction, including
   caret moves, and every Table menu control asked for the table context (a third serialization and a grid walk)
   on every transaction: about twenty-five serializations per key. The guard now runs only when the document
   changed, and the context is computed once per editor state.
2. Smoke harness (written without a run).
   - The table measurement took the text box's size from `offsetWidth`, a whole number. This round's box is
     0.84 x 960 = 806.4 px wide, so the layout was made for 806 px and every column edge came out 1/8 px off the
     real canvas (11 failed checks). It now reads the exact size from the element's style. The product was right.
   - One step pressed Tab into the last cell, then Enter, and expected the cell's text to survive. Tab selects
     the text of the cell it enters (see Accepted), so Enter replaced it. The step now checks that selection
     (`p3b2_tab_selects_cell_text`), presses End and waits until the editor has registered the caret move.
     Three short experiments on the same harness showed why the wait is needed: the editor learns of a native
     caret move from the browser's selectionchange event, which arrives after the key; a key sent within the
     same few milliseconds still acts on the old selection. End, Home and the arrows behave normally in every
     cell once that event has arrived.
   - Two checks passed a single node to `plain_text`, which takes a whole envelope (the fatal error of run 1).

### Accepted

- Tab and Shift+Tab select the text of the cell they enter, as Word does; typing replaces it. Tab in the last
  cell does nothing (no new row, focus stays).
- A table action on an unsaved draft is two steps in the document history: the text save, then the operation.
  The workspace's Undo walks both. The editor's own Ctrl+Z history starts again after each table action,
  because the editor is mounted again on the stored result.
- From the keyboard a table can only keep its structure or go away whole. An edit that would change part of
  it (a selection that crosses the table's edge and is deleted or typed over) is refused with the notice
  "Use the Table menu to change rows, columns or cells." Editing and emptying cells is allowed, and so is
  removing a whole table together with what is selected around it (select-all, then Delete).
- A pasted HTML table is refused with its notice; plain text pastes as before.
- Style, Bullets and Numbering are disabled inside a cell (cells hold paragraphs only).

### Visual check

- Real app, operations manual: the Table menu (insert form; the current table's actions appear with the caret
  in a table), a two-cell selection with its tint, the table while typing, and the final table after the
  whole sequence.
- PDF region and a Word 16 render of the exported DOCX: the same table (header fill, rules, the two-paragraph
  cell, the paragraph after the table).

### Numbers

- Node 307/307 (rich text 258, conflicts 18, search 20, tables 11).
- Focused suite 1421 passed, none failed, on the final product code.
- Smoke P3b (part 1 and part 2 in one run): run 1 stopped in part 2 with 103 of 115 checks passed (the rounded
  box size, the Tab step and a misused helper); run 2 passed 168 of 169 (the Tab step again: the key after End
  arrived before the editor had registered the caret move); run 3 169/169 on the final code.
- Three short experiments on the smoke harness (the same server, browser and editor; about three minutes each)
  logged the editor's selection after every key: End, Home and the arrows collapse a cell's selected text in
  every cell; a caret move is registered on the browser's selectionchange event, some milliseconds after the
  key.
- Smokes P3a 194/194, P2b 36/36, P2a 23/23, P1a 27/27, P1b 46/46, P1c 35/35, each on its first run, alone.
- Both baseline checks exit 0 (stores reopened unchanged).
- Documentation suites 1478 passed plus the 1 pre-existing failure
  (test_operations_manual_precoding_contracts::test_source_ids_references_and_local_hashes_are_closed).
- Wide suites 170 failed / 9 errors / 3851 passed / 68 skipped: the same 179 failure IDs as at P3a-1, nothing new.
- The product files were last written at 10:54, before the focused suite; the smoke file at 11:31, before
  smoke run 3; every gate after that ran on that code.
- A Word 16 render of the exported DOCX (42 pages) and the PDF region, checked against the canvas.

### Notes for later rounds

- P4a: measure page elements from their style or bounding box, never `offsetWidth`.
- P5a: structure-only read of a table for Sage; lazy load of the editor bundle (carried).
- P4b: the operations DOCX header band covers the top of chapter headings in Word (carried).
