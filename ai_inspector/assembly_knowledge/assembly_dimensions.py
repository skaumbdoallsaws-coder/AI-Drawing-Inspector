"""Smart Dimension on the server (docs/assembly-smart-dimension-plan.md): what one face of the loaded assembly, or
two, measure, the way the Assembly view's Smart Dimension measures them (static/assembly_smart_dimension.js). It
works from the exact surface the view reported for each face (a plane, a cylinder or a sphere, in metres in the
view's axes) and the face's centre, which stands in for the spot the pointer picked. Sage names faces; edges and
vertices are picked with the pointer. tests/fixtures/smart_dimension_cases.json holds cases both sides check."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional

PARALLEL_SIN = math.sin(math.radians(0.05))
INCH = 0.0254
DIAMETER = "\u00d8"
DEGREE = "\u00b0"
SURFACES = ("plane", "cylinder", "sphere")


class DimensionError(ValueError):
    """Faces that give no dimension."""


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _scale(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def _add_scaled(a, b, s):
    return [a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _length(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    size = _length(a)
    return _scale(a, 1 / size) if size > 1e-12 else [0.0, 0.0, 0.0]


def _reject(a, axis):
    return _add_scaled(a, axis, -_dot(a, axis))


def _perpendicular_to(a):
    return _unit(_cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0]))


def _foot_on_line(p, origin, direction):
    return _add_scaled(origin, direction, _dot(_sub(p, origin), direction))


def _foot_on_plane(p, origin, normal):
    return _add_scaled(p, normal, -_dot(_sub(p, origin), normal))


def face_entity(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """A face as the view's report lists it (its centre and exact surface), as something to measure; None when
    the view gave no exact surface for it (a cone, a torus, a free-form face)."""
    surface = row.get("geometry")
    if not isinstance(surface, Mapping) or surface.get("kind") not in SURFACES:
        return None
    entity = {key: (list(value) if isinstance(value, (list, tuple)) else value) for key, value in surface.items()}
    entity["anchor"] = list(row.get("center") or surface.get("point") or surface.get("center"))
    return entity


def _measure_one(e: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if e["kind"] == "cylinder":
        return {"kind": "diameter", "value": 2 * e["radius"]}
    if e["kind"] == "sphere":
        return {"kind": "diameter", "sphere": True, "value": 2 * e["radius"]}
    return None


def _linear(p1, p2, method=None):
    return {"kind": "distance", "value": _length(_sub(p1, p2)), "method": method}


def _towards(direction, origin, target):
    return _scale(direction, -1) if _dot(_sub(target, origin), direction) < 0 else direction


def _angle(u, v):
    return {"kind": "angle", "value": math.acos(max(-1.0, min(1.0, _dot(u, v))))}


def _measure_two(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    pa = a["center"] if a["kind"] == "sphere" else None
    pb = b["center"] if b["kind"] == "sphere" else None
    la = (a["point"], a["axis"]) if a["kind"] == "cylinder" else None
    lb = (b["point"], b["axis"]) if b["kind"] == "cylinder" else None
    qa = (a["point"], a["normal"]) if a["kind"] == "plane" else None
    qb = (b["point"], b["normal"]) if b["kind"] == "plane" else None
    if pa and pb:
        return _linear(pa, pb)
    if pa and lb:
        return _linear(pa, _foot_on_line(pa, *lb), "perpendicular")
    if la and pb:
        return _linear(_foot_on_line(pb, *la), pb, "perpendicular")
    if pa and qb:
        return _linear(pa, _foot_on_plane(pa, *qb), "perpendicular")
    if qa and pb:
        return _linear(_foot_on_plane(pb, *qa), pb, "perpendicular")
    if la and lb:
        if _length(_cross(la[1], lb[1])) < PARALLEL_SIN:
            p1 = _foot_on_line(a["anchor"], *la)
            return _linear(p1, _foot_on_line(p1, *lb), "parallel")
        w = _sub(la[0], lb[0])
        d = _dot(la[1], lb[1])
        denominator = 1 - d * d
        s = (d * _dot(lb[1], w) - _dot(la[1], w)) / denominator
        t = (_dot(lb[1], w) - d * _dot(la[1], w)) / denominator
        apex = _add_scaled(la[0], la[1], s)
        other = _add_scaled(lb[0], lb[1], t)
        return _angle(_towards(la[1], apex, a["anchor"]), _towards(lb[1], other, b["anchor"]))
    if (la and qb) or (qa and lb):
        line, plane, line_entity = (la, qb, a) if la else (lb, qa, b)
        if abs(_dot(line[1], plane[1])) < PARALLEL_SIN:
            p1 = _foot_on_line(line_entity["anchor"], *line)
            return _linear(p1, _foot_on_plane(p1, *plane), "parallel")
        t = _dot(_sub(plane[0], line[0]), plane[1]) / _dot(line[1], plane[1])
        apex = _add_scaled(line[0], line[1], t)
        along = _towards(line[1], apex, line_entity["anchor"])
        flat = _unit(_reject(along, plane[1]))
        if _length(flat) < 0.5:
            flat = _perpendicular_to(plane[1])
        return _angle(along, flat)
    # Two planes.
    if _length(_cross(qa[1], qb[1])) < PARALLEL_SIN:
        p1 = _foot_on_plane(a["anchor"], *qa)
        return _linear(p1, _foot_on_plane(p1, *qb), "parallel")
    line = _unit(_cross(qa[1], qb[1]))
    mid = _scale(_add(a["anchor"], b["anchor"]), 0.5)
    c = _dot(qa[1], qb[1])
    r1 = _dot(qa[1], qa[0]) - _dot(qa[1], mid)
    r2 = _dot(qb[1], qb[0]) - _dot(qb[1], mid)
    alpha = (r1 - c * r2) / (1 - c * c)
    beta = (r2 - c * r1) / (1 - c * c)
    apex = _add_scaled(_add_scaled(mid, qa[1], alpha), qb[1], beta)
    u = _unit(_reject(_sub(a["anchor"], apex), line))
    v = _unit(_reject(_sub(b["anchor"], apex), line))
    if _length(u) < 0.5:
        u = _unit(_cross(qa[1], line))
    if _length(v) < 0.5:
        v = _unit(_cross(line, qb[1]))
    return _angle(u, v)


def measure(a: Mapping[str, Any], b: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """What the faces measure: {kind: diameter | distance | angle, value (metres or radians), sphere?, method?}.
    Raises DimensionError for a flat face alone, which has no size of its own."""
    if b is None:
        found = _measure_one(a)
        if not found:
            raise DimensionError("a flat face has no size of its own: give a second face to measure it from")
        return found
    return _measure_two(a, b)


def format_value(found: Mapping[str, Any], units: str = "mm") -> str:
    """The value as the view writes it (SOLIDWORKS' way): 2 decimals, no unit, a diameter sign or degrees."""
    if found["kind"] == "angle":
        return f"{math.degrees(found['value']):.2f}{DEGREE}"
    text = f"{(found['value'] / INCH if units == 'in' else found['value'] * 1000):.2f}"
    if found["kind"] == "diameter":
        return ("S" if found.get("sphere") else "") + DIAMETER + text
    if found["kind"] == "radius":
        return "R" + text
    return text


def described(found: Mapping[str, Any], units: str = "mm") -> Dict[str, Any]:
    """A measurement for Sage: its kind, the text the view shows, the number in the units shown and how it was
    taken (parallel, square to a face or an axis)."""
    if found["kind"] == "angle":
        value, unit = round(math.degrees(found["value"]), 4), "degrees"
    else:
        value, unit = round(found["value"] / INCH if units == "in" else found["value"] * 1000, 4), units
    row: Dict[str, Any] = {"kind": "sphere diameter" if found.get("sphere") else found["kind"],
                           "text": format_value(found, units), "value": value, "unit": unit}
    if found.get("method"):
        row["method"] = found["method"]
    return row


__all__: List[str] = ["DimensionError", "PARALLEL_SIN", "described", "face_entity", "format_value", "measure"]
