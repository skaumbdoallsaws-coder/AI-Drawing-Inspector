"""Basic shape families (docs/sage-basic-shapes-plan.md, BS1): building structure, safety, overhead services, roof
sheeting and simple equipment, each a few parameters with defaults and limits and one builder on the shape kernel
(primitives.py).

`build_asset(family, parameters)` checks the parameters against the family's JSON schema, fills in the defaults,
rounds lengths to the millimetre and returns the GLB with its catalog entry. The asset id comes from the family and
the rounded parameters, so asking twice for the same thing gives the same asset, which the 3D view then instances.

Every model follows the kernel's rules: centred, base at y = 0, length along x. Overhead parts are tagged 'overhead'
(the 3D view's roof frame and services layer) and roof sheeting 'roof-sheeting' (its own layer, hidden at first).
Sizes and colours come from the hand-built Factory 02 models (2026-10-30). They are illustrations, not engineering,
and every description says so.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Callable

from .primitives import Finish, Mesh, glb, on_floor, size_of, verify

GENERATOR = "ai_inspector/industrial_assets/shape_families.py"
FOLDER = "generated/industrial_assets/authored"   # where BS2 writes the models (decision 1: a shared library)
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
MAX_TRIANGLES = 250_000

STEEL, JOIST_STEEL, PLATE = "#c3cad0", "#d4d9dd", "#858d94"   # light enough to read under the Machine shop scene
YELLOW, BLACK = "#f5c400", "#26292c"
GALVANIZED, HANGER = "#a8b0b8", "#2b3036"
SPRINKLER_RED, BRASS = "#b3261e", "#c9b37e"
HOUSING = "#3f4650"
MEMBRANE, DECK_UNDER, FASCIA = "#d5dade", "#9aa3ab", "#7f888e"
# The library finish a high-bay lens comes lit with (static/facility_library/appearances.json).
LIT_LENS = "light-cool-white-led"

STRUCTURAL = "Illustrative only; no structural sizing, load or fire rating."
BARRIER = "Illustrative only; not a certified product and no impact rating."


@dataclass(frozen=True)
class Param:
    kind: str   # "length" (metres, rounded to the millimetre), "count" (a whole number) or "color" ('#rrggbb')
    default: Any
    low: float | None = None
    high: float | None = None
    doc: str = ""


@dataclass(frozen=True)
class Family:
    name: str
    label: str
    summary: str
    category: str
    tags: tuple
    params: dict
    build: Callable[[dict], list]
    title: Callable[[dict], str]
    describe: Callable[[dict], str]
    key: Callable[[dict], str]
    disclaimer: str


def _mm(value: float) -> int:
    return int(round(value * 1000))


def _g(value: float) -> str:
    return f"{value:g}"


def _length(default, low, high, doc):
    return Param("length", default, low, high, doc)


def _color(default, doc="colour"):
    return Param("color", default, doc=doc)


def _spread(first: float, last: float, most: float) -> list[float]:
    """Evenly spaced points from first to last, at most `most` apart (both ends included)."""
    count = max(1, math.ceil((last - first) / most - 1e-9))
    return [first + (last - first) * k / count for k in range(count + 1)]


# Structure -----------------------------------------------------------------------------------------------------

def _column(p):
    depth, width, height, plate_side = (p["sectionDepthMeters"], p["sectionWidthMeters"], p["heightMeters"],
                                        p["basePlateMeters"])
    if plate_side < max(depth, width):
        raise ValueError("basePlateMeters must be at least as wide as the column section")
    flange, web, plate_t = max(0.008, depth / 16), max(0.006, depth / 28), 0.03
    steel, plate = Mesh(), Mesh()
    for side in (-1, 1):
        x0, x1 = sorted((side * depth / 2, side * (depth / 2 - flange)))
        steel.box((x0, plate_t, -width / 2), (x1, height, width / 2), skip=("-y",))
    steel.box((-depth / 2 + flange, plate_t, -web / 2), (depth / 2 - flange, height, web / 2), skip=("-y", "+x", "-x"))
    plate.box((-plate_side / 2, 0.0, -plate_side / 2), (plate_side / 2, plate_t, plate_side / 2), skip=("-y",))
    return [("steel", steel, Finish(p["color"])), ("base plate", plate, Finish(p["plateColor"]))]


def _beam(p):
    half, depth, flange_w = p["lengthMeters"] / 2, p["depthMeters"], p["flangeWidthMeters"]
    flange, web = max(0.006, depth / 36), max(0.005, depth / 56)
    steel = Mesh()
    steel.box((-half, 0.0, -flange_w / 2), (half, flange, flange_w / 2))
    steel.box((-half, depth - flange, -flange_w / 2), (half, depth, flange_w / 2))
    steel.box((-half, flange, -web / 2), (half, depth - flange, web / 2), skip=("+y", "-y"))
    return [("steel", steel, Finish(p["color"]))]


def _joist(p):
    length, depth, width = p["lengthMeters"], p["depthMeters"], p["chordWidthMeters"]
    half = length / 2
    top_h, bottom_h = max(0.03, depth * 0.0933), max(0.03, depth * 0.08)
    bar = max(0.015, min(width / 3, depth * 0.0533))
    if top_h + bottom_h + 2 * bar > depth:
        raise ValueError("depthMeters leaves no room for the web between the chords")
    chords, webs = Mesh(), Mesh()
    chords.box((-half, depth - top_h, -width / 2), (half, depth, width / 2))
    chords.box((-half, 0.0, -width / 2), (half, bottom_h, width / 2))
    top_y, bottom_y, inset = depth - top_h / 2, bottom_h / 2, 0.05 + bar   # the end bars stay inside the chords
    panels = max(1, round((length - 2 * inset) / p["panelMeters"]))
    step = (length - 2 * inset) / panels
    for k in range(panels):
        x0 = -half + inset + k * step
        webs.bar((x0, top_y, 0.0), (x0 + step / 2, bottom_y, 0.0), bar)   # 4 sides, no caps: the ends sit in the chords
        webs.bar((x0 + step / 2, bottom_y, 0.0), (x0 + step, top_y, 0.0), bar)
    return [("chords", chords, Finish(p["color"])), ("web", webs, Finish(p["color"]))]


# Safety ----------------------------------------------------------------------------------------------------------

def _post_and_rail(p, *, post_radius, base, rails, rail_radius):
    """Posts on base plates at most postSpacingMeters apart, the end posts at both ends, rails between them."""
    half, height = p["lengthMeters"] / 2, p["heightMeters"]
    if 2 * half < base + 0.05:
        raise ValueError(f"lengthMeters must be at least {base + 0.05:g} m")
    first, last = -half + base / 2, half - base / 2
    posts, rail_mesh, bases = Mesh(), Mesh(), Mesh()
    xs = _spread(first, last, p["postSpacingMeters"])
    for x in xs:
        posts.prism("y", (x, 0.0), post_radius, 0.015, height)
        bases.box((x - base / 2, 0.0, -base / 2), (x + base / 2, 0.015, base / 2), skip=("-y",))
    for share in rails:
        if last - first > 0.01:
            rail_mesh.prism("x", (share * height, 0.0), rail_radius, first, last, caps=False)
    parts = [("posts", posts, Finish(p["color"])), ("rails", rail_mesh, Finish(p["color"])),
             ("bases", bases, Finish(p["baseColor"]))]
    return parts, len(xs)


def _pedestrian_barrier(p):
    return _post_and_rail(p, post_radius=0.08, base=0.24, rails=(0.30 / 1.1, 0.65 / 1.1, 1.00 / 1.1),
                          rail_radius=0.035)[0]


def _traffic_barrier(p):
    return _post_and_rail(p, post_radius=0.095, base=0.30, rails=(0.15 / 0.4, 0.31 / 0.4), rail_radius=0.065)[0]


def _post_count(p, base):
    half = p["lengthMeters"] / 2
    return len(_spread(-half + base / 2, half - base / 2, p["postSpacingMeters"]))


def _bollard(p):
    height, radius = p["heightMeters"], p["diameterMeters"] / 2
    plate_side, plate_t = 2 * radius + 0.12, 0.015
    post, plate = Mesh(), Mesh()
    post.prism("y", (0.0, 0.0), radius, plate_t, height, sides=24, smooth=True)
    plate.box((-plate_side / 2, 0.0, -plate_side / 2), (plate_side / 2, plate_t, plate_side / 2), skip=("-y",))
    return [("post", post, Finish(p["color"])), ("base plate", plate, Finish(p["baseColor"]))]


def _guard_rail(p):
    half, height, toe = p["lengthMeters"] / 2, p["heightMeters"], p["toeBoardMeters"]
    tube = 0.05
    first, last = -half + tube / 2, half - tube / 2
    frame, board = Mesh(), Mesh()
    for x in _spread(first, last, p["postSpacingMeters"]):
        frame.bar((x, 0.0, 0.0), (x, height, 0.0), tube, caps=True)
    for y in (height - tube / 2, height / 2):
        frame.bar((first, y, 0.0), (last, y, 0.0), tube)
    board.box((first, 0.01, -0.01), (last, toe, 0.01))
    return [("frame", frame, Finish(p["color"])), ("toe board", board, Finish(p["color"]))]


# Overhead services -------------------------------------------------------------------------------------------------

def _hangers(length: float, most: float) -> list[float]:
    half = length / 2
    return _spread(-half + 0.15, half - 0.15, most)


def _cable_tray(p):
    length, width, drop = p["lengthMeters"], p["widthMeters"], p["dropMeters"]
    half, strut, rail_h, rung_h = length / 2, 0.04, 0.10, 0.02
    rails, rungs, hangers = Mesh(), Mesh(), Mesh()
    for side in (-1, 1):
        z0, z1 = sorted((side * width / 2, side * (width / 2 - 0.01)))
        rails.box((-half, strut, z0), (half, strut + rail_h, z1))
    for x in _spread(-half + 0.05, half - 0.05, 0.3):
        rungs.box((x - 0.0125, strut, -width / 2 + 0.01), (x + 0.0125, strut + rung_h, width / 2 - 0.01))
    top = strut + rail_h + drop
    for x in _hangers(length, p["hangerSpacingMeters"]):
        hangers.box((x - 0.02, 0.0, -width / 2 - 0.06), (x + 0.02, strut, width / 2 + 0.06))
        for z in (-width / 2 - 0.04, width / 2 + 0.04):
            hangers.bar((x, strut, z), (x, top, z), 0.012)
    return [("rails", rails, Finish(p["color"])), ("rungs", rungs, Finish(p["color"])),
            ("hangers", hangers, Finish(p["hangerColor"]))]


def _pipe_run(p):
    length, radius, drop = p["lengthMeters"], p["diameterMeters"] / 2, p["dropMeters"]
    pipe, hangers = Mesh(), Mesh()
    pipe.prism("x", (radius, 0.0), radius, -length / 2, length / 2, sides=8 if radius < 0.075 else 16, smooth=True)
    for x in _hangers(length, p["hangerSpacingMeters"]):
        hangers.bar((x, 2 * radius, 0.0), (x, 2 * radius + drop, 0.0), 0.012)
    return [("pipe", pipe, Finish(p["color"])), ("hangers", hangers, Finish(p["hangerColor"]))]


def _sprinkler_line(p):
    length, radius, drop = p["lengthMeters"], p["diameterMeters"] / 2, p["dropMeters"]
    head_h = 0.07
    pipe_y = head_h + radius
    pipe, hangers, heads = Mesh(), Mesh(), Mesh()
    pipe.prism("x", (pipe_y, 0.0), radius, -length / 2, length / 2, smooth=True)
    xs = _hangers(length, p["headSpacingMeters"])
    for x in xs:
        hangers.bar((x, pipe_y + radius, 0.0), (x, pipe_y + radius + drop, 0.0), 0.012)
    for a, b in zip(xs, xs[1:]):   # a pendent head midway between hangers
        middle = (a + b) / 2
        heads.box((middle - 0.025, 0.0, -0.025), (middle + 0.025, head_h, 0.025))
    return [("pipe", pipe, Finish(p["color"])), ("hangers", hangers, Finish(p["hangerColor"])),
            ("heads", heads, Finish(p["headColor"]))]


def _sprinkler_heads(p):
    return max(0, len(_hangers(p["lengthMeters"], p["headSpacingMeters"])) - 1)


LIGHT_HOUSING_RADIUS = 0.21
LONGEST = 400.0          # one piece is at most 400 m long, as every length parameter says


def _high_bay_lights(p):
    count, spacing, pendant = p["count"], p["spacingMeters"], p["pendantMeters"]
    lens_h, housing_h = 0.015, 0.09
    lenses, housings, rods = Mesh(), Mesh(), Mesh()
    for k in range(count):
        x = (k - (count - 1) / 2) * spacing
        lenses.prism("y", (x, 0.0), 0.19, 0.0, lens_h, sides=16, smooth=True)
        housings.prism("y", (x, 0.0), LIGHT_HOUSING_RADIUS, lens_h, lens_h + housing_h, sides=16, smooth=True)
        rods.bar((x, lens_h + housing_h, 0.0), (x, lens_h + housing_h + pendant, 0.0), 0.016)
    lens = Finish("#ffffff", fields={"emissiveFactor": [1.0, 0.97, 0.9]}, extras={"facilityDefaultFinish": LIT_LENS})
    return [("housing", housings, Finish(p["housingColor"])), ("rod", rods, Finish(p["rodColor"])),
            ("lens", lenses, lens)]


# Roof sheeting (the 'roof-sheeting' layer) ----------------------------------------------------------------------

def _roof_deck(p):
    hx, hz, t = p["widthMeters"] / 2, p["depthMeters"] / 2, p["thicknessMeters"]
    top, under = Mesh(), Mesh()
    top.box((-hx, 0.0, -hz), (hx, t, hz), skip=("-y", "+x", "-x", "+z", "-z"))
    under.box((-hx, 0.0, -hz), (hx, t, hz), skip=("+y",))
    return [("membrane", top, Finish(p["color"])), ("deck", under, Finish(p["underColor"]))]


def _fascia(p):
    half, height, thickness = p["lengthMeters"] / 2, p["heightMeters"], p["thicknessMeters"]
    mesh = Mesh()
    mesh.box((-half, 0.0, -thickness / 2), (half, height, thickness / 2))
    return [("fascia", mesh, Finish(p["color"]))]


# Simple equipment --------------------------------------------------------------------------------------------------

def _tank(p):
    mesh = Mesh()
    mesh.prism("y", (0.0, 0.0), p["diameterMeters"] / 2, 0.0, p["heightMeters"], sides=32, smooth=True)
    return [("shell", mesh, Finish(p["color"]))]


def _bin(p):
    hx, hz, height = p["widthMeters"] / 2, p["depthMeters"] / 2, p["heightMeters"]
    wall = min(0.02, max(0.004, min(hx, hz) * 2 / 30))
    ix, iz = hx - wall, hz - wall
    mesh = Mesh()
    mesh.box((-hx, 0.0, -hz), (hx, height, hz), skip=("+y",))   # outside and bottom
    for corners, normal in (([(-ix, wall, -iz), (ix, wall, -iz), (ix, wall, iz), (-ix, wall, iz)], (0, 1, 0)),
                            ([(ix, wall, -iz), (ix, height, -iz), (ix, height, iz), (ix, wall, iz)], (-1, 0, 0)),
                            ([(-ix, wall, -iz), (-ix, height, -iz), (-ix, height, iz), (-ix, wall, iz)], (1, 0, 0)),
                            ([(-ix, wall, iz), (ix, wall, iz), (ix, height, iz), (-ix, height, iz)], (0, 0, -1)),
                            ([(-ix, wall, -iz), (ix, wall, -iz), (ix, height, -iz), (-ix, height, -iz)], (0, 0, 1))):
        mesh.face(corners, normal)   # the inside walls and floor, facing in
    for corners in ([(-hx, height, -hz), (hx, height, -hz), (ix, height, -iz), (-ix, height, -iz)],
                    [(hx, height, -hz), (hx, height, hz), (ix, height, iz), (ix, height, -iz)],
                    [(hx, height, hz), (-hx, height, hz), (-ix, height, iz), (ix, height, iz)],
                    [(-hx, height, hz), (-hx, height, -hz), (-ix, height, -iz), (-ix, height, iz)]):
        mesh.face(corners, (0, 1, 0))   # the rim
    return [("bin", mesh, Finish(p["color"]))]


PALLET_HEIGHT = 0.144


def _pallet_stack(p):
    hx, hz = p["lengthMeters"] / 2, p["widthMeters"] / 2
    board, stringer = 0.022, 0.1
    wood, load = Mesh(), Mesh()
    for level in range(p["pallets"]):
        y = level * PALLET_HEIGHT
        for x in (-hx + 0.05, 0.0, hx - 0.05):   # bottom deck boards, across
            wood.box((x - 0.05, y, -hz), (x + 0.05, y + board, hz))
        for z in (-hz + 0.0225, 0.0, hz - 0.0225):   # stringers, along
            wood.box((-hx, y + board, z - 0.0225), (hx, y + board + stringer, z + 0.0225))
        for x in _spread(-hx + 0.05, hx - 0.05, (2 * hx - 0.1) / 6):   # 7 top deck boards, across
            wood.box((x - 0.05, y + board + stringer, -hz), (x + 0.05, y + PALLET_HEIGHT, hz))
    if p["loadHeightMeters"] > 0:
        y = p["pallets"] * PALLET_HEIGHT
        load.box((-hx + 0.02, y, -hz + 0.02), (hx - 0.02, y + p["loadHeightMeters"], hz - 0.02))
    return [("pallets", wood, Finish(p["color"])), ("load", load, Finish(p["loadColor"]))]


def _workbench(p):
    hx, hz, height = p["widthMeters"] / 2, p["depthMeters"] / 2, p["heightMeters"]
    top_t, leg = 0.04, 0.05
    top, frame = Mesh(), Mesh()
    top.box((-hx, height - top_t, -hz), (hx, height, hz))
    for x in (-hx + 0.05, hx - 0.05):
        for z in (-hz + 0.05, hz - 0.05):
            frame.bar((x, 0.0, z), (x, height - top_t, z), leg)
    frame.box((-hx + 0.05, 0.15, -hz + 0.05), (hx - 0.05, 0.17, hz - 0.05))   # the lower shelf
    return [("top", top, Finish(p["topColor"])), ("frame", frame, Finish(p["frameColor"]))]


LENGTH_400 = dict(low=0.5, high=400)
FAMILIES: dict[str, Family] = {f.name: f for f in (
    Family("steel_column", "Steel column", "An H-section steel building column on a base plate.",
           "Building Structures", ("column", "structure", "building", "steel"),
           {"heightMeters": _length(10.0, 2, 30, "height, base plate included"),
            "sectionDepthMeters": _length(0.4, 0.1, 1.2, "H-section depth, flange to flange (along x)"),
            "sectionWidthMeters": _length(0.3, 0.1, 1.0, "flange width (along z)"),
            "basePlateMeters": _length(0.5, 0.15, 2.0, "side of the square base plate"),
            "color": _color(STEEL), "plateColor": _color(PLATE, "base plate colour")},
           _column, lambda p: f"Steel column {_g(p['heightMeters'])} m",
           lambda p: (f"Authored steel building column, {_g(p['heightMeters'])} m high: H-section "
                      f"{_mm(p['sectionDepthMeters'])} x {_mm(p['sectionWidthMeters'])} mm on a "
                      f"{_mm(p['basePlateMeters'])} mm base plate."),
           lambda p: f"{_mm(p['heightMeters'])}mm", STRUCTURAL),
    Family("i_beam", "Steel I-beam", "A steel I-beam: a girder on a column line or an edge beam on a wall top.",
           "Building Structures", ("beam", "girder", "structure", "building", "steel", "overhead"),
           {"lengthMeters": _length(10.0, 0.5, 400, "length (along x)"),
            "depthMeters": _length(0.9, 0.1, 2.0, "section depth"),
            "flangeWidthMeters": _length(0.3, 0.05, 1.0, "flange width"), "color": _color(STEEL)},
           _beam, lambda p: f"Steel I-beam {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored steel I-beam (girder or edge beam), {_g(p['lengthMeters'])} m long, I-section "
                      f"{_mm(p['depthMeters'])} x {_mm(p['flangeWidthMeters'])} mm."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", STRUCTURAL),
    Family("open_web_joist", "Open-web joist", "An open-web steel roof joist with a Warren web.",
           "Building Structures", ("joist", "roof", "structure", "building", "steel", "overhead"),
           {"lengthMeters": _length(20.0, 1, 400, "length (along x)"),
            "depthMeters": _length(0.75, 0.2, 2.0, "depth, chord to chord"),
            "panelMeters": _length(1.3, 0.3, 3.0, "Warren web panel length"),
            "chordWidthMeters": _length(0.12, 0.05, 0.4, "chord width"), "color": _color(JOIST_STEEL)},
           _joist, lambda p: f"Open-web joist {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored open-web steel joist, {_g(p['lengthMeters'])} m long and {_mm(p['depthMeters'])} mm "
                      f"deep, Warren web at {_g(p['panelMeters'])} m panels."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", STRUCTURAL),
    Family("pedestrian_barrier", "Pedestrian barrier", "Posts and three rails between a walkway and a forklift aisle.",
           "Safety", ("safety", "barrier", "pedestrian", "forklift", "guardrail"),
           {"lengthMeters": _length(10.0, **LENGTH_400, doc="length (along x)"),
            "heightMeters": _length(1.1, 0.6, 1.5, "height"),
            "postSpacingMeters": _length(2.0, 0.5, 3.0, "the most space between posts"),
            "color": _color(YELLOW), "baseColor": _color(BLACK, "base plate colour")},
           _pedestrian_barrier, lambda p: f"Pedestrian barrier {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored generic pedestrian barrier, {_g(p['lengthMeters'])} m long and "
                      f"{_g(p['heightMeters'])} m high: {_post_count(p, 0.24)} posts at most "
                      f"{_g(p['postSpacingMeters'])} m apart with three rails, for separating walkways from forklift "
                      "aisles."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", BARRIER),
    Family("low_traffic_barrier", "Low traffic barrier", "Low posts and two heavy rails against forklift wheels.",
           "Safety", ("safety", "barrier", "traffic", "forklift"),
           {"lengthMeters": _length(2.0, **LENGTH_400, doc="length (along x)"),
            "heightMeters": _length(0.4, 0.2, 1.0, "height"),
            "postSpacingMeters": _length(1.5, 0.5, 3.0, "the most space between posts"),
            "color": _color(YELLOW), "baseColor": _color(BLACK, "base plate colour")},
           _traffic_barrier, lambda p: f"Low traffic barrier {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored generic low traffic barrier, {_g(p['lengthMeters'])} m long and "
                      f"{_g(p['heightMeters'])} m high: {_post_count(p, 0.30)} posts with two heavy rails, for "
                      "guarding racks, walls and machines from forklift wheels."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", BARRIER),
    Family("bollard", "Bollard", "A steel bollard on a base plate.",
           "Safety", ("safety", "bollard", "forklift"),
           {"heightMeters": _length(1.2, 0.4, 2.0, "height"),
            "diameterMeters": _length(0.168, 0.06, 0.5, "post diameter"),
            "color": _color(YELLOW), "baseColor": _color(BLACK, "base plate colour")},
           _bollard, lambda p: f"Bollard {_g(p['heightMeters'])} m",
           lambda p: (f"Authored steel bollard, {_g(p['heightMeters'])} m high and {_mm(p['diameterMeters'])} mm "
                      "across, on a base plate."),
           lambda p: f"{_mm(p['heightMeters'])}x{_mm(p['diameterMeters'])}mm", BARRIER),
    Family("guard_rail", "Guard rail", "A guard rail with a mid rail and a toe board, for open edges.",
           "Safety", ("safety", "guardrail", "rail", "edge-protection"),
           {"lengthMeters": _length(10.0, **LENGTH_400, doc="length (along x)"),
            "heightMeters": _length(1.1, 0.9, 1.5, "top rail height"),
            "postSpacingMeters": _length(1.8, 0.5, 2.5, "the most space between posts"),
            "toeBoardMeters": _length(0.15, 0.09, 0.3, "toe board height"), "color": _color(YELLOW)},
           _guard_rail, lambda p: f"Guard rail {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored guard rail, {_g(p['lengthMeters'])} m long and {_g(p['heightMeters'])} m high: posts "
                      f"at most {_g(p['postSpacingMeters'])} m apart, a top and a mid rail and a "
                      f"{_mm(p['toeBoardMeters'])} mm toe board, for open edges of platforms and mezzanines."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", BARRIER),
    Family("cable_tray", "Cable tray", "A ladder cable tray on trapeze hangers, hung from the roof.",
           "Building Structures", ("overhead", "services", "building", "electrical", "cable-tray"),
           {"lengthMeters": _length(20.0, 1, 400, "length (along x)"),
            "widthMeters": _length(0.6, 0.1, 1.2, "tray width"),
            "dropMeters": _length(0.45, 0.05, 3.0, "hanger rods above the tray"),
            "hangerSpacingMeters": _length(3.0, 1.0, 6.0, "the most space between hangers"),
            "color": _color(GALVANIZED), "hangerColor": _color(HANGER, "hanger colour")},
           _cable_tray, lambda p: f"Cable tray {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored {_mm(p['widthMeters'])} mm ladder cable tray, {_g(p['lengthMeters'])} m long, on "
                      f"trapeze hangers at most {_g(p['hangerSpacingMeters'])} m apart."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", "Illustrative only; not an electrical design."),
    Family("pipe_run", "Pipe run", "A straight pipe on hanger rods, hung from the roof.",
           "Building Structures", ("overhead", "services", "building", "pipe"),
           {"lengthMeters": _length(20.0, **LENGTH_400, doc="length (along x)"),
            "diameterMeters": _length(0.1, 0.02, 1.0, "pipe diameter"),
            "dropMeters": _length(0.3, 0.05, 3.0, "hanger rods above the pipe"),
            "hangerSpacingMeters": _length(3.0, 1.0, 6.0, "the most space between hangers"),
            "color": _color(GALVANIZED), "hangerColor": _color(HANGER, "hanger colour")},
           _pipe_run, lambda p: f"Pipe run {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored pipe run, {_g(p['lengthMeters'])} m long and {_mm(p['diameterMeters'])} mm across, "
                      f"on hanger rods at most {_g(p['hangerSpacingMeters'])} m apart."),
           lambda p: f"{_mm(p['lengthMeters'])}x{_mm(p['diameterMeters'])}mm",
           "Illustrative only; not a piping design."),
    Family("sprinkler_line", "Sprinkler line", "A sprinkler branch line with pendent heads, hung from the roof.",
           "Building Structures", ("overhead", "services", "building", "fire", "sprinkler"),
           {"lengthMeters": _length(20.0, 1, 400, "length (along x)"),
            "headSpacingMeters": _length(3.0, 1.5, 4.6, "the most space between heads"),
            "dropMeters": _length(0.25, 0.05, 1.5, "hanger rods above the pipe"),
            "diameterMeters": _length(0.06, 0.025, 0.15, "pipe diameter"),
            "color": _color(SPRINKLER_RED), "headColor": _color(BRASS, "head colour"),
            "hangerColor": _color(HANGER, "hanger colour")},
           _sprinkler_line, lambda p: f"Sprinkler line {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored sprinkler branch line, {_g(p['lengthMeters'])} m long: {_mm(p['diameterMeters'])} mm "
                      f"pipe with {_sprinkler_heads(p)} pendent heads at most {_g(p['headSpacingMeters'])} m apart, "
                      "on hanger rods."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", "Illustrative only; not a fire protection design."),
    Family("high_bay_lights", "High-bay lights", "Round LED high-bay lights on pendants, one or a row; the lenses "
           "come lit.", "Building Structures", ("overhead", "services", "building", "lighting", "light"),
           {"count": Param("count", 1, 1, 100, "lights in the row (along x)"),
            "spacingMeters": _length(6.0, 1.0, 30.0, "space between lights in a row"),
            "pendantMeters": _length(0.9, 0.1, 3.0, "pendant length above the light"),
            "housingColor": _color(HOUSING, "housing colour"), "rodColor": _color(HANGER, "pendant colour")},
           _high_bay_lights,
           lambda p: ("High-bay light" if p["count"] == 1 else
                      f"High-bay light row {p['count']} x {_g(p['spacingMeters'])} m"),
           lambda p: (f"Authored round LED high-bay light on a {_g(p['pendantMeters'])} m pendant, its lens lit."
                      if p["count"] == 1 else
                      f"Authored row of {p['count']} round LED high-bay lights on {_g(p['pendantMeters'])} m pendants, "
                      f"{_g(p['spacingMeters'])} m apart, lenses lit."),
           lambda p: f"{p['count']}x{_mm(p['spacingMeters'])}mm", "Illustrative only; not a lighting design."),
    Family("roof_deck", "Roof deck", "A flat roof deck with a membrane on top, laid on the joists (switchable).",
           "Building Structures", ("roof", "roof-sheeting", "overhead", "building"),
           {"widthMeters": _length(20.0, 1, 400, "size along x"), "depthMeters": _length(20.0, 1, 400, "size along z"),
            "thicknessMeters": _length(0.08, 0.02, 0.5, "thickness"),
            "color": _color(MEMBRANE, "membrane colour"), "underColor": _color(DECK_UNDER, "underside colour")},
           _roof_deck, lambda p: f"Roof deck {_g(p['widthMeters'])} x {_g(p['depthMeters'])} m",
           lambda p: (f"Authored flat roof deck, {_g(p['widthMeters'])} x {_g(p['depthMeters'])} m, with a light "
                      "membrane on top, laid on roof joists."),
           lambda p: f"{_mm(p['widthMeters'])}x{_mm(p['depthMeters'])}mm", STRUCTURAL),
    Family("roof_fascia", "Roof fascia", "A fascia between a wall top and the roof edge, with a low parapet "
           "(switchable).", "Building Structures", ("roof", "roof-sheeting", "overhead", "building"),
           {"lengthMeters": _length(20.0, **LENGTH_400, doc="length (along x)"),
            "heightMeters": _length(1.9, 0.2, 5.0, "height"),
            "thicknessMeters": _length(0.05, 0.02, 0.3, "thickness"), "color": _color(FASCIA)},
           _fascia, lambda p: f"Roof fascia {_g(p['lengthMeters'])} m",
           lambda p: (f"Authored roof fascia, {_g(p['lengthMeters'])} m long and {_g(p['heightMeters'])} m high, "
                      "closing the gap between a wall top and the roof edge."),
           lambda p: f"{_mm(p['lengthMeters'])}mm", STRUCTURAL),
    Family("tank", "Tank", "An upright cylindrical tank.", "Utilities", ("tank", "vessel", "equipment"),
           {"diameterMeters": _length(2.0, 0.2, 20, "diameter"), "heightMeters": _length(3.0, 0.2, 30, "height"),
            "color": _color("#d9dde0")},
           _tank, lambda p: f"Tank {_g(p['diameterMeters'])} x {_g(p['heightMeters'])} m",
           lambda p: (f"Authored upright cylindrical tank, {_g(p['diameterMeters'])} m across and "
                      f"{_g(p['heightMeters'])} m high."),
           lambda p: f"{_mm(p['diameterMeters'])}x{_mm(p['heightMeters'])}mm",
           "Illustrative only; no rated capacity or pressure."),
    Family("bin", "Bin", "An open-top bin or tote.", "Storage", ("bin", "container", "storage"),
           {"widthMeters": _length(0.6, 0.1, 3.0, "size along x"),
            "depthMeters": _length(0.4, 0.1, 3.0, "size along z"),
            "heightMeters": _length(0.3, 0.1, 2.0, "height"), "color": _color("#2f6db5")},
           _bin, lambda p: f"Bin {_mm(p['widthMeters'])} x {_mm(p['depthMeters'])} mm",
           lambda p: (f"Authored open-top bin, {_mm(p['widthMeters'])} x {_mm(p['depthMeters'])} mm and "
                      f"{_mm(p['heightMeters'])} mm high."),
           lambda p: f"{_mm(p['widthMeters'])}x{_mm(p['depthMeters'])}x{_mm(p['heightMeters'])}mm",
           "Illustrative only; no rated capacity."),
    Family("pallet_stack", "Pallet stack", "A stack of wooden pallets, with an optional load box on top.",
           "Storage", ("pallet", "storage", "logistics"),
           {"pallets": Param("count", 10, 1, 20, "pallets in the stack"),
            "lengthMeters": _length(1.2, 0.8, 1.5, "pallet length (along x)"),
            "widthMeters": _length(1.0, 0.8, 1.3, "pallet width (along z)"),
            "loadHeightMeters": _length(0.0, 0.0, 2.0, "a load box on the top pallet; 0 for none"),
            "color": _color("#b8925e", "wood colour"), "loadColor": _color("#c8a46e", "load colour")},
           _pallet_stack, lambda p: f"Pallet stack {p['pallets']}",
           lambda p: (f"Authored stack of {p['pallets']} wooden pallets, {_mm(p['lengthMeters'])} x "
                      f"{_mm(p['widthMeters'])} mm" + (f", with a {_g(p['loadHeightMeters'])} m load on top."
                                                         if p["loadHeightMeters"] > 0 else ".")),
           lambda p: f"{p['pallets']}x{_mm(p['lengthMeters'])}x{_mm(p['widthMeters'])}mm",
           "Illustrative only; no rated load."),
    Family("workbench", "Workbench", "A workbench with a lower shelf.", "Workstations",
           ("workbench", "bench", "workstation"),
           {"widthMeters": _length(1.8, 0.6, 4.0, "size along x"),
            "depthMeters": _length(0.75, 0.4, 1.2, "size along z"),
            "heightMeters": _length(0.9, 0.6, 1.2, "worktop height"),
            "topColor": _color("#b08a5a", "worktop colour"), "frameColor": _color("#4a5560", "frame colour")},
           _workbench, lambda p: f"Workbench {_mm(p['widthMeters'])} x {_mm(p['depthMeters'])} mm",
           lambda p: (f"Authored workbench, {_mm(p['widthMeters'])} x {_mm(p['depthMeters'])} mm and "
                      f"{_mm(p['heightMeters'])} mm high, with a lower shelf."),
           lambda p: f"{_mm(p['widthMeters'])}x{_mm(p['depthMeters'])}mm", "Illustrative only; no rated load."),
)}


def schema(name: str) -> dict:
    """The family's JSON schema: every parameter optional (defaults fill the rest), with its limits."""
    family = _family(name)
    properties = {}
    for key, param in family.params.items():
        if param.kind == "color":
            properties[key] = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$", "default": param.default,
                               "description": param.doc}
        else:
            properties[key] = {"type": "integer" if param.kind == "count" else "number", "minimum": param.low,
                               "maximum": param.high, "default": param.default,
                               "description": param.doc + ("" if param.kind == "count" else ", metres")}
    return {"type": "object", "properties": properties, "additionalProperties": False}


def listing() -> list[dict]:
    """Every family for Sage: name, what it is, its category and its parameters with defaults and limits."""
    return [{"family": f.name, "label": f.label, "summary": f.summary, "category": f.category,
             "parameters": schema(f.name)["properties"]} for f in FAMILIES.values()]


def _family(name: str) -> Family:
    family = FAMILIES.get(name)
    if family is None:
        raise ValueError(f"Unknown shape family {name!r}; the families are {', '.join(FAMILIES)}")
    return family


def resolve(name: str, parameters: dict | None = None) -> tuple[Family, dict]:
    """The family and its full, rounded parameters (lengths to the millimetre, colours in lower case)."""
    from jsonschema import Draft202012Validator
    family = _family(name)
    parameters = {} if parameters is None else parameters
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    errors = sorted(Draft202012Validator(schema(name)).iter_errors(parameters), key=lambda e: list(e.path))
    if errors:
        raise ValueError("; ".join(f"{'.'.join(str(p) for p in e.path) or 'parameters'}: {e.message}"
                                   for e in errors))
    values = {}
    for key, param in family.params.items():
        value = parameters.get(key, param.default)
        if param.kind == "length":
            value = float(round(float(value), 3))
            if not param.low <= value <= param.high:   # rounding can step over a limit by a fraction of a millimetre
                value = min(max(value, float(param.low)), float(param.high))
        elif param.kind == "count":
            value = int(value)
        else:
            value = value.lower()
        values[key] = value
    if family.name == "high_bay_lights":       # count and spacing pass one by one; the row they make may not
        span = (values["count"] - 1) * values["spacingMeters"] + 2 * LIGHT_HOUSING_RADIUS
        if span > LONGEST + 1e-9:
            raise ValueError(f"count, spacingMeters: a row of {values['count']} lights {_g(values['spacingMeters'])} "
                             f"m apart is {_g(round(span, 3))} m long; one piece is at most {_g(LONGEST)} m")
    return family, values


def asset_id(name: str, parameters: dict | None = None) -> str:
    """asset-authored-<family>-<main size>-<hash>: the same family and rounded parameters give the same id."""
    family, values = resolve(name, parameters)
    return _asset_id(family, values)


def _asset_id(family: Family, values: dict) -> str:
    digest = hashlib.sha256(json.dumps({"family": family.name, "parameters": values}, sort_keys=True,
                                       separators=(",", ":")).encode("ascii")).hexdigest()
    return f"asset-authored-{family.name.replace('_', '-')}-{family.key(values)}-{digest[:10]}"


def model(name: str, parameters: dict | None = None) -> list:
    """The family's parts with these parameters, centred with the base at y = 0: what build_asset writes to the GLB
    (shape_preview.py draws it)."""
    family, values = resolve(name, parameters)
    return on_floor(family.build(values))


def build_asset(name: str, parameters: dict | None = None) -> dict:
    """The model and its catalog entry: {assetId, family, parameters, payload (GLB bytes), entry, dimensions,
    triangles}. Raises ValueError for parameters outside the family's limits."""
    family, values = resolve(name, parameters)
    parts = on_floor(family.build(values))
    dimensions = {key: round(value, 4) for key, value in size_of(parts).items()}
    identifier = _asset_id(family, values)
    payload = glb(parts, root=identifier[len("asset-"):])
    report = verify(payload, dimensions)
    if report["triangles"] > MAX_TRIANGLES:
        raise ValueError(f"The model has {report['triangles']} triangles, more than {MAX_TRIANGLES}; ask for fewer or "
                         "larger pieces")
    entry = {"artifact": f"{FOLDER}/{identifier[len('asset-'):]}.glb", "assetId": identifier,
             "category": family.category, "description": f"{family.describe(values)} {family.disclaimer}",
             "dimensions": dimensions, "displayName": family.title(values),
             "source": {"evidenceStatus": "authored", "generator": GENERATOR, "kind": "authored-primitive",
                        "family": family.name, "parameters": values},
             "sourceToCanonical": list(IDENTITY), "tags": [*family.tags, "authored", "unverified"]}
    return {"assetId": identifier, "family": family.name, "parameters": values, "payload": payload, "entry": entry,
            "dimensions": dimensions, "triangles": report["triangles"]}
