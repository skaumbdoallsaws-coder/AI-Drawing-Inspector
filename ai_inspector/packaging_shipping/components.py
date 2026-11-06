"""Analytic top-open insert pockets; no arbitrary negative product geometry."""
from __future__ import annotations

import math

TOLERANCE_M = 1e-6


def pocket_volume(pocket):
    x, y, z = pocket.dimensions_m
    return x * y * z if pocket.shape == "rectangular" else math.pi * (x / 2) ** 2 * y


def _footprint_distance(a, b):
    ax, _, az = a.position_m
    bx, _, bz = b.position_m
    aw, _, ad = a.dimensions_m
    bw, _, bd = b.dimensions_m
    if a.shape == b.shape == "cylindrical":
        return math.hypot(ax + aw / 2 - bx - bw / 2, az + ad / 2 - bz - bd / 2) - (aw + bw) / 2
    if a.shape == "cylindrical" or b.shape == "cylindrical":
        circle, rectangle = (a, b) if a.shape == "cylindrical" else (b, a)
        x, _, z = circle.position_m
        radius = circle.dimensions_m[0] / 2
        x, z = x + radius, z + radius
        rx, _, rz = rectangle.position_m
        rw, _, rd = rectangle.dimensions_m
        return math.hypot(max(rx - x, 0, x - rx - rw), max(rz - z, 0, z - rz - rd)) - radius
    dx, dz = max(ax - bx - bw, bx - ax - aw), max(az - bz - bd, bz - az - ad)
    return math.hypot(max(dx, 0), max(dz, 0)) if dx >= 0 or dz >= 0 else max(dx, dz)


def insert_geometry(insert):
    findings = []
    for index, pocket in enumerate(insert.pockets):
        lower, size, block = pocket.position_m, pocket.dimensions_m, insert.dimensions_m
        if any(lower[a] < insert.minimum_wall_m - TOLERANCE_M
               or lower[a] + size[a] > block[a] - insert.minimum_wall_m + TOLERANCE_M for a in (0, 2)):
            findings.append(("pocket_wall_thin", "Pocket violates the required side-wall thickness."))
        if lower[1] < insert.minimum_floor_m - TOLERANCE_M:
            findings.append(("pocket_floor_thin", "Pocket violates the required remaining floor thickness."))
        if abs(lower[1] + size[1] - block[1]) > TOLERANCE_M:
            findings.append(("pocket_not_top_open", "Supported insert pockets must open exactly at the positive-Y face."))
        for previous in insert.pockets[:index]:
            if _footprint_distance(pocket, previous) < insert.minimum_wall_m - TOLERANCE_M:
                findings.append(("pocket_web_thin", "Pockets overlap or leave less than the required material between them."))
    gross = math.prod(insert.dimensions_m)
    removed = sum(pocket_volume(pocket) for pocket in insert.pockets)
    if removed >= gross:
        findings.append(("insert_volume_invalid", "Pocket subtraction leaves no positive insert volume."))
    return {"valid": not findings, "gross_volume_m3": gross, "removed_volume_m3": removed,
            "net_volume_m3": None if findings else gross - removed, "findings": findings,
            "basis": "analytic_nonoverlapping_top_open_pockets" if insert.pockets else "analytic_rectangular_solid"}


def _inside_void(bounds, insert, pocket):
    lower = tuple(insert.position_m[a] + pocket.position_m[a] for a in range(3))
    upper = tuple(lower[a] + pocket.dimensions_m[a] for a in range(3))
    if any(bounds[0][a] < lower[a] - TOLERANCE_M or bounds[1][a] > upper[a] + TOLERANCE_M for a in range(3)):
        return False
    if pocket.shape == "rectangular":
        return True
    radius = pocket.dimensions_m[0] / 2
    cx, cz = lower[0] + radius, lower[2] + radius
    return all(math.hypot(x - cx, z - cz) <= radius + TOLERANCE_M
               for x in (bounds[0][0], bounds[1][0]) for z in (bounds[0][2], bounds[1][2]))


def intersects_insert_material(bounds, insert):
    """Conservatively test a product envelope against a valid analytic insert."""
    lower = tuple(max(bounds[0][a], insert.position_m[a]) for a in range(3))
    upper = tuple(min(bounds[1][a], insert.position_m[a] + insert.dimensions_m[a]) for a in range(3))
    if any(upper[a] - lower[a] <= TOLERANCE_M for a in range(3)):
        return False
    if not insert_geometry(insert)["valid"]:
        return True
    return not any(_inside_void((lower, upper), insert, pocket) for pocket in insert.pockets)


CUSHION_WORK_LIMIT = 200_000  # face cells x material pieces for one product face


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def foam_along(bounds, valid_inserts, axis, toward_max, inner):
    """Least insert material crossed between one product face and its carton wall, in metres.

    The ray runs along `axis` from the product face to the wall, over the whole face.
    Pass only inserts that `insert_geometry` accepts; invalid ones provide no material.
    Pocket voids are subtracted, and a cylindrical pocket is bounded by its square prism,
    so material can be undercounted but never overcounted. Returns None when the face
    is too detailed to check within the work limit.
    """
    lo, hi = bounds
    start, end = (hi[axis], inner[axis]) if toward_max else (0.0, lo[axis])
    if end - start <= TOLERANCE_M:
        return 0.0
    u, v = (k for k in range(3) if k != axis)
    pieces = []
    for insert in valid_inserts:
        b0 = insert.position_m
        b1 = tuple(b0[k] + insert.dimensions_m[k] for k in range(3))
        along = _overlap(b0[axis], b1[axis], start, end)
        if along <= TOLERANCE_M or _overlap(b0[u], b1[u], lo[u], hi[u]) <= 0 or _overlap(b0[v], b1[v], lo[v], hi[v]) <= 0:
            continue
        pieces.append((b0[u], b1[u], b0[v], b1[v], along))
        for pocket in insert.pockets:
            p0 = tuple(b0[k] + pocket.position_m[k] for k in range(3))
            p1 = tuple(p0[k] + pocket.dimensions_m[k] for k in range(3))
            gone = _overlap(p0[axis], p1[axis], start, end)
            if gone > 0 and _overlap(p0[u], p1[u], lo[u], hi[u]) > 0 and _overlap(p0[v], p1[v], lo[v], hi[v]) > 0:
                pieces.append((p0[u], p1[u], p0[v], p1[v], -gone))
    if not pieces:
        return 0.0
    us = sorted({lo[u], hi[u], *(x for p in pieces for x in p[0:2] if lo[u] < x < hi[u])})
    vs = sorted({lo[v], hi[v], *(x for p in pieces for x in p[2:4] if lo[v] < x < hi[v])})
    if (len(us) - 1) * (len(vs) - 1) * len(pieces) > CUSHION_WORK_LIMIT:
        return None
    least = None
    for i in range(len(us) - 1):
        cu = (us[i] + us[i + 1]) / 2
        for j in range(len(vs) - 1):
            cv = (vs[j] + vs[j + 1]) / 2
            total = sum(p[4] for p in pieces if p[0] <= cu <= p[1] and p[2] <= cv <= p[3])
            least = total if least is None else min(least, total)
    return max(0.0, least)


def contact_evidence(bounds, insert):
    """Only geometric support evidence, never a foam load/cushioning rating."""
    if not insert_geometry(insert)["valid"]:
        return False
    bottom = bounds[0][1]
    candidates = [insert.position_m[1] + insert.dimensions_m[1]]
    candidates.extend(insert.position_m[1] + p.position_m[1] for p in insert.pockets)
    if not any(abs(bottom - level) <= TOLERANCE_M for level in candidates):
        return False
    sample = ((bounds[0][0], bottom - 1e-4, bounds[0][2]),
              (bounds[1][0], bottom - 2 * TOLERANCE_M, bounds[1][2]))
    return intersects_insert_material(sample, insert)
