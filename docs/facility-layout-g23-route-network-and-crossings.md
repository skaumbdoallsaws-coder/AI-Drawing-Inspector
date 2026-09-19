# Facility Layout G2.3 Route Network And Crossings

Date: 2026-08-28

Status: Implemented and production-browser accepted

## Purpose

G2.3 extends the qualified Facility circulation path from individual route
geometry to a deterministic route-network view. Sage resolves a semantic
question or amendment. InspectorPro owns graph construction, reachability,
crossing geometry, floor-marking placement, validation, receipt supersession,
and Undo.

## Qualified behavior

- Build a directed department graph from authored route-to-department
  bindings and each route's one-way or two-way direction.
- Report connected components, unconnected departments, topological dead ends,
  directional reachability, and the exact bound route path between two named
  departments.
- Filter reachability by material, forklift, or pedestrian route kind when the
  user names one.
- Derive exact route-centerline intersections and distinguish point crossings
  from shared segments.
- Report whether each mixed pedestrian/material point crossing is covered by
  an authored crosswalk floor marking.
- Add one crosswalk only when exactly one eligible unmarked point crossing is
  resolved and the user supplies explicit width and depth with units.
- Derive the marking position and orientation from route geometry; the model
  never supplies coordinates.
- Reroute the most recent generated aisle through named departments while
  preserving its stable route ID and every unaffected route and department.
- Rebuild amendments in the existing durable generation run, supersede prior
  receipts, preserve prior crossing requests, and keep the saved layout
  unchanged until explicit Save.

## Authority boundary

G2.3 proves route-graph and static-marking facts only. It does not establish:

- traffic safety, crossing adequacy, visibility, or regulatory compliance;
- route capacity, congestion, throughput, travel time, or stopping distance;
- operational optimality or a preferred facility design;
- whether a topological dead end is acceptable or defective;
- vehicle suitability without the exact published vehicle-profile authority;
  or
- any crosswalk dimension, clearance, or policy value the user did not supply.

Requests for safe, compliant, adequate, or optimal circulation are refused
unless the applicable controlled evidence is connected. Ambiguous crossings
ask the user to name both routes. Missing crossing dimensions ask for exact
values. Chat-authored coordinates remain forbidden.

## Acceptance queries

Read-only network analysis:

1. Can material travel from Inbound to Dispatch?
2. Which departments are unreachable from Receiving?
3. Which departments are topological dead ends?
4. How many connected route-network components are present?
5. Which mixed-traffic point crossings are unmarked?

Bounded amendments:

1. Add a 4 m by 3 m pedestrian crossing at the route intersection.
2. Reroute that aisle through Fabrication and keep everything else unchanged.
3. Send that walkway through Center instead.

Fail-closed cases:

1. Make this a safe crossing.
2. Add whatever crosswalk dimensions the code requires.
3. Mark the crossing when more than one eligible point crossing exists.
4. Put the crossing at x=40 m and z=25 m.
5. Claim the route network has enough traffic capacity.

## Deterministic evidence

The implementation adds focused coverage for parsing, direction-aware graph
analysis, crossing coverage, exact marking dimensions, coordinate ownership,
route and zone preservation, local route amendment, durable-run replay, tool
canonicalization, direct Sage answers, and unsupported-authority refusal.

Current automated results:

- 234 focused circulation, coordinator, Sage-integration, service, and host
  tests passed;
- 125 shared operation, routing, spatial, and spatial-integration tests passed,
  with one existing opt-in performance benchmark skipped;
- 32 knowledge-foundation and tool-knowledge contract tests passed;
- 6 of 6 browser transport contract checks passed; and
- 70 of 70 Facility workspace checks passed; and
- 48 of 48 Facility session checks passed.

Production Playwright acceptance completed against the restarted application at
`http://127.0.0.1:8141/`. One same-thread run proved:

- a 120 m by 90 m, nine-department draft with two intersecting routes;
- material reachability from Inbound to Dispatch across the exact bound route;
- one of one mixed-traffic point crossings initially unmarked;
- one exact 4 m by 3 m crosswalk placed at the derived centerline intersection;
- zero of one mixed-traffic point crossings unmarked after placement;
- a semantic walkway amendment through Center with stable route ID, route
  dimensions, marking ID, marking geometry, route bindings, and department
  geometry;
- refreshed marking provenance after the bound route revision changed;
- an evidence-bound refusal for `Make this a safe crossing.`;
- no page, console, failed-request, or server errors;
- no change to the saved layout; and
- one Undo restoring the exact blank base draft.

Machine-readable evidence:

`tests/fixtures/facility_layout/knowledge_foundation/g23-route-network-browser-evidence.json`

Screenshots:

1. `tests/fixtures/facility_layout/knowledge_foundation/g23-route-network-browser/01-unmarked-network-crossing.png`
2. `tests/fixtures/facility_layout/knowledge_foundation/g23-route-network-browser/02-authored-crosswalk-marked.png`
3. `tests/fixtures/facility_layout/knowledge_foundation/g23-route-network-browser/03-network-edit-and-authority-boundary.png`

### Interrogative authority refusal retest

An independent review found that imperative safety and compliance requests
failed closed, while equivalent questions could reach read-only analysis or the
model. The deterministic guard now covers subject-first and policy-conformance
questions. Production-browser acceptance verifies all five review phrasings:

1. `Is this network safe?`
2. `Is this crossing safe for pedestrians?`
3. `Is this aisle layout adequate?`
4. `Is this route network compliant with fire code?`
5. `Does this layout meet OSHA egress requirements?`

Each turn returned
`facility_circulation_operational_authority_missing`, made no tool call or
provider-dependent claim, and left both draft and saved layout state unchanged.
The browser run recorded no page, console, failed-request, or server errors.

Machine-readable retest evidence:

`tests/fixtures/facility_layout/knowledge_foundation/g23-authority-question-browser-evidence.json`

Screenshot:

`tests/fixtures/facility_layout/knowledge_foundation/g23-route-network-browser/04-interrogative-authority-refusals.png`

## Remaining circulation gates

G2.3 does not qualify dynamic traffic simulation, policy-derived regulatory
clearance, travel-time or throughput optimization, route capacity, crossing
signal/control design, dead-end policy, deducted aisle area, or facility-wide
flow optimization. Those remain evidence-bound follow-on gates under FLI-018
through FLI-021.
