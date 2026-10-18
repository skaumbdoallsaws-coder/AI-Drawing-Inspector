"""Pure deterministic routing primitives for Facility Layout P7.

The module owns spatial connector resolution and route geometry only. It never
derives or mutates Process Map precedence: proximity is a distance fact, not a
manufacturing-order fact.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import heapq
import json
import math
from typing import Any, Iterable, Mapping, Sequence

try:
    from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon
    from shapely.geometry.polygon import orient as orient_polygon
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
except ImportError:  # pragma: no cover - exercised by explicit fail-closed tests
    GeometryCollection = None
    LineString = None
    MultiPolygon = None
    Polygon = None
    STRtree = None
    orient_polygon = None
    unary_union = None

from .errors import FacilityValidationError


ROUTING_ENGINE_VERSION = "facility-routing-v1"
ROUTER_VERSION = "heading-lattice-v1"
SWEPT_ENVELOPE_REVISION = "facility-swept-envelope-v1"
MAXIMUM_SWEPT_VOLUME_SAMPLES = 25_000
MAXIMUM_SWEEP_OBSTACLE_COMPARISONS = 5_000_000
CARDINAL_ROUTE_ALIGNMENT_TOLERANCE_RADIANS = math.radians(0.1)
METER_DECIMAL_PLACES = 6
HEADING_DECIMAL_PLACES = 9
EPSILON = 1e-9

ROUTE_KINDS = frozenset({"material", "operator", "forklift", "conveyor"})
UTILITY_KINDS = frozenset(
    {
        "electrical",
        "compressed_air",
        "water",
        "exhaust",
        "network",
        "gas",
        "drain",
    }
)
PROCESS_SEMANTICS = {
    "precedenceDerived": False,
    "policy": "spatial_proximity_never_implies_process_precedence",
}
_SEVERITY_ORDER = {"error": 0, "blocked": 1, "warning": 2, "info": 3}
# An aisle bound to a department must extend at least this far inside it.
# Stopping at the department's edge leaves its equipment and doors unreached.
AISLE_ZONE_ENTRY_MINIMUM_METERS = 0.05


class FacilityRoutingResourceError(FacilityValidationError):
    """Fail closed when deterministic route analysis exceeds a fixed budget."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_copy(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("ascii"))


def _round(value: float, places: int = METER_DECIMAL_PLACES) -> float:
    result = round(float(value), places)
    return 0.0 if result == 0.0 else result


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _point2(value: Mapping[str, Any], label: str = "point") -> tuple[float, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return _finite(value.get("x"), f"{label}.x"), _finite(
        value.get("z"), f"{label}.z"
    )


def _vector3(
    value: Mapping[str, Any],
    label: str = "vector",
) -> tuple[float, float, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return (
        _finite(value.get("x"), f"{label}.x"),
        _finite(value.get("y"), f"{label}.y"),
        _finite(value.get("z"), f"{label}.z"),
    )


def _vector_dict(value: Sequence[float]) -> dict[str, float]:
    return {
        "x": _round(value[0]),
        "y": _round(value[1]),
        "z": _round(value[2]),
    }


def _point_dict(value: Sequence[float]) -> dict[str, float]:
    return {"x": _round(value[0]), "z": _round(value[1])}


def _normalize2(value: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(*value)
    if length <= EPSILON:
        raise ValueError("direction vector must be non-zero")
    return value[0] / length, value[1] / length


def _normalize3(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in value))
    if length <= EPSILON:
        raise ValueError("direction vector must be non-zero")
    return tuple(component / length for component in value)  # type: ignore[return-value]


def stable_route_fingerprint(value: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 route or route-request fingerprint."""

    return _sha256(
        {
            "routingEngineVersion": ROUTING_ENGINE_VERSION,
            "routerVersion": ROUTER_VERSION,
            "value": value,
        }
    )


def routing_layout_fingerprint(layout: Mapping[str, Any]) -> str:
    """Fingerprint only persisted geometry and authorities routes depend on."""

    return stable_route_fingerprint(
        {
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
                        "zoneType": item.get("zoneType"),
                        "boundary": item.get("boundary"),
                        "anchors": item.get("anchors"),
                    }
                    for item in layout.get("zones", [])
                    if isinstance(item, Mapping)
                ),
                key=lambda item: str(item.get("zoneId") or ""),
            ),
            "sourceShellRef": layout.get("sourceShellRef"),
            "policySetRef": layout.get("policySetRef"),
        }
    )


def _canonical_metric_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_metric_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_canonical_metric_value(item) for item in value]
    if isinstance(value, float):
        rounded = round(value, METER_DECIMAL_PLACES)
        if rounded == 0:
            return 0
        if rounded.is_integer():
            return int(rounded)
        return rounded
    return value


def persisted_route_fingerprint(route: Mapping[str, Any]) -> str:
    """Bind persisted route geometry to endpoints, vehicle, and sources."""

    return stable_route_fingerprint(
        _canonical_metric_value({
            "routeKind": route.get("routeKind"),
            "sourceEndpoint": route.get("sourceEndpoint"),
            "targetEndpoint": route.get("targetEndpoint"),
            "routingMode": route.get("routingMode"),
            "centerline": route.get("centerline"),
            "corridorWidth": route.get("corridorWidth"),
            "vehicleProfileRef": route.get("vehicleProfileRef"),
            "sourceRevisions": route.get("sourceRevisions"),
        })
    )


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    subjects: Iterable[str] = (),
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if severity not in _SEVERITY_ORDER:
        raise ValueError("unsupported finding severity")
    normalized_subjects = sorted({str(item) for item in subjects})
    normalized_details = deepcopy(dict(details or {}))
    identity = {
        "code": code,
        "details": normalized_details,
        "subjects": normalized_subjects,
    }
    result = {
        "findingId": f"flr-{_sha256(identity)[:24]}",
        "severity": severity,
        "code": code,
        "message": message,
        "subjects": normalized_subjects,
    }
    if normalized_details:
        result["details"] = normalized_details
    return result


def _sort_findings(findings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for raw in findings:
        item = deepcopy(dict(raw))
        unique[str(item["findingId"])] = item
    return sorted(
        unique.values(),
        key=lambda item: (
            _SEVERITY_ORDER.get(str(item.get("severity")), 99),
            str(item.get("code")),
            tuple(item.get("subjects") or ()),
            str(item.get("findingId")),
        ),
    )


def _failed_resolution(
    endpoint: Any,
    finding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "resolved": False,
        "endpoint": deepcopy(endpoint),
        "findings": _sort_findings([finding]),
    }


def _quaternion_rotate(
    quaternion: Mapping[str, Any],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    qx = _finite(quaternion.get("x"), "quaternion.x")
    qy = _finite(quaternion.get("y"), "quaternion.y")
    qz = _finite(quaternion.get("z"), "quaternion.z")
    qw = _finite(quaternion.get("w"), "quaternion.w")
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm <= EPSILON:
        raise ValueError("quaternion must be non-zero")
    qx, qy, qz, qw = (item / norm for item in (qx, qy, qz, qw))
    vx, vy, vz = vector
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return (
        vx + qw * tx + qy * tz - qz * ty,
        vy + qw * ty + qz * tx - qx * tz,
        vz + qw * tz + qx * ty - qy * tx,
    )


def _catalog_records(
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], str | None]]:
    records: list[tuple[Mapping[str, Any], str | None]] = []
    values: Iterable[Any]
    if isinstance(asset_definitions, Mapping):
        if asset_definitions.get("documentKind") == "industrial_asset_definition":
            values = [asset_definitions]
        else:
            values = asset_definitions.values()
    else:
        values = asset_definitions
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        document = raw
        revision = raw.get("assetDefinitionRevision") or raw.get("revision")
        if isinstance(raw.get("document"), Mapping):
            document = raw["document"]
        elif isinstance(raw.get("definition"), Mapping):
            document = raw["definition"]
        elif isinstance(raw.get("assetDefinition"), Mapping):
            document = raw["assetDefinition"]
        if document.get("documentKind") != "industrial_asset_definition":
            continue
        records.append((document, str(revision) if revision else None))
    return sorted(
        records,
        key=lambda item: (
            str(item[0].get("assetId")),
            item[1] or "",
        ),
    )


def _asset_definition_for_placement(
    placement: Mapping[str, Any],
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    asset_id = str(placement.get("assetId") or "")
    expected_revision = str(placement.get("assetDefinitionRevision") or "")
    candidates = [
        (document, revision)
        for document, revision in _catalog_records(asset_definitions)
        if document.get("assetId") == asset_id
    ]
    exact = [
        item
        for item in candidates
        if item[1] == expected_revision
    ]
    if len(exact) == 1:
        return exact[0][0], None
    if len(exact) > 1:
        return None, _finding(
            "ambiguous_asset_definition",
            "error",
            "More than one asset definition matches the placement revision.",
            subjects=(str(placement.get("placementId")), asset_id),
        )
    if candidates:
        if all(item[1] is None for item in candidates):
            return None, _finding(
                "asset_definition_revision_unavailable",
                "error",
                "Asset definition is missing its repository revision envelope.",
                subjects=(str(placement.get("placementId")), asset_id),
                details={"expectedRevision": expected_revision},
            )
        return None, _finding(
            "stale_asset_definition_revision",
            "error",
            "The placement asset-definition revision is unavailable.",
            subjects=(str(placement.get("placementId")), asset_id),
            details={"expectedRevision": expected_revision},
        )
    return None, _finding(
        "asset_definition_missing",
        "error",
        "The placement asset definition is unavailable.",
        subjects=(str(placement.get("placementId")), asset_id),
    )


def _direction_role_allowed(role: str, direction: str) -> bool:
    if direction == "source":
        return role in {"source", "output", "bidirectional"}
    if direction == "target":
        return role in {"sink", "input", "bidirectional"}
    return True


def resolve_endpoint(
    layout: Mapping[str, Any],
    endpoint: Mapping[str, Any],
    *,
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]] = (),
    shell: Mapping[str, Any] | None = None,
    shell_revision: str | None = None,
    route_kind: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Resolve an occurrence-qualified endpoint into current world geometry.

    Expected reference variants are the three variants frozen by Facility
    Layout v1. Invalid or stale references return typed findings rather than
    falling back to asset-local IDs or nearest spatial objects.
    """

    if not isinstance(endpoint, Mapping):
        return _failed_resolution(
            endpoint,
            _finding(
                "invalid_route_endpoint",
                "error",
                "Route endpoint must be an object.",
            ),
        )
    kind = endpoint.get("kind")
    if kind == "placement_connector":
        placement_id = str(endpoint.get("placementId") or "")
        connector_id = str(endpoint.get("connectorId") or "")
        placements = [
            item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId") == placement_id
        ]
        if len(placements) != 1:
            return _failed_resolution(
                endpoint,
                _finding(
                    "dangling_placement_endpoint",
                    "error",
                    "Placement connector references one unknown placement.",
                    subjects=(placement_id, connector_id),
                ),
            )
        placement = placements[0]
        asset, asset_finding = _asset_definition_for_placement(
            placement, asset_definitions
        )
        if asset_finding is not None or asset is None:
            return _failed_resolution(endpoint, asset_finding or {})
        connectors = [
            item
            for item in asset.get("connectors", [])
            if isinstance(item, Mapping) and item.get("connectorId") == connector_id
        ]
        if len(connectors) != 1:
            code = (
                "ambiguous_asset_connector"
                if len(connectors) > 1
                else "dangling_placement_connector"
            )
            return _failed_resolution(
                endpoint,
                _finding(
                    code,
                    "error",
                    "Placement connector does not resolve to one asset connector.",
                    subjects=(placement_id, connector_id),
                ),
            )
        connector = connectors[0]
        try:
            local_position = _vector3(connector.get("position"), "connector.position")
            local_facing = _vector3(connector.get("facing"), "connector.facing")
            transform = placement.get("transform")
            if not isinstance(transform, Mapping):
                raise ValueError("placement.transform must be an object")
            translation = _vector3(transform.get("position"), "transform.position")
            quaternion = transform.get("quaternion")
            if not isinstance(quaternion, Mapping):
                raise ValueError("transform.quaternion must be an object")
            scale = _finite(transform.get("scale"), "transform.scale")
            rotated_position = _quaternion_rotate(
                quaternion, tuple(item * scale for item in local_position)
            )
            rotated_facing = _normalize3(
                _quaternion_rotate(quaternion, local_facing)
            )
        except ValueError as exc:
            return _failed_resolution(
                endpoint,
                _finding(
                    "invalid_connector_geometry",
                    "error",
                    str(exc),
                    subjects=(placement_id, connector_id),
                ),
            )
        service_type = str(connector.get("connectorKind") or "")
        role = str(connector.get("role") or "")
        allowed = connector.get("allowedRouteKinds")
        if not isinstance(allowed, list):
            allowed = (
                [service_type]
                if service_type in ROUTE_KINDS | UTILITY_KINDS
                else []
            )
        result = {
            "resolved": True,
            "endpoint": deepcopy(dict(endpoint)),
            "qualifiedEndpointId": f"placement:{placement_id}:{connector_id}",
            "endpointKind": kind,
            "position": _vector_dict(
                tuple(
                    translation[index] + rotated_position[index]
                    for index in range(3)
                )
            ),
            "facing": _vector_dict(rotated_facing),
            "serviceType": service_type,
            "role": role,
            "allowedRouteKinds": sorted({str(item) for item in allowed}),
            "interface": _canonical_copy(dict(connector.get("interface") or {})),
            "capacity": _canonical_copy(dict(connector.get("capacity") or {})),
            "evidenceStatus": str(connector.get("evidenceStatus") or "unknown"),
            "findings": [],
        }
    elif kind == "zone_anchor":
        zone_id = str(endpoint.get("zoneId") or "")
        anchor_id = str(endpoint.get("anchorId") or "")
        matches = []
        for zone in layout.get("zones", []):
            if not isinstance(zone, Mapping) or zone.get("zoneId") != zone_id:
                continue
            for anchor in zone.get("anchors", []):
                if isinstance(anchor, Mapping) and anchor.get("anchorId") == anchor_id:
                    matches.append(anchor)
        if len(matches) != 1:
            return _failed_resolution(
                endpoint,
                _finding(
                    "dangling_zone_anchor",
                    "error",
                    "Zone endpoint does not resolve to one qualified anchor.",
                    subjects=(zone_id, anchor_id),
                ),
            )
        anchor = matches[0]
        try:
            position = _vector3(anchor.get("position"), "anchor.position")
            facing = _normalize3(_vector3(anchor.get("facing"), "anchor.facing"))
        except ValueError as exc:
            return _failed_resolution(
                endpoint,
                _finding(
                    "invalid_connector_geometry",
                    "error",
                    str(exc),
                    subjects=(zone_id, anchor_id),
                ),
            )
        result = {
            "resolved": True,
            "endpoint": deepcopy(dict(endpoint)),
            "qualifiedEndpointId": f"zone:{zone_id}:{anchor_id}",
            "endpointKind": kind,
            "position": _vector_dict(position),
            "facing": _vector_dict(facing),
            "serviceType": str(anchor.get("anchorKind") or ""),
            "role": "bidirectional",
            "allowedRouteKinds": sorted(
                {str(item) for item in anchor.get("allowedRouteKinds", [])}
            ),
            "interface": {},
            "capacity": {},
            "evidenceStatus": (
                "derived" if anchor.get("evidence") else "unknown"
            ),
            "findings": [],
        }
    elif kind == "shell_connector":
        expected = layout.get("sourceShellRef")
        if not isinstance(expected, Mapping):
            return _failed_resolution(
                endpoint,
                _finding(
                    "stale_shell_revision",
                    "error",
                    "Layout has no revision-bound source shell.",
                ),
            )
        shell_id = str(endpoint.get("shellId") or "")
        endpoint_revision = str(endpoint.get("shellRevision") or "")
        expected_revision = str(expected.get("shellRevision") or "")
        shell_document = shell
        if isinstance(shell, Mapping) and isinstance(shell.get("document"), Mapping):
            shell_document = shell["document"]
        supplied_revision = (
            shell_revision
            or (shell or {}).get("shellRevision")
            or (shell or {}).get("revision")
        )
        actual_revision = str(supplied_revision or "")
        if (
            shell_id != expected.get("shellId")
            or endpoint_revision != expected_revision
            or actual_revision != expected_revision
        ):
            return _failed_resolution(
                endpoint,
                _finding(
                    "stale_shell_revision",
                    "error",
                    "Shell connector does not match the layout shell revision.",
                    subjects=(shell_id, str(endpoint.get("connectorId") or "")),
                    details={
                        "expectedRevision": expected_revision,
                        "actualRevision": actual_revision,
                    },
                ),
            )
        if (
            not isinstance(shell_document, Mapping)
            or shell_document.get("shellId") != shell_id
        ):
            return _failed_resolution(
                endpoint,
                _finding(
                    "shell_connector_missing",
                    "error",
                    "The referenced facility shell is unavailable.",
                    subjects=(shell_id,),
                ),
            )
        connector_id = str(endpoint.get("connectorId") or "")
        matches = [
            item
            for item in shell_document.get("shellConnectors", [])
            if isinstance(item, Mapping) and item.get("connectorId") == connector_id
        ]
        if len(matches) != 1:
            return _failed_resolution(
                endpoint,
                _finding(
                    (
                        "ambiguous_shell_connector"
                        if len(matches) > 1
                        else "dangling_shell_connector"
                    ),
                    "error",
                    "Shell endpoint does not resolve to one connector.",
                    subjects=(shell_id, connector_id),
                ),
            )
        connector = matches[0]
        try:
            position = _vector3(connector.get("position"), "connector.position")
            facing = _normalize3(_vector3(connector.get("facing"), "connector.facing"))
        except ValueError as exc:
            return _failed_resolution(
                endpoint,
                _finding(
                    "invalid_connector_geometry",
                    "error",
                    str(exc),
                    subjects=(shell_id, connector_id),
                ),
            )
        service_type = str(connector.get("serviceType") or "")
        role = str(connector.get("role") or "")
        result = {
            "resolved": True,
            "endpoint": deepcopy(dict(endpoint)),
            "qualifiedEndpointId": (
                f"shell:{shell_id}:{endpoint_revision}:{connector_id}"
            ),
            "endpointKind": kind,
            "position": _vector_dict(position),
            "facing": _vector_dict(facing),
            "serviceType": service_type,
            "role": role,
            "allowedRouteKinds": (
                [service_type]
                if service_type in ROUTE_KINDS | UTILITY_KINDS
                else []
            ),
            "interface": _canonical_copy(dict(connector.get("interface") or {})),
            "capacity": _canonical_copy(dict(connector.get("capacity") or {})),
            "evidenceStatus": (
                "derived" if connector.get("evidence") else "unknown"
            ),
            "findings": [],
        }
    elif kind == "world_point":
        try:
            position = _vector3(endpoint.get("position"), "endpoint.position")
        except ValueError as exc:
            return _failed_resolution(
                endpoint,
                _finding(
                    "invalid_connector_geometry",
                    "error",
                    str(exc),
                ),
            )
        canonical_position = _vector_dict(position)
        result = {
            "resolved": True,
            "endpoint": deepcopy(dict(endpoint)),
            "qualifiedEndpointId": (
                "world:"
                f"{canonical_position['x']}:"
                f"{canonical_position['y']}:"
                f"{canonical_position['z']}"
            ),
            "endpointKind": kind,
            "position": canonical_position,
            "facing": {"x": 0.0, "y": 0.0, "z": 1.0},
            "serviceType": str(route_kind or ""),
            "role": "bidirectional",
            "allowedRouteKinds": sorted(ROUTE_KINDS),
            "interface": {},
            "capacity": {},
            "evidenceStatus": "unverified",
            "findings": [],
        }
    else:
        return _failed_resolution(
            endpoint,
            _finding(
                "invalid_route_endpoint",
                "error",
                "Route endpoint kind is unsupported.",
                details={"kind": kind},
            ),
        )

    findings = []
    if route_kind is not None and route_kind not in result["allowedRouteKinds"]:
        findings.append(
            _finding(
                "utility_type_incompatible"
                if route_kind in UTILITY_KINDS
                else "route_endpoint_incompatible",
                "error",
                "Endpoint does not allow the requested route or service type.",
                subjects=(result["qualifiedEndpointId"], str(route_kind)),
            )
        )
    if direction is not None and not _direction_role_allowed(
        str(result["role"]), direction
    ):
        findings.append(
            _finding(
                "connector_direction_invalid",
                "error",
                "Connector role is incompatible with route direction.",
                subjects=(result["qualifiedEndpointId"], str(direction)),
                details={"role": result["role"]},
            )
        )
    result["findings"] = _sort_findings(findings)
    result["resolved"] = not any(
        item["severity"] in {"error", "blocked"} for item in result["findings"]
    )
    return result


def validate_facility_aisle_route(
    layout: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    endpoint_tolerance_meters: float = 0.01,
) -> dict[str, Any]:
    """Validate a planning aisle without upgrading it to a vehicle path."""

    route_id = str(route.get("routeId") or "")
    route_kind = str(route.get("routeKind") or "")
    findings: list[Mapping[str, Any]] = []
    if route_kind not in ROUTE_KINDS:
        findings.append(
            _finding(
                "route_kind_invalid",
                "error",
                "Route kind is unsupported.",
                subjects=(route_id, route_kind),
            )
        )
    source = resolve_endpoint(
        layout,
        route.get("sourceEndpoint") or {},
        route_kind=route_kind,
        direction="source",
    )
    target = resolve_endpoint(
        layout,
        route.get("targetEndpoint") or {},
        route_kind=route_kind,
        direction="target",
    )
    findings.extend(source.get("findings", []))
    findings.extend(target.get("findings", []))
    if (
        source.get("resolved")
        and target.get("resolved")
        and source.get("qualifiedEndpointId") == target.get("qualifiedEndpointId")
    ):
        findings.append(
            _finding(
                "route_self_connection",
                "error",
                "An aisle cannot begin and end at the same world point.",
                subjects=(route_id, str(source.get("qualifiedEndpointId"))),
            )
        )
    raw_centerline = route.get("centerline")
    centerline = (
        [item for item in raw_centerline if isinstance(item, Mapping)]
        if isinstance(raw_centerline, list)
        else []
    )
    if len(centerline) < 2:
        findings.append(
            _finding(
                "aisle_centerline_invalid",
                "error",
                "An aisle centerline requires at least two world points.",
                subjects=(route_id,),
            )
        )
    elif source.get("resolved") and target.get("resolved"):
        tolerance = max(
            0.0,
            _finite(endpoint_tolerance_meters, "endpoint_tolerance_meters"),
        )
        for label, point, resolved in (
            ("source", centerline[0], source),
            ("target", centerline[-1], target),
        ):
            distance = math.dist(
                _vector3(point, f"{label}.centerline"),
                _vector3(resolved.get("position"), f"{label}.position"),
            )
            if distance > tolerance + EPSILON:
                findings.append(
                    _finding(
                        "route_endpoint_geometry_mismatch",
                        "error",
                        "Aisle centerline does not terminate at its world endpoint.",
                        subjects=(route_id, label),
                        details={
                            "distanceMeters": _round(distance),
                            "maximumMeters": _round(tolerance),
                        },
                    )
                )
    expected_fingerprint = persisted_route_fingerprint(route)
    if route.get("routeFingerprint") != expected_fingerprint:
        findings.append(
            _finding(
                "stale_route_geometry",
                "error",
                "Aisle fingerprint does not match its persisted geometry.",
                subjects=(route_id,),
                details={
                    "expectedFingerprint": expected_fingerprint,
                    "actualFingerprint": route.get("routeFingerprint"),
                },
            )
        )
    extensions = route.get("extensions")
    aisle = (
        extensions.get("facilityAisle")
        if isinstance(extensions, Mapping)
        and isinstance(extensions.get("facilityAisle"), Mapping)
        else {}
    )
    evidence_status = str(aisle.get("clearanceEvidenceStatus") or "unverified")
    evidence = route.get("evidence")
    has_evidence = isinstance(evidence, list) and bool(evidence)
    if evidence_status in {"authored", "derived"} and not has_evidence:
        findings.append(
            _finding(
                "aisle_authoritative_evidence_missing",
                "error",
                "Authoritative aisle clearance requires attached evidence.",
                subjects=(route_id,),
                details={"clearanceEvidenceStatus": evidence_status},
            )
        )
    elif evidence_status not in {"authored", "derived"}:
        findings.append(
            _finding(
                "aisle_clearance_unverified",
                "warning",
                "Aisle clearance is planning data and remains unverified.",
                subjects=(route_id,),
                details={"clearanceEvidenceStatus": evidence_status},
            )
        )
    findings.extend(
        _aisle_zone_binding_findings(layout, route_id, centerline, aisle)
    )
    ordered = _sort_findings(findings)
    return {
        "routeId": route_id,
        "valid": not any(
            item["severity"] in {"error", "blocked"} for item in ordered
        ),
        "source": source,
        "target": target,
        "sweptVolume": None,
        "findings": ordered,
        "processSemantics": dict(PROCESS_SEMANTICS),
    }


def _aisle_zone_binding_findings(
    layout: Mapping[str, Any],
    route_id: str,
    centerline: Sequence[Mapping[str, Any]],
    aisle: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Warn when an aisle never extends into a department it is bound to.

    Reachability and review tools report the bound departments as connected,
    so a centerline drawn only up to a department's edge would otherwise read
    as access to the racks and doors inside it.
    """
    if LineString is None or Polygon is None or len(centerline) < 2:
        return []
    bound = [("source", aisle.get("sourceZoneId"))]
    bound.extend(("via", item) for item in aisle.get("viaZoneIds") or [])
    bound.append(("target", aisle.get("targetZoneId")))
    zones = {
        str(zone.get("zoneId")): zone
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping) and zone.get("zoneId")
    }
    try:
        line = LineString([_point2(point, "centerline") for point in centerline])
    except ValueError:
        return []  # Malformed centerlines already fail aisle validation.
    findings = []
    for role, zone_id in bound:
        zone = zones.get(str(zone_id or ""))
        if zone is None:
            continue  # Unknown zone references are reported by layout validation.
        try:
            polygon = Polygon(
                [_point2(point, "zone.boundary") for point in zone.get("boundary") or []]
            )
        except ValueError:
            continue
        if not polygon.is_valid or polygon.area <= EPSILON:
            continue
        interior = polygon.buffer(-AISLE_ZONE_ENTRY_MINIMUM_METERS)
        if line.intersection(interior).length > EPSILON:
            continue
        findings.append(
            _finding(
                "aisle_zone_not_entered",
                "warning",
                "Aisle stops at or runs along the edge of a department it is "
                "bound to without extending into it.",
                subjects=(route_id, str(zone_id)),
                details={
                    "bindingRole": role,
                    "zoneId": str(zone_id),
                    "zoneLabel": str(zone.get("label") or zone_id),
                    "minimumEntryMeters": AISLE_ZONE_ENTRY_MINIMUM_METERS,
                },
            )
        )
    return findings


def _interface_findings(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    route_kind: str,
) -> list[dict[str, Any]]:
    if route_kind not in {"material", "conveyor"}:
        return []
    source_interface = source.get("interface")
    target_interface = target.get("interface")
    left = (
        dict(source_interface)
        if isinstance(source_interface, Mapping)
        else {}
    )
    right = (
        dict(target_interface)
        if isinstance(target_interface, Mapping)
        else {}
    )
    findings = []
    for key in sorted(set(left) & set(right)):
        if left[key] == right[key]:
            continue
        findings.append(
            _finding(
                "route_interface_incompatible",
                "error",
                "Route endpoints have incompatible authored interfaces.",
                subjects=(
                    str(source.get("qualifiedEndpointId") or ""),
                    str(target.get("qualifiedEndpointId") or ""),
                    key,
                ),
                details={
                    "routeKind": route_kind,
                    "sourceValue": left[key],
                    "targetValue": right[key],
                },
            )
        )
    return findings


def _route_endpoint_references(
    layout: Mapping[str, Any],
    *,
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]] = (),
    shell: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for placement in sorted(
        (
            item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping)
        ),
        key=lambda item: str(item.get("placementId") or ""),
    ):
        asset, finding = _asset_definition_for_placement(
            placement,
            asset_definitions,
        )
        if finding is not None or asset is None:
            continue
        for connector in sorted(
            (
                item
                for item in asset.get("connectors", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("connectorId"), str)
            ),
            key=lambda item: str(item.get("connectorId")),
        ):
            references.append(
                {
                    "kind": "placement_connector",
                    "placementId": str(placement.get("placementId") or ""),
                    "connectorId": str(connector["connectorId"]),
                }
            )
    for zone in sorted(
        (
            item for item in layout.get("zones", []) if isinstance(item, Mapping)
        ),
        key=lambda item: str(item.get("zoneId") or ""),
    ):
        for anchor in sorted(
            (
                item
                for item in zone.get("anchors", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("anchorId"), str)
            ),
            key=lambda item: str(item.get("anchorId")),
        ):
            references.append(
                {
                    "kind": "zone_anchor",
                    "zoneId": str(zone.get("zoneId") or ""),
                    "anchorId": str(anchor["anchorId"]),
                }
            )
    shell_document = shell
    shell_revision = None
    if isinstance(shell, Mapping) and isinstance(shell.get("document"), Mapping):
        shell_document = shell["document"]
        shell_revision = shell.get("revision")
    elif isinstance(shell, Mapping):
        shell_revision = shell.get("revision") or shell.get("shellRevision")
    source_ref = layout.get("sourceShellRef")
    if isinstance(shell_document, Mapping) and isinstance(source_ref, Mapping):
        for connector in sorted(
            (
                item
                for item in shell_document.get("shellConnectors", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("connectorId"), str)
            ),
            key=lambda item: str(item.get("connectorId")),
        ):
            references.append(
                {
                    "kind": "shell_connector",
                    "shellId": str(source_ref.get("shellId") or ""),
                    "shellRevision": str(
                        source_ref.get("shellRevision")
                        or shell_revision
                        or ""
                    ),
                    "connectorId": str(connector["connectorId"]),
                }
            )
    return references


def generate_connector_candidates(
    layout: Mapping[str, Any],
    source_endpoint: Mapping[str, Any],
    *,
    route_kind: str,
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]] = (),
    shell: Mapping[str, Any] | None = None,
    shell_revision: str | None = None,
    maximum_distance_meters: float | None = None,
    maximum_candidates: int = 64,
) -> dict[str, Any]:
    """Return stable, occurrence-qualified compatible connector targets."""

    source = resolve_endpoint(
        layout,
        source_endpoint,
        asset_definitions=asset_definitions,
        shell=shell,
        shell_revision=shell_revision,
        route_kind=route_kind,
        direction="source",
    )
    if not source.get("resolved"):
        return {
            "routeKind": route_kind,
            "source": source,
            "candidates": [],
            "findings": deepcopy(source.get("findings", [])),
            "processSemantics": dict(PROCESS_SEMANTICS),
        }
    limit = max(1, min(256, int(maximum_candidates)))
    maximum_distance = (
        None
        if maximum_distance_meters is None
        else _finite(maximum_distance_meters, "maximum_distance_meters")
    )
    layout_fingerprint = _sha256(
        {
            "placements": layout.get("placements", []),
            "zones": layout.get("zones", []),
            "sourceShellRef": layout.get("sourceShellRef"),
        }
    )
    candidates: list[dict[str, Any]] = []
    for endpoint in _route_endpoint_references(
        layout,
        asset_definitions=asset_definitions,
        shell=shell,
    ):
        target = resolve_endpoint(
            layout,
            endpoint,
            asset_definitions=asset_definitions,
            shell=shell,
            shell_revision=shell_revision,
            route_kind=route_kind,
            direction="target",
        )
        if (
            not target.get("resolved")
            or target.get("qualifiedEndpointId")
            == source.get("qualifiedEndpointId")
        ):
            continue
        compatibility_findings = _interface_findings(
            source,
            target,
            route_kind,
        )
        if any(
            item["severity"] in {"error", "blocked"}
            for item in compatibility_findings
        ):
            continue
        distance = math.dist(
            _vector3(source.get("position"), "source.position"),
            _vector3(target.get("position"), "target.position"),
        )
        if maximum_distance is not None and distance > maximum_distance + EPSILON:
            continue
        candidate_id = (
            "fcc-"
            + _sha256(
                {
                    "layoutFingerprint": layout_fingerprint,
                    "routeKind": route_kind,
                    "source": source["qualifiedEndpointId"],
                    "target": target["qualifiedEndpointId"],
                }
            )[:24]
        )
        candidates.append(
            {
                "candidateId": candidate_id,
                "routeKind": route_kind,
                "sourceEndpoint": deepcopy(dict(source_endpoint)),
                "targetEndpoint": deepcopy(endpoint),
                "sourceQualifiedEndpointId": source["qualifiedEndpointId"],
                "targetQualifiedEndpointId": target["qualifiedEndpointId"],
                "distanceMeters": _round(distance),
                "sourcePosition": deepcopy(source["position"]),
                "targetPosition": deepcopy(target["position"]),
                "layoutFingerprint": layout_fingerprint,
                "findings": compatibility_findings,
            }
        )
    candidates.sort(
        key=lambda item: (
            item["distanceMeters"],
            item["targetQualifiedEndpointId"],
            item["candidateId"],
        )
    )
    return {
        "routeKind": route_kind,
        "source": source,
        "candidates": candidates[:limit],
        "findings": [],
        "processSemantics": dict(PROCESS_SEMANTICS),
    }


def _route_poses(centerline: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    points = [_vector3(item, "route.centerline") for item in centerline]
    poses: list[dict[str, Any]] = []
    prior_heading = 0.0
    for index, point in enumerate(points):
        other = (
            points[index + 1]
            if index + 1 < len(points)
            else points[index - 1]
        )
        dx = other[0] - point[0]
        dz = other[2] - point[2]
        if index + 1 >= len(points):
            dx = point[0] - other[0]
            dz = point[2] - other[2]
        if abs(dx) > EPSILON or abs(dz) > EPSILON:
            prior_heading = math.atan2(dz, dx)
        poses.append(
            {
                "x": _round(point[0]),
                "z": _round(point[2]),
                "heading": _round(prior_heading, HEADING_DECIMAL_PLACES),
                "gear": "forward",
            }
        )
    return poses


def validate_route(
    layout: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]] = (),
    shell: Mapping[str, Any] | None = None,
    shell_revision: str | None = None,
    vehicle_profile: Mapping[str, Any] | None = None,
    traversable_polygons: Sequence[Any] = (),
    obstacles: Sequence[Any] = (),
    endpoint_tolerance_meters: float = 0.01,
) -> dict[str, Any]:
    """Validate persisted route semantics against current trusted geometry."""

    route_id = str(route.get("routeId") or "")
    route_kind = str(route.get("routeKind") or "")
    findings: list[Mapping[str, Any]] = []
    if route_kind not in ROUTE_KINDS:
        findings.append(
            _finding(
                "route_kind_invalid",
                "error",
                "Route kind is unsupported.",
                subjects=(route_id, route_kind),
            )
        )
    source = resolve_endpoint(
        layout,
        route.get("sourceEndpoint") or {},
        asset_definitions=asset_definitions,
        shell=shell,
        shell_revision=shell_revision,
        route_kind=route_kind,
        direction="source",
    )
    target = resolve_endpoint(
        layout,
        route.get("targetEndpoint") or {},
        asset_definitions=asset_definitions,
        shell=shell,
        shell_revision=shell_revision,
        route_kind=route_kind,
        direction="target",
    )
    findings.extend(source.get("findings", []))
    findings.extend(target.get("findings", []))
    if source.get("resolved") and target.get("resolved"):
        findings.extend(_interface_findings(source, target, route_kind))
    if (
        source.get("resolved")
        and target.get("resolved")
        and source.get("qualifiedEndpointId") == target.get("qualifiedEndpointId")
    ):
        findings.append(
            _finding(
                "route_self_connection",
                "error",
                "A route cannot connect one endpoint to itself.",
                subjects=(route_id, str(source.get("qualifiedEndpointId"))),
            )
        )
    raw_centerline = route.get("centerline")
    centerline = (
        [item for item in raw_centerline if isinstance(item, Mapping)]
        if isinstance(raw_centerline, list)
        else []
    )
    if len(centerline) >= 2 and source.get("resolved") and target.get("resolved"):
        tolerance = max(
            0.0,
            _finite(endpoint_tolerance_meters, "endpoint_tolerance_meters"),
        )
        for label, point, resolved in (
            ("source", centerline[0], source),
            ("target", centerline[-1], target),
        ):
            distance = math.dist(
                _vector3(point, f"{label}.centerline"),
                _vector3(resolved.get("position"), f"{label}.position"),
            )
            if distance > tolerance + EPSILON:
                findings.append(
                    _finding(
                        "route_endpoint_geometry_mismatch",
                        "error",
                        "Route centerline does not terminate at its resolved endpoint.",
                        subjects=(route_id, label),
                        details={
                            "distanceMeters": _round(distance),
                            "maximumMeters": _round(tolerance),
                        },
                    )
                )
    source_revisions = route.get("sourceRevisions")
    source_revisions = (
        dict(source_revisions)
        if isinstance(source_revisions, Mapping)
        else {}
    )
    expected_revisions = {
        "layout": routing_layout_fingerprint(layout),
    }
    source_shell_ref = layout.get("sourceShellRef")
    if isinstance(source_shell_ref, Mapping):
        expected_revisions["shell"] = str(
            source_shell_ref.get("shellRevision") or ""
        )
    policy_ref = layout.get("policySetRef")
    if isinstance(policy_ref, Mapping):
        expected_revisions["policy"] = str(
            policy_ref.get("policySetRevision") or ""
        )
    vehicle_ref = route.get("vehicleProfileRef")
    if isinstance(vehicle_ref, Mapping):
        expected_revisions["vehicle"] = str(
            vehicle_ref.get("vehicleProfileRevision") or ""
        )
    for key, expected_revision in sorted(expected_revisions.items()):
        if not expected_revision:
            continue
        if source_revisions.get(key) != expected_revision:
            findings.append(
                _finding(
                    "stale_route_source_revision",
                    "blocked",
                    "Route source revision no longer matches trusted layout state.",
                    subjects=(route_id, key),
                    details={
                        "expectedRevision": expected_revision,
                        "actualRevision": source_revisions.get(key),
                    },
                )
            )
    expected_fingerprint = persisted_route_fingerprint(route)
    if route.get("routeFingerprint") != expected_fingerprint:
        findings.append(
            _finding(
                "stale_route_geometry",
                "error",
                "Route fingerprint does not match its persisted geometry.",
                subjects=(route_id,),
                details={
                    "expectedFingerprint": expected_fingerprint,
                    "actualFingerprint": route.get("routeFingerprint"),
                },
            )
        )
    swept = None
    if route_kind == "forklift":
        if not isinstance(vehicle_profile, Mapping):
            findings.append(
                _finding(
                    "vehicle_profile_unavailable",
                    "blocked",
                    "Forklift route requires its revision-bound vehicle profile.",
                    subjects=(route_id,),
                )
            )
        elif not traversable_polygons:
            findings.append(
                _finding(
                    "route_traversable_space_unavailable",
                    "blocked",
                    "Forklift route requires trusted traversable-zone geometry.",
                    subjects=(route_id,),
                )
            )
        elif len(centerline) >= 2:
            swept = validate_swept_volume(
                _route_poses(centerline),
                vehicle_profile,
                traversable_polygons=traversable_polygons,
                obstacles=obstacles,
                load=(
                    route.get("load")
                    if isinstance(route.get("load"), Mapping)
                    else None
                ),
                allow_reverse=bool(route.get("reverseAllowed", False)),
            )
            findings.extend(swept.get("findings", []))
    ordered = _sort_findings(findings)
    return {
        "routeId": route_id,
        "valid": not any(
            item["severity"] in {"error", "blocked"} for item in ordered
        ),
        "source": source,
        "target": target,
        "sweptVolume": swept,
        "findings": ordered,
        "processSemantics": dict(PROCESS_SEMANTICS),
    }


def validate_utility_network(
    layout: Mapping[str, Any],
    network: Mapping[str, Any],
    *,
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]] = (),
    shell: Mapping[str, Any] | None = None,
    shell_revision: str | None = None,
    obstacles: Sequence[Any] = (),
    endpoint_tolerance_meters: float = 0.01,
) -> dict[str, Any]:
    """Resolve utility topology and reject incompatible services/interfaces."""

    network_id = str(network.get("utilityNetworkId") or "")
    service_type = str(network.get("networkKind") or "")
    findings: list[Mapping[str, Any]] = []
    if service_type not in UTILITY_KINDS:
        findings.append(
            _finding(
                "utility_type_incompatible",
                "error",
                "Utility network kind is unsupported.",
                subjects=(network_id, service_type),
            )
        )
    resolved_nodes: dict[str, dict[str, Any]] = {}
    raw_nodes = [
        item for item in network.get("nodes", []) if isinstance(item, Mapping)
    ]
    for node in sorted(raw_nodes, key=lambda item: str(item.get("networkNodeId"))):
        node_id = str(node.get("networkNodeId") or "")
        if node_id in resolved_nodes:
            findings.append(
                _finding(
                    "duplicate_network_node",
                    "error",
                    "Utility network node ID is duplicated.",
                    subjects=(network_id, node_id),
                )
            )
            continue
        if node.get("nodeKind") == "junction":
            try:
                position = _vector3(node.get("position"), "node.position")
            except ValueError as exc:
                findings.append(
                    _finding(
                        "invalid_connector_geometry",
                        "error",
                        str(exc),
                        subjects=(network_id, node_id),
                    )
                )
                continue
            resolved_nodes[node_id] = {
                "networkNodeId": node_id,
                "nodeKind": "junction",
                "networkRole": "junction",
                "position": _vector_dict(position),
                "serviceType": service_type,
                "interface": {},
            }
            continue
        if node.get("nodeKind") != "endpoint":
            findings.append(
                _finding(
                    "invalid_network_node",
                    "error",
                    "Utility network node kind is unsupported.",
                    subjects=(network_id, node_id),
                )
            )
            continue
        network_role = str(node.get("networkRole") or "")
        direction = "source" if network_role == "supply" else "target"
        resolved = resolve_endpoint(
            layout,
            node.get("endpointRef") or {},
            asset_definitions=asset_definitions,
            shell=shell,
            shell_revision=shell_revision,
            route_kind=service_type,
            direction=direction,
        )
        findings.extend(resolved.get("findings", []))
        if not resolved.get("resolved"):
            continue
        if resolved.get("serviceType") != service_type:
            findings.append(
                _finding(
                    "utility_type_incompatible",
                    "error",
                    "Utility endpoint service does not match the network.",
                    subjects=(
                        network_id,
                        node_id,
                        str(resolved.get("qualifiedEndpointId")),
                    ),
                    details={
                        "networkKind": service_type,
                        "endpointServiceType": resolved.get("serviceType"),
                    },
                )
            )
            continue
        resolved_nodes[node_id] = {
            "networkNodeId": node_id,
            "nodeKind": "endpoint",
            "networkRole": network_role,
            **{
                key: deepcopy(resolved[key])
                for key in (
                    "qualifiedEndpointId",
                    "position",
                    "facing",
                    "serviceType",
                    "role",
                    "interface",
                    "capacity",
                )
            },
        }

    resolved_segments = []
    raw_segments = [
        item for item in network.get("segments", []) if isinstance(item, Mapping)
    ]
    for segment in sorted(
        raw_segments, key=lambda item: str(item.get("networkSegmentId"))
    ):
        segment_id = str(segment.get("networkSegmentId") or "")
        source_id = str(segment.get("sourceNetworkNodeId") or "")
        target_id = str(segment.get("targetNetworkNodeId") or "")
        if source_id not in resolved_nodes or target_id not in resolved_nodes:
            findings.append(
                _finding(
                    "dangling_network_node",
                    "error",
                    "Utility segment references an unresolved network node.",
                    subjects=(network_id, segment_id, source_id, target_id),
                )
            )
            continue
        source_node = resolved_nodes[source_id]
        target_node = resolved_nodes[target_id]
        if (
            source_node.get("networkRole") == "sink"
            or target_node.get("networkRole") == "supply"
        ):
            findings.append(
                _finding(
                    "utility_flow_direction_invalid",
                    "error",
                    "Utility segment must flow from supply toward sink.",
                    subjects=(
                        network_id,
                        segment_id,
                        source_id,
                        target_id,
                    ),
                )
            )
        raw_centerline = segment.get("centerline")
        centerline = (
            [item for item in raw_centerline if isinstance(item, Mapping)]
            if isinstance(raw_centerline, list)
            else []
        )
        if len(centerline) >= 2:
            tolerance = max(
                0.0,
                _finite(
                    endpoint_tolerance_meters,
                    "endpoint_tolerance_meters",
                ),
            )
            for label, point, node in (
                ("source", centerline[0], source_node),
                ("target", centerline[-1], target_node),
            ):
                distance = math.dist(
                    _vector3(point, f"{label}.centerline"),
                    _vector3(node.get("position"), f"{label}.position"),
                )
                if distance > tolerance + EPSILON:
                    findings.append(
                        _finding(
                            "utility_endpoint_geometry_mismatch",
                            "error",
                            "Utility centerline does not terminate at its resolved node.",
                            subjects=(network_id, segment_id, label),
                            details={
                                "distanceMeters": _round(distance),
                                "maximumMeters": _round(tolerance),
                            },
                        )
                    )
            obstacle_records = _obstacle_records(obstacles)
            points2 = [
                (
                    _vector3(point, "utility.centerline")[0],
                    _vector3(point, "utility.centerline")[2],
                )
                for point in centerline
            ]
            crossed = set()
            for line_index in range(1, len(points2)):
                start = points2[line_index - 1]
                end = points2[line_index]
                for obstacle_id, polygon in obstacle_records:
                    interior_samples = [
                        (
                            start[0] + (end[0] - start[0]) * ratio,
                            start[1] + (end[1] - start[1]) * ratio,
                        )
                        for ratio in (0.01, 0.25, 0.5, 0.75, 0.99)
                    ]
                    boundary_crossing = any(
                        _segments_intersect(
                            start,
                            end,
                            polygon[index],
                            polygon[(index + 1) % len(polygon)],
                        )
                        for index in range(len(polygon))
                    )
                    endpoint_only = (
                        line_index == 1
                        and _point_in_polygon(start, polygon)
                        and not any(
                            _point_in_polygon(sample, polygon)
                            for sample in interior_samples
                        )
                    ) or (
                        line_index == len(points2) - 1
                        and _point_in_polygon(end, polygon)
                        and not any(
                            _point_in_polygon(sample, polygon)
                            for sample in interior_samples
                        )
                    )
                    if (
                        boundary_crossing
                        or any(
                            _point_in_polygon(sample, polygon)
                            for sample in interior_samples
                        )
                    ) and not endpoint_only:
                        crossed.add(obstacle_id)
            if crossed:
                findings.append(
                    _finding(
                        "utility_segment_obstructed",
                        "error",
                        "Utility centerline crosses trusted facility geometry.",
                        subjects=(
                            network_id,
                            segment_id,
                            *sorted(crossed),
                        ),
                    )
                )
        segment_interface = segment.get("interface")
        segment_interface = (
            dict(segment_interface) if isinstance(segment_interface, Mapping) else {}
        )
        for node_id in (source_id, target_id):
            endpoint_interface = resolved_nodes[node_id].get("interface") or {}
            if resolved_nodes[node_id]["nodeKind"] != "endpoint":
                continue
            for key in sorted(segment_interface):
                if key not in endpoint_interface:
                    findings.append(
                        _finding(
                            "utility_spec_mismatch",
                            "blocked",
                            "A required utility interface value is unknown.",
                            subjects=(network_id, segment_id, node_id, key),
                            details={"requiredValue": segment_interface[key]},
                        )
                    )
                elif endpoint_interface[key] != segment_interface[key]:
                    findings.append(
                        _finding(
                            "utility_spec_mismatch",
                            "error",
                            "Utility endpoint interface is incompatible.",
                            subjects=(network_id, segment_id, node_id, key),
                            details={
                                "requiredValue": segment_interface[key],
                                "actualValue": endpoint_interface[key],
                            },
                        )
                    )
        endpoint_node_ids = [
            node_id
            for node_id in (source_id, target_id)
            if resolved_nodes[node_id]["nodeKind"] == "endpoint"
        ]
        if len(endpoint_node_ids) == 2:
            left_interface = resolved_nodes[endpoint_node_ids[0]].get("interface") or {}
            right_interface = resolved_nodes[endpoint_node_ids[1]].get("interface") or {}
            for key in sorted(set(left_interface) | set(right_interface)):
                if key not in left_interface or key not in right_interface:
                    findings.append(
                        _finding(
                            "utility_spec_mismatch",
                            "blocked",
                            "Utility endpoint compatibility cannot be established.",
                            subjects=(
                                network_id,
                                segment_id,
                                endpoint_node_ids[0],
                                endpoint_node_ids[1],
                                key,
                            ),
                        )
                    )
                elif left_interface[key] != right_interface[key]:
                    findings.append(
                        _finding(
                            "utility_spec_mismatch",
                            "error",
                            "Utility endpoint interfaces are incompatible.",
                            subjects=(
                                network_id,
                                segment_id,
                                endpoint_node_ids[0],
                                endpoint_node_ids[1],
                                key,
                            ),
                            details={
                                "sourceValue": left_interface[key],
                                "targetValue": right_interface[key],
                            },
                        )
                    )
        segment_capacity = segment.get("capacity")
        segment_capacity = (
            dict(segment_capacity)
            if isinstance(segment_capacity, Mapping)
            else {}
        )
        for node_id in endpoint_node_ids:
            endpoint_capacity = resolved_nodes[node_id].get("capacity") or {}
            for key, requested_value in sorted(segment_capacity.items()):
                if key not in endpoint_capacity:
                    continue
                actual_value = endpoint_capacity[key]
                if (
                    isinstance(requested_value, (int, float))
                    and not isinstance(requested_value, bool)
                    and isinstance(actual_value, (int, float))
                    and not isinstance(actual_value, bool)
                    and float(requested_value) > float(actual_value) + EPSILON
                ):
                    findings.append(
                        _finding(
                            "utility_capacity_exceeded",
                            "error",
                            "Utility segment demand exceeds endpoint capacity.",
                            subjects=(
                                network_id,
                                segment_id,
                                node_id,
                                key,
                            ),
                            details={
                                "requestedValue": requested_value,
                                "maximumValue": actual_value,
                            },
                        )
                    )
        resolved_segments.append(
            {
                "networkSegmentId": segment_id,
                "sourceNetworkNodeId": source_id,
                "targetNetworkNodeId": target_id,
                "serviceType": service_type,
                "interface": _canonical_copy(segment_interface),
                "capacity": _canonical_copy(dict(segment.get("capacity") or {})),
            }
        )
    ordered_findings = _sort_findings(findings)
    return {
        "networkId": network_id,
        "serviceType": service_type,
        "valid": not any(
            item["severity"] in {"error", "blocked"} for item in ordered_findings
        ),
        "resolvedNodes": [
            resolved_nodes[key] for key in sorted(resolved_nodes)
        ],
        "resolvedSegments": resolved_segments,
        "findings": ordered_findings,
        "processSemantics": dict(PROCESS_SEMANTICS),
    }


def _orientation(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (
        b[1] - a[1]
    ) * (c[0] - a[0])


def _point_on_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> bool:
    return (
        abs(_orientation(a, b, point)) <= EPSILON
        and min(a[0], b[0]) - EPSILON <= point[0] <= max(a[0], b[0]) + EPSILON
        and min(a[1], b[1]) - EPSILON <= point[1] <= max(a[1], b[1]) + EPSILON
    )


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    oa = _orientation(a, b, c)
    ob = _orientation(a, b, d)
    oc = _orientation(c, d, a)
    od = _orientation(c, d, b)
    if (
        ((oa > EPSILON and ob < -EPSILON) or (oa < -EPSILON and ob > EPSILON))
        and ((oc > EPSILON and od < -EPSILON) or (oc < -EPSILON and od > EPSILON))
    ):
        return True
    return (
        (abs(oa) <= EPSILON and _point_on_segment(c, a, b))
        or (abs(ob) <= EPSILON and _point_on_segment(d, a, b))
        or (abs(oc) <= EPSILON and _point_on_segment(a, c, d))
        or (abs(od) <= EPSILON and _point_on_segment(b, c, d))
    )


def _point_in_polygon(
    point: tuple[float, float],
    polygon: Sequence[tuple[float, float]],
) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _point_on_segment(point, previous, current):
            return True
        if (current[1] > point[1]) != (previous[1] > point[1]):
            x_intersection = (
                (previous[0] - current[0])
                * (point[1] - current[1])
                / (previous[1] - current[1])
                + current[0]
            )
            if point[0] < x_intersection:
                inside = not inside
        previous = current
    return inside


def _polygons_intersect(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
) -> bool:
    for index, a in enumerate(left):
        b = left[(index + 1) % len(left)]
        for other_index, c in enumerate(right):
            d = right[(other_index + 1) % len(right)]
            if _segments_intersect(a, b, c, d):
                return True
    return _point_in_polygon(left[0], right) or _point_in_polygon(right[0], left)


def _polygon(
    value: Any,
    label: str = "polygon",
) -> tuple[tuple[float, float], ...]:
    if isinstance(value, Mapping):
        value = value.get("boundary") or value.get("footprint")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a point array")
    result = tuple(_point2(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(result) < 3 or len(set(result)) != len(result):
        raise ValueError(f"{label} must have at least three unique points")
    return result


def _polygon_centroid(
    polygon: Sequence[tuple[float, float]],
) -> tuple[float, float]:
    area_twice = 0.0
    x_sum = 0.0
    z_sum = 0.0
    for index, point in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        cross = point[0] * following[1] - following[0] * point[1]
        area_twice += cross
        x_sum += (point[0] + following[0]) * cross
        z_sum += (point[1] + following[1]) * cross
    if abs(area_twice) <= EPSILON:
        return (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
        )
    return x_sum / (3.0 * area_twice), z_sum / (3.0 * area_twice)


def _intersection_centroid(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
) -> tuple[float, float] | None:
    candidates: list[tuple[float, float]] = []
    candidates.extend(point for point in left if _point_in_polygon(point, right))
    candidates.extend(point for point in right if _point_in_polygon(point, left))
    for index, a in enumerate(left):
        b = left[(index + 1) % len(left)]
        for other_index, c in enumerate(right):
            d = right[(other_index + 1) % len(right)]
            denominator = (a[0] - b[0]) * (c[1] - d[1]) - (
                a[1] - b[1]
            ) * (c[0] - d[0])
            if abs(denominator) <= EPSILON:
                continue
            determinant_left = a[0] * b[1] - a[1] * b[0]
            determinant_right = c[0] * d[1] - c[1] * d[0]
            x = (
                determinant_left * (c[0] - d[0])
                - (a[0] - b[0]) * determinant_right
            ) / denominator
            z = (
                determinant_left * (c[1] - d[1])
                - (a[1] - b[1]) * determinant_right
            ) / denominator
            point = (x, z)
            if _point_on_segment(point, a, b) and _point_on_segment(point, c, d):
                candidates.append(point)
    unique = sorted(
        {(_round(point[0]), _round(point[1])) for point in candidates}
    )
    if not unique:
        return None
    return (
        sum(point[0] for point in unique) / len(unique),
        sum(point[1] for point in unique) / len(unique),
    )


def _segment_inside_polygon(
    start: tuple[float, float],
    end: tuple[float, float],
    polygon: Sequence[tuple[float, float]],
) -> bool:
    for index in range(21):
        ratio = index / 20.0
        point = (
            start[0] + (end[0] - start[0]) * ratio,
            start[1] + (end[1] - start[1]) * ratio,
        )
        if not _point_in_polygon(point, polygon):
            return False
    return True


def build_aisle_topology(
    layout: Mapping[str, Any],
    *,
    route_kind: str = "forklift",
    extra_points: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic graph from aisle zones and qualified anchors."""

    aisles = []
    findings = []
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping) or zone.get("zoneType") != "aisle":
            continue
        zone_id = str(zone.get("zoneId") or "")
        try:
            boundary = _polygon(zone.get("boundary"), f"aisle {zone_id}")
        except ValueError as exc:
            findings.append(
                _finding(
                    "invalid_aisle_geometry",
                    "error",
                    str(exc),
                    subjects=(zone_id,),
                )
            )
            continue
        aisles.append((zone_id, boundary, zone))
    aisles.sort(key=lambda item: item[0])
    nodes: dict[str, dict[str, Any]] = {}
    for zone_id, boundary, zone in aisles:
        center = _polygon_centroid(boundary)
        nodes[f"aisle:{zone_id}:center"] = {
            "nodeId": f"aisle:{zone_id}:center",
            "position": _point_dict(center),
            "zoneIds": [zone_id],
            "kind": "aisle_center",
        }
        for anchor in zone.get("anchors", []):
            if not isinstance(anchor, Mapping):
                continue
            if route_kind not in anchor.get("allowedRouteKinds", []):
                continue
            anchor_id = str(anchor.get("anchorId") or "")
            point = _point2(anchor.get("position"), f"anchor {anchor_id}")
            node_id = f"anchor:{zone_id}:{anchor_id}"
            nodes[node_id] = {
                "nodeId": node_id,
                "position": _point_dict(point),
                "zoneIds": [zone_id],
                "kind": "zone_anchor",
            }
    for left_index, (left_id, left, _) in enumerate(aisles):
        for right_id, right, _ in aisles[left_index + 1 :]:
            point = _intersection_centroid(left, right)
            if point is None:
                continue
            node_id = f"intersection:{left_id}:{right_id}"
            nodes[node_id] = {
                "nodeId": node_id,
                "position": _point_dict(point),
                "zoneIds": [left_id, right_id],
                "kind": "aisle_intersection",
            }
    for node_id, raw_point in sorted((extra_points or {}).items()):
        point = _point2(raw_point, f"extra point {node_id}")
        containing = [
            zone_id
            for zone_id, boundary, _ in aisles
            if _point_in_polygon(point, boundary)
        ]
        if not containing:
            findings.append(
                _finding(
                    "route_unreachable",
                    "error",
                    "Topology point is outside every aisle.",
                    subjects=(str(node_id),),
                )
            )
            continue
        nodes[str(node_id)] = {
            "nodeId": str(node_id),
            "position": _point_dict(point),
            "zoneIds": containing,
            "kind": "requested_point",
        }
    edges = []
    node_values = [nodes[key] for key in sorted(nodes)]
    aisle_by_id = {item[0]: item[1] for item in aisles}
    for index, left in enumerate(node_values):
        for right in node_values[index + 1 :]:
            shared = sorted(set(left["zoneIds"]) & set(right["zoneIds"]))
            if not shared:
                continue
            start = _point2(left["position"])
            end = _point2(right["position"])
            valid_zones = [
                zone_id
                for zone_id in shared
                if _segment_inside_polygon(start, end, aisle_by_id[zone_id])
            ]
            if not valid_zones:
                continue
            distance = math.dist(start, end)
            edge_id = (
                f"ae-{_sha256({'a': left['nodeId'], 'b': right['nodeId']})[:24]}"
            )
            edges.append(
                {
                    "edgeId": edge_id,
                    "sourceNodeId": left["nodeId"],
                    "targetNodeId": right["nodeId"],
                    "distanceMeters": _round(distance),
                    "zoneIds": valid_zones,
                }
            )
    edges.sort(key=lambda item: item["edgeId"])
    ordered_findings = _sort_findings(findings)
    fingerprint = stable_route_fingerprint(
        {
            "kind": "aisle_topology",
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": edges,
        }
    )
    return {
        "topologyFingerprint": fingerprint,
        "routeKind": route_kind,
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": edges,
        "findings": ordered_findings,
        "processSemantics": dict(PROCESS_SEMANTICS),
    }


def estimate_aisle_distance(
    topology: Mapping[str, Any],
    source_node_id: str,
    target_node_id: str,
) -> dict[str, Any]:
    """Run deterministic Dijkstra over an aisle topology."""

    nodes = {
        str(item.get("nodeId")): item
        for item in topology.get("nodes", [])
        if isinstance(item, Mapping)
    }
    if source_node_id not in nodes or target_node_id not in nodes:
        finding = _finding(
            "route_unreachable",
            "error",
            "A distance endpoint is absent from the aisle topology.",
            subjects=(source_node_id, target_node_id),
        )
        return {
            "reachable": False,
            "distanceMeters": None,
            "nodePath": [],
            "findings": [finding],
            "processSemantics": dict(PROCESS_SEMANTICS),
        }
    adjacency: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for edge in topology.get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("sourceNodeId"))
        target = str(edge.get("targetNodeId"))
        distance = _finite(edge.get("distanceMeters"), "edge.distanceMeters")
        edge_id = str(edge.get("edgeId"))
        adjacency[source].append((target, distance, edge_id))
        adjacency[target].append((source, distance, edge_id))
    for values in adjacency.values():
        values.sort(key=lambda item: (item[0], item[2]))
    queue = [(0.0, (source_node_id,), source_node_id)]
    best = {source_node_id: (0.0, (source_node_id,))}
    final: tuple[float, tuple[str, ...]] | None = None
    while queue:
        distance, path, node_id = heapq.heappop(queue)
        if best.get(node_id) != (distance, path):
            continue
        if node_id == target_node_id:
            final = distance, path
            break
        for neighbor, edge_distance, _ in adjacency.get(node_id, []):
            candidate = (distance + edge_distance, path + (neighbor,))
            if neighbor not in best or candidate < best[neighbor]:
                best[neighbor] = candidate
                heapq.heappush(queue, (*candidate, neighbor))
    if final is None:
        finding = _finding(
            "route_unreachable",
            "error",
            "No connected aisle path exists between the requested nodes.",
            subjects=(source_node_id, target_node_id),
        )
        return {
            "reachable": False,
            "distanceMeters": None,
            "nodePath": [],
            "findings": [finding],
            "processSemantics": dict(PROCESS_SEMANTICS),
        }
    return {
        "reachable": True,
        "distanceMeters": _round(final[0]),
        "nodePath": list(final[1]),
        "findings": [],
        "processSemantics": dict(PROCESS_SEMANTICS),
    }


def _heading(value: Any, label: str) -> float:
    result = _finite(value, label)
    while result <= -math.pi:
        result += 2 * math.pi
    while result > math.pi:
        result -= 2 * math.pi
    return result


def _cardinal_heading(value: float) -> int:
    raw = (value / (math.pi / 2.0)) % 4
    result = int(round(raw)) % 4
    target = result * math.pi / 2.0
    difference = abs(math.atan2(math.sin(value - target), math.cos(value - target)))
    if difference > 1e-6:
        raise ValueError("P7 heading lattice requires cardinal start and goal headings")
    return result


def _heading_radians(index: int) -> float:
    result = (index % 4) * math.pi / 2.0
    return result if result <= math.pi else result - 2 * math.pi


def normalized_cardinal_route_heading(
    start: Mapping[str, Any],
    end: Mapping[str, Any],
) -> float:
    """Normalize sub-0.1-degree route drafting drift to the P7 lattice.

    The threshold is a computational compatibility tolerance, not an
    engineering clearance or an authority for reinterpreting diagonal routes.
    """

    delta_x = _finite(end.get("x"), "route end.x") - _finite(
        start.get("x"), "route start.x"
    )
    delta_z = _finite(end.get("z"), "route end.z") - _finite(
        start.get("z"), "route start.z"
    )
    if math.hypot(delta_x, delta_z) <= EPSILON:
        raise ValueError("Route heading requires two distinct centerline points")
    raw = math.atan2(delta_z, delta_x)
    nearest = int(round(raw / (math.pi / 2.0))) % 4
    target = _heading_radians(nearest)
    difference = abs(
        math.atan2(math.sin(raw - target), math.cos(raw - target))
    )
    if difference > CARDINAL_ROUTE_ALIGNMENT_TOLERANCE_RADIANS + EPSILON:
        raise ValueError(
            "P7 motion playback requires a cardinal route centerline; the "
            "selected segment exceeds the 0.1-degree computational alignment "
            "tolerance"
        )
    return target


def _vehicle_footprints(
    vehicle_profile: Mapping[str, Any],
    load: Mapping[str, Any] | None,
) -> tuple[list[tuple[tuple[float, float], ...]], float, float]:
    footprint = _polygon(vehicle_profile.get("footprint"), "vehicle footprint")
    footprints = [footprint]
    if load and load.get("footprint") is not None:
        footprints.append(_polygon(load["footprint"], "load footprint"))
    all_points = [point for polygon in footprints for point in polygon]
    width = max(point[1] for point in all_points) - min(
        point[1] for point in all_points
    )
    length = max(point[0] for point in all_points) - min(
        point[0] for point in all_points
    )
    return footprints, width, length


def _transform_polygon(
    polygon: Sequence[tuple[float, float]],
    pose: Mapping[str, Any],
) -> tuple[tuple[float, float], ...]:
    x = _finite(pose.get("x"), "pose.x")
    z = _finite(pose.get("z"), "pose.z")
    heading = _heading(pose.get("heading"), "pose.heading")
    cosine = math.cos(heading)
    sine = math.sin(heading)
    return tuple(
        (
            x + point[0] * cosine - point[1] * sine,
            z + point[0] * sine + point[1] * cosine,
        )
        for point in polygon
    )


def _inside_union(
    polygon: Sequence[tuple[float, float]],
    traversable: Sequence[Sequence[tuple[float, float]]],
) -> bool:
    if not traversable:
        return False

    def convex(boundary: Sequence[tuple[float, float]]) -> bool:
        direction = 0
        for index, current in enumerate(boundary):
            following = boundary[(index + 1) % len(boundary)]
            after = boundary[(index + 2) % len(boundary)]
            cross = (
                (following[0] - current[0]) * (after[1] - following[1])
                - (following[1] - current[1]) * (after[0] - following[0])
            )
            if abs(cross) <= EPSILON:
                continue
            current_direction = 1 if cross > 0 else -1
            if direction and current_direction != direction:
                return False
            direction = current_direction
        return direction != 0

    # A convex polygon contains every segment between its contained points.
    # This exact fast path handles ordinary rectangular aisles without
    # constructing the more expensive general polygon-union sample set.
    for boundary in traversable:
        if convex(boundary) and all(
            _point_in_polygon(point, boundary) for point in polygon
        ):
            return True

    def covered(point: tuple[float, float]) -> bool:
        return any(
            _point_in_polygon(point, boundary)
            for boundary in traversable
        )

    def intersection_parameter(
        start: tuple[float, float],
        end: tuple[float, float],
        left: tuple[float, float],
        right: tuple[float, float],
    ) -> float | None:
        direction = (end[0] - start[0], end[1] - start[1])
        other = (right[0] - left[0], right[1] - left[1])
        denominator = direction[0] * other[1] - direction[1] * other[0]
        if abs(denominator) <= EPSILON:
            return None
        offset = (left[0] - start[0], left[1] - start[1])
        parameter = (
            offset[0] * other[1] - offset[1] * other[0]
        ) / denominator
        other_parameter = (
            offset[0] * direction[1] - offset[1] * direction[0]
        ) / denominator
        if (
            -EPSILON <= parameter <= 1.0 + EPSILON
            and -EPSILON <= other_parameter <= 1.0 + EPSILON
        ):
            return min(1.0, max(0.0, parameter))
        return None

    samples: list[tuple[float, float]] = list(polygon)
    samples.append(_polygon_centroid(polygon))
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        parameters = {0.0, 1.0}
        for boundary in traversable:
            for edge_index, left in enumerate(boundary):
                right = boundary[(edge_index + 1) % len(boundary)]
                parameter = intersection_parameter(
                    start,
                    end,
                    left,
                    right,
                )
                if parameter is not None:
                    parameters.add(parameter)
        ordered = sorted(parameters)
        for parameter in ordered:
            samples.append(
                (
                    start[0] + (end[0] - start[0]) * parameter,
                    start[1] + (end[1] - start[1]) * parameter,
                )
            )
        for left, right in zip(ordered, ordered[1:]):
            parameter = (left + right) / 2.0
            samples.append(
                (
                    start[0] + (end[0] - start[0]) * parameter,
                    start[1] + (end[1] - start[1]) * parameter,
                )
            )

    minimum_x = min(point[0] for point in polygon)
    maximum_x = max(point[0] for point in polygon)
    minimum_z = min(point[1] for point in polygon)
    maximum_z = max(point[1] for point in polygon)
    epsilon = max(
        EPSILON * 10.0,
        math.hypot(maximum_x - minimum_x, maximum_z - minimum_z)
        * 1e-7,
    )
    offsets = (
        (-epsilon, 0.0),
        (epsilon, 0.0),
        (0.0, -epsilon),
        (0.0, epsilon),
    )
    for boundary in traversable:
        for index, start in enumerate(boundary):
            end = boundary[(index + 1) % len(boundary)]
            midpoint = (
                (start[0] + end[0]) / 2.0,
                (start[1] + end[1]) / 2.0,
            )
            for point in (start, midpoint):
                if not _point_in_polygon(point, polygon):
                    continue
                samples.append(point)
                for offset in offsets:
                    candidate = (
                        point[0] + offset[0],
                        point[1] + offset[1],
                    )
                    if _point_in_polygon(candidate, polygon):
                        samples.append(candidate)

    return all(covered(sample) for sample in samples)


def _obstacle_records(
    obstacles: Sequence[Any],
) -> list[tuple[str, tuple[tuple[float, float], ...]]]:
    records = []
    for index, raw in enumerate(obstacles):
        if isinstance(raw, Mapping):
            obstacle_id = str(
                raw.get("obstacleId")
                or raw.get("placementId")
                or raw.get("zoneId")
                or f"obstacle-{index:04d}"
            )
            boundary = raw.get("boundary") or raw.get("footprint")
        else:
            obstacle_id = f"obstacle-{index:04d}"
            boundary = raw
        records.append((obstacle_id, _polygon(boundary, obstacle_id)))
    return sorted(records, key=lambda item: item[0])


def _polygon_bounds(
    polygon: Sequence[tuple[float, float]],
) -> tuple[float, float, float, float]:
    return (
        min(point[0] for point in polygon),
        min(point[1] for point in polygon),
        max(point[0] for point in polygon),
        max(point[1] for point in polygon),
    )


def _bounds_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] < right[0] - EPSILON
        or right[2] < left[0] - EPSILON
        or left[3] < right[1] - EPSILON
        or right[3] < left[1] - EPSILON
    )


def _obstacles_near_traversable_space(
    obstacles: Sequence[tuple[str, Sequence[tuple[float, float]]]],
    traversable: Sequence[Sequence[tuple[float, float]]],
) -> list[tuple[str, Sequence[tuple[float, float]]]]:
    """Discard obstacles whose bounds cannot intersect traversable space."""

    traversable_bounds = [_polygon_bounds(polygon) for polygon in traversable]
    return [
        obstacle
        for obstacle in obstacles
        if any(
            _bounds_overlap(_polygon_bounds(obstacle[1]), bounds)
            for bounds in traversable_bounds
        )
    ]


def projected_swept_sample_count(
    poses: Sequence[Mapping[str, Any]],
    spacing: float,
) -> int:
    """Return the exact number of poses ``_interpolate_poses`` will allocate."""

    resolved_spacing = _finite(spacing, "sample_spacing_meters")
    if resolved_spacing <= 0:
        raise ValueError("sample_spacing_meters must be positive")
    if not poses:
        return 0
    count = 1
    for index in range(1, len(poses)):
        previous = poses[index - 1]
        current = poses[index]
        start = (
            _finite(previous.get("x"), "pose.x"),
            _finite(previous.get("z"), "pose.z"),
        )
        end = (
            _finite(current.get("x"), "pose.x"),
            _finite(current.get("z"), "pose.z"),
        )
        count += max(1, int(math.ceil(math.dist(start, end) / resolved_spacing)))
    return count


def _require_motion_geometry_engine() -> None:
    if any(
        item is None
        for item in (
            GeometryCollection,
            LineString,
            MultiPolygon,
            Polygon,
            STRtree,
            orient_polygon,
            unary_union,
        )
    ):
        raise FacilityRoutingResourceError(
            "facility_motion_geometry_engine_unavailable",
            "Motion geometry requires the configured exact polygon engine.",
        )


def _ring_area_twice(points: Sequence[Mapping[str, Any]]) -> float:
    return sum(
        float(point["x"]) * float(points[(index + 1) % len(points)]["z"])
        - float(points[(index + 1) % len(points)]["x"]) * float(point["z"])
        for index, point in enumerate(points)
    )


def _canonical_motion_ring(
    coordinates: Sequence[Sequence[float]],
    *,
    counterclockwise: bool,
) -> list[dict[str, float]]:
    values = list(coordinates)
    if len(values) > 1 and values[0][:2] == values[-1][:2]:
        values.pop()
    points: list[dict[str, float]] = []
    for coordinate in values:
        point = {"x": _round(coordinate[0]), "z": _round(coordinate[1])}
        if not points or point != points[-1]:
            points.append(point)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3 or abs(_ring_area_twice(points)) <= EPSILON:
        raise FacilityRoutingResourceError(
            "facility_motion_swept_geometry_invalid",
            "Swept geometry collapsed during canonical normalization.",
        )
    is_counterclockwise = _ring_area_twice(points) > 0
    if is_counterclockwise != counterclockwise:
        points.reverse()
    start = min(
        range(len(points)),
        key=lambda index: (points[index]["x"], points[index]["z"], index),
    )
    return points[start:] + points[:start]


def _canonical_swept_geometry(shapes: Sequence[Any]) -> dict[str, Any]:
    _require_motion_geometry_engine()
    merged = unary_union(list(shapes))
    if not merged.is_valid:
        merged = merged.buffer(0)
    if merged.is_empty:
        raise FacilityRoutingResourceError(
            "facility_motion_swept_geometry_invalid",
            "Swept geometry is empty.",
        )
    if isinstance(merged, Polygon):
        polygon_parts = [merged]
    elif isinstance(merged, MultiPolygon):
        polygon_parts = list(merged.geoms)
    elif isinstance(merged, GeometryCollection):
        polygon_parts = [item for item in merged.geoms if isinstance(item, Polygon)]
    else:
        polygon_parts = []
    polygons = []
    for raw_polygon in polygon_parts:
        oriented = orient_polygon(raw_polygon, sign=1.0)
        exterior = _canonical_motion_ring(
            oriented.exterior.coords,
            counterclockwise=True,
        )
        holes = [
            _canonical_motion_ring(ring.coords, counterclockwise=False)
            for ring in oriented.interiors
        ]
        holes.sort(
            key=lambda ring: (
                ring[0]["x"],
                ring[0]["z"],
                abs(_ring_area_twice(ring)),
            )
        )
        polygons.append({"exterior": exterior, "holes": holes})
    if not polygons:
        raise FacilityRoutingResourceError(
            "facility_motion_swept_geometry_invalid",
            "Swept geometry contains no polygonal component.",
        )
    polygons.sort(
        key=lambda item: (
            item["exterior"][0]["x"],
            item["exterior"][0]["z"],
            abs(_ring_area_twice(item["exterior"])),
        )
    )
    return {
        "polygons": polygons,
        "ringOrientation": {
            "exterior": "counterclockwise",
            "holes": "clockwise",
        },
        "startVertexRule": "lowest_x_then_z_lexicographic",
        "precisionDecimals": METER_DECIMAL_PLACES,
        "polygonSortKey": "first_vertex_then_area",
    }


def route_traversable_corridor(
    route: Mapping[str, Any],
) -> list[list[dict[str, float]]]:
    """Derive exact traversable polygons from one authored route corridor."""

    _require_motion_geometry_engine()
    centerline = route.get("centerline")
    if not isinstance(centerline, list) or len(centerline) < 2:
        raise FacilityRoutingResourceError(
            "facility_motion_route_geometry_unavailable",
            "The selected route has no replayable centerline.",
        )
    try:
        points = [
            (
                _finite(point.get("x"), "route.centerline.x"),
                _finite(point.get("z"), "route.centerline.z"),
            )
            for point in centerline
            if isinstance(point, Mapping)
        ]
        width = _finite(route.get("corridorWidth"), "route.corridorWidth")
    except ValueError as exc:
        raise FacilityRoutingResourceError(
            "facility_motion_route_geometry_unavailable",
            "The selected route corridor is invalid.",
        ) from exc
    if len(points) < 2 or width <= 0:
        raise FacilityRoutingResourceError(
            "facility_motion_route_geometry_unavailable",
            "The selected route requires a positive-width centerline corridor.",
        )
    corridor = LineString(points).buffer(
        width / 2.0,
        cap_style=3,
        join_style=2,
    )
    if corridor.is_empty or not corridor.is_valid:
        raise FacilityRoutingResourceError(
            "facility_motion_route_geometry_unavailable",
            "The selected route corridor could not be resolved.",
        )
    parts = [corridor] if isinstance(corridor, Polygon) else list(corridor.geoms)
    return [
        [
            {"x": _round(x), "z": _round(z)}
            for x, z in list(part.exterior.coords)[:-1]
        ]
        for part in parts
        if isinstance(part, Polygon)
    ]


def _interpolate_poses(
    poses: Sequence[Mapping[str, Any]],
    spacing: float,
) -> list[dict[str, Any]]:
    result = []
    for index, current in enumerate(poses):
        if index == 0:
            result.append(dict(current))
            continue
        previous = poses[index - 1]
        start = (_finite(previous.get("x"), "pose.x"), _finite(previous.get("z"), "pose.z"))
        end = (_finite(current.get("x"), "pose.x"), _finite(current.get("z"), "pose.z"))
        start_heading = _heading(previous.get("heading"), "pose.heading")
        end_heading = _heading(current.get("heading"), "pose.heading")
        heading_delta = math.atan2(
            math.sin(end_heading - start_heading),
            math.cos(end_heading - start_heading),
        )
        distance = math.dist(start, end)
        steps = max(1, int(math.ceil(distance / spacing)))
        for step in range(1, steps + 1):
            ratio = step / steps
            result.append(
                {
                    "x": start[0] + (end[0] - start[0]) * ratio,
                    "z": start[1] + (end[1] - start[1]) * ratio,
                    "heading": start_heading + heading_delta * ratio,
                    "gear": current.get("gear", "forward"),
                }
            )
    return result


def validate_swept_volume(
    poses: Sequence[Mapping[str, Any]],
    vehicle_profile: Mapping[str, Any],
    *,
    traversable_polygons: Sequence[Any],
    obstacles: Sequence[Any] = (),
    load: Mapping[str, Any] | None = None,
    sample_spacing_meters: float = 0.1,
    allow_reverse: bool | None = None,
    maximum_sample_count: int = MAXIMUM_SWEPT_VOLUME_SAMPLES,
    maximum_obstacle_comparisons: int = MAXIMUM_SWEEP_OBSTACLE_COMPARISONS,
) -> dict[str, Any]:
    """Independently recheck a complete route's footprint sweep."""

    if len(poses) < 2:
        finding = _finding(
            "route_unreachable",
            "error",
            "A vehicle route requires at least two poses.",
        )
        return {
            "valid": False,
            "sampledPoseCount": 0,
            "effectiveWidthMeters": None,
            "effectiveLengthMeters": None,
            "sampleSpacingMeters": None,
            "sweptEnvelopeRevision": SWEPT_ENVELOPE_REVISION,
            "findings": [finding],
        }
    spacing = _finite(sample_spacing_meters, "sample_spacing_meters")
    if spacing <= 0:
        raise ValueError("sample_spacing_meters must be positive")
    projected_count = projected_swept_sample_count(poses, spacing)
    if projected_count > int(maximum_sample_count):
        raise FacilityRoutingResourceError(
            "facility_route_sample_budget_exceeded",
            "The requested route resolution exceeds the motion sample budget.",
            details={
                "projectedSampleCount": projected_count,
                "maximumSampleCount": int(maximum_sample_count),
                "requestedSampleSpacingMeters": _round(spacing),
            },
        )
    _require_motion_geometry_engine()
    traversable = [
        _polygon(value, f"traversable[{index}]")
        for index, value in enumerate(traversable_polygons)
    ]
    obstacle_records = _obstacle_records(obstacles)
    footprints, width, length = _vehicle_footprints(vehicle_profile, load)
    projected_comparisons = (
        projected_count * len(footprints) * len(obstacle_records)
    )
    if projected_comparisons > int(maximum_obstacle_comparisons):
        raise FacilityRoutingResourceError(
            "facility_route_clearance_budget_exceeded",
            "The route clearance analysis exceeds the geometry-work budget.",
            details={
                "projectedComparisonCount": projected_comparisons,
                "maximumComparisonCount": int(maximum_obstacle_comparisons),
                "projectedSampleCount": projected_count,
                "obstacleCount": len(obstacle_records),
                "footprintPartCount": len(footprints),
            },
        )
    sampled = _interpolate_poses(poses, spacing)
    sampled_distances = [0.0]
    for index in range(1, len(sampled)):
        sampled_distances.append(
            sampled_distances[-1]
            + math.dist(
                (float(sampled[index - 1]["x"]), float(sampled[index - 1]["z"])),
                (float(sampled[index]["x"]), float(sampled[index]["z"])),
            )
        )
    obstacle_shapes = [Polygon(item[1]) for item in obstacle_records]
    obstacle_tree = STRtree(obstacle_shapes) if obstacle_shapes else None
    findings = []
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    outside_reported = False
    collided: set[str] = set()
    sampled_shapes = []
    clearance_samples = []

    def location(index: int) -> dict[str, Any]:
        pose = sampled[index]
        return {
            "localized": True,
            "sampleIndex": index,
            "pose": {
                "x": _round(pose["x"]),
                "z": _round(pose["z"]),
                "heading": _round(
                    _heading(pose["heading"], "pose.heading"),
                    HEADING_DECIMAL_PLACES,
                ),
                "gear": str(pose.get("gear") or "forward"),
            },
            "distanceMeters": _round(sampled_distances[index]),
        }

    for index, pose in enumerate(sampled):
        sample_parts = []
        for local in footprints:
            world = _transform_polygon(local, pose)
            shape = Polygon(world)
            if not shape.is_valid:
                shape = shape.buffer(0)
            sample_parts.append(shape)
            for point in world:
                bounds[0] = min(bounds[0], point[0])
                bounds[1] = min(bounds[1], point[1])
                bounds[2] = max(bounds[2], point[0])
                bounds[3] = max(bounds[3], point[1])
            if traversable and not _inside_union(world, traversable):
                if not outside_reported:
                    findings.append(
                        _finding(
                            "route_width_insufficient",
                            "error",
                            "Vehicle swept volume leaves the traversable corridor.",
                            subjects=("swept-volume",),
                            details={"sampleIndex": index},
                        )
                    )
                    findings[-1]["location"] = location(index)
                    outside_reported = True
        sample_shape = unary_union(sample_parts)
        sampled_shapes.append(sample_shape)
        if obstacle_tree is not None:
            intersecting = sorted(
                (int(item) for item in obstacle_tree.query(
                    sample_shape,
                    predicate="intersects",
                )),
                key=lambda item: obstacle_records[item][0],
            )
            for obstacle_index in intersecting:
                obstacle_id = obstacle_records[obstacle_index][0]
                if obstacle_id not in collided:
                    collided.add(obstacle_id)
                    findings.append(
                        _finding(
                            "route_swept_volume_collision",
                            "error",
                            "Vehicle swept volume intersects an obstacle.",
                            subjects=("swept-volume", obstacle_id),
                            details={"sampleIndex": index},
                        )
                    )
                    findings[-1]["location"] = location(index)
            nearest_indices, nearest_distances = obstacle_tree.query_nearest(
                sample_shape,
                all_matches=True,
                return_distance=True,
            )
            pairs = sorted(
                (
                    (obstacle_records[int(obstacle_index)][0], float(distance))
                    for obstacle_index, distance in zip(
                        nearest_indices,
                        nearest_distances,
                    )
                ),
                key=lambda item: item[0],
            )
            minimum_distance = min(item[1] for item in pairs)
            nearest_ids = [
                obstacle_id
                for obstacle_id, distance in pairs
                if math.isclose(
                    distance,
                    minimum_distance,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            ]
            clearance = _round(minimum_distance)
        else:
            nearest_ids = []
            clearance = None
        clearance_samples.append(
            {
                "distanceMeters": _round(sampled_distances[index]),
                "nearestObstacleIds": nearest_ids,
                "clearanceMeters": clearance,
            }
        )
    minimum_radius = _finite(
        (vehicle_profile.get("steeringLimits") or {}).get(
            "minimumTurningRadiusMeters", 0
        ),
        "minimumTurningRadiusMeters",
    )
    for index in range(1, len(sampled)):
        previous = sampled[index - 1]
        current = sampled[index]
        distance = math.dist(
            (_finite(previous["x"], "pose.x"), _finite(previous["z"], "pose.z")),
            (_finite(current["x"], "pose.x"), _finite(current["z"], "pose.z")),
        )
        delta = abs(
            math.atan2(
                math.sin(
                    _heading(current["heading"], "pose.heading")
                    - _heading(previous["heading"], "pose.heading")
                ),
                math.cos(
                    _heading(current["heading"], "pose.heading")
                    - _heading(previous["heading"], "pose.heading")
                ),
            )
        )
        observed_radius = (
            distance / (2.0 * math.sin(delta / 2.0))
            if delta > 1e-6
            else math.inf
        )
        radius_tolerance = max(1e-4, minimum_radius * 0.005)
        if (
            delta > 1e-6
            and observed_radius + radius_tolerance < minimum_radius
        ):
            findings.append(
                _finding(
                    "route_turning_radius_violation",
                    "error",
                    "Route curvature is tighter than the vehicle profile permits.",
                    subjects=("swept-volume",),
                    details={
                        "minimumTurningRadiusMeters": _round(minimum_radius),
                        "observedRadiusMeters": _round(observed_radius),
                    },
                )
            )
            findings[-1]["location"] = location(index)
            break
    reverse_policy = str(vehicle_profile.get("reversePolicy") or "prohibited")
    reverse_permitted = (
        bool(allow_reverse)
        if allow_reverse is not None
        else reverse_policy in {"allowed", "permitted"}
    )
    first_reverse = next(
        (
            index
            for index, pose in enumerate(sampled)
            if pose.get("gear") == "reverse"
        ),
        None,
    )
    if first_reverse is not None and not reverse_permitted:
        findings.append(
            _finding(
                "route_reverse_not_allowed",
                "error",
                "Route uses reverse travel without an authorizing policy.",
                subjects=("swept-volume", reverse_policy),
            )
        )
        findings[-1]["location"] = location(first_reverse)
    for finding in findings:
        if finding.get("severity") == "error" and "location" not in finding:
            finding["location"] = {"localized": False}
    ordered = _sort_findings(findings)
    localized_errors = [
        item
        for item in ordered
        if item.get("severity") == "error"
        and (item.get("location") or {}).get("localized") is True
    ]
    blocking_index = (
        min(int(item["location"]["sampleIndex"]) for item in localized_errors)
        if localized_errors
        else None
    )
    geometry_shapes = (
        sampled_shapes
        if blocking_index is None
        else sampled_shapes[: blocking_index + 1]
    )
    blocking_findings = [
        item
        for item in localized_errors
        if int(item["location"]["sampleIndex"]) == blocking_index
    ]
    blocking_obstacles = sorted(
        {
            subject
            for item in blocking_findings
            if item.get("code") == "route_swept_volume_collision"
            for subject in item.get("subjects", [])
            if subject != "swept-volume"
        }
    )
    blocking = (
        {
            "localized": True,
            "blockingSampleIndex": blocking_index,
            "blockingPose": location(blocking_index)["pose"],
            "blockingDistanceMeters": location(blocking_index)["distanceMeters"],
            "blockingObstacleIds": blocking_obstacles,
        }
        if blocking_index is not None
        else {"localized": False, "blockingObstacleIds": []}
    )
    return {
        "valid": not any(item["severity"] == "error" for item in ordered),
        "sampledPoseCount": len(sampled),
        "projectedSampleCount": projected_count,
        "sampleSpacingMeters": _round(spacing),
        "effectiveWidthMeters": _round(width),
        "effectiveLengthMeters": _round(length),
        "sweptEnvelopeRevision": SWEPT_ENVELOPE_REVISION,
        "sweptBounds": (
            None
            if math.isinf(bounds[0])
            else {
                "minimum": {"x": _round(bounds[0]), "z": _round(bounds[1])},
                "maximum": {"x": _round(bounds[2]), "z": _round(bounds[3])},
            }
        ),
        "geometry": _canonical_swept_geometry(geometry_shapes),
        "clearance": {
            "sampleSpacingMeters": _round(spacing),
            "samples": clearance_samples,
        },
        "blocking": blocking,
        "findings": ordered,
    }


def _action_samples(
    state: tuple[float, float, int, str],
    action: str,
    *,
    resolution: float,
    turning_radius: float,
    sample_spacing: float,
) -> tuple[tuple[float, float, int, str], list[dict[str, Any]], float]:
    x, z, heading_index, _ = state
    theta = heading_index * math.pi / 2.0
    forward = (math.cos(theta), math.sin(theta))
    left = (-forward[1], forward[0])
    if action in {"forward", "reverse"}:
        sign = 1.0 if action == "forward" else -1.0
        end = (
            _round(x + forward[0] * resolution * sign),
            _round(z + forward[1] * resolution * sign),
            heading_index,
            action,
        )
        pose = {
            "x": end[0],
            "z": end[1],
            "heading": _heading_radians(heading_index),
            "gear": action,
        }
        return end, [pose], resolution
    direction = 1.0 if action == "left" else -1.0
    center = (
        x + left[0] * turning_radius * direction,
        z + left[1] * turning_radius * direction,
    )
    start_relative = (x - center[0], z - center[1])
    arc_length = math.pi * turning_radius / 2.0
    steps = max(2, int(math.ceil(arc_length / sample_spacing)))
    poses = []
    for index in range(1, steps + 1):
        angle = direction * math.pi / 2.0 * index / steps
        cosine = math.cos(angle)
        sine = math.sin(angle)
        relative = (
            start_relative[0] * cosine - start_relative[1] * sine,
            start_relative[0] * sine + start_relative[1] * cosine,
        )
        poses.append(
            {
                "x": center[0] + relative[0],
                "z": center[1] + relative[1],
                "heading": theta + angle,
                "gear": "forward",
            }
        )
    final_heading = (heading_index + int(direction)) % 4
    end = (
        _round(poses[-1]["x"]),
        _round(poses[-1]["z"]),
        final_heading,
        "forward",
    )
    poses[-1].update(
        {
            "x": end[0],
            "z": end[1],
            "heading": _heading_radians(final_heading),
        }
    )
    return end, poses, arc_length


def _action_clear(
    samples: Sequence[Mapping[str, Any]],
    footprints: Sequence[Sequence[tuple[float, float]]],
    traversable: Sequence[Sequence[tuple[float, float]]],
    obstacles: Sequence[tuple[str, Sequence[tuple[float, float]]]],
) -> bool:
    for pose in samples:
        for footprint in footprints:
            world = _transform_polygon(footprint, pose)
            if traversable and not _inside_union(world, traversable):
                return False
            if any(_polygons_intersect(world, obstacle) for _, obstacle in obstacles):
                return False
    return True


def _reconstruct_route(
    final_state: tuple[float, float, int, str],
    start_state: tuple[float, float, int, str],
    came_from: Mapping[
        tuple[float, float, int, str],
        tuple[
            tuple[float, float, int, str],
            Sequence[Mapping[str, Any]],
            str,
            float,
        ],
    ],
) -> tuple[list[dict[str, Any]], list[str], float]:
    steps = []
    current = final_state
    while current != start_state:
        previous, poses, action, distance = came_from[current]
        steps.append((poses, action, distance))
        current = previous
    steps.reverse()
    poses = [
        {
            "x": start_state[0],
            "z": start_state[1],
            "heading": _heading_radians(start_state[2]),
            "gear": "forward",
        }
    ]
    actions = []
    distance = 0.0
    for action_poses, action, action_distance in steps:
        poses.extend(deepcopy([dict(item) for item in action_poses]))
        actions.append(action)
        distance += action_distance
    return poses, actions, distance


def _rejected_route(
    findings: Iterable[Mapping[str, Any]],
    *,
    loaded: bool,
    outcome: str = "unroutable",
    centerline: Sequence[Mapping[str, Any]] = (),
    poses: Sequence[Mapping[str, Any]] = (),
    actions: Sequence[str] = (),
    distance_meters: float | None = None,
    estimated_travel_seconds: float | None = None,
    swept_volume: Mapping[str, Any] | None = None,
    attempt_fingerprint: str | None = None,
    source_revisions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if outcome not in {"unroutable", "envelope_refused"}:
        raise ValueError("unsupported rejected route outcome")
    result = {
        "accepted": False,
        "outcome": outcome,
        "routingEngineVersion": ROUTING_ENGINE_VERSION,
        "routerVersion": ROUTER_VERSION,
        "routeFingerprint": None,
        "centerline": deepcopy([dict(item) for item in centerline]),
        "poses": deepcopy([dict(item) for item in poses]),
        "actions": [str(item) for item in actions],
        "distanceMeters": (
            None if distance_meters is None else _round(distance_meters)
        ),
        "estimatedTravelSeconds": (
            None
            if estimated_travel_seconds is None
            else _round(estimated_travel_seconds)
        ),
        "reverseUsed": "reverse" in actions,
        "loaded": loaded,
        "sweptVolume": (
            None if swept_volume is None else deepcopy(dict(swept_volume))
        ),
        "findings": _sort_findings(findings),
        "processSemantics": dict(PROCESS_SEMANTICS),
    }
    if attempt_fingerprint is not None:
        result["attemptFingerprint"] = str(attempt_fingerprint)
    if source_revisions is not None:
        result["sourceRevisions"] = deepcopy(dict(source_revisions))
    return result


def plan_forklift_route(
    start: Mapping[str, Any],
    goal: Mapping[str, Any],
    vehicle_profile: Mapping[str, Any],
    *,
    traversable_polygons: Sequence[Any],
    obstacles: Sequence[Any] = (),
    load: Mapping[str, Any] | None = None,
    allow_reverse: bool | None = None,
    grid_resolution_meters: float = 0.5,
    maximum_expansions: int = 50_000,
    source_revisions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan a deterministic cardinal heading-lattice forklift route.

    The planner uses straight and minimum-radius 90-degree arc primitives.
    Every accepted result is then passed through ``validate_swept_volume``.
    """

    loaded = load is not None
    try:
        resolution = _finite(grid_resolution_meters, "grid_resolution_meters")
        if resolution <= 0:
            raise ValueError("grid_resolution_meters must be positive")
        start_x = _finite(start.get("x"), "start.x")
        start_z = _finite(start.get("z"), "start.z")
        start_y = _finite(start.get("y", 0.0), "start.y")
        goal_x = _finite(goal.get("x"), "goal.x")
        goal_z = _finite(goal.get("z"), "goal.z")
        goal_y = _finite(goal.get("y", start_y), "goal.y")
        start_heading = _cardinal_heading(_heading(start.get("heading"), "start.heading"))
        goal_heading = _cardinal_heading(_heading(goal.get("heading"), "goal.heading"))
        traversable = [
            _polygon(value, f"traversable[{index}]")
            for index, value in enumerate(traversable_polygons)
        ]
        obstacle_records = _obstacles_near_traversable_space(
            _obstacle_records(obstacles),
            traversable,
        )
        footprints, effective_width, _ = _vehicle_footprints(vehicle_profile, load)
        minimum_radius = _finite(
            (vehicle_profile.get("steeringLimits") or {}).get(
                "minimumTurningRadiusMeters"
            ),
            "minimumTurningRadiusMeters",
        )
        if minimum_radius <= 0:
            raise ValueError("minimum turning radius must be positive")
    except ValueError as exc:
        return _rejected_route(
            [
                _finding(
                    "invalid_vehicle_route_request",
                    "error",
                    str(exc),
                )
            ],
            loaded=loaded,
            source_revisions=source_revisions,
        )
    maximum_load = (vehicle_profile.get("loadLimits") or {}).get(
        "maximumKilograms"
    )
    if load and load.get("massKilograms") is not None and maximum_load is not None:
        mass = _finite(load.get("massKilograms"), "load.massKilograms")
        if mass > _finite(maximum_load, "maximumKilograms"):
            return _rejected_route(
                [
                    _finding(
                        "route_load_exceeded",
                        "error",
                        "Requested load exceeds the vehicle profile.",
                        subjects=(str(vehicle_profile.get("vehicleProfileId") or ""),),
                        details={
                            "massKilograms": _round(mass),
                            "maximumKilograms": _round(float(maximum_load)),
                        },
                    )
                ],
                loaded=loaded,
                source_revisions=source_revisions,
            )
    direct_horizontal_distance = math.hypot(goal_x - start_x, goal_z - start_z)
    grade_percent = (
        math.inf
        if direct_horizontal_distance <= EPSILON and abs(goal_y - start_y) > EPSILON
        else (
            0.0
            if direct_horizontal_distance <= EPSILON
            else abs(goal_y - start_y) / direct_horizontal_distance * 100.0
        )
    )
    maximum_grade = (vehicle_profile.get("gradeLimits") or {}).get(
        "maximumPercent"
    )
    if maximum_grade is not None and grade_percent > _finite(
        maximum_grade, "maximumPercent"
    ) + EPSILON:
        return _rejected_route(
            [
                _finding(
                    "route_grade_exceeded",
                    "error",
                    "Requested route grade exceeds the vehicle profile.",
                    subjects=(str(vehicle_profile.get("vehicleProfileId") or ""),),
                    details={
                        "gradePercent": (
                            "infinite"
                            if math.isinf(grade_percent)
                            else _round(grade_percent)
                        ),
                        "maximumPercent": _round(float(maximum_grade)),
                    },
                )
            ],
            loaded=loaded,
            source_revisions=source_revisions,
        )
    if not traversable:
        return _rejected_route(
            [
                _finding(
                    "route_unreachable",
                    "error",
                    "No traversable aisle geometry is available.",
                )
            ],
            loaded=loaded,
            source_revisions=source_revisions,
        )
    polygon_widths = []
    for polygon in traversable:
        width = min(
            max(point[0] for point in polygon) - min(point[0] for point in polygon),
            max(point[1] for point in polygon) - min(point[1] for point in polygon),
        )
        polygon_widths.append(width)
    if polygon_widths and max(polygon_widths) + EPSILON < effective_width:
        return _rejected_route(
            [
                _finding(
                    "route_width_insufficient",
                    "error",
                    "Every available aisle is narrower than the vehicle envelope.",
                    details={
                        "requiredWidthMeters": _round(effective_width),
                        "maximumAisleWidthMeters": _round(max(polygon_widths)),
                    },
                )
            ],
            loaded=loaded,
            source_revisions=source_revisions,
        )
    reverse_policy = str(vehicle_profile.get("reversePolicy") or "prohibited")
    reverse_permitted = (
        bool(allow_reverse)
        if allow_reverse is not None
        else reverse_policy in {"allowed", "permitted"}
    )
    turning_radius = math.ceil(minimum_radius / resolution - EPSILON) * resolution
    start_state = (
        _round(round(start_x / resolution) * resolution),
        _round(round(start_z / resolution) * resolution),
        start_heading,
        "forward",
    )
    goal_key = (
        _round(round(goal_x / resolution) * resolution),
        _round(round(goal_z / resolution) * resolution),
        goal_heading,
    )
    start_pose = {
        "x": start_state[0],
        "z": start_state[1],
        "heading": _heading_radians(start_heading),
        "gear": "forward",
    }
    goal_pose = {
        "x": goal_key[0],
        "z": goal_key[1],
        "heading": _heading_radians(goal_heading),
        "gear": "forward",
    }
    if not _action_clear(
        [start_pose, goal_pose],
        footprints,
        traversable,
        obstacle_records,
    ):
        start_valid = _action_clear(
            [start_pose], footprints, traversable, obstacle_records
        )
        goal_valid = _action_clear(
            [goal_pose], footprints, traversable, obstacle_records
        )
        if not start_valid or not goal_valid:
            return _rejected_route(
                [
                    _finding(
                        "route_width_insufficient",
                        "error",
                        "Start or goal vehicle envelope is outside usable aisle space.",
                        subjects=tuple(
                            name
                            for name, valid in (
                                ("start", start_valid),
                                ("goal", goal_valid),
                            )
                            if not valid
                        ),
                    )
                ],
                loaded=loaded,
                source_revisions=source_revisions,
            )
    def heuristic(state: tuple[float, float, int, str]) -> float:
        heading_steps = min(
            (state[2] - goal_key[2]) % 4,
            (goal_key[2] - state[2]) % 4,
        )
        return math.hypot(state[0] - goal_key[0], state[1] - goal_key[1]) + (
            heading_steps * turning_radius * 0.25
        )

    queue: list[tuple[Any, ...]] = []
    start_path_key = (start_state[0], start_state[1], start_state[2], start_state[3])
    heapq.heappush(
        queue,
        (
            _round(heuristic(start_state), 9),
            0.0,
            0,
            start_path_key,
            start_state,
        ),
    )
    best: dict[tuple[float, float, int, str], tuple[float, int, tuple[Any, ...]]] = {
        start_state: (0.0, 0, start_path_key)
    }
    came_from: dict[
        tuple[float, float, int, str],
        tuple[
            tuple[float, float, int, str],
            Sequence[Mapping[str, Any]],
            str,
            float,
        ],
    ] = {}
    final_state = None
    expansions = 0
    while queue and expansions < maximum_expansions:
        _, cost, reversals, path_key, state = heapq.heappop(queue)
        if best.get(state) != (cost, reversals, path_key):
            continue
        expansions += 1
        if (state[0], state[1], state[2]) == goal_key:
            final_state = state
            break
        actions = ["forward", "left", "right"]
        if reverse_permitted:
            actions.append("reverse")
        for action in actions:
            next_state, samples, distance = _action_samples(
                state,
                action,
                resolution=resolution,
                turning_radius=turning_radius,
                sample_spacing=max(0.1, resolution / 2.0),
            )
            if not _action_clear(
                samples,
                footprints,
                traversable,
                obstacle_records,
            ):
                continue
            reverse_count = reversals + (1 if action == "reverse" else 0)
            action_cost = distance * (1.2 if action == "reverse" else 1.0)
            if state[3] != next_state[3]:
                action_cost += 0.05
            next_cost = _round(cost + action_cost, 9)
            next_path_key = path_key + (action,)
            candidate = (next_cost, reverse_count, next_path_key)
            if next_state in best and best[next_state] <= candidate:
                continue
            best[next_state] = candidate
            came_from[next_state] = (state, samples, action, distance)
            heapq.heappush(
                queue,
                (
                    _round(next_cost + heuristic(next_state), 9),
                    next_cost,
                    reverse_count,
                    next_path_key,
                    next_state,
                ),
            )
    if final_state is None:
        details = {
            "expandedStates": expansions,
            "maximumExpansions": maximum_expansions,
            "reverseAllowed": reverse_permitted,
        }
        return _rejected_route(
            [
                _finding(
                    "route_unreachable",
                    "error",
                    "No heading-aware route satisfies the vehicle constraints.",
                    details=details,
                )
            ],
            loaded=loaded,
            source_revisions=source_revisions,
        )
    poses, actions, distance = _reconstruct_route(
        final_state, start_state, came_from
    )
    swept = validate_swept_volume(
        poses,
        vehicle_profile,
        traversable_polygons=traversable_polygons,
        obstacles=obstacles,
        load=load,
        sample_spacing_meters=min(0.1, resolution / 4.0),
        allow_reverse=reverse_permitted,
    )
    if not swept["valid"]:
        attempted_horizontal_segments = [
            math.dist(
                (
                    float(poses[index - 1]["x"]),
                    float(poses[index - 1]["z"]),
                ),
                (float(poses[index]["x"]), float(poses[index]["z"])),
            )
            for index in range(1, len(poses))
        ]
        attempted_total_horizontal = sum(attempted_horizontal_segments)
        attempted_cumulative = 0.0
        attempted_centerline = []
        for index, pose in enumerate(poses):
            if index:
                attempted_cumulative += attempted_horizontal_segments[index - 1]
            ratio = (
                attempted_cumulative / attempted_total_horizontal
                if attempted_total_horizontal > EPSILON
                else 0.0
            )
            attempted_centerline.append(
                {
                    "x": _round(pose["x"]),
                    "y": _round(start_y + (goal_y - start_y) * ratio),
                    "z": _round(pose["z"]),
                }
            )
        attempted_poses = [
            {
                "x": _round(pose["x"]),
                "z": _round(pose["z"]),
                "heading": _round(
                    _heading(pose["heading"], "pose.heading"),
                    HEADING_DECIMAL_PLACES,
                ),
                "gear": str(pose.get("gear") or "forward"),
            }
            for pose in poses
        ]
        attempted_maximum_speed = _finite(
            (vehicle_profile.get("speedLimits") or {}).get(
                "maximumMetersPerSecond", 1.0
            ),
            "maximumMetersPerSecond",
        )
        attempted_seconds = (
            distance / attempted_maximum_speed
            if attempted_maximum_speed > 0
            else None
        )
        attempt_input = {
            "fingerprintKind": "facility-route-attempt-v1",
            "start": {
                "x": start_state[0],
                "z": start_state[1],
                "heading": _heading_radians(start_heading),
            },
            "goal": {
                "x": goal_key[0],
                "z": goal_key[1],
                "heading": _heading_radians(goal_heading),
            },
            "vehicleProfileId": vehicle_profile.get("vehicleProfileId"),
            "vehicleProfileRevision": vehicle_profile.get(
                "vehicleProfileRevision"
            ),
            "loaded": loaded,
            "load": deepcopy(dict(load or {})),
            "centerline": attempted_centerline,
            "poses": attempted_poses,
            "sourceRevisions": deepcopy(dict(source_revisions or {})),
            "obstacleFingerprint": _sha256(
                [
                    {"obstacleId": item[0], "polygon": item[1]}
                    for item in obstacle_records
                ]
            ),
            "traversableFingerprint": _sha256(traversable),
            "blocking": swept.get("blocking"),
        }
        return _rejected_route(
            swept["findings"],
            loaded=loaded,
            outcome="envelope_refused",
            centerline=attempted_centerline,
            poses=attempted_poses,
            actions=actions,
            distance_meters=distance,
            estimated_travel_seconds=attempted_seconds,
            swept_volume=swept,
            attempt_fingerprint=_sha256(attempt_input),
            source_revisions=source_revisions,
        )
    horizontal_segments = [
        math.dist(
            (float(poses[index - 1]["x"]), float(poses[index - 1]["z"])),
            (float(poses[index]["x"]), float(poses[index]["z"])),
        )
        for index in range(1, len(poses))
    ]
    total_horizontal = sum(horizontal_segments)
    cumulative = 0.0
    centerline = []
    for index, pose in enumerate(poses):
        if index:
            cumulative += horizontal_segments[index - 1]
        ratio = cumulative / total_horizontal if total_horizontal > EPSILON else 0.0
        centerline.append(
            {
                "x": _round(pose["x"]),
                "y": _round(start_y + (goal_y - start_y) * ratio),
                "z": _round(pose["z"]),
            }
        )
    canonical_poses = [
        {
            "x": _round(pose["x"]),
            "z": _round(pose["z"]),
            "heading": _round(
                _heading(pose["heading"], "pose.heading"),
                HEADING_DECIMAL_PLACES,
            ),
            "gear": str(pose.get("gear") or "forward"),
        }
        for pose in poses
    ]
    maximum_speed = _finite(
        (vehicle_profile.get("speedLimits") or {}).get(
            "maximumMetersPerSecond", 1.0
        ),
        "maximumMetersPerSecond",
    )
    estimated_seconds = distance / maximum_speed if maximum_speed > 0 else None
    fingerprint_input = {
        "start": {
            "x": start_state[0],
            "z": start_state[1],
            "heading": _heading_radians(start_heading),
        },
        "goal": {
            "x": goal_key[0],
            "z": goal_key[1],
            "heading": _heading_radians(goal_heading),
        },
        "vehicleProfileId": vehicle_profile.get("vehicleProfileId"),
        "vehicleProfileRevision": vehicle_profile.get("vehicleProfileRevision"),
        "loaded": loaded,
        "load": deepcopy(dict(load or {})),
        "centerline": centerline,
        "poses": canonical_poses,
        "sourceRevisions": deepcopy(dict(source_revisions or {})),
        "obstacleFingerprint": _sha256(
            [
                {"obstacleId": item[0], "polygon": item[1]}
                for item in obstacle_records
            ]
        ),
        "traversableFingerprint": _sha256(traversable),
    }
    return {
        "accepted": True,
        "outcome": "accepted",
        "routingEngineVersion": ROUTING_ENGINE_VERSION,
        "routerVersion": ROUTER_VERSION,
        "routeFingerprint": stable_route_fingerprint(fingerprint_input),
        "centerline": centerline,
        "poses": canonical_poses,
        "actions": actions,
        "distanceMeters": _round(distance),
        "estimatedTravelSeconds": (
            None if estimated_seconds is None else _round(estimated_seconds)
        ),
        "reverseUsed": "reverse" in actions,
        "loaded": loaded,
        "sourceRevisions": deepcopy(dict(source_revisions or {})),
        "sweptVolume": swept,
        "findings": [],
        "processSemantics": dict(PROCESS_SEMANTICS),
    }
