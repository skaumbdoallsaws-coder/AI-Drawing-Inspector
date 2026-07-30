# Facility Layout P11 Self-Use Soak Procedure

## Two Separate Gates

The P11 verifier records two different activities:

1. Accelerated deterministic soak: executable transaction and persistence
   mechanics completed in minutes.
2. Real elapsed soak: actual self-use over at least fourteen calendar days.

Accelerated activity never increments the real elapsed observations.

Exact idempotent replay means retrying the same approved binding, principal,
session, and idempotency key returns the original canonical receipt. Changing
any bound value is an altered retry and must fail closed.

## Accelerated Coverage

The automated harness must exercise:

- At least 10 layouts.
- At least 20 proposal previews.
- At least 10 explicitly approved, receipt-backed applies.
- At least 5 byte-identical dismissals.
- At least 5 rejected stale or unauthorized attempts.
- At least 5 reopen cycles per layout.
- Durable canonical receipt retrieval and idempotent replay.
- A warehouse storage zone and a manufacturing workcell.

Its result appears under `acceleratedDeterministicSoak`.

## Real Elapsed Coverage

The real ledger requires:

- 14 elapsed days.
- 10 layouts.
- 50 editing sessions.
- 20 agent previews.
- 10 approved receipt-backed Sage applies.
- 5 dismissed previews proven byte-identical.
- 5 stale or unauthorized attempts rejected.
- 5 reopen cycles for every layout.
- Warehouse, manufacturing-cell, and rollback workflows.
- The same write-capable build throughout the credited interval.

The verifier preserves the existing `realElapsedSoak.observed` values on
rerun. Record only actual activity. Add canonical receipt IDs only after the
receipt has been retrieved from durable storage and matched to the apply
response.

Before fourteen calendar days, the status must remain exactly:

```text
elapsed_duration_pending
```

After fourteen days, it remains `activity_requirements_pending` until every
count and canonical-receipt check is met.

## Integrity Rules

- Do not backdate `startedAtUtc`.
- Do not count automated accelerated activity as self-use.
- Do not count a preview that was never displayed for review.
- Do not count an apply without explicit approval and a canonical receipt.
- Do not count a reopen unless the saved revision and receipts were retrieved.
- Preserve defects and failed attempts in the pilot issue log.
- A stale proposal rejected by design is evidence; a stale proposal applied is
  a release-stopping defect.
