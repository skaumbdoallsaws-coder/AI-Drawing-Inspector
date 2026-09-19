# Facility Navigation NAV0 Baseline Report

Date: 2026-08-31

Status: **IMPLEMENTED / PROMOTION HOLDS OPEN**

NAV0 freezes the current navigation evidence, geometry contract, reference
complexity, and routing-algorithm decision. It does not approve operator work
cycles, vehicle routes, staffing, timing, safety, clearance, throughput, or
regulatory compliance.

## Verdict

The NAV0 implementation is complete and its local verification is green. The
reference-scale pedestrian algorithm is frozen to
`triangulated_navmesh_astar_funnel` because a full visibility graph exceeds
the pre-allocation resource ceiling on the archived Automation scope.

NAV0 is not promoted yet. Two deliberate holds remain:

1. Shadrack must explicitly review or replace the 12 operator-cycle, four
   vehicle-path, and seven handoff candidates.
2. The frozen geometry fixture must produce byte-identical fingerprints on
   one pinned Linux runner using the declared Shapely/GEOS versions.

Neither hold is represented as a pass, and no generator or test grants human
authority automatically.

## Frozen Source

| Item | Value |
| --- | --- |
| Reference layout | `fl-reference-manual-20260812` |
| Layout revision | `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088` |
| Reference manifest revision | `95f233aecbfd26e2fa4e36784d2bc7c6009ed83e0e622346c82b1da5448b7fab` |
| NAV0 baseline revision | `4a107b2abb3cc609b15d434da27a253e13fcfec7d166bebcdc06db732c36f5b4` |
| Geometry fixture revision | `28349b3edae2d31839f740d8deca234eeb21ff37a63e777b66f88dfed8dc7fe4` |

The build script hashes the archived layout before and after generation and
fails if it changes. The source archive remained byte-identical.

## Candidate Review

| Candidate class | Count | State |
| --- | ---: | --- |
| Existing operator placements available | 20 | Inventoried |
| Existing operator cycles selected | 12 | Derived / pending |
| Existing vehicle paths selected | 4 | Derived / pending |
| Material handoffs | 7 | Derived / pending |

All selected actors are existing placement IDs. The legacy operator loops are
captured only as failure evidence. Every operator candidate records
`service_side_not_authored`, `station_visit_order_not_authored`, and
`legacy_rectangle_path_not_gold`.

All four vehicle candidates still require exact published vehicle profiles.
Two also lack directional lane markings. Every handoff still lacks authored
FIFO identity, participant assignment, sequence, and timing. The review
receipt therefore remains `pending`, with `approvalRequested: false` and no
approved IDs.

## Geometry Contract

The deterministic geometry implementation freezes:

- six-decimal canonical coordinates and stable obstacle ordering;
- source union, secant-corrected round expansion, and post-expansion union;
- `quad_segs = 16`, round cap/join styles, and mitre limit `5.0`;
- counterclockwise exteriors, clockwise holes, and lexicographic ring starts;
- polygon ordering by first vertex, area, and retained source identity;
- deterministic duplicate/collinear removal and fail-closed invalid results;
- a `5,000,000` visibility candidate-pair ceiling checked before edge
  allocation.

The secant correction and numeric epsilon are computational geometry controls.
They are not engineering clearance or a safety allowance.

The Windows receipt passes all three frozen cases with Python 3.14.0, Shapely
2.1.2, and GEOS 3.13.1. Each receipt binds expanded geometry, free-space,
visibility-graph, accepted-centerline, and route fingerprints. A Linux runtime
was not available on this host, so `promotionStatus` correctly remains
`pending_linux_receipt`.

Seven additional synthetic cases freeze the future behavior surface:
free-space routing, disconnected space, blocked service side, ordered
multi-stop loops, paired directional lanes, vehicle turnarounds, and
unreachable handoffs. They are deterministic test inputs, not factory-policy
evidence.

## Reference Complexity

The gold performance scope is `Automation + Robot cells`:

| Metric | Result |
| --- | ---: |
| Source placements / obstacle records | 492 |
| Wire-mesh guard panels | 456 |
| Pre-expansion source-union polygons | 480 |
| Pre-expansion source-union vertices | 1,920 |
| Expanded polygons | 36 |
| Expanded vertices | 5,808 |
| Visibility nodes | 5,814 |
| Projected visibility pairs | 16,898,391 |
| Frozen pair ceiling | 5,000,000 |
| Navmesh triangles | 5,882 |
| Navmesh adjacency edges | 5,917 |
| Navmesh graph bytes | 930,988 |

The union step is essential but does not make the reference visibility graph
tractable: round obstacle expansion reduces polygon count while increasing the
canonical boundary vertex count. The implementation refuses the projected
visibility graph before allocating its 16.9 million candidate pairs. This is a
resource refusal, not evidence that the route is geometrically impossible.

## Performance

The frozen machine is the Dell 15 DC15250 running Windows 11 build 26200 with
an Intel Core i7-1355U, 10 physical cores, 12 logical processors, and 16.8 GB
RAM. Each metric uses 20 measured runs after one discarded warmup; p95 uses
nearest rank.

| Gate | p95 | Limit | Result |
| --- | ---: | ---: | --- |
| Automation geometry compile | 2,798.3934 ms | 5,000 ms | Pass |
| Full cold navigation snapshot compile | 3,314.6946 ms | 5,000 ms | Pass |
| Visibility preflight | 27.8727 ms | 5,000 ms | Resource-refused as designed |
| Navmesh cold build + query | 1,969.2383 ms | 5,000 ms | Pass |
| Navmesh warm query | 971.0377 ms | 1,500 ms | Pass |

The selected reference-scale algorithm is therefore
`triangulated_navmesh_astar_funnel`. The visibility-graph implementation
remains available for small scopes that pass the pre-allocation ceiling.

## Verification

- NAV0 contract and fixture tests: **9 passed**.
- Adjacent circulation, routing, motion-package, activity, lean-motion, and
  reference-generation tests: **84 passed**.
- Python compilation: passed for the two new navigation modules, builder, and
  tests.
- Reference archive hash after all generation and tests: unchanged.

The only observed test warning is the existing pytest cache-path warning. It
does not affect test results.

## Artifacts

- `ai_inspector/facility_layout/navigation_geometry.py`
- `ai_inspector/facility_layout/navigation_baseline.py`
- `tools/build_facility_navigation_nav0.py`
- `tests/test_facility_layout_navigation_nav0.py`
- `tests/fixtures/facility_layout/navigation/nav0-reference-baseline-v1.json`
- `tests/fixtures/facility_layout/navigation/nav0-reference-review-v1.json`
- `tests/fixtures/facility_layout/navigation/nav0-geometry-cross-platform-v1.json`
- `tests/fixtures/facility_layout/navigation/nav0-performance-v1.json`
- `tests/fixtures/facility_layout/navigation/nav0-routing-cases-v1.json`
- `tests/fixtures/facility_layout/navigation/nav0-visual-evidence-v1.json`
- `tests/fixtures/facility_layout/navigation/browser/01-operator-path-candidates-plan.png`
- `tests/fixtures/facility_layout/navigation/browser/02-operator-path-candidates-3d.png`
- `tests/fixtures/facility_layout/navigation/browser/03-vehicle-path-candidates-plan.png`
- `tests/fixtures/facility_layout/navigation/browser/04-vehicle-path-candidates-3d.png`

## Next Gate

NAV1 may implement contracts, authority mapping, and motion-package schema v2.
Writable `extensions.facilityNavigation` remains disabled until the narrower
`validationContextFingerprint` gate is available. NAV2 authoring must not ship
until the Linux geometry receipt and explicit product-owner review close the
two NAV0 promotion holds.
