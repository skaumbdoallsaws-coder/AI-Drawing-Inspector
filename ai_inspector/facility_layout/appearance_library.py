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

Lights: a library appearance may carry ``emission`` (``{"color", "intensity"}``),
the glow the Facility 3D view draws on top of its unlit ``color``. A ``color``
override on such a finish recolors the light: the glow takes the color and the
unlit lens the same color at half brightness, so a blinking lamp's dark step and
a switched-off lamp keep its color. Only the Facility view draws a glow, so the
Assembly tools leave these finishes out. An emission may also carry
``"pattern"`` (steady, blink, strobe, rotate or cycle) with ``"periodSeconds"``
(0.5 to 10 s per cycle; 2 to 60 s per color loop for cycle): the Facility view then
blinks it, steady under reduced motion. A cycle light eases its glow through
``"cycleColors"`` (2 to 8 colors, DEFAULT_CYCLE_COLORS without them), one loop per
period, its unlit lens following at half brightness; steady (the first color) under
reduced motion. A use of a Lights finish (a placement, a part or a custom finish)
may set its own ``pattern``, ``periodSeconds`` and ``cycleColors`` the same way, e.g.
a red stack lamp that blinks.
An outdoor light's emission may carry ``"beamAngleDegrees"`` (10 to 160): in the
evening scene the Facility view then draws a soft beam from the lamp down to the
ground and a pool of light where its aim lands (docs/facility-lighting-plan.md, L8).
With ``"accent": true`` as well (an accent spot) the view instead lights what the
beam reaches (a wall, an object, the floor) with a spot light, and draws no pool.
A general, outdoor or accent Lights finish may carry ``estimate`` (``{"lumens", "beamAngleDegrees", "basis"}``): a
typical output and beam angle, for the lighting coverage estimate only (light_coverage.py, CC).
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
    "pattern", "periodSeconds", "cycleColors",
})
# Overrides that only a Lights finish (one with an emission) takes.
LIGHT_OVERRIDES = ("pattern", "periodSeconds", "cycleColors")
SCENE_ADJUSTMENTS = frozenset({
    "exposure", "environmentIntensity", "ambient", "directional",
    "background", "shadows", "environmentRotationDegrees", "lights", "lightAreas", "glowHalo",
})
# General lights by area (docs/facility-lighting-plan.md, L7): on only inside the areas, or everywhere except.
LIGHT_AREA_MODES = ("only", "except")
MAX_LIGHT_AREAS = 64
FLOOR_AREA_ID = re.compile(r"fs-[a-z0-9-]{1,76}")
RECTANGLE_KEYS = ("minX", "minZ", "maxX", "maxZ")


GLOW_PATTERNS = ("steady", "blink", "strobe", "rotate", "cycle")
# A cycle light (2026-11-02, accent lighting) eases through its colors, one loop per period: slow ambient loops, so a
# longer period than a blink. Without cycleColors the Facility view uses this palette, chosen for a dark evening
# scene: violet, blue, cyan, magenta (static/facility_layout_finishes.js keeps the same list).
DEFAULT_CYCLE_COLORS = ("#8a4dff", "#2f6bff", "#00d5ff", "#ff3dce")
MIN_CYCLE_COLORS, MAX_CYCLE_COLORS = 2, 8


def _period_range(pattern):
    """Seconds per cycle a pattern takes: 0.5 to 10 for blink, strobe and rotate, 2 to 60 per color loop for cycle."""
    return (2, 60) if pattern == "cycle" else (0.5, 10)


def _valid_cycle_colors(colors):
    return (isinstance(colors, list) and MIN_CYCLE_COLORS <= len(colors) <= MAX_CYCLE_COLORS
            and all(isinstance(color, str) and COLOR.fullmatch(color) for color in colors))


def _finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _valid_emission(emission):
    """A glow: color and intensity, optionally a pattern with its period, and an outdoor light's beam angle
    (docs/facility-lighting-plan.md)."""
    if not isinstance(emission, Mapping) or not (
            {"color", "intensity"} <= set(emission)
            <= {"color", "intensity", "pattern", "periodSeconds", "cycleColors", "beamAngleDegrees", "accent"}):
        return False
    if "accent" in emission and not (emission["accent"] is True and "beamAngleDegrees" in emission):
        return False
    if "beamAngleDegrees" in emission and not (
            _finite_number(emission["beamAngleDegrees"]) and 10 <= emission["beamAngleDegrees"] <= 160):
        return False
    if not (isinstance(emission["color"], str) and COLOR.fullmatch(emission["color"])):
        return False
    if not (_finite_number(emission["intensity"]) and 0 < emission["intensity"] <= 4):
        return False
    pattern = emission.get("pattern", "steady")
    if pattern not in GLOW_PATTERNS:
        return False
    if "cycleColors" in emission and not (pattern == "cycle" and _valid_cycle_colors(emission["cycleColors"])):
        return False
    if pattern == "steady":
        return "periodSeconds" not in emission
    low, high = _period_range(pattern)
    return _finite_number(emission.get("periodSeconds")) and low <= emission["periodSeconds"] <= high


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
        emission = row.get("emission")
        if emission is not None and not _valid_emission(emission):
            raise ValueError(f"Appearance {row['appearanceId']} has an invalid emission")
        if "estimate" in row and not (emission and _valid_estimate(row["estimate"])):
            raise ValueError(f"Appearance {row['appearanceId']} has an invalid estimate")
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


def _valid_estimate(estimate):
    """A light's typical output (1 to 200000 lm) and beam angle (10 to 170 degrees), for estimates only."""
    return (isinstance(estimate, Mapping) and set(estimate) == {"lumens", "beamAngleDegrees", "basis"}
            and _finite_number(estimate["lumens"]) and 1 <= estimate["lumens"] <= 200000
            and _finite_number(estimate["beamAngleDegrees"]) and 10 <= estimate["beamAngleDegrees"] <= 170
            and estimate["basis"] == "typical, for estimates")


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
        elif key == "pattern":
            if item not in GLOW_PATTERNS:
                raise ValueError("pattern must be steady, blink, strobe, rotate or cycle")
            result[key] = item
        elif key == "periodSeconds":
            # "pattern" sorts first, so it is checked by now: a cycle takes a longer period.
            result[key] = _number(item, key, *_period_range(value.get("pattern")), 3)
        elif key == "cycleColors":
            if not (isinstance(item, list) and MIN_CYCLE_COLORS <= len(item) <= MAX_CYCLE_COLORS):
                raise ValueError(f"cycleColors takes {MIN_CYCLE_COLORS} to {MAX_CYCLE_COLORS} colors")
            result[key] = [_color(color, "Each cycleColors entry") for color in item]
    # As in the library: a steady light has no period; blink, strobe, rotate and cycle need one.
    if "periodSeconds" in result and "pattern" not in result:
        raise ValueError("periodSeconds goes with a pattern (blink, strobe, rotate or cycle)")
    if result.get("pattern") == "steady" and "periodSeconds" in result:
        raise ValueError("A steady light has no periodSeconds")
    if result.get("pattern", "steady") != "steady" and "periodSeconds" not in result:
        low, high = _period_range(result["pattern"])
        unit = "s per color loop" if result["pattern"] == "cycle" else "s per cycle"
        raise ValueError(f"A {result['pattern']} light needs periodSeconds ({low:g} to {high:g} {unit})")
    if "cycleColors" in result and result.get("pattern") != "cycle":
        raise ValueError("cycleColors goes with pattern cycle")
    return result


def _lights_only(overrides, base_row):
    """pattern, periodSeconds and cycleColors belong to a light: refuse them on a finish without a glow."""
    if any(key in overrides for key in LIGHT_OVERRIDES) and not (base_row and base_row.get("emission")):
        raise ValueError("pattern, periodSeconds and cycleColors go only on a Lights finish (one that glows)")


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
    overrides = normalize_overrides(value)
    library = load_library()["appearances"]
    if appearance_id in library:
        _lights_only(overrides, library[appearance_id])
    elif layout is not None:
        custom = custom_appearances(layout).get(appearance_id) or {}
        _lights_only(overrides, library.get(custom.get("baseAppearanceId")))
    return dict({"appearanceId": appearance_id}, **overrides)


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
        overrides = normalize_overrides(row)
        _lights_only(overrides, library[row["baseAppearanceId"]])
        result.append(dict({"appearanceId": identifier, "label": label.strip(),
                            "baseAppearanceId": row["baseAppearanceId"]}, **overrides))
    return {"version": 1, "custom": result}


def _light_areas(value) -> dict:
    """General lighting on only inside the areas (mode only) or everywhere except inside them (mode except).

    An area is a floor area ({surfaceId}) or a rectangle on the plan ({rectangle: {minX, minZ, maxX, maxZ}},
    metres). Exit signs, beacons and other lights that throw no floor pool stay on either way."""
    if not isinstance(value, Mapping) or set(value) != {"mode", "areas"}:
        raise ValueError("Scene lightAreas needs mode and areas")
    if value["mode"] not in LIGHT_AREA_MODES:
        raise ValueError("Scene lightAreas mode must be only or except")
    areas = value["areas"]
    if not isinstance(areas, list) or len(areas) > MAX_LIGHT_AREAS:
        raise ValueError(f"Scene lightAreas takes a list of at most {MAX_LIGHT_AREAS} areas")
    result, seen = [], set()
    for area in areas:
        if isinstance(area, Mapping) and set(area) == {"surfaceId"}:
            if not isinstance(area["surfaceId"], str) or not FLOOR_AREA_ID.fullmatch(area["surfaceId"]):
                raise ValueError("A light area's surfaceId must be a floor area id (fs-...)")
            row, key = {"surfaceId": area["surfaceId"]}, area["surfaceId"]
        elif isinstance(area, Mapping) and set(area) == {"rectangle"}:
            rectangle = area["rectangle"]
            if not isinstance(rectangle, Mapping) or set(rectangle) != set(RECTANGLE_KEYS):
                raise ValueError("A light area rectangle needs minX, minZ, maxX and maxZ")
            box = {k: _number(rectangle[k], "Light area " + k, -10000, 10000, 3) for k in RECTANGLE_KEYS}
            if box["maxX"] - box["minX"] < 0.1 or box["maxZ"] - box["minZ"] < 0.1:
                raise ValueError("A light area rectangle must be at least 0.1 m across each way")
            row, key = {"rectangle": box}, tuple(box[k] for k in RECTANGLE_KEYS)
        else:
            raise ValueError("A light area is a floor area (surfaceId) or a rectangle")
        if key in seen:
            raise ValueError("List each light area once")
        seen.add(key)
        result.append(row)
    return {"mode": value["mode"], "areas": result}


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
        elif key in ("shadows", "lights", "glowHalo"):
            if type(item) is not bool:
                raise ValueError(f"Scene {key} must be true or false")
            normalized[key] = item
        elif key == "environmentRotationDegrees":
            normalized[key] = _number(item, key, -360, 360, 3)
        elif key == "lightAreas":
            normalized[key] = _light_areas(item)
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


def library_summary(kind="appearances", query="", category=None, limit=60, glow=None) -> list:
    """Compact rows for agents: what can be applied, without file paths or provenance.

    ``glow`` filters appearances: None lists all, False only those without an emission (the Assembly view
    draws no glow), True only the glowing ones."""
    library = load_library()
    words = [word for word in re.split(r"\s+", (query or "").lower()) if word]
    if kind == "scenes":
        # lightPools: the scene shows floor light pools and can take the glow halo (lighting L3 and L6).
        rows = [dict({"sceneId": row["sceneId"], "label": row["label"], "group": row["group"],
                      "description": row["description"], "shadows": row["shadows"]},
                     **({"lightPools": True} if row.get("lightPools") else {}))
                for row in library["scenes"].values()]
    elif kind == "decals":
        rows = [{"decalId": row["decalId"], "label": row["label"], "code": row["code"], "group": row["group"]}
                for row in library["decals"].values()]
    else:
        rows = [dict({"appearanceId": row["appearanceId"], "label": row["label"], "category": row["category"],
                      "textured": bool(row.get("texture")), "color": row["color"], "roughness": row["roughness"],
                      "metalness": row["metalness"], "tags": row.get("tags", [])},
                     **({"emission": dict(row["emission"])} if row.get("emission") else {}))
                for row in library["appearances"].values()
                if (category is None or row["category"] == category)
                and (glow is None or bool(row.get("emission")) == glow)]

    def matches(row):
        text = json.dumps(row).lower()
        return all(word in text for word in words)
    return [row for row in rows if matches(row)][:max(1, min(200, int(limit)))]
