# Private Gym Connected Tour

The connected driver is a recording aid, not a layout-generation demonstration.
It uses the desktop app's real collision-aware walking navigation between rooms.
Guided aerial camera moves climb above the building before crossing walls and
descend to the same eye position used by the walking camera.

## Run

Use the installed application Python, including its user-site dependencies.
Launch `launch.py` through `pythonw.exe` with redirected output and a hidden
launcher, never through a visible terminal during recording.

```text
tools/private_gym_tour/launch.py --name connected-rehearsal --connected --fast --pause-check
tools/private_gym_tour/launch.py --name connected-recording --connected
```

Names must be unique. `--fast` shortens holds and aerial moves, not walking
physics. `--pause-check` deliberately pauses during the first walk, verifies
that movement stops, and resumes. Do not use that flag for the recording.
Without `--connected`, the original static-viewpoint driver remains available
for supplementary footage.

The app maximizes itself. Keep it focused while recording. F8 pauses/resumes
the tour and F9 stops it; avoid conflicting Camtasia hotkeys. Focus loss pauses
the route. The app closes when the route finishes or a verification fails.
The driver never starts or stops Camtasia.

## Verification

Outputs are under `.runtime/private-gym-tour/<name>/`:

- `report.json`: preflight routes, live walking traces, arrival checks, camera
  handoff deltas, screenshots, and failure diagnostics.
- PNGs: both destination views and intermediate walking/flight frames.
- `launch.json`: process completion and saved-layout hash verification.
- `runtime/last-application-run.json`: backend shutdown evidence.

Preflight uses exact catalog revisions, the editor's footprint resolver, the
existing route planner, actual ground surfaces, and wall geometry. Aerial
clearance is sampled every 0.1 m with a 0.35 m camera radius. A blocked route,
unsupported floor, failed mouse capture, or missed destination stops the tour;
there is no teleport fallback.

Walking paths are also replayed through the existing movement solver at six
frame intervals from 16 to 200 ms. The Warrior Hall approach has an explicit
centered doorway waypoint: its original diagonal path grazed the corner at
some frame intervals even though the route planner accepted it. This is a
tour-route correction, not a change to the product's general route planner.
Aerial heading and tilt interpolate independently of world-space look targets
to stay within the existing orbit camera's polar limits. Actual camera positions
are checked after every applied flight frame and at every mode handoff.

The launcher snapshots the layout store, denies mutating API requests in the
tour session, and checks both the live file and snapshot hashes. It does not
save layout changes, call Sage, or change product navigation/rendering logic.

```text
node --test tools/private_gym_tour/route.test.cjs
```

## Verified Rehearsal

`.runtime/private-gym-tour/connected-05/report.json` records the completed
native desktop run: 32 walks, 11 aerial moves, zero recorded collisions, six
continuous takeoff/landing handoffs, and a successful pause/resume check.
All 282 placements passed the renderer transform audit with no missing,
unavailable, hidden/pending placements or pending loads. The maximized app
produced 88 captures, including 39 intermediate travel views. Both saved-layout
hashes remained unchanged; no mutating API requests occurred. The backend
closed cleanly without forced termination. Eight focused Node tests also pass.

The rehearsal used `--fast --pause-check`. For the recorded take, omit those
flags so detail views and aerial movements have their normal holds. Start
Camtasia separately before launching; startup/model warmup can be trimmed out.

## Wall Artwork Verification

The model-only audit above did not establish wall-art visibility. A subsequent
native check reproduced 15 fitted graphics with `status: ready` but hidden
parent groups. A layer refresh during texture loading hid the group; the
completion callback restored only its child mesh. The shared renderer now
restores the correct visibility root while respecting the current walls toggle.

The connected driver compares every saved wall-art ID and image path against
renderer diagnostics before touring and at every capture. Missing, failed or
hidden artwork stops the take instead of silently recording bare walls.

```text
tools/private_gym_tour/launch.py --name artwork-rehearsal --connected --fast --artwork-check
node --test tools/private_gym_tour/artwork.test.cjs tools/private_gym_tour/route.test.cjs
node tests/test_facility_layout_three_adapter.js
```

`--artwork-check` is a targeted static-camera QA pass, not the connected tour.
`.runtime/private-gym-tour/artwork-fixed-01/report.json` passed with all 40
saved wall graphics loaded and visible, no generated-resource failures, and
a successful wall-layer off/on check. Native screenshots verified the Viking,
Zulu, gallery, kitchen graphic, soccer action mural and both goal-wall graphics.
The live and snapshot layout hashes stayed unchanged. Renderer tests passed
114/114; the combined artwork, wall-geometry and route tests passed 23/23.
