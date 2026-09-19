from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import (
    canonicalize_layout,
    layout_revision,
)
from ai_inspector.facility_layout.motion_package import (
    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2,
    FacilityMotionPackageError,
    build_facility_motion_package_v2,
    validate_facility_motion_package,
    validate_facility_motion_package_for_playback,
)
from ai_inspector.facility_layout.motion_validation_context import (
    FacilityMotionValidationContextError,
    build_motion_validation_context_projection,
    build_motion_validation_context_spec,
    motion_validation_context_fingerprint,
)
from ai_inspector.facility_layout.navigation_contract import (
    FACILITY_NAVIGATION_JOURNEY_SCHEMA,
    FACILITY_NAVIGATION_SCHEMA_VERSION,
    FACILITY_NAVIGATION_SNAPSHOT_SCHEMA,
    FacilityNavigationContractError,
    build_navigation_sage_summary,
    navigation_contract_manifest,
    navigation_field_mapping_matrix,
    navigation_identity_index,
    navigation_sage_contract,
    seal_journey_solution,
    seal_navigation_snapshot,
    validate_facility_navigation_extension,
    validate_navigation_writer_authority,
)
from ai_inspector.facility_layout.routing import plan_forklift_route
from ai_inspector.facility_layout.validate import validate_layout


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "facility_layout"
ROUTING_FIXTURE = FIXTURES / "routing" / "p7-routing-goldens.json"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def _extension(*, manual: bool = False, inferred: bool = False) -> dict:
    if inferred:
        position_authority = "inferred"
        local_position = None
        derived_ref = {
            "sourceKind": "placement_transform",
            "sourceId": "pl-machine-01",
            "sourceRevision": "e" * 64,
        }
        evidence_status = "inferred"
    else:
        position_authority = "ui_authored"
        local_position = {"x": 4.0000004, "z": 4.0}
        derived_ref = None
        evidence_status = "authored"
    extension = {
        "schemaVersion": FACILITY_NAVIGATION_SCHEMA_VERSION,
        "anchors": [
            {
                "navigationAnchorId": "na-machine-home",
                "anchorKind": "actor_home",
                "ownerRef": {
                    "ownerKind": "placement",
                    "ownerId": "pl-machine-01",
                },
                "interactionKind": "none",
                "positionAuthority": position_authority,
                "localPosition": local_position,
                "derivedPositionRef": derived_ref,
                "approachDirections": ["south", "north"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": evidence_status,
                "evidence": ["ev-machine-home"],
                "reviewStatus": "pending",
            }
        ],
        "movementPrograms": [
            {
                "movementProgramId": "nmp-machine-cycle",
                "actorPlacementId": "pl-machine-01",
                "actorClass": "pedestrian",
                "actorProfileRef": {
                    "profileKind": "pedestrian",
                    "profileId": "operator-profile-standard",
                    "profileRevision": "1" * 64,
                },
                "orderedStops": [
                    {
                        "stopId": "nst-machine-home",
                        "navigationAnchorId": "na-machine-home",
                        "interactionKind": "none",
                        "required": True,
                    }
                ],
                "loopMode": "closed_loop",
                "requiredRouteIds": [],
                "requiredAnchorIds": ["na-machine-home"],
                "forbiddenZoneIds": [],
                "forbiddenRouteIds": [],
                "manualPathConstraintIds": (
                    ["nmc-machine-guide"] if manual else []
                ),
                "handoffProgramIds": [],
                "sourceRevisions": {"layout": "2" * 64},
                "evidenceStatus": evidence_status,
                "evidence": ["ev-machine-cycle"],
                "reviewStatus": "pending",
            }
        ],
        "manualPathConstraints": [],
        "handoffPrograms": [],
    }
    if manual:
        extension["manualPathConstraints"] = [
            {
                "manualPathConstraintId": "nmc-machine-guide",
                "movementProgramId": "nmp-machine-cycle",
                "constraintMode": "guide",
                "authoredPolyline": [
                    {"x": 4.0, "z": 4.0},
                    {"x": 6.0, "z": 4.0},
                ],
                "snapRefs": [
                    {
                        "pointIndex": 0,
                        "refKind": "navigation_anchor",
                        "refId": "na-machine-home",
                    }
                ],
                "lockedSegmentIndexes": [],
                "direction": "bidirectional",
                "positionAuthority": "ui_authored",
                "evidenceStatus": "authored",
                "evidence": ["ev-machine-guide"],
                "reviewStatus": "pending",
            }
        ]
    return extension


def _layout_with_navigation(*, manual: bool = False) -> dict:
    layout = _load("two_asset_cell.json")
    layout["extensions"] = {"facilityNavigation": _extension(manual=manual)}
    return layout


def _motion_layout() -> dict:
    return {
        "sourceShellRef": {
            "shellId": "shell-nav1",
            "shellRevision": "a" * 64,
        },
        "policySetRef": {
            "policySetId": "policy-nav1",
            "policySetRevision": "d" * 64,
        },
        "catalogSnapshotRevision": "c" * 64,
        "placements": [
            {
                "placementId": "vehicle-one",
                "assetId": "asset-forklift",
                "assetDefinitionRevision": "e" * 64,
                "transform": {
                    "position": {"x": 0, "y": 0, "z": 0},
                    "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                    "scale": 1,
                },
            },
            {
                "placementId": "machine-far",
                "assetId": "asset-machine",
                "assetDefinitionRevision": "f" * 64,
                "transform": {
                    "position": {"x": 100, "y": 0, "z": 100},
                    "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                    "scale": 1,
                },
            },
        ],
        "zones": [],
        "floorMarkings": [
            {"markingId": "fm-lane-one", "semanticRole": "direction_arrow"}
        ],
        "routes": [
            {
                "routeId": "route-main",
                "routeKind": "material",
                "sourceEndpoint": {"kind": "world_point", "position": {"x": 0, "z": 0}},
                "targetEndpoint": {"kind": "world_point", "position": {"x": 10, "z": 0}},
                "centerline": [{"x": 0, "z": 0}, {"x": 10, "z": 0}],
                "corridorWidth": 4,
            }
        ],
        "processBindings": [],
        "extensions": {
            "facilityNavigation": {
                "schemaVersion": 1,
                "anchors": [],
                "movementPrograms": [],
                "manualPathConstraints": [],
                "handoffPrograms": [],
            }
        },
    }


def _profile() -> dict:
    fixture = json.loads(ROUTING_FIXTURE.read_text(encoding="utf-8"))
    return deepcopy(fixture["vehicleProfile"])


def _accepted_route_result() -> tuple[dict, dict]:
    fixture = json.loads(ROUTING_FIXTURE.read_text(encoding="utf-8"))
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


def _motion_context(layout: dict, result: dict) -> tuple[dict, dict, list[dict]]:
    profile = _profile()
    spec = build_motion_validation_context_spec(
        layout,
        route_id="route-main",
        actor_profile_ref={
            "vehicleProfileId": profile["vehicleProfileId"],
            "vehicleProfileRevision": profile["vehicleProfileRevision"],
        },
        planner_versions={
            "routingEngineVersion": str(result["routingEngineVersion"]),
            "routerVersion": str(result["routerVersion"]),
        },
        influence_bounds=result["sweptVolume"]["sweptBounds"],
        actor_placement_id="vehicle-one",
        marking_ids=["fm-lane-one"],
    )
    obstacles = [
        {
            "obstacleId": "ob-near",
            "boundary": [
                {"x": 1, "z": 1},
                {"x": 2, "z": 1},
                {"x": 2, "z": 2},
                {"x": 1, "z": 2},
            ],
        },
        {
            "obstacleId": "ob-far",
            "boundary": [
                {"x": 100, "z": 100},
                {"x": 101, "z": 100},
                {"x": 101, "z": 101},
                {"x": 100, "z": 101},
            ],
        },
    ]
    projection = build_motion_validation_context_projection(
        layout,
        spec,
        actor_profile=profile,
        obstacles=obstacles,
    )
    return spec, projection, obstacles


def test_navigation_extension_is_closed_canonical_and_revision_bearing() -> None:
    base = _load("two_asset_cell.json")
    layout = _layout_with_navigation(manual=True)

    canonical = canonicalize_layout(layout)
    validate_layout(canonical, require_canonical=True)

    navigation = canonical["extensions"]["facilityNavigation"]
    assert navigation["anchors"][0]["localPosition"] == {"x": 4, "z": 4}
    assert navigation["anchors"][0]["approachDirections"] == ["north", "south"]
    assert layout_revision(canonical) != layout_revision(base)


def test_unknown_fields_and_dangling_identities_fail_closed() -> None:
    layout = _layout_with_navigation(manual=True)
    identities = navigation_identity_index(layout)
    unknown = deepcopy(layout["extensions"]["facilityNavigation"])
    unknown["computedRoute"] = [{"x": 1, "z": 2}]
    with pytest.raises(FacilityNavigationContractError) as error:
        validate_facility_navigation_extension(unknown, identities)
    assert error.value.code == "facility_navigation_unknown_field"

    dangling = deepcopy(layout["extensions"]["facilityNavigation"])
    dangling["manualPathConstraints"][0]["snapRefs"][0]["refId"] = "na-missing"
    with pytest.raises(FacilityNavigationContractError) as error:
        validate_facility_navigation_extension(dangling, identities)
    assert error.value.code == "facility_navigation_dangling_identity"


def test_generator_cannot_self_promote_human_or_controlled_authority() -> None:
    layout = _load("two_asset_cell.json")
    identities = navigation_identity_index(layout)
    inferred = _extension(inferred=True)
    validate_navigation_writer_authority(
        inferred,
        identities,
        writer_kind="deterministic_generator",
    )

    authored = _extension()
    with pytest.raises(FacilityNavigationContractError) as error:
        validate_navigation_writer_authority(
            authored,
            identities,
            writer_kind="model",
        )
    assert error.value.code == "facility_navigation_writer_authority_forbidden"


def test_authority_and_evidence_status_cannot_disagree() -> None:
    layout = _load("two_asset_cell.json")
    extension = _extension(inferred=True)
    extension["anchors"][0]["evidenceStatus"] = "authored"
    with pytest.raises(FacilityNavigationContractError) as error:
        validate_facility_navigation_extension(
            extension,
            navigation_identity_index(layout),
        )
    assert error.value.code == "facility_navigation_authority_mismatch"


def test_snapshot_barriers_are_not_service_targets_and_artifacts_are_sealed() -> None:
    snapshot = seal_navigation_snapshot(
        {
            "layoutRevision": "1" * 64,
            "compilerVersion": "nav-compiler-v1",
            "actorClass": "pedestrian",
            "actorProfileRevision": "2" * 64,
            "walkableRegions": [
                {
                    "walkableRegionId": "walkable-one",
                    "geometryFingerprint": "3" * 64,
                    "sourceRefIds": ["zn-machine-cell"],
                }
            ],
            "obstacleRecords": [
                {
                    "obstacleRecordId": "obstacle-one",
                    "ownerRef": {
                        "sourceKind": "placement",
                        "sourceId": "pl-machine-01",
                        "sourceRevision": "4" * 64,
                    },
                    "role": "barrier",
                    "geometryFingerprint": "5" * 64,
                    "evidenceStatus": "derived",
                }
            ],
            "nodes": [
                {"nodeId": "node-a", "nodeKind": "anchor", "position": {"x": 0, "z": 0}},
                {"nodeId": "node-b", "nodeKind": "visibility", "position": {"x": 2, "z": 0}},
            ],
            "edges": [
                {
                    "edgeId": "edge-a-b",
                    "sourceNodeId": "node-a",
                    "targetNodeId": "node-b",
                    "direction": "bidirectional",
                    "costMeters": 2,
                    "evidenceStatus": "derived",
                }
            ],
            "connectedComponents": [
                {"componentId": "component-one", "nodeIds": ["node-a", "node-b"]}
            ],
            "sourceRevisions": {"layout": "1" * 64},
            "geometryContextFingerprint": "6" * 64,
        }
    )
    assert snapshot["schemaVersion"] == FACILITY_NAVIGATION_SNAPSHOT_SCHEMA
    assert snapshot["navigationSnapshotId"].startswith("nss-")

    invalid = deepcopy(snapshot)
    invalid["obstacleRecords"][0]["serviceAnchorId"] = "na-machine-home"
    invalid.pop("navigationSnapshotId")
    invalid.pop("snapshotFingerprint")
    with pytest.raises(FacilityNavigationContractError) as error:
        seal_navigation_snapshot(invalid)
    assert error.value.code == "facility_navigation_barrier_service_forbidden"


def test_closed_loop_journey_may_return_to_its_start_anchor() -> None:
    journey = seal_journey_solution(
        {
            "movementProgramId": "nmp-machine-cycle",
            "navigationSnapshotId": "nss-1234567890abcdef12345678",
            "actorPlacementId": "pl-machine-01",
            "generationLayoutRevision": "1" * 64,
            "validationContextFingerprint": "2" * 64,
            "outcome": "accepted",
            "orderedAnchorIds": ["na-home", "na-service", "na-home"],
            "networkEdgeIds": ["edge-out", "edge-return"],
            "centerline": [{"x": 0, "z": 0}, {"x": 1, "z": 0}, {"x": 0, "z": 0}],
            "poses": [
                {"x": 0, "z": 0, "heading": 0, "gear": "forward"},
                {"x": 1, "z": 0, "heading": 0, "gear": "forward"},
                {"x": 0, "z": 0, "heading": 3.141592654, "gear": "forward"},
            ],
            "distanceMeters": 2,
            "turnCount": 1,
            "reverseUsed": False,
            "validation": {
                "identity": "pass",
                "topology": "pass",
                "direction": "pass",
                "physical": "pass",
                "authority": "pass",
                "stale": "pass",
            },
            "sourceRevisions": {"layout": "1" * 64},
            "plannerVersions": {"pedestrianRouter": "nav-router-v1"},
        }
    )
    assert journey["schemaVersion"] == FACILITY_NAVIGATION_JOURNEY_SCHEMA
    assert journey["orderedAnchorIds"][0] == journey["orderedAnchorIds"][-1]


def test_sage_contract_and_summary_are_bounded_and_coordinate_free() -> None:
    contract = navigation_sage_contract()
    summary = build_navigation_sage_summary(_extension(manual=True))
    payload = json.dumps(summary, separators=(",", ":"), sort_keys=True).encode("ascii")
    flattened_keys = set()

    def visit(value):
        if isinstance(value, dict):
            flattened_keys.update(value)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(summary)
    assert len(payload) <= 8_192
    assert summary["estimatedTokensBytes4"] < 9_600
    assert not flattened_keys.intersection(
        {"x", "y", "z", "position", "localPosition", "authoredPolyline", "poses"}
    )
    assert "localPosition" in contract["forbiddenInputFields"]
    assert len(json.dumps(contract).encode("utf-8")) < 16_384


def test_field_mapping_has_one_owner_per_behavior_field() -> None:
    matrix = navigation_field_mapping_matrix()
    fields = [item["behaviorField"] for item in matrix]
    assert fields
    assert len(fields) == len(set(fields))
    assert {item["canonicalOwner"] for item in matrix}.issuperset(
        {"facilityNavigation.anchors", "routes", "motion_lanes.py"}
    )


def test_checked_in_nav1_contract_artifacts_match_runtime_contract() -> None:
    fixture_root = FIXTURES / "navigation"
    contract = json.loads(
        (fixture_root / "nav1-contract-manifest-v1.json").read_text(
            encoding="ascii"
        )
    )
    mapping = json.loads(
        (fixture_root / "nav1-field-mapping-v1.json").read_text(
            encoding="ascii"
        )
    )

    assert contract == navigation_contract_manifest()
    assert mapping["rows"] == navigation_field_mapping_matrix()
    assert contract["productionEligible"] is False
    assert contract["humanApproval"] is None


def test_v2_projection_ignores_unselected_anchor_but_tracks_sources_and_obstacles() -> None:
    fixture, result = _accepted_route_result()
    layout = _motion_layout()
    spec, projection, obstacles = _motion_context(layout, result)
    fingerprint = motion_validation_context_fingerprint(projection)

    unrelated = deepcopy(layout)
    unrelated["extensions"]["facilityNavigation"]["anchors"].append(
        {"navigationAnchorId": "na-unrelated"}
    )
    unrelated_projection = build_motion_validation_context_projection(
        unrelated,
        spec,
        actor_profile=_profile(),
        obstacles=obstacles,
    )
    assert motion_validation_context_fingerprint(unrelated_projection) == fingerprint

    changed_source = deepcopy(layout)
    changed_source["routes"][0]["corridorWidth"] = 5
    changed_projection = build_motion_validation_context_projection(
        changed_source,
        spec,
        actor_profile=_profile(),
        obstacles=obstacles,
    )
    assert motion_validation_context_fingerprint(changed_projection) != fingerprint

    entering = deepcopy(obstacles)
    entering[1]["boundary"] = [
        {"x": 3, "z": 1.8},
        {"x": 4, "z": 1.8},
        {"x": 4, "z": 2.0},
        {"x": 3, "z": 2.0},
    ]
    entering_projection = build_motion_validation_context_projection(
        layout,
        spec,
        actor_profile=_profile(),
        obstacles=entering,
    )
    assert motion_validation_context_fingerprint(entering_projection) != fingerprint

    missing = deepcopy(layout)
    missing["routes"] = []
    with pytest.raises(FacilityMotionValidationContextError) as error:
        build_motion_validation_context_projection(
            missing,
            spec,
            actor_profile=_profile(),
            obstacles=obstacles,
        )
    assert error.value.code == "facility_motion_validation_context_missing_record"


def test_v2_playback_uses_only_recomputed_context_while_v1_stays_conservative() -> None:
    fixture, route_result = _accepted_route_result()
    layout = _motion_layout()
    spec, projection, _ = _motion_context(layout, route_result)
    built = build_facility_motion_package_v2(
        route_result,
        layout=layout,
        layout_revision=fixture["sourceRevisions"]["layout"],
        obstacle_context_revision="obstacle-context-nav1",
        route_id="route-main",
        vehicle_profile_ref={
            "vehicleProfileId": _profile()["vehicleProfileId"],
            "vehicleProfileRevision": _profile()["vehicleProfileRevision"],
        },
        validation_context_spec=spec,
        validation_context_projection=projection,
        vehicle_placement_id="vehicle-one",
    )
    package = validate_facility_motion_package(built["package"])
    fingerprint = package["validationContextFingerprint"]

    assert package["schemaVersion"] == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2
    assert "layoutRevision" not in package
    validate_facility_motion_package_for_playback(
        package,
        active_layout_revision="9" * 64,
        active_validation_context_fingerprint=fingerprint,
    )
    with pytest.raises(FacilityMotionValidationContextError) as error:
        validate_facility_motion_package_for_playback(
            package,
            active_layout_revision=fixture["sourceRevisions"]["layout"],
            active_validation_context_fingerprint="8" * 64,
        )
    assert error.value.code == "facility_motion_package_stale"
    with pytest.raises(FacilityMotionValidationContextError) as error:
        validate_facility_motion_package_for_playback(
            package,
            active_layout_revision=fixture["sourceRevisions"]["layout"],
        )
    assert error.value.code == "facility_motion_validation_context_unavailable"
    assert len(json.dumps(built["summary"]).encode("utf-8")) < 16_384


def test_v2_package_identity_covers_validation_context() -> None:
    fixture, route_result = _accepted_route_result()
    layout = _motion_layout()
    spec, projection, _ = _motion_context(layout, route_result)
    built = build_facility_motion_package_v2(
        route_result,
        layout=layout,
        layout_revision=fixture["sourceRevisions"]["layout"],
        obstacle_context_revision="obstacle-context-nav1",
        route_id="route-main",
        vehicle_profile_ref={
            "vehicleProfileId": _profile()["vehicleProfileId"],
            "vehicleProfileRevision": _profile()["vehicleProfileRevision"],
        },
        validation_context_spec=spec,
        validation_context_projection=projection,
    )
    tampered = deepcopy(built["package"])
    tampered["validationContextFingerprint"] = "7" * 64
    with pytest.raises(FacilityMotionPackageError) as error:
        validate_facility_motion_package(tampered)
    assert error.value.code == "facility_motion_package_id_mismatch"
