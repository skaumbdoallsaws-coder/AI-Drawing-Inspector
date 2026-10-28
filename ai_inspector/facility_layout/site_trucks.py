"""Trucks at the dock doors and the truck court's circulation arrows (site-dressing plan S4).

Trucks back up to every other door in both the receiving and the shipping half of the dock wall,
using the library's 40 ft container truck in its dock pose (container doors at the model's -z
end, cab at +z). Arrows on the court show counter-clockwise circulation, so drivers pull along the
dock wall with the building on their side and back in toward it (sight-side backing, research
defaults in docs/facility-site-dressing-plan.md). In the new plan's frame: x 0..width, z 0..depth,
plan edges 0 south, 1 east, 2 north, 3 west, each run counter-clockwise.
"""
from __future__ import annotations

import math

TRUCK_ASSET = "asset-truck-40ft-container-straight"
TRUCK_HALF_LENGTH = 7.937  # the model's z extent each side of its origin, when the catalogue has none
REAR_GAP_METERS = 0.25     # container doors this far off the plan edge (the wall's face and bumpers)
ZONE_ID = "zn-truck-court"
MARKING_PREFIX, PLACEMENT_PREFIX = "fm-truck-court-", "pl-truck-court-"
YELLOW = "#facc15"
# The 3D view paints a model's plain parts one neutral slate, so each part gets its colour: the user's blue cab
# and white container (warehouse 5, 2026-10-23) on a dark chassis. Keys are the model's parts. Applied after the
# design is saved, as its own review (site_paint.py).
TRUCK_FINISH = {"representation": "overview", "overrides": [
    {"key": "p:User%20Library-truck-1_Container-40Feet-1#0", "color": "#ffffff", "roughness": 0.7, "metalness": 0.04},
    {"key": "p:User%20Library-truck-1_Truck-2#0", "color": "#1565c0", "roughness": 0.7, "metalness": 0.04},
    {"key": "p:User%20Library-truck-1_Truck-train-2#0", "color": "#2b2f33", "roughness": 0.6, "metalness": 0.2}]}


def _wall(side: str, width: float, depth: float):
    """Where a point `m` metres along the dock wall lies, the wall's outward direction, and the
    direction the wall runs (counter-clockwise round the building)."""
    return {"south": (lambda m: (m, 0.0), (0.0, -1.0), (1.0, 0.0)),
            "east": (lambda m: (width, m), (1.0, 0.0), (0.0, 1.0)),
            "north": (lambda m: (width - m, depth), (0.0, 1.0), (-1.0, 0.0)),
            "west": (lambda m: (0.0, depth - m), (-1.0, 0.0), (0.0, -1.0))}[side]


def _yaw(direction) -> float:
    """The yaw turning a model's +z axis to `direction` (x, z): +z goes to (sin yaw, cos yaw)."""
    return math.degrees(math.atan2(direction[0], direction[1]))


def operations(geometry: dict, settings: dict, catalog: dict | None) -> list[dict]:
    from .site_plan import APRON_METERS
    width, depth = geometry["size"]
    side, court = geometry["side"], settings["truckCourtDepthMeters"]
    at, out, along = _wall(side, width, depth)
    wall = width if side in ("south", "north") else depth
    ops = []
    corners = [at(0.0), at(wall)]
    far = [(x + out[0] * court, z + out[1] * court) for x, z in corners]
    ops.append({"op": "add_zone", "zone": {
        "zoneId": ZONE_ID, "zoneType": "dock", "label": "Truck court",
        "boundary": [{"x": round(x, 3) + 0.0, "z": round(z, 3) + 0.0} for x, z in corners + far[::-1]],
        "floorElevation": 0, "anchors": [], "evidence": []}})

    def arrow(key, x, z, direction):
        ops.append({"op": "add_floor_marking", "floorMarking": {
            "markingId": MARKING_PREFIX + key, "markingType": "direction_arrow", "label": key.replace("-", " ").title(),
            "semanticRole": "decorative", "transform": {"position": {"x": round(x, 3), "y": 0.008, "z": round(z, 3)},
                                                       "rotationDegrees": round(_yaw(direction), 3)},
            "width": 1.2, "depth": 3.0, "fillColor": YELLOW, "strokeColor": YELLOW, "opacity": 1, "text": "",
            "positionMode": "manual", "metadata": {"authoredIn": "site_dressing_truck_court"}, "evidence": []}})

    # In along the outside of the court, back along the dock wall with the building on the driver's side.
    inner = min(APRON_METERS + 3.0, court - 6.0)
    for index, share in enumerate((0.2, 0.5, 0.8)):
        x, z = at(wall * share)
        arrow(f"along-docks-{index + 1}", x + out[0] * inner, z + out[1] * inner, along)
        arrow(f"outside-{index + 1}", x + out[0] * (court - 4.0), z + out[1] * (court - 4.0), (-along[0], -along[1]))
    truck = (catalog or {}).get(TRUCK_ASSET)
    if truck:
        aabb = ((truck.get("definition") or {}).get("geometry") or {}).get("aabb") or {}
        half = -float((aabb.get("minimum") or {}).get("z", -TRUCK_HALF_LENGTH))
        doors = geometry["doors"]
        halves = [[door for door in doors if (door[0] + door[1]) / 2 < wall / 2],
                  [door for door in doors if (door[0] + door[1]) / 2 >= wall / 2]]
        yaw = math.radians(_yaw(out))
        for name, group in zip(("receiving", "shipping"), halves):
            for index, (start, end) in enumerate(group[::2]):
                x, z = at((start + end) / 2)
                cx, cz = x + out[0] * (REAR_GAP_METERS + half), z + out[1] * (REAR_GAP_METERS + half)
                ops.append({"op": "place_asset", "placement": {
                    "placementId": f"{PLACEMENT_PREFIX}{name}-{index + 1}", "assetId": TRUCK_ASSET,
                    "assetDefinitionRevision": truck["assetDefinitionRevision"],
                    "transform": {"position": {"x": round(cx, 3), "y": 0, "z": round(cz, 3)},
                                  "quaternion": {"x": 0, "y": math.sin(yaw / 2), "z": 0, "w": math.cos(yaw / 2)},
                                  "scale": 1},
                    "positionMode": "manual", "snapRelationship": None,
                    "metadata": {"instanceLabel": f"Truck at {name} door {index + 1}",
                                 "inputMethod": "site-dressing-truck-court"}}})
    return ops


def clear_previous(layout: dict) -> list[dict]:
    """Delete an earlier plan's trucks, court arrows and court zone."""
    ops = [{"op": "delete_placement", "placementId": p["placementId"]} for p in layout.get("placements", [])
           if str(p.get("placementId", "")).startswith(PLACEMENT_PREFIX)]
    ops += [{"op": "delete_floor_marking", "markingId": m["markingId"]} for m in layout.get("floorMarkings", [])
            if str(m.get("markingId", "")).startswith(MARKING_PREFIX)]
    ops += [{"op": "delete_zone", "zoneId": ZONE_ID} for z in layout.get("zones", []) if z.get("zoneId") == ZONE_ID]
    return ops
