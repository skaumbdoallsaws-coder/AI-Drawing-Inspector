# Motion Package Contract — v1

Status: **contract locked 2026-07-03** (review fixes incorporated). No implementation yet.
Schema: [`motion_package.schema.json`](motion_package.schema.json) (shape); semantic rules live in the
validator canaries (§8) — the schema checks structure, the canaries check physics.

## Purpose

Export structured motion data from a SolidWorks motion study (4-cylinder crank / rod / piston
assembly) so InspectorPro can replay the mechanism in the 3D viewport, retime it to any RPM, and
let Sage combine motion playback with FAI explanations and part highlighting.

**Not** a video export. **Not** LLM kinematics.

## Architecture (locked)

- SolidWorks validates the motion (mates + motor solve it).
- A dumb VBA macro samples transforms from the solved study.
- Python builds and validates the package (all contract logic lives here, testable).
- The frontend replays deterministic transforms.
- Sage only explains and triggers actions.
- The LLM never calculates motion, RPM, clearances, or loads.

## Core decisions

1. **Transforms are position + unit quaternion** (no scale, no matrices), sampled per component.
2. **Coordinate space is the GLB asset root** — the local frame of the exported GLB's scene root,
   *not* Three.js scene world. The viewer may recenter/reorient the loaded assembly group; the
   motion rig lives **under** that group, so viewer transforms carry the rig along. (This is the
   facility-layout offset lesson, applied structurally.)
3. **Samples are indexed by crank angle** (0–360°, fixed step, duplicated endpoint). RPM is purely
   a playback rate: `θ += rpm × 6 × dt` deg/sec. Retiming never touches data.
4. **The package is pinned to one exact GLB** by sha256 + byteLength. A package never animates an
   asset it wasn't built and validated against.
5. **Playback applies delta poses**: `delta(θ) = sample(θ) × sample(0)⁻¹`, applied to the GLB rest
   arrangement. θ = 0 reproduces the rest pose *by construction*, and the mechanism works whether
   the exporter preserved node transforms or baked them into vertices.
6. **The agent gets a code-generated summary and five verbs.** It never sees transform arrays.
7. **Binding is resolved and validated at build time.** The frontend refuses to play on any
   unresolved moving component or asset-pin mismatch — no partial playback, no fuzzy matching at
   runtime.

### Review fixes incorporated (2026-07-03)

| # | Fix | Where it landed |
|---|-----|-----------------|
| 1 | Pin package to exact GLB (`glbAsset` sha256/byteLength) | §3 `glbAsset`, canary V1, bind step B2 |
| 2 | GLB-root coordinates; rig under loaded assembly group | Core decision 2, §4, §5 |
| 3 | One SW component → multiple GLB nodes (`glbNodes[]`) | §3 components, §5 bind step B3 |
| 4 | Stable SolidWorks instance paths as component identity | §3 components (`id` = instance path), §7 macro |
| 5 | GLB must be exported at the sample-0 pose; validator enforces | §7 workflow rule W1, canaries V8–V9 |
| 6 | Do not assume time ≡ angle; verify crank rotates exactly 360° | Canaries V5–V6 (uniformity + closure) |

---

## 3. Package contract

One JSON file per motion, served next to the GLB (proposed: `generated/motion/<assembly>/<motion>.json`).
Size estimate for this assembly: ~13 moving leaf parts × 181 samples × 7 floats ≈ 150–300 KB.
Plain JSON; no binary sidecar in v1.

```json
{
  "contractVersion": 1,
  "motionId": "engine4cyl_crank_cycle",
  "name": "Crank-slider cycle — 4-cylinder engine",
  "description": "One crankshaft revolution driving four connecting rods and pistons.",

  "source": {
    "system": "solidworks_motion",
    "assemblyFile": "Engine.SLDASM",
    "configuration": "Default",
    "motionStudyName": "Motion Study 1",
    "studyType": "basic_motion",
    "exportedAt": "2026-07-03T14:00:00Z",
    "exporterVersion": "motion_export_macro/1"
  },

  "glbAsset": {
    "fileName": "engine.glb",
    "sha256": "3f8a…64 hex chars…c21b",
    "byteLength": 4183112
  },

  "frame": {
    "space": "glb_asset_root",
    "convention": "y_up_right_handed",
    "units": { "length": "m", "angle": "deg" },
    "sourceConvention": "solidworks_assembly",
    "sourceToPackageMatrix": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
  },

  "driver": {
    "kind": "rotary",
    "componentId": "crankshaft-1",
    "axis": { "origin": [0.0, 0.0, 0.0], "direction": [0, 0, 1] },
    "cycleDegrees": 360,
    "defaultRpm": 90,
    "rpmRange": [10, 600]
  },

  "components": {
    "moving": [
      {
        "id": "crankshaft-1",
        "displayName": "Crankshaft",
        "swInstancePath": "crankshaft-1",
        "sourceFile": "crankshaft.sldprt",
        "partNumber": "CRK-100",
        "glbNodes": ["crankshaft-1"]
      },
      {
        "id": "PistonAsm-1/connrod-1",
        "displayName": "Connecting Rod 1",
        "swInstancePath": "PistonAsm-1/connrod-1",
        "sourceFile": "connrod.sldprt",
        "partNumber": "ROD-100",
        "glbNodes": ["connrod-1", "connrod-cap-1", "rod-bolts-1"]
      }
    ],
    "fixed": [
      {
        "id": "block-1",
        "displayName": "Engine Block",
        "swInstancePath": "block-1",
        "sourceFile": "block.sldprt",
        "partNumber": "BLK-100",
        "glbNodes": ["block-1"]
      }
    ]
  },

  "sampling": {
    "parameter": "crank_angle_deg",
    "startDeg": 0,
    "endDeg": 360,
    "stepDeg": 2,
    "count": 181,
    "endpointDuplicatesStart": true
  },

  "samples": {
    "crankshaft-1":            { "p": [[0,0,0], "… 181 …"], "q": [[0,0,0,1], "… 181 …"] },
    "PistonAsm-1/connrod-1":   { "p": ["…"], "q": ["…"] }
  },

  "events": [
    { "angleDeg": 0,   "id": "tdc_cyl1", "label": "Cylinder 1 TDC", "componentIds": ["PistonAsm-1/piston-1"] },
    { "angleDeg": 180, "id": "bdc_cyl1", "label": "Cylinder 1 BDC", "componentIds": ["PistonAsm-1/piston-1"] }
  ],

  "semanticGroups": [
    {
      "id": "crank_slider_cyl1",
      "label": "Cylinder 1 crank-slider",
      "componentIds": ["crankshaft-1", "PistonAsm-1/connrod-1", "PistonAsm-1/piston-1", "PistonAsm-1/pistonpin-1"],
      "function": "Converts crank rotation into piston 1 reciprocation through the connecting rod and piston pin."
    },
    {
      "id": "reciprocating_group",
      "label": "Reciprocating components",
      "componentIds": ["PistonAsm-1/piston-1", "PistonAsm-2/piston-2", "PistonAsm-3/piston-3", "PistonAsm-4/piston-4"],
      "function": "All pistons; pure reciprocation along the cylinder axes."
    }
  ],

  "derived": {
    "strokeM": { "PistonAsm-1/piston-1": 0.086 },
    "pistonTravelAxis": [0, 1, 0]
  }
}
```

Field rules:

- **`glbAsset` (fix 1).** sha256 + byteLength of the *exact* GLB the package was built and
  validated against. The builder computes it; the player verifies it at bind time (§5.B2). A
  package is meaningless against any other asset — including a re-export of the same assembly.
- **Component identity (fix 4).** `id` **is** the root-relative SolidWorks instance path
  (`Name2` chain from the assembly root, e.g. `PistonAsm-1/connrod-1`) — unique by construction in
  SolidWorks, stable across sessions, and the key used everywhere: `samples`, `driver.componentId`,
  `events[].componentIds`, `semanticGroups[].componentIds`, `derived.strokeM`. `displayName` and
  `sourceFile` are carried for humans and for GLB-name matching; `partNumber` joins to
  `assyPartMeshMap` and FAI characteristics.
- **`glbNodes[]` (fix 3).** Always an array, minimum one entry. A SolidWorks component or
  subassembly may export as several GLB nodes/meshes (caps, bolts, split bodies). All listed nodes
  move rigidly with the component's sampled pose. No node may appear under two components.
- **Leaf-part sampling.** The macro samples *leaf part occurrences* recursively, not top-level
  components — a rod and its piston sit in the same subassembly but move differently, so the
  subassembly is not a rigid unit. Rigidly-joined leaves (piston + pin) simply produce
  near-identical sample tracks; harmless, and moving/fixed classification stays data-driven.
- **`cycleDegrees: 360`** is correct for pure crank-slider kinematics (geometry repeats every
  revolution). Valve/firing events need 720° and become a *separate* package in v2.
- **`rpmRange` is a display clamp, not engineering data.** Real idle (~800 RPM) is unwatchable;
  `defaultRpm: 90` exists so the demo reads visually. The agent contract requires presenting RPM
  as a visualization rate, never an operating-speed claim.
- **`events`** are computed by the builder from piston extrema along `pistonTravelAxis` — never
  assumed. (A flat-plane 4-cyl crank pairs pistons 1&4 and 2&3; the data shows that on its own.)
- **`semanticGroups[].function`** strings are authored once in the builder's config section (same
  pattern as the facility semantic JSON) — they bridge an FAI characteristic on the pin bore to
  "the group that contains the piston pin."

## 4. Transform format and coordinate space

**Position + unit quaternion, in GLB-asset-root space, GLB convention (right-handed, +Y up, meters).**

- **TRS over 4×4 matrices:** quaternions slerp cleanly; matrices interpolate badly and carry 16
  numbers to say 7. Scale is forbidden — the validator rejects any sampled scale ≠ 1 (also catches
  a corrupted export early).
- **GLB asset root, not scene world (fix 2):** the viewer recenters/reorients the loaded assembly
  group. Package coordinates are relative to the GLB's own scene root, and the motion rig is a
  child of that root — whatever the viewer does to the group (recenter, rotate, scale) is applied
  *above* the rig and cannot desynchronize it.
- **One frame, baked at build time.** The SolidWorks→GLB conversion is applied by the builder and
  recorded in `frame.sourceToPackageMatrix` for audit only. No parallel raw/render arrays — one
  authoritative frame, plus canaries that make a frame mismatch a loud failure (V8–V9).
- **Quaternion hemisphere continuity is enforced at build time** (flip q when
  dot(qₖ, qₖ₊₁) < 0) so the player slerps naively.
- **Delta-pose semantics.** The sample track defines each component's pose over the cycle; the
  player applies `delta(θ) = sample(θ) × sample(0)⁻¹` to the component's GLB rest arrangement.
  This is exact at θ = 0 regardless of how the exporter flattened hierarchy or baked transforms,
  and it preserves intra-component offsets for multi-node components.

## 5. Binding and playback contract

**Bind (once per scene attach, mirrors the `assyPartMeshMap` lifecycle):**

- **B1 — Resolve.** For each component, resolve every entry in `glbNodes` to a node in the loaded
  GLB (exact name; the *builder* already verified these names exist in the pinned asset, so bind
  does lookup, not matching).
- **B2 — Verify the asset pin (fix 1).** Compare the loaded GLB against `glbAsset`: byteLength
  always; sha256 whenever the loader path retains the ArrayBuffer (hash via
  `crypto.subtle.digest`). Mismatch → refuse to bind, name the expected vs actual asset.
- **B3 — Rig (fixes 2 + 3).** Create a `motion-rig` group as a **direct child of the GLB scene
  root** (identity local transform). For each moving component, create a per-component group at
  the component's sample-0 pose and `attach()` all its resolved nodes into it — `attach`
  preserves each node's current pose, so intra-component offsets (cap, bolts) survive. Record
  every node's original parent + local transform for restore.
- **B4 — Refuse partial playback.** Any unresolved moving node, duplicate claim, or pin mismatch →
  no playback, surface the specific list. A crank turning without its rods is worse than an error.
- **B5 — Restore.** `stop()` re-attaches nodes to original parents with original transforms and
  removes the rig. Leave the scene exactly as found (same discipline as the facility overlay
  dispose path).

**Playback:**

- Per render frame: `θ = (θ + rpm × 6 × dt) mod 360`; index `θ / stepDeg`; lerp p, slerp q between
  adjacent samples; set each per-component rig group's local pose to the interpolated sample pose.
  The duplicated 360° endpoint makes loop wrap seamless with no special case.
- RPM changes take effect next frame, clamped to `driver.rpmRange`. No resampling, ever.

**Player surface (frontend module):**

```
motionPlayer.load(pkg)                    motionPlayer.setRpm(rpm)     // clamped to rpmRange
motionPlayer.bind(glbRoot) -> {ok, problems[]}
motionPlayer.play({rpm, loop})            motionPlayer.seek(angleDeg)
motionPlayer.pause()                      motionPlayer.stop()          // restores rest pose
motionPlayer.state() -> {playing, rpm, angleDeg, motionId}
```

**Agent command route** — five new action types on the *existing* declarative action channel
(the `{"workspace", "actions": [...]}` registry that already carries highlight/focus/explode;
server.py ~16872). No new transport.

```json
{ "type": "play_motion",    "motion_id": "engine4cyl_crank_cycle", "rpm": 60, "loop": true }
{ "type": "pause_motion" }
{ "type": "set_motion_rpm", "rpm": 30 }
{ "type": "seek_motion",    "crank_angle_deg": 180 }
{ "type": "stop_motion" }
```

Demo utterances compose from existing + new actions:

- "Show the piston motion" → `play_motion`
- "Slow it down" → `set_motion_rpm` (current rpm from playback state, halved, clamped)
- "Show why this pin bore matters" → FAI reasoning (existing) + `HIGHLIGHT_PARTS` on the pin's
  semantic group + `play_motion` at low rpm
- "Highlight affected parts and play motion" → `HIGHLIGHT_PARTS` + `play_motion` in one ordered
  action list

## 6. Agent contract

Sage receives a **summary generated by code from the package** — never hand-written, never the
arrays — through the existing mode-contract channel: a `motion` block inside `mode_state` for the
3dmodel/assembly modes, rendered by `_render_mode_contract_section` like the facility route
summary.

```json
{
  "available_motions": [{
    "motion_id": "engine4cyl_crank_cycle",
    "name": "Crank-slider cycle — 4-cylinder engine",
    "driver": "crankshaft-1, rotary, 360° cycle",
    "default_rpm": 90,
    "rpm_range": [10, 600],
    "moving_component_count": 13,
    "groups": [{
      "id": "crank_slider_cyl1",
      "label": "Cylinder 1 crank-slider",
      "component_ids": ["crankshaft-1", "PistonAsm-1/connrod-1", "PistonAsm-1/piston-1", "PistonAsm-1/pistonpin-1"],
      "part_numbers": ["CRK-100", "ROD-100", "PST-100", "PIN-100"],
      "function": "Converts crank rotation into piston 1 reciprocation…"
    }],
    "events": [{ "id": "tdc_cyl1", "angle_deg": 0 }],
    "stroke_m": 0.086
  }],
  "playback": { "active_motion_id": null, "playing": false, "rpm": null, "angle_deg": null }
}
```

`MODE_CONTRACTS` addendum lines for motion-capable modes (established style):

- Cite `stroke_m`, `default_rpm`, `rpm_range`, event angles, and group functions **verbatim** from
  the summary.
- Allowed verbs: `play_motion`, `pause_motion`, `set_motion_rpm`, `seek_motion`, `stop_motion`;
  compose freely with `HIGHLIGHT_PARTS`.
- **Do NOT invent** operating RPMs (displayed RPM is a visualization rate), clearances, loads,
  forces, velocities, accelerations, or firing order — none of that exists in the package. If
  asked, say it is not computed yet.
- If `available_motions` is empty for the current assembly: say so; do not offer to animate.

`groups[].part_numbers` is the deterministic join from FAI: characteristic → part number →
containing group(s) → highlight + play. No inference.

## 7. Export path from SolidWorks

**VBA macro for sampling + Python builder for everything else.** A C# add-in buys robustness we
don't need for one assembly and costs a build/install toolchain; revisit if motion export becomes
per-customer (v2+).

**Workflow rules (fix 5):**

- **W1 — Rest-pose discipline.** Set the motion study to t = 0 (assembly in the sample-0 state)
  **before** exporting the GLB, then run the macro against the same state. The GLB and the package
  must depict the same instant. Canaries V8–V9 enforce this; the sha256 pin freezes the validated
  pairing.
- **W2 — Same configuration.** GLB export and macro run against the same assembly configuration
  named in `source.configuration`.

**Macro (`ExportMotionRaw.swp`, ~150 lines), deliberately dumb:**

1. Constants at top: `STEP_DEG = 2`, `CYCLE_SECONDS` (set once to match the study motor: a 60 RPM
   motor → 1.0 s cycle).
2. `MotionStudyManager` → `GetMotionStudy("Motion Study 1")` → `Activate` → ensure solved
   (`Calculate` for Motion Analysis; Basic Motion solves on activation).
3. For each sample k in 0..180: `SetTime(k/180 × CYCLE_SECONDS)`; walk the component tree
   recursively to **leaf part occurrences**; read each `Component2.Transform2.ArrayData`
   (16 doubles, SolidWorks assembly frame — smoke-test during step 2 of sequencing that nested
   occurrences report root-relative transforms).
4. Per occurrence, also dump: root-relative instance path (`Name2` chain — fix 4), referenced
   document filename, configuration, suppression state.
5. Write `motion_raw.json` (SolidWorks frame, raw matrices). Reset the study to t = 0. No frame
   math, no classification, no naming decisions in the macro — those belong to the builder.

Sampling the study clock at fixed times equals fixed crank angles **only because the motor is
constant-speed — and the builder verifies rather than assumes this (fix 6, canaries V5–V6).**
Replaying the solved study via `SetTime` is also strictly more reliable than driving a mate angle,
which re-solves positions outside the study and can diverge from it.

**Builder (`tools/motion_package_build.py`):** raw → contract.

- Frame conversion to GLB convention; matrix→TRS decompose; reject scale ≠ 1; hemisphere fix.
- Moving/fixed classification by displacement threshold (> 0.1 mm anywhere in cycle = moving).
- **GLB node resolution against the pinned asset** (pygltflib): match instance path leaf → exact
  node name → normalized (lowercase, strip `-n` instance suffix, strip non-alphanumerics) →
  source filename stem. A component may resolve to **multiple** nodes (fix 3). Unresolved moving
  component or doubly-claimed node = **hard build failure**. Matching happens here, once, offline
  — never fuzzily at runtime.
- Compute `glbAsset` sha256/byteLength (fix 1); compute events from piston extrema; merge
  hand-authored `semanticGroups` config; emit package + agent summary.
- Run the validator (§8) as the last build step; a red canary fails the build.

## 8. Validation canaries

`tools/motion_validate.py` + `tests/test_motion_package.py` (same standalone-runner pattern as
`test_mode_contract.py`); run automatically at build time.

| # | Canary | Threshold |
|---|--------|-----------|
| V1 | **Asset pin**: `glbAsset.sha256`/`byteLength` match the GLB on disk | exact |
| V2 | **Shape**: every sampled id has exactly `sampling.count` entries; quaternions unit-norm; no scale | ‖q‖ − 1 < 1e-6 |
| V3 | **Loop closure**: sample[last] ≈ sample[0], every component | 0.1 mm / 0.1° |
| V4 | **Fixed stay fixed**: max excursion of fixed components | < 0.01 mm / 0.01° |
| V5 | **Crank closes exactly one revolution** (fix 6): accumulated rotation about `driver.axis` = 360°; axis direction constant; origin stays on axis | ± 0.5° |
| V6 | **Angle uniformity** (fix 6): per-step crank rotation = `stepDeg` — catches a non-constant motor, i.e. time ≢ angle | ± 0.1° per step |
| V7 | **Continuity**: per-step displacement < 3× that component's median step; all post-fix quaternion dots positive | — |
| V8 | **Kinematic replay against the pinned GLB** (fixes 2 + 5): apply `delta(θ)` at test angles (90/180/270°) to GLB rest data in Python; piston nodes translate along `pistonTravelAxis` with total travel = `strokeM`; crank nodes rotate about `driver.axis`; off-axis piston drift < 0.01 mm; piston orientation change < 0.5° | as listed |
| V9 | **Rest pose is the 0° state** (fix 5): each TDC/BDC-tagged piston's rest position sits at the extremum of its sampled travel (catches a GLB exported at the wrong crank angle); where the exporter preserved node transforms, also compare sample-0 poses to GLB node transforms directly | 1 mm / 0.5° |
| V10 | **Binding completeness**: every `glbNodes` entry exists in the pinned GLB; no node claimed twice; every `componentIds` reference in events/groups/driver resolves to a declared component | exact |
| V11 | **Summary consistency**: regenerate the agent summary from the package; assert equality with the shipped one | exact |

Frontend runtime guards (bind time, §5): pin verification, resolution lookup, refuse-partial. These
re-check V1/V10 in the browser; the physics canaries run offline only.

## 9. Scope

**V1 (demo-sufficient):** one package (crank cycle, 360°, 2° steps); TRS samples; player with five
verbs + RPM retiming; TDC/BDC events; semantic groups; agent summary in the mode contract; five
action types composing with `HIGHLIGHT_PARTS`; validator wired into the build.

**V2 (explicitly out):** multiple motions + manifest; 720° packages with valve/firing events;
Motion Analysis force/load channels; computed clearance checks (deterministic geometry code, still
never the LLM); motion diff across revisions; camera choreography during playback.

## 10. Implementation sequence

Each step produces a checkable artifact before the next starts.

1. ~~Contract doc + JSON schema~~ (this document).
2. Macro on the Engine assembly → `motion_raw.json`. Smoke-test: nested occurrences report
   root-relative transforms; instance paths unique.
3. GLB export of the same assembly at the t = 0 state (workflow rule W1) through the existing
   pipeline.
4. Builder + validator + tests, offline against the raw dump + GLB. All canaries green before any
   frontend work.
5. Frontend player + hidden dev control strip (play/pause/RPM slider/scrub). Verify visually
   against SolidWorks side by side.
6. Mode-contract wiring (summary block + `MODE_CONTRACTS` addendum) and the five action types in
   the action registry.
7. Demo rehearsal: pin-bore FAI → explanation → highlight + dim → motion at ~40 RPM.
