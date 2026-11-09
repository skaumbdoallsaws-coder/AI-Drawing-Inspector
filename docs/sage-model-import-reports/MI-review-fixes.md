# Post-review model-import fixes

## CHANGED

- ai_inspector/facility_layout/model_import_store.py: all four lease claim sites now establish cleanup protection before claiming. prepare protects the initial checking-state write; retry protects queued-state publication and thread handoff. Cleanup leaves the OS coordinator before calling lease.release. Failed startup writes cannot bypass release, and ENOSPC retains the quota/507 error.
- Audited upload creation/completion and hold_draft (registration). Upload completion becomes finished only after successful thread startup; flush/fsync/close failures also release. Thread construction/startup cleanup belongs to the caller until ownership transfers to the worker. Registration protects errors between claim and yielding its lease. Partial claim-marker/job creation failures roll back under the existing coordinator, without reacquiring it. If cleanup itself is temporarily blocked, the lease is marked ending for immediate reconciliation cleanup instead of waiting for a nonexistent worker.
- Existing inspect/draft paging and receipt lookups acquire no lease. The background inspect worker already has a release finally. Completed orphan drafts on simulated process interruption remain recoverable; the prior restart-recovery behavior is preserved.
- ai_inspector/industrial_assets/model_import/inspection.py: accept canonical, unique, strictly numerically increasing source keys with gaps, bounded by the source primitive limit. Validate that the summary page agrees with full metadata. Source keys are not renumbered; paging still counts retained parts, while recipes select the original keys.
- tests/test_model_import_lifecycle_fixes.py: state-write failures before/after atomic publication, persistent failures, interruption before handoff, initial upload failures, thread construction/startup failures, failed terminal writes, registration pre-yield failure, partial claim publication, deferred cleanup, upload flush/fsync plus close failure, and immediately reusable admission.
- tests/test_model_import_inspection.py: valid gapped/numerically ordered keys; duplicate/reversed/noncanonical/out-of-budget keys; summary/metadata disagreement; a generated GLB with POINTS before and between TRIANGLES through the real upload worker to ready. The real-worker case checks p1/p3 summary and paging, then prepares a recipe dropping p1 and selecting/renaming p3.

If storage also refuses the attempted terminal/recovery write, lease cleanup still runs. Once storage recovers, reconciliation repairs any interrupted persisted state without waiting for an abandoned live operation.

No static files, browser harness, server.py, history or index were changed. No commit was made.

## TESTS

Attempted hidden command:

    python -B -m pytest tests/test_model_import_lifecycle_fixes.py tests/test_model_import_inspection.py tests/test_model_import_store.py tests/test_model_import_reader.py -q -p no:cacheprovider --basetemp=<temporary directory>/mi-review-tests

Result: exit 1 before collection, "No module named pytest".

Actual standard-library probes on temporary roots passed:
- 8 prepare/retry state-write cases: one claim and one release outside the coordinator, zero worker starts, ready/failed state, reusable admission and successful retry.
- 6 thread construction/startup/failure-record cases; 3 initial-upload failures; 3 partial-claim rollback cases.
- Registration failure before yielding its lease; 2 upload flush/fsync plus close-failure cases; deferred partial-claim cleanup before reconciliation waits.
- Existing interrupted draft-publication recovery through reconciliation, retry and reuse.
- 12 source-key validation/paging cases, including p1/p3 and numeric p9/p10 ordering.

These probes use the existing protocol worker stand-ins and bypass application package startup. They do not substitute for the new real GLB/subprocess test. AST/LF checks passed for all four changed/new Python files; targeted git diff --check passed.

## NOT RUN

Pytest, real GLB decoding/prepare subprocesses, and the broader regression suites remain for Claude's environment. No packages were installed and no network/private downloads or default stores were accessed.

## DEVIATIONS

None. Cleanup changes cover the other lease claim and handoff sites explicitly requested by the review, rather than only the two reported state writes. Reader keys, recipe selection, and normal publication semantics remain unchanged.

## OPEN QUESTIONS

None.
