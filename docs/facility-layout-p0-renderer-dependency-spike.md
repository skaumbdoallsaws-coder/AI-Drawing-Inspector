# Facility Layout P0 Renderer and Dependency Spike

Date: 2026-07-28

Status: P0 renderer, local dependency, offline loader, and real repeated-rack
spikes complete; production application migration remains gated

## Decision

**GO, with conditions, to an isolated Facility Layout renderer proof using a
shared WebGL/Three.js renderer, an orthographic plan scene, and repeated
placement instancing. Use SVG as the WebGL-unavailable/context-loss fallback.
Do not use the measured Canvas 2D full-redraw path as the primary renderer.**

**GO for the P0 dependency and renderer-choice gates. NO-GO to production
application integration in P0.** Exact r184 modules are locally vendored with
hashes and license retention. A network-denied browser smoke imported the
official loader, parsed a valid GLB, rejected a corrupt GLB, and rendered a
nonblank WebGL 2 scene. A second browser proof loaded a real rack GLB and
verified instance-aware stable placement resolution. Release-length full-layer
benchmarks, context recovery, lifecycle churn, and minimum hardware remain
later release gates.

| Decision item | Result | Reason |
| --- | --- | --- |
| WebGL placement layer | Conditional GO | 8.8 ms p95 at 500 and 8.7 ms p95 at 5,000 on the named machine |
| SVG fallback | Conditional GO | 8.7 ms p95 at 500; 32.89 ms at 5,000 is usable only as a degraded/virtualized path |
| Canvas 2D full redraw | NO-GO as primary | 33.5 ms p95 at 500 and 41.6 ms at 5,000 |
| Repeated-geometry instancing | P0 GO | A real 8x16 rack GLB rendered six stable occurrences through 10 instance groups instead of 60 independent mesh draws |
| Local official Three.js/GLTFLoader | P0 GO | Exact r184 files, hashes, package provenance, and MIT license are present in the scoped source set; network-denied valid/corrupt GLB checks pass |
| CDN plus inline custom GLB loader | NO-GO for the editor | Offline failure, incomplete glTF support, copied 327 MB buffer, no real cancellation, and no managed provenance record |
| Meshopt, Draco, or KTX2 | NO-GO now | No representative-asset performance, failure, license, cancellation, or offline decoder evidence |

## Proof Status and Non-Claims

These boundaries are binding:

| Question | What this spike proved | What remains unproven |
| --- | --- | --- |
| Current dependency risk | The working page has only a remote cdnjs Three.js r128 core, no SRI, and an inline custom `THREE.GLTFLoader`; loss of the CDN leaves no Three.js runtime. The custom loader's code and 327 MB buffer copy were inspected. | No current application offline fallback was exercised. |
| Pinned local Three.js and official GLTFLoader | Same-version r184 files are vendored under `static/vendor/three/0.184.0`; `VERSIONS.md` pins upstream package integrity, per-file hashes, and MIT license. Network-denied Edge imported the official loader, parsed a valid GLB, rejected a corrupt GLB, and rendered WebGL 2. | Production r128-to-r184 application migration and all viewer regressions remain unproven. |
| Compression | Official GLTFLoader decoder hooks were identified. | No Meshopt, Draco, or KTX2 package was selected, licensed, packaged, run offline, failure-tested, cancellation-tested, or compared on a representative asset. Compression is **not proven or approved**. |
| Renderer choice | The seeded 500/5,000 placement-footprint comparison was measured on the named Dell/Edge/Intel environment. It supports WebGL primary and SVG degraded fallback for this bounded layer. | It does not prove the Three.js adapter, full plan layers, release-length protocol, headed browser, minimum hardware, picking, context loss, loading, or remount budgets. |
| Prototype/instance behavior | In addition to the synthetic 500/5,000 layer benchmark, the standalone extractor exported one real 8x16 rack prototype. The pinned local loader rendered six extracted occurrences through 10 `InstancedMesh` groups, resolved a raycast `instanceId` to a stable placement ID, and recorded a 6x draw-call reduction. | Other rack configurations, production catalog publication, compaction, large-scale picking p95, and release-length full-layer performance remain unproven. |

## Scope and Inputs

This spike addresses the rendering-agent work in
`docs/industrial-layout-platform-implementation-plan.md`:

- local Three.js module, loader, compression, and offline packaging assessment;
- SVG versus Canvas 2D versus WebGL at 500-placement editing and
  5,000-placement navigation;
- repeated-geometry instancing;
- a recorded primary renderer and fallback;
- no user-visible feature.

Evidence is tied to the current dirty worktree rather than assumed HEAD content:

| Input | SHA-256 / identity |
| --- | --- |
| Git commit | `96e678d40113ccf8e0f55917879708c54aa12cee` |
| `static/index.html` working copy | `B22372662AD7E82B48D82A64244726C749E213D05B0645B9489C62FE810E0C53` |
| implementation plan working copy | `D3021F3E078BF6F95731D50C536B8FF4347B094350B191FED66E60F41B3BB980` |
| legacy `Assem3_colored.glb` | 327,184,996 bytes; `DA2BE02ACEA430027324857E58DB3DDEE81713DCF9B54E38D45B830671898CE2` |

The benchmark is a placement-footprint renderer spike, not a full Facility
Layout benchmark. It deliberately excludes zones, routes, labels, 10,000
clearance volumes, picking, spatial queries, 3D assets, loading, remount,
context-loss recovery, and accessibility semantics.

## Current Architecture Findings

The current `static/index.html` is a monolithic classic-script architecture:

- Line 14161 loads Three.js r128 from cdnjs without Subresource Integrity.
- Lines 14163-14215 define a minimal inline `CSS2DRenderer`.
- Lines 14217-14306 define a minimal inline STL loader.
- Lines 14311-14425 define `THREE.GLTFLoader` as a custom binary-GLB-only
  parser.
- Line 15525 hard-codes the 327 MB Facility Layout GLB URL.
- Lines 37967-37969 create a renderer and use uncapped
  `window.devicePixelRatio`.
- Lines 38008-38043 run the assembly renderer continuously.
- Lines 38093-38158 load through the custom loader. A mount token discards a
  stale result but does not abort the download or parse.

The custom GLB parser:

- assumes one JSON chunk followed immediately by one BIN chunk;
- copies the complete BIN chunk with `ArrayBuffer.slice`;
- does not validate declared GLB length, chunk types, or most offsets/bounds;
- ignores interleaved `byteStride`, sparse and normalized accessors, UVs,
  tangents, vertex colors, textures, alpha modes, animations, skins, morphs,
  cameras, and most extensions;
- clones scene nodes but does not create occurrence-level instancing;
- has no decoder integration or bounded/cancellable parse pipeline.

If the remote script fails, the next inline script immediately dereferences
`THREE`, so there is no 3D dependency fallback. The repository has no root
frontend `package.json`/lockfile. It does have a useful local-vendoring pattern
at `static/vendor/floating-ui/VERSIONS.md`: exact versions, source URLs,
SHA-256 values, and retained license text.

The implementation plan's binary audit is consistent with this risk: the
legacy GLB contains about 11.75 million vertices, 3.92 million triangles, 245
meshes, 245 materials, no occurrence reuse, and only five repeated shape
signatures. Compression alone cannot turn that artifact into an editor
payload. It must remain the `legacy-heavy` refusal/proxy fixture.

## Benchmark Fixture

Files:

- `tests/fixtures/facility_layout/rendering/renderer-benchmark-spec.json`
- `tests/fixtures/facility_layout/rendering/renderer-benchmark.html`
- `tools/benchmark_facility_layout_renderers.py`
- `tests/fixtures/facility_layout/rendering/renderer-benchmark-results.json`

The seeded generator creates 20 prototype dimensions/colors on an X/Z grid
with deterministic jitter and quarter-turn rotations. All renderers receive
byte-for-byte-equivalent generated placement values:

| Scenario | Placement SHA-256 |
| --- | --- |
| `edit-500` | `6cb4f5388c4aa725d3c5a861c4d333271b2b1fab6cff92b503106ee0822fc43a` |
| `navigate-5000` | `fae1e9964d5aedb257c2032f1a4c96be84fc9c7676a4dd38823b8d4d62dd0c3d` |

Workloads:

- `edit-500`: continuously pan, zoom, and drag one selected placement.
- `navigate-5000`: continuously pan and zoom all 5,000 placements.

Renderer implementations:

- SVG retains one `<rect>` per placement and updates the `viewBox` plus the
  selected transform.
- Canvas 2D clears and redraws the viewport; rectangles are batched into 21
  color paths to avoid 5,000 independent fills.
- Native WebGL 2 uses one instanced unit quad, per-instance
  position/size/rotation/color, one draw call, and one 16-byte selected-instance
  update per frame.

The WebGL path is an upper-bound renderer prototype. It is not Three.js and
does not include 20 `InstancedMesh` groups, material setup, `renderer.info`,
selection proxies, labels, or other full-scene costs.

## Named Environment

| Field | Value |
| --- | --- |
| Machine | Dell 15 DC15250 |
| CPU | 13th Gen Intel Core i7-1355U, 10 cores / 12 logical processors |
| RAM | 16,849,256,448 bytes (15.69 GiB) |
| GPU | Intel UHD Graphics, driver `32.0.101.7077` |
| WebGL backend | ANGLE, Intel UHD, Direct3D 11, shader model 5.0 |
| OS | Windows 11 Home `10.0.26200`, build 26200 |
| Browser | Microsoft Edge `150.0.4078.99`, headless |
| Physical display | 1920 x 1080 at 120 Hz |
| Benchmark viewport | 1440 x 960, device-pixel ratio 1 |
| Power | Windows Balanced; battery reported 100 percent |
| Browser capability | 12 hardware threads, 16 GiB device memory, visible page |

This was a non-isolated developer workstation. Background applications were
not quiesced. Headless Edge used hardware D3D11, not SwiftShader.

## Measurement Protocol

- Five runs per renderer/scenario, 30 measured runs total.
- Renderer order rotated each run.
- Two-second warm-up and ten-second measured window per run.
- One stable browser context; each run used a fresh page.
- Fixture served only from loopback HTTP.
- All non-local browser requests were blocked; zero were attempted.
- Every frame interval and JavaScript callback duration was retained.
- 24,327 frame-interval samples were recorded.
- No page errors, console errors, benchmark errors, context losses, or
  measured `PerformanceObserver` long tasks occurred.

This is intentionally bounded below the implementation plan's release
protocol of five 60-second runs after ten-second warm-ups. It meets neither the
duration requirement nor the full-fixture requirement and cannot certify a
release performance gate.

## Results

The plan's comparison thresholds are `<= 22 ms` p95 on standard hardware and
`<= 33 ms` p95 on minimum hardware.

| Renderer | Scenario | Samples | Effective fps | Frame median | Frame p95 | Callback p95 | Frames >22 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SVG | edit 500 | 5,999 | 119.89 | 8.3 ms | **8.7 ms** | 0.3 ms | 2 |
| SVG | navigate 5,000 | 2,563 | 51.17 | 16.8 ms | **32.89 ms** | 0.2 ms | 958 |
| Canvas 2D | edit 500 | 2,089 | 41.74 | 24.5 ms | **33.5 ms** | 0.7 ms | 1,082 |
| Canvas 2D | navigate 5,000 | 1,680 | 33.50 | 25.0 ms | **41.6 ms** | 15.9 ms | 1,405 |
| WebGL | edit 500 | 6,007 | 120.05 | 8.3 ms | **8.8 ms** | 0.3 ms | 2 |
| WebGL | navigate 5,000 | 5,989 | 119.70 | 8.3 ms | **8.7 ms** | 0.3 ms | 2 |

Per-run p95 ranges:

| Renderer | Edit 500 | Navigate 5,000 |
| --- | ---: | ---: |
| SVG | 8.6-8.9 ms | 25.1-33.3 ms |
| Canvas 2D | 33.3-41.5 ms | 33.5-49.9 ms |
| WebGL | 8.7-8.8 ms | 8.5-8.7 ms |

Build/first-paint-ready medians were:

| Renderer | Edit 500 | Navigate 5,000 |
| --- | ---: | ---: |
| SVG | 10.3 / 20.8 ms | 52.9 / 73.1 ms |
| Canvas 2D | 3.2 / 7.2 ms | 14.9 / 17.9 ms |
| WebGL | 35.1 / 38.1 ms | 38.5 / 43.0 ms |

Interpretation:

1. WebGL has substantial headroom at both counts on this hardware.
2. SVG is excellent for 500 placements but misses the standard-hardware gate
   at 5,000. Its low callback cost does not include browser style/paint work;
   frame cadence is the binding measurement.
3. Canvas 2D's full redraw misses the standard gate at both counts. Repeated
   frame stalls occurred even when its 500-placement callback was short,
   indicating that callback timing alone would give a false result.
4. Zero reported long tasks does not contradict the frame stalls because
   raster/compositor delay may occur outside the observed JavaScript task.
5. Heap deltas were GC-sensitive and are retained only as raw diagnostics; no
   memory-budget claim is made.

Raw result artifact:

- Size: 1,427,317 bytes
- SHA-256:
  `6C54130C382147FADF0DB4C0DEBE1379BD3443482E4D169E51C55F7B0131AD67`

## Renderer Recommendation

Use one primary WebGL implementation across plan and 3D tabs rather than
switching SVG/WebGL at an arbitrary placement count. For the plan view:

- use the shared Three.js `WebGLRenderer` with an orthographic camera;
- render repeated placement footprints/proxies through prototype/material
  instance groups;
- render only on state/camera changes and stop within 250 ms;
- cap device-pixel ratio;
- keep camera state separate from layout transforms;
- keep selection identity in explicit
  `placementId -> prototypeId -> instanceId` maps;
- read Three.js raycast `instanceId` and resolve it through the reverse map;
- use a separate lightweight overlay for the selected/ghost placement rather
  than rebuilding an instance group during drag;
- recompute instance bounds after transform changes;
- expose `renderer.info`, buffer estimates, and lifecycle counters.

Use SVG as degraded 2D mode when WebGL 2 is unavailable or lost. The fallback
must use the same layout/camera/selection model, but at 5,000 placements it
must spatially window visible objects, suppress nonessential labels/effects,
and use coarse tile summaries. The unvirtualized 5,000-node SVG result is not a
standard-hardware pass.

Canvas 2D remains reasonable for export, print, thumbnails, or a future
dirty-region/worker experiment. The measured full-viewport path is rejected as
the runtime primary and fallback.

## Instancing Assessment

The original placement benchmark in this section is based on synthetic quads.
The later real-rack proof in "P0 Integration Closure" supplies the separate
prototype/export and stable-instance evidence; neither artifact is placement
or safety authority.

The synthetic WebGL path used:

- 18,048 GPU buffer bytes and 1,000 triangles for 500 placements;
- 180,048 GPU buffer bytes and 10,000 triangles for 5,000 placements;
- one draw call in both cases.

Three.js `InstancedMesh` uses a 4 x 4 matrix per occurrence, or 64 bytes before
optional instance color/ID data. Five thousand matrices are about 320 KB, so
occurrence transforms are not the memory risk. Prototype geometry, material
splits, labels, selection, and detail LODs are the meaningful costs.

The target fixture has 20 prototypes. A straightforward upper bound is one
instance group per compatible prototype/material combination, not one group
per placement. The current 245-material legacy GLB cannot satisfy that model
without an asset-pipeline rewrite. Deduplicate before web export, store
occurrence transforms separately, and reject negative-scale instances.

Instance IDs are renderer-local and may change when a group compacts. Stable
layout identity must remain `placementId`; both forward and reverse maps are
rebuilt atomically with the instance buffers. Picking performance and
compaction correctness remain open tests.

## Three.js and Offline Packaging

As of 2026-07-28, official r184 maps to npm `three@0.184.0`. Registry and
`npm pack --dry-run` evidence:

| Package field | Value |
| --- | --- |
| License | MIT |
| Tarball | 12,661,342 bytes |
| Unpacked package | 36,963,785 bytes |
| SHA-1 | `5bca0a3851eea5345e4c205567b40dfa49b791b5` |
| npm integrity | `sha512-wtTRjG92pM5eUg/KuUnHsqSAlPM296brTOcLgMRqEeylYTh/CdtvKUvCyyCQTzFuStieWxvZb8mVTMvdPyUpxg==` |

The complete unminified package is not shipped. The pinned local file set is
974,511 raw bytes, excluding the 2,305-byte local `VERSIONS.md`:

| File | Bytes |
| --- | ---: |
| `build/three.core.min.js` | 384,222 |
| `build/three.module.min.js` | 364,998 |
| `examples/jsm/loaders/GLTFLoader.js` | 114,959 |
| `examples/jsm/utils/BufferGeometryUtils.js` | 35,539 |
| `examples/jsm/utils/SkeletonUtils.js` | 11,535 |
| `examples/jsm/controls/OrbitControls.js` | 40,504 |
| `examples/jsm/loaders/STLLoader.js` | 10,715 |
| `examples/jsm/renderers/CSS2DRenderer.js` | 7,384 |
| `LICENSE` and `package.json` | 4,655 |

The official loader imports the two matching-version utility modules; optional
Draco, Meshopt, and KTX2 decoders are injected separately and are not approved
by this spike.

Recommended packaging:

1. Vendor exact r184 files under a versioned local path.
2. Add a `VERSIONS.md` record with package version, tarball integrity, source
   URLs, every extracted-file SHA-256, and the retained MIT license.
3. Resolve both `three` and `three/addons/` to local URLs through one import
   map or a deterministic local bundle.
4. Add CI that rejects remote Three/addon URLs, missing licenses, hash drift,
   and mixed Three versions.
5. Serve versioned assets with immutable caching; never resolve a floating
   version at runtime.
6. Fetch size-limited, hash-verified GLB bytes with `AbortController`, then
   call `GLTFLoader.parseAsync`. A mount token still protects state, but parse
   cancellation/worker termination must be designed explicitly.
7. Exercise network-denied startup, valid local GLB, corrupt/truncated GLB,
   unsupported extension, cancellation, and 20 remounts before integration.

### Migration Risk

r128 to r184 is not a drop-in script swap:

- r184 is an ES-module architecture and its `WebGLRenderer` requires WebGL 2;
- the current page expects a global `THREE` during inline script evaluation;
- color-management/output APIs and rendered appearance changed across the
  intervening releases;
- the current custom loader forces non-source metalness/roughness and ignores
  textures, while the official loader preserves broader glTF semantics;
- official `GLTFLoader` image resources add explicit disposal obligations;
- current custom controls, CSS labels, STL paths, highlights, material clones,
  clipping, screenshots, and teardown all require regression coverage.

Do not load r128 and r184 together on the production page. If immediate offline
operation is required before the migration is ready, self-host exact r128 as a
short-lived compatibility step with the same license/hash discipline, while
the new renderer remains unintegrated. The target remains one r184 engine and
one shared renderer.

## Fallback and Failure Policy

| Failure | Required behavior |
| --- | --- |
| WebGL 2 unavailable at creation | Mount virtualized SVG plan view; do not attempt 3D |
| WebGL context lost | Cancel the active gesture, preserve authoritative state, mount SVG, resume supported 2D editing, and offer explicit retry |
| Local Three module missing/hash mismatch | Fail closed to SVG; report dependency diagnostic |
| GLB over automatic-load limit | Load footprints/proxies only; require explicit detail action |
| Corrupt/unsupported GLB | Keep plan operational, quarantine artifact, show stable error code |
| Offline | All core modules and proxy/footprint assets remain local; no CDN retry |
| Legacy 327 MB GLB | Refuse automatic load and enter proxy mode |
| Instance mapping mismatch | Disable picking/mutation for the affected group and rebuild atomically |

The fallback changes only presentation capability. It must not alter layout
coordinates, revisions, selection IDs, dirty state, or save semantics.

## P0 Integration Closure

### Local dependency proof

The r184 proof is isolated from the current r128 application path:

```text
static/vendor/three/0.184.0/
    build/three.core.min.js
    build/three.module.min.js
    examples/jsm/controls/OrbitControls.js
    examples/jsm/loaders/GLTFLoader.js
    examples/jsm/loaders/STLLoader.js
    examples/jsm/renderers/CSS2DRenderer.js
    examples/jsm/utils/BufferGeometryUtils.js
    examples/jsm/utils/SkeletonUtils.js
    LICENSE
    package.json
    VERSIONS.md
```

The complete directory is 976,816 bytes including `VERSIONS.md`. The offline
smoke blocks every non-loopback request and records:

```text
12/12 checks pass
Three revision: 184
Official GLTFLoader: imported
Valid GLB: parsed
Corrupt GLB: rejected
WebGL 2: rendered
Nonblank pixels: confirmed
Page/console errors: 0/0
External requests: 0
```

The offline smoke evidence in
`tests/fixtures/facility_layout/rendering/three-offline-smoke-result.json`
binds only the vendor entries loaded by its page and script. Its `source`
object records `manifestEntriesSha256` and `manifestEntryPaths`. The paths
are relative to `static/vendor/three/0.184.0`:

- `build/three.core.min.js`
- `build/three.module.min.js`
- `examples/jsm/loaders/GLTFLoader.js`
- `examples/jsm/utils/BufferGeometryUtils.js`
- `examples/jsm/utils/SkeletonUtils.js`

The page imports Three and GLTFLoader; their transitive imports load core
and the two utilities. `tools/facility_three_manifest.py` is shared by the
producer and evidence test. It hashes compact ASCII JSON of
`[path, byte_count, sha256]` lists, sorted by path, with no trailing newline,
extracted from the `VERSIONS.md` File/Bytes/SHA-256 table. Missing, malformed,
or duplicate required entries fail. Unused rows, prose, row order, and line
endings do not affect this binding. The existing `fixtureSha256`,
`moduleSha256`, and `loaderSha256` bindings remain unchanged.

Evidence carrying only the legacy whole-file `manifestSha256` is rejected.
Regenerate it with `python tools/verify_facility_three_offline.py`; do not
edit evidence hashes by hand. Other renderer and release evidence bindings
retain their existing scope.

No compression decoder is adopted in P0. The two private machine GLBs are
under 1 MB and the rack prototype is 13.5 MB. Meshopt, Draco, or KTX2 requires
a separate representative-asset measurement and dependency decision.

### Real repeated-rack proof

The standalone SolidWorks extractor exported the saved `8x16` configuration
of `Pallet Racking.SLDASM`:

| Field | Value |
| --- | --- |
| Source CAD SHA-256 | `81575b23be1559cb6a6ca6e655db83b622d2291d478344aaeb866190eb0334b7` |
| Prototype GLB | 13,493,420 bytes |
| Prototype GLB SHA-256 | `185e9914e28106b14054a8467b941eba1cf31c85593cd566ab40d608cea77c0c` |
| Prototype meshes/materials | 10 / 10 |
| Extracted matching occurrences | 6 |
| Naive independent mesh draws | 60 |
| Instanced mesh draws | 10 |
| Draw-call reduction | 6x |
| Raycast mapping | `instanceId` resolved to stable `placementId` |
| Changed pixels | 63,461 |
| Page/console errors | 0 / 0 |
| External requests | 0 |

The screenshot is
`tests/fixtures/facility_layout/rendering/rack-instancing-smoke.png`. The
fixture explicitly classifies the legacy occurrence transforms as inferred
render evidence only. It does not make the rack placement-ready or
planning-ready.

Executable artifacts:

- `tests/fixtures/facility_layout/rendering/repeated-rack-instance-spike.json`
- `tests/fixtures/facility_layout/rendering/rack-instancing-smoke.html`
- `tests/fixtures/facility_layout/rendering/rack-instancing-smoke.js`
- `tests/fixtures/facility_layout/rendering/rack-instancing-smoke-result.json`
- `tools/verify_facility_rack_instancing.py`

## Remaining Risks and Gates

| Risk | Severity | Required gate |
| --- | --- | --- |
| Native one-draw result does not represent Three.js scene overhead | High | Repeat with the actual Three adapter and 20 prototype groups |
| Benchmark omits zones, routes, clearances, labels, and picking | High | Full `warehouse-500` and `warehouse-5000` fixtures |
| Headless standard laptop only | High | Headed standard and named minimum hardware, full 5 x 60-second protocol |
| r128-to-r184 visual/API regression | High | Viewer compatibility matrix and screenshot/pixel baselines |
| WebGL context recovery not measured | High | Forced context loss/restore plus SVG continuity |
| Instance compaction can corrupt identity | Medium | Stable-ID property tests and instance-aware picking p95 |
| Only the 8x16 rack configuration has real prototype evidence | Medium | Normalize and publish each required configuration in P2 |
| SVG 5,000 fallback misses standard budget | Medium | Spatial virtualization and degraded-mode benchmark |
| Compression may add decoder/worker risk | Medium | Separate Meshopt/Draco comparison before adoption |
| Pinned files can drift after review | Medium | Keep manifest/license/hash tests in CI |

## Next Implementation Decision

The P0 renderer choice, local dependency, and prototype/instance spikes are
closed. They authorize P1 transaction-kernel work, not immediate editor
wiring. Production renderer integration belongs to the later renderer phase
and still requires:

1. one shared Three.js adapter with forward/reverse instance maps;
2. full plan layers, demand rendering, disposal, and SVG degraded mode;
3. network-denied loading and hash verification in the application shell;
4. full `warehouse-500` and `warehouse-5000` measurements;
5. the five 60-second protocol on standard and named minimum hardware;
6. context-loss, cancellation, remount, and visual-regression gates.

## Commands and Results

Architecture and requirement audit:

```powershell
rg -n -i "three(\.min)?\.js|THREE\.|GLTFLoader|webgl|requestanimationframe|cdn" static/index.html
rg -n -i -C 4 "P0|renderer|Three|offline|500|5,000|instanc|fallback|dependenc" docs/industrial-layout-platform-implementation-plan.md
```

Result: remote r128 plus inline loaders confirmed; P0 renderer/dependency and
runtime gates located.

Package metadata and closure:

```powershell
npm view three@0.184.0 version license dist.tarball dist.integrity dist.unpackedSize --json
npm pack three@0.184.0 --dry-run --json --offline
```

Result: `0.184.0`, MIT, 12,661,342-byte tarball, 36,963,785-byte unpacked
package, and a 974,511-byte pinned module/license set excluding the local
manifest. No package was installed and no tarball was left in the repository.

Smoke:

```powershell
python -B tools\benchmark_facility_layout_renderers.py --smoke --output "$env:TEMP\facility-layout-renderer-smoke.json"
```

Result: 6/6 renderer/scenario samples, zero errors, identical per-scenario
fixture hashes, zero external requests, hardware D3D11 WebGL.

Measured spike:

```powershell
python -B tools\benchmark_facility_layout_renderers.py --runs 5 --warmup-seconds 2 --duration-seconds 10 --output tests\fixtures\facility_layout\rendering\renderer-benchmark-results.json
```

Result: 30/30 runs, zero errors, 375.595 seconds elapsed, 24,327 retained frame
intervals. Aggregate results are in the table above and every raw sample is in
the JSON artifact.

Official primary references consulted:

- Three.js r184 release:
  <https://github.com/mrdoob/three.js/releases/tag/r184>
- Three.js r184 package metadata and MIT license:
  <https://github.com/mrdoob/three.js/blob/r184/package.json>,
  <https://github.com/mrdoob/three.js/blob/r184/LICENSE>
- Installation and same-version addon guidance:
  <https://threejs.org/manual/en/installation.html>
- Official GLTFLoader:
  <https://threejs.org/docs/pages/GLTFLoader.html>
- InstancedMesh and instance-aware raycast result:
  <https://threejs.org/docs/pages/InstancedMesh.html>,
  <https://threejs.org/docs/pages/Raycaster.html>
- WebGLRenderer lifecycle/info and disposal:
  <https://threejs.org/docs/pages/WebGLRenderer.html>,
  <https://threejs.org/manual/en/how-to-dispose-of-objects.html>
