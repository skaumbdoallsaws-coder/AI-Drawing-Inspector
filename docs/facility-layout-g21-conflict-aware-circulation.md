# Facility Layout G2.1 Conflict-Aware Circulation

Date: 2026-08-27

Status: Implemented and browser accepted

## Purpose

G2.1 extends the qualified G2 circulation path with exact mixed-traffic
conflict analysis and deterministic route separation. Sage continues to own
semantic intent only. The Facility kernel owns route geometry, candidate
generation, comparison, validation, revision binding, Save, and Undo.

## Qualified behavior

- Detect pedestrian/material corridor overlap, point crossings, and shared
  centerline segments from the active draft.
- Report route labels, route kinds, conflict type, derived location, shared
  length, and overlap area without claiming safety or compliance.
- Resolve conflicts while preserving route IDs, authored route widths,
  source/via/target department bindings, and department geometry.
- Compare two deterministic alternatives: reroute pedestrian traffic or
  reroute material traffic.
- Select the feasible alternative with the shorter total centerline unless
  the user explicitly identifies the route class to adjust.
- Apply no additional clearance when none is supplied. This establishes
  geometric non-overlap only.
- Apply an explicit user-authored separation exactly when one is supplied.
- Keep the result as an unsaved revision-bound draft until Save.

## Authority boundary

G2.1 never interprets geometric separation as:

- an OSHA, NFPA, fire-code, egress, or accessibility requirement;
- adequate forklift turning or stopping clearance;
- traffic capacity or throughput;
- safe visibility at a crossing; or
- an operationally optimal route.

A request to use whatever a regulation requires is refused until an authored
policy is connected. Candidate ranking is qualified as a geometric length
comparison only.

## Acceptance queries

Read-only analysis:

1. Where do the pedestrian and forklift routes conflict?
2. Do any mixed-traffic routes share a segment?
3. Are there corridor overlaps even where the centerlines do not cross?
4. Which route pair crosses, and where is the crossing?
5. Are the current pedestrian and material routes geometrically separated?

Automatic deterministic comparison:

1. Separate the forklift lane and pedestrian walkway without changing the departments.
2. Resolve the mixed-traffic overlap while preserving route widths and endpoints.
3. Remove the route conflict, compare both rerouting options, and keep the shorter feasible result.

Explicit adjustment intent:

1. Reroute the pedestrian walkway and keep the forklift lane fixed.
2. Move the forklift route and keep the pedestrian walkway fixed.
3. Resolve the overlap with 1.5 m between the routes without moving departments.
4. Keep 4 ft between the routes and reroute pedestrian traffic only.

Fail-closed cases:

1. Resolve the crossing using whatever OSHA clearance applies.
2. Make the routes code compliant without changing anything else.
3. Put the pedestrian detour at x=40 and z=25.
4. Resolve the conflict after the active draft revision has changed.
5. Resolve a conflict when fewer than two generated routes exist.

## Deterministic evidence

The focused circulation, generation coordinator, host, runtime, and Sage
integration suites are the release gate. Browser evidence must prove the full
same-thread sequence:

1. generate departments;
2. add a forklift route;
3. add a pedestrian route;
4. ask where they conflict;
5. resolve the conflict;
6. confirm zero mixed-traffic geometric conflicts;
7. Undo to the unchanged saved base.

The 2026-08-27 Playwright acceptance run passed all checks against the live app:

- one 75 m shared pedestrian/material centerline segment was detected;
- the user-authored 1.5 m separation was achieved exactly;
- only the pedestrian route geometry changed;
- both route IDs, widths, directions, and department bindings were preserved;
- department geometry remained byte-identical;
- the saved base remained unchanged and one Undo restored it exactly;
- all six streamed chat turns returned HTTP 200; and
- no page, console, failed-response, or interruption errors occurred.

Evidence:

- `tests/fixtures/facility_layout/knowledge_foundation/g21-conflict-resolution-browser-evidence.json`
- `tests/fixtures/facility_layout/knowledge_foundation/g21-conflict-resolution-browser/01-conflict-located.png`
- `tests/fixtures/facility_layout/knowledge_foundation/g21-conflict-resolution-browser/02-conflict-resolved.png`

## Successor gate

Static obstacle avoidance moved to the separately qualified G2.2 gate. It now
routes around revision-bound machine footprints, authoritative keep-clear
envelopes, shell obstacles, protected markings, and restricted zones. Exact
published vehicle-profile revisions can invoke the existing heading-lattice
and swept-volume validator. See
`docs/facility-layout-g22-obstacle-aware-circulation.md`.

Dynamic traffic, inferred or regulatory clearance, travel time, throughput,
crossing controls, dead-end policy, deducted aisle area, and facility-wide flow
optimization remain separate evidence-bound gates under FLI-018 through
FLI-021.
