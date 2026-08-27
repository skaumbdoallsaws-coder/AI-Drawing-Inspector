from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from ai_inspector.facility_layout.feature_flags import (
    FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES,
    FACILITY_LAYOUT_CAPABILITY_FLAGS,
    FACILITY_LAYOUT_FEATURE_FLAGS,
    FacilityLayoutFeatureFlags,
)
from ai_inspector.facility_layout.knowledge_foundation import (
    FACILITY_COMMAND_EFFECTS,
    FACILITY_GENERATION_RUN_SCHEMA_VERSION,
    FACILITY_GENERATION_STAGES,
    FACILITY_KNOWLEDGE_SCHEMA_VERSION,
    FACILITY_MAXIMUM_OPERATION_BATCH,
    FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
    FacilityKnowledgeContractError,
    canonical_cell_recipe_registry,
    canonical_cell_strategy_registry,
    canonical_facility_agent_tool_registry,
    canonical_facility_command_registry,
    canonical_facility_knowledge_bytes,
    default_generation_stage_graph,
    facility_domain_ontology,
    facility_intent_schema,
    facility_knowledge_registry,
    facility_sage_responsibility_contract,
    query_facility_knowledge,
    validate_department_partition_request,
    validate_facility_envelope_request,
    validate_facility_intent,
    validate_generation_run,
    validate_generation_save_receipt,
    validate_generation_stage,
    validate_generation_substage,
)
from ai_inspector.facility_layout.semantic_model import (
    AGENT_TOOL_SEMANTICS,
    CELL_LAYOUT_STRATEGIES,
    FACILITY_COMMAND_SEMANTICS,
)


ZERO_SHA = "0" * 64


def _intent() -> dict:
    return {
        "schemaVersion": FACILITY_KNOWLEDGE_SCHEMA_VERSION,
        "intentId": "intent-g1",
        "mode": "greenfield",
        "facilityEnvelope": {
            "width": 300,
            "depth": 200,
            "sourceUnit": "ft",
            "displayName": "Pilot Factory",
        },
        "originConvention": {
            "origin": "southwest_floor_corner",
            "northDirection": "positive_z",
            "source": "user",
        },
        "departments": [
            {
                "requestId": "dept-receiving",
                "label": "Receiving",
                "semanticType": "receiving",
                "quantity": 1,
                "proportion": 0.4,
            },
            {
                "requestId": "dept-assembly",
                "label": "Assembly",
                "semanticType": "assembly",
                "quantity": 1,
                "proportion": 0.6,
                "adjacentTo": ["dept-receiving"],
            },
        ],
        "circulation": [],
        "cells": [],
        "resources": [],
        "staging": [],
        "floorCommunication": [],
        "utilities": [],
        "expansion": None,
        "hardConstraints": [],
        "preferences": [],
        "assumptions": [],
        "unresolvedItems": [],
        "sourceRevisionBindings": [
            {
                "sourceId": "source-user-request",
                "revision": "turn-1",
                "evidenceStatus": "authored",
            }
        ],
        "authorityBindings": [
            {
                "authorityId": "authority-prototype",
                "status": "pending",
                "source": "system",
            }
        ],
        "executionMode": "authorized_draft_run",
        "savePolicy": "explicit_user_command",
        "prototypeMode": True,
    }


def _run() -> dict:
    return {
        "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
        "runId": "fgr-contract-fixture",
        "tenantId": "tenant-a",
        "siteId": "site-a",
        "workspaceId": "workspace-a",
        "layoutId": "fl-a",
        "userId": "user-a",
        "sessionId": "session-a",
        "baseLayoutRevision": ZERO_SHA,
        "effectiveProvider": "anthropic",
        "effectiveModel": "claude-sonnet-4-5-20250929",
        "reasoningEffort": None,
        "intentHash": "1" * 64,
        "dependencyFingerprint": "2" * 64,
        "stageGraph": default_generation_stage_graph(),
        "currentStageId": "facility_envelope",
        "resumePoint": {
            "stageId": "facility_envelope",
            "substageId": None,
            "turnSequence": 0,
        },
        "receiptChain": [],
        "invalidations": [],
        "status": "active",
        "writable": False,
        "writableLease": None,
        "prototypeMode": True,
        "createdAt": "2026-08-26T00:00:00.000000Z",
        "updatedAt": "2026-08-26T00:00:00.000000Z",
        "lastActivityAt": "2026-08-26T00:00:00.000000Z",
        "expiresAt": "2026-08-27T00:00:00.000000Z",
        "cumulativeDiffHash": None,
        "cumulativeProposal": None,
        "saveEligibility": "blocked",
        "terminalReason": None,
    }


def test_registry_preserves_exact_runtime_surface_and_owners() -> None:
    commands = canonical_facility_command_registry()
    tools = canonical_facility_agent_tool_registry()
    assert {item["commandId"] for item in commands} == {
        item["commandId"] for item in FACILITY_COMMAND_SEMANTICS
    }
    assert {item["commandId"] for item in tools} == {
        item["commandId"] for item in AGENT_TOOL_SEMANTICS
    }
    assert len(commands) == 39
    assert len(tools) == 15
    assert set(item["effect"] for item in commands) == set(FACILITY_COMMAND_EFFECTS)
    assert all(item["deterministicOwner"] for item in commands)
    assert len({item["commandId"] for item in commands}) == len(commands)
    for item in commands:
        assert item["semanticIntent"]
        assert item["correctUseCases"]
        assert item["incorrectUseCases"] or item["effect"] == "viewport"
        assert item["inputSchema"]["additionalProperties"] is False
        assert item["uiCommandId"] == item["commandId"]
        for capability in item["requiredCapabilities"]:
            assert capability in FACILITY_LAYOUT_CAPABILITY_FLAGS
            assert item["featureFlagDependencies"][capability] == list(
                FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES[capability]
            )


def test_cell_strategies_preserve_all_source_fields_and_add_four_groups() -> None:
    records = canonical_cell_strategy_registry()
    assert len(records) == 10
    by_id = {item["strategyId"]: item for item in records}
    for source in CELL_LAYOUT_STRATEGIES:
        migrated = by_id[source["strategyId"]]
        for key, value in source.items():
            assert migrated[key] == value
        assert set(migrated) - set(source) == {
            "schemaVersion",
            "spaceModel",
            "interfaces",
            "accessAssumptions",
            "resultMetrics",
        }
    assert len(canonical_cell_recipe_registry()) == 8


def test_ontology_and_responsibility_contract_are_repeatable() -> None:
    first = facility_domain_ontology()
    second = facility_domain_ontology()
    assert first == second
    assert first["ontologyRevision"] == hashlib.sha256(
        canonical_facility_knowledge_bytes(
            {key: value for key, value in first.items() if key != "ontologyRevision"}
        )
    ).hexdigest()
    assert all(not item["labelMaySubstituteForIdentity"] for item in first["entities"])
    responsibility = facility_sage_responsibility_contract()
    assert responsibility["authorityBoundary"]["modelMayApproveOrRelease"] is False
    assert responsibility["receiptClaims"]["modelTextAloneProvesExecution"] is False


def test_intent_schema_normalizes_units_and_rejects_model_geometry() -> None:
    assert facility_intent_schema()["additionalProperties"] is False
    normalized = validate_facility_intent(_intent())
    assert normalized["facilityEnvelope"]["widthMeters"] == pytest.approx(91.44)
    assert normalized["facilityEnvelope"]["depthMeters"] == pytest.approx(60.96)
    bad = _intent()
    bad["cells"] = [{"requestId": "cell-a", "position": {"x": 10, "z": 20}}]
    with pytest.raises(FacilityKnowledgeContractError) as exc:
        validate_facility_intent(bad)
    assert exc.value.code == "model_authored_geometry_forbidden"


def test_intent_never_promotes_model_authority() -> None:
    bad = _intent()
    bad["authorityBindings"][0] = {
        "authorityId": "authority-invalid",
        "status": "approved",
        "source": "model",
    }
    with pytest.raises(FacilityKnowledgeContractError) as exc:
        validate_facility_intent(bad)
    assert exc.value.code == "human_authority_required"


@pytest.mark.parametrize(
    ("width", "unit", "expected"),
    [(500, "mm", 0.5), (10_000, "m", 10_000.0), (12, "in", None)],
)
def test_facility_envelope_bounds_and_units(width: float, unit: str, expected: float | None) -> None:
    value = {"width": width, "depth": width, "sourceUnit": unit}
    if expected is None:
        with pytest.raises(FacilityKnowledgeContractError) as exc:
            validate_facility_envelope_request(value)
        assert exc.value.code == "facility_dimension_out_of_bounds"
    else:
        assert validate_facility_envelope_request(value)["widthMeters"] == pytest.approx(expected)


def test_department_defaults_are_disclosed_and_explicit_proportions_win() -> None:
    defaulted = validate_department_partition_request(
        {"labels": ["Receiving", "Assembly"], "count": 2}
    )
    assert defaulted["proportions"] == [0.5, 0.5]
    assert defaulted["assumptions"] == ["equal_area_partition"]
    assert defaulted["inventedCorridor"] is False
    explicit = validate_department_partition_request(
        {
            "labels": ["Receiving", "Assembly"],
            "count": 2,
            "proportions": [1, 3],
        }
    )
    assert explicit["proportions"] == [0.25, 0.75]
    assert explicit["assumptions"] == []


def test_bounded_registry_query_is_exact_and_fails_closed() -> None:
    result = query_facility_knowledge(
        command_ids=["rectangle-zone", "bulk-zones"],
        stage_ids=["macro_departments"],
    )
    payload = canonical_facility_knowledge_bytes(result)
    assert result["measurement"]["canonicalBytes"] == len(payload)
    assert len(payload) <= FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES
    with pytest.raises(FacilityKnowledgeContractError) as unknown:
        query_facility_knowledge(command_ids=["not-a-command"])
    assert unknown.value.code == "unknown_registry_identifier"
    with pytest.raises(FacilityKnowledgeContractError) as oversized:
        query_facility_knowledge(
            command_ids=[item["commandId"] for item in FACILITY_COMMAND_SEMANTICS],
        )
    assert oversized.value.code == "registry_slice_too_large"


def test_stage_substage_and_run_contracts_enforce_frozen_graph_and_caps() -> None:
    substage = {
        "substageId": "substage-a",
        "sequence": 1,
        "status": "ready",
        "operationCount": FACILITY_MAXIMUM_OPERATION_BATCH,
        "plannedInstanceCount": 500,
        "operationReceiptIds": [],
        "validation": {"status": "pending"},
        "affectedStableIds": [],
    }
    assert validate_generation_substage(substage)["operationCount"] == 500
    too_large = deepcopy(substage)
    too_large["operationCount"] = 501
    with pytest.raises(FacilityKnowledgeContractError) as exc:
        validate_generation_substage(too_large)
    assert exc.value.code == "generation_substage_budget_exceeded"
    run = _run()
    run["stageGraph"][0]["substageGraph"] = [substage]
    run["stageGraph"][0]["selectedCommandIds"] = ["fit-layout"]
    assert validate_generation_run(run)["runId"] == run["runId"]
    wrong = deepcopy(run["stageGraph"][1])
    wrong["dependsOn"] = []
    with pytest.raises(FacilityKnowledgeContractError) as dependency:
        validate_generation_stage(wrong)
    assert dependency.value.code == "generation_stage_dependency_mismatch"


def test_save_receipt_requires_explicit_human_command() -> None:
    receipt = {
        "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
        "saveReceiptId": "save-a",
        "runId": "fgr-contract-fixture",
        "tenantId": "tenant-a",
        "siteId": "site-a",
        "workspaceId": "workspace-a",
        "layoutId": "fl-a",
        "baseLayoutRevision": ZERO_SHA,
        "savedLayoutRevision": "1" * 64,
        "cumulativeDiffHash": "2" * 64,
        "dependencyFingerprint": "3" * 64,
        "receiptChain": ["receipt-a"],
        "approvedBy": "user-a",
        "approvedAt": "2026-08-26T00:00:00.000000Z",
        "persistedAt": "2026-08-26T00:00:01.000000Z",
        "approvalSource": "explicit_user_command",
    }
    assert validate_generation_save_receipt(receipt)["approvalSource"] == "explicit_user_command"
    receipt["approvalSource"] = "model"
    with pytest.raises(FacilityKnowledgeContractError) as exc:
        validate_generation_save_receipt(receipt)
    assert exc.value.code == "explicit_approval_required"


def test_feature_flag_ladder_is_unchanged() -> None:
    flags = FacilityLayoutFeatureFlags.all_enabled()
    assert len(FACILITY_LAYOUT_FEATURE_FLAGS) == 7
    assert all(flags.enabled(item) for item in FACILITY_LAYOUT_CAPABILITY_FLAGS)
    assert list(FACILITY_LAYOUT_CAPABILITY_DEPENDENCIES) == [
        "viewer_v2",
        "asset_library",
        "manual_edit",
        "constraints",
        "routing",
        "agent_preview",
        "agent_write",
    ]


def test_full_registry_is_stable_and_complete() -> None:
    first = facility_knowledge_registry()
    second = facility_knowledge_registry()
    assert first == second
    assert len(first["commands"]) == 39
    assert len(first["agentTools"]) == 15
    assert len(first["cellStrategies"]) == 10
    assert len(first["stages"]) == len(FACILITY_GENERATION_STAGES) == 10
