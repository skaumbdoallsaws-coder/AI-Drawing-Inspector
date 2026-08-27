"""Bounded Facility Layout tool knowledge compiled from the KF1 registry."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence

from .knowledge_foundation import (
    FACILITY_CONTEXT_MAXIMUM_ESTIMATED_TOKENS,
    FACILITY_CONTEXT_TARGET_ESTIMATED_TOKENS,
    FACILITY_GENERATION_STAGES,
    FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
    FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES,
    FacilityKnowledgeContractError,
    bytes4_estimate,
    canonical_facility_knowledge_bytes,
    facility_knowledge_registry,
)


FACILITY_TOOL_KNOWLEDGE_VERSION = "facility-tool-knowledge-v1"
FACILITY_SKILL_CONTEXT_TARGET_BYTES = (
    FACILITY_CONTEXT_TARGET_ESTIMATED_TOKENS * 4
)
FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES = (
    FACILITY_CONTEXT_MAXIMUM_ESTIMATED_TOKENS * 4
)

_GENERIC_SUPPORT_COMMAND_IDS = frozenset({
    "select",
    "pan",
    "delete",
    "clear-all",
    "undo",
    "redo",
    "fit",
    "fit-layout",
    "top-view",
    "orbit",
    "walkthrough",
    "drone",
})

_STAGE_CORE_COMMAND_IDS: Mapping[str, tuple[str, ...]] = {
    "facility_envelope": (),
    "macro_departments": ("rectangle-zone", "polygon-zone", "bulk-zones"),
    "primary_circulation": ("aisle",),
    "department_subdivisions": (
        "rectangle-zone",
        "polygon-zone",
        "bulk-zones",
        "duplicate",
    ),
    "department_resources": (
        "assets",
        "rotate",
        "lock",
        "relative",
        "distance",
        "vertical-stack",
        "surface-stack",
        "auto-arrange",
    ),
    "seed_cells": (
        "assets",
        "lock",
        "relative",
        "distance",
        "cell-layout",
        "create-cell-group",
        "ungroup-cell",
        "auto-arrange",
    ),
    "repeated_modules": (
        "duplicate",
        "linear-pattern",
        "circular-pattern",
        "perimeter-pattern",
        "cell-layout",
        "create-cell-group",
        "mirror",
    ),
    "floor_communication": ("floor-marking", "duplicate"),
    "deterministic_validation": (),
    "review_and_save": ("save", "record"),
}

_AGENT_TOOL_STAGES: Mapping[str, tuple[str, ...]] = {
    "search_industrial_assets": (
        "department_resources",
        "seed_cells",
        "repeated_modules",
    ),
    "inspect_facility_entities": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES
    ),
    "inspect_facility_region": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES[1:]
    ),
    "inspect_facility_findings": (
        "deterministic_validation",
        "review_and_save",
    ),
    "inspect_process_bindings": (
        "department_resources",
        "seed_cells",
        "repeated_modules",
        "deterministic_validation",
    ),
    "inspect_facility_semantics": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES
    ),
    "inspect_pattern_provenance": (
        "repeated_modules",
        "floor_communication",
        "deterministic_validation",
        "review_and_save",
    ),
    "inspect_cell_layout_provenance": (
        "seed_cells",
        "repeated_modules",
        "floor_communication",
        "deterministic_validation",
        "review_and_save",
    ),
    "analyze_facility_spatial": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES[1:]
    ),
    "analyze_facility_fit": (
        "department_resources",
        "seed_cells",
        "repeated_modules",
    ),
    "preview_facility_move": (
        "department_resources",
        "seed_cells",
        "repeated_modules",
        "floor_communication",
    ),
    "build_facility_layout_preview": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES[:8]
    ),
    "generate_facility_departments_draft": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES
    ),
    "present_chat_visualization": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES
    ),
    "present_chat_table": tuple(
        item["stageId"] for item in FACILITY_GENERATION_STAGES
    ),
}


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _registry_indexes() -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    registry = facility_knowledge_registry()
    commands = {item["commandId"]: item for item in registry["commands"]}
    tools = {item["commandId"]: item for item in registry["agentTools"]}
    stages = {item["stageId"]: item for item in registry["stages"]}
    if set(tools) != set(_AGENT_TOOL_STAGES):
        raise FacilityKnowledgeContractError(
            "facility_agent_tool_stage_coverage_mismatch",
            "Every canonical Facility agent tool must have a stage contract.",
            details={
                "missing": sorted(set(tools) - set(_AGENT_TOOL_STAGES)),
                "unknown": sorted(set(_AGENT_TOOL_STAGES) - set(tools)),
            },
        )
    return registry, commands, tools, stages


def _measure_bounded(
    value: Mapping[str, Any],
    *,
    maximum_bytes: int,
    overflow_code: str,
    diagnostic: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes < 256
    ):
        raise FacilityKnowledgeContractError(
            "invalid_tool_knowledge_budget",
            "Tool-knowledge maximum_bytes must be an integer of at least 256.",
        )
    result = deepcopy(dict(value))
    result["measurement"] = {
        "canonicalBytes": 0,
        "estimatedTokens": 0,
        "estimatorId": "bytes4-v1",
        "maximumBytes": maximum_bytes,
    }
    for _attempt in range(12):
        byte_count = len(canonical_facility_knowledge_bytes(result))
        measurement = {
            "canonicalBytes": byte_count,
            "estimatedTokens": bytes4_estimate(byte_count),
            "estimatorId": "bytes4-v1",
            "maximumBytes": maximum_bytes,
        }
        if result["measurement"] == measurement:
            break
        result["measurement"] = measurement
    payload = canonical_facility_knowledge_bytes(result)
    if result["measurement"]["canonicalBytes"] != len(payload):
        result["measurement"]["canonicalBytes"] = len(payload)
        result["measurement"]["estimatedTokens"] = bytes4_estimate(len(payload))
        payload = canonical_facility_knowledge_bytes(result)
    if len(payload) > maximum_bytes:
        raise FacilityKnowledgeContractError(
            overflow_code,
            "Facility tool knowledge exceeds its canonical byte limit.",
            details={
                **deepcopy(dict(diagnostic)),
                "canonicalBytes": len(payload),
                "estimatedTokens": bytes4_estimate(len(payload)),
                "maximumBytes": maximum_bytes,
            },
        )
    return result


def _command_index_card(command: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "commandId": command["commandId"],
        "label": command["label"],
        "effect": command["effect"],
        "semanticIntent": command["semanticIntent"],
        "deterministicOwner": command["deterministicOwner"],
    }


def _command_selection_guide(command: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_command_index_card(command),
        "inputFields": list(command["inputContract"]["fields"]),
        "correctUse": command["correctUseCases"][0],
        "prohibitedUse": command["prohibitedUses"][0],
        "requiredCapabilities": list(command["requiredCapabilities"]),
    }


def _agent_tool_guide(tool: Mapping[str, Any]) -> dict[str, Any]:
    execution = tool["executionContract"]
    return {
        "toolId": tool["commandId"],
        "effect": tool["effect"],
        "semanticIntent": tool["semanticUse"],
        "deterministicOwner": tool["deterministicOwner"],
        "requiredCapabilities": list(tool["requiredCapabilities"]),
        "modelCalculatesGeometry": bool(execution["modelCalculatesGeometry"]),
        "mutatesSavedLayout": bool(execution["mutatesSavedLayout"]),
        "returnsRevisionBoundEvidence": bool(
            execution["returnsRevisionBoundEvidence"]
        ),
    }


def _agent_tool_index_guide(tool: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "toolId": tool["commandId"],
        "effect": tool["effect"],
        "semanticIntent": tool["semanticUse"],
        "deterministicOwner": tool["deterministicOwner"],
    }


def _mutation_path(command: Mapping[str, Any]) -> dict[str, str]:
    effect = command["effect"]
    if effect == "draft_edit":
        return {
            "preview": "build_facility_layout_preview",
            "validation": "facility.validate_layout",
            "receipt": "facility_generation_stage_receipt",
            "undo": "undo",
        }
    if effect == "persistent_save":
        return {
            "preview": "cumulative_diff_review",
            "validation": "facility.validate_layout_and_receipt_chain",
            "receipt": "facility_generation_save_receipt",
            "undo": "new_revision_required",
        }
    return {
        "preview": "not_required",
        "validation": "input_contract_only",
        "receipt": "not_required",
        "undo": "not_document_mutation",
    }


def compile_command_explanation(
    command_id: str,
    *,
    maximum_bytes: int = FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
) -> dict[str, Any]:
    registry, commands, _tools, _stages = _registry_indexes()
    command = commands.get(str(command_id))
    if command is None:
        raise FacilityKnowledgeContractError(
            "unknown_facility_command",
            "Facility command is not registered.",
            details={"commandId": str(command_id)},
        )
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_command_explanation",
        "knowledgeVersion": FACILITY_TOOL_KNOWLEDGE_VERSION,
        "registryRevision": registry["registryRevision"],
        "command": deepcopy(command),
        "mutationPath": _mutation_path(command),
        "limits": {
            "modelAuthoredWorldCoordinatesAllowed": False,
            "screenCoordinatesAreDocumentIntent": False,
            "implicitSaveAllowed": False,
            "humanAuthorityMayBeInferred": False,
        },
    }
    return _measure_bounded(
        value,
        maximum_bytes=maximum_bytes,
        overflow_code="facility_command_explanation_too_large",
        diagnostic={"commandId": str(command_id)},
    )


def compile_agent_tool_explanation(
    tool_id: str,
    *,
    maximum_bytes: int = FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
) -> dict[str, Any]:
    registry, _commands, tools, _stages = _registry_indexes()
    tool = tools.get(str(tool_id))
    if tool is None:
        raise FacilityKnowledgeContractError(
            "unknown_facility_agent_tool",
            "Facility agent tool is not registered.",
            details={"toolId": str(tool_id)},
        )
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_agent_tool_explanation",
        "knowledgeVersion": FACILITY_TOOL_KNOWLEDGE_VERSION,
        "registryRevision": registry["registryRevision"],
        "agentTool": deepcopy(tool),
        "supportedStages": list(_AGENT_TOOL_STAGES[tool["commandId"]]),
        "limits": {
            "modelAuthoredWorldCoordinatesAllowed": False,
            "implicitSaveAllowed": False,
            "humanAuthorityMayBeInferred": False,
        },
    }
    return _measure_bounded(
        value,
        maximum_bytes=maximum_bytes,
        overflow_code="facility_agent_tool_explanation_too_large",
        diagnostic={"toolId": str(tool_id)},
    )


def compile_stage_tool_knowledge(
    stage_id: str,
    *,
    maximum_bytes: int = FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
) -> dict[str, Any]:
    registry, commands, tools, stages = _registry_indexes()
    stage_key = str(stage_id)
    stage = stages.get(stage_key)
    if stage is None:
        raise FacilityKnowledgeContractError(
            "unknown_facility_stage",
            "Facility generation stage is not registered.",
            details={"stageId": stage_key},
        )
    supported = [
        command
        for command in commands.values()
        if stage_key in command["supportedStages"]
    ]
    stage_commands = [
        command
        for command in supported
        if command["commandId"] not in _GENERIC_SUPPORT_COMMAND_IDS
    ]
    core_ids = set(_STAGE_CORE_COMMAND_IDS[stage_key])
    primary = [
        command for command in stage_commands if command["commandId"] in core_ids
    ]
    additional = [
        command["commandId"]
        for command in stage_commands
        if command["commandId"] not in core_ids
    ]
    support = [
        command["commandId"]
        for command in supported
        if command["commandId"] in _GENERIC_SUPPORT_COMMAND_IDS
    ]
    stage_tools = [
        tools[tool_id]
        for tool_id, stage_ids in _AGENT_TOOL_STAGES.items()
        if stage_key in stage_ids
    ]
    strategy_ids = []
    recipe_ids = []
    if stage_key in {"seed_cells", "repeated_modules"}:
        strategy_ids = [item["strategyId"] for item in registry["cellStrategies"]]
        recipe_ids = [item["recipeId"] for item in registry["cellRecipes"]]
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_stage_tool_knowledge",
        "knowledgeVersion": FACILITY_TOOL_KNOWLEDGE_VERSION,
        "registryRevision": registry["registryRevision"],
        "stage": deepcopy(stage),
        "primaryCommands": [_command_selection_guide(item) for item in primary],
        "additionalCommandIds": additional,
        "supportCommandIds": support,
        "agentTools": [_agent_tool_index_guide(item) for item in stage_tools],
        "cellStrategyIds": strategy_ids,
        "cellRecipeIds": recipe_ids,
        "selectionRules": {
            "selectBySemanticIntent": True,
            "retrieveFullCommandBeforeExecution": True,
            "modelAuthoredCoordinatesAllowed": False,
            "deterministicOwnerExecutes": True,
            "explicitSaveOnly": True,
        },
        "availableQueries": [
            "command_explanation",
            "stage",
            "capability",
            "compatibility",
            "prerequisites",
            "prohibitions",
            "followups",
        ],
    }
    return _measure_bounded(
        value,
        maximum_bytes=maximum_bytes,
        overflow_code="facility_stage_tool_knowledge_too_large",
        diagnostic={
            "stageId": stage_key,
            "primaryCommandIds": [item["commandId"] for item in primary],
            "additionalCommandIds": additional,
            "supportCommandIds": support,
            "agentToolIds": [item["commandId"] for item in stage_tools],
        },
    )


def compile_capability_tool_knowledge(
    capability: str,
    *,
    maximum_bytes: int = FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
) -> dict[str, Any]:
    registry, commands, tools, _stages = _registry_indexes()
    known = set(registry["capabilityFlags"])
    if capability not in known:
        raise FacilityKnowledgeContractError(
            "unknown_facility_capability",
            "Facility capability is not registered.",
            details={"capability": str(capability)},
        )
    selected_commands = [
        item
        for item in commands.values()
        if capability in item["requiredCapabilities"]
        or capability in item["featureFlagDependencies"]
    ]
    selected_tools = [
        item
        for item in tools.values()
        if capability in item["requiredCapabilities"]
    ]
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_capability_tool_knowledge",
        "knowledgeVersion": FACILITY_TOOL_KNOWLEDGE_VERSION,
        "registryRevision": registry["registryRevision"],
        "capability": capability,
        "featureFlag": registry["capabilityFlags"][capability],
        "dependsOn": list(registry["capabilityDependencies"].get(capability, [])),
        "commands": [_command_index_card(item) for item in selected_commands],
        "agentTools": [_agent_tool_guide(item) for item in selected_tools],
    }
    return _measure_bounded(
        value,
        maximum_bytes=maximum_bytes,
        overflow_code="facility_capability_tool_knowledge_too_large",
        diagnostic={"capability": str(capability)},
    )


def query_command_compatibility(command_id: str) -> dict[str, Any]:
    explanation = compile_command_explanation(command_id)
    command = explanation["command"]
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_command_compatibility",
        "registryRevision": explanation["registryRevision"],
        "commandId": command["commandId"],
        "supportedStages": list(command["supportedStages"]),
        "compatibleNextCommands": list(command["compatibleNextCommands"]),
        "incompatibleCommands": list(command["incompatibleCommands"]),
        "requiredCapabilities": list(command["requiredCapabilities"]),
    }
    return _measure_bounded(
        value,
        maximum_bytes=FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
        overflow_code="facility_compatibility_response_too_large",
        diagnostic={"commandId": str(command_id)},
    )


def query_command_prerequisites(command_id: str) -> dict[str, Any]:
    explanation = compile_command_explanation(command_id)
    command = explanation["command"]
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_command_prerequisites",
        "registryRevision": explanation["registryRevision"],
        "commandId": command["commandId"],
        "preconditions": list(command["preconditions"]),
        "requiredContext": list(command["requiredContext"]),
        "requiredCapabilities": list(command["requiredCapabilities"]),
        "requiredFeatureFlags": list(command["requiredFeatureFlags"]),
        "featureFlagDependencies": deepcopy(command["featureFlagDependencies"]),
        "inputSchema": deepcopy(command["inputSchema"]),
        "defaultPolicy": command["defaultPolicy"],
    }
    return _measure_bounded(
        value,
        maximum_bytes=FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
        overflow_code="facility_prerequisite_response_too_large",
        diagnostic={"commandId": str(command_id)},
    )


def query_command_prohibitions(command_id: str) -> dict[str, Any]:
    explanation = compile_command_explanation(command_id)
    command = explanation["command"]
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_command_prohibitions",
        "registryRevision": explanation["registryRevision"],
        "commandId": command["commandId"],
        "incorrectUseCases": list(command["incorrectUseCases"]),
        "prohibitedUses": list(command["prohibitedUses"]),
        "incompatibleCommands": list(command["incompatibleCommands"]),
        "limits": deepcopy(explanation["limits"]),
    }
    return _measure_bounded(
        value,
        maximum_bytes=FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
        overflow_code="facility_prohibition_response_too_large",
        diagnostic={"commandId": str(command_id)},
    )


def query_command_followups(command_id: str) -> dict[str, Any]:
    explanation = compile_command_explanation(command_id)
    command = explanation["command"]
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_command_followups",
        "registryRevision": explanation["registryRevision"],
        "commandId": command["commandId"],
        "compatibleNextCommands": list(command["compatibleNextCommands"]),
        "mutationPath": deepcopy(explanation["mutationPath"]),
        "receiptShape": deepcopy(command["receiptShape"]),
        "undoSemantics": command["undoSemantics"],
    }
    return _measure_bounded(
        value,
        maximum_bytes=FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
        overflow_code="facility_followup_response_too_large",
        diagnostic={"commandId": str(command_id)},
    )


def compile_facility_ui_metadata() -> dict[str, Any]:
    registry, commands, _tools, _stages = _registry_indexes()
    group_order = (
        "selection",
        "create",
        "arrange",
        "position",
        "pattern",
        "history",
        "layout",
        "document",
    )
    ribbon_groups = []
    for group in group_order:
        command_ids = [
            item["commandId"]
            for item in commands.values()
            if item["group"] == group and "ribbon" in item["uiSurfaces"]
        ]
        if command_ids:
            ribbon_groups.append({
                "groupId": group,
                "label": group.replace("_", " ").title(),
                "commandIds": command_ids,
            })
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_ui_command_metadata",
        "knowledgeVersion": FACILITY_TOOL_KNOWLEDGE_VERSION,
        "registryRevision": registry["registryRevision"],
        "ribbonGroups": ribbon_groups,
        "commands": [
            {
                "commandId": item["commandId"],
                "label": item["label"],
                "group": item["group"],
                "effect": item["effect"],
                "scope": item["scope"],
                "uiSurfaces": list(item["uiSurfaces"]),
                "requiredFeatureFlags": list(item["requiredFeatureFlags"]),
            }
            for item in commands.values()
        ],
    }
    return _measure_bounded(
        value,
        maximum_bytes=FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES,
        overflow_code="facility_ui_metadata_too_large",
        diagnostic={"commandCount": len(commands)},
    )


def compile_facility_agent_tool_metadata() -> dict[str, Any]:
    registry, _commands, tools, _stages = _registry_indexes()
    value = {
        "schemaVersion": 1,
        "recordKind": "facility_agent_tool_metadata",
        "knowledgeVersion": FACILITY_TOOL_KNOWLEDGE_VERSION,
        "registryRevision": registry["registryRevision"],
        "agentTools": [
            {
                **_agent_tool_guide(item),
                "label": item["label"],
                "scope": item["scope"],
                "supportedStages": list(_AGENT_TOOL_STAGES[item["commandId"]]),
            }
            for item in tools.values()
        ],
    }
    return _measure_bounded(
        value,
        maximum_bytes=FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES,
        overflow_code="facility_agent_tool_metadata_too_large",
        diagnostic={"agentToolCount": len(tools)},
    )


def validate_facility_command_surface_parity(
    *,
    ui_command_ids: Sequence[str],
    agent_tool_ids: Sequence[str],
) -> dict[str, Any]:
    _registry, commands, tools, _stages = _registry_indexes()
    expected_ui = set(commands)
    expected_tools = set(tools)
    supplied_ui = set(_stable_unique(ui_command_ids))
    supplied_tools = set(_stable_unique(agent_tool_ids))
    if supplied_ui != expected_ui or supplied_tools != expected_tools:
        raise FacilityKnowledgeContractError(
            "facility_command_surface_parity_mismatch",
            "Facility UI or agent-tool identifiers differ from the canonical registry.",
            details={
                "missingUi": sorted(expected_ui - supplied_ui),
                "unknownUi": sorted(supplied_ui - expected_ui),
                "missingAgentTools": sorted(expected_tools - supplied_tools),
                "unknownAgentTools": sorted(supplied_tools - expected_tools),
            },
        )
    return {
        "status": "pass",
        "uiCommandCount": len(expected_ui),
        "agentToolCount": len(expected_tools),
    }


def measure_facility_skill_context(
    context: Mapping[str, Any],
    *,
    tool_response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context_bytes = len(canonical_facility_knowledge_bytes(context))
    response_bytes = (
        len(canonical_facility_knowledge_bytes(tool_response))
        if tool_response is not None
        else 0
    )
    if context_bytes > FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES:
        raise FacilityKnowledgeContractError(
            "facility_skill_context_hard_limit_exceeded",
            "Facility skill context exceeds the hard context limit.",
            details={
                "canonicalBytes": context_bytes,
                "estimatedTokens": bytes4_estimate(context_bytes),
                "maximumBytes": FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES,
            },
        )
    if response_bytes > FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES:
        raise FacilityKnowledgeContractError(
            "facility_tool_response_hard_limit_exceeded",
            "Facility tool response exceeds the hard response limit.",
            details={
                "canonicalBytes": response_bytes,
                "maximumBytes": FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES,
            },
        )
    return {
        "estimatorId": "bytes4-v1",
        "contextCanonicalBytes": context_bytes,
        "contextEstimatedTokens": bytes4_estimate(context_bytes),
        "contextTargetBytes": FACILITY_SKILL_CONTEXT_TARGET_BYTES,
        "contextMaximumBytes": FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES,
        "withinContextTarget": context_bytes <= FACILITY_SKILL_CONTEXT_TARGET_BYTES,
        "toolResponseCanonicalBytes": response_bytes,
        "toolResponseMaximumBytes": FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES,
        "withinToolResponseLimit": response_bytes <= FACILITY_TOOL_RESPONSE_MAXIMUM_BYTES,
    }


__all__ = [
    "FACILITY_SKILL_CONTEXT_MAXIMUM_BYTES",
    "FACILITY_SKILL_CONTEXT_TARGET_BYTES",
    "FACILITY_TOOL_KNOWLEDGE_VERSION",
    "compile_capability_tool_knowledge",
    "compile_agent_tool_explanation",
    "compile_command_explanation",
    "compile_facility_agent_tool_metadata",
    "compile_facility_ui_metadata",
    "compile_stage_tool_knowledge",
    "measure_facility_skill_context",
    "query_command_compatibility",
    "query_command_followups",
    "query_command_prerequisites",
    "query_command_prohibitions",
    "validate_facility_command_surface_parity",
]
