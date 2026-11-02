# Sage gets the ribbon's tools: patterns, cells, positions and stacks

Status: R1 and R2 are built in the test copy (2026-11-01; see notes/dev-lane-log.md); R3 and R4 follow in
order.

The user asked on 2026-11-01: "please let make available to sage the different tools like linear patterns
and more to build faster....please check the ribbon and all its functions to make sure that similar functions
and tools are available to sage". The main session relayed it, with a first audit and a design. The user then
said "go ahead, keep the defaults" (decisions at the end).

## Why

Sage can already make nearly every edit the ribbon makes. What it lacks is the ribbon's position helpers.
- To repeat a workstation, Sage writes every copy's coordinates by hand.
- For a U-shaped cell, Sage picks every machine's position and turn by hand.
- Both are slow (many tokens) and error-prone (spacing, overlaps, machines facing the wrong way).

The ribbon does this math in the browser only:
- `static/facility_layout_patterns.js`: linear, circular and perimeter patterns, stack, on surface, mirror,
  swap and the cell layouts;
- `static/facility_layout_workspace.js`: align, distribute, relative, distance and offset.

## Audit (2026-11-01)

What was checked:
- the ribbon: `static/index.html`, groups Create, Edit, Surfaces, Position, Build, History and Layout, plus
  the More menu's Utilities;
- the workspace's 45 commands (`static/facility_layout_workspace.js`);
- the operations each command emits (`static/facility_layout_session.js`);
- Sage on Codex: its 38 read tools, 3 edit tools and 60 edit operations
  (`edit_schemas.operation_batch_schema`);
- the server's 69 operations (`ai_inspector/facility_layout/operations.py`).

| Ribbon | Emits | Sage today | Plan |
|---|---|---|---|
| Create: rectangle zone, polygon zone | add_zone | add_zone | - |
| Create: bulk zones | add_zone per zone | add_zone, many in one batch | - |
| Create: aisle | add_aisle | add_aisle | - |
| Create: floor marking | add_floor_marking | add_floor_marking, add_floor_path | - |
| Create: motion path | set_facility_navigation | add/edit/delete_route only | offer, R5 |
| Edit: rotate 90 | rotate_placement | rotate_placement with orientation | - |
| Edit: duplicate | duplicate_placement | duplicate_placement | - |
| Edit: delete | delete_placement, delete_zone ... | the same | - |
| Edit: lock | set_position_mode | set_position_mode | - |
| Edit: appearance | set_appearance; set_custom_appearances | set_appearance | offer, R5 |
| Edit: component materials | set_component_materials | the same, inspect_facility_components | - |
| Edit: replace asset | replace_asset | replace_asset | - |
| Surfaces: decals | set_decals; set_equipment_decals | set_decals, upsert/delete_decal | offer, R5 |
| Surfaces: lettering | upsert_wall_artwork | prepare_facility_lettering, upsert_wall_artwork | - |
| Surfaces: interior walls | set_interior_walls | the same, upsert/delete_interior_wall | - |
| Surfaces: floor surfaces | set_floor_surfaces | the same, upsert/delete_floor_surface | - |
| Position: align, distribute | move_placement | move_placement, coordinates by hand | R3 |
| Position: relative, distance | move_placement | by hand | R3 |
| Position: offset | duplicate_placement or a move | by hand | R3 |
| Build: linear pattern | duplicate_placement, zone and marking copies | place_asset_array: 1 asset, 1 row | R1 |
| Build: circular, perimeter pattern | duplicate_placement | by hand | R2 |
| Build: mirror | duplicate_placement, mirrored turn | by hand | R2 |
| Build: cell layout (10 shapes) | move_placement + rotate_placement | analyze_facility_spatial compares only | R1 |
| Build: create cell, ungroup cell | add_zone with cellGroup; delete_zone | add_zone by hand | R4 |
| Build: stack | duplicate_placement, set_snap_relationship | by hand | R4 |
| Build: on surface | move, set_snap_relationship | set_snap_relationship by hand | R4 |
| Build: swap positions | move_placement + rotate_placement | by hand | R3 |
| History: undo, redo | the app's history | preview_facility_undo; no redo | - |
| History: fit, fit layout, top view | the view only | none | Part B (SV0, SV3b) |
| Layout: Auto Arrange | server planner.py: alternatives to pick from | none | described, not built |
| Layout: export PDF | plan.pdf | prepare_layout_pdf | - |
| Layout: save | the app | Apply directly or a review | - |
| Utilities: saved movement | set_facility_navigation | none | offer, R5 |
| Utilities: Clear All | clear_layout_contents | none | stays user-only |
| Select, pan, assets | the view; the library | search_industrial_assets, list_facility_library | - |

The ribbon's pattern and cell commands store `layoutProvenance` on what they make (command, strategy, seeds,
parameters). Sage's own `duplicate_placement` schema has no such field, so its hand-made copies carry none.

Server operations Sage lacks (5):
- `archive_layout` and `clear_layout_contents`: they stay with the user.
- `set_custom_appearances`, `set_equipment_decals` and `set_facility_navigation`: offered as R5, not planned.

Corrections to the first audit (the main session's, on the real repo at 8769960):
1. Sage already has `upsert/delete_decal`, `upsert/delete_floor_surface` and `upsert/delete_interior_wall`.
   The `edit_*_row` names are the server's handler functions for them, not missing operations.
2. The ribbon's linear pattern is one direction only (count, pitch, angle). A 2D grid is new: the same math
   applied in a second direction.
3. The older agent's four construction tools are implemented, not just names:
   - the tools: `preview_facility_linear_pattern`, `_cell_layout`, `_surface_stack`, `_create_cell_group`;
   - `construction_compiler.py` runs the ribbon's own JS in Node:
     `tools/compile_facility_construction_command.js`, with `static/facility_layout_command_adapter.js` and
     `static/contracts/facility-construction-commands-v1.json`;
   - `construction_service.py` previews them for the older agent;
   - Sage on Codex does not have them.
   Reusing that bridge at run time would need Node on the user's machine and one Node process per call
   (128 MB), and its `subprocess.run` has no no-window flag. The parity tests reuse it instead (below).
4. The ribbon's cell layout arranges items that are already placed. "Lay out 5 CNC machines" also needs new
   machines placed.
5. Facing: the ribbon's face-center turns each model's north side toward the cell's centre point. That is
   diagonal at the ends of a U, and wrong for a model whose front is not its north side (a CNC mill's
   reviewed front is south). The helper below uses each model's reviewed operator side, square to the cell.

## Design

- **The same math as the ribbon, in Python.**
  - `ai_inspector/facility_layout/layout_patterns.py` ports `facility_layout_patterns.js` builder by builder:
    in R1 the selection, bounds, linear pattern and cell layout; in R2-R4 the rest.
  - It ports the command adapter's guards (unknown ids, locked items, stacks, a support without its attached
    items, exact asset revisions) and the session's operation building, so the operations are the ribbon's
    own.
- **Read-only Sage tools that plan, like the build steps.**
  - Each returns a short summary and a `packageId`. Sage stages the package with `preview_planned_design`: one
    review, with the usual validation (overlaps, aisles, zone rules).
  - In Apply directly mode the app applies a package without findings. Otherwise it opens a review.
  - A package holds up to 1000 operations, so a large pattern needs no splitting and no copied coordinates.
- **The ribbon's operations and provenance.**
  - Copies are `duplicate_placement` (finishes, labels and attached items come along). Zone and floor-marking
    copies are `add_zone` and `add_floor_marking`.
  - Cells are `move_placement` + `rotate_placement` pairs. New machines are `place_asset` with the exact
    catalog revision.
  - Each carries `layoutProvenance` as the ribbon writes it, so `inspect_pattern_provenance` and
    `inspect_cell_layout_provenance` read Sage's patterns like the ribbon's.
- **Seeds can be several items:** a whole workstation (bench, chair, fixtures), or a zone, which brings what
  stands inside it.
- **Clearing first:** `removeIds` deletes the items Sage names (for example the old machines in a zone) in the
  same review. Clear All stays the user's.
  - A saved walk (movement) that stops at a removed item, or whose walker is removed, goes in the same change:
    "Walk removal" below. Until 2026-11-01 Sage refused such items, and the user had to clear them by hand.
- **Walk removal** (the user, 2026-11-01: "let sage remove the walk in the same change"; no Plan delete button).
  - The package removes, after its deletions, each saved walk they strand with the stops only it uses
    (`delete_stranded_movements`, operations.py). Every other walk stays byte-identical.
  - A stop that another walk shares stays while its item stays. When its item goes, that walk goes too and is
    named.
  - A handoff to a walk that stays, or a kept walk's drawn path snapped to a stop that goes, is refused in words.
  - The kernel takes only walks that deletions earlier in the same batch strand. It wants every one of them, and
    every stop left without its item. A stop it removes has lost its item or is used by no walk that stays.
    Only a package from the server's planner may carry it (`operation_proposals.PLANNED_ONLY_OPERATIONS`).
  - Apply directly and Review: the same rules as the deletions (`direct_edit_policy.PLANNED_OPERATIONS`).
    Undo restores the earlier revision, walk included.
  - Never silent:
    - Sage's summary has `alsoRemoves` ("Also removes the A05 operator's saved walk (4 stops)."), and the
      pilot rule says to repeat it;
    - the review card adds the same sentence. It compares the saved and proposed walks, so any proposal that
      takes a walk out says so.
- **Clear a zone** (the user, 2026-11-02: removes "everything in the zone except building columns, floor markings
  included"; names what it removes; Undo restores it; no lookups first). `plan_facility_cell` takes `clearZone: true`
  with `zoneId`:
  - it removes every placement and floor marking standing in the zone (its position inside the zone's outline, as
    the ribbon's zone selection reads it), with what is attached to them and the saved walks they strand;
  - it keeps the building's structure (the library's Building Structures: columns, walls, roof members, sprinklers,
    light rows), locked items, and an item mounted on one that stays;
  - with no strategy or machines it only clears the zone (one review, as "Clear Assembly Cell A06" asks);
  - the summary's `cleared` names what goes and what stays ("Clears Assembly Cell A05: removes A05 assembly bench,
    ... and A05 kit cart bay (floor marking). Keeps Column C-5 (building structure)."), and the pilot rule says to
    repeat it. Sage no longer looks up a zone's items, or reviews its workstations, before planning a cell.
  - Why: the desktop's A05 U kept the yellow KIT CART bay (Sage's removeIds named placements only), and that turn
    spent 227 of its 240 s on lookups.
  - The review card counts floor markings too and names what any proposal removes ("Removes A05 kit cart, ... and
    A05 kit cart bay (floor marking)."), up to 24 names. A clear-only review stays in 3D (a review or a direct
    apply only moves the view into or out of Site).
- **Skill rules** (`ai_inspector/codex_runtime/pilot.py`): to repeat items or lay out machines, use these
  tools instead of computing coordinates. Stage the package unchanged. Say when a facing is unverified.
- **Progress steps** (`progress.py`): plain labels, for example "Planning a U-shaped cell of 5 machines".

## Phases

Each phase: build, test in the test UI, commit, log port-ready on its own. The main session then ports it and
checks it with Sage in the desktop app.

### R1: linear pattern and cell layout (built 2026-11-01)

`plan_facility_pattern`, kind `linear` (R2 adds the other kinds):
- `seedIds`: 1-240 placements, floor markings or zones. The ribbon's rules apply: no locked or stacked item,
  and a support goes with all its attached items.
- `count`: 2-50 instances, the seed included (the ribbon's count).
- `direction`: north, east, south or west (north is +z, up on the plan), or `headingDegrees` (0 north,
  90 east). Neither (built 2026-11-01, the main session's item 3; the ribbon always asks): the row runs along
  the seed's length (its largest placement's long side), either way, else across it, where it fits (see
  "Where a pattern fits" below). When more than one way fits, the one with more room (room past the row's
  gap, or 1 m, counts the same), else the seed's own +x way. `picked` says which way and why, for Sage to
  tell the user.
- `spacing` (centre to centre, the ribbon's pitch) or `gap` (clear space between instances along the
  direction): one of them. "2 m apart" is `gap` 2 unless the user says centre to centre; the summary gives
  both.
- A grid: `rows` (default 1), `rowDirection` or `rowHeadingDegrees` (neither: the side that fits, named in
  `picked`), and `rowSpacing` or `rowGap` (default: `gap`, so "1.5 m apart" holds both ways).
- `origin` `{x, z}`: the seed's main item moves there first, in the same package (rows, grids, circles and
  rings; not for a seed with a zone in it).
- `removeIds`.
- At most 240 new objects, the ribbon's limit.
- It returns each instance's centre, the pitch, the pattern's extent and the package.

`plan_facility_cell` (R4 adds create and ungroup):
- `placementIds` (2-50 placed machines, in flow order) or `assets` (`[{assetId, count}]`, new machines,
  2-50 in all).
- `strategy`: line, l, u, grid, parallel, serpentine, loop, spine, herringbone or cluster (all ten).
- Where the cell goes:
  - `zoneId`: centred in the zone, and it must fit inside it;
  - `center`: `{x, z}`;
  - neither: the machines' own centre, as the ribbon does (placed machines only).
- Its size: `width` and `depth`. The default starts from the ribbon's (the largest machine and `gap`,
  default 1 m).
- Room to work (built 2026-11-01; the ribbon does neither): the ribbon's gap is only a preferred spacing,
  and it does not look at what else stands where the cell goes. A default-sized cell grows (width and
  depth apart, smallest area first, up to 2.2 times) and, in a zone, shifts inside the zone (0.5 m steps,
  nearest first) until neighbours, and what stays there, keep the gap. The positions are still the
  ribbon's for that size and centre. Overhead items do not count. The result names what it kept clear
  of, how far it shifted, and anything still too close (in A06, the locked Column C-6).
- `rows`, for the grid, parallel and serpentine shapes.
- Which way it turns:
  - `turnDegrees`: turns the whole cell clockwise (the ribbon's angle);
  - `openSide`, for a U: north, east, south or west.
- `facing`: `operator-inside` (the default), or the ribbon's own preserve, follow-path, face-center or
  face-outward (these two turn the reviewed operator side: "Cell facing" below).
  - `operator-inside`: each machine's reviewed operator side (else its front) faces square into the cell:
    - U, L, loop: the inside of the path;
    - cluster: the centre;
    - spine: the spine;
    - line, grid, parallel, serpentine: `operatorSide`, by default the right of the flow (south for a row
      that runs east);
    - herringbone: the ribbon's 35 degree turns, applied to the front.
  - A model with no reviewed front uses its north side, and the result says its facing is unverified.
- `removeIds`.
- It returns each machine's position, its turn, which way its front faces and whether that front is
  reviewed, which way its operator side faces (`operatorFaces`, "north-east (the centre)"), one sentence for
  Sage to repeat (`operatorSides`), the cell's centre and size, the closest gap, and the package.
- New machines are numbered on from the machines of that model that stay ("CNC Milling Machine 7").

Rough effort: 1.5 days.

**Where a pattern fits** (built 2026-11-01: the main session's item 3, widened to grids, circles and rings; the
ribbon does none of it). A row, grid, circle or ring, not a mirror (its copy goes where its line puts it):
- It stays in a zone: the smallest zone round the seed's main item that the pattern fits by size one way. A
  station's own small zone is not where a row of stations goes; with no such zone, there is no zone check.
- Each instance stands inside the zone, with nothing that stays in its way: touching is not in the way, items
  above or below are not, floor markings do not count, and the seed and `removeIds` do not stay.
- When it does not fit from where the seed stands, it moves with the seed inside the zone (0.5 m steps along
  its own axes, the nearest 400 places): to the nearest place that keeps the pattern's gap (at least 1 m) clear
  of what stays, else to the place with the most room. A row given no direction tries along the seed's length
  first (both ways), then across it.
- The package moves the seed first, then copies it where it stands: `move_placement` for each placement (an
  item on a support gets its own: the kernel does not carry it along), `edit_floor_marking` for a marking. The
  first copy re-stamps the seed's provenance.
- `seedMoved` names the items, by how much, where to and why. Sage says it and never asks the user to move the
  seed first. The main session approved this on 2026-11-01 ("the tool may move the seed on its own when the
  row can't fit otherwise, as long as it always says so"). A `keepSeedInPlace` flag is the offer if the user
  wants to be asked first.
- A direction given is kept: the seed moves along it, or the plan is refused. A seed with a zone in it does
  not move.
- Nothing fits: refused, naming what is in each way, how far the tool looked ("even moving Bench 1 up to 4.3
  m inside Bay"), and what to change.
- `closestToWhatStays`: the pattern stands closer than its gap to something that stays (the roomiest place,
  or `origin`).
- Factory 02, offline:
  - A04, "6 benches 2 m apart": runs south, the bench moving 3.5 m west (east and west need 22.8 m of A04's
    20 m).
  - A05, the 3 by 2 grid 1.5 m apart: the bench moves 4.5 m.
  - The A04 ring moves 2.5 m north; the A06 circle 2.6 m.
  - 0.2 to 1 s each.
- A behaviour change: before, a row given a direction was made as given even onto existing items (staging
  then counted the collisions).

### R2: mirror, circular pattern, perimeter pattern (built 2026-11-01)

`plan_facility_pattern` takes `kind` (default `linear`). Each kind refuses the others' parameters by name. The
same seeds and rules as R1; a perimeter copies a zone's contents, not the zone, as the ribbon does.
- `mirror`: one mirrored copy (the ribbon's count of 2). The line, given one way:
  - `side` (north, east, south or west; default east) with `gap`, the clear space between the seed and its
    copy;
  - `side` without `gap`: the ribbon's default line, 1 m (or one grid step, if larger) past the seed's edge on
    that side, rounded out to the Plan's grid;
  - `lineX` (a north-south line), `lineZ` (an east-west line), or `linePoints` (two points).
  - Machines' fronts are mirrored (below).
- `circular`: `count` (the seed included), `center` `{x, z}` (default: the ribbon's, west of the seed by 1.5
  times its larger side), `totalDegrees` (default 360; less makes an arc; copies go clockwise) and
  `turnWithPattern` (the ribbon's rotate with pattern).
- `perimeter`: `shape` (rectangle or square), `widthCount` (default 6) on the seed's side and the side opposite,
  `depthCount` (default 4) on each end, `gap` (the ribbon's clear gap, default 0) and `turnDegrees` (the
  ribbon's angle). As in the ribbon, a ring runs along the seed's long side (it turns 90 degrees for a seed
  deeper than wide), and each side's copies turn with it.
- Every kind returns the closest gap between instances (items overhead ignored) and a note when copies
  overlap (touching is not overlapping). A circle or a ring says which way the seed's operator side faces
  (toward the centre or into the ring, along it, or away), with a note when machines face along a ring or a
  turning circle.

**Mirror facing** (the ribbon's Mirror fixed 2026-11-01; Sage's built the same way). A turn cannot mirror a
model, so a mirrored copy keeps one side as the mirror image and the others follow. The ribbon's Mirror
(`mirrorRotationDegrees`) used to keep the copy's own east side: the copy turned to 2L - yaw - 180, L the line's
compass heading. That suits a model whose front is its east or west side. For a front on its north or south side
(the CNC mill's operator side is south, the lathe's front north), the copy faced 180 degrees from the mirror
image: a mill facing an aisle, mirrored across the aisle's centreline, faced away from the aisle. Found while
building R2, under the main session's rule "Facing must be right: machines face the operator side". The user
then asked for the ribbon's fix ("yeah fix it so it works as intended").

Now both keep each machine's reviewed operator side, else its front (the catalog's
`facilitySemantics.functionalSides`, in the layout's model space), else its north side (+Z, a model file's
front; Sage names those unverified). The copy turns to 2L - yaw - 2h, h that side's heading in the model's own
axes. Both rules agree for a side at 90 or 270 degrees. Floor markings and zones keep their east side, as
before; positions are unchanged. A model with no reviewed side now keeps yaw 0 across a north-south line,
where it used to turn 180 degrees.

**Cell facing** (the ribbon's Cell Layout and Sage's cell, fixed 2026-11-01). The ribbon's face-center turned each
model's +Z (a model file's front) toward the cell's centre, and face-outward away from it. A CNC mill works from its
south side, so a circle of mills "all facing the centre" faced out. The main session saw it on scratch copy b
(plan_facility_cell, a loop of 4 mills in A06 at yaws 45, 135, -135 and -45), and Sage said they faced the centre.
The user asked for the ribbon's fix too ("yes fix the ribbon face center too").

Now both turn each machine's reviewed operator side, else its front, else its north side (the Mirror's rule)
toward or away from the centre, for every strategy. A model with no reviewed side keeps the old +Z turn, and Sage
lists it in `unverifiedFacing`. Sage's summary gives:
- each machine's `operatorFaces`: its bearing and, round a U, L, loop or cluster (or with face-center or
  face-outward), whether it faces the centre, into the cell, along it, out of it, or away from the centre;
- `operatorSides`: one sentence ("All 4 operator sides face the centre."). The pilot rule tells Sage to repeat
  it, not the facing it asked for.

### R3: align, distribute, offset, relative, distance, swap

`plan_facility_position`, with modes:
- `align` (edges or centres, to an anchor item);
- `distribute` (an axis, equal centres or equal gaps);
- `offset` (copy or move by a distance);
- `relative` (a side of a reference item, at a distance, aligned);
- `distance` (set the distance between two items);
- `swap` (exchange two items' places).

Ported from the workspace's `buildAlignmentUpdates`, `buildDistributionUpdates`,
`buildRelativePositionUpdates` and `buildDistanceUpdate`, and from the patterns' `buildSwap`. Rough effort:
1 day.

### R4: stack, on surface, create and ungroup cell

- `plan_facility_stack`: modes `stack` (a count and a gap) and `surface` (onto a support's published surface).
- `plan_facility_cell` actions `group` (a named cell zone around items, with numbering) and `ungroup`.

Rough effort: 1 day.

### Not planned

- **Auto Arrange:** the server's `planner.py` makes whole-layout alternatives from an asset set, as ghost
  previews the user picks from. A Sage tool for it would answer "lay out this hall for me". Recommended
  after R4, not built (decision 4).
- **Fit, fit layout, top view:** moving the user's view is Part B of `docs/sage-basic-shapes-plan.md`
  (SV0, SV3b).
- **Clear All:** stays the user's. Sage clears a zone or an area with its delete operations, through
  `removeIds` or its own batch.

## Tests

- **Parity with the ribbon's math.**
  - A Node script runs `facility_layout_patterns.js` on shared fixtures: a layout, a catalog and builder
    calls.
  - The pytest runs `layout_patterns.py` on the same fixtures and asserts the same copies and moves, every
    number within 1e-9.
  - Node runs only in tests (with the no-window flag), never in the app.
- **Parity with the ribbon's operations.**
  - For placed seeds, `tools/compile_facility_construction_command.js` (the ribbon's own operation
    building) and the package give the same operations: kinds, sources, positions, turns and provenance.
  - Ids that depend on the session's namespace are left out.
  - The mirror, circle and ring do not go through that compiler: the workspace builds them and the session's
    `applyPattern` turns them into operations. `tests/pattern_session_runner.js` runs those two on the same
    fixture, with Sage's namespace: the same operations, ids and turns included.
- **Tool tests.**
  - The arguments, and refusals with a plain reason: unknown ids, locked or stacked items, a missing
    attached item, too many objects, a cell that does not fit its zone.
  - Walk removal: the walk named and removed with its own stops, a shared stop kept, a handoff refused; the
    kernel's rules; staged, applied directly, the other walk byte-identical, undone. Review sentence: a Node
    check.
  - `removeIds`; new machines at their exact catalog revision.
  - Facing for reviewed fronts (a CNC mill faces south unturned, a lathe north) and for unreviewed ones.
  - face-center and face-outward on a loop and a cluster: each operator side toward or away from the centre, in
    the ribbon (a Node check) and in Sage (`operatorFaces`, `operatorSides`).
  - Where a pattern fits: the zone it stays in, `picked`, `seedMoved` for a row, grid, ring and circle (a
    circle's centre moves with it), `origin`, the roomiest place, and the refusal. A moved seed is staged and
    applied directly, its provenance read back consistent.
  - Provenance read back by the two provenance tools.
  - Staged with `preview_planned_design`: Apply directly applies a package without findings.
- **Rules and labels:** the pilot rules and the progress labels.
- **Test UI:** stage and apply the plans on a scratch copy of Factory 02 through the server (no Sage turn),
  then look at them in the 3D view:
  - a row and a grid of workstations;
  - a U and an L of 5 CNC machines in a cleared zone;
  - R2: a mirrored workstation and machine, a circle that turns, and a ring.

## Sage prompts (live checks: the main session, in the desktop app, on scratch copy b)

1. With a workbench selected: "add 5 more workbenches in a row after this one, 2 m apart". Expect one
   pattern, 5 new benches with the same finish, a 2 m clear gap between them.
2. "Clear Assembly Cell A06 and lay out 5 CNC machines as a U-shaped cell". Expect A06's old items removed
   and 5 machines in a U in one review, every front facing into the U.
3. "Now try an L". Expect the same 5 machines moved into an L, fronts facing into the L.
4. With a workstation selected: "make a 3 by 2 grid of this workstation, 1.5 m apart". Expect a grid of 6,
   with the attached items on each bench.

R2:
5. With a CNC mill selected: "mirror this mill to its east, 4 m clear". Expect kind mirror, side east, gap 4:
   one copy 4 m clear, its front the mirror image of the original's (facing back toward the line if the
   original faced it).
6. With a CNC mill selected that faces a robot: "make 4 of these mills in a circle round the robot, all facing
   it". Expect kind circular, count 4, the robot's position as the centre and turnWithPattern: every front
   faces the robot.
7. With a workbench selected: "put a ring of benches round here, 3 on each long side and 2 on each end, 1 m
   apart". Expect kind perimeter, widthCount 3, depthCount 2, gap 1: 9 new benches.

Sage turns in the test copy only on the user's yes.

## Decisions (made by the user 2026-11-01: "go ahead, keep the defaults")

1. **Order:** R1 to R4 in order. Each is logged port-ready on its own; the main session ports it and checks
   it with Sage in the desktop app.
2. **Clear All** stays user-only. Sage clears by zone or area with its delete operations.
3. **Fit and top view** stay with Part B (SV0, SV3b).
4. **Auto Arrange** is described and recommended, not built.

These follow the plan's recommendations, the defaults the user kept:
- the ribbon's math ported to Python, with the parity tests, rather than the Node bridge at run time;
- packages staged with `preview_planned_design`, rather than operations Sage copies;
- `operator-inside` facing by default.

## Offers, not built

- **R5: the three operations Sage lacks:**
  - `set_facility_navigation` (motion paths, saved movement);
  - `set_equipment_decals`;
  - `set_custom_appearances`.
- **The older agent's construction tools** could be retired once R1 and R4 cover them.
