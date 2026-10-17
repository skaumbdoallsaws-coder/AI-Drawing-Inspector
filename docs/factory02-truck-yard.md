# Factory 02 Truck Yard

Implemented and saved on October 2, 2026. This is a geometric layout concept, not an approved dock, traffic, structural, drainage, or safety design.

## Saved layout

- Factory 02 now contains 1,078 placements.
- Receiving: two 40-foot container trucks and one smaller 20-foot container truck at three loading bays.
- Shipping: the same three-bay arrangement.
- Holding: two large-truck and two smaller-truck spaces.
- West yard: 82 m extension, pavement 1.35 m below the factory floor. Combined ground bounds are 458 m by approximately 200.04 m.
- Six 4.5 m wall openings, dock bumpers, steel-colored bridge surfaces, bay labels and one-way circulation markings.
- Central aisle remains open, connected by a 24 m long, 8 m wide ramp rising 1.35 m.

The two original west wall placements were replaced with eight opening-aware segments. The other 1,048 original placements, all existing zones/routes/markings, and all 40 movement programs were preserved. The original manual reference and 49 other saved layouts are byte-for-byte unchanged.

Saved layout: `fl-independent-factory-20260928`.

Saved revision: `ddb1120745f382c756361841f9fe1739c261eb922ec5191464ccfa7fab31637e`.

## Height and model evidence

Cargo-floor measurements come from transformed CAD triangles, not manufacturer specifications:

| Model | Cargo floor above tire-ground | Cargo floor relative to factory |
| --- | --- | --- |
| 40-foot container truck | 1.300000 m | -0.050000 m |
| 20-foot container truck | 1.374601 m | +0.024601 m |

One-metre bridge surfaces connect those levels to the factory floor. Contact placement includes 1 mm clearance to avoid crossing the bridge boundary after canonical coordinate rounding.

The original 40-foot model was articulated. A separate library asset, `asset-truck-40ft-container-straight`, rigidly rotates the trailer/container into line with the cab without scaling. Its visual pivot is inferred from the intersecting chassis axes; it is not a qualified steering model. The source GLB and original catalog asset remain unchanged. The derived truck measures approximately 2.55 m wide, 15.875 m long and 3.792 m high.

## Reusable ground contract

`extensions.facilityGround` schema version 1 describes non-overlapping rectangular flat surfaces and straight ramps, with stable IDs, metre coordinates, endpoint elevations, slope axis and color. It replaces the legacy single floor only when explicitly present.

- `ground.py` validates bounded finite geometry and supplies authoritative support regions.
- `set_ground` uses the atomic operation kernel. Null restores the ordinary plan floor.
- Adjacent coplanar tiles can support a placement together. Gaps, sloping support and wrong placement elevations are rejected.
- Ordinary plan resizing cannot silently replace explicit ground levels. Grid settings remain editable; boundary changes require a ground operation.
- Plan fitting and cursor projection include the lower yard. Three.js renders actual ground levels and ramp meshes, rather than a painted imitation.
- Walking samples the same surfaces and stops at abrupt drops. The existing navigation planner remains planar: a requested path over a drop can stop as blocked; automatic detouring through a ramp is not qualified here.
- Drone movement also rejects an endpoint below the ground surface. Existing movement programs remain unchanged; the ten new parked trucks have no new motion programs.

This first ground contract is rectangle-based and authored through operations. It does not add a terrain editor or qualify equipment parking on slopes.

## Verification

- 135 Python tests passed; one existing test skipped.
- 97 Three.js adapter checks, 38 Plan editor checks and four ground checks passed.
- Full candidate: zero placement collisions, shell collisions, clearance conflicts, obstructed aisles or authoritative spatial errors. The diagnostic still reports 4,351 unverified findings and 17 unverified aisle clearances; a zero-error result is not complete engineering approval.
- Two isolated Electron runs passed. The final run retained nine screenshots at wide/narrow window sizes, canvas-pixel checks, real truck representations and zero missing/mismatched placement transforms.
- Native walking reached factory elevation 0 from yard elevation -1.35 m and returned, with the visible avatar. The unprotected edge test stopped before the drop.
- Native checks did not request Save, and saved document bytes remained unchanged. Both owned backends confirmed clean shutdown; both Electron processes exited with code 0.
- Publication checked the exact reviewed candidate bytes and the unchanged saved base, then saved only Factory 02 through the normal revision-bound service.

Evidence: `.runtime/f2-yard/dry04/report.json`, `validation.json`, `cargo-floor-evidence.json`, and `.runtime/f2-yard/native02/report.json` with screenshots. Earlier failed staging attempts are retained.

## Remaining engineering work

Truck turning/reversing envelopes, dock equipment load ratings, trailer suspension variation, drainage, edge protection, door equipment and regulatory requirements require authoritative inputs and separate review. Container doors and dock bridges are static in this concept.

Restart the desktop application before inspecting the updated Factory 02 so its backend, library and renderer load the new code. The authoring and verification scripts do not close the user's existing desktop session.
