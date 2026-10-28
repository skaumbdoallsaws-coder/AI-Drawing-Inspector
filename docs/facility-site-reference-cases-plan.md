# Reference cases for the site build (plan, 2026-10-25)

## Why

The idea is borrowed from SolidCraft, an open-source CAD app. Its "oracle" rebuilds 83 reference parts from saved
command recipes on every change and compares each with known values (volume, area, centre of mass, size).

Our step planners are deterministic and free to run, but their tests use one made-up lot: a 140 x 100 m rectangle on
Mill St. The bugs that reached a paid run or the desktop app came from the real Bayport lot, and each was fixed with
its own test only after a live run found it:

- the car park crossed the 4th Ave N property line by 0.27 m, because that line sits off the metre grid;
- the employee walk started inside the wall;
- staging lanes were counted as car bays.

A reference case rebuilds a whole site from the numbers in the user's prompts. After each step it runs every check
the review runs, then compares the results with recorded numbers. A planner change that breaks a real lot then fails
in seconds, for free, before any Sage run.

## What a case is

1. **A frozen lot:** the property line, its setbacks and street and rear edges, the Census roads, and the traced
   existing pavement. Geometry and names only: no photo, no parcel PIN or address. Owner and tax data are never
   requested, so they cannot be in it.
2. **A recipe:** the step tools' arguments in order, taken from the prompts. For Bayport these are the take's prompts
   (`steps_take.py` PROMPTS): an 80 x 45 m building, 10 m high, along 4th Ave N, 60 m back, docks on the west wall;
   receiving and shipping 15 m deep and a 20 x 4 m charging bay; 8 staging lanes and a 1 m walkway; rack rows with
   3.7 m aisles; 8 doors and a 40 m court; 30 stalls north of the building; racks, 4 forklifts, trucks at 5 doors and
   20 cars; the paint; 4 reference points.
3. **Model sizes:** the bounding boxes of the library models the recipe uses (rack bay, truck, forklift, pickup), so
   no model files are needed. The colours step needs the real model files, so it stays with its own tests.
4. **Expected results:** hard rules that must always hold, and recorded numbers.

## What is checked after every step

**Hard rules.** Any break fails, naming the step and the rule.

1. The step's operations apply with no validation error.
2. Site checks (`analyze_site_context`) give no warnings: nothing outside the property line or a setback, no
   overlapping areas, entrances clear of intersections and rail crossings, a long enough truck queue.
3. Spatial checks (`diagnose_layout`, as the review runs them): no collisions, no obstructed aisles, no errors or
   warnings.
4. The parking review: the stalls asked for are all there and every bay can be reached.
5. The step rules:
   - the user's numbers are kept exactly: size, distance back, doors, court depth, stalls, forklifts, trucks, cars;
   - earlier layers are left untouched;
   - the walls stay plain until the paint step;
   - aisles are at least the 3.7 m asked for;
   - the car park has its own entrance at least 40 m from the truck one, stays at least 10 m from the court and the
     truck drive, and never lies between the truck entrance and the court.
6. The reference points are inside the property line, each with its ties.

**Recorded numbers.** A change fails until it is accepted.

- Building area, doors, rack rows and bays, aisles, stalls, parked trucks, cars and forklifts, paved area, the route
  lengths to the highway, and the reference-point ties.
- A refusal is recorded too, with its reason, for example "1.2 m too long for the lot".
- Tolerances cover rounding only: 1 cm for lengths, 0.1 m2 for areas.
- `--accept` rewrites the numbers and prints each old and new value, so a change is a decision, not an accident.

## The first cases

1. **Bayport:** the lot of "Bayport warehouse 6" (the LinkedIn video) with the take's recipe.
2. **Bayport off the grid:** the same lot moved 0.37 m east and 0.61 m north. Every count must match case 1 and every
   hard rule must hold. This is the kind of bug that put the car park over the line.
3. **Bayport at the limits:** the biggest building that fits, the same building 1 m too big (refused, saying by how
   much), and the docks on another wall.
4. **The made-up lot** from the unit tests, as the simple control.

## How it runs

- `python tests/test_facility_site_reference_cases.py`: no model, no network, a temporary store only. Target: under
  a minute.
- It prints one table per case (step, result, key numbers) and, on a failure, the step and the rule.
- It joins the tests run before every port and the free rehearsal before any paid Sage run.
- Cases are Python modules in `tests/site_cases/`, because the repo ignores `*.json`.

## Not in this plan

- Sage itself choosing the arguments. That stays with the live rehearsal, and `replay_ui.py` replays recorded turns.
- The PDF sheets and the 3D view.
- The other two SolidCraft ideas: Sage looking at its own work, and changing a number to rebuild the later steps.

## Where

Built in the test copy, then ported to the real repo with the usual procedure (backups, tests before and after).
The Bayport lot is read once from the saved warehouse 6 layout, read-only. The tests write only to a temporary store
and never touch the desktop store.

## Decisions (user, 2026-10-25: "I go with your recommendation")

1. Recorded numbers fail until accepted with `--accept`.
2. Bayport first; more real lots once it runs.

## Status (2026-10-25): built in the test copy, uncommitted

Files:
- `tests/test_facility_site_reference_cases.py`: the harness and the pytest cases.
- `tests/site_cases/__init__.py`: the cases and recipes.
- `tests/site_cases/bayport_lot.py`: the frozen lot and the four model records.
- `tests/site_cases/recorded.py`: the recorded numbers.

How it runs:
- Each step goes through Sage's own path: the tool, `preview_planned_design`, the review opened, approved, saved.
  The test store's model library is patched to the frozen records.
- A full build takes 10-45 s and the whole suite 1-3 minutes, depending on the machine's load. That is slower than
  the minute planned, because each step runs the app's full review and commit.
- Besides counts, the numbers include geometry: marking areas and extents, route lengths, and the spread of each
  model's placements. Counts alone missed a simulated planner change (a wider gap between rack bays, patched in
  memory). With the geometry recorded, it shows as 500.1 -> 514.8 m2 of rack rows.

**Cross-check:** the Bayport replay reproduces warehouse 6, which Sage built live, exactly:
- 216 rack bays in 24 rows and 7 aisles at 3.7 m;
- 8 doors, 30 stalls, 5 trucks, 20 cars, 4 forklifts, 3 closed doors;
- routes of 341.1 m and 381.5 m;
- the building pose.

**Results before the fixes:** 4 cases passed; bayport and bayport-moved failed on finding 1.

**Findings:**
1. **Fixed 2026-10-25. The car entrance was 39.953 m from the truck entrance; the rule says at least 40 m.** This is
   in warehouse 6, the video's layout, too.
   - Cause: `plan_parking` kept the car entrance out of a 40 m disc, `Point(...).buffer(40)`. That disc is a
     64-sided polygon whose edges sit up to 4.8 cm inside the circle. The planner's summary rounded the gap to 40.0.
   - The same pattern kept the two driveways apart in `site_parking.plan_car_park` (`TRUCK_GAP_METERS`) and the
     entrances clear of intersections and rail crossings in `site_access.frontage`.
   - Fix: `site_access.circle_around(point, radius)` buffers by r / cos(pi / 64), so the polygon contains the
     circle. All three places use it. The car entrance is now 40.002 m away.
2. **Fixed 2026-10-25. The car park search grid was laid out from the site point, not from the building.**
   - Moving the same lot 0.37 m east and 0.61 m north (bayport-moved) moved the car park about 0.5 m relative to
     the building, so the result depended on where the address geocodes.
   - Fix: the grid steps whole metres from the building's corner.
   - Where the grid starts also decides which largest free rectangles the search finds. From the corner alone,
     Bayport fitted only 25 of the 30 stalls, in two rows. The search now starts from four offsets (0 and 0.5 m on
     each axis) and keeps the best car park. Bayport keeps its 30 stalls in one row; the east docks still fit 29.
   - bayport-moved now compares everything in the building's frame (doors, zones, markings, routes, models, ground
     tiles), not only counts, and matches bayport.
   - New unit tests (`test_facility_site_steps.py`): a keep-away circle holds the whole distance all round, and the
     made-up lot moved off the grid gives the same car park. The second fails on the old grid.
3. **East docks fit 29 of the 30 stalls asked.** The tool reports it, which is its designed behaviour (Sage tells
   the user and asks).
4. **Observation:** a step runs `validate_layout` about 39 times through the review and commit path (349 times for
   9 steps). That is likely why approvals are slow in the desktop app. It is out of scope here.

**After the fixes:** all 6 cases pass, and the new numbers were accepted (173 changed values, printed by
`--accept`). For Bayport they are small: the car entrance moves 2 cm along 4th Ave N, the employee door 2 cm, the
crosswalk grows from 6.5 to 7.5 m2 and the walk from 3.97 to 4.3 m, and the car park keeps 10.6 m clear of the trucks
(11.0 before). All 181 tests in the `test_facility_site_*` files and `test_codex_site_tools.py` pass.
