"""Conservative whole-model footprints and catalog-shaped explicit supports."""
import numpy as np

from .transforms import bounds
from .validation import require


def _hull(points):
    points = np.unique(points, axis=0)
    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    def half(values):
        result = []
        for point in values:
            while len(result) >= 2 and cross(result[-2], result[-1], point) <= 0:
                result.pop()
            result.append(point)
        return result
    return np.array(half(points)[:-1] + half(points[::-1])[:-1], dtype=float)


def _clip(polygon, a, b):
    edge = b - a
    # Expand a half-plane slightly; dropping planes must never reduce the true hull.
    epsilon = max(1, float(np.linalg.norm(edge))) * 1e-12
    def distance(p):
        delta = p - a
        return edge[0] * delta[1] - edge[1] * delta[0] + epsilon
    result = []
    previous, dp = polygon[-1], distance(polygon[-1])
    for current in polygon:
        dc = distance(current)
        if (dp >= 0) != (dc >= 0):
            result.append(previous + (current - previous) * dp / (dp - dc))
        if dc >= 0:
            result.append(current)
        previous, dp = current, dc
    return result


def footprint(parts, mode="hull"):
    low, high = bounds(parts)
    rectangle = [np.array([x, z]) for x, z in ((low[0], low[2]), (high[0], low[2]),
                                              (high[0], high[2]), (low[0], high[2]))]
    if mode == "box":
        polygon = rectangle
    else:
        hull = _hull(np.concatenate([p.positions[:, [0, 2]] for p in parts]))
        require(len(hull) >= 3, "model_dimensions_invalid")
        if len(hull) <= 32:
            polygon = hull
        else:
            # Intersect the bounding rectangle with 28 evenly spaced hull planes.
            # At most 32 edges; omitting the other planes enlarges the hull.
            polygon = rectangle
            for i in (np.arange(28) * len(hull) // 28):
                polygon = _clip(polygon, hull[i], hull[(i + 1) % len(hull)])
            polygon = _hull(np.asarray(polygon))
    require(3 <= len(polygon) <= 32, "model_dimensions_invalid")
    points = np.asarray(polygon)
    edges = np.roll(points, -1, axis=0) - points
    turns = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
    if not np.any(turns > 1e-9):
        # The binder ignores smaller turns; a conservative box remains convex
        # at its tolerance when an extremely small detailed hull would not.
        points = np.asarray(rectangle)
    area = .5 * float(np.sum(points[:, 0] * np.roll(points[:, 1], -1)
                              - points[:, 1] * np.roll(points[:, 0], -1)))
    # The catalog rejects footprints at or below its 1e-9 area tolerance.
    require(area > 1e-9, "model_dimensions_invalid")
    return [[{"x": float(p[0]), "z": float(p[1])} for p in points]]


def support_surfaces(recipe, dimensions):
    output = []
    for surface in recipe["surfaces"]:
        x0, z0, x1, z1 = surface["rect"]
        require(-dimensions["width"] / 2 - 1e-7 <= x0 < x1 <= dimensions["width"] / 2 + 1e-7
                and -dimensions["depth"] / 2 - 1e-7 <= z0 < z1 <= dimensions["depth"] / 2 + 1e-7
                and 0 <= surface["height"] <= dimensions["height"] + 1e-7, "recipe_invalid")
        output.append({
            "surfaceId": surface["id"], "label": surface["label"],
            "localFrame": {"origin": {"x": (x0 + x1) / 2, "y": surface["height"], "z": (z0 + z1) / 2},
                           "xAxis": {"x": 1, "y": 0, "z": 0}, "zAxis": {"x": 0, "y": 0, "z": 1},
                           "normal": {"x": 0, "y": 1, "z": 0}},
            "bounds": {"minimumX": -(x1 - x0) / 2, "maximumX": (x1 - x0) / 2,
                       "minimumZ": -(z1 - z0) / 2, "maximumZ": (z1 - z0) / 2},
            "allowedSides": ["above"], "evidenceStatus": "authored",
        })
    return output
