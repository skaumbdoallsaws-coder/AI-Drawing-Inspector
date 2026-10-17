# Private Gym Detail Review

Date: 2026-10-07. Status: saved and verified in the normal desktop application after explicit user authorization.

## Changes

- Preserves all 66 scheduled equipment/accessory/pool-table items and their recipe identities and transforms.
- Adds eleven support furnishings: two changing benches, two towel cabinets, two sinks, one wash-area bench, a staff desk and chair, a storage cabinet and drawers.
- Adds a 140-tile mobility mat from the user's unchanged CAD at a measured 460 mm repeat. The joined model contains 10,640 triangles, one mesh, and approximately 29.624 m2 of actual tile coverage. This deliberately remains a smaller patch than the initial 120 m2 proposal; it is not evidence that the original flooring target was installed.
- Widens the concept support-room entrance gap and adds changing, wash-area, staff and cardio access branches. Eleven authored routes form one connected network.
- Cuts floor finishes around circulation and the physical mat. No solid finish rectangles overlap each other or the authored route corridors.
- Changes rectangular 3D floor paint from thin boxes to horizontal planes, eliminating opposing faces that compete for depth. Aisle yaw still rotates the already-horizontal geometry. The fallback for minimal test renderers remains a thin box.

The resulting layout contains 93 placements. The mat is one derived catalog asset, not 140 independent library downloads or a rescaled approximation.

## Checks

`tools/detail_private_gym.py` builds using the existing operation kernel, validates the original equipment schedule, connected path geometry, containment, furniture intersections and finish intersections, and records a nearest-footprint-gap audit for every scheduled item. The smallest equipment gap is approximately 0.73 m between dumbbell racks; it is not an operating-clearance acceptance threshold.

The 2 x 2 tile joining test uses a 0.1 micrometre geometric tolerance to eliminate floating-point seams. It verifies no holes, connectivity and negligible duplicate coverage. Original CAD vertices are not changed by this tolerance; the repeated GLB uses only translations and no scaling.

Local automated results: 13 Python gym tests and 105 renderer tests passed. The tests use isolated stores where applicable. The private CAD library is not distributed as a public fixture.

Native evidence is recorded under `.runtime/private-gym-detail-20261007/`. The desktop driver checks actual loaded CAD, canvas content, Undo/Redo, continuous walking, saved-state isolation, and a candidate-bound approval before Save. Final native results must be read from `native-check.json`, not inferred from the geometry tests.

The native run finished `saved-and-verified`: all 93 placements loaded with no transform mismatches or degraded renderer, wide/narrow captures were nonblank, perimeter-wall Undo/Redo restored the exact document, and the avatar reached all eleven continuous-walk destinations within 0.3 m. The observed cold 3D load was 9.009 seconds, a single observation rather than a latency qualification. Captured cardio, mobility, changing and staff views were inspected; the earlier floor striping was absent.

The normal session Save persisted the reviewed document. Reload matched the saved document exactly and left the editor clean. All other saved layouts, including Factory 02, retained their previous bytes. The report's `savedRevision` field in this run is a SHA-256 of the saved file bytes, not the repository's canonical revision identifier.

## Remaining Boundaries

- Toilets, showers and actual lockers have not been found in the library. The sinks, benches and ordinary storage cabinets do not substitute for those fixtures.
- The existing Hideaway Cabinet model is a utility-style, open-top unit. Its final support-room purpose and suitability for towel handling still need review; it is not a verified clean-linen cabinet or locker.
- Manufacturer-specific machine entry, exercise travel, plate-loading, servicing and overhead clearances remain unqualified. Generic Mach1 and Model identities are still unresolved.
- Loaded bars remain in designated floor bays, pending a compatible storage solution.
- Mat edge trim, transitions, friction, material properties, accessibility, egress and building services require separate review. A CAD walkthrough is not installation approval.
- The earlier review window was retained to avoid destroying its unsaved state during the detail pass. The current saved window contains the revised 93-placement layout; an older 81-placement unsaved window is no longer the current version.
