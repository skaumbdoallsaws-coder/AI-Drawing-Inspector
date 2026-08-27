"""Deterministic Gate G1 facility-envelope and department partition compiler."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re
from typing import Any, Mapping, Sequence

from .canonical import layout_revision
from .knowledge_foundation import (
    FacilityKnowledgeContractError,
    canonical_facility_knowledge_bytes,
    validate_department_partition_request,
    validate_facility_envelope_request,
)
from .plan_settings import MINIMUM_GRID_SPACING_METERS


G1_PARTITION_TOLERANCE = 1e-6
G1_COORDINATE_PRECISION_METERS = 1e-6
_ZONE_TYPES = frozenset(
    {
        "workcell",
        "storage",
        "staging",
        "receiving",
        "shipping",
        "inspection",
        "aisle",
        "dock",
        "charging",
        "safety",
        "exclusion",
        "utility",
        "service",
        "operator",
    }
)


def _stable_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()
    return f"{prefix}-{digest[:24]}"


def _grid_settings(width: float, depth: float, requested: float | None) -> tuple[float, float]:
    maximum = max(width, depth)
    if requested is None:
        grid = min(1.0, max(MINIMUM_GRID_SPACING_METERS, min(width, depth) / 20.0))
    else:
        grid = float(requested)
    if grid > maximum:
        raise FacilityKnowledgeContractError(
            "facility_grid_out_of_bounds",
            "Requested grid size is larger than the facility.",
        )
    multiple = max(1, min(5, int(math.floor(maximum / grid + 1e-12))))
    return grid, grid * multiple


def compile_g1_envelope_operations(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    replace_existing: bool = False,
) -> dict[str, Any]:
    envelope = validate_facility_envelope_request(request)
    grid, major = _grid_settings(
        envelope["widthMeters"],
        envelope["depthMeters"],
        envelope.get("gridSizeMeters"),
    )
    operations: list[dict[str, Any]] = []
    selected_command_ids: list[str] = []
    if replace_existing:
        operations.append({"op": "clear_layout_contents"})
        selected_command_ids.append("clear-all")
    operations.append(
        {
            "op": "set_plan_settings",
            "planSettings": {
                "widthMeters": envelope["widthMeters"],
                "depthMeters": envelope["depthMeters"],
                "gridSpacingMeters": grid,
                "majorGridSpacingMeters": major,
            },
        }
    )
    if str(layout.get("displayName") or "") != envelope["displayName"]:
        operations.append(
            {"op": "rename_layout", "displayName": envelope["displayName"]}
        )
    return {
        "stageId": "facility_envelope",
        "selectedCommandIds": selected_command_ids,
        "operations": operations,
        "plannedInstanceCount": 0,
        "normalizedRequest": envelope,
        "assumptions": [],
        "validationPlan": ["dimension_bounds", "unit_normalization", "plan_settings"],
        "expectedSummary": {
            "widthMeters": envelope["widthMeters"],
            "depthMeters": envelope["depthMeters"],
            "source": deepcopy(envelope["source"]),
            "replacedExistingContents": bool(replace_existing),
            "saved": False,
        },
    }


def default_g1_department_labels(count: int) -> list[str]:
    width = max(2, len(str(count)))
    return [f"Department {index + 1:0{width}d}" for index in range(count)]


def _chunks(count: int, width: int) -> list[tuple[int, int]]:
    result = []
    start = 0
    while start < count:
        end = min(count, start + width)
        result.append((start, end))
        start = end
    return result


def _horizontal_bands(
    width: float,
    depth: float,
    proportions: Sequence[float],
) -> list[tuple[float, float, float, float]]:
    result = []
    cursor = 0.0
    for index, proportion in enumerate(proportions):
        next_cursor = depth if index == len(proportions) - 1 else cursor + depth * proportion
        result.append((0.0, cursor, width, next_cursor))
        cursor = next_cursor
    return result


def _vertical_columns(
    width: float,
    depth: float,
    proportions: Sequence[float],
) -> list[tuple[float, float, float, float]]:
    result = []
    cursor = 0.0
    for index, proportion in enumerate(proportions):
        next_cursor = width if index == len(proportions) - 1 else cursor + width * proportion
        result.append((cursor, 0.0, next_cursor, depth))
        cursor = next_cursor
    return result


def _deterministic_grid(
    width: float,
    depth: float,
    proportions: Sequence[float],
    orientation: str,
) -> list[tuple[float, float, float, float]]:
    count = len(proportions)
    aspect = max(0.1, min(10.0, width / depth))
    columns = max(1, min(count, int(math.ceil(math.sqrt(count * aspect)))))
    if orientation == "vertical":
        columns = max(1, int(math.ceil(count / max(1, columns))))
    result: list[tuple[float, float, float, float]] = []
    z_cursor = 0.0
    ranges = _chunks(count, columns)
    for row_index, (start, end) in enumerate(ranges):
        row_share = sum(proportions[start:end])
        next_z = depth if row_index == len(ranges) - 1 else z_cursor + depth * row_share
        x_cursor = 0.0
        for index in range(start, end):
            local_share = proportions[index] / row_share
            next_x = width if index == end - 1 else x_cursor + width * local_share
            result.append((x_cursor, z_cursor, next_x, next_z))
            x_cursor = next_x
        z_cursor = next_z
    return result


def g1_department_semantic_type(label: str) -> tuple[str, str]:
    normalized = re.sub(
        r"[^a-z0-9]+",
        "_",
        label.casefold(),
    ).strip("_")
    aliases = {
        "receiving": "receiving",
        "shipping": "shipping",
        "inspection": "inspection",
        "quality": "inspection",
        "storage": "storage",
        "staging": "staging",
        "dock": "dock",
        "charging": "charging",
        "utilities": "utility",
        "utility": "utility",
        "service": "service",
        "maintenance": "service",
    }
    for token, zone_type in aliases.items():
        if token in normalized:
            return zone_type, normalized
    return "workcell", normalized or "department"


def compile_g1_department_operations(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    partition = validate_department_partition_request(request)
    extensions = layout.get("extensions")
    plan = extensions.get("facilityPlan") if isinstance(extensions, Mapping) else None
    if not isinstance(plan, Mapping):
        raise FacilityKnowledgeContractError(
            "facility_envelope_required",
            "Macro departments require a validated facility envelope.",
        )
    width = float(plan["widthMeters"])
    depth = float(plan["depthMeters"])
    labels = partition["labels"] or default_g1_department_labels(
        partition["count"]
    )
    arrangement = partition["arrangement"]
    if arrangement == "rows":
        rectangles = _horizontal_bands(width, depth, partition["proportions"])
    elif arrangement == "columns":
        rectangles = _vertical_columns(width, depth, partition["proportions"])
    else:
        rectangles = _deterministic_grid(
            width,
            depth,
            partition["proportions"],
            partition["orientation"],
        )
    if len(rectangles) != partition["count"]:
        raise AssertionError("department partition did not produce the requested count")
    operations = []
    zone_ids = []
    for index, (label, rectangle) in enumerate(zip(labels, rectangles, strict=True)):
        minimum_x, minimum_z, maximum_x, maximum_z = rectangle
        zone_type, semantic_type = g1_department_semantic_type(label)
        if zone_type not in _ZONE_TYPES:
            zone_type = "workcell"
        zone_id = _stable_id(
            "zn-g1",
            {"layoutId": layout.get("layoutId"), "index": index, "label": label},
        )
        zone_ids.append(zone_id)
        operations.append(
            {
                "op": "add_zone",
                "zone": {
                    "zoneId": zone_id,
                    "zoneType": zone_type,
                    "label": label,
                    "boundary": [
                        {"x": minimum_x, "z": minimum_z},
                        {"x": maximum_x, "z": minimum_z},
                        {"x": maximum_x, "z": maximum_z},
                        {"x": minimum_x, "z": maximum_z},
                    ],
                    "floorElevation": 0.0,
                    "anchors": [],
                    "evidence": [],
                    "extensions": {
                        "knowledgeFoundation": {
                            "semanticType": semantic_type,
                            "semanticTypeEvidenceStatus": "derived",
                            "partitionAssumptions": list(partition["assumptions"]),
                        }
                    },
                },
            }
        )
    return {
        "stageId": "macro_departments",
        "selectedCommandIds": ["bulk-zones"],
        "operations": operations,
        "plannedInstanceCount": partition["count"],
        "normalizedRequest": partition,
        "assumptions": list(partition["assumptions"]),
        "validationPlan": [
            "department_count",
            "label_identity",
            "facility_containment",
            "zero_overlap",
            "area_proportions",
        ],
        "expectedSummary": {
            "departmentCount": partition["count"],
            "labels": labels,
            "zoneIds": zone_ids,
            "proportions": list(partition["proportions"]),
            "inventedCorridor": False,
            "inventedSafetySeparation": False,
            "inventedExpansionReserve": False,
            "saved": False,
        },
    }


def _rectangle(zone: Mapping[str, Any]) -> tuple[float, float, float, float]:
    points = zone.get("boundary")
    if not isinstance(points, list) or len(points) != 4:
        raise FacilityKnowledgeContractError(
            "g1_department_geometry_invalid",
            "G1 department validation requires four-corner deterministic polygons.",
        )
    xs = [float(point["x"]) for point in points]
    zs = [float(point["z"]) for point in points]
    return min(xs), min(zs), max(xs), max(zs)


def validate_g1_department_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    expected_ids = list(expected["zoneIds"])
    zones_by_id = {
        str(item.get("zoneId")): item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping)
    }
    missing = [item for item in expected_ids if item not in zones_by_id]
    if missing:
        raise FacilityKnowledgeContractError(
            "g1_department_result_missing",
            "The draft is missing expected G1 departments.",
            details={"missingZoneIds": missing},
        )
    zones = [zones_by_id[item] for item in expected_ids]
    unexpected = sorted(set(zones_by_id) - set(expected_ids))
    labels = [str(item.get("label")) for item in zones]
    rectangles = [_rectangle(item) for item in zones]
    plan = layout["extensions"]["facilityPlan"]
    width = float(plan["widthMeters"])
    depth = float(plan["depthMeters"])
    overlaps = []
    for left in range(len(rectangles)):
        for right in range(left + 1, len(rectangles)):
            a = rectangles[left]
            b = rectangles[right]
            overlap_width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
            overlap_depth = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
            if overlap_width * overlap_depth > G1_PARTITION_TOLERANCE:
                overlaps.append((expected_ids[left], expected_ids[right]))
    areas = [(item[2] - item[0]) * (item[3] - item[1]) for item in rectangles]
    total_area = width * depth
    area_tolerance = max(
        G1_PARTITION_TOLERANCE,
        total_area * 1e-8,
        (width + depth) * G1_COORDINATE_PRECISION_METERS * 2.0,
    )
    shares = [area / total_area for area in areas]
    expected_shares = list(expected["proportions"])
    share_errors = [abs(actual - planned) for actual, planned in zip(shares, expected_shares, strict=True)]
    contained = all(
        minimum_x >= -G1_PARTITION_TOLERANCE
        and minimum_z >= -G1_PARTITION_TOLERANCE
        and maximum_x <= width + G1_PARTITION_TOLERANCE
        and maximum_z <= depth + G1_PARTITION_TOLERANCE
        for minimum_x, minimum_z, maximum_x, maximum_z in rectangles
    )
    valid = (
        labels == list(expected["labels"])
        and not unexpected
        and not overlaps
        and contained
        and max(share_errors, default=0.0) <= G1_PARTITION_TOLERANCE
        and abs(sum(areas) - total_area) <= area_tolerance
    )
    return {
        "status": "valid" if valid else "invalid",
        "layoutRevision": layout_revision(layout),
        "departmentCount": len(zones),
        "labels": labels,
        "unexpectedZoneIds": unexpected,
        "contained": contained,
        "overlaps": overlaps,
        "areaShares": shares,
        "expectedAreaShares": expected_shares,
        "maximumShareError": max(share_errors, default=0.0),
        "coversFacilityArea": abs(sum(areas) - total_area) <= area_tolerance,
        "facilityAreaError": abs(sum(areas) - total_area),
        "facilityAreaTolerance": area_tolerance,
    }


__all__ = [
    "G1_PARTITION_TOLERANCE",
    "G1_COORDINATE_PRECISION_METERS",
    "compile_g1_department_operations",
    "compile_g1_envelope_operations",
    "default_g1_department_labels",
    "g1_department_semantic_type",
    "validate_g1_department_result",
]
