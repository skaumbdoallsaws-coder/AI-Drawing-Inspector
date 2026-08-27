# Facility Layout KF3 Implementation Report

Date: 2026-08-26

Status: Complete

## Scope

KF3 establishes the K6 asset and zone planning-readiness boundary. It adapts
the existing asset definitions, semantic classifiers, and bounded fit analyzer;
it does not introduce another geometry or placement engine.

## Implemented

- `planning_readiness.py` compiles exact asset revisions into a bounded K6
  projection covering footprint, height, mobility, support relationships,
  directional interfaces, access and clearance evidence, operating envelope,
  utilities, zone roles, process capabilities, and readiness blockers.
- Every required directional role reports one of `authored`, `derived`,
  `inferred`, or `unknown`. Only authored or derived evidence is eligible for a
  hard rule.
- Geometric planning readiness is distinct from controlled planning readiness.
  A revision-bound footprint supports bounded preview reasoning; it does not
  silently establish clearances, safety, operating envelopes, or process
  authority.
- Zone labels are retained byte-for-byte as authored input. Typed zone roles
  continue to use the established semantic classifier, and inferred roles are
  advisory only.
- `analyze_planning_ready_asset_fit()` adds readiness diagnostics around
  `fit_analysis.analyze_facility_asset_fit()`. The established analyzer remains
  the sole owner of candidate geometry and validation.
- Public semantic-classification adapters expose the existing asset and zone
  rules without copying their implementation.
- `build_facility_layout_kf3_readiness.py` produces a reproducible audit of the
  current local asset library.

## Current Library Audit

The audit at `facility-layout-kf3-asset-readiness-report.json` covers 152 exact
asset revisions: four built-in definitions and 148 private local definitions.

- 152 of 152 have a revision-bound footprint and height.
- 152 are available for bounded geometric planning.
- 0 are silently promoted to controlled planning readiness.
- 0 currently contain authoritative clearance evidence.
- All 1,064 required directional-interface fields remain explicitly unknown.

This is the intended result for the current source data. Sage can use the
physical envelopes for preview analysis while reporting that controlled
clearances and directional interfaces have not yet been authored.

## Verification

- KF3 planning-readiness tests: 12 passed.
- KF3 plus existing fit and semantic-model tests: 42 passed.
- Tests prove unavailable assets are retained in the report, inferred sides and
  clearances cannot satisfy hard rules, exact user labels are preserved, and
  fit analysis is bounded, revision-bound, delegated, and read-only.

## Exit Gates

- Every planning asset has a revision-bound footprint or is unavailable: PASS.
- Every directional interface has an explicit evidence status: PASS.
- No inferred side or clearance satisfies a hard placement rule: PASS.
- Zone labels remain authored while semantic roles remain typed: PASS.
- Bounded fit reuses `fit_analysis.py`: PASS.
