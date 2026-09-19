# Sage Memory Phase 1 Pilot Runbook

Status: Internal single-host pilot

Date: 2026-08-07

## Scope

This runbook operates the Phase 1 server-owned conversation, workflow,
continuity, and Memory Envelope store. It does not migrate or rewrite drawings,
CAD packages, Process Maps, Facility Layouts, or other engineering assets.

The approved internal pilot principal is server-issued:

```text
tenantId = local
userId   = local-user
roles    = admin
```

Browser-supplied tenant and user values have no authority.

## Storage

The default Windows database is:

```text
%LOCALAPPDATA%\InspectorPro\memory\inspectorpro-memory.sqlite3
```

`INSPECTORPRO_MEMORY_DB_PATH` may override this only with a durable local path.
Do not place the SQLite database on OneDrive, a network share, or ephemeral
storage. A multi-host or shared-storage deployment requires the PostgreSQL
rebaseline defined in the Phase 1 contract.

SQLite is configured with WAL, foreign keys, `synchronous=NORMAL`, and a bounded
busy timeout. Filesystem access control and disk encryption protect the local
pilot file.

## Rollout Modes

Set `INSPECTORPRO_MEMORY_V1_MODE` to one of:

| Mode | Durable collection | Prompt authority | Intended use |
| --- | --- | --- | --- |
| `off` | No | Legacy | Immediate rollback and baseline |
| `shadow` | Yes | Legacy | Persistence and telemetry observation |
| `compare` | Yes | Legacy | Bounded-versus-legacy token comparison |
| `enforce` | Yes | Server memory | Internal pilot |

Restart InspectorPro after changing the mode. Do not change modes during an
active turn. Progress in order: `off`, `shadow`, `compare`, then `enforce`.

The internal pilot is approved for the `local/local-user` principal only. Keep
external tenants off until the P1.8 report is accepted.

## Preflight

From the repository root, inspect the configured database:

```powershell
python tools/sage_memory_admin.py health
```

Expected fields:

```text
status: ok
healthy: true
quickCheck: ok
journal_mode: wal
foreign_keys: true
```

The server endpoint provides the same operational view:

```text
GET /api/admin/memory/health
```

Do not enable `enforce` when health is unavailable or `quickCheck` is not `ok`.

## Backup

Online backup is supported while InspectorPro is running. Create one before an
enforce rollout, upgrade, retention-policy change, or recovery exercise:

```powershell
python tools/sage_memory_admin.py backup --destination C:\InspectorProBackups\memory-YYYYMMDD.sqlite3
```

The command copies through SQLite's online backup API, verifies the copy, and
returns its SHA-256 digest. Verify it independently:

```powershell
python tools/sage_memory_admin.py verify --source C:\InspectorProBackups\memory-YYYYMMDD.sqlite3
```

Record the destination, digest, byte count, `quickCheck`, and creation time in
the pilot change record. Keep backups under the customer's retention policy and
outside the application workspace.

## Restore

Restore only while InspectorPro is stopped. The command rejects an unverified
source and creates a pre-restore backup of the current database.

1. Stop InspectorPro and confirm no Python server process is using the database.
2. Verify the selected backup.
3. Run the guarded restore.
4. Run health checks before restarting.

```powershell
python tools/sage_memory_admin.py verify --source C:\InspectorProBackups\memory-YYYYMMDD.sqlite3
python tools/sage_memory_admin.py restore --source C:\InspectorProBackups\memory-YYYYMMDD.sqlite3 --confirm-replace
python tools/sage_memory_admin.py health
```

After restart, open a known conversation and confirm its committed sequence and
agent sessions. Never copy only `-wal` or `-shm` files and never restore over a
running process.

## Retention And Deletion

Pilot defaults:

```text
conversation retention: 30 days
active workflow TTL:     24 hours
referent TTL:            30 minutes
stale pending recovery:  15 minutes by default
cleanup batch:           100 conversations
```

Run bounded retention for the local pilot principal:

```powershell
python tools/sage_memory_admin.py retention --tenant local --user local-user --batch-size 100
```

The equivalent server operation is:

```text
POST /api/admin/memory/retention/run
```

Retention is tenant-scoped, repeatable, and cascade-deletes the conversation's
sessions, turns, summaries, manifests, and summary jobs. User deletion is a soft
delete followed by this bounded retention cleanup. Run a backup before changing
retention defaults.

## Failure Behavior

| Condition | Read-only turn | Preview/action/write turn |
| --- | --- | --- |
| Memory unavailable | Explicit stateless fallback only when configured | Fail closed before tools |
| Soft-stale summary | May answer with visible warning | One bounded refresh; block on failure |
| Hard-stale summary | Visible incomplete continuity | Block before routing |
| Required context over budget | Fail closed | Fail closed |
| Source revision advances | Label read snapshot and current revision | Reject before effect; CAS remains final guard |
| Stream interruption | Pending/cancelled state is visible | Frozen retry reuses client turn ID |

Never describe a failed or unacknowledged turn as committed. Never retry an
action with a new client turn ID merely because its terminal response was lost.

## Recovery Exercises

Before external rollout, reproduce all of these in the internal tenant:

1. Restart after a committed turn and restore the conversation.
2. Restart with a pending turn, then retry the frozen request.
3. Interrupt a streamed answer and verify no duplicate committed turn.
4. Retry a Scout search and verify no second provider or browser search call.
5. Advance a Process Map or Facility Layout revision during an action turn and
   verify the revision barrier blocks the stale effect.
6. Disable the summary provider for 20 turns and verify continuity-dependent
   actions fail closed.
7. Delete a conversation, run retention, and verify another tenant is untouched.
8. Restore a backup and verify committed history plus SQLite integrity.

## Rollback

To roll back prompt behavior immediately:

1. Stop new pilot turns.
2. Set `INSPECTORPRO_MEMORY_V1_MODE=off`.
3. Restart InspectorPro.
4. Verify legacy chat and frozen engineering regressions.

`off` mode does not open or mutate the memory database. Keep the database for
forensics or later re-enable it; do not delete it as part of rollback. No
engineering asset migration is required, and rollback must not touch Process
Map, Facility Layout, drawing, FAI, CAD, or training files.

## Incident Record

Capture only bounded metadata:

- memory mode and error code;
- tenant-safe conversation, session, turn, and manifest IDs;
- source/result revision hashes;
- replay flag, omission count, and token counts;
- backup digest and health output.

Do not copy raw prompts, secrets, images, or provider credentials into incident
logs. Use context-manifest hashes and server receipts for diagnosis.
