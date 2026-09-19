from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import ai_inspector.facility_layout.activity_artifact_cache as cache_module
from ai_inspector.facility_layout.activity_artifact_cache import (
    FacilityActivityScenarioArtifactCache,
)
from ai_inspector.facility_layout.activity_scenario import (
    build_facility_activity_scenario,
)
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.motion_package import (
    build_facility_motion_package,
)
from ai_inspector.facility_layout.routing import plan_forklift_route


ROUTING_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "routing"
    / "p7-routing-goldens.json"
)


def _cache_fixture() -> tuple[dict, dict]:
    routing = json.loads(ROUTING_FIXTURE.read_text(encoding="utf-8"))
    route_case = routing["scenarios"][0]
    layout_revision = "a" * 64
    route_result = plan_forklift_route(
        route_case["start"],
        route_case["goal"],
        routing["vehicleProfile"],
        traversable_polygons=route_case["traversablePolygons"],
        allow_reverse=route_case.get("allowReverse"),
        source_revisions={
            **routing["sourceRevisions"],
            "layout": layout_revision,
        },
    )
    placement_id = "pl-cache-vehicle"
    built = build_facility_motion_package(
        route_result,
        layout={
            "placements": [
                {
                    "placementId": placement_id,
                    "snapRelationship": None,
                }
            ]
        },
        layout_revision=layout_revision,
        obstacle_context_revision="cache-obstacle-context",
        route_id="rt-cache-route",
        vehicle_profile_ref={
            "vehicleProfileId": routing["vehicleProfile"]["vehicleProfileId"],
            "vehicleProfileRevision": routing["vehicleProfile"][
                "vehicleProfileRevision"
            ],
        },
        vehicle_placement_id=placement_id,
        generated_at="2026-09-05T00:00:00Z",
    )
    package_id = built["package"]["packageId"]
    actor = {
        "actorId": "actor-cache-vehicle",
        "actorType": "vehicle",
        "label": "Cached vehicle",
        "motionPackageId": package_id,
        "returnMotionPackageId": None,
        "endTransferMotionPackageId": None,
        "startTransferMotionPackageId": None,
        "cycleMotionPackageIds": [],
        "placementId": placement_id,
        "assetDefinitionRef": {
            "assetId": "asset-cache-vehicle",
            "assetDefinitionRevision": "b" * 64,
        },
        "routeId": "rt-cache-route",
        "departmentZoneIds": ["zn-cache"],
        "startOffsetSeconds": 0.0,
        "repeat": True,
        "loopMode": "ping_pong",
        "endpointTurnSeconds": 1.0,
        "visualAlignment": {
            "forwardAxis": "+X",
            "authority": "curated_revision_bound_visual_review",
            "evidenceArtifact": "tests/fixtures/cache-vehicle.glb",
        },
    }
    scenario = build_facility_activity_scenario(
        layout_revision=layout_revision,
        label="Cached activity scenario",
        actors=[actor],
        cycle_duration_seconds=30,
        stationary_evidence={
            "placementCount": 0,
            "assetTypeCount": 0,
            "reason": "No stationary evidence in this cache fixture.",
            "evidenceStatus": "unknown",
        },
    )
    key = {
        "tenantId": "tenant-a",
        "siteId": "site-a",
        "layoutId": "fl-cache",
        "layoutRevision": layout_revision,
        "preset": "reference_complete_navigation",
        "compilerRevision": "reference-complete-navigation-v1",
        "maximumActors": 1,
    }
    payload = {
        "tenantId": "tenant-a",
        "siteId": "site-a",
        "layoutId": "fl-cache",
        "layoutRevision": layout_revision,
        "scenario": scenario,
        "actorPayloads": {package_id: built},
        "candidatePresentation": {
            "sourceLayoutId": "fl-cache",
            "sourceLayoutRevision": layout_revision,
            "candidateCounts": {"displayedActors": 1},
        },
    }
    return key, payload


def test_activity_artifact_cache_survives_a_new_store_instance(tmp_path):
    key, payload = _cache_fixture()
    root = tmp_path / "activity-cache"

    first = FacilityActivityScenarioArtifactCache(root)
    path = first.put(key, payload)
    second = FacilityActivityScenarioArtifactCache(root)
    restored = second.get(key)

    assert path.is_file()
    assert restored == payload
    assert restored is not payload


def test_activity_artifact_cache_fails_closed_on_revision_or_byte_tampering(
    tmp_path,
):
    key, payload = _cache_fixture()
    cache = FacilityActivityScenarioArtifactCache(tmp_path / "activity-cache")
    path = cache.put(key, payload)

    stale_key = {**key, "layoutRevision": "c" * 64}
    assert cache.get(stale_key) is None
    newer_compiler_key = {
        **key,
        "compilerRevision": "reference-complete-navigation-v2",
    }
    assert cache.get(newer_compiler_key) is None

    artifact = json.loads(path.read_text(encoding="ascii"))
    artifact["payload"]["scenario"]["label"] = "Tampered"
    path.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")),
        encoding="ascii",
    )
    assert cache.get(key) is None


def test_activity_artifact_cache_enforces_its_canonical_byte_ceiling(
    tmp_path,
    monkeypatch,
):
    key, payload = _cache_fixture()
    cache = FacilityActivityScenarioArtifactCache(tmp_path / "activity-cache")
    path = cache.put(key, payload)
    canonical_size = path.stat().st_size
    path.unlink()
    monkeypatch.setattr(
        cache_module,
        "FACILITY_ACTIVITY_ARTIFACT_MAXIMUM_CANONICAL_BYTES",
        canonical_size - 1,
    )

    with pytest.raises(FacilityValidationError) as caught:
        cache.put(key, deepcopy(payload))

    assert caught.value.code == "facility_activity_artifact_too_large"
    assert caught.value.details == {
        "canonicalBytes": canonical_size,
        "maximumCanonicalBytes": canonical_size - 1,
    }
