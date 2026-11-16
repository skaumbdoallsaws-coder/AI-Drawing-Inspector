"""Closed recipe validation, canonical defaults and semantic checks; stdlib only."""
from copy import deepcopy
import math
import re
import unicodedata
from urllib.parse import urlsplit

from .errors import ModelBuildError, json_bytes, require
from .schema import RECIPE_SCHEMA, PATTERNS

ENGINE_VERSION = "model-builder-1"
RECIPE_BYTES = 24 * 1024
MIN_LENGTH = .0005
# cmap of the pinned Aileron subset (fonts/fonts.json); no system-font lookup.
PRINT_CODEPOINTS = frozenset(range(32, 127)) | {
    10, 169, 171, 176, 177, 180, 183, 187, 8216, 8217, 8220, 8221, 8230,
    8249, 8250, 8260, 8482, 64257, 64258,
}


def _validate(value, schema, path="$", depth=0):
    require(depth <= 40, path, "JSON nesting exceeds 40", "budget_exceeded")
    if "$ref" in schema:
        schema = RECIPE_SCHEMA["$defs"][schema["$ref"].rsplit("/", 1)[1]]
    if "oneOf" in schema:
        options = schema["oneOf"]
        # Dispatch entries and drawing items without walking every recursive variant.
        if isinstance(value, dict):
            discriminators = {"shape", "group", "include"} if options is RECIPE_SCHEMA["$defs"]["entry"]["oneOf"] else {
                "text", "rect", "line", "circle", "barcode", "stripes", "dots"}
            present = value.keys() & discriminators
            if present:
                require(len(present) == 1, path, "Choose exactly one discriminator")
                key = next(iter(present))
                candidates = [s for s in options if key in s.get("properties", {}) and
                              s["properties"][key].get("const", value[key]) == value[key]]
                require(len(candidates) == 1, path + "." + key, "Unsupported discriminator")
                return _validate(value, candidates[0], path, depth + 1)
        matches = 0
        for option in options:
            try:
                _validate(value, option, path, depth + 1)
                matches += 1
            except ModelBuildError:
                pass
        require(matches == 1, path, "Choose exactly one permitted form")
        return
    if "const" in schema:
        require(type(value) is type(schema["const"]) and value == schema["const"], path,
                f"Expected {schema['const']!r}")
    if "enum" in schema:
        require(type(value) is not bool and value in schema["enum"], path, "Unsupported value")
    kind = schema.get("type")
    if kind == "object":
        require(type(value) is dict, path, "Expected an object")
        require(schema.get("minProperties", 0) <= len(value) <= schema.get("maxProperties", 1000),
                path, "Object has too many or too few fields")
        for key in schema.get("required", ()):
            require(key in value, path + "." + key, "Required")
        properties = schema.get("properties", {})
        for key, child in value.items():
            require(isinstance(key, str), path, "JSON object keys must be strings")
            if "propertyNames" in schema:
                _validate(key, schema["propertyNames"], path + "." + key, depth + 1)
            child_schema = properties.get(key, schema.get("additionalProperties"))
            require(isinstance(child_schema, dict), path + "." + key, "Unknown field")
            _validate(child, child_schema, path + "." + key, depth + 1)
    elif kind == "array":
        require(type(value) is list, path, "Expected an array")
        require(schema["minItems"] <= len(value) <= schema["maxItems"], path, "Array length outside its limit")
        for index, child in enumerate(value):
            _validate(child, schema["items"], f"{path}[{index}]", depth + 1)
    elif kind in ("number", "integer"):
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        require(valid, path, "Expected a finite number")
        require(kind != "integer" or type(value) is int, path, "Expected an integer")
        require(schema["minimum"] <= value <= schema["maximum"], path, "Number outside its limit")
    elif kind == "boolean":
        require(type(value) is bool, path, "Expected a boolean")
    elif kind == "string":
        require(isinstance(value, str), path, "Expected text")
        require(schema["minLength"] <= len(value) <= schema["maxLength"], path, "Text length outside its limit")
        require(schema["minLength"] == 0 or bool(value.strip()), path, "Text cannot be blank")
        require(not any(unicodedata.category(c).startswith("C")
                        and not (path.endswith(".text") and c == "\n") for c in value),
                path, "Control characters are not allowed")
        if "pattern" in schema:
            require(re.fullmatch(schema["pattern"], value) is not None, path, "Invalid text format")


def _canonical(value, field=""):
    if isinstance(value, dict):
        return {k: _canonical(v, k) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical(v, field) for v in value]
    if type(value) is float:
        v = round(value, 6)
        return int(v) if v.is_integer() else v
    if isinstance(value, str) and re.fullmatch("#[0-9A-Fa-f]{6}", value):
        return value.lower()
    if isinstance(value, str) and field in {"name", "front"}:
        return " ".join(value.split())
    return value


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _rectangle(value, path):
    require(value[0] < value[2] and value[1] < value[3], path, "Expected increasing rectangle bounds")


def polygon_area(points):
    return sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(points, points[1:] + points[:1])) / 2


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def simple_polygon(points, path):
    require(len(points) >= 3 and abs(polygon_area(points)) >= 1e-10, path, "Profile must enclose area")
    for i, a in enumerate(points):
        b = points[(i+1) % len(points)]
        require(_distance(a, b) >= MIN_LENGTH - 1e-12, path, "Profile edge shorter than 0.5 mm")
        for j in range(i+1, len(points)):
            if j in ((i+1) % len(points), (i-1) % len(points)):
                continue
            c, d = points[j], points[(j+1) % len(points)]
            o = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
            overlapping = (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) + 1e-12
                           and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])) + 1e-12)
            require(not (overlapping and o[0]*o[1] <= 1e-20 and o[2]*o[3] <= 1e-20),
                    path, "Profile intersects itself")


def _printing(entry, path):
    for i, item in enumerate(entry["print"]["items"]):
        p = f"{path}.print.items[{i}]"
        if "text" in item:
            bad = sorted({c for c in item["text"] if ord(c) not in PRINT_CODEPOINTS})
            require(not bad, p + ".text", "Unsupported characters: " + ", ".join(repr(c) for c in bad),
                    "print_invalid")
            require(item["text"].count("\n") <= 2, p + ".text", "At most three text lines", "print_invalid")
            item.setdefault("weight", "regular")
            item.setdefault("align", "center")
            _rectangle(item["box"], p + ".box")
        for key in ("rect", "barcode", "stripes"):
            if key in item:
                _rectangle(item[key], p + "." + key)
        if "rect" in item or "circle" in item:
            require("fill" in item or "stroke" in item, p, "Supply fill or stroke", "print_invalid")
        if "rect" in item:
            item.setdefault("lineMm", 1)
            item.setdefault("radiusMm", 0)
        if "circle" in item:
            require(item["circle"][2] > 0, p + ".circle", "Circle radius must be positive", "print_invalid")
        if "dots" in item:
            _rectangle(item["dots"]["area"], p + ".dots.area")
            require(2 * item["dots"]["radiusMm"] <= item["dots"]["pitchMm"], p,
                    "Dots must not overlap", "print_invalid")


def normalize_recipe(recipe, *, allowed_categories=None, allowed_appearance_ids=()):
    """Pure validation. None categories means syntax-only; hosts pass their catalog list.

    References and research sources remain input metadata here. portable_recipe()
    removes them before identity or shared-library publication.
    """
    try:
        require(len(json_bytes(recipe)) <= RECIPE_BYTES, "$", "Recipe exceeds 24 KiB", "budget_exceeded")
        _validate(recipe, RECIPE_SCHEMA)
        value = _canonical(deepcopy(recipe))
        if allowed_categories is not None:
            require(value["category"] in allowed_categories, "$.category", "Category is not in the supplied catalog")
        for key, default in {"description": "", "tags": [], "front": [], "references": [], "hangHeight": 0,
                             "surfaces": [], "footprint": "hull"}.items():
            value.setdefault(key, default)
        value["sizeBasis"].setdefault("sources", [])
        for i, source in enumerate(value["sizeBasis"]["sources"]):
            url = urlsplit(source["url"])
            require(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password,
                    f"$.sizeBasis.sources[{i}].url", "Expected an HTTPS citation without credentials")
        for key, material in value["materials"].items():
            for field, default in {"roughness": .6, "metalness": 0, "opacity": 1, "lit": 0}.items():
                material.setdefault(field, default)
            if "finish" in material:
                require(material["finish"]["appearanceId"] in allowed_appearance_ids,
                        f"$.materials.{key}.finish.appearanceId", "Finish is not in the supplied bundled library")
        if "fitsWithin" in value:
            fits = value["fitsWithin"]
            fits.setdefault("orientation", 0)
            fits.setdefault("basis", "user")
            fits.setdefault("note", "")
            fits.setdefault("clearances", {})
            for key in ("front", "back", "sides"):
                fits["clearances"].setdefault(key, 0)
        ids, names = set(), set()
        for i, entry in enumerate(value["entries"]):
            _entry(entry, f"$.entries[{i}]", 0, ids, names, value["materials"])
        require(set(value["front"]) <= names, "$.front", "Front names must exist in the recipe")
        surface_ids = set()
        for i, surface in enumerate(value["surfaces"]):
            require(surface["id"] not in surface_ids, f"$.surfaces[{i}].id", "Surface IDs must be unique")
            surface_ids.add(surface["id"])
            _rectangle(surface["rect"], f"$.surfaces[{i}].rect")
        from .budgets import estimate
        estimate(value)
        # Canonical defaults also fit the recipe cap, so get/revise can round-trip it.
        require(len(json_bytes(value)) <= RECIPE_BYTES, "$", "Normalised recipe exceeds 24 KiB", "budget_exceeded")
        return value
    except ModelBuildError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as error:
        raise ModelBuildError("schema_invalid", "$", "Expected bounded, finite JSON data") from error


def _entry(e, p, depth, ids, names, materials):
    require(e["id"] not in ids, p + ".id", "Entry IDs must be globally unique")
    ids.add(e["id"])
    require(len(ids) <= 400, p, "At most 400 entries", "budget_exceeded")
    patterns = [key for key in PATTERNS if key in e]
    require(len(patterns) <= 1, p, "At most one pattern per entry")
    if "include" not in e:
        e.setdefault("rotate", {})
    if "rotate" in e:
        for axis in "xyz":
            e["rotate"].setdefault(axis, 0)
    if "around" in e:
        e["around"].setdefault("degrees", 360)
    if "grid" in e:
        require(math.prod(e["grid"]["count"]) <= 400, p + ".grid", "At most 400 grid copies", "budget_exceeded")
    if "scatter" in e:
        scatter = e["scatter"]
        require(all(a < b for a, b in zip(scatter["within"]["min"], scatter["within"]["max"])),
                p + ".scatter.within", "Expected increasing bounds")
        for key in ("turnY", "tiltX", "tiltZ"):
            scatter.setdefault(key, [0, 0])
            require(scatter[key][0] <= scatter[key][1], p + ".scatter." + key, "Expected an increasing interval")
        scatter.setdefault("sizeJitter", [0, 0, 0])
    if "group" in e:
        require(depth < 3, p, "At most three group levels", "budget_exceeded")
        e.setdefault("position", [0, 0, 0])
        for i, child in enumerate(e["group"]):
            _entry(child, f"{p}.group[{i}]", depth + 1, ids, names, materials)
        return
    names.add(e["name"])
    if "include" in e:
        require(not patterns, p, "Includes may only be patterned through an ancestor group")
        e.setdefault("position", [0, 0, 0])
        e.setdefault("rotateY", 0)
        e.setdefault("recolor", [])
        for i, rule in enumerate(e["recolor"]):
            require(rule["material"] in materials, f"{p}.recolor[{i}].material", "Unknown material")
        return
    require(e["material"] in materials, p + ".material", "Unknown material")
    shape = e["shape"]
    if shape == "box":
        keys = set(e) & {"min", "max", "center", "size"}
        require(keys in ({"min", "max"}, {"center", "size"}), p, "Choose min/max or center/size")
        if "min" in e:
            require(all(b-a >= MIN_LENGTH - 1e-12 for a, b in zip(e["min"], e["max"])), p, "Box too thin or inverted")
    elif shape == "cylinder":
        e.setdefault("radiusTo", e["radius"])
        e.setdefault("segments", 24)
        e.setdefault("caps", "both")
        require(_distance(e["from"], e["to"]) >= MIN_LENGTH, p + ".to", "Cylinder axis shorter than 0.5 mm")
        require(e["radiusTo"] == 0 or e["radiusTo"] >= MIN_LENGTH, p + ".radiusTo", "Radius too small")
        if "hollow" in e:
            require(e["hollow"] <= min(e["radius"], e["radiusTo"]) - MIN_LENGTH, p + ".hollow",
                    "Wall must leave an inner radius of at least 0.5 mm")
    elif shape == "tube":
        e.setdefault("sides", 12)
        e.setdefault("closed", False)
        if e["closed"] and e["path"][0] == e["path"][-1]:
            e["path"].pop()
        require(len(e["path"]) >= (3 if e["closed"] else 2), p + ".path", "Too few distinct tube points")
        points = e["path"] + (e["path"][:1] if e["closed"] else [])
        require(all(_distance(a, b) >= MIN_LENGTH for a, b in zip(points, points[1:])), p + ".path",
                "Tube segment shorter than 0.5 mm")
    elif shape == "lathe":
        e.setdefault("axis", "y")
        e.setdefault("segments", 32)
        e.setdefault("degrees", 360)
        require(all(r >= 0 for r, _ in e["profile"]) and max(r for r, _ in e["profile"]) >= MIN_LENGTH,
                p + ".profile", "Radii must be nonnegative")
        profile = lathe_profile(e["profile"])
        simple_polygon(profile, p + ".profile")
        # An intermediate axis vertex pinches two solids together at a point.
        # Keep a single contiguous axis edge, or a profile wholly off-axis.
        axis_runs = sum(a[0] != 0 and b[0] == 0 for a, b in zip(profile, profile[1:] + profile[:1]))
        require(axis_runs <= 1, p + ".profile", "Profile pinches at the rotation axis")
    elif shape == "torus":
        e.setdefault("axis", "y")
        e.setdefault("segments", 24)
        require(e["radius"] > e["tubeRadius"], p + ".tubeRadius", "Torus must have an open centre")
    elif shape == "sphere":
        e.setdefault("part", "whole")
    elif shape == "extrude":
        simple_polygon(e["profile"], p + ".profile")
    elif shape == "panel":
        require("finish" not in materials[e["material"]], p + ".material",
                "Printed front materials cannot have a default finish", "print_invalid")
        e.setdefault("back", materials[e["material"]]["color"])
        _printing(e, p)


def lathe_profile(profile):
    """An open radial path closes by its bottom edge; two points describe a capped solid."""
    profile = [list(p) for p in profile]
    if profile[0] == profile[-1]:
        profile.pop()
    if len(profile) == 2:
        profile = [[0, profile[0][1]], *profile, [0, profile[-1][1]]]
        profile = [p for i, p in enumerate(profile) if i == 0 or p != profile[i-1]]
    return profile


def portable_recipe(normalized):
    value = deepcopy(normalized)
    references = value.pop("references", [])
    sources = value["sizeBasis"].pop("sources", [])
    return value, {"references": references, "sources": sources}
