# Facility Layout Motion Playback Plan

Date: 2026-08-31 (revision 7 - NAV1 compatibility amendment added)

Status: FM0-FM6 implemented and verified; the NAV1 compatibility amendment is
required before durable Facility navigation authoring is enabled. See
`facility-layout-motion-playback-implementation-report.md`.

Working name: FM0-FM6

## 1. Objective

Let a user watch a validated vehicle traversal inside a saved or draft facility
layout, in Plan and 3D, without introducing a simulator.

```text
an authored route + a published vehicle profile
  -> the existing deterministic planner produces poses and a swept envelope
  -> a revision-bound Facility Motion Package serializes that result
  -> the browser replays the package against the exact layout revision
  -> the user scrubs, inspects clearance, and sees refusals in place
```

The motion layer adds no new geometry authority. Every pose it replays was
already computed and validated by `plan_forklift_route` and
`validate_swept_volume`. Playback is presentation of existing evidence.

This work is **orthogonal to RQ0-RQ8**. It requires a layout with at least one
route and one published vehicle profile; it does not require reference-quality
generation. The first target is the archived manual reference.

## 2. What Already Exists

Verified in the repository:

1. `ai_inspector/facility_layout/routing.py` -> `plan_forklift_route` returns a
   complete, deterministic motion track:

   | Field | Use |
   |---|---|
   | `poses` | `x`, `z`, `heading`, `gear` per lattice sample |
   | `centerline` | `x`, `y`, `z` polyline |
   | `actions` | manoeuvre sequence, includes `reverse` |
   | `distanceMeters` | path length |
   | `estimatedTravelSeconds` | duration at profile max speed |
   | `sweptVolume` | `valid`, `sampledPoseCount`, `effectiveWidthMeters`, `effectiveLengthMeters`, `sweptBounds`, `findings` |
   | `routeFingerprint` | deterministic identity |
   | `sourceRevisions` | layout / obstacle context / vehicle |

2. `validate_swept_volume` runs before `accepted: True` is returned, so every
   accepted track is envelope-checked, not merely planned.

3. The published-profile gate is already strict: exact `vehicleProfileId` and
   `revision`, `status == "published"`, else
   `facility_circulation_vehicle_profile_unavailable`.

4. `generated/engine_motion/motion/` is an existing motion-package precedent:
   `motion_registry.json`, a frames package, a `_summary.json` carrying
   `available_motions` and `playback`, and a diagnostics file.

5. `window.InspectorProFacilityThree` is the established adapter capability
   namespace. The cooling-tower walkthrough extends it without restructuring
   the adapter.

Verified gaps (re-measured 2026-08-30):

6. `facility_layout_three_adapter.js` **owns an animation loop already** -
   `onAnimationFrame(timestamp, generation)` at line 2265, with injectable
   `requestFrame`/`cancelFrame` at 1727-1732, serving walkthrough, drone, and
   auto-rotation. The `generation` argument is a staleness guard against frames
   arriving after dispose. FM3 extends this loop; it must not add a second one.
   (Revision 1 of this plan reported no loop. That measurement was taken before
   the adapter grew from 8,287 to 8,449 lines and is superseded.)
7. `poses`, `sweptVolume`, and `estimatedTravelSeconds` appear **nowhere** in
   `static/*.js`. The track is computed and discarded.
8. `sweptVolume.sweptBounds` is an axis-aligned bounding box only. **There is
   no swept polygon in the current return value.** However
   `validate_swept_volume` already builds the world-space footprint for every
   sampled pose (`world = _transform_polygon(local, pose)`), so the union
   belongs there - not in the serializer and not in the browser.
9. **Refused traversals carry no trajectory.** `_rejected_route`
   (`routing.py:2673`) returns `poses: []`, `centerline: []`,
   `sweptVolume: None`, `routeFingerprint: None`, `distanceMeters: None`.
   Refusals divide into two classes:
   - **search failure** (`routing.py:2991`, `final_state is None`) - no
     trajectory was ever produced; static presentation is the only honest
     option;
   - **envelope failure** (`routing.py:3015`) - `poses`, `actions`, and
     `distance` are already reconstructed and in scope, then discarded. Partial
     trajectory evidence here is a parameter, not a redesign.
10. **Refusal findings index a different array, and two are unlocalized.**
    `validate_swept_volume` iterates `sampled = _interpolate_poses(poses, spacing)`,
    so `details.sampleIndex` addresses that **densified** array, not the
    planner's serialized `poses[]`. Only `route_swept_volume_collision` and
    `route_width_insufficient` carry it at all;
    `route_turning_radius_violation` and `route_reverse_not_allowed` carry no
    location. The validator also computes no cumulative distance along
    `sampled`.
11. **`accepted` has live consumers.** `circulation.py:3045` gates on
    `result.get("accepted") is not True`, and `planner.py:1719/1737/1825`
    construct and forward the boolean, alongside test consumers. It cannot be
    replaced; a discriminator must be added beside it.
12. **Validation is discrete, and playback is continuous.**
    `validate_swept_volume` is called with
    `sample_spacing_meters=min(0.1, resolution / 4.0)`, which sets a **0.1 m
    maximum, not a constant**. `grid_resolution_meters=0.5` is a *default
    argument* (`routing.py:2705`), not an enforced floor - the planner's only
    guard is `resolution <= 0` (`routing.py:2718`). The `max(0.5, ...)` floor
    exists solely in the circulation caller (`circulation.py:3022`).
    **`service.py:3243` passes `request.get("gridResolutionMeters", 0.5)`
    through unclamped**, so a caller can drive the resolution - and therefore
    the sample count and package size - arbitrarily far down. On the 120x90
    reference the spacing is 0.1 m. FM2 can render a pose anywhere between two
    validated samples, and
    such a pose **was never directly validated**. Clearance must therefore be
    reported at validated samples only; interpolating between them and
    presenting the result as measured evidence would be inventing it. The
    spacing is derived at run time and must be published from the actual run,
    never hard-coded. Because it is caller-influenceable, the FM0 sample-count
    ceiling is a real resource control, not a formality.
13. **There is no per-pose clearance.** The obstacle test is
    `_polygons_intersect(world, obstacle)` - a boolean - and `collided` records
    which obstacle IDs were hit, not the distance to them at each pose. Exact
    clearance at a scrub position is **new server analysis**, not existing
    evidence plumbing.

## 3. Product Boundary

### 3.1 Motion playback may claim

- that a specific vehicle profile, at a specific revision, traverses a specific
  route with a validated swept envelope;
- the clearance to named obstacles **at validated samples**, at the published
  sample spacing;
- the planner's own estimated travel seconds, labelled as an estimate derived
  from the profile's maximum speed;
- that a requested traversal was **refused**, and where.

### 3.2 Motion playback must never claim

- throughput, pallets per hour, cycle time, or capacity;
- congestion, queueing, or interaction between vehicles;
- traffic safety, operator safety, or regulatory compliance;
- that observed smoothness implies real-world drivability;
- continuous clearance. Between two validated samples there is no measurement,
  and none may be implied.

### 3.3 Vehicle identity

Two request shapes, with different rights:

- **"replay profile X on route Y"** - a profile-derived proxy. Permitted, but
  it must be visibly labelled a proxy, and it has no layout identity, therefore
  no `carriedPlacementIds`.
- **"show this forklift"** - requires `vehiclePlacementId`. Only this shape may
  carry loads, resolved as the placements whose
  `snapRelationship.supportPlacementId` equals that id.

### 3.4 Required refusals

Extend the existing G2.3 refusal vocabulary. These must refuse
deterministically, in both imperative and interrogative phrasing:

- "how many pallets an hour can this aisle move";
- "is this traffic pattern safe";
- "simulate the fleet";
- "show me congestion at shift change";
- any request to author poses or coordinates directly.

## 4. Facility Motion Package

One revision-bound, coordinate-carrying **output** artifact. Unlike the
model-facing program contracts, this one legitimately contains coordinates -
it is deterministic engine output, not model input. No model may author it.

```text
facilityMotionPackage                 immutable evidence; canonical-hashable
  schemaVersion
  packageId
  plannerVersions { routingEngineVersion, routerVersion }   hashed provenance
  layoutRevision                      generation provenance and v1 gate
  validationContextFingerprint?       required v2 playback gate
  obstacleContextRevision
  movement                            exactly one; see the union below

facilityMotionEnvelope                excluded from the canonical hash
  packageId
  generatedAt                         wall clock only
```

`plannerVersions` stays **inside** the hash. An `unroutable` movement has no
`routeFingerprint`, so versions cannot be bound transitively through it; two
packages built by different planner versions from identical inputs must not
hash alike. Only the wall-clock stamp sits outside.

The movement is a discriminated union on `outcome`. Fields not listed for an
outcome must be absent, not null, so a consumer cannot read a field that has no
meaning for that case:

```text
outcome = "accepted"
  movementId, routeId, vehicleProfileRef, vehiclePlacementId?
  routeFingerprint
  plannerDurationEstimateSeconds, distanceMeters
  poses[], cumulativeDistance[]
  carriedPlacementIds[]
  sweptEnvelope { valid, effectiveWidthMeters, effectiveLengthMeters,
                  sweptBounds, geometry, sweptEnvelopeRevision, findings[] }
  clearance { sampleSpacingMeters, samples[] }

outcome = "envelope_refused"
  movementId, routeId, vehicleProfileRef, vehiclePlacementId?
  attemptFingerprint                  domain-separated; see below
  attemptedPoses[], cumulativeDistance[]
  blocking { blockingSampleIndex, blockingPose, blockingDistanceMeters,
             blockingObstacleIds[], localized }
  sweptEnvelope { valid: false, ..., findings[] }

outcome = "unroutable"
  movementId, routeId, vehicleProfileRef
  findings[]                          nothing else; no trajectory ever existed
```

Clearance is stored compactly and keyed by distance, so it aligns with the
FM2 arc-length parameterization without an index mapping:

```text
clearance
  sampleSpacingMeters               derived at run time; published, not assumed
  samples[]
    distanceMeters                  cumulative along the sampled trajectory
    nearestObstacleIds[]            one nearest result; ties listed, not ranked
    clearanceMeters
```

One nearest-obstacle result per sample, not an obstacle-by-sample matrix. Ties
are listed rather than arbitrarily broken. **Every validated sample is
retained.** Keeping only local minima is semantic downsampling: it discards
traceability and shifts the burden to proving no smaller value exists between
retained points. Size is addressed by lossless wire compression or a compact
columnar encoding later, never by dropping measurements. A scrub position between samples
**quantizes down to the preceding validated sample** and the UI says
"clearance at validated sample", never "clearance here".

Swept geometry is polygonal, not a single ring. A sweep can enclose holes, and
`_vehicle_footprints` may return several parts:

```text
geometry
  polygons[] { exterior[], holes[][] }
  ringOrientation                     exterior CCW, holes CW
  startVertexRule                     lowest (x, z) lexicographic
  precisionDecimals
  polygonSortKey                      by first vertex, then area
```

`attemptFingerprint` is domain-separated so it is **structurally incapable** of
colliding with a validated `routeFingerprint`. It carries
`fingerprintKind: "facility-route-attempt-v1"` inside the hashed input, and
covers the attempted trajectory, profile and load, planner versions, validation
context, and the blocking evidence.

Every one of those normalization rules is required for byte-reproducibility and
mirrors what `canonical.py` already does for layout polygons. If the geometry
engine is unavailable the package **fails closed**, following the existing
`_require_geometry_engine()` precedent - it never emits partial geometry.


Playback state - `playing`, `t`, `playbackRateMultiplier`, `activeMovementId` -
lives in browser state only. It is never serialized into the package. Mixing it
with evidence would make FM1's byte-reproducibility gate self-contradictory,
since `t` changes every frame.

`plannerDurationEstimateSeconds` and `playbackRateMultiplier` are separate
quantities and must never be summed or conflated. The planner value is
distance divided by profile maximum speed with **no acceleration model**. It is
displayed as "estimated at profile maximum speed" and never as "travel time",
"cycle time", or "throughput".


`qualification` is mandatory and fixed:

> Replays one deterministically planned traversal against nominal geometry at
> an exact vehicle revision. It does not establish throughput, congestion,
> traffic safety, or regulatory compliance.

## 5. Architecture

```text
route + published profile
  -> plan_forklift_route            (extended by FM1a)
  -> motion_package.py              (new; serializer + arc-length table)
  -> transport                      (new endpoint, revision-bound)
  -> InspectorProFacilityThree.motion  (new adapter capability)
  -> Plan and 3D replay             (frame loop owns transforms)
```

Three invariants:

1. **The package is derived, never authored.** It is regenerated from the
   planner, never edited. No write path accepts a package as input to geometry.
2. **Playback is read-only.** It never mutates the layout, never enters the
   draft, and requires no Save. It is not an operation and produces no receipt.
3. **Revision binding is enforced at play time. The implemented FM0-FM6 v1
   package gates on the full `layoutRevision`.** It remains deliberately
   conservative and retains that behavior through its compatibility window.
   Durable navigation intent changes canonical layout bytes frequently, so it
   cannot be enabled on the v1 gate without making normal path authoring
   invalidate every package. The NAV1 compatibility amendment below therefore
   promotes a narrower `validationContextFingerprint` to a prerequisite for
   navigation authoring. It does not retroactively weaken v1 packages.

### 5.1 NAV1 navigation-authoring compatibility amendment

Before `extensions.facilityNavigation` can be written by the product, add a v2
motion-package contract with both:

```text
generationLayoutRevision          provenance; the layout revision at planning
validationContextFingerprint      active playback validity gate
```

At playback time, InspectorPro rebuilds the exact validation-context projection
from the current layout. Playback proceeds only when its canonical fingerprint
matches. The projection includes:

- selected actor placement transform and asset-definition revision;
- exact vehicle/operator profile and optional load revision;
- referenced movement program, anchors, handoffs, and manual constraints;
- traversable polygons and directed lane edges used by the solution;
- used route geometry, pavement markings, turnarounds, and crossings;
- shell and policy revisions used by validation;
- current obstacle records selected by the frozen influence region around the
  swept geometry; and
- geometry, buffer, canonicalization, routing, and planner versions.

Obstacle membership is recomputed from current geometry. A moved obstacle that
enters the influence region changes the fingerprint; an unrelated navigation
anchor outside the projection does not. Missing projected records fail stale.
The influence-region margin and **computational epsilon** are frozen and tested.
Neither is an engineering clearance and neither may be displayed as one.

The v2 gate additionally requires byte-identical canonical geometry and
membership on pinned Windows and Linux Shapely/GEOS fixtures. V1 and v2 do not
coexist as parallel validity rules for one package: schema v1 requires full
revision equality; schema v2 requires the validation-context fingerprint.

NAV1 exit evidence must prove:

1. adding an unrelated navigation anchor changes layout revision but preserves
   validity of an otherwise identical v2 package;
2. changing any projected route, actor, profile, anchor, constraint,
   traversable polygon, shell/policy source, or obstacle rejects before the
   first playback frame;
3. moving a previously unrelated obstacle into the influence region rejects;
4. a missing dependency rejects rather than falling back to full-layout
   equality; and
5. every existing v1 fixture retains its current full-revision behavior.

## 6. Implementation Phases

### FM0 - Baseline And Fixtures

Tasks:

1. Freeze a motion fixture set from the archived reference: one accepted
   traversal, one refused traversal, one reverse-using traversal, one with a
   carried load.
2. Record planner wall-clock for each on the frozen machine.
2a. **Measure package size before freezing any ceiling.** Serialize each fixture
    and record canonical uncompressed bytes, broken down by poses, swept
    geometry, and clearance samples. Establish **two global limits**: a
    canonical uncompressed byte ceiling and a sample-count ceiling. Both are
    fixed global numbers - a ceiling that scales with route length is not a
    resource limit. Cap canonical uncompressed bytes only; HTTP compression is
    negotiated separately and never counts toward either limit.
2b. **Author** a hostile fixture - a small `gridResolutionMeters` supplied
    through the `service.py:3243` path - and record its projected sample count.
    FM0 measures and freezes; it does **not** assert that the request fails,
    because the guard does not exist until FM1a.
2c. Record the derived `sampleSpacingMeters` from each run.
3. Capture Plan and 3D stills of the static route as the visual baseline.
4. Confirm the archived reference has a route and profile combination that
   plans successfully; if not, author the minimum fixture layout instead and
   say so.

Exit gate:

- four fixtures exist with recorded planner outputs and timings;
- canonical uncompressed size and sample count are recorded per fixture with a
  component breakdown, and both proposed ceilings are justified against the
  densest case;
- boundary fixtures exist at ceiling minus one, exactly at the ceiling, and
  ceiling plus one, for both limits, with expected outcomes recorded but not
  yet enforced;
- the hostile fixture's projected sample count is recorded;
- both ceilings are frozen as named constants before FM1a begins;
- the derived sample spacing is recorded, not assumed;
- the refused fixture carries real findings, not a synthetic failure;
- no fixture depends on a live provider.

### FM1 - Motion Package Contract And Serializer

New module `ai_inspector/facility_layout/motion_package.py`. Server-side only.
Touches no existing file except an export in `__init__.py`.

Tasks:

1. Define the closed schema in Section 4. Unknown fields fail closed.
2. Build the package from an existing `plan_forklift_route` result. Do not
   re-plan and do not re-validate; carry the planner's own outputs.
3. Precompute `cumulativeDistance` server-side so the browser never has to.
4. Resolve `carriedPlacementIds` as the placements whose
   `snapRelationship.supportPlacementId` equals `vehiclePlacementId`. When no
   `vehiclePlacementId` is supplied the vehicle is a profile-derived proxy with
   no layout identity, `carriedPlacementIds` is empty, and the package says so.
5. Serialize the three `outcome` values. `unroutable` carries no poses by
   construction; `envelope_refused` carries the partial trajectory added in FM1a.
6. Enforce the FM0-frozen **canonical-byte** ceiling during serialization; a
   package exceeding it fails with `facility_motion_package_too_large`. The
   sample-count ceiling is not enforced here - FM1a already refused those
   requests before allocation. **Never truncates** poses, geometry, or
   clearance samples, and never downsamples clearance. Deterministic segmentation at action
   boundaries is a possible later feature, not a v1 fallback.
7. Split the transport: **Sage receives only `packageId` plus a summary**
   (outcome, distance, duration estimate, sample spacing, blocking summary).
   The browser fetches the full package directly. A multi-megabyte pose array
   must never enter the model context or the 16,384-byte tool-response budget.

Exit gate:

- accepted, envelope-refused, and unroutable fixtures all serialize;
- the package is byte-identical across repeated runs from the same inputs;
  **only `generatedAt` sits outside the canonical hash** - `plannerVersions`
  remain inside it;
- fingerprint presence is scoped by outcome: `accepted` carries
  `routeFingerprint`, `envelope_refused` carries `attemptFingerprint`, and
  `unroutable` carries neither. Asserting the wrong one for an outcome fails;
- v1 `layoutRevision` and `vehicleProfileRevision` are present and match the
  planner's `sourceRevisions`; v2 additionally carries the NAV1 validation
  context and generation revision required by Section 5.1;
- pose count and `distanceMeters` match the planner exactly;
- no field in the package is model-authored;
- schema fixtures cover valid, refused, stale, oversized, and unknown-field
  cases.

### FM1a - Partial Trajectory, Blocking Evidence, Swept Geometry (planner)

Three planner changes. All surface data the planner already holds or can derive
in the loop it already runs.

Tasks:

0. **Pre-allocation sample guard.** `validate_swept_volume` calls
   `_interpolate_poses(poses, spacing)` (`routing.py:2366`), which materializes
   the densified list *before* any downstream code sees the result. A ceiling
   checked after the planner returns is therefore too late. Compute, from the
   sparse lattice `poses` and the resolved spacing, **before** densifying:

   ```text
   projectedSampleCount = 1 + sum over segments of
                              max(1, ceil(segmentDistance / sampleSpacing))
   ```

   This is **exact, not an estimate**: `_interpolate_poses` appends one pose at
   index 0, then exactly `max(1, ceil(distance / spacing))` per segment. If
   `projectedSampleCount` exceeds the FM0-frozen ceiling, fail with
   `facility_route_sample_budget_exceeded` **before** calling
   `_interpolate_poses`.

   This is a **resource refusal, not a geometric outcome.** It is neither
   `unroutable` nor `envelope_refused` - no geometry was disproven - and it
   produces **no motion package at all**.

   Reuse the array `_interpolate_poses` produces for validation *and* for the
   FM4 clearance sampler. It must never be densified twice.

   Sage must not control `gridResolutionMeters`. Direct API callers through
   `service.py:3243` remain bounded by this preflight, which is the only guard
   between an unclamped request value and memory.

1. At `routing.py:3015`, pass the already-reconstructed `poses`, `actions`, and
   `distance` into `_rejected_route` so an envelope refusal carries the
   attempted trajectory. The search-failure path at `routing.py:2991` stays
   empty; it never had one.
2. Accumulate cumulative distance along `sampled` inside the existing sampling
   loop, and publish on the refusal: `blockingSampleIndex` (explicitly indexing
   the densified `sampled` array), the `blockingPose` itself, and
   `blockingDistanceMeters`.
   **Playback truncation is driven by distance, not by either index.** Distance
   is the only quantity the densified validator array and the serialized
   `poses[]` share, and FM2 arc-length-parameterizes the latter, so the two meet
   without an index mapping.
3. Localize the two findings that currently have no position. Both are nearly
   free: the turning-radius loop already holds `index` and `break`s on first
   violation, and the reverse check is an `any(...)` that becomes a `next(...)`.
   Where a finding genuinely cannot be localized, mark it `localized: false`
   rather than inventing a position.
4. In `validate_swept_volume`, union the per-pose world footprints it already
   computes into `geometry.polygons[]`, applying the Section 4 normalization
   rules, and stamp `sweptEnvelopeRevision`.
5. Add `outcome` **beside** the existing `accepted` boolean, never replacing it:
   `accepted == (outcome == "accepted")`. `circulation.py:3045` and
   `planner.py:1719/1737/1825` keep working unchanged. Only the motion package
   uses the discriminator.

Exit gate:

- `projectedSampleCount` equals `len(_interpolate_poses(poses, spacing))`
  exactly, across every FM0 fixture;
- a request exceeding the sample ceiling fails with
  `facility_route_sample_budget_exceeded` **before** `_interpolate_poses` is
  entered, proven by instrumenting the call, and produces no package;
- the sample-budget refusal is distinguishable from `unroutable` and
  `envelope_refused` in both code and message;
- the densified array is produced once and shared by validation and clearance;
- boundary behaviour holds at ceiling minus one, exactly at, and plus one;
- an envelope refusal returns a non-empty attempted trajectory plus
  `blockingDistanceMeters`;
- a search failure still returns an empty trajectory and `outcome: "unroutable"`;
- every error finding is either localized or explicitly `localized: false`;
- `accepted` retains its exact current semantics for all existing consumers,
  proven by running the circulation, planner, routing, and service suites
  unchanged;
- `geometry.polygons[]` is byte-identical across repeated runs, including ring
  orientation, start vertex, precision, and sort order;
- geometry-engine unavailability fails closed;
- existing `routeFingerprint` values for accepted routes are unchanged by this
  phase, proven against the FM0 fixtures;
- `test_facility_layout_routing.py` is extended, not duplicated.

### FM2 - Deterministic Sampling

Poses come from the heading lattice as straight and 90-degree arc primitives,
so they are **not uniformly spaced**. Sampling by index produces a vehicle that
changes speed for no physical reason.

Tasks:

1. Arc-length parameterization using the precomputed `cumulativeDistance`.
2. Shortest-arc heading interpolation with explicit wrap handling.
3. Preserve `gear` from the lower-bracket pose; never interpolate it.
4. Expose `sampleAt(t)` as a pure function so it is unit-testable without a
   renderer.

Exit gate:

- `sampleAt(0)` and `sampleAt(durationSeconds)` return the exact first and last
  poses, not interpolations;
- constant `dt` produces constant distance travelled within a stated tolerance;
- a heading crossing the +/-pi boundary never rotates the long way;
- reverse segments report `gear: "reverse"` for their whole span;
- the sampler is deterministic: same `t` always yields the same pose.

### FM3 - Playback Capability

Extend `window.InspectorProFacilityThree` following the walkthrough precedent.

Tasks:

1. Add `motion.load(package)`, `motion.play()`, `motion.pause()`,
   `motion.seek(t)`, `motion.setRate(x)`, `motion.dispose()`.
2. **Extend the existing `onAnimationFrame(timestamp, generation)` loop.** Do
   not add a second `requestAnimationFrame`. Respect the `generation` staleness
   guard so a frame arriving after dispose is discarded like every other
   consumer's.
3. Own all transform writes inside that loop. State subscriptions may set the
   target; only the loop writes `position` and `rotation`.
3. Carry loads by **temporary scene-graph reparenting**. Do not serialize
   per-frame child transforms. Before reparenting, snapshot each child's
   parent, sibling order, local transform, visibility, and selection state;
   restore all five on dispose, on failure, and on a stale `generation`.
4. Refuse a v1 package whose `layoutRevision` does not match the active layout.
   Refuse a v2 package whose recomputed `validationContextFingerprint` differs,
   even when another revision field happens to match.
5. Render the vehicle from the published profile footprint, not a stand-in box.
6. Honour `prefers-reduced-motion` by defaulting to paused with scrub only.
7. Drive a **Plan-view marker** from the same `sampleAt(t)` and the same shared
   playback state, so Plan and 3D cannot disagree about where the vehicle is.

Exit gate:

- dispose restores every reparented placement's parent, sibling order, local
  transform, visibility, and selection state, byte-identical;
- the same restoration runs on playback failure and on a stale generation, not
  only on clean dispose;
- the layout document is never mutated during playback;
- a stale package is refused with a named code;
- no `requestAnimationFrame` handler survives dispose;
- scrubbing backwards and forwards through the same `t` yields identical poses;
- playback runs without console or page errors in both themes;
- Plan and 3D report the same pose for the same `t` within a stated tolerance;
- no second animation loop exists in the adapter;
- a frame delivered after dispose is rejected by the generation guard.

### FM4 - Swept Envelope Visualization

This phase is the reason the feature is worth building, and it needs a server
change first because `sweptBounds` is only an AABB.

Tasks:

1. Render the `geometry.polygons[]` produced in FM1a as a translucent ribbon in
   Plan and 3D, honouring holes rather than filling exteriors only.
2. Build a **per-pose clearance sampler** as new server analysis, placed beside
   `validate_swept_volume` in `routing.py` and reusing `_obstacle_records` for
   extraction. The current validator answers only "does the footprint intersect
   an obstacle"; it publishes no distance. This computes, per sampled pose, the
   minimum distance from the transformed vehicle footprint to each relevant
   obstacle, bound to `sweptEnvelopeRevision`.
4. For refused movements, render the envelope up to the blocking pose and
   highlight the obstacle named in the finding.
5. Show clearance in **two distinct modes**, never as a value for an
   unvalidated position:
   - *continuous playback* - display the most recent validated sample, labelled
     with its own `distanceMeters`, so the reading is always attributed to a
     real measurement behind the vehicle;
   - *paused inspection or scrubbing* - **snap the vehicle and the cursor to an
     actual validated sample** and show that exact value.

   Never interpolate a clearance value, and never display the minimum of two
   bracketing samples as the clearance "here" - that is not a proven lower bound
   for the interval between them.
6. Render a persistent viewport disclosure for the duration of playback:

   > Nominal geometry playback at published profile revision. Sampled
   > validation only; not vehicle dynamics, traffic, safety, or regulatory
   > validation.

Exit gate:

- the rendered ribbon is derived from server geometry, never from a client
  approximation;
- the ribbon for an accepted movement contains every sampled footprint;
- a refused movement shows the blocking pose and the named obstacle;
- clearance is verified against **analytical fixtures** with hand-computed
  distances, not against `analyze_primary_circulation_obstacles`. Those two are
  not equivalent and must not be required to agree: the circulation analyzer
  measures the static aisle corridor (centerline buffered by route width/2)
  against obstacles, while this sampler measures the transformed vehicle
  footprint at a heading. A vehicle narrower than its aisle legitimately reports
  more clearance than the corridor does;
- no safety, capacity, or compliance wording appears anywhere in the UI;
- no clearance value is displayed that does not correspond to a validated
  sample, proven by asserting every displayed value against `clearance.samples`;
- the disclosure is present in Plan and 3D whenever a movement is loaded.

### FM5 - Conversational Surface And Refusals

Tasks:

1. Parse "show me a forklift running this aisle" style intent into a motion
   request naming route and profile.
2. Require the exact published profile ID and revision; refuse otherwise, reusing
   the existing G2.2 refusal.
3. Add the Section 3.3 refusals in both imperative and interrogative form.
4. Attach the fixed `qualification` to every motion answer.
5. Never let Sage author poses, coordinates, speeds, or durations.

Exit gate:

- all Section 3.3 prompts refuse deterministically and mutate nothing;
- interrogative and imperative phrasings behave identically;
- a missing or stale profile refuses before any planner call;
- every motion answer carries the qualification;
- no answer states a throughput or safety conclusion.

### FM6 - Evaluation And Promotion

| Metric | Required |
|---|---:|
| Package byte-reproducibility from identical inputs | 100% |
| Pose count and distance match planner | 100% |
| Stale-revision playback refused | 100% |
| Layout mutation during playback | 0 |
| Carried placements restored on dispose | 100% |
| Unsupported throughput/safety/capacity claims | 0 |
| Model-authored pose, coordinate, or duration | 0 |
| Console or page errors during playback | 0 |
| Package build p95 (single movement, reference layout) | to be set in FM0 |
| Sustained playback frame rate, reference layout, desktop | to be set in FM0 |

Automatic failure conditions:

- any interaction model between vehicles;
- a v1 package accepted whose `layoutRevision` does not match, or a v2 package
  accepted whose recomputed `validationContextFingerprint` does not match;
- a client-side approximation of the swept envelope presented as validated;
- playback that writes to the draft or requires Save;
- smoothing that hides a real discontinuity in the planned path.

## 7. Milestones

Guard ownership is split by phase, because the two ceilings bind at different
moments:

| Phase | Owns |
|---|---|
| FM0 | measures both ceilings, freezes them, authors boundary and hostile fixtures - asserts nothing |
| FM1a | the **pre-allocation sample-count guard**, inside routing, before densification |
| FM1 | the **canonical-byte guard**, during serialization |

**Milestone 1 - Engine output is serializable.** FM0 -> FM1a -> FM1 -> FM2.
FM1a precedes FM1: the serializer cannot be the first line of defence against a
payload the planner already materialized.
Entirely server-side and unit-testable. No adapter changes. Zero collision with
in-flight facility work.

**Milestone 2 - It moves.** FM3.
First adapter change. See Section 9.

**Milestone 3 - It proves something.** FM4 -> FM5 -> FM6.

## 8. What Not To Do

1. Do not build a simulator. No vehicle-to-vehicle interaction, no queueing, no
   congestion, no stochastic events. **Release 1 supports exactly one active
   movement.** Two tracks playing at once implies an interaction model that does
   not exist. The moment two vehicles affect each other,
   every claim in Section 3.1 becomes unsupportable.
2. Do not smooth toward a live stream. The package is complete and precomputed;
   sample it exactly. Exponential smoothing is compensation for not knowing the
   future, and it would hide real discontinuities in the planned path.
3. Do not let playback create operations, receipts, or draft changes.
4. Do not reconstruct the swept envelope in the browser and present it as
   validated geometry.
5. Do not infer duration from anything but the planner's own estimate, and
   always label it an estimate.
6. Do not add a second layout store or cache the layout inside the package
   beyond the revision binding.

## 8a. Test Suites To Extend

Extend these; do not create parallel suites:

| Suite | Covers |
|---|---|
| `tests/test_facility_layout_routing.py` | FM1a planner changes, blocking evidence, swept geometry determinism |
| `tests/test_facility_layout_service.py` | package build and transport split |
| `tests/test_facility_layout_circulation.py` | `accepted` semantics preserved for existing consumers |
| `tests/test_facility_layout_agent_integration.py` | FM5 refusals, summary-only Sage payload |
| `tests/test_facility_layout_transport.js` | revision-bound package fetch |
| `tests/test_facility_layout_three_adapter.js` | frame-loop integration, generation guard, reparent restore |
| `tests/test_facility_layout_session.js` | playback never mutates the draft; Undo unaffected |

## 9. Sequencing Risk

`static/index.html` and `static/facility_layout_three_adapter.js` are both in
active use by concurrent facility-layout work. FM0-FM2 touch neither and can
proceed at any time. FM3 is the first adapter change and should be scheduled
into a quiet window, or taken on a branch that rebases onto the adapter rather
than merging against it.

## 10. Review Questions

Decided across revisions 2 and 3: swept geometry produced inside validation;
refusal replayability split into two classes; duration fields separated;
runtime state removed from the package while planner versions stay hashed;
package kept separate from the persisted route record; proxy vehicles permitted
but labelled and load-less; one active movement in release 1; clearance sampler
placed in `routing.py`; and full-revision invalidation for the implemented v1
package.

Decided in revision 4: reparenting with a five-field state snapshot; ceiling
measured in FM0 and enforced by failure not truncation; the persistent
drivability disclosure; the seven suites to extend; the frozen computational
epsilon and cross-platform GEOS requirement for the narrow gate; and
domain-separated `attemptFingerprint`.

Decided in revision 7: durable navigation authoring requires package schema v2
and one recomputed `validationContextFingerprint` validity gate. V1 retains
full-revision equality. The NAV1 amendment must pass before navigation intent is
writable.

Decided in revisions 5 and 6: every validated clearance sample is retained;
two fixed global ceilings rather than a length-scaling one; the two-mode
clearance display; and the pre-allocation sample guard with its own resource
refusal code and phase ownership.

Open:

1. Should `facility_route_sample_budget_exceeded` suggest a coarser
   `gridResolutionMeters` in its message, or would that invite callers to tune
   around a resource limit?
2. Does the FM4 clearance sampler need its own budget, or is the shared
   densified array sufficient given FM1a already bounded it?

## 11. Definition Of Done

A user can select an authored route and a published vehicle profile, watch the
planned traversal replayed in Plan and 3D at a published sample spacing, scrub
to a validated sample and read the clearance measured at that sample, and see
where a refused traversal stops and what blocks it - while a request whose
sample budget is exceeded is refused as a resource limit rather than presented
as a geometric verdict.

They cannot obtain a throughput, congestion, safety, drivability, or compliance
claim from any of it, and cannot obtain a clearance figure for a position that
was never validated. Nothing the user watches was authored by a model, and
nothing they watch changes the layout.
