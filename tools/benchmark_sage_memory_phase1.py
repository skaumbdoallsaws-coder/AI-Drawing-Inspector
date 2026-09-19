"""Run the pinned Sage Memory Phase 1 local-pilot benchmark.

Provider calls are intentionally absent. Fixture seeding is excluded from every
release-gate latency and uses one SQLite transaction so the benchmark measures
the memory implementation rather than fixture construction overhead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.memory import (  # noqa: E402
    ContinuityProjection,
    MemoryPrincipal,
    SqliteMemoryRepository,
    TrustedTurnContext,
    build_memory_envelope,
    build_request_identity_v1,
    canonical_json,
    canonical_sha256,
    new_memory_id,
    revision_vector_sha256,
    sqlite_quick_check,
    utc_timestamp,
)


TARGETS_MS = {
    "repositoryReadP95": 25.0,
    "repositoryWriteP95": 25.0,
    "contextManifestPersistenceP95": 20.0,
    "conversationRestore200P95": 250.0,
    "memoryEnvelopeAssemblyP95": 75.0,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=10_000)
    parser.add_argument("--conversations", type=int, default=50)
    parser.add_argument("--samples", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "runtime_logs" / "sage_memory_p18_benchmark.json",
    )
    parser.add_argument("--database", type=Path)
    return parser


def _timed_ms(operation: Callable[[], Any]) -> float:
    started = time.perf_counter()
    operation()
    return (time.perf_counter() - started) * 1000.0


def _p95(values: Iterable[float]) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _trusted_context() -> TrustedTurnContext:
    revision = {
        "processMapRevision": "a" * 64,
        "productStructureRevision": "b" * 64,
    }
    return TrustedTurnContext(
        asset_scope={
            "kind": "process_map",
            "ids": {"productId": "benchmark", "mapId": "default"},
            "expectedRevisionVector": revision,
        },
        scope_fingerprint="scope-v1:" + "1" * 64,
        revision_vector=revision,
        workflow_mode="process_map",
    )


def _request_identity(message: str) -> tuple[Dict[str, Any], str]:
    trusted = _trusted_context()
    return build_request_identity_v1(
        message=message,
        agent_type="deviation-analyst",
        trusted_context=trusted,
        request_context={
            "asset_scope": trusted.asset_scope,
            "semantic_targets": {
                "partOccurrenceIds": ["occ-benchmark-001"],
                "processMapNodeIds": ["node-benchmark-001"],
                "processMapEdgeIds": [],
                "facilityPlacementIds": [],
                "faiCharacteristicIds": [],
            },
        },
        action_parameters={},
        image_sha256=[],
        cross_agent_context=None,
    )


def _seed_fixture(
    repository: SqliteMemoryRepository,
    principal: MemoryPrincipal,
    *,
    turn_count: int,
    conversation_count: int,
) -> List[tuple[str, str]]:
    if turn_count < 10_000:
        raise ValueError("Phase 1 benchmark requires at least 10,000 turns")
    if conversation_count < 2 or conversation_count > turn_count:
        raise ValueError("conversation count must be between 2 and turn count")

    scopes: List[tuple[str, str]] = []
    for index in range(conversation_count):
        conversation = repository.create_conversation(
            principal,
            title=f"Benchmark conversation {index + 1}",
            metadata={"fixture": "sage-memory-p18", "index": index + 1},
        )
        session = repository.create_agent_session(
            principal,
            conversation.conversation_id,
            agent_type="deviation-analyst",
            scope_fingerprint=_trusted_context().scope_fingerprint,
            revision_vector=_trusted_context().revision_vector,
        )
        scopes.append((conversation.conversation_id, session.agent_session_id))

    distributions = [turn_count // conversation_count] * conversation_count
    for index in range(turn_count % conversation_count):
        distributions[index] += 1

    timestamp = utc_timestamp()
    scope = _trusted_context()
    source_revision_json = canonical_json(scope.revision_vector)
    barrier_json = canonical_json({
        "classification": "read_only",
        "outcome": "matched",
        "resultingRevisionVector": scope.revision_vector,
    })
    route_json = canonical_json({
        "agentType": "deviation-analyst",
        "workflowMode": "process_map",
        "turnClassification": "read_only",
    })
    model_json = canonical_json({"provider": "fixture", "model": "none"})

    connection = sqlite3.connect(repository.database_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        for scope_index, ((conversation_id, session_id), count) in enumerate(
            zip(scopes, distributions)
        ):
            for sequence in range(1, count + 1):
                global_index = scope_index * max(distributions) + sequence
                message = (
                    f"Review process-map node {global_index} against the current "
                    "approved structure and retain the operator correction."
                )
                identity, request_sha256 = _request_identity(message)
                turn_id = new_memory_id("turn")
                manifest_id = new_memory_id("context_manifest")
                envelope_hash = hashlib.sha256(
                    f"envelope:{conversation_id}:{sequence}".encode("ascii")
                ).hexdigest()
                assistant_result = {
                    "response": (
                        "The current server-owned map revision was reviewed; "
                        f"node {global_index} remains in scope."
                    ),
                    "warnings": [],
                }
                manifest = {
                    "schemaVersion": "sage-context-manifest-1.0",
                    "identity": {"turnId": turn_id},
                    "providers": [{
                        "contextKey": "process_map.state",
                        "origin": "server",
                        "included": True,
                        "payloadSha256": "c" * 64,
                        "estimatedTokens": 220,
                    }],
                    "budget": {
                        "estimated": 900,
                        "maximum": 12_000,
                        "omissions": [],
                    },
                }
                connection.execute(
                    """
                    INSERT INTO memory_turns (
                        turn_id, tenant_id, conversation_id, agent_session_id,
                        sequence, client_turn_id, request_hash_version,
                        request_identity_json, request_sha256, status,
                        user_message_json, assistant_result_json,
                        tool_receipts_json, route_metadata_json,
                        model_metadata_json, scope_fingerprint,
                        source_revision_vector_json,
                        resulting_revision_vector_json,
                        revision_barrier_json, memory_envelope_sha256,
                        context_manifest_id, error_code, created_at_utc,
                        committed_at_utc
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, 1, ?, ?, 'committed', ?, ?, '[]',
                        ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?
                    )
                    """,
                    (
                        turn_id,
                        principal.tenant_id,
                        conversation_id,
                        session_id,
                        sequence,
                        f"fixture-{scope_index + 1}-{sequence}",
                        canonical_json(identity),
                        request_sha256,
                        canonical_json({"role": "user", "content": message}),
                        canonical_json(assistant_result),
                        route_json,
                        model_json,
                        scope.scope_fingerprint,
                        source_revision_json,
                        source_revision_json,
                        barrier_json,
                        envelope_hash,
                        manifest_id,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO memory_context_manifests (
                        context_manifest_id, tenant_id, conversation_id,
                        agent_session_id, turn_id, schema_version,
                        scope_fingerprint, revision_vector_sha256,
                        memory_envelope_sha256, manifest_json, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        manifest_id,
                        principal.tenant_id,
                        conversation_id,
                        session_id,
                        turn_id,
                        scope.scope_fingerprint,
                        revision_vector_sha256(scope.revision_vector),
                        envelope_hash,
                        canonical_json(manifest),
                        timestamp,
                    ),
                )
            connection.execute(
                """
                UPDATE memory_conversations
                SET last_turn_sequence = ?, updated_at_utc = ?
                WHERE conversation_id = ? AND tenant_id = ?
                """,
                (count, timestamp, conversation_id, principal.tenant_id),
            )
            connection.execute(
                """
                UPDATE memory_agent_sessions SET updated_at_utc = ?
                WHERE agent_session_id = ? AND tenant_id = ?
                """,
                (timestamp, session_id, principal.tenant_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return scopes


def _continuity() -> ContinuityProjection:
    summary = {
        "schemaVersion": "sage-continuity-summary-1.0",
        "summaryRevision": 4,
        "throughTurnSequence": 194,
        "objective": {
            "text": "Review the current process-map revision.",
            "sourceTurnIds": ["turn-source-194"],
        },
        "userClaims": [],
        "continuityDecisions": [],
        "assumptions": [],
        "corrections": [{
            "text": "Use the current authored route requirement.",
            "sourceTurnIds": ["turn-source-188"],
        }],
        "openQuestions": [],
        "referencedEntities": [],
        "sourceEvidenceRefs": [],
        "warnings": [],
    }
    recent = tuple(
        item
        for index in range(195, 201)
        for item in (
            {"role": "user", "content": f"Review node {index}."},
            {"role": "assistant", "content": f"Node {index} was reviewed."},
        )
    )
    return ContinuityProjection(
        status="healthy",
        staleness="fresh",
        summary=summary,
        summary_revision=4,
        through_turn_sequence=194,
        recent_history=recent,
        recent_turn_ids=tuple(f"turn-source-{i}" for i in range(195, 201)),
        omitted_turn_count=188,
        unsummarized_turn_count=6,
        unsummarized_token_estimate=420,
        oldest_unsummarized_turn_sequence=195,
        all_unsummarized_turns_included=True,
        warnings=(),
        applied_to_prompt=True,
    )


def _build_envelope(sample: int):
    trusted = _trusted_context()
    return build_memory_envelope(
        context_manifest_id=f"benchmark-manifest-{sample}",
        identity={
            "conversationId": "benchmark-conversation",
            "agentSessionId": "benchmark-session",
            "turnId": f"benchmark-turn-{sample}",
            "agentType": "deviation-analyst",
        },
        scope={
            "kind": trusted.asset_scope["kind"],
            "ids": trusted.asset_scope["ids"],
            "scopeFingerprint": trusted.scope_fingerprint,
            "revisionVector": trusted.revision_vector,
        },
        workflow_state={
            "workflow_id": "process-map-generation",
            "version": "1.0.0",
            "status": "active",
            "stage": "review_preview",
            "objective": "Review the generated process map.",
            "entities": {},
            "referents": {},
        },
        providers=[{
            "contextKey": "process_map.state",
            "origin": "server",
            "requestedBy": ["generate-process-map"],
            "required": True,
            "sourceIds": ["benchmark/default"],
            "sourceRevisions": ["a" * 64],
            "included": True,
            "payload": {
                "nodes": [
                    {"id": f"node-{index}", "label": f"Operation {index}"}
                    for index in range(24)
                ],
                "edges": [
                    {"source": f"node-{index}", "target": f"node-{index + 1}"}
                    for index in range(23)
                ],
                "selection": [],
                "dirty": False,
            },
        }],
        approved_source_decisions=[],
        continuity=_continuity(),
        receipts=[],
        selected_skills=["generate-process-map"],
        allowed_tools=["build_process_map_preview"],
        restrictions=["no_commit_without_approval"],
        classification="preview",
        current_user_request="Review the current complete map preview.",
    )


def _query_plans(database_path: Path, principal: MemoryPrincipal, scopes):
    conversation_id, session_id = scopes[-1]
    queries = {
        "conversationRestore": (
            """
            SELECT t.* FROM memory_turns t
            JOIN memory_conversations c
              ON c.conversation_id=t.conversation_id AND c.tenant_id=t.tenant_id
            WHERE t.tenant_id=? AND t.conversation_id=?
              AND c.user_id=? AND t.sequence>?
            ORDER BY t.sequence ASC LIMIT ?
            """,
            (principal.tenant_id, conversation_id, principal.user_id, 0, 200),
        ),
        "sessionTurns": (
            """
            SELECT t.* FROM memory_turns t
            JOIN memory_conversations c
              ON c.conversation_id=t.conversation_id AND c.tenant_id=t.tenant_id
            WHERE t.tenant_id=? AND t.agent_session_id=?
              AND c.user_id=? AND t.sequence>? AND t.status='committed'
            ORDER BY t.sequence ASC LIMIT ?
            """,
            (principal.tenant_id, session_id, principal.user_id, 0, 100),
        ),
    }
    result = {}
    with closing(sqlite3.connect(database_path)) as connection:
        for name, (query, parameters) in queries.items():
            rows = connection.execute(
                "EXPLAIN QUERY PLAN " + query, parameters
            ).fetchall()
            details = [str(row[3]) for row in rows]
            result[name] = {
                "details": details,
                "usesIndex": any("INDEX" in detail.upper() for detail in details),
                "turnTableFullScan": any(
                    "SCAN T" in detail.upper()
                    and "USING" not in detail.upper()
                    for detail in details
                ),
            }
    return result


def run(args: argparse.Namespace) -> Dict[str, Any]:
    temporary = None
    if args.database:
        database_path = args.database.resolve()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path.exists():
            database_path.unlink()
    else:
        temporary = tempfile.TemporaryDirectory(
            prefix="InspectorPro-SageMemory-P18-"
        )
        database_path = Path(temporary.name) / "benchmark.sqlite3"

    repository = SqliteMemoryRepository(database_path)
    principal = MemoryPrincipal("benchmark-tenant", "benchmark-user")
    seeded_started = time.perf_counter()
    scopes = _seed_fixture(
        repository,
        principal,
        turn_count=args.turns,
        conversation_count=args.conversations,
    )
    seed_seconds = time.perf_counter() - seeded_started

    sample_count = max(20, int(args.samples))
    read_samples: List[float] = []
    restore_samples: List[float] = []
    for index in range(sample_count):
        conversation_id, _session_id = scopes[index % len(scopes)]
        read_samples.append(_timed_ms(
            lambda cid=conversation_id: repository.get_conversation(
                principal, cid
            )
        ))
        restore_samples.append(_timed_ms(
            lambda cid=conversation_id: repository.list_turns(
                principal, cid, limit=200
            )
        ))

    write_conversation = repository.create_conversation(
        principal,
        title="Timed repository writes",
        metadata={"fixture": "timed"},
    )
    write_session = repository.create_agent_session(
        principal,
        write_conversation.conversation_id,
        agent_type="deviation-analyst",
        scope_fingerprint=_trusted_context().scope_fingerprint,
        revision_vector=_trusted_context().revision_vector,
    )
    start_samples: List[float] = []
    manifest_samples: List[float] = []
    commit_samples: List[float] = []
    trusted = _trusted_context()
    for index in range(sample_count):
        identity, _digest = _request_identity(f"Timed write {index}.")
        holder: Dict[str, Any] = {}
        start_samples.append(_timed_ms(lambda: holder.update({
            "turn": repository.start_turn(
                principal,
                write_conversation.conversation_id,
                write_session.agent_session_id,
                client_turn_id=f"timed-{index}",
                request_identity=identity,
                user_message={
                    "role": "user",
                    "content": f"Timed write {index}.",
                },
                scope_fingerprint=trusted.scope_fingerprint,
                source_revision_vector=trusted.revision_vector,
            ).turn,
        })))
        turn = holder["turn"]
        built = _build_envelope(index)
        manifest_id = new_memory_id("context_manifest")
        manifest_samples.append(_timed_ms(
            lambda mid=manifest_id, item=turn, value=built: (
                repository.create_context_manifest(
                    principal,
                    write_conversation.conversation_id,
                    write_session.agent_session_id,
                    item.turn_id,
                    schema_version=1,
                    scope_fingerprint=trusted.scope_fingerprint,
                    revision_vector_sha256=revision_vector_sha256(
                        trusted.revision_vector
                    ),
                    memory_envelope_sha256=value.memory_envelope_sha256,
                    manifest=value.manifest,
                    context_manifest_id=mid,
                )
            )
        ))
        commit_samples.append(_timed_ms(
            lambda item=turn, mid=manifest_id, value=built: (
                repository.commit_turn(
                    principal,
                    item.turn_id,
                    assistant_result={"response": "Timed committed response."},
                    tool_receipts=[],
                    resulting_revision_vector=trusted.revision_vector,
                    revision_barrier={
                        "classification": "read_only",
                        "outcome": "matched",
                    },
                    memory_envelope_sha256=value.memory_envelope_sha256,
                    context_manifest_id=mid,
                )
            )
        ))

    envelope_samples = [
        _timed_ms(lambda sample=index: _build_envelope(sample))
        for index in range(sample_count)
    ]
    first_hash = _build_envelope(1).memory_envelope_sha256
    second_hash = _build_envelope(1).memory_envelope_sha256
    plans = _query_plans(database_path, principal, scopes)

    measurements = {
        "repositoryReadP95": _p95(read_samples),
        "repositoryStartTurnP95": _p95(start_samples),
        "repositoryCommitTurnP95": _p95(commit_samples),
        "repositoryWriteP95": max(_p95(start_samples), _p95(commit_samples)),
        "contextManifestPersistenceP95": _p95(manifest_samples),
        "conversationRestore200P95": _p95(restore_samples),
        "memoryEnvelopeAssemblyP95": _p95(envelope_samples),
    }
    gates = {
        name: {
            "actualMs": round(measurements[name], 4),
            "targetMs": target,
            "passed": measurements[name] < target,
        }
        for name, target in TARGETS_MS.items()
    }
    gates["normalTurnQueriesIndexed"] = {
        "passed": all(
            value["usesIndex"] and not value["turnTableFullScan"]
            for value in plans.values()
        ),
        "plans": plans,
    }
    gates["envelopeDeterministic"] = {
        "passed": first_hash == second_hash,
        "sha256": first_hash,
    }
    gates["fixtureMinimum"] = {
        "passed": args.turns >= 10_000 and args.conversations >= 2,
        "turnCount": args.turns,
        "conversationCount": args.conversations,
    }
    database_bytes = database_path.stat().st_size
    result = {
        "schemaVersion": "sage-memory-p18-benchmark-1.0",
        "status": (
            "passed" if all(item["passed"] for item in gates.values())
            else "failed"
        ),
        "referenceWorkstationFixture": str(
            REPO_ROOT / "tests" / "fixtures" / "memory"
            / "reference-workstation.json"
        ),
        "runtime": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "gitCommit": _git_commit(),
            "providerCalls": 0,
        },
        "fixture": {
            "turnCount": args.turns,
            "conversationCount": args.conversations,
            "timedSampleCount": sample_count,
            "seedSecondsExcludedFromGates": round(seed_seconds, 4),
            "databaseBytes": database_bytes,
            "quickCheck": sqlite_quick_check(database_path),
        },
        "measurementsMs": {
            name: round(value, 4) for name, value in measurements.items()
        },
        "gates": gates,
    }
    repository.close()
    if temporary is not None:
        temporary.cleanup()
    return result


def main() -> int:
    args = _parser().parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2) + "\n",
        encoding="ascii",
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
