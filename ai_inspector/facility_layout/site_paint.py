"""The look the user asks for, as its own package (the step-by-step build: walls and models arrive plain).

Only what the user's prompt names is painted (the user, 2026-10-24: "paint in our colors? I don't like that ...
you need a prompt to say it as well"). Sage passes each item with its colours and nothing else is added: no
logo, band or yard mark unless asked.
- walls: a panel colour, a band along the top when asked, and the logo only on the walls named (a compass side,
  or beside_docks for the two walls either side of the dock wall); artwork added by hand stays;
- pavementLogo: the crosshair logo in the truck yard: the court's asphalt beyond the parked trucks, between its
  arrows (the largest open stretch of yard when there is no court yet, site_plan._ground_marks);
- trucks: cab, container and chassis colours; racks: upright and beam colours;
- cars: the colours named, in turn, or everyday colours.
Colours are names from COLORS, so "cyan" is the same cyan on every run, or #rrggbb.

Sage may colour a model's parts only on a saved placement, with the fingerprint (visualSha256) of the exact
visual those parts belong to (proposal_components.py): one set_component_materials edit per model, each visual
inspected once, read from the saved layout so models added by hand are painted too.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Mapping

from .site_interior import RACK_ASSET, RACK_FINISH
from .site_parking import CAR_ASSETS, PAINT_KEY, paint_for
from .site_trucks import TRUCK_ASSET, TRUCK_FINISH

COLORS = {"white": "#ffffff", "off white": "#f1f1ee", "black": "#16181b", "dark grey": "#2b2f33",
          "grey": "#62676b", "light grey": "#b9bdc1", "silver": "#b4b9be", "cyan": "#06b6d4", "teal": "#0f766e",
          "sky blue": "#38bdf8", "blue": "#1565c0", "deep blue": "#174a7e", "navy": "#1f3a6b", "purple": "#6d28d9",
          "red": "#b3261e", "dark red": "#8e1b1f", "orange": "#f07818", "yellow": "#facc15", "green": "#2e7d32",
          "dark green": "#2e4a37", "brown": "#6e5643", "beige": "#d8cbb0"}
ITEMS = ("walls", "pavementLogo", "trucks", "racks", "cars")
WALL_CHOICES = ("north", "east", "south", "west", "beside_docks")
LOGO_PREFIX = "inspectorpro-logo-"
Inventory = Callable[[str, str], Mapping[str, Any]]  # (placementId, representation) -> {visualSha256, slots}


class PaintError(ValueError):
    """What was asked cannot be painted; the message says why."""


def color(value: Any) -> str:
    text = str(value).strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", text):
        return text
    name = re.sub(r"[\s_-]+", " ", text).replace("gray", "grey").strip()
    if name in COLORS:
        return COLORS[name]
    raise PaintError(f"Unknown colour '{value}'. Use one of: {', '.join(COLORS)}, or #rrggbb.")


def _named(hex_color: str) -> str:
    return next((name for name, value in COLORS.items() if value == hex_color), hex_color)


def _finish(base: Mapping[str, Any], pick: Callable[[str], str]) -> dict:
    return {"representation": base["representation"],
            "overrides": [dict(row, color=pick(row["key"])) for row in base["overrides"]]}


def plan_paint(layout: Mapping[str, Any], inventory: Inventory | None, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Exactly the items in `spec` (ITEMS), in its colours: the walls' finish, the yard's logo, and
    set_component_materials edits for the trucks, racks and cars."""
    spec = {key: value for key, value in (spec or {}).items() if key in ITEMS and value not in (None, False)}
    if not spec:
        raise PaintError("Say what to paint (walls, pavementLogo, trucks, racks or cars) and in which colours.")
    look: dict[str, str] = {}
    finishes: dict[str, dict] = {}
    if "trucks" in spec:
        cab, box, chassis = (color(spec["trucks"][key]) for key in ("cabColor", "containerColor", "chassisColor"))
        finishes["trucks"] = _finish(TRUCK_FINISH, lambda key: box if "Container" in key else
                                     chassis if "Truck-train" in key else cab)
        look["trucks"] = f"{_named(cab)} cabs, {_named(box)} containers, {_named(chassis)} chassis"
    if "racks" in spec:
        upright, beam = color(spec["racks"]["uprightColor"]), color(spec["racks"]["beamColor"])
        finishes["racks"] = _finish(RACK_FINISH, lambda key: upright if "Legs" in key else beam)
        look["racks"] = f"{_named(upright)} uprights, {_named(beam)} beams"
    car_colors = None
    if "cars" in spec:
        car_colors = [color(value) for value in (spec["cars"] if isinstance(spec["cars"], Mapping) else {})
                      .get("colors") or []]
        look["cars"] = ", ".join(_named(c) for c in car_colors) if car_colors else "everyday colours"
    operations, painted, unchanged = _building_paint(layout, spec, look)
    visuals: dict[tuple[str, str, str], tuple[str, set[str]]] = {}
    cars = 0
    for placement in sorted(layout.get("placements") or [], key=lambda item: item["placementId"]):
        asset = placement.get("assetId")
        if asset == TRUCK_ASSET:
            kind = "trucks"
        elif asset in CAR_ASSETS:
            kind = "cars"
            cars += 1  # the planner's car park order: pl-car-park-001, 002, ...
        elif asset == RACK_ASSET:
            kind = "racks"
        else:
            continue
        if kind not in spec or inventory is None:
            continue
        if kind == "cars":
            finish = paint_for(cars - 1)
            if car_colors:
                body = car_colors[(cars - 1) % len(car_colors)]
                finish = {**finish, "overrides": [dict(row, color=body) if row["key"] == PAINT_KEY else row
                                                  for row in finish["overrides"]]}
        else:
            finish = finishes[kind]
        representation = finish["representation"]
        # Every placement of one asset revision shares that visual's bytes, so each visual is inspected once.
        key = (asset, placement["assetDefinitionRevision"], representation)
        if key not in visuals:
            found = inventory(placement["placementId"], representation)
            visuals[key] = (found["visualSha256"], {slot["key"] for slot in found["slots"]})
        fingerprint, slots = visuals[key]
        materials = {"representation": representation,
                     "overrides": [dict(row) for row in finish["overrides"] if row["key"] in slots]}
        if not materials["overrides"]:
            continue  # this visual has none of the planned parts
        if placement.get("componentMaterials") == materials:
            unchanged[kind] += 1
            continue
        operations.append({"op": "set_component_materials", "placementId": placement["placementId"],
                           "materials": materials, "visualSha256": fingerprint})
        painted[kind] += 1
    missing = [kind for kind in spec if not painted[kind] and not unchanged[kind]]
    return {"available": bool(operations), "operations": operations, "painted": dict(painted),
            "alreadyPainted": dict(unchanged), "look": look,
            **({"notPainted": {kind: "nothing saved to paint yet" for kind in missing}} if missing else {}),
            **({} if operations else {"reason": "Nothing saved needs these colours: it already has them, or is not "
                                               "built yet."})}


def _logo_edges(layout: Mapping[str, Any], names: list[str], dock_edge: int) -> list[int]:
    from .site_plan import SIDES
    edges = set()
    for name in names:
        if name == "beside_docks":
            edges |= {(dock_edge + 1) % 4, (dock_edge + 3) % 4}
            continue
        if name not in WALL_CHOICES:
            raise PaintError(f"The logo goes on the north, east, south, west or beside_docks walls, not '{name}'.")
        from .site_steps import Building, StepError, _site
        try:
            building = Building(dict(layout), _site(dict(layout)))
        except StepError as error:
            raise PaintError("Name the logo walls beside_docks: " + str(error)) from error
        edges.add(SIDES.index(building.side_for(name)))
    return sorted(edges)


def _court_mark(layout: Mapping[str, Any]) -> dict | None:
    """The crosshair centred on the truck court's asphalt (past the concrete apron the trucks stand on), half way
    along the dock wall: clear of the court's two rows of arrows (site_trucks.py). None without a court or room."""
    from pathlib import Path
    from .site_plan import APRON_METERS, TARGET_IMAGE, TARGET_METERS, TARGET_UV
    from .site_trucks import ZONE_ID
    court = next((z for z in layout.get("zones") or [] if z.get("zoneId") == ZONE_ID), None)
    openings = ((layout.get("extensions") or {}).get("facilityPerimeterWalls") or {}).get("settings", {}).get("openings") or []
    doors = Counter(o["edge"] for o in openings if abs(o["endMeters"] - o["startMeters"] - 3.0) < 0.05)
    if not court or not doors or not (Path(__file__).resolve().parents[2] / TARGET_IMAGE.lstrip("/")).is_file():
        return None
    xs, zs = [float(p["x"]) for p in court["boundary"]], [float(p["z"]) for p in court["boundary"]]
    edge = doors.most_common(1)[0][0]  # walls: 0 at z = 0, 1 at x = width, 2 at z = depth, 3 at x = 0
    across = edge in (1, 3)  # the court runs out along x from an east or west wall
    near, far = ((min(xs), max(xs)) if edge == 1 else (max(xs), min(xs)) if edge == 3
                 else (max(zs), min(zs)) if edge == 0 else (min(zs), max(zs)))
    depth = abs(far - near)
    size = min(TARGET_METERS, 0.6 * (depth - APRON_METERS))
    if size < 6.0:
        return None
    out = near + (far - near) * (APRON_METERS + depth) / (2 * depth)
    along = (min(zs) + max(zs)) / 2 if across else (min(xs) + max(xs)) / 2
    x, z = (out, along) if across else (along, out)
    return {"markId": "gm-target", "label": "Crosshair target", "imagePath": TARGET_IMAGE,
            "uv": [round(v, 6) for v in TARGET_UV], "x": round(x, 3), "z": round(z, 3),
            "widthMeters": round(size, 3), "depthMeters": round(size, 3), "rotationDegrees": 0.0}


def _building_paint(layout: Mapping[str, Any], spec: Mapping[str, Any], look: dict) -> tuple[list, Counter, Counter]:
    """The walls' finish (a patch that keeps the openings) and the yard's logo, when asked and not already there."""
    from .site_plan import _ground_marks, _wall_finish
    operations, painted, unchanged = [], Counter(), Counter()
    extensions = layout.get("extensions") or {}
    walls = (extensions.get("facilityPerimeterWalls") or {}).get("settings")
    plan = extensions.get("facilityPlan") or {}
    wall_spec = spec.get("walls")
    if wall_spec and walls and plan.get("widthMeters"):
        openings = walls.get("openings") or []
        doors = Counter(o["edge"] for o in openings if abs(o["endMeters"] - o["startMeters"] - 3.0) < 0.05)
        dock_edge = doors.most_common(1)[0][0] if doors else 0
        panels = color(wall_spec["color"])
        band = color(wall_spec["bandColor"]) if wall_spec.get("bandColor") else None
        names = list(wall_spec.get("logoWalls") or [])
        finish = _wall_finish(float(plan["widthMeters"]), float(plan["depthMeters"]),
                              float(walls.get("heightMeters", 10.0)), dock_edge, openings,
                              color=panels, band_color=band, logo_edges=_logo_edges(layout, names, dock_edge))
        saved = walls.get("exteriorFinish") or {}
        kept = [art for art in saved.get("artworks") or [] if not str(art.get("artworkId", "")).startswith(LOGO_PREFIX)]
        logos = finish.get("artworks") or []
        finish["artworks"] = kept + logos
        finish.setdefault("bands", [])
        if all(saved.get(key, [] if isinstance(value, list) else None) == value for key, value in finish.items()):
            unchanged["walls"] += 1
        else:
            operations.append({"op": "edit_perimeter_walls", "patch": {"exteriorFinish": finish}})
            painted["walls"] += 1
        look["walls"] = (f"{_named(panels)} panels" + (f", a {_named(band)} band along the top" if band else "")
                         + (f", the logo on {len(logos)} wall{'s' if len(logos) != 1 else ''} ({', '.join(names)})"
                            if logos else "")
                         + (" (no named wall had room for the logo clear of its doors)" if names and not logos else ""))
    ground = extensions.get("facilityGround") or {}
    if spec.get("pavementLogo") and ground.get("surfaces"):
        court = _court_mark(layout)
        marks = [court] if court else _ground_marks(ground["surfaces"])
        if marks and ground.get("marks") == marks:
            unchanged["pavementLogo"] += 1
        elif marks:
            operations.append({"op": "set_ground", "ground": {**ground, "marks": marks}})
            painted["pavementLogo"] += 1
        if marks:
            look["pavementLogo"] = ("the crosshair logo in the truck court, beyond the parked trucks" if court
                                    else "the crosshair logo on the largest open stretch of yard")
    return operations, painted, unchanged
