# Facility Layout G2.2 Obstacle-Aware Circulation

Date: 2026-08-28

Status: Implemented and browser accepted

## Purpose

G2.2 extends the qualified Facility circulation path from route-to-route
separation to revision-bound static obstacle avoidance. Sage resolves the
user's semantic request. InspectorPro snapshots the authoritative layout
context, calculates route geometry, validates the result, and applies it only
to the active unsaved draft.

## Qualified behavior

- Inspect active-draft routes for exact geometric conflicts with static
  obstacle records.
- Recognize revision-bound placement footprints, authoritative equipment
  clearance envelopes, shell obstacles, protected floor markings, and
  protected or exclusion zones.
- Reroute one existing aisle around those obstacles while preserving its route
  ID, authored width, direction, source/via/target department bindings, and all
  department geometry.
- Apply an explicit nonnegative user-authored clearance exactly. If no
  clearance is supplied, claim geometric non-intersection only.
- Bind every result to a canonical obstacle-context revision and retain the
  obstacle IDs evaluated and avoided in route metadata.
- Require the exact ID and revision of a published vehicle profile before
  claiming vehicle-envelope or turning validation.
- Reuse the existing deterministic heading-lattice and swept-volume validator
  for published vehicle profiles; reject infeasible paths rather than relaxing
  a vehicle constraint.
- Keep the result as an unsaved revision-bound draft until explicit Save, with
  exact Undo to the saved base.

## Authority boundary

G2.2 does not invent or infer:

- OSHA, NFPA, fire-code, egress, accessibility, or company clearance values;
- equipment service clearances that are not bound to authoritative evidence;
- vehicle dimensions, turning radius, reverse policy, stopping distance, or
  operating speed;
- dynamic pedestrian, forklift, or material traffic behavior;
- travel-time, congestion, throughput, capacity, or optimality claims; or
- door, dock, or opening suitability beyond the static geometry represented in
  the bound source.

A request for whatever clearance the code requires is refused. A request to
validate turning without an exact published vehicle profile asks for that
profile instead of guessing.

The authority and coordinate guards run before ordinary circulation intent
classification. This keeps unsupported safety, policy, vehicle, and authored
coordinate requests on the deterministic refusal path even when the wording
does not contain a normal route-construction verb.

## Acceptance queries

Read-only analysis:

1. Does this aisle intersect any machines or restricted regions?
2. Which static obstacle blocks the route, and where?
3. Is the route geometrically clear of the current equipment footprints?

Obstacle-aware amendment:

1. Reroute that aisle around the Restricted Area with 1 m clearance.
2. Keep the route identity, width, and departments unchanged while avoiding the machine footprints.
3. Reroute around the authored keep-clear envelopes without moving equipment.

Published vehicle validation:

1. Reroute this forklift aisle using vehicle profile FLT-01 revision 4 and validate its turning envelope.
2. Keep reverse prohibited and report if no vehicle-valid route exists.

Fail-closed cases:

1. Use whatever regulatory clearance applies.
2. Make the route safe for any forklift.
3. Validate turning without a published vehicle profile and revision.
4. Move the aisle to model-authored coordinates.
5. Reroute after the obstacle-context revision or active draft has gone stale.

## Deterministic evidence

The final focused suites passed:

- 212 circulation, coordinator, API host, service-context, and Sage-integration
  tests;
- 125 shared operation, routing, spatial, and spatial-integration tests, with
  one existing skip; and
- 6 of 6 browser transport contract checks.

The production Playwright run proved this same-thread sequence against
`http://127.0.0.1:8141/`:

1. create a blank 120 m by 90 m facility with nine equal departments;
2. add a 4 m material aisle from Inbound to Dispatch;
3. ask whether the route intersects a machine or restricted region;
4. identify one exact conflict with the protected `Restricted Area` zone;
5. reroute the same aisle with 1 m user-authored clearance;
6. verify the route ID, width, department bindings, and all zone geometry are
   unchanged;
7. refuse `Make this aisle safe for any forklift.` without changing the draft;
8. refuse a typical-forklift turning claim without an exact published vehicle
   profile and revision;
9. refuse an unbound OSHA-clearance request without inventing a value;
10. refuse `Put the detour at x=40 m and z=25 m.` as chat-authored geometry;
11. verify all four refusals leave the accepted reroute byte-identical;
12. verify the saved layout remains byte-equivalent to the blank base; and
13. Undo the generated draft back to that blank base.

The accepted centerline changed from a direct route at Z 45 m to an orthogonal
detour at Z 27 m. With a 4 m corridor, the 1 m requested clearance expands the
protected boundary by 3 m; the detour is exactly tangent to that boundary and
does not enter it.

No browser page errors, console errors, failed requests, or HTTP 5xx responses
were recorded.

Post-review hardening also canonicalizes the pre-operation geometry before
computing preservation hashes and recognizes protected multiword labels such
as `Restricted Area` and `Keep Clear Area`. The browser exposes the mounted
Facility authoring app through a read-only `window` getter for inspection; the
lexical application state remains the only source of truth.

Evidence:

- `tests/fixtures/facility_layout/knowledge_foundation/g22-obstacle-aware-browser-evidence.json`
- `tests/fixtures/facility_layout/knowledge_foundation/g22-obstacle-aware-browser/01-obstacle-detected.png`
- `tests/fixtures/facility_layout/knowledge_foundation/g22-obstacle-aware-browser/02-obstacle-rerouted.png`
- `tests/fixtures/facility_layout/knowledge_foundation/g22-obstacle-aware-browser/03-authority-refused.png`

## Remaining circulation gates

G2.2 does not yet qualify dynamic traffic simulation, policy-derived regulatory
clearance, travel time, throughput, capacity, crossing controls, dead-end
policy, deducted aisle area, or facility-wide flow optimization. Those remain
separate evidence-bound gates under FLI-018 through FLI-021.
