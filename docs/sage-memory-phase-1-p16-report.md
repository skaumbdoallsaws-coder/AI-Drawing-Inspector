# Sage Memory Phase 1 - P1.6 Verification Report

Date: 2026-08-07

## Verdict

P1.6 is complete as an architecture checkpoint. Every memory-enabled Sage turn
now reconciles its durable workflow state and continuity against the current
server-resolved scope and revision vector before routing, authorization, prompt
construction, or tool execution.

## Implemented

- Added the closed revision-invalidation matrix and reconciliation outcome
  vocabulary from the frozen Phase 1 contract.
- Distinguished map/layout, structure/evidence, policy, scope, abandonment, and
  workflow-package-version changes.
- Revalidated workflow entities and referents against current Process Map and
  Facility Layout target indexes, including nodes, edges, placements, routes,
  zones, utility networks, process bindings, and industrial assets.
- Preserved the durable objective and audit receipts while invalidating stale
  previews, approval tokens, execution receipts, referents, and evidence.
- Added explicit fail-closed workflow-version reset when no registered migration
  exists; objective and audit history survive while stage-specific state resets.
- Scope-gated continuity summaries by default and allowed retention only for an
  explicit cross-scope comparison, with a visible warning.
- Reconciled summaries by removing stale evidence references and marking policy-
  dependent decisions for reload rather than silently presenting them as current.
- Ignored browser workflow-state mirrors in enforce mode and injected only the
  reconciled server-owned workflow state into routing and prompt construction.
- Added the structured reconciliation event to both response memory metadata and
  the canonical persisted context manifest.
- Bound Process Map and Facility Layout preview calls to the current trusted base
  revision; existing Builder/repository CAS remains the final race-closing guard.
- Prevented the legacy streaming workflow-state path from overwriting durable
  memory state after the memory lifecycle has committed it.

## Exit-Gate Evidence

- A Process Map revision change preserves the user's objective and regresses only
  the stage whose dependencies became stale.
- A deleted Process Map node is removed from both entity sets and actionable
  referents before the routed provider sees workflow state.
- A stale semantic preview approval is rejected by the existing Builder CAS before
  any asset write.
- A Facility Layout policy revision invalidates dependent decisions, previews,
  approval tokens, and placement referents while preserving audit receipts.
- A scope change excludes prior continuity and entities unless the user explicitly
  requests a cross-scope comparison.
- A workflow package version change resets stage-specific state without erasing
  the durable objective or audit history.
- Past execution receipts move to audit history and do not authorize a new tool
  call.
- The response reconciliation event is byte-equivalent to the event stored in the
  context manifest.

## Verification

```text
Workflow-state persistence and version reconciliation: 8 passed
HTTP turn reconciliation and manifest integration: 9 passed
Invalidation, envelope, lifecycle, and frozen contracts: 28 passed
Invalidation plus Process Map Builder CAS exit-gate run: 28 passed
Python compilation: clean
```

Pytest reports the existing workspace cache warning because `.pytest_cache`
cannot create one Windows path that already exists as a file. Test execution is
unaffected.

## P1.7 Boundary

P1.6 makes server state authoritative but does not finish the browser transition.
P1.7 must create and restore server-backed conversations, freeze client turn
requests across retries, render committed history after reload, keep localStorage
as cache and legacy archive only, preserve local drafts, and expose pending,
unavailable, stale, retry, and recovered states without confusing them with a
committed answer.
