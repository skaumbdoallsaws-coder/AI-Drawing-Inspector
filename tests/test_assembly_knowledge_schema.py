from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeSchemaError,
    canonical_json_bytes,
    canonical_json_sha256,
    make_package_id,
    package_revision,
    require_valid_document,
    stable_id,
    validate_document,
)


FIXTURE_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)


def _minimal_package() -> dict:
    digest = "a" * 64
    return {
        "schemaVersion": 1,
        "packageId": "akp-" + ("b" * 24),
        "productId": "tricycle",
        "sourceRevision": digest,
        "packageRevision": "c" * 64,
        "extractorVersion": "0.1.0",
        "adapterVersion": "1.0.0",
        "bridgePackageSchemaVersion": "1.0",
        "enrichmentPolicyVersion": "economy-v1",
        "promptVersion": "none",
        "modelProvider": None,
        "modelId": None,
        "readiness": "structure_ready",
        "productionEligible": False,
        "documentHashes": {"source_manifest.json": "d" * 64},
        "assetHashes": {},
    }


def test_canonical_json_is_ascii_stable_and_rejects_non_finite() -> None:
    left = {"z": "cafe\u0301", "a": [2, 1]}
    right = {"a": [2, 1], "z": "cafe\u0301"}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_json_bytes(left).decode("ascii")
    with pytest.raises(ValueError):
        canonical_json_bytes({"x": float("nan")})


def test_stable_id_and_package_id_are_deterministic() -> None:
    assert stable_id("occ", {"path": "a", "cfg": "Default"}) == stable_id(
        "occ", {"cfg": "Default", "path": "a"}
    )
    assert make_package_id("tricycle", "a" * 64, "Default", "1.0.0") == (
        make_package_id("tricycle", "a" * 64, "Default", "1.0.0")
    )


def test_package_schema_accepts_minimum_and_rejects_unknown_fields() -> None:
    package = _minimal_package()
    assert validate_document("package.json", package) == []
    package["unexpected"] = True
    findings = validate_document("package.json", package)
    assert any(item["code"] == "unknown_field" for item in findings)
    with pytest.raises(AssemblyKnowledgeSchemaError):
        require_valid_document("package.json", package)


def test_package_revision_ignores_claimed_revision_and_key_order() -> None:
    package = _minimal_package()
    docs = {"source_manifest.json": {"schemaVersion": 1, "b": 2, "a": 1}}
    first = package_revision(package, docs, {"visuals/view.png": "e" * 64})
    changed_claim = copy.deepcopy(package)
    changed_claim["packageRevision"] = "f" * 64
    second = package_revision(
        changed_claim,
        {"source_manifest.json": {"a": 1, "b": 2, "schemaVersion": 1}},
        {"visuals/view.png": "e" * 64},
    )
    assert first == second
    assert canonical_json_sha256({"a": 1}) != canonical_json_sha256({"a": 2})


def test_bridge_v1_fixture_pins_repeated_occurrences_and_mates() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text("utf-8"))
    assembly = json.loads(
        (FIXTURE_ROOT / "assembly" / "assembly.json").read_text("utf-8")
    )
    assert manifest["schemaVersion"] == "1.0"
    assert manifest["kind"] == "assembly"
    assert [item["name"] for item in assembly["components"]] == [
        "Wheel-1",
        "Wheel-2",
        "Axle-1",
    ]
    assert assembly["bom_synthesized"][1]["quantity"] == 2
    assert len(assembly["mates"]) == 2


def test_unknown_document_type_fails_closed() -> None:
    findings = validate_document("browser_payload.json", {})
    assert findings == [
        {
            "severity": "error",
            "code": "unknown_document_type",
            "path": "$",
            "message": "Unsupported package document: browser_payload.json.",
        }
    ]
