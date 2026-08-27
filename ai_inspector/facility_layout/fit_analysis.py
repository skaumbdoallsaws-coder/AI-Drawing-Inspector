"""Bounded, read-only spatial fit analysis for Facility Layout agents.

The model selects an exact revisioned asset and an authored zone. The server
owns every probe coordinate, executes the existing deterministic candidate
engine, and then verifies target-zone, route, marking, and clearance
constraints. A bounded fit result is never represented as maximum capacity.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Iterable, Mapping, Sequence

try:
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
except ImportError:  # pragma: no cover - deployment preflight covers this.
    LineString = None
    Polygon = None
    unary_union = None

from .spatial import (
    canonical_spatial_bytes,
    generate_placement_candidates,
    oriented_box_polygon,
    placement_clearance_records,
    placement_spatial_records,
    point_in_polygon,
    polygon_bounds,
    polygon_contains_polygon,
)


FACILITY_FIT_ANALYSIS_VERSION = 1
_SUPPORTED_ORIENTATIONS = (0, 90, 180, 270)
_PROBE_FRACTIONS = (0.05, 0.275, 0.5, 0.725, 0.95)
_PROTECTED_MARKING_TERMS = frozenset(
    {
        "aisle",
        "crosswalk",
        "egress",
        "exit_route",
        "forklift_lane",
        "keep_clear",
        "no_entry",
        "pedestrian_lane",
        "pedestrian_walkway",
        "restricted",
        "safety_boundary",
    }
)
_PROTECTED_ZONE_TERMS = frozenset(
    {
        "egress",
        "keep_clear",
        "no_entry",
        "restricted",
        "safety_restricted",
    }
)


class FacilityFitAnalysisError(ValueError):
    """Stable validation failure for read-only fit analysis."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _asset_field(
    asset: Mapping[str, Any],
    name: str,
    default: Any = None,
) -> Any:
    if name in asset:
        return asset[name]
    definition = asset.get("definition")
    if isinstance(definition, Mapping) and name in definition:
        return definition[name]
    return default


def _asset_index(
    values: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        asset_id = str(_asset_field(value, "assetId") or "")
        revision = str(
            _asset_field(value, "assetDefinitionRevision") or ""
        )
        if asset_id and revision:
            result[(asset_id, revision)] = value
    return result


def _polygon_points(value: Any) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    points = []
    try:
        for item in value:
            if not isinstance(item, Mapping):
                return None
            points.append((float(item["x"]), float(item["z"])))
    except (KeyError, TypeError, ValueError):
        return None
    return tuple(points)


def _zone_boundary(zone: Mapping[str, Any]) -> tuple[tuple[float, float], ...]:
    boundary = _polygon_points(zone.get("boundary"))
    if boundary is None:
        raise FacilityFitAnalysisError(
            "facility_fit_zone_geometry_unavailable",
            "The selected zone has no usable authored boundary.",
        )
    return boundary


def _probe_anchors(
    zone: Mapping[str, Any],
    boundary: Sequence[tuple[float, float]],
) -> list[dict[str, Any]]:
    low_x, low_z, high_x, high_z = polygon_bounds(boundary)
    elevation = float(zone.get("floorElevation") or 0.0)
    anchors = []
    for z_index, z_fraction in enumerate(_PROBE_FRACTIONS):
        z_value = low_z + (high_z - low_z) * z_fraction
        for x_index, x_fraction in enumerate(_PROBE_FRACTIONS):
            x_value = low_x + (high_x - low_x) * x_fraction
            if not point_in_polygon((x_value, z_value), boundary):
                continue
            anchors.append(
                {
                    "anchorId": (
                        f"fit-probe-{z_index + 1:02d}-{x_index + 1:02d}"
                    ),
                    "anchorKind": "bay",
                    "position": {
                        "x": round(x_value, 9),
                        "y": round(elevation, 9),
                        "z": round(z_value, 9),
                    },
                }
            )
    return anchors


def _quaternion(degrees: int) -> dict[str, float]:
    half_angle = math.radians(degrees) / 2.0
    return {
        "x": 0.0,
        "y": round(math.sin(half_angle), 12),
        "z": 0.0,
        "w": round(math.cos(half_angle), 12),
    }


def _normalized_text(value: Any) -> str:
    return "_".join(str(value or "").strip().casefold().split())


def _marking_polygon(marking: Mapping[str, Any]) -> tuple[tuple[float, float], ...] | None:
    for key in ("boundary", "polygon", "points"):
        polygon = _polygon_points(marking.get(key))
        if polygon is not None:
            return polygon
    geometry = marking.get("geometry")
    if isinstance(geometry, Mapping):
        for key in ("boundary", "polygon", "points"):
            polygon = _polygon_points(geometry.get(key))
            if polygon is not None:
                return polygon
    transform = marking.get("transform")
    position = (
        transform.get("position")
        if isinstance(transform, Mapping)
        and isinstance(transform.get("position"), Mapping)
        else {}
    )
    try:
        width = float(marking.get("width"))
        depth = float(marking.get("depth"))
        x_value = float(position["x"])
        z_value = float(position["z"])
        degrees = float(
            transform.get("rotationDegrees", marking.get("rotationDegrees", 0))
            if isinstance(transform, Mapping)
            else marking.get("rotationDegrees", 0)
        )
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or depth <= 0:
        return None
    return oriented_box_polygon(
        (x_value, z_value),
        (width / 2.0, depth / 2.0),
        math.radians(degrees),
    )


def _protected_geometries(
    layout: Mapping[str, Any],
    *,
    target_zone_id: str,
) -> list[tuple[str, str, Any]]:
    if Polygon is None or LineString is None or unary_union is None:
        raise FacilityFitAnalysisError(
            "facility_fit_geometry_engine_unavailable",
            "Exact protected-route geometry requires the configured geometry engine.",
        )
    result: list[tuple[str, str, Any]] = []
    for route in layout.get("routes", []):
        if not isinstance(route, Mapping):
            continue
        route_id = str(route.get("routeId") or "")
        centerline = route.get("centerline")
        if not route_id or not isinstance(centerline, list):
            continue
        points = []
        try:
            for item in centerline:
                if not isinstance(item, Mapping):
                    raise TypeError
                points.append((float(item["x"]), float(item["z"])))
            width = float(
                route.get("corridorWidth", route.get("width", 0))
            )
        except (KeyError, TypeError, ValueError):
            continue
        if len(points) >= 2 and width > 0:
            result.append(
                (
                    "protected_route",
                    route_id,
                    LineString(points).buffer(
                        width / 2.0,
                        cap_style=2,
                        join_style=2,
                    ),
                )
            )
    for marking in layout.get("floorMarkings", []):
        if not isinstance(marking, Mapping):
            continue
        terms = {
            _normalized_text(marking.get("markingType")),
            _normalized_text(marking.get("semanticRole")),
        }
        if not terms.intersection(_PROTECTED_MARKING_TERMS):
            continue
        polygon = _marking_polygon(marking)
        marking_id = str(marking.get("markingId") or "")
        if polygon is not None and marking_id:
            result.append(
                ("protected_floor_marking", marking_id, Polygon(polygon))
            )
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping):
            continue
        zone_id = str(zone.get("zoneId") or "")
        if not zone_id or zone_id == target_zone_id:
            continue
        terms = {
            _normalized_text(zone.get("zoneType")),
            _normalized_text(zone.get("semanticType")),
        }
        if not terms.intersection(_PROTECTED_ZONE_TERMS):
            continue
        boundary = _polygon_points(zone.get("boundary"))
        if boundary is not None:
            result.append(("protected_zone", zone_id, Polygon(boundary)))
    return result


def _candidate_placement(
    candidate: Mapping[str, Any],
    *,
    asset_id: str,
    revision: str,
) -> dict[str, Any]:
    return {
        "placementId": "pl-facility-fit-analysis",
        "assetId": asset_id,
        "assetDefinitionRevision": revision,
        "positionMode": "auto",
        "transform": deepcopy(candidate["transform"]),
        "metadata": {},
    }


def _record_union(records: Iterable[Any]) -> Any:
    polygons = [Polygon(record.polygon) for record in records]
    return unary_union(polygons) if polygons else None


def _validate_orientations(values: Sequence[int] | None) -> tuple[int, ...]:
    raw = list(values) if values is not None else [0, 90]
    if not raw or len(raw) > len(_SUPPORTED_ORIENTATIONS):
        raise FacilityFitAnalysisError(
            "facility_fit_orientations_invalid",
            "orientationsDegrees must contain one to four supported values.",
        )
    result = []
    for value in raw:
        if isinstance(value, bool):
            raise FacilityFitAnalysisError(
                "facility_fit_orientations_invalid",
                "orientationsDegrees accepts only 0, 90, 180, or 270.",
            )
        try:
            integer = int(value)
        except (TypeError, ValueError) as exc:
            raise FacilityFitAnalysisError(
                "facility_fit_orientations_invalid",
                "orientationsDegrees accepts only 0, 90, 180, or 270.",
            ) from exc
        if integer != value or integer not in _SUPPORTED_ORIENTATIONS:
            raise FacilityFitAnalysisError(
                "facility_fit_orientations_invalid",
                "orientationsDegrees accepts only 0, 90, 180, or 270.",
            )
        if integer not in result:
            result.append(integer)
    return tuple(result)


def analyze_facility_asset_fit(
    layout: Mapping[str, Any],
    asset_definitions: Sequence[Mapping[str, Any]],
    *,
    asset_id: str,
    asset_definition_revision: str,
    zone_id: str,
    shell: Mapping[str, Any] | None = None,
    policy_set: Mapping[str, Any] | None = None,
    evidence_authority: Mapping[str, Any] | None = None,
    orientations_degrees: Sequence[int] | None = None,
    maximum_results: int = 8,
) -> dict[str, Any]:
    """Find bounded candidate placements without mutating the layout."""

    if isinstance(maximum_results, bool) or not 1 <= maximum_results <= 8:
        raise FacilityFitAnalysisError(
            "facility_fit_result_limit_invalid",
            "maximumResults must be between 1 and 8.",
        )
    orientations = _validate_orientations(orientations_degrees)
    catalog = _asset_index(asset_definitions)
    asset = catalog.get((asset_id, asset_definition_revision))
    if asset is None:
        return {
            "fitAnalysisVersion": FACILITY_FIT_ANALYSIS_VERSION,
            "status": "blocked",
            "assetId": asset_id,
            "assetDefinitionRevision": asset_definition_revision,
            "zoneId": zone_id,
            "blockerCodes": ["exact_asset_revision_unavailable"],
            "geometricFitFound": False,
            "clearanceValidatedFitFound": False,
            "fullyValidatedFitFound": False,
            "candidates": [],
        }
    zones = [
        item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping) and str(item.get("zoneId") or "") == zone_id
    ]
    if len(zones) != 1:
        return {
            "fitAnalysisVersion": FACILITY_FIT_ANALYSIS_VERSION,
            "status": "blocked",
            "assetId": asset_id,
            "assetDefinitionRevision": asset_definition_revision,
            "zoneId": zone_id,
            "blockerCodes": ["authored_zone_unavailable"],
            "geometricFitFound": False,
            "clearanceValidatedFitFound": False,
            "fullyValidatedFitFound": False,
            "candidates": [],
        }
    target_zone = deepcopy(dict(zones[0]))
    boundary = _zone_boundary(target_zone)
    probes = _probe_anchors(target_zone, boundary)
    if not probes:
        return {
            "fitAnalysisVersion": FACILITY_FIT_ANALYSIS_VERSION,
            "status": "blocked",
            "assetId": asset_id,
            "assetDefinitionRevision": asset_definition_revision,
            "zoneId": zone_id,
            "blockerCodes": ["zone_has_no_bounded_probe_points"],
            "geometricFitFound": False,
            "clearanceValidatedFitFound": False,
            "fullyValidatedFitFound": False,
            "candidates": [],
        }

    before = canonical_spatial_bytes(layout)
    analysis_layout = deepcopy(dict(layout))
    prepared_zones = []
    for raw_zone in layout.get("zones", []):
        if not isinstance(raw_zone, Mapping):
            continue
        prepared = deepcopy(dict(raw_zone))
        prepared["anchors"] = probes if prepared.get("zoneId") == zone_id else []
        prepared_zones.append(prepared)
    analysis_layout["zones"] = prepared_zones
    low_x, low_z, high_x, high_z = polygon_bounds(boundary)
    requested = {
        "x": round((low_x + high_x) / 2.0, 9),
        "y": round(float(target_zone.get("floorElevation") or 0.0), 9),
        "z": round((low_z + high_z) / 2.0, 9),
    }
    protected = _protected_geometries(
        layout,
        target_zone_id=zone_id,
    )
    accepted = []
    rejection_counts: dict[str, int] = {}
    engine_evaluated = 0
    engine_seed_count = 0
    for orientation in orientations:
        try:
            generated = generate_placement_candidates(
                analysis_layout,
                asset,
                requested,
                asset_definitions,
                shell=shell,
                policy_set=policy_set,
                evidence_authority=evidence_authority,
                enabled_families=("bay",),
                requested_quaternion=_quaternion(orientation),
                asset_definition_revision=asset_definition_revision,
                maximum_candidates=64,
            )
        except (TypeError, ValueError) as exc:
            return {
                "fitAnalysisVersion": FACILITY_FIT_ANALYSIS_VERSION,
                "status": "blocked",
                "assetId": asset_id,
                "assetDefinitionRevision": asset_definition_revision,
                "zoneId": zone_id,
                "blockerCodes": ["asset_spatial_geometry_unavailable"],
                "blockerDetail": " ".join(str(exc).split())[:240],
                "geometricFitFound": False,
                "clearanceValidatedFitFound": False,
                "fullyValidatedFitFound": False,
                "candidates": [],
            }
        engine_evaluated += int(generated.get("evaluatedCount") or 0)
        engine_seed_count += int(generated.get("seedCount") or 0)
        for code, count in generated.get("rejectionCounts", {}).items():
            rejection_counts[str(code)] = (
                rejection_counts.get(str(code), 0) + int(count)
            )
        for candidate in generated.get("candidates", []):
            placement = _candidate_placement(
                candidate,
                asset_id=asset_id,
                revision=asset_definition_revision,
            )
            physical = placement_spatial_records(placement, asset)
            clearances = placement_clearance_records(
                placement,
                asset,
                evidence_authority=evidence_authority,
            )
            candidate_codes = []
            if not physical or not all(
                polygon_contains_polygon(boundary, record.polygon)
                for record in physical
            ):
                candidate_codes.append("candidate_outside_target_zone")
            clearance_inside = bool(clearances) and all(
                polygon_contains_polygon(boundary, record.polygon)
                for record in clearances
            )
            if clearances and not clearance_inside:
                candidate_codes.append("clearance_outside_target_zone")
            physical_union = _record_union(physical)
            clearance_union = _record_union(clearances)
            protected_hits = []
            for kind, protected_id, geometry in protected:
                if (
                    physical_union is not None
                    and physical_union.intersects(geometry)
                ) or (
                    clearance_union is not None
                    and clearance_union.intersects(geometry)
                ):
                    protected_hits.append(
                        {"kind": kind, "id": protected_id}
                    )
            if protected_hits:
                candidate_codes.append("protected_space_intrusion")
            metrics = candidate.get("metrics", {})
            if int(metrics.get("physicalCollisions") or 0) > 0:
                candidate_codes.append("placement_collision")
            if int(metrics.get("clearanceConflicts") or 0) > 0:
                candidate_codes.append("clearance_conflict")
            geometric_valid = not {
                "candidate_outside_target_zone",
                "placement_collision",
                "protected_space_intrusion",
            }.intersection(candidate_codes)
            clearances_authoritative = bool(clearances) and all(
                record.authoritative for record in clearances
            )
            clearance_validated = bool(
                geometric_valid
                and clearance_inside
                and clearances_authoritative
                and "clearance_conflict" not in candidate_codes
            )
            fully_validated = bool(
                clearance_validated
                and candidate.get("safetyStatus") == "safe"
            )
            if not geometric_valid:
                for code in sorted(set(candidate_codes)):
                    rejection_counts[code] = rejection_counts.get(code, 0) + 1
                continue
            position = candidate["transform"]["position"]
            accepted.append(
                {
                    "candidateId": candidate["candidateId"],
                    "family": candidate.get("family"),
                    "orientationDegrees": orientation,
                    "transform": deepcopy(candidate["transform"]),
                    "distanceFromZoneCenterMeters": round(
                        math.hypot(
                            float(position["x"]) - requested["x"],
                            float(position["z"]) - requested["z"],
                        ),
                        6,
                    ),
                    "geometricValid": True,
                    "clearanceValidated": clearance_validated,
                    "fullyValidated": fully_validated,
                    "clearanceEvidenceComplete": clearances_authoritative,
                    "safetyStatus": candidate.get("safetyStatus"),
                    "protectedSpaceHits": protected_hits,
                    "blockerCodes": sorted(set(candidate_codes)),
                    "metrics": {
                        "physicalCollisions": int(
                            metrics.get("physicalCollisions") or 0
                        ),
                        "clearanceConflicts": int(
                            metrics.get("clearanceConflicts") or 0
                        ),
                        "unverifiedCount": int(
                            metrics.get("unverifiedCount") or 0
                        ),
                        "warningCount": int(
                            metrics.get("warningCount") or 0
                        ),
                    },
                }
            )
    if canonical_spatial_bytes(layout) != before:
        raise RuntimeError("read-only fit analysis mutated the source layout")
    accepted.sort(
        key=lambda item: (
            not item["fullyValidated"],
            not item["clearanceValidated"],
            item["metrics"]["unverifiedCount"],
            item["metrics"]["warningCount"],
            item["distanceFromZoneCenterMeters"],
            item["orientationDegrees"],
            item["candidateId"],
        )
    )
    returned = accepted[:maximum_results]
    return {
        "fitAnalysisVersion": FACILITY_FIT_ANALYSIS_VERSION,
        "status": "complete",
        "analysisMode": "read_only_bounded_single_asset_fit",
        "assetId": asset_id,
        "assetDefinitionRevision": asset_definition_revision,
        "zoneId": zone_id,
        "orientationsDegrees": list(orientations),
        "probeCount": len(probes),
        "engineSeedCount": engine_seed_count,
        "engineEvaluatedCount": engine_evaluated,
        "acceptedCandidateCount": len(accepted),
        "returnedCandidateCount": len(returned),
        "geometricFitFound": bool(accepted),
        "clearanceValidatedFitFound": any(
            item["clearanceValidated"] for item in accepted
        ),
        "fullyValidatedFitFound": any(
            item["fullyValidated"] for item in accepted
        ),
        "rejectionCounts": {
            key: rejection_counts[key] for key in sorted(rejection_counts)
        },
        "candidates": returned,
        "evidenceClassification": {
            "assetAndZoneIdentity": "authored",
            "candidateGeometry": "derived",
            "fitSearchCompleteness": "bounded_not_exhaustive",
            "maximumAdditionalCapacity": "unknown",
            "productionCapacity": "unknown",
        },
        "qualification": (
            "This proves only whether the bounded deterministic search found "
            "a valid placement for one exact asset revision. It does not prove "
            "maximum spatial capacity or production throughput."
        ),
        "mutated": False,
    }


__all__ = [
    "FACILITY_FIT_ANALYSIS_VERSION",
    "FacilityFitAnalysisError",
    "analyze_facility_asset_fit",
]
