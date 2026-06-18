# Drawing Planner MVP Plan

Saved: 2026-05-28

## Purpose

Build the first read-only planning layer for AI-assisted drawing revision work.

The goal is not to let Sage autonomously create or release drawings yet. The goal is to let InspectorPro understand an existing part, its named dimensions, its semantic regions, and its current drawing enough to:

- identify which dimensions should appear on a drawing,
- understand which model feature or sketch each dimension belongs to,
- avoid obvious duplicate dimensioning,
- assign dimensions to the most appropriate drawing views,
- validate an existing drawing for missing, duplicated, crowded, or unsupported checks,
- prepare a structured drawing plan that can later be handed to the SolidWorks add-in.

This is a planning and validation layer only.

## Scope

MVP target part: `1030035`.

Reason: current curated dimension data is strongest on this part family. The planner must degrade gracefully for other parts and return warnings instead of pretending it has complete model understanding.

Main app only:

- Add Python modules under `ai_inspector/drawing_planner/`.
- Add read-only endpoints in `server.py`.
- Add tests around the planner outputs.

No SolidWorks writes in this phase.

## Non-Goals

- No automatic drawing creation.
- No automatic dimension placement in SolidWorks.
- No section-view or detail-view creation.
- No autonomous ASME compliance claim.
- No tolerance or GD&T invention.
- No production release workflow.
- No SolidWorks command execution from this planner.

The planner can recommend and validate. It cannot authoritatively release.

## Current Data Reality

### Strong Inputs

- `semantic_regions.json`
  - Rich region labels and aliases.
  - Region-to-feature mapping.
  - `axisFrame` with length/lateral/vertical axes and ranges.
  - Best available signal for view assignment.

- `sketch_dimension_intent_map.json`
  - Curated named dimensions for `1030035`.
  - Good bridge from physical phrases to SolidWorks sketch dimensions.
  - Good for demo-grade dimension understanding.

- Existing drawing maps
  - Drawing annotations may carry dimension values and drawing locations.
  - This is currently the best source for numeric values when CAD-side dimension values are missing.

### Weak or Missing Inputs

- `dimension_intent_map.json`
  - Exists in some places but currently has little or no useful mapping coverage.

- `part.json cadDimensions`
  - Not available yet as a complete CAD-side dimension list.
  - Needed later for precise CAD dimension values and no-drawing dimension coverage.

- `semantic_regions.cadTargets.dimensions`
  - Currently mostly empty.
  - Region-to-dimension linkage relies on the sketch dimension map for now.

- Section/detail drawing geometry
  - Current extractor intentionally skips fragile geometry extraction for section/detail views.
  - Validation must mark those checks as skipped when geometry is unavailable, not as passed.

## Required Module Structure

Create:

```text
ai_inspector/drawing_planner/
  __init__.py
  schema.py
  model_context.py
  dimension_candidates.py
  redundancy.py
  view_planner.py
  validation.py
  references.py
```

### `schema.py`

Define plain dictionaries or Pydantic-compatible structures for:

- model context
- dimension candidate
- redundancy finding
- view assignment
- validation issue
- references used
- drawing plan document

Candidate fields should include:

```json
{
  "dimensionFullName": "D1@Sketch_MountingPlate_OverallSize",
  "dimensionShortName": "D1",
  "sketchFeature": "Sketch_MountingPlate_OverallSize",
  "cadFeatureId": "boss_mountingplate",
  "sourceFeature": "Boss_MountingPlate",
  "regionId": "mounting_plate",
  "regionLabel": "Mounting Plate",
  "physicalName": "mounting plate length",
  "controlType": "length",
  "axis": "length",
  "units": "mm",
  "valueKnown": true,
  "value": 114.3,
  "valueSource": "drawing_map",
  "confidence": "high",
  "reviewed": true,
  "sources": ["sketch_dimension_intent_map", "drawing_map"]
}
```

`value` must not be required. `valueKnown` must be first-class.

### `model_context.py`

Load the available per-revision artifacts:

- semantic regions
- feature intent map if present
- sketch dimension intent map if present
- dimension intent map if present
- drawing map if present
- inspection profile if useful

Reuse existing loaders where possible, especially from `ai_inspector.dimension_intent`, instead of re-implementing duplicate artifact-loading logic.

Output:

- `partNumber`
- `revision`
- loaded artifact summaries
- semantic regions
- axis frame
- warnings for missing optional artifacts

Missing optional artifacts should not fail the request.

### `dimension_candidates.py`

Build candidate drawing dimensions primarily from:

1. `sketch_dimension_intent_map.json`
2. existing drawing map annotations
3. feature intent map when it can add physical wording
4. dimension intent map when it becomes useful later

Rules:

- If a drawing annotation can be matched to a candidate, use the drawing annotation value and set `valueKnown=true`.
- If no value is available, set `valueKnown=false`.
- Preserve curated/reviewed entries.
- Do not guess between equal-value or ambiguous dimensions.
- Do not assume `controlType` is unique within a region.

Important data-quality warning:

- If a candidate has `controlType="angle"` but `units="mm"`, emit a warning. Do not silently trust the units.

### `redundancy.py`

Primary uniqueness key:

```text
dimensionFullName
```

This is the only key that should produce hard duplicate findings.

Do not use `{regionId}.{controlType}` as a hard key. Real data has valid collisions:

- `mounting_slots` can have multiple spacing dimensions.
- `swivel_race` can have multiple diameter dimensions.

Use `{regionId, controlType, axis}` only as a soft review signal:

```text
warn: possible_duplicate_design_intent
```

Never auto-reject dimensions because they share a control type.

### `view_planner.py`

Assign each candidate to a preferred drawing view using deterministic rules.

Use `semantic_regions.axisFrame` as the main geometry signal:

- length dimensions prefer the view where the length axis is visible and not foreshortened.
- width/lateral dimensions prefer the view where the lateral axis is visible.
- thickness/depth dimensions often prefer side/front/section views depending on feature type.
- hole/slot sizes prefer the face view where the feature shape is visible.
- internal features may recommend section/detail views, but only as recommendations.

The planner should output assignments, not SolidWorks operations.

Example:

```json
{
  "dimensionFullName": "D1@Sketch_MountingPlate_OverallSize",
  "preferredView": "top",
  "reason": "Mounting plate overall length is best shown on the plate face view.",
  "confidence": "high"
}
```

### `validation.py`

Validate an existing extracted drawing against the candidate set.

Validation results must support:

- `pass`
- `warn`
- `fail`
- `skipped`

Checks:

- missing design-intent dimensions
- duplicate exact `dimensionFullName`
- soft duplicate design intent
- annotation overlap when geometry is available
- title-block obstruction when bounds are available
- dimensions without sheet positions
- section/detail geometry unavailable

Critical rule:

If a section/detail view lacks usable geometry, emit:

```text
skipped: geometry_unavailable_section_detail
```

Do not report "no overlap" as a pass when geometry was unavailable.

### `references.py`

Add a small static checklist reference layer.

This should not claim ASME compliance. It should produce cautious references such as:

```json
{
  "title": "Internal drawing best-practice checklist",
  "sourceType": "internal_checklist",
  "section": null,
  "reasonUsed": "Used to check for duplicate dimensions and crowded annotation layout.",
  "confidence": "medium"
}
```

If external standards are used later, the system must cite only sections that were actually retrieved and used.

## Endpoints

### Draft Drawing Plan

```http
POST /api/drawing-plan/{partNumber}/draft
Content-Type: application/json

{
  "sourceRevision": "A",
  "targetRevision": "B",
  "instruction": "create a new drawing revision following the standard"
}
```

Writes:

```text
400S_Sorted_Library/parts/{pn}/{rev}/{pn}_drawing_plan.json
```

Response includes:

- `ok`
- `partNumber`
- `sourceRevision`
- `targetRevision`
- `candidateCount`
- `warnings`
- `outputPath`
- `referencesUsed`

### Read Drawing Plan

```http
GET /api/drawing-plan/{partNumber}?revision=A
```

Returns the saved drawing plan document.

If missing, return `404` with a clear hint to call `POST /draft`.

### Validate Existing Drawing

```http
POST /api/drawing-plan/{partNumber}/validate-existing
Content-Type: application/json

{
  "revision": "A"
}
```

Response includes:

- candidate summary
- validation issues
- skipped checks
- references used
- warnings

This endpoint is the most valuable MVP output because it can work without writing to SolidWorks.

## Saved Drawing Plan Schema

```json
{
  "schemaVersion": "drawing-plan-0.1.0",
  "partNumber": "1030035",
  "sourceRevision": "revA",
  "targetRevision": "revB",
  "createdAtUtc": "2026-05-28T00:00:00Z",
  "instruction": "create a new drawing revision following the standard",
  "modelContext": {
    "semanticRegionCount": 11,
    "axisFrameAvailable": true,
    "warnings": []
  },
  "dimensionCandidates": [],
  "viewAssignments": [],
  "redundancyFindings": [],
  "validationSummary": {
    "passCount": 0,
    "warnCount": 0,
    "failCount": 0,
    "skippedCount": 0
  },
  "referencesUsed": [],
  "warnings": []
}
```

## Tests To Add

Add a new test file, likely:

```text
tests/test_drawing_planner.py
```

Required tests:

1. Context builds on `1030035`.
2. Missing optional files return warnings, not crashes.
3. Candidates are built from `sketch_dimension_intent_map`.
4. Drawing map values set `valueKnown=true`.
5. Missing values set `valueKnown=false`.
6. Exact duplicate `dimensionFullName` is flagged as a hard duplicate.
7. Same `controlType` within a region is not auto-rejected.
8. `SlotPitchX` and `SlotPitchY` both survive candidate building.
9. Multiple `swivel_race` diameter dimensions survive candidate building.
10. `angle` with `mm` units emits a warning.
11. View planner uses `axisFrame`.
12. Section/detail missing geometry is reported as skipped.
13. `validate-existing` returns pass/warn/fail/skipped structure.
14. `draft` writes `{pn}_drawing_plan.json`.
15. No SolidWorks handoff, drawing write, or CAD write code is introduced.

## Future Extractor Work Needed

For a later placement/write phase, the extractor should add:

1. `cadDimensions` in `part.json`
   - dimension full name
   - short name
   - owner sketch/feature
   - value
   - units
   - driving/driven flag
   - feature linkage

2. Region-to-dimension linkage
   - populate `semantic_regions.cadTargets.dimensions`, or
   - keep `sketch_dimension_intent_map` as the official bridge.

3. Better section/detail view geometry extraction
   - only if safe and stable.
   - until then, validation must label geometry-dependent checks as skipped.

## Later Phases

### Phase 2: Drawing Handoff To SolidWorks

After the read-only planner is stable:

- create a drawing revision session log,
- send a constrained drawing handoff to the SolidWorks Sage pane,
- preview the drawing plan,
- let the operator approve a narrow drawing action.

### Phase 3: Screenshot Review Loop

After SolidWorks can create or update drawings:

1. export drawing screenshot/PDF,
2. run visual validation,
3. check for overlapping dimensions, crowding, title-block intrusion, missing callouts,
4. send constrained correction handoffs,
5. repeat until checks pass or max iterations is reached,
6. mark as ready for human review.

### Phase 4: Standards/RAG Guidance

Use RAG/checklists to guide decisions.

The summary should include references used, but only cite references actually retrieved and applied.

Do not claim ASME compliance unless the exact requirement was retrieved, applied, and validated.

## Implementation Principle

Build the "understand and validate" layer first.

Do not build the SolidWorks drawing writer until the planner can explain:

- what dimensions matter,
- what each dimension controls,
- which view each dimension belongs in,
- which checks were passed,
- which checks were skipped because data was unavailable.

