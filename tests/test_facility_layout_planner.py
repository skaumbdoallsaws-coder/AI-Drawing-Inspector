from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    layout_revision,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
)
from ai_inspector.facility_layout.planner import (
    FACILITY_LAYOUT_PLANNER_VERSION,
    FacilityLayoutPlanningError,
    canonical_planner_bytes,
    generate_layout_proposals,
    planner_fingerprint,
    validate_layout_request,
)
from ai_inspector.facility_layout.routing import persisted_route_fingerprint


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "planning"
    / "p8-planning-golden.json"
)


@pytest.fixture()
def golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))


def _plan(golden: dict, **overrides):
    arguments = {
        "layout": golden["baseLayout"],
        "request": golden["request"],
        "asset_definitions": golden["assetDefinitions"],
        "vehicle_profiles": golden["vehicleProfiles"],
    }
    arguments.update(overrides)
    return generate_layout_proposals(**arguments)


def _placement(layout: dict, placement_id: str) -> dict:
    return next(
        item
        for item in layout["placements"]
        if item["placementId"] == placement_id
    )


def _cleanup_request(*, movable_manual=()):
    return {
        "schemaVersion": 1,
        "requestId": "request-p8-cleanup",
        "objective": "cleanup_layout",
        "assetSet": [],
        "strategies": ["compact_rows"],
        "maximumAlternatives": 1,
        "spacingMeters": 0.5,
        "cleanup": {
            "enabled": True,
            "moveAuto": True,
            "movableManualPlacementIds": list(movable_manual),
        },
        "zoneSizing": [],
        "routes": [],
        "sourceRevisions": {},
    }


def test_golden_alternatives_are_pinned_and_complete(golden: dict) -> None:
    result = _plan(golden)

    assert result["plannerVersion"] == FACILITY_LAYOUT_PLANNER_VERSION
    assert result["previewPure"] is True
    assert result["layoutRevision"] == (
        "4bfc7c42283e1cc49a76d7486a31de8337cab0538c6c7c3eba0fed661ce31130"
    )
    assert result["requestFingerprint"] == (
        "e563369fe69acf537c0aece649e1dbdba8f434b36da01f46c4386a9152c55726"
    )
    assert result["dependencyFingerprint"] == (
        "192b8a0a0d0e57a35dfaa1307b23658c6a7efbd53954d7202aca8e27e7d4a972"
    )
    assert result["obstacleFingerprint"] == (
        "c1525710fe2ab9ee3635c39b2ca180eafd79d2083deb4652441b111fc3ac7be6"
    )
    assert [item["alternativeId"] for item in result["alternatives"]] == [
        "fla-p8-cb81c87a6d17a04d3ea9e35f",
        "fla-p8-1cddbcb20279f2d734d1d48c",
        "fla-p8-4373e4cdae6256f10cecc3e8",
    ]
    assert result["selectedAlternativeId"] == (
        "fla-p8-cb81c87a6d17a04d3ea9e35f"
    )
    assert result["rejectedAlternatives"] == []
    for alternative in result["alternatives"]:
        assert alternative["metrics"]["completeAssetSet"] is True
        assert alternative["metrics"]["requestedInstanceCount"] == 7
        assert alternative["metrics"]["resolvedInstanceCount"] == 7
        assert alternative["metrics"]["createdPlacementCount"] == 4
        assert alternative["metrics"]["spatialErrorCount"] == 0
        assert alternative["metrics"]["placementCollisions"] == 0
        assert alternative["metrics"]["clearanceConflicts"] == 0
        assert alternative["newHardFindingIds"] == []


def test_preview_is_pure_and_exact_operations_replay_identically(
    golden: dict,
) -> None:
    original_layout = deepcopy(golden["baseLayout"])
    original_request = deepcopy(golden["request"])
    original_assets = deepcopy(golden["assetDefinitions"])

    result = _plan(golden)
    selected = result["alternatives"][0]
    replay = apply_facility_layout_operations(
        golden["baseLayout"],
        selected["operations"],
        base_revision=result["layoutRevision"],
    )

    assert canonical_layout_bytes(replay["document"]) == canonical_layout_bytes(
        selected["ghostPreview"]["layout"]
    )
    assert replay["canonicalDiff"] == selected["operationReceipt"]["canonicalDiff"]
    assert replay["diffHash"] == selected["operationReceipt"]["diffHash"]
    assert replay["diffHash"] == selected["approvalBinding"]["diffHash"]
    assert selected["approvalBinding"]["obstacleFingerprint"] == (
        result["obstacleFingerprint"]
    )
    assert golden["baseLayout"] == original_layout
    assert golden["request"] == original_request
    assert golden["assetDefinitions"] == original_assets


def test_explicit_replacement_is_preview_only_and_clears_before_planning(
    golden: dict,
) -> None:
    original = deepcopy(golden["baseLayout"])
    request = deepcopy(golden["request"])
    request["requestId"] = "request-p8-explicit-replacement"
    request["cleanup"]["replaceExistingContents"] = True
    request["assetSet"] = request["assetSet"][:2]
    for item in request["assetSet"]:
        item.pop("targetZoneId", None)
        item.pop("existingPlacementId", None)
    request["routes"] = []
    request["zoneSizing"] = [
        {
            "memberItemIds": [request["assetSet"][0]["itemId"]],
            "paddingMeters": 1.0,
            "newZone": {
                "zoneId": "zn-replacement-west",
                "zoneType": "workcell",
                "label": "West department",
                "allowedAssetCategories": [],
                "evidence": [],
            },
        },
        {
            "memberItemIds": [request["assetSet"][1]["itemId"]],
            "paddingMeters": 1.0,
            "newZone": {
                "zoneId": "zn-replacement-east",
                "zoneType": "workcell",
                "label": "East department",
                "allowedAssetCategories": [],
                "evidence": [],
            },
        },
    ]

    shell = {
        "features": [{
            "featureId": "floor-explicit-replacement",
            "featureKind": "floor",
            "geometry": {
                "boundary": [
                    {"x": 0.0, "z": 0.0},
                    {"x": 30.0, "z": 0.0},
                    {"x": 30.0, "z": 20.0},
                    {"x": 0.0, "z": 20.0},
                ],
                "elevation": 0.0,
            },
        }],
    }
    result = _plan(golden, request=request, shell=shell)

    assert result["alternatives"]
    for alternative in result["alternatives"]:
        assert alternative["operations"][0] == {
            "op": "clear_layout_contents"
        }
        ghost = alternative["ghostPreview"]["layout"]
        assert len(ghost["placements"]) == 4
        assert len(ghost["zones"]) == 2
        zone_bounds = {
            zone["zoneId"]: (
                min(point["x"] for point in zone["boundary"]),
                min(point["z"] for point in zone["boundary"]),
                max(point["x"] for point in zone["boundary"]),
                max(point["z"] for point in zone["boundary"]),
            )
            for zone in ghost["zones"]
        }
        assert min(value[0] for value in zone_bounds.values()) <= 2.0
        assert max(value[2] for value in zone_bounds.values()) >= 28.0
        placement_items = {
            item["metadata"]["plannerItemId"]: item
            for item in ghost["placements"]
        }
        expected_zones = {
            request["assetSet"][0]["itemId"]: "zn-replacement-west",
            request["assetSet"][1]["itemId"]: "zn-replacement-east",
        }
        for item_id, placement in placement_items.items():
            minimum_x, minimum_z, maximum_x, maximum_z = zone_bounds[
                expected_zones[item_id]
            ]
            position = placement["transform"]["position"]
            assert minimum_x <= position["x"] <= maximum_x
            assert minimum_z <= position["z"] <= maximum_z
        assert not {
            "pl-p8-existing-auto",
            "pl-p8-existing-manual",
            "pl-p8-existing-locked",
        } & {item["placementId"] for item in ghost["placements"]}
    assert golden["baseLayout"] == original


def test_replacement_department_grid_adds_inferred_macro_infrastructure(
    golden: dict,
) -> None:
    request = deepcopy(golden["request"])
    request["requestId"] = "request-p8-department-infrastructure"
    request["objective"] = "place_and_cleanup"
    request["strategies"] = ["balanced_grid"]
    request["maximumAlternatives"] = 1
    request["cleanup"] = {
        "enabled": True,
        "moveAuto": True,
        "movableManualPlacementIds": [],
        "replaceExistingContents": True,
    }
    request["routes"] = []
    seed = deepcopy(golden["request"]["assetSet"][0])
    seed.pop("targetZoneId", None)
    seed.pop("existingPlacementId", None)
    seed["quantity"] = 1
    request["assetSet"] = []
    request["zoneSizing"] = []
    for index in range(6):
        item = deepcopy(seed)
        item["itemId"] = f"department-item-{index + 1}"
        item["stage"] = index
        request["assetSet"].append(item)
        request["zoneSizing"].append({
            "memberItemIds": [item["itemId"]],
            "paddingMeters": 1.0,
            "newZone": {
                "zoneId": f"zn-department-{index + 1}",
                "zoneType": "workcell",
                "label": f"Department {index + 1}",
                "allowedAssetCategories": [],
                "evidence": [],
            },
        })
    shell = {
        "features": [{
            "featureId": "floor-department-infrastructure",
            "featureKind": "floor",
            "geometry": {
                "boundary": [
                    {"x": 0.0, "z": 0.0},
                    {"x": 30.0, "z": 0.0},
                    {"x": 30.0, "z": 20.0},
                    {"x": 0.0, "z": 20.0},
                ],
                "elevation": 0.0,
            },
        }],
    }

    result = _plan(golden, request=request, shell=shell)
    alternative = result["alternatives"][0]
    ghost = alternative["ghostPreview"]["layout"]

    assert len(ghost["placements"]) == 6
    assert len(ghost["zones"]) == 6
    assert len(ghost["routes"]) == 3
    assert len(ghost["floorMarkings"]) == 8
    assert sum(
        route["extensions"]["facilityAisle"]["aisleKind"] == "forklift"
        for route in ghost["routes"]
    ) == 1
    assert sum(
        route["extensions"]["facilityAisle"]["aisleKind"] == "pedestrian"
        for route in ghost["routes"]
    ) == 2
    assert sum(
        marking["markingType"] == "direction_arrow"
        for marking in ghost["floorMarkings"]
    ) == 6
    assert sum(
        marking["markingType"] == "crosswalk"
        for marking in ghost["floorMarkings"]
    ) == 2
    assert alternative["metrics"]["spatialErrorCount"] == 0
    assert alternative["operations"][0] == {"op": "clear_layout_contents"}


def test_locked_and_manual_placements_are_preserved_by_default(
    golden: dict,
) -> None:
    result = _plan(golden)
    for alternative in result["alternatives"]:
        operations = alternative["operations"]
        assert not any(
            operation.get("placementId") == "pl-p8-existing-locked"
            for operation in operations
        )
        assert not any(
            operation.get("placementId") == "pl-p8-existing-manual"
            for operation in operations
        )
        layout = alternative["ghostPreview"]["layout"]
        assert _placement(
            layout, "pl-p8-existing-locked"
        )["transform"] == _placement(
            golden["baseLayout"], "pl-p8-existing-locked"
        )["transform"]
        assert _placement(
            layout, "pl-p8-existing-manual"
        )["transform"] == _placement(
            golden["baseLayout"], "pl-p8-existing-manual"
        )["transform"]


def test_manual_cleanup_requires_exact_placement_authorization(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    manual = _placement(layout, "pl-p8-existing-manual")
    locked = _placement(layout, "pl-p8-existing-locked")
    manual["transform"] = deepcopy(locked["transform"])

    preserved = _plan(
        golden,
        layout=layout,
        request=_cleanup_request(),
    )
    preserved_alt = preserved["alternatives"][0]
    assert preserved_alt["operations"] == []
    assert _placement(
        preserved_alt["ghostPreview"]["layout"],
        "pl-p8-existing-manual",
    )["transform"] == locked["transform"]

    authorized = _plan(
        golden,
        layout=layout,
        request=_cleanup_request(
            movable_manual=("pl-p8-existing-manual",)
        ),
    )
    authorized_alt = authorized["alternatives"][0]
    manual_moves = [
        operation
        for operation in authorized_alt["operations"]
        if operation.get("placementId") == "pl-p8-existing-manual"
    ]
    assert len(manual_moves) == 1
    assert manual_moves[0]["movementKind"] == "user"
    assert authorized_alt["metrics"]["movedManualCount"] == 1
    assert not any(
        operation.get("placementId") == "pl-p8-existing-locked"
        for operation in authorized_alt["operations"]
    )


def test_auto_cleanup_uses_minimal_deterministic_displacement(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    auto = _placement(layout, "pl-p8-existing-auto")
    locked = _placement(layout, "pl-p8-existing-locked")
    auto["transform"] = deepcopy(locked["transform"])

    result = _plan(
        golden,
        layout=layout,
        request=_cleanup_request(),
    )
    alternative = result["alternatives"][0]
    auto_moves = [
        operation
        for operation in alternative["operations"]
        if operation.get("placementId") == "pl-p8-existing-auto"
    ]
    assert len(auto_moves) == 1
    assert auto_moves[0]["movementKind"] == "automatic"
    assert alternative["metrics"]["autoDisplacementMeters"] == 1.5
    assert alternative["metrics"]["spatialErrorCount"] == 0


@pytest.mark.parametrize(
    "forbidden",
    [
        {"x": 4.0},
        {"position": {"east": 4}},
        {"camera": {"zoom": 1}},
        {"routePoints": []},
        {"transform": {}},
    ],
)
def test_declarative_request_rejects_raw_geometry(
    golden: dict,
    forbidden: dict,
) -> None:
    request = deepcopy(golden["request"])
    request["layoutHint"] = forbidden
    with pytest.raises(FacilityLayoutPlanningError) as caught:
        validate_layout_request(request)
    assert caught.value.code == "raw_geometry_forbidden"


def test_zone_sizing_uses_planned_content_and_stable_identity(
    golden: dict,
) -> None:
    selected = _plan(golden)["alternatives"][0]
    zone = next(
        item
        for item in selected["ghostPreview"]["layout"]["zones"]
        if item["zoneId"] == "zn-p8-generated-cell"
    )
    assert zone["label"] == "Generated production cell"
    assert zone["zoneType"] == "workcell"
    assert len(zone["boundary"]) == 4
    assert any(
        operation["op"] == "add_zone"
        and operation["zone"]["zoneId"] == "zn-p8-generated-cell"
        for operation in selected["operations"]
    )


def test_forklift_route_is_persistable_and_revision_bound(golden: dict) -> None:
    selected = _plan(golden)["alternatives"][0]
    proposals = selected["ghostPreview"]["routeProposals"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["routeRequestId"] == "route-p8-forklift"
    assert proposal["accepted"] is True
    assert proposal["persistable"] is True
    assert proposal["reason"] is None
    assert proposal["route"]["distanceMeters"] == 26.0
    assert proposal["route"]["routeFingerprint"]
    assert proposal["route"]["findings"] == []
    assert proposal["operation"]["op"] == "add_route"
    route = proposal["operation"]["route"]
    assert route["routeId"].startswith("rt-")
    assert route["routeFingerprint"] == persisted_route_fingerprint(route)
    assert route["extensions"]["planner"]["plannedRouteFingerprint"] == (
        proposal["route"]["routeFingerprint"]
    )
    assert route["routeFingerprint"] != proposal["route"]["routeFingerprint"]
    assert route["vehicleProfileRef"] == {
        "vehicleProfileId": "vehicle-p8-forklift",
        "vehicleProfileRevision": "e" * 64,
    }
    assert selected["ghostPreview"]["layout"]["routes"] == [route]
    assert selected["operations"][-1] == proposal["operation"]
    assert selected["metrics"]["acceptedRouteCount"] == 1


def test_hard_route_finding_rejects_the_alternative(golden: dict) -> None:
    layout = deepcopy(golden["baseLayout"])
    aisle = next(
        item for item in layout["zones"] if item["zoneId"] == "zn-p8-aisle"
    )
    aisle["boundary"] = [
        {"x": 0.0, "z": 9.7},
        {"x": 30.0, "z": 9.7},
        {"x": 30.0, "z": 10.3},
        {"x": 0.0, "z": 10.3},
    ]
    request = deepcopy(golden["request"])
    request["strategies"] = ["balanced_grid"]
    request["maximumAlternatives"] = 1

    with pytest.raises(FacilityLayoutPlanningError) as caught:
        _plan(golden, layout=layout, request=request)

    assert caught.value.code == "no_layout_alternative"
    assert caught.value.details["rejectedAlternatives"][0]["finding"]["code"] == (
        "planner_route_rejected"
    )


def test_no_hard_finding_is_introduced_when_baseline_is_already_invalid(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    manual = _placement(layout, "pl-p8-existing-manual")
    locked = _placement(layout, "pl-p8-existing-locked")
    manual["transform"] = deepcopy(locked["transform"])

    result = _plan(
        golden,
        layout=layout,
        request=_cleanup_request(),
    )
    alternative = result["alternatives"][0]
    assert alternative["newHardFindingIds"] == []
    assert alternative["metrics"]["spatialErrorCount"] == 1


def test_unplaceable_complete_asset_set_fails_without_partial_preview(
    golden: dict,
) -> None:
    layout = deepcopy(golden["baseLayout"])
    workcell = next(
        item for item in layout["zones"] if item["zoneId"] == "zn-p8-workcell"
    )
    workcell["boundary"] = [
        {"x": 0.0, "z": 0.0},
        {"x": 2.1, "z": 0.0},
        {"x": 2.1, "z": 2.1},
        {"x": 0.0, "z": 2.1},
    ]
    request = deepcopy(golden["request"])
    request["strategies"] = ["compact_rows"]
    request["maximumAlternatives"] = 1
    request["zoneSizing"] = []
    request["routes"] = []

    with pytest.raises(FacilityLayoutPlanningError) as caught:
        _plan(golden, layout=layout, request=request)

    assert caught.value.code == "no_layout_alternative"
    rejected = caught.value.details["rejectedAlternatives"]
    assert rejected[0]["finding"]["code"] == "planning_region_too_small"


def test_referenced_dependency_changes_fingerprint_but_unrelated_asset_does_not(
    golden: dict,
) -> None:
    baseline = _plan(golden)
    catalog_with_unrelated = deepcopy(golden["assetDefinitions"])
    catalog_with_unrelated["asset-unrelated"] = {
        "revision": "9" * 64,
        "document": {
            "assetId": "asset-unrelated",
            "category": "tool",
            "geometry": {
                "footprintPolygons": [
                    [
                        {"x": -0.1, "z": -0.1},
                        {"x": 0.1, "z": -0.1},
                        {"x": 0.1, "z": 0.1},
                        {"x": -0.1, "z": 0.1},
                    ]
                ],
                "heightInterval": {"minimumY": 0.0, "maximumY": 0.2},
            },
            "collision": {
                "geometry": {"footprintIndex": 0},
                "verticalInterval": {"minimumY": 0.0, "maximumY": 0.2},
            },
        },
    }
    unrelated = _plan(golden, asset_definitions=catalog_with_unrelated)
    assert unrelated["dependencyFingerprint"] == baseline["dependencyFingerprint"]
    assert unrelated["selectedAlternativeId"] == baseline["selectedAlternativeId"]

    changed_catalog = deepcopy(golden["assetDefinitions"])
    changed_request = deepcopy(golden["request"])
    changed_revision = "3" * 64
    changed_catalog["asset-machine-p8"]["revision"] = changed_revision
    for item in changed_request["assetSet"]:
        if item["assetId"] == "asset-machine-p8":
            item["assetDefinitionRevision"] = changed_revision
    changed = _plan(
        golden,
        request=changed_request,
        asset_definitions=changed_catalog,
    )
    assert changed["dependencyFingerprint"] != baseline["dependencyFingerprint"]
    assert changed["selectedAlternativeId"] != baseline["selectedAlternativeId"]


def test_stale_asset_revision_fails_before_candidate_generation(
    golden: dict,
) -> None:
    request = deepcopy(golden["request"])
    request["assetSet"][0]["assetDefinitionRevision"] = "f" * 64
    with pytest.raises(FacilityLayoutPlanningError) as caught:
        _plan(golden, request=request)
    assert caught.value.code == "stale_asset_definition_revision"


def test_canonical_fingerprints_are_order_stable() -> None:
    left = {"z": [3, {"b": 2, "a": 1}], "a": "value"}
    right = {"a": "value", "z": [3, {"a": 1, "b": 2}]}
    assert canonical_planner_bytes(left) == canonical_planner_bytes(right)
    assert planner_fingerprint(left) == planner_fingerprint(right)


def test_hash_seed_does_not_change_planner_output() -> None:
    script = r"""
import json
from pathlib import Path
from ai_inspector.facility_layout.planner import (
    canonical_planner_bytes,
    generate_layout_proposals,
    planner_fingerprint,
)
fixture = json.loads(Path(
    "tests/fixtures/facility_layout/planning/p8-planning-golden.json"
).read_text(encoding="ascii"))
result = generate_layout_proposals(
    fixture["baseLayout"],
    fixture["request"],
    fixture["assetDefinitions"],
    vehicle_profiles=fixture["vehicleProfiles"],
)
print(planner_fingerprint(result))
"""
    fingerprints = []
    for seed in ("1", "7", "8675309"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        fingerprints.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                cwd=Path(__file__).parent.parent,
                env=environment,
                text=True,
            ).strip()
        )
    assert len(set(fingerprints)) == 1


def test_same_inputs_return_byte_identical_proposals(golden: dict) -> None:
    first = _plan(golden)
    second = _plan(golden)
    assert canonical_planner_bytes(first) == canonical_planner_bytes(second)
    assert first["selectedAlternativeId"] == second["selectedAlternativeId"]
    assert first["alternatives"][0]["operationReceipt"]["diffHash"] == (
        second["alternatives"][0]["operationReceipt"]["diffHash"]
    )
    assert first["layoutRevision"] == layout_revision(golden["baseLayout"])
