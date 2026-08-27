"""KF4 deterministic feasibility and strategy-surface parity."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from ai_inspector.facility_layout.knowledge_foundation import (
    canonical_cell_recipe_registry,
    canonical_cell_strategy_registry,
    canonical_facility_command_registry,
)
from ai_inspector.facility_layout.observation import (
    facility_layout_read_tool_specs,
)
from ai_inspector.facility_layout.semantic_model import (
    CELL_FEASIBILITY_STRATEGIES,
    analyze_facility_cell_alternatives,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "cell_intelligence"
    / "kf4-strategy-fixtures.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))


def _square(cx: float, cz: float, radius: float) -> list[dict[str, float]]:
    return [
        {"x": cx - radius, "z": cz - radius},
        {"x": cx + radius, "z": cz - radius},
        {"x": cx + radius, "z": cz + radius},
        {"x": cx - radius, "z": cz + radius},
    ]


def _state(
    *,
    width: float,
    depth: float,
    clearance: str = "authored",
) -> dict:
    placements = []
    for index in range(6):
        x_value = 1.5 + (index % 3) * 2.0
        z_value = 1.5 + (index // 3) * 2.0
        placement = {
            "placementId": f"pl-kf4-{index + 1}",
            "assetId": "asset-kf4-station",
            "assetDefinitionRevision": "a" * 64,
            "displayName": f"Station {index + 1}",
            "category": "Workstations",
            "positionMode": "auto",
            "transform": {
                "position": {"x": x_value, "y": 0.0, "z": z_value},
                "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                "scale": 1.0,
            },
            "zoneIds": ["cell-kf4"],
            "physicalGeometry": [{
                "recordId": f"physical:pl-kf4-{index + 1}",
                "polygon": _square(x_value, z_value, 0.5),
                "minimumY": 0.0,
                "maximumY": 1.0,
                "authoritative": True,
            }],
        }
        if clearance != "missing":
            placement["clearanceGeometry"] = [{
                "recordId": f"clearance:pl-kf4-{index + 1}",
                "polygon": _square(
                    x_value,
                    z_value,
                    0.7 if clearance == "authored" else 20.0,
                ),
                "minimumY": 0.0,
                "maximumY": 1.0,
                "authoritative": True,
            }]
        placements.append(placement)
    return {
        "identity": {
            "layoutId": "layout-kf4",
            "displayName": "KF4 cell fixture",
            "revision": "b" * 64,
        },
        "zones": [{
            "zoneId": "cell-kf4",
            "label": "KF4 Manufacturing Cell",
            "zoneType": "workcell",
            "floorElevation": 0.0,
            "boundary": [
                {"x": 0.0, "z": 0.0},
                {"x": width, "z": 0.0},
                {"x": width, "z": depth},
                {"x": 0.0, "z": depth},
            ],
            "extensions": {
                "cellGroup": {
                    "groupKind": "manufacturing_cell",
                    "functionalInterfaces": {
                        "loading": {
                            "side": "west",
                            "evidenceStatus": "authored",
                        },
                        "service": {
                            "side": "north",
                            "evidenceStatus": "authored",
                        },
                    },
                },
            },
        }],
        "assets": [{
            "assetId": "asset-kf4-station",
            "assetDefinitionRevision": "a" * 64,
            "displayName": "KF4 Station",
            "category": "Workstations",
            "dimensions": {"x": 1.0, "y": 1.0, "z": 1.0},
            "planningReady": clearance == "authored",
        }],
        "placements": placements,
        "routes": [],
        "floorMarkings": [],
        "processBindings": [],
    }


def test_all_strategy_surfaces_match_the_shared_fixture() -> None:
    fixture = _fixture()
    expected = fixture["strategyIds"]
    assert list(CELL_FEASIBILITY_STRATEGIES) == expected
    assert [
        item["strategyId"] for item in canonical_cell_strategy_registry()
    ] == expected

    spatial = next(
        item
        for item in facility_layout_read_tool_specs()
        if item["name"] == "analyze_facility_spatial"
    )
    schema = spatial["input_schema"]["properties"]["cellStrategies"]
    assert schema["items"]["enum"] == expected
    assert schema["maxItems"] == len(expected)

    browser_source = (
        ROOT / "static" / "facility_layout_patterns.js"
    ).read_text(encoding="utf-8")
    for strategy in expected:
        assert f"'{strategy}'" in browser_source


def test_all_ten_strategies_produce_ranked_feasible_candidates() -> None:
    fixture = _fixture()["validCase"]
    state = _state(
        width=fixture["targetZoneWidthMeters"],
        depth=fixture["targetZoneDepthMeters"],
    )
    before = json.dumps(state, sort_keys=True)

    result = analyze_facility_cell_alternatives(
        state,
        scope_ids=["cell-kf4"],
        strategies=list(CELL_FEASIBILITY_STRATEGIES),
        preferred_gap_meters=fixture["preferredGapMeters"],
    )

    assert result["returnedCount"] == 10
    assert result["feasibleCount"] == 10
    assert result["rejectedCount"] == 0
    assert {item["strategy"] for item in result["rankedFeasibleRecords"]} == set(
        CELL_FEASIBILITY_STRATEGIES
    )
    assert all(item["geometryValid"] for item in result["records"])
    assert all(not item["blockerCodes"] for item in result["records"])
    assert all(
        item["metrics"]["minimumPhysicalGapMeters"] >= 1.0
        for item in result["records"]
    )
    assert all(
        item["metrics"]["clearanceEvidenceComplete"] is True
        and item["metrics"]["accessStatus"]
        == "authoritative_clearances_validated"
        for item in result["records"]
    )
    assert result["mutationPerformed"] is False
    assert json.dumps(state, sort_keys=True) == before


def test_all_ten_strategies_explain_infeasible_small_zone() -> None:
    fixture = _fixture()["invalidCase"]
    result = analyze_facility_cell_alternatives(
        _state(
            width=fixture["targetZoneWidthMeters"],
            depth=fixture["targetZoneDepthMeters"],
        ),
        scope_ids=["cell-kf4"],
        strategies=list(CELL_FEASIBILITY_STRATEGIES),
        preferred_gap_meters=fixture["preferredGapMeters"],
    )

    assert result["returnedCount"] == 10
    assert result["feasibleCount"] == 0
    assert result["rejectedCount"] == 10
    assert result["rankedFeasibleRecords"] == []
    assert all(item["blockerCodes"] for item in result["rejectedRecords"])
    assert all(item["geometryValid"] is False for item in result["records"])


def test_authored_clearance_envelopes_are_enforced() -> None:
    result = analyze_facility_cell_alternatives(
        _state(width=100.0, depth=100.0, clearance="conflicting"),
        scope_ids=["cell-kf4"],
        strategies=list(CELL_FEASIBILITY_STRATEGIES),
    )

    assert result["feasibleCount"] == 0
    assert all(
        "authored_clearance_conflict" in item["blockerCodes"]
        for item in result["rejectedRecords"]
    )


def test_missing_clearance_evidence_remains_visible() -> None:
    result = analyze_facility_cell_alternatives(
        _state(width=100.0, depth=100.0, clearance="missing"),
        scope_ids=["cell-kf4"],
        strategies=["line", "grid", "cluster"],
    )

    assert result["feasibleCount"] == 3
    assert all(
        item["validationStatus"]
        == "geometrically_valid_clearance_unverified"
        and item["clearanceEvidenceComplete"] is False
        and item["metrics"]["accessStatus"]
        == "clearance_evidence_incomplete"
        for item in result["rankedFeasibleRecords"]
    )


def test_locked_and_manual_members_are_preserved() -> None:
    for mode, code, field in (
        ("locked", "locked_cell_placements", "lockedPlacementIds"),
        ("manual", "manual_cell_placements", "manualPlacementIds"),
    ):
        state = _state(width=100.0, depth=100.0)
        state["placements"][0]["positionMode"] = mode
        before = deepcopy(state["placements"][0]["transform"])
        result = analyze_facility_cell_alternatives(
            state,
            scope_ids=["cell-kf4"],
            strategies=["line"],
        )
        assert result["records"] == []
        assert code in result["blockerCodes"]
        assert result[field] == ["pl-kf4-1"]
        assert state["placements"][0]["transform"] == before


def test_strategy_contracts_have_four_groups_and_implemented_feasibility() -> None:
    required_metrics = {
        "requiredWidth",
        "requiredDepth",
        "physicalFootprintArea",
        "envelopeArea",
        "minimumPhysicalGap",
        "contiguousFreeArea",
        "routeConnectivity",
        "operatorTravelProxy",
        "totalMovement",
        "accessStatus",
        "accessEvidenceCompleteness",
        "expansionReserve",
    }
    for strategy in canonical_cell_strategy_registry():
        assert strategy["spaceModel"]["serverFeasibilityStatus"] == "implemented"
        assert strategy["spaceModel"]["inventedClearanceAllowed"] is False
        assert strategy["interfaces"]["unknownInterfacesRemainUnknown"] is True
        assert strategy["accessAssumptions"][
            "lockedAndManualMembersPreserved"
        ] is True
        assert set(strategy["resultMetrics"]) == required_metrics


def test_recipes_compile_only_to_registered_commands_and_strategies() -> None:
    commands = {
        item["commandId"] for item in canonical_facility_command_registry()
    }
    strategies = set(CELL_FEASIBILITY_STRATEGIES)
    recipes = canonical_cell_recipe_registry()

    assert len(recipes) == 8
    assert all(set(item["commandIds"]) <= commands for item in recipes)
    assert all(set(item["strategyIds"]) <= strategies for item in recipes)
    assert all(item["geometryEngineBypassAllowed"] is False for item in recipes)
