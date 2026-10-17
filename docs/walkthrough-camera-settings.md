# Walkthrough Camera Settings

Implemented September 27, 2026 for Facility Layout and the cooling-tower
Plant / Process Explanation walkthrough. This is a navigation preference, not a
layout operation. Operator dimensions, physical position and saved geometry do
not change when selecting a camera preset.

## Controls

Open the gear button titled "Walkthrough camera settings" in the 3D toolbar.
Choose a preset, or adjust Follow distance and Camera rise. Changing a preset or
slider selects third-person mode without starting or moving the walker.
The reset icon restores Standard. Escape closes the panel and returns focus.
Mouse-wheel scrolling over the active third-person viewport adjusts distance;
first-person, orbit, drone and Ctrl+wheel retain their existing behavior.

| Preset | Follow distance | Rise above the aim anchor |
| --- | --- | --- |
| Close | 3 m | 0.15 m |
| Standard | 5 m | 0.5 m |
| Wide | 9 m | 1.5 m |

Distance is bounded to 2.5-14 m; rise to 0-3 m. Field of view is unchanged.
The process viewer applies its existing model scale to these visual metre
values; this does not certify the model engineering scale or physical access.

Both workflows share `inspectorpro.walkthrough-camera.v1` in local storage.
Preferences survive reloads in the same browser/desktop profile. Invalid values
are bounded or defaulted; denied storage and quota failures retain a session
preference. Preferences never enter the layout, editor history or backend writes.

## Implementation

- `static/walkthrough_camera_settings.js`: common presets, normalization,
  persistence, wheel normalization and accessible controls.
- `static/walkthrough_camera_settings.css`: bounded light/dark settings panel.
- `static/facility_layout_three_adapter.js`: configurable collision-aware boom,
  distance-dependent obstacle search, independent mouse-look aim and cleanup.
- `static/facility_layout_workspace.js`: toolbar entry and state synchronization.
- `static/index.html`: dependencies and process camera integration, scaled
  distance/rise, first-person aim restoration and listener/panel disposal.

Collision checks still govern the actual camera position. Near equipment the
actual distance may be shorter than requested. Tight obstruction temporarily
uses the eye position; the preference remains intact and resumes when clear.
This retains existing illustrative collision models, not certified clearance.

## Verification

Focused checks passed:
- 78 facility adapter tests and 88 workspace checks.
- 17 Python process-walkthrough and parts-manual UI contracts.
- Shared-avatar geometry/gait/resource and process-operator suites.
- New camera preference, bounds, storage-failure and wheel-normalization tests.
- Wide-camera collision beyond the old five-metre search radius; body-position
  invariance, first-person wheel isolation and listener disposal.

The small real-browser controls check passed at 900x700 and 360x560 in both themes:
`.runtime/walk-camera-controls-20260927-172501/result.json`.
This final run uses the actual workspace toolbar-button builder and checks its
gear asset and settings call-site wiring as well as the shared settings panel.
Preset-button text contrast was 9.29:1 dark and 12.58:1 light. It also verified
keyboard sliders, reset, focus, Escape, hidden-owner dismissal, icons and cleanup.
Screenshots were inspected.

The final real-application rerun is recorded at
`.runtime/walk-camera-20260927-171005/result.json`: passed with confirmed backend
shutdown, zero page/shader errors, zero layout mutation requests and unchanged
original manual-layout hash. Final application screenshots were inspected.
The verifier covers the actual 827-placement manual layout and real tower,
presets, wheel zoom, pose invariance, reload/cross-workflow persistence,
mouse-look stability, visible movement, wide/narrow screenshots, editor-state
equality, zero layout mutation requests and backend cleanup.

The earlier `walk-camera-20260927-164333` run reached the interaction assertions
but failed while printing its completion receipt after the output pipe closed.
Its failed receipt and captures are retained, not reclassified as a pass. The
reporter now preserves its on-disk evidence if stdout becomes unavailable.

Reproduce with `tests/verify_walkthrough_camera_app.py` and
`tests/verify_walkthrough_camera_controls.py` in the Python Playwright environment.
Windows subprocesses must remain hidden.

Native Electron recapture was not performed for this change. It uses the same
frontend, but these results are not a new native acceptance or desktop performance
qualification. No provider requests are required.
