"""Pure, deterministic Facility Layout v1 domain operations.

This module performs no I/O, generates no time or randomness, and never mutates
the caller's document. Repository code owns authorization, timestamps, CAS,
backups, and durable writes.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .canonical import canonical_layout_bytes, canonicalize_layout, layout_revision
from .diff import build_exact_layout_diff, facility_layout_diff_hash
from .errors import FacilityValidationError
from .navigation_contract import (
    FacilityNavigationContractError,
    canonicalize_facility_navigation_extension,
    navigation_identity_index,
    validate_navigation_writer_authority,
)
from .plan_settings import PLAN_SETTINGS_EXTENSION_KEY, normalize_plan_settings
from .perimeter_walls import KEY as WALLS_KEY, compile_perimeter_walls
from .routing import persisted_route_fingerprint
from .validate import validate_layout


MAX_OPERATION_BATCH = 500
_LABEL_LIMIT = 120
_ID_LIMIT = 128
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_POSITION_MODES = frozenset(("auto", "manual", "locked"))
_MOVEMENT_KINDS = frozenset(("user", "automatic"))
_LAYOUT_PROVENANCE_COMMANDS = frozenset((
    "linear_pattern",
    "circular_pattern",
    "perimeter",
    "cell_layout",
    "vertical_stack",
    "surface_stack",
    "mirror",
    "swap",
    "duplicate",
    "industrial_pattern_module_source",
))
_LAYOUT_STRATEGIES = frozenset((
    "line",
    "l",
    "u",
    "grid",
    "parallel",
    "serpentine",
    "loop",
    "spine",
    "herringbone",
    "cluster",
    "deterministic_industrial_pattern_set",
))


class FacilityLayoutOperationError(FacilityValidationError):
    """A requested pure operation is malformed or cannot be applied."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        operation_index: Optional[int] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        error_details = deepcopy(dict(details or {}))
        if operation_index is not None:
            error_details["operationIndex"] = operation_index
        super().__init__(code, message, details=error_details)
        self.operation_index = operation_index

    def finding(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "severity": "error",
            "code": self.code,
            "message": str(self),
        }
        if self.operation_index is not None:
            result["operationIndex"] = self.operation_index
        details = {
            key: value
            for key, value in self.details.items()
            if key != "operationIndex"
        }
        if details:
            result["details"] = deepcopy(details)
        return result


def _fail(
    code: str,
    message: str,
    *,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    raise FacilityLayoutOperationError(code, message, details=details)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        _fail("invalid_operation", f"Operation data is not canonical JSON: {exc}")
    raise AssertionError("unreachable")


def _clean_id(value: Any, field: str, prefix: Optional[str] = None) -> str:
    if not isinstance(value, str):
        _fail("invalid_operation_field", f"{field} must be a string.")
    cleaned = value.strip()
    if (
        not cleaned
        or len(cleaned) > _ID_LIMIT
        or _ID_PATTERN.fullmatch(cleaned) is None
        or (prefix is not None and not cleaned.startswith(f"{prefix}-"))
    ):
        requirement = f" beginning with '{prefix}-'" if prefix else ""
        _fail(
            "invalid_operation_field",
            f"{field} must be a valid stable ID{requirement}.",
        )
    return cleaned


def _clean_label(value: Any, field: str = "displayName") -> str:
    if not isinstance(value, str):
        _fail("invalid_operation_field", f"{field} must be a string.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _LABEL_LIMIT:
        _fail(
            "invalid_operation_field",
            f"{field} must contain 1 to {_LABEL_LIMIT} characters.",
        )
    return cleaned


def _mapping(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_operation_field", f"{field} must be an object.")
    return deepcopy(dict(value))


def _layout_provenance(value: Any) -> Dict[str, Any]:
    provenance = _mapping(value, "layoutProvenance")
    command = provenance.get("command")
    if command not in _LAYOUT_PROVENANCE_COMMANDS:
        _fail(
            "invalid_operation_field",
            "layoutProvenance.command is unsupported.",
        )
    strategy = provenance.get("authoredStrategy")
    if strategy is not None and strategy not in _LAYOUT_STRATEGIES:
        _fail(
            "invalid_operation_field",
            "layoutProvenance.authoredStrategy is unsupported.",
        )
    seed_ids = provenance.get("seedEntityIds", [])
    if (
        not isinstance(seed_ids, list)
        or len(seed_ids) > MAX_OPERATION_BATCH
        or any(not isinstance(item, str) or not item for item in seed_ids)
    ):
        _fail(
            "invalid_operation_field",
            "layoutProvenance.seedEntityIds must be a bounded string array.",
        )
    parameters = provenance.get("parameters", {})
    if not isinstance(parameters, Mapping) or len(parameters) > 32:
        _fail(
            "invalid_operation_field",
            "layoutProvenance.parameters must be a bounded object.",
        )
    result = deepcopy(provenance)
    result["schemaVersion"] = 1
    result["command"] = command
    result["authoredStrategy"] = strategy
    result["seedEntityIds"] = list(dict.fromkeys(seed_ids))
    result["parameters"] = deepcopy(dict(parameters))
    result["manuallyEditedSinceCreation"] = False
    return result


def _current_layout_geometry(target: Mapping[str, Any]) -> Dict[str, Any]:
    if "placementId" in target:
        return {
            "kind": "placement",
            "transform": deepcopy(target.get("transform")),
        }
    if "markingId" in target:
        return {
            "kind": "floor_marking",
            "transform": deepcopy(target.get("transform")),
            "width": target.get("width"),
            "depth": target.get("depth"),
        }
    return {
        "kind": "zone",
        "boundary": deepcopy(target.get("boundary")),
    }


def _normalize_embedded_layout_provenance(
    target: Dict[str, Any],
    *,
    container: str,
) -> None:
    record = target.get(container)
    if not isinstance(record, dict):
        return
    raw = record.get("layoutProvenance")
    if not isinstance(raw, Mapping):
        return
    normalized = _layout_provenance(raw)
    normalized.setdefault(
        "authoredGeometry",
        _current_layout_geometry(target),
    )
    record["layoutProvenance"] = normalized


def _set_or_stale_layout_provenance(
    target: Dict[str, Any],
    operation: Mapping[str, Any],
    *,
    container: str,
    manually_edited: bool = True,
) -> None:
    record = target.get(container)
    if not isinstance(record, dict):
        record = {}
        target[container] = record
    supplied = operation.get("layoutProvenance")
    if supplied is not None:
        normalized = _layout_provenance(supplied)
        normalized.setdefault(
            "authoredGeometry",
            _current_layout_geometry(target),
        )
        record["layoutProvenance"] = normalized
        return
    current = record.get("layoutProvenance")
    if isinstance(current, Mapping):
        stale = deepcopy(dict(current))
        stale["geometryEditedSinceCreation"] = True
        if manually_edited:
            stale["manuallyEditedSinceCreation"] = True
        record["layoutProvenance"] = stale


def _collection(document: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    value = document.get(field)
    if not isinstance(value, list):
        _fail("invalid_layout_shape", f"{field} must be an array.")
    if not all(isinstance(item, Mapping) for item in value):
        _fail("invalid_layout_shape", f"{field} must contain objects.")
    return value


def _find(
    document: Dict[str, Any],
    collection: str,
    key: str,
    identifier: str,
    label: str,
) -> Dict[str, Any]:
    match = next(
        (
            record
            for record in _collection(document, collection)
            if record.get(key) == identifier
        ),
        None,
    )
    if match is None:
        _fail(
            "operation_target_not_found",
            f"{label} '{identifier}' was not found.",
            details={"targetId": identifier},
        )
    return match


def _all_object_ids(document: Dict[str, Any]) -> Set[str]:
    result: Set[str] = set()
    for collection, key in (
        ("zones", "zoneId"),
        ("placements", "placementId"),
        ("routes", "routeId"),
        ("utilityNetworks", "utilityNetworkId"),
        ("processBindings", "processBindingId"),
    ):
        result.update(
            str(record[key])
            for record in _collection(document, collection)
            if isinstance(record.get(key), str)
        )
    result.update(
        str(record["markingId"])
        for record in document.get("floorMarkings", [])
        if isinstance(record, Mapping)
        and isinstance(record.get("markingId"), str)
    )
    for network in _collection(document, "utilityNetworks"):
        for collection, key in (
            (network.get("nodes"), "networkNodeId"),
            (network.get("segments"), "networkSegmentId"),
        ):
            if not isinstance(collection, list):
                continue
            result.update(
                str(record[key])
                for record in collection
                if isinstance(record, Mapping)
                and isinstance(record.get(key), str)
            )
    return result


def _deterministic_id(
    document: Dict[str, Any],
    *,
    prefix: str,
    operation: Mapping[str, Any],
    operation_index: int,
    base_revision: str,
) -> str:
    seed = {
        "layoutId": document.get("layoutId"),
        "baseRevision": base_revision,
        "operationIndex": operation_index,
        "operation": deepcopy(dict(operation)),
    }
    digest = hashlib.sha256(_canonical_json_bytes(seed)).hexdigest()
    used = _all_object_ids(document)
    for width in (24, 32, 40, 48, 56, 64):
        candidate = f"{prefix}-{digest[:width]}"
        if candidate not in used:
            return candidate
    _fail("id_allocation_failed", f"Could not allocate a unique {prefix} ID.")
    raise AssertionError("unreachable")


def _requested_or_generated_id(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    operation_index: int,
    *,
    field: str,
    prefix: str,
    base_revision: str,
) -> str:
    requested = operation.get(field)
    identifier = (
        _clean_id(requested, field, prefix)
        if requested is not None
        else _deterministic_id(
            document,
            prefix=prefix,
            operation=operation,
            operation_index=operation_index,
            base_revision=base_revision,
        )
    )
    if identifier in _all_object_ids(document):
        _fail(
            "duplicate_id",
            f"{field} '{identifier}' is already in use.",
            details={"targetId": identifier},
        )
    return identifier


def _reference_matches(value: Any, key: str, identifier: str) -> bool:
    # Layouts are JSON trees. Avoid generic Mapping dispatch on every scalar,
    # while retaining support for mapping/list subclasses at the API boundary.
    pending = [value]
    while pending:
        current = pending.pop()
        kind = type(current)
        if kind is dict:
            if current.get(key) == identifier:
                return True
            pending.extend(current.values())
        elif kind is list:
            pending.extend(current)
        elif kind not in (str, int, float, bool, type(None)):
            if isinstance(current, Mapping):
                if current.get(key) == identifier:
                    return True
                pending.extend(current.values())
            elif isinstance(current, list):
                pending.extend(current)
    return False


def _zone_references(document: Dict[str, Any], zone_id: str) -> List[str]:
    references: List[str] = []
    for collection, key in (
        ("placements", "placementId"),
        ("routes", "routeId"),
        ("utilityNetworks", "utilityNetworkId"),
        ("processBindings", "processBindingId"),
    ):
        for record in _collection(document, collection):
            if _reference_matches(record, "zoneId", zone_id):
                references.append(str(record.get(key) or collection))
    return sorted(set(references))


def _placement_references(document: Dict[str, Any], placement_id: str) -> List[str]:
    references: List[str] = []
    for collection, key in (
        ("placements", "placementId"),
        ("routes", "routeId"),
        ("utilityNetworks", "utilityNetworkId"),
        ("processBindings", "processBindingId"),
    ):
        for record in _collection(document, collection):
            if collection == "placements" and record.get("placementId") == placement_id:
                continue
            if _reference_matches(record, "placementId", placement_id):
                references.append(str(record.get(key) or collection))
            if collection == "placements":
                relationship = record.get("snapRelationship")
                if (
                    isinstance(relationship, Mapping)
                    and relationship.get("supportPlacementId") == placement_id
                ):
                    references.append(str(record.get(key) or collection))
            if collection == "processBindings":
                ids = record.get("placementIds")
                if isinstance(ids, list) and placement_id in ids:
                    references.append(str(record.get(key) or collection))
    return sorted(set(references))


def _validation_findings(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    result = validate_layout(document)
    if result is None:
        return []
    if isinstance(result, Mapping):
        raw = result.get("findings", [])
    else:
        raw = result
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        _fail("invalid_validator_result", "validate_layout returned an invalid result.")
    findings = [deepcopy(dict(item)) for item in raw if isinstance(item, Mapping)]
    errors = [item for item in findings if item.get("severity") == "error"]
    if errors:
        _fail(
            "layout_validation_failed",
            "The operation batch produced an invalid Facility Layout.",
            details={"findings": errors},
        )
    return findings


def _op_rename_layout(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    document["displayName"] = _clean_label(operation.get("displayName"))
    return [], [str(document["layoutId"])]


def _op_archive_layout(
    document: Dict[str, Any],
    _operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    document["status"] = "archived"
    return [], [str(document["layoutId"])]


def _op_add_zone(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    zone = _mapping(operation.get("zone"), "zone")
    zone_id = _requested_or_generated_id(
        document,
        {**operation, "zone": {key: value for key, value in zone.items() if key != "zoneId"}},
        index,
        field="zoneId",
        prefix="zn",
        base_revision=base_revision,
    ) if zone.get("zoneId") is None and operation.get("zoneId") is None else _clean_id(
        zone.get("zoneId", operation.get("zoneId")),
        "zoneId",
        "zn",
    )
    if zone_id in _all_object_ids(document):
        _fail("duplicate_id", f"zoneId '{zone_id}' is already in use.")
    zone["zoneId"] = zone_id
    _normalize_embedded_layout_provenance(
        zone,
        container="extensions",
    )
    _collection(document, "zones").append(zone)
    return [zone_id], [zone_id]


def _op_edit_zone(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    zone_id = _clean_id(operation.get("zoneId"), "zoneId", "zn")
    patch = _mapping(operation.get("patch"), "patch")
    if "zoneId" in patch:
        _fail("immutable_identity", "edit_zone cannot change zoneId.")
    zone = _find(document, "zones", "zoneId", zone_id, "Zone")
    for key, value in patch.items():
        zone[str(key)] = deepcopy(value)
    if operation.get("layoutProvenance") is not None:
        _set_or_stale_layout_provenance(
            zone,
            operation,
            container="extensions",
            manually_edited=False,
        )
    elif {"boundary", "anchors", "floorElevation"}.intersection(patch):
        _set_or_stale_layout_provenance(
            zone,
            operation,
            container="extensions",
        )
    return [], [zone_id]


def _op_delete_zone(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    zone_id = _clean_id(operation.get("zoneId"), "zoneId", "zn")
    _find(document, "zones", "zoneId", zone_id, "Zone")
    references = _zone_references(document, zone_id)
    if references:
        _fail(
            "referenced_object_in_use",
            f"Zone '{zone_id}' is still referenced.",
            details={"targetId": zone_id, "references": references},
        )
    document["zones"] = [
        zone for zone in _collection(document, "zones") if zone.get("zoneId") != zone_id
    ]
    return [], [zone_id]


def _floor_markings(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = document.setdefault("floorMarkings", [])
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        _fail("invalid_layout_shape", "floorMarkings must contain objects.")
    return value


def _op_add_floor_marking(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    marking = _mapping(operation.get("floorMarking"), "floorMarking")
    requested = marking.get("markingId", operation.get("markingId"))
    if requested is None:
        identity_operation = {
            **operation,
            "floorMarking": {
                key: value
                for key, value in marking.items()
                if key != "markingId"
            },
        }
        marking_id = _requested_or_generated_id(
            document,
            identity_operation,
            index,
            field="markingId",
            prefix="fm",
            base_revision=base_revision,
        )
    else:
        marking_id = _clean_id(requested, "markingId", "fm")
    if marking_id in _all_object_ids(document):
        _fail("duplicate_id", f"markingId '{marking_id}' is already in use.")
    marking["markingId"] = marking_id
    _normalize_embedded_layout_provenance(
        marking,
        container="metadata",
    )
    _floor_markings(document).append(marking)
    return [marking_id], [marking_id]


def _op_add_floor_path(document, operation, index, base_revision):
    from .floor_paths import compile_floor_path
    created = []
    for marking in compile_floor_path(operation.get("path")):
        ids, _ = _op_add_floor_marking(document, {"op": "add_floor_marking", "floorMarking": marking}, index, base_revision)
        created.extend(ids)
    return created, created


def _op_edit_floor_marking(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    marking_id = _clean_id(operation.get("markingId"), "markingId", "fm")
    _floor_markings(document)
    patch = _mapping(operation.get("patch"), "patch")
    if "markingId" in patch:
        _fail(
            "immutable_identity",
            "edit_floor_marking cannot change markingId.",
        )
    marking = _find(
        document,
        "floorMarkings",
        "markingId",
        marking_id,
        "Floor marking",
    )
    if marking.get("positionMode") == "locked" and (
        "transform" in patch or "width" in patch or "depth" in patch
    ):
        _fail(
            "locked_object",
            f"Floor marking '{marking_id}' is locked.",
            details={"targetId": marking_id},
        )
    for key, value in patch.items():
        marking[str(key)] = deepcopy(value)
    if {"transform", "width", "depth"}.intersection(patch):
        _set_or_stale_layout_provenance(
            marking,
            operation,
            container="metadata",
        )
    return [], [marking_id]


def _op_delete_floor_marking(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    marking_id = _clean_id(operation.get("markingId"), "markingId", "fm")
    _floor_markings(document)
    _find(
        document,
        "floorMarkings",
        "markingId",
        marking_id,
        "Floor marking",
    )
    document["floorMarkings"] = [
        marking
        for marking in _floor_markings(document)
        if marking.get("markingId") != marking_id
    ]
    return [], [marking_id]


def _op_place_asset(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    placement = _mapping(operation.get("placement"), "placement")
    requested = placement.get("placementId", operation.get("placementId"))
    if requested is None:
        identity_operation = deepcopy(dict(operation))
        identity_placement = deepcopy(placement)
        identity_placement.pop("placementId", None)
        identity_operation["placement"] = identity_placement
        placement_id = _deterministic_id(
            document,
            prefix="pl",
            operation=identity_operation,
            operation_index=index,
            base_revision=base_revision,
        )
    else:
        placement_id = _clean_id(requested, "placementId", "pl")
    if placement_id in _all_object_ids(document):
        _fail("duplicate_id", f"placementId '{placement_id}' is already in use.")
    placement["placementId"] = placement_id
    _normalize_embedded_layout_provenance(
        placement,
        container="metadata",
    )
    _collection(document, "placements").append(placement)
    return [placement_id], [placement_id]


MAX_ARRAY_COUNT = 200
_ARRAY_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")


def _op_place_asset_array(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    """A straight row of copies of one placement (racks, parked cars): ids pl-<arrayId>-001 onward,
    each `step` metres on from the last. Placing the same arrayId again replaces the earlier row."""
    if set(operation) - {"op", "arrayId", "placement", "step", "count"}:
        _fail("invalid_operation_field", "place_asset_array takes arrayId, placement, step and count.")
    array_id = operation.get("arrayId")
    if not isinstance(array_id, str) or _ARRAY_ID.fullmatch(array_id) is None:
        _fail("invalid_operation_field", "arrayId must be 1 to 60 lowercase letters, digits and hyphens.")
    count = operation.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_ARRAY_COUNT:
        _fail("invalid_operation_field", f"count must be a whole number from 1 to {MAX_ARRAY_COUNT}.")
    step = _mapping(operation.get("step"), "step")
    if set(step) - {"x", "y", "z"}:
        _fail("invalid_operation_field", "step takes x, y and z.")
    offsets = []
    for axis in ("x", "y", "z"):
        value = step.get(axis, 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not abs(value) <= 1000:
            _fail("invalid_operation_field", f"step.{axis} must be a number of metres within 1000.")
        offsets.append(float(value))
    template = _mapping(operation.get("placement"), "placement")
    position = _mapping(_mapping(template.get("transform"), "placement.transform").get("position"),
                        "placement.transform.position")
    for axis in ("x", "y", "z"):
        if isinstance(position.get(axis), bool) or not isinstance(position.get(axis), (int, float)):
            _fail("invalid_operation_field", f"placement.transform.position.{axis} must be a number.")
    prefix = f"pl-{array_id}-"
    removed = [str(item.get("placementId")) for item in document.get("placements", [])
               if str(item.get("placementId", "")).startswith(prefix)]
    for placement_id in removed:
        _op_delete_placement(document, {"op": "delete_placement", "placementId": placement_id}, index, base_revision)
    label = (template.get("metadata") or {}).get("instanceLabel") if isinstance(template.get("metadata"), Mapping) else None
    created: List[str] = []
    for number in range(count):
        placement = deepcopy(dict(template))
        placement.pop("placementId", None)
        moved = placement["transform"]["position"]
        for axis, offset in zip(("x", "y", "z"), offsets):
            moved[axis] = round(float(moved[axis]) + offset * number, 6)
        placement["placementId"] = f"{prefix}{number + 1:03}"
        if label:
            placement["metadata"] = {**placement["metadata"], "instanceLabel": f"{label} {number + 1}"[:120]}
        made, _ = _op_place_asset(document, {"op": "place_asset", "placement": placement}, index, base_revision)
        created.extend(made)
    return created, created + removed


def _op_delete_asset_array(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    """Remove a whole row placed by place_asset_array."""
    if set(operation) != {"op", "arrayId"}:
        _fail("invalid_operation_field", "delete_asset_array takes arrayId.")
    array_id = operation.get("arrayId")
    if not isinstance(array_id, str) or _ARRAY_ID.fullmatch(array_id) is None:
        _fail("invalid_operation_field", "arrayId must be 1 to 60 lowercase letters, digits and hyphens.")
    prefix = f"pl-{array_id}-"
    removed = [str(item.get("placementId")) for item in document.get("placements", [])
               if str(item.get("placementId", "")).startswith(prefix)]
    if not removed:
        _fail("object_not_found", f"No row has arrayId '{array_id}'.")
    for placement_id in removed:
        _op_delete_placement(document, {"op": "delete_placement", "placementId": placement_id}, index, base_revision)
    return [], removed


def _movement(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    *,
    field: str,
) -> Tuple[Dict[str, Any], str, str]:
    placement_id = _clean_id(operation.get("placementId"), "placementId", "pl")
    placement = _find(
        document,
        "placements",
        "placementId",
        placement_id,
        "Placement",
    )
    movement_kind = operation.get("movementKind", "user")
    if movement_kind not in _MOVEMENT_KINDS:
        _fail(
            "invalid_operation_field",
            "movementKind must be 'user' or 'automatic'.",
        )
    mode = placement.get("positionMode")
    if mode == "locked":
        _fail(
            "locked_placement_movement",
            f"Placement '{placement_id}' is locked.",
        )
    if movement_kind == "automatic" and mode != "auto":
        _fail(
            "manual_placement_preserved",
            f"Automatic movement may only move auto placement '{placement_id}'.",
        )
    transform = placement.get("transform")
    if not isinstance(transform, dict):
        _fail("invalid_layout_shape", f"Placement '{placement_id}' has no transform.")
    if field not in operation:
        _fail("invalid_operation_field", f"{field} is required.")
    return placement, placement_id, str(movement_kind)


def _op_move_placement(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    placement, placement_id, movement_kind = _movement(
        document,
        operation,
        field="position",
    )
    placement["transform"]["position"] = _mapping(operation["position"], "position")
    _set_or_stale_layout_provenance(
        placement,
        operation,
        container="metadata",
        manually_edited=movement_kind == "user",
    )
    if movement_kind == "user" and placement.get("positionMode") == "auto":
        placement["positionMode"] = "manual"
    return [], [placement_id]


def _op_rotate_placement(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    placement, placement_id, movement_kind = _movement(
        document,
        operation,
        field="quaternion",
    )
    placement["transform"]["quaternion"] = _mapping(
        operation["quaternion"],
        "quaternion",
    )
    _set_or_stale_layout_provenance(
        placement,
        operation,
        container="metadata",
        manually_edited=movement_kind == "user",
    )
    if movement_kind == "user" and placement.get("positionMode") == "auto":
        placement["positionMode"] = "manual"
    return [], [placement_id]


def _op_duplicate_placement(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    source_id = _clean_id(
        operation.get("sourcePlacementId"),
        "sourcePlacementId",
        "pl",
    )
    source = _find(
        document,
        "placements",
        "placementId",
        source_id,
        "Placement",
    )
    new_id = _requested_or_generated_id(
        document,
        operation,
        index,
        field="newPlacementId",
        prefix="pl",
        base_revision=base_revision,
    )
    duplicate = deepcopy(source)
    duplicate["placementId"] = new_id
    duplicate["snapRelationship"] = None
    if "snapRelationship" in operation:
        relationship = operation.get("snapRelationship")
        duplicate["snapRelationship"] = (
            None
            if relationship is None
            else _mapping(relationship, "snapRelationship")
        )
    duplicate["positionMode"] = operation.get("positionMode", "manual")
    if duplicate["positionMode"] not in _POSITION_MODES:
        _fail(
            "invalid_operation_field",
            "positionMode must be auto, manual, or locked.",
        )
    if "transform" in operation:
        duplicate["transform"] = _mapping(operation["transform"], "transform")
    else:
        if "position" in operation:
            duplicate["transform"]["position"] = _mapping(
                operation["position"],
                "position",
            )
        if "quaternion" in operation:
            duplicate["transform"]["quaternion"] = _mapping(
                operation["quaternion"],
                "quaternion",
            )
    if operation.get("layoutProvenance") is not None:
        _set_or_stale_layout_provenance(
            duplicate,
            operation,
            container="metadata",
        )
    else:
        metadata = duplicate.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        duplicate["metadata"] = metadata
        metadata["layoutProvenance"] = {
            "schemaVersion": 1,
            "command": "duplicate",
            "authoredStrategy": None,
            "seedEntityIds": [source_id],
            "parameters": {},
            "manuallyEditedSinceCreation": False,
        }
    _collection(document, "placements").append(duplicate)
    return [new_id], [source_id, new_id]


def _op_delete_placement(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    placement_id = _clean_id(operation.get("placementId"), "placementId", "pl")
    _find(
        document,
        "placements",
        "placementId",
        placement_id,
        "Placement",
    )
    references = _placement_references(document, placement_id)
    if references:
        _fail(
            "referenced_object_in_use",
            f"Placement '{placement_id}' is still referenced.",
            details={"targetId": placement_id, "references": references},
        )
    document["placements"] = [
        placement
        for placement in _collection(document, "placements")
        if placement.get("placementId") != placement_id
    ]
    from .decals import remove_bound_decals
    remove_bound_decals(document, lambda target: target.get("placementId") == placement_id)
    from .equipment_decals import remove_equipment_decals
    remove_equipment_decals(document, placement_id)
    return [], [placement_id]


def _op_set_appearance(document, operation, _index, _base_revision):
    """Set or remove one finish on whole placements.

    ``color`` keeps the original plain-color form. ``appearance`` applies a
    library or custom finish (``{"appearanceId": ..., <overrides>}``); null in
    either form removes the override so the asset's own finish shows again.
    """
    ids = operation.get("placementIds")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 5000:
        _fail("invalid_operation_field", "placementIds must contain 1 to 5000 IDs.")
    ids = [_clean_id(value, "placementId", "pl") for value in ids]
    if len(set(ids)) != len(ids):
        _fail("invalid_operation_field", "placementIds must be unique.")
    if ("color" in operation) == ("appearance" in operation):
        _fail("invalid_operation_field", "Give color or appearance; use null to reset appearance.")
    if "appearance" in operation:
        value = operation["appearance"]
        if value is not None:
            from .appearance_library import normalize_appearance
            try:
                value = normalize_appearance(value, document)
            except ValueError as exc:
                _fail("invalid_appearance", str(exc))
    else:
        color = operation["color"]
        if color is not None and (not isinstance(color, str)
                                 or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None):
            _fail("invalid_operation_field", "color must be a six-digit hex color or null.")
        value = None if color is None else {"color": color.lower()}
    placements = [_find(document, "placements", "placementId", value_id, "Placement") for value_id in ids]
    for placement in placements:
        if value is None:
            placement.pop("appearance", None)
        else:
            placement["appearance"] = deepcopy(value)
    return [], ids


def _op_set_custom_appearances(document, operation, _index, _base_revision):
    from .appearance_library import CUSTOM_KEY, normalize_custom_appearances, validate_layout_references
    if set(operation) != {"op", "appearances"}:
        _fail("invalid_custom_appearances", "Expected appearances")
    try:
        value = normalize_custom_appearances(operation["appearances"])
    except ValueError as exc:
        _fail("invalid_custom_appearances", str(exc))
    extensions = document.setdefault("extensions", {})
    previous = extensions.get(CUSTOM_KEY)
    if value["custom"]:
        extensions[CUSTOM_KEY] = value
    else:
        extensions.pop(CUSTOM_KEY, None)
    try:
        validate_layout_references(document)
    except ValueError as exc:
        if previous is None:
            extensions.pop(CUSTOM_KEY, None)
        else:
            extensions[CUSTOM_KEY] = previous
        _fail("custom_appearance_in_use", f"{exc}. Change those finishes before deleting it.")
    return [], []


def _op_set_scene(document, operation, _index, _base_revision):
    from .appearance_library import SCENE_KEY, normalize_scene
    if set(operation) != {"op", "scene"}:
        _fail("invalid_scene", "Expected scene")
    extensions = document.setdefault("extensions", {})
    if operation["scene"] is None:
        extensions.pop(SCENE_KEY, None)
        return [], []
    try:
        extensions[SCENE_KEY] = normalize_scene(operation["scene"])
    except ValueError as exc:
        _fail("invalid_scene", str(exc))
    return [], []


def _op_set_site_context(document, operation, _index, _base_revision):
    """Place the layout on the Earth, or take it off (site context; site_context.py)."""
    from .site_context import KEY, normalize_site_context
    if set(operation) != {"op", "siteContext"}:
        _fail("invalid_site_context", "Expected siteContext")
    extensions = document.setdefault("extensions", {})
    if operation["siteContext"] is None:
        extensions.pop(KEY, None)
        return [], []
    try:
        extensions[KEY] = normalize_site_context(operation["siteContext"], document)
    except ValueError as exc:
        _fail("invalid_site_context", str(exc))
    return [], []


def _op_set_building_pose(document, operation, _index, _base_revision):
    from .site_context import KEY, normalize_site_context
    if set(operation) != {"op", "buildingPose"}:
        _fail("invalid_building_pose", "Expected buildingPose")
    context = (document.get("extensions") or {}).get(KEY)
    if context is None:
        _fail("site_context_missing", "Place the layout on a site before moving the building")
    try:
        document["extensions"][KEY] = normalize_site_context({**context, "buildingPose": operation["buildingPose"]}, document)
    except ValueError as exc:
        _fail("invalid_building_pose", str(exc))
    return [], []


def _op_upsert_site_area(document, operation, _index, _base_revision):
    from .site_context import KEY, normalize_site_context, normalize_site_area
    if set(operation) != {"op", "area"}:
        _fail("invalid_site_area", "Expected area")
    context = (document.get("extensions") or {}).get(KEY)
    if context is None:
        _fail("site_context_missing", "Place the layout on a site first")
    try:
        area = normalize_site_area(operation["area"])
        existing = context.get("areas", [])
        created = not any(item["areaId"] == area["areaId"] for item in existing)
        areas = [area if item["areaId"] == area["areaId"] else item for item in existing]
        if created:
            areas.append(area)
        document["extensions"][KEY] = normalize_site_context({**context, "areas": areas}, document)
    except ValueError as exc:
        _fail("invalid_site_area", str(exc))
    return [area["areaId"]] if created else [], [area["areaId"]]


def _op_upsert_site_reference(document, operation, _index, _base_revision):
    from .site_context import KEY, normalize_site_context, normalize_site_reference
    if set(operation) != {"op", "reference"}:
        _fail("invalid_site_reference", "Expected reference")
    context = (document.get("extensions") or {}).get(KEY)
    if context is None:
        _fail("site_context_missing", "Place the layout on a site first")
    try:
        reference = normalize_site_reference(operation["reference"])
        existing = context.get("references", [])
        created = not any(item["referenceId"] == reference["referenceId"] for item in existing)
        references = [reference if item["referenceId"] == reference["referenceId"] else item for item in existing]
        if created:
            references.append(reference)
        document["extensions"][KEY] = normalize_site_context({**context, "references": references}, document)
    except ValueError as exc:
        _fail("invalid_site_reference", str(exc))
    return [reference["referenceId"]] if created else [], [reference["referenceId"]]


def _op_delete_site_reference(document, operation, _index, _base_revision):
    from .site_context import KEY, normalize_site_context
    if set(operation) != {"op", "referenceId"} or not isinstance(operation["referenceId"], str):
        _fail("invalid_site_reference", "Expected referenceId")
    context = (document.get("extensions") or {}).get(KEY)
    if context is None or not any(item["referenceId"] == operation["referenceId"]
                                  for item in context.get("references", [])):
        _fail("site_reference_missing", "Reference point was not found")
    references = [item for item in context["references"] if item["referenceId"] != operation["referenceId"]]
    document["extensions"][KEY] = normalize_site_context({**context, "references": references}, document)
    return [], [operation["referenceId"]]


def _op_delete_site_area(document, operation, _index, _base_revision):
    from .site_context import KEY, normalize_site_context
    if set(operation) != {"op", "areaId"} or not isinstance(operation["areaId"], str):
        _fail("invalid_site_area", "Expected areaId")
    context = (document.get("extensions") or {}).get(KEY)
    if context is None or not any(area["areaId"] == operation["areaId"] for area in context.get("areas", [])):
        _fail("site_area_missing", "Outdoor area was not found")
    document["extensions"][KEY] = normalize_site_context({**context, "areas": [
        area for area in context["areas"] if area["areaId"] != operation["areaId"]]}, document)
    return [], [operation["areaId"]]


def _op_set_equipment_decals(document, operation, _index, _base_revision):
    from .equipment_decals import KEY, normalize_equipment_decals
    if set(operation) != {"op", "decals"}:
        _fail("invalid_equipment_decals", "Expected decals")
    try:
        value = normalize_equipment_decals(operation["decals"], document)
    except ValueError as exc:
        _fail("invalid_equipment_decals", str(exc))
    extensions = document.setdefault("extensions", {})
    if value["decals"]:
        extensions[KEY] = value
    else:
        extensions.pop(KEY, None)
    return [], sorted({row["placementId"] for row in value["decals"]})


def _op_replace_asset(document, operation, _index, _base_revision):
    identifier = _clean_id(operation.get("placementId"), "placementId", "pl")
    placement = _find(document, "placements", "placementId", identifier, "Placement")
    asset_id = _clean_id(operation.get("assetId"), "assetId", "asset")
    revision = operation.get("assetDefinitionRevision")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        _fail("invalid_operation_field", "Choose an exact asset definition revision.")
    keep = operation.get("keepAppearance", True)
    if type(keep) is not bool:
        _fail("invalid_operation_field", "keepAppearance must be boolean.")
    if placement["assetId"] == asset_id and placement["assetDefinitionRevision"] == revision:
        return [], []
    references = _placement_references(document, identifier)
    if placement.get("snapRelationship"):
        references.append("placement attachment")
    ext = document.get("extensions", {})
    art = list(ext.get("facilityDecals", {}).get("artworks", []))
    art += ext.get("facilityPerimeterWalls", {}).get("settings", {}).get("exteriorFinish", {}).get("fittedArtworks", [])
    if any(a.get("target", {}).get("placementId") == identifier for a in art):
        references.append("wall artwork")
    if _reference_matches(ext.get("facilityNavigation", {}), "placementId", identifier):
        references.append("movement program")
    if references:
        _fail("replacement_has_dependencies", "Detach linked equipment, routes, process bindings, movement, or wall artwork before replacing this asset.", details={"targetId":identifier,"references":sorted(set(references))})
    placement["assetId"] = asset_id
    placement["assetDefinitionRevision"] = revision
    placement.pop("componentMaterials", None)
    from .equipment_decals import remove_equipment_decals
    remove_equipment_decals(document, identifier)
    if not keep: placement.pop("appearance", None)
    _set_or_stale_layout_provenance(placement, operation, container="metadata")
    return [], [identifier]


def _op_set_floor_surfaces(document, operation, _index, _base_revision):
    from .floor_surfaces import normalize_floor_surfaces, KEY
    try:
        value = normalize_floor_surfaces(operation.get("surfaces"), document)
    except ValueError as exc:
        _fail("invalid_floor_surfaces", str(exc))
    previous = {s["surfaceId"] for s in document.get("extensions", {}).get(KEY, {}).get("surfaces", [])}
    current = {s["surfaceId"] for s in value["surfaces"]}
    document.setdefault("extensions", {})[KEY] = value
    return sorted(current-previous), sorted(current | previous)


def _op_set_interior_walls(document, operation, _index, _base_revision):
    from .interior_walls import compile_interior_walls, KEY
    from .decals import remove_bound_decals
    try:
        value = compile_interior_walls(operation.get("walls"), document)
    except ValueError as exc:
        _fail("invalid_interior_walls", str(exc))
    previous = {w["wallId"] for w in document.get("extensions", {}).get(KEY, {}).get("walls", [])}
    current = {w["wallId"] for w in value["walls"]}
    document.setdefault("extensions", {})[KEY] = value
    remove_bound_decals(document, lambda target: target.get("wallId") in previous-current)
    return sorted(current-previous), sorted(current | previous)


def _edit_collection_row(
    value, collection, operation, *, row_field, identity_field, delete=False,
    derived_fields=(), extra_fields=(),
):
    field = identity_field if delete else row_field
    if set(operation) != {"op", field, *extra_fields}:
        _fail("invalid_operation_field", f"Expected {field} for {operation['op']}.")
    row = None if delete else _mapping(operation[field], field)
    identifier = operation[field] if delete else row.get(identity_field)
    if not isinstance(identifier, str) or not identifier:
        _fail("invalid_operation_field", f"{identity_field} must be a nonempty string.")
    rows = _collection(value, collection)
    target = next((i for i, item in enumerate(rows) if item.get(identity_field) == identifier), None)
    if delete and target is None:
        _fail(
            "operation_target_not_found", f"{identity_field} '{identifier}' was not found.",
            details={"targetId": identifier},
        )
    # Saved geometry is derived; only authored fields may re-enter the setters.
    rows = [{key: item for key, item in record.items() if key not in derived_fields} for record in rows]
    if delete:
        del rows[target]
    elif target is None:
        rows.append(row)
    else:
        rows[target] = row
    value[collection] = rows
    return ([identifier] if target is None else []), [identifier]


def _op_edit_floor_surface_row(document, operation, index, base_revision):
    from .floor_surfaces import KEY
    value = _mapping(document.get("extensions", {}).get(KEY, {"version": 1, "surfaces": []}), KEY)
    result = _edit_collection_row(
        value, "surfaces", operation, row_field="surface", identity_field="surfaceId",
        delete=operation["op"] == "delete_floor_surface",
    )
    _op_set_floor_surfaces(document, {"op": "set_floor_surfaces", "surfaces": value}, index, base_revision)
    return result


def _op_edit_interior_wall_row(document, operation, index, base_revision):
    from .interior_walls import KEY
    from .decals import KEY as DECALS_KEY
    value = _mapping(document.get("extensions", {}).get(KEY, {"version": 1, "walls": []}), KEY)
    created, affected = _edit_collection_row(
        value, "walls", operation, row_field="wall", identity_field="wallId",
        delete=operation["op"] == "delete_interior_wall", derived_fields=("panels",),
    )
    if operation["op"] == "delete_interior_wall":
        affected.extend(
            row["artworkId"] for row in document.get("extensions", {}).get(DECALS_KEY, {}).get("artworks", [])
            if row["target"].get("wallId") == operation["wallId"]
        )
    _op_set_interior_walls(document, {"op": "set_interior_walls", "walls": value}, index, base_revision)
    return created, affected


def _op_set_component_materials(document, operation, _index, _base_revision):
    from .component_materials import normalize_component_materials
    identifier = _clean_id(operation.get("placementId"), "placementId", "pl")
    placement = _find(document, "placements", "placementId", identifier, "Placement")
    if "materials" not in operation:
        _fail("invalid_operation_field", "materials is required; use null to restore originals.")
    if operation["materials"] is None:
        placement.pop("componentMaterials", None)
    else:
        try:
            placement["componentMaterials"] = normalize_component_materials(operation["materials"], document)
        except ValueError as exc:
            _fail("invalid_component_materials", str(exc))
    return [], [identifier]


def _op_set_position_mode(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    placement_id = _clean_id(operation.get("placementId"), "placementId", "pl")
    mode = operation.get("positionMode")
    if mode not in _POSITION_MODES:
        _fail(
            "invalid_operation_field",
            "positionMode must be auto, manual, or locked.",
        )
    placement = _find(
        document,
        "placements",
        "placementId",
        placement_id,
        "Placement",
    )
    placement["positionMode"] = mode
    return [], [placement_id]


def _op_set_snap_relationship(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    placement_id = _clean_id(operation.get("placementId"), "placementId", "pl")
    placement = _find(
        document,
        "placements",
        "placementId",
        placement_id,
        "Placement",
    )
    if placement.get("positionMode") == "locked":
        _fail(
            "locked_placement_movement",
            f"Placement '{placement_id}' is locked.",
        )
    relationship = operation.get("snapRelationship")
    placement["snapRelationship"] = (
        None
        if relationship is None
        else _mapping(relationship, "snapRelationship")
    )
    if operation.get("layoutProvenance") is not None:
        _set_or_stale_layout_provenance(
            placement,
            operation,
            container="metadata",
        )
    return [], [placement_id]


def _apply_seed_layout_provenance(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
) -> List[str]:
    raw_ids = operation.get("layoutProvenanceSeedEntityIds")
    if raw_ids is None:
        return []
    if (
        not isinstance(raw_ids, list)
        or len(raw_ids) > MAX_OPERATION_BATCH
        or any(not isinstance(item, str) or not item for item in raw_ids)
    ):
        _fail(
            "invalid_operation_field",
            "layoutProvenanceSeedEntityIds must be a bounded string array.",
        )
    affected = []
    for entity_id in dict.fromkeys(raw_ids):
        target: Optional[Dict[str, Any]] = None
        container = "metadata"
        for collection, key, candidate_container in (
            ("placements", "placementId", "metadata"),
            ("zones", "zoneId", "extensions"),
        ):
            target = next(
                (
                    item for item in _collection(document, collection)
                    if item.get(key) == entity_id
                ),
                None,
            )
            if target is not None:
                container = candidate_container
                break
        if target is None:
            target = next(
                (
                    item for item in _floor_markings(document)
                    if item.get("markingId") == entity_id
                ),
                None,
            )
        if target is None:
            _fail(
                "operation_target_not_found",
                f"Layout entity '{entity_id}' was not found.",
                details={"targetId": entity_id},
            )
        _set_or_stale_layout_provenance(
            target,
            operation,
            container=container,
        )
        affected.append(entity_id)
    return affected


def _insert_top_level_object(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
    *,
    collection: str,
    value_field: str,
    id_field: str,
    prefix: str,
) -> Tuple[List[str], List[str]]:
    value = _mapping(operation.get(value_field), value_field)
    requested = value.get(id_field, operation.get(id_field))
    if requested is None:
        identity_operation = deepcopy(dict(operation))
        identity_value = deepcopy(value)
        identity_value.pop(id_field, None)
        identity_operation[value_field] = identity_value
        identifier = _deterministic_id(
            document,
            prefix=prefix,
            operation=identity_operation,
            operation_index=index,
            base_revision=base_revision,
        )
    else:
        identifier = _clean_id(requested, id_field, prefix)
    if identifier in _all_object_ids(document):
        _fail("duplicate_id", f"{id_field} '{identifier}' is already in use.")
    value[id_field] = identifier
    _collection(document, collection).append(value)
    return [identifier], [identifier]


def _edit_top_level_object(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    *,
    collection: str,
    id_field: str,
    prefix: str,
    label: str,
) -> Tuple[List[str], List[str]]:
    identifier = _clean_id(operation.get(id_field), id_field, prefix)
    patch = _mapping(operation.get("patch"), "patch")
    if id_field in patch:
        _fail("immutable_identity", f"{operation.get('op')} cannot change {id_field}.")
    target = _find(document, collection, id_field, identifier, label)
    for key, value in patch.items():
        target[str(key)] = deepcopy(value)
    return [], [identifier]


def _op_add_route(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _insert_top_level_object(
        document,
        operation,
        index,
        base_revision,
        collection="routes",
        value_field="route",
        id_field="routeId",
        prefix="rt",
    )


def _aisle_kind(value: Any) -> str:
    if value not in {"forklift", "pedestrian", "material"}:
        _fail(
            "invalid_operation_field",
            "aisleKind must be forklift, pedestrian, or material.",
        )
    return str(value)


def _aisle_direction(value: Any) -> str:
    if value not in {"one_way", "two_way"}:
        _fail(
            "invalid_operation_field",
            "direction must be one_way or two_way.",
        )
    return str(value)


def _aisle_color(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None:
        _fail(
            "invalid_operation_field",
            "color must be a six-digit hex color.",
        )
    return value.lower()


def _aisle_width(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("invalid_operation_field", "corridorWidth must be a number.")
    width = float(value)
    if not 0 < width <= 1000:
        _fail(
            "invalid_operation_field",
            "corridorWidth must be greater than zero and at most 1000 meters.",
        )
    return width


def _aisle_centerline(value: Any) -> List[Dict[str, float]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4096:
        _fail(
            "invalid_operation_field",
            "centerline must contain between 2 and 4096 points.",
        )
    result: List[Dict[str, float]] = []
    for index, raw_point in enumerate(value):
        point = _mapping(raw_point, f"centerline[{index}]")
        if set(point) != {"x", "y", "z"}:
            _fail(
                "invalid_operation_field",
                f"centerline[{index}] must contain x, y, and z.",
            )
        normalized: Dict[str, float] = {}
        for axis in ("x", "y", "z"):
            coordinate = point[axis]
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
                _fail(
                    "invalid_operation_field",
                    f"centerline[{index}].{axis} must be a number.",
                )
            normalized[axis] = float(coordinate)
        result.append(normalized)
    return result


def _aisle_route(
    request: Mapping[str, Any],
    *,
    base_revision: str,
    existing: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    aisle = deepcopy(dict(request))
    current = deepcopy(dict(existing or {}))
    extensions = current.get("extensions")
    existing_extension = (
        extensions.get("facilityAisle")
        if isinstance(extensions, Mapping)
        and isinstance(extensions.get("facilityAisle"), Mapping)
        else {}
    )
    aisle_kind = _aisle_kind(
        aisle.get("aisleKind", existing_extension.get("aisleKind"))
    )
    direction = _aisle_direction(
        aisle.get("direction", existing_extension.get("direction", "two_way"))
    )
    color = _aisle_color(
        aisle.get("color", existing_extension.get("color", "#d9a514"))
    )
    centerline = _aisle_centerline(
        aisle.get("centerline", current.get("centerline"))
    )
    width = _aisle_width(
        aisle.get("corridorWidth", current.get("corridorWidth"))
    )
    label = _clean_label(aisle.get("label", current.get("label")), "label")
    status = aisle.get(
        "clearanceEvidenceStatus",
        existing_extension.get("clearanceEvidenceStatus", "unverified"),
    )
    if status not in {"authored", "derived", "inferred", "unknown", "unverified"}:
        _fail(
            "invalid_operation_field",
            "clearanceEvidenceStatus is unsupported.",
        )
    source_zone_id = aisle.get(
        "sourceZoneId", existing_extension.get("sourceZoneId")
    )
    target_zone_id = aisle.get(
        "targetZoneId", existing_extension.get("targetZoneId")
    )
    via_zone_ids = aisle.get(
        "viaZoneIds", existing_extension.get("viaZoneIds", [])
    )
    area_accounting = aisle.get(
        "areaAccounting", existing_extension.get("areaAccounting", "overlay")
    )
    width_authority = aisle.get(
        "widthAuthority", existing_extension.get("widthAuthority", "unknown")
    )
    obstacle_awareness = aisle.get(
        "obstacleAwareness", existing_extension.get("obstacleAwareness")
    )
    if obstacle_awareness is not None and not isinstance(
        obstacle_awareness, Mapping
    ):
        _fail(
            "invalid_operation_field",
            "obstacleAwareness must be an object.",
        )
    routing_mode = str(
        aisle.get(
            "routingMode",
            current.get(
                "routingMode",
                "vehicle" if aisle_kind == "forklift" else "polyline",
            ),
        )
    )
    if routing_mode not in {"orthogonal", "polyline", "vehicle"}:
        _fail("invalid_operation_field", "routingMode is unsupported.")
    vehicle_profile_ref = aisle.get(
        "vehicleProfileRef", current.get("vehicleProfileRef")
    )
    if vehicle_profile_ref is not None and not isinstance(
        vehicle_profile_ref, Mapping
    ):
        _fail(
            "invalid_operation_field",
            "vehicleProfileRef must be an object.",
        )
    swept_envelope = aisle.get(
        "sweptEnvelope", current.get("sweptEnvelope")
    )
    if swept_envelope is not None and not isinstance(swept_envelope, Mapping):
        _fail("invalid_operation_field", "sweptEnvelope must be an object.")
    if source_zone_id is not None:
        source_zone_id = _clean_id(source_zone_id, "sourceZoneId", "zn")
    if target_zone_id is not None:
        target_zone_id = _clean_id(target_zone_id, "targetZoneId", "zn")
    if not isinstance(via_zone_ids, list):
        _fail("invalid_operation_field", "viaZoneIds must be an array.")
    normalized_via_zone_ids = [
        _clean_id(item, "viaZoneIds", "zn") for item in via_zone_ids
    ]
    if len(set(normalized_via_zone_ids)) != len(normalized_via_zone_ids):
        _fail("invalid_operation_field", "viaZoneIds must be unique.")
    if area_accounting not in {"overlay"}:
        _fail(
            "invalid_operation_field",
            "areaAccounting must be overlay for generated circulation.",
        )
    if width_authority not in {"user_authored", "policy_authored", "unknown"}:
        _fail(
            "invalid_operation_field",
            "widthAuthority is unsupported.",
        )
    route_kind = {
        "forklift": "forklift",
        "pedestrian": "operator",
        "material": "material",
    }[aisle_kind]
    route = {
        "label": label,
        "routeKind": route_kind,
        "sourceEndpoint": {
            "kind": "world_point",
            "position": deepcopy(centerline[0]),
        },
        "targetEndpoint": {
            "kind": "world_point",
            "position": deepcopy(centerline[-1]),
        },
        "routingMode": routing_mode,
        "centerline": centerline,
        "corridorWidth": width,
        "routeFingerprint": "0" * 64,
        "sourceRevisions": deepcopy(
            aisle.get("sourceRevisions")
            if isinstance(aisle.get("sourceRevisions"), Mapping)
            else (
                current.get("sourceRevisions")
                if isinstance(current.get("sourceRevisions"), Mapping)
                else {"layoutBaseRevision": base_revision}
            )
        ),
        "requirements": deepcopy(
            current.get("requirements")
            if isinstance(current.get("requirements"), list)
            else []
        ),
        "evidence": deepcopy(
            current.get("evidence")
            if isinstance(current.get("evidence"), list)
            else []
        ),
        "extensions": {
            "facilityAisle": {
                "schemaVersion": 1,
                "aisleKind": aisle_kind,
                "direction": direction,
                "color": color,
                "clearanceEvidenceStatus": str(status),
                **(
                    {"sourceZoneId": source_zone_id}
                    if source_zone_id is not None
                    else {}
                ),
                **(
                    {"targetZoneId": target_zone_id}
                    if target_zone_id is not None
                    else {}
                ),
                **(
                    {"viaZoneIds": normalized_via_zone_ids}
                    if source_zone_id is not None or target_zone_id is not None
                    else {}
                ),
                **(
                    {
                        "areaAccounting": str(area_accounting),
                        "widthAuthority": str(width_authority),
                    }
                    if source_zone_id is not None or target_zone_id is not None
                    else {}
                ),
                **(
                    {"obstacleAwareness": deepcopy(dict(obstacle_awareness))}
                    if isinstance(obstacle_awareness, Mapping)
                    else {}
                ),
            },
        },
        **(
            {"vehicleProfileRef": deepcopy(dict(vehicle_profile_ref))}
            if isinstance(vehicle_profile_ref, Mapping)
            else {}
        ),
        **(
            {"sweptEnvelope": deepcopy(dict(swept_envelope))}
            if isinstance(swept_envelope, Mapping)
            else {}
        ),
    }
    route["routeFingerprint"] = persisted_route_fingerprint(route)
    return route


def _op_add_aisle(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    route = _aisle_route(
        _mapping(operation.get("aisle"), "aisle"),
        base_revision=base_revision,
    )
    requested = operation.get("routeId")
    if requested is not None:
        route["routeId"] = requested
    return _insert_top_level_object(
        document,
        {"op": "add_route", "route": route},
        index,
        base_revision,
        collection="routes",
        value_field="route",
        id_field="routeId",
        prefix="rt",
    )


def _op_edit_aisle(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    route_id = _clean_id(operation.get("routeId"), "routeId", "rt")
    target = _find(document, "routes", "routeId", route_id, "Route")
    extensions = target.get("extensions")
    if not isinstance(extensions, Mapping) or not isinstance(
        extensions.get("facilityAisle"), Mapping
    ):
        _fail(
            "operation_target_type_mismatch",
            f"Route '{route_id}' is not a facility aisle.",
        )
    rebuilt = _aisle_route(
        _mapping(operation.get("patch"), "patch"),
        base_revision=base_revision,
        existing=target,
    )
    target.clear()
    target.update(rebuilt)
    target["routeId"] = route_id
    return [], [route_id]


def _op_edit_route(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _edit_top_level_object(
        document,
        operation,
        collection="routes",
        id_field="routeId",
        prefix="rt",
        label="Route",
    )


def _op_delete_route(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    route_id = _clean_id(operation.get("routeId"), "routeId", "rt")
    _find(document, "routes", "routeId", route_id, "Route")
    references = sorted(
        str(binding.get("processBindingId") or "processBindings")
        for binding in _collection(document, "processBindings")
        if route_id in (
            binding.get("routeIds")
            if isinstance(binding.get("routeIds"), list)
            else []
        )
    )
    if references:
        _fail(
            "referenced_object_in_use",
            f"Route '{route_id}' is still referenced.",
            details={"targetId": route_id, "references": references},
        )
    document["routes"] = [
        route
        for route in _collection(document, "routes")
        if route.get("routeId") != route_id
    ]
    return [], [route_id]


def _op_add_utility_network(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _insert_top_level_object(
        document,
        operation,
        index,
        base_revision,
        collection="utilityNetworks",
        value_field="utilityNetwork",
        id_field="utilityNetworkId",
        prefix="un",
    )


def _op_edit_utility_network(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _edit_top_level_object(
        document,
        operation,
        collection="utilityNetworks",
        id_field="utilityNetworkId",
        prefix="un",
        label="Utility network",
    )


def _op_delete_utility_network(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    network_id = _clean_id(
        operation.get("utilityNetworkId"),
        "utilityNetworkId",
        "un",
    )
    _find(
        document,
        "utilityNetworks",
        "utilityNetworkId",
        network_id,
        "Utility network",
    )
    document["utilityNetworks"] = [
        network
        for network in _collection(document, "utilityNetworks")
        if network.get("utilityNetworkId") != network_id
    ]
    return [], [network_id]


def _network(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
) -> Tuple[Dict[str, Any], str]:
    network_id = _clean_id(
        operation.get("utilityNetworkId"),
        "utilityNetworkId",
        "un",
    )
    network = _find(
        document,
        "utilityNetworks",
        "utilityNetworkId",
        network_id,
        "Utility network",
    )
    return network, network_id


def _nested_collection(
    network: Dict[str, Any],
    field: str,
) -> List[Dict[str, Any]]:
    value = network.get(field)
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        _fail("invalid_layout_shape", f"utilityNetwork.{field} must be an array.")
    return value


def _find_nested(
    network: Dict[str, Any],
    *,
    collection: str,
    id_field: str,
    identifier: str,
    label: str,
) -> Dict[str, Any]:
    match = next(
        (
            item
            for item in _nested_collection(network, collection)
            if item.get(id_field) == identifier
        ),
        None,
    )
    if match is None:
        _fail(
            "operation_target_not_found",
            f"{label} '{identifier}' was not found.",
            details={"targetId": identifier},
        )
    return match


def _insert_network_object(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
    *,
    collection: str,
    value_field: str,
    id_field: str,
    prefix: str,
) -> Tuple[List[str], List[str]]:
    network, network_id = _network(document, operation)
    value = _mapping(operation.get(value_field), value_field)
    requested = value.get(id_field, operation.get(id_field))
    identifier = (
        _clean_id(requested, id_field, prefix)
        if requested is not None
        else _deterministic_id(
            document,
            prefix=prefix,
            operation=operation,
            operation_index=index,
            base_revision=base_revision,
        )
    )
    if identifier in _all_object_ids(document):
        _fail("duplicate_id", f"{id_field} '{identifier}' is already in use.")
    value[id_field] = identifier
    _nested_collection(network, collection).append(value)
    return [identifier], [network_id, identifier]


def _edit_network_object(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    *,
    collection: str,
    id_field: str,
    prefix: str,
    label: str,
) -> Tuple[List[str], List[str]]:
    network, network_id = _network(document, operation)
    identifier = _clean_id(operation.get(id_field), id_field, prefix)
    patch = _mapping(operation.get("patch"), "patch")
    if id_field in patch:
        _fail("immutable_identity", f"{operation.get('op')} cannot change {id_field}.")
    target = _find_nested(
        network,
        collection=collection,
        id_field=id_field,
        identifier=identifier,
        label=label,
    )
    for key, value in patch.items():
        target[str(key)] = deepcopy(value)
    return [], [network_id, identifier]


def _op_add_utility_network_node(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _insert_network_object(
        document,
        operation,
        index,
        base_revision,
        collection="nodes",
        value_field="node",
        id_field="networkNodeId",
        prefix="nn",
    )


def _op_edit_utility_network_node(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _edit_network_object(
        document,
        operation,
        collection="nodes",
        id_field="networkNodeId",
        prefix="nn",
        label="Utility network node",
    )


def _op_delete_utility_network_node(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    network, network_id = _network(document, operation)
    node_id = _clean_id(
        operation.get("networkNodeId"),
        "networkNodeId",
        "nn",
    )
    _find_nested(
        network,
        collection="nodes",
        id_field="networkNodeId",
        identifier=node_id,
        label="Utility network node",
    )
    references = sorted(
        str(segment.get("networkSegmentId") or "segments")
        for segment in _nested_collection(network, "segments")
        if node_id
        in {
            segment.get("sourceNetworkNodeId"),
            segment.get("targetNetworkNodeId"),
        }
    )
    if references:
        _fail(
            "referenced_object_in_use",
            f"Utility network node '{node_id}' is still referenced.",
            details={"targetId": node_id, "references": references},
        )
    network["nodes"] = [
        node
        for node in _nested_collection(network, "nodes")
        if node.get("networkNodeId") != node_id
    ]
    return [], [network_id, node_id]


def _op_add_utility_network_segment(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _insert_network_object(
        document,
        operation,
        index,
        base_revision,
        collection="segments",
        value_field="segment",
        id_field="networkSegmentId",
        prefix="ns",
    )


def _op_edit_utility_network_segment(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _edit_network_object(
        document,
        operation,
        collection="segments",
        id_field="networkSegmentId",
        prefix="ns",
        label="Utility network segment",
    )


def _op_delete_utility_network_segment(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    network, network_id = _network(document, operation)
    segment_id = _clean_id(
        operation.get("networkSegmentId"),
        "networkSegmentId",
        "ns",
    )
    _find_nested(
        network,
        collection="segments",
        id_field="networkSegmentId",
        identifier=segment_id,
        label="Utility network segment",
    )
    network["segments"] = [
        segment
        for segment in _nested_collection(network, "segments")
        if segment.get("networkSegmentId") != segment_id
    ]
    return [], [network_id, segment_id]


def _op_attach_process_binding(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    index: int,
    base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _insert_top_level_object(
        document,
        operation,
        index,
        base_revision,
        collection="processBindings",
        value_field="processBinding",
        id_field="processBindingId",
        prefix="pb",
    )


def _op_edit_process_binding(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    return _edit_top_level_object(
        document,
        operation,
        collection="processBindings",
        id_field="processBindingId",
        prefix="pb",
        label="Process binding",
    )


def _op_detach_process_binding(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    binding_id = _clean_id(
        operation.get("processBindingId"),
        "processBindingId",
        "pb",
    )
    _find(
        document,
        "processBindings",
        "processBindingId",
        binding_id,
        "Process binding",
    )
    document["processBindings"] = [
        binding
        for binding in _collection(document, "processBindings")
        if binding.get("processBindingId") != binding_id
    ]
    return [], [binding_id]


def _op_set_plan_settings(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    try:
        settings = normalize_plan_settings(
            _mapping(operation.get("planSettings"), "planSettings")
        )
    except ValueError as exc:
        _fail("invalid_operation_field", str(exc))
    extensions = document.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        _fail("invalid_layout_shape", "extensions must be an object.")
    if "facilityGround" in extensions and settings != extensions.get(PLAN_SETTINGS_EXTENSION_KEY):
        previous = extensions.get(PLAN_SETTINGS_EXTENSION_KEY) or {}
        if any(settings[key] != previous.get(key) for key in ("widthMeters", "depthMeters")):
            _fail("explicit_ground_boundary", "This layout has explicit ground levels. Edit their boundaries with set_ground; plan dimensions cannot silently replace them.")
    extensions[PLAN_SETTINGS_EXTENSION_KEY] = settings
    if WALLS_KEY in extensions:
        try:
            extensions[WALLS_KEY] = compile_perimeter_walls(extensions[WALLS_KEY]["settings"], document)
        except ValueError as exc:
            _fail("invalid_perimeter_walls", str(exc))
    return [], []


def _op_set_ground(document, operation, _index, _base_revision):
    from .ground import KEY, normalize_ground
    if set(operation) != {"op", "ground"}:
        _fail("invalid_ground", "Expected ground (or null to restore the plan floor)")
    extensions = document.setdefault("extensions", {})
    if operation["ground"] is None:
        extensions.pop(KEY, None)
    else:
        try:
            extensions[KEY] = normalize_ground(operation["ground"])
        except ValueError as exc:
            _fail("invalid_ground", str(exc))
    return [], []


def _op_set_perimeter_walls(document, operation, _index, _base_revision):
    if "wallSettings" not in operation or set(operation) - {"op", "wallSettings"}:
        _fail("invalid_perimeter_walls", "Expected wallSettings (or null to remove walls)")
    extensions = document.setdefault("extensions", {})
    settings = operation.get("wallSettings")
    if settings is None:
        extensions.pop(WALLS_KEY, None)
        from .decals import remove_bound_decals
        remove_bound_decals(document, lambda target: "edge" in target)
    else:
        try:
            extensions[WALLS_KEY] = compile_perimeter_walls(settings, document)
        except ValueError as exc:
            _fail("invalid_perimeter_walls", str(exc))
    return [], []


def _op_set_decals(document, operation, _index, _base_revision):
    from .decals import KEY, normalize_decals
    if set(operation) != {"op", "decals"}:
        _fail("invalid_decals", "Expected decals")
    try:
        value = normalize_decals(operation["decals"], document)
    except ValueError as exc:
        _fail("invalid_decals", str(exc))
    document.setdefault("extensions", {})[KEY] = value
    return [], []


def _op_set_emergency_plan(document, operation, _index, _base_revision):
    from .emergency_plan import KEY, normalize_emergency_plan
    if set(operation) != {"op", "emergencyPlan"}:
        _fail("invalid_emergency_plan", "Expected emergencyPlan (or null to remove it)")
    extensions = document.setdefault("extensions", {})
    if operation["emergencyPlan"] is None:
        extensions.pop(KEY, None)
        return [], []
    try:
        extensions[KEY] = normalize_emergency_plan(operation["emergencyPlan"], document)
    except ValueError as exc:
        _fail("invalid_emergency_plan", str(exc))
    return [], []


def _op_edit_decal_row(document, operation, index, base_revision):
    from .decals import KEY
    value = _mapping(document.get("extensions", {}).get(KEY, {"version": 1, "artworks": []}), KEY)
    result = _edit_collection_row(
        value, "artworks", operation, row_field="decal", identity_field="artworkId",
        delete=operation["op"] == "delete_decal",
    )
    _op_set_decals(document, {"op": "set_decals", "decals": value}, index, base_revision)
    return result


def _perimeter_settings_for_edit(document):
    value = document.get("extensions", {}).get(WALLS_KEY)
    if value is None:
        _fail("operation_target_not_found", "Perimeter walls were not found.", details={"targetId": WALLS_KEY})
    return _mapping(value.get("settings"), "wallSettings")


def _perimeter_artwork_index(settings):
    finish = settings.get("exteriorFinish", {})
    return {
        row["artworkId"]: (collection, row)
        for collection in ("artworks", "fittedArtworks")
        for row in finish.get(collection, [])
    }


def _op_edit_perimeter_walls(document, operation, index, base_revision):
    if set(operation) != {"op", "patch"}:
        _fail("invalid_operation_field", "Expected patch for edit_perimeter_walls.")
    patch = _mapping(operation["patch"], "patch")
    allowed = {"boundarySource", "boundary", "heightMeters", "thicknessMeters", "openings", "interiorColor", "exteriorFinish"}
    if set(patch) - allowed:
        _fail("invalid_operation_field", "Unsupported perimeter wall patch fields.")
    settings = _perimeter_settings_for_edit(document)
    previous_artworks = _perimeter_artwork_index(settings)
    if "exteriorFinish" in patch:
        finish = _mapping(settings.get("exteriorFinish", {}), "exteriorFinish")
        finish.update(_mapping(patch["exteriorFinish"], "exteriorFinish"))
        patch["exteriorFinish"] = finish
    if patch.get("boundarySource") == "plan" and "boundary" not in patch:
        settings.pop("boundary", None)
    settings.update(patch)
    _op_set_perimeter_walls(document, {"op": "set_perimeter_walls", "wallSettings": settings}, index, base_revision)
    current_artworks = _perimeter_artwork_index(document["extensions"][WALLS_KEY]["settings"])
    affected = {
        identifier for identifier in previous_artworks.keys() | current_artworks.keys()
        if previous_artworks.get(identifier) != current_artworks.get(identifier)
    }
    return sorted(current_artworks.keys() - previous_artworks.keys()), sorted(affected | {str(document["layoutId"])})


def _op_edit_wall_artwork_row(document, operation, index, base_revision):
    collection = operation.get("collection")
    if collection not in ("artworks", "fittedArtworks"):
        _fail("invalid_operation_field", "collection must be artworks or fittedArtworks.")
    settings = _perimeter_settings_for_edit(document)
    if "exteriorFinish" not in settings:
        _fail("operation_target_not_found", "Perimeter exterior finish was not found.", details={"targetId": "exteriorFinish"})
    finish = settings["exteriorFinish"]
    finish.setdefault(collection, [])
    result = _edit_collection_row(
        finish, collection, operation, row_field="artwork", identity_field="artworkId",
        delete=operation["op"] == "delete_wall_artwork", extra_fields=("collection",),
    )
    _op_set_perimeter_walls(document, {"op": "set_perimeter_walls", "wallSettings": settings}, index, base_revision)
    return result


def _navigation_record_ids(value: Any) -> set[str]:
    if not isinstance(value, Mapping):
        return set()
    fields = (
        ("anchors", "navigationAnchorId"),
        ("movementPrograms", "movementProgramId"),
        ("manualPathConstraints", "manualPathConstraintId"),
        ("handoffPrograms", "handoffProgramId"),
    )
    return {
        str(item.get(identity_field))
        for collection, identity_field in fields
        for item in value.get(collection, [])
        if isinstance(item, Mapping) and item.get(identity_field)
    }


def _op_set_facility_navigation(
    document: Dict[str, Any],
    operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    """Replace durable navigation intent from one explicit Plan gesture."""

    unknown = sorted(
        set(operation) - {"op", "facilityNavigation", "authoringSource"}
    )
    if unknown:
        _fail(
            "invalid_operation_field",
            "set_facility_navigation contains unsupported fields.",
            details={"unknownFields": unknown},
        )
    authoring_source = operation.get("authoringSource")
    if authoring_source not in {"plan_pointer", "sage_semantic"}:
        _fail(
            "facility_navigation_coordinate_authority_forbidden",
            "Navigation intent requires the Plan pointer or the coordinate-free Sage semantic surface.",
        )
    requested = operation.get("facilityNavigation")
    identities = navigation_identity_index(document)
    try:
        navigation = canonicalize_facility_navigation_extension(
            requested,
            identities,
        )
        if authoring_source == "plan_pointer":
            validate_navigation_writer_authority(
                navigation,
                identities,
                writer_kind="user",
            )
    except FacilityNavigationContractError as error:
        _fail(error.code, str(error), details=error.details)
    extensions = document.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        _fail("invalid_layout_shape", "extensions must be an object.")
    previous = extensions.get("facilityNavigation")
    if authoring_source == "sage_semantic":
        previous_value = previous if isinstance(previous, Mapping) else {
            "schemaVersion": navigation["schemaVersion"],
            "anchors": [],
            "movementPrograms": [],
            "manualPathConstraints": [],
            "handoffPrograms": [],
        }
        for collection in ("manualPathConstraints", "handoffPrograms"):
            if _canonical_json_bytes(previous_value.get(collection, [])) != (
                _canonical_json_bytes(navigation.get(collection, []))
            ):
                _fail(
                    "facility_navigation_writer_authority_forbidden",
                    "Sage semantic intent cannot create or change path coordinates or handoffs.",
                    details={"collection": collection},
                )
        previous_anchors = {
            str(item.get("navigationAnchorId")): item
            for item in previous_value.get("anchors", [])
            if isinstance(item, Mapping) and item.get("navigationAnchorId")
        }
        next_anchors = {
            str(item.get("navigationAnchorId")): item
            for item in navigation.get("anchors", [])
            if isinstance(item, Mapping) and item.get("navigationAnchorId")
        }
        removed_anchor_ids = sorted(set(previous_anchors) - set(next_anchors))
        changed_anchor_ids = sorted(
            anchor_id
            for anchor_id in set(previous_anchors) & set(next_anchors)
            if _canonical_json_bytes(previous_anchors[anchor_id])
            != _canonical_json_bytes(next_anchors[anchor_id])
        )
        added_anchor_ids = sorted(set(next_anchors) - set(previous_anchors))
        if removed_anchor_ids or changed_anchor_ids or len(added_anchor_ids) > 21:
            _fail(
                "facility_navigation_writer_authority_forbidden",
                "Sage cannot remove or alter existing anchors and may derive at most 21 placement-bound anchors per proposal.",
                details={
                    "removedAnchorIds": removed_anchor_ids,
                    "changedAnchorIds": changed_anchor_ids,
                    "addedAnchorIds": added_anchor_ids,
                },
            )
        placement_revisions = {
            str(item.get("placementId")): str(
                item.get("assetDefinitionRevision") or ""
            )
            for item in document.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        }
        for anchor_id in added_anchor_ids:
            anchor = next_anchors[anchor_id]
            derived = anchor.get("derivedPositionRef")
            owner = anchor.get("ownerRef")
            source_kind = (
                str(derived.get("sourceKind") or "")
                if isinstance(derived, Mapping) else ""
            )
            source_id = (
                str(derived.get("sourceId") or "")
                if isinstance(derived, Mapping) else ""
            )
            expected_kind = (
                "actor_home" if source_kind == "placement_transform"
                else "station_operate"
            )
            if (
                source_kind not in {"placement_transform", "placement_access"}
                or source_id not in placement_revisions
                or str(derived.get("sourceRevision") or "")
                    != placement_revisions[source_id]
                or not isinstance(owner, Mapping)
                or owner.get("ownerKind") != "placement"
                or str(owner.get("ownerId") or "") != source_id
                or anchor.get("anchorKind") != expected_kind
                or anchor.get("positionAuthority") != "derived"
                or anchor.get("localPosition") is not None
                or anchor.get("evidenceStatus") != "derived"
                or anchor.get("reviewStatus") != "pending"
                or anchor.get("actorClasses") != ["pedestrian"]
                or anchor.get("evidence")
                    != ["evidence:deterministic-placement-access-v1"]
            ):
                _fail(
                    "facility_navigation_writer_authority_forbidden",
                    "Sage may add only pending derived pedestrian anchors bound to exact existing placement revisions.",
                    details={"navigationAnchorId": anchor_id},
                )
        previous_programs = {
            str(item.get("movementProgramId")): item
            for item in previous_value.get("movementPrograms", [])
            if isinstance(item, Mapping) and item.get("movementProgramId")
        }
        next_programs = {
            str(item.get("movementProgramId")): item
            for item in navigation.get("movementPrograms", [])
            if isinstance(item, Mapping) and item.get("movementProgramId")
        }
        removed = sorted(set(previous_programs) - set(next_programs))
        changed = sorted(
            program_id
            for program_id, item in next_programs.items()
            if program_id not in previous_programs
            or _canonical_json_bytes(item)
            != _canonical_json_bytes(previous_programs[program_id])
        )
        if removed or len(changed) != 1:
            _fail(
                "facility_navigation_semantic_diff_invalid",
                "One Sage semantic proposal must upsert exactly one movement program and preserve all unrelated programs.",
                details={"removedProgramIds": removed, "changedProgramIds": changed},
            )
        changed_program = next_programs[changed[0]]
        if (
            changed_program.get("evidenceStatus") not in {
                "derived", "inferred", "unknown"
            }
            or changed_program.get("reviewStatus") != "pending"
        ):
            _fail(
                "facility_navigation_writer_authority_forbidden",
                "Sage semantic proposals must remain non-authored and pending review.",
                details={"movementProgramId": changed[0]},
            )
        required_anchor_ids = set(changed_program.get("requiredAnchorIds") or [])
        if not set(added_anchor_ids).issubset(required_anchor_ids):
            _fail(
                "facility_navigation_semantic_diff_invalid",
                "Every newly derived anchor must be used by the one changed movement program.",
                details={
                    "movementProgramId": changed[0],
                    "unusedAnchorIds": sorted(
                        set(added_anchor_ids) - required_anchor_ids
                    ),
                },
            )
    previous_ids = _navigation_record_ids(previous)
    next_ids = _navigation_record_ids(navigation)
    extensions["facilityNavigation"] = navigation
    return sorted(next_ids - previous_ids), sorted(previous_ids | next_ids)


def _op_clear_layout_contents(
    document: Dict[str, Any],
    _operation: Mapping[str, Any],
    _index: int,
    _base_revision: str,
) -> Tuple[List[str], List[str]]:
    """Clear authored spatial contents while preserving document settings."""

    identifier_fields = {
        "zones": "zoneId",
        "floorMarkings": "markingId",
        "placements": "placementId",
        "routes": "routeId",
        "utilityNetworks": "utilityNetworkId",
        "processBindings": "processBindingId",
        "dismissedSuggestions": "suggestionId",
    }
    affected: List[str] = []
    for collection_name, identifier_field in identifier_fields.items():
        values = document.get(collection_name, [])
        if not isinstance(values, list):
            _fail(
                "invalid_layout_shape",
                f"{collection_name} must be an array.",
            )
        affected.extend(
            str(value.get(identifier_field))
            for value in values
            if isinstance(value, Mapping) and value.get(identifier_field)
        )
        document[collection_name] = []
    from .decals import remove_bound_decals
    remove_bound_decals(document, lambda target: "placementId" in target)
    return [], affected


_Handler = Callable[
    [Dict[str, Any], Mapping[str, Any], int, str],
    Tuple[List[str], List[str]],
]

_HANDLERS: Dict[str, _Handler] = {
    "rename_layout": _op_rename_layout,
    "archive_layout": _op_archive_layout,
    "add_zone": _op_add_zone,
    "edit_zone": _op_edit_zone,
    "delete_zone": _op_delete_zone,
    "add_floor_marking": _op_add_floor_marking,
    "add_floor_path": _op_add_floor_path,
    "edit_floor_marking": _op_edit_floor_marking,
    "delete_floor_marking": _op_delete_floor_marking,
    "place_asset": _op_place_asset,
    "place_asset_array": _op_place_asset_array,
    "delete_asset_array": _op_delete_asset_array,
    "move_placement": _op_move_placement,
    "rotate_placement": _op_rotate_placement,
    "duplicate_placement": _op_duplicate_placement,
    "delete_placement": _op_delete_placement,
    "set_position_mode": _op_set_position_mode,
    "set_appearance": _op_set_appearance,
    "set_custom_appearances": _op_set_custom_appearances,
    "set_scene": _op_set_scene,
    "set_site_context": _op_set_site_context,
    "set_building_pose": _op_set_building_pose,
    "upsert_site_area": _op_upsert_site_area,
    "delete_site_area": _op_delete_site_area,
    "upsert_site_reference": _op_upsert_site_reference,
    "delete_site_reference": _op_delete_site_reference,
    "set_equipment_decals": _op_set_equipment_decals,
    "set_component_materials": _op_set_component_materials,
    "set_interior_walls": _op_set_interior_walls,
    "set_floor_surfaces": _op_set_floor_surfaces,
    "upsert_interior_wall": _op_edit_interior_wall_row,
    "delete_interior_wall": _op_edit_interior_wall_row,
    "upsert_floor_surface": _op_edit_floor_surface_row,
    "delete_floor_surface": _op_edit_floor_surface_row,
    "replace_asset": _op_replace_asset,
    "set_snap_relationship": _op_set_snap_relationship,
    "add_route": _op_add_route,
    "add_aisle": _op_add_aisle,
    "edit_aisle": _op_edit_aisle,
    "edit_route": _op_edit_route,
    "delete_route": _op_delete_route,
    "add_utility_network": _op_add_utility_network,
    "edit_utility_network": _op_edit_utility_network,
    "delete_utility_network": _op_delete_utility_network,
    "add_utility_network_node": _op_add_utility_network_node,
    "edit_utility_network_node": _op_edit_utility_network_node,
    "delete_utility_network_node": _op_delete_utility_network_node,
    "add_utility_network_segment": _op_add_utility_network_segment,
    "edit_utility_network_segment": _op_edit_utility_network_segment,
    "delete_utility_network_segment": _op_delete_utility_network_segment,
    "attach_process_binding": _op_attach_process_binding,
    "edit_process_binding": _op_edit_process_binding,
    "detach_process_binding": _op_detach_process_binding,
    "set_plan_settings": _op_set_plan_settings,
    "set_perimeter_walls": _op_set_perimeter_walls,
    "set_decals": _op_set_decals,
    "set_emergency_plan": _op_set_emergency_plan,
    "edit_perimeter_walls": _op_edit_perimeter_walls,
    "upsert_wall_artwork": _op_edit_wall_artwork_row,
    "delete_wall_artwork": _op_edit_wall_artwork_row,
    "upsert_decal": _op_edit_decal_row,
    "delete_decal": _op_edit_decal_row,
    "set_ground": _op_set_ground,
    "set_facility_navigation": _op_set_facility_navigation,
    "clear_layout_contents": _op_clear_layout_contents,
}


def supported_facility_layout_operations() -> Tuple[str, ...]:
    return tuple(sorted(_HANDLERS))


def create_layout_document(
    *,
    layout_id: str,
    display_name: str,
    association: Mapping[str, Any],
    coordinate_frame: Mapping[str, Any],
    source_shell_ref: Mapping[str, Any],
    policy_set_ref: Mapping[str, Any],
    created_at: str,
    updated_at: Optional[str] = None,
    status: str = "draft",
    catalog_snapshot_revision: Optional[str] = None,
    extensions: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct and validate one new, empty layout without external effects."""

    if status not in ("draft", "active", "template"):
        _fail("invalid_operation_field", "New layouts must be draft, active, or template.")
    if not isinstance(created_at, str) or not created_at:
        _fail("invalid_operation_field", "created_at is required.")
    document: Dict[str, Any] = {
        "schemaVersion": 1,
        "layoutId": _clean_id(layout_id, "layoutId", "fl"),
        "displayName": _clean_label(display_name),
        "status": status,
        "association": _mapping(association, "association"),
        "coordinateFrame": _mapping(coordinate_frame, "coordinate_frame"),
        "sourceShellRef": _mapping(source_shell_ref, "source_shell_ref"),
        "policySetRef": _mapping(policy_set_ref, "policy_set_ref"),
        "zones": [],
        "floorMarkings": [],
        "placements": [],
        "routes": [],
        "utilityNetworks": [],
        "processBindings": [],
        "dismissedSuggestions": [],
        "createdAt": created_at,
        "updatedAt": updated_at if updated_at is not None else created_at,
    }
    if catalog_snapshot_revision is not None:
        document["catalogSnapshotRevision"] = catalog_snapshot_revision
    if extensions:
        for key, value in extensions.items():
            if key in document:
                _fail(
                    "reserved_extension_field",
                    f"Extension '{key}' would replace a required layout field.",
                )
            document[str(key)] = deepcopy(value)
    normalized = canonicalize_layout(document)
    _validation_findings(normalized)
    return normalized


def apply_facility_layout_operations(
    layout: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    *,
    base_revision: Optional[str] = None,
    updated_at: Optional[str] = None,
    maximum_operations: int = MAX_OPERATION_BATCH,
) -> Dict[str, Any]:
    """Apply one immutable, all-or-nothing operation batch in memory."""

    if not isinstance(layout, Mapping):
        raise FacilityLayoutOperationError(
            "layout_not_object",
            "layout must be an object.",
        )
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)):
        raise FacilityLayoutOperationError(
            "operations_not_array",
            "operations must be an array.",
        )
    limit = max(1, min(MAX_OPERATION_BATCH, int(maximum_operations)))
    if len(operations) > limit:
        raise FacilityLayoutOperationError(
            "operations_too_large",
            f"An operation batch can contain at most {limit} operations.",
        )

    before = canonicalize_layout(deepcopy(dict(layout)))
    effective_base_revision = base_revision or layout_revision(before)
    after = deepcopy(before)
    created_ids: List[str] = []
    affected_ids: List[str] = []
    operation_results: List[Dict[str, Any]] = []

    if after.get("status") == "archived" and operations:
        raise FacilityLayoutOperationError(
            "archived_layout_read_only",
            "Archived layouts are read-only.",
        )

    normalized_operations: List[Dict[str, Any]] = []
    for index, raw_operation in enumerate(operations):
        if not isinstance(raw_operation, Mapping):
            raise FacilityLayoutOperationError(
                "operation_not_object",
                f"Operation {index} must be an object.",
                operation_index=index,
            )
        operation = deepcopy(dict(raw_operation))
        normalized_operations.append(operation)
        operation_name = operation.get("op")
        handler = _HANDLERS.get(operation_name) if isinstance(operation_name, str) else None
        if handler is None:
            raise FacilityLayoutOperationError(
                "unknown_facility_layout_operation",
                f"Operation {index} has unsupported op '{operation_name}'.",
                operation_index=index,
            )
        if after.get("status") == "archived":
            raise FacilityLayoutOperationError(
                "archived_layout_read_only",
                "Archived layouts are read-only.",
                operation_index=index,
            )
        try:
            created, affected = handler(
                after,
                operation,
                index,
                effective_base_revision,
            )
            affected.extend(_apply_seed_layout_provenance(
                after,
                operation,
            ))
        except FacilityLayoutOperationError as exc:
            if exc.operation_index is None:
                exc.operation_index = index
                exc.details["operationIndex"] = index
            raise
        created_ids.extend(created)
        affected_ids.extend(affected)
        operation_results.append(
            {
                "index": index,
                "op": operation_name,
                "createdIds": sorted(set(created)),
                "affectedIds": sorted(set(affected)),
            }
        )

    after = canonicalize_layout(after)
    content_changed = canonical_layout_bytes(before) != canonical_layout_bytes(after)
    if content_changed and updated_at is not None:
        if not isinstance(updated_at, str) or not updated_at:
            raise FacilityLayoutOperationError(
                "invalid_operation_field",
                "updated_at must be a non-empty string.",
            )
        after["updatedAt"] = updated_at
        after = canonicalize_layout(after)

    findings = _validation_findings(after)
    canonical_diff = build_exact_layout_diff(before, after)
    changed = bool(canonical_diff["changed"])
    diff_hash = facility_layout_diff_hash(
        layout_id=str(after.get("layoutId") or ""),
        base_revision=effective_base_revision,
        operations=normalized_operations,
        after=after,
        canonical_diff=canonical_diff,
    )
    return {
        "schemaVersion": 1,
        "document": after,
        "changed": changed,
        "createdIds": sorted(set(created_ids)),
        "affectedIds": sorted(set(affected_ids)),
        "findings": findings,
        "canonicalDiff": canonical_diff,
        "diffHash": diff_hash,
        "operationResults": operation_results,
    }


def apply_prevalidated_facility_layout_operations(
    layout: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    *,
    base_revision: str,
) -> Dict[str, Any]:
    """Apply one immutable plan batch without repeated whole-layout audits.

    The caller must first validate the complete operation plan and must pass a
    canonical document produced by this kernel. Handlers still validate every
    operation. Full layout validation and the cumulative diff remain required
    after the final batch.
    """

    if not isinstance(layout, Mapping):
        raise FacilityLayoutOperationError(
            "layout_not_object", "layout must be an object."
        )
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)):
        raise FacilityLayoutOperationError(
            "operations_not_array", "operations must be an array."
        )
    if len(operations) > MAX_OPERATION_BATCH:
        raise FacilityLayoutOperationError(
            "operations_too_large",
            f"An operation batch can contain at most {MAX_OPERATION_BATCH} operations.",
        )

    after = deepcopy(dict(layout))
    operation_results: List[Dict[str, Any]] = []
    for index, raw_operation in enumerate(operations):
        if not isinstance(raw_operation, Mapping):
            raise FacilityLayoutOperationError(
                "operation_not_object",
                f"Operation {index} must be an object.",
                operation_index=index,
            )
        operation = deepcopy(dict(raw_operation))
        operation_name = operation.get("op")
        handler = _HANDLERS.get(operation_name) if isinstance(operation_name, str) else None
        if handler is None:
            raise FacilityLayoutOperationError(
                "unknown_facility_layout_operation",
                f"Operation {index} has unsupported op '{operation_name}'.",
                operation_index=index,
            )
        try:
            created, affected = handler(after, operation, index, base_revision)
            affected.extend(_apply_seed_layout_provenance(after, operation))
        except FacilityLayoutOperationError as exc:
            if exc.operation_index is None:
                exc.operation_index = index
                exc.details["operationIndex"] = index
            raise
        operation_results.append(
            {
                "index": index,
                "op": operation_name,
                "createdIds": sorted(set(created)),
                "affectedIds": sorted(set(affected)),
            }
        )

    return {
        "schemaVersion": 1,
        "document": canonicalize_layout(after),
        "operationResults": operation_results,
    }


# Concise alias for callers that already operate inside the Facility Layout domain.
apply_layout_operations = apply_facility_layout_operations
