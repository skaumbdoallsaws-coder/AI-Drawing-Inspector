# Sage Memory Phase 1 - P1.1 Repository Checkpoint

Date: 2026-08-06

Status: complete

P1.1 adds the storage foundation only. It does not change Sage prompts, browser
history, workflow-state authority, routing, or tool execution.

## Delivered

- storage-agnostic `MemoryRepository` interface and typed immutable records;
- canonical ASCII JSON and SHA-256 helpers;
- closed canonical request-hash v1 implementation matching the P1.0 fixture;
- server-generated IDs for conversations, sessions, turns, summaries, and
  context manifests;
- forward-only, hash-pinned, transactional SQLite migrations;
- WAL, foreign keys, configured busy timeout, and `quick_check` diagnostics;
- tenant- and user-scoped conversation, agent-session, turn, summary, and
  context-manifest operations;
- atomic pending-turn creation with idempotent client-turn handling;
- monotonic per-conversation sequence allocation under concurrent writers;
- terminal committed, failed, and cancelled turn operations;
- workflow-state compare-and-set storage primitive for P1.2;
- current-summary revisioning with supersession;
- deterministic retention queries and cascading deletion;
- pilot database path resolution outside OneDrive by default.

## Files

```text
ai_inspector/memory/__init__.py
ai_inspector/memory/ids.py
ai_inspector/memory/models.py
ai_inspector/memory/policy.py
ai_inspector/memory/repository.py
ai_inspector/memory/sqlite_repository.py
tests/test_memory_models.py
tests/test_memory_sqlite_repository.py
tests/test_memory_tenant_isolation.py
```

## Verification

```text
python -m pytest \
  tests/test_sage_memory_p10_contracts.py \
  tests/test_memory_models.py \
  tests/test_memory_sqlite_repository.py \
  tests/test_memory_tenant_isolation.py -q

24 passed
```

Focused unchanged-runtime regression:

```text
python -m pytest \
  tests/test_agent_workflow_state.py \
  tests/test_prompt_compiler.py \
  tests/test_prompt_compilation_plans.py \
  tests/test_context_evidence.py \
  tests/test_agent_chat_streaming_backend.py \
  tests/test_chat_streaming.py -q

45 passed
```

The tests prove:

- committed conversations, turns, summaries, manifests, and receipts survive a
  repository close and reopen;
- the frozen request-hash fixture reproduces byte-for-byte;
- a duplicate client-turn ID with the same hash returns the original pending or
  committed turn;
- a duplicate client-turn ID with a different hash fails with
  `client_turn_id_reused`;
- twelve concurrent writers allocate exactly sequences 1 through 12 with no
  duplicate turn IDs;
- cross-tenant and same-tenant cross-user reads return the same not-found error;
- retention cleanup removes dependent sessions, turns, summaries, and manifests
  and remains safe to repeat;
- a deliberately failing migration rolls back its first statement, after which
  the prior schema reopens and passes health checks;
- all databases created by tests live below pytest temporary directories.

## Exit Gate

- restart preserves committed data: met;
- duplicate client-turn IDs are deterministic: met;
- concurrent writes cannot allocate duplicate sequence numbers: met;
- tenant-isolation tests pass: met;
- migration rollback leaves the prior schema usable: met;
- repository tests leave no workspace database: met;
- repository diagnostics expose migration, WAL, foreign-key, timeout, and
  integrity state: met.

P1.2 may now use `update_agent_session_state` as the durable compare-and-set
boundary while migrating workflow state from the combined v1
`asset_fingerprint` contract to separate scope and revision authority.
