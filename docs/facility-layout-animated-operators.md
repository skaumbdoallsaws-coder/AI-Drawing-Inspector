# Animated Operators in Facility Motion

Implemented and verified on September 28, 2026.

## Behavior

- The manual layout's 20 existing operator placements now display the smooth shared
  walkthrough character in 3D, including helmet, vest, clothing and boots.
- This is an explicit visual substitution for asset-operator at catalog revision
  773d3761fb0796587de7a21ccb8b368f4334c71f73c06682b84472d69d4b5757.
  Other assets and unrecognized operator revisions retain their existing visuals.
- At rest, baked ordinary meshes use existing instancing and picking. There is no
  live skeleton per stationary occurrence. Catalog footprints/bounds remain authoritative.
- Activity playback and manual path previews create an independent animated rig for
  each displayed operator. Vehicles keep their catalog GLBs. Arms/legs follow absolute
  path distance and the existing display clock; seek is deterministic and pause freezes
  the pose. Turns and completed paths settle to a standing pose.
- Static orientation retains the catalog's +Z convention. Moving avatars use their
  actual -Z forward axis. Diagnostics expose both axes and mark the substituted visual
  as animated-operator-avatar, not an exact catalog GLB.
- Playback suppresses the original instances, restores them on close, and releases
  owned geometries, materials and skeletons. No asset, layout or route record is rewritten.
- The complete-reference scenario still contains 17 moving operators and six vehicles.
  Its existing handling of the other three operator placements is unchanged: they are
  suppressed during that scenario and restored on close. No new routes were fabricated.

## Verification

Passed:

- 79 renderer checks, including a new real-Three.js static-instance/activity/manual-path
  integration test: correct direction, pause, seek, return leg, endpoint idle, source
  suppression, exact matrix restoration and rig disposal.
- 88 workspace checks; shared-avatar, process-operator and camera-settings suites.
- Browser verification against an isolated copy of all 827 manual placements, real assets,
  existing motion API and the revision-bound cached complete-reference scenario.
- Native Electron verification through the normal application entry and protected managed
  backend, with the same isolated data and existing motion cache.
- Play/pause via visible controls, seek/reseek, Plan/3D switching, wide/narrow captures,
  no duplicate operators, and unchanged layout, revisions and editor history.
- Browser comparison between two close-up motion frames changed 15,624 pixels. Native
  wide and narrow screenshots were also visually inspected.
- Original manual layout and isolated saved copies remained byte-identical. The browser
  recorded only the read-only activity-scenario creation POST, not a Save request.
- Owned browser backend stopped. Native shutdown receipt confirms resourcesClosed,
  lifespanStopped and no cleanup errors.

Evidence (project-relative):

- .runtime/operator-motion-20260928-045032/result.json
- .runtime/operator-motion-native-1790587545924/evidence/operator-motion-check.json
- .runtime/operator-motion-native-1790587545924/evidence/01-walking-a.png
- .runtime/operator-motion-native-1790587545924/evidence/02-walking-b.png
- .runtime/operator-motion-native-1790587545924/evidence/04-narrow-motion.png
- Native cleanup: .runtime/operator-motion-native-1790587545924/desktop-logs/
  7aabd715-7688-4ef4-a090-aef2730da178.log

## Limitations Retained

The first test request used maximumActors=24 and was correctly rejected: this existing
complete-reference preset requires exactly 23. Evidence remains at
.runtime/operator-motion-20260928-041807/result.json.

A fresh, uncached complete-reference regeneration then exceeded the ten-minute test
limit, before playback loaded. Evidence remains at
.runtime/operator-motion-20260928-042140/result.json. Its server was stopped and layouts
were unchanged. No cold-generation performance improvement is claimed by this change.

Passing browser/native runs used copies of the live manual layout's existing artifacts
from .runtime/facility-layout/layouts/.derived/activity-scenarios. The application still
validated their revision, compiler binding and integrity normally; there was no validator
bypass or manufactured motion payload. The successful claim is cached playback and avatar
rendering, not fresh route compilation. Provider/chat interpretation was not exercised.

The avatar is illustrative. Its appearance and gait do not replace collision envelopes,
prove ergonomics, staffing, physical human motion, safety or manufacturing cycle times.

## Testing in the App

Reload the desktop app after preserving any unsaved work. Open Reference Factory - Manual
Build, switch to 3D and start the existing complete-reference movement playback. In the
Movement Playback pane, choose an Operator, press Focus, then Play. Pause and scrub to
inspect the limbs; Close restores the standing operators.

Automated entry points:

- tests/verify_facility_operator_motion_app.py: fresh isolated browser run; add
  --existing-motion-cache for the verified cached-playback path.
- desktop/tools/application-operator-motion-check.cjs: normal native application check.
  Use a fresh profile from desktop/tools/prepare-application-check.py and, for cached
  playback, copy the existing revision-bound activity artifact directory into that
  isolated profile's facility/layouts/.derived/activity-scenarios before launch.

No provider requests or Save commands are needed for these test drivers.

