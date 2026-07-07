# Engineering Lessons Learned

This file records hard implementation lessons from InspectorPro work that took real debugging time. Each entry should preserve the failure mode, the false assumptions, the fix that actually worked, and the checks we should require next time.

## 2026-07-05 - Engine Motion GLB/Motion Package Mismatch

### Context

We built motion playback for `Engine_Motion_Study`, a four-cylinder crankshaft, connecting rod, piston, pin, ring, and lower-block assembly. The intended demo was:

- Load the assembly in InspectorPro.
- Ask the agent to show motion.
- Combine FAI reasoning, part highlighting, and motion playback.
- Let the user vary RPM while the crank-slider mechanism stays physically assembled.

The motion package used SolidWorks motion-study samples from:

- `generated/engine_motion/motion_exports/engine_motion_crank_cycle_trimmed_45_raw.json`

The app played those samples against the pinned GLB:

- `generated/engine_motion/glb_assets_sample0/Engine_Motion_Study_sample0_colored.glb`

### What Went Wrong

The visible assembly looked wrong during playback. Connecting rods and caps appeared to lose concentricity with the crankshaft journals, and after one attempted fix the rods/pins/pistons were visibly broken at the small end.

The confusing part was that several checks were passing:

- The motion-package transforms were coherent.
- Runtime `motionJointCheck()` reported crank-to-rod/cap axis distances of `0 mm`.
- Package-level joint-closure checks passed.
- The GLB hash pin matched the package.

Those checks were not sufficient. They proved that the exported transform tracks were internally consistent, but they did not prove that the rendered GLB vertex geometry was baked from the same exact sample-0 component transforms.

### Bad Assumptions

1. **A passing transform-track check means the rendered assembly is correct.**

   False. The motion tracks can be correct while the GLB mesh vertices are stale, swapped, or baked from a different pose.

2. **A hash-pinned GLB means the asset is physically valid.**

   False. A hash pin only proves the package and asset are paired. It does not prove the asset itself was generated from the right geometry or transform source.

3. **Fixing the crank big-end alignment fixes the mechanism.**

   False. A connecting rod has at least two critical visual constraints:

   - Big end concentric with the crank journal.
   - Small end concentric with the piston pin and piston bosses.

   My first repair aligned the crank big ends by rebaking repeated rod/cap meshes from one known-good instance. That made the crank side look better but broke the piston-pin side. This was the wrong fix.

4. **Visual helper rings prove alignment.**

   False. The cyan witness rings were based on the wrong interpretation of mate-axis placement and made the view more confusing. Debug overlays must be mathematically correct and temporary; otherwise they become misleading UI.

### Real Root Cause

The sample-0 assembly GLB had baked geometry for repeated moving instances that did not match the raw SolidWorks sample-0 transforms used by the motion package.

In practical terms:

- The motion JSON was driving the parts according to SolidWorks sample data.
- Some rendered GLB meshes were not baked from that same sample-0 basis.
- Therefore the app was animating correct transforms against a visually invalid rest asset.

### Correct Fix

The correct fix was not to patch individual moving instances by eye. The correct fix was to rebuild the sample-0 assembly GLB from canonical part-level GLBs:

- Use each canonical part mesh as the local geometry source.
- Apply the raw SolidWorks sample-0 transform for every rendered leaf component.
- Preserve GLB node names so package binding still works.
- Rebuild the motion package so the GLB hash pin matches the corrected asset.

This fixed both sides of the mechanism:

- Crankshaft to rods/caps.
- Connecting rods to piston pins.
- Pistons to piston pins.
- Fasteners to rod/cap holes.

### Validation That Finally Proved It

The useful validation was vertex-level and mate-surface based, not just transform based.

For each relevant SolidWorks concentric mate, measure the rendered GLB mesh surface against the mate axis at sample 0:

- Crankshaft journal surfaces against rod/cap big-end axes.
- Rod small-end bore surfaces against piston-pin axes.
- Piston boss bore surfaces against piston-pin axes.
- Fastener/hole surfaces where applicable.

The corrected GLB produced effectively `0.00 mm` surface error for the checked mate surfaces.

Then verify runtime playback at multiple crank angles:

- `0 deg`
- `90 deg`
- `132 deg`
- `180 deg`
- `270 deg`

Runtime checks and screenshots were captured under:

- `.runtime/motion_fix_canonical_final/`

### Future Rule

For CAD motion playback, every exported package needs two independent validations:

1. **Track validation:** checks that sampled transforms are internally coherent.

   Examples:

   - Quaternion continuity.
   - Loop closure.
   - Driver completes expected rotation.
   - Joint closure from transform tracks.

2. **Rendered asset validation:** checks that actual GLB vertices match the same physical constraints.

   Examples:

   - Sample-0 GLB vertex surfaces align with SolidWorks mate axes.
   - Repeated instances are validated independently.
   - Both ends of a linked body are checked, not just one joint.

Do not ship motion playback based only on track validation.

### Debugging Checklist For Future Motion Work

Before wiring a motion package into the app:

1. Confirm the GLB hash pin matches the package.
2. Confirm every moving component binds to exactly one GLB node.
3. Confirm sample-0 GLB vertices match raw sample-0 transforms.
4. Confirm all relevant mate surfaces align at sample 0.
5. Confirm runtime playback at several crank angles with Playwright screenshots.
6. Confirm the user-visible mechanism, not just console metrics.
7. Do not use debug overlays as proof unless the overlay is itself validated.
8. If a fix improves one joint and breaks another, stop and validate the entire kinematic chain.

### Implementation Notes

Files involved in this lesson:

- `static/index.html`
- `tools/motion_package_build.py`
- `tests/test_motion_package_build.py`
- `generated/engine_motion/motion/engine4cyl_crank_cycle.json`
- `generated/engine_motion/glb_assets_sample0/Engine_Motion_Study_sample0_colored.glb`
- `generated/engine_motion/glb_assets_sample0/Engine_Motion_Study_sample0_assembly.json`

Useful runtime command:

```js
motionJointCheck()
```

Important limitation:

`motionJointCheck()` only checks the runtime mate-axis closure currently represented in the frontend. It should not be treated as proof that GLB vertex geometry was baked correctly. Vertex-to-mate validation belongs in the builder/test layer.

### Product Lesson

For a visual engineering tool, "the math says it is right" is not enough. The app is judged by whether the viewport communicates the physical truth. Validation must include the rendered artifact the user sees.

