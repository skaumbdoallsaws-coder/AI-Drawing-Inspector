# Facility Layout G4 Asset Placement

Date: 2026-08-28

Status: Implemented and production-browser accepted

Backlog capability: `FLI-023`

## Purpose

G4 extends a qualified Facility generation run from departments, circulation,
and nested work areas into exact, revision-bound resources. Sage resolves the
requested catalog asset, quantity, named target area, operational role, and
semantic orientation. InspectorPro owns footprint geometry, candidate search,
coordinates, collision checks, revision binding, durable-run replay, and Undo.

## Qualified Behavior

- Resolve one exact authorized catalog asset and its current definition
  revision.
- Place from 1 through 50 instances in a uniquely named macro department or G3
  child area.
- Preserve the requested quantity as one atomic complete-set operation: an
  infeasible set produces no partial placement.
- Classify the resource role as production, storage, staging, inspection,
  support, material handling, or unspecified.
- Support automatic orientation, long-side east-west, long-side north-south,
  and evidence-backed functional-front orientation.
- Compute every transform through the existing deterministic asset-fit engine.
- Validate physical containment and collision freedom against the complete
  current draft, including existing placements and protected geometry handled
  by the fit engine.
- Preserve all department and child-area geometry, routes, floor markings,
  utility networks, process bindings, groups, and pre-existing placements.
- Keep exact asset IDs and definition revisions in the placement and replay
  receipt.
- Report access as `validated` only when the exact asset revision carries
  current authoritative clearance evidence; otherwise report `unverified`.
- Append placements to the same durable unsaved generation run.
- Keep the cumulative result unsaved until explicit Save and restore the exact
  saved base with one Undo.

## Authority Boundary

Sage may express asset identity, quantity, target area, role, and semantic
orientation only. The chat tool contract has no coordinate, transform, angle,
or clearance-dimension field. InspectorPro computes geometry from the exact
catalog footprint.

G4 refuses:

- chat-authored coordinates, world points, transforms, and numeric angles;
- invented OSHA, fire-code, regulatory, safety, service, or access clearance;
- a functional-front direction when the catalog has no registered front-side
  evidence; and
- stale or unavailable asset revisions.

A physically valid placement establishes only static footprint containment and
collision freedom. It does not establish safe access, serviceability,
ergonomics, utilities, anchoring, floor loading, regulatory compliance,
capacity, throughput, or production suitability.

## Deterministic Contract

The closed tool contract is `generate_facility_asset_placement_draft`. Its
inputs are the exact asset ID and revision, quantity, target-area label,
semantic orientation, optional cardinal facing direction, resource role,
access requirement, hierarchy-preservation flag, and
`authorized_draft_run` execution mode.

The server catalog is authoritative. Browser and model payloads cannot submit
asset definitions. The run stores a minimal exact-revision catalog snapshot so
restart and replay cannot silently bind to a later asset revision.

Compilation uses `analyze_facility_asset_fit` and creates stable placement IDs.
Independent post-validation checks:

- exact asset and definition revision;
- exact target-zone binding;
- target-zone containment;
- physical collision freedom;
- requested semantic orientation;
- access-evidence classification;
- byte parity for the G3 hierarchy and all protected collections; and
- byte parity for every pre-existing placement.

Changing the G4 request supersedes and replays only stage 5 and its dependants.
A failed amendment leaves the previously valid draft unchanged.

## Acceptance Queries

Complete builds:

1. `Place two CNC Milling Machines in Mechanical Build with their long side east-west for production.`
2. `Stage three Pallet Racks in Machining with their long side north-south for storage.`
3. `Place one registered inspection station in Verification facing north.`

Clarification or refusal:

1. `Place two workbenches in Verification.` An ambiguous catalog name must ask
   for one exact asset.
2. `Place one machine in Mechanical Build.` A missing exact asset or quantity
   must not be guessed.
3. `Place one Assembly Workbench at x=10 z=10 in Verification.` Coordinates
   must be refused.
4. `Place one Assembly Workbench in Verification with whatever OSHA clearance applies.`
   Unsupported authority must be refused.
5. `Place the machine facing north.` Front-facing intent must ask for evidence
   when the asset has no registered functional front.
6. `Place 50 machines in Mechanical Build.` The complete set must fail without
   partial output when it cannot fit.

## Automated Evidence

Current results:

- 204 focused asset-placement, generation-coordinator, Sage-integration, and
  host tests passed;
- 174 shared circulation, service, operations, routing, spatial, and
  spatial-integration tests passed, with one existing opt-in performance test
  skipped;
- 32 knowledge-foundation and tool-knowledge contract tests passed;
- 6 of 6 browser transport checks passed;
- 70 of 70 Facility workspace checks passed; and
- 48 of 48 Facility session checks passed.

The focused coverage includes exact and ambiguous catalog resolution, closed
tool inputs, non-asset parser ownership, nested targets, long-side and
functional-front orientation, exact revision pinning, authoritative access
evidence, unverified-access classification, infeasible complete sets,
collision and containment validation, durable-run replay, API transport,
direct deterministic Sage routing, Save, and exact Undo.

## Production Browser Evidence

Playwright drove seven prompts through one visible Sage conversation against
the restarted application at `http://127.0.0.1:8141/`:

1. create a 120 m by 90 m, four-department facility;
2. divide Assembly into Mechanical Build and Verification;
3. place two exact-revision CNC Milling Machines in Mechanical Build;
4. stage three exact-revision Pallet Racks in Machining;
5. refuse an invented OSHA-clearance request;
6. refuse chat-authored asset coordinates; and
7. ask for one exact catalog asset when `workbenches` is ambiguous.

The run passed 13 of 13 browser assertions and proved:

- seven successful production chat streams in one conversation and one
  durable generation run;
- five exact-revision placements with requested quantities, roles, targets,
  and long-side orientations;
- exact physical containment and zero placement collisions;
- byte-identical G3 hierarchy and unrelated layout collections;
- five explicitly unverified access results and zero unsupported validated
  access claims;
- no mutation across all three clarification or refusal turns;
- an unchanged blank saved-layout revision;
- one Undo restoring the exact blank base; and
- no page, console, failed-request, or server errors.

Machine-readable evidence:

`tests/fixtures/facility_layout/knowledge_foundation/g4-asset-placement-browser-evidence.json`

Screenshots:

1. `tests/fixtures/facility_layout/knowledge_foundation/g4-asset-placement-browser/01-g3-target-areas.png`
2. `tests/fixtures/facility_layout/knowledge_foundation/g4-asset-placement-browser/02-g4-machines.png`
3. `tests/fixtures/facility_layout/knowledge_foundation/g4-asset-placement-browser/03-g4-resources.png`
4. `tests/fixtures/facility_layout/knowledge_foundation/g4-asset-placement-browser/04-g4-refusals.png`

## Continuous G1 Through G4 Integration Gate

Playwright also ran every qualified Facility capability from a blank layout in
one visible Sage conversation and one durable unsaved generation run. The
22-turn thread covered:

1. a 120 m by 90 m, nine-department, three-row G1 partition;
2. two mixed-traffic routes, deterministic conflict detection, and exact 1.5 m
   G2.1 separation;
3. a material aisle crossing a protected zone and deterministic G2.2 rerouting
   with exactly 1 m user-authored clearance;
4. G2.3 direction-aware reachability, unmarked point-crossing derivation, one
   exact 4 m by 3 m crosswalk, dead-end reporting, and an evidence-bound safety
   and fire-code refusal;
5. a four-child G3 subdivision plus a two-child nested subdivision; and
6. two exact-revision CNC Milling Machines, three exact-revision Pallet Racks,
   and one fail-closed ambiguous workbench request in G4.

All 26 integration assertions passed and all 22 chat streams returned HTTP 200.
The conversation title and run ID remained stable. G4 preserved every prior
zone, route, floor marking, hierarchy relationship, and receipt-bound identity.
All five resources were physically contained and collision-free, while access
remained explicitly unverified because no authoritative clearance evidence was
available. No response was interrupted, no browser or request error occurred,
the saved blank layout was never modified, and one Undo restored the exact
blank base.

Machine-readable evidence:

`tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser-evidence.json`

Milestone screenshots:

1. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/01-g1-departments.png`
2. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/02-g21-conflict.png`
3. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/03-g21-resolved.png`
4. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/04-g22-obstacle.png`
5. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/05-g22-rerouted.png`
6. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/06-g23-crossing.png`
7. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/07-g23-crosswalk.png`
8. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/08-g3-subdivision.png`
9. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/09-g3-nested-subdivision.png`
10. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/10-g4-machines.png`
11. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/11-g4-resources.png`
12. `tests/fixtures/facility_layout/knowledge_foundation/g1-to-g4-continuous-browser/12-g4-ambiguity.png`

## Remaining Asset Gates

The live catalog used by this proof does not publish authoritative service or
operator-clearance envelopes for the selected resources. G4 therefore reports
access as unverified instead of manufacturing a plausible clearance. Utilities,
anchors, floor loading, ergonomics, shared service zones, dynamic handling
space, and operational capacity remain evidence-bound follow-on work.

## Next Gate

G5 is manufacturing-cell feasibility and composition. It will combine exact
resource footprints, process order, interfaces, registered access evidence,
and available area to select and compare only enabled cell strategies. The
deterministic engine will own geometry and explain rejected fits; Sage will own
user intent and bounded trade-off narration.
