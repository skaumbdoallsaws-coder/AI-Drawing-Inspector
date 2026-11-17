"""JSON Schema for the recipe, also used by the dependency-free validator."""


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def text(maximum=80, minimum=1, **kwargs):
    return {"type": "string", "minLength": minimum, "maxLength": maximum, **kwargs}


def num(low, high):
    return {"type": "number", "minimum": low, "maximum": high}


def integer(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def arr(item, minimum, maximum=None):
    return {"type": "array", "items": item, "minItems": minimum,
            "maxItems": minimum if maximum is None else maximum}


def enum(*values):
    return {"enum": list(values)}


ID = text(40, pattern="^[a-z0-9-]{1,40}$")
HASH = text(64, 64, pattern="^[0-9a-f]{64}$")
COLOR = text(7, 7, pattern="^#[0-9a-fA-F]{6}$")
COORD = num(-15, 15)
LENGTH = num(.0005, 30)
VEC = arr(COORD, 3)
ROTATE = obj({a: num(-360, 360) for a in "xyz"})
BOUNDS = obj({"min": VEC, "max": VEC}, ["min", "max"])
FINISH = obj({"appearanceId": text(120), "color": COLOR,
              "roughness": num(0, 1), "metalness": num(0, 1)}, ["appearanceId"])
MATERIAL = obj({"color": COLOR, "roughness": num(0, 1), "metalness": num(0, 1),
                "opacity": num(.2, 1), "lit": num(0, 1), "finish": FINISH}, ["color"])
# Modest overflow is clipped and linted by MB2; large coordinates still refuse.
BOX2 = arr(num(-1, 2), 4)
PAINT = {"fill": COLOR, "stroke": COLOR}
PRINT_ITEM = {"oneOf": [
    obj({"text": text(60), "box": BOX2, "color": COLOR, "weight": enum("regular", "bold"),
         "align": enum("left", "center", "right")}, ["text", "box", "color"]),
    obj({"rect": BOX2, **PAINT, "lineMm": num(.1, 100), "radiusMm": num(0, 100)}, ["rect"]),
    obj({"line": BOX2, "color": COLOR, "lineMm": num(.1, 100)}, ["line", "color", "lineMm"]),
    obj({"circle": arr(num(-1, 2), 3), **PAINT}, ["circle"]),
    obj({"barcode": BOX2, "seed": integer(0, 4294967295)}, ["barcode", "seed"]),
    obj({"stripes": BOX2, "colors": arr(COLOR, 2), "angleDegrees": num(-360, 360),
         "widthMm": num(.1, 1000)}, ["stripes", "colors", "angleDegrees", "widthMm"]),
    obj({"dots": obj({"area": BOX2, "pitchMm": num(.5, 1000), "radiusMm": num(.1, 500),
                       "color": COLOR}, ["area", "pitchMm", "radiusMm", "color"])}, ["dots"]),
]}
PRINT = obj({"background": COLOR, "items": arr(PRINT_ITEM, 0, 24)}, ["background", "items"])
PATTERNS = {
    "repeat": obj({"count": integer(2, 200), "step": VEC}, ["count", "step"]),
    "grid": obj({"count": arr(integer(1, 400), 2), "step1": VEC, "step2": VEC},
                ["count", "step1", "step2"]),
    "around": obj({"count": integer(2, 120), "axis": enum("x", "y", "z"), "center": VEC,
                   "degrees": num(0, 360)}, ["count", "axis", "center"]),
    "mirror": obj({"plane": enum("x", "z")}, ["plane"]),
    "scatter": obj({"count": integer(1, 60), "seed": integer(0, 4294967295), "within": BOUNDS,
                    "turnY": arr(num(-360, 360), 2), "tiltX": arr(num(-360, 360), 2),
                    "tiltZ": arr(num(-360, 360), 2), "sizeJitter": arr(num(0, .3), 3)},
                   ["count", "seed", "within"]),
}
COMMON = {"id": ID, "name": text(), "material": ID, "rotate": ROTATE, **PATTERNS}
SHAPES = {
    "box": ({"min": VEC, "max": VEC, "center": VEC, "size": arr(LENGTH, 3)}, []),
    "cylinder": ({"from": VEC, "to": VEC, "radius": LENGTH, "radiusTo": num(0, 30),
                  "hollow": LENGTH, "segments": integer(6, 64),
                  "caps": enum("both", "start", "end", "none")}, ["from", "to", "radius"]),
    "tube": ({"path": arr(VEC, 2, 64), "radius": LENGTH, "sides": integer(6, 24),
              "closed": {"type": "boolean"}}, ["path", "radius"]),
    "lathe": ({"profile": arr(arr(COORD, 2), 2, 64), "center": VEC,
               "axis": enum("x", "y", "z"), "segments": integer(8, 64), "degrees": {"const": 360}},
              ["profile", "center"]),
    "torus": ({"center": VEC, "axis": enum("x", "y", "z"), "radius": LENGTH,
               "tubeRadius": LENGTH, "segments": integer(8, 64)}, ["center", "radius", "tubeRadius"]),
    "sphere": ({"center": VEC, "radii": arr(LENGTH, 3), "part": enum("whole", "upper", "lower")},
               ["center", "radii"]),
    "extrude": ({"profile": arr(arr(COORD, 2), 3, 64), "plane": enum("xy", "zy", "xz"),
                 "at": COORD, "depth": LENGTH}, ["profile", "plane", "at", "depth"]),
    "panel": ({"center": VEC, "size": arr(LENGTH, 2), "facing": enum("+z", "-z", "+x", "-x", "+y"),
               "print": PRINT, "back": COLOR}, ["center", "size", "facing", "print"]),
}
SELECTOR = {"oneOf": [text(512, pattern="^p:.+#[0-9]+$"), *[
    obj({k: text(512 if k == "part" else 80)}, [k]) for k in ("part", "mesh", "material", "node")],
    obj({"all": {"const": True}}, ["all"])]}
INCLUDE = obj({"include": text(128, pattern="^asset-[a-z0-9-]+$"), "id": ID, "name": text(),
               "revision": HASH, "artifactSha256": HASH, "position": VEC, "rotateY": num(-360, 360),
               "recolor": arr(obj({"select": SELECTOR, "material": ID}, ["select", "material"]), 0, 16),
               **PATTERNS}, ["include", "id", "name", "revision", "artifactSha256"])
ENTRY = {"oneOf": [obj({**COMMON, "shape": {"const": shape}, **props},
                       ["id", "name", "material", "shape", *required])
                    for shape, (props, required) in SHAPES.items()] + [
    obj({"id": ID, "group": arr({"$ref": "#/$defs/entry"}, 1, 400), "position": VEC,
         "rotate": ROTATE, **PATTERNS}, ["id", "group"]), INCLUDE]}
SOURCE = obj({"url": text(2048, pattern="^https://[^\\s]+$"), "title": text(160)}, ["url", "title"])
SIZE = obj({k: LENGTH for k in ("width", "depth", "height")}, ["width", "depth", "height"])
RECIPE_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": {"entry": ENTRY},
    **obj({"name": text(), "category": text(), "description": text(300, 0), "tags": arr(text(), 0, 8),
           "size": SIZE, "hangHeight": num(0, 3),
           "sizeBasis": obj({"kind": enum("user", "layout", "document", "photo", "research", "typical"),
                             "note": text(160, 0), "sources": arr(SOURCE, 0, 3)}, ["kind", "note"]),
           "fitsWithin": obj({"width": LENGTH, "depth": LENGTH, "height": LENGTH,
                              "orientation": num(-360, 360), "note": text(160, 0),
                              "clearances": obj({k: num(0, 15) for k in ("front", "back", "sides")}),
                              "basis": enum("measured", "user", "research")}, ["width", "depth"]),
           "references": arr(text(27, 27, pattern="^rf-[0-9a-f]{24}$"), 0, 3),
           "front": arr(text(), 0, 400),
           "materials": {"type": "object", "minProperties": 1, "maxProperties": 32,
                         "propertyNames": ID, "additionalProperties": MATERIAL},
           "entries": arr({"$ref": "#/$defs/entry"}, 1, 160),
            "surfaces": arr(obj({"id": ID, "label": text(), "height": COORD,
                                "rect": arr(COORD, 4)}, ["id", "label", "height", "rect"]), 0, 6),
           "footprint": enum("hull", "box")}, ["name", "category", "size", "sizeBasis", "materials", "entries"])}
