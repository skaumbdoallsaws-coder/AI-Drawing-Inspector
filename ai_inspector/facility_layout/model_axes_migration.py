"""Bring a layout saved before the 2026-10-21 display fix into the mirrored model space.

model_axes.py mirrors every model file once on its way into a layout. A layout
saved before that placed models in the files' own axes, so four things change:

1. A model whose reviewed front is the file's east or west side turns 180
   degrees in place, so its front keeps facing where it faced. Its footprint
   rectangle, and so the plan, do not change.
2. A chair sitting exactly at a desk's registered seat moves to the mirrored
   seat of that desk.
3. An item attached to an authored support surface is re-placed on the
   mirrored surface. An item on a derived top keeps its place.
4. Equipment decals move to the mirrored spot on their model.

Zones, walls, routes, markings and every other position stay as they are.
Placement-face artworks are not handled yet: a layout holding any is refused.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
from typing import Any

from .asset_orientation import COMPASS_HEADINGS, REGISTERED_ASSET_SEMANTICS, yaw_quaternion
from .model_axes import mirror_heading
from .spatial import _rotate_vector

SEAT_DISTANCE_METERS = 0.02
SEAT_YAW_DEGREES = 1.0


def _yaw_degrees(quaternion: Mapping[str, Any]) -> float:
    x, y, z, w = (float(quaternion[k]) for k in ("x", "y", "z", "w"))
    return math.degrees(math.atan2(2.0 * (w * y + x * z), 1.0 - 2.0 * (y * y + z * z)))


def _quaternion_tuple(quaternion: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return tuple(float(quaternion[k]) for k in ("x", "y", "z", "w"))


def _canonical_sign(x: float, y: float, z: float, w: float) -> dict[str, float]:
    # The layout requires the first nonzero of w, x, y, z to be positive.
    for value in (w, x, y, z):
        if abs(value) > 1e-15:
            if value < 0:
                x, y, z, w = -x, -y, -z, -w
            break
    return {"x": x + 0.0, "y": y + 0.0, "z": z + 0.0, "w": w + 0.0}


def _turned(quaternion: Mapping[str, Any], degrees: float) -> dict[str, float]:
    """The orientation followed by a turn about the model's own vertical axis."""
    x, y, z, w = _quaternion_tuple(quaternion)
    if abs(x) < 1e-12 and abs(z) < 1e-12:
        return yaw_quaternion(_yaw_degrees(quaternion) + degrees)
    half = math.radians(degrees) / 2.0
    by, bw = math.sin(half), math.cos(half)
    # Hamilton product q * b with b = (0, by, 0, bw): b turns first, in the model's frame.
    return _canonical_sign(x * bw - z * by, w * by + y * bw, x * by + z * bw, w * bw - y * by)


def _normalized_degrees(value: float) -> float:
    result = (float(value) + 180.0) % 360.0 - 180.0
    return 180.0 if math.isclose(result, -180.0, abs_tol=1e-9) else result + 0.0


def _entry(placement: Mapping[str, Any], registry) -> Mapping[str, Any] | None:
    entry = registry.get(str(placement.get("assetId") or ""))
    if entry is None or placement.get("assetDefinitionRevision") != entry[0]:
        return None
    return entry[1]


def _front_side(semantics: Mapping[str, Any] | None) -> str | None:
    sides = (semantics or {}).get("functionalSides")
    front = sides.get("front") if isinstance(sides, Mapping) else None
    return front.get("side") if isinstance(front, Mapping) else None


def migrate_layout(document: Mapping[str, Any], registry=None) -> tuple[dict[str, Any], dict[str, int]]:
    """Return the migrated layout and counts of what changed."""
    registry = REGISTERED_ASSET_SEMANTICS if registry is None else registry
    layout = deepcopy(dict(document))
    report = {"turned": 0, "seated": 0, "attachments": 0, "derivedAttachments": 0, "equipmentDecals": 0}
    extensions = layout.get("extensions") if isinstance(layout.get("extensions"), Mapping) else {}
    artworks = (extensions.get("facilityDecals") or {}).get("artworks", []) if isinstance(extensions, Mapping) else []
    if any(isinstance(item, Mapping) and "placementId" in (item.get("target") or {}) for item in artworks):
        raise ValueError("Placement-face artworks cannot be migrated yet")
    placements = [p for p in layout.get("placements", []) if isinstance(p, dict) and isinstance(p.get("transform"), dict)]
    by_id = {p["placementId"]: p for p in placements}
    before = {p["placementId"]: deepcopy(p["transform"]) for p in placements}
    turned: set[str] = set()

    # 1. Models with an east or west front turn 180 degrees in place.
    for placement in placements:
        if _front_side(_entry(placement, registry)) in ("east", "west"):
            placement["transform"]["quaternion"] = _turned(placement["transform"]["quaternion"], 180.0)
            turned.add(placement["placementId"])
            report["turned"] += 1

    attached = {p["placementId"] for p in placements
                if (p.get("snapRelationship") or {}).get("family") == "surface_attachment"}

    # 2. Chairs at a registered seat move to the mirrored seat.
    for desk in placements:
        seat = (_entry(desk, registry) or {}).get("workstationSeat")
        if not isinstance(seat, Mapping):
            continue
        sx, sz = float(seat["localPosition"]["x"]), float(seat["localPosition"]["z"])
        facing = float(seat["facingDegrees"])
        old = before[desk["placementId"]]
        old_offset = _rotate_vector((sx, 0.0, sz), _quaternion_tuple(old["quaternion"]))
        old_seat = (float(old["position"]["x"]) + old_offset[0], float(old["position"]["z"]) + old_offset[2])
        new_offset = _rotate_vector((-sx, 0.0, sz), _quaternion_tuple(desk["transform"]["quaternion"]))
        for chair in placements:
            if chair is desk or chair["placementId"] in attached or chair["placementId"] in turned:
                continue
            front = _front_side(_entry(chair, registry))
            if front not in COMPASS_HEADINGS:
                continue
            chair_old = before[chair["placementId"]]
            distance = math.hypot(float(chair_old["position"]["x"]) - old_seat[0],
                                  float(chair_old["position"]["z"]) - old_seat[1])
            expected_yaw = _yaw_degrees(old["quaternion"]) + facing - COMPASS_HEADINGS[front]
            if distance > SEAT_DISTANCE_METERS or abs(_normalized_degrees(
                    _yaw_degrees(chair_old["quaternion"]) - expected_yaw)) > SEAT_YAW_DEGREES:
                continue
            chair["transform"]["position"] = {
                **chair["transform"]["position"],
                "x": float(desk["transform"]["position"]["x"]) + new_offset[0] + 0.0,
                "z": float(desk["transform"]["position"]["z"]) + new_offset[2] + 0.0,
            }
            chair["transform"]["quaternion"] = yaw_quaternion(
                _yaw_degrees(desk["transform"]["quaternion"]) + mirror_heading(facing)
                - mirror_heading(COMPASS_HEADINGS[front]))
            report["seated"] += 1

    # 3. Attachments follow their support's mirrored surface.
    for child in placements:
        relationship = child.get("snapRelationship")
        if not isinstance(relationship, dict) or relationship.get("family") != "surface_attachment":
            continue
        support = by_id.get(relationship.get("supportPlacementId"))
        if support is None:
            continue
        local = relationship["localPosition"]
        lx, lz = float(local["x"]), float(local["z"])
        rotation = float(relationship["localRotationDegrees"])
        if relationship.get("surfaceSource") == "asset_definition":
            lx, rotation = -lx, -rotation
            relationship["localPosition"] = {"x": lx + 0.0, "z": lz + 0.0}
            relationship["localRotationDegrees"] = _normalized_degrees(rotation)
            support_q = _quaternion_tuple(support["transform"]["quaternion"])
            offset = _rotate_vector((lx, 0.0, lz), support_q)
            child["transform"]["position"] = {
                **child["transform"]["position"],
                "x": float(support["transform"]["position"]["x"]) + offset[0] + 0.0,
                "z": float(support["transform"]["position"]["z"]) + offset[2] + 0.0,
            }
            child["transform"]["quaternion"] = yaw_quaternion(
                _yaw_degrees(support["transform"]["quaternion"]) + relationship["localRotationDegrees"])
            report["attachments"] += 1
        else:
            # A derived top is the support's symmetric box: the item keeps its place.
            if support["placementId"] in turned:
                lx, lz, rotation = -lx, -lz, rotation - 180.0
            if child["placementId"] in turned:
                rotation += 180.0
            relationship["localPosition"] = {"x": lx + 0.0, "z": lz + 0.0}
            relationship["localRotationDegrees"] = _normalized_degrees(rotation)
            report["derivedAttachments"] += 1

    # 4. Equipment decals move to the mirrored spot on their model.
    decals = (extensions.get("facilityEquipmentDecals") or {}).get("decals", []) if isinstance(extensions, Mapping) else []
    for decal in decals:
        anchor = decal.get("anchor") if isinstance(decal, dict) else None
        if not isinstance(anchor, dict):
            continue
        for name in ("position", "normal"):
            if isinstance(anchor.get(name), dict):
                anchor[name] = {**anchor[name], "x": -float(anchor[name]["x"]) + 0.0}
        anchor["rotationDegrees"] = -float(anchor["rotationDegrees"]) + 0.0
        report["equipmentDecals"] += 1
    return layout, report
