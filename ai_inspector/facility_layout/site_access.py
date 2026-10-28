"""How vehicles reach a site: street frontage, driveway clearances and routes to the main road.

Rules of thumb from the site-dressing research (docs/facility-site-dressing-plan.md):
- a driveway needs a street centreline within about 15 m of the lot edge it crosses;
- keep it about 23 m (75 ft) from an intersection on a quiet street (MnDOT access management) and
  about 30 m (100 ft) from a rail crossing;
- a guarded truck gate needs about 43 m (140 ft) from the street, so trucks waiting to check in
  clear it. With no gate, trucks drive on into the court; a shorter run is noted, not warned about.
Concept checks on Census centrelines (site_roads.py), not a traffic study.
"""
from __future__ import annotations

import math

FRONTAGE_METERS = 15.0
CORNER_CLEARANCE_METERS = 23.0
RAIL_CLEARANCE_METERS = 30.5
QUEUE_METERS = 42.7
END_ON_STREET_METERS = 1.0  # a street ending this close to another one meets it
MAIN_KINDS = ("highway", "arterial")  # a route ends where it reaches one of these
ROUTE_FACTORS = {"highway": 1.0, "arterial": 1.0, "ramp": 1.0, "local": 1.3, "service": 2.0}  # public ways only


def circle_around(point, radius: float):
    """Everything within `radius` of a shapely point, for keeping things at least that far away. A buffered point
    is a 64-sided polygon whose edges cut up to r(1 - cos(pi/64)) inside the circle, 4.8 cm at 40 m (live at
    Bayport, 2026-10-25: a car entrance 39.953 m from the truck entrance); this one's edges touch the circle from
    outside, so whatever lies outside it is at least `radius` away."""
    return point.buffer(radius / math.cos(math.pi / 64), quad_segs=16)


def street_lines(roads: dict | None) -> list[tuple[dict, object]]:
    """Each street's property-frame centreline; railways are left out."""
    from shapely.geometry import LineString
    return [(road, LineString([(p["x"], p["z"]) for p in road["line"]])) for road in (roads or {}).get("items", [])
            if road.get("kind") != "railroad" and len(road.get("line") or []) >= 2]


def rail_lines(roads: dict | None) -> list:
    from shapely.geometry import LineString
    return [LineString([(p["x"], p["z"]) for p in road["line"]]) for road in (roads or {}).get("items", [])
            if road.get("kind") == "railroad" and len(road.get("line") or []) >= 2]


def _points(geometry) -> list:
    """The points of an intersection result; overlapping stretches are not meeting points."""
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [geometry]
    return [part for part in getattr(geometry, "geoms", []) if part.geom_type == "Point"]


def junctions(line, others: list) -> list:
    """Where other streets meet this one: crossings, and street ends that stop on it."""
    from shapely.geometry import Point
    found = []
    for other in others:
        found += _points(line.intersection(other))
        found += [end for end in (Point(other.coords[0]), Point(other.coords[-1]))
                  if line.distance(end) <= END_ON_STREET_METERS]
    return found


def rail_crossings(line, rails: list) -> list:
    return [point for rail in rails for point in _points(line.intersection(rail))]


def frontage(boundary: list[tuple[float, float]], line, blocked: list[tuple[object, float]],
             width: float) -> list[tuple[int, object]]:
    """Stretches of lot edge where the middle of a driveway `width` wide can meet this street.

    Within FRONTAGE_METERS of its centreline, outside each (point, radius) in `blocked`, and far
    enough from the stretch's ends that the whole driveway stays on one edge. Returns
    [(edge index, stretch)].
    """
    from shapely.geometry import LineString
    from shapely.ops import substring, unary_union
    reach = line.buffer(FRONTAGE_METERS)
    keep_out = unary_union([circle_around(point, radius) for point, radius in blocked]) if blocked else None
    found = []
    for index, a in enumerate(boundary):
        edge = LineString([a, boundary[(index + 1) % len(boundary)]])
        near = edge.intersection(reach)
        if keep_out is not None and not near.is_empty:
            near = near.difference(keep_out)
        for piece in getattr(near, "geoms", [near]):
            if piece.geom_type == "LineString" and piece.length > width + 0.1:
                found.append((index, substring(piece, width / 2 + 0.05, piece.length - width / 2 - 0.05)))
    return found


def entrance_findings(context: dict) -> list[dict]:
    """Driveway checks for each vehicle entrance: on a street, clear of corners and rail, room to queue."""
    from shapely.geometry import Point, Polygon
    prop, roads = context.get("property"), context.get("roads")
    streets = street_lines(roads)
    if not prop or not streets:
        return []
    rails = rail_lines(roads)
    courts = [Polygon([(p["x"], p["z"]) for p in area["boundary"]])
              for area in context.get("areas", []) if area["kind"] == "truck_court"]
    findings = []
    for entrance in prop.get("entrances", []):
        if entrance["use"] == "pedestrians":
            continue
        point = Point(entrance["x"], entrance["z"])
        what = {"trucks": "truck entrance", "cars": "car entrance"}.get(entrance["use"], "entrance")
        road, line = min(streets, key=lambda item: item[1].distance(point))

        def finding(code, message, severity="warning", **extra):
            findings.append({"code": code, "severity": severity, "entranceId": entrance["entranceId"],
                             "message": message, **extra})
        gap = line.distance(point)
        if gap > FRONTAGE_METERS:
            finding("site_entrance_far_from_street",
                    f"The {what} is {gap:.0f} m from the nearest street ({road['label']}); a driveway needs "
                    f"the street within about {FRONTAGE_METERS:.0f} m.", distanceMeters=round(gap, 1))
            continue
        corner = min((j.distance(point) for j in junctions(line, [other for item, other in streets if item is not road])),
                     default=math.inf)
        if corner < CORNER_CLEARANCE_METERS:
            finding("site_entrance_near_intersection",
                    f"The {what} is {corner:.0f} m from an intersection on {road['label']}; about "
                    f"{CORNER_CLEARANCE_METERS:.0f} m (75 ft) is the usual minimum on a quiet street.",
                    distanceMeters=round(corner, 1))
        rail = min((c.distance(point) for c in rail_crossings(line, rails)), default=math.inf)
        if rail < RAIL_CLEARANCE_METERS:
            finding("site_entrance_near_rail_crossing",
                    f"The {what} is {rail:.0f} m from the rail crossing on {road['label']}; keep about "
                    f"{RAIL_CLEARANCE_METERS:.0f} m (100 ft).", distanceMeters=round(rail, 1))
        if entrance["use"] in ("trucks", "shared") and courts:
            queue = min(court.distance(point) for court in courts)
            if queue < QUEUE_METERS:
                finding("site_truck_queue_short",
                        f"{queue:.0f} m between the {what} and the truck court. Trucks drive straight in; a "
                        f"guarded gate would need about {QUEUE_METERS:.0f} m (140 ft) so trucks waiting to "
                        f"check in clear the street.", distanceMeters=round(queue, 1), severity="info")
    return findings


def vehicle_routes(context: dict) -> list[dict]:
    """Each vehicle entrance's way along the stored streets to the nearest highway or arterial.

    Streets join only where they share a vertex (site_roads keeps junctions), so an overpass is
    never a turn. Local streets cost a little more than main roads, so a route prefers to reach a
    main road early; alleys, private roads and parking aisles are not public ways and are not used.
    A route starts at the entrance on the lot line and ends where it first meets a main road.
    """
    import heapq
    from shapely.geometry import LineString, Point
    prop, roads = context.get("property"), context.get("roads")
    entrances = [e for e in (prop or {}).get("entrances", []) if e["use"] in ("trucks", "cars", "shared")]
    streets = [(road, line) for road, line in street_lines(roads) if road["kind"] in ROUTE_FACTORS]
    if not entrances or not streets:
        return []
    key = lambda point: (round(point[0], 2), round(point[1], 2))  # noqa: E731
    graph, where, main = {}, {}, {}
    for road, line in streets:
        coords = list(line.coords)
        for a, b in zip(coords, coords[1:]):
            if key(a) == key(b):
                continue
            where[key(a)], where[key(b)] = a, b
            cost = math.dist(a, b) * ROUTE_FACTORS[road["kind"]]
            graph.setdefault(key(a), []).append((key(b), cost, road))
            graph.setdefault(key(b), []).append((key(a), cost, road))
        if road["kind"] in MAIN_KINDS:
            main.update({key(point): road["label"] for point in coords})
    rails = rail_lines(roads)
    rail_vertices = {key(point) for rail in rails for point in rail.coords}
    found = []
    for entrance in entrances:
        point = Point(entrance["x"], entrance["z"])
        road, line = min(streets, key=lambda item: item[1].distance(point))
        if line.distance(point) > FRONTAGE_METERS:
            continue  # site_entrance_far_from_street says so
        attach = line.interpolate(line.project(point))
        coords, along, run, segment = list(line.coords), line.project(point), 0.0, len(line.coords) - 2
        for index, (a, b) in enumerate(zip(coords, coords[1:])):
            if run + math.dist(a, b) >= along:
                segment = index
                break
            run += math.dist(a, b)
        origin = key((attach.x, attach.y))
        where[origin] = (attach.x, attach.y)
        first = [(key(coords[i]), math.dist((attach.x, attach.y), coords[i]) * ROUTE_FACTORS[road["kind"]], road)
                 for i in (segment, segment + 1)]
        best, back, heap, reached = {origin: 0.0}, {}, [(0.0, origin)], None
        while heap:
            cost, here = heapq.heappop(heap)
            if cost > best.get(here, math.inf):
                continue
            if here in main or (here == origin and road["kind"] in MAIN_KINDS):
                reached = here
                break
            for there, step, via in graph.get(here, []) + (first if here == origin else []):
                if cost + step < best.get(there, math.inf):
                    best[there], back[there] = cost + step, (here, via)
                    heapq.heappush(heap, (cost + step, there))
        keys, vias = [reached if reached is not None else origin], []
        while keys[-1] != origin:
            previous, via = back[keys[-1]]
            keys.append(previous)
            vias.append(via)
        keys.reverse()
        vias.reverse()
        path = LineString([(entrance["x"], entrance["z"])] + [where[k] for k in keys])
        names = []
        for via in [road] + vias:
            if not names or names[-1] != via["label"]:
                names.append(via["label"])
        local = sum(math.dist(where[a], where[b]) for a, b, via in zip(keys, keys[1:], vias)
                    if via["kind"] not in MAIN_KINDS)
        simple = path.simplify(0.5, preserve_topology=False)
        found.append({
            "routeId": f"route-{entrance['entranceId']}"[:80], "entranceId": entrance["entranceId"],
            "use": entrance["use"],
            "mainRoad": main.get(reached, road["label"] if road["kind"] in MAIN_KINDS else None) if reached else None,
            "roads": names, "lengthMeters": round(path.length, 1), "localStreetMeters": round(local, 1),
            "railCrossings": sum(len(_points(path.intersection(rail))) for rail in rails),
            "railCrossingsAtGrade": sum(1 for k in keys if k in rail_vertices),
            "points": [{"x": round(x, 3) + 0.0, "z": round(z, 3) + 0.0} for x, z in simple.coords]})
    return found
