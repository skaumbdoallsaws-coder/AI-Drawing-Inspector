"""A revision-bound rectangular gap measured from the existing facility read sources."""
from copy import deepcopy
import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .policy import PilotError

NAME = "measure_facility_gap"
KINDS = ("column", "interior_wall", "perimeter_wall", "marking", "placement", "zone")
EDGES = {"+x": (1, 0), "-x": (-1, 0), "+z": (0, 1), "-z": (0, -1)}


def tool_spec():
    reference = {"type": "object", "properties": {
        "kind": {"enum": list(KINDS)}, "id": {"type": "string", "minLength": 1, "maxLength": 128},
        "edge": {"enum": list(EDGES)}}, "required": ["kind", "id"],
        "if": {"properties": {"kind": {"enum": ["interior_wall", "perimeter_wall", "zone"]}},
               "required": ["kind"]}, "then": {"required": ["edge"]}, "additionalProperties": False}
    return {"name": NAME, "description":
        "Measure a clear rectangular gap in the saved layout, between typed column, wall, marking, placement, or "
        "zone edges. Wall and zone references require edge (+x, -x, +z, -z). Use depth in metres or a zone region "
        "when the references do not bound depth. The answer reports obstructions; it never shrinks the gap silently. "
        "Deduct clearances once before setting a model recipe's fitsWithin.",
        "input_schema": {"type": "object", "properties": {"from": reference, "to": reference,
            "depth": {"type": "number", "exclusiveMinimum": 0, "maximum": 30},
            "region": {"type": "string", "minLength": 1, "maxLength": 128}},
            "required": ["from", "to"], "additionalProperties": False}}


def _error(code, message):
    raise PilotError(code, message, 422)


def _poly(points):
    try:
        value = Polygon([(p["x"], p["z"]) if isinstance(p, dict) else p for p in points])
        if not value.is_valid or value.area <= 1e-8:
            raise ValueError("Invalid footprint")
        return value
    except (KeyError, TypeError, ValueError):
        _error("gap_geometry_unsupported", "A reference has no usable rectangular footprint.")


def _sources(runtime, principal, reference):
    bundle = runtime.resolve_context(principal, site_id=reference["siteId"],
                                     layout_id=reference["layoutId"], expected_revision=reference["revision"])
    layout, shell = bundle.layout_document, bundle.shell_document
    rows = []
    for zone in layout.get("zones", []):
        rows.append(("zone", zone["zoneId"], _poly(zone["boundary"]), zone.get("heightLimit")))
    for column in layout.get("extensions", {}).get("facilityColumns", {}).get("columns", []):
        from ai_inspector.facility_layout.columns import footprint
        rows.append(("column", column["columnId"], _poly(column.get("footprint") or footprint(column)), None))
    for wall in layout.get("extensions", {}).get("facilityInteriorWalls", {}).get("walls", []):
        panels = wall.get("panels") or []
        if panels:
            rows.append(("interior_wall", wall["wallId"], unary_union([_poly(p) for p in panels]), None))
    # The app's own marking footprint (circulation.py), so a rotated marking turns the same way here as there.
    from ai_inspector.facility_layout.circulation import FacilityCirculationError, _floor_marking_polygon
    for marking in layout.get("floorMarkings", []):
        try:
            polygon = _floor_marking_polygon(marking)
        except FacilityCirculationError:
            polygon = None
        if polygon is not None and polygon.is_valid and polygon.area > 1e-8:
            rows.append(("marking", marking["markingId"], polygon, None))
    from ai_inspector.facility_layout.spatial import placement_spatial_records
    for placement in layout.get("placements", []):
        asset = runtime.service._resolve_asset_definition(principal, reference["siteId"],
                                                          placement["assetId"], placement["assetDefinitionRevision"])
        polygons = [_poly(record.polygon) for record in placement_spatial_records(placement, asset)]
        rows.append(("placement", placement["placementId"], unary_union(polygons), None))
    for feature in shell.get("features", []):
        identifier = feature.get("featureId", "")
        if (feature.get("featureKind") != "wall" or identifier.startswith("layout-interior-wall-")):
            continue
        geometry = feature.get("geometry") or {}
        boundary = geometry.get("boundary") or geometry.get("footprint")
        if boundary:
            rows.append(("perimeter_wall", identifier, _poly(boundary), None))
    return rows


def _rectangle(polygon):
    if polygon.geom_type != "Polygon":
        _error("gap_geometry_unsupported", "The reference does not have one rectangular footprint.")
    rectangle = polygon.minimum_rotated_rectangle
    if abs(rectangle.area - polygon.area) > max(1e-6, polygon.area*1e-5):
        _error("gap_geometry_unsupported", "The reference does not have one rectangular footprint.")
    coords = list(rectangle.exterior.coords)[:-1]
    if not rectangle.exterior.is_ccw:
        coords.reverse()
    result = []
    for a, b in zip(coords, coords[1:] + coords[:1]):
        dx, dz = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dz)
        result.append((a, (dz/length, -dx/length)))
    return result


def _selected_edges(polygon, requested):
    edges = _rectangle(polygon)
    if requested is None:
        return edges
    direction = EDGES[requested]
    found = [item for item in edges if item[1][0]*direction[0]+item[1][1]*direction[1] > .9999]
    if len(found) != 1:
        _error("gap_geometry_unsupported", "That edge is not an axis-facing edge of the reference.")
    return found


def _project(polygon, axis):
    values = [x*axis[0]+z*axis[1] for x, z in list(polygon.exterior.coords)[:-1]]
    return min(values), max(values)


def measure(runtime, principal, reference, args):
    rows = _sources(runtime, principal, reference)
    table = {(kind, identifier): (shape, height) for kind, identifier, shape, height in rows}
    a, b = args["from"], args["to"]
    if (a["kind"], a["id"]) == (b["kind"], b["id"]):
        _error("gap_reference_invalid", "Choose two different references.")
    try:
        pa, _ = table[(a["kind"], a["id"])]
        pb, _ = table[(b["kind"], b["id"])]
    except KeyError:
        _error("gap_reference_missing", "A named reference is unavailable in the saved layout or shell.")
    region = None
    if "region" in args:
        try:
            region, _ = table[("zone", args["region"])]
        except KeyError:
            _error("gap_reference_missing", "The named zone region is unavailable.")
    candidates = []
    needs_region = False
    for point_a, normal in _selected_edges(pa, a.get("edge")):
        tangent = (-normal[1], normal[0])
        alo, ahi = _project(pa, tangent)
        blo, bhi = _project(pb, tangent)
        overlap = min(ahi, bhi) - max(alo, blo)
        for point_b, other in _selected_edges(pb, b.get("edge")):
            if normal[0]*other[0]+normal[1]*other[1] > -.9999:
                continue
            width = (point_b[0]-point_a[0])*normal[0] + (point_b[1]-point_a[1])*normal[1]
            if width <= 1e-6 or width > 30:
                continue
            if overlap <= 1e-6 and region is None:
                needs_region = True
                continue
            candidates.append((width, -overlap, normal, tangent, point_a, alo, ahi, blo, bhi))
    if not candidates:
        if needs_region:
            _error("gap_region_required", "A zone region is required when the references do not overlap in depth.")
        _error("gap_geometry_unsupported", "The references do not face across a rectangular gap; use a zone "
               "region when they do not overlap in depth.")
    width, neg_overlap, normal, tangent, point, alo, ahi, blo, bhi = min(candidates)
    overlap = -neg_overlap
    if overlap > 1e-6:
        lo, hi = max(alo, blo), min(ahi, bhi)
        if "depth" in args:
            depth = args["depth"]
            if depth > hi-lo + 1e-7:
                _error("gap_depth_invalid", "The requested depth exceeds the reference overlap.")
            middle = (lo+hi)/2
            lo, hi = middle-depth/2, middle+depth/2
    else:
        if region is None:
            _error("gap_region_required", "A zone region is required when the references do not overlap in depth.")
        lo, hi = _project(region, tangent)
        if "depth" in args:
            depth = args["depth"]
            if depth > hi-lo + 1e-7:
                _error("gap_depth_invalid", "The requested depth exceeds the zone region.")
            middle = (lo+hi)/2
            lo, hi = middle-depth/2, middle+depth/2
    across = point[0]*normal[0]+point[1]*normal[1]
    def corner(u, v):
        return (normal[0]*u+tangent[0]*v, normal[1]*u+tangent[1]*v)
    corners = [corner(across, lo), corner(across+width, lo),
               corner(across+width, hi), corner(across, hi)]
    rectangle = Polygon(corners)
    if (not rectangle.is_valid or rectangle.area < 1e-8
            or region is not None and not region.buffer(1e-7).covers(rectangle)):
        _error("gap_geometry_unsupported", "The proposed gap is not a rectangle inside the zone region.")
    inner = rectangle.buffer(-.005, join_style=2)
    obstacles = [{"kind": kind, "id": identifier} for kind, identifier, polygon, _ in rows
                 if kind not in ("zone",) and not inner.is_empty and polygon.intersection(inner).area > 1e-8]
    if len(obstacles) > 100:
        _error("gap_obstructions_too_many", "More than 100 obstructions cross this gap; narrow the region.")
    height_limits = [limit for kind, identifier, polygon, limit in rows
                     if kind == "zone" and limit is not None and polygon.buffer(1e-7).covers(rectangle)]
    result = {"revision": reference["revision"], "references": {"from": deepcopy(a), "to": deepcopy(b),
              **({"region": args["region"]} if region is not None else {})},
              "width": round(width, 6), "depth": round(hi-lo, 6),
              "orientation": round(math.degrees(math.atan2(-normal[1], normal[0])), 6),
              "corners": [{"x": round(x, 6), "z": round(z, 6)} for x, z in corners],
              "clear": not obstacles, "obstructions": obstacles,
              **({"heightLimit": min(height_limits)} if height_limits else {})}
    return result
