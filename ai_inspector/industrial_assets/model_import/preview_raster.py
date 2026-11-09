"""Orthographic depth-buffer previews with linear-light texture and alpha sampling."""
from collections import OrderedDict
from io import BytesIO

import numpy as np
from PIL import Image

from .validation import require

BACKGROUND = (236, 239, 242)
AMBIENT, DIFFUSE = .4, .6
LIGHT = np.array([.35, .8, .6], dtype=np.float32)
LIGHT /= np.linalg.norm(LIGHT)
_SRGB = np.arange(256, dtype=np.float32) / 255
LINEAR = np.where(_SRGB <= .04045, _SRGB / 12.92, ((_SRGB + .055) / 1.055) ** 2.4)


def to_srgb(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0, 1)
    encoded = np.where(value <= .0031308, value * 12.92, 1.055 * value ** (1 / 2.4) - .055)
    return np.rint(encoded * 255).astype(np.uint8)


class TextureCache:
    """At most four decoded 2048-square RGBA images (64 MiB), reused across views."""
    def __init__(self, images):
        self.images = images
        self.decoded = OrderedDict()

    def get(self, index):
        if index in self.decoded:
            self.decoded.move_to_end(index)
            return self.decoded[index]
        while len(self.decoded) >= 4:
            self.decoded.popitem(last=False)
        item = self.images[index]
        with Image.open(BytesIO(item.data)) as image:
            require(image.format in {"PNG", "JPEG"} and image.size == (item.width, item.height)
                    and max(image.size) <= 2048 and getattr(image, "n_frames", 1) == 1, "image_unsafe")
            with image.convert("RGBA") as rgba:
                pixels = np.array(rgba)
        self.decoded[index] = pixels
        return pixels


def _coordinates(values, size, mode):
    values = values.astype(np.float64)
    if mode == 10497:
        values %= 1
    elif mode == 33648:
        values = 1 - np.abs(values % 2 - 1)
    else:
        values = np.clip(values, 0, 1)
    coordinate = values * size - .5
    first = np.floor(coordinate).astype(np.int32)
    weight = (coordinate - first).astype(np.float32)
    second = first + 1
    if mode == 10497:
        first %= size
        second %= size
    else:
        first, second = np.clip(first, 0, size - 1), np.clip(second, 0, size - 1)
    return first, second, weight


def sample_texture(cache: TextureCache, texture: dict, uv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """glTF UV (0,0) addresses the image's top left; filter RGB in linear light."""
    pixels = cache.get(texture["image"])
    x0, x1, wx = _coordinates(uv[:, 0], pixels.shape[1], texture["wrapS"])
    y0, y1, wy = _coordinates(uv[:, 1], pixels.shape[0], texture["wrapT"])
    rgb = np.zeros((len(uv), 3), dtype=np.float32)
    alpha = np.zeros(len(uv), dtype=np.float32)
    for x, y, weight in ((x0, y0, (1 - wx) * (1 - wy)), (x1, y0, wx * (1 - wy)),
                         (x0, y1, (1 - wx) * wy), (x1, y1, wx * wy)):
        texels = pixels[y, x]
        rgb += LINEAR[texels[:, :3]] * weight[:, None]
        alpha += (texels[:, 3] / 255) * weight
    return rgb, alpha


def shade(shader, uv, light, cache, has_uv=True):
    base = np.array(shader["baseColor"], dtype=np.float32)
    if shader["texture"] is not None and has_uv:
        rgb, alpha = sample_texture(cache, shader["texture"], uv)
        rgb *= base[:3]
        alpha *= base[3]
    else:
        rgb = np.broadcast_to(base[:3], (len(uv), 3)).copy()
        alpha = np.full(len(uv), base[3], dtype=np.float32)
    if not shader["unlit"]:
        rgb *= np.asarray(light, dtype=np.float32).reshape(-1, 1)
    # This is a bounded LDR preview, not an exposure/HDR rendering pipeline.
    emissive = np.clip(np.asarray(shader["emissive"], dtype=np.float64), 0, 64).astype(np.float32)
    return np.clip(rgb + emissive, 0, 1), alpha


def _unit(value):
    result = np.asarray(value, dtype=np.float32)
    return result / np.linalg.norm(result)


def _projection(scene, direction, size):
    view = _unit(direction)
    forward = -view
    right = _unit(np.cross(forward, [0, 1, 0]))
    up = np.cross(right, forward)
    basis = np.stack((right, up, forward), axis=1)
    box = scene.box @ basis
    low, high = box[:, :2].min(axis=0), box[:, :2].max(axis=0)
    center = (low + high) / 2
    factor = min(size * .72 / max(float(high[0] - low[0]), 1e-12),
                 size * .72 / max(float(high[1] - low[1]), 1e-12))
    points = scene.corners @ basis
    points[:, :, 0] = size / 2 + (points[:, :, 0] - center[0]) * factor
    points[:, :, 1] = size / 2 - (points[:, :, 1] - center[1]) * factor
    return points, basis, center, factor, view


def _background(scene, basis, center, factor, size, grid):
    rgb = np.empty((size, size, 3), dtype=np.float32)
    rgb[:] = LINEAR[np.array(BACKGROUND)]
    depth = np.full((size, size), np.inf, dtype=np.float32)
    if not grid:
        return rgb, depth
    right, up, forward = basis[:, 0], basis[:, 1], basis[:, 2]
    if abs(float(forward[1])) < 1e-6:
        row = int(round(size / 2 + float(center[1]) * factor))
        if 0 <= row < size:
            rgb[row] = LINEAR[np.array([210, 217, 224])]
        return rgb, depth
    px = (np.arange(size, dtype=np.float32)[None, :] + .5 - size / 2) / factor + center[0]
    py = -(np.arange(size, dtype=np.float32)[:, None] + .5 - size / 2) / factor + center[1]
    ground_depth = -(right[1] * px + up[1] * py) / forward[1]
    gx = right[0] * px + up[0] * py + forward[0] * ground_depth
    gz = right[2] * px + up[2] * py + forward[2] * ground_depth
    visible = ((np.abs(gx) <= max(float(scene.dimensions[0] / scene.scale) * .65, .3))
               & (np.abs(gz) <= max(float(scene.dimensions[2] / scene.scale) * .65, .3)))
    spacing = .1 if float(scene.dimensions.max()) < 1.5 else .5
    step = spacing / scene.scale
    # Hide a subpixel grid instead of allocating billions of physical lines.
    if step * factor >= 2:
        dx = np.abs((gx / step + .5) % 1 - .5) * step
        dz = np.abs((gz / step + .5) % 1 - .5) * step
        on_line = (dx < .55 / factor) | (dz < .55 / factor)
        rgb[visible & on_line] = LINEAR[np.array([210, 217, 224])]
    depth[visible] = ground_depth[visible] + 1e-5
    return rgb, depth


def _top_left(a, b, sign):
    dx, dy = (b[:2] - a[:2]) * sign
    return dy < 0 or (dy == 0 and dx > 0)


def _draw_triangle(index, screen, scene, shade_values, flat_colors, cache, rgb, nearest, blend, boxes):
    points = screen[index]
    x0, y0, d0 = points[0]
    x1, y1, d1 = points[1]
    x2, y2, d2 = points[2]
    area = float((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0))
    if abs(area) <= 1e-10:
        return
    west, north, east, south = boxes[index]
    if west > east or north > south:
        return
    window = nearest[north:south + 1, west:east + 1]
    if min(d0, d1, d2) >= window.max():
        return
    xs = np.arange(west, east + 1, dtype=np.float32)[None, :] + .5
    ys = np.arange(north, south + 1, dtype=np.float32)[:, None] + .5
    w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
    w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
    w2 = 1 - w0 - w1
    sign = 1 if area > 0 else -1
    covered = np.ones(w0.shape, dtype=bool)
    for weight, a, b in ((w0, points[1], points[2]), (w1, points[2], points[0]), (w2, points[0], points[1])):
        covered &= (weight > 1e-7) | ((np.abs(weight) <= 1e-7) & _top_left(a, b, sign))
    depths = w0 * d0 + w1 * d1 + w2 * d2
    covered &= depths < window
    yy, xx = np.nonzero(covered)
    if not len(xx):
        return
    shader = scene.shaders[scene.materials[index]]
    if shader["texture"] is not None and scene.has_uv[index]:
        weights = np.stack((w0[yy, xx], w1[yy, xx], w2[yy, xx]), axis=1)
        uv = weights.astype(np.float64) @ scene.uv[index].astype(np.float64)
        colors, alpha = shade(shader, uv, [shade_values[index]], cache)
    else:
        colors = np.broadcast_to(flat_colors[index], (len(xx), 3))
        alpha = np.full(len(xx), shader["baseColor"][3], dtype=np.float32)
    if shader["alphaMode"] == "MASK":
        keep = alpha >= shader["alphaCutoff"]
        yy, xx, colors, alpha = yy[keep], xx[keep], colors[keep], alpha[keep]
    target = rgb[north:south + 1, west:east + 1]
    if blend:
        alpha = np.clip(alpha, 0, 1)[:, None]
        target[yy, xx] = colors * alpha + target[yy, xx] * (1 - alpha)
    else:
        target[yy, xx] = colors
        window[yy, xx] = depths[yy, xx]


def _splat_colors(indices, scene, shade_values, cache):
    colors = np.empty((len(indices), 3), dtype=np.float32)
    alpha = np.ones(len(indices), dtype=np.float32)
    uv = scene.uv[indices].mean(axis=1, dtype=np.float64)
    # Group shading by a shader and UV availability, without changing depth order.
    groups = scene.materials[indices] * 2 + scene.has_uv[indices]
    order = np.argsort(groups, kind="stable")
    starts = np.r_[0, np.flatnonzero(np.diff(groups[order])) + 1, len(indices)]
    for start, end in zip(starts[:-1], starts[1:]):
        rows = order[start:end]
        key = int(groups[rows[0]])
        shader = scene.shaders[key // 2]
        colors[rows], sampled_alpha = shade(shader, uv[rows], shade_values[indices[rows]], cache, bool(key % 2))
        if shader["alphaMode"] == "MASK":
            alpha[rows] = sampled_alpha >= shader["alphaCutoff"]
        elif shader["alphaMode"] == "BLEND":
            alpha[rows] = sampled_alpha
    return colors, np.clip(alpha, 0, 1)


def _splat(indices, centroids, colors, alpha, rgb, nearest, blend):
    if not len(indices):
        return
    sample = centroids[indices]
    xs, ys = np.floor(sample[:, 0]).astype(np.int32), np.floor(sample[:, 1]).astype(np.int32)
    size = len(nearest)
    valid = (xs >= 0) & (ys >= 0) & (xs < size) & (ys < size)
    indices, xs, ys, sample = indices[valid], xs[valid], ys[valid], sample[valid]
    valid = (sample[:, 2] < nearest[ys, xs]) & (alpha[indices] > 0)
    indices, xs, ys, sample = indices[valid], xs[valid], ys[valid], sample[valid]
    if not len(indices):
        return
    pixels = ys * size + xs
    if not blend:
        order = np.lexsort((indices, sample[:, 2], pixels))
        ordered_pixels = pixels[order]
        first = np.r_[True, ordered_pixels[1:] != ordered_pixels[:-1]]
        rows = order[first]
        rgb[ys[rows], xs[rows]] = colors[indices[rows]]
        nearest[ys[rows], xs[rows]] = sample[rows, 2]
        return
    # Incoming samples are already far-to-near. Stable grouping retains that
    # order, then segmented products compose every layer without a Python loop.
    order = np.argsort(pixels, kind="stable")
    pixels, ids = pixels[order], indices[order]
    starts = np.r_[0, np.flatnonzero(np.diff(pixels)) + 1]
    ends = np.r_[starts[1:] - 1, len(ids) - 1]
    counts = ends - starts + 1
    opacity = alpha[ids].astype(np.float64)
    prefix = np.cumsum(np.log1p(-np.minimum(opacity, 1 - 1e-12)))
    last = np.repeat(prefix[ends], counts)
    weight = opacity * np.exp(last - prefix)
    total_color = np.add.reduceat(colors[ids] * weight[:, None], starts)
    before = np.r_[0., prefix[starts[1:] - 1]]
    transmission = np.exp(prefix[ends] - before)
    flat = rgb.reshape(-1, 3)
    target = pixels[starts]
    flat[target] = total_color + flat[target] * transmission[:, None]


def rasterize(scene, images, direction=(0, 0, 1), size=384, grid=True, cache=None):
    cache = TextureCache(images) if cache is None else cache
    screen, basis, center, factor, view = _projection(scene, direction, size)
    rgb, nearest = _background(scene, basis, center, factor, size, grid)
    normal = scene.normals * np.where(scene.normals @ view < 0, -1, 1)[:, None]
    shade_values = AMBIENT + DIFFUSE * np.maximum(normal @ LIGHT, 0)
    bases = np.array([s["baseColor"][:3] for s in scene.shaders], dtype=np.float32)[scene.materials]
    emissions = np.clip(np.array([s["emissive"] for s in scene.shaders], dtype=np.float64), 0, 64)[scene.materials]
    unlit = np.array([s["unlit"] for s in scene.shaders])[scene.materials]
    flat_colors = np.clip(bases * np.where(unlit, 1, shade_values)[:, None] + emissions, 0, 1).astype(np.float32)
    low, high = screen[:, :, :2].min(axis=1), screen[:, :, :2].max(axis=1)
    small = np.all(high - low <= 2, axis=1)
    area = ((screen[:, 1, 0] - screen[:, 0, 0]) * (screen[:, 2, 1] - screen[:, 0, 1])
            - (screen[:, 1, 1] - screen[:, 0, 1]) * (screen[:, 2, 0] - screen[:, 0, 0]))
    active = np.abs(area) > 1e-10
    boxes = np.column_stack((np.maximum(np.floor(low), 0), np.minimum(np.ceil(high), size - 1))).astype(np.int32)
    centroid = screen.mean(axis=1)
    blend = np.array([s["alphaMode"] == "BLEND" for s in scene.shaders])[scene.materials]
    small_ids = np.flatnonzero(small & active)
    colors = np.zeros((len(screen), 3), dtype=np.float32)
    alpha = np.zeros(len(screen), dtype=np.float32)
    if len(small_ids):
        colors[small_ids], alpha[small_ids] = _splat_colors(small_ids, scene, shade_values, cache)
    opaque = np.flatnonzero(~small & ~blend & active)
    opaque = opaque[np.argsort(centroid[opaque, 2], kind="stable")]
    for index in opaque:
        _draw_triangle(index, screen, scene, shade_values, flat_colors, cache, rgb, nearest, False, boxes)
    _splat(np.flatnonzero(small & ~blend & active), centroid, colors, alpha, rgb, nearest, False)
    transparent = np.flatnonzero(blend & active)
    transparent = transparent[np.argsort(-centroid[transparent, 2], kind="stable")]
    # Interleave vectorized runs of splats with larger triangles in global depth order.
    large_positions = np.flatnonzero(~small[transparent])
    start = 0
    for position in large_positions:
        _splat(transparent[start:position], centroid, colors, alpha, rgb, nearest, True)
        _draw_triangle(transparent[position], screen, scene, shade_values, flat_colors, cache, rgb, nearest, True, boxes)
        start = position + 1
    _splat(transparent[start:], centroid, colors, alpha, rgb, nearest, True)
    return to_srgb(rgb)
