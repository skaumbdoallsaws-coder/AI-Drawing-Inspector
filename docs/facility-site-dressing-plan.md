# Site: Paved Lot, Fitted-Out Warehouse and Traffic Routes (plan)

Status: approved by the user 2026-10-23: paving inside the setbacks, counterbalance forklifts. Test copy only.
- Builds on `facility-site-find-and-build-plan.md`: Sage traces the lot and plans the building.
- One part is already done: local streets now reach the highway (commit 40f3f57).

## Goal

The user's request, 2026-10-23:
- The layout follows the lot (the green property line), with the warehouse built on it.
- Pavement covers the shape: dark like real asphalt outside, grey concrete inside.
- Inside: aisles, racks, floor markings and forklifts.
- Trucks parked at the receiving and shipping docks.
- Show how incoming and outgoing trucks get to the main road. Research how this is best done, then
  build that connection.
- An employee car park at the front, inside the boundary: stalls, markings, drive aisles, cars,
  and the car flow to the main road.

## What the app has today

From a code survey on 2026-10-23.
- **Building.** The plan rectangle is the building, and the site model, the Site tab and the
  planner all assume this.
  - Perimeter walls can follow any polygon.
  - Ground ("explicit ground levels") is 1-256 rectangles and may reach past the plan; when
    present, it replaces the plan floor.
- **Things that can stand outside the building.**
  - Floor finishes: hole-free, non-overlapping polygons on the plan or on flat ground; any colour.
  - Floor markings (parking boxes, arrows, lines, crosswalks, hatching, text) and aisles have no
    containment limit.
  - Placements need plan or ground underneath, and a zone around them once any zone exists. Zone
    types include `dock`, `service` and `charging`.
- **Models.** The test server loads the private library: a 40 ft container truck with a dock pose,
  trucks with trailers, cars, forklifts, pallet racking, wheel stops, bollards and cones.
- **Missing.**
  - Traffic routes of any kind.
  - A rack-row generator.
  - Bulk operations: a Sage batch is at most 50 operations and 24,000 bytes, and a single rack bay
    is one operation.
  - Roads in 3D.
- **Precedent.** `tools/add_factory02_truck_yard.py` and `tools/add_factory02_employee_parking.py`
  built Factory 02's truck yard and car park this way. Ground reached past the plan, trucks were
  parked at the doors, and the car park had IN/OUT arrows, stall boxes and cars.

## "Can we do only square layouts?"

- **The building stays a rectangle.** It is the plan, and the dock-door, zone and rack logic is
  built on it. Polygon walls are possible later.
- **The paved yard follows the lot.**
  - It is ground reaching past the building, made of up to 256 rectangles aligned with the building.
  - Everything outside the building stands on it: trucks, cars, stripes and arrows.
  - Where the property line is diagonal or curved, the paving steps or stops short, and the gap
    stays landscaped (decision 1).

## Design defaults

From the research; sources are listed at the end.

| Item | Default |
|---|---|
| Truck court | 41 m (135 ft) including an 18.3 m (60 ft) concrete apron. With a trailer row opposite the docks: 56 m (185 ft), 3.7 x 18.3 m trailer stalls [1][2] |
| Circulation | One-way counter-clockwise loop where it fits, so the docks are on the driver's side for backing. Otherwise two-way, turning in the court [1][3] |
| Driveways | Separate truck and car driveways [4]. Truck: 12.2 m (40 ft), 15-23 m curb returns, checked for a WB-67. Car: 7.3 m (24 ft) [5] |
| Driveway placement | Only on an edge facing a street (no more than about 15 m from its centreline). At least 23 m from an intersection on quiet streets, up to 69 m on busy ones [4]. At least 30 m (100 ft) from a rail crossing [6] |
| Truck queue | Gate 42.7 m (140 ft) inside the property line, so trucks never wait on the street [7]. If that does not fit, a finding says so |
| Route to the main road | The marked truck route goes to the nearest arterial or highway, avoiding residential streets [8] |
| Docks | 2.74 x 3.05 m (9 x 10 ft) doors at 3.7-4.3 m spacing; 18.3 m staging bay inside [1][9] |
| Car park | 90-degree stalls 2.74 x 5.49 m (9 x 18 ft), 7.32 m (24 ft) two-way aisles [10] |
| Car park size | 0.75 stalls per 1,000 sq ft of building (about 52 at 6,500 m2) [11]. ADA count from the federal table (51-75 stalls: 3, one of them a van stall), on the shortest route to the employee door [12] |
| Car park place | Office/front side, away from the trucks, with a walkway to the employee door [4][1] |
| Racks | Back-to-back double rows: 1.07 m (42 in) frames, 2.44 m (96 in) beams, 0.3 m (12 in) flue. 5 levels under 10 m walls [13] |
| Aisles | Counterbalance forklifts 3.7 m (12 ft); reach trucks 2.9 m (9.5 ft). Cross aisle 3.7 m plus a 1 m walkway [14] |
| Floor markings | Yellow 100 mm aisle and lane lines; white staging lanes and rack lines; green walkway; red/white hatching at fire equipment and exits [15] |
| Forklifts | About 1 per 2.5 dock doors, parked at a charging zone. This is an assumption: no published ratio was found |
| Paving | Concrete truck apron and building slab; dark asphalt drives and car park [2] |

## Steps

Each step comes with tests and an offline replay at Bayport. The result is then shown live in the
open browser, which is free. Only the final Sage run costs money, and it is asked for first.

### S1 - Truck access and routes (the connection)

- **Driveways.**
  - Driveways are only placed on street-facing edges, using the spacing rules above.
  - This fixes today's drive, which ends 45 m from 4th Ave N.
  - Separate truck and car driveways.
- **Circulation.**
  - A counter-clockwise loop when the lot allows; otherwise two-way.
  - The gate and queue length are checked against the 42.7 m default.
- **Routes.**
  - A shortest path along the stored roads from each driveway to the nearest highway or arterial.
    Main roads are preferred.
  - Each route's rail crossings and residential streets are noted.
  - Stored in the site context as `routes`: truck in, truck out, car in, car out.
- **Drawing.**
  - Site tab: colour lines with arrowheads. Trucks orange, cars blue; the "out" routes dashed.
  - 3D: on the lot, direction arrows painted as floor markings; on public roads, a raised ribbon
    over the photo.
- **Findings and Sage.**
  - New findings: a drive ending more than about 15 m from its road; a truck route on residential
    streets; a rail crossing on a route.
  - Sage reads the routes in `inspect_site_context`.

- **Built 2026-10-23.**
  - **`site_access.py`.**
    - Frontage: stretches of each lot edge within 15 m of a street's centreline. They keep 23 m
      from intersections and 30 m from rail crossings, and leave each driveway whole on one edge.
    - Entrance checks become site findings: far from a street; near an intersection or rail
      crossing; a short run to the truck court. The last is noted as info, since a 43 m queue
      matters only behind a gate.
  - **Planner.**
    - The drive runs from the court's open sides to the frontage, straight or with one or two bends
      square to the building.
    - Its full 12 m width must clear the building and stay inside the lot.
    - If nothing fits, the building is shortened along its dock wall in 6 m steps.
    - Planning again replaces the earlier zones and walls.
  - **Roads.** Junction vertices survive simplification; twin features do not count as junctions.
  - **Routes.** `routes` is derived in the site context. For each truck or car entrance, a
    shortest path along public streets runs to the first highway or arterial; local streets cost
    1.3x. It records the main road, the streets used, the length, the local-street metres and the
    rail crossings (and how many are at grade).
  - **Sage.** `inspect_site_context` lists the routes.
  - **Site tab.**
    - Each route is drawn as two lanes: incoming solid, outgoing dashed. Trucks are red-pink, cars
      sky blue.
    - Arrowheads every 90 px, and a label at the main-road end, e.g. "Trucks to State Hwy 95,
      387 m".
    - A Routes row in Layers.
  - **3D.** The same lanes lie flat just above the photo, each 1.4 m wide with 30 m arrowheads, the
    outgoing one dashed. Past the photo they run on over the dark background to the main road.
  - **Bayport.**
    - The re-planned east design is 94 x 63 m (shortened 6 m for the drive), with 12 doors.
    - The drive runs 94.5 m to a truck entrance on E43, 10.5 m from 4th Ave N.
    - The route runs 387 m west on 4th Ave N, crossing the railway at grade, to State Hwy 95.
    - No warnings.

### S2 - Paved lot

- **What the planner lays out together:** the building, the truck court, the car park at the front,
  the drives and the driveways.
  - The building shrinks if needed to make room.
- **Paving.**
  - The lot inside its setbacks is paved as ground rectangles in dark asphalt.
  - Concrete floor finishes cover the building slab (already built) and the 18.3 m truck apron.
- Site areas stay as the planning record, shown on the Site tab. 3D shows the paving.

- **Built 2026-10-23.**
  - **Paving.** The planner's operations add `set_ground` with tiles square to the building, made
    by `_paving`:
    - the building (under the slab);
    - an 18.3 m concrete apron along the dock wall and the asphalt rest of the court;
    - the drive's legs, paved on to about 4 m from the street centreline;
    - the traced pavement inside the setbacks, filled with the largest rectangles on a 2 m grid
      that also contains every designed edge.
  - **Rules.**
    - Yard tiles under 200 m2 or narrower than 6 m are left green.
    - At most 64 tiles; colours are asphalt #4a4f55, apron #a7abae and slab tile #9da1a4.
    - Tiles never overlap and share exact edges, so the slab and later placements stand on them.
  - **Drives.** They are now straight only when square to the building; otherwise they have one or
    two square bends, so they tile exactly.
  - **Planning again.** Clears the old ground before the plan size changes.
  - **3D.**
    - The floor grid is drawn only inside the building plan, so the paved yard reads as asphalt.
    - The route lanes sit 2 cm above the floor.
  - **Bayport.** 11 tiles (1 slab, 1 apron, 3 court-lane and drive, 6 yard). The batch is 8.7 of
    24 kB, with no findings. Shown live.

### S3 - Employee car park

- **Layout.**
  - The front (street side, not the dock side) gets its own driveway.
  - Stall rows and aisles, accessible stalls by the employee door, and a crosswalk.
  - Painted IN/OUT arrows; the car route out to the main road comes from S1.
- **Models.** Library cars in about two thirds of the stalls, with wheel stops.
- **Zone.** A `service` zone labelled "Employee parking" holds the cars.

- **Built 2026-10-23 (`site_parking.py`).**
  - **Search.**
    - The free room is the lot inside its setbacks, minus the building with a 3 m walkway and the
      truck court and drive with 2 m of clearance. It is limited to driving reach of the
      street-facing edges.
    - The largest rectangles there are tried. Each gets one aisle with one or two rows of stalls,
      shortened to the stalls needed.
    - Each needs its own car driveway (7.32 m) to a frontage at least 30 m from the truck driveway,
      clear of the truck court and drive.
  - **Choice.** The planner keeps the first car park that holds 90% of the ratio (a guide: the
    research range is 0.37-0.78 per 1,000 sq ft) within 90 m of its street.
    - Otherwise the building gives way in 6 m steps: back first, then the dock-wall ends.
  - **Operations.**
    - In the main batch: the car entrance (with the truck entrance, in one `set_site_context`), the
      Employee parking and car drive areas, and paving for both.
    - In `parkingOperations`: a workcell zone `zn-employee-parking` (service zones cannot hold
      models), `parking_box` stalls (accessible and van stalls blue and labelled), the aisle centre
      line, a crosswalk to the door with an EMPLOYEE ENTRANCE label, and library cars in two of
      every three standard stalls (exact revisions come from Sage's asset catalogue).
    - Planning again deletes the earlier car park by its ID prefixes.
  - **Sage.** The tool passes the catalogue.
  - **Bayport, live.** 44 stalls of the 48 the ratio asks for, including 2 accessible, and 28
    parked cars, north-west of the full 94 x 63 m building (12 doors).
    - A 15 m car driveway to 4th Ave N, 49 m from the truck driveway.
    - The car route runs 336 m to State Hwy 95.
    - No findings.

### S4 - Trucks at the docks

- Container trucks backed into about half the doors, split between receiving and shipping, using
  the library's dock-pose model.
- Trailers go in the trailer row when the court is deep enough for one.
- A `dock` zone labelled "Truck court" holds them.

- **Built 2026-10-23 (`site_trucks.py`).**
  - **Zone.** A `dock` zone, "Truck court", covers the court so trucks may stand in it.
  - **Trucks.** The library's 40 ft container truck in its dock pose backs up to every other door,
    in both the receiving and the shipping half.
    - Container doors are at the model's -z end, so the yaw turns +z to the wall's outward
      direction.
    - The doors sit 0.25 m off the plan edge; the wall's outer face is at 0.15 m.
  - **Arrows.** Yellow arrows show counter-clockwise circulation: back along the dock wall at
    apron + 3 m, and the other way along the far side.
  - **Delivery.** These operations come as `truckOperations`; planning again deletes them by ID
    prefix.
  - **Bayport, live.** 6 trucks at the 12 east doors. The whole site (183 operations) applied with
    no findings.

### S5 - Interior

- **Racks.**
  - Double rows in the storage zone, at right angles to the dock wall.
  - Forklift aisles between rows, and a cross aisle with a walkway along the staging zone.
  - Staging lanes marked in front of each door.
- **Forklifts and markings.**
  - Forklifts parked at a `charging` zone.
  - Yellow aisle edges, white staging lanes, a green walkway, and hatching at exits.
- **Bulk operation.** One new operation places a row of identical models, so a rack row is one
  operation instead of 30. A full fit-out then fits in a few batches.

- **Built 2026-10-23 (`site_interior.py`, plus two engine operations).**
  - **Engine.**
    - `place_asset_array` places a straight row of copies of one placement, each `step` metres on,
      with ids `pl-<arrayId>-001` onward. Placing the same arrayId again replaces the row.
    - `delete_asset_array` removes a row at once, so re-planning stays within batch limits.
    - Both are in Sage's schema, the proposal allow-list, the progress labels and the browser's
      ordinary operations.
  - **Interior.**
    - Racks: back-to-back double rows of the library rack bay (2.53 x 1.23 m) with a 0.3 m flue,
      running at right angles to the dock wall.
    - Aisles: 3.7 m counterbalance forklift aisles (the user's choice) between the rows and at the
      outer walls.
    - Cross aisles: one with yellow edge lines and a 1 m green walkway along the staging area, one
      across the middle of rows longer than 50 m, and a back aisle.
    - A white staging lane, `DOOR n`, in front of each door.
    - A charging zone at the far wall with forklifts, one per 2.5 doors (an assumption).
  - **Delivery.** These come as `interiorOperations`; planning again removes them (rows via
    `delete_asset_array`).
  - **Bayport, live.**
    - 36 rack rows (432 bays), 13 aisles and 5 forklifts.
    - The whole design (266 operations) applied in one direct batch with no findings.

### S6 - Sage and the live run

- **Tooling.**
  - The warehouse plan grows into a site plan that returns several batches. Each batch is within
    50 operations and 24,000 bytes.
  - Sage stages the batches in turn and the user approves each.
  - The pilot prompt gets the circulation and parking rules.
- **Checks.**
  - Offline replay at Bayport.
  - One live run in the visible browser, paid at about $0.50-1.00, asked for first.

- **Built 2026-10-23; run live with Sage the same day (below).**
  - **Packages.** `plan_warehouse_on_outline` now leaves the whole design (operations, car park,
    trucks, interior) on the gateway as one package.
    - Sage's result carries only summaries and a `packageId`: 4 kB at Bayport.
    - The new tool `preview_planned_design {packageId}` stages it as one review through the usual
      proposal path. Validation is unchanged; the limits rise to 1,000 operations and 600 kB, for
      server-built packages only.
    - The pilot prompt has Sage stage the package and describe the routes.
  - **Car park review.** For the app's parking review:
    - Stalls are 2.75 x 5.5 m and the aisle 7.375 m (exact in binary), from a corner snapped to
      1/16 m, so stall and aisle edges coincide.
    - The aisle is a material corridor end to end, and a pedestrian walk runs to the employee door.
    - Stalls the walk crosses stay empty.
    - The review then reports only its standard "manoeuvring unverified" note.
  - **Free rehearsal.** The real gateway, on a temporary store holding Bayport reset to before its
    design.
    - The plan took 0.3 s; the 174-operation package staged in 1.4 s.
    - No new errors, no site findings, no equipment in aisles; 471 placements with no collisions.
    - It did not open the staged review or read the layout engine's own aisle check, which is where
      the live run found problems (below).

- **Live run, 2026-10-23: Bayport warehouse 4, OpenCode with Claude Sonnet 5.5, $0.32.**
  - **What Sage did.** Five tools in 59 s: inspect_site_context, look_at_site_photo,
    trace_site_feature, plan_warehouse_on_outline (with its traced outline, no facing asked) and
    preview_planned_design.
  - **What the planner chose.** West docks: 94 x 51 m, 9 doors, 5 trucks, 28 rack rows, 4
    forklifts, and 39 stalls (2 accessible) with 24 cars. The east option (94 x 63 m, 12 doors) left
    no room for the car park within the 90 % / 90 m rule.
  - **The review could not open.** Sage staged the whole design (151 operations) as one review, but
    the browser showed "Propose between 1 and 50 operations." Fixed in commit 8700742, with the next
    two problems:
    1. Opening and approving a review rebuild the proposal from its stored request
       (`operation_proposals.regenerate`), and that rebuild used the 50-operation default. A package
       now stores its limits with the proposal.
    2. The car park check also reviewed Receiving and Shipping, because the "DOOR n" staging lanes
       are `parking_box` footprints: "9 bays with no aisle or walk". Footprints with the staging role
       no longer count as car parking; any other role still does.
    3. Sage had no route data, so it said it "did not stage a route". The plan now reports
       `routesToMainRoad`, the same routes the saved design derives. At Bayport, trucks run 330 m and
       cars 360 m along 4th Ave N to St Croix Trl N (State Hwy 95), each crossing the railway at grade.
  - **Recovered for free.** `replay_ui.py` now replays OpenCode turns from OpenCode's session store,
    read-only. The paid turn ran again through the fixed gateway in the visible browser. The review
    opened (369 new items, 6 zones, 13 aisles, 7 site edits) and was approved.
  - **One blocked aisle, two warnings.** The employee walk started on the wall centreline and cut
    into the 0.3 m wall. Now:
    - The door sits on the wall facing the car park, at least 3 m from a corner.
    - The walk starts outside the wall and leaves it square. When the car park is off to the side,
      the walk turns along the middle of the walkway strip.
    - The door's floor text is outside the wall.

    A rehearsal of the same turn now shows 0 blocked aisles, 0 warnings and 0 collisions.
    Warehouse 4 was then corrected in place: the fixed planner's walk, crosswalk and door text
    replaced the old three in one direct edit, after a check that the other 66 car-park pieces
    came out identical.
  - **Found by the full test run.** S5 had put `place_asset_array` and `delete_asset_array` between
    `place_asset` and its orientation rules, which attach to the last schema variant. A `place_asset`
    with neither a quaternion nor an orientation then passed the schema. The rules are back on
    `place_asset`.
  - **Cost cap.** The test server's `opencode_ui.py --cost-cap 0.8` stops a turn once it has spent
    that much. Not reached: the turn cost $0.32.

- **Codex run, 2026-10-23: Bayport warehouse 5, gpt-6.1-sol on the user's ChatGPT plan, no money.**
  - **Setup.** The test server `codex_ui.py` runs Sage on the real Codex App Server, as the desktop
    does. The test copy has its own application profile and sign-in
    (`ui-data/codex-profile`); the user signed in once through `tools/connect_chatgpt_account.py`.
  - **The run.** Six tools in 62 s, the same prompt as the paid run: inspect_facility_context,
    inspect_site_context, look_at_site_photo, trace_site_feature, plan_warehouse_on_outline and
    preview_planned_design. That is within the product's 240 s editing budget.
  - **The review.** 345 new items, 6 zones, 13 aisles and 7 site edits. No blocked aisles and no
    warnings; the one site note is the info that a guarded gate would need a 43 m truck queue. The
    review was approved.
  - **The design.** West docks: 93 x 56 m, 11 doors, 6 trucks, 308 rack bays and 4 forklifts, plus
    43 stalls with 27 cars. Sage described the routes from `routesToMainRoad`: about 330 m for trucks
    and 360 m for cars to State Hwy 95, each crossing the railway once.
  - **The walk.** The saved employee walk stops 3.5 cm short of the wall without cutting into it.

### S7 - Appearance (user's requests, 2026-10-23)

The user had been colouring warehouse 5 with Sage on Codex. That showed four gaps:
- the cars were one colour from roof to tyres;
- a white band along the top of the walls was not possible;
- all 308 racks were more than one review holds;
- an entrance door failed with "geometry does not match its authored settings".

The user then chose realistic pickups and their warehouse-5 look as the default, and asked for the
InspectorPro logo on the side walls and a white crosshair on the outside pavement.

- **Wall bands.** Exterior finishes take optional `bands` (`bottomMeters`, `heightMeters`, `color`):
  level strips round the whole perimeter, broken by door openings, drawn over the panels. Finishes
  without bands recompile unchanged.
- **Doorway bug.** `compile_perimeter_walls` cut openings in the order given, but stored them sorted.
  Any door added out of order (the employee door after the dock doors) then failed validation by a
  few bits. It now cuts in the stored order.
- **Ground marks.** `facilityGround` takes optional `marks`: images painted flat on the ground, each
  centred on a level surface, with size and rotation like a floor marking's yaw. They are drawn in 3D
  just above the paving.
- **Planner defaults.**
  - Walls: cyan panels (#06b6d4) on dark joints, with a 1 m white band along the top.
  - Logo: the InspectorPro logo, 6.5 m tall, centred on the two walls beside the dock wall, moved
    clear of any door.
  - Employee door: a 1.8 m entrance where the employee walk meets the wall.
  - Trucks: blue cab, white container, dark chassis.
  - Parked cars: the library's Ford F-150 (the APEX variant, whose own glass, tyres, bumper and lights
    the view keeps), in everyday colours with silver instead of gold trim.
  - Racks: deep blue legs and orange crossmembers, carried by each row's template.
  - Ground: the crosshair, 12 m across, at the centre of the largest open yard tile.
  - The plan result has an `appearance` summary.
- **Images.** Both are content-addressed PNGs in `generated/facility-wall-art/` (logo `cfbcc704...`,
  target `841df2c1...`). They were re-encoded from the user's downloads, and like the rest of that
  folder they are not in git. Without them the planner leaves the logo and target out.
- **Far-view streaks.** The finish's layers sit millimetres apart and z-fought into black streaks
  beyond about 100 m. Each layer now has a matching polygon offset, and the logo the strongest.
- **Warehouse 5.** Updated in place, keeping the user's cyan and truck colours. One direct edit of 370
  operations:
  - the band, the two logos and the employee door;
  - the crosshair on the east yard;
  - dark truck chassis;
  - 27 pickups in place of the one-colour cars;
  - the rack colours on all 308 bays.

### S8 - Smooth flybys (2026-10-23)

The user found flybys slow. Measured in the browser:
- each frame took about 0.8 s (0.4 s without shadows);
- hiding the models brought it to 0.04 s;
- 80.5 million triangles were drawn per frame: rack bay 161,480 triangles x 308, F-150 pickup
  1,124,610 x 27.

Fixes:
- **Part finishes stay instanced** (commit 10ca1e5). Render groups are keyed by finish content, not
  placement. Warehouse 5 went from 342 groups to 11.
- **Lighter overview models.**
  - A `<model>.overview.glb` beside a private model is what the view draws; the full model stays as
    `detail` (`host.build_private_local_asset_catalog`). The asset revision is unchanged.
  - The copies were made with gltfpack 0.22 (`-kn -km -ke -noq`, keeping node names, materials and
    extras):
    - pickup: 1,124,610 to 56,301 triangles (`-si 0.05`), 31.2 MB to 2.1 MB;
    - rack: 161,480 to 7,120 triangles (`-si 0.05 -sa`), 13.5 MB to 90 kB.
  - Both keep every part key, label, authored flag and colour, so saved colours still apply.
  - The files sit in `generated/industrial_assets/`, which is not in git.
  - The frame time with shadows on went from about 800 ms to 35 ms.
- **Frame-by-frame video.** `record_flyby.py` (test-copy root) sets the camera, renders
  (`renderRecordingFrame`), saves each frame, then assembles them with ffmpeg at a fixed 30 fps. The
  result is smooth whatever the frame time. The tour comes from `live_warehouse_demo.framing`.

### S9 - The paint step (user's option A, 2026-10-23)

A free dry run of a fresh design through Sage's path found that two of Codex's authoring rules
refused S7's look. Warehouse 5 had never met them, because its look was applied by a direct edit.
- **Images:** new artwork must already be in the layout or be imported. The planner's own logo and
  crosshair are now allowed; every other image still needs an import (commit 021ba4b).
- **Part colours:** a model's part colours may only be set on a saved placement, with the fingerprint
  (`visualSha256`) of its exact visual. Rack rows (`place_asset_array`) slipped past this; they are
  now checked too.

The user chose to keep that rule and paint in a second step:
1. **The design** (first review) arrives with the walls, band, logo, paving and crosshair. The
   trucks, pickups and racks arrive unpainted.
2. **The paint** (second review). When asked, Sage calls `plan_design_paint`.
   - The server reads the saved trucks, pickups and racks and builds one `set_component_materials`
     per model.
   - Each edit carries the fingerprint of its visual, read once per asset revision through the
     host's component inventory (`site_paint.py`).
   - Sage stages it with `preview_planned_design`, and the card reads "Changes: 341 repainted items."
   - Planning again finds nothing left to paint. `kinds` limits the paint to trucks, cars or racks.
- **Checking each visual once.** The proof check had read the saved layout and parsed the model file
  for every edit. Every placement of one asset revision shares one visual, so each distinct visual is
  now checked once. On warehouse 5 that took the paint review from 30 s to stage, 30 s to open and
  194 s to approve, down to about 4 s, 5 s and 15-20 s.
- **The camera stays.** A review made only of appearance edits no longer re-fits the 3D and plan views,
  when it opens or when it closes. Re-entering 3D after a paint change keeps the view too.
- **Live test, 2026-10-23,** on "Bayport paint test", a copy of warehouse 4:
  - prompt: "Paint the trucks, racks and cars in our colours.";
  - Sage on Codex: 3 tools in 40 s, 341 edits, approved; the camera stayed at the docks.
  - The 24 cars there are the older car model, which has no planned paint part. Sage left them and
    asked for a colour.

## Decisions (user, 2026-10-23)

1. **Paving extent: inside the setbacks.** Straight edges aligned to the building; odd corners and
   the wooded river bank stay green.
2. **Forklifts: counterbalance.** 3.7 m (12 ft) aisles.

## Costs and risks

- **Cost.** Several hours of building, all free until the final live run.
- **3D load.** Hundreds of rack models may slow the 3D view. If they do, rack rows become one model
  each.
- **The real site.**
  - Bayport's lot is in FEMA flood Zone AE and on the St. Croix (a protected riverway with its own
    shoreland setbacks).
  - This is a concept, not a buildable plan. The findings name the rules it cannot check.
- **Unconfirmed defaults.** The research could not confirm the rack orientation, the cross-aisle
  spacing or a forklift-per-door ratio.
- **Paywalled codes.** Fire-code values (NFPA 13, IFC) and road geometry (AASHTO) come from
  secondary sources.

## Sources

1. Blue Giant dock planning: https://www.bluegiant.com/architects/planning-and-design/dock-access/
2. Truck court and paving example: https://www.commercialcafe.com/commercial-property/us/ga/cartersville/lakepoint-commerce-center-building-100/
3. Sight-side backing (Ryder): https://prod.ryder.com/globalassets/media/documents/non-solution/fleet-risk-services/ryder-safety-message-blind-side-backing_ada.pdf
4. MnDOT access management, chapter 3: https://www.dot.state.mn.us/accessmanagement/docs/pdf/manualchapters/chapter3.pdf
5. Georgia DOT driveways: https://www.dot.ga.gov/PartnerSmart/permits/Encroachment/Chapter4.pdf
6. WisDOT rail crossings: https://wisconsindot.gov/rdwy/fdm/fd-17-60.pdf
7. Lake Elsinore truck queuing: https://riversiderecord.org/wp-content/uploads/2023/05/Lake-Elsinore-Good-Neighbor-Policy.pdf
8. New Jersey warehouse guidance: https://www.nj.gov/state/bac/planning/documents/warehouse-guidance.pdf
9. Blue Giant truck berths: https://www.bluegiant.com/architects/planning-and-design/truck-berths/
10. Henrico parking design: https://henrico.gov/services/parking/
11. Class A ratio example: https://www.commercialsearch.com/commercial-property/us/sc/summerville/berkeley-charleston-tradeport-building-2-16/
12. ADA parking: https://www.access-board.gov/ada/guides/chapter-5-parking/
13. Rack design (Steel King via Cisco-Eagle): https://www.cisco-eagle.com/uploads/SK-General-Rack/RackDesignGuide.pdf
14. Aisle widths (Cisco-Eagle): https://www.cisco-eagle.com/blog/2013/05/31/key-considerations-for-warehouse-aisle-widths/
15. OSHA 1910.176 and 1910.144: https://www.law.cornell.edu/cfr/text/29/1910.176 , https://www.law.cornell.edu/cfr/text/29/1910.144 ; Brady colour guide: https://www.bradyid.com/applications/floor-marking-guide
