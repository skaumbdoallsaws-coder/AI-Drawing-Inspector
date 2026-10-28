"""Reference point candidates from what the site already holds (reference-points plan, R2).

A builder sets a building out from points they can find on site. The user's choice (2026-10-23) is to start from
the property corners and the corners of pavement seen on the photo; road intersections and the rail crossing serve
only to check the photo against the map. Accuracies are the sources' own, stated plainly:
- the USGS NAIP photo is about 6 m to true ground at 95% of points, though features in one photo are within about
  1 m of each other;
- county parcel lines come from recorded plats and are not survey-grade (assumed here to within 3 m);
- Census TIGER road centrelines are good to several metres (about 8 m assumed).
Positions are in the property frame (metres east and north of the site origin).
"""
from __future__ import annotations

import math
from typing import Any, Mapping

PARCEL_ACCURACY_METERS = 3.0
PHOTO_ACCURACY_METERS = 6.0
ROAD_MAP_ACCURACY_METERS = 8.0
PROPERTY_CORNER_TURN = 25.0  # degrees; the river side of a parcel wiggles by less than this at most vertices
PAVEMENT_CORNER_TURN = 35.0
CORNER_EDGE_METERS = 4.0     # both edges at a corner at least this long: a corner, not a notch in a trace
CHECK_RADIUS_METERS = 250.0
COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
COMPASS_16 = ("north", "north-north-east", "north-east", "east-north-east", "east", "east-south-east", "south-east",
              "south-south-east", "south", "south-south-west", "south-west", "west-south-west", "west",
              "west-north-west", "north-west", "north-north-west")


def _xz(point: Any) -> tuple[float, float]:
    return (float(point["x"]), float(point["z"])) if isinstance(point, Mapping) else (float(point[0]), float(point[1]))


def corners(points, min_turn_degrees: float, min_edge_meters: float = 1.0) -> list[tuple[int, float]]:
    """Indices of a closed outline's vertices where it turns by at least `min_turn_degrees` between edges at least
    `min_edge_meters` long, with the turn."""
    found = []
    count = len(points)
    for index in range(count):
        a, b, c = _xz(points[index - 1]), _xz(points[index]), _xz(points[(index + 1) % count])
        first = math.atan2(b[1] - a[1], b[0] - a[0])
        second = math.atan2(c[1] - b[1], c[0] - b[0])
        turn = abs((math.degrees(second - first) + 180) % 360 - 180)
        if turn >= min_turn_degrees and math.dist(a, b) >= min_edge_meters and math.dist(b, c) >= min_edge_meters:
            found.append((index, turn))
    return found


def compass(dx: float, dz: float, points: int = 8) -> str:
    """The 8- or 16-point compass direction of an (east, north) offset."""
    names = COMPASS if points == 8 else COMPASS_16
    return names[round(math.degrees(math.atan2(dx, dz)) % 360 / (360 / points)) % points]


def _name_corners(items: list[dict[str, Any]], middle: tuple[float, float], noun: str) -> None:
    """'North-west property corner'; where two would share a name, both take the 16-point name."""
    eight = [compass(item["x"] - middle[0], item["z"] - middle[1]) for item in items]
    for item, name in zip(items, eight):
        if eight.count(name) > 1:
            name = compass(item["x"] - middle[0], item["z"] - middle[1], 16)
        item["label"] = f"{name.capitalize()} {noun}"


def _intersection(p, q, r, s):
    d = (q[0] - p[0]) * (s[1] - r[1]) - (q[1] - p[1]) * (s[0] - r[0])
    if abs(d) < 1e-9:
        return None
    t = ((r[0] - p[0]) * (s[1] - r[1]) - (r[1] - p[1]) * (s[0] - r[0])) / d
    u = ((r[0] - p[0]) * (q[1] - p[1]) - (r[1] - p[1]) * (q[0] - p[0])) / d
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])) if 0 <= t <= 1 and 0 <= u <= 1 else None


def _road_crossings(site: Mapping[str, Any], centre: tuple[float, float]) -> list[dict[str, Any]]:
    """Where two mapped roads meet, or a road crosses the railway, near the building."""
    items = [item for item in (site.get("roads") or {}).get("items") or [] if len(item.get("line") or []) >= 2]
    found = []
    for i, first in enumerate(items):
        for second in items[i + 1:]:
            if first.get("label") == second.get("label") and first.get("kind") == second.get("kind"):
                continue
            rail = "railroad" in (first.get("kind"), second.get("kind"))
            if first.get("kind") == second.get("kind") == "railroad":
                continue
            a_line, b_line = [_xz(p) for p in first["line"]], [_xz(p) for p in second["line"]]
            for p, q in zip(a_line, a_line[1:]):
                for r, s in zip(b_line, b_line[1:]):
                    point = _intersection(p, q, r, s)
                    if point is None or math.dist(point, centre) > CHECK_RADIUS_METERS:
                        continue
                    if any(math.dist(point, (item["x"], item["z"])) < 5 for item in found):
                        continue
                    names = sorted({first.get("label") or "a road", second.get("label") or "a road"} - {"Railroad"})
                    found.append({"kind": "rail_crossing" if rail else "road_intersection", "source": "road_map",
                                  "x": round(point[0], 3), "z": round(point[1], 3),
                                  "accuracyMeters": ROAD_MAP_ACCURACY_METERS,
                                  "label": ("Rail crossing of " + names[0]) if rail and names
                                  else " and ".join(names) + " intersection",
                                  "use": "check the photo against the map",
                                  "_roads": [(first.get("kind"), a_line), (second.get("kind"), b_line)]})
    return found


def _spread(candidates: list[dict[str, Any]], chosen: list[dict[str, Any]], limit: int,
            near: tuple[float, float]) -> list[dict[str, Any]]:
    """Add up to `limit` candidates: with nothing chosen yet the one nearest `near` (short ties to the building),
    then each the farthest from those already chosen (a well-spread set)."""
    picked = []
    pool = list(candidates)
    while pool and len(picked) < limit:
        taken = chosen + picked
        if not taken:
            best = min(pool, key=lambda item: math.dist((item["x"], item["z"]), near))
            picked.append(best)
            pool.remove(best)
            continue
        best = max(pool, key=lambda item: min(math.dist((item["x"], item["z"]), (t["x"], t["z"])) for t in taken))
        if taken and min(math.dist((best["x"], best["z"]), (t["x"], t["z"])) for t in taken) < 10:
            break
        picked.append(best)
        pool.remove(best)
    return picked


def suggest_references(site: Mapping[str, Any], layout: Mapping[str, Any], max_points: int = 5) -> dict[str, Any]:
    """Candidates and a well-spread suggestion, ready to stage with upsert_site_reference."""
    from .site_context import building_outline
    prop = site.get("property") or {}
    boundary = prop.get("boundary") or []
    outline = building_outline(layout, site)
    centre = (sum(p["x"] for p in outline) / 4, sum(p["z"] for p in outline) / 4)
    xs, zs = [_xz(p)[0] for p in boundary], [_xz(p)[1] for p in boundary]
    middle = ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2) if boundary else centre  # the lot's box centre
    parcel = "county_parcel" if prop.get("source") == "county_parcel" else "user"
    property_corners = [{"kind": "property_corner", "source": parcel, "x": round(_xz(boundary[i])[0], 3),
                         "z": round(_xz(boundary[i])[1], 3),
                         "accuracyMeters": PARCEL_ACCURACY_METERS if parcel == "county_parcel" else 1.0,
                         "turnDegrees": round(turn)}
                        for i, turn in corners(boundary, PROPERTY_CORNER_TURN)] if len(boundary) >= 3 else []
    _name_corners(property_corners, middle, "property corner")
    pavement_corners = []
    for area in site.get("areas") or []:
        if area.get("kind") != "existing_pavement":
            continue
        points = area["boundary"]
        for i, turn in corners(points, PAVEMENT_CORNER_TURN, CORNER_EDGE_METERS):
            x, z = _xz(points[i])
            pavement_corners.append({"kind": "pavement_corner", "source": "site_photo", "x": round(x, 3), "z": round(z, 3),
                                     "accuracyMeters": PHOTO_ACCURACY_METERS, "turnDegrees": round(turn)})
    _name_corners(pavement_corners, middle, "corner of the existing pavement")
    checks = [{key: value for key, value in item.items() if key != "_roads"} for item in _road_crossings(site, centre)]
    limit = max(1, min(int(max_points), 8))
    chosen = _spread(property_corners, [], min(4, limit), centre)
    chosen += _spread(pavement_corners, chosen, limit - len(chosen), centre)
    existing = {item["referenceId"] for item in site.get("references") or []}
    numbers = (n for n in range(1, 100) if f"rp-{n}" not in existing)
    suggested = [{"referenceId": f"rp-{next(numbers)}", **{key: item[key] for key in
                  ("label", "kind", "source", "x", "z", "accuracyMeters")}} for item in chosen]
    return {"available": bool(suggested), "suggested": suggested,
            "candidates": {"propertyCorners": property_corners, "pavementCorners": pavement_corners,
                           "checkPoints": checks},
            "accuracy": {"countyParcelMeters": PARCEL_ACCURACY_METERS, "photoMeters": PHOTO_ACCURACY_METERS,
                         "roadMapMeters": ROAD_MAP_ACCURACY_METERS,
                         "note": "The photo is about 6 m to true ground; features in one photo are within about 1 m of "
                                 "each other. Parcel lines come from plats, not a survey. Stake from a surveyor's control."},
            **({} if suggested else {"reason": "The site has no property corners or traced pavement to use."})}
