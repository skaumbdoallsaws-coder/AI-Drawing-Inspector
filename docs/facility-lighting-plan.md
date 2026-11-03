# Facility 3D lights: glowing fixtures, an evening scene and blinking beacons (L0-L6)

Status: written 2026-10-30; all five decisions accepted as recommended the same day (user: "yes"). Build after
the speedrun demo (2026-11-01) and YC W27 (2026-11-02). Building in the test copy since 2026-10-31: L0 to L8
and CC done (see "L0 results" to "L4 results", "L7 results", "L5 results", "L6 results", "L8 results" and "CC
results"). CC's live Sage turn passed in the desktop app on 2026-11-01. The same day the user kept L6, the glow halo,
as built (off by default), and said go on a soft beam edge for CC's estimate (both relayed by the main session).
Added 2026-10-31 (the user's "go", relayed by the main session): L7 lights per area, L8 outdoor night lighting and a
coverage check (CC); see "L7, L8 and CC" below.

## Goal

The user, 2026-10-30, after asking whether we can add "animated object of light in the factory": "i am interested in
light only leave the moving forklift". So the goal is light only: lamps that look switched on, a darker scene in which
that reads, and lights that blink or strobe (beacons, stack lights). Moving objects (forklift playback) stay as they
are and are out of scope.

## What the 3D view does today (checked in the real repo, 2026-10-30)

- Two light sources only: one `HemisphereLight` (sky fill) and one `DirectionalLight` (sun), sized by the scene
  preset (`static/facility_library/scenes.json`: ambient, directional, exposure, environment, shadows). No point or
  spot lights.
- Glow (`emissive`) is used only for selection highlight. The neutral asset material sets emissive to black, so a
  glow authored inside a GLB does not show either.
- Unlit (`KHR_materials_unlit`) is honoured only for printed wall artwork (`facilityArtwork`).
- Rendering is on demand (`needsRender`): a frame is drawn only when something changes. Nothing redraws on a timer
  except the motion and activity playback clocks.
- No post-processing: three r184 is vendored with `examples/jsm` controls, loaders, renderers and utils, but not
  `postprocessing` (no bloom).
- Component finishes (`set_component_materials`) take `{key, color, roughness, metalness}` or `{key, appearanceId}`.
  An appearance from the library is therefore the natural carrier for a glow, with no new operation shape.
- Factory 02 (scene `machine-shop`): 16 placements of `asset-factory02-high-bay-light-row-294m` = 800 round LED
  high-bay lights, each with its own `lens` material (plus `housing`, `rod`). Also 17 exit doors, 2 exit sign posts,
  3 assembly-point signs, 12 ABB IRB 6650 robots, 5 forklifts, 4 forklift chargers.

## Design

Real light sources do not scale: 800 lamps as `PointLight`s would stop the view. The plan fakes what the eye reads
as "the lights are on" and keeps real lights out:

1. **Glow finishes.** New appearances in the library, group "Lights": cool-white LED, warm-white, exit green,
   beacon amber, alarm red, signal blue, stack red / amber / green. Each carries
   `emission: {color, intensity, pattern, periodSeconds}`. The adapter applies them as emissive (and not tone-mapped
   down), so a lens looks lit in any scene. Applied with the existing `set_component_materials` (`appearanceId`) by
   hand, by script or by Sage. GLB-authored emissive is kept instead of zeroed.
2. **Lights switch + Evening scene.** A scene-level "Lights on/off" saved with the layout's scene (off = glow parts
   drawn as plain frosted plastic). A new scene preset "Evening / night shift": sun and sky turned far down, dark
   background, low environment, so the glow carries the picture.
3. **Light pools on the floor.** Under each light row, one soft additive "pool" strip (a radial-gradient texture
   repeated along the row, one mesh per row = 16 draw calls for Factory 02), shown only when lights are on and the
   scene is dark enough to need it. Cheap, and reads like light falling on the floor.
4. **Blinking.** `pattern`: steady, blink, strobe (short flash), rotate (sweeping brightness for a rotating beacon).
   While any blinking glow is in view, the view redraws on a light timer instead of on demand. It stops when none is
   in view, when the window is hidden, or when the user prefers reduced motion (the adapter already tracks
   `prefersReducedMotion`; then patterns show steady).
5. **Light-fitting models.** Authored, light in triangles: three-lamp stack light (andon) on a short pole for robot
   cells and machines, rotating amber beacon for forklifts and dock doors, glowing exit sign face. Placed like any
   other asset; their lamp parts carry the glow finishes.
6. **Bloom halo (optional, last).** Vendor three r184 `EffectComposer`, `RenderPass`, `UnrealBloomPass`, `OutputPass`
   (MIT, same package). A view setting, on only in the Evening scene, off by default. It adds full-screen passes, so
   it is measured on Factory 02 before it ships.

## Steps

| Step | What | Done when |
| --- | --- | --- |
| L0 | Spike: emissive survives the neutral-material and finish paths; frame time on Factory 02 with 800 glowing lenses and with a 10 fps redraw timer | numbers written here |
| L1 | Glow appearances in the library + adapter applies `emission` + GLB emissive kept; Appearance pane "Lights" group; Sage sees them via its existing finish tools; tests | a lens set to cool-white LED glows in the desktop app |
| L2 | Lights on/off saved with the scene + "Evening" scene preset; tests | Factory 02 in Evening with lights on/off shots |
| L3 | Floor light pools under light rows (one mesh per row), only when lit and dark | Evening shot shows pools, frame time within 10% of L2 |
| L4 | Blink / strobe / rotate patterns + redraw timer that idles when nothing blinks, when hidden, and under reduced motion; tests | a beacon blinks; CPU/GPU idle again when it leaves view |
| L5 | Stack light, rotating beacon, glowing exit sign models; Factory 02 pass (all 800 lenses, exit signs, a stack light per robot cell, beacons per the decisions) | shots + saved revision, findings unchanged |
| L6 | Optional bloom in Evening only, measured | user's go-ahead after the L6 numbers |
| L7 | Lights on/off per area (named floor areas or a rectangle drawn on the plan), saved with the scene; general lighting only; Sage does it from a sentence | Evening shots of Factory 02 with lights on in two areas only; frame time within the noise; tests |
| L8 | Outdoor night lighting: soft see-through beam cones and ground pools for a few dozen outdoor lamps, Evening only; a pole light model when a layout has none | Evening shots of the Factory 02 car park; frame time measured; tests |
| CC | Coverage check: the lot or a floor coloured by estimated brightness, dark spots between lamps listed; Sage can run it; always labelled an estimate | one lamp checked by hand; shots; tests |

Order (the user, 2026-10-31): L1, L2, L3, L7, L4, L5, L6, L8, CC. L4 was already built when L7 was added, so the
build order from there is L7, L5, L6, L8, CC.

Then the usual port to the real repo, desktop restart, and one short Sage turn ("turn the lights on and switch to
the evening scene") with the user's approval for the paid turn.

## L0 results (2026-10-31, test copy)

Setup. The test copy's Factory 02 is the 2026-10-22 copy (1,545 placements) and has no light rows, and the
real light-row asset is not in the test copy. So the spike used a stand-in: `asset-lighting-spike-high-bay-row-294m`
(50 round lamps on 294 m, each a rod, housing and lens; 6,800 triangles per row; the lens authors a white
`emissiveFactor`), hung at 5.63 m, 16 rows, in a scratch layout `fl-lighting-spike-factory02` (1,561 placements).
Test-copy only (gitignored catalog, test store); scripts `lighting_spike.py` and `lighting_spike_measure.py` in the
test root. Headed Chromium, ANGLE on Intel UHD Graphics (D3D11), 3D canvas 1395-1695 x 532 at pixel ratio 1.25,
neutral asset materials. The machine was busy (desktop app, Cursor, Codex; about 2 GB free).

Where a glow survives today:

- **Neutral path (every Factory 02 asset): lost twice.** `createNeutralAssetMaterial` sets emissive to black, and
  `batchStaticPrototypeMeshes` merges all neutral parts that share colour and roughness, so a row's 150 parts
  (rod, housing, lens x 50) become one mesh and a lens cannot glow on its own. Two small changes fix both (tried
  and reverted): copy the source emissive into the neutral copy, and add emissive to the batch key. The row then
  draws as two instanced meshes (housing + rod 5,600 triangles; lens 1,200 triangles, glowing): **+1 draw call
  for all 800 lenses**. (L1: not needed for the real assets, which are authored finishes; see "L1 results".)
- **Finish path: never set.** `createFinishMaterial` has no emissive; L1 adds `emission` there. Part overrides
  (`set_component_materials` with `appearanceId`) build their material through it too; those materials are not
  neutral, so they are not batched (one draw per lens part, instanced across rows that share the overrides). The
  instanced path clones the material (emissive kept) and tints with instance colours, which touch only the base
  colour.
- **Selection: keeps the glow.** Instanced rows: glow unchanged while selected and after clearing (checked).
  Non-instanced objects save their emissive the first time they are highlighted and put it back after; the L2
  lights switch must update that saved value (`facilitySelectionOriginal`), or the next deselect undoes the switch.
- **Assets that already author a glow:** 6 of 541 catalog GLBs. Five Private Gym court walls ("Warm linear wall
  light", meant to glow) and "Modern Computer Desk" (`asset-import-bzkhmca1or28`: 0.19 grey on its default
  material, a 3ds Max export default; used only in the asset lineup). None in Factory 02. (L1: superseded; the
  glows meant to show are all authored finishes and already kept, and the neutral path keeps zeroing leftovers
  like this one, so no threshold is needed. See "L1 results".)

Frame time (median of 40 synchronous frames, GPU wait included, ms; draw calls; triangles):

| Run | Aerial | Aisle | Calls | Triangles |
| --- | --- | --- | --- | --- |
| Today's code, lamps unlit (merged) | 66 (min 50) | 57 (min 45) | 2,534 / 2,374 | 10.7 M |
| 800 lit (emissive set at run time) | 73 (min 50) | 69 (min 50) | same | same |
| L1 shape (lens split, GLB glow kept) | 72 (min 59) | 70 (min 54) | 2,535 / 2,354 | 10.7 M |

Interleaved on/off at the aisle view (4 x 30 frames each): off 62-107, on 60-94. **Glow has no measurable cost;
run-to-run noise on this machine is about +-20 ms.** A Factory 02 frame costs 50-70 ms on this GPU whatever the
lights do (about 2,500 draw calls), so the view tops out near 15-20 fps.

Redraw timer (15 s each; CPU = all Chromium processes, % of one core; GPU = 3D engine of the GPU process):

| Redraw | CPU | GPU 3D | Frames/s reached |
| --- | --- | --- | --- |
| On demand, nothing changing | 4-6 % | 0-2 % | 0 |
| 10 fps timer | 78-93 % | 26-36 % | 10 |
| 30 fps timer | 183-199 % | 45-64 % | 18-25 |

What this means for the later steps:

- L1: glow is free. (Done; the neutral-path changes turned out unnecessary, see "L1 results".)
- L3: 10 % of a 50-70 ms frame is inside the noise, so compare L3 with L2 by switching the pools on and off in one
  session (interleaved), not by separate runs.
- L4: a fixed 10 fps redraw on Factory 02 costs about a core and a third of the GPU. Recommend: blink and strobe
  redraw only at their on/off edges (all lights on one shared clock, so one frame per edge; a 1 Hz blink is
  2 frames/s), and only rotate runs on a steady timer, capped low (about 8 steps per turn). Idle rules as planned.
- L5/L2 shots need the real Factory 02 and light-row asset in the test copy (the main session copies them in).

## L1 results (2026-10-31, test copy)

What L1 added:

- **Lights finishes.** Group "Lights" (`lights`), 9 finishes: Cool-white LED, Warm-white light, Exit sign green,
  Beacon amber, Alarm red, Signal blue, Stack light red / amber / green (`light-*` ids). Each has a `color` (the
  plastic when switched off, for L2) and `emission: {color, intensity}` (the glow). `pattern` and `periodSeconds`
  come with L4, where they are used. Library version 2026.10.31.1.
- **Drawn as a glow.** `createFinishMaterial` sets emissive from `emission` with `toneMapped = false`, so a lens
  reads as on in any scene; `userData.facilityGlow` marks it for the L2 switch. A color override on a light sets
  its glow color (the unlit plastic keeps the library color). The finish signature includes the glow.
- **Pane.** The Lights group appears in the Appearances tree (categories come from the manifest); the color field
  reads "Glow color" and starts at the glow; a one-line note says it lights no other surface. Thumbnails:
  `render_thumbnails.py --ids ...` renders only the named items; a light is drawn as a lamp in a dim room on a dark
  backdrop, because under the full key light every pale lens clipped to the same white.
- **Sage.** `list_facility_library` lists the Lights with their emission and says how to use them
  (`set_component_materials` on a lens or sign face, `set_appearance` on a whole small fitting). No new tool.
- **Assembly side: Lights hidden** (my call; easy to reverse). The Assembly view draws no glow, so its pane and
  Sage's `list_appearances` leave them out, and Assembly finishes refuse a light id. Glow in the Assembly view is an
  extra to offer, not built.
- **Neutral path left alone** (my call). A scan of the 602-asset catalog: 13 assets author a glowing material. The
  11 meant to glow (Factory 02 light rows, exit doors, exit-sign posts, floor scale, forklift charger and time clock
  displays, five Private Gym wall lights) are all flagged authored finishes, which skip the neutral copy, so they
  already glow today (tone-mapped). The other two are the stray 0.19 desk default and the L0 stand-in, which the
  neutral path keeps zeroing. This replaces the L0 recommendation (two neutral-path changes and a 0.5 threshold).
- **Found and fixed: part finishes lost the depth offset.** Authored materials draw with `polygonOffset(-1, -1)`;
  a part finish replaced the material without it, so seen from below at a grazing angle the housing (still pulled
  forward by its offset, which grows with the angle) hid a lens 1.5 cm below it and the lamp looked black. Part finishes
  and their previews now keep the depth offset of the material they replace (`keepDepthOffset` in
  `facility_layout_component_materials.js`). This affected any part finish on an authored asset, not only lights.

Test UI check (the real Factory 02 as copied in, 2,190 placements; headed Chromium; `lighting_check.py l1` in the
test root): row 5's lens set to Cool-white LED with the pane (part scope, Apply). The lens draws with the glow
material (emissive eef4ff, not tone-mapped) and its pixels peak at 255, where the other 15 rows' authored lenses
(emissive fffcf3, tone-mapped) peak at 237. After the selection highlight, deselecting gives the glow back. Reset took
it off and the row matched its starting state exactly. Apply edits the open draft only and nothing was saved, so the
test store's Factory 02 is unchanged. Shots in `ui-data/drive/lighting-l1/`.

Notes for the next steps:

- L2: the lights switch must turn off the authored glows too (the rows' own lenses, exit signs, displays), not only
  `facilityGlow` finishes, and update `facilitySelectionOriginal` on non-instanced objects.
- L5: a row with its own part finish leaves the rows' instanced batch and draws on its own; rows sharing the same
  part finishes instance together again, so the L5 pass should give all 16 rows the same override.

## L2 results (2026-10-31, test copy)

What L2 added:

- **Lights switch, saved with the scene.** `adjustments.lights` in `extensions.facilityScene` (true or false; absent
  means on, decision 1). Checked by `normalize_scene`, in Sage's `set_scene` schema and text, and resolved by
  `resolveScene` (always true or false). The Scenes pane has a "Lights on" box.
- **Off turns every glow off** (my call): Lights finishes and the glows authored in models (the light rows' lenses,
  exit signs, displays). Authored glows are recorded once, when a model is prepared (`userData.facilityAuthoredGlow`:
  an authored-finish or artwork material with an emissive color). A Lights finish switched off is its plain unlit
  color, tone-mapped like any plastic. Switching reloads and rebuilds nothing. While an object is selected its
  highlight stays and the switch shows on deselect. Every copy of a model takes the switch's current state when it is
  made (`cloneRenderable`), so models loaded later, finish previews and activity actors match. Found while building:
  without that, an activity actor copied from a prototype prepared with the lights on came out lit.
- **Pane: re-editing the layout's own scene starts from its saved adjustments** (needed so Apply keeps the switch).
  Before, Apply dropped any saved adjustment not touched in the pane, including ambient and directional set by Sage.
- **Evening / night shift** (`evening`, group Industrial): the Machine shop HDRI at 0.06, ambient 0.04, directional
  0.25, exposure 1.0, background #0b0f16, no shadows. Tuned on Factory 02 from three levels. This one keeps the
  racks and boxes readable while the lamps carry the picture. Mean screen brightness is 27 vs 103-108 in
  Machine shop. Thumbnail rendered. Library version 2026.10.31.2. The Assembly scene list shows Evening too (a dark
  scene there). The switch is Facility only.

Test UI check (the real Factory 02, headed Chromium, `lighting_check.py l2 shots` in the test root, draft only).

- **As saved (Machine shop):** 7 glow materials, all lit:
  - the light-row lens, 16 rows in one batch;
  - the exit-door sign, x17;
  - the exit-sign post face and back, x2;
  - the floor-scale and charger displays, x4 each;
  - the time-clock face.
- **The pane flow:** Evening, Apply: 7 of 7 lit. Lights on unticked, Apply: 0 of 7 lit. The switch changes
  820-910 pixels per shot by more than 30 levels (up to 214): the lamps.
- **Reopening Evening** in the pane shows the box unticked. Machine shop starts ticked, and its lights-off preview
  works too.
- **Reopening Factory 02** dropped the draft: Machine shop, lit. Its shots are pixel-identical to the start, and the
  store file's hash is unchanged.

Shots in `ui-data/drive/lighting-l2/`.

Notes for the next steps:

- Floor paint, zone outlines, aisle overlays, the floor grid and printed wall artwork are drawn unlit (about 880
  materials in Factory 02). They keep full brightness in Evening and read as faintly self-lit lines. They were left
  alone (not in the plan); dimming them with the scene is an extra to offer.
- L3: per decision 3, pools show only in Evening and only with the lights on. Compare against these L2 Evening shots
  (same poses, `hall` and `aisle`).

## L3 results (2026-10-31, test copy)

What L3 added:

- **Floor light pools** (`static/facility_layout_light_pools.js`, new). A lamp is a connected patch of
  downward-facing triangles in a glowing material (a Lights finish or a glow authored in the model). Each lamp
  hung at least 3 m up, and still facing down once placed, throws one pool. A pool is a soft round spot on an
  additive quad, 2 cm above the floor (y 0), in the lamp's glow color. Its radius is half the hanging height,
  between 1.5 and 6 m. Brightness 0.08 (linear), picked on Factory 02 from 0.05, 0.08 and 0.12.
- **Adapter.** One pool mesh per render group. Factory 02's 16 rows draw as one batch, so their 800 pools are one
  mesh: one extra draw call. A group's pools are built the first time they are needed, kept with the group and
  dropped with it. They follow the group's layer, are never picked, and are freed with the view. Switching the
  lights or the scene only shows or hides them. Diagnostics: `appearanceLibrary.lightPools`.
- **Only in Evening** (decision 3): the Evening scene row carries `lightPools: true` in the manifest. It is not a
  per-layout setting, and the adapter checks no scene id. Library version 2026.10.31.3.
- **My calls:**
  - Pools land on the ground floor (y 0). A lamp above a mezzanine would light the floor under it; Factory 02 has
    none.
  - Exit signs, displays, beacons and stack lights throw no pool: they hang below 3 m or do not face down.

Test UI check (the real Factory 02, headed Chromium, `lighting_check.py l3` in the test root, draft only):

- Evening through the Scenes pane: 800 pools (16 rows x 50 lamps) in one mesh.
- Mean screen brightness:

  | View | Pools shown | Pools hidden (the L2 look) |
  | --- | --- | --- |
  | Hall | 36.4 | 26.6 |
  | Aisle | 30.7 | 26.4 |

- Lights off: no pools.
- Reopening Factory 02 dropped the draft (Machine shop, no pools), and the store file's hash is unchanged.
- Shots in `ui-data/drive/lighting-l3/`.

Frame time, pools shown vs hidden, in interleaved rounds, each frame timed until the GPU finished:

| Run | Rounds | Hall | Aisle |
| --- | --- | --- | --- |
| 1 | 6 | +2.7% | +1.8% |
| 2 | 6 | -0.8% | +18.0% |
| 3 | 10 | -5.7% | -3.9% |

Run 1 still had the pools at 0.12, left over from tuning; their cost does not depend on brightness. Run 3 started
with about 1 GB of memory free (the browser held about 4 GB with Factory 02 open), and its round medians swung
between 88 and 202 ms. The pools' cost is below the noise on this machine: 1 draw call added to about 6,400, and
1,600 triangles. Five of the six readings are within 10%; the one +18% did not repeat (run 3, same view: -3.9%).

Notes for the next steps:

- L4: a blinking lamp hung high would need its pool to blink too. The L4 beacons and stack lights hang low, so
  they throw none.
- L5: once the 16 rows' lenses get Cool-white LED, their pools take its glow color (eef4ff).

## L4 results (2026-10-31, test copy)

What L4 added:

- **Patterns** (`static/facility_layout_finishes.js`). A light's `emission` may carry `pattern` (steady, blink,
  strobe or rotate) and `periodSeconds` (0.5 to 10 s per cycle). Every lamp runs on one shared clock, so lamps
  with the same pattern change together. Each pattern is a few fixed brightness steps:
  - blink: on for the first half of each cycle, off for the second;
  - strobe: one flash, the first tenth of each cycle;
  - rotate: 8 steps per turn (1, 0.55, 0.2 five times, 0.55): the beam sweeps past the viewer, then the lamp glows
    dimly. Its brightness changes 4 times a turn.
- **Library** (version 2026.10.31.4). Beacon amber turns, Alarm red strobes and Signal blue blinks, each once a
  second. The other six Lights stay steady, so stack lights and exit signs are steady as decision 4 says.
  Descriptions and search tags say which ones blink. The pattern is part of a finish's signature. Python checks
  pattern and period when it loads the library. Sage: `list_facility_library` shows the pattern, and its
  description names the finishes that blink.
- **Adapter.** Rendering stays on demand. three.js calls a blinking finish's hook just before it draws an object
  with it, so only lamps actually drawn set their brightness and keep the view redrawing: in view, on a shown
  layer, lights on and not highlighted. After each frame, one timer is set for the next change of any lamp drawn.
  A 1 s blink redraws 2 times a second, a turning beacon 4 times.
  - An instanced batch is checked copy by copy: three.js culls a batch as a whole, and a batch of beacons can span
    the hall.
  - No timer while no blinking lamp is in view, while the window is hidden, or when the viewer prefers reduced
    motion. Under reduced motion every pattern shows steady.
  - When the window shows again, one frame restarts the blinking.
  - A blinking lamp throws no floor pool: a steady pool under it would not blink with it.
  - Diagnostics: `appearanceLibrary.lightPatterns`.
- **My calls** (the plan was silent; all easy to change):
  - which finishes blink, as above;
  - every period 1 s;
  - the strobe flash lasts a tenth of the cycle;
  - rotate dims and brightens the whole lamp. Drawing a beam that moves around the dome would be an extra to
    offer;
  - reduced motion is read when the view is created, as the adapter already did.

Test UI check (the real Factory 02, headed Chromium, `lighting_check.py l4` in the test root, draft only):

- **Stand-in.** There is no beacon model before L5. A forklift charger's display (`pl-factory02-support-charger-02`)
  got Beacon amber with the Appearances pane (part scope, Apply). The forklift beside it has no lamp part: its top
  plate is seen edge-on, and `ice_window` is only the inner faces of the window opening.
- **It turns.** Sampled every 10 ms, the brightness stepped 0.2, 0.55, 1, 0.55, 0.2, one turn a second, with
  125 ms steps. 12 frames were drawn in 3 s.
- **Shots** of the bright, sweeping and dim steps, in Machine shop and in an Evening preview (not saved). Mean
  display color, bright / sweeping / dim:
  - Machine shop: (232, 191, 48), (232, 164, 43), (209, 139, 38);
  - Evening: (227, 158, 31), (187, 124, 23), (131, 86, 15).

  In Machine shop the lit amber plastic keeps the dim step bright.
- **Redraws and load**, 15 s windows (5 s for "shown again"). CPU is all Chromium processes, as % of one core;
  GPU is the GPU process's 3D engine.

  | View | Frames/s | CPU | GPU 3D |
  | --- | --- | --- | --- |
  | Turned away (beacon not in view) | 0 | 5.7% | 0% |
  | Beacon in view | 4.0 | 10.8% | 8.6% |
  | Turned away again | 0 | 0.4% | 0% |
  | Window hidden (see below) | 0 | 5.1% | 0% |
  | Shown again | 4.0 | 17.5% | 11.7% |

  The last two rows come from an earlier run with a forklift part as the stand-in. Over all ten windows with a
  beacon in view: 4.0 to 4.2 frames/s, CPU 11 to 51%, GPU 9 to 15%. Over all six turned away: 0 frames, GPU 0 to
  0.1%. For comparison, L0's fixed 10 fps timer cost 78 to 93% CPU and 26 to 36% GPU.
- **Hidden.** This test browser keeps its pages visible: minimized, or behind another tab, `document.hidden`
  stayed false, and Chrome still drew about 1 frame a second (CPU 8 to 15%, GPU 1 to 3%). So the hidden row comes
  from setting `document.hidden` in the page and sending `visibilitychange`, as a hidden window would.
- **Reduced motion** (emulated, Factory 02 reopened): the display stayed at full brightness, 0 frames in 3 s, no
  timer.
- **Nothing saved.** Reopening Factory 02 dropped the draft, and the store file's hash is unchanged.
- Shots and reports in `ui-data/drive/lighting-l4/`.

Notes for the next steps:

- L5: the beacon model's lamp part takes Beacon amber. Beacons on the 5 forklifts and the 6 dock doors draw as
  batches, which the copy-by-copy check handles.
- After porting: whether a minimized desktop window reports itself hidden depends on WebView2. If it does not, a
  beacon in view keeps drawing while the window is minimized (1 to 4 frames a second). Worth one check in the
  desktop app.

## Cycle pattern (2026-11-02, test copy)

Added for the game room's color-changing accent lighting (the user, through the main session). A fifth pattern,
`cycle`: the glow stays at full brightness and eases through `cycleColors` (2 to 8 `#rrggbb`), one loop every
`periodSeconds` (2 to 60 s; blink, strobe and rotate keep 0.5 to 10), then repeats. Without `cycleColors` it uses
violet, blue, cyan, magenta (`#8a4dff #2f6bff #00d5ff #ff3dce`). The unlit lens follows the current color at half
brightness, as a recolored lamp does. A use of a Lights finish (placement, part or custom finish) sets it like the
other patterns; another pattern on top drops the colors. Each step between two colors is eased (smoothstep), and
the loop is cut into steps, at most 48 per color and 8 a second, so a cycling lamp in view redraws 8 times a
second at most, on the same timer as a blink. Like the other patterns: steady (its first color) under reduced
motion, no floor pool, no timer while out of view or hidden. Check (`cycle_check.py` in the test root, scratch
layout `fl-cycle-light-check`, a beacon lens with the default palette and a 12 s loop, Evening): 8.0 frames a
second in view, 94 colors over 13 s, the lens always half the glow; shots in `ui-data/drive/cycle-light/`.

## Ceiling mounting (2026-11-02, test copy)

Added so the Private Gym's table pendants and recessed downlights can be placed (the user, through the main
session): its lounge has 3.2 m walls but the shell has only a floor, so a lamp hung at 1.7 m failed
`unsupported_mounting_surface`. A zone may now carry `extensions.ceiling` = `{heightMeters}` (2 to 40 m above its
`floorElevation`, over its whole boundary), set or cleared (null) by the operation `set_zone_ceiling` {zoneId,
heightMeters}. `shell_with_plan_boundary` adds each one to the shell the checks see as a "ceiling" mounting surface
(`layout-ceiling-<zoneId>`, `ceilings.py`); the shared shell authority is not edited. A placement hangs when it says
`metadata.mountingSurface` `{"surfaceKind": "ceiling"}` (implied when its asset's `allowedMountingSurfaces` is only
`["ceiling"]`); its footprint must lie inside a zone ceiling and its top (the highest point of its physical volume)
must meet it, so `transform.position.y` = ceiling minus the asset's height (a 1.3 m pendant under 3.2 m: 1.9; a
0.015 m downlight: 3.185). Collisions stay 3D: a lamp over a table collides only where their heights overlap.
Sage: `set_zone_ceiling` is in its schema and allowed in a preview (review, not direct apply); its description says
how to hang a lamp. Floor pools are unchanged: a lamp throws one only from 3 m up and facing down, so the
downlights do (checked with 28 at 3.185 m) and a pendant whose lens hangs at 1.9 m does not. Check
(`ceiling_check.py` in the test root, scratch layout `fl-ceiling-check`, scratch pendant
`asset-ceiling-check-pendant`): without a ceiling the server refuses the hung lamp; with a 3.2 m ceiling it previews
without errors, saves, and shows over the table in 3D; shots in `ui-data/drive/ceiling-mounting/`.

## Gym lighting: lamps that light things, zone ceilings (2026-11-02, test copy)

Asked by the user through the main session: "brighter lighter ... key locations like the piano need to be lit ...
play with light to not hide things in the room", and "a ceiling with those ceiling lights". In Evening with the
lights on, lamps now light what they shine on, not only the floor; a zone ceiling shows from inside the room.

- **Zone ceilings.** A zone with `extensions.ceiling` (above) is drawn as a flat ceiling over its boundary at its
  floor plus that height (`renderZoneCeilings`).
  - Its triangles face down, so only a view from below draws it: the overview and any view from above or outside
    look straight in.
  - Its shading normal points up, so it is lit like the room under it. Facing down, nothing shone on it and it drew
    pure black even by day.
  - Matte charcoal (#2a2a2d, roughness 1); no shadow, never picked, on the overhead layer, in every scene. Hung
    lamps sit in it (polygon offset).
  - A finish came later: 'acoustic-tile' or 'open-deck' (see "Ceiling finishes and zone roofs" below).
- **Accent spot LED** (`light-accent-spot`, Lights). Warm white `#ffc08a` (about 3000 K), beam 30 degrees,
  estimate 700 lm at 30 degrees, and `emission.accent: true`.
  - Python accepts `accent` only as true with a beam angle.
  - The 3D view draws no floor pool or beam cone for it. It lights what its lens faces, as placed, with a spot light
    reaching about 8 m: a wall (an oval wash), an object or the floor.
  - Sage is told in one sentence. Library 2026.11.02.1.
  - The coverage estimate (CC) counts it like any lamp with data: 700 lm, aimed along its lens.
- **Spot lights** (`spotsOf`, `spotSettings`, `syncLampSpots`). The candidates are:
  - accent spots, at any height;
  - pendants: a Lights finish with estimate data (general lighting only, never a sign, beacon or signal lamp)
    whose lamps face down 0.5 to 3 m above the floor.
  - A pendant's lamp may be a bare bulb: any glowing part with a patch facing down (`bulbsOf`). The gym's vintage
    billiard pendant has three bulbs, a tenth of whose surface faces down, so the pool lamp test (a fifth) would
    miss them.
  - Each copy gives one spot: at its lamps' centre, aimed along their mean aim. Its intensity is the lamp's candela
    (lumens and beam, as CC) times LUX_TO_SCENE (1/250, set by eye). The cone is 1.5 times half the beam, soft
    edged, fading to nothing at 8 m (accent) or 6 m (pendant). No shadows.
  - The scene holds a fixed 8 three.js spot lights while there are candidates, so lit materials compile once.
  - Before each frame they go to the 8 candidates nearest the orbit target (or 3 m ahead of a walker); unused ones
    are dark.
  - They follow the lights switch, the scene and the asset layer. Light areas (L7) switch general lighting only,
    so they leave spots on.
- **Fill** (`fillField`, `patchFillShader`, `syncLightFill`). General lighting gently lifts what stands under it.
  - The lit floor pools (not outdoor beams, not lamps an area switches off) are summed into a small half-float
    map over the plan (0.25 m texels, at most 512 a side).
  - Each adds its color times 0.7 (about a quarter of the daytime sun), falling smoothly to nothing at twice its
    pool radius, capped at 1.5.
  - Every lit material in the model adds the map to its indirect light, only below the highest lamp over that
    point. A chair under a downlight is lifted; the ceiling is not.
  - Materials are patched once, the first time the fill is wanted, and switched off by a uniform outside Evening.
    A daytime-only session patches nothing.
  - Only under zone ceilings (the user's choice after the first port, 2026-11-02): only pools whose lamp is in a
    zone with `extensions.ceiling` count. A layout without a zone ceiling gets no map, no uniforms and no patched
    material: Factory 02's Evening is pixel for pixel as at 12a038a again (aisle identical; hall identical but for a
    blinking beacon's 7 pixels). Removing the last ceiling frees both maps.
  - The ceiling mask (`fillMask`, after a Codex review of 43662a6) cuts the fill at the ceilings' footprint, so
    outside it the fill is exactly zero. It is a second half-float map, twice as fine as the fill map over the same
    plan (0.125 m texels), holding the signed distance to the footprint's edge less 1 cm. The shader adds the fill
    only where it reads above zero.
    - Read with linear filtering, distances alone leak a few centimetres past an inner corner. So each texel is
      also held at or below the signed distance to the line of every footprint edge within a texel diagonal: in a
      cell an edge crosses, the filtered value is then at most that edge's line distance, below zero on its outer
      side. The fill map itself is no longer cut, so a room's own walls keep all their fill.
    - The cost: 1 cm along a straight edge (a wall face on a ceiling zone's edge counts as outside), up to about
      0.18 m in an inner corner of the footprint, and the map's outermost 0.125 m, where the fill is near zero.
    - Built once per fill map grid and set of outlines, by scanlines and only near the edges: 2,000 lamps under
      100 ceiling zones take about 30 ms (the first version's per-texel outline tests took 1.8-2.5 s).
    - Nearby rooms keep separate distances (after Codex reviews of b4437c2 and a068a1d). Two outlines touch when
      they overlap or meet, and clash when they do not but are nearer than 0.75 m. The mask has up to 4 channels
      (R, RG or RGBA) and the shader takes the largest.
      - Each channel holds groups of outlines. A group grows from an outline through the outlines touching it,
        leaving out any that clashes with one already in. Groups are made until each outline and each touching
        pair is in one, so a shared edge is never an edge everywhere.
      - Groups that overlap or come nearer than 0.75 m take different channels. Two rooms a wall's width apart,
        joined by a hallway across their ends, become {room 1, hallway} and {room 2, hallway}.
      - A room's wall a few centimetres from the next room's ceiling keeps its fill. Before, the other room's edge
        lines cut it: a wall 5 cm inside read -0.085 instead of +0.04, at a068a1d still when a hallway joined them.
      - Outside every ceiling every channel is at most zero.
      - With more than four groups near one another, one shares a channel: near the others its fill is cut a
        little, never lit outside. So is a notch narrower than a texel diagonal within one outline, or between two
        touching ones.
      - The gym's 20 ceilings are one group: its mask is the same, texel for texel.
- **Gym check.** `gym_lighting_check.py` in the test root makes the scratch layout `fl-gym-lighting-check` from the
  test store's gym copy (282 items, read only). It adds:
  - a 3.2 m ceiling on the wellness lounge;
  - 28 downlights at 3.185 m, 3.1 m apart;
  - the vintage billiard pendant over the pool table (yaw 90);
  - a dome over the chess table;
  - four accent spots: two at z -3.9 aimed at the piano and guitar wall (yaw 0: the lens faces +z and the wall is
    at z -3.08), two at x 0.95 washing the scripture on the west wall (yaw -90);
  - warm white lenses on all of them.
  - It previews with no errors and saves (316 items). Evening: 6 spot candidates (4 accents, 2 pendants), fill
    from 28 pools.
  - The shots (`ui-data/drive/gym-lighting/`) show:
    - the felt and balls lit under the pendant; the chess table under the dome;
    - two washes on the piano and guitar wall and two on the west wall;
    - the black chairs under the downlights readable;
    - the ceiling dark over the room from inside, absent from the overview.
  - Daytime: no spots and no fill (0 patched materials). The ceiling reads matte grey from inside and is invisible
    from above.
- **Frame time.** Each frame timed until the GPU finished; 6 interleaved rounds of 15 frames, new lighting on vs
  off; machine short of memory.
  - Gym lounge: 129 vs 122 ms. Gym overview: 57.5 vs 54.4 ms. The rounds cross both ways.
  - Factory 02 hall: 164 vs 167 ms. Aisle: 151 vs 155 ms. No spot candidates (its lamps hang high and throw
    pools); a fill of 800 pools (512 x 334 map).
  - Factory 02's Evening then showed its racks, boxes and columns lit under the rows, where they were dark
    silhouettes. The user did not want Factory 02 changed by gym work: the fill is now only under zone ceilings
    (above), which Factory 02 does not have.

## Ceiling finishes and zone roofs (2026-11-02, test copy)

Asked by the user through the main session: "please build commercial ceiling + roof for all the areas that need
them" (the Private Gym). A layout with neither renders as before: Factory 02 pixel for pixel.

- **Ceiling finish.** `set_zone_ceiling` takes an optional `finish`:
  - 'acoustic-tile': a white suspended ceiling of 600 x 600 mm matte tiles in a thin light grey T-bar grid;
  - 'open-deck', or left out: the matte charcoal as before.
  - Saved as `extensions.ceiling.finish`. A set replaces the whole ceiling, so leaving the finish out clears it. A
    null height with a finish is refused.
  - The tiles are one 128-texel texture with the grid on 2 texels at each edge, mipmapped. It is mapped by plan
    position (x / 0.6, z / 0.6), so the grid lines up across rooms.
  - **Bulkheads.** Where a ceiling borders a higher one (reception 3.0 m beside cardio 3.6 m), a vertical face
    closes the step. It runs from the lower ceiling up to the higher one, faces the higher room and takes its color
    (charcoal, or the tiles' plain #f1f0ec). Without it the gap showed the sky, or the roof.
- **Zone roofs.** New operation `set_zone_roof` {zoneId, heightMeters}: 2-40 m, or null to remove it. Saved as
  `extensions.roof` {heightMeters}, allowed in a Sage preview, one sentence in Sage's schema.
  - A flat commercial roof over the zone outline. Its underside is at floor + heightMeters (the wall tops); it is
    0.2 m thick, with a membrane on top.
  - A 0.2 m wide parapet (#a4a7aa) rises 0.45 m above the membrane, with a darker coping (#8e9296) along its top,
    and its outer face comes 0.1 m down past the underside.
  - Solid from every side (2026-11-03; the user: "why am I going through the roof? they need to work like the
    factory ones"): the membrane faces up, the underside (#d6dadd) faces down, and the parapet has faces inside and
    out, its outer face also seen from inside down to the bottom of its drop. With the layer on, no view from inside
    a roofed building opens onto the sky.
    - A ceiling at the roof's height is drawn in front of the underside (polygon offset 2 against the ceiling's 1),
      so nothing flickers; the underside shows only above a lower ceiling.
    - Until then only the faces seen from above and outside were drawn.
  - No shadow, never picked, on the 'Roof sheeting (3D)' layer (off by default).
  - **Membrane texture** (asked with the solid roof: "also give great texture to the roof"): a light grey single-ply
    membrane, one procedural 512-texel texture covering 12 m (nothing downloaded), laid along the roof's longest
    edge:
    - sheets 3 m wide with heat-welded side laps (the shadow of the upper sheet, its edge, then the welded strip,
      about 19 cm in all), and an end lap every 12 m, staggered from sheet to sheet;
    - soft mottling at four scales, some weathering, and each sheet a touch lighter or darker;
    - mipmapped, with anisotropic filtering up to 8, so it shows no moire from afar. It is built once and shared by
      all roofs: about 25 ms, 0.1 s the first time.
    - No HVAC units or walkway pads (not asked).
  - **Shared edges.** Where a roof meets one as high or higher, its parapet has no outer face there. Where it meets
    a lower one, the outer face comes down only to that roof's membrane, however little lower it is (annex 3.3 m
    over pool 3.2 m: down to 3.4 m). Each edge is cut where a neighbour's corner lies on it or a neighbour's edge
    crosses it, so a roof crossing the middle of an edge leaves the open parts their face. Without this, the annex
    parapet's outer face showed through a doorway from inside the main building. (The lower-neighbour rule and the
    crossing cuts came from a Codex review of b4437c2.)
- **Check.** `roof_check.py` in the test root makes the scratch `fl-gym-roof-check`, a copy of
  `fl-gym-lighting-check` with the heights the main session will set on the real gym. It has 5 roofs and 20
  ceilings, 10 of them acoustic tile (the lounge included). Shots are in `ui-data/drive/gym-roofs/`.
  - Inside views (reception, washrooms, pool, annex, lounge, free weights, soccer, the cardio-reception step):
    roofs on and off are identical, apart from models finishing loading and a 15 x 2 pixel streak in the free
    weights view: a crack where a ceiling meets a wall top, through which a roof face shows when the layer is on.
  - At b4437c2 the pool view also had a one-pixel line where the tile ceiling meets the wall top: the annex
    parapet's outer face, then coming down to 3.2 m over the 3.2 m pool roof, showing through such a crack. With
    the face stopping at the pool membrane (3.4 m) the pool views are identical with roofs on and off.
  - The overview and the street views show the roofs over the ceilings with the layer on.
  - Solid roofs (2026-11-03), with the layer on:
    - 8 views from inside the roofs show no sky: from between a tile ceiling and the roof (reception, washrooms,
      wellness annex) the roof's underside and the parapet's inner faces close the view; under a ceiling at the
      roof's height (cardio open deck, pool tiles, boxing) the ceiling shows, not the underside.
    - Where a view from a room got past a ceiling (cracks where a ceiling meets a wall top, 1 pixel; past the end of
      the cardio-reception bulkhead into the plenum, a band), the sky showed with the layer on; now the roof shows.
    - Views with the layer off are unchanged: the gym lighting check is identical shot for shot. The scratch's
      differences from the earlier run were state that run left (a table selected, one black frame); the change
      touches only the roof functions.
    - Known limit: a higher roof inside a lower one's outline would show the lower roof's underside inside it. The
      gym's roofs do not overlap.
  - Lounge Evening under the white tiles: the 28 downlights sit flush in the grid and the pendant canopies meet it
    cleanly, without flicker (two shots of each close-up are identical). The accent washes and the fill read as
    before (the ceiling mask changed at most 1 level in 3 pixels).
  - Factory 02: the saved scene is identical to before, but for the compass widget's anti-aliasing. Evening is
    identical to 43662a6, with the same draw calls and triangles.
- **Frame time.** Each frame timed until the GPU finished, in interleaved rounds.
  - Gym, roof layer on vs off: overview 66.9 vs 68.2 ms; free weights 50.1 vs 49.4 ms; cardio-reception step 46.6
    vs 46.6 ms.
  - Solid textured roofs (2026-11-03, a loaded machine: both twice the numbers above, rounds varying by half):
    overview 133.5 vs 130.5 ms; free weights 101.9 vs 90.5 ms; cardio-reception step 66.4 vs 84.2 ms. No cost
    shows; the roofs add 2 triangles of underside each (rectangles) and the parapets' inner faces.
  - Factory 02 Evening in a fresh browser: hall 126-130 ms, aisle 132-158 ms, as at 43662a6. With the browser grown
    to 4 GB and 600 MB free on the machine, the same frames took 270-300 ms.
  - The fill on the gym with all 20 ceilings builds in 56 ms in the page, the first time (the mask alone takes
    2 ms in Node).

## L7 results (2026-10-31, test copy)

What L7 added:

- **Saved with the scene**: `adjustments.lightAreas` = `{mode: only | except, areas}`, with up to 64 areas, each
  `{surfaceId}` or `{rectangle: {minX, minZ, maxX, maxZ}}` (plan metres, at least 0.1 m each way, 3 decimals).
  - Python checks the shape when the scene is saved. Saving refuses a floor area id the layout does not have,
    but only for areas the change itself gives.
  - A floor area deleted later lights nothing. A change that does not touch the areas, such as Sage's "turn the
    lights off" (see the set_scene fix, 494f0bb), keeps them.
- **General lighting** = the lamps that throw L3 floor pools. There is now one lamp test, `lampPartsOf` in the
  light pools module, and it changes L3's test:
  - parts are joined by vertex position, not index, because glTF and box geometries split vertices at hard edges;
  - a part is a lamp only when its downward-facing patches make up at least a fifth of its surface, besides the
    old size, facing and height rules;
  - a glowing exit-sign box hung 3 m up no longer counts (its bottom edge is 4% of it). A lens (46%) and a bowl
    facing down (29%) still count. Factory 02 still has its 800 pools.
- **Drawing.**
  - Each steady glow material gets a small on/off table, one texel per lamp per copy, which its shader reads. The
    16 rows stay one batch, and changing areas rebuilds nothing.
  - A lamp switched off by area draws like L2's off: plain plastic, tone-mapped. Its pool is blanked in place.
  - Glows without lamps (exit signs, displays) carry the hook but always read as on.
  - Tables and the hook are added only once a scene uses areas.
- **Pane** (Scenes, under "Lights on"):
  - "General lights: Everywhere / Only in / Everywhere except";
  - the layout's floor areas as tick boxes;
  - "Draw an area on the plan": the plan opens, you drag a rectangle, then the 3D view returns. Esc cancels, and
    picking another tool or view ends it;
  - drawn rectangles listed with Remove;
  - a floor area removed from the layout is listed as removed and dropped on Apply.

  Live preview and Apply work as before. Switching to Everywhere and back keeps the ticked areas.
- **Sage**: `set_scene` takes `lightAreas`. Its description gives the example sentence and says where the floor
  area ids are. With 494f0bb, Sage can leave `sceneId` out and stay in Evening.
- **My calls** (the plan was silent):
  - the share of a fifth;
  - a selected or hovered lamp shows its highlight whole;
  - "Everywhere except" with no areas means on everywhere;
  - a drawn rectangle snaps to the plan grid, like other plan drawing;
  - the floor-area check applies only to areas a change gives.

Test UI check (the real Factory 02, headed Chromium, `lighting_check.py l7 shots` in the test root, draft only).
The same numbers came out in two runs.

| Scene (Evening) | Lamps on | Lamps off | Pools on / off |
| --- | --- | --- | --- |
| No areas | 800 | 0 | 800 / 0 |
| Only in 01 Receiving + 06 Finished Goods + Dispatch (ticked in the pane) | 135 | 665 | 135 / 665 |
| The same plus a 39.6 x 64 m rectangle drawn on the plan over 03 Robotic Production | 165 | 635 | 165 / 635 |
| Everywhere except those three areas (preview) | 635 | 165 | 635 / 165 |

- **Lamp by lamp.** The two floor areas light the west end of rows 1-8 and 10-16. Row 9 runs between them and
  stays dark. The rectangle adds 6 lamps on each of rows 11-15.
- **Stays on.** The 17 exit-door signs, both exit sign posts, the charger and scale displays and the clock all
  still glow. None of them has lamp numbers.
- **Saved and dropped.** Apply saved `{mode: only, areas: [the two floor areas, the rectangle]}` in the draft.
  Reopening Factory 02 dropped it, and the store file's hash is unchanged.
- **Frame time** (overview, 1500 x 640 canvas, 6 interleaved rounds of 15 frames): 96.1 ms median with areas,
  95.2 ms without, 90.7 ms before any area was used. That is within the noise: the per-round medians cross both
  ways.
- **Pane width.** In the first run the area names were cut short in the 230 px wide pane. The list now uses the
  full width, shows each full name on hover, and wraps the drawn-area line.
- Shots, including the plan while drawing and the pane, and reports are in `ui-data/drive/lighting-l7/`.

Not run: a Sage turn (it needs the user's yes). Extras to offer, as planned: outlines of the areas on the plan,
zones as areas, and dimming instead of off.

## L5 results (2026-10-31, test copy)

What L5 added:

- **Three light models** (`tools/factory02_light_models.py`). They are built from simple shapes, written to
  `generated/industrial_assets/factory02_lights/`, and listed in the private asset catalog. The app reads that
  catalog when it starts, so restart it after installing.
  - "Stack light - 3 lamps" (Automation), 0.381 m tall: red, amber and green 60 mm lamps, from the top down, on a
    short pole. Each lamp is its own part. Its footprint is the 40 mm mounting foot, so it fits on a guard panel's
    top rail.
  - "Rotating beacon" (Safety Equipment), 0.15 x 0.15 x 0.18 m: a base and an amber lens.
  - "Rotating beacon on wall bracket": the same beacon on a steel bracket, back plate against the wall.
  - Every part keeps its own color. The lamp parts face only sideways or up, so a lit lamp throws no floor pool
    (L7's lamp test needs a fifth of a part facing down).
- **The Factory 02 pass** (`tools/light_factory02.py`), re-runnable. It sets:
  - the lens of all 16 light rows (800 lamps) to Cool-white LED. Every row gets the same finish, so the rows still
    draw as one batch;
  - a stack light at each of the 12 robot cell entrances, on the top rail of the guard panel beside the opening:
    green lit, and R06 amber lit (decision 4);
  - a rotating beacon on the guard roof of each of the 4 powered forklifts, Beacon amber;
  - a rotating beacon on a wall bracket beside each of the 6 dock doors, 4.6 m up, left of the opening, Beacon
    amber.

  How a run goes:
  - it installs the models and works out what is missing or different;
  - it applies that to a staged copy of the store and checks it there: no spatial errors, the same warnings as
    before, and new notes only about its own placements;
  - with `--save`, it saves the checked result, but only if Factory 02 has not changed in the meantime.

  A second run finds nothing to do. After a forklift moves, a new run moves only that forklift's beacon. Stack
  lights and forklift beacons stand on top of their support, as the 3D view's own surface attachments do. Dock
  beacons are locked placements at 4.6 m, which the spatial check counts as overhead.
- **My calls** (the plan was silent, or the layout differed from it):
  - 4 forklift beacons, not 5. The fifth "forklift" is a hand-winch lift truck with no power; adding one is easy.
  - R06 is the amber cell.
  - The cells have no controller cabinets, so each stack light stands on the fence at the entrance. Its lamps are
    at 2.23 to 2.41 m, just above the 2.04 m fence.
  - The forklift beacon sits at the rear corner of the guard roof. The compact truck's roof is open slats under
    two side rails, so its beacon stands on the rear end of the left rail. Its first spot, worked out from the
    model file, was off the roof in front of the mast. A map of the roof as the 3D view draws it put it right.
  - Dock beacons hang on wall brackets, clear of the door tracks, the guard posts and the raised door.
  - Exit signs stay as they are. The 17 exit-door signs and the 2 exit sign posts already glow green, with their
    lettering, so I made no new exit sign model.
  - "Findings unchanged" means errors and warnings are identical, and new notes are only about the pass's own
    placements.

Test UI check (the real Factory 02, headed Chromium, `lighting_check.py l5 shots` in the test root):

- **Saved to the test store.** Factory 02 is now at revision
  c9bca828ce6f05b7c50e87e1cee1a4bc78e2551c31ec625ca0d2ffe7081a5e2b. The first save was eb300a48...; the second
  moved the compact truck's beacon.
  - Errors and warnings are the same before and after: spatial 4 warnings, routing 36.
  - 98 new notes, all about the 22 new placements: each gets asset-planning-evidence, clearance-rule and
    policy-rule notes (3 x 22). The 16 that are not overhead also get floor-load and surface-attachment-safety
    notes (2 x 16).
- **Rehearsal of the port step.** In a scratch copy of the test store I undid the pass: deleted the 22 placements
  and removed the 16 rows' finish. Then I ran `tools/light_factory02.py --save` on it fresh: 60 operations and the
  same errors and warnings. The result matched the test store's Factory 02 exactly, placements and the rest of the
  layout.
- **Glows**, as saved and in Evening:
  - Cool-white LED on 16 rows (one batch);
  - Stack light green on 11, Stack light amber on 1;
  - Beacon amber on 10, turning (2 batches: top-mounted and wall);
  - the exit signs, displays and clock as before.

  In Evening there are 800 floor pools, now in the LED's color (#eef4ff).
- **Turning.** With a beacon in view, sampled every 10 ms: the brightness stepped 0.2, 0.55, 1, 0.55, 0.2 once a
  second, with 12 frames in 3 s, as in L4. There are shots at the bright and the dim step, as saved and in Evening.
- **Redraws and load** (Evening, 15 s windows, 3 runs). CPU is all Chromium processes, as % of one core:

  | View | Frames/s | CPU | GPU 3D |
  | --- | --- | --- | --- |
  | Overview, all 10 beacons in view | 4.0 | 42 to 67% | 20 to 28% |
  | A dock door, one beacon in view | 4.0 | 8 to 11% | 8% |
  | East over the robot cells, no beacon in view | 0 | 1 to 6% | 0% |

  The overview costs the most: while a beacon turns in view, all of Factory 02 is drawn 4 times a second. L4
  measured 11 to 51% CPU with a beacon in view.
- **Frame time** on the overview (Evening, 1500 x 640 canvas): 97 ms median in two runs. The third gave 121 ms; the
  machine was busier during it, and its load numbers were higher too. L7 measured 91 to 96 ms.
- **Shots**, as saved and in Evening: the hall, the overview, the amber (R06) and a green (R07) stack light, a
  beacon on each kind of forklift, and a dock beacon. In the overview the fittings are too small to see; the
  close-ups show them. Shots and reports are in `ui-data/drive/lighting-l5/`.
- **Nothing else saved.** Evening was applied to the open draft only. Reopening Factory 02 dropped it, and the
  shots left the store file's hash unchanged.

Tests: `tests/test_facility_light_models.py` (6).
- **Models:** valid GLBs with named parts and their own finishes, faces pointing outward, no lamp part facing
  down, and catalog entries that match.
- **Install:** a second install changes nothing, and the host reads the entries.
- **The pass, on a small made-up layout:**
  - it places each light as designed, with no spatial errors and the same warnings;
  - a second run does nothing;
  - after a forklift moves, only its beacon moves;
  - a stack light whose cell is gone is removed.

The findings comparison changed too. The spatial check without a policy set gives one note that lists every
placement. When that note changes only by gaining or losing the pass's own placements, the comparison now counts
it as unchanged.

Notes for the port:
- Run the pass on the desktop's store with the desktop app closed, then restart the app.
- L4's note on minimized windows matters more now. Factory 02's overview has all 10 beacons in view, and it costs
  the most to redraw.

Not run: a Sage turn. Extras to offer: a beacon on the hand-winch lift truck, a beam that sweeps around the beacon
dome (from L4), and a new glowing exit sign model.

## L6 results (2026-11-01, test copy)

What L6 added: an optional glow halo around lit lamps, signs, beacons and displays.

- **Saved with the scene, off by default.** It is the scene adjustment `glowHalo`, not a view setting as the plan
  said, so Sage can turn it on (the user's ask, relayed by the main session). It shows only in a scene with floor
  light pools (Evening) and with the lights on. The Scenes pane has a "Glow halo" box for Evening, with live preview
  and Apply. `set_scene` takes `adjustments.glowHalo`, and `list_facility_library` (scenes) marks Evening with
  `lightPools`.
- **Drawn over the finished frame.** The scene is drawn as always, keeping its antialiasing and its lit glows
  (drawn outside tone mapping). The frame is then copied, three's `UnrealBloomPass` makes the halo, and the result
  is drawn back. `EffectComposer` and `OutputPass` were not used: they draw the scene off screen and tone-map
  everything at the end.
- **Only from glows.** The first version bloomed everything bright. At the plan's threshold, the yellow floor
  markings (drawn unlit, brightness 0.93) glowed like neon, brighter than an amber beacon (0.78), and no threshold
  could keep the beacons and drop the paint. So every glow now marks the stencil where it is drawn, and the halo
  spreads only from those pixels. A selected glow shows its highlight and no halo. The canvas now asks for a
  stencil buffer. A view without one shows no halo rather than one around everything.
- **Tuning:** strength 1, radius 0.5, threshold 0.35 (softness 0.15), on brightness as shown. A lit red or blue
  lamp is about 0.45, so it glows too. Lamps switched off and the dark step of a blink stay under it.
- **Fallback:** if the frame cannot be copied, the view says so once and shows without the halo.
- Vendored from three r184 (MIT): `UnrealBloomPass.js`, `Pass.js`, `CopyShader.js`, `LuminosityHighPassShader.js`.

Measured on Factory 02 in the test UI (headed test browser on the GPU, 1500 x 640 canvas, pixel ratio 1, Evening).
The machine was very short on memory during the run, so all frame times are high. The difference is what matters.

| | Halo off | Halo on |
| --- | --- | --- |
| Overview, median frame (4 interleaved rounds of 15) | 115.3 ms | 128.3 ms (+13 ms, +11%) |
| Overview, 90th percentile frame | 135.7 ms | 176.3 ms |
| Draw calls per frame | 6,693 | 6,709 (+16: the bloom passes and 3 full-screen quads) |
| Overview, beacons redrawing 4 times a second: browser CPU (one core) | 49-53% | 53-59% |
| Same, GPU 3D | 20-26% | 24-29% |
| Dock close-up: CPU / GPU | 9.8% / 7.4% | 10.6% / 9.0% |
| GPU memory | none | 18.2 MB at this size (two frame copies and the bloom buffers), freed when off |

- Pixels changed by more than 8 levels: hall 0.8%, forklift close-ups 1.8-2.2%, stack lights 0.3%, overview 0.02%.
  From a distance the halo hardly shows; up close it does.
- Shots in `ui-data/drive/lighting-l6/`:
  - `off-*` and `on-*`, the same poses without and with the halo;
  - `compare-off-mask-strong.png`, a crop sheet of no halo, strength 0.7 and strength 1.1;
  - `on-forklift-selected.png`, a selected forklift with no halo.
- Checks in the same run:
  - a Machine shop preview has no Glow halo box and draws none;
  - a lights-off preview draws none;
  - reopening Evening shows the box ticked;
  - Cancel restores the draft;
  - reopening Factory 02 as saved left the store unchanged (same hash).

For the user: keep it or drop it. It costs nothing while off. Turned on, it adds about 13 ms per frame on the
Factory 02 overview, less up close. Sage can switch it ("evening scene with a glow around the lights").

**Kept** (the user, 2026-11-01, relayed by the main session): as built, off by default.

## L8 results (2026-11-01, test copy)

What L8 added: soft beams and ground pools for outdoor lamps in Evening, and outdoor lights in Factory 02.

- **Library.** Three outdoor Lights finishes: Pole light LED (beam 110 degrees), Wall light LED (100) and Dock light
  LED (70, a warmer white). `emission.beamAngleDegrees` is new: Python accepts 10 to 160, the finish signature
  includes it, and Sage's `list_facility_library` says what it does and where it goes. Library 2026.11.01.1, with
  rendered thumbnails.
- **Aim and pool.** A lamp's aim is the area-weighted normal of its downward faces. A lamp with a beam angle throws
  its pool where its aim meets the ground: the view steps along the aim (0.25 m, up to 80 m) over the layout's ground
  surfaces (the truck yard 1.35 m down included), else the floor. The radius is that distance times
  tan(beam / 2), and the pool lies on that ground. As for floor pools, the lamp must hang 3 m above where it lands.
  A ground edit builds the pools again.
- **Cone.** All cones are one instanced mesh (one draw call), at most 64 per layout; lamps beyond the cap keep their
  pools. Each runs from the lamp along its aim to its pool and is as wide as the pool. Additive, no depth write, both
  sides, in the lamp's glow color: 0.14 at the lamp, fading as the square toward the ground and toward its edge as
  seen. Never picked.
- **When.** With the pools: Evening, lights on, the lamp's layer shown. L7's areas switch a cone and its pool with
  the lamp (decided where the lamp is, not where the pool lands).
- **Models** (`tools/factory02_light_models.py`, as for L5): `asset-factory02-pole-light`, an 8 m pole on a concrete
  base with one LED head, its lens facing straight down at 7.85 m; `asset-factory02-wall-light`, a wall pack whose
  lens faces down and 30 degrees out from the wall. Each lens is its own part.
- **Factory 02 pass** (`tools/light_factory02.py`, now L5 and L8), 30 more placements:
  - 16 car park poles, on the line between the 5 pairs of parking rows parked head to head, about 13 m apart (north
    lot z 126.5, 146.5 and 166.5, 4 each; south lot z 51.3 and 71.3, 2 each). No car reaches into the middle 2.2 m
    there; two assembly-point signs stand clear of them.
  - 8 truck yard poles, 3 m in from the yard's far (west) edge, 25 m apart, standing on the yard.
  - 6 dock lights (the wall light with Dock light LED), outside over each dock door: 4.6 m up (above the 3.55 m dock
    shelter, and hung overhead for the spatial check), back 3 mm off the wall, aimed out over the apron.
  - Staged check: errors and warnings unchanged (spatial 4, routing 36); 114 new notes, all about the 30 lights.
    Saved to the test store (revision 9900042991ca); a second run does nothing.

Measured on Factory 02 in the test UI (headed test browser on the GPU, 1500 x 640 canvas, pixel ratio 1, an Evening
preview, 6 interleaved rounds of 15 frames each way):

| | Beams hidden | Beams shown |
| --- | --- | --- |
| Car park from above, median frame | 57.3 ms | 60.3 ms (the rounds spread 55 to 65 ms either way) |
| Truck yard, median frame | 19.3 ms | 19.6 ms |

- Evening: 30 cones and 830 pools (800 indoor, 30 outdoor). Machine shop as saved: none.
- Pixels the cones change by more than 8 levels: car park from above 1.8% (they lie over the bright pools), at eye
  level in an aisle 12% (against the dark sky), docks 0.3%.
- Shots in `ui-data/drive/lighting-l8/`: `evening-*` (car park from above and in an aisle, the south lot, the truck
  yard, the docks), `evening-no-beams-*` and `saved-car-park.png`. The store was unchanged by the shots.

Offers, not built: brighter cones; wall lights along the other outside walls (Wall light LED is in the library,
unused in Factory 02).

## CC results (2026-11-01, test copy)

What CC added: an estimate of the light on the floor from the layout's own lamps, on request, for one area: the car
parks and truck yards, a floor area or a zone. In the Scenes pane, the plan and the 3D view, and for Sage.

- **Lamp data (CC1).** The 5 general and outdoor Lights finishes carry a typical output and beam ("typical, for
  estimates"): Cool-white LED 20000 lm 120 degrees, Warm-white LED 4000 lm 110, Pole light LED 12000 lm 110, Wall light
  LED 4000 lm 100, Dock light LED 3000 lm 70. Signal lights (beacons, stack lights, exit signs) light nothing. Lamps
  are found as the view finds the lamps that throw pools; the saved scene's switch and L7 areas turn lamps off.
- **Estimate (CC2, server).** Lux on a 1 m grid; each lamp a point source whose light fades away from its aim (the
  soft edge, below), with inverse square and cosine onto the ground below, out to 60 m. Walls stop it (added later,
  below); nothing else casts shadows, and no reflections or daylight. Totals (min, mean, max). A lamp lights the
  area when it adds at least 0.5 lux somewhere in it. Dark spots: connected cells below half the area's mean (or a
  given level), largest first, 20 listed, each with its deepest point (on a tie, the one nearest the spot's middle),
  size, lux and 3 nearest lamps. Areas: a floor area, a zone, a rectangle (Sage only) or the lot: outdoor ground
  (zones named parking, car park, yard or lot, and parking bays out of doors, less the building and floor areas;
  fixed later, below).
- **Soft beam edge** (2026-11-01, the user's go, relayed by the main session).
  - CC was first built with the plan's even beam: full intensity inside the beam angle, none outside it.
  - In the desktop app the main session found dark spots of 12 to 13 sq m at 0 lux about 12 m from four car park
    poles: a 110 degree beam from 7.85 m stops dead 11.2 m out. Makers give the beam angle where the intensity is
    half the peak, and light goes on past it.
  - Now, theta off the aim: I = I0 cos^m(theta), with m = ln 0.5 / ln cos(half the beam angle) (1.0 at 120 degrees,
    1.25 at 110, 3.5 at 70) and I0 = lumens (m + 1) / (2 pi), so the whole output falls in the lamp's front half.
  - Cutting each lamp at 60 m drops about 0.04 lux or less per lamp.
  - Each lamp works out only the area's cells within its reach. The whole lot's estimate takes 0.1 s (0.06 s with the
    hard edge).
- **Walls** (2026-11-01, the user's go, relayed by the main session).
  - Before, light went through walls: the hall's light rows lit the truck yard, the east car park and the annex
    rooms through the perimeter wall.
  - Now a lamp lights a cell only if the line from the lamp to the cell clears every wall: where it crosses a wall
    in plan, it passes above the wall's top. A wall wholly above a lamp stops none of its light.
  - A wall counts down to the ground. Factory 02's truck yard is 1.35 m below the hall floor the walls stand on;
    with a bottom check, hall light would pass under the dock wall onto a strip of yard.
  - The walls: each upright placement tagged "wall" (its centre line, from its box as placed) and the building's
    own walls (the shell's and the layout's perimeter and interior walls, as the spatial checks see them). Doors,
    mesh guards, fences, racks and machines stop nothing, and light passes a gap between walls in full.
  - A dark spot's 3 nearest lamps are now the nearest that no wall hides from it.
  - Factory 02 (75 wall placements: the 10 m perimeter and rooms of 3 to 3.6 m; no shell walls), mean estimated
    lux before and after:
    - Truck yard: 15.9 and 7.2. Dark spots below half the mean: 1 and 14; the biggest now 10,225 sq m at a mean of
      1.1 lux. The 16 hall light rows alone light 52% of the yard to 1 lux or more before, 30% after.
    - Receiving Docks R1-R3: 39.1 and 10.4. Employee Parking South: 32.2 and 18.9 (61 lamps light it, now 35).
      Employee Parking North: 16.8 and 16.2.
    - Employee Gym and Administrative Office, past the hall's 10 m east wall, with no lamps of their own: 35.8 and
      2.6, 38.2 and 5.2.
    - Car parks and truck yards: 35.6 and 26.6 (238 lamps light it, now 212). 01 Receiving + Raw Stock, inside
      the hall: 235, unchanged.
  - Door gaps. The 6 dock door infills (4.5 m wide, round a 3.0 by 3.2 m door) are not walls, so light passes
    each gap full height. Counted as walls, the yard's mean is 5.7 (7.2) and the hall rows light 8% of it to 1 lux
    or more (30%), through the 15 m opening in the west wall at z 91 to 106; closing that too leaves 0.1%.
  - Time: walls add about 0.2 s to the lot's estimate (0.75 to 0.95 s) and under 0.1 s to one area. The test
    server answers the lot in 1.3 s (curl). In the headed test browser it showed in 3.3 to 5 s, the 3D view
    drawing meanwhile.
  - Test UI (Evening previewed, store unchanged by hash): the lot, the car park and Receiving shown, hidden and
    dropped on an edit as before. Shots in `ui-data/drive/walls-cc/` (same names and poses as CC3's).
- **The lot is outdoor ground** (2026-11-01, a CC bug, fixed on the main session's word).
  - Factory 02's lot took in the hall's Equipment Service + Utilities zone: a zone holding parking bays counted as
    lot, and its 12 equipment bays are parking bays. 1,968 sq m of hall floor at a mean of 264 lux.
  - Now the lot leaves out the building as it leaves out floor areas, and a bay inside either marks no lot. The
    building: what each placement tagged "roof" and "building" covers (Factory 02's roof deck over the hall) and
    the outline the layout's perimeter walls follow. A canopy tagged "roof" alone is not the building.
  - Factory 02's lot (walls on), before and after: 31,473 and 29,460 sq m; mean 26.6 and 10.7 lux, 0 to 299 and
    0 to 176; 212 and 153 lamps light it; 3 and 18 dark spots (below 13.3 and 5.4 lux). The biggest is the truck
    yard's middle (14,084 and 11,476 sq m, at a mean of 2.7 and 1.5 lux); next, 6,652 sq m round the office car
    park.
  - The whole check takes 0.7 s; the building adds nothing measurable. Test UI: the lot, the car park and Receiving
    as before, the hall no longer coloured. Shots in `ui-data/drive/lot-fix/`.
- **View (CC3).**
  - In the Scenes pane, at the end of the scene editor: "Lighting coverage", the area to check (Car parks and truck
    yards, each floor area, each zone), Show and Hide.
  - The server estimates the layout as the view holds it: the saved revision plus the unsaved edits, read-only
    (`POST .../lighting/coverage`). It sends a packed grid (tenths of a lux) and the spot outlines.
  - On the floor in the plan and the 3D view: 8 bands of one amber hue, from near black (under 1 lux) to near white
    (200 and up), at 80%. In the plan it lies over the floor, zones, routes and markings and under the equipment. In 3D
    it lies 5 cm over the highest floor drawn under each cell (ground, floor area or the floor), unlit and never picked.
  - Dark spots are outlined in white (on a black casing in the plan) and numbered in the plan as the pane lists them.
  - A legend in estimated lux with the caption "Estimate, not a lighting design. No code-compliance claims." sits on
    the viewport in both views. The pane repeats the caption with the totals, the lamps that light the area and the
    dark spots.
  - Not saved. Hide, any edit to the layout or leaving it drops the estimate; a reply for a layout that changed
    meanwhile is not drawn.
- **Sage (CC4).** `check_lighting_coverage` (floor area, zone, rectangle or the lot): the same numbers and caption,
  and a standing line: an estimate, never a code or standard verdict.
- **Sage shows the overlay** (2026-11-01, the user's go, relayed by the main session).
  - After `check_lighting_coverage` in the chat, the view shows the same estimate on the floor, as the Scenes pane
    shows it: the plan and the 3D view with the legend, the caption and the numbered outlines, and the pane's block
    with its numbers when the pane is open.
  - How: the tool's done step names the area Sage checked and the layout revision it read. The chat page hands it to
    the facility view, which asks for that estimate as the pane does, and only while it holds that revision with no
    unsaved edits (a facility turn needs that anyway). Nothing is saved.
  - It stays until Hide or an edit, as the pane's does. Hide: the pane's block, or Hide on the legend (new).
  - A rectangle (Sage only) has no entry in the pane's area menu; the block still shows its numbers, the rectangle
    named, and Hide.
  - Test UI on Factory 02 (Evening previewed, the Scenes pane open, headed): Sage's done step for the truck yard
    showed it in 1.9 s with the yard's 14 numbered outlines, and the pane's block with the same numbers as the
    pane's own Show. The legend's Hide and the pane's each cleared it; a step for another revision drew nothing; an
    unsaved edit dropped it; the store was unchanged by hash. Shots in `ui-data/drive/sage-overlay/`.
- **CC5's live Sage turn** (the desktop app, the main session, 2026-11-01, on a scratch copy of Factory 02, hard
  edge): "Check the car park lighting at night." Sage checked both car parks (North mean 17.3 lux, South 29.7),
  called the numbers an estimate and made no code claims. The overlay showed the lot in 2.3 s with 20 numbered
  outlines; Hide cleared it. The main session runs it again after porting the soft edge.
- **Factory 02** (test UI, Evening previewed, store unchanged by hash), soft edge, with the first build's hard edge
  in brackets:
  - Car parks and truck yards, 31,473 sq m: 0 to 299 lux, mean 35.6 (0 to 328, mean 34.8). Under 1 lux: 12.5% of
    it (57%).
    - 2 dark spots below 17.8 lux (20 below 17.4): 12,271 sq m of the truck yard away from its west-edge poles (mean
      4.7 lux) and 7,182 sq m round the 20-space office car park (mean 5.1).
    - 238 lamps light it (170). Shown in 1.3 s.
  - Employee Parking South: 0.2 to 160 lux, mean 32.2 (0 to 175, mean 29.7).
    - 1 dark spot below 16.1 lux: the margin round the lit rows, 3,198 sq m (12 below 14.8: the margin and 11 small
      pockets between the poles).
    - The 6 pockets at 0 lux now get 24 to 30 lux. 0.6 s.
  - Employee Parking North: mean 16.8 (17.3); 1 dark spot (2).
  - Truck yard: mean 15.9 (13.1); 94 lamps light it (62), many of them hall rows through the wall.
  - Office car park (20 spaces): mean 1.2 (0).
  - 01 Receiving + Raw Stock: 139 to 284 lux, mean 235 (140 to 319, mean 250), no dark spots. 0.8 s.
- Found in the test UI and fixed before the commit: the car park's markings (its paint fills the lot) hid the plan
  colours; the legend sat under the plan's ruler and scale bar; a long zone name pushed Show off the pane; an error
  could be cut short in the pane's one-line status (it is now said in the block).
- Shots in `ui-data/drive/lighting-cc3/` (hard edge) and `ui-data/drive/lighting-cc-soft/` (soft edge, same names
  and poses): `3d-*`, `plan-*` and `pane-*` for the lot, the car park and Receiving.

Offers, not built: dock doors that stop light above and beside the door itself (now light passes each 4.5 m door
gap full height), drawing a rectangle in the view, a lux readout under the pointer, spot numbers in 3D, clicking a
listed spot to go to it. Reading makers' photometric files (IES, EULUMDAT) stays a later step.

## L7, L8 and CC (added 2026-10-31)

The user said "go" on these on 2026-10-31 (relayed by the main session). The specs below are theirs. The points
marked "my call" are mine, where the spec is silent.

### L7: lights on/off per area

Spec: lights on or off per area. An area is a named floor area (`facilityFloorSurfaces`, e.g. "01 Receiving + Raw
Stock") or a rectangle drawn on the plan. Saved with the scene. Each lamp's glow and floor pool is masked by its
position, because the 16 light rows span the whole building. Only general lighting follows the areas; exit signs and
beacons stay on. Sage can do it from a sentence ("lights on in shipping and receiving only, evening scene"). L2's
switch must leave room for areas.

Design:

- **Saved with the scene.** A new `adjustments.lightAreas`, next to L2's `lights`:
  - `mode` is `only` (general lights on only inside the areas) or `except` (on everywhere except inside them).
    My call: "only" alone could not say "lights off in the gym" without also darkening every aisle.
  - `areas` lists up to 64 areas, each `{surfaceId}` (a floor area) or `{rectangle: {minX, minZ, maxX, maxZ}}`
    (plan metres).
  - Absent: general lights on everywhere, as today. L2's `lights: false` still turns every glow off, areas or not,
    so L2's switch is unchanged and the areas sit beside it.
- **General lighting** (my call) = the lamps that throw floor pools (L3): a steady glow facing down, hung 3 m or
  higher. Exit signs, beacons, stack lights and displays stay on. One rule, so a lamp and its pool always switch
  together.
- **Lamp by lamp.** A lamp is inside an area when its centre is (seen from above, edges count as inside). A row
  that crosses three areas is split lamp by lamp, and each pool follows its lamp.
- **Drawing it.**
  - Each glow material with lamps gets a small table of which lamps are on (copy x lamp), which its shader reads.
    So the 16 rows stay one batch and one draw call, and changing areas rebuilds nothing.
  - A lamp switched off by area draws exactly like one switched off by L2's switch: its plain plastic,
    tone-mapped.
  - An off lamp's pool is blanked in place.
  - The table and the shader hook are only added once a scene uses areas.
- **Pane.** Under "Lights on":
  - "General lights: everywhere / only in / everywhere except";
  - the layout's floor areas as tick boxes;
  - "Draw an area on the plan": switches to the plan, you drag a rectangle, then it switches back to 3D;
  - drawn rectangles are listed, each with Remove.

  Live preview and Apply as now.
- **Sage.** `set_scene` takes `adjustments.lightAreas`. Its description gives the example sentence and says to find
  floor area ids with `inspect_facility_authoring` (floor_surfaces). Saving refuses an unknown area id. An area
  deleted later just lights nothing, and the pane lists it as removed.
- **Not in L7** (extras to offer): outlines of the areas on the plan, zones as areas, dimming instead of off.

### L8: outdoor night lighting

Spec:

- Visible beams as soft see-through cones fading toward the ground, plus pools of light on the ground.
- Only for a few dozen outdoor lamps (car park poles, wall lights, dock lights), never the 800 indoor lamps.
- No true volumetric fog.
- Pool size comes from pole height and beam angle.
- Shown in the Evening scene.
- If a layout has no outdoor lamps yet, authoring a simple pole light is part of L8.

Design (my calls, to settle when L8 starts):

- **Which lamps.** New outdoor Lights finishes (pole light, wall light, dock light) whose emission carries a beam
  angle. Only a lamp with a beam angle gets a cone. The indoor Cool-white LED has none, so the 800 indoor lamps never
  do. A cap of 64 cones per layout; any lamps beyond it get pools only.
- **Cone.** From the lamp along its aim, opening at the beam angle, down to the ground. Additive, see-through, no
  depth write. It fades toward the ground and toward its edge. All cones are one instanced mesh, one draw call.
- **Ground pool.** The L3 spot, centred where the lamp's aim meets the ground. Its radius is the distance along the
  aim times tan(beam angle / 2), so a wall light's pool lands in front of the wall.
- **When.** Evening (the scene's `lightPools` flag), lights on, and following L7's areas: outdoor lamps are general
  lighting.
- **Models and Factory 02.** A simple pole light (a 6-9 m pole and one LED head facing down, few triangles); wall
  and dock lights if needed. Factory 02 has no outdoor lamps today. An L8 Factory 02 pass, a re-runnable script like
  L5's, places a few dozen in the employee car park and truck yard and over the 6 dock doors.
- **Done when:** Evening shots of the Factory 02 car park, frame time with and without cones, tests.

### CC: coverage check (last)

Spec:

- Colour the lot or a floor by estimated brightness, from each lamp's height, output and beam angle.
- List the dark spots between lamps.
- Sage can run it ("check the car park lighting at night").
- Always labelled an estimate, not a lighting design, with no code-compliance claims.
- Reading lamp makers' photometric files is a later step, not now.

Steps:

- **CC1, lamp data.**
  - Each general and outdoor Lights finish gets a typical output (lumens) and beam angle, labelled "typical, for
    estimates".
  - A lamp's height comes from where it hangs, as for the pools.
  - Lamps switched off by the scene (L2 switch, L7 areas) count as off.
- **CC2, estimate** (server side, so Sage and the view get the same numbers).
  - **Brightness.** Estimated brightness on a 1 m grid over the chosen floor area, rectangle or the lot, from every
    lamp that reaches it. Each lamp is a point source with inverse square and the cosine of the angle. Its intensity
    fades away from its aim: half the peak at the edge of its beam angle and less past it, with its whole output in
    front of it. (Changed 2026-11-01 on the user's go. First built even inside the beam and none outside; see "CC
    results".)
  - **Totals.** Minimum, mean and maximum.
  - **Dark spots.** Connected cells below a threshold (default: half the area's mean, or a level the user gives),
    each with its centre, size and nearest lamps.
  - **Walls.** A lamp lights a cell only if the line between them clears the walls (wall placements and the
    building's own walls, up to their top). (Added 2026-11-01 on the user's go; see "CC results".)
- **CC3, view.**
  - A colour overlay on the floor in the plan and the 3D view, with a legend in estimated lux.
  - The dark spots are outlined and listed.
  - Always captioned "Estimate, not a lighting design. No code-compliance claims."
  - Shown on request, not saved with the layout.
- **CC4, Sage.**
  - A read-only tool, `check_lighting_coverage` (a floor area id, a rectangle or the lot), returns the totals and
    dark spots with the same label.
  - It makes no code or standard claims.
  - After Sage's check the view shows the same estimate on the floor, until Hide (the pane's or the legend's) or an
    edit. (Added 2026-11-01 on the user's go; see "CC results".)
- **CC5, checks.**
  - Unit tests, including one lamp checked by hand against the formula.
  - A test UI check on a Factory 02 floor and the car park.
  - One live Sage turn, only with the user's yes.
- **Later, not CC:** reading IES or EULUMDAT photometric files.

## Out of scope

- Moving objects (forklift and operator playback), per the user.
- Lighting design: no photometric files, lighting calculations to a standard or code checks. The look is
  illustrative, like the light rows today. The coverage check (CC) is a rough estimate and always says so.
- Real shadows from the lamps.

## Decisions (accepted as recommended, 2026-10-30)

1. **Glow by default.** Recommend: lights on by default, saved with the scene; the switch turns them off.
2. **Evening scene.** Recommend: add it as a preset; Factory 02 stays on Machine shop unless you switch.
3. **Floor light pools.** Recommend: yes, only in Evening.
4. **Blinking in Factory 02.** Recommend: a stack light per robot cell (12, steady green with one amber to show
   the idea), exit signs steady green, amber beacons on the 5 forklifts and the 6 dock doors blinking. Skip any of
   these you do not want.
5. **Bloom.** Recommend: build it last and only keep it if Factory 02 stays smooth.
