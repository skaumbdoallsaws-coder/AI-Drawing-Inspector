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
