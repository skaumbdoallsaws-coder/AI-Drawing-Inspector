# Sage Memory Phase 1 - P1.2 Verification Report

Date: 2026-08-06

## Verdict

P1.2 is complete as an architecture checkpoint. Durable workflow state can be
reconciled through the real server helper from a reopened SQLite repository with
no browser workflow mirror. P1.3 still owns binding ordinary browser chat IDs to
canonical server conversation and agent-session records before durable memory is
enabled in the default chat path.

## Implemented

- Replaced workflow-state v1 with the closed v2 scope and revision contract.
- Added `advance_workflow_state_v2` and migrated every production caller.
- Added deterministic v1-to-v2 migration that rebuilds scope and revisions only
  from current trusted providers. It never derives them from the old combined
  hash.
- Added the ten-field closed revision vector and canonical revision hash.
- Added the closed invalidation action vocabulary and dispatcher.
- Added dependency and safe-predecessor policies for every registered workflow
  stage.
- Added deterministic stage regression for revision changes and restore-time
  invalidation of preview, approval, apply, and execution stages.
- Added target, referent, and evidence revalidation.
- Added active and audit-only receipt separation. Receipts observed while an
  authorization or revision is invalidated cannot become active authorization.
- Added a SQLite-backed workflow-state store with CAS updates, expiry, explicit
  abandon, completion, health metadata, and server-compatible session checking.
- Kept live viewport state outside persisted workflow memory.
- Split stable scope identity from mutable revisions for CAD/FAI, Process Map,
  and Facility Layout trusted contexts.
- Renamed Facility Layout's unrelated internal asset-definition fingerprint
  variables so they cannot be confused with workflow identity.

## Migration Ledger

The frozen 117-entry P1.0 ledger is closed without rescanning post-migration
source as if it were the historical baseline:

| Disposition | Count |
| --- | ---: |
| Migrated | 95 |
| Removed | 13 |
| Retained v1 reader | 9 |
| Pending | 0 |

The only current production occurrence of the old field name is the named v1
reader in `migrate_workflow_state_v1_to_v2`. A source-boundary test enforces that
exception.

## Exit-Gate Evidence

- Reopening SQLite and reconciling through the server helper restores valid
  workflow state without browser state.
- Expired workflow state is cleared and cannot be restored.
- A scope change clears state, referents, and pending effects.
- Stable-scope revision changes follow the frozen dependency policy.
- Authorization stages regress to their declared safe predecessor on restore.
- Active receipts become audit-only across invalidation boundaries.
- Explicit abandonment clears workflow state without disabling the surrounding
  agent session.
- No remembered viewport side effect is replayed.
- All registered workflow stages match the frozen policy and all authorization
  stages have a valid predecessor.
- The closed ledger has no pending entries.

## Verification

```text
Memory, workflow, and P1.0 contract suites: 51 passed
Process Map, Facility Layout, and streaming integration: 54 passed
Server restart workflow subset: 22 passed
Frontend workflow state: 8/8 passed
Frontend stream contract: 13/13 passed
Frontend stream runtime: 10/10 passed
Python compilation: clean
Migration ledger --check: clean
git diff --check: clean
New P1.2 files: ASCII-clean
```

Pytest reports a workspace cache warning because `.pytest_cache` cannot create
one Windows path that already exists as a file. Tests still execute and report
normally.

## Unrelated Test Drift

The broader legacy skill suites currently report 21 passed and 14 failed. The
failures expect nine registered skills while the runtime has eleven and omit
already-shipped Process Map tools from their local Sage allowlist. They do not
exercise or reference the P1.2 workflow-state contract. This drift is recorded
for cleanup but is not attributed to P1.2.

## P1.3 Boundary

The server's default production workflow-state singleton remains the legacy
in-memory store. P1.3 must create canonical conversations and agent sessions,
map browser requests to those server IDs, persist pending turns before provider
calls, and bind terminal streaming commits to SQLite. Enforce mode must not be
enabled before that lifecycle is complete.
