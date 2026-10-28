"""2D plan PDF of a facility layout, drawn on the one reusable sheet template.

plan_sheet_template.json is the template every plan uses: an 11 x 17 in landscape frame with a title strip
(brand, project, sheet, key numbers, legend, notes, sheet number) and the style of every kind of object. Any
saved layout fills it from its own data. A layout placed on a site gets a site plan and a floor plan; one
without a site gets the floor plan only. Dimensions are feet and inches with metres in brackets.

Geometry is the layout's own, in metres on the layout X/Z frame. +Z is plan north and is drawn up the sheet,
as in the app's Plan view; the north arrow points to true north from the building pose's bearing.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .errors import FacilityLayoutError
from .pdf_canvas import Document, Page, color, text_width

TEMPLATE_PATH = Path(__file__).with_name("plan_sheet_template.json")
APP_ROOT = Path(__file__).resolve().parents[2]
SITE_KEY = "facilitySiteContext"
PT_PER_INCH = 72.0
FOOT = 0.3048
SQFT_PER_M2 = 10.7639104
M2_PER_ACRE = 4046.8564224
DOCK_DOOR_MIN_WIDTH = 2.5  # openings at least this wide are dock doors, narrower ones personnel doors
MIN_TEXT_POINTS = 3.5  # painted words shrink to fit their marking down to this size, then are left out

Point = tuple[float, float]
AssetResolver = Callable[[str, str], "Mapping[str, Any] | None"]


# --- units -----------------------------------------------------------------------------------------------
def feet_inches(meters: float) -> str:
    inches = round(abs(meters) / 0.0254)
    feet, rest = divmod(inches, 12)
    sign = "-" if meters < 0 and inches else ""
    return f"{sign}{feet:,}'-{rest}\"" if feet else f'{sign}{rest}"'


def length_label(meters: float) -> str:
    return f"{feet_inches(meters)} ({meters:,.1f} m)"


def area_label(square_meters: float) -> str:
    return f"{square_meters * SQFT_PER_M2:,.0f} SF ({square_meters:,.0f} m\xb2)"


def quadrant_bearing(degrees: float) -> str:
    """A compass bearing as a surveyor writes it: N 87 deg 34' 12" E."""
    d = degrees % 360
    if d <= 90:
        ns, ew, angle = "N", "E", d
    elif d <= 180:
        ns, ew, angle = "S", "E", 180 - d
    elif d <= 270:
        ns, ew, angle = "S", "W", d - 180
    else:
        ns, ew, angle = "N", "W", 360 - d
    whole, rest = divmod(round(angle * 3600), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{ns} {whole}\xb0{minutes:02d}'{seconds:02d}\" {ew}"


def _true_bearing(start: Point, end: Point) -> float:
    """Compass bearing from one property-frame point (x east, z north) to another."""
    return math.degrees(math.atan2(end[0] - start[0], end[1] - start[1])) % 360


# --- geometry --------------------------------------------------------------------------------------------
def _area(points: Sequence[Point]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, list(points[1:]) + [points[0]])) / 2.0


def _centroid(points: Sequence[Point]) -> Point:
    area = _area(points)
    if abs(area) < 1e-9:
        return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    cx = cz = 0.0
    for a, b in zip(points, list(points[1:]) + [points[0]]):
        cross = a[0] * b[1] - b[0] * a[1]
        cx += (a[0] + b[0]) * cross
        cz += (a[1] + b[1]) * cross
    return cx / (6 * area), cz / (6 * area)


def _box(points: Sequence[Point]) -> tuple[float, float, float, float]:
    xs, zs = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(zs), max(xs), max(zs)


def _rotated_box(cx: float, cz: float, width: float, depth: float, degrees: float) -> list[Point]:
    """A floor marking's rectangle: width along its local X, depth along its local Z, turned about +Y."""
    t = math.radians(degrees)
    c, s = math.cos(t), math.sin(t)
    return [(cx + a * c + b * s, cz - a * s + b * c)
            for a, b in ((-width / 2, -depth / 2), (width / 2, -depth / 2), (width / 2, depth / 2), (-width / 2, depth / 2))]


def _inside(point: Point, rect: tuple[float, float, float, float] | None) -> bool:
    return rect is not None and rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def _xz(value: Any) -> Point:
    if isinstance(value, Mapping):
        return float(value["x"]), float(value["z"])
    return float(value[0]), float(value[1])


def _short_road(name: str) -> str:
    """'St Croix Trl N (State Hwy 95, 3rd St N)' -> 'St Croix Trl N (State Hwy 95)'."""
    match = re.match(r"\s*([^()]+?)\s*\(([^,()]+)", name or "")
    return f"{match.group(1)} ({match.group(2).strip()})" if match else (name or "").strip()


def _asset_kind(asset_id: str, definition: Mapping[str, Any] | None) -> str:
    text = " ".join(str(v) for v in (asset_id, (definition or {}).get("displayName", ""),
                                     (definition or {}).get("category", ""))).lower()
    for kind, words in (("forklift", ("forklift", "lift truck", "reach truck")), ("truck", ("truck", "trailer")),
                        ("rack", ("rack",)), ("car", ("pickup", " car", "-car", "sedan", "suv", "vehicle", "van"))):
        if any(word in text for word in words):
            return kind
    return "equipment"


# --- the layout, read once ---------------------------------------------------------------------------------
class PlanData:
    """Everything the sheets draw, in layout metres."""

    def __init__(self, layout: Mapping[str, Any], resolve_asset: AssetResolver | None):
        self.layout = layout
        extensions = layout.get("extensions") or {}
        plan = extensions.get("facilityPlan") or {}
        self.width = float(plan.get("widthMeters") or 0)
        self.depth = float(plan.get("depthMeters") or 0)
        self.building = (0.0, 0.0, self.width, self.depth) if self.width and self.depth else None
        walls = extensions.get("facilityPerimeterWalls") or {}
        self.wall_settings = walls.get("settings") or {}
        self.wall_panels = [[_xz(p) for p in tri] for tri in walls.get("panels") or [] if len(tri) >= 3]
        ground = extensions.get("facilityGround") or {}
        self.ground = list(ground.get("surfaces") or [])
        self.ground_marks = list(ground.get("marks") or [])
        self.floors = list((extensions.get("facilityFloorSurfaces") or {}).get("surfaces") or [])
        self.zones = [z for z in layout.get("zones") or [] if len(z.get("boundary") or []) >= 3]
        self.markings = list(layout.get("floorMarkings") or [])
        self.aisles = [r for r in layout.get("routes") or [] if len(r.get("centerline") or []) >= 2]
        self.site = self._site(layout)
        self.items = self._placements(layout, resolve_asset)
        self.openings = self._openings()

    def _site(self, layout: Mapping[str, Any]) -> dict[str, Any] | None:
        raw = (layout.get("extensions") or {}).get(SITE_KEY)
        if not isinstance(raw, Mapping) or not isinstance(raw.get("property"), Mapping):
            return None
        from .site_context import building_outline, normalize_site_context
        try:
            site = normalize_site_context(raw, layout)
        except (ValueError, KeyError, TypeError):
            return None
        prop = site.get("property") or {}
        if len(prop.get("boundary") or []) < 3:
            return None
        pose = site.get("buildingPose") or {"x": 0.0, "z": 0.0, "bearingDegrees": 0.0}
        b = math.radians(float(pose["bearingDegrees"]))
        c, s = math.cos(b), math.sin(b)

        def local(value: Any) -> Point:  # property frame (+X east, +Z north) -> layout frame
            x, z = _xz(value)
            dx, dz = x - float(pose["x"]), z - float(pose["z"])
            return dx * c - dz * s, dx * s + dz * c

        roads = (site.get("roads") or {}).get("items") or []
        routes = site.get("routes") or raw.get("routes") or []
        return {
            "bearing": float(pose["bearingDegrees"]),
            "north": (-s, c),
            "boundary": [local(p) for p in prop["boundary"]],
            "areas": [{"kind": a.get("kind"), "label": a.get("label") or "", "points": [local(p) for p in a["boundary"]]}
                      for a in site.get("areas") or [] if len(a.get("boundary") or []) >= 3],
            "roads": [{"kind": r.get("kind") or "other", "label": r.get("label") or "",
                       "points": [local(p) for p in r.get("line") or []]} for r in roads if len(r.get("line") or []) >= 2],
            "routes": [{"use": r.get("use"), "mainRoad": r.get("mainRoad") or "", "length": float(r.get("lengthMeters") or 0),
                        "points": [local(p) for p in r.get("points") or []]} for r in routes if len(r.get("points") or []) >= 2],
            "entrances": [{"use": e.get("use"), "width": float(e.get("widthMeters") or 0), "at": local(e)}
                          for e in prop.get("entrances") or []],
            "georeference": site.get("georeference") or {},
            # Setting out works in the property frame (true north); `at` is where each point draws on the plan.
            "references": [dict(item, at=local(item)) for item in site.get("references") or []],
            "corners": [(p["x"], p["z"]) for p in building_outline(layout, site)] if self.width and self.depth else [],
        }

    def _placements(self, layout: Mapping[str, Any], resolve_asset: AssetResolver | None) -> list[dict[str, Any]]:
        from .spatial import placement_spatial_records
        items = []
        for placement in layout.get("placements") or []:
            asset_id = str(placement.get("assetId") or "")
            revision = str(placement.get("assetDefinitionRevision") or "")
            definition = resolve_asset(asset_id, revision) if resolve_asset else None
            polygons: list[list[Point]] = []
            if definition:
                try:
                    polygons = [list(record.polygon) for record in placement_spatial_records(placement, definition)]
                except (ValueError, TypeError, KeyError):
                    polygons = []
            position = (placement.get("transform") or {}).get("position") or {}
            items.append({"kind": _asset_kind(asset_id, definition), "polygons": polygons,
                          "at": (float(position.get("x") or 0), float(position.get("z") or 0)),
                          "label": (placement.get("metadata") or {}).get("instanceLabel")
                          or (definition or {}).get("displayName") or asset_id})
        return items

    def _openings(self) -> list[dict[str, Any]]:
        settings = self.wall_settings
        if settings.get("boundarySource") == "plan" and self.building:
            corners = [(0.0, 0.0), (self.width, 0.0), (self.width, self.depth), (0.0, self.depth)]
        elif settings.get("boundarySource") == "polygon":
            corners = [_xz(p) for p in settings.get("boundary") or []]
        else:
            return []
        if len(corners) < 3:
            return []
        clockwise = _area(corners) < 0
        result, docks = [], 0
        for opening in sorted(settings.get("openings") or [], key=lambda o: (o["edge"], o["startMeters"])):
            a, b = corners[opening["edge"]], corners[(opening["edge"] + 1) % len(corners)]
            length = math.dist(a, b)
            if length <= 0:
                continue
            ux, uz = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            start, end = float(opening["startMeters"]), float(opening["endMeters"])
            width = end - start
            kind = "dock" if width >= DOCK_DOOR_MIN_WIDTH else "door"
            docks += kind == "dock"
            result.append({"kind": kind, "number": docks if kind == "dock" else None, "width": width,
                           "start": (a[0] + ux * start, a[1] + uz * start), "end": (a[0] + ux * end, a[1] + uz * end),
                           "along": (ux, uz), "outward": (-uz, ux) if clockwise else (uz, -ux)})
        return result

    # --- counts for the key numbers ---------------------------------------------------------------------
    def count(self, kind: str, inside: bool | None = None) -> int:
        return sum(1 for item in self.items if item["kind"] == kind
                   and (inside is None or _inside(item["at"], self.building) == inside))

    def stalls(self) -> int:
        return sum(1 for m in self.markings if m.get("markingType") == "parking_box" and m.get("semanticRole") == "parking")


# --- sheet frames ------------------------------------------------------------------------------------------
def load_template(path: Path | str | None = None) -> dict[str, Any]:
    template = json.loads(Path(path or TEMPLATE_PATH).read_text(encoding="utf-8"))
    if template.get("schemaVersion") != 1 or not template.get("sheets"):
        raise ValueError("Unsupported plan sheet template")
    return template


class Frames:
    def __init__(self, template: Mapping[str, Any]):
        page = template["page"]
        self.width, self.height = page["widthInches"] * PT_PER_INCH, page["heightInches"] * PT_PER_INCH
        m = page["marginInches"] * PT_PER_INCH
        strip = template["titleStrip"]["widthInches"] * PT_PER_INCH
        pad, band = template["drawing"]["padding"], template["drawing"]["titleBandHeight"]
        self.frame = (m, m, self.width - m, self.height - m)
        self.strip = (self.width - m - strip, m, self.width - m, self.height - m)
        self.drawing = (m + pad, m + pad + band, self.strip[0] - pad, self.height - m - pad)
        self.band = (m + pad, m + pad * 0.6, self.strip[0] - pad, m + pad + band - 6)


class View:
    """Layout metres -> sheet points at a true scale (1 in = N ft), centred on a box."""

    def __init__(self, box: tuple[float, float, float, float], bounds: tuple[float, float, float, float],
                 feet_per_inch: float):
        self.feet_per_inch = feet_per_inch
        self.k = PT_PER_INCH / (feet_per_inch * FOOT)
        self.ox = (box[0] + box[2]) / 2 - (bounds[0] + bounds[2]) / 2 * self.k
        self.oy = (box[1] + box[3]) / 2 - (bounds[1] + bounds[3]) / 2 * self.k

    def p(self, point: Point) -> Point:
        return self.ox + point[0] * self.k, self.oy + point[1] * self.k

    def ps(self, points: Sequence[Point]) -> list[Point]:
        return [self.p(point) for point in points]


def pick_scale(bounds: tuple[float, float, float, float], box: tuple[float, float, float, float],
               scales: Sequence[float]) -> float:
    width_m, depth_m = bounds[2] - bounds[0], bounds[3] - bounds[1]
    for feet in sorted(scales):
        k = PT_PER_INCH / (feet * FOOT)
        if width_m * k <= box[2] - box[0] and depth_m * k <= box[3] - box[1]:
            return feet
    return max(scales)


# --- drawing primitives -------------------------------------------------------------------------------------
class Sheet:
    def __init__(self, page: Page, template: Mapping[str, Any]):
        self.page, self.template = page, template
        self.styles, self.sizes, self.palette = template["styles"], template["fontSizes"], template["palette"]
        self.legend: list[tuple[str, str]] = []

    def use(self, style: str, swatch: str) -> None:
        if (style, swatch) not in self.legend and self.styles.get(style, {}).get("label"):
            self.legend.append((style, swatch))

    def fill(self, points, style: str, *, alpha: float | None = None, fill=None) -> None:
        s = self.styles[style]
        if alpha is not None:
            self.page.save()
            self.page.alpha(fill=alpha)
        self.page.polygon(points, fill=fill or s["fill"], stroke=s.get("stroke") if alpha is None else None,
                          width=s.get("width", 0.3))
        if alpha is not None:
            self.page.restore()

    def outline(self, points, style: str, *, closed: bool = True, stroke=None, dash=None) -> None:
        s = self.styles[style]
        self.page.path(points, closed=closed, stroke=stroke or s["stroke"], fill=s.get("fill") if closed else None,
                       width=s.get("width", 0.4), dash=dash if dash is not None else s.get("dash"), join=1)

    def label(self, at: Point, text: str, *, size: str = "label", font: str = "regular", fill=None,
              align: str = "center", angle: float = 0.0, halo: bool = False, points: float | None = None) -> float:
        size_pt = points or self.sizes[size]
        if halo:  # a soft white box behind the text, so it reads over lines and fills
            width = text_width(text, size_pt, font)
            t = math.radians(angle)
            c, s = math.cos(t), math.sin(t)
            shift = {"left": 0.0, "center": width / 2, "right": width}[align]
            corners = [(at[0] + (lx - shift) * c - ly * s, at[1] + (lx - shift) * s + ly * c)
                       for lx, ly in ((-1.5, -1.8), (width + 1.5, -1.8), (width + 1.5, size_pt * 0.82),
                                      (-1.5, size_pt * 0.82))]
            self.page.save()
            self.page.alpha(fill=0.85)
            self.page.polygon(corners, fill="#FFFFFF")
            self.page.restore()
        return self.page.text(at[0], at[1], text, size=size_pt, font=font, fill=fill or self.palette["text"],
                              align=align, angle=angle)

    def dimension(self, a: Point, b: Point, side: Point, text: str) -> None:
        """A dimension line between sheet points a and b, set off towards `side` (a unit vector)."""
        s = self.styles["dimension"]
        off, tick = s["offset"], s["tick"]
        a2 = (a[0] + side[0] * off, a[1] + side[1] * off)
        b2 = (b[0] + side[0] * off, b[1] + side[1] * off)
        for p, q in ((a, a2), (b, b2)):
            self.page.line((p[0] + side[0] * 2, p[1] + side[1] * 2), (q[0] + side[0] * 2.5, q[1] + side[1] * 2.5),
                           stroke=s["stroke"], width=s["width"])
        self.page.line(a2, b2, stroke=s["stroke"], width=s["width"])
        dx, dy = b2[0] - a2[0], b2[1] - a2[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        tx, ty = (ux - uy) * 0.7071, (uy + ux) * 0.7071  # architectural ticks: slashes at 45 degrees
        for p in (a2, b2):
            self.page.line((p[0] - tx * tick, p[1] - ty * tick), (p[0] + tx * tick, p[1] + ty * tick),
                           stroke=s["stroke"], width=s["width"] * 2.2)
        angle = math.degrees(math.atan2(uy, ux))
        if angle > 90.01 or angle < -89.99:  # keep text upright
            angle += 180
        t = math.radians(angle)
        normal = (-math.sin(t), math.cos(t))
        mid = ((a2[0] + b2[0]) / 2 + normal[0] * 2, (a2[1] + b2[1]) / 2 + normal[1] * 2)
        self.label(mid, text, size="dimension", angle=angle, halo=True)


def _overlaps(box: tuple[float, float, float, float], others: Sequence[tuple[float, float, float, float]]) -> bool:
    return any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in others)


def _contains(polygon: Sequence[Point], point: Point) -> bool:
    inside = False
    for a, b in zip(polygon, list(polygon[1:]) + [polygon[0]]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            if point[0] < a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
    return inside


def _free_spot(polygon: Sequence[Point], centre: Point, half: float, obstacles, step: float = 6.0) -> Point | None:
    """Of the spots inside a sheet polygon where a two-line label (half-width `half`) covers no obstacle, the one
    nearest `centre`; None when there is none."""
    x0, y0, x1, y1 = _box(polygon)
    near = [o for o in obstacles if o[0] < x1 and x0 < o[2] and o[1] < y1 and y0 < o[3]]
    best, best_distance = None, math.inf
    y = y0 + 10
    while y <= y1 - 12:
        x = x0 + half + 1
        while x <= x1 - half - 1:
            block = (x - half, y - 9, x + half, y + 11)
            distance = math.dist((x, y), centre)
            if distance < best_distance and all(_contains(polygon, c) for c in ((block[0], block[1]), (block[2], block[3]))) \
                    and not _overlaps(block, near):
                best, best_distance = (x, y), distance
            x += step
        y += step
    return best


def _segment_distance(point: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length))
    return math.dist(point, (a[0] + t * dx, a[1] + t * dy))


def _fitted(text: str, room: float, size: float, font: str = "regular") -> float | None:
    """The text size, at most `size`, at which `text` fits in `room` points; None when that is below MIN_TEXT_POINTS."""
    width = text_width(text, size, font)
    fit = size if width <= room else size * room / width
    return fit if fit >= MIN_TEXT_POINTS else None


def _wrap(text: str, width: float, size: float, font: str = "regular") -> list[str]:
    lines, line = [], ""
    for word in str(text).split():
        trial = f"{line} {word}".strip()
        if line and text_width(trial, size, font) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


_NICE = sorted(step * 10.0 ** power for step in (1, 2, 2.5, 5) for power in range(-1, 6))


def _nice(value: float) -> float:
    """The smallest round number (1, 2, 2.5 or 5 times a power of ten) at least `value`."""
    return next((candidate for candidate in _NICE if candidate >= value), value)


def _nice_floor(value: float) -> float:
    """The largest round number at most `value`."""
    return max((candidate for candidate in _NICE if candidate <= value), default=value)


# --- the drawing layers ---------------------------------------------------------------------------------------
def _ground_kind(surface: Mapping[str, Any]) -> str:
    try:
        r, g, b = color(surface.get("color") or "#888888")
    except ValueError:
        return "asphalt"
    return "concrete" if 0.2126 * r + 0.7152 * g + 0.0722 * b >= 0.5 else "asphalt"


def _draw_roads(sheet: Sheet, view: View, data: PlanData) -> list[tuple[list[Point], str]]:
    styles = sheet.styles
    road, rail = styles["road"], styles["railroad"]
    labels = []
    for item in data.site["roads"]:
        points = view.ps(item["points"])
        if item["kind"] == "railroad":
            sheet.page.path(points, stroke=rail["stroke"], width=rail["width"])
            spacing, half = rail["tieSpacingMeters"] * view.k, rail["tieLengthMeters"] * view.k / 2
            for a, b in zip(points, points[1:]):
                length = math.dist(a, b)
                if length <= 0:
                    continue
                ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                steps = int(length // spacing)
                for i in range(steps + 1):
                    cx, cy = a[0] + ux * i * spacing, a[1] + uy * i * spacing
                    sheet.page.line((cx - uy * half, cy + ux * half), (cx + uy * half, cy - ux * half),
                                    stroke=rail["stroke"], width=rail["width"] * 0.7)
            sheet.use("railroad", "rail")
            continue
        width = road["widthMeters"].get(item["kind"], road["widthMeters"]["other"]) * view.k
        sheet.page.path(points, stroke=road["edge"], width=width + road["edgeWidth"] * 2, cap=1, join=1)
        sheet.page.path(points, stroke=road["fill"], width=width, cap=1, join=1)
        sheet.use("road", "road")
        if item["label"]:
            labels.append((points, item["label"]))
    for item in data.site["roads"]:
        if item["kind"] != "railroad":
            sheet.page.path(view.ps(item["points"]), stroke=road["centre"], width=road["centreWidth"],
                            dash=road["centreDash"])
    return labels


def _existing_paving(data: PlanData) -> list[list[Point]]:
    """The traced pavement inside the property line, as smooth outlines: the lot in the photo. The 3D ground keeps
    it as square tiles (the yard), which on paper read as stepped blocks."""
    from shapely.geometry import Polygon
    if not data.site:
        return []
    lot = Polygon(data.site["boundary"]).buffer(0)
    rings = []
    for area in data.site["areas"]:
        if area["kind"] != "existing_pavement":
            continue
        shape = Polygon(area["points"]).buffer(0).intersection(lot)
        for part in getattr(shape, "geoms", [shape]):
            if part.geom_type == "Polygon" and part.area >= 1.0:
                rings.append([(float(x), float(z)) for x, z in part.exterior.coords[:-1]])
    return rings


def _draw_ground(sheet: Sheet, view: View, data: PlanData) -> None:
    existing = _existing_paving(data)
    for ring in existing:
        sheet.outline(view.ps(ring), "existingPaving")
        sheet.use("existingPaving", "dashed")
    for kind in ("asphalt", "concrete"):
        for surface in data.ground:
            if _ground_kind(surface) != kind:
                continue
            if existing and str(surface.get("surfaceId", "")).startswith("gr-yard-"):
                continue  # the traced lot kept as yard: drawn above as existing paving
            rect = [(surface["minX"], surface["minZ"]), (surface["maxX"], surface["minZ"]),
                    (surface["maxX"], surface["maxZ"]), (surface["minX"], surface["maxZ"])]
            sheet.page.polygon(view.ps(rect), fill=sheet.styles[kind]["fill"])
            sheet.use(kind, "fill")
    for surface in data.ground:  # concrete edges over the asphalt, so joints read
        if _ground_kind(surface) == "concrete":
            rect = [(surface["minX"], surface["minZ"]), (surface["maxX"], surface["minZ"]),
                    (surface["maxX"], surface["maxZ"]), (surface["minX"], surface["maxZ"])]
            style = sheet.styles["concrete"]
            sheet.page.polygon(view.ps(rect), stroke=style["stroke"], width=style["width"])


def _draw_marking(sheet: Sheet, view: View, mark: Mapping[str, Any]) -> None:
    position = (mark.get("transform") or {}).get("position") or {}
    degrees = float((mark.get("transform") or {}).get("rotationDegrees") or 0)
    cx, cz = float(position.get("x") or 0), float(position.get("z") or 0)
    width, depth = float(mark.get("width") or 0), float(mark.get("depth") or 0)
    if width <= 0 or depth <= 0:
        return
    kind, role = mark.get("markingType"), mark.get("semanticRole")
    box = view.ps(_rotated_box(cx, cz, width, depth, degrees))
    page = sheet.page
    if kind == "parking_box":
        style = "staging" if role == "staging" else "stall"
        sheet.outline(box, style)
        sheet.use(style, "outline" if style == "stall" else "dashed")
        text = str(mark.get("text") or "").strip()
        points = _fitted(text, max(width, depth) * view.k - 2, sheet.sizes["smallLabel"]) if text else None
        if points and min(width, depth) * view.k >= points * 1.2:  # inside its box, or not at all
            angle = degrees if width >= depth else degrees - 90
            angle = -angle  # the sheet turns counter-clockwise, the layout's rotation clockwise
            angle = ((angle + 90) % 180) - 90
            sheet.label(view.p((cx, cz)), text, size="smallLabel", angle=angle, points=points)
    elif kind in ("solid_line", "dashed_line"):
        a, b = _rotated_box(cx, cz, 0, depth, degrees)[1:3] if depth >= width else _rotated_box(cx, cz, width, 0, degrees)[0:2]
        if role == "pedestrian_lane" and max(width, depth) > 0 and min(width, depth) >= 0.5:
            sheet.fill(box, "walkway")
            sheet.use("walkway", "fill")
            return
        style = sheet.styles["laneLine"]
        page.line(view.p(a), view.p(b), stroke=style["stroke"], width=max(style["width"], min(width, depth) * view.k),
                  dash=[4, 3] if kind == "dashed_line" else None)
        sheet.use("laneLine", "line")
    elif kind == "crosswalk":
        style = sheet.styles["crosswalk"]
        page.polygon(box, fill=style["fill"], stroke=style["stroke"], width=style["width"])
        stripes = max(2, int(max(width, depth) / 0.6))
        long_x = width >= depth
        for i in range(1, stripes, 2):
            t0, t1 = -0.5 + i / stripes, -0.5 + (i + 1) / stripes
            if long_x:
                part = _rotated_box(cx + (t0 + t1) / 2 * width * math.cos(math.radians(degrees)),
                                    cz - (t0 + t1) / 2 * width * math.sin(math.radians(degrees)), width / stripes, depth, degrees)
            else:
                part = _rotated_box(cx + (t0 + t1) / 2 * depth * math.sin(math.radians(degrees)),
                                    cz + (t0 + t1) / 2 * depth * math.cos(math.radians(degrees)), width, depth / stripes, degrees)
            page.polygon(view.ps(part), fill=style["stroke"])
    elif kind == "direction_arrow":
        t = math.radians(degrees)
        c, s = math.cos(t), math.sin(t)

        def at(a: float, b: float) -> Point:
            return view.p((cx + a * c + b * s, cz - a * s + b * c))
        w, d = width / 2, depth / 2
        page.polygon([at(-w * 0.35, -d), at(w * 0.35, -d), at(w * 0.35, d * 0.15), at(w, d * 0.15), at(0, d),
                      at(-w, d * 0.15), at(-w * 0.35, d * 0.15)], fill=sheet.styles["arrow"]["fill"])
    elif kind == "floor_text":
        text = str(mark.get("text") or "").strip()
        points = _fitted(text, max(width, depth) * view.k, sheet.sizes["smallLabel"], "bold") if text else None
        if points:  # painted words stay the length they are painted: too small to read, they are left out
            angle = -degrees if width >= depth else -(degrees - 90)
            angle = ((angle + 90) % 180) - 90
            sheet.label(view.p((cx, cz)), text, size="smallLabel", font="bold", angle=angle, points=points)


def _draw_items(sheet: Sheet, view: View, data: PlanData, kinds: Sequence[str], inside: bool | None) -> None:
    for item in data.items:
        if item["kind"] not in kinds or (inside is not None and _inside(item["at"], data.building) != inside):
            continue
        if not item["polygons"]:
            x, y = view.p(item["at"])
            sheet.page.line((x - 2, y - 2), (x + 2, y + 2), stroke="#DC2626", width=0.5)
            sheet.page.line((x - 2, y + 2), (x + 2, y - 2), stroke="#DC2626", width=0.5)
            continue
        for polygon in item["polygons"]:
            sheet.outline(view.ps(polygon), item["kind"])
        sheet.use(item["kind"], "outline")
        if item["kind"] == "forklift":
            sheet.label(view.p(item["at"]), "FL", size="smallLabel", font="bold", fill=sheet.styles["forklift"]["stroke"])


def _draw_walls(sheet: Sheet, view: View, data: PlanData, *, detail: bool) -> None:
    if data.wall_panels:
        for triangle in data.wall_panels:
            pts = view.ps(triangle)
            sheet.page.polygon(pts, fill=sheet.styles["wall"]["fill"], stroke=sheet.styles["wall"]["fill"], width=0.15)
        sheet.use("wall", "fill")
    elif data.building:
        rect = [(0, 0), (data.width, 0), (data.width, data.depth), (0, data.depth)]
        sheet.page.polygon(view.ps(rect), stroke=sheet.styles["wall"]["fill"], width=1.2)
        sheet.use("wall", "fill")
    thickness = float(data.wall_settings.get("thicknessMeters") or 0.3)
    for opening in data.openings:
        (ax, az), (bx, bz) = opening["start"], opening["end"]
        (ux, uz), (nx, nz) = opening["along"], opening["outward"]
        if opening["kind"] == "dock":
            style = sheet.styles["dockDoor"]
            sheet.use("dockDoor", "dock")
            if detail:  # the dock leveller pit just inside the door
                depth = style["levellerMeters"]
                pit = [(ax - nx * thickness / 2, az - nz * thickness / 2), (bx - nx * thickness / 2, bz - nz * thickness / 2),
                       (bx - nx * depth, bz - nz * depth), (ax - nx * depth, az - nz * depth)]
                sheet.page.polygon(view.ps(pit), stroke=style["stroke"], width=style["width"] * 0.7, dash=style["leveller"])
                tag = view.p(((ax + bx) / 2 + nx * 1.6, (az + bz) / 2 + nz * 1.6))
                sheet.label((tag[0], tag[1] - sheet.sizes["smallLabel"] / 3), f"D{opening['number']}",
                            size="smallLabel", font="bold")
            sheet.page.line(view.p((ax + nx * thickness / 2, az + nz * thickness / 2)),
                            view.p((bx + nx * thickness / 2, bz + nz * thickness / 2)),
                            stroke=style["stroke"], width=style["width"])
        else:
            style = sheet.styles["door"]
            sheet.use("door", "door")
            width = opening["width"]
            hinge = (ax - nx * thickness / 2, az - nz * thickness / 2)
            leaf = (hinge[0] - nx * width, hinge[1] - nz * width)
            sheet.page.line(view.p(hinge), view.p(leaf), stroke=style["stroke"], width=style["width"])
            start = math.atan2(-nz, -nx)
            end = math.atan2(uz, ux)
            if end - start > math.pi:
                end -= 2 * math.pi
            if start - end > math.pi:
                end += 2 * math.pi
            arc = [view.p((hinge[0] + width * math.cos(start + (end - start) * i / 16),
                           hinge[1] + width * math.sin(start + (end - start) * i / 16))) for i in range(17)]
            sheet.page.path(arc, stroke=style["stroke"], width=style["width"] * 0.6, dash=[2, 1.5])


def _arrow_head(page: Page, tip: Point, back: Point, size: float, fill) -> None:
    dx, dy = tip[0] - back[0], tip[1] - back[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    page.polygon([tip, (tip[0] - ux * size - uy * size * 0.45, tip[1] - uy * size + ux * size * 0.45),
                  (tip[0] - ux * size + uy * size * 0.45, tip[1] - uy * size - ux * size * 0.45)], fill=fill)


def _clip_polyline(points: Sequence[Point], box: tuple[float, float, float, float]) -> list[Point]:
    """The leading run of a polyline inside a box (it starts inside), cut where it leaves."""
    result = [points[0]]
    for a, b in zip(points, points[1:]):
        if _inside(b, box):
            result.append(b)
            continue
        t_exit = 1.0
        for axis, low, high in ((0, box[0], box[2]), (1, box[1], box[3])):
            d = b[axis] - a[axis]
            if d > 0 and b[axis] > high:
                t_exit = min(t_exit, (high - a[axis]) / d)
            elif d < 0 and b[axis] < low:
                t_exit = min(t_exit, (low - a[axis]) / d)
        result.append((a[0] + (b[0] - a[0]) * t_exit, a[1] + (b[1] - a[1]) * t_exit))
        break
    return result


def _draw_routes(sheet: Sheet, view: View, data: PlanData, box: tuple[float, float, float, float]) -> list[list[Point]]:
    """The routes out to the main road, to where they leave the sheet; one label per main road at the arrows."""
    drawn, ends = [], {}
    inner = (box[0] + 10, box[1] + 10, box[2] - 10, box[3] - 10)
    for index, route in enumerate(data.site["routes"]):
        style_key = "routeTrucks" if route["use"] == "trucks" else "routeCars"
        style = sheet.styles[style_key]
        points = view.ps(route["points"])
        if not _inside(points[0], inner):
            continue
        offset = (index % 2) * 2.2  # two routes on one street sit side by side
        shown = [(x, y + offset) for x, y in _clip_polyline(points, inner)]
        sheet.page.path(shown, stroke=style["stroke"], width=style["width"], cap=1, join=1)
        if len(shown) >= 2:
            _arrow_head(sheet.page, shown[-1], shown[-2], 6, style["stroke"])
            ends.setdefault(_short_road(route["mainRoad"]), []).append(shown[-1])
        drawn.append(shown)
        sheet.use(style_key, "route")
    for road, points in ends.items():
        x = sum(p[0] for p in points) / len(points)
        y = max(p[1] for p in points)
        align = "left" if x < (box[0] + box[2]) / 2 else "right"
        sheet.label((x + (4 if align == "left" else -4), y + 9), f"TO {road.upper()}", size="smallLabel", font="bold",
                    align=align, halo=True)
    return drawn


def _road_labels(sheet: Sheet, roads: Sequence[tuple[list[Point], str]], box, routes: Sequence[list[Point]]) -> None:
    """Each road's name along it, at the first spot inside the sheet that no route line or other name covers."""
    placed: list[Point] = []
    inner = (box[0] + 30, box[1] + 12, box[2] - 30, box[3] - 12)
    for points, text in roads:
        segments = sorted(zip(points, points[1:]), key=lambda pair: -math.dist(*pair))
        for a, b in segments:
            spot = None
            for t in (0.5, 0.3, 0.7, 0.15, 0.85):
                at = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                clear = all(_segment_distance(at, p, q) > 12 for line in routes for p, q in zip(line, line[1:]))
                if _inside(at, inner) and clear and all(math.dist(at, other) > 70 for other in placed):
                    spot = at
                    break
            if spot is None:
                continue
            angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            angle = ((angle + 90) % 180) - 90
            sheet.label((spot[0], spot[1] - 2), text, size="smallLabel", font="italic", fill=sheet.palette["muted"],
                        angle=angle)
            placed.append(spot)
            break


def _ground_mark(sheet: Sheet, view: View, mark: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """The pavement logo as a target symbol; returns its box on the sheet, for labels to keep clear of."""
    style = sheet.styles["groundMark"]
    centre = view.p((float(mark["x"]), float(mark["z"])))
    r = float(mark.get("widthMeters") or 4) / 2 * view.k
    _target(sheet.page, centre, r, style)
    sheet.use("groundMark", "target")
    return centre[0] - r * 1.1, centre[1] - r * 1.1, centre[0] + r * 1.1, centre[1] + r * 1.1


def _target(page: Page, centre: Point, r: float, style: Mapping[str, Any]) -> None:
    for scale in (1.0, 0.62):
        page.circle(centre[0], centre[1], r * scale, stroke=style["stroke"], width=style["width"])
    page.line((centre[0] - r * 1.1, centre[1]), (centre[0] + r * 1.1, centre[1]), stroke=style["stroke"], width=style["width"])
    page.line((centre[0], centre[1] - r * 1.1), (centre[0], centre[1] + r * 1.1), stroke=style["stroke"], width=style["width"])


# --- the sheets -------------------------------------------------------------------------------------------------
def _site_bounds(data: PlanData) -> tuple[float, float, float, float]:
    points = list(data.site["boundary"])
    for surface in data.ground:
        points += [(surface["minX"], surface["minZ"]), (surface["maxX"], surface["maxZ"])]
    if data.building:
        points += [(0, 0), (data.width, data.depth)]
    x0, z0, x1, z1 = _box(points)
    pad = max(x1 - x0, z1 - z0) * 0.04
    return x0 - pad, z0 - pad, x1 + pad, z1 + pad


def _floor_bounds(data: PlanData) -> tuple[float, float, float, float]:
    if data.building:  # room for the dimensions all round, and for door tags and door dimensions on dock sides
        docks = _dock_edges(data)
        extra = {edge: 7.0 if edge in docks else 0.0 for edge in range(4)}
        return -6.0 - extra[3], -6.0 - extra[0], data.width + 6.0 + extra[1], data.depth + 6.0 + extra[2]
    points = [p for z in data.zones for p in map(_xz, z["boundary"])] + [item["at"] for item in data.items]
    if not points:
        return -10.0, -10.0, 10.0, 10.0
    x0, z0, x1, z1 = _box(points)
    return x0 - 5, z0 - 5, x1 + 5, z1 + 5


def _building_dimensions(sheet: Sheet, view: View, data: PlanData, dock_edges: set[int]) -> None:
    if not data.building:
        return
    w, d = data.width, data.depth
    # Put each dimension on a side without dock doors where possible.
    south_free = 0 not in dock_edges
    west_free = 3 not in dock_edges
    if south_free:
        sheet.dimension(view.p((0, 0)), view.p((w, 0)), (0, -1), length_label(w))
    else:
        sheet.dimension(view.p((0, d)), view.p((w, d)), (0, 1), length_label(w))
    if west_free:
        sheet.dimension(view.p((0, 0)), view.p((0, d)), (-1, 0), length_label(d))
    else:
        sheet.dimension(view.p((w, 0)), view.p((w, d)), (1, 0), length_label(d))


def _dock_edges(data: PlanData) -> set[int]:
    edges = set()
    for opening in data.openings:
        if opening["kind"] == "dock" and data.building:
            (ax, az), (nx, nz) = opening["start"], opening["outward"]
            edges.add(0 if nz < -0.5 else 2 if nz > 0.5 else 3 if nx < -0.5 else 1)
    return edges


def draw_site_sheet(sheet: Sheet, frames: Frames, data: PlanData) -> dict[str, Any]:
    bounds = _site_bounds(data)
    feet = pick_scale(bounds, frames.drawing, sheet.template["scalesFeetPerInch"])
    view = View(frames.drawing, bounds, feet)
    page, box = sheet.page, frames.drawing
    page.save()
    page.clip_rect(box[0], box[1], box[2] - box[0], box[3] - box[1])
    road_labels = _draw_roads(sheet, view, data)
    _draw_ground(sheet, view, data)
    for mark in data.markings:
        position = (mark.get("transform") or {}).get("position") or {}
        if not _inside((float(position.get("x") or 0), float(position.get("z") or 0)), data.building):
            _draw_marking(sheet, view, mark)
    logos = [_ground_mark(sheet, view, mark) for mark in data.ground_marks]
    _draw_items(sheet, view, data, ("truck", "car", "equipment"), inside=False)
    if data.building:
        rect = [(0, 0), (data.width, 0), (data.width, data.depth), (0, data.depth)]
        page.polygon(view.ps(rect), fill=sheet.styles["building"]["fill"])
    _draw_walls(sheet, view, data, detail=False)
    sheet.outline(view.ps(data.site["boundary"]), "property")
    sheet.use("property", "property")
    routes = _draw_routes(sheet, view, data, box)
    _road_labels(sheet, road_labels, box, routes)
    # Labels: the building, then the outdoor areas that have room.
    if data.building:
        centre = view.p((data.width / 2, data.depth / 2))
        sheet.label((centre[0], centre[1] + 8), "WAREHOUSE", size="drawingTitle", font="bold")
        sheet.label((centre[0], centre[1] - 3), f"{feet_inches(data.width)} x {feet_inches(data.depth)}", size="label")
        sheet.label((centre[0], centre[1] - 12), area_label(data.width * data.depth), size="label")
    for area in data.site["areas"]:
        if area["kind"] in ("existing_pavement",) or not area["label"]:
            continue
        x0, z0, x1, z1 = _box(area["points"])
        if (x1 - x0) * view.k < 60 and (z1 - z0) * view.k < 60:
            continue
        centre = view.p(_centroid(area["points"]))
        text = area["label"].upper()
        half = text_width(text, sheet.sizes["smallLabel"], "bold") / 2 + 2
        for logo in logos:  # the truck court's logo sits where its label would: the label goes under the logo
            if _overlaps((centre[0] - half, centre[1] - 3, centre[0] + half, centre[1] + 6), [logo]):
                centre = ((logo[0] + logo[2]) / 2, logo[1] - 8)
        if _inside(centre, frames.drawing):
            sheet.label(centre, text, size="smallLabel", font="bold", fill=sheet.palette["muted"], halo=True)
    for entrance in data.site["entrances"]:
        at = view.p(entrance["at"])
        if _inside(at, frames.drawing):
            use = {"trucks": "TRUCK", "cars": "CAR"}.get(entrance["use"], str(entrance["use"] or "").upper())
            text = f"{use} ENTRANCE {feet_inches(entrance['width'])}".strip()
            sheet.label((at[0], at[1] - 12), text, size="smallLabel", font="bold", halo=True)
    _building_dimensions(sheet, view, data, _dock_edges(data))
    page.restore()
    return {"view": view, "feet": feet}


def draw_floor_sheet(sheet: Sheet, frames: Frames, data: PlanData) -> dict[str, Any]:
    bounds = _floor_bounds(data)
    feet = pick_scale(bounds, frames.drawing, sheet.template["scalesFeetPerInch"])
    view = View(frames.drawing, bounds, feet)
    page, box = sheet.page, frames.drawing
    page.save()
    page.clip_rect(box[0], box[1], box[2] - box[0], box[3] - box[1])
    if data.building:
        rect = [(0, 0), (data.width, 0), (data.width, data.depth), (0, data.depth)]
        page.polygon(view.ps(rect), fill=sheet.styles["slab"]["fill"])
    zone_style = sheet.styles["zone"]
    inside_zones = []
    for zone in data.zones:
        points = [_xz(p) for p in zone["boundary"]]
        if data.building and not _inside(_centroid(points), data.building):
            continue
        tint = zone_style["colors"].get(zone.get("zoneType"), zone_style["colors"]["other"])
        sheet.fill(view.ps(points), "zone", alpha=zone_style["fillAlpha"], fill=tint)
        page.polygon(view.ps(points), stroke=tint, width=zone_style["width"], dash=zone_style["dash"])
        inside_zones.append((zone, points, tint))
        sheet.use("zone", "zone")
    for mark in data.markings:
        position = (mark.get("transform") or {}).get("position") or {}
        if data.building is None or _inside((float(position.get("x") or 0), float(position.get("z") or 0)), data.building):
            _draw_marking(sheet, view, mark)
    aisle_style = sheet.styles["aisle"]
    labelled_widths = set()
    for aisle in data.aisles:
        points = [_xz(p) for p in aisle["centerline"]]
        mid = ((points[0][0] + points[-1][0]) / 2, (points[0][1] + points[-1][1]) / 2)
        if data.building and not _inside(mid, data.building):
            continue
        page.path(view.ps(points), stroke=aisle_style["stroke"], width=aisle_style["width"], dash=aisle_style["dash"])
        sheet.use("aisle", "dashed")
        width = round(float(aisle.get("corridorWidth") or 0), 2)
        if width and width not in labelled_widths:
            a, b = view.p(points[0]), view.p(points[1])
            angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            angle = ((angle + 90) % 180) - 90
            # The label sits at a third of the first segment, clear of the cross aisles at its ends.
            at = (a[0] + (b[0] - a[0]) * 0.36, a[1] + (b[1] - a[1]) * 0.36)
            sheet.label(at, f"AISLE {length_label(width)}", size="smallLabel", angle=angle, halo=True)
            labelled_widths.add(width)
    _draw_items(sheet, view, data, ("rack", "forklift", "equipment"), inside=None if data.building is None else True)
    _draw_walls(sheet, view, data, detail=True)
    # Zone names go to the first clear spot inside the zone: its middle, then along its top and bottom edges.
    obstacles = []
    for mark in data.markings:
        position = (mark.get("transform") or {}).get("position") or {}
        if float(mark.get("width") or 0) > 0 and float(mark.get("depth") or 0) > 0:
            corners = view.ps(_rotated_box(float(position.get("x") or 0), float(position.get("z") or 0),
                                           float(mark["width"]), float(mark["depth"]),
                                           float((mark.get("transform") or {}).get("rotationDegrees") or 0)))
            obstacles.append(_box(corners))
    obstacles += [_box(view.ps(polygon)) for item in data.items for polygon in item["polygons"]]
    for zone, points, tint in inside_zones:
        x0, z0, x1, z1 = _box(points)
        if (x1 - x0) * view.k < 50 or (z1 - z0) * view.k < 24:
            continue
        name = str(zone.get("label") or zone.get("zoneType") or "").upper()
        area = area_label(abs(_area(points)))
        half = max(text_width(name, sheet.sizes["label"], "bold"), text_width(area, sheet.sizes["smallLabel"])) / 2 + 2
        centre = view.p(_centroid(points))
        px, py = _free_spot(view.ps(points), centre, half, obstacles) or centre
        sheet.label((px, py + 3), name, size="label", font="bold", fill=tint, halo=True)
        sheet.label((px, py - 6), area, size="smallLabel", fill=tint, halo=True)
        obstacles.append((px - half, py - 9, px + half, py + 11))
    docks = [o for o in data.openings if o["kind"] == "dock"]
    if len(docks) >= 2:  # door width and spacing, on the first two doors
        first, second = docks[0], docks[1]
        side = first["outward"]
        out = 5.5
        a = view.p((first["start"][0] + side[0] * out, first["start"][1] + side[1] * out))
        b = view.p((first["end"][0] + side[0] * out, first["end"][1] + side[1] * out))
        sheet.dimension(a, b, side, feet_inches(first["width"]))
        c1 = ((first["start"][0] + first["end"][0]) / 2, (first["start"][1] + first["end"][1]) / 2)
        c2 = ((second["start"][0] + second["end"][0]) / 2, (second["start"][1] + second["end"][1]) / 2)
        out2 = out + 3.6
        sheet.dimension(view.p((c1[0] + side[0] * out2, c1[1] + side[1] * out2)),
                        view.p((c2[0] + side[0] * out2, c2[1] + side[1] * out2)), side,
                        f"{feet_inches(math.dist(c1, c2))} O.C.")
    for opening in data.openings:
        if opening["kind"] == "door":
            (ax, az), (bx, bz), (nx, nz) = opening["start"], opening["end"], opening["outward"]
            at = view.p(((ax + bx) / 2 + nx * 2.4, (az + bz) / 2 + nz * 2.4))
            sheet.label((at[0], at[1] - 2), "PERSONNEL DOOR", size="smallLabel", font="bold", halo=True)
    _building_dimensions(sheet, view, data, _dock_edges(data))
    page.restore()
    return {"view": view, "feet": feet}


def _fit(text: str, width: float, size: float, font: str = "regular") -> str:
    """The text, shortened with an ellipsis to fit `width` points."""
    text = str(text)
    if text_width(text, size, font) <= width:
        return text
    while text and text_width(text + "...", size, font) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def _table(sheet: Sheet, x: float, top: float, title: str, columns, rows) -> float:
    """A small table: columns are (header, width, align); returns the height used below `top`."""
    page, sizes, style = sheet.page, sheet.sizes, sheet.styles["table"]
    height = style["rowHeight"]
    sheet.label((x, top - sizes["heading"]), title.upper(), size="heading", font="bold", fill=sheet.palette["muted"],
                align="left")
    y = top - sizes["heading"] - 4
    width = sum(column[1] for column in columns)
    page.rect(x, y - height, width, height, fill=style["header"])
    for index, row in enumerate([[column[0] for column in columns]] + [list(map(str, row)) for row in rows]):
        cx = x
        for (header, w, align), cell in zip(columns, row):
            tx = cx + 2 if align == "left" else cx + w - 2
            sheet.label((tx, y - height + 2.8), _fit(cell, w - 4, sizes["smallLabel"], "bold" if index == 0 else "regular"),
                        size="smallLabel", font="bold" if index == 0 else "regular", align=align)
            cx += w
        y -= height
        page.line((x, y), (x + width, y), stroke=style["rule"], width=0.3)
    return top - y + 10


def setting_out(data: PlanData) -> dict[str, Any]:
    """Building corners, lines, reference points and ties, in the property frame (true north)."""
    from .geo import from_property
    site = data.site
    geo = site["georeference"]

    def latlon(point: Point) -> tuple[float, float]:
        latitude, longitude, _ = from_property(point[0], point[1], float(geo["originLatitude"]), float(geo["originLongitude"]))
        return latitude, longitude
    corners = list(zip("ABCD", site["corners"]))
    centre = (sum(p[0] for _, p in corners) / 4, sum(p[1] for _, p in corners) / 4) if corners else None
    lines = [(f"{a}-{b}", _true_bearing(p, q), math.dist(p, q))
             for (a, p), (b, q) in zip(corners, corners[1:] + corners[:1])]
    ties = []
    references = site["references"]
    for name, corner in corners:
        for reference in sorted(references, key=lambda r: math.dist((r["x"], r["z"]), corner))[:2]:
            start = (reference["x"], reference["z"])
            ties.append({"from": reference, "to": name, "corner": corner,
                         "meters": math.dist(start, corner), "bearing": _true_bearing(start, corner)})
    return {"corners": [(name, point, latlon(point)) for name, point in corners]
            + ([("Centre", centre, latlon(centre))] if centre else []),
            "lines": lines, "ties": ties, "references": references}


def _reference_code(reference: Mapping[str, Any]) -> str:
    match = re.fullmatch(r"rp-(\d+)", reference["referenceId"])
    return f"RP{match.group(1)}" if match else reference["referenceId"].upper()


def draw_setting_out_sheet(sheet: Sheet, frames: Frames, data: PlanData, fit: Mapping[str, Any] | None) -> dict[str, Any]:
    box = frames.drawing
    split = box[0] + (box[2] - box[0]) * 0.58
    map_box = (box[0], box[1], split - 12, box[3])
    points = list(data.site["boundary"]) + ([(0.0, 0.0), (data.width, data.depth)] if data.building else []) \
        + [r["at"] for r in data.site["references"]]
    x0, z0, x1, z1 = _box(points)
    pad = max(x1 - x0, z1 - z0) * 0.06
    bounds = (x0 - pad, z0 - pad, x1 + pad, z1 + pad)
    feet = pick_scale(bounds, map_box, sheet.template["scalesFeetPerInch"])
    view = View(map_box, bounds, feet)
    page, styles = sheet.page, sheet.styles
    plan = setting_out(data)
    page.save()
    page.clip_rect(map_box[0], map_box[1], map_box[2] - map_box[0], map_box[3] - map_box[1])
    page.save()
    page.alpha(fill=0.45)
    _draw_ground(sheet, view, data)  # paving faint, for orientation
    page.restore()
    if data.building:
        page.polygon(view.ps([(0, 0), (data.width, 0), (data.width, data.depth), (0, data.depth)]),
                     fill=styles["building"]["fill"])
    _draw_walls(sheet, view, data, detail=False)
    sheet.outline(view.ps(data.site["boundary"]), "property")
    sheet.use("property", "property")
    layout_corners = [(0.0, 0.0), (data.width, 0.0), (data.width, data.depth), (0.0, data.depth)] if data.building else []
    by_name = dict(zip("ABCD", layout_corners))
    for tie in plan["ties"]:  # ties first, under the markers
        a, b = view.p(tie["from"]["at"]), view.p(by_name[tie["to"]])
        page.line(a, b, stroke=styles["tie"]["stroke"], width=styles["tie"]["width"], dash=styles["tie"]["dash"])
        angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        angle = ((angle + 90) % 180) - 90
        sheet.label(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 1.5), feet_inches(tie["meters"]), size="smallLabel",
                    angle=angle, halo=True, fill=styles["tie"]["stroke"])
    if plan["ties"]:
        sheet.use("tie", "tie")
    for reference in data.site["references"]:
        at = view.p(reference["at"])
        _triangle(page, at, styles["reference"])
        sheet.label((at[0] + 7, at[1] + 4), _reference_code(reference), size="label", font="bold", align="left", halo=True)
    if data.site["references"]:
        sheet.use("reference", "reference")
    centre = view.p((data.width / 2, data.depth / 2)) if data.building else None
    for name, point in by_name.items():
        at = view.p(point)
        page.circle(at[0], at[1], styles["corner"]["size"], fill=styles["corner"]["fill"], stroke=styles["corner"]["stroke"],
                    width=styles["corner"]["width"])
        dx, dy = at[0] - centre[0], at[1] - centre[1]
        length = math.hypot(dx, dy) or 1.0
        sheet.label((at[0] + dx / length * 10, at[1] + dy / length * 10 - 3), name, size="label", font="bold", halo=True)
    if by_name:
        sheet.use("corner", "corner")
        sheet.use("wall", "fill")
    page.restore()
    # Tables, beside the drawing.
    x = split
    width = box[2] - x
    top = box[3]
    top -= _table(sheet, x, top, "Building corners (site metres and WGS84)",
                  [("Point", width * 0.13, "left"), ("East (m)", width * 0.17, "right"), ("North (m)", width * 0.17, "right"),
                   ("Latitude", width * 0.265, "right"), ("Longitude", width * 0.265, "right")],
                  [(name, f"{p[0]:,.2f}", f"{p[1]:,.2f}", f"{ll[0]:.7f}\xb0", f"{ll[1]:.7f}\xb0")
                   for name, p, ll in plan["corners"]])
    top -= _table(sheet, x, top, "Building lines",
                  [("Line", width * 0.16, "left"), ("Bearing", width * 0.42, "left"), ("Length", width * 0.42, "right")],
                  [(name, quadrant_bearing(bearing), length_label(length)) for name, bearing, length in plan["lines"]])
    if plan["references"]:
        top -= _table(sheet, x, top, "Reference points",
                      [("Point", width * 0.12, "left"), ("Description", width * 0.43, "left"), ("Source", width * 0.2, "left"),
                       ("East (m)", width * 0.125, "right"), ("North (m)", width * 0.125, "right")],
                      [(_reference_code(r), r["label"], f"{r['source'].replace('_', ' ')}, \xb1{r['accuracyMeters']:g} m",
                        f"{r['x']:,.2f}", f"{r['z']:,.2f}") for r in plan["references"][:8]])
        top -= _table(sheet, x, top, "Ties from reference points",
                      [("From", width * 0.14, "left"), ("To", width * 0.12, "left"), ("Distance", width * 0.38, "right"),
                       ("Bearing", width * 0.36, "right")],
                      [(_reference_code(t["from"]), t["to"], length_label(t["meters"]), quadrant_bearing(t["bearing"]))
                       for t in plan["ties"]])
    else:
        sheet.label((x, top - 8), "No reference points yet: ask Sage to add them.", size="body", align="left",
                    fill=sheet.palette["muted"])
        top -= 22
    sheet.label((x, top - sheet.sizes["heading"]), "FIT CHECK", size="heading", font="bold", fill=sheet.palette["muted"],
                align="left")
    top -= sheet.sizes["heading"] + 6
    lines = list((fit or {}).get("summary") or [])
    survey = (fit or {}).get("survey") or {}
    if survey.get("pending"):
        lines.append(survey["pending"])
    if not lines:
        lines = ["Not checked yet."]
    for line in lines:
        for part in _wrap(line, width, sheet.sizes["note"]):
            sheet.label((x, top - sheet.sizes["note"]), part, size="note", align="left")
            top -= sheet.sizes["note"] + 2.5
        top -= 2
    return {"view": view, "feet": feet}


def _setting_out_numbers(data: PlanData) -> list[tuple[str, str]]:
    geo = data.site["georeference"]
    lat, lon = float(geo["originLatitude"]), float(geo["originLongitude"])
    rows = [("Site origin", f"{abs(lat):.6f}\xb0 {'N' if lat >= 0 else 'S'}, {abs(lon):.6f}\xb0 {'E' if lon >= 0 else 'W'}")]
    plan = setting_out(data)
    if plan["lines"]:
        rows.append(("Long side A-B", quadrant_bearing(plan["lines"][0][1])))
    centre = next((ll for name, _, ll in plan["corners"] if name == "Centre"), None)
    if centre:
        rows.append(("Building centre", f"{abs(centre[0]):.6f}\xb0 {'N' if centre[0] >= 0 else 'S'}, "
                                        f"{abs(centre[1]):.6f}\xb0 {'E' if centre[1] >= 0 else 'W'}"))
    rows.append(("Reference points", str(len(plan["references"]))))
    return rows


# --- title band, title strip -----------------------------------------------------------------------------------------
def _scale_text(feet: float) -> str:
    return f"SCALE: 1\" = {feet:g}'-0\"  (1:{feet * 12:,.0f})"


def _draw_title_band(sheet: Sheet, frames: Frames, spec: Mapping[str, Any], view: View, data: PlanData,
                     north: Point | None) -> None:
    page, band, palette = sheet.page, frames.band, sheet.palette
    x, y = band[0], band[1]
    page.circle(x + 13, y + 15, 12, stroke=palette["text"], width=0.8)
    page.line((x + 1, y + 15), (x + 25, y + 15), stroke=palette["text"], width=0.5)
    sheet.label((x + 13, y + 17.5), "1", size="smallLabel", font="bold")
    sheet.label((x + 13, y + 7.5), spec["number"], size="smallLabel")
    title_width = sheet.label((x + 32, y + 17), spec["title"], size="drawingTitle", font="bold", align="left")
    page.line((x + 32, y + 13.5), (x + 32 + max(title_width, 150), y + 13.5), stroke=palette["text"], width=0.8)
    sheet.label((x + 32, y + 4.5), _scale_text(view.feet_per_inch), size="smallLabel", align="left")
    # Scale bar: feet above, metres below, about 2.5 in of paper.
    k_ft = view.k * FOOT
    total_ft = _nice(2.5 * view.feet_per_inch)
    seg_ft = total_ft / 4
    bar_x, bar_y = (band[0] + band[2]) / 2 - total_ft * k_ft / 2, y + 15
    for i in range(4):
        page.rect(bar_x + i * seg_ft * k_ft, bar_y, seg_ft * k_ft, 3.2, stroke=palette["text"], width=0.4,
                  fill=palette["text"] if i % 2 == 0 else "#FFFFFF")
        sheet.label((bar_x + i * seg_ft * k_ft, bar_y + 5.5), f"{seg_ft * i:g}", size="smallLabel")
    sheet.label((bar_x + total_ft * k_ft, bar_y + 5.5), f"{total_ft:g} FT", size="smallLabel")
    seg_m = _nice_floor(total_ft * FOOT / 4)
    total_m = seg_m * 4
    for i in range(4):
        page.rect(bar_x + i * seg_m * view.k, bar_y - 5, seg_m * view.k, 3.2, stroke=palette["muted"], width=0.4,
                  fill=palette["muted"] if i % 2 == 0 else "#FFFFFF")
    sheet.label((bar_x + total_m * view.k + 3, bar_y - 4.8), f"{total_m:g} M", size="smallLabel", align="left",
                fill=palette["muted"])
    # North arrow, on the band's right.
    if north is not None:
        cx, cy = band[2] - 26, y + 16
        size = sheet.styles["northArrow"]["size"] / 2
        nx, ny = north
        page.circle(cx, cy, size, stroke=palette["text"], width=0.6)
        tip, tail = (cx + nx * size, cy + ny * size), (cx - nx * size * 0.75, cy - ny * size * 0.75)
        left = (cx - ny * size * 0.32, cy + nx * size * 0.32)
        right = (cx + ny * size * 0.32, cy - nx * size * 0.32)
        page.polygon([tip, left, tail, right], stroke=palette["text"], width=0.5)
        page.polygon([tip, left, tail], fill=palette["text"])
        sheet.label((cx + nx * (size + 6), cy + ny * (size + 6) - 2.5), "N", size="label", font="bold")


def _legend_swatch(sheet: Sheet, style_key: str, swatch: str, x: float, y: float) -> None:
    page, style = sheet.page, sheet.styles[style_key]
    w, h = 18, 6
    if swatch == "fill":
        page.rect(x, y, w, h, fill=style.get("fill"), stroke=style.get("stroke") or style.get("fill"), width=style.get("width", 0.3))
    elif swatch in ("outline", "dashed"):
        page.rect(x + 2, y, w - 4, h, stroke=style["stroke"], fill=style.get("fill"), width=style.get("width", 0.4),
                  dash=style.get("dash") if swatch == "dashed" else None)
    elif swatch == "zone":
        page.rect(x, y, w, h, stroke=style["colors"]["receiving"], width=style["width"], dash=style["dash"])
    elif swatch == "property":
        page.line((x, y + h / 2), (x + w, y + h / 2), stroke=style["stroke"], width=style["width"], dash=[6, 1.5, 1, 1.5])
    elif swatch == "road":
        page.line((x, y + h / 2), (x + w, y + h / 2), stroke=style["edge"], width=h + 0.8)
        page.line((x, y + h / 2), (x + w, y + h / 2), stroke=style["fill"], width=h)
        page.line((x, y + h / 2), (x + w, y + h / 2), stroke=style["centre"], width=style["centreWidth"], dash=[3, 2])
    elif swatch == "rail":
        page.line((x, y + h / 2), (x + w, y + h / 2), stroke=style["stroke"], width=style["width"])
        for i in range(5):
            page.line((x + 1 + i * 4, y + 0.8), (x + 1 + i * 4, y + h - 0.8), stroke=style["stroke"], width=0.4)
    elif swatch in ("line", "route"):
        page.line((x, y + h / 2), (x + w, y + h / 2), stroke=style["stroke"], width=min(style["width"], 2), dash=style.get("dash"))
        if swatch == "route":
            _arrow_head(page, (x + w + 3, y + h / 2), (x, y + h / 2), 4, style["stroke"])
    elif swatch == "dock":
        page.rect(x, y + h - 1.5, w, 1.5, fill=sheet.styles["wall"]["fill"])
        page.rect(x + 4, y, w - 8, h - 1.5, stroke=style["stroke"], width=0.4, dash=style["leveller"])
    elif swatch == "door":
        page.line((x + 2, y), (x + 2, y + h), stroke=style["stroke"], width=style["width"])
        page.path(page.arc_points(x + 2, y, h, math.pi / 2, 0, 8), stroke=style["stroke"], width=0.3, dash=[1.5, 1])
    elif swatch == "reference":
        _triangle(page, (x + w / 2, y + h / 2), style)
    elif swatch == "corner":
        page.circle(x + w / 2, y + h / 2, style["size"], fill=style["fill"], stroke=style["stroke"], width=style["width"])
    elif swatch == "target":
        _target(page, (x + w / 2, y + h / 2), h / 2 / 1.1, style)
    elif swatch == "tie":
        page.line((x, y + h / 2), (x + w, y + h / 2), stroke=style["stroke"], width=style["width"], dash=style["dash"])


def _triangle(page: Page, at: Point, style: Mapping[str, Any]) -> None:
    s = style["size"]
    page.polygon([(at[0], at[1] + s), (at[0] + s * 0.87, at[1] - s * 0.5), (at[0] - s * 0.87, at[1] - s * 0.5)],
                 fill=style["fill"], stroke=style["stroke"], width=style["width"])


def _draw_title_strip(sheet: Sheet, frames: Frames, spec: Mapping[str, Any], data: PlanData, numbers: list,
                      index: int, count: int, revision: str, today: str, logo: str | None) -> None:
    page, palette, sizes = sheet.page, sheet.palette, sheet.sizes
    x0, y0, x1, y1 = frames.strip
    pad = sheet.template["titleStrip"]["padding"]
    inner = x1 - x0 - 2 * pad
    page.line((x0, y0), (x0, y1), stroke=sheet.styles["frame"]["stroke"], width=sheet.styles["frame"]["width"])
    # Brand band.
    brand = sheet.template["brand"]
    top = y1
    page.rect(x0, top - 62, x1 - x0, 62, fill=palette["brand"])
    text_x = x0 + pad
    if logo:
        page.image(logo, x0 + pad, top - 54, 40, 40)
        text_x += 48
    first, second = brand["wordmark"]
    width = sheet.label((text_x, top - 34), first, size="wordmark", font="bold", fill=palette["brandText"], align="left")
    sheet.label((text_x + width, top - 34), second, size="wordmark", font="bold", fill=palette["accent"], align="left")
    sheet.label((text_x, top - 46), brand["tagline"].upper(), size="tagline", fill=palette["accent"], align="left")
    y = top - 62 - pad

    def heading(text: str) -> None:
        nonlocal y
        sheet.label((x0 + pad, y - sizes["heading"]), text.upper(), size="heading", font="bold", fill=palette["muted"], align="left")
        y -= sizes["heading"] + 4

    def rule() -> None:
        nonlocal y
        y -= 3
        page.line((x0 + pad, y), (x1 - pad, y), stroke=sheet.styles["rule"]["stroke"], width=sheet.styles["rule"]["width"])
        y -= 7

    heading("Project")
    for line in _wrap(data.layout.get("displayName") or data.layout.get("layoutId") or "Facility layout", inner, sizes["project"], "bold"):
        sheet.label((x0 + pad, y - sizes["project"]), line, size="project", font="bold", align="left")
        y -= sizes["project"] + 2
    geo = (data.site or {}).get("georeference") or {}
    if geo.get("originLatitude") is not None:
        lat, lon = float(geo["originLatitude"]), float(geo["originLongitude"])
        place = geo.get("label") or ""
        where = f"{abs(lat):.5f}\xb0 {'N' if lat >= 0 else 'S'}, {abs(lon):.5f}\xb0 {'E' if lon >= 0 else 'W'}"
        for line in _wrap((place + "  " if place else "") + where, inner, sizes["body"]):
            sheet.label((x0 + pad, y - sizes["body"] - 1), line, size="body", align="left", fill=palette["muted"])
            y -= sizes["body"] + 3
    rule()
    heading("Sheet")
    sheet.label((x0 + pad, y - sizes["sheetTitle"]), spec["title"], size="sheetTitle", font="bold", align="left")
    y -= sizes["sheetTitle"] + 4
    sheet.label((x0 + pad, y - sizes["body"]), _scale_text(sheet.scale_feet), size="body", align="left")
    y -= sizes["body"] + 3
    rule()
    heading("Key numbers")
    for name, value in numbers:
        lines = _wrap(value, inner * 0.58, sizes["body"])
        sheet.label((x0 + pad, y - sizes["body"]), name, size="body", align="left", fill=palette["muted"])
        for line in lines:
            sheet.label((x1 - pad, y - sizes["body"]), line, size="body", font="bold", align="right")
            y -= sizes["body"] + 3
        y -= 1
    rule()
    heading("Legend")
    column = inner / 2
    for i, (style_key, swatch) in enumerate(sheet.legend):
        cx = x0 + pad + (i % 2) * column
        if i % 2 == 0 and i:
            y -= 11
        _legend_swatch(sheet, style_key, swatch, cx, y - 7)
        label = sheet.styles[style_key]["label"]
        if style_key == "zone":
            label = "Zone (colour by use)"
        sheet.label((cx + 23, y - 6), label, size="smallLabel", align="left")
    y -= 14
    rule()
    heading("Notes")
    for number, note in enumerate(list(sheet.template["notes"]) + list(spec.get("notes") or []), start=1):
        for k, line in enumerate(_wrap(note, inner - 10, sizes["note"])):
            if k == 0:
                sheet.label((x0 + pad, y - sizes["note"]), f"{number}.", size="note", align="left", fill=palette["muted"])
            sheet.label((x0 + pad + 10, y - sizes["note"]), line, size="note", align="left", fill=palette["muted"])
            y -= sizes["note"] + 2.5
        y -= 1.5
    # Sheet block along the bottom.
    block_top = y0 + 70
    page.line((x0, block_top), (x1, block_top), stroke=sheet.styles["frame"]["stroke"], width=0.8)
    page.line((x0 + (x1 - x0) * 0.58, y0), (x0 + (x1 - x0) * 0.58, block_top), stroke=sheet.styles["rule"]["stroke"], width=0.5)
    rows = (("Date", today), ("Revision", (revision or "unsaved")[:12]), ("Layout", data.layout.get("layoutId") or ""))
    ry = block_top - 8
    for name, value in rows:
        sheet.label((x0 + pad, ry - sizes["smallLabel"]), name.upper(), size="smallLabel", font="bold", fill=palette["muted"], align="left")
        for line in _wrap(value, (x1 - x0) * 0.58 - pad * 2 - 34, sizes["smallLabel"])[:2]:
            sheet.label((x0 + pad + 34, ry - sizes["smallLabel"]), line, size="smallLabel", align="left")
            ry -= sizes["smallLabel"] + 2
        ry -= 4
    sx = x0 + (x1 - x0) * 0.79
    sheet.label((sx, block_top - 14), "SHEET", size="heading", font="bold", fill=palette["muted"])
    sheet.label((sx, block_top - 38), spec["number"], size="sheetNumber", font="bold")
    sheet.label((sx, block_top - 52), f"{index} OF {count}", size="body")


def _logo(document: Document, template: Mapping[str, Any]) -> str | None:
    brand = template.get("brand") or {}
    path = APP_ROOT / str(brand.get("logoPath") or "")
    if not brand.get("logoPath") or not path.is_file():
        return None
    try:
        from PIL import Image
        with Image.open(path) as source:
            image = source.convert("RGBA")
        u0, v0, u1, v1 = brand.get("logoUv") or (0, 0, 1, 1)
        w, h = image.size
        image = image.crop((round(u0 * w), round((1 - v1) * h), round(u1 * w), round((1 - v0) * h)))
        image = image.resize((160, 160), Image.LANCZOS)
        rgb = image.convert("RGB").tobytes()
        alpha = image.getchannel("A").tobytes()
    except (OSError, ValueError):
        return None
    return document.add_image("Logo", 160, 160, rgb, alpha)


# --- the document -------------------------------------------------------------------------------------------------------
def _site_numbers(data: PlanData) -> list[tuple[str, str]]:
    lot = abs(_area(data.site["boundary"]))
    rows = [("Property area", f"{lot / M2_PER_ACRE:,.2f} acres ({lot:,.0f} m\xb2)")]
    if data.building:
        footprint = data.width * data.depth
        rows += [("Building", f"{feet_inches(data.width)} x {feet_inches(data.depth)}"),
                 ("Footprint", area_label(footprint)), ("Lot coverage", f"{footprint / lot * 100:.0f}%")]
    docks = sum(1 for o in data.openings if o["kind"] == "dock")
    if docks:
        rows.append(("Dock doors", str(docks)))
    if data.count("truck"):
        rows.append(("Trucks at docks", str(data.count("truck"))))
    if data.stalls():
        rows.append(("Car parking", f"{data.stalls()} stalls"))
    for route in data.site["routes"]:
        rows.append((f"{'Truck' if route['use'] == 'trucks' else 'Car'} route",
                     f"{feet_inches(route['length'])} ({route['length']:,.0f} m) to {_short_road(route['mainRoad'])}"))
    return rows


def _floor_numbers(data: PlanData) -> list[tuple[str, str]]:
    rows = []
    if data.building:
        rows += [("Building", f"{feet_inches(data.width)} x {feet_inches(data.depth)}"),
                 ("Floor area", area_label(data.width * data.depth))]
    height = data.wall_settings.get("heightMeters")
    if height:
        rows.append(("Wall height", length_label(float(height))))
    docks = [o for o in data.openings if o["kind"] == "dock"]
    if docks:
        rows.append(("Dock doors", f"{len(docks)} at {feet_inches(docks[0]['width'])} wide"))
    doors = sum(1 for o in data.openings if o["kind"] == "door")
    if doors:
        rows.append(("Personnel doors", str(doors)))
    inside = None if data.building is None else True
    for kind, name in (("rack", "Rack bays"), ("forklift", "Forklifts"), ("equipment", "Equipment")):
        if data.count(kind, inside):
            rows.append((name, str(data.count(kind, inside))))
    aisles = [a for a in data.aisles if data.building is None or _inside(_xz(a["centerline"][0]), data.building)]
    if aisles:
        rows.append(("Aisles", str(len(aisles))))
    return rows


SITE_SHEETS = ("site", "setting-out")  # drawn only for a layout placed on a site


def render_plan_pdf(layout: Mapping[str, Any], resolve_asset: AssetResolver | None = None, *, revision: str = "",
                    now: datetime | None = None, template: Mapping[str, Any] | None = None,
                    fit: Mapping[str, Any] | None = None) -> bytes:
    """The layout's plan sheets as PDF bytes: for a layout placed on a site a site plan and a setting-out plan (with
    the fit check's result, when given), and always a floor plan."""
    template = template or load_template()
    data = PlanData(layout, resolve_asset)
    frames = Frames(template)
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    name = layout.get("displayName") or layout.get("layoutId") or "Facility layout"
    document = Document(title=f"{name} - plan", author="InspectorPro", subject="Facility layout plan sheets")
    logo = _logo(document, template)
    specs = [spec for spec in template["sheets"]
             if spec["kind"] not in SITE_SHEETS or (data.site is not None and (spec["kind"] == "site" or data.building))]
    for index, spec in enumerate(specs, start=1):
        page = document.add_page(frames.width, frames.height)
        sheet = Sheet(page, template)
        frame = frames.frame
        page.rect(frame[0], frame[1], frame[2] - frame[0], frame[3] - frame[1], stroke=sheet.styles["frame"]["stroke"],
                  width=sheet.styles["frame"]["width"])
        if spec["kind"] == "site":
            drawn, numbers = draw_site_sheet(sheet, frames, data), _site_numbers(data)
        elif spec["kind"] == "setting-out":
            drawn, numbers = draw_setting_out_sheet(sheet, frames, data, fit), _setting_out_numbers(data)
        else:
            drawn, numbers = draw_floor_sheet(sheet, frames, data), _floor_numbers(data)
        sheet.scale_feet = drawn["feet"]
        north = data.site["north"] if data.site else None
        _draw_title_band(sheet, frames, spec, drawn["view"], data, north)
        _draw_title_strip(sheet, frames, spec, data, numbers, index, len(specs), revision, today, logo)
    return document.to_bytes()


def _fit_check(service, principal, site_id: str, layout: Mapping[str, Any]) -> dict[str, Any] | None:
    """The fit check for the setting-out sheet, with the site's stored photo when there is one."""
    from .site_context import normalize_site_context
    from .site_reference_fit import check_references
    raw = (layout.get("extensions") or {}).get(SITE_KEY)
    if not isinstance(raw, Mapping):
        return None
    try:
        site = normalize_site_context(raw, layout)
        photo = None
        if site.get("imagery"):
            from .site_imagery import site_photo_path
            from .site_trace import _site_photo
            photo = _site_photo(site, lambda image: site_photo_path(service, principal, site_id, image["imageId"]))
        return check_references(site, layout, photo)
    except (ValueError, KeyError, FacilityLayoutError):
        return None


# --- HTTP -----------------------------------------------------------------------------------------------------------------
def create_plan_pdf_router(*, service, principal_resolver, feature_gate=None):
    router = APIRouter()

    @router.get("/api/facility-layouts/{site_id}/{layout_id}/plan.pdf")
    async def plan_pdf(site_id: str, layout_id: str, request: Request):
        try:
            principal = principal_resolver(request)

            def build() -> bytes:
                current = service.get_layout(principal, site_id, layout_id)
                cache: dict[tuple[str, str], Any] = {}

                def resolve(asset_id: str, revision: str):
                    key = (asset_id, revision)
                    if key not in cache:
                        try:
                            cache[key] = service._resolve_asset_dependency(principal, site_id, asset_id, revision)[0]
                        except FacilityLayoutError:
                            cache[key] = None
                    return cache[key]
                return render_plan_pdf(current["layout"], resolve, revision=current.get("revision") or "",
                                       fit=_fit_check(service, principal, site_id, current["layout"]))
            content = await run_in_threadpool(build)
        except FacilityLayoutError as exc:
            return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})
        filename = (re.sub(r"[^A-Za-z0-9._-]+", "-", layout_id).strip("-")[:80] or "layout") + "-plan.pdf"
        return Response(content=content, media_type="application/pdf", headers={
            "Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff"})

    return router
