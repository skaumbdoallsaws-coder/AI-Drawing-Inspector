#!/usr/bin/env python3
"""Deterministic facility flow routing that stays inside the operating-zone aisles.

The aisle network is derived from the rack-row geometry (the same gaps the frontend
draws as operating zones), NOT from a hand-seeded sparse graph:

  - horizontal aisles run along the centerline of each gap between consecutive rack rows;
  - a west spine connects their west ends (the west operating aisle);
  - forklifts attach to the nearest aisle by a short perpendicular approach;
  - a route to a rack ends at an ACCESS POINT in the adjacent aisle (in front of the rack),
    never at the rack centre — so routes no longer cut through or terminate inside racks.

All travel happens on aisle centerlines, which sit between the racks by construction, so
the path cannot cross a rack footprint. A lightweight obstacle check flags any vertex that
lands inside a rack band as a safety net.

Coordinates are in the SolidWorks/semantic frame (identity transform to the GLB per the
coordinate contract). The polyline is NOT pre-recentered; the renderer draws it under
state.assyLiveScene. The math is LLM-free and deterministic.
"""

from __future__ import annotations

import heapq
import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

EAST_MARGIN_M = 0.30          # extend aisle past the easternmost rack center
RACK_HALF_DEPTH_M = 0.70     # fallback footprint half-depth when no rack envelope was extracted
RACK_FACE_CLEARANCE_M = 0.12  # rack access point sits this far OUTSIDE the footprint, in the aisle
OBSTACLE_EPS_M = 0.15        # a segment must cross a rack interior by more than this to count as a violation
DEFAULT_SPEED_MPS = 1.5      # assumed forklift travel speed for ETA (override via options.speedMps)

# Facility frame: +x = east, +z = south (rows run north=low z -> south=high z), y = vertical.
_BEARING_WORD = {"N": "north", "S": "south", "E": "east", "W": "west"}


# ------------------------------------------------------------------- geometry

def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _project(px, pz, ax, az, bx, bz):
    """Foot of perpendicular from (px,pz) onto segment (a,b), clamped. Returns (fx,fz,dist)."""
    dx, dz = bx - ax, bz - az
    l2 = dx * dx + dz * dz
    t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / l2))
    fx, fz = ax + t * dx, az + t * dz
    return fx, fz, math.hypot(px - fx, pz - fz)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _bearing(dx, dz):
    if abs(dx) >= abs(dz):
        return "E" if dx > 0 else "W"
    return "S" if dz > 0 else "N"


def _turn(pv, nv):
    """Turn from heading pv to nv. cross>0 = right, cross<0 = left (this frame)."""
    cross = pv[0] * nv[1] - pv[1] * nv[0]
    dot = pv[0] * nv[0] + pv[1] * nv[1]
    mag = math.hypot(*pv) * math.hypot(*nv)
    if mag < 1e-9:
        return "straight"
    if dot < -0.7 * mag:
        return "back"
    if cross > 0.1 * mag:
        return "right"
    if cross < -0.1 * mag:
        return "left"
    return "straight"


def _eta_text(seconds):
    s = int(round(seconds))
    if s < 60:
        return f"~{s} s"
    return f"~{s // 60} min {s % 60} s" if s % 60 else f"~{s // 60} min"


def _rack_rects(rows):
    """Rack footprint rectangles (x0, z0, x1, z1, id) for obstacle/clearance checks."""
    return [(r["fxmin"], r["fzmin"], r["fxmax"], r["fzmax"], r["id"]) for r in rows]


def _seg_crosses_rect(ax, az, bx, bz, x0, z0, x1, z1, eps=OBSTACLE_EPS_M):
    """True if segment a->b passes through the rect interior by more than eps (Liang-Barsky)."""
    dx, dz = bx - ax, bz - az
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dz, az - z0), (dz, z1 - az)):
        if abs(p) < 1e-12:
            if q < 0:
                return False  # parallel to a slab and outside it
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return False
                if t > t0:
                    t0 = t
            else:
                if t < t0:
                    return False
                if t < t1:
                    t1 = t
    if t1 <= t0:
        return False
    return (t1 - t0) * math.hypot(dx, dz) > eps


def _floor_y(semantic: dict) -> float:
    ys = [_num((i.get("positionMeters") or {}).get("y"))
          for r in semantic.get("rackRows", []) for i in r.get("rackInstances", [])]
    ys = [y for y in ys if y is not None]
    return min(ys) if ys else 0.0


def _polygon_bounds(poly) -> Optional[dict]:
    pts = [(p.get("x"), p.get("z")) for p in (poly or []) if isinstance(p, dict)]
    xs = [_num(x) for x, _ in pts]
    zs = [_num(z) for _, z in pts]
    xs = [x for x in xs if x is not None]
    zs = [z for z in zs if z is not None]
    if not xs or not zs:
        return None
    return {"xmin": min(xs), "xmax": max(xs), "zmin": min(zs), "zmax": max(zs)}


# --------------------------------------------------------------------- rows

def _rows(semantic: dict) -> List[dict]:
    rows = []
    for r in semantic.get("rackRows", []):
        xs, zs, env_xs, env_zs = [], [], [], []
        for inst in r.get("rackInstances", []):
            p = inst.get("positionMeters") or {}
            x, z = _num(p.get("x")), _num(p.get("z"))
            if x is not None and z is not None:
                xs.append(x); zs.append(z)
            bounds = (((inst.get("rackEnvelopeEstimate") or {}).get("centerlineBoundsMeters")) or {})
            mn, mx = bounds.get("min") or {}, bounds.get("max") or {}
            ex0, ex1 = _num(mn.get("x")), _num(mx.get("x"))
            ez0, ez1 = _num(mn.get("z")), _num(mx.get("z"))
            if ex0 is not None and ex1 is not None:
                env_xs.extend([ex0, ex1])
            if ez0 is not None and ez1 is not None:
                env_zs.extend([ez0, ez1])
        if not xs:
            continue
        axis = r.get("primaryAxis") or ("x" if (max(xs) - min(xs)) >= (max(zs) - min(zs)) else "z")
        # Prefer extracted metal rack envelope bounds. Fallback to rack-center rows plus a small
        # nominal depth so legacy semantics remain routable.
        if env_xs:
            fxmin, fxmax = min(env_xs), max(env_xs)
        elif axis == "z":
            cx = sum(xs) / len(xs)
            fxmin, fxmax = cx - RACK_HALF_DEPTH_M, cx + RACK_HALF_DEPTH_M
        else:
            fxmin, fxmax = min(xs) - 0.2, max(xs) + 0.2
        if env_zs:
            fzmin, fzmax = min(env_zs), max(env_zs)
        elif axis == "x":
            cz = sum(zs) / len(zs)
            fzmin, fzmax = cz - RACK_HALF_DEPTH_M, cz + RACK_HALF_DEPTH_M
        else:
            fzmin, fzmax = min(zs) - 0.2, max(zs) + 0.2
        rows.append({
            "id": r.get("id"), "label": r.get("displayName") or r.get("id"),
            "axis": axis,
            "cx": sum(xs) / len(xs), "cz": sum(zs) / len(zs),
            "xmin": min(xs), "xmax": max(xs), "zmin": min(zs), "zmax": max(zs),
            "fxmin": fxmin, "fxmax": fxmax, "fzmin": fzmin, "fzmax": fzmax,
            "loadX": (fxmin + fxmax) / 2.0, "loadZ": (fzmin + fzmax) / 2.0,
            "aliases": r.get("aliases") or [],
        })
    return rows


# --------------------------------------------------------------- aisle graph

def _layout_aisle_corridors(semantic: Optional[dict]) -> List[dict]:
    return (((semantic or {}).get("layoutMap") or {}).get("aisleCorridors") or [])


def _corridor_for_rows(corridors: List[dict], row_a: str, row_b: str) -> Optional[dict]:
    target = {row_a, row_b}
    for c in corridors:
        if set(c.get("betweenRows") or []) == target:
            return c
    return None


def _connector_corridor(corridors: List[dict]) -> Optional[dict]:
    for c in corridors:
        if c.get("id") == "Aisle_West_Connector" or c.get("kind") == "connector_corridor":
            return c
    return None


def _build_aisle_graph(rows: List[dict], semantic: Optional[dict] = None):
    horiz = sorted([r for r in rows if r["axis"] == "x"], key=lambda r: r["cz"])
    vert = [r for r in rows if r["axis"] == "z"]
    if len(horiz) < 2:
        return None
    corridors = _layout_aisle_corridors(semantic)
    west_corridor = _connector_corridor(corridors)
    west_center = (west_corridor or {}).get("centerlineMeters") or {}
    west_x = _num(west_center.get("x"))
    if west_x is None:
        west_x = min(r["fxmin"] for r in horiz)
    aisles = []
    for k in range(len(horiz) - 1):
        a, b = horiz[k], horiz[k + 1]
        corridor = _corridor_for_rows(corridors, a["id"], b["id"])
        center = (corridor or {}).get("centerlineMeters") or {}
        bounds = _polygon_bounds((corridor or {}).get("approxFloorPolygonMeters"))
        z = _num(center.get("z"))
        if z is None:
            z = (a["cz"] + b["cz"]) / 2.0
        x_east = (bounds or {}).get("xmax")
        if x_east is None:
            x_east = max(a["fxmax"], b["fxmax"]) + EAST_MARGIN_M
        aid = (corridor or {}).get("id") or f"aisle_{k}"
        label = (corridor or {}).get("displayName") or f"{a['label']} / {b['label']} aisle"
        aisles.append({
            "id": aid, "z": z,
            "xWest": west_x, "xEast": x_east,
            "label": label,
        })
    nodes: Dict[str, Tuple[float, float]] = {}
    adj: Dict[str, List[Tuple[str, float, Optional[str]]]] = defaultdict(list)

    def link(u, v, w, aid):
        adj[u].append((v, w, aid)); adj[v].append((u, w, aid))

    for ai in aisles:
        wn, en = ai["id"] + "_w", ai["id"] + "_e"
        nodes[wn] = (ai["xWest"], ai["z"]); nodes[en] = (ai["xEast"], ai["z"])
        link(wn, en, abs(ai["xEast"] - ai["xWest"]), ai["id"])
    # West spine: only connect two aisle west-ends if that vertical run is actually a clear
    # corridor (does not pass through a rack). Otherwise there is no connector and the aisles
    # stay disconnected (routing between them will correctly report "no route").
    rects = _rack_rects(rows)
    spine_segments, spine_blocked = 0, 0
    for k in range(len(aisles) - 1):
        z0, z1 = aisles[k]["z"], aisles[k + 1]["z"]
        if any(_seg_crosses_rect(west_x, z0, west_x, z1, *rect[:4]) for rect in rects):
            spine_blocked += 1
            continue
        link(aisles[k]["id"] + "_w", aisles[k + 1]["id"] + "_w", abs(z1 - z0), "west_spine")
        spine_segments += 1
    spine_bounds = _polygon_bounds((west_corridor or {}).get("approxFloorPolygonMeters"))
    if spine_bounds:
        spine_z = (spine_bounds["zmin"], spine_bounds["zmax"])
    else:
        spine_z = (aisles[0]["z"], aisles[-1]["z"])
    return {"horiz": horiz, "vert": vert, "aisles": aisles, "westX": west_x,
            "nodes": nodes, "adj": adj, "spineZ": spine_z,
            "westSpineSegments": spine_segments, "westSpineBlocked": spine_blocked}


# ------------------------------------------------------------------ endpoints

def _endpoints(rows: List[dict], semantic: dict, graph) -> Dict[str, dict]:
    reg: Dict[str, dict] = {}
    horiz_ids = [r["id"] for r in graph["horiz"]]
    for r in rows:
        ep = {"id": r["id"], "label": r["label"], "kind": "rack_row", "cx": r["cx"], "cz": r["cz"],
              "axis": r["axis"], "aliases": r["aliases"],
              "fxmin": r["fxmin"], "fxmax": r["fxmax"], "fzmin": r["fzmin"], "fzmax": r["fzmax"],
              "loadX": r["loadX"], "loadZ": r["loadZ"]}
        if r["axis"] == "x" and r["id"] in horiz_ids:
            ep["rowIndex"] = horiz_ids.index(r["id"])
        reg[r["id"]] = ep
    for asset in semantic.get("materialHandlingAssets", []):
        p = asset.get("positionMeters") or {}
        x, z = _num(p.get("x")), _num(p.get("z"))
        if x is None or z is None or not asset.get("id"):
            continue
        reg[asset["id"]] = {"id": asset["id"], "label": asset.get("displayName") or asset["id"],
                            "kind": "forklift", "cx": x, "cz": z, "aliases": asset.get("aliases") or []}
    return reg


def _resolve(query: str, reg: Dict[str, dict], semantic: dict) -> Optional[dict]:
    if not query:
        return None
    q = str(query).strip()
    if q in reg:
        return reg[q]
    ql = q.lower()
    idx = semantic.get("semanticIndex") or {}
    if ql in idx and idx[ql] in reg:
        return reg[idx[ql]]
    for ep in reg.values():
        if ep["id"].lower() == ql or ep["label"].lower() == ql or any(ql == str(a).lower() for a in ep.get("aliases", [])):
            return ep
    if "fork" in ql:
        nums = re.findall(r"\d+", ql)
        if nums:
            tag = f"forklift_{int(nums[0]):02d}_"
            for ep in reg.values():
                if ep["kind"] == "forklift" and tag in ep["id"].lower():
                    return ep
    for ep in reg.values():
        if ql in ep["label"].lower() or ql in ep["id"].lower():
            return ep
    return None


def _attach(graph, nodes, adj, ep, role: str, feet_by_aisle: dict):
    """Insert an endpoint into the graph. Returns (anchor_id, include_anchor_in_polyline).

    Feet (access points on aisle centerlines) are recorded per aisle so _chain_feet can link
    same-aisle feet directly afterwards (otherwise two points on one aisle would detour
    through an end node).
    """
    def link(u, v, w, aid):
        adj[u].append((v, w, aid)); adj[v].append((u, w, aid))

    def record(aid, foot, fx, fz):
        feet_by_aisle.setdefault(aid, []).append((foot, fz if aid == "west_spine" else fx))

    anchor = f"__{role}__"
    nodes[anchor] = (ep["cx"], ep["cz"])

    if ep["kind"] == "forklift":
        # nearest aisle (horizontal or west spine) by perpendicular approach
        best = None  # (dist, fx, fz, connect_node_ids, aisleId)
        for ai in graph["aisles"]:
            fx, fz, d = _project(ep["cx"], ep["cz"], ai["xWest"], ai["z"], ai["xEast"], ai["z"])
            if best is None or d < best[0]:
                best = (d, fx, fz, [ai["id"] + "_w", ai["id"] + "_e"], ai["id"])
        sz0, sz1 = graph["spineZ"]
        fx, fz, d = _project(ep["cx"], ep["cz"], graph["westX"], sz0, graph["westX"], sz1)
        if d < best[0]:
            best = (d, fx, fz, [a["id"] + "_w" for a in graph["aisles"]], "west_spine")
        d, fx, fz, conns, aid = best
        foot = f"__{role}_foot__"
        nodes[foot] = (fx, fz)
        link(anchor, foot, d, aid)
        for cn in conns:
            link(foot, cn, _dist((fx, fz), nodes[cn]), aid)
        record(aid, foot, fx, fz)
        return anchor, True  # forklift position is a real on-floor point -> keep in polyline

    # rack: stop at the aisle-facing load/unload point. The along-row midpoint comes from the
    # extracted rack envelope, while the cross-row coordinate sits just outside the rack face,
    # so the marker is physically reachable and shared by all shelf levels in the rack row.
    specs = []  # (face_xz, foot_xz, connect_node_ids, aisleId)
    if ep.get("axis") == "z":  # west row -> west spine (spine lies east of the row)
        sz0, sz1 = graph["spineZ"]
        fz = max(min(ep["loadZ"], max(sz0, sz1)), min(sz0, sz1))
        face_x = (ep["fxmax"] + RACK_FACE_CLEARANCE_M
                  if graph["westX"] >= ep["cx"] else ep["fxmin"] - RACK_FACE_CLEARANCE_M)
        specs.append(((face_x, fz), (graph["westX"], fz),
                      [a["id"] + "_w" for a in graph["aisles"]], "west_spine"))
    else:
        i = ep.get("rowIndex")
        bordering = [k for k in (i - 1, i) if i is not None and 0 <= k < len(graph["aisles"])]
        for k in bordering:
            ai = graph["aisles"][k]
            fx = max(min(ep["loadX"], ai["xEast"]), ai["xWest"])
            face_z = (ep["fzmax"] + RACK_FACE_CLEARANCE_M
                      if ai["z"] >= ep["cz"] else ep["fzmin"] - RACK_FACE_CLEARANCE_M)
            specs.append(((fx, face_z), (fx, ai["z"]), [ai["id"] + "_w", ai["id"] + "_e"], ai["id"]))
    for j, (face, foot, conns, aid) in enumerate(specs):
        fn, ft = f"__{role}_face{j}__", f"__{role}_foot{j}__"
        nodes[fn] = face
        nodes[ft] = foot
        link(anchor, fn, 0.0, aid)             # virtual rack centre -> chosen face, no cost
        link(fn, ft, _dist(face, foot), aid)   # access leg: face -> aisle centerline
        for cn in conns:
            link(ft, cn, _dist(foot, nodes[cn]), aid)
        record(aid, ft, foot[0], foot[1])
    return anchor, False  # rack centre is virtual -> excluded; the face becomes the first drawn point


def _chain_feet(nodes, adj, feet_by_aisle):
    """Link feet on the same aisle in order, so two points on one aisle connect directly."""
    for aid, feet in feet_by_aisle.items():
        if len(feet) < 2:
            continue
        ordered = sorted(feet, key=lambda f: f[1])
        for (na, pa), (nb, pb) in zip(ordered, ordered[1:]):
            adj[na].append((nb, abs(pb - pa), aid))
            adj[nb].append((na, abs(pb - pa), aid))


# --------------------------------------------------------------------- search

def _dijkstra(nodes, adj, start, end):
    dist = {start: 0.0}
    prev: Dict[str, Tuple[str, Optional[str]]] = {}
    pq = [(0.0, start)]
    while pq:
        d, n = heapq.heappop(pq)
        if n == end:
            break
        if d > dist.get(n, math.inf):
            continue
        for nb, w, aid in adj.get(n, []):
            nd = d + w
            if nd < dist.get(nb, math.inf):
                dist[nb] = nd
                prev[nb] = (n, aid)
                heapq.heappush(pq, (nd, nb))
    if end not in dist:
        return None, None
    path, aids, cur = [end], [], end
    while cur != start:
        p, aid = prev[cur]
        aids.append(aid); path.append(p); cur = p
    path.reverse(); aids.reverse()
    return path, aids


# -------------------------------------------------------------------- result

def _aisle_label(aid: Optional[str], graph) -> Optional[str]:
    if not aid:
        return None
    if aid == "west_spine":
        return "West aisle"
    for ai in graph["aisles"]:
        if ai["id"] == aid:
            return ai["label"]
    return aid


def _edge_aid_between(aids: List[Optional[str]], start_idx: int, end_idx: int) -> Optional[str]:
    """First non-empty aisle id along the original path between two retained nodes."""
    if end_idx <= start_idx:
        return None
    for aid in aids[start_idx:end_idx]:
        if aid:
            return aid
    return None


def _compressed_drawn_path(path: List[str], nodes: Dict[str, Tuple[float, float]],
                           start_idx: int, end_idx: int) -> Tuple[List[str], List[int]]:
    """Drop consecutive drawn nodes that occupy the same point."""
    kept: List[str] = []
    kept_indices: List[int] = []
    for i in range(start_idx, end_idx):
        n = path[i]
        if kept and _dist(nodes[kept[-1]], nodes[n]) < 1e-6:
            continue
        kept.append(n)
        kept_indices.append(i)
    return kept, kept_indices


def _build_steps(drawn, nodes, drawn_aids, graph, s_label, e_label, e_kind):
    """Turn-by-turn directions. Merges same-bearing hops into legs and adds turns between them."""
    steps = [{"kind": "start", "text": f"Start at {s_label}"}]
    pts = [nodes[n] for n in drawn]
    segs = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        dx, dz = b[0] - a[0], b[1] - a[1]
        if math.hypot(dx, dz) < 1e-6:
            continue
        aid = drawn_aids[i] if i < len(drawn_aids) else None
        segs.append({"dx": dx, "dz": dz, "d": math.hypot(dx, dz), "bearing": _bearing(dx, dz), "aisle": aid})
    legs = []
    for s in segs:
        if legs and legs[-1]["bearing"] == s["bearing"]:
            legs[-1]["d"] += s["d"]
            if not legs[-1]["aisle"] and s["aisle"]:
                legs[-1]["aisle"] = s["aisle"]
        else:
            legs.append(dict(s))
    for i, leg in enumerate(legs):
        aisle_lbl = _aisle_label(leg["aisle"], graph) or "the aisle"
        word = _BEARING_WORD[leg["bearing"]]
        if i == 0:
            text = f"Head {word} along {aisle_lbl}"
        else:
            t = _turn((legs[i - 1]["dx"], legs[i - 1]["dz"]), (leg["dx"], leg["dz"]))
            verb = {"left": "Turn left", "right": "Turn right", "straight": "Continue", "back": "Turn around"}[t]
            text = f"{verb} and head {word} along {aisle_lbl}"
        steps.append({"kind": "travel", "text": text, "bearing": leg["bearing"],
                      "aisle": leg["aisle"], "distanceMeters": round(leg["d"], 1)})
    arrive = f"Arrive at {e_label}" + (" (aisle access)" if e_kind == "rack_row" else "")
    steps.append({"kind": "arrive", "text": arrive})
    return steps


def _is_endpoint_access_segment(u: str, v: str) -> bool:
    """Endpoint approach/load legs may touch the endpoint area; aisle travel may not."""
    for role in ("__start", "__end"):
        if u.startswith(role) and v.startswith(role):
            return True
    return False


def _obstacle_violations(polyline, rows, segment_node_pairs=None):
    """Route segments that pass through a rack-footprint rectangle (should be empty)."""
    bad = []
    rects = _rack_rects(rows)
    pts = [(p["x"], p["z"]) for p in polyline]
    for idx, ((ax, az), (bx, bz)) in enumerate(zip(pts, pts[1:])):
        if segment_node_pairs and idx < len(segment_node_pairs):
            u, v = segment_node_pairs[idx]
            if _is_endpoint_access_segment(u, v):
                continue
        for (x0, z0, x1, z1, rid) in rects:
            if _seg_crosses_rect(ax, az, bx, bz, x0, z0, x1, z1):
                bad.append({"row": rid, "seg": [round(ax, 2), round(az, 2), round(bx, 2), round(bz, 2)]})
                break
    return bad


def build_route_result(semantic: dict, start: str, end: str, options: Optional[dict] = None) -> dict:
    rows = _rows(semantic)
    graph = _build_aisle_graph(rows, semantic)
    if graph is None:
        return {"ok": False, "error": "Could not derive an aisle network (need >= 2 rack rows)."}
    reg = _endpoints(rows, semantic, graph)
    s = _resolve(start, reg, semantic)
    e = _resolve(end, reg, semantic)
    if s is None or e is None:
        routable = sorted({ep["label"] for ep in reg.values()})
        miss = [f"start '{start}'" for _ in [0] if s is None] + [f"end '{end}'" for _ in [0] if e is None]
        return {"ok": False, "error": f"Could not resolve {', '.join(miss)}.", "routableEndpoints": routable}
    if s["id"] == e["id"]:
        return {"ok": False, "error": "Start and end are the same endpoint."}

    nodes = dict(graph["nodes"])
    adj = defaultdict(list, {k: list(v) for k, v in graph["adj"].items()})
    feet_by_aisle = {}
    s_anchor, s_keep = _attach(graph, nodes, adj, s, "start", feet_by_aisle)
    e_anchor, e_keep = _attach(graph, nodes, adj, e, "end", feet_by_aisle)
    _chain_feet(nodes, adj, feet_by_aisle)

    path, aids = _dijkstra(nodes, adj, s_anchor, e_anchor)
    if not path:
        return {"ok": False, "error": f"No route found between {s['label']} and {e['label']}."}

    # Drop virtual rack anchors from the drawn polyline and collapse duplicate access feet.
    start_idx = 0 if s_keep else 1
    end_idx = len(path) if e_keep else len(path) - 1
    drawn, drawn_indices = _compressed_drawn_path(path, nodes, start_idx, end_idx)

    floor_y = _floor_y(semantic)
    polyline = [{"x": round(nodes[n][0], 4), "y": round(floor_y, 4), "z": round(nodes[n][1], 4)} for n in drawn]
    total, segments, aisle_ids = 0.0, [], []
    for i in range(len(drawn) - 1):
        a, b = nodes[drawn[i]], nodes[drawn[i + 1]]
        seg_d = _dist(a, b)
        if seg_d < 1e-6:
            continue
        total += seg_d
        # aisle id for this hop, from the original path edge labels.
        aid = _edge_aid_between(aids, drawn_indices[i], drawn_indices[i + 1])
        if aid and aid not in aisle_ids:
            aisle_ids.append(aid)
        segments.append({"from": drawn[i], "to": drawn[i + 1], "aisleId": aid, "distanceMeters": round(seg_d, 3)})

    via_labels = [l for l in (_aisle_label(a, graph) for a in aisle_ids) if l]
    via = " -> ".join(dict.fromkeys(via_labels)) if via_labels else "direct"
    start_label = s["label"]
    end_label = e["label"] + (" (aisle access)" if e["kind"] == "rack_row" else "")
    explanation = (f"From {start_label} to {end_label}: {round(total, 1)} m across {len(segments)} "
                   f"segment(s){f' via {via}' if via_labels else ''}.")

    speed = float((options or {}).get("speedMps") or DEFAULT_SPEED_MPS)
    eta_seconds = total / speed if speed > 0 else None
    drawn_aids = [_edge_aid_between(aids, drawn_indices[i], drawn_indices[i + 1])
                  for i in range(max(0, len(drawn) - 1))]
    steps = _build_steps(drawn, nodes, drawn_aids, graph, start_label, e["label"], e["kind"])

    segment_node_pairs = [(drawn[i], drawn[i + 1]) for i in range(len(drawn) - 1)]
    violations = _obstacle_violations(polyline, rows, segment_node_pairs)
    cf = ((semantic.get("layoutMap") or {}).get("coordinateFrame") or {})
    return {
        "ok": True,
        "start": {"id": s["id"], "label": s["label"], "kind": s["kind"],
                  "position": polyline[0] if polyline else None},
        "end": {"id": e["id"], "label": e["label"], "kind": e["kind"],
                "position": polyline[-1] if polyline else None},
        "pathNodeIds": drawn,
        "segments": segments,
        "aisleIds": aisle_ids,
        "aisleLabels": via_labels,
        "distanceMeters": round(total, 3),
        "etaSeconds": round(eta_seconds, 1) if eta_seconds is not None else None,
        "etaText": _eta_text(eta_seconds) if eta_seconds is not None else None,
        "speedAssumptionMps": speed,
        "steps": steps,
        "cost": {"distanceMeters": round(total, 3), "etaSeconds": round(eta_seconds, 1) if eta_seconds is not None else None},
        "routePolyline": polyline,
        "floorYMeters": round(floor_y, 4),
        "explanation": explanation,
        "units": "meters",
        "coordinateFrame": {
            "frame": "solidworks", "viewer": "glb", "transformToGlb": "identity",
            "glbSha256": (cf.get("glbAsset") or {}).get("sha256"),
            "rendererNote": "Draw under state.assyLiveScene; coordinates are NOT pre-recentered.",
        },
        "method": {
            "algorithm": "dijkstra",
            "graph": "aisle network derived from layoutMap aisle-corridor centerlines + west connector",
            "endpointAttachment": "forklift = perpendicular approach to nearest aisle; rack = aisle-facing load/unload midpoint with an access leg to the operating-zone centerline",
            "obstacleCheck": "ok" if not violations else "VIOLATIONS",
            "obstacleViolations": violations,
        },
    }


# ------------------------------------------------------ layout tradeoff (what-if)

def _route_cost(graph, reg, sid, eid) -> float:
    """Shortest travel distance between two endpoints over `graph` (inf if unreachable)."""
    s, e = reg.get(sid), reg.get(eid)
    if not s or not e or sid == eid:
        return math.inf
    nodes = dict(graph["nodes"])
    adj = defaultdict(list, {k: list(v) for k, v in graph["adj"].items()})
    feet = {}
    sa, _ = _attach(graph, nodes, adj, s, "s", feet)
    ea, _ = _attach(graph, nodes, adj, e, "e", feet)
    _chain_feet(nodes, adj, feet)
    dist = {sa: 0.0}
    pq = [(0.0, sa)]
    while pq:
        d, n = heapq.heappop(pq)
        if n == ea:
            return d
        if d > dist.get(n, math.inf):
            continue
        for nb, w, _ in adj.get(n, []):
            nd = d + w
            if nd < dist.get(nb, math.inf):
                dist[nb] = nd
                heapq.heappush(pq, (nd, nb))
    return dist.get(ea, math.inf)


def _candidate_with_east_spine(graph, rows):
    """A copy of the aisle graph with a hypothetical east cross-aisle added, east of every rack
    (so the spine is a clear perimeter corridor by construction), with a clearance check."""
    nodes = dict(graph["nodes"])
    adj = defaultdict(list, {k: list(v) for k, v in graph["adj"].items()})
    aisles = graph["aisles"]
    rects = _rack_rects(rows)
    east_x = max((r["fxmax"] for r in rows), default=0.0) + EAST_MARGIN_M  # east of every rack envelope

    def link(u, v, w, aid):
        adj[u].append((v, w, aid)); adj[v].append((u, w, aid))

    spine = []
    for ai in aisles:
        en = ai["id"] + "_es"
        nodes[en] = (east_x, ai["z"])
        link(en, ai["id"] + "_w", abs(east_x - ai["xWest"]), ai["id"])
        link(en, ai["id"] + "_e", abs(east_x - ai["xEast"]), ai["id"])
        spine.append((en, ai["z"]))
    for k in range(len(spine) - 1):
        z0, z1 = spine[k][1], spine[k + 1][1]
        if any(_seg_crosses_rect(east_x, z0, east_x, z1, *rect[:4]) for rect in rects):
            continue
        link(spine[k][0], spine[k + 1][0], abs(z1 - z0), "east_spine")
    g = dict(graph)
    g["nodes"] = nodes
    g["adj"] = adj
    return g


def build_layout_analysis(semantic: dict, options: Optional[dict] = None) -> dict:
    """What-if: how much would an east cross-aisle cut total travel? (decision support)"""
    rows = _rows(semantic)
    graph = _build_aisle_graph(rows, semantic)
    if graph is None:
        return {"ok": False, "error": "Could not derive an aisle network."}
    reg = _endpoints(rows, semantic, graph)
    forklifts = [e["id"] for e in reg.values() if e["kind"] == "forklift"]
    racks = [e["id"] for e in reg.values() if e["kind"] == "rack_row"]
    pairs = [(f, r) for f in forklifts for r in racks]
    pairs += [(racks[i], racks[j]) for i in range(len(racks)) for j in range(i + 1, len(racks))]

    candidate = _candidate_with_east_spine(graph, rows)
    base_total = cand_total = 0.0
    n = 0
    for sid, eid in pairs:
        b = _route_cost(graph, reg, sid, eid)
        c = _route_cost(candidate, reg, sid, eid)
        if math.isfinite(b) and math.isfinite(c):
            base_total += b
            cand_total += c
            n += 1
    reduction = (base_total - cand_total) / base_total if base_total > 0 else 0.0
    pct = round(reduction * 100, 1)
    return {
        "ok": True,
        "currentCrossAisles": 1,
        "crossAisleIds": ["west_spine"],
        "odPairsEvaluated": n,
        "baselineTotalMeters": round(base_total, 1),
        "withEastCrossAisleTotalMeters": round(cand_total, 1),
        "reductionPercent": pct,
        "headline": (f"This layout has one cross-aisle (west). Adding an east cross-aisle would cut "
                     f"total travel ~{round(pct)}% across {n} representative routes."),
        "note": ("Estimated by re-routing all forklift->rack and rack->rack pairs with a hypothetical "
                 "east cross-aisle added; distance-based, single assumed forklift speed."),
    }
