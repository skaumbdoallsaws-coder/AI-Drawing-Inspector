#!/usr/bin/env python3
"""Build a lightweight facility-layout GLB from facility_layout_semantic.json.

This is a viewport asset generator, not a replacement for detailed CAD export.
It uses SolidWorks-derived rack envelopes and component positions so the
Training tab can load the facility in 3D and highlight semantic groups.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def _pad4(data: bytes, pad: bytes = b" ") -> bytes:
    remainder = len(data) % 4
    if not remainder:
        return data
    return data + pad * (4 - remainder)


def _unit_cube_payload() -> tuple[bytes, list[dict], list[dict]]:
    # 24 vertices, 4 per face, so each face has a clean normal.
    faces = [
        # normal, four corners
        ((0, 0, 1),  [(-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)]),
        ((0, 0, -1), [(0.5, -0.5, -0.5), (-0.5, -0.5, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5)]),
        ((1, 0, 0),  [(0.5, -0.5, 0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5)]),
        ((-1, 0, 0), [(-0.5, -0.5, -0.5), (-0.5, -0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5, -0.5)]),
        ((0, 1, 0),  [(-0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5)]),
        ((0, -1, 0), [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5), (-0.5, -0.5, 0.5)]),
    ]
    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []
    for face_index, (normal, corners) in enumerate(faces):
        base = face_index * 4
        for corner in corners:
            positions.extend(corner)
            normals.extend(normal)
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])

    chunks: list[bytes] = []
    buffer_views: list[dict] = []

    pos_offset = 0
    pos_bytes = struct.pack("<" + "f" * len(positions), *positions)
    chunks.append(pos_bytes)
    buffer_views.append({"buffer": 0, "byteOffset": pos_offset, "byteLength": len(pos_bytes), "target": 34962})

    norm_offset = pos_offset + len(pos_bytes)
    norm_bytes = struct.pack("<" + "f" * len(normals), *normals)
    chunks.append(norm_bytes)
    buffer_views.append({"buffer": 0, "byteOffset": norm_offset, "byteLength": len(norm_bytes), "target": 34962})

    idx_offset = norm_offset + len(norm_bytes)
    idx_bytes = struct.pack("<" + "H" * len(indices), *indices)
    chunks.append(idx_bytes)
    buffer_views.append({"buffer": 0, "byteOffset": idx_offset, "byteLength": len(idx_bytes), "target": 34963})

    accessors = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(positions) // 3,
            "type": "VEC3",
            "min": [-0.5, -0.5, -0.5],
            "max": [0.5, 0.5, 0.5],
        },
        {
            "bufferView": 1,
            "componentType": 5126,
            "count": len(normals) // 3,
            "type": "VEC3",
        },
        {
            "bufferView": 2,
            "componentType": 5123,
            "count": len(indices),
            "type": "SCALAR",
            "min": [0],
            "max": [23],
        },
    ]
    return b"".join(chunks), buffer_views, accessors


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _vec3(data: dict | None) -> list[float]:
    data = data or {}
    return [_number(data.get("x")), _number(data.get("y")), _number(data.get("z"))]


def _rack_node(row: dict, rack: dict) -> dict:
    env = rack.get("rackEnvelopeEstimate") or {}
    center = _vec3((env.get("centerlineBoundsMeters") or {}).get("center") or rack.get("positionMeters"))
    span = env.get("centerlineSpanMeters") or {}
    x_span = max(_number(span.get("x"), 2.4), 0.15)
    y_span = max(_number(span.get("y"), 2.4), 0.15)
    z_span = max(_number(span.get("z"), 1.0), 0.15)
    return {
        "mesh": 0,
        "name": rack.get("componentName") or row.get("id") or "rack",
        "translation": center,
        "scale": [x_span, y_span, z_span],
        "extras": {
            "kind": "rack",
            "rowId": row.get("id"),
            "rowDisplayName": row.get("displayName"),
            "activeConfiguration": rack.get("activeConfiguration"),
        },
    }


def _forklift_node(asset: dict) -> dict:
    pos = _vec3(asset.get("positionMeters"))
    # Approximate envelope for layout context only.
    center = [pos[0], pos[1] + 0.65, pos[2]]
    return {
        "mesh": 0,
        "name": asset.get("componentName") or asset.get("id") or "forklift",
        "translation": center,
        "scale": [1.2, 1.3, 2.2],
        "extras": {
            "kind": asset.get("kind") or "forklift",
            "assetId": asset.get("id"),
            "displayName": asset.get("displayName"),
        },
    }


def build_glb(semantic: dict) -> bytes:
    bin_payload, buffer_views, accessors = _unit_cube_payload()
    nodes: list[dict] = []
    for row in semantic.get("rackRows") or []:
        for rack in row.get("rackInstances") or []:
            nodes.append(_rack_node(row, rack))
    for asset in semantic.get("materialHandlingAssets") or []:
        nodes.append(_forklift_node(asset))

    gltf = {
        "asset": {"version": "2.0", "generator": "InspectorPro facility_semantic_glb.py"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": [
            {
                "name": "semantic_box",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "material": 0,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "InspectorPro_gray",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.58, 0.63, 0.67, 1.0],
                    "metallicFactor": 0.25,
                    "roughnessFactor": 0.38,
                },
            }
        ],
        "buffers": [{"byteLength": len(bin_payload)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }

    json_chunk = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    bin_chunk = _pad4(bin_payload, b"\x00")
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total_length)
    json_header = struct.pack("<I4s", len(json_chunk), b"JSON")
    bin_header = struct.pack("<I4s", len(bin_chunk), b"BIN\x00")
    return header + json_header + json_chunk + bin_header + bin_chunk


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic", type=Path, default=Path("facility_layout_semantic.json"))
    parser.add_argument("--output", type=Path, default=Path("generated/training/facility-layout/Assem3_colored.glb"))
    args = parser.parse_args()

    semantic_doc = json.loads(args.semantic.read_text(encoding="utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    glb = build_glb(semantic_doc)
    args.output.write_bytes(glb)
    print(f"Wrote {args.output} ({len(glb)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
