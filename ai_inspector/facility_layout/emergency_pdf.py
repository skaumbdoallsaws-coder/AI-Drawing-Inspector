"""Evacuation map and emergency map of a facility layout: one 11 x 17 in poster page each, beside the plan sheets.

The evacuation map shows each team's area in its colour, a star at every exit, each team's meeting point and the
line telling people what to do. The emergency map shows the floor plan in black with a symbol at every safety item
(fire extinguishers, first aid kits, AEDs, eyewash, spill kits, electrical panels, fire risers, PPE vending, exits),
the restrooms and shelters the plan names, and the assembly areas. Both come from the saved layout only: the
placements' catalog tags give the symbols (emergency_plan.SYMBOLS) and extensions.facilityEmergencyPlan the teams.

They are drawings of what the layout holds, not a code review: the facility's emergency action plan governs.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .emergency_plan import (SYMBOLS, centroid, farthest_from, indoor_zones, meeting_point_at, plan_from_layout,
                             safety_items, zone_points)
from .pdf_canvas import Document, Page, text_width
from .plan_pdf import FOOT, PT_PER_INCH, AssetResolver, View, _logo, _wrap, length_label, load_template

KINDS = ("evacuation", "emergency")
NOTE = ("Generated from the saved layout. Check exits, routes and equipment on site; the facility's emergency "
        "action plan governs.")
INSTRUCTION = "Proceed to any exit door and continue to your meeting point for evacuation roll call."
EXIT_GREEN, EXIT_RED = "#15803D", "#C8102E"
INK, MUTED, RULE = "#18212A", "#596A76", "#ABBAC4"
SYMBOL_HALF = 6.0  # half the width of a map symbol, in points
LEGEND = {symbol: name for _, symbol, name in SYMBOLS} | {"restroom": "Restroom", "shelter": "Severe weather shelter"}
LEGEND_ORDER = ("exit", "first_aid", "aed", "eyewash", "shelter", "spill_kit", "extinguisher", "panel", "restroom",
                "riser", "ppe", "assembly")
Point = tuple[float, float]


class EmergencyMapError(ValueError):
    """The map cannot be drawn from this layout (no teams for an evacuation map, say)."""


# --- symbols --------------------------------------------------------------------------------------------------------
def star(page: Page, x: float, y: float, r: float, fill: str, stroke: str = "#FFFFFF", width: float = 0.6) -> None:
    points = [(x + (r if i % 2 == 0 else r * 0.45) * math.sin(math.pi * i / 5),
               y + (r if i % 2 == 0 else r * 0.45) * math.cos(math.pi * i / 5)) for i in range(10)]
    page.polygon(points, fill=fill, stroke=stroke, width=width, join=1)


def _square(page: Page, x: float, y: float, s: float, fill: str) -> None:
    page.rect(x - s, y - s, 2 * s, 2 * s, fill=fill, stroke="#FFFFFF", width=0.5)


def _letters(page: Page, x: float, y: float, s: float, text: str, fill: str = "#FFFFFF") -> None:
    size = min(s * 1.25, s * 1.8 / max(text_width(text, 1, "bold"), 0.01))
    page.text(x, y - size * 0.36, text, size=size, font="bold", fill=fill, align="center")


def draw_symbol(page: Page, kind: str, x: float, y: float, s: float = SYMBOL_HALF) -> None:
    """One map symbol centred on (x, y), about 2s wide: ISO 7010-like colours drawn as plain vector shapes."""
    w = "#FFFFFF"
    if kind == "exit":  # the US red EXIT box
        page.rect(x - s * 1.7, y - s * 0.8, s * 3.4, s * 1.6, fill=EXIT_RED, stroke=w, width=0.5)
        page.text(x, y - s * 0.42, "EXIT", size=s * 1.15, font="bold", fill=w, align="center")
    elif kind == "extinguisher":
        _square(page, x, y, s, "#C8102E")
        page.rect(x - s * 0.28, y - s * 0.75, s * 0.56, s * 1.15, fill=w)  # cylinder
        page.rect(x - s * 0.12, y + s * 0.4, s * 0.24, s * 0.22, fill=w)  # valve
        page.path([(x - s * 0.05, y + s * 0.55), (x - s * 0.55, y + s * 0.62), (x - s * 0.7, y + s * 0.2)],
                  stroke=w, width=s * 0.14)  # hose
    elif kind == "first_aid":
        _square(page, x, y, s, "#00843D")
        page.rect(x - s * 0.22, y - s * 0.65, s * 0.44, s * 1.3, fill=w)
        page.rect(x - s * 0.65, y - s * 0.22, s * 1.3, s * 0.44, fill=w)
    elif kind == "aed":
        _square(page, x, y, s, "#00843D")
        r = s * 0.3
        page.circle(x - r * 0.95, y + r * 0.45, r, fill=w)
        page.circle(x + r * 0.95, y + r * 0.45, r, fill=w)
        page.polygon([(x - r * 1.9, y + r * 0.2), (x + r * 1.9, y + r * 0.2), (x, y - s * 0.72)], fill=w)
        page.path([(x + s * 0.12, y + s * 0.5), (x - s * 0.15, y), (x + s * 0.15, y), (x - s * 0.12, y - s * 0.5)],
                  stroke="#C8102E", width=s * 0.13)
    elif kind == "eyewash":
        _square(page, x, y, s, "#00843D")
        eye = [(x + s * 0.75 * math.cos(t), y + s * 0.38 * math.sin(t)) for t in [i * math.pi / 12 for i in range(24)]]
        page.polygon(eye, fill=w)
        page.circle(x, y, s * 0.24, fill="#00843D")
        for dx in (-0.35, 0.0, 0.35):  # water rising to the eye
            page.line((x + s * dx, y - s * 0.85), (x + s * dx * 0.6, y - s * 0.5), stroke=w, width=s * 0.1)
    elif kind == "spill_kit":
        _square(page, x, y, s, "#F2C200")
        page.polygon([(x, y + s * 0.75)] + page.arc_points(x, y - s * 0.2, s * 0.44, math.radians(25),
                                                         math.radians(-205), 14), fill=INK)
    elif kind == "panel":
        page.polygon([(x, y + s), (x + s * 1.1, y - s * 0.85), (x - s * 1.1, y - s * 0.85)], fill="#F9D71C",
                     stroke=INK, width=0.6, join=1)
        page.polygon([(x + s * 0.12, y + s * 0.55), (x - s * 0.28, y - s * 0.12), (x - s * 0.02, y - s * 0.12),
                      (x - s * 0.14, y - s * 0.65), (x + s * 0.28, y + s * 0.02), (x + s * 0.02, y + s * 0.02)],
                     fill=INK)
    elif kind == "riser":
        _square(page, x, y, s, "#C8102E")
        page.rect(x - s * 0.13, y - s * 0.8, s * 0.26, s * 1.6, fill=w)  # pipe
        page.circle(x, y + s * 0.1, s * 0.34, fill=w)  # valve
        page.rect(x - s * 0.55, y + s * 0.45, s * 1.1, s * 0.16, fill=w)  # handwheel
    elif kind == "ppe":
        _square(page, x, y, s, "#1D4ED8")
        _letters(page, x, y, s, "PPE")
    elif kind == "restroom":
        _square(page, x, y, s, "#1D4ED8")
        _letters(page, x, y, s, "WC")
    elif kind == "shelter":
        _square(page, x, y, s, "#6D28D9")
        page.polygon([(x, y + s * 0.75), (x + s * 0.75, y + s * 0.05), (x - s * 0.75, y + s * 0.05)], fill=w)
        page.rect(x - s * 0.5, y - s * 0.7, s, s * 0.75, fill=w)
        page.rect(x - s * 0.15, y - s * 0.7, s * 0.3, s * 0.45, fill="#6D28D9")
    elif kind == "assembly":
        _square(page, x, y, s, "#00843D")
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            tip = (x + dx * s * 0.25, y + dy * s * 0.25)
            back = (x + dx * s * 0.8, y + dy * s * 0.8)
            page.line(back, tip, stroke=w, width=s * 0.14)
        page.circle(x, y, s * 0.16, fill=w)
    else:
        page.circle(x, y, s * 0.6, fill=MUTED)


# --- what is drawn --------------------------------------------------------------------------------------------------
class MapData:
    def __init__(self, layout: Mapping[str, Any], resolve_asset: AssetResolver | None):
        from .spatial import OVERHEAD_MINIMUM_CLEARANCE, placement_spatial_records
        self.layout = layout
        self.plan = plan_from_layout(layout)
        self.zones = [z for z in layout.get("zones") or [] if len(z.get("boundary") or []) >= 3]
        self.safety = safety_items(layout, resolve_asset)
        safety_ids = {item["placementId"] for item in self.safety}
        self.walls: list[list[Point]] = []
        self.items: list[list[Point]] = []
        for placement in layout.get("placements") or []:
            definition = resolve_asset(str(placement.get("assetId") or ""),
                                       str(placement.get("assetDefinitionRevision") or "")) if resolve_asset else None
            if not definition or placement.get("placementId") in safety_ids:
                continue
            try:
                records = placement_spatial_records(placement, definition)
            except (ValueError, TypeError, KeyError):
                continue
            if records and not placement.get("snapRelationship") \
                    and min(r.minimum_y for r in records) >= OVERHEAD_MINIMUM_CLEARANCE:
                continue  # roof structure and services are left to 3D, as on the floor plan
            polygons = [list(record.polygon) for record in records]
            (self.walls if "wall" in (definition.get("tags") or ()) else self.items).extend(polygons)
        extensions = layout.get("extensions") or {}
        walls = extensions.get("facilityPerimeterWalls") or {}
        self.walls += [[(float(p["x"]), float(p["z"])) for p in tri] for tri in walls.get("panels") or [] if len(tri) >= 3]
        self.exits = [item["at"] for item in self.safety if item["symbol"] == "exit"]
        from .plan_pdf import PlanData
        self.exits += [((o["start"][0] + o["end"][0]) / 2, (o["start"][1] + o["end"][1]) / 2)
                       for o in PlanData(layout, None).openings if o["kind"] == "door"]
        zones_by_id = {z.get("zoneId"): z for z in self.zones}
        plan = self.plan or {}
        self.restrooms = [zone_points(zones_by_id[i]) for i in plan.get("restroomZoneIds") or [] if i in zones_by_id]
        self.shelters = [zone_points(zones_by_id[i]) for i in plan.get("shelterZoneIds") or [] if i in zones_by_id]
        self.teams = []
        for team in plan.get("teams") or []:
            self.teams.append(dict(team, polygons=[zone_points(zones_by_id[i]) for i in team["zoneIds"] if i in zones_by_id],
                                   meetingAt=meeting_point_at(layout, team)))
        site = extensions.get("facilitySiteContext") or {}
        geo = site.get("georeference") or {} if isinstance(site, Mapping) else {}
        self.address = str(geo.get("label") or "").strip()

    def bounds(self) -> tuple[float, float, float, float]:
        points = [p for z in self.zones for p in zone_points(z)] + [p for poly in self.walls + self.items for p in poly]
        points += [item["at"] for item in self.safety]
        if not points:
            return -10.0, -10.0, 10.0, 10.0
        xs, zs = [p[0] for p in points], [p[1] for p in points]
        pad = max(max(xs) - min(xs), max(zs) - min(zs)) * 0.02 + 2
        return min(xs) - pad, min(zs) - pad, max(xs) + pad, max(zs) + pad

    def farthest_exit(self) -> dict[str, Any] | None:
        return farthest_from(self.exits, indoor_zones(self.layout), step=3.0)


# --- the poster page ------------------------------------------------------------------------------------------------
class Poster:
    def __init__(self, document: Document, template: Mapping[str, Any]):
        page = template["page"]
        self.width, self.height = page["widthInches"] * PT_PER_INCH, page["heightInches"] * PT_PER_INCH
        self.m = page["marginInches"] * PT_PER_INCH
        self.page = document.add_page(self.width, self.height)
        self.panel_w = 3.3 * PT_PER_INCH
        self.title_h = 70.0
        self.footer_h = 20.0
        m = self.m
        self.panel = (self.width - m - self.panel_w, m + self.footer_h, self.width - m, self.height - m - self.title_h)
        self.drawing = (m + 10, m + self.footer_h + 8, self.panel[0] - 14, self.height - m - self.title_h - 8)
        self.page.rect(m, m, self.width - 2 * m, self.height - 2 * m, stroke=INK, width=1.2)


def _title(poster: Poster, title: str, subtitle: str, accent: str, logo: str | None, template) -> None:
    page, m = poster.page, poster.m
    top = poster.height - m
    page.rect(m, top - poster.title_h, poster.width - 2 * m, poster.title_h, fill="#FFFFFF", stroke=INK, width=1.2)
    page.rect(m, top - 7, poster.width - 2 * m, 7, fill=accent)
    page.text(m + 16, top - 38, title, size=26, font="bold", fill=INK)
    if subtitle:
        page.text(m + 16, top - 56, subtitle, size=10, fill=MUTED)
    brand = template.get("brand") or {}
    first, second = (brand.get("wordmark") or ["Inspector", "Pro"])[:2]
    x = poster.width - m - 14
    second_w = text_width(second, 13, "bold")
    page.text(x, top - 36, second, size=13, font="bold", fill=template["palette"]["accent"], align="right")
    page.text(x - second_w, top - 36, first, size=13, font="bold", fill=template["palette"]["brand"], align="right")
    if logo:
        page.image(logo, x - second_w - text_width(first, 13, "bold") - 34, top - 46, 28, 28)
    page.text(x, top - 50, "Facility layout", size=7, fill=MUTED, align="right")


def _footer(poster: Poster, revision: str, today: str, layout_id: str) -> None:
    page, m = poster.page, poster.m
    y = m + 7
    page.line((m, m + poster.footer_h), (poster.width - m, m + poster.footer_h), stroke=INK, width=0.6)
    page.text(m + 10, y, NOTE, size=7, fill=MUTED)
    page.text(poster.width - m - 10, y, f"InspectorPro  |  {today}  |  revision {(revision or 'unsaved')[:12]}  |  {layout_id}",
              size=7, fill=MUTED, align="right")


def _base(poster: Poster, view: View, data: MapData, *, dark: bool) -> None:
    page = poster.page
    zone_stroke = "#3B4652" if dark else "#B4BDC6"
    for zone in data.zones:
        if ((zone.get("extensions") or {}).get("style") or {}).get("labelHidden") is True:
            continue
        page.polygon(view.ps(zone_points(zone)), stroke=zone_stroke, width=0.3 if dark else 0.35)
    for polygon in data.items:
        if dark:
            page.polygon(view.ps(polygon), stroke="#6B7280", width=0.2)
        else:
            page.polygon(view.ps(polygon), fill="#E9ECEF", stroke="#B9C1C9", width=0.15)
    for polygon in data.walls:
        page.polygon(view.ps(polygon), fill="#000000" if dark else "#4B5563",
                     stroke="#000000" if dark else "#4B5563", width=0.4)


def _view(poster: Poster, data: MapData, template) -> View:
    """A wall map fills its paper: the scale is the smallest whole 10 ft per inch that fits, not a drawing scale."""
    bounds = data.bounds()
    box = poster.drawing
    needed = max((bounds[2] - bounds[0]) / ((box[2] - box[0]) / PT_PER_INCH),
                 (bounds[3] - bounds[1]) / ((box[3] - box[1]) / PT_PER_INCH)) / FOOT
    return View(box, bounds, max(10.0, math.ceil(needed / 10.0) * 10.0))


def _place(boxes: list, x: float, y: float, half_w: float, half_h: float) -> Point:
    """A spot for a symbol at (x, y), nudged clear of the symbols already drawn."""
    def free(cx, cy):
        return not any(cx - half_w < b[2] and b[0] < cx + half_w and cy - half_h < b[3] and b[1] < cy + half_h
                       for b in boxes)
    for ring in (0.0, 1.0, 1.7, 2.4, 3.2):
        for k in range(1 if ring == 0 else 8):
            a = math.pi / 4 * k
            cx, cy = x + math.cos(a) * ring * half_w * 2.2, y + math.sin(a) * ring * half_h * 2.2
            if free(cx, cy):
                boxes.append((cx - half_w, cy - half_h, cx + half_w, cy + half_h))
                return cx, cy
    boxes.append((x - half_w, y - half_h, x + half_w, y + half_h))
    return x, y


def _symbol_at(poster: Poster, boxes: list, kind: str, point: Point, s: float = SYMBOL_HALF) -> None:
    x, y = point
    half_w = s * (1.75 if kind == "exit" else 1.05)
    cx, cy = _place(boxes, x, y, half_w, s * 1.05)
    if (cx, cy) != (x, y):  # a leader back to where the item stands
        poster.page.line((x, y), (cx, cy), stroke=MUTED, width=0.35)
        poster.page.circle(x, y, 0.9, fill=MUTED)
    draw_symbol(poster.page, kind, cx, cy, s)


def _panel_heading(poster: Poster, y: float, text: str) -> float:
    x0, _, x1, _ = poster.panel
    poster.page.text(x0 + 12, y - 9, text.upper(), size=8, font="bold", fill=MUTED)
    poster.page.line((x0 + 12, y - 13), (x1 - 12, y - 13), stroke=RULE, width=0.5)
    return y - 22


def _panel_frame(poster: Poster) -> None:
    x0, y0, x1, y1 = poster.panel
    poster.page.line((x0, y0), (x0, y1), stroke=INK, width=0.8)


def _numbers(poster: Poster, y: float, rows: Sequence[tuple[str, str]]) -> float:
    x0, _, x1, _ = poster.panel
    for name, value in rows:
        names = _wrap(name, (x1 - x0) * 0.42, 7.5)
        values = _wrap(value, (x1 - x0) * 0.42, 7.5, "bold")
        for k in range(max(len(names), len(values))):
            if k < len(names):
                poster.page.text(x0 + 12, y - 8, names[k], size=7.5, fill=MUTED)
            if k < len(values):
                poster.page.text(x1 - 12, y - 8, values[k], size=7.5, font="bold", fill=INK, align="right")
            y -= 10.5
        y -= 2
    return y - 4


def _distance_text(farthest: dict[str, Any] | None) -> str:
    return "-" if not farthest else f"{length_label(farthest['meters'])} (straight line)"


# --- the two maps -----------------------------------------------------------------------------------------------------
def draw_evacuation(poster: Poster, data: MapData, template, logo, name: str) -> dict[str, Any]:
    if not data.teams:
        raise EmergencyMapError("This layout has no emergency teams yet: set teams and meeting points first "
                                "(set_emergency_plan).")
    page = poster.page
    _title(poster, f"{name} Evacuation Map", data.address, EXIT_GREEN, logo, template)
    view = _view(poster, data, template)
    box = poster.drawing
    page.save()
    page.clip_rect(box[0], box[1], box[2] - box[0], box[3] - box[1])
    for team in data.teams:  # team areas under the plan
        for polygon in team["polygons"]:
            page.save()
            page.alpha(fill=0.22)
            page.polygon(view.ps(polygon), fill=team["color"])
            page.restore()
    _base(poster, view, data, dark=False)
    for team in data.teams:
        for polygon in team["polygons"]:
            page.polygon(view.ps(polygon), stroke=team["color"], width=1.4, join=1)
    boxes: list = []
    for at in data.exits:
        x, y = view.p(at)
        cx, cy = _place(boxes, x, y, 6.5, 6.5)
        star(page, cx, cy, 6.5, EXIT_GREEN)
    for team in data.teams:
        if team["meetingAt"] is None:
            continue
        x, y = view.p(team["meetingAt"])
        star(page, x, y, 11, team["color"], stroke=INK, width=0.8)
        label = f"{team['name'].split(' - ')[0].upper()} MEETING POINT"
        w = text_width(label, 7, "bold") + 8
        lx, ly = x + 14, y - 5
        if lx + w > box[2]:
            lx = x - 14 - w
        page.rect(lx, ly, w, 11, fill="#FFFFFF", stroke=team["color"], width=0.9)
        page.text(lx + 4, ly + 3.2, label, size=7, font="bold", fill=INK)
    page.restore()
    # Instruction under the title, across the drawing.
    m = poster.m
    band_top = poster.height - m - poster.title_h
    page.rect(box[0], band_top - 22, box[2] - box[0], 18, fill="#071B2A")
    page.text((box[0] + box[2]) / 2, band_top - 17, INSTRUCTION, size=10.5, font="bold", fill="#FFFFFF", align="center")
    # The panel: teams, legend, numbers.
    _panel_frame(poster)
    x0, _, x1, y1 = poster.panel
    y = _panel_heading(poster, y1 - 6, "Teams and meeting points")
    for team in data.teams:
        page.rect(x0 + 12, y - 16, x1 - x0 - 24, 16, fill=team["color"])
        page.text(x0 + 18, y - 11.5, team["name"].upper(), size=8.5, font="bold", fill="#FFFFFF")
        y -= 16
        lines = _wrap(f"Meeting point - {team['meetingPoint']['label']}", x1 - x0 - 34, 8, "bold")
        zones = {z.get("zoneId"): z.get("label") or z.get("zoneId") for z in data.zones}
        areas = _wrap(", ".join(zones.get(i, i) for i in team["zoneIds"]), x1 - x0 - 34, 6.5)[:4]
        height = 6 + 10 * len(lines) + 8.5 * len(areas) + 4
        page.rect(x0 + 12, y - height, x1 - x0 - 24, height, fill="#FFFFFF", stroke=team["color"], width=1.0)
        ty = y - 13
        for line in lines:
            page.text(x0 + 18, ty, line, size=8, font="bold", fill=INK)
            ty -= 10
        for line in areas:
            page.text(x0 + 18, ty, line, size=6.5, fill=MUTED)
            ty -= 8.5
        y -= height + 8
    y = _panel_heading(poster, y - 2, "Legend")
    star(page, x0 + 22, y - 6, 6.5, EXIT_GREEN, stroke=INK, width=0.4)
    page.text(x0 + 36, y - 9, "Exit door", size=8, fill=INK)
    y -= 18
    star(page, x0 + 22, y - 6, 8, "#9CA3AF", stroke=INK, width=0.6)
    page.text(x0 + 36, y - 9, "Meeting point (team colour)", size=8, fill=INK)
    y -= 18
    page.rect(x0 + 14, y - 11, 16, 9, fill="#FDE2E2", stroke="#DC2626", width=1.2)
    page.text(x0 + 36, y - 9, "Team area (team colour)", size=8, fill=INK)
    y -= 22
    farthest = data.farthest_exit()
    y = _panel_heading(poster, y, "Key numbers")
    _numbers(poster, y, [("Exits", str(len(data.exits))), ("Teams", str(len(data.teams))),
                         ("Farthest floor point from an exit", _distance_text(farthest)),
                         ("Scale", f"1 in = {view.feet_per_inch:g} ft")])
    return {"exits": len(data.exits), "teams": [{"name": t["name"], "meetingPoint": t["meetingPoint"]["label"],
                                                 "zones": len(t["zoneIds"])} for t in data.teams],
            "farthestFromExit": farthest, "feetPerInch": view.feet_per_inch}


def draw_emergency(poster: Poster, data: MapData, template, logo, name: str) -> dict[str, Any]:
    page = poster.page
    subtitle = "  |  ".join(part for part in (data.address, f"Site phone {data.plan['phone']}"
                                              if data.plan and data.plan.get("phone") else "") if part)
    _title(poster, f"{name} Emergency Map", subtitle, EXIT_RED, logo, template)
    view = _view(poster, data, template)
    box = poster.drawing
    page.save()
    page.clip_rect(box[0], box[1], box[2] - box[0], box[3] - box[1])
    for polygon in data.shelters:
        page.save()
        page.alpha(fill=0.18)
        page.polygon(view.ps(polygon), fill="#6D28D9")
        page.restore()
    _base(poster, view, data, dark=True)
    for polygon in data.shelters:
        page.polygon(view.ps(polygon), stroke="#6D28D9", width=1.2, dash=[4, 2])
    for polygon in data.restrooms:
        page.polygon(view.ps(polygon), stroke="#1D4ED8", width=0.9)
    boxes: list = []
    counts: dict[str, int] = {}
    order = {kind: i for i, kind in enumerate(LEGEND_ORDER)}
    # Larger-footprint symbols first (exits), then by legend order, so the common ones get nudged, not the rare.
    for item in sorted(data.safety, key=lambda i: (i["symbol"] != "exit", -order.get(i["symbol"], 99))):
        counts[item["symbol"]] = counts.get(item["symbol"], 0) + 1
        _symbol_at(poster, boxes, item["symbol"], view.p(item["at"]))
    for polygon in data.restrooms:
        counts["restroom"] = counts.get("restroom", 0) + 1
        _symbol_at(poster, boxes, "restroom", view.p(centroid(polygon)))
    for polygon in data.shelters:
        counts["shelter"] = counts.get("shelter", 0) + 1
        _symbol_at(poster, boxes, "shelter", view.p(centroid(polygon)))
    for team in data.teams:
        if team["meetingAt"] is not None:
            x, y = view.p(team["meetingAt"])
            star(page, x, y + 16, 9, team["color"], stroke=INK, width=0.7)
    page.restore()
    _panel_frame(poster)
    x0, _, x1, y1 = poster.panel
    y = _panel_heading(poster, y1 - 6, "Legend")
    for kind in LEGEND_ORDER:
        if not counts.get(kind):
            continue
        draw_symbol(page, kind, x0 + 26, y - 7, 7)
        page.text(x0 + 46, y - 10, LEGEND[kind], size=9, fill=INK)
        page.text(x1 - 12, y - 10, str(counts[kind]), size=9, font="bold", fill=INK, align="right")
        y -= 21
    if data.teams:
        y = _panel_heading(poster, y - 4, "Assembly areas")
        for team in data.teams:
            star(page, x0 + 26, y - 7, 7.5, team["color"], stroke=INK, width=0.5)
            for k, line in enumerate(_wrap(f"{team['name']}: {team['meetingPoint']['label']}", x1 - x0 - 58, 8)[:2]):
                page.text(x0 + 46, y - 10 - k * 9.5, line, size=8, fill=INK)
            y -= 22
    farthest = data.farthest_exit()
    y = _panel_heading(poster, y - 4, "Key numbers")
    _numbers(poster, y, [("Safety items", str(len(data.safety))),
                         ("Farthest floor point from an exit", _distance_text(farthest)),
                         ("Scale", f"1 in = {view.feet_per_inch:g} ft")])
    return {"counts": {LEGEND[k]: v for k, v in counts.items()}, "farthestFromExit": farthest,
            "teams": [t["name"] for t in data.teams], "feetPerInch": view.feet_per_inch}


def render_emergency_pdf(layout: Mapping[str, Any], resolve_asset: AssetResolver | None = None, *, kind: str,
                         revision: str = "", now: datetime | None = None,
                         template: Mapping[str, Any] | None = None) -> tuple[bytes, dict[str, Any]]:
    """The evacuation or emergency map as PDF bytes, with the numbers it shows."""
    if kind not in KINDS:
        raise EmergencyMapError(f"Unknown map kind {kind!r}")
    template = template or load_template()
    data = MapData(layout, resolve_asset)
    name = layout.get("displayName") or layout.get("layoutId") or "Facility"
    title = "Evacuation Map" if kind == "evacuation" else "Emergency Map"
    document = Document(title=f"{name} - {title}", author="InspectorPro", subject=f"Facility {title.lower()}")
    logo = _logo(document, template)
    poster = Poster(document, template)
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    info = (draw_evacuation if kind == "evacuation" else draw_emergency)(poster, data, template, logo, name)
    _footer(poster, revision, today, str(layout.get("layoutId") or ""))
    return document.to_bytes(), dict(info, kind=kind, paper="11 x 17 in (tabloid), landscape")


__all__ = ["KINDS", "EmergencyMapError", "render_emergency_pdf", "draw_symbol", "FOOT"]
