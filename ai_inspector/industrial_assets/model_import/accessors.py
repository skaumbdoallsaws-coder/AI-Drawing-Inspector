"""Accessor metadata is checked before numpy sees a buffer or allocates an array."""
from dataclasses import dataclass

import numpy as np

from .containers import Container
from .limits import Limits
from .validation import integer, mapping, reference, require, sequence, vector

_COMPONENTS = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
_TYPES = {"SCALAR": (1, 1), "VEC2": (1, 2), "VEC3": (1, 3), "VEC4": (1, 4),
          "MAT2": (2, 2), "MAT3": (3, 3), "MAT4": (4, 4)}


@dataclass
class Accessor:
    count: int
    kind: str
    component: int
    normalized: bool
    buffer: bytes | None
    offset: int
    stride: int
    column_stride: int
    target: int | None
    explicit_stride: bool
    local_offset: int = 0


class Accessors:
    def __init__(self, container: Container, limits: Limits):
        self.limits = limits
        document = container.document
        self.buffers = []
        raw_buffers = sequence(document.get("buffers", []), 512)
        for index, raw in enumerate(raw_buffers):
            raw = mapping(raw)
            length = integer(raw.get("byteLength"), 1, limits.zip_bytes)
            if "uri" in raw:
                data = container.resource(raw["uri"])
                require(len(data) >= length)
            else:
                require(index == 0 and container.binary is not None)
                data = container.binary
                require(length <= len(data) <= length + 3)
            self.buffers.append(memoryview(data)[:length])
        self.views = []
        for raw in sequence(document.get("bufferViews", []), limits.buffer_views):
            raw = mapping(raw)
            buffer = self.buffers[reference(raw.get("buffer"), self.buffers)]
            offset = integer(raw.get("byteOffset", 0))
            length = integer(raw.get("byteLength"), 1)
            require(offset + length <= len(buffer))
            stride = raw.get("byteStride")
            if stride is not None:
                integer(stride, 4, 252)
                require(stride % 4 == 0)
            target = raw.get("target")
            require(target is None or type(target) is int and target in (34962, 34963))
            self.views.append((buffer, offset, length, stride, target))
        self.items = []
        for raw in sequence(document.get("accessors", []), limits.accessors):
            self.items.append(self._layout(mapping(raw)))

    def _layout(self, raw: dict) -> Accessor:
        require("sparse" not in raw, "gltf_feature_unsupported")
        component = integer(raw.get("componentType"))
        kind = raw.get("type")
        require(component in _COMPONENTS and isinstance(kind, str) and kind in _TYPES)
        count = integer(raw.get("count"), 1)
        require(count <= max(self.limits.vertices, self.limits.triangles * 3), "gltf_too_complex")
        normalized = raw.get("normalized", False)
        require(type(normalized) is bool and (not normalized or component in (5120, 5121, 5122, 5123)))
        columns, rows = _TYPES[kind]
        width = np.dtype(_COMPONENTS[component]).itemsize
        column_stride = ((rows * width + 3) // 4 * 4) if columns > 1 else rows * width
        element_size = columns * column_stride
        for key in ("min", "max"):
            if key in raw:
                values = vector(raw[key], columns * rows)
                if component != 5126:
                    info = np.iinfo(np.dtype(_COMPONENTS[component]))
                    require(all(v.is_integer() and info.min <= v <= info.max for v in values))
        if "min" in raw and "max" in raw:
            require(all(a <= b for a, b in zip(raw["min"], raw["max"])))
        local = integer(raw.get("byteOffset", 0))
        require(local % width == 0)
        if "bufferView" not in raw:
            require(local == 0)
            return Accessor(count, kind, component, normalized, None, 0, element_size,
                            column_stride, None, False)
        buffer, offset, length, stride, target = self.views[reference(raw["bufferView"], self.views)]
        step = stride or element_size
        require(step >= element_size and step % width == 0 and (offset + local) % width == 0)
        # Last matrix column needs its actual components, not unused trailing padding.
        last_size = (columns - 1) * column_stride + rows * width
        require(local + (count - 1) * step + last_size <= length)
        if columns > 1:
            require((offset + local) % 4 == 0)
        return Accessor(count, kind, component, normalized, buffer, offset + local, step,
                        column_stride, target, stride is not None, local)

    def item(self, index: int) -> Accessor:
        return self.items[reference(index, self.items)]

    def read(self, index: int) -> np.ndarray:
        item = self.item(index)
        columns, rows = _TYPES[item.kind]
        dtype = np.dtype(_COMPONENTS[item.component])
        if item.buffer is None:
            values = np.zeros((item.count, columns * rows), dtype=dtype)
        else:
            values = np.ndarray((item.count, columns, rows), dtype=dtype, buffer=item.buffer,
                                offset=item.offset, strides=(item.stride, item.column_stride, dtype.itemsize))
            values = values.reshape(item.count, columns * rows)
        require(bool(np.isfinite(values).all()))
        if item.normalized:
            info = np.iinfo(dtype)
            values = values.astype(np.float64) / info.max
            if info.min < 0:
                values = np.maximum(values, -1.0)
        return values

    def attribute(self, index: int, semantic: str, quantized: bool) -> np.ndarray:
        item = self.item(index)
        require(item.target in (None, 34962))
        require(item.offset % 4 == 0 and item.local_offset % 4 == 0
                and (item.count <= 1 or item.stride % 4 == 0))
        if semantic == "POSITION":
            require(item.kind == "VEC3" and (item.component == 5126 or quantized
                    and item.component in (5120, 5121, 5122, 5123)))
        elif semantic == "NORMAL":
            require(item.kind == "VEC3" and (item.component == 5126 or quantized
                    and item.component in (5120, 5122) and item.normalized))
        elif semantic == "TEXCOORD_0":
            require(item.kind == "VEC2" and (item.component == 5126
                    or item.component in (5121, 5123) and item.normalized
                    or quantized and item.component in (5120, 5121, 5122, 5123)))
        return self.read(index)

    def index_array(self, index: int, vertex_count: int) -> np.ndarray:
        item = self.item(index)
        require(item.kind == "SCALAR" and item.component in (5121, 5123, 5125)
                and not item.normalized and not item.explicit_stride and item.target in (None, 34963))
        result = self.read(index).ravel()
        require(int(result.max()) < vertex_count)
        # glTF forbids the primitive-restart value even if a vertex exists there.
        require(int(result.max()) < np.iinfo(np.dtype(_COMPONENTS[item.component])).max)
        return result.astype(np.uint32)

    def image_bytes(self, index: int) -> bytes:
        buffer, offset, length, stride, target = self.views[reference(index, self.views)]
        require(stride is None and target is None)
        return bytes(buffer[offset:offset + length])
