"""A picture of a basic-shape model for Sage (docs/sage-basic-shapes-plan.md, BS3).

author_shape_asset returns it beside its JSON result. The model is drawn as the 3D view would show it, without a
browser: flat-shaded triangles through a depth buffer, seen from the front-right and above with a parallel projection,
drawn at twice the size and reduced for smooth edges. A long model (a 40 m barrier, a 300 m girder) would
be a hairline at full length, so its first stretch is shown close up instead and the result says how long it is.
"""
from __future__ import annotations

import io
import math
from typing import Sequence

import numpy as np
from PIL import Image

from .primitives import Finish, Part, bounds

SIZE = (640, 400)
SUPERSAMPLE = 2
MARGIN = 0.08                      # of the picture, on every side
BACKGROUND = (236, 239, 242)
CAMERA = (0.55, 0.62, 1.0)         # from the model towards the camera: front-right (+x, +z) and above
LIGHT = (0.35, 1.0, 0.55)          # towards the light
AMBIENT, DIFFUSE = 0.48, 0.55
CLOSE_UP = 5.0                     # a model longer than 5 times its height and depth shows its first stretch
QUALITY = 88


def _unit(vector) -> np.ndarray:
    array = np.asarray(vector, dtype=float)
    return array / np.linalg.norm(array)


def _srgb(color: str) -> np.ndarray:
    return np.array([int(color[index:index + 2], 16) for index in (1, 3, 5)], dtype=float)


def _triangles(parts: Sequence[Part]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Every triangle's corners (n, 3, 3), its shading normal (n, 3), its colour (n, 3) and whether it glows (n)."""
    corners, normals, colors, glows = [], [], [], []
    for _, mesh, finish in parts:
        if not mesh.indices:
            continue
        positions = np.asarray(mesh.positions, dtype=float)
        vertex_normals = np.asarray(mesh.normals, dtype=float)
        index = np.asarray(mesh.indices, dtype=np.int64).reshape(-1, 3)
        color = finish.color if isinstance(finish, Finish) else finish
        lit = isinstance(finish, Finish) and any(finish.fields.get("emissiveFactor") or [])
        corners.append(positions[index])
        normals.append(vertex_normals[index].mean(axis=1))
        colors.append(np.repeat(_srgb(color)[None, :], len(index), axis=0))
        glows.append(np.full(len(index), lit))
    if not corners:
        raise ValueError("The model has no geometry")
    return np.concatenate(corners), np.concatenate(normals), np.concatenate(colors), np.concatenate(glows)


def _clip_far(polygon: list[np.ndarray], limit: float) -> list[np.ndarray]:
    """The part of a polygon with x at most `limit` (one Sutherland-Hodgman pass)."""
    kept = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        inside_now, inside_before = current[0] <= limit, previous[0] <= limit
        if inside_now != inside_before:
            share = (limit - previous[0]) / (current[0] - previous[0])
            kept.append(previous + (current - previous) * share)
        if inside_now:
            kept.append(current)
    return kept


def _rasterize(screen: np.ndarray, paints: np.ndarray, width: int, height: int) -> np.ndarray:
    """Flat triangles (n, 3, [x, y, depth]) in pixels through a depth buffer: the nearest surface wins at every
    pixel, where overlapping boards or rails would fool a far-to-near drawing order."""
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:] = BACKGROUND
    nearest = np.full((height, width), np.inf)
    for (x0, y0, d0), (x1, y1, d1), (x2, y2, d2), paint in zip(screen[:, 0], screen[:, 1], screen[:, 2], paints):
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue
        west, east = max(int(math.floor(min(x0, x1, x2))), 0), min(int(math.ceil(max(x0, x1, x2))), width - 1)
        north, south = max(int(math.floor(min(y0, y1, y2))), 0), min(int(math.ceil(max(y0, y1, y2))), height - 1)
        if west > east or north > south:
            continue
        xs, ys = np.meshgrid(np.arange(west, east + 1) + 0.5, np.arange(north, south + 1) + 0.5)
        w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
        w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
        w2 = 1.0 - w0 - w1
        depth = w0 * d0 + w1 * d1 + w2 * d2
        window = nearest[north:south + 1, west:east + 1]
        drawn = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6) & (depth < window)
        window[drawn] = depth[drawn]
        image[north:south + 1, west:east + 1][drawn] = paint
    return image


def render(parts: Sequence[Part], size: tuple[int, int] = SIZE) -> tuple[bytes, dict]:
    """The JPEG bytes of the picture and what it shows: {"view", "shownLengthMeters" (a close-up only)}."""
    corners, normals, colors, glows = _triangles(parts)
    lo, hi = bounds(parts)
    length, cross = hi[0] - lo[0], max(hi[1] - lo[1], hi[2] - lo[2])
    window = None
    if length > CLOSE_UP * cross:
        window = max(CLOSE_UP * cross, 1.0)
    view = _unit(CAMERA)
    forward = -view
    right = _unit(np.cross(forward, (0.0, 1.0, 0.0)))
    up = np.cross(right, forward)
    geometric = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    facing = geometric @ view > 0                      # faces turned away from the camera are hidden anyway
    shade = AMBIENT + DIFFUSE * np.clip((normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True),
                                                             1e-12)) @ _unit(LIGHT), 0.0, 1.0)
    shade = np.where(glows, 1.0, shade)
    fills = np.clip(colors * shade[:, None], 0, 255).astype(int)
    triangles, paints = [], []
    for index in np.nonzero(facing)[0]:
        polygon = list(corners[index])
        if window is not None:
            if min(point[0] for point in polygon) > lo[0] + window:
                continue
            polygon = _clip_far(polygon, lo[0] + window)
            if len(polygon) < 3:
                continue
        points = np.asarray(polygon)
        projected = np.stack((points @ right, points @ up, points @ forward), axis=1)
        for k in range(1, len(projected) - 1):       # a clipped quad back into triangles
            triangles.append(projected[[0, k, k + 1]])
            paints.append(fills[index])
    if not triangles:
        raise ValueError("Nothing of the model faces the camera")
    triangles = np.asarray(triangles)
    (left, bottom), (right_edge, top) = triangles[:, :, :2].reshape(-1, 2).min(axis=0), \
        triangles[:, :, :2].reshape(-1, 2).max(axis=0)
    width, height = size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE
    scale = min(width * (1 - 2 * MARGIN) / max(right_edge - left, 1e-9),
                height * (1 - 2 * MARGIN) / max(top - bottom, 1e-9))
    screen = np.empty_like(triangles)
    screen[:, :, 0] = width / 2 + (triangles[:, :, 0] - (left + right_edge) / 2) * scale
    screen[:, :, 1] = height / 2 - (triangles[:, :, 1] - (bottom + top) / 2) * scale
    screen[:, :, 2] = triangles[:, :, 2]
    image = Image.fromarray(_rasterize(screen, np.asarray(paints, dtype=np.uint8), width, height))
    image = image.resize(size, Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=QUALITY)
    info = {"view": "from the front-right and above"}
    if window is not None:
        info["shownLengthMeters"] = round(min(window, length), 3)
    return out.getvalue(), info


def preview(name: str, parameters: dict | None = None) -> tuple[bytes, dict]:
    """The picture of a shape family's model with these parameters (shape_families.build_asset's model)."""
    from .shape_families import model
    return render(model(name, parameters))

