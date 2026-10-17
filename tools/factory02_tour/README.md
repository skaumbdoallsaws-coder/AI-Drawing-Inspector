# Factory 02 desktop tour

This harness rehearses the existing Factory 02 layout in the native Electron
application. It demonstrates Plan selection, 3D views, collision-aware walking,
interior details, dock-yard aerial views, and employee parking. It does not
generate or edit a layout and does not record video.

## Run

The recording launcher opens the full tour maximized and waits at the Plan
overview. Invoke it directly with windowless Python from the repository root:

```text
C:\Python314\pythonw.exe tools\factory02_tour\record.pyw
```

Start recording in Camtasia, return to InspectorPro, then press F8.
Returning focus alone never supplies the initial start cue. The
harness does not start a recorder. The connected Camtasia plugin creates
screenshot storyboards and narration, not live screen recordings.

For shorter checks, use `launch.py --name <unique-name>`. Add `--full` for the
complete route, `--plan-only` for three Plan checkpoints, or `--verify-ready`
for a startup-only verification that automatically closes without walking.
All normal runs wait for a cue by default. `--auto-start` is an explicit
rehearsal-only opt-in; `--wait-for-cue` remains supported.

F8 starts/pauses/resumes; F9 stops. The bottom-right tour overlay stays hidden
before and during recording. Losing window focus pauses the tour. Refocusing resumes a
focus-triggered pause; an explicit manual pause stays paused. Keep the rehearsal
window focused during walking. A five-minute pause limit applies after the tour
has started, not while waiting for the initial recording cue. The launcher's
one-hour process watchdog still applies to the whole session.

`record.pyw` and the child-process launcher require no terminal window. Electron
starts with `CREATE_NO_WINDOW`, the managed backend uses `windowsHide: true`
and `shell: false`, and output is redirected into the run directory. Do not
wrap the recording launcher in PowerShell, cmd, or npm. No terminal commands
are launched by the tour's camera or walking steps.

## Isolation and evidence

Each run uses a new `.runtime/factory02-tour/<name>` directory, isolated desktop
profile and port, and a copy of the saved facility store. Existing runs cannot
be overwritten. The asset library is shared for reading. The harness does not
attach to, reload, or close the user's existing app window.

Facility write requests are blocked in the rehearsal session. Every checkpoint
checks the editor document and dirty flag plus the original and copied saved
file hashes. A changed original aborts verification rather than overwriting it.
Normal completion closes the rehearsal and its managed backend.

Evidence includes `report.json`, `events.jsonl`, numbered PNG captures,
`launch.json`, and `runtime/last-application-run.json`. Check all of these:

- Report status is `passed`, with zero blocked writes and unchanged saved state.
- Walking arrivals match their targets; collision counts are recorded per leg.
- Placement audit has no missing placements or transform mismatches.
- Launcher confirms the original and snapshot bytes are unchanged.
- Backend cleanup is confirmed and the application reports zero Save calls.

Captured images receive a coarse nonblank check; visual review remains
necessary. The placement audit checks transforms, not the visual completeness
of every imported CAD mesh. Subject readiness waits for an overview or detail
representation, not a placeholder, for each requested asset identity.

## Rehearsal findings

The full rehearsal on October 3, 2026 (local time), stored in
`.runtime/factory02-tour/full03`, completed 54 walking legs with zero collisions
and 26 captured checkpoints. Pause/resume and exact position restoration after
focus loss passed. Saved data was unchanged and the backend shut down cleanly.

That run predates the final selection-zoom, first-person gaze restoration, and
pause-aware camera timing refinements. The native `short05` run verified four
walking legs, pause/resume, exact first-person position and gaze recovery, and
unchanged saved data. Its Plan zoom passed the scale check, but screenshot
review found oversized labels; the final selection refresh addresses that
display problem. Each report records the source hashes it used.

The final `plan07` native run passed all three Plan checkpoints. Screenshot
review confirmed readable labels and the centered cubicle highlight. Saved
bytes remained unchanged, no Save calls occurred, and backend cleanup completed
normally. Eight control tests and 105 adapter tests passed; the adapter source
hash still matches the full-route run. The complete route has not been rerun
with the final presentation-only and timeout changes.

The `ready08` native startup check verified a maximized window, the initial
paused state, no walking or selection changes while waiting, and acceptance of
the explicit Start button. Focus-handler checks did not start the tour. The
test then stopped without walking; saved bytes were unchanged. Nine control
tests and three launcher-option tests pass, including a delayed recording cue
that must not consume the mid-tour pause limit.

The subsequent `short06` instance became unresponsive during tree expansion
and required forced termination of that isolated process tree. Its launcher
confirmed both saved files were unchanged. Its partial report is not a pass.
Renderer commands now have a 60-second timeout; screenshot requests have a
15-second timeout. These bounds require a responsive Electron main process;
the launcher also has a one-hour process watchdog. Repeated-run reliability
and the cause of the unresponsive instance remain open.

The route is functionally rehearsed, but not yet qualified for smooth recording.
Diagnostics at some stops report roughly 91-132 million rendered triangles.
The imported CAD rendering workload needs a separate profiling and optimization
pass. Screenshot success must not be reported as a frame-rate qualification.

The dock yard is 1.35 m below the factory and has no authored walking ramp.
The tour stays on the factory side, switches to an elevated camera, and later
lands on employee parking. It never pretends the walker can step off the dock.

## Tests

```text
node --test tools/factory02_tour/control.test.cjs
node tests/test_facility_layout_three_adapter.js
node --check tools/factory02_tour/tour.cjs
python tools/factory02_tour/test_launch.py
```

The route uses existing editor, tree, and 3D adapter APIs. Shared adapter fixes
cover large-site local route searches, truthful search-budget outcomes, camera
gaze control, and preserving the new heading when a walk begins. The tour's
coordinates and story are specific to Factory 02, not a general layout planner.
