from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from ai_inspector.memory import (
    MemoryPrincipal,
    canonical_json,
    canonical_sha256,
    default_memory_db_path,
    is_memory_id,
    new_memory_id,
    normalize_request_identity_v1,
    configured_secret_patterns,
    redact_for_persistence,
    redact_text,
    record_memory_event,
    request_identity_sha256_v1,
)
from ai_inspector.telemetry import TelemetryStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "memory"


def _request_fixture() -> dict:
    return json.loads(
        (FIXTURES / "request-hash-v1-cases.json").read_text(encoding="ascii")
    )


def test_canonical_json_is_ascii_sorted_compact_and_finite() -> None:
    value = {"z": "caf\u00e9", "a": {"b": 2, "a": 1}}
    encoded = canonical_json(value)
    assert encoded == '{"a":{"a":1,"b":2},"z":"caf\\u00e9"}'
    assert encoded.isascii()
    assert canonical_sha256(value) == canonical_sha256({"a": {"a": 1, "b": 2}, "z": "caf\u00e9"})
    with pytest.raises(ValueError):
        canonical_json({"invalid": math.nan})


def test_request_hash_v1_reproduces_the_frozen_fixture() -> None:
    fixture = _request_fixture()
    identity, digest = request_identity_sha256_v1(fixture["baseRaw"])
    assert digest == fixture["baseExpectedSha256"]
    assert list(identity) == fixture["includedTopLevelFields"]

    for case in fixture["cases"]:
        raw = copy.deepcopy(fixture["baseRaw"])
        raw.update(copy.deepcopy(case["overrides"]))
        _, candidate_digest = request_identity_sha256_v1(raw)
        if case["expectedRelation"] == "same":
            assert candidate_digest == digest, case["caseId"]
        else:
            assert candidate_digest != digest, case["caseId"]


def test_request_hash_v1_is_closed_at_semantic_boundaries() -> None:
    raw = copy.deepcopy(_request_fixture()["baseRaw"])
    raw["assetScope"]["browserRevision"] = "untrusted"
    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_request_identity_v1(raw)

    raw = copy.deepcopy(_request_fixture()["baseRaw"])
    raw["semanticTargets"]["hoveredNodeIds"] = ["node-1"]
    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_request_identity_v1(raw)

    raw = copy.deepcopy(_request_fixture()["baseRaw"])
    raw["actionParameters"] = {"invalid": math.inf}
    with pytest.raises(ValueError):
        normalize_request_identity_v1(raw)


def test_server_ids_and_principals_are_validated() -> None:
    expected_kinds = {
        "conversation": "conv-",
        "agent_session": "agent-session-",
        "turn": "turn-",
        "summary": "summary-",
        "summary_job": "summary-job-",
        "context_manifest": "context-",
    }
    for kind, prefix in expected_kinds.items():
        value = new_memory_id(kind)
        assert value.startswith(prefix)
        assert is_memory_id(value, kind)
    assert not is_memory_id("conv-browser-controlled", "conversation")
    with pytest.raises(ValueError):
        MemoryPrincipal(tenant_id="", user_id="user")


def test_default_database_path_stays_outside_the_workspace() -> None:
    default = default_memory_db_path({"LOCALAPPDATA": "C:/LocalData"})
    assert default.as_posix().endswith(
        "InspectorPro/memory/inspectorpro-memory.sqlite3"
    )
    override = default_memory_db_path(
        {
            "LOCALAPPDATA": "C:/LocalData",
            "INSPECTORPRO_MEMORY_DB_PATH": "D:/pilot/memory.sqlite3",
        }
    )
    assert override.as_posix() == "D:/pilot/memory.sqlite3"


def test_redaction_handles_headers_structured_keys_and_configured_patterns() -> None:
    source = (
        "Authorization: Bearer token-value-123456789\n"
        "api_key=sk-ant-abcdefghijklmnopqrstuvwxyz\n"
        "plant credential FACILITY-CODE-4829"
    )
    patterns = configured_secret_patterns({
        "INSPECTORPRO_MEMORY_SECRET_PATTERNS_JSON": (
            '["FACILITY-CODE-[0-9]+"]'
        )
    })
    redacted = redact_text(source, configured_patterns=patterns)
    assert "token-value" not in redacted
    assert "sk-ant-" not in redacted
    assert "FACILITY-CODE-4829" not in redacted
    assert redacted.count("<redacted:sha256:") == 3

    structured = redact_for_persistence({
        "cookie": "session-cookie-value",
        "nested": {"password": "correct horse battery staple"},
        "safe": "engineering context",
    })
    assert structured["safe"] == "engineering context"
    assert "session-cookie-value" not in canonical_json(structured)
    assert "correct horse" not in canonical_json(structured)


def test_memory_telemetry_records_only_bounded_rollout_metadata(
    tmp_path: Path,
) -> None:
    store = TelemetryStore(tmp_path / "memory-telemetry.sqlite3")
    event = record_memory_event(
        "memory.turn.committed",
        mode="compare",
        classification="preview",
        agent_type="sage",
        session_id="agent-session-123",
        turn_id="turn-123",
        applied_to_prompt=False,
        context_tokens=3200,
        legacy_tokens=9800,
        omission_count=2,
        replayed=False,
        revision_outcome="matched",
        summary_revision=4,
        workflow_state_revision=7,
        context_manifest_id="context-123",
        envelope_sha256="a" * 64,
        source_revision_sha256="b" * 64,
        result_revision_sha256="c" * 64,
        store=store,
    )
    assert event is not None
    restored = store.query_recent(1)[0]
    assert restored.workflow == "sage_memory"
    assert restored.stage == "memory.turn.committed"
    assert restored.memoryMode == "compare"
    assert restored.memoryClassification == "preview"
    assert restored.memoryAuthoritative == 0
    assert restored.memoryContextTokens == 3200
    assert restored.memoryLegacyTokens == 9800
    assert restored.memoryOmissionCount == 2
    assert restored.memoryEnvelopeSha256 == "a" * 64
    with pytest.raises(ValueError, match="unsupported Sage-memory telemetry"):
        record_memory_event("memory.raw.prompt", mode="enforce", store=store)
    store.close()
