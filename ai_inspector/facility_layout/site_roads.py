"""Roads and railways around a site, from the US Census TIGER/Line map (public domain).

Sage uses them to decide which side of a building faces which road (docks toward the truck
route, away from houses), and the Site tab draws them over the photo. The server fetches them
from TIGERweb for the photo's box (highways and arterials, and the local streets that lead out to
them, from a box twice the size), clips and simplifies them, and merges features that differ
only in name ("St Croix Trl N" and "State Hwy 95" are one road). The site context stores them
in latitude/longitude and derives property-frame lines (site_context.py). US only; no key.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime
import math

from .errors import FacilityLayoutError
from .site_context import MAX_ROAD_POINTS, MAX_ROADS, ROAD_KINDS, building_outline

TIGER_MAP = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer"
TIGER_LAYERS = (2, 6, 8, 9)  # primary, secondary and local roads, and railroads, each at full detail
MAIN_ROAD_LAYERS = (2, 6)
LOCAL_LAYER = 8
LINK_KINDS = ("local", "ramp")  # public streets a way out to a main road may follow
LINK_SNAP_DECIMALS = 2  # streets that meet share a TIGER vertex; centimetres match them
MAIN_ROAD_REACH = 2.0  # highways and arterials are fetched from a box twice the photo's size: the truck
                       # route matters even when it runs just past the photo
KIND_ORDER = ("highway", "arterial", "ramp", "local", "service", "alley", "private", "parking_aisle", "railroad")
SIMPLIFY_METERS = 0.5
SAME_ROAD_METERS = 3.0
MAX_POINTS_PER_ROAD = 200
METERS_PER_DEGREE = 111_320.0
ALONG_EDGE_METERS = 30.0
ALONG_EDGE_DEGREES = 25.0
COMPASS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")


def _layer(layer_id: int, bounds: dict) -> list[dict]:
    from .site_layers import _json
    answer = _json(f"{TIGER_MAP}/{layer_id}/query", {
        "geometry": f"{bounds['west']},{bounds['south']},{bounds['east']},{bounds['north']}",
        "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "OID,NAME,MTFCC",
        "returnGeometry": "true", "f": "json"})
    if answer.get("exceededTransferLimit"):
        raise ValueError("More roads than one answer holds")
    return answer.get("features") or []


def _lies_on(longer, shorter) -> bool:
    """Whether every part of the shorter line runs within a few metres of the longer one."""
    from shapely import segmentize
    from shapely.geometry import Point
    return all(longer.distance(Point(point)) <= SAME_ROAD_METERS for point in segmentize(shorter, 5.0).coords)


def _node(point) -> tuple[float, float]:
    return (round(point[0], LINK_SNAP_DECIMALS), round(point[1], LINK_SNAP_DECIMALS))


def _junctions(lines: list) -> set:
    """Vertices where lines meet: an end on another line, or a crossing at a shared vertex.

    Twin features (one road under two names) share every vertex but run on together, so a shared
    vertex whose neighbours are the same on every line is not a junction.
    """
    around = {}
    for index, (_layer, _mtfcc, _name, _oid, line) in enumerate(lines):
        coords = list(line.coords)
        for i, point in enumerate(coords):
            neighbours = frozenset(_node(coords[j]) for j in (i - 1, i + 1) if 0 <= j < len(coords))
            around.setdefault(_node(point), []).append((index, neighbours, i in (0, len(coords) - 1)))
    return {key for key, users in around.items() if len({index for index, _n, _end in users}) > 1
            and (any(end for _i, _n, end in users) or len({neighbours for _i, neighbours, _e in users}) > 1)}


def _simplify_keeping(line, keep: set, tolerance: float):
    """Simplify a line but keep its junction vertices, so the stored map still shows which streets meet:
    a junction simplified away would read as an overpass."""
    from shapely.geometry import LineString
    coords = list(line.coords)
    cuts = [0] + [i for i in range(1, len(coords) - 1) if _node(coords[i]) in keep] + [len(coords) - 1]
    out = []
    for a, b in zip(cuts, cuts[1:]):
        points = list(LineString(coords[a:b + 1]).simplify(tolerance, preserve_topology=False).coords)
        out.extend(points if not out else points[1:])
    return LineString(out)


def _links(lines: list, photo) -> dict[int, list]:
    """Stretches of local street that join the photo's streets to the nearest highway or arterial.

    TIGER/Line is topological: streets that meet share a vertex, while an overpass shares none. A
    shortest-path search over local streets, starting from every main-road vertex, gives each street
    vertex in the photo its way out to a main road. Only the stretches those ways use are kept, so a
    far-off street grid is never stored. Returns {line index: [(a, b) segments in metres]}.
    """
    import heapq
    from shapely.geometry import Point
    node = lambda point: (round(point[0], LINK_SNAP_DECIMALS), round(point[1], LINK_SNAP_DECIMALS))  # noqa: E731
    graph = {}
    for index, (layer, mtfcc, _name, _oid, line) in enumerate(lines):
        if layer in MAIN_ROAD_LAYERS or ROAD_KINDS[mtfcc] not in LINK_KINDS:
            continue
        coords = list(line.coords)
        for a, b in zip(coords, coords[1:]):
            if node(a) != node(b):
                graph.setdefault(node(a), []).append((node(b), math.dist(a, b), index, (a, b)))
                graph.setdefault(node(b), []).append((node(a), math.dist(a, b), index, (a, b)))
    sources = {node(point) for layer, _m, _n, _o, line in lines if layer in MAIN_ROAD_LAYERS for point in line.coords}
    best = dict.fromkeys(sources, 0.0)
    heap = [(0.0, source) for source in sources]
    heapq.heapify(heap)
    back = {}
    while heap:
        distance, here = heapq.heappop(heap)
        if distance > best[here]:
            continue
        for there, length, index, segment in graph.get(here, ()):
            if distance + length < best.get(there, math.inf):
                best[there] = distance + length
                back[there] = (here, index, segment)
                heapq.heappush(heap, (distance + length, there))
    links, walked = {}, set()
    for layer, mtfcc, _name, _oid, line in lines:
        if layer in MAIN_ROAD_LAYERS or ROAD_KINDS[mtfcc] not in LINK_KINDS:
            continue
        for point in line.coords:
            here = node(point)
            if here in walked or not photo.covers(Point(point)):
                continue
            while here in back and here not in walked:
                walked.add(here)
                here, index, segment = back[here]
                links.setdefault(index, []).append(segment)
    return links


def fetch_roads(bounds: dict) -> dict:
    """The roads and railways crossing a latitude/longitude box, clipped to it.

    Highways and arterials reach twice as far, and so do the stretches of local street that join the
    photo's streets to them (see _links), so the way out to the main road is known. All or nothing: a
    road map missing its local streets would mislead the dock-side reasoning.
    """
    from shapely import affinity, line_merge
    from shapely.geometry import LineString, MultiLineString, box
    middle = ((bounds["south"] + bounds["north"]) / 2, (bounds["west"] + bounds["east"]) / 2)
    wide = {"south": middle[0] - (middle[0] - bounds["south"]) * MAIN_ROAD_REACH,
            "north": middle[0] + (bounds["north"] - middle[0]) * MAIN_ROAD_REACH,
            "west": middle[1] - (middle[1] - bounds["west"]) * MAIN_ROAD_REACH,
            "east": middle[1] + (bounds["east"] - middle[1]) * MAIN_ROAD_REACH}

    def fetch(layer):
        if layer in MAIN_ROAD_LAYERS:
            return _layer(layer, wide), False
        if layer != LOCAL_LAYER:
            return _layer(layer, bounds), False
        try:
            return _layer(layer, wide), True
        except ValueError:  # too many streets in the wide box for one answer: the photo's own, without links
            return _layer(layer, bounds), False

    try:
        with ThreadPoolExecutor(max_workers=len(TIGER_LAYERS)) as pool:
            answers = dict(zip(TIGER_LAYERS, pool.map(fetch, TIGER_LAYERS)))
    except Exception as exc:
        raise FacilityLayoutError("site_roads_unavailable", "The US Census road map did not answer.",
                                  status_code=502) from exc
    # Work in metres east/north of the box's south-west corner, then store degrees again.
    xfact = METERS_PER_DEGREE * math.cos(math.radians((bounds["south"] + bounds["north"]) / 2))
    to_metres = lambda shape: affinity.scale(affinity.translate(shape, -bounds["west"], -bounds["south"]),  # noqa: E731
                                             xfact, METERS_PER_DEGREE, origin=(0, 0))
    to_degrees = lambda shape: affinity.translate(affinity.scale(shape, 1 / xfact, 1 / METERS_PER_DEGREE,  # noqa: E731
                                                                 origin=(0, 0)), bounds["west"], bounds["south"])
    photo = to_metres(box(bounds["west"], bounds["south"], bounds["east"], bounds["north"]))
    far = to_metres(box(wide["west"], wide["south"], wide["east"], wide["north"]))
    lines = []
    for layer in TIGER_LAYERS:
        for feature in answers[layer][0]:
            attributes = feature.get("attributes") or {}
            mtfcc = attributes.get("MTFCC")
            if mtfcc not in ROAD_KINDS:
                continue  # trails, paths and medians
            name = str(attributes.get("NAME") or "").strip()[:80]
            for path in (feature.get("geometry") or {}).get("paths") or []:
                if len(path) >= 2:
                    lines.append((layer, mtfcc, name, str(attributes.get("OID") or "x"), to_metres(LineString(path))))
    links = _links(lines, photo) if answers[LOCAL_LAYER][1] else {}
    meets = _junctions(lines)
    parts = []
    for index, (layer, mtfcc, name, oid, line) in enumerate(lines):
        clipped = line.intersection(far if layer in MAIN_ROAD_LAYERS else photo)
        if index in links:
            # The photo's stretch and its way out to a main road, cut from the street itself along a thin strip
            # round the links, so the two never overlap as near-copies that will not merge into one line.
            strip = line_merge(MultiLineString(links[index])).buffer(0.5, cap_style=2, join_style=2)
            clipped = line.intersection(photo.union(strip)).intersection(far)
        for piece in getattr(clipped, "geoms", [clipped]):
            if piece.geom_type != "LineString" or piece.length < 1.0:
                continue
            tolerance = SIMPLIFY_METERS
            simple = _simplify_keeping(piece, meets, tolerance)
            while len(simple.coords) > MAX_POINTS_PER_ROAD and tolerance < 64:
                tolerance *= 2
                simple = _simplify_keeping(piece, meets, tolerance)
            while len(simple.coords) > MAX_POINTS_PER_ROAD:  # more junctions than a line may hold
                tolerance *= 2
                simple = piece.simplify(tolerance, preserve_topology=False)
            parts.append({"mtfcc": mtfcc, "names": [name] if name else [], "oid": oid, "shape": simple})
    # Longest first, so a town's name for one stretch of a highway joins the highway.
    parts.sort(key=lambda part: (-round(part["shape"].length, 1), part["mtfcc"], part["names"], part["oid"]))
    merged = []
    for part in parts:
        twin = next((road for road in merged if ROAD_KINDS[road["mtfcc"]] == ROAD_KINDS[part["mtfcc"]]
                     and _lies_on(road["shape"], part["shape"])), None)
        if twin is None:
            merged.append(part)
        else:
            twin["names"] += [name for name in part["names"] if name not in twin["names"]][:4 - len(twin["names"])]
    merged.sort(key=lambda road: (KIND_ORDER.index(ROAD_KINDS[road["mtfcc"]]),
                                  road["names"][0] if road["names"] else "~", -road["shape"].length))
    items, points, seen = [], 0, {}
    for road in merged:
        coords = [[round(x, 7), round(y, 7)] for x, y in to_degrees(road["shape"]).coords]
        if len(items) == MAX_ROADS or points + len(coords) > MAX_ROAD_POINTS:
            break
        seen[road["oid"]] = seen.get(road["oid"], -1) + 1
        items.append({"roadId": f"tiger-{road['oid']}-{seen[road['oid']]}", "names": road["names"],
                      "mtfcc": road["mtfcc"], "lonLat": coords})
        points += len(coords)
    return {"source": "census_tiger", "fetched": datetime.date.today().isoformat(),
            "geoBounds": dict(bounds), "items": items}


def summarize_roads(layout: dict, site: dict) -> dict | None:
    """What Sage needs to choose sides: each road's kind, how far it is and which side it is on."""
    from shapely.geometry import LineString, Point, Polygon
    roads = site.get("roads")
    if not roads:
        return None
    building = Polygon([(p["x"], p["z"]) for p in building_outline(layout, site)])
    center = building.centroid
    lot = site.get("property")
    boundary = [(p["x"], p["z"]) for p in lot["boundary"]] if lot else []
    lot_shape = Polygon(boundary) if lot else None
    summary = {}
    for road in roads["items"]:
        line = LineString([(p["x"], p["z"]) for p in road["line"]])
        nearest = line.interpolate(line.project(center))
        bearing = math.degrees(math.atan2(nearest.x - center.x, nearest.y - center.y)) % 360
        entry = summary.setdefault((road["label"], road["kind"]), {
            "name": road["label"], "kind": road["kind"], "distanceFromBuildingMeters": math.inf,
            "sideOfBuilding": None, "lengthInViewMeters": 0.0})
        distance = line.distance(building)
        if distance < entry["distanceFromBuildingMeters"]:
            entry.update(distanceFromBuildingMeters=distance, sideOfBuilding=COMPASS[round(bearing / 45) % 8])
        entry["lengthInViewMeters"] += road["lengthMeters"]
        if lot_shape is not None:
            entry["distanceFromLotMeters"] = min(entry.get("distanceFromLotMeters", math.inf), line.distance(lot_shape))
            along = set(entry.get("alongLotEdges", []))
            for index, a in enumerate(boundary):
                b = boundary[(index + 1) % len(boundary)]
                edge = LineString([a, b])
                if edge.length < 1 or line.distance(edge) > ALONG_EDGE_METERS:
                    continue
                near = line.interpolate(line.project(Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)))
                step = line.interpolate(min(line.length, line.project(near) + 5.0))
                back = line.interpolate(max(0.0, line.project(near) - 5.0))
                road_angle = math.atan2(step.y - back.y, step.x - back.x)
                edge_angle = math.atan2(b[1] - a[1], b[0] - a[0])
                turn = abs(math.degrees(road_angle - edge_angle)) % 180
                if min(turn, 180 - turn) <= ALONG_EDGE_DEGREES:
                    along.add(index)
            entry["alongLotEdges"] = sorted(along)
    items = sorted(summary.values(), key=lambda item: item["distanceFromBuildingMeters"])[:20]
    for item in items:
        for key in ("distanceFromBuildingMeters", "distanceFromLotMeters", "lengthInViewMeters"):
            if key in item:
                item[key] = round(item[key], 1)
    return {"source": roads["attribution"], "fetched": roads["fetched"],
            "note": "Centerlines only; widths and traffic are not included. Local streets and railways cover the "
                    "photo; highways and arterials reach twice as far, and so do the stretches of local street "
                    "that lead out to them. Edge indices are 0-based, as in property.streetEdges.",
            "items": items}
