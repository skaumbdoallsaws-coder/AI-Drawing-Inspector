"""The warehouse's interior: racks, aisles, floor markings and forklifts (site-dressing plan S5).

Research defaults (docs/facility-site-dressing-plan.md), with the user's choice of counterbalance
forklifts:
- back-to-back double rows of selective pallet rack (the library's bay: 2.53 m long, 1.23 m deep),
  0.3 m flue between them, running at right angles to the dock wall;
- 3.7 m (12 ft) forklift aisles between double rows and at the outer walls;
- a 3.7 m cross aisle with a 1 m green walkway along the staging area, another across the middle of
  long rows, and a back aisle along the far wall beside the forklift charging bay;
- yellow 100 mm lines along the cross aisle, a white staging lane in front of each dock door;
- about one counterbalance forklift per 2.5 doors (an assumption: no published ratio was found),
  parked at the charging bay.
Positions are in the building's frame (x 0..width, z 0..depth); racks come as place_asset_array rows.
"""
from __future__ import annotations

import math

RACK_ASSET, FORKLIFT_ASSET = "asset-pallet-rack", "asset-forklift"
BAY_LENGTH, RACK_DEPTH = 2.528, 1.227  # the library rack bay, when the catalogue has no size
FLUE = 0.3
AISLE = 3.7
WALKWAY = 1.0
WALL_GAP = 0.5
BACK_AISLE_AND_CHARGING = 6.5  # back aisle 3.7 m, then a 2.8 m charging bay against the far wall
MIDDLE_AISLE_OVER = 50.0       # rows longer than this get a cross aisle in the middle
DOORS_PER_FORKLIFT = 2.5
YELLOW, WHITE, GREEN = "#facc15", "#ffffff", "#22c55e"
ZONE_ID = "zn-forklift-charging"
MARKING_PREFIX, ARRAY_PREFIX, PLACEMENT_PREFIX, ROUTE_PREFIX = "fm-interior-", "racks-", "pl-forklift-", "rt-interior-"
# The user's rack colours (warehouse 5, 2026-10-23): deep blue legs and orange crossmembers, on every part
# of the library bay. Applied to each saved bay after the design, as its own review (site_paint.py).
RACK_FINISH = {"representation": "overview", "overrides": sorted(
    [{"key": f"p:Crossmember-{n}#0", "color": "#f07818", "roughness": 0.55, "metalness": 0.1} for n in (1, 2, 3, 4, 7, 8, 9, 10)]
    + [{"key": f"p:Legs-{n}#0", "color": "#174a7e", "roughness": 0.55, "metalness": 0.1} for n in (1, 2)],
    key=lambda item: item["key"])}


def _frame(side: str, width: float, depth: float):
    """(a, d) to (x, z): `a` along the dock wall (counter-clockwise), `d` from the dock wall inward.
    Also the wall's length, the depth inward, and the unit directions of growing a and d."""
    return {"east": (lambda a, d: (width - d, a), depth, width, (0.0, 1.0), (-1.0, 0.0)),
            "west": (lambda a, d: (d, depth - a), depth, width, (0.0, -1.0), (1.0, 0.0)),
            "south": (lambda a, d: (a, d), width, depth, (1.0, 0.0), (0.0, 1.0)),
            "north": (lambda a, d: (width - a, depth - d), width, depth, (-1.0, 0.0), (0.0, -1.0))}[side]


def _yaw(direction) -> float:
    return math.degrees(math.atan2(direction[0], direction[1]))


def _quaternion(yaw_degrees: float) -> dict:
    half = math.radians(yaw_degrees) / 2
    return {"x": 0, "y": round(math.sin(half), 9), "z": 0, "w": round(math.cos(half), 9)}


def _size(record: dict | None, fallback: tuple[float, float]) -> tuple[float, float]:
    """A model's (x, z) footprint from its catalogue record."""
    aabb = (((record or {}).get("definition") or {}).get("geometry") or {}).get("aabb") or {}
    low, high = aabb.get("minimum") or {}, aabb.get("maximum") or {}
    try:
        return float(high["x"]) - float(low["x"]), float(high["z"]) - float(low["z"])
    except (KeyError, TypeError, ValueError):
        return fallback


def operations(geometry: dict, settings: dict, catalog: dict | None) -> list[dict]:
    width, depth = geometry["size"]
    side = geometry["side"]
    at, wall, deep, a_dir, d_dir = _frame(side, width, depth)
    stage = min(settings["stagingDepthMeters"], deep / 3)
    ops = []

    def mark(key, kind, a, d, length_along_a, length_along_d, color, text="", role="decorative", opacity=1.0):
        x, z = at(a, d)
        # A marking's depth runs along its local z, turned by rotationDegrees like a yaw.
        rotation, wide, long = (_yaw(a_dir), length_along_d, length_along_a) if length_along_a >= length_along_d \
            else (_yaw(d_dir), length_along_a, length_along_d)
        ops.append({"op": "add_floor_marking", "floorMarking": {
            "markingId": MARKING_PREFIX + key, "markingType": kind, "label": key.replace("-", " ").title(),
            "semanticRole": role, "transform": {"position": {"x": round(x, 3), "y": 0.008, "z": round(z, 3)},
                                               "rotationDegrees": round(rotation, 3)},
            "width": round(wide, 3), "depth": round(long, 3), "fillColor": color, "strokeColor": color,
            "opacity": opacity, "text": text, "positionMode": "manual",
            "metadata": {"authoredIn": "site_dressing_interior"}, "evidence": []}})

    def aisle(key, label, points, corridor):
        ops.append({"op": "add_aisle", "routeId": ROUTE_PREFIX + key, "aisle": {
            "label": label, "centerline": [{"x": round(x, 3), "y": 0, "z": round(z, 3)} for x, z in (at(a, d) for a, d in points)],
            "corridorWidth": corridor, "aisleKind": "forklift", "direction": "two_way", "color": "#d9a514",
            "clearanceEvidenceStatus": "unverified"}})

    # Staging lanes in front of each door, numbered along the wall.
    for number, (start, end) in enumerate(geometry["doors"], start=1):
        mark(f"door-{number:02}", "parking_box", (start + end) / 2, (stage - 2.0) / 2 + 0.5, end - start + 0.4,
             stage - 2.0, WHITE, f"DOOR {number}", role="staging")
    # Cross aisle along the staging area, with its edge lines and the walkway behind it.
    span = (WALL_GAP, wall - WALL_GAP)
    cross = stage + AISLE / 2
    aisle("cross-aisle", "Cross aisle", [(span[0], cross), (span[1], cross)], AISLE - 0.1)
    for key, d in (("cross-aisle-edge-staging", stage), ("cross-aisle-edge-racks", stage + AISLE)):
        mark(key, "solid_line", sum(span) / 2, d, span[1] - span[0], 0.1, YELLOW, role="forklift_lane")
    mark("walkway", "solid_line", sum(span) / 2, stage + AISLE + WALKWAY / 2, span[1] - span[0], WALKWAY, GREEN,
         role="pedestrian_lane", opacity=0.75)
    # Rack rows between the walkway and the back aisle, with a middle cross aisle when they are long.
    row_start, row_end = stage + AISLE + WALKWAY, deep - BACK_AISLE_AND_CHARGING
    if row_end - row_start < 2 * BAY_LENGTH:
        return ops
    blocks = [(row_start, row_end)]
    if row_end - row_start > MIDDLE_AISLE_OVER:
        middle = (row_start + row_end) / 2
        blocks = [(row_start, middle - AISLE / 2), (middle + AISLE / 2, row_end)]
        aisle("middle-aisle", "Middle cross aisle", [(span[0], middle), (span[1], middle)], AISLE - 0.1)
    back = deep - BACK_AISLE_AND_CHARGING + AISLE / 2
    aisle("back-aisle", "Back aisle", [(span[0], back), (span[1], back)], AISLE - 0.1)
    rack = (catalog or {}).get(RACK_ASSET)
    rack_depth, bay = _size(rack, (RACK_DEPTH, BAY_LENGTH))
    double = 2 * rack_depth + FLUE
    count = int((wall - 2 * WALL_GAP - AISLE) // (double + AISLE))
    slack = (wall - 2 * WALL_GAP - AISLE - count * (double + AISLE)) / 2
    a = WALL_GAP + slack
    aisle_centres = [a + AISLE / 2]
    rows = []
    for number in range(count):
        middle_of_double = a + AISLE + double / 2
        rows.append(middle_of_double)
        a += AISLE + double
        aisle_centres.append(a + AISLE / 2)
    for index, centre in enumerate(aisle_centres, start=1):
        aisle(f"rack-aisle-{index:02}", f"Rack aisle {index}", [(centre, row_start - WALKWAY), (centre, back)], AISLE - 0.1)
    if rack:
        yaw = _yaw(d_dir)  # bays run along the rows: the model's long (z) side along growing d
        for number, centre in enumerate(rows, start=1):
            for face, offset in (("a", -(rack_depth + FLUE) / 2), ("b", (rack_depth + FLUE) / 2)):
                for block, (d0, d1) in enumerate(blocks, start=1):
                    bays = int((d1 - d0) // bay)
                    if bays < 1:
                        continue
                    first = d0 + ((d1 - d0) - bays * bay) / 2 + bay / 2
                    x, z = at(centre + offset, first)
                    ops.append({"op": "place_asset_array", "arrayId": f"{ARRAY_PREFIX}{number:02}{face}-{block}",
                                "placement": {"assetId": RACK_ASSET, "assetDefinitionRevision": rack["assetDefinitionRevision"],
                                              "transform": {"position": {"x": round(x, 3), "y": 0, "z": round(z, 3)},
                                                            "quaternion": _quaternion(yaw), "scale": 1},
                                              "positionMode": "manual", "snapRelationship": None,
                                              "metadata": {"instanceLabel": f"Rack {number}{face.upper()}-{block} bay",
                                                           "inputMethod": "site-dressing-interior"}},
                                "step": {"x": round(d_dir[0] * bay, 6), "y": 0, "z": round(d_dir[1] * bay, 6)},
                                "count": bays})
    # Forklift charging bay against the far wall, at the end nearest the first aisle.
    forklifts = max(2, round(len(geometry["doors"]) / DOORS_PER_FORKLIFT))
    forklift = (catalog or {}).get(FORKLIFT_ASSET)
    truck_width, truck_length = _size(forklift, (1.13, 1.96))
    spacing = truck_width + 1.0
    bay_a = (WALL_GAP, WALL_GAP + spacing * forklifts)
    bay_d = (deep - BACK_AISLE_AND_CHARGING + AISLE, deep - 0.2)
    corners = [at(bay_a[0], bay_d[0]), at(bay_a[1], bay_d[0]), at(bay_a[1], bay_d[1]), at(bay_a[0], bay_d[1])]
    ops.append({"op": "add_zone", "zone": {"zoneId": ZONE_ID, "zoneType": "charging", "label": "Forklift charging",
                "boundary": [{"x": round(x, 3), "z": round(z, 3)} for x, z in corners],
                "floorElevation": 0, "anchors": [], "evidence": []}})
    if forklift:
        d = bay_d[0] + (bay_d[1] - bay_d[0]) / 2
        for number in range(forklifts):
            x, z = at(bay_a[0] + spacing * (number + 0.5), d)
            ops.append({"op": "place_asset", "placement": {
                "placementId": f"{PLACEMENT_PREFIX}{number + 1:02}", "assetId": FORKLIFT_ASSET,
                "assetDefinitionRevision": forklift["assetDefinitionRevision"],
                "transform": {"position": {"x": round(x, 3), "y": 0, "z": round(z, 3)},
                              "quaternion": _quaternion(_yaw(d_dir)), "scale": 1},
                "positionMode": "manual", "snapRelationship": None,
                "metadata": {"instanceLabel": f"Forklift {number + 1}", "inputMethod": "site-dressing-interior"}}})
    return ops


def clear_previous(layout: dict) -> list[dict]:
    """Delete an earlier plan's interior: rack rows, forklifts, aisles, markings and the charging zone."""
    rows = sorted({str(p["placementId"])[3:].rsplit("-", 1)[0] for p in layout.get("placements", [])
                   if str(p.get("placementId", "")).startswith("pl-" + ARRAY_PREFIX)})
    ops = [{"op": "delete_asset_array", "arrayId": row} for row in rows]
    ops += [{"op": "delete_placement", "placementId": p["placementId"]} for p in layout.get("placements", [])
            if str(p.get("placementId", "")).startswith(PLACEMENT_PREFIX)]
    ops += [{"op": "delete_floor_marking", "markingId": m["markingId"]} for m in layout.get("floorMarkings", [])
            if str(m.get("markingId", "")).startswith(MARKING_PREFIX)]
    ops += [{"op": "delete_route", "routeId": r["routeId"]} for r in layout.get("routes", [])
            if str(r.get("routeId", "")).startswith(ROUTE_PREFIX)]
    ops += [{"op": "delete_zone", "zoneId": ZONE_ID} for z in layout.get("zones", []) if z.get("zoneId") == ZONE_ID]
    return ops
