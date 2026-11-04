"""Synthetic DXF drawings for the floor-plan import tests (docs/facility-floor-plan-import-plan.md, section 11,
"Fixture DXFs to create"). Each builder writes a small drawing with ezdxf into a folder and returns its path; the
coordinates are documented here and the tests check the reader's output against these hand-written numbers, never
against ezdxf itself. Large stress drawings are generated in the tests, never committed. All of them are written for
these tests (no third-party content).

The asymmetric factory, in meters (fixture 1); every other unit fixture is the same drawing scaled:
- A-WALL-EXT: closed outline (0,0) (30,0) (30,20) (0,20).
- A-WALL: a 10 m partition 0.2 m thick, faces at x = 10 and x = 10.2 from y = 0 to y = 10, broken by a 1.2 m door
  gap from y = 4 to y = 5.2; jamb lines across the faces at y = 4 and y = 5.2, and an end line at y = 10.
- A-AREA: a 4 m by 5 m room, closed (20,12) (24,12) (24,17) (20,17).
- S-COLS: an off-center column, a circle at (17.5, 6.5), radius 0.25.
- A-DOOR: the door swing, an arc centered (10.2, 4) with radius 1.2 from 0 to 90 degrees.
- A-TEXT: TEXT "Office" at (21, 14), height 0.3; MTEXT "Workshop" / "Bay 1" at (3, 15), height 0.5.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf

FACTORY_OUTLINE = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0)]
FACTORY_FACES = [((10.0, 0.0), (10.0, 4.0)), ((10.0, 5.2), (10.0, 10.0)),
                 ((10.2, 0.0), (10.2, 4.0)), ((10.2, 5.2), (10.2, 10.0))]
FACTORY_JAMBS = [((10.0, 4.0), (10.2, 4.0)), ((10.0, 5.2), (10.2, 5.2)), ((10.0, 10.0), (10.2, 10.0))]
FACTORY_ROOM = [(20.0, 12.0), (24.0, 12.0), (24.0, 17.0), (20.0, 17.0)]
FACTORY_COLUMN = ((17.5, 6.5), 0.25)
FACTORY_DOOR_ARC = ((10.2, 4.0), 1.2, 0.0, 90.0)

UNIT_CODES = {"meters": 6, "millimeters": 4, "inches": 1, "feet": 2}
UNIT_PER_METER = {"meters": 1.0, "millimeters": 1000.0, "inches": 1 / 0.0254, "feet": 1 / 0.3048}


def _layers(doc):
    for name, color in (("A-WALL-EXT", 1), ("A-WALL", 2), ("A-AREA", 3), ("S-COLS", 4), ("A-DOOR", 5),
                        ("A-TEXT", 7)):
        doc.layers.add(name, color=color)


def factory(folder: Path, *, unit: str = "meters", offset=(0.0, 0.0), insunits: int | None = None,
            name: str | None = None) -> Path:
    """Fixture 1 (meters) and 2 (the same drawing in millimeters, inches or feet); OFFSET (in the drawing's own
    units) moves everything, for fixture 4 (survey-sized coordinates). INSUNITS overrides the header (fixture 3)."""
    k = UNIT_PER_METER[unit]
    ox, oy = offset
    doc = ezdxf.new("R2010", units=UNIT_CODES[unit] if insunits is None else insunits)
    if insunits is not None:
        doc.header["$INSUNITS"] = insunits
    _layers(doc)
    msp = doc.modelspace()

    def p(x, y):
        return (x * k + ox, y * k + oy)

    msp.add_lwpolyline([p(*q) for q in FACTORY_OUTLINE], close=True, dxfattribs={"layer": "A-WALL-EXT"})
    for a, b in FACTORY_FACES + FACTORY_JAMBS:
        msp.add_line(p(*a), p(*b), dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline([p(*q) for q in FACTORY_ROOM], close=True, dxfattribs={"layer": "A-AREA"})
    (cx, cy), radius = FACTORY_COLUMN
    msp.add_circle(p(cx, cy), radius * k, dxfattribs={"layer": "S-COLS"})
    (ax, ay), arc_radius, start, end = FACTORY_DOOR_ARC
    msp.add_arc(p(ax, ay), arc_radius * k, start, end, dxfattribs={"layer": "A-DOOR"})
    msp.add_text("Office", height=0.3 * k, dxfattribs={"layer": "A-TEXT", "insert": p(21.0, 14.0)})
    msp.add_mtext("Workshop\\PBay 1", dxfattribs={"layer": "A-TEXT", "insert": p(3.0, 15.0), "char_height": 0.5 * k})
    path = Path(folder) / (name or f"factory-{unit}.dxf")
    doc.saveas(path)
    return path


def unitless_segment(folder: Path, *, insunits: int = 0, name: str = "unitless.dxf") -> Path:
    """Fixture 3: a single 10,000-unit segment from (0, 0) to (10000, 0) with the given unit header (0 = none)."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = insunits
    doc.modelspace().add_line((0, 0), (10000, 0), dxfattribs={"layer": "A-WALL"})
    path = Path(folder) / name
    doc.saveas(path)
    return path


def blocks(folder: Path) -> Path:
    """Fixture 5, in meters.
    - Block COL (base 0,0): a 0.4 m square on layer 0 from (-0.2,-0.2) to (0.2,0.2), and TEXT "C" on S-TEXT at (0,0).
    - Block ROW: three COL inserts on layer 0 at x = 0, 6, 12.
    - INSERT ROW on S-COLS at (2, 3), rotated 90 degrees: column squares centered (2,3), (2,9), (2,15), on S-COLS.
    - Block DOOR (base 0,0): ARC center (0,0) radius 1 from 0 to 90 degrees, and LINE (0,0)-(1,0), both on layer 0.
      INSERT DOOR on A-DOOR at (5, 5) mirrored (xscale -1): the line runs (5,5)-(4,5) and the arc from (4,5) to (5,6).
    - INSERT COL on S-COLS at (20, 20) with xscale 2 and yscale 0.5: a 0.8 m by 0.2 m rectangle (19.6..20.4,
      19.9..20.1).
    - MINSERT COL on S-GRID at (30, 0): 3 columns 5 m apart and 2 rows 4 m apart, centers (30|35|40, 0|4).
    - Block MM-PART carries its own unit (millimeters) and a LINE from (0,0) to (1000,0); INSERT MM-PART at (0, 30)
      with scale 0.001, as a CAD program stores it: the line is 1 m long, (0,30)-(1,30) (scaled once, not twice).
    - Block BASED (base point 100, 0): LINE (100,0)-(110,0); INSERT BASED at (50, 50): (50,50)-(60,50).
    """
    doc = ezdxf.new("R2010", units=6)
    for name in ("S-COLS", "S-TEXT", "A-DOOR", "S-GRID"):
        doc.layers.add(name)
    col = doc.blocks.new("COL")
    col.add_lwpolyline([(-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2)], close=True, dxfattribs={"layer": "0"})
    col.add_text("C", height=0.1, dxfattribs={"layer": "S-TEXT", "insert": (0, 0)})
    row = doc.blocks.new("ROW")
    for x in (0, 6, 12):
        row.add_blockref("COL", (x, 0), dxfattribs={"layer": "0"})
    door = doc.blocks.new("DOOR")
    door.add_arc((0, 0), 1, 0, 90, dxfattribs={"layer": "0"})
    door.add_line((0, 0), (1, 0), dxfattribs={"layer": "0"})
    mm_part = doc.blocks.new("MM-PART")
    mm_part.block_record.dxf.units = 4
    mm_part.add_line((0, 0), (1000, 0), dxfattribs={"layer": "0"})
    based = doc.blocks.new("BASED", base_point=(100, 0))
    based.add_line((100, 0), (110, 0), dxfattribs={"layer": "0"})
    msp = doc.modelspace()
    msp.add_blockref("ROW", (2, 3), dxfattribs={"layer": "S-COLS", "rotation": 90})
    msp.add_blockref("DOOR", (5, 5), dxfattribs={"layer": "A-DOOR", "xscale": -1})
    msp.add_blockref("COL", (20, 20), dxfattribs={"layer": "S-COLS", "xscale": 2, "yscale": 0.5})
    grid = msp.add_blockref("COL", (30, 0), dxfattribs={"layer": "S-GRID"})
    grid.dxf.column_count = 3
    grid.dxf.row_count = 2
    grid.dxf.column_spacing = 5
    grid.dxf.row_spacing = 4
    msp.add_blockref("MM-PART", (0, 30), dxfattribs={"layer": "A-PART", "xscale": 0.001, "yscale": 0.001,
                                                       "zscale": 0.001})
    msp.add_blockref("BASED", (50, 50), dxfattribs={"layer": "A-PART"})
    path = Path(folder) / "blocks.dxf"
    doc.saveas(path)
    return path


def curves(folder: Path) -> Path:
    """Fixture 6, in meters.
    - LWPOLYLINE on A-CURVE: (0,0) bulge 1 to (10,0), then straight to (10,-5): a half circle of radius 5 centered
      (5,0) bulging to negative y (bulge > 0 turns counter-clockwise from (0,0) to (10,0)), then a 5 m line.
    - ARC on A-CURVE with extrusion (0,0,-1): OCS center (20,0), radius 2, 0 to 90 degrees; in world coordinates the
      center is (-20, 0) and the arc runs from (-22, 0) to (-20, 2) (clockwise seen from above).
    - CIRCLE on A-CURVE at (40, 0), radius 3: closed.
    """
    doc = ezdxf.new("R2010", units=6)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0, 0, 0, 1), (10, 0, 0, 0, 0), (10, -5, 0, 0, 0)], format="xyseb",
                       dxfattribs={"layer": "A-CURVE"})
    msp.add_arc((20, 0), 2, 0, 90, dxfattribs={"layer": "A-CURVE", "extrusion": (0, 0, -1)})
    msp.add_circle((40, 0), 3, dxfattribs={"layer": "A-CURVE"})
    path = Path(folder) / "curves.dxf"
    doc.saveas(path)
    return path


def hostile(folder: Path) -> dict:
    """Fixture 10: drawings the reader must refuse or report, never crash on. Returns {name: path}."""
    folder = Path(folder)
    out = {}
    # A block that inserts itself, an external reference, a 10,000-character label, an HTML-like label, a hatch and
    # a dimension, and a paper-space sheet.
    doc = ezdxf.new("R2010", units=6)
    loop = doc.blocks.new("LOOP")
    loop.add_line((0, 0), (1, 0))
    loop.add_blockref("LOOP", (2, 0))
    doc.add_xref_def("C:/private/projects/base-building.dxf", "BASE-XREF")
    msp = doc.modelspace()
    msp.add_blockref("LOOP", (0, 0), dxfattribs={"layer": "A-LOOP"})
    msp.add_blockref("BASE-XREF", (0, 0), dxfattribs={"layer": "A-XREF"})
    msp.add_text("x" * 10_000, height=1, dxfattribs={"layer": "A-TEXT", "insert": (0, 5)})
    msp.add_text("<script>alert(1)</script>\u202e", height=1, dxfattribs={"layer": "A-TEXT", "insert": (0, 8)})
    hatch = msp.add_hatch(color=2, dxfattribs={"layer": "A-HATCH"})
    hatch.paths.add_polyline_path([(0, 0), (1, 0), (1, 1)], is_closed=True)
    msp.add_linear_dim(base=(0, -2), p1=(0, 0), p2=(5, 0), dxfattribs={"layer": "A-DIMS"}).render()
    msp.add_line((0, 0), (3, 4), dxfattribs={"layer": "A-WALL"})
    doc.paperspace().add_line((0, 0), (1, 1))
    out["mixed"] = folder / "hostile-mixed.dxf"
    doc.saveas(out["mixed"])
    # A coordinate that is not a number.
    doc = ezdxf.new("R2010", units=6)
    doc.modelspace().add_line((0, 0), (1234.5678, 0), dxfattribs={"layer": "A-WALL"})
    doc.modelspace().add_line((0, 1), (2, 1), dxfattribs={"layer": "A-WALL"})
    text_path = folder / "hostile-nan.dxf"
    doc.saveas(text_path)
    text_path.write_text(text_path.read_text(encoding="utf-8").replace("1234.5678", "nan"), encoding="utf-8")
    out["nan"] = text_path
    # A truncated file, a binary DXF, a DWG header, a zip archive and plain text.
    full = folder / "complete.dxf"
    factory(folder, name="complete.dxf")
    data = full.read_bytes()
    (folder / "hostile-truncated.dxf").write_bytes(data[: len(data) // 2])
    out["truncated"] = folder / "hostile-truncated.dxf"
    doc = ezdxf.new("R2010", units=6)
    doc.modelspace().add_line((0, 0), (1, 0))
    out["binary"] = folder / "hostile-binary.dxf"
    doc.saveas(out["binary"], fmt="bin")
    out["dwg"] = folder / "hostile.dwg.dxf"
    out["dwg"].write_bytes(b"AC1032\x00\x00\x00\x00\x00" + b"\x00" * 64)
    out["zip"] = folder / "hostile-zip.dxf"
    out["zip"].write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    out["text"] = folder / "hostile-text.dxf"
    out["text"].write_text("hello, this is not a drawing\n", encoding="utf-8")
    return out


def many_lines(folder: Path, count: int, *, name: str = "many.dxf", layers: int = 1) -> Path:
    """COUNT parallel 1 m lines, 0.1 m apart, spread over LAYERS layers (fixture 11, sized by the test)."""
    doc = ezdxf.new("R2010", units=6)
    msp = doc.modelspace()
    for index in range(count):
        msp.add_line((0, index * 0.1), (1, index * 0.1), dxfattribs={"layer": f"L-{index % layers}"})
    path = Path(folder) / name
    doc.saveas(path)
    return path
