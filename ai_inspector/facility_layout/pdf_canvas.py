"""A small vector PDF writer: pages of lines, shapes, text and images, with no third-party library.

Coordinates are PDF points (1/72 inch) from the bottom-left corner of the page. Text uses the standard
Helvetica faces that every PDF viewer provides, so no font is embedded; strings are encoded as
Windows-1252. Content streams are compressed with zlib.
"""
from __future__ import annotations

import math
import zlib
from typing import Iterable, Sequence

Point = tuple[float, float]

# Advance widths (1/1000 em) of the characters 32..126 in the standard Helvetica faces (Adobe AFM metrics,
# WinAnsi encoding: 39 is quotesingle, 96 is grave). Helvetica-Oblique uses the regular widths.
_REGULAR = (278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
            556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
            1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
            667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
            333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
            556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584)
_BOLD = (278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
         975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
         333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
         611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584)
# A few Windows-1252 characters beyond ASCII: endash, emdash, degree, twosuperior, periodcentered, multiply.
_EXTRA = {0x96: 556, 0x97: 1000, 0xB0: 400, 0xB2: 333, 0xB7: 278, 0xD7: 584}
FONTS = {
    "regular": ("F1", "Helvetica", _REGULAR),
    "bold": ("F2", "Helvetica-Bold", _BOLD),
    "italic": ("F3", "Helvetica-Oblique", _REGULAR),
}


def _encode(text: str) -> bytes:
    return str(text).encode("cp1252", errors="replace")


def text_width(text: str, size: float, font: str = "regular") -> float:
    widths = FONTS[font][2]
    total = 0
    for code in _encode(text):
        total += widths[code - 32] if 32 <= code <= 126 else _EXTRA.get(code, 556)
    return total * size / 1000.0


def color(value) -> tuple[float, float, float]:
    """'#rrggbb' or an (r, g, b) tuple of 0..1 floats."""
    if isinstance(value, str):
        text = value.lstrip("#")
        if len(text) != 6:
            raise ValueError(f"Colours are #rrggbb, not {value!r}")
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    r, g, b = value
    return float(r), float(g), float(b)


def _num(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _pdf_string(data: bytes) -> bytes:
    return b"(" + data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


class Page:
    def __init__(self, document: "Document", width: float, height: float):
        self.document, self.width, self.height = document, float(width), float(height)
        self._ops: list[str] = []
        self._states: set[str] = set()
        self._images: set[str] = set()

    # --- state -------------------------------------------------------------------------------------
    def save(self) -> None:
        self._ops.append("q")

    def restore(self) -> None:
        self._ops.append("Q")

    def clip_rect(self, x: float, y: float, w: float, h: float) -> None:
        """Clip everything drawn until the matching restore() to a rectangle."""
        self._ops.append(f"{_num(x)} {_num(y)} {_num(w)} {_num(h)} re W n")

    def alpha(self, fill: float = 1.0, stroke: float = 1.0) -> None:
        name = self.document._state(fill, stroke)
        self._states.add(name)
        self._ops.append(f"/{name} gs")

    def _style(self, stroke, fill, width, dash, cap, join) -> str:
        if stroke is not None:
            self._ops.append("{} {} {} RG".format(*map(_num, color(stroke))))
            self._ops.append(f"{_num(width)} w {cap} J {join} j")
            self._ops.append("[" + " ".join(_num(v) for v in (dash or ())) + "] 0 d")
        if fill is not None:
            self._ops.append("{} {} {} rg".format(*map(_num, color(fill))))
        if stroke is not None and fill is not None:
            return "B"
        return "S" if stroke is not None else "f" if fill is not None else "n"

    # --- shapes ------------------------------------------------------------------------------------
    def path(self, points: Sequence[Point], *, closed: bool = False, stroke=None, fill=None, width: float = 0.5,
             dash: Sequence[float] | None = None, cap: int = 0, join: int = 0) -> None:
        points = list(points)
        if len(points) < 2:
            return
        paint = self._style(stroke, fill, width, dash, cap, join)
        steps = [f"{_num(points[0][0])} {_num(points[0][1])} m"]
        steps += [f"{_num(x)} {_num(y)} l" for x, y in points[1:]]
        if closed:
            steps.append("h")
        self._ops.append(" ".join(steps) + " " + paint)

    def polygon(self, points: Sequence[Point], **style) -> None:
        self.path(points, closed=True, **style)

    def line(self, a: Point, b: Point, **style) -> None:
        self.path([a, b], **style)

    def rect(self, x: float, y: float, w: float, h: float, **style) -> None:
        self.path([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], closed=True, **style)

    def arc_points(self, cx: float, cy: float, r: float, start: float, end: float, steps: int = 24) -> list[Point]:
        """Points along a circular arc, angles in radians counter-clockwise from +x."""
        return [(cx + r * math.cos(start + (end - start) * i / steps), cy + r * math.sin(start + (end - start) * i / steps))
                for i in range(steps + 1)]

    def circle(self, cx: float, cy: float, r: float, **style) -> None:
        self.path(self.arc_points(cx, cy, r, 0, 2 * math.pi, 48)[:-1], closed=True, **style)

    # --- text --------------------------------------------------------------------------------------
    def text(self, x: float, y: float, value: str, *, size: float = 8, font: str = "regular", fill="#000000",
             align: str = "left", angle: float = 0.0) -> float:
        """Draw one line of text with its baseline at (x, y); returns its width. angle in degrees."""
        width = text_width(value, size, font)
        shift = {"left": 0.0, "center": width / 2.0, "right": width}[align]
        radians = math.radians(angle)
        c, s = math.cos(radians), math.sin(radians)
        ox, oy = x - shift * c, y - shift * s
        name = FONTS[font][0]
        self.document._fonts.add(font)
        self._ops.append("BT {} {} {} rg /{} {} Tf {} {} {} {} {} {} Tm ".format(
            *map(_num, color(fill)), name, _num(size), _num(c), _num(s), _num(-s), _num(c), _num(ox), _num(oy))
            + _pdf_string(_encode(value)).decode("latin-1") + " Tj ET")
        return width

    # --- images ------------------------------------------------------------------------------------
    def image(self, name: str, x: float, y: float, w: float, h: float) -> None:
        if name not in self.document._image_objects:
            raise KeyError(f"Unknown image {name}")
        self._images.add(name)
        self._ops.append(f"q {_num(w)} 0 0 {_num(h)} {_num(x)} {_num(y)} cm /{name} Do Q")

    def content(self) -> bytes:
        return "\n".join(self._ops).encode("latin-1")


class Document:
    def __init__(self, *, title: str = "", author: str = "", subject: str = "", creator: str = "InspectorPro"):
        self.info = {"Title": title, "Author": author, "Subject": subject, "Creator": creator,
                     "Producer": "InspectorPro facility layout PDF"}
        self.pages: list[Page] = []
        self._fonts: set[str] = set()
        self._gstates: dict[str, tuple[float, float]] = {}
        self._image_objects: dict[str, tuple[int, int, bytes, bytes | None]] = {}

    def add_page(self, width: float, height: float) -> Page:
        page = Page(self, width, height)
        self.pages.append(page)
        return page

    def add_image(self, name: str, width: int, height: int, rgb: bytes, alpha: bytes | None = None) -> str:
        """Register an 8-bit RGB image (and an optional 8-bit alpha mask) under a resource name."""
        if len(rgb) != width * height * 3 or (alpha is not None and len(alpha) != width * height):
            raise ValueError("Image bytes do not match its size")
        self._image_objects[name] = (width, height, rgb, alpha)
        return name

    def _state(self, fill: float, stroke: float) -> str:
        name = f"GS{round(fill * 100)}x{round(stroke * 100)}"
        self._gstates[name] = (max(0.0, min(1.0, fill)), max(0.0, min(1.0, stroke)))
        return name

    def to_bytes(self) -> bytes:
        objects: list[bytes] = []

        def reserve() -> int:
            objects.append(b"")
            return len(objects)

        def stream(header: str, data: bytes) -> bytes:
            packed = zlib.compress(data, 9)
            return (f"<< {header} /Filter /FlateDecode /Length {len(packed)} >>\nstream\n").encode("latin-1") \
                + packed + b"\nendstream"

        catalog, pages_id, info_id = reserve(), reserve(), reserve()
        font_ids = {}
        for key in sorted(self._fonts):
            font_ids[key] = reserve()
            objects[font_ids[key] - 1] = (f"<< /Type /Font /Subtype /Type1 /BaseFont /{FONTS[key][1]} "
                                          "/Encoding /WinAnsiEncoding >>").encode("latin-1")
        state_ids = {}
        for name, (fill, stroke) in sorted(self._gstates.items()):
            state_ids[name] = reserve()
            objects[state_ids[name] - 1] = f"<< /Type /ExtGState /ca {_num(fill)} /CA {_num(stroke)} >>".encode("latin-1")
        image_ids = {}
        for name, (width, height, rgb, alpha) in sorted(self._image_objects.items()):
            mask = ""
            if alpha is not None:
                mask_id = reserve()
                objects[mask_id - 1] = stream(f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
                                              "/ColorSpace /DeviceGray /BitsPerComponent 8", alpha)
                mask = f" /SMask {mask_id} 0 R"
            image_ids[name] = reserve()
            objects[image_ids[name] - 1] = stream(f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
                                                  f"/ColorSpace /DeviceRGB /BitsPerComponent 8{mask}", rgb)
        page_ids = []
        for page in self.pages:
            content_id = reserve()
            objects[content_id - 1] = stream("", page.content())
            page_id = reserve()
            fonts = " ".join(f"/{FONTS[key][0]} {font_ids[key]} 0 R" for key in sorted(self._fonts))
            states = " ".join(f"/{name} {state_ids[name]} 0 R" for name in sorted(page._states))
            images = " ".join(f"/{name} {image_ids[name]} 0 R" for name in sorted(page._images))
            resources = f"/Font << {fonts} >>" + (f" /ExtGState << {states} >>" if states else "") \
                + (f" /XObject << {images} >>" if images else "")
            objects[page_id - 1] = (f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {_num(page.width)} "
                                    f"{_num(page.height)}] /Resources << {resources} >> /Contents {content_id} 0 R >>"
                                    ).encode("latin-1")
            page_ids.append(page_id)
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("latin-1")
        info = " ".join(f"/{key} " + _pdf_string(_encode(value)).decode("latin-1")
                        for key, value in self.info.items() if value)
        objects[info_id - 1] = f"<< {info} >>".encode("latin-1")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
        out += b"".join(f"{offset:010d} 00000 n \n".encode("latin-1") for offset in offsets)
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info_id} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode("latin-1")
        return bytes(out)


def bounds(points: Iterable[Point]) -> tuple[float, float, float, float]:
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)
