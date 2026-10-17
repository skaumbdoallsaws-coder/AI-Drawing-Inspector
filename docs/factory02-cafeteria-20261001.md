# Factory 02 Cafeteria

Added a photo-inspired open-plan cafeteria just beyond the dispatch office in
`fl-independent-factory-20260928` (Factory 02 - Integrated Production).

- Zone `zn-independent-cafeteria`: X 53.5-63 m, Z 17-36.5 m.
- Four round plastic-top tables (5589T51), each with four inward-facing chairs.
- One existing Kitchen Assembly, including its original island and three stools.
  Its serving side faces the dining tables; the tall cabinets are at the back.
- A 1.5 m pedestrian cross-aisle joins the existing office pedestrian route.
- 21 added placements, 873 total; one added zone and one added route.
- All previous 852 placements, zones, routes, markings, walls, process bindings
  and 40 movement-program definitions are unchanged. The original manual reference
  remains byte-identical. No animation or food-service capability was added.

Base revision: `247b9723ef009d5788ce6717e7d5df635fd70b899b477f8ccf564e5ccacf3f7c`.
Saved revision: `184423d9e8ab181755124cfb81f2447ffda4825e929e9906a65b629b2fcc218f`.

## Verification

- Real kernel: zero placement collisions, shell collisions, obstructed aisles
  or spatial errors. Existing unverified-clearance findings remain unverified.
- New furniture remains inside the cafeteria; no existing equipment or markings
  intersect its zone. Minimum existing-equipment gap is 4.124 m; minimum gap
  between furniture and route corridors is 0.625 m.
- 24 focused Python checks passed, including chair facing, kitchen orientation,
  quantities, revisions, readiness and preservation of the office/fan contracts.
- Isolated normal Electron application: real meshes for all three furniture
  types, 873 placements, zero transform mismatches, five nonblank captures at
  1440x900 and 900x700 logical window sizes. Overview, eye-level and narrow
  screenshots were visually inspected. No Save was called in the native review;
  backend termination and resource cleanup were confirmed.
- After visual review, the existing revision-checked Save service published the
  candidate. The live document matches the reviewed candidate except the Save
  timestamp, and removing the additions restores every original field.

Evidence: `.runtime/factory02-cafeteria-20261001/` (`dry02`, `native02`, test log
and publication log). `dry01` reached an intermittent spatial-worker timeout
during isolated Save; an unchanged retry passed. `native01` exceeded its outer
deadline before capture and its owned process tree was terminated. The second
native run added stage diagnostics and began waiting at DOM readiness; it passed
and shut down normally. Neither intermittent delay is claimed fixed.

This is a furnishing concept, not an enclosed kitchen, utility installation,
food-service, exhaust, fire, hygiene or accessibility qualification. The photo
guided the furniture arrangement; glazing, ceiling and lighting were not copied.
No provider requests were made and the user's running app was not forcibly
reloaded. Restart InspectorPro and open Factory 02; the structure tree lists
`Cafeteria + Kitchen`.
