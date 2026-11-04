"""Where new items can stand (docs/sage-basic-shapes-plan.md, BS4): a deterministic obstacle map of a layout, as the
Factory 02 column search was, made from what the spatial checks see (spatial.py): the items' footprints and heights,
their clearance envelopes, the shell's walls and other obstacles, the floor, the aisle routes, the zones that take no
placements and the floor markings that keep the floor clear.

A grid point (place_grid) keeps GRID_CLEARANCES:
- 0.25 m from equipment, fences, racks and every other item its height meets, from walls and other shell obstacles,
  and from crosswalk, keep-clear and parking markings;
- 0.5 m from forklift and material aisles (a route's corridor: its centre line and width);
- out of walkways (pedestrian aisles), zones that take no placements and items' clearance envelopes (service,
  operator, door swing, ...); touching counts, as the checks count it;
- on the floor.
A run (place_along_line) stops RUN_GAP short of the same things, aisle routes included: a run beside an aisle or
walkway stays clear of its corridor, and where one crosses the line (the walkway through a door, say) the run leaves
an opening, as the checks would otherwise warn of a blocked aisle.
Overhead items (lowest point 4.5 m up or more) skip the aisles, zones, markings and floor, as the checks do; items,
envelopes and walls count wherever their height meets the new item's.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
import math
from typing import Any, Iterable, Mapping, Sequence

from shapely import STRtree
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .spatial import (_NON_PLACEMENT_ZONE_TYPES, OVERHEAD_MINIMUM_CLEARANCE, _aisle_segment_polygon, _asset_catalog,
                      _asset_field, _catalog_asset, _clearance_templates, _layout_placement_records,
                      _normalized_authority, _placement_clearance_records_from_templates, _prepare_mounting_surfaces,
                      _prepare_transform, oriented_box_polygon, shell_obstacle_records)

ITEM, WALL, ENVELOPE, MARKING, VEHICLE_AISLE, WALKWAY, ZONE = (
    "item", "wall", "envelope", "marking", "vehicle aisle", "walkway", "zone")
GRID_CLEARANCES = {ITEM: 0.25, WALL: 0.25, MARKING: 0.25, VEHICLE_AISLE: 0.5, WALKWAY: 0.0, ZONE: 0.0, ENVELOPE: 0.0}
GRID_KEEPS = ("keeps 0.25 m from items (equipment, fences, racks), walls and crosswalk, keep-clear and parking "
              "markings, 0.5 m from forklift and material aisles, and stays out of walkways, zones that take no "
              "placements and items' clearance envelopes")
RUN_GAP = 0.05
RUN_KINDS = (ITEM, WALL, MARKING, ZONE, ENVELOPE, VEHICLE_AISLE, WALKWAY)
CLEAR_MARKINGS = ("crosswalk", "keep_clear", "parking_box")
VEHICLE_AISLES = ("forklift", "material")
FLOOR_ONLY = (MARKING, VEHICLE_AISLE, WALKWAY, ZONE)
ORDER = {WALL: 0, ITEM: 1, ENVELOPE: 2, ZONE: 3, VEHICLE_AISLE: 4, WALKWAY: 5, MARKING: 6}
OFF_FLOOR = "off the floor"
EPSILON = 1e-9


@dataclass(frozen=True)
class Obstacle:
    kind: str
    name: str            # as a reason names it: "CNC lathe 2", "forklift aisle 'Material spine'"
    shape: Polygon
    low: float = -math.inf
    high: float = math.inf


def _polygon(points: Sequence[Sequence[float]]) -> Polygon | None:
    shape = Polygon(points)
    if not shape.is_valid:
        shape = shape.buffer(0)
    return shape if not shape.is_empty and shape.area > EPSILON else None


def _wall_name(feature_id: str) -> str:
    if feature_id.startswith("layout-perimeter-wall"):
        return "the outer wall"
    if feature_id.startswith("layout-interior-wall-"):
        name = feature_id[len("layout-interior-wall-"):]
        head, _, tail = name.rpartition("-")
        return f"interior wall {head if tail.isdigit() and head else name}"
    return f"wall {feature_id}"


class ObstacleMap:
    """The layout's obstacles, queried by footprint (grid points) or along a band (runs). Without asset definitions
    and a shell (a layout on its own, as in tests) it holds the aisle routes, zones and markings only."""

    def __init__(self, layout: Mapping[str, Any], *, shell: Mapping[str, Any] | None = None,
                 asset_definitions: Mapping | Sequence | None = None, evidence_authority: Any = None):
        self.obstacles: list[Obstacle] = []
        if asset_definitions:
            self._items(layout, _asset_catalog(asset_definitions), _normalized_authority(evidence_authority))
        self._shell(shell)
        self._routes(layout)
        self._zones(layout)
        self._markings(layout)
        self.tree = STRtree([obstacle.shape for obstacle in self.obstacles])
        self.floor = self._floor(shell)
        extensions = shell.get("extensions") if isinstance(shell, Mapping) else None
        self.ground = extensions.get("facilityGround") if isinstance(extensions, Mapping) else None

    # --- what the map holds ---

    def _add(self, kind: str, name: str, points, low: float = -math.inf, high: float = math.inf) -> None:
        shape = _polygon(points) if not hasattr(points, "geom_type") else (None if points.is_empty else points)
        if shape is not None:
            self.obstacles.append(Obstacle(kind, name, shape, low, high))

    def _items(self, layout, catalog, authority) -> None:
        records, _ = _layout_placement_records(layout, catalog)
        placements = {str(item.get("placementId")): item for item in layout.get("placements") or []
                      if isinstance(item, Mapping) and item.get("placementId")}
        for placement_id in sorted(records):
            placement = placements[placement_id]
            asset = _catalog_asset(catalog, str(placement.get("assetId") or ""),
                                   str(placement.get("assetDefinitionRevision") or ""))
            metadata = placement.get("metadata") if isinstance(placement.get("metadata"), Mapping) else {}
            name = str(metadata.get("instanceLabel") or (asset and _asset_field(asset, "displayName"))
                       or placement_id)
            for record in records[placement_id]:
                self._add(ITEM, name, record.polygon, record.minimum_y, record.maximum_y)
            if asset is None:
                continue
            try:
                templates = _clearance_templates(asset, authority)
                envelopes = _placement_clearance_records_from_templates(
                    placement, str(placement.get("assetId")), templates,
                    prepared_transform=_prepare_transform(placement["transform"])) if templates else ()
            except (KeyError, TypeError, ValueError):
                continue
            for record in envelopes:
                kind = str(record.clearance_kind or "safety").replace("_", " ")
                self._add(ENVELOPE, f"the {kind} clearance of {name}", record.polygon, record.minimum_y,
                          record.maximum_y)

    def _shell(self, shell) -> None:
        features = {str(feature.get("featureId") or ""): feature for feature in (shell or {}).get("features") or []
                    if isinstance(feature, Mapping)}
        for record in shell_obstacle_records(shell):
            kind = str(features.get(record.owner_id, {}).get("featureKind") or "")
            name = (_wall_name(record.owner_id) if kind == "wall"
                    else f"{kind.replace('_', ' ')} {record.owner_id}")
            self._add(WALL, name, record.polygon, record.minimum_y, record.maximum_y)

    def _routes(self, layout) -> None:
        for route in layout.get("routes") or []:
            if not isinstance(route, Mapping):
                continue
            extensions = route.get("extensions") if isinstance(route.get("extensions"), Mapping) else {}
            aisle = extensions.get("facilityAisle")
            if not isinstance(aisle, Mapping):
                continue
            try:
                points = [(float(point["x"]), float(point["z"])) for point in route.get("centerline") or []]
                width = float(route.get("corridorWidth"))
            except (KeyError, TypeError, ValueError):
                continue
            segments = [_aisle_segment_polygon(a, b, width) for a, b in zip(points, points[1:])]
            shapes = [shape for shape in (_polygon(segment) for segment in segments if segment) if shape]
            if not shapes:
                continue
            kind = str(aisle.get("aisleKind") or "")
            label = str(route.get("label") or route.get("routeId") or "")
            if kind in VEHICLE_AISLES:
                self._add(VEHICLE_AISLE, f"{kind} aisle '{label}'", unary_union(shapes))
            else:
                self._add(WALKWAY, f"walkway '{label}'", unary_union(shapes))

    def _zones(self, layout) -> None:
        for zone in layout.get("zones") or []:
            if not isinstance(zone, Mapping) or str(zone.get("zoneType") or "") not in _NON_PLACEMENT_ZONE_TYPES:
                continue
            try:
                points = [(float(point["x"]), float(point["z"])) for point in zone["boundary"]]
            except (KeyError, TypeError, ValueError):
                continue
            if len(points) >= 3:
                label = str(zone.get("label") or zone.get("zoneId") or "")
                self._add(ZONE, f"{zone['zoneType']} zone '{label}'", points)

    def _markings(self, layout) -> None:
        for marking in layout.get("floorMarkings") or []:
            if not isinstance(marking, Mapping) or marking.get("markingType") not in CLEAR_MARKINGS:
                continue
            try:
                transform = marking["transform"]
                center = (float(transform["position"]["x"]), float(transform["position"]["z"]))
                half = (float(marking["width"]) / 2, float(marking["depth"]) / 2)
                turn = math.radians(float(transform.get("rotationDegrees", 0) or 0))
            except (KeyError, TypeError, ValueError):
                continue
            if half[0] > 0 and half[1] > 0:
                label = str(marking.get("label") or marking.get("markingId") or "")
                self._add(MARKING, f"{marking['markingType'].replace('_', ' ')} marking '{label}'",
                          oriented_box_polygon(center, half, turn))

    @staticmethod
    def _floor(shell):
        if not isinstance(shell, Mapping):
            return None
        floors = [_polygon(boundary) for _, kind, boundary in _prepare_mounting_surfaces(shell)
                  if kind == "floor" and boundary]
        floors = [shape for shape in floors if shape is not None]
        return unary_union(floors) if floors else None

    # --- queries ---

    def _near(self, shape, reach: float) -> Iterable[Obstacle]:
        for index in sorted(self.tree.query(shape.buffer(reach) if reach > 0 else shape)):
            yield self.obstacles[int(index)]

    def reasons(self, footprint: Polygon, low: float, high: float,
                clearances: Mapping[str, float] = GRID_CLEARANCES) -> list[str]:
        """Why an item with this footprint and height cannot stand here; empty when it can."""
        overhead = low >= OVERHEAD_MINIMUM_CLEARANCE - EPSILON
        found: dict[str, tuple] = {}
        if not overhead and not self._on_floor(footprint, low):
            found[OFF_FLOOR] = (-1, 0.0)
        for obstacle in self._near(footprint, max(clearances.values(), default=0.0)):
            need = clearances.get(obstacle.kind)
            if need is None or (overhead and obstacle.kind in FLOOR_ONLY):
                continue
            if obstacle.high < low - EPSILON or high < obstacle.low - EPSILON:
                continue
            distance = footprint.distance(obstacle.shape)
            if distance > EPSILON and distance >= need - EPSILON:
                continue
            if obstacle.kind == ENVELOPE:
                reason = f"in {obstacle.name}"
            elif distance <= EPSILON:
                reason = ("in " if obstacle.kind in (VEHICLE_AISLE, WALKWAY, ZONE) else "on ") + obstacle.name
            else:
                reason = f"{distance:.2f} m from {obstacle.name} (keeps {need:g} m)"
            key = (ORDER[obstacle.kind], distance)
            if reason not in found or key < found[reason]:
                found[reason] = key
        return [reason for reason, _ in sorted(found.items(), key=lambda item: item[1])]

    def _on_floor(self, footprint: Polygon, elevation: float) -> bool:
        """As the mounting check sees a floor item: on one level stretch of site ground, or inside a floor."""
        if self.ground is not None:
            from .ground import supports_footprint
            return supports_footprint(self.ground, list(footprint.exterior.coords)[:-1], elevation)
        return self.floor is None or self.floor.covers(footprint)

    def touching(self, shape: Polygon, kinds: Sequence[str]) -> list[str]:
        """The obstacles of these kinds a shape meets (a column strip may not cross an aisle route)."""
        return sorted({obstacle.name for obstacle in self._near(shape, 0.0)
                       if obstacle.kind in kinds and obstacle.shape.intersects(shape)})

    def blocked_along(self, origin, along, length: float, half_width: float, low: float, high: float,
                      kinds: Sequence[str] = RUN_KINDS, gap: float = RUN_GAP) -> list[tuple[float, float, str]]:
        """Where along a run (0 to length) its band of half_width meets an obstacle, widened by `gap` at both ends:
        (start, end, name)."""
        overhead = low >= OVERHEAD_MINIMUM_CLEARANCE - EPSILON
        left = (-along[1], along[0])
        band = _polygon([(origin[0] + along[0] * a + left[0] * b, origin[1] + along[1] * a + left[1] * b)
                         for a, b in ((-gap, -half_width), (length + gap, -half_width), (length + gap, half_width),
                                      (-gap, half_width))])
        found = []
        for obstacle in self._near(band, 0.0):
            if obstacle.kind not in kinds or (overhead and obstacle.kind in FLOOR_ONLY):
                continue
            if obstacle.high < low - EPSILON or high < obstacle.low - EPSILON:
                continue
            if not obstacle.shape.intersects(band):
                continue
            part = obstacle.shape.intersection(band)
            spans = [(x - origin[0]) * along[0] + (z - origin[1]) * along[1] for x, z in _coordinates(part)]
            if not spans:
                continue
            start, end = min(spans) - gap, max(spans) + gap
            if end >= 0 and start <= length:
                found.append((max(start, 0.0), min(end, length), obstacle.name))
        return found

    # --- the plan picture ---

    def picture(self, view: tuple[float, float, float, float], low: float, high: float, *,
                x_lines: Sequence[tuple[str, float]] = (), z_lines: Sequence[tuple[str, float]] = (),
                placed: Sequence[Polygon] = (), dropped: Sequence[tuple[float, float]] = (),
                strips: Sequence[Polygon] = (), caption: str = "") -> bytes:
        """A plan (north up) of what is in the way of items from low to high, the grid lines, the placed items
        (black), the points left out (red x) and the new strips (orange), for Sage to check by eye: PNG bytes."""
        overhead = low >= OVERHEAD_MINIMUM_CLEARANCE - EPSILON
        shown = [obstacle for obstacle in self._near(box(*view), 0.0)
                 if not (overhead and obstacle.kind in FLOOR_ONLY)
                 and not (obstacle.high < low - EPSILON or high < obstacle.low - EPSILON)]
        return _draw(self.floor if not overhead else None, shown, view, x_lines, z_lines, placed, dropped, strips,
                     caption)


def _coordinates(shape) -> list[tuple[float, float]]:
    if shape.is_empty:
        return []
    if hasattr(shape, "geoms"):
        return [point for part in shape.geoms for point in _coordinates(part)]
    if isinstance(shape, Polygon):
        return [tuple(point) for point in shape.exterior.coords]
    return [tuple(point) for point in shape.coords]


def _parts(shape) -> list[Polygon]:
    if shape.is_empty:
        return []
    if hasattr(shape, "geoms"):
        return [part for item in shape.geoms for part in _parts(item)]
    return [shape] if isinstance(shape, Polygon) else []


# The picture: light and plain, for a model to read. Colours by kind.
PICTURE_SIZE = (1100, 760)
SUPERSAMPLE = 2
FILL = {VEHICLE_AISLE: (201, 206, 211), WALKWAY: (205, 230, 247), ZONE: (243, 217, 217), ITEM: (216, 196, 143),
        WALL: (57, 66, 74)}
OUTLINE = {MARKING: (208, 106, 106), ENVELOPE: (232, 163, 61), ITEM: (122, 101, 50), ZONE: (192, 128, 128)}
LEGEND = ("grey: forklift and material aisles; blue: walkways; pink: zones that take no placements; tan: items; "
          "dark: walls; orange outline: clearance envelopes; red outline: keep-clear markings")


def _draw(floor, shown: Sequence[Obstacle], view, x_lines, z_lines, placed, dropped, strips, caption) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    k = SUPERSAMPLE
    width, height = PICTURE_SIZE[0] * k, PICTURE_SIZE[1] * k
    pad, legend = 34 * k, 62 * k
    west, south, east, north = view
    scale = min((width - 2 * pad) / max(east - west, 1e-6), (height - 2 * pad - legend) / max(north - south, 1e-6))
    left = (width - (east - west) * scale) / 2
    top = pad + ((height - 2 * pad - legend) - (north - south) * scale) / 2

    def at(x, z):
        return left + (x - west) * scale, top + (north - z) * scale

    def ring(shape):
        return [at(x, z) for x, z in shape.exterior.coords]

    image = Image.new("RGB", (width, height), (233, 236, 239))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=13 * k)
    frame = box(west, south, east, north)
    draw.rectangle([at(west, north), at(east, south)], fill=(250, 250, 250))
    if floor is not None:
        for part in _parts(floor.intersection(frame)):
            draw.polygon(ring(part), fill=(255, 255, 255), outline=(154, 163, 171))
    for kind in (ZONE, VEHICLE_AISLE, WALKWAY, ITEM, ENVELOPE, MARKING, WALL):
        for obstacle in shown:
            if obstacle.kind != kind:
                continue
            for part in _parts(obstacle.shape.intersection(frame)):
                draw.polygon(ring(part), fill=FILL.get(kind), outline=OUTLINE.get(kind), width=k if kind in OUTLINE
                             else 1)
    for strip in strips:
        draw.polygon(ring(strip), fill=(242, 166, 90), outline=(196, 106, 16), width=k)
    dash = 6 * k
    for name, x in x_lines:
        sx = at(x, 0)[0]
        for y in range(int(top), int(top + (north - south) * scale), 2 * dash):
            draw.line([(sx, y), (sx, min(y + dash, top + (north - south) * scale))], fill=(92, 102, 112), width=k)
        draw.text((sx, top - 4 * k), name, fill=(20, 24, 28), font=font, anchor="mb")
    for name, z in z_lines:
        sy = at(0, z)[1]
        for x in range(int(left), int(left + (east - west) * scale), 2 * dash):
            draw.line([(x, sy), (min(x + dash, left + (east - west) * scale), sy)], fill=(92, 102, 112), width=k)
        draw.text((left - 5 * k, sy), name, fill=(20, 24, 28), font=font, anchor="rm")
    for shape in placed:
        x0, z0, x1, z1 = shape.bounds
        cx, cz = at((x0 + x1) / 2, (z0 + z1) / 2)
        half = max((x1 - x0) * scale / 2, 3 * k)
        draw.rectangle([cx - half, cz - half, cx + half, cz + half], fill=(31, 41, 51))
    for x, z in dropped:
        cx, cz = at(x, z)
        r = 5 * k
        draw.line([(cx - r, cz - r), (cx + r, cz + r)], fill=(214, 40, 40), width=2 * k)
        draw.line([(cx - r, cz + r), (cx + r, cz - r)], fill=(214, 40, 40), width=2 * k)
    draw.text((pad, height - legend + 8 * k), caption, fill=(20, 24, 28), font=font)
    draw.text((pad, height - legend + 30 * k), LEGEND, fill=(70, 78, 86), font=ImageFont.load_default(size=11 * k))
    draw.text((width - pad, pad - 18 * k), "N up", fill=(70, 78, 86), font=font, anchor="rs")
    image = image.resize(PICTURE_SIZE, Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()
