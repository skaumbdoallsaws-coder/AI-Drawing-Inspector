"""Deterministic Facility Layout canonicalization and revisions."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
import math
from typing import Any, Mapping, MutableMapping, Sequence

from .errors import FacilityCompatibilityError, FacilityValidationError


METER_DECIMAL_PLACES = 6
QUATERNION_DECIMAL_PLACES = 9
QUATERNION_NORMALIZATION_TOLERANCE = 1e-9
MAXIMUM_ABSOLUTE_WORLD_COORDINATE_METERS = 1_000_000


def _fail(code: str, message: str, path: str) -> None:
    raise FacilityValidationError(code, message, details={"path": path})


def _canonical_value_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise FacilityValidationError(
            "invalid_json_value",
            "Facility Layout data must be finite JSON-compatible data.",
        ) from exc
    return encoded.encode("ascii")


def _detached_json(value: Any) -> Any:
    return json.loads(_canonical_value_bytes(value).decode("ascii"))


def _number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("non_finite_transform", "Expected a finite number.", path)
    if not math.isfinite(value):
        _fail("non_finite_transform", "Expected a finite number.", path)
    return value


def _rounded_number(value: Any, places: int, path: str) -> int | float:
    number = _number(value, path)
    try:
        quantum = Decimal(1).scaleb(-places)
        rounded = Decimal(str(number)).quantize(quantum, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, ValueError) as exc:
        _fail("non_finite_transform", "Could not canonicalize number.", path)
        raise AssertionError("unreachable") from exc
    if rounded == 0:
        return 0
    if rounded == rounded.to_integral_value():
        return int(rounded)
    return float(rounded)


def _mapping(value: Any, path: str) -> MutableMapping[str, Any]:
    if not isinstance(value, MutableMapping):
        _fail("invalid_layout_shape", "Expected an object.", path)
    return value


def _sequence(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("invalid_layout_shape", "Expected an array.", path)
    return value


def _canonical_vector(
    value: Any,
    keys: Sequence[str],
    path: str,
) -> MutableMapping[str, Any]:
    vector = _mapping(value, path)
    for key in keys:
        if key in vector:
            vector[key] = _rounded_number(
                vector[key],
                METER_DECIMAL_PLACES,
                f"{path}.{key}",
            )
    return vector


def _orientation(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    c: Mapping[str, Any],
) -> float:
    return (
        (float(b["x"]) - float(a["x"])) * (float(c["z"]) - float(a["z"]))
        - (float(b["z"]) - float(a["z"])) * (float(c["x"]) - float(a["x"]))
    )


def _point_on_segment(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    point: Mapping[str, Any],
) -> bool:
    epsilon = 1e-12
    if abs(_orientation(a, b, point)) > epsilon:
        return False
    return (
        min(float(a["x"]), float(b["x"])) - epsilon
        <= float(point["x"])
        <= max(float(a["x"]), float(b["x"])) + epsilon
        and min(float(a["z"]), float(b["z"])) - epsilon
        <= float(point["z"])
        <= max(float(a["z"]), float(b["z"])) + epsilon
    )


def _segments_intersect(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    c: Mapping[str, Any],
    d: Mapping[str, Any],
) -> bool:
    epsilon = 1e-12
    first_c = _orientation(a, b, c)
    first_d = _orientation(a, b, d)
    second_a = _orientation(c, d, a)
    second_b = _orientation(c, d, b)
    if (
        ((first_c > epsilon and first_d < -epsilon) or
         (first_c < -epsilon and first_d > epsilon))
        and
        ((second_a > epsilon and second_b < -epsilon) or
         (second_a < -epsilon and second_b > epsilon))
    ):
        return True
    return (
        (abs(first_c) <= epsilon and _point_on_segment(a, b, c))
        or (abs(first_d) <= epsilon and _point_on_segment(a, b, d))
        or (abs(second_a) <= epsilon and _point_on_segment(c, d, a))
        or (abs(second_b) <= epsilon and _point_on_segment(c, d, b))
    )


def _polygon_area_twice(points: Sequence[Mapping[str, Any]]) -> float:
    area = 0.0
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        area += (
            float(point["x"]) * float(following["z"])
            - float(following["x"]) * float(point["z"])
        )
    return area


def _validate_polygon_geometry(
    points: Sequence[Mapping[str, Any]],
    path: str,
) -> None:
    if len(points) < 3:
        _fail("invalid_polygon", "A zone needs at least three vertices.", path)
    identities = [(point.get("x"), point.get("z")) for point in points]
    if len(identities) != len(set(identities)):
        _fail("invalid_polygon", "A zone boundary repeats a vertex.", path)
    if identities[0] == identities[-1]:
        _fail(
            "invalid_polygon",
            "A zone boundary must use implicit closure.",
            path,
        )
    if abs(_polygon_area_twice(points)) <= 1e-12:
        _fail("invalid_polygon", "A zone boundary has zero area.", path)

    edge_count = len(points)
    for first_index in range(edge_count):
        first_next = (first_index + 1) % edge_count
        for second_index in range(first_index + 1, edge_count):
            second_next = (second_index + 1) % edge_count
            if first_index in (second_index, second_next):
                continue
            if first_next in (second_index, second_next):
                continue
            if _segments_intersect(
                points[first_index],
                points[first_next],
                points[second_index],
                points[second_next],
            ):
                _fail("invalid_polygon", "A zone boundary self-intersects.", path)


def canonicalize_polygon(value: Any, path: str = "$.boundary") -> list[dict[str, Any]]:
    points = _sequence(value, path)
    canonical: list[dict[str, Any]] = []
    for index, raw_point in enumerate(points):
        point = _mapping(raw_point, f"{path}[{index}]")
        canonical.append(
            {
                **point,
                "x": _rounded_number(
                    point.get("x"),
                    METER_DECIMAL_PLACES,
                    f"{path}[{index}].x",
                ),
                "z": _rounded_number(
                    point.get("z"),
                    METER_DECIMAL_PLACES,
                    f"{path}[{index}].z",
                ),
            }
        )
    _validate_polygon_geometry(canonical, path)
    if _polygon_area_twice(canonical) < 0:
        canonical = [canonical[0], *reversed(canonical[1:])]
    return canonical


def canonicalize_quaternion(
    value: Any,
    path: str = "$.quaternion",
) -> dict[str, Any]:
    quaternion = _mapping(value, path)
    keys = ("x", "y", "z", "w")
    components = [_number(quaternion.get(key), f"{path}.{key}") for key in keys]
    norm = math.sqrt(sum(float(component) ** 2 for component in components))
    if not math.isclose(
        norm,
        1.0,
        rel_tol=0.0,
        abs_tol=QUATERNION_NORMALIZATION_TOLERANCE,
    ):
        _fail(
            "invalid_quaternion",
            "Placement quaternions must already have unit length.",
            path,
        )
    rounded = [
        _rounded_number(component, QUATERNION_DECIMAL_PLACES, f"{path}.{key}")
        for key, component in zip(keys, components)
    ]
    sign_probe = [rounded[3], rounded[0], rounded[1], rounded[2]]
    first_nonzero = next((item for item in sign_probe if item != 0), 0)
    if first_nonzero < 0:
        rounded = [-item for item in rounded]
    rounded = [0 if item == 0 else item for item in rounded]
    result = dict(quaternion)
    result.update(dict(zip(keys, rounded)))
    return result


def canonicalize_layout(layout: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached v1 layout with canonical known geometry.

    Unknown fields on compatible open objects are preserved verbatim.
    """

    if not isinstance(layout, Mapping):
        _fail("invalid_layout_shape", "Facility Layout must be an object.", "$")
    version = layout.get("schemaVersion")
    if isinstance(version, bool) or not isinstance(version, int):
        raise FacilityCompatibilityError(
            "unsupported_schema_version",
            "Facility Layout schemaVersion is unsupported.",
            details={"detectedSchemaVersion": version},
        )
    if version > 1:
        raise FacilityCompatibilityError(
            "unsupported_schema_version_read_only",
            "Newer Facility Layout schemas are read-only.",
            details={"detectedSchemaVersion": version},
        )
    if version != 1:
        raise FacilityCompatibilityError(
            "unsupported_schema_version",
            "Facility Layout schemaVersion is unsupported.",
            details={"detectedSchemaVersion": version},
        )

    result = deepcopy(dict(layout))
    frame = _mapping(result.get("coordinateFrame"), "$.coordinateFrame")
    if "floorElevation" in frame:
        frame["floorElevation"] = _rounded_number(
            frame["floorElevation"],
            METER_DECIMAL_PLACES,
            "$.coordinateFrame.floorElevation",
        )

    zones = _sequence(result.get("zones"), "$.zones")
    for zone_index, raw_zone in enumerate(zones):
        zone_path = f"$.zones[{zone_index}]"
        zone = _mapping(raw_zone, zone_path)
        if "boundary" in zone:
            zone["boundary"] = canonicalize_polygon(
                zone["boundary"],
                f"{zone_path}.boundary",
            )
        for field in ("floorElevation", "heightLimit", "gridSpacing"):
            if field in zone:
                zone[field] = _rounded_number(
                    zone[field],
                    METER_DECIMAL_PLACES,
                    f"{zone_path}.{field}",
                )
        if isinstance(zone.get("edgeSetbacks"), MutableMapping):
            zone["edgeSetbacks"] = {
                key: _rounded_number(
                    value,
                    METER_DECIMAL_PLACES,
                    f"{zone_path}.edgeSetbacks.{key}",
                )
                for key, value in zone["edgeSetbacks"].items()
            }
        for anchor_index, raw_anchor in enumerate(zone.get("anchors", [])):
            anchor = _mapping(
                raw_anchor,
                f"{zone_path}.anchors[{anchor_index}]",
            )
            if "position" in anchor:
                _canonical_vector(
                    anchor["position"],
                    ("x", "y", "z"),
                    f"{zone_path}.anchors[{anchor_index}].position",
                )
            if "facing" in anchor:
                _canonical_vector(
                    anchor["facing"],
                    ("x", "y", "z"),
                    f"{zone_path}.anchors[{anchor_index}].facing",
                )
        extensions = zone.get("extensions")
        extensions = extensions if isinstance(extensions, MutableMapping) else {}
        cell_group = extensions.get("cellGroup")
        cell_group = (
            cell_group if isinstance(cell_group, MutableMapping) else {}
        )
        if "envelopePadding" in cell_group:
            cell_group["envelopePadding"] = _rounded_number(
                cell_group["envelopePadding"],
                METER_DECIMAL_PLACES,
                f"{zone_path}.extensions.cellGroup.envelopePadding",
            )
        interfaces = cell_group.get("functionalInterfaces")
        interfaces = (
            interfaces if isinstance(interfaces, MutableMapping) else {}
        )
        for role, raw_interface in interfaces.items():
            if not isinstance(raw_interface, MutableMapping):
                continue
            interface_path = (
                f"{zone_path}.extensions.cellGroup."
                f"functionalInterfaces.{role}"
            )
            for field in ("openingWidthMeters", "approachDepthMeters"):
                if field in raw_interface:
                    raw_interface[field] = _rounded_number(
                        raw_interface[field],
                        METER_DECIMAL_PLACES,
                        f"{interface_path}.{field}",
                    )
            if "position" in raw_interface:
                _canonical_vector(
                    raw_interface["position"],
                    ("x", "z"),
                    f"{interface_path}.position",
                )
            if "facing" in raw_interface:
                _canonical_vector(
                    raw_interface["facing"],
                    ("x", "z"),
                    f"{interface_path}.facing",
                )
            if "accessEnvelope" in raw_interface:
                raw_interface["accessEnvelope"] = canonicalize_polygon(
                    raw_interface["accessEnvelope"],
                    f"{interface_path}.accessEnvelope",
                )

    floor_markings = _sequence(
        result.get("floorMarkings", []),
        "$.floorMarkings",
    )
    for marking_index, raw_marking in enumerate(floor_markings):
        path = f"$.floorMarkings[{marking_index}]"
        marking = _mapping(raw_marking, path)
        transform = _mapping(marking.get("transform"), f"{path}.transform")
        if "position" in transform:
            _canonical_vector(
                transform["position"],
                ("x", "y", "z"),
                f"{path}.transform.position",
            )
        if "rotationDegrees" in transform:
            transform["rotationDegrees"] = _rounded_number(
                transform["rotationDegrees"],
                METER_DECIMAL_PLACES,
                f"{path}.transform.rotationDegrees",
            )
        for field in ("width", "depth", "opacity"):
            if field in marking:
                marking[field] = _rounded_number(
                    marking[field],
                    METER_DECIMAL_PLACES,
                    f"{path}.{field}",
                )

    placements = _sequence(result.get("placements"), "$.placements")
    for placement_index, raw_placement in enumerate(placements):
        path = f"$.placements[{placement_index}]"
        placement = _mapping(raw_placement, path)
        transform = _mapping(placement.get("transform"), f"{path}.transform")
        if "position" in transform:
            _canonical_vector(
                transform["position"],
                ("x", "y", "z"),
                f"{path}.transform.position",
            )
        if "quaternion" in transform:
            transform["quaternion"] = canonicalize_quaternion(
                transform["quaternion"],
                f"{path}.transform.quaternion",
            )

    routes = _sequence(result.get("routes"), "$.routes")
    for route_index, raw_route in enumerate(routes):
        path = f"$.routes[{route_index}]"
        route = _mapping(raw_route, path)
        for point_index, point in enumerate(route.get("centerline", [])):
            _canonical_vector(
                point,
                ("x", "y", "z"),
                f"{path}.centerline[{point_index}]",
            )
        if "corridorWidth" in route:
            route["corridorWidth"] = _rounded_number(
                route["corridorWidth"],
                METER_DECIMAL_PLACES,
                f"{path}.corridorWidth",
            )

    networks = _sequence(result.get("utilityNetworks"), "$.utilityNetworks")
    for network_index, raw_network in enumerate(networks):
        network_path = f"$.utilityNetworks[{network_index}]"
        network = _mapping(raw_network, network_path)
        for node_index, raw_node in enumerate(network.get("nodes", [])):
            node = _mapping(
                raw_node,
                f"{network_path}.nodes[{node_index}]",
            )
            if "position" in node:
                _canonical_vector(
                    node["position"],
                    ("x", "y", "z"),
                    f"{network_path}.nodes[{node_index}].position",
                )
        for segment_index, raw_segment in enumerate(network.get("segments", [])):
            segment_path = f"{network_path}.segments[{segment_index}]"
            segment = _mapping(raw_segment, segment_path)
            for point_index, point in enumerate(segment.get("centerline", [])):
                _canonical_vector(
                    point,
                    ("x", "y", "z"),
                    f"{segment_path}.centerline[{point_index}]",
                )

    root_extensions = result.get("extensions")
    if isinstance(root_extensions, MutableMapping) and "facilityNavigation" in root_extensions:
        from .navigation_contract import (
            canonicalize_facility_navigation_extension,
            navigation_identity_index,
        )

        root_extensions["facilityNavigation"] = (
            canonicalize_facility_navigation_extension(
                root_extensions["facilityNavigation"],
                navigation_identity_index(result),
            )
        )
    return result


def canonical_layout_bytes(layout: Mapping[str, Any]) -> bytes:
    canonical = canonicalize_layout(layout)
    from .validate import validate_layout

    validate_layout(canonical, require_canonical=True)
    return _canonical_value_bytes(canonical)


def trusted_canonical_layout_bytes(layout: Mapping[str, Any]) -> bytes:
    """Serialize a document already canonicalized by the operation kernel.

    This intentionally skips normalization and validation. It is only for
    immutable, prevalidated operation-plan execution where each preceding
    batch returned a canonical document.
    """

    return _canonical_value_bytes(layout)


def trusted_canonical_layout_revision(layout: Mapping[str, Any]) -> str:
    return hashlib.sha256(trusted_canonical_layout_bytes(layout)).hexdigest()


def layout_revision(layout: Mapping[str, Any] | bytes | bytearray) -> str:
    if isinstance(layout, (bytes, bytearray)):
        payload = bytes(layout)
    else:
        payload = canonical_layout_bytes(layout)
    return hashlib.sha256(payload).hexdigest()
