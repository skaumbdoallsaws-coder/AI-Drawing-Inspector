"""Deterministic occurrence identity masks rendered from a GLB asset."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw


class GlbMaskError(ValueError):
    pass


_COMPONENT_DTYPES = {
    5121: np.dtype("<u1"),
    5123: np.dtype("<u2"),
    5125: np.dtype("<u4"),
    5126: np.dtype("<f4"),
}

_TYPE_WIDTHS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
}


def _read_glb(path: Path) -> Tuple[Mapping[str, Any], bytes]:
    payload = path.read_bytes()
    if len(payload) < 20:
        raise GlbMaskError("GLB is truncated.")
    magic, version, declared_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(payload):
        raise GlbMaskError("GLB header is invalid.")
    offset = 12
    document = None
    binary = None
    while offset + 8 <= len(payload):
        chunk_length, chunk_type = struct.unpack_from("<II", payload, offset)
        offset += 8
        chunk = payload[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \t\r\n\0").decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = chunk
    if not isinstance(document, dict) or binary is None:
        raise GlbMaskError("GLB requires JSON and BIN chunks.")
    return document, binary


def _accessor(
    document: Mapping[str, Any],
    binary: bytes,
    accessor_index: int,
) -> np.ndarray:
    accessors = document.get("accessors", [])
    buffer_views = document.get("bufferViews", [])
    try:
        accessor = accessors[accessor_index]
        view = buffer_views[accessor["bufferView"]]
        dtype = _COMPONENT_DTYPES[accessor["componentType"]]
        width = _TYPE_WIDTHS[accessor["type"]]
        count = int(accessor["count"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise GlbMaskError(f"Unsupported GLB accessor {accessor_index}.") from exc
    if int(view.get("buffer", 0)) != 0:
        raise GlbMaskError("Identity renderer supports one embedded GLB buffer.")
    byte_offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    packed_stride = dtype.itemsize * width
    byte_stride = int(view.get("byteStride", packed_stride))
    if byte_stride == packed_stride:
        result = np.frombuffer(
            binary,
            dtype=dtype,
            count=count * width,
            offset=byte_offset,
        ).reshape((count, width))
    else:
        result = np.ndarray(
            shape=(count, width),
            dtype=dtype,
            buffer=binary,
            offset=byte_offset,
            strides=(byte_stride, dtype.itemsize),
        )
    return np.array(result, copy=True)


def _node_matrix(node: Mapping[str, Any]) -> np.ndarray:
    if "matrix" in node:
        values = np.asarray(node["matrix"], dtype=np.float64)
        if values.size != 16:
            raise GlbMaskError("Node matrix must contain 16 values.")
        return values.reshape((4, 4), order="F")
    translation = np.asarray(node.get("translation", [0, 0, 0]), dtype=np.float64)
    scale = np.asarray(node.get("scale", [1, 1, 1]), dtype=np.float64)
    quaternion = np.asarray(node.get("rotation", [0, 0, 0, 1]), dtype=np.float64)
    if translation.size != 3 or scale.size != 3 or quaternion.size != 4:
        raise GlbMaskError("Node TRS values are invalid.")
    x, y, z, w = quaternion
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = rotation @ np.diag(scale)
    result[:3, 3] = translation
    return result


def _load_occurrence_triangles(
    glb_path: Path,
    colors_by_alias: Mapping[str, Tuple[int, int, int]],
) -> Tuple[np.ndarray, np.ndarray]:
    document, binary = _read_glb(glb_path)
    meshes = document.get("meshes", [])
    triangle_blocks = []
    color_blocks = []
    seen_aliases = set()
    for node in document.get("nodes", []):
        if "mesh" not in node:
            continue
        alias = str(node.get("name") or "")
        if alias not in colors_by_alias:
            raise GlbMaskError(f"GLB mesh alias is not canonical: {alias or '<missing>'}")
        mesh = meshes[int(node["mesh"])]
        matrix = _node_matrix(node)
        for primitive in mesh.get("primitives", []):
            if int(primitive.get("mode", 4)) != 4:
                raise GlbMaskError("Identity renderer supports triangle primitives only.")
            positions = _accessor(
                document,
                binary,
                int(primitive["attributes"]["POSITION"]),
            ).astype(np.float64)
            homogeneous = np.concatenate(
                [positions[:, :3], np.ones((positions.shape[0], 1))],
                axis=1,
            )
            positions = (homogeneous @ matrix.T)[:, :3]
            if "indices" in primitive:
                indices = _accessor(
                    document,
                    binary,
                    int(primitive["indices"]),
                ).reshape(-1)
            else:
                indices = np.arange(positions.shape[0], dtype=np.int64)
            if indices.size % 3:
                raise GlbMaskError(f"Mesh indices are not triangles: {alias}")
            triangles = positions[indices.astype(np.int64)].reshape((-1, 3, 3))
            triangle_blocks.append(triangles)
            color_blocks.append(
                np.tile(
                    np.asarray(colors_by_alias[alias], dtype=np.uint8),
                    (triangles.shape[0], 1),
                )
            )
        seen_aliases.add(alias)
    missing = sorted(set(colors_by_alias) - seen_aliases)
    if missing:
        raise GlbMaskError(
            "Canonical occurrences missing from GLB: " + ", ".join(missing[:8])
        )
    if not triangle_blocks:
        raise GlbMaskError("GLB contains no occurrence triangles.")
    return np.concatenate(triangle_blocks), np.concatenate(color_blocks)


def summarize_glb_occurrences(
    glb_path: str | Path,
) -> Dict[str, Dict[str, Any]]:
    """Return deterministic world-space geometry summaries by node alias."""
    document, binary = _read_glb(Path(glb_path))
    meshes = document.get("meshes", [])
    summaries: Dict[str, Dict[str, Any]] = {}
    for node in document.get("nodes", []):
        if "mesh" not in node:
            continue
        alias = str(node.get("name") or "")
        if not alias or alias in summaries:
            raise GlbMaskError(f"GLB occurrence alias is missing or duplicated: {alias}")
        mesh = meshes[int(node["mesh"])]
        matrix = _node_matrix(node)
        position_blocks = []
        triangle_count = 0
        for primitive in mesh.get("primitives", []):
            if int(primitive.get("mode", 4)) != 4:
                raise GlbMaskError("Geometry summary supports triangle primitives only.")
            positions = _accessor(
                document,
                binary,
                int(primitive["attributes"]["POSITION"]),
            ).astype(np.float64)
            homogeneous = np.concatenate(
                [positions[:, :3], np.ones((positions.shape[0], 1))],
                axis=1,
            )
            world = (homogeneous @ matrix.T)[:, :3]
            position_blocks.append(world)
            if "indices" in primitive:
                index_count = _accessor(
                    document,
                    binary,
                    int(primitive["indices"]),
                ).size
            else:
                index_count = world.shape[0]
            if index_count % 3:
                raise GlbMaskError(f"Mesh indices are not triangles: {alias}")
            triangle_count += index_count // 3
        if not position_blocks:
            continue
        positions = np.concatenate(position_blocks)
        minimum = positions.min(axis=0)
        maximum = positions.max(axis=0)
        center = (minimum + maximum) / 2.0
        size = maximum - minimum
        summaries[alias] = {
            "bounds": {
                "min": [round(float(value), 9) for value in minimum],
                "max": [round(float(value), 9) for value in maximum],
                "center": [round(float(value), 9) for value in center],
                "size": [round(float(value), 9) for value in size],
            },
            "vertexCount": int(positions.shape[0]),
            "triangleCount": int(triangle_count),
        }
    return dict(sorted(summaries.items()))


def _view_basis(view_name: str) -> np.ndarray:
    if view_name == "front":
        return np.asarray(((1, 0, 0), (0, 1, 0), (0, 0, 1)), dtype=np.float64)
    if view_name == "top":
        return np.asarray(((1, 0, 0), (0, 0, -1), (0, 1, 0)), dtype=np.float64)
    if view_name == "right":
        return np.asarray(((0, 0, -1), (0, 1, 0), (1, 0, 0)), dtype=np.float64)
    if view_name == "isometric":
        depth = np.asarray((1, 1, 1), dtype=np.float64)
        depth /= np.linalg.norm(depth)
        right = np.asarray((1, 0, -1), dtype=np.float64)
        right /= np.linalg.norm(right)
        up = np.cross(depth, right)
        up /= np.linalg.norm(up)
        return np.stack((right, up, depth))
    raise GlbMaskError(f"Unsupported view: {view_name}")


def _render_view(
    triangles: np.ndarray,
    colors: np.ndarray,
    *,
    view_name: str,
    size: Tuple[int, int],
    margin_ratio: float,
) -> Image.Image:
    width, height = size
    if width < 64 or height < 64:
        raise GlbMaskError("Identity-mask dimensions are too small.")
    projected = triangles @ _view_basis(view_name).T
    x_values = projected[:, :, 0]
    y_values = projected[:, :, 1]
    x_min, x_max = float(x_values.min()), float(x_values.max())
    y_min, y_max = float(y_values.min()), float(y_values.max())
    if not all(math.isfinite(value) for value in (x_min, x_max, y_min, y_max)):
        raise GlbMaskError("GLB contains non-finite geometry.")
    available_width = width * (1.0 - margin_ratio * 2)
    available_height = height * (1.0 - margin_ratio * 2)
    scale = min(
        available_width / max(x_max - x_min, 1e-9),
        available_height / max(y_max - y_min, 1e-9),
    )
    x_center = (x_min + x_max) / 2.0
    y_center = (y_min + y_max) / 2.0
    screen_x = (x_values - x_center) * scale + width / 2.0
    screen_y = height / 2.0 - (y_values - y_center) * scale
    depths = projected[:, :, 2].mean(axis=1)
    order = np.argsort(depths, kind="stable")

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for index in order:
        points = [
            (int(round(screen_x[index, vertex])), int(round(screen_y[index, vertex])))
            for vertex in range(3)
        ]
        area = abs(
            (points[1][0] - points[0][0]) * (points[2][1] - points[0][1])
            - (points[2][0] - points[0][0]) * (points[1][1] - points[0][1])
        )
        if area == 0:
            continue
        color = tuple(int(value) for value in colors[index])
        draw.polygon(points, fill=color)
    return image


def render_glb_identity_masks(
    glb_path: str | Path,
    legend_entries: Sequence[Mapping[str, str]],
    *,
    output_dir: str | Path,
    assembly_base_name: str,
    dimensions_by_view: Mapping[str, Tuple[int, int]],
    margin_ratio: float = 0.08,
) -> Dict[str, Path]:
    colors_by_alias: Dict[str, Tuple[int, int, int]] = {}
    for entry in legend_entries:
        alias = str(entry["componentAlias"])
        color = str(entry["hexColor"])
        if alias in colors_by_alias:
            raise GlbMaskError(f"Duplicate canonical alias: {alias}")
        colors_by_alias[alias] = tuple(
            int(color[index : index + 2], 16) for index in (1, 3, 5)
        )
    triangles, colors = _load_occurrence_triangles(Path(glb_path), colors_by_alias)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    result = {}
    for view_name in ("front", "top", "right", "isometric"):
        if view_name not in dimensions_by_view:
            raise GlbMaskError(f"Missing mask dimensions for {view_name}.")
        image = _render_view(
            triangles,
            colors,
            view_name=view_name,
            size=dimensions_by_view[view_name],
            margin_ratio=margin_ratio,
        )
        path = output_root / (
            f"{assembly_base_name}_identity_mask_view_{view_name}.png"
        )
        image.save(path, format="PNG", optimize=False, compress_level=9)
        result[view_name] = path
    return result
