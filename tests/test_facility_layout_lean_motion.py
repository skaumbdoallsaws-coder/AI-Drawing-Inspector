from __future__ import annotations

from copy import deepcopy

from ai_inspector.facility_layout.lean_motion import (
    FACILITY_LEAN_MOTION_QUALIFICATION,
    FACILITY_LEAN_MOTION_SCHEMA_VERSION,
    build_facility_lean_motion,
    derive_facility_lean_motion_blueprint,
)


def _boundary(x0: float, z0: float, x1: float, z1: float) -> list[dict]:
    return [
        {"x": x0, "z": z0},
        {"x": x1, "z": z0},
        {"x": x1, "z": z1},
        {"x": x0, "z": z1},
    ]


def _zone(zone_id: str, label: str, bounds: tuple[float, ...]) -> dict:
    return {
        "zoneId": zone_id,
        "label": label,
        "boundary": _boundary(*bounds),
    }


def _operator(placement_id: str, x: float, z: float) -> dict:
    return {
        "placementId": placement_id,
        "assetId": "asset-operator",
        "transform": {"position": {"x": x, "y": 0, "z": z}},
    }


def _asset(placement_id: str, asset_id: str, x: float, z: float) -> dict:
    return {
        "placementId": placement_id,
        "assetId": asset_id,
        "transform": {"position": {"x": x, "y": 0, "z": z}},
    }


def _layout() -> dict:
    return {
        "zones": [
            _zone("zone-assembly", "Assembly + Kitting", (0, 0, 30, 40)),
            _zone("zone-cell-a", "Assembly Cell A01", (2, 26, 12, 36)),
            _zone("zone-cell-b", "Assembly Cell A02", (18, 26, 28, 36)),
            _zone("zone-line-a", "Assembly Line L01", (2, 10, 12, 23)),
            _zone("zone-line-b", "Assembly Line L02", (18, 10, 28, 23)),
            _zone("zone-kit-a", "Kitting Island K01", (2, 2, 12, 8)),
            # The reference layout contains this historical spelling.
            _zone("zone-kit-b", "Knitting Island K02", (18, 2, 28, 8)),
        ],
        "placements": [
            _operator("operator-cell-a", 7, 31),
            _operator("operator-cell-b", 23, 31),
            _operator("operator-line-a-near", 7, 16),
            _operator("operator-line-a-far", 7, 12),
            _operator("operator-line-b-near", 23, 16),
            _operator("operator-line-b-far", 23, 21),
            _operator("operator-kit-a", 7, 5),
            _operator("operator-kit-b", 23, 5),
            _asset("bench-line-a-low", "asset-workbench", 7, 11),
            _asset("bench-line-a-high", "asset-workbench", 7, 21),
            _asset("bench-line-b-low", "asset-workbench", 23, 11),
            _asset("bench-line-b-high", "asset-workbench", 23, 22),
        ],
    }


def test_blueprint_is_deterministic_and_separates_people_from_material_flow():
    layout = _layout()
    before = deepcopy(layout)

    first = derive_facility_lean_motion_blueprint(layout)
    second = derive_facility_lean_motion_blueprint(layout)

    assert first == second
    assert layout == before
    assert len(first["operatorPlans"]) == 8
    assert len(first["pedestrianLinkPlans"]) == 8
    assert len(first["assistanceGatePlans"]) == 2
    assert len(first["materialHandoffs"]) == 4
    assert len(first["fifoPoints"]) == 8

    by_zone = {}
    for plan in first["operatorPlans"]:
        by_zone.setdefault(plan["zoneId"], []).append(plan)
        assert len(plan["waypoints"]) == (
            5 if plan["segmentCount"] > 1 else 7
        )
        assert plan["waypoints"][0] == plan["anchor"]
        for index, start in enumerate(plan["waypoints"]):
            end = plan["waypoints"][(index + 1) % len(plan["waypoints"])]
            assert start["x"] == end["x"] or start["z"] == end["z"]
        assert plan["traversableBoundary"]
    assert len(by_zone["zone-line-a"]) == 2
    assert len(by_zone["zone-line-b"]) == 2
    assert [
        plan["placementId"] for plan in by_zone["zone-line-a"]
    ] == ["operator-line-a-far", "operator-line-a-near"]
    assert by_zone["zone-line-a"][0]["assignedPlacementIds"] == [
        "bench-line-a-low"
    ]
    assert by_zone["zone-line-a"][1]["assignedPlacementIds"] == [
        "bench-line-a-high"
    ]
    assert all(
        gate["participantPlanIds"][0]
        != gate["participantPlanIds"][1]
        for gate in first["assistanceGatePlans"]
    )
    assert all(
        link["traversableBoundary"]
        and link["planId"]
        and link["pointId"]
        and link["handoffIds"]
        for link in first["pedestrianLinkPlans"]
    )

    operator_zone_ids = {plan["zoneId"] for plan in first["operatorPlans"]}
    handoff_pairs = {
        (item["fromZoneId"], item["toZoneId"])
        for item in first["materialHandoffs"]
    }
    assert operator_zone_ids == {
        "zone-cell-a",
        "zone-cell-b",
        "zone-line-a",
        "zone-line-b",
        "zone-kit-a",
        "zone-kit-b",
    }
    assert handoff_pairs == {
        ("zone-kit-a", "zone-line-a"),
        ("zone-kit-b", "zone-line-b"),
        ("zone-line-a", "zone-cell-a"),
        ("zone-line-b", "zone-cell-b"),
    }
    assert all(
        item["evidenceStatus"] == "derived"
        for item in first["materialHandoffs"] + first["fifoPoints"]
    )
    plan_ids = {plan["planId"] for plan in first["operatorPlans"]}
    connection_ids = {
        plan["connectionPlanId"] for plan in first["pedestrianLinkPlans"]
    }
    assert all(
        handoff["fromPlanId"] in plan_ids
        and handoff["toPlanId"] in plan_ids
        and handoff["fromPlanId"] != handoff["toPlanId"]
        and handoff["fromConnectionPlanId"] in connection_ids
        and handoff["toConnectionPlanId"] in connection_ids
        for handoff in first["materialHandoffs"]
    )


def test_browser_layer_retains_qualification_and_detaches_inputs():
    blueprint = derive_facility_lean_motion_blueprint(_layout())
    operator_paths = [{
        "pathId": "path-one",
        "actorId": "actor-one",
        "zoneId": "zone-cell-a",
        "pathKind": "cell_work_loop",
        "centerline": [
            {"x": 2, "z": 2},
            {"x": 4, "z": 2},
            {"x": 4, "z": 4},
            {"x": 2, "z": 2},
        ],
        "closed": True,
        "evidenceStatus": "derived",
    }]

    layer = build_facility_lean_motion(blueprint, operator_paths)
    operator_paths[0]["centerline"][0]["x"] = 999

    assert layer["schemaVersion"] == FACILITY_LEAN_MOTION_SCHEMA_VERSION
    assert layer["qualification"] == FACILITY_LEAN_MOTION_QUALIFICATION
    assert layer["evidenceStatus"] == "derived"
    assert layer["operatorPaths"][0]["centerline"][0]["x"] == 2
    assert layer["pedestrianConnections"] == []
    assert layer["assistanceGates"] == []
    assert len(layer["materialHandoffs"]) == 4
    assert len(layer["fifoPoints"]) == 8
