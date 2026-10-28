# Inspection Sheet with open fields (plan, 2026-10-25)

## Why

The user, 2026-10-25, after looking at a fillable government form (ICE I-983): "I am thinking to have something
similar for documentation with incomplete information provided by the user. so sage can still build the document
but will leave empty field it does not have the information yet." Then: "yes and start with the inspection sheet"
and "write the plan and start building it".

Today every document type refuses to build when an input is missing (the specification sheet without its profile,
the operations manual without its evidence). The Inspection Sheet is not built at all: the registry marks it
`planned`, the workspace shows "coming soon", and Sage says "Not built in the app yet."

## The idea in one paragraph

Sage builds the document from what the app knows and leaves every missing value as a fillable PDF field. There are
two kinds of blank. An **open field** is information the document still needs, such as a tolerance or a lot
number. It is tinted amber, counted on the cover, and never guessed. A **record field** is filled where the
document is used: a measured value, conforms yes or no, the gauge, a signature. The user can supply values in
three ways: tell Sage in chat, type them in the app, or fill the PDF and give it back. The app keeps the values,
so the next build carries them.

## How the reference form is built (ICE I-983, inspected 2026-10-25)

- A Word document converted with Acrobat PDFMaker. The fields were added afterwards in Acrobat, in a second save.
- 74 plain AcroForm fields over the printed lines: 66 text, 7 signature, 1 checkbox. No JavaScript, no XFA.
  - Each field is named after its label and has a tooltip.
  - Text uses auto-sized Helvetica. 13 text fields are multi-line.
- AES-256 encrypted with an owner password. Anyone can open, fill, sign and print it; nobody can change the
  layout.
- We copy the field technique, not the lock. Nothing is encrypted in v1.

## What exists to build on

- **Drawing maps.** The SolidWorks extractor's `{pn}_drawing_map.json` is the only source of characteristics
  with sheet coordinates. Each annotation has its type, text, value in metres, position, bounds and leaders.
  - The loader `utils/drawing_map.py` drops `tolerancePlus/toleranceMinus/toleranceType`. Fixed in IS1.
- **Drawing PDFs.** `{pn}_drawing.pdf` exists for some parts. The resolver is `server._resolve_part_drawing_pdf_path`.
- **Dimension descriptions.** `{pn}_dimension_descriptions.json` holds curated text per dimension.
- **Inspection profiles.** `{pn}_inspection_profile.json` lists the features to inspect and why, with no
  nominal values.
- **Report tab FAI (browser only).** `buildFaiCharacteristics` balloons the drawing dimensions. It orders them by
  sheet, view, then top-to-bottom and left-to-right. PASS/WARN/FAIL comes from `evaluateCharacteristic`. Nothing
  is saved, and the print uses `window.print()`.
- **The assembly catalog.** `_parts_manual_catalog_for_assembly` provides the BOM and part numbers.
- **The library data is only on disk.** The engine data is not in git (`.gitignore` has `*.json`), so the test
  copy needs a copy of it:
  - Engine 100001 is parts 100002 to 100009.
  - Only the piston, 100006, has a drawing (PDF and map): 21 dimensions with nominals and descriptions, and no
    tolerances at all.
  - The other seven parts have inspection profiles and no drawings.
  - 100010 is the piston plus its rings.
  - That makes 100001 a natural test of "build it anyway".

## Decisions (taken 2026-10-25, the user asked to start building)

1. **One sheet per assembly.** It is bound to the assembly loaded in Documentation, like the other types. There
   is one section per unique part number in BOM order, then an assembly check.
2. **Characteristics, strongest source first:**
   1. The part's drawing map. Every visible, non-dangling dimension is ballooned on the part's drawing PDF, in
      the same order as the Report tab, so the numbers match.
   2. The part's inspection profile. Each feature is a row, and its requirement is an open field.
   3. Neither. One row "Inspect to drawing", whose drawing reference is an open field.
3. **Tolerances, in order:**
   1. the dimension's own tolerance;
   2. else the part's **general tolerance**, one open field per part, from the title block (title blocks are not
      extracted);
   3. else the limits stay blank.

   Limits are printed only when known: there is no JavaScript to compute them in the PDF. Values the user
   provides are applied on the next build. A returned PDF is checked against the limits the app has.
4. **Assembly check.** One row per BOM line (item, part number, description, quantity), with record fields:
   quantity found, and conforms.
5. **Header and sign-off.**
   - Open fields: customer, purchase order or job, lot or serial, drawing revision per part, sample size.
   - Record fields: inspection date, inspector name and signature, reviewer name and signature, and accept or
     reject.
6. **Page format.** US Letter landscape for every page, because the tables are wide and the drawings are
   landscape. The registry's `pageOrientation` changes to landscape.
7. **Field names are stable,** so values survive rebuilds:
   - `header.<key>`
   - `part.<pn>.general_tolerance`, `part.<pn>.drawing_revision`
   - `char.<pn>.<n>.requirement|measured|conforms|gauge`
   - `bom.<item>.found|conforms`
   - `signoff.<who>.name|date|signature`
   - `result.accept`, `result.reject`
8. **Values store.** `INSPECTORPRO_INSPECTION_SHEET_ROOT/<assembly>/values.json`. Each value records its source
   (`chat`, `workspace` or `returned_pdf`) and time; a chat value also keeps the user's words. Built PDFs go in
   `<assembly>/documents/<revision>/`.
9. **Never guessed.** The app writes no value from inference. Sage's write tool accepts a value only when it
   appears in the user's own message for that turn; the gateway checks this.
10. **No release state in v1.** The sheet is a working form. Its cover shows the open-field count and the
    conformance summary from the last returned PDF.

## Phases

**IS1 - server core (build first).**
- Fix the drawing-map loader so tolerances are kept.
- `ai_inspector/inspection_sheet/`:
  - `document.py`: compile sections, characteristics, fields and open fields from the catalog, drawing maps,
    descriptions, profiles and stored values.
  - `exports.py`: the PDF. Cover with the header and open-field list; per part, the drawing page with balloons,
    then the characteristics table; the assembly check; sign-off. All of it uses `documentation/form_fields.py`.
  - `store.py`: the values file and the built PDFs.
  - Conformance: measured value against limits gives PASS, FAIL, NO_LIMITS or PENDING, mirroring
    `evaluateCharacteristic` without its 10% WARN band. The WARN band is a Report-tab hint, not a disposition.
- Routes:
  - `GET /api/inspection-sheet/{asm}` returns the summary and open fields.
  - `POST /api/inspection-sheet/{asm}/build` writes the PDF.
  - `GET /api/inspection-sheet/{asm}/pdf/{revision}`
  - `POST /api/inspection-sheet/{asm}/values` sets provided values (workspace).
  - `POST /api/inspection-sheet/{asm}/returned-pdf` reads a filled PDF back and gives conformance.
- The registry status becomes `available` (changed in IS2: `review_available` makes Sage call the export a
  "review copy", which a form meant to be filled is not; its `releaseNotice` says what it is).
- Tests.

**IS2 - Sage on Codex.**
- The `inspection_sheet` guide entry: purpose, pages, outputs, and needs with who provides each.
- Readiness: "can build; N open fields", with the open fields listed.
- Tool `build_inspection_sheet`, run on the server during the turn (changed from a browser workflow
  `generate_inspection_sheet`: the sheet needs no browser captures and builds in seconds, so Sage can name the
  real open fields from the build instead of promising them). The turn's receipt carries `builtDocuments`; the
  browser's status line under Sage's reply reports pages, characteristics, open fields and the PDF link (IS3).
- Tool `provide_inspection_sheet_values` (name, value). The value must be in this turn's user message as a whole
  token (case, spacing and the +/- and diameter spellings aside); anything else is refused. The message is stored
  as the value's quote, with source `chat`. Tick boxes and signatures are refused. A provided value is used on the
  next build.
- Progress labels and tests.

**IS3 - workspace.**
- Enable the type in the Documentation selector.
- A panel with the summary, the open fields as inputs, a Build PDF button and "Return a filled PDF".
- The PDF opens in the viewer the other types use.

**IS4 - live test, then port.**
- In the test UI (:8491), on 100001 and 100010:
  - ask Sage what the sheet needs;
  - build it;
  - give the piston's general tolerance in chat and rebuild;
  - fill a copy of the PDF and return it.
- Port to the real repo. The engine data is already on disk there.

**Later.** The same open fields on the specification sheet, then the operations manual. Balloons on a 3D figure
for parts without drawings. GD&T text (the extractor returns `None`). Title-block extraction, which would supply
the general tolerance and revision. Word export.

## Status

- `documentation/form_fields.py` + `tests/test_documentation_form_fields.py` (7 tests): fields round-trip through a
  filled PDF.
- IS1 committed 900711b (test copy): `inspection_sheet/` (document, exports, store), the drawing-map loader keeps
  tolerances, five routes, `tests/test_inspection_sheet.py`. 100001: 8 pages, 214 fields, 41 open, 49
  characteristics (21 ballooned on the piston drawing). 100010: 5 pages.
- IS2 (2026-10-25): the guide entry, `build_inspection_sheet` and `provide_inspection_sheet_values`, the host's
  state, build and values, progress labels, the instructions. The detail read lists up to 100 rows with their field
  names (about 430 bytes a row) so Sage can record "dimension 4 measured 55.31". Found while probing on real data
  and fixed: the general tolerance parser took the first number of anything ('+0.1 -0.05' became +/-0.1, inches
  were read as mm). It now reads +/-T, +a -b and +a/-b in mm or inches and nothing else; a value it cannot read
  stays an open field with the reason, tinted amber in the PDF. 115 tests pass (sheet, form fields, Codex
  documentation tools, Sage route, drawing map, specification sheet).
- Later, added: decimal-place tolerance blocks (.X +/-0.1, .XX +/-0.05) are a common title-block form; they are
  refused today and could be read per characteristic from its printed decimals.
- IS3 committed c307f53: the type is selectable in Documentation; its panel (no 3D, no composed pages) shows the
  summary, the open fields as inputs with Save values, what was provided and the last returned copy; the ribbon has
  Build Sheet (opens the PDF), Refresh, Open PDF and Return Filled PDF. A Sage turn that builds the sheet attaches the
  PDF as a chat file card (pages, characteristics, open fields) and refreshes the panel. Found on the way:
  `_build_part_properties` read a part's inspection profile (its fallback when `<pn>.json` is missing) as if its
  feature list were the extraction's dict, and one such part stopped the whole assembly from loading; guarded.
- IS4 (2026-10-25, test UI :8491, Sage on Codex gpt-6.1-sol, plan usage):
  - Panel on 100010: saved +0.10 -0.05 and the lot, built (4 pages), filled a copy outside the app and returned
    it: 9 values read, PASS 3, FAIL 1 (55.31 against 55.15-55.30, ticked as conforming, so a disagreement).
  - Sage on 100001, turn 1 "Build the inspection sheet ... tell me what is still missing": 2 tools, 33 s, 8 pages,
    41 open fields named correctly, PDF card under the reply.
  - Turn 2, the piston tolerance, revision C, the lot and a sample size of 5 in one message: Sage read the field
    names, recorded the 4 values (source chat, the message as quote) and rebuilt: 7 pages, 37 open fields, every
    piston row with +/-0.05 limits.
- Ported to the real repo 2026-10-25 (port 13, e1a545a..c307f53, 16 files, backup
  Documents/InspectorPro-Backups/2026-10-25-before-inspection-sheet-port). Real repo: 203 Python tests passed;
  JS 50/51 files, the one failure (test_chat_stream_frontend_contract.js) fails the same on the pre-port index.html.
  The desktop app was not restarted: it reported unsaved work.
- Next: the same open fields on the specification sheet, then the operations manual.
