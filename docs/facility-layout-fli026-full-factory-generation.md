# FLI-026 Full-Factory Generation

Status: qualified prototype capability

Date: 2026-08-28

## Outcome

Sage can now compile one complete, fully specified high-level factory request
into one validated, unsaved Facility Layout draft. The browser dispatches one
closed `generate_full_factory_draft` tool call. InspectorPro then executes the
existing qualified G1-G6 kernels through one durable ten-stage run.

The qualified browser case produced:

- a 120 m by 90 m facility with a 1 m grid;
- nine equal-area macro departments in three authored rows;
- two named semantic routes and one exact authored-size crossing;
- three child areas inside one named department;
- two exact-revision Assembly Workbench assets in the seed cell;
- a deterministic line/L/U comparison using an exact 1 m gap;
- two translated cell replicas with new stable identities;
- 12 zones, two routes, one floor marking, and six placements total; and
- one cumulative review draft bound to ten immutable stage receipts.

The final live turn completed in 44.752 seconds and the complete browser proof
in 47.272 seconds. The saved blank layout remained byte-identical. One Undo
cancelled the run and restored the exact blank base.

## Ownership Contract

Sage owns semantic intent only. It may provide:

- facility dimensions and source units;
- department and child-area labels, proportions, and row membership;
- route kinds, directions, named endpoints, and user-authored widths;
- crossing dimensions and the two route labels that establish its location;
- exact catalog display names, quantities, target areas, and semantic
  orientation;
- qualified cell-strategy candidates, objective, and authored spacing; and
- a source cell plus empty named replication targets.

Sage may not provide coordinates, route points, transforms, asset IDs,
revisions, inferred clearance, regulatory values, approval, or release
authority. Unknown fields and model-authored geometry fail closed.

InspectorPro owns:

- exact unit normalization and G1 partition geometry;
- route geometry and crossing-point derivation;
- child-area geometry and hierarchy;
- exact catalog identity and revision resolution;
- fit, collision, cell-strategy, and replica geometry;
- deterministic validation and receipt generation; and
- Save, Undo, stale-revision, lease, and supersession behavior.

Equivalent explicit-row encodings normalize at the semantic adapter. Explicit
row membership governs over the generic `rows` grid mode, while incomplete,
duplicated, contradictory, or unknown row membership still fails closed.

## Durable Stages

1. `facility_envelope`
2. `macro_departments`
3. `primary_circulation`
4. `department_subdivisions`
5. `department_resources`
6. `seed_cells`
7. `repeated_modules`
8. `floor_communication`
9. `deterministic_validation`
10. `review_and_save`

Stage inputs are persisted with the run before execution. Each stage can be
continued after coordinator reconstruction without replaying completed work.
Stages with no requested work issue a bounded cancelled receipt rather than
inventing content. A completed run exposes one cumulative diff hash and remains
unsaved until the user issues an explicit Save command.

## Bounds

The full-factory contract is intentionally bounded:

- 24 routes;
- 24 crossings;
- 24 subdivision requests;
- 100 asset-placement requests;
- 480 total requested assets;
- 200 total child areas; and
- the existing G1 limit of 50 macro departments.

Every individual operation batch remains subject to the 500-operation kernel
cap. Larger factories and automatic substage splitting remain production-
hardening work.

## Verification

Automated release results:

| Surface | Result |
|---|---:|
| Composed G1-G6 backend and skill regression | 151 passed |
| Facility Sage agent integration | 163 passed |
| Facility workspace static contracts | 70/70 passed |
| Facility session contracts | 48/48 passed |
| Facility transport contracts | 7/7 passed |
| Live FLI-026 browser assertions | 15/15 passed |

The browser proof confirms one successful Sage stream, one full-factory start,
ten successful continuation requests, one successful Undo request, no failed
HTTP responses, no page errors, and no console errors.

Evidence:

- `tests/fixtures/facility_layout/knowledge_foundation/fli026-full-factory-browser-evidence.json`
- `tests/fixtures/facility_layout/knowledge_foundation/fli026-full-factory-browser/01-blank-before.png`
- `tests/fixtures/facility_layout/knowledge_foundation/fli026-full-factory-browser/02-complete-unsaved-factory.png`
- `tests/fixtures/facility_layout/knowledge_foundation/fli026-full-factory-browser/03-one-undo-blank.png`

## Qualification Boundary

This gate qualifies composition of the already qualified G1-G6 prototype
capabilities. It does not qualify:

- inferred regulatory, safety, egress, fire, accessibility, or vehicle values;
- throughput, staffing, travel-time, capacity, or operational-optimality claims;
- irregular envelopes, cut-outs, or non-rectangular partition solving;
- automatic process-derived department sizing or adjacency optimization;
- occupied-target replacement, rotated/scaled/mirrored cell replication;
- model-selected catalog identities without an exact display-name match;
- automatic Save, approval, controlled release, or human authority; or
- large-layout substage splitting, multi-process scale, performance, memory,
  and 2D/3D theme-parity qualification.

Those remain separate backlog items and must not be implied by a successful
FLI-026 draft.
