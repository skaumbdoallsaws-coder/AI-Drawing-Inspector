from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.facility_layout.knowledge_foundation import (
    FACILITY_GENERATION_STAGES,
    FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
    FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES,
    FacilityKnowledgeContractError,
    canonical_facility_agent_tool_registry,
    canonical_facility_command_registry,
    canonical_facility_knowledge_bytes,
)
from ai_inspector.facility_layout.semantic_model import AGENT_TOOL_SEMANTICS
from ai_inspector.facility_layout.tool_knowledge import (
    FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES,
    FACILITY_SKILL_CONTEXT_TARGET_BYTES,
    compile_agent_tool_explanation,
    compile_capability_tool_knowledge,
    compile_command_explanation,
    compile_facility_agent_tool_metadata,
    compile_facility_ui_metadata,
    compile_stage_tool_knowledge,
    measure_facility_skill_context,
    query_command_compatibility,
    query_command_followups,
    query_command_prerequisites,
    query_command_prohibitions,
    validate_facility_command_surface_parity,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _assert_exact_measurement(value: dict, maximum_bytes: int) -> None:
    payload = canonical_facility_knowledge_bytes(value)
    assert len(payload) == value["measurement"]["canonicalBytes"]
    assert len(payload) <= maximum_bytes
    assert value["measurement"]["estimatedTokens"] == (len(payload) + 3) // 4


def _static_ribbon_command_ids() -> list[str]:
    source = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r"const FACILITY_LAYOUT_RIBBON_CONFIG = Object\.freeze\(\[(.*?)\]\);",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    return [
        token
        for command_list in re.findall(
            r"commands:\s*\[([^\]]*)\]", match.group(1), flags=re.DOTALL
        )
        for token in re.findall(r"['\"]([^'\"]+)['\"]", command_list)
    ]


def test_every_command_has_complete_on_demand_explanation() -> None:
    commands = canonical_facility_command_registry()
    for command in commands:
        explanation = compile_command_explanation(command["commandId"])
        _assert_exact_measurement(
            explanation, FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES
        )
        compiled = explanation["command"]
        assert compiled["semanticIntent"]
        assert compiled["deterministicOwner"]
        assert compiled["correctUseCases"]
        assert compiled["prohibitedUses"]
        assert compiled["requiredContext"] is not None
        if compiled["effect"] in {"draft_edit", "persistent_save"}:
            path = explanation["mutationPath"]
            assert path["preview"] != "not_required"
            assert path["validation"] != "input_contract_only"
            assert path["receipt"] != "not_required"
            assert path["undo"] != "not_document_mutation"


def test_every_agent_tool_has_bounded_stage_aware_explanation() -> None:
    for tool in canonical_facility_agent_tool_registry():
        explanation = compile_agent_tool_explanation(tool["commandId"])
        _assert_exact_measurement(
            explanation, FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES
        )
        assert explanation["supportedStages"]
        assert explanation["agentTool"]["deterministicOwner"]
        assert explanation["limits"]["modelAuthoredWorldCoordinatesAllowed"] is False


def test_all_stage_slices_are_bounded_and_semantically_lossless() -> None:
    commands = canonical_facility_command_registry()
    all_command_ids = {item["commandId"] for item in commands}
    for stage in FACILITY_GENERATION_STAGES:
        stage_id = stage["stageId"]
        value = compile_stage_tool_knowledge(stage_id)
        _assert_exact_measurement(value, FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES)
        assert value["measurement"]["estimatedTokens"] <= 2048
        selected = {
            item["commandId"] for item in value["primaryCommands"]
        } | set(value["additionalCommandIds"]) | set(value["supportCommandIds"])
        expected = {
            item["commandId"]
            for item in commands
            if stage_id in item["supportedStages"]
        }
        assert selected == expected
        assert selected <= all_command_ids
        assert value["selectionRules"]["retrieveFullCommandBeforeExecution"] is True
        assert value["selectionRules"]["modelAuthoredCoordinatesAllowed"] is False


def test_stage_overflow_fails_closed_with_complete_diagnostic() -> None:
    with pytest.raises(FacilityKnowledgeContractError) as caught:
        compile_stage_tool_knowledge("repeated_modules", maximum_bytes=7000)
    assert caught.value.code == "facility_stage_tool_knowledge_too_large"
    assert caught.value.details["canonicalBytes"] > 7000
    assert caught.value.details["primaryCommandIds"]
    assert caught.value.details["additionalCommandIds"]
    assert caught.value.details["agentToolIds"]


def test_deterministic_queries_cover_selection_and_execution_boundaries() -> None:
    capability = compile_capability_tool_knowledge("manual_edit")
    _assert_exact_measurement(capability, FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES)
    assert capability["commands"]

    compatibility = query_command_compatibility("bulk-zones")
    assert "macro_departments" in compatibility["supportedStages"]
    prerequisites = query_command_prerequisites("bulk-zones")
    assert prerequisites["inputSchema"]["additionalProperties"] is False
    assert "current_layout_digest" in prerequisites["requiredContext"]
    prohibitions = query_command_prohibitions("bulk-zones")
    assert prohibitions["prohibitedUses"]
    assert prohibitions["limits"]["implicitSaveAllowed"] is False
    followups = query_command_followups("bulk-zones")
    assert followups["mutationPath"]["receipt"] == (
        "facility_generation_stage_receipt"
    )
    assert followups["undoSemantics"]


def test_ui_and_agent_metadata_match_independent_runtime_surfaces() -> None:
    ui = compile_facility_ui_metadata()
    tools = compile_facility_agent_tool_metadata()
    _assert_exact_measurement(ui, FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES)
    _assert_exact_measurement(tools, FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES)

    canonical_ids = {
        item["commandId"] for item in canonical_facility_command_registry()
    }
    generated_ids = {item["commandId"] for item in ui["commands"]}
    assert generated_ids == canonical_ids
    generated_ribbon_ids = [
        command_id
        for group in ui["ribbonGroups"]
        for command_id in group["commandIds"]
    ]
    assert generated_ribbon_ids == _static_ribbon_command_ids()

    runtime_tool_ids = {item["commandId"] for item in AGENT_TOOL_SEMANTICS}
    generated_tool_ids = {item["toolId"] for item in tools["agentTools"]}
    assert generated_tool_ids == runtime_tool_ids
    assert validate_facility_command_surface_parity(
        ui_command_ids=sorted(generated_ids),
        agent_tool_ids=sorted(generated_tool_ids),
    ) == {
        "status": "pass",
            "uiCommandCount": 40,
        "agentToolCount": 23,
    }


def test_parity_and_unknown_identifiers_fail_closed() -> None:
    with pytest.raises(FacilityKnowledgeContractError) as caught:
        validate_facility_command_surface_parity(
            ui_command_ids=["rectangle-zone"],
            agent_tool_ids=["invent_layout"],
        )
    assert caught.value.code == "facility_command_surface_parity_mismatch"
    assert "bulk-zones" in caught.value.details["missingUi"]
    assert caught.value.details["unknownAgentTools"] == ["invent_layout"]

    for call in (
        lambda: compile_command_explanation("invent-layout"),
        lambda: compile_agent_tool_explanation("invent-layout"),
        lambda: compile_stage_tool_knowledge("invent-stage"),
        lambda: compile_capability_tool_knowledge("invent-capability"),
    ):
        with pytest.raises(FacilityKnowledgeContractError) as unknown:
            call()
        assert unknown.value.code.startswith("unknown_facility_")


def test_context_and_tool_response_budgets_use_bytes4_without_truncation() -> None:
    stage = compile_stage_tool_knowledge("macro_departments")
    response = compile_command_explanation("bulk-zones")
    context = {
        "stageKnowledge": stage,
        "layoutDigest": {"layoutId": "empty", "revision": "base-a"},
        "userIntent": "Create four equal departments in a 300 by 200 ft facility.",
        "boundedEvidence": "x" * 20_000,
    }
    measurement = measure_facility_skill_context(
        context, tool_response=response
    )
    assert measurement["withinContextTarget"] is True
    assert measurement["contextCanonicalBytes"] <= FACILITY_SKILL_CONTEXT_TARGET_BYTES
    assert measurement["contextMaximumBytes"] == FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES
    assert measurement["toolResponseCanonicalBytes"] <= FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES

    with pytest.raises(FacilityKnowledgeContractError) as context_error:
        measure_facility_skill_context(
            {"payload": "x" * FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES}
        )
    assert context_error.value.code == "facility_skill_context_hard_limit_exceeded"

    with pytest.raises(FacilityKnowledgeContractError) as response_error:
        measure_facility_skill_context(
            {},
            tool_response={"payload": "x" * FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES},
        )
    assert response_error.value.code == "facility_tool_response_hard_limit_exceeded"


def test_read_only_knowledge_endpoints_expose_same_bounded_contracts() -> None:
    with TestClient(server.app) as client:
        stage = client.get(
            "/api/training/facility-layout/knowledge/stages/macro_departments"
        )
        assert stage.status_code == 200, stage.text
        assert stage.json()["measurement"]["canonicalBytes"] <= 8192

        command = client.get(
            "/api/training/facility-layout/knowledge/commands/bulk-zones/prerequisites"
        )
        assert command.status_code == 200, command.text
        assert command.json()["commandId"] == "bulk-zones"

        tool = client.get(
            "/api/training/facility-layout/knowledge/agent-tools/"
            "build_facility_layout_preview"
        )
        assert tool.status_code == 200, tool.text
        assert tool.json()["agentTool"]["commandId"] == (
            "build_facility_layout_preview"
        )

        missing = client.get(
            "/api/training/facility-layout/knowledge/stages/not-a-stage"
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "unknown_facility_stage"
