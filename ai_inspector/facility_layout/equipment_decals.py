"""Decals projected onto equipment surfaces, bound to one placement.

A decal records where it sits in the placement's own (unscaled, unrotated)
coordinates: an anchor point on the surface, the surface normal there and a
rotation about that normal. The renderer projects the image onto whatever
geometry lies under that anchor, so the decal follows the placement when it
moves. Replacing or deleting the placement removes its decals; geometry-bound
finishes do not survive a model change.
"""
from collections.abc import Mapping
import math
import re

from .decals import IMAGE_PATH, LEGACY_IMAGE_PATH

KEY = "facilityEquipmentDecals"
MAX_EQUIPMENT_DECALS = 64
DECAL_ID = re.compile(r"edecal-[a-z0-9-]{1,80}")
FIELDS = {"decalId", "label", "imagePath", "placementId", "anchor", "widthMeters", "heightMeters"}
OPTIONAL = {"libraryDecalId"}


def _number(value, name, low, high, places=5):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    rounded = round(float(value), places)
    return int(rounded) if rounded == int(rounded) else rounded


def _vector(value, name, low, high):
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "z"}:
        raise ValueError(f"{name} needs x, y and z")
    return {axis: _number(value[axis], f"{name}.{axis}", low, high) for axis in ("x", "y", "z")}


def normalize_equipment_decals(value, layout) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"version", "decals"} \
            or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported equipment decal document")
    rows = value["decals"]
    if not isinstance(rows, list) or len(rows) > MAX_EQUIPMENT_DECALS:
        raise ValueError(f"A layout holds at most {MAX_EQUIPMENT_DECALS} equipment decals")
    placements = {p.get("placementId") for p in layout.get("placements", []) if isinstance(p, Mapping)}
    site = layout.get("association", {}).get("siteId") if isinstance(layout.get("association"), Mapping) else None
    from .appearance_library import load_library
    library_decals = load_library()["decals"]
    result, ids = [], set()
    for row in rows:
        if not isinstance(row, Mapping) or not FIELDS <= set(row) or set(row) - FIELDS - OPTIONAL:
            raise ValueError("Unsupported equipment decal fields")
        identifier = row["decalId"]
        if not isinstance(identifier, str) or not DECAL_ID.fullmatch(identifier) or identifier in ids:
            raise ValueError("Each equipment decal needs a unique edecal- ID")
        ids.add(identifier)
        label = row["label"]
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 120:
            raise ValueError("Decal name must contain 1 to 120 characters")
        path = row["imagePath"]
        if not isinstance(path, str) or not (IMAGE_PATH.fullmatch(path) or LEGACY_IMAGE_PATH.fullmatch(path)):
            raise ValueError("Decals must reference an imported content-addressed image")
        if IMAGE_PATH.fullmatch(path) and site is not None and path.split("/")[3] != site:
            raise ValueError("Decal image belongs to another site")
        if row["placementId"] not in placements:
            raise ValueError("Decal placement is missing")
        anchor = row["anchor"]
        if not isinstance(anchor, Mapping) or set(anchor) != {"position", "normal", "rotationDegrees"}:
            raise ValueError("Decal anchor needs position, normal and rotationDegrees")
        position = _vector(anchor["position"], "anchor.position", -1000, 1000)
        normal = _vector(anchor["normal"], "anchor.normal", -10, 10)
        length = math.sqrt(sum(normal[axis] ** 2 for axis in "xyz"))
        if length < 1e-6:
            raise ValueError("Decal normal must not be zero")
        normal = {axis: round(normal[axis] / length, 6) for axis in "xyz"}
        item = {
            "decalId": identifier, "label": label.strip(), "imagePath": path, "placementId": row["placementId"],
            "anchor": {"position": position, "normal": normal,
                       "rotationDegrees": _number(anchor["rotationDegrees"], "anchor.rotationDegrees", -360, 360, 3)},
            "widthMeters": _number(row["widthMeters"], "widthMeters", 0.02, 10),
            "heightMeters": _number(row["heightMeters"], "heightMeters", 0.02, 10),
        }
        if "libraryDecalId" in row:
            if row["libraryDecalId"] not in library_decals:
                raise ValueError("Unknown library decal")
            item["libraryDecalId"] = row["libraryDecalId"]
        result.append(item)
    return {"version": 1, "decals": result}


def remove_equipment_decals(document, placement_id) -> None:
    extension = document.get("extensions", {}).get(KEY)
    if isinstance(extension, Mapping) and isinstance(extension.get("decals"), list):
        extension["decals"] = [row for row in extension["decals"] if row.get("placementId") != placement_id]
