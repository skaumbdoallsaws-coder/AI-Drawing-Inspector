# Sage Memory Phase 1 P1.0 Baseline

Generated: `2026-08-07T02:22:24Z`

Plan: `docs/sage-memory-phase-1-plan.md`, revision 4

Checkpoint: **P1.0 contract freeze complete**

This checkpoint adds fixtures, validation tests, a migration-inventory generator,
and this report. It does not change memory runtime, prompts, provider calls,
workflow-state behavior, server APIs, or frontend behavior.

## Baseline Identity

| Item | Value |
| --- | --- |
| Git branch | `ui-bridge-telemetry-unified-2026-05-18` |
| Git HEAD | `e40b30deb824e4c287ac9ae448053141adecd097` |
| Migration source-manifest SHA-256 | `480d06133269f3b9044e4ba421bf3d385599019a4236ebbdc86714e6f68365b3` |
| Worktree | Dirty before P1.0; unrelated changes were preserved |
| OS | Windows 11 `10.0.26200`, 64-bit |
| Time zone | America/Chicago |

The migration ledger pins raw working-tree hashes for all eight migration-source
files. This is necessary because the current working tree contains relevant
uncommitted work and Git HEAD alone does not identify the tested source bytes.

## Safety Controls

- `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` were empty for Python baseline runs.
- No provider, paid model, or network call was made.
- `PYTHONDONTWRITEBYTECODE=1` prevented Python bytecode output.
- Pytest caching was disabled with `-p no:cacheprovider`.
- Every pytest run used a distinct `--basetemp` under `%TEMP%`.
- Telemetry paths were redirected to distinct `%TEMP%` SQLite files.
- Heavy Process Map and Facility Layout suites ran sequentially after a parallel
  baseline attempt was interrupted by workstation memory pressure.
- No existing source, release artifact, generated asset, or failing test was
  changed to make this checkpoint pass.

## Frozen Decisions

### Principal mapping

Local mode uses the existing server-issued Facility principal mapping:

```text
tenantId = local
userId   = local-user
roles    = admin
```

Hosted Phase 1 uses `FacilityPrincipalResolver`; `tenant_id`, `principal_id`, and
`roles` become memory principal fields. Browser-supplied principal fields have no
authority. Unauthenticated access is 401 and cross-tenant resource lookup is 404.

### Pilot topology and database

The Commitment A pilot is one host with one application process and one durable
local volume. None of the PostgreSQL triggers in Section 3.5 applies, so SQLite is
binding for P1.1.

The default Windows database location is outside the OneDrive workspace:

```text
%LOCALAPPDATA%\InspectorPro\memory\inspectorpro-memory.sqlite3
```

`INSPECTORPRO_MEMORY_DB_PATH` may override it, but a shared/network path or an
ephemeral volume triggers a PostgreSQL rebaseline before P1.1.

### Reference workstation

| Item | Value |
| --- | --- |
| Computer | Dell 15 DC15250 |
| CPU | 13th Gen Intel Core i7-1355U; 10 cores / 12 logical |
| RAM | 16,849,256,448 bytes (15.69 GiB) |
| Storage | KIOXIA 1 TB NVMe SSD; NTFS |
| Power profile | Balanced |
| Python / pytest | 3.14.0 / 9.1.1 |
| SQLite | 3.50.4 |
| Node / npm | v24.11.1 / 11.9.0 |

Section 28 timing gates are binding only under the benchmark policy in
`tests/fixtures/memory/reference-workstation.json` or a separately rebaselined
hardware profile.

## Frozen Contracts

| Artifact | Contract |
| --- | --- |
| `sage-memory-contracts-v1.schema.json` | Closed principal, scope, revision-vector, continuity-summary, Memory Envelope, context-manifest, and workflow-state-v2 shapes |
| `sage-memory-contract-examples-v1.json` | Valid examples for every frozen shape |
| `request-hash-v1-cases.json` | Exact field set, exclusions, canonicalization, positive cases, and negative cases |
| `revision-invalidation-matrix-v1.json` | Ten closed invalidation actions and every matrix cell |
| `workflow-stage-revalidation-v1.json` | Dependencies, authorization kind, and safe predecessor for all five registered workflows |
| `pending-turn-revision-barrier-v1.json` | Read drift, pre-effect rejection, CAS race, and successful-effect/post-drift behavior |
| `transcript-accounting-v1.json` | Short, medium, and long current-history accounting |
| `principal-mapping-v1.json` | Local and hosted server principal mapping |
| `pilot-deployment-topology-v1.json` | SQLite decision, storage path, and PostgreSQL triggers |
| `current-runtime-memory-baseline-v1.json` | Browser registry, provider history, router continuity, and trusted-provider substitution |
| `workflow-state-v1-migration-inventory.json` | Closed ledger of every v1 fingerprint/transition occurrence |

The frozen workflow-state v2 shape removes `asset_fingerprint` and stores
`scope_fingerprint`, a structured `revision_vector`, and
`revision_vector_sha256` separately. Active execution receipts and audit-only
historical receipts are distinct fields.

## Request Hash v1

The canonical base identity hashes to:

```text
381c93f65d18f0568ef44cd16644dc2ccfc83c0e6f78ab20f67d2b5f3b59b03e
```

The fixtures prove equal hashes for:

- NFC-equivalent Unicode and CRLF/LF normalization;
- reordered or duplicated set-like semantic targets; and
- changed tenant, conversation, turn, timestamp, retry, camera, hover, or stream
  fields.

They prove unequal hashes for changes to message, expected revision, semantic
target, action parameters, ordered image hashes, and cross-agent projection.

## Workflow Stage Revalidation

All stages in all registered workflow manifests are covered exactly once:

| Workflow | Version | Stages | Authorization-bearing stages |
| --- | --- | ---: | --- |
| `assembly-knowledge-preparation` | 1.0.0 | 4 | none |
| `facility-layout-generation` | 1.0.0 | 6 | preview, approval |
| `process-map-analysis` | 1.1.0 | 4 | none |
| `process-map-generation` | 1.0.0 | 6 | preview, approval |
| `supplier-fai-disposition` | 1.0.0 | 6 | viewport execution |

Every authorization-bearing stage has an earlier safe predecessor. Fixture cases
pin preservation when dependencies are unchanged, regression when a dependency
changes, and unconditional regression of preview, approval, and execution stages.

## Migration Inventory

The case-sensitive substring search is frozen to eight named files and two
symbols. Every occurrence has a path, symbol, snippet hash, file-local source
ordinal, semantic category, target contract, disposition, and verification
fixture. No occurrence identity relies only on a line number.

| Dimension | Count |
| --- | ---: |
| Total entries | 117 |
| Source files | 8 |
| `asset_fingerprint` | 104 |
| `advance_workflow_state` | 13 |
| Producers | 24 |
| Consumers | 38 |
| Serializers | 4 |
| Schemas | 2 |
| API projections | 6 |
| Tests | 43 |

All 117 entries start as `pending`. P1.2 must move each to `migrated`, `removed`,
or the narrowly permitted `retained_v1_reader`; an active v2 writer may not remain
a v1 reader.

## Current Runtime Baseline

### Browser registry

- key: `inspectorpro.chat_registry.v1`;
- snapshot version: 1;
- maximum age: seven days;
- pending assistant messages are excluded;
- image data URLs are stripped;
- workflow state and workflow-state event are stored;
- registry covers Inspector, Sage, and Scout sessions; and
- localStorage is current authority only because server memory is not yet active.

### Provider history

- Anthropic receives all prior user/assistant messages with native roles.
- OpenAI converts all prior turns into one delimited
  `<conversation_history>` text block and preserves the final multimodal turn.
- The main answer path currently forwards the complete browser history.
- The semantic router sees only the last four turns, each truncated to 400
  characters.

### Trusted provider substitution

`_resolve_trusted_process_map_context` removes browser-supplied graph, state, and
evidence before loading server authority. `_resolve_trusted_facility_layout_context`
does the same for digest, state, and evidence. The fixture pins the source hashes
and the P1.0 test checks all six removal paths.

## Transcript Accounting

The current-history estimates use the existing `ceil(characters / 4)` convention.
They measure deterministic ASCII transcript fixtures and do not claim provider
billed-token precision.

| Conversation | Prior turns | Anthropic chars | Est. tokens | OpenAI history chars | Est. tokens | Router turns / chars |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Short | 4 | 531 | 133 | 411 | 103 | 4 / 320 |
| Medium | 20 | 2,315 | 579 | 1,875 | 469 | 4 / 320 |
| Long | 100 | 11,235 | 2,809 | 9,195 | 2,299 | 4 / 320 |

This confirms the Phase 1 problem: main-agent history grows linearly while router
continuity remains bounded and lossy.

## Test Results

| Baseline bar | Result |
| --- | --- |
| P1.0 contract validation | `10 passed` |
| Existing workflow state | `13 passed` |
| Prompt compilation | `9 passed` |
| Context evidence | `6 passed` |
| Chat streaming backend | `17 passed` |
| Frontend workflow state | `8/8 passed` |
| Frontend stream contract | `13/13 passed` |
| Frontend stream runtime | `10/10 passed` |
| Complete Process Map Python suite | `221 passed` |
| Process Map editor Node harness | `83/83 passed` |
| Process Map spatial Node harness | `44/44 passed` |
| Floating-surface Node harness | `14/14 passed` |
| Complete Facility Layout Python suite | `450 passed, 12 failed, 1 skipped` |
| Facility Layout Node harnesses | `167/167 passed` |

### Existing Facility Layout failures

Eleven failures are stale source-bound evidence or release artifacts after the
current dirty-worktree UI/source changes:

- accessibility raw/summary consistency;
- P11 accessibility/visual release gates;
- P11 real-soak build binding;
- P4 renderer evidence;
- P5 authoring evidence;
- P5 product evidence;
- P6 product evidence;
- P8 product evidence;
- P9 product evidence; and
- release-performance smoke evidence.

One failure is behavioral and reproduced independently:

```text
tests/test_facility_layout_proposals.py::
test_apply_rejects_stale_referenced_asset_definition
expected 409, received 200
```

This failure predates and is untouched by P1.0. It is a carry-forward blocker for
Facility Layout action-enforcement integration because a stale referenced asset
definition must not authorize an apply. It does not block P1.1 repository work,
but it must be resolved before a memory-backed Facility action path can enter
enforce mode.

## P1.0 Exit Gate

- Closed contracts: **met**.
- ASCII-clean fixtures: **met**.
- Exact request hash: **met**.
- Closed invalidation vocabulary and matrix: **met**.
- Stage dependency and safe-regression coverage: **met**.
- Migration inventory completeness and uniqueness: **met** (`117/117`).
- Baseline reproduction: **met**, including the documented non-green Facility
  baseline.
- Reference workstation: **met**.
- Principal mapping: **met**.
- Deployment topology and storage path: **met**.
- SQLite/PostgreSQL decision: **SQLite confirmed for P1.1**.

P1.0 is complete. P1.1 may begin with the repository and SQLite foundation. The
Facility stale-asset apply failure remains explicitly outside this checkpoint and
must be closed before action-enforcement integration.
