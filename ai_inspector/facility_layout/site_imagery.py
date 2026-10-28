"""Aerial imagery and address lookup for the Site tab (site context, SC1).

The server, not the browser, talks to the public services, so no key or third-party
request ever runs in the renderer:
- USGS The National Map NAIP imagery (public domain; about 0.6 m per pixel, US only),
  with the USGS Imagery basemap as a fallback when NAIP does not answer;
- the US Census geocoder (public, US addresses);
- the USGS Imagery basemap's cached tiles for the globe flight to a new address, relayed
  and kept a short while in memory, never on disk.
Images are stored once per site, content-addressed like decal images, so a placed
layout keeps working offline. Imagery is display context, never a boundary source.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
import datetime
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .authorization import require_facility_action
from .decal_images import scope_directory
from .errors import FacilityLayoutError
from .geo import geographic_box
from .repository import _native_fs_path

NAIP_EXPORT = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"
NAIP_IDENTIFY = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/identify"
BASEMAP_EXPORT = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
# MnGeo's image service: the Metropolitan Council's spring 2025 orthophoto of the 7-county Twin
# Cities metro, 1 ft (0.3 m), leaf-off, public domain (Minnesota Government Data Practices Act).
MNGEO_WMS = "https://imageserver.gisdata.mn.gov/cgi-bin/wms"
MNGEO_METRO_LAYER = "met25"
MNGEO_METRO_CAPTURED = "2025-04"
MNGEO_METRO_COVERAGE = {"west": -94.08, "east": -92.68, "south": 44.43, "north": 45.44}
HIGH_RES_METERS_PER_PIXEL = 0.3
PHOTO_SOURCES = ("standard", "mngeo_metro")
USER_AGENT = "InspectorPro facility site context (local)"
TIMEOUT_SECONDS = 30
METERS_PER_PIXEL = 0.5
MAX_SIDE_PIXELS = 4096
MIN_HALF_SIZE_METERS = 50.0
MAX_HALF_SIZE_METERS = 1000.0
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# The globe flight's imagery: Web Mercator tiles of the USGS Imagery basemap (public domain;
# NASA Blue Marble and Landsat at small scales, NAIP close in). They show to zoom 16.
GLOBE_TILES = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile"
GLOBE_MAX_ZOOM = 16
GLOBE_TILE_BYTES = 2 * 1024 * 1024
GLOBE_TIMEOUT_SECONDS = 10
# The dive asks for tiles faster than a browser's six connections to this server can relay
# them, so the server fetches each place's tile column in parallel as the flight starts.
GLOBE_WORKERS = 16
GLOBE_PREFETCH_WAIT_SECONDS = 6
GLOBE_MEMORY_TILES = 800
_globe_pool = ThreadPoolExecutor(max_workers=GLOBE_WORKERS, thread_name_prefix="site-globe-tile")
_globe_lock = threading.Lock()
_globe_tiles: OrderedDict = OrderedDict()
_globe_pending: dict = {}

# Tests replace this; everything that leaves the machine goes through it.
_urlopen = urllib.request.urlopen


def _get(url: str, params: dict | None = None) -> tuple[bytes, str]:
    query = "?" + urllib.parse.urlencode(params) if params else ""
    request = urllib.request.Request(url + query, headers={"User-Agent": USER_AGENT})
    with _urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        content = response.read(MAX_IMAGE_BYTES + 1)
        return content, str(response.headers.get("Content-Type", "")).split(";")[0].strip().lower()


def plan_request(latitude: float, longitude: float, half_size: float,
                 meters_per_pixel: float = METERS_PER_PIXEL) -> dict:
    """The box and pixel size for an image centred on a point, about meters_per_pixel per pixel."""
    if not (-89.0 <= latitude <= 89.0 and -180.0 <= longitude <= 180.0):
        raise ValueError("Latitude must be within 89 degrees and longitude within 180.")
    if not MIN_HALF_SIZE_METERS <= half_size <= MAX_HALF_SIZE_METERS:
        raise ValueError(f"The area must be {2 * MIN_HALF_SIZE_METERS:g} to {2 * MAX_HALF_SIZE_METERS:g} m across.")
    bounds = geographic_box(latitude, longitude, half_size, half_size)
    side = min(MAX_SIDE_PIXELS, max(64, int(math.ceil(2 * half_size / meters_per_pixel))))
    return {"bounds": bounds, "widthPixels": side, "heightPixels": side}


def _export_params(bounds: dict, width: int, height: int, exact: bool) -> dict:
    params = {"bbox": f"{bounds['west']:.8f},{bounds['south']:.8f},{bounds['east']:.8f},{bounds['north']:.8f}",
              "bboxSR": 4326, "imageSR": 4326, "size": f"{width},{height}", "format": "jpg", "f": "json"}
    if exact:
        # By default the image server widens the box until its pixels are square in degrees, so
        # the picture would cover about 1.4 times the ground asked for north-south (at 45 N).
        params["adjustAspectRatio"] = "false"
    return params


def _drawn(content: bytes, service_url: str, bounds: dict, width: int, height: int) -> tuple[str, dict]:
    """The picture's link and the latitude/longitude box it really covers, from the JSON answer.

    The box is read back, never assumed: a service that ignores adjustAspectRatio (the basemap
    has no such option) still reports the box it drew, and that box is what the photo shows.
    """
    answer = json.loads(content)
    link = urllib.parse.urlsplit(str(answer.get("href") or ""))
    if link.scheme != "https" or link.netloc != urllib.parse.urlsplit(service_url).netloc:
        raise ValueError("answered without a picture on its own host")
    if (answer.get("width"), answer.get("height")) != (width, height):
        raise ValueError("drew a picture of another size")
    extent = answer.get("extent") or {}
    reference = extent.get("spatialReference") or {}
    if 4326 not in (reference.get("latestWkid"), reference.get("wkid")):
        raise ValueError("drew the picture in another coordinate system")
    drawn = {"south": float(extent["ymin"]), "west": float(extent["xmin"]),
             "north": float(extent["ymax"]), "east": float(extent["xmax"])}
    latitude = (bounds["south"] + bounds["north"]) / 2
    longitude = (bounds["west"] + bounds["east"]) / 2
    if not (all(math.isfinite(value) for value in drawn.values())
            and drawn["south"] < latitude < drawn["north"] and drawn["west"] < longitude < drawn["east"]):
        raise ValueError("drew a box away from the one asked for")
    return link.geturl(), drawn


def _clean_jpeg(content: bytes, width: int, height: int) -> bytes:
    """Accept only a JPEG of the requested size; re-encode it without metadata."""
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format != "JPEG" or source.size != (width, height):
                raise ValueError("unexpected image")
            source.load()
            output = BytesIO()
            source.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("The imagery service did not return an image.") from exc


def fetch_aerial(bounds: dict, width: int, height: int) -> tuple[bytes, str, str | None, dict]:
    """Fetch an image of a latitude/longitude box: (jpeg, source, capture date or None, box drawn)."""
    errors = []
    for source, url in (("usgs_naip", NAIP_EXPORT), ("usgs_naip", NAIP_EXPORT), ("usgs_imagery", BASEMAP_EXPORT)):
        try:
            answer, _ = _get(url, _export_params(bounds, width, height, exact=source == "usgs_naip"))
            href, drawn = _drawn(answer, url, bounds, width, height)
            content, content_type = _get(href)
            if not content_type.startswith("image/"):
                raise ValueError(f"answered {content_type or 'without a type'}")
            jpeg = _clean_jpeg(content, width, height)
            captured = _naip_capture_date(drawn) if source == "usgs_naip" else None
            return jpeg, source, captured, drawn
        except Exception as exc:  # network, HTTP or decoding: try the next source
            errors.append(f"{source}: {exc}")
    raise FacilityLayoutError("site_imagery_unavailable",
                              "The USGS imagery services did not answer. Try again in a minute.",
                              status_code=502, details={"attempts": [e[:160] for e in errors]})


def _mostly_blank(jpeg: bytes) -> bool:
    """True when most of a picture is flat white or black: the service has no photo there."""
    with Image.open(BytesIO(jpeg)) as picture:
        small = picture.convert("RGB").resize((64, 64))
        pixels = list(small.getdata())
    empty = sum(1 for r, g, b in pixels if min(r, g, b) > 245 or max(r, g, b) < 10)
    return empty > len(pixels) / 2


def fetch_mngeo_metro(bounds: dict, width: int, height: int) -> tuple[bytes, str, str | None, dict]:
    """The 2025 Twin Cities metro photo of a latitude/longitude box: (jpeg, source, captured, box).

    WMS GetMap draws exactly the box asked for, so the box is the one requested.
    """
    covered = MNGEO_METRO_COVERAGE
    not_covered = FacilityLayoutError(
        "site_imagery_not_covered",
        "The high-resolution photo covers only the 7-county Twin Cities metro. Use the standard photo here.",
        status_code=422)
    if not (covered["west"] <= bounds["west"] and bounds["east"] <= covered["east"]
            and covered["south"] <= bounds["south"] and bounds["north"] <= covered["north"]):
        raise not_covered
    params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": MNGEO_METRO_LAYER,
              "STYLES": "", "SRS": "EPSG:4326", "FORMAT": "image/jpeg", "WIDTH": width, "HEIGHT": height,
              "BBOX": f"{bounds['west']:.8f},{bounds['south']:.8f},{bounds['east']:.8f},{bounds['north']:.8f}"}
    errors = []
    for _attempt in range(2):
        try:
            content, content_type = _get(MNGEO_WMS, params)
            if not content_type.startswith("image/"):
                raise ValueError(f"answered {content_type or 'without a type'}")
            jpeg = _clean_jpeg(content, width, height)
        except Exception as exc:  # network, HTTP, a WMS error document or decoding: try once more
            errors.append(str(exc))
            continue
        if _mostly_blank(jpeg):
            raise not_covered
        return jpeg, "mngeo_metro", MNGEO_METRO_CAPTURED, dict(bounds)
    raise FacilityLayoutError("site_imagery_unavailable",
                              "The MnGeo image service did not answer. Try again in a minute, or use the standard photo.",
                              status_code=502, details={"attempts": [e[:160] for e in errors]})


def _naip_capture_date(bounds: dict) -> str | None:
    """The flight date of the NAIP photo at the box centre, if the service says."""
    centre = {"x": (bounds["west"] + bounds["east"]) / 2, "y": (bounds["south"] + bounds["north"]) / 2,
              "spatialReference": {"wkid": 4326}}
    for _attempt in range(2):  # the service often answers 504 once, as the export does
        try:
            content, _ = _get(NAIP_IDENTIFY, {"geometry": json.dumps(centre), "geometryType": "esriGeometryPoint",
                                              "returnGeometry": "false", "returnCatalogItems": "true", "f": "json"})
            for feature in (json.loads(content).get("catalogItems") or {}).get("features") or []:
                stamp = (feature.get("attributes") or {}).get("acquisition_date")
                if isinstance(stamp, (int, float)) and stamp > 0:
                    return datetime.datetime.fromtimestamp(stamp / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
            return None
        except Exception:  # the date is a courtesy; the image stands without it
            continue
    return None


def geocode(address: str) -> list[dict]:
    """Up to five US address matches as label, latitude and longitude."""
    text = " ".join(str(address or "").split())
    if not 3 <= len(text) <= 200:
        raise ValueError("Enter a street address of 3 to 200 characters.")
    try:
        content, _ = _get(CENSUS_GEOCODER, {"address": text, "benchmark": "Public_AR_Current", "format": "json"})
        matches = (json.loads(content).get("result") or {}).get("addressMatches") or []
    except Exception as exc:
        raise FacilityLayoutError("geocoder_unavailable", "The US Census address service did not answer.",
                                  status_code=502) from exc
    result = []
    for match in matches[:5]:
        coordinates = match.get("coordinates") or {}
        if isinstance(coordinates.get("x"), (int, float)) and isinstance(coordinates.get("y"), (int, float)):
            result.append({"label": str(match.get("matchedAddress") or text)[:160],
                           "latitude": round(float(coordinates["y"]), 8),
                           "longitude": round(float(coordinates["x"]), 8)})
    return result


def fetch_globe_tile(z: int, x: int, y: int) -> tuple[bytes, str]:
    """One 256-pixel globe tile, addressed z/x/y; the basemap's own order is z/row/column."""
    missing = FacilityLayoutError("site_globe_tile_missing", "Tile was not found.", status_code=404)
    if not (0 <= z <= GLOBE_MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise missing
    request = urllib.request.Request(f"{GLOBE_TILES}/{z}/{y}/{x}", headers={"User-Agent": USER_AGENT})
    unavailable = FacilityLayoutError("site_globe_unavailable", "The USGS imagery service did not answer.",
                                      status_code=502)
    try:
        with _urlopen(request, timeout=GLOBE_TIMEOUT_SECONDS) as response:
            content = response.read(GLOBE_TILE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise (missing if exc.code == 404 else unavailable) from exc
    except OSError as exc:
        raise unavailable from exc
    if len(content) <= GLOBE_TILE_BYTES:
        for magic, media_type in ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png")):
            if content.startswith(magic):
                return content, media_type
    raise unavailable


def _keep_globe_tile(key: tuple) -> tuple[bytes, str]:
    try:
        tile = fetch_globe_tile(*key)
    except BaseException:
        with _globe_lock:
            _globe_pending.pop(key, None)
        raise
    with _globe_lock:
        _globe_pending.pop(key, None)
        _globe_tiles[key] = tile
        _globe_tiles.move_to_end(key)
        while len(_globe_tiles) > GLOBE_MEMORY_TILES:
            _globe_tiles.popitem(last=False)
    return tile


def _globe_future(key: tuple) -> Future:
    """The tile from memory, the fetch already under way, or a new fetch: never two at once."""
    with _globe_lock:
        if key in _globe_tiles:
            _globe_tiles.move_to_end(key)
            done = Future()
            done.set_result(_globe_tiles[key])
            return done
        future = _globe_pending.get(key)
        if future is None:
            future = _globe_pending[key] = _globe_pool.submit(_keep_globe_tile, key)
        return future


def globe_future(z: int, x: int, y: int) -> Future:
    if not (0 <= z <= GLOBE_MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise FacilityLayoutError("site_globe_tile_missing", "Tile was not found.", status_code=404)
    return _globe_future((z, x, y))


def globe_tile(z: int, x: int, y: int) -> tuple[bytes, str]:
    return globe_future(z, x, y).result(timeout=GLOBE_TIMEOUT_SECONDS * 3)


def globe_column(latitude: float, longitude: float) -> list[tuple[int, int, int]]:
    """The 3 x 3 tiles around a place at every zoom, lowest first: what the dive will draw."""
    keys = []
    phi = math.radians(max(-85.0, min(85.0, latitude)))
    for z in range(GLOBE_MAX_ZOOM + 1):
        n = 2 ** z
        x = min(n - 1, int((longitude + 180) / 360 * n))
        y = min(n - 1, int((1 - math.asinh(math.tan(phi)) / math.pi) / 2 * n))
        keys.extend((z, (x + dx) % n, y + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if 0 <= y + dy < n)
    return list(dict.fromkeys(keys))


def prefetch_globe(latitude: float, longitude: float) -> int:
    keys = globe_column(latitude, longitude)
    for key in keys:
        _globe_future(key)
    return len(keys)


def site_photo_path(service, principal, site_id: str, image_id: str) -> Path:
    """Where a site's stored photo lives on disk (content-addressed, per tenant and site)."""
    if not re.fullmatch(r"[a-f0-9]{64}", str(image_id)):
        raise FacilityLayoutError("site_photo_missing", "The site photo was not found.", status_code=404)
    root = service.layout_repository.root / "site-imagery"
    return Path(_native_fs_path(scope_directory(root, principal, site_id) / (image_id + ".jpg")))


def store_jpeg(root: Path, principal, site_id: str, content: bytes, suffix: str = ".jpg") -> str:
    digest = sha256(content).hexdigest()
    folder = scope_directory(root, principal, site_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = Path(_native_fs_path(folder / (digest + suffix)))
    if not target.exists():
        fd, temporary = tempfile.mkstemp(prefix="image-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return digest


def create_site_imagery_router(*, service, principal_resolver, feature_gate=None):
    router = APIRouter()
    root = service.layout_repository.root / "site-imagery"

    def error_response(error):
        return JSONResponse(status_code=error.status_code, content={"error": error.to_dict()})

    async def body(request: Request) -> dict:
        try:
            value = json.loads((await request.body()) or b"{}")
        except ValueError as exc:
            raise FacilityLayoutError("invalid_request", "Expected a JSON object.", status_code=400) from exc
        if not isinstance(value, dict):
            raise FacilityLayoutError("invalid_request", "Expected a JSON object.", status_code=400)
        return value

    @router.post("/api/facility-site-geocode/{site_id}")
    async def lookup_address(site_id: str, request: Request):
        try:
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.read")
            value = await body(request)
            matches = await run_in_threadpool(geocode, value.get("address"))
            return {"matches": matches, "source": "US Census geocoder"}
        except ValueError as exc:
            return error_response(FacilityLayoutError("invalid_address", str(exc), status_code=400))
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/site-analysis")
    async def inspect_site(site_id: str, layout_id: str, request: Request):
        from .site_context import analyze_site_context
        from .validate import validate_layout
        try:
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.read")
            await run_in_threadpool(service.get_layout, principal, site_id, layout_id)
            value = await body(request)
            if set(value) != {"layout"} or not isinstance(value["layout"], dict):
                raise ValueError("Expected the current draft layout")
            layout = value["layout"]
            if layout.get("layoutId") != layout_id or (layout.get("association") or {}).get("siteId") != site_id:
                raise ValueError("Draft layout does not match this site and layout")
            validate_layout(layout)
            return await run_in_threadpool(analyze_site_context, layout)
        except ValueError as exc:
            return error_response(FacilityLayoutError("invalid_site_context", str(exc), status_code=400))
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/site-imagery")
    async def fetch_site_image(site_id: str, layout_id: str, request: Request):
        try:
            if feature_gate:
                feature_gate("manual_edit")
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.edit")
            await run_in_threadpool(service.get_layout, principal, site_id, layout_id)
            value = await body(request)
            source = str(value.get("source") or "standard")
            try:
                if source not in PHOTO_SOURCES:
                    raise ValueError("The photo source must be standard or mngeo_metro.")
                plan = plan_request(float(value.get("latitude")), float(value.get("longitude")),
                                    float(value.get("halfSizeMeters", 250)),
                                    HIGH_RES_METERS_PER_PIXEL if source == "mngeo_metro" else METERS_PER_PIXEL)
            except (TypeError, ValueError) as exc:
                raise FacilityLayoutError("invalid_site_image_request", str(exc) if isinstance(exc, ValueError)
                                          and str(exc) else "Give latitude, longitude and halfSizeMeters.",
                                          status_code=400) from exc
            fetch = fetch_mngeo_metro if source == "mngeo_metro" else fetch_aerial
            jpeg, source, captured, drawn = await run_in_threadpool(
                fetch, plan["bounds"], plan["widthPixels"], plan["heightPixels"])
            digest = await run_in_threadpool(store_jpeg, root, principal, site_id, jpeg)
            return {"imageId": digest, "imagePath": f"/api/facility-site-imagery/{site_id}/{digest}.jpg",
                    "source": source, "captured": captured, "geoBounds": drawn,
                    "widthPixels": plan["widthPixels"], "heightPixels": plan["heightPixels"]}
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.get("/api/facility-site-imagery/{site_id}/{digest}.jpg")
    async def get_site_image(site_id: str, digest: str, request: Request):
        return serve(site_id, digest, request, ".jpg", "image/jpeg")

    @router.get("/api/facility-site-imagery/{site_id}/{digest}.png")
    async def get_site_overlay(site_id: str, digest: str, request: Request):
        return serve(site_id, digest, request, ".png", "image/png")

    @router.get("/api/facility-site-globe/{site_id}/{z}/{x}/{y}.jpg")
    async def get_globe_tile(site_id: str, z: int, x: int, y: int, request: Request):
        try:
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.read")
            # Wait without holding one of the server's request threads: a dive sends a hundred-odd
            # tile requests, many cancelled by the browser, and held threads stalled every route.
            # The shield keeps a cancelled request from cancelling the shared fetch.
            try:
                content, media_type = await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(globe_future(z, x, y))), GLOBE_TIMEOUT_SECONDS * 3)
            except TimeoutError as exc:
                raise FacilityLayoutError("site_globe_unavailable", "The USGS imagery service did not answer.",
                                          status_code=502) from exc
            return Response(content, media_type=media_type, headers={
                "Cache-Control": "private, max-age=604800", "X-Content-Type-Options": "nosniff"})
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post("/api/facility-site-globe/{site_id}/prefetch")
    async def prefetch_globe_tiles(site_id: str, request: Request):
        try:
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.read")
            value = await body(request)
            try:
                latitude, longitude = float(value["latitude"]), float(value["longitude"])
                if not (abs(latitude) <= 85 and abs(longitude) <= 180):
                    raise ValueError("out of range")
            except (KeyError, TypeError, ValueError) as exc:
                raise FacilityLayoutError("invalid_site_globe_request", "Give latitude and longitude in degrees.",
                                          status_code=400) from exc
            futures = [asyncio.shield(asyncio.wrap_future(_globe_future(key)))
                       for key in globe_column(latitude, longitude)]
            # Answer once the column is in memory (or soon after), so the globe can dive into tiles
            # that are already here; a tile that fails just leaves its parent showing.
            done, _pending = await asyncio.wait(futures, timeout=GLOBE_PREFETCH_WAIT_SECONDS)
            return {"tiles": len(futures), "ready": sum(1 for f in done if not f.exception())}
        except FacilityLayoutError as exc:
            return error_response(exc)

    def serve(site_id, digest, request, suffix, media_type):
        try:
            principal = principal_resolver(request)
            require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.read")
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise FacilityLayoutError("site_image_missing", "Image was not found.", status_code=404)
            path = Path(_native_fs_path(scope_directory(root, principal, site_id) / (digest + suffix)))
            if not path.is_file():
                raise FacilityLayoutError("site_image_missing", "Image was not found.", status_code=404)
            return FileResponse(path, media_type=media_type, headers={
                "Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})
        except FacilityLayoutError as exc:
            return error_response(exc)

    async def editable(site_id, layout_id, request):
        if feature_gate:
            feature_gate("manual_edit")
        principal = principal_resolver(request)
        require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.edit")
        await run_in_threadpool(service.get_layout, principal, site_id, layout_id)
        return principal, await body(request)

    def bad(code, exc, fallback):
        return FacilityLayoutError(code, str(exc) if isinstance(exc, ValueError) and str(exc) else fallback,
                                   status_code=400)

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/site-parcel")
    async def fetch_site_parcel(site_id: str, layout_id: str, request: Request):
        from .site_layers import fetch_parcel
        try:
            _principal, value = await editable(site_id, layout_id, request)
            try:
                numbers = [float(value[key]) for key in ("latitude", "longitude", "originLatitude", "originLongitude")]
                if not all(math.isfinite(n) for n in numbers) or abs(numbers[0]) > 89 or abs(numbers[2]) > 89:
                    raise ValueError("Latitude and longitude must be degrees.")
            except (KeyError, TypeError, ValueError) as exc:
                raise bad("invalid_site_parcel_request", exc,
                          "Give latitude, longitude, originLatitude and originLongitude.") from exc
            return await run_in_threadpool(fetch_parcel, *numbers)
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/site-overlay")
    async def fetch_site_overlay(site_id: str, layout_id: str, request: Request):
        import datetime
        from .site_layers import LAYERS, fetch_overlay
        try:
            principal, value = await editable(site_id, layout_id, request)
            try:
                layer = value.get("layer")
                if layer not in LAYERS:
                    raise ValueError("The layer must be flood, wetlands, contours or soils.")
                box = value.get("geoBounds") or {}
                bounds = {key: float(box[key]) for key in ("south", "west", "north", "east")}
                if not (bounds["south"] < bounds["north"] and bounds["west"] < bounds["east"]
                        and bounds["north"] - bounds["south"] < 0.05 and bounds["east"] - bounds["west"] < 0.07):
                    raise ValueError("The overlay box must be a site-sized latitude/longitude box.")
                width, height = int(value.get("widthPixels")), int(value.get("heightPixels"))
                if not (64 <= width <= MAX_SIDE_PIXELS and 64 <= height <= MAX_SIDE_PIXELS):
                    raise ValueError("Overlay size must be 64 to 4096 pixels a side.")
            except (KeyError, TypeError, ValueError) as exc:
                raise bad("invalid_site_overlay_request", exc,
                          "Give layer, geoBounds, widthPixels and heightPixels.") from exc
            png, drawn, detail = await run_in_threadpool(fetch_overlay, layer, bounds, width, height)
            digest = await run_in_threadpool(store_jpeg, root, principal, site_id, png, ".png")
            with Image.open(BytesIO(png)) as picture:
                size = picture.size
            return {"layer": layer, "imageId": digest, "imagePath": f"/api/facility-site-imagery/{site_id}/{digest}.png",
                    "source": LAYERS[layer]["source"], "captured": datetime.date.today().isoformat(),
                    "geoBounds": drawn, "widthPixels": size[0], "heightPixels": size[1], "detail": detail}
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/site-trace")
    async def trace_site_photo(site_id: str, layout_id: str, request: Request):
        from .site_context import KEY, normalize_site_context
        from .site_trace import trace_feature
        from .validate import validate_layout
        try:
            principal, value = await editable(site_id, layout_id, request)
            try:
                layout = value.get("layout")
                if not isinstance(layout, dict) or set(value) - {"layout", "x", "z", "box"}:
                    raise ValueError("Expected the current draft layout and a point or a box")
                if layout.get("layoutId") != layout_id or (layout.get("association") or {}).get("siteId") != site_id:
                    raise ValueError("Draft layout does not match this site and layout")
                x = float(value["x"]) if value.get("x") is not None else None
                z = float(value["z"]) if value.get("z") is not None else None
                box = value.get("box")
                if box is not None:
                    box = {key: float(box[key]) for key in ("minX", "maxX", "minZ", "maxZ")}
                    if not (box["minX"] < box["maxX"] and box["minZ"] < box["maxZ"]):
                        raise ValueError("The box needs minX < maxX and minZ < maxZ")
                if box is None and (x is None or z is None):
                    raise ValueError("Give x and z, or a box")
                validate_layout(layout)
                raw = (layout.get("extensions") or {}).get(KEY)
                if raw is None:
                    raise ValueError("Place the layout on a site first.")
                context = normalize_site_context(raw, layout)
            except (KeyError, TypeError, ValueError) as exc:
                raise bad("invalid_site_trace", exc, "Expected the current draft layout and a point or a box.") from exc
            photo_path = lambda image: site_photo_path(service, principal, site_id, image["imageId"])  # noqa: E731
            return await run_in_threadpool(trace_feature, layout, context, photo_path, x, z, box)
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/site-roads")
    async def fetch_site_roads(site_id: str, layout_id: str, request: Request):
        from .site_roads import fetch_roads
        try:
            _principal, value = await editable(site_id, layout_id, request)
            try:
                box = value.get("geoBounds") or {}
                bounds = {key: float(box[key]) for key in ("south", "west", "north", "east")}
                if not (bounds["south"] < bounds["north"] and bounds["west"] < bounds["east"]
                        and bounds["north"] - bounds["south"] < 0.05 and bounds["east"] - bounds["west"] < 0.07):
                    raise ValueError("The road box must be a site-sized latitude/longitude box.")
            except (KeyError, TypeError, ValueError) as exc:
                raise bad("invalid_site_roads_request", exc, "Give geoBounds.") from exc
            return await run_in_threadpool(fetch_roads, bounds)
        except FacilityLayoutError as exc:
            return error_response(exc)

    @router.post("/api/facility-layouts/{site_id}/{layout_id}/site-layer-checks")
    async def check_site_layers(site_id: str, layout_id: str, request: Request):
        from .site_context import KEY, normalize_site_context, site_geometry_key
        from .site_layers import LAYERS, check_layers, check_targets
        from .validate import validate_layout
        try:
            _principal, value = await editable(site_id, layout_id, request)
            try:
                layout = value.get("layout")
                if not isinstance(layout, dict) or set(value) - {"layout", "layers"}:
                    raise ValueError("Expected the current draft layout")
                if layout.get("layoutId") != layout_id or (layout.get("association") or {}).get("siteId") != site_id:
                    raise ValueError("Draft layout does not match this site and layout")
                layers = value.get("layers") or list(LAYERS)
                if not isinstance(layers, list) or any(layer not in LAYERS for layer in layers):
                    raise ValueError("Layers must be flood, wetlands, contours or soils.")
                validate_layout(layout)
                raw = (layout.get("extensions") or {}).get(KEY)
                if raw is None:
                    raise ValueError("Place the layout on a site first.")
                context = normalize_site_context(raw, layout)
            except ValueError as exc:
                raise bad("invalid_site_layer_check", exc, "Expected the current draft layout.") from exc
            targets = check_targets(layout, context)
            result = await run_in_threadpool(check_layers, targets, layers)
            return {"geometryKey": site_geometry_key(layout, context), **result}
        except FacilityLayoutError as exc:
            return error_response(exc)

    return router
