"""Frozen build drafts. Pure validation and bounded local I/O, no application parents."""
from copy import deepcopy
from hashlib import sha256
import math
import re

from .errors import json_bytes, parse_json
from .identity import asset_identity, build_provenance
from .imports import module
from .job_io import directory, read_bytes
from .recipe import ENGINE_VERSION, RECIPE_BYTES, normalize_recipe
from .protocol import RESULT_BYTES, GLB_BYTES

DAY = 86400
DRAFT_BYTES = 1024*1024
FILES = {"draft.json": DRAFT_BYTES, "recipe.json": RECIPE_BYTES, "result.json": RESULT_BYTES,
         "model.glb": GLB_BYTES, "preview.png": 1536*1024, "thumbnail.webp": 64*1024, "CREDITS.txt": 16*1024}
HEAVY = {"model.glb", "thumbnail.webp", "CREDITS.txt"}
FIELDS = {"schemaVersion", "kind", "scope", "created", "expires", "draftId", "assetId", "identitySha256",
          "engineVersion", "recipe", "outputSha256", "dimensions", "catalogDimensions", "triangles", "includes",
          "attribution", "surfaces", "footprint", "buildProvenance"}


def normalized_frozen(recipe):
    """Validate frozen syntax without depending on today's appearance/category library."""
    appearances = [m["finish"]["appearanceId"] for m in recipe["materials"].values() if "finish" in m]
    return normalize_recipe(recipe, allowed_categories=[recipe["category"]], allowed_appearance_ids=appearances)


def make_draft(recipe, result, scope, created, derived_from=None):
    value = {"schemaVersion": 1, "kind": "build", "scope": scope, "created": created, "expires": created+7*DAY,
             "engineVersion": ENGINE_VERSION, "recipe": deepcopy(recipe),
             **{k: deepcopy(result[k]) for k in ("outputSha256", "dimensions", "catalogDimensions", "triangles", "includes",
                                                "attribution", "surfaces", "footprint")},
             "buildProvenance": build_provenance(recipe, result["triangles"], derived_from)}
    identity = asset_identity(value)
    value.update(draftId="md-"+identity["sha256"][:24], assetId=identity["assetId"], identitySha256=identity["sha256"])
    return validate_draft(value)


def validate_draft(value):
    if (type(value) is not dict or set(value) != FIELDS or value["kind"] != "build"
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1):
        raise ValueError("Invalid build draft fields")
    if value["engineVersion"] != ENGINE_VERSION or not isinstance(value["scope"], str) or not re.fullmatch("[0-9a-f]{24}", value["scope"]):
        raise ValueError("Invalid build draft scope or engine")
    if any(type(value[k]) not in (int, float) or not math.isfinite(value[k]) or not 0 < value[k] < 1e12 for k in ("created", "expires")):
        raise ValueError("Invalid build draft dates")
    if value["expires"] != value["created"]+7*DAY or normalized_frozen(value["recipe"]) != value["recipe"]:
        raise ValueError("Invalid build draft recipe or expiry")
    for key in ("outputSha256", "identitySha256"):
        if not isinstance(value[key], str) or not re.fullmatch("[0-9a-f]{64}", value[key]):
            raise ValueError("Invalid build draft digest")
    provenance = build_provenance(value["recipe"], value["triangles"], value["buildProvenance"].get("derivedFrom"))
    if value["buildProvenance"] != provenance:
        raise ValueError("Build provenance differs from its frozen recipe")
    for field in ("dimensions", "catalogDimensions"):
        size = value[field]
        if type(size) is not dict or set(size) != {"width", "height", "depth"} or any(
                type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 30 for v in size.values()):
            raise ValueError("Invalid build draft dimensions")
    if value["catalogDimensions"] != dict(value["dimensions"], height=value["dimensions"]["height"]+value["recipe"]["hangHeight"]):
        raise ValueError("Invalid hung model dimensions")
    identity = asset_identity(value)
    if (value["draftId"] != "md-"+identity["sha256"][:24] or value["assetId"] != identity["assetId"]
            or value["identitySha256"] != identity["sha256"] or len(json_bytes(value)) > DRAFT_BYTES):
        raise ValueError("Invalid build draft identity")
    return value


def result_matches(draft, result):
    if (result.get("kind") != "build" or result.get("engineVersion") != ENGINE_VERSION
            or result.get("recipeSha256") != sha256(json_bytes(draft["recipe"])).hexdigest()):
        raise ValueError("Build result differs from its draft recipe")
    for key in ("outputSha256", "dimensions", "catalogDimensions", "triangles", "includes", "attribution", "surfaces", "footprint"):
        if json_bytes(result.get(key)) != json_bytes(draft[key]):
            raise ValueError("Build result differs from its frozen draft")


def write_draft(destination, recipe, result, payload, preview, thumbnail, *, scope, created, derived_from=None):
    value = make_draft(recipe, result, scope, created, derived_from)
    result_matches(value, result)
    files = {"draft.json": json_bytes(value), "recipe.json": json_bytes(recipe), "result.json": json_bytes(result),
             "model.glb": payload, "preview.png": preview, "thumbnail.webp": thumbnail}
    if value["attribution"] is not None:
        files["CREDITS.txt"] = module("credit").credits_text(value["attribution"]).encode("utf-8")
    destination.mkdir()
    destination = directory(destination)
    for name, data in files.items():
        if not isinstance(data, bytes) or not 0 < len(data) <= FILES[name]:
            raise ValueError("Build draft file exceeds its limit")
        with (destination / name).open("xb") as stream:
            stream.write(data)
    manifest = {"schemaVersion": 1, "kind": "build", "files": {
        name: {"bytes": len(data), "sha256": sha256(data).hexdigest()} for name, data in files.items()}}
    with (destination / "manifest.json").open("xb") as stream:
        stream.write(json_bytes(manifest))
    read_draft(destination)
    return value


def read_draft(folder, *, compact=False):
    folder = directory(folder)
    value = validate_draft(parse_json(read_bytes(folder, "draft.json", DRAFT_BYTES), DRAFT_BYTES))
    manifest = parse_json(read_bytes(folder, "manifest.json", 4096), 4096)
    wanted = set(FILES) - ({"CREDITS.txt"} if value["attribution"] is None else set())
    if (type(manifest) is not dict or set(manifest) != {"schemaVersion", "kind", "files"}
            or manifest["kind"] != "build" or type(manifest["schemaVersion"]) is not int
            or manifest["schemaVersion"] != 1 or set(manifest["files"]) != wanted):
        raise ValueError("Invalid build draft manifest")
    from .job_io import names
    present = names(folder, len(FILES)+1)
    required = wanted-HEAVY if compact else wanted
    if not (required | {"manifest.json"}) <= present or not present <= (wanted | {"manifest.json"}):
        raise ValueError("Unexpected build draft files")
    for name in sorted(wanted & present):
        payload = read_bytes(folder, name, FILES[name])
        if manifest["files"][name] != {"bytes": len(payload), "sha256": sha256(payload).hexdigest()}:
            raise ValueError("Build draft file differs from its frozen manifest")
    for name in wanted:
        entry = manifest["files"][name]
        if (type(entry) is not dict or set(entry) != {"bytes", "sha256"}
                or type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= FILES[name]
                or not isinstance(entry["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])):
            raise ValueError("Invalid build file digest")
    if manifest["files"]["model.glb"]["sha256"] != value["outputSha256"]:
        raise ValueError("Build manifest differs from its output identity")
    if parse_json(read_bytes(folder, "recipe.json", RECIPE_BYTES), RECIPE_BYTES) != value["recipe"]:
        raise ValueError("Build recipe differs from its frozen draft")
    result = parse_json(read_bytes(folder, "result.json", RESULT_BYTES), RESULT_BYTES)
    result_matches(value, result)
    for name, kind in (("preview.png", "preview"), ("thumbnail.webp", "thumbnail")):
        if name in present:
            module("pictures").validate_picture(read_bytes(folder, name, FILES[name]), kind)
    if "CREDITS.txt" in present and read_bytes(folder, "CREDITS.txt", FILES["CREDITS.txt"]) != module("credit").credits_text(value["attribution"]).encode("utf-8"):
        raise ValueError("Build credit differs from its frozen attribution")
    if "model.glb" in present:
        import struct
        from .protocol import validate_glb_metadata
        payload = read_bytes(folder, "model.glb", GLB_BYTES)
        if sha256(payload).hexdigest() != value["outputSha256"] or len(payload) != result["outputBytes"]:
            raise ValueError("Build GLB differs from its frozen result")
        size = struct.unpack_from("<I", payload, 12)[0]
        validate_glb_metadata(parse_json(payload[20:20+size], GLB_BYTES), result, payload=payload)
    return value


def public_result(folder, draft, *, offset=0, limit=64):
    result = parse_json(read_bytes(folder, "result.json", RESULT_BYTES), RESULT_BYTES)
    result_matches(draft, result)
    parts = result["parts"]
    if type(offset) is not int or not 0 <= offset <= len(parts) or type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError("Invalid build parts page")
    value = {"kind": "build", "draftId": draft["draftId"], "name": draft["recipe"]["name"],
             "dimensions": draft["catalogDimensions"], "triangles": draft["triangles"], "partsTotal": len(parts),
             "partsOffset": offset, "parts": deepcopy(parts[offset:offset+limit]), "nextPartsOffset": None,
             "warnings": result["warnings"], "lints": result["lints"], "attribution": draft["attribution"]}
    while True:
        end = offset+len(value["parts"])
        value["nextPartsOffset"] = end if end < len(parts) else None
        if len(json_bytes(value)) <= 48*1024:
            return value
        if len(value["parts"]) > 1:
            value["parts"].pop()
        elif value["lints"]:
            value["lints"].pop()
        else:
            raise ValueError("Build summary exceeds 48 KiB")
