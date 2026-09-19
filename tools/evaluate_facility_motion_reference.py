"""Build motion evidence against the archived manual Facility Layout.

The source layout is opened read-only and hashed before and after evaluation.
Any emitted browser payload is a separate prototype acceptance artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.authorization import local_facility_principal
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.motion_package import (
    FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES,
    build_facility_motion_package,
)
from ai_inspector.facility_layout.routing import (
    MAXIMUM_SWEEP_OBSTACLE_COMPARISONS,
    MAXIMUM_SWEPT_VOLUME_SAMPLES,
    normalized_cardinal_route_heading,
    plan_forklift_route,
    projected_swept_sample_count,
    route_traversable_corridor,
    routing_layout_fingerprint,
)


DEFAULT_LAYOUT = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / LOCAL_SITE_ID
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
DEFAULT_PROFILE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "p0_authority_documents.json"
)
ROUTING_GOLDENS = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "routing"
    / "p7-routing-goldens.json"
)
FM0_BASELINE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "motion"
    / "fm0-motion-baseline-v1.json"
)
REFERENCE_ROUTE_ID = "rt-332016e60dd81aea2df8b79a"
PROTOTYPE_PROFILE_REVISION = hashlib.sha256(
    b"InspectorPro Facility Motion prototype profile fixture v1"
).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, int(math.ceil(percentile * len(ordered))))
    return ordered[rank - 1]


def _component_byte_breakdown(package: dict[str, Any]) -> dict[str, int]:
    """Attribute canonical bytes without pretending JSON members are standalone files."""

    total = len(_canonical_bytes(package))
    movement = package["movement"]
    pose_key = "poses" if "poses" in movement else "attemptedPoses"

    def contribution(path: tuple[str, ...], replacement: Any) -> int:
        reduced = deepcopy(package)
        target: Any = reduced
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = replacement
        return total - len(_canonical_bytes(reduced))

    poses = (
        contribution(("movement", pose_key), []) if pose_key in movement else 0
    )
    swept_geometry = (
        contribution(
            ("movement", "sweptEnvelope", "geometry"),
            {"polygons": []},
        )
        if isinstance(movement.get("sweptEnvelope"), dict)
        else 0
    )
    clearance_samples = (
        contribution(("movement", "clearance", "samples"), [])
        if isinstance(movement.get("clearance"), dict)
        else 0
    )
    return {
        "poses": poses,
        "sweptGeometry": swept_geometry,
        "clearanceSamples": clearance_samples,
        "remainingPackage": total - poses - swept_geometry - clearance_samples,
        "total": total,
    }


def _profile() -> dict[str, Any]:
    documents = json.loads(DEFAULT_PROFILE_FIXTURE.read_text(encoding="ascii"))
    profile = next(
        item for item in documents if item.get("documentKind") == "vehicle_profile"
    )
    result = deepcopy(profile)
    result["vehicleProfileId"] = "prototype-reference-forklift-v1"
    result["vehicleProfileRevision"] = PROTOTYPE_PROFILE_REVISION
    result["displayName"] = "Prototype Reference Forklift"
    result["status"] = "prototype_fixture"
    return result


def _build_once(
    *,
    layout: dict[str, Any],
    route: dict[str, Any],
    profile: dict[str, Any],
    obstacles: list[dict[str, Any]],
) -> dict[str, Any]:
    centerline = list(route["centerline"])
    started = time.perf_counter()
    result = plan_forklift_route(
        {
            "x": centerline[0]["x"],
            "y": centerline[0].get("y", 0),
            "z": centerline[0]["z"],
            "heading": normalized_cardinal_route_heading(
                centerline[0], centerline[1]
            ),
        },
        {
            "x": centerline[-1]["x"],
            "y": centerline[-1].get("y", 0),
            "z": centerline[-1]["z"],
            "heading": normalized_cardinal_route_heading(
                centerline[-2], centerline[-1]
            ),
        },
        profile,
        traversable_polygons=route_traversable_corridor(route),
        obstacles=obstacles,
        grid_resolution_meters=0.5,
        source_revisions={
            "layout": layout_revision(layout),
            "obstacleContext": routing_layout_fingerprint(layout),
            "vehicle": PROTOTYPE_PROFILE_REVISION,
        },
    )
    planned_seconds = time.perf_counter() - started
    serialized_started = time.perf_counter()
    built = build_facility_motion_package(
        result,
        layout=layout,
        layout_revision=layout_revision(layout),
        obstacle_context_revision=routing_layout_fingerprint(layout),
        route_id=str(route["routeId"]),
        vehicle_profile_ref={
            "vehicleProfileId": str(profile["vehicleProfileId"]),
            "vehicleProfileRevision": PROTOTYPE_PROFILE_REVISION,
        },
        vehicle_placement_id=None,
    )
    serialized_seconds = time.perf_counter() - serialized_started
    return {
        "result": result,
        "built": built,
        "plannedSeconds": planned_seconds,
        "serializedSeconds": serialized_seconds,
    }


def _golden_case(case_id: str) -> dict[str, Any]:
    fixture = json.loads(ROUTING_GOLDENS.read_text(encoding="utf-8"))
    case = next(
        item for item in fixture["scenarios"] if item.get("caseId") == case_id
    )
    started = time.perf_counter()
    result = plan_forklift_route(
        case["start"],
        case["goal"],
        fixture["vehicleProfile"],
        traversable_polygons=case["traversablePolygons"],
        allow_reverse=case.get("allowReverse"),
        load=case.get("load"),
        source_revisions=fixture["sourceRevisions"],
    )
    planned_seconds = time.perf_counter() - started
    serialized_started = time.perf_counter()
    built = build_facility_motion_package(
        result,
        layout={"placements": []},
        layout_revision=fixture["sourceRevisions"]["layout"],
        obstacle_context_revision="fm0-golden-context",
        route_id=f"fm0-{case_id}",
        vehicle_profile_ref={
            "vehicleProfileId": fixture["vehicleProfile"]["vehicleProfileId"],
            "vehicleProfileRevision": fixture["vehicleProfile"][
                "vehicleProfileRevision"
            ],
        },
    )
    return _fixture_result(
        case_id=case_id,
        result=result,
        built=built,
        planned_seconds=planned_seconds,
        serialized_seconds=time.perf_counter() - serialized_started,
    )


def _envelope_refusal_case() -> dict[str, Any]:
    fixture = json.loads(ROUTING_GOLDENS.read_text(encoding="utf-8"))
    baseline = json.loads(FM0_BASELINE_FIXTURE.read_text(encoding="utf-8"))
    case = next(
        item for item in baseline["cases"] if item["caseId"] == "envelope-refused"
    )
    profile = deepcopy(case["vehicleProfile"])
    profile["vehicleProfileRevision"] = fixture["vehicleProfile"][
        "vehicleProfileRevision"
    ]
    started = time.perf_counter()
    result = plan_forklift_route(
        case["start"],
        case["goal"],
        profile,
        traversable_polygons=case["traversablePolygons"],
        obstacles=case["obstacles"],
        grid_resolution_meters=case["gridResolutionMeters"],
        source_revisions=fixture["sourceRevisions"],
    )
    planned_seconds = time.perf_counter() - started
    serialized_started = time.perf_counter()
    built = build_facility_motion_package(
        result,
        layout={"placements": []},
        layout_revision=fixture["sourceRevisions"]["layout"],
        obstacle_context_revision="fm0-envelope-refusal-context",
        route_id="fm0-envelope-refusal",
        vehicle_profile_ref={
            "vehicleProfileId": profile["vehicleProfileId"],
            "vehicleProfileRevision": profile["vehicleProfileRevision"],
        },
    )
    return _fixture_result(
        case_id="envelope-refused",
        result=result,
        built=built,
        planned_seconds=planned_seconds,
        serialized_seconds=time.perf_counter() - serialized_started,
    )


def _fixture_result(
    *,
    case_id: str,
    result: dict[str, Any],
    built: dict[str, Any],
    planned_seconds: float,
    serialized_seconds: float,
) -> dict[str, Any]:
    movement = built["package"]["movement"]
    poses = movement.get("poses", movement.get("attemptedPoses", []))
    clearance = movement.get("clearance") or {}
    return {
        "caseId": case_id,
        "outcome": movement["outcome"],
        "findingCodes": [
            item["code"] for item in result.get("findings", []) if item.get("code")
        ],
        "localizedBlocking": bool(
            (movement.get("blocking") or {}).get("localized")
        ),
        "reverseUsed": "reverse" in result.get("actions", []),
        "loaded": result.get("loaded") is True,
        "poseCount": len(poses),
        "sampleCount": len(clearance.get("samples", [])),
        "sampleSpacingMeters": clearance.get(
            "sampleSpacingMeters",
            (movement.get("sweptEnvelope") or {}).get("sampleSpacingMeters"),
        ),
        "canonicalBytes": built["canonicalBytes"],
        "canonicalByteBreakdown": _component_byte_breakdown(built["package"]),
        "plannerSeconds": round(planned_seconds, 6),
        "serializerSeconds": round(serialized_seconds, 6),
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    layout_path = Path(args.layout).resolve()
    before_hash = _sha256(layout_path)
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    route = next(
        item for item in layout.get("routes", []) if item.get("routeId") == args.route
    )
    host = LocalFacilityLayoutHost(
        ROOT / ".runtime" / "facility-layout",
        process_map_root=ROOT / "generated" / "training",
        facility_planning_root=ROOT / "generated" / "facility_planning",
        private_assets=True,
    )
    principal = local_facility_principal(site_id=LOCAL_SITE_ID)
    spatial = host.service._spatial_context(principal, LOCAL_SITE_ID, layout)
    obstacles = host.service._route_obstacles(
        layout,
        spatial.asset_definitions,
        spatial.shell,
    )
    profile = _profile()
    runs = [
        _build_once(
            layout=layout,
            route=route,
            profile=profile,
            obstacles=obstacles,
        )
        for _ in range(max(1, args.runs))
    ]
    first = runs[0]
    package = first["built"]["package"]
    movement = package["movement"]
    package_ids = {item["built"]["package"]["packageId"] for item in runs}
    planner_values = [item["plannedSeconds"] for item in runs]
    serializer_values = [item["serializedSeconds"] for item in runs]
    reference_fixture = _fixture_result(
        case_id="accepted-reference-manual",
        result=first["result"],
        built=first["built"],
        planned_seconds=statistics.median(planner_values),
        serialized_seconds=statistics.median(serializer_values),
    )
    baseline_fixture = json.loads(
        FM0_BASELINE_FIXTURE.read_text(encoding="utf-8")
    )
    hostile_grid_resolution = baseline_fixture["hostileResolution"][
        "gridResolutionMeters"
    ]
    hostile_spacing = min(0.1, hostile_grid_resolution / 4.0)
    hostile_projected_samples = projected_swept_sample_count(
        first["result"]["poses"],
        hostile_spacing,
    )
    after_hash = _sha256(layout_path)
    report = {
        "schemaVersion": 1,
        "evaluationId": "facility-motion-reference-manual-fm6",
        "prototypeMode": True,
        "sourceLayout": {
            "path": str(layout_path.relative_to(ROOT)),
            "layoutId": layout["layoutId"],
            "fileSha256Before": before_hash,
            "fileSha256After": after_hash,
            "byteIdentical": before_hash == after_hash,
            "zoneCount": len(layout.get("zones", [])),
            "routeCount": len(layout.get("routes", [])),
            "placementCount": len(layout.get("placements", [])),
            "floorMarkingCount": len(layout.get("floorMarkings", [])),
        },
        "route": {
            "routeId": route["routeId"],
            "label": route.get("label"),
            "corridorWidthMeters": route.get("corridorWidth"),
        },
        "vehicleProfile": {
            "vehicleProfileId": profile["vehicleProfileId"],
            "vehicleProfileRevision": PROTOTYPE_PROFILE_REVISION,
            "displayName": profile["displayName"],
            "authority": "prototype_fixture",
        },
        "obstacleCount": len(obstacles),
        "outcome": movement["outcome"],
        "findings": deepcopy(
            movement.get("findings", first["result"].get("findings", []))
        ),
        "packageId": package["packageId"],
        "packageByteReproducible": len(package_ids) == 1,
        "canonicalBytes": first["built"]["canonicalBytes"],
        "canonicalByteBreakdown": _component_byte_breakdown(package),
        "canonicalByteCeiling": FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES,
        "poseCount": len(
            movement.get("poses", movement.get("attemptedPoses", []))
        ),
        "sampleCount": len(
            (movement.get("clearance") or {}).get("samples", [])
        ),
        "sampleSpacingMeters": (
            movement.get("clearance") or {}
        ).get("sampleSpacingMeters"),
        "distanceMeters": movement.get("distanceMeters"),
        "estimatedTravelSeconds": movement.get(
            "plannerDurationEstimateSeconds"
        ),
        "budgets": {
            "maximumSamples": MAXIMUM_SWEPT_VOLUME_SAMPLES,
            "maximumObstacleComparisons": MAXIMUM_SWEEP_OBSTACLE_COMPARISONS,
            "boundaryContracts": {
                "sampleCount": [
                    {
                        "projected": MAXIMUM_SWEPT_VOLUME_SAMPLES - 1,
                        "expected": "allowed",
                    },
                    {
                        "projected": MAXIMUM_SWEPT_VOLUME_SAMPLES,
                        "expected": "allowed",
                    },
                    {
                        "projected": MAXIMUM_SWEPT_VOLUME_SAMPLES + 1,
                        "expected": "facility_route_sample_budget_exceeded",
                    },
                ],
                "canonicalBytes": [
                    {
                        "bytes": (
                            FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES - 1
                        ),
                        "expected": "allowed",
                    },
                    {
                        "bytes": FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES,
                        "expected": "allowed",
                    },
                    {
                        "bytes": (
                            FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES + 1
                        ),
                        "expected": "facility_motion_package_too_large",
                    },
                ],
            },
            "hostileResolutionFixture": {
                "gridResolutionMeters": hostile_grid_resolution,
                "sampleSpacingMeters": hostile_spacing,
                "projectedSampleCount": hostile_projected_samples,
                "exceedsMaximumSamples": (
                    hostile_projected_samples > MAXIMUM_SWEPT_VOLUME_SAMPLES
                ),
            },
        },
        "baselineFixtures": [
            reference_fixture,
            _envelope_refusal_case(),
            _golden_case("reverse-required"),
            _golden_case("loaded"),
        ],
        "timing": {
            "sampleSize": len(runs),
            "machine": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "python": platform.python_version(),
            },
            "plannerSeconds": [round(item["plannedSeconds"], 6) for item in runs],
            "serializerSeconds": [
                round(item["serializedSeconds"], 6) for item in runs
            ],
            "plannerMedianSeconds": round(
                statistics.median(planner_values), 6
            ),
            "plannerP95Seconds": round(_nearest_rank(planner_values, 0.95), 6),
            "serializerMedianSeconds": round(
                statistics.median(serializer_values), 6
            ),
            "serializerP95Seconds": round(
                _nearest_rank(serializer_values, 0.95), 6
            ),
        },
        "qualification": package["qualification"],
    }
    if args.browser_payload:
        payload = {
            "prototypeMode": True,
            "prototypeLabel": (
                "Prototype fixture profile on archived manual factory"
            ),
            "package": package,
            "facilityMotionEnvelope": first["built"]["facilityMotionEnvelope"],
            "vehicleProfile": profile,
        }
        output_path = Path(args.browser_payload).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        report["browserPayload"] = str(output_path.relative_to(ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    parser.add_argument("--route", default=REFERENCE_ROUTE_ID)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output")
    parser.add_argument("--browser-payload")
    args = parser.parse_args()
    report = evaluate(args)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not report["sourceLayout"]["byteIdentical"]:
        return 2
    if not report["packageByteReproducible"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
