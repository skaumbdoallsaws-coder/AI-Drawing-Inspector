"""Bounded preview geometry: source sampling and shared shader records, no app imports."""
from dataclasses import dataclass

import numpy as np

from .model import Model
from .transforms import bounds
from .validation import json_bytes

MAX_PREVIEW_TRIANGLES = 250_000


@dataclass
class PreviewGeometry:
    corners: np.ndarray
    normals: np.ndarray
    uv: np.ndarray
    has_uv: np.ndarray
    materials: np.ndarray
    shaders: list[dict]
    dimensions: np.ndarray
    scale: float
    box: np.ndarray
    total: int

    @property
    def shown(self) -> int:
        return len(self.corners)


def build_geometry(model: Model, maximum: int = MAX_PREVIEW_TRIANGLES) -> PreviewGeometry:
    low, high = bounds(model.parts)
    dimensions = high - low
    scale = max(float(dimensions.max()), 1e-30)
    origin = np.array([(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2])
    total = sum(len(p.indices) for p in model.parts)
    selected = None
    if total > maximum:
        areas = np.empty(total, dtype=np.float64)
        offset = 0
        for part in model.parts:
            for start in range(0, len(part.indices), 8192):
                faces = part.indices[start:start + 8192]
                points = (part.positions[faces].astype(np.float64) - origin) / scale
                cross = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
                areas[offset + start:offset + start + len(faces)] = np.einsum("ij,ij->i", cross, cross)
            offset += len(part.indices)
        threshold = np.partition(areas, total - maximum)[total - maximum]
        selected = areas > threshold
        # Exact ties retain source traversal order, independent of partition tie order.
        ties = np.flatnonzero(areas == threshold)[:maximum - int(selected.sum())]
        selected[ties] = True
    shader_ids, shaders, material_map = {}, [], []
    for material in model.materials:
        shader = {key: material[key] for key in ("baseColor", "texture", "alphaMode", "alphaCutoff",
                                               "emissive", "unlit")}
        key = json_bytes(shader)
        if key not in shader_ids:
            shader_ids[key] = len(shaders)
            shaders.append(shader)
        material_map.append(shader_ids[key])
    corners, normals, uvs, has_uv, materials = [], [], [], [], []
    offset = 0
    for part in model.parts:
        indices = part.indices if selected is None else part.indices[selected[offset:offset + len(part.indices)]]
        offset += len(part.indices)
        if not len(indices):
            continue
        points = ((part.positions[indices].astype(np.float64) - origin) / scale).astype(np.float32)
        geometric = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
        normal = part.normals[indices].mean(axis=1) if part.normals is not None else geometric
        lengths = np.linalg.norm(normal, axis=1, keepdims=True)
        normal = np.divide(normal, lengths, out=np.zeros_like(normal), where=lengths > 1e-20)
        corners.append(points)
        normals.append(normal.astype(np.float32))
        uvs.append(part.uv0[indices] if part.uv0 is not None else np.zeros((len(indices), 3, 2), dtype=np.float32))
        has_uv.append(np.full(len(indices), part.uv0 is not None, dtype=bool))
        materials.append(np.full(len(indices), material_map[part.material], dtype=np.int32))
    box = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1])
                    for z in (low[2], high[2])], dtype=np.float64)
    box = ((box - origin) / scale).astype(np.float32)
    return PreviewGeometry(np.concatenate(corners), np.concatenate(normals), np.concatenate(uvs),
                           np.concatenate(has_uv), np.concatenate(materials), shaders, dimensions, scale, box, total)
