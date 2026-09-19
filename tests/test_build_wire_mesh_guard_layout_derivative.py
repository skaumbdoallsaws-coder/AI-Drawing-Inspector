from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.build_wire_mesh_guard_layout_derivative import build_guard_glb


def _glb_document(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    magic, version, total_length = struct.unpack_from("<4sII", payload, 0)
    assert magic == b"glTF"
    assert version == 2
    assert total_length == len(payload)
    json_length, json_kind = struct.unpack_from("<II", payload, 12)
    assert json_kind == 0x4E4F534A
    return json.loads(payload[20:20 + json_length].decode("ascii"))


def test_guard_derivative_is_bounded_deterministic_and_source_bound(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dense-source.glb"
    source.write_bytes(b"deterministic dense source")
    first = tmp_path / "first.glb"
    second = tmp_path / "second.glb"
    arguments = {
        "source": source,
        "width": 1.45,
        "height": 2.041,
        "depth": 0.04547,
        "frame_size": 0.035,
        "wire_size": 0.0045,
        "wire_spacing": 0.0508,
    }

    first_evidence = build_guard_glb(output=first, **arguments)
    second_evidence = build_guard_glb(output=second, **arguments)

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence["artifactSha256"] == hashlib.sha256(
        first.read_bytes()
    ).hexdigest()
    assert first_evidence["sourceSha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
    assert first_evidence["dimensionsMeters"] == {
        "depth": 0.04547,
        "height": 2.041,
        "width": 1.45,
    }
    assert first_evidence["frameBoxes"] == 4
    assert first_evidence["meshBars"] == 67
    assert first_evidence["triangleCount"] == 852
    assert first.with_suffix(".derivative.json").is_file()
    assert second_evidence["artifactSha256"] == first_evidence["artifactSha256"]

    document = _glb_document(first)
    assert document["asset"]["generator"] == (
        "InspectorPro wire-mesh layout derivative v1"
    )
    assert document["extras"]["visualDerivative"]["sourceSha256"] == (
        first_evidence["sourceSha256"]
    )
    assert len(document["meshes"][0]["primitives"]) == 2
    assert len(document["materials"]) == 2
    assert document["buffers"][0]["byteLength"] > 0
