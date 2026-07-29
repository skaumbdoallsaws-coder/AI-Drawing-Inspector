"""Pure deterministic Facility Layout proposals and ghost alternatives.

P8 deliberately separates three concerns:

* callers describe an outcome without supplying world or screen coordinates;
* this module computes deterministic candidate geometry and route diagnostics;
* the existing operation kernel remains the only mutation language.

The returned alternatives are immutable preview artifacts. Applying an
alternative means submitting its exact ``operations`` array through the
existing revision-aware preview/apply service.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_layout_bytes, canonicalize_layout, layout_revision
from .errors import FacilityValidationError
from .operations import apply_facility_layout_operations
from .routing import (
    persisted_route_fingerprint,
    plan_forklift_route,
    resolve_endpoint,
    routing_layout_fingerprint,
)
from .spatial import (
    diagnose_layout,
    generate_placement_candidates,
    placement_spatial_records,
)


FACILITY_LAYOUT_PLANNER_VERSION = "1.0.0"
FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION = 1
FACILITY_LAYOUT_ALTERNATIVE_POLICY_VERSION = "1.0.0"
MAXIMUM_PLANNED_INSTANCES = 500
MAXIMUM_ALTERNATIVES = 4
MAXIMUM_SEARCH_RING = 8

_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_STRATEGIES = ("compact_rows", "balanced_grid", "flow_lanes")
_OBJECTIVES = ("place_asset_set", "cleanup_layout", "place_and_cleanup")
_RAW_GEOMETRY_KEYS = frozenset(
    {
        "camera",
        "centerline",
        "matrix",
        "pixels",
        "position",
        "quaternion",
        "routepoints",
        "screen",
        "transform",
        "viewport",
        "worldposition",
        "x",
        "y",
        "z",
    }
)
_HARD_SEVERITIES = frozenset(("error", "blocked"))


class FacilityLayoutPlanningError(ValueError):
    """Typed, deterministic planner rejection."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = deepcopy(dict(details or {}))

    def finding(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": "error",
            "message": self.message,
            "details": deepcopy(self.details),
        }


def _fail(
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> None:
    raise FacilityLayoutPlanningError(code, message, details=details)


def _canonical_value(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except (TypeError, ValueError) as exc:
        raise FacilityLayoutPlanningError(
            "invalid_planner_value",
            "Planner inputs must contain finite JSON values.",
        ) from exc


def canonical_planner_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def planner_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_planner_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}{planner_fingerprint(value)[:length]}"


def _finite_number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("invalid_planner_request", f"{field} must be a finite number.")
    number = float(value)
    if not math.isfinite(number):
        _fail("invalid_planner_request", f"{field} must be a finite number.")
    if minimum is not None and number < minimum:
        _fail(
            "invalid_planner_request",
            f"{field} must be at least {minimum}.",
        )
    if maximum is not None and number > maximum:
        _fail(
            "invalid_planner_request",
            f"{field} must be at most {maximum}.",
        )
    return number


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_planner_request", f"{field} is required.")
    result = value.strip()
    if len(result) > 128:
        _fail("invalid_planner_request", f"{field} is too long.")
    return result


def _revision(value: Any, field: str) -> str:
    result = _required_string(value, field)
    if not _REVISION_RE.fullmatch(result):
        _fail(
            "invalid_planner_request",
            f"{field} must be a lowercase SHA-256 revision.",
        )
    return result


def _reject_raw_geometry(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in _RAW_GEOMETRY_KEYS:
                _fail(
                    "raw_geometry_forbidden",
                    "Declarative layout requests cannot supply coordinates, "
                    "camera state, route points, or transforms.",
                    details={"path": f"{path}.{key}"},
                )
            _reject_raw_geometry(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_raw_geometry(child, f"{path}[{index}]")


def _asset_field(asset: Mapping[str, Any], field: str, default: Any = None) -> Any:
    if field in asset:
        return asset[field]
    document = asset.get("document")
    if isinstance(document, Mapping) and field in document:
        return document[field]
    definition = asset.get("definition")
    if isinstance(definition, Mapping) and field in definition:
        return definition[field]
    identity = asset.get("identity")
    if isinstance(identity, Mapping) and field in identity:
        return identity[field]
    return default


def _asset_catalog(
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if isinstance(asset_definitions, Mapping):
        if isinstance(asset_definitions.get("assets"), list):
            values = list(asset_definitions["assets"])
        elif _asset_field(asset_definitions, "assetId"):
            values = [asset_definitions]
        else:
            values = [
                value
                for _, value in sorted(
                    asset_definitions.items(), key=lambda item: str(item[0])
                )
                if isinstance(value, Mapping)
            ]
    elif isinstance(asset_definitions, Sequence) and not isinstance(
        asset_definitions, (str, bytes)
    ):
        values = list(asset_definitions)
    else:
        _fail(
            "invalid_asset_catalog",
            "asset_definitions must be an object or array.",
        )
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        document = raw.get("document")
        definition = (
            deepcopy(dict(document))
            if isinstance(document, Mapping)
            else deepcopy(dict(raw))
        )
        asset_id = str(_asset_field(definition, "assetId", "") or "")
        if not asset_id:
            continue
        reported_revision = (
            raw.get("revision")
            or raw.get("assetDefinitionRevision")
            or _asset_field(definition, "assetDefinitionRevision")
        )
        revision = (
            str(reported_revision)
            if isinstance(reported_revision, str)
            and _REVISION_RE.fullmatch(reported_revision)
            else planner_fingerprint(definition)
        )
        result[asset_id] = {
            "assetId": asset_id,
            "revision": revision,
            "document": definition,
        }
    return result


def _vehicle_catalog(
    vehicle_profiles: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if vehicle_profiles is None:
        return {}
    if isinstance(vehicle_profiles, Mapping):
        if vehicle_profiles.get("vehicleProfileId"):
            values = [vehicle_profiles]
        else:
            values = [
                value
                for _, value in sorted(
                    vehicle_profiles.items(), key=lambda item: str(item[0])
                )
                if isinstance(value, Mapping)
            ]
    elif isinstance(vehicle_profiles, Sequence) and not isinstance(
        vehicle_profiles, (str, bytes)
    ):
        values = list(vehicle_profiles)
    else:
        _fail(
            "invalid_vehicle_catalog",
            "vehicle_profiles must be an object or array.",
        )
    result = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        document = raw.get("document")
        profile = (
            deepcopy(dict(document))
            if isinstance(document, Mapping)
            else deepcopy(dict(raw))
        )
        profile_id = str(profile.get("vehicleProfileId") or "")
        if profile_id:
            result[profile_id] = profile
    return result


def _normalized_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        _fail("invalid_planner_request", "request must be an object.")
    _reject_raw_geometry(request)
    value = _canonical_value(dict(request))
    if value.get("schemaVersion") != FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION:
        _fail(
            "unsupported_planner_schema",
            "Planner request schemaVersion must equal 1.",
        )
    request_id = _required_string(value.get("requestId"), "requestId")
    objective = value.get("objective", "place_asset_set")
    if objective not in _OBJECTIVES:
        _fail(
            "invalid_planner_request",
            f"objective must be one of {list(_OBJECTIVES)}.",
        )
    strategies = value.get("strategies", list(_STRATEGIES))
    if not isinstance(strategies, list) or not strategies:
        _fail("invalid_planner_request", "strategies must be a non-empty array.")
    normalized_strategies = []
    for strategy in strategies:
        if strategy not in _STRATEGIES:
            _fail(
                "invalid_planner_request",
                f"Unsupported layout strategy '{strategy}'.",
            )
        if strategy not in normalized_strategies:
            normalized_strategies.append(strategy)
    maximum_alternatives = value.get(
        "maximumAlternatives",
        len(normalized_strategies),
    )
    if (
        isinstance(maximum_alternatives, bool)
        or not isinstance(maximum_alternatives, int)
        or not 1 <= maximum_alternatives <= MAXIMUM_ALTERNATIVES
    ):
        _fail(
            "invalid_planner_request",
            f"maximumAlternatives must be between 1 and {MAXIMUM_ALTERNATIVES}.",
        )
    spacing = _finite_number(
        value.get("spacingMeters", 1.0),
        "spacingMeters",
        minimum=0.05,
        maximum=1000.0,
    )
    asset_set = value.get("assetSet", [])
    if not isinstance(asset_set, list):
        _fail("invalid_planner_request", "assetSet must be an array.")
    if objective != "cleanup_layout" and not asset_set:
        _fail(
            "invalid_planner_request",
            "assetSet is required when placing assets.",
        )
    total = 0
    normalized_assets = []
    item_ids = set()
    for index, raw in enumerate(asset_set):
        if not isinstance(raw, Mapping):
            _fail(
                "invalid_planner_request",
                f"assetSet[{index}] must be an object.",
            )
        item = deepcopy(dict(raw))
        item_id = _required_string(item.get("itemId"), f"assetSet[{index}].itemId")
        if item_id in item_ids:
            _fail(
                "invalid_planner_request",
                f"Duplicate planner itemId '{item_id}'.",
            )
        item_ids.add(item_id)
        item["itemId"] = item_id
        item["assetId"] = _required_string(
            item.get("assetId"), f"assetSet[{index}].assetId"
        )
        item["assetDefinitionRevision"] = _revision(
            item.get("assetDefinitionRevision"),
            f"assetSet[{index}].assetDefinitionRevision",
        )
        quantity = item.get("quantity", 1)
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not 1 <= quantity <= MAXIMUM_PLANNED_INSTANCES
        ):
            _fail(
                "invalid_planner_request",
                f"assetSet[{index}].quantity is unsupported.",
            )
        if item.get("existingPlacementId") is not None and quantity != 1:
            _fail(
                "invalid_planner_request",
                "An existing placement item must have quantity 1.",
            )
        item["quantity"] = quantity
        stage = item.get("stage", 0)
        if isinstance(stage, bool) or not isinstance(stage, int) or stage < 0:
            _fail(
                "invalid_planner_request",
                f"assetSet[{index}].stage must be a non-negative integer.",
            )
        item["stage"] = stage
        if item.get("targetZoneId") is not None:
            item["targetZoneId"] = _required_string(
                item["targetZoneId"],
                f"assetSet[{index}].targetZoneId",
            )
        if item.get("existingPlacementId") is not None:
            item["existingPlacementId"] = _required_string(
                item["existingPlacementId"],
                f"assetSet[{index}].existingPlacementId",
            )
        total += quantity
        normalized_assets.append(item)
    if total > MAXIMUM_PLANNED_INSTANCES:
        _fail(
            "planner_request_too_large",
            f"A planner request supports at most {MAXIMUM_PLANNED_INSTANCES} instances.",
        )
    cleanup = value.get("cleanup", {})
    if not isinstance(cleanup, Mapping):
        _fail("invalid_planner_request", "cleanup must be an object.")
    movable_manual = cleanup.get("movableManualPlacementIds", [])
    if not isinstance(movable_manual, list) or any(
        not isinstance(item, str) or not item for item in movable_manual
    ):
        _fail(
            "invalid_planner_request",
            "cleanup.movableManualPlacementIds must contain stable IDs.",
        )
    zone_sizing = value.get("zoneSizing", [])
    if not isinstance(zone_sizing, list):
        _fail("invalid_planner_request", "zoneSizing must be an array.")
    routes = value.get("routes", [])
    if not isinstance(routes, list):
        _fail("invalid_planner_request", "routes must be an array.")
    source_revisions = value.get("sourceRevisions", {})
    if not isinstance(source_revisions, Mapping):
        _fail("invalid_planner_request", "sourceRevisions must be an object.")
    for key, revision in source_revisions.items():
        _revision(revision, f"sourceRevisions.{key}")
    return {
        **value,
        "requestId": request_id,
        "objective": objective,
        "strategies": normalized_strategies,
        "maximumAlternatives": maximum_alternatives,
        "spacingMeters": spacing,
        "assetSet": normalized_assets,
        "cleanup": {
            "enabled": bool(cleanup.get("enabled", objective != "place_asset_set")),
            "moveAuto": bool(cleanup.get("moveAuto", True)),
            "movableManualPlacementIds": sorted(set(movable_manual)),
        },
        "zoneSizing": deepcopy(zone_sizing),
        "routes": deepcopy(routes),
        "sourceRevisions": deepcopy(dict(source_revisions)),
    }


def validate_layout_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return one detached declarative P8 request."""

    return _normalized_request(request)


def _identity_quaternion() -> dict[str, float]:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _positions(layout: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("placementId")): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }


def _zones(layout: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("zoneId")): item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }


def _polygon_bounds(boundary: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    points = [
        (float(point["x"]), float(point["z"]))
        for point in boundary
        if isinstance(point, Mapping) and "x" in point and "z" in point
    ]
    if len(points) < 3:
        _fail("planning_region_unavailable", "A planning region needs a polygon.")
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _default_region(
    layout: Mapping[str, Any],
    shell: Mapping[str, Any] | None,
) -> dict[str, Any]:
    zones = sorted(
        (
            item
            for item in layout.get("zones", [])
            if isinstance(item, Mapping)
            and str(item.get("zoneType") or "")
            not in {"aisle", "egress", "door_swing", "utility_corridor"}
        ),
        key=lambda item: str(item.get("zoneId") or ""),
    )
    if zones:
        zone = zones[0]
        return {
            "regionId": str(zone.get("zoneId")),
            "boundary": deepcopy(zone.get("boundary")),
            "floorElevation": float(zone.get("floorElevation", 0.0)),
            "gridSpacing": float(zone.get("gridSpacing", 0.5)),
        }
    shell_document = shell
    if isinstance(shell, Mapping) and isinstance(shell.get("document"), Mapping):
        shell_document = shell["document"]
    if isinstance(shell_document, Mapping):
        features = sorted(
            (
                item
                for item in shell_document.get("features", [])
                if isinstance(item, Mapping)
                and str(item.get("featureKind") or "")
                in {"floor", "floor_surface"}
            ),
            key=lambda item: str(item.get("featureId") or ""),
        )
        for feature in features:
            geometry = feature.get("geometry")
            boundary = geometry.get("boundary") if isinstance(geometry, Mapping) else None
            if isinstance(boundary, list) and len(boundary) >= 3:
                return {
                    "regionId": str(feature.get("featureId") or "shell-floor"),
                    "boundary": deepcopy(boundary),
                    "floorElevation": float(geometry.get("elevation", 0.0)),
                    "gridSpacing": 0.5,
                }
    _fail(
        "planning_region_unavailable",
        "The layout has no operational zone or revision-bound floor boundary.",
    )
    raise AssertionError("unreachable")


def _region_for_item(
    item: Mapping[str, Any],
    layout: Mapping[str, Any],
    default_region: Mapping[str, Any],
) -> dict[str, Any]:
    target_zone_id = item.get("targetZoneId")
    if target_zone_id is None:
        return deepcopy(dict(default_region))
    zone = _zones(layout).get(str(target_zone_id))
    if zone is None:
        _fail(
            "target_zone_not_found",
            f"Target zone '{target_zone_id}' does not exist.",
            details={"itemId": item.get("itemId"), "zoneId": target_zone_id},
        )
    return {
        "regionId": str(target_zone_id),
        "boundary": deepcopy(zone.get("boundary")),
        "floorElevation": float(zone.get("floorElevation", 0.0)),
        "gridSpacing": float(zone.get("gridSpacing", 0.5)),
    }


def _asset_half_extents(asset: Mapping[str, Any]) -> tuple[float, float]:
    probe = {
        "placementId": "pl-p8-geometry-probe",
        "assetId": str(_asset_field(asset, "assetId") or ""),
        "assetDefinitionRevision": "0" * 64,
        "transform": {
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "quaternion": _identity_quaternion(),
            "scale": 1,
        },
        "positionMode": "auto",
        "snapRelationship": None,
        "metadata": {},
    }
    records = placement_spatial_records(probe, asset)
    minimum_x = min(record.bounds[0] for record in records)
    minimum_z = min(record.bounds[1] for record in records)
    maximum_x = max(record.bounds[2] for record in records)
    maximum_z = max(record.bounds[3] for record in records)
    return (
        max(0.01, (maximum_x - minimum_x) / 2.0),
        max(0.01, (maximum_z - minimum_z) / 2.0),
    )


def _expand_instances(
    request: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for item in request["assetSet"]:
        record = catalog.get(str(item["assetId"]))
        if record is None:
            _fail(
                "asset_definition_unavailable",
                f"Asset definition '{item['assetId']}' is unavailable.",
                details={"itemId": item["itemId"]},
            )
        if record["revision"] != item["assetDefinitionRevision"]:
            _fail(
                "stale_asset_definition_revision",
                "A requested asset definition revision is unavailable.",
                details={
                    "assetId": item["assetId"],
                    "expectedRevision": item["assetDefinitionRevision"],
                    "actualRevision": record["revision"],
                },
            )
        half_x, half_z = _asset_half_extents(record["document"])
        for occurrence_index in range(item["quantity"]):
            result.append(
                {
                    **deepcopy(item),
                    "occurrenceIndex": occurrence_index,
                    "instanceKey": f"{item['itemId']}:{occurrence_index}",
                    "halfX": half_x,
                    "halfZ": half_z,
                }
            )
    return sorted(
        result,
        key=lambda item: (
            int(item.get("stage", 0)),
            str(item["itemId"]),
            int(item["occurrenceIndex"]),
        ),
    )


def _strategy_seeds(
    strategy: str,
    instances: Sequence[Mapping[str, Any]],
    regions: Mapping[str, Mapping[str, Any]],
    spacing: float,
) -> dict[str, tuple[float, float, float]]:
    by_region: dict[str, list[Mapping[str, Any]]] = {}
    for item in instances:
        by_region.setdefault(str(item["regionId"]), []).append(item)
    result: dict[str, tuple[float, float, float]] = {}
    for region_id in sorted(by_region):
        items = by_region[region_id]
        region = regions[region_id]
        minimum_x, minimum_z, maximum_x, maximum_z = _polygon_bounds(
            region["boundary"]
        )
        maximum_half_x = max(float(item["halfX"]) for item in items)
        maximum_half_z = max(float(item["halfZ"]) for item in items)
        usable_min_x = minimum_x + maximum_half_x + spacing
        usable_max_x = maximum_x - maximum_half_x - spacing
        usable_min_z = minimum_z + maximum_half_z + spacing
        usable_max_z = maximum_z - maximum_half_z - spacing
        if usable_max_x < usable_min_x or usable_max_z < usable_min_z:
            _fail(
                "planning_region_too_small",
                f"Planning region '{region_id}' is too small for the requested assets.",
            )
        if strategy == "balanced_grid":
            columns = max(1, math.ceil(math.sqrt(len(items))))
            cell_x = 2.0 * maximum_half_x + spacing
            cell_z = 2.0 * maximum_half_z + spacing
            for index, item in enumerate(items):
                column = index % columns
                row = index // columns
                x = usable_min_x + column * cell_x
                z = usable_min_z + row * cell_z
                result[str(item["instanceKey"])] = (
                    min(x, usable_max_x),
                    float(region["floorElevation"]),
                    min(z, usable_max_z),
                )
        elif strategy == "flow_lanes":
            stages = sorted({int(item.get("stage", 0)) for item in items})
            stage_columns = {
                stage: (
                    usable_min_x
                    if len(stages) == 1
                    else usable_min_x
                    + (usable_max_x - usable_min_x)
                    * stages.index(stage)
                    / (len(stages) - 1)
                )
                for stage in stages
            }
            stage_rows: dict[int, int] = {}
            for item in items:
                stage = int(item.get("stage", 0))
                row = stage_rows.get(stage, 0)
                stage_rows[stage] = row + 1
                z = usable_min_z + row * (2.0 * maximum_half_z + spacing)
                result[str(item["instanceKey"])] = (
                    stage_columns[stage],
                    float(region["floorElevation"]),
                    min(z, usable_max_z),
                )
        else:
            cursor_x = usable_min_x
            cursor_z = usable_min_z
            row_depth = 0.0
            for item in items:
                half_x = float(item["halfX"])
                half_z = float(item["halfZ"])
                if cursor_x + half_x > maximum_x - spacing and cursor_x > usable_min_x:
                    cursor_x = usable_min_x
                    cursor_z += row_depth + spacing
                    row_depth = 0.0
                if cursor_z + half_z > maximum_z - spacing:
                    _fail(
                        "planning_region_too_small",
                        f"Planning region '{region_id}' cannot hold the full asset set.",
                    )
                x = max(cursor_x, minimum_x + half_x + spacing)
                z = max(cursor_z, minimum_z + half_z + spacing)
                result[str(item["instanceKey"])] = (
                    x,
                    float(region["floorElevation"]),
                    z,
                )
                cursor_x = x + half_x + spacing
                row_depth = max(row_depth, 2.0 * half_z)
    return result


def _search_offsets(step: float) -> list[tuple[float, float]]:
    result = [(0.0, 0.0)]
    for ring in range(1, MAXIMUM_SEARCH_RING + 1):
        candidates = []
        for dx in range(-ring, ring + 1):
            for dz in range(-ring, ring + 1):
                if max(abs(dx), abs(dz)) != ring:
                    continue
                candidates.append((dx * step, dz * step))
        result.extend(
            sorted(
                candidates,
                key=lambda item: (
                    round(math.hypot(item[0], item[1]), 9),
                    round(math.atan2(item[1], item[0]), 9),
                    item[1],
                    item[0],
                ),
            )
        )
    return result


def _hard_finding_ids(diagnostics: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("findingId") or planner_fingerprint(item))
        for item in diagnostics.get("findings", [])
        if item.get("severity") in _HARD_SEVERITIES
    }


def _catalog_documents(
    catalog: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        deepcopy(catalog[asset_id]["document"])
        for asset_id in sorted(catalog)
    ]


def _apply_increment(
    layout: Mapping[str, Any],
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    return apply_facility_layout_operations(
        layout,
        [operation],
        base_revision=layout_revision(layout),
    )["document"]


def _candidate_operation(
    *,
    current_layout: Mapping[str, Any],
    placement_id: str,
    asset_record: Mapping[str, Any],
    desired: tuple[float, float, float],
    target_zone_id: str | None,
    existing: Mapping[str, Any] | None,
    movement_kind: str,
    planner_metadata: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    shell: Mapping[str, Any] | None,
    policy_set: Mapping[str, Any] | None,
    evidence_authority: Mapping[str, Any] | Iterable[str] | None,
    spacing: float,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    documents = _catalog_documents(catalog)
    baseline = diagnose_layout(
        current_layout,
        documents,
        shell=shell,
        policy_set=policy_set,
        evidence_authority=evidence_authority,
    )
    baseline_hard = _hard_finding_ids(baseline)
    grid = max(0.1, spacing, 0.5)
    requested_quaternion = (
        deepcopy(existing["transform"]["quaternion"])
        if existing is not None
        else _identity_quaternion()
    )
    for offset_x, offset_z in _search_offsets(grid):
        requested = {
            "x": desired[0] + offset_x,
            "y": desired[1],
            "z": desired[2] + offset_z,
        }
        candidate_result = generate_placement_candidates(
            current_layout,
            asset_record["document"],
            requested,
            documents,
            shell=shell,
            policy_set=policy_set,
            evidence_authority=evidence_authority,
            enabled_families=("grid",),
            requested_quaternion=requested_quaternion,
            target_placement_id=(
                placement_id if existing is not None else None
            ),
            asset_definition_revision=str(asset_record["revision"]),
            maximum_candidates=4,
        )
        for candidate in candidate_result["candidates"]:
            if existing is None:
                operation = {
                    "op": "place_asset",
                    "placement": {
                        "placementId": placement_id,
                        "assetId": str(asset_record["assetId"]),
                        "assetDefinitionRevision": str(asset_record["revision"]),
                        "transform": deepcopy(candidate["transform"]),
                        "positionMode": "auto",
                        "snapRelationship": deepcopy(candidate["snapRelationship"]),
                        "metadata": deepcopy(dict(planner_metadata)),
                    },
                }
            else:
                operation = {
                    "op": "move_placement",
                    "placementId": placement_id,
                    "position": deepcopy(candidate["transform"]["position"]),
                    "movementKind": movement_kind,
                }
            try:
                next_layout = _apply_increment(current_layout, operation)
            except (FacilityValidationError, ValueError):
                continue
            diagnostics = diagnose_layout(
                next_layout,
                documents,
                shell=shell,
                policy_set=policy_set,
                evidence_authority=evidence_authority,
            )
            if _hard_finding_ids(diagnostics) - baseline_hard:
                continue
            if target_zone_id is not None and target_zone_id not in (
                diagnostics.get("zoneMembership", {}).get(placement_id, [])
            ):
                continue
            return operation, next_layout
    return None


def _cleanup_collisions(
    layout: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    shell: Mapping[str, Any] | None,
    policy_set: Mapping[str, Any] | None,
    evidence_authority: Mapping[str, Any] | Iterable[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, float]]:
    cleanup = request["cleanup"]
    if not cleanup["enabled"]:
        return [], deepcopy(dict(layout)), {"auto": 0.0, "manual": 0.0}
    documents = _catalog_documents(catalog)
    current = deepcopy(dict(layout))
    operations: list[dict[str, Any]] = []
    displacement = {"auto": 0.0, "manual": 0.0}
    movable_manual = set(cleanup["movableManualPlacementIds"])
    diagnostics = diagnose_layout(
        current,
        documents,
        shell=shell,
        policy_set=policy_set,
        evidence_authority=evidence_authority,
    )
    hard_subjects = {
        str(subject)
        for finding in diagnostics.get("findings", [])
        if finding.get("severity") in _HARD_SEVERITIES
        for subject in finding.get("subjectRefs", [])
    }
    for placement_id, placement in sorted(_positions(current).items()):
        if placement_id not in hard_subjects:
            continue
        mode = str(placement.get("positionMode") or "")
        if mode == "locked":
            continue
        if mode == "manual" and placement_id not in movable_manual:
            continue
        if mode == "auto" and not cleanup["moveAuto"]:
            continue
        asset_record = catalog.get(str(placement.get("assetId") or ""))
        if asset_record is None:
            continue
        original = placement["transform"]["position"]
        found = _candidate_operation(
            current_layout=current,
            placement_id=placement_id,
            asset_record=asset_record,
            desired=(
                float(original["x"]),
                float(original.get("y", 0.0)),
                float(original["z"]),
            ),
            target_zone_id=None,
            existing=placement,
            movement_kind="automatic" if mode == "auto" else "user",
            planner_metadata={},
            catalog=catalog,
            shell=shell,
            policy_set=policy_set,
            evidence_authority=evidence_authority,
            spacing=float(request["spacingMeters"]),
        )
        if found is None:
            continue
        operation, next_layout = found
        next_position = operation["position"]
        moved = math.hypot(
            float(next_position["x"]) - float(original["x"]),
            float(next_position["z"]) - float(original["z"]),
        )
        if moved <= 1e-9:
            continue
        operations.append(operation)
        displacement[mode] += moved
        current = next_layout
    return operations, current, displacement


def _planned_placement_id(
    request: Mapping[str, Any],
    item: Mapping[str, Any],
) -> str:
    existing = item.get("existingPlacementId")
    if existing:
        return str(existing)
    return _stable_id(
        "pl-p8-",
        {
            "requestId": request["requestId"],
            "itemId": item["itemId"],
            "occurrenceIndex": item["occurrenceIndex"],
            "assetId": item["assetId"],
            "assetDefinitionRevision": item["assetDefinitionRevision"],
        },
        20,
    )


def _size_zones(
    layout: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    instance_placements: Mapping[str, str],
    catalog: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current = deepcopy(dict(layout))
    operations: list[dict[str, Any]] = []
    for index, raw in enumerate(request["zoneSizing"]):
        if not isinstance(raw, Mapping):
            _fail(
                "invalid_planner_request",
                f"zoneSizing[{index}] must be an object.",
            )
        member_item_ids = raw.get("memberItemIds")
        if not isinstance(member_item_ids, list) or not member_item_ids:
            _fail(
                "invalid_planner_request",
                f"zoneSizing[{index}].memberItemIds must be non-empty.",
            )
        member_ids = [
            placement_id
            for instance_key, placement_id in sorted(instance_placements.items())
            if instance_key.split(":", 1)[0] in set(member_item_ids)
        ]
        if not member_ids:
            _fail(
                "zone_sizing_members_unresolved",
                "An explicit zone-sizing request resolved no planned placements.",
                details={"memberItemIds": member_item_ids},
            )
        records = []
        placements = _positions(current)
        for placement_id in member_ids:
            placement = placements.get(placement_id)
            if placement is None:
                _fail(
                    "zone_sizing_members_unresolved",
                    f"Placement '{placement_id}' is unavailable for zone sizing.",
                )
            asset = catalog.get(str(placement.get("assetId") or ""))
            if asset is None:
                _fail(
                    "asset_definition_unavailable",
                    "Zone sizing requires every member asset definition.",
                )
            records.extend(
                placement_spatial_records(placement, asset["document"])
            )
        padding = _finite_number(
            raw.get("paddingMeters", 1.0),
            f"zoneSizing[{index}].paddingMeters",
            minimum=0.0,
            maximum=1000.0,
        )
        minimum_x = min(record.bounds[0] for record in records) - padding
        minimum_z = min(record.bounds[1] for record in records) - padding
        maximum_x = max(record.bounds[2] for record in records) + padding
        maximum_z = max(record.bounds[3] for record in records) + padding
        boundary = [
            {"x": minimum_x, "z": minimum_z},
            {"x": maximum_x, "z": minimum_z},
            {"x": maximum_x, "z": maximum_z},
            {"x": minimum_x, "z": maximum_z},
        ]
        zone_id = raw.get("zoneId")
        if zone_id is not None:
            zone_id = _required_string(zone_id, f"zoneSizing[{index}].zoneId")
            if zone_id not in _zones(current):
                _fail(
                    "target_zone_not_found",
                    f"Zone '{zone_id}' does not exist for resizing.",
                )
            operation = {
                "op": "edit_zone",
                "zoneId": zone_id,
                "patch": {"boundary": boundary},
            }
        else:
            new_zone = raw.get("newZone")
            if not isinstance(new_zone, Mapping):
                _fail(
                    "invalid_planner_request",
                    "Zone sizing requires zoneId or newZone.",
                )
            zone = deepcopy(dict(new_zone))
            zone_id = str(
                zone.get("zoneId")
                or _stable_id(
                    "zn-p8-",
                    {
                        "requestId": request["requestId"],
                        "index": index,
                        "memberItemIds": sorted(member_item_ids),
                    },
                    20,
                )
            )
            zone.update(
                {
                    "zoneId": zone_id,
                    "zoneType": str(zone.get("zoneType") or "workcell"),
                    "label": str(zone.get("label") or f"Planned zone {index + 1}"),
                    "boundary": boundary,
                    "floorElevation": float(zone.get("floorElevation", 0.0)),
                    "anchors": deepcopy(zone.get("anchors", [])),
                    "evidence": deepcopy(zone.get("evidence", [])),
                }
            )
            operation = {"op": "add_zone", "zone": zone}
        current = _apply_increment(current, operation)
        operations.append(operation)
    return operations, current


def _resolved_endpoint_ref(
    endpoint: Mapping[str, Any],
    instance_placements: Mapping[str, str],
) -> dict[str, Any]:
    if endpoint.get("kind") != "planned_asset_connector":
        return deepcopy(dict(endpoint))
    item_id = _required_string(endpoint.get("itemId"), "route.endpoint.itemId")
    occurrence_index = endpoint.get("occurrenceIndex", 0)
    if (
        isinstance(occurrence_index, bool)
        or not isinstance(occurrence_index, int)
        or occurrence_index < 0
    ):
        _fail(
            "invalid_planner_request",
            "route endpoint occurrenceIndex must be a non-negative integer.",
        )
    instance_key = f"{item_id}:{occurrence_index}"
    placement_id = instance_placements.get(instance_key)
    if placement_id is None:
        _fail(
            "route_endpoint_unresolved",
            f"Planned route endpoint '{instance_key}' is unavailable.",
        )
    return {
        "kind": "placement_connector",
        "placementId": placement_id,
        "connectorId": _required_string(
            endpoint.get("connectorId"),
            "route.endpoint.connectorId",
        ),
    }


def _route_obstacles(
    layout: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    excluded_placement_ids: set[str],
) -> list[dict[str, Any]]:
    result = []
    for placement_id, placement in sorted(_positions(layout).items()):
        if placement_id in excluded_placement_ids:
            continue
        asset = catalog.get(str(placement.get("assetId") or ""))
        if asset is None:
            continue
        for index, record in enumerate(
            placement_spatial_records(placement, asset["document"])
        ):
            result.append(
                {
                    "obstacleId": f"{placement_id}:{index}",
                    "boundary": [
                        {"x": point[0], "z": point[1]}
                        for point in record.polygon
                    ],
                }
            )
    return result


def _persisted_forklift_route_operation(
    *,
    request: Mapping[str, Any],
    raw_route: Mapping[str, Any],
    route_index: int,
    route_request_id: str,
    route_kind: str,
    source_ref: Mapping[str, Any],
    target_ref: Mapping[str, Any],
    vehicle: Mapping[str, Any],
    vehicle_id: str,
    vehicle_revision: str,
    layout: Mapping[str, Any],
    planned: Mapping[str, Any],
) -> dict[str, Any]:
    route = {
        "routeId": _stable_id(
            "rt-",
            {
                "requestId": request["requestId"],
                "routeRequestId": route_request_id,
                "routeFingerprint": planned["routeFingerprint"],
                "sourceEndpoint": source_ref,
                "targetEndpoint": target_ref,
            },
        ),
        "routeKind": route_kind,
        "sourceEndpoint": deepcopy(dict(source_ref)),
        "targetEndpoint": deepcopy(dict(target_ref)),
        "routingMode": "vehicle",
        "centerline": deepcopy(planned["centerline"]),
        "corridorWidth": _finite_number(
            raw_route.get(
                "corridorWidth",
                (vehicle.get("overallDimensions") or {}).get("width", 1.0),
            ),
            f"routes[{route_index}].corridorWidth",
            minimum=0.01,
        ),
        "vehicleProfileRef": {
            "vehicleProfileId": vehicle_id,
            "vehicleProfileRevision": vehicle_revision,
        },
        "sourceRevisions": {
            **deepcopy(planned["sourceRevisions"]),
            "layout": routing_layout_fingerprint(layout),
        },
        "requirements": deepcopy(raw_route.get("requirements", [])),
        "evidence": deepcopy(raw_route.get("evidence", [])),
        "extensions": {
            "planner": {
                "routeRequestId": route_request_id,
                "plannedRouteFingerprint": planned["routeFingerprint"],
                "routingEngineVersion": planned["routingEngineVersion"],
                "routerVersion": planned["routerVersion"],
                "distanceMeters": planned["distanceMeters"],
                "estimatedTravelSeconds": planned[
                    "estimatedTravelSeconds"
                ],
                "reverseUsed": planned["reverseUsed"],
                "loaded": planned["loaded"],
            }
        },
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    return {"op": "add_route", "route": route}


def _route_proposals(
    layout: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    instance_placements: Mapping[str, str],
    catalog: Mapping[str, Mapping[str, Any]],
    vehicle_catalog: Mapping[str, Mapping[str, Any]],
    shell: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    result = []
    asset_envelopes = {
        asset_id: {
            "revision": record["revision"],
            "document": record["document"],
        }
        for asset_id, record in catalog.items()
    }
    shell_revision = (
        str((layout.get("sourceShellRef") or {}).get("shellRevision") or "")
    )
    for index, raw in enumerate(request["routes"]):
        if not isinstance(raw, Mapping):
            _fail(
                "invalid_planner_request",
                f"routes[{index}] must be an object.",
            )
        route_request_id = _required_string(
            raw.get("routeRequestId"),
            f"routes[{index}].routeRequestId",
        )
        route_kind = _required_string(
            raw.get("routeKind"),
            f"routes[{index}].routeKind",
        )
        source_raw = raw.get("sourceEndpoint")
        target_raw = raw.get("targetEndpoint")
        if not isinstance(source_raw, Mapping) or not isinstance(target_raw, Mapping):
            _fail(
                "invalid_planner_request",
                "Route requests require sourceEndpoint and targetEndpoint.",
            )
        source_ref = _resolved_endpoint_ref(source_raw, instance_placements)
        target_ref = _resolved_endpoint_ref(target_raw, instance_placements)
        source = resolve_endpoint(
            layout,
            source_ref,
            asset_definitions=asset_envelopes,
            shell=shell,
            shell_revision=shell_revision,
            route_kind=route_kind,
            direction="source",
        )
        target = resolve_endpoint(
            layout,
            target_ref,
            asset_definitions=asset_envelopes,
            shell=shell,
            shell_revision=shell_revision,
            route_kind=route_kind,
            direction="target",
        )
        findings = list(source.get("findings", [])) + list(
            target.get("findings", [])
        )
        if not source.get("resolved") or not target.get("resolved"):
            result.append(
                {
                    "routeRequestId": route_request_id,
                    "routeKind": route_kind,
                    "accepted": False,
                    "persistable": False,
                    "reason": "endpoint_resolution_failed",
                    "findings": sorted(
                        findings,
                        key=lambda item: (
                            str(item.get("code") or ""),
                            str(item.get("findingId") or ""),
                        ),
                    ),
                }
            )
            continue
        if route_kind != "forklift":
            result.append(
                {
                    "routeRequestId": route_request_id,
                    "routeKind": route_kind,
                    "accepted": False,
                    "persistable": False,
                    "reason": "route_mutation_not_supported",
                    "findings": [
                        {
                            "code": "route_generation_not_supported",
                            "severity": "warning",
                            "message": (
                                "P8 can preview deterministic forklift routes; "
                                "this route kind remains diagnostic-only."
                            ),
                        }
                    ],
                    "sourceEndpoint": source_ref,
                    "targetEndpoint": target_ref,
                }
            )
            continue
        vehicle_id = _required_string(
            raw.get("vehicleProfileId"),
            f"routes[{index}].vehicleProfileId",
        )
        vehicle = vehicle_catalog.get(vehicle_id)
        if vehicle is None:
            _fail(
                "vehicle_profile_unavailable",
                f"Vehicle profile '{vehicle_id}' is unavailable.",
            )
        requested_vehicle_revision = _revision(
            raw.get("vehicleProfileRevision"),
            f"routes[{index}].vehicleProfileRevision",
        )
        if vehicle.get("vehicleProfileRevision") != requested_vehicle_revision:
            _fail(
                "stale_vehicle_profile_revision",
                "A requested vehicle profile revision is unavailable.",
                details={"vehicleProfileId": vehicle_id},
            )
        traversable = [
            deepcopy(zone["boundary"])
            for zone in sorted(
                (
                    zone
                    for zone in layout.get("zones", [])
                    if isinstance(zone, Mapping)
                    and str(zone.get("zoneType") or "")
                    in {"aisle", "forklift_aisle", "travel"}
                ),
                key=lambda zone: str(zone.get("zoneId") or ""),
            )
        ]
        obstacles = _route_obstacles(
            layout,
            catalog,
            set(),
        )
        source_facing = source["facing"]
        target_facing = target["facing"]
        planned = plan_forklift_route(
            {
                **source["position"],
                "heading": math.atan2(
                    float(source_facing["z"]),
                    float(source_facing["x"]),
                ),
            },
            {
                **target["position"],
                "heading": math.atan2(
                    float(target_facing["z"]),
                    float(target_facing["x"]),
                ),
            },
            vehicle,
            traversable_polygons=traversable,
            obstacles=obstacles,
            load=deepcopy(raw.get("load")),
            allow_reverse=raw.get("allowReverse"),
            source_revisions={
                **deepcopy(request["sourceRevisions"]),
                "layout": layout_revision(layout),
                "vehicle": requested_vehicle_revision,
            },
        )
        result.append(
            {
                "routeRequestId": route_request_id,
                "routeKind": route_kind,
                "accepted": bool(planned["accepted"]),
                "persistable": bool(planned["accepted"]),
                "reason": (
                    None
                    if planned["accepted"]
                    else "vehicle_route_rejected"
                ),
                "sourceEndpoint": source_ref,
                "targetEndpoint": target_ref,
                "route": planned,
                "operation": (
                    _persisted_forklift_route_operation(
                        request=request,
                        raw_route=raw,
                        route_index=index,
                        route_request_id=route_request_id,
                        route_kind=route_kind,
                        source_ref=source_ref,
                        target_ref=target_ref,
                        vehicle=vehicle,
                        vehicle_id=vehicle_id,
                        vehicle_revision=requested_vehicle_revision,
                        layout=layout,
                        planned=planned,
                    )
                    if planned["accepted"]
                    else None
                ),
                "findings": deepcopy(planned["findings"]),
            }
        )
    return sorted(result, key=lambda item: item["routeRequestId"])


def _dependency_snapshot(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    vehicle_catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    referenced_assets = sorted(
        {
            str(item["assetId"])
            for item in request["assetSet"]
        }
        | {
            str(item.get("assetId"))
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("assetId")
        }
    )
    referenced_vehicles = sorted(
        {
            str(item.get("vehicleProfileId"))
            for item in request["routes"]
            if isinstance(item, Mapping) and item.get("vehicleProfileId")
        }
    )
    return {
        "layoutRevision": layout_revision(layout),
        "sourceShellRef": deepcopy(layout.get("sourceShellRef")),
        "policySetRef": deepcopy(layout.get("policySetRef")),
        "catalogSnapshotRevision": layout.get("catalogSnapshotRevision"),
        "assetDefinitionRevisions": [
            {
                "assetId": asset_id,
                "assetDefinitionRevision": catalog[asset_id]["revision"],
            }
            for asset_id in referenced_assets
            if asset_id in catalog
        ],
        "vehicleProfileRevisions": [
            {
                "vehicleProfileId": vehicle_id,
                "vehicleProfileRevision": vehicle_catalog[vehicle_id].get(
                    "vehicleProfileRevision"
                ),
            }
            for vehicle_id in referenced_vehicles
            if vehicle_id in vehicle_catalog
        ],
        "processMapRevisions": sorted(
            {
                str(binding.get("processMapRevision"))
                for binding in layout.get("processBindings", [])
                if isinstance(binding, Mapping) and binding.get("processMapRevision")
            }
        ),
        "requestedSourceRevisions": deepcopy(request["sourceRevisions"]),
    }


def _obstacle_snapshot(
    layout: Mapping[str, Any],
    shell: Mapping[str, Any] | None,
) -> dict[str, Any]:
    shell_document = shell
    if isinstance(shell, Mapping) and isinstance(shell.get("document"), Mapping):
        shell_document = shell["document"]
    return {
        "placements": sorted(
            (
                {
                    "placementId": item.get("placementId"),
                    "assetId": item.get("assetId"),
                    "assetDefinitionRevision": item.get(
                        "assetDefinitionRevision"
                    ),
                    "transform": item.get("transform"),
                }
                for item in layout.get("placements", [])
                if isinstance(item, Mapping)
            ),
            key=lambda item: str(item.get("placementId") or ""),
        ),
        "zones": sorted(
            (
                {
                    "zoneId": item.get("zoneId"),
                    "boundary": item.get("boundary"),
                    "edgeSetbacks": item.get("edgeSetbacks"),
                    "heightLimit": item.get("heightLimit"),
                }
                for item in layout.get("zones", [])
                if isinstance(item, Mapping)
            ),
            key=lambda item: str(item.get("zoneId") or ""),
        ),
        "shellFeatures": (
            sorted(
                (
                    {
                        "featureId": item.get("featureId"),
                        "featureKind": item.get("featureKind"),
                        "geometry": item.get("geometry"),
                    }
                    for item in shell_document.get("features", [])
                    if isinstance(item, Mapping)
                ),
                key=lambda item: str(item.get("featureId") or ""),
            )
            if isinstance(shell_document, Mapping)
            else []
        ),
    }


def _alternative_metrics(
    *,
    operations: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    route_proposals: Sequence[Mapping[str, Any]],
    displacement: Mapping[str, float],
    requested_instances: int,
    instance_placements: Mapping[str, str],
) -> dict[str, Any]:
    route_results = [
        item.get("route")
        for item in route_proposals
        if isinstance(item.get("route"), Mapping)
    ]
    return {
        "requestedInstanceCount": requested_instances,
        "resolvedInstanceCount": len(instance_placements),
        "completeAssetSet": len(instance_placements) == requested_instances,
        "operationCount": len(operations),
        "createdPlacementCount": sum(
            item.get("op") == "place_asset" for item in operations
        ),
        "movedAutoCount": sum(
            item.get("op") == "move_placement"
            and item.get("movementKind") == "automatic"
            for item in operations
        ),
        "movedManualCount": sum(
            item.get("op") == "move_placement"
            and item.get("movementKind") == "user"
            for item in operations
        ),
        "zoneOperationCount": sum(
            item.get("op") in {"add_zone", "edit_zone"} for item in operations
        ),
        "autoDisplacementMeters": round(float(displacement["auto"]), 6),
        "manualDisplacementMeters": round(float(displacement["manual"]), 6),
        "spatialErrorCount": int(diagnostics["metrics"]["errorCount"]),
        "spatialWarningCount": int(diagnostics["metrics"]["warningCount"]),
        "spatialUnverifiedCount": int(diagnostics["metrics"]["unverifiedCount"]),
        "placementCollisions": int(
            diagnostics["metrics"]["placementCollisions"]
        ),
        "clearanceConflicts": int(
            diagnostics["metrics"]["clearanceConflicts"]
        ),
        "routeRequestCount": len(route_proposals),
        "acceptedRouteCount": sum(
            item.get("accepted") is True for item in route_proposals
        ),
        "routeDistanceMeters": round(
            sum(
                float(item.get("distanceMeters") or 0.0)
                for item in route_results
                if isinstance(item, Mapping)
            ),
            6,
        ),
        "changed": bool(receipt["changed"]),
    }


def _build_alternative(
    *,
    base_layout: Mapping[str, Any],
    base_diagnostics: Mapping[str, Any],
    request: Mapping[str, Any],
    strategy: str,
    instances: Sequence[Mapping[str, Any]],
    catalog: Mapping[str, Mapping[str, Any]],
    vehicle_catalog: Mapping[str, Mapping[str, Any]],
    shell: Mapping[str, Any] | None,
    policy_set: Mapping[str, Any] | None,
    evidence_authority: Mapping[str, Any] | Iterable[str] | None,
    dependency_fingerprint: str,
    obstacle_fingerprint: str,
) -> dict[str, Any]:
    operations, current, displacement = _cleanup_collisions(
        base_layout,
        request=request,
        catalog=catalog,
        shell=shell,
        policy_set=policy_set,
        evidence_authority=evidence_authority,
    )
    default_region = _default_region(current, shell)
    regions: dict[str, dict[str, Any]] = {}
    enriched_instances = []
    for instance in instances:
        region = _region_for_item(instance, current, default_region)
        region_id = str(region["regionId"])
        regions[region_id] = region
        enriched_instances.append({**deepcopy(instance), "regionId": region_id})
    seeds = _strategy_seeds(
        strategy,
        enriched_instances,
        regions,
        float(request["spacingMeters"]),
    )
    instance_placements: dict[str, str] = {}
    for item in enriched_instances:
        instance_key = str(item["instanceKey"])
        placement_id = _planned_placement_id(request, item)
        existing = _positions(current).get(placement_id)
        if item.get("existingPlacementId") and existing is None:
            _fail(
                "existing_placement_not_found",
                f"Existing placement '{placement_id}' is unavailable.",
            )
        if existing is not None:
            if str(existing.get("assetId")) != str(item["assetId"]):
                _fail(
                    "existing_placement_asset_mismatch",
                    f"Existing placement '{placement_id}' uses another asset.",
                )
            mode = str(existing.get("positionMode") or "")
            movable = mode == "auto" or (
                mode == "manual"
                and placement_id
                in set(request["cleanup"]["movableManualPlacementIds"])
            )
            if mode == "locked" or not movable:
                target_zone_id = item.get("targetZoneId")
                if target_zone_id is not None:
                    diagnostics = diagnose_layout(
                        current,
                        _catalog_documents(catalog),
                        shell=shell,
                        policy_set=policy_set,
                        evidence_authority=evidence_authority,
                    )
                    if target_zone_id not in diagnostics.get(
                        "zoneMembership", {}
                    ).get(placement_id, []):
                        _fail(
                            "fixed_placement_outside_target_zone",
                            "A fixed placement cannot satisfy its requested zone.",
                            details={"placementId": placement_id},
                        )
                instance_placements[instance_key] = placement_id
                continue
        asset_record = catalog[str(item["assetId"])]
        found = _candidate_operation(
            current_layout=current,
            placement_id=placement_id,
            asset_record=asset_record,
            desired=seeds[instance_key],
            target_zone_id=item.get("targetZoneId"),
            existing=existing,
            movement_kind=(
                "automatic"
                if existing is None or existing.get("positionMode") == "auto"
                else "user"
            ),
            planner_metadata={
                "plannedBy": "facility-layout-planner",
                "plannerRequestId": request["requestId"],
                "plannerItemId": item["itemId"],
                "plannerOccurrenceIndex": item["occurrenceIndex"],
            },
            catalog=catalog,
            shell=shell,
            policy_set=policy_set,
            evidence_authority=evidence_authority,
            spacing=float(request["spacingMeters"]),
        )
        if found is None:
            _fail(
                "complete_asset_set_unplaceable",
                "The deterministic planner could not place the complete asset set.",
                details={
                    "strategy": strategy,
                    "instanceKey": instance_key,
                    "assetId": item["assetId"],
                },
            )
        operation, next_layout = found
        if existing is not None:
            before = existing["transform"]["position"]
            after = operation["position"]
            moved = math.hypot(
                float(after["x"]) - float(before["x"]),
                float(after["z"]) - float(before["z"]),
            )
            if moved <= 1e-9:
                instance_placements[instance_key] = placement_id
                continue
            mode = str(existing.get("positionMode"))
            displacement[mode] += moved
        operations.append(operation)
        current = next_layout
        instance_placements[instance_key] = placement_id
    zone_operations, current = _size_zones(
        current,
        request=request,
        instance_placements=instance_placements,
        catalog=catalog,
    )
    operations.extend(zone_operations)
    final_receipt = apply_facility_layout_operations(
        base_layout,
        operations,
        base_revision=layout_revision(base_layout),
    )
    if canonical_layout_bytes(final_receipt["document"]) != canonical_layout_bytes(
        current
    ):
        _fail(
            "planner_transaction_mismatch",
            "Incremental planning and exact operation replay diverged.",
        )
    diagnostics = diagnose_layout(
        final_receipt["document"],
        _catalog_documents(catalog),
        shell=shell,
        policy_set=policy_set,
        evidence_authority=evidence_authority,
    )
    new_hard = sorted(
        _hard_finding_ids(diagnostics) - _hard_finding_ids(base_diagnostics)
    )
    if new_hard:
        _fail(
            "planner_introduced_hard_finding",
            "The proposal introduced a hard spatial finding.",
            details={"findingIds": new_hard, "strategy": strategy},
        )
    route_proposals = _route_proposals(
        final_receipt["document"],
        request=request,
        instance_placements=instance_placements,
        catalog=catalog,
        vehicle_catalog=vehicle_catalog,
        shell=shell,
    )
    route_hard_findings = [
        finding
        for proposal in route_proposals
        for finding in proposal.get("findings", [])
        if finding.get("severity") in _HARD_SEVERITIES
    ]
    if route_hard_findings:
        _fail(
            "planner_route_rejected",
            "A requested supported route has a hard deterministic finding.",
            details={
                "strategy": strategy,
                "findings": route_hard_findings,
            },
        )
    route_operations = [
        deepcopy(proposal["operation"])
        for proposal in route_proposals
        if proposal.get("accepted") is True
        and proposal.get("persistable") is True
        and isinstance(proposal.get("operation"), Mapping)
    ]
    if route_operations:
        operations.extend(route_operations)
        final_receipt = apply_facility_layout_operations(
            base_layout,
            operations,
            base_revision=layout_revision(base_layout),
        )
        diagnostics = diagnose_layout(
            final_receipt["document"],
            _catalog_documents(catalog),
            shell=shell,
            policy_set=policy_set,
            evidence_authority=evidence_authority,
        )
        new_hard = sorted(
            _hard_finding_ids(diagnostics)
            - _hard_finding_ids(base_diagnostics)
        )
        if new_hard:
            _fail(
                "planner_introduced_hard_finding",
                "The proposal introduced a hard spatial finding.",
                details={"findingIds": new_hard, "strategy": strategy},
            )
    metrics = _alternative_metrics(
        operations=operations,
        receipt=final_receipt,
        diagnostics=diagnostics,
        route_proposals=route_proposals,
        displacement=displacement,
        requested_instances=len(instances),
        instance_placements=instance_placements,
    )
    if not metrics["completeAssetSet"]:
        _fail(
            "incomplete_asset_set",
            "A proposal must resolve every requested asset occurrence.",
        )
    alternative_id = _stable_id(
        "fla-p8-",
        {
            "baseRevision": layout_revision(base_layout),
            "requestFingerprint": planner_fingerprint(request),
            "strategy": strategy,
            "operations": operations,
            "routeProposals": route_proposals,
            "dependencyFingerprint": dependency_fingerprint,
            "obstacleFingerprint": obstacle_fingerprint,
        },
        24,
    )
    score = [
        metrics["spatialErrorCount"],
        metrics["placementCollisions"],
        metrics["clearanceConflicts"],
        metrics["spatialUnverifiedCount"],
        metrics["manualDisplacementMeters"],
        metrics["autoDisplacementMeters"],
        -metrics["acceptedRouteCount"],
        metrics["routeDistanceMeters"],
        metrics["operationCount"],
        _STRATEGIES.index(strategy),
        alternative_id,
    ]
    return {
        "alternativeId": alternative_id,
        "strategy": strategy,
        "operations": deepcopy(operations),
        "operationReceipt": deepcopy(final_receipt),
        "ghostPreview": {
            "layout": deepcopy(final_receipt["document"]),
            "routeProposals": deepcopy(route_proposals),
        },
        "diagnostics": deepcopy(diagnostics),
        "metrics": metrics,
        "instancePlacements": {
            key: instance_placements[key] for key in sorted(instance_placements)
        },
        "newHardFindingIds": [],
        "score": score,
        "approvalBinding": {
            "layoutId": str(base_layout.get("layoutId") or ""),
            "baseRevision": layout_revision(base_layout),
            "alternativeId": alternative_id,
            "diffHash": final_receipt["diffHash"],
            "dependencyFingerprint": dependency_fingerprint,
            "obstacleFingerprint": obstacle_fingerprint,
        },
    }


def generate_layout_proposals(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    shell: Mapping[str, Any] | None = None,
    policy_set: Mapping[str, Any] | None = None,
    evidence_authority: Mapping[str, Any] | Iterable[str] | None = None,
    vehicle_profiles: (
        Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
    ) = None,
) -> dict[str, Any]:
    """Generate complete deterministic P8 alternatives without writing state."""

    if not isinstance(layout, Mapping):
        _fail("invalid_layout", "layout must be an object.")
    original_layout = _canonical_value(dict(layout))
    original_request = _canonical_value(dict(request))
    normalized_layout = canonicalize_layout(deepcopy(dict(layout)))
    normalized_request = _normalized_request(request)
    catalog = _asset_catalog(asset_definitions)
    vehicles = _vehicle_catalog(vehicle_profiles)
    instances = _expand_instances(normalized_request, catalog)
    base_diagnostics = diagnose_layout(
        normalized_layout,
        _catalog_documents(catalog),
        shell=shell,
        policy_set=policy_set,
        evidence_authority=evidence_authority,
    )
    dependencies = _dependency_snapshot(
        normalized_layout,
        normalized_request,
        catalog,
        vehicles,
    )
    dependency_fingerprint = planner_fingerprint(dependencies)
    obstacle_fingerprint = planner_fingerprint(
        _obstacle_snapshot(normalized_layout, shell)
    )
    alternatives = []
    rejected = []
    for strategy in normalized_request["strategies"]:
        try:
            alternatives.append(
                _build_alternative(
                    base_layout=normalized_layout,
                    base_diagnostics=base_diagnostics,
                    request=normalized_request,
                    strategy=strategy,
                    instances=instances,
                    catalog=catalog,
                    vehicle_catalog=vehicles,
                    shell=shell,
                    policy_set=policy_set,
                    evidence_authority=evidence_authority,
                    dependency_fingerprint=dependency_fingerprint,
                    obstacle_fingerprint=obstacle_fingerprint,
                )
            )
        except FacilityLayoutPlanningError as exc:
            rejected.append(
                {
                    "strategy": strategy,
                    "finding": exc.finding(),
                }
            )
    alternatives.sort(key=lambda item: tuple(item["score"]))
    alternatives = alternatives[: normalized_request["maximumAlternatives"]]
    if not alternatives:
        _fail(
            "no_layout_alternative",
            "No deterministic layout alternative satisfied the request.",
            details={"rejectedAlternatives": rejected},
        )
    if _canonical_value(dict(layout)) != original_layout:
        _fail("planner_mutated_input", "Planner mutated the layout input.")
    if _canonical_value(dict(request)) != original_request:
        _fail("planner_mutated_input", "Planner mutated the request input.")
    return {
        "plannerVersion": FACILITY_LAYOUT_PLANNER_VERSION,
        "requestSchemaVersion": FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION,
        "alternativePolicyVersion": FACILITY_LAYOUT_ALTERNATIVE_POLICY_VERSION,
        "layoutId": str(normalized_layout.get("layoutId") or ""),
        "layoutRevision": layout_revision(normalized_layout),
        "requestId": normalized_request["requestId"],
        "requestFingerprint": planner_fingerprint(normalized_request),
        "dependencyFingerprint": dependency_fingerprint,
        "obstacleFingerprint": obstacle_fingerprint,
        "dependencies": dependencies,
        "previewPure": True,
        "selectedAlternativeId": alternatives[0]["alternativeId"],
        "alternatives": alternatives,
        "rejectedAlternatives": rejected,
    }


# Naming aliases keep the public surface concise for P9's future tool adapter.
plan_facility_layout = generate_layout_proposals
build_layout_ghost_alternatives = generate_layout_proposals


__all__ = [
    "FACILITY_LAYOUT_ALTERNATIVE_POLICY_VERSION",
    "FACILITY_LAYOUT_PLANNER_VERSION",
    "FACILITY_LAYOUT_REQUEST_SCHEMA_VERSION",
    "FacilityLayoutPlanningError",
    "build_layout_ghost_alternatives",
    "canonical_planner_bytes",
    "generate_layout_proposals",
    "plan_facility_layout",
    "planner_fingerprint",
    "validate_layout_request",
]
