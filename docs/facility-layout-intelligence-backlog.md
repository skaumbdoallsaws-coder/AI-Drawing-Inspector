# Facility Layout Intelligence Backlog

Date: 2026-08-29

Status: Post-G6 planning backlog; qualified items are identified explicitly

## Purpose

This backlog records Facility Layout capabilities that are valuable but are not
part of the currently qualified G1.1 production path. It prevents future
requirements from being mistaken for behavior that Sage can already execute.

Every item must preserve the existing ownership boundary:

```text
user intent
  -> Sage resolves semantic constraints
  -> deterministic InspectorPro tools calculate geometry
  -> validators prove the result
  -> the user reviews one unsaved cumulative draft
  -> Save requires explicit approval
```

Sage must not calculate coordinates, imitate pointer events, invent policy, or
silently choose among conflicting interpretations.

## Qualified G1.1 Baseline

The current prototype path supports:

- one rectangular facility envelope with supported dimensions and units;
- 1 through 50 explicitly labelled macro departments;
- equal-area partitioning;
- complete named department percentages;
- authored row proportions;
- any valid number of north-to-south rows;
- explicit department membership and west-to-east order within each row;
- deterministic containment, overlap, area, and identity validation;
- stable semantic zone IDs while an existing generated draft is reshaped;
- replacement of a same-scope unsaved generated draft;
- an unchanged saved layout until explicit Save; and
- exact Undo to the saved base.

## Qualified G2 Circulation Baseline

The current explicit-prototype path also supports:

- material, forklift, and pedestrian routes on an active generated department
  draft;
- exact user-authored route width and source-unit provenance;
- named source, target, and ordered through-departments;
- deterministic orthogonal route geometry and corridor containment;
- one-way or two-way direction, with a disclosed two-way default;
- explicit overlay area accounting without changing department areas;
- additional generated routes and same-route width follow-ups;
- active-draft connectivity questions;
- stable route identity and department bindings across follow-ups;
- exact conflict detection against revision-bound placement footprints,
  authoritative equipment clearance envelopes, shell obstacles, protected
  floor markings, and protected or exclusion zones;
- deterministic obstacle-aware rerouting with exact user-authored clearance;
- exact published vehicle-profile revision binding before vehicle-envelope or
  turning validation;
- direction-aware department reachability, connected components, unconnected
  departments, and topological dead-end reporting from route bindings;
- exact mixed pedestrian/material point-crossing derivation and authored
  crosswalk-coverage reporting;
- exact user-dimensioned crosswalk creation at one unambiguous derived route
  intersection, without a safety or compliance claim;
- semantic rerouting of one generated aisle through named departments while
  preserving route identity and unaffected geometry;
- fail-closed handling when regulatory clearance or vehicle authority is
  missing;
- no draft change for clarifications, refusals, and read-only analysis; and
- unchanged saved state until explicit Save, with exact Undo.

The current path does not qualify irregular envelopes, adjacency solving,
minimum-area constraints, partial allocation rules, optimized or policy-bound
circulation, reusable cell modules, or dependency-aware local reflow.

## Qualified Rollout G3 Subdivision Baseline

Backlog item `FLI-022` is now qualified for the explicit prototype path. Sage can
divide one uniquely named rectangular department or existing child area into
explicitly labelled children using equal area, complete proportions, columns,
deterministic grids, or authored row stacks. InspectorPro owns the coordinates,
preserves the parent and unrelated geometry byte for byte, validates hierarchy,
containment, overlap, and exact area closure, and retains the result as an
unsaved cumulative draft with exact Undo.

This does not qualify irregular parents, inferred operational requirements,
equipment placement, access clearances, cell-strategy selection, or local
dependency-aware reflow. See
`docs/facility-layout-g3-department-subdivisions.md`.

## Permanent Non-Goals And Safety Boundaries

These are controls, not future feature requests:

- accepting model-authored coordinates as authoritative geometry;
- treating a request to build as approval to Save;
- inventing fire, life-safety, accessibility, or equipment clearances;
- generating pointer events to imitate manual ribbon operations;
- silently normalizing conflicting percentages or missing constraints;
- deleting referenced entities or dependent evidence without disposition; and
- allowing a model or browser payload to grant approval authority.

## Backlog

### G2. Richer Macro-Planning Intent

| ID | Capability | Required deterministic behavior | Minimum exit evidence |
|---|---|---|---|
| FLI-001 | Standalone envelope authoring | Create or resize an envelope without inventing departments; preserve source-unit provenance. | Unit, API, and browser tests for valid, missing-unit, and out-of-bound requests. |
| FLI-002 | Extended label grammar | Support newline lists, quoted labels, labels containing `and`, and explicitly requested numeric ranges without changing authored spelling. | Held-out label corpus and exact identity tests. |
| FLI-003 | Partial area allocation | Resolve instructions such as one named share plus an equal split of the remainder. Reject under-allocation unless the user explicitly names unallocated space. | Property tests proving exact closure and no residual geometry. |
| FLI-004 | Relative area constraints | Support `twice`, `half`, minimum, and maximum area only through a deterministic constraint compiler. | Feasible and infeasible fixtures with named conflicts. |
| FLI-005 | Bands and directional flow | Compile north/south bands and west/east sequences while using the authoritative coordinate frame. | Orientation, ordering, shared-edge, and frame-binding tests. |
| FLI-006 | Adjacency and separation | Satisfy required shared-edge adjacency and non-adjacency; a shared corner must not count. | Solver fixtures with deterministic proof or a specific unsatisfied constraint. |
| FLI-007 | Clarification contract | Return structured clarification reasons for duplicate labels, count mismatch, incomplete proportions, and contradictory constraints. | Stable error codes plus user-facing response tests; no draft may be created. |

### G3. Irregular Facility Geometry

| ID | Capability | Required deterministic behavior | Minimum exit evidence |
|---|---|---|---|
| FLI-008 | Supported polygon envelopes | Accept authored polygonal boundaries through a deterministic schema, not model-generated points. | Polygon validity, winding, bounds, and round-trip tests. |
| FLI-009 | Cut-outs and prohibited regions | Represent columns, voids, courtyards, and unavailable corners as explicit exclusions. | Usable-area accounting and zero-intrusion validation. |
| FLI-010 | Non-rectangular department partitioning | Partition usable polygon area without crossing exclusions or fabricating unusable residual strips. | Exact area, containment, overlap, and topology fixtures. |

### G4. Incremental Editing And Dependency-Aware Reflow

| ID | Capability | Required deterministic behavior | Minimum exit evidence |
|---|---|---|---|
| FLI-011 | Rename without recreation | Change a label while preserving zone identity and geometry. | Byte-stable boundary and stable-ID test. |
| FLI-012 | Add and insert a department | Insert a named department at an authored relationship and reflow only the affected scope. | Locality proof and adjacency validation. |
| FLI-013 | Resize selected departments | Apply absolute or relative area changes and disclose which constraints no longer hold. | Before/after dependency and area-closure receipts. |
| FLI-014 | Locked geometry | Preserve explicitly locked zones and report infeasibility instead of moving them. | Lock integrity and impossible-request fixtures. |
| FLI-015 | Safe deletion | Delete only unreferenced zones; name routes, bindings, cells, or records that block deletion. | Reference-integrity tests and no cascading implicit deletion. |
| FLI-016 | Localized deterministic reflow | Recompute the smallest valid dependency region instead of repartitioning the whole facility. | Unaffected-region byte-parity tests. |
| FLI-017 | Cumulative Undo and supersession | Restore the exact prior state across split substages and retain immutable superseded receipts. | Restart, remount, Undo, and receipt-chain browser evidence. |

### G5. Circulation And Operational Space

The failing pre-implementation browser baseline is recorded in
`docs/facility-layout-circulation-intent-baseline.md`. It proves revision safety
but also proves that current generic route tools read the saved reference layout
instead of the active unsaved generated draft.

That baseline failure is closed for the qualified G2 slice. `FLI-018` is
qualified only for explicit overlay widths; deducted-area allocation remains
open. `FLI-019` is qualified for semantic department bindings, deterministic
orthogonal geometry, exact widths, connectivity reads, static mixed-traffic
conflict detection, deterministic geometric separation, and revision-bound
static obstacle avoidance. G2.1 compares pedestrian-route and material-route
alternatives by total centerline length but makes no operational-optimality
claim. G2.2 applies explicit user-authored clearance and can validate an exact
published vehicle-profile revision through the existing heading-lattice and
swept-volume kernel. Dynamic traffic, inferred or regulatory clearance,
travel time, throughput, capacity, dead-end policy, deducted aisle area, and
broader route optimization remain open. G2.3 additionally qualifies
deterministic route-network reachability, components, topological dead ends,
exact mixed-traffic point intersections, authored crosswalk coverage, and
local semantic route amendments. It does not promote those static facts into
safety, adequacy, capacity, or optimality claims. See
`docs/facility-layout-g2-circulation-report.md`,
`docs/facility-layout-g21-conflict-aware-circulation.md`, and
`docs/facility-layout-g22-obstacle-aware-circulation.md`, and
`docs/facility-layout-g23-route-network-and-crossings.md`.

| ID | Capability | Required deterministic behavior | Minimum exit evidence |
|---|---|---|---|
| FLI-018 | Authored aisle allocation | Add aisles only from explicit dimensions or approved company policy and identify whether their area is gross or deducted from departments. | Area-accounting and provenance tests. |
| FLI-019 | Route connectivity | Generate material, pedestrian, and service routes with deterministic connectivity and width validation. | Reachability, crossing, width, and dead-end fixtures. |
| FLI-020 | Clearance envelopes | Apply equipment and access clearances only from bound evidence. | Source-bound clearance and missing-policy rejection tests. |
| FLI-021 | Flow-aware department placement | Evaluate authored process precedence and travel relationships without claiming unsupported design intent. | Flow metrics, alternative comparison, and provenance receipts. |

### G6. Nested Areas, Cells, And Assets

`FLI-025` is now qualified for the explicit prototype path. Sage can name one
qualified G5 source cell and one or more empty target areas; InspectorPro then
creates new stable identities while preserving exact asset revisions, relative
geometry, orientation, internal relationships, upstream Facility state, and
the single cumulative Save/Undo boundary. Read-only conformance reports later
drift without overwriting it. This does not qualify rotation, scaling,
mirroring, automatic family synchronization, occupied-target replacement, or
process, safety, capacity, and compliance equivalence. See
`docs/facility-layout-g6-reusable-cell-modules.md`.

| ID | Capability | Required deterministic behavior | Minimum exit evidence |
|---|---|---|---|
| FLI-022 | Nested department subdivisions | **Qualified in rollout G3.** Create child zones while preserving hierarchy and parent containment. | Passed hierarchy, exact-area, preservation, API, browser, Save, and Undo gates. |
| FLI-023 | Asset placement and orientation | **Qualified in rollout G4 for exact-revision physical placement.** Use authoritative footprints, semantic orientation, and evidence-bound service/access requirements; unsupported clearance remains explicitly unverified. | Passed fit, containment, collision, stale-asset, hierarchy-preservation, API, browser, and Undo gates. |
| FLI-024 | Manufacturing-cell feasibility | **Qualified in rollout G5 for exact G4 resources.** Compare and compose line, L, U, grid, parallel, serpentine, loop, spine, herringbone, and cluster strategies using deterministic geometry, explicit objectives, and evidence-bound spacing. | Passed every-strategy, rejected-fit, authority, preservation, durable-run, API, browser, Save, and Undo gates. |
| FLI-025 | Reusable modules and patterns | **Qualified in rollout G6 for exact translation of qualified G5 cells into empty target areas.** Preserve revisions, relative geometry, relationships, source state, upstream layout state, and explicit prototype authority. | Passed identity, provenance, drift, fit, API, Sage, browser, refusal, Save-state, and Undo gates. |
| FLI-026 | Full-factory generation | **Qualified for one complete, fully specified prototype intent composed through the existing G1-G6 kernels.** Resolve exact assets server-side, execute one durable ten-stage run, retain one cumulative unsaved review diff, and never infer geometry or authority. | Passed closed-schema, restart, stage-composition, exact-asset, validation, agent, full-browser, saved-state, and one-Undo gates. |

## Qualified Rollout FLI-026 Full-Factory Generation

Sage can now turn one complete semantic request into one full unsaved factory
draft. The qualified path composes the envelope, macro departments, routes,
crossings, child areas, exact-revision assets, one qualified seed-cell strategy,
and translated replicas through ten durable stages. InspectorPro owns every
coordinate and validates each existing G1-G6 contract before exposing one
cumulative Save decision.

The live gate produced 12 zones, two routes, one crossing, and six exact assets
from one Sage request in 47.272 seconds total. The saved blank layout remained
unchanged and one Undo restored its exact bytes. This qualification does not
add safety, compliance, capacity, clearance, process-sizing, or operational-
optimality authority. See
`docs/facility-layout-fli026-full-factory-generation.md`.

## Qualified G7 Production Hardening

`FLI-027` through `FLI-030` are qualified for the explicit prototype path.
Durable runs resume after process reconstruction, cross-process writer leases
fail closed, oversized stages split into restart-safe batches under both
500-item caps, and one exact world revision is proven across Plan/3D,
light/dark, and desktop/mobile surfaces.

`FLI-031` passes the current-machine engineering gate: 20 measured full-factory
cycles remain within frozen latency, heap, RSS, pending-load, canvas, and render
cleanup budgets, and the accelerated persistence soak passes. Controlled
release remains blocked because the new source-bound campaign has not completed
the literal 14-day elapsed-soak requirement. See
`docs/facility-layout-g7-production-hardening.md`.

### G7. Production Hardening

| ID | Capability | Required deterministic behavior | Minimum exit evidence |
|---|---|---|---|
| FLI-027 | Durable restart and resume | **Qualified.** Recover the exact active stage without replaying completed stages. | Passed repository restart, stage-journal recovery, and interrupted-save fixtures. |
| FLI-028 | Cross-process writer exclusion | **Qualified.** Allow one writable run per layout/base revision while retaining read-only previews. | Passed multi-process lease, stale-lock recovery, and compare-and-swap tests. |
| FLI-029 | Large-layout substage splitting | **Qualified.** Keep every operation and planned-instance batch within 500 while preserving one cumulative review diff. | Passed 1,201-operation restart and operation-501 failure-injection fixtures. |
| FLI-030 | 2D/3D and theme parity | **Qualified.** Prove that Plan and 3D views represent the same world state in light and dark themes. | Passed eight browser surfaces, scene assertions, camera interaction, and nonblank pixel checks. |
| FLI-031 | Performance and memory qualification | **Engineering-qualified; controlled release pending elapsed soak.** Establish bounded latency, heap, RSS, and cleanup for repeated full generation and reflow. | Passed machine-bound numeric budgets and accelerated soak; literal 14-day campaign remains open. |

## Agent Architecture Experiments

| ID | Capability | Required behavior | Minimum exit evidence |
|---|---|---|---|
| FLI-032 | Sage Facility Lab Mode | **Deferred experiment.** Allow model-first semantic planning and bounded multi-step tool orchestration inside an isolated unsaved draft while deterministic tools retain geometry, validation, evidence, and persistence authority. | A/B evaluation against the frozen production router, held-out paraphrases, browser proof, exact Undo, unchanged saved state, and no unauthorized claims or actions. See `docs/sage-facility-lab-mode-experiment-plan.md`. |
| FLI-033 | Sage persistent design loop | **Implemented; product-owner promotion review pending.** A coordinate-free manufacturing objective, exact references, hard constraints, permitted changes, priorities, and decisions persist across turns; an evidence-bound manufacturing snapshot and deterministic evaluator compare bounded alternatives; correction, cancellation, preview, unsaved Apply, exact Undo, and recovery are implemented. `FLI-032` must consume these contracts rather than create parallel memory or evaluation state. | The six-turn material-travel conversation retains every lock, compares measured alternatives, accepts a validated unsaved editor base, selects a corrected exact proposal on a separate turn, applies one unsaved proposal only with `agent_write`, and restores exact bytes with Undo. Preview-only comparison, failed `O -> A -> B` replacement recovery, expired-lease local Undo, four held-out positive controls, one negative control, reference-scale no-improvement, browser evidence, and latency gates pass. See `docs/facility-sage-persistent-design-loop-implementation-report.md`. |

## Evaluation Backlog

Each capability gate must add:

- held-out intent cases that were not used to author parser rules;
- deterministic positive, ambiguous, contradictory, and unauthorized cases;
- multi-turn scenarios with unpredictable but valid follow-ups;
- API and production-browser evidence;
- exact saved-state, Undo, stale-revision, and identity assertions;
- property-based geometry tests across supported size and entity ranges; and
- a provider shadow that cannot write or approve a layout.

The proposed forty-case G1 suite from 2026-08-27 is input to this backlog, not
the current G1.1 release gate. Its adjacency, irregular-envelope, partial-area,
minimum-area, incremental-editing, and localized-reflow cases map to FLI-003
through FLI-017. Infrastructure cases map to FLI-027 through FLI-031.

## Promotion Rule

A backlog item becomes an enabled Sage capability only after its semantic
contract, deterministic implementation, negative cases, browser proof, and
Save/Undo behavior pass a named gate. Documentation or a successful isolated
kernel experiment does not constitute production availability.
