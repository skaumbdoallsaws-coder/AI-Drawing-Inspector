"""Deterministic Gate G3 department-subdivision intent and geometry."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re
from typing import Any, Mapping, Sequence

from .canonical import layout_revision
from .chat_intent import (
    _parse_bounded_count,
    _parse_department_labels,
    _parse_department_proportions,
    _parse_department_rows,
)
from .g1_planner import (
    G1_COORDINATE_PRECISION_METERS,
    G1_PARTITION_TOLERANCE,
    G1_ZONE_TYPES,
    compile_partition_rectangles,
    g1_department_semantic_type,
)
from .knowledge_foundation import (
    FacilityKnowledgeContractError,
    canonical_facility_knowledge_bytes,
    validate_department_partition_request,
)
from .operations import apply_facility_layout_operations


G3_SUBDIVISION_SCOPE = "department_subdivisions"
G3_FACILITY_SUBDIVISION_TOOL = "generate_facility_subdivision_draft"
_PRESERVED_COLLECTIONS = (
    "routes",
    "floorMarkings",
    "placements",
    "utilityNetworks",
    "processBindings",
    "groups",
)
_ACTION = re.compile(
    r"\b(?:divide|subdivide|split|partition)\b",
    re.IGNORECASE,
)
_TARGET = re.compile(
    r"\b(?:child\s+areas?|subzones?|sub-zones?|work\s+areas?|"
    r"sections?|areas?|zones?)\b",
    re.IGNORECASE,
)
_COUNT = re.compile(
    r"\b(?:into|in)\s+(?P<count>\d{1,2}|one|two|three|four|five|six|"
    r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty)\s+"
    r"(?:(?:equal(?:[-\s]+(?:sized|area))?|equally[-\s]+sized)\s+)?"
    r"(?:child\s+areas?|subzones?|sub-zones?|work\s+areas?|sections?|"
    r"areas?|zones?)\b",
    re.IGNORECASE,
)
_LABELS = re.compile(
    r"\b(?:named|called|labelled|labeled)\s+(?P<labels>[^.!?]+)",
    re.IGNORECASE,
)
_COORDINATE = re.compile(
    r"(?:\b(?:x|z)\s*=\s*-?\d|\bcoordinates?\b|\bworld\s+point\b)",
    re.IGNORECASE,
)


class FacilitySubdivisionError(FacilityKnowledgeContractError):
    """A G3 subdivision request is ambiguous or invalid."""


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _rectangle(
    zone: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    points = zone.get("boundary")
    if not isinstance(points, list) or len(points) != 4:
        raise FacilitySubdivisionError(
            "facility_subdivision_parent_not_rectangular",
            "G3 currently requires a four-corner rectangular parent area.",
        )
    coordinates = [(float(point["x"]), float(point["z"])) for point in points]
    xs = [item[0] for item in coordinates]
    zs = [item[1] for item in coordinates]
    rectangle = (min(xs), min(zs), max(xs), max(zs))
    expected = {
        (rectangle[0], rectangle[1]),
        (rectangle[2], rectangle[1]),
        (rectangle[2], rectangle[3]),
        (rectangle[0], rectangle[3]),
    }
    if set(coordinates) != expected or (
        rectangle[2] - rectangle[0] <= G1_PARTITION_TOLERANCE
        or rectangle[3] - rectangle[1] <= G1_PARTITION_TOLERANCE
    ):
        raise FacilitySubdivisionError(
            "facility_subdivision_parent_not_rectangular",
            "G3 currently requires an axis-aligned rectangular parent area.",
        )
    return rectangle


def _zone_parent_id(zone: Mapping[str, Any]) -> str | None:
    extensions = zone.get("extensions")
    knowledge = (
        extensions.get("knowledgeFoundation")
        if isinstance(extensions, Mapping)
        else None
    )
    if not isinstance(knowledge, Mapping):
        return None
    value = str(knowledge.get("parentZoneId") or "").strip()
    return value or None


def _resolve_parent(
    layout: Mapping[str, Any], parent_label: str
) -> Mapping[str, Any]:
    key = re.sub(r"\s+", " ", parent_label.strip()).casefold()
    matches = [
        zone
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping)
        and re.sub(r"\s+", " ", str(zone.get("label") or "").strip()).casefold()
        == key
    ]
    if not matches:
        available = [
            str(zone.get("label") or "")
            for zone in layout.get("zones", [])
            if isinstance(zone, Mapping) and zone.get("label")
        ]
        raise FacilitySubdivisionError(
            "facility_subdivision_parent_not_found",
            f"No active department or subzone is labelled '{parent_label}'.",
            details={"availableLabels": available[:50]},
        )
    if len(matches) != 1:
        raise FacilitySubdivisionError(
            "facility_subdivision_parent_ambiguous",
            f"More than one active zone is labelled '{parent_label}'.",
            details={
                "matchingZoneIds": [str(item.get("zoneId")) for item in matches]
            },
        )
    _rectangle(matches[0])
    return matches[0]


def _closed_request(request: Mapping[str, Any]) -> None:
    allowed = {
        "parent_department",
        "count",
        "labels",
        "zone_types",
        "zone_type_evidence_status",
        "proportions",
        "arrangement",
        "orientation",
        "rows",
        "preserve_parent",
        "execution_mode",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise FacilitySubdivisionError(
            "facility_subdivision_model_geometry_refused",
            "Subdivision accepts semantic intent fields only.",
            details={"fields": unknown},
        )


def normalize_subdivision_request(
    request: Mapping[str, Any],
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise FacilitySubdivisionError(
            "facility_subdivision_request_invalid",
            "Subdivision intent must be an object.",
        )
    _closed_request(request)
    if request.get("preserve_parent") is not True:
        raise FacilitySubdivisionError(
            "facility_subdivision_parent_preservation_required",
            "G3 requires the parent department to remain unchanged.",
        )
    if str(request.get("execution_mode") or "") != "authorized_draft_run":
        raise FacilitySubdivisionError(
            "facility_subdivision_execution_mode_invalid",
            "Subdivision requires authorized_draft_run mode.",
        )
    parent_label = str(request.get("parent_department") or "").strip()
    if not parent_label:
        raise FacilitySubdivisionError(
            "facility_subdivision_parent_required",
            "Name the department or subzone to divide.",
        )
    parent = _resolve_parent(layout, parent_label)
    raw_proportions = request.get("proportions")
    if raw_proportions is not None:
        if not isinstance(raw_proportions, list):
            raise FacilitySubdivisionError(
                "facility_subdivision_proportions_invalid",
                "Subdivision proportions must be a complete array.",
            )
        try:
            total = sum(float(item) for item in raw_proportions)
        except (TypeError, ValueError):
            total = -1.0
        if not (
            math.isclose(total, 1.0, abs_tol=1e-9)
            or math.isclose(total, 100.0, abs_tol=1e-6)
        ):
            raise FacilitySubdivisionError(
                "facility_subdivision_proportions_incomplete",
                "Authored child-area proportions must total 100 percent.",
                details={"total": total},
            )
    try:
        partition = validate_department_partition_request(
            {
                "count": request.get("count"),
                "labels": request.get("labels"),
                "proportions": raw_proportions,
                "arrangement": request.get("arrangement"),
                "orientation": request.get("orientation"),
                "rows": request.get("rows"),
            }
        )
    except FacilityKnowledgeContractError as exc:
        raise FacilitySubdivisionError(
            exc.code, str(exc), details=exc.details
        ) from exc
    labels = list(partition["labels"])
    if not labels:
        raise FacilitySubdivisionError(
            "facility_subdivision_labels_required",
            "G3 requires explicit labels for every child area.",
        )
    keys = [item.casefold() for item in labels]
    if len(keys) != len(set(keys)):
        raise FacilitySubdivisionError(
            "facility_subdivision_child_labels_duplicate",
            "Child-area labels must be unique within their parent.",
        )
    if str(parent.get("label") or "").casefold() in set(keys):
        raise FacilitySubdivisionError(
            "facility_subdivision_child_matches_parent",
            "A child area cannot reuse its parent department label.",
        )
    raw_zone_types = request.get("zone_types")
    if raw_zone_types is None:
        zone_types = [g1_department_semantic_type(label)[0] for label in labels]
        zone_type_evidence_status = "derived"
    else:
        if not isinstance(raw_zone_types, list) or len(raw_zone_types) != len(labels):
            raise FacilitySubdivisionError(
                "facility_subdivision_zone_types_invalid",
                "Child-area zone types must align one-for-one with child labels.",
            )
        zone_types = [str(item or "").strip() for item in raw_zone_types]
        if any(item not in G1_ZONE_TYPES for item in zone_types):
            raise FacilitySubdivisionError(
                "facility_subdivision_zone_types_invalid",
                "Child-area zone types must use the Facility Layout vocabulary.",
            )
        zone_type_evidence_status = str(
            request.get("zone_type_evidence_status") or "unknown"
        )
        if zone_type_evidence_status not in {"authored", "derived", "inferred", "unknown"}:
            raise FacilitySubdivisionError(
                "facility_subdivision_zone_type_authority_invalid",
                "Child-area zone-type evidence status is invalid.",
            )
    return {
        "scope": G3_SUBDIVISION_SCOPE,
        "parentDepartment": str(parent.get("label") or ""),
        "parentZoneId": str(parent.get("zoneId") or ""),
        "count": partition["count"],
        "labels": labels,
        "zoneTypes": zone_types,
        "zoneTypeEvidenceStatus": zone_type_evidence_status,
        "proportions": list(partition["proportions"]),
        "arrangement": partition["arrangement"],
        "orientation": partition["orientation"],
        "rows": deepcopy(partition["rows"]),
        "rowOrder": partition["rowOrder"],
        "areaSizing": partition["areaSizing"],
        "assumptions": list(partition["assumptions"]),
        "preserveParent": True,
        "executionMode": "authorized_draft_run",
    }


def subdivision_tool_spec() -> dict[str, Any]:
    nullable_number_array = {
        "type": ["array", "null"],
        "items": {"type": "number", "exclusiveMinimum": 0},
        "maxItems": 50,
    }
    nullable_rows = {
        "type": ["array", "null"],
        "items": {
            "type": "object",
            "properties": {
                "labels": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "proportion": {"type": ["number", "null"]},
            },
            "required": ["labels", "proportion"],
            "additionalProperties": False,
        },
        "maxItems": 50,
    }
    return {
        "name": G3_FACILITY_SUBDIVISION_TOOL,
        "description": (
            "Divide one named department or subzone into explicitly named child "
            "areas in the active unsaved Facility generation run. Supply semantic "
            "membership, proportions, rows, and orientation only. InspectorPro "
            "owns coordinates, preserves the parent and unrelated layout entities, "
            "validates exact containment and coverage, and waits for Save."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_department": {"type": "string", "minLength": 1},
                "count": {"type": "integer", "minimum": 1, "maximum": 50},
                "labels": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "proportions": nullable_number_array,
                "arrangement": {
                    "type": "string",
                    "enum": ["deterministic_grid", "rows", "columns", "row_stack"],
                },
                "orientation": {
                    "type": "string",
                    "enum": ["auto", "horizontal", "vertical"],
                },
                "rows": nullable_rows,
                "preserve_parent": {"type": "boolean", "const": True},
                "execution_mode": {
                    "type": "string",
                    "const": "authorized_draft_run",
                },
            },
            "required": [
                "parent_department",
                "count",
                "labels",
                "proportions",
                "arrangement",
                "orientation",
                "rows",
                "preserve_parent",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


def parse_subdivision_turn(
    message: str,
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(message or "").strip())
    if not _ACTION.search(text) or not _TARGET.search(text):
        return {"kind": "not_applicable"}
    if _COORDINATE.search(text):
        return {
            "kind": "refuse",
            "code": "facility_subdivision_coordinate_ownership",
            "response": (
                "**I cannot accept authored subdivision coordinates from chat.** "
                "Name the parent area, child labels, proportions, and row arrangement; "
                "InspectorPro will compute the boundaries deterministically."
            ),
        }
    count_match = _COUNT.search(text)
    labels_match = _LABELS.search(text)
    if count_match is None or labels_match is None:
        return {
            "kind": "ask",
            "code": "facility_subdivision_intent_incomplete",
            "response": (
                "**I need the parent department, child-area count, and every child "
                "label before I can divide it.** You may also specify rows or complete "
                "area percentages."
            ),
        }
    count = _parse_bounded_count(count_match.group("count"))
    if count is None:
        return {
            "kind": "ask",
            "code": "facility_subdivision_count_invalid",
            "response": "**Give a child-area count from 1 through 50.**",
        }
    action = _ACTION.search(text)
    parent = text[action.end():count_match.start()] if action is not None else ""
    parent = re.sub(r"\b(?:into|in)\s*$", "", parent, flags=re.IGNORECASE)
    parent = re.sub(
        r"^\s*(?:the\s+)?|\s+(?:department|zone|area)\s*$",
        "",
        parent,
        flags=re.IGNORECASE,
    ).strip(" ,;:")
    labels = _parse_department_labels(labels_match.group("labels"), count)
    if labels is None and count == 2:
        raw_pair = labels_match.group("labels").strip().strip(" .")
        pair = [
            item.strip().strip("\"'")
            for item in re.split(r"\s+and\s+", raw_pair, maxsplit=1, flags=re.IGNORECASE)
        ]
        if len(pair) == 2 and all(pair):
            labels = pair
    if not parent or labels is None:
        return {
            "kind": "ask",
            "code": "facility_subdivision_label_count_mismatch",
            "response": (
                f"**I need exactly {count} distinct child labels and one named parent "
                "department.** Nothing changed."
            ),
        }
    rows, row_cue = _parse_department_rows(text, labels)
    proportions, area_cue = _parse_department_proportions(text, labels)
    if row_cue and rows is None:
        return {
            "kind": "ask",
            "code": "facility_subdivision_rows_ambiguous",
            "response": (
                "**I could not resolve every child area to exactly one requested row.** "
                "List each row and its child labels."
            ),
        }
    authored_row_proportions = bool(
        rows and all(row.get("proportion") is not None for row in rows)
    )
    if area_cue and proportions is None and not authored_row_proportions:
        return {
            "kind": "ask",
            "code": "facility_subdivision_proportions_incomplete",
            "response": (
                "**The child-area proportions are incomplete or do not total 100 "
                "percent.** Provide every share or ask for equal areas."
            ),
        }
    request = {
        "parent_department": parent,
        "count": count,
        "labels": labels,
        "proportions": proportions,
        "arrangement": "row_stack" if rows is not None else "deterministic_grid",
        "orientation": "auto",
        "rows": rows,
        "preserve_parent": True,
        "execution_mode": "authorized_draft_run",
    }
    lowered = text.casefold()
    if rows is None and re.search(r"\b(?:single\s+)?row\b", lowered):
        request["arrangement"] = "rows"
    elif rows is None and re.search(r"\b(?:single\s+)?column\b", lowered):
        request["arrangement"] = "columns"
    if re.search(r"\b(?:horizontal|horizontally)\b", lowered):
        request["orientation"] = "horizontal"
    elif re.search(r"\b(?:vertical|vertically)\b", lowered):
        request["orientation"] = "vertical"
    try:
        normalized = normalize_subdivision_request(request, layout)
    except FacilitySubdivisionError as exc:
        kind = (
            "refuse"
            if exc.code in {
                "facility_subdivision_parent_not_rectangular",
                "facility_subdivision_model_geometry_refused",
            }
            else "ask"
        )
        return {
            "kind": kind,
            "code": exc.code,
            "response": f"**I could not prepare that subdivision.** {exc} Nothing changed.",
        }
    return {"kind": "build", "request": normalized}


def _compile_one(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = normalize_subdivision_request(
        {
            "parent_department": request.get("parentDepartment")
            or request.get("parent_department"),
            "count": request.get("count"),
            "labels": request.get("labels"),
            "zone_types": request.get("zoneTypes") or request.get("zone_types"),
            "zone_type_evidence_status": request.get("zoneTypeEvidenceStatus")
            or request.get("zone_type_evidence_status"),
            "proportions": request.get("proportions"),
            "arrangement": request.get("arrangement"),
            "orientation": request.get("orientation"),
            "rows": request.get("rows"),
            "preserve_parent": True,
            "execution_mode": "authorized_draft_run",
        },
        layout,
    )
    parent = _resolve_parent(layout, normalized["parentDepartment"])
    parent_bounds = _rectangle(parent)
    minimum_x, minimum_z, maximum_x, maximum_z = parent_bounds
    width = maximum_x - minimum_x
    depth = maximum_z - minimum_z
    rectangles, row_metadata = compile_partition_rectangles(
        width,
        depth,
        normalized,
        normalized["labels"],
    )
    operations: list[dict[str, Any]] = []
    child_ids: list[str] = []
    bounds_by_id: dict[str, list[float]] = {}
    for index, (label, local) in enumerate(
        zip(normalized["labels"], rectangles, strict=True)
    ):
        child_bounds = (
            minimum_x + local[0],
            minimum_z + local[1],
            minimum_x + local[2],
            minimum_z + local[3],
        )
        label_key = re.sub(r"\s+", " ", label.strip()).casefold()
        child_id = _stable_id(
            "zn-g3",
            {
                "layoutId": layout.get("layoutId"),
                "parentZoneId": normalized["parentZoneId"],
                "label": label_key,
            },
        )
        child_ids.append(child_id)
        bounds_by_id[child_id] = list(child_bounds)
        zone_type = normalized["zoneTypes"][index]
        _, semantic_type = g1_department_semantic_type(label)
        partition = {
            "arrangement": normalized["arrangement"],
            "orientation": normalized["orientation"],
            "areaProportion": normalized["proportions"][index],
            "areaSizing": normalized["areaSizing"],
        }
        partition.update(row_metadata.get(label.casefold(), {}))
        operations.append(
            {
                "op": "add_zone",
                "zone": {
                    "zoneId": child_id,
                    "zoneType": zone_type,
                    "label": label,
                    "boundary": [
                        {"x": child_bounds[0], "z": child_bounds[1]},
                        {"x": child_bounds[2], "z": child_bounds[1]},
                        {"x": child_bounds[2], "z": child_bounds[3]},
                        {"x": child_bounds[0], "z": child_bounds[3]},
                    ],
                    "floorElevation": float(parent.get("floorElevation") or 0.0),
                    "anchors": [],
                    "evidence": [],
                    "extensions": {
                        "knowledgeFoundation": {
                            "entityKind": "subzone",
                            "semanticType": semantic_type,
                            "semanticTypeEvidenceStatus": normalized[
                                "zoneTypeEvidenceStatus"
                            ],
                            "parentZoneId": normalized["parentZoneId"],
                            "parentLabel": normalized["parentDepartment"],
                            "generatedBy": "facility_subdivision_g3",
                            "partitionAssumptions": list(
                                normalized["assumptions"]
                            ),
                            "partition": partition,
                        }
                    },
                },
            }
        )
    return {
        "normalizedRequest": normalized,
        "operations": operations,
        "assumptions": list(normalized["assumptions"]),
        "expectedSummary": {
            "parentZoneId": normalized["parentZoneId"],
            "parentDepartment": normalized["parentDepartment"],
            "parentZoneRevision": _revision(parent),
            "parentBounds": list(parent_bounds),
            "childZoneIds": child_ids,
            "childLabels": list(normalized["labels"]),
            "childZoneTypes": list(normalized["zoneTypes"]),
            "proportions": list(normalized["proportions"]),
            "boundsByZoneId": bounds_by_id,
            "arrangement": normalized["arrangement"],
            "rows": deepcopy(normalized["rows"]),
            "areaSizing": normalized["areaSizing"],
        },
    }


def compile_department_subdivision_program(
    layout: Mapping[str, Any],
    requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(requests, Sequence) or isinstance(requests, (str, bytes)):
        raise FacilitySubdivisionError(
            "facility_subdivision_program_invalid",
            "Subdivision requests must be an ordered array.",
        )
    base_zone_revisions = {
        str(zone.get("zoneId")): _revision(zone)
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping) and zone.get("zoneId")
    }
    preserved = {
        field: _revision(layout.get(field, [])) for field in _PRESERVED_COLLECTIONS
    }
    working = deepcopy(dict(layout))
    operations: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    normalized_requests: list[dict[str, Any]] = []
    assumptions: list[str] = []
    for request in requests:
        compiled = _compile_one(working, request)
        operations.extend(compiled["operations"])
        groups.append(compiled["expectedSummary"])
        normalized_requests.append(compiled["normalizedRequest"])
        assumptions.extend(compiled["assumptions"])
        working = apply_facility_layout_operations(
            working,
            compiled["operations"],
            base_revision=layout_revision(working),
        )["document"]
    return {
        "stageId": "department_subdivisions",
        "selectedCommandIds": ["bulk-zones"] if operations else [],
        "operations": operations,
        "plannedInstanceCount": len(operations),
        "normalizedRequest": {
            "scope": G3_SUBDIVISION_SCOPE,
            "requests": normalized_requests,
        },
        "assumptions": list(dict.fromkeys(assumptions)),
        "validationPlan": [
            "parent_identity_preserved",
            "child_label_identity",
            "parent_containment",
            "zero_child_overlap",
            "exact_parent_coverage",
            "unrelated_layout_byte_parity",
        ],
        "expectedSummary": {
            "subdivisionCount": len(groups),
            "childZoneCount": len(operations),
            "groups": groups,
            "baseZoneRevisions": base_zone_revisions,
            "preservedCollectionRevisions": preserved,
            "saved": False,
        },
    }


def validate_department_subdivision_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    zones = {
        str(zone.get("zoneId")): zone
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping) and zone.get("zoneId")
    }
    errors: list[str] = []
    expected_child_ids = {
        str(child_id)
        for group in expected.get("groups", [])
        if isinstance(group, Mapping)
        for child_id in group.get("childZoneIds", [])
    }
    base_revisions = expected.get("baseZoneRevisions") or {}
    for zone_id, revision in base_revisions.items():
        if zone_id not in zones:
            errors.append(f"base_zone_missing:{zone_id}")
        elif _revision(zones[zone_id]) != revision:
            errors.append(f"base_zone_changed:{zone_id}")
    if set(zones) != set(base_revisions) | expected_child_ids:
        errors.append("zone_identity_set_changed")
    group_results = []
    for group in expected.get("groups", []):
        parent_id = str(group.get("parentZoneId") or "")
        child_ids = [str(item) for item in group.get("childZoneIds", [])]
        parent = zones.get(parent_id)
        children = [zones.get(item) for item in child_ids]
        group_errors: list[str] = []
        if parent is None:
            group_errors.append("parent_missing")
        if any(item is None for item in children):
            group_errors.append("child_missing")
        rectangles = []
        if parent is not None and not group_errors:
            parent_rect = _rectangle(parent)
            rectangles = [_rectangle(item) for item in children if item is not None]
            expected_bounds = group.get("boundsByZoneId") or {}
            for child_id, child, rectangle in zip(
                child_ids, children, rectangles, strict=True
            ):
                planned = expected_bounds.get(child_id)
                if not isinstance(planned, Sequence) or len(planned) != 4 or any(
                    abs(actual - float(target)) > G1_COORDINATE_PRECISION_METERS
                    for actual, target in zip(rectangle, planned, strict=True)
                ):
                    group_errors.append(f"child_geometry_changed:{child_id}")
                if _zone_parent_id(child) != parent_id:
                    group_errors.append(f"parent_binding_changed:{child_id}")
                if not (
                    rectangle[0] >= parent_rect[0] - G1_PARTITION_TOLERANCE
                    and rectangle[1] >= parent_rect[1] - G1_PARTITION_TOLERANCE
                    and rectangle[2] <= parent_rect[2] + G1_PARTITION_TOLERANCE
                    and rectangle[3] <= parent_rect[3] + G1_PARTITION_TOLERANCE
                ):
                    group_errors.append(f"child_outside_parent:{child_id}")
            for left in range(len(rectangles)):
                for right in range(left + 1, len(rectangles)):
                    a, b = rectangles[left], rectangles[right]
                    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                        0.0, min(a[3], b[3]) - max(a[1], b[1])
                    )
                    if overlap > G1_PARTITION_TOLERANCE:
                        group_errors.append(
                            f"child_overlap:{child_ids[left]}:{child_ids[right]}"
                        )
            parent_area = (parent_rect[2] - parent_rect[0]) * (
                parent_rect[3] - parent_rect[1]
            )
            child_area = sum(
                (item[2] - item[0]) * (item[3] - item[1]) for item in rectangles
            )
            tolerance = max(G1_PARTITION_TOLERANCE, parent_area * 1e-8)
            if abs(child_area - parent_area) > tolerance:
                group_errors.append("parent_area_not_fully_allocated")
            actual_labels = [str(item.get("label") or "") for item in children]
            if actual_labels != list(group.get("childLabels") or []):
                group_errors.append("child_labels_changed")
            actual_types = [str(item.get("zoneType") or "") for item in children]
            if actual_types != list(group.get("childZoneTypes") or []):
                group_errors.append("child_zone_types_changed")
        group_results.append(
            {
                "parentZoneId": parent_id,
                "childZoneIds": child_ids,
                "status": "valid" if not group_errors else "invalid",
                "errors": group_errors,
            }
        )
        errors.extend(group_errors)
    for field, revision in (
        expected.get("preservedCollectionRevisions") or {}
    ).items():
        if _revision(layout.get(field, [])) != revision:
            errors.append(f"unrelated_collection_changed:{field}")
    return {
        "status": "valid" if not errors else "invalid",
        "layoutRevision": layout_revision(layout),
        "subdivisionCount": len(group_results),
        "childZoneCount": len(expected_child_ids),
        "groups": group_results,
        "errors": errors,
    }


__all__ = [
    "G3_FACILITY_SUBDIVISION_TOOL",
    "G3_SUBDIVISION_SCOPE",
    "FacilitySubdivisionError",
    "compile_department_subdivision_program",
    "normalize_subdivision_request",
    "parse_subdivision_turn",
    "subdivision_tool_spec",
    "validate_department_subdivision_result",
]
