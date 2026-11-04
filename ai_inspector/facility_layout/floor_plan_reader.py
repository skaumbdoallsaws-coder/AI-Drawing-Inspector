"""Floor-plan import, reader (docs/facility-floor-plan-import-plan.md, sections 3, 5 and 10).

Reads an untrusted ASCII DXF with ezdxf into bounded, normalized plan geometry in DRAWING units:

- LINE, LWPOLYLINE, planar POLYLINE (bulges kept), ARC, CIRCLE, ELLIPSE and SPLINE become polylines; curves are
  flattened so no point of the curve is farther than `curveTolerance` (drawing units) from its polyline. A polyline
  that ends where it starts counts as closed.
- TEXT, MTEXT and ATTRIB become sanitized labels (formatting codes removed; fields stay plain text, never evaluated).
- INSERT blocks are expanded with their own transforms: nested, rotated, scaled (also unevenly), mirrored and arrayed
  (MINSERT). Entities on layer "0" inside a block take the layer of the insert that places them. A block's own unit
  setting is reported but never applied: the insert's scale already carries any unit conversion, and applying both
  would scale the block twice.
- Everything else is counted by type, layer and reason in `unsupported`; paper-space sheets and external references
  are listed. Nothing disappears without a line in the report.

Points are stored relative to `origin` (the minimum of the drawn geometry) and rounded to six decimals of a drawing
unit, so large survey coordinates keep their local precision. The output is deterministic for a given file and
ezdxf version: same order, same IDs (the DXF handle, prefixed by the handles of the inserts that place it: "2A/1F";
a MINSERT copy adds its index: "2B[3]/1F").

This module imports nothing from the app (only the standard library and ezdxf): the parse runs in a separate,
killable worker process that loads this file by its path (floor_plan_worker.py), and `worker_main` is that process's
entry point.
"""
from __future__ import annotations

import gc
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter

ADAPTER_VERSION = 1
SCHEMA = "inspectorpro.facility.floorPlanGeometry"
SCHEMA_VERSION = 1

DEFAULT_LIMITS = {
    "maxFileBytes": 25 * 1024 * 1024,
    "maxSourceEntities": 100_000,    # model-space entities, before block expansion
    "maxExpandedEntities": 250_000,  # entities read, block contents and MINSERT copies included
    "maxVertices": 1_000_000,        # flattened vertices kept, all entities together
    "maxEntityVertices": 50_000,     # one polyline or flattened curve
    "maxBlockDepth": 16,             # nested inserts
    "maxLayers": 512,
    "maxTextBytes": 4096,            # one label, UTF-8, after normalization
    "maxTexts": 50_000,              # labels kept
    "maxCoordinate": 1e10,           # absolute drawing units
    "maxReportRows": 200,            # rows in unsupported / warnings / paperSpace / externalReferences
}

# Building-scale units ($INSUNITS) and their exact size in meters. Any other code (unitless 0, miles, kilometers,
# microns, astronomical units...) is "unresolved": the user chooses the unit or calibrates with a known distance.
UNIT_METERS = {
    1: 0.0254,            # inches
    2: 0.3048,            # feet
    4: 0.001,             # millimeters
    5: 0.01,              # centimeters
    6: 1.0,               # meters
    10: 0.9144,           # yards
    14: 0.1,              # decimeters
    21: 1200.0 / 3937.0,  # US survey feet
    22: 100.0 / 3937.0,   # US survey inches
    23: 3600.0 / 3937.0,  # US survey yards
}
UNIT_NAMES = {
    0: "unitless", 1: "inches", 2: "feet", 3: "miles", 4: "millimeters", 5: "centimeters", 6: "meters",
    7: "kilometers", 8: "microinches", 9: "mils", 10: "yards", 11: "angstroms", 12: "nanometers", 13: "microns",
    14: "decimeters", 15: "decameters", 16: "hectometers", 17: "gigameters", 18: "astronomical units",
    19: "light years", 20: "parsecs", 21: "US survey feet", 22: "US survey inches", 23: "US survey yards",
    24: "US survey miles",
}

CURVE_TYPES = frozenset({"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"})
TEXT_TYPES = frozenset({"TEXT", "MTEXT", "ATTRIB"})
# Why an entity type is not drawn. Anything not listed here is "unsupported".
SKIP_REASONS = {
    "HATCH": "hatch", "MPOLYGON": "hatch", "DIMENSION": "dimension", "ARC_DIMENSION": "dimension",
    "LARGE_RADIAL_DIMENSION": "dimension", "LEADER": "annotation", "MLEADER": "annotation",
    "MULTILEADER": "annotation", "TOLERANCE": "annotation", "IMAGE": "image", "WIPEOUT": "image",
    "PDFUNDERLAY": "underlay", "DWFUNDERLAY": "underlay", "DGNUNDERLAY": "underlay", "OLE2FRAME": "embedded_object",
    "OLEFRAME": "embedded_object", "ACAD_PROXY_ENTITY": "proxy_object", "3DSOLID": "solid", "REGION": "solid",
    "BODY": "solid", "SURFACE": "solid", "MESH": "solid", "3DFACE": "solid", "SOLID": "solid", "TRACE": "solid",
    "POINT": "point", "XLINE": "infinite_line", "RAY": "infinite_line", "ATTDEF": "attribute_definition",
    "VIEWPORT": "viewport", "SHAPE": "shape", "HELIX": "solid",
}
_XREF_FLAGS = 4 | 8  # BLOCK flags: external reference, overlay
_ALIGN_BY_ATTACHMENT = {1: "TOP_LEFT", 2: "TOP_CENTER", 3: "TOP_RIGHT", 4: "MIDDLE_LEFT", 5: "MIDDLE_CENTER",
                        6: "MIDDLE_RIGHT", 7: "BOTTOM_LEFT", 8: "BOTTOM_CENTER", 9: "BOTTOM_RIGHT"}
# Unicode controls that would reorder or hide label text (bidi overrides and isolates, zero-width marks).
_HIDDEN = {0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067,
           0x2068, 0x2069, 0xFEFF}
_DWG_SIGNATURE = re.compile(rb"AC[0-9.]{4}")


class FloorPlanReadError(Exception):
    """A drawing that cannot be imported. `code` is stable for the API; `message` is safe to show the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def sniff(head: bytes) -> None:
    """Refuse what is clearly not an ASCII DXF before the parser sees it (the suffix and MIME type prove nothing)."""
    if head.startswith(b"AutoCAD Binary DXF"):
        raise FloorPlanReadError("binary_dxf", "This is a binary DXF. Save the drawing as an ASCII DXF and import "
                                               "that.")
    if _DWG_SIGNATURE.match(head):
        raise FloorPlanReadError("dwg_file", "This is a DWG file. Save it as a DXF from your CAD program (File > "
                                             "Save As > DXF) and import the DXF.")
    if head.startswith((b"PK\x03\x04", b"\x1f\x8b", b"%PDF", b"Rar!", b"7z\xbc\xaf")):
        raise FloorPlanReadError("not_dxf", "This file is not a DXF drawing (archives and PDFs can't be imported).")
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    lines = [line.strip() for line in head.decode("latin-1").splitlines()]
    index = 0
    while index + 1 < len(lines) and lines[index] == "999":  # leading comments
        index += 2
    if lines[index:index + 2] != ["0", "SECTION"]:
        raise FloorPlanReadError("not_dxf", "This file is not an ASCII DXF drawing.")


def check_tail(tail: bytes) -> None:
    """A complete ASCII DXF ends with the pair 0 / EOF; anything else was cut short (a partial download or copy)."""
    lines = [line.strip() for line in tail.rstrip(b"\x00\x1a \t\r\n").splitlines()]
    if len(lines) < 2 or lines[-1].upper() != b"EOF" or lines[-2] != b"0":
        raise FloorPlanReadError("truncated", "The drawing file is incomplete: it does not end the way a DXF file "
                                              "does. Export it again from your CAD program.")


def clean_text(raw, max_bytes: int) -> tuple[str, bool]:
    """Label text safe to show: NFC, newlines kept, other controls and hidden direction marks removed, trimmed to
    MAX_BYTES of UTF-8 (whole characters). Returns (text, truncated)."""
    text = unicodedata.normalize("NFC", str(raw).replace("\r\n", "\n").replace("\r", "\n"))
    kept = []
    for char in text:
        code = ord(char)
        if char == "\n" or code in (0x2028, 0x2029):  # line and paragraph separators are new lines
            kept.append("\n")
        elif char == "\t":
            kept.append(" ")
        elif code in _HIDDEN or unicodedata.category(char) in ("Cc", "Cf", "Cs", "Co"):
            continue  # controls, every format character (direction marks, invisible joiners, tags), surrogates
        else:
            kept.append(char)
    text = "\n".join(line.strip() for line in "".join(kept).split("\n")).strip()
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text, False
    return data[:max_bytes].decode("utf-8", errors="ignore").rstrip(), True


def _name(raw, limit: int = 255) -> str:
    text, _ = clean_text(raw, limit)
    return text.replace("\n", " ")


def _attr(entity, key: str, default=None):
    try:
        value = entity.dxf.get(key, default)
    except Exception:  # an attribute this entity type does not define
        return default
    return default if value is None else value


def _finite(value: float, bound: float) -> bool:
    return math.isfinite(value) and abs(value) <= bound


def _r6(value: float) -> float:
    rounded = round(value, 6)
    return 0.0 if rounded == 0 else rounded


def _sig(value: float) -> float:
    """Twelve significant digits: for sizes that are not coordinates (a tolerance in inches is 0.0787401574803)."""
    return float(f"{value:.12g}")


class _Reader:
    def __init__(self, doc, limits: dict, tolerance: float):
        self.doc = doc
        self.limits = limits
        self.tolerance = tolerance
        self.layer_keys: dict[str, str] = {}   # casefolded layer name -> layer id (DXF layer names ignore case)
        self.layer_info: dict[str, dict] = {}  # layer id -> table facts
        self.records: list[dict] = []          # absolute drawing coordinates until `read_dxf` rebases them
        self.unsupported: Counter = Counter()
        self.warnings: list[dict] = []
        self.ids: set[str] = set()
        self.vertices = 0
        self.expanded = 0
        self.texts = 0
        self.sequence = 0
        self.z_range = [math.inf, -math.inf]
        self.block_units: dict[str, int] = {}
        self.xref_names: list[str] = []
        self.truncated_texts = 0
        for layer in doc.layers:
            self.layer(layer.dxf.name, layer)

    # -- report ---------------------------------------------------------------------------------------------------
    def layer(self, name, table_entry=None) -> str:
        key = str(name).casefold()
        found = self.layer_keys.get(key)
        if found is not None:
            return found
        if len(self.layer_keys) >= self.limits["maxLayers"]:
            raise FloorPlanReadError("too_many_layers", f"The drawing uses more than {self.limits['maxLayers']} "
                                                        "layers, more than the import supports.")
        layer_id = f"L{len(self.layer_keys)}"
        self.layer_keys[key] = layer_id
        info = {"layerId": layer_id, "name": _name(name), "color": 7, "on": True, "frozen": False}
        if table_entry is not None:
            try:
                info["color"] = abs(int(table_entry.color)) or 7
                info["on"] = bool(table_entry.is_on())
                info["frozen"] = bool(table_entry.is_frozen())
                rgb = table_entry.rgb
                if rgb is not None:
                    info["rgb"] = "#%02x%02x%02x" % tuple(int(c) for c in rgb)
            except Exception:  # an odd layer table entry keeps the defaults
                pass
        self.layer_info[layer_id] = info
        return layer_id

    def skip(self, entity_type: str, layer_id: str, reason: str) -> None:
        self.unsupported[(entity_type, layer_id, reason)] += 1

    def warn(self, code: str, message: str) -> None:
        if len(self.warnings) < self.limits["maxReportRows"]:
            self.warnings.append({"code": code, "message": message})

    def make_id(self, prefix: str, entity, fallback: str | None = None) -> str:
        handle = _attr(entity, "handle")
        if handle:
            base = f"{prefix}{handle}"
        elif fallback:
            base = f"{prefix}{fallback}"
        else:
            self.sequence += 1
            base = f"{prefix}#{self.sequence}"
        unique, k = base, 1
        while unique in self.ids:
            k += 1
            unique = f"{base}~{k}"
        self.ids.add(unique)
        return unique

    def count_entity(self) -> None:
        self.expanded += 1
        if self.expanded > self.limits["maxExpandedEntities"]:
            raise FloorPlanReadError("too_many_entities", "The drawing has more than "
                                     f"{self.limits['maxExpandedEntities']:,} entities once its blocks are expanded, "
                                     "more than the import supports.")

    # -- traversal ------------------------------------------------------------------------------------------------
    def walk(self, entities, matrix, inherited_layer, prefix: str, blocks: tuple, depth: int) -> None:
        for entity in entities:
            self.count_entity()
            kind = entity.dxftype()
            layer_name = _attr(entity, "layer", "0") or "0"
            if inherited_layer is not None and layer_name == "0":
                layer_name = inherited_layer
            layer_id = self.layer(layer_name)
            if _attr(entity, "invisible", 0):
                self.skip(kind, layer_id, "invisible")
            elif kind == "INSERT":
                self.insert(entity, matrix, inherited_layer, layer_name, layer_id, prefix, blocks, depth)
            elif kind in CURVE_TYPES:
                self.curve(entity, kind, matrix, layer_id, prefix, blocks)
            elif kind in TEXT_TYPES:
                self.text(entity, kind, matrix, layer_id, prefix, blocks)
            else:
                self.skip(kind, layer_id, SKIP_REASONS.get(kind, "unsupported"))

    def insert(self, entity, matrix, inherited_layer, layer_name, layer_id, prefix, blocks, depth) -> None:
        from ezdxf.math import Matrix44

        name = _attr(entity, "name", "")
        block = self.doc.blocks.get(name)
        if block is None:
            self.skip("INSERT", layer_id, "missing_block")
            return
        if int(_attr(block.block, "flags", 0) or 0) & _XREF_FLAGS:
            self.skip("INSERT", layer_id, "external_reference")
            if name not in self.xref_names:
                self.xref_names.append(name)
            return
        if name in blocks:
            self.skip("INSERT", layer_id, "recursive_block")
            return
        if depth >= self.limits["maxBlockDepth"]:
            self.skip("INSERT", layer_id, "block_nesting")
            return
        units = int(_attr(block.block_record, "units", 0) or 0)
        if units:
            self.block_units[name] = units
        insert_id = self.make_id(prefix, entity)
        try:
            count = int(entity.mcount)
        except Exception:
            count = 1
        if count > self.limits["maxExpandedEntities"]:
            raise FloorPlanReadError("too_many_entities", f"An array insert in the drawing makes {count:,} copies, "
                                     "more than the import supports.")
        try:
            copies = entity.multi_insert() if count > 1 else (entity,)
            for index, instance in enumerate(copies):
                if index:
                    self.count_entity()
                local = instance.matrix44()
                if not all(math.isfinite(v) for v in local) or abs(_determinant_2d(local)) < 1e-300:
                    self.skip("INSERT", layer_id, "degenerate_transform")
                    continue
                combined = local if matrix is None else Matrix44.chain(local, matrix)
                inner = f"{insert_id}[{index}]/" if count > 1 else f"{insert_id}/"
                self.walk(block, combined, layer_name, inner, blocks + (name,), depth + 1)
                # Attributes sit beside the insert, in the space that holds it, not inside the block. Each one counts
                # as an entity, and one on layer 0 takes the insert's own (effective) layer.
                for position, attrib in enumerate(getattr(instance, "attribs", None) or []):
                    self.count_entity()
                    attrib_layer = _attr(attrib, "layer", "0") or "0"
                    if attrib_layer == "0":
                        attrib_layer = layer_name
                    self.text(attrib, "ATTRIB", matrix, self.layer(attrib_layer), inner, blocks,
                              fallback=f"@{position}")
        except (FloorPlanReadError, MemoryError, RecursionError):
            raise
        except Exception:
            self.skip("INSERT", layer_id, "unreadable")

    def curve(self, entity, kind, matrix, layer_id, prefix, blocks) -> None:
        cap = self.limits["maxEntityVertices"]
        # Curves are sampled in the block's own space, so the tolerance shrinks by the most the insert stretches.
        stretch = max(_largest_stretch(matrix), 1e-12) if matrix is not None else 1.0
        tolerance = self.tolerance
        points = None
        try:
            if kind == "POLYLINE" and (entity.is_poly_face_mesh or entity.is_polygon_mesh):
                self.skip(kind, layer_id, "mesh")
                return
            for _ in range(4):  # a curve too detailed at the declared tolerance is retried coarser, then skipped
                collected = []
                for vertex in _flatten(entity, kind, tolerance / stretch):
                    collected.append(vertex)
                    if len(collected) > cap:
                        break
                if len(collected) <= cap:
                    points = collected
                    break
                tolerance *= 10
            if points is not None and matrix is not None:
                points = [(v.x, v.y, v.z) for v in matrix.transform_vertices(points)]
        except MemoryError:
            raise
        except Exception:
            self.skip(kind, layer_id, "unreadable")
            return
        if points is None:
            self.skip(kind, layer_id, "too_many_vertices")
            return
        bound = self.limits["maxCoordinate"]
        if not points or not all(_finite(c, bound) for p in points for c in p):
            self.skip(kind, layer_id, "coordinates_out_of_range")
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        if max(zs) - min(zs) > 1e-6 * span:
            self.skip(kind, layer_id, "nonplanar")
            return
        flat = list(zip(xs, ys))
        closed = _is_closed(entity, kind)
        if not closed and len(flat) > 2 and math.dist(flat[0], flat[-1]) <= 1e-9 * span:
            closed = True  # drawn back to its start
        if closed and len(flat) > 1 and math.dist(flat[0], flat[-1]) <= 1e-9 * span:
            flat.pop()
        if len(flat) < 2:
            self.skip(kind, layer_id, "degenerate")
            return
        if self.vertices + len(flat) > self.limits["maxVertices"]:
            raise FloorPlanReadError("too_many_vertices", "The drawing has more than "
                                     f"{self.limits['maxVertices']:,} points once its curves are drawn, more than "
                                     "the import supports.")
        self.vertices += len(flat)
        self.z_range[0] = min(self.z_range[0], zs[0])
        self.z_range[1] = max(self.z_range[1], zs[0])
        record = {"id": self.make_id(prefix, entity), "layer": layer_id, "type": kind, "closed": closed,
                  "points": flat}
        if tolerance != self.tolerance:
            record["tolerance"] = tolerance
        if blocks:
            record["blocks"] = [_name(b, 128) for b in blocks]
        self.records.append(record)

    def text(self, entity, kind, matrix, layer_id, prefix, blocks, fallback: str | None = None) -> None:
        from ezdxf.math import Vec3

        if self.texts >= self.limits["maxTexts"]:
            self.skip(kind, layer_id, "too_many_texts")
            return
        try:
            if kind == "ATTRIB" and entity.is_invisible:
                self.skip(kind, layer_id, "invisible")
                return
            raw = entity.plain_text()
            if kind == "MTEXT":
                ucs = entity.ucs()
                at = Vec3(ucs.origin)
                height = float(_attr(entity, "char_height", 1.0) or 1.0)
                direction = Vec3(ucs.ux)
                up = Vec3(ucs.uy) * height
                align = _ALIGN_BY_ATTACHMENT.get(int(_attr(entity, "attachment_point", 1) or 1), "TOP_LEFT")
                flipped = False
            else:
                ocs = entity.ocs()
                alignment, insert, align_point = entity.get_placement()
                align = getattr(alignment, "name", "LEFT")
                if align in ("LEFT", "ALIGNED", "FIT") or align_point is None:
                    anchor, align = insert, "LEFT"  # ALIGNED and FIT start at the insert point too
                else:
                    anchor = align_point
                at = Vec3(ocs.to_wcs(Vec3(anchor)))
                rotation = math.radians(float(_attr(entity, "rotation", 0.0) or 0.0))
                height = float(_attr(entity, "height", 1.0) or 1.0)
                direction = Vec3(ocs.to_wcs(Vec3(math.cos(rotation), math.sin(rotation), 0)))
                up = Vec3(ocs.to_wcs(Vec3(-math.sin(rotation), math.cos(rotation), 0))) * height
                generation = int(_attr(entity, "text_generation_flag", 0) or 0)
                flipped = bool(generation & 2) != bool(generation & 4)  # backward xor upside down
            if matrix is not None:
                at = matrix.transform(at)
                direction = matrix.transform_direction(direction)
                up = matrix.transform_direction(up)
        except MemoryError:
            raise
        except Exception:
            self.skip(kind, layer_id, "unreadable")
            return
        text, truncated = clean_text(raw, self.limits["maxTextBytes"])
        if not text:
            self.skip(kind, layer_id, "empty_text")
            return
        bound = self.limits["maxCoordinate"]
        values = (at.x, at.y, direction.x, direction.y, up.x, up.y)
        # Finite parts can still make an infinite length (a huge height turned 45 degrees and scaled).
        height = math.hypot(up.x, up.y) if all(math.isfinite(v) for v in values) else math.inf
        if not (_finite(at.x, bound) and _finite(at.y, bound) and _finite(height, bound)
                and math.isfinite(math.hypot(direction.x, direction.y))):
            self.skip(kind, layer_id, "coordinates_out_of_range")
            return
        if truncated:
            self.truncated_texts += 1
        self.texts += 1
        cross = direction.x * up.y - direction.y * up.x
        record = {"id": self.make_id(prefix, entity, fallback), "layer": layer_id, "type": kind,
                  "at": (at.x, at.y), "height": height,
                  "rotation": math.degrees(math.atan2(direction.y, direction.x)), "align": align,
                  "mirrored": (cross < 0) != flipped, "text": text}
        if blocks:
            record["blocks"] = [_name(b, 128) for b in blocks]
        self.records.append(record)


def _determinant_2d(matrix) -> float:
    rows = list(matrix.rows())
    return rows[0][0] * rows[1][1] - rows[0][1] * rows[1][0]


def _largest_stretch(matrix) -> float:
    """The most the matrix lengthens any block-space vector as seen in plan: the larger singular value of the 2x3
    map from block X/Y/Z to plan X/Y. A curve in a tilted OCS, or a tilted insert, reaches the plan through its Z
    part too. Scaled by the largest entry first so that squaring cannot overflow."""
    rows = list(matrix.rows())
    p = [rows[0][0], rows[1][0], rows[2][0]]  # plan X of the images of block X, Y and Z (row-vector convention)
    q = [rows[0][1], rows[1][1], rows[2][1]]  # plan Y
    largest = max(abs(value) for value in p + q)
    if not math.isfinite(largest) or largest == 0.0:
        return largest
    p = [value / largest for value in p]
    q = [value / largest for value in q]
    pp, qq = sum(v * v for v in p), sum(v * v for v in q)
    pq = sum(a * b for a, b in zip(p, q))
    total, det = pp + qq, max(pp * qq - pq * pq, 0.0)
    return largest * math.sqrt((total + math.sqrt(max(total * total - 4 * det, 0.0))) / 2)


def _arc_steps(radius: float, sweep: float, sagitta: float) -> int:
    """Chords for an arc of RADIUS through SWEEP radians that stay within SAGITTA of it; at least one per 45
    degrees, so a circle smaller than the tolerance still reads as round."""
    minimum = max(1, math.ceil(sweep / (math.pi / 4) - 1e-9))
    if not (radius > 0 and 0 < sagitta < radius):
        return minimum
    return max(minimum, math.ceil(sweep / (2.0 * math.acos(1.0 - sagitta / radius)) - 1e-9))


def _bulge_points(start, end, bulge: float, sagitta: float):
    """The arc a polyline bulge draws from START to END (2D), sampled on the true circle; END included, START not.
    A positive bulge turns counter-clockwise; its sweep is 4 * atan(bulge)."""
    from ezdxf.math import Vec2, bulge_to_arc

    center, _, _, radius = bulge_to_arc(Vec2(start), Vec2(end), bulge)
    sweep = 4.0 * math.atan(bulge)
    first = math.atan2(start[1] - center.y, start[0] - center.x)
    steps = _arc_steps(radius, abs(sweep), sagitta)
    for index in range(1, steps):
        angle = first + sweep * index / steps
        yield center.x + radius * math.cos(angle), center.y + radius * math.sin(angle)
    yield end[0], end[1]


def _polyline_points(vertices, closed: bool, sagitta: float, to_wcs):
    """Points of a polyline given as [(x, y, bulge)] in its own plane; TO_WCS lifts (x, y) to (x, y, z)."""
    count = len(vertices)
    if not count:
        return
    yield to_wcs(vertices[0][0], vertices[0][1])
    for index in range(count if closed else count - 1):
        x1, y1, bulge = vertices[index]
        x2, y2, _ = vertices[(index + 1) % count]
        if bulge and (x1, y1) != (x2, y2):
            if not math.isfinite(bulge):
                raise ValueError("bulge is not a number")
            for x, y in _bulge_points((x1, y1), (x2, y2), bulge, sagitta):
                yield to_wcs(x, y)
        else:
            yield to_wcs(x2, y2)


def _flatten(entity, kind: str, sagitta: float):
    """(x, y, z) points of a curve entity in the space that holds it (WCS there), each chord within SAGITTA of the
    true curve. Lines, polylines, arcs and circles are sampled exactly on the curve (not through Bezier
    approximations, whose own error grows with the radius); ellipses and splines use ezdxf's adaptive sampling of the
    exact curve."""
    from ezdxf.math import Vec3

    if kind == "LINE":
        yield tuple(Vec3(entity.dxf.start))
        yield tuple(Vec3(entity.dxf.end))
    elif kind in ("ARC", "CIRCLE"):
        ocs = entity.ocs()
        center = Vec3(entity.dxf.center)
        radius = abs(float(entity.dxf.radius))
        if kind == "CIRCLE":
            first, sweep = 0.0, math.tau
        else:
            first = math.radians(float(entity.dxf.start_angle))
            sweep = (math.radians(float(entity.dxf.end_angle)) - first) % math.tau or math.tau
        steps = _arc_steps(radius, sweep, sagitta)
        for index in range(steps + 1):
            angle = first + sweep * index / steps
            yield tuple(ocs.to_wcs(Vec3(center.x + radius * math.cos(angle), center.y + radius * math.sin(angle),
                                        center.z)))
    elif kind == "ELLIPSE":
        for vertex in entity.flattening(sagitta, segments=8):
            yield (vertex.x, vertex.y, vertex.z)
    elif kind == "SPLINE":
        for vertex in entity.flattening(sagitta, segments=4):
            yield (vertex.x, vertex.y, vertex.z)
    elif kind == "LWPOLYLINE":
        ocs = entity.ocs()
        elevation = float(_attr(entity, "elevation", 0.0) or 0.0)
        vertices = [(float(x), float(y), float(b)) for x, y, b in entity.get_points("xyb")]
        yield from _polyline_points(vertices, bool(entity.is_closed), sagitta,
                                    lambda x, y: tuple(ocs.to_wcs(Vec3(x, y, elevation))))
    elif kind == "POLYLINE":
        kept = [v for v in entity.vertices if not int(_attr(v, "flags", 0) or 0) & 16]  # not spline frame points
        if entity.is_3d_polyline:
            points = [tuple(Vec3(v.dxf.location)) for v in kept]
            yield from points
            if entity.is_closed and points:
                yield points[0]
        else:
            ocs = entity.ocs()
            elevation = Vec3(_attr(entity, "elevation", (0, 0, 0))).z
            vertices = [(Vec3(v.dxf.location).x, Vec3(v.dxf.location).y, float(_attr(v, "bulge", 0.0) or 0.0))
                        for v in kept]
            yield from _polyline_points(vertices, bool(entity.is_closed), sagitta,
                                        lambda x, y: tuple(ocs.to_wcs(Vec3(x, y, elevation))))


def _is_closed(entity, kind: str) -> bool:
    if kind == "CIRCLE":
        return True
    if kind in ("LWPOLYLINE", "POLYLINE"):
        return bool(entity.is_closed)
    if kind == "SPLINE":
        return bool(entity.closed)
    if kind == "ELLIPSE":
        span = (float(entity.dxf.end_param) - float(entity.dxf.start_param)) % math.tau
        return span < 1e-9 or abs(span - math.tau) < 1e-9
    return False


def _header_point(doc, name):
    try:
        value = doc.header.get(name)
        if value is None:
            return None
        x, y = float(value[0]), float(value[1])
        return (x, y) if math.isfinite(x) and math.isfinite(y) and abs(x) < 1e20 and abs(y) < 1e20 else None
    except Exception:
        return None


def units_of(doc) -> dict:
    try:
        code = int(doc.header.get("$INSUNITS", 0) or 0)
    except (TypeError, ValueError):
        code = 0
    meters = UNIT_METERS.get(code)
    result = {"insunits": code, "name": UNIT_NAMES.get(code, f"unit code {code}"), "metersPerUnit": meters,
              "status": "declared" if meters is not None else "unresolved"}
    try:
        result["measurement"] = "metric" if int(doc.header.get("$MEASUREMENT", 0) or 0) == 1 else "imperial"
    except (TypeError, ValueError):
        pass
    return result


def curve_tolerance(doc, units: dict) -> float:
    """The largest distance a flattened curve may stray from the true curve, in drawing units: 2 mm when the units
    are known; otherwise 1/100,000 of the header's extents diagonal (0.01 units when the header has none)."""
    if units["metersPerUnit"]:
        return 0.002 / units["metersPerUnit"]
    low, high = _header_point(doc, "$EXTMIN"), _header_point(doc, "$EXTMAX")
    if low and high and high[0] > low[0] and high[1] > low[1]:
        return max(math.dist(low, high) * 1e-5, 1e-9)
    return 0.01


def read_dxf(path: str, *, limits: dict | None = None, source_sha256: str | None = None) -> dict:
    """The normalized geometry artifact of the DXF at PATH (see the module docstring). Raises FloorPlanReadError."""
    try:
        import ezdxf
    except ImportError:
        raise FloorPlanReadError("reader_unavailable", "The DXF reader (ezdxf) is not installed for the Python that "
                                 "runs the app. Install the app's requirements, then restart it.") from None

    limits = {**DEFAULT_LIMITS, **(limits or {})}
    size = os.path.getsize(path)
    if size > limits["maxFileBytes"]:
        raise FloorPlanReadError("too_large", f"The drawing is larger than {limits['maxFileBytes'] // (1024 * 1024)} "
                                 "MB, more than the import supports.")
    with open(path, "rb") as handle:
        sniff(handle.read(4096))
        handle.seek(max(0, size - 256))
        check_tail(handle.read())
    try:
        doc = ezdxf.readfile(path)
    except MemoryError:
        raise
    except Exception:
        raise FloorPlanReadError("not_readable", "The drawing could not be read: it is damaged or not a DXF file the "
                                                 "import understands.") from None
    msp = doc.modelspace()
    source_entities = len(msp)
    if source_entities > limits["maxSourceEntities"]:
        raise FloorPlanReadError("too_many_entities", f"The drawing has {source_entities:,} entities in model space, "
                                 f"more than the {limits['maxSourceEntities']:,} the import supports.")
    units = units_of(doc)
    tolerance = curve_tolerance(doc, units)
    reader = _Reader(doc, limits, tolerance)
    reader.walk(msp, None, None, "", (), 0)

    report_rows = limits["maxReportRows"]
    paper = []
    for layout in doc.layouts:
        if layout.name == "Model":
            continue
        count = sum(1 for entity in layout if entity.dxftype() != "VIEWPORT")
        if count and len(paper) < report_rows:
            paper.append({"name": _name(layout.name, 128), "entities": count})
    for block in doc.blocks:  # external references that no insert in model space places are listed too
        if int(_attr(block.block, "flags", 0) or 0) & _XREF_FLAGS and block.name not in reader.xref_names:
            reader.xref_names.append(block.name)
    xrefs = []
    for name in reader.xref_names[:report_rows]:
        block = doc.blocks.get(name)
        target = _attr(block.block, "xref_path", "") if block is not None else ""
        # Only the file name: a full path can name the author's folders.
        xrefs.append({"name": _name(name, 128), "file": _name(os.path.basename(str(target).replace("\\", "/")), 128)})
    source = {"sha256": source_sha256, "bytes": size, "dxfVersion": str(doc.dxfversion), "encoding": str(doc.encoding)}
    # The parsed document is the biggest thing in memory; let it go before the output is built (its entities point
    # back at it, so only the cycle collector frees them).
    reader.doc = None
    doc = msp = block = layout = None
    gc.collect()

    # Rebase on the minimum of everything drawn, round, and drop points that rounding made repeat. Records are
    # rewritten in place so the drawing is never held twice.
    low_x = low_y = math.inf
    for record in reader.records:
        for x, y in record["points"] if "points" in record else (record["at"],):
            low_x, low_y = min(low_x, x), min(low_y, y)
    origin = (_r6(low_x), _r6(low_y)) if math.isfinite(low_x) else (0.0, 0.0)
    stats = {layer_id: {"entities": 0, "texts": 0, "vertices": 0, "box": None} for layer_id in reader.layer_info}
    entities = []
    vertices = 0
    for record in reader.records:
        out = record
        stat = stats[record["layer"]]
        if "points" in record:
            points = []
            for x, y in record["points"]:
                point = [_r6(x - origin[0]), _r6(y - origin[1])]
                if not points or point != points[-1]:
                    points.append(point)
            closed = record["closed"]
            if closed and len(points) > 1 and points[0] == points[-1]:
                points.pop()
            if len(points) < 2:
                reader.skip(record["type"], record["layer"], "degenerate")
                continue
            out["closed"] = closed and len(points) > 2
            out["points"] = points
            if "tolerance" in out:
                out["tolerance"] = _sig(out["tolerance"])
            stat["entities"] += 1
            stat["vertices"] += len(points)
            vertices += len(points)
            drawn = points
        else:
            out["at"] = [_r6(record["at"][0] - origin[0]), _r6(record["at"][1] - origin[1])]
            out["height"] = _r6(record["height"])
            out["rotation"] = _r6(record["rotation"])
            stat["texts"] += 1
            drawn = [out["at"]]
        box = stat["box"]
        for x, y in drawn:
            if box is None:
                box = stat["box"] = [x, y, x, y]
            else:
                box[0], box[1], box[2], box[3] = min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)
        entities.append(out)
    layers = []
    for layer_id, info in reader.layer_info.items():
        stat = stats[layer_id]
        layers.append(dict(info, entities=stat["entities"], texts=stat["texts"], vertices=stat["vertices"],
                           extents=({"min": stat["box"][:2], "max": stat["box"][2:]} if stat["box"] else None)))
    boxes = [stat["box"] for stat in stats.values() if stat["box"]]
    extents = ({"min": [min(b[0] for b in boxes), min(b[1] for b in boxes)],
                "max": [max(b[2] for b in boxes), max(b[3] for b in boxes)]} if boxes else None)

    if xrefs:
        reader.warn("external_references", f"The drawing refers to {len(reader.xref_names)} external drawing(s) "
                    "that are not part of this file; they are not imported.")
    if paper:
        reader.warn("paper_space", "Paper-space sheets are not imported; only model space is read.")
    if reader.truncated_texts:
        reader.warn("long_text", f"{reader.truncated_texts} label(s) were longer than {limits['maxTextBytes']} bytes "
                    "and were shortened.")
    if reader.block_units:
        reader.warn("block_units", "Some blocks carry their own unit setting; their insert scales are used as stored "
                    "(the block unit is not applied a second time).")
    if units["status"] != "declared":
        said = ("The drawing does not say what unit it is drawn in" if units["name"] == "unitless"
                else f"The drawing's unit ({units['name']}) is not a building unit")
        reader.warn("units_unresolved", said + ": choose the unit or calibrate with a known distance before aligning "
                    "it.")
    if not entities:
        reader.warn("empty", "The drawing has nothing the import can show in model space.")
    unsupported = [{"type": kind, "layer": layer_id, "reason": reason, "count": count}
                   for (kind, layer_id, reason), count in sorted(reader.unsupported.items())]
    if len(unsupported) > report_rows:
        reader.warn("report_trimmed", f"{len(unsupported) - report_rows} more unsupported entity groups are not "
                    "listed.")
        unsupported = unsupported[:report_rows]

    return {
        "schema": SCHEMA,
        "schemaVersion": SCHEMA_VERSION,
        "parser": {"name": "ezdxf", "version": ezdxf.__version__, "adapterVersion": ADAPTER_VERSION},
        "source": source,
        "units": units,
        "curveTolerance": _sig(tolerance),
        "origin": [origin[0], origin[1]],
        "extents": extents,
        "elevation": ({"min": _r6(reader.z_range[0]), "max": _r6(reader.z_range[1])}
                      if math.isfinite(reader.z_range[0]) else None),
        "counts": {"sourceEntities": source_entities, "expandedEntities": reader.expanded,
                   "keptEntities": len(entities), "texts": reader.texts, "vertices": vertices,
                   "unsupported": sum(reader.unsupported.values())},
        "limits": limits,
        "layers": layers,
        "entities": entities,
        "unsupported": unsupported,
        "externalReferences": xrefs,
        "paperSpace": paper,
        "blockUnits": [{"block": _name(name, 128), "units": UNIT_NAMES.get(code, str(code))}
                       for name, code in sorted(reader.block_units.items())][:report_rows],
        "warnings": reader.warnings,
    }


def manifest_of(geometry: dict) -> dict:
    """Everything but the entities: what the import panel shows before it fetches the drawing."""
    return {key: value for key, value in geometry.items() if key != "entities"}


def _write_json(path: str, value) -> None:
    temporary = path + ".part"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(temporary, path)


def worker_main(argv: list[str]) -> int:
    """Worker process entry: worker_main([dxf_path, out_dir, limits_json, source_sha256]). Writes geometry.json and
    manifest.json into OUT_DIR and returns 0, or writes error.json ({code, message}) and returns 3 (4 when memory
    ran out)."""
    dxf_path, out_dir = argv[0], argv[1]
    limits = json.loads(argv[2]) if len(argv) > 2 and argv[2] else None
    source_sha256 = argv[3] if len(argv) > 3 and argv[3] else None
    try:
        geometry = read_dxf(dxf_path, limits=limits, source_sha256=source_sha256)
        _write_json(os.path.join(out_dir, "geometry.json"), geometry)
        _write_json(os.path.join(out_dir, "manifest.json"), manifest_of(geometry))
        return 0
    except FloorPlanReadError as error:
        _write_json(os.path.join(out_dir, "error.json"), {"code": error.code, "message": error.message})
        return 3
    except MemoryError:
        geometry = None  # let the collector take the partial drawing before writing the error
        try:
            _write_json(os.path.join(out_dir, "error.json"), {"code": "too_large", "message": "Reading the drawing "
                        "needs more memory than the import allows."})
        except Exception:
            pass
        return 4


if __name__ == "__main__":  # pragma: no cover - the worker loads this file by path and calls worker_main
    sys.exit(worker_main(sys.argv[1:]))
