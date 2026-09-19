from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

import pytest
from shapely.geometry import LineString

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    layout_revision,
)
from ai_inspector.facility_layout.feature_flags import (
    FACILITY_ALL_FEATURE_FLAGS,
    FACILITY_LAYOUT_FEATURE_FLAGS,
    FACILITY_NAVIGATION_CAPABILITY_FLAGS,
    FACILITY_NAVIGATION_FEATURE_FLAGS,
    FacilityLayoutFeatureFlags,
)
from ai_inspector.facility_layout.journey_planning import (
    plan_pedestrian_journey,
)
from ai_inspector.facility_layout.navigation_compiler import (
    compile_navigation_snapshot,
)
from ai_inspector.facility_layout.navigation_geometry import (
    NAVIGATION_GEOMETRY_GRID_METERS,
    geometry_from_canonical_polygons,
)
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
)
from ai_inspector.facility_layout.repository import FacilityLayoutRepository
from ai_inspector.facility_layout.service import FacilityLayoutService


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "two_asset_cell.json"
)
SHELL_REVISION = "a" * 64
POLICY_REVISION = "d" * 64
PROFILE_REVISION = "e" * 64
NAVIGATION_FIXTURES = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "navigation"
)
REFERENCE_ARCHIVE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
REFERENCE_SHA256 = (
    "a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088"
)


def _rectangle(x0: float, z0: float, x1: float, z1: float):
    return [
        {"x": x0, "z": z0},
        {"x": x1, "z": z0},
        {"x": x1, "z": z1},
        {"x": x0, "z": z1},
    ]


def _asset(asset_id: str, revision: str, half_x: float, half_z: float):
    return {
        "assetId": asset_id,
        "assetDefinitionRevision": revision,
        "category": "machine",
        "geometry": {
            "heightInterval": {"minimumY": 0, "maximumY": 2},
            "aabb": {
                "minimum": {"x": -half_x, "y": 0, "z": -half_z},
                "maximum": {"x": half_x, "y": 2, "z": half_z},
            },
            "footprintPolygons": [[
                {"x": -half_x, "z": -half_z},
                {"x": half_x, "z": -half_z},
                {"x": half_x, "z": half_z},
                {"x": -half_x, "z": half_z},
            ]],
        },
    }


def _navigation(home_z: float, work_z: float):
    return {
        "schemaVersion": 1,
        "anchors": [
            {
                "navigationAnchorId": "na-home",
                "anchorKind": "actor_home",
                "ownerRef": {
                    "ownerKind": "placement",
                    "ownerId": "pl-machine-01",
                },
                "interactionKind": "none",
                "positionAuthority": "ui_authored",
                "localPosition": {"x": 1.0, "z": home_z},
                "derivedPositionRef": None,
                "approachDirections": ["any"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "authored",
                "evidence": ["ev-nav9-pointer"],
                "reviewStatus": "pending",
            },
            {
                "navigationAnchorId": "na-work",
                "anchorKind": "station_operate",
                "ownerRef": {
                    "ownerKind": "placement",
                    "ownerId": "pl-workstation-01",
                },
                "interactionKind": "operate",
                "positionAuthority": "ui_authored",
                "localPosition": {"x": 11.0, "z": work_z},
                "derivedPositionRef": None,
                "approachDirections": ["any"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "authored",
                "evidence": ["ev-nav9-pointer"],
                "reviewStatus": "pending",
            },
        ],
        "movementPrograms": [{
            "movementProgramId": "nmp-random-cycle",
            "actorPlacementId": "pl-machine-01",
            "actorClass": "pedestrian",
            "actorProfileRef": {
                "profileKind": "pedestrian",
                "profileId": "operator-profile-nav9",
                "profileRevision": PROFILE_REVISION,
            },
            "orderedStops": [
                {
                    "stopId": "nst-home",
                    "navigationAnchorId": "na-home",
                    "interactionKind": "none",
                    "required": True,
                },
                {
                    "stopId": "nst-work",
                    "navigationAnchorId": "na-work",
                    "interactionKind": "operate",
                    "required": True,
                },
            ],
            "loopMode": "out_and_return",
            "requiredRouteIds": [],
            "requiredAnchorIds": ["na-home", "na-work"],
            "forbiddenZoneIds": [],
            "forbiddenRouteIds": [],
            "manualPathConstraintIds": [],
            "handoffProgramIds": [],
            "sourceRevisions": {"layout": "2" * 64},
            "evidenceStatus": "authored",
            "evidence": ["ev-nav9-program"],
            "reviewStatus": "pending",
        }],
        "manualPathConstraints": [],
        "handoffPrograms": [],
    }


def _case(seed: int, *, disconnected: bool = False):
    rng = random.Random(seed)
    layout = json.loads(FIXTURE.read_text(encoding="ascii"))
    top_left = round(rng.uniform(7.0, 9.0), 3)
    left_height = round(rng.uniform(7.2, 8.0), 3)
    boundary = [
        {"x": 0.0, "z": 0.0},
        {"x": 12.0, "z": 0.0},
        {"x": 12.0, "z": 8.0},
        {"x": top_left, "z": 8.0},
        {"x": 0.0, "z": left_height},
    ]
    layout["zones"][0]["boundary"] = deepcopy(boundary)
    layout["routes"] = []
    layout["floorMarkings"] = []
    layout.setdefault("extensions", {})["facilityNavigation"] = _navigation(
        round(rng.uniform(0.9, 6.3), 3),
        round(rng.uniform(0.9, 6.3), 3),
    )
    layout["placements"][0]["transform"]["position"].update({
        "x": round(rng.uniform(1.5, 2.5), 3),
        "z": round(rng.uniform(2.0, 6.0), 3),
    })
    layout["placements"][1]["transform"]["position"].update({
        "x": round(rng.uniform(5.2, 6.8), 3),
        "z": 4.0,
    })
    obstacle_half_x = round(rng.uniform(0.3, 0.9), 3)
    obstacle_half_z = 5.0 if disconnected else round(
        rng.uniform(0.4, 1.25), 3
    )
    shell = {
        "features": [{
            "featureId": "floor-nav9",
            "featureKind": "floor_surface",
            "geometry": {"boundary": deepcopy(boundary)},
        }]
    }
    assets = {
        ("asset-machine-01", PROFILE_REVISION): _asset(
            "asset-machine-01", PROFILE_REVISION, 0.25, 0.25
        ),
        ("asset-workstation-01", "f" * 64): _asset(
            "asset-workstation-01", "f" * 64,
            obstacle_half_x, obstacle_half_z,
        ),
    }
    return layout, shell, assets


def _compile(layout, shell, assets):
    return compile_navigation_snapshot(
        layout,
        shell=shell,
        asset_definitions=assets,
        actor_class="pedestrian",
        actor_profile_revision=PROFILE_REVISION,
        navigation_radius_meters=0.35,
        shell_revision=SHELL_REVISION,
        policy_revision=POLICY_REVISION,
    )


def test_nav9_one_hundred_seeded_routes_are_exactly_contained_and_clear():
    accepted = 0
    for seed in range(100):
        layout, shell, assets = _case(seed)
        package = _compile(layout, shell, assets)
        journey = plan_pedestrian_journey(
            layout, package, "nmp-random-cycle"
        )
        assert journey["outcome"] == "accepted", seed
        line = LineString([
            (point["x"], point["z"])
            for point in journey["centerline"]
        ])
        free_space = geometry_from_canonical_polygons(
            package["freeSpacePolygons"]
        )
        obstacles = geometry_from_canonical_polygons(
            package["expandedObstaclePolygons"]
        )
        source_obstacles = geometry_from_canonical_polygons(
            package["sourceObstaclePolygons"]
        )
        assert free_space.covers(line), seed
        assert not line.intersects(source_obstacles), seed
        # Canonical path and polygon coordinates are rounded to the frozen
        # one-micrometre grid. Boundary-following paths may therefore land by
        # one grid unit on either side of the pre-rounding curve.
        obstacle_interior = obstacles.buffer(
            -2 * NAVIGATION_GEOMETRY_GRID_METERS
        )
        assert obstacle_interior.is_empty or not line.intersects(
            obstacle_interior
        ), seed
        accepted += 1
    assert accepted == 100


@pytest.mark.parametrize("seed", range(5))
def test_nav9_disconnected_components_return_stable_unreachable(seed: int):
    layout, shell, assets = _case(seed, disconnected=True)
    package = _compile(layout, shell, assets)
    first = plan_pedestrian_journey(layout, package, "nmp-random-cycle")
    second = plan_pedestrian_journey(layout, package, "nmp-random-cycle")
    assert first == second
    assert first["outcome"] == "unreachable"
    assert first["centerline"] == []
    assert first["validation"]["topology"] == "refused"


def test_nav9_navigation_feature_chain_cannot_skip_a_stage():
    base = set(FACILITY_LAYOUT_FEATURE_FLAGS)
    capabilities = tuple(FACILITY_NAVIGATION_CAPABILITY_FLAGS)
    for index, flag in enumerate(FACILITY_NAVIGATION_FEATURE_FLAGS):
        enabled = base | set(FACILITY_NAVIGATION_FEATURE_FLAGS[: index + 1])
        flags = FacilityLayoutFeatureFlags.from_environment({
            item: "1" if item in enabled else "0"
            for item in FACILITY_ALL_FEATURE_FLAGS
        })
        assert flags.enabled(capabilities[index])
        if index + 1 < len(capabilities):
            enabled.add(FACILITY_NAVIGATION_FEATURE_FLAGS[index + 1])
            enabled.remove(flag)
            skipped = FacilityLayoutFeatureFlags.from_environment({
                item: "1" if item in enabled else "0"
                for item in FACILITY_ALL_FEATURE_FLAGS
            })
            assert not skipped.enabled(capabilities[index + 1])


def test_nav9_legacy_rectangle_loop_is_test_fixture_only(monkeypatch):
    service = object.__new__(FacilityLayoutService)
    service.allow_legacy_lean_motion_fixture = False

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy rectangle-loop builder was reached")

    monkeypatch.setattr(
        "ai_inspector.facility_layout.service.derive_facility_lean_motion_blueprint",
        forbidden,
    )
    with pytest.raises(FacilityValidationError) as caught:
        service.build_prototype_activity_scenario(
            None, "site-a", "layout-a", "r" * 64, {}
        )
    assert caught.value.code == "facility_legacy_navigation_fixture_only"


def test_nav9_saved_navigation_reopens_byte_equivalently(tmp_path: Path):
    layout, _shell, _assets = _case(77)
    navigation = deepcopy(layout["extensions"].pop("facilityNavigation"))
    if not layout["extensions"]:
        layout.pop("extensions")

    principal = FacilityPrincipal(
        principal_id="nav9-reviewer",
        tenant_id="tenant-nav9",
        allowed_site_ids=("site-a",),
        roles=("editor",),
    )
    repository = FacilityLayoutRepository(tmp_path / "navigation-store")
    created = repository.create_layout(principal, "site-a", layout)
    draft = apply_facility_layout_operations(
        created["layout"],
        [{
            "op": "set_facility_navigation",
            "authoringSource": "plan_pointer",
            "facilityNavigation": navigation,
        }],
        base_revision=created["revision"],
    )["document"]
    assert layout_revision(draft) != created["revision"]

    saved = repository.save_layout(
        principal,
        "site-a",
        layout["layoutId"],
        draft,
        created["revision"],
    )
    reopened = FacilityLayoutRepository(
        repository.root
    ).get_layout(principal, "site-a", layout["layoutId"])

    assert reopened["revision"] == saved["revision"]
    assert canonical_layout_bytes(reopened["layout"]) == (
        canonical_layout_bytes(saved["layout"])
    )
    assert reopened["layout"]["extensions"]["facilityNavigation"] == navigation


def test_nav9_frozen_performance_evidence_passes_every_budget():
    evidence = json.loads((
        NAVIGATION_FIXTURES / "nav9-performance-v1.json"
    ).read_text(encoding="ascii"))
    assert evidence["schemaVersion"] == (
        "facility-navigation-nav9-performance-v1"
    )
    assert evidence["status"] == "pass"
    assert evidence["protocol"]["measuredRuns"] == 20
    assert evidence["reference"]["layoutRevision"] == REFERENCE_SHA256
    assert evidence["resultChecks"]["scenarioActorCount"] == 16
    assert evidence["resultChecks"]["scenarioProcessTimingClaimed"] is False
    assert evidence["resultChecks"][
        "scenarioGeneratedCollisionAvoidanceOffsets"
    ] is False
    for measurement in evidence["measurements"].values():
        assert measurement["sampleCount"] == 20
        assert measurement["p95Milliseconds"] <= measurement[
            "limitMilliseconds"
        ]
        assert measurement["passed"] is True


def test_nav9_reference_candidates_are_complete_without_granting_approval():
    evidence = json.loads((
        NAVIGATION_FIXTURES / "nav9-reference-acceptance-v1.json"
    ).read_text(encoding="ascii"))
    assert evidence["status"] == "promotion_held_review_pending"
    assert evidence["source"]["layoutRevision"] == REFERENCE_SHA256
    assert evidence["counts"] == {
        "handoffCandidates": 7,
        "omittedCandidateCases": 0,
        "operatorCandidates": 12,
        "reviewedHandoffs": 0,
        "reviewedOperatorCycles": 0,
        "reviewedVehicles": 0,
        "vehicleCandidates": 4,
    }
    assert all(
        item["technicalChecks"][
            "candidateCenterlineInsideCandidateBoundary"
        ]
        for item in evidence["operatorCandidates"]
    )
    assert all(
        item["code"] == "facility_navigation_vehicle_profile_unavailable"
        for item in evidence["vehicleCandidates"]
    )
    assert evidence["scenario"]["built"] is False
    assert evidence["promotion"]["eligible"] is False
    assert hashlib.sha256(REFERENCE_ARCHIVE.read_bytes()).hexdigest() == (
        REFERENCE_SHA256
    )


def test_nav9_browser_evidence_proves_exact_read_only_playback():
    evidence_path = (
        NAVIGATION_FIXTURES / "browser" / "nav9-browser-evidence-v1.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="ascii"))

    assert evidence["schemaVersion"] == (
        "facility-navigation-nav9-browser-evidence-v1"
    )
    assert evidence["referenceSha256Before"] == REFERENCE_SHA256
    assert evidence["referenceSha256After"] == REFERENCE_SHA256
    assert evidence["checks"]
    assert all(evidence["checks"].values())
    assert evidence["activity"]["plannerOutcome"] == "accepted"
    assert evidence["activity"]["acceptedJourneyCount"] == 1
    assert evidence["activity"]["actorCount"] == 1
    assert evidence["playback"]["durationSeconds"] == 60
    assert evidence["playback"]["renderedFrames"] >= 1_800
    assert evidence["playback"]["framesPerSecond"] >= 30
    assert "D3D11" in evidence["playback"]["graphics"]["renderer"]
    assert len(evidence["captures"]) == 8
    for capture in evidence["captures"]:
        assert capture["poseAgreement"] is True
        assert capture["surfacePixels"]["nonblank"] is True
        assert (ROOT / capture["fullScreenshot"]).is_file()
        assert (ROOT / capture["surfaceScreenshot"]).is_file()
