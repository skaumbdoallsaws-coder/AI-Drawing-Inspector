"""Deterministic validation and normalization for industrial web artifacts.

This module is intentionally limited to staged artifact candidates. It does not
publish catalog records, mutate source artifacts, or promote inferred geometry
to reviewed or verified engineering data.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
from typing import Any, Mapping, Sequence
import warnings

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from .schema_v1 import canonical_json_bytes


GLB_MAGIC = b"glTF"
GLB_JSON_CHUNK = b"JSON"
GLB_BINARY_CHUNK = b"BIN\x00"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
BMP_MAGIC = b"BM"
WEBP_RIFF_MAGIC = b"RIFF"
WEBP_FORMAT_MAGIC = b"WEBP"

DEFAULT_MAX_GLB_BYTES = 30 * 1024 * 1024
DEFAULT_MAX_POSITION_VERTICES = 5_000_000
DEFAULT_MAX_IMAGE_INPUT_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_IMAGE_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 20_000_000
DEFAULT_MAX_IMAGE_DIMENSION = 2048
DEFAULT_OVERVIEW_BYTES = 10 * 1024 * 1024
DEFAULT_OVERVIEW_TRIANGLES = 150_000
DEFAULT_BOUNDS_ABSOLUTE_TOLERANCE_METERS = 0.005
DEFAULT_BOUNDS_RELATIVE_TOLERANCE = 0.01

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOD_ID_RE = re.compile(r"^lod([0-9]+)$")
_EVIDENCE_STATUSES = {"authored", "derived", "inferred", "unknown"}
_COMPONENT_FORMATS = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class ArtifactValidationError(ValueError):
    """A fail-closed validation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GlbInspection:
    byte_length: int
    sha256: str
    declared_byte_length: int
    json_chunk_sha256: str
    binary_chunk_sha256: str
    binary_chunk_byte_length: int
    generator: str | None
    mesh_count: int
    primitive_count: int
    position_vertex_count: int
    triangle_count: int
    scene_triangle_count: int
    aabb: Mapping[str, Mapping[str, float]]

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "mediaType": "model/gltf-binary",
            "byteLength": self.byte_length,
            "sha256": self.sha256,
            "nonblank": self.scene_triangle_count > 0,
            "glbVersion": 2,
            "declaredByteLength": self.declared_byte_length,
            "jsonChunkSha256": self.json_chunk_sha256,
            "binaryChunkSha256": self.binary_chunk_sha256,
            "binaryChunkByteLength": self.binary_chunk_byte_length,
            "generator": self.generator,
            "meshCount": self.mesh_count,
            "primitiveCount": self.primitive_count,
            "positionVertexCount": self.position_vertex_count,
            "triangleCount": self.triangle_count,
            "sceneTriangleCount": self.scene_triangle_count,
            "aabb": _copy_aabb(self.aabb),
            "validation": {
                "structure": "glb_2_0_validated",
                "bounds": "finite_position_bytes_inspected",
                "byteIdentity": "exact_sha256_and_length",
            },
        }


@dataclass(frozen=True)
class NormalizedImageArtifact:
    data: bytes
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class RenderBundleCandidate:
    manifest: Mapping[str, Any]
    render_bundle_revision: str


def _read_bounded_bytes(
    source: bytes | bytearray | memoryview | Path | str,
    *,
    maximum_bytes: int,
    kind: str,
) -> tuple[bytes, str | None]:
    if maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be positive")
    claimed_suffix: str | None = None
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
    else:
        path = Path(source)
        claimed_suffix = path.suffix.lower() or None
        try:
            byte_length = path.stat().st_size
        except OSError as exc:
            raise ArtifactValidationError(
                f"{kind}_unreadable",
                f"{kind} artifact could not be inspected",
            ) from exc
        if byte_length > maximum_bytes:
            raise ArtifactValidationError(
                f"{kind}_oversized",
                f"{kind} artifact exceeds the {maximum_bytes}-byte limit",
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ArtifactValidationError(
                f"{kind}_unreadable",
                f"{kind} artifact could not be inspected",
            ) from exc
    if not data:
        raise ArtifactValidationError(
            f"{kind}_empty",
            f"{kind} artifact is empty",
        )
    if len(data) > maximum_bytes:
        raise ArtifactValidationError(
            f"{kind}_oversized",
            f"{kind} artifact exceeds the {maximum_bytes}-byte limit",
        )
    return data, claimed_suffix


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_expected_identity(
    data: bytes,
    *,
    expected_sha256: str | None,
    expected_byte_length: int | None,
    kind: str,
) -> None:
    if expected_byte_length is not None and len(data) != expected_byte_length:
        raise ArtifactValidationError(
            f"{kind}_byte_length_mismatch",
            f"{kind} byte length does not match its staged identity",
        )
    if expected_sha256 is not None:
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        if _sha256(data) != expected_sha256:
            raise ArtifactValidationError(
                f"{kind}_sha256_mismatch",
                f"{kind} SHA-256 does not match its staged identity",
            )


def _finite_number(value: Any, *, code: str, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(code, f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ArtifactValidationError(code, f"{label} must be finite")
    if abs(number) > 1_000_000:
        raise ArtifactValidationError(code, f"{label} exceeds coordinate bounds")
    return number


def _canonical_number(value: float, *, precision: int = 6) -> float:
    result = round(float(value), precision)
    return 0.0 if result == 0.0 else result


def _vector3(values: Sequence[Any], *, code: str, label: str) -> tuple[float, float, float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ArtifactValidationError(code, f"{label} must be a three-vector")
    if len(values) != 3:
        raise ArtifactValidationError(code, f"{label} must have three values")
    return tuple(
        _finite_number(item, code=code, label=f"{label}[{index}]")
        for index, item in enumerate(values)
    )  # type: ignore[return-value]


def _copy_aabb(
    aabb: Mapping[str, Mapping[str, float]],
    *,
    precision: int = 9,
) -> dict[str, dict[str, float]]:
    return {
        endpoint: {
            axis: _canonical_number(float(aabb[endpoint][axis]), precision=precision)
            for axis in ("x", "y", "z")
        }
        for endpoint in ("minimum", "maximum")
    }


def _union_bounds(
    current: tuple[list[float], list[float]] | None,
    minimum: Sequence[float],
    maximum: Sequence[float],
) -> tuple[list[float], list[float]]:
    if current is None:
        return [float(item) for item in minimum], [float(item) for item in maximum]
    return (
        [min(current[0][index], float(minimum[index])) for index in range(3)],
        [max(current[1][index], float(maximum[index])) for index in range(3)],
    )


def _identity_matrix() -> tuple[float, ...]:
    return (
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _multiply_matrices(
    left: Sequence[float],
    right: Sequence[float],
) -> tuple[float, ...]:
    return tuple(
        sum(
            left[column_inner * 4 + row] * right[column * 4 + column_inner]
            for column_inner in range(4)
        )
        for column in range(4)
        for row in range(4)
    )


def _node_matrix(node: Mapping[str, Any]) -> tuple[float, ...]:
    if "matrix" in node:
        values = node["matrix"]
        if not isinstance(values, list) or len(values) != 16:
            raise ArtifactValidationError(
                "glb_node_transform_invalid",
                "GLB node matrix must contain 16 values",
            )
        return tuple(
            _finite_number(
                value,
                code="glb_node_transform_invalid",
                label=f"node.matrix[{index}]",
            )
            for index, value in enumerate(values)
        )

    translation = _vector3(
        node.get("translation", [0.0, 0.0, 0.0]),
        code="glb_node_transform_invalid",
        label="node.translation",
    )
    scale = _vector3(
        node.get("scale", [1.0, 1.0, 1.0]),
        code="glb_node_transform_invalid",
        label="node.scale",
    )
    rotation = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    if not isinstance(rotation, list) or len(rotation) != 4:
        raise ArtifactValidationError(
            "glb_node_transform_invalid",
            "GLB node rotation must contain four values",
        )
    x, y, z, w = (
        _finite_number(
            value,
            code="glb_node_transform_invalid",
            label=f"node.rotation[{index}]",
        )
        for index, value in enumerate(rotation)
    )
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 1e-12:
        raise ArtifactValidationError(
            "glb_node_transform_invalid",
            "GLB node quaternion has zero length",
        )
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    m00 = 1.0 - 2.0 * (y * y + z * z)
    m01 = 2.0 * (x * y - z * w)
    m02 = 2.0 * (x * z + y * w)
    m10 = 2.0 * (x * y + z * w)
    m11 = 1.0 - 2.0 * (x * x + z * z)
    m12 = 2.0 * (y * z - x * w)
    m20 = 2.0 * (x * z - y * w)
    m21 = 2.0 * (y * z + x * w)
    m22 = 1.0 - 2.0 * (x * x + y * y)
    sx, sy, sz = scale
    return (
        m00 * sx,
        m10 * sx,
        m20 * sx,
        0.0,
        m01 * sy,
        m11 * sy,
        m21 * sy,
        0.0,
        m02 * sz,
        m12 * sz,
        m22 * sz,
        0.0,
        translation[0],
        translation[1],
        translation[2],
        1.0,
    )


def _transform_point(
    matrix: Sequence[float],
    point: Sequence[float],
) -> tuple[float, float, float]:
    x, y, z = point
    result = (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )
    w = matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15]
    if not math.isfinite(w) or abs(w) <= 1e-12:
        raise ArtifactValidationError(
            "geometry_transform_invalid",
            "Geometry transform produced an invalid homogeneous coordinate",
        )
    transformed = tuple(value / w for value in result)
    if not all(math.isfinite(value) and abs(value) <= 1_000_000 for value in transformed):
        raise ArtifactValidationError(
            "geometry_transform_invalid",
            "Geometry transform produced non-finite or excessive coordinates",
        )
    return transformed  # type: ignore[return-value]


def _transformed_aabb(
    minimum: Sequence[float],
    maximum: Sequence[float],
    matrix: Sequence[float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    bounds: tuple[list[float], list[float]] | None = None
    for x in (minimum[0], maximum[0]):
        for y in (minimum[1], maximum[1]):
            for z in (minimum[2], maximum[2]):
                point = _transform_point(matrix, (x, y, z))
                bounds = _union_bounds(bounds, point, point)
    assert bounds is not None
    return tuple(bounds[0]), tuple(bounds[1])  # type: ignore[return-value]


def _parse_glb_chunks(data: bytes) -> tuple[Mapping[str, Any], bytes, bytes]:
    if len(data) < 20:
        raise ArtifactValidationError("glb_truncated", "GLB header or JSON chunk is truncated")
    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    if magic != GLB_MAGIC:
        raise ArtifactValidationError("glb_magic_invalid", "Artifact is not a GLB file")
    if version != 2:
        raise ArtifactValidationError("glb_version_unsupported", "Only GLB 2.0 is supported")
    if declared_length != len(data):
        raise ArtifactValidationError(
            "glb_length_mismatch",
            "GLB declared byte length does not match the exact artifact bytes",
        )

    offset = 12
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ArtifactValidationError("glb_chunk_truncated", "GLB chunk header is truncated")
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        end = offset + chunk_length
        if chunk_length % 4 != 0 or end > len(data):
            raise ArtifactValidationError(
                "glb_chunk_invalid",
                "GLB chunk length is unaligned or exceeds the artifact",
            )
        chunks.append((chunk_type, data[offset:end]))
        offset = end
    if not chunks or chunks[0][0] != GLB_JSON_CHUNK:
        raise ArtifactValidationError(
            "glb_json_chunk_missing",
            "GLB must begin with exactly one JSON chunk",
        )
    if sum(chunk_type == GLB_JSON_CHUNK for chunk_type, _ in chunks) != 1:
        raise ArtifactValidationError(
            "glb_json_chunk_invalid",
            "GLB must contain exactly one JSON chunk",
        )
    if sum(chunk_type == GLB_BINARY_CHUNK for chunk_type, _ in chunks) > 1:
        raise ArtifactValidationError(
            "glb_binary_chunk_invalid",
            "GLB may contain at most one binary chunk",
        )
    json_bytes = chunks[0][1]
    binary_bytes = next(
        (payload for chunk_type, payload in chunks if chunk_type == GLB_BINARY_CHUNK),
        b"",
    )
    try:
        document = json.loads(json_bytes.rstrip(b" \t\r\n\x00").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(
            "glb_json_invalid",
            "GLB JSON chunk is not valid UTF-8 JSON",
        ) from exc
    if not isinstance(document, dict):
        raise ArtifactValidationError("glb_json_invalid", "GLB JSON root must be an object")
    asset = document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise ArtifactValidationError(
            "glb_asset_version_invalid",
            "GLB asset.version must be exactly 2.0",
        )
    return document, json_bytes, binary_bytes


def _validate_glb_buffer_structure(
    document: Mapping[str, Any],
    binary_bytes: bytes,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    buffers = document.get("buffers", [])
    buffer_views = document.get("bufferViews", [])
    accessors = document.get("accessors", [])
    if not isinstance(buffers, list) or len(buffers) != 1:
        raise ArtifactValidationError(
            "glb_buffer_invalid",
            "A self-contained facility GLB must contain exactly one buffer",
        )
    if not isinstance(buffer_views, list) or not isinstance(accessors, list):
        raise ArtifactValidationError(
            "glb_structure_invalid",
            "GLB bufferViews and accessors must be arrays",
        )
    buffer = buffers[0]
    if not isinstance(buffer, dict) or "uri" in buffer:
        raise ArtifactValidationError(
            "glb_external_resource_forbidden",
            "Facility GLBs must embed their binary buffer",
        )
    buffer_length = buffer.get("byteLength")
    if (
        isinstance(buffer_length, bool)
        or not isinstance(buffer_length, int)
        or buffer_length < 0
        or buffer_length > len(binary_bytes)
        or len(binary_bytes) - buffer_length > 3
    ):
        raise ArtifactValidationError(
            "glb_buffer_length_invalid",
            "GLB binary chunk does not match buffer byteLength and padding rules",
        )
    for image in document.get("images", []):
        if isinstance(image, dict) and "uri" in image:
            raise ArtifactValidationError(
                "glb_external_resource_forbidden",
                "Facility GLBs may not depend on external image URIs",
            )
    normalized_views: list[Mapping[str, Any]] = []
    for index, view in enumerate(buffer_views):
        if not isinstance(view, dict):
            raise ArtifactValidationError(
                "glb_buffer_view_invalid",
                f"GLB bufferView {index} must be an object",
            )
        if view.get("buffer", 0) != 0:
            raise ArtifactValidationError(
                "glb_buffer_view_invalid",
                f"GLB bufferView {index} references an unavailable buffer",
            )
        start = view.get("byteOffset", 0)
        length = view.get("byteLength")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or start < 0
            or isinstance(length, bool)
            or not isinstance(length, int)
            or length < 0
            or start + length > buffer_length
        ):
            raise ArtifactValidationError(
                "glb_buffer_view_invalid",
                f"GLB bufferView {index} exceeds the embedded buffer",
            )
        stride = view.get("byteStride")
        if stride is not None and (
            isinstance(stride, bool)
            or not isinstance(stride, int)
            or stride < 4
            or stride > 252
            or stride % 4 != 0
        ):
            raise ArtifactValidationError(
                "glb_buffer_view_invalid",
                f"GLB bufferView {index} has an invalid byteStride",
            )
        normalized_views.append(view)
    normalized_accessors: list[Mapping[str, Any]] = []
    for index, accessor in enumerate(accessors):
        if not isinstance(accessor, dict):
            raise ArtifactValidationError(
                "glb_accessor_invalid",
                f"GLB accessor {index} must be an object",
            )
        component_type = accessor.get("componentType")
        accessor_type = accessor.get("type")
        count = accessor.get("count")
        if (
            component_type not in _COMPONENT_FORMATS
            or accessor_type not in _TYPE_COMPONENTS
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise ArtifactValidationError(
                "glb_accessor_invalid",
                f"GLB accessor {index} has an invalid component/type/count",
            )
        if "sparse" in accessor:
            raise ArtifactValidationError(
                "glb_sparse_accessor_unsupported",
                "Sparse GLB accessors are not supported for facility artifacts",
            )
        view_index = accessor.get("bufferView")
        if (
            isinstance(view_index, bool)
            or not isinstance(view_index, int)
            or not 0 <= view_index < len(normalized_views)
        ):
            raise ArtifactValidationError(
                "glb_accessor_invalid",
                f"GLB accessor {index} does not reference a valid bufferView",
            )
        normalized_accessors.append(accessor)
    return [buffer], normalized_views, normalized_accessors


def _read_position_accessor(
    accessor_index: int,
    *,
    accessors: Sequence[Mapping[str, Any]],
    buffer_views: Sequence[Mapping[str, Any]],
    binary_bytes: bytes,
    maximum_vertices: int,
) -> tuple[tuple[float, float, float], tuple[float, float, float], int]:
    if not 0 <= accessor_index < len(accessors):
        raise ArtifactValidationError(
            "glb_position_accessor_invalid",
            "Mesh POSITION attribute references an unavailable accessor",
        )
    accessor = accessors[accessor_index]
    if (
        accessor.get("componentType") != 5126
        or accessor.get("type") != "VEC3"
        or accessor.get("normalized", False)
    ):
        raise ArtifactValidationError(
            "glb_position_accessor_invalid",
            "Mesh POSITION data must be non-normalized FLOAT VEC3",
        )
    count = int(accessor["count"])
    if count <= 0 or count > maximum_vertices:
        raise ArtifactValidationError(
            "glb_position_count_invalid",
            "Mesh POSITION accessor count is empty or exceeds the inspection limit",
        )
    view = buffer_views[int(accessor["bufferView"])]
    stride = int(view.get("byteStride", 12))
    if stride < 12:
        raise ArtifactValidationError(
            "glb_position_accessor_invalid",
            "Mesh POSITION byteStride is too small",
        )
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    last_end = start + (count - 1) * stride + 12
    view_end = int(view.get("byteOffset", 0)) + int(view["byteLength"])
    if start < int(view.get("byteOffset", 0)) or last_end > view_end:
        raise ArtifactValidationError(
            "glb_position_accessor_invalid",
            "Mesh POSITION accessor exceeds its bufferView",
        )
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    for index in range(count):
        values = struct.unpack_from("<fff", binary_bytes, start + index * stride)
        if not all(math.isfinite(value) and abs(value) <= 1_000_000 for value in values):
            raise ArtifactValidationError(
                "glb_position_nonfinite",
                "Mesh POSITION bytes contain non-finite or excessive coordinates",
            )
        for axis in range(3):
            minimum[axis] = min(minimum[axis], values[axis])
            maximum[axis] = max(maximum[axis], values[axis])
    declared_minimum = _vector3(
        accessor.get("min", []),
        code="glb_position_bounds_missing",
        label="POSITION.min",
    )
    declared_maximum = _vector3(
        accessor.get("max", []),
        code="glb_position_bounds_missing",
        label="POSITION.max",
    )
    for axis in range(3):
        tolerance = max(1e-6, abs(maximum[axis] - minimum[axis]) * 1e-6)
        if (
            abs(declared_minimum[axis] - minimum[axis]) > tolerance
            or abs(declared_maximum[axis] - maximum[axis]) > tolerance
        ):
            raise ArtifactValidationError(
                "glb_position_bounds_mismatch",
                "Declared POSITION bounds do not match the exact vertex bytes",
            )
    return tuple(minimum), tuple(maximum), count  # type: ignore[return-value]


def _primitive_triangle_count(
    primitive: Mapping[str, Any],
    *,
    accessors: Sequence[Mapping[str, Any]],
    position_count: int,
) -> int:
    mode = primitive.get("mode", 4)
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 6:
        raise ArtifactValidationError("glb_primitive_invalid", "GLB primitive mode is invalid")
    count = position_count
    if "indices" in primitive:
        index = primitive["indices"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(accessors):
            raise ArtifactValidationError(
                "glb_index_accessor_invalid",
                "GLB primitive indices reference an unavailable accessor",
            )
        index_accessor = accessors[index]
        if (
            index_accessor.get("type") != "SCALAR"
            or index_accessor.get("componentType") not in {5121, 5123, 5125}
        ):
            raise ArtifactValidationError(
                "glb_index_accessor_invalid",
                "GLB indices must use an unsigned SCALAR accessor",
            )
        count = int(index_accessor["count"])
    if mode == 4:
        if count % 3 != 0:
            raise ArtifactValidationError(
                "glb_triangle_count_invalid",
                "Triangle primitive index/vertex count is not divisible by three",
            )
        return count // 3
    if mode in {5, 6}:
        return max(0, count - 2)
    return 0


def inspect_glb(
    source: bytes | bytearray | memoryview | Path | str,
    *,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    maximum_bytes: int = DEFAULT_MAX_GLB_BYTES,
    maximum_position_vertices: int = DEFAULT_MAX_POSITION_VERTICES,
) -> GlbInspection:
    """Inspect exact GLB bytes and validate static, self-contained GLB 2.0."""

    data, _ = _read_bounded_bytes(
        source,
        maximum_bytes=maximum_bytes,
        kind="glb",
    )
    _require_expected_identity(
        data,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
        kind="glb",
    )
    document, json_bytes, binary_bytes = _parse_glb_chunks(data)
    _, buffer_views, accessors = _validate_glb_buffer_structure(
        document,
        binary_bytes,
    )
    meshes = document.get("meshes", [])
    nodes = document.get("nodes", [])
    scenes = document.get("scenes", [])
    if not isinstance(meshes, list) or not meshes:
        raise ArtifactValidationError("glb_mesh_missing", "GLB contains no meshes")
    if not isinstance(nodes, list) or not isinstance(scenes, list) or not scenes:
        raise ArtifactValidationError(
            "glb_scene_missing",
            "GLB must contain a renderable scene and nodes",
        )
    if "skins" in document or "animations" in document:
        raise ArtifactValidationError(
            "glb_dynamic_geometry_unsupported",
            "Facility render artifacts must use static geometry",
        )

    mesh_bounds: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    mesh_triangles: list[int] = []
    primitive_count = 0
    vertex_count = 0
    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives"), list):
            raise ArtifactValidationError(
                "glb_mesh_invalid",
                f"GLB mesh {mesh_index} has no primitive array",
            )
        bounds: tuple[list[float], list[float]] | None = None
        triangles = 0
        for primitive in mesh["primitives"]:
            if not isinstance(primitive, dict):
                raise ArtifactValidationError(
                    "glb_primitive_invalid",
                    "GLB mesh primitive must be an object",
                )
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise ArtifactValidationError(
                    "glb_position_missing",
                    "Every facility mesh primitive must expose POSITION data",
                )
            if "targets" in primitive:
                raise ArtifactValidationError(
                    "glb_dynamic_geometry_unsupported",
                    "Morph targets are not supported for facility render artifacts",
                )
            minimum, maximum, count = _read_position_accessor(
                attributes["POSITION"],
                accessors=accessors,
                buffer_views=buffer_views,
                binary_bytes=binary_bytes,
                maximum_vertices=maximum_position_vertices,
            )
            bounds = _union_bounds(bounds, minimum, maximum)
            triangles += _primitive_triangle_count(
                primitive,
                accessors=accessors,
                position_count=count,
            )
            vertex_count += count
            primitive_count += 1
        if bounds is None:
            raise ArtifactValidationError("glb_mesh_empty", "GLB mesh has no geometry")
        mesh_bounds.append((tuple(bounds[0]), tuple(bounds[1])))
        mesh_triangles.append(triangles)

    active_scene_index = document.get("scene", 0)
    if (
        isinstance(active_scene_index, bool)
        or not isinstance(active_scene_index, int)
        or not 0 <= active_scene_index < len(scenes)
        or not isinstance(scenes[active_scene_index], dict)
    ):
        raise ArtifactValidationError("glb_scene_invalid", "GLB active scene is invalid")
    root_nodes = scenes[active_scene_index].get("nodes", [])
    if not isinstance(root_nodes, list) or not root_nodes:
        raise ArtifactValidationError("glb_scene_empty", "GLB active scene contains no nodes")

    scene_bounds: tuple[list[float], list[float]] | None = None
    scene_triangle_count = 0

    def visit(
        node_index: Any,
        parent_matrix: Sequence[float],
        ancestors: frozenset[int],
        depth: int,
    ) -> None:
        nonlocal scene_bounds, scene_triangle_count
        if depth > 256:
            raise ArtifactValidationError(
                "glb_node_depth_exceeded",
                "GLB node hierarchy exceeds the supported depth",
            )
        if (
            isinstance(node_index, bool)
            or not isinstance(node_index, int)
            or not 0 <= node_index < len(nodes)
            or not isinstance(nodes[node_index], dict)
        ):
            raise ArtifactValidationError(
                "glb_node_invalid",
                "GLB scene references an unavailable node",
            )
        if node_index in ancestors:
            raise ArtifactValidationError("glb_node_cycle", "GLB node hierarchy is cyclic")
        node = nodes[node_index]
        world = _multiply_matrices(parent_matrix, _node_matrix(node))
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            if (
                isinstance(mesh_index, bool)
                or not isinstance(mesh_index, int)
                or not 0 <= mesh_index < len(mesh_bounds)
            ):
                raise ArtifactValidationError(
                    "glb_mesh_reference_invalid",
                    "GLB node references an unavailable mesh",
                )
            minimum, maximum = _transformed_aabb(
                mesh_bounds[mesh_index][0],
                mesh_bounds[mesh_index][1],
                world,
            )
            scene_bounds = _union_bounds(scene_bounds, minimum, maximum)
            scene_triangle_count += mesh_triangles[mesh_index]
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ArtifactValidationError(
                "glb_node_invalid",
                "GLB node children must be an array",
            )
        next_ancestors = ancestors | {node_index}
        for child in children:
            visit(child, world, next_ancestors, depth + 1)

    for root in root_nodes:
        visit(root, _identity_matrix(), frozenset(), 0)
    if scene_bounds is None:
        raise ArtifactValidationError(
            "glb_scene_geometry_missing",
            "GLB active scene does not reference visible mesh geometry",
        )
    minimum, maximum = scene_bounds
    if any(maximum[index] <= minimum[index] for index in range(3)):
        raise ArtifactValidationError(
            "glb_bounds_degenerate",
            "GLB scene bounds must have positive extent on every axis",
        )
    asset = document["asset"]
    generator = asset.get("generator")
    if generator is not None and not isinstance(generator, str):
        raise ArtifactValidationError(
            "glb_generator_invalid",
            "GLB asset.generator must be a string when present",
        )
    return GlbInspection(
        byte_length=len(data),
        sha256=_sha256(data),
        declared_byte_length=struct.unpack_from("<I", data, 8)[0],
        json_chunk_sha256=_sha256(json_bytes),
        binary_chunk_sha256=_sha256(binary_bytes),
        binary_chunk_byte_length=len(binary_bytes),
        generator=generator,
        mesh_count=len(meshes),
        primitive_count=primitive_count,
        position_vertex_count=vertex_count,
        triangle_count=sum(mesh_triangles),
        scene_triangle_count=scene_triangle_count,
        aabb={
            "minimum": dict(zip(("x", "y", "z"), minimum)),
            "maximum": dict(zip(("x", "y", "z"), maximum)),
        },
    )


def _extract_source_bounds(
    extractor_bounding_box: Mapping[str, Any],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not isinstance(extractor_bounding_box, Mapping):
        raise ArtifactValidationError(
            "extractor_bounds_invalid",
            "Extractor bounding box must be an object",
        )
    minimum = tuple(
        _finite_number(
            extractor_bounding_box.get(f"min{axis.upper()}"),
            code="extractor_bounds_invalid",
            label=f"boundingBox.min{axis.upper()}",
        )
        for axis in ("x", "y", "z")
    )
    maximum = tuple(
        _finite_number(
            extractor_bounding_box.get(f"max{axis.upper()}"),
            code="extractor_bounds_invalid",
            label=f"boundingBox.max{axis.upper()}",
        )
        for axis in ("x", "y", "z")
    )
    if any(maximum[index] <= minimum[index] for index in range(3)):
        raise ArtifactValidationError(
            "extractor_bounds_degenerate",
            "Extractor bounding box must have positive extent on every axis",
        )
    return minimum, maximum  # type: ignore[return-value]


def derive_geometry_candidates(
    extractor_bounding_box: Mapping[str, Any],
    *,
    evidence_refs: Sequence[str],
    source_coordinate_units: str = "m",
    source_up_axis: str = "+Y",
    source_to_canonical: Sequence[float] | None = None,
    transform_evidence_status: str | None = None,
    precision: int = 6,
) -> dict[str, Any]:
    """Derive review-required placement candidates from trusted SI bounds."""

    if source_coordinate_units != "m":
        raise ArtifactValidationError(
            "extractor_units_not_si",
            "Geometry candidates require extractor coordinates in SI meters",
        )
    if source_up_axis != "+Y":
        raise ArtifactValidationError(
            "extractor_up_axis_unresolved",
            "A reviewed source-to-canonical transform is required for non-+Y sources",
        )
    evidence = tuple(dict.fromkeys(str(item) for item in evidence_refs))
    if not evidence or any(
        not item or not item.isascii() or len(item) > 128 for item in evidence
    ):
        raise ValueError("evidence_refs must contain non-empty ASCII identifiers")
    source_minimum, source_maximum = _extract_source_bounds(extractor_bounding_box)
    automatic_transform = source_to_canonical is None
    if automatic_transform:
        center_x = (source_minimum[0] + source_maximum[0]) / 2.0
        center_z = (source_minimum[2] + source_maximum[2]) / 2.0
        matrix = list(_identity_matrix())
        matrix[12] = -center_x
        matrix[13] = -source_minimum[1]
        matrix[14] = -center_z
        transform_status = "inferred"
    else:
        if len(source_to_canonical) != 16:
            raise ArtifactValidationError(
                "source_transform_invalid",
                "source_to_canonical must contain 16 column-major values",
            )
        matrix = [
            _finite_number(
                value,
                code="source_transform_invalid",
                label=f"sourceToCanonical[{index}]",
            )
            for index, value in enumerate(source_to_canonical)
        ]
        transform_status = transform_evidence_status or "derived"
    if transform_status not in _EVIDENCE_STATUSES:
        raise ValueError("transform_evidence_status is invalid")

    canonical_minimum, canonical_maximum = _transformed_aabb(
        source_minimum,
        source_maximum,
        matrix,
    )
    source_floor_center = (
        (source_minimum[0] + source_maximum[0]) / 2.0,
        source_minimum[1],
        (source_minimum[2] + source_maximum[2]) / 2.0,
    )
    floor_anchor = _transform_point(matrix, source_floor_center)
    minimum = {
        axis: _canonical_number(canonical_minimum[index], precision=precision)
        for index, axis in enumerate(("x", "y", "z"))
    }
    maximum = {
        axis: _canonical_number(canonical_maximum[index], precision=precision)
        for index, axis in enumerate(("x", "y", "z"))
    }
    anchor = {
        axis: _canonical_number(floor_anchor[index], precision=precision)
        for index, axis in enumerate(("x", "y", "z"))
    }
    footprint = [
        {"x": minimum["x"], "z": minimum["z"]},
        {"x": maximum["x"], "z": minimum["z"]},
        {"x": maximum["x"], "z": maximum["z"]},
        {"x": minimum["x"], "z": maximum["z"]},
    ]
    signed_area = 0.5 * sum(
        footprint[index]["x"] * footprint[(index + 1) % 4]["z"]
        - footprint[(index + 1) % 4]["x"] * footprint[index]["z"]
        for index in range(4)
    )
    if signed_area <= 0:
        raise AssertionError("canonical footprint generation must be counter-clockwise")
    center = {
        axis: _canonical_number(
            (minimum[axis] + maximum[axis]) / 2.0,
            precision=precision,
        )
        for axis in ("x", "y", "z")
    }
    half_extents = {
        axis: _canonical_number(
            (maximum[axis] - minimum[axis]) / 2.0,
            precision=precision,
        )
        for axis in ("x", "y", "z")
    }
    source_bounds_record = {
        "minimum": dict(zip(("x", "y", "z"), source_minimum)),
        "maximum": dict(zip(("x", "y", "z"), source_maximum)),
    }
    candidate_basis = {
        "claimStatus": "candidate",
        "verified": False,
        "requiresReview": True,
        "evidence": list(evidence),
    }
    return {
        "schemaVersion": 1,
        "recordKind": "industrial_asset_geometry_candidates",
        "authorityBoundary": {
            "placementGeometryOnly": True,
            "safetyAuthority": False,
            "clearanceAuthority": False,
            "floorLoadAuthority": False,
        },
        "sourceBasis": {
            "kind": "trusted_extractor_si_aabb",
            "coordinateUnits": "m",
            "sourceUpAxis": source_up_axis,
            "aabb": _copy_aabb(source_bounds_record),
            "evidenceStatus": "derived",
            "evidence": list(evidence),
            "verified": False,
        },
        "sourceToCanonicalCandidate": {
            **candidate_basis,
            "value": [_canonical_number(value, precision=precision) for value in matrix],
            "evidenceStatus": transform_status,
            "method": (
                "center_xz_and_translate_minimum_y_to_zero"
                if automatic_transform
                else "caller_supplied_transform"
            ),
        },
        "canonicalAabbCandidate": {
            **candidate_basis,
            "value": {"minimum": minimum, "maximum": maximum},
            "evidenceStatus": "derived",
        },
        "floorAnchorCandidate": {
            **candidate_basis,
            "value": anchor,
            "evidenceStatus": "inferred" if automatic_transform else transform_status,
            "basis": "minimum_y_support_datum",
        },
        "footprintCandidate": {
            **candidate_basis,
            "value": footprint,
            "winding": "counter_clockwise_xz",
            "signedAreaSquareMeters": _canonical_number(
                signed_area,
                precision=precision,
            ),
            "evidenceStatus": "derived",
            "basis": "conservative_aabb_xz_projection",
        },
        "heightIntervalCandidate": {
            **candidate_basis,
            "value": {
                "minimumY": minimum["y"],
                "maximumY": maximum["y"],
            },
            "evidenceStatus": "derived",
        },
        "collisionProxyCandidate": {
            **candidate_basis,
            "model": "compound_box",
            "value": {
                "boxes": [
                    {
                        "boxId": "box-main",
                        "center": center,
                        "halfExtents": half_extents,
                    }
                ],
                "verticalInterval": {
                    "minimumY": minimum["y"],
                    "maximumY": maximum["y"],
                },
            },
            "evidenceStatus": "derived",
            "basis": "conservative_extractor_aabb",
        },
    }


def build_aabb_proxy_glb(
    aabb: Mapping[str, Mapping[str, Any]],
) -> bytes:
    """Build a deterministic, lightweight GLB box for overview rendering.

    The proxy preserves the exact supplied bounds. It is render geometry only;
    callers must not treat it as collision, clearance, or safety authority.
    """

    minimum, maximum = _extract_source_bounds(
        {
            "minX": aabb.get("minimum", {}).get("x"),
            "minY": aabb.get("minimum", {}).get("y"),
            "minZ": aabb.get("minimum", {}).get("z"),
            "maxX": aabb.get("maximum", {}).get("x"),
            "maxY": aabb.get("maximum", {}).get("y"),
            "maxZ": aabb.get("maximum", {}).get("z"),
        }
    )
    min_x, min_y, min_z = minimum
    max_x, max_y, max_z = maximum
    positions = (
        (min_x, min_y, min_z),
        (max_x, min_y, min_z),
        (max_x, max_y, min_z),
        (min_x, max_y, min_z),
        (min_x, min_y, max_z),
        (max_x, min_y, max_z),
        (max_x, max_y, max_z),
        (min_x, max_y, max_z),
    )
    indices = (
        0, 2, 1, 0, 3, 2,
        4, 5, 6, 4, 6, 7,
        0, 1, 5, 0, 5, 4,
        3, 7, 6, 3, 6, 2,
        0, 4, 7, 0, 7, 3,
        1, 2, 6, 1, 6, 5,
    )
    position_bytes = b"".join(
        struct.pack("<fff", *point) for point in positions
    )
    index_bytes = struct.pack("<" + "H" * len(indices), *indices)
    binary_bytes = position_bytes + index_bytes
    while len(binary_bytes) % 4:
        binary_bytes += b"\x00"
    document = {
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "max": list(maximum),
                "min": list(minimum),
                "type": "VEC3",
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": len(indices),
                "max": [max(indices)],
                "min": [min(indices)],
                "type": "SCALAR",
            },
        ],
        "asset": {
            "generator": "InspectorPro industrial AABB proxy v1",
            "version": "2.0",
        },
        "bufferViews": [
            {
                "buffer": 0,
                "byteLength": len(position_bytes),
                "byteOffset": 0,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteLength": len(index_bytes),
                "byteOffset": len(position_bytes),
                "target": 34963,
            },
        ],
        "buffers": [{"byteLength": len(binary_bytes)}],
        "meshes": [
            {
                "name": "overview-bounds",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": 4,
                    }
                ],
            }
        ],
        "nodes": [{"mesh": 0, "name": "overview-bounds"}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
    }
    json_bytes = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary_bytes)
    return (
        struct.pack("<4sII", GLB_MAGIC, 2, total_length)
        + struct.pack("<I4s", len(json_bytes), GLB_JSON_CHUNK)
        + json_bytes
        + struct.pack("<I4s", len(binary_bytes), GLB_BINARY_CHUNK)
        + binary_bytes
    )


def detect_image_format(data: bytes) -> str:
    """Identify supported image payloads by magic bytes, never extension."""

    if data.startswith(PNG_MAGIC):
        return "PNG"
    if data.startswith(BMP_MAGIC):
        return "BMP"
    if data.startswith(JPEG_MAGIC):
        return "JPEG"
    if (
        len(data) >= 12
        and data.startswith(WEBP_RIFF_MAGIC)
        and data[8:12] == WEBP_FORMAT_MAGIC
    ):
        return "WEBP"
    raise ArtifactValidationError(
        "image_format_unsupported",
        "Image payload is not a supported PNG, BMP, JPEG, or WebP",
    )


def _image_nonblank_metrics(image: Image.Image) -> dict[str, Any]:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    alpha_extrema = alpha.getextrema()
    if alpha_extrema == (0, 0):
        raise ArtifactValidationError(
            "image_blank",
            "Image is fully transparent",
        )
    visible = Image.new("RGB", rgba.size, (255, 255, 255))
    visible.paste(rgba.convert("RGB"), mask=alpha)
    statistics = ImageStat.Stat(visible)
    maximum_variance = max(float(value) for value in statistics.var)
    extrema = visible.getextrema()
    channel_range = max(high - low for low, high in extrema)
    if channel_range <= 1 or maximum_variance < 0.5:
        raise ArtifactValidationError(
            "image_blank",
            "Image has insufficient visible variation",
        )
    return {
        "maximumChannelRange": int(channel_range),
        "maximumChannelVariance": round(maximum_variance, 6),
        "alphaExtrema": [int(alpha_extrema[0]), int(alpha_extrema[1])],
    }


def normalize_web_image(
    source: bytes | bytearray | memoryview | Path | str,
    *,
    output_format: str = "WEBP",
    claimed_suffix: str | None = None,
    maximum_input_bytes: int = DEFAULT_MAX_IMAGE_INPUT_BYTES,
    maximum_output_bytes: int = DEFAULT_MAX_IMAGE_OUTPUT_BYTES,
    maximum_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
    maximum_dimension: int = DEFAULT_MAX_IMAGE_DIMENSION,
) -> NormalizedImageArtifact:
    """Decode, validate, resize, and encode a deterministic web image."""

    data, path_suffix = _read_bounded_bytes(
        source,
        maximum_bytes=maximum_input_bytes,
        kind="image",
    )
    _require_expected_identity(
        data,
        expected_sha256=None,
        expected_byte_length=None,
        kind="image",
    )
    detected_format = detect_image_format(data)
    suffix = (claimed_suffix or path_suffix or "").lower()
    suffix_format = {
        ".png": "PNG",
        ".bmp": "BMP",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".webp": "WEBP",
    }.get(suffix)
    findings: list[dict[str, Any]] = []
    if suffix and suffix_format != detected_format:
        findings.append(
            {
                "code": "image_extension_mismatch",
                "severity": "warning",
                "message": (
                    f"Claimed {suffix or 'unknown'} extension contains "
                    f"{detected_format} bytes"
                ),
            }
        )
    normalized_format = output_format.upper()
    if normalized_format not in {"PNG", "WEBP"}:
        raise ValueError("output_format must be PNG or WEBP")
    if maximum_pixels <= 0 or maximum_dimension <= 0 or maximum_output_bytes <= 0:
        raise ValueError("image limits must be positive")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != detected_format:
                    raise ArtifactValidationError(
                        "image_decoder_mismatch",
                        "Decoded image format disagrees with its magic bytes",
                    )
                width, height = probe.size
                if width <= 0 or height <= 0 or width * height > maximum_pixels:
                    raise ArtifactValidationError(
                        "image_dimensions_oversized",
                        "Image dimensions exceed the configured pixel budget",
                    )
                if getattr(probe, "n_frames", 1) != 1:
                    raise ArtifactValidationError(
                        "image_animation_unsupported",
                        "Animated images are not supported for asset thumbnails",
                    )
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.load()
                image = ImageOps.exif_transpose(decoded).copy()
    except ArtifactValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ArtifactValidationError(
            "image_corrupt",
            "Image could not be decoded safely",
        ) from exc

    source_metrics = _image_nonblank_metrics(image)
    original_size = image.size
    if max(image.size) > maximum_dimension:
        image.thumbnail(
            (maximum_dimension, maximum_dimension),
            Image.Resampling.LANCZOS,
            reducing_gap=3.0,
        )
    if "A" in image.getbands():
        output_image = image.convert("RGBA")
    else:
        output_image = image.convert("RGB")
    output = io.BytesIO()
    try:
        if normalized_format == "WEBP":
            output_image.save(
                output,
                format="WEBP",
                lossless=True,
                method=6,
                exact=True,
            )
            media_type = "image/webp"
        else:
            output_image.save(
                output,
                format="PNG",
                compress_level=9,
                optimize=False,
            )
            media_type = "image/png"
    except OSError as exc:
        raise ArtifactValidationError(
            "image_encode_failed",
            "Image could not be encoded as a web artifact",
        ) from exc
    normalized = output.getvalue()
    if len(normalized) > maximum_output_bytes:
        raise ArtifactValidationError(
            "image_output_oversized",
            "Normalized image exceeds the output byte budget",
        )
    if detect_image_format(normalized) != normalized_format:
        raise ArtifactValidationError(
            "image_output_invalid",
            "Normalized image magic bytes do not match its media type",
        )
    try:
        with Image.open(io.BytesIO(normalized)) as check:
            check.load()
            normalized_metrics = _image_nonblank_metrics(check)
            normalized_size = check.size
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ArtifactValidationError(
            "image_output_invalid",
            "Normalized image failed validation",
        ) from exc
    manifest = {
        "mediaType": media_type,
        "byteLength": len(normalized),
        "sha256": _sha256(normalized),
        "nonblank": True,
        "width": normalized_size[0],
        "height": normalized_size[1],
        "nonblankMetrics": normalized_metrics,
        "sourceInspection": {
            "detectedFormat": detected_format,
            "claimedSuffix": suffix or None,
            "byteLength": len(data),
            "sha256": _sha256(data),
            "width": original_size[0],
            "height": original_size[1],
            "nonblankMetrics": source_metrics,
        },
        "findings": findings,
        "validation": {
            "decoded": True,
            "nonblank": True,
            "magicMatchesMediaType": True,
        },
    }
    return NormalizedImageArtifact(data=normalized, manifest=manifest)


def _aabb_close(
    left: Mapping[str, Mapping[str, float]],
    right: Mapping[str, Mapping[str, float]],
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> bool:
    for axis in ("x", "y", "z"):
        left_extent = float(left["maximum"][axis]) - float(left["minimum"][axis])
        right_extent = float(right["maximum"][axis]) - float(right["minimum"][axis])
        tolerance = max(
            absolute_tolerance,
            abs(left_extent) * relative_tolerance,
            abs(right_extent) * relative_tolerance,
        )
        for endpoint in ("minimum", "maximum"):
            if abs(float(left[endpoint][axis]) - float(right[endpoint][axis])) > tolerance:
                return False
    return True


def validate_lod_set(
    lods: Mapping[str, GlbInspection],
    *,
    overview_lod: str,
    expected_aabb: Mapping[str, Mapping[str, float]] | None = None,
    maximum_automatic_asset_bytes: int = DEFAULT_MAX_GLB_BYTES,
    maximum_overview_bytes: int = DEFAULT_OVERVIEW_BYTES,
    maximum_overview_triangles: int = DEFAULT_OVERVIEW_TRIANGLES,
    bounds_absolute_tolerance: float = DEFAULT_BOUNDS_ABSOLUTE_TOLERANCE_METERS,
    bounds_relative_tolerance: float = DEFAULT_BOUNDS_RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    """Validate LOD identity, ordering, bounds consistency, and load budgets."""

    if not lods:
        raise ArtifactValidationError("lod_set_empty", "At least one LOD is required")
    parsed: list[tuple[int, str, GlbInspection]] = []
    for lod_id, inspection in lods.items():
        match = _LOD_ID_RE.fullmatch(str(lod_id))
        if match is None or not isinstance(inspection, GlbInspection):
            raise ArtifactValidationError(
                "lod_record_invalid",
                "LOD IDs must be lod0, lod1, ... and contain GLB inspections",
            )
        parsed.append((int(match.group(1)), str(lod_id), inspection))
    parsed.sort()
    if [rank for rank, _, _ in parsed] != list(range(len(parsed))):
        raise ArtifactValidationError(
            "lod_sequence_invalid",
            "LOD ranks must be contiguous starting at lod0",
        )
    if overview_lod not in lods:
        raise ArtifactValidationError(
            "lod_overview_missing",
            "The selected overview LOD is not present",
        )
    if any(
        value <= 0
        for value in (
            maximum_automatic_asset_bytes,
            maximum_overview_bytes,
            maximum_overview_triangles,
            bounds_absolute_tolerance,
            bounds_relative_tolerance,
        )
    ):
        raise ValueError("LOD limits and tolerances must be positive")
    reference = expected_aabb or parsed[0][2].aabb
    previous_triangles: int | None = None
    records: list[dict[str, Any]] = []
    hashes: set[str] = set()
    for rank, lod_id, inspection in parsed:
        if inspection.sha256 in hashes:
            raise ArtifactValidationError(
                "lod_duplicate_artifact",
                "Distinct LOD IDs may not point at identical geometry bytes",
            )
        hashes.add(inspection.sha256)
        if inspection.byte_length > maximum_automatic_asset_bytes:
            raise ArtifactValidationError(
                "lod_automatic_load_budget_exceeded",
                f"{lod_id} exceeds the automatic-load byte budget",
            )
        if not _aabb_close(
            inspection.aabb,
            reference,
            absolute_tolerance=bounds_absolute_tolerance,
            relative_tolerance=bounds_relative_tolerance,
        ):
            raise ArtifactValidationError(
                "lod_bounds_inconsistent",
                f"{lod_id} bounds are inconsistent with the render-bundle reference",
            )
        triangles = inspection.scene_triangle_count
        if previous_triangles is not None and triangles > previous_triangles:
            raise ArtifactValidationError(
                "lod_complexity_increases",
                f"{lod_id} has more visible triangles than the preceding LOD",
            )
        previous_triangles = triangles
        records.append(
            {
                "lodId": lod_id,
                "rank": rank,
                **inspection.to_manifest_dict(),
            }
        )
    overview = lods[overview_lod]
    if overview.byte_length > maximum_overview_bytes:
        raise ArtifactValidationError(
            "lod_overview_byte_budget_exceeded",
            "Overview LOD exceeds the default 10 MiB target",
        )
    if overview.scene_triangle_count > maximum_overview_triangles:
        raise ArtifactValidationError(
            "lod_overview_triangle_budget_exceeded",
            "Overview LOD exceeds the default 150k triangle target",
        )
    return {
        "lods": records,
        "overviewLod": overview_lod,
        "boundsReference": _copy_aabb(reference),
        "boundsConsistent": True,
        "budgets": {
            "maximumAutomaticAssetBytes": maximum_automatic_asset_bytes,
            "maximumOverviewBytes": maximum_overview_bytes,
            "maximumOverviewTriangles": maximum_overview_triangles,
            "withinBudget": True,
        },
    }


def build_render_bundle_manifest(
    *,
    asset_id: str,
    geometry_interface_revision: str,
    lods: Mapping[str, GlbInspection],
    overview_lod: str,
    thumbnail: NormalizedImageArtifact,
    expected_aabb: Mapping[str, Mapping[str, float]] | None = None,
    textures: Sequence[Mapping[str, Any]] = (),
    maximum_automatic_asset_bytes: int = DEFAULT_MAX_GLB_BYTES,
    maximum_overview_bytes: int = DEFAULT_OVERVIEW_BYTES,
    maximum_overview_triangles: int = DEFAULT_OVERVIEW_TRIANGLES,
) -> RenderBundleCandidate:
    """Build a canonical staged render bundle and its independent revision."""

    if (
        not isinstance(asset_id, str)
        or not asset_id
        or len(asset_id) > 128
        or not asset_id.isascii()
    ):
        raise ValueError("asset_id must be a non-empty ASCII stable identifier")
    if not _SHA256_RE.fullmatch(geometry_interface_revision):
        raise ValueError("geometry_interface_revision must be a SHA-256 digest")
    thumbnail_manifest = dict(thumbnail.manifest)
    validation = thumbnail_manifest.get("validation")
    if not isinstance(validation, Mapping) or not (
        validation.get("decoded")
        and validation.get("nonblank")
        and validation.get("magicMatchesMediaType")
    ):
        raise ArtifactValidationError(
            "thumbnail_invalid",
            "Render bundle thumbnail must be a validated nonblank web image",
        )
    lod_validation = validate_lod_set(
        lods,
        overview_lod=overview_lod,
        expected_aabb=expected_aabb,
        maximum_automatic_asset_bytes=maximum_automatic_asset_bytes,
        maximum_overview_bytes=maximum_overview_bytes,
        maximum_overview_triangles=maximum_overview_triangles,
    )
    normalized_textures: list[dict[str, Any]] = []
    for index, texture in enumerate(textures):
        if not isinstance(texture, Mapping):
            raise ArtifactValidationError(
                "render_texture_invalid",
                f"Render texture {index} must be an object",
            )
        media_type = texture.get("mediaType")
        byte_length = texture.get("byteLength")
        digest = texture.get("sha256")
        if (
            media_type not in {"image/png", "image/webp", "image/jpeg"}
            or isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length <= 0
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
        ):
            raise ArtifactValidationError(
                "render_texture_invalid",
                f"Render texture {index} lacks a valid exact identity",
            )
        normalized_textures.append(
            {
                "mediaType": media_type,
                "byteLength": byte_length,
                "sha256": digest,
            }
        )
    normalized_textures.sort(key=lambda item: (item["sha256"], item["mediaType"]))
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "documentKind": "industrial_asset_render_bundle",
        "assetId": asset_id,
        "geometryInterfaceRevision": geometry_interface_revision,
        "lodArtifacts": lod_validation["lods"],
        "overviewGeometry": {
            "lodId": overview_lod,
            "sha256": lods[overview_lod].sha256,
        },
        "thumbnail": thumbnail_manifest,
        "textures": normalized_textures,
        "validation": {
            "glb20": True,
            "finiteBounds": True,
            "boundsConsistent": lod_validation["boundsConsistent"],
            "nonblankThumbnail": True,
            "budgets": lod_validation["budgets"],
        },
        "readiness": {
            "visualReady": True,
            "blockers": [],
        },
    }
    revision = _sha256(canonical_json_bytes(manifest))
    return RenderBundleCandidate(
        manifest=manifest,
        render_bundle_revision=revision,
    )


def _render_identity(
    record: Mapping[str, Any],
    *,
    artifact_id: str,
    allowed_media_types: set[str],
) -> tuple[str, int, str]:
    media_type = record.get("mediaType")
    byte_length = record.get("byteLength")
    digest = record.get("sha256")
    if (
        media_type not in allowed_media_types
        or isinstance(byte_length, bool)
        or not isinstance(byte_length, int)
        or byte_length <= 0
        or not isinstance(digest, str)
        or _SHA256_RE.fullmatch(digest) is None
    ):
        raise ArtifactValidationError(
            "render_artifact_identity_invalid",
            f"{artifact_id} lacks a valid exact media, length, and SHA-256 identity",
        )
    return str(media_type), byte_length, digest


def _require_manifest_claim(
    record: Mapping[str, Any],
    key: str,
    actual: Any,
    *,
    artifact_id: str,
) -> None:
    if key in record and record[key] != actual:
        raise ArtifactValidationError(
            "render_artifact_claim_mismatch",
            f"{artifact_id} claim {key} does not match the staged artifact",
        )


def _validate_glb_manifest_claims(
    record: Mapping[str, Any],
    inspection: GlbInspection,
    *,
    artifact_id: str,
) -> None:
    actual = inspection.to_manifest_dict()
    for key in (
        "nonblank",
        "glbVersion",
        "declaredByteLength",
        "jsonChunkSha256",
        "binaryChunkSha256",
        "binaryChunkByteLength",
        "generator",
        "meshCount",
        "primitiveCount",
        "positionVertexCount",
        "triangleCount",
        "sceneTriangleCount",
        "aabb",
    ):
        _require_manifest_claim(
            record,
            key,
            actual[key],
            artifact_id=artifact_id,
        )
    validation = record.get("validation")
    if validation is not None:
        if not isinstance(validation, Mapping):
            raise ArtifactValidationError(
                "render_artifact_claim_invalid",
                f"{artifact_id} validation claim must be an object",
            )
        for key, value in actual["validation"].items():
            _require_manifest_claim(
                validation,
                key,
                value,
                artifact_id=artifact_id,
            )


def _inspect_exact_render_image(
    source_path: Path,
    *,
    expected_sha256: str,
    expected_byte_length: int,
    expected_media_type: str,
    artifact_id: str,
    maximum_bytes: int,
    maximum_pixels: int,
) -> dict[str, Any]:
    data, _ = _read_bounded_bytes(
        source_path,
        maximum_bytes=maximum_bytes,
        kind="render_image",
    )
    _require_expected_identity(
        data,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
        kind="render_image",
    )
    detected = detect_image_format(data)
    detected_media_type = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }.get(detected)
    if detected_media_type != expected_media_type:
        raise ArtifactValidationError(
            "render_image_media_type_mismatch",
            f"{artifact_id} bytes do not match the claimed media type",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as decoded:
                if decoded.format != detected:
                    raise ArtifactValidationError(
                        "render_image_decoder_mismatch",
                        f"{artifact_id} decoder format disagrees with its magic bytes",
                    )
                width, height = decoded.size
                if (
                    width <= 0
                    or height <= 0
                    or width * height > maximum_pixels
                ):
                    raise ArtifactValidationError(
                        "render_image_dimensions_invalid",
                        f"{artifact_id} dimensions exceed the publication budget",
                    )
                if getattr(decoded, "n_frames", 1) != 1:
                    raise ArtifactValidationError(
                        "render_image_animation_unsupported",
                        f"{artifact_id} must contain exactly one image frame",
                    )
                decoded.load()
                metrics = _image_nonblank_metrics(ImageOps.exif_transpose(decoded))
    except ArtifactValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ArtifactValidationError(
            "render_image_corrupt",
            f"{artifact_id} could not be decoded safely",
        ) from exc
    return {
        "decoded": True,
        "nonblank": True,
        "magicMatchesMediaType": True,
        "width": width,
        "height": height,
        "nonblankMetrics": metrics,
    }


def _validate_image_manifest_claims(
    record: Mapping[str, Any],
    inspection: Mapping[str, Any],
    *,
    artifact_id: str,
) -> None:
    for key in ("nonblank", "width", "height", "nonblankMetrics"):
        _require_manifest_claim(
            record,
            key,
            inspection[key],
            artifact_id=artifact_id,
        )
    validation = record.get("validation")
    if validation is not None:
        if not isinstance(validation, Mapping):
            raise ArtifactValidationError(
                "render_artifact_claim_invalid",
                f"{artifact_id} validation claim must be an object",
            )
        for key in ("decoded", "nonblank", "magicMatchesMediaType"):
            _require_manifest_claim(
                validation,
                key,
                inspection[key],
                artifact_id=artifact_id,
            )


def validate_render_artifact_sources(
    render_bundle: Mapping[str, Any],
    artifact_sources: Mapping[str, Path],
    *,
    maximum_glb_bytes: int = DEFAULT_MAX_GLB_BYTES,
    maximum_image_bytes: int = DEFAULT_MAX_IMAGE_INPUT_BYTES,
    maximum_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
) -> dict[str, dict[str, Any]]:
    """Revalidate every staged render byte before catalog publication.

    ``artifact_sources`` must contain exactly the SHA-256 identities claimed by
    the bundle. The returned SHA-256-keyed mapping is a deterministic copy
    descriptor. Its paths are copy inputs, not authorization to publish bytes
    that have changed after this validation.
    """

    if not isinstance(render_bundle, Mapping):
        raise ArtifactValidationError(
            "render_bundle_invalid",
            "Render bundle must be an object",
        )
    if (
        render_bundle.get("schemaVersion") != 1
        or render_bundle.get("documentKind")
        != "industrial_asset_render_bundle"
    ):
        raise ArtifactValidationError(
            "render_bundle_invalid",
            "Render bundle schema and document kind are invalid",
        )
    lod_records = render_bundle.get("lodArtifacts")
    thumbnail = render_bundle.get("thumbnail")
    textures = render_bundle.get("textures", [])
    if (
        not isinstance(lod_records, list)
        or not lod_records
        or not isinstance(thumbnail, Mapping)
        or not isinstance(textures, list)
    ):
        raise ArtifactValidationError(
            "render_bundle_invalid",
            "Render bundle must contain LODs, a thumbnail, and a texture list",
        )
    if (
        maximum_glb_bytes <= 0
        or maximum_image_bytes <= 0
        or maximum_image_pixels <= 0
    ):
        raise ValueError("Publication artifact limits must be positive")
    if not isinstance(artifact_sources, Mapping):
        raise ArtifactValidationError(
            "staged_artifact_sources_invalid",
            "Artifact sources must be a SHA-256-to-Path mapping",
        )

    expected_records: list[tuple[str, Mapping[str, Any]]] = []
    seen_lod_ids: set[str] = set()
    for index, record in enumerate(lod_records):
        if not isinstance(record, Mapping):
            raise ArtifactValidationError(
                "render_bundle_invalid",
                f"LOD record {index} must be an object",
            )
        lod_id = record.get("lodId")
        rank = record.get("rank")
        if (
            not isinstance(lod_id, str)
            or _LOD_ID_RE.fullmatch(lod_id) is None
            or lod_id in seen_lod_ids
            or isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank != index
            or lod_id != f"lod{index}"
        ):
            raise ArtifactValidationError(
                "render_bundle_lod_sequence_invalid",
                "LOD records must be unique and contiguous from lod0",
            )
        seen_lod_ids.add(lod_id)
        expected_records.append((f"lod:{lod_id}", record))
    expected_records.append(("thumbnail", thumbnail))
    for index, record in enumerate(textures):
        if not isinstance(record, Mapping):
            raise ArtifactValidationError(
                "render_bundle_invalid",
                f"Texture record {index} must be an object",
            )
        expected_records.append((f"texture:{index:04d}", record))

    identities: list[tuple[str, Mapping[str, Any], str, int, str]] = []
    expected_hashes: set[str] = set()
    for artifact_id, record in expected_records:
        allowed_media_types = (
            {"model/gltf-binary"}
            if artifact_id.startswith("lod:")
            else {"image/png", "image/webp", "image/jpeg"}
        )
        media_type, byte_length, digest = _render_identity(
            record,
            artifact_id=artifact_id,
            allowed_media_types=allowed_media_types,
        )
        identities.append(
            (artifact_id, record, media_type, byte_length, digest)
        )
        expected_hashes.add(digest)

    provided_hashes: set[str] = set()
    normalized_paths: dict[str, Path] = {}
    for digest, source_path in artifact_sources.items():
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise ArtifactValidationError(
                "staged_artifact_identity_invalid",
                "Staged artifact keys must be lowercase SHA-256 digests",
            )
        if not isinstance(source_path, Path):
            raise ArtifactValidationError(
                "staged_artifact_path_invalid",
                f"Staged artifact {digest} must resolve to a Path",
            )
        provided_hashes.add(digest)
        normalized_paths[digest] = source_path
    missing = sorted(expected_hashes - provided_hashes)
    if missing:
        raise ArtifactValidationError(
            "staged_artifact_missing",
            f"Staged artifact is missing for SHA-256 {missing[0]}",
        )
    extra = sorted(provided_hashes - expected_hashes)
    if extra:
        raise ArtifactValidationError(
            "staged_artifact_unclaimed",
            f"Staged artifact SHA-256 {extra[0]} is not claimed by the bundle",
        )

    validated: list[tuple[str, Path, str, int, str, Mapping[str, Any]]] = []
    lod_inspections: dict[str, GlbInspection] = {}
    for artifact_id, record, media_type, byte_length, digest in identities:
        source_path = normalized_paths[digest]
        if artifact_id.startswith("lod:"):
            inspection = inspect_glb(
                source_path,
                expected_sha256=digest,
                expected_byte_length=byte_length,
                maximum_bytes=maximum_glb_bytes,
            )
            if inspection.scene_triangle_count <= 0:
                raise ArtifactValidationError(
                    "render_glb_blank",
                    f"{artifact_id} has no visible scene triangles",
                )
            _validate_glb_manifest_claims(
                record,
                inspection,
                artifact_id=artifact_id,
            )
            lod_id = artifact_id.split(":", 1)[1]
            lod_inspections[lod_id] = inspection
            inspection_record: Mapping[str, Any] = inspection.to_manifest_dict()
        else:
            inspection_record = _inspect_exact_render_image(
                source_path,
                expected_sha256=digest,
                expected_byte_length=byte_length,
                expected_media_type=media_type,
                artifact_id=artifact_id,
                maximum_bytes=maximum_image_bytes,
                maximum_pixels=maximum_image_pixels,
            )
            _validate_image_manifest_claims(
                record,
                inspection_record,
                artifact_id=artifact_id,
            )
        validated.append(
            (
                artifact_id,
                source_path,
                media_type,
                byte_length,
                digest,
                inspection_record,
            )
        )

    overview = render_bundle.get("overviewGeometry")
    if not isinstance(overview, Mapping):
        raise ArtifactValidationError(
            "render_bundle_overview_invalid",
            "Render bundle overview geometry is missing",
        )
    overview_lod = overview.get("lodId")
    if (
        not isinstance(overview_lod, str)
        or overview_lod not in lod_inspections
        or overview.get("sha256") != lod_inspections[overview_lod].sha256
    ):
        raise ArtifactValidationError(
            "render_bundle_overview_invalid",
            "Overview geometry does not resolve to a validated LOD",
        )
    validate_lod_set(
        lod_inspections,
        overview_lod=overview_lod,
    )
    bundle_validation = render_bundle.get("validation")
    if bundle_validation is not None:
        if not isinstance(bundle_validation, Mapping):
            raise ArtifactValidationError(
                "render_bundle_claim_invalid",
                "Render bundle validation claim must be an object",
            )
        for key in (
            "glb20",
            "finiteBounds",
            "boundsConsistent",
            "nonblankThumbnail",
        ):
            if key in bundle_validation and bundle_validation[key] is not True:
                raise ArtifactValidationError(
                    "render_bundle_claim_mismatch",
                    f"Render bundle claim {key} is not satisfied",
                )
    descriptors: dict[str, dict[str, Any]] = {}
    for (
        artifact_id,
        source_path,
        media_type,
        byte_length,
        digest,
        inspection_record,
    ) in sorted(validated, key=lambda item: (item[4], item[0])):
        kind = artifact_id.split(":", 1)[0]
        existing = descriptors.get(digest)
        if existing is None:
            descriptors[digest] = {
                "sourcePath": source_path,
                "byteLength": byte_length,
                "mediaType": media_type,
                "kind": kind,
                "artifactIds": [artifact_id],
                "inspection": dict(inspection_record),
            }
            continue
        if (
            existing["sourcePath"] != source_path
            or existing["byteLength"] != byte_length
            or existing["mediaType"] != media_type
        ):
            raise ArtifactValidationError(
                "render_artifact_identity_conflict",
                f"SHA-256 {digest} has conflicting render artifact claims",
            )
        existing["artifactIds"].append(artifact_id)
        kinds = sorted(
            {
                str(existing["kind"]),
                kind,
            }
        )
        existing["kind"] = kinds[0] if len(kinds) == 1 else "shared"
    return descriptors
