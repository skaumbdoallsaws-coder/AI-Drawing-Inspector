"""G5 manufacturing-cell comparison and deterministic draft composition."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.asset_placement import (
    compile_asset_placement_program,
)
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.cell_composition import (
    FacilityCellCompositionError,
    compile_cell_composition_program,
    parse_cell_composition_turn,
    validate_cell_composition_result,
)
from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)
from ai_inspector.facility_layout.semantic_model import (
    CELL_FEASIBILITY_STRATEGIES,
)


REVISION = "a" * 64


def _catalog() -> list[dict]:
    definition = {
        "schemaVersion": 1,
        "documentKind": "industrial_asset_definition",
        "assetId": "asset-g5-station",
        "assetDefinitionRevision": REVISION,
        "displayName": "G5 Assembly Station",
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


def _layout(*, placements: int = 4) -> dict:
    layout = create_layout_document(
        layout_id="fl-g5",
        display_name="G5 Facility",
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
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "G5 Facility",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    departments = compile_g1_department_operations(
        layout,
        {"count": 1, "labels": ["Assembly Cell"], "arrangement": "rows"},
    )
    layout = apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    if not placements:
        return layout
    assets = compile_asset_placement_program(
        layout,
        [{
            "asset_id": "asset-g5-station",
            "asset_definition_revision": REVISION,
            "quantity": placements,
            "target_area": "Assembly Cell",
            "orientation_mode": "auto",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
            "preserve_hierarchy": True,
            "execution_mode": "authorized_draft_run",
        }],
        _catalog(),
    )
    return apply_facility_layout_operations(
        layout,
        assets["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _request(**changes) -> dict:
    value = {
        "target_area": "Assembly Cell",
        "candidate_strategies": ["line", "l", "u"],
        "selected_strategy": None,
        "objective": "shortest_travel",
        "preferred_gap_meters": 1.0,
        "invert_u": False,
        "process_sequence_placement_ids": [],
        "preserve_departments": True,
        "preserve_routes": True,
        "preserve_markings": True,
        "preserve_locked_and_manual": True,
        "execution_mode": "authorized_draft_run",
    }
    value.update(changes)
    return value


def test_parser_compares_without_mutating_and_builds_only_on_request() -> None:
    layout = _layout()
    before = deepcopy(layout)
    compared = parse_cell_composition_turn(
        "Compare line, L, and U layouts in Assembly Cell for shortest travel "
        "with 1 m spacing.",
        layout,
        _catalog(),
    )
    assert compared["kind"] == "read_only"
    assert compared["analysis"]["selectedStrategy"] in {"line", "l", "u"}
    assert layout == before

    built = parse_cell_composition_turn(
        "Arrange Assembly Cell using the shortest feasible of line, L, and U "
        "with 1 m spacing.",
        layout,
        _catalog(),
    )
    assert built["kind"] == "build"
    assert built["request"]["objective"] == "shortest_travel"
    assert built["request"]["selectedStrategy"] is None

    converted = parse_cell_composition_turn(
        "Convert Assembly Cell to an L-shaped layout for minimum movement with "
        "1 m spacing.",
        layout,
        _catalog(),
    )
    assert converted["kind"] == "build"
    assert converted["request"]["selectedStrategy"] == "l"


@pytest.mark.parametrize(
    "prompt",
    [
        (
            "Create a new 120 m by 90 m facility with Assembly and Shipping. "
            "Arrange them in two rows."
        ),
        "Divide Assembly Cell into two equal areas named Build and Test.",
        "Place two workbenches in Assembly Cell.",
    ],
)
def test_g5_parser_yields_to_the_owning_facility_gate(prompt: str) -> None:
    assert parse_cell_composition_turn(
        prompt,
        _layout(),
        _catalog(),
    ) == {"kind": "not_applicable"}


def test_compiler_applies_only_a_ranked_feasible_registered_strategy() -> None:
    layout = _layout()
    compiled = compile_cell_composition_program(
        layout, _request(), _catalog()
    )
    assert compiled["expectedSummary"]["selectedStrategy"] in {
        "line", "l", "u"
    }
    assert compiled["expectedSummary"]["selectedStrategyLabel"]
    assert compiled["plannedInstanceCount"] == 4
    assert compiled["selectedCommandIds"] == [
        "cell-layout", "create-cell-group"
    ]
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_cell_composition_result(
        result,
        compiled["expectedSummary"],
        _catalog(),
        base_layout=layout,
    )
    assert validation["status"] == "valid"
    target = next(zone for zone in result["zones"] if zone["label"] == "Assembly Cell")
    assert target["extensions"]["cellGroup"]["groupKind"] == "manufacturing_cell"
    assert target["extensions"]["layoutProvenance"]["command"] == "cell_layout"
    assert target["extensions"]["layoutProvenance"]["authoredStrategy"] == (
        compiled["expectedSummary"]["selectedStrategy"]
    )
    assert all(
        placement["metadata"]["layoutProvenance"]["command"] == "cell_layout"
        for placement in result["placements"]
    )


def test_registered_cell_strategy_translates_away_from_protected_route() -> None:
    layout = _layout()
    target_zone_id = layout["zones"][0]["zoneId"]
    layout = apply_facility_layout_operations(
        layout,
        [{
            "op": "add_aisle",
            "routeId": "rt-protected-centerline",
            "aisle": {
                "label": "Protected material aisle",
                "aisleKind": "material",
                "direction": "two_way",
                "corridorWidth": 6.0,
                "centerline": [
                    {"x": 0.0, "y": 0.0, "z": 45.0},
                    {"x": 120.0, "y": 0.0, "z": 45.0},
                ],
                "color": "#d9a514",
                "clearanceEvidenceStatus": "unverified",
                "sourceZoneId": target_zone_id,
                "targetZoneId": target_zone_id,
                "viaZoneIds": [],
                "areaAccounting": "overlay",
                "widthAuthority": "user_authored",
            },
        }],
        base_revision=layout_revision(layout),
    )["document"]

    compiled = compile_cell_composition_program(
        layout,
        _request(objective="smallest_envelope"),
        _catalog(),
    )
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_cell_composition_result(
        result,
        compiled["expectedSummary"],
        _catalog(),
        base_layout=layout,
    )

    assert validation["status"] == "valid"
    assert result["routes"] == layout["routes"]
    assert all(
        abs(float(item["transform"]["position"]["z"]) - 45.0) > 4.0
        for item in result["placements"]
    )


def test_all_ten_registered_strategies_can_be_compared_by_g5() -> None:
    compiled = compile_cell_composition_program(
        _layout(),
        _request(candidate_strategies=list(CELL_FEASIBILITY_STRATEGIES)),
        _catalog(),
    )
    summary = compiled["expectedSummary"]
    assert summary["selectedStrategy"] in CELL_FEASIBILITY_STRATEGIES
    assert len(summary["candidateStrategies"]) == 10


def test_explicit_strategy_and_spacing_are_retained_as_provenance() -> None:
    compiled = compile_cell_composition_program(
        _layout(),
        _request(
            candidate_strategies=["u"],
            selected_strategy="u",
            preferred_gap_meters=1.25,
            invert_u=True,
        ),
        _catalog(),
    )
    assert compiled["expectedSummary"]["selectedStrategy"] == "u"
    assert compiled["expectedSummary"]["selectedStrategyLabel"] == (
        "U-shaped cell"
    )
    assert compiled["expectedSummary"]["preferredGapMeters"] == 1.25
    assert compiled["expectedSummary"]["preferredGapAuthority"] == "user_authored"


def test_missing_spacing_never_becomes_an_authored_clearance() -> None:
    compiled = compile_cell_composition_program(
        _layout(),
        _request(preferred_gap_meters=None),
        _catalog(),
    )
    summary = compiled["expectedSummary"]
    assert summary["preferredGapMeters"] == 0
    assert summary["preferredGapAuthority"] == "not_supplied"
    assert summary["clearanceEvidenceComplete"] is False
    assert "no_preferred_gap_supplied_physical_non_overlap_only" in compiled[
        "assumptions"
    ]


def test_fixed_resources_fail_closed_without_moving() -> None:
    layout = _layout()
    layout["placements"][0]["positionMode"] = "locked"
    before = deepcopy(layout)
    result = parse_cell_composition_turn(
        "Arrange Assembly Cell as a U-shaped cell for shortest travel with "
        "1 m spacing.",
        layout,
        _catalog(),
    )
    assert result["kind"] == "ask"
    assert result["code"] == "facility_cell_fixed_placements_require_bounded_reflow"
    assert layout == before


@pytest.mark.parametrize(
    "prompt,code",
    [
        (
            "Arrange Assembly Cell at x=20 z=30 as a line cell.",
            "facility_cell_coordinate_ownership",
        ),
        (
            "Is the Assembly Cell safe and OSHA compliant?",
            "facility_cell_unsupported_engineering_claim",
        ),
        (
            "What throughput capacity does the Assembly Cell have?",
            "facility_cell_unsupported_engineering_claim",
        ),
    ],
)
def test_authority_and_coordinate_claims_refuse_deterministically(
    prompt: str, code: str
) -> None:
    result = parse_cell_composition_turn(prompt, _layout(), _catalog())
    assert result["kind"] == "refuse"
    assert result["code"] == code


def test_cell_requires_existing_exact_resources() -> None:
    result = parse_cell_composition_turn(
        "Create an assembly cell in Assembly Cell using the best feasible layout.",
        _layout(placements=0),
        _catalog(),
    )
    assert result["kind"] == "ask"
    assert result["code"] == "facility_cell_resources_required"


def test_unregistered_or_uncompared_strategy_is_rejected() -> None:
    with pytest.raises(FacilityCellCompositionError) as error:
        compile_cell_composition_program(
            _layout(),
            _request(
                candidate_strategies=["line"],
                selected_strategy="u",
            ),
            _catalog(),
        )
    assert error.value.code == "facility_cell_selected_strategy_not_compared"
