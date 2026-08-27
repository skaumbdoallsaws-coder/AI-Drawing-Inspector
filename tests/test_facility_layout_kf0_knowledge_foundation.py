from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from ai_inspector.facility_layout import feature_flags as flag_module
from ai_inspector.facility_layout.agent_runtime import (
    FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS,
    FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN,
    FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES,
    FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS,
)
from ai_inspector.facility_layout.operations import MAX_OPERATION_BATCH
from ai_inspector.facility_layout.planner import MAXIMUM_PLANNED_INSTANCES
from ai_inspector.facility_layout.generation_coordinator import (
    G1_FACILITY_GENERATION_TOOL,
)
from ai_inspector.facility_layout.semantic_model import (
    AGENT_TOOL_SEMANTICS,
    FACILITY_COMMAND_SEMANTICS,
)
from tools import build_facility_layout_kf0_baseline as kf0


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "facility-layout-kf0-baseline-manifest.json"
CROSSWALK = ROOT / "docs" / "facility-layout-kf0-command-crosswalk.json"
DECISIONS = ROOT / "docs" / "facility-layout-kf0-decisions.json"
GAPS = ROOT / "docs" / "facility-layout-kf0-capability-gaps.json"
REPORT = ROOT / "docs" / "facility-layout-kf0-baseline-report.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="ascii"))


def _canonical_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def test_kf0_artifacts_are_ascii_well_formed_and_internally_valid():
    for path in (MANIFEST, CROSSWALK, DECISIONS, GAPS, REPORT):
        payload = path.read_bytes()
        payload.decode("ascii")
        assert payload

    assert kf0.check(current_sources=False) == []
    manifest = _load(MANIFEST)
    assert manifest["schemaVersion"] == "facility-layout-kf0-baseline-v1"
    assert manifest["baselineDisposition"] == {
        "changedSurfaceSuitesGreen": True,
        "facilityReleaseBlockedByQuarantines": True,
        "facilityReleaseEvidenceCurrent": False,
        "kf0ExitEligible": True,
        "quarantinedFailureCount": 13,
        "rawFailureCount": 13,
        "unexplainedFailureCount": 0,
    }


def test_kf0_crosswalk_preserves_its_snapshot_and_current_registry_evolution():
    crosswalk = _load(CROSSWALK)
    commands = crosswalk["commandRegistry"]["commands"]
    tools = crosswalk["agentToolRegistry"]["tools"]
    live_commands = list(FACILITY_COMMAND_SEMANTICS)
    live_tools = list(AGENT_TOOL_SEMANTICS)
    kf0_live_tools = [
        item for item in live_tools
        if item["commandId"] != G1_FACILITY_GENERATION_TOOL
    ]

    assert [item["commandId"] for item in commands] == [
        item["commandId"] for item in live_commands
    ]
    assert [item["commandId"] for item in tools] == [
        item["commandId"] for item in kf0_live_tools
    ]
    assert len(commands) == len({item["commandId"] for item in commands}) == 39
    assert len(tools) == len({item["commandId"] for item in tools}) == 14
    assert [item["commandId"] for item in live_tools].count(
        G1_FACILITY_GENERATION_TOOL
    ) == 1
    assert len(live_tools) == 15
    assert crosswalk["commandRegistry"]["ribbonCount"] == 32
    assert crosswalk["commandRegistry"]["nonRibbonCount"] == 7
    assert kf0._parse_ribbon_command_ids() == [
        item["commandId"] for item in commands if item["uiSurface"] == "ribbon"
    ]
    assert Counter(item["effect"] for item in commands) == {
        "draft_edit": 28,
        "viewport": 8,
        "read": 1,
        "persistent_save": 1,
        "viewport_capture": 1,
    }
    assert all(item["uiHandler"] for item in commands)
    assert all(item["deterministicOwner"] for item in commands)
    assert all(item["requiredCapabilities"] for item in commands)
    assert all(item["tests"] for item in commands)
    assert all(item["deterministicOwner"] for item in tools)
    assert all(item["tests"] for item in tools)
    assert all(
        item["operationKernelHandlers"]
        if item["operationKernelApplicability"] == "applicable"
        else not item["operationKernelHandlers"]
        for item in commands
    )

    ladder = crosswalk["featureFlagLadder"]
    assert ladder["orderedCapabilities"] == list(flag_module._CAPABILITY_FLAGS)
    assert [item["environmentVariable"] for item in ladder["flags"]] == list(
        flag_module.FACILITY_LAYOUT_FEATURE_FLAGS
    )
    assert [item["dependencies"] for item in ladder["flags"]] == [
        list(flag_module._DEPENDENCIES[item["capability"]])
        for item in ladder["flags"]
    ]
    classification = crosswalk["classification"]
    assert classification["allCommandsClassified"] is True
    assert classification["allAgentToolsClassified"] is True
    assert classification["allEffectsClassified"] is True
    assert classification["allFeatureFlagsClassified"] is True
    assert classification["unclassifiedCommandIds"] == []
    assert classification["unclassifiedAgentToolIds"] == []


def test_kf0_decisions_freeze_runtime_authority_and_gate_g1_bounds():
    decisions = _load(DECISIONS)
    budgets = decisions["runtimeBudgets"]
    assert budgets["toolCallsPerTurn"] == (
        FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN
    )
    assert budgets["toolResponseBytes"] == (
        FACILITY_LAYOUT_AGENT_MAXIMUM_RESPONSE_BYTES
    )
    assert budgets["cursorTtlSeconds"] == (
        FACILITY_LAYOUT_AGENT_CURSOR_TTL_SECONDS
    )
    assert budgets["turnTtlSeconds"] == (
        FACILITY_LAYOUT_AGENT_TURN_TTL_SECONDS
    )
    assert budgets["operationBatch"] == MAX_OPERATION_BATCH == 500
    assert budgets["plannedInstances"] == MAXIMUM_PLANNED_INSTANCES == 500
    assert budgets["skillContextTargetEstimatedTokens"] == 9600
    assert budgets["skillContextHardEstimatedTokens"] == 12000
    assert budgets["stageRegistrySliceCanonicalBytes"] == 8192
    assert budgets["estimator"] == {
        "formula": "ceil(canonical_utf8_bytes / 4)",
        "id": "bytes4-v1",
        "isModelTokenizer": False,
    }
    measured = decisions["runtimeBudgetArtifactMeasurement"]
    encoded = _canonical_bytes(budgets)
    assert measured["canonicalBytes"] == len(encoded)
    assert measured["estimatedTokens"] == (len(encoded) + 3) // 4
    assert measured["canonicalSha256"] == hashlib.sha256(encoded).hexdigest()

    authority = decisions["authorityPolicy"]
    assert authority["modelMayGrantHumanAuthority"] is False
    assert authority["modelMayApproveOrRelease"] is False
    assert authority["prototypeModeRequiresExplicitFlag"] is True
    assert authority["humanApprovalRequiredForPersistentSave"] is True
    assert authority["finalSaveIsSeparateExplicitCommand"] is True
    assert len(decisions["stageTaxonomy"]) == 10
    assert [item["stage"] for item in decisions["stageTaxonomy"]] == list(
        range(1, 11)
    )

    g1 = decisions["gateG1Defaults"]
    assert g1["minimumFacilityAxisMeters"] == 0.5
    assert g1["maximumFacilityAxisMeters"] == 10000.0
    assert g1["supportedSourceUnits"] == ["m", "mm", "ft", "in"]
    assert g1["minimumDepartmentCount"] == 1
    assert g1["maximumDepartmentCount"] == 50
    assert g1["labelsOnlyDefault"] == (
        "equal_area_partition_with_disclosed_assumption"
    )
    assert g1["inventExpansionReserve"] is False
    assert g1["inventCorridor"] is False
    assert g1["inventSafetySeparation"] is False

    configuration = decisions["configuration"]
    assert configuration["provider"] == "anthropic"
    assert configuration["model"] == "claude-sonnet-4-5-20250929"
    assert configuration["reasoningEffort"] is None
    assert configuration["apiKeyRecorded"] is False
    assert all(
        name.startswith("INSPECTORPRO_FACILITY_LAYOUT_SAGE_")
        for name in configuration["futureFacilityScopedEnvironmentVariables"]
    )


def test_kf0_evaluation_inventory_is_regression_visible_not_held_out():
    manifest = _load(MANIFEST)
    inventory = manifest["fixtures"]["evaluation"]
    fixture = _load(
        ROOT
        / "tests"
        / "fixtures"
        / "facility_layout"
        / "semantic_intelligence"
        / "evaluation-cases-v1.json"
    )
    assert inventory["count"] == 71
    assert [item["id"] for item in inventory["cases"]] == [
        item["id"] for item in fixture["cases"]
    ]
    assert all(
        item["classification"] == "regression_visible"
        and item["heldOut"] is False
        for item in inventory["cases"]
    )


def test_kf0_quarantines_are_explicit_release_blockers_not_silent_passes():
    manifest = _load(MANIFEST)
    quarantines = manifest["quarantines"]
    assert len(quarantines) == 13
    assert len({item["testId"] for item in quarantines}) == 13
    assert {
        item["testId"] for item in quarantines
    } == set(kf0.EXPECTED_QUARANTINES)
    for item in quarantines:
        assert item["owner"]
        assert item["reason"]
        assert item["expiryCondition"]
        assert len(item["testSource"]["sha256"]) == 64
        assert len(item["baselineEvidence"]["sha256"]) == 64
        assert item["changedSurfaceIntersection"] is False
        assert item["blocksChangedSurfaceRegressionClaim"] is False
        assert item["blocksFacilityReleaseClaim"] is True
        assert item["disposition"] == "quarantined_release_evidence"
        assert item["nonIntersectionEvidence"][
            "independentCurrentBehaviorEvidence"
        ]


def test_kf0_capability_matrix_classifies_k1_through_k10():
    gaps = _load(GAPS)
    records = gaps["records"]
    assert [item["capabilityId"] for item in records] == [
        f"K{index}" for index in range(1, 11)
    ]
    assert gaps["summary"] == {"missing": 4, "partial": 6}
    assert gaps["allK1ThroughK10Classified"] is True
    assert all(item["gap"] and item["closureMilestone"] for item in records)
