"""The host validates small worker JSON; it never decodes source models or images."""
import math
import re

from .errors import ModelImportError
from .limits import CACHE_BYTES, CACHE_METADATA_BYTES, SUMMARY_BYTES, PREVIEW_BYTES, INSPECTION_BYTES
from .validation import clean_text, json_bytes, parse_json

SUMMARY_KEYS = {
    "schemaVersion", "name", "format", "state", "refusal", "sourceBytes", "sourceSha256", "triangles",
    "rawBounds", "rawSize", "unitGuesses", "upAxisHint", "licence", "partsTotal", "partsOffset",
    "parts", "nextPartsOffset", "materials", "materialsTotal", "flatTopHints", "warnings",
}
MATERIAL_KEYS = {"name", "baseColor", "textureSize", "alphaMode", "alphaCutoff", "emissive",
                 "doubleSided", "roughness", "metalness", "unlit"}


def _ok(condition):
    if not condition:
        raise ModelImportError("model_worker_failed")


def _int(value, low=0, high=2**63 - 1):
    _ok(type(value) is int and low <= value <= high)


def _num(value, low=-math.inf, high=math.inf):
    _ok(type(value) in (int, float))
    try:
        _ok(math.isfinite(value) and low <= value <= high)
    except OverflowError:
        _ok(False)


def _text(value, maximum):
    _ok(isinstance(value, str) and len(value) <= maximum and clean_text(value, maximum) == value)


def _keys(value, keys):
    _ok(isinstance(value, dict) and set(value) == set(keys))


def _list(value, maximum):
    _ok(isinstance(value, list) and len(value) <= maximum)


def _vector(value, length, low=-math.inf, high=math.inf):
    _list(value, length)
    _ok(len(value) == length)
    for entry in value:
        _num(entry, low, high)


def _bounds(value):
    _keys(value, {"minimum", "maximum"})
    _vector(value["minimum"], 3)
    _vector(value["maximum"], 3)
    _ok(all(a <= b for a, b in zip(value["minimum"], value["maximum"])))


def _size(value):
    _keys(value, {"width", "height", "depth"})
    for entry in value.values():
        _num(entry, 0)


def _material(value):
    _keys(value, MATERIAL_KEYS)
    _text(value["name"], 80)
    _vector(value["baseColor"], 4, 0, 1)
    _vector(value["emissive"], 3, 0)
    _num(value["roughness"], 0, 1)
    _num(value["metalness"], 0, 1)
    _num(value["alphaCutoff"], 0)
    _ok(value["alphaMode"] in ("OPAQUE", "MASK", "BLEND"))
    _ok(type(value["doubleSided"]) is bool and type(value["unlit"]) is bool)
    if value["textureSize"] is not None:
        _list(value["textureSize"], 2)
        _ok(len(value["textureSize"]) == 2)
        for dimension in value["textureSize"]:
            _int(dimension, 1, 2048)


def validate_source_part(part):
    _keys(part, (MATERIAL_KEYS - {"name"}) | {"key", "name", "node", "mesh", "material", "triangles", "bounds"})
    _ok(isinstance(part["key"], str) and re.fullmatch(r"p[0-9]{1,4}", part["key"]))
    for key in ("name", "node", "mesh", "material"):
        _text(part[key], 80)
    _int(part["triangles"], 1, 2_000_000)
    _bounds(part["bounds"])
    _material({key: part[key] for key in MATERIAL_KEYS})


def validate_licence(licence, excerpt_limit=600):
    _keys(licence, {"class", "title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl", "excerpt", "conflicts"})
    _ok(licence["class"] in ("cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nd",
                            "cc-by-nc-sa", "cc-by-nc-nd", "other", "unknown"))
    for key in ("title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl", "excerpt"):
        _text(licence[key], excerpt_limit if key == "excerpt" else 300)
    _list(licence["conflicts"], 6)
    for conflict in licence["conflicts"]:
        _keys(conflict, {"field", "values"})
        _ok(conflict["field"] in ("title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl"))
        _list(conflict["values"], 4)
        for item in conflict["values"]:
            _text(item, 300)


def validate_summary(value: dict) -> dict:
    try:
        _keys(value, SUMMARY_KEYS)
        _ok(len(json_bytes(value)) <= SUMMARY_BYTES)
        _ok(value["schemaVersion"] == 1 and type(value["schemaVersion"]) is int
            and value["state"] == "ready" and value["refusal"] is None)
        _text(value["name"], 80)
        _ok(value["format"] in ("glb", "glb-zip", "gltf-zip"))
        _int(value["sourceBytes"], 1, 128 * 1024 * 1024)
        _ok(isinstance(value["sourceSha256"], str) and re.fullmatch("[a-f0-9]{64}", value["sourceSha256"]))
        _int(value["triangles"], 1, 2_000_000)
        _bounds(value["rawBounds"])
        _size(value["rawSize"])
        _list(value["unitGuesses"], 4)
        _ok(len(value["unitGuesses"]) == 4)
        for guess in value["unitGuesses"]:
            _keys(guess, {"unit", "metersPerUnit", "sizeMeters"})
            _ok(guess["unit"] in ("m", "cm", "mm", "in"))
            _num(guess["metersPerUnit"], 0.001, 1)
            _size(guess["sizeMeters"])
        hint = value["upAxisHint"]
        _keys(hint, {"declared", "generator", "bounds", "suggested", "note"})
        _ok(hint["declared"] == "+Y" and hint["suggested"] in ("+Z", "unknown"))
        _text(hint["generator"], 300)
        _text(hint["note"], 300)
        _bounds(hint["bounds"])
        validate_licence(value["licence"])
        _int(value["partsTotal"], 1, 4096)
        _int(value["partsOffset"], 0, value["partsTotal"])
        _list(value["parts"], 64)
        for part in value["parts"]:
            validate_source_part(part)
        _ok(value["partsOffset"] + len(value["parts"]) <= value["partsTotal"])
        expected = value["partsOffset"] + len(value["parts"])
        _ok(value["nextPartsOffset"] == (expected if expected < value["partsTotal"] else None))
        _int(value["materialsTotal"], 1, 64)
        _list(value["materials"], value["materialsTotal"])
        for material in value["materials"]:
            _material(material)
        _list(value["flatTopHints"], 6)
        for hint in value["flatTopHints"]:
            _keys(hint, {"part", "height", "rect", "verifiedSupport"})
            _text(hint["part"], 5)
            _num(hint["height"])
            _vector(hint["rect"], 4)
            _ok(hint["verifiedSupport"] is False)
        _list(value["warnings"], 20)
        for warning in value["warnings"]:
            _text(warning, 300)
        return value
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise ModelImportError("model_worker_failed") from None


def read_summary(payload: bytes) -> dict:
    try:
        return validate_summary(parse_json(payload, SUMMARY_BYTES))
    except ModelImportError:
        raise ModelImportError("model_worker_failed") from None


def validate_manifest(value) -> dict:
    _keys(value, {"schemaVersion", "files"})
    _ok(type(value["schemaVersion"]) is int and value["schemaVersion"] in (1, 2, 3))
    files = {"summary.json": SUMMARY_BYTES, "cache.json": CACHE_METADATA_BYTES, "parts.npz": CACHE_BYTES}
    if value["schemaVersion"] >= 2:
        files["preview.png"] = PREVIEW_BYTES
    if value["schemaVersion"] == 3:
        files["inspection.json"] = INSPECTION_BYTES
    _keys(value["files"], files)
    for name, maximum in files.items():
        entry = value["files"][name]
        _keys(entry, {"bytes", "sha256"})
        _int(entry["bytes"], 1, maximum)
        _ok(isinstance(entry["sha256"], str) and re.fullmatch("[a-f0-9]{64}", entry["sha256"]))
    return value
