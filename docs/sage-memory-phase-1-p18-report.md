# Sage Memory Phase 1 P1.8 Verification Report

Date: 2026-08-07

## Verdict

P1.8 and the Sage Memory Phase 1 implementation exit gate are met. Durable
conversation memory, bounded continuity, trusted context assembly, revision
barriers, idempotent retries, browser cutover, operational recovery, and pilot
rollout controls are implemented and verified without a paid provider call.

The current complete Facility Layout Python suite remains intentionally
non-green: 465 passed, 12 failed, 1 skipped. All 12 current failures are stale
checked-in release evidence or the local real-soak build identity, not runtime
behavior. The failure composition changed from P1.0: the previously documented
stale asset-definition apply defect was fixed and its complete 17-test proposal
suite passes, while a source-binding failure entered the backend release
benchmark after `ai_inspector/facility_layout/spatial.py` changed.

## Delivered

- Off, shadow, compare, and enforce rollout modes. Off opens no memory database;
  shadow and compare persist observations without replacing legacy prompt
  authority; enforce uses bounded server memory and suppresses browser mirrors.
- Server-owned conversations, agent sessions, turns, summaries, workflow state,
  manifests, receipts, retention metadata, and tenant-scoped deletion.
- Canonical request-hash identity, pending/committed/failed lifecycle, restart
  recovery, immutable retry, pre-effect revision barriers, and authoritative CAS.
- Structured continuity summaries with source-turn provenance, six-turn and
  token budgets, soft/hard staleness, one bounded synchronous action refresh,
  and action fail-closed behavior.
- Deterministic Memory Envelopes and context manifests with authority ordering,
  provider revisions, token accounting, omission reasons, and redaction at the
  persistence boundary.
- Durable Scout search streaming. Search/status/text events remain live, while
  the terminal response is withheld until the turn commits. A committed retry
  returns the canonical result without repeating search or provider work.
- Browser server-authority cutover, immutable local legacy archives, visible
  memory health, durable delete/reload, retry state, and two-browser discovery.
- Privacy-bounded memory telemetry and enforce-mode admin health and retention
  endpoints.
- Online SQLite backup, quick-check verification, bounded retention cleanup,
  and atomic restore with pre-restore backup, stale WAL/SHM removal, and
  rollback.
- A pilot runbook at `docs/sage-memory-phase-1-pilot-runbook.md` and admin CLI at
  `tools/sage_memory_admin.py`.
- Current-catalog asset revision validation before Facility Layout proposal
  apply. Historical definitions remain available for saved-layout rendering,
  but cannot authorize a stale new proposal.

## Pilot Replay Matrix

The closed fixture is
`tests/fixtures/memory/pilot-replay-matrix-v1.json`. Its schema test rejects
missing, duplicate, reordered, or nonexistent test nodes. All 12 scenarios and
18 referenced checks passed:

1. FAI impact, disposition, and viewport continuity.
2. Process Map preview followed by map revision and continued review.
3. Facility Layout move followed by policy revision and validation.
4. Tricycle conversation switched to another assembly scope.
5. A user correction supersedes but does not erase an earlier claim.
6. Two conflicting sources remain explicit and authority-separated.
7. Identical labels remain isolated across tenants.
8. A real summary timeout blocks the action at the configured deadline.
9. A 20-turn summarizer outage becomes visible and blocks dependent action.
10. Provider change between turns survives repository restart.
11. Restart between request and retry does not replay an effect.
12. Mid-flight asset revision advance blocks action and same-turn retry.

## Performance

`python tools/benchmark_sage_memory_phase1.py` seeded 10,000 realistic turns
across 50 conversations. Seeding was excluded from gates. The run made zero
provider calls and wrote `runtime_logs/sage_memory_p18_benchmark.json`.

| Gate | Actual p95 | Target | Result |
| --- | ---: | ---: | --- |
| Repository read | 3.4177 ms | 25 ms | pass |
| Repository write | 11.7472 ms | 25 ms | pass |
| Context manifest persistence | 9.9055 ms | 20 ms | pass |
| Restore 200 turns | 11.3385 ms | 250 ms | pass |
| Memory Envelope assembly | 1.3641 ms | 75 ms | pass |

SQLite `quick_check` returned `ok`; normal turn queries used indexes with no
turn-table full scan; repeated envelope assembly produced the same SHA-256.

## Verification

```text
Complete Phase 1 Python memory surface: 94 passed
Closed pilot replay scenarios: 18 passed; matrix contract: passed
Browser memory runtime: 8/8 passed
Frontend memory contract: 10/10 passed
Live enforce-mode browser cutover: 20/20 passed, 0 page errors
Scout durable backend: 3 passed
Scout enforce-mode browser smoke: 3/3 passed
Frozen workflow/prompt/context/streaming Python bar: 50 passed
Frontend workflow state: 8/8 passed
Frontend streaming contract: 13/13 passed
Frontend streaming runtime: 10/10 passed
Complete Process Map Python suite: 221 passed
Process Map editor: 83/83 passed
Process Map spatial: 44/44 passed
Floating surface: 14/14 passed
Complete Facility Layout Python suite: 465 passed, 12 failed, 1 skipped
Facility Layout proposal suite: 17 passed
Facility Layout Node harnesses: 167/167 passed
Inline application scripts: 4/4 syntax-clean
Python compilation: clean
Whitespace check: clean
New Phase 1 files: 60/60 ASCII and trailing-whitespace clean
```

The independent pre-correction review reproduced 80 memory tests, correcting
the earlier unsupported `83 passed` line. The required review patch added 14
regression cases for closed attempted-CAS outcomes, no-effect action responses,
missing resulting revision vectors, and stale SQLite sidecars; the resulting
surface is the 94-test bar above.

## Independent Review Corrections

- Every attempted action CAS now fails unless its normalized outcome is in the
  closed success set: `applied`, `committed`, `success`, or `succeeded`.
  `not_attempted` and `not_applicable` remain explicit no-effect states, so Sage
  may commit a refusal or browser-deferred proposal without claiming a write.
- A successful receipt that omits `resultingRevisionVector` no longer attributes
  unrelated authority drift to the effect. The authorized vector remains the
  expected vector and `postEffectRevisionDrift` is reported truthfully.
- Restore removes destination `-wal` and `-shm` files immediately before the
  authoritative swap and before rollback, preventing stale frames from being
  replayed into the restored database.

The enforce-mode admin endpoint and CLI both reported schema version 2, WAL,
foreign keys enabled, `quick_check: ok`, and the configured 30-day conversation,
24-hour workflow, 30-minute referent, and 15-minute pending-turn policies.

## Known Non-Phase-1 Conditions

- Facility Layout release screenshots, source hashes, accessibility summaries,
  and product evidence must be regenerated by that workstream after its current
  UI/source changes. The real-soak ledger correctly reports `build_changed`.
- Pytest emits the existing Windows `.pytest_cache` path warning.
- Python 3.14 emits the existing LangSmith/Pydantic v1 compatibility warning.

These conditions do not alter memory behavior or the reproduced frozen bars.
