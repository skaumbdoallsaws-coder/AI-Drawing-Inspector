"""Parking completeness evidence, not vehicle clearance or regulatory certification."""
import math
import re

from . import routing
from .spatial import oriented_box_polygon


VERSION = "parking-completeness-v1"
LIMITATIONS = [
    "Bay counts use explicit parking_box footprints; loose lines and vehicle placements are not counted as bays.",
    "Footprints with the staging role mark material staging (for example in front of dock doors), not parking.",
    "A corridor touching a bay is not proof that a vehicle can enter or turn.",
    "Vehicle swept paths, clear widths, obstacles, grades and external road connections require separate verification.",
    "Accessibility, fire access and local parking requirements are not certified by this review.",
]
CHECKLIST = [
    "Verify the requested number of usable spaces, actual vehicle dimensions and parking orientation.",
    "Reserve continuous drive aisles before placing bays; cars or painted arrows alone are not circulation.",
    "Connect the aisles to an entrance/exit and give every bay an accessible approach.",
    "Check turning/reversing space, obstacles and pedestrian access to the building.",
    "State assumptions, unresolved constraints and applicable-rule checks instead of calling an incomplete lot finished.",
]


def tool_spec():
    return {"name": "review_facility_parking", "description":
        "Review saved parking zones for bay count, authored aisle geometry, bay adjacency and boundary access evidence. "
        "Run before planning a parking lot and recheck after approved changes. Preview results also include changed-zone reviews. "
        "Warnings describe missing evidence, not proof of physical absence. Never certifies turning clearance or compliance.",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["zoneIds"], "properties": {
            "zoneIds": {"type": "array", "minItems": 1, "maxItems": 10, "uniqueItems": True,
                "items": {"type": "string", "pattern": "^zn-[A-Za-z0-9][A-Za-z0-9._:-]*$", "maxLength": 128}},
            "requestedSpaces": {"type": "integer", "minimum": 1, "maximum": 10000,
                "description": "Expected bay count per selected zone. Omit when zones have different capacities."}}}}


def _polygon(zone):
    return routing.Polygon([(p["x"], p["z"]) for p in zone["boundary"]])


def _mark_polygon(marking):
    transform = marking["transform"]
    p = transform["position"]
    return routing.Polygon(oriented_box_polygon((p["x"], p["z"]),
        (marking["width"] / 2, marking["depth"] / 2), math.radians(transform["rotationDegrees"])))


def _near_floor(y, zone):
    return abs(float(y) - float(zone["floorElevation"])) <= .1


def _is_bay(mark):
    # Any other role still counts: relabelling a bay must not take it out of the review.
    return mark.get("markingType") == "parking_box" and mark.get("semanticRole") != "staging"


def _records(layout, zone):
    area = _polygon(zone)
    bays, lanes, walks = [], [], []
    for mark in layout.get("floorMarkings", []):
        if not _near_floor(mark["transform"]["position"]["y"], zone):
            continue
        is_bay = _is_bay(mark)
        is_lane = mark["semanticRole"] == "forklift_lane" and mark["markingType"] == "keep_clear"
        if not (is_bay or is_lane):
            continue
        shape = _mark_polygon(mark)
        if shape.intersection(area).area > 1e-6:
            (bays if is_bay else lanes).append((mark["markingId"], shape))
    for route in layout.get("routes", []):
        points = route.get("centerline", [])
        width = route.get("corridorWidth", 0)
        if len(points) < 2 or width <= 0 or not all(_near_floor(p["y"], zone) for p in points):
            continue
        kind = route.get("routeKind")
        if kind not in {"forklift", "material", "operator"}:
            continue
        shape = routing.LineString([(p["x"], p["z"]) for p in points]).buffer(width / 2, cap_style=2)
        if shape.intersection(area).area > 1e-6:
            (walks if kind == "operator" else lanes).append((route["routeId"], shape))
    return area, bays, lanes, walks


def _review_zone(layout, zone, requested_spaces):
    area, bays, lanes, walks = _records(layout, zone)
    findings = []
    def finding(code, message, ids=()):
        findings.append({"code": code, "severity": "warning", "message": message,
                         "entityIds": list(ids)[:20]})
    contained = [(key, shape) for key, shape in bays if area.buffer(1e-6).covers(shape)]
    if not bays:
        finding("parking_spaces_unrepresented", "No explicit parking_box footprints were found. Bays drawn with loose lines require separate verification; vehicle count alone does not establish usable spaces.")
    if len(contained) != len(bays):
        finding("parking_bays_cross_zone_boundary", "Some bay footprints extend outside the parking zone.")
    if requested_spaces is not None and len(contained) != requested_spaces:
        finding("parking_capacity_mismatch", f"Found {len(contained)} contained marked bays; requested {requested_spaces}.")
    if not lanes:
        finding("parking_vehicle_aisle_missing", "No authored vehicle/material corridor or full-area vehicle-lane marking was found. Reserve a drive aisle; arrows alone are not an aisle.")
    # Connected components must reach the zone boundary. This is topological
    # evidence only; widths, obstructions and swept turns remain unverified.
    aisle_area = routing.unary_union([shape for _, shape in lanes]).intersection(area)
    components = list(aisle_area.geoms) if aisle_area.geom_type == "MultiPolygon" else (
        [aisle_area] if aisle_area.geom_type == "Polygon" and not aisle_area.is_empty else [])
    connected = [shape for shape in components if shape.boundary.intersection(area.boundary).length > 1e-5]
    if lanes and not connected:
        finding("parking_boundary_access_missing", "The authored aisle geometry does not reach the zone boundary. Provide an entry/exit connection.")
    unreachable, overlap = [], []
    for key, bay in contained:
        if bay.intersection(aisle_area).area > 1e-5:
            overlap.append(key)
        elif not any(bay.boundary.intersection(lane.boundary).length > 1e-5 for lane in connected):
            unreachable.append(key)
    if overlap:
        finding("parking_aisle_overlaps_bays", "Aisle area overlaps parking bays. Reserve distinct bay and circulation areas.", overlap)
    if unreachable:
        finding("parking_bay_access_unverified", "These bays lack a shared edge with an aisle connected to the zone boundary.", unreachable)
    if not walks:
        finding("parking_pedestrian_access_unverified", "No pedestrian route is represented in this zone. Check a safe connection to the building.")
    finding("parking_maneuvering_unverified", "Turning/reversing space, clear aisle width and external entry/exit suitability still need vehicle-specific verification.")
    return {"zoneId": zone["zoneId"], "label": zone["label"], "status": "needs_review",
        "markedBays": len(bays), "containedBays": len(contained), "requestedSpaces": requested_spaces,
        "aisleGeometryIds": [key for key, _ in lanes][:20], "boundaryConnectedComponents": len(connected),
        "pedestrianRouteIds": [key for key, _ in walks][:20], "findings": findings}


def review_parking(layout, zone_ids, requested_spaces=None):
    zones = {z["zoneId"]: z for z in layout.get("zones", [])}
    selected = sorted(set(zone_ids))
    unknown = [key for key in selected if key not in zones]
    if unknown:
        from .errors import FacilityValidationError
        raise FacilityValidationError("parking_zone_missing", "Inspect the current zone IDs before reviewing parking.",
                                      details={"references": unknown[:10]})
    result = {"reviewVersion": VERSION, "status": "needs_review", "certified": False,
              "checklist": CHECKLIST, "limitations": LIMITATIONS, "reviews": []}
    if len(selected) > 10 or sum(len(layout.get(k, [])) for k in ("zones", "floorMarkings", "routes")) > 20000:
        return dict(result, status="not_checked", reason="Review fewer zones or reduce the geometry scope.")
    if routing.Polygon is None:
        return dict(result, status="not_checked", reason="The deterministic geometry dependency is unavailable.")
    result["reviews"] = [_review_zone(layout, zones[key], requested_spaces) for key in selected]
    return result


def _scope_snapshot(layout, zone):
    from shapely.geometry import Point
    area, bays, lanes, walks = _records(layout, zone)
    # Finishes do not change parking function; placement motion does.
    placements = [(p["placementId"], p["assetId"], p["assetDefinitionRevision"], p["transform"])
        for p in layout.get("placements", []) if area.covers(Point(
            p["transform"]["position"]["x"], p["transform"]["position"]["z"]))
        and _near_floor(p["transform"]["position"]["y"], zone)]
    return (zone["label"], zone["boundary"], zone["floorElevation"],
            sorted((key, shape.wkb_hex) for key, shape in [*bays, *lanes, *walks]), sorted(placements))


def review_changed_parking(before, after):
    if routing.Polygon is None:
        return {"reviewVersion": VERSION, "status": "not_checked", "certified": False,
                "reason": "Parking geometry review is unavailable."}
    previous = {z["zoneId"]: z for z in before.get("zones", [])}
    if max(len(d.get("zones", [])) * (len(d.get("floorMarkings", [])) + len(d.get("routes", []))
            + len(d.get("placements", []))) for d in (before, after)) > 500000:
        return {"reviewVersion": VERSION, "status": "not_checked", "certified": False,
                "reason": "Parking review exceeded its geometry scope. Review selected zones separately."}
    parking_marks = [[mark for mark in d.get("floorMarkings", []) if _is_bay(mark)] for d in (before, after)]
    selected = []
    for zone in after.get("zones", []):
        named = bool(re.search(r"\bparking\b|\bcar\s*park\b", zone.get("label", ""), re.I))
        old = previous.get(zone["zoneId"])
        was_named = old and re.search(r"\bparking\b|\bcar\s*park\b", old.get("label", ""), re.I)
        if not (named or was_named) and not any(
                candidate and _near_floor(mark["transform"]["position"]["y"], candidate)
                and _polygon(candidate).intersection(_mark_polygon(mark)).area > 1e-6
                for candidate, marks in zip((old, zone), parking_marks) for mark in marks):
            continue
        if old is None or _scope_snapshot(before, old) != _scope_snapshot(after, zone):
            selected.append(zone["zoneId"])
    return review_parking(after, selected) if selected else None
