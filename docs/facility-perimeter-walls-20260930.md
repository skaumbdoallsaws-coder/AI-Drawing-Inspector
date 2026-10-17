# Facility Perimeter Walls

Implemented September 30 - October 1, 2026. This report covers wall visibility and reusable perimeter authoring, not building-code compliance or a new Sage capability.

## Controls

- In Plan or 3D, open **Layers** and toggle **Walls**. This is independent of Assets and does not change the draft revision. Hidden walls remain physical obstacles.
- Choose **Perimeter walls...** in the same panel to create, edit, or remove generated walls.
- Use the facility plan boundary for rectangular walls that follow plan resizing. Alternatively, select a zone and use its boundary as a polygon snapshot. Existing polygon walls can reuse their saved boundary.
- Set height, thickness, and full-height openings. Opening distances run along the selected edge from its displayed first endpoint, in metres.
- Apply and Remove are ordinary unsaved, undoable gestures. Save remains explicit. Wall authoring is unavailable in read-only, busy, conflicted, or proposal-preview states.
- Save any current work and reopen InspectorPro to load both the updated backend operation and frontend assets.

Existing Factory 02 walls are tagged catalog placements. They now respond to the Walls toggle but are not converted or automatically resized. Creating a second plan perimeter over these tagged perimeter assets is refused to avoid duplication. No existing saved layout was migrated or edited.

## Supported Geometry

The reusable compiler accepts the rectangular plan boundary or a simple polygon with 3-128 vertices, including rotated and concave boundaries. Polygon boundaries are snapshots, not live links to zones. Later zone edits do not silently move walls.

Walls straddle the boundary centreline. Height is 0.5-30 m; thickness is 0.05-2 m. Up to 128 nonoverlapping edge openings are supported, each at least 0.1 m wide. Self-intersections, holes, and thicknesses that eliminate or split the interior are rejected. Curved walls, roofs, windows, multiple floors, and arbitrary CAD-derived boundaries are outside this slice.

`layout.extensions.facilityPerimeterWalls` stores versioned settings and deterministic triangular panels. Shapely 2.1+ compiles the buffered ring and openings. Validation recomputes panels and rejects forged or stale geometry. `set_perimeter_walls` joins the existing atomic operation kernel; `set_plan_settings` recompiles plan-bound walls or rejects an invalid resize atomically.

Plan and Three.js render the same compiled panels. Effective shell features expose the walls to existing placement validation and indexed aisle obstruction checks. Aisle findings retain the existing advisory severity. Walkthrough and drone navigation receive wall obstacles independently of layer visibility. Hidden objects are excluded from picking; scene cleanup disposes generated meshes.

## Implementation Owners

- Backend: `perimeter_walls.py`, `operations.py`, `plan_settings.py`, `validate.py`, and `spatial.py` under `ai_inspector/facility_layout/`.
- Frontend: `static/facility_layout_walls.js`, session/workspace integration, Plan editor and Three adapter, workspace styles, and script loading in `static/index.html`.
- Regression coverage: `tests/test_facility_perimeter_walls.py`, `tests/test_facility_layout_walls.js`, and existing editor/Three suites.
- End-to-end harnesses: `desktop/tools/facility-walls-entry.cjs` and `tools/verify_facility_walls_browser.py`.

## Verification

The final focused JavaScript run passed **295 checks**: editor 38, session 61, Three adapter 94, workspace 99, and wall helpers 3. The Node runner aggregates older custom suites, so its top-level test count is not the individual-check total.

The final Python run passed **122 tests, with 1 skipped** across perimeter walls, plan settings, operations, and spatial suites. The skip is the existing opt-in spatial performance test. Coverage includes concave/rotated geometry, invalid inputs, stale panels, openings, placement and aisle obstructions, atomic resize rejection, Undo, and isolated repository Save/reload.

Native Electron checks used the ordinary application runtime with an isolated managed backend and copied data:

| Evidence | Result |
| --- | --- |
| `.runtime/facility-walls-20260930/native03/` | Factory 02 loaded all 850 placements; all six tagged legacy walls hid and reappeared without changing document or revision. |
| `.runtime/facility-walls-20260930/native06/` | Actual dialog created a concave polygon perimeter with an opening; Plan/3D agreed; visibility preserved document/revision and walkthrough obstacles; Undo restored the exact base; plan-bound walls followed resize and both gestures undid exactly. |
| `.runtime/facility-walls-20260930/browser03/` | Playwright at 1440x900 and 390x700 verified nonblank wall rendering, visible/hidden pixel differences, camera interaction, and a fitting settings dialog. The narrow check is a component test, not full-application mobile qualification. |

Native screenshots were inspected at 1440x900 and 900x700 logical window sizes. Final native cleanup confirmed backend termination, closed resources and stdio, and exit code 0. Native scenarios made no Save calls and preserved their saved documents. Persistence was tested separately in temporary repository tests.

Earlier harness failures are retained: native01/native02 had fixture setup issues; native04 had an unregistered fixture layout; browser01/browser02 lacked a required camera-settings script. Corrected runs passed. Native06's `00-wall-settings.png` captured before dialog paint and is not dialog visual evidence; use the browser03 dialog captures. These were harness issues, not claims of successful checks.

Scoped `git diff --check` passed. Live saved-layout SHA-256 values remained unchanged:

```text
Factory 02:       e8433641ed1c870b23aed9bd71c87c762a919f877c8d423aa25a27e3f7ceb9eb
Manual reference: a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088
```

No provider requests were needed. The user's running desktop application was not restarted or closed.
