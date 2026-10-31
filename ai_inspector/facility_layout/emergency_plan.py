"""Emergency teams, meeting points, shelters and restrooms of a layout (extensions.facilityEmergencyPlan), the safety
items placed in it, and a first suggestion of teams for Sage to stage with set_emergency_plan.

The evacuation and emergency maps (emergency_pdf.py) draw from this. Safety items are ordinary placements: a catalog
tag on the model (fire-extinguisher, first-aid, ...) says which map symbol it gets. Nothing here is a code check:
the facility's own emergency action plan and the fire marshal decide exits, routes and equipment.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Callable, Sequence

KEY = "facilityEmergencyPlan"
MAX_TEAMS = 8
MAX_ZONES = 200
TEAM_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
COLOR = re.compile(r"#[0-9a-fA-F]{6}")
PHONE = re.compile(r"[0-9+() .\-]{3,40}")

# Map symbols by catalog tag, in legend order.
SYMBOLS = (
    ("emergency-exit", "exit", "Emergency exit"),
    ("first-aid", "first_aid", "First aid kit"),
    ("aed", "aed", "AED"),
    ("eyewash", "eyewash", "Eyewash"),
    ("spill-kit", "spill_kit", "Spill kit"),
    ("fire-extinguisher", "extinguisher", "Fire extinguisher"),
    ("electrical-panel", "panel", "Electrical panel"),
    ("fire-riser", "riser", "Fire riser"),
    ("ppe-vending", "ppe", "PPE vending"),
    ("assembly-point", "assembly", "Assembly point"),
)
# aed placements also carry first-aid; the more specific tag wins.
_TAG_ORDER = ("emergency-exit", "aed", "eyewash", "first-aid", "spill-kit", "fire-extinguisher", "electrical-panel",
              "fire-riser", "ppe-vending", "assembly-point")
_SYMBOL_BY_TAG = {tag: symbol for tag, symbol, _ in SYMBOLS}

TEAM_COLORS = {"production": "#DC2626", "warehouse": "#2563EB", "office": "#16A34A"}
TEAM_NAMES = {"production": "Red Team - Production", "warehouse": "Blue Team - Warehouse",
              "office": "Green Team - Office"}
_OFFICE_WORDS = ("office", "lunch", "cafeteria", "kitchen", "conference", "meeting", "boardroom", "gym", "break",
                 "training", "reception", "locker", "dining")
_WAREHOUSE_WORDS = ("receiving", "dispatch", "shipping", "storage", "warehouse", "finished goods", "raw stock", "rack",
                    "inventory", "staging", "pallet")
_OUTDOOR_WORDS = ("parking", "yard", "truck", "road", "drive", "court", "outdoor", "apron", "car park")
_RESTROOM_WORDS = ("restroom", "toilet", "washroom", "lavatory")


def _ids(value, known: set[str], name: str, limit: int = MAX_ZONES) -> list[str]:
    if not isinstance(value, list) or len(value) > limit or len(set(map(str, value))) != len(value):
        raise ValueError(f"{name} must be a list of up to {limit} distinct zone IDs")
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise ValueError(f"{name}: zone {item!r} is not in this layout")
    return list(value)


def _text(value, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must contain 1 to {limit} characters")
    return value.strip()


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e5:
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def normalize_emergency_plan(value: Any, layout: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("version") != 1 or type(value.get("version")) is not int:
        raise ValueError("Unsupported emergency plan (version 1 expected)")
    allowed = {"version", "teams", "shelterZoneIds", "restroomZoneIds", "phone"}
    if set(value) - allowed or not {"version", "teams"} <= set(value):
        raise ValueError("Emergency plan fields: version, teams, shelterZoneIds, restroomZoneIds, phone")
    zones = {z.get("zoneId") for z in layout.get("zones") or []}
    placements = {p.get("placementId") for p in layout.get("placements") or []}
    teams = value["teams"]
    if not isinstance(teams, list) or len(teams) > MAX_TEAMS:
        raise ValueError(f"An emergency plan has at most {MAX_TEAMS} teams")
    result_teams, team_ids, team_zones = [], set(), set()
    for team in teams:
        if not isinstance(team, Mapping) or set(team) != {"teamId", "name", "color", "zoneIds", "meetingPoint"}:
            raise ValueError("Each team needs teamId, name, color, zoneIds and meetingPoint")
        team_id = team["teamId"]
        if not isinstance(team_id, str) or not TEAM_ID.fullmatch(team_id) or team_id in team_ids:
            raise ValueError("Each team needs a unique lower-case teamId")
        team_ids.add(team_id)
        if not isinstance(team["color"], str) or not COLOR.fullmatch(team["color"]):
            raise ValueError("Team colours are six-digit #rrggbb")
        zone_ids = _ids(team["zoneIds"], zones, f"Team {team_id} zoneIds")
        if not zone_ids:
            raise ValueError(f"Team {team_id} needs at least one zone")
        if team_zones & set(zone_ids):
            raise ValueError("A zone belongs to at most one team")
        team_zones |= set(zone_ids)
        point = team["meetingPoint"]
        if not isinstance(point, Mapping) or "label" not in point or set(point) - {"label", "placementId", "position"} \
                or len(set(point) & {"placementId", "position"}) != 1:
            raise ValueError("A meeting point has a label and either a placementId or a position {x, z}")
        meeting = {"label": _text(point["label"], "Meeting point label", 120)}
        if "placementId" in point:
            if point["placementId"] not in placements:
                raise ValueError(f"Meeting point placement {point['placementId']!r} is not in this layout")
            meeting["placementId"] = point["placementId"]
        else:
            position = point["position"]
            if not isinstance(position, Mapping) or set(position) != {"x", "z"}:
                raise ValueError("A meeting point position is {x, z} in layout metres")
            meeting["position"] = {"x": _number(position["x"], "x"), "z": _number(position["z"], "z")}
        result_teams.append({"teamId": team_id, "name": _text(team["name"], "Team name", 80),
                             "color": team["color"].upper(), "zoneIds": zone_ids, "meetingPoint": meeting})
    result = {"version": 1, "teams": result_teams,
              "shelterZoneIds": _ids(value.get("shelterZoneIds", []), zones, "shelterZoneIds"),
              "restroomZoneIds": _ids(value.get("restroomZoneIds", []), zones, "restroomZoneIds")}
    if value.get("phone") is not None:
        phone = value["phone"]
        if not isinstance(phone, str) or not PHONE.fullmatch(phone.strip()):
            raise ValueError("phone holds digits, spaces and + ( ) . - only")
        result["phone"] = phone.strip()
    return result


def plan_from_layout(layout: Mapping[str, Any]) -> dict[str, Any] | None:
    """The stored plan, dropping references to zones or placements deleted since it was set."""
    raw = (layout.get("extensions") or {}).get(KEY)
    if not isinstance(raw, Mapping):
        return None
    zones = {z.get("zoneId") for z in layout.get("zones") or []}
    placements = {p.get("placementId") for p in layout.get("placements") or []}
    teams = []
    for team in raw.get("teams") or []:
        point = dict(team.get("meetingPoint") or {})
        if point.get("placementId") and point["placementId"] not in placements:
            continue
        teams.append(dict(team, zoneIds=[z for z in team.get("zoneIds") or [] if z in zones], meetingPoint=point))
    return dict(raw, teams=teams,
                shelterZoneIds=[z for z in raw.get("shelterZoneIds") or [] if z in zones],
                restroomZoneIds=[z for z in raw.get("restroomZoneIds") or [] if z in zones])


# --- geometry -----------------------------------------------------------------------------------------------------
Point = tuple[float, float]


def _xz(value: Mapping[str, Any]) -> Point:
    return float(value.get("x") or 0), float(value.get("z") or 0)


def polygon_area(points: Sequence[Point]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, list(points[1:]) + [points[0]]))) / 2


def centroid(points: Sequence[Point]) -> Point:
    twice, cx, cz = 0.0, 0.0, 0.0
    for a, b in zip(points, list(points[1:]) + [points[0]]):
        cross = a[0] * b[1] - b[0] * a[1]
        twice += cross
        cx += (a[0] + b[0]) * cross
        cz += (a[1] + b[1]) * cross
    if abs(twice) < 1e-9:
        return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    return cx / (3 * twice), cz / (3 * twice)


def contains(polygon: Sequence[Point], point: Point) -> bool:
    x, z = point
    inside = False
    for (x0, z0), (x1, z1) in zip(polygon, list(polygon[1:]) + [polygon[0]]):
        if (z0 > z) != (z1 > z) and x < x0 + (z - z0) * (x1 - x0) / (z1 - z0):
            inside = not inside
    return inside


def zone_points(zone: Mapping[str, Any]) -> list[Point]:
    return [_xz(p) for p in zone.get("boundary") or []]


def _hidden(zone: Mapping[str, Any]) -> bool:
    return ((zone.get("extensions") or {}).get("style") or {}).get("labelHidden") is True


def _words(zone: Mapping[str, Any]) -> str:
    return f" {zone.get('label') or ''} {zone.get('zoneType') or ''} ".lower()


def is_outdoor(zone: Mapping[str, Any]) -> bool:
    """A lot, yard or road; an annex named for its offices and its parking is not."""
    text = _words(zone)
    return any(word in text for word in _OUTDOOR_WORDS) and not any(word in text for word in _OFFICE_WORDS)


def is_restroom(zone: Mapping[str, Any]) -> bool:
    text = _words(zone)
    return any(word in text for word in _RESTROOM_WORDS) or " wc " in text


def is_parking_lot(zone: Mapping[str, Any]) -> bool:
    text = _words(zone)
    return "parking" in text and not any(word in text for word in _OFFICE_WORDS)


# --- safety items ----------------------------------------------------------------------------------------------------
def symbol_for(tags: Sequence[str]) -> str | None:
    present = set(tags or ())
    for tag in _TAG_ORDER:
        if tag in present:
            return _SYMBOL_BY_TAG[tag]
    return None


def safety_items(layout: Mapping[str, Any], resolve_asset: Callable[[str, str], Any] | None) -> list[dict[str, Any]]:
    """Placements whose model carries a safety tag, with their map symbol."""
    items = []
    for placement in layout.get("placements") or []:
        definition = resolve_asset(str(placement.get("assetId") or ""), str(placement.get("assetDefinitionRevision") or "")) \
            if resolve_asset else None
        symbol = symbol_for((definition or {}).get("tags") or ())
        if not symbol:
            continue
        position = (placement.get("transform") or {}).get("position") or {}
        items.append({"symbol": symbol, "placementId": placement.get("placementId"),
                      "at": (float(position.get("x") or 0), float(position.get("z") or 0)),
                      "label": (placement.get("metadata") or {}).get("instanceLabel")
                      or (definition or {}).get("displayName") or placement.get("assetId")})
    return items


def meeting_point_at(layout: Mapping[str, Any], team: Mapping[str, Any]) -> Point | None:
    point = team.get("meetingPoint") or {}
    if point.get("position"):
        return _xz(point["position"])
    for placement in layout.get("placements") or []:
        if placement.get("placementId") == point.get("placementId"):
            return _xz((placement.get("transform") or {}).get("position") or {})
    return None


def indoor_zones(layout: Mapping[str, Any]) -> list[list[Point]]:
    """The floor people work on: zones not named for parking, yards or roads (an annex named for its parking too is
    left out; its rooms are zones of their own)."""
    return [pts for z in layout.get("zones") or [] if not any(word in _words(z) for word in _OUTDOOR_WORDS)
            and not _hidden(z) and len(pts := zone_points(z)) >= 3]


def farthest_from(points: Sequence[Point], floor: Sequence[Sequence[Point]], step: float = 2.0) -> dict[str, Any] | None:
    """The floor point (inside any of the floor polygons, on a step-metre grid) farthest in a straight line from its
    nearest point in `points`."""
    if not points or not floor:
        return None
    xs = [p[0] for poly in floor for p in poly]
    zs = [p[1] for poly in floor for p in poly]
    worst, at = -1.0, None
    boxes = [(min(p[0] for p in poly), min(p[1] for p in poly), max(p[0] for p in poly), max(p[1] for p in poly), poly)
             for poly in floor]
    x = min(xs) + step / 2
    while x < max(xs):
        z = min(zs) + step / 2
        while z < max(zs):
            if any(b[0] <= x <= b[2] and b[1] <= z <= b[3] and contains(b[4], (x, z)) for b in boxes):
                d = min(math.hypot(x - px, z - pz) for px, pz in points)
                if d > worst:
                    worst, at = d, (x, z)
            z += step
        x += step
    return None if at is None else {"meters": round(worst, 1), "at": {"x": round(at[0], 1), "z": round(at[1], 1)}}


# --- a first suggestion for Sage ----------------------------------------------------------------------------------------
def _group(zone: Mapping[str, Any]) -> str | None:
    """warehouse or office from the zone's own words, "" when it has neither, None when it is no team's area."""
    text = _words(zone)
    if _hidden(zone) or is_outdoor(zone) or is_restroom(zone) or " wall " in text:
        return None
    if any(word in text for word in _WAREHOUSE_WORDS):
        return "warehouse"
    if any(word in text for word in _OFFICE_WORDS):
        return "office"
    return ""


def suggest_emergency_plan(layout: Mapping[str, Any], resolve_asset=None) -> dict[str, Any]:
    """Teams from zone names and types (production, warehouse, office), each the largest zones that are not inside
    another zone of the same team and do not mix teams; meeting points in the parking lots, the largest team to the
    largest lot, at an assembly-point sign there when there is one. Restrooms from zone names. Shelters are left to
    the user: which rooms can shelter people is a structural question."""
    zones = [z for z in layout.get("zones") or [] if len(zone_points(z)) >= 3]
    by_id = {z["zoneId"]: z for z in zones}
    shapes = {z["zoneId"]: zone_points(z) for z in zones}

    def inside(inner: str, outer: str) -> bool:
        return inner != outer and all(contains(shapes[outer], p) or _on_edge(shapes[outer], p) for p in shapes[inner])

    containers = {zid: sorted((o for o in shapes if inside(zid, o)), key=lambda o: polygon_area(shapes[o]))
                  for zid in shapes}
    groups = {}
    for zid, zone in by_id.items():
        group = _group(zone)
        if group is not None and any(is_outdoor(by_id[o]) for o in containers[zid]):
            group = None  # inside a yard or a lot
        if group == "":  # no words of its own: the nearest container that has them, else production
            group = next((g for o in containers[zid] if (g := _group(by_id[o]))), "production")
        groups[zid] = group
    # A container that mixes teams (an annex with offices and parking) is left out; its rooms are listed instead.
    mixed = {zid for zid, group in groups.items() if group is not None and any(
        groups[c] not in (None, group) or is_parking_lot(by_id[c]) for c in shapes if inside(c, zid))}
    chosen: dict[str, list[str]] = {"production": [], "warehouse": [], "office": []}
    for zid, group in groups.items():
        if group is None or zid in mixed:
            continue
        if any(groups[o] == group and o not in mixed for o in containers[zid]):
            continue  # inside a larger zone of the same team
        chosen[group].append(zid)
    teams = [(g, ids) for g, ids in chosen.items() if ids]
    teams.sort(key=lambda t: -sum(polygon_area(shapes[i]) for i in t[1]))
    lots = sorted((z for z in zones if is_parking_lot(z)), key=lambda z: -polygon_area(shapes[z["zoneId"]]))
    signs = [item for item in safety_items(layout, resolve_asset) if item["symbol"] == "assembly"] if resolve_asset else []
    plan_teams, notes = [], []
    for index, (group, ids) in enumerate(teams):
        if lots:
            lot = lots[min(index, len(lots) - 1)]
            label = re.sub(r"\s*-\s*\d+\s+spaces?$", "", str(lot.get("label") or "Parking"), flags=re.I)
            sign = next((s for s in signs if contains(shapes[lot["zoneId"]], s["at"])), None)
            point = {"label": label, "placementId": sign["placementId"]} if sign else \
                {"label": label, "position": dict(zip("xz", map(lambda v: round(v, 2), centroid(shapes[lot["zoneId"]]))))}
            if not sign:
                notes.append(f"No assembly-point sign in {label}: the meeting point is the lot's middle.")
        else:
            point = {"label": "Outside - choose a meeting point", "position": {"x": 0.0, "z": 0.0}}
            notes.append("The layout has no parking lot: ask the user where each team meets.")
        plan_teams.append({"teamId": f"{group}-team", "name": TEAM_NAMES[group], "color": TEAM_COLORS[group],
                           "zoneIds": ids, "meetingPoint": point})
    restrooms = [z["zoneId"] for z in zones if is_restroom(z)]
    plan = {"version": 1, "teams": plan_teams, "shelterZoneIds": [], "restroomZoneIds": restrooms}
    current = plan_from_layout(layout)
    if current and current.get("phone"):
        plan["phone"] = current["phone"]
    if current:
        plan["shelterZoneIds"] = list(current.get("shelterZoneIds") or [])
    names = {z["zoneId"]: z.get("label") or z["zoneId"] for z in zones}
    return {"plan": plan, "operation": {"op": "set_emergency_plan", "emergencyPlan": plan},
            "teams": [{"name": t["name"], "zones": [names[i] for i in t["zoneIds"]],
                       "meetingPoint": t["meetingPoint"]["label"]} for t in plan_teams],
            "restrooms": [names[i] for i in restrooms], "notes": notes + [
                "Shelters are not suggested: which rooms can shelter people in severe weather is the user's (and a "
                "structural engineer's) call."]}


def _on_edge(polygon: Sequence[Point], point: Point, tolerance: float = 1e-6) -> bool:
    for a, b in zip(polygon, list(polygon[1:]) + [polygon[0]]):
        ax, az, bx, bz = *a, *b
        length = math.hypot(bx - ax, bz - az)
        if length < tolerance:
            continue
        t = max(0.0, min(1.0, ((point[0] - ax) * (bx - ax) + (point[1] - az) * (bz - az)) / length ** 2))
        if math.hypot(point[0] - (ax + t * (bx - ax)), point[1] - (az + t * (bz - az))) <= tolerance:
            return True
    return False
