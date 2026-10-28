"""Workstation intents for new placements: an item on a desk surface, or a chair at a desk.

An agent could put a monitor on a cubicle worktop only by writing the exact surface
attachment the spatial validator checks (position, height, turn and footprint to a
micrometre), and it had to guess where a desk's user sits. These intents let it name
the desk instead:

    attachTo {"supportPlacementId", "surfaceId"}: centre the new item on one of the
        support asset's named surfaces (its definition's supportSurfaces), at the
        surface height, turned with the surface's axes. An item with a reviewed front
        faces the surface's +z side, where its user is; one without keeps its own
        axes on the surface's axes.
    seatAt {"deskPlacementId"}: put the new chair at the desk's registered seat
        (facilitySemantics.workstationSeat), facing the way that seat faces.

Both follow the support's or desk's own turn. The gateway resolves them before
validation, so the operation kernel still checks every batch it receives.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence

from .asset_orientation import COMPASS_HEADINGS, yaw_quaternion
from .errors import FacilityValidationError
from .spatial import _rotate_vector  # the validator's own rotation, so results match it exactly

PLACEMENT_INTENT_KEYS = ("attachTo", "seatAt")
_EPSILON = 1.0e-9


def _fail(code: str, message: str, index: int, **details: Any) -> None:
    raise FacilityValidationError(code, message, details={"operationIndex": index, **details})


def _record(records: Sequence[Mapping[str, Any]], asset_id: Any, revision: Any) -> Mapping[str, Any] | None:
    return next((item for item in records if item.get("assetId") == asset_id
                 and item.get("assetDefinitionRevision") == revision), None)


def _definition_field(record: Mapping[str, Any], name: str) -> Any:
    definition = record.get("definition")
    if isinstance(definition, Mapping) and name in definition:
        return definition[name]
    return record.get(name)


def _label(record: Mapping[str, Any]) -> str:
    return str(record.get("displayName") or record.get("label") or record.get("assetId") or "This asset")


def _quaternion(transform: Mapping[str, Any]) -> tuple[float, float, float, float]:
    q = transform["quaternion"]
    return float(q["x"]), float(q["y"]), float(q["z"]), float(q["w"])


def _yaw_degrees(q: tuple[float, float, float, float]) -> float:
    """Turn about the vertical axis, computed as the spatial validator computes it."""
    x, y, z, w = q
    return math.degrees(math.atan2(2.0 * (w * y + x * z), 1.0 - 2.0 * (y * y + z * z)))


def _front_heading(record: Mapping[str, Any] | None) -> int | None:
    semantics = record.get("facilitySemantics") if isinstance(record, Mapping) else None
    sides = semantics.get("functionalSides") if isinstance(semantics, Mapping) else None
    front = sides.get("front") if isinstance(sides, Mapping) else None
    side = front.get("side") if isinstance(front, Mapping) else front
    return COMPASS_HEADINGS.get(side) if isinstance(side, str) else None


def _footprint_points(record: Mapping[str, Any]) -> list[tuple[float, float]]:
    geometry = _definition_field(record, "geometry")
    polygons = geometry.get("footprintPolygons") if isinstance(geometry, Mapping) else None
    return [(float(point["x"]), float(point["z"])) for polygon in polygons or [] for point in polygon]


def _minimum_y(record: Mapping[str, Any]) -> float:
    geometry = _definition_field(record, "geometry")
    interval = geometry.get("heightInterval") if isinstance(geometry, Mapping) else None
    return float(interval.get("minimumY", 0.0)) if isinstance(interval, Mapping) else 0.0


def _size(points: Sequence[tuple[float, float]]) -> str:
    xs, zs = [p[0] for p in points], [p[1] for p in points]
    return f"{max(xs) - min(xs):.2f} x {max(zs) - min(zs):.2f} m"


def _new_placement_id(operation: Mapping[str, Any]) -> str | None:
    placement = operation.get("placement")
    return operation.get("placementId") or (placement.get("placementId") if isinstance(placement, Mapping) else None)


def _supports(layout: Mapping[str, Any], prior: Sequence[Any]) -> dict[str, Mapping[str, Any]]:
    """Saved placements, then new ones from earlier in the batch, by ID."""
    known = {item["placementId"]: item for item in layout.get("placements", [])
             if isinstance(item, Mapping) and item.get("placementId")}
    for operation in prior:
        if isinstance(operation, Mapping) and operation.get("op") == "place_asset":
            placement_id = _new_placement_id(operation)
            if placement_id and isinstance(operation.get("placement"), Mapping):
                known[placement_id] = operation["placement"]
    return known


def _intent(operation: dict, key: str, fields: tuple[str, ...], index: int) -> dict:
    intent = operation.pop(key)
    if not isinstance(intent, Mapping) or set(intent) != set(fields) or not all(
            isinstance(intent[field], str) and intent[field] for field in fields):
        _fail("placement_intent_invalid", f"{key} needs exactly {', '.join(fields)}.", index)
    if "orientation" in operation:
        _fail("placement_intent_conflict", f"{key} sets the turn itself; leave out orientation.", index)
    transform = operation["placement"].get("transform")
    if not isinstance(transform, Mapping) or "position" in transform or "quaternion" in transform:
        _fail("placement_intent_conflict",
              f"{key} computes transform.position and transform.quaternion; give only transform.scale.", index)
    return dict(intent)


def _placed(operation: dict, index: int, key: str, holder_id: str,
            supports: Mapping[str, Mapping[str, Any]], records) -> tuple[Mapping, Mapping, Mapping]:
    holder = supports.get(holder_id)
    transform = holder.get("transform") if isinstance(holder, Mapping) else None
    if not isinstance(transform, Mapping) or "quaternion" not in transform or "position" not in transform:
        _fail("placement_intent_target_unknown",
              f"{key} needs a saved placement, or one placed earlier in this batch with a known turn.",
              index, placementId=holder_id)
    record = _record(records, holder.get("assetId"), holder.get("assetDefinitionRevision"))
    if record is None:
        _fail("placement_intent_target_unknown", f"{key} could not read the asset of {holder_id}.",
              index, placementId=holder_id)
    item = _record(records, operation["placement"].get("assetId"), operation["placement"].get("assetDefinitionRevision"))
    if item is None:
        _fail("placement_intent_asset_unknown", "Search the library for the item's exact asset revision first.", index)
    return transform, record, item


def _attach(operation: dict, index: int, supports, records) -> None:
    intent = _intent(operation, "attachTo", ("supportPlacementId", "surfaceId"), index)
    support_id, surface_id = intent["supportPlacementId"], intent["surfaceId"]
    support_transform, support_record, item = _placed(operation, index, "attachTo", support_id, supports, records)
    surfaces = _definition_field(support_record, "supportSurfaces") or []
    surface = next((s for s in surfaces if isinstance(s, Mapping) and s.get("surfaceId") == surface_id), None)
    if surface is None:
        names = ", ".join(str(s.get("surfaceId")) for s in surfaces if isinstance(s, Mapping)) or "none"
        _fail("attachment_surface_unknown",
              f"{_label(support_record)} has no surface '{surface_id}'. Its surfaces: {names}.", index)
    if "above" not in (surface.get("allowedSides") or ["above"]):
        _fail("attachment_surface_unknown", f"Surface '{surface_id}' does not hold items on top.", index)
    frame, bounds = surface["localFrame"], surface["bounds"]
    origin = (float(frame["origin"]["x"]), float(frame["origin"]["y"]), float(frame["origin"]["z"]))
    z_axis = (float(frame["zAxis"]["x"]), float(frame["zAxis"]["z"]))
    # The surface's +z side faces its user. An item with a reviewed front turns that way;
    # an item without one keeps its own +z there, so its axes line up with the surface.
    surface_heading = math.degrees(math.atan2(z_axis[0], z_axis[1]))
    heading_radians = math.radians(surface_heading)
    x_axis = (float(frame["xAxis"]["x"]), float(frame["xAxis"]["z"]))
    if (abs(x_axis[0] - math.cos(heading_radians)) > 1.0e-6 or abs(x_axis[1] + math.sin(heading_radians)) > 1.0e-6
            or abs(float(frame["normal"]["y"]) - 1.0) > 1.0e-6):
        _fail("attachment_surface_unknown", f"Surface '{surface_id}' is not a flat, turned frame that attachTo supports.", index)
    front = _front_heading(item)
    turn_on_surface = -(front or 0)
    radians = math.radians(turn_on_surface)
    footprint = _footprint_points(item)
    if not footprint:
        _fail("placement_intent_asset_unknown", f"{_label(item)} has no footprint to fit on a surface.", index)
    fits = all(
        float(bounds["minimumX"]) - _EPSILON <= x * math.cos(radians) + z * math.sin(radians) <= float(bounds["maximumX"]) + _EPSILON
        and float(bounds["minimumZ"]) - _EPSILON <= -x * math.sin(radians) + z * math.cos(radians) <= float(bounds["maximumZ"]) + _EPSILON
        for x, z in footprint)
    if not fits:
        surface_size = (f"{float(bounds['maximumX']) - float(bounds['minimumX']):.2f} x "
                        f"{float(bounds['maximumZ']) - float(bounds['minimumZ']):.2f} m")
        _fail("attachment_does_not_fit",
              f"{_label(item)} ({_size(footprint)}) does not fit surface '{surface_id}' ({surface_size}). "
              "Choose an item made for that surface or a smaller one.", index)
    local_rotation = surface_heading + turn_on_surface
    support_q = _quaternion(support_transform)
    support_position = support_transform["position"]
    offset = _rotate_vector((origin[0], 0.0, origin[2]), support_q)
    plane = float(support_position["y"]) + _rotate_vector(origin, support_q)[1]
    placement = operation["placement"]
    placement["transform"] = {
        "position": {"x": float(support_position["x"]) + offset[0], "y": plane - _minimum_y(item),
                     "z": float(support_position["z"]) + offset[2]},
        "quaternion": yaw_quaternion(_yaw_degrees(support_q) + local_rotation),
        "scale": placement["transform"].get("scale", 1),
    }
    placement["snapRelationship"] = {
        "family": "surface_attachment",
        "attachmentId": f"surface:{support_id}:{surface_id}"[:160],
        "supportPlacementId": support_id,
        "surfaceId": surface_id,
        "side": "above",
        "localPosition": {"x": origin[0], "z": origin[2]},
        "localRotationDegrees": local_rotation,
        "normalOffsetMeters": 0,
        "surfaceSource": "asset_definition",
        "evidenceStatus": "unverified",
    }


def _seat(operation: dict, index: int, supports, records) -> None:
    intent = _intent(operation, "seatAt", ("deskPlacementId",), index)
    desk_id = intent["deskPlacementId"]
    desk_transform, desk_record, chair = _placed(operation, index, "seatAt", desk_id, supports, records)
    semantics = desk_record.get("facilitySemantics")
    seat = semantics.get("workstationSeat") if isinstance(semantics, Mapping) else None
    if not isinstance(seat, Mapping):
        _fail("workstation_seat_unknown",
              f"{_label(desk_record)} has no registered seat. Place the chair with a position and orientation.", index)
    front = _front_heading(chair)
    if front is None:
        _fail("asset_front_side_unknown",
              f"{_label(chair)} has no reviewed front side, so it can't be turned to face the desk. "
              "Choose a chair with one, or place it with a position and yawDegrees.", index)
    desk_q = _quaternion(desk_transform)
    desk_position = desk_transform["position"]
    local = seat["localPosition"]
    offset = _rotate_vector((float(local["x"]), 0.0, float(local["z"])), desk_q)
    placement = operation["placement"]
    placement["transform"] = {
        "position": {"x": float(desk_position["x"]) + offset[0], "y": float(desk_position["y"]),
                     "z": float(desk_position["z"]) + offset[2]},
        "quaternion": yaw_quaternion(_yaw_degrees(desk_q) + float(seat["facingDegrees"]) - front),
        "scale": placement["transform"].get("scale", 1),
    }


def resolve_placement_intents(
    operations: Any,
    *,
    catalog: Sequence[Mapping[str, Any]],
    layout: Mapping[str, Any],
) -> Any:
    """Replace attachTo and seatAt on place_asset with an exact transform (and attachment)."""
    if not isinstance(operations, list) or not any(
            isinstance(item, Mapping) and any(key in item for key in PLACEMENT_INTENT_KEYS) for item in operations):
        return operations
    records = [item for item in catalog if isinstance(item, Mapping)]
    resolved: list[Any] = []
    for index, raw in enumerate(operations):
        if not isinstance(raw, Mapping) or not any(key in raw for key in PLACEMENT_INTENT_KEYS):
            resolved.append(raw)
            continue
        operation = deepcopy(dict(raw))
        if operation.get("op") != "place_asset" or not isinstance(operation.get("placement"), Mapping):
            _fail("placement_intent_unsupported", "attachTo and seatAt are accepted only on place_asset.", index)
        if all(key in operation for key in PLACEMENT_INTENT_KEYS):
            _fail("placement_intent_conflict", "Give attachTo or seatAt, not both.", index)
        operation["placement"] = dict(operation["placement"])
        supports = _supports(layout, resolved)
        if "attachTo" in operation:
            _attach(operation, index, supports, records)
        else:
            _seat(operation, index, supports, records)
        resolved.append(operation)
    return resolved
