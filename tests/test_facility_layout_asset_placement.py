from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.asset_placement import (
    FacilityAssetPlacementError,
    compile_asset_placement_program,
    parse_asset_placement_turn,
    validate_asset_placement_result,
)
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)
from ai_inspector.facility_layout.subdivisions import (
    compile_department_subdivision_program,
    parse_subdivision_turn,
)


REV_MACHINE = "a" * 64
REV_RACK = "b" * 64


def _asset(
    asset_id: str,
    revision: str,
    display_name: str,
    width: float,
    depth: float,
    *,
    clearance: bool = False,
    front: str | None = None,
) -> dict:
    definition = {
        "schemaVersion": 1,
        "documentKind": "industrial_asset_definition",
        "assetId": asset_id,
        "displayName": display_name,
        "category": "Machines" if "machine" in display_name.lower() else "Storage",
        "geometry": {
            "aabb": {
                "minimum": {"x": -width / 2, "y": 0, "z": -depth / 2},
                "maximum": {"x": width / 2, "y": 2, "z": depth / 2},
            },
            "footprintPolygons": [[
                {"x": -width / 2, "z": -depth / 2},
                {"x": width / 2, "z": -depth / 2},
                {"x": width / 2, "z": depth / 2},
                {"x": -width / 2, "z": depth / 2},
            ]],
            "heightInterval": {"minimumY": 0, "maximumY": 2},
        },
        "clearances": [],
        "connectors": [],
        "readiness": {
            "visualReady": {"value": True, "blockers": []},
            "placementReady": {"value": True, "blockers": []},
            "planningReady": {
                "value": clearance,
                "blockers": [] if clearance else ["clearance_evidence_missing"],
            },
        },
    }
    if clearance:
        definition["clearances"] = [{
            "clearanceId": f"clearance-{asset_id}-service",
            "clearanceKind": "service",
            "enforcement": "hard",
            "evidence": ["ev-service"],
            "evidenceStatus": "authored",
            "geometry": {
                "shape": "rectangle",
                "minimum": {"x": -width / 2 - 0.5, "z": -depth / 2 - 0.5},
                "maximum": {"x": width / 2 + 0.5, "z": depth / 2 + 0.5},
            },
        }]
    if front:
        definition["facilitySemantics"] = {
            "functionalSides": {
                "front": {"side": front, "evidenceStatus": "authored"}
            },
            "evidenceStatus": "authored",
        }
    return {
        "assetId": asset_id,
        "assetDefinitionRevision": revision,
        "displayName": display_name,
        "category": definition["category"],
        "previewPlanningEligible": True,
        "definition": definition,
    }


def _catalog(*, clearance: bool = False, front: str | None = None) -> list[dict]:
    return [
        _asset(
            "asset-cnc-mill",
            REV_MACHINE,
            "CNC Milling Machine",
            3,
            4,
            clearance=clearance,
            front=front,
        ),
        _asset(
            "asset-pallet-rack",
            REV_RACK,
            "Pallet Rack",
            4,
            1,
        ),
        _asset(
            "asset-rack-narrow",
            "c" * 64,
            "Narrow Pallet Rack",
            2,
            1,
        ),
    ]


def _layout() -> dict:
    layout = create_layout_document(
        layout_id="fl-g4",
        display_name="G4 Facility",
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
            "shellRevision": "d" * 64,
            "coordinateFrameFingerprint": "e" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-a",
            "policySetRevision": "f" * 64,
        },
        created_at="2026-08-28T00:00:00Z",
    )
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 80,
            "depth": 60,
            "sourceUnit": "m",
            "displayName": "G4 Facility",
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
            "count": 2,
            "labels": ["Machining", "Assembly"],
            "arrangement": "rows",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    subdivision = parse_subdivision_turn(
        "Divide Assembly into two child areas named Mechanical Build and Test.",
        layout,
    )["request"]
    compiled = compile_department_subdivision_program(layout, [subdivision])
    return apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _request(**changes) -> dict:
    value = {
        "asset_id": "asset-cnc-mill",
        "asset_definition_revision": REV_MACHINE,
        "quantity": 2,
        "target_area": "Mechanical Build",
        "orientation_mode": "long_side_east_west",
        "facing_direction": None,
        "resource_role": "production",
        "access_requirement": "physical_only",
        "preserve_hierarchy": True,
        "execution_mode": "authorized_draft_run",
    }
    value.update(changes)
    return value


def test_parser_resolves_exact_catalog_asset_nested_target_and_orientation() -> None:
    result = parse_asset_placement_turn(
        "Place two CNC Milling Machines in Mechanical Build with their long "
        "side east-west for production.",
        _layout(),
        _catalog(),
    )
    assert result["kind"] == "build"
    request = result["request"]
    assert request["assetId"] == "asset-cnc-mill"
    assert request["assetDefinitionRevision"] == REV_MACHINE
    assert request["quantity"] == 2
    assert request["targetArea"] == "Mechanical Build"
    assert request["orientationMode"] == "long_side_east_west"
    assert request["resourceRole"] == "production"


def test_parser_fails_closed_for_ambiguous_asset_geometry_and_authority() -> None:
    layout = _layout()
    ambiguous = parse_asset_placement_turn(
        "Place two pallet racks in Mechanical Build.",
        layout,
        _catalog(),
    )
    # The exact generic catalog name wins over the longer narrow variant.
    assert ambiguous["kind"] == "build"
    assert ambiguous["request"]["assetId"] == "asset-pallet-rack"

    unclear = parse_asset_placement_turn(
        "Place two racks in Mechanical Build.", layout, _catalog()
    )
    assert unclear["kind"] == "ask"
    assert unclear["code"] == "facility_asset_selection_ambiguous"

    coordinates = parse_asset_placement_turn(
        "Place two CNC Milling Machines at x=20 z=10 in Mechanical Build.",
        layout,
        _catalog(),
    )
    assert coordinates["kind"] == "refuse"
    assert coordinates["code"] == "facility_asset_coordinate_ownership"

    compliance = parse_asset_placement_turn(
        "Place two CNC Milling Machines in Mechanical Build with whatever OSHA "
        "clearance applies.",
        layout,
        _catalog(),
    )
    assert compliance["kind"] == "refuse"
    assert compliance["code"] == "facility_asset_unsupported_compliance_claim"


@pytest.mark.parametrize(
    "message",
    [
        "Add some aisles.",
        "Add whatever fire aisles the code requires.",
        "Add a 3 m one-way forklift lane from North West to South East.",
        "Place a 5 m material route between Machining and Assembly.",
        "Add a pedestrian corridor through Assembly.",
        "Add two floor markings in Assembly.",
    ],
)
def test_parser_leaves_non_asset_facility_entities_to_their_owner(message) -> None:
    assert (
        parse_asset_placement_turn(message, _layout(), _catalog())["kind"]
        == "not_applicable"
    )


def test_front_facing_requires_registered_functional_side() -> None:
    missing = parse_asset_placement_turn(
        "Place one CNC Milling Machine in Mechanical Build facing north.",
        _layout(),
        _catalog(),
    )
    assert missing["kind"] == "ask"
    assert missing["code"] == "facility_asset_front_orientation_unavailable"

    supported = parse_asset_placement_turn(
        "Place one CNC Milling Machine in Mechanical Build facing east.",
        _layout(),
        _catalog(front="north"),
    )
    assert supported["kind"] == "build"
    assert supported["request"]["orientationMode"] == "front_facing"


def test_compiler_places_complete_set_without_mutating_hierarchy() -> None:
    layout = _layout()
    before = deepcopy(layout)
    compiled = compile_asset_placement_program(
        layout, [_request()], _catalog()
    )
    assert layout == before
    assert len(compiled["operations"]) == 2
    assert {item["op"] for item in compiled["operations"]} == {"place_asset"}
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    assert result["zones"] == before["zones"]
    assert result["routes"] == before["routes"]
    assert len(result["placements"]) == 2
    assert {
        item["metadata"]["orientationDegrees"]
        for item in result["placements"]
    }.issubset({90, 270})
    assert all(
        item["metadata"]["accessStatus"] == "unverified"
        for item in result["placements"]
    )
    validation = validate_asset_placement_result(
        result, compiled["expectedSummary"], _catalog()
    )
    assert validation["status"] == "valid"
    assert validation["accessUnverifiedCount"] == 2


def test_registered_access_is_required_only_when_explicitly_requested() -> None:
    with pytest.raises(FacilityAssetPlacementError) as caught:
        compile_asset_placement_program(
            _layout(),
            [_request(quantity=1, access_requirement="registered_access_required")],
            _catalog(clearance=False),
        )
    assert caught.value.code == "facility_asset_access_evidence_unavailable"

    authority = {
        "ev-service": {
            "status": "authored",
            "current": True,
            "authoritative": True,
            "blockers": [],
        }
    }
    compiled = compile_asset_placement_program(
        _layout(),
        [_request(quantity=1, access_requirement="registered_access_required")],
        _catalog(clearance=True),
        evidence_authority=authority,
    )
    assert compiled["expectedSummary"]["placements"][0]["accessStatus"] == "validated"


def test_unplaceable_complete_set_fails_without_partial_output() -> None:
    layout = _layout()
    before = deepcopy(layout)
    with pytest.raises(FacilityAssetPlacementError) as caught:
        compile_asset_placement_program(
            layout,
            [_request(quantity=50)],
            _catalog(),
        )
    assert caught.value.code == "facility_asset_set_unplaceable"
    assert layout == before


def test_exact_asset_revision_must_be_currently_available() -> None:
    with pytest.raises(FacilityAssetPlacementError) as caught:
        compile_asset_placement_program(
            _layout(),
            [_request(asset_definition_revision="9" * 64)],
            _catalog(),
        )
    assert caught.value.code == "facility_asset_revision_unavailable"
