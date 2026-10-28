# Site: Find, Measure and Build (plan)

Status: approved by the user 2026-10-23 ("yes"). In the test copy only:
- **Step R (roads):** done 2026-10-23. See "Built" under step R.
- **Step F (find and measure):** built 2026-10-23. Sage's live gate passed in the step B run.
- **Step B (build):** built 2026-10-23. Its gate passed live in two paid runs ($0.39, then $0.46
  after the fixes); see "Built" under step B.

## Goal

The user says: "I want to turn this parking lot into a warehouse." Sage should:
- find the lot on the site photo, highlight it and measure it;
- build the warehouse in the Plan, at least its walls;
- use the surrounding roads to decide which side gets receiving and shipping.

The user's sketch (`Downloads\Video\11.png`) shows the intended reasoning:
- red arrows along the highway, the local street and the rail line;
- a purple outline around the parking lot.

## Rules kept from the site plan

- Sage never calls outside services.
  - Roads are fetched by the server when a person places the site or loads layers.
  - Tracing runs on the photo the site already stores.
  - Sage only reads stored site data.
- A traced outline is existing pavement seen on a photo, accurate to about 1-2 m. It is never a
  property line, and it is labelled with its photo and date.
- Every change Sage makes is a reviewed proposal that the user approves.
- No Google content anywhere.

## Step R - Roads (being built)

- **Source.** US Census TIGER/Line, through the TIGERweb Transportation MapServer: public domain,
  no key, US only.
  - Layers: primary roads (2), secondary roads (6), local roads (8) and railroads (9).
  - Kinds come from the MTFCC code: highway S1100, arterial S1200, local S1400, ramp S1630,
    service S1640, alley S1730, private S1740, parking aisle S1780, railroad R1011/R1051/R1052.
    Trails, paths and medians are left out.
- **Fetching.** Roads are fetched with the photo's box, clipped to it and simplified to about 0.5 m.
  - Features with the same shape are merged and keep every name; at Bayport TIGER lists
    "St Croix Trl N" and "State Hwy 95" for one road.
  - The fetch is all or nothing: a partial road map would mislead Sage.
- **Storage.** In `facilitySiteContext.roads`: `{source, fetched, geoBounds, items}`. Each item
  stores `{roadId, names, mtfcc, lonLat}`.
  - `kind`, `label`, `line` (property-frame x/z) and `lengthMeters` are derived on every save,
    like image corners.
- **When.** Roads are fetched with every new photo, in the same edit as the placement. The Layers
  section can reload them. A failed fetch never blocks placement; it is reported.
- **Site tab.** Centerlines are coloured by kind and named; railroads are dashed. There is a show
  checkbox, and the credit line names the source.
- **Sage.** `inspect_site_context` gains `roads`: each road's name, kind, distance from the
  building and the lot, compass side of the building, and the lot edges it runs along. Sage's
  site edits keep the stored roads and cannot change them.
- **Gate.** At Bayport:
  - the highway, the local streets and the rail line appear where the photo shows them;
  - Sage's site read names the highway side.
- **Built (2026-10-23).**
  - Code: `ai_inspector/facility_layout/site_roads.py`; `roads` in `site_context.py`; POST
    `.../site-roads`; Sage's `inspect_site_context` (`summarize_roads`); the Site tab's
    `roadLabels`, road drawing and Layers row.
  - Two changes from the plan above:
    - Highways and arterials are fetched from a box twice the photo's size, so a truck route
      just past the photo still counts.
    - A shorter stretch merges into the road it lies on. At Bayport, 3rd St N and 3rd St S join
      St Croix Trl N / State Hwy 95.
    - Added 2026-10-23 at the user's request: local streets also come from the wider box, but
      only the stretches on the shortest way from the photo's streets to the nearest highway or
      arterial are kept.
      - The search follows TIGER's shared vertices, so an overpass is not a junction.
      - If the wider box holds too many streets for one answer, the fetch falls back to the
        photo's own streets.
      - At Bayport, 4th Ave N now reaches State Hwy 95, about 400 m west, for 4 extra points.
  - Live at Bayport (hidden browser, test layout `fl-site-preview-1792672238`):
    - placing the layout brought 9-10 roads in the same edit as the photo;
    - 4th Ave N, Maine St N, the dashed rail line and the residential streets lie on the photo's
      roads.
  - Sage's read lists 4th Ave N 78 m north, the railroad 131 m west, Maine St N 143 m west, and
    State Hwy 95 370 m west.
  - Tests: `tests/test_facility_site_roads.py` (9), plus additions to `test_codex_site_tools.py`,
    `test_facility_layout_site.js` and `test_facility_site_requests.js`.

## Step F - Find and measure

- `look_at_site_photo`: Sage gets the stored photo with a labelled grid. Its model reads images.
- `trace_site_feature`: Sage gives a point or a rough box, and the server traces the region on
  the photo.
  - Method: grow the region over similar pavement colour, close the gaps left by cars and stripes,
    and stop at grass, trees and roofs.
  - Result: an outline with area, perimeter, length x width and long-axis bearing.
- The Site tab highlights the outline as a proposal. The user confirms it or adjusts its corners.
  It is then kept as an `existing_pavement` reference outline.
- **Gate.** At Bayport, Sage finds the lot east of the building. The traced outline matches the
  user's sketch to within about 2 m, and the measurements agree with the Measure tool.
- **Built (2026-10-23).**
  - **The tracer** (`site_trace.py`) works on numpy, scipy and PIL at 0.75 m per pixel.
    - Pavement is low saturation, not green and not yellow. Dry grass was cut out using
      thresholds calibrated on the Bayport NAIP photo.
    - The Census roads are cut out (step R).
    - Stripe and car gaps are closed; necks under about 8 m are opened with a square; corners are
      regrown half the opening distance.
    - "Find" drops light regions that are mostly stripes on asphalt.
  - **Box limit.** A box keeps only the part meant.
  - **Speed.** A trace takes about 0.1 s and a find 0.7 s. The first call per server pays a one-time
    6 s scipy import.
  - **Bayport.** A box trace gives 5.24 ac (21,196 m2), 229 x 130 m, long side east-west. It follows
    4th Ave N, the rail corridor and the tree line, and leaves out the south strip and the dry field,
    as in the user's sketch.
  - **Area kind.** `existing_pavement` is reference only:
    - no setback, overlap or boundary findings;
    - not counted as paving;
    - it does not block `analyze_site_fit`;
    - it is drawn as a dashed cyan outline.
  - **Manual.** Areas > "Trace pavement on the photo": click, or drag a box. The result becomes an
    area draft with a size summary; the user adjusts its corners, then Apply area. POST
    `.../site-trace`. Checked live in a hidden browser.
  - **Sage.**
    - `look_at_site_photo` returns lettered paved areas (outline, size, direction, roads).
    - `trace_site_feature` takes a point or a box.
    - The pilot prompt says to stage `upsert_site_area` with kind `existing_pavement`.
  - **Images.** The marked-up photo (50 m grid, letters) goes out as MCP image content beside the
    JSON, through `gateway.take_image()`. Whether OpenCode passes it to the model is unverified,
    because that needs a paid run. The text list works either way.
  - **Measures dropped.** A vehicle-colour measure and a texture measure could not tell the lot
    from the factory roofs, so they were left out. Telling lots from roofs is the job of Sage's
    eyes and the user's confirmation.
  - Tests: `tests/test_facility_site_trace.py` (10, on a synthetic photo), plus additions to
    `test_facility_layout_site.js` and `test_facility_site_requests.js`.

## Step B - Build

From a confirmed outline, Sage stages one proposal:
- a building sized to fit the outline inside the setbacks, turned to its long axis;
- exterior walls, with dock doors on the side the roads favour;
- receiving and shipping zones inside;
- a truck court and a drive to that road, through an entrance.

It uses the existing tools: plan size, building pose, walls, zones and outdoor areas.
- A layout holds one building today, so the warehouse is its own layout at that address.
- **Gate.** One prompt gives a warehouse that validates clean, and Sage states its reasons for the
  dock side.
- **Built (2026-10-23).** `site_plan.py`; Sage's tool `plan_warehouse_on_outline`.
  - **How it plans.**
    - It smooths notches up to about 20 m across in the traced edge.
    - It keeps inside the lot and clear of its setbacks.
    - It tries the outline's long axis and its longest edges as building angles.
    - For each compass facing it finds the largest building + 40 m truck court rectangle (a 1 m
      grid search), leaving a 6 m lane all round.
  - **Drives.** A straight 12 m drive goes to the road that serves the facing best (arterial over
    local), never across a railway. It is trimmed with 2 cm margins against the court, the building
    and the lot line. Where it crosses the lot line it gets a new truck entrance.
  - **Operations.** Plan size, building pose, perimeter walls with up to 40 dock-door openings, a
    concrete floor slab over the whole building, receiving, shipping and storage zones, the truck
    court, the drive, and the entrance (one `set_site_context`). A passed outline is recorded as
    existing pavement in the same batch.
    - The slab (`fs-warehouse-slab`) is left out when the layout already has floor finishes, which
      it would overlap; the plan's notes say so. A slab from an earlier plan is replaced.
- **Live run (Bayport, layout `fl-bayport-warehouse-20261023`).**
  - Setup, free: a fresh layout placed at the lot, Census roads and the county parcel.
  - The one prompt: "I want to turn this parking lot into a warehouse ... Tell me why you chose
    the dock side."
  - Sage: $0.39, 53 s, 6 calls, all successful (inspect_site_context, look_at_site_photo,
    trace_site_feature, plan_warehouse_on_outline, inspect_facility_context,
    preview_facility_operations).
    - It traced only the main lot with a box: 186 x 104 m, about 4 ac. It left out the south
      strip and the north patch itself.
    - It chose docks facing east. Its reasons: rail, Maine St and the houses lie west; 4th Ave N
      gives the shortest drive; north and south fit only 130 x 30 m; south has no drive.
  - After approval: a 90 x 70 m building, 10 m walls, 14 dock doors east, receiving, shipping and
    storage zones, a 40 m truck court, and a drive with a truck entrance onto 4th Ave N.
    **Zero findings.**
- **Fixed after the run.**
  - Sage reported saving the lot as existing pavement, but the planner's `set_site_context` (for
    the entrance) replaced the area list and dropped it. The plan now records the outline itself,
    after its `set_site_context`, and tells Sage to stage its operations first.
  - Replaying the batch offline on a wider trace showed the drive could overlap the court or
    overhang the lot by millimetre rounding. Trims now keep 2 cm margins.
  - Both replays are clean and keep the existing pavement. Not re-run live, since that would need
    a second paid run.
- **Slab, added 2026-10-23 at the user's request.** The first 3D shots showed the photo's parked
  cars through the floorless building.
  - The slab was added by hand to the Bayport layout, then made part of the plan.
  - Replayed offline on Bayport (a fresh layout, and a re-plan over the old slab): the batch passes
    Sage's operation guard and argument schema, is 6,716 of 24,000 bytes, and has zero findings.
- **Second live run (2026-10-23, layout `fl-bayport-warehouse-2-20261023`).** Same setup and prompt
  as the first run, approved by the user.
  - Sage: $0.46, 97 s, 6 calls, all successful (inspect_site_context, look_at_site_photo,
    trace_site_feature, plan_warehouse_on_outline, then preview_facility_operations twice; the
    logs keep no arguments, so what changed between the previews is unknown).
  - It traced 199 x 126 m (4.6 ac), chose east-facing docks for the same reasons, and staged a
    91 x 69 m building with 14 dock doors.
  - After approval: the traced lot kept as existing pavement, the slab, the three zones, truck court,
    drive and truck entrance. **Zero findings.** Both fixes held live.
- **3D fix found by that run.** The 3D ground drew the kept existing-pavement outline as solid
  asphalt. That hid the photo under a dark patch and flickered where it overlaps the truck court.
  - Reference outlines are now left out of the 3D ground (`areaSurfaces`).
  - The Site tab still draws them dashed.
  - Checked in 3D shots of the second layout.
- Tests: `tests/test_facility_site_plan.py` (7).

## Costs and risks

- Live checks are paid Sage runs, likely $1-2 in all. Each one is asked for first.
- The model may pick the wrong lot. The confirm step catches it.
- Tracing can leak into adjoining pavement or stop at deep shadows. The user adjusts the corners;
  the result is shown as approximate.
- TIGER centerlines carry no widths. Widths come from the Measure tool or are assumed per road
  kind, and are stated as such.
