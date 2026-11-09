"""Small, deterministic inspection pages; no triangle arrays enter tool JSON."""
from copy import deepcopy

import numpy as np

from .limits import SUMMARY_BYTES
from .model import Model
from .validation import integer, json_bytes, require


def bounds(positions: np.ndarray) -> dict:
    return {"minimum": positions.min(axis=0).astype(float).tolist(),
            "maximum": positions.max(axis=0).astype(float).tolist()}


def raw_bounds(model: Model) -> dict:
    low = np.min([p.positions.min(axis=0) for p in model.parts], axis=0).astype(float)
    high = np.max([p.positions.max(axis=0) for p in model.parts], axis=0).astype(float)
    return {"minimum": low.tolist(), "maximum": high.tolist()}


def material_summary(material: dict, images) -> dict:
    texture = material["texture"]
    image = images[texture["image"]] if texture else None
    return {key: deepcopy(material[key]) for key in
            ("name", "baseColor", "alphaMode", "alphaCutoff", "emissive", "doubleSided", "roughness", "metalness",
             "unlit")} | {"textureSize": [image.width, image.height] if image else None}


def part_summary(part, model) -> dict:
    return {"key": part.key, "name": part.name, "node": part.node, "mesh": part.mesh,
            "material": model.materials[part.material]["name"], "triangles": len(part.indices),
            "bounds": bounds(part.positions), **{key: value for key, value in
            material_summary(model.materials[part.material], model.images).items() if key != "name"}}


def flat_top_hints(model: Model) -> list[dict]:
    """Bounding rectangles of upward horizontal triangles, not verified supports."""
    hints = []
    for part in model.parts:
        for start in range(0, len(part.indices), 4096):
            points = part.positions[part.indices[start:start + 4096]].astype(float)
            normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
            lengths = np.linalg.norm(normals, axis=1)
            mask = ((normals[:, 1] > 0) & (np.abs(normals[:, 1]) >= lengths * 0.99999)
                    & (np.ptp(points[:, :, 1], axis=1) <= 1e-5))
            for triangle in points[mask][:6]:
                low, high = triangle.min(axis=0), triangle.max(axis=0)
                hint = {"part": part.key, "height": float(triangle[:, 1].mean()),
                        "rect": [float(low[0]), float(low[2]), float(high[0]), float(high[2])],
                        "verifiedSupport": False}
                if hint not in hints:
                    hints.append(hint)
                if len(hints) == 6:
                    return hints
    return hints


def build_summary(model: Model, *, parts_offset: int = 0, parts_limit: int = 64) -> dict:
    integer(parts_offset, 0, len(model.parts))
    integer(parts_limit, 1, 64)
    box = raw_bounds(model)
    size = [high - low for low, high in zip(box["minimum"], box["maximum"])]
    licence = deepcopy(model.licence)
    licence["excerpt"] = licence["excerpt"][:600]
    for conflict in licence["conflicts"]:
        conflict["values"] = [v[:80] for v in conflict["values"][:2]]
    summary = {
        "schemaVersion": 1, "name": model.name, "format": model.format, "state": "ready", "refusal": None,
        "sourceBytes": model.source_bytes, "sourceSha256": model.source_sha256,
        "triangles": sum(len(p.indices) for p in model.parts), "rawBounds": box,
        "rawSize": dict(zip(("width", "height", "depth"), size)),
        "unitGuesses": [{"unit": unit, "metersPerUnit": factor, "sizeMeters":
                        dict(zip(("width", "height", "depth"), [v * factor for v in size]))}
                       for unit, factor in (("m", 1), ("cm", 0.01), ("mm", 0.001), ("in", 0.0254))],
        "upAxisHint": {"declared": "+Y", "generator": model.generator, "bounds": box,
                       "suggested": "+Z" if "z-up" in model.generator.lower() else "unknown",
                       "note": "Bounds and generator are hints; orientation needs review."},
        "licence": licence, "partsTotal": len(model.parts), "partsOffset": parts_offset,
        "parts": [part_summary(p, model) for p in model.parts[parts_offset:parts_offset + parts_limit]],
        "materials": [material_summary(m, model.images) for m in model.materials],
        "materialsTotal": len(model.materials),
        "flatTopHints": flat_top_hints(model), "warnings": list(model.warnings[:20]),
    }
    # The page can contain fewer than requested when long Unicode names consume the budget.
    summary["nextPartsOffset"] = parts_offset + len(summary["parts"])
    while len(json_bytes(summary)) > SUMMARY_BYTES and len(summary["parts"]) > 1:
        summary["parts"].pop()
        summary["nextPartsOffset"] = parts_offset + len(summary["parts"])
    while len(json_bytes(summary)) > SUMMARY_BYTES and summary["materials"]:
        summary["materials"].pop()
    while len(json_bytes(summary)) > SUMMARY_BYTES and summary["warnings"]:
        summary["warnings"].pop()
    require(len(json_bytes(summary)) <= SUMMARY_BYTES, "gltf_too_complex")
    require(parts_offset == len(model.parts) or bool(summary["parts"]), "gltf_too_complex")
    if summary["nextPartsOffset"] >= len(model.parts):
        summary["nextPartsOffset"] = None
    return summary
