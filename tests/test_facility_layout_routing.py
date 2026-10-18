from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

import ai_inspector.facility_layout.routing as routing_module
from ai_inspector.facility_layout.routing import (
    FacilityRoutingResourceError,
    PROCESS_SEMANTICS,
    build_aisle_topology,
    estimate_aisle_distance,
    generate_connector_candidates,
    normalized_cardinal_route_heading,
    plan_forklift_route,
    projected_swept_sample_count,
    persisted_route_fingerprint,
    resolve_endpoint,
    routing_layout_fingerprint,
    stable_route_fingerprint,
    validate_facility_aisle_route,
    validate_route,
    validate_swept_volume,
    validate_utility_network,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "routing"
    / "p7-routing-goldens.json"
)
ASSET_REVISION = "e" * 64
SHELL_REVISION = "a" * 64


def _rectangle(x0: float, z0: float, x1: float, z1: float):
    return [
        {"x": x0, "z": z0},
        {"x": x1, "z": z0},
        {"x": x1, "z": z1},
        {"x": x0, "z": z1},
    ]


def _placement(
    placement_id: str,
    x: float,
    z: float,
    *,
    quaternion=None,
):
    return {
        "placementId": placement_id,
        "assetId": "asset-machine",
        "assetDefinitionRevision": ASSET_REVISION,
        "transform": {
            "position": {"x": x, "y": 0.0, "z": z},
            "quaternion": quaternion
            or {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "scale": 1,
        },
        "positionMode": "manual",
        "snapRelationship": None,
        "metadata": {},
    }


def _asset_definition():
    return {
        "documentKind": "industrial_asset_definition",
        "assetId": "asset-machine",
        "connectors": [
            {
                "connectorId": "material-out",
                "connectorKind": "material",
                "position": {"x": 1.0, "y": 0.5, "z": 0.0},
                "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                "role": "output",
                "interface": {"carrier": "pallet"},
                "evidenceStatus": "authored",
                "evidence": ["ev-material"],
            },
            {
                "connectorId": "compressed-air-in",
                "connectorKind": "compressed_air",
                "position": {"x": -1.0, "y": 1.5, "z": 0.0},
                "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
                "role": "input",
                "interface": {
                    "nominalDiameterMm": 12,
                    "interfaceStandard": "NPT",
                },
                "evidenceStatus": "authored",
                "evidence": ["ev-air"],
            },
        ],
    }


def _asset_catalog():
    return {
        "asset-machine": {
            "revision": ASSET_REVISION,
            "document": _asset_definition(),
        }
    }


def _shell():
    return {
        "schemaVersion": 1,
        "documentKind": "facility_shell",
        "shellId": "shell-site-a",
        "shellConnectors": [
            {
                "connectorId": "air-header",
                "serviceType": "compressed_air",
                "position": {"x": 0.0, "y": 3.0, "z": 2.0},
                "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                "role": "source",
                "interface": {
                    "nominalDiameterMm": 12,
                    "interfaceStandard": "NPT",
                },
                "evidence": ["ev-air-header"],
            },
            {
                "connectorId": "forklift-door",
                "serviceType": "forklift",
                "position": {"x": 0.0, "y": 0.0, "z": 4.0},
                "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                "role": "bidirectional",
                "evidence": ["ev-door"],
            },
        ],
    }


def _layout():
    return {
        "layoutId": "fl-routing",
        "sourceShellRef": {
            "shellId": "shell-site-a",
            "shellRevision": SHELL_REVISION,
            "coordinateFrameFingerprint": "b" * 64,
        },
        "placements": [
            _placement("pl-machine-a", 2.0, 2.0),
            _placement(
                "pl-machine-b",
                6.0,
                2.0,
                quaternion={"x": 0.0, "y": 1.0, "z": 0.0, "w": 0.0},
            ),
        ],
        "zones": [
            {
                "zoneId": "zn-receiving",
                "zoneType": "receiving",
                "boundary": _rectangle(0.0, 0.0, 4.0, 4.0),
                "anchors": [
                    {
                        "anchorId": "za-material-in",
                        "anchorKind": "material",
                        "position": {"x": 0.0, "y": 0.0, "z": 2.0},
                        "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "allowedRouteKinds": ["material"],
                        "evidence": [],
                    }
                ],
            }
        ],
    }


def test_semantic_aisle_uses_world_endpoints_without_vehicle_authority():
    layout = _layout()
    route = {
        "routeId": "rt-main-aisle",
        "routeKind": "forklift",
        "sourceEndpoint": {
            "kind": "world_point",
            "position": {"x": 0.0, "y": 0.0, "z": 5.0},
        },
        "targetEndpoint": {
            "kind": "world_point",
            "position": {"x": 20.0, "y": 0.0, "z": 5.0},
        },
        "routingMode": "vehicle",
        "centerline": [
            {"x": 0.0, "y": 0.0, "z": 5.0},
            {"x": 20.0, "y": 0.0, "z": 5.0},
        ],
        "corridorWidth": 3.5,
        "sourceRevisions": {"layoutBaseRevision": "d" * 64},
        "requirements": [],
        "evidence": [],
        "extensions": {
            "facilityAisle": {
                "schemaVersion": 1,
                "aisleKind": "forklift",
                "direction": "two_way",
                "color": "#d9a514",
                "clearanceEvidenceStatus": "unverified",
            }
        },
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)

    result = validate_facility_aisle_route(layout, route)

    assert result["valid"] is True
    assert result["source"]["endpointKind"] == "world_point"
    assert result["target"]["position"] == {"x": 20.0, "y": 0.0, "z": 5.0}
    assert [item["code"] for item in result["findings"]] == [
        "aisle_clearance_unverified"
    ]

    unsupported = deepcopy(route)
    unsupported["extensions"]["facilityAisle"][
        "clearanceEvidenceStatus"
    ] = "authored"
    invalid = validate_facility_aisle_route(layout, unsupported)
    assert invalid["valid"] is False
    assert [item["code"] for item in invalid["findings"]] == [
        "aisle_authoritative_evidence_missing"
    ]


def _department_bound_aisle(start_x: float, end_x: float):
    route = {
        "routeId": "rt-spine",
        "routeKind": "forklift",
        "sourceEndpoint": {
            "kind": "world_point",
            "position": {"x": start_x, "y": 0.0, "z": 5.0},
        },
        "targetEndpoint": {
            "kind": "world_point",
            "position": {"x": end_x, "y": 0.0, "z": 5.0},
        },
        "routingMode": "polyline",
        "centerline": [
            {"x": start_x, "y": 0.0, "z": 5.0},
            {"x": end_x, "y": 0.0, "z": 5.0},
        ],
        "corridorWidth": 3.5,
        "sourceRevisions": {"layoutBaseRevision": "d" * 64},
        "requirements": [],
        "evidence": [],
        "extensions": {
            "facilityAisle": {
                "schemaVersion": 1,
                "aisleKind": "forklift",
                "direction": "two_way",
                "color": "#d9a514",
                "clearanceEvidenceStatus": "unverified",
                "sourceZoneId": "zn-receiving",
                "targetZoneId": "zn-shipping",
                "viaZoneIds": ["zn-machining"],
                "areaAccounting": "overlay",
                "widthAuthority": "unknown",
            }
        },
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    return route


def test_aisle_bound_to_departments_must_extend_into_them():
    # Sage drew a Receiving-to-Shipping aisle that stopped at both department
    # edges, and review tools then reported the racks and docks as connected.
    layout = _layout()
    layout["zones"] = [
        {"zoneId": "zn-receiving", "label": "Receiving",
         "boundary": _rectangle(0.0, 0.0, 10.0, 10.0)},
        {"zoneId": "zn-machining", "label": "Machining",
         "boundary": _rectangle(10.0, 0.0, 30.0, 10.0)},
        {"zoneId": "zn-shipping", "label": "Shipping",
         "boundary": _rectangle(30.0, 0.0, 40.0, 10.0)},
    ]

    stopping = validate_facility_aisle_route(layout, _department_bound_aisle(10.0, 30.0))
    unreached = [
        item for item in stopping["findings"]
        if item["code"] == "aisle_zone_not_entered"
    ]
    assert stopping["valid"] is True
    assert {item["severity"] for item in unreached} == {"warning"}
    assert sorted(
        (item["details"]["bindingRole"], item["details"]["zoneLabel"])
        for item in unreached
    ) == [("source", "Receiving"), ("target", "Shipping")]

    reaching = validate_facility_aisle_route(layout, _department_bound_aisle(2.0, 38.0))
    assert "aisle_zone_not_entered" not in [
        item["code"] for item in reaching["findings"]
    ]


def _utility_network():
    return {
        "utilityNetworkId": "un-air",
        "networkKind": "compressed_air",
        "label": "Machine air",
        "sourceRevisionRefs": {"shell": SHELL_REVISION},
        "nodes": [
            {
                "networkNodeId": "nn-source",
                "nodeKind": "endpoint",
                "networkRole": "supply",
                "endpointRef": {
                    "kind": "shell_connector",
                    "shellId": "shell-site-a",
                    "shellRevision": SHELL_REVISION,
                    "connectorId": "air-header",
                },
            },
            {
                "networkNodeId": "nn-machine",
                "nodeKind": "endpoint",
                "networkRole": "sink",
                "endpointRef": {
                    "kind": "placement_connector",
                    "placementId": "pl-machine-a",
                    "connectorId": "compressed-air-in",
                },
            },
        ],
        "segments": [
            {
                "networkSegmentId": "ns-air-machine",
                "sourceNetworkNodeId": "nn-source",
                "targetNetworkNodeId": "nn-machine",
                "centerline": [
                    {"x": 0.0, "y": 3.0, "z": 2.0},
                    {"x": 1.0, "y": 1.5, "z": 2.0},
                ],
                "interface": {
                    "nominalDiameterMm": 12,
                    "interfaceStandard": "NPT",
                },
                "capacity": {"maximumFlowCfm": 35},
                "requirements": [],
                "evidence": [],
            }
        ],
        "requirements": [],
        "evidence": [],
    }


def _aisle_layout():
    def aisle(zone_id, boundary):
        return {
            "zoneId": zone_id,
            "zoneType": "aisle",
            "label": zone_id,
            "boundary": boundary,
            "floorElevation": 0.0,
            "anchors": [],
            "evidence": [],
        }

    return {
        "zones": [
            aisle("zn-horizontal", _rectangle(0.0, 0.0, 10.0, 4.0)),
            aisle("zn-vertical", _rectangle(6.0, 0.0, 10.0, 10.0)),
        ]
    }


def _goldens():
    return json.loads(FIXTURE.read_text("utf-8"))


def test_occurrence_qualified_placement_connectors_are_unambiguous():
    layout = _layout()
    endpoint_a = {
        "kind": "placement_connector",
        "placementId": "pl-machine-a",
        "connectorId": "material-out",
    }
    endpoint_b = {
        **endpoint_a,
        "placementId": "pl-machine-b",
    }
    first = resolve_endpoint(
        layout,
        endpoint_a,
        asset_definitions=_asset_catalog(),
        route_kind="material",
        direction="source",
    )
    second = resolve_endpoint(
        layout,
        endpoint_b,
        asset_definitions=_asset_catalog(),
        route_kind="material",
        direction="source",
    )
    assert first["resolved"] is second["resolved"] is True
    assert first["qualifiedEndpointId"] == (
        "placement:pl-machine-a:material-out"
    )
    assert second["qualifiedEndpointId"] == (
        "placement:pl-machine-b:material-out"
    )
    assert first["position"] == {"x": 3.0, "y": 0.5, "z": 2.0}
    assert second["position"] == {"x": 5.0, "y": 0.5, "z": 2.0}
    assert first["facing"] == {"x": 1.0, "y": 0.0, "z": 0.0}
    assert second["facing"] == {"x": -1.0, "y": 0.0, "z": 0.0}
    assert first["qualifiedEndpointId"] != second["qualifiedEndpointId"]


def test_zone_and_revision_bound_shell_connectors_resolve_deterministically():
    layout = _layout()
    anchor = resolve_endpoint(
        layout,
        {
            "kind": "zone_anchor",
            "zoneId": "zn-receiving",
            "anchorId": "za-material-in",
        },
        route_kind="material",
        direction="source",
    )
    shell = resolve_endpoint(
        layout,
        {
            "kind": "shell_connector",
            "shellId": "shell-site-a",
            "shellRevision": SHELL_REVISION,
            "connectorId": "forklift-door",
        },
        shell=_shell(),
        shell_revision=SHELL_REVISION,
        route_kind="forklift",
        direction="target",
    )
    assert anchor["resolved"] is shell["resolved"] is True
    assert anchor["qualifiedEndpointId"] == (
        "zone:zn-receiving:za-material-in"
    )
    assert shell["qualifiedEndpointId"].startswith(
        f"shell:shell-site-a:{SHELL_REVISION}:"
    )
    stale = resolve_endpoint(
        layout,
        {
            "kind": "shell_connector",
            "shellId": "shell-site-a",
            "shellRevision": SHELL_REVISION,
            "connectorId": "forklift-door",
        },
        shell=_shell(),
        shell_revision="9" * 64,
        route_kind="forklift",
    )
    assert stale["resolved"] is False
    assert [item["code"] for item in stale["findings"]] == [
        "stale_shell_revision"
    ]


def test_direction_and_local_connector_only_references_fail_closed():
    layout = _layout()
    invalid_direction = resolve_endpoint(
        layout,
        {
            "kind": "placement_connector",
            "placementId": "pl-machine-a",
            "connectorId": "material-out",
        },
        asset_definitions=_asset_catalog(),
        route_kind="material",
        direction="target",
    )
    assert invalid_direction["resolved"] is False
    assert [item["code"] for item in invalid_direction["findings"]] == [
        "connector_direction_invalid"
    ]
    local_only = resolve_endpoint(
        layout,
        {"kind": "placement_connector", "connectorId": "material-out"},
        asset_definitions=_asset_catalog(),
    )
    assert local_only["resolved"] is False
    assert [item["code"] for item in local_only["findings"]] == [
        "dangling_placement_endpoint"
    ]
    bare_catalog = resolve_endpoint(
        layout,
        {
            "kind": "placement_connector",
            "placementId": "pl-machine-a",
            "connectorId": "material-out",
        },
        asset_definitions={"asset-machine": _asset_definition()},
    )
    assert bare_catalog["resolved"] is False
    assert [item["code"] for item in bare_catalog["findings"]] == [
        "asset_definition_revision_unavailable"
    ]

    unbound_shell = resolve_endpoint(
        layout,
        {
            "kind": "shell_connector",
            "shellId": "shell-site-a",
            "shellRevision": SHELL_REVISION,
            "connectorId": "forklift-door",
        },
        shell=_shell(),
        route_kind="forklift",
    )
    assert unbound_shell["resolved"] is False
    assert [item["code"] for item in unbound_shell["findings"]] == [
        "stale_shell_revision"
    ]


def test_utility_service_direction_and_interface_are_validated():
    valid = validate_utility_network(
        _layout(),
        _utility_network(),
        asset_definitions=_asset_catalog(),
        shell=_shell(),
        shell_revision=SHELL_REVISION,
    )
    assert valid["valid"] is True
    assert valid["findings"] == []
    assert [item["networkNodeId"] for item in valid["resolvedNodes"]] == [
        "nn-machine",
        "nn-source",
    ]
    assert valid["resolvedSegments"] == [
        {
            "networkSegmentId": "ns-air-machine",
            "sourceNetworkNodeId": "nn-source",
            "targetNetworkNodeId": "nn-machine",
            "serviceType": "compressed_air",
            "interface": {
                "interfaceStandard": "NPT",
                "nominalDiameterMm": 12,
            },
            "capacity": {"maximumFlowCfm": 35},
        }
    ]
    reordered_network = _utility_network()
    reordered_network["nodes"].reverse()
    reordered_network["segments"].reverse()
    reordered = validate_utility_network(
        _layout(),
        reordered_network,
        asset_definitions=_asset_catalog(),
        shell=_shell(),
        shell_revision=SHELL_REVISION,
    )
    assert reordered == valid

    mismatch = _utility_network()
    mismatch["segments"][0]["interface"]["nominalDiameterMm"] = 25
    invalid = validate_utility_network(
        _layout(),
        mismatch,
        asset_definitions=_asset_catalog(),
        shell=_shell(),
        shell_revision=SHELL_REVISION,
    )
    assert invalid["valid"] is False
    assert [item["code"] for item in invalid["findings"]] == [
        "utility_spec_mismatch",
        "utility_spec_mismatch",
    ]
    assert all(item["findingId"].startswith("flr-") for item in invalid["findings"])


def test_utility_unknown_spec_is_blocked_not_assumed():
    catalog = _asset_catalog()
    catalog["asset-machine"]["document"]["connectors"][1]["interface"].pop(
        "interfaceStandard"
    )
    result = validate_utility_network(
        _layout(),
        _utility_network(),
        asset_definitions=catalog,
        shell=_shell(),
        shell_revision=SHELL_REVISION,
    )
    assert result["valid"] is False
    finding = next(
        item
        for item in result["findings"]
        if "interfaceStandard" in item["subjects"]
    )
    assert finding["severity"] == "blocked"
    assert finding["code"] == "utility_spec_mismatch"


def test_aisle_topology_and_distance_are_stable_and_do_not_create_precedence():
    extra = {
        "start": {"x": 1.0, "z": 2.0},
        "goal": {"x": 8.0, "z": 8.0},
    }
    first = build_aisle_topology(_aisle_layout(), extra_points=extra)
    reversed_layout = _aisle_layout()
    reversed_layout["zones"].reverse()
    second = build_aisle_topology(reversed_layout, extra_points=extra)
    assert first == second
    assert first["findings"] == []
    estimate = estimate_aisle_distance(first, "start", "goal")
    assert estimate["reachable"] is True
    assert estimate["distanceMeters"] == 13.0
    assert estimate["nodePath"][0] == "start"
    assert estimate["nodePath"][-1] == "goal"
    assert first["processSemantics"] == estimate["processSemantics"] == {
        "precedenceDerived": False,
        "policy": "spatial_proximity_never_implies_process_precedence",
    }


@pytest.mark.parametrize("case", _goldens()["scenarios"], ids=lambda case: case["caseId"])
def test_forklift_routing_goldens(case):
    fixture = _goldens()
    result = plan_forklift_route(
        case["start"],
        case["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=case["traversablePolygons"],
        obstacles=case.get("obstacles", []),
        load=case.get("load"),
        allow_reverse=case["allowReverse"],
        grid_resolution_meters=0.5,
        source_revisions=fixture["sourceRevisions"],
    )
    expected = case["expected"]
    assert result["accepted"] == expected["accepted"]
    assert result["distanceMeters"] == expected["distanceMeters"]
    assert result["reverseUsed"] == expected["reverseUsed"]
    assert result["loaded"] == expected["loaded"]
    assert [item["code"] for item in result["findings"]] == expected[
        "findingCodes"
    ]
    assert [item["findingId"] for item in result["findings"]] == expected[
        "findingIds"
    ]
    assert result["routeFingerprint"] == expected["routeFingerprint"]
    assert result["processSemantics"] == PROCESS_SEMANTICS
    if result["accepted"]:
        assert result["sweptVolume"]["valid"] is True
        assert result["sweptVolume"]["findings"] == []


def test_independent_swept_volume_rejects_tampered_collision_and_tight_turn():
    fixture = _goldens()
    straight = fixture["scenarios"][0]
    accepted = plan_forklift_route(
        straight["start"],
        straight["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=straight["traversablePolygons"],
        allow_reverse=False,
        source_revisions=fixture["sourceRevisions"],
    )
    assert accepted["accepted"] is True
    collision = validate_swept_volume(
        accepted["poses"],
        fixture["vehicleProfile"],
        traversable_polygons=straight["traversablePolygons"],
        obstacles=[
            {
                "obstacleId": "blocked-center",
                "boundary": _rectangle(4.5, 1.0, 5.5, 3.0),
            }
        ],
        allow_reverse=False,
    )
    assert collision["valid"] is False
    assert [item["code"] for item in collision["findings"]] == [
        "route_swept_volume_collision"
    ]

    tight_turn = validate_swept_volume(
        [
            {"x": 2.0, "z": 2.0, "heading": 0.0, "gear": "forward"},
            {
                "x": 2.1,
                "z": 2.1,
                "heading": math.pi / 2.0,
                "gear": "forward",
            },
        ],
        fixture["vehicleProfile"],
        traversable_polygons=[_rectangle(0.0, 0.0, 10.0, 10.0)],
        allow_reverse=False,
    )
    assert tight_turn["valid"] is False
    assert "route_turning_radius_violation" in {
        item["code"] for item in tight_turn["findings"]
    }


def test_swept_sample_budget_binds_before_dense_pose_allocation(monkeypatch):
    fixture = _goldens()
    poses = [
        {"x": 0.0, "z": 2.0, "heading": 0.0, "gear": "forward"},
        {"x": 10.0, "z": 2.0, "heading": 0.0, "gear": "forward"},
    ]
    assert projected_swept_sample_count(poses, 0.1) == 101
    entered = []

    def forbidden(*_args, **_kwargs):
        entered.append(True)
        raise AssertionError("dense allocation must not run")

    monkeypatch.setattr(routing_module, "_interpolate_poses", forbidden)
    with pytest.raises(FacilityRoutingResourceError) as caught:
        validate_swept_volume(
            poses,
            fixture["vehicleProfile"],
            traversable_polygons=[_rectangle(-1.0, 0.0, 11.0, 4.0)],
            sample_spacing_meters=0.1,
            maximum_sample_count=100,
        )
    assert caught.value.code == "facility_route_sample_budget_exceeded"
    assert caught.value.details["projectedSampleCount"] == 101
    assert entered == []


def test_swept_sample_boundary_and_clearance_are_exact_and_reproducible():
    fixture = _goldens()
    poses = [
        {"x": 0.0, "z": 2.0, "heading": 0.0, "gear": "forward"},
        {"x": 10.0, "z": 2.0, "heading": 0.0, "gear": "forward"},
    ]
    kwargs = {
        "traversable_polygons": [_rectangle(-1.0, 0.0, 11.0, 4.0)],
        "obstacles": [
            {
                "obstacleId": "north-wall",
                "boundary": _rectangle(-1.0, 3.0, 11.0, 3.5),
            }
        ],
        "sample_spacing_meters": 0.1,
        "maximum_sample_count": 101,
    }
    first = validate_swept_volume(poses, fixture["vehicleProfile"], **kwargs)
    second = validate_swept_volume(poses, fixture["vehicleProfile"], **kwargs)

    below_boundary = validate_swept_volume(
        [poses[0], {**poses[1], "x": 9.9}],
        fixture["vehicleProfile"],
        **kwargs,
    )

    assert first == second
    assert below_boundary["sampledPoseCount"] == 100
    assert first["sampledPoseCount"] == first["projectedSampleCount"] == 101
    assert len(first["clearance"]["samples"]) == 101
    assert first["clearance"]["samples"][0] == {
        "distanceMeters": 0.0,
        "nearestObstacleIds": ["north-wall"],
        "clearanceMeters": 0.6,
    }
    assert first["geometry"]["ringOrientation"] == {
        "exterior": "counterclockwise",
        "holes": "clockwise",
    }


def test_every_swept_error_is_localized_or_explicitly_unlocalized():
    fixture = _goldens()
    result = validate_swept_volume(
        [
            {"x": 2.0, "z": 2.0, "heading": 0.0, "gear": "forward"},
            {
                "x": 2.1,
                "z": 2.1,
                "heading": math.pi / 2.0,
                "gear": "reverse",
            },
        ],
        fixture["vehicleProfile"] | {"reversePolicy": "prohibited"},
        traversable_polygons=[_rectangle(0.0, 0.0, 10.0, 10.0)],
        allow_reverse=False,
    )
    assert result["valid"] is False
    assert result["findings"]
    assert all(
        isinstance(item.get("location"), dict)
        and isinstance(item["location"].get("localized"), bool)
        for item in result["findings"]
        if item["severity"] == "error"
    )


def test_route_fingerprints_and_findings_are_stable_and_input_bound():
    fixture = _goldens()
    straight = fixture["scenarios"][0]
    first = plan_forklift_route(
        straight["start"],
        straight["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=straight["traversablePolygons"],
        allow_reverse=False,
        source_revisions=fixture["sourceRevisions"],
    )
    second = plan_forklift_route(
        straight["start"],
        straight["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=deepcopy(straight["traversablePolygons"]),
        allow_reverse=False,
        source_revisions=deepcopy(fixture["sourceRevisions"]),
    )
    assert first == second
    changed_revisions = dict(fixture["sourceRevisions"])
    changed_revisions["layout"] = "c" * 64
    changed = plan_forklift_route(
        straight["start"],
        straight["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=straight["traversablePolygons"],
        allow_reverse=False,
        source_revisions=changed_revisions,
    )
    assert changed["accepted"] is True
    assert changed["centerline"] == first["centerline"]
    assert changed["routeFingerprint"] != first["routeFingerprint"]
    assert stable_route_fingerprint({"b": 2, "a": 1}) == stable_route_fingerprint(
        {"a": 1, "b": 2}
    )


def test_vehicle_load_and_grade_limits_fail_closed():
    fixture = _goldens()
    straight = fixture["scenarios"][0]
    overloaded = plan_forklift_route(
        straight["start"],
        straight["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=straight["traversablePolygons"],
        load={
            "massKilograms": 1001,
            "footprint": fixture["vehicleProfile"]["footprint"],
        },
        allow_reverse=False,
    )
    assert overloaded["accepted"] is False
    assert [item["code"] for item in overloaded["findings"]] == [
        "route_load_exceeded"
    ]

    elevated_goal = dict(straight["goal"], y=1.0)
    excessive_grade = plan_forklift_route(
        dict(straight["start"], y=0.0),
        elevated_goal,
        fixture["vehicleProfile"],
        traversable_polygons=straight["traversablePolygons"],
        allow_reverse=False,
    )
    assert excessive_grade["accepted"] is False
    assert [item["code"] for item in excessive_grade["findings"]] == [
        "route_grade_exceeded"
    ]
    vertical_only = plan_forklift_route(
        {"x": 2.0, "y": 0.0, "z": 2.0, "heading": 0.0},
        {"x": 2.0, "y": 1.0, "z": 2.0, "heading": 0.0},
        fixture["vehicleProfile"],
        traversable_polygons=straight["traversablePolygons"],
        allow_reverse=False,
    )
    assert vertical_only["accepted"] is False
    assert vertical_only["findings"][0]["details"]["gradePercent"] == "infinite"


def test_spatial_routing_never_emits_process_precedence():
    fixture = _goldens()
    for case in fixture["scenarios"]:
        result = plan_forklift_route(
            case["start"],
            case["goal"],
            fixture["vehicleProfile"],
            traversable_polygons=case["traversablePolygons"],
            load=case.get("load"),
            allow_reverse=case["allowReverse"],
            source_revisions=fixture["sourceRevisions"],
        )
        assert result["processSemantics"]["precedenceDerived"] is False
        assert "processEdges" not in result
        assert "precedence" not in result


def test_connector_candidates_are_occurrence_qualified_and_deterministic():
    asset = _asset_definition()
    asset["connectors"].append(
        {
            "connectorId": "material-in",
            "connectorKind": "material",
            "position": {"x": -1.0, "y": 0.5, "z": 0.0},
            "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
            "role": "input",
            "interface": {"carrier": "pallet"},
            "evidenceStatus": "authored",
            "evidence": ["ev-material"],
        }
    )
    catalog = {
        "asset-machine": {
            "revision": ASSET_REVISION,
            "document": asset,
        }
    }
    source = {
        "kind": "placement_connector",
        "placementId": "pl-machine-a",
        "connectorId": "material-out",
    }
    first = generate_connector_candidates(
        _layout(),
        source,
        route_kind="material",
        asset_definitions=catalog,
        shell={"document": _shell(), "revision": SHELL_REVISION},
        shell_revision=SHELL_REVISION,
    )
    second = generate_connector_candidates(
        deepcopy(_layout()),
        deepcopy(source),
        route_kind="material",
        asset_definitions=deepcopy(catalog),
        shell={"document": deepcopy(_shell()), "revision": SHELL_REVISION},
        shell_revision=SHELL_REVISION,
    )

    assert first == second
    targets = {
        item["targetQualifiedEndpointId"]
        for item in first["candidates"]
    }
    assert "placement:pl-machine-a:material-in" in targets
    assert "placement:pl-machine-b:material-in" in targets
    assert all(
        item["sourceQualifiedEndpointId"]
        == "placement:pl-machine-a:material-out"
        for item in first["candidates"]
    )
    assert len({item["candidateId"] for item in first["candidates"]}) == len(
        first["candidates"]
    )


def test_persisted_route_must_match_resolved_connector_geometry():
    asset = _asset_definition()
    asset["connectors"].append(
        {
            "connectorId": "material-in",
            "connectorKind": "material",
            "position": {"x": -1.0, "y": 0.5, "z": 0.0},
            "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
            "role": "input",
            "interface": {"carrier": "pallet"},
            "evidenceStatus": "authored",
            "evidence": ["ev-material"],
        }
    )
    catalog = {
        "asset-machine": {
            "revision": ASSET_REVISION,
            "document": asset,
        }
    }
    layout = _layout()
    route = {
        "routeId": "rt-machine-a-b",
        "routeKind": "material",
        "sourceEndpoint": {
            "kind": "placement_connector",
            "placementId": "pl-machine-a",
            "connectorId": "material-out",
        },
        "targetEndpoint": {
            "kind": "placement_connector",
            "placementId": "pl-machine-b",
            "connectorId": "material-in",
        },
        "centerline": [
            {"x": 3.0, "y": 0.5, "z": 2.0},
            {"x": 7.0, "y": 0.5, "z": 2.0},
        ],
        "routingMode": "polyline",
        "corridorWidth": 1.0,
        "sourceRevisions": {
            "layout": routing_layout_fingerprint(layout),
            "shell": SHELL_REVISION,
        },
        "requirements": [],
        "evidence": [],
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    valid = validate_route(
        layout,
        route,
        asset_definitions=catalog,
        shell={"document": _shell(), "revision": SHELL_REVISION},
        shell_revision=SHELL_REVISION,
    )
    assert valid["valid"] is True
    assert valid["findings"] == []

    tampered = deepcopy(route)
    tampered["centerline"][0]["x"] = 4.0
    invalid = validate_route(
        layout,
        tampered,
        asset_definitions=catalog,
        shell={"document": _shell(), "revision": SHELL_REVISION},
        shell_revision=SHELL_REVISION,
    )
    assert invalid["valid"] is False
    assert {
        item["code"] for item in invalid["findings"]
    } == {
        "route_endpoint_geometry_mismatch",
        "stale_route_geometry",
    }


def test_connector_interfaces_reject_incompatible_material_carriers():
    asset = _asset_definition()
    asset["connectors"].append(
        {
            "connectorId": "material-in",
            "connectorKind": "material",
            "position": {"x": -1.0, "y": 0.5, "z": 0.0},
            "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
            "role": "input",
            "interface": {"carrier": "bin"},
            "evidenceStatus": "authored",
            "evidence": ["ev-material-bin"],
        }
    )
    catalog = {
        "asset-machine": {
            "revision": ASSET_REVISION,
            "document": asset,
        }
    }
    result = generate_connector_candidates(
        _layout(),
        {
            "kind": "placement_connector",
            "placementId": "pl-machine-a",
            "connectorId": "material-out",
        },
        route_kind="material",
        asset_definitions=catalog,
    )
    assert result["candidates"]
    assert all(
        candidate["targetEndpoint"]
        != {
            "kind": "placement_connector",
            "placementId": "pl-machine-a",
            "connectorId": "material-in",
        }
        for candidate in result["candidates"]
    )


def test_utility_centerline_and_flow_direction_are_enforced():
    network = _utility_network()
    network["segments"][0]["centerline"][0]["x"] = 100.0
    displaced = validate_utility_network(
        _layout(),
        network,
        asset_definitions=_asset_catalog(),
        shell={"document": _shell(), "revision": SHELL_REVISION},
        shell_revision=SHELL_REVISION,
    )
    assert displaced["valid"] is False
    assert "utility_endpoint_geometry_mismatch" in {
        item["code"] for item in displaced["findings"]
    }

    reversed_network = _utility_network()
    segment = reversed_network["segments"][0]
    segment["sourceNetworkNodeId"], segment["targetNetworkNodeId"] = (
        segment["targetNetworkNodeId"],
        segment["sourceNetworkNodeId"],
    )
    segment["centerline"] = list(reversed(segment["centerline"]))
    reversed_result = validate_utility_network(
        _layout(),
        reversed_network,
        asset_definitions=_asset_catalog(),
        shell={"document": _shell(), "revision": SHELL_REVISION},
        shell_revision=SHELL_REVISION,
    )
    assert reversed_result["valid"] is False
    assert "utility_flow_direction_invalid" in {
        item["code"] for item in reversed_result["findings"]
    }


def test_swept_volume_rejects_gap_between_traversable_polygons():
    profile = deepcopy(_goldens()["vehicleProfile"])
    result = validate_swept_volume(
        [
            {"x": 0.0, "z": 0.0, "heading": 0.0, "gear": "forward"},
            {"x": 0.01, "z": 0.0, "heading": 0.0, "gear": "forward"},
        ],
        profile,
        traversable_polygons=[
            _rectangle(-2.0, -2.0, 0.2, 2.0),
            _rectangle(0.3, -2.0, 2.0, 2.0),
        ],
    )
    assert result["valid"] is False
    assert {
        item["code"] for item in result["findings"]
    } == {"route_width_insufficient"}


def test_motion_heading_normalizes_only_sub_tenth_degree_drafting_drift():
    normalized = normalized_cardinal_route_heading(
        {"x": 7.62, "z": 94.7928},
        {"x": 291.6936, "z": 95.0976},
    )
    assert normalized == 0.0
    with pytest.raises(ValueError, match="0.1-degree"):
        normalized_cardinal_route_heading(
            {"x": 0.0, "z": 0.0},
            {"x": 10.0, "z": 1.0},
        )


def test_route_source_revision_is_bound_to_current_spatial_state():
    layout = _layout()
    route = {
        "routeId": "rt-revision-bound",
        "routeKind": "material",
        "sourceEndpoint": {
            "kind": "zone_anchor",
            "zoneId": "zn-receiving",
            "anchorId": "za-material-in",
        },
        "targetEndpoint": {
            "kind": "placement_connector",
            "placementId": "pl-machine-a",
            "connectorId": "material-out",
        },
        "routingMode": "polyline",
        "centerline": [
            {"x": 0.0, "y": 0.0, "z": 2.0},
            {"x": 3.0, "y": 0.5, "z": 2.0},
        ],
        "corridorWidth": 1.0,
        "sourceRevisions": {
            "layout": "9" * 64,
            "shell": SHELL_REVISION,
        },
        "requirements": [],
        "evidence": [],
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    result = validate_route(
        layout,
        route,
        asset_definitions=_asset_catalog(),
        shell={"document": _shell(), "revision": SHELL_REVISION},
        shell_revision=SHELL_REVISION,
    )
    assert result["valid"] is False
    assert "stale_route_source_revision" in {
        item["code"] for item in result["findings"]
    }
