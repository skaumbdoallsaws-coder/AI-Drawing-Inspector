"""Four approximate views and a bounded thumbnail, rendered only inside the worker."""
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .errors import ModelImportError
from .model import Model
from .limits import PREVIEW_BYTES, THUMBNAIL_BYTES
from .preview_geometry import MAX_PREVIEW_TRIANGLES, build_geometry
from .preview_raster import BACKGROUND, TextureCache, rasterize
from .validation import require

VIEW_SIZE = 384
SHEET_SIZE = (768, 768)
VIEWS = (("Front", (0, 0, 1)), ("Side", (1, 0, 0)), ("Back", (0, 0, -1)),
         ("Three-quarter from above", (.65, .65, 1)))


@dataclass
class PreviewImages:
    preview: bytes
    thumbnail: bytes | None
    triangles_shown: int
    triangles_total: int


def render_view(model: Model, direction=(0, 0, 1), *, size: int = VIEW_SIZE, grid: bool = True) -> np.ndarray:
    """Small test/debug seam; the production sheet shares geometry and texture caches."""
    require(16 <= size <= VIEW_SIZE, "model_preview_failed")
    return rasterize(build_geometry(model), model.images, direction, size, grid)


def _png(sheet: Image.Image) -> bytes:
    with BytesIO() as stream:
        sheet.save(stream, format="PNG", compress_level=6)
        data = stream.getvalue()
    if len(data) > PREVIEW_BYTES:
        with sheet.quantize(colors=256, dither=Image.Dither.NONE) as reduced, BytesIO() as stream:
            reduced.save(stream, format="PNG", compress_level=6)
            data = stream.getvalue()
    require(len(data) <= PREVIEW_BYTES, "model_preview_failed")
    return data


def _thumbnail(image: Image.Image) -> bytes:
    with image.resize((256, 256), Image.Resampling.LANCZOS) as reduced:
        for quality in (80, 65, 50, 35):
            with BytesIO() as stream:
                reduced.save(stream, format="WEBP", quality=quality, method=4)
                data = stream.getvalue()
            if len(data) <= THUMBNAIL_BYTES:
                return data
    raise ModelImportError("model_preview_failed")


def render_previews(model: Model, *, source: bool = False, thumbnail: bool = True) -> PreviewImages:
    """At most 250k source triangles, chosen by world area; a full prepared model."""
    try:
        scene = build_geometry(model)
        if not source:
            require(scene.total <= MAX_PREVIEW_TRIANGLES, "model_output_too_complex")
        cache = TextureCache(model.images)
        with Image.new("RGB", SHEET_SIZE, BACKGROUND) as sheet:
            font = ImageFont.load_default()
            thumbnail_bytes = None
            for index, (label, direction) in enumerate(VIEWS):
                pixels = rasterize(scene, model.images, direction, VIEW_SIZE, True, cache)
                with Image.fromarray(pixels) as view:
                    if index == 3 and thumbnail:
                        thumbnail_bytes = _thumbnail(view)
                    ImageDraw.Draw(view).text((10, 8), label, fill=(45, 54, 64), font=font)
                    sheet.paste(view, ((index % 2) * VIEW_SIZE, (index // 2) * VIEW_SIZE))
            draw = ImageDraw.Draw(sheet)
            draw.rectangle((0, 728, 767, 767), fill=BACKGROUND)
            width, height, depth = scene.dimensions
            dimensions = f"W {width:.4g} m    D {depth:.4g} m    H {height:.4g} m"
            draw.text((10, 731), dimensions, fill=(45, 54, 64), font=font)
            label = "preview (approximate)"
            if source and scene.shown < scene.total:
                label += " - largest 250k triangles shown"
            draw.text((10, 749), label, fill=(65, 74, 84), font=font)
            return PreviewImages(_png(sheet), thumbnail_bytes, scene.shown, scene.total)
    except ModelImportError:
        raise
    except (OSError, ValueError, OverflowError, IndexError):
        raise ModelImportError("model_preview_failed") from None
