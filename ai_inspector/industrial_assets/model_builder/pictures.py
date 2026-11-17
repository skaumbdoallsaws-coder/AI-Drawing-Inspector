"""Build-only contact sheets. Import previews retain their original renderer path."""
from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .imports import module


def _linear_color(value):
    rgb = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]


def _scene(model, appearance_colors):
    geometry = module("preview_geometry")
    materials = []
    for original in model.materials:
        material = dict(original)
        if material.get("artwork") and material.get("emissiveTexture") is not None:
            # The print texture is the emitted image. A constant emissive term
            # would turn light colors white and destroy the lettering.
            material["unlit"] = True
            material["emissive"] = [0, 0, 0]
        elif material.get("defaultFinish"):
            finish = material["defaultFinish"]
            color = finish.get("color") or appearance_colors.get(finish["appearanceId"])
            if color:
                material["baseColor"] = _linear_color(color) + [material["baseColor"][3]]
        materials.append(material)
    return geometry.build_geometry(replace(model, materials=materials))


def _bounds(model, indices):
    selected = [model.parts[i] for i in indices]
    if not selected:
        raise ValueError("Empty focus selection")
    low = np.min([p.positions.min(axis=0) for p in selected], axis=0).astype(np.float64)
    high = np.max([p.positions.max(axis=0) for p in selected], axis=0).astype(np.float64)
    return low, high


def _box(low, high, origin, scale):
    return np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1])
                     for z in (low[2], high[2])], dtype=np.float64).astype(np.float32) / scale - origin / scale


def _screen(point, origin, scene, basis, center, factor, size):
    local = (np.asarray(point, dtype=np.float64) - origin) / scene.scale
    projected = local @ basis
    return (size / 2 + (projected[0] - center[0]) * factor,
            size / 2 - (projected[1] - center[1]) * factor)


def _front_arrow(draw, origin, scene, basis, center, factor, low, high, size):
    length = min(.25, max(.06, scene.scale * .12))
    x = high[0] + min(.05, scene.scale * .03)
    z = (low[2] + high[2]) / 2
    start = _screen((x, 0, z-length/2), origin, scene, basis, center, factor, size)
    end = _screen((x, 0, z+length/2), origin, scene, basis, center, factor, size)
    color = (22, 84, 169)
    draw.line((start, end), fill=color, width=3)
    draw.ellipse((end[0]-4, end[1]-4, end[0]+4, end[1]+4), fill=color)
    draw.text((end[0]+5, end[1]-8), "FRONT", fill=color, font=ImageFont.load_default())


def _person(draw, origin, scene, basis, center, factor, low, size):
    z = low[2] - max(.2, scene.scale * .08)
    x = (low[0] + origin[0]) / 2
    # A 1.75 m figure standing on the floor (y = 0), arms down: neck, shoulders, hip, feet, hands.
    points = [(x, 1.55, z), (x, 1.42, z), (x, .9, z), (x, 0, z-.15), (x, 0, z+.15),
              (x, .85, z-.25), (x, .85, z+.25)]
    pts = [_screen(p, origin, scene, basis, center, factor, size) for p in points]
    ink = (35, 78, 112)
    for a, b in ((0, 2), (2, 3), (2, 4), (1, 5), (1, 6)):
        draw.line((pts[a], pts[b]), fill=ink, width=2)
    left = _screen((x, 1.55, z-.1), origin, scene, basis, center, factor, size)
    right = _screen((x, 1.75, z+.1), origin, scene, basis, center, factor, size)
    draw.ellipse((min(left[0], right[0]), min(left[1], right[1]),
                  max(left[0], right[0]), max(left[1], right[1])), outline=ink, width=2)


def render_previews(model, *, appearance_colors=None, focus_indices=None, thumbnail=True):
    """Render four views; focus changes the camera framing, never crops pixels."""
    preview = module("preview")
    raster = module("preview_raster")
    appearance_colors = appearance_colors or {}
    scene = _scene(model, appearance_colors)
    low, high = _bounds(model, range(len(model.parts)))
    origin = np.array([(low[0]+high[0])/2, low[1], (low[2]+high[2])/2], dtype=np.float64)
    focused = focus_indices is not None
    if focused:
        focus_low, focus_high = _bounds(model, focus_indices)
        focus_low -= .1
        focus_high += .1
        frame = _box(focus_low, focus_high, origin, scene.scale)
    else:
        if low[1] > 0:
            ground_low = low.copy()
            ground_low[1] = 0
            frame = _box(ground_low, high, origin, scene.scale)
        else:
            frame = None
    cache = raster.TextureCache(model.images)
    with Image.new("RGB", preview.SHEET_SIZE, raster.BACKGROUND) as sheet:
        font = ImageFont.load_default()
        thumb = None
        for index, (label, direction) in enumerate(preview.VIEWS):
            view_frame = frame
            if not focused and index == 1 and scene.dimensions[1] > .5:
                side_low = low.copy()
                side_high = high.copy()
                side_low[1] = min(side_low[1], 0)
                side_low[2] -= max(.45, scene.scale * .16)
                side_high[1] = max(side_high[1], 1.75)
                view_frame = _box(side_low, side_high, origin, scene.scale)
            pixels = raster.rasterize(scene, model.images, direction, preview.VIEW_SIZE,
                                      True, cache, frame_box=view_frame)
            with Image.fromarray(pixels) as view:
                draw = ImageDraw.Draw(view)
                _, basis, center, factor, _ = raster._projection(scene, direction, preview.VIEW_SIZE, view_frame)
                if not focused and index == 1 and scene.dimensions[1] > .5:
                    _person(draw, origin, scene, basis, center, factor, low, preview.VIEW_SIZE)
                if not focused and index == 3:
                    _front_arrow(draw, origin, scene, basis, center, factor, low, high, preview.VIEW_SIZE)
                if index == 3 and thumbnail:
                    thumb = preview._thumbnail(view)
                draw.text((10, 8), label, fill=(45, 54, 64), font=font)
                sheet.paste(view, ((index % 2) * preview.VIEW_SIZE, (index // 2) * preview.VIEW_SIZE))
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((0, 728, 767, 767), fill=raster.BACKGROUND)
        width, height, depth = scene.dimensions
        draw.text((10, 731), f"W {width:.4g} m    D {depth:.4g} m    H {height:.4g} m",
                  fill=(45, 54, 64), font=font)
        draw.text((10, 749), "preview (approximate)", fill=(65, 74, 84), font=font)
        return preview.PreviewImages(preview._png(sheet), thumb, scene.shown, scene.total)
