# Facility Layout NAV8 Implementation Report

Date: 2026-09-01

Status: Implemented and verified in explicit prototype mode. No human
authority, production eligibility, safety approval, throughput claim, or
regulatory claim was granted.

## Scope

NAV8 gives Sage a bounded, coordinate-free interface to deterministic facility
navigation. It adds five read tools, one semantic proposal tool, and one
prototype presentation tool:

- `observe_navigation_context`;
- `compile_navigation_snapshot`;
- `plan_actor_journey`;
- `validate_actor_journey`;
- `compare_journey_alternatives`;
- `propose_navigation_intent`; and
- `build_activity_scenario`.

Large snapshots, paths, and scenarios remain server-side. Sage receives stable
IDs, bounded summaries, findings, and semantic diffs. The browser is the only
terminal executor for proposal and presentation actions.

## Authority Boundary

Sage may select existing actors, reviewed anchors, authored routes, loop modes,
and semantic preferences. It cannot provide path coordinates, clearances,
vehicle dimensions, task order that is not present in trusted context, or
engineering approval.

Semantic proposals preserve manually authored anchors, manual path constraints,
and handoff programs byte-for-byte. New inferred movement intent remains
`pending`, is applied as one unsaved gesture, and retains exact Undo. Activity
presentation does not alter the saved layout or editor draft.

## Deterministic Routing

The intent classifier runs before general model fallback. It distinguishes
build, ask, refuse, read, and not-applicable outcomes. Refusals cover chat
coordinates, invented clearances, unspecified vehicles, and unsupported safety,
capacity, compliance, and operational-optimality claims.

The frozen held-out corpus contains 40 cases and was not used to author the
rules. Its SHA-256 is:

`88df25add9f09779bbec594cdcdceb0cb3757d398b3c134f5dbac67388c595cf`

All 40 classify exactly, including all eight mandatory refusals.

## Local Replanning

The navigation geometry-context fingerprint excludes the full layout revision
while retaining shell, policy, actor profile, navigation radius, allowed
geometry, exact obstacle geometry, traversable geometry, tracks, required
anchors, and forbidden zones. A semantic-only evidence change therefore changes
the source layout revision but preserves the geometry-context fingerprint.
Anchor, obstacle, shell, policy, or profile changes still invalidate it.

This keeps existing package provenance immutable while allowing a selected
journey to be replanned without invalidating unrelated accepted geometry.

## Verification

- NAV8 focused contract and runtime suite: 12 passed;
- NAV3 through NAV7 navigation regression suite: 21 passed;
- full Facility agent runtime, integration, and skill surface: 213 passed after
  aligning the published skill and contract version to `1.10.0`;
- navigation authoring: 7/7 passed;
- Facility session: 50/50 passed;
- Facility workspace: 72/72 passed;
- Facility transport: 21/21 passed;
- Facility P11 contracts: 8/8 passed; and
- chat-stream frontend contracts: 18/18 passed.

The recurring pytest cache warning is a local OneDrive cache-path warning and
not a test failure.

## Remaining Boundary

NAV8 is still prototype workflow capability. NAV9 owns randomized geometry,
feature-flag promotion order, stale-state and persistence hardening, complete
manual-reference acceptance, performance evidence, browser accessibility, and
the production call-path removal of the legacy rectangle-loop heuristic.
