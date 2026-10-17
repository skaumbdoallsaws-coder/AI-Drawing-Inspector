# Private Gym Sports Extension

Date: 2026-10-07. Status: saved and reloaded in the normal Electron application.

## Saved Scope

- Original 60 x 30 m gym: all 93 existing placements, zones, routes and floor markings retained unchanged.
- East-side boxing annex: 22 x 16 m gross zone, actual 9.201 x 9.201 m CAD ring footprint, clear perimeter circulation, three wall-mounted bags and a training mat.
- Outdoor half court: 15 x 14 m playing area within a 19 x 18 m run-off pad, three dedicated mural walls and a wall-supported hoop.
- Connection: existing east gym door, boxing circulation, 2 m boxing-to-outdoor opening, then the open end of the court.
- Saved totals after the three-bag update: 106 placements and 13 zones. The original building perimeter remains fixed; new ground is an L-shaped extension rather than enclosing the outdoor court inside an enlarged building.
- Five supplied replacement artworks are embedded without cropping or editing. Boxing and wrestling artwork face each other. None of the earlier celebrity-poster choices were used.

## Models And Dimensions

The requested three-bag update added two copies at 2 m centre spacing on either side of the original bag. The existing 104 placements, mat, routes and other geometry were preserved. `tools/add_private_gym_boxing_bags.py` stages and revision-bound saves the change; native preview/reload evidence is in `.runtime/private-gym-three-bags-20261007/`. All 106 placements rendered with no missing placements or transform mismatches; 26 focused regression tests passed for this update.

The supplied STEP files retain their CAD scale. Hoop: 1.200 x 0.721 x 0.900 m. Ring: 9.201 x 9.201 x 2.360 m including stairs. Bag and bracket: 0.634 x 1.909 x 2.276 m after upright normalization.

The hoop has a measured 450 mm internal ring diameter. Its top is positioned at 3.05 m. The backboard is the supplied recreational 1.2 x 0.9 m model, not a regulation-size replacement.

Court geometry uses [FIBA's 2024 rules](https://assets.fiba.basketball/image/upload/documents-corporate-fiba-official-rules-2024-v10a.pdf) and [equipment dimensions](https://assets.fiba.basketball/image/upload/documents-corporate-fiba-official-rules-2024-official-basketball-rules-and-basketball-equipment.pdf) as references. Editable 50 mm line primitives form the boundaries, key, free-throw circle, three-point arc, restricted-area semicircle and half-court circle. Arcs are sampled into short segments. This is a recreational concept, not competition certification.

Native bag extraction used the installed SolidWorks COM API, read-only. It retained 108 visible component instances / 114 mesh bodies and excluded four hidden components, including the source walls. All visible faces were required to tessellate. A custom compiled helper was blocked by Windows and was not used; no security setting was changed.

The STEP exporter emitted one empty assembly-container mesh with invalid -1 accessors for the ring. Only that empty container was removed; valid geometry, node transforms and binary payload were retained. This cleanup has a regression test.

## Attachment Contract

`wall_attachment` records the exact support placement and asset revision, selected +/-Z face, local X/Y and a bounded mounting gap. Deterministic checks require upright, unscaled geometry, canonical child frames, face alignment and projected contact. Missing supports, changed revisions, wrong orientation, cycles, unrelated collisions and floating equipment remain failures.

The authored hoop support is a concept cantilever. Wall mounting reports `wall_attachment_safety_unverified`; it does not establish anchor strength, structural capacity, impact protection, weather resistance or installation compliance. Editing a supporting placement without updating its dependent attachment invalidates the relationship at validation; this work does not add an automatic reattachment UI.

## Verification

- 171 focused, spatial, perimeter, schema and operation tests passed; one existing performance test was skipped.
- Existing operation engine and service Save validated the candidate in an isolated store before publication.
- Normal desktop preview captured the court, boxing ring, bag, both boxing artworks and aerial context. Canvas-pixel checks were nonblank.
- Saved reload matched the exact saved document, with 104 rendered placements, zero missing placements and zero transform mismatches.
- Read-only Playwright checks captured the saved Plan and 3D views and completed six continuous walking legs from the existing gym through the boxing room and outdoor doorway to the court. Normal viewport focus and pointer lock were required; saved bytes remained unchanged.
- Compact-window coverage is not established: Electron viewport emulation stalled capture, and its CDP implementation does not expose native window resizing. Full-size desktop captures and the continuous route passed.
- Other saved layout documents were unchanged. The gym's registry entry updated as part of the ordinary Save.
- Evidence: `.runtime/private-gym-sports-20261007/` contains source receipts, operations, spatial findings, before/candidate/saved documents, native and Playwright screenshots, `native-check.json` and `playwright-check.json`.

## Owners

- `tools/import_private_gym_sports.py`: source conversion and canonical library preparation.
- `tools/export_visible_gym_assembly.ps1`: read-only visible-component native extraction.
- `tools/expand_private_gym_sports.py`: staged authoring, validation, publication and reconciled revision-bound Save.
- `ai_inspector/facility_layout/wall_attachments.py`: geometric mounting validation.
- `tests/test_private_gym_sports.py`, `tests/test_facility_wall_attachments.py`: focused acceptance and refusal cases.

This is user-directed layout authoring, not qualification of a new autonomous Sage capability.
