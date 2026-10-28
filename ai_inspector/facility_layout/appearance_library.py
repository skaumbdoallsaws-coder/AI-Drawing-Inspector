"""Facility appearance, scene and decal libraries: manifests and saved-value rules.

Appearances are visual only. Nothing here reads or writes mass, density, strength or
an assigned engineering material, and no rule depends on a third-party service: the
manifests and their files ship under ``static/facility_library``.

Saved shapes
------------
``placement.appearance`` is either the legacy ``{"color": "#rrggbb"}`` or
``{"appearanceId": ..., <overrides>}`` where the overrides tune one library or
custom finish for that placement only.

``extensions.facilityAppearances`` holds custom finishes saved with the layout:
``{"version": 1, "custom": [{"appearanceId": "custom-...", "label": ...,
"baseAppearanceId": <library id>, <overrides>}]}``.

``extensions.facilityScene`` holds the viewport scene saved with the layout:
``{"version": 1, "sceneId": ..., "adjustments": {...}}``.

Precedence when rendering: a part (component) override beats the placement
appearance, which beats the asset's own finish. Selection highlights are never
saved.
"""
from collections.abc import Mapping
from functools import lru_cache
import json
import math
from pathlib import Path
import re

LIBRARY_ROOT = Path(__file__).resolve().parents[2] / "static" / "facility_library"
CUSTOM_KEY = "facilityAppearances"
SCENE_KEY = "facilityScene"
MAX_CUSTOM_APPEARANCES = 64

COLOR = re.compile(r"#[0-9a-fA-F]{6}")
LIBRARY_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
CUSTOM_ID = re.compile(r"custom-[a-z0-9][a-z0-9-]{0,56}")
MAPPINGS = ("box", "cylindrical", "uv")
GRAINS = ("part", "length", "width", "height")
OVERRIDE_FIELDS = frozenset({
    "color", "roughness", "metalness", "opacity", "textureStrength",
    "sizeMeters", "rotationDegrees", "offsetMeters", "mapping", "grain",
})
SCENE_ADJUSTMENTS = frozenset({
    "exposure", "environmentIntensity", "ambient", "directional",
    "background", "shadows", "environmentRotationDegrees",
})


@lru_cache(maxsize=4)
def load_library(root: str = str(LIBRARY_ROOT)) -> dict:
    """Read the three manifests once and index them by ID."""
    base = Path(root)
    documents = {}
    for name in ("appearances", "scenes", "decals"):
        value = json.loads((base / f"{name}.json").read_text(encoding="utf-8"))
        if not isinstance(value, Mapping) or value.get("schemaVersion") != 1:
            raise ValueError(f"Unsupported {name} library manifest")
        documents[name] = value
    appearances = {row["appearanceId"]: row for row in documents["appearances"]["appearances"]}
    texture_sets = {row["textureSetId"]: row for row in documents["appearances"]["textureSets"]}
    for row in appearances.values():
        texture = row.get("texture")
        if texture and texture["textureSetId"] not in texture_sets:
            raise ValueError(f"Appearance {row['appearanceId']} uses a missing texture set")
    return {
        "libraryVersion": documents["appearances"].get("libraryVersion"),
        "appearances": appearances,
        "categories": [row["categoryId"] for row in documents["appearances"]["categories"]],
        "textureSets": texture_sets,
        "scenes": {row["sceneId"]: row for row in documents["scenes"]["scenes"]},
        "environments": {row["environmentId"]: row for row in documents["scenes"]["environments"]},
        "decals": {row["decalId"]: row for row in documents["decals"]["decals"]},
        "documents": documents,
    }


def _number(value, name, low, high, places=4):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    rounded = round(float(value), places)
    return int(rounded) if rounded == int(rounded) else rounded


def _color(value, name="color"):
    if not isinstance(value, str) or not COLOR.fullmatch(value):
        raise ValueError(f"{name} must be a six-digit hex color")
    return value.lower()


def normalize_overrides(value: Mapping) -> dict:
    """Validate the per-use finish adjustments shared by placements, parts and custom finishes."""
    result = {}
    for key in sorted(set(value) & OVERRIDE_FIELDS):
        item = value[key]
        if key == "color":
            result[key] = _color(item)
        elif key in ("roughness", "metalness", "opacity", "textureStrength"):
            result[key] = _number(item, key, 0, 1)
        elif key == "sizeMeters":
            result[key] = _number(item, key, 0.01, 50)
        elif key == "rotationDegrees":
            result[key] = _number(item, key, -360, 360, 3)
        elif key == "offsetMeters":
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("offsetMeters needs two numbers")
            result[key] = [_number(part, key, -100, 100) for part in item]
        elif key == "mapping":
            if item not in MAPPINGS:
                raise ValueError("mapping must be box, cylindrical or uv")
            result[key] = item
        elif key == "grain":
            if item not in GRAINS:
                raise ValueError("grain must follow part, length, width or height")
            result[key] = item
    return result


def custom_appearances(layout) -> dict:
    """Custom finishes saved with a layout, by ID. Invalid documents yield nothing here."""
    extensions = layout.get("extensions") if isinstance(layout, Mapping) else None
    value = extensions.get(CUSTOM_KEY) if isinstance(extensions, Mapping) else None
    rows = value.get("custom") if isinstance(value, Mapping) else None
    return {row["appearanceId"]: row for row in rows or []
            if isinstance(row, Mapping) and isinstance(row.get("appearanceId"), str)}


def known_appearance(appearance_id, layout=None) -> bool:
    if not isinstance(appearance_id, str):
        return False
    if CUSTOM_ID.fullmatch(appearance_id):
        # Without a layout only the syntax can be checked; the save validation
        # repeats this with the layout's custom list.
        return layout is None or appearance_id in custom_appearances(layout)
    return LIBRARY_ID.fullmatch(appearance_id) is not None and appearance_id in load_library()["appearances"]


def normalize_appearance(value, layout=None) -> dict:
    """Validate one placement appearance: legacy color or a library/custom finish."""
    if not isinstance(value, Mapping):
        raise ValueError("Appearance must be an object")
    if "appearanceId" not in value:
        if set(value) != {"color"}:
            raise ValueError("A color appearance contains only color")
        return {"color": _color(value["color"])}
    unknown = set(value) - OVERRIDE_FIELDS - {"appearanceId"}
    if unknown:
        raise ValueError("Unsupported appearance fields: " + ", ".join(sorted(unknown)))
    appearance_id = value["appearanceId"]
    if not known_appearance(appearance_id, layout):
        raise ValueError(f"Unknown appearance '{appearance_id}'")
    return dict({"appearanceId": appearance_id}, **normalize_overrides(value))


def normalize_custom_appearances(value) -> dict:
    """Validate the layout's custom finish list. Custom finishes extend library finishes only."""
    if not isinstance(value, Mapping) or set(value) != {"version", "custom"} or value["version"] != 1 \
            or type(value["version"]) is not int:
        raise ValueError("Unsupported custom appearance document")
    rows = value["custom"]
    if not isinstance(rows, list) or len(rows) > MAX_CUSTOM_APPEARANCES:
        raise ValueError(f"Save at most {MAX_CUSTOM_APPEARANCES} custom appearances")
    library = load_library()["appearances"]
    result, ids = [], set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Unsupported custom appearance")
        unknown = set(row) - OVERRIDE_FIELDS - {"appearanceId", "label", "baseAppearanceId"}
        if unknown or not {"appearanceId", "label", "baseAppearanceId"} <= set(row):
            raise ValueError("A custom appearance needs appearanceId, label and baseAppearanceId")
        identifier = row["appearanceId"]
        if not isinstance(identifier, str) or not CUSTOM_ID.fullmatch(identifier) or identifier in ids:
            raise ValueError("Each custom appearance needs a unique custom- ID")
        ids.add(identifier)
        label = row["label"]
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 80:
            raise ValueError("A custom appearance name needs 1 to 80 characters")
        if row["baseAppearanceId"] not in library:
            raise ValueError("A custom appearance must start from a library appearance")
        result.append(dict({"appearanceId": identifier, "label": label.strip(),
                            "baseAppearanceId": row["baseAppearanceId"]}, **normalize_overrides(row)))
    return {"version": 1, "custom": result}


def normalize_scene(value) -> dict:
    if not isinstance(value, Mapping) or not {"version", "sceneId"} <= set(value) \
            or set(value) - {"version", "sceneId", "adjustments"}:
        raise ValueError("Unsupported scene document")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported scene version")
    if value["sceneId"] not in load_library()["scenes"]:
        raise ValueError(f"Unknown scene '{value['sceneId']}'")
    result = {"version": 1, "sceneId": value["sceneId"]}
    adjustments = value.get("adjustments")
    if adjustments is None:
        return result
    if not isinstance(adjustments, Mapping) or set(adjustments) - SCENE_ADJUSTMENTS:
        raise ValueError("Unsupported scene adjustments")
    normalized = {}
    for key in sorted(adjustments):
        item = adjustments[key]
        if key == "background":
            if item not in ("theme", "environment") and not (isinstance(item, str) and COLOR.fullmatch(item)):
                raise ValueError("Scene background must be theme, environment or a hex color")
            normalized[key] = item.lower()
        elif key == "shadows":
            if type(item) is not bool:
                raise ValueError("Scene shadows must be true or false")
            normalized[key] = item
        elif key == "environmentRotationDegrees":
            normalized[key] = _number(item, key, -360, 360, 3)
        else:
            normalized[key] = _number(item, key, 0, 5)
    if normalized:
        result["adjustments"] = normalized
    return result


def validate_layout_references(layout) -> None:
    """Every appearance a layout uses must exist in the library or the layout's custom list."""
    for placement in layout.get("placements", []) if isinstance(layout, Mapping) else []:
        appearance = placement.get("appearance") if isinstance(placement, Mapping) else None
        if isinstance(appearance, Mapping) and "appearanceId" in appearance:
            identifier = appearance["appearanceId"]
            if not known_appearance(identifier, layout):
                raise ValueError(f"Placement {placement.get('placementId')} uses unknown appearance '{identifier}'")
        materials = placement.get("componentMaterials") if isinstance(placement, Mapping) else None
        for row in materials.get("overrides", []) if isinstance(materials, Mapping) else []:
            identifier = row.get("appearanceId") if isinstance(row, Mapping) else None
            if identifier is not None and not known_appearance(identifier, layout):
                raise ValueError(f"Placement {placement.get('placementId')} part uses unknown appearance '{identifier}'")


def library_summary(kind="appearances", query="", category=None, limit=60) -> list:
    """Compact rows for agents: what can be applied, without file paths or provenance."""
    library = load_library()
    words = [word for word in re.split(r"\s+", (query or "").lower()) if word]
    if kind == "scenes":
        rows = [{"sceneId": row["sceneId"], "label": row["label"], "group": row["group"],
                 "description": row["description"], "shadows": row["shadows"]}
                for row in library["scenes"].values()]
    elif kind == "decals":
        rows = [{"decalId": row["decalId"], "label": row["label"], "code": row["code"], "group": row["group"]}
                for row in library["decals"].values()]
    else:
        rows = [{"appearanceId": row["appearanceId"], "label": row["label"], "category": row["category"],
                 "textured": bool(row.get("texture")), "color": row["color"], "roughness": row["roughness"],
                 "metalness": row["metalness"], "tags": row.get("tags", [])}
                for row in library["appearances"].values()
                if category is None or row["category"] == category]

    def matches(row):
        text = json.dumps(row).lower()
        return all(word in text for word in words)
    return [row for row in rows if matches(row)][:max(1, min(200, int(limit)))]
