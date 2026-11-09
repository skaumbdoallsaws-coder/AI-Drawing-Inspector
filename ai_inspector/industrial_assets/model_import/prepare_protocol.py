"""Validate prepare results without importing numpy, Pillow or application code."""
import re

from .credit import credits_text
from .errors import ModelImportError
from .identity import asset_identity
from .job_io import bounded_read, file_digest, local_directory, regular_file
from .licence import https_url
from .limits import PREVIEW_BYTES, THUMBNAIL_BYTES
from .pictures import validate_picture
from .protocol import _int, _keys, _list, _material, _num, _ok, _size, _text
from .recipe import LICENSE_CLASSES, MODEL_IMPORT_ENGINE_VERSION, normalize_recipe
from .validation import json_bytes, parse_json

DRAFT_BYTES = 128 * 1024
DRAFT_FILES = {"model.glb": 30 * 1024 * 1024, "draft.json": DRAFT_BYTES,
               "CREDITS.txt": 16 * 1024, "parts.jsonl": 32 * 1024 * 1024,
               "preview.png": PREVIEW_BYTES, "thumbnail.webp": THUMBNAIL_BYTES}
PUBLIC_FIELDS = ("draftId", "dimensions", "triangles", "partsTotal", "parts", "nextPartsOffset",
                 "materialsTotal", "materials", "surfaces", "footprint", "warnings", "attribution", "changes")


def validate_part(part, index=None):
    _keys(part, {"key", "name", "triangles"})
    _ok(isinstance(part["key"], str) and re.fullmatch("p[0-9]{1,5}", part["key"]))
    if index is not None:
        _ok(part["key"] == f"p{index}")
    _text(part["name"], 80)
    _int(part["triangles"], 1, 250000)


def validate_draft(value):
    try:
        _keys(value, {*PUBLIC_FIELDS, "schemaVersion", "engineVersion", "recipe", "sourceSha256", "outputSha256"})
        _ok(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1)
        _ok(value["engineVersion"] == MODEL_IMPORT_ENGINE_VERSION)
        _ok(normalize_recipe(value["recipe"]) == value["recipe"])
        for key in ("sourceSha256", "outputSha256"):
            _ok(isinstance(value[key], str) and re.fullmatch("[0-9a-f]{64}", value[key]))
        _size(value["dimensions"])
        for size in value["dimensions"].values():
            _num(size, 1e-8, 10000)
        _int(value["triangles"], 1, 250000)
        _int(value["partsTotal"], 1, 4096 * 12 + 8)
        _list(value["parts"], 64)
        _ok(0 < len(value["parts"]) <= value["partsTotal"])
        for i, part in enumerate(value["parts"]):
            validate_part(part, i)
        _ok(sum(p["triangles"] for p in value["parts"]) <= value["triangles"])
        _ok(value["nextPartsOffset"] == (len(value["parts"]) if len(value["parts"]) < value["partsTotal"] else None))
        _int(value["materialsTotal"], 1, value["partsTotal"])
        _list(value["materials"], min(64, value["materialsTotal"]))
        for material in value["materials"]:
            _material(material)
        _list(value["warnings"], 20)
        for warning in value["warnings"]:
            _text(warning, 300)
        credit = value["attribution"]
        _keys(credit, {"title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl",
                       "licenseClass", "statedBy", "changes"})
        for key in ("title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl"):
            _text(credit[key], 300)
            if key.endswith("Url") and credit[key]:
                _ok(https_url(credit[key]) == credit[key])
        _ok(credit["licenseClass"] in LICENSE_CLASSES and credit["statedBy"] in {"file", "user"})
        _text(value["changes"], 600)
        _ok(credit["changes"] == value["changes"])
        _surfaces(value)
        _footprint(value)
        _ok(value["draftId"] == "md-" + asset_identity(value)["sha256"][:24])
        _ok(len(json_bytes({k: value[k] for k in PUBLIC_FIELDS})) <= 48 * 1024)
        _ok(len(json_bytes(value)) <= DRAFT_BYTES)
        return value
    except (ModelImportError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise ModelImportError("model_worker_failed") from None


def _surfaces(draft):
    _list(draft["surfaces"], 6)
    expected = []
    # Same simple catalog mapping as the numerical worker, intentionally no numpy import.
    for source in draft["recipe"]["surfaces"]:
        x0, z0, x1, z1 = source["rect"]
        size = draft["dimensions"]
        _ok(-size["width"] / 2 - 1e-7 <= x0 < x1 <= size["width"] / 2 + 1e-7)
        _ok(-size["depth"] / 2 - 1e-7 <= z0 < z1 <= size["depth"] / 2 + 1e-7)
        _ok(source["height"] <= size["height"] + 1e-7)
        expected.append({"surfaceId": source["id"], "label": source["label"],
                         "localFrame": {"origin": {"x": (x0 + x1) / 2, "y": source["height"], "z": (z0 + z1) / 2},
                                        "xAxis": {"x": 1, "y": 0, "z": 0}, "zAxis": {"x": 0, "y": 0, "z": 1},
                                        "normal": {"x": 0, "y": 1, "z": 0}},
                         "bounds": {"minimumX": -(x1 - x0) / 2, "maximumX": (x1 - x0) / 2,
                                    "minimumZ": -(z1 - z0) / 2, "maximumZ": (z1 - z0) / 2},
                         "allowedSides": ["above"], "evidenceStatus": "authored"})
    _ok(draft["surfaces"] == expected)


def _footprint(draft):
    polygons = draft["footprint"]
    _list(polygons, 1)
    _ok(len(polygons) == 1)
    polygon = polygons[0]
    _list(polygon, 32)
    _ok(len(polygon) >= 3)
    for point in polygon:
        _keys(point, {"x", "z"})
        _num(point["x"], -draft["dimensions"]["width"] / 2 - 1e-8, draft["dimensions"]["width"] / 2 + 1e-8)
        _num(point["z"], -draft["dimensions"]["depth"] / 2 - 1e-8, draft["dimensions"]["depth"] / 2 + 1e-8)
    pairs = [(p["x"], p["z"]) for p in polygon]
    _ok(len(set(pairs)) == len(pairs))
    area = sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(pairs, pairs[1:] + pairs[:1]))
    _ok(area > 2e-9)
    for i, (ax, az) in enumerate(pairs):
        bx, bz = pairs[(i + 1) % len(pairs)]
        _ok(all((bx - ax) * (z - az) - (bz - az) * (x - ax) >= -1e-8 for x, z in pairs))


def read_draft_output(directory):
    """Fixed filenames, hashes, scalar schema and complete parts ledger checked before publish."""
    try:
        directory = local_directory(directory)
        _ok({p.name for p in directory.iterdir()} == {*DRAFT_FILES, "manifest.json"})
        manifest = parse_json(bounded_read(directory, "manifest.json", 4096), 4096)
        _keys(manifest, {"schemaVersion", "files"})
        _ok(type(manifest["schemaVersion"]) is int and manifest["schemaVersion"] == 2)
        _keys(manifest["files"], DRAFT_FILES)
        for name, maximum in DRAFT_FILES.items():
            entry = manifest["files"][name]
            _keys(entry, {"bytes", "sha256"})
            _int(entry["bytes"], 1, maximum)
            _ok(isinstance(entry["sha256"], str) and re.fullmatch("[0-9a-f]{64}", entry["sha256"]))
            file = regular_file(directory, name)
            _ok(file.stat().st_size == entry["bytes"] and file_digest(file) == entry["sha256"])
        validate_picture(bounded_read(directory, "preview.png", PREVIEW_BYTES), "preview")
        validate_picture(bounded_read(directory, "thumbnail.webp", THUMBNAIL_BYTES), "thumbnail")
        draft = validate_draft(parse_json(bounded_read(directory, "draft.json", DRAFT_BYTES), DRAFT_BYTES))
        _ok(draft["outputSha256"] == manifest["files"]["model.glb"]["sha256"])
        _ok(bounded_read(directory, "CREDITS.txt", DRAFT_FILES["CREDITS.txt"]) ==
            credits_text(draft["attribution"]).encode("utf-8"))
        count, triangles = 0, 0
        with regular_file(directory, "parts.jsonl").open("rb") as stream:
            while line := stream.readline(2049):
                _ok(len(line) <= 2048 and line.endswith(b"\n"))
                part = parse_json(line, 2048)
                validate_part(part, count)
                if count < len(draft["parts"]):
                    _ok(part == draft["parts"][count])
                count += 1
                triangles += part["triangles"]
                _ok(count <= draft["partsTotal"] and triangles <= draft["triangles"])
        _ok(count == draft["partsTotal"] and triangles == draft["triangles"])
        return draft
    except (ModelImportError, OSError, KeyError, ValueError, TypeError, OverflowError):
        raise ModelImportError("model_worker_failed") from None
