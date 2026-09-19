from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.activity_scenario import (
    FACILITY_ACTIVITY_SCENARIO_QUALIFICATION,
    FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION,
    FacilityActivityScenarioError,
    FacilityActivityScenarioStore,
    build_facility_activity_scenario,
    facility_activity_scenario_summary,
    validate_facility_activity_scenario,
)
from ai_inspector.facility_layout.activity_visuals import (
    activity_visual_alignment,
)
from ai_inspector.facility_layout.lean_motion import (
    FACILITY_LEAN_MOTION_QUALIFICATION,
    FACILITY_LEAN_MOTION_SCHEMA_VERSION,
)


def _actor(index: int, actor_type: str = "vehicle") -> dict:
    return {
        "actorId": f"actor-{index:02d}",
        "actorType": actor_type,
        "label": f"Actor {index:02d}",
        "motionPackageId": f"fmp-package-{index:02d}",
        "returnMotionPackageId": None,
        "endTransferMotionPackageId": None,
        "startTransferMotionPackageId": None,
        "cycleMotionPackageIds": [],
        "placementId": f"pl-placement-{index:02d}",
        "assetDefinitionRef": {
            "assetId": f"asset-{actor_type}-{index:02d}",
            "assetDefinitionRevision": str(index) * 64,
        },
        "routeId": f"rt-route-{index:02d}",
        "departmentZoneIds": [f"zn-department-{index:02d}"],
        "startOffsetSeconds": float(index - 1),
        "repeat": True,
        "loopMode": "ping_pong",
        "endpointTurnSeconds": 1.0,
        "visualAlignment": {
            "forwardAxis": "+X",
            "authority": "curated_revision_bound_visual_review",
            "evidenceArtifact": "tests/fixtures/activity-actor.glb",
        },
    }


def _scenario() -> dict:
    return build_facility_activity_scenario(
        layout_revision="a" * 64,
        label="Prototype factory activity",
        actors=[_actor(1), _actor(2, "operator")],
        cycle_duration_seconds=42.5,
        repeat=True,
        stationary_evidence={
            "placementCount": 12,
            "assetTypeCount": 3,
            "reason": "No revision-bound machine kinematic tracks are available.",
            "evidenceStatus": "unknown",
        },
    )


def test_activity_scenario_is_content_addressed_and_summarized():
    first = _scenario()
    second = _scenario()

    assert first == second
    assert first["schemaVersion"] == FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION
    assert first["qualification"] == FACILITY_ACTIVITY_SCENARIO_QUALIFICATION
    assert first["scenarioId"].startswith("fas-")
    summary = facility_activity_scenario_summary(first)
    assert summary["actorCount"] == 2
    assert summary["actorTypeCounts"] == {
        "vehicle": 1,
        "operator": 1,
        "mobile_equipment": 0,
    }
    assert summary["departmentCount"] == 2


def test_activity_scenario_supports_23_actor_reference_playback_but_caps_at_24():
    scenario = build_facility_activity_scenario(
        layout_revision="a" * 64,
        label="Complete reference movement",
        actors=[_actor(index) for index in range(1, 24)],
        cycle_duration_seconds=120,
        stationary_evidence={
            "placementCount": 0,
            "assetTypeCount": 0,
            "reason": "No stationary evidence in this bounded fixture.",
            "evidenceStatus": "unknown",
        },
    )
    assert len(scenario["actors"]) == 23

    with pytest.raises(FacilityActivityScenarioError) as caught:
        build_facility_activity_scenario(
            layout_revision="a" * 64,
            label="Over actor limit",
            actors=[_actor(index) for index in range(1, 26)],
            cycle_duration_seconds=120,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "No stationary evidence in this bounded fixture.",
                "evidenceStatus": "unknown",
            },
        )
    assert caught.value.code == "facility_activity_scenario_actor_limit"


def test_activity_scenario_binds_a_closed_operator_loop_to_one_actor():
    actor = _actor(1, "operator")
    actor.update({
        "motionPackageId": "fmp-loop-a",
        "cycleMotionPackageIds": [
            "fmp-loop-a",
            "fmp-loop-b",
            "fmp-loop-c",
            "fmp-loop-d",
        ],
        "loopMode": "closed_path",
        "endpointTurnSeconds": 0.45,
    })
    lean_motion = {
        "schemaVersion": FACILITY_LEAN_MOTION_SCHEMA_VERSION,
        "qualification": FACILITY_LEAN_MOTION_QUALIFICATION,
        "evidenceStatus": "derived",
        "operatorPaths": [{
            "pathId": "operator-path-one",
            "actorId": actor["actorId"],
            "zoneId": "zone-line-one",
            "pathKind": "cell_work_loop",
            "segmentIndex": 0,
            "segmentCount": 1,
            "assignedPlacementIds": ["pl-bench-one"],
            "centerline": [
                {"x": 0, "z": 0},
                {"x": 4, "z": 0},
                {"x": 4, "z": 3},
                {"x": 0, "z": 3},
                {"x": 0, "z": 0},
            ],
            "closed": True,
            "evidenceStatus": "derived",
        }],
        "pedestrianConnections": [],
        "assistanceGates": [],
        "materialHandoffs": [],
        "fifoPoints": [],
    }
    scenario = build_facility_activity_scenario(
        layout_revision="c" * 64,
        label="Closed operator loop",
        actors=[actor],
        cycle_duration_seconds=24,
        lean_motion=lean_motion,
        stationary_evidence={
            "placementCount": 0,
            "assetTypeCount": 0,
            "reason": "No stationary kinematic tracks are in this fixture.",
            "evidenceStatus": "unknown",
        },
    )

    assert scenario["actors"][0]["loopMode"] == "closed_path"
    assert scenario["leanMotion"]["operatorPaths"][0]["actorId"] == (
        actor["actorId"]
    )
    assert facility_activity_scenario_summary(scenario)["leanMotionCounts"] == {
        "operatorPaths": 1,
        "pedestrianConnections": 0,
        "assistanceGates": 0,
        "materialHandoffs": 0,
        "fifoPoints": 0,
    }

    invalid = deepcopy(lean_motion)
    invalid["operatorPaths"][0]["actorId"] = "actor-not-in-scenario"
    with pytest.raises(FacilityActivityScenarioError) as caught:
        build_facility_activity_scenario(
            layout_revision="c" * 64,
            label="Invalid actor binding",
            actors=[actor],
            cycle_duration_seconds=24,
            lean_motion=invalid,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "No stationary kinematic tracks are in this fixture.",
                "evidenceStatus": "unknown",
            },
        )
    assert caught.value.code == "facility_activity_scenario_invalid"


def test_activity_scenario_binds_pedestrian_connections_and_assistance_gate():
    actors = [_actor(1, "operator"), _actor(2, "operator")]
    for actor in actors:
        actor.update({
            "loopMode": "closed_path",
            "cycleMotionPackageIds": [
                actor["motionPackageId"],
                f"{actor['motionPackageId']}-b",
                f"{actor['motionPackageId']}-c",
            ],
            "endpointTurnSeconds": 0.45,
        })
    paths = []
    for index, actor in enumerate(actors):
        x0 = index * 6
        paths.append({
            "pathId": f"path-{index + 1}",
            "actorId": actor["actorId"],
            "zoneId": "zone-line" if index == 0 else "zone-cell",
            "pathKind": "split_station_loop",
            "segmentIndex": index,
            "segmentCount": 2,
            "assignedPlacementIds": [f"station-{index + 1}"],
            "centerline": [
                {"x": x0, "z": 0},
                {"x": x0 + 4, "z": 0},
                {"x": x0 + 4, "z": 4},
                {"x": x0, "z": 4},
                {"x": x0, "z": 0},
            ],
            "closed": True,
            "evidenceStatus": "derived",
        })
    lean_motion = {
        "schemaVersion": FACILITY_LEAN_MOTION_SCHEMA_VERSION,
        "qualification": FACILITY_LEAN_MOTION_QUALIFICATION,
        "evidenceStatus": "derived",
        "operatorPaths": paths,
        "pedestrianConnections": [
            {
                "connectionId": "connection-source",
                "actorId": actors[0]["actorId"],
                "pathId": "path-1",
                "zoneId": "zone-line",
                "fifoPointId": "fifo-output",
                "handoffIds": ["handoff-one"],
                "role": "output",
                "motionPackageIds": [
                    f"{actors[0]['motionPackageId']}-b",
                    f"{actors[0]['motionPackageId']}-c",
                ],
                "centerline": [
                    {"x": 0, "z": 0},
                    {"x": 4, "z": 2},
                    {"x": 0, "z": 0},
                ],
                "closed": True,
                "evidenceStatus": "derived",
            },
            {
                "connectionId": "connection-target",
                "actorId": actors[1]["actorId"],
                "pathId": "path-2",
                "zoneId": "zone-cell",
                "fifoPointId": "fifo-input",
                "handoffIds": ["handoff-one"],
                "role": "input",
                "motionPackageIds": [
                    f"{actors[1]['motionPackageId']}-b",
                    f"{actors[1]['motionPackageId']}-c",
                ],
                "centerline": [
                    {"x": 6, "z": 0},
                    {"x": 6, "z": 2},
                    {"x": 6, "z": 0},
                ],
                "closed": True,
                "evidenceStatus": "derived",
            },
        ],
        "assistanceGates": [{
            "gateId": "gate-one",
            "zoneId": "zone-line",
            "participantPathIds": ["path-1", "path-2"],
            "participantActorIds": [
                actors[0]["actorId"],
                actors[1]["actorId"],
            ],
            "position": {"x": 5, "z": 2},
            "evidenceStatus": "derived",
        }],
        "materialHandoffs": [{
            "handoffId": "handoff-one",
            "fromZoneId": "zone-line",
            "toZoneId": "zone-cell",
            "centerline": [{"x": 4, "z": 2}, {"x": 6, "z": 2}],
            "fromPointId": "fifo-output",
            "toPointId": "fifo-input",
            "fromPathId": "path-1",
            "toPathId": "path-2",
            "fromActorId": actors[0]["actorId"],
            "toActorId": actors[1]["actorId"],
            "fromConnectionId": "connection-source",
            "toConnectionId": "connection-target",
            "evidenceStatus": "derived",
        }],
        "fifoPoints": [
            {
                "pointId": "fifo-output",
                "zoneId": "zone-line",
                "role": "output",
                "position": {"x": 4, "z": 2},
                "evidenceStatus": "derived",
            },
            {
                "pointId": "fifo-input",
                "zoneId": "zone-cell",
                "role": "input",
                "position": {"x": 6, "z": 2},
                "evidenceStatus": "derived",
            },
        ],
    }
    scenario = build_facility_activity_scenario(
        layout_revision="d" * 64,
        label="Segmented operator network",
        actors=actors,
        cycle_duration_seconds=30,
        lean_motion=lean_motion,
        stationary_evidence={
            "placementCount": 0,
            "assetTypeCount": 0,
            "reason": "No stationary fixture assets.",
            "evidenceStatus": "unknown",
        },
    )

    assert facility_activity_scenario_summary(scenario)["leanMotionCounts"] == {
        "operatorPaths": 2,
        "pedestrianConnections": 2,
        "assistanceGates": 1,
        "materialHandoffs": 1,
        "fifoPoints": 2,
    }

    invalid = deepcopy(lean_motion)
    invalid["assistanceGates"][0]["participantActorIds"].reverse()
    with pytest.raises(FacilityActivityScenarioError):
        build_facility_activity_scenario(
            layout_revision="d" * 64,
            label="Invalid gate binding",
            actors=actors,
            cycle_duration_seconds=30,
            lean_motion=invalid,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "No stationary fixture assets.",
                "evidenceStatus": "unknown",
            },
        )


def test_activity_scenario_rejects_identity_drift_and_duplicate_placements():
    scenario = _scenario()
    changed = deepcopy(scenario)
    changed["actors"][0]["routeId"] = "rt-other"
    with pytest.raises(FacilityActivityScenarioError) as caught:
        validate_facility_activity_scenario(changed)
    assert caught.value.code == "facility_activity_scenario_id_mismatch"

    duplicate = [_actor(1), _actor(2)]
    duplicate[1]["placementId"] = duplicate[0]["placementId"]
    with pytest.raises(FacilityActivityScenarioError) as caught:
        build_facility_activity_scenario(
            layout_revision="a" * 64,
            label="Duplicate",
            actors=duplicate,
            cycle_duration_seconds=10,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "No machine tracks were requested.",
                "evidenceStatus": "unknown",
            },
        )
    assert caught.value.code == "facility_activity_scenario_duplicate_actor"


def test_activity_scenario_rejects_unreviewed_visual_axis_and_loop_drift():
    actor = _actor(1)
    actor["visualAlignment"]["forwardAxis"] = "+Y"
    with pytest.raises(FacilityActivityScenarioError) as caught:
        build_facility_activity_scenario(
            layout_revision="a" * 64,
            label="Bad visual axis",
            actors=[actor],
            cycle_duration_seconds=10,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "No machine tracks were requested.",
                "evidenceStatus": "unknown",
            },
        )
    assert caught.value.code == "facility_activity_scenario_invalid"

    actor = _actor(1)
    actor["loopMode"] = "restart"
    with pytest.raises(FacilityActivityScenarioError) as caught:
        build_facility_activity_scenario(
            layout_revision="a" * 64,
            label="Bad loop",
            actors=[actor],
            cycle_duration_seconds=10,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "No machine tracks were requested.",
                "evidenceStatus": "unknown",
            },
        )
    assert caught.value.code == "facility_activity_scenario_invalid"


def test_activity_scenario_requires_complete_unique_paired_lane_packages():
    actor = _actor(1)
    actor.update({
        "loopMode": "paired_lanes",
        "endpointTurnSeconds": 0.0,
        "returnMotionPackageId": "fmp-return",
        "endTransferMotionPackageId": "fmp-end-transfer",
        "startTransferMotionPackageId": "fmp-start-transfer",
    })
    scenario = build_facility_activity_scenario(
        layout_revision="a" * 64,
        label="Paired lanes",
        actors=[actor],
        cycle_duration_seconds=20,
        stationary_evidence={
            "placementCount": 0,
            "assetTypeCount": 0,
            "reason": "No machine tracks were requested.",
            "evidenceStatus": "unknown",
        },
    )
    assert scenario["actors"][0]["loopMode"] == "paired_lanes"

    incomplete = deepcopy(actor)
    incomplete["endTransferMotionPackageId"] = None
    with pytest.raises(FacilityActivityScenarioError) as caught:
        build_facility_activity_scenario(
            layout_revision="a" * 64,
            label="Incomplete paired lanes",
            actors=[incomplete],
            cycle_duration_seconds=20,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "No machine tracks were requested.",
                "evidenceStatus": "unknown",
            },
        )
    assert caught.value.code == "facility_activity_scenario_invalid"

def test_activity_visual_alignment_is_bound_to_exact_asset_revision():
    alignment = activity_visual_alignment({
        "assetId": "asset-operator",
        "assetDefinitionRevision": (
            "773d3761fb0796587de7a21ccb8b368f4334c71f73c06682b84472d69d4b5757"
        ),
    })
    assert alignment["forwardAxis"] == "+Z"
    assert alignment["authority"] == (
        "curated_revision_bound_visual_review"
    )
    electric = activity_visual_alignment({
        "assetId": "asset-forklift",
        "assetDefinitionRevision": (
            "da1345e51b1a32c38ad8388799154ba77dc59e99890a855caac3648548f5be5f"
        ),
    })
    telescopic = activity_visual_alignment({
        "assetId": "asset-forklift-telescopic-red",
        "assetDefinitionRevision": (
            "ab73c19258c171d1c3cab496cd317b1d896293249ddd62c57cba81a61829f214"
        ),
    })
    assert electric["forwardAxis"] == "+Z"
    assert telescopic["forwardAxis"] == "-X"

    with pytest.raises(Exception) as caught:
        activity_visual_alignment({
            "assetId": "asset-operator",
            "assetDefinitionRevision": "0" * 64,
        })
    assert getattr(caught.value, "code", None) == (
        "facility_activity_visual_alignment_unavailable"
    )


def test_activity_scenario_store_is_bounded_and_expires():
    now = [10.0]
    store = FacilityActivityScenarioStore(
        ttl_seconds=5,
        maximum_entries=1,
        clock=lambda: now[0],
    )
    first = _scenario()
    store.put(first["scenarioId"], {"scenario": first})
    assert store.get(first["scenarioId"])["scenario"] == first

    second = build_facility_activity_scenario(
        layout_revision="b" * 64,
        label="Second",
        actors=[_actor(3)],
        cycle_duration_seconds=8,
        stationary_evidence={
            "placementCount": 0,
            "assetTypeCount": 0,
            "reason": "No machine tracks were requested.",
            "evidenceStatus": "unknown",
        },
    )
    store.put(second["scenarioId"], {"scenario": second})
    with pytest.raises(Exception) as evicted:
        store.get(first["scenarioId"])
    assert getattr(evicted.value, "code", None) == (
        "facility_activity_scenario_not_found"
    )

    now[0] = 16.0
    with pytest.raises(Exception) as expired:
        store.get(second["scenarioId"])
    assert getattr(expired.value, "code", None) == (
        "facility_activity_scenario_not_found"
    )
