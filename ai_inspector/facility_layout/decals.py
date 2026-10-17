"""Wall-bound visual decals, independent of wall paint or perimeter generation."""
from collections.abc import Mapping
from copy import deepcopy
import math
import re

KEY = "facilityDecals"
MAX_DECALS = 48
IMAGE_PATH = re.compile(r"/api/facility-decal-images/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/[a-f0-9]{64}\.png")
LEGACY_IMAGE_PATH = re.compile(r"/generated/facility-wall-art/[a-f0-9]{64}\.png")


def normalize_lettering(value):
    if not isinstance(value, Mapping) or set(value) != {"text", "reference", "font", "align", "color"}:
        raise ValueError("Unsupported lettering settings")
    for key, limit in (("text", 1000), ("reference", 160)):
        text = value[key]
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 and c != "\n" for c in text):
            raise ValueError("Invalid lettering text")
    if not value["text"].strip() or value["text"].count("\n") > 15:
        raise ValueError("Lettering needs text with at most 16 lines")
    if value["font"] not in ("Arial", "Georgia") or value["align"] not in ("left", "center", "right"):
        raise ValueError("Unsupported lettering font or alignment")
    if not isinstance(value["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value["color"]):
        raise ValueError("Lettering needs a six-digit color")
    return dict(value, text=value["text"].strip(), reference=value["reference"].strip(), color=value["color"].lower())


def normalize_decals(value, layout):
    from .perimeter_walls import _number
    from .plan_settings import plan_settings_from_layout

    if not isinstance(value, Mapping) or set(value) != {"version", "artworks"} or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported decal document")
    records = value["artworks"]
    if not isinstance(records, list) or len(records) > MAX_DECALS:
        raise ValueError(f"Decals must contain at most {MAX_DECALS} images")
    extensions = layout.get("extensions", {})
    settings = extensions.get("facilityPerimeterWalls", {}).get("settings", {})
    finish = settings.get("exteriorFinish", {})
    existing = finish.get("artworks", []) + finish.get("fittedArtworks", [])
    ids = {item["artworkId"] for item in existing}
    if len(existing) + len(records) > MAX_DECALS:
        raise ValueError(f"Combined wall artwork exceeds the {MAX_DECALS}-image budget")
    placements = {p["placementId"] for p in layout.get("placements", [])}
    plan = plan_settings_from_layout(layout)
    points = [] if not settings else settings.get("boundary") if settings.get("boundarySource") == "polygon" else [
        {"x": 0, "z": 0}, {"x": plan["widthMeters"], "z": 0},
        {"x": plan["widthMeters"], "z": plan["depthMeters"]}, {"x": 0, "z": plan["depthMeters"]}]
    result = []
    for record in records:
        fields = {"artworkId", "label", "imagePath", "uv", "target", "region", "coverage"}
        if not isinstance(record, Mapping) or set(record) not in (fields, fields | {"lettering"}):
            raise ValueError("Unsupported decal fields")
        identifier = record["artworkId"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", identifier) or identifier in ids:
            raise ValueError("Each decal needs a unique stable ID")
        ids.add(identifier)
        label = record["label"]
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError("Decal name must contain 1 to 120 characters")
        path = record["imagePath"]
        if not isinstance(path, str) or not (IMAGE_PATH.fullmatch(path) or LEGACY_IMAGE_PATH.fullmatch(path)):
            raise ValueError("Decals must reference an imported content-addressed image")
        if IMAGE_PATH.fullmatch(path) and path.split("/")[3] != layout["association"]["siteId"]:
            raise ValueError("Decal image belongs to another site")
        item = deepcopy(dict(record))
        if "lettering" in item:
            item["lettering"] = normalize_lettering(item["lettering"])
        item["label"] = label.strip()
        item["coverage"] = _number(item["coverage"], "coverage", .95, 1)
        for key in ("uv", "region"):
            values = item[key]
            if not isinstance(values, list) or len(values) != 4:
                raise ValueError(f"Decal {key} needs four fractions")
            values = [_number(v, key, 0, 1) for v in values]
            if values[2] - values[0] < .001 or values[3] - values[1] < .001:
                raise ValueError(f"Empty decal {key}")
            item[key] = values
        target = item["target"]
        if not isinstance(target, Mapping):
            raise ValueError("Decal needs a wall target")
        if set(target) == {"edge", "side"}:
            edge = target["edge"]
            if not settings or type(edge) is not int or not 0 <= edge < len(points) or target["side"] not in ("interior", "exterior"):
                raise ValueError("Decal perimeter wall is missing")
            a, b = points[edge], points[(edge + 1) % len(points)]
            length = math.hypot(b["x"] - a["x"], b["z"] - a["z"])
            start, end = (item["region"][i] * length for i in (0, 2))
            if any(o["edge"] == edge and start < o["endMeters"] - 1e-6 and end > o["startMeters"] + 1e-6 for o in settings["openings"]):
                raise ValueError("Decal would cover a door opening")
        elif set(target) == {"wallId", "side"}:
            interior = next((w for w in extensions.get("facilityInteriorWalls", {}).get("walls", []) if w["wallId"] == target["wallId"]), None)
            if not interior or target["side"] not in ("left", "right"):
                raise ValueError("Interior decal wall is missing")
            length = math.hypot(interior["end"]["x"]-interior["start"]["x"], interior["end"]["z"]-interior["start"]["z"])
            start, end = (item["region"][i]*length for i in (0,2))
            if any(start < o["endMeters"]-1e-6 and end > o["startMeters"]+1e-6 for o in interior["openings"]):
                raise ValueError("Decal would cover an interior wall opening")
        elif set(target) == {"placementId", "face"}:
            if not isinstance(target["placementId"], str) or target["placementId"] not in placements:
                raise ValueError("Decal wall placement is missing")
            if target["face"] not in ("positive_x", "negative_x", "positive_z", "negative_z"):
                raise ValueError("Unsupported decal wall face")
        else:
            raise ValueError("Unsupported decal target")
        result.append(item)
    return {"version": 1, "artworks": result}


def remove_bound_decals(document, predicate):
    extension = document.get("extensions", {}).get(KEY)
    if extension:
        extension["artworks"] = [art for art in extension["artworks"] if not predicate(art["target"])]
