"""Narrow, reproducible playback validity for Facility Motion Package v2."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .errors import FacilityValidationError
from .navigation_contract import (
    FACILITY_NAVIGATION_COMPUTATIONAL_EPSILON,
    FACILITY_NAVIGATION_INFLUENCE_MARGIN_METERS,
)


FACILITY_MOTION_VALIDATION_CONTEXT_SCHEMA = (
    "facility-motion-validation-context-spec-v1"
)
FACILITY_MOTION_VALIDATION_PROJECTION_VERSION = (
    "facility-motion-validation-projection-v1"
)
FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_CANONICAL_BYTES = 2 * 1024 * 1024
FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_SELECTED_IDS = 2_000
FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_OBSTACLES = 25_000
FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_OBSTACLE_POINTS = 2_048
FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_TOTAL_OBSTACLE_POINTS = 250_000
FACILITY_MOTION_VALIDATION_CONTEXT_PRECISION = 6

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SELECTOR_FIELDS = (
    "placementIds",
    "routeIds",
    "markingIds",
    "zoneIds",
    "processBindingIds",
    "navigationAnchorIds",
    "movementProgramIds",
    "manualPathConstraintIds",
    "handoffProgramIds",
)
_LAYOUT_COLLECTIONS = {
    "placementIds": ("placements", "placementId"),
    "routeIds": ("routes", "routeId"),
    "markingIds": ("floorMarkings", "markingId"),
    "zoneIds": ("zones", "zoneId"),
    "processBindingIds": ("processBindings", "processBindingId"),
}
_NAVIGATION_COLLECTIONS = {
    "navigationAnchorIds": ("anchors", "navigationAnchorId"),
    "movementProgramIds": ("movementPrograms", "movementProgramId"),
    "manualPathConstraintIds": (
        "manualPathConstraints",
        "manualPathConstraintId",
    ),
    "handoffProgramIds": ("handoffPrograms", "handoffProgramId"),
}


class FacilityMotionValidationContextError(FacilityValidationError):
    """A motion v2 validation context is malformed, stale, or incomplete."""


def _fail(code: str, message: str, path: str, **details: Any) -> None:
    raise FacilityMotionValidationContextError(
        code,
        message,
        details={"path": path, **details},
    )


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise FacilityMotionValidationContextError(
            "facility_motion_validation_context_invalid_json",
            "Motion validation context must be finite JSON-compatible data.",
        ) from error


def _detached(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("ascii"))


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Expected an object.",
            path,
        )
    return value


def _closed(
    value: Mapping[str, Any],
    required: Iterable[str],
    path: str,
    *,
    optional: Iterable[str] = (),
) -> None:
    required_fields = set(required)
    optional_fields = set(optional)
    missing = sorted(required_fields - set(value))
    unknown = sorted(set(value) - required_fields - optional_fields)
    if missing:
        _fail(
            "facility_motion_validation_context_schema_invalid",
            f"Missing required fields: {', '.join(missing)}.",
            path,
        )
    if unknown:
        _fail(
            "facility_motion_validation_context_unknown_field",
            f"Unknown fields: {', '.join(unknown)}.",
            path,
        )


def _text(value: Any, path: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Expected a bounded non-empty string.",
            path,
        )
    return value


def _stable_id(value: Any, path: str) -> str:
    result = _text(value, path)
    if not _ID_RE.fullmatch(result):
        _fail(
            "facility_motion_validation_context_identity_invalid",
            "Expected a stable identity.",
            path,
        )
    return result


def _revision(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        _fail(
            "facility_motion_validation_context_revision_invalid",
            "Expected a lowercase SHA-256 revision.",
            path,
        )
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Expected a finite number.",
            path,
        )
    result = float(value)
    if not math.isfinite(result):
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Expected a finite number.",
            path,
        )
    return result


def _rounded(value: Any, path: str) -> int | float:
    result = round(_number(value, path), FACILITY_MOTION_VALIDATION_CONTEXT_PRECISION)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def _point(value: Any, path: str) -> dict[str, int | float]:
    item = _mapping(value, path)
    _closed(item, {"x", "z"}, path)
    return {
        "x": _rounded(item["x"], f"{path}.x"),
        "z": _rounded(item["z"], f"{path}.z"),
    }


def _bounds(value: Any, path: str) -> dict[str, dict[str, int | float]]:
    item = _mapping(value, path)
    _closed(item, {"minimum", "maximum"}, path)
    minimum = _point(item["minimum"], f"{path}.minimum")
    maximum = _point(item["maximum"], f"{path}.maximum")
    if minimum["x"] > maximum["x"] or minimum["z"] > maximum["z"]:
        _fail(
            "facility_motion_validation_context_bounds_invalid",
            "Influence bounds minimum must not exceed maximum.",
            path,
        )
    return {"minimum": minimum, "maximum": maximum}


def _id_array(value: Any, path: str) -> list[str]:
    if not isinstance(value, list):
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Expected an identity array.",
            path,
        )
    if len(value) > FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_SELECTED_IDS:
        _fail(
            "facility_motion_validation_context_resource_limit_exceeded",
            "Selected identities exceed the pre-allocation ceiling.",
            path,
            actualItems=len(value),
            maximumItems=FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_SELECTED_IDS,
        )
    result = [_stable_id(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if result != sorted(set(result)):
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Selected identities must be unique and sorted.",
            path,
        )
    return result


def _source_ref(value: Any, path: str) -> dict[str, str]:
    item = _mapping(value, path)
    _closed(item, {"sourceId", "sourceRevision"}, path)
    return {
        "sourceId": _stable_id(item["sourceId"], f"{path}.sourceId"),
        "sourceRevision": _revision(
            item["sourceRevision"],
            f"{path}.sourceRevision",
        ),
    }


def validate_motion_validation_context_spec(value: Any) -> dict[str, Any]:
    item = _mapping(value, "validationContextSpec")
    _closed(
        item,
        {
            "schemaVersion",
            "projectionVersion",
            "influenceRegion",
            "selectors",
            "actorProfileRef",
            "plannerVersions",
        },
        "validationContextSpec",
        optional={"loadContext"},
    )
    if item["schemaVersion"] != FACILITY_MOTION_VALIDATION_CONTEXT_SCHEMA:
        _fail(
            "facility_motion_validation_context_schema_unsupported",
            "Unsupported motion validation-context schema.",
            "validationContextSpec.schemaVersion",
        )
    if item["projectionVersion"] != FACILITY_MOTION_VALIDATION_PROJECTION_VERSION:
        _fail(
            "facility_motion_validation_context_projection_unsupported",
            "Unsupported motion validation-context projection.",
            "validationContextSpec.projectionVersion",
        )
    region = _mapping(item["influenceRegion"], "validationContextSpec.influenceRegion")
    _closed(
        region,
        {"bounds", "marginMeters", "computationalEpsilon"},
        "validationContextSpec.influenceRegion",
    )
    canonical_region = {
        "bounds": _bounds(region["bounds"], "validationContextSpec.influenceRegion.bounds"),
        "marginMeters": _rounded(
            region["marginMeters"],
            "validationContextSpec.influenceRegion.marginMeters",
        ),
        "computationalEpsilon": _number(
            region["computationalEpsilon"],
            "validationContextSpec.influenceRegion.computationalEpsilon",
        ),
    }
    if canonical_region["marginMeters"] != FACILITY_NAVIGATION_INFLUENCE_MARGIN_METERS:
        _fail(
            "facility_motion_validation_context_contract_mismatch",
            "The frozen influence-region margin changed.",
            "validationContextSpec.influenceRegion.marginMeters",
        )
    if canonical_region["computationalEpsilon"] != FACILITY_NAVIGATION_COMPUTATIONAL_EPSILON:
        _fail(
            "facility_motion_validation_context_contract_mismatch",
            "The frozen computational epsilon changed.",
            "validationContextSpec.influenceRegion.computationalEpsilon",
        )
    selectors = _mapping(item["selectors"], "validationContextSpec.selectors")
    _closed(selectors, set(_SELECTOR_FIELDS), "validationContextSpec.selectors")
    canonical_selectors = {
        field: _id_array(
            selectors[field],
            f"validationContextSpec.selectors.{field}",
        )
        for field in _SELECTOR_FIELDS
    }
    profile_ref = _mapping(
        item["actorProfileRef"],
        "validationContextSpec.actorProfileRef",
    )
    _closed(
        profile_ref,
        {"profileKind", "profileId", "profileRevision"},
        "validationContextSpec.actorProfileRef",
    )
    if profile_ref["profileKind"] not in {"pedestrian", "vehicle"}:
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Actor profile kind must be pedestrian or vehicle.",
            "validationContextSpec.actorProfileRef.profileKind",
        )
    canonical_profile_ref = {
        "profileKind": profile_ref["profileKind"],
        "profileId": _stable_id(
            profile_ref["profileId"],
            "validationContextSpec.actorProfileRef.profileId",
        ),
        "profileRevision": _revision(
            profile_ref["profileRevision"],
            "validationContextSpec.actorProfileRef.profileRevision",
        ),
    }
    versions = _mapping(item["plannerVersions"], "validationContextSpec.plannerVersions")
    if not versions or len(versions) > 16:
        _fail(
            "facility_motion_validation_context_schema_invalid",
            "Planner versions require between 1 and 16 entries.",
            "validationContextSpec.plannerVersions",
        )
    canonical_versions = {
        _stable_id(key, f"validationContextSpec.plannerVersions.{key}"): _text(
            version,
            f"validationContextSpec.plannerVersions.{key}",
        )
        for key, version in sorted(versions.items())
    }
    result = {
        "schemaVersion": FACILITY_MOTION_VALIDATION_CONTEXT_SCHEMA,
        "projectionVersion": FACILITY_MOTION_VALIDATION_PROJECTION_VERSION,
        "influenceRegion": canonical_region,
        "selectors": canonical_selectors,
        "actorProfileRef": canonical_profile_ref,
        "plannerVersions": canonical_versions,
    }
    if "loadContext" in item:
        result["loadContext"] = _detached(item["loadContext"])
    if len(_canonical_bytes(result)) > FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_CANONICAL_BYTES:
        _fail(
            "facility_motion_validation_context_resource_limit_exceeded",
            "Validation-context specification exceeds its canonical byte ceiling.",
            "validationContextSpec",
        )
    return result


def _records_by_id(
    records: Any,
    identity_field: str,
    path: str,
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(records, list):
        _fail(
            "facility_motion_validation_context_source_invalid",
            "Projected source collection is unavailable.",
            path,
        )
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(records):
        record = _mapping(raw, f"{path}[{index}]")
        identity = record.get(identity_field)
        if not isinstance(identity, str) or not identity:
            continue
        result[identity] = record
    return result


def _selected_records(
    records: Mapping[str, Mapping[str, Any]],
    selected_ids: Sequence[str],
    path: str,
) -> list[dict[str, Any]]:
    missing = [identity for identity in selected_ids if identity not in records]
    if missing:
        _fail(
            "facility_motion_validation_context_missing_record",
            "A projected source record is missing.",
            path,
            missingIds=missing,
        )
    return [_detached(records[identity]) for identity in selected_ids]


def _obstacle_boundary(value: Any, path: str) -> list[dict[str, int | float]]:
    if not isinstance(value, list) or len(value) < 3:
        _fail(
            "facility_motion_validation_context_obstacle_invalid",
            "Obstacle boundary requires at least three points.",
            path,
        )
    if len(value) > FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_OBSTACLE_POINTS:
        _fail(
            "facility_motion_validation_context_resource_limit_exceeded",
            "Obstacle boundary exceeds its point ceiling.",
            path,
        )
    points = [_point(point, f"{path}[{index}]") for index, point in enumerate(value)]
    if points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        _fail(
            "facility_motion_validation_context_obstacle_invalid",
            "Obstacle boundary collapses below three points.",
            path,
        )
    rotations = [points[index:] + points[:index] for index in range(len(points))]
    reverse = list(reversed(points))
    rotations.extend(
        reverse[index:] + reverse[:index] for index in range(len(reverse))
    )
    return min(rotations, key=lambda ring: _canonical_bytes(ring))


def _boundary_bounds(points: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    return (
        min(float(point["x"]) for point in points),
        min(float(point["z"]) for point in points),
        max(float(point["x"]) for point in points),
        max(float(point["z"]) for point in points),
    )


def _intersects_influence(
    obstacle_bounds: tuple[float, float, float, float],
    influence: Mapping[str, Any],
) -> bool:
    bounds = influence["bounds"]
    margin = float(influence["marginMeters"])
    epsilon = float(influence["computationalEpsilon"])
    minimum_x = float(bounds["minimum"]["x"]) - margin - epsilon
    minimum_z = float(bounds["minimum"]["z"]) - margin - epsilon
    maximum_x = float(bounds["maximum"]["x"]) + margin + epsilon
    maximum_z = float(bounds["maximum"]["z"]) + margin + epsilon
    return not (
        obstacle_bounds[2] < minimum_x
        or obstacle_bounds[0] > maximum_x
        or obstacle_bounds[3] < minimum_z
        or obstacle_bounds[1] > maximum_z
    )


def _current_authority_refs(layout: Mapping[str, Any]) -> dict[str, Any]:
    shell = _mapping(layout.get("sourceShellRef"), "layout.sourceShellRef")
    policy = _mapping(layout.get("policySetRef"), "layout.policySetRef")
    required = {
        "shell": (shell, "shellId", "shellRevision"),
        "policy": (policy, "policySetId", "policySetRevision"),
    }
    result = {}
    for name, (record, id_field, revision_field) in required.items():
        if id_field not in record or revision_field not in record:
            _fail(
                "facility_motion_validation_context_missing_record",
                "A required authority reference is missing.",
                f"layout.{name}",
            )
        result[name] = {
            "sourceId": _stable_id(record[id_field], f"layout.{name}.{id_field}"),
            "sourceRevision": _revision(
                record[revision_field],
                f"layout.{name}.{revision_field}",
            ),
        }
    catalog_revision = layout.get("catalogSnapshotRevision")
    if catalog_revision is not None:
        result["catalog"] = {
            "sourceId": "facility-catalog-snapshot",
            "sourceRevision": _revision(
                catalog_revision,
                "layout.catalogSnapshotRevision",
            ),
        }
    return result


def build_motion_validation_context_projection(
    layout: Mapping[str, Any],
    spec: Mapping[str, Any],
    *,
    actor_profile: Mapping[str, Any],
    obstacles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project only source records that can affect one planned traversal."""

    canonical_spec = validate_motion_validation_context_spec(spec)
    if len(obstacles) > FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_OBSTACLES:
        _fail(
            "facility_motion_validation_context_resource_limit_exceeded",
            "Obstacle candidates exceed the pre-allocation ceiling.",
            "obstacles",
            actualItems=len(obstacles),
            maximumItems=FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_OBSTACLES,
        )
    profile_ref = canonical_spec["actorProfileRef"]
    actual_profile_id = actor_profile.get("vehicleProfileId") or actor_profile.get(
        "operatorProfileId"
    ) or actor_profile.get("profileId")
    actual_profile_revision = actor_profile.get("vehicleProfileRevision") or actor_profile.get(
        "operatorProfileRevision"
    ) or actor_profile.get("profileRevision")
    if (
        actual_profile_id != profile_ref["profileId"]
        or actual_profile_revision != profile_ref["profileRevision"]
    ):
        _fail(
            "facility_motion_validation_context_profile_mismatch",
            "The exact actor profile revision is unavailable.",
            "actorProfile",
        )
    selectors = canonical_spec["selectors"]
    selected: dict[str, list[dict[str, Any]]] = {}
    for selector, (collection, identity_field) in _LAYOUT_COLLECTIONS.items():
        records = _records_by_id(layout.get(collection), identity_field, f"layout.{collection}")
        selected[selector] = _selected_records(
            records,
            selectors[selector],
            f"layout.{collection}",
        )
    navigation = {}
    extensions = layout.get("extensions")
    if isinstance(extensions, Mapping) and isinstance(
        extensions.get("facilityNavigation"),
        Mapping,
    ):
        navigation = extensions["facilityNavigation"]
    for selector, (collection, identity_field) in _NAVIGATION_COLLECTIONS.items():
        records = _records_by_id(
            navigation.get(collection, []),
            identity_field,
            f"layout.extensions.facilityNavigation.{collection}",
        )
        selected[selector] = _selected_records(
            records,
            selectors[selector],
            f"layout.extensions.facilityNavigation.{collection}",
        )
    selected_obstacles = []
    total_points = 0
    obstacle_ids = set()
    for index, raw in enumerate(obstacles):
        path = f"obstacles[{index}]"
        obstacle = _mapping(raw, path)
        obstacle_id = _stable_id(obstacle.get("obstacleId"), f"{path}.obstacleId")
        if obstacle_id in obstacle_ids:
            _fail(
                "facility_motion_validation_context_identity_invalid",
                "Obstacle identities must be unique.",
                f"{path}.obstacleId",
            )
        obstacle_ids.add(obstacle_id)
        boundary = _obstacle_boundary(obstacle.get("boundary"), f"{path}.boundary")
        total_points += len(boundary)
        if total_points > FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_TOTAL_OBSTACLE_POINTS:
            _fail(
                "facility_motion_validation_context_resource_limit_exceeded",
                "Obstacle geometry exceeds the total pre-allocation point ceiling.",
                "obstacles",
            )
        if _intersects_influence(
            _boundary_bounds(boundary),
            canonical_spec["influenceRegion"],
        ):
            selected_obstacles.append(
                {"obstacleId": obstacle_id, "boundary": boundary}
            )
    selected_obstacles.sort(key=lambda item: item["obstacleId"])
    projection = {
        "schemaVersion": FACILITY_MOTION_VALIDATION_PROJECTION_VERSION,
        "influenceRegion": canonical_spec["influenceRegion"],
        "selectedRecords": {key: selected[key] for key in sorted(selected)},
        "selectedObstacles": selected_obstacles,
        "actorProfile": _detached(actor_profile),
        "authorityRefs": _current_authority_refs(layout),
        "plannerVersions": canonical_spec["plannerVersions"],
    }
    if "loadContext" in canonical_spec:
        projection["loadContext"] = deepcopy(canonical_spec["loadContext"])
    payload = _canonical_bytes(projection)
    if len(payload) > FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_CANONICAL_BYTES:
        _fail(
            "facility_motion_validation_context_resource_limit_exceeded",
            "Validation-context projection exceeds its canonical byte ceiling.",
            "validationContextProjection",
            canonicalBytes=len(payload),
            maximumCanonicalBytes=FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_CANONICAL_BYTES,
        )
    return _detached(projection)


def motion_validation_context_fingerprint(projection: Mapping[str, Any]) -> str:
    payload = _canonical_bytes(projection)
    if len(payload) > FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_CANONICAL_BYTES:
        _fail(
            "facility_motion_validation_context_resource_limit_exceeded",
            "Validation-context projection exceeds its canonical byte ceiling.",
            "validationContextProjection",
        )
    return hashlib.sha256(payload).hexdigest()


def infer_motion_validation_selectors(
    layout: Mapping[str, Any],
    *,
    route_id: str,
    actor_placement_id: str | None,
    marking_ids: Sequence[str] = (),
    additional_placement_ids: Sequence[str] = (),
) -> dict[str, list[str]]:
    """Resolve the durable records transitively referenced by one movement."""

    route_id = _stable_id(route_id, "routeId")
    placements = {
        str(item.get("placementId")): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    selected_placements = set(additional_placement_ids)
    if actor_placement_id is not None:
        selected_placements.add(_stable_id(actor_placement_id, "actorPlacementId"))
    zones = set()
    selected_markings = set(marking_ids)
    route = next(
        (
            item
            for item in layout.get("routes", [])
            if isinstance(item, Mapping) and item.get("routeId") == route_id
        ),
        None,
    )
    if route is None:
        _fail(
            "facility_motion_validation_context_missing_record",
            "The selected route is missing.",
            "layout.routes",
            missingIds=[route_id],
        )
    for endpoint_field in ("sourceEndpoint", "targetEndpoint"):
        endpoint = route.get(endpoint_field)
        if not isinstance(endpoint, Mapping):
            continue
        if endpoint.get("placementId"):
            selected_placements.add(str(endpoint["placementId"]))
        if endpoint.get("zoneId"):
            zones.add(str(endpoint["zoneId"]))
    aisle = (route.get("extensions") or {}).get("facilityAisle")
    if isinstance(aisle, Mapping):
        for field in ("sourceZoneId", "targetZoneId"):
            if aisle.get(field):
                zones.add(str(aisle[field]))
        zones.update(str(item) for item in aisle.get("viaZoneIds", []) if item)
    for placement_id in selected_placements:
        if placement_id not in placements:
            _fail(
                "facility_motion_validation_context_missing_record",
                "A selected placement is missing.",
                "layout.placements",
                missingIds=[placement_id],
            )
    process_binding_ids = set()
    for binding in layout.get("processBindings", []):
        if not isinstance(binding, Mapping):
            continue
        if route_id in binding.get("routeIds", []) or selected_placements.intersection(
            str(item) for item in binding.get("placementIds", [])
        ):
            process_binding_ids.add(str(binding.get("processBindingId")))
    navigation = {}
    extensions = layout.get("extensions")
    if isinstance(extensions, Mapping) and isinstance(
        extensions.get("facilityNavigation"),
        Mapping,
    ):
        navigation = extensions["facilityNavigation"]
    movement_ids = set()
    anchor_ids = set()
    constraint_ids = set()
    handoff_ids = set()
    for program in navigation.get("movementPrograms", []):
        if not isinstance(program, Mapping):
            continue
        if (
            program.get("actorPlacementId") in selected_placements
            or route_id in program.get("requiredRouteIds", [])
        ):
            movement_ids.add(str(program.get("movementProgramId")))
            anchor_ids.update(str(item) for item in program.get("requiredAnchorIds", []))
            constraint_ids.update(
                str(item) for item in program.get("manualPathConstraintIds", [])
            )
            handoff_ids.update(str(item) for item in program.get("handoffProgramIds", []))
    return {
        "placementIds": sorted(selected_placements),
        "routeIds": [route_id],
        "markingIds": sorted(selected_markings),
        "zoneIds": sorted(zones),
        "processBindingIds": sorted(process_binding_ids),
        "navigationAnchorIds": sorted(anchor_ids),
        "movementProgramIds": sorted(movement_ids),
        "manualPathConstraintIds": sorted(constraint_ids),
        "handoffProgramIds": sorted(handoff_ids),
    }


def build_motion_validation_context_spec(
    layout: Mapping[str, Any],
    *,
    route_id: str,
    actor_profile_ref: Mapping[str, Any],
    planner_versions: Mapping[str, str],
    influence_bounds: Mapping[str, Any],
    actor_placement_id: str | None = None,
    marking_ids: Sequence[str] = (),
    additional_placement_ids: Sequence[str] = (),
    load_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile_id = actor_profile_ref.get("vehicleProfileId") or actor_profile_ref.get(
        "operatorProfileId"
    ) or actor_profile_ref.get("profileId")
    profile_revision = actor_profile_ref.get(
        "vehicleProfileRevision"
    ) or actor_profile_ref.get("operatorProfileRevision") or actor_profile_ref.get(
        "profileRevision"
    )
    profile_kind = actor_profile_ref.get("profileKind") or (
        "vehicle" if actor_profile_ref.get("vehicleProfileId") else "pedestrian"
    )
    result = {
        "schemaVersion": FACILITY_MOTION_VALIDATION_CONTEXT_SCHEMA,
        "projectionVersion": FACILITY_MOTION_VALIDATION_PROJECTION_VERSION,
        "influenceRegion": {
            "bounds": _bounds(influence_bounds, "influenceBounds"),
            "marginMeters": FACILITY_NAVIGATION_INFLUENCE_MARGIN_METERS,
            "computationalEpsilon": FACILITY_NAVIGATION_COMPUTATIONAL_EPSILON,
        },
        "selectors": infer_motion_validation_selectors(
            layout,
            route_id=route_id,
            actor_placement_id=actor_placement_id,
            marking_ids=marking_ids,
            additional_placement_ids=additional_placement_ids,
        ),
        "actorProfileRef": {
            "profileKind": profile_kind,
            "profileId": profile_id,
            "profileRevision": profile_revision,
        },
        "plannerVersions": dict(planner_versions),
    }
    if load_context is not None:
        result["loadContext"] = _detached(load_context)
    return validate_motion_validation_context_spec(result)


def validate_motion_package_playback_context(
    package: Mapping[str, Any],
    *,
    active_layout_revision: str,
    active_validation_context_fingerprint: str | None = None,
) -> None:
    """Apply exactly one stale rule according to the package schema."""

    schema = package.get("schemaVersion")
    if schema == "facility-motion-package-v1":
        if package.get("layoutRevision") != active_layout_revision:
            _fail(
                "facility_motion_package_stale",
                "The v1 motion package does not match the active layout revision.",
                "package.layoutRevision",
            )
        return
    if schema in {"facility-motion-package-v2", "facility-motion-package-v3"}:
        expected = package.get("validationContextFingerprint")
        if not isinstance(active_validation_context_fingerprint, str):
            _fail(
                "facility_motion_validation_context_unavailable",
                "The motion validation context was not recomputed before playback.",
                "activeValidationContextFingerprint",
            )
        _revision(expected, "package.validationContextFingerprint")
        _revision(
            active_validation_context_fingerprint,
            "activeValidationContextFingerprint",
        )
        if active_validation_context_fingerprint != expected:
            _fail(
                "facility_motion_package_stale",
                "The motion package validation context changed.",
                "package.validationContextFingerprint",
            )
        return
    _fail(
        "facility_motion_package_schema_unsupported",
        "Unsupported Facility Motion Package schema.",
        "package.schemaVersion",
    )


__all__ = [
    "FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_CANONICAL_BYTES",
    "FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_OBSTACLES",
    "FACILITY_MOTION_VALIDATION_CONTEXT_MAXIMUM_SELECTED_IDS",
    "FACILITY_MOTION_VALIDATION_CONTEXT_SCHEMA",
    "FACILITY_MOTION_VALIDATION_PROJECTION_VERSION",
    "FacilityMotionValidationContextError",
    "build_motion_validation_context_projection",
    "build_motion_validation_context_spec",
    "infer_motion_validation_selectors",
    "motion_validation_context_fingerprint",
    "validate_motion_package_playback_context",
    "validate_motion_validation_context_spec",
]
