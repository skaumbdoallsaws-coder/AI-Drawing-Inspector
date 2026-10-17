"""Bounded curved floor graphics compiled into the existing editable line primitives."""
import json
import math

from jsonschema import Draft202012Validator

from .errors import FacilityValidationError


def _object(properties, required=None):
    return {"type": "object", "properties": properties, "additionalProperties": False,
            "required": list(properties) if required is None else required}


POINT = _object({key: {"type": "number", "minimum": -10000, "maximum": 10000} for key in ("x", "z")})
SCHEMA = _object({
    "label": {"type": "string", "minLength": 1, "maxLength": 100},
    "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
    "lineWidth": {"type": "number", "minimum": .005, "maximum": 1},
    "elevation": {"type": "number", "minimum": -1000, "maximum": 1000},
    "shape": {"oneOf": [
        _object({"kind": {"const": "polyline"}, "points": {"type": "array", "items": POINT,
            "minItems": 2, "maxItems": 128}, "closed": {"type": "boolean"}}),
        _object({"kind": {"const": "arc"}, "center": POINT,
            "radius": {"type": "number", "minimum": .01, "maximum": 1000},
            "startDegrees": {"type": "number", "minimum": -360, "maximum": 360},
            "sweepDegrees": {"type": "number", "minimum": -360, "maximum": 360,
                             "not": {"const": 0}}}),
    ]},
})
_VALIDATOR = Draft202012Validator(SCHEMA)


def compile_floor_path(path):
    try:
        json.dumps(path, allow_nan=False)
    except (ValueError, TypeError):
        raise FacilityValidationError("floor_path_invalid", "Path values must be finite JSON data.") from None
    errors = list(_VALIDATOR.iter_errors(path))
    if errors:
        raise FacilityValidationError("floor_path_invalid", "The floor path does not match its contract.")
    shape = path["shape"]
    if shape["kind"] == "polyline":
        points = [(p["x"], p["z"]) for p in shape["points"]]
        if shape["closed"] and points[-1] != points[0]:
            points.append(points[0])
    else:
        # At most 128 segments for a circle; angles follow x/z plan coordinates.
        count = max(1, math.ceil(abs(shape["sweepDegrees"]) / (360 / 128)))
        points = []
        for i in range(count + 1):
            angle = math.radians(shape["startDegrees"] + shape["sweepDegrees"] * i / count)
            points.append((shape["center"]["x"] + shape["radius"] * math.cos(angle),
                           shape["center"]["z"] + shape["radius"] * math.sin(angle)))
    result = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        dx, dz = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dz)
        if not math.isfinite(length) or length < .000001:
            raise FacilityValidationError("floor_path_invalid", "Path segments must have finite, distinct endpoints.")
        result.append({"label": f"{path['label']} {i+1}", "markingType": "solid_line",
            "semanticRole": "decorative", "positionMode": "manual",
            "transform": {"position": {"x": (a[0]+b[0])/2, "y": path["elevation"], "z": (a[1]+b[1])/2},
                          "rotationDegrees": -math.degrees(math.atan2(dz, dx))},
            "width": length, "depth": path["lineWidth"], "fillColor": path["color"],
            "strokeColor": path["color"], "opacity": 1, "text": "", "evidence": [],
            "metadata": {"floorPathLabel": path["label"], "floorPathSegment": i}})
    return result
