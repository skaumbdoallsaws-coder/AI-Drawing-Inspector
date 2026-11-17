"""Trusted cookbook and installed built-recipe reads for the Sage host hooks."""
from hashlib import sha256
import math
from pathlib import Path
import re

from . import model_import_files as disk
from .errors import FacilityLayoutError
from ..industrial_assets.model_builder.errors import json_bytes, parse_json
from ..industrial_assets.model_builder.recipe import RECIPE_BYTES, normalize_recipe, portable_recipe
from ..industrial_assets.model_builder_bundle import FOLDER

DEFAULT_COOKBOOK = Path(__file__).resolve().parents[1] / "industrial_assets" / "model_builder" / "cookbook"
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def _bounded_bytes(path, limit):
    path = disk.safe(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Model recipe file exceeds its limit")
    with path.open("rb") as stream:
        payload = stream.read(limit+1)
    if len(payload) > limit:
        raise ValueError("Model recipe file exceeds its limit")
    return payload


def cookbook_index(root=DEFAULT_COOKBOOK):
    path = disk.safe(Path(root) / "index.json")
    try:
        raw = _bounded_bytes(path, RECIPE_BYTES)
        value = parse_json(raw, RECIPE_BYTES)
        if (type(value) is not dict or set(value) != {"schemaVersion", "recipes"}
                or value["schemaVersion"] != 1 or type(value["recipes"]) is not list
                or len(value["recipes"]) > 20):
            raise ValueError("Invalid cookbook index")
        seen = set()
        for entry in value["recipes"]:
            if (type(entry) is not dict or set(entry) != {"id", "name", "size", "teaches"}
                    or type(entry["id"]) is not str or not ID.fullmatch(entry["id"])
                    or entry["id"] in seen or type(entry["name"]) is not str
                    or not 0 < len(entry["name"]) <= 80 or type(entry["teaches"]) is not str
                    or not 0 < len(entry["teaches"]) <= 120 or type(entry["size"]) is not dict
                    or set(entry["size"]) != {"width", "depth", "height"}
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not .0005 <= v <= 30
                           for v in entry["size"].values())):
                raise ValueError("Invalid cookbook entry")
            seen.add(entry["id"])
        return value["recipes"]
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        raise FacilityLayoutError("model_cookbook_invalid", "The bundled model cookbook is unavailable.",
                                  status_code=503) from error


def cookbook_recipe(root, cookbook_id, *, categories, appearance_ids):
    entries = cookbook_index(root)
    entry = next((item for item in entries if item["id"] == cookbook_id), None)
    if entry is None:
        raise FacilityLayoutError("model_recipe_missing", "That cookbook recipe is unavailable.", status_code=404)
    try:
        payload = _bounded_bytes(Path(root) / (cookbook_id + ".json"), RECIPE_BYTES)
        raw = parse_json(payload, RECIPE_BYTES)
        recipe = normalize_recipe(raw, allowed_categories=categories,
                                  allowed_appearance_ids=appearance_ids)
        if (recipe["name"] != entry["name"] or recipe["size"] != entry["size"]
                or len(json_bytes(recipe)) > RECIPE_BYTES):
            raise ValueError("Cookbook recipe differs from its index")
        return recipe
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        raise FacilityLayoutError("model_cookbook_invalid", "The bundled model recipe is invalid.",
                                  status_code=503) from error


def built_record(rows, asset_id, revision=None):
    record = next((row for row in rows if row.get("assetId") == asset_id), None)
    if (record is None or not isinstance(asset_id, str) or not asset_id.startswith("asset-built-")
            or not isinstance(record.get("buildProvenance"), dict)):
        raise FacilityLayoutError("model_recipe_missing", "That built asset is unavailable.", status_code=404)
    current = record.get("assetDefinitionRevision")
    if revision is not None and revision != current:
        raise FacilityLayoutError("model_recipe_mismatch", "The built asset revision changed.", status_code=409)
    return record


def installed_recipe(root, record, *, categories, appearance_ids):
    asset_id = record["assetId"]
    if not re.fullmatch(r"asset-built-[a-z0-9-]{1,40}-[0-9a-f]{24}", asset_id):
        raise FacilityLayoutError("model_recipe_missing", "That built asset is unavailable.", status_code=404)
    folder = disk.safe(Path(root) / FOLDER / asset_id)
    try:
        payload = _bounded_bytes(folder / "recipe.json", RECIPE_BYTES)
        manifest = parse_json(_bounded_bytes(folder / "bundle.json", 1024*1024), 1024*1024)
        expected = manifest["files"]["recipe.json"]
        if (not 0 < len(payload) <= RECIPE_BYTES or expected != {"sha256": sha256(payload).hexdigest(),
                                                                "bytes": len(payload)}):
            raise ValueError("Installed recipe hash differs")
        raw = parse_json(payload, RECIPE_BYTES)
        legacy_finishes = [material["finish"]["appearanceId"] for material in raw.get("materials", {}).values()
                           if isinstance(material, dict) and isinstance(material.get("finish"), dict)
                           and isinstance(material["finish"].get("appearanceId"), str)]
        recipe = normalize_recipe(raw, allowed_categories=None,
                                  allowed_appearance_ids=set(appearance_ids) | set(legacy_finishes))
        portable, _ = portable_recipe(recipe)
        if (json_bytes(portable) != payload or
                record["buildProvenance"]["recipeSha256"] != sha256(payload).hexdigest()):
            raise ValueError("Installed recipe differs from its catalog")
        return recipe
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        raise FacilityLayoutError("model_recipe_invalid", "The installed built recipe failed its integrity check.",
                                  status_code=503) from error
