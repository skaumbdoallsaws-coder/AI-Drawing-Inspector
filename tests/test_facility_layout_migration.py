from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import canonical_layout_bytes
from ai_inspector.facility_layout.errors import (
    FacilityCompatibilityError,
    FacilityIntegrityError,
)
from ai_inspector.facility_layout.migration import migrate_legacy_semantic_v02
from ai_inspector.facility_layout.schema_v1 import detect_layout_compatibility
from ai_inspector.facility_layout.validate import validate_layout


MIGRATION = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "migration"
)


def _load(name: str) -> dict:
    return json.loads((MIGRATION / name).read_text(encoding="ascii"))


def _source() -> bytes:
    return (MIGRATION / "legacy-semantic-v0.2.input.json").read_bytes()


def _context() -> dict:
    return _load("legacy-semantic-v0.2.migration-context.json")


def test_legacy_migration_matches_all_frozen_documents_exactly():
    bundle = migrate_legacy_semantic_v02(_source(), _context())
    assert bundle.layout == _load("legacy-semantic-v0.2.expected-layout-v1.json")
    assert bundle.shell == _load("legacy-semantic-v0.2.expected-shell-v1.json")
    assert bundle.policy_set == _load(
        "legacy-semantic-v0.2.expected-policy-v1.json"
    )
    assert list(bundle.evidence_records) == [
        _load("legacy-semantic-v0.2.expected-evidence-v1.json")
    ]
    validate_layout(bundle.layout, require_canonical=True)


def test_migration_is_deterministic_and_canonical_layout_bytes_are_stable():
    first = migrate_legacy_semantic_v02(_source(), _context())
    second = migrate_legacy_semantic_v02(_source(), deepcopy(_context()))
    assert first.to_dict() == second.to_dict()
    assert canonical_layout_bytes(first.layout) == canonical_layout_bytes(
        second.layout
    )


def test_migration_retains_the_complete_legacy_payload_and_source_identity():
    source = _source()
    parsed = json.loads(source)
    bundle = migrate_legacy_semantic_v02(source, _context())
    retained = bundle.layout["extensions"]["inspectorproLegacySemanticV0_2"]
    assert retained["payload"] == parsed
    assert retained["sourceByteLength"] == len(source)
    assert retained["sourceSha256"] == hashlib.sha256(source).hexdigest()
    assert retained["payload"]["futureRootField"] == parsed["futureRootField"]
    assert (
        retained["payload"]["layoutMap"]["futureLayoutField"]
        == parsed["layoutMap"]["futureLayoutField"]
    )


def test_migration_regenerates_all_five_pinned_legacy_ids():
    bundle = migrate_legacy_semantic_v02(_source(), _context())
    assert bundle.layout["layoutId"] == "fl-legacy-33ea0aeb31bb98a2f8f0"
    assert (
        bundle.layout["sourceShellRef"]["shellId"]
        == "shell-legacy-cc6490e95e7c50f92ed1"
    )
    assert (
        bundle.layout["policySetRef"]["policySetId"]
        == "policy-legacy-bd9684d48638d0524305"
    )
    assert (
        bundle.layout["placements"][0]["placementId"]
        == "pl-legacy-a8a737880b15ffbae445"
    )
    assert (
        bundle.layout["zones"][0]["zoneId"]
        == "zn-legacy-b8c3ba5b369e128fd3af"
    )


def test_migration_promotes_only_explicitly_bound_content():
    bundle = migrate_legacy_semantic_v02(_source(), _context())
    assert len(bundle.layout["placements"]) == 1
    assert len(bundle.layout["zones"]) == 1
    placement = bundle.layout["placements"][0]
    assert placement["metadata"]["legacyComponentName"] == "Rack-01"
    assert placement["positionMode"] == "locked"
    assert placement["metadata"]["readOnly"] is True
    retained = bundle.layout["extensions"]["inspectorproLegacySemanticV0_2"][
        "payload"
    ]
    assert retained["materialHandlingAssets"][0]["componentName"] == "Forklift-01"
    assert retained["aisles"]
    assert retained["layoutMap"]["pathGraph"]


def test_migration_authority_revisions_match_generated_documents():
    bundle = migrate_legacy_semantic_v02(_source(), _context())

    def fingerprint(value: dict) -> str:
        raw = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(raw).hexdigest()

    assert (
        bundle.layout["sourceShellRef"]["shellRevision"]
        == fingerprint(bundle.shell)
    )
    assert (
        bundle.layout["policySetRef"]["policySetRevision"]
        == fingerprint(bundle.policy_set)
    )


def test_source_byte_tampering_is_rejected_before_projection():
    source = _source().replace(b"Sanitized warehouse sample", b"Sanitized warehouse samplf")
    with pytest.raises(FacilityIntegrityError) as captured:
        migrate_legacy_semantic_v02(source, _context())
    assert captured.value.code == "legacy_source_hash_mismatch"


def test_source_length_mismatch_is_rejected_before_projection():
    context = _context()
    context["source"]["byteLength"] += 1
    with pytest.raises(FacilityIntegrityError) as captured:
        migrate_legacy_semantic_v02(_source(), context)
    assert captured.value.code == "legacy_source_length_mismatch"


def test_stale_shell_or_policy_context_is_rejected():
    shell = _context()
    shell["sourceShellRef"]["shellRevision"] = "0" * 64
    with pytest.raises(FacilityIntegrityError) as captured:
        migrate_legacy_semantic_v02(_source(), shell)
    assert captured.value.code == "stale_shell_revision"

    policy = _context()
    policy["policySetRef"]["policySetRevision"] = "0" * 64
    with pytest.raises(FacilityIntegrityError) as captured:
        migrate_legacy_semantic_v02(_source(), policy)
    assert captured.value.code == "stale_policy_revision"


def test_migration_requires_original_bytes_not_a_parsed_mapping():
    with pytest.raises(FacilityIntegrityError) as captured:
        migrate_legacy_semantic_v02(json.loads(_source()), _context())
    assert captured.value.code == "legacy_source_bytes_required"


def test_nonlegacy_source_cannot_enter_the_legacy_migration():
    source = json.dumps(
        {"schemaVersion": 1},
        separators=(",", ":"),
    ).encode("ascii")
    context = _context()
    context["source"]["byteLength"] = len(source)
    context["source"]["sha256"] = hashlib.sha256(source).hexdigest()
    context["source"]["schemaVersion"] = 1
    with pytest.raises(FacilityCompatibilityError) as captured:
        migrate_legacy_semantic_v02(source, context)
    assert captured.value.code == "unsupported_legacy_schema"


def test_newer_schema_bytes_remain_exact_and_are_not_migrated():
    source = (MIGRATION / "newer-schema-v2.input.json").read_bytes()
    expected = _load("newer-schema-v2.expected-read-only.json")
    result = detect_layout_compatibility(source)
    assert result.mode == "read_only"
    assert result.original_bytes == source
    assert len(source) == expected["source"]["byteLength"]
    assert hashlib.sha256(source).hexdigest() == expected["source"]["sha256"]
    assert result.migration_allowed is False
    assert result.canonical_rewrite_allowed is False
