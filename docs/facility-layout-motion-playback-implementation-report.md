# Facility Layout Motion Playback - Implementation Report

Date: 2026-08-30

Status: Implemented and browser-verified through FM0-FM6

## Result

InspectorPro can now replay one deterministic, revision-bound vehicle route in
Plan and 3D without changing the Facility Layout. The playback uses route-planner
poses, server-generated swept geometry, and clearance measured at published
validation samples. It is a presentation of existing evidence, not a traffic or
vehicle simulator.

The primary acceptance run used the archived manual reference factory:

- 45 zones
- 8 routes
- 827 placements
- 50 floor markings
- source SHA-256
  `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`

The source archive remained byte-identical before and after every engine and
browser run.

The visible Sage-chat acceptance used the explicit prototype host mode and the
exact draft profile revision
`3fb4abeec1542d894498417e8f594f2e139397aca276a6d022e7986eb2b2a530`.
The profile is marked `prototypeMode: true` and
`productionEligible: false`; InspectorPro does not promote or publish it.

A second visible Sage acceptance bound playback to the exact detailed forklift
already placed in the archived factory:

- placement ID `pl-043ba93c06287a1189f76121`;
- asset ID `asset-forklift-telescopic-red`;
- asset-definition revision
  `ab73c19258c171d1c3cab496cd317b1d896293249ddd62c57cba81a61829f214`;
- vehicle-profile revision
  `65e868ee2d4d122bf1d9db32d0d8a7279dbbcf386b1f973b587db0952a81d042`.

The profile is revision-bound to that exact asset definition. A different or
unbound placement fails before a motion package can be created.

## Implemented Phases

### FM0 - Baseline And Resource Contracts

The frozen fixture set contains:

1. The accepted traversal on `Main Forklift Boulevard` in the manual factory.
2. A real localized `envelope_refused` result produced by denser swept-envelope
   validation detecting an obstacle between coarse planner samples.
3. An accepted reverse traversal.
4. An accepted loaded traversal.

Global limits are fixed at:

- 25,000 swept-volume samples
- 5,000,000 sample-to-obstacle comparisons
- 8 MiB canonical uncompressed motion-package bytes

The hostile `gridResolutionMeters: 0.001` fixture projects 1,136,001 samples
and is rejected before dense allocation.

### FM1a - Planner Evidence And Pre-Allocation Guard

The route planner now produces accepted, envelope-refused, and unroutable
outcomes. Envelope refusals retain the attempted trajectory, exact blocking
distance, blocking pose, and obstacle identities. Sample count is projected
exactly before interpolation. Budget failure is a resource refusal, never a
geometric verdict.

Swept geometry is canonical polygonal geometry with normalized rings and holes.
Every validated clearance sample is retained. No downsampling or client-side
reconstruction is used.

### FM1 - Immutable Motion Package

`motion_package.py` implements:

- a closed discriminated package schema;
- outcome-scoped route and attempt fingerprints;
- planner versions inside the canonical hash;
- wall-clock generation time outside the canonical hash;
- an 8 MiB serialization guard;
- revision-bound package fetch through a bounded TTL store;
- a summary-only model payload;
- explicit proxy-versus-real-vehicle handling;
- carried-placement resolution only for a real placement identity.

### FM2 - Deterministic Sampling

Playback is parameterized by arc length, with shortest-arc heading interpolation.
Paused inspection snaps to a real validated clearance sample. Continuous playback
shows the preceding validated sample and labels its actual distance and spacing.
It never presents interpolated clearance as measured evidence.

### FM3 - Plan And 3D Playback

The existing owned animation loop now drives motion; no second loop was added.
Plan and 3D consume the same sampled state. The renderer supports play, pause,
scrub, and 0.25x-4x presentation rate. Playback state stays in browser memory and
never enters the layout, operation history, or Save flow.

The 3D view renders the exact profile footprint and server-provided swept
geometry. A real vehicle and its carried placements are temporarily reparented
and restored on disposal. Proxy vehicles are visibly qualified and cannot carry
placements.

Placed-asset playback automatically frames and follows the moving vehicle in the
normal 3D orbit view. The operator can toggle Follow without changing layout
state. Entering Walkthrough or Drone turns Follow off so those independently
controlled camera modes remain available while motion stays loaded. The moving
asset retains the active Facility display style; the acceptance screenshots use
neutral CAD gray while preserving the forklift's detailed geometry.

Walkthrough and Drone remain available while playback is loaded.

### FM4 - Evidence Presentation

The motion panel displays:

- accepted/refused/unroutable outcome;
- prototype-fixture status when applicable;
- playback position and estimated duration at profile maximum speed;
- clearance at the selected validated sample;
- actual validation sample spacing;
- fixed qualification and non-simulation disclosure;
- localized blocker evidence for a refused traversal.

### FM5 - Sage Intent Boundary

Sage can select one exact authored route and one exact published vehicle-profile
ID and 64-character revision. The browser tool contract contains identities and
travel direction only. It has no coordinate, pose, speed, duration, or grid
resolution field.

The parser refuses unsupported playback claims about throughput, capacity,
safety, compliance, fleet interaction, congestion, queues, and continuous
clearance. It does not steal ordinary circulation analysis or aisle-edit intent;
motion ownership requires explicit playback, replay, animation, traversal,
driving, or simulation language.

### FM6 - Acceptance

The five-run manual-layout engine baseline produced:

- package size: 499,927 canonical bytes
- poses: 569
- clearance samples: 2,841 at 0.1 m spacing
- route distance: 284.0 m
- planner estimate: 142.0 s at profile maximum speed
- planner p95: 3.183 s
- serialization p95: 0.352 s
- package byte reproducibility: 100%

The Edge Playwright run produced:

- Plan marker advanced from 56.8 m to 198.8 m
- Plan and 3D pose agreement: exact
- sustained measured playback: 30.15 FPS at 1920 x 1080
- Drone active with motion loaded: yes
- Walkthrough active with motion loaded: yes
- draft operations created: 0
- dirty state after playback: false
- source archive changed: no
- page, console, request, and HTTP 5xx errors: 0

The same route was then started through the visible Sage chat with the exact
paste-ready prompt. Sage resolved `Main Forklift Boulevard`, invoked the
identity-only browser tool, loaded accepted playback, and advanced beyond the
starting pose while the evidence was captured. The motion panel was visible,
the layout stayed clean with zero draft operations, all entity counts remained
unchanged, and the archive hash remained byte-identical.

The detailed placed-asset acceptance then replayed the same route with the exact
red telescopic-forklift placement. Browser diagnostics changed its representation
from a one-mesh footprint placeholder to the resolved GLB overview containing 11
prototype meshes. The GLB request returned HTTP 200. The vehicle advanced from
x = 58.6 m to x = 212.0 m, a 153.4 m route displacement, while 3D Follow kept its
projected center visible. Both canvas captures were nonblank, and the run produced
no page, console, request, or HTTP 5xx errors.

The browser uses an isolated `fl-main` identity clone because the local bootstrap
opens that stable ID. After substituting the archived layout ID, the browser
layout equals the archived manual layout exactly. The source archive is never
overwritten.

## Verification Receipts

Python:

- focused motion/service/agent/host/circulation/coordinator: 322 passed
- detailed placed-asset service/intent/agent/host regression: 231 passed
- shared operations/spatial kernel: 101 passed, 1 opt-in benchmark skipped
- Facility API: 9 passed

Browser contracts:

- Three.js adapter: 58/58
- workspace: 71/71
- session: 48/48
- Plan editor: 31/31
- transport: 12/12
- static safety contracts: 7/7

Evidence:

- `.runtime/facility-motion/fm0-reference-report.json`
- `.runtime/facility-motion/evidence/facility-motion-browser-evidence.json`
- `.runtime/facility-motion/evidence/01-plan-motion-20-percent.png`
- `.runtime/facility-motion/evidence/02-plan-motion-70-percent.png`
- `.runtime/facility-motion/evidence/03-3d-motion-midpoint.png`
- `.runtime/facility-motion/evidence/04-3d-drone-motion-loaded.png`
- `.runtime/facility-motion/evidence/05-3d-walkthrough-motion-loaded.png`
- `.runtime/facility-motion/evidence/sage-exact-prompt-motion-evidence.json`
- `.runtime/facility-motion/evidence/06-sage-exact-prompt-motion.png`
- `.runtime/facility-motion/evidence/detailed-forklift-motion-evidence.json`
- `.runtime/facility-motion/evidence/07-detailed-forklift-3d-first.png`
- `.runtime/facility-motion/evidence/07-detailed-forklift-3d-first-canvas.png`
- `.runtime/facility-motion/evidence/08-detailed-forklift-3d-second.png`
- `.runtime/facility-motion/evidence/08-detailed-forklift-3d-second-canvas.png`

## Deliberate Boundaries

- Release 1 supports one active movement.
- Playback does not simulate acceleration, traffic, queues, congestion, or
  vehicle interactions.
- Duration is an estimate based on route distance and profile maximum speed.
- Clearance applies only at published validated samples.
- Any layout-revision change invalidates playback in release 1.
- Production use requires an exact published vehicle-profile revision.
- The manual-reference browser run uses a clearly labelled prototype profile
  fixture and makes no production authority claim.
