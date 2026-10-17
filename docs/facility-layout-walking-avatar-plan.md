# Facility Layout Walking Avatar

September 27, 2026. Scoped extension of the existing 3D Walkthrough, independent
of the paused provider-backed generation work. No provider calls required.

## Scope

One human-scale articulated worker in third-person view, idle/walk animation,
first/third-person camera switching, existing WASD/Shift and click-to-walk,
camera obstruction handling, and exact return to the previous overview.
Existing Drone mode, layout sheets, equipment selection and movement playback
must continue to work. No multiplayer, staffing simulation, new saved placement,
Save operation, or safety/compliance claim.

The catalog operator GLB is static (no skins or animation clips) and about 9 MB.
Use a dedicated lightweight Three.js articulated worker with workwear and hard
hat, built from reusable geometry. This is a navigation mannequin, not a new
catalog asset. Its gait follows actual collision-resolved travel; pressing a
movement key against an obstacle must not play an in-place walking cycle.

## Implementation Sequence

1. Separate physical walker position from the display camera. Reuse the existing
   floor spawn, obstacle polygons, movement resolution and route planner.
   First-person remains the initial view for compatibility; the avatar toggle
   selects third-person before entry or while walking. C also changes view.
2. Add an isolated avatar presentation module with owned/disposable geometry,
   smooth heading changes, distance-driven gait, and a bounded idle transition.
   Integrate into the existing render loop only; no second animation loop.
3. Follow the walker with the existing mouse-look orientation. Shorten the
   camera boom before equipment/boundaries and floor intersections. Hide the
   avatar when the camera is too close to see it cleanly. The camera must never
   move the collision body. Apply the same position to click-to-walk and Drone
   handoff; camera toggles must not move the body or alter a route.
4. Add a familiar icon toggle beside Walkthrough, with tooltip/pressed state.
   Keep picking restricted to layout objects. On exit, suspend, sheet parking,
   context loss or disposal, hide/dispose the avatar and release its resources.
5. Add focused regressions and run an isolated manual-layout acceptance check.

## Acceptance

- First/third-person toggle preserves physical position, heading, route and
  selection; exiting restores the overview camera.
- Real manual layout (827 placements): avatar visible at human scale, movement
  and limb animation visible, wall/equipment collision respected, no floor
  penetration, and camera obstruction shortens the boom rather than clipping.
- Collision checks remain the current nominal footprint model, not a claim of
  exact mesh collision or general stair navigation.
- Idle stops the frame loop after settling; no duplicate avatars after repeated
  entry, Drone handoff, suspend/resume or layout-sheet switching.
- Plan and saved layout bytes, placement counts, draft revision, selection and
  Undo history remain unchanged. Zero Save calls in acceptance.
- Desktop-sized and narrow viewport screenshots and canvas-pixel comparisons
  prove framing, nonblank output and animation. Inspect actual screenshots.
- Test only an isolated copy of the manual layout. Preserve source hashes and
  failure evidence; stop owned test backends. State native vs browser coverage
  separately in the completion report.

## Primary Owners

- static/facility_layout_avatar.js (new presentation helper)
- static/facility_layout_three_adapter.js (position, camera and lifecycle)
- static/facility_layout_workspace.js (toolbar command/state)
- static/index.html (script loading/cache versions)
- focused avatar/adapter/workspace tests and isolated manual-layout verifier

## Status

- Inspection and scope: complete.
- Implementation: complete, including a five-metre retracting camera boom and
  a low framing anchor that keeps the whole avatar above the walkthrough HUD.
- Focused regressions: 76 adapter and 88 workspace checks passed; real-Three
  avatar scale, geometry, gait, idle and resource-disposal checks passed.
- Manual-layout browser acceptance: passed, including routing, Drone handoff,
  actual-machine collision, wide/narrow framing and visual inspection.
- Native acceptance: not established. The restricted launch exited before a
  stage report with 0x80000003; an unrestricted launcher could not access the
  existing private Electron executable. Neither result qualifies the UI.

## Verification Record

Initial walking-avatar browser run (superseded visually by the finish below):
[machine-readable result](../.runtime/avatar-browser-20260927-114329/result.json).
Screenshots:
[walking, wide](../.runtime/avatar-browser-20260927-114329/walking-1440.png),
[idle, narrow](../.runtime/avatar-browser-20260927-114329/avatar-900.png), and
[machine collision](../.runtime/avatar-browser-20260927-114329/machine-collision.png).
Both tested viewports (1440 x 900 and 900 x 700) passed:

- Real manual layout and real mesh representations loaded; 827 placements.
- Actual keyboard movement, articulated gait, idle settling, perspective
  switching without moving the walker, route completion and Drone handoff.
- At the selected Doosan machine, 7 blocked movement attempts were recorded;
  gait returned to idle while W and Shift were still pressed.
- Toolbar controls stayed within the viewport. Projected head/feet cleared the
  toolbar and HUD; screenshots contained visible worker vest pixels.
- Switching to Plan removed the avatar. Layout, draft/base revisions, selection,
  history, history cursor and dirty state were unchanged.
- Zero layout mutation requests, zero Save calls, zero page errors, unchanged
  isolated saved copy and original file, and confirmed backend termination.

Original manual-layout SHA-256, rechecked after verification:

    a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088

Earlier failures remain in their separate .runtime/avatar-browser-* directories.
They exposed a fixed short-viewport framing problem and animation settling that
incorrectly shared the movement timestep cap. Another run timed out during the
initial 3D click; cold setup now uses the same bounded 150-second test deadline
as mesh loading. This is not a new startup-performance qualification.

Native test support is prepared in desktop/tools/application-avatar-check.cjs
and desktop/tools/run-avatar-check.py. It uses the normal application entry with
an isolated facility store. Restricted execution exited with 0x80000003 before
producing a stage report; attempts outside that session could not access the
private Electron executable. Native acceptance remains pending, not failed or
passed on the strength of browser evidence.

## Smooth Operator Finish Follow-Up

Requested September 27: bring the walker closer to the smooth silhouette of the
stationary catalog operator, without replacing the articulated navigation model
with that static GLB. Preserve height, collision body, controls and travel-driven
animation. Use smooth tapered clothing, rounded shoulders/hips/boots and curved
reflective trim; retain a recognizable industrial worker palette.

Verify finite geometry/normals, bounded triangle/resource counts, human scale,
gait and disposal. Inspect front, rear, side and walking renders before rerunning
the isolated manual-layout checks at wide and narrow sizes. No layout writes,
provider requests, new runtime assets or extra animation loop.

Implemented and verified:

- Smooth torso/hips, rounded hands and work boots, refined face and hard hat.
- Continuous two-bone skinned sleeves and trouser legs replace separate joint
  spheres, so elbows and knees bend without visible ball-joint seams. The
  existing resolved-distance gait and navigation code remain unchanged.
- Reflective trim follows the curved vest. Clothing, skin, trim and helmet have
  separate surface finishes. The stationary operator asset is unchanged.
- Still 1.876 m tall and under 0.61 m wide at rest; 34 meshes, 29,952 triangles,
  12 shared geometry resources, 6 materials and 4 small skeletons. All owned
  resources are released exactly once. No external asset download or new loop.
- Real-Three tests pass for bounds, finite positions/normals, normalized skin
  weights, triangle budget, gait floor clearance, idle and complete disposal.
  Adapter 76/76 and workspace 88/88 regressions pass.

Close-up Playwright renders, visually inspected in front, three-quarter, side
and rear views:
[idle](../.runtime/avatar-finish-20260927-121037/operator-idle-views.png),
[walking](../.runtime/avatar-finish-20260927-121037/operator-walking-views.png),
[render evidence](../.runtime/avatar-finish-20260927-121037/result.json).

Latest isolated manual-layout check:
[result](../.runtime/avatar-browser-20260927-121046/result.json),
[walking, wide](../.runtime/avatar-browser-20260927-121046/walking-1440.png),
[idle, narrow](../.runtime/avatar-browser-20260927-121046/avatar-900.png).
Both 1440 x 900 and 900 x 700 pass. Actual keyboard walking, idle, route arrival,
first/third-person switching and Drone handoff pass. Six blocked attempts at
the Doosan machine stop the gait while movement keys remain held. Screenshots
and visible-vest pixel checks confirm framing and a nonblank articulated worker.
Editor state, original layout and isolated saved copy remain unchanged; zero
layout mutations, zero Save calls, zero page errors, confirmed backend cleanup.

This is shared-frontend browser qualification. Native Electron recapture was
not rerun; the earlier runtime-access limitation remains. The avatar script's
cache version is bumped so a fresh desktop load requests the new presentation.

## Existing Layout Operators

The shared character now also represents existing operator placements during standing
and motion playback. See [animated operator implementation and native evidence](facility-layout-animated-operators.md).
This is a separate visual use of the character, not a new walkthrough-created placement.

## Trying It

Reopen InspectorPro to load the updated shared frontend. Open the manual layout,
switch to 3D, and enter Walkthrough using the walking-person icon. Press C to
show the avatar, or choose the adjacent camera icon before entering Walkthrough.
WASD moves, Shift moves faster, mouse-look turns the view, C switches perspective,
G hands off to Drone, and Escape exits to the prior overview. Existing floor
click navigation remains available. This navigation never creates a layout
placement or saves a change.
