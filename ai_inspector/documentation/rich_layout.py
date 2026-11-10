"""Bounded authored-text export model and PDF layout (schema 1).

content_model() is independent of PyMuPDF and contains no PDF positions. DOCX
consumes that model in P2b-2. Layout uses only PyMuPDF's built-in font programs;
it never discovers system fonts or opens font files. All normalization is on
the disposable rendering model, never on the stored envelope.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import re
import unicodedata

from .commands import DocumentEditError
from .rich_text import from_plain, is_rich, validate

PDF_RENDERER_VERSION = "authored-text-pdf-1"
# The PDF mirrors the canvas: documentation_rich_text.js render() inside a
# .documentation-object.text box, where one page px is one PDF point. These are
# that box's CSS and the browser defaults it relies on.
HEADING_SCALE = {0: 1.0, 1: 2.0, 2: 1.5, 3: 1.17}  # UA h1-h3 font-size; headings are also bold
LINE_HEIGHT = 1.2  # .documentation-object.text { line-height: 1.2 }
PADDING = 3.0  # .documentation-object.text { padding: 3px }, inside its border (border-box)
LIST_INDENT = 40.0  # UA ul/ol padding-inline-start: 40px per list level
LINK_COLOR = "#0000ee"  # UA link color; links are also underlined
BULLETS = ("\u2022", "\u25e6", "\u25aa")  # UA disc, circle, square by the number of enclosing lists
SYNTHETIC_BOLD = 0.04  # stroke width per font size where a font has no bold face (as browsers synthesize)
SYNTHETIC_OBLIQUE = 0.25  # shear where a font has no italic face (14 degrees, as browsers synthesize)
TAB_SPACES = 4
_EPSILON = 0.01
# UAX #14 in brief: a line may break before or after an ideograph, kana or Hangul syllable, but
# never before closing punctuation, small kana or iteration marks, nor after opening punctuation.
_NO_BREAK_BEFORE = frozenset(map(chr, (
    0x3001, 0x3002, 0xFF0C, 0xFF0E, 0x30FB, 0xFF1A, 0xFF1B, 0xFF1F, 0xFF01, 0x30FC, 0xFF09, 0x3015, 0xFF3D,
    0xFF5D, 0x3009, 0x300B, 0x300D, 0x300F, 0x3011, 0x3019, 0x3017, 0x301F, 0xFF60, 0x00BB, 0x2019, 0x201D,
    0x2010, 0x301C, 0xFF5E, 0x3005, 0x303B, 0x309D, 0x309E, 0x30FD, 0x30FE, 0xFF61, 0xFF63, 0xFF64,
    0x3041, 0x3043, 0x3045, 0x3047, 0x3049, 0x3063, 0x3083, 0x3085, 0x3087, 0x308E, 0x3095, 0x3096,
    0x30A1, 0x30A3, 0x30A5, 0x30A7, 0x30A9, 0x30C3, 0x30E3, 0x30E5, 0x30E7, 0x30EE, 0x30F5, 0x30F6,
    *range(0x31F0, 0x3200)))) | frozenset(")]},.:;!?%")
_NO_BREAK_AFTER = frozenset(map(chr, (
    0xFF08, 0x3014, 0xFF3B, 0xFF5B, 0x3008, 0x300A, 0x300C, 0x300E, 0x3010, 0x3018, 0x3016, 0x301D,
    0xFF5F, 0x00AB, 0x2018, 0x201C, 0xFF62))) | frozenset("([{$")


def _ideographic(char):
    code = ord(char)
    return (0x2E80 <= code <= 0x9FFF or 0xAC00 <= code <= 0xD7A3 or 0xF900 <= code <= 0xFAFF
            or 0xFF00 <= code <= 0xFFEF or 0x20000 <= code <= 0x3FFFD)


def _space(atom):
    # Only U+0020 breaks and hangs (tabs and CR are drawn as spaces); a no-break space binds.
    return not atom.text.strip(" ")


def _break_between(left, right):
    before, after = left.text[-1], right.text[0]
    if after in _NO_BREAK_BEFORE or before in _NO_BREAK_AFTER:
        return False
    return _ideographic(before) or _ideographic(after)


@dataclass(frozen=True)
class Run:
    kind: str  # text or break; raw whitespace/Unicode is retained here
    text: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str = "#18212a"
    href: str | None = None


@dataclass(frozen=True)
class ListLevel:
    list_id: str  # deterministic preorder identity, local to this content model
    kind: str  # bulletList or orderedList
    start: int
    ordinal: int


@dataclass(frozen=True)
class Paragraph:
    kind: str
    heading_level: int
    font_family: str
    font_size: float
    align: str
    list_path: tuple[ListLevel, ...]
    marker: str | None  # only the first paragraph in an item has a marker
    runs: tuple[Run, ...]


@dataclass(frozen=True)
class Content:
    paragraphs: tuple[Paragraph, ...]
    base_size: float
    base_run: Run


def _color(value, fallback="#18212a"):
    return value.lower() if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def content_model(value, style=None):
    """Native paragraphs/runs/list membership, with no font engine or positions.

    Plain strings pass through the schema's lossless from_plain conversion. Its
    temporary IDs are deterministic and never leave this function or get saved.
    """
    style = style or {}
    next_id = 0

    def allocate():
        nonlocal next_id
        next_id += 1
        return f"rt-00000000-0000-4000-8000-{next_id:012x}"

    envelope = from_plain(value, id_factory=allocate) if isinstance(value, str) else validate(value)
    size = float(style.get("fontSize") or 10)
    if not math.isfinite(size) or not 4 <= size <= 144:
        raise DocumentEditError("invalid_export_layout", "Text object font size must be between 4 and 144 points.")
    base = Run("text", bold=int(style.get("fontWeight") or 400) >= 600,
               italic=style.get("fontStyle") == "italic", underline=style.get("textDecoration") == "underline",
               color=_color(style.get("color")))
    family = str(style.get("fontFamily") or "Arial")
    align = style.get("textAlign") if style.get("textAlign") in {"left", "center", "right"} else "left"
    paragraphs, list_count = [], 0

    def inline(node, heading):
        marks = {mark["type"]: mark.get("attrs", {}) for mark in node.get("marks", [])}
        href = marks.get("link", {}).get("href")
        # The canvas nests the color span inside the link, so an explicit color wins;
        # otherwise a link has the browser's link color. Links are underlined either way.
        return Run("break" if node["type"] == "hardBreak" else "text", node.get("text", ""),
                   base.bold or heading or "bold" in marks, base.italic or "italic" in marks,
                   base.underline or "underline" in marks or bool(href),
                   _color(marks.get("textStyle", {}).get("color"), LINK_COLOR if href else base.color), href)

    def block(node, path=(), marker=None):
        nonlocal list_count
        kind = node["type"]
        if kind in {"bulletList", "orderedList"}:
            list_count += 1
            identity = f"list-{list_count}"
            start = node.get("attrs", {}).get("start", 1)
            for index, item in enumerate(node["content"]):
                level = ListLevel(identity, kind, start, start + index)
                for child_index, child in enumerate(item["content"]):
                    bullet = BULLETS[min(len(path), len(BULLETS) - 1)]
                    label = (bullet if kind == "bulletList" else f"{level.ordinal}.") if child_index == 0 else None
                    block(child, path + (level,), label)
            return
        level = node["attrs"]["level"] if kind == "heading" else 0
        runs = []
        for child in node.get("content", []):
            run = inline(child, kind == "heading")
            # Adjacent identical text styles form one normalization unit; a mark
            # boundary is never silently moved across a combining character.
            if runs and run.kind == "text" and replace(runs[-1], text="") == replace(run, text=""):
                runs[-1] = replace(run, text=runs[-1].text + run.text)
            else:
                runs.append(run)
        paragraphs.append(Paragraph(kind, level, family, size * HEADING_SCALE[level], align, path, marker, tuple(runs)))

    for node in envelope["doc"]["content"]:
        block(node)
    return Content(tuple(paragraphs), size, base)


class _Fonts:
    def __init__(self, fitz):
        self.fitz = fitz
        self.fonts = {}
        self.missing = set()

    def get(self, key):
        if key not in self.fonts:
            try:
                self.fonts[key] = self.fitz.Font(fontname=key)
            except (ValueError, RuntimeError):
                self.fonts[key] = None
        return self.fonts[key]

    def choose(self, char, primary):
        # Fonts are embedded as Unicode CID fonts (draw_pdf_object), so any glyph
        # of the object's built-in family can be drawn; the built-in CJK font is
        # the only fallback.
        for key in (primary, "cjk"):
            font = self.get(key)
            if font is not None and font.has_glyph(ord(char), fallback=False):
                return key, font
        self.missing.add(ord(char))
        return primary, self.get(primary)


@dataclass(frozen=True)
class _Atom:
    text: str
    run: Run
    font: str
    size: float
    advance: float
    left: float
    right: float
    ascent: float
    descent: float


@dataclass(frozen=True)
class PositionedRun:
    text: str
    x: float
    baseline: float
    width: float
    font: str
    font_size: float
    bold: bool
    italic: bool
    underline: bool
    color: str
    href: str | None
    rect: tuple[float, float, float, float]
    marker: bool = False
    hanging: bool = False  # white space hanging past a line end: never underlined or linked


@dataclass(frozen=True)
class Line:
    paragraph: int
    top: float
    baseline: float
    height: float
    width: float
    runs: tuple[PositionedRun, ...]


@dataclass(frozen=True)
class Layout:
    content: Content
    frame: tuple[float, float, float, float]
    lines: tuple[Line, ...]
    measured_height: float
    overflow: bool
    unrenderable: tuple[str, ...]
    fonts: _Fonts = field(repr=False, compare=False)


def layout_text(value, frame, style=None, *, fitz_module=None):
    """Lay out into an (x0, y0, x1, y1) content box in PDF points, as the canvas does.

    Lines follow the box CSS (LINE_HEIGHT, white-space: pre-wrap, overflow-wrap:
    anywhere). Each line is LINE_HEIGHT times its font size, with the baseline at
    the CSS half-leading. Preserved white space never wraps; at a line end it
    hangs. A word that does not fit moves to the next line, and is split at glyph
    boundaries only when it is wider than a whole line. No trimming, shrinking,
    clipping or implicit font substitution. Tabs advance four spaces in their
    run's font; literal CR advances one space (as in the browser). LF and
    hardBreak end a line; a final one adds no empty line (as in the browser). NFC
    affects rendering only.
    """
    if fitz_module is None:
        import fitz as fitz_module
    from ai_inspector.parts_manual.pdf import _pdf_font

    content = content_model(value, style)
    bounds = tuple(float(n) for n in frame)
    if len(bounds) != 4 or not all(math.isfinite(n) for n in bounds):
        raise DocumentEditError("invalid_export_layout", "Text object frame must contain finite point coordinates.")
    x0, y0, x1, y1 = bounds
    fonts = _Fonts(fitz_module)

    def atoms(run, paragraph):
        primary = _pdf_font(paragraph.font_family, 700 if run.bold else 400, "italic" if run.italic else "normal")
        if run.kind == "break":
            return [None]
        result = []
        for char in unicodedata.normalize("NFC", run.text):
            if char == "\n":
                result.append(None)
                continue
            shown = " " * TAB_SPACES if char == "\t" else " " if char == "\r" else char
            key, font = fonts.choose(shown[0], primary)
            if font is None:
                raise DocumentEditError("unsupported_export_font", "The built-in PDF base font is unavailable.")
            advance = font.glyph_advance(ord(shown[0])) * paragraph.font_size * len(shown)
            # Like CSS, lines measure advances, never ink: glyph_bbox is the whole font box
            # for some built-in fonts (the CJK one), which would widen every ideograph by 12%.
            result.append(_Atom(shown, run, key, paragraph.font_size, advance, 0.0, advance,
                font.ascender * paragraph.font_size, -font.descender * paragraph.font_size))
        return result

    def extents(items):
        advance, left, right = 0.0, 0.0, 0.0
        for atom in items:
            left = min(left, advance + atom.left)
            right = max(right, advance + atom.right, advance + atom.advance)
            advance += atom.advance
        return left, right

    def marker_atoms(paragraph):
        text = paragraph.marker
        if text in BULLETS[1:]:
            key = _pdf_font(paragraph.font_family, 700 if content.base_run.bold else 400,
                            "italic" if content.base_run.italic else "normal")
            if not any(font is not None and font.has_glyph(ord(text), fallback=False)
                       for font in (fonts.get(key), fonts.get("cjk"))):
                text = BULLETS[0]
        # An outside marker in the item's base font, with its suffix space; never underlined or linked.
        run = replace(content.base_run, text=text + " ", underline=False, href=None)
        return atoms(run, replace(paragraph, font_size=content.base_size))

    lines, top, overflow = [], y0, x1 <= x0 or y1 <= y0
    for paragraph_index, paragraph in enumerate(content.paragraphs):
        body = [atom for run in paragraph.runs for atom in atoms(run, paragraph)]
        label = marker_atoms(paragraph) if paragraph.marker else []
        indent = LIST_INDENT * len(paragraph.list_path)
        available = x1 - x0 - indent
        bold = content.base_run.bold or paragraph.heading_level > 0
        metrics = fonts.get(_pdf_font(paragraph.font_family, 700 if bold else 400,
                                      "italic" if content.base_run.italic else "normal"))
        if metrics is None:
            raise DocumentEditError("unsupported_export_font", "The built-in PDF base font is unavailable.")
        line_height = LINE_HEIGHT * paragraph.font_size
        # CSS half-leading: the font's ascent plus descent sits centered in the line.
        baseline_offset = (line_height + (metrics.ascender + metrics.descender) * paragraph.font_size) / 2
        current, first = [], True

        def flush():
            nonlocal current, top, first, overflow
            # Trailing preserved white space hangs: it is kept and drawn, but it is
            # left out of the fit check and of the alignment.
            end = len(current)
            while end and _space(current[end - 1]):
                end -= 1
            visible, hanging = current[:end], current[end:]
            left, right = extents(visible)
            width = right - left
            if width > available + _EPSILON or available <= 0:
                overflow = True
            extra = max(0, available - width)
            offset = extra / 2 if paragraph.align == "center" else extra if paragraph.align == "right" else 0
            baseline = top + baseline_offset
            positioned = []

            def place(items, pen, **flags):
                for atom in items:
                    rect = (pen + min(0, atom.left), baseline - atom.ascent,
                            pen + max(atom.advance, atom.right), baseline + atom.descent)
                    run = PositionedRun(atom.text, pen, baseline, atom.advance, atom.font, atom.size,
                        atom.run.bold, atom.run.italic, atom.run.underline, atom.run.color, atom.run.href, rect, **flags)
                    if positioned and replace(positioned[-1], text="", width=0, rect=(), x=0) == replace(run, text="", width=0, rect=(), x=0):
                        previous = positioned[-1]
                        positioned[-1] = replace(previous, text=previous.text + run.text, width=previous.width + run.width,
                            rect=(min(previous.rect[0], rect[0]), min(previous.rect[1], rect[1]),
                                  max(previous.rect[2], rect[2]), max(previous.rect[3], rect[3])))
                    else:
                        positioned.append(run)
                    pen += atom.advance
                return pen

            if first and label:
                # The marker and its suffix space end where the item text starts.
                start = x0 + indent - sum(atom.advance for atom in label)
                if start < x0 - _EPSILON:
                    overflow = True  # a marker wider than its list indent would leave the box
                place(label, start, marker=True)
            place(hanging, place(visible, x0 + indent + offset - left), hanging=True)
            lines.append(Line(paragraph_index, top, baseline, line_height, width, tuple(positioned)))
            top += line_height
            current, first = [], False

        index = 0
        while index < len(body):
            atom = body[index]
            if atom is None:
                if index < len(body) - 1:
                    flush()
                index += 1
                continue
            if _space(atom):
                current.append(atom)  # white space never wraps (it hangs at a line end)
                index += 1
                continue
            # Wrap whole words across mark boundaries (and between ideographs); split an
            # overlong word only at glyph boundaries. Whitespace itself is never discarded.
            end = index + 1
            while (end < len(body) and body[end] is not None and not _space(body[end])
                   and not _break_between(body[end - 1], body[end])):
                end += 1
            token = body[index:end]
            left, right = extents(current + token)
            if current and right - left > available + _EPSILON:
                flush()
            for item in token:
                left, right = extents(current + [item])
                if current and right - left > available + _EPSILON:
                    flush()
                current.append(item)
            index = end
        flush()  # includes empty paragraphs
    height = top - y0
    overflow = overflow or height > y1 - y0 + _EPSILON
    return Layout(content, bounds, tuple(lines), height, overflow,
                  tuple(f"U+{code:04X}" for code in sorted(fonts.missing)), fonts)


def authored_objects(descriptor):
    """Return a display object plus its canonical content, never its projection."""
    display = descriptor.get("documentationObjects") or {}
    composition = descriptor.get("documentationComposition") or (descriptor.get("renderRequest") or {}).get("composition") or {}
    canonical = composition.get("documentObjects") or {}
    for key in dict.fromkeys([*display, *canonical]):
        value = display.get(key) or canonical[key]
        if value.get("type") != "text":
            continue
        stored = canonical.get(key, value).get("content", "")
        if value.get("isRichText") and not is_rich(stored):
            raise DocumentEditError("missing_rich_text_content", "Canonical rich text is missing; export cannot use its plain projection.",
                                    targets=[{"pageId": descriptor["pageId"], "targetId": key}])
        yield key, value, stored


def has_text_objects(document):
    return any(next(authored_objects(page), None) is not None for page in document.get("pages", []))


@dataclass(frozen=True)
class ObjectLayout:
    target: dict
    frame: tuple[float, float, float, float]
    style: dict
    outline: bool
    layout: Layout


def prepare_pdf_objects(fitz, document, page_size, *, rich_only=False):
    """Preflight every applicable object before drawing or writing any artifact."""
    from ai_inspector.parts_manual.pdf import _document_object_style, _document_theme

    result, rotated, missing, overflowing = {}, [], [], []
    theme = _document_theme(document)
    width, height = page_size
    for descriptor in document.get("pages", []):
        page_plans = result.setdefault(descriptor["pageId"], {})
        for key, value, stored in authored_objects(descriptor):
            if rich_only and not is_rich(stored):
                continue
            target = {"pageId": descriptor["pageId"], "targetId": key}
            frame = value.get("frame") or {}
            x, y, w, h, rotation = (float(frame.get(name) or 0) for name in ("x", "y", "width", "height", "rotation"))
            if not all(math.isfinite(n) for n in (x, y, w, h, rotation)):
                raise DocumentEditError("invalid_export_layout", "Text object frame is not finite.", targets=[target])
            if abs(rotation) > 1e-9:
                rotated.append(target)
                continue
            bounds = (x * width, y * height, (x + w) * width, (y + h) * height)
            style = _document_object_style(theme, value)
            outline = "outlineColor" in (value.get("styleOverrides") or {})
            # Like the canvas (border-box): the text sits inside the border and the padding.
            inset = PADDING + (max(0.0, float(style.get("lineWidth") or 0)) if outline else 0.0)
            try:
                layout = layout_text(stored, (bounds[0] + inset, bounds[1] + inset, bounds[2] - inset, bounds[3] - inset),
                                     style, fitz_module=fitz)
            except DocumentEditError as error:
                raise DocumentEditError(error.code, str(error), **{**error.details, "targets": [target]}) from error
            if layout.unrenderable:
                missing.append({**target, "codePoints": list(layout.unrenderable)})
            reasons = [reason for reason, failed in (
                ("outside_page", x < 0 or y < 0 or x + w > 1 + 1e-9 or y + h > 1 + 1e-9),
                ("text_does_not_fit", layout.overflow)) if failed]
            if reasons:
                overflowing.append({**target, "reasons": reasons, "measuredHeight": layout.measured_height,
                                    "frame": list(bounds)})
            page_plans[key] = ObjectLayout(target, bounds, style, outline, layout)
    if rotated:
        raise DocumentEditError("unsupported_export_rotation", "Rotated authored text is not supported by the rich PDF layout.", targets=rotated)
    if missing:
        raise DocumentEditError("unsupported_export_glyph", "No available built-in PDF font renders these characters.",
                                targets=missing, codePoints=sorted({code for item in missing for code in item["codePoints"]}))
    if overflowing:
        raise DocumentEditError("layout_overflow", "Authored text must fit inside its text box, and the box must be on the "
                                "page; enlarge or move the box, or shorten the text.", targets=overflowing)
    return result


def draw_pdf_object(fitz, page, plan):
    """Draw one preflighted object, with per-run underlines and exact URI links."""
    from ai_inspector.parts_manual.pdf import _hex_rgb

    if plan.layout.overflow or plan.layout.unrenderable:
        raise DocumentEditError("invalid_export_layout", "Only a successful text layout can be drawn.", targets=[plan.target])
    rect, style = fitz.Rect(plan.frame), plan.style
    opacity = float(style.get("opacity") if style.get("opacity") is not None else 1)
    fill = style.get("fill")
    if fill and str(fill).upper() != "#FFFFFF":
        page.draw_rect(rect, color=None, fill=_hex_rgb(fill, "#FFFFFF"), fill_opacity=opacity)
    outline_width = float(style.get("lineWidth") or 0)
    if outline_width > 0 and plan.outline:
        # The canvas border lies inside the box (border-box), so the stroke is centered half a width in.
        border = fitz.Rect(rect.x0 + outline_width / 2, rect.y0 + outline_width / 2,
                           rect.x1 - outline_width / 2, rect.y1 - outline_width / 2)
        page.draw_rect(border, color=_hex_rgb(style.get("outlineColor"), "#ABBAC4"), width=outline_width, stroke_opacity=opacity)
    registered = set()
    for line in plan.layout.lines:
        for run in line.runs:
            name = "drt_" + run.font
            font = plan.layout.fonts.get(run.font)
            if name not in registered:
                # Embed the built-in font program as a Unicode CID font. This
                # avoids insert_text's simple-font substitution for e.g. bullets.
                page.insert_font(fontname=name, fontbuffer=font.buffer, set_simple=False)
                registered.add(name)
            color = _hex_rgb(run.color)
            options = {}
            if run.bold and not font.flags.get("bold"):
                # The fallback font has no bold face: embolden it as browsers synthesize bold.
                options.update(render_mode=2, fill=color, border_width=SYNTHETIC_BOLD, stroke_opacity=opacity)
            if run.italic and not font.flags.get("italic"):
                # ... nor an italic face: slant it about the run's baseline origin.
                options["morph"] = (fitz.Point(run.x, run.baseline), fitz.Matrix(1, 0, SYNTHETIC_OBLIQUE, 1, 0, 0))
            page.insert_text((run.x, run.baseline), run.text, fontname=name, fontsize=run.font_size,
                             color=color, fill_opacity=opacity, **options)
            if run.hanging:
                continue
            if run.underline and run.width:
                page.draw_line((run.x, run.baseline + run.font_size * 0.1),
                    (run.x + run.width, run.baseline + run.font_size * 0.1), color=color,
                    width=max(0.5, run.font_size * 0.04), stroke_opacity=opacity)
            if run.href and run.width:
                page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(run.rect), "uri": run.href})


def draw_pdf_objects(fitz, page, descriptor, plans):
    for plan in plans.get(descriptor["pageId"], {}).values():
        draw_pdf_object(fitz, page, plan)


def finish_pdf_fonts(pdf, plans):
    """Subset the embedded built-in fonts once every planned object is drawn.

    Only a document with text drawn by this path embeds fonts, so every other
    export keeps its exact bytes. The built-in CJK font alone is about 3.5 MB.
    """
    if any(plans.values()):
        pdf.subset_fonts()
