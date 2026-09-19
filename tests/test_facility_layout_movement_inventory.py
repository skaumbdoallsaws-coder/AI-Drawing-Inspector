"""Movement inventory: real-actor enumeration and candidate refusal."""
from __future__ import annotations

import json
from pathlib import Path

from ai_inspector.facility_layout.movement_inventory import (
    NEEDS_AUTHORED_STOPS,
    NEEDS_PUBLISHED_VEHICLE_PROFILE,
    build_movement_report,
    contained_area_zone_labels,
    enumerate_area,
    evaluate_candidates,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = (
    ROOT
    / ".runtime/facility-layout/layouts/local/site-local/layouts"
    / "fl-reference-manual-20260812.json"
)

AREA = (
    ["Inspection + Packing + Finished goods", "Inspection", "Packaging", "Finished Goods"]
    + [f"Inpection Station Q0{index}" for index in (1, 2, 3, 4)]
    + [f"Packaging Station P0{index}" for index in (1, 2, 3, 4)]
    + [f"Finished Goods Rack Row R0{index}" for index in (1, 2, 3, 4)]
)


def _layout() -> dict:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def _square(zone_id: str, label: str, x0, z0, x1, z1, anchors=()) -> dict:
    return {
        "zoneId": zone_id,
        "label": label,
        "zoneType": "workcell",
        "anchors": list(anchors),
        "boundary": [
            {"x": x0, "z": z0},
            {"x": x1, "z": z0},
            {"x": x1, "z": z1},
            {"x": x0, "z": z1},
        ],
    }


def _placement(placement_id: str, asset_id: str, x, z) -> dict:
    return {
        "placementId": placement_id,
        "assetId": asset_id,
        "assetDefinitionRevision": "a" * 64,
        "snapRelationship": None,
        "transform": {"position": {"x": x, "y": 0, "z": z}},
    }


# ------------------------------------------------------- reference inventory --
def test_enumerates_the_real_actors_without_inventing_any() -> None:
    inventory = enumerate_area(_layout(), AREA)

    operators = [a for a in inventory["actors"] if a["actorKind"] == "operator"]
    vehicles = [a for a in inventory["actors"] if a["actorKind"] == "vehicle"]

    assert len(operators) == 8, "4 inspection + 4 packaging operators"
    assert len(vehicles) == 2, "1 forklift + 1 pallet truck"
    assert len(inventory["zones"]) == 16

    layout_ids = {p["placementId"] for p in _layout()["placements"]}
    for actor in inventory["actors"]:
        assert actor["placementId"] in layout_ids, "no actor may be invented"


def test_reference_area_descendants_are_derived_from_the_parent_boundary() -> None:
    labels = contained_area_zone_labels(
        _layout(),
        ["Inspection + Packing + Finished goods"],
    )

    assert labels == sorted(AREA)


def test_reference_area_has_no_authored_routing_evidence() -> None:
    inventory = enumerate_area(_layout(), AREA)

    assert inventory["authoredAnchorCount"] == 0
    assert inventory["processBindingCount"] == 0
    assert inventory["routesInArea"] == []
    assert inventory["directionalMarkingIds"] == []


def test_every_reference_candidate_refuses_with_named_authority() -> None:
    report = build_movement_report(_layout(), AREA, vehicle_profiles=[])

    assert report["availableCandidateCount"] == 0
    assert report["unavailableCandidateCount"] == 5
    for candidate in report["candidates"]:
        assert candidate["status"] == "unavailable"
        assert candidate["orderedStopIds"] == []
        assert candidate["missingAuthority"], "a refusal must name what is missing"


def test_operator_candidates_return_needs_authored_stops() -> None:
    report = build_movement_report(_layout(), AREA, vehicle_profiles=[])
    by_id = {item["candidateId"]: item for item in report["candidates"]}

    assert by_id["inspection_operator_journey"]["code"] == NEEDS_AUTHORED_STOPS
    assert by_id["packaging_operator_journey"]["code"] == NEEDS_AUTHORED_STOPS


def test_draft_vehicle_profile_does_not_qualify() -> None:
    draft = {
        "documentKind": "vehicle_profile",
        "vehicleProfileId": "prototype-reference-forklift-v1",
        "status": "draft",
        "assetDefinitionRef": {"assetId": "asset-forklift"},
    }

    report = build_movement_report(_layout(), AREA, vehicle_profiles=[draft])
    vehicle = next(
        item
        for item in report["candidates"]
        if item["candidateId"] == "finished_goods_vehicle_journey"
    )

    assert vehicle["status"] == "unavailable"
    assert vehicle["code"] == NEEDS_PUBLISHED_VEHICLE_PROFILE


def test_handoffs_are_topology_only() -> None:
    report = build_movement_report(_layout(), AREA, vehicle_profiles=[])
    handoffs = [item for item in report["candidates"] if "handoff" in item["candidateId"]]

    assert len(handoffs) == 2
    for handoff in handoffs:
        assert handoff["topologyOnly"] is True


def test_report_carries_the_prototype_qualification() -> None:
    report = build_movement_report(_layout(), AREA, vehicle_profiles=[])

    for banned in ("safety", "throughput", "capacity", "scheduling", "ergonomics"):
        assert banned in report["qualification"], "qualification must disclaim it"
    assert report["qualification"].startswith("Prototype candidate movement")


# -------------------------------------------------- the gate opens correctly --
def test_authored_anchors_and_routes_make_an_operator_candidate_available() -> None:
    """Prove the evaluator is a gate, not a blanket refusal."""
    anchor = {
        "anchorId": "za-q01-stand",
        "anchorKind": "operator",
        "position": {"x": 5.0, "y": 0.0, "z": 5.0},
        "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
        "allowedRouteKinds": ["operator"],
        "evidence": [],
    }
    layout = {
        "zones": [_square("zn-q01", "Inpection Station Q01", 0, 0, 10, 10, [anchor])],
        "placements": [_placement("pl-op-1", "asset-operator", 5.0, 5.0)],
        "routes": [
            {
                "routeId": "rt-walk",
                "routeKind": "operator",
                "centerline": [
                    {"x": 1.0, "y": 0.0, "z": 5.0},
                    {"x": 9.0, "y": 0.0, "z": 5.0},
                ],
                "extensions": {"facilityAisle": {"direction": "two_way"}},
            }
        ],
        "floorMarkings": [],
        "processBindings": [{"bindingId": "pb-1"}],
    }

    inventory = enumerate_area(layout, ["Inpection Station Q01"])
    assert inventory["authoredAnchorCount"] == 1
    assert len(inventory["routesInArea"]) == 1

    candidates = evaluate_candidates(inventory, vehicle_profiles=[])
    inspection = next(
        item for item in candidates if item["candidateId"] == "inspection_operator_journey"
    )

    assert inspection["status"] == "available"
    assert inspection["code"] is None
    assert inspection["actorPlacementIds"] == ["pl-op-1"]


def test_published_profile_and_one_way_lane_clear_the_vehicle_gate() -> None:
    layout = {
        "zones": [_square("zn-fg", "Finished Goods", 0, 0, 20, 20)],
        "placements": [_placement("pl-fork-1", "asset-forklift", 10.0, 10.0)],
        "routes": [
            {
                "routeId": "rt-lane",
                "routeKind": "forklift",
                "centerline": [
                    {"x": 1.0, "y": 0.0, "z": 10.0},
                    {"x": 19.0, "y": 0.0, "z": 10.0},
                ],
                "extensions": {"facilityAisle": {"direction": "one_way"}},
            }
        ],
        "floorMarkings": [],
        "processBindings": [],
    }
    published = {
        "documentKind": "vehicle_profile",
        "vehicleProfileId": "published-forklift-v1",
        "status": "published",
        "assetDefinitionRef": {"assetId": "asset-forklift"},
    }

    inventory = enumerate_area(layout, ["Finished Goods"])
    vehicle = next(
        item
        for item in evaluate_candidates(inventory, vehicle_profiles=[published])
        if item["candidateId"] == "finished_goods_vehicle_journey"
    )

    assert vehicle["status"] == "available"
    assert vehicle["actorPlacementIds"] == ["pl-fork-1"]


def test_placement_is_assigned_to_the_smallest_containing_zone() -> None:
    layout = {
        "zones": [
            _square("zn-outer", "Inspection", 0, 0, 100, 100),
            _square("zn-inner", "Inpection Station Q01", 40, 40, 60, 60),
        ],
        "placements": [_placement("pl-op-1", "asset-operator", 50.0, 50.0)],
        "routes": [],
        "floorMarkings": [],
        "processBindings": [],
    }

    inventory = enumerate_area(layout, ["Inspection", "Inpection Station Q01"])

    assert inventory["actors"][0]["zoneId"] == "zn-inner"
