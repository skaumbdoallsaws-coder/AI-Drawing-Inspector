# Handoff: Facility Site Context (the Site tab) - for Codex

Date: 2026-10-22. Started by the Claude Code session that built SC0 and SC1;
updated by Codex after the location fix, SC2, SC3 and the offline SC4 work.

Read this file first, then `docs/facility-site-context-plan.md` (sections 0,
1, 3, 5, 6, 7, 7a, 9 and 10). The plan is the binding contract; this file is
the current state and how to work.

## 0. Where to work

- **Work only in the isolated test copy:**
  `C:\Users\might\Documents\InspectorPro-CopilotTest\app`.
- **Do not edit the real app** (the user calls it "the desktop app"):
  `C:\Users\might\OneDrive\Desktop\InspectorPro\AI-Drawing-Inspector`.
  - You may read it.
  - Porting the work there happens later, and only when the user asks.
- **Version control.** The test copy is not a git repo. Its code history
  lives in an external git dir; from `app\` run:
  `git --git-dir=../notes/backups/2026-10-21-before-site-context/code.git --work-tree=. <command>`
  - History: `5ec0580` baseline; `9241b53` tests synced; `65a57af` and
    `b89bdf3` SC0; `e04f9f7` SC1; handoff `22e3fc4`; location fix `4438a86`;
    SC2 `a74b743`; SC3 `92c9d06`; then the SC4 integration commit.
  - Stage files by name. Never `git add -A`: the work tree holds hundreds of
    unrelated untracked files.
  - Commit finished, tested steps only. Never push anywhere.
- **Secrets.** Never print, copy or commit `.env` files, API keys or tokens.
  The main repo's `.env` holds `OPENCODE_API_KEY`, which must never be
  displayed.
- **The user.** Latest instruction authorizes continuing implementation while
  they are away, without routine questions. Use existing command permissions;
  do not bypass sandbox restrictions. Paid model runs still need the explicit
  budget required by the plan. No desktop port is authorized.

## 1. The end objective

Taken from plan section 1.

An engineer finds a property, sees it at true scale under the plan, marks the
property line and asks Sage: "Design a manufacturing facility on this property
with production areas, loading docks, offices, parking and access roads." Sage
proposes the building's size and position on the lot and the outdoor areas
around it. The engineer refines that with the existing tools and fits out the
interior as today. The 3D view shows the factory on its real lot.

The flow:
1. **Find:** an address or coordinates.
2. **Frame:** an aerial image at true scale.
3. **Bound:** the property line, street side, setbacks and entrances.
4. **Design:** Sage places the building and lays out the truck court, docks,
   parking and drives.
5. **Refine and fit out:** the existing tools.
6. **Present:** a 3D fly-over and walkthrough on the real lot.

Guiding principle: geography is context for the CAD and AI tools.
InspectorPro does not become a mapping application, and the imagery is a
reference layer.

Non-goals: legal boundaries, zoning or code compliance, grading, stormwater,
utilities, a map browser, a globe viewer. Plan section 5 lists what
InspectorPro may and must never claim.

Milestones (plan section 8):

| Milestone | Phases | Outcome | State |
|---|---|---|---|
| M1 | SC0 + SC1 | A layout sits on its real lot, correctly oriented, in plan and 3D | Done in the test copy |
| M2 | SC2 + SC3 | An engineer can lay out a conceptual site by hand | Done in the test copy |
| M3 | SC4 | Sage designs the site from one prompt; this is the next demo video | Offline integration verified; paid live gate remains |
| M4 | SC5 | Photoreal surroundings, optional | Go/no-go on Google terms first |

## 1a. Current State After Codex Work

This section supersedes the historical SC1 descriptions below. All changes
remain in the test copy; the desktop source and its layout store are untouched.

- Find/Enter places a single address match, shows map-level progress/errors,
  retains the old context on failure and cancels stale requests. Several matches
  still require selection. Browser checks used controlled imagery responses;
  they do not establish current USGS availability.
- SC2: property drawing/typed coordinates/edge lengths, setbacks, street/rear
  edges, entrances and building move/rotation. Pose edits preserve geography
  and interior coordinates. Revision checks, undo/redo and save/reopen verified.
- SC3: seven outdoor area kinds, three surfaces, geometry checks and metrics,
  rendered in Site and real WebGL 3D. Dock openings reuse the existing editor.
  The 3D compass and site top view use true north.
- SC4: revision-bound `inspect_site_context` and deterministic `analyze_site_fit`.
  Four site edit operations use the existing proposal/approval/undo pipeline;
  none auto-applies, even in direct-edit mode. Sage cannot change/remove the
  geographic anchor or imagery. Those remain manual UI operations.
- Fit results are bounded candidate searches, not an optimizer or code approval.
  Parking includes reserved aisle space but is not authored stalls, circulation
  connections or turning-path verification. Candidates are rechecked through
  the persisted normalizer. A no-fit response is not proof of infeasibility.
- The Site tab now displays the same proposed layout as Plan/3D, read-only.
  Review controls count site edits/findings rather than claiming no problems
  when the parking extends outside the property.

Verification on 2026-10-22:
- 151 focused Python tests passed, including real gateway approval, stale
  revision rejection, exact receipt undo, schema boundaries and fit analysis.
- JS passed: workspace 101, session 63, transport 30, app 6, adapter 115,
  site helpers 9, requests 7 and Codex operation-preview 47 checks.
- `tests/verify_facility_site_browser.py`: SC2/SC3 acceptance fixture
  `fl-site-acceptance-1792661687`, seven surfaces, clean findings, 30-degree
  pose, save/reopen and undo/redo, no page errors. Desktop/compact screenshots
  and 3D nonblank pixels checked. This is a geometry fixture, not a finished site.
- `tests/verify_facility_site_browser.py --preview-only`: final fixture
  `fl-site-preview-1792673055`. A real gateway proposal flagged an out-of-lot
  parking area in both the Site panel and approval bar. Dismissal restored the
  base view without changing the saved revision. No page errors.
  Pending proposals are process-local, so this browser test bridges only its
  proposal GET/DELETE to the owning test host. Geometry/validation are real,
  but this is NOT an end-to-end paid Sage/model test.
- Screenshots: `../ui-data/site-checks/sc3-*.png` and `sc4-site-proposal.png`.
- The full facility/Codex suite was not rerun; its historical missing-fixture
  failures below must not be described as newly verified or resolved.

The test server is at http://127.0.0.1:8491. Example:
http://127.0.0.1:8491/?facilityLayoutId=fl-site-acceptance-1792661687
Hidden-server logs: `../ui-data/site-codex-server.stdout.log` and
`../ui-data/site-codex-server.stderr.log`. No paid model calls were made.

Next gate: obtain a live-run budget, then exercise the flagship Sage prompt on
a disposable property through chat. Check actual doors, parking stalls/aisles,
entrance connectivity and interior preservation, not only reserved polygons.
Fix observed gaps before declaring M3 complete. SC5 still needs a terms/budget
decision; SC6 remains later work. General geographic-origin rebasing is not
exposed. Keep the SC0 unresolved visual/migration checks in plan section 7a.

## 1b. Live Test Results, 2026-10-22 (Claude: real browser and a paid Sage run)

Tested in a headed Chromium on the real GPU. Headless software WebGL froze on
3D-heavy steps; that is a limit of the test harness, not of the app.

The layout was "Machine Shop Test", placed at 100 4th Ave N, Bayport, MN, with
a 1 km NAIP photo.

**Passed**
- **Location:** an address plus Enter places a single match by itself. A
  banner shows on the map during the fetch, and the old photo stays until the
  new one arrives (16-25 s).
- **Property:**
  - Four map clicks made a 238.5 x 204.4 m lot of 12.05 acres.
  - Setbacks and edge types apply. The finding "Edge 4 (street): building is
    5.05 m away; requested setback is 15 m" was checked by hand.
  - Typed moves work.
  - A 30-degree turn left all 22 placements, the zones and the walls
    unchanged.
  - The move handle works.
  - Save and reopen gave identical site data.
- **Entrance and walls:** a truck entrance (Edge 4, 12 m) adds correctly.
  "Walls and dock openings" opens the Perimeter walls editor.
- **Areas:**
  - Drawn and typed areas have exact sizes.
  - "Drive overlaps Car park" is flagged, and the paved total counts the
    overlap once.
  - Delete, undo and redo are exact.
  - In 3D: surfaces, the property line, the true-north compass and a
    north-up Top View.
- **Paid Sage run.** One prompt; $0.40; 110 s; claude-sonnet-5-5 on OpenCode.
  - All 8 tool calls succeeded, including `inspect_site_context`,
    `analyze_site_fit` and `preview_facility_operations`.
  - Sage staged 5 areas for review: an entrance drive, a truck court, trailer
    parking, car parking and a car drive. It kept the compliant building pose
    and stated its assumptions.
  - The Site tab showed the read-only proposal. The approval bar read
    "5 site edits, 1 site finding".
  - After approval:
    - the interior, building pose, georeference and property were unchanged;
    - the 12 m drive is centred on the 12 m entrance;
    - the drive meets the truck court, and the court abuts the building
      (0.3 m).

**Fixed during the test** (commit `a290ea9`). The rotate handle silently
failed after any other drag.
- The earlier drag had selected the SVG label text.
- The next press then started a native drag of that selection, and the
  `pointercancel` dropped the gesture.
- The fix: `user-select: none` on the Site canvas.

**Open findings**
1. **Fixed (Claude, commit `a999477`).** Every realistic site carried one
   finding: a drive joining an authored entrance must cross the street setback
   ("Truck entrance drive: Edge 4 requested setback is not met").
   - Now only the part of a drive or sidewalk outside the entrance strip has
     to meet the setback. The strip is the entrance's width, as deep as the
     setback, with a 5 cm tolerance.
   - Drives may use vehicle or shared entrances; sidewalks may use any.
   - A wider drive is still reported, as "not met beyond the entrance width".
   - Exempt crossings are listed in `metrics.entranceCrossings`, not as
     findings, so a site can validate clean. Sage's `upsert_site_area` text
     states the rule.
   - Sage's Bayport design (the backup from before the county parcel replaced
     the lot) now has no geometry findings.
2. The Building X/Z inputs show float noise after a drag
   (69.97200000000001). Round the display to the millimetre.
3. A drag started while the previous site edit is still committing is ignored
   without feedback. This was seen once, right after reopening, when a commit
   took more than 3.5 s.
4. Sage made all five areas asphalt, which makes them hard to tell apart in
   3D. Consider default surfaces by kind, such as a concrete truck court.
5. Parking stays reserved envelopes, with no marked stalls and no pedestrian
   path from the car lot. Sage said so itself.

**Added after the live test (Claude, 2026-10-22, at the user's request)**
- **Measure.** A map button in the Site tab: click two points for the
  distance in metres and feet, with a live line while placing the second
  point. Esc or Done exits.
  - It is a view tool; nothing is saved. It also works on read-only
    proposals.
  - Live check: the 2025 photo's crosswalk on 4th Ave N reads 7.79 m.
- **Photo source.** In the Location panel: Standard (USGS NAIP, nationwide),
  or High resolution, which is the Metropolitan Council / MnGeo spring 2025
  orthophoto. That photo is 1 ft, leaf-off and public domain under the
  Minnesota Government Data Practices Act.
  - It comes from the WMS layer `met25`, requested at 0.3 m per pixel.
  - Outside the 7-county coverage box, or where the answer is blank, it
    returns 422 `site_imagery_not_covered`. No silent fallback; the current
    photo stays.
  - The source key is `mngeo_metro`. Sage's site schema now takes its photo
    sources from `site_context.SOURCES`.
- Why: the summer NAIP photo read a 7.5 m road as 4-5 m, because of trees and
  its 0.6 m detail. The leaf-off 2025 photo reads it correctly.

**Public reference layers (Claude, 2026-10-22, at the user's request: "pull most data from public sources")**
- **Property, "Use county parcel".** Click inside a lot on the photo. The open-data county parcel
  (MnGeo's compilation of opted-in Minnesota counties) becomes the property line.
  - The outline is simplified to 120 points or fewer with Shapely. The source is `county_parcel`,
    with a label such as "Washington County parcel <PIN>".
  - Setbacks are kept; edge types and entrances are cleared, after a confirm dialog.
  - Only the outline, PIN, address, legal description and acreage are requested; owner and tax
    fields never are.
  - Outside Minnesota the lookup returns 422 `site_parcel_not_covered`; with no parcel under the
    point, 404.
- **A new Layers section.** "Load layers for this photo" fetches transparent map images of the
  photo's box, each drawn by the agency's own service:
  - FEMA NFHL flood zones (minimal hazard left out);
  - USFWS NWI wetlands;
  - USGS 3DEP contours at 2, 5 or 10 ft by area, recoloured light;
  - USDA SSURGO soil units.
  - They are stored like photos (PNG, content-addressed) in `facilitySiteContext.overlays`, with
    one show checkbox each and a shared opacity.
- **"Check building, lot and areas".** Sends the outlines to each service and asks which zones
  they touch. The services intersect server-side, so no river-sized geometry is downloaded.
  - Results go into `layerChecks`, with a `geometryKey` of the outlines checked.
  - The analysis turns them into `site_flood_zone` and `site_wetland` warnings and
    `site_ground_fall` notes. After any building, lot or area change it reports
    `site_layer_checks_stale` instead.
- **Sage.** It sees `referenceLayers` and `layerChecks` in `inspect_site_context`. Its site edits
  carry the stored overlays and checks over, and changing them is refused as a manual-only
  change.
- **Live result.** At Bayport the building, lot and all five Sage areas lie in FEMA Zone AE (the
  1% annual chance floodplain), and the lot touches the St. Croix riverine wetland.
- **Known.**
  - Overlays show in the Site tab only, not in 3D.
  - The parcel's many short river-side edges crowd their length labels.
  - The live stale check froze the headless browser on a building move. It is covered by a unit
    test.

**Globe flight to a new site (Claude, 2026-10-22, at the user's request)**
- **What it does.** When a layout is placed by address (Find) or coordinates (Place), a globe
  turns to the place. It starts over the previous site, or a quarter turn away for a first
  placement.
  - It hovers until the server holds the dive's tiles (at most 4 s), then dives in about 5 s.
  - It holds over the place while the photo downloads.
  - Once the photo is drawn beneath, it settles on the Site view's exact framing and fades out
    over 0.7 s.
  - It is presentation only: nothing is stored, and the photo flow is unchanged.
  - Skip, Esc, switching tab or layout, or a failed photo ends it at once.
  - With reduced motion, no WebGL, or no library, there is no flight.
- **Code.** `static/facility_layout_site_globe.js`; hooks in `facility_layout_site.js`
  (`startFlight`, `flightCamera`, `landFlight`; `viewForBox` is shared with `fitView`).
  - MapLibre GL JS 6.13.0 (BSD-3) is vendored in `static/vendor/maplibre-gl/6.13.0/`. Provenance
    and hashes are in `VERSIONS.md`.
  - It is an ES module, imported on the first flight rather than at page load.
- **Imagery.** The USGS `USGSImageryOnly` cached tiles: NASA Blue Marble at small scales, then
  Landsat, then NAIP; public domain.
  - Tiles go through the server: GET `/api/facility-site-globe/{site}/{z}/{x}/{y}.jpg`, needing
    `layout.read`, for zoom 16 and coarser.
  - POST `.../prefetch` fetches the 3 x 3 tiles around the place at every zoom (140 tiles) with
    16 workers. It answers once they are ready, or after 6 s.
  - Up to 800 tiles are kept in memory, never on disk.
  - Google was ruled out: Maps Platform ToS 3.2.3(e) forbids a Google map "with or near" a
    non-Google map, and Google Earth cannot be embedded.
- **Server fixes found by the live test.**
  - `server.py` telemetry no longer records `/api/facility-site-globe/` requests. Each record
    blocked the event loop.
  - The tile route waits on an asyncio future instead of holding a request thread. A dive sends
    100+ tile requests, and the held threads had stalled every route; the photo fetch went from
    30-40 s to about 9 s.
- **Known, not changed.** Facility layout routes run their work on the event loop
  (`api._result`).
  - Listing layouts takes 25-30 s in this test copy, and freezes the whole server meanwhile,
    flights included.
  - In practice the app's start-up listing finishes before anyone types an address.
- **Live result.** Seattle to Chicago (233 S Wacker Dr):
  - no empty frames, and about 11 s from Find to the photo;
  - `live_globe_align.py` measured a 0 px offset between the landed globe and the photo.
- **Looks.**
  - At globe scale the poles beyond 85 degrees show as a grey cap, a MapLibre Web Mercator limit.
  - Past zoom 16 the tiles are enlarged, so the last globe frame is softer than the photo, and the
    fade reads as a focus pull.

**Find, measure and build (plan approved 2026-10-23).** The user's goal: "turn this parking lot
into a warehouse".
- The plan is `docs/facility-site-find-and-build-plan.md`.
- Step R (roads from the US Census TIGER/Line map, stored with the site, drawn and named, and read
  by Sage) is built.
- Step F (find, trace and measure on the stored photo, manually and as Sage's tools) is built.
- Step B (Sage plans the warehouse and chooses the dock side from the roads) is built.
- Both passed one paid live run ($0.39) on layout `fl-bayport-warehouse-20261023`, ending with zero
  findings; see the plan for details and the two fixes made after it.

## 2. Original Bug Report (resolved; retained for context)

**Report (2026-10-22):** "When I entered the new address the viewport did not
update."

**What the user did:**
- Opened the Site tab on "Machine Shop Test". It was already placed at
  1 Federal Dr, St Paul, MN.
- Clicked **Change location** and typed one of these addresses (all three
  geocode):
  - `100 4th Ave N, Bayport, MN 55003`;
  - `2009 University Ave SE, Minneapolis, MN 55455`;
  - `1265 Lombardi Ave, Green Bay, WI 54304`.
- May also have set "Aerial photo area" to 1 km square.

**What we know:**
- The server logged no error, and no new photo was stored. The photo request
  never completed, or never started.
- In `static/facility_layout_site.js`, **Find** only lists the matches as
  buttons. Nothing moves until a match is clicked, which calls `place()`.

**Suspects, most likely first:**
1. The user expected Find or Enter to place the building, and never clicked
   the match button.
2. The photo fetch was slow, and the panel's "Fetching the aerial photo..."
   line went unnoticed.
   - NAIP often answers 504. With one retry, the basemap fallback and the
     flight-date lookup, a fetch can take minutes.
   - A 1 km photo is 2000 x 2000 px, which is slower still.
3. A client-side request timeout in `static/facility_layout_transport.js` is
   shorter than the server's fetch.

**Original suggested fix.** The user subsequently approved this behavior.
- With exactly one match, place it straight from Find or Enter. Keep the list
  when there are several.
- Show the in-progress state on the map itself, not only in a panel line.
  Keep the old photo visible until the new one arrives.
- Give `/site-imagery` a client timeout of about 3 minutes, and show failures
  clearly.
- Reproduce headless first (section 5), then add a regression test.

## 3. Original Roadmap (current completion in section 1a)

**SC2 - Property line and building on the lot.** See plan section 7.
- Boundary drawing and editing: vertex handles, plus typed coordinates and
  edge lengths. Setbacks, street edges and entrances.
- `set_building_pose`, with drag and rotate handles in the Site tab.
  - Today the pose can only be moved, through "Move building on the photo",
    which re-georeferences the origin.
  - The 3D adapter already maps the photo through the pose.
- `site_context.py`:
  - findings: `site_building_outside_property`, `site_setback_violation`,
    `site_area_*`;
  - metrics: lot area, coverage, and the distance from the building to each
    edge.
  - Setbacks are checked, not constructed. See plan 6.2.
- Gate:
  - A building inside a setback is flagged, and the finding names the edge.
  - Turning the building leaves the interior intact.
  - Undo, redo and save/reopen round-trip the site.

The later phases:
- **SC3:** outdoor areas (truck court, trailer parking, parking, drives and
  more); 3D surfaces; dock doors through the existing wall openings; metrics.
- **SC4:** the Sage tools `inspect_site_context` and `analyze_site_fit`, with
  typed schemas. Live runs are paid; get the user's budget approval first.
- **SC5:** optional photoreal tiles, after a go/no-go. **SC6:** later items.
- Each phase has a gate in plan section 7. Record the evidence in plan section
  7a, as SC0 and SC1 do.

Per plan section 6.3, the Site tab should reuse the plan editor's drawing
(`facility_layout_editor.js`) for polygons, rather than writing new drawing
code.

## 4. Historical SC1 Architecture

For the files, design and evidence in full, see plan section 7a.

**Server** (`ai_inspector/facility_layout/`):
- `geo.py`: WGS84 geodetic, ECEF and property-frame conversions, and photo
  boxes.
- `site_context.py`: normalizes `facilitySiteContext` v1, which holds
  `georeference`, `buildingPose` and `imagery`.
- `site_imagery.py`: the Census geocode route, the NAIP photo route (retried
  once, then the USGS basemap), and content-addressed photo storage.
- `set_site_context` in `operations.py`, where null removes the site.
  Validation runs in `validate.py`.
- Routes:
  - `POST /api/facility-site-geocode/{site}`;
  - `POST /api/facility-layouts/{site}/{layout}/site-imagery`;
  - `GET /api/facility-site-imagery/{site}/{sha}.jpg`.

**Client** (`static/`):
- `facility_layout_site.js` (the Site tab). The workspace adds the tab as
  Plan | 3D | Site.
- The adapter lays the photo under the floor as the 3D ground.
- The session and transport provide `setSiteContext`, `fetchSiteImagery` and
  `geocodeAddress`.

**Frames:**
- Layout axes are +X east, +Z north, +Y up.
- The property frame is an exact WGS84 ENU tangent plane at the georeference
  origin.
- `buildingPose` = {x, z, bearingDegrees}. The bearing is the compass bearing
  of plan north, clockwise from true north.
- From the building frame to the property frame:
  `p = (x + bx cos b + bz sin b, z - bx sin b + bz cos b)`.
- The default pose centres the building on the origin.

**Imagery rules:**
- A photo's `geoBounds` box is authoritative; the property-frame corners are
  derived from it on every normalize.
- Always store the box the service reports (`f=json`). ArcGIS widens a
  requested box unless `adjustAspectRatio=false`. NAIP accepts that option;
  the basemap ignores it.
- Missing this once made north-south distances 30 % short. A field
  measurement caught it (plan 7a).

**Sage at SC1:** no site tools existed then. SC4 now adds the read/fit tools
and reviewed site edits described in section 1a.

**3D convention from SC0. Do not undo it.**
- The 3D canvas is displayed mirrored, with CSS `scaleX(-1)`. The camera
  sees a left-handed world as right-handed.
- Model files are mirrored once, in model space, when the catalog is built
  (`model_axes.py`). Never use a negative scale: it breaks instancing and
  raycasting.
- Pointer input, the compass and textures follow the mirror.
- If something in 3D looks east-west flipped, check this first.

## 5. How to run and test

**Python tests.** From `app\`:
`env -u PYTHONPATH -u PYTHONHOME ../venv/Scripts/python.exe -m pytest tests/test_facility_geo.py tests/test_facility_site_context.py -q -p no:cacheprovider --basetemp=C:/Users/might/AppData/Local/Temp/ipt`
- Delete `ipt` afterwards.
- Keep `--basetemp` short: long paths fail on Windows.

**Full suite.** The same command with
`tests/test_facility*.py tests/test_codex*.py`; it takes about 10-15 minutes.
- Baseline after SC1: 2,514 passed, 61 skipped, **66 failed and 9 errors**.
- The failures and errors already existed: missing fixtures in the test copy.
  Compare against them; do not chase them.

**JS tests.** From `app\`: `node --test tests/<file>.js`. The relevant files:
- `test_facility_layout_site.js`;
- `test_facility_site_requests.js` and `test_facility_site_globe.js` (the
  globe flight, against a fake MapLibre);
- `test_facility_layout_workspace.js`;
- `test_facility_layout_session.js`;
- `test_facility_layout_transport.js`;
- `test_facility_layout_app.js`;
- `test_facility_layout_three_adapter.js`;
- `test_facility_model_axes_mirror.js`.

**Server.** From the test copy root, run `venv\Scripts\python.exe opencode_ui.py --model claude-sonnet-5-5`
(with `PYTHONPATH`/`PYTHONHOME` unset), then open http://127.0.0.1:8491.
- To reach the Site tab: Workflows > Facility Layout > "Machine Shop Test" >
  Site.
- Viewing is free. Chatting with Sage there spends paid OpenCode credits.
- Send output to a log file. Never pipe it through `head`: once `head` exits,
  the server's stdout is a broken pipe.
- As of this handoff, a server started on 2026-10-22 may still be running
  (`opencode_ui.py` in the process list), logging to
  `ui-data\server-2026-10-22-globe5.log`. Stop it before starting another.

**Headless browser checks.** These scripts live in the test copy root; run
them with `C:\Python314\python.exe`, which has Playwright in its user site.
- `ui_driver.py`: `launch`, `open LAYOUT_ID`, `js "EXPR"`, `shot NAME`,
  `click "SELECTOR"`, `stop`. Chromium runs on CDP port 9333.
- `sc1_site.py`: `place "ADDRESS"`, `shots NAME`, `move DX DZ`, `undo`,
  `remove`, `report`.
- `sc1_align.py`: measures how well the Site tab and 3D photos line up.
- `sc1_refresh.py`: "New photo here", while probing the browser's health.
- `live_globe.py LAYOUT_ID "ADDRESS" NAME`: places a layout and films the
  globe flight. `live_globe_align.py NAME` measures the offset between the
  landed globe and the photo.
  - Both need the visible browser (`ui_driver.py launch --headed`).
  - `live_globe.py` waits for the app's start-up requests to finish first.
- Screenshots go to `ui-data\drive\`.
- "Machine Shop Test" is `fl-eb787390-dec6-458d-9813-60aa7de09692`, 24 x 18 m.

**Layout store.** `ui-data\facility-layout` holds a copy of the user's
layouts.
- Backups: `notes\backups\2026-10-21-before-site-context\layout-store.tar`
  (before SC0) and `layout-store-after-sc0.tar` (before SC1).
- Archived layouts are read-only.

## 6. Gotchas

- **Line endings and encoding.**
  - Facility files are LF. On Windows, Python's `Path.write_text` writes
    CRLF; use `write_bytes`.
  - New strings in `server.py` and `index.html` must be ASCII.
- **Script versions.** Bump the `?v=` version on a static file's script tag in
  `index.html` whenever you change that file, or browsers keep the old copy.
- **No console windows.** No flashing console windows on Windows
  (`AGENTS.md`).
- **Downloads are untrusted.** Put each in its own folder, and run Python that
  reads them with `-E -P` from another folder.
- **External services.**
  - NAIP is flaky (504s).
  - The Census geocoder misses some street names. For example,
    "Rev Dr Martin Luther King Jr Blvd" does not match.
  - A Census match is a street-address point, which can land on the road.
- **Headless Chromium hangs under low memory.**
  - Symptoms: port 9333 accepts connections but never answers, and the
    browser process idles.
  - Never kill a Playwright CDP client with a short `timeout`; poll with
    short calls instead (see `sc1_refresh.py`).
  - Recovery: stop the `headless_shell` tree, then run `ui_driver.py launch`
    and `open` again.
- **Memory.** The machine runs at about 3 GB free. Background servers can be
  stopped by the host's low-memory guard.
- **A blocked server loop stalls everything.**
  - Any synchronous work in an `async` route, or in an `/api/*` middleware,
    holds every other request: tiles, the photo, even `/api/bridge/status`.
  - Check request timings in the page
    (`performance.getEntriesByType('resource')`) before blaming the network.
- **The user's preference for visual work.** Build the literal minimum that
  was asked for, and offer extras as options instead of shipping them.
