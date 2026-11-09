"""D11 transforms on copies of validated arrays; the source cache stays immutable."""
from copy import deepcopy
from dataclasses import replace
from difflib import get_close_matches
import math

import numpy as np

from .errors import ModelImportError
from .model import Model, Part
from .validation import json_bytes, require

OUTPUT_TRIANGLES = 250_000


def select_parts(parts: list[Part], materials: list[dict], selector: dict) -> list[Part]:
    key, value = next(iter(selector.items()))
    def field(part):
        return part.key if key == "part" else materials[part.material]["name"] if key == "material" else getattr(part, key, "")
    matches = list(parts) if key == "all" else [p for p in parts if field(p) == value]
    if not matches:
        candidates = sorted({field(p) for p in parts}) if key != "all" else []
        closest = get_close_matches(str(value), candidates, n=4, cutoff=0)[:4]
        raise ModelImportError("recipe_selector_empty", {"selector": f"{key}: {value}", "closest": closest})
    return matches


def bounds(parts):
    require(bool(parts), "model_empty")
    return (np.min([p.positions.min(axis=0) for p in parts], axis=0).astype(float),
            np.max([p.positions.max(axis=0) for p in parts], axis=0).astype(float))


def base_center(part):
    low, high = bounds([part])
    return np.array([(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2])


def rotation(x=0, y=0, z=0):
    x, y, z = (math.radians(v) for v in (x, y, z))
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _transform(part, scale=1, matrix=None, pivot=None, offset=None):
    matrix = np.eye(3) if matrix is None else matrix
    pivot = np.zeros(3) if pivot is None else pivot
    offset = np.zeros(3) if offset is None else offset
    positions = ((part.positions - pivot) * scale) @ matrix.T + pivot + offset
    normals = part.normals @ matrix.T if part.normals is not None else None
    return replace(part, positions=positions, normals=normals)


def linear_color(color):
    values = np.array([int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)], dtype=float)
    return np.where(values <= .04045, values / 12.92, ((values + .055) / 1.055) ** 2.4).tolist()


def patch_material(material, patch):
    result = deepcopy(material)
    if "color" in patch:
        result["baseColor"] = linear_color(patch["color"]) + [1.0]
    for key in ("roughness", "metalness", "alphaCutoff", "doubleSided"):
        if key in patch:
            result[key] = patch[key]
    if patch.get("texture") == "drop":
        result["texture"] = None
    if patch.get("emissive") == "off":
        result["emissive"] = [0.0, 0.0, 0.0]
    if "alpha" in patch:
        result["alphaMode"] = patch["alpha"].upper()
    return result


def triangle_budget(parts, copies=1, added=0):
    count = sum(len(p.indices) for p in parts) * copies + added
    if count > OUTPUT_TRIANGLES:
        largest = sorted(parts, key=lambda p: (-len(p.indices), p.key))[:5]
        raise ModelImportError("model_output_too_complex", {
            "triangles": count, "largestParts": [{"key": p.key, "name": p.name,
                                                  "triangles": len(p.indices) * copies} for p in largest]})


def transform_model(source: Model, recipe: dict) -> Model:
    """Recipe must already be normalized. Selectors keep their source identities."""
    from .simple_parts import added_part
    # Only vertices referenced by triangles affect an authored solid. This also
    # prevents unused source vertices multiplying memory across twelve copies.
    parts = []
    for part in source.parts:
        used, inverse = np.unique(part.indices.reshape(-1), return_inverse=True)
        parts.append(replace(part, positions=part.positions[used].astype(float),
                             normals=part.normals[used].astype(float) if part.normals is not None else None,
                             uv0=part.uv0[used].copy() if part.uv0 is not None else None,
                             indices=inverse.reshape(-1, 3).astype(np.uint32)))
    low, high = bounds(parts)
    pivot = np.array([(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2])
    if recipe["pivot"] != "base":
        chosen = {p.key: p for selector in recipe["pivot"]["parts"]
                  for p in select_parts(parts, source.materials, selector)}
        points = np.concatenate([p.positions for p in chosen.values()])
        threshold = points[:, 1].min() + np.ptp(points[:, 1]) * .1
        feet = points[points[:, 1] <= threshold]
        pivot[[0, 2]] = (feet.min(axis=0) + feet.max(axis=0))[[0, 2]] / 2
    matrix = rotation(**recipe["rotate"])
    parts = [_transform(replace(p, positions=p.positions - pivot), matrix=matrix) for p in parts]
    # The working pivot is now x=z=0. Rebase after rotation, before sizing.
    low, high = bounds(parts)
    parts = [_transform(p, offset=np.array([0, -low[1], 0])) for p in parts]
    size = recipe["size"]
    if "scale" in size:
        scale = size["scale"]
    else:
        extent = high - low
        length = float(extent.max() if size["dimension"] == "largest" else
                       extent[{"width": 0, "height": 1, "depth": 2}[size["dimension"]]])
        require(length > 1e-12, "model_dimensions_invalid")
        scale = size["meters"] / length
    parts = [_transform(p, scale=scale) for p in parts]
    # Keep source material indices for all selector evaluations; patches are separate.
    finishes = {p.key: deepcopy(source.materials[p.material]) for p in parts}
    for part in parts:
        if part.uv0 is None:
            finishes[part.key]["texture"] = None
    for rule in recipe["parts"]:
        selected = {p.key for p in select_parts(parts, source.materials, rule["select"])}
        output = []
        for part in parts:
            if part.key not in selected:
                output.append(part)
                continue
            part = replace(part, name=rule.get("name", part.name))
            if rule["drop"]:
                continue
            finishes[part.key] = patch_material(finishes[part.key], rule["material"])
            center = base_center(part)
            part = _transform(part, scale=rule["scale"], matrix=rotation(y=rule["turnDegrees"]), pivot=center)
            offset = np.array(rule["moveTo"]) - center if "moveTo" in rule else np.array(rule["move"])
            output.append(_transform(part, offset=offset))
        parts = output
    additions = [added_part(item, i) for i, item in enumerate(recipe["add"])]
    triangle_budget(parts, len(recipe["copies"]), sum(len(p.indices) for p, _ in additions))
    materials, material_ids = [], {}
    def material_id(material):
        key = json_bytes(material)
        if key not in material_ids:
            material_ids[key] = len(materials)
            materials.append(material)
        return material_ids[key]
    output = []
    for copy in recipe["copies"]:
        matrix = rotation(y=copy["turnDegrees"])
        for part in parts:
            material = deepcopy(finishes[part.key])
            material["name"] = part.name
            transformed = _transform(part, scale=copy["scale"], matrix=matrix,
                                     offset=np.array([copy["x"], 0, copy["z"]]))
            output.append(replace(transformed, key=f"p{len(output)}", material=material_id(material)))
    for part, material in additions:
        output.append(replace(part, key=f"p{len(output)}", material=material_id(material)))
    low, high = bounds(output)
    offset = -np.array([(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2])
    output = [_transform(p, offset=offset) for p in output]
    for part in output:
        part.positions = part.positions.astype("<f4")
        if part.normals is not None:
            part.normals = part.normals.astype("<f4")
        require(bool(np.isfinite(part.positions).all()), "model_dimensions_invalid")
    low, high = bounds(output)
    require(bool(np.all(high - low > 1e-8)) and bool(np.all(high - low <= 10000)), "model_dimensions_invalid")
    return replace(source, name=recipe["name"], parts=output, materials=materials, warnings=list(source.warnings))
