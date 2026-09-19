# Facility Layout NAV1 Implementation Report

Date: 2026-08-31

Status: Implemented and verified in prototype mode. No human authority or
production approval was granted.

## Scope

NAV1 establishes the durable navigation-intent contract and the narrower
playback-validity boundary required before NAV2 may write manual navigation
intent.

Implemented:

- closed contracts for navigation anchors, movement programs, manual path
  constraints, handoff programs, navigation snapshots, and journey solutions;
- strict validation of `extensions.facilityNavigation` inside Layout v1;
- deterministic canonical ordering, six-decimal geometry, stable IDs, resource
  ceilings, and canonical fingerprints;
- generator authority guards and evidence/position-authority consistency;
- a non-service `barrier` obstacle role;
- a field-level ownership and migration matrix;
- bounded, coordinate-free Sage contract and summary payloads;
- Facility Motion Package v2 with generation revision provenance and a
  recomputed `validationContextFingerprint` playback gate; and
- service and Three.js checks that reject stale or missing v2 context before the
  first playback frame.

## Ownership

Durable intent is stored only at `extensions.facilityNavigation`. Existing
zones, placements, routes, markings, process bindings, and connectors remain
their own sources of truth and are referenced by stable ID.

Navigation snapshots, journey geometry, poses, clearance samples, and playback
state are derived artifacts. They are never persisted as facility truth.

The machine-readable ownership matrix is:

- `tests/fixtures/facility_layout/navigation/nav1-field-mapping-v1.json`

## Authority

The contract enforces these boundaries:

- only the Plan UI may persist manual path coordinates;
- model and deterministic-generator writers cannot emit authored evidence,
  confirmed review, controlled-source position authority, or authored timing;
- an inferred candidate remains inferred and pending until a user or controlled
  import promotes it;
- barriers subtract from free space but cannot receive service anchors; and
- authored navigation intent is not a safety, compliance, capacity, or release
  claim.

All published NAV1 fixtures carry `productionEligible: false` and
`humanApproval: null`.

## Motion V2

V1 behavior is unchanged: `facility-motion-package-v1` requires exact full
layout-revision equality.

V2 uses one different, non-competing rule:

1. `generationLayoutRevision` records provenance.
2. `validationContextSpec` freezes selectors, influence bounds, planner
   versions, zero influence margin, and the `1e-9` computational epsilon.
3. The server recomputes selected source records and current obstacles whose
   canonical bounds intersect that influence region.
4. Playback proceeds only when the recomputed fingerprint is byte-identical.
5. Missing records, unavailable context, changed projected geometry, or a new
   in-region obstacle fail before playback.

The epsilon is computational geometry tolerance. It is not engineering
clearance and is not exposed as one.

Normal authored-route motion generation now emits v2. Existing multi-actor
prototype activity builders remain v1 until NAV7 migrates them deliberately.

## Resource Gates

The contract checks collection counts before allocation-heavy work and applies
fixed canonical ceilings:

- durable navigation extension: 2 MiB;
- navigation snapshot: 8 MiB;
- journey solution: 8 MiB;
- validation-context spec/projection: 2 MiB;
- graph nodes: 25,000;
- graph edges: 100,000;
- selected validation-context IDs: 2,000;
- obstacle candidates: 25,000; and
- Sage navigation summary: 8,192 bytes.

The generated contract artifact is 6,203 bytes. Sage-facing summaries are
IDs and semantics only, remain under 8,192 bytes, and stay below the 9,600
estimated-token Facility target.

## Evidence

Machine-readable artifacts:

- `tests/fixtures/facility_layout/navigation/nav1-contract-manifest-v1.json`
- `tests/fixtures/facility_layout/navigation/nav1-field-mapping-v1.json`
- `tests/fixtures/facility_layout/navigation/nav1-artifact-manifest-v1.json`

Deterministic publisher:

- `tools/build_facility_navigation_nav1.py`

Verification completed on 2026-08-31:

- Python NAV1-focused and adjacent regression matrix: 110 passed;
- Facility transport: 12/12 passed;
- Facility workspace: 71/71 passed;
- Facility Three.js adapter: 62/62 passed;
- Layout v1 schema compatibility: included in the 110-test matrix;
- Python compile check: passed; and
- JavaScript syntax check: passed.

The frozen manual reference archive remained byte-identical:

`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`

## Exit Gates

- one canonical owner per behavior-bearing field: passed;
- no computed route persisted as facility truth: passed;
- generators cannot emit human or controlled authority: passed;
- unknown fields and dangling identities fail closed: passed;
- unrelated, unselected navigation anchor does not stale v2: passed;
- selected source changes stale v2: passed;
- obstacle entering the frozen influence region stales v2: passed;
- missing projected record fails before playback: passed;
- v1 retains full-layout staleness behavior: passed;
- browser refuses missing or mismatched v2 context before playback: passed;
- compact responses remain below 16,384 bytes: passed; and
- Facility context remains below the 9,600 estimated-token target: passed.

## Remaining Boundary

NAV1 does not expose manual path editing. That belongs to NAV2 and remains
disabled until these v2 gates are present. NAV0's pedestrian-algorithm promotion
holds and cross-platform geometry receipt also remain separate review items;
NAV1 does not manufacture their approval.
