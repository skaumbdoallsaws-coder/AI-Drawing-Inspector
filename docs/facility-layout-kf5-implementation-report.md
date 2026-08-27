# Facility Layout KF5 Implementation Report

Date: 2026-08-26

Status: Complete

## Scope

KF5 implements the coordinate-free stage planner, durable generation-run
repository, revision-bound stage receipts, browser draft installation, and
explicit cumulative Save contract. It exposes only the G1 facility-envelope
and macro-department capability; later rollout stages remain bounded and
inactive.

## Implemented

- `FacilityGenerationRunRepository` is the restart-safe owner of runs,
  generation-session mappings, writable leases, stage receipts, checkpoints,
  tombstones, and saved receipts.
- Cross-process single-writer locking and revision compare-and-swap prevent two
  writable runs from silently replacing each other. Read-only preview runs may
  coexist.
- Run expiry is 24 hours, tombstones are retained for 30 days, and the legacy
  1,800-second pending-operation store remains outside the durable generation
  contract.
- The coordinator supports `preview_only`, `guided_draft`, and
  `authorized_draft_run`. Save remains a separate, explicit action.
- An authorized G1 run advances through the frozen ten-stage sequence. Skipped
  stages receive revision-bound receipts and do not invent routes, resources,
  cells, modules, or floor markings.
- Each stage writes a transaction checkpoint before installing the next draft.
  Recovery resumes from the exact checkpoint after interruption instead of
  replaying valid completed stages.
- Dependency changes supersede affected receipts, invalidate descendants, and
  restore the last valid checkpoint.
- The cumulative proposal is bound to the complete valid receipt chain and an
  exact diff hash. Missing, stale, invalid, or superseded receipts block Save.
- Save intent is frozen before persistence and recovery is idempotent if the
  layout write succeeds before the receipt write.
- Undo restores the exact pre-run layout and cancels the generation run.
- Sage chooses semantic intent only. The deterministic planner owns all final
  polygons and coordinates, and coordinate-bearing model intent fails closed.
- No generated operation grants human authority or persists a layout
  implicitly.

## Browser Integration

- The production Facility tool registry now contains 15 tools: the 14 frozen
  KF0 tools plus `generate_facility_departments_draft`.
- The browser installs accepted stage drafts progressively through the normal
  workspace session and transport surfaces.
- Save and Undo use the established workspace commands and event handlers.
- G1 responses remain under the 10,155-byte tool-response limit.

## Verification

- Changed Python contract, repository, coordinator, planner, host, tool, and
  evaluator surface: 123 passed.
- Browser editor, session, transport, app, workspace, viewport-intent,
  patterns, and chat contracts: 326 passed.
- Restart, expiry, lease, compare-and-swap, stale-state, checkpoint, save
  recovery, explicit approval, and exact Undo fixtures: PASS.

## Exit Gates

- Durable resume after interruption: PASS.
- Exactly one cross-process writable lease: PASS.
- No model-authored coordinates: PASS.
- No implicit Save or authority promotion: PASS.
- Exact cumulative diff and receipt-chain binding: PASS.
- Invalidated descendants block Save: PASS.
- Atomic persistence with idempotent recovery: PASS.
