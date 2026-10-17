# Private Gym Exterior

Date: 2026-10-07. Status: saved and reloaded in the normal Electron application.

## Saved Scope

The supplied exterior reference informed charcoal panel faces, narrow gold accents and a light stone-color backing for the Apex emblem beside reception. The supplied Discipline Builds Freedom and Higher Everyday artwork occupies separate exterior wall sections. Seven outward-facing basketball and boxing annex wall faces receive the same charcoal finish without changing their interior artwork.

All 106 existing placements, physical wall geometry, door openings, interior murals, zones and routes are unchanged. Other saved layout documents are unchanged. This is a visual finish, not a structural or material-performance claim.

Original PNG bytes are retained in content-addressed files under `generated/facility-wall-art/`. UV framing excludes transparent export padding, and the visible artwork retains its aspect ratio. No generated replacement artwork is used.

## Contract And Owners

- `ai_inspector/facility_layout/wall_finishes.py` validates optional `facilityPerimeterWalls.settings.exteriorFinish`: colors, bounded panel dimensions, artwork source paths and UVs, wall-edge extents, opening exclusions and exact placed-wall references.
- `ai_inspector/facility_layout/perimeter_walls.py` retains the finish through perimeter configuration and validates it with the existing wall geometry.
- `static/facility_layout_walls.js` derives outward visual surfaces and exposes an Exterior finish checkbox and Exterior color swatch in perimeter-wall settings. Disabling the finish also removes its artwork and accents.
- `static/facility_layout_three_adapter.js` renders batched finish geometry and locally sourced artwork, tracks texture readiness, respects wall visibility and disposes resources. Finishes add no collision volumes.
- `tools/style_private_gym_exterior.py` stages, audits and revision-bound saves this user-directed layout update. It is not a new autonomous Sage capability.

Placed-wall finishes bind to exact placement and asset-definition revisions. A changed or deleted support requires updating the finish binding; this does not implement automatic artwork remapping.

## Verification

- 122 Python tests passed across finish, perimeter, operation, schema and wall-attachment coverage.
- The existing 3D adapter suite passed 105/105 checks; all five wall-module JavaScript tests passed.
- Native previews covered the exterior, emblem and both quotes. Saved reload matched the exact saved document.
- Reload diagnostics reported all three artwork textures ready, 15 finish objects, all 106 placements rendered, zero missing placements, zero transform mismatches and no warnings.
- A separate read-only Playwright viewport/dialog check could not enter the desktop-authenticated backend (HTTP 401). Compact/mobile rendering and live wall-dialog interaction are not qualified by that attempt; no authentication controls were changed. Native full-size screenshots and saved-reload checks passed independently.
- Evidence is retained in `.runtime/private-gym-exterior-20261007/`, including before/candidate/saved documents, operations, source receipts, native screenshots and `native-check.json`.

The associated sports extension is documented in [private-gym-sports-extension.md](private-gym-sports-extension.md).

## Basketball Interior Follow-Up

At the user's request, the three basketball court wall placements now use the adjoining boxing room's light color (`#deddd7`) instead of their original dark blue-gray. `tools/lighten_private_gym_court.py` applies the existing `set_appearance` operation, audits that only these three appearances and the update timestamp change, and uses revision-bound Save. Exterior face finishes, original mural assets, court markings and geometry remain unchanged. Native preview and saved-reload evidence is in `.runtime/private-gym-light-court-20261007/`.
