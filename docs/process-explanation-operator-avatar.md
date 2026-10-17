# Process Explanation Operator Avatar

Scope: reuse the facility walker in the existing cooling-tower scene. Add
third-person exploration, articulated crouch/kneel/crawl, stair foot placement,
and an optional operator accompanying explanation steps. No equipment or layout
writes, staffing simulation, maintenance approval, or invented access paths.

Implementation:
1. Extend the shared rig with continuous posture transitions and two-segment
   limb posing; retain the original facility walking defaults.
2. Separate the process walker position from the camera. Reuse multi-level
   collision/surface helpers and add conservative pose envelopes. Keep C/Z/Space
   posture controls; V switches camera and K kneels. Dispose with the viewer.
3. Reuse actual CAD stair/platform groups and deterministic ground routing for
   guide targets. Unsupported or obstructed actions stop explicitly. An optional
   operator tour and narration cues use the same actor and update loop; pause,
   cancellation, step replacement, manual takeover and workflow exit cancel old
   movement. No model-authored coordinates.
4. Verify real-Three poses/resources, navigation and timeline contracts, then
   the real cooling tower in Playwright at wide/narrow sizes. Preserve failures
   and source hashes. Keep native Electron verification separate.

The existing tower scene derives a visual scale from its model bounds and uses
mesh-derived walk surfaces/sparse collision volumes. This is an illustrative
walkdown, not certified physical clearance or a safe operating procedure.

## Implemented

- Shared smooth-skinned operator, with standing, crouching, kneeling and crawling
  blends. Existing facility walking defaults are preserved.
- Third-person process exploration with a collision-retracted follow camera and
  first-person toggle. The actor is a disposable navigation overlay outside the
  CAD model and never becomes equipment or a saved layout placement.
- Conservative bent-body clearance and turning checks, actual stair treads and
  platform support, and bounded deterministic routes to existing component groups.
- Operator walkdown: filter approach, kneel, stand, stair ascent, platform pointing
  and descent. Route failure stops with an explicit finding rather than teleporting.
- Training step and cooling-tower narration cues; pause/resume, step replacement,
  manual takeover, deferred-cue cancellation, overview restoration and disposal.
- Legacy Three r128 skinning support, including separate rigid/skinned materials
  in CAD normal-depth and hidden-line passes. Material state is restored on failure.
- Follow-camera collision uses existing sparse volumes rather than repeated full
  CAD triangle scans. Redundant contained ground rectangles are removed before
  routing; full collision volumes still validate every accepted path.

## Controls

In Workflows > Plant / Process Explanation, use the existing walkthrough icon.
WASD moves; C crouches; K kneels; Z crawls; Space stands; V changes camera;
Escape returns to the prior overview. The operator walkdown toolbar button starts,
pauses, resumes or replays the guided sequence. Text fields retain their keyboard
input. Clicking the viewport takes manual control.

The 3D toolbar now also has shared [walkthrough camera settings](walkthrough-camera-settings.md):
Close/Standard/Wide, distance and rise sliders, reset, saved preferences and
mouse-wheel distance adjustment in third-person mode.

## Verification

Current focused results:
- Shared-avatar real-Three geometry/gait/resource checks passed.
- 76 facility adapter checks and 88 workspace checks passed.
- 17 Python process-walkthrough and parts-manual UI contracts passed.
- New operator checks cover both Three revisions, posture bounds, blocked standing,
  head clearance, turning, conservative route pruning, timeline pause/cancel,
  deferred-cue cancellation and rendering-failure material restoration.
- Captured real tower geometry completed the full guide at 50 ms and 250 ms steps,
  ascending approximately 1.466 m and returning to the ground. This is deterministic
  engine evidence, separate from browser playback.

Real browser acceptance passed:
- .runtime/process-operator-20260927-132928/result.json: all four rendered poses,
  first/third-person toggle, exact overview restoration, keyboard stair ascent and
  descent, full six-action guide completion, pause/resume, typing isolation,
  explanation-step replacement and viewer disposal. No page/shader errors.
- .runtime/process-operator-20260927-134207/result.json: final 1600x960 and 900x700
  framing, viewport resize, wrapped toolbar, HUD containment, input preservation,
  deferred-cue cancellation, workflow-exit gating and cleanup. Screenshots inspected.
- Both runs record zero layout mutation requests, unchanged tower and manual-layout
  hashes, and confirmed shutdown of their owned isolated backends.

The framing follow-up fixes the process host's inherited relative-positioning
resize bug and switches temporarily to first-person when a retracted camera cannot
frame the avatar. The actor remains outside model selection and saved content.

Native Electron and live synthesized narration have not been qualified by this
change. Voice requests were excluded; existing narration hooks and local procedure
step transitions were exercised without provider calls.

Reproduction: tests/verify_process_operator_app.py runs the full isolated browser
check; --framing-only runs the current focused UI/lifecycle follow-up.
Node checks are tests/test_process_operator.cjs and tests/test_facility_layout_avatar.cjs.
The operator Node test also accepts a captured geometry.json path to run the complete
route against actual CAD-derived surfaces and obstacles.

## Boundaries

The first integrated scene is the existing cooling tower. Other process models
need their own grounded target groups, walk surfaces and authored cue mappings;
this is not arbitrary model traversal or an approved maintenance procedure.
Crawling is a manual, clearance-checked exploration posture, not an automatically
invented maintenance route. Kneeling is stationary. No ladder climbing, hand-tool
interaction, ergonomic certification or fall-protection assessment is claimed.

The restricted headless renderer can run below interactive frame rates. A 90-second
playback diagnostic timed out while the guide was still making valid progress.
The walker now permits up to 250 ms elapsed time per frame; the existing movement
kernel subdivides collision checks. The browser diagnostic allows 180 seconds and
is a correctness check, not a desktop performance qualification. Earlier failed
and interrupted captures remain in .runtime/process-operator-*.
