"""Floor-plan import, alignment (docs/facility-floor-plan-import-plan.md, section 5).

One transform from drawing units to layout meters, used by display, calibration and conversion alike:

    layoutPoint = translation + metersPerDrawingUnit * R(rotation) * (drawingPoint - sourceOrigin)
    drawing X -> layout X, drawing Y -> layout Z, R counter-clockwise in the numeric X/Z plane:
    x = cos(r) * du - sin(r) * dv,  z = sin(r) * du + cos(r) * dv

Translation, rotation and one uniform scale: never a stretch of one axis, never a reflection. The browser's copy
(static/facility_layout_floor_plan.js) is checked against the same cases as this module
(tests/fixtures/facility_layout/floor_plan/alignment_cases.json).
"""
from __future__ import annotations

import math

UNIT_SOURCES = ("header", "chosen", "calibrated")
MAX_CONTROL_POINTS = 16
MAX_DRAWING_COORDINATE = 1e10
MAX_LAYOUT_COORDINATE = 1_000_000.0   # canonical.MAXIMUM_ABSOLUTE_WORLD_COORDINATE_METERS
MIN_METERS_PER_UNIT = 1e-9
MAX_METERS_PER_UNIT = 1e4
MIN_CONTROL_SEPARATION_METERS = 0.1   # two picks closer than this cannot fix a scale or a direction
_ALIGNMENT_KEYS = {"sourceOrigin", "metersPerDrawingUnit", "rotationDegrees", "translationMeters", "unitSource",
                   "confirmed", "controlPoints"}


def _number(value, name: str, bound: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")
    number = float(value)
    if not math.isfinite(number) or abs(number) > bound:
        raise ValueError(f"{name} must be a finite number within +-{bound:g}.")
    return number


def _sig(value: float, digits: int = 12) -> float:
    return float(f"{value:.{digits}g}")


def _r(value: float, places: int) -> float:
    rounded = round(value, places)
    return 0.0 if rounded == 0 else rounded


def normalize_rotation(degrees: float) -> float:
    """Degrees in (-180, 180]."""
    turned = math.fmod(float(degrees), 360.0)
    if turned <= -180.0:
        turned += 360.0
    elif turned > 180.0:
        turned -= 360.0
    return turned


def _uv(value, name: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"u", "v"}:
        raise ValueError(f"{name} must be an object with exactly u and v.")
    return {"u": _r(_number(value["u"], f"{name}.u", MAX_DRAWING_COORDINATE), 6),
            "v": _r(_number(value["v"], f"{name}.v", MAX_DRAWING_COORDINATE), 6)}


def _xz(value, name: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"x", "z"}:
        raise ValueError(f"{name} must be an object with exactly x and z.")
    return {"x": _r(_number(value["x"], f"{name}.x", MAX_LAYOUT_COORDINATE), 6),
            "z": _r(_number(value["z"], f"{name}.z", MAX_LAYOUT_COORDINATE), 6)}


def normalize_alignment(value) -> dict:
    """The stored form of an alignment (a closed field set); raises ValueError. Idempotent."""
    if not isinstance(value, dict) or set(value) != _ALIGNMENT_KEYS:
        raise ValueError("alignment must have exactly " + ", ".join(sorted(_ALIGNMENT_KEYS)) + ".")
    scale = _number(value["metersPerDrawingUnit"], "alignment.metersPerDrawingUnit", MAX_METERS_PER_UNIT)
    if scale < MIN_METERS_PER_UNIT:
        raise ValueError("alignment.metersPerDrawingUnit must be positive.")
    if value["unitSource"] not in UNIT_SOURCES:
        raise ValueError("alignment.unitSource must be one of " + ", ".join(UNIT_SOURCES) + ".")
    if not isinstance(value["confirmed"], bool):
        raise ValueError("alignment.confirmed must be true or false.")
    controls = value["controlPoints"]
    if not isinstance(controls, list) or len(controls) > MAX_CONTROL_POINTS:
        raise ValueError(f"alignment.controlPoints must be a list of at most {MAX_CONTROL_POINTS} points.")
    normalized_controls = []
    for index, control in enumerate(controls):
        if not isinstance(control, dict) or set(control) != {"source", "target"}:
            raise ValueError(f"alignment.controlPoints[{index}] must have exactly source and target.")
        normalized_controls.append({"source": _uv(control["source"], f"controlPoints[{index}].source"),
                                    "target": _xz(control["target"], f"controlPoints[{index}].target")})
    return {
        "sourceOrigin": _uv(value["sourceOrigin"], "alignment.sourceOrigin"),
        "metersPerDrawingUnit": _sig(scale),
        # Rounded, then turned into (-180, 180] again: -179.9999999996 rounds to -180, which is stored as 180.
        "rotationDegrees": normalize_rotation(_r(normalize_rotation(_number(
            value["rotationDegrees"], "alignment.rotationDegrees", 1e6)), 9)),
        "translationMeters": _xz(value["translationMeters"], "alignment.translationMeters"),
        "unitSource": value["unitSource"],
        "confirmed": value["confirmed"],
        "controlPoints": normalized_controls,
    }


def to_layout(alignment: dict, u: float, v: float) -> tuple[float, float]:
    """Drawing point (u, v), absolute drawing units -> layout (x, z) meters."""
    origin, move = alignment["sourceOrigin"], alignment["translationMeters"]
    scale = alignment["metersPerDrawingUnit"]
    angle = math.radians(alignment["rotationDegrees"])
    du, dv = (u - origin["u"]) * scale, (v - origin["v"]) * scale
    cos, sin = math.cos(angle), math.sin(angle)
    return move["x"] + cos * du - sin * dv, move["z"] + sin * du + cos * dv


def to_drawing(alignment: dict, x: float, z: float) -> tuple[float, float]:
    """Layout (x, z) meters -> drawing point (u, v), absolute drawing units."""
    origin, move = alignment["sourceOrigin"], alignment["translationMeters"]
    scale = alignment["metersPerDrawingUnit"]
    angle = math.radians(alignment["rotationDegrees"])
    dx, dz = x - move["x"], z - move["z"]
    cos, sin = math.cos(angle), math.sin(angle)
    return origin["u"] + (cos * dx + sin * dz) / scale, origin["v"] + (-sin * dx + cos * dz) / scale


def fit(pairs, *, source_origin: tuple[float, float] = (0.0, 0.0), meters_per_unit: float | None = None) -> dict:
    """Best alignment for control PAIRS [((u, v), (x, z)), ...]: drawing points (absolute drawing units) and where
    they belong in the layout (meters). With METERS_PER_UNIT the scale is held (a rigid fit: declared, confirmed
    units); without it the scale comes from the points. Least squares over every pair; returns the alignment's
    numbers, each pair's residual and the scale the points imply (to catch a wrong unit header). Raises ValueError for
    fewer than two pairs or picks too close together to fix a direction."""
    points = []
    for index, pair in enumerate(pairs):
        try:
            (u, v), (x, z) = pair
        except (TypeError, ValueError):
            raise ValueError(f"control pair {index} must be ((u, v), (x, z)).") from None
        points.append((_number(u, "u", MAX_DRAWING_COORDINATE), _number(v, "v", MAX_DRAWING_COORDINATE),
                       _number(x, "x", MAX_LAYOUT_COORDINATE), _number(z, "z", MAX_LAYOUT_COORDINATE)))
    if len(points) < 2:
        raise ValueError("Pick at least two points to align the drawing.")
    if len(points) > MAX_CONTROL_POINTS:
        raise ValueError(f"Use at most {MAX_CONTROL_POINTS} control points.")
    try:
        origin_u, origin_v = source_origin
    except (TypeError, ValueError):
        raise ValueError("source_origin must be (u, v).") from None
    ou = _number(origin_u, "source origin u", MAX_DRAWING_COORDINATE)
    ov = _number(origin_v, "source origin v", MAX_DRAWING_COORDINATE)
    held = None
    if meters_per_unit is not None:  # 0 is a wrong unit, not "no unit"
        held = _number(meters_per_unit, "meters per drawing unit", MAX_METERS_PER_UNIT)
        if held < MIN_METERS_PER_UNIT:
            raise ValueError("The drawing unit must be a positive length.")
    n = len(points)
    su = [p[0] - ou for p in points]
    sv = [p[1] - ov for p in points]
    cu, cv = sum(su) / n, sum(sv) / n
    cx, cz = sum(p[2] for p in points) / n, sum(p[3] for p in points) / n
    a = [(su[i] - cu, sv[i] - cv) for i in range(n)]
    b = [(points[i][2] - cx, points[i][3] - cz) for i in range(n)]
    source_spread = max(math.hypot(*a_i) for a_i in a) * 2
    target_spread = max(math.hypot(*b_i) for b_i in b) * 2
    if source_spread <= 1e-9:
        raise ValueError("The drawing points are on top of each other; pick points farther apart.")
    if target_spread < MIN_CONTROL_SEPARATION_METERS:
        raise ValueError("The layout points are less than 10 cm apart; pick points farther apart.")
    dot = sum(a[i][0] * b[i][0] + a[i][1] * b[i][1] for i in range(n))
    cross = sum(a[i][0] * b[i][1] - a[i][1] * b[i][0] for i in range(n))
    angle = math.atan2(cross, dot)
    norm = sum(x * x + y * y for x, y in a)
    implied_scale = math.hypot(dot, cross) / norm
    scale = held if held is not None else implied_scale
    if not (MIN_METERS_PER_UNIT <= scale <= MAX_METERS_PER_UNIT):
        raise ValueError("The points give a scale outside what a floor plan can have.")
    cos, sin = math.cos(angle), math.sin(angle)
    tx = cx - scale * (cos * cu - sin * cv)
    tz = cz - scale * (sin * cu + cos * cv)
    alignment = {"sourceOrigin": {"u": ou, "v": ov}, "metersPerDrawingUnit": scale,
                 "rotationDegrees": math.degrees(angle), "translationMeters": {"x": tx, "z": tz}}
    residuals = []
    for p in points:
        x, z = to_layout(alignment, p[0], p[1])
        residuals.append(math.hypot(x - p[2], z - p[3]))
    return {
        "metersPerDrawingUnit": scale,
        "rotationDegrees": normalize_rotation(math.degrees(angle)),
        "translationMeters": {"x": tx, "z": tz},
        "sourceOrigin": {"u": ou, "v": ov},
        "impliedMetersPerDrawingUnit": implied_scale,
        "scaleRatio": implied_scale / scale,
        "residualsMeters": residuals,
        "rmsMeters": math.sqrt(sum(r * r for r in residuals) / n),
        "maxResidualMeters": max(residuals),
    }


def scale_for_distance(a: tuple[float, float], b: tuple[float, float], meters: float) -> float:
    """Meters per drawing unit when the drawing points A and B are METERS apart."""
    distance = math.dist(a, b)
    meters = _number(meters, "distance", MAX_LAYOUT_COORDINATE)
    if distance <= 1e-9:
        raise ValueError("The two drawing points are on top of each other; pick points farther apart.")
    if meters < MIN_CONTROL_SEPARATION_METERS:
        raise ValueError("Enter a real distance of at least 10 cm.")
    scale = meters / distance
    if not (MIN_METERS_PER_UNIT <= scale <= MAX_METERS_PER_UNIT):
        raise ValueError("That distance gives a scale outside what a floor plan can have.")
    return scale
