"""G6 reusable-cell replication and deterministic drift contracts."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.asset_placement import (
    compile_asset_placement_program,
)
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.cell_composition import (
    compile_cell_composition_program,
)
from ai_inspector.facility_layout.cell_replication import (
    FacilityCellReplicationError,
    analyze_cell_replication_state,
    compile_cell_replication_program,
    normalize_cell_replication_request,
    parse_cell_replication_turn,
    validate_cell_replication_result,
)
from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)


REVISION = "a" * 64


def _catalog() -> list[dict]:
    definition = {
        "schemaVersion": 1,
        "documentKind": "industrial_asset_definition",
        "assetId": "asset-g6-station",
        "assetDefinitionRevision": REVISION,
        "displayName": "G6 Assembly Station",
        "category": "Workstations",
        "geometry": {
            "aabb": {
                "minimum": {"x": -1, "y": 0, "z": -1},
                "maximum": {"x": 1, "y": 2, "z": 1},
            },
            "footprintPolygons": [[
                {"x": -1, "z": -1},
                {"x": 1, "z": -1},
                {"x": 1, "z": 1},
                {"x": -1, "z": 1},
            ]],
            "heightInterval": {"minimumY": 0, "maximumY": 2},
        },
        "clearances": [],
        "connectors": [],
        "readiness": {
            "visualReady": {"value": True, "blockers": []},
            "placementReady": {"value": True, "blockers": []},
            "planningReady": {
                "value": False,
                "blockers": ["clearance_evidence_missing"],
            },
        },
    }
    return [{
        "assetId": definition["assetId"],
        "assetDefinitionRevision": REVISION,
        "displayName": definition["displayName"],
        "category": definition["category"],
        "previewPlanningEligible": True,
        "definition": definition,
    }]


def _layout() -> dict:
    layout = create_layout_document(
        layout_id="fl-g6",
        display_name="G6 Facility",
        association={"siteId": "site-a", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "origin-a",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "shell-a",
            "shellRevision": "b" * 64,
            "coordinateFrameFingerprint": "c" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-a",
            "policySetRevision": "d" * 64,
        },
        created_at="2026-08-28T00:00:00Z",
    )
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 40,
            "sourceUnit": "m",
            "displayName": "G6 Facility",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    departments = compile_g1_department_operations(
        layout,
        {
            "count": 3,
            "labels": ["Source Cell", "Replica East", "Replica West"],
            "arrangement": "rows",
            "orientation": "horizontal",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    placed = compile_asset_placement_program(
        layout,
        [{
            "asset_id": "asset-g6-station",
            "asset_definition_revision": REVISION,
            "quantity": 3,
            "target_area": "Source Cell",
            "orientation_mode": "auto",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
            "preserve_hierarchy": True,
            "execution_mode": "authorized_draft_run",
        }],
        _catalog(),
    )
    layout = apply_facility_layout_operations(
        layout,
        placed["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    composed = compile_cell_composition_program(
        layout,
        {
            "target_area": "Source Cell",
            "candidate_strategies": ["line"],
            "selected_strategy": "line",
            "objective": "shortest_travel",
            "preferred_gap_meters": 1.0,
            "invert_u": False,
            "process_sequence_placement_ids": [],
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_locked_and_manual": True,
            "execution_mode": "authorized_draft_run",
        },
        _catalog(),
    )
    return apply_facility_layout_operations(
        layout,
        composed["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _request(**changes) -> dict:
    value = {
        "source_cell": "Source Cell",
        "target_areas": ["Replica East", "Replica West"],
        "copy_current_edited_state": False,
        "preserve_departments": True,
        "preserve_routes": True,
        "preserve_markings": True,
        "preserve_source_cell": True,
        "preserve_manual_and_locked": True,
        "execution_mode": "authorized_draft_run",
    }
    value.update(changes)
    return value


def test_parser_builds_named_targets_and_inspection_is_read_only() -> None:
    layout = _layout()
    before = deepcopy(layout)
    built = parse_cell_replication_turn(
        "Replicate Source Cell into Replica East and Replica West.",
        layout,
    )
    assert built["kind"] == "build"
    assert built["request"]["targetAreas"] == [
        "Replica East",
        "Replica West",
    ]
    checked = parse_cell_replication_turn(
        "Check whether Source Cell still matches its reusable module.",
        layout,
    )
    assert checked["kind"] == "read_only"
    assert checked["analysis"]["sources"][0]["sourceStatus"] == "consistent"
    assert layout == before

    electrical = deepcopy(layout)
    source = next(zone for zone in electrical["zones"] if zone["label"] == "Source Cell")
    source["label"] = "Electrical Build"
    checked = parse_cell_replication_turn(
        "Check whether Electrical Build and its replicas still match their authored module snapshots.",
        electrical,
    )
    assert checked["kind"] == "read_only"
    assert (
        checked["analysis"]["sources"][0]["sourceCellLabel"]
        == "Electrical Build"
    )


def test_parser_does_not_hijack_generic_copy_or_drop_unknown_targets() -> None:
    layout = _layout()
    assert parse_cell_replication_turn(
        "Copy this machine beside the other one.", layout
    ) == {"kind": "not_applicable"}
    unknown = parse_cell_replication_turn(
        "Replicate Source Cell into Replica East and Unknown Bay.", layout
    )
    assert unknown["kind"] == "ask"
    assert unknown["code"] == "facility_cell_module_target_unknown"
    assert "Unknown Bay" in unknown["response"]


def test_compiler_remaps_exact_cell_into_empty_named_targets() -> None:
    layout = _layout()
    before = deepcopy(layout)
    compiled = compile_cell_replication_program(layout, _request(), _catalog())
    assert compiled["stageId"] == "repeated_modules"
    assert compiled["selectedCommandIds"] == ["duplicate", "create-cell-group"]
    summary = compiled["expectedSummary"]
    assert summary["replicaCount"] == 2
    assert summary["copiedPlacementCount"] == 6
    assert summary["authoredStrategy"] == "line"
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_cell_replication_result(
        result,
        summary,
        _catalog(),
        base_layout=layout,
    )
    assert validation["status"] == "valid"
    assert validation["departmentGeometryPreserved"] is True
    assert validation["sourceCellPreserved"] is True
    source_ids = set(summary["sourceMemberPlacementIds"])
    after = {item["placementId"]: item for item in result["placements"]}
    prior = {item["placementId"]: item for item in before["placements"]}
    assert all(after[item] == prior[item] for item in source_ids)
    for replica in summary["replicas"]:
        id_map = {
            item["sourcePlacementId"]: item["copiedPlacementId"]
            for item in replica["placementIdMap"]
        }
        assert set(id_map) == source_ids
        assert len(set(id_map.values())) == len(source_ids)
        for copied_id in id_map.values():
            copied = after[copied_id]
            assert copied["metadata"]["generatedBy"] == (
                "facility_cell_replication_g6"
            )
            assert copied["metadata"]["targetZoneId"] == (
                replica["targetZoneId"]
            )
            assert copied["metadata"]["layoutProvenance"]["command"] == (
                "duplicate"
            )
    state = analyze_cell_replication_state(result, "Source Cell")
    assert state["sources"][0]["replicaCount"] == 2
    assert {
        item["status"] for item in state["sources"][0]["replicas"]
    } == {"consistent"}


def test_replica_relationships_are_remapped_to_copied_members() -> None:
    layout = _layout()
    source_ids = [item["placementId"] for item in layout["placements"]]
    layout = apply_facility_layout_operations(
        layout,
        [{
            "op": "set_snap_relationship",
            "placementId": source_ids[1],
            "snapRelationship": {
                "kind": "surface",
                "supportPlacementId": source_ids[0],
                "surfaceId": "top",
            },
        }],
        base_revision=layout_revision(layout),
    )["document"]
    compiled = compile_cell_replication_program(
        layout,
        _request(target_areas=["Replica East"]),
        _catalog(),
    )
    copied = compiled["expectedSummary"]["replicas"][0]
    id_map = {
        item["sourcePlacementId"]: item["copiedPlacementId"]
        for item in copied["placementIdMap"]
    }
    record = next(
        item
        for item in copied["copiedPlacements"]
        if item["sourcePlacementId"] == source_ids[1]
    )
    assert record["snapRelationship"]["supportPlacementId"] == id_map[
        source_ids[0]
    ]


def test_diverged_source_requires_explicit_current_state_authority() -> None:
    layout = _layout()
    source_id = layout["placements"][0]["placementId"]
    position = deepcopy(layout["placements"][0]["transform"]["position"])
    position["x"] += 0.25
    edited = apply_facility_layout_operations(
        layout,
        [{
            "op": "move_placement",
            "placementId": source_id,
            "position": position,
            "movementKind": "user",
        }],
        base_revision=layout_revision(layout),
    )["document"]
    state = analyze_cell_replication_state(edited, "Source Cell")
    assert state["sources"][0]["sourceStatus"] == "modified"
    with pytest.raises(FacilityCellReplicationError) as exc:
        normalize_cell_replication_request(_request(), edited)
    assert exc.value.code == "facility_cell_module_source_diverged"
    normalized = normalize_cell_replication_request(
        _request(copy_current_edited_state=True), edited
    )
    assert normalized["sourceStateAuthority"] == (
        "explicit_current_edited_state"
    )


def test_manual_replica_edit_is_reported_without_overwriting_it() -> None:
    layout = _layout()
    compiled = compile_cell_replication_program(
        layout,
        _request(target_areas=["Replica East"]),
        _catalog(),
    )
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    copied_id = compiled["expectedSummary"]["replicas"][0][
        "copiedPlacements"
    ][0]["copiedPlacementId"]
    copied = next(item for item in result["placements"] if item["placementId"] == copied_id)
    position = deepcopy(copied["transform"]["position"])
    position["z"] += 0.5
    edited = apply_facility_layout_operations(
        result,
        [{
            "op": "move_placement",
            "placementId": copied_id,
            "position": position,
            "movementKind": "user",
        }],
        base_revision=layout_revision(result),
    )["document"]
    before = deepcopy(edited)
    state = analyze_cell_replication_state(edited, "Source Cell")
    replica = state["sources"][0]["replicas"][0]
    assert replica["status"] == "modified"
    assert replica["modifiedPlacementIds"] == [copied_id]
    assert edited == before


def test_occupied_target_and_external_relationship_fail_closed() -> None:
    layout = _layout()
    occupied = deepcopy(layout)
    occupied["placements"][0]["metadata"]["targetZoneId"] = next(
        item["zoneId"] for item in occupied["zones"] if item["label"] == "Replica East"
    )
    with pytest.raises(FacilityCellReplicationError) as exc:
        normalize_cell_replication_request(
            _request(target_areas=["Replica East"]), occupied
        )
    assert exc.value.code == "facility_cell_module_target_occupied"

    source_ids = [item["placementId"] for item in layout["placements"]]
    external = deepcopy(layout)
    external["placements"][1]["snapRelationship"] = {
        "kind": "surface",
        "supportPlacementId": "pl-external-support",
        "surfaceId": "top",
    }
    with pytest.raises(FacilityCellReplicationError) as exc:
        compile_cell_replication_program(
            external,
            _request(target_areas=["Replica East"]),
            _catalog(),
        )
    assert source_ids
    assert exc.value.code == "facility_cell_module_external_dependency"


@pytest.mark.parametrize(
    "prompt,code",
    [
        (
            "Copy Source Cell to Replica East at x=80 z=20.",
            "facility_cell_module_coordinate_ownership",
        ),
        (
            "Are copies of Source Cell safe and OSHA compliant?",
            "facility_cell_module_unsupported_engineering_claim",
        ),
        (
            "Replicate Source Cell with optimal throughput into Replica East.",
            "facility_cell_module_unsupported_engineering_claim",
        ),
    ],
)
def test_coordinates_and_unsupported_claims_refuse_deterministically(
    prompt: str, code: str
) -> None:
    result = parse_cell_replication_turn(prompt, _layout())
    assert result["kind"] == "refuse"
    assert result["code"] == code


def test_closed_contract_rejects_geometry_fields() -> None:
    with pytest.raises(FacilityCellReplicationError) as exc:
        normalize_cell_replication_request(
            {**_request(), "translation": {"x": 10, "z": 0}},
            _layout(),
        )
    assert exc.value.code == "facility_cell_module_model_geometry_refused"
