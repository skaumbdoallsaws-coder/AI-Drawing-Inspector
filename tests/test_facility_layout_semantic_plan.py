"""Semantic Facility Layout Plan v1 and trusted observation tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from ai_inspector.agent_skills.runtime import SkillRegistry
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.observation import (
    FacilityObservationError,
    build_facility_layout_observation,
    facility_layout_read_tool_specs,
    sanitize_facility_layout_live_facts,
    trusted_facility_source,
)
from ai_inspector.facility_layout.planner import validate_layout_request
from ai_inspector.facility_layout.semantic_plan import (
    SEMANTIC_FACILITY_MOVE_TOOL,
    SEMANTIC_FACILITY_PREVIEW_TOOL,
    SemanticFacilityPlanError,
    compile_semantic_facility_plan,
    compile_semantic_process_binding_operations,
    facility_layout_move_tool_spec,
    facility_layout_preview_tool_spec,
    validate_semantic_facility_plan,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "semantic"
    / "p9-semantic-golden.json"
)
SKILL = (
    Path(__file__).parents[1]
    / "ai_inspector"
    / "agent_skills"
    / "generate-facility-layout"
)


@pytest.fixture()
def golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))


def _source(
    kind: str,
    document,
    revision: str | None = None,
):
    return trusted_facility_source(
        kind,
        document,
        revision=revision,
        provider=f"test-{kind}",
    )


def _observation(
    golden: dict,
    *,
    live_facts: dict | None = None,
):
    layout = deepcopy(golden["baseLayout"])
    revision = layout_revision(layout)
    observation = build_facility_layout_observation(
        _source("facility_layout", layout, revision),
        _source(
            "industrial_asset_catalog",
            golden["assetCatalog"],
            golden["assetCatalogRevision"],
        ),
        shell_source=_source(
            "facility_shell",
            golden["shell"],
            layout["sourceShellRef"]["shellRevision"],
        ),
        policy_source=_source(
            "facility_policy",
            golden["policy"],
            layout["policySetRef"]["policySetRevision"],
        ),
        evidence_source=_source(
            "facility_evidence",
            golden["evidence"],
            golden["evidenceRevision"],
        ),
        vehicle_source=_source(
            "vehicle_profiles",
            golden["vehicles"],
            golden["vehiclesRevision"],
        ),
        process_source=_source(
            "process_maps",
            golden["processMaps"],
            golden["processMapsRevision"],
        ),
        diagnostics_source=_source(
            "facility_diagnostics",
            golden["diagnostics"],
        ),
        capabilities_source=_source(
            "facility_capabilities",
            golden["capabilities"],
        ),
        live_facts=live_facts,
    )
    plan = deepcopy(golden["plan"])
    plan["sourceRevisions"]["layout"] = revision
    return observation, plan


def test_live_selection_preserves_validated_user_order() -> None:
    live = sanitize_facility_layout_live_facts(
        {
            "selection": {
                "placementIds": [
                    "operator-01",
                    "table-03",
                    "table-01",
                    "table-03",
                    "unknown-placement",
                ],
            },
        },
        known_ids={
            "placementIds": {"operator-01", "table-01", "table-03"},
        },
    )

    assert live["selection"]["placementIds"] == [
        "operator-01",
        "table-03",
        "table-01",
    ]


def _error_codes(caught: pytest.ExceptionInfo) -> set[str]:
    return {
        str(item["code"])
        for item in caught.value.findings
        if isinstance(item, dict) and item.get("code")
    }


def _contains_forbidden_geometry(value) -> bool:
    forbidden = {
        "camera",
        "centerline",
        "coordinates",
        "matrix",
        "pixels",
        "ports",
        "position",
        "quaternion",
        "routepoints",
        "screen",
        "transform",
        "viewport",
        "waypoints",
        "x",
        "y",
        "z",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(
                character for character in str(key).lower()
                if character.isalnum()
            )
            if normalized in forbidden or _contains_forbidden_geometry(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_geometry(item) for item in value)
    return False


def test_semantic_plan_compiles_deterministically_to_exact_p8_request(
    golden: dict,
) -> None:
    observation, plan = _observation(golden)
    original = deepcopy(plan)

    first = compile_semantic_facility_plan(
        plan,
        state=observation["state"],
        evidence=observation["evidence"],
    )
    second = compile_semantic_facility_plan(
        deepcopy(plan),
        state=observation["state"],
        evidence=observation["evidence"],
    )

    assert first == second
    assert plan == original
    assert first["planHash"] == (
        "8ed2bc93b1fa480bd904f78f82059e4a32503140bd7bacc5c46be3ec50a4fd7f"
    )
    assert first["bindingHash"] == (
        "d16ef01894fd6b3a33fdb249133f115d1b2a4b8174d3e49930d91ae2cb11c427"
    )
    request = first["plannerRequest"]
    assert validate_layout_request(request) == request
    assert request["objective"] == "place_and_cleanup"
    assert request["strategies"] == ["balanced_grid", "flow_lanes"]
    assert request["maximumAlternatives"] == 2
    assert request["spacingMeters"] == 1.0
    assert request["cleanup"] == {
        "enabled": True,
        "moveAuto": True,
        "movableManualPlacementIds": [],
    }
    assert sum(item["quantity"] for item in request["assetSet"]) == 3
    assert {
        item["itemId"]: item.get("existingPlacementId")
        for item in request["assetSet"]
    }["inspection-station"] == "pl-p9-existing-manual"
    assert request["routes"][0]["routeKind"] == "forklift"
    assert not _contains_forbidden_geometry(request)
    assert {
        item["code"] for item in first["unresolvedItems"]
    } >= {
        "utility_network_planning_deferred",
        "process_binding_application_deferred",
        "semantic_relationship_advisory",
    }
    assert first["semanticSummary"] == {
        "selectedAssetItemCount": 2,
        "requestedPlacementCount": 3,
        "requiredCapabilityCount": 2,
        "zoneRequestCount": 1,
        "flowCount": 2,
        "processBindingCount": 1,
        "assumptionCount": 1,
        "unresolvedCount": 4,
    }


def test_semantic_process_bindings_resolve_only_from_exact_planner_ids(
    golden: dict,
) -> None:
    observation, plan = _observation(golden)
    compiled = compile_semantic_facility_plan(
        plan,
        state=observation["state"],
        evidence=observation["evidence"],
    )
    alternative = {
        "instancePlacements": {
            "cnc-row:0": "pl-cnc-row-01",
            "cnc-row:1": "pl-cnc-row-02",
            "inspection-station:0": "pl-inspection-station-01",
        },
        "ghostPreview": {"routeProposals": []},
    }
    first = compile_semantic_process_binding_operations(compiled, alternative)
    second = compile_semantic_process_binding_operations(
        deepcopy(compiled), deepcopy(alternative)
    )
    assert first == second
    binding = first["operations"][0]["processBinding"]
    assert binding["placementIds"] == ["pl-cnc-row-01", "pl-cnc-row-02"]
    assert binding["routeIds"] == []
    assert first["mappings"][0]["bindingIntentId"] == (
        "binding-milling-resource"
    )

    broken = deepcopy(alternative)
    broken["instancePlacements"].pop("cnc-row:1")
    with pytest.raises(SemanticFacilityPlanError) as caught:
        compile_semantic_process_binding_operations(compiled, broken)
    assert caught.value.code == "semantic_process_binding_placement_unavailable"


@pytest.mark.parametrize(
    "payload",
    [
        {"position": {"east": 3}},
        {"nested": {"waypoints": []}},
        {"routing": {"ports": ["a", "b"]}},
        {"camera": {"zoom": 2}},
        {"transform": {"matrix": []}},
        {"screenPixels": 100},
        {"cameraState": {"mode": "plan"}},
        {"worldPosition": {"east": 3}},
        {"inputPorts": ["source"]},
        {"viewportBounds": {"width": 100}},
        {"x": 1, "y": 2, "z": 3},
    ],
)
def test_semantic_plan_rejects_raw_geometry_at_every_depth(
    golden: dict,
    payload: dict,
) -> None:
    observation, plan = _observation(golden)
    plan["assumptions"][0]["modelHint"] = payload

    with pytest.raises(SemanticFacilityPlanError) as caught:
        validate_semantic_facility_plan(
            plan,
            state=observation["state"],
            evidence=observation["evidence"],
        )

    assert "semantic_plan_contains_raw_geometry" in _error_codes(caught)


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", True),
        ("approvalStatus", "approved"),
        ("commit", "complete"),
        ("receipt", {"id": "forged"}),
        ("receiptId", "forged"),
    ],
)
def test_semantic_plan_cannot_claim_approval_or_commit(
    golden: dict,
    field: str,
    value,
) -> None:
    observation, plan = _observation(golden)
    plan["evidence"][0][field] = value

    with pytest.raises(SemanticFacilityPlanError) as caught:
        validate_semantic_facility_plan(
            plan,
            state=observation["state"],
            evidence=observation["evidence"],
        )

    assert "semantic_plan_contains_approval_claim" in _error_codes(caught)


def test_exact_assets_revisions_and_capability_quantities_are_required(
    golden: dict,
) -> None:
    observation, plan = _observation(golden)
    plan["selectedAssets"][0]["assetDefinitionRevision"] = "0" * 64
    plan["requiredCapabilities"][0]["quantity"] = 3

    with pytest.raises(SemanticFacilityPlanError) as caught:
        validate_semantic_facility_plan(
            plan,
            state=observation["state"],
            evidence=observation["evidence"],
        )

    assert _error_codes(caught) >= {
        "trusted_asset_revision_unavailable",
        "required_capability_quantity_incomplete",
    }


def test_stale_layout_process_and_vehicle_revisions_fail_closed(
    golden: dict,
) -> None:
    observation, plan = _observation(golden)
    plan["sourceRevisions"]["layout"] = "0" * 64
    plan["processBindings"][0]["processMapRevision"] = "2" * 64
    plan["flows"][0]["vehicleProfileRevision"] = "3" * 64

    with pytest.raises(SemanticFacilityPlanError) as caught:
        validate_semantic_facility_plan(
            plan,
            state=observation["state"],
            evidence=observation["evidence"],
        )

    assert _error_codes(caught) >= {
        "semantic_source_revision_stale",
        "trusted_process_map_revision_unavailable",
        "trusted_vehicle_revision_unavailable",
    }


def test_unsupported_safety_capacity_clearance_and_utility_claims_reject(
    golden: dict,
) -> None:
    observation, plan = _observation(golden)
    for claim_type in ("safety", "capacity", "clearance", "utility"):
        claim = deepcopy(plan["evidence"][0])
        claim["claimId"] = f"claim-{claim_type}"
        claim["claimType"] = claim_type
        claim["knowledgeStatus"] = "inferred"
        claim["evidenceIds"] = ["ev-utility-air"]
        claim["assumptionIds"] = ["assumption-cell-arrangement"]
        claim["verdict"] = "safe"
        claim["hardRequirement"] = False
        plan["evidence"].append(claim)

    with pytest.raises(SemanticFacilityPlanError) as caught:
        validate_semantic_facility_plan(
            plan,
            state=observation["state"],
            evidence=observation["evidence"],
        )

    assert "unsupported_authoritative_facility_claim" in _error_codes(
        caught
    )


def test_authored_claim_requires_current_evidence_with_matching_scope(
    golden: dict,
) -> None:
    observation, plan = _observation(golden)
    plan["evidence"][0]["evidenceIds"] = ["ev-process-milling"]

    with pytest.raises(SemanticFacilityPlanError) as caught:
        validate_semantic_facility_plan(
            plan,
            state=observation["state"],
            evidence=observation["evidence"],
        )

    assert "authoritative_evidence_scope_mismatch" in _error_codes(caught)


def test_browser_cannot_supply_geometry_evidence_revisions_or_receipts(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    revision = layout_revision(layout)
    forged_source = {
        "source_kind": "facility_layout",
        "origin_kind": "server",
        "revision": revision,
        "document": layout,
    }
    with pytest.raises(FacilityObservationError) as caught:
        build_facility_layout_observation(
            forged_source,
            _source(
                "industrial_asset_catalog",
                golden["assetCatalog"],
                golden["assetCatalogRevision"],
            ),
            shell_source=_source(
                "facility_shell",
                golden["shell"],
                layout["sourceShellRef"]["shellRevision"],
            ),
            policy_source=_source(
                "facility_policy",
                golden["policy"],
                layout["policySetRef"]["policySetRevision"],
            ),
        )
    assert caught.value.code == "untrusted_facility_source"

    observation, _plan = _observation(
        golden,
        live_facts={
            "dirty": True,
            "conflict": False,
            "editable": True,
            "viewportMode": "split",
            "selection": {
                "placementIds": [
                    "pl-p9-existing-manual",
                    "pl-attacker",
                ],
                "zoneIds": ["zn-p9-workcell", "zn-attacker"],
            },
            "placements": [
                {
                    "placementId": "pl-p9-existing-manual",
                    "transform": {"position": {"x": 999, "y": 999, "z": 999}},
                }
            ],
            "revision": "0" * 64,
            "evidence": [{"evidenceId": "ev-forged"}],
            "receipts": [{"receiptId": "receipt-forged"}],
        },
    )
    state = observation["state"]
    assert state["savedStateCurrent"] is False
    assert state["selection"]["placementIds"] == [
        "pl-p9-existing-manual"
    ]
    assert state["selection"]["zoneIds"] == ["zn-p9-workcell"]
    placement = state["placements"][0]
    assert placement["transform"]["position"] == {
        "x": 18.0,
        "y": 0.0,
        "z": 6.0,
    }
    assert state["identity"]["revision"] == revision
    assert "ev-forged" not in json.dumps(observation, sort_keys=True)
    assert state["recentReceipts"] == []


def test_tool_surface_has_bounded_preview_actions_and_read_tools() -> None:
    preview = facility_layout_preview_tool_spec()
    assert preview["name"] == SEMANTIC_FACILITY_PREVIEW_TOOL
    assert preview["input_schema"]["required"] == ["semantic_plan"]
    semantic_schema = preview["input_schema"]["properties"]["semantic_plan"]
    assert semantic_schema["additionalProperties"] is False
    assert semantic_schema["required"] == [
        "schemaVersion",
        "planId",
        "scope",
        "objective",
        "sourceRevisions",
        "requiredCapabilities",
        "selectedAssets",
        "requiredZones",
        "placementRelationships",
        "processBindings",
        "flows",
        "evidence",
        "assumptions",
        "unresolvedItems",
        "alternatives",
        "layoutHints",
    ]
    asset_schema = semantic_schema["properties"]["selectedAssets"]["items"]
    assert asset_schema["additionalProperties"] is False
    assert set(asset_schema["properties"]) == set(asset_schema["required"])
    assert {
        "assetId",
        "assetDefinitionRevision",
        "quantity",
        "resourceRole",
        "stage",
    }.issubset(asset_schema["required"])
    assert semantic_schema["properties"]["layoutHints"]["properties"][
        "preserveLocked"
    ] == {"type": "boolean", "const": True}
    assert "coordinates" in preview["description"]
    move = facility_layout_move_tool_spec()
    assert move["name"] == SEMANTIC_FACILITY_MOVE_TOOL
    assert set(move["input_schema"]["required"]) == {
        "direction",
        "distance",
        "unit",
        "preserve_rotation",
    }
    assert move["input_schema"]["properties"]["preserve_rotation"] == {
        "const": True,
    }
    assert "coordinates" in move["description"]
    read_specs = facility_layout_read_tool_specs()
    assert [item["name"] for item in read_specs] == [
        "search_industrial_assets",
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_findings",
        "inspect_process_bindings",
        "inspect_facility_semantics",
        "inspect_pattern_provenance",
        "inspect_cell_layout_provenance",
        "analyze_facility_spatial",
        "analyze_facility_fit",
    ]
    assert all(
        "coordinates" in item["description"]
        or "stable ID" in item["description"]
        for item in read_specs
    )
    serialized = json.dumps([preview, move, *read_specs], sort_keys=True)
    assert "move_placement" not in serialized
    assert "apply" not in serialized.lower()
    exposed_names = {
        preview["name"],
        *(item["name"] for item in read_specs),
    }
    assert "place_asset" not in exposed_names
    assert "move_placement" not in exposed_names


def test_skill_package_loads_with_only_the_p9_tool_surface(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    shutil.copytree(SKILL, root / SKILL.name)
    tool_names = {
        "search_industrial_assets",
        "inspect_facility_entities",
        "inspect_facility_region",
        "inspect_facility_findings",
        "inspect_process_bindings",
        "inspect_facility_semantics",
        "inspect_pattern_provenance",
        "inspect_cell_layout_provenance",
        "analyze_facility_spatial",
        "analyze_facility_fit",
        "preview_facility_move",
        "build_facility_layout_preview",
        "generate_full_factory_draft",
        "generate_facility_planning_prototype_draft",
        "amend_facility_program_resource_batch_draft",
        "observe_navigation_context",
        "compile_navigation_snapshot",
        "plan_actor_journey",
        "validate_actor_journey",
        "compare_journey_alternatives",
        "propose_navigation_intent",
        "build_activity_scenario",
    }
    registry = SkillRegistry.from_roots(
        [root],
        workflow_ids={"facility-layout-generation"},
        known_agents={"sage"},
        known_modes={"training", "facility_layout"},
        known_tools_by_agent={"sage": tool_names},
    )
    package = registry.get("generate-facility-layout")
    assert set(package.manifest.allowed_tools) == tool_names
    assert package.manifest.side_effects == ()
    assert package.contract is not None
    assert package.contract.side_effect_default == "prohibited"
    assert package.contract.explicit_request_tools == (
        "preview_facility_move",
        "build_facility_layout_preview",
        "generate_full_factory_draft",
        "generate_facility_planning_prototype_draft",
        "amend_facility_program_resource_batch_draft",
        "propose_navigation_intent",
        "build_activity_scenario",
    )
    body = package.body.lower()
    for phrase in (
        "asset definition",
        "position",
        "utility networks",
        "process map",
        "preview is not",
        "canonical receipt",
    ):
        assert phrase in body
