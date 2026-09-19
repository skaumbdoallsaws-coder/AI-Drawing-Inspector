from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.activity_scenario import (  # noqa: E402
    build_navigation_activity_scenario,
)
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost  # noqa: E402
from ai_inspector.facility_layout.journey_planning import (  # noqa: E402
    plan_pedestrian_journey,
    plan_vehicle_journey,
)
from ai_inspector.facility_layout.motion_package import (  # noqa: E402
    build_navigation_journey_motion_package,
)
from ai_inspector.facility_layout.navigation_activity import (  # noqa: E402
    build_navigation_activity_presentation,
)
from ai_inspector.facility_layout.navigation_baseline import (  # noqa: E402
    NAV0_REFERENCE_LAYOUT_REVISION,
    build_reference_automation_geometry,
)
from ai_inspector.facility_layout.navigation_compiler import (  # noqa: E402
    FacilityNavigationSnapshotStore,
)
from ai_inspector.facility_layout.navigation_contract import (  # noqa: E402
    seal_journey_solution,
)
from ai_inspector.facility_layout.navigation_geometry import (  # noqa: E402
    build_triangulated_mesh,
    geometry_from_canonical_polygons,
)
from ai_inspector.facility_layout.reference_performance import (  # noqa: E402
    summarize_timing_samples,
)


MEASURED_RUNS = 20
LIMITS_MILLISECONDS = {
    "coldNavigationSnapshotCompile": 5_000.0,
    "warmSnapshotLookup": 100.0,
    "localPedestrianQuery": 1_500.0,
    "singleVehicleQuery": 5_000.0,
    "completeBounded16ActorScenario": 60_000.0,
}
ARCHIVE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
MANIFEST = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "reference-manifest-v1.json"
)
BASELINE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "navigation"
    / "nav0-reference-baseline-v1.json"
)
HARDWARE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "performance"
    / "standard-hardware-profile.json"
)
NAV0_PERFORMANCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "navigation"
    / "nav0-performance-v1.json"
)
OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "navigation"
    / "nav9-performance-v1.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _measure(callback: Callable[[], Any]) -> tuple[list[float], Any]:
    callback()
    samples: list[float] = []
    result = None
    for _ in range(MEASURED_RUNS):
        started = time.perf_counter()
        result = callback()
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples, result


def _measurement(
    samples: list[float],
    *,
    limit: float,
    outcomes: list[str] | None = None,
) -> dict[str, Any]:
    result = summarize_timing_samples(samples, limit_milliseconds=limit)
    if outcomes is not None:
        result["outcomeCounts"] = {
            outcome: outcomes.count(outcome) for outcome in sorted(set(outcomes))
        }
    return result


def _nav7_actor(journey: dict[str, Any], package: dict[str, Any], index: int):
    placement_id = journey["actorPlacementId"]
    return {
        "actorId": f"actor-nav9-{index:02d}",
        "actorType": "operator",
        "label": f"NAV9 Operator {index:02d}",
        "motionPackageId": package["packageId"],
        "returnMotionPackageId": None,
        "endTransferMotionPackageId": None,
        "startTransferMotionPackageId": None,
        "cycleMotionPackageIds": [],
        "placementId": placement_id,
        "assetDefinitionRef": {
            "assetId": "asset-machine-01",
            "assetDefinitionRevision": "e" * 64,
        },
        "routeId": journey["movementProgramId"],
        "departmentZoneIds": ["zn-machine-cell"],
        "startOffsetSeconds": 0,
        "repeat": True,
        "loopMode": "journey_cycle",
        "endpointTurnSeconds": 0,
        "visualAlignment": {
            "forwardAxis": "+X",
            "authority": "curated_revision_bound_visual_review",
            "evidenceArtifact": "tests/fixtures/operator-forward-axis-v1.json",
        },
    }


def _sixteen_actor_input(
    source_journey: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    actors = []
    payloads = {}
    for index in range(1, 17):
        candidate = deepcopy(source_journey)
        candidate.pop("journeySolutionId", None)
        candidate.pop("solutionFingerprint", None)
        candidate["actorPlacementId"] = f"pl-nav9-benchmark-{index:02d}"
        offset = round((index - 8.5) * 0.08, 6)
        for point in candidate["centerline"]:
            point["z"] = round(float(point["z"]) + offset, 6)
        for pose in candidate["poses"]:
            pose["z"] = round(float(pose["z"]) + offset, 6)
        journey = seal_journey_solution(candidate)
        built = build_navigation_journey_motion_package(
            journey,
            actor_class="pedestrian",
            actor_profile_ref={
                "profileKind": "pedestrian",
                "profileId": "operator-profile-standard",
                "profileRevision": "1" * 64,
            },
            generated_at="2026-09-01T00:00:00Z",
        )["package"]
        actors.append(_nav7_actor(journey, built, index))
        payloads[built["packageId"]] = {"package": built}
    return actors, payloads


def main() -> None:
    archive_before = _sha256(ARCHIVE)
    if archive_before != NAV0_REFERENCE_LAYOUT_REVISION:
        raise RuntimeError("The frozen manual reference archive has changed.")

    reference_layout = _load(ARCHIVE)
    manifest = _load(MANIFEST)
    baseline = _load(BASELINE)
    hardware = _load(HARDWARE)
    nav0_evidence = _load(NAV0_PERFORMANCE)
    host = LocalFacilityLayoutHost(
        ROOT / ".runtime" / "facility-layout",
        process_map_root=ROOT / "generated" / "training",
        private_assets=True,
        private_asset_root=ROOT,
    )
    try:
        catalog = host.authoritative_asset_catalog()
    finally:
        host.close()

    def build_reference_geometry():
        return build_reference_automation_geometry(
            reference_layout, manifest, catalog
        )

    if nav0_evidence["baselineRevision"] != baseline["baselineRevision"]:
        raise RuntimeError("The frozen NAV0 performance evidence is stale.")
    if hardware["machineLabel"] != nav0_evidence["machine"]["machineLabel"]:
        raise RuntimeError("The frozen NAV0 hardware fixture is inconsistent.")

    def build_reference_snapshot():
        geometry = build_reference_geometry()
        free_space = geometry_from_canonical_polygons(
            geometry["freeSpacePolygons"]
        )
        mesh = build_triangulated_mesh(free_space)
        return {
            "geometryContextFingerprint": geometry[
                "geometryContextFingerprint"
            ],
            "triangleCount": len(mesh.triangles),
            "adjacencyEdgeCount": len(mesh.adjacency),
        }

    cold_samples, cold_result = _measure(build_reference_snapshot)

    # The current deterministic planner cases are the same fixtures used by
    # the NAV3-NAV7 contract suite. Loading them here prevents benchmark-only
    # geometry from drifting away from the tested implementation surface.
    fixture = runpy.run_path(
        str(ROOT / "tests" / "test_facility_layout_navigation_nav3.py")
    )
    pedestrian_layout = fixture["_layout"]()
    pedestrian_package = fixture["_compile"](pedestrian_layout)
    refused_pedestrian_layout = deepcopy(pedestrian_layout)
    refused_pedestrian_layout["extensions"]["facilityNavigation"]["anchors"][1][
        "localPosition"
    ] = {"x": 8, "z": 4}
    refused_pedestrian_package = fixture["_compile"](
        refused_pedestrian_layout
    )
    vehicle_layout = fixture["_vehicle_layout"]()
    vehicle_package = fixture["_compile_vehicle"](vehicle_layout)
    vehicle_profile = fixture["_vehicle_profile"]()
    refused_vehicle_layout = fixture["_vehicle_layout"](
        loop_mode="paired_lane_return"
    )
    refused_vehicle_layout["extensions"]["facilityNavigation"]["anchors"][1][
        "anchorKind"
    ] = "station_unload"
    refused_vehicle_package = fixture["_compile_vehicle"](
        refused_vehicle_layout
    )

    store = FacilityNavigationSnapshotStore(maximum_items=4)
    store.put(pedestrian_package)
    warm_samples, warm_result = _measure(
        lambda: store.get(pedestrian_package["navigationPackageId"])
    )

    pedestrian_outcomes: list[str] = []
    pedestrian_index = 0

    def pedestrian_query():
        nonlocal pedestrian_index
        refused = pedestrian_index % 2 == 1
        pedestrian_index += 1
        result = plan_pedestrian_journey(
            refused_pedestrian_layout if refused else pedestrian_layout,
            refused_pedestrian_package if refused else pedestrian_package,
            "nmp-cycle",
        )
        pedestrian_outcomes.append(result["outcome"])
        return result

    pedestrian_query()
    pedestrian_outcomes.clear()
    pedestrian_samples, pedestrian_result = _measure(pedestrian_query)
    pedestrian_outcomes = pedestrian_outcomes[-MEASURED_RUNS:]

    vehicle_outcomes: list[str] = []
    vehicle_index = 0

    def vehicle_query():
        nonlocal vehicle_index
        refused = vehicle_index % 2 == 1
        vehicle_index += 1
        result = plan_vehicle_journey(
            refused_vehicle_layout if refused else vehicle_layout,
            refused_vehicle_package if refused else vehicle_package,
            "nmp-cycle",
            vehicle_profile=vehicle_profile,
        )
        vehicle_outcomes.append(result["outcome"])
        return result

    vehicle_query()
    vehicle_outcomes.clear()
    vehicle_samples, vehicle_result = _measure(vehicle_query)
    vehicle_outcomes = vehicle_outcomes[-MEASURED_RUNS:]

    source_journey = plan_pedestrian_journey(
        pedestrian_layout, pedestrian_package, "nmp-cycle"
    )
    actors, payloads = _sixteen_actor_input(source_journey)

    def build_scenario():
        presentation = build_navigation_activity_presentation(
            actors,
            payloads,
            cycle_duration_seconds=30,
            sample_count=101,
        )
        return build_navigation_activity_scenario(
            layout_revision=source_journey["generationLayoutRevision"],
            label="NAV9 bounded 16-actor benchmark",
            actors=actors,
            cycle_duration_seconds=30,
            navigation_presentation=presentation,
            stationary_evidence={
                "placementCount": 0,
                "assetTypeCount": 0,
                "reason": "The benchmark contains journey actors only.",
                "evidenceStatus": "unknown",
            },
        )

    scenario_samples, scenario_result = _measure(build_scenario)
    measurements = {
        "coldNavigationSnapshotCompile": _measurement(
            cold_samples,
            limit=LIMITS_MILLISECONDS["coldNavigationSnapshotCompile"],
        ),
        "warmSnapshotLookup": _measurement(
            warm_samples,
            limit=LIMITS_MILLISECONDS["warmSnapshotLookup"],
        ),
        "localPedestrianQuery": _measurement(
            pedestrian_samples,
            limit=LIMITS_MILLISECONDS["localPedestrianQuery"],
            outcomes=pedestrian_outcomes,
        ),
        "singleVehicleQuery": _measurement(
            vehicle_samples,
            limit=LIMITS_MILLISECONDS["singleVehicleQuery"],
            outcomes=vehicle_outcomes,
        ),
        "completeBounded16ActorScenario": _measurement(
            scenario_samples,
            limit=LIMITS_MILLISECONDS["completeBounded16ActorScenario"],
        ),
    }
    measurements["coldNavigationSnapshotCompile"]["limitMilliseconds"] = (
        LIMITS_MILLISECONDS["coldNavigationSnapshotCompile"]
    )
    output = {
        "schemaVersion": "facility-navigation-nav9-performance-v1",
        "status": (
            "pass" if all(item["passed"] for item in measurements.values())
            else "fail"
        ),
        "protocol": {
            "discardedWarmupRuns": 1,
            "measuredRuns": MEASURED_RUNS,
            "percentileMethod": "nearest_rank",
            "mixedQueryOrder": "accepted_then_refused",
        },
        "machine": deepcopy(nav0_evidence["machine"]),
        "reference": {
            "layoutId": reference_layout["layoutId"],
            "layoutRevision": archive_before,
            "layoutCounts": {"zones": 45, "placements": 827},
            "selectedPedestrianAlgorithm": nav0_evidence["results"][
                "selectedAlgorithm"
            ],
        },
        "measurements": measurements,
        "resultChecks": {
            "warmSnapshotId": warm_result["snapshot"]["navigationSnapshotId"],
            "lastPedestrianOutcome": pedestrian_result["outcome"],
            "lastVehicleOutcome": vehicle_result["outcome"],
            "scenarioActorCount": len(scenario_result["actors"]),
            "scenarioProcessTimingClaimed": scenario_result[
                "navigationPresentation"
            ]["processTimingClaimed"],
            "scenarioGeneratedCollisionAvoidanceOffsets": scenario_result[
                "navigationPresentation"
            ]["generatedCollisionAvoidanceOffsets"],
            "coldSnapshotTriangleCount": cold_result["triangleCount"],
        },
        "authorityBoundary": (
            "Performance evidence only. It grants no human review authority and "
            "makes no safety, staffing, throughput, or travel-time claim."
        ),
    }
    output["performanceRevision"] = hashlib.sha256(
        json.dumps(
            output,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    if _sha256(ARCHIVE) != archive_before:
        raise RuntimeError("The benchmark modified the frozen reference archive.")
    OUTPUT.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(json.dumps({
        "output": str(OUTPUT),
        "status": output["status"],
        "p95Milliseconds": {
            key: value["p95Milliseconds"]
            for key, value in measurements.items()
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
