"""Executable gates for the operations-manual pre-coding package."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "operations-manual"


def _load(name: str) -> dict[str, Any]:
    return json.loads((DOCS / name).read_text(encoding="utf-8"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "null": value is None,
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }[expected]


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    assert ref.startswith("#/"), f"unsupported reference {ref}"
    current: Any = root
    for token in ref[2:].split("/"):
        current = current[token.replace("~1", "/").replace("~0", "~")]
    assert isinstance(current, dict)
    return current


def _valid(value: Any, schema: dict[str, Any], root: dict[str, Any]) -> bool:
    try:
        _validate(value, schema, root)
    except AssertionError:
        return False
    return True


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> None:
    if "$ref" in schema:
        _validate(value, _resolve_ref(root, schema["$ref"]), root, path)

    if "allOf" in schema:
        for candidate in schema["allOf"]:
            _validate(value, candidate, root, path)
    if "anyOf" in schema:
        assert any(_valid(value, candidate, root) for candidate in schema["anyOf"]), f"{path}: no anyOf match"
    if "oneOf" in schema:
        matches = sum(_valid(value, candidate, root) for candidate in schema["oneOf"])
        assert matches == 1, f"{path}: expected one oneOf match, got {matches}"

    if "if" in schema:
        branch = schema.get("then") if _valid(value, schema["if"], root) else schema.get("else")
        if branch is not None:
            _validate(value, branch, root, path)

    if "const" in schema:
        assert value == schema["const"], f"{path}: const mismatch"
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: value not in enum"

    declared_type = schema.get("type")
    if declared_type is not None:
        expected = declared_type if isinstance(declared_type, list) else [declared_type]
        assert any(_matches_type(value, item) for item in expected), f"{path}: wrong type"

    if isinstance(value, dict):
        required = set(schema.get("required", []))
        assert required <= set(value), f"{path}: missing {sorted(required - set(value))}"
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False:
            assert set(value) <= set(properties), f"{path}: extra {sorted(set(value) - set(properties))}"
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], root, f"{path}.{key}")
            elif isinstance(additional, dict):
                _validate(item, additional, root, f"{path}.{key}")
    elif isinstance(value, list):
        assert len(value) >= int(schema.get("minItems", 0)), f"{path}: too few items"
        if "maxItems" in schema:
            assert len(value) <= int(schema["maxItems"]), f"{path}: too many items"
        if schema.get("uniqueItems"):
            encoded = [_canonical_bytes(item) for item in value]
            assert len(encoded) == len(set(encoded)), f"{path}: duplicate items"
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{index}]")
    elif isinstance(value, str):
        assert len(value) >= int(schema.get("minLength", 0)), f"{path}: too short"
        if "pattern" in schema:
            assert re.search(schema["pattern"], value), f"{path}: pattern mismatch"
        if schema.get("format") == "date":
            date.fromisoformat(value)
        elif schema.get("format") == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif schema.get("format") == "uri":
            parsed = urlparse(value)
            assert parsed.scheme and (parsed.netloc or parsed.scheme == "file"), f"{path}: invalid URI"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema:
            assert value >= schema["minimum"], f"{path}: below minimum"


@pytest.mark.parametrize(
    ("document", "schema_name"),
    [
        ("source-register.json", "source-register.schema.json"),
        ("evidence-register.json", "evidence-register.schema.json"),
        ("mmle-50d-prototype-plan.example.json", "operations-manual-plan.schema.json"),
        ("safety-symbol-register.json", "safety-symbol-register.schema.json"),
    ],
)
def test_registered_documents_validate(document: str, schema_name: str) -> None:
    schema = _load(schema_name)
    _validate(_load(document), schema, schema)


def test_source_ids_references_and_local_hashes_are_closed() -> None:
    sources = _load("source-register.json")["sources"]
    evidence = _load("evidence-register.json")
    source_ids = [source["sourceId"] for source in sources]
    assert len(source_ids) == len(set(source_ids))

    for source in sources:
        if "canonicalLocation" not in source:
            continue
        path = ROOT / source["canonicalLocation"]
        assert path.is_file(), source["sourceId"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"].lower(), source["sourceId"]

    known_sources = set(source_ids)
    claim_ids = {claim["claimId"] for claim in evidence["claims"]}
    conflict_ids = {conflict["conflictId"] for conflict in evidence["conflicts"]}
    assert len(claim_ids) == len(evidence["claims"])
    assert len(conflict_ids) == len(evidence["conflicts"])
    for claim in evidence["claims"]:
        assert set(claim["sourceIds"]) <= known_sources
        assert set(claim.get("conflictIds", [])) <= conflict_ids
    for conflict in evidence["conflicts"]:
        assert set(conflict["sourceIds"]) <= known_sources


def test_review_corrections_are_machine_readable() -> None:
    sources = _load("source-register.json")["sources"]
    evidence = _load("evidence-register.json")
    by_source = {item["sourceId"]: item for item in sources}
    by_claim = {item["claimId"]: item for item in evidence["claims"]}
    by_conflict = {item["conflictId"]: item for item in evidence["conflicts"]}
    by_gap = {item["gapId"]: item for item in evidence["gaps"]}

    assert by_source["SRC-IP-MMLE-REGISTRY"]["sha256"]
    assert by_source["LIB-PYMUPDF-1-27-2-3"]["licenseReview"]["status"] == "pending"
    assert all(item["editionVerification"]["status"] for item in sources if item["kind"] == "standard")
    assert by_claim["CLM-SAFETY-FEATURE-004"]["conflictIds"] == ["CONFLICT-008"]
    assert by_claim["CLM-REVISION-001"]["status"] == "publication_rule"
    assert by_conflict["CONFLICT-008"]["releaseBlocking"] is True
    assert by_conflict["CONFLICT-009"]["releaseBlocking"] is True
    assert by_gap["GAP-012"]["releaseBlocking"] is True
    assert by_gap["GAP-013"]["releaseBlocking"] is True


def test_source_schema_rejects_unhashed_local_and_unreviewed_verified_records() -> None:
    schema = _load("source-register.schema.json")
    sources = _load("source-register.json")

    unhashed = copy.deepcopy(sources)
    local = next(item for item in unhashed["sources"] if "canonicalLocation" in item)
    local["sha256"] = None
    assert not _valid(unhashed, schema, schema)

    anonymous_verification = copy.deepcopy(sources)
    standard = next(item for item in anonymous_verification["sources"] if item["kind"] == "standard")
    standard["editionVerification"]["status"] = "verified_current"
    standard["editionVerification"].pop("reviewer", None)
    standard["editionVerification"].pop("verifiedAt", None)
    assert not _valid(anonymous_verification, schema, schema)


def test_plan_claims_and_manual_groups_resolve() -> None:
    plan = _load("mmle-50d-prototype-plan.example.json")
    evidence = _load("evidence-register.json")
    registry = json.loads(
        (ROOT / "ai_inspector" / "assembly_knowledge" / "documentation_assembly_registry.json").read_text(
            encoding="utf-8"
        )
    )
    claim_ids = {item["claimId"] for item in evidence["claims"]}
    assembly = next(item for item in registry["assemblies"] if item["assemblyNumber"] == "MMLE-50D")
    group_ids = {item["name"] for item in assembly["manualPlanning"]["groups"]}

    for section in plan["sections"]:
        assert set(section["requiredClaimIds"]) <= claim_ids
        assert set(section["optionalClaimIds"]) <= claim_ids
        for block in section["blocks"]:
            assert set(block["evidenceClaimIds"]) <= claim_ids
        for figure in section["figureRequests"]:
            assert set(figure["scope"]["manualGroupIds"]) <= group_ids


def test_figure_scope_and_feature_mapping_negative_contracts() -> None:
    schema = _load("operations-manual-plan.schema.json")
    plan = _load("mmle-50d-prototype-plan.example.json")
    invalid_scope = copy.deepcopy(plan)
    figure = invalid_scope["sections"][0]["figureRequests"][0]
    figure["visibility"] = "isolate_scope"
    assert not _valid(invalid_scope, schema, schema)

    invalid_feature = copy.deepcopy(plan)
    invalid_feature["sections"][0]["figureRequests"][0]["featureClaimIds"] = ["CLM-SAFETY-FEATURE-004"]
    assert not _valid(invalid_feature, schema, schema)


def test_approval_and_symbol_release_conditions_reject_incomplete_records() -> None:
    approval_schema = _load("approval-receipt.schema.json")
    receipt = {
        "receiptId": "APR-TEST-001",
        "productConfigurationId": "mmle-50d-unverified-prototype",
        "artifactType": "manual_plan",
        "scope": {"description": "Test plan"},
        "role": "engineering",
        "reviewer": {"name": "Reviewer", "organization": "Example", "identity": "reviewer@example.invalid"},
        "decision": "approved",
        "sourceRevision": "source-1",
        "evidenceRevision": "evidence-1",
        "planRevision": "plan-1",
        "documentRevision": "document-1",
        "signedAt": "2026-08-20T12:00:00-05:00",
        "signatureMethod": "authenticated_application_action",
    }
    _validate(receipt, approval_schema, approval_schema)

    conditional = copy.deepcopy(receipt)
    conditional["decision"] = "approved_with_conditions"
    assert not _valid(conditional, approval_schema, approval_schema)

    symbol_schema = _load("safety-symbol-register.schema.json")
    symbols = _load("safety-symbol-register.json")
    symbols["status"] = "approved"
    assert not _valid(symbols, symbol_schema, symbol_schema)
