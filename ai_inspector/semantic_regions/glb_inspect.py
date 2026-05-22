"""Minimal glTF 2.0 binary (.glb) reader for semantic-region heuristics.

Reads only what the rules need: per-mesh name, per-mesh axis-aligned
bbox from the POSITION accessor's min/max fields (which the
SolidWorksExtractor writes for every mesh -- the glTF spec requires
min/max on POSITION accessors). Zero external dependencies; pure stdlib.

Why not pygltflib / trimesh: this MVP runs inside the FastAPI request
handler and we already parse GLBs the same way in our smoke scripts.
A 60-line parser keeps the dependency surface zero.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


_GLB_MAGIC = 0x46546C67  # "glTF" little-endian
_JSON_CHUNK_TYPE = 0x4E4F534A


@dataclass
class GlbNode:
    """Per-node summary used by the region rules.

    `bbox_min` and `bbox_max` are in glTF native units (the
    SolidWorksExtractor emits raw SolidWorks meters; do not scale).
    Rules normalize against the overall part bbox so the unit cancels.
    Any axis where min==max yields zero extent on that axis -- legitimate
    for flat planar surfaces (e.g. Surface-Plane).
    """
    index:        int
    name:         str          # mesh name (== node name for SolidWorksExtractor output)
    material_idx: int
    double_sided: bool
    bbox_min:     Tuple[float, float, float]
    bbox_max:     Tuple[float, float, float]

    @property
    def centroid(self) -> Tuple[float, float, float]:
        return (
            0.5 * (self.bbox_min[0] + self.bbox_max[0]),
            0.5 * (self.bbox_min[1] + self.bbox_max[1]),
            0.5 * (self.bbox_min[2] + self.bbox_max[2]),
        )

    @property
    def extent(self) -> Tuple[float, float, float]:
        return (
            self.bbox_max[0] - self.bbox_min[0],
            self.bbox_max[1] - self.bbox_min[1],
            self.bbox_max[2] - self.bbox_min[2],
        )


@dataclass
class GlbSummary:
    """Per-part inspection result. `overall_min`/`max` is the union of
    all node bboxes, used to normalize the rule thresholds."""
    generator:    str
    nodes:        List[GlbNode]
    overall_min:  Tuple[float, float, float]
    overall_max:  Tuple[float, float, float]

    @property
    def overall_extent(self) -> Tuple[float, float, float]:
        return (
            self.overall_max[0] - self.overall_min[0],
            self.overall_max[1] - self.overall_min[1],
            self.overall_max[2] - self.overall_min[2],
        )


def inspect_glb(glb_path: Path) -> GlbSummary:
    """Parse a .glb file and return per-mesh names + bboxes.

    Raises FileNotFoundError if missing, ValueError on bad magic or
    malformed JSON chunk. Tolerates accessors without min/max by
    falling back to a zero bbox -- the node still appears in the
    summary so the rules can route it to a fallback bucket rather
    than silently dropping it.
    """
    if not glb_path.exists():
        raise FileNotFoundError(f"GLB not found: {glb_path}")

    data = glb_path.read_bytes()
    if len(data) < 20:
        raise ValueError(f"GLB too short ({len(data)} bytes): {glb_path}")
    magic, version, total_len = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC:
        raise ValueError(f"Not a GLB (magic=0x{magic:08x}): {glb_path}")
    if version != 2:
        raise ValueError(f"Unsupported GLB version {version}: {glb_path}")

    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != _JSON_CHUNK_TYPE:
        raise ValueError(f"First chunk is not JSON (type=0x{chunk_type:08x}): {glb_path}")
    json_bytes = data[20:20 + chunk_len]
    json_str = json_bytes.decode("utf-8", errors="replace").rstrip("\x00 ")
    try:
        doc = json.loads(json_str)
    except json.JSONDecodeError as ex:
        raise ValueError(f"Malformed glTF JSON in {glb_path}: {ex}")

    generator = (doc.get("asset") or {}).get("generator") or ""
    accessors = doc.get("accessors") or []
    materials = doc.get("materials") or []
    meshes    = doc.get("meshes")    or []

    nodes: List[GlbNode] = []
    for i, mesh in enumerate(meshes):
        primitives = mesh.get("primitives") or []
        if not primitives:
            continue
        prim = primitives[0]
        attrs = prim.get("attributes") or {}
        pos_acc_idx = attrs.get("POSITION")
        material_idx = prim.get("material", -1)
        bbox_min = (0.0, 0.0, 0.0)
        bbox_max = (0.0, 0.0, 0.0)
        if isinstance(pos_acc_idx, int) and 0 <= pos_acc_idx < len(accessors):
            acc = accessors[pos_acc_idx]
            amn = acc.get("min")
            amx = acc.get("max")
            if isinstance(amn, list) and len(amn) >= 3:
                bbox_min = (float(amn[0]), float(amn[1]), float(amn[2]))
            if isinstance(amx, list) and len(amx) >= 3:
                bbox_max = (float(amx[0]), float(amx[1]), float(amx[2]))
        double_sided = False
        if 0 <= material_idx < len(materials):
            double_sided = bool(materials[material_idx].get("doubleSided", False))
        nodes.append(GlbNode(
            index=i,
            name=str(mesh.get("name") or f"mesh_{i}"),
            material_idx=material_idx,
            double_sided=double_sided,
            bbox_min=bbox_min,
            bbox_max=bbox_max,
        ))

    if nodes:
        ox_min = min(n.bbox_min[0] for n in nodes)
        oy_min = min(n.bbox_min[1] for n in nodes)
        oz_min = min(n.bbox_min[2] for n in nodes)
        ox_max = max(n.bbox_max[0] for n in nodes)
        oy_max = max(n.bbox_max[1] for n in nodes)
        oz_max = max(n.bbox_max[2] for n in nodes)
    else:
        ox_min = oy_min = oz_min = 0.0
        ox_max = oy_max = oz_max = 0.0

    return GlbSummary(
        generator=generator,
        nodes=nodes,
        overall_min=(ox_min, oy_min, oz_min),
        overall_max=(ox_max, oy_max, oz_max),
    )
