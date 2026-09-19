# Facility Layout G7 Production Hardening

Date: 2026-08-29

Status: Engineering qualification passed; controlled release remains blocked by
the literal elapsed-soak gate

## Scope

G7 hardens the qualified G1-G6 generation path without changing its authority
boundary. Sage resolves semantic intent, InspectorPro owns geometry and
validation, generation remains an unsaved cumulative draft, Save still requires
explicit approval, and one Undo restores the exact saved base.

## FLI-027: Durable Restart And Resume

The generation-run repository is restart-safe and records the active stage,
stage receipts, resume point, immutable source intent, draft revision, lease,
and cumulative proposal on disk. A reconstructed coordinator resumes from the
next incomplete stage without replaying completed work.

The gate includes repository restart, checkpoint-journal recovery, and recovery
after the layout is persisted but before its receipt is finalized.

## FLI-028: Cross-Process Writer Exclusion

One writable run may hold the layout/base-revision lease. The repository uses a
cross-process exclusive lock plus revision compare-and-swap; preview-only runs
do not own that lease. Stale lock recovery is bounded, and run expiry produces a
retained tombstone before collection.

The gate includes a real multi-process writer race. An in-process lock alone is
not accepted as evidence.

## FLI-029: Bounded Large-Layout Substages

An oversized stage is compiled once into an immutable operation-plan artifact.
InspectorPro then executes restart-safe substages bounded by both production
limits:

- no more than 500 operations per substage;
- no more than 500 planned instances per substage; and
- one cumulative proposal and one final Save decision for the complete run.

The 1,201-operation fixture produces `500 + 500 + 201` operations, reconstructs
the coordinator between substages, preserves all 12 receipt IDs, and restores
the exact base with one Undo. A failure injected at operation 501 retains the
first 500-operation checkpoint, marks the second substage failed, and blocks
Save without discarding prior evidence.

The browser continuation bound is 128 transitions, so bounded substages can
span more than the original ten semantic stages without becoming an unbounded
model loop.

## FLI-030: Plan, 3D, Theme, And Viewport Parity

The browser proof builds one unsaved factory containing 12 zones, two routes,
one crossing, and six exact-revision placements. It captures all eight required
surfaces:

| Viewport | Theme | Views |
|---|---|---|
| 1440 x 960 | light and dark | Plan and 3D |
| 390 x 844 | light and dark | Plan and 3D |

Every surface uses draft revision
`c397e067cd9aa89e2857443aec994a874bba9ee1656090def97a410dfe9c9f6f`
and the same entity IDs. Both transform audits report `match`, all images are
nonblank and contained, theme changes alter rendered pixels, real mouse input
changes the 3D camera, no browser/API error is recorded, the saved blank layout
is unchanged, and one Undo restores it exactly.

Evidence:

- `tests/fixtures/facility_layout/production_hardening/fli030-parity-evidence.json`
- `tests/fixtures/facility_layout/production_hardening/fli030-parity/`

## FLI-031: Performance, Memory, And Cleanup

The qualification uses one discarded warmup followed by 20 measured cycles.
Each cycle runs full-factory generation, fits the 3D scene, returns to Plan, and
performs exact Undo. Browser RSS, server RSS, precise JavaScript heap, pending
loads, canvas count, active render work, browser errors, and HTTP failures are
recorded against the machine profile in the evidence artifact.

| Metric | Budget | Observed |
|---|---:|---:|
| Full generation p95 | 6,000 ms | 3,682.300 ms |
| Generation transition p95 | 1,500 ms | 443.510 ms |
| Undo p95 | 1,000 ms | 358.315 ms |
| JavaScript heap growth | 10% | -11.260% |
| Browser RSS end growth | 256 MiB | 159,752,192 bytes |
| Browser RSS peak growth | 512 MiB | 161,587,200 bytes |
| Server RSS end growth | 128 MiB | 163,840 bytes |
| Server RSS peak growth | 256 MiB | 163,840 bytes |
| Pending loads after fit | 0 | 0 |
| Canvases after cleanup | 1 | 1 |
| Active render requests after cleanup | 0 | 0 |

JavaScript growth compares the medians of the first and last five post-GC
measured cycles. The single endpoint delta remains in the artifact as a
diagnostic, but it is not used as the leak gate because V8 alternates between
stable collection states.

The accelerated deterministic soak also passed with 10 layouts, 21 previews,
10 receipt-backed applies, rejection controls, and five reopen cycles per
layout. Acceleration proves mechanics and persistence; it is never credited as
elapsed self-use time.

Evidence:

- `tests/fixtures/facility_layout/production_hardening/fli031-performance-evidence.json`
- `tests/fixtures/facility_layout/production_hardening/fli031-accelerated-soak.json`

## Controlled-Release Boundary

The real G7 soak campaign started at `2026-08-29T06:11:28.355256Z` with campaign
ID `fls-5dd32bd2e8b7be9f47f3c539` and source aggregate
`df6f4fad34cd533bffcce02e1786c27018f4397153fc9e8290ca131b44915720`.
Its append-only ledger is:

` .runtime/facility_layout/g7-real-soak-events.json `

The campaign has not elapsed for 14 days and therefore cannot satisfy the
controlled-release gate. G7 is engineering-qualified for the current reference
machine; it is not represented as a completed production soak or controlled
release.

## Regression Contract

`tests/test_facility_layout_g7_production_hardening.py` fails closed when source
hashes, screenshots, entity parity, numeric budgets, cycle cleanup, or the
controlled-release blocker no longer match the captured evidence. FLI-027
through FLI-029 remain covered by the generation repository and coordinator
fixtures rather than duplicating their runtime logic in the artifact test.
