# Private Gym First-Draft Review

Date: 2026-10-07

Historical first-pass record. The subsequent [detail pass](private-gym-detail-review.md) was explicitly approved for Save, saved, and reloaded successfully on the same date.

## Delivered State

The user's instruction to start authorized the separate 60 x 30 m concept layout. `fl-private-gym-20261007` is an empty saved sheet with an authored, unsaved equipment draft open in the normal Electron application. No equipment Save was performed; Factory 02 and all other existing saved layouts remain unchanged.

The draft contains 66 scheduled equipment/accessory/pool-table placements, six architectural placements, eight reception/lounge furniture placements, and one tile sample: 81 placements total. All 19 newly published gym asset types are represented. The three excluded imports remain absent.

There are ten functional subdivisions plus the building parent, seven connected pedestrian routes, perimeter walls, and reception branding. Rectangular packing adjusts the initial area targets as recorded in the plan. Support rooms are reserved, not equipped facilities.

## Implementation and Evidence

- `tools/build_private_gym.py` builds through the existing operation kernel and checks exact quantities, containment, footprint intersections, route blockage, and a conceptual 1.4 m pool-table cue allowance. It refuses to overwrite an existing Private Gym sheet.
- `desktop/tools/private-gym-entry.cjs` authors the draft through ordinary editor-session methods in the normal application. It does not Save equipment.
- `tests/test_private_gym.py` covers schedule, exclusions, connected routes, cardio orientation, and rejection of missing equipment, outside placements, intersections, and blocked paths. It uses an isolated test store and requires the private local library.
- Local evidence: `.runtime/private-gym-20261007/`, including initial candidate, native editor snapshot, spatial diagnostics, screenshots, saved-byte hashes, and `native-check.json`.

Native checks passed for Plan/3D rendering, all 81 loaded placement transforms, Undo/Redo of perimeter walls, unchanged saved bytes, and five walkthrough spawn locations. Wide and narrow canvas captures were nonblank. One observed cold 3D load took 7.6 seconds; this is not a performance benchmark. Continuous walking and sustained frame rate were not qualified.

After initial capture, visual and mesh inspection identified opposite headings in the cardio rows. Six ellipticals and six bikes were rotated 180 degrees using the native Rotate 90 command twice per group. The authoring recipe and regression test now match that correction. The original native snapshot and screenshots predate the correction and are retained unchanged, not relabeled as final-state evidence.

## Next Detail Pass

- Inspect each machine's working side, mounting, plate-loading and exercise envelope against applicable instructions. Footprint non-overlap is not operating-clearance qualification; spatial diagnostics retain unverified findings.
- Resolve compatible loaded-bar storage. Current bars are in designated floor bays outside authored paths.
- Furnish support rooms only after selecting appropriate catalog assets and defining the concept scope. Building services and compliance are not established.
- Prove a small connected floor-tile patch before expanding. The CAD suggests a 460 mm repeat within its 500 mm outer extent; the draft contains one sample, not full tiling. The colored mobility patch is provisional.
- Clean up visible floor-finish striping/depth artifacts and inspect routes at walking height.
- Walk all member routes and measure movement responsiveness with all CAD loaded. Current spawn checks do not substitute for this.

The current result is a reviewable first concept draft, not a finished or installation-qualified gym. Explicit user Save remains required.
