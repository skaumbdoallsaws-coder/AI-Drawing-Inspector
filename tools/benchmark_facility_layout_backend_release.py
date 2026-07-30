"""Deterministic backend microbenchmark for Facility Layout release evidence.

The benchmark deliberately measures a narrow backend slice. It does not cover
browser advisory latency, rendering, loading, HTTP, persistence, concurrency,
or the extended 5,000-placement warehouse fixture.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "performance"
    / "backend-release-microbenchmark-spec-v1.json"
)
DEFAULT_RESULT_PATH = DEFAULT_SPEC_PATH.with_name(
    "backend-release-microbenchmark-results.json"
)
SPATIAL_CONTRACT_PATH = (
    REPO_ROOT / "static" / "contracts" / "facility-layout-spatial-contract-v1.json"
)
SPATIAL_SOURCE_PATH = REPO_ROOT / "ai_inspector" / "facility_layout" / "spatial.py"
ROUTING_SOURCE_PATH = REPO_ROOT / "ai_inspector" / "facility_layout" / "routing.py"
RUNNER_PATH = Path(__file__).resolve()
RESULT_SCHEMA_VERSION = "facility-layout-backend-release-microbenchmark-v1"


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.facility_layout.routing import (  # noqa: E402
    persisted_route_fingerprint,
    plan_forklift_route,
)
from ai_inspector.facility_layout.canonical import canonicalize_layout  # noqa: E402
from ai_inspector.facility_layout.spatial import (  # noqa: E402
    UniformGridSpatialIndex,
    diagnose_layout,
    generate_placement_candidates,
    height_intervals_intersect,
    placement_clearance_records,
    placement_spatial_records,
    polygons_intersect,
    spatial_fingerprint,
)
from ai_inspector.facility_layout.validate import validate_layout  # noqa: E402


JsonObject = dict[str, Any]
TimedOperation = Callable[[int], Any]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _rectangle(
    minimum_x: float,
    minimum_z: float,
    maximum_x: float,
    maximum_z: float,
) -> list[JsonObject]:
    return [
        {"x": minimum_x, "z": minimum_z},
        {"x": maximum_x, "z": minimum_z},
        {"x": maximum_x, "z": maximum_z},
        {"x": minimum_x, "z": maximum_z},
    ]


def _identity_quaternion() -> JsonObject:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _placement(placement_id: str, x: float, z: float) -> JsonObject:
    return {
        "placementId": placement_id,
        "assetId": "asset-backend-benchmark-machine",
        "assetDefinitionRevision": "a" * 64,
        "transform": {
            "position": {"x": x, "y": 0.0, "z": z},
            "quaternion": _identity_quaternion(),
            "scale": 1,
        },
        "positionMode": "manual",
        "snapRelationship": None,
        "metadata": {},
    }


def _asset_definition() -> JsonObject:
    return {
        "documentKind": "industrial_asset_definition",
        "assetId": "asset-backend-benchmark-machine",
        "assetDefinitionRevision": "a" * 64,
        "category": "machine",
        "coordinateFrame": {
            "allowedMountingSurfaces": ["floor"],
            "floorAnchor": {"x": 0.0, "y": 0.0, "z": 0.0},
        },
        "geometry": {
            "footprintPolygons": [
                _rectangle(-0.75, -0.5, 0.75, 0.5),
            ],
            "heightInterval": {"minimumY": 0.0, "maximumY": 2.0},
        },
        "collision": {
            "geometry": {"footprintIndex": 0},
            "verticalInterval": {"minimumY": 0.0, "maximumY": 2.0},
        },
        "clearances": [
            {
                "clearanceId": "clearance-benchmark-service",
                "clearanceKind": "service",
                "enforcement": "hard",
                "evidenceStatus": "authored",
                "evidence": ["ev-backend-benchmark-clearance"],
                "geometry": {
                    "shape": "rectangle",
                    "minimum": {"x": -1.0, "z": -0.75},
                    "maximum": {"x": 1.0, "z": 0.75},
                    "verticalInterval": {
                        "minimumY": 0.0,
                        "maximumY": 2.0,
                    },
                },
            }
        ],
        "connectors": [
            {
                "connectorId": "material-in",
                "connectorKind": "material",
                "position": {"x": -0.75, "y": 0.5, "z": 0.0},
                "facing": {"x": -1.0, "y": 0.0, "z": 0.0},
                "role": "input",
                "interface": {"carrier": "benchmark-pallet"},
                "evidenceStatus": "authored",
                "evidence": ["ev-backend-benchmark-connector"],
            },
            {
                "connectorId": "material-out",
                "connectorKind": "material",
                "position": {"x": 0.75, "y": 0.5, "z": 0.0},
                "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                "role": "output",
                "interface": {"carrier": "benchmark-pallet"},
                "evidenceStatus": "authored",
                "evidence": ["ev-backend-benchmark-connector"],
            },
        ],
    }


def _authority() -> JsonObject:
    return {
        "ev-backend-benchmark-clearance": {
            "status": "authored",
            "current": True,
            "authoritative": True,
            "blockers": [],
        },
        "ev-backend-benchmark-connector": {
            "status": "authored",
            "current": True,
            "authoritative": True,
            "blockers": [],
        },
    }


def _zone(zone_index: int, spec: Mapping[str, Any]) -> JsonObject:
    columns = int(spec["zoneColumns"])
    width = float(spec["zoneWidthMeters"])
    depth = float(spec["zoneDepthMeters"])
    column = zone_index % columns
    row = zone_index // columns
    minimum_x = column * width
    minimum_z = row * depth
    return {
        "zoneId": f"zn-bench-{zone_index:03d}",
        "zoneType": "workcell",
        "label": f"Benchmark workcell {zone_index + 1}",
        "boundary": _rectangle(
            minimum_x,
            minimum_z,
            minimum_x + width,
            minimum_z + depth,
        ),
        "floorElevation": 0.0,
        "heightLimit": 8.0,
        "allowedAssetCategories": ["machine"],
        "gridSpacing": 0.5,
        "anchors": [],
        "evidence": [],
    }


def _placement_positions(spec: Mapping[str, Any]) -> list[tuple[float, float]]:
    count = int(spec["placementCount"])
    per_zone = int(spec["placementsPerZone"])
    width = float(spec["zoneWidthMeters"])
    depth = float(spec["zoneDepthMeters"])
    columns = int(spec["zoneColumns"])
    positions = []
    local_x = (3.0, 6.5, 10.0, 13.5, 17.0)
    if per_zone > len(local_x):
        raise ValueError("placementsPerZone exceeds the deterministic template")
    for index in range(count):
        zone_index = index // per_zone
        zone_column = zone_index % columns
        zone_row = zone_index // columns
        positions.append(
            (
                zone_column * width + local_x[index % per_zone],
                zone_row * depth + depth / 2.0,
            )
        )
    return positions


def _route(
    route_index: int,
    placements: Sequence[Mapping[str, Any]],
) -> JsonObject:
    source = placements[route_index]
    target = placements[route_index + 1]
    source_position = source["transform"]["position"]
    target_position = target["transform"]["position"]
    route = {
        "routeId": f"rt-bench-{route_index:04d}",
        "routeKind": "material",
        "sourceEndpoint": {
            "kind": "placement_connector",
            "placementId": source["placementId"],
            "connectorId": "material-out",
        },
        "targetEndpoint": {
            "kind": "placement_connector",
            "placementId": target["placementId"],
            "connectorId": "material-in",
        },
        "routingMode": "polyline",
        "centerline": [
            {
                "x": float(source_position["x"]) + 0.75,
                "y": 0.5,
                "z": float(source_position["z"]),
            },
            {
                "x": float(target_position["x"]) - 0.75,
                "y": 0.5,
                "z": float(target_position["z"]),
            },
        ],
        "corridorWidth": 1.0,
        "routeFingerprint": "0" * 64,
        "sourceRevisions": {
            "layout": "b" * 64,
            "asset": "a" * 64,
        },
        "requirements": [],
        "evidence": [],
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    return route


def _build_primary_fixture(spec: Mapping[str, Any]) -> JsonObject:
    zone_count = int(spec["zoneCount"])
    route_count = int(spec["routeCount"])
    positions = _placement_positions(spec)
    placements = [
        _placement(f"pl-bench-{index:04d}", x, z)
        for index, (x, z) in enumerate(positions)
    ]
    if route_count >= len(placements):
        raise ValueError("routeCount must be lower than placementCount")
    zones = [_zone(index, spec) for index in range(zone_count)]
    zone_columns = int(spec["zoneColumns"])
    zone_rows = math.ceil(zone_count / zone_columns)
    shell_width = zone_columns * float(spec["zoneWidthMeters"])
    shell_depth = zone_rows * float(spec["zoneDepthMeters"])
    layout = {
        "schemaVersion": 1,
        "layoutId": "fl-backend-release-benchmark",
        "displayName": "Backend release microbenchmark",
        "status": "draft",
        "association": {
            "siteId": "site-backend-benchmark",
            "areaId": "area-primary",
        },
        "coordinateFrame": {
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "datum-backend-benchmark",
            "floorElevation": 0,
        },
        "sourceShellRef": {
            "shellId": "shell-backend-benchmark",
            "shellRevision": "c" * 64,
            "coordinateFrameFingerprint": "d" * 64,
        },
        "catalogSnapshotRevision": "e" * 64,
        "policySetRef": {
            "policySetId": "policy-backend-benchmark",
            "policySetRevision": "f" * 64,
        },
        "zones": zones,
        "placements": placements,
        "routes": [
            _route(index, placements) for index in range(route_count)
        ],
        "utilityNetworks": [],
        "processBindings": [],
        "dismissedSuggestions": [],
        "createdAt": "2026-07-29T00:00:00Z",
        "updatedAt": "2026-07-29T00:00:00Z",
    }
    shell = {
        "schemaVersion": 1,
        "documentKind": "facility_shell",
        "shellId": "shell-backend-benchmark",
        "coordinateFrame": {"floorElevation": 0.0},
        "features": [
            {
                "featureId": "floor-backend-benchmark",
                "featureKind": "floor_surface",
                "geometry": {
                    "boundary": _rectangle(
                        -2.0,
                        -2.0,
                        shell_width + 2.0,
                        shell_depth + 2.0,
                    ),
                    "elevation": 0.0,
                },
            }
        ],
        "unresolvedItems": [],
    }
    policy_set = {
        "policySetId": "policy-backend-benchmark",
        "policySetRevision": "f" * 64,
        "rules": [],
        "unresolvedItems": [],
    }
    asset = _asset_definition()
    authority = _authority()
    target = deepcopy(placements[0])
    target["transform"]["position"] = {
        "x": float(placements[1]["transform"]["position"]["x"]),
        "y": 0.0,
        "z": float(placements[1]["transform"]["position"]["z"]),
    }
    candidate_requests = []
    width = float(spec["zoneWidthMeters"])
    depth = float(spec["zoneDepthMeters"])
    for request_index in range(31):
        zone_index = request_index % zone_count
        zone_column = zone_index % zone_columns
        zone_row = zone_index // zone_columns
        candidate_requests.append(
            {
                "x": zone_column * width + 3.0,
                "y": 0.0,
                "z": zone_row * depth + depth - 2.0,
            }
        )
    fixture = {
        "fixtureId": str(spec["fixtureId"]),
        "layout": layout,
        "assetDefinition": asset,
        "assetDefinitions": [asset],
        "shell": shell,
        "policySet": policy_set,
        "evidenceAuthority": authority,
        "movedPlacement": target,
        "candidateRequests": candidate_requests,
        "candidateMaximum": int(spec["candidateMaximum"]),
    }
    layout = canonicalize_layout(layout)
    fixture["layout"] = layout
    validate_layout(layout, require_canonical=True)
    return fixture


def _build_forklift_fixture(spec: Mapping[str, Any]) -> JsonObject:
    vehicle = {
        "vehicleProfileId": "vehicle-backend-benchmark",
        "vehicleProfileRevision": "1" * 64,
        "displayName": "Backend benchmark forklift",
        "overallDimensions": {
            "length": 1.2,
            "width": 0.8,
            "height": 1.8,
        },
        "footprint": _rectangle(-0.6, -0.4, 0.6, 0.4),
        "wheelbase": 0.8,
        "steeringLimits": {"minimumTurningRadiusMeters": 1.0},
        "speedLimits": {"maximumMetersPerSecond": 2.0},
        "loadLimits": {"maximumKilograms": 1000},
        "gradeLimits": {"maximumPercent": 8},
        "reversePolicy": "allowed",
    }
    return {
        "fixtureId": str(spec["fixtureId"]),
        "start": {"x": 1.0, "z": 2.0, "heading": 0.0},
        "goal": {
            "x": 18.0,
            "z": 14.0,
            "heading": math.pi / 2.0,
        },
        "vehicleProfile": vehicle,
        "traversablePolygons": [
            _rectangle(0.0, 0.0, 20.0, 4.0),
            _rectangle(16.0, 0.0, 20.0, 16.0),
        ],
        "obstacles": [],
        "load": None,
        "allowReverse": bool(spec["allowReverse"]),
        "gridResolutionMeters": float(spec["gridResolutionMeters"]),
        "maximumExpansions": int(spec["maximumExpansions"]),
        "sourceRevisions": {
            "layout": "2" * 64,
            "vehicle": "1" * 64,
        },
    }


def build_fixture_bundle(
    spec: Mapping[str, Any],
    *,
    smoke: bool,
) -> JsonObject:
    """Build deterministic benchmark fixtures directly from the pinned spec."""

    fixture_spec = spec["smokeFixture"] if smoke else spec["primaryFixture"]
    primary = _build_primary_fixture(fixture_spec)
    forklift = _build_forklift_fixture(spec["forkliftFixture"])
    return {
        "primary": primary,
        "forklift": forklift,
        "hashes": {
            "primary": _sha256_value(primary),
            "forklift": _sha256_value(forklift),
        },
    }


def _record_intersects(left: Any, right: Any) -> bool:
    return (
        height_intervals_intersect(left.interval, right.interval)
        and polygons_intersect(left.polygon, right.polygon)
    )


def _prepare_operations(
    fixture_bundle: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> tuple[dict[str, TimedOperation], dict[str, JsonObject]]:
    primary = fixture_bundle["primary"]
    layout = primary["layout"]
    asset = primary["assetDefinition"]
    target_id = str(primary["movedPlacement"]["placementId"])
    base_placements = [
        item for item in layout["placements"] if item["placementId"] != target_id
    ]
    physical_records = tuple(
        record
        for placement in base_placements
        for record in placement_spatial_records(placement, asset)
    )
    clearance_records = tuple(
        record
        for placement in base_placements
        for record in placement_clearance_records(
            placement,
            asset,
            evidence_authority=primary["evidenceAuthority"],
        )
    )
    physical_index = UniformGridSpatialIndex(physical_records)
    clearance_index = UniformGridSpatialIndex(clearance_records)
    moved_physical = placement_spatial_records(
        primary["movedPlacement"],
        asset,
    )
    moved_clearances = placement_clearance_records(
        primary["movedPlacement"],
        asset,
        evidence_authority=primary["evidenceAuthority"],
    )

    def moved_query(_: int) -> JsonObject:
        hits = sorted(
            {
                record_id
                for record in moved_physical
                for record_id in physical_index.query(record.bounds)
            }
        )
        return {
            "queryRecordCount": len(moved_physical),
            "candidateRecordIds": hits,
        }

    def collision_clearance(_: int) -> JsonObject:
        physical_hits: set[str] = set()
        candidate_clearance_hits: set[tuple[str, str]] = set()
        existing_clearance_hits: set[tuple[str, str]] = set()
        for record in moved_physical:
            for record_id in physical_index.query(record.bounds):
                other = physical_index.record(record_id)
                if _record_intersects(record, other):
                    physical_hits.add(other.owner_id)
            for record_id in clearance_index.query(record.bounds):
                other = clearance_index.record(record_id)
                if _record_intersects(record, other):
                    existing_clearance_hits.add(
                        (other.owner_id, str(other.clearance_id))
                    )
        for clearance in moved_clearances:
            for record_id in physical_index.query(clearance.bounds):
                other = physical_index.record(record_id)
                if _record_intersects(clearance, other):
                    candidate_clearance_hits.add(
                        (other.owner_id, str(clearance.clearance_id))
                    )
        return {
            "physicalCollisionOwnerIds": sorted(physical_hits),
            "candidateClearanceIntersections": [
                list(item) for item in sorted(candidate_clearance_hits)
            ],
            "existingClearanceIntersections": [
                list(item) for item in sorted(existing_clearance_hits)
            ],
        }

    candidate_requests = primary["candidateRequests"]

    def candidates(iteration: int) -> JsonObject:
        request_index = (
            len(candidate_requests) - 1
            if iteration < 0
            else iteration % (len(candidate_requests) - 1)
        )
        return generate_placement_candidates(
            layout,
            asset,
            candidate_requests[request_index],
            primary["assetDefinitions"],
            shell=primary["shell"],
            policy_set=primary["policySet"],
            evidence_authority=primary["evidenceAuthority"],
            enabled_families=(
                "grid",
                "boundary",
                "row",
                "bay",
                "alignment",
                "foundation",
            ),
            target_placement_id=target_id,
            asset_definition_revision=asset["assetDefinitionRevision"],
            maximum_candidates=int(primary["candidateMaximum"]),
        )

    def full_diagnostics(_: int) -> JsonObject:
        return diagnose_layout(
            layout,
            primary["assetDefinitions"],
            shell=primary["shell"],
            policy_set=primary["policySet"],
            evidence_authority=primary["evidenceAuthority"],
        )

    forklift = fixture_bundle["forklift"]

    def forklift_route(_: int) -> JsonObject:
        return plan_forklift_route(
            forklift["start"],
            forklift["goal"],
            forklift["vehicleProfile"],
            traversable_polygons=forklift["traversablePolygons"],
            obstacles=forklift["obstacles"],
            load=forklift["load"],
            allow_reverse=forklift["allowReverse"],
            grid_resolution_meters=forklift["gridResolutionMeters"],
            maximum_expansions=forklift["maximumExpansions"],
            source_revisions=forklift["sourceRevisions"],
        )

    sizes = {
        "moved_object_spatial_query": {
            "indexedPhysicalRecords": len(physical_records),
            "movedPhysicalRecords": len(moved_physical),
            "indexCellSizeMeters": physical_index.cell_size,
            "indexBuildIncluded": False,
        },
        "candidate_generation": {
            "placementCount": len(layout["placements"]),
            "zoneCount": len(layout["zones"]),
            "carriedRouteRecordCount": len(layout["routes"]),
            "maximumCandidates": int(primary["candidateMaximum"]),
            "enabledFamilyCount": 6,
            "resultCachePolicy": "distinct timed requests",
            "obstacleScenePolicy": "warmed once",
        },
        "collision_clearance_query": {
            "indexedPhysicalRecords": len(physical_records),
            "indexedClearanceRecords": len(clearance_records),
            "movedPhysicalRecords": len(moved_physical),
            "movedClearanceRecords": len(moved_clearances),
            "indexBuildIncluded": False,
            "narrowPhaseIncluded": True,
        },
        "full_diagnostics": {
            "placementCount": len(layout["placements"]),
            "zoneCount": len(layout["zones"]),
            "carriedRouteRecordCount": len(layout["routes"]),
            "assetDefinitionCount": len(primary["assetDefinitions"]),
            "shellFeatureCount": len(primary["shell"]["features"]),
            "policyRuleCount": len(primary["policySet"]["rules"]),
        },
        "forklift_routing": {
            "traversablePolygonCount": len(forklift["traversablePolygons"]),
            "traversableVertexCount": sum(
                len(item) for item in forklift["traversablePolygons"]
            ),
            "obstacleCount": len(forklift["obstacles"]),
            "loaded": forklift["load"] is not None,
            "allowReverse": forklift["allowReverse"],
            "gridResolutionMeters": forklift["gridResolutionMeters"],
            "maximumExpansions": forklift["maximumExpansions"],
        },
    }
    return {
        "moved_object_spatial_query": moved_query,
        "candidate_generation": candidates,
        "collision_clearance_query": collision_clearance,
        "full_diagnostics": full_diagnostics,
        "forklift_routing": forklift_route,
    }, sizes


def _summarize_output(operation_id: str, output: Mapping[str, Any]) -> JsonObject:
    if operation_id == "moved_object_spatial_query":
        return {
            "candidateRecordCount": len(output["candidateRecordIds"]),
            "queryRecordCount": output["queryRecordCount"],
        }
    if operation_id == "candidate_generation":
        return {
            "candidateCount": len(output.get("candidates", [])),
            "evaluatedCount": output.get("evaluatedCount"),
            "seedCount": output.get("seedCount"),
            "rejectionCounts": deepcopy(output.get("rejectionCounts", {})),
        }
    if operation_id == "collision_clearance_query":
        return {
            "physicalCollisionCount": len(
                output["physicalCollisionOwnerIds"]
            ),
            "candidateClearanceIntersectionCount": len(
                output["candidateClearanceIntersections"]
            ),
            "existingClearanceIntersectionCount": len(
                output["existingClearanceIntersections"]
            ),
        }
    if operation_id == "full_diagnostics":
        return {
            "safetyStatus": output.get("safetyStatus"),
            "valid": output.get("valid"),
            "findingCount": len(output.get("findings", [])),
            "metrics": deepcopy(output.get("metrics", {})),
        }
    if operation_id == "forklift_routing":
        return {
            "accepted": output.get("accepted"),
            "distanceMeters": output.get("distanceMeters"),
            "actionCount": len(output.get("actions", [])),
            "poseCount": len(output.get("poses", [])),
            "findingCodes": [
                item.get("code") for item in output.get("findings", [])
            ],
        }
    return {"outputSha256": _sha256_value(output)}


def _p95(samples: Sequence[float]) -> float:
    if len(samples) < 2:
        return float(samples[0])
    return statistics.quantiles(
        samples,
        n=100,
        method="inclusive",
    )[94]


def _measure_operation(
    *,
    operation_id: str,
    operation: TimedOperation,
    input_sizes: Mapping[str, Any],
    measured_iterations: int,
    budget_p95_ms: float,
    budget_source: str,
    claim_kind: str,
) -> JsonObject:
    try:
        operation(-1)
        durations = []
        output_hashes = []
        first_output = None
        for iteration in range(measured_iterations):
            started = time.perf_counter_ns()
            output = operation(iteration)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            durations.append(round(elapsed_ms, 6))
            output_hashes.append(_sha256_value(output))
            if first_output is None:
                first_output = deepcopy(output)
        deterministic_left = operation(0)
        deterministic_right = operation(0)
    except Exception as exc:
        return {
            "operationId": operation_id,
            "required": True,
            "availability": "unavailable",
            "unavailableReason": {
                "exceptionType": type(exc).__name__,
                "message": str(exc),
            },
            "inputSizes": deepcopy(dict(input_sizes)),
            "rawSamplesMs": [],
            "outputHashes": [],
            "determinism": {"passed": False},
            "budget": {
                "metric": "p95Milliseconds",
                "limit": budget_p95_ms,
                "source": budget_source,
                "passed": False,
            },
            "claimKind": claim_kind,
        }
    median = statistics.median(durations)
    p95 = _p95(durations)
    determinism_left_hash = _sha256_value(deterministic_left)
    determinism_right_hash = _sha256_value(deterministic_right)
    return {
        "operationId": operation_id,
        "required": True,
        "availability": "available",
        "claimKind": claim_kind,
        "inputSizes": deepcopy(dict(input_sizes)),
        "warmupIterations": 1,
        "measuredIterations": measured_iterations,
        "rawSamplesMs": durations,
        "summaryMilliseconds": {
            "median": round(median, 6),
            "p95": round(p95, 6),
            "minimum": round(min(durations), 6),
            "maximum": round(max(durations), 6),
        },
        "outputHashes": output_hashes,
        "outputSequenceSha256": _sha256_value(output_hashes),
        "determinism": {
            "probeInputIndex": 0,
            "firstOutputSha256": determinism_left_hash,
            "secondOutputSha256": determinism_right_hash,
            "passed": determinism_left_hash == determinism_right_hash,
        },
        "sampleOutputSummary": _summarize_output(
            operation_id,
            first_output,
        ),
        "budget": {
            "metric": "p95Milliseconds",
            "measured": round(p95, 6),
            "limit": budget_p95_ms,
            "unit": "ms",
            "source": budget_source,
            "passed": p95 <= budget_p95_ms,
        },
    }


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip().lower()
    return value if len(value) == 40 else None


def _cpu_name() -> str | None:
    candidates = [
        os.environ.get("PROCESSOR_IDENTIFIER"),
        platform.processor(),
    ]
    if os.name != "nt":
        try:
            for line in Path("/proc/cpuinfo").read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines():
                if line.lower().startswith("model name"):
                    candidates.append(line.split(":", 1)[1].strip())
                    break
        except OSError:
            pass
    return next(
        (value.strip() for value in candidates if value and value.strip()),
        None,
    )


def _ram_bytes() -> int | None:
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
                ctypes.byref(status)
            ):
                return int(status.ullTotalPhys)
        except (AttributeError, OSError):
            return None
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return pages * page_size
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _environment() -> JsonObject:
    cpu = _cpu_name()
    ram = _ram_bytes()
    return {
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "operatingSystem": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "cpu": {
            "name": cpu,
            "logicalProcessorCount": os.cpu_count(),
            "available": cpu is not None,
        },
        "ram": {
            "totalBytes": ram,
            "available": ram is not None,
        },
    }


def _source_binding(spec_path: Path) -> JsonObject:
    commit = _git_commit()
    files = []
    for path in (
        RUNNER_PATH,
        spec_path,
        SPATIAL_CONTRACT_PATH,
        SPATIAL_SOURCE_PATH,
        ROUTING_SOURCE_PATH,
    ):
        files.append(
            {
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "byteLength": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return {
        "sourceCommit": commit,
        "sourceCommitAvailable": commit is not None,
        "files": files,
        "aggregateFileSha256": _sha256_value(files),
    }


def _fixture_evidence(
    fixture_bundle: Mapping[str, Any],
) -> JsonObject:
    primary = fixture_bundle["primary"]
    layout = primary["layout"]
    forklift = fixture_bundle["forklift"]
    return {
        "generation": "deterministic_in_memory_from_pinned_spec",
        "primary": {
            "fixtureId": primary["fixtureId"],
            "sha256": fixture_bundle["hashes"]["primary"],
            "canonicalByteLength": len(_canonical_bytes(primary)),
            "inputSizes": {
                "placementCount": len(layout["placements"]),
                "zoneCount": len(layout["zones"]),
                "zoneVertexCount": sum(
                    len(zone["boundary"]) for zone in layout["zones"]
                ),
                "routeCount": len(layout["routes"]),
                "routePointCount": sum(
                    len(route["centerline"]) for route in layout["routes"]
                ),
                "assetDefinitionCount": len(
                    primary["assetDefinitions"]
                ),
                "shellFeatureCount": len(primary["shell"]["features"]),
                "policyRuleCount": len(primary["policySet"]["rules"]),
            },
        },
        "forklift": {
            "fixtureId": forklift["fixtureId"],
            "sha256": fixture_bundle["hashes"]["forklift"],
            "canonicalByteLength": len(_canonical_bytes(forklift)),
            "inputSizes": {
                "traversablePolygonCount": len(
                    forklift["traversablePolygons"]
                ),
                "traversableVertexCount": sum(
                    len(item) for item in forklift["traversablePolygons"]
                ),
                "obstacleCount": len(forklift["obstacles"]),
                "loaded": forklift["load"] is not None,
                "allowReverse": forklift["allowReverse"],
                "gridResolutionMeters": forklift[
                    "gridResolutionMeters"
                ],
                "maximumExpansions": forklift["maximumExpansions"],
            },
        },
    }


def deterministic_result_manifest(result: Mapping[str, Any]) -> JsonObject:
    """Return the timing-independent evidence used by focused tests."""

    return {
        "mode": result["mode"],
        "fixtures": {
            key: value["sha256"]
            for key, value in result["fixtures"].items()
            if isinstance(value, Mapping) and "sha256" in value
        },
        "operations": [
            {
                "operationId": item["operationId"],
                "availability": item["availability"],
                "outputSequenceSha256": item.get("outputSequenceSha256"),
                "determinismProbeSha256": (
                    item.get("determinism", {}).get(
                        "firstOutputSha256"
                    )
                ),
                "sampleOutputSummary": item.get("sampleOutputSummary"),
            }
            for item in result["operations"]
        ],
    }


def run_benchmark(
    *,
    smoke: bool = False,
    spec_path: Path = DEFAULT_SPEC_PATH,
) -> JsonObject:
    """Run the benchmark and return its complete evidence artifact."""

    spec = _read_json(spec_path)
    measured_iterations = int(
        spec["protocol"][
            "smokeMeasuredIterations" if smoke else "measuredIterations"
        ]
    )
    fixture_bundle = build_fixture_bundle(spec, smoke=smoke)
    operations, input_sizes = _prepare_operations(fixture_bundle, spec)
    operation_specs = {
        item["operationId"]: item for item in spec["operations"]
    }
    measured = []
    for operation_id in (
        "moved_object_spatial_query",
        "candidate_generation",
        "collision_clearance_query",
        "full_diagnostics",
        "forklift_routing",
    ):
        operation_spec = operation_specs[operation_id]
        measured.append(
            _measure_operation(
                operation_id=operation_id,
                operation=operations[operation_id],
                input_sizes=input_sizes[operation_id],
                measured_iterations=measured_iterations,
                budget_p95_ms=float(
                    operation_spec["budgetP95Milliseconds"]
                ),
                budget_source=str(operation_spec["budgetSource"]),
                claim_kind=str(operation_spec["claimKind"]),
            )
        )
    required_available = all(
        item["availability"] == "available" for item in measured
    )
    determinism_passed = all(
        item.get("determinism", {}).get("passed") is True
        for item in measured
    )
    budgets_passed = all(
        item.get("budget", {}).get("passed") is True for item in measured
    )
    source = _source_binding(spec_path)
    environment = _environment()
    environment_complete = (
        environment["cpu"]["available"]
        and environment["ram"]["available"]
    )
    release_slice_passed = (
        not smoke
        and required_available
        and determinism_passed
        and budgets_passed
        and source["sourceCommitAvailable"]
        and environment_complete
    )
    result = {
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "benchmarkId": spec["benchmarkId"],
        "generatedAtUtc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "mode": "smoke" if smoke else "release",
        "releaseEligible": not smoke,
        "protocol": {
            "timer": spec["protocol"]["timer"],
            "warmupIterations": int(
                spec["protocol"]["warmupIterations"]
            ),
            "measuredIterations": measured_iterations,
            "percentile": int(spec["protocol"]["percentile"]),
            "percentileMethod": spec["protocol"]["percentileMethod"],
            "rawSamplesRetained": True,
            "singleProcess": True,
            "operationOrder": [
                item["operationId"] for item in measured
            ],
        },
        "source": source,
        "environment": environment,
        "fixtures": _fixture_evidence(fixture_bundle),
        "operations": measured,
        "unavailableOperations": deepcopy(
            spec.get("unavailableOperations", [])
        ),
        "requiredOperationsAvailable": required_available,
        "determinismPassed": determinism_passed,
        "budgetsPassed": budgets_passed,
        "provenanceComplete": (
            source["sourceCommitAvailable"] and environment_complete
        ),
        "releaseSlicePassed": release_slice_passed,
        "claimBoundary": deepcopy(spec["claimBoundary"]),
    }
    result["deterministicEvidenceSha256"] = _sha256_value(
        deterministic_result_manifest(result)
    )
    if smoke:
        result["releaseSlicePassed"] = False
        result["smokePassed"] = (
            required_available and determinism_passed
        )
    return result


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("ascii") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure deterministic Facility Layout backend release slices."
        )
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run the reduced non-release fixture with three raw iterations.",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC_PATH,
        help="Pinned benchmark spec.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Artifact path. Release mode defaults to the committed result "
            "fixture; smoke mode prints only unless this is supplied."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_benchmark(
        smoke=bool(args.smoke),
        spec_path=args.spec.resolve(),
    )
    output_path = args.output
    if output_path is None and not args.smoke:
        output_path = DEFAULT_RESULT_PATH
    if output_path is not None:
        resolved = (
            output_path
            if output_path.is_absolute()
            else REPO_ROOT / output_path
        )
        _write_json_atomic(resolved, result)
        print(f"Wrote {resolved}")
    print(
        json.dumps(
            {
                "mode": result["mode"],
                "requiredOperationsAvailable": result[
                    "requiredOperationsAvailable"
                ],
                "determinismPassed": result["determinismPassed"],
                "budgetsPassed": result["budgetsPassed"],
                "releaseSlicePassed": result["releaseSlicePassed"],
                "operations": [
                    {
                        "operationId": item["operationId"],
                        "availability": item["availability"],
                        "medianMs": item.get(
                            "summaryMilliseconds", {}
                        ).get("median"),
                        "p95Ms": item.get(
                            "summaryMilliseconds", {}
                        ).get("p95"),
                        "budgetPassed": item.get("budget", {}).get(
                            "passed"
                        ),
                    }
                    for item in result["operations"]
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.smoke:
        return 0 if result.get("smokePassed") else 2
    return 0 if result["releaseSlicePassed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
