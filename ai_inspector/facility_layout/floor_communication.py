"""Coordinate-free floor-communication templates for FacilityProgram."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from typing import Any, Mapping

from .knowledge_foundation import canonical_facility_knowledge_bytes


FLOOR_COMMUNICATION_PATTERN_VERSION = "facility-floor-communication-v1"
FLOOR_COMMUNICATION_MARKING_TYPES = frozenset(
    {"direction_arrow", "keep_clear", "parking_box", "pedestrian_lane", "restricted_zone"}
)
_MARKING_DOCUMENT_SEMANTICS = {
    "direction_arrow": ("direction_arrow", "material_flow"),
    "keep_clear": ("keep_clear", "keep_clear"),
    "parking_box": ("parking_box", "parking"),
    "pedestrian_lane": ("solid_line", "pedestrian_lane"),
    "restricted_zone": ("hazard_stripe", "safety"),
}
_UNIT_SCALE = {"m": 1.0, "mm": 0.001, "ft": 0.3048, "in": 0.0254}


class FacilityFloorCommunicationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _meters(value: Any, unit: str, field: str) -> float:
    if unit not in _UNIT_SCALE:
        raise FacilityFloorCommunicationError(
            "floor_communication_unit_invalid", f"{field} has an unsupported unit."
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise FacilityFloorCommunicationError(
            "floor_communication_dimension_invalid", f"{field} must be positive."
        )
    return float(value) * _UNIT_SCALE[unit]


def _rectangle(zone: Mapping[str, Any]) -> tuple[float, float, float, float]:
    points = [
        (float(item["x"]), float(item["z"]))
        for item in zone.get("boundary", [])
        if isinstance(item, Mapping)
    ]
    xs = sorted({round(item[0], 9) for item in points})
    zs = sorted({round(item[1], 9) for item in points})
    if len(points) != 4 or len(xs) != 2 or len(zs) != 2:
        raise FacilityFloorCommunicationError(
            "floor_communication_anchor_unsupported",
            "Area-anchored marking arrays require a rectangular area.",
        )
    return xs[0], zs[0], xs[1], zs[1]


def _unique_by_label(layout: Mapping[str, Any], collection: str, label: str) -> Mapping[str, Any]:
    matches = [
        item
        for item in layout.get(collection, [])
        if isinstance(item, Mapping)
        and str(item.get("label") or "").strip().casefold() == label.strip().casefold()
    ]
    if len(matches) != 1:
        raise FacilityFloorCommunicationError(
            "floor_communication_anchor_unresolved",
            "The marking anchor must resolve to one exact entity.",
            details={"collection": collection, "label": label, "matchCount": len(matches)},
        )
    return matches[0]


def _route_midpoint(route: Mapping[str, Any]) -> tuple[float, float, int]:
    points = [
        (float(item["x"]), float(item["z"]))
        for item in route.get("centerline", [])
        if isinstance(item, Mapping)
    ]
    if len(points) < 2:
        raise FacilityFloorCommunicationError(
            "floor_communication_route_geometry_unavailable",
            "The route anchor has no bounded centerline.",
        )
    segments = []
    total = 0.0
    for left, right in zip(points, points[1:]):
        length = math.hypot(right[0] - left[0], right[1] - left[1])
        segments.append((left, right, length))
        total += length
    target = total / 2.0
    travelled = 0.0
    for left, right, length in segments:
        if travelled + length >= target:
            ratio = 0.0 if length == 0 else (target - travelled) / length
            x = left[0] + (right[0] - left[0]) * ratio
            z = left[1] + (right[1] - left[1]) * ratio
            angle = round(math.degrees(math.atan2(right[1] - left[1], right[0] - left[0])))
            return x, z, angle
        travelled += length
    left, right, _length = segments[-1]
    return right[0], right[1], round(math.degrees(math.atan2(right[1] - left[1], right[0] - left[0])))


def _anchor_frame(
    layout: Mapping[str, Any], anchor: Mapping[str, Any]
) -> tuple[float, float, int, tuple[float, float, float, float] | None, str]:
    kind = str(anchor.get("kind") or "")
    if kind == "area":
        label = str(anchor.get("target_area") or "")
        zone = _unique_by_label(layout, "zones", label)
        bounds = _rectangle(zone)
        low_x, low_z, high_x, high_z = bounds
        return (
            (low_x + high_x) / 2.0,
            (low_z + high_z) / 2.0,
            0,
            bounds,
            str(zone.get("zoneId") or ""),
        )
    if kind == "route":
        route = _unique_by_label(layout, "routes", str(anchor.get("route_label") or ""))
        x, z, angle = _route_midpoint(route)
        return x, z, angle, None, str(route.get("routeId") or "")
    if kind == "asset":
        placement_id = str(anchor.get("placement_id") or "")
        matches = [
            item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId") == placement_id
        ]
        if len(matches) != 1:
            raise FacilityFloorCommunicationError(
                "floor_communication_anchor_unresolved",
                "The asset marking anchor must resolve to one exact placement.",
            )
        position = (matches[0].get("transform") or {}).get("position") or {}
        return (
            float(position.get("x") or 0.0),
            float(position.get("z") or 0.0),
            0,
            None,
            placement_id,
        )
    raise FacilityFloorCommunicationError(
        "floor_communication_anchor_invalid",
        "Marking arrays require an area, route, or exact asset anchor.",
    )


def compile_marking_array(
    layout: Mapping[str, Any], specification: Mapping[str, Any]
) -> dict[str, Any]:
    """Compile exact-count markings from relational anchors and authored dimensions."""

    marking_type = str(specification.get("marking_type") or "")
    if marking_type not in FLOOR_COMMUNICATION_MARKING_TYPES:
        raise FacilityFloorCommunicationError(
            "floor_communication_type_invalid", "The floor-marking type is unsupported."
        )
    evidence_refs = specification.get("dimension_evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs or any(
        not isinstance(item, str) or not item.strip() for item in evidence_refs
    ):
        raise FacilityFloorCommunicationError(
            "floor_communication_dimension_authority_missing",
            "Every marking dimension requires user or policy evidence.",
        )
    count = specification.get("count")
    rows = specification.get("rows")
    columns = specification.get("columns")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= 500
        or isinstance(rows, bool)
        or not isinstance(rows, int)
        or rows < 1
        or isinstance(columns, bool)
        or not isinstance(columns, int)
        or columns < 1
        or rows * columns != count
    ):
        raise FacilityFloorCommunicationError(
            "floor_communication_array_shape_invalid",
            "Marking rows multiplied by columns must equal the exact requested count.",
        )
    unit = str(specification.get("source_unit") or "")
    width = _meters(specification.get("width"), unit, "width")
    depth = _meters(specification.get("depth"), unit, "depth")
    pitch = specification.get("pitch")
    if not isinstance(pitch, Mapping):
        raise FacilityFloorCommunicationError(
            "floor_communication_pitch_invalid", "Marking arrays require authored pitch."
        )
    along = _meters(pitch.get("along"), unit, "pitch.along")
    across = _meters(pitch.get("across"), unit, "pitch.across")
    if (columns > 1 and along < width) or (rows > 1 and across < depth):
        raise FacilityFloorCommunicationError(
            "floor_communication_pitch_invalid",
            "Marking pitch cannot be smaller than the marking dimensions.",
        )
    orientation = str(specification.get("semantic_orientation") or "")
    if orientation not in {"east_west", "north_south", "route_aligned"}:
        raise FacilityFloorCommunicationError(
            "floor_communication_orientation_invalid",
            "Marking array orientation is unsupported.",
        )
    anchor = specification.get("anchor_relationship")
    if not isinstance(anchor, Mapping):
        raise FacilityFloorCommunicationError(
            "floor_communication_anchor_invalid", "A relational marking anchor is required."
        )
    center_x, center_z, route_angle, bounds, anchor_id = _anchor_frame(layout, anchor)
    rotation = route_angle if orientation == "route_aligned" else (0 if orientation == "east_west" else 90)
    if orientation == "north_south":
        along_x, along_z = 0.0, along
        across_x, across_z = across, 0.0
    elif orientation == "route_aligned":
        radians = math.radians(route_angle)
        along_x, along_z = math.cos(radians) * along, math.sin(radians) * along
        across_x, across_z = -math.sin(radians) * across, math.cos(radians) * across
    else:
        along_x, along_z = along, 0.0
        across_x, across_z = 0.0, across
    origin_x = center_x - (columns - 1) * along_x / 2.0 - (rows - 1) * across_x / 2.0
    origin_z = center_z - (columns - 1) * along_z / 2.0 - (rows - 1) * across_z / 2.0
    communication_id = str(specification.get("communication_id") or "")
    operations = []
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column + 1
            x = origin_x + column * along_x + row * across_x
            z = origin_z + column * along_z + row * across_z
            if bounds is not None:
                low_x, low_z, high_x, high_z = bounds
                if not (
                    low_x - 1.0e-9 <= x - width / 2
                    and x + width / 2 <= high_x + 1.0e-9
                    and low_z - 1.0e-9 <= z - depth / 2
                    and z + depth / 2 <= high_z + 1.0e-9
                ):
                    raise FacilityFloorCommunicationError(
                        "floor_communication_array_unplaceable",
                        "The exact marking array does not fit its authored anchor area.",
                    )
            marking_id = _stable_id(
                "fm-rq-array",
                {"communicationId": communication_id, "index": index, "anchorId": anchor_id},
            )
            operations.append(
                {
                    "op": "add_floor_marking",
                    "floorMarking": {
                        "markingId": marking_id,
                        "markingType": _MARKING_DOCUMENT_SEMANTICS[marking_type][0],
                        "semanticRole": _MARKING_DOCUMENT_SEMANTICS[marking_type][1],
                        "label": str(specification.get("label") or marking_type.replace("_", " ").title()),
                        "text": "",
                        "width": width,
                        "depth": depth,
                        "transform": {
                            "position": {"x": round(x, 9), "y": 0.0, "z": round(z, 9)},
                            "rotationDegrees": rotation,
                        },
                        "positionMode": "auto",
                        "fillColor": "#ffffff",
                        "strokeColor": "#1f2937",
                        "opacity": 1.0,
                        "evidence": [],
                        "metadata": {
                            "generatedBy": "facility_floor_communication_rq5",
                            "patternVersion": FLOOR_COMMUNICATION_PATTERN_VERSION,
                            "communicationId": communication_id,
                            "communicationKind": marking_type,
                            "arrayIndex": index,
                            "anchorKind": anchor.get("kind"),
                            "anchorId": anchor_id,
                            "positionAuthority": "derived_from_relational_anchor",
                            "dimensionAuthority": "user_or_policy_authored",
                            "dimensionEvidenceRefs": list(evidence_refs),
                        },
                    },
                }
            )
    return {
        "schemaVersion": FLOOR_COMMUNICATION_PATTERN_VERSION,
        "communicationId": communication_id,
        "markingType": marking_type,
        "requestedCount": count,
        "generatedCount": len(operations),
        "operations": operations,
        "anchorId": anchor_id,
        "claimBoundary": (
            "These markings communicate authored floor intent only; they do not establish "
            "regulatory compliance, safety, capacity, or operational adequacy."
        ),
    }


__all__ = [
    "FLOOR_COMMUNICATION_MARKING_TYPES",
    "FLOOR_COMMUNICATION_PATTERN_VERSION",
    "FacilityFloorCommunicationError",
    "compile_marking_array",
]
