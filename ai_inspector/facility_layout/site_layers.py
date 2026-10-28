"""Public reference layers for the Site tab: parcels, flood zones, wetlands, contours and soils.

Every source is free public data that may be stored with a layout:
- parcels: MnGeo's compilation of Minnesota counties that publish open parcel data. Only the
  outline, PIN, address and acreage are requested; owner and tax fields never are;
- flood zones: FEMA National Flood Hazard Layer; wetlands: USFWS National Wetlands Inventory;
- contours and ground elevation: USGS 3D Elevation Program; soils: USDA NRCS Soil Data Access.

Display layers are map images of the site photo's box, drawn by each agency's own service. The
checks send the building, lot and outdoor-area outlines to each service and ask which zones they
touch, so no river- or floodplain-sized geometry is ever downloaded. Reference data only: not a
survey, permit or compliance review.
"""
from __future__ import annotations

import datetime
from io import BytesIO
import json
import math
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, UnidentifiedImageError

from .errors import FacilityLayoutError
from .geo import from_property, to_property
from . import site_imagery

PARCEL_QUERY = ("https://enterprise.gisdata.mn.gov/aghost/rest/services/us_mn_state_mngeo/"
                "plan_parcels_open/MapServer/1/query")
PARCEL_FIELDS = "state_pin,county_pin,co_name,ctu_name,anumber,st_pre_dir,st_name,st_pos_typ,lot,block,plat_name,acres_poly"
MINNESOTA = {"west": -97.25, "east": -89.48, "south": 43.49, "north": 49.39}
MAX_PARCEL_VERTICES = 120

FEMA_MAP = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
FEMA_ZONES_LAYER = 28
FEMA_SHOWN = "SFHA_TF = 'T' OR ZONE_SUBTY LIKE '%0.2 PCT%'"  # leave out "area of minimal flood hazard"
NWI_MAP = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer"
DEM_IMAGE = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
SOIL_WMS = "https://SDMDataAccess.sc.egov.usda.gov/Spatial/SDM.wms"
SOIL_SQL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"

LAYERS = {
    "flood": {"title": "Flood zones", "source": "fema_nfhl",
              "attribution": "FEMA National Flood Hazard Layer (public domain)"},
    "wetlands": {"title": "Wetlands", "source": "usfws_nwi",
                 "attribution": "USFWS National Wetlands Inventory (public domain)"},
    "contours": {"title": "Contours", "source": "usgs_3dep",
                 "attribution": "USGS 3D Elevation Program (public domain)"},
    "soils": {"title": "Soils", "source": "usda_ssurgo",
              "attribution": "USDA NRCS Soil Survey Geographic Database (public domain)"},
}
MAX_OVERLAY_SIDE = 2048
CONTOUR_COLOR = (255, 214, 120)
MAX_CHECK_TARGETS = 14
HIGH_FLOOD_ZONES = {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE"}


def _today() -> str:
    return datetime.date.today().isoformat()


def _json(url: str, params: dict, attempts: int = 2) -> dict:
    """GET a JSON answer, retrying once; an ArcGIS error document counts as a failure."""
    last = None
    for _attempt in range(attempts):
        try:
            content, _ = site_imagery._get(url, params)
            answer = json.loads(content)
            if isinstance(answer, dict) and "error" in answer:
                raise ValueError(str(answer["error"].get("message") or answer["error"])[:200])
            return answer
        except Exception as exc:  # network, HTTP or a service error: retry once
            last = exc
    raise last  # type: ignore[misc]


# Parcels ------------------------------------------------------------------------------------------

def _simplified_ring(points: list[tuple[float, float]]) -> tuple[list[tuple[float, float]], float]:
    from shapely.geometry import Polygon
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
        if polygon.geom_type != "Polygon":
            polygon = max(polygon.geoms, key=lambda part: part.area)
    tolerance = 0.0
    shape = polygon
    while len(shape.exterior.coords) - 1 > MAX_PARCEL_VERTICES:
        tolerance = 0.05 if tolerance == 0 else tolerance * 1.5
        shape = polygon.simplify(tolerance, preserve_topology=True)
    return list(shape.exterior.coords)[:-1], tolerance


def fetch_parcel(latitude: float, longitude: float, origin_latitude: float, origin_longitude: float) -> dict:
    """The open-data county parcel under a point, as a property boundary in the site's frame."""
    from shapely.geometry import Point, Polygon
    if not (MINNESOTA["south"] <= latitude <= MINNESOTA["north"] and MINNESOTA["west"] <= longitude <= MINNESOTA["east"]):
        raise FacilityLayoutError("site_parcel_not_covered",
                                  "Parcel lookup covers Minnesota counties that publish open parcel data. "
                                  "Draw the boundary here instead.", status_code=422)
    try:
        answer = _json(PARCEL_QUERY, {
            "geometry": f"{longitude:.8f},{latitude:.8f}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": PARCEL_FIELDS,
            "returnGeometry": "true", "outSR": 4326, "f": "json"})
    except Exception as exc:
        raise FacilityLayoutError("site_parcel_unavailable", "The parcel service did not answer. Try again in a minute.",
                                  status_code=502, details={"reason": str(exc)[:160]}) from exc
    features = [f for f in answer.get("features") or [] if (f.get("geometry") or {}).get("rings")]
    if not features:
        raise FacilityLayoutError("site_parcel_not_found",
                                  "No open-data parcel covers that point. Click inside a lot, or draw the boundary.",
                                  status_code=404)
    feature = features[0]
    point = Point(longitude, latitude)
    rings = [ring for ring in feature["geometry"]["rings"] if len(ring) >= 4]
    ring = next((r for r in rings if Polygon(r).contains(point)), max(rings, key=lambda r: Polygon(r).area))
    local = []
    for lon, lat in ring:
        x, z, _y = to_property(float(lat), float(lon), origin_latitude, origin_longitude)
        local.append((x, z))
    simple, tolerance = _simplified_ring(local)
    attrs = feature.get("attributes") or {}
    text = lambda key: str(attrs.get(key) or "").strip()
    street = " ".join(part for part in (text("anumber"), text("st_pre_dir"), text("st_name"), text("st_pos_typ")) if part)
    legal = ", ".join(part for part in (f"Lot {text('lot')}" if text("lot") else "",
                                        f"Block {text('block')}" if text("block") else "", text("plat_name")) if part)
    area = abs(Polygon(simple).area)
    return {
        "boundary": [{"x": round(x, 3), "z": round(z, 3)} for x, z in simple],
        "parcelId": text("state_pin") or text("county_pin"), "county": text("co_name"), "city": text("ctu_name"),
        "address": ", ".join(part for part in (street, text("ctu_name")) if part), "legal": legal,
        "acres": attrs.get("acres_poly"), "areaSquareMeters": round(area, 1),
        "simplified": {"fromVertices": len(ring) - 1, "toVertices": len(simple), "toleranceMeters": round(tolerance, 3)},
        "source": "mngeo_open_parcels",
        "attribution": "MnGeo: parcels compiled from Minnesota open-data counties (county tax maps, not surveys)",
    }


# Display images -----------------------------------------------------------------------------------

def _clean_png(content: bytes, width: int, height: int, recolor: tuple[int, int, int] | None = None) -> bytes:
    """Accept only a PNG of the requested size; re-encode it as RGBA without metadata."""
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format != "PNG" or source.size != (width, height):
                raise ValueError("unexpected image")
            picture = source.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("The service did not return an image.") from exc
    if recolor is not None:  # black contour lines vanish on an aerial photo: draw them light
        alpha = picture.getchannel("A")
        picture = Image.new("RGBA", picture.size, recolor + (255,))
        picture.putalpha(alpha)
    output = BytesIO()
    picture.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _contour_interval(bounds: dict) -> int:
    half = (bounds["north"] - bounds["south"]) * 111_132 / 2
    return 2 if half <= 160 else 5 if half <= 320 else 10


def fetch_overlay(layer: str, bounds: dict, width: int, height: int) -> tuple[bytes, dict, str]:
    """A transparent map image of one layer for a latitude/longitude box: (png, box drawn, detail)."""
    if layer not in LAYERS:
        raise ValueError("Unknown layer")
    width, height = min(width, MAX_OVERLAY_SIDE), min(height, MAX_OVERLAY_SIDE)
    bbox = f"{bounds['west']:.8f},{bounds['south']:.8f},{bounds['east']:.8f},{bounds['north']:.8f}"
    errors = []
    for _attempt in range(2):
        try:
            if layer == "soils":  # WMS draws exactly the box asked for
                content, content_type = site_imagery._get(SOIL_WMS, {
                    "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": "mapunitpoly", "STYLES": "",
                    "SRS": "EPSG:4326", "BBOX": bbox, "WIDTH": width, "HEIGHT": height,
                    "FORMAT": "image/png", "TRANSPARENT": "true"})
                if not content_type.startswith("image/"):
                    raise ValueError(f"answered {content_type or 'without a type'}")
                return _clean_png(content, width, height), dict(bounds), "Soil map units (SSURGO)"
            common = {"bbox": bbox, "bboxSR": 4326, "imageSR": 4326, "size": f"{width},{height}", "f": "json"}
            if layer == "contours":
                interval = _contour_interval(bounds)
                url = f"{DEM_IMAGE}/exportImage"
                params = {**common, "format": "png", "adjustAspectRatio": "false",
                          "renderingRule": json.dumps({"rasterFunction": f"Preset {interval}ft Contour Interval"})}
                detail = f"{interval} ft contours"
            else:
                url = f"{FEMA_MAP if layer == 'flood' else NWI_MAP}/export"
                params = {**common, "format": "png32", "transparent": "true",
                          "layers": f"show:{FEMA_ZONES_LAYER if layer == 'flood' else 0}"}
                if layer == "flood":
                    params["layerDefs"] = json.dumps({str(FEMA_ZONES_LAYER): FEMA_SHOWN})
                detail = "FEMA flood hazard zones" if layer == "flood" else "NWI wetlands and deepwater"
            answer, _ = site_imagery._get(url, params)
            href, drawn = site_imagery._drawn(answer, url, bounds, width, height)
            content, _ = site_imagery._get(href)
            png = _clean_png(content, width, height, CONTOUR_COLOR if layer == "contours" else None)
            return png, drawn, detail
        except Exception as exc:  # network, HTTP, a service error or decoding: try once more
            errors.append(str(exc))
    raise FacilityLayoutError("site_layer_unavailable",
                              f"The {LAYERS[layer]['title'].lower()} service did not answer. Try again in a minute.",
                              status_code=502, details={"attempts": [e[:160] for e in errors]})


# Checks -------------------------------------------------------------------------------------------

def _esri_polygon(ring: list[list[float]]) -> str:
    return json.dumps({"rings": [ring], "spatialReference": {"wkid": 4326}})


def _query_zones(map_url: str, layer_id: int, ring: list[list[float]], fields: str) -> list[dict]:
    answer = _json(f"{map_url}/{layer_id}/query", {
        "geometry": _esri_polygon(ring), "geometryType": "esriGeometryPolygon", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": fields, "returnGeometry": "false", "f": "json"})
    return [feature.get("attributes") or {} for feature in answer.get("features") or []]


def _flood_items(ring):
    items = {}
    for attrs in _query_zones(FEMA_MAP, FEMA_ZONES_LAYER, ring, "FLD_ZONE,ZONE_SUBTY,SFHA_TF"):
        zone = str(attrs.get("FLD_ZONE") or "").strip()
        subtype = str(attrs.get("ZONE_SUBTY") or "").upper()
        if zone in HIGH_FLOOD_ZONES or attrs.get("SFHA_TF") == "T":
            items[zone] = {"code": zone, "label": f"1% annual chance flood area (Zone {zone})", "severity": "high"}
        elif "0.2 PCT" in subtype:
            items["X 0.2%"] = {"code": "X 0.2%", "label": "0.2% annual chance flood area (shaded Zone X)",
                               "severity": "moderate"}
        elif zone == "D":
            items["D"] = {"code": "D", "label": "Undetermined flood hazard (Zone D)", "severity": "moderate"}
        elif zone == "OPEN WATER":
            items["OPEN WATER"] = {"code": "OPEN WATER", "label": "Open water", "severity": "high"}
    return list(items.values())


def _wetland_items(ring):
    items = {}
    for attrs in _query_zones(NWI_MAP, 0, ring, "ATTRIBUTE,WETLAND_TYPE"):
        code = str(attrs.get("ATTRIBUTE") or "").strip()
        label = str(attrs.get("WETLAND_TYPE") or "Wetland").strip()
        items[code] = {"code": code[:40], "label": f"{label} ({code})"[:160], "severity": "high"}
    return list(items.values())


def _soil_items(ring):
    wkt = "polygon((" + ", ".join(f"{lon:.7f} {lat:.7f}" for lon, lat in ring) + "))"
    query = ("SELECT mukey, musym, muname FROM mapunit WHERE mukey IN "
             f"(SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}'))")
    last = None
    for _attempt in range(2):
        try:
            request = site_imagery.urllib.request.Request(
                SOIL_SQL, data=json.dumps({"query": query, "format": "JSON"}).encode(),
                headers={"User-Agent": site_imagery.USER_AGENT, "Content-Type": "application/json"})
            with site_imagery._urlopen(request, timeout=site_imagery.TIMEOUT_SECONDS) as response:
                rows = (json.loads(response.read(site_imagery.MAX_IMAGE_BYTES)) or {}).get("Table") or []
            return [{"code": str(row[1])[:40], "label": str(row[2])[:160], "severity": "info"} for row in rows[:12]]
        except Exception as exc:
            last = exc
    raise last  # type: ignore[misc]


def _ground(ring):
    """Ground elevation across a polygon from a small USGS 3DEP grid: min, max and fall."""
    import numpy as np
    from shapely.geometry import Point, Polygon
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    west, east, south, north = min(lons), max(lons), min(lats), max(lats)
    size = 48
    content, content_type = site_imagery._get(f"{DEM_IMAGE}/exportImage", {
        "bbox": f"{west:.8f},{south:.8f},{east:.8f},{north:.8f}", "bboxSR": 4326, "imageSR": 4326,
        "size": f"{size},{size}", "format": "tiff", "pixelType": "F32", "adjustAspectRatio": "false",
        "interpolation": "RSP_BilinearInterpolation", "f": "image"})
    if not content_type.startswith("image/"):
        raise ValueError(f"answered {content_type or 'without a type'}")
    with Image.open(BytesIO(content)) as grid:
        values = np.asarray(grid, dtype=float)
    shape = Polygon(ring)
    inside = [values[r, c] for r in range(size) for c in range(size)
              if shape.contains(Point(west + (c + 0.5) * (east - west) / size, north - (r + 0.5) * (north - south) / size))]
    inside = [v for v in inside if math.isfinite(v) and -500 < v < 9000]
    if not inside:
        return None
    low, high = min(inside), max(inside)
    return {"minElevationMeters": round(low, 2), "maxElevationMeters": round(high, 2), "fallMeters": round(high - low, 2)}


def check_layers(targets: list[dict], layers: list[str]) -> dict:
    """Ask each service which zones each target outline touches; failures are reported per layer."""
    if not targets or len(targets) > MAX_CHECK_TARGETS:
        raise ValueError(f"Check 1 to {MAX_CHECK_TARGETS} outlines at a time")
    jobs = [(layer, target) for layer in layers for target in targets
            if not (layer == "contours" and target["target"] == "lot")]

    def run(job):
        layer, target = job
        ring = target["ring"]
        if layer == "flood":
            return job, _flood_items(ring), None
        if layer == "wetlands":
            return job, _wetland_items(ring), None
        if layer == "soils":
            return job, _soil_items(ring), None
        ground = _ground(ring)
        items = []
        if ground and target["target"] == "building" and ground["fallMeters"] >= 1.0:
            items.append({"code": "fall", "label": f"Ground falls {ground['fallMeters']:.1f} m across the footprint",
                          "severity": "moderate"})
        return job, items, ground

    results, errors = [], {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in [pool.submit(lambda job=job: _safe(run, job)) for job in jobs]:
            job, items, metric, error = future.result()
            layer, target = job
            if error:
                errors.setdefault(layer, error)
                continue
            results.append({"layer": layer, "target": target["target"], "targetLabel": target["label"],
                            "items": items[:12], "metric": metric})
    return {"checkedAt": _today(), "results": results,
            "errors": [{"layer": layer, "message": f"The {LAYERS[layer]['title'].lower()} service did not answer."}
                       for layer in sorted(errors)]}


def _safe(run, job):
    try:
        found, items, metric = run(job)
        return found, items, metric, None
    except Exception as exc:  # one service down must not hide the others
        return job, [], None, str(exc)[:160]


def check_targets(layout: dict, context: dict) -> list[dict]:
    """The building, lot and outdoor-area outlines, in latitude/longitude, for the checks."""
    from .site_context import building_outline
    reference = context["georeference"]

    def ring(points):
        coords = []
        for p in points:
            lat, lon, _h = from_property(p["x"], p["z"], reference["originLatitude"], reference["originLongitude"])
            coords.append([round(lon, 8), round(lat, 8)])
        return coords + [coords[0]]

    targets = [{"target": "building", "label": "Building", "ring": ring(building_outline(layout, context))}]
    if context.get("property"):
        targets.append({"target": "lot", "label": "Lot", "ring": ring(context["property"]["boundary"])})
    for area in (context.get("areas") or [])[:MAX_CHECK_TARGETS - len(targets)]:
        targets.append({"target": area["areaId"], "label": area["label"], "ring": ring(area["boundary"])})
    return targets
