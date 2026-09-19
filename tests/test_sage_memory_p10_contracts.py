"""Contract-freeze checks for Sage Memory Phase 1 checkpoint P1.0."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "memory"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _schema_type_matches(value: Any, expected: str) -> bool:
    return {
        "null": value is None,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }[expected]


def _resolve_ref(schema_root: dict[str, Any], ref: str) -> dict[str, Any]:
    assert ref.startswith("#/")
    current: Any = schema_root
    for token in ref[2:].split("/"):
        current = current[token.replace("~1", "/").replace("~0", "~")]
    assert isinstance(current, dict)
    return current


def _validate_schema(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> None:
    if "$ref" in schema:
        _validate_schema(value, _resolve_ref(root, schema["$ref"]), root, path)
        return
    if "oneOf" in schema:
        matches = 0
        for candidate in schema["oneOf"]:
            try:
                _validate_schema(value, candidate, root, path)
            except AssertionError:
                continue
            matches += 1
        assert matches == 1, f"{path}: expected exactly one oneOf match, got {matches}"
        return
    if "const" in schema:
        assert value == schema["const"], f"{path}: const mismatch"
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: value not in enum"
    declared_type = schema.get("type")
    if declared_type is not None:
        choices = declared_type if isinstance(declared_type, list) else [declared_type]
        assert any(_schema_type_matches(value, item) for item in choices), (
            f"{path}: expected {choices}, got {type(value).__name__}"
        )

    if isinstance(value, dict):
        required = set(schema.get("required") or [])
        assert required <= set(value), f"{path}: missing {sorted(required - set(value))}"
        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        if additional is False:
            assert set(value) <= set(properties), f"{path}: extra {sorted(set(value) - set(properties))}"
        assert len(value) >= int(schema.get("minProperties", 0))
        if "maxProperties" in schema:
            assert len(value) <= int(schema["maxProperties"])
        for key, item in value.items():
            if key in properties:
                _validate_schema(item, properties[key], root, f"{path}.{key}")
            elif isinstance(additional, dict):
                _validate_schema(item, additional, root, f"{path}.{key}")
    elif isinstance(value, list):
        assert len(value) >= int(schema.get("minItems", 0))
        if "maxItems" in schema:
            assert len(value) <= int(schema["maxItems"])
        if schema.get("uniqueItems"):
            encoded = [_canonical_bytes(item) for item in value]
            assert len(encoded) == len(set(encoded)), f"{path}: duplicate items"
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _validate_schema(item, schema["items"], root, f"{path}[{index}]")
    elif isinstance(value, str):
        assert len(value) >= int(schema.get("minLength", 0))
        if "maxLength" in schema:
            assert len(value) <= int(schema["maxLength"])
        if "pattern" in schema:
            assert re.search(schema["pattern"], value), f"{path}: pattern mismatch"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema:
            assert value >= schema["minimum"], f"{path}: below minimum"


def _request_identity(raw: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    message = str(raw["message"]).replace("\r\n", "\n").replace("\r", "\n")
    targets = raw["semanticTargets"]
    return {
        "requestHashVersion": 1,
        "message": unicodedata.normalize("NFC", message),
        "agentType": str(raw["agentType"]).strip().lower(),
        "workflowMode": str(raw["workflowMode"]).strip().lower(),
        "assetScope": copy.deepcopy(raw["assetScope"]),
        "semanticTargets": {
            key: sorted({str(item) for item in targets.get(key, [])})
            for key in fixture["setLikeSemanticTargetFields"]
        },
        "imageSha256": list(raw["imageSha256"]),
        "actionParameters": copy.deepcopy(raw["actionParameters"]),
        "crossAgentProjectionSha256": raw["crossAgentProjectionSha256"],
        "memorySchemaVersion": raw["memorySchemaVersion"],
    }


def _generated_transcript(spec: dict[str, Any], history_turns: int) -> list[dict[str, str]]:
    rows = []
    for sequence in range(1, history_turns + 1):
        role = "user" if sequence % 2 else "assistant"
        template = spec["userTemplate"] if role == "user" else spec["assistantTemplate"]
        rows.append({"role": role, "content": template.format(sequence=sequence)})
    return rows


def test_contract_examples_validate_against_closed_schema() -> None:
    schema = _load("sage-memory-contracts-v1.schema.json")
    examples = _load("sage-memory-contract-examples-v1.json")
    _validate_schema(examples, schema, schema)

    object_schemas: list[dict[str, Any]] = []
    stack = [schema]
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        if current.get("type") == "object":
            object_schemas.append(current)
        for child in current.values():
            if isinstance(child, dict):
                stack.append(child)
            elif isinstance(child, list):
                stack.extend(item for item in child if isinstance(item, dict))
    assert object_schemas
    assert all("additionalProperties" in item for item in object_schemas)
    assert "asset_fingerprint" not in examples["workflowStateV2"]
    assert examples["workflowStateV2"]["state_version"] == 2


def test_request_hash_v1_positive_and_negative_cases() -> None:
    fixture = _load("request-hash-v1-cases.json")
    base_identity = _request_identity(fixture["baseRaw"], fixture)
    assert list(base_identity) == fixture["includedTopLevelFields"]
    base_hash = _sha256(base_identity)
    assert base_hash == fixture["baseExpectedSha256"]

    different_hashes = set()
    for case in fixture["cases"]:
        raw = copy.deepcopy(fixture["baseRaw"])
        raw.update(copy.deepcopy(case["overrides"]))
        candidate_hash = _sha256(_request_identity(raw, fixture))
        if case["expectedRelation"] == "same":
            assert candidate_hash == base_hash, case["caseId"]
        else:
            assert candidate_hash != base_hash, case["caseId"]
            different_hashes.add(candidate_hash)
    assert len(different_hashes) == sum(
        case["expectedRelation"] == "different" for case in fixture["cases"]
    )


def test_invalidation_matrix_uses_closed_vocabulary() -> None:
    fixture = _load("revision-invalidation-matrix-v1.json")
    expected_actions = {
        "reset",
        "preserve",
        "revalidate",
        "invalidate",
        "invalidate_affected",
        "retain_audit_only",
        "never_retain",
        "scope_gate",
        "mark_stale_refs",
        "mark_stale_decisions",
    }
    assert set(fixture["actions"]) == expected_actions
    used = {
        row[dimension]
        for row in fixture["items"]
        for dimension in fixture["dimensions"]
    }
    assert used == expected_actions
    assert len({row["item"] for row in fixture["items"]}) == len(fixture["items"]) == 10


def test_stage_metadata_covers_registry_and_safe_regressions() -> None:
    from ai_inspector.agent_skills.runtime import WorkflowRegistry

    fixture = _load("workflow-stage-revalidation-v1.json")
    registry = WorkflowRegistry.from_roots([ROOT / "ai_inspector" / "agent_workflows"])
    configured = {row["workflowId"]: row for row in fixture["workflows"]}
    assert set(configured) == set(registry.ids)
    dependencies = set(fixture["dependencyVocabulary"])
    authorization_kinds = set(fixture["authorizationKinds"])

    for workflow_id in sorted(registry.ids):
        package = registry.get(workflow_id)
        row = configured[workflow_id]
        assert row["workflowVersion"] == package.manifest.version
        assert row["firstStage"] == package.manifest.stages[0]
        assert [item["stage"] for item in row["stages"]] == list(package.manifest.stages)
        stage_index = {stage: index for index, stage in enumerate(package.manifest.stages)}
        for stage in row["stages"]:
            assert stage["dependencies"]
            assert set(stage["dependencies"]) <= dependencies
            if stage["authorizationKind"] is not None:
                assert stage["authorizationKind"] in authorization_kinds
                assert stage["safePredecessor"] is not None
            predecessor = stage["safePredecessor"]
            if predecessor is not None:
                assert stage_index[predecessor] < stage_index[stage["stage"]]

    for case in fixture["revalidationCases"]:
        workflow = configured[case["workflowId"]]
        stage = next(item for item in workflow["stages"] if item["stage"] == case["currentStage"])
        changed = set(case["changedDependencies"])
        if stage["authorizationKind"] is not None:
            actual_stage = stage["safePredecessor"] or workflow["firstStage"]
            event = "authorization_stage_invalidated"
        elif changed.intersection(stage["dependencies"]):
            actual_stage = stage["safePredecessor"] or workflow["firstStage"]
            event = "stage_regressed"
        else:
            actual_stage = stage["stage"]
            event = "stage_preserved"
        assert (actual_stage, event) == (case["expectedStage"], case["expectedEvent"])


def test_pending_turn_revision_barrier_scenarios_are_closed() -> None:
    fixture = _load("pending-turn-revision-barrier-v1.json")
    assert set(fixture["classifications"]) == {"read_only", "preview", "action_write"}
    assert {row["scenarioId"] for row in fixture["scenarios"]} == {
        "read-only-revision-advanced",
        "preview-blocked-before-effect",
        "action-cas-closes-race",
        "successful-effect-with-unrelated-post-drift",
    }
    for row in fixture["scenarios"]:
        expected = row["expected"]
        if expected["effectCount"]:
            assert row["receipt"] is not None
            assert row["casOutcome"] == "applied"
            assert row["receipt"]["authorizedBeforeVector"] == row["sourceRevisionVector"]
        else:
            assert row["receipt"] is None
        if row["classification"] in {"preview", "action_write"} and (
            row["preEffectRevisionVector"] != row["sourceRevisionVector"]
        ):
            assert expected["terminalStatus"] == "failed"
            assert expected["effectCount"] == 0


def test_transcript_accounting_reproduces_current_behavior() -> None:
    fixture = _load("transcript-accounting-v1.json")
    spec = fixture["generator"]
    measured = {row["name"]: row for row in fixture["measurements"]}
    for size in spec["sizes"]:
        messages = _generated_transcript(spec, size["historyTurns"])
        current = {"role": "user", "content": spec["currentRequest"]}
        anthropic_json = json.dumps(
            messages + [current], ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        history_lines = [f"[{row['role']}]\n{row['content'].strip()}" for row in messages]
        openai_history = (
            "<conversation_history>\n"
            + "\n\n".join(history_lines)
            + "\n</conversation_history>"
        )
        router = messages[-4:]
        expected = measured[size["name"]]
        assert expected == {
            "name": size["name"],
            "historyTurns": size["historyTurns"],
            "anthropicSerializedCharacters": len(anthropic_json),
            "anthropicEstimatedTokens": math.ceil(len(anthropic_json) / 4),
            "openAiHistoryCharacters": len(openai_history),
            "openAiHistoryEstimatedTokens": math.ceil(len(openai_history) / 4),
            "routerTurns": len(router),
            "routerCharacters": sum(len(row["content"][:400]) for row in router),
        }
    assert measured["long"]["anthropicEstimatedTokens"] > measured["short"]["anthropicEstimatedTokens"] * 20


def test_migration_inventory_is_complete_unique_and_closed() -> None:
    fixture = _load("workflow-state-v1-migration-inventory.json")
    module_path = ROOT / "tools" / "build_sage_memory_p10_inventory.py"
    spec = importlib.util.spec_from_file_location("sage_memory_p10_inventory", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate_inventory(fixture, require_closed=True)
    assert fixture["counts"] == {
        "entries": 117,
        "files": 8,
        "bySymbol": {"asset_fingerprint": 104, "advance_workflow_state": 13},
    }
    entries = fixture["entries"]
    assert len({row["occurrenceId"] for row in entries}) == len(entries)
    assert {row["occurrenceKind"] for row in entries} <= set(fixture["allowedOccurrenceKinds"])
    assert {
        disposition: sum(
            row["migrationDisposition"] == disposition for row in entries
        )
        for disposition in ("migrated", "removed", "retained_v1_reader")
    } == {
        "migrated": 95,
        "removed": 13,
        "retained_v1_reader": 9,
    }
    assert all(row["verificationFixture"] and row["sourceSnippetSha256"] for row in entries)


def test_runtime_baseline_claims_and_historical_hashes_are_pinned() -> None:
    fixture = _load("current-runtime-memory-baseline-v1.json")
    for row in fixture["sourceFiles"]:
        assert (ROOT / row["path"]).is_file()
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8-sig")
    server = (ROOT / "server.py").read_text(encoding="utf-8-sig")
    routing = (ROOT / "ai_inspector" / "agent_skills" / "routing.py").read_text(encoding="utf-8-sig")
    assert "const AGENT_CHAT_REGISTRY_KEY = 'inspectorpro.chat_registry.v1'" in index
    assert ".filter(msg => !(msg.meta && msg.meta.pending))" in index
    assert "block.dataUrl = null" in index
    assert "recent_turns[-4:]" in routing and "[:400]" in routing
    assert "def _openai_responses_input" in server
    assert "<conversation_history>" in server
    assert "def _resolve_trusted_process_map_context" in server
    assert "def _resolve_trusted_facility_layout_context" in server
    for field in ("process_map_graph", "process_map_state", "process_map_evidence"):
        assert f'ctx.pop("{field}", None)' in server
    for field in ("facility_layout_digest", "facility_layout_state", "facility_layout_evidence"):
        assert f'ctx.pop("{field}", None)' in server


def test_v2_source_has_only_the_named_legacy_reader_boundary() -> None:
    fixture = _load("workflow-state-v1-migration-inventory.json")
    matches = []
    pattern = re.compile(r"asset_fingerprint|advance_workflow_state(?!_v2)")
    for relative_path in fixture["search"]["paths"]:
        source = (ROOT / relative_path).read_text(encoding="utf-8-sig")
        for line_number, line in enumerate(source.splitlines(), start=1):
            for match in pattern.finditer(line):
                matches.append((relative_path, line_number, match.group(0), line.strip()))
    assert len(matches) == 1
    path, _line_number, symbol, line = matches[0]
    assert path == "ai_inspector/agent_skills/workflow_state.py"
    assert symbol == "asset_fingerprint"
    assert 'value.get("asset_fingerprint")' in line


def test_principal_topology_and_reference_workstation_decisions_are_closed() -> None:
    principal = _load("principal-mapping-v1.json")
    topology = _load("pilot-deployment-topology-v1.json")
    workstation = _load("reference-workstation.json")
    assert principal["browserAuthorityFields"] == []
    assert (principal["local"]["tenantId"], principal["local"]["userId"]) == (
        "local",
        "local-user",
    )
    assert topology["decision"] == "sqlite"
    assert topology["storage"]["insideOneDrive"] is False
    assert topology["storage"]["networkFilesystem"] is False
    assert not any(row["applies"] for row in topology["postgresqlTriggers"])
    assert workstation["cpu"]["logicalProcessors"] == 12
    assert workstation["memory"]["bytes"] > 16_000_000_000
    assert workstation["storage"]["filesystem"] == "NTFS"


def test_all_p10_json_artifacts_are_ascii_clean() -> None:
    for path in sorted(FIXTURES.glob("*.json")):
        raw = path.read_bytes()
        raw.decode("ascii")
        assert b"\r" not in raw
        assert raw.endswith(b"\n")
        assert all(line.rstrip(b" \t") == line for line in raw.splitlines())
