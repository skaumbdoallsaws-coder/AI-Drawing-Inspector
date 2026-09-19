# Sage Memory Phase 1 Plan

Status: Proposed implementation contract for external review
Revision: 4
Date: 2026-08-06
Implementation status: Planning only. No Phase 1 code has been implemented from this plan.

Revision 4 resolves the remaining Commitment A planning decisions:

- binds the current single-host pilot to SQLite and defines the deployment
  conditions that require PostgreSQL before P1.1;
- requires workflow-stage revalidation on every mutable revision and safe
  regression for approval/execution stages;
- turns the v1-to-v2 migration inventory into a closed, machine-checkable ledger
  with a zero-unaccounted-occurrence exit gate.

Revision 3 incorporated the second external review corrections:

- distinguishes nominal asynchronous summarization from the bounded synchronous
  refresh used only in degraded continuity;
- adds a just-in-time revision barrier before previews, approvals, or action
  effects can use a pending turn's captured revisions.

Revision 2 incorporated the first external review corrections:

- freezes the canonical request-hash field set and exclusions;
- adds bounded-staleness behavior for sustained summarizer failure;
- replaces ambiguous invalidation verbs with named operational actions;
- explicitly versions and changes the pure workflow-transition signature;
- removes browser-mirror signing from Phase 1;
- fixes fail-closed memory behavior as a decision rather than an open question;
- makes performance gates conditional on a pinned reference workstation.

## 1. Objective

Build the pilot-critical memory foundation that lets Sage remain consistent across
long conversations, browser reloads, server restarts, and engineering asset
revisions without treating prior model prose as authoritative engineering truth.

Phase 1 must provide four capabilities:

1. Server-side conversation and workflow-state persistence.
2. Bounded short-term context using recent turns plus a structured rolling
   continuity summary.
3. A deterministic, versioned Memory Envelope for every Sage turn.
4. Revision-aware invalidation that preserves the user's objective while
   invalidating stale evidence, previews, and conclusions.

The target is not to make Sage remember everything. The target is to make the
right current state, approved history, and relevant continuity available at the
right time with explicit provenance and deterministic precedence.

## 2. Pilot Success Statement

For the same authenticated principal, conversation, active workflow, asset scope,
source revisions, skill versions, and current user request, InspectorPro should
construct the same Memory Envelope and authorize the same deterministic tool and
workflow behavior.

Model wording may vary. The following may not vary silently:

- the active asset identity;
- the source revision vector;
- the selected workflow and available tools;
- the evidence supplied as authoritative;
- stale-memory invalidation decisions;
- write authorization;
- transaction and approval requirements;
- tool idempotency behavior.

## 3. Binding Architecture Decisions

### 3.1 Current state is observed, not remembered

Saved engineering state and validated live-editor facts must be rebuilt from
trusted server providers on every relevant turn. Conversation memory may help
resolve continuity, but it must never override current CAD, drawing, FAI,
Process Map, Facility Layout, or transaction state.

### 3.2 The server is the memory authority

Browser storage becomes a cache and recovery aid. It is not the canonical source
for conversation history, workflow state, summaries, evidence references, or
tool receipts once Phase 1 is enabled.

### 3.3 Model prose is not durable engineering knowledge

Ordinary assistant responses may remain in the transcript, but they do not
become authoritative facts. A model-generated summary is continuity context and
must be labeled untrusted until a fact is re-established by a trusted provider
or an existing approved source artifact.

### 3.4 Phase 1 does not introduce a generic vector database

InspectorPro already has strong structured identities, graphs, revisions, and
context providers. Phase 1 uses those deterministic mechanisms. Hybrid retrieval
over unstructured manuals and procedures belongs to a later phase.

### 3.5 SQLite is the first persistence implementation

Use SQLite for local and customer-hosted pilots through a repository interface
that does not expose SQLite-specific behavior to the memory service. A later
PostgreSQL implementation must be possible without changing the Memory Envelope
or API contracts.

This is binding for Commitment A's current single-host pilot. Replace the P1.1
adapter with PostgreSQL before implementation only if the committed pilot
deployment requires any of the following:

- independently scaled application replicas writing the same memory store;
- a shared/network filesystem for the database file;
- multi-host high availability or automatic database failover;
- a managed relational service mandated by the customer;
- ephemeral application storage with no supported durable local volume.

Do not implement SQLite and then change databases midway through Commitment A.
If a trigger applies, retain the repository/API contracts and rebaseline P1.1
against PostgreSQL before code begins.

SQLite requirements:

- WAL journal mode;
- foreign keys enabled;
- configurable busy timeout;
- explicit transactions;
- schema migrations;
- no process-local write queue as the only durability mechanism;
- one database file under a configurable runtime path;
- deterministic JSON serialization for hashes and revisions.

### 3.6 Stable scope and source revision are separate concepts

The current workflow-state fingerprint combines asset identity and revision. In
Phase 1 these become separate:

- `scopeFingerprint` identifies the same product, map, layout, or assembly.
- `revisionVector` identifies the exact evidence revisions used on a turn.

A same-scope revision change may preserve the objective while invalidating stale
evidence. A scope change does not inherit workflow state unless the user
explicitly requests a cross-scope operation.

### 3.7 Existing trusted-context and transaction systems remain authoritative

Phase 1 extends, rather than replaces:

- `compile_skill_context` and skill context contracts;
- server-side Process Map and Facility Layout context resolution;
- `advance_workflow_state_v2` as the pure workflow transition function, with the
  signature and migration defined in Section 17.7;
- deterministic router validation;
- tool receipts;
- Builder preview, approval, CAS, and atomic-commit rules.

### 3.8 Every committed turn is idempotent

The browser supplies a unique client turn ID. The server binds it to the
authenticated principal, conversation, agent session, and request hash. Retrying
the same turn may return the committed result but must not repeat a tool effect or
create duplicate messages.

The canonical request-hash contract is frozen in Section 18.2. Implementations
may not add volatile client fields to that hash without a schema-version change.

### 3.9 Memory outages fail closed by default

All action/write turns fail closed when durable turn, workflow-state, and receipt
storage is unavailable. Read-only stateless fallback is also disabled by default.

An environment may explicitly enable read-only stateless fallback only for turns
that can be answered from the current trusted state and current request without
workflow continuity. The response must carry `memoryUnavailable=true` and
`continuityMode=stateless`; the UI must surface this state. Stateless fallback
can never execute a tool, apply a preview, approve a transaction, or reuse a
prior referent.

### 3.10 Action authorization has a just-in-time revision barrier

An action, preview, or approval may not rely only on the revision vector captured
when its turn started. Immediately before the authoritative preview creation or
side effect, the server reloads the current trusted revision vector and compares
it with the turn's authorized vector. A mismatch fails before the effect with
`revision_advanced_during_turn`, invalidates affected previews and approval
tokens, and requires a new turn against current state.

The existing Builder/CAS check remains the final write guard and closes the race
between this pre-effect check and the actual asset commit. Read-only turns may
finish against their captured snapshot, but must return both the source revision
and any newer current revision detected before response commit.

## 4. Verified Current Baseline

The following baseline was verified in the current code before this plan was
written.

### 4.1 Browser conversation registry

`static/index.html` stores a versioned chat registry in browser `localStorage`.
Each conversation contains one session per public agent, full structured
messages, a browser-generated chat session ID, a summary field, workflow state,
and pending cross-agent context.

Current limitation:

- it is browser-local;
- it is not tenant-authoritative;
- it is not available on another browser or device;
- a server cannot audit or reconstruct it independently;
- storage growth is not governed by a server retention policy.

### 4.2 Main answer history

The browser flattens every non-pending user and assistant message and sends the
complete transcript on each agent request. The server then forwards all supplied
history to the answer provider. For OpenAI, `_openai_responses_input` converts
earlier turns into one delimited `<conversation_history>` text block inside the
final user input. For Anthropic, `_invoke_agent_model` passes the normalized turn
list directly as `messages`, retaining user/assistant roles.

Current limitation:

- input grows with every turn;
- earlier contradictions remain present indefinitely;
- irrelevant turns compete with current trusted evidence;
- there is no hard whole-turn history budget;
- the OpenAI adapter embeds earlier history as a delimited transcript in the
  final user input rather than as provider-native role history.

### 4.3 Router continuity

The semantic router receives only the last four turns, truncated to 400
characters per turn, plus a structured workflow-state object and a live target
index.

This is a good bounded-memory pattern and should remain.

### 4.4 Workflow state

`ai_inspector/agent_skills/workflow_state.py` implements:

- a pure workflow transition;
- objective, stage, status, entities, evidence references, and referents;
- milestones and compact tool receipts;
- asset-fingerprint validation;
- a thread-safe TTL/LRU store;
- a browser mirror sanitizer;
- explicit abandon, expiration, and asset-change behavior.

The production store currently defaults to:

- 30-minute TTL;
- 512 sessions;
- process memory only;
- browser-mirror recovery after a server restart.

Current limitation:

- it is not durable server state;
- any revision included in the asset fingerprint invalidates the complete state;
- recovery depends on a client mirror;
- it does not support audit queries across sessions.

### 4.5 Context compiler

`ai_inspector/prompts/context.py` maps declared context-provider IDs to fields,
applies skill requirements, removes undeclared fields, computes provenance, and
prunes optional context under a contract budget.

Current limitation:

- required context that still exceeds the budget produces a warning but is not
  rejected or reduced by a domain-specific digest;
- context accounting is logged but not attached to a durable per-turn manifest;
- conversation continuity has a separate, unbounded path.

### 4.6 Trusted engineering providers

Before prompting, `_resolve_trusted_process_map_context` and
`_resolve_trusted_facility_layout_context` remove browser-supplied derived
context and replace browser references with current server authority for:

- Process Map graph, state, evidence, revision, proposal, and receipts;
- Facility Layout digest, state, evidence, revision, proposal, and receipts.

This behavior is the model for all memory-sensitive workflows: the browser names
the scope, but the server loads and verifies the data.

### 4.7 Cross-agent summary

The existing `/api/agent/summarize` endpoint creates a short free-text summary
when switching agents and injects it once into the target agent.

Current limitation:

- it is not structured;
- it has no claim-level source turn IDs;
- it does not model correction or supersession;
- it depends on one provider-specific summarization path;
- it is not a general context-window manager.

### 4.8 Current RAG

ASME visual references are selected through deterministic keyword-to-directory
mapping and a bounded image loader.

This is useful domain retrieval, but it is not a general long-term memory system.

## 5. Memory Vocabulary

### 5.1 Authoritative observation

Current state loaded from a trusted server provider at the start of the turn.
Examples: saved map revision, FAI row, selected layout ID, live dirty state,
available tool capability, current proposal.

### 5.2 Source evidence

A record from CAD, a drawing, an inspection table, an approved procedure, an ERP
record, a process-map asset, or another revisioned source. Evidence has a source
ID and source revision.

### 5.3 Workflow state

Structured continuity required to finish a multi-turn task: objective, stage,
entities, referents, pending clarification, and recent execution receipts.

### 5.4 Conversation continuity

Recent turns and a structured rolling summary. This helps interpret pronouns,
corrections, and goals, but it is not engineering authority.

### 5.5 Approved decision

A decision already stored in an authoritative application artifact or represented
by a validated approval/commit receipt. Phase 1 may retrieve and present these.
Creating a general company-wide decision ledger is deferred to Phase 2.

### 5.6 Assumption

A proposition used for planning that lacks authoritative evidence. Assumptions
must remain visibly distinct from facts and approved decisions.

### 5.7 Tool receipt

The immutable result of an attempted deterministic tool action, including action
identity, status, affected revision, warnings, and created IDs.

### 5.8 Context manifest

The non-secret audit record describing what the Memory Envelope contained, why it
was included, its source revision, token allocation, hash, and any omission.

## 6. Trust and Precedence Rules

When two inputs conflict, use this precedence order:

1. System and safety policy.
2. Current authenticated permissions and tool policy.
3. Current trusted saved/live observation.
4. Applicable approved source artifacts and approval receipts.
5. Current revisioned source evidence.
6. Validated workflow state.
7. Explicit current-turn user instruction.
8. Recent user continuity statements.
9. Structured continuity summary.
10. Prior assistant prose.

Additional rules:

- A current user instruction may set an objective but cannot redefine current
  saved engineering facts.
- A user-provided engineering value is a `user_claim` until written into an
  authorized source artifact or independently observed.
- Prior assistant prose cannot establish a dimension, requirement, approval,
  process sequence, facility clearance, or inspection result.
- A summary cannot upgrade the authority of its source turns.
- Current live state always overrides a remembered viewport state.
- A stale approval receipt remains audit history but cannot authorize a new
  effect.

## 7. Scope

### 7.1 Included

- server-owned conversation identities;
- server-owned agent-session identities;
- durable committed turn storage;
- durable workflow state;
- idempotent turn processing;
- structured rolling continuity summaries;
- bounded recent-turn selection;
- Memory Envelope v1;
- per-turn context manifests;
- stable scope fingerprints;
- source revision vectors;
- revision-aware state reconciliation;
- localStorage-to-server transition behavior;
- conversation deletion and retention;
- shadow, compare, and enforce rollout modes;
- restart, conflict, privacy, and long-conversation tests.

### 7.2 Explicitly excluded

- generic vector-store infrastructure;
- enterprise search across every customer document;
- personal preference memory;
- automatic long-term storage of assistant conclusions;
- a company-wide approved-decision ledger;
- collaborative memory editing;
- PostgreSQL implementation;
- model fine-tuning or continual training;
- changes to Builder approval or atomic-write semantics;
- replacing the skill router;
- storing screenshots or image base64 in memory tables;
- automatic upload of existing browser-local transcripts without user consent.

## 8. High-Level Architecture

```text
Browser
  -> server-issued conversation ID
  -> server-issued agent-session ID
  -> client turn ID and current request
  -> current asset reference and validated live facts

Memory API / Chat Orchestrator
  -> resolve authenticated principal
  -> create or resume pending turn idempotently
  -> load durable workflow state and continuity summary
  -> resolve current trusted engineering context
  -> reconcile stable scope and revision vector
  -> compile selected skill context
  -> select bounded recent turns
  -> build Memory Envelope v1
  -> persist context manifest hash

Router / Sage / Deterministic Executors
  -> route from current request, live targets, workflow state, recent turns
  -> answer or propose action
  -> validate and execute permitted tools
  -> collect immutable receipts

Commit
  -> atomically commit assistant response, receipts, workflow-state update,
     turn status, and summary work marker
  -> emit terminal HTTP/SSE result
  -> update rolling summary asynchronously
```

Deterministic fast paths must also commit a normal turn. Bypassing the model does
not mean bypassing continuity, idempotency, or audit records.

## 9. Proposed Module Layout

```text
ai_inspector/memory/
  __init__.py
  models.py
  ids.py
  policy.py
  repository.py
  sqlite_repository.py
  service.py
  envelope.py
  context_manifest.py
  summarizer.py
  invalidation.py
  retention.py

tests/
  test_memory_models.py
  test_memory_sqlite_repository.py
  test_memory_service.py
  test_memory_envelope.py
  test_memory_summary.py
  test_memory_invalidation.py
  test_memory_api.py
  test_memory_agent_integration.py
  test_memory_tenant_isolation.py
  test_memory_frontend.js
  fixtures/memory/
```

Integration changes are expected in:

- `server.py` for request orchestration and compatibility endpoints;
- `static/index.html` for server conversation IDs and local cache behavior;
- `ai_inspector/agent_skills/workflow_state.py` for the persistence adapter and
  stable-scope reconciliation inputs;
- `ai_inspector/prompts/context.py` for envelope-aware accounting and hard budget
  behavior;
- provider adapters only where bounded history replaces full transcript input.

Do not place SQL, summary prompts, or invalidation logic directly into
`server.py`.

## 10. Principal and Scope Model

### 10.1 Principal

All memory reads and writes are scoped by a server-resolved principal:

```json
{
  "tenantId": "tenant-local-or-authenticated",
  "userId": "user-local-or-authenticated",
  "roles": ["operator"]
}
```

Rules:

- never accept `tenantId` or `userId` as authority from the browser payload;
- reuse authenticated Facility Layout principal resolution where applicable;
- local mode receives explicit stable IDs such as `local` and `local-user`;
- every repository query includes `tenantId`;
- user-specific chat listing also includes `userId` unless a future role permits
  shared access;
- cross-tenant conversation IDs return 404 rather than disclosing existence.

### 10.2 Stable scope

Examples:

```json
{
  "kind": "process_map",
  "ids": {
    "productId": "tricycle",
    "mapId": "default"
  },
  "scopeFingerprint": "scope-v1:..."
}
```

```json
{
  "kind": "facility_layout",
  "ids": {
    "siteId": "site-local",
    "layoutId": "default"
  },
  "scopeFingerprint": "scope-v1:..."
}
```

CAD/FAI scope may include:

- part number;
- assembly number;
- active configuration;
- inspection profile ID.

Stable scope excludes mutable content revisions.

### 10.3 Revision vector

The exact fields depend on the active scope. The envelope uses one normalized
mapping:

```json
{
  "processMapRevision": "sha256-or-null",
  "productStructureRevision": "sha256-or-null",
  "assemblyKnowledgeRevision": "sha256-or-null",
  "facilityLayoutRevision": "sha256-or-null",
  "facilityShellRevision": "sha256-or-null",
  "facilityPolicyRevision": "sha256-or-null",
  "partRevision": "revision-or-null",
  "drawingRevision": "revision-or-null",
  "faiRevision": "revision-or-null",
  "motionAssetPin": "pin-or-null"
}
```

Only populated fields participate in the revision-vector hash.

## 11. Persistence Schema

All JSON columns are canonical ASCII JSON with sorted keys and compact
separators before hashing. Timestamps are server-stamped UTC ISO-8601 values.

### 11.1 `memory_schema_migrations`

```text
version INTEGER PRIMARY KEY
applied_at_utc TEXT NOT NULL
sha256 TEXT NOT NULL
```

Migrations must be forward-only and transactional.

### 11.2 `memory_conversations`

```text
conversation_id TEXT PRIMARY KEY
tenant_id TEXT NOT NULL
user_id TEXT NOT NULL
title TEXT NOT NULL
status TEXT NOT NULL              active | archived | deleted
schema_version INTEGER NOT NULL
created_at_utc TEXT NOT NULL
updated_at_utc TEXT NOT NULL
last_turn_sequence INTEGER NOT NULL DEFAULT 0
retention_until_utc TEXT
metadata_json TEXT NOT NULL
```

Indexes:

- `(tenant_id, user_id, updated_at_utc DESC)`;
- `(tenant_id, status, retention_until_utc)`.

### 11.3 `memory_agent_sessions`

```text
agent_session_id TEXT PRIMARY KEY
conversation_id TEXT NOT NULL REFERENCES memory_conversations
tenant_id TEXT NOT NULL
agent_type TEXT NOT NULL
status TEXT NOT NULL              active | completed | abandoned
scope_fingerprint TEXT
revision_vector_json TEXT NOT NULL
workflow_state_json TEXT
workflow_state_revision INTEGER NOT NULL DEFAULT 0
summary_revision INTEGER NOT NULL DEFAULT 0
created_at_utc TEXT NOT NULL
updated_at_utc TEXT NOT NULL
expires_at_utc TEXT
```

Unique constraint:

- `(tenant_id, conversation_id, agent_type, agent_session_id)`.

### 11.4 `memory_turns`

One row represents one user request and its terminal assistant result.

```text
turn_id TEXT PRIMARY KEY
tenant_id TEXT NOT NULL
conversation_id TEXT NOT NULL REFERENCES memory_conversations
agent_session_id TEXT NOT NULL REFERENCES memory_agent_sessions
sequence INTEGER NOT NULL
client_turn_id TEXT NOT NULL
request_hash_version INTEGER NOT NULL
request_identity_json TEXT NOT NULL
request_sha256 TEXT NOT NULL
status TEXT NOT NULL              pending | committed | failed | cancelled
user_message_json TEXT NOT NULL
assistant_result_json TEXT
tool_receipts_json TEXT NOT NULL
route_metadata_json TEXT NOT NULL
model_metadata_json TEXT NOT NULL
scope_fingerprint TEXT
source_revision_vector_json TEXT NOT NULL
resulting_revision_vector_json TEXT
revision_barrier_json TEXT NOT NULL
memory_envelope_sha256 TEXT
context_manifest_id TEXT
error_code TEXT
created_at_utc TEXT NOT NULL
committed_at_utc TEXT
```

Constraints:

- unique `(tenant_id, conversation_id, agent_session_id, client_turn_id)`;
- unique `(tenant_id, conversation_id, sequence)`;
- `request_identity_json` must validate against the matching closed request-hash
  version and reproduce `request_sha256` byte-for-byte;
- a committed turn requires `assistant_result_json`, `committed_at_utc`,
  `resulting_revision_vector_json`, and `memory_envelope_sha256`;
- `revision_barrier_json` records classification, pre-effect comparison, CAS
  outcome, and any post-effect drift without raw asset content;
- tool receipts must be empty until execution or terminal rejection.

### 11.5 `memory_summaries`

```text
summary_id TEXT PRIMARY KEY
tenant_id TEXT NOT NULL
conversation_id TEXT NOT NULL
agent_session_id TEXT NOT NULL
summary_revision INTEGER NOT NULL
through_turn_sequence INTEGER NOT NULL
source_turn_sha256 TEXT NOT NULL
summary_json TEXT NOT NULL
summary_sha256 TEXT NOT NULL
status TEXT NOT NULL              current | superseded | failed
model_metadata_json TEXT NOT NULL
created_at_utc TEXT NOT NULL
```

Unique constraint:

- `(tenant_id, agent_session_id, summary_revision)`.

### 11.6 `memory_context_manifests`

```text
context_manifest_id TEXT PRIMARY KEY
tenant_id TEXT NOT NULL
conversation_id TEXT NOT NULL
agent_session_id TEXT NOT NULL
turn_id TEXT NOT NULL
schema_version INTEGER NOT NULL
scope_fingerprint TEXT
revision_vector_sha256 TEXT NOT NULL
memory_envelope_sha256 TEXT NOT NULL
manifest_json TEXT NOT NULL
created_at_utc TEXT NOT NULL
```

The manifest records source metadata, hashes, token accounting, and omissions.
It does not duplicate full CAD data, images, prompts, or secrets.

## 12. Structured Continuity Summary v1

The rolling summary is not a prose paragraph. Its schema is:

```json
{
  "schemaVersion": "sage-continuity-summary-1.0",
  "summaryRevision": 3,
  "throughTurnSequence": 18,
  "objective": {
    "text": "Generate and review a Tricycle process map",
    "sourceTurnIds": ["turn-..."]
  },
  "userClaims": [
    {
      "claimId": "claim-...",
      "text": "The user says the workstation is already approved",
      "status": "active",
      "sourceTurnIds": ["turn-..."],
      "supersedesClaimId": null
    }
  ],
  "continuityDecisions": [
    {
      "text": "Preserve manually positioned nodes",
      "authority": "conversation_only",
      "sourceTurnIds": ["turn-..."]
    }
  ],
  "assumptions": [
    {
      "text": "Assembly sequence remains inferred",
      "status": "open",
      "sourceTurnIds": ["turn-..."]
    }
  ],
  "corrections": [
    {
      "text": "Use 30 mm, not 32 mm, for the stated nominal",
      "sourceTurnIds": ["turn-..."],
      "supersededClaimIds": ["claim-..."]
    }
  ],
  "openQuestions": [
    {
      "text": "Which approved procedure defines the operation order?",
      "sourceTurnIds": ["turn-..."]
    }
  ],
  "referencedEntities": [
    {
      "kind": "process_map",
      "id": "default",
      "label": "Tricycle process map"
    }
  ],
  "sourceEvidenceRefs": [],
  "warnings": []
}
```

Summary rules:

- every item cites one or more source turn IDs;
- assistant-only engineering values may not be promoted to `userClaims`;
- a user claim remains `conversation_only` and is never labeled observed fact;
- approved source decisions are not copied into this summary as authority; they
  are independently loaded from their source artifact;
- corrections supersede earlier continuity claims rather than deleting audit
  history;
- unresolved questions persist until answered or explicitly dismissed;
- stale evidence references are marked, not silently reused;
- the summary payload is schema-validated and size-bounded;
- invalid output is rejected and the previous valid summary remains current.

## 13. Summary Generation Policy

### 13.1 Trigger

Create or update a summary when either condition is met:

- more than eight committed turns are not represented by the current summary;
- unsummarized text exceeds 3,200 estimated tokens.

Always preserve the six most recent complete turns outside the summary.

### 13.2 Incremental input

The summarizer receives:

- the previous structured summary, if any;
- only turns after `throughTurnSequence`;
- source turn IDs;
- current stable scope identity;
- no trusted engineering context unless required to validate an evidence ID.

It must not receive the entire historical transcript on every update.

### 13.3 Provider behavior

- use one pinned, validated memory-summary provider and model configuration;
- do not automatically follow the answer provider selected for the current turn;
- request strict JSON when supported;
- bound timeout, output tokens, and retry count;
- record provider/model/version in summary metadata;
- never make summary success a prerequisite for authoritative current-state
  loading;
- on timeout or invalid output, retain the old summary and include additional
  recent unsummarized turns within the continuity budget;
- do not silently fall back to a different model without recording it.

### 13.4 Bounded-staleness guard

Summary failure may not silently create a missing middle in the context. Track:

```text
unsummarizedTurnCount
unsummarizedTokenEstimate
summaryAgeTurns
oldestUnsummarizedTurnSequence
```

Initial thresholds:

```text
Soft stale: more than 8 unsummarized turns, more than 3,200 estimated tokens,
            or any unsummarized committed turn would be omitted by the current
            recent-turn allocation
Hard stale: more than 16 unsummarized turns or 6,400 estimated tokens
```

At the soft threshold:

1. Mark the session `continuity_degraded`.
2. Attempt one bounded synchronous summary refresh before an action turn. Use one
   provider request, no fallback model, and a total wall-clock deadline of 5,000
   ms by default.
3. If that refresh fails, block the action turn with
   `continuity_summary_refresh_required`; do not ask the model to infer whether
   the omitted range matters.
4. Surface a non-blocking warning for read-only turns.
5. Record the failure and unsummarized range in the context manifest.

At the hard threshold:

1. Fail closed for all action/write turns with
   `continuity_summary_stale` before routing or tool execution.
2. Fail closed for a continuation that depends on an omitted historical
   correction, referent, approval, or unresolved question.
3. Permit a read-only stateless turn only when the request is independently
   answerable from current trusted state plus the current request and the
   environment explicitly enables stateless read fallback.
4. Attach `continuityMode=degraded` or `continuityMode=stateless` to the response
   and show it in the UI.
5. Never represent a six-turn recent window as complete continuity when older
   unsummarized turns have been omitted.

The hard-stale state clears only after a valid summary covers the missing turn
range, the user explicitly starts a new conversation, or the workflow is
abandoned and restarted without historical continuity.

### 13.5 Asynchronous commit

The assistant turn commits before summary generation. Summary generation runs
after the terminal turn is durable. The next request may use the previous summary
plus newer turns.

Use a database work marker or compare-and-swap on `summaryRevision`; do not rely
on an untracked background task that is lost on restart.

## 14. Bounded Context Policy

### 14.1 Main-agent history

Replace full transcript forwarding with:

- current structured continuity summary;
- latest six complete turns, reduced further only when their token allocation is
  exceeded;
- current user request;
- current workflow state;
- current trusted context selected by skill contracts.

Never split a turn in the middle merely to fit the budget. Prefer fewer complete
turns. If this selection would omit unsummarized turns beyond the thresholds in
Section 13.4, apply the degraded-context policy rather than silently truncating.

### 14.2 Initial configurable budgets

These are allocation defaults, not model context-window claims:

```text
Compiled trusted skill context: existing contract maximum, normally 6,000 tokens
Workflow state and receipts: 800 tokens
Continuity summary: 1,200 tokens
Recent complete turns: 2,400 tokens
Cross-agent continuity projection: 600 tokens
Envelope metadata and manifests: 600 tokens
Current user request: up to 2,000 tokens before explicit oversized-input handling
```

Images are counted separately by provider-specific accounting and only belong to
the current request or selected trusted visual evidence.

### 14.3 Hard budget behavior

- required trusted context is never silently removed;
- optional context is removed according to the selected skill contract;
- if required context exceeds its contract budget, first use an existing
  deterministic domain digest;
- if no valid digest can satisfy the contract, fail with
  `required_context_budget_exceeded` and identify the provider that exceeded it;
- do not send an over-budget request merely with a warning;
- summary and recent-history omission is recorded in the context manifest;
- current user request and safety policy cannot be summarized away.

### 14.4 Router history

Keep the existing last-four-turn router policy. Feed it the most recent complete
turns plus validated workflow state. Do not feed the full continuity summary to
the semantic router unless an evaluation proves it improves referent resolution
without increasing stale carryover.

## 15. Memory Envelope v1

### 15.1 Schema

```json
{
  "schemaVersion": "sage-memory-envelope-1.0",
  "identity": {
    "conversationId": "conv-...",
    "agentSessionId": "agent-session-...",
    "turnId": "turn-...",
    "agentType": "deviation-analyst"
  },
  "scope": {
    "kind": "process_map",
    "ids": {
      "productId": "tricycle",
      "mapId": "default"
    },
    "scopeFingerprint": "scope-v1:...",
    "revisionVector": {
      "processMapRevision": "...",
      "productStructureRevision": "..."
    }
  },
  "workflow": {
    "workflowId": "process-map-generation",
    "workflowVersion": "1.0.0",
    "status": "active",
    "stage": "draft_plan",
    "objective": "Build a complete process-map preview",
    "entities": {},
    "referents": {},
    "pendingClarification": null
  },
  "observations": {
    "trustedContext": {},
    "liveStateOverridesMemory": true
  },
  "approvedSourceDecisions": [],
  "continuity": {
    "status": "healthy",
    "summary": {},
    "recentTurns": [],
    "throughTurnSequence": 18,
    "unsummarizedTurnCount": 0,
    "oldestUnsummarizedTurnSequence": null,
    "authority": "untrusted_continuity"
  },
  "receipts": [],
  "capabilities": {
    "selectedSkills": [],
    "allowedTools": [],
    "restrictions": []
  },
  "budget": {
    "allocations": {},
    "estimatedTokens": 0,
    "omissions": []
  },
  "provenance": {
    "contextManifestId": "context-...",
    "sourceHashes": {},
    "warnings": []
  }
}
```

`continuity.status` is `healthy`, `degraded`, or `stateless`. A hard-stale action
turn fails before constructing an action-capable envelope.

### 15.2 Construction order

1. Resolve principal and conversation ownership.
2. Load the existing committed agent session.
3. Resolve current trusted engineering state.
4. Compute stable scope and revision vector.
5. Reconcile workflow state against scope and revisions.
6. Route and select the skill composition.
7. Compile required and optional trusted context.
8. Load the current validated continuity summary.
9. Select bounded recent turns.
10. Resolve applicable approved decisions from existing source artifacts.
11. Attach recent validated receipts.
12. Apply section budgets and omission policy.
13. Canonicalize and hash the envelope.
14. Persist the context manifest before the model call.

### 15.3 Prompt boundaries

Render envelope sections into clearly separated tags:

```text
<trusted_current_state>
...
</trusted_current_state>

<trusted_source_decisions>
...
</trusted_source_decisions>

<workflow_continuity>
...
</workflow_continuity>

<untrusted_conversation_summary>
...
</untrusted_conversation_summary>

<untrusted_recent_turns>
...
</untrusted_recent_turns>

<user_request>
...
</user_request>
```

Do not merge prior conversation, trusted context, and the current request into one
undifferentiated text block.

## 16. Context Manifest v1

For every turn, store metadata similar to:

```json
{
  "schemaVersion": "sage-context-manifest-1.0",
  "turnId": "turn-...",
  "memoryEnvelopeSha256": "...",
  "providers": [
    {
      "contextKey": "process_map.state",
      "origin": "server",
      "requestedBy": ["generate-process-map"],
      "required": true,
      "sourceIds": ["tricycle/default"],
      "sourceRevisions": ["..."],
      "included": true,
      "estimatedTokens": 740,
      "payloadSha256": "...",
      "omissionReason": null
    }
  ],
  "continuity": {
    "status": "healthy",
    "summaryRevision": 3,
    "throughTurnSequence": 18,
    "recentTurnIds": ["turn-..."],
    "omittedTurnCount": 22,
    "unsummarizedTurnCount": 0,
    "oldestUnsummarizedTurnSequence": null,
    "allUnsummarizedTurnsIncluded": true
  },
  "revisionBarrier": {
    "classification": "action_write",
    "sourceRevisionVectorSha256": "...",
    "preEffectRevisionVectorSha256": "...",
    "outcome": "matched",
    "resultingRevisionVectorSha256": "...",
    "postEffectRevisionDrift": false
  },
  "budget": {
    "maximum": 13600,
    "estimated": 10920,
    "exceeded": false
  },
  "warnings": []
}
```

The manifest supports replay and diagnosis without logging raw customer content.

## 17. Revision-Aware Reconciliation

### 17.1 Reconciliation outcomes

```text
same_scope_same_revisions
same_scope_revision_advanced
same_scope_dependency_removed
scope_changed
workflow_version_changed
memory_expired
explicitly_abandoned
```

### 17.2 Same scope, same revisions

Resume validated workflow state and referents. Revalidate live target IDs and
tool availability before use.

### 17.3 Same scope, revision advanced

Preserve:

- conversation identity;
- user objective;
- workflow identity when still registered;
- workflow stage when still valid;
- user-authored continuity statements;
- audit history and past receipts.

Revalidate or invalidate:

- entity and referent IDs against current target indexes;
- evidence references tied to changed sources;
- calculated conclusions derived from changed evidence;
- pending previews;
- approval tokens;
- route candidates based on removed nodes or assets;
- summaries that cite stale source evidence.

Past receipts remain historical and lose all authorization value.

### 17.4 Scope changed

Start a new workflow state. Do not copy entities, referents, evidence references,
or open previews. The conversation transcript remains visible, but its summary is
not injected into the new scope unless the user explicitly requests a comparison
or cross-scope task.

### 17.5 Workflow package version changed

Use an explicit migration function keyed by old and new workflow versions. If no
migration exists:

- preserve the user objective as continuity text;
- discard stage-specific workflow state;
- restart at the new workflow's first stage;
- report `workflow_state_migration_unavailable` in the manifest.

### 17.6 Operational invalidation actions

The matrix uses only the following closed action vocabulary. Implement one
table-driven dispatcher, `apply_invalidation_action(action, item,
current_context, changed_dependencies)`, and reject unknown actions.

| Action | Required operational behavior |
| --- | --- |
| `reset` | Replace the active item with its schema default. Do not copy prior content. |
| `preserve` | Copy the item after schema validation. Do not query a source provider. |
| `revalidate` | Resolve referenced IDs through current trusted providers and apply the item-specific current-validity policy below. Retain only successful resolutions. |
| `invalidate` | Remove the item from active memory and record the invalidation reason in audit state. |
| `invalidate_affected` | Intersect the item's declared dependencies with `changed_dependencies`; invalidate only the intersecting subset. |
| `retain_audit_only` | Keep the immutable historical record outside active memory. It cannot enter the Memory Envelope as authorization or current evidence. |
| `never_retain` | Do not copy the item into the next state or any active authorization field. |
| `scope_gate` | Include continuity only for the same stable scope or an explicit user-requested cross-scope comparison. |
| `mark_stale_refs` | Preserve continuity prose, mark affected evidence references stale, and prohibit those references from grounding an answer. |
| `mark_stale_decisions` | Preserve the historical mention, but require the current decision or policy to be reloaded before use. |

`preserve` is a schema-validated copy without a current-source lookup.
`revalidate` consults current trusted providers. They are not interchangeable.
The corresponding implementation handlers should be named `_reset_item`,
`_preserve_item`, `_revalidate_item`, `_invalidate_item`,
`_invalidate_affected`, `_retain_audit_only`, `_never_retain`, `_scope_gate`,
`_mark_stale_refs`, and `_mark_stale_decisions` so the fixture and code use the
same vocabulary.

Workflow-stage `revalidate` has additional binding behavior. Every workflow stage
definition must declare its revision dependencies and whether it is
authorization-bearing (`preview`, `approval`, `apply`, or `execution`). On any
map/layout, structure/evidence, or policy revision:

1. Rebuild the stage's dependencies from current trusted providers.
2. Preserve a non-authorizing stage only when none of its declared dependencies
   changed and its workflow-version transition remains valid.
3. If dependencies changed, regress to the latest declared safe predecessor;
   never advance a stage during reconciliation.
4. Always invalidate authorization-bearing stage state and regress to its safe
   pre-preview/pre-approval checkpoint, even when the stage name still exists.
5. If no valid predecessor mapping exists, reset to the workflow's first stage and
   record `workflow_stage_revalidation_unavailable` in the context manifest.

This policy preserves the user's objective while preventing a prior review or
approval stage from surviving changed evidence merely because its name remains
schema-valid.

### 17.7 Workflow transition v2 signature and migration

The current pure function accepts one combined `asset_fingerprint`. Phase 1 must
change that signature; it cannot preserve the old parameter while also separating
scope identity from revisions.

The new pure transition contract is:

```python
def advance_workflow_state_v2(
    prior,
    *,
    route,
    context_facts,
    scope_fingerprint,
    revision_vector,
    workflow_version,
    workflow_stages,
    now_epoch,
    ttl_seconds,
):
    ...
```

Requirements:

- increment the workflow-state schema from v1 to v2;
- persist `scope_fingerprint` and the normalized `revision_vector` separately;
- derive a `revision_vector_sha256` for comparisons, without replacing the
  structured vector;
- keep `advance_workflow_state_v2` deterministic and free of repository, clock,
  provider, or UI access;
- pass `now_epoch` and all current trusted facts explicitly;
- remove `asset_fingerprint` from newly persisted v2 state after migration;
- migrate every production, store, sanitizer, server, and test caller before
  enforce mode; P1.0 must freeze the exact caller inventory;
- do not add a compatibility wrapper that feeds `scope_fingerprint` into the old
  `asset_fingerprint` parameter, because that would silently discard revision
  reconciliation.

Add `migrate_workflow_state_v1_to_v2(value, current_scope,
current_revision_vector, target_index)`. The old combined hash cannot be
decomposed and must never be guessed. Migration therefore rebuilds scope and
revisions from current trusted server context. It may retain a schema-valid user
objective, workflow ID, stage, and continuity fields; it must revalidate entities
and referents, drop active evidence references, previews, approval tokens, and
effect authorization, and move prior receipts to audit-only history. If current
trusted context is unavailable, migration fails closed and starts no active
workflow state.

### 17.8 Dependency-specific invalidation matrix

Every cell names exactly one action from Section 17.6.

| Memory item | Stable scope change | Map/layout revision | Structure/evidence revision | Policy revision |
| --- | --- | --- | --- | --- |
| Objective | `reset` | `preserve` | `preserve` | `preserve` |
| Workflow stage | `reset` | `revalidate` | `revalidate` | `revalidate` |
| Entity IDs | `reset` | `revalidate` | `revalidate` | `preserve` |
| Referents | `reset` | `revalidate` | `revalidate` | `preserve` |
| Evidence refs | `reset` | `invalidate_affected` | `invalidate_affected` | `invalidate_affected` |
| Semantic preview | `invalidate` | `invalidate` | `invalidate` | `invalidate` |
| Approval token | `invalidate` | `invalidate` | `invalidate` | `invalidate` |
| Past receipt audit | `retain_audit_only` | `retain_audit_only` | `retain_audit_only` | `retain_audit_only` |
| Prior tool authorization | `never_retain` | `never_retain` | `never_retain` | `never_retain` |
| Continuity summary | `scope_gate` | `mark_stale_refs` | `mark_stale_refs` | `mark_stale_decisions` |

## 18. Turn Lifecycle and Idempotency

### 18.1 Request fields

Extend `AgentChatRequest` with optional Phase 1 fields:

```json
{
  "conversation_id": "conv-...",
  "agent_session_id": "agent-session-...",
  "client_turn_id": "browser-generated-uuid",
  "memory_schema_version": "1.0",
  "request_hash_version": 1,
  "request_context": {
    "asset_scope": {},
    "semantic_targets": {}
  }
}
```

The browser freezes `request_context` for retries of that client turn. The server
normalizes and validates it against current trusted providers on first receipt.
Do not accept principal or revision authority from these fields.

### 18.2 Canonical request hash v1

The request hash is a correctness boundary, not a telemetry convenience:

```text
request_sha256 = sha256(canonical_ascii_json(request_identity_v1))
```

`request_identity_v1` has this exact top-level shape:

```json
{
  "requestHashVersion": 1,
  "message": "normalized current user message",
  "agentType": "sage",
  "workflowMode": "process_map",
  "assetScope": {
    "kind": "process_map",
    "ids": {
      "mapId": "default",
      "productId": "tricycle"
    },
    "expectedRevisionVector": {
      "processMapRevision": "sha256-or-null",
      "productStructureRevision": "sha256-or-null"
    }
  },
  "semanticTargets": {
    "partOccurrenceIds": [],
    "processMapNodeIds": [],
    "processMapEdgeIds": [],
    "facilityPlacementIds": [],
    "faiCharacteristicIds": []
  },
  "imageSha256": [],
  "actionParameters": {},
  "crossAgentProjectionSha256": null,
  "memorySchemaVersion": "1.0"
}
```

Included fields are frozen as follows:

- `message`: Unicode NFC normalization and `CRLF`/`CR` to `LF`; preserve all
  other whitespace, punctuation, case, and ordering;
- `agentType`: the normalized requested agent;
- `workflowMode`: the semantic workflow mode, not the selected UI tab;
- `assetScope`: a server-normalized object with exactly `kind`, `ids`, and
  `expectedRevisionVector`. Its v1 variants are:
  - Process Map: `kind=process_map`; IDs `productId` and `mapId`; populated
    revision keys from `processMapRevision`, `productStructureRevision`, and
    `assemblyKnowledgeRevision`;
  - Facility Layout: `kind=facility_layout`; IDs `siteId` and `layoutId`;
    populated revision keys from `facilityLayoutRevision`,
    `facilityShellRevision`, and `facilityPolicyRevision`;
  - CAD/FAI: `kind=cad_fai`; populated IDs from `productId`, `partNumber`,
    `assemblyNumber`, `configuration`, and `inspectionProfileId`; populated
    revision keys from `partRevision`, `drawingRevision`, `faiRevision`,
    `assemblyKnowledgeRevision`, and `motionAssetPin`;
  - no active asset: `{"kind":"none","ids":{},"expectedRevisionVector":{}}`;
  `expectedRevisionVector` uses the exact normalized field names in Section 10.3
  and omits unpopulated keys;
- `semanticTargets`: sorted, deduplicated, server-validated IDs frozen when the
  client turn is created. Active selection is included here because words such as
  "this" or "selected" can change request meaning;
- `imageSha256`: attachment hashes in attachment order, never raw bytes;
- `actionParameters`: only explicit, schema-accepted parameters on the current
  request, with absent optional fields omitted;
- `crossAgentProjectionSha256`: the hash of an explicitly supplied one-time
  cross-agent projection, otherwise `null`;
- `memorySchemaVersion`: the requested compatible memory contract version.

The hash explicitly excludes:

- tenant, user, conversation, agent-session, and client-turn IDs, because they
  are separate server-side key bindings;
- client/server timestamps, request IDs, stream IDs, retry counts, and network
  metadata;
- full transcript, rolling summary, workflow state, context manifest, resolved
  trusted context, route output, and tool receipts;
- provider/model selection and other execution metadata;
- camera, pan, zoom, viewport size, hover, cursor, tooltip, open-panel, and other
  UI-only state;
- raw image bytes and local cache metadata.

Canonicalization uses sorted object keys, compact separators, ASCII-escaped JSON,
finite JSON numbers only, and no insignificant whitespace. Arrays representing
sets are sorted and deduplicated; ordered arrays such as image attachments retain
their order. Any field-set or normalization change requires a new
`requestHashVersion` and migration fixtures.

The browser must retain the frozen semantic targets and expected asset revisions
for retries of the same `client_turn_id`; it must not rebuild them from whatever
is selected later. A retry of an already committed turn with the same hash returns
the original committed result even if the asset has advanced since that commit.
The response reports the original revision vector. A user who wants an answer
against the new revision creates a new client turn.

For an existing client-turn key, compare the retry's canonical identity with the
persisted `request_identity_json` before current-asset reconciliation. Never
substitute a newer revision into a retry hash. New turns still validate their
expected revision vector before any action or write.

### 18.3 Start turn

In one transaction:

1. Validate ownership.
2. Check the unique client-turn key.
3. If committed with the same request hash, return the prior terminal result.
4. If the same ID has a different request hash, return 409
   `client_turn_id_reused`.
5. If pending and not expired, return or attach to the current operation.
6. Allocate the next monotonic conversation sequence.
7. Persist a pending turn before any model or tool call.

### 18.4 Pending-turn revision barrier

Classify each turn as `read_only`, `preview`, or `action_write` before tools are
authorized.

Read-only turns may complete against the revision vector captured at start. Just
before terminal response commit, reload the current vector. If it differs, return
both `sourceRevisionVector` and `currentRevisionVector` with
`revisionAdvancedDuringTurn=true`; do not relabel the answer as current.

For `preview` and `action_write` turns:

1. Immediately before issuing a preview/approval token or invoking a
   side-effecting tool, reload the trusted revision vector.
2. Compare every populated field from the authorized start vector unless the
   selected skill and tool contract declare a smaller closed dependency set.
3. On mismatch, execute no effect, invalidate affected preview/approval state,
   terminally fail the turn with `revision_advanced_during_turn`, and return both
   vectors. Do not replan or retry automatically under the same client turn.
4. Pass the same authorized base revisions into the existing Builder/repository
   CAS operation. The pre-effect check does not replace CAS; CAS closes the race
   between the check and the authoritative asset commit.
5. Require every successful effect receipt to record the authorized before-vector,
   resulting revision IDs, affected dependency fields, and idempotency key.

A successful effect may itself advance an owned revision. Immediately before the
memory turn's terminal commit, compute the expected post-effect vector by applying
only receipt-declared revision changes to the authorized vector and compare it
with current authority. If unrelated revision drift occurred after the effect,
commit the successful receipt and truthfully mark `postEffectRevisionDrift=true`;
do not report the effect as failed or permit another effect. This distinction
prevents a retry from repeating work that already succeeded.

Any persistent action path without an authoritative CAS or equivalent
compare-and-set guard fails closed in Phase 1. Transient viewport actions remain
subject to validated live-state and idempotency checks but do not invent an asset
revision.

### 18.5 Commit turn

Atomically persist:

- terminal assistant result;
- route and selected-skill metadata;
- model/provider metadata;
- complete tool receipts;
- resulting durable workflow state;
- exact scope, authorized source revision vector, resulting revision vector, and
  revision-barrier outcome;
- envelope and context-manifest hashes;
- committed timestamp;
- summary work marker.

Only after this commit may the non-streaming endpoint return success or the
streaming endpoint emit its terminal commit event.

### 18.6 Failure and cancellation

- failures receive a stable error code and terminal status;
- partial assistant text is not canonical history;
- a cancelled model call may commit a cancelled turn without assistant content;
- any tool that already executed must have a receipt even if response generation
  later fails;
- a retry must reconcile receipts before deciding whether execution may resume;
- an action turn may never repeat an already-succeeded effect.

## 19. API Surface

### 19.1 Conversation endpoints

```text
POST   /api/agent/conversations
GET    /api/agent/conversations?cursor=...
GET    /api/agent/conversations/{conversationId}
DELETE /api/agent/conversations/{conversationId}
```

`POST` returns server-generated conversation and per-agent session IDs.

`GET` returns bounded metadata and committed messages. It does not return raw
context envelopes or private tool payloads to ordinary users.

`DELETE` performs soft deletion immediately and queues retention cleanup. The
conversation must disappear from normal queries at once.

### 19.2 Existing chat endpoints

`/api/agent/chat` and its streaming counterpart remain the main send APIs. They
accept Phase 1 identity fields and return:

```json
{
  "memory": {
    "mode": "enforce",
    "conversationId": "conv-...",
    "agentSessionId": "agent-session-...",
    "turnId": "turn-...",
    "turnSequence": 19,
    "workflowStateRevision": 7,
    "summaryRevision": 3,
    "scopeEvent": "same_scope_same_revisions",
    "contextManifestId": "context-...",
    "memoryEnvelopeSha256": "...",
    "warnings": []
  }
}
```

### 19.3 Diagnostic endpoint

Add a pilot-admin-only endpoint:

```text
GET /api/agent/memory/turns/{turnId}/manifest
```

It returns the context manifest metadata, not the raw prompt or full customer
data. Access must be principal and role checked.

## 20. Frontend Transition

### 20.1 New canonical behavior

- create conversations through the server;
- retain server-issued IDs;
- send a new client turn ID with every request;
- render committed server history after reload;
- cache recent committed messages locally for UI responsiveness;
- reconcile local cache with server sequence numbers;
- never restore workflow state from localStorage as authority in enforce mode;
- preserve local pending-input text as a browser convenience only.

### 20.2 Existing local history

Do not silently upload existing `inspectorpro.chat_registry.v1` transcripts.

Rollout behavior:

1. Keep legacy conversations locally as read-only archived chats.
2. Start new server-backed conversations after Phase 1 is enabled.
3. Optionally expose an explicit `Import this conversation` action later.
4. Import requires user confirmation and creates a manifest recording
   `source=browser_legacy_import`.

### 20.3 Cross-agent switching

All public agents remain child sessions of the same conversation. Switching
agents no longer requires a one-time free-text summary call. The target session
receives a bounded cross-agent continuity projection generated from committed
turns and source IDs.

The projection is untrusted continuity and cannot grant tool authorization.

### 20.4 Offline and memory-service errors

- unsent text remains local;
- a request is not shown as committed until the server confirms its turn ID;
- read-only requests may use an explicit stateless fallback only when configured;
- write/action requests fail closed when durable idempotency and receipt storage
  are unavailable;
- the UI displays `Memory unavailable; no action was executed` rather than
  silently continuing an action turn.

## 21. Retention and Deletion

Initial pilot defaults:

```text
Conversation retention: 30 days after last activity
Active workflow lifetime: 24 hours unless completed or abandoned
Recent referent lifetime: 30 minutes
Failed pending turn recovery window: 15 minutes
Context manifest retention: same as conversation
Raw image persistence: disabled
```

All values are server configuration, not client choices.

Retention cleanup must:

- run deterministically from persisted timestamps;
- be safe to repeat;
- delete dependent summaries, turns, and manifests;
- preserve only separately authorized operational audit records;
- record aggregate cleanup metrics without customer content.

## 22. Security and Privacy

### 22.1 Tenant isolation

- every table carries `tenant_id`;
- every read and write filters by server-resolved tenant;
- IDs alone never authorize access;
- cross-tenant IDs return 404;
- tests create same-named parts, maps, and conversations in two tenants;
- no global summary or route cache may omit tenant or context fingerprint from
  its key.

### 22.2 Prompt-injection boundary

- historical conversation and summaries remain explicitly untrusted;
- retrieved customer text cannot modify system, skill, or tool policy;
- current tool schemas come from the registry, not memory;
- a remembered request for a side effect is never replayed without a current
  explicit user request;
- current user intent and deterministic authorization are evaluated each turn.

### 22.3 Sensitive data

- do not persist API keys, authorization headers, cookies, image base64, or raw
  model-provider objects;
- redact configured secret patterns before transcript persistence;
- store provider request IDs only when needed for debugging;
- raw prompts are disabled in production logs by default;
- context manifests use hashes and metadata rather than full source payloads.

### 22.4 SQLite file protection

For local pilots, rely on customer-host filesystem access controls and disk
encryption. Document the database path and backup behavior. Application-level
column encryption is not part of Phase 1, but the repository interface must not
prevent it later.

## 23. Failure Policy

| Failure | Read-only turn | Action/write turn |
| --- | --- | --- |
| Memory DB unavailable | optional explicit stateless fallback | fail closed |
| Summary unavailable below soft threshold | use previous summary plus every unsummarized turn; record warning | use the same complete range and record warning |
| Summary soft stale | continue with visible degraded warning | attempt one bounded refresh, then fail `continuity_summary_refresh_required` |
| Summary hard stale | optional explicit stateless fallback only when current state is sufficient | fail `continuity_summary_stale` before routing/tools |
| Trusted provider unavailable | clarify or fail based on skill contract | fail closed |
| Required context over budget | fail with provider detail | fail closed |
| Stale asset revision | reload current state and reconcile | invalidate proposal/token |
| Revision advances while turn is pending | return captured/current vectors and mark answer historical | fail `revision_advanced_during_turn` before preview/effect |
| CAS detects a race after the pre-effect check | not applicable | apply no effect; return current revision and fail closed |
| Unrelated revision advances after a successful effect | not applicable | commit the receipt, mark `postEffectRevisionDrift`, permit no further effect |
| Invalid client IDs | issue new conversation only with explicit response | fail closed |
| Duplicate committed turn | return committed terminal result | never re-execute |
| Pending turn collision | return 409 or attach to existing stream | never create duplicate |
| Invalid summary JSON | retain previous valid summary | retain previous valid summary, subject to staleness guard |

## 24. Telemetry and Audit

Record content-free or content-minimized metrics:

```text
memory.turn.started
memory.turn.committed
memory.turn.idempotent_replay
memory.turn.failed
memory.turn.revision_barrier_checked
memory.turn.revision_advanced_during_turn
memory.turn.post_effect_revision_drift
memory.summary.started
memory.summary.committed
memory.summary.invalid
memory.summary.soft_stale
memory.summary.hard_stale
memory.summary.action_blocked
memory.workflow.resumed
memory.workflow.reconciled_revision
memory.workflow.scope_changed
memory.context.budget_used
memory.context.optional_omitted
memory.context.required_over_budget
memory.context.envelope_build_ms
memory.repository.operation_ms
memory.retention.deleted
```

Each turn also records:

- selected workflow and skill versions;
- answer provider and model;
- router cache status;
- context manifest ID;
- envelope hash;
- source revision-vector hash;
- resulting revision-vector hash;
- revision-barrier classification and outcome;
- summary revision;
- workflow-state revision;
- tool receipt IDs;
- fallback mode.

Do not include raw user messages, CAD data, or summary text in default telemetry.

## 25. Rollout Configuration

Suggested configuration:

```text
INSPECTORPRO_MEMORY_V1_MODE=off|shadow|compare|enforce
INSPECTORPRO_MEMORY_DB_PATH=.runtime/memory/inspectorpro-memory.sqlite3
INSPECTORPRO_MEMORY_CONVERSATION_RETENTION_DAYS=30
INSPECTORPRO_MEMORY_WORKFLOW_TTL_SECONDS=86400
INSPECTORPRO_MEMORY_REFERENT_TTL_SECONDS=1800
INSPECTORPRO_MEMORY_RECENT_TURNS=6
INSPECTORPRO_MEMORY_SUMMARY_MAX_TOKENS=1200
INSPECTORPRO_MEMORY_HISTORY_MAX_TOKENS=2400
INSPECTORPRO_MEMORY_SUMMARY_MODEL=<configured-model>
INSPECTORPRO_MEMORY_SUMMARY_SOFT_STALE_TURNS=8
INSPECTORPRO_MEMORY_SUMMARY_SOFT_STALE_TOKENS=3200
INSPECTORPRO_MEMORY_SUMMARY_HARD_STALE_TURNS=16
INSPECTORPRO_MEMORY_SUMMARY_HARD_STALE_TOKENS=6400
INSPECTORPRO_MEMORY_SUMMARY_SYNC_REFRESH_TIMEOUT_MS=5000
INSPECTORPRO_MEMORY_STATELESS_READ_FALLBACK=false
```

Modes:

### Off

Current behavior remains unchanged.

### Shadow

Persist turns, build summaries and envelopes, and compute invalidation decisions.
Do not alter the prompt or workflow-state source. Compare results offline.

### Compare

Build both legacy full-history input and bounded Memory Envelope input. Send only
the legacy path to the answer model, but record token, provider, source, and
decision differences. No duplicate paid answer call is required.

### Enforce

Use server memory, bounded history, durable workflow state, hard budgets, and
revision-aware reconciliation. Browser state is cache only.

Enable enforce mode per pilot tenant after shadow gates pass.

## 26. Implementation Checkpoints

### P1.0 - Baseline and contract freeze

Work:

- record current test counts for workflow state, prompt compilation, context
  evidence, chat streaming, Process Map, Facility Layout, and frontend sessions;
- capture current prompt/history token behavior on short, medium, and long chats;
- freeze Memory Envelope, summary, manifest, principal, scope, revision-vector,
  request-hash v1, workflow-state v2, invalidation-action, and pending-turn
  revision-barrier contracts as fixtures;
- freeze workflow-stage dependency, authorization-bearing, and safe-predecessor
  metadata for every registered workflow;
- record existing browser registry behavior;
- confirm answer-provider behavior for Anthropic and OpenAI histories;
- confirm Process Map and Facility Layout trusted-provider substitution paths;
- inventory every production and test occurrence that produces, consumes,
  serializes, validates, projects, or tests `asset_fingerprint` or
  `advance_workflow_state`;
- pin the reference workstation and benchmark configuration required by
  Section 28;
- record the committed pilot deployment topology and evaluate every PostgreSQL
  trigger in Section 3.5;
- document pilot local-principal and hosted-principal mapping.

Artifacts:

- `docs/sage-memory-phase-1-baseline.md`;
- JSON schema files or closed fixture contracts;
- short/medium/long transcript accounting fixtures;
- revision-invalidation matrix fixture using only Section 17.6 action names;
- workflow-stage revalidation and safe-regression fixtures;
- canonical request-hash positive/negative fixtures;
- pending-turn revision-drift and post-effect receipt fixtures;
- `tests/fixtures/memory/workflow-state-v1-migration-inventory.json`;
- `tests/fixtures/memory/reference-workstation.json`.

The migration inventory is a closed ledger. It records:

```json
{
  "baselineCommit": "sha256",
  "searchContractVersion": 1,
  "entries": [
    {
      "occurrenceId": "server.py::_workflow_asset_fingerprint::producer::1",
      "path": "server.py",
      "symbol": "_workflow_asset_fingerprint",
      "baselineLine": 24088,
      "sourceSnippetSha256": "sha256",
      "occurrenceKind": "producer",
      "currentContract": "asset_fingerprint_v1",
      "targetContract": "scope_and_revision_v2",
      "migrationDisposition": "pending",
      "verificationFixture": "fixture-id"
    }
  ]
}
```

`occurrenceKind` is closed to `producer`, `consumer`, `serializer`, `schema`,
`api_projection`, or `test`. `migrationDisposition` is closed to `pending`,
`migrated`, `removed`, or `retained_v1_reader`. A retained v1 reader is allowed
only inside the named v1-to-v2 migration boundary and may not produce active v2
state.

An advisory planning scan on 2026-08-06 found 104 `asset_fingerprint`
occurrences across seven files and 13 `advance_workflow_state` occurrences across
three files, with 117 combined occurrences across eight unique files. P1.0 must
regenerate and baseline-pin this inventory because working-tree changes may alter
those counts before implementation.

Exit gate:

- schemas are closed and ASCII-clean;
- request-hash inputs, exclusions, normalization, and version are fixture-pinned;
- the transition signature and every invalidation action are unambiguous enough
  for table-driven tests;
- every baseline occurrence appears exactly once in the migration ledger and has
  a target contract and verification fixture;
- no ledger entry remains uncategorized or relies only on a line number for
  identity;
- baseline suites reproduce;
- the reference workstation is recorded before Section 28 becomes a release gate;
- the deployment record either confirms SQLite eligibility or rebaselines P1.1
  to PostgreSQL before implementation;
- no implementation begins while principal identity, deployment topology, or
  server storage path is unresolved.

### P1.1 - Repository and SQLite foundation

Work:

- implement repository interface;
- implement migrations and SQLite adapter;
- enable WAL, foreign keys, and busy timeout;
- implement canonical JSON and hashes;
- implement canonical request-hash v1 exactly as specified in Section 18.2;
- implement server-generated IDs;
- implement conversation, agent session, pending turn, terminal turn, summary,
  and manifest CRUD;
- enforce tenant filters and uniqueness constraints;
- implement retention query and deletion primitives;
- add repository health diagnostics.

Exit gate:

- restart preserves committed data;
- duplicate client turn IDs are deterministic;
- concurrent writes do not allocate duplicate sequence numbers;
- tenant-isolation tests pass;
- migration rollback leaves the prior schema usable;
- repository unit tests use temporary databases and leave no workspace data.

### P1.2 - Durable workflow state

Work:

- introduce the pure `advance_workflow_state_v2` signature from Section 17.7;
- migrate every inventoried caller, sanitizer, store field, fixture, and API
  projection from the combined `asset_fingerprint` contract;
- update each closed-ledger entry atomically with its migration and verification
  fixture; do not declare migration complete from a repository-wide search alone;
- implement deterministic v1-to-v2 migration from current trusted scope and
  revision providers;
- implement a repository-backed store with the current interface where practical;
- separate scope fingerprint from revision vector;
- persist workflow revisions, expiry, referents, milestones, and compact receipts;
- validate every registered stage's dependency declarations and require safe
  predecessors for preview/approval/apply/execution stages;
- implement deterministic stage revalidation and regression from Section 17.6;
- support explicit abandon and completion;
- migrate or restore validated v1 browser mirrors only in shadow/transition mode;
- ignore browser mirrors as authority in enforce mode; Phase 1 introduces no
  browser-signing keys, rotation, or verification subsystem;
- keep live viewport state outside workflow memory.

Exit gate:

- server restart resumes a valid workflow without browser state;
- expired state is not restored;
- a tab change does not invalidate state;
- a stable-scope revision change follows the exact action matrix in Section 17.8;
- every authorization-bearing stage has a valid safe predecessor and regresses to
  it when a declared dependency changes;
- a scope change drops referents and pending effects;
- v1 migration never guesses scope or revisions from the old combined hash;
- every ledger entry is `migrated`, `removed`, or an explicitly permitted
  `retained_v1_reader` with a passing boundary test;
- no production v2 state or function call contains `asset_fingerprint`;
- a source/schema scan finds no legacy identifier outside the named migration
  reader and frozen v1 fixtures;
- no remembered side effect is replayed.

### P1.3 - Conversation and turn lifecycle

Work:

- add server conversation endpoints;
- extend chat request and response schemas;
- freeze semantic targets and expected asset revisions when creating a client
  turn;
- calculate request hash v1 before pending-turn persistence;
- persist pending turns before provider calls;
- classify turns as read-only, preview, or action/write;
- re-resolve trusted revisions immediately before preview issuance or any effect;
- pass the authorized base revision through existing Builder/repository CAS;
- persist before/result revision vectors and barrier outcomes in receipts and
  context manifests;
- commit deterministic fast paths as normal turns;
- bind streaming terminal events to database commit;
- store normalized provider/model/route metadata;
- reconcile tool receipts on retries;
- implement cancellation and stale-pending recovery;
- ensure one committed user request has one canonical assistant result.

Exit gate:

- browser retry returns the committed result;
- timestamp, camera, hover, and retry-count changes do not alter a request hash;
- message, semantic target, expected revision, action parameter, image hash, or
  cross-agent projection changes do alter it;
- a revision change while an action is pending produces no preview or effect and
  returns `revision_advanced_during_turn`;
- a revision race after the pre-effect check is rejected by authoritative CAS;
- a successful effect is never reported as failed merely because unrelated state
  changed before its receipt was committed;
- an interrupted stream cannot duplicate a tool action;
- a different request reusing a client turn ID receives 409;
- response is not displayed as committed before server commit;
- direct deterministic responses appear in restored history.

### P1.4 - Bounded history and structured summary

Work:

- implement continuity-summary schema and validator;
- implement incremental summary scheduling;
- preserve source turn IDs and correction links;
- implement recent complete-turn selection;
- add provider-neutral summary adapter configuration;
- add timeout and invalid-output fallback;
- track unsummarized turn/token ranges and soft/hard summary staleness;
- perform one bounded synchronous refresh before an action at soft staleness;
- block action turns after failed soft-stale refresh and at hard staleness;
- stop forwarding full history in shadow comparison first;
- preserve current images only, never historical image payloads;
- replace one-time cross-agent prose summary with a bounded projection.

Exit gate:

- a 100-turn chat sends no more than the configured continuity budget;
- corrections supersede earlier claims in the summary;
- every summary item has source turn IDs;
- summary failure does not lose current authoritative state;
- twenty unsummarized failed-summary turns cannot be hidden behind a six-turn
  recent window;
- sustained summary failure visibly degrades read-only turns and deterministically
  blocks action turns before routing or tool execution;
- recovery clears staleness only after a valid summary covers the missing range;
- no assistant-only engineering value becomes an authoritative fact;
- Anthropic and OpenAI receive semantically equivalent bounded history.

### P1.5 - Memory Envelope and context manifest

Work:

- implement deterministic envelope builder;
- integrate selected skill context and trusted provider origins;
- implement per-section token accounting;
- enforce required-context budget failure;
- persist context manifests and hashes;
- include workflow, receipts, capabilities, and restrictions;
- render explicit trusted/untrusted prompt boundaries;
- attach memory metadata to API responses;
- add admin manifest inspection endpoint.

Exit gate:

- identical inputs produce byte-identical canonical envelopes;
- every included provider has origin, reason, revision, hash, and token count;
- every omission has a reason;
- no required provider is silently removed;
- prompt text cannot blur transcript data into trusted application context;
- manifest contains no raw image or secret.

### P1.6 - Revision-aware invalidation

Work:

- implement normalized scope builders;
- implement revision-vector builders for CAD/FAI, Process Map, and Facility Layout;
- implement the closed dispatcher and matrix in Sections 17.6 and 17.8;
- revalidate entity IDs and referents against current target indexes;
- invalidate stale previews and approval tokens;
- preserve objective and applicable stage on same-scope edits;
- mark stale summary evidence references;
- expose reconciliation event in the response and manifest.

Exit gate:

- saving a Process Map does not erase the user's objective;
- a removed node cannot remain an actionable referent;
- a stale semantic preview cannot commit;
- a Facility Layout policy revision invalidates dependent decisions;
- changing from Tricycle to another assembly does not carry Tricycle entities;
- past receipts remain audit history but never authorize execution.

### P1.7 - Frontend cutover

Work:

- create server-backed conversations;
- store server conversation/session IDs;
- generate unique client turn IDs;
- render server history after reload;
- keep localStorage only as cache and legacy archive;
- add deletion behavior;
- show memory-unavailable and stale-context states;
- preserve unsent drafts locally;
- do not upload old history automatically;
- verify switching agents and conversations during non-pending states.

Exit gate:

- reload restores committed history from the server;
- clearing browser storage does not delete server history;
- deleting a server conversation removes it after reload;
- old local conversations remain readable but are not injected automatically;
- no duplicate turn appears after stream retry;
- pending work cannot be confused with a committed answer.

### P1.8 - Shadow evaluation and pilot hardening

Work:

- run off/shadow/compare/enforce modes;
- compare legacy and bounded token use;
- replay long and conflicting conversations;
- restart the server during pending and committed states;
- exercise multiple browser sessions;
- test tenant isolation and deletion;
- measure DB and envelope latency;
- document backup, retention, and recovery;
- enable one internal pilot tenant before external rollout.

Exit gate:

- all Definition of Done criteria pass;
- no unexplained legacy regression;
- no tenant leakage;
- no stale revision is used for an action;
- no action repeats after retry;
- bounded context remains within configured limits;
- rollback to `off` does not corrupt conversations or engineering assets.

## 27. Test Strategy

### 27.1 Unit tests

- closed schema validation;
- canonical serialization and hash stability;
- request-hash v1 field inclusion, exclusion, normalization, and versioning;
- equal hashes when only timestamps, camera, hover, stream ID, or retry count
  differ;
- unequal hashes when message, expected revision, semantic target, action
  parameter, image hash, or cross-agent projection differs;
- scope-fingerprint stability;
- revision-vector sensitivity;
- summary source-turn enforcement;
- correction and supersession behavior;
- token allocation and omission ordering;
- workflow-state v1-to-v2 migration without combined-hash inference;
- migration-ledger generation accounts for every baseline occurrence exactly once;
- permitted v1 readers cannot produce or authorize active v2 state;
- every cell of the workflow-state reconciliation matrix through the closed
  Section 17.6 dispatcher;
- retention eligibility;
- redaction behavior;
- ID and request-hash validation.

### 27.2 Repository tests

- migration from empty database;
- migration idempotency;
- transaction rollback;
- concurrent sequence allocation;
- duplicate client turn handling;
- pending-to-committed transition;
- restart recovery;
- expired pending turn recovery;
- tenant isolation;
- soft deletion and retention cleanup;
- malformed JSON rejection;
- WAL and foreign-key configuration.

### 27.3 API and streaming tests

- create/list/get/delete conversation;
- unauthorized and cross-tenant access;
- legacy request compatibility;
- server-backed request identity;
- committed idempotent replay;
- replay after a later asset revision returns the original committed result and
  original revision vector;
- mismatched request hash conflict;
- stream disconnect before first token;
- stream disconnect after partial text;
- read-only turn started at revision A and completed after revision B returns both
  vectors and `revisionAdvancedDuringTurn=true`;
- action turn started at revision A and advanced to B while the provider is
  blocked executes no preview or tool and fails `revision_advanced_during_turn`;
- a retry attached to that pending/failed turn cannot bypass the revision barrier;
- a CAS race after a successful pre-effect comparison applies no effect;
- post-effect unrelated drift preserves the successful receipt, exposes the
  drift flag, and permits no second effect;
- server restart after commit;
- deterministic fast-path persistence;
- tool receipt persistence;
- stateless read fallback policy;
- write fail-closed policy.

### 27.4 Context tests

- short conversation with no summary;
- 100-turn conversation with bounded input;
- correction in turn 40 used correctly in turn 100 on the healthy-summary path;
- with summarization failing from turn 41 through turn 100, the correction is
  never silently omitted: read-only output is visibly degraded and an action
  turn fails before routing or tool execution;
- soft-stale synchronous refresh success and failure;
- hard-stale recovery only after the missing range is covered;
- old assistant claim excluded as authority;
- required context preserved;
- optional context pruned by declared priority;
- required provider over budget fails closed;
- current live state overrides summary;
- cross-agent continuity cannot authorize a tool;
- OpenAI and Anthropic adapters receive equivalent content classes;
- context manifest hashes reproduce.

### 27.5 Revision tests

- same Process Map revision resumes;
- Process Map edit preserves objective and invalidates preview;
- revision of a dependency used by an approval/apply stage regresses the workflow
  to its declared safe checkpoint;
- a non-authorizing planning stage remains only when its declared dependencies
  are unchanged and its workflow-version transition is valid;
- missing safe-predecessor metadata resets to the first stage and emits
  `workflow_stage_revalidation_unavailable`;
- product-structure revision removes stale part referent;
- Facility Layout revision preserves objective and revalidates placement IDs;
- policy revision invalidates dependent approval;
- FAI table revision invalidates prior measurement conclusion;
- drawing revision invalidates old callout evidence;
- pending preview and approval-token issuance recheck current revisions;
- the revision barrier compares every populated field unless a closed
  skill/tool dependency set is fixture-approved;
- effect receipts reproduce the expected post-effect revision vector;
- changing assembly configuration creates a new scope when required;
- changing tabs does not change scope;
- pan, zoom, selection, and temporary highlight do not become durable memory.

### 27.6 Frontend tests

- new server conversation;
- reload and restore;
- local cache disagreement resolved by server sequence;
- browser storage cleared;
- delete conversation;
- archived legacy local chat;
- no silent legacy upload;
- agent switch;
- conversation switch;
- duplicate send prevention;
- pending/committed visual states;
- memory service unavailable;
- accessibility of warnings and status labels.

### 27.7 Pilot replay fixtures

At minimum:

1. FAI impact question followed by disposition and viewport command.
2. Process Map generation, preview, map revision, and continued review.
3. Facility Layout generation, manual move, policy revision, and validation.
4. Tricycle conversation switched to a different assembly.
5. User corrects an earlier claimed value.
6. Two source documents conflict.
7. Two tenants use identical part and map names.
8. Provider timeout during summary generation.
9. Summarizer unavailable for at least 20 committed turns, followed by a
   continuity-dependent action.
10. Provider switch between turns.
11. Server restart between user request and retry.
12. Process Map or Facility Layout revision advances while an action turn is
    waiting on the model, followed by a retry of the same client turn.

## 28. Performance Targets

P1.0 must pin a reference workstation before these numbers become binding. Store
the benchmark definition in
`tests/fixtures/memory/reference-workstation.json` with:

- CPU model, physical/logical core count, and architecture;
- installed RAM;
- storage type and filesystem;
- OS version;
- Python and SQLite versions;
- power profile;
- repository commit and benchmark fixture revision.

Until that fixture exists, timings are informative and cannot satisfy or fail an
exit gate. Once pinned, the initial local-pilot targets on that workstation are:

- repository read/write p95 below 25 ms excluding retention cleanup;
- Memory Envelope assembly p95 below 75 ms excluding trusted-provider loading;
- context manifest persistence p95 below 20 ms;
- conversation restore of 200 committed turns below 250 ms server-side;
- frontend initial render may paginate and must not render all 200 turns at once;
- on the nominal path, summary generation is asynchronous and adds no latency to
  terminal turn commit;
- on the soft-stale action path only, one synchronous refresh may add at most the
  configured 5,000 ms deadline before the turn is allowed to route; timeout blocks
  the action instead of exceeding the deadline or using incomplete continuity;
- no whole-database scan on a normal chat turn;
- no transcript-length-dependent prompt growth after the summary threshold.

Performance fixtures must contain realistic JSON sizes and at least 10,000 turns
across multiple conversations to expose missing indexes. CI timing is reported
separately and does not silently replace the reference-workstation result.

## 29. Pilot Metrics and Release Gates

### 29.1 Reliability

- server-restart conversation recovery: 100 percent in fixtures;
- committed-turn duplicate rate: 0;
- repeated tool-effect rate after retry: 0;
- stale-preview application rate: 0;
- cross-tenant retrieval rate: 0;
- required-context silent-drop rate: 0;
- action execution while continuity is soft/hard stale: 0;
- preview or effect authorized against a superseded source revision: 0;
- persistent action paths without authoritative CAS/equivalent protection: 0;
- silently omitted unsummarized ranges: 0.

### 29.2 Context quality

- current-state precedence violations: 0;
- summaries with missing source turn IDs: 0;
- assistant-only claims promoted to authority: 0;
- context-budget violations in enforce mode: 0;
- unresolved omission without manifest reason: 0;
- wrong-scope referent carryover: 0;
- continuity-dependent answers that omit a known unsummarized correction: 0.

### 29.3 Operational

- memory repository availability is visible in health diagnostics;
- every committed turn has an envelope hash and context manifest;
- every action turn has complete receipts;
- conversation deletion and retention are testable;
- rollback flag works without engineering-asset migration.

## 30. Risks and Mitigations

### Full transcripts are mistaken for better memory

Mitigation: bounded recent turns plus structured continuity, with current trusted
state loaded independently.

### Summary errors become durable facts

Mitigation: summaries remain untrusted, require source turn IDs, and cannot
upgrade authority.

### A map save destroys useful workflow continuity

Mitigation: separate stable scope from revision vector and invalidate by
dependency.

### Stale evidence survives because its text still appears in chat

Mitigation: current trusted state wins; stale source refs are marked in summaries;
prior assistant text has the lowest engineering authority.

### Retry repeats a physical or viewport action

Mitigation: pending turn persistence, client-turn uniqueness, request hashes, and
receipt reconciliation before execution.

### An asset revision advances while an action turn is pending

Mitigation: re-resolve trusted revisions immediately before preview/effect,
invalidate on mismatch, pass the authorized base revision into CAS, and record
before/result vectors in the terminal receipt.

### Browser data is treated as server truth

Mitigation: server-issued IDs, tenant-scoped repository reads, and browser cache
reconciliation.

### SQLite becomes a deployment constraint

Mitigation: repository interface, no SQLite types in service/API contracts, and
no assumption that one process owns all state.

### Summary calls add cost

Mitigation: incremental summaries, fixed thresholds, bounded output, asynchronous
execution, one pinned validated summary model, and provider/model telemetry.

### Sustained summarizer failure hides a middle correction

Mitigation: persist the exact unsummarized range, expose soft/hard staleness,
attempt one bounded refresh, and fail action turns before routing or tools rather
than treating the latest six turns as complete continuity.

### Required context exceeds the selected skill budget

Mitigation: deterministic digest first, then explicit fail-closed error rather
than silent truncation.

### Local chat history is uploaded without consent

Mitigation: no automatic import; retain legacy history locally unless the user
explicitly imports it.

### Memory outage silently weakens safety

Mitigation: action turns fail closed; optional read-only stateless behavior is
explicitly configured and returned to the UI.

## 31. Definition of Done

Phase 1 is complete only when all of the following are true:

1. New conversations and agent sessions are server-owned and tenant-scoped.
2. Committed turns survive browser and server restart.
3. Every turn is idempotent and bound to canonical request-hash v1 fixtures;
   volatile UI and transport fields cannot change retry identity.
4. Workflow state is durable without relying on a browser mirror.
5. Stable scope and source revisions are modeled separately.
6. Same-scope revisions preserve objectives while invalidating affected evidence.
7. Scope changes do not carry stale entities or referents.
8. Main answer prompting no longer sends the complete transcript.
9. Recent-turn and summary input obey configured budgets without silently
   omitting a known unsummarized range.
10. Structured summaries cite source turns and remain untrusted continuity.
11. Current trusted engineering state overrides all remembered state.
12. Every committed turn has a deterministic Memory Envelope hash.
13. Every committed turn has a context manifest with providers, revisions,
    accounting, and omissions.
14. Required context is never silently dropped or sent over budget.
15. Action retries cannot repeat successful effects.
16. Browser storage is cache/legacy archive only in enforce mode.
17. Existing Process Map, Facility Layout, FAI, viewport, Builder, and streaming
    behavior passes its frozen regression bars.
18. Cross-tenant and deletion tests pass.
19. Shadow and compare telemetry meet the release gates.
20. The pilot runbook documents storage path, retention, backup, recovery,
    rollback, and memory-unavailable behavior.
21. Soft and hard summary staleness are visible, tested, and block action turns
    according to Section 13.4.
22. Workflow-state v2 stores scope and revision separately; the closed migration
    ledger accounts for every baseline occurrence, and no enforce-mode state or
    caller relies on the old combined `asset_fingerprint` contract.
23. Every invalidation-matrix cell dispatches one defined Section 17.6 action.
24. Every mutable revision revalidates workflow stage, and affected
    authorization-bearing stages regress to a declared safe checkpoint.
25. Every preview and persistent action passes the just-in-time revision barrier
    and authoritative CAS/equivalent guard before taking effect.
26. Read-only answers completed after revision drift identify both their source
    snapshot and the newer current revision.
27. Performance gates run against the pinned reference-workstation fixture and
    report CI timing separately.

## 32. Remaining Question for External Review

1. Which existing approved artifacts should Phase 1 expose as
   `approvedSourceDecisions` before the Phase 2 decision ledger exists?

This decision does not block Commitment A. It must be resolved and fixture-pinned
before P1.5 begins constructing `approvedSourceDecisions` in the Memory Envelope.

### 32.1 Phase 1 decisions and defaults

The following are implementation defaults, not unresolved review questions. They
may be tuned from shadow telemetry without changing the architecture:

- conversation retention is 30 days, active workflow TTL is 24 hours after last
  valid activity, and referent TTL is 30 minutes; explicit completion,
  abandonment, or deletion ends them sooner;
- all action/write turns fail closed when memory is unavailable, and stateless
  read fallback defaults to disabled;
- the initial continuity allocation is six complete turns, a 1,200-token
  structured summary, and a 2,400-token recent-history budget;
- the summary provider/model is pinned and independently validated rather than
  following the current answer provider;
- legacy browser conversations remain local read-only archives unless the user
  explicitly imports them;
- context manifests are the Phase 1 audit record; raw prompt snapshots are not
  stored by default;
- browser mirrors are ignored as authority in enforce mode and are not signed;
- SQLite is binding for the current single-host Commitment A pilot; any trigger in
  Section 3.5 requires a PostgreSQL rebaseline before P1.1, not a mid-phase swap;
- workflow stages use `revalidate` for every mutable revision; changed or
  authorization-bearing stages regress to a declared safe checkpoint under
  Section 17.6;
- timing gates are binding only on the pinned reference workstation.

## 33. Recommended Approval Boundary

Approve Phase 1 in two implementation commitments:

### Commitment A

P1.0 through P1.3:

- frozen contracts;
- SQLite repository;
- durable workflow state;
- conversation and idempotent turn lifecycle.

This is foundational and does not change prompt behavior in production.

### Commitment B

P1.4 through P1.8, after Commitment A verification:

- bounded history;
- structured summary;
- Memory Envelope;
- revision-aware invalidation;
- frontend cutover;
- enforce-mode rollout.

This split prevents approval of prompt-changing behavior before persistence,
idempotency, and restart recovery have been proven.
