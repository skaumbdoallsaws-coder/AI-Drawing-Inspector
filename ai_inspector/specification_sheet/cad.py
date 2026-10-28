"""What the CAD says about a product, for the specification sheet: its overall extents from the 3D model and its
weight when every part has a material. Nothing here is estimated: a fact the CAD does not have stays open."""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
_MAX_PLAUSIBLE_METRES = 200.0  # a GLB larger than this is in millimetres, not metres


def _multiply(a: List[float], b: List[float]) -> List[float]:
    """Column-major 4x4 product, as glTF stores matrices."""
    return [sum(a[k * 4 + row] * b[column * 4 + k] for k in range(4))
            for column in range(4) for row in range(4)]


def _local_matrix(node: Mapping[str, Any]) -> List[float]:
    if isinstance(node.get("matrix"), list) and len(node["matrix"]) == 16:
        return [float(value) for value in node["matrix"]]
    tx, ty, tz = (node.get("translation") or [0.0, 0.0, 0.0])[:3]
    qx, qy, qz, qw = (node.get("rotation") or [0.0, 0.0, 0.0, 1.0])[:4]
    sx, sy, sz = (node.get("scale") or [1.0, 1.0, 1.0])[:3]
    rotation = [
        1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw), 0.0,
        2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw), 0.0,
        2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy), 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    scaled = [rotation[i] * (sx, sy, sz, 1.0)[i // 4] for i in range(16)]
    scaled[12:15] = [float(tx), float(ty), float(tz)]
    return scaled


def glb_extents(path: str | Path, exclude: Iterable[str] = ()) -> Optional[Dict[str, float]]:
    """The model's axis-aligned extents in metres: width (x), depth (z) and height (y, glTF's up axis). Nodes named
    in exclude (and what they hold) are left out: a library model's clearance zone is not the machine."""
    excluded = {str(name).strip().casefold() for name in exclude if str(name).strip()}
    try:
        data = Path(path).read_bytes()
        if data[:4] != b"glTF":
            return None
        length = struct.unpack_from("<I", data, 12)[0]
        gltf = json.loads(data[20:20 + length])
    except (OSError, ValueError, struct.error):
        return None
    nodes = gltf.get("nodes") or []
    meshes = gltf.get("meshes") or []
    accessors = gltf.get("accessors") or []
    scenes = gltf.get("scenes") or []
    roots = (scenes[int(gltf.get("scene") or 0)].get("nodes") if scenes else None) or [
        index for index in range(len(nodes))
        if not any(index in (other.get("children") or []) for other in nodes)]
    low, high = [math.inf] * 3, [-math.inf] * 3
    stack = [(index, _IDENTITY) for index in roots]
    seen = 0
    while stack and seen < 100000:
        index, parent = stack.pop()
        seen += 1
        if not 0 <= index < len(nodes):
            continue
        node = nodes[index]
        if excluded and str(node.get("name") or "").strip().casefold() in excluded:
            continue
        world = _multiply(parent, _local_matrix(node))
        mesh = meshes[node["mesh"]] if isinstance(node.get("mesh"), int) and node["mesh"] < len(meshes) else None
        for primitive in (mesh or {}).get("primitives") or []:
            accessor_index = (primitive.get("attributes") or {}).get("POSITION")
            if not isinstance(accessor_index, int) or accessor_index >= len(accessors):
                continue
            accessor = accessors[accessor_index]
            minimum, maximum = accessor.get("min"), accessor.get("max")
            if not (isinstance(minimum, list) and isinstance(maximum, list) and len(minimum) >= 3):
                continue
            for corner in range(8):
                point = [maximum[axis] if corner >> axis & 1 else minimum[axis] for axis in range(3)]
                for axis in range(3):
                    value = sum(world[k * 4 + axis] * (point + [1.0])[k] for k in range(4))
                    low[axis], high[axis] = min(low[axis], value), max(high[axis], value)
        stack.extend((child, world) for child in node.get("children") or [])
    if not all(math.isfinite(value) for value in low + high):
        return None
    size = [high[axis] - low[axis] for axis in range(3)]
    if max(size) > _MAX_PLAUSIBLE_METRES:
        size = [value / 1000.0 for value in size]
    if max(size) <= 0:
        return None
    return {"width": round(size[0], 4), "depth": round(size[2], 4), "height": round(size[1], 4)}


def assembly_mass(assembly_data: Mapping[str, Any]) -> Dict[str, Any]:
    """The sum of the parts' CAD masses (kg; the extractor's unit label says mg but the values are SI), only when
    every part instance has an assigned material. Otherwise the weight is open and the note says why."""
    cache = assembly_data.get("partDataCache") if isinstance(assembly_data.get("partDataCache"), Mapping) else {}
    total, parts, missing = 0.0, 0, 0
    for component in assembly_data.get("components") or []:
        if not isinstance(component, Mapping) or component.get("isSuppressed"):
            continue
        if str(component.get("type") or "").casefold() != "part":
            continue
        parts += 1
        physical = (cache.get(component.get("partDataKey")) or {}).get("physical") if component.get(
            "partDataKey") in cache else None
        mass = physical.get("mass") if isinstance(physical, Mapping) else None
        if not isinstance(physical, Mapping) or not physical.get("assignedMaterial") \
                or not isinstance(mass, (int, float)) or not math.isfinite(mass) or mass <= 0:
            missing += 1
            continue
        total += float(mass)
    if not parts:
        return {"massKg": None, "note": "the CAD lists no parts"}
    if missing:
        return {"massKg": None, "note": f"{missing} of {parts} parts have no material in the CAD"}
    return {"massKg": round(total, 3), "note": f"sum of {parts} parts with materials"}


def _number(value: float, places: int) -> str:
    text = f"{value:,.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_extents(extents: Mapping[str, float], units: str) -> str:
    values = [float(extents[key]) for key in ("width", "depth", "height")]
    if units == "metric":
        return " x ".join(_number(value * 1000.0, 0) for value in values) + " mm"
    return " x ".join(_number(value / 0.0254, 1) for value in values) + " in"


def format_mass(mass_kg: float, units: str) -> str:
    if units == "metric":
        return _number(mass_kg, 1 if mass_kg < 100 else 0) + " kg"
    pounds = mass_kg / 0.45359237
    return _number(pounds, 1 if pounds < 100 else 0) + " lb"
