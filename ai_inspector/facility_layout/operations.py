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
from .validate import validate_layout


MAX_OPERATION_BATCH = 500
_LABEL_LIMIT = 120
_ID_LIMIT = 128
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_POSITION_MODES = frozenset(("auto", "manual", "locked"))
_MOVEMENT_KINDS = frozenset(("user", "automatic"))


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
    if isinstance(value, Mapping):
        if value.get(key) == identifier:
            return True
        return any(_reference_matches(item, key, identifier) for item in value.values())
    if isinstance(value, list):
        return any(_reference_matches(item, key, identifier) for item in value)
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
    _collection(document, "placements").append(placement)
    return [placement_id], [placement_id]


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
    return [], [placement_id]


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
    return [], [placement_id]


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
    "place_asset": _op_place_asset,
    "move_placement": _op_move_placement,
    "rotate_placement": _op_rotate_placement,
    "duplicate_placement": _op_duplicate_placement,
    "delete_placement": _op_delete_placement,
    "set_position_mode": _op_set_position_mode,
    "set_snap_relationship": _op_set_snap_relationship,
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


# Concise alias for callers that already operate inside the Facility Layout domain.
apply_layout_operations = apply_facility_layout_operations
