"""Build NAV0 evidence without modifying the archived Facility Layout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
from typing import Any

import shapely


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.host import LocalFacilityLayoutHost  # noqa: E402
from ai_inspector.facility_layout.navigation_baseline import (  # noqa: E402
    benchmark_nav0_algorithms,
    build_nav0_geometry_fixture,
    build_nav0_reference_baseline,
    build_nav0_review_receipt,
    build_nav0_routing_fixture,
    build_reference_automation_geometry,
)
from ai_inspector.facility_layout.navigation_geometry import (  # noqa: E402
    build_visibility_graph,
    canonicalize_polygon_geometry,
    free_space_geometry,
    solve_visibility_graph,
    union_and_expand_obstacles,
)


DEFAULT_ARCHIVE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
DEFAULT_MANIFEST = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "reference_quality"
    / "reference-manifest-v1.json"
)
DEFAULT_HARDWARE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "performance"
    / "standard-hardware-profile.json"
)
DEFAULT_HISTORICAL_VEHICLE_EVIDENCE = (
    ROOT
    / ".runtime"
    / "facility-motion"
    / "directional-loop-final-evidence"
    / "facility-activity-browser-evidence.json"
)
DEFAULT_OUTPUT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "navigation"
)
DEFAULT_VISUAL_SOURCES = (
    {
        "captureId": "operator_paths_plan",
        "view": "plan",
        "subject": "legacy_operator_cycle_candidates",
        "source": ROOT
        / ".runtime"
        / "facility-motion"
        / "existing-operators-handoff-final"
        / "01-plan-lean-motion-paths.png",
        "fileName": "01-operator-path-candidates-plan.png",
    },
    {
        "captureId": "operator_paths_3d",
        "view": "3d",
        "subject": "legacy_operator_cycle_and_fifo_candidates",
        "source": ROOT
        / ".runtime"
        / "facility-motion"
        / "existing-operators-handoff-final"
        / "03-3d-existing-operator-fifo-access.png",
        "fileName": "02-operator-path-candidates-3d.png",
    },
    {
        "captureId": "vehicle_paths_plan",
        "view": "plan",
        "subject": "prototype_vehicle_path_candidates",
        "source": ROOT
        / ".runtime"
        / "facility-motion"
        / "directional-loop-final-evidence"
        / "02-plan-all-actors-35-seconds.png",
        "fileName": "03-vehicle-path-candidates-plan.png",
    },
    {
        "captureId": "vehicle_paths_3d",
        "view": "3d",
        "subject": "prototype_vehicle_path_candidates",
        "source": ROOT
        / ".runtime"
        / "facility-motion"
        / "directional-loop-final-evidence"
        / "04-3d-factory-activity-overview.png",
        "fileName": "04-vehicle-path-candidates-3d.png",
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} does not contain a JSON object.")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )


def _historical_evidence(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = _read_json(path)
    activity = value.get("activity")
    if not isinstance(activity, dict):
        return None
    actor_counts = activity.get("actorTypeCounts")
    if not isinstance(actor_counts, dict):
        actor_counts = {}
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
        "actorCount": int(activity.get("actorCount") or 0),
        "vehicleCount": int(actor_counts.get("vehicle") or 0),
    }


def _publish_visual_evidence(output: Path) -> dict[str, Any]:
    visual_root = output / "browser"
    visual_root.mkdir(parents=True, exist_ok=True)
    captures = []
    for spec in DEFAULT_VISUAL_SOURCES:
        source = spec["source"]
        if not isinstance(source, Path):
            raise RuntimeError("NAV0 visual evidence source must be a path.")
        destination = visual_root / str(spec["fileName"])
        if source.is_file():
            shutil.copyfile(source, destination)
        elif not destination.is_file():
            raise RuntimeError(f"Required NAV0 visual evidence is missing: {source}")
        source_hash = _sha256(source) if source.is_file() else _sha256(destination)
        captures.append(
            {
                "captureId": spec["captureId"],
                "view": spec["view"],
                "subject": spec["subject"],
                "path": destination.relative_to(ROOT).as_posix(),
                "sha256": _sha256(destination),
                "sourcePath": source.relative_to(ROOT).as_posix(),
                "sourceSha256": source_hash,
                "reviewStatus": "pending",
                "productionEligible": False,
            }
        )
    return {
        "schemaVersion": "facility-navigation-nav0-visual-evidence-v1",
        "qualification": (
            "These captures preserve current prototype candidates for review; "
            "they do not approve the paths or establish navigation safety."
        ),
        "captures": captures,
    }


def _platform_receipt(geometry_fixture: dict[str, Any]) -> dict[str, Any]:
    observed = []
    for case in geometry_fixture["cases"]:
        result = union_and_expand_obstacles(
            case["obstacles"],
            navigation_radius_meters=case["navigationRadiusMeters"],
        )
        free_space = free_space_geometry(
            case["allowedPolygons"],
            result["expandedPolygons"],
        )
        start = (float(case["start"]["x"]), float(case["start"]["z"]))
        goal = (float(case["goal"]["x"]), float(case["goal"]["z"]))
        graph = build_visibility_graph(free_space, start, goal)
        route = solve_visibility_graph(graph, start, goal)
        observed.append(
            {
                "caseId": case["caseId"],
                "geometryFingerprint": result["geometryFingerprint"],
                "freeSpaceFingerprint": _fingerprint(
                    canonicalize_polygon_geometry(free_space)
                ),
                "graphFingerprint": _fingerprint(
                    {"nodes": graph.nodes, "edges": graph.edges}
                ),
                "routeFingerprint": route["routeFingerprint"],
                "centerline": route["centerline"],
                "matchesExpected": all((
                    result["geometryFingerprint"]
                    == case["expectedGeometryFingerprint"],
                    _fingerprint(canonicalize_polygon_geometry(free_space))
                    == case["expectedFreeSpaceFingerprint"],
                    _fingerprint({"nodes": graph.nodes, "edges": graph.edges})
                    == case["expectedGraphFingerprint"],
                    route["routeFingerprint"]
                    == case["expectedRouteFingerprint"],
                    route["centerline"] == case["expectedCenterline"],
                )),
            }
        )
    return {
        "platform": sys.platform,
        "operatingSystem": platform.platform(),
        "python": platform.python_version(),
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
        "cases": observed,
        "passed": all(item["matchesExpected"] for item in observed),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--hardware", type=Path, default=DEFAULT_HARDWARE)
    parser.add_argument(
        "--historical-vehicle-evidence",
        type=Path,
        default=DEFAULT_HISTORICAL_VEHICLE_EVIDENCE,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-performance", action="store_true")
    args = parser.parse_args()

    archive = args.archive.resolve()
    archive_sha256 = _sha256(archive)
    layout = _read_json(archive)
    manifest = _read_json(args.manifest.resolve())
    hardware = _read_json(args.hardware.resolve())
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

    historical = _historical_evidence(
        args.historical_vehicle_evidence.resolve()
    )
    baseline = build_nav0_reference_baseline(
        layout,
        manifest,
        catalog,
        historical_vehicle_evidence=historical,
    )
    review = build_nav0_review_receipt(baseline)
    routing_fixture = build_nav0_routing_fixture()
    geometry = build_nav0_geometry_fixture()
    platform_receipt = _platform_receipt(geometry)
    geometry["observedPlatformReceipts"] = [platform_receipt]
    geometry["promotionStatus"] = (
        "pending_linux_receipt"
        if platform_receipt["platform"].startswith("win")
        else "pending_windows_receipt"
    )

    performance = None
    if not args.skip_performance:
        performance = benchmark_nav0_algorithms(
            baseline,
            hardware_profile=hardware,
            cold_geometry_builder=lambda: build_reference_automation_geometry(
                layout,
                manifest,
                catalog,
            ),
        )

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    visual_manifest = _publish_visual_evidence(output)
    baseline_path = output / "nav0-reference-baseline-v1.json"
    review_path = output / "nav0-reference-review-v1.json"
    geometry_path = output / "nav0-geometry-cross-platform-v1.json"
    routing_fixture_path = output / "nav0-routing-cases-v1.json"
    visual_manifest_path = output / "nav0-visual-evidence-v1.json"
    _write_json(baseline_path, baseline)
    _write_json(review_path, review)
    _write_json(geometry_path, geometry)
    _write_json(routing_fixture_path, routing_fixture)
    _write_json(visual_manifest_path, visual_manifest)
    performance_path = output / "nav0-performance-v1.json"
    if performance is not None:
        _write_json(performance_path, performance)

    archive_unchanged = _sha256(archive) == archive_sha256
    if not archive_unchanged:
        raise RuntimeError("The manual reference archive changed during NAV0.")
    result = {
        "archive": archive.relative_to(ROOT).as_posix(),
        "archiveSha256": archive_sha256,
        "archiveUnchanged": archive_unchanged,
        "baseline": baseline_path.relative_to(ROOT).as_posix(),
        "baselineRevision": baseline["baselineRevision"],
        "review": review_path.relative_to(ROOT).as_posix(),
        "reviewStatus": review["reviewStatus"],
        "geometry": geometry_path.relative_to(ROOT).as_posix(),
        "geometryPromotionStatus": geometry["promotionStatus"],
        "routingCases": routing_fixture_path.relative_to(ROOT).as_posix(),
        "visualEvidence": visual_manifest_path.relative_to(ROOT).as_posix(),
        "performance": (
            performance_path.relative_to(ROOT).as_posix()
            if performance is not None
            else None
        ),
        "performanceStatus": performance.get("status") if performance else None,
        "selectedAlgorithm": (
            performance["results"]["selectedAlgorithm"]
            if performance is not None
            else None
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
