"""How well the sources agree, and the plan dropped onto surveyed points (reference-points plan, R3).

Before a survey, the road map is checked against the photo at points both show: each mapped road intersection
and rail crossing near the building. Across each road the photo's own centre is found (the middle of its paved
strip at stations either side of the crossing), a line is fitted through those centres, and the two lines are
crossed. The offsets from the mapped points say how far the photo the design was traced on is from the map data.

After a survey, reference points carry a measured position. The best move and turn (never a stretch) takes the
plan's positions onto the measured ones. Each point's residual, the average and the worst are reported, with how
far that moves the building corners and where they then lie.

Positions are property metres (x east, z north of the site origin).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .site_references import ROAD_MAP_ACCURACY_METERS, _road_crossings, compass

Point = tuple[float, float]
STATIONS = (12.0, 18.0, 24.0, 30.0, 36.0)  # metres either side of a crossing, clear of the crossing itself
WINDOW_METERS = 20.0   # how far across a road its paved strip is looked for
ROAD_WIDTHS = {"railroad": (3.0, 16.0)}
DEFAULT_WIDTHS = (4.0, 28.0)
MAX_PHOTO_OFFSET_METERS = 20.0
MIN_CROSSING_DEGREES = 20.0
MAX_CENTRE_SPREAD_METERS = 1.5


def rigid_fit(pairs: Sequence[tuple[Point, Point]]) -> dict[str, Any] | None:
    """The move and turn taking each first point onto its second, least squares; one pair gives a move only."""
    if not pairs:
        return None
    n = len(pairs)
    mx, mz = sum(a[0] for a, _ in pairs) / n, sum(a[1] for a, _ in pairs) / n
    tx, tz = sum(b[0] for _, b in pairs) / n, sum(b[1] for _, b in pairs) / n
    angle = 0.0
    if n > 1:
        cross = sum((a[0] - mx) * (b[1] - tz) - (a[1] - mz) * (b[0] - tx) for a, b in pairs)
        dot = sum((a[0] - mx) * (b[0] - tx) + (a[1] - mz) * (b[1] - tz) for a, b in pairs)
        angle = math.atan2(cross, dot)
    c, s = math.cos(angle), math.sin(angle)

    def apply(point: Point) -> Point:
        dx, dz = point[0] - mx, point[1] - mz
        return tx + dx * c - dz * s, tz + dx * s + dz * c
    residuals = [math.dist(apply(a), b) for a, b in pairs]
    return {"apply": apply, "rotationDegrees": math.degrees(angle), "shift": (tx - mx, tz - mz),
            "residuals": residuals, "averageMeters": sum(residuals) / n, "worstMeters": max(residuals)}


def _nearest_direction(line: Sequence[Point], point: Point) -> Point | None:
    best, direction = math.inf, None
    for a, b in zip(line, line[1:]):
        dx, dz = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dz)
        if length < 1e-6:
            continue
        t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dz) / (length * length)))
        distance = math.dist(point, (a[0] + t * dx, a[1] + t * dz))
        if distance < best:
            best, direction = distance, (dx / length, dz / length)
    return direction


def _strip_middle(paved, photo, point: Point, normal: Point, widths: tuple[float, float]) -> Point | None:
    """The middle of the paved strip that `point` (on the mapped centreline) lies in, across `normal`, or None.

    Only the strip under the mapped line counts. A nearby strip could be another surface the same grey, such as
    the ballast beside a road, and a wrong answer is worse than none."""
    step = photo.dx / 2
    count = int(2 * WINDOW_METERS / step) + 1
    samples = []
    for i in range(count):
        t = -WINDOW_METERS + i * step
        row, col = photo.pixel(point[0] + normal[0] * t, point[1] + normal[1] * t)
        if not (0 <= row < photo.rows and 0 <= col < photo.cols):
            return None  # off the photo
        samples.append((t, bool(paved[row, col])))
    runs, start, previous = [], None, None
    for t, on in samples:
        if on and start is None:
            start = t
        elif not on and start is not None:
            runs.append((start, previous))
            start = None
        previous = t
    if start is not None:
        runs.append((start, previous))
    under = [run for run in runs if run[0] <= 0 <= run[1] and widths[0] <= run[1] - run[0] <= widths[1]
             and run[0] > -WINDOW_METERS + step and run[1] < WINDOW_METERS - step]
    if not under:
        return None
    middle = (under[0][0] + under[0][1]) / 2
    return point[0] + normal[0] * middle, point[1] + normal[1] * middle


def _photo_line(paved, photo, kind: str, line: Sequence[Point], crossing: Point) -> tuple[Point, Point] | None:
    """A straight photo centreline for one road near the crossing: a point on it and its direction."""
    direction = _nearest_direction(line, crossing)
    if direction is None:
        return None
    normal = (-direction[1], direction[0])
    widths = ROAD_WIDTHS.get(kind, DEFAULT_WIDTHS)
    centres = []
    for distance in STATIONS:
        for sign in (-1, 1):
            station = (crossing[0] + sign * distance * direction[0], crossing[1] + sign * distance * direction[1])
            middle = _strip_middle(paved, photo, station, normal, widths)
            if middle is not None:
                centres.append(middle)
    if len(centres) < 3:
        return None
    cx, cz = sum(p[0] for p in centres) / len(centres), sum(p[1] for p in centres) / len(centres)
    sxx = sum((p[0] - cx) ** 2 for p in centres)
    szz = sum((p[1] - cz) ** 2 for p in centres)
    sxz = sum((p[0] - cx) * (p[1] - cz) for p in centres)
    angle = 0.5 * math.atan2(2 * sxz, sxx - szz)
    d = (math.cos(angle), math.sin(angle))
    # The centres must line up: a road's middle wanders less than this along a straight stretch.
    spread = math.sqrt(sum(((p[0] - cx) * d[1] - (p[1] - cz) * d[0]) ** 2 for p in centres) / len(centres))
    if spread > MAX_CENTRE_SPREAD_METERS:
        return None
    return (cx, cz), d


def _cross(first: tuple[Point, Point], second: tuple[Point, Point]) -> Point | None:
    (p, d), (q, e) = first, second
    det = d[0] * e[1] - d[1] * e[0]
    if abs(det) < math.sin(math.radians(MIN_CROSSING_DEGREES)):
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / det
    return p[0] + t * d[0], p[1] + t * d[1]


def photo_vs_map(site: Mapping[str, Any], centre: Point, photo) -> dict[str, Any]:
    """The mapped crossings near the building, each with where the photo shows it."""
    from scipy import ndimage
    from .site_trace import _pavement
    # Roads are read from the raw pavement mask with one light closing (bridging cars and paint): the tracer's heavy
    # closing joins a road to the driveways and yards beside it.
    paved = ndimage.binary_closing(_pavement(photo)[0], structure=ndimage.generate_binary_structure(2, 1), iterations=1)
    points = []
    for crossing in _road_crossings(site, centre):
        mapped = (crossing["x"], crossing["z"])
        lines = [_photo_line(paved, photo, kind, line, mapped) for kind, line in crossing["_roads"]]
        seen = _cross(lines[0], lines[1]) if all(lines) else None
        if seen is not None and math.dist(seen, mapped) > MAX_PHOTO_OFFSET_METERS:
            seen = None
        entry = {"label": crossing["label"], "kind": crossing["kind"], "map": {"x": mapped[0], "z": mapped[1]}}
        if seen is None:
            entry["photo"] = None
            entry["note"] = "The photo does not show both roads clearly here."
        else:
            offset = (mapped[0] - seen[0], mapped[1] - seen[1])
            entry.update(photo={"x": round(seen[0], 2), "z": round(seen[1], 2)},
                         offsetMeters=round(math.hypot(*offset), 2),
                         mapIs=compass(*offset) + " of the photo" if math.hypot(*offset) >= 0.5 else "on the photo point")
        points.append(entry)
    found = [p for p in points if p.get("photo")]
    result = {"points": points, "found": len(found)}
    fit = rigid_fit([((p["photo"]["x"], p["photo"]["z"]), (p["map"]["x"], p["map"]["z"])) for p in found])
    if fit:
        shift = fit["shift"]
        result.update(averageOffsetMeters=round(sum(p["offsetMeters"] for p in found) / len(found), 2),
                      worstOffsetMeters=round(max(p["offsetMeters"] for p in found), 2),
                      mapShiftMeters=round(math.hypot(*shift), 2),
                      mapShiftDirection=compass(*shift) if math.hypot(*shift) >= 0.5 else None,
                      afterMoveAndTurnMeters=round(fit["averageMeters"], 2) if len(found) > 1 else None)
    return result


def survey_fit(site: Mapping[str, Any], layout: Mapping[str, Any]) -> dict[str, Any]:
    """The plan's reference positions fitted onto their measured ones, and what that means for the building."""
    from .geo import from_property
    from .site_context import building_outline
    measured = [r for r in site.get("references") or [] if r.get("measured")]
    if not measured:
        return {"pending": "No reference point has a measured position yet. Enter surveyed positions for at least "
                           "two reference points to fit the plan onto them."}
    fit = rigid_fit([((r["x"], r["z"]), (r["measured"]["x"], r["measured"]["z"])) for r in measured])
    geo = site["georeference"]
    corners = []
    for name, corner in zip("ABCD", building_outline(layout, site)):
        moved = fit["apply"]((corner["x"], corner["z"]))
        latitude, longitude, _ = from_property(moved[0], moved[1], geo["originLatitude"], geo["originLongitude"])
        corners.append({"corner": name, "movesMeters": round(math.dist((corner["x"], corner["z"]), moved), 3),
                        "x": round(moved[0], 3), "z": round(moved[1], 3),
                        "latitude": round(latitude, 8), "longitude": round(longitude, 8)})
    return {"points": [{"referenceId": r["referenceId"], "label": r["label"], "source": r["measured"]["source"],
                        "residualMeters": round(residual, 3)} for r, residual in zip(measured, fit["residuals"])],
            "averageResidualMeters": round(fit["averageMeters"], 3), "worstResidualMeters": round(fit["worstMeters"], 3),
            "moveMeters": round(math.hypot(*fit["shift"]), 3),
            "moveDirection": compass(*fit["shift"]) if math.hypot(*fit["shift"]) >= 0.005 else None,
            "turnDegrees": round(fit["rotationDegrees"], 4), "buildingCorners": corners,
            **({"note": "One measured point fixes position only; measure two or more to fix the turn too."}
               if len(measured) == 1 else {})}


def check_references(site: Mapping[str, Any], layout: Mapping[str, Any], photo=None) -> dict[str, Any]:
    from .site_context import building_outline
    outline = building_outline(layout, site)
    centre = (sum(p["x"] for p in outline) / 4, sum(p["z"] for p in outline) / 4)
    result = {"available": True,
              "photoVsMap": photo_vs_map(site, centre, photo) if photo is not None
              else {"points": [], "found": 0, "note": "The site has no stored photo."},
              "survey": survey_fit(site, layout),
              "accuracy": {"roadMapMeters": ROAD_MAP_ACCURACY_METERS, "photoMeters": 6.0,
                           "note": "The road map's centrelines are good to several metres and the photo to about 6 m; "
                                   "a survey settles it. Stake from a surveyor's control."}}
    lines = []
    check = result["photoVsMap"]
    if check.get("found"):
        lines.append(f"At {check['found']} of {len(check['points'])} mapped crossings near the building the road map "
                     f"is on average {check['averageOffsetMeters']} m from the photo (worst {check['worstOffsetMeters']} m)"
                     + (f"; overall the map sits {check['mapShiftMeters']} m {check['mapShiftDirection']} of the photo."
                        if check.get("mapShiftDirection") else "."))
    survey = result["survey"]
    if "points" in survey:
        lines.append(f"Fitted onto {len(survey['points'])} measured points with a move of {survey['moveMeters']} m and a "
                     f"turn of {survey['turnDegrees']} degrees, the points agree within {survey['worstResidualMeters']} m; "
                     f"the building corners move up to {max(c['movesMeters'] for c in survey['buildingCorners'])} m.")
    result["summary"] = lines
    return result
