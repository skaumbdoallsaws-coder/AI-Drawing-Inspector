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
