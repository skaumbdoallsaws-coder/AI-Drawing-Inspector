# Factory 02: Perimeter Walls

September 28, 2026. Authored geometry around the perimeter highlighted by the
user, on Factory 02 only. This is not a new autonomous Sage capability or a
building-design approval.

## Saved Geometry

- Six locked structural placements, using three shared generated box GLBs.
- Height 6 m; thickness 0.25 m; 0.01 m corner panel joints. These are authored
  concept dimensions, not measured construction specifications.
- Openings on both east and west sides, from Z=91 to Z=106 m, span the main
  aisle and adjacent pedestrian lanes. No door leaves or roof were added.
- The perimeter follows the existing floor, approximately 300.015 by 200.040 m.
- Original 830 placements, 52 zones, nine aisles and 90 markings are unchanged.
  Six narrow wall-footprint regions were added, giving 836 placements/58 zones.
  The existing generic equipment-area zone type represents those footprints;
  no placement `zoneId` was added. Walls are categorized Building Structures.
- All 144 prior catalog records are unchanged. Three authored wall records are
  appended; no manufacturer, process or safety evidence is attributed to them.

Before revision: `4d3d7213064ee5a999e3b14e8771aff648e7dddf2b1d80515a33bb80cddabc7c`.
Saved revision: `a217107d22b3d78b6fa186d532138d8d8a169280c47a1a39d4a568eb2dcac3a0`.

## Checks

75 focused Python tests passed, including 13 new wall tests. The deterministic
GLB exporter and inspector are reused; all three meshes have 12 triangles and
validated finite bounds. Only 72 rendered triangles are added across six walls.

The existing authoritative service reports zero placement collisions, shell
collisions, obstructed aisles or spatial errors. A deliberately overlapping
placement is rejected by the collision calculation. Both perimeter openings
and every existing aisle are checked geometrically against the wall footprints.

There are still 3,367 unverified findings, including the original missing
clearance evidence. Zero collisions is not structural, fire, exit, operational
or building-code approval. Outdoor walkthrough remains bounded by the existing
facility floor; an opening does not add an outdoor navigation domain.

Native Electron review passed and is recorded under `native/native-check.json`:

- Eight screenshots cover Plan, the open-top perimeter, a wall corner, an aisle
  opening and a narrow desktop window. The four wall screenshots were visually
  inspected; canvas-only pixel checks passed for the six visible 3D captures.
- All 836 placement transforms match the persisted document; all three wall
  mesh groups load as real overview GLBs. No geometry-renderer changes were needed.
- Native walkthrough sees all 836 obstacle footprints. A requested spawn at
  X=0.35/Z=50 is moved clear of the wall, while X=0.4/Z=98 in the opening remains
  unchanged. This tests collision-aware spawn, not a complete walking trajectory.
- Original and updated layout bytes remain unchanged during native review;
  switching between the original manual sheet and Factory 02 passes.

## Preservation And Recovery

`tools/add_independent_factory_walls.py` defaults to an isolated dry-run and
refuses any different Factory 02 base revision. It stages assets and validates
the candidate before publishing the additive catalog update and saving through
the existing revision-bound service. Failed publication restores its own catalog
update only if no concurrent catalog/layout update has occurred.

Evidence lives in `.runtime/independent-factory-walls-20260928/`. The `applied/`
directory contains the original catalog bytes, previous layout, operations,
candidate, saved layout, generated meshes and validation results. Earlier failed
dry-runs remain separate: one encountered Windows long paths; another correctly
rejected service-clearance zones and touching independent wall objects. Neither
changed the live layout. The implementation now uses the existing long-path
helper, generic equipment-footprint regions and explicit panel joints.

This offline Save does not add an Undo entry to an already-open editor. Walls
use ordinary placements and can be unlocked/edited with existing tools after
loading the new revision. Existing windows are not force-reloaded or closed.
Restart the desktop app after resolving unsaved work to load the new catalog.

The original manual layout and default-sheet choice are preserved. Original
SHA-256: `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
No provider calls were used.

## User-Window Loading Follow-Up

Screenshot `13.png` showed six small fallback cubes at the wall centers. The
running window was the earlier Layer 2 review application on port 8510, whose
backend started before the three wall definitions were published. The host
builds `_catalog` and `_asset_versions` at initialization; sheet reloads can
therefore read the newer saved layout without learning its newly added assets.
The viewport then lacks the wall dimensions and mesh references. This is a
stale catalog, not a failed wall GLB or changed placement transform.

The earlier isolated native pass did not refresh this already-open user window.
Restarting the backend, not merely reloading the sheet, is necessary with the
current catalog lifecycle. No hot-reload capability is claimed by this fix.

An additional read-only relaunch check uses the ordinary application profile
on port 8480, retaining its normal permissions and storage identity. Evidence is
under `user-relaunch/`; it selects Factory 02 and leaves the window open after
checking the exact saved document, six walls, three real mesh groups, and both
layout hashes. The previous window is not forced closed or its draft discarded.

This ordinary-profile check passed: 836 rendered placements, all six wall
instances in three real overview mesh groups, zero transform mismatches, and
no degraded render state. `user-relaunch/factory-walls.png` was visually
inspected and shows the complete perimeter and both aisle openings. Both saved
layout hashes are unchanged. The ordinary application is left open on Factory
02 in 3D. No application source or saved geometry was changed in this follow-up;
the earlier 75-test result was not rerun.
