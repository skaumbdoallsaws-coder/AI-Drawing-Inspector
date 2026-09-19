#!/usr/bin/env python3
"""Build a bounded GLB derivative for a dense wire-mesh guard panel."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Iterable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _append_box(
    positions: list[tuple[float, float, float]],
    normals: list[tuple[float, float, float]],
    indices: list[int],
    *,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
) -> None:
    cx, cy, cz = center
    hx, hy, hz = (value / 2.0 for value in size)
    x0, x1 = cx - hx, cx + hx
    y0, y1 = cy - hy, cy + hy
    z0, z1 = cz - hz, cz + hz
    faces = (
        ((1.0, 0.0, 0.0), ((x1, y0, z0), (x1, y1, z0),
                             (x1, y1, z1), (x1, y0, z1))),
        ((-1.0, 0.0, 0.0), ((x0, y0, z1), (x0, y1, z1),
                              (x0, y1, z0), (x0, y0, z0))),
        ((0.0, 1.0, 0.0), ((x0, y1, z0), (x0, y1, z1),
                             (x1, y1, z1), (x1, y1, z0))),
        ((0.0, -1.0, 0.0), ((x0, y0, z1), (x0, y0, z0),
                              (x1, y0, z0), (x1, y0, z1))),
        ((0.0, 0.0, 1.0), ((x0, y0, z1), (x1, y0, z1),
                             (x1, y1, z1), (x0, y1, z1))),
        ((0.0, 0.0, -1.0), ((x1, y0, z0), (x0, y0, z0),
                              (x0, y1, z0), (x1, y1, z0))),
    )
    for normal, corners in faces:
        base = len(positions)
        positions.extend(corners)
        normals.extend((normal,) * 4)
        indices.extend((base, base + 1, base + 2, base, base + 2, base + 3))


def _float_bytes(values: Iterable[tuple[float, float, float]]) -> bytes:
    flattened = (component for value in values for component in value)
    data = list(flattened)
    return struct.pack("<" + "f" * len(data), *data)


def _index_bytes(values: Iterable[int]) -> bytes:
    data = list(values)
    return struct.pack("<" + "I" * len(data), *data)


def _primitive(
    boxes: list[tuple[tuple[float, float, float], tuple[float, float, float]]]
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[int]]:
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    indices: list[int] = []
    for center, size in boxes:
        _append_box(
            positions,
            normals,
            indices,
            center=center,
            size=size,
        )
    return positions, normals, indices


def build_guard_glb(
    *,
    output: Path,
    source: Path,
    width: float,
    height: float,
    depth: float,
    frame_size: float,
    wire_size: float,
    wire_spacing: float,
) -> dict[str, object]:
    if min(width, height, depth, frame_size, wire_size, wire_spacing) <= 0:
        raise ValueError("Guard dimensions and spacing must be positive")
    if frame_size * 2.0 >= min(width, height):
        raise ValueError("Frame size leaves no interior mesh area")

    half_width = width / 2.0
    inner_width = width - frame_size * 2.0
    inner_height = height - frame_size * 2.0
    frame_boxes = [
        ((0.0, height / 2.0, -half_width + frame_size / 2.0),
         (depth, height, frame_size)),
        ((0.0, height / 2.0, half_width - frame_size / 2.0),
         (depth, height, frame_size)),
        ((0.0, frame_size / 2.0, 0.0),
         (depth, frame_size, inner_width)),
        ((0.0, height - frame_size / 2.0, 0.0),
         (depth, frame_size, inner_width)),
    ]
    mesh_boxes = []
    vertical_count = max(2, int(inner_width / wire_spacing) + 1)
    horizontal_count = max(2, int(inner_height / wire_spacing) + 1)
    for index in range(vertical_count):
        ratio = index / (vertical_count - 1)
        z = -inner_width / 2.0 + ratio * inner_width
        mesh_boxes.append((
            (0.0, height / 2.0, z),
            (wire_size, inner_height, wire_size),
        ))
    for index in range(horizontal_count):
        ratio = index / (horizontal_count - 1)
        y = frame_size + ratio * inner_height
        mesh_boxes.append((
            (0.0, y, 0.0),
            (wire_size, wire_size, inner_width),
        ))

    binary = bytearray()
    buffer_views: list[dict[str, int]] = []
    accessors: list[dict[str, object]] = []
    primitives: list[dict[str, object]] = []

    def add_view(data: bytes, target: int) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(data)
        buffer_views.append({
            "buffer": 0,
            "byteLength": len(data),
            "byteOffset": offset,
            "target": target,
        })
        return len(buffer_views) - 1

    for material_index, boxes in enumerate((frame_boxes, mesh_boxes)):
        positions, normals, indices = _primitive(boxes)
        position_view = add_view(_float_bytes(positions), 34962)
        normal_view = add_view(_float_bytes(normals), 34962)
        index_view = add_view(_index_bytes(indices), 34963)
        minimum = [min(value[axis] for value in positions) for axis in range(3)]
        maximum = [max(value[axis] for value in positions) for axis in range(3)]
        position_accessor = len(accessors)
        accessors.append({
            "bufferView": position_view,
            "componentType": 5126,
            "count": len(positions),
            "max": maximum,
            "min": minimum,
            "type": "VEC3",
        })
        normal_accessor = len(accessors)
        accessors.append({
            "bufferView": normal_view,
            "componentType": 5126,
            "count": len(normals),
            "type": "VEC3",
        })
        index_accessor = len(accessors)
        accessors.append({
            "bufferView": index_view,
            "componentType": 5125,
            "count": len(indices),
            "type": "SCALAR",
        })
        primitives.append({
            "attributes": {
                "NORMAL": normal_accessor,
                "POSITION": position_accessor,
            },
            "indices": index_accessor,
            "material": material_index,
            "mode": 4,
        })

    while len(binary) % 4:
        binary.append(0)
    source_hash = _sha256(source)
    document = {
        "accessors": accessors,
        "asset": {
            "generator": "InspectorPro wire-mesh layout derivative v1",
            "version": "2.0",
        },
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(binary)}],
        "materials": [
            {
                "doubleSided": True,
                "name": "Powder-coated steel frame",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.035, 0.045, 0.055, 1.0],
                    "metallicFactor": 0.05,
                    "roughnessFactor": 0.88,
                },
            },
            {
                "doubleSided": True,
                "name": "Powder-coated wire mesh",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.11, 0.13, 0.15, 1.0],
                    "metallicFactor": 0.05,
                    "roughnessFactor": 0.9,
                },
            },
        ],
        "meshes": [{"name": "5987T55 layout mesh", "primitives": primitives}],
        "nodes": [{"mesh": 0, "name": "Wire Mesh Machine Guard Panel 5987T55"}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "extras": {
            "visualDerivative": {
                "kind": "facility_layout_wire_mesh_guard",
                "sourceFile": source.name,
                "sourceSha256": source_hash,
            }
        },
    }
    json_bytes = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    payload = b"".join((
        struct.pack("<4sII", b"glTF", 2, total_length),
        struct.pack("<II", len(json_bytes), 0x4E4F534A),
        json_bytes,
        struct.pack("<II", len(binary), 0x004E4942),
        bytes(binary),
    ))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    evidence = {
        "schemaVersion": 1,
        "artifact": output.name,
        "artifactSha256": _sha256(output),
        "kind": "facility_layout_wire_mesh_guard",
        "sourceArtifact": source.name,
        "sourceSha256": source_hash,
        "dimensionsMeters": {
            "depth": depth,
            "height": height,
            "width": width,
        },
        "frameBoxes": len(frame_boxes),
        "meshBars": len(mesh_boxes),
        "triangleCount": sum(len(item[2]) // 3 for item in (
            _primitive(frame_boxes),
            _primitive(mesh_boxes),
        )),
    }
    output.with_suffix(".derivative.json").write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=float, default=1.450000048)
    parser.add_argument("--height", type=float, default=2.04099988)
    parser.add_argument("--depth", type=float, default=0.0454703998)
    parser.add_argument("--frame-size", type=float, default=0.035)
    parser.add_argument("--wire-size", type=float, default=0.0045)
    parser.add_argument("--wire-spacing", type=float, default=0.0508)
    args = parser.parse_args()
    evidence = build_guard_glb(
        output=args.output.resolve(),
        source=args.source.resolve(),
        width=args.width,
        height=args.height,
        depth=args.depth,
        frame_size=args.frame_size,
        wire_size=args.wire_size,
        wire_spacing=args.wire_spacing,
    )
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
