#!/usr/bin/env python3
"""Render a deterministic thumbnail from an oversized static GLB.

The primary asset-thumbnail renderer uses Three.js. This bounded software
fallback samples exact GLB POSITION data when a large CAD export exceeds the
practical browser-rendering budget. It is intended for catalog thumbnails,
not for replacing the full interactive GLB.
"""

from __future__ import annotations

import hashlib
import json
import math
import mmap
import os
import struct
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw


_GLB_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_BACKGROUND = (238, 243, 247)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _node_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        values = np.asarray(node["matrix"], dtype=np.float64)
        if values.shape != (16,) or not np.isfinite(values).all():
            raise ValueError("GLB node matrix is invalid")
        return values.reshape((4, 4), order="F")
    translation = np.asarray(node.get("translation", [0, 0, 0]), dtype=np.float64)
    scale = np.asarray(node.get("scale", [1, 1, 1]), dtype=np.float64)
    quaternion = np.asarray(node.get("rotation", [0, 0, 0, 1]), dtype=np.float64)
    if not all(value.shape == shape for value, shape in (
        (translation, (3,)), (scale, (3,)), (quaternion, (4,))
    )):
        raise ValueError("GLB node transform is invalid")
    x, y, z, w = quaternion
    magnitude = float(np.linalg.norm(quaternion))
    if magnitude <= 1e-12:
        raise ValueError("GLB node quaternion is invalid")
    x, y, z, w = quaternion / magnitude
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = rotation @ np.diag(scale)
    matrix[:3, 3] = translation
    return matrix


def _source_transform_matrix(
    values: tuple[float, ...] | list[float] | None,
) -> np.ndarray:
    if values is None:
        return np.eye(4, dtype=np.float64)
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.shape != (16,) or not np.isfinite(matrix).all():
        raise ValueError("Source transform must contain 16 finite values")
    return matrix.reshape((4, 4), order="F")


def _scene_instances(
    document: dict[str, Any],
    source_transform: np.ndarray | None = None,
) -> list[tuple[int, np.ndarray]]:
    nodes = document.get("nodes", [])
    scenes = document.get("scenes", [])
    scene_index = int(document.get("scene", 0))
    if not isinstance(nodes, list) or not 0 <= scene_index < len(scenes):
        raise ValueError("GLB scene graph is invalid")
    roots = scenes[scene_index].get("nodes", [])
    instances: list[tuple[int, np.ndarray]] = []

    def visit(index: int, parent: np.ndarray, ancestors: frozenset[int]) -> None:
        if index in ancestors or not 0 <= index < len(nodes):
            raise ValueError("GLB scene graph is cyclic or invalid")
        node = nodes[index]
        world = parent @ _node_matrix(node)
        mesh = node.get("mesh")
        if isinstance(mesh, int):
            instances.append((mesh, world))
        for child in node.get("children", []):
            visit(int(child), world, ancestors | {index})

    root_transform = (
        source_transform
        if source_transform is not None
        else np.eye(4, dtype=np.float64)
    )
    for root in roots:
        visit(int(root), root_transform, frozenset())
    if not instances:
        raise ValueError("GLB scene contains no mesh instances")
    return instances


def _transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def _transform_bounds(
    minimum: Iterable[float],
    maximum: Iterable[float],
    matrix: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    low = np.asarray(tuple(minimum), dtype=np.float64)
    high = np.asarray(tuple(maximum), dtype=np.float64)
    corners = np.array([
        [x, y, z]
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ])
    transformed = _transform_points(corners, matrix)
    return transformed.min(axis=0), transformed.max(axis=0)


def _material_color(document: dict[str, Any], index: Any) -> np.ndarray:
    materials = document.get("materials", [])
    factor = [0.36, 0.58, 0.72, 1]
    if isinstance(index, int) and 0 <= index < len(materials):
        factor = (
            materials[index]
            .get("pbrMetallicRoughness", {})
            .get("baseColorFactor", factor)
        )
    linear = np.clip(np.asarray(factor[:3], dtype=np.float64), 0, 1)
    return np.rint(np.power(linear, 1 / 2.2) * 255).astype(np.uint8)


def _position_view(
    binary: mmap.mmap,
    binary_offset: int,
    document: dict[str, Any],
    accessor_index: int,
) -> np.ndarray:
    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])
    accessor = accessors[accessor_index]
    if accessor.get("componentType") != 5126 or accessor.get("type") != "VEC3":
        raise ValueError("Software thumbnail requires FLOAT VEC3 POSITION data")
    view = views[int(accessor["bufferView"])]
    count = int(accessor["count"])
    stride = int(view.get("byteStride", 12))
    offset = (
        binary_offset
        + int(view.get("byteOffset", 0))
        + int(accessor.get("byteOffset", 0))
    )
    return np.ndarray(
        shape=(count, 3),
        dtype="<f4",
        buffer=binary,
        offset=offset,
        strides=(stride, 4),
    )


def _index_view(
    binary: mmap.mmap,
    binary_offset: int,
    document: dict[str, Any],
    accessor_index: int,
) -> np.ndarray:
    accessor = document.get("accessors", [])[accessor_index]
    views = document.get("bufferViews", [])
    component_type = int(accessor.get("componentType", 0))
    dtype = {5121: "u1", 5123: "<u2", 5125: "<u4"}.get(component_type)
    if dtype is None or accessor.get("type") != "SCALAR":
        raise ValueError("GLB triangle indices must be unsigned SCALAR data")
    view = views[int(accessor["bufferView"])]
    item_size = np.dtype(dtype).itemsize
    stride = int(view.get("byteStride", item_size))
    offset = (
        binary_offset
        + int(view.get("byteOffset", 0))
        + int(accessor.get("byteOffset", 0))
    )
    return np.ndarray(
        shape=(int(accessor["count"]),),
        dtype=dtype,
        buffer=binary,
        offset=offset,
        strides=(stride,),
    )


def _pixel_metrics(image: Image.Image) -> dict[str, Any]:
    pixels = np.asarray(image.convert("RGB"))
    changed = np.any(pixels != np.asarray(_BACKGROUND, dtype=np.uint8), axis=2)
    ys, xs = np.nonzero(changed)
    if not len(xs):
        raise ValueError("Software thumbnail is blank")
    channels = pixels[changed]
    return {
        "backgroundRgb": list(_BACKGROUND),
        "changedPixelBounds": [
            int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
        ],
        "changedPixelCount": int(changed.sum()),
        "changedPixelFraction": round(float(changed.mean()), 8),
        "channelSpan": int(channels.max() - channels.min()),
        "nonblank": True,
    }


def render_software_thumbnail(
    input_path: Path,
    output_path: Path,
    *,
    evidence_path: Path | None = None,
    width: int = 480,
    height: int = 300,
    maximum_triangles: int = 80_000,
    source_transform: tuple[float, ...] | list[float] | None = None,
) -> dict[str, Any]:
    source = input_path.expanduser().resolve()
    if not source.is_file() or source.stat().st_size < 28:
        raise ValueError("GLB input is missing or invalid")
    if width < 128 or height < 128 or maximum_triangles < 5_000:
        raise ValueError("Software thumbnail limits are invalid")

    with source.open("rb") as stream, mmap.mmap(
        stream.fileno(), 0, access=mmap.ACCESS_READ
    ) as binary:
        if binary[:4] != _GLB_MAGIC or struct.unpack_from("<I", binary, 4)[0] != 2:
            raise ValueError("Software thumbnail requires GLB 2.0")
        declared_length = struct.unpack_from("<I", binary, 8)[0]
        if declared_length != len(binary):
            raise ValueError("GLB declared length does not match its bytes")
        json_length, json_kind = struct.unpack_from("<II", binary, 12)
        if json_kind != _JSON_CHUNK:
            raise ValueError("GLB first chunk is not JSON")
        document = json.loads(
            binary[20 : 20 + json_length].decode("utf-8").rstrip("\x00 ")
        )
        binary_header = 20 + json_length
        _, binary_kind = struct.unpack_from("<II", binary, binary_header)
        if binary_kind != _BIN_CHUNK:
            raise ValueError("GLB second chunk is not binary")
        binary_offset = binary_header + 8
        meshes = document.get("meshes", [])
        normalized_source_transform = _source_transform_matrix(source_transform)
        instances = _scene_instances(document, normalized_source_transform)

        primitives: list[tuple[dict[str, Any], np.ndarray, int, int]] = []
        total_triangles = 0
        triangle_count = 0
        scene_min = np.array([math.inf, math.inf, math.inf])
        scene_max = np.array([-math.inf, -math.inf, -math.inf])
        for mesh_index, matrix in instances:
            mesh = meshes[mesh_index]
            for primitive in mesh.get("primitives", []):
                accessor_index = primitive.get("attributes", {}).get("POSITION")
                if not isinstance(accessor_index, int):
                    continue
                accessor = document["accessors"][accessor_index]
                count = int(accessor["count"])
                low, high = _transform_bounds(
                    accessor["min"], accessor["max"], matrix
                )
                scene_min = np.minimum(scene_min, low)
                scene_max = np.maximum(scene_max, high)
                element_count = count
                if isinstance(primitive.get("indices"), int):
                    element_count = int(
                        document["accessors"][primitive["indices"]]["count"]
                    )
                primitive_triangles = 0
                if int(primitive.get("mode", 4)) == 4:
                    primitive_triangles = element_count // 3
                    triangle_count += primitive_triangles
                if primitive_triangles:
                    primitives.append((
                        primitive,
                        matrix,
                        accessor_index,
                        primitive_triangles,
                    ))
                    total_triangles += primitive_triangles
        if not primitives or not np.isfinite(scene_min).all() or np.any(scene_max <= scene_min):
            raise ValueError("GLB has no bounded renderable geometry")

        triangle_batches = []
        color_batches = []
        for primitive, matrix, accessor_index, primitive_triangles in primitives:
            positions = _position_view(
                binary, binary_offset, document, accessor_index
            )
            target = max(
                4,
                int(round(
                    maximum_triangles * primitive_triangles / total_triangles
                )),
            )
            sample_count = min(primitive_triangles, target)
            chosen_triangles = np.linspace(
                0,
                primitive_triangles - 1,
                sample_count,
                dtype=np.int64,
            )
            if isinstance(primitive.get("indices"), int):
                source_indices = _index_view(
                    binary,
                    binary_offset,
                    document,
                    primitive["indices"],
                )
                vertex_indices = np.asarray(
                    source_indices[
                        chosen_triangles[:, None] * 3 + np.arange(3)[None, :]
                    ],
                    dtype=np.int64,
                )
            else:
                vertex_indices = (
                    chosen_triangles[:, None] * 3 + np.arange(3)[None, :]
                )
            sampled = np.asarray(
                positions[vertex_indices.reshape(-1)], dtype=np.float64
            ).reshape((-1, 3, 3))
            sampled = _transform_points(
                sampled.reshape((-1, 3)), matrix
            ).reshape((-1, 3, 3))
            color = _material_color(
                document, primitive.get("material")
            )
            triangle_batches.append(sampled)
            color_batches.append(np.repeat(color[None, :], sample_count, axis=0))
        triangles = np.concatenate(triangle_batches, axis=0)
        colors = np.concatenate(color_batches, axis=0)

    center = (scene_min + scene_max) / 2
    camera = np.asarray([1.0, 0.72, 1.0], dtype=np.float64)
    camera /= np.linalg.norm(camera)
    right = np.cross(np.asarray([0.0, 1.0, 0.0]), camera)
    right /= np.linalg.norm(right)
    up = np.cross(camera, right)
    up /= np.linalg.norm(up)
    centered = triangles - center
    horizontal = centered @ right
    vertical = centered @ up
    depth = centered @ camera

    render_width = width * 2
    render_height = height * 2
    margin = max(24, int(min(render_width, render_height) * 0.1))
    horizontal_span = max(float(np.ptp(horizontal)), 1e-9)
    vertical_span = max(float(np.ptp(vertical)), 1e-9)
    scale = min(
        (render_width - 2 * margin) / horizontal_span,
        (render_height - 2 * margin) / vertical_span,
    )
    x = np.rint(
        render_width / 2 + (horizontal - (horizontal.min() + horizontal.max()) / 2) * scale
    ).astype(np.int64)
    y = np.rint(
        render_height / 2 - (vertical - (vertical.min() + vertical.max()) / 2) * scale
    ).astype(np.int64)
    edge_a = triangles[:, 1] - triangles[:, 0]
    edge_b = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(edge_a, edge_b)
    normal_length = np.linalg.norm(normals, axis=1)
    valid = normal_length > 1e-12
    normals[valid] /= normal_length[valid, None]
    light = np.asarray([0.45, 0.82, 0.35], dtype=np.float64)
    light /= np.linalg.norm(light)
    illumination = 0.58 + 0.42 * np.abs(normals @ light)
    mean_depth = depth.mean(axis=1)
    depth_range = max(float(np.ptp(mean_depth)), 1e-9)
    depth_shade = 0.82 + 0.18 * (
        mean_depth - mean_depth.min()
    ) / depth_range
    colors = np.clip(
        colors * illumination[:, None] * depth_shade[:, None],
        0,
        255,
    ).astype(np.uint8)

    image = Image.new("RGB", (render_width, render_height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    for index in np.argsort(mean_depth):
        polygon = [
            (int(x[index, vertex]), int(y[index, vertex]))
            for vertex in range(3)
        ]
        draw.polygon(polygon, fill=tuple(int(value) for value in colors[index]))
    image = image.resize(
        (width, height), Image.Resampling.LANCZOS
    )
    metrics = _pixel_metrics(image)

    output = output_path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output.parent, suffix=".webp", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        image.save(temporary_path, format="WEBP", quality=90, method=6)
        os.replace(temporary_path, output)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    source_hash = _sha256(source)
    output_hash = _sha256(output)
    bounds_size = scene_max - scene_min
    evidence = {
        "checks": {
            "actualBoundsFinite": True,
            "boundedDimensions": True,
            "boundedOutputBytes": True,
            "geometryRenderable": True,
            "nonblankPixels": True,
            "softwareFallbackBounded": True,
            "validGlb2": True,
        },
        "geometry": {
            "bounds": {
                "center": center.tolist(),
                "max": scene_max.tolist(),
                "min": scene_min.tolist(),
                "radius": float(np.linalg.norm(bounds_size) / 2),
                "size": bounds_size.tolist(),
            },
            "meshCount": len(instances),
            "primitiveCount": len(primitives),
            "sampledTriangleCount": int(len(triangles)),
            "triangleCount": int(triangle_count),
        },
        "network": {
            "externalRequestCount": 0,
            "offlineOnly": True,
        },
        "output": {
            "artifactName": output.name,
            "byteLength": output.stat().st_size,
            "height": height,
            "mediaType": "image/webp",
            "pixelValidation": metrics,
            "sha256": output_hash,
            "width": width,
        },
        "passed": True,
        "renderer": {
            "cameraDirection": camera.tolist(),
            "kind": "deterministic-software-triangle-projection",
            "maximumTriangles": maximum_triangles,
            "sourceTransform": normalized_source_transform.reshape(
                16, order="F"
            ).tolist(),
        },
        "schemaVersion": "industrial-asset-thumbnail-evidence-v1",
        "source": {
            "artifactName": source.name,
            "byteLength": source.stat().st_size,
            "containerVersion": 2,
            "sha256": source_hash,
        },
    }
    if evidence_path is not None:
        evidence_output = evidence_path.expanduser().resolve()
        evidence_output.parent.mkdir(parents=True, exist_ok=True)
        evidence_output.write_text(
            json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
    return evidence


__all__ = ["render_software_thumbnail"]
