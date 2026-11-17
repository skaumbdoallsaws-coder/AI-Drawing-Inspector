"""Bounded Pillow panel artwork. All coordinates are fractions, with v down."""
from collections import OrderedDict
from dataclasses import dataclass, replace
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .budgets import panel_pixels
from .errors import require
from .job_io import font_bytes
from .print_contract import BarcodeRandom, MAX_FONT_SIZE, MIN_FONT_SIZE, outside_panel
from .recipe import PRINT_CODEPOINTS


# The tallest and deepest ASCII glyphs; every covered character's ink lies within their vertical extent.
LINE_REFERENCE = "Hbdfhklt|()[]{}gjpqy_"


@dataclass
class PrintedFace:
    data: bytes
    width: int
    height: int
    text_metrics: list
    clipped: list


class Fonts:
    def __init__(self, directory=None):
        self.data = font_bytes(directory)
        self.cache = OrderedDict()

    def get(self, size):
        if size not in self.cache:
            # BASIC avoids machine-dependent optional libraqm shaping.
            self.cache[size] = ImageFont.truetype(BytesIO(self.data), size=size,
                                                  layout_engine=ImageFont.Layout.BASIC)
            if len(self.cache) > 16:
                self.cache.popitem(last=False)
        self.cache.move_to_end(size)
        return self.cache[size]


def _pixel_box(box, width, height):
    """Half-open integer pixels, clipped before allocating any drawing surface."""
    x0, y0, x1, y1 = (round(v*s) for v, s in zip(box, (width, height, width, height)))
    return max(0, x0), max(0, y0), min(width, x1), min(height, y1)


def _text(image, item, fonts, box):
    x0, y0, x1, y1 = (round(v*s) for v, s in zip(box, (*image.size, *image.size)))
    available = (x1-x0, y1-y0)
    measure = ImageDraw.Draw(image)
    def metrics(size):
        font = fonts.get(size)
        stroke = round(.04*size) if item["weight"] == "bold" else 0
        spacing = max(1, round(.2*size))
        bounds = measure.multiline_textbbox((0, 0), item["text"], font=font, spacing=spacing,
                                            align=item["align"], stroke_width=stroke)
        return font, stroke, spacing, bounds
    lines = item["text"].count("\n")+1
    def line_height(size):
        # The box height sets the type size the same way for any text with this many lines: rows with descenders
        # or brackets are not shrunk below their neighbours. Width still shrinks a line that is too long.
        font, stroke, spacing, _ = metrics(size)
        reference = measure.multiline_textbbox((0, 0), "\n".join([LINE_REFERENCE]*lines), font=font,
                                               spacing=spacing, stroke_width=stroke)
        return reference[3]-reference[1]
    low, high, best = MIN_FONT_SIZE, MAX_FONT_SIZE, MIN_FONT_SIZE
    while low <= high:
        middle = (low+high)//2
        *_, bounds = metrics(middle)
        if bounds[2]-bounds[0] <= available[0] and line_height(middle) <= available[1]:
            best, low = middle, middle+1
        else:
            high = middle-1
    font, stroke, spacing, bounds = metrics(best)
    # Centred/right lines give fractional boxes; widen to whole pixels.
    bounds = (math.floor(bounds[0]), math.floor(bounds[1]), math.ceil(bounds[2]), math.ceil(bounds[3]))
    # Pillow's box starts at the pen (x0 = 0) and ends at the advance, so it holds the ink but is not the ink.
    # Align on the real ink, measured once at the chosen size on a scratch mask no larger than that box.
    pad = stroke+2
    with Image.new("L", (bounds[2]-bounds[0]+2*pad, bounds[3]-bounds[1]+2*pad), 0) as scratch:
        ImageDraw.Draw(scratch).multiline_text((pad-bounds[0], pad-bounds[1]), item["text"], font=font, fill=255,
                                               spacing=spacing, align=item["align"], stroke_width=stroke,
                                               stroke_fill=255)
        ink = scratch.getbbox()
    if ink:
        bounds = (ink[0]-pad+bounds[0], ink[1]-pad+bounds[1], ink[2]-pad+bounds[0], ink[3]-pad+bounds[1])
    ink_w, ink_h = bounds[2]-bounds[0], bounds[3]-bounds[1]
    clipped = ink_w > available[0] or ink_h > available[1]
    align = {"left": 0, "center": .5, "right": 1}[item["align"]]
    origin = (x0+round((available[0]-ink_w)*align)-bounds[0],
              y0+round((available[1]-ink_h)/2)-bounds[1])
    left, top, right, bottom = _pixel_box(box, *image.size)
    if left < right and top < bottom:
        # The item gets a hard clip even when its minimum font cannot fit.
        with Image.new("L", (right-left, bottom-top), 0) as mask:
            ImageDraw.Draw(mask).multiline_text((origin[0]-left, origin[1]-top), item["text"],
                font=font, fill=255, spacing=spacing, align=item["align"],
                stroke_width=stroke, stroke_fill=255)
            image.paste(item["color"], (left, top, right, bottom), mask)
    cap = font.getbbox("H", stroke_width=stroke)
    return {"fontSize": best, "capHeightPixels": cap[3]-cap[1]}, clipped


def _pattern(image, item, size, kind):
    area = item["dots"]["area"] if kind == "dots" else item[kind]
    x0, y0, x1, y1 = _pixel_box(area, *image.size)
    if x0 >= x1 or y0 >= y1:
        return
    # Work per output pixel, never per physical dot/stripe (which could number
    # billions on a large panel). These arrays are bounded by one 1024px image.
    x = (np.arange(x0, x1, dtype=float)+.5) * size[0]*1000/image.width - area[0]*size[0]*1000
    y = (np.arange(y0, y1, dtype=float)+.5) * size[1]*1000/image.height - area[1]*size[1]*1000
    if kind == "dots":
        spec = item["dots"]
        pitch = spec["pitchMm"]
        dx, dy = (x % pitch)-pitch/2, (y % pitch)-pitch/2
        mask = dx[None, :]**2 + dy[:, None]**2 <= spec["radiusMm"]**2
        color = spec["color"]
    else:
        angle = math.radians(item["angleDegrees"])
        band = np.floor((x[None, :]*math.cos(angle)+y[:, None]*math.sin(angle))/item["widthMm"])
        mask = (band % 2) == 0
        color = item["colors"][0]
        image.paste(item["colors"][1], (x0, y0, x1, y1))
    with Image.fromarray(mask.astype(np.uint8)*255) as coverage:
        image.paste(color, (x0, y0, x1, y1), coverage)


def _barcode(image, item):
    area = item["barcode"]
    x0, y0, x1, y1 = _pixel_box(area, *image.size)
    if x0 >= x1 or y0 >= y1:
        return
    image.paste("#ffffff", (x0, y0, x1, y1))
    random = BarcodeRandom(item["seed"])
    runs = [random.width() for _ in range(64)]
    total = sum(runs)
    width = (area[2]-area[0])*image.width
    start, scale = area[0]*image.width+.05*width, .9*width/total
    for index, units in enumerate(runs):
        end = start+units*scale
        left, right = max(x0, round(start)), min(x1, round(end))
        if index % 2 == 0 and left < right:
            image.paste("#000000", (left, y0, right, y1))
        start = end


def render_panel(entry, *, fonts=None, font_directory=None):
    """Render a normalized panel; return PNG bytes and per-item diagnostic metrics."""
    for index, item in enumerate(entry["print"]["items"]):
        if "text" in item:
            bad = sorted({c for c in item["text"] if ord(c) not in PRINT_CODEPOINTS})
            require(not bad, f"$.print.items[{index}].text",
                    "Unsupported characters: " + ", ".join(repr(c) for c in bad), "print_invalid")
    fonts = fonts if fonts is not None else Fonts(font_directory)
    width, height = panel_pixels(entry)
    metrics, clipped = [], []
    with Image.new("RGB", (width, height), entry["print"]["background"]) as image:
        draw = ImageDraw.Draw(image)
        density = min(width/entry["size"][0], height/entry["size"][1])/1000
        for index, item in enumerate(entry["print"]["items"]):
            cut = outside_panel(item, entry["size"])
            if "text" in item:
                metric, cannot_fit = _text(image, item, fonts, item["box"])
                metrics.append(dict(metric, item=index))
                cut |= cannot_fit
            elif "rect" in item:
                x0, y0, x1, y1 = (round(v*s) for v, s in zip(item["rect"], (width, height, width, height)))
                if x0 < x1 and y0 < y1:
                    draw.rounded_rectangle((x0, y0, x1-1, y1-1),
                        radius=max(0, round(item["radiusMm"]*density)), fill=item.get("fill"),
                        outline=item.get("stroke"), width=max(1, round(item["lineMm"]*density)))
            elif "line" in item:
                points = [v*s for v, s in zip(item["line"], (width, height, width, height))]
                draw.line(points, fill=item["color"], width=max(1, round(item["lineMm"]*density)))
            elif "circle" in item:
                u, v, radius = item["circle"]
                rx, ry = radius*width, radius*entry["size"][0]/entry["size"][1]*height
                draw.ellipse((u*width-rx, v*height-ry, u*width+rx, v*height+ry),
                             fill=item.get("fill"), outline=item.get("stroke"), width=max(1, round(density)))
            elif "barcode" in item:
                _barcode(image, item)
            else:
                _pattern(image, item, entry["size"], "dots" if "dots" in item else "stripes")
            if cut:
                clipped.append(index)
        with BytesIO() as stream:
            image.save(stream, format="PNG", compress_level=6)
            data = stream.getvalue()
    return PrintedFace(data, width, height, metrics, clipped)


def render_prints(components, *, font_directory=None):
    prints, fonts = {}, None
    for component in components:
        if component.role != "print" or component.entry["id"] in prints:
            continue
        if fonts is None:
            fonts = Fonts(font_directory)
        prints[component.entry["id"]] = render_panel(component.entry, fonts=fonts)
    return prints


def print_lints(components, prints):
    findings, counts = [], {}
    def add(code, component, item, **details):
        if counts.get(code, 0) < 20:
            counts[code] = counts.get(code, 0)+1
            findings.append({"code": code, "entryIds": [component.entry["id"]],
                             "instances": [component.instance], "item": item, **details})
    for component in components:
        if component.role != "print":
            continue
        artwork = prints[component.entry["id"]]
        # Original panel vertices 0->3 span its vertical edge after every affine
        # transform, including mirrors and scatter jitter. Measure the real copy.
        height_mm = float(np.linalg.norm(component.mesh.positions[3]-component.mesh.positions[0]))*1000
        for metric in artwork.text_metrics:
            cap_mm = metric["capHeightPixels"]*height_mm/artwork.height
            if cap_mm < 6-1e-7:
                add("print_small_text", component, metric["item"], capHeightMm=round(cap_mm, 6))
        for item in artwork.clipped:
            add("print_clipped", component, item)
    return findings


def preview_model(model):
    """MB4 preview seam: lit prints appear at full brightness, an approximation.

    The catalog GLB keeps physical emission. Do not modify its materials or the
    legacy import preview shaders, which do not sample emissiveTexture.
    """
    materials = [dict(m, unlit=True, emissive=[0, 0, 0])
                 if m.get("artwork") and m.get("emissiveTexture") else m for m in model.materials]
    return replace(model, materials=materials)
