"""Bounded agent recipe schema and dependency-free canonical normalization.

Category is an open catalog string, as in _private_manifest_specs; the live catalog
has no fixed enum. This validator implements only the schema keywords used below,
so the isolated worker needs no jsonschema dependency.
"""
from copy import deepcopy
import math
import re

from .errors import ModelImportError
from .diagnostics import recipe_error
from .licence import https_url
from .validation import clean_text, json_bytes

MODEL_IMPORT_ENGINE_VERSION = "model-import-1"
RECIPE_BYTES = 32 * 1024
LICENSE_CLASSES = ["cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nd",
                   "cc-by-nc-sa", "cc-by-nc-nd", "other", "unknown"]


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def text(limit=80, minimum=1):
    return {"type": "string", "minLength": minimum, "maxLength": limit}


def num(low, high):
    return {"type": "number", "minimum": low, "maximum": high}


def array(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def enum(*values):
    return {"enum": list(values)}


ANGLE = num(-360, 360)
POSITION = array(num(-100, 100), 3, 3)
COLOR = {**text(7), "pattern": "^#[0-9a-fA-F]{6}$"}
SELECTOR = {"oneOf": [obj({key: value}, [key]) for key, value in
                      (("part", {**text(), "pattern": "^p[0-9]{1,5}$"}), ("mesh", text()),
                       ("material", text()), ("node", text()), ("all", {"const": True}))]}
MATERIAL_PATCH = obj({
    "color": COLOR, "roughness": num(0, 1), "metalness": num(0, 1),
    "texture": enum("keep", "drop"), "emissive": enum("keep", "off"),
    "alpha": enum("opaque", "mask", "blend"), "alphaCutoff": num(.05, .95),
    "doubleSided": {"type": "boolean"},
})
PART_RULE = obj({"select": SELECTOR, "name": text(), "drop": {"type": "boolean"},
                 "material": MATERIAL_PATCH, "scale": num(.05, 20), "turnDegrees": ANGLE,
                 "move": POSITION, "moveTo": POSITION}, ["select"])
PART_RULE["not"] = {"required": ["move", "moveTo"]}
ADD_COMMON = {"position": POSITION, "turnDegrees": ANGLE, "name": text(), "color": COLOR,
              "roughness": num(0, 1), "metalness": num(0, 1)}
ADDITION = {"oneOf": [
    obj({**ADD_COMMON, "shape": {"const": "box"}, "size": array(num(.0001, 30), 3, 3)},
        ["shape", "size", "name", "color"]),
    obj({**ADD_COMMON, "shape": {"const": "cylinder"}, "radius": num(.0001, 15),
         "height": num(.0001, 30), "hollow": num(.000001, 15)},
        ["shape", "radius", "height", "name", "color"]),
    obj({**ADD_COMMON, "shape": {"const": "frustum"}, "radiusTop": num(.0001, 15),
         "radiusBottom": num(.0001, 15), "height": num(.0001, 30), "hollow": num(.000001, 15)},
        ["shape", "radiusTop", "radiusBottom", "height", "name", "color"]),
]}
ATTRIBUTION = obj({**{k: text(300, 0) for k in
                      ("title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl")},
                   "licenseClass": enum(*LICENSE_CLASSES), "statedBy": {"const": "user"}}, ["statedBy"])
RECIPE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **obj({
        "importId": {**text(27), "pattern": "^mi-[0-9a-f]{24}$"},
        "name": text(), "category": text(), "description": text(300),
        "tags": array(text(), 8),
        "rotate": obj({axis: ANGLE for axis in "xyz"}),
        "pivot": {"oneOf": [{"const": "base"}, obj({"parts": array(SELECTOR, 64, 1)}, ["parts"])]},
        "size": {"oneOf": [obj({"dimension": enum("height", "width", "depth", "largest"),
                                "meters": num(.01, 30)}, ["dimension", "meters"]),
                            obj({"scale": num(.0001, 10000)}, ["scale"])]},
        "parts": array(PART_RULE, 64),
        "textureMaxPx": {"type": "integer", "enum": [256, 512, 1024, 2048]},
        "copies": array(obj({"x": num(-100, 100), "z": num(-100, 100),
                              "turnDegrees": ANGLE, "scale": num(.5, 2)}), 12, 1),
        "add": array(ADDITION, 8),
        "surfaces": array(obj({"id": text(), "label": text(), "height": num(0, 100),
                               "rect": array(num(-100, 100), 4, 4)}, ["id", "label", "height", "rect"]), 6),
        "footprint": enum("hull", "box"), "attribution": ATTRIBUTION, "changesNote": text(200, 0),
    }, ["importId", "name", "category"]),
}


def _valid(value, schema) -> bool:
    if "oneOf" in schema and sum(_valid(value, item) for item in schema["oneOf"]) != 1:
        return False
    if "not" in schema and _valid(value, schema["not"]):
        return False
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        return False
    if "enum" in schema and (isinstance(value, bool) or value not in schema["enum"]):
        return False
    kind = schema.get("type")
    if kind == "object" and not isinstance(value, dict):
        return False
    if isinstance(value, dict):
        if not set(schema.get("required", ())) <= value.keys():
            return False
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and not value.keys() <= props.keys():
            return False
        if any(not _valid(v, props[k]) for k, v in value.items() if k in props):
            return False
    if kind == "array":
        if not isinstance(value, list) or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            return False
        if any(not _valid(v, schema["items"]) for v in value):
            return False
    if kind in {"number", "integer"}:
        if type(value) not in (int, float):
            return False
        try:
            if not math.isfinite(value):
                return False
        except OverflowError:
            return False
        if kind == "integer" and value != int(value):
            return False
        if not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            return False
    if kind == "boolean" and type(value) is not bool:
        return False
    if kind == "string":
        if not isinstance(value, str) or not schema["minLength"] <= len(value) <= schema["maxLength"]:
            return False
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            return False
    return True


def _path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else str(key)


def _problems(value, schema, path="") -> list[tuple[str, str]]:
    """Explain the bounded schema subset without a worker jsonschema dependency."""
    label = path or "recipe"
    if "oneOf" in schema:
        options = schema["oneOf"]
        matches = [option for option in options if _valid(value, option)]
        if len(matches) == 1:
            return []
        if not isinstance(value, dict):
            choices = [str(option["const"]) for option in options if "const" in option]
            return [(label, "expected " + (" or ".join(choices) + " or an object" if choices else "one selector object"))]
        if not value:
            return [(label, "choose one form: " + " | ".join("/".join(o.get("required", ())) for o in options))]
        def score(option):
            properties = option.get("properties", {})
            shared = value.keys() & properties.keys()
            constants = sum("const" in properties[k] and value[k] == properties[k]["const"] for k in shared)
            return constants * 100 + len(shared) * 10 - len(value.keys() - properties.keys())
        chosen = max(options, key=score)
        return _problems(value, chosen, path) or [(label, "must match exactly one allowed form")]
    kind = schema.get("type")
    expected = {"object": dict, "array": list, "string": str, "boolean": bool}
    if kind in expected and not isinstance(value, expected[kind]):
        return [(label, "expected " + kind)]
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        return [(label, "expected " + repr(schema["const"]).lower())]
    if "enum" in schema and (isinstance(value, bool) or value not in schema["enum"]):
        return [(label, "expected one of: " + ", ".join(str(v) for v in schema["enum"]))]
    if kind in {"number", "integer"}:
        try:
            finite = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            return [(label, "expected a finite " + kind)]
        if kind == "integer" and value != int(value):
            return [(label, "expected integer")]
        low, high = schema.get("minimum", -math.inf), schema.get("maximum", math.inf)
        return [] if low <= value <= high else [(label, f"must be {low:g}-{high:g}")]
    if kind == "string":
        if schema.get("pattern") == "^#[0-9a-fA-F]{6}$" and re.fullmatch(schema["pattern"], value) is None:
            return [(label, "expected #rrggbb")]
        if not schema["minLength"] <= len(value) <= schema["maxLength"]:
            return [(label, f"length must be {schema['minLength']}-{schema['maxLength']} characters")]
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            expected_pattern = {"^#[0-9a-fA-F]{6}$": "#rrggbb", "^mi-[0-9a-f]{24}$": "mi- followed by 24 lowercase hex digits",
                                "^p[0-9]{1,5}$": "a part key such as p0"}
            return [(label, "expected " + expected_pattern.get(schema["pattern"], "the required format"))]
    problems = []
    if kind == "object":
        for key in schema.get("required", ()):
            if key not in value:
                problems.append((_path(path, key), "required"))
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key not in properties and schema.get("additionalProperties") is False:
                problems.append((_path(path, key), "unknown field"))
            elif key in properties:
                problems.extend(_problems(item, properties[key], _path(path, key)))
            if len(problems) >= 5:
                break
        if "not" in schema and _valid(value, schema["not"]):
            problems.append((label, "move and moveTo cannot both be supplied"))
    if kind == "array":
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            return [(label, f"must contain {schema['minItems']}-{schema['maxItems']} items")]
        for i, item in enumerate(value):
            problems.extend(_problems(item, schema["items"], f"{path}[{i}]"))
            if len(problems) >= 5:
                break
    return problems[:5]


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return clean_text(value, len(value))
    if type(value) in (int, float):
        result = round(float(value), 6)
        return int(result) if result.is_integer() else result
    return value


def normalize_recipe(recipe: dict) -> dict:
    """No paths or model data in a recipe; defaults have one canonical spelling."""
    try:
        problems = _problems(recipe, RECIPE_SCHEMA)
        if problems:
            raise recipe_error(problems)
        if len(json_bytes(recipe)) > RECIPE_BYTES:
            raise recipe_error([("recipe", "must be at most 32768 bytes")])
        value = _clean(deepcopy(recipe))
        defaults = {"description": "Imported static model.", "tags": [], "rotate": {},
                    "pivot": "base", "size": {"scale": 1}, "parts": [], "textureMaxPx": 1024,
                    "copies": [{}], "add": [], "surfaces": [], "footprint": "hull", "changesNote": ""}
        for key, default in defaults.items():
            value.setdefault(key, default)
        for axis in "xyz":
            value["rotate"].setdefault(axis, 0)
        for rule in value["parts"]:
            for key, default in {"drop": False, "material": {}, "scale": 1, "turnDegrees": 0}.items():
                rule.setdefault(key, default)
            if "moveTo" not in rule:
                rule.setdefault("move", [0, 0, 0])
            rule["material"].setdefault("texture", "keep")
            rule["material"].setdefault("emissive", "keep")
            if "color" in rule["material"]:
                rule["material"]["color"] = rule["material"]["color"].lower()
        for copy in value["copies"]:
            for key, default in {"x": 0, "z": 0, "turnDegrees": 0, "scale": 1}.items():
                copy.setdefault(key, default)
        semantic = []
        for index, addition in enumerate(value["add"]):
            for key, default in {"position": [0, 0, 0], "turnDegrees": 0,
                                 "roughness": .8, "metalness": 0}.items():
                addition.setdefault(key, default)
            addition["color"] = addition["color"].lower()
            if "hollow" in addition:
                radius = addition.get("radius", min(addition.get("radiusTop", 1), addition.get("radiusBottom", 1)))
                if addition["hollow"] >= min(radius, addition["height"]):
                    semantic.append((f"add[{index}].hollow", "must be smaller than the height and both radii"))
        seen = set()
        for index, surface in enumerate(value["surfaces"]):
            x0, z0, x1, z1 = surface["rect"]
            if x0 >= x1 or z0 >= z1:
                semantic.append((f"surfaces[{index}].rect", "expected x0 < x1 and z0 < z1"))
            if surface["id"] in seen:
                semantic.append((f"surfaces[{index}].id", "must be unique"))
            seen.add(surface["id"])
        for key in ("authorUrl", "sourceUrl", "licenseUrl"):
            url = value.get("attribution", {}).get(key)
            if url and https_url(url) != url:
                semantic.append(("attribution." + key, "expected an https URL without credentials or control characters"))
        semantic.extend(_problems(value, RECIPE_SCHEMA))
        if semantic:
            raise recipe_error(semantic)
        if len(json_bytes(value)) > RECIPE_BYTES:
            raise recipe_error([("recipe", "normalized recipe must be at most 32768 bytes")])
        return value
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise recipe_error([("recipe", "expected bounded JSON with finite numbers")]) from None
