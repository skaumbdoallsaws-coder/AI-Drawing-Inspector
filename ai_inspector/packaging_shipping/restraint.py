"""Predicted translational clearance of each placed product under the bounding-box model; never protection.

For every product envelope and each of six directions, the distance the envelope can translate before any
part of its face meets insert material, another product's envelope or a carton wall, and what it meets.
Envelopes are bounding boxes and move rigidly without rotating; product shape, friction and foam
compression are not modelled. A cylindrical pocket counts as its square prism, so material is undercounted
and travel overstated, never the reverse. Rotation, foam compression and shipping protection remain
unverified; a passing result is not validated transport protection.
"""
from __future__ import annotations

TOLERANCE_M = 1e-6
WORK_LIMIT = 200_000  # face cells x obstacle boxes (pockets included) for one product face
TOTAL_WORK_LIMIT = 1_000_000  # the same, summed over every face in one assessment; later faces stay unchecked
DIRECTIONS = (("-x", 0, False), ("+x", 0, True), ("-y", 1, False), ("+y", 1, True), ("-z", 2, False), ("+z", 2, True))


def _box(position, dimensions):
    return tuple(position), tuple(p + d for p, d in zip(position, dimensions))


def _overlaps(box, lo, hi, u, v):
    """True when a box overlaps the face's (u, v) rectangle by more than the tolerance. A neighbour that only
    touches the face's edge is not ahead of it; counting its float sliver would stop the face at 0 mm."""
    return (box[0][u] < hi[u] - TOLERANCE_M and box[1][u] > lo[u] + TOLERANCE_M
            and box[0][v] < hi[v] - TOLERANCE_M and box[1][v] > lo[v] + TOLERANCE_M)


def _cuts(lo, hi, values):
    """Cell boundaries across [lo, hi]: the ends plus every edge more than the tolerance from the ends and the last cut."""
    out = [lo]
    for x in sorted(values):
        if out[-1] + TOLERANCE_M < x < hi - TOLERANCE_M:
            out.append(x)
    return out + [hi]


def _material(insert):
    """(insert box, pocket boxes in carton axes) for a valid analytic insert."""
    box = _box(insert.position_m, insert.dimensions_m)
    pockets = [_box(tuple(insert.position_m[k] + p.position_m[k] for k in range(3)), p.dimensions_m) for p in insert.pockets]
    return box, pockets


def _intervals(box, pockets, axis, u, v, cu, cv):
    """Material along `axis` through the line at (cu, cv): the insert span minus every pocket it crosses."""
    lo, hi = box
    if not (lo[u] < cu < hi[u] and lo[v] < cv < hi[v]):
        return []
    spans = [(lo[axis], hi[axis])]
    for p0, p1 in pockets:
        if not (p0[u] < cu < p1[u] and p0[v] < cv < p1[v]):
            continue
        cut = []
        for a, b in spans:
            if p1[axis] <= a or p0[axis] >= b:
                cut.append((a, b))
                continue
            if p0[axis] > a:
                cut.append((a, p0[axis]))
            if p1[axis] < b:
                cut.append((p1[axis], b))
        spans = cut
    return [(a, b) for a, b in spans if b - a > TOLERANCE_M]


def _distance(spans, face, toward_max):
    """Gap from the face to the first material span ahead of it (0 when material already touches the face)."""
    best = None
    for a, b in spans:
        if toward_max:
            if b <= face + TOLERANCE_M:
                continue
            d = max(0.0, a - face)
        else:
            if a >= face - TOLERANCE_M:
                continue
            d = max(0.0, face - b)
        best = d if best is None else min(best, d)
    return best


def travel(bounds, axis, toward_max, inner, materials, others, budget=None):
    """Predicted translational clearance of one envelope in one direction (bounding-box model).

    materials: [(id, insert box, pocket boxes)], others: [(id, product box)], budget: an optional one-item list
    of work left, shared across faces. Returns a dict with travel_m, stops (kinds met at that distance:
    insert, product, carton_wall), stop_ids, contact_area_m2 and face_area_m2, or None when the face is too
    detailed to check within the work limits.
    """
    lo, hi = bounds
    u, v = (k for k in range(3) if k != axis)
    face = hi[axis] if toward_max else lo[axis]
    wall = (inner[axis] - hi[axis]) if toward_max else lo[axis]
    ahead = [(oid, box, pockets) for oid, box, pockets in materials if _overlaps(box, lo, hi, u, v)]
    near = [(oid, box) for oid, box in others if _overlaps(box, lo, hi, u, v)]
    boxes = [b for _, box, pockets in ahead for b in (box, *pockets)] + [box for _, box in near]
    us = _cuts(lo[u], hi[u], [x for b in boxes for x in (b[0][u], b[1][u])])
    vs = _cuts(lo[v], hi[v], [x for b in boxes for x in (b[0][v], b[1][v])])
    work = (len(us) - 1) * (len(vs) - 1) * (len(boxes) + 1)
    if work > WORK_LIMIT or (budget is not None and work > budget[0]):
        return None
    if budget is not None:
        budget[0] -= work
    cells = []  # (distance, area, [(kind, id)])
    for i in range(len(us) - 1):
        cu, du = (us[i] + us[i + 1]) / 2, us[i + 1] - us[i]
        for j in range(len(vs) - 1):
            cv, dv = (vs[j] + vs[j + 1]) / 2, vs[j + 1] - vs[j]
            hits = [(max(0.0, wall), "carton_wall", "carton")]
            for oid, box, pockets in ahead:
                d = _distance(_intervals(box, pockets, axis, u, v, cu, cv), face, toward_max)
                if d is not None:
                    hits.append((d, "insert", oid))
            for oid, box in near:
                if box[0][u] < cu < box[1][u] and box[0][v] < cv < box[1][v]:
                    d = (box[0][axis] - hi[axis]) if toward_max else (lo[axis] - box[1][axis])
                    if d >= -TOLERANCE_M:
                        hits.append((max(0.0, d), "product", oid))
            least = min(h[0] for h in hits)
            cells.append((least, du * dv, [(kind, oid) for d, kind, oid in hits if d <= least + TOLERANCE_M]))
    distance = min(c[0] for c in cells)
    touching = [c for c in cells if c[0] <= distance + TOLERANCE_M]
    met = sorted({pair for c in touching for pair in c[2]})
    return {"travel_m": round(distance, 9), "stops": sorted({kind for kind, _ in met}), "stop_ids": [oid for _, oid in met],
            "contact_area_m2": round(sum(c[1] for c in touching), 12), "face_area_m2": round((hi[u] - lo[u]) * (hi[v] - lo[v]), 12)}


def package_restraint(package_id, boxes, valid_inserts, inner, budget=None):
    """Rows for every product envelope in one package. boxes: [(item id, envelope)]; budget as for travel()."""
    materials = [(x.id, *_material(x)) for x in valid_inserts]
    rows = []
    for item_id, bounds in boxes:
        others = [(oid, box) for oid, box in boxes if oid != item_id]
        directions, verified = {}, True
        for name, axis, toward_max in DIRECTIONS:
            found = travel(bounds, axis, toward_max, inner, materials, others, budget)
            if found is None:
                verified = False
            directions[name] = found
        known = {k: d for k, d in directions.items() if d is not None}
        worst = max(known.items(), key=lambda kv: kv[1]["travel_m"]) if known else None
        rows.append({"package_id": package_id, "item_id": item_id, "verified": verified, "directions": directions,
                     "max_travel_m": worst[1]["travel_m"] if worst else None, "max_travel_direction": worst[0] if worst else None,
                     "reaches_products": sorted({oid for d in known.values() if "product" in d["stops"]
                                                 for oid in d["stop_ids"] if oid in {o for o, _ in others}})})
    return rows
