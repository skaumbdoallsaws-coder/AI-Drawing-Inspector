# Specification Sheet with editable slots (plan, 2026-10-25)

## Why

The user, 2026-10-25, after the Inspection Sheet with open fields was built:

- "I am thinking of using that approach to edit for example the specification sheet right in our viewport, so
  that when we output the pdf it is ready ... both the generated and to be filled information to be cleanly
  selectable ... user can just click through it to change and add what they see fit ... we need to maintain our
  presentation and slides style."
- "we can even use another machine! we have plenty of machines in the library. for a given machine, will sage know
  the usual specs name? it might not fill the value yet ... the desktop should have a browser tool to do just that
  ... sage has tools to capture the machine model to add picture to the spec sheet, hopefully it can still do all
  that."
- "I will go with your recommendations but proceed with writing the plan."

Today the Specification Sheet builds for one product only. It refuses any assembly without a hand-reviewed profile
(`docs/specification-sheet/profiles/<assembly>.json`); only MMLE-50D has one. The 100001 engine gets "no reviewed
specification-sheet profile is registered". Every library machine (309 catalog entries) is out of reach, because
Documentation only documents the assembly loaded in the Assembly tab.

## The idea in one paragraph

The page keeps its presentation style, and every piece of text on it becomes a **slot**: the title, the tagline,
each specification row's name and value, the feature cards, the caption. A slot holds a value and where it came
from: the CAD, the reviewed evidence, a cited public source, the user in chat, the user in the viewport, or Sage's
draft. In the viewport the user clicks any slot and types, as in PowerPoint. A value the app does not have is an
amber placeholder, shown in the viewport only. Sage knows the usual specification names for a machine type. The
first time, it proposes them and the user approves the list, which becomes that type's template. Sage fills what
the CAD, the evidence, the user or a cited source gives, and leaves the rest open. The final PDF is drawn from the
same slots: real, selectable text, ready to send. A fillable PDF turns the remaining open slots into fields for
someone else to fill and return, as the Inspection Sheet does.

## What exists to build on (read 2026-10-25)

- **The document.** `specification_sheet/document.py` builds one Letter portrait page from layout blocks:
  `spec-kicker`, `spec-title`, `spec-tagline`, `spec-figure` (the CAD capture), `specifications-heading`,
  `specifications-table` (a `key_value_table`: rows of `[label, value]` with claim ids), `features-heading`, and
  `spec-feature-1..3`.
  - Values come from the profile's claims in the operations-manual evidence repository. Every claim must be
    approved, or the build fails.
  - It needs exactly three features.
  - The features heading is hard-coded: "Designed for productive material handling".
- **The viewport.** Double-click edits the title, the tagline, plain blocks and the feature copy in place
  (`_documentationBeginInlineTextEdit` sends `update_text`, stored as `pageElementOverrides` in the documentation
  scene).
  - The specifications table is one object: a single row or cell cannot be selected (user's screenshot,
    `Downloads\Video\21.png`).
  - Feature-card titles have no edit handler.
  - Overrides are bound to the scene's plan revision, so a regeneration with a changed profile rebaselines the
    scene and drops them.
- **Gap found while reading:** the spec sheet's PDF and DOCX exporters (`specification_sheet/exports.py`) draw
  the text of `layoutBlocks` and never read `pageElementOverrides`. The parts manual (`parts_manual/pdf.py`) and
  the operations manual (`operations_manual/exports.py`) do read them. So today an in-place edit on the spec
  sheet does not reach its exported PDF or DOCX. To be confirmed with a test in SS0.
- **The capture.** The draft workflow captures the product from the loaded assembly's 3D viewer. The render
  request has `scopeKind: "assembly"` and occurrence ids; the image is 2200 px, technical white, isometric. The
  export refuses until the capture matches the current document revision.
- **Sage on Codex in Documentation** (`codex_runtime/documentation_tools.py`):
  - `generate_specification_sheet_draft` and `publish_specification_sheet` are browser workflows, queued after
    the reply.
  - The Inspection Sheet added the pattern this plan reuses:
    - a server-side build during the turn;
    - a values tool that accepts only values said in the user's message (`said()`, whole tokens);
    - a values store with source and quote;
    - the chat's PDF file card.
- **Public research** (`codex_runtime/research_tools.py`): `search_public_sources` and `read_public_source`.
  - Connected to Facility Layout only, behind `INSPECTORPRO_CODEX_WEB_RESEARCH`. It is off in the test UI; the
    desktop's setting lives in `.env`, which is never read here.
  - At most 4 requests a turn, public terms only, cited URLs.
  - A value is relied on only after `read_public_source`. Web values never overwrite CAD.
- **Library machines.** `generated/industrial_assets/**/catalog-entry.json`: 309 entries, with assetId,
  displayName, category (Machines, Material Handling, Automation, Vehicles, ...), description, overall
  dimensions in metres, and the colored GLB. Also `extracted.json` (SolidWorks extraction).
  - Examples: Three-Axis CNC Machine, Mori CL-200A CNC Lathe, Okamoto Surface Grinder, Sinker EDM Machine,
    Nordson EFD 3-Axis Robot, Reversible-Fork Lift Truck, Red Telescopic Forklift, Pallet Truck.
  - Facility Layout's Sage finds them with `search_industrial_assets`.
  - Caution: the Mori's extraction has no assigned material, so its CAD mass (8419.66, unit labelled mg) is not a
    machine weight.
  - Their GLBs have named nodes, one per body or component: the Mori has 12 (0.1 MB), the red forklift 11; some
    models are a single body.
- **The Assembly viewport can load any GLB.**
  - `_initAssembly3DScene(container, number, {glbUrl, cacheKey, meshMapMode})` is used this way by Training's
    guided viewer.
  - In the default mode, `_buildPartMeshMap` matches GLB nodes to `assemblyContext.occurrences` by exact name, and
    the documentation capture shows the occurrences its render request lists.
  - So a model opens and captures like an assembly once the app describes it as one. Assemblies open with
    `?assemblyProfile=<number>`.
- **Fillable fields.** `documentation/form_fields.py` (from the Inspection Sheet): AcroForm text and checkbox
  fields, amber open fields, read-back of a returned PDF.

## Decisions (taken 2026-10-25; the user took the three recommendations)

1. **Slots, not form fields, in the viewport.**
   - Every text on the page is a slot with a stable id: `title`, `tagline`, `kicker`, `caption`,
     `features.heading`, `spec.<key>.label`, `spec.<key>.value`, `feature.<n>.title`, `feature.<n>.text`.
   - The template places the slots, so the presentation style (theme, header band, figure frame, table rules,
     feature cards) never changes. Only the words do.
2. **Edits are values, not layout.**
   - Slot values live in a values store, `INSPECTORPRO_SPECIFICATION_SHEET_ROOT/<subject>/values.json`, keyed by
     slot id. Each value has its source, time, and quote or citation.
   - The row list (order, added and removed rows) lives there too.
   - So "Generate Sheet" can run again without losing anything the user typed. The scene keeps only layout
     (positions, styles).
3. **Sources, and what each one may do:**
   - `cad`: overall dimensions from the model's bounding box. Weight only when the model has an assigned
     material; otherwise the weight stays open.
   - `evidence`: an approved claim. This is how MMLE-50D works today, unchanged.
   - `research`: a value read from a public source in this turn (`read_public_source` receipt). It is
     **filled, marked "from source, unreviewed"**, with the URL, title and retrieval date (recommendation 2).
   - `chat`: a value the user said, under the Inspection Sheet's rule (whole tokens of this turn's message).
   - `workspace`: typed in the viewport.
   - `sage_draft`: tagline, feature-card text and headings that Sage wrote. Marked unreviewed. Every number in a
     draft must equal a value already on the sheet, so a draft never introduces a new figure.
4. **Typing over a CAD or evidence value is allowed and flagged** (recommendation 3). The slot becomes a user
   override, and the release gate lists it with the original value and its source.
5. **Spec names per machine type** (recommendation from the 2026-10-25 discussion).
   - The type comes from the reviewed profile, the library category and description, or Sage's classification,
     which the user confirms.
   - The first sheet of a type: Sage proposes the rows (label, unit, short hint) from its knowledge of that
     type, and the user approves the list.
   - The approved list is stored as `templates/<type>.json` and used for every machine of that type.
   - A sheet can still add, remove or reorder rows; that does not change the template unless the user asks.
6. **Library machines open as assemblies** (recommendation 1; approach chosen by the user 2026-10-25).
   - A library machine is opened in the Assembly viewport as a **library-machine assembly** (`asset-<id>`),
     built by the server from its catalog entry:
     - name, category and overall dimensions;
     - one occurrence per GLB node, named exactly as the node;
     - the machine's GLB served through the usual assembly model route.
   - Everything downstream then works unchanged: Documentation, Capture Product and Refresh Capture, Sage's draft
     workflow, and the slots.
   - Only machines the user opens are registered, not all 309.
   - Their nodes are bodies, not numbered parts, so Documentation offers them the Specification Sheet only and
     says why the parts manual and the inspection sheet do not apply.
7. **Two exports from one page:**
   - **Final PDF**: drawn from the slots. Real, selectable text and no fields. A row whose value is open is left
     out; an open prose slot is left out with its frame.
   - **Fillable PDF**: the same page, with the open slots as amber AcroForm fields (`form_fields.py`). A
     returned copy is read back, with source `returned_pdf` (it never clears a value), as on the Inspection Sheet.
   - DOCX keeps working and is drawn from the same slots.
8. **Release gate.** It stays a review copy (`controlledPdfAllowed: false`, as today) and now also lists:
   - open slots;
   - unreviewed research values;
   - Sage drafts;
   - user overrides of CAD or evidence.
   - Accepting a research value or a draft in the workspace (or telling Sage) clears its flag.
9. **Units.** Each sheet has a unit system: imperial or metric, from the profile or the template, and the user
   can change it. CAD values are converted, and research values keep the unit their source printed.
10. **Never guessed.** The rule from the Inspection Sheet holds. Sage records a value only from the user's words,
    an approved claim, the CAD, or a source it read in this turn. A typical value for the type is a hint in the
    placeholder ("typically 6,000 rpm for this class"), never a filled value.

## Phases

**SS0 - export what the viewport shows (small, ship first).**
- A test that edits the title and a feature text in place, exports, and reads the PDF and DOCX text. Expected to
  fail today.
- The spec sheet exporters resolve each block's text through `pageElementOverrides`, as the parts manual does.
- This is independent of the slot work, and it fixes "the PDF is ready" for MMLE-50D now.

**SS1 - slot model and values store (server).**
- `specification_sheet/slots.py`: slot ids, values with sources, rows, open list, user overrides, the units
  setting.
- The profile becomes optional:
  - with a profile, the evidence fills the slots, and MMLE-50D renders exactly as today (golden test on the
    PDF text);
  - without one, the type template plus the CAD fill what they can and the rest is open.
- CAD values from the catalog's bounding box (assembly or library machine), and weight only with a material.
- Store: `values.json`, `templates/<type>.json`.
- Routes:
  - `GET /api/specification-sheet/{subject}/slots`
  - `POST .../values` (workspace)
  - `POST .../rows` (add, remove, move)
  - `POST .../accept` (research value or draft)
- The document's layout blocks are generated from the slots, so the viewport, the PDF and the DOCX read one
  source.
- Tests: store rules (same as the Inspection Sheet's), override flags, numbers-in-drafts guard, unit conversion,
  MMLE-50D golden.

**SS2 - the viewport.**
- Every slot is its own element, real DOM text: selectable and copyable.
  - Click selects; double-click or Enter edits in place; Tab and Shift+Tab move to the next or previous slot;
    Esc cancels.
  - Specification rows: label and value cells are separate slots. "Add row" sits under the table; a selected row
    can be deleted or moved up and down.
  - Feature titles become editable.
- Open slots show an amber placeholder in the viewport only, for example "Spindle speed - add value", with the
  type's hint as a tooltip.
- Nothing new is drawn on the page for sources. The Properties pane shows the selected slot's source (CAD, the
  claim, the link, "you", "Sage draft"), with Accept for unreviewed values and "Revert to CAD" for overrides
  (minimal visual additions).
- Text fit: shrink to the template's minimum size, then wrap within the frame. Past that, the slot shows a red
  outline and export names the slot that does not fit.

**SS3 - exports.**
- Final PDF and DOCX from the slots (open rows left out); fillable PDF with open slots as fields; returned-copy
  read-back.
- Ribbon: "Export PDF" stays the final PDF; "Export Fillable PDF" is added next to "Export DOCX".
- The chat's PDF file card is attached when Sage exports, as on the Inspection Sheet.

**SS4 - Sage.**
- `inspect_documentation_type` for the spec sheet returns the slots: rows, values, sources, open slots and flags,
  so Sage names exactly what is missing.
- `propose_specification_template(type, rows)`: stored as a proposal and shown in the workspace for approval (or
  "approve" in chat). It is not used until approved.
- `provide_document_values(documentType, values)`: chat values under the `said()` rule. This is the general
  version of `provide_inspection_sheet_values`; the Inspection Sheet keeps its own tool until a later cleanup.
- `record_researched_values(values: slot, value, researchId, sourceIndex)`: accepted only when that source was
  read in this turn; the URL and title are attached by the app, not by Sage.
- `draft_specification_text(slot, text)`: tagline, feature cards and headings, under the numbers-in-drafts guard.
- `search_public_sources` and `read_public_source` join the Documentation gateway behind the same flag, with the
  same 4-request limit and the same instructions. Only the machine's public make and model are searched; never
  customer or project data.
- The draft and publish browser workflows stay. The capture still runs in the browser after the reply, so the
  existing "Capture Product / Refresh Capture" and Sage's draft workflow keep working.
- Release-gate lines in the chat status; progress labels; tests.

**SS5 - library machines open as assemblies.**
- First, a quick check, done by hand with the Mori and one single-body model:
  - register the record;
  - open it with `?assemblyProfile=asset-...`;
  - confirm that the meshes map and that the automatic camera frames the capture (2200 px, technical white,
    isometric).
- Server adapter (`assembly_knowledge/library_machines.py`):
  - from `catalog-entry.json` and the GLB's node names, build an assembly profile with identity, category,
    dimensions, and one part occurrence per node (part number "Not specified");
  - a parts-manual catalog with the same occurrences, and a source revision from the GLB's hash;
  - `get_assembly_model` serves the asset's GLB for `asset-<id>`.
  - The opened machines are kept in a small registry file, so they are loaded with the library after a restart.
- Opening a machine:
  - a picker in Documentation, and in the Assembly tab's library list, searched by name and category;
  - Sage: `find_library_machines(query)` (read) and `open_library_machine(assetId)`, a queued browser workflow
    that opens it after the reply.
- Documentation readiness for a library machine: the Specification Sheet is available. The parts manual,
  operations manual, work instructions and inspection sheet say "a library model has bodies, not numbered parts".
- Stores, scenes and exports are keyed by `asset-<id>`, as they are by assembly number.

**SS6 - live test, then port.**
- In the test UI (:8491) with Sage on Codex, with research on in the test copy only:
  - Mori CL-200A CNC Lathe: Sage proposes the "CNC lathe" names, the user approves, Sage fills the footprint
    from CAD, researches a few published values with links, and leaves the rest open. The user clicks through
    in the viewport, then exports the final and fillable PDFs.
  - A forklift (Reversible-Fork Lift Truck): a second type template.
  - The 100001 engine: an assembly without a profile.
  - MMLE-50D regression: same page, the evidence values unchanged, SS0's edits in the PDF.
- Port to the real repo with the usual backup and byte check. The desktop research setting stays the user's
  choice (`.env` is never read or edited here without being asked).

## Risks and open points

- **Capture for a library machine** (the check at the start of SS5). The risk is small: the viewport already
  loads arbitrary GLBs, and the meshes map by node name. Two things could still need care:
  - a single-body model has nothing to explode;
  - a model in other units than metres would be framed oddly.
  The catalog dimensions show the library models are in metres.
- **Assembly-tab panes** that expect SolidWorks extraction data show nothing for a library machine. The
  part-properties crash on missing data was fixed with the Inspection Sheet (IS3).
- **Research quality.** A model name can match several variants (CL-200A vs CL-200B). Sage must name the variant
  it read, and the user accepts per value. With no access or a paywall, the slot stays open.
- **Text fit** in a one-page layout: long user text is the most likely export failure, so SS2 shows it early.
- **PyMuPDF licence review** is still pending, as for every exporter; no new dependency is added.

## Later

The same slots on the operations manual and the work instructions. Inspection Sheet values moved onto the
general `provide_document_values`. Decimal-place tolerance blocks for the Inspection Sheet. A shared template
library across customers.

## Status

- 2026-10-25: plan written. The user took the three recommendations, then chose to open library machines in the
  Assembly viewport (SS5 rewritten).
- 2026-10-25: approved ("apply the plan from start to finish"); building in the test copy, one commit per phase.
  - SS0 done (7806510): the exporters draw the viewport's edits (moves, sizes, styles, text) for PDF and DOCX.
  - SS1 done (127b8b8): slots, the values store, templates, CAD facts, the release gate, the routes; a sheet
    builds without a profile (engine 100001: CAD dimensions and weight, 8 open slots); MMLE-50D unchanged.
  - SS2 done: slots in the viewport, live-tested on :8491 (100001 and MMLE-50D). Click selects, double-click or
    Enter types in place, Tab moves on, Esc cancels; amber open slots; + Add row (keyed by the name typed in);
    the Inspector shows the source, the CAD or evidence value typed over, Revert, Accept, row moves, units and
    the gate. Found live: the page's drag handling swallowed click and blur, so presses are handled on
    pointer-up and an open editor commits on any press elsewhere; saves run one at a time without the overlay.
    The stores are `<root>/<subject>/slots.json` and `<root>/_templates/<type>.json` (named values.json and
    templates/ above).
  - SS3 done: the final PDF and DOCX leave open slots out (a row with an open value, an empty prose slot, a
    feature card with nothing in it); slot text shrinks to 70%, then the export names the slot that does not fit.
    "Export Fillable PDF" puts the open slots as amber fields named by slot id; "Return Filled PDF" fills slots
    still open (source returned_pdf); an empty field never clears, a slot filled since the export keeps its value,
    another assembly's copy is refused. Live-tested on :8491 with the engine. The chat file card comes with the
    Sage export tool in SS4.
  - SS4 done (tests; live with Codex in SS6): inspect_documentation_type returns every slot with its source and
    hint, the rows, the type, the approved types and whether the picture is current. New tools:
    propose_specification_template (sets the type; names used once approved; rows marked cad map to the CAD rows),
    approve_specification_template and accept_specification_values (only on the user's own yes this turn),
    provide_document_values (the said() rule, quote kept), record_researched_values (a read_public_source result
    of this turn; every number must be in what it returned; link, title and date attached by the app),
    draft_specification_text (wording slots only, no new numbers), edit_specification_sheet (rows, units, an
    approved type), export_specification_sheet (server export with the chat file card when the picture is
    current, else the publish workflow is queued). Public research joins the Documentation tools behind
    INSPECTORPRO_CODEX_WEB_RESEARCH. An approved type's names now keep the CAD rows they leave out. The workspace
    reloads after a turn that changed the sheet.
  - SS5 done (tests + live on :8491): library_machines.py reads the library's catalog.json (508 models with a
    GLB), searched by name, tags and category (walls, building elements and people left out). Opening one
    records it in <library>/library_machines.json and describes it as an assembly: one part per named mesh
    node (the Assembly viewer's loader keeps node names as written; an empty or shared name falls back to the
    whole model), the GLB as its model, identity with the GLB's sha256 so the source revision follows the
    model. Found while checking: 5 models (the Mori, an oven, a surface grinder, a band saw, a bar loader)
    carry a "buffer zone" body, the floor kept clear around the machine; it is left out of the parts, the
    overall size (Mori 3,392 -> 2,192 mm deep) and the 3D view and picture. A single-body model keeps whatever
    its one body holds (the Hardinge lathe's floor plate stays in its size). Entry points: machine-library
    items in the part search, a Library Machine button in the spec sheet's ribbon, an "Open a library machine"
    button on Documentation's empty page, and Sage's find_library_machines / open_library_machine (queued,
    runs after the reply, needs no loaded assembly). A library machine gets only the Specification Sheet (the
    type is set when it loads; other types refused with "a library model has bodies, not numbered parts");
    its weight stays open ("a library model carries no materials"). Live: Mori and Hardinge HLV opened from
    the part search and the picker, all bodies mapped, picture captured and framed, CAD size filled.
  - SS6 live run done on :8491 with Sage on Codex (gpt-6.1-sol, research on in the test copy only), 10 turns:
    - Mori CL-200A: Sage proposed 12 "CNC lathe" names and asked; on the user's yes it approved them, searched,
      read two public sources (a catalogue transcription and a dealer listing) and recorded 11 values with links,
      all unreviewed, the CAD footprint kept (101.5 x 86.3 x 90 in). It drafted the tagline and three features
      from the sheet's numbers. On "I checked them, accept them, export both" it accepted 19 slots and exported
      the review and fillable PDFs in one reply (two file cards).
    - Forklift (a model with no make or model): Sage opened it from the library itself (find + open, queued),
      proposed 12 forklift names as a second type, and on the user's yes kept every value open but the CAD
      footprint ("no exact manufacturer/model for reliable research"); the review PDF was published with the
      capture; the fillable PDF has 19 fields.
    - Haas ST-30: the approved "CNC lathe" names were reused for a second lathe (edit_specification_sheet with
      the approved type), 9 values recorded from haascnc.com, 2 left open that Haas does not print that way.
    - MMLE-50D: the golden PDF text is unchanged and its rows keep their layout heights at full size.
    - 100001 (no profile) was not run with Sage again: the gateway tests drive it through the real host, and the
      forklift and Haas runs took the same no-profile path live.
    Found and fixed (b24947c, 32ca2c3): researched values carried their qualifications into the cell ("330 mm
    (catalogue transcription; ... verify)") - a value is now the cell only (40 chars, raised to 120 on 2026-10-25
    with one list item per line, after the robot's six axis ranges were squeezed into 40) with the qualification in a
    note shown in the Inspector; the PDF gave every row the same height, so a two-line value refused the export -
    rows now grow to their text and the table draws smaller as a whole down to 70%; the PDF fonts draw Latin-1
    only ("10[8]" printed "10?8?") - dashes, quotes, primes and full-width brackets are drawn plain, anything else
    refuses naming its slot; two exports in one reply kept one card; a library machine's card was named by its
    asset id; the viewport did not shrink a table's open hints, row heights or cell padding, so 12 rows
    overflowed (forklift into the Features heading, Mori with red outlines); opening a library machine posted
    "0 features in profile"; drafted features carried caveats ("confirm the configuration") that would print.
    Known, not changed: a library model is not always true to size (the Haas ST-30 model is 190 in wide; its
    largest body is the machine itself, not a zone), and the sheet says the size is from the CAD model.
    Documentation opens with a blank page until Refresh or Generate Sheet, for every document (existing design).
  - Ported 2026-10-25 (port 14, bf5c093..dfbf9db, 19 files, uncommitted in the real repo; backup in
    Documents\InspectorPro-Backups\2026-10-25-before-spec-sheet-port). Real repo: the documentation, codex, spec
    sheet and library suites pass (544 passed). The desktop app was open from its normal shortcut, so whether it
    had unsaved work could not be checked: it was not restarted.
