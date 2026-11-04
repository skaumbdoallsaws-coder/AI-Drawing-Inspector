"""Floor-plan import, the layout side (docs/facility-floor-plan-import-plan.md, section 4, "Layout extension").

`extensions.facilityFloorPlanReferences` keeps an imported drawing as a Plan view underlay: which stored import it
shows (its import id, and the digests of its source and geometry), how the drawing sits on the layout (its alignment), which layers
show and what the user says each layer is, and how strongly it is drawn. The drawing itself never enters the layout:
it lives in the site's floor-plan store (floor_plan_store.py), so the 5 MiB extension budget is not spent on it.

One reference per layout at first; the list leaves room for more. The record is closed: the normalizer rejects
unknown fields and returns the one stored form (idempotent), and validation requires the stored form.
"""
from __future__ import annotations

import math
import re
from hashlib import sha256

from .floor_plan_alignment import normalize_alignment

KEY = "facilityFloorPlanReferences"
VERSION = 1
MAX_REFERENCES = 1
MAX_LAYERS = 512
# What a layer is, in the user's words; the conversion phases read these. "reference" just shows it.
ROLES = ("reference", "wall_centerline", "wall_faces", "perimeter", "room_boundary", "column", "door", "text",
         "ignore")
MIN_OPACITY, MAX_OPACITY = 0.05, 1.0
REFERENCE_ID = re.compile(r"fp-[a-z0-9-]{1,60}")
DIGEST = re.compile(r"[a-f0-9]{64}")
LAYER_ID = re.compile(r"L(0|[1-9][0-9]{0,3})")
PARSER_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}")
_FIELDS = {"referenceId", "label", "sourceName", "importId", "sourceSha256", "geometrySha256", "parserVersion",
           "alignment", "layers", "opacity", "showIn3D"}
_REQUIRED = _FIELDS - {"sourceName"}


def import_id_for(source_sha256: str, parser_version: str) -> str:
    """The store's name for the import of one source file by one reader version: the same file read by the same
    reader is the same import, so importing it again finds it instead of reading it again."""
    return "fpi-" + sha256(f"{source_sha256}\0{parser_version}".encode("ascii")).hexdigest()[:32]


def clean_label(value, name: str, maximum: int = 120) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    text = " ".join("".join(c for c in value if c.isprintable() or c.isspace()).split())
    if not 1 <= len(text) <= maximum:
        raise ValueError(f"{name} must be 1 to {maximum} characters.")
    return text


def _layers(value) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_LAYERS:
        raise ValueError(f"layers must be a list of at most {MAX_LAYERS} layers.")
    rows = {}
    for index, layer in enumerate(value):
        if not isinstance(layer, dict) or set(layer) != {"layerId", "visible", "role"}:
            raise ValueError(f"layers[{index}] must have exactly layerId, visible and role.")
        layer_id = layer["layerId"]
        if not isinstance(layer_id, str) or not LAYER_ID.fullmatch(layer_id):
            raise ValueError(f"layers[{index}].layerId must be a drawing layer id such as L3.")
        if layer_id in rows:
            raise ValueError(f"Layer {layer_id} is listed twice.")
        if not isinstance(layer["visible"], bool):
            raise ValueError(f"layers[{index}].visible must be true or false.")
        if layer["role"] not in ROLES:
            raise ValueError(f"layers[{index}].role must be one of " + ", ".join(ROLES) + ".")
        rows[layer_id] = {"layerId": layer_id, "visible": layer["visible"], "role": layer["role"]}
    return [rows[key] for key in sorted(rows, key=lambda key: int(key[1:]))]


def normalize_reference(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("A floor-plan reference must be an object.")
    keys = set(value)
    if not _REQUIRED <= keys or not keys <= _FIELDS:
        missing, extra = sorted(_REQUIRED - keys), sorted(keys - _FIELDS)
        raise ValueError("A floor-plan reference " + "; ".join(
            part for part in (("needs " + ", ".join(missing)) if missing else "",
                              ("cannot have " + ", ".join(extra)) if extra else "") if part) + ".")
    reference_id = value["referenceId"]
    if not isinstance(reference_id, str) or not REFERENCE_ID.fullmatch(reference_id):
        raise ValueError("referenceId must look like fp-<lowercase letters, digits and dashes>.")
    for field in ("sourceSha256", "geometrySha256"):
        if not isinstance(value[field], str) or not DIGEST.fullmatch(value[field]):
            raise ValueError(f"{field} must be a SHA-256 digest (64 lowercase hex digits).")
    parser = value["parserVersion"]
    if not isinstance(parser, str) or not PARSER_VERSION.fullmatch(parser):
        raise ValueError("parserVersion must be a short version name such as ezdxf-1.4.5+a1.")
    if value["importId"] != import_id_for(value["sourceSha256"], parser):
        raise ValueError("importId must be the import of sourceSha256 by parserVersion.")
    opacity = value["opacity"]
    if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not math.isfinite(opacity) \
            or not MIN_OPACITY <= opacity <= MAX_OPACITY:
        raise ValueError(f"opacity must be a number from {MIN_OPACITY} to {MAX_OPACITY}.")
    if value["showIn3D"] is not False:
        raise ValueError("showIn3D must be false: the underlay shows in the Plan view only.")
    result = {"referenceId": reference_id, "label": clean_label(value["label"], "label")}
    if "sourceName" in value:
        result["sourceName"] = clean_label(value["sourceName"], "sourceName")
    result.update({
        "importId": value["importId"],
        "sourceSha256": value["sourceSha256"],
        "geometrySha256": value["geometrySha256"],
        "parserVersion": parser,
        "alignment": normalize_alignment(value["alignment"]),
        "layers": _layers(value["layers"]),
        "opacity": round(float(opacity), 2),
        "showIn3D": False,
    })
    return result


def normalize_floor_plan_references(value) -> dict:
    """The stored form of the extension; raises ValueError. An empty list is not stored: the key is removed."""
    if not isinstance(value, dict) or set(value) != {"version", "references"}:
        raise ValueError(f"{KEY} must have exactly version and references.")
    if value["version"] != VERSION or isinstance(value["version"], bool):
        raise ValueError(f"{KEY}.version must be {VERSION}.")
    references = value["references"]
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_REFERENCES:
        raise ValueError(f"A layout keeps 1 to {MAX_REFERENCES} floor-plan reference(s).")
    normalized = [normalize_reference(reference) for reference in references]
    identifiers = [reference["referenceId"] for reference in normalized]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Each floor-plan reference needs its own referenceId.")
    return {"version": VERSION, "references": normalized}


def layout_references(document) -> dict[str, dict]:
    """referenceId -> reference, read leniently from any document (validation reports bad records elsewhere)."""
    value = ((document or {}).get("extensions") or {}).get(KEY)
    if not isinstance(value, dict) or not isinstance(value.get("references"), list):
        return {}
    return {reference["referenceId"]: reference for reference in value["references"]
            if isinstance(reference, dict) and isinstance(reference.get("referenceId"), str)}
