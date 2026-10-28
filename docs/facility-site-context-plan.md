# Facility Site Context Plan

Date: 2026-10-21 (revision 2 - decisions made; SC0 and SC1 built in the test copy)

Status: SC0 and SC1 are done in the isolated test copy and not yet ported here
(section 7a). SC2-SC6 are not started. Work continues in the test copy; see
`docs/facility-site-context-handoff.md` there. Written at the user's request after the
2026-10-21 discussion of the geographic idea note (three cases: design on real
land, recreate an existing facility, an embedded Earth viewport). The user
accepted every recommendation in section 0 and asked for a Site tab next to the
3D tab (section 3).

Scope: case 1 - design a new facility on an actual property - plus optional
photoreal surroundings for presentation. Case 2 (recreate an existing facility
from imagery) and case 3 (a free-roaming Earth viewport) are out of scope;
section 12 says why and what they would need.

## 0. Decisions (all five accepted by the user, 2026-10-21)

1. **How 3D will match the plan (SC0).** Recommended: keep the data convention
   (+X east, +Z north, +Y up) that the server, the plan and Sage already use,
   and correct the 3D renderer, which today draws the layout as a mirror image
   of the plan. The alternative, redefining the data axes, rewrites saved
   layouts and Sage's compass wording.
2. **US-first imagery.** Recommended: start with USGS aerial imagery - public
   domain, free, measurable and storable, but US-only. Global coverage needs a
   licensed provider later.
3. **Whether photoreal surroundings (SC5) are in scope at all.** Google's
   Photorealistic 3D Tiles look striking but are display-only, metered and
   carry attribution rules. Recommended: decide after M3, on demo value.
4. **Where site data lives in v1.** Recommended: an additive layout extension,
   versioned and undoable with the layout. A reviewed, shared authority (like
   the facility shell) is the long-term home once a property holds several
   buildings.
5. **Display units.** Data stays metric. Recommended: show acres and feet
   alongside for US users.

## 1. Objective

An engineer finds a property, sees it at true scale under the plan, marks the
property line and asks Sage: "Design a manufacturing facility on this property
with production areas, loading docks, offices, parking and access roads." Sage
proposes the building's size and position on the lot and the outdoor areas
around it. The engineer refines that with the existing tools and fits out the
interior as today. The 3D view shows the factory on its real lot.

The flow, end to end:
1. **Find:** type an address or paste coordinates.
2. **Frame:** InspectorPro fetches an aerial image of the area and shows it
   under the plan at true scale.
3. **Bound:** draw the property line on the image or type its corners; mark
   the street side, setbacks and drive entrances.
4. **Design:** Sage places the building and lays out the truck court, docks,
   parking and drives inside the lot and its setbacks.
5. **Refine and fit out:** existing tools, for the building and its interior.
6. **Present:** 3D fly-over and walkthrough on the real lot.

Guiding principle, from the idea note: geography is context for the CAD and AI
tools; InspectorPro does not become a mapping application. The engineering
geometry stays ours. The imagery is a reference layer.

Non-goals: legal boundary determination, zoning or code compliance, grading,
stormwater, utilities, a map browser, a globe viewer.

## 2. What Already Exists

- **Layout document.** `coordinateFrame` is `{"datumId": "local-origin",
  "floorAxes": ["+X", "+Z"], "upAxis": "+Y", "handedness": "right", "units":
  "m", "floorElevation": 0}`. Extensions in use: `facilityPlan` (building
  width, depth and grid), `facilityPerimeterWalls`, `facilityInteriorWalls`,
  `facilityScene`, and `facilityGround` when authored. `association` carries
  `siteId` and `areaId`, where "site" means the tenant's facility container,
  not a piece of land. The new data never reuses `siteId`; it says "site
  context" for the extension and "property" for the parcel.
- **Shell authority.** `sourceShellRef` pins a `facility_shell` revision with
  its own `coordinateFrame` and a `floor_surface` feature. The starter shell
  carries the finding `local_shell_requires_site_review`: "Replace the starter
  floor boundary with reviewed site data before safety or installation
  decisions." That finding is the hook this plan eventually fills.
- **The plan is the building.** `plan_settings.py` rewrites the effective
  floor to the rectangle (0,0)-(width, depth). `spatial.py` rejects floor
  placements outside it (`placement_outside_floor`), and once any zone exists
  every placement must be inside a zone (`zone_containment_violation`).
- **Ground surfaces.** `ground.py` (`facilityGround`) authors rectangular
  ground levels and straight ramps, coordinates bounded to +/-10 km: a
  precedent for ground beyond one flat floor.
- **Scenes are looks only.** `static/facility_layout_scenes.js` and the
  adapter's `setScene` and `applySceneBackground` set the environment,
  background, lights, exposure and sun shadows
  (`docs/facility-appearance-library.md`). A scene has no ground imagery, no
  geometry and no geography. It stays the right home for the sky and sun of an
  outdoor site, and nothing more.
- **The plan editor is SVG** (`static/facility_layout_editor.js`). An underlay
  is an SVG `image` element below the grid.
- **3D adapter.** `applyPlacementTransform` in
  `static/facility_layout_three_adapter.js` copies layout positions and
  quaternions straight into three.js (r184), and
  `cameraOrientationFromQuaternion` drives the compass. That direct copy is
  why the 3D view is a mirror image of the plan (found 2026-10-18, unfixed).
- **Image store pattern.** `decal_images.py` stores content-addressed (sha256)
  images per site under the layout repository, with a POST import route, a GET
  serve route, a 10 MB cap and the `layout.edit` permission. Site imagery can
  copy it.
- **Desktop network policy.** `desktop/src/application-network.cjs` lets the
  renderer reach external HTTPS only for xhr, image, media, font and websocket
  requests, under ordinary CORS, and never sends the private token outside.
  Scripts and navigation stay local.
- **Sage editing policy.** `direct_edit_policy.py` lists the operations that
  may apply without review; plan-level changes such as `set_plan_settings` are
  not in it. Placement intents (`placement_intents.py`) showed that computed
  geometry (`attachTo`, `seatAt`) beats model-guessed coordinates; the same
  idea drives `analyze_site_fit` below.

## 3. Frames And North

```
Earth (WGS84 latitude/longitude)
   |  georeference: origin point + exact tangent plane via ECEF
Property frame   (+X true east, +Z true north, +Y up, meters)
   |  buildingPose: x, z, bearingDegrees
Building frame   (today's layout frame; plan north = +Z)
   |  placement transforms (unchanged)
Equipment        (vendor CAD models in canonical model space)
```

- **Property frame (new):** fixed to the Earth, origin at a chosen point of the
  lot. It is a local tangent plane computed exactly through ECEF on WGS84, with
  no projection library. Over 1 km from the origin the curved Earth falls about
  8 cm below the plane, far less than the imagery error.
- **Building frame (existing):** the layout's frame, unchanged. Its pose on the
  lot is `buildingPose`: where its origin sits in the property frame, plus
  `bearingDegrees`, the compass bearing of the building's plan north (+Z)
  measured clockwise from true north.

Consequences:
- Moving or turning the building on the lot edits one pose. No interior
  coordinate changes, and the property line stays put on the Earth.
- Changing the georeference origin later converts existing property-frame
  geometry, so nothing moves on the Earth.
- Sage's existing "north wall" language keeps meaning plan north, as on
  architectural drawings ("project north"). Site tools report both plan north
  and true north, so Sage can act on "put the docks on the true-north side".
- A **Site tab** sits next to the others: Plan | 3D | Site (the user's
  request, 2026-10-21).
  - It is a top-down 2D view of the lot, with true north up and the aerial
    image at true scale.
  - It shows the property line, setbacks, the building's footprint (drag to
    move, a handle to turn), outdoor areas and entrances. Lot design happens
    here.
  - Before a layout is placed, the tab offers address or coordinate entry.
- The **Plan tab** stays exactly as it is, for the building interior.
- Once a layout is placed, the **3D tab** shows the building on its lot: the
  property frame, with the building group posed inside it. The photoreal
  surroundings (SC5) become a switch in that same 3D view, not a second 3D tab.

**The mirror (SC0).** The data axes (+X east, +Y up, +Z north) form a
left-handed set, while three.js is right-handed, so the direct copy in
`applyPlacementTransform` shows the world mirrored. Over real imagery that is
not survivable: the building would sit on the wrong side of the road.

As built (2026-10-21, section 7a): layout numbers and every camera, fit,
walkthrough and saved-view calculation stay as they are, and the 3D canvas is
displayed mirrored left to right (`scaleX(-1)`). That one change makes the 3D
view agree with the plan. Reflecting the scene root instead was rejected: the
adapter treats layout coordinates as world coordinates in dozens of places.
The mirror has four consequences, each handled:

- **Model files** would look mirrored, so each one is mirrored once in its own
  model space as it loads. The vertex data is mirrored, not the transform,
  because negative-determinant transforms break instanced rendering and
  raycast culling.
- **Model-space data** therefore lives in the mirrored model space too:
  footprints, bounds, connectors, support surfaces, reviewed sides and seats.
  It stays authored in each model file's own axes and is converted once where
  the catalog is built (`model_axes.py`). Built-in prototype boxes have no
  file and are left as authored.
- **Input** is mirrored horizontally: picking, orbit and pan, zoom to cursor,
  walkthrough mouse-look and strafe.
- **Writing and pictures** are sampled mirrored so they still read correctly.
  Walls flip left to right. Floors flip top to bottom, because a floor plane's
  texture "up" points south; floor text then reads upright with north up, as on
  the plan. Video recording mirrors its copy of the canvas.

The 3D compass computed the bottom of the view rather than the top; that sign
error is fixed with it.

Saved layouts need a one-time migration (`model_axes_migration.py`):
- models whose reviewed front is east or west turn 180 degrees in place;
- chairs at a registered seat move to the mirrored seat;
- attachments are re-placed on the mirrored surface;
- equipment decals move to the mirrored spot.

The plan does not change. `coordinateFrame.handedness` still says "right" for
an axis set that is left-handed; the reflection is documented in
`model_axes.py` instead, so the coordinate-frame fingerprints that shell
references pin stay valid.

## 4. Data Sources And Licensing

Confirm current terms, pricing and endpoints before building on any of them;
they change.

| Source | Gives | Coverage | Terms (summary) | Use here |
|---|---|---|---|---|
| USGS NAIP aerial imagery (The National Map ImageServer, `exportImage`) | Orthophoto, about 60 cm a pixel, finer in some recent years | Contiguous US, reflown every 2-3 years | Public domain | SC1 underlay: fetch once, store with the layout, measure against it |
| USGS 3DEP elevation | Terrain heights from lidar | US | Public domain | SC6, visual terrain only |
| US Census Geocoder | Address to coordinates | US addresses | Free, public, no key | SC1 location entry |
| Pasted coordinates | Latitude and longitude | Global | - | SC1, works anywhere |
| Survey drawing (DXF or PDF) | The boundary as surveyed | Per project | The user's document | SC6 boundary import |
| County parcel GIS | Parcel polygons | Varies by county | Varies by county | SC6 boundary import from a user-supplied file |
| Google Photorealistic 3D Tiles (Map Tiles API) | Photoreal 3D surroundings | Many cities worldwide | Display only; Google attribution on screen; caching restricted; no deriving outlines, models or measurements; metered per session | SC5, optional, presentation only |
| Open building footprints (Overture, OpenStreetMap, Microsoft) | Building outlines | Wide | Attribution, some share-alike (ODbL) | Case 2 only, not this plan |

Aerial imagery is accurate to a few meters. The property line comes from the
user or a survey, never from tracing a photo.

## 5. Product Boundary

### 5.1 InspectorPro may claim
- A conceptual site layout on a property boundary the user supplied.
- Dimensions, areas, coverage and setback distances computed from the model.
- The imagery's source, capture year and license, shown with the image.

### 5.2 InspectorPro must never claim
- That a boundary is legal or surveyed. An imported survey boundary is
  labeled "as drawn in <document>", nothing stronger.
- Zoning, building code, fire access, stormwater, grading, accessibility or
  utility compliance or feasibility.
- That imagery is current or exact.

### 5.3 Required refusals
- Deriving a boundary, a building outline or a model from Google imagery or
  tiles.
- Storing or exporting Google tiles.
- "Recreate this factory from the map" (case 2) until its own plan exists.
- Sage fetching maps or imagery itself. Sage reads stored site data only, the
  same boundary AGENTS.md draws between Sage and the in-app browser.

## 6. Architecture

### 6.1 Data: one additive layout extension

```json
"facilitySiteContext": {
  "version": 1,
  "georeference": {
    "datum": "WGS84",
    "originLatitude": 44.97,
    "originLongitude": -93.26,
    "originElevationMeters": 256.0,
    "placedBy": "address",
    "label": "the address or note the user entered"
  },
  "property": {
    "boundary": [{"x": -60.0, "z": -40.0}, {"x": 90.0, "z": -40.0}, "..."],
    "source": "user_drawn",
    "setbacksMeters": {"street": 15.0, "side": 6.0, "rear": 9.0},
    "streetEdges": [0],
    "entrances": [{"entranceId": "e1", "x": 10.0, "z": -40.0, "use": "trucks"}]
  },
  "buildingPose": {"x": -30.0, "z": -10.0, "bearingDegrees": 0.0},
  "areas": [
    {"areaId": "a1", "kind": "truck_court", "boundary": ["..."], "label": "Truck court"}
  ],
  "imagery": [
    {"imageId": "<sha256>", "source": "usgs_naip", "captured": "2023",
     "license": "public_domain", "attribution": "USGS NAIP",
     "corners": ["four points in the property frame"], "metersPerPixel": 0.6}
  ]
}
```

- Area kinds in v1: `truck_court`, `trailer_parking`, `parking`, `drive`,
  `sidewalk`, `landscape`, `outdoor_storage`.
- The building footprint is derived from the pose and `facilityPlan`, never
  stored twice.
- A layout without `facilitySiteContext` behaves exactly as today.

### 6.2 Server (`ai_inspector/facility_layout/`)
- **`geo.py` (new):** WGS84 geodetic, ECEF and property-frame conversions and
  bearings. Pure functions, no new dependencies.
- **`site_context.py` (new):** normalizes and validates the extension.
  - Findings: `site_building_outside_property`, `site_setback_violation`,
    `site_area_outside_property`, `site_area_overlaps_building`,
    `site_area_overlap`.
  - Derived metrics: lot area in square meters and acres, building coverage,
    paved area, and the distance from the building to each property edge.
  - Setbacks are checked, not constructed. Every footprint and area edge must
    keep its distance from each boundary edge, using the street, side or rear
    distance that edge carries. No polygon-offset library is needed, and
    concave lots work.
- **`site_imagery.py` (new, modeled on `decal_images.py`):**
  - The server fetches a NAIP image for a box around the origin. It requests
    the image in geographic coordinates and converts the four corners into the
    property frame.
  - The service may draw a different box from the one requested. The server
    stores the box it reports (`f=json`), and asks NAIP with
    `adjustAspectRatio=false`. See SC1 in section 7a.
  - Images are stored content-addressed and served to the client, with a size
    cap of 4096 pixels a side, timeouts, and a clear error when the service is
    down.
  - A geocode route forwards to the Census geocoder.
- **`operations.py`:** `set_site_context` (georeference, boundary, setbacks,
  street edges, entrances), `set_building_pose`, `upsert_site_area` and
  `delete_site_area`. None joins `DIRECT_OPERATIONS` in v1: lot changes go
  through review, like `set_plan_settings`.
- **Validation** runs the site checks next to the interior checks. Interior
  rules are untouched.

### 6.3 Client (`static/`)
- **`facility_layout_site.js` (new):** the Site tab. It is a top-down 2D view
  built on the plan editor's SVG drawing, in the property frame, with its
  panel:
  - Location entry and the imagery fetch, with an opacity control.
  - Drawing and editing the property line: vertex handles plus typed
    coordinates and edge lengths.
  - Setbacks, street edges and entrances.
  - Handles to move and turn the building.
- **`facility_layout_workspace.js`:** the third tab next to Plan and 3D.
- **`facility_layout_editor.js`:** what the Site tab reuses (grid, pan and
  zoom, polygon drawing; area drawing reuses zone drawing). The Plan tab itself
  is unchanged.
- **`facility_layout_three_adapter.js`:**
  - The SC0 world correction.
  - A property-frame root with the building group posed inside it.
  - The imagery as a ground quad just below the building floor, with render
    order to avoid z-fighting, as the floor paint code already does.
  - Areas as flat surfaces.
  - Camera bounds and the compass taken from the property frame.
- **`facility_layout_scenes.js`:** one outdoor preset ("Site daylight"), still
  only a look.
- New UI strings stay ASCII (AGENTS.md).

### 6.4 Sage
- **Read: `inspect_site_context`.**
  - Lot size and area, boundary edges with their lengths and true bearings.
  - Street edges, entrances and setbacks.
  - Building pose and footprint, and plan north against true north.
  - Imagery source and year.
  - Caveats: the boundary is user-drawn, and the imagery is context.
- **Analysis: `analyze_site_fit`.** Given a building size, and optionally a
  dock wall, truck court depth and parking count, it returns feasible poses
  that respect the boundary and setbacks, ranked, with reasons. It is
  deterministic, so Sage never guesses lot coordinates.
- **Edit:** the four operations above, through the normal approval flow.
- **Guidance:** rules of thumb are stated as assumptions, for example truck
  court depth for 53 ft trailers, dock door spacing, stall and aisle sizes, and
  parking ratio. Sage states them, asks when the brief is silent, and never
  presents them as code.

## 7. Implementation Phases

Each phase ends at a gate, and nothing moves past a failed gate. Sizes are
relative: S, M or L.

### SC0 - 3D Matches The Plan (prerequisite, L) - done in the test copy
- Decision (user, 2026-10-21): keep the data axes and correct the 3D view.
- Built as a mirrored display plus a once-only model-file mirror (section 3,
  "The mirror"); status, evidence and what is still open are in section 7a.
- Audit and migrate lateral registrations in canonical model space: seats,
  support surfaces, east and west sides in `asset_orientation.py`, and
  equipment decal anchors.
- Gate:
  - A straight-down 3D view of an asymmetric fixture overlays the plan, with
    marker positions within a pixel tolerance.
  - Both compasses agree.
  - Every chair in the 2026-10-21 demo layout still meets its desk, and the
    band saw's infeed still faces the racks.
  - Sign text reads correctly.
  - Existing layouts look the same on the plan, and their 3D now matches it.
    Saved layouts migrate once (section 3).
- This is the riskiest phase.

### SC1 - Georeference And Aerial Underlay (M) - done in the test copy
- `geo.py`, `site_imagery.py`, the geocode route, and `set_site_context` with
  the georeference only.
- The Site tab: location entry, and the aerial underlay at true scale. The
  same image becomes the 3D ground.
- Gate:
  - On a known lot, distances measured on the underlay match a published
    reference, such as a county GIS measurement or a road width, within
    imagery accuracy.
  - The underlay lines up in the plan and in a straight-down 3D view.
  - It works offline after the first fetch.

### SC2 - Property Line And Building On The Lot (M) - done in the test copy
- Boundary drawing and editing, setbacks, street edges and entrances.
- `set_building_pose` with drag and rotate handles.
- `site_context.py` validation and metrics, shown in the Site tab.
- Gate:
  - A building placed inside a setback is flagged, and the finding names the
    edge.
  - Turning the building leaves the interior intact.
  - Undo, redo and save/reopen round-trip the site.

### SC3 - Outdoor Areas (M) - done in the test copy
- Area kinds and drawing.
- 3D surfaces: asphalt, concrete and grass.
- Dock doors as openings in the wall that faces the truck court, using the
  existing perimeter wall openings.
- Metrics.
- Gate: a hand-drawn site plan validates clean and reads correctly in both
  views. It has a building, a truck court, trailer parking, car parking and
  drives.

### SC4 - Sage Designs The Site (M to L) - offline integration done; live gate open
- `inspect_site_context`, `analyze_site_fit`, tool schemas and descriptions,
  guidance, and typed-schema tests.
- Then live runs on the flagship prompt. These are paid, so get approval for
  the budget first.
- Gate:
  - From one prompt, Sage proposes a building pose and outdoor areas that
    validate clean, and states its assumptions.
  - The interior turns of the existing demo still work on the posed building.

### SC5 - Photoreal Surroundings (optional, M)
- First, a go/no-go on terms, pricing and key handling (section 0, item 3).
  - A key shipped in the renderer cannot be meaningfully restricted to an
    Electron origin.
  - Prefer the backend relaying requests without storing them, if the terms
    allow; otherwise a per-user key.
- `3d-tiles-renderer` (NASA-AMMOS; three.js native; Google tiles support in
  current releases), in the 3D view only and off by default.
- Google attribution visible whenever tiles show.
- Clip the mesh over the lot, so trees and buildings in the photo do not cut
  through the design.
- Never cached.
- Gate:
  - Frame rate on the 2026-10-21 demo layout stays above an agreed floor.
  - The attribution is visible in every frame.
  - Nothing is written to disk.

### SC6 - Later
- Survey drawing import for the boundary, through InspectorPro's drawing
  pipeline.
- County GIS file import.
- Visual terrain from 3DEP, and the true sun position for the site's location
  and date.
- Several buildings per property, which moves the site data into a shared
  authority.
- Sage placing the georeference from an address given in chat.

## 7a. Implementation Status

### SC0, 2026-10-21 (test copy only)

**Where.** `Documents\InspectorPro-CopilotTest\app`. Before the work began it
matched this repo for every facility file; this repo is untouched.
`notes\backups\2026-10-21-before-site-context\` in the test copy holds:
- the layout store from before the work (`layout-store.tar`);
- a git history of the code (`code.git`): baseline `5ec0580`, tests synced
  `9241b53`, then SC0 in `65a57af` and `b89bdf3`;
- the SC0 change as one patch (`sc0-model-axes.patch`) and the migration
  scripts.

**What changed.**
- `ai_inspector/facility_layout/model_axes.py` (new): the conversion, applied
  in `host.py` where the catalog is built.
- `ai_inspector/facility_layout/model_axes_migration.py` (new): the one-time
  layout migration.
- `asset_orientation.py`: a comment only. Registry entries stay in the model
  file's axes.
- `static/facility_layout_three_adapter.js`:
  - the display mirror;
  - the model-file vertex mirror (`mirrorModelFileGeometry`, exported);
  - input mirroring;
  - texture flips;
  - the compass fix.
- `static/facility_layout_recorder.js`: records the view as displayed.
- Tests:
  - `tests/test_facility_model_axes.py` (5 tests);
  - `tests/test_facility_model_axes_mirror.js` (3 tests, real three.js r184);
  - corrected compass values in `tests/test_facility_layout_three_adapter.js`
    (the old values pinned the bug).
- The demo camera scripts need no change: camera poses stay in layout
  coordinates.

**Evidence.**
- **Tests.**
  - The new tests pass, and the adapter JS suite passes 115 of 115.
  - The facility and codex pytest suites pass 2,493 tests. Their 75 failures
    and errors are the same 75 on the baseline code: missing fixtures and
    source-bound evidence in the test copy.
- **Browser** (headless, test copy):
  - A straight-down 3D view of the 2026-10-21 demo layout matches its plan,
    and both compasses agree (north up, east right).
  - Every office chair sits in the inside corner of its cubicle.
  - The band saw sits east of the racks, with its infeed toward them.
  - Floor writing ("KEEP CLEAR", "FINISHED GOODS") reads upright with north
    up, as on the plan.
- **Migration of the test store** (record:
  `ui-data/facility-layout/migrations/2026-10-21-model-axes.json`):

  | Outcome | Layouts |
  |---|---|
  | Migrated | 22 (3 saved through the repository because a route now brushes a corrected outline; 8 kept pre-existing chair collisions) |
  | Unchanged | 17 |
  | Archived, read-only, left as they are | 40 |
  | Unresolved dependency, left as it is | 1 |

**Still open.**
- Wall artwork and equipment decals follow the same flip rule but have not
  been seen in the browser: the test store has none.
- The automated plan/3D overlay check from the SC0 gate is not built; the
  comparison was visual.
- The migration refuses placement-face artworks (none exist yet).
- Restoring a snapshot saved before 2026-10-21 brings back unmigrated data;
  run the migration on it.
- **This repo:** port the patch and migrate its store. The Private Gym fixture
  tests then run against migrated data. Do this only when the user asks.
- The headless test browser stalled twice while loading the 187 x 62 m
  "Layout 3" (600 floor markings, each its own canvas texture). Not
  investigated, and not checked on the baseline code.

### SC1, 2026-10-22 (test copy only)

**Where.** The same test copy. `code.git` holds SC1 as one commit after SC0.
`layout-store-after-sc0.tar`, next to the first store backup, is the layout
store before SC1.

**What changed.**
- `ai_inspector/facility_layout/geo.py` (new): WGS84 geodetic, ECEF and
  property-frame conversions, and the latitude/longitude box for a photo.
- `ai_inspector/facility_layout/site_context.py` (new): normalizes
  `facilitySiteContext` v1, which holds the georeference, the building pose and
  the photos.
  - A photo's latitude/longitude box (`geoBounds`) is authoritative.
  - Its corners in the property frame are derived again on every save, so
    stale corners never survive.
- `ai_inspector/facility_layout/site_imagery.py` (new):
  - the Census geocoder route;
  - the photo route: NAIP, retried once, then the USGS basemap;
  - content-addressed photo storage per site, served from the store.
- `operations.py`: `set_site_context`, where null removes the site.
- `validate.py`: validates the extension with the layout.
- `api.py`: mounts the router.
- `static/facility_layout_site.js` (new): the Site tab.
  - The view: the aerial photo at true scale with north up, the building
    outline and site origin, a scale bar, a north arrow, the photo credit, and
    pan and zoom.
  - The panel: find an address or enter coordinates, and pick the photo area.
    Once placed: move the building on the photo, fetch a new photo, change
    location, remove the site, and set the photo's opacity.
- `static/facility_layout_workspace.js`: the third tab (Plan | 3D | Site).
  Fit acts on the Site view while it shows.
- `static/facility_layout_three_adapter.js`: the photo is the 3D ground. It
  lies 5 cm under the floor and maps into the layout's frame through the
  building pose.
- `facility_layout_session.js`, `facility_layout_transport.js` and
  `facility_layout_app.js`: `setSiteContext`, `fetchSiteImagery` and
  `geocodeAddress`.
- Styles, and the versioned script tags in `index.html`.
- Tests:
  - `tests/test_facility_geo.py` (5);
  - `tests/test_facility_site_context.py` (16);
  - `tests/test_facility_layout_site.js` (5).
- As planned, Sage has no site tools yet. The building can be moved on the
  photo but not turned; turning comes in SC2.

**A bug the distance gate caught.** ArcGIS `exportImage` widens the requested
box until its pixels are square in degrees, unless `adjustAspectRatio=false`.
- At 45 N a photo then covers about 1.4 times the requested ground
  north-south, while the app placed it in the requested box.
- North-south distances therefore read about 30 % short.
- The Site/3D comparison could not see this, because both views use the same
  box.

The server now:
- asks NAIP with `adjustAspectRatio=false`;
- asks every service for `f=json`;
- stores the box the service reports;
- fetches the picture from the returned link, on the service's own host only.

The basemap fallback has no such option and still widens the box. The box it
reports, and now stores, is the widened one.

**Evidence.**
- **Tests:**
  - The new tests pass.
  - The JS suites pass: workspace, session, transport, app, adapter, site and
    model axes.
  - The facility and codex pytest suites pass 2,514 tests, 21 more than after SC0: the new site tests. They still have 66 failures and 9 errors. None involves the site code, and every failure visible in the SC0 run's log is among them.
- **Browser** (headless, test copy). "Machine Shop Test" was placed at
  1 Federal Dr, St Paul, MN.
  - These all work, with no console errors: address lookup, photo fetch,
    placement, moving the building on the photo, undo and redo, save and
    reopen, and remove.
  - **The 3D ground matches the Site tab.** At 0.093 m per pixel the two
    photos align to 0 px beside the building and 2 px (0.19 m) below it.
    Normalized correlation is 0.97-0.99, against 0.08-0.64 for a mirrored
    copy.
  - **Offline.** After a reload, the page contacted only the local server
    (171 requests), and the photo came from the store.
- **Distances.** Measured on the University of Minnesota turf field
  (2009 University Ave SE, Minneapolis): NAIP 2021, 0.5 m per pixel, with
  pixels mapped to the ground as the Site tab maps them.

  | Measure | Photo | Rule | Difference |
  |---|---|---|---|
  | Yard-line spacing, east-west (spectrum) | 4.577 m | 5 yd = 4.572 m | +0.1 % |
  | End line to end line, east-west (edges) | 108.91 m | 120 yd = 109.73 m | -0.82 m |
  | Sideline to sideline, north-south (edges) | 47.67 m | 160 ft = 48.77 m | -1.09 m |

  - The edge method reads both axes about 1 m short, because of blur on thin
    white borders. The two axes agree within half a pixel.
  - Before the fix, the north-south width would have read about 34.6 m.
  - The basemap fallback photo is older and blurrier, with pixels 0.5 x 0.70 m.
    Goal line to goal line reads 93.0 m against 91.44 m (+1.7 %), consistent
    with its resolution.

**Still open.**
- The Plan tab does not show the photo; the Site tab does, as planned.
- A Census match is a street-address point, which can sit on the street.
  "Move building on the photo" corrects the placement.
- NAIP often answers 504, and the server retries once. The flight-date lookup
  also retries once; without it, the photo shows no date.
- Photos fetched during the checks stay in the test store unreferenced. They
  are content-addressed and small.
- The headless test browser hung twice during the checks. Each time a test
  client was stuck and then killed. The same steps passed when repeated
  carefully. This is not a product finding.
- **This repo:** port SC0 and SC1 together, and only when the user asks.

### SC2, 2026-10-22 (test copy only)

Property boundaries now support map drawing, draggable vertices, typed X/Z
coordinates and typed edge lengths. Edge order is retained so street/rear
assignments and entrances remain stable. Entrance use, width and position along
an edge are editable when adding one. Backend checks reject self-intersection,
invalid edge indices and entrances that leave their edge. Setbacks are explicit
user inputs, not automatic code requirements.

Building X/Z and true bearing are editable numerically or with move/rotation
handles. The existing photo-pick move now changes buildingPose, not the Earth
origin. A read-only, document-scoped analysis route returns area (metric/acres),
coverage and per-edge distances/findings. Geometry uses the existing polygon
and segment routines; the Site sketch shares Plan editor helpers. All edits use
the normal revision-checked session transaction, undo and Save. No Sage tools
were enabled in this phase.

Acceptance: tests/verify_facility_site_browser.py created its own layout,
drew a four-vertex boundary, flagged a street setback naming Edge 1, added a
truck entrance, applied a 30-degree building pose, dragged it, verified interior
placements/zones/routes and georeference unchanged, exercised undo/redo, and
saved/reopened identical site data. No page errors. Screenshots are under
ui-data/site-checks. Focused Python site suites: 35 passed including the
endpoint authorization test. Existing JS suites: workspace 101/101, session
63/63, transport 30/30, app 6/6; location regressions also pass.

The UI is a conceptual property editor, not an automated survey or compliance
tool. General georeference-origin rebasing of an already designed property is
not exposed: Change location explicitly confirms replacing property context.
Building moves never rebase the origin.

### Location-change regression details

The Find/Enter path now places a single match automatically; several matches
still require a choice. Map-level progress/errors accompany the panel status.
A failed photo fetch leaves the prior context intact. Requests have deadlines
(45 seconds for geocoding, 180 for imagery), propagate cancellation, and cannot
commit after the view is destroyed or its layout changes. Refresh retains all
other site fields. Static asset versions were bumped.

Evidence: 5 existing site helper tests, 6 new request/UI regressions and all 30
transport checks passed. A headless browser against port 8491 exercised the
real Site pane with controlled geocode/photo responses: Find initiated imagery,
a 503 preserved the original site/photo, Enter applied a single match through
the normal transaction, and undo restored the original context. No page errors.
Stored imagery returned HTTP 200 and was visually verified after load. No live
USGS availability claim or paid model run was made; no desktop files changed.

### SC3, 2026-10-22 (test copy only)

The Site Areas panel supports truck courts, trailer parking, car parking,
drives, sidewalks, landscape and outdoor storage. Boundaries use shared map
drawing, typed coordinates and vertex handles. Each area has a stable ID,
label and asphalt/concrete/grass surface. Upsert/delete are normal undoable,
revision-checked operations. Mouse input is rounded to millimetres so shared
edges do not acquire microscopic overlap slivers from SVG conversions.

Analysis reports property containment, building overlap, area overlap and
requested setbacks. Paved area is a geometric union, not a double-counted sum.
Shared edges are legal. Existing Shapely routines implement the checks.
Site surfaces reuse the existing floor mesh/texture renderer without adding
interior floor records. The building stays in its own frame. Fit includes the
property/areas, the compass reports true north, and site Top View is north-up.
The Building panel opens the existing perimeter wall/opening editor.

Acceptance: tests/verify_facility_site_browser.py passed on disposable layout
fl-site-acceptance-1792661687. Seven areas, a building at a 30-degree bearing,
a truck entrance and dock opening survived save/reopen. Site analysis had no
findings. Area deletion undo/redo preserved exact data. All seven surfaces
rendered in real WebGL, with 86,306 green pixels in the top-view screenshot;
desktop and 800x700 screenshots were visually inspected. No page errors.
Focused Python site/proposal/authoring suites: 99 passed. JS: workspace 101,
session 63, transport 30, app 6, adapter 115, site helpers 9 and requests 6 passed.
Evidence is under ui-data/site-checks/sc3-*.png.

These are conceptual flat site surfaces, not graded terrain, parking stalls,
turning-path certification or a surveyed property. The acceptance layout is
a UI/geometry fixture, not a finished operational site design. No paid model
calls, desktop promotion or external map-provider changes were made.

### SC4, 2026-10-22 (test copy only; no paid model calls)

`codex_runtime/site_tools.py` publishes `inspect_site_context` and
`analyze_site_fit` through the existing revision-bound gateway, with closed
schemas, normal permissions/deadlines/budgets and bounded results. Inspection
pages outdoor area geometry and reports complete imagery metadata so a reviewed
context edit can preserve it. No new filesystem, shell or network tools.

`facility_layout/site_fit.py` searches up to eight bearings on a bounded 9x9
center grid plus current center/lot centroid. It tests containment, user
setbacks and existing/proposed area overlap, ranks viable poses and returns
up to eight candidates. Truck-court and parking envelopes are optional.
Parking reserves aisle space; it does not create stalls or prove capacity.
All dimensions and unverified constraints are explicit assumptions, not
standards. Empty results do not establish infeasibility. Returned candidates
are rechecked through the real persisted normalizer/analysis; a 1 mm court
reservation gap avoids rounding-induced overlap on rotated shared edges.

`set_site_context`, `set_building_pose`, `upsert_site_area` and
`delete_site_area` reuse the existing exact-operation proposal engine. They
require review even when other edits use direct mode. Backend validation
refuses Sage changes to the geographic anchor or imagery, including clearing
the whole site. Revision binding, approval tokens and exact receipt undo are
unchanged. Site checks accompany proposal validation with bounded findings.
Sage guidance requires inspecting the authored lot, preserving interior data,
stating assumptions and refining reservations into actual access/parking.

The Site tab displays the same candidate layout as the existing Plan/3D
proposal flow. Its edit controls and old imagery requests are disabled while
reviewing. Analysis targets the candidate, not the saved base. The approval
bar now reports site edit/finding counts, fixing a misleading "no problems"
message discovered during screenshot review.

Evidence:
- 151 focused Python tests passed across site geometry/context/areas/fit,
  gateway/tools, proposals, schemas, authoring boundaries/reads and progress.
- Real-host tests cover preview purity, explicit approval, stale revisions,
  geographic restrictions, exact undo and unchanged interior coordinates.
- JS suites passed: workspace 101, session 63, transport 30, app 6, adapter
  115, site helpers 9, requests 7 and Codex operation-preview 47 checks.
- `tests/verify_facility_site_browser.py --preview-only` passed on disposable
  layout `fl-site-preview-1792673055`. A real gateway-created candidate moved
  parking outside the lot, and both the Site panel and approval bar reported
  it. Read-only review and dismissal left the saved revision/data unchanged.
  No page errors. `ui-data/site-checks/sc4-site-proposal.png` was inspected.
  The harness bridges its proposal GET/DELETE to the owning real test host
  because proposals are process-local. This is not a paid model or live
  chat-to-runtime acceptance test.

M2 is complete for conceptual manual site authoring. M3 is NOT complete:
the budget-approved one-prompt Sage exercise remains. Existing exterior
placement/marking tools still need to prove that reservations can become a
usable design with connected entrances, real aisles/stalls and dock doors.
No claims of turning-path safety, legal boundaries, compliance, grading or
walkable terrain are made. SC5 requires a terms/budget decision and SC6 remains
deferred. Desktop source/data were not modified or promoted.

**Live run, 2026-10-22 (Claude; budget approved by the user).**
- One flagship-style prompt on "Machine Shop Test" at Bayport, MN: $0.40,
  110 s, claude-sonnet-5-5 on OpenCode. All 8 tool calls succeeded.
- Sage proposed 5 outdoor areas and kept the already compliant building pose.
  It stated its assumptions. Approval left the interior and geography
  unchanged. The drive meets the entrance and the truck court, which abuts
  the building.
- The proposal carried one finding: the entrance drive crosses the street
  setback, as any driveway must. The gate is met except for that structural
  finding, which needs an entrance exemption (handoff section 1b).

**Public data layers, 2026-10-22 (Claude; test copy).** This delivers SC6's "county GIS file
import" for Minnesota open-data counties: the parcel becomes the property line. It also adds
flood, wetland, contour and soil reference layers from FEMA, USFWS, USGS and USDA, with checks of
the building, lot and areas that become site findings. Google Earth layers were rejected: they
cannot be exported, downloaded or copied. Details are in handoff section 1b.

**Entrance exemption and globe flight, 2026-10-22 (Claude; test copy).**
- A drive or sidewalk may now cross a setback through an entrance on that edge. With that, the
  SC4 gate ("validates clean") can pass: Sage's Bayport design has no geometry findings.
- Placing a layout by address now plays a globe flight from public USGS imagery. The globe holds
  until the photo is ready, then fades into it at the same framing.
- Google's 3D globe was ruled out: its terms forbid a Google map next to our non-Google photo.
- Details are in handoff section 1b.

## 8. Milestones

- **M1 (SC0 + SC1):** a layout sits on its real lot, correctly oriented, in the
  plan and in 3D.
- **M2 (SC2 + SC3):** an engineer can lay out a whole site by hand.
- **M3 (SC4):** Sage designs the site from one prompt. This is the next demo
  video.
- **M4 (SC5):** photoreal surroundings for presentations.

## 9. What Not To Do

- Do not design on the photoreal mesh. Design happens on the plan, over
  measurable imagery.
- Do not trace, measure or cache Google content.
- Do not put map API keys in the renderer, a layout or a log.
- Do not change interior semantics or the building schema in place. The site
  is an additive extension.
- Do not build a map browser. Location entry stays an address or coordinates.
- Do not show imagery under the plan in a demo before SC0 passes.
- Do not let Sage call geocoders or imagery services.

## 10. Test Suites To Extend

- New: `tests/test_facility_geo.py`.
  - Round trips through ECEF and the property frame.
  - One degree of latitude at 45 degrees is about 111.1 km.
  - A point 100 m east of the origin lands at x = 100 m.
- New: `tests/test_facility_site_context.py`: validation, findings, setbacks on
  concave lots, metrics, and pose changes leaving interior coordinates alone.
- New: `tests/test_facility_site_imagery.py`: request building, corner
  conversion, storage and service errors, with the network mocked plus one
  opt-in live call.
- Extend:
  - `tests/test_codex_mcp_schema_types.py`, for the new schemas;
  - `tests/test_facility_layout_agent_runtime.py`, for the read and fit tools;
  - the operation tests, for the four new operations.
- New browser checks, in the pattern of
  `tests/verify_facility_layout_structure_tree_app.py`:
  - SC0: the plan/3D overlay and the compass;
  - SC1: underlay alignment;
  - SC2: boundary and pose editing.
- Run the pytest suites in the test-copy venv with a short `--basetemp`. Long
  temp paths fail on Windows.

## 11. Sequencing Risk

- **SC0's reach.** It touches most of the 3D adapter and the asset registries,
  so regressions would show in every existing layout and in the demo scripts.
  Mitigation: the overlay check, plus a before/after screenshot set of the
  2026-10-21 demo layout and the gym.
- **External services.** USGS, the Census geocoder and Google can be slow, go
  down or change their terms. Store only what we may store, and fail clearly.
- **Fit analysis.** Sage's site design depends on it. Without SC4's analysis
  tool, Sage will guess coordinates, as it did with seats before placement
  intents.
- **Scope creep toward civil engineering.** Section 5 is the brake.

## 12. The Other Cases

- **Case 2, recreate or redesign an existing facility,** needs its own plan.
  Google imagery cannot be the source of outlines or models under its terms;
  open footprint data and the customer's own drawings can. Heights and
  interiors still need the customer's documents.
- **Case 3, an embedded Earth viewport:** SC5 brings the surroundings into our
  own 3D view. A free-roaming globe is a non-goal for now.
  - The globe flight (2026-10-22) is a short transition into the photo, not a
    map to browse.
  - The same Google terms clause affects SC5: while Google's 3D tiles are on,
    our USGS photo must not share the screen.
