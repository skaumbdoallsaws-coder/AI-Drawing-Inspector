# Facility Walkthrough Performance

Date: 2026-09-28

Follow-up: [Drone visibility correction](facility-drone-visibility-20260928.md). The walking benchmark below did not cover Drone's automatic distance cutoff. The later native check reproduced missing operators/walls and now verifies the complete default Drone scene. A transform audit is not sufficient proof of visibility across modes. Full-scene Drone rendering may increase GPU work; no new Drone FPS claim is made.

## Changes

- Walking consumes elapsed frame time up to 250 ms instead of discarding time above 50 ms. Ordinary slow frames no longer reduce the specified walking speed. Long stalls deliberately discard excess time, without accumulating catch-up movement.
- Movement and third-person camera obstruction checks query the existing spatial grid using a conservative swept region. The existing narrow-phase collision and spatial subdivision remain authoritative, including sliding and thin walls.
- Walking, pointer look and click-to-walk use the existing interactive rendering resolution. Full display resolution returns at rest. Blur clears movement and cancels navigation.
- Moving crosshair queries run at most ten times per second and use a bounded ray distance. Explicit context actions still request a fresh result. Diagnostics read cached context rather than introducing another raycast.
- Unchanged highlights and instance colors no longer trigger repeated work. Emissive uniform changes do not invalidate shader programs.
- Compatible static neutral CAD meshes are baked into shared prototype geometry and merged using the vendored Three.js `mergeGeometries` utility before repeated placements are instanced. No geometry decimation, catalog changes or placement merging is performed. Original prototypes remain available for motion.
- Source-colored, reflected, partially drawn, morph/skinned and incompatible meshes retain their existing path. Failed merges fall back to the original meshes. Temporary buffers and owned merged buffers are disposed.
- The normal Facility Layout runtime supplies the merger; the adapter script cache version is updated. Existing windows need a normal reload/reopen to load the change.

Owners: `static/facility_layout_three_adapter.js`, the existing Three runtime import/adapter options in `static/index.html`, and focused regression tests. Other pre-existing working-tree changes in these files are not part of this performance claim.

## Native Evidence

Read-only normal-Electron application checks used a separate application profile and the actual **Factory 02 - Integrated Production**, with 836 placements, on the Intel UHD Graphics D3D11 renderer. Each invocation used the same six-second walking path: one initial sample, one warm sample, and one CPU-profiled sample. These are diagnostic samples, not a statistically qualified release benchmark.

| Version | Initial FPS | Warm FPS | Profiled FPS | Warm speed | Warm draw calls | Warm triangles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Before changes | 1.16 | 19.49 | 14.49 | 1.315 m/s | 835 | 4,191,386 |
| Timing/index/picking/highlights | 2.82 | 13.82 | 14.06 | 1.404 m/s | 903 | 6,450,266 |
| With static batching | 25.97 | 18.81 | 20.29 | 1.404 m/s | 596 | 6,458,402 |

Important qualifications:

- Initial samples include cold work and are highly variable. Do not interpret their ratio as a startup speedup.
- Deferred detail loading changed the workload: ten groups remained deferred in the original warm sample, nine in the subsequent warm samples. The original and final FPS are **not** an equal-geometry comparison.
- Batching reduced draw submissions by about one third relative to the timing-only run with a similar heavy workload. Merged bounds can change frustum-culling granularity slightly; the optimization does not remove source triangles.
- Stable walking speed is independently covered at 5, 10, 20, 30, 60 and 144 FPS. Native samples confirm approximately 1.4 m/s under load. This does not promise steady rendering or full elapsed-time travel during stalls longer than 250 ms.
- Full-factory rendering still falls below 30 FPS in these samples. No 60 FPS or hardware-independent performance claim is made. Further improvement needs measured detail/LOD and GPU-work reduction, not simply increasing walking speed.

Native final audit: all 836 placement transforms match; 2,141 stored instance matrices audited; zero missing or mismatched placements. Screenshots show the real factory, markings, walls and walking avatar. All three test backends shut down normally with confirmed cleanup. Each run recorded zero Save calls.

Evidence under `.runtime/walkthrough-performance-20260928/`:

- `baseline/report.json`, `optimized/report.json`, `batched/report.json`
- Each run's `walking.png`, `walking.cpuprofile` and `runtime/last-application-run.json`
- `webgl/report.json` and desktop/narrow/mobile static and moving CAD captures

Native harness: `desktop/tools/walkthrough-performance-entry.cjs`. It uses the normal authorized application, a separate profile, saved-byte hashes and normal lifecycle cleanup; it does not enable a remote debugging port.

## Verification

- Renderer: **91/91** checks, including six frame-rate cases, bounded stalls, thin-wall sprint collision, 600 indexed/full-scan comparisons, interactive resolution, context query bounds and redundant highlight avoidance.
- Session: **61/61** checks.
- Workspace: **88/88** checks.
- Navigation authoring: **8/8** checks.
- Real-Three avatar and shared camera-settings regression scripts passed.
- Playwright real-WebGL test: nine batching/fallback cases, including actual CNC GLB geometry, canonical and placement transforms, normals, selection, ray picking, exact visual motion preview, duplicate suppression, restoration and disposal. The CNC changes from 33 prototype meshes to one; both placements retain 38,508 indexed vertex references. Maximum tested world-vertex error is below 0.000001 m, consistent with Float32 storage.
- Playwright captures at 1440x900, 900x700 and 390x844 are nonblank and change during rotation. Desktop/native and mobile CAD screenshots were inspected.

Tests: `tests/test_facility_layout_three_adapter.js`, `tests/verify_facility_static_batching.py`, and its `tests/fixtures/facility_layout/rendering/static-batching.*` fixture.

## Saved-State Isolation

Before/after SHA-256 values match:

| Layout | SHA-256 |
| --- | --- |
| Factory 02 | `a217107d22b3d78b6fa186d532138d8d8a169280c47a1a39d4a568eb2dcac3a0` |
| Original manual | `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088` |

No provider calls, layout saves or source asset rewrites were needed. The user's existing desktop window was not force-closed or reloaded.
