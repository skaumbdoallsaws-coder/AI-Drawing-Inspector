"""A layout's place on the Earth: extensions.facilitySiteContext (site context, SC1).

- georeference: the WGS84 point that is the origin of the site's property frame
  (+X east, +Z north, metres; geo.py).
- buildingPose: where the layout's own frame sits in the property frame, and the
  compass bearing of its plan north. SC1 keeps it at the default, centred on the
  origin with plan north = true north; SC2 lets the user move and turn it.
- imagery: aerial images fetched for the site. An image's latitude/longitude box is
  the authority; its corners in the property frame are derived from the georeference
  each time, so moving the origin never misplaces an image.

Imagery is reference only: it is display context and never the source of a boundary.

- overlays: public reference map images over the photo's box (FEMA flood zones, USFWS
  wetlands, USGS contours, USDA soils), stored and placed exactly like imagery.
- layerChecks: what those services said about the building, lot and outdoor areas, with a key
  of the geometry it was asked about; a check made for other geometry is reported as stale.
- roads: road and railway centerlines around the site from the US Census TIGER/Line map
  (site_roads.py), stored in latitude/longitude; kind, label, property-frame line and length
  are derived, like image corners.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import re
from typing import Any

from .geo import box_corners, to_property

KEY = "facilitySiteContext"
IMAGE_PATH = re.compile(r"/api/facility-site-imagery/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/[a-f0-9]{64}\.jpg")
OVERLAY_PATH = re.compile(r"/api/facility-site-imagery/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/[a-f0-9]{64}\.png")
# Public reference layers (site_layers.py). US federal data: public domain.
OVERLAY_SOURCES = {
    "fema_nfhl": {"license": "public_domain", "attribution": "FEMA National Flood Hazard Layer (public domain)"},
    "usfws_nwi": {"license": "public_domain", "attribution": "USFWS National Wetlands Inventory (public domain)"},
    "usgs_3dep": {"license": "public_domain", "attribution": "USGS 3D Elevation Program (public domain)"},
    "usda_ssurgo": {"license": "public_domain",
                    "attribution": "USDA NRCS Soil Survey Geographic Database (public domain)"},
}
OVERLAY_LAYERS = {"flood": "fema_nfhl", "wetlands": "usfws_nwi", "contours": "usgs_3dep", "soils": "usda_ssurgo"}
PROPERTY_SOURCES = ("user_drawn", "user_coordinates", "survey_document", "county_parcel")
CHECK_SEVERITIES = ("high", "moderate", "info")
SOURCES = {
    "usgs_naip": {"license": "public_domain", "attribution": "USGS NAIP imagery (public domain)"},
    "usgs_imagery": {"license": "public_domain", "attribution": "USGS The National Map imagery (public domain)"},
    # Spring 2025, 1 ft, leaf-off; public domain under the Minnesota Government Data Practices Act.
    "mngeo_metro": {"license": "public_domain",
                    "attribution": "Metropolitan Council / MnGeo 2025 Twin Cities orthoimagery (public domain)"},
}
PLACED_BY = ("address", "coordinates", "map")
MAX_IMAGES = 4
AREA_KINDS = ("truck_court", "trailer_parking", "parking", "drive", "sidewalk", "landscape", "outdoor_storage",
              "existing_pavement")
# Reference outlines of what is there today (site_trace.py traces them from the photo). They are not part of
# the design: no setback, overlap or boundary findings, and they are not counted as paving.
REFERENCE_AREA_KINDS = ("existing_pavement",)
AREA_SURFACES = ("asphalt", "concrete", "grass")
# A drive or sidewalk may cross a setback where it passes through an entrance on that edge.
ENTRANCE_ACCESS = {"drive": ("trucks", "cars", "shared"), "sidewalk": ("trucks", "cars", "pedestrians", "shared")}
GATE_TOLERANCE_METERS = 0.05
MAX_OFFSET_METERS = 5000.0
# Roads (site_roads.py): US Census TIGER/Line, public domain. Kinds by MAF/TIGER feature class code.
ROAD_KINDS = {"S1100": "highway", "S1200": "arterial", "S1400": "local", "S1630": "ramp", "S1640": "service",
              "S1730": "alley", "S1740": "private", "S1780": "parking_aisle",
              "R1011": "railroad", "R1051": "railroad", "R1052": "railroad"}
ROAD_SOURCES = {"census_tiger": {"license": "public_domain",
                                 "attribution": "US Census Bureau TIGER/Line roads (public domain)"}}
MAX_ROADS = 80
MAX_ROAD_POINTS = 4000
_ROAD_FIELDS = {"roadId", "names", "mtfcc", "lonLat"}
_DERIVED_ROAD_FIELDS = {"kind", "label", "line", "lengthMeters"}
MAX_IMAGE_HALF_SIZE_METERS = 2000.0
_DERIVED_IMAGE_FIELDS = {"license", "attribution", "corners", "metersPerPixel"}
_IMAGE_FIELDS = {"imageId", "imagePath", "source", "captured", "geoBounds", "widthPixels", "heightPixels"}


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a number")
    if not low <= float(value) <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return float(value) + 0.0


def _plan_size(layout: Mapping[str, Any]) -> tuple[float, float]:
    plan = ((layout.get("extensions") or {}).get("facilityPlan") or {}) if isinstance(layout, Mapping) else {}
    return float(plan.get("widthMeters") or 40.0), float(plan.get("depthMeters") or 30.0)


def default_building_pose(layout: Mapping[str, Any]) -> dict[str, float]:
    """The building centred on the site origin, plan north on true north."""
    width, depth = _plan_size(layout)
    return {"x": -width / 2.0, "z": -depth / 2.0, "bearingDegrees": 0.0}


def _georeference(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"datum", "originLatitude", "originLongitude", "placedBy", "label"} \
            or not {"originLatitude", "originLongitude"} <= set(value):
        raise ValueError("georeference needs originLatitude and originLongitude")
    if value.get("datum", "WGS84") != "WGS84":
        raise ValueError("georeference datum must be WGS84")
    placed_by = value.get("placedBy", "coordinates")
    if placed_by not in PLACED_BY:
        raise ValueError("georeference placedBy must be address, coordinates or map")
    label = value.get("label", "")
    if not isinstance(label, str) or len(label.strip()) > 160 or re.search(r"[\x00-\x1f]", label):
        raise ValueError("georeference label must be at most 160 characters")
    return {
        "datum": "WGS84",
        "originLatitude": round(_number(value["originLatitude"], "originLatitude", -89.0, 89.0), 8),
        "originLongitude": round(_number(value["originLongitude"], "originLongitude", -180.0, 180.0), 8),
        "placedBy": placed_by,
        "label": label.strip(),
    }


def _building_pose(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != {"x", "z", "bearingDegrees"}:
        raise ValueError("buildingPose needs x, z and bearingDegrees")
    bearing = _number(value["bearingDegrees"], "buildingPose.bearingDegrees", -360.0, 360.0) % 360.0
    return {"x": _number(value["x"], "buildingPose.x", -MAX_OFFSET_METERS, MAX_OFFSET_METERS),
            "z": _number(value["z"], "buildingPose.z", -MAX_OFFSET_METERS, MAX_OFFSET_METERS),
            "bearingDegrees": bearing + 0.0}


def _image(value: Any, georeference: Mapping[str, Any], site_id: str | None,
           sources: Mapping[str, Any] = SOURCES, pattern: re.Pattern = IMAGE_PATH, extra: frozenset = frozenset()
           ) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not _IMAGE_FIELDS <= set(value) \
            or set(value) - _IMAGE_FIELDS - _DERIVED_IMAGE_FIELDS - extra:
        raise ValueError("Each site image needs imageId, imagePath, source, captured, geoBounds and pixel size")
    image_id, path = value["imageId"], value["imagePath"]
    if not isinstance(image_id, str) or not re.fullmatch(r"[a-f0-9]{64}", image_id):
        raise ValueError("Site image IDs are content digests")
    suffix = ".png" if pattern is OVERLAY_PATH else ".jpg"
    if not isinstance(path, str) or not pattern.fullmatch(path) or not path.endswith(f"/{image_id}{suffix}"):
        raise ValueError("Site images must reference a stored site image")
    if site_id is not None and path.split("/")[3] != site_id:
        raise ValueError("Site image belongs to another site")
    if not isinstance(value["source"], str) or value["source"] not in sources:
        raise ValueError("Site image source is not supported")
    captured = value["captured"]
    if captured is not None and (not isinstance(captured, str) or len(captured) > 40):
        raise ValueError("Site image capture date must be short text")
    bounds = value["geoBounds"]
    if not isinstance(bounds, Mapping) or set(bounds) != {"south", "west", "north", "east"}:
        raise ValueError("Site image geoBounds needs south, west, north and east")
    box = {
        "south": _number(bounds["south"], "geoBounds.south", -89.0, 89.0),
        "west": _number(bounds["west"], "geoBounds.west", -180.0, 180.0),
        "north": _number(bounds["north"], "geoBounds.north", -89.0, 89.0),
        "east": _number(bounds["east"], "geoBounds.east", -180.0, 180.0),
    }
    if box["north"] <= box["south"] or box["east"] <= box["west"]:
        raise ValueError("Site image geoBounds is empty")
    width = int(_number(value["widthPixels"], "widthPixels", 16, 4096))
    height = int(_number(value["heightPixels"], "heightPixels", 16, 4096))
    corners = box_corners(box, georeference["originLatitude"], georeference["originLongitude"])
    span_x = corners[1]["x"] - corners[0]["x"]
    span_z = corners[3]["z"] - corners[0]["z"]
    if max(abs(c["x"]) for c in corners) > MAX_OFFSET_METERS or max(abs(c["z"]) for c in corners) > MAX_OFFSET_METERS:
        raise ValueError("Site image lies too far from the site origin")
    if span_x / 2 > MAX_IMAGE_HALF_SIZE_METERS or span_z / 2 > MAX_IMAGE_HALF_SIZE_METERS:
        raise ValueError("Site image covers too large an area")
    return {
        "imageId": image_id, "imagePath": path, "source": value["source"], "captured": captured,
        "geoBounds": box, "widthPixels": width, "heightPixels": height,
        **sources[value["source"]],
        "corners": corners,
        "metersPerPixel": round(math.sqrt((span_x / width) * (span_z / height)), 4),
    }


def _overlay(value: Any, georeference: Mapping[str, Any], site_id: str | None) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("layer"), str) or value["layer"] not in OVERLAY_LAYERS:
        raise ValueError("Each overlay names a layer: flood, wetlands, contours or soils")
    if value.get("source") != OVERLAY_LAYERS[value["layer"]]:
        raise ValueError("Overlay source does not match its layer")
    detail = value.get("detail", "")
    if not isinstance(detail, str) or len(detail) > 80:
        raise ValueError("Overlay detail must be short text")
    image = _image({key: item for key, item in value.items() if key not in ("layer", "detail")},
                   georeference, site_id, OVERLAY_SOURCES, OVERLAY_PATH)
    return {"layer": value["layer"], "detail": detail.strip(), **image}


def _short(value: Any, name: str, limit: int = 160) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{name} must be text of at most {limit} characters")
    return value.strip()


def _layer_checks(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"geometryKey", "checkedAt", "results", "errors"}:
        raise ValueError("Layer checks need geometryKey, checkedAt, results and errors")
    key = value.get("geometryKey")
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{16}", key):
        raise ValueError("Layer checks need a geometry key")
    results, errors = value.get("results", []), value.get("errors", [])
    if not isinstance(results, list) or len(results) > 80 or not isinstance(errors, list) or len(errors) > 8:
        raise ValueError("Layer checks hold at most 80 results and 8 errors")
    clean = []
    for result in results:
        if not isinstance(result, Mapping) or not isinstance(result.get("layer"), str) \
                or result["layer"] not in OVERLAY_LAYERS:
            raise ValueError("Each layer check result names a layer")
        items = result.get("items", [])
        if not isinstance(items, list) or len(items) > 12:
            raise ValueError("A layer check result holds at most 12 items")
        metric = result.get("metric")
        if metric is not None:
            if not isinstance(metric, Mapping) or set(metric) - {"minElevationMeters", "maxElevationMeters", "fallMeters"}:
                raise ValueError("Ground metrics hold elevations and fall")
            metric = {name: _number(metric[name], name, -500.0, 9000.0) for name in metric}
        checked = []
        for item in items:
            if not isinstance(item, Mapping) or item.get("severity") not in CHECK_SEVERITIES:
                raise ValueError("Each layer check item needs a code, label and severity")
            checked.append({"code": _short(item.get("code"), "code", 40), "label": _short(item.get("label"), "label"),
                            "severity": item["severity"]})
        clean.append({"layer": result["layer"], "target": _short(result.get("target"), "target", 80),
                      "targetLabel": _short(result.get("targetLabel"), "targetLabel", 120),
                      "items": checked, "metric": metric})
    return {"geometryKey": key, "checkedAt": _short(value.get("checkedAt", ""), "checkedAt", 40),
            "results": clean,
            "errors": [{"layer": _short(e.get("layer"), "layer", 20), "message": _short(e.get("message"), "message")}
                       for e in errors if isinstance(e, Mapping)]}


def _roads(value: Any, georeference: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not {"source", "fetched", "geoBounds", "items"} <= set(value) \
            or set(value) - {"source", "fetched", "geoBounds", "items", "license", "attribution"}:
        raise ValueError("Roads need source, fetched, geoBounds and items")
    if not isinstance(value["source"], str) or value["source"] not in ROAD_SOURCES:
        raise ValueError("Road source is not supported")
    bounds = value["geoBounds"]
    if not isinstance(bounds, Mapping) or set(bounds) != {"south", "west", "north", "east"}:
        raise ValueError("Roads geoBounds needs south, west, north and east")
    box = {key: _number(bounds[key], f"geoBounds.{key}", -180.0 if key in ("west", "east") else -89.0,
                        180.0 if key in ("west", "east") else 89.0) for key in ("south", "west", "north", "east")}
    items = value["items"]
    if not isinstance(items, list) or len(items) > MAX_ROADS:
        raise ValueError(f"A site holds at most {MAX_ROADS} roads")
    origin = (georeference["originLatitude"], georeference["originLongitude"])
    clean, total, ids = [], 0, set()
    for item in items:
        if not isinstance(item, Mapping) or not _ROAD_FIELDS <= set(item) \
                or set(item) - _ROAD_FIELDS - _DERIVED_ROAD_FIELDS:
            raise ValueError("Each road needs roadId, names, mtfcc and lonLat")
        road_id = item["roadId"]
        if not isinstance(road_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", road_id) \
                or road_id in ids:
            raise ValueError("Each road needs a unique roadId")
        ids.add(road_id)
        if not isinstance(item["mtfcc"], str) or item["mtfcc"] not in ROAD_KINDS:
            raise ValueError("Road class is not supported")
        names = item["names"]
        if not isinstance(names, list) or len(names) > 4:
            raise ValueError("A road has at most four names")
        names = [_short(name, "Road name", 80) for name in names]
        points = item["lonLat"]
        if not isinstance(points, list) or not 2 <= len(points) <= 400:
            raise ValueError("A road line needs 2 to 400 points")
        total += len(points)
        coords, line = [], []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("Road points are [longitude, latitude]")
            longitude = _number(point[0], "road longitude", -180.0, 180.0)
            latitude = _number(point[1], "road latitude", -89.0, 89.0)
            x, z, _ = to_property(latitude, longitude, *origin)
            if abs(x) > MAX_OFFSET_METERS or abs(z) > MAX_OFFSET_METERS:
                raise ValueError("A road lies too far from the site origin")
            coords.append([round(longitude, 7), round(latitude, 7)])
            line.append({"x": round(x, 3) + 0.0, "z": round(z, 3) + 0.0})
        kind = ROAD_KINDS[item["mtfcc"]]
        label = (names[0] + (f" ({', '.join(names[1:])})" if len(names) > 1 else "") if names
                 else "Railroad" if kind == "railroad" else "Unnamed road")
        length = sum(math.dist((a["x"], a["z"]), (b["x"], b["z"])) for a, b in zip(line, line[1:]))
        clean.append({"roadId": road_id, "names": names, "mtfcc": item["mtfcc"], "lonLat": coords,
                      "kind": kind, "label": label, "line": line, "lengthMeters": round(length, 1)})
    if total > MAX_ROAD_POINTS:
        raise ValueError(f"Roads may contain at most {MAX_ROAD_POINTS} points in all")
    return {"source": value["source"], "fetched": _short(value["fetched"], "fetched", 40), "geoBounds": box,
            **ROAD_SOURCES[value["source"]], "items": clean}


def site_geometry_key(layout: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    """A short digest of the outlines the layer checks were asked about."""
    round_points = lambda points: [[round(p["x"], 2), round(p["z"], 2)] for p in points]
    payload = {"building": round_points(building_outline(layout, context)),
               "lot": round_points(context["property"]["boundary"]) if context.get("property") else None,
               "areas": [[area["areaId"], round_points(area["boundary"])] for area in context.get("areas", [])]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def normalize_site_context(value: Any, layout: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a site context and return it with its derived fields recomputed."""
    if not isinstance(value, Mapping) or value.get("version") != 1 or "georeference" not in value \
            or set(value) - {"version", "georeference", "buildingPose", "imagery", "property", "areas",
                             "overlays", "layerChecks", "roads", "routes", "references"}:
        raise ValueError("Site context needs version 1 and a georeference")
    georeference = _georeference(value["georeference"])
    pose = _building_pose(value["buildingPose"]) if "buildingPose" in value else default_building_pose(layout)
    imagery = value.get("imagery", [])
    if not isinstance(imagery, list) or len(imagery) > MAX_IMAGES:
        raise ValueError(f"A site holds at most {MAX_IMAGES} images")
    association = layout.get("association") if isinstance(layout, Mapping) else None
    site_id = association.get("siteId") if isinstance(association, Mapping) else None
    images = [_image(item, georeference, site_id) for item in imagery]
    if len({item["imageId"] for item in images}) != len(images):
        raise ValueError("A site image is listed twice")
    result = {"version": 1, "georeference": georeference, "buildingPose": pose, "imagery": images}
    if value.get("property") is not None:
        result["property"] = normalize_property(value["property"])
    if "areas" in value:
        areas = value["areas"]
        if not isinstance(areas, list) or len(areas) > 64:
            raise ValueError("A site holds at most 64 outdoor areas")
        result["areas"] = [normalize_site_area(area) for area in areas]
        if len({area["areaId"] for area in result["areas"]}) != len(areas):
            raise ValueError("Outdoor area IDs must be unique")
        if sum(len(area["boundary"]) for area in result["areas"]) > 2048:
            raise ValueError("Outdoor areas may contain at most 2048 total vertices")
    if "references" in value:
        references = value["references"]
        if not isinstance(references, list) or len(references) > MAX_REFERENCES:
            raise ValueError(f"A site holds at most {MAX_REFERENCES} reference points")
        result["references"] = [normalize_site_reference(item) for item in references]
        if len({item["referenceId"] for item in result["references"]}) != len(references):
            raise ValueError("Reference point IDs must be unique")
    if value.get("overlays"):
        overlays = value["overlays"]
        if not isinstance(overlays, list) or len(overlays) > len(OVERLAY_LAYERS):
            raise ValueError("A site holds at most one overlay per layer")
        result["overlays"] = [_overlay(item, georeference, site_id) for item in overlays]
        if len({item["layer"] for item in result["overlays"]}) != len(result["overlays"]):
            raise ValueError("A site holds at most one overlay per layer")
    if value.get("layerChecks") is not None:
        result["layerChecks"] = _layer_checks(value["layerChecks"])
    if value.get("roads") is not None:
        result["roads"] = _roads(value["roads"], georeference)
    # Derived like the road lines: each vehicle entrance's way to the main road (site_access.py).
    from .site_access import vehicle_routes
    routes = vehicle_routes(result)
    if routes:
        result["routes"] = routes
    return result


REFERENCE_KINDS = ("property_corner", "pavement_corner", "curb_corner", "pole", "road_intersection",
                   "rail_crossing", "other")
REFERENCE_SOURCES = ("county_parcel", "site_photo", "road_map", "survey", "user")
MAX_REFERENCES = 32


def normalize_site_reference(value: Any) -> dict[str, Any]:
    """A reference point: a feature a builder can find on site, in the property frame, with where its
    position came from and how far it can be trusted. `measured` is the same point measured independently
    (a survey, or another source at a point both show), which the fit check compares against."""
    if not isinstance(value, Mapping) or set(value) - {"referenceId", "label", "kind", "source", "x", "z",
                                                        "accuracyMeters", "measured"}:
        raise ValueError("Invalid reference point")
    identity, kind, source, label = value.get("referenceId"), value.get("kind"), value.get("source"), value.get("label", "")
    if not isinstance(identity, str) or not re.fullmatch(r"rp-[a-z0-9][a-z0-9-]{0,39}", identity):
        raise ValueError("A reference point needs a referenceId such as rp-1")
    if kind not in REFERENCE_KINDS:
        raise ValueError("Unsupported reference point kind")
    if source not in REFERENCE_SOURCES:
        raise ValueError("Unsupported reference point source")
    if not isinstance(label, str) or not label.strip() or len(label) > 120 or re.search(r"[\x00-\x1f]", label):
        raise ValueError("A reference point needs a label of 1 to 120 characters")

    def position(item, name, default_accuracy=None):
        accuracy = item.get("accuracyMeters", default_accuracy)
        return {"x": round(_number(item.get("x"), f"{name}.x", -MAX_OFFSET_METERS, MAX_OFFSET_METERS), 3),
                "z": round(_number(item.get("z"), f"{name}.z", -MAX_OFFSET_METERS, MAX_OFFSET_METERS), 3),
                "accuracyMeters": round(_number(accuracy, f"{name}.accuracyMeters", 0.005, 100), 3)}
    result = {"referenceId": identity, "label": label.strip(), "kind": kind, "source": source,
              **position(value, "reference")}
    measured = value.get("measured")
    if measured is not None:
        if not isinstance(measured, Mapping) or set(measured) - {"x", "z", "source", "accuracyMeters"} \
                or measured.get("source") not in REFERENCE_SOURCES:
            raise ValueError("A measured position needs x, z and its source")
        result["measured"] = {"source": measured["source"], **position(measured, "measured", 0.05)}
    return result


def normalize_site_area(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"areaId", "kind", "label", "boundary", "surface"}:
        raise ValueError("Invalid outdoor area")
    identity, kind, label = value.get("areaId"), value.get("kind"), value.get("label", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", identity):
        raise ValueError("Outdoor area needs a stable areaId")
    if kind not in AREA_KINDS:
        raise ValueError("Unsupported outdoor area kind")
    if not isinstance(label, str) or not label.strip() or len(label) > 120 or re.search(r"[\x00-\x1f]", label):
        raise ValueError("Outdoor area needs a label of 1 to 120 characters")
    surface = value.get("surface", "grass" if kind == "landscape" else "concrete" if kind == "sidewalk" else "asphalt")
    if surface not in AREA_SURFACES:
        raise ValueError("Outdoor surface must be asphalt, concrete or grass")
    return {"areaId": identity, "kind": kind, "label": label.strip(), "surface": surface,
            "boundary": _boundary(value.get("boundary"))}


def _boundary(value: Any) -> list[dict[str, float]]:
    from .canonical import canonicalize_polygon
    from .errors import FacilityLayoutError
    if not isinstance(value, list) or not 3 <= len(value) <= 128:
        raise ValueError("A property boundary needs 3 to 128 vertices")
    points = []
    for point in value:
        if not isinstance(point, Mapping) or set(point) != {"x", "z"}:
            raise ValueError("Boundary vertices need x and z")
        points.append({axis: round(_number(point[axis], f"boundary.{axis}",
                                          -MAX_OFFSET_METERS, MAX_OFFSET_METERS), 6) for axis in ("x", "z")})
    try:
        canonicalize_polygon(points)
    except FacilityLayoutError as exc:
        raise ValueError(str(exc)) from exc
    # Preserve vertex order: edge indices carry setbacks and entrance references.
    return points


def _edge_indices(value: Any, count: int, name: str) -> list[int]:
    if not isinstance(value, list) or any(type(i) is not int or not 0 <= i < count for i in value) \
            or len(set(value)) != len(value):
        raise ValueError(f"{name} must contain unique boundary edge indices")
    return sorted(value)


def normalize_property(value: Any) -> dict[str, Any]:
    from .spatial import point_segment_distance
    fields = {"boundary", "source", "sourceLabel", "setbacksMeters", "streetEdges", "rearEdges", "entrances"}
    if not isinstance(value, Mapping) or set(value) - fields or "boundary" not in value:
        raise ValueError("Property needs a boundary and supported property fields")
    boundary = _boundary(value["boundary"])
    source = value.get("source", "user_drawn")
    if source not in PROPERTY_SOURCES:
        raise ValueError("Property source must be user_drawn, user_coordinates, survey_document or county_parcel")
    label = value.get("sourceLabel", "")
    if not isinstance(label, str) or len(label) > 160 or re.search(r"[\x00-\x1f]", label):
        raise ValueError("Property source label must be short text")
    street = _edge_indices(value.get("streetEdges", []), len(boundary), "streetEdges")
    rear = _edge_indices(value.get("rearEdges", []), len(boundary), "rearEdges")
    if set(street) & set(rear):
        raise ValueError("An edge cannot be both street and rear")
    setbacks = value.get("setbacksMeters", {})
    if not isinstance(setbacks, Mapping) or set(setbacks) - {"street", "side", "rear"}:
        raise ValueError("Setbacks need street, side and rear distances")
    setbacks = {key: _number(setbacks.get(key, 0), f"setbacksMeters.{key}", 0, 500)
                for key in ("street", "side", "rear")}
    entrances = value.get("entrances", [])
    if not isinstance(entrances, list) or len(entrances) > 64:
        raise ValueError("Property holds at most 64 entrances")
    clean = []
    for entrance in entrances:
        if not isinstance(entrance, Mapping) or set(entrance) - {"entranceId", "edgeIndex", "x", "z", "use", "widthMeters"}:
            raise ValueError("Invalid property entrance")
        identity = entrance.get("entranceId")
        edge = entrance.get("edgeIndex")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", identity):
            raise ValueError("Entrance needs a stable entranceId")
        if type(edge) is not int or not 0 <= edge < len(boundary):
            raise ValueError("Entrance needs a valid edgeIndex")
        use = entrance.get("use", "shared")
        if use not in ("trucks", "cars", "pedestrians", "shared"):
            raise ValueError("Entrance use must be trucks, cars, pedestrians or shared")
        point = {axis: _number(entrance.get(axis), f"entrance.{axis}", -MAX_OFFSET_METERS, MAX_OFFSET_METERS)
                 for axis in ("x", "z")}
        a, b = boundary[edge], boundary[(edge + 1) % len(boundary)]
        if point_segment_distance((point["x"], point["z"]), (a["x"], a["z"]), (b["x"], b["z"])) > 0.01:
            raise ValueError("Entrance must lie on its referenced property edge")
        width = _number(entrance.get("widthMeters", 4), "entrance.widthMeters", 0.5, 50)
        if min(math.hypot(point["x"] - q["x"], point["z"] - q["z"]) for q in (a, b)) + 0.01 < width / 2:
            raise ValueError("Entrance width must fit within its edge")
        clean.append({"entranceId": identity, "edgeIndex": edge, **point, "use": use, "widthMeters": width})
    if len({item["entranceId"] for item in clean}) != len(clean):
        raise ValueError("Entrance IDs must be unique")
    return {"boundary": boundary, "source": source, "sourceLabel": label.strip(), "setbacksMeters": setbacks,
            "streetEdges": street, "rearEdges": rear, "entrances": clean}


def building_outline(layout: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, float]]:
    pose = context["buildingPose"]
    angle = math.radians(pose["bearingDegrees"])
    c, s = math.cos(angle), math.sin(angle)
    width, depth = _plan_size(layout)
    return [{"x": pose["x"] + x * c + z * s, "z": pose["z"] - x * s + z * c}
            for x, z in ((0, 0), (width, 0), (width, depth), (0, depth))]


LAYER_TITLES = {"flood": "FEMA flood map", "wetlands": "USFWS wetlands map", "contours": "USGS elevation",
                "soils": "USDA soil survey"}
LAYER_CODES = {"flood": "site_flood_zone", "wetlands": "site_wetland", "contours": "site_ground_fall",
               "soils": "site_soil"}


def _layer_check_findings(layout: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks = context.get("layerChecks")
    if not checks:
        return []
    if checks["geometryKey"] != site_geometry_key(layout, context):
        return [{"code": "site_layer_checks_stale", "severity": "unverified",
                 "message": "Flood, wetland, soil and ground checks were made for an earlier layout. "
                            "Run them again in the Site tab's Layers section."}]
    findings = []
    for result in checks["results"]:
        for item in result["items"]:
            if item["severity"] == "info":
                continue
            findings.append({"code": LAYER_CODES[result["layer"]],
                             "severity": "warning" if item["severity"] == "high" else "info",
                             "target": result["target"],
                             "message": f'{result["targetLabel"]}: {item["label"]} ({LAYER_TITLES[result["layer"]]}).'})
    for error in checks["errors"]:
        findings.append({"code": "site_layer_check_failed", "severity": "unverified",
                         "message": f'{error["message"]} The {error["layer"]} check is incomplete.'})
    return findings


def _edge_distance(polygon, a, b):
    from shapely.geometry import LineString, Polygon
    return Polygon(polygon).distance(LineString([a, b]))


def _entrance_gates(kind, entrances, index, boundary, depth, counterclockwise):
    """The strip through each usable entrance on one edge, as wide as the entrance and as deep as the setback."""
    from shapely.geometry import Polygon
    uses = ENTRANCE_ACCESS.get(kind, ())
    a, b = boundary[index], boundary[(index + 1) % len(boundary)]
    length = math.dist(a, b)
    ux, uz = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    nx, nz = (-uz, ux) if counterclockwise else (uz, -ux)  # into the lot
    near, far = -GATE_TOLERANCE_METERS, depth + GATE_TOLERANCE_METERS
    gates = []
    for entrance in entrances:
        if entrance["edgeIndex"] != index or entrance["use"] not in uses:
            continue
        half = entrance["widthMeters"] / 2 + GATE_TOLERANCE_METERS
        x, z = entrance["x"], entrance["z"]
        gates.append((entrance["entranceId"], Polygon([
            (x - ux * half + nx * near, z - uz * half + nz * near), (x + ux * half + nx * near, z + uz * half + nz * near),
            (x + ux * half + nx * far, z + uz * half + nz * far), (x - ux * half + nx * far, z - uz * half + nz * far)])))
    return gates


def analyze_site_context(layout: Mapping[str, Any]) -> dict[str, Any]:
    """Conceptual geometry findings only; never a legal or regulatory clearance."""
    from .spatial import polygon_area, polygon_contains_polygon
    raw = (layout.get("extensions") or {}).get(KEY)
    if raw is None:
        return {"available": False, "findings": [], "metrics": None}
    context = normalize_site_context(raw, layout)
    outline = building_outline(layout, context)
    footprint = [(p["x"], p["z"]) for p in outline]
    result = {"available": True, "buildingFootprint": outline, "findings": [], "metrics": None,
              "caveat": "Conceptual site geometry. User-supplied boundary and setbacks; not a survey or compliance review."}
    result["findings"].extend(_layer_check_findings(layout, context))
    prop = context.get("property")
    if not prop:
        result["findings"].append({"code": "site_property_missing", "severity": "unverified",
                                   "message": "No user-supplied property boundary."})
        return result
    boundary = [(p["x"], p["z"]) for p in prop["boundary"]]
    area = abs(polygon_area(boundary))
    building_area = abs(polygon_area(footprint))
    contained = polygon_contains_polygon(boundary, footprint)
    if not contained:
        result["findings"].append({"code": "site_building_outside_property", "severity": "warning",
                                   "message": "Building footprint extends outside the property boundary."})
    edges = []
    for index, a in enumerate(boundary):
        b = boundary[(index + 1) % len(boundary)]
        kind = "street" if index in prop["streetEdges"] else "rear" if index in prop["rearEdges"] else "side"
        required = prop["setbacksMeters"][kind]
        distance = _edge_distance(footprint, a, b)
        edges.append({"edgeIndex": index, "kind": kind, "lengthMeters": math.dist(a, b),
                      "bearingDegrees": math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360,
                      "buildingDistanceMeters": distance, "requiredSetbackMeters": required})
        if distance + 1e-6 < required:
            result["findings"].append({"code": "site_setback_violation", "severity": "warning", "edgeIndex": index,
                "distanceMeters": distance, "requiredMeters": required,
                "message": f"Edge {index + 1} ({kind}): building is {distance:.2f} m away; requested setback is {required:g} m."})
    result["metrics"] = {"lotAreaSquareMeters": area, "lotAreaAcres": area / 4046.8564224,
                         "buildingAreaSquareMeters": building_area, "buildingCoveragePercent": building_area / area * 100,
                         "buildingInsideProperty": contained, "edges": edges}
    from shapely.geometry import LinearRing, LineString, Polygon
    from shapely.ops import unary_union
    lot = Polygon(boundary)
    building = Polygon(footprint)
    counterclockwise = LinearRing(boundary).is_ccw
    crossings = []
    every = [(item, Polygon([(p["x"], p["z"]) for p in item["boundary"]])) for item in context.get("areas", [])]
    shapes = [(item, shape) for item, shape in every if item["kind"] not in REFERENCE_AREA_KINDS]
    for index, (item, shape) in enumerate(shapes):
        def finding(code, message, **extra):
            result["findings"].append({"code": code, "severity": "warning", "areaId": item["areaId"],
                                       "message": message, **extra})
        if not lot.buffer(1e-6).covers(shape):
            finding("site_area_outside_property", f'{item["label"]} extends outside the property.')
        if shape.intersection(building).area > 1e-6:
            finding("site_area_overlaps_building", f'{item["label"]} overlaps the building footprint.')
        for other, other_shape in shapes[:index]:
            if shape.intersection(other_shape).area > 1e-6:
                finding("site_area_overlap", f'{item["label"]} overlaps {other["label"]}.', otherAreaId=other["areaId"])
        for edge in edges:
            i, required = edge["edgeIndex"], edge["requiredSetbackMeters"]
            line = LineString([boundary[i], boundary[(i + 1) % len(boundary)]])
            distance = shape.distance(line)
            if distance + 1e-6 >= required:
                continue
            gates = [(identity, gate) for identity, gate in _entrance_gates(
                item["kind"], prop["entrances"], i, boundary, required, counterclockwise)
                if shape.intersection(gate).area > 1e-6]
            message = f'{item["label"]}: Edge {i + 1} requested setback is not met.'
            if gates:
                # Only the part outside the entrance strips has to respect the setback.
                beyond = shape.difference(unary_union([gate for _, gate in gates]))
                distance = beyond.distance(line) if not beyond.is_empty else math.inf
                if distance + 1e-6 >= required:
                    crossings.append({"areaId": item["areaId"], "edgeIndex": i,
                                      "entranceIds": [identity for identity, _ in gates]})
                    continue
                message = f'{item["label"]}: Edge {i + 1} requested setback is not met beyond the entrance width.'
            finding("site_area_setback_violation", message, edgeIndex=i, distanceMeters=distance, requiredMeters=required)
    from .site_access import entrance_findings
    result["findings"].extend(entrance_findings(context))
    paved = unary_union([shape for item, shape in shapes if item["surface"] != "grass"])
    result["metrics"].update({"pavedAreaSquareMeters": paved.area, "entranceCrossings": crossings,
        "pavedAreaWithinPropertySquareMeters": paved.intersection(lot).area,
        "areas": [{"areaId": item["areaId"], "label": item["label"], "kind": item["kind"],
                   "surface": item["surface"], "areaSquareMeters": shape.area} for item, shape in every]})
    return result


def property_point(site_context: Mapping[str, Any], latitude: float, longitude: float) -> dict[str, float]:
    """A WGS84 position in this site's property frame."""
    reference = site_context["georeference"]
    x, z, _ = to_property(latitude, longitude, reference["originLatitude"], reference["originLongitude"])
    return {"x": x, "z": z}
