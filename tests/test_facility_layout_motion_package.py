from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

import ai_inspector.facility_layout.motion_package as motion_package_module
from ai_inspector.facility_layout.motion_package import (
    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION,
    FacilityMotionPackageError,
    FacilityMotionPackageStore,
    build_facility_motion_package,
    canonical_facility_motion_package_bytes,
    sample_motion_at_distance,
    sample_motion_at_time,
    validate_facility_motion_package,
)
from ai_inspector.facility_layout.routing import plan_forklift_route


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "routing"
    / "p7-routing-goldens.json"
)


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _accepted_result():
    fixture = _fixture()
    case = fixture["scenarios"][0]
    result = plan_forklift_route(
        case["start"],
        case["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=case["traversablePolygons"],
        allow_reverse=case.get("allowReverse"),
        source_revisions=fixture["sourceRevisions"],
    )
    return fixture, result


def _build(result=None, *, layout=None, vehicle_placement_id=None, generated_at=None):
    fixture, accepted = _accepted_result()
    result = result or accepted
    return build_facility_motion_package(
        result,
        layout=layout or {"placements": []},
        layout_revision=fixture["sourceRevisions"]["layout"],
        obstacle_context_revision="context-revision-one",
        route_id="route-main",
        vehicle_profile_ref={
            "vehicleProfileId": fixture["vehicleProfile"]["vehicleProfileId"],
            "vehicleProfileRevision": fixture["vehicleProfile"][
                "vehicleProfileRevision"
            ],
        },
        vehicle_placement_id=vehicle_placement_id,
        generated_at=generated_at,
    )


def test_accepted_package_is_reproducible_and_preserves_planner_evidence():
    _, result = _accepted_result()
    first = _build(result, generated_at="2026-08-30T01:00:00Z")
    second = _build(result, generated_at="2026-08-30T02:00:00Z")

    assert first["package"] == second["package"]
    assert first["facilityMotionEnvelope"] != second["facilityMotionEnvelope"]
    movement = first["package"]["movement"]
    assert first["package"]["schemaVersion"] == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION
    assert movement["outcome"] == "accepted"
    assert movement["routeFingerprint"] == result["routeFingerprint"]
    assert movement["distanceMeters"] == result["distanceMeters"]
    assert len(movement["poses"]) == len(result["poses"])
    assert movement["cumulativeDistance"][-1] == result["distanceMeters"]
    assert len(movement["clearance"]["samples"]) == result["sweptVolume"][
        "sampledPoseCount"
    ]
    assert first["summary"]["packageId"] == first["package"]["packageId"]
    assert "poses" not in first["summary"]
    assert "clearance" not in first["summary"]


def test_real_vehicle_resolves_carried_placements_and_proxy_carries_none():
    layout = {
        "placements": [
            {"placementId": "vehicle-one", "snapRelationship": None},
            {
                "placementId": "pallet-one",
                "snapRelationship": {"supportPlacementId": "vehicle-one"},
            },
            {
                "placementId": "pallet-two",
                "snapRelationship": {"supportPlacementId": "vehicle-one"},
            },
        ]
    }
    proxy = _build(layout=layout)["package"]["movement"]
    placed = _build(
        layout=layout,
        vehicle_placement_id="vehicle-one",
    )["package"]["movement"]

    assert "vehiclePlacementId" not in proxy
    assert proxy["carriedPlacementIds"] == []
    assert placed["vehiclePlacementId"] == "vehicle-one"
    assert placed["carriedPlacementIds"] == ["pallet-one", "pallet-two"]


def test_unroutable_package_has_no_trajectory_or_fingerprint():
    fixture = _fixture()
    result = plan_forklift_route(
        {"x": 0, "z": 0, "heading": 0},
        {"x": 5, "z": 0, "heading": 0},
        fixture["vehicleProfile"],
        traversable_polygons=[],
        source_revisions=fixture["sourceRevisions"],
    )
    package = _build(result)["package"]

    assert package["movement"]["outcome"] == "unroutable"
    assert set(package["movement"]) == {
        "outcome",
        "movementId",
        "routeId",
        "vehicleProfileRef",
        "findings",
    }


def test_envelope_refusal_serializes_only_to_the_blocking_distance():
    _, accepted = _accepted_result()
    refused = deepcopy(accepted)
    refused.update(
        {
            "accepted": False,
            "outcome": "envelope_refused",
            "routeFingerprint": None,
            "attemptFingerprint": "attempt-one",
            "findings": [
                {
                    "findingId": "finding-one",
                    "severity": "error",
                    "code": "route_swept_volume_collision",
                    "message": "Blocked.",
                    "subjects": ["obstacle-one"],
                }
            ],
        }
    )
    refused["sweptVolume"] = deepcopy(accepted["sweptVolume"])
    refused["sweptVolume"]["valid"] = False
    refused["sweptVolume"]["findings"] = deepcopy(refused["findings"])
    refused["sweptVolume"]["blocking"] = {
        "localized": True,
        "blockingSampleIndex": 20,
        "blockingPose": {"x": 3, "z": 2, "heading": 0, "gear": "forward"},
        "blockingDistanceMeters": 2,
        "blockingObstacleIds": ["obstacle-one"],
    }

    movement = _build(refused)["package"]["movement"]
    assert movement["outcome"] == "envelope_refused"
    assert movement["attemptFingerprint"] == "attempt-one"
    assert "routeFingerprint" not in movement
    assert movement["cumulativeDistance"][-1] == 2
    assert movement["attemptedPoses"][-1] == {
        "x": 3.0,
        "z": 2.0,
        "heading": 0.0,
        "gear": "forward",
    }


def test_unknown_fields_and_wrong_package_id_fail_closed():
    package = _build()["package"]
    unknown = deepcopy(package)
    unknown["modelAuthoredPose"] = {"x": 9, "z": 9}
    with pytest.raises(FacilityMotionPackageError) as exc:
        validate_facility_motion_package(unknown)
    assert exc.value.code == "facility_motion_package_unknown_field"

    changed = deepcopy(package)
    changed["layoutRevision"] = "changed"
    with pytest.raises(FacilityMotionPackageError) as exc:
        canonical_facility_motion_package_bytes(changed)
    assert exc.value.code == "facility_motion_package_id_mismatch"


def test_canonical_byte_budget_has_exact_global_boundaries(monkeypatch):
    package = _build()["package"]
    canonical_size = len(canonical_facility_motion_package_bytes(package))

    monkeypatch.setattr(
        motion_package_module,
        "FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES",
        canonical_size - 1,
    )
    with pytest.raises(FacilityMotionPackageError) as exc:
        canonical_facility_motion_package_bytes(package)
    assert exc.value.code == "facility_motion_package_too_large"
    assert exc.value.details == {
        "canonicalBytes": canonical_size,
        "maximumCanonicalBytes": canonical_size - 1,
    }

    monkeypatch.setattr(
        motion_package_module,
        "FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES",
        canonical_size,
    )
    assert len(canonical_facility_motion_package_bytes(package)) == canonical_size

    monkeypatch.setattr(
        motion_package_module,
        "FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES",
        canonical_size + 1,
    )
    assert len(canonical_facility_motion_package_bytes(package)) == canonical_size


def test_arc_length_sampler_uses_shortest_heading_arc_and_lower_gear():
    movement = {
        "outcome": "accepted",
        "poses": [
            {"x": 0, "z": 0, "heading": math.pi - 0.1, "gear": "reverse"},
            {"x": 10, "z": 0, "heading": -math.pi + 0.1, "gear": "forward"},
        ],
        "cumulativeDistance": [0, 10],
        "distanceMeters": 10,
        "plannerDurationEstimateSeconds": 5,
    }
    midpoint = sample_motion_at_distance(movement, 5)
    timed = sample_motion_at_time(movement, 2.5)

    assert {key: value for key, value in timed.items() if key != "timeSeconds"} == midpoint
    assert math.isclose(abs(midpoint["heading"]), math.pi)
    assert midpoint["gear"] == "reverse"
    assert sample_motion_at_time(movement, 0)["x"] == 0
    assert sample_motion_at_time(movement, 5)["x"] == 10


def test_package_store_is_bounded_and_expires():
    now = [0.0]
    store = FacilityMotionPackageStore(
        ttl_seconds=5,
        maximum_entries=1,
        clock=lambda: now[0],
    )
    store.put("one", {"value": 1})
    store.put("two", {"value": 2})
    with pytest.raises(Exception) as exc:
        store.get("one")
    assert getattr(exc.value, "code", None) == "facility_motion_package_not_found"
    assert store.get("two") == {"value": 2}
    now[0] = 6
    with pytest.raises(Exception) as exc:
        store.get("two")
    assert getattr(exc.value, "code", None) == "facility_motion_package_not_found"
