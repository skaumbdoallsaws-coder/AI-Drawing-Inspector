"""Structural and referential validation for Facility Layout v1."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .canonical import (
    QUATERNION_NORMALIZATION_TOLERANCE,
    _canonical_value_bytes,
    canonicalize_layout,
)
from .errors import FacilityCompatibilityError, FacilityValidationError
from .navigation_contract import (
    navigation_identity_index,
    validate_facility_navigation_extension,
)
from .schema_v1 import (
    FORBIDDEN_LIVE_STATE_FIELDS,
    ID_PREFIXES,
    LIMITS,
    MAXIMUM_ABSOLUTE_WORLD_COORDINATE_METERS,
    MAXIMUM_CANONICAL_DOCUMENT_BYTES,
    MAXIMUM_EXTENSION_FIELDS_PER_OBJECT,
    MAXIMUM_JSON_DEPTH,
    MAXIMUM_TOTAL_EXTENSION_BYTES,
    REQUIRED_LAYOUT_FIELDS,
    REVISION_RE,
    SCHEMA_VERSION,
    STABLE_ID_RE,
)


_LAYOUT_FIELDS = REQUIRED_LAYOUT_FIELDS | {
    "catalogSnapshotRevision",
    "floorMarkings",
    "extensions",
}
_ZONE_FIELDS = {
    "zoneId",
    "zoneType",
    "label",
    "boundary",
    "floorElevation",
    "heightLimit",
    "allowedAssetCategories",
    "gridSpacing",
    "edgeSetbacks",
    "loadLimit",
    "policyRefs",
    "anchors",
    "evidence",
    "extensions",
}
_ANCHOR_FIELDS = {
    "anchorId",
    "anchorKind",
    "position",
    "facing",
    "allowedRouteKinds",
    "evidence",
    "extensions",
}
_PLACEMENT_FIELDS = {
    "appearance",
    "componentMaterials",
    "placementId",
    "assetId",
    "assetDefinitionRevision",
    "transform",
    "positionMode",
    "snapRelationship",
    "metadata",
    "extensions",
}
_FLOOR_MARKING_FIELDS = {
    "markingId",
    "markingType",
    "label",
    "semanticRole",
    "transform",
    "width",
    "depth",
    "fillColor",
    "strokeColor",
    "opacity",
    "text",
    "positionMode",
    "metadata",
    "evidence",
    "extensions",
}
_ROUTE_FIELDS = {
    "routeId",
    "label",
    "routeKind",
    "sourceEndpoint",
    "targetEndpoint",
    "routingMode",
    "centerline",
    "corridorWidth",
    "sweptEnvelope",
    "vehicleProfileRef",
    "routeFingerprint",
    "sourceRevisions",
    "requirements",
    "evidence",
    "extensions",
}
_NETWORK_FIELDS = {
    "utilityNetworkId",
    "networkKind",
    "label",
    "sourceRevisionRefs",
    "nodes",
    "segments",
    "requirements",
    "evidence",
    "extensions",
}
_NETWORK_NODE_FIELDS = {
    "networkNodeId",
    "nodeKind",
    "networkRole",
    "endpointRef",
    "position",
    "extensions",
}
_NETWORK_SEGMENT_FIELDS = {
    "networkSegmentId",
    "sourceNetworkNodeId",
    "targetNetworkNodeId",
    "centerline",
    "interface",
    "capacity",
    "requirements",
    "evidence",
    "extensions",
}
_PROCESS_BINDING_FIELDS = {
    "processBindingId",
    "productId",
    "processMapId",
    "processMapRevision",
    "processNodeIds",
    "processEdgeIds",
    "placementIds",
    "routeIds",
    "bindingRole",
    "extensions",
}


def _fail(code: str, message: str, path: str, **details: Any) -> None:
    payload = {"path": path}
    payload.update(details)
    raise FacilityValidationError(code, message, details=payload)


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_layout_shape", "Expected an object.", path)
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("invalid_layout_shape", "Expected an array.", path)
    return value


def _required(value: Mapping[str, Any], names: Iterable[str], path: str) -> None:
    missing = sorted(set(names) - set(value))
    if missing:
        _fail(
            "invalid_layout_shape",
            "Required fields are missing.",
            path,
            missingFields=missing,
        )


def _closed(value: Mapping[str, Any], names: Iterable[str], path: str) -> None:
    unknown = sorted(set(value) - set(names))
    if unknown:
        _fail(
            "invalid_layout_shape",
            "Closed Facility Layout object contains unknown fields.",
            path,
            unknownFields=unknown,
        )


def _json_tree(value: Any, path: str = "$", depth: int = 1) -> None:
    if depth > MAXIMUM_JSON_DEPTH:
        _fail(
            "document_limit_exceeded",
            "Facility Layout exceeds the maximum JSON depth.",
            path,
            maximumDepth=MAXIMUM_JSON_DEPTH,
        )
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            _fail("non_finite_transform", "Numbers must be finite.", path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_tree(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(
                    "invalid_json_value",
                    "JSON object keys must be strings.",
                    path,
                )
            _json_tree(item, f"{path}.{key}", depth + 1)
        return
    _fail(
        "invalid_json_value",
        "Facility Layout contains a non-JSON value.",
        path,
    )


@dataclass
class _ExtensionBudget:
    total_bytes: int = 0

    def add_open_object(
        self,
        value: Mapping[str, Any],
        known_fields: set[str] | frozenset[str],
        path: str,
    ) -> None:
        unknown = [key for key in value if key not in known_fields]
        explicit_extensions: Mapping[str, Any] = {}
        if "extensions" in value:
            explicit_extensions = _object(value["extensions"], f"{path}.extensions")
        extension_field_count = len(unknown) + len(explicit_extensions)
        if extension_field_count > MAXIMUM_EXTENSION_FIELDS_PER_OBJECT:
            _fail(
                "extension_limit_exceeded",
                "Object has too many extension fields.",
                path,
                maximumFields=MAXIMUM_EXTENSION_FIELDS_PER_OBJECT,
                actualFields=extension_field_count,
            )
        for key in sorted(unknown):
            self.add_value({key: value[key]}, f"{path}.{key}")
        if "extensions" in value:
            self.add_value(explicit_extensions, f"{path}.extensions")

    def add_value(self, value: Any, path: str) -> None:
        self.total_bytes += len(_canonical_value_bytes(value))
        if self.total_bytes > MAXIMUM_TOTAL_EXTENSION_BYTES:
            _fail(
                "extension_limit_exceeded",
                "Facility Layout extension data exceeds its byte budget.",
                path,
                maximumBytes=MAXIMUM_TOTAL_EXTENSION_BYTES,
                actualBytes=self.total_bytes,
            )


def _stable_id(value: Any, path: str, *, prefix: str | None = None) -> str:
    if not isinstance(value, str) or not STABLE_ID_RE.fullmatch(value):
        _fail("invalid_id", "Expected a stable ASCII identifier.", path)
    if prefix is not None and not value.startswith(prefix):
        _fail(
            "invalid_id",
            f"Identifier must start with {prefix}.",
            path,
        )
    return value


def _revision(value: Any, path: str) -> str:
    if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
        _fail("invalid_revision", "Expected a lowercase SHA-256 revision.", path)
    return value


def _string(
    value: Any,
    path: str,
    *,
    minimum: int = 0,
    maximum: int,
) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        _fail(
            "invalid_layout_shape",
            f"Expected a string between {minimum} and {maximum} characters.",
            path,
        )
    return value


def _hex_color(value: Any, path: str) -> str:
    color = _string(value, path, minimum=7, maximum=7)
    if color[0] != "#" or any(
        character not in "0123456789abcdefABCDEF"
        for character in color[1:]
    ):
        _fail(
            "invalid_layout_shape",
            "Expected a six-digit hexadecimal color.",
            path,
        )
    return color


def _number(
    value: Any,
    path: str,
    *,
    minimum: float = -MAXIMUM_ABSOLUTE_WORLD_COORDINATE_METERS,
    maximum: float = MAXIMUM_ABSOLUTE_WORLD_COORDINATE_METERS,
    exclusive_minimum: bool = False,
) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        _fail("non_finite_transform", "Expected a finite number.", path)
    if exclusive_minimum:
        valid_minimum = value > minimum
    else:
        valid_minimum = value >= minimum
    if not valid_minimum or value > maximum:
        _fail(
            "non_finite_transform",
            "Number is outside the supported Facility Layout range.",
            path,
            minimum=minimum,
            maximum=maximum,
        )
    return value


def _vector2(value: Any, path: str) -> Mapping[str, Any]:
    vector = _object(value, path)
    _required(vector, ("x", "z"), path)
    _closed(vector, ("x", "z"), path)
    _number(vector["x"], f"{path}.x")
    _number(vector["z"], f"{path}.z")
    return vector


def _vector3(value: Any, path: str) -> Mapping[str, Any]:
    vector = _object(value, path)
    _required(vector, ("x", "y", "z"), path)
    _closed(vector, ("x", "y", "z"), path)
    _number(vector["x"], f"{path}.x")
    _number(vector["y"], f"{path}.y")
    _number(vector["z"], f"{path}.z")
    return vector


def _unique_array(
    value: Any,
    path: str,
    *,
    maximum: int,
) -> list[Any]:
    items = _array(value, path)
    if len(items) > maximum:
        _fail(
            "document_limit_exceeded",
            "Array exceeds its Facility Layout limit.",
            path,
            maximumItems=maximum,
            actualItems=len(items),
        )
    identities = [_canonical_value_bytes(item) for item in items]
    if len(identities) != len(set(identities)):
        _fail("duplicate_id", "Array values must be unique.", path)
    return items


def _stable_id_array(
    value: Any,
    path: str,
    *,
    maximum: int,
) -> list[str]:
    items = _unique_array(value, path, maximum=maximum)
    for index, item in enumerate(items):
        _stable_id(item, f"{path}[{index}]")
    return items


def _evidence(value: Any, path: str) -> list[str]:
    return _stable_id_array(
        value,
        path,
        maximum=LIMITS["evidencePerTarget"],
    )


def _requirements(
    value: Any,
    path: str,
    extensions: _ExtensionBudget,
) -> list[Any]:
    items = _array(value, path)
    if len(items) > LIMITS["requirementsPerTarget"]:
        _fail(
            "document_limit_exceeded",
            "Requirement list exceeds its target limit.",
            path,
        )
    for index, item in enumerate(items):
        requirement = _object(item, f"{path}[{index}]")
        if len(requirement) > MAXIMUM_EXTENSION_FIELDS_PER_OBJECT:
            _fail(
                "extension_limit_exceeded",
                "Requirement object has too many fields.",
                f"{path}[{index}]",
            )
        extensions.add_value(requirement, f"{path}[{index}]")
    return items


def _mapping_with_max_properties(
    value: Any,
    path: str,
    *,
    maximum: int,
    extensions: _ExtensionBudget | None = None,
) -> Mapping[str, Any]:
    result = _object(value, path)
    if len(result) > maximum:
        _fail(
            "extension_limit_exceeded",
            "Object exceeds its property limit.",
            path,
            maximumProperties=maximum,
            actualProperties=len(result),
        )
    if extensions is not None:
        extensions.add_value(result, path)
    return result


def _surface_attachment_relationship(
    value: Any,
    path: str,
    *,
    placement_id: str,
    placement_ids: set[str],
) -> Mapping[str, Any]:
    relationship = _object(value, path)
    fields = {
        "family",
        "attachmentId",
        "supportPlacementId",
        "surfaceId",
        "side",
        "localPosition",
        "localRotationDegrees",
        "normalOffsetMeters",
        "surfaceSource",
        "evidenceStatus",
    }
    _required(relationship, fields, path)
    _closed(relationship, fields, path)
    if relationship["family"] != "surface_attachment":
        _fail(
            "invalid_layout_shape",
            "Surface attachment family is invalid.",
            f"{path}.family",
        )
    _string(relationship["attachmentId"], f"{path}.attachmentId", minimum=1, maximum=160)
    support_id = _stable_id(
        relationship["supportPlacementId"],
        f"{path}.supportPlacementId",
        prefix=ID_PREFIXES["placementId"],
    )
    if support_id == placement_id:
        _fail(
            "invalid_layout_shape",
            "A placement cannot be attached to itself.",
            f"{path}.supportPlacementId",
        )
    if support_id not in placement_ids:
        _fail(
            "dangling_reference",
            "Surface attachment support does not exist.",
            f"{path}.supportPlacementId",
        )
    _string(relationship["surfaceId"], f"{path}.surfaceId", minimum=1, maximum=120)
    if relationship["side"] not in {"above", "below"}:
        _fail(
            "invalid_layout_shape",
            "Surface attachment side must be above or below.",
            f"{path}.side",
        )
    _vector2(relationship["localPosition"], f"{path}.localPosition")
    _number(
        relationship["localRotationDegrees"],
        f"{path}.localRotationDegrees",
    )
    _number(
        relationship["normalOffsetMeters"],
        f"{path}.normalOffsetMeters",
        minimum=0,
    )
    if relationship["surfaceSource"] not in {"asset_definition", "derived_aabb"}:
        _fail(
            "invalid_layout_shape",
            "Surface attachment source is unsupported.",
            f"{path}.surfaceSource",
        )
    if relationship["evidenceStatus"] not in {
        "authored",
        "derived",
        "inferred",
        "unverified",
        "unknown",
    }:
        _fail(
            "invalid_layout_shape",
            "Surface attachment evidence status is unsupported.",
            f"{path}.evidenceStatus",
        )
    return relationship


def _typed_ids(
    items: Sequence[Mapping[str, Any]],
    key: str,
    path: str,
) -> set[str]:
    result: set[str] = set()
    prefix = ID_PREFIXES[key]
    for index, item in enumerate(items):
        identifier = _stable_id(item.get(key), f"{path}[{index}].{key}", prefix=prefix)
        if identifier in result:
            _fail(
                "duplicate_id",
                f"Duplicate {key}.",
                f"{path}[{index}].{key}",
            )
        result.add(identifier)
    return result


def _ceiling_extension(zone: Mapping[str, Any], path: str) -> None:
    """A zone's ceiling, which lamps hang from ({heightMeters} above its floor, an optional finish), and its roof
    ({heightMeters}): ceilings.py."""
    raw_extensions = zone.get("extensions")
    if not isinstance(raw_extensions, Mapping):
        return
    from .ceilings import normalize_ceiling, normalize_roof
    for key, normalize in (("ceiling", normalize_ceiling), ("roof", normalize_roof)):
        if raw_extensions.get(key) is None:
            continue
        try:
            normalize(raw_extensions[key])
        except ValueError as exc:
            _fail("invalid_layout_shape", str(exc), f"{path}.extensions.{key}")


def _cell_group_extension(zone: Mapping[str, Any], path: str) -> None:
    raw_extensions = zone.get("extensions")
    if raw_extensions is None:
        return
    zone_extensions = _object(raw_extensions, f"{path}.extensions")
    raw_group = zone_extensions.get("cellGroup")
    if raw_group is None:
        return
    group_path = f"{path}.extensions.cellGroup"
    group = _object(raw_group, group_path)
    required_group_fields = {
        "schemaVersion",
        "groupKind",
        "membership",
        "envelopePadding",
        "autoNumber",
    }
    group_fields = required_group_fields | {"functionalInterfaces"}
    _required(group, required_group_fields, group_path)
    _closed(group, group_fields, group_path)
    if group.get("schemaVersion") != 1:
        _fail(
            "invalid_layout_shape",
            "Manufacturing cell schemaVersion must be 1.",
            f"{group_path}.schemaVersion",
        )
    if group.get("groupKind") != "manufacturing_cell":
        _fail(
            "invalid_layout_shape",
            "Cell group kind is unsupported.",
            f"{group_path}.groupKind",
        )
    if group.get("membership") != "geometric":
        _fail(
            "persisted_zone_membership_forbidden",
            "Manufacturing cell membership must be derived geometrically.",
            f"{group_path}.membership",
        )
    _number(group["envelopePadding"], f"{group_path}.envelopePadding", minimum=0)
    auto_path = f"{group_path}.autoNumber"
    auto_number = _object(group["autoNumber"], auto_path)
    auto_fields = {
        "seriesId", "baseName", "prefix", "start", "padding", "sequence",
    }
    _required(auto_number, auto_fields, auto_path)
    _closed(auto_number, auto_fields, auto_path)
    _stable_id(auto_number["seriesId"], f"{auto_path}.seriesId")
    _string(auto_number["baseName"], f"{auto_path}.baseName", minimum=1, maximum=80)
    _string(auto_number["prefix"], f"{auto_path}.prefix", minimum=0, maximum=12)
    for field, maximum in (("start", 999999), ("sequence", 999999)):
        number = _number(
            auto_number[field],
            f"{auto_path}.{field}",
            minimum=0,
            maximum=maximum,
        )
        if not float(number).is_integer():
            _fail(
                "invalid_layout_shape",
                "Cell numbering values must be integers.",
                f"{auto_path}.{field}",
            )
    padding = _number(
        auto_number["padding"],
        f"{auto_path}.padding",
        minimum=1,
        maximum=6,
    )
    if not float(padding).is_integer():
        _fail(
            "invalid_layout_shape",
            "Cell number padding must be an integer.",
            f"{auto_path}.padding",
        )
    if "functionalInterfaces" in group:
        interfaces_path = f"{group_path}.functionalInterfaces"
        interfaces = _object(
            group["functionalInterfaces"], interfaces_path
        )
        interface_roles = {"gate", "loading", "service"}
        _closed(interfaces, interface_roles, interfaces_path)
        for role, raw_interface in interfaces.items():
            interface_path = f"{interfaces_path}.{role}"
            interface = _object(raw_interface, interface_path)
            required_interface_fields = {"evidenceStatus"}
            interface_fields = required_interface_fields | {
                "side",
                "facing",
                "openingWidthMeters",
                "approachDepthMeters",
                "position",
                "accessEnvelope",
            }
            _required(
                interface, required_interface_fields, interface_path
            )
            _closed(interface, interface_fields, interface_path)
            if "side" not in interface and "facing" not in interface:
                _fail(
                    "invalid_layout_shape",
                    "Manufacturing cell interfaces require side or facing.",
                    interface_path,
                )
            if "side" in interface and interface["side"] not in {
                "north", "east", "south", "west",
            }:
                _fail(
                    "invalid_layout_shape",
                    "Manufacturing cell interface side is unsupported.",
                    f"{interface_path}.side",
                )
            if "facing" in interface:
                facing = _vector2(
                    interface["facing"],
                    f"{interface_path}.facing",
                )
                magnitude = math.hypot(
                    float(facing["x"]), float(facing["z"])
                )
                if magnitude <= 1e-9:
                    _fail(
                        "invalid_layout_shape",
                        "Manufacturing cell interface facing cannot be zero.",
                        f"{interface_path}.facing",
                    )
            if interface["evidenceStatus"] not in {
                "authored", "derived", "inferred", "unknown",
            }:
                _fail(
                    "invalid_layout_shape",
                    "Manufacturing cell interface evidence is unsupported.",
                    f"{interface_path}.evidenceStatus",
                )
            for field in ("openingWidthMeters", "approachDepthMeters"):
                if field in interface:
                    _number(
                        interface[field],
                        f"{interface_path}.{field}",
                        minimum=0,
                        exclusive_minimum=True,
                    )
            if "position" in interface:
                _vector2(
                    interface["position"],
                    f"{interface_path}.position",
                )
            if "accessEnvelope" in interface:
                _polygon(
                    interface["accessEnvelope"],
                    f"{interface_path}.accessEnvelope",
                )


def _facility_aisle_extension(route: Mapping[str, Any], path: str) -> None:
    raw_extensions = route.get("extensions")
    if raw_extensions is None:
        return
    route_extensions = _object(raw_extensions, f"{path}.extensions")
    raw_aisle = route_extensions.get("facilityAisle")
    if raw_aisle is None:
        return
    aisle_path = f"{path}.extensions.facilityAisle"
    aisle = _object(raw_aisle, aisle_path)
    fields = {
        "schemaVersion",
        "aisleKind",
        "direction",
        "color",
        "clearanceEvidenceStatus",
        "sourceZoneId",
        "targetZoneId",
        "viaZoneIds",
        "areaAccounting",
        "widthAuthority",
        "obstacleAwareness",
    }
    _required(
        aisle,
        {
            "schemaVersion",
            "aisleKind",
            "direction",
            "color",
            "clearanceEvidenceStatus",
        },
        aisle_path,
    )
    _closed(aisle, fields, aisle_path)
    if aisle.get("schemaVersion") != 1:
        _fail(
            "invalid_layout_shape",
            "Facility aisle schemaVersion must be 1.",
            f"{aisle_path}.schemaVersion",
        )
    if aisle.get("aisleKind") not in {"forklift", "pedestrian", "material"}:
        _fail(
            "invalid_layout_shape",
            "Facility aisle kind is unsupported.",
            f"{aisle_path}.aisleKind",
        )
    if aisle.get("direction") not in {"one_way", "two_way"}:
        _fail(
            "invalid_layout_shape",
            "Facility aisle direction is unsupported.",
            f"{aisle_path}.direction",
        )
    color = _string(aisle["color"], f"{aisle_path}.color", minimum=7, maximum=7)
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", color) is None:
        _fail(
            "invalid_layout_shape",
            "Facility aisle color must be a six-digit hex color.",
            f"{aisle_path}.color",
        )
    if aisle.get("clearanceEvidenceStatus") not in {
        "authored", "derived", "inferred", "unknown", "unverified",
    }:
        _fail(
            "invalid_layout_shape",
            "Facility aisle clearance evidence status is unsupported.",
            f"{aisle_path}.clearanceEvidenceStatus",
        )
    source_zone_id = aisle.get("sourceZoneId")
    target_zone_id = aisle.get("targetZoneId")
    if (source_zone_id is None) != (target_zone_id is None):
        _fail(
            "invalid_layout_shape",
            "Facility aisle sourceZoneId and targetZoneId must be supplied together.",
            aisle_path,
        )
    if source_zone_id is not None:
        _stable_id(
            source_zone_id,
            f"{aisle_path}.sourceZoneId",
            prefix="zn",
        )
        _stable_id(
            target_zone_id,
            f"{aisle_path}.targetZoneId",
            prefix="zn",
        )
        via_zone_ids = _stable_id_array(
            aisle.get("viaZoneIds", []),
            f"{aisle_path}.viaZoneIds",
            maximum=LIMITS["zones"],
        )
        if len(via_zone_ids) != len(set(via_zone_ids)):
            _fail(
                "invalid_layout_shape",
                "Facility aisle viaZoneIds must be unique.",
                f"{aisle_path}.viaZoneIds",
            )
        if aisle.get("areaAccounting") != "overlay":
            _fail(
                "invalid_layout_shape",
                "Generated Facility aisle areaAccounting must be overlay.",
                f"{aisle_path}.areaAccounting",
            )
        if aisle.get("widthAuthority") not in {
            "user_authored",
            "policy_authored",
            "unknown",
        }:
            _fail(
                "invalid_layout_shape",
                "Facility aisle widthAuthority is unsupported.",
                f"{aisle_path}.widthAuthority",
            )
    raw_awareness = aisle.get("obstacleAwareness")
    if raw_awareness is not None:
        awareness_path = f"{aisle_path}.obstacleAwareness"
        awareness = _object(raw_awareness, awareness_path)
        awareness_fields = {
            "schemaVersion",
            "mode",
            "obstacleContextRevision",
            "minimumClearanceMeters",
            "clearanceAuthority",
            "evaluatedObstacleIds",
            "avoidedObstacleIds",
            "vehicleTurningValidated",
        }
        _required(awareness, awareness_fields, awareness_path)
        _closed(awareness, awareness_fields, awareness_path)
        if awareness.get("schemaVersion") != 1:
            _fail(
                "invalid_layout_shape",
                "Obstacle awareness schemaVersion must be 1.",
                f"{awareness_path}.schemaVersion",
            )
        if awareness.get("mode") != "static_geometry":
            _fail(
                "invalid_layout_shape",
                "Obstacle awareness mode is unsupported.",
                f"{awareness_path}.mode",
            )
        _revision(
            awareness.get("obstacleContextRevision"),
            f"{awareness_path}.obstacleContextRevision",
        )
        clearance = _number(
            awareness.get("minimumClearanceMeters"),
            f"{awareness_path}.minimumClearanceMeters",
            minimum=0,
        )
        authority = awareness.get("clearanceAuthority")
        if authority not in {
            "geometric_non_overlap_only",
            "user_authored",
            "policy_authored",
        }:
            _fail(
                "invalid_layout_shape",
                "Obstacle clearance authority is unsupported.",
                f"{awareness_path}.clearanceAuthority",
            )
        if clearance > 0 and authority == "geometric_non_overlap_only":
            _fail(
                "invalid_layout_shape",
                "Positive obstacle clearance requires authored authority.",
                f"{awareness_path}.clearanceAuthority",
            )
        evaluated = _array(
            awareness.get("evaluatedObstacleIds"),
            f"{awareness_path}.evaluatedObstacleIds",
        )
        avoided = _array(
            awareness.get("avoidedObstacleIds"),
            f"{awareness_path}.avoidedObstacleIds",
        )
        if len(evaluated) > LIMITS["floorMarkings"] or len(avoided) > len(evaluated):
            _fail(
                "document_limit_exceeded",
                "Obstacle awareness record count is unsupported.",
                awareness_path,
            )
        for field_name, values in (
            ("evaluatedObstacleIds", evaluated),
            ("avoidedObstacleIds", avoided),
        ):
            for index, value in enumerate(values):
                _stable_id(
                    value,
                    f"{awareness_path}.{field_name}[{index}]",
                )
            if len(values) != len(set(values)):
                _fail(
                    "invalid_layout_shape",
                    "Obstacle awareness IDs must be unique.",
                    f"{awareness_path}.{field_name}",
                )
        if not set(avoided).issubset(set(evaluated)):
            _fail(
                "invalid_layout_shape",
                "Avoided obstacles must be part of the evaluated set.",
                f"{awareness_path}.avoidedObstacleIds",
            )
        if not isinstance(awareness.get("vehicleTurningValidated"), bool):
            _fail(
                "invalid_layout_shape",
                "vehicleTurningValidated must be boolean.",
                f"{awareness_path}.vehicleTurningValidated",
            )


def _polygon(value: Any, path: str) -> list[Any]:
    points = _array(value, path)
    if not 3 <= len(points) <= LIMITS["verticesPerZone"]:
        _fail(
            "invalid_polygon",
            "Zone boundary vertex count is outside the supported range.",
            path,
        )
    for index, point in enumerate(points):
        _vector2(point, f"{path}[{index}]")
    from .canonical import canonicalize_polygon

    canonical = canonicalize_polygon(points, path)
    original_vertices = [(point["x"], point["z"]) for point in points]
    canonical_vertices = [(point["x"], point["z"]) for point in canonical]
    if canonical_vertices != original_vertices:
        _fail(
            "invalid_polygon",
            "Zone boundary is not in canonical counter-clockwise form.",
            path,
        )
    return points


def _quaternion(value: Any, path: str) -> Mapping[str, Any]:
    quaternion = _object(value, path)
    _required(quaternion, ("x", "y", "z", "w"), path)
    _closed(quaternion, ("x", "y", "z", "w"), path)
    components = []
    for key in ("x", "y", "z", "w"):
        components.append(
            _number(
                quaternion[key],
                f"{path}.{key}",
                minimum=-1,
                maximum=1,
            )
        )
    norm = math.sqrt(sum(float(item) ** 2 for item in components))
    if not math.isclose(
        norm,
        1.0,
        rel_tol=0.0,
        abs_tol=QUATERNION_NORMALIZATION_TOLERANCE,
    ):
        _fail(
            "invalid_quaternion",
            "Placement quaternion must have unit length.",
            path,
        )
    sign_probe = [quaternion["w"], quaternion["x"], quaternion["y"], quaternion["z"]]
    first_nonzero = next((item for item in sign_probe if item != 0), 0)
    if first_nonzero < 0:
        _fail(
            "invalid_quaternion",
            "Placement quaternion does not use the canonical sign.",
            path,
        )
    return quaternion


def _endpoint(
    value: Any,
    path: str,
    *,
    layout: Mapping[str, Any],
    placement_ids: set[str],
    zone_anchors: set[tuple[str, str]],
) -> Mapping[str, Any]:
    endpoint = _object(value, path)
    kind = endpoint.get("kind")
    if kind == "placement_connector":
        expected = {"kind", "placementId", "connectorId"}
        _required(endpoint, expected, path)
        _closed(endpoint, expected, path)
        placement_id = _stable_id(endpoint["placementId"], f"{path}.placementId")
        _stable_id(endpoint["connectorId"], f"{path}.connectorId")
        if placement_id not in placement_ids:
            _fail(
                "dangling_placement_endpoint",
                "Route endpoint references an unknown placement.",
                path,
            )
        return endpoint
    if kind == "shell_connector":
        expected = {"kind", "shellId", "shellRevision", "connectorId"}
        _required(endpoint, expected, path)
        _closed(endpoint, expected, path)
        _stable_id(endpoint["shellId"], f"{path}.shellId")
        _revision(endpoint["shellRevision"], f"{path}.shellRevision")
        _stable_id(endpoint["connectorId"], f"{path}.connectorId")
        source_shell = layout["sourceShellRef"]
        if (
            endpoint["shellId"] != source_shell["shellId"]
            or endpoint["shellRevision"] != source_shell["shellRevision"]
        ):
            _fail(
                "shell_endpoint_mismatch",
                "Shell endpoint does not match the layout shell revision.",
                path,
            )
        return endpoint
    if kind == "zone_anchor":
        expected = {"kind", "zoneId", "anchorId"}
        _required(endpoint, expected, path)
        _closed(endpoint, expected, path)
        zone_id = _stable_id(endpoint["zoneId"], f"{path}.zoneId")
        anchor_id = _stable_id(endpoint["anchorId"], f"{path}.anchorId")
        if (zone_id, anchor_id) not in zone_anchors:
            _fail(
                "dangling_zone_anchor",
                "Route endpoint references an unknown qualified zone anchor.",
                path,
            )
        return endpoint
    if kind == "world_point":
        expected = {"kind", "position"}
        _required(endpoint, expected, path)
        _closed(endpoint, expected, path)
        _vector3(endpoint["position"], f"{path}.position")
        return endpoint
    _fail(
        "invalid_layout_shape",
        "Route endpoint kind is unsupported.",
        path,
    )
    raise AssertionError("unreachable")


def _validate_coordinate_frame(value: Any, path: str) -> Mapping[str, Any]:
    frame = _object(value, path)
    expected = {
        "units": "m",
        "handedness": "right",
        "upAxis": "+Y",
        "floorAxes": ["+X", "+Z"],
    }
    _required(
        frame,
        (*expected, "datumId", "floorElevation"),
        path,
    )
    _closed(
        frame,
        (*expected, "datumId", "floorElevation"),
        path,
    )
    if frame.get("units") != "m":
        _fail("unsupported_units", "Facility Layout units must be meters.", path)
    for key, expected_value in expected.items():
        if frame.get(key) != expected_value:
            _fail(
                "invalid_coordinate_frame",
                "Facility Layout coordinate frame is not canonical.",
                f"{path}.{key}",
            )
    _stable_id(frame["datumId"], f"{path}.datumId")
    _number(frame["floorElevation"], f"{path}.floorElevation")
    return frame


def validate_layout(
    document: Mapping[str, Any],
    *,
    require_canonical: bool = False,
) -> Mapping[str, Any]:
    """Validate one native v1 layout and return the unchanged mapping."""

    layout = _object(document, "$")
    _json_tree(layout)
    raw_size = len(_canonical_value_bytes(layout))
    if raw_size > MAXIMUM_CANONICAL_DOCUMENT_BYTES:
        _fail(
            "document_limit_exceeded",
            "Facility Layout exceeds the maximum canonical byte size.",
            "$",
            maximumBytes=MAXIMUM_CANONICAL_DOCUMENT_BYTES,
            actualBytes=raw_size,
        )

    version = layout.get("schemaVersion")
    if isinstance(version, bool) or not isinstance(version, int):
        raise FacilityCompatibilityError(
            "unsupported_schema_version",
            "Facility Layout schemaVersion is unsupported.",
            details={"detectedSchemaVersion": version},
        )
    if version > SCHEMA_VERSION:
        raise FacilityCompatibilityError(
            "unsupported_schema_version_read_only",
            "Newer Facility Layout schemas are read-only.",
            details={"detectedSchemaVersion": version},
        )
    if version != SCHEMA_VERSION:
        raise FacilityCompatibilityError(
            "unsupported_schema_version",
            "Facility Layout schemaVersion is unsupported.",
            details={"detectedSchemaVersion": version},
        )

    _required(layout, REQUIRED_LAYOUT_FIELDS, "$")
    live_fields = sorted(FORBIDDEN_LIVE_STATE_FIELDS & set(layout))
    if live_fields:
        _fail(
            "forbidden_live_state",
            "Camera and live editor state cannot be persisted.",
            "$",
            forbiddenFields=live_fields,
        )

    extensions = _ExtensionBudget()
    extensions.add_open_object(layout, _LAYOUT_FIELDS, "$")

    _stable_id(layout["layoutId"], "$.layoutId", prefix=ID_PREFIXES["layoutId"])
    _string(layout["displayName"], "$.displayName", minimum=1, maximum=120)
    if layout["status"] not in {"draft", "active", "template", "archived"}:
        _fail("invalid_layout_shape", "Layout status is unsupported.", "$.status")

    association = _object(layout["association"], "$.association")
    _required(association, ("siteId",), "$.association")
    _stable_id(association["siteId"], "$.association.siteId")
    if "areaId" in association:
        _stable_id(association["areaId"], "$.association.areaId")
    extensions.add_open_object(
        association,
        {"siteId", "areaId", "extensions"},
        "$.association",
    )

    _validate_coordinate_frame(layout["coordinateFrame"], "$.coordinateFrame")
    source_shell = _object(layout["sourceShellRef"], "$.sourceShellRef")
    shell_fields = {"shellId", "shellRevision", "coordinateFrameFingerprint"}
    _required(source_shell, shell_fields, "$.sourceShellRef")
    _closed(source_shell, shell_fields, "$.sourceShellRef")
    _stable_id(source_shell["shellId"], "$.sourceShellRef.shellId")
    _revision(source_shell["shellRevision"], "$.sourceShellRef.shellRevision")
    _revision(
        source_shell["coordinateFrameFingerprint"],
        "$.sourceShellRef.coordinateFrameFingerprint",
    )

    policy = _object(layout["policySetRef"], "$.policySetRef")
    policy_fields = {"policySetId", "policySetRevision"}
    _required(policy, policy_fields, "$.policySetRef")
    _closed(policy, policy_fields, "$.policySetRef")
    _stable_id(policy["policySetId"], "$.policySetRef.policySetId")
    _revision(policy["policySetRevision"], "$.policySetRef.policySetRevision")
    if "catalogSnapshotRevision" in layout:
        _revision(layout["catalogSnapshotRevision"], "$.catalogSnapshotRevision")

    zones = _array(layout["zones"], "$.zones")
    floor_markings = _array(
        layout.get("floorMarkings", []),
        "$.floorMarkings",
    )
    placements = _array(layout["placements"], "$.placements")
    routes = _array(layout["routes"], "$.routes")
    networks = _array(layout["utilityNetworks"], "$.utilityNetworks")
    bindings = _array(layout["processBindings"], "$.processBindings")
    collection_limits = (
        ("zones", zones),
        ("floorMarkings", floor_markings),
        ("placements", placements),
        ("routes", routes),
        ("utilityNetworks", networks),
        ("processBindings", bindings),
    )
    for field, values in collection_limits:
        if len(values) > LIMITS[field]:
            _fail(
                "document_limit_exceeded",
                f"{field} exceeds its Facility Layout limit.",
                f"$.{field}",
                maximumItems=LIMITS[field],
                actualItems=len(values),
            )
        for index, value in enumerate(values):
            _object(value, f"$.{field}[{index}]")

    zone_ids = _typed_ids(zones, "zoneId", "$.zones")
    floor_marking_ids = _typed_ids(
        floor_markings,
        "markingId",
        "$.floorMarkings",
    )
    placement_ids = _typed_ids(placements, "placementId", "$.placements")
    route_ids = _typed_ids(routes, "routeId", "$.routes")
    network_ids = _typed_ids(
        networks,
        "utilityNetworkId",
        "$.utilityNetworks",
    )
    binding_ids = _typed_ids(
        bindings,
        "processBindingId",
        "$.processBindings",
    )
    top_level_ids = [
        zone_ids,
        floor_marking_ids,
        placement_ids,
        route_ids,
        network_ids,
        binding_ids,
    ]
    if len(set().union(*top_level_ids)) != sum(len(items) for items in top_level_ids):
        _fail("duplicate_id", "Top-level Facility Layout IDs must be unique.", "$")

    zone_anchors: set[tuple[str, str]] = set()
    total_vertices = 0
    total_anchors = 0
    zone_types = {
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
    route_kinds = {"material", "operator", "forklift", "conveyor"}
    for zone_index, raw_zone in enumerate(zones):
        path = f"$.zones[{zone_index}]"
        zone = _object(raw_zone, path)
        required = {
            "zoneId",
            "zoneType",
            "label",
            "boundary",
            "floorElevation",
            "anchors",
            "evidence",
        }
        _required(zone, required, path)
        extensions.add_open_object(zone, _ZONE_FIELDS, path)
        _cell_group_extension(zone, path)
        _ceiling_extension(zone, path)
        if zone["zoneType"] not in zone_types:
            _fail("invalid_layout_shape", "Zone type is unsupported.", f"{path}.zoneType")
        _string(zone["label"], f"{path}.label", minimum=1, maximum=120)
        boundary = _polygon(zone["boundary"], f"{path}.boundary")
        total_vertices += len(boundary)
        _number(zone["floorElevation"], f"{path}.floorElevation")
        if "heightLimit" in zone:
            _number(zone["heightLimit"], f"{path}.heightLimit", minimum=0)
        if "gridSpacing" in zone:
            _number(
                zone["gridSpacing"],
                f"{path}.gridSpacing",
                minimum=0,
                exclusive_minimum=True,
            )
        if "allowedAssetCategories" in zone:
            _stable_id_array(
                zone["allowedAssetCategories"],
                f"{path}.allowedAssetCategories",
                maximum=64,
            )
        if "policyRefs" in zone:
            _stable_id_array(zone["policyRefs"], f"{path}.policyRefs", maximum=64)
        if "edgeSetbacks" in zone:
            setbacks = _mapping_with_max_properties(
                zone["edgeSetbacks"],
                f"{path}.edgeSetbacks",
                maximum=16,
            )
            for key, value in setbacks.items():
                _number(value, f"{path}.edgeSetbacks.{key}", minimum=0)
        if "loadLimit" in zone:
            _mapping_with_max_properties(
                zone["loadLimit"],
                f"{path}.loadLimit",
                maximum=16,
                extensions=extensions,
            )
        _evidence(zone["evidence"], f"{path}.evidence")

        anchors = _array(zone["anchors"], f"{path}.anchors")
        if len(anchors) > LIMITS["anchorsPerZone"]:
            _fail(
                "document_limit_exceeded",
                "Zone has too many anchors.",
                f"{path}.anchors",
            )
        total_anchors += len(anchors)
        local_anchor_ids: set[str] = set()
        for anchor_index, raw_anchor in enumerate(anchors):
            anchor_path = f"{path}.anchors[{anchor_index}]"
            anchor = _object(raw_anchor, anchor_path)
            required_anchor = {
                "anchorId",
                "anchorKind",
                "position",
                "facing",
                "allowedRouteKinds",
                "evidence",
            }
            _required(anchor, required_anchor, anchor_path)
            extensions.add_open_object(anchor, _ANCHOR_FIELDS, anchor_path)
            anchor_id = _stable_id(
                anchor["anchorId"],
                f"{anchor_path}.anchorId",
                prefix=ID_PREFIXES["anchorId"],
            )
            if anchor_id in local_anchor_ids:
                _fail("duplicate_id", "Duplicate zone anchor ID.", anchor_path)
            local_anchor_ids.add(anchor_id)
            if anchor["anchorKind"] not in route_kinds:
                _fail(
                    "invalid_layout_shape",
                    "Zone anchor kind is unsupported.",
                    f"{anchor_path}.anchorKind",
                )
            _vector3(anchor["position"], f"{anchor_path}.position")
            _vector3(anchor["facing"], f"{anchor_path}.facing")
            allowed = _unique_array(
                anchor["allowedRouteKinds"],
                f"{anchor_path}.allowedRouteKinds",
                maximum=4,
            )
            if any(item not in route_kinds for item in allowed):
                _fail(
                    "invalid_layout_shape",
                    "Zone anchor allows an unsupported route kind.",
                    f"{anchor_path}.allowedRouteKinds",
                )
            _evidence(anchor["evidence"], f"{anchor_path}.evidence")
            zone_anchors.add((zone["zoneId"], anchor_id))

    if total_vertices > LIMITS["totalZoneVertices"]:
        _fail(
            "document_limit_exceeded",
            "Total zone vertices exceed the document limit.",
            "$.zones",
        )
    if total_anchors > LIMITS["totalZoneAnchors"]:
        _fail(
            "document_limit_exceeded",
            "Total zone anchors exceed the document limit.",
            "$.zones",
        )

    marking_types = {
        "direction_arrow",
        "solid_line",
        "dashed_line",
        "keep_clear",
        "crosswalk",
        "hazard_stripe",
        "floor_text",
        "parking_box",
    }
    semantic_roles = {
        "decorative",
        "pedestrian_lane",
        "forklift_lane",
        "material_flow",
        "keep_clear",
        "staging",
        "safety",
        "parking",
    }
    for marking_index, raw_marking in enumerate(floor_markings):
        path = f"$.floorMarkings[{marking_index}]"
        marking = _object(raw_marking, path)
        required = {
            "markingId",
            "markingType",
            "label",
            "semanticRole",
            "transform",
            "width",
            "depth",
            "fillColor",
            "strokeColor",
            "opacity",
            "text",
            "positionMode",
            "metadata",
            "evidence",
        }
        _required(marking, required, path)
        extensions.add_open_object(marking, _FLOOR_MARKING_FIELDS, path)
        _stable_id(
            marking["markingId"],
            f"{path}.markingId",
            prefix=ID_PREFIXES["markingId"],
        )
        if marking["markingType"] not in marking_types:
            _fail(
                "invalid_layout_shape",
                "Floor marking type is unsupported.",
                f"{path}.markingType",
            )
        _string(marking["label"], f"{path}.label", minimum=1, maximum=120)
        if marking["semanticRole"] not in semantic_roles:
            _fail(
                "invalid_layout_shape",
                "Floor marking semantic role is unsupported.",
                f"{path}.semanticRole",
            )
        transform = _object(marking["transform"], f"{path}.transform")
        transform_fields = {"position", "rotationDegrees"}
        _required(transform, transform_fields, f"{path}.transform")
        _closed(transform, transform_fields, f"{path}.transform")
        _vector3(transform["position"], f"{path}.transform.position")
        _number(
            transform["rotationDegrees"],
            f"{path}.transform.rotationDegrees",
            minimum=-360_000,
            maximum=360_000,
        )
        _number(
            marking["width"],
            f"{path}.width",
            minimum=0,
            exclusive_minimum=True,
        )
        _number(
            marking["depth"],
            f"{path}.depth",
            minimum=0,
            exclusive_minimum=True,
        )
        _hex_color(marking["fillColor"], f"{path}.fillColor")
        _hex_color(marking["strokeColor"], f"{path}.strokeColor")
        _number(marking["opacity"], f"{path}.opacity", minimum=0, maximum=1)
        _string(marking["text"], f"{path}.text", maximum=120)
        if marking["markingType"] == "floor_text" and not marking["text"]:
            _fail(
                "invalid_layout_shape",
                "Floor text markings require text.",
                f"{path}.text",
            )
        if marking["positionMode"] not in {"auto", "manual", "locked"}:
            _fail(
                "invalid_layout_shape",
                "Floor marking position mode is unsupported.",
                f"{path}.positionMode",
            )
        _mapping_with_max_properties(
            marking["metadata"],
            f"{path}.metadata",
            maximum=32,
            extensions=extensions,
        )
        _evidence(marking["evidence"], f"{path}.evidence")

    for placement_index, raw_placement in enumerate(placements):
        path = f"$.placements[{placement_index}]"
        placement = _object(raw_placement, path)
        required = {
            "placementId",
            "assetId",
            "assetDefinitionRevision",
            "transform",
            "positionMode",
            "snapRelationship",
            "metadata",
        }
        _required(placement, required, path)
        if "zoneId" in placement:
            _fail(
                "persisted_zone_membership_forbidden",
                "Zone membership is computed at runtime.",
                f"{path}.zoneId",
            )
        if "processBindings" in placement:
            _fail(
                "placement_binding_dual_write_forbidden",
                "Process bindings cannot be duplicated on placements.",
                f"{path}.processBindings",
            )
        extensions.add_open_object(placement, _PLACEMENT_FIELDS, path)
        if "appearance" in placement:
            appearance = _object(placement["appearance"], f"{path}.appearance")
            if "appearanceId" not in appearance:
                _required(appearance, {"color"}, f"{path}.appearance")
                _closed(appearance, {"color"}, f"{path}.appearance")
                color = appearance["color"]
                if not isinstance(color, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
                    _fail("invalid_appearance", "Appearance color must be a six-digit hex color.",
                          f"{path}.appearance.color")
            else:
                from .appearance_library import normalize_appearance
                try:
                    normalize_appearance(appearance, layout)
                except ValueError as exc:
                    _fail("invalid_appearance", str(exc), f"{path}.appearance")
        if "componentMaterials" in placement:
            from .component_materials import normalize_component_materials
            try:
                normalize_component_materials(placement["componentMaterials"], layout)
            except ValueError as exc:
                _fail("invalid_component_materials", str(exc), f"{path}.componentMaterials")
        _stable_id(placement["assetId"], f"{path}.assetId")
        _revision(
            placement["assetDefinitionRevision"],
            f"{path}.assetDefinitionRevision",
        )
        transform = _object(placement["transform"], f"{path}.transform")
        transform_fields = {"position", "quaternion", "scale"}
        _required(transform, transform_fields, f"{path}.transform")
        _closed(transform, transform_fields, f"{path}.transform")
        _vector3(transform["position"], f"{path}.transform.position")
        _quaternion(transform["quaternion"], f"{path}.transform.quaternion")
        if isinstance(transform["scale"], bool) or transform["scale"] != 1:
            _fail(
                "unsupported_scale",
                "Facility Layout placement scale must equal one.",
                f"{path}.transform.scale",
            )
        if placement["positionMode"] not in {"auto", "manual", "locked"}:
            _fail(
                "invalid_layout_shape",
                "Placement position mode is unsupported.",
                f"{path}.positionMode",
            )
        if placement["snapRelationship"] is not None:
            relationship = _mapping_with_max_properties(
                placement["snapRelationship"],
                f"{path}.snapRelationship",
                maximum=16,
                extensions=extensions,
            )
            if relationship.get("family") == "surface_attachment":
                _surface_attachment_relationship(
                    relationship,
                    f"{path}.snapRelationship",
                    placement_id=str(placement["placementId"]),
                    placement_ids=placement_ids,
                )
            elif relationship.get("family") == "wall_attachment":
                from .wall_attachments import validate_relationship
                try:
                    validate_relationship(relationship)
                except ValueError as exc:
                    _fail("invalid_layout_shape", str(exc), f"{path}.snapRelationship")
        _mapping_with_max_properties(
            placement["metadata"],
            f"{path}.metadata",
            maximum=32,
            extensions=extensions,
        )

    total_route_points = 0
    for route_index, raw_route in enumerate(routes):
        path = f"$.routes[{route_index}]"
        route = _object(raw_route, path)
        required = {
            "routeId",
            "routeKind",
            "sourceEndpoint",
            "targetEndpoint",
            "routingMode",
            "centerline",
            "corridorWidth",
            "routeFingerprint",
            "sourceRevisions",
            "requirements",
            "evidence",
        }
        _required(route, required, path)
        extensions.add_open_object(route, _ROUTE_FIELDS, path)
        if "label" in route:
            _string(route["label"], f"{path}.label", minimum=1, maximum=120)
        _facility_aisle_extension(route, path)
        if route["routeKind"] not in route_kinds:
            _fail("invalid_layout_shape", "Route kind is unsupported.", f"{path}.routeKind")
        _endpoint(
            route["sourceEndpoint"],
            f"{path}.sourceEndpoint",
            layout=layout,
            placement_ids=placement_ids,
            zone_anchors=zone_anchors,
        )
        _endpoint(
            route["targetEndpoint"],
            f"{path}.targetEndpoint",
            layout=layout,
            placement_ids=placement_ids,
            zone_anchors=zone_anchors,
        )
        if route["routingMode"] not in {"orthogonal", "polyline", "vehicle"}:
            _fail(
                "invalid_layout_shape",
                "Routing mode is unsupported.",
                f"{path}.routingMode",
            )
        centerline = _array(route["centerline"], f"{path}.centerline")
        if not 2 <= len(centerline) <= LIMITS["pointsPerRoute"]:
            _fail(
                "document_limit_exceeded",
                "Route centerline point count is unsupported.",
                f"{path}.centerline",
            )
        total_route_points += len(centerline)
        for point_index, point in enumerate(centerline):
            _vector3(point, f"{path}.centerline[{point_index}]")
        _number(route["corridorWidth"], f"{path}.corridorWidth", minimum=0)
        if "sweptEnvelope" in route:
            _mapping_with_max_properties(
                route["sweptEnvelope"],
                f"{path}.sweptEnvelope",
                maximum=32,
                extensions=extensions,
            )
        if "vehicleProfileRef" in route:
            vehicle = _object(route["vehicleProfileRef"], f"{path}.vehicleProfileRef")
            fields = {"vehicleProfileId", "vehicleProfileRevision"}
            _required(vehicle, fields, f"{path}.vehicleProfileRef")
            _closed(vehicle, fields, f"{path}.vehicleProfileRef")
            _stable_id(
                vehicle["vehicleProfileId"],
                f"{path}.vehicleProfileRef.vehicleProfileId",
            )
            _revision(
                vehicle["vehicleProfileRevision"],
                f"{path}.vehicleProfileRef.vehicleProfileRevision",
            )
        _revision(route["routeFingerprint"], f"{path}.routeFingerprint")
        source_revisions = _mapping_with_max_properties(
            route["sourceRevisions"],
            f"{path}.sourceRevisions",
            maximum=64,
        )
        for key, revision in source_revisions.items():
            _revision(revision, f"{path}.sourceRevisions.{key}")
        _requirements(route["requirements"], f"{path}.requirements", extensions)
        _evidence(route["evidence"], f"{path}.evidence")
    if total_route_points > LIMITS["totalRoutePoints"]:
        _fail(
            "document_limit_exceeded",
            "Total route points exceed the document limit.",
            "$.routes",
        )

    total_network_nodes = 0
    total_network_segments = 0
    total_utility_points = 0
    network_kinds = {
        "electrical",
        "compressed_air",
        "water",
        "exhaust",
        "network",
        "gas",
        "drain",
    }
    for network_index, raw_network in enumerate(networks):
        path = f"$.utilityNetworks[{network_index}]"
        network = _object(raw_network, path)
        required = {
            "utilityNetworkId",
            "networkKind",
            "label",
            "sourceRevisionRefs",
            "nodes",
            "segments",
            "requirements",
            "evidence",
        }
        _required(network, required, path)
        extensions.add_open_object(network, _NETWORK_FIELDS, path)
        if network["networkKind"] not in network_kinds:
            _fail(
                "invalid_layout_shape",
                "Utility network kind is unsupported.",
                f"{path}.networkKind",
            )
        _string(network["label"], f"{path}.label", minimum=1, maximum=120)
        source_refs = _mapping_with_max_properties(
            network["sourceRevisionRefs"],
            f"{path}.sourceRevisionRefs",
            maximum=64,
        )
        for key, revision in source_refs.items():
            _revision(revision, f"{path}.sourceRevisionRefs.{key}")

        nodes = _array(network["nodes"], f"{path}.nodes")
        segments = _array(network["segments"], f"{path}.segments")
        if len(nodes) > LIMITS["nodesPerUtilityNetwork"]:
            _fail("document_limit_exceeded", "Utility network has too many nodes.", f"{path}.nodes")
        if len(segments) > LIMITS["segmentsPerUtilityNetwork"]:
            _fail(
                "document_limit_exceeded",
                "Utility network has too many segments.",
                f"{path}.segments",
            )
        total_network_nodes += len(nodes)
        total_network_segments += len(segments)
        for index, node in enumerate(nodes):
            _object(node, f"{path}.nodes[{index}]")
        for index, segment in enumerate(segments):
            _object(segment, f"{path}.segments[{index}]")
        node_ids = _typed_ids(nodes, "networkNodeId", f"{path}.nodes")
        _typed_ids(segments, "networkSegmentId", f"{path}.segments")
        for node_index, raw_node in enumerate(nodes):
            node_path = f"{path}.nodes[{node_index}]"
            node = _object(raw_node, node_path)
            _required(node, ("networkNodeId", "nodeKind", "networkRole"), node_path)
            extensions.add_open_object(node, _NETWORK_NODE_FIELDS, node_path)
            if node["nodeKind"] == "endpoint":
                _required(node, ("endpointRef",), node_path)
                if node["networkRole"] not in {"supply", "sink"}:
                    _fail(
                        "invalid_layout_shape",
                        "Utility endpoint role must be supply or sink.",
                        f"{node_path}.networkRole",
                    )
                if "position" in node:
                    _fail(
                        "invalid_layout_shape",
                        "Utility endpoint nodes cannot persist free positions.",
                        f"{node_path}.position",
                    )
                _endpoint(
                    node["endpointRef"],
                    f"{node_path}.endpointRef",
                    layout=layout,
                    placement_ids=placement_ids,
                    zone_anchors=zone_anchors,
                )
            elif node["nodeKind"] == "junction":
                _required(node, ("position",), node_path)
                if node["networkRole"] != "junction":
                    _fail(
                        "invalid_layout_shape",
                        "Utility junction role must be junction.",
                        f"{node_path}.networkRole",
                    )
                if "endpointRef" in node:
                    _fail(
                        "invalid_layout_shape",
                        "Utility junction nodes cannot persist endpoint references.",
                        f"{node_path}.endpointRef",
                    )
                _vector3(node["position"], f"{node_path}.position")
            else:
                _fail(
                    "invalid_layout_shape",
                    "Utility node kind is unsupported.",
                    f"{node_path}.nodeKind",
                )

        for segment_index, raw_segment in enumerate(segments):
            segment_path = f"{path}.segments[{segment_index}]"
            segment = _object(raw_segment, segment_path)
            required_segment = {
                "networkSegmentId",
                "sourceNetworkNodeId",
                "targetNetworkNodeId",
                "centerline",
                "interface",
                "capacity",
                "requirements",
                "evidence",
            }
            _required(segment, required_segment, segment_path)
            extensions.add_open_object(
                segment,
                _NETWORK_SEGMENT_FIELDS,
                segment_path,
            )
            for field in ("sourceNetworkNodeId", "targetNetworkNodeId"):
                node_id = _stable_id(segment[field], f"{segment_path}.{field}")
                if node_id not in node_ids:
                    _fail(
                        "dangling_network_node",
                        "Utility segment references an unknown network node.",
                        f"{segment_path}.{field}",
                    )
            centerline = _array(segment["centerline"], f"{segment_path}.centerline")
            if not 2 <= len(centerline) <= LIMITS["pointsPerUtilitySegment"]:
                _fail(
                    "document_limit_exceeded",
                    "Utility segment centerline point count is unsupported.",
                    f"{segment_path}.centerline",
                )
            total_utility_points += len(centerline)
            for point_index, point in enumerate(centerline):
                _vector3(
                    point,
                    f"{segment_path}.centerline[{point_index}]",
                )
            _mapping_with_max_properties(
                segment["interface"],
                f"{segment_path}.interface",
                maximum=32,
                extensions=extensions,
            )
            _mapping_with_max_properties(
                segment["capacity"],
                f"{segment_path}.capacity",
                maximum=32,
                extensions=extensions,
            )
            _requirements(
                segment["requirements"],
                f"{segment_path}.requirements",
                extensions,
            )
            _evidence(segment["evidence"], f"{segment_path}.evidence")
        _requirements(network["requirements"], f"{path}.requirements", extensions)
        _evidence(network["evidence"], f"{path}.evidence")

    if total_network_nodes > LIMITS["totalUtilityNodes"]:
        _fail(
            "document_limit_exceeded",
            "Total utility nodes exceed the document limit.",
            "$.utilityNetworks",
        )
    if total_network_segments > LIMITS["totalUtilitySegments"]:
        _fail(
            "document_limit_exceeded",
            "Total utility segments exceed the document limit.",
            "$.utilityNetworks",
        )
    if total_utility_points > LIMITS["totalUtilityPoints"]:
        _fail(
            "document_limit_exceeded",
            "Total utility points exceed the document limit.",
            "$.utilityNetworks",
        )

    binding_roles = {
        "resource",
        "material_flow",
        "operator_flow",
        "inspection",
        "storage",
        "staging",
    }
    for binding_index, raw_binding in enumerate(bindings):
        path = f"$.processBindings[{binding_index}]"
        binding = _object(raw_binding, path)
        required = {
            "processBindingId",
            "productId",
            "processMapId",
            "processMapRevision",
            "processNodeIds",
            "processEdgeIds",
            "placementIds",
            "routeIds",
            "bindingRole",
        }
        _required(binding, required, path)
        extensions.add_open_object(binding, _PROCESS_BINDING_FIELDS, path)
        _stable_id(binding["productId"], f"{path}.productId")
        _stable_id(binding["processMapId"], f"{path}.processMapId")
        _revision(binding["processMapRevision"], f"{path}.processMapRevision")
        _stable_id_array(
            binding["processNodeIds"],
            f"{path}.processNodeIds",
            maximum=5000,
        )
        _stable_id_array(
            binding["processEdgeIds"],
            f"{path}.processEdgeIds",
            maximum=5000,
        )
        bound_placements = _stable_id_array(
            binding["placementIds"],
            f"{path}.placementIds",
            maximum=5000,
        )
        for placement_id in bound_placements:
            if placement_id not in placement_ids:
                _fail(
                    "dangling_process_binding_placement",
                    "Process binding references an unknown placement.",
                    f"{path}.placementIds",
                )
        bound_routes = _stable_id_array(
            binding["routeIds"],
            f"{path}.routeIds",
            maximum=2000,
        )
        for route_id in bound_routes:
            if route_id not in route_ids:
                _fail(
                    "dangling_process_binding_route",
                    "Process binding references an unknown route.",
                    f"{path}.routeIds",
                )
        if binding["bindingRole"] not in binding_roles:
            _fail(
                "invalid_layout_shape",
                "Process binding role is unsupported.",
                f"{path}.bindingRole",
            )

    _stable_id_array(
        layout["dismissedSuggestions"],
        "$.dismissedSuggestions",
        maximum=LIMITS["dismissedSuggestions"],
    )
    _string(layout["createdAt"], "$.createdAt", minimum=1, maximum=64)
    _string(layout["updatedAt"], "$.updatedAt", minimum=1, maximum=64)

    root_extensions = layout.get("extensions")
    if isinstance(root_extensions, Mapping) and "facilityGround" in root_extensions:
        from .ground import normalize_ground
        try:
            normalize_ground(root_extensions["facilityGround"])
        except ValueError as exc:
            _fail("invalid_ground", str(exc), "$.extensions.facilityGround")
    if isinstance(root_extensions, Mapping) and "facilityPerimeterWalls" in root_extensions:
        from .perimeter_walls import validate_perimeter_walls
        try:
            validate_perimeter_walls(layout)
        except ValueError as exc:
            _fail("invalid_perimeter_walls", str(exc), "$.extensions.facilityPerimeterWalls")
    if isinstance(root_extensions, Mapping) and "facilityInteriorWalls" in root_extensions:
        from .interior_walls import validate_interior_walls
        try:
            validate_interior_walls(layout)
        except ValueError as exc:
            _fail("invalid_interior_walls", str(exc), "$.extensions.facilityInteriorWalls")
    if isinstance(root_extensions, Mapping) and "facilityFloorSurfaces" in root_extensions:
        from .floor_surfaces import normalize_floor_surfaces
        try:
            normalize_floor_surfaces(root_extensions["facilityFloorSurfaces"], layout)
        except ValueError as exc:
            _fail("invalid_floor_surfaces", str(exc), "$.extensions.facilityFloorSurfaces")
    if isinstance(root_extensions, Mapping) and "facilityDecals" in root_extensions:
        from .decals import normalize_decals
        try:
            normalize_decals(root_extensions["facilityDecals"], layout)
        except ValueError as exc:
            _fail("invalid_decals", str(exc), "$.extensions.facilityDecals")
    if isinstance(root_extensions, Mapping) and "facilityAppearances" in root_extensions:
        from .appearance_library import normalize_custom_appearances
        try:
            normalize_custom_appearances(root_extensions["facilityAppearances"])
        except ValueError as exc:
            _fail("invalid_custom_appearances", str(exc), "$.extensions.facilityAppearances")
    if isinstance(root_extensions, Mapping) and "facilityScene" in root_extensions:
        from .appearance_library import normalize_scene
        try:
            normalize_scene(root_extensions["facilityScene"])
        except ValueError as exc:
            _fail("invalid_scene", str(exc), "$.extensions.facilityScene")
    if isinstance(root_extensions, Mapping) and "facilitySiteContext" in root_extensions:
        from .site_context import normalize_site_context
        try:
            normalize_site_context(root_extensions["facilitySiteContext"], layout)
        except ValueError as exc:
            _fail("invalid_site_context", str(exc), "$.extensions.facilitySiteContext")
    if isinstance(root_extensions, Mapping) and "facilityEquipmentDecals" in root_extensions:
        from .equipment_decals import normalize_equipment_decals
        try:
            normalize_equipment_decals(root_extensions["facilityEquipmentDecals"], layout)
        except ValueError as exc:
            _fail("invalid_equipment_decals", str(exc), "$.extensions.facilityEquipmentDecals")
    from .appearance_library import validate_layout_references
    try:
        validate_layout_references(layout)
    except ValueError as exc:
        _fail("invalid_appearance", str(exc), "$.placements")
    if isinstance(root_extensions, Mapping) and "facilityNavigation" in root_extensions:
        validate_facility_navigation_extension(
            root_extensions["facilityNavigation"],
            navigation_identity_index(layout),
        )

    if require_canonical:
        canonical = canonicalize_layout(layout)
        if _canonical_value_bytes(canonical) != _canonical_value_bytes(layout):
            _fail(
                "non_canonical_layout",
                "Facility Layout geometry is not canonical.",
                "$",
            )
    return document
