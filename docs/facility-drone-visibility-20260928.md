# Facility Drone Visibility Correction

Date: 2026-09-28

## Reproduction and Cause

The existing Drone distance window hid placements whose centers were beyond its altitude-dependent range, and shortened the camera far plane. This was not a GLB loading failure. Long walls could disappear even when their near end was within range. The earlier walking performance checks did not exercise this Drone-specific behavior; a successful transform audit alone did not establish complete visibility.

A read-only normal-Electron check reproduced the symptom in Factory 02 - Integrated Production, at the central aisle and 8 m altitude:

| Scene objects retained | Before | After |
| --- | ---: | ---: |
| Operators | 26/40 | 40/40 |
| Wall sections | 0/6 | 6/6 |
| All placements | 253/836 | 836/836 |

These counts are unique placement IDs in actual visible scene meshes/instance buffers, not a promise that every object is simultaneously within the camera image. Normal camera-frustum culling remains enabled. Before/after Drone screenshots were visually inspected.

## Correction

- Drone retains the complete scene by default. Distance hiding requires the explicit adapter option `droneDistanceCulling: true`; no new UI setting is claimed.
- The default Drone far plane covers the layout bounds from the current camera position.
- Optional distance hiding tests distance to transformed asset bounds instead of placement centers, retaining nearby ends of long assets.
- Static CAD batching, detail loading, motion ownership and ordinary frustum culling remain intact.
- The application adapter cache version changed to `20260928-complete-drone-scene-1`. Existing windows need reload/reopen.

Implementation: `static/facility_layout_three_adapter.js`, its version in `static/index.html`, and `tests/test_facility_layout_three_adapter.js`. Native verification: `desktop/tools/facility-visibility-entry.cjs`.

## Verification

- Renderer: **93/93**, including two new default/opt-in Drone visibility cases, far-plane coverage and mode restoration. The new default case failed against the previous implementation.
- Workspace: **88/88**; session: **61/61**; navigation authoring: **8/8**. Total: **250 focused JavaScript checks**.
- Real-WebGL Playwright batching verification passed all nine geometry/fallback cases, including transforms, normals, picking, selection, exact motion/restoration and disposal. Desktop, narrow and mobile captures passed nonblank/moving checks.
- Native after-fix run passed eight stages: Factory orbit, Drone, Walkthrough, immersive exit, and two round trips to the original manual sheet. Each Factory stage retained all 40 operators and six wall sections. Both manual-sheet visits retained its 20 operators; that saved sheet has no walls.
- Zero transform mismatches, zero Save calls and unchanged saved-layout hashes. Both owned test backends terminated with confirmed cleanup.

Evidence: `.runtime/facility-visibility-20260928/{before,after}/report.json`, numbered PNG captures and `runtime/last-application-run.json`. The before report's `passed` means its observational probe completed; its recorded missing-object counts reproduce the defect and are not acceptance of that behavior. The after harness asserts full expected visibility.

| Layout | Unchanged SHA-256 |
| --- | --- |
| Factory 02 | `a217107d22b3d78b6fa186d532138d8d8a169280c47a1a39d4a568eb2dcac3a0` |
| Original manual | `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088` |

## Boundaries

The user's existing window was not closed, reloaded or edited. Its exact active camera mode could not be inspected because the native Computer Use helper was unavailable. The isolated normal-Electron reproduction establishes the concrete Drone defect and correction.

Walls are authored on Factory 02 only; this change does not add walls to the original manual layout. Retaining the full Drone scene can increase GPU work compared with the incomplete distance-limited scene. This is a visibility correction, not a new FPS qualification.
